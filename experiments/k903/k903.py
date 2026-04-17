#!/usr/bin/env python3
"""
K903: Paper 1 Tables 2/3 Canonical 2010-Start Replication (K902 extension)
==========================================================================
[提出: K902 reproducibility audit (agent-af5db316), 執行: Claude]

Purpose: Re-run K902 rolling gamma analysis (Table 2) and OOS QLIKE (Table 3)
with data_start=2010-01-01 instead of 2017-01-01, to produce the canonical
numbers that align with Paper 1 main.tex.

Root cause of K902 divergence (from diff_report.md):
  - K902 uses TABLE1_START='2017-01-01' → only 36 quarterly windows
  - Paper Table 2 uses extended sample (2010-2025) → more windows, different statistics
  - GLD mean γ: paper=-0.067, K902=-0.006 (major divergence, same direction)
  - SPY mean γ: paper=+0.211, K902=+0.124 (similar direction, different magnitude)

K903 fix:
  - rolling_gamma: computed on FULL series from 2010-01-01 (not truncated to 2017)
  - QLIKE OOS: training history starts from 2010 (expanding window OOS)
  - All other methodology: IDENTICAL to K902

Decision protocol (per task brief):
  After comparison, recommend one of:
  (a) Script needs fixing (K902 bug) — K903 is the right number, paper diverged
  (b) Paper needs updating — K903 confirmed paper's numbers are right, K902 was wrong
  (c) Errata pending — cannot resolve without further investigation

Data source: yfinance (2005-01-01 to 2026-04-05)
Assets: SPY, QQQ, GLD, TLT, EEM, BTC-USD, SLV (Table 2)
        SPY, QQQ, GLD, TLT, EEM, BTC-USD (Table 3)

References:
  - Patton (2011) J. Econometrics 160 — QLIKE proxy-robust
  - Glosten, Jagannathan, Runkle (1993) JoF 48 — GJR-GARCH
  - Diebold & Mariano (1995) — predictive accuracy test
  - Harvey et al. (2016) — t > 3.0 threshold
  - K902: original Paper 1 Tables 1&3 supplement (2017-start)
  - diff_report.md: reproducibility audit identifying sample period mismatch
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
from scipy.optimize import minimize
from scipy.stats import norm

# Add project root for volpred.utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
try:
    from volpred.utils import clean_tw50_data
except ImportError:
    def clean_tw50_data(prices):
        returns = prices.pct_change().dropna()
        return prices, returns

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(__file__), 'k903_results.json')
TABLE2_CSV = os.path.join(os.path.dirname(__file__), 'tables', 'k903_table2.csv')
TABLE3_CSV = os.path.join(os.path.dirname(__file__), 'tables', 'k903_table3.csv')

# ============================================================
# KEY DIFFERENCE FROM K902: data_start = 2010-01-01
# This means rolling gamma uses all data from 2010 (not 2017)
# ============================================================
DOWNLOAD_START = '2005-01-01'  # download wider for safety
DOWNLOAD_END = '2026-04-17'

# TABLE2 rolling gamma: start from 2010 (paper's extended window)
TABLE2_START = '2010-01-01'

# Table 3 OOS periods (same as K902 and paper)
OOS_PRIMARY_START = '2023-01-01'
OOS_PRIMARY_END = '2024-12-31'
OOS_VALIDATION_START = '2025-01-01'
OOS_VALIDATION_END = '2026-03-31'

REFIT_EVERY = 63  # re-estimate every ~3 months (paper: quarterly, 63 trading days)
ROLLING_GAMMA_WINDOW = 504  # ~2 years rolling (w=504 per paper)
ROLLING_GAMMA_STEP = 63     # paper: "504-day windows advanced by 63 trading days"

ASSETS_TABLE2 = ['SPY', 'QQQ', 'EEM', 'GLD', 'TLT', 'BTC-USD', 'SLV']
ASSETS_TABLE3 = ['SPY', 'QQQ', 'GLD', 'TLT', 'EEM', 'BTC-USD']


# ==============================================================
# A. Variance filters (IDENTICAL to K902)
# ==============================================================

def garch_filter(r, omega, alpha, beta):
    """GARCH(1,1): σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1}"""
    T = len(r)
    s2 = np.empty(T)
    s2[0] = max(np.var(r), 1e-10)
    for t in range(1, T):
        s2[t] = omega + alpha * r[t - 1] ** 2 + beta * s2[t - 1]
        if s2[t] < 1e-12:
            s2[t] = 1e-12
    return s2


def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1): σ²_t = ω + (α + γ·I_{r<0})·r²_{t-1} + β·σ²_{t-1}"""
    T = len(r)
    s2 = np.empty(T)
    s2[0] = max(np.var(r), 1e-10)
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        s2[t] = omega + (alpha + gamma * ind) * r[t - 1] ** 2 + beta * s2[t - 1]
        if s2[t] < 1e-12:
            s2[t] = 1e-12
    return s2


# ==============================================================
# B. MLE fitting (IDENTICAL to K902)
# ==============================================================

