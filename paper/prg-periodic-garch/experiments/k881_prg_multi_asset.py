#!/usr/bin/env python3
"""
K881: PRG Multi-Asset Validation (QQQ, GLD, EEM)
==================================================

Research Question (EMPIRICAL):
  K874e: PRG wins on TAIFEX (DM t=5.10 vs GJR)
  K880: PRG tested on SPY (running in parallel)
  K881: Extend to 3 diverse markets — QQQ (tech equity), GLD (gold, NO leverage
  effect), EEM (emerging markets, different dynamics).

  Need 3+ markets for paper-ready evidence that PRG advantage generalises.

Session Decomposition (daily frequency, no tick data):
  r_overnight = log(open_t / close_{t-1})  → r²_overnight proxy
  r_intra     = log(close_t / open_t)       → r²_intra proxy
  σ²_fullday  = r²_overnight + r²_intra     → common target

Models (same 5 as K880):
  1. GJR-GARCH(1,1) on close-to-close returns (standard benchmark)
  2. HAR-proxy: HAR on log(σ²_fullday) with daily/5d/22d lags
  3. PRG Basic (6 params): periodic GARCH, alternating overnight/intraday
  4. PRG Extended (8 params): add leverage γ_{s_n} for negative returns
  5. Separate GARCH: independent GARCH for each session (no cross-recursion)

Key Comparison: PRG vs Separate GARCH isolates cross-recursion value per asset.

Evaluation (common target σ²_fullday):
  Layer 1: QLIKE, MSE, MAE, HMSE, MZ-R² (multiple loss functions)
  Layer 2: MCS (Model Confidence Set, Hansen Lunde Nason 2011)
  Layer 3: Spearman rank correlation with bootstrap CI
  Layer 4: VaR 1% + 5% (Kupiec + Christoffersen + Basel)
  Layer 5: DM test pairwise (Harvey |t|>3.0)

Data: yfinance — QQQ, GLD, EEM
  QQQ: 2000-01 to 2026-04 (tech equity, leverage effect expected)
  GLD: 2004-11 to 2026-04 (gold, minimal/no leverage effect)
  EEM: 2003-04 to 2026-04 (emerging markets, higher vol, overnight gaps)
IS: first 70%, OOS: last 30%

Error log rules applied:
  - DM test: use dm_test from volpred.stats.model_evaluation
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1]) — no stale variance
  - Sanity check: verify forecasts > 0 before evaluation
  - shift(1) equivalent: predict next session from current observation

References:
  - Patton (2011): Volatility forecast comparison using imperfect proxies
  - Hansen, Lunde & Nason (2011): Model Confidence Set
  - Kupiec (1995): Proportion of failures VaR test
  - Christoffersen (1998): Conditional coverage VaR test
  - Bollerslev & Ghysels (1996): Periodic GARCH
  - Corsi (2009): HAR-RV
  - Diebold & Mariano (1995), Harvey et al. (1997): DM test
  - Lai et al. (2024): PRS concept (simplified as PRG)

Author: VolPred Research System
Date: 2026-04-05
"""

import os
import sys
import json
import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from scipy import stats as sp_stats
from scipy.optimize import minimize
from numba import njit

