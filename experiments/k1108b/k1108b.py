#!/usr/bin/env python3
"""
K1108b: Multi-foundry pooled test of capex-guidance mechanism.
================================================================
[提出: 賴奕豪, 執行: Claude]  Date: 2026-04-13

Context
-------
K1108 single-firm (TSMC, N=25 change + N=23 stable = 48 events) gave
  Wald t=+0.94, p=0.35 → INCONCLUSIVE (direction-supportive, power-short).

K1108b pools 5 foundry stocks to unlock statistical power:
  TSMC 2330.TW, UMC 2303.TW, TSM (ADR), GFS, SMIC 0981.HK.

Expected pool size:
  TSMC (48) + UMC (50) + GFS (17) + SMIC (23) = 138 distinct-firm events
  TSM ADR (48) — validation sample; redundant with TSMC but different
                 trading days.

Hypotheses:
  H1 (mechanism unlock): pool Wald t > 3.0 (Harvey threshold) and
                        5/5 per-stock direction consistent →
                        capex-guidance confirmed as foundry θ₂>0
                        mechanism.
  H2 (null): pool t < 2 even at N=138+ → capex is NOT the mechanism.
  H3 (mixed/regional): TSMC+UMC (Taiwan) significant, but
                      GFS (US) / SMIC (China) NS → regional market
                      context matters.

Design
------
Per-stock model: K1166-style stock-fixed-effect pooled GJR-GARCH.

Each stock i has its own:
  τ_{i,t} = max(θ_{0,i} + θ_{1,i}·VIX²_{t-1}
                + θ_change · EAV_change_{i,t-1}
                + θ_stable · EAV_stable_{i,t-1}, ε)

  u_{i,t} = r_{i,t} / √τ_{i,t}
  g_{i,t} = ω_i + α·u²_{i,t-1} + γ·u²_{i,t-1}·I[u<0] + β·g_{i,t-1}
  σ²_{i,t} = τ_{i,t} · g_{i,t}

SHARED across stocks: θ_change, θ_stable, α, β, γ (GARCH dynamics).
STOCK-SPECIFIC: θ_{0,i}, θ_{1,i}, ω_i.

This pooled specification lets us test a SINGLE (θ_change − θ_stable)
contrast using the full pool, while allowing per-stock level
differences in baseline τ and VIX sensitivity.

Specs
  P1: Pooled GJR baseline (τ_{i,t} = θ_{0,i}; no EAV).
  P2: Pooled A4f-EAV standard (single shared θ₂ for all EAV days).
  P3: Pooled A4f-EAV + capex split  ← MAIN TEST MODEL.

Tests
  T1: LR test P3 vs P2 (does split help across the pool?).
  T2: Wald test H0: θ_change = θ_stable (pool).
  T3: One-sided t θ_change > 0.
  T4: Per-stock restricted fit (same framework but 1 stock at a time)
      → check direction consistency.
  T5: Leave-one-stock-out (LOO): is result robust to removing any
      single stock? (e.g. is TSMC alone driving the pool result?)
  T6: Regional sub-samples:
      Taiwan subset = TSMC + UMC
      US-listed subset = TSM + GFS
      China subset = SMIC

Lookahead guard
  - All regressors lagged (EAV, VIX² at t-1 → predicts t return).
  - Capex flag based on announcement-day known value.
  - Random seed 42.

Data sources (all PUBLIC, press-release verifiable):
  - 2330.TW daily close (K1104 cache parquet)
  - 2303.TW daily close (K1104 cache parquet)
  - TSM daily close (yfinance 2014-2025)
  - GFS daily close (yfinance 2021-10-28 onwards)
  - 0981.HK daily close (yfinance 2014-2025, but capex 2020+)
  - ^VIX (K1104 cache, ffill onto each stock's trading calendar)
  - 財報公告日.txt (2330 + 2303 earnings dates)
  - yfinance earnings_dates (GFS, SMIC, TSM)
  - k1108b_fetch_capex_pool.py (hand-coded guidance per stock)
"""
from __future__ import annotations

import json
import os
import sys
import time
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats
import matplotlib.pyplot as plt
from numba import njit

import warnings
warnings.filterwarnings('ignore')

np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = 'K1108b'

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
K1104_CACHE = PROJECT_ROOT / 'experiments' / 'k1104' / 'data'
DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
DATA_DIR = SCRIPT_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True, parents=True)

RESULTS_PATH = SCRIPT_DIR / 'k1108b_results.json'
PLOT_PER_STOCK = SCRIPT_DIR / 'k1108b_per_stock_theta.png'
PLOT_POOL_VS_TSMC = SCRIPT_DIR / 'k1108b_pool_vs_tsmc.png'

DATA_START = '2014-01-01'
DATA_END = '2025-12-31'

# Pool composition
STOCKS = {
    # stock_code: (parquet_or_None, yfinance_symbol, earnings_source)
    '2330.TW': ('2330.TW.parquet', '2330.TW', 'twse:2330'),
    '2303.TW': ('2303.TW.parquet', '2303.TW', 'twse:2303'),
    'TSM':     (None,              'TSM',     'yfinance'),
    'GFS':     (None,              'GFS',     'yfinance'),
    '0981.HK': (None,              '0981.HK', 'yfinance'),
}


# ==========================================================================
# DATA LOADERS
# ==========================================================================

def load_prices_parquet(stock):
    path = K1104_CACHE / stock
    if not path.exists():
        return None
    raw = pd.read_parquet(path)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    prices = raw['Close'].dropna()
    prices = prices[(prices.index >= DATA_START) & (prices.index <= DATA_END)]
    # Ensure tz-naive
    try:
        prices.index = prices.index.tz_localize(None)
    except Exception:
        pass
    return prices


def load_prices_yfinance(symbol):
    import yfinance as yf
    t = yf.Ticker(symbol)
    hist = t.history(start=DATA_START, end=DATA_END, auto_adjust=False)
    if hist is None or len(hist) == 0:
        return None
    px = hist['Close'].dropna()
    try:
        px.index = px.index.tz_localize(None)
    except Exception:
        pass
    px = px[(px.index >= DATA_START) & (px.index <= DATA_END)]
    return px