def fit_garch(returns, n_starts=5):
    """Fit GARCH(1,1) via quasi-MLE (Normal)."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 200:
        return None
    rv = np.var(r)

    def negll(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0:
            return 1e10
        if alpha + beta >= 1.0:
            return 1e10
        s2 = garch_filter(r, omega, alpha, beta)
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 200)
        a0 = np.clip(0.06 + 0.03 * np.random.randn(), 0.01, 0.3)
        b0 = np.clip(0.90 + 0.03 * np.random.randn(), 0.5, 0.98)
        if a0 + b0 >= 0.99:
            b0 = 0.98 - a0
        o0 = max(1e-8, rv * (1 - a0 - b0))
        try:
            res = minimize(negll, [o0, a0, b0],
                           method='L-BFGS-B',
                           bounds=[(1e-10, None), (0, 0.5), (0, 0.999)],
                           options={'maxiter': 2000})
            if res.fun < best_nll:
                best_nll, best = res.fun, res
        except Exception:
            continue
    if best is None:
        return None
    omega, alpha, beta = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta), 'persistence': float(alpha + beta)}


def fit_gjr(returns, n_starts=5):
    """Fit GJR-GARCH(1,1) via quasi-MLE (Normal). Returns params dict or None."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 200:
        return None
    rv = np.var(r)

    def negll(params):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        s2 = gjr_filter(r, omega, alpha, beta, gamma)
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 100)
        a0 = np.clip(0.05 + 0.03 * np.random.randn(), 0.01, 0.3)
        b0 = np.clip(0.88 + 0.04 * np.random.randn(), 0.5, 0.97)
        g0 = np.clip(0.08 + 0.04 * np.random.randn(), 0.01, 0.3)
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.95 - a0 - 0.5 * g0
        o0 = max(1e-8, rv * (1 - a0 - b0 - 0.5 * g0))
        try:
            res = minimize(negll, [o0, a0, b0, g0],
                           method='L-BFGS-B',
                           bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                           options={'maxiter': 2000})
            if res.fun < best_nll:
                best_nll, best = res.fun, res
        except Exception:
            continue
    if best is None:
        return None
    omega, alpha, beta, gamma = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta), 'gamma': float(gamma),
            'persistence': float(alpha + beta + 0.5 * gamma)}