warnings.filterwarnings('ignore')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
from volpred.stats.model_evaluation import dm_test

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k881_results.json")
CHARTS_DIR = os.path.join(SCRIPT_DIR, "k881_charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# Assets to test
ASSETS = {
    'QQQ': {'start': '2000-01-01', 'description': 'Tech equity (Nasdaq-100)'},
    'GLD': {'start': '2004-11-01', 'description': 'Gold ETF (no leverage effect)'},
    'EEM': {'start': '2003-04-01', 'description': 'Emerging markets ETF'},
}

# OOS: last 30% of each asset's data
IS_FRACTION = 0.70

# Refit frequencies
REFIT_FREQ_GJR_HAR = 63     # quarterly for lighter models
REFIT_FREQ_PRG = 252         # annual for PRG (heavy MLE — speed optimised)
PRG_N_STARTS = 3             # multi-start optimization (reduced for speed)


# ============================================================
# Numba-accelerated inner loops
# ============================================================
@njit(cache=True)
def _gjr_negll_numba(omega, alpha, gamma_p, beta, r, T):
    """GJR-GARCH negative log-likelihood (numba-accelerated)."""
    h = np.empty(T)
    h[0] = 0.0
    n_init = min(50, T)
    s = 0.0
    for i in range(n_init):
        s += r[i] ** 2
    h[0] = s / n_init
    if h[0] < 1e-12:
        h[0] = 1e-8
    ll = 0.0
    for t in range(1, T):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        h[t] = omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * indicator + beta * h[t-1]
        if h[t] < 1e-12:
            h[t] = 1e-12
        ll += -0.5*np.log(2*np.pi) - 0.5*np.log(h[t]) - 0.5*r[t]**2/h[t]
    return -ll, h


@njit(cache=True)
def _gjr_propagate_state(omega, alpha, gamma_p, beta, returns, n, h0):
    """Propagate GJR state from h0 through returns[0..n-1]."""
    h = h0
    for t in range(1, n):
        indicator = 1.0 if returns[t-1] < 0 else 0.0
        h = omega + alpha * returns[t-1]**2 + gamma_p * returns[t-1]**2 * indicator + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _garch_negll_numba(omega, alpha, beta, r, T):
    """GARCH(1,1) negative log-likelihood (numba-accelerated)."""
    h = np.empty(T)
    n_init = min(50, T)
    s = 0.0
    for i in range(n_init):
        s += r[i] ** 2
    h[0] = s / n_init
    if h[0] < 1e-12:
        h[0] = 1e-8
    ll = 0.0
    for t in range(1, T):
        h[t] = omega + alpha * r[t-1]**2 + beta * h[t-1]
        if h[t] < 1e-12:
            h[t] = 1e-12
        ll += -0.5*np.log(2*np.pi) - 0.5*np.log(h[t]) - 0.5*r[t]**2/h[t]
    return -ll


@njit(cache=True)
def _garch_propagate_state(omega, alpha, beta, returns, n, h0):
    """Propagate GARCH state from h0 through returns[0..n-1]."""
    h = h0
    for t in range(1, n):
        h = omega + alpha * returns[t-1]**2 + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _prg_negll_numba(omega0, alpha0, beta0, omega1, alpha1, beta1,
                     gamma0, gamma1, r_seq, x_seq, s_seq, n_total):
    """PRG negative log-likelihood (numba-accelerated)."""
    omega = np.array([omega0, omega1])
    alpha = np.array([alpha0, alpha1])
    beta_p = np.array([beta0, beta1])
    gamma = np.array([gamma0, gamma1])

    h = np.empty(n_total)
    n_init = min(100, n_total)
    s = 0.0
    for i in range(n_init):
        s += x_seq[i]
    h[0] = s / n_init
    if h[0] < 1e-12:
        h[0] = 1e-8

    for t in range(1, n_total):
        st = s_seq[t]
        lev = gamma[st] * x_seq[t-1] * (1.0 if r_seq[t-1] < 0.0 else 0.0)
        h[t] = omega[st] + alpha[st] * x_seq[t-1] + lev + beta_p[st] * h[t-1]
        if h[t] < 1e-12:
            h[t] = 1e-12

    ll = 0.0
    for t in range(1, n_total):
        if h[t] > 1e-12:
            ll += -0.5 * np.log(2*np.pi) - 0.5*np.log(h[t]) - 0.5*r_seq[t]**2/h[t]
        else:
            ll += -100.0
    return -ll


@njit(cache=True)
def _prg_propagate_full(omega0, alpha0, beta0, omega1, alpha1, beta1,
                        gamma0, gamma1,
                        r_overnight, r_intra, r2_overnight, r2_intra, n_days):
    """Propagate PRG state through all days, return final h."""
    omega = np.array([omega0, omega1])
    alpha = np.array([alpha0, alpha1])
    beta_p = np.array([beta0, beta1])
    gamma = np.array([gamma0, gamma1])

    n_init = min(50, n_days)
    s = 0.0
    for i in range(n_init):
        s += r2_overnight[i] + r2_intra[i]
    h = s / (2.0 * n_init)
    if h < 1e-12:
        h = 1e-8

    for d in range(n_days):
        # Overnight session
        st = 0
        if d > 0:
            x_prev = r2_intra[d-1]
            r_prev = r_intra[d-1]
        else:
            x_prev = r2_overnight[0]
            r_prev = r_overnight[0]
        lev = gamma[st] * x_prev * (1.0 if r_prev < 0 else 0.0)
        h = omega[st] + alpha[st] * x_prev + lev + beta_p[st] * h
        if h < 1e-12:
            h = 1e-12

        # Intraday session
        st = 1
        x_prev_in = r2_overnight[d]
        r_prev_in = r_overnight[d]
        lev = gamma[st] * x_prev_in * (1.0 if r_prev_in < 0 else 0.0)
        h = omega[st] + alpha[st] * x_prev_in + lev + beta_p[st] * h
        if h < 1e-12:
            h = 1e-12

    return h


@njit(cache=True)
def _prg_forecast_day(omega0, alpha0, beta0, omega1, alpha1, beta1,
                      gamma0, gamma1, h_in,
                      r2_intra_prev, r_intra_prev,
                      r2_overnight_t, r_overnight_t):
    """Forecast σ²_fullday for day t given state h from intraday_{t-1}."""
    omega = np.array([omega0, omega1])
    alpha = np.array([alpha0, alpha1])
    beta_p = np.array([beta0, beta1])
    gamma = np.array([gamma0, gamma1])

    # Overnight of day t
    st = 0
    lev = gamma[st] * r2_intra_prev * (1.0 if r_intra_prev < 0 else 0.0)
    h_ov_t = omega[st] + alpha[st] * r2_intra_prev + lev + beta_p[st] * h_in
    if h_ov_t < 1e-12:
        h_ov_t = 1e-12

    # Intraday of day t
    st = 1
    lev = gamma[st] * r2_overnight_t * (1.0 if r_overnight_t < 0 else 0.0)
    h_in_t = omega[st] + alpha[st] * r2_overnight_t + lev + beta_p[st] * h_ov_t
    if h_in_t < 1e-12:
        h_in_t = 1e-12

    return h_ov_t + h_in_t, h_in_t


@njit(cache=True)
def _prg_propagate_one_day(omega0, alpha0, beta0, omega1, alpha1, beta1,
                           gamma0, gamma1, h_in,
                           r2_intra_prev, r_intra_prev,
                           r2_overnight_d, r_overnight_d):
    """Propagate PRG state through one observed day, return new h."""
    omega = np.array([omega0, omega1])
    alpha = np.array([alpha0, alpha1])
    beta_p = np.array([beta0, beta1])
    gamma = np.array([gamma0, gamma1])

    # Overnight
    st = 0
    lev = gamma[st] * r2_intra_prev * (1.0 if r_intra_prev < 0 else 0.0)
    h = omega[st] + alpha[st] * r2_intra_prev + lev + beta_p[st] * h_in
    if h < 1e-12:
        h = 1e-12

    # Intraday
    st = 1
    lev = gamma[st] * r2_overnight_d * (1.0 if r_overnight_d < 0 else 0.0)
    h = omega[st] + alpha[st] * r2_overnight_d + lev + beta_p[st] * h
    if h < 1e-12:
        h = 1e-12

    return h


# Warm up numba (compile all functions)
print("Warming up numba JIT...")
_dummy_r = np.random.randn(100)
_gjr_negll_numba(1e-6, 0.05, 0.05, 0.9, _dummy_r, 100)
_gjr_propagate_state(1e-6, 0.05, 0.05, 0.9, _dummy_r, 100, 1e-4)
_garch_negll_numba(1e-6, 0.05, 0.9, _dummy_r, 100)
_garch_propagate_state(1e-6, 0.05, 0.9, _dummy_r, 100, 1e-4)
_r_ov = np.abs(_dummy_r[:50]) * 0.01
_r_in = np.abs(_dummy_r[50:]) * 0.01
_r2_ov = _r_ov ** 2
_r2_in = _r_in ** 2
_r_seq = np.zeros(100)
_x_seq = np.zeros(100)
_s_seq = np.zeros(100, dtype=np.int64)
for i in range(50):
    _r_seq[2*i] = _r_ov[i]
    _r_seq[2*i+1] = _r_in[i]
    _x_seq[2*i] = _r2_ov[i]
    _x_seq[2*i+1] = _r2_in[i]
    _s_seq[2*i] = 0
    _s_seq[2*i+1] = 1
_prg_negll_numba(1e-6, 0.1, 0.8, 1e-6, 0.1, 0.8, 0.05, 0.05,
                 _r_seq, _x_seq, _s_seq, 100)
_prg_propagate_full(1e-6, 0.1, 0.8, 1e-6, 0.1, 0.8, 0.05, 0.05,
                    _r_ov, _r_in, _r2_ov, _r2_in, 50)
_prg_forecast_day(1e-6, 0.1, 0.8, 1e-6, 0.1, 0.8, 0.05, 0.05,
                  1e-4, 1e-4, 0.01, 1e-4, 0.01)
_prg_propagate_one_day(1e-6, 0.1, 0.8, 1e-6, 0.1, 0.8, 0.05, 0.05,
                       1e-4, 1e-4, 0.01, 1e-4, 0.01)
print("  Numba JIT warm-up complete.")


# ============================================================
# DATA LOADING
# ============================================================
def load_asset_data(ticker, start_date):
    """Load OHLC from yfinance and compute session decomposition."""
    import yfinance as yf

    print(f"  Downloading {ticker} from yfinance...")
    data = yf.download(ticker, start=start_date, end="2026-04-05", auto_adjust=True)
    print(f"    {ticker}: {len(data)} days, {data.index[0].date()} to {data.index[-1].date()}")

    # Flatten MultiIndex columns if present
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    df = pd.DataFrame(index=data.index)
    df['open'] = data['Open'].values
    df['high'] = data['High'].values
    df['low'] = data['Low'].values
    df['close'] = data['Close'].values

    # Session decomposition
    df['prev_close'] = df['close'].shift(1)
    df['r_overnight'] = np.log(df['open'] / df['prev_close'])
    df['r_intra'] = np.log(df['close'] / df['open'])
    df['r_c2c'] = np.log(df['close'] / df['prev_close'])

    # Variance proxies
    df['r2_overnight'] = df['r_overnight'] ** 2
    df['r2_intra'] = df['r_intra'] ** 2
    df['sigma2_fullday'] = df['r2_overnight'] + df['r2_intra']

    # Parkinson variance for reference
    df['parkinson'] = (np.log(df['high'] / df['low'])) ** 2 / (4 * np.log(2))

    # Drop first row (no prev_close) and any NaN
    df = df.iloc[1:].dropna(subset=['r_overnight', 'r_intra', 'sigma2_fullday'])

    # Remove extreme outliers (data errors) — > 20% daily move
    mask = (np.abs(df['r_c2c']) < 0.20) & (df['sigma2_fullday'] < 0.04)
    n_removed = len(df) - mask.sum()
    if n_removed > 0:
        print(f"    Removed {n_removed} extreme outliers (>20% daily move)")
    df = df[mask]

    print(f"    After processing: {len(df)} days")
    return df


# ============================================================
# MODEL 1: GJR-GARCH OOS
# ============================================================
def gjr_oos_forecast(returns, is_end, refit_freq=63):
    """GJR-GARCH(1,1) OOS on c2c returns, numba-accelerated."""
    n = len(returns)
    forecasts = np.full(n, np.nan)

    def gjr_negll(params, r):
        nll, _ = _gjr_negll_numba(params[0], params[1], params[2], params[3], r, len(r))
        return nll

    eps = 1e-8
    bounds = [(eps, 1e-3), (eps, 0.5), (0.0, 0.5), (eps, 0.999)]
    current_params = None
    h_state = np.var(returns[:min(50, n)])

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            r_train = returns[:t]
            best_nll = np.inf
            best_p = None
            rng = np.random.RandomState(42)
            for i in range(3):
                if i == 0:
                    x0 = [np.var(r_train)*0.05, 0.08, 0.06, 0.85]
                else:
                    x0 = [rng.uniform(1e-8, 1e-4), rng.uniform(0.02, 0.2),
                           rng.uniform(0.0, 0.15), rng.uniform(0.7, 0.95)]
                try:
                    result = minimize(gjr_negll, x0, args=(r_train,),
                                      method='L-BFGS-B', bounds=bounds,
                                      options={'maxiter': 1000})
                    if result.fun < best_nll:
                        best_nll = result.fun
                        best_p = result.x
                except Exception:
                    continue
            if best_p is not None:
                current_params = best_p
                omega, alpha, gamma_p, beta = current_params
                h0 = np.var(returns[:min(50, t)])
                if h0 < 1e-12:
                    h0 = 1e-8
                h_state = _gjr_propagate_state(omega, alpha, gamma_p, beta, returns, t, h0)

        if current_params is not None:
            omega, alpha, gamma_p, beta = current_params
            indicator = 1.0 if returns[t-1] < 0 else 0.0
            h_state = omega + alpha*returns[t-1]**2 + gamma_p*returns[t-1]**2*indicator + beta*h_state
            if h_state < 1e-12:
                h_state = 1e-12
            forecasts[t] = h_state

    return forecasts


# ============================================================
# MODEL 2: HAR on σ²_fullday (log-space)
# ============================================================
def har_oos_forecast(sigma2_series, is_end, refit_freq=63):
    """HAR on log(σ²_fullday) with daily/5d/22d lags."""
    eps_val = 1e-12
    log_sig = np.log(np.clip(sigma2_series, eps_val, None))
    n = len(log_sig)

    log_d = pd.Series(log_sig).shift(1).values
    log_5d = pd.Series(log_sig).rolling(5).mean().shift(1).values
    log_22d = pd.Series(log_sig).rolling(22).mean().shift(1).values

    forecasts = np.full(n, np.nan)
    beta = None

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            train_start = 22
            y_train = log_sig[train_start:t]
            X_train = np.column_stack([
                log_d[train_start:t],
                log_5d[train_start:t],
                log_22d[train_start:t],
            ])
            valid = np.all(np.isfinite(X_train), axis=1) & np.isfinite(y_train)
            if valid.sum() < 50:
                continue
            y_t = y_train[valid]
            X_t = X_train[valid]
            X_c = np.column_stack([np.ones(len(y_t)), X_t])
            try:
                beta = np.linalg.lstsq(X_c, y_t, rcond=None)[0]
            except Exception:
                continue

        if (beta is not None and np.isfinite(log_d[t])
                and np.isfinite(log_5d[t]) and np.isfinite(log_22d[t])):
            x_t = np.array([1.0, log_d[t], log_5d[t], log_22d[t]])
            log_forecast = x_t @ beta
            forecasts[t] = np.exp(log_forecast)

    return forecasts


# ============================================================
# MODEL 3/4: PRG (Periodic Realized GARCH)
# ============================================================
def estimate_prg(r_overnight, r_intra, r2_overnight, r2_intra,
                 extended=False, n_starts=3):
    """
    Estimate PRG via MLE (numba-accelerated inner loop).
    Interleaved sequence: overnight_0, intra_0, overnight_1, intra_1, ...
    """
    n_days = len(r_overnight)
    n_total = 2 * n_days

    # Build interleaved arrays
    r_seq = np.zeros(n_total)
    x_seq = np.zeros(n_total)
    s_seq = np.zeros(n_total, dtype=np.int64)

    for i in range(n_days):
        idx_ov = 2 * i
        idx_in = 2 * i + 1
        r_seq[idx_ov] = r_overnight[i]
        r_seq[idx_in] = r_intra[i]
        x_seq[idx_ov] = r2_overnight[i]
        x_seq[idx_in] = r2_intra[i]
        s_seq[idx_ov] = 0
        s_seq[idx_in] = 1

    def neg_loglik(params):
        g0 = params[6] if extended else 0.0
        g1 = params[7] if extended else 0.0
        return _prg_negll_numba(
            params[0], params[1], params[2],
            params[3], params[4], params[5],
            g0, g1, r_seq, x_seq, s_seq, n_total)

    eps = 1e-8
    if extended:
        bounds = [
            (eps, 1e-3), (eps, 1.0), (eps, 0.999),
            (eps, 1e-3), (eps, 1.0), (eps, 0.999),
            (0.0, 1.0), (0.0, 1.0),
        ]
    else:
        bounds = [
            (eps, 1e-3), (eps, 1.0), (eps, 0.999),
            (eps, 1e-3), (eps, 1.0), (eps, 0.999),
        ]

    var_ov = np.mean(x_seq[s_seq == 0][:min(100, n_total)])
    var_in = np.mean(x_seq[s_seq == 1][:min(100, n_total)])

    best_nll = np.inf
    best_params = None
    rng = np.random.RandomState(42)

    for start_i in range(n_starts):
        if start_i == 0:
            x0 = [var_ov*0.05, 0.15, 0.80, var_in*0.05, 0.15, 0.80]
            if extended:
                x0 += [0.05, 0.05]
        else:
            x0 = [rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.40), rng.uniform(0.50, 0.95),
                   rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.40), rng.uniform(0.50, 0.95)]
            if extended:
                x0 += [rng.uniform(0.0, 0.2), rng.uniform(0.0, 0.2)]

        try:
            result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                              options={'maxiter': 1500, 'ftol': 1e-9})
            if result.fun < best_nll:
                best_nll = result.fun
                best_params = result.x
        except Exception:
            continue

    return best_params, -best_nll if best_params is not None else None