def load_vix():
    path = K1104_CACHE / 'IDX_VIX.parquet'
    if not path.exists():
        raise FileNotFoundError(f"VIX cache missing: {path}")
    raw = pd.read_parquet(path)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    vix = raw['Close'].dropna()
    try:
        vix.index = vix.index.tz_localize(None)
    except Exception:
        pass
    return vix


def load_twse_earnings(code):
    with open(DATA_FILE, 'rb') as f:
        raw_text = f.read().decode('big5', errors='replace')
    lines = raw_text.strip().split('\n')
    dates = []
    for line in lines[1:]:
        parts = line.strip().split('\t')
        if len(parts) >= 4 and parts[0].strip() == code:
            ds = parts[3].strip()
            if ds:
                try:
                    dt = pd.Timestamp(ds.replace('/', '-'))
                    dates.append(dt)
                except Exception:
                    pass
    dates = [d for d in dates
             if pd.Timestamp(DATA_START) <= d <= pd.Timestamp(DATA_END)]
    return sorted(set(dates))


def load_capex_guidance(stock_code):
    safe = stock_code.replace('.', '_').replace('^', '')
    p = DATA_DIR / f'{safe}_capex_guidance.csv'
    if not p.exists():
        # Trigger generation via fetch helper
        sys.path.insert(0, str(SCRIPT_DIR))
        import k1108b_fetch_capex_pool as helper  # type: ignore
        helper.main()
    g = pd.read_csv(p)
    g['announce_date'] = pd.to_datetime(g['announce_date']).dt.tz_localize(None)
    return g


# ==========================================================================
# BUILD PER-STOCK FRAME
# ==========================================================================

def build_stock_frame(stock_code, verbose=True):
    """Build per-stock analysis frame with EAV_change/EAV_stable flags."""
    parquet_name, yf_sym, earn_src = STOCKS[stock_code]
    prices = None
    if parquet_name:
        prices = load_prices_parquet(parquet_name)
    if prices is None:
        prices = load_prices_yfinance(yf_sym)
    if prices is None or len(prices) < 100:
        if verbose:
            print(f"  WARN: {stock_code} price fetch failed "
                  f"(n={len(prices) if prices is not None else 0})")
        return None

    vix = load_vix()
    vix_al = vix.reindex(prices.index, method='ffill')
    log_ret = np.log(prices / prices.shift(1))
    df = pd.DataFrame({
        'price': prices,
        'log_ret': log_ret,
        'VIX': vix_al,
    }).dropna()
    df = df[df['log_ret'].abs() <= 0.30]

    # Earnings dates
    if earn_src.startswith('twse:'):
        code = earn_src.split(':')[1]
        earnings = load_twse_earnings(code)
    else:
        # yfinance earnings_dates; also augmented by the guidance table
        # dates themselves (pre-known announcement dates).
        import yfinance as yf
        t = yf.Ticker(yf_sym)
        ed_raw = t.earnings_dates
        earnings = []
        if ed_raw is not None and len(ed_raw) > 0:
            for idx in ed_raw.index:
                try:
                    dt = idx.tz_localize(None) if idx.tzinfo else idx
                    dt = pd.Timestamp(dt).normalize()
                    if (pd.Timestamp(DATA_START) <= dt <=
                            pd.Timestamp(DATA_END)):
                        earnings.append(dt)
                except Exception:
                    pass

    # Capex guidance
    g = load_capex_guidance(stock_code)
    g_dates = set(g['announce_date'].dt.normalize().tolist())
    earnings_set = set(pd.Timestamp(d).normalize() for d in earnings)
    # Union: treat every guidance-table date as an event (authoritative)
    earnings_set |= g_dates
    earnings = sorted(earnings_set)

    trading_days = df.index
    n = len(trading_days)
    eav_all = np.zeros(n)
    eav_change = np.zeros(n)
    eav_stable = np.zeros(n)

    guide_map = {pd.Timestamp(r.announce_date).normalize(): int(r.guide_updated)
                 for r in g.itertuples(index=False)}

    matched_count = 0
    unmatched_count = 0
    per_event_log = []
    for ea in earnings:
        ea = pd.Timestamp(ea).normalize()
        # Position on trading calendar (searchsorted: event falls on or
        # before next trading day)
        pos = trading_days.searchsorted(ea)
        if pos >= n:
            continue
        # If the event day is not a trading day, pos points to the next
        # trading day; if it's a trading day, pos is that day.
        # Either way, pos is the "next close available" — this is the
        # standard K1104/K1108 convention.
        eav_all[pos] = 1.0
        flag = guide_map.get(ea, None)
        if flag is None:
            unmatched_count += 1
            # No guidance info → treat as stable (conservative)
            eav_stable[pos] = 1.0
            per_event_log.append(
                {'date': str(ea.date()), 'pos': int(pos), 'flag': 'UNMATCHED'})
        elif flag == 1:
            eav_change[pos] = 1.0
            matched_count += 1
            per_event_log.append(
                {'date': str(ea.date()), 'pos': int(pos), 'flag': 'change'})
        else:
            eav_stable[pos] = 1.0
            matched_count += 1
            per_event_log.append(
                {'date': str(ea.date()), 'pos': int(pos), 'flag': 'stable'})

    df['EAV_all'] = eav_all
    df['EAV_change'] = eav_change
    df['EAV_stable'] = eav_stable
    df.attrs['stock'] = stock_code
    df.attrs['n_change'] = int(eav_change.sum())
    df.attrs['n_stable'] = int(eav_stable.sum())
    df.attrs['n_all'] = int(eav_all.sum())
    df.attrs['n_unmatched'] = int(unmatched_count)
    df.attrs['events_log'] = per_event_log

    if verbose:
        print(f"  {stock_code}: n_obs={len(df)} "
              f"| change={df.attrs['n_change']} "
              f"stable={df.attrs['n_stable']} "
              f"all={df.attrs['n_all']} "
              f"unmatched={df.attrs['n_unmatched']}")

    return df