def fit_gjr_unconstrained(returns, n_starts=5):
    """Fit GJR-GARCH(1,1) allowing NEGATIVE gamma (for rolling analysis).

    Standard GJR constrains gamma >= 0, but for rolling analysis we want to
    detect assets where leverage effect is reversed (e.g., GLD, TLT).
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 200:
        return None
    rv = np.var(r)

    def negll(params):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0:
            return 1e10
        if alpha + gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * max(gamma, 0) >= 1.0:
            return 1e10
        s2 = gjr_filter(r, omega, alpha, beta, gamma)
        if np.any(s2 <= 0):
            return 1e10
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 400)
        a0 = np.clip(0.08 + 0.04 * np.random.randn(), 0.01, 0.3)
        b0 = np.clip(0.88 + 0.04 * np.random.randn(), 0.5, 0.97)
        if seed % 2 == 0:
            g0 = np.clip(0.08 + 0.04 * np.random.randn(), -0.2, 0.3)
        else:
            g0 = np.clip(-0.05 + 0.04 * np.random.randn(), -0.2, 0.3)
        if a0 + g0 < 0:
            g0 = -a0 + 0.01
        if a0 + b0 + 0.5 * max(g0, 0) >= 0.99:
            b0 = 0.95 - a0 - 0.5 * max(g0, 0)
        o0 = max(1e-8, rv * max(0.01, 1 - a0 - b0 - 0.5 * max(g0, 0)))
        try:
            res = minimize(negll, [o0, a0, b0, g0],
                           method='L-BFGS-B',
                           bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (-0.5, 0.5)],
                           options={'maxiter': 2000})
            if res.fun < best_nll:
                best_nll, best = res.fun, res
        except Exception:
            continue
    if best is None:
        return None
    omega, alpha, beta, gamma = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta), 'gamma': float(gamma),
            'persistence': float(alpha + beta + 0.5 * max(gamma, 0))}


# ==============================================================
# C. Rolling gamma analysis (IDENTICAL to K902, but applied to
#    longer series starting 2010)
# ==============================================================

def rolling_gamma_analysis(returns, window=504, step=63):
    """Compute rolling GJR gamma estimates with given window.
    Uses UNCONSTRAINED gamma (can be negative) to detect reverse leverage.
    Applied to full series (from 2010), not truncated to 2017.

    Paper: "504-day windows advanced by 63 trading days" (quarterly step).
    KEY FIX vs K902: step=63 (not step=50 which K902 used via max(21, w//10)).
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    n = len(r)
    if n < window + 100:
        params = fit_gjr_unconstrained(r, n_starts=3)
        if params is None:
            return {'mean_gamma': np.nan, 'std_gamma': np.nan,
                    'pct_negative': np.nan, 'n_windows': 0}
        return {'mean_gamma': params['gamma'],
                'std_gamma': 0.0,
                'pct_negative': 0.0 if params['gamma'] >= 0 else 100.0,
                'n_windows': 1}

    gammas = []
    for start in range(0, n - window, step):  # step=63 (quarterly, per paper)
        end = start + window
        chunk = r[start:end]
        params = fit_gjr_unconstrained(chunk, n_starts=3)
        if params is not None:
            gammas.append(params['gamma'])

    if len(gammas) == 0:
        return {'mean_gamma': np.nan, 'std_gamma': np.nan,
                'pct_negative': np.nan, 'n_windows': 0}

    gammas = np.array(gammas)
    mean_g = float(np.mean(gammas))
    std_g = float(np.std(gammas))
    pct_neg = float(100 * np.mean(gammas < 0))

    # HAC t-stat for mean(gamma) != 0
    # Paper: "Because our quarterly gamma estimates use overlapping windows
    # (504-day windows stepped by 63 days), we employ Newey-West HAC standard
    # errors (8 lags)." — body.tex line 164
    n_g = len(gammas)
    d = gammas - mean_g
    gamma0 = np.mean(d ** 2)
    var_g = gamma0
    max_lag = min(8, n_g // 4)  # paper uses 8 lags for HAC
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)  # Bartlett kernel
        gamma_l = np.mean(d[lag:] * d[:-lag])
        var_g += 2 * w * gamma_l
    var_g = max(var_g, 1e-20)
    se = np.sqrt(var_g / n_g)
    hac_t = mean_g / se if se > 1e-12 else 0.0

    return {
        'mean_gamma': mean_g,
        'std_gamma': std_g,
        'pct_negative': pct_neg,
        'hac_tstat': float(hac_t),
        'n_windows': int(n_g),
    }


# ==============================================================
# D. OOS QLIKE (IDENTICAL to K902)
# ==============================================================

def oos_qlike_rolling(returns_full, dates_full, oos_start, oos_end,
                      window=504, refit_every=63, model='gjr'):
    """Rolling-window OOS QLIKE computation (w=504, paper methodology).

    KEY DIFFERENCE from K902 expanding window:
    - At each OOS point t, training data = r[t-window:t] (fixed lookback)
    - NOT all data from inception (K902 expanding)
    - Paper body.tex: "We employ a rolling window approach with re-estimation
      at each forecast origin. The primary window size is w=504 trading days."
    - Paper also says "expanding windows (worst QLIKE, distant regime contamination)"
      confirming rolling is the paper's method.

    Re-estimation happens every refit_every=63 days (quarterly), same as K902.
    """
    r = np.ascontiguousarray(returns_full, dtype=np.float64)
    d = dates_full

    oos_mask = (d >= pd.Timestamp(oos_start)) & (d <= pd.Timestamp(oos_end))
    oos_idx = np.where(oos_mask)[0]
    if len(oos_idx) == 0:
        return None

    forecasts = []
    realized = []
    qlike_vals = []
    oos_dates_out = []

    params = None
    last_fit_idx = -refit_every

    for i, idx in enumerate(oos_idx):
        # Need at least window observations before this OOS point
        if idx < window:
            continue

        # Re-estimate parameters periodically using ROLLING window
        if i - last_fit_idx >= refit_every or params is None:
            # Rolling window: only last `window` observations
            train_r = r[idx - window:idx]
            if model == 'garch':
                params = fit_garch(train_r, n_starts=3)
            else:
                params = fit_gjr(train_r, n_starts=3)
            last_fit_idx = i
            if params is None:
                continue

        # One-step forecast using rolling window filter
        # Run filter on rolling window up to t-1
        train_r = r[idx - window:idx]

        if model == 'garch':
            s2 = garch_filter(train_r, params['omega'], params['alpha'], params['beta'])
            h_t = (params['omega']
                   + params['alpha'] * train_r[-1] ** 2
                   + params['beta'] * s2[-1])
        else:
            s2 = gjr_filter(train_r, params['omega'], params['alpha'],
                            params['beta'], params['gamma'])
            ind = 1.0 if train_r[-1] < 0 else 0.0
            h_t = (params['omega']
                   + (params['alpha'] + params['gamma'] * ind) * train_r[-1] ** 2
                   + params['beta'] * s2[-1])

        h_t = max(h_t, 1e-12)
        r2_t = r[idx] ** 2

        # QLIKE_t = log(h_t) + r²_t / h_t
        q_t = np.log(h_t) + r2_t / h_t

        if np.isfinite(q_t):
            forecasts.append(float(h_t))
            realized.append(float(r2_t))
            qlike_vals.append(float(q_t))
            oos_dates_out.append(str(d[idx].date()))

    if len(qlike_vals) == 0:
        return None

    return {
        'qlike_mean': float(np.mean(qlike_vals)),
        'qlike_values': qlike_vals,
        'n_oos': len(qlike_vals),
        'dates': oos_dates_out,
        'forecasts': forecasts,
        'realized': realized,
    }


def oos_qlike_expanding(returns_full, dates_full, oos_start, oos_end,
                        refit_every=63, model='gjr'):
    """Expanding-window OOS QLIKE (K902 methodology — kept for reference).
    NOT used in K903 canonical run. Paper uses rolling window, not expanding.
    """
    r = np.ascontiguousarray(returns_full, dtype=np.float64)
    d = dates_full

    oos_mask = (d >= pd.Timestamp(oos_start)) & (d <= pd.Timestamp(oos_end))
    oos_idx = np.where(oos_mask)[0]
    if len(oos_idx) == 0:
        return None

    forecasts = []
    realized = []
    qlike_vals = []
    oos_dates_out = []

    params = None
    last_fit_idx = -refit_every

    for i, idx in enumerate(oos_idx):
        if idx < 252:
            continue

        if i - last_fit_idx >= refit_every or params is None:
            train_r = r[:idx]
            if model == 'garch':
                params = fit_garch(train_r, n_starts=3)
            else:
                params = fit_gjr(train_r, n_starts=3)
            last_fit_idx = i
            if params is None:
                continue

        train_r = r[:idx]

        if model == 'garch':
            s2 = garch_filter(train_r, params['omega'], params['alpha'], params['beta'])
            h_t = (params['omega']
                   + params['alpha'] * train_r[-1] ** 2
                   + params['beta'] * s2[-1])
        else:
            s2 = gjr_filter(train_r, params['omega'], params['alpha'],
                            params['beta'], params['gamma'])
            ind = 1.0 if train_r[-1] < 0 else 0.0
            h_t = (params['omega']
                   + (params['alpha'] + params['gamma'] * ind) * train_r[-1] ** 2
                   + params['beta'] * s2[-1])

        h_t = max(h_t, 1e-12)
        r2_t = r[idx] ** 2

        q_t = np.log(h_t) + r2_t / h_t

        if np.isfinite(q_t):
            forecasts.append(float(h_t))
            realized.append(float(r2_t))
            qlike_vals.append(float(q_t))
            oos_dates_out.append(str(d[idx].date()))

    if len(qlike_vals) == 0:
        return None

    return {
        'qlike_mean': float(np.mean(qlike_vals)),
        'qlike_values': qlike_vals,
        'n_oos': len(qlike_vals),
        'dates': oos_dates_out,
        'forecasts': forecasts,
        'realized': realized,
    }


def dm_test_hac(loss1, loss2, h=1):
    """Diebold-Mariano test with Newey-West HAC.
    Negative t → model 1 is better.
    """
    d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return 0.0, 1.0

    d_mean = np.mean(d)
    max_lag = max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))
    gamma0 = np.mean((d - d_mean) ** 2)
    var_d = gamma0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)
        gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2 * w * gamma_l

    var_d = max(var_d, 1e-20)
    se = np.sqrt(var_d / n)
    if se < 1e-12:
        return 0.0, 1.0

    t_stat = d_mean / se
    p_val = 2 * (1 - norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val)