def prg_oos_forecast(r_overnight, r_intra, r2_overnight, r2_intra,
                     is_end, extended=False, refit_freq=252):
    """
    PRG OOS forecast (numba-accelerated).
    Predicts σ²_fullday = h_overnight + h_intraday.
    Uses incremental state propagation between refits.
    """
    n_days = len(r_overnight)
    forecasts = np.full(n_days, np.nan)

    current_params = None
    h_state = None

    for t in range(is_end, n_days):
        # Refit periodically
        if (t - is_end) % refit_freq == 0 or t == is_end:
            params, ll = estimate_prg(
                r_overnight[:t], r_intra[:t],
                r2_overnight[:t], r2_intra[:t],
                extended=extended, n_starts=PRG_N_STARTS
            )
            if params is not None:
                current_params = params
                g0 = current_params[6] if extended else 0.0
                g1 = current_params[7] if extended else 0.0

                # Full state rebuild via numba
                h_state = _prg_propagate_full(
                    current_params[0], current_params[1], current_params[2],
                    current_params[3], current_params[4], current_params[5],
                    g0, g1,
                    r_overnight[:t], r_intra[:t],
                    r2_overnight[:t], r2_intra[:t], t)

        if current_params is None or h_state is None:
            continue

        g0 = current_params[6] if extended else 0.0
        g1 = current_params[7] if extended else 0.0

        # Between refits: propagate state for day t-1 observations
        if (t - is_end) % refit_freq != 0 and t != is_end:
            d = t - 1
            x_prev = r2_intra[d-1] if d > 0 else r2_overnight[0]
            r_prev = r_intra[d-1] if d > 0 else r_overnight[0]
            h_state = _prg_propagate_one_day(
                current_params[0], current_params[1], current_params[2],
                current_params[3], current_params[4], current_params[5],
                g0, g1, h_state,
                x_prev, r_prev,
                r2_overnight[d], r_overnight[d])

        # Forecast day t
        fc, h_forecast = _prg_forecast_day(
            current_params[0], current_params[1], current_params[2],
            current_params[3], current_params[4], current_params[5],
            g0, g1, h_state,
            r2_intra[t-1], r_intra[t-1],
            r2_overnight[t], r_overnight[t])
        forecasts[t] = fc

    return forecasts


