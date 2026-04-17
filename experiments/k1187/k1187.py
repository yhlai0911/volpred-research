#!/usr/bin/env python3
"""
K1187: Paper 1 Table 7 (Tab:vt) VT Cross-Asset Performance — 5 Asset Canonical
================================================================================
[提出: worktree agent K1187 (Paper 1 BLOCKER), 執行: Claude]

PURPOSE: Reproduce Paper 1 Table 7 "Volatility Targeting: Cross-Asset Performance"
         — 5 assets × 5 metrics (BH Sharpe, VT Sharpe, Δ Sharpe, BH MaxDD, VT MaxDD)

Paper Table 7 (tables.tex, tab:vt):
  Asset | BH Sharpe | VT Sharpe | Δ Sharpe | BH MaxDD | VT MaxDD
  SPY   |   0.82    |   0.85    |  +0.03   | -33.7%   | -14.8%
  GLD   |   1.56    |   1.71    |  +0.15   | -25.1%   | -13.4%
  TLT   |   0.02    |   0.33    |  +0.31   | -43.8%   | -30.7%
  EEM   |   0.42    |   0.45    |  +0.03   | -38.2%   | -21.5%
  BTC   |   0.43    |   0.60    |  +0.17   | -76.6%   | -21.3%

KEY DESIGN DECISIONS (from body.tex Sec 4.5):
  SIGMA_TARGET = 10% annualized = 10/sqrt(252) daily
  SMOOTHING: 5-day moving average of GARCH sigma forecast
  WEIGHT CLIP: [0, 1.5]
  MODEL SELECTION (body.tex line ~236):
    - GJR-GARCH for assets with γ > 0.10: SPY, EEM, BTC-USD
    - GARCH(1,1) for assets with γ <= 0.10 or γ < 0: GLD, TLT
  GARCH ESTIMATION: Rolling window w=504, refit at each step
  DATA: Yahoo Finance adjusted close, 2014-2026 (body.tex: "7-16 year periods")
    - SPY: 2014-01-01 to 2026-04-17 (longer US ETF history)
    - GLD: 2014-01-01 to 2026-04-17
    - TLT: 2014-01-01 to 2026-04-17
    - EEM: 2014-01-01 to 2026-04-17
    - BTC: 2014-01-01 to 2026-04-17 (BTC available from 2014-09)
  RISK-FREE RATE: 0 (Sharpe = mean(r_vt) / std(r_vt) * sqrt(252))
    Note: body.tex says "7--16 year periods" for BH vs VT comparison;
          Table 9 (Hybrid VT) period is 2014-2026 N≈3100 days.
          We use the same period for all assets for consistency.
  BURN-IN: First w=504 trading days used for initial GARCH estimation
  seed=42

METHODOLOGY:
  1. Download adjusted close prices from Yahoo Finance
  2. Compute daily simple returns r_t = (P_t - P_{t-1}) / P_{t-1}
  3. Rolling GARCH(1,1) or GJR-GARCH(1,1) with window=504, refit each step
     (same quasi-MLE as K1188; GARCH(1,1) uses gamma=0 constraint)
  4. Forecast one-step-ahead sigma_{t+1}
  5. Smooth: sigma_smooth_{t} = mean(sigma_{t-4:t+1}) [5-day MA of sigma]
  6. VT weight: w_t = sigma_target / sigma_smooth_{t}, clipped to [0, 1.5]
  7. VT return: r_vt_{t+1} = w_t * r_{t+1}  (signal from t, return at t+1)
  8. BH: buy and hold (w=1 throughout)
  9. Metrics:
     - Sharpe: annualized = mean(r) / std(r) * sqrt(252)
     - MaxDD: minimum of cumulative product drawdown

REFERENCES:
  - Moreira & Muir (2017) JF — VT alpha from variance-return disconnect
  - Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, Van Hemert (2018) — multi-asset VT
  - Glosten, Jagannathan, Runkle (1993) — GJR-GARCH
  - Bollerslev (1986) — GARCH(1,1)
  - K1185: Paper 1 Table 4 (GARCH base methodology)
  - K1188: Paper 1 Table 8 (same GARCH estimation kernel)
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from numba import njit
from scipy.optimize import minimize

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(__file__), 'k1187_results.json')
LOG_PATH = os.path.join(os.path.dirname(__file__), 'run.log')
SEED = 42

# VT strategy parameters (body.tex Sec 4.5)
SIGMA_TARGET = 0.10 / np.sqrt(252)   # 10% annual -> daily
SMOOTH_WINDOW = 5                      # 5-day MA of sigma forecast
WEIGHT_MIN = 0.0
WEIGHT_MAX = 1.5
WINDOW_SIZE = 504                      # Rolling estimation window

# Data period
DATA_START = '2013-01-01'   # enough burn-in before 2014
DATA_END = '2026-04-17'

# Assets and model selection (γ > 0.10 -> GJR; else GARCH)
ASSETS = {
    'SPY': {'use_gjr': True,  'paper_bh_sharpe': 0.82, 'paper_vt_sharpe': 0.85,
            'paper_delta': 0.03, 'paper_bh_maxdd': -0.337, 'paper_vt_maxdd': -0.148},
    'GLD': {'use_gjr': False, 'paper_bh_sharpe': 1.56, 'paper_vt_sharpe': 1.71,
            'paper_delta': 0.15, 'paper_bh_maxdd': -0.251, 'paper_vt_maxdd': -0.134},
    'TLT': {'use_gjr': False, 'paper_bh_sharpe': 0.02, 'paper_vt_sharpe': 0.33,
            'paper_delta': 0.31, 'paper_bh_maxdd': -0.438, 'paper_vt_maxdd': -0.307},
    'EEM': {'use_gjr': True,  'paper_bh_sharpe': 0.42, 'paper_vt_sharpe': 0.45,
            'paper_delta': 0.03, 'paper_bh_maxdd': -0.382, 'paper_vt_maxdd': -0.215},
    'BTC-USD': {'use_gjr': True,  'paper_bh_sharpe': 0.43, 'paper_vt_sharpe': 0.60,
                'paper_delta': 0.17, 'paper_bh_maxdd': -0.766, 'paper_vt_maxdd': -0.213},
}

RTOL = 0.05   # 5% relative tolerance


# ================================================================
# GARCH(1,1) filter (numba-accelerated)
# ================================================================

@njit(cache=True)
def garch_filter(r, omega, alpha, beta):
    """GARCH(1,1): h_t = omega + alpha*r^2_{t-1} + beta*h_{t-1}"""
    T = len(r)
    h = np.empty(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i] ** 2
    var_r /= T
    h[0] = var_r
    for t in range(1, T):
        h[t] = omega + alpha * r[t - 1] ** 2 + beta * h[t - 1]
        if h[t] < 1e-12:
            h[t] = 1e-12
    return h


# ================================================================
# GJR-GARCH(1,1) filter (numba-accelerated)
# ================================================================

@njit(cache=True)
def gjr_garch_filter(r, omega, alpha, gamma, beta):
    """GJR-GARCH(1,1): h_t = omega + (alpha + gamma*I_{r<0})*r^2_{t-1} + beta*h_{t-1}"""
    T = len(r)
    h = np.empty(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i] ** 2
    var_r /= T
    h[0] = var_r
    for t in range(1, T):
        ind_neg = 1.0 if r[t - 1] < 0.0 else 0.0
        h[t] = (omega
                + (alpha + gamma * ind_neg) * r[t - 1] ** 2
                + beta * h[t - 1])
        if h[t] < 1e-12:
            h[t] = 1e-12
    return h


# ================================================================
# GARCH(1,1) estimation (quasi-MLE)
# ================================================================

def fit_garch(returns, n_starts=5):
    """Fit GARCH(1,1) via quasi-MLE. Returns [omega, alpha, beta]."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 100:
        return None
    rv = float(np.var(r))
    if rv <= 0:
        rv = 1e-6

    def negll(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0:
            return 1e10
        if alpha + beta >= 1.0:
            return 1e10
        h = garch_filter(r, omega, alpha, beta)
        ll = -0.5 * np.sum(np.log(h[1:]) + r[1:] ** 2 / h[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for s in range(n_starts):
        np.random.seed(SEED + 200 + s)
        a0 = np.clip(0.08 + 0.03 * np.random.randn(), 0.01, 0.2)
        b0 = np.clip(0.88 + 0.02 * np.random.randn(), 0.5, 0.97)
        if a0 + b0 >= 0.99:
            b0 = 0.97 - a0
            b0 = max(b0, 0.5)
        o0 = max(1e-8, rv * (1.0 - a0 - b0))

        res = minimize(
            negll,
            [o0, a0, b0],
            method='L-BFGS-B',
            bounds=[(1e-10, None), (0, 0.5), (0, 0.999)],
            options={'maxiter': 4000, 'ftol': 1e-12, 'gtol': 1e-8}
        )
        if res.fun < best_nll and np.isfinite(res.fun):
            best_nll, best = res.fun, res

    if best is None:
        return None
    o, a, b = best.x
    if a + b >= 1.0:
        return None
    return best.x  # [omega, alpha, beta]


# ================================================================
# GJR-GARCH(1,1) estimation (quasi-MLE)
# ================================================================

def fit_gjr_garch(returns, n_starts=5):
    """Fit GJR-GARCH(1,1) via quasi-MLE. Returns [omega, alpha, gamma, beta]."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 100:
        return None
    rv = float(np.var(r))
    if rv <= 0:
        rv = 1e-6

    def negll(params):
        omega, alpha, gamma, beta = params
        if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
            return 1e10
        if alpha + gamma / 2.0 + beta >= 1.0:
            return 1e10
        h = gjr_garch_filter(r, omega, alpha, gamma, beta)
        ll = -0.5 * np.sum(np.log(h[1:]) + r[1:] ** 2 / h[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for s in range(n_starts):
        np.random.seed(SEED + 100 + s)
        a0 = np.clip(0.06 + 0.03 * np.random.randn(), 0.01, 0.2)
        g0 = np.clip(0.05 + 0.02 * np.random.randn(), 0.01, 0.2)
        b0 = np.clip(0.88 + 0.02 * np.random.randn(), 0.5, 0.97)
        if a0 + g0 / 2.0 + b0 >= 0.99:
            b0 = 0.97 - a0 - g0 / 2.0
            b0 = max(b0, 0.5)
        o0 = max(1e-8, rv * (1.0 - a0 - g0 / 2.0 - b0))

        res = minimize(
            negll,
            [o0, a0, g0, b0],
            method='L-BFGS-B',
            bounds=[(1e-10, None), (0, 0.5), (0, 0.5), (0, 0.999)],
            options={'maxiter': 4000, 'ftol': 1e-12, 'gtol': 1e-8}
        )
        if res.fun < best_nll and np.isfinite(res.fun):
            best_nll, best = res.fun, res

    if best is None:
        return None
    o, a, g, b = best.x
    if a + g / 2.0 + b >= 1.0:
        return None
    return best.x  # [omega, alpha, gamma, beta]


# ================================================================
# One-step-ahead forecast
# ================================================================

def forecast_sigma(r_train, use_gjr):
    """One-step-ahead sigma forecast (daily std)."""
    r = np.ascontiguousarray(r_train, dtype=np.float64)
    if use_gjr:
        params = fit_gjr_garch(r)
        if params is None:
            params_g = fit_garch(r)
            if params_g is None:
                return float(np.std(r_train))
            omega, alpha, beta = params_g
            h = garch_filter(r, omega, alpha, beta)
            h_next = omega + alpha * r[-1] ** 2 + beta * h[-1]
            return float(np.sqrt(max(h_next, 1e-12)))
        omega, alpha, gamma, beta = params
        h = gjr_garch_filter(r, omega, alpha, gamma, beta)
        ind_neg = 1.0 if r[-1] < 0.0 else 0.0
        h_next = omega + (alpha + gamma * ind_neg) * r[-1] ** 2 + beta * h[-1]
        return float(np.sqrt(max(h_next, 1e-12)))
    else:
        params = fit_garch(r)
        if params is None:
            return float(np.std(r_train))
        omega, alpha, beta = params
        h = garch_filter(r, omega, alpha, beta)
        h_next = omega + alpha * r[-1] ** 2 + beta * h[-1]
        return float(np.sqrt(max(h_next, 1e-12)))


# ================================================================
# Performance metrics
# ================================================================

def sharpe_ratio(returns, annualize=252):
    """Annualized Sharpe ratio (rf=0)."""
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if len(r) < 2 or np.std(r) == 0:
        return np.nan
    return float(np.mean(r) / np.std(r, ddof=1) * np.sqrt(annualize))


def max_drawdown(returns):
    """Maximum drawdown from cumulative returns."""
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return np.nan
    cum = np.cumprod(1.0 + r)
    running_max = np.maximum.accumulate(cum)
    dd = cum / running_max - 1.0
    return float(np.min(dd))


# ================================================================
# VT backtest for one asset
# ================================================================

def run_vt_backtest(ticker, use_gjr, log_fn):
    """
    Download data, run rolling GARCH VT backtest.
    Returns dict with BH and VT metrics.
    """
    log_fn(f"  [{ticker}] Downloading {DATA_START} to {DATA_END} ...")
    data = yf.download(ticker, start=DATA_START, end=DATA_END,
                       auto_adjust=True, progress=False)
    if data is None or len(data) < WINDOW_SIZE + 100:
        log_fn(f"  [{ticker}] ERROR: insufficient data ({len(data) if data is not None else 0} rows)")
        return None

    if isinstance(data.columns, pd.MultiIndex):
        close = data['Close'][ticker] if ticker in data['Close'].columns else data['Close'].iloc[:, 0]
    else:
        close = data['Close']

    close = close.dropna()
    returns = close.pct_change().dropna()
    log_fn(f"  [{ticker}] {len(returns)} daily returns ({returns.index[0].date()} to {returns.index[-1].date()})")

    r = returns.values.astype(np.float64)
    dates = returns.index

    # Rolling forecast
    T = len(r)
    sigma_forecast = np.full(T, np.nan)

    log_fn(f"  [{ticker}] Running rolling GARCH (w={WINDOW_SIZE}, n_steps={T - WINDOW_SIZE}) ...")
    t_start = time.time()

    for t in range(WINDOW_SIZE, T):
        r_train = r[t - WINDOW_SIZE:t]
        sigma_forecast[t] = forecast_sigma(r_train, use_gjr)

        if (t - WINDOW_SIZE) % 500 == 0 and t > WINDOW_SIZE:
            elapsed = time.time() - t_start
            pct = (t - WINDOW_SIZE) / (T - WINDOW_SIZE) * 100
            log_fn(f"  [{ticker}] {pct:.0f}% done ({elapsed:.1f}s)")

    elapsed = time.time() - t_start
    log_fn(f"  [{ticker}] Rolling done in {elapsed:.1f}s")

    # Smooth sigma: 5-day MA
    sigma_smooth = np.full(T, np.nan)
    for t in range(T):
        if np.isnan(sigma_forecast[t]):
            continue
        # Use up to 5 most recent non-NaN forecasts including current
        start_sm = max(0, t - SMOOTH_WINDOW + 1)
        window_vals = sigma_forecast[start_sm:t + 1]
        valid_vals = window_vals[~np.isnan(window_vals)]
        if len(valid_vals) >= 1:
            sigma_smooth[t] = np.mean(valid_vals)

    # VT weight: w_t = sigma_target / sigma_smooth_t
    # Signal at t (using sigma from training up to t), return at t+1
    vt_returns = np.full(T, np.nan)
    bh_returns = np.full(T, np.nan)

    for t in range(WINDOW_SIZE, T - 1):  # forecast t, return at t+1
        if np.isnan(sigma_smooth[t]) or sigma_smooth[t] <= 0:
            continue
        w = SIGMA_TARGET / sigma_smooth[t]
        w = np.clip(w, WEIGHT_MIN, WEIGHT_MAX)
        vt_returns[t + 1] = w * r[t + 1]
        bh_returns[t + 1] = r[t + 1]

    # Trim to VT active period
    active_mask = ~np.isnan(vt_returns)
    r_vt = vt_returns[active_mask]
    r_bh = bh_returns[active_mask]

    n_obs = len(r_vt)
    log_fn(f"  [{ticker}] VT active period: {n_obs} days "
           f"({dates[active_mask][0].date()} to {dates[active_mask][-1].date()})")

    bh_sh = sharpe_ratio(r_bh)
    vt_sh = sharpe_ratio(r_vt)
    bh_dd = max_drawdown(r_bh)
    vt_dd = max_drawdown(r_vt)
    delta_sh = round(vt_sh - bh_sh, 2) if np.isfinite(vt_sh) and np.isfinite(bh_sh) else np.nan

    log_fn(f"  [{ticker}] BH Sharpe={bh_sh:.2f}, VT Sharpe={vt_sh:.2f}, "
           f"Δ={delta_sh:+.2f}, BH MDD={bh_dd:.1%}, VT MDD={vt_dd:.1%}")

    return {
        'ticker': ticker,
        'use_gjr': use_gjr,
        'n_obs': int(n_obs),
        'data_start': str(dates[active_mask][0].date()),
        'data_end': str(dates[active_mask][-1].date()),
        'bh_sharpe': float(round(bh_sh, 2)),
        'vt_sharpe': float(round(vt_sh, 2)),
        'delta_sharpe': float(round(delta_sh, 2)) if np.isfinite(delta_sh) else None,
        'bh_maxdd': float(round(bh_dd * 100, 1)) / 100,  # keep as decimal
        'vt_maxdd': float(round(vt_dd * 100, 1)) / 100,
        'bh_sharpe_raw': float(bh_sh),
        'vt_sharpe_raw': float(vt_sh),
        'bh_maxdd_raw': float(bh_dd),
        'vt_maxdd_raw': float(vt_dd),
    }


# ================================================================
# Match comparison
# ================================================================

def check_match(computed, paper, metric_name, rtol=RTOL):
    """Check if computed value matches paper within tolerance."""
    if computed is None or np.isnan(computed):
        return 'MISSING', None
    delta = abs(computed - paper)
    if abs(paper) > 1e-6:
        rel_delta = delta / abs(paper)
    else:
        rel_delta = delta
    if rel_delta <= rtol:
        return 'MATCHED', rel_delta
    else:
        return 'DIVERGED', rel_delta


# ================================================================
# Main
# ================================================================

def main():
    t0 = time.time()
    log_lines = []

    def log_fn(msg):
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        log_lines.append(line)

    log_fn("=" * 70)
    log_fn("K1187: Paper 1 Table 7 VT Cross-Asset Performance")
    log_fn(f"SEED={SEED}, SIGMA_TARGET={SIGMA_TARGET:.6f}/day ({SIGMA_TARGET * np.sqrt(252):.2%}/yr)")
    log_fn(f"WINDOW={WINDOW_SIZE}, SMOOTH={SMOOTH_WINDOW}, WEIGHT_CLIP=[{WEIGHT_MIN},{WEIGHT_MAX}]")
    log_fn("=" * 70)

    results = {}
    all_matches = []

    # Run backtest for each asset
    for ticker, cfg in ASSETS.items():
        log_fn(f"\n[{ticker}] use_gjr={cfg['use_gjr']}")
        res = run_vt_backtest(ticker, cfg['use_gjr'], log_fn)

        if res is None:
            log_fn(f"  [{ticker}] FAILED to compute")
            results[ticker] = {'error': 'computation failed'}
            continue

        # Compare with paper
        paper_key = 'BTC' if ticker == 'BTC-USD' else ticker
        paper_vals = {
            'bh_sharpe': cfg['paper_bh_sharpe'],
            'vt_sharpe': cfg['paper_vt_sharpe'],
            'bh_maxdd': cfg['paper_bh_maxdd'],
            'vt_maxdd': cfg['paper_vt_maxdd'],
        }

        match_results = {}
        for metric, paper_val in paper_vals.items():
            computed_val = res[metric]
            status, rel_delta = check_match(computed_val, paper_val, metric)
            match_results[metric] = {
                'paper': paper_val,
                'computed': computed_val,
                'status': status,
                'rel_delta': float(rel_delta) if rel_delta is not None else None,
            }
            all_matches.append(status == 'MATCHED')
            log_fn(f"  [{ticker}] {metric}: paper={paper_val}, computed={computed_val}, "
                   f"status={status}, rdelta={rel_delta:.3f}" if rel_delta is not None
                   else f"  [{ticker}] {metric}: MISSING")

        res['match'] = match_results
        results[ticker] = res

    # Summary
    total_metrics = len(all_matches)
    matched = sum(all_matches)
    log_fn(f"\n{'=' * 70}")
    log_fn(f"SUMMARY: {matched}/{total_metrics} metrics matched (rtol={RTOL})")
    log_fn(f"Elapsed: {time.time() - t0:.1f}s")

    # Save results
    output = {
        'experiment': 'K1187',
        'purpose': 'Paper 1 Table 7 (Tab:vt) VT Cross-Asset Performance Reproduction',
        'run_date': datetime.now(timezone.utc).isoformat(),
        'parameters': {
            'seed': SEED,
            'sigma_target_annual': 0.10,
            'sigma_target_daily': float(SIGMA_TARGET),
            'smooth_window': SMOOTH_WINDOW,
            'weight_min': WEIGHT_MIN,
            'weight_max': WEIGHT_MAX,
            'garch_window': WINDOW_SIZE,
            'rtol': RTOL,
        },
        'paper_table7': {
            'SPY':  {'bh_sharpe': 0.82, 'vt_sharpe': 0.85, 'delta': 0.03, 'bh_maxdd': -0.337, 'vt_maxdd': -0.148},
            'GLD':  {'bh_sharpe': 1.56, 'vt_sharpe': 1.71, 'delta': 0.15, 'bh_maxdd': -0.251, 'vt_maxdd': -0.134},
            'TLT':  {'bh_sharpe': 0.02, 'vt_sharpe': 0.33, 'delta': 0.31, 'bh_maxdd': -0.438, 'vt_maxdd': -0.307},
            'EEM':  {'bh_sharpe': 0.42, 'vt_sharpe': 0.45, 'delta': 0.03, 'bh_maxdd': -0.382, 'vt_maxdd': -0.215},
            'BTC':  {'bh_sharpe': 0.43, 'vt_sharpe': 0.60, 'delta': 0.17, 'bh_maxdd': -0.766, 'vt_maxdd': -0.213},
        },
        'results': results,
        'summary': {
            'total_metrics': total_metrics,
            'matched': matched,
            'match_rate': float(matched) / total_metrics if total_metrics > 0 else 0.0,
            'elapsed_seconds': float(time.time() - t0),
        }
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    log_fn(f"Results saved to {RESULTS_PATH}")

    # Save log
    with open(LOG_PATH, 'w') as f:
        f.write('\n'.join(log_lines))
    log_fn(f"Log saved to {LOG_PATH}")

    return output


if __name__ == '__main__':
    np.random.seed(SEED)
    result = main()
    matched = result['summary']['matched']
    total = result['summary']['total_metrics']
    print(f"\nFINAL: {matched}/{total} metrics matched")
    sys.exit(0 if matched > 0 else 1)