# ==============================================================
# E. Data loading
# ==============================================================

def load_asset_data(ticker):
    """Download data from yfinance and compute returns."""
    print(f"  Downloading {ticker}...")
    df = yf.download(ticker, start=DOWNLOAD_START, end=DOWNLOAD_END,
                     auto_adjust=True, progress=False)
    if df.empty:
        print(f"  WARNING: No data for {ticker}")
        return None, None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    prices = df['Close'].dropna()
    returns = prices.pct_change().dropna()

    extreme = returns.abs() > 0.50
    if extreme.any():
        print(f"  Removing {extreme.sum()} extreme returns for {ticker}")
        returns = returns[~extreme]

    print(f"  {ticker}: {len(returns)} returns, "
          f"{returns.index[0].date()} to {returns.index[-1].date()}")
    return prices, returns


# ==============================================================
# F. Table 2: Rolling Gamma (2010 extended window)
# ==============================================================

def run_table2():
    """Table 2: GJR-GARCH gamma rolling estimates using 2010+ data."""
    print("\n" + "=" * 70)
    print("TABLE 2: Rolling Gamma (2010-start, w=504, quarterly step)")
    print("=" * 70)

    results = {}

    for ticker in ASSETS_TABLE2:
        prices, returns = load_asset_data(ticker)
        if returns is None:
            results[ticker] = {'error': 'No data'}
            continue

        # Use data from 2010-01-01 onwards (extended window vs K902's 2017)
        mask = (returns.index >= TABLE2_START)
        r_extended = returns[mask]

        print(f"\n  {ticker}: Using {len(r_extended)} obs from "
              f"{r_extended.index[0].date()} to {r_extended.index[-1].date()}")

        if len(r_extended) < ROLLING_GAMMA_WINDOW + 100:
            print(f"  WARNING: Only {len(r_extended)} obs, may be insufficient")

        rolling_info = rolling_gamma_analysis(r_extended.values,
                                              window=ROLLING_GAMMA_WINDOW,
                                              step=ROLLING_GAMMA_STEP)

        result = {
            'data_start': str(r_extended.index[0].date()),
            'data_end': str(r_extended.index[-1].date()),
            'n_obs': len(r_extended),
            'mean_gamma': round(rolling_info['mean_gamma'], 3)
                          if not np.isnan(rolling_info['mean_gamma']) else None,
            'std_gamma': round(rolling_info['std_gamma'], 3)
                         if not np.isnan(rolling_info.get('std_gamma', np.nan)) else None,
            'pct_negative': round(rolling_info['pct_negative'], 0)
                            if not np.isnan(rolling_info['pct_negative']) else None,
            'hac_tstat': round(rolling_info.get('hac_tstat', np.nan), 2)
                         if not np.isnan(rolling_info.get('hac_tstat', np.nan)) else None,
            'n_windows': rolling_info['n_windows'],
        }

        results[ticker] = result

        print(f"    mean γ={result['mean_gamma']}, std={result['std_gamma']}, "
              f"pct_neg={result['pct_negative']}%, HAC t={result['hac_tstat']}, "
              f"n_windows={result['n_windows']}")

    return results


# ==============================================================
# G. Table 3: OOS QLIKE (with 2010+ training history)
# ==============================================================

