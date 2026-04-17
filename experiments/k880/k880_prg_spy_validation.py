#!/usr/bin/env python3
"""
K880: PRG Cross-Market Validation on SPY (Daily Frequency)
===========================================================

Research Question (EMPIRICAL):
  K874c/d/e validated PRG on TAIFEX — cross-recursion DM t=5.10 vs GJR.
  Does this advantage hold on SPY using daily OHLC proxies?

Session Decomposition (daily frequency, no tick data):
  r_overnight = log(open_t / close_{t-1})  → r²_overnight proxy
  r_intra = log(close_t / open_t)           → r²_intra proxy
  σ²_fullday = r²_overnight + r²_intra      → common target

Models:
  1. GJR-GARCH(1,1) on close-to-close returns (standard benchmark)
  2. HAR-proxy: HAR on σ²_fullday (log-space, daily/5d/22d lags)
  3. PRG Basic (6 params): periodic GARCH alternating overnight/intraday sessions
     h_n = ω_{s_n} + α_{s_n}·x_{n-1} + β_{s_n}·h_{n-1}
  4. PRG Extended (8 params): add leverage γ_{s_n} for negative returns
  5. Separate GARCH: independent GARCH for each session (no cross-recursion)

Key Comparison: PRG vs Separate GARCH isolates cross-recursion value.

Evaluation (common target σ²_fullday):
  Layer 1: QLIKE, MSE, MAE, HMSE, MZ-R² (multiple loss functions)
  Layer 2: MCS (Model Confidence Set, Hansen Lunde Nason 2011)
  Layer 3: Spearman rank correlation with bootstrap CI
  Layer 4: VaR 1% + 5% (Kupiec + Christoffersen + Basel)
  Layer 5: DM test pairwise (Harvey |t|>3.0)

Data: yfinance SPY + ^VIX, 2000-01 to 2026-04
IS: 2000-2018, OOS: 2019-2026 (~1750 days)

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
# Numba-accelerated inner loops
# ============================================================
@njit(cache=True)
def _gjr_negll_numba(omega, alpha, gamma_p, beta, r):
    """GJR-GARCH negative log-likelihood (numba-accelerated)."""
    T = len(r)
    h = np.empty(T)
    h[0] = 0.0
    for i in range(min(50, T)):
        h[0] += r[i] ** 2
    h[0] /= min(50, T)
    if h[0] < 1e-12:
        h[0] = 1e-8
    ll = 0.0
    for t in range(1, T):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        h[t] = omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * indicator + beta * h[t-1]
        if h[t] < 1e-12:
            h[t] = 1e-12
        ll += -0.5*np.log(2*np.pi) - 0.5*np.log(h[t]) - 0.5*r[t]**2/h[t]
    return -ll


@njit(cache=True)
def _gjr_propagate_numba(omega, alpha, gamma_p, beta, r, h0, start, end):
    """Propagate GJR state from start to end. Returns final h."""
    h = h0
    for t in range(start, end):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        h = omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * indicator + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _garch_negll_numba(omega, alpha, beta, r):
    """GARCH(1,1) negative log-likelihood (numba-accelerated)."""
    T = len(r)
    h = np.empty(T)
    h[0] = 0.0
    for i in range(min(50, T)):
        h[0] += r[i] ** 2
    h[0] /= min(50, T)
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
def _garch_propagate_numba(omega, alpha, beta, r, h0, start, end):
    """Propagate GARCH(1,1) state. Returns final h."""
    h = h0
    for t in range(start, end):
        h = omega + alpha * r[t-1]**2 + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _prg_negll_numba(params, r_seq, x_seq, s_seq, n_total, extended):
    """PRG negative log-likelihood (numba-accelerated)."""
    omega_0, alpha_0, beta_0 = params[0], params[1], params[2]
    omega_1, alpha_1, beta_1 = params[3], params[4], params[5]
    gamma_0 = params[6] if extended else 0.0
    gamma_1 = params[7] if extended else 0.0

    h = np.empty(n_total)
    h[0] = 0.0
    count = min(100, n_total)
    for i in range(count):
        h[0] += x_seq[i]
    h[0] /= count
    if h[0] < 1e-12:
        h[0] = 1e-8

    for t in range(1, n_total):
        st = s_seq[t]
        if st == 0:
            lev = gamma_0 * x_seq[t-1] * (1.0 if r_seq[t-1] < 0 else 0.0)
            h[t] = omega_0 + alpha_0 * x_seq[t-1] + lev + beta_0 * h[t-1]
        else:
            lev = gamma_1 * x_seq[t-1] * (1.0 if r_seq[t-1] < 0 else 0.0)
            h[t] = omega_1 + alpha_1 * x_seq[t-1] + lev + beta_1 * h[t-1]
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
def _prg_propagate_days_numba(omega_0, alpha_0, beta_0, gamma_0,
                              omega_1, alpha_1, beta_1, gamma_1,
                              r_overnight, r_intra, r2_overnight, r2_intra,
                              start_d, end_d, h_init):
    """Propagate PRG state through days [start_d, end_d). Returns h after last intraday."""
    h = h_init
    for d in range(start_d, end_d):
        # Overnight session (s=0)
        if d > 0:
            x_prev = r2_intra[d-1]
            r_prev = r_intra[d-1]
        else:
            x_prev = r2_overnight[0]
            r_prev = r_overnight[0]
        lev = gamma_0 * x_prev * (1.0 if r_prev < 0 else 0.0)
        h = omega_0 + alpha_0 * x_prev + lev + beta_0 * h
        if h < 1e-12:
            h = 1e-12

        # Intraday session (s=1)
        x_prev_in = r2_overnight[d]
        r_prev_in = r_overnight[d]
        lev = gamma_1 * x_prev_in * (1.0 if r_prev_in < 0 else 0.0)
        h = omega_1 + alpha_1 * x_prev_in + lev + beta_1 * h
        if h < 1e-12:
            h = 1e-12
    return h

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k880_results.json")
CHARTS_DIR = os.path.join(SCRIPT_DIR, "k880_charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# OOS split
IS_END_DATE = "2018-12-31"
REFIT_FREQ = 63  # quarterly refit

# PRG optimization
PRG_N_STARTS = 5
PRG_REFIT_FREQ = 126  # semi-annual refit for PRG (heavier optimization)


# ============================================================
# DATA LOADING
# ============================================================
def load_spy_data():
    """Load SPY OHLC from yfinance and compute session decomposition."""
    import yfinance as yf

    print("Downloading SPY data from yfinance...")
    spy = yf.download("SPY", start="2000-01-01", end="2026-04-05", auto_adjust=True)
    print(f"  SPY: {len(spy)} days, {spy.index[0].date()} to {spy.index[-1].date()}")

    # Flatten MultiIndex columns if present
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    df = pd.DataFrame(index=spy.index)
    df['open'] = spy['Open'].values
    df['high'] = spy['High'].values
    df['low'] = spy['Low'].values
    df['close'] = spy['Close'].values

    # Session decomposition
    df['prev_close'] = df['close'].shift(1)
    df['r_overnight'] = np.log(df['open'] / df['prev_close'])
    df['r_intra'] = np.log(df['close'] / df['open'])
    df['r_c2c'] = np.log(df['close'] / df['prev_close'])

    # Variance proxies
    df['r2_overnight'] = df['r_overnight'] ** 2
    df['r2_intra'] = df['r_intra'] ** 2
    df['sigma2_fullday'] = df['r2_overnight'] + df['r2_intra']

    # Also compute Parkinson variance for comparison
    df['parkinson'] = (np.log(df['high'] / df['low'])) ** 2 / (4 * np.log(2))

    # Drop first row (no prev_close)
    df = df.iloc[1:].dropna(subset=['r_overnight', 'r_intra', 'sigma2_fullday'])

    print(f"  After processing: {len(df)} days")
    print(f"  Mean σ²_fullday: {df['sigma2_fullday'].mean():.6f}")
    print(f"  Mean r²_overnight: {df['r2_overnight'].mean():.6f} ({df['r2_overnight'].mean()/df['sigma2_fullday'].mean()*100:.1f}% of fullday)")
    print(f"  Mean r²_intra: {df['r2_intra'].mean():.6f} ({df['r2_intra'].mean()/df['sigma2_fullday'].mean()*100:.1f}% of fullday)")

    return df


# ============================================================
# MODEL 1: GJR-GARCH OOS (close-to-close returns)
# ============================================================
def gjr_oos_forecast(returns, is_end, refit_freq=63):
    """GJR-GARCH(1,1) OOS on c2c returns, recursive variance propagation.
    Uses numba-accelerated log-likelihood and state propagation."""
    n = len(returns)
    forecasts = np.full(n, np.nan)

    def gjr_negll_wrapper(params, r):
        return _gjr_negll_numba(params[0], params[1], params[2], params[3], r)

    eps = 1e-8
    bounds = [(eps, 1e-3), (eps, 0.5), (0.0, 0.5), (eps, 0.999)]
    current_params = None
    h_state = np.var(returns[:min(50, n)])

    for t in range(is_end, n):
        # Refit periodically
        if (t - is_end) % refit_freq == 0 or t == is_end:
            r_train = returns[:t].copy()
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
                    result = minimize(gjr_negll_wrapper, x0, args=(r_train,),
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
                if h0 < 1e-12: h0 = 1e-8
                h_state = _gjr_propagate_numba(omega, alpha, gamma_p, beta, returns, h0, 1, t)

        if current_params is not None:
            omega, alpha, gamma_p, beta = current_params
            indicator = 1.0 if returns[t-1] < 0 else 0.0
            h_state = omega + alpha*returns[t-1]**2 + gamma_p*returns[t-1]**2*indicator + beta*h_state
            if h_state < 1e-12: h_state = 1e-12
            forecasts[t] = h_state

    return forecasts


# ============================================================
# MODEL 2: HAR on σ²_fullday (log-space)
# ============================================================
def har_oos_forecast(sigma2_series, is_end, refit_freq=63):
    """HAR on log(σ²_fullday) with daily/5d/22d lags. Predict t from t-1."""
    eps = 1e-12
    log_sig = np.log(np.clip(sigma2_series, eps, None))
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

        if beta is not None and np.isfinite(log_d[t]) and np.isfinite(log_5d[t]) and np.isfinite(log_22d[t]):
            x_t = np.array([1.0, log_d[t], log_5d[t], log_22d[t]])
            log_forecast = x_t @ beta
            forecasts[t] = np.exp(log_forecast)

    return forecasts


# ============================================================
# MODEL 3/4: PRG (Periodic Realized GARCH)
# ============================================================
def estimate_prg_spy(r_overnight, r_intra, r2_overnight, r2_intra,
                     extended=False, n_starts=5):
    """
    Estimate PRG via MLE on SPY daily OHLC decomposition.

    Interleaved sequence: overnight_0, intra_0, overnight_1, intra_1, ...
    Session s=0: overnight, s=1: intraday

    h_n = ω_{s_n} + α_{s_n}·x_{n-1} + β_{s_n}·h_{n-1} [+ γ_{s_n}·x_{n-1}·I(r<0)]

    where x_{n-1} is the realized variance proxy of the previous session.
    """
    n_days = len(r_overnight)
    # Interleave: session 0=overnight, session 1=intraday
    # Total observations = 2 * n_days
    n_total = 2 * n_days

    # Build interleaved arrays (vectorized)
    r_seq = np.empty(n_total)
    x_seq = np.empty(n_total)
    s_seq = np.empty(n_total, dtype=np.int64)

    r_seq[0::2] = r_overnight
    r_seq[1::2] = r_intra
    x_seq[0::2] = r2_overnight
    x_seq[1::2] = r2_intra
    s_seq[0::2] = 0
    s_seq[1::2] = 1

    ext_flag = extended

    def neg_loglik(params):
        p = np.zeros(8)
        p[:len(params)] = params
        if not ext_flag:
            p[6] = 0.0
            p[7] = 0.0
        return _prg_negll_numba(p, r_seq, x_seq, s_seq, n_total, ext_flag)

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
            if extended: x0 += [0.05, 0.05]
        else:
            x0 = [rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.40), rng.uniform(0.50, 0.95),
                   rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.40), rng.uniform(0.50, 0.95)]
            if extended: x0 += [rng.uniform(0.0, 0.2), rng.uniform(0.0, 0.2)]

        try:
            result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                              options={'maxiter': 2000, 'ftol': 1e-10})
            if result.fun < best_nll:
                best_nll = result.fun
                best_params = result.x
        except Exception:
            continue

    return best_params, -best_nll if best_params is not None else None


def prg_oos_forecast(r_overnight, r_intra, r2_overnight, r2_intra,
                     is_end, extended=False, refit_freq=126):
    """
    PRG OOS forecast on SPY. Predicts σ²_fullday = h_overnight + h_intraday.

    OPTIMIZED: Only rebuild state from scratch on refit. Between refits,
    propagate h incrementally (O(n) total instead of O(n²)).
    Uses numba-accelerated state propagation.
    """
    n_days = len(r_overnight)
    forecasts = np.full(n_days, np.nan)

    current_params = None
    h_state = None

    # Parse params helper
    def _parse(params):
        o0, a0, b0 = params[0], params[1], params[2]
        o1, a1, b1 = params[3], params[4], params[5]
        g0 = params[6] if extended and len(params) > 6 else 0.0
        g1 = params[7] if extended and len(params) > 7 else 0.0
        return o0, a0, b0, g0, o1, a1, b1, g1

    for t in range(is_end, n_days):
        # Refit periodically
        if (t - is_end) % refit_freq == 0 or t == is_end:
            params, ll = estimate_prg_spy(
                r_overnight[:t], r_intra[:t],
                r2_overnight[:t], r2_intra[:t],
                extended=extended, n_starts=PRG_N_STARTS
            )
            if params is not None:
                current_params = params
                o0, a0, b0, g0, o1, a1, b1, g1 = _parse(current_params)

                # Rebuild full state from scratch on refit (numba-accelerated)
                h_init = np.mean(r2_overnight[:min(50, t)] + r2_intra[:min(50, t)]) / 2
                if h_init < 1e-12: h_init = 1e-8
                h_state = _prg_propagate_days_numba(
                    o0, a0, b0, g0, o1, a1, b1, g1,
                    r_overnight, r_intra, r2_overnight, r2_intra,
                    0, t, h_init
                )

        if current_params is None or h_state is None:
            continue

        o0, a0, b0, g0, o1, a1, b1, g1 = _parse(current_params)

        # Forecast day t: overnight_t then intraday_t
        # h_state is after intraday of day t-1

        # Overnight forecast (s=0)
        x_prev = r2_intra[t-1]
        r_prev = r_intra[t-1]
        lev = g0 * x_prev * (1.0 if r_prev < 0 else 0.0)
        h_ov_t = o0 + a0 * x_prev + lev + b0 * h_state
        if h_ov_t < 1e-12: h_ov_t = 1e-12

        # Intraday forecast (s=1) — uses observed overnight of day t
        x_prev_in = r2_overnight[t]
        r_prev_in = r_overnight[t]
        lev = g1 * x_prev_in * (1.0 if r_prev_in < 0 else 0.0)
        h_in_t = o1 + a1 * x_prev_in + lev + b1 * h_ov_t
        if h_in_t < 1e-12: h_in_t = 1e-12

        forecasts[t] = h_ov_t + h_in_t

        # Propagate state through day t incrementally (numba-accelerated)
        h_state = _prg_propagate_days_numba(
            o0, a0, b0, g0, o1, a1, b1, g1,
            r_overnight, r_intra, r2_overnight, r2_intra,
            t, t+1, h_state
        )

    return forecasts


# ============================================================
# MODEL 5: Separate GARCH (no cross-recursion)
# ============================================================
def separate_garch_oos(r_overnight, r_intra, r2_overnight, r2_intra,
                       is_end, refit_freq=63):
    """
    Two independent GARCH(1,1) — one for overnight, one for intraday.
    No cross-session h propagation. Uses numba-accelerated log-likelihood.
    σ²_fullday = h_overnight + h_intraday.
    """
    n_days = len(r_overnight)
    forecasts = np.full(n_days, np.nan)

    def garch_negll_wrapper(params, r):
        return _garch_negll_numba(params[0], params[1], params[2], r)

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
            r_ov_train = r_overnight[:t].copy()
            best_nll = np.inf
            best_p = None
            for i in range(3):
                if i == 0:
                    x0 = [np.var(r_ov_train)*0.05, 0.08, 0.85]
                else:
                    x0 = [rng.uniform(1e-8, 1e-4), rng.uniform(0.02, 0.2),
                           rng.uniform(0.7, 0.95)]
                try:
                    result = minimize(garch_negll_wrapper, x0, args=(r_ov_train,),
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
                if h0 < 1e-12: h0 = 1e-8
                h_ov_state = _garch_propagate_numba(omega, alpha, beta, r_overnight, h0, 1, t)

            # Fit intraday GARCH
            r_in_train = r_intra[:t].copy()
            best_nll = np.inf
            best_p = None
            for i in range(3):
                if i == 0:
                    x0 = [np.var(r_in_train)*0.05, 0.08, 0.85]
                else:
                    x0 = [rng.uniform(1e-8, 1e-4), rng.uniform(0.02, 0.2),
                           rng.uniform(0.7, 0.95)]
                try:
                    result = minimize(garch_negll_wrapper, x0, args=(r_in_train,),
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
                if h0 < 1e-12: h0 = 1e-8
                h_in_state = _garch_propagate_numba(omega, alpha, beta, r_intra, h0, 1, t)

        # Propagate one step
        if ov_params is not None:
            omega, alpha, beta = ov_params
            h_ov_state = omega + alpha * r_overnight[t-1]**2 + beta * h_ov_state
            if h_ov_state < 1e-12: h_ov_state = 1e-12

        if in_params is not None:
            omega, alpha, beta = in_params
            h_in_state = omega + alpha * r_intra[t-1]**2 + beta * h_in_state
            if h_in_state < 1e-12: h_in_state = 1e-12

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
# LAYER 2: Model Confidence Set (simplified bootstrap)
# ============================================================
def model_confidence_set(loss_dict, alpha=0.10, n_boot=5000):
    """
    Simplified MCS using bootstrap elimination.
    loss_dict: {model_name: loss_array}
    Returns surviving models at significance level alpha.
    """
    model_names = list(loss_dict.keys())
    n_models = len(model_names)

    # Align to common valid observations
    n_obs = min(len(v) for v in loss_dict.values())
    losses = {}
    for name in model_names:
        arr = loss_dict[name][:n_obs]
        valid = np.isfinite(arr)
        losses[name] = arr

    # Find common valid indices
    common_valid = np.ones(n_obs, dtype=bool)
    for name in model_names:
        common_valid &= np.isfinite(losses[name])

    idx = np.where(common_valid)[0]
    if len(idx) < 100:
        return model_names, {}  # Not enough data

    aligned_losses = {name: losses[name][idx] for name in model_names}
    T = len(idx)

    surviving = list(model_names)
    eliminated = {}
    rng = np.random.RandomState(42)

    while len(surviving) > 1:
        # Compute mean loss differences
        mean_losses = {name: np.mean(aligned_losses[name]) for name in surviving}

        # T_R statistic: max relative performance
        worst_name = max(surviving, key=lambda n: mean_losses[n])

        # Bootstrap test: is the worst model significantly worse?
        d_arrays = {}
        for name in surviving:
            if name != worst_name:
                d_arrays[name] = aligned_losses[worst_name] - aligned_losses[name]

        # Bootstrap p-value for T_R
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
            break  # Cannot eliminate more

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
        idx = rng.randint(0, n, n)
        br, _ = sp_stats.spearmanr(r[idx], f[idx])
        boot_rhos.append(br)
    boot_rhos = np.array(boot_rhos)
    ci_lo = np.percentile(boot_rhos, 2.5)
    ci_hi = np.percentile(boot_rhos, 97.5)

    return {'rho': float(rho), 'p': float(p), 'ci_lo': float(ci_lo), 'ci_hi': float(ci_hi), 'n': n}


# ============================================================
# LAYER 4: VaR Backtesting
# ============================================================
def var_backtest(returns, sigma2_forecasts, alpha_levels=[0.01, 0.05]):
    """VaR backtesting with Kupiec + Christoffersen tests."""
    valid = np.isfinite(returns) & np.isfinite(sigma2_forecasts) & (sigma2_forecasts > 0)
    r = returns[valid]
    s2 = sigma2_forecasts[valid]
    n = len(r)

    results = {}
    for alpha in alpha_levels:
        z = sp_stats.norm.ppf(alpha)
        var_level = z * np.sqrt(s2)  # VaR is negative

        violations = r < var_level
        n_violations = int(np.sum(violations))
        vr = n_violations / n if n > 0 else np.nan

        # Kupiec LR test
        if n_violations > 0 and n_violations < n:
            lr_uc = -2 * (n_violations * np.log(alpha) + (n - n_violations) * np.log(1 - alpha)
                         - n_violations * np.log(vr) - (n - n_violations) * np.log(1 - vr))
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
                lr_ind = -2 * ((n00 + n10) * np.log(1 - p_hat) + (n01 + n11) * np.log(p_hat)
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

        results[f"VaR_{int(alpha*100)}pct"] = {
            'n': n,
            'n_violations': n_violations,
            'violation_rate': float(vr),
            'expected_rate': float(alpha),
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
def pairwise_dm_tests(model_losses, model_names):
    """Pairwise DM tests between all model pairs using QLIKE loss."""
    results = {}
    for i in range(len(model_names)):
        for j in range(i+1, len(model_names)):
            name_i = model_names[i]
            name_j = model_names[j]

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
                d_var = np.var(d, ddof=1)
                n = len(d)
                # Newey-West HAC
                max_lag = int(np.floor(n ** (1/3)))
                gamma = np.zeros(max_lag + 1)
                d_centered = d - d_mean
                for k in range(max_lag + 1):
                    gamma[k] = np.mean(d_centered[k:] * d_centered[:n-k])
                hac_var = gamma[0] + 2 * sum((1 - k/(max_lag+1)) * gamma[k] for k in range(1, max_lag+1))
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
def make_charts(df_oos, forecasts_dict, target_oos, charts_dir):
    """Generate comparison charts."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Chart 1: QLIKE comparison bar chart
    fig, ax = plt.subplots(figsize=(10, 6))
    names = []
    qlikes = []
    for name, fc in forecasts_dict.items():
        ql = qlike_loss_array(target_oos, fc)
        valid = ql[np.isfinite(ql)]
        if len(valid) > 0:
            names.append(name)
            qlikes.append(np.mean(valid))

    colors = ['#e74c3c' if q == min(qlikes) else '#3498db' for q in qlikes]
    bars = ax.bar(names, qlikes, color=colors, edgecolor='black', linewidth=0.5)
    ax.set_ylabel('QLIKE (lower = better)', fontsize=12)
    ax.set_title('K880: QLIKE Comparison — PRG on SPY (OOS 2019-2026)', fontsize=14)
    for bar, q in zip(bars, qlikes):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.001,
                f'{q:.4f}', ha='center', va='bottom', fontsize=10)
    plt.xticks(rotation=15, ha='right')
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'qlike_comparison.png'), dpi=150)
    plt.close()

    # Chart 2: Rolling 60-day QLIKE ratio (PRG Extended / GJR)
    if 'PRG_Extended' in forecasts_dict and 'GJR' in forecasts_dict:
        ql_prg = qlike_loss_array(target_oos, forecasts_dict['PRG_Extended'])
        ql_gjr = qlike_loss_array(target_oos, forecasts_dict['GJR'])

        valid = np.isfinite(ql_prg) & np.isfinite(ql_gjr)
        dates_v = df_oos.index[valid]
        ratio = pd.Series(ql_prg[valid] / np.clip(ql_gjr[valid], 1e-12, None),
                          index=dates_v)
        rolling_ratio = ratio.rolling(60).mean()

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(rolling_ratio.index, rolling_ratio.values, 'b-', linewidth=1.5,
                label='PRG_Ext / GJR QLIKE ratio (60d MA)')
        ax.axhline(1.0, color='red', linestyle='--', linewidth=1, label='Equal performance')
        ax.fill_between(rolling_ratio.index, rolling_ratio.values, 1.0,
                        where=rolling_ratio.values < 1, alpha=0.3, color='green',
                        label='PRG better')
        ax.fill_between(rolling_ratio.index, rolling_ratio.values, 1.0,
                        where=rolling_ratio.values > 1, alpha=0.3, color='red',
                        label='GJR better')
        ax.set_title('K880: Rolling QLIKE Ratio — PRG Extended vs GJR (SPY OOS)', fontsize=13)
        ax.set_ylabel('QLIKE Ratio (< 1 = PRG better)')
        ax.legend(loc='upper left', fontsize=9)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'rolling_qlike_ratio.png'), dpi=150)
        plt.close()

    # Chart 3: Forecast vs realized scatter (PRG Extended)
    if 'PRG_Extended' in forecasts_dict:
        fc = forecasts_dict['PRG_Extended']
        valid = np.isfinite(target_oos) & np.isfinite(fc) & (fc > 0) & (target_oos > 0)
        fig, ax = plt.subplots(figsize=(8, 8))
        ax.scatter(fc[valid]*1e4, target_oos[valid]*1e4, alpha=0.15, s=8, c='steelblue')
        lim = max(np.percentile(fc[valid]*1e4, 99), np.percentile(target_oos[valid]*1e4, 99))
        ax.plot([0, lim], [0, lim], 'r--', linewidth=1, label='45° line')
        ax.set_xlabel('PRG Extended Forecast (×10⁴)', fontsize=11)
        ax.set_ylabel('Realized σ²_fullday (×10⁴)', fontsize=11)
        ax.set_title('K880: PRG Extended — Forecast vs Realized (SPY)', fontsize=13)
        ax.set_xlim(0, lim)
        ax.set_ylim(0, lim)
        ax.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'prg_scatter.png'), dpi=150)
        plt.close()

    print(f"  Charts saved to {charts_dir}")