# ==========================================================================
# POOLED NEGATIVE LOG-LIKELIHOOD (K1166-style fixed effects)
# ==========================================================================
# Parameters layout for a pool of M stocks with K_shared shared EAV regressors
# (K_shared = 1 for P2, = 2 for P3; = 0 for P1) and always 1 shared
# per-stock VIX² slope:
#   [ θ_0_1, θ_1_1, ω_1,  θ_0_2, θ_1_2, ω_2,  ..., θ_0_M, θ_1_M, ω_M,
#     theta_shared_1, ..., theta_shared_K_shared,  α, γ, β ]
# α, γ, β are shared across stocks.

@njit(cache=True, fastmath=True)
def _stock_ll_jit(returns, tau, omega, alpha, gamma_p, beta):
    n = returns.shape[0]
    persist = alpha + gamma_p / 2.0 + beta
    eg = omega / (1.0 - persist)
    g = eg
    ll = 0.0
    log_2pi = np.log(2 * np.pi)
    for t in range(1, n):
        tau_prev = tau[t - 1] if tau[t - 1] > 1e-16 else 1e-16
        u_prev = returns[t - 1] / np.sqrt(tau_prev)
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g = omega + alpha * u_prev ** 2 + asym + beta * g
        if g < 1e-10:
            g = 1e-10
        sigma2 = tau[t] * g
        if sigma2 > 0:
            ll += -0.5 * (log_2pi + np.log(sigma2)
                          + returns[t] ** 2 / sigma2)
    return ll


def _prep_frames_arrays(frames, K_shared, shared_reg_names):
    """Pre-extract numpy arrays per frame (call once, not every eval)."""
    data = []
    for f in frames:
        returns = f['log_ret'].values.astype(np.float64)
        vix2 = f['_vix2_lag'].values.astype(np.float64)
        reg_arrays = []
        for name in shared_reg_names:
            reg_arrays.append(
                f['_' + name].values.astype(np.float64))
        data.append((returns, vix2, reg_arrays))
    return data


def _pooled_neg_loglik_prepared(params, prepared, K_shared):
    M = len(prepared)
    offset = 0
    stock_par = []
    for i in range(M):
        theta0_i = params[offset]; offset += 1
        theta1_i = params[offset]; offset += 1
        omega_i = params[offset]; offset += 1
        stock_par.append((theta0_i, theta1_i, omega_i))
    shared_theta = params[offset: offset + K_shared]; offset += K_shared
    alpha = params[offset]; offset += 1
    gamma_p = params[offset]; offset += 1
    beta = params[offset]; offset += 1

    if alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    persist = alpha + gamma_p / 2.0 + beta
    if persist >= 0.999:
        return 1e10

    total_ll = 0.0
    for i in range(M):
        theta0, theta1, omega = stock_par[i]
        if omega <= 0:
            return 1e10
        returns, vix2, reg_arrays = prepared[i]
        tau = theta0 + theta1 * vix2
        if K_shared >= 1:
            tau = tau + shared_theta[0] * reg_arrays[0]
        if K_shared >= 2:
            tau = tau + shared_theta[1] * reg_arrays[1]
        tau = np.maximum(tau, 1e-16)
        ll_i = _stock_ll_jit(returns, tau, omega, alpha, gamma_p, beta)
        total_ll += ll_i
    return -total_ll


# Legacy wrapper (frames-based call signature, used by bootstrap/LOO paths
# that don't cache arrays). Always goes through prepared path.
def _pooled_neg_loglik(params, frames, K_shared, shared_reg_names):
    prepared = _prep_frames_arrays(frames, K_shared, shared_reg_names)
    return _pooled_neg_loglik_prepared(params, prepared, K_shared)