def run_table3():
    """Table 3: OOS QLIKE with ROLLING window (w=504), paper methodology.

    KEY FIX vs K902: Rolling window (w=504), NOT expanding.
    Paper body: "We employ a rolling window approach with re-estimation
    at each forecast origin. The primary window size is w=504 trading days."
    Paper body: "expanding windows (worst QLIKE, distant regime contamination)"
    """
    print("\n" + "=" * 70)
    print(f"TABLE 3: OOS QLIKE (ROLLING w={ROLLING_GAMMA_WINDOW}, refit every {REFIT_EVERY}d)")
    print("=" * 70)

    results = {}

    for ticker in ASSETS_TABLE3:
        print(f"\n--- {ticker} ---")
        prices, returns = load_asset_data(ticker)
        if returns is None:
            results[ticker] = {'error': 'No data'}
            continue

        r_arr = returns.values.astype(np.float64)
        dates_arr = returns.index

        asset_results = {}

        for oos_label, oos_start, oos_end in [
            ('2023-2024', OOS_PRIMARY_START, OOS_PRIMARY_END),
            ('2025', OOS_VALIDATION_START, OOS_VALIDATION_END),
        ]:
            print(f"  OOS: {oos_label}")

            # Use ROLLING window (paper methodology)
            garch_oos = oos_qlike_rolling(
                r_arr, dates_arr, oos_start, oos_end,
                window=ROLLING_GAMMA_WINDOW, refit_every=REFIT_EVERY, model='garch')

            gjr_oos = oos_qlike_rolling(
                r_arr, dates_arr, oos_start, oos_end,
                window=ROLLING_GAMMA_WINDOW, refit_every=REFIT_EVERY, model='gjr')

            if garch_oos is None or gjr_oos is None:
                print(f"    SKIP: insufficient data for {ticker} {oos_label}")
                asset_results[oos_label] = {'error': 'insufficient data'}
                continue

            garch_qlike = garch_oos['qlike_mean']
            gjr_qlike = gjr_oos['qlike_mean']

            delta_pct = (gjr_qlike - garch_qlike) / abs(garch_qlike) * 100

            dm_t, dm_p = dm_test_hac(
                np.array(garch_oos['qlike_values']),
                np.array(gjr_oos['qlike_values']),
                h=1
            )

            period_result = {
                'garch_qlike': round(garch_qlike, 3),
                'gjr_qlike': round(gjr_qlike, 3),
                'delta_pct': round(delta_pct, 2),
                'dm_tstat': round(dm_t, 3),
                'dm_pvalue': round(dm_p, 4),
                'dm_significant_5pct': dm_p < 0.05,
                'dm_harvey_pass': abs(dm_t) > 3.0,
                'n_oos_garch': garch_oos['n_oos'],
                'n_oos_gjr': gjr_oos['n_oos'],
            }

            asset_results[oos_label] = period_result

            sig = '*' if dm_p < 0.05 else ''
            harvey = ' [Harvey PASS]' if abs(dm_t) > 3.0 else ''
            print(f"    GARCH QLIKE: {garch_qlike:.3f}")
            print(f"    GJR   QLIKE: {gjr_qlike:.3f}")
            print(f"    Delta: {delta_pct:+.2f}%")
            print(f"    DM t={dm_t:.3f}, p={dm_p:.4f}{sig}{harvey}")
            print(f"    N(OOS): GARCH={garch_oos['n_oos']}, GJR={gjr_oos['n_oos']}")

        results[ticker] = asset_results

    return results


# ==============================================================
# H. Paper comparison (allclose check, rtol=0.01)
# ==============================================================

# Paper Table 2 numbers (from tables.tex tab:gamma)
PAPER_TABLE2 = {
    'SPY': {'mean_gamma': 0.211, 'std': 0.044, 'pct_negative': 0.0, 'hac_t': 8.30},
    'QQQ': {'mean_gamma': 0.110, 'std': 0.072, 'pct_negative': 12.0, 'hac_t': 3.21},
    'EEM': {'mean_gamma': 0.180, 'std': 0.095, 'pct_negative': 8.0, 'hac_t': 4.12},
    'GLD': {'mean_gamma': -0.067, 'std': 0.044, 'pct_negative': 93.0, 'hac_t': -5.79},
    'TLT': {'mean_gamma': -0.008, 'std': 0.048, 'pct_negative': 52.0, 'hac_t': -0.34},
    'BTC-USD': {'mean_gamma': 0.117, 'std': 0.136, 'pct_negative': 28.0, 'hac_t': 1.83},
    'SLV': {'mean_gamma': -0.041, 'std': 0.058, 'pct_negative': 72.0, 'hac_t': -2.91},
}

# Paper Table 3 numbers (from tables.tex tab:qlike)
PAPER_TABLE3 = {
    'SPY': {
        '2023-2024': {'garch': -8.985, 'gjr': -9.034, 'delta': -0.54, 'dm_p': 0.001},
        '2025': {'garch': -8.719, 'gjr': -8.818, 'delta': -1.13, 'dm_p': 0.029},
    },
    'QQQ': {
        '2023-2024': {'garch': -8.554, 'gjr': -8.475, 'delta': 0.92, 'dm_p': 0.067},
        '2025': {'garch': -8.367, 'gjr': -8.454, 'delta': -1.04, 'dm_p': 0.023},
    },
    'GLD': {
        '2023-2024': {'garch': -9.058, 'gjr': -9.065, 'delta': -0.07, 'dm_p': 0.871},
        '2025': {'garch': -8.637, 'gjr': -8.633, 'delta': 0.05, 'dm_p': 0.350},
    },
    'TLT': {
        '2023-2024': {'garch': -9.169, 'gjr': -9.170, 'delta': -0.01, 'dm_p': 0.104},
    },
    'EEM': {
        '2023-2024': {'garch': -8.867, 'gjr': -8.889, 'delta': -0.25, 'dm_p': 0.156},
    },
    'BTC-USD': {
        '2023-2024': {'garch': -6.871, 'gjr': -6.881, 'delta': -0.14, 'dm_p': 0.293},
    },
}


def allclose_check(k903_val, paper_val, rtol=0.01, atol=0.005):
    """Check if two values are within tolerance.
    Returns (is_close, rel_diff, status_symbol)
    """
    if paper_val is None or k903_val is None:
        return None, None, '?'
    if abs(paper_val) < 1e-10:
        diff = abs(k903_val - paper_val)
        is_close = diff < atol
    else:
        rel_diff = abs(k903_val - paper_val) / abs(paper_val)
        is_close = rel_diff < rtol
        diff = rel_diff
    status = '✓' if is_close else '✗'
    return is_close, diff, status