# ============================================================
# MAIN
# ============================================================
def main():
    # Use flush for all prints so progress is visible in real-time
    import builtins
    _original_print = builtins.print
    def print(*args, **kwargs):
        kwargs.setdefault('flush', True)
        _original_print(*args, **kwargs)

    print("=" * 70)
    print("K880: PRG Cross-Market Validation on SPY (Daily Frequency)")
    print("=" * 70)

    # Warm up numba JIT (first call compiles)
    print("\n  Warming up numba JIT...")
    _dummy_r = np.array([0.01, -0.02, 0.015, -0.005, 0.01], dtype=np.float64)
    _gjr_negll_numba(1e-5, 0.1, 0.05, 0.85, _dummy_r)
    _garch_negll_numba(1e-5, 0.1, 0.85, _dummy_r)
    _prg_negll_numba(np.zeros(8), _dummy_r, np.abs(_dummy_r), np.array([0,1,0,1,0], dtype=np.int64), 5, False)
    _prg_propagate_days_numba(1e-5, 0.1, 0.85, 0.0, 1e-5, 0.1, 0.85, 0.0,
                              _dummy_r, _dummy_r, _dummy_r**2, _dummy_r**2, 0, 2, 1e-5)
    _gjr_propagate_numba(1e-5, 0.1, 0.05, 0.85, _dummy_r, 1e-5, 1, 4)
    _garch_propagate_numba(1e-5, 0.1, 0.85, _dummy_r, 1e-5, 1, 4)
    print("  JIT compilation done.")

    t0 = datetime.now()

    # ---- Data ----
    print("\n[1/6] Loading and processing SPY data...")
    df = load_spy_data()

    # Descriptive stats
    print(f"\n  Descriptive statistics:")
    print(f"    Total days: {len(df)}")
    print(f"    Date range: {df.index[0].date()} to {df.index[-1].date()}")
    print(f"    c2c return: mean={df['r_c2c'].mean():.6f}, std={df['r_c2c'].std():.4f}")
    print(f"    Overnight return: mean={df['r_overnight'].mean():.6f}, std={df['r_overnight'].std():.4f}")
    print(f"    Intraday return: mean={df['r_intra'].mean():.6f}, std={df['r_intra'].std():.4f}")
    print(f"    Overnight var share: {df['r2_overnight'].mean() / df['sigma2_fullday'].mean() * 100:.1f}%")
    print(f"    Intraday var share: {df['r2_intra'].mean() / df['sigma2_fullday'].mean() * 100:.1f}%")

    # IS/OOS split
    is_mask = df.index <= IS_END_DATE
    is_end = int(np.sum(is_mask))
    oos_mask = df.index > IS_END_DATE
    n_oos = int(np.sum(oos_mask))
    print(f"\n  IS: {is_end} days ({df.index[0].date()} to {IS_END_DATE})")
    print(f"  OOS: {n_oos} days ({df.index[is_end].date()} to {df.index[-1].date()})")

    returns_c2c = df['r_c2c'].values
    r_overnight = df['r_overnight'].values
    r_intra = df['r_intra'].values
    r2_overnight = df['r2_overnight'].values
    r2_intra = df['r2_intra'].values
    sigma2_fullday = df['sigma2_fullday'].values

    # ---- Model forecasts ----
    print("\n[2/6] Running OOS forecasts...")

    # GJR
    print("  GJR-GARCH...")
    gjr_fc = gjr_oos_forecast(returns_c2c, is_end, refit_freq=REFIT_FREQ)
    n_gjr = np.sum(np.isfinite(gjr_fc[is_end:]))
    print(f"    GJR: {n_gjr} valid forecasts")

    # HAR
    print("  HAR on σ²_fullday...")
    har_fc = har_oos_forecast(sigma2_fullday, is_end, refit_freq=REFIT_FREQ)
    n_har = np.sum(np.isfinite(har_fc[is_end:]))
    print(f"    HAR: {n_har} valid forecasts")

    # PRG Basic
    print("  PRG Basic (6 params)...")
    prg_basic_fc = prg_oos_forecast(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end, extended=False, refit_freq=PRG_REFIT_FREQ
    )
    n_prg_b = np.sum(np.isfinite(prg_basic_fc[is_end:]))
    print(f"    PRG Basic: {n_prg_b} valid forecasts")

    # PRG Extended
    print("  PRG Extended (8 params)...")
    prg_ext_fc = prg_oos_forecast(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end, extended=True, refit_freq=PRG_REFIT_FREQ
    )
    n_prg_e = np.sum(np.isfinite(prg_ext_fc[is_end:]))
    print(f"    PRG Extended: {n_prg_e} valid forecasts")

    # Separate GARCH
    print("  Separate GARCH (no cross-recursion)...")
    sep_fc = separate_garch_oos(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end, refit_freq=REFIT_FREQ
    )
    n_sep = np.sum(np.isfinite(sep_fc[is_end:]))
    print(f"    Separate: {n_sep} valid forecasts")

    # Sanity check: all forecasts > 0
    for name, fc in [('GJR', gjr_fc), ('HAR', har_fc), ('PRG_Basic', prg_basic_fc),
                      ('PRG_Extended', prg_ext_fc), ('Separate', sep_fc)]:
        valid_fc = fc[is_end:][np.isfinite(fc[is_end:])]
        if len(valid_fc) > 0:
            print(f"    {name}: min={valid_fc.min():.2e}, mean={valid_fc.mean():.2e}, max={valid_fc.max():.2e}")
            assert valid_fc.min() > 0, f"{name} has non-positive forecasts!"

    # ---- Layer 1: Multiple Loss Functions ----
    print("\n[3/6] Layer 1: Multiple Statistical Loss Functions...")
    target_oos = sigma2_fullday[is_end:]

    model_names_list = ['GJR', 'HAR', 'PRG_Basic', 'PRG_Extended', 'Separate']
    forecasts_oos = {
        'GJR': gjr_fc[is_end:],
        'HAR': har_fc[is_end:],
        'PRG_Basic': prg_basic_fc[is_end:],
        'PRG_Extended': prg_ext_fc[is_end:],
        'Separate': sep_fc[is_end:],
    }

    layer1 = {}
    for name in model_names_list:
        losses = compute_all_losses(target_oos, forecasts_oos[name])
        layer1[name] = {k: v for k, v in losses.items() if k not in ('qlike_array', 'mse_array')}
        print(f"    {name}: QLIKE={losses['QLIKE']:.4f}, MSE={losses['MSE']:.2e}, "
              f"MAE={losses['MAE']:.4e}, MZ-R²={losses['MZ_R2']:.3f}")

    # Determine best for each metric
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
    print("\n[4/6] Layer 2: Model Confidence Set (QLIKE)...")
    qlike_losses = {}
    for name in model_names_list:
        ql = qlike_loss_array(target_oos, forecasts_oos[name])
        qlike_losses[name] = ql

    surviving, eliminated = model_confidence_set(qlike_losses, alpha=0.10, n_boot=5000)
    print(f"    Surviving models (α=0.10): {surviving}")
    print(f"    Eliminated: {eliminated}")

    layer2 = {
        'surviving': surviving,
        'eliminated': {k: float(v) for k, v in eliminated.items()},
        'alpha': 0.10,
    }

    # ---- Layer 3: Spearman ----
    print("\n  Layer 3: Spearman Rank Correlation...")
    layer3 = {}
    for name in model_names_list:
        sp = spearman_with_bootstrap(target_oos, forecasts_oos[name])
        layer3[name] = sp
        print(f"    {name}: ρ={sp['rho']:.3f} [{sp['ci_lo']:.3f}, {sp['ci_hi']:.3f}]")

    # ---- Layer 4: VaR ----
    print("\n[5/6] Layer 4: VaR Backtesting...")
    layer4 = {}
    for name in model_names_list:
        vr = var_backtest(returns_c2c[is_end:], forecasts_oos[name])
        layer4[name] = vr
        for level in ['VaR_1pct', 'VaR_5pct']:
            v = vr[level]
            kp = 'PASS' if v['kupiec_pass'] else 'FAIL'
            cp = 'PASS' if v['cc_pass'] else 'FAIL'
            print(f"    {name} {level}: VR={v['violation_rate']:.3f} "
                  f"(expect {v['expected_rate']:.2f}), "
                  f"Kupiec {kp} (p={v['kupiec_p']:.3f}), "
                  f"CC {cp}, Basel {v['basel']}")

    # ---- Layer 5: DM Tests ----
    print("\n[6/6] Layer 5: Pairwise DM Tests...")
    dm_results = pairwise_dm_tests(qlike_losses, model_names_list)

    for pair, result in dm_results.items():
        print(f"    {pair}: t={result['t_stat']:.2f}, "
              f"Harvey {'PASS' if result['harvey_pass'] else 'FAIL'}, "
              f"Winner: {result['winner']}")

    # Key comparison: PRG vs Separate (cross-recursion value)
    print("\n  === KEY COMPARISON: PRG vs Separate (cross-recursion value) ===")
    for key in dm_results:
        if 'PRG' in key and 'Separate' in key:
            r = dm_results[key]
            print(f"    {key}: t={r['t_stat']:.2f} → {r['interpretation']}")

    # PRG vs GJR (main comparison)
    print("\n  === MAIN COMPARISON: PRG vs GJR ===")
    for key in dm_results:
        if 'PRG' in key and 'GJR' in key:
            r = dm_results[key]
            print(f"    {key}: t={r['t_stat']:.2f} → {r['interpretation']}")

    # ---- Charts ----
    print("\n  Generating charts...")
    df_oos = df.iloc[is_end:]
    forecasts_full = {
        'GJR': gjr_fc[is_end:],
        'HAR': har_fc[is_end:],
        'PRG_Basic': prg_basic_fc[is_end:],
        'PRG_Extended': prg_ext_fc[is_end:],
        'Separate': sep_fc[is_end:],
    }
    make_charts(df_oos, forecasts_full, target_oos, CHARTS_DIR)

    # ---- Compile results ----
    elapsed = (datetime.now() - t0).total_seconds()
    print(f"\n  Total runtime: {elapsed:.1f}s")

    # Compare with TAIFEX results
    print("\n  === CROSS-MARKET COMPARISON ===")
    print(f"  TAIFEX (K874d): PRG_Ext QLIKE=0.198, DM t=5.10 vs GJR (Harvey PASS)")
    prg_ext_qlike = layer1['PRG_Extended']['QLIKE']
    gjr_qlike = layer1['GJR']['QLIKE']
    print(f"  SPY (K880):     PRG_Ext QLIKE={prg_ext_qlike:.4f}, GJR QLIKE={gjr_qlike:.4f}")

    prg_vs_gjr_key = [k for k in dm_results if 'PRG_Extended' in k and 'GJR' in k]
    if prg_vs_gjr_key:
        t_val = dm_results[prg_vs_gjr_key[0]]['t_stat']
        print(f"  SPY DM t={t_val:.2f} (Harvey {'PASS' if abs(t_val)>3 else 'FAIL'})")

    # Overnight variance share comparison
    ov_share_spy = df['r2_overnight'].mean() / df['sigma2_fullday'].mean() * 100
    print(f"\n  Overnight variance share: SPY={ov_share_spy:.1f}%, TAIFEX≈27-50%")
    print(f"  (Higher overnight share → more cross-session information → bigger PRG advantage)")

    results = {
        'experiment_id': 'K880',
        'title': 'PRG Cross-Market Validation on SPY (Daily Frequency)',
        'type': 'empirical',
        'data_source': 'yfinance (SPY)',
        'period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'is_period': f"{df.index[0].date()} to {IS_END_DATE}",
        'oos_period': f"{df.index[is_end].date()} to {df.index[-1].date()}",
        'n_is': int(is_end),
        'n_oos': int(n_oos),
        'session_decomposition': {
            'overnight_var_share_pct': float(ov_share_spy),
            'intraday_var_share_pct': float(100 - ov_share_spy),
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
        },
        'layer1_loss_functions': layer1,
        'layer2_mcs': layer2,
        'layer3_spearman': layer3,
        'layer4_var': layer4,
        'layer5_dm_tests': dm_results,
        'cross_market_comparison': {
            'taifex_k874d': {
                'PRG_Extended_QLIKE': 0.198,
                'GJR_QLIKE': 0.448,
                'DM_t_PRGExt_vs_GJR': 5.10,
                'overnight_var_share_pct': '27-50% (non-stationary)',
            },
            'spy_k880': {
                'PRG_Extended_QLIKE': float(prg_ext_qlike),
                'GJR_QLIKE': float(gjr_qlike),
                'DM_t_PRGExt_vs_GJR': float(t_val) if prg_vs_gjr_key else None,
                'overnight_var_share_pct': float(ov_share_spy),
            },
        },
        'key_findings': [],
        'runtime_seconds': float(elapsed),
        'refit_freq_gjr_har': REFIT_FREQ,
        'refit_freq_prg': PRG_REFIT_FREQ,
        'references': [
            'Patton (2011): Volatility forecast comparison using imperfect proxies',
            'Hansen, Lunde & Nason (2011): Model Confidence Set',
            'Bollerslev & Ghysels (1996): Periodic GARCH',
            'Corsi (2009): HAR-RV',
            'Lai et al. (2024): PRS concept',
        ],
    }

    # Build key findings
    findings = []

    # 1. Best model
    qlikes = {n: layer1[n]['QLIKE'] for n in model_names_list}
    best_model = min(qlikes, key=qlikes.get)
    findings.append(f"Best QLIKE model: {best_model} ({qlikes[best_model]:.4f})")

    # 2. PRG vs GJR
    if prg_vs_gjr_key:
        r = dm_results[prg_vs_gjr_key[0]]
        findings.append(f"PRG_Extended vs GJR: DM t={r['t_stat']:.2f} ({'Harvey PASS' if r['harvey_pass'] else 'Harvey FAIL (NS)'})")

    # 3. Cross-recursion value
    prg_vs_sep_key = [k for k in dm_results if 'PRG_Extended' in k and 'Separate' in k]
    if prg_vs_sep_key:
        r = dm_results[prg_vs_sep_key[0]]
        findings.append(f"Cross-recursion value (PRG vs Separate): DM t={r['t_stat']:.2f} ({'Harvey PASS' if r['harvey_pass'] else 'NS'})")

    # 4. MCS
    findings.append(f"MCS surviving: {surviving}")

    # 5. Cross-market
    findings.append(f"SPY overnight var share: {ov_share_spy:.1f}% (vs TAIFEX 27-50%)")

    results['key_findings'] = findings

    # Save
    # Convert any remaining numpy types for JSON
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

    results = deep_convert(results)

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n  Results saved to {OUTPUT_FILE}")
    print(f"  Charts saved to {CHARTS_DIR}/")

    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    for f_str in findings:
        print(f"  • {f_str}")
    print("=" * 70)


if __name__ == '__main__':
    main()