# ============================================================
# MODEL 5: Separate GARCH (no cross-recursion)
# ============================================================
def separate_garch_oos(r_overnight, r_intra, r2_overnight, r2_intra,
                       is_end, refit_freq=63):
    """
    Two independent GARCH(1,1) for overnight and intraday (numba-accelerated).
    No cross-session h propagation.
    σ²_fullday = h_overnight + h_intraday.
    """
    n_days = len(r_overnight)
    forecasts = np.full(n_days, np.nan)

    def garch_negll(params, r):
        return _garch_negll_numba(params[0], params[1], params[2], r, len(r))

    eps = 1e-8
    bounds = [(eps, 1e-3), (eps, 0.5), (eps, 0.999)]

    ov_params = None
    in_params = None
    h_ov_state = np.var(r_overnight[:min(50, n_days)])
    h_in_state = np.var(r_intra[:min(50, n_days)])

    for t in range(is_end, n_days):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            rng = np.random.RandomState(42)

            # Fit overnight GARCH
            r_ov_train = r_overnight[:t]
            best_nll = np.inf
            best_p = None
            for i in range(3):
                if i == 0:
                    x0 = [np.var(r_ov_train)*0.05, 0.08, 0.85]
                else:
                    x0 = [rng.uniform(1e-8, 1e-4), rng.uniform(0.02, 0.2),
                           rng.uniform(0.7, 0.95)]
                try:
                    result = minimize(garch_negll, x0, args=(r_ov_train,),
                                      method='L-BFGS-B', bounds=bounds,
                                      options={'maxiter': 1000})
                    if result.fun < best_nll:
                        best_nll = result.fun
                        best_p = result.x
                except Exception:
                    continue
            if best_p is not None:
                ov_params = best_p
                omega, alpha, beta = ov_params
                h0 = np.var(r_ov_train[:min(50, t)])
                if h0 < 1e-12:
                    h0 = 1e-8
                h_ov_state = _garch_propagate_state(omega, alpha, beta, r_overnight, t, h0)

            # Fit intraday GARCH
            r_in_train = r_intra[:t]
            best_nll = np.inf
            best_p = None
            for i in range(3):
                if i == 0:
                    x0 = [np.var(r_in_train)*0.05, 0.08, 0.85]
                else:
                    x0 = [rng.uniform(1e-8, 1e-4), rng.uniform(0.02, 0.2),
                           rng.uniform(0.7, 0.95)]
                try:
                    result = minimize(garch_negll, x0, args=(r_in_train,),
                                      method='L-BFGS-B', bounds=bounds,
                                      options={'maxiter': 1000})
                    if result.fun < best_nll:
                        best_nll = result.fun
                        best_p = result.x
                except Exception:
                    continue
            if best_p is not None:
                in_params = best_p
                omega, alpha, beta = in_params
                h0 = np.var(r_in_train[:min(50, t)])
                if h0 < 1e-12:
                    h0 = 1e-8
                h_in_state = _garch_propagate_state(omega, alpha, beta, r_intra, t, h0)

        # Propagate one step
        if ov_params is not None:
            omega, alpha, beta = ov_params
            h_ov_state = omega + alpha * r_overnight[t-1]**2 + beta * h_ov_state
            if h_ov_state < 1e-12:
                h_ov_state = 1e-12

        if in_params is not None:
            omega, alpha, beta = in_params
            h_in_state = omega + alpha * r_intra[t-1]**2 + beta * h_in_state
            if h_in_state < 1e-12:
                h_in_state = 1e-12

        if ov_params is not None and in_params is not None:
            forecasts[t] = h_ov_state + h_in_state

    return forecasts