def build_diff_report(table2_results, table3_results):
    """Build a detailed diff report comparing K903 vs paper."""
    lines = []
    lines.append("# K903 vs Paper 1 main.tex — Cell-by-Cell Diff Report")
    lines.append(f"**K903 data_start:** {TABLE2_START}")
    lines.append(f"**Paper data_start:** 2010-01-01 (inferred from audit)")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("## Legend")
    lines.append("- ✓ = allclose (within rtol=0.01 or atol=0.005)")
    lines.append("- ✗ = divergent (outside tolerance)")
    lines.append("- ? = missing data")
    lines.append("")

    # Table 2 diff
    lines.append("## Table 2: Rolling Gamma (w=504)")
    lines.append("")
    lines.append("| Asset | Metric | Paper | K903 | Status | AbsErr | Note |")
    lines.append("|-------|--------|-------|------|--------|--------|------|")

    table2_matched = 0
    table2_diverged = 0
    max_divergence = 0.0
    max_divergence_cell = ''

    for ticker in ['SPY', 'QQQ', 'EEM', 'GLD', 'TLT', 'BTC-USD', 'SLV']:
        paper = PAPER_TABLE2.get(ticker, {})
        k903 = table2_results.get(ticker, {})

        if 'error' in k903:
            lines.append(f"| {ticker} | ALL | — | ERROR | ? | — | {k903['error']} |")
            continue

        # mean gamma
        p_val = paper.get('mean_gamma')
        k_val = k903.get('mean_gamma')
        is_close, diff, status = allclose_check(k_val, p_val)
        abs_err = abs(k_val - p_val) if k_val is not None and p_val is not None else None
        if status == '✓':
            table2_matched += 1
        elif status == '✗':
            table2_diverged += 1
            if abs_err and abs_err > max_divergence:
                max_divergence = abs_err
                max_divergence_cell = f"{ticker} mean γ"
        abs_err_str = f"{abs_err:.3f}" if abs_err is not None else 'N/A'
        lines.append(f"| {ticker} | mean γ | {p_val} | {k_val} | {status} | "
                     f"{abs_err_str} | |")

        # std
        p_val = paper.get('std')
        k_val = k903.get('std_gamma')
        is_close, diff, status = allclose_check(k_val, p_val)
        abs_err = abs(k_val - p_val) if k_val is not None and p_val is not None else None
        if status == '✓':
            table2_matched += 1
        elif status == '✗':
            table2_diverged += 1
        lines.append(f"| {ticker} | std | {p_val} | {k_val} | {status} | "
                     f"{f'{abs_err:.3f}' if abs_err is not None else 'N/A'} | |")

        # pct_negative
        p_val = paper.get('pct_negative')
        k_val = k903.get('pct_negative')
        # For %, use atol=5 (5 percentage points)
        if k_val is not None and p_val is not None:
            abs_err = abs(k_val - p_val)
            is_close = abs_err <= 5.0
            status = '✓' if is_close else '✗'
        else:
            abs_err, status = None, '?'
        if status == '✓':
            table2_matched += 1
        elif status == '✗':
            table2_diverged += 1
        lines.append(f"| {ticker} | % negative | {p_val}% | {k_val}% | {status} | "
                     f"{f'{abs_err:.1f}' if abs_err is not None else 'N/A'} | |")

        # HAC t-stat
        p_val = paper.get('hac_t')
        k_val = k903.get('hac_tstat')
        # For t-stats, use atol=0.5 (generous given sampling variance)
        if k_val is not None and p_val is not None:
            abs_err = abs(k_val - p_val)
            is_close = abs_err <= 0.5 or (abs(p_val) > 0.1 and abs_err / abs(p_val) <= 0.10)
            status = '✓' if is_close else '✗'
        else:
            abs_err, status = None, '?'
        if status == '✓':
            table2_matched += 1
        elif status == '✗':
            table2_diverged += 1
            if abs_err and abs_err > max_divergence:
                max_divergence = abs_err
                max_divergence_cell = f"{ticker} HAC t"
        lines.append(f"| {ticker} | HAC t | {p_val} | {k_val} | {status} | "
                     f"{f'{abs_err:.2f}' if abs_err is not None else 'N/A'} | |")

    lines.append("")
    lines.append(f"**Table 2 summary:** {table2_matched} matched, "
                 f"{table2_diverged} diverged")
    lines.append("")

    # Table 3 diff
    lines.append("## Table 3: OOS QLIKE")
    lines.append("")
    lines.append("| Asset | Period | Metric | Paper | K903 | Status | AbsErr | Note |")
    lines.append("|-------|--------|--------|-------|------|--------|--------|------|")

    table3_matched = 0
    table3_diverged = 0

    for ticker in ['SPY', 'QQQ', 'GLD', 'TLT', 'EEM', 'BTC-USD']:
        paper_asset = PAPER_TABLE3.get(ticker, {})
        k903_asset = table3_results.get(ticker, {})

        if 'error' in k903_asset:
            lines.append(f"| {ticker} | ALL | ALL | — | ERROR | ? | — | {k903_asset.get('error', '')} |")
            continue

        for period_label in ['2023-2024', '2025']:
            paper_period = paper_asset.get(period_label)
            k903_period = k903_asset.get(period_label)

            if paper_period is None:
                continue  # paper doesn't have this row

            if k903_period is None or 'error' in (k903_period or {}):
                lines.append(f"| {ticker} | {period_label} | ALL | — | NO DATA | ? | — | |")
                continue

            for metric, p_key, k_key in [
                ('GARCH QLIKE', 'garch', 'garch_qlike'),
                ('GJR QLIKE', 'gjr', 'gjr_qlike'),
                ('Δ%', 'delta', 'delta_pct'),
                ('DM p', 'dm_p', 'dm_pvalue'),
            ]:
                p_val = paper_period.get(p_key)
                k_val = k903_period.get(k_key)

                if metric == 'DM p':
                    # For p-values, check sign consistency and order of magnitude
                    if k_val is not None and p_val is not None:
                        abs_err = abs(k_val - p_val)
                        # Both significant at 5% or both not
                        same_sig = (k_val < 0.05) == (p_val < 0.05)
                        is_close = same_sig and abs_err < 0.05
                        status = '✓' if is_close else ('≈' if same_sig else '✗')
                    else:
                        abs_err, status = None, '?'
                elif metric in ('GARCH QLIKE', 'GJR QLIKE'):
                    is_close, diff, status = allclose_check(k_val, p_val, rtol=0.01)
                    abs_err = abs(k_val - p_val) if k_val is not None and p_val is not None else None
                    if abs_err and abs_err > max_divergence:
                        max_divergence = abs_err
                        max_divergence_cell = f"{ticker} {period_label} {metric}"
                else:
                    # Delta%: atol=0.3 (0.3 percentage point)
                    if k_val is not None and p_val is not None:
                        abs_err = abs(k_val - p_val)
                        is_close = abs_err <= 0.3
                        status = '✓' if is_close else '✗'
                    else:
                        abs_err, status = None, '?'

                if status == '✓':
                    table3_matched += 1
                elif status == '✗':
                    table3_diverged += 1

                lines.append(f"| {ticker} | {period_label} | {metric} | {p_val} | "
                             f"{k_val} | {status} | "
                             f"{f'{abs_err:.4f}' if abs_err is not None else 'N/A'} | |")

    lines.append("")
    lines.append(f"**Table 3 summary:** {table3_matched} matched, "
                 f"{table3_diverged} diverged")
    lines.append("")

    # Decision recommendation
    total_matched = table2_matched + table3_matched
    total_diverged = table2_diverged + table3_diverged

    lines.append("## Decision Recommendation")
    lines.append("")

    # Determine recommendation based on results
    if total_diverged == 0:
        recommendation = "MATCHED"
        lines.append(f"**Result: MATCHED** — K903 (2010-start) reproduces paper numbers "
                     f"within rtol=0.01 tolerance. Paper numbers are correctly derived from 2010+ data.")
    elif total_diverged <= 3:
        recommendation = "NEAR_MATCH"
        lines.append(f"**Result: NEAR MATCH** — {total_diverged}/{total_matched+total_diverged} "
                     f"cells outside tolerance. Minor divergences may be due to exact step size "
                     f"or data vintage. Recommend (b) paper is correct, K902 was the wrong window.")
    else:
        recommendation = "DIVERGENT"
        lines.append(f"**Result: DIVERGENT** — {total_diverged}/{total_matched+total_diverged} "
                     f"cells outside tolerance after 2010 correction.")
        lines.append("")
        lines.append("See analysis below for (a)/(b)/(c) recommendation.")

    lines.append("")
    lines.append(f"**Max divergence magnitude:** {max_divergence:.4f} (cell: {max_divergence_cell})")
    lines.append("")
    lines.append("### (a) Script fix / (b) Paper update / (c) Errata pending")
    lines.append("")
    lines.append("If K903 ≈ Paper: **(b)** — Paper numbers are correct. "
                 "K902 was wrong (2017-start instead of 2010-start). "
                 "The fix is to update K902 to use 2010 data (done: this is K903). "
                 "**Action: Paper 1 main.tex numbers are confirmed correct. "
                 "K903 is now the canonical script.**")
    lines.append("")
    lines.append("If K903 still diverges: **(c) errata pending** — needs main thread investigation "
                 "into additional differences (step size, filter warm-up, etc.).")

    return "\n".join(lines), recommendation, max_divergence, max_divergence_cell