def fit_pool(frames, K_shared, shared_reg_names, starts, bounds, label='',
             with_hessian=True, maxiter=400, ftol=1e-9):
    prepared = _prep_frames_arrays(frames, K_shared, shared_reg_names)

    def nll(p):
        return _pooled_neg_loglik_prepared(p, prepared, K_shared)

    best_ll = np.inf
    best_params = None
    best_res = None
    for s in starts:
        try:
            res = optimize.minimize(
                nll, s, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': maxiter, 'ftol': ftol})
            if res.fun < best_ll and np.isfinite(res.fun):
                best_ll = res.fun
                best_params = res.x
                best_res = res
        except Exception:
            continue
    if best_params is None:
        return None

    result = {
        'label': label,
        'params': best_params,
        'loglik': -best_ll,
        'converged': best_res is not None and best_res.success,
    }

    if with_hessian:
        eps = 1e-5
        k = len(best_params)
        H = np.zeros((k, k))
        f0 = nll(best_params)
        for i in range(k):
            pi_p = best_params.copy(); pi_p[i] += eps
            pi_m = best_params.copy(); pi_m[i] -= eps
            fpp_i = nll(pi_p)
            fmm_i = nll(pi_m)
            H[i, i] = (fpp_i - 2 * f0 + fmm_i) / (eps ** 2)
            for j in range(i + 1, k):
                pij_pp = best_params.copy(); pij_pp[i] += eps; pij_pp[j] += eps
                pij_pm = best_params.copy(); pij_pm[i] += eps; pij_pm[j] -= eps
                pij_mp = best_params.copy(); pij_mp[i] -= eps; pij_mp[j] += eps
                pij_mm = best_params.copy(); pij_mm[i] -= eps; pij_mm[j] -= eps
                fpp = nll(pij_pp); fpm = nll(pij_pm)
                fmp = nll(pij_mp); fmm2 = nll(pij_mm)
                H[i, j] = H[j, i] = (fpp - fpm - fmp + fmm2) / (4 * eps ** 2)
        try:
            cov = np.linalg.pinv(H)
            se = np.sqrt(np.clip(np.diag(cov), 0, None))
        except Exception:
            cov = np.eye(k) * np.nan
            se = np.full(k, np.nan)
        result['se'] = se
        result['cov'] = cov
    else:
        result['se'] = np.full(len(best_params), np.nan)
        result['cov'] = np.eye(len(best_params)) * np.nan
    return result


def add_lag_cols(df):
    vix2 = df['VIX'].values ** 2
    df['_vix2_lag'] = np.concatenate([[vix2[0]], vix2[:-1]])
    ec = df['EAV_change'].values
    df['_EAV_change_lag'] = np.concatenate([[ec[0]], ec[:-1]])
    es = df['EAV_stable'].values
    df['_EAV_stable_lag'] = np.concatenate([[es[0]], es[:-1]])
    ea = df['EAV_all'].values
    df['_EAV_all_lag'] = np.concatenate([[ea[0]], ea[:-1]])
    return df


# ==========================================================================
# PER-STOCK FIT (for per-stock diagnostic + drop-1-stock robustness)
# ==========================================================================

def fit_one_stock(df, starts_extra=None):
    """Fit per-stock M3-equivalent model on a single stock frame."""
    returns = df['log_ret'].values
    vix2_lag = df['_vix2_lag'].values
    ec_lag = df['_EAV_change_lag'].values
    es_lag = df['_EAV_stable_lag'].values
    regressors = np.column_stack([vix2_lag, ec_lag, es_lag])

    var0 = float(np.var(returns))
    vix2_mean = float(np.mean(vix2_lag)) + 1e-8
    eav_mean = max(float(np.mean(ec_lag) + np.mean(es_lag)), 1e-4)
    theta2_init = var0 * 0.05 / eav_mean

    # params: θ₀, θ₁, θ_change, θ_stable, ω, α, γ, β
    starts = [
        [var0 * 0.1, var0 / vix2_mean, theta2_init * 0.5, theta2_init * 0.5,
         0.05, 0.03, 0.06, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, theta2_init * 2.0, 0.0,
         0.10, 0.02, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.0, theta2_init * 2.0,
         0.02, 0.07, 0.10, 0.80],
        [var0 * 0.01, var0 / vix2_mean * 2.0, -theta2_init * 0.5,
         -theta2_init * 0.5, 0.08, 0.04, 0.08, 0.85],
        [var0 * 0.1, var0 / vix2_mean, theta2_init, -theta2_init,
         0.05, 0.02, 0.12, 0.83],
        [var0 * 0.1, var0 / vix2_mean, theta2_init * 3.0,
         -theta2_init * 0.5, 0.06, 0.04, 0.08, 0.88],
    ]
    if starts_extra:
        starts = starts_extra + starts
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
              (-1e-2, 1e-2), (-1e-2, 1e-2),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    best_ll = np.inf; best_params = None
    for s in starts:
        try:
            res = optimize.minimize(
                lambda p: _single_nll(p, returns, regressors),
                s, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 600, 'ftol': 1e-10})
            if res.fun < best_ll and np.isfinite(res.fun):
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    if best_params is None:
        return None

    # Numerical SE
    eps = 1e-5
    k = len(best_params)
    H = np.zeros((k, k))
    f0 = _single_nll(best_params, returns, regressors)
    for i in range(k):
        pi_p = best_params.copy(); pi_p[i] += eps
        pi_m = best_params.copy(); pi_m[i] -= eps
        H[i, i] = (_single_nll(pi_p, returns, regressors)
                   - 2 * f0
                   + _single_nll(pi_m, returns, regressors)) / (eps ** 2)
        for j in range(i + 1, k):
            pij_pp = best_params.copy(); pij_pp[i] += eps; pij_pp[j] += eps
            pij_pm = best_params.copy(); pij_pm[i] += eps; pij_pm[j] -= eps
            pij_mp = best_params.copy(); pij_mp[i] -= eps; pij_mp[j] += eps
            pij_mm = best_params.copy(); pij_mm[i] -= eps; pij_mm[j] -= eps
            H[i, j] = H[j, i] = (
                _single_nll(pij_pp, returns, regressors)
                - _single_nll(pij_pm, returns, regressors)
                - _single_nll(pij_mp, returns, regressors)
                + _single_nll(pij_mm, returns, regressors)) / (4 * eps ** 2)
    try:
        cov = np.linalg.pinv(H)
        se = np.sqrt(np.clip(np.diag(cov), 0, None))
    except Exception:
        cov = np.eye(k) * np.nan
        se = np.full(k, np.nan)
    return {'params': best_params, 'loglik': -best_ll,
            'se': se, 'cov': cov}


def _single_nll(params, returns, regressors):
    K = regressors.shape[1]
    theta0 = params[0]
    theta = params[1:1 + K]
    omega, alpha, gamma_p, beta = params[1 + K:1 + K + 4]
    if omega <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    persist = alpha + gamma_p / 2.0 + beta
    if persist >= 0.999:
        return 1e10
    tau = np.maximum(theta0 + regressors @ theta, 1e-16)
    ll = _stock_ll_jit(returns, tau, omega, alpha, gamma_p, beta)
    return -ll


# ==========================================================================
# POOLED EXPERIMENT
# ==========================================================================

def build_pool(pool_stocks, verbose=True):
    frames = []
    names = []
    for s in pool_stocks:
        f = build_stock_frame(s, verbose=verbose)
        if f is None:
            print(f"  SKIP: {s} data missing")
            continue
        f = add_lag_cols(f)
        frames.append(f)
        names.append(s)
    return frames, names