# ============================================================
# EVALUATION FUNCTIONS
# ============================================================
def qlike_loss_array(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    loss = np.full(len(realized), np.nan)
    r = realized[valid]
    f = forecast[valid]
    loss[valid] = r/f - np.log(r/f) - 1
    return loss


def mse_loss_array(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast)
    loss = np.full(len(realized), np.nan)
    loss[valid] = (realized[valid] - forecast[valid]) ** 2
    return loss


def mae_loss_array(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast)
    loss = np.full(len(realized), np.nan)
    loss[valid] = np.abs(realized[valid] - forecast[valid])
    return loss


def hmse_loss_array(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    loss = np.full(len(realized), np.nan)
    loss[valid] = (1 - realized[valid] / forecast[valid]) ** 2
    return loss


def mincer_zarnowitz_r2(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    r = realized[valid]
    f = forecast[valid]
    n = len(r)
    if n < 30:
        return {'r2': np.nan, 'b': np.nan, 'n': n}
    X = np.column_stack([np.ones(n), f])
    try:
        beta_hat = np.linalg.lstsq(X, r, rcond=None)[0]
    except Exception:
        return {'r2': np.nan, 'b': np.nan, 'n': n}
    r_hat = X @ beta_hat
    ss_res = np.sum((r - r_hat) ** 2)
    ss_tot = np.sum((r - np.mean(r)) ** 2)
    r2_val = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return {'r2': float(r2_val), 'a': float(beta_hat[0]), 'b': float(beta_hat[1]), 'n': n}


def compute_all_losses(realized_oos, forecast_oos):
    """Compute all loss functions for a model."""
    ql = qlike_loss_array(realized_oos, forecast_oos)
    ms = mse_loss_array(realized_oos, forecast_oos)
    ma = mae_loss_array(realized_oos, forecast_oos)
    hm = hmse_loss_array(realized_oos, forecast_oos)
    mz = mincer_zarnowitz_r2(realized_oos, forecast_oos)

    valid_ql = ql[np.isfinite(ql)]
    valid_ms = ms[np.isfinite(ms)]
    valid_ma = ma[np.isfinite(ma)]
    valid_hm = hm[np.isfinite(hm)]

    return {
        'QLIKE': float(np.mean(valid_ql)) if len(valid_ql) > 0 else np.nan,
        'MSE': float(np.mean(valid_ms)) if len(valid_ms) > 0 else np.nan,
        'MAE': float(np.mean(valid_ma)) if len(valid_ma) > 0 else np.nan,
        'HMSE': float(np.mean(valid_hm)) if len(valid_hm) > 0 else np.nan,
        'MZ_R2': mz['r2'],
        'MZ_b': mz.get('b', np.nan),
        'n_obs': len(valid_ql),
        'qlike_array': ql,
        'mse_array': ms,
    }


# ============================================================
# LAYER 2: Model Confidence Set
# ============================================================
def model_confidence_set(loss_dict, alpha=0.10, n_boot=5000):
    """Simplified MCS using bootstrap elimination."""
    model_names = list(loss_dict.keys())

    n_obs = min(len(v) for v in loss_dict.values())
    losses = {}
    for name in model_names:
        arr = loss_dict[name][:n_obs]
        losses[name] = arr

    common_valid = np.ones(n_obs, dtype=bool)
    for name in model_names:
        common_valid &= np.isfinite(losses[name])

    idx = np.where(common_valid)[0]
    if len(idx) < 100:
        return model_names, {}

    aligned_losses = {name: losses[name][idx] for name in model_names}
    T = len(idx)

    surviving = list(model_names)
    eliminated = {}
    rng = np.random.RandomState(42)

    while len(surviving) > 1:
        mean_losses = {name: np.mean(aligned_losses[name]) for name in surviving}
        worst_name = max(surviving, key=lambda n: mean_losses[n])

        d_arrays = {}
        for name in surviving:
            if name != worst_name:
                d_arrays[name] = aligned_losses[worst_name] - aligned_losses[name]

        observed_max_d = max(np.mean(d) for d in d_arrays.values())

        boot_count = 0
        for b in range(n_boot):
            boot_idx = rng.randint(0, T, T)
            boot_max = max(np.mean(d_arrays[name][boot_idx]) for name in d_arrays)
            if boot_max >= observed_max_d:
                boot_count += 1

        p_value = boot_count / n_boot

        if p_value < alpha:
            surviving.remove(worst_name)
            eliminated[worst_name] = float(p_value)
        else:
            break

    return surviving, eliminated


# ============================================================
# LAYER 3: Spearman with bootstrap CI
# ============================================================
def spearman_with_bootstrap(realized, forecast, n_boot=5000):
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    r = realized[valid]
    f = forecast[valid]
    n = len(r)
    if n < 30:
        return {'rho': np.nan, 'ci_lo': np.nan, 'ci_hi': np.nan, 'n': n}

    rho, p = sp_stats.spearmanr(r, f)

    rng = np.random.RandomState(42)
    boot_rhos = []
    for _ in range(n_boot):
        idx_b = rng.randint(0, n, n)
        br, _ = sp_stats.spearmanr(r[idx_b], f[idx_b])
        boot_rhos.append(br)
    boot_rhos = np.array(boot_rhos)
    ci_lo = np.percentile(boot_rhos, 2.5)
    ci_hi = np.percentile(boot_rhos, 97.5)

    return {'rho': float(rho), 'p': float(p),
            'ci_lo': float(ci_lo), 'ci_hi': float(ci_hi), 'n': n}


# ============================================================
# LAYER 4: VaR Backtesting
# ============================================================
def var_backtest(returns, sigma2_forecasts, alpha_levels=None):
    """VaR backtesting with Kupiec + Christoffersen tests."""
    if alpha_levels is None:
        alpha_levels = [0.01, 0.05]

    valid = np.isfinite(returns) & np.isfinite(sigma2_forecasts) & (sigma2_forecasts > 0)
    r = returns[valid]
    s2 = sigma2_forecasts[valid]
    n = len(r)

    results = {}
    for alpha_val in alpha_levels:
        z = sp_stats.norm.ppf(alpha_val)
        var_level = z * np.sqrt(s2)

        violations = r < var_level
        n_violations = int(np.sum(violations))
        vr = n_violations / n if n > 0 else np.nan

        # Kupiec LR test
        if 0 < n_violations < n:
            lr_uc = -2 * (n_violations * np.log(alpha_val)
                         + (n - n_violations) * np.log(1 - alpha_val)
                         - n_violations * np.log(vr)
                         - (n - n_violations) * np.log(1 - vr))
            p_kupiec = 1 - sp_stats.chi2.cdf(lr_uc, 1)
        else:
            lr_uc = np.nan
            p_kupiec = np.nan

        # Christoffersen conditional coverage
        v = violations.astype(int)
        n00 = np.sum((v[:-1] == 0) & (v[1:] == 0))
        n01 = np.sum((v[:-1] == 0) & (v[1:] == 1))
        n10 = np.sum((v[:-1] == 1) & (v[1:] == 0))
        n11 = np.sum((v[:-1] == 1) & (v[1:] == 1))

        if (n00 + n01) > 0 and (n10 + n11) > 0 and n01 > 0 and n10 > 0:
            p01 = n01 / (n00 + n01)
            p11 = n11 / (n10 + n11)
            p_hat = (n01 + n11) / (n00 + n01 + n10 + n11)

            if 0 < p_hat < 1 and 0 < p01 < 1 and 0 < p11 < 1:
                lr_ind = -2 * ((n00 + n10) * np.log(1 - p_hat)
                              + (n01 + n11) * np.log(p_hat)
                              - n00 * np.log(1 - p01) - n01 * np.log(p01)
                              - n10 * np.log(1 - p11) - n11 * np.log(p11))
                lr_cc = lr_uc + lr_ind
                p_cc = 1 - sp_stats.chi2.cdf(lr_cc, 2)
            else:
                lr_cc = np.nan
                p_cc = np.nan
        else:
            lr_cc = np.nan
            p_cc = np.nan

        # Basel traffic light (250-day window)
        if n >= 250:
            recent_violations = int(np.sum(violations[-250:]))
            if recent_violations < 5:
                basel = "Green"
            elif recent_violations < 10:
                basel = "Yellow"
            else:
                basel = "Red"
        else:
            recent_violations = n_violations
            basel = "N/A"

        results[f"VaR_{int(alpha_val*100)}pct"] = {
            'n': n,
            'n_violations': n_violations,
            'violation_rate': float(vr),
            'expected_rate': float(alpha_val),
            'kupiec_LR': float(lr_uc) if np.isfinite(lr_uc) else None,
            'kupiec_p': float(p_kupiec) if np.isfinite(p_kupiec) else None,
            'kupiec_pass': bool(p_kupiec > 0.05) if np.isfinite(p_kupiec) else None,
            'cc_LR': float(lr_cc) if np.isfinite(lr_cc) else None,
            'cc_p': float(p_cc) if np.isfinite(p_cc) else None,
            'cc_pass': bool(p_cc > 0.05) if np.isfinite(p_cc) else None,
            'basel': basel,
            'basel_violations_250d': recent_violations,
        }

    return results


# ============================================================
# LAYER 5: DM Test (pairwise, Harvey correction)
# ============================================================
def pairwise_dm_tests(model_losses, model_names_list):
    """Pairwise DM tests between all model pairs using QLIKE loss."""
    results = {}
    for i in range(len(model_names_list)):
        for j in range(i+1, len(model_names_list)):
            name_i = model_names_list[i]
            name_j = model_names_list[j]

            loss_i = model_losses[name_i]
            loss_j = model_losses[name_j]

            valid = np.isfinite(loss_i) & np.isfinite(loss_j)
            li = loss_i[valid]
            lj = loss_j[valid]

            if len(li) < 100:
                results[f"{name_i}_vs_{name_j}"] = {
                    't_stat': np.nan, 'p_value': np.nan, 'n': len(li),
                    'winner': 'N/A', 'harvey_pass': False
                }
                continue

            try:
                dm_result = dm_test(li, lj)
                t_stat = dm_result.get('t_statistic', dm_result.get('t_stat', np.nan))
                p_val = dm_result.get('p_value', np.nan)
            except Exception:
                # Fallback manual DM
                d = li - lj
                d_mean = np.mean(d)
                n = len(d)
                max_lag = int(np.floor(n ** (1/3)))
                d_centered = d - d_mean
                gamma_arr = np.zeros(max_lag + 1)
                for k in range(max_lag + 1):
                    gamma_arr[k] = np.mean(d_centered[k:] * d_centered[:n-k])
                hac_var = gamma_arr[0] + 2 * sum(
                    (1 - k/(max_lag+1)) * gamma_arr[k] for k in range(1, max_lag+1))
                t_stat = d_mean / np.sqrt(hac_var / n) if hac_var > 0 else 0
                p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), n-1))

            if t_stat < 0:
                winner = name_i
            elif t_stat > 0:
                winner = name_j
            else:
                winner = 'tie'

            harvey_pass = abs(t_stat) > 3.0

            results[f"{name_i}_vs_{name_j}"] = {
                't_stat': float(t_stat),
                'p_value': float(p_val),
                'n': int(len(li)),
                'winner': winner,
                'harvey_pass': bool(harvey_pass),
                'interpretation': f"{winner} wins {'(Harvey PASS)' if harvey_pass else '(Harvey FAIL, NS)'}"
            }

    return results