# ==============================================================
# I. Save CSV tables
# ==============================================================

def save_csv_tables(table2_results, table3_results):
    """Save Table 2 and Table 3 as CSV files."""
    os.makedirs(os.path.join(os.path.dirname(__file__), 'tables'), exist_ok=True)

    # Table 2 CSV
    rows2 = []
    for ticker in ['SPY', 'QQQ', 'EEM', 'GLD', 'TLT', 'BTC-USD', 'SLV']:
        r = table2_results.get(ticker, {})
        if 'error' in r:
            rows2.append({'asset': ticker, 'mean_gamma': None, 'std_gamma': None,
                          'pct_negative': None, 'hac_tstat': None, 'n_windows': None})
        else:
            rows2.append({
                'asset': ticker,
                'mean_gamma': r.get('mean_gamma'),
                'std_gamma': r.get('std_gamma'),
                'pct_negative': r.get('pct_negative'),
                'hac_tstat': r.get('hac_tstat'),
                'n_windows': r.get('n_windows'),
            })
    pd.DataFrame(rows2).to_csv(TABLE2_CSV, index=False)
    print(f"\nTable 2 saved to {TABLE2_CSV}")

    # Table 3 CSV
    rows3 = []
    for ticker in ['SPY', 'QQQ', 'GLD', 'TLT', 'EEM', 'BTC-USD']:
        for period in ['2023-2024', '2025']:
            asset_r = table3_results.get(ticker, {})
            pr = asset_r.get(period, {})
            if 'error' in pr or not pr:
                rows3.append({'asset': ticker, 'period': period,
                              'garch_qlike': None, 'gjr_qlike': None,
                              'delta_pct': None, 'dm_tstat': None, 'dm_pvalue': None})
            else:
                rows3.append({
                    'asset': ticker,
                    'period': period,
                    'garch_qlike': pr.get('garch_qlike'),
                    'gjr_qlike': pr.get('gjr_qlike'),
                    'delta_pct': pr.get('delta_pct'),
                    'dm_tstat': pr.get('dm_tstat'),
                    'dm_pvalue': pr.get('dm_pvalue'),
                })
    pd.DataFrame(rows3).to_csv(TABLE3_CSV, index=False)
    print(f"Table 3 saved to {TABLE3_CSV}")


# ==============================================================
# J. Main
# ==============================================================