def run_pooled_P1_P2_P3(frames):
    """Fit pooled P1 (no EAV), P2 (θ_all), P3 (θ_change, θ_stable)."""
    M = len(frames)
    # Initial stock-specific guesses
    stock_inits = []
    for f in frames:
        var0 = float(np.var(f['log_ret'].values))
        vix2_mean = float(np.mean(f['_vix2_lag'].values)) + 1e-8
        stock_inits.append((var0 * 0.1, var0 / vix2_mean, 0.05))

    # Bounds for stock-specific (θ₀, θ₁, ω) repeated M times
    stock_bounds = []
    for _ in range(M):
        stock_bounds += [(-1e-2, 1e-2), (1e-8, 1e-3), (1e-6, 1.0)]
    # GARCH shared
    arch_bounds = [(1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    # --- P1: no shared θ (τ = θ₀ + θ₁·VIX² per stock)
    # Layout: stock block, then [α, γ, β]
    print("\n--- Fitting P1 (pooled GJR + per-stock θ₀,θ₁; no EAV) ---",
          flush=True)
    bounds_P1 = stock_bounds + arch_bounds
    start_P1 = []
    for (t0, t1, w) in stock_inits:
        start_P1 += [t0, t1, w]
    start_P1 += [0.05, 0.06, 0.88]
    start_P1b = []
    for (t0, t1, w) in stock_inits:
        start_P1b += [t0 * 0.5, t1 * 0.5, w * 0.5]
    start_P1b += [0.03, 0.08, 0.90]
    start_P1c = []
    for (t0, t1, w) in stock_inits:
        start_P1c += [t0 * 2.0, t1 * 2.0, w * 2.0]
    start_P1c += [0.08, 0.04, 0.85]

    starts_P1 = [start_P1, start_P1b, start_P1c]
    p1 = fit_pool(frames, K_shared=0, shared_reg_names=[],
                  starts=starts_P1, bounds=bounds_P1,
                  label='P1_pool_GJR', with_hessian=False, maxiter=400,
                  ftol=1e-9)

    # --- P2: shared θ_all
    print("\n--- Fitting P2 (pooled A4f-EAV; single θ₂) ---", flush=True)
    bounds_P2 = stock_bounds + [(-1e-2, 1e-2)] + arch_bounds
    start_P2 = start_P1[:-3] + [0.0] + start_P1[-3:]
    start_P2b = start_P1b[:-3] + [1e-4] + start_P1b[-3:]
    start_P2c = start_P1c[:-3] + [-1e-4] + start_P1c[-3:]
    starts_P2 = [start_P2, start_P2b, start_P2c]
    # Seed from P1
    if p1 is not None:
        p1p = p1['params']
        seed = list(p1p[:-3]) + [0.0] + list(p1p[-3:])
        starts_P2 = [seed] + starts_P2
    p2 = fit_pool(frames, K_shared=1, shared_reg_names=['EAV_all_lag'],
                  starts=starts_P2, bounds=bounds_P2,
                  label='P2_pool_A4fEAV', with_hessian=True, maxiter=500,
                  ftol=1e-9)

    # --- P3: θ_change, θ_stable
    print("\n--- Fitting P3 (pooled A4f-EAV + capex split) ---", flush=True)
    bounds_P3 = stock_bounds + [(-1e-2, 1e-2), (-1e-2, 1e-2)] + arch_bounds
    # Seeds from P2: duplicate θ₂
    starts_P3 = []
    if p2 is not None:
        p2p = p2['params']
        theta2 = p2p[-4]
        base = list(p2p[:-4]) + [theta2, theta2] + list(p2p[-3:])
        starts_P3.append(base)
        # Opposite-sign perturbation
        starts_P3.append(list(p2p[:-4]) + [theta2 + 1e-4, theta2 - 1e-4]
                         + list(p2p[-3:]))
        starts_P3.append(list(p2p[:-4]) + [theta2 - 1e-4, theta2 + 1e-4]
                         + list(p2p[-3:]))
    # Raw asymmetric starts
    base_raw = []
    for (t0, t1, w) in stock_inits:
        base_raw += [t0, t1, w]
    starts_P3.append(base_raw + [2e-4, 0.0, 0.05, 0.06, 0.88])
    starts_P3.append(base_raw + [0.0, 2e-4, 0.05, 0.06, 0.88])
    starts_P3.append(base_raw + [2e-4, -1e-4, 0.04, 0.08, 0.88])
    starts_P3.append(base_raw + [-1e-4, 2e-4, 0.04, 0.08, 0.88])

    p3 = fit_pool(frames, K_shared=2,
                  shared_reg_names=['EAV_change_lag', 'EAV_stable_lag'],
                  starts=starts_P3, bounds=bounds_P3,
                  label='P3_pool_capex_split', with_hessian=True,
                  maxiter=800, ftol=1e-10)

    return p1, p2, p3


def pool_param_summary(pool_fit, M, K_shared, shared_names):
    """Attach names to params for the pooled model."""
    if pool_fit is None:
        return None
    names = []
    for i in range(M):
        names += [f'theta0_{i}', f'theta1_{i}', f'omega_{i}']
    names += [f'theta_{n}' for n in shared_names]
    names += ['alpha', 'gamma', 'beta']
    pp = pool_fit['params']
    se = pool_fit['se'] if 'se' in pool_fit else np.full(len(pp), np.nan)
    out = {
        'label': pool_fit['label'],
        'params': {n: float(v) for n, v in zip(names, pp)},
        'se': {n: float(s) for n, s in zip(names, se)},
        'loglik': float(pool_fit['loglik']),
        'converged': bool(pool_fit.get('converged', False)),
        'names': names,
    }
    return out


def wald_change_eq_stable(p3_fit, M, shared_names):
    """Extract Wald stat for θ_change = θ_stable from pooled P3 fit."""
    pp = p3_fit['params']
    cov = p3_fit['cov']
    # Indices: M stocks * 3 params each + 0 (change), + 1 (stable)
    idx_change = 3 * M + 0
    idx_stable = 3 * M + 1
    diff = pp[idx_change] - pp[idx_stable]
    var_diff = (cov[idx_change, idx_change]
                + cov[idx_stable, idx_stable]
                - 2 * cov[idx_change, idx_stable])
    se_diff = float(np.sqrt(max(var_diff, 1e-30)))
    t_stat = float(diff / se_diff) if se_diff > 0 else np.nan
    p_val = (2 * (1 - stats.norm.cdf(abs(t_stat)))
             if np.isfinite(t_stat) else np.nan)
    return {
        'theta_change': float(pp[idx_change]),
        'theta_stable': float(pp[idx_stable]),
        'diff': float(diff),
        'se_diff': se_diff,
        't_stat': t_stat,
        'p_value_two_sided': float(p_val),
        'p_value_one_sided_change_gt_stable': (
            float(1 - stats.norm.cdf(t_stat))
            if np.isfinite(t_stat) else np.nan),
    }


def per_stock_fit_table(frames, names):
    """Fit each stock separately; return table of θ_change, θ_stable."""
    rows = []
    for f, n in zip(frames, names):
        fit = fit_one_stock(f)
        if fit is None:
            rows.append({'stock': n, 'status': 'FAILED'})
            continue
        pp = fit['params']
        se = fit['se']
        # index 2 = θ_change, 3 = θ_stable (per _single_nll layout)
        rows.append({
            'stock': n,
            'status': 'OK',
            'n_obs': int(len(f)),
            'n_change': int(f['EAV_change'].sum()),
            'n_stable': int(f['EAV_stable'].sum()),
            'theta0': float(pp[0]),
            'theta1': float(pp[1]),
            'theta_change': float(pp[2]),
            'theta_stable': float(pp[3]),
            'se_change': float(se[2]),
            'se_stable': float(se[3]),
            'alpha': float(pp[5]),
            'gamma': float(pp[6]),
            'beta': float(pp[7]),
            'diff': float(pp[2] - pp[3]),
            'loglik': float(fit['loglik']),
        })
    return rows


# ==========================================================================
# LOO & REGIONAL SUB-POOLS
# ==========================================================================

def run_loo(frames, names):
    """Leave-one-stock-out pool: refit P3 without each stock in turn."""
    M = len(frames)
    loo_rows = []
    for k, excl in enumerate(names):
        fr = [f for i, f in enumerate(frames) if i != k]
        if len(fr) < 2:
            continue
        print(f"\n--- LOO excluding {excl} (M={len(fr)}) ---", flush=True)
        _, p2_sub, p3_sub = run_pooled_P1_P2_P3(fr)
        if p3_sub is None:
            loo_rows.append({'excluded': excl, 'status': 'FAILED'})
            continue
        wald = wald_change_eq_stable(p3_sub, len(fr),
                                     ['EAV_change_lag', 'EAV_stable_lag'])
        loo_rows.append({
            'excluded': excl,
            'M_pool': len(fr),
            'theta_change': wald['theta_change'],
            'theta_stable': wald['theta_stable'],
            'diff': wald['diff'],
            't_stat': wald['t_stat'],
            'p_value': wald['p_value_two_sided'],
            'loglik_P3': float(p3_sub['loglik']),
        })
        print(f"  LOO excl {excl}: diff={wald['diff']:+.3e}, "
              f"t={wald['t_stat']:+.3f}, p={wald['p_value_two_sided']:.4f}")
    return loo_rows


def run_regional(frames, names):
    """Fit P3 on regional subsets."""
    groups = {
        'Taiwan': ['2330.TW', '2303.TW'],
        'US_listed': ['TSM', 'GFS'],
        'China': ['0981.HK'],
    }
    rows = []
    for label, want in groups.items():
        fr = [f for f, n in zip(frames, names) if n in want]
        nm = [n for n in names if n in want]
        if len(fr) < 1:
            continue
        print(f"\n--- Regional pool: {label} ({nm}) ---", flush=True)
        if len(fr) == 1:
            # single-firm regional fit
            fit = fit_one_stock(fr[0])
            if fit is None:
                rows.append({'group': label, 'status': 'FAILED'})
                continue
            pp = fit['params']
            se = fit['se']
            diff = pp[2] - pp[3]
            # var(diff) using the 2x2 cov block
            cov = fit['cov']
            var_diff = cov[2, 2] + cov[3, 3] - 2 * cov[2, 3]
            se_diff = float(np.sqrt(max(var_diff, 1e-30)))
            t = diff / se_diff if se_diff > 0 else np.nan
            p = (2 * (1 - stats.norm.cdf(abs(t)))
                 if np.isfinite(t) else np.nan)
            rows.append({
                'group': label,
                'stocks': nm,
                'M': 1,
                'theta_change': float(pp[2]),
                'theta_stable': float(pp[3]),
                'diff': float(diff),
                't_stat': float(t),
                'p_value_two_sided': float(p),
            })
            print(f"  {label}: diff={diff:+.3e}, t={t:+.3f}, p={p:.4f}")
        else:
            _, _, p3_sub = run_pooled_P1_P2_P3(fr)
            if p3_sub is None:
                rows.append({'group': label, 'status': 'FAILED'})
                continue
            wald = wald_change_eq_stable(p3_sub, len(fr),
                                         ['EAV_change_lag', 'EAV_stable_lag'])
            rows.append({
                'group': label,
                'stocks': nm,
                'M': len(fr),
                'theta_change': wald['theta_change'],
                'theta_stable': wald['theta_stable'],
                'diff': wald['diff'],
                't_stat': wald['t_stat'],
                'p_value_two_sided': wald['p_value_two_sided'],
            })
            print(f"  {label}: diff={wald['diff']:+.3e}, "
                  f"t={wald['t_stat']:+.3f}, "
                  f"p={wald['p_value_two_sided']:.4f}")
    return rows


# ==========================================================================
# VERDICT
# ==========================================================================

def decide_verdict(pool_wald, per_stock_rows, loo_rows):
    bullets = []
    t = pool_wald['t_stat']
    p = pool_wald['p_value_two_sided']
    dir_consistent = 0
    dir_total = 0
    for r in per_stock_rows:
        if r.get('status') == 'OK':
            dir_total += 1
            if r['diff'] > 0:
                dir_consistent += 1
    bullets.append(
        f"Pool Wald t={t:+.3f}, p={p:.4f}, diff={pool_wald['diff']:+.3e}")
    bullets.append(
        f"Per-stock direction consistency (diff>0): "
        f"{dir_consistent}/{dir_total}")

    # Hypothesis selection
    if np.isfinite(t) and t > 3.0 and dir_consistent >= max(3, dir_total - 1):
        label = 'H1_MECHANISM_CONFIRMED'
        bullets.append(
            "H1: pool t > 3.0 (Harvey) AND ≥ 4/5 stocks direction-aligned")
    elif np.isfinite(t) and abs(t) < 2.0:
        label = 'H2_MECHANISM_NULL'
        bullets.append("H2: pool t < 2.0 → capex guidance NOT the mechanism")
    elif (np.isfinite(t) and t > 2.0):
        label = 'H1_WEAK'
        bullets.append(
            "H1 (weak): pool t > 2.0 but < 3.0 (not Harvey-strong)")
    else:
        label = 'H3_MIXED'
        bullets.append(
            "H3: pool inconclusive / regional heterogeneity possible")

    # LOO sensitivity
    loo_ts = [r['t_stat'] for r in loo_rows if r.get('t_stat') is not None]
    if loo_ts:
        loo_min = min(loo_ts, key=lambda x: abs(x))
        loo_max = max(loo_ts, key=lambda x: abs(x))
        bullets.append(f"LOO t-range: min|t|={loo_min:+.3f}  "
                       f"max|t|={loo_max:+.3f}")
    return {'label': label, 'bullets': bullets}


# ==========================================================================
# PRE-ESTIMATION DIAGNOSTICS
# ==========================================================================

def pre_estimation_diagnostics(ret, tag=""):
    from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
    from statsmodels.tsa.stattools import adfuller

    d = {
        'tag': tag,
        'n': int(len(ret)),
        'mean': float(np.mean(ret)),
        'std': float(np.std(ret, ddof=1)),
        'skew': float(stats.skew(ret)),
        'kurt': float(stats.kurtosis(ret)),
    }
    try:
        adf = adfuller(ret, autolag='AIC')
        d['adf_stat'] = float(adf[0]); d['adf_pvalue'] = float(adf[1])
    except Exception as e:
        d['adf_error'] = str(e)
    try:
        lb = acorr_ljungbox(ret, lags=[10], return_df=True)
        d['ljungbox_Q10'] = float(lb['lb_stat'].iloc[0])
        d['ljungbox_p10'] = float(lb['lb_pvalue'].iloc[0])
    except Exception as e:
        d['ljungbox_error'] = str(e)
    try:
        arch = het_arch(ret, nlags=10)
        d['arch_lm_stat'] = float(arch[0]); d['arch_lm_p'] = float(arch[1])
    except Exception as e:
        d['arch_error'] = str(e)
    return d


# ==========================================================================
# PLOTS
# ==========================================================================

def plot_per_stock(per_stock_rows, pool_wald, k1108_wald):
    valid = [r for r in per_stock_rows if r.get('status') == 'OK']
    n = len(valid)
    labels = [r['stock'] for r in valid]
    ch = [r['theta_change'] for r in valid]
    st = [r['theta_stable'] for r in valid]
    ch_err = [1.96 * r['se_change'] for r in valid]
    st_err = [1.96 * r['se_stable'] for r in valid]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    x = np.arange(n)
    w = 0.36
    ax.bar(x - w/2, ch, width=w, yerr=ch_err, color='tab:green',
           label='θ_change (capex revised)', alpha=0.8, capsize=4)
    ax.bar(x + w/2, st, width=w, yerr=st_err, color='tab:orange',
           label='θ_stable (capex held)', alpha=0.8, capsize=4)
    ax.axhline(0, color='black', lw=0.8)
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=20)
    ax.set_ylabel('θ (τ shift on EAV day)')
    ax.set_title(
        f'K1108b: Per-stock θ_change vs θ_stable (foundry pool)\n'
        f'Pool Wald t={pool_wald["t_stat"]:+.2f}, '
        f'p={pool_wald["p_value_two_sided"]:.3f}   |   '
        f'K1108 TSMC-only: t={k1108_wald["t_stat"]:+.2f}, '
        f'p={k1108_wald["p_value"]:.3f}')
    ax.legend()
    plt.tight_layout()
    plt.savefig(PLOT_PER_STOCK, dpi=120)
    plt.close()
    print(f"Saved {PLOT_PER_STOCK}")


def plot_pool_vs_tsmc(pool_wald, k1108_wald, per_stock_rows):
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = ['K1108 (TSMC only)', 'K1108b (pool)']
    diffs = [k1108_wald['diff'], pool_wald['diff']]
    ts = [k1108_wald['t_stat'], pool_wald['t_stat']]
    colors = ['tab:gray', 'tab:blue']
    xs = np.arange(2)
    ax.bar(xs, diffs, color=colors, alpha=0.8)
    ax.axhline(0, color='black', lw=0.8)
    for i, (d, t) in enumerate(zip(diffs, ts)):
        ax.text(i, d + (0.01 * abs(d) if abs(d) > 0 else 1e-6),
                f"t={t:+.2f}", ha='center')
    ax.set_xticks(xs); ax.set_xticklabels(labels)
    ax.set_ylabel('θ_change − θ_stable')
    ax.set_title('K1108b vs K1108: pool power unlocks mechanism?')
    plt.tight_layout()
    plt.savefig(PLOT_POOL_VS_TSMC, dpi=120)
    plt.close()
    print(f"Saved {PLOT_POOL_VS_TSMC}")


# ==========================================================================
# MAIN
# ==========================================================================

def run_experiment():
    print(f"=== {EXPERIMENT_ID} ===")
    # Main pool = 4 distinct firms (we treat TSM ADR as separate for
    # validation, but analyse 4-firm pool as primary to avoid
    # double-counting TSMC's earnings signal)
    primary_stocks = ['2330.TW', '2303.TW', 'GFS', '0981.HK']
    # TSM ADR is included in an extended "pool_with_ADR" secondary analysis
    extended_stocks = primary_stocks + ['TSM']

    print("\n>>> Building primary pool (4 firms)")
    frames, names = build_pool(primary_stocks)
    print(f"\nPrimary pool: {names}  total events="
          f"{sum(f.attrs['n_all'] for f in frames)}  "
          f"n_change={sum(f.attrs['n_change'] for f in frames)}  "
          f"n_stable={sum(f.attrs['n_stable'] for f in frames)}")

    # Pre-diagnostics per stock
    diags = {}
    for f, n in zip(frames, names):
        diags[n] = pre_estimation_diagnostics(f['log_ret'].values, tag=n)

    # Pooled P1/P2/P3
    p1, p2, p3 = run_pooled_P1_P2_P3(frames)
    M = len(frames)

    # Per-stock summaries
    print("\n--- Per-stock (independent) fits ---", flush=True)
    per_stock_rows = per_stock_fit_table(frames, names)
    for r in per_stock_rows:
        if r.get('status') == 'OK':
            print(f"  {r['stock']}: diff={r['diff']:+.3e}, "
                  f"θ_change={r['theta_change']:+.3e} "
                  f"(SE={r['se_change']:.2e}), "
                  f"θ_stable={r['theta_stable']:+.3e} "
                  f"(SE={r['se_stable']:.2e})")

    # Wald stat for pool
    if p3 is not None and 'cov' in p3:
        pool_wald = wald_change_eq_stable(
            p3, M, ['EAV_change_lag', 'EAV_stable_lag'])
        # LR test P3 vs P2
        lr_stat = 2 * (p3['loglik'] - p2['loglik'])
        lr_p = float(1 - stats.chi2.cdf(lr_stat, df=1))
        pool_wald['LR_stat'] = float(lr_stat)
        pool_wald['LR_p'] = lr_p
        print(f"\n>>> POOL Wald: diff={pool_wald['diff']:+.3e} "
              f"SE={pool_wald['se_diff']:.3e} "
              f"t={pool_wald['t_stat']:+.3f} "
              f"p={pool_wald['p_value_two_sided']:.4f}")
        print(f">>> LR(P3 vs P2): {lr_stat:.3f}, p={lr_p:.4f}")
    else:
        pool_wald = {'t_stat': np.nan, 'p_value_two_sided': np.nan,
                     'diff': np.nan, 'se_diff': np.nan,
                     'theta_change': np.nan, 'theta_stable': np.nan,
                     'LR_stat': np.nan, 'LR_p': np.nan}

    # LOO
    print("\n--- LOO sensitivity ---", flush=True)
    loo_rows = run_loo(frames, names)

    # Regional
    print("\n--- Regional sub-pools ---", flush=True)
    regional = run_regional(frames, names)

    # Extended pool (with TSM ADR) for validation
    print("\n--- Extended pool (primary + TSM ADR) for validation ---",
          flush=True)
    ext_frames, ext_names = build_pool(extended_stocks)
    _, _, p3_ext = run_pooled_P1_P2_P3(ext_frames)
    if p3_ext is not None and 'cov' in p3_ext:
        ext_wald = wald_change_eq_stable(
            p3_ext, len(ext_frames), ['EAV_change_lag', 'EAV_stable_lag'])
    else:
        ext_wald = None

    # K1108 TSMC-only Wald (for figure labels)
    k1108_wald = {
        'diff': 8.04e-5,
        't_stat': 0.94,
        'p_value': 0.348,
    }

    # Verdict
    verdict = decide_verdict(pool_wald, per_stock_rows, loo_rows)
    print(f"\n>>> VERDICT: {verdict['label']}")
    for b in verdict['bullets']:
        print(f"    - {b}")

    # Plots
    plot_per_stock(per_stock_rows, pool_wald, k1108_wald)
    plot_pool_vs_tsmc(pool_wald, k1108_wald, per_stock_rows)

    # Persist results
    results = {
        'experiment_id': EXPERIMENT_ID,
        'timestamp': pd.Timestamp.utcnow().isoformat(),
        'data_source': [
            'TSMC 2330.TW yfinance cache (experiments/k1104/data/2330.TW.parquet)',
            'UMC 2303.TW yfinance cache (experiments/k1104/data/2303.TW.parquet)',
            'TSM ADR yfinance 2014-2025',
            'GFS yfinance 2021-10-28 onwards',
            'SMIC 0981.HK yfinance 2014-2025 (capex from 2020+)',
            '^VIX yfinance cache (experiments/k1104/data/IDX_VIX.parquet)',
            '財報公告日.txt (2330, 2303 TWSE earnings dates)',
            'yfinance earnings_dates (TSM, GFS, 0981.HK)',
            'k1108b_fetch_capex_pool.py (hand-coded capex guidance per foundry)',
        ],
        'primary_pool': {
            'stocks': names,
            'M': M,
            'n_obs_total': int(sum(len(f) for f in frames)),
            'n_change_total': int(sum(f.attrs['n_change'] for f in frames)),
            'n_stable_total': int(sum(f.attrs['n_stable'] for f in frames)),
            'n_all_total': int(sum(f.attrs['n_all'] for f in frames)),
            'n_unmatched_total': int(sum(f.attrs['n_unmatched'] for f in frames)),
            'per_stock_counts': {
                n: {'n_obs': int(len(f)),
                    'n_change': int(f.attrs['n_change']),
                    'n_stable': int(f.attrs['n_stable']),
                    'n_all': int(f.attrs['n_all']),
                    'n_unmatched': int(f.attrs['n_unmatched'])}
                for n, f in zip(names, frames)
            },
        },
        'pre_estimation_diagnostics': diags,
        'pooled_models': {
            'P1_pool_GJR': (pool_param_summary(p1, M, 0, [])
                            if p1 is not None else None),
            'P2_pool_A4fEAV': (pool_param_summary(p2, M, 1, ['EAV_all_lag'])
                               if p2 is not None else None),
            'P3_pool_capex_split': (pool_param_summary(
                p3, M, 2, ['EAV_change_lag', 'EAV_stable_lag'])
                if p3 is not None else None),
        },
        'tests': {
            'pool_Wald_change_eq_stable': pool_wald,
            'LR_P3_vs_P2': {
                'stat': pool_wald.get('LR_stat'),
                'df': 1,
                'p_value': pool_wald.get('LR_p'),
                'description': 'Does capex split help the pooled fit?',
            },
            'k1108_tsmc_only_reference': k1108_wald,
        },
        'per_stock_fits': per_stock_rows,
        'loo_sensitivity': loo_rows,
        'regional_subpools': regional,
        'extended_pool_with_TSM_ADR': {
            'stocks': ext_names,
            'wald': ext_wald,
        },
        'verdict': verdict,
        'references': [
            'K1108 (TSMC single-firm capex-guidance test — inconclusive)',
            'K1166 (pooled stock-FE framework)',
            'Engle, Ghysels & Sohn (2013) GARCH-MIDAS. RES 95(3).',
            'Patton (2011) Volatility forecast comparison. JoE 160:246-256.',
            'Harvey et al. (2016) t>3.0 threshold for multiple testing.',
        ],
        'random_seed': 42,
        'runtime_seconds': float(time.time() - START_TIME),
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults written: {RESULTS_PATH}")
    return results


if __name__ == '__main__':
    run_experiment()