# ============================================================
# CHARTS
# ============================================================
def make_charts(all_results, charts_dir):
    """Generate cross-asset comparison charts."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    assets = list(all_results.keys())

    # Chart 1: QLIKE comparison grouped bar chart (all assets × all models)
    model_names = ['GJR', 'HAR', 'PRG_Basic', 'PRG_Extended', 'Separate']
    fig, axes = plt.subplots(1, len(assets), figsize=(6*len(assets), 6), sharey=False)
    if len(assets) == 1:
        axes = [axes]

    for ax, asset in zip(axes, assets):
        qlikes = []
        names = []
        for m in model_names:
            q = all_results[asset]['layer1_loss_functions'].get(m, {}).get('QLIKE', np.nan)
            if np.isfinite(q):
                qlikes.append(q)
                names.append(m)

        if not qlikes:
            continue

        colors = ['#e74c3c' if q == min(qlikes) else '#3498db' for q in qlikes]
        bars = ax.bar(names, qlikes, color=colors, edgecolor='black', linewidth=0.5)
        ax.set_ylabel('QLIKE (lower = better)', fontsize=10)
        ax.set_title(f'{asset}', fontsize=13, fontweight='bold')
        for bar, q in zip(bars, qlikes):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.001,
                    f'{q:.4f}', ha='center', va='bottom', fontsize=8)
        ax.tick_params(axis='x', rotation=20)

    plt.suptitle('K881: QLIKE Comparison Across Assets (OOS)', fontsize=15, y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'qlike_all_assets.png'), dpi=150, bbox_inches='tight')
    plt.close()

    # Chart 2: DM t-stat heatmap (PRG_Extended vs others, per asset)
    fig, ax = plt.subplots(figsize=(10, 5))
    comparisons = ['GJR', 'HAR', 'PRG_Basic', 'Separate']
    data_matrix = []
    for asset in assets:
        row = []
        dm_results = all_results[asset].get('layer5_dm_tests', {})
        for comp in comparisons:
            # Find the key
            key1 = f"PRG_Extended_vs_{comp}"
            key2 = f"{comp}_vs_PRG_Extended"
            if key1 in dm_results:
                t = dm_results[key1]['t_stat']
                # Positive t means second model (comp) wins; negative means first (PRG_Ext) wins
                # We want: negative = PRG_Ext better
                row.append(t)
            elif key2 in dm_results:
                t = dm_results[key2]['t_stat']
                # Flip sign: if key is "comp_vs_PRGExt" and t>0, PRGExt wins
                row.append(-t)
            else:
                row.append(np.nan)
        data_matrix.append(row)

    data_matrix = np.array(data_matrix)
    im = ax.imshow(data_matrix, cmap='RdYlGn_r', aspect='auto',
                   vmin=-6, vmax=6)
    ax.set_xticks(range(len(comparisons)))
    ax.set_xticklabels(comparisons, fontsize=11)
    ax.set_yticks(range(len(assets)))
    ax.set_yticklabels(assets, fontsize=11)

    for i in range(len(assets)):
        for j in range(len(comparisons)):
            val = data_matrix[i, j]
            if np.isfinite(val):
                color = 'white' if abs(val) > 3 else 'black'
                marker = '***' if abs(val) > 3 else ''
                ax.text(j, i, f'{val:.1f}{marker}', ha='center', va='center',
                        fontsize=11, fontweight='bold', color=color)

    ax.set_title('DM t-stat: PRG Extended vs Others (negative = PRG better)\n'
                 '*** = Harvey significant |t|>3', fontsize=12)
    plt.colorbar(im, ax=ax, label='DM t-statistic')
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'dm_heatmap.png'), dpi=150, bbox_inches='tight')
    plt.close()

    # Chart 3: Overnight variance share vs PRG advantage
    fig, ax = plt.subplots(figsize=(8, 6))
    ov_shares = []
    prg_advantages = []  # QLIKE improvement %
    labels = []
    for asset in assets:
        ov = all_results[asset]['session_decomposition']['overnight_var_share_pct']
        prg_q = all_results[asset]['layer1_loss_functions']['PRG_Extended']['QLIKE']
        gjr_q = all_results[asset]['layer1_loss_functions']['GJR']['QLIKE']
        improvement = (gjr_q - prg_q) / gjr_q * 100
        ov_shares.append(ov)
        prg_advantages.append(improvement)
        labels.append(asset)

    # Add TAIFEX reference point
    ov_shares.append(38.0)  # Approximate mid-range
    prg_advantages.append((0.448 - 0.198) / 0.448 * 100)  # K874d
    labels.append('TAIFEX')

    ax.scatter(ov_shares[:-1], prg_advantages[:-1], s=120, c='steelblue',
               edgecolors='black', linewidth=1.5, zorder=5)
    ax.scatter(ov_shares[-1], prg_advantages[-1], s=120, c='orange',
               edgecolors='black', linewidth=1.5, zorder=5, marker='D',
               label='TAIFEX (K874d)')

    for i, label in enumerate(labels):
        ax.annotate(label, (ov_shares[i], prg_advantages[i]),
                    textcoords="offset points", xytext=(8, 8), fontsize=11)

    ax.axhline(0, color='gray', linestyle='--', linewidth=0.8)
    ax.set_xlabel('Overnight Variance Share (%)', fontsize=12)
    ax.set_ylabel('PRG QLIKE Improvement over GJR (%)', fontsize=12)
    ax.set_title('K881: Overnight Variance Share vs PRG Advantage', fontsize=13)
    ax.legend(fontsize=10)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'overnight_vs_prg_advantage.png'), dpi=150)
    plt.close()

    # Chart 4: Spearman correlation comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    x_pos = np.arange(len(model_names))
    width = 0.25
    offsets = np.linspace(-width*(len(assets)-1)/2, width*(len(assets)-1)/2, len(assets))
    colors_assets = ['#2196F3', '#FF9800', '#4CAF50']

    for i, asset in enumerate(assets):
        rhos = []
        for m in model_names:
            sp = all_results[asset].get('layer3_spearman', {}).get(m, {})
            rhos.append(sp.get('rho', np.nan))
        ax.bar(x_pos + offsets[i], rhos, width=width, label=asset,
               color=colors_assets[i], edgecolor='black', linewidth=0.5)

    ax.set_xticks(x_pos)
    ax.set_xticklabels(model_names, fontsize=10)
    ax.set_ylabel('Spearman ρ', fontsize=12)
    ax.set_title('K881: Spearman Rank Correlation by Asset (OOS)', fontsize=13)
    ax.legend(fontsize=10)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'spearman_comparison.png'), dpi=150)
    plt.close()

    print(f"  Charts saved to {charts_dir}")


# ============================================================
# RUN ONE ASSET
# ============================================================
def run_single_asset(ticker, start_date, description):
    """Run the full 5-model comparison for one asset."""
    flush_print(f"\n{'='*60}")
    flush_print(f"  ASSET: {ticker} — {description}")
    flush_print(f"{'='*60}")

    t0 = datetime.now()

    # Load data
    df = load_asset_data(ticker, start_date)

    # Descriptive stats
    ov_share = df['r2_overnight'].mean() / df['sigma2_fullday'].mean() * 100
    in_share = 100 - ov_share
    print(f"  Overnight var share: {ov_share:.1f}%")
    print(f"  Intraday var share: {in_share:.1f}%")
    print(f"  c2c return: mean={df['r_c2c'].mean():.6f}, std={df['r_c2c'].std():.4f}")

    # IS/OOS split
    is_end = int(len(df) * IS_FRACTION)
    n_oos = len(df) - is_end
    is_end_date = df.index[is_end - 1].strftime('%Y-%m-%d')
    oos_start_date = df.index[is_end].strftime('%Y-%m-%d')
    print(f"  IS: {is_end} days ({df.index[0].date()} to {is_end_date})")
    print(f"  OOS: {n_oos} days ({oos_start_date} to {df.index[-1].date()})")

    if n_oos < 252:
        print(f"  WARNING: OOS < 252 days ({n_oos}). Results may be unreliable.")

    returns_c2c = df['r_c2c'].values
    r_overnight = df['r_overnight'].values
    r_intra = df['r_intra'].values
    r2_overnight = df['r2_overnight'].values
    r2_intra = df['r2_intra'].values
    sigma2_fullday = df['sigma2_fullday'].values

    # ---- Model forecasts ----
    flush_print(f"\n  Running OOS forecasts for {ticker}...")

    # GJR
    flush_print(f"    GJR-GARCH...")
    gjr_fc = gjr_oos_forecast(returns_c2c, is_end, refit_freq=REFIT_FREQ_GJR_HAR)
    n_gjr = np.sum(np.isfinite(gjr_fc[is_end:]))
    print(f"      {n_gjr} valid forecasts")

    # HAR
    flush_print(f"    HAR on σ²_fullday...")
    har_fc = har_oos_forecast(sigma2_fullday, is_end, refit_freq=REFIT_FREQ_GJR_HAR)
    n_har = np.sum(np.isfinite(har_fc[is_end:]))
    print(f"      {n_har} valid forecasts")

    # PRG Basic
    flush_print(f"    PRG Basic (6 params)...")
    prg_basic_fc = prg_oos_forecast(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end, extended=False, refit_freq=REFIT_FREQ_PRG
    )
    n_prg_b = np.sum(np.isfinite(prg_basic_fc[is_end:]))
    print(f"      {n_prg_b} valid forecasts")

    # PRG Extended
    flush_print(f"    PRG Extended (8 params)...")
    prg_ext_fc = prg_oos_forecast(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end, extended=True, refit_freq=REFIT_FREQ_PRG
    )
    n_prg_e = np.sum(np.isfinite(prg_ext_fc[is_end:]))
    print(f"      {n_prg_e} valid forecasts")

    # Separate GARCH
    flush_print(f"    Separate GARCH...")
    sep_fc = separate_garch_oos(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end, refit_freq=REFIT_FREQ_GJR_HAR
    )
    n_sep = np.sum(np.isfinite(sep_fc[is_end:]))
    print(f"      {n_sep} valid forecasts")

    # Sanity check
    model_names_list = ['GJR', 'HAR', 'PRG_Basic', 'PRG_Extended', 'Separate']
    all_fc = {
        'GJR': gjr_fc, 'HAR': har_fc, 'PRG_Basic': prg_basic_fc,
        'PRG_Extended': prg_ext_fc, 'Separate': sep_fc
    }
    for name in model_names_list:
        valid_fc = all_fc[name][is_end:][np.isfinite(all_fc[name][is_end:])]
        if len(valid_fc) > 0:
            print(f"      {name}: min={valid_fc.min():.2e}, mean={valid_fc.mean():.2e}, max={valid_fc.max():.2e}")
            if valid_fc.min() <= 0:
                print(f"      WARNING: {name} has non-positive forecasts!")

    # ---- Layer 1: Multiple Loss Functions ----
    print(f"\n  Layer 1: Loss Functions ({ticker})...")
    target_oos = sigma2_fullday[is_end:]
    forecasts_oos = {name: all_fc[name][is_end:] for name in model_names_list}

    layer1 = {}
    for name in model_names_list:
        losses = compute_all_losses(target_oos, forecasts_oos[name])
        layer1[name] = {k: v for k, v in losses.items() if k not in ('qlike_array', 'mse_array')}
        print(f"    {name}: QLIKE={losses['QLIKE']:.4f}, MSE={losses['MSE']:.2e}, "
              f"MAE={losses['MAE']:.4e}, MZ-R²={losses['MZ_R2']:.3f}")

    # Best per metric
    for metric in ['QLIKE', 'MSE', 'MAE', 'HMSE']:
        vals = {n: layer1[n][metric] for n in model_names_list if np.isfinite(layer1[n][metric])}
        if vals:
            best = min(vals, key=vals.get)
            print(f"    Best {metric}: {best} ({vals[best]:.4f})")
    vals_r2 = {n: layer1[n]['MZ_R2'] for n in model_names_list if np.isfinite(layer1[n]['MZ_R2'])}
    if vals_r2:
        best_r2 = max(vals_r2, key=vals_r2.get)
        print(f"    Best MZ-R²: {best_r2} ({vals_r2[best_r2]:.4f})")

    # ---- Layer 2: MCS ----
    print(f"\n  Layer 2: Model Confidence Set ({ticker})...")
    qlike_losses = {}
    for name in model_names_list:
        qlike_losses[name] = qlike_loss_array(target_oos, forecasts_oos[name])

    surviving, eliminated = model_confidence_set(qlike_losses, alpha=0.10, n_boot=5000)
    print(f"    Surviving (α=0.10): {surviving}")
    print(f"    Eliminated: {eliminated}")

    layer2 = {
        'surviving': surviving,
        'eliminated': {k: float(v) for k, v in eliminated.items()},
        'alpha': 0.10,
    }

    # ---- Layer 3: Spearman ----
    print(f"\n  Layer 3: Spearman ({ticker})...")
    layer3 = {}
    for name in model_names_list:
        sp = spearman_with_bootstrap(target_oos, forecasts_oos[name])
        layer3[name] = sp
        print(f"    {name}: ρ={sp['rho']:.3f} [{sp['ci_lo']:.3f}, {sp['ci_hi']:.3f}]")

    # ---- Layer 4: VaR ----
    print(f"\n  Layer 4: VaR Backtesting ({ticker})...")
    layer4 = {}
    for name in model_names_list:
        vr = var_backtest(returns_c2c[is_end:], forecasts_oos[name])
        layer4[name] = vr
        for level in ['VaR_1pct', 'VaR_5pct']:
            v = vr[level]
            kp = 'PASS' if v.get('kupiec_pass') else 'FAIL'
            cp = 'PASS' if v.get('cc_pass') else 'FAIL'
            print(f"    {name} {level}: VR={v['violation_rate']:.3f} "
                  f"(expect {v['expected_rate']:.2f}), "
                  f"Kupiec {kp}, Basel {v['basel']}")

    # ---- Layer 5: DM Tests ----
    print(f"\n  Layer 5: DM Tests ({ticker})...")
    dm_results = pairwise_dm_tests(qlike_losses, model_names_list)

    for pair, result in dm_results.items():
        print(f"    {pair}: t={result['t_stat']:.2f}, "
              f"Harvey {'PASS' if result['harvey_pass'] else 'FAIL'}, "
              f"Winner: {result['winner']}")

    # Key comparisons
    print(f"\n  === KEY: PRG vs Separate (cross-recursion value) for {ticker} ===")
    for key in dm_results:
        if 'PRG' in key and 'Separate' in key:
            r = dm_results[key]
            print(f"    {key}: t={r['t_stat']:.2f} → {r['interpretation']}")

    print(f"\n  === MAIN: PRG vs GJR for {ticker} ===")
    for key in dm_results:
        if 'PRG_Extended' in key and 'GJR' in key:
            r = dm_results[key]
            print(f"    {key}: t={r['t_stat']:.2f} → {r['interpretation']}")

    elapsed = (datetime.now() - t0).total_seconds()
    flush_print(f"\n  {ticker} runtime: {elapsed:.1f}s")

    # Build key findings for this asset
    findings = []
    qlikes = {n: layer1[n]['QLIKE'] for n in model_names_list}
    best_model = min(qlikes, key=qlikes.get)
    findings.append(f"Best QLIKE: {best_model} ({qlikes[best_model]:.4f})")

    prg_vs_gjr_key = [k for k in dm_results if 'PRG_Extended' in k and 'GJR' in k]
    if prg_vs_gjr_key:
        r = dm_results[prg_vs_gjr_key[0]]
        findings.append(f"PRG_Ext vs GJR: DM t={r['t_stat']:.2f} "
                       f"({'Harvey PASS' if r['harvey_pass'] else 'NS'})")

    prg_vs_sep_key = [k for k in dm_results if 'PRG_Extended' in k and 'Separate' in k]
    if prg_vs_sep_key:
        r = dm_results[prg_vs_sep_key[0]]
        findings.append(f"Cross-recursion (PRG vs Separate): DM t={r['t_stat']:.2f} "
                       f"({'Harvey PASS' if r['harvey_pass'] else 'NS'})")

    findings.append(f"MCS surviving: {surviving}")
    findings.append(f"Overnight var share: {ov_share:.1f}%")

    return {
        'ticker': ticker,
        'description': description,
        'period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'is_period': f"{df.index[0].date()} to {is_end_date}",
        'oos_period': f"{oos_start_date} to {df.index[-1].date()}",
        'n_total': len(df),
        'n_is': is_end,
        'n_oos': n_oos,
        'session_decomposition': {
            'overnight_var_share_pct': float(ov_share),
            'intraday_var_share_pct': float(in_share),
            'mean_sigma2_fullday': float(df['sigma2_fullday'].mean()),
            'mean_r2_overnight': float(df['r2_overnight'].mean()),
            'mean_r2_intraday': float(df['r2_intra'].mean()),
        },
        'descriptive_stats': {
            'c2c_return_mean': float(df['r_c2c'].mean()),
            'c2c_return_std': float(df['r_c2c'].std()),
            'overnight_return_mean': float(df['r_overnight'].mean()),
            'overnight_return_std': float(df['r_overnight'].std()),
            'intraday_return_mean': float(df['r_intra'].mean()),
            'intraday_return_std': float(df['r_intra'].std()),
            'skewness': float(sp_stats.skew(df['r_c2c'].values)),
            'kurtosis': float(sp_stats.kurtosis(df['r_c2c'].values)),
        },
        'layer1_loss_functions': layer1,
        'layer2_mcs': layer2,
        'layer3_spearman': layer3,
        'layer4_var': layer4,
        'layer5_dm_tests': dm_results,
        'key_findings': findings,
        'runtime_seconds': float(elapsed),
    }


# ============================================================
# MAIN
# ============================================================
def flush_print(*args, **kwargs):
    """Print and flush immediately."""
    print(*args, **kwargs)
    sys.stdout.flush()


def main():
    flush_print("=" * 70)
    flush_print("K881: PRG Multi-Asset Validation (QQQ, GLD, EEM)")
    flush_print("=" * 70)
    flush_print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    flush_print(f"Common target: σ²_fullday = r²_overnight + r²_intraday")
    flush_print(f"Models: GJR, HAR, PRG Basic, PRG Extended, Separate GARCH")
    flush_print(f"Assets: {list(ASSETS.keys())}")

    t0_global = datetime.now()
    all_results = {}

    for ticker, config in ASSETS.items():
        result = run_single_asset(ticker, config['start'], config['description'])
        all_results[ticker] = result

    # ---- Cross-asset summary ----
    print("\n" + "=" * 70)
    print("CROSS-ASSET SUMMARY")
    print("=" * 70)

    # Summary table
    print(f"\n{'Asset':<8} {'OV%':>6} {'Best QLIKE':>14} {'PRG_Ext QLIKE':>14} {'GJR QLIKE':>10} "
          f"{'DM t(PRG/GJR)':>14} {'Cross-rec t':>12} {'MCS survivors':>20}")
    print("-" * 105)

    cross_market = {}
    for ticker in ASSETS:
        r = all_results[ticker]
        ov = r['session_decomposition']['overnight_var_share_pct']
        prg_q = r['layer1_loss_functions']['PRG_Extended']['QLIKE']
        gjr_q = r['layer1_loss_functions']['GJR']['QLIKE']

        # Find DM t for PRG_Extended vs GJR
        dm_t_prg_gjr = np.nan
        for key, val in r['layer5_dm_tests'].items():
            if 'PRG_Extended' in key and 'GJR' in key:
                dm_t_prg_gjr = val['t_stat']
                break

        # Find DM t for PRG_Extended vs Separate (cross-recursion)
        dm_t_cross = np.nan
        for key, val in r['layer5_dm_tests'].items():
            if 'PRG_Extended' in key and 'Separate' in key:
                dm_t_cross = val['t_stat']
                break

        mcs_survivors = r['layer2_mcs']['surviving']

        qlikes_all = {n: r['layer1_loss_functions'][n]['QLIKE'] for n in r['layer1_loss_functions']}
        best_m = min(qlikes_all, key=qlikes_all.get)

        print(f"{ticker:<8} {ov:>5.1f}% {best_m:>14} {prg_q:>13.4f} {gjr_q:>10.4f} "
              f"{dm_t_prg_gjr:>13.2f} {dm_t_cross:>12.2f} {str(mcs_survivors):>20}")

        cross_market[ticker] = {
            'overnight_var_share_pct': float(ov),
            'best_model': best_m,
            'PRG_Extended_QLIKE': float(prg_q),
            'GJR_QLIKE': float(gjr_q),
            'QLIKE_improvement_pct': float((gjr_q - prg_q) / gjr_q * 100),
            'DM_t_PRGExt_vs_GJR': float(dm_t_prg_gjr) if np.isfinite(dm_t_prg_gjr) else None,
            'DM_t_cross_recursion': float(dm_t_cross) if np.isfinite(dm_t_cross) else None,
            'MCS_surviving': mcs_survivors,
        }

    # Add TAIFEX reference
    print(f"\n  Reference — TAIFEX (K874e): OV≈38%, PRG_Ext QLIKE=0.198, DM t=5.10 vs GJR")

    # ---- Charts ----
    print("\n  Generating cross-asset charts...")
    make_charts(all_results, CHARTS_DIR)

    # ---- Compile final results ----
    elapsed_total = (datetime.now() - t0_global).total_seconds()
    print(f"\n  Total runtime: {elapsed_total:.1f}s")

    # Build global key findings
    global_findings = []
    n_prg_wins = sum(1 for t in ASSETS if cross_market[t]['best_model'].startswith('PRG'))
    global_findings.append(f"PRG best QLIKE in {n_prg_wins}/{len(ASSETS)} assets")

    n_harvey_pass = sum(1 for t in ASSETS
                        if cross_market[t]['DM_t_PRGExt_vs_GJR'] is not None
                        and abs(cross_market[t]['DM_t_PRGExt_vs_GJR']) > 3.0)
    global_findings.append(f"PRG vs GJR Harvey PASS in {n_harvey_pass}/{len(ASSETS)} assets")

    n_cross_pass = sum(1 for t in ASSETS
                       if cross_market[t]['DM_t_cross_recursion'] is not None
                       and abs(cross_market[t]['DM_t_cross_recursion']) > 3.0)
    global_findings.append(f"Cross-recursion value (PRG vs Separate) Harvey PASS in {n_cross_pass}/{len(ASSETS)} assets")

    # Overnight share vs advantage
    ov_shares_list = [cross_market[t]['overnight_var_share_pct'] for t in ASSETS]
    improvements = [cross_market[t]['QLIKE_improvement_pct'] for t in ASSETS]
    if len(ov_shares_list) > 1:
        corr_ov_adv, _ = sp_stats.spearmanr(ov_shares_list, improvements)
        global_findings.append(f"Overnight share vs PRG improvement correlation: {corr_ov_adv:.2f}")

    # GLD special case
    gld = cross_market.get('GLD', {})
    if gld:
        global_findings.append(f"GLD (no leverage): Best={gld['best_model']}, "
                              f"PRG_Ext QLIKE={gld['PRG_Extended_QLIKE']:.4f}")

    final_results = {
        'experiment_id': 'K881',
        'title': 'PRG Multi-Asset Validation (QQQ, GLD, EEM)',
        'type': 'empirical',
        'data_source': 'yfinance',
        'assets_tested': list(ASSETS.keys()),
        'common_target': 'σ²_fullday = r²_overnight + r²_intraday',
        'models': ['GJR-GARCH', 'HAR-proxy', 'PRG_Basic', 'PRG_Extended', 'Separate_GARCH'],
        'is_fraction': IS_FRACTION,
        'refit_freq_gjr_har': REFIT_FREQ_GJR_HAR,
        'refit_freq_prg': REFIT_FREQ_PRG,
        'per_asset_results': all_results,
        'cross_market_summary': cross_market,
        'global_key_findings': global_findings,
        'cross_market_reference': {
            'TAIFEX_K874e': {
                'overnight_var_share_pct': '27-50% (non-stationary)',
                'PRG_Extended_QLIKE': 0.198,
                'GJR_QLIKE': 0.448,
                'DM_t_PRGExt_vs_GJR': 5.10,
            }
        },
        'runtime_total_seconds': float(elapsed_total),
        'references': [
            'Patton (2011): Volatility forecast comparison using imperfect proxies',
            'Hansen, Lunde & Nason (2011): Model Confidence Set',
            'Bollerslev & Ghysels (1996): Periodic GARCH',
            'Corsi (2009): HAR-RV',
            'Kupiec (1995): Proportion of failures VaR test',
            'Christoffersen (1998): Conditional coverage VaR test',
            'Lai et al. (2024): PRS concept',
        ],
    }

    # JSON serialization
    def convert(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj) if np.isfinite(obj) else None
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        return obj

    def deep_convert(obj):
        if isinstance(obj, dict):
            return {k: deep_convert(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [deep_convert(v) for v in obj]
        else:
            return convert(obj)

    final_results = deep_convert(final_results)

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(final_results, f, indent=2, default=str)

    print(f"\n  Results saved to {OUTPUT_FILE}")
    print(f"  Charts saved to {CHARTS_DIR}/")

    print("\n" + "=" * 70)
    print("GLOBAL KEY FINDINGS:")
    for f_str in global_findings:
        print(f"  * {f_str}")

    print("\nPER-ASSET FINDINGS:")
    for ticker in ASSETS:
        print(f"\n  {ticker}:")
        for f_str in all_results[ticker]['key_findings']:
            print(f"    * {f_str}")
    print("=" * 70)


if __name__ == '__main__':
    main()