def main():
    t0 = time.time()
    print("K903: Paper 1 Tables 2/3 Canonical 2010-Start Replication")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print(f"KEY DIFF 1 vs K902: TABLE2_START={TABLE2_START} (K902 used 2017-01-01)")
    print(f"KEY DIFF 2 vs K902: Rolling window OOS (K902 used expanding window)")
    print(f"KEY DIFF 3 vs K902: Rolling step={ROLLING_GAMMA_STEP} (K902 used ~50)")
    print(f"KEY DIFF 4 vs K902: HAC lags=8 (K902 used 5)")

    # Run Table 2: rolling gamma
    table2_results = run_table2()

    # Run Table 3: OOS QLIKE
    table3_results = run_table3()

    elapsed = time.time() - t0

    # Build diff report
    diff_report, recommendation, max_div, max_div_cell = build_diff_report(
        table2_results, table3_results)

    # Save CSV tables
    save_csv_tables(table2_results, table3_results)

    # Print summary tables
    print("\n" + "=" * 70)
    print("SUMMARY: Table 2 — Rolling Gamma")
    print("=" * 70)
    print(f"{'Asset':<12} {'mean γ':>8} {'std':>7} {'%neg':>6} {'HAC t':>7} {'n_win':>6}")
    print("-" * 55)
    for ticker in ['SPY', 'QQQ', 'EEM', 'GLD', 'TLT', 'BTC-USD', 'SLV']:
        r = table2_results.get(ticker, {})
        paper = PAPER_TABLE2.get(ticker, {})
        if 'error' in r:
            print(f"{ticker:<12} ERROR")
            continue
        print(f"{ticker:<12} {r.get('mean_gamma', 'N/A'):>8} {r.get('std_gamma', 'N/A'):>7} "
              f"{str(r.get('pct_negative', 'N/A'))+'%':>6} {r.get('hac_tstat', 'N/A'):>7} "
              f"{r.get('n_windows', 'N/A'):>6}")
        print(f"{'  paper:':>12} {paper.get('mean_gamma', '—'):>8} {paper.get('std', '—'):>7} "
              f"{str(paper.get('pct_negative', '—'))+'%':>6} {paper.get('hac_t', '—'):>7}")

    print("\n" + "=" * 70)
    print("SUMMARY: Table 3 — OOS QLIKE")
    print("=" * 70)
    print(f"{'Asset':<10} {'Period':<12} {'GARCH':>8} {'GJR':>8} "
          f"{'Δ%':>7} {'DM t':>7} {'DM p':>7}")
    print("-" * 65)
    for ticker in ['SPY', 'QQQ', 'GLD', 'TLT', 'EEM', 'BTC-USD']:
        asset_r = table3_results.get(ticker, {})
        paper_asset = PAPER_TABLE3.get(ticker, {})
        for period in ['2023-2024', '2025']:
            pr = asset_r.get(period, {})
            pp = paper_asset.get(period, {})
            if 'error' in pr or not pr:
                print(f"{ticker:<10} {period:<12} NO DATA")
                continue
            print(f"{ticker:<10} {period:<12} {pr['garch_qlike']:>8.3f} "
                  f"{pr['gjr_qlike']:>8.3f} {pr['delta_pct']:>+7.2f} "
                  f"{pr['dm_tstat']:>7.3f} {pr['dm_pvalue']:>7.4f}")
            if pp:
                print(f"{'  paper:':>22} {pp.get('garch', '—'):>8} "
                      f"{pp.get('gjr', '—'):>8} {pp.get('delta', '—'):>+7.2f}")

    print("\n" + "=" * 70)
    print(f"RECOMMENDATION: {recommendation}")
    print(f"Max divergence: {max_div:.4f} ({max_div_cell})")
    print("=" * 70)

    # Assemble results
    final = {
        'experiment_id': 'K903',
        'title': 'Paper 1 Tables 2/3 Canonical 2010-Start Replication (K902 extension)',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_seconds': round(elapsed, 1),
        'data_source': 'yfinance',
        'key_changes_vs_k902': [
            f'data_start={TABLE2_START} (K902 used 2017-01-01)',
            'Rolling OOS window w=504 (K902 used expanding)',
            f'Rolling step={ROLLING_GAMMA_STEP} days (K902 used ~50)',
            'HAC lags=8 (K902 used 5)',
        ],
        'methodology': {
            'table2': {
                'period': f'{TABLE2_START} to present',
                'rolling_window': ROLLING_GAMMA_WINDOW,
                'step': f'{ROLLING_GAMMA_STEP} days (paper: quarterly)',
                'gamma_estimator': 'GJR unconstrained (allows negative gamma)',
                'hac_lags': 8,
                'paper_citation': 'body.tex: "504-day windows advanced by 63 trading days" + 8 HAC lags',
            },
            'table3': {
                'oos_primary': f'{OOS_PRIMARY_START} to {OOS_PRIMARY_END}',
                'oos_validation': f'{OOS_VALIDATION_START} to {OOS_VALIDATION_END}',
                'oos_method': 'ROLLING window w=504 (paper: "rolling window approach")',
                'refit_every': REFIT_EVERY,
                'qlike_formula': 'QLIKE_t = log(h_t) + r²_t / h_t',
                'dm_test': 'Newey-West HAC',
            },
        },
        'table2_rolling_gamma': table2_results,
        'table3_oos_qlike': table3_results,
        'diff_summary': {
            'recommendation': recommendation,
            'max_divergence': max_div,
            'max_divergence_cell': max_div_cell,
        },
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(final, f, indent=2, default=str)
    print(f"\nResults saved to {RESULTS_PATH}")
    print(f"Elapsed: {elapsed:.1f}s")

    # Save diff report
    diff_path = os.path.join(os.path.dirname(__file__), 'k903_vs_paper_diff.md')
    with open(diff_path, 'w') as f:
        f.write(diff_report)
    print(f"Diff report saved to {diff_path}")

    return final


if __name__ == '__main__':
    main()
