#!/usr/bin/env python3
"""
K880v2: PRG Without Lookahead — Critical Fix of K880
=====================================================

MOTIVATION: Codex found 3 bugs in K880. This experiment re-runs with all fixes.

Bug 1 [CRITICAL — LOOKAHEAD]:
  K880 h_intraday_t used r2_overnight[t] (same-day info). GJR/HAR don't get this.
  FIX: h_intraday_t now uses h_overnight_t (the FORECAST), not r2_overnight[t].
  Full-day forecast at t-1 close:
    h_overnight_t = ω₀ + α₀·r²_intra[t-1] + β₀·h_prev   (yesterday's intraday)
    h_intraday_t  = ω₁ + α₁·h_overnight_t + β₁·h_prev     (FORECAST, not realized)
    h_total_t     = h_overnight_t + h_intraday_t

Bug 2 [HIGH — Cov missing]:
  σ²_c2c = Var(OV) + Var(IN) + 2×Cov(OV,IN). K880 assumed Cov=0.
  FIX: Estimate rolling 252-day Cov(r_ov, r_in) for VaR computation.

Bug 3 [HIGH — MLE no stationarity]:
  h<=0 was clipped to 1e-12 instead of rejected.
  FIX: Return np.inf from LL when h<=0. Add α+β < 0.999 constraint.

Models (same 5, all rerun):
  1. GJR-GARCH(1,1) on c2c returns
  2. HAR-proxy on σ²_fullday
  3. PRG Basic (6 params) — FIXED (no lookahead)
  4. PRG Extended (8 params) — FIXED (no lookahead)
  5. Separate GARCH (no cross-recursion)

Evaluation (common target σ²_fullday):
  Layer 1: QLIKE, MSE, MAE, HMSE, MZ-R²
  Layer 2: MCS (Hansen Lunde Nason 2011)
  Layer 3: Spearman rank correlation + bootstrap CI
  Layer 4: VaR 1%+5% with Cov correction (Kupiec + Christoffersen + Basel)
  Layer 5: DM test pairwise (Harvey |t|>3.0)

Data: yfinance SPY, 2000-01 to 2026-04
IS: 2000-2018, OOS: 2019-2026 (~1750 days)

CRITICAL CHECK: If PRG DM drops below 3.0, K880 result was lookahead artifact.
REPORT HONESTLY EITHER WAY.

Error log rules:
  - DM test: use dm_test from volpred.stats.model_evaluation
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])
  - signal.shift(1) equivalent: ALL forecasts use ONLY info up to t-1 close
  - Sanity check: verify forecasts > 0

References:
  Patton (2011), Hansen Lunde Nason (2011), Bollerslev & Ghysels (1996),
  Corsi (2009), Lai et al. (2024), Kupiec (1995), Christoffersen (1998),
  Diebold & Mariano (1995), Harvey et al. (1997)

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
    """GJR-GARCH negative log-likelihood (numba)."""
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
        if h[t] <= 0:
            return 1e15  # FIX 3: reject h<=0
        ll += -0.5*np.log(2*np.pi) - 0.5*np.log(h[t]) - 0.5*r[t]**2/h[t]
    return -ll


@njit(cache=True)
def _gjr_propagate_numba(omega, alpha, gamma_p, beta, r, h0, start, end):
    """Propagate GJR state from start to end."""
    h = h0
    for t in range(start, end):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        h = omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * indicator + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _garch_negll_numba(omega, alpha, beta, r):
    """GARCH(1,1) negative log-likelihood (numba)."""
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
        if h[t] <= 0:
            return 1e15  # FIX 3: reject h<=0
        ll += -0.5*np.log(2*np.pi) - 0.5*np.log(h[t]) - 0.5*r[t]**2/h[t]
    return -ll


@njit(cache=True)
def _garch_propagate_numba(omega, alpha, beta, r, h0, start, end):
    """Propagate GARCH(1,1) state."""
    h = h0
    for t in range(start, end):
        h = omega + alpha * r[t-1]**2 + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _prg_negll_fixed_numba(params, r_seq, x_seq, s_seq, n_total, extended):
    """
    PRG negative log-likelihood — FIXED (stationarity + h<=0 rejection).

    FIX 3: Return 1e15 when h<=0 (reject, don't clip).
    """
    omega_0, alpha_0, beta_0 = params[0], params[1], params[2]
    omega_1, alpha_1, beta_1 = params[3], params[4], params[5]
    gamma_0 = params[6] if extended else 0.0
    gamma_1 = params[7] if extended else 0.0

    # FIX 3: Stationarity check
    if alpha_0 + beta_0 >= 0.999:
        return 1e15
    if alpha_1 + beta_1 >= 0.999:
        return 1e15

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
        if h[t] <= 0:
            return 1e15  # FIX 3: reject h<=0

    ll = 0.0
    for t in range(1, n_total):
        ll += -0.5 * np.log(2*np.pi) - 0.5*np.log(h[t]) - 0.5*r_seq[t]**2/h[t]
    return -ll


@njit(cache=True)
def _prg_propagate_fixed_numba(omega_0, alpha_0, beta_0, gamma_0,
                                omega_1, alpha_1, beta_1, gamma_1,
                                r_overnight, r_intra, r2_overnight, r2_intra,
                                start_d, end_d, h_init):
    """
    Propagate PRG state through days — FIXED (no lookahead).

    ORIGINAL (K880 BUG):
      Overnight: uses r2_intra[d-1] (OK — yesterday's intraday)
      Intraday:  uses r2_overnight[d] (BUG — today's overnight)

    FIXED (K880v2):
      For IS estimation, we still use interleaved realized values (same as K880)
      because estimation uses realized data from past sessions. The bug was
      specifically in the OOS FORECAST step, not in IS estimation.
      This propagation function is for state tracking, which uses realized data.
    """
    h = h_init
    for d in range(start_d, end_d):
        # Overnight session (s=0) — uses yesterday's intraday
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

        # Intraday session (s=1) — uses today's overnight (for state tracking)
        # NOTE: This function is for IS state tracking only.
        # The OOS forecast function (prg_oos_forecast_fixed) does NOT use this
        # for forecasting — it uses h_overnight_t as input instead.
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
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k880v2_results.json")
CHARTS_DIR = os.path.join(SCRIPT_DIR, "k880v2_charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

IS_END_DATE = "2018-12-31"
REFIT_FREQ = 63       # quarterly refit
PRG_N_STARTS = 5
PRG_REFIT_FREQ = 126  # semi-annual refit for PRG


# ============================================================
# DATA
# ============================================================
def load_spy_data():
    """Load SPY OHLC from yfinance."""
    import yfinance as yf

    print("Downloading SPY data from yfinance...")
    spy = yf.download("SPY", start="2000-01-01", end="2026-04-05", auto_adjust=True)
    print(f"  SPY: {len(spy)} days, {spy.index[0].date()} to {spy.index[-1].date()}")

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    df = pd.DataFrame(index=spy.index)
    df['open'] = spy['Open'].values
    df['high'] = spy['High'].values
    df['low'] = spy['Low'].values
    df['close'] = spy['Close'].values

    df['prev_close'] = df['close'].shift(1)
    df['r_overnight'] = np.log(df['open'] / df['prev_close'])
    df['r_intra'] = np.log(df['close'] / df['open'])
    df['r_c2c'] = np.log(df['close'] / df['prev_close'])

    df['r2_overnight'] = df['r_overnight'] ** 2
    df['r2_intra'] = df['r_intra'] ** 2
    df['sigma2_fullday'] = df['r2_overnight'] + df['r2_intra']
    df['parkinson'] = (np.log(df['high'] / df['low'])) ** 2 / (4 * np.log(2))

    df = df.iloc[1:].dropna(subset=['r_overnight', 'r_intra', 'sigma2_fullday'])

    print(f"  After processing: {len(df)} days")
    print(f"  Mean σ²_fullday: {df['sigma2_fullday'].mean():.6f}")
    print(f"  Overnight share: {df['r2_overnight'].mean()/df['sigma2_fullday'].mean()*100:.1f}%")
    print(f"  Intraday share: {df['r2_intra'].mean()/df['sigma2_fullday'].mean()*100:.1f}%")

    return df


# ============================================================
# MODEL 1: GJR-GARCH
# ============================================================
def gjr_oos_forecast(returns, is_end, refit_freq=63):
    """GJR-GARCH(1,1) OOS with recursive variance propagation."""
    n = len(returns)
    forecasts = np.full(n, np.nan)

    def gjr_negll_wrapper(params, r):
        # FIX 3: stationarity
        if params[1] + params[2] + params[3] >= 0.999:
            return 1e15
        return _gjr_negll_numba(params[0], params[1], params[2], params[3], r)

    eps = 1e-8
    bounds = [(eps, 1e-3), (eps, 0.5), (0.0, 0.5), (eps, 0.999)]
    current_params = None
    h_state = np.var(returns[:min(50, n)])

    for t in range(is_end, n):
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
# MODEL 2: HAR
# ============================================================
def har_oos_forecast(sigma2_series, is_end, refit_freq=63):
    """HAR on log(σ²_fullday). Predict t from t-1 info."""
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
# MODEL 3/4: PRG — FIXED (no lookahead)
# ============================================================
def estimate_prg_fixed(r_overnight, r_intra, r2_overnight, r2_intra,
                       extended=False, n_starts=5):
    """
    Estimate PRG via MLE — FIXED with stationarity constraint (Bug 3).

    Interleaved sequence for estimation only — this uses realized data
    from past sessions which is fine for IS estimation.
    """
    n_days = len(r_overnight)
    n_total = 2 * n_days

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
        # FIX 3: stationarity in wrapper too
        o0, a0, b0 = p[0], p[1], p[2]
        o1, a1, b1 = p[3], p[4], p[5]
        if a0 + b0 >= 0.999 or a1 + b1 >= 0.999:
            return 1e15
        return _prg_negll_fixed_numba(p, r_seq, x_seq, s_seq, n_total, ext_flag)

    eps = 1e-8
    if extended:
        bounds = [
            (eps, 1e-3), (eps, 0.8), (eps, 0.998),
            (eps, 1e-3), (eps, 0.8), (eps, 0.998),
            (0.0, 0.8), (0.0, 0.8),
        ]
    else:
        bounds = [
            (eps, 1e-3), (eps, 0.8), (eps, 0.998),
            (eps, 1e-3), (eps, 0.8), (eps, 0.998),
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
            x0 = [rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.35), rng.uniform(0.50, 0.90),
                   rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.35), rng.uniform(0.50, 0.90)]
            if extended: x0 += [rng.uniform(0.0, 0.15), rng.uniform(0.0, 0.15)]

        try:
            result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                              options={'maxiter': 2000, 'ftol': 1e-10})
            if result.fun < best_nll and result.fun < 1e14:
                best_nll = result.fun
                best_params = result.x
        except Exception:
            continue

    return best_params, -best_nll if best_params is not None else None


def prg_oos_forecast_fixed(r_overnight, r_intra, r2_overnight, r2_intra,
                           is_end, extended=False, refit_freq=126):
    """
    PRG OOS forecast — FIXED (Bug 1: no lookahead).

    *** CRITICAL FIX ***
    At t-1 close, to forecast day t:
      h_overnight_t = ω₀ + α₀·r²_intra[t-1] + [γ₀·lev] + β₀·h_state
        → uses yesterday's intraday (available at t-1 close) ✓

      h_intraday_t  = ω₁ + α₁·h_overnight_t + [γ₁·lev] + β₁·h_overnight_t
        → uses h_overnight_t (FORECAST), NOT r2_overnight[t] (realized)
        → K880 BUG was using r2_overnight[t] here (same-day info!) ✗

      h_total_t = h_overnight_t + h_intraday_t

    For leverage in intraday forecast: we DON'T have r_overnight[t] yet,
    so we use the SIGN of the overnight forecast residual from yesterday
    or simply omit leverage for the second-stage forecast.
    Conservative choice: use sign of r_intra[t-1] (last known return).

    State update (after day t is observed):
      h_state is updated using REALIZED data for next forecast.
    """
    n_days = len(r_overnight)
    forecasts = np.full(n_days, np.nan)
    h_ov_forecasts = np.full(n_days, np.nan)
    h_in_forecasts = np.full(n_days, np.nan)

    current_params = None
    h_state = None

    def _parse(params):
        o0, a0, b0 = params[0], params[1], params[2]
        o1, a1, b1 = params[3], params[4], params[5]
        g0 = params[6] if extended and len(params) > 6 else 0.0
        g1 = params[7] if extended and len(params) > 7 else 0.0
        return o0, a0, b0, g0, o1, a1, b1, g1

    for t in range(is_end, n_days):
        # Refit periodically
        if (t - is_end) % refit_freq == 0 or t == is_end:
            params, ll = estimate_prg_fixed(
                r_overnight[:t], r_intra[:t],
                r2_overnight[:t], r2_intra[:t],
                extended=extended, n_starts=PRG_N_STARTS
            )
            if params is not None:
                current_params = params
                o0, a0, b0, g0, o1, a1, b1, g1 = _parse(current_params)

                # Rebuild state from scratch using realized data
                h_init = np.mean(r2_overnight[:min(50, t)] + r2_intra[:min(50, t)]) / 2
                if h_init < 1e-12: h_init = 1e-8
                h_state = _prg_propagate_fixed_numba(
                    o0, a0, b0, g0, o1, a1, b1, g1,
                    r_overnight, r_intra, r2_overnight, r2_intra,
                    0, t, h_init
                )

        if current_params is None or h_state is None:
            continue

        o0, a0, b0, g0, o1, a1, b1, g1 = _parse(current_params)

        # =============================================
        # FIX 1: NO LOOKAHEAD FORECAST
        # =============================================
        # At t-1 close, h_state holds the state after intraday of t-1.
        # Forecast overnight of day t:
        x_prev = r2_intra[t-1]   # yesterday's intraday — AVAILABLE at t-1 close ✓
        r_prev = r_intra[t-1]
        lev_ov = g0 * x_prev * (1.0 if r_prev < 0 else 0.0)
        h_ov_t = o0 + a0 * x_prev + lev_ov + b0 * h_state
        if h_ov_t < 1e-12: h_ov_t = 1e-12

        # Forecast intraday of day t:
        # *** FIX: use h_overnight_t (FORECAST), NOT r2_overnight[t] (realized) ***
        # For leverage: we don't know r_overnight[t] yet.
        # Use sign of the last known return (r_intra[t-1]) as proxy.
        # This is conservative — in K880 the leverage used realized r_overnight[t].
        lev_in = g1 * h_ov_t * (1.0 if r_prev < 0 else 0.0)
        h_in_t = o1 + a1 * h_ov_t + lev_in + b1 * h_ov_t
        if h_in_t < 1e-12: h_in_t = 1e-12

        forecasts[t] = h_ov_t + h_in_t
        h_ov_forecasts[t] = h_ov_t
        h_in_forecasts[t] = h_in_t

        # State update: propagate through day t using REALIZED data
        # (this is for the NEXT forecast, not the current one)
        h_state = _prg_propagate_fixed_numba(
            o0, a0, b0, g0, o1, a1, b1, g1,
            r_overnight, r_intra, r2_overnight, r2_intra,
            t, t+1, h_state
        )

    return forecasts, h_ov_forecasts, h_in_forecasts


# ============================================================
# MODEL 5: Separate GARCH
# ============================================================
def separate_garch_oos(r_overnight, r_intra, r2_overnight, r2_intra,
                       is_end, refit_freq=63):
    """Two independent GARCH(1,1) — no cross-session h propagation."""
    n_days = len(r_overnight)
    forecasts = np.full(n_days, np.nan)

    def garch_negll_wrapper(params, r):
        if params[1] + params[2] >= 0.999:  # FIX 3
            return 1e15
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
                    if result.fun < best_nll and result.fun < 1e14:
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
                    if result.fun < best_nll and result.fun < 1e14:
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
# MCS
# ============================================================
def model_confidence_set(loss_dict, alpha=0.10, n_boot=5000):
    model_names = list(loss_dict.keys())
    n_obs = min(len(v) for v in loss_dict.values())
    losses = {}
    for name in model_names:
        losses[name] = loss_dict[name][:n_obs]

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
# Spearman
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

    return {
        'rho': float(rho), 'p': float(p),
        'ci_lo': float(np.percentile(boot_rhos, 2.5)),
        'ci_hi': float(np.percentile(boot_rhos, 97.5)),
        'n': n
    }


# ============================================================
# VaR with Cov correction (FIX 2)
# ============================================================
def var_backtest_with_cov(returns_c2c, r_overnight, r_intra,
                          sigma2_forecasts, h_ov_fc, h_in_fc,
                          alpha_levels=[0.01, 0.05], cov_window=252):
    """
    VaR backtesting with Cov correction (FIX 2).

    σ²_c2c = h_ov + h_in + 2×Cov(r_ov, r_in)
    If h_ov/h_in unavailable (non-PRG models), use sigma2_forecasts directly.
    """
    n = len(returns_c2c)
    valid = (np.isfinite(returns_c2c) & np.isfinite(sigma2_forecasts) &
             (sigma2_forecasts > 0))

    # Compute rolling covariance for PRG models
    has_components = (h_ov_fc is not None and h_in_fc is not None and
                      not np.all(np.isnan(h_ov_fc)))

    if has_components:
        # Rolling Cov(r_ov, r_in) from PAST data only
        cov_series = np.full(n, 0.0)
        for t in range(cov_window, n):
            ov_window = r_overnight[t-cov_window:t]
            in_window = r_intra[t-cov_window:t]
            if len(ov_window) > 0:
                cov_series[t] = np.cov(ov_window, in_window)[0, 1]

        # Corrected variance: h_ov + h_in + 2*Cov
        sigma2_corrected = np.where(
            np.isfinite(h_ov_fc) & np.isfinite(h_in_fc),
            h_ov_fc + h_in_fc + 2 * cov_series,
            sigma2_forecasts
        )
        # Ensure positive
        sigma2_corrected = np.maximum(sigma2_corrected, 1e-12)
    else:
        sigma2_corrected = sigma2_forecasts

    r = returns_c2c
    s2 = sigma2_corrected
    results = {}

    for alpha in alpha_levels:
        z = sp_stats.norm.ppf(alpha)
        var_level = z * np.sqrt(s2)

        mask = valid & np.isfinite(s2) & (s2 > 0)
        r_m = r[mask]
        var_m = var_level[mask]
        n_m = len(r_m)

        violations = r_m < var_m
        n_violations = int(np.sum(violations))
        vr = n_violations / n_m if n_m > 0 else np.nan

        # Kupiec
        if n_violations > 0 and n_violations < n_m:
            lr_uc = -2 * (n_violations * np.log(alpha) + (n_m - n_violations) * np.log(1 - alpha)
                         - n_violations * np.log(vr) - (n_m - n_violations) * np.log(1 - vr))
            p_kupiec = 1 - sp_stats.chi2.cdf(lr_uc, 1)
        else:
            lr_uc = np.nan
            p_kupiec = np.nan

        # Christoffersen
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

        # Basel
        if n_m >= 250:
            recent_v = int(np.sum(violations[-250:]))
            if recent_v < 5: basel = "Green"
            elif recent_v < 10: basel = "Yellow"
            else: basel = "Red"
        else:
            recent_v = n_violations
            basel = "N/A"

        results[f"VaR_{int(alpha*100)}pct"] = {
            'n': n_m,
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
            'basel_violations_250d': recent_v,
            'cov_corrected': bool(has_components),
        }

    if has_components:
        valid_cov = cov_series[np.isfinite(h_ov_fc)]
        results['cov_stats'] = {
            'mean_cov': float(np.mean(valid_cov)) if len(valid_cov) > 0 else 0,
            'cov_as_pct_of_total': float(
                2 * np.mean(valid_cov) /
                np.mean(sigma2_corrected[np.isfinite(h_ov_fc)]) * 100
            ) if len(valid_cov) > 0 else 0,
        }

    return results


# ============================================================
# ES Backtesting (Acerbi-Szekely)
# ============================================================
def es_backtest(returns_c2c, sigma2_forecasts, alpha=0.025):
    """Expected Shortfall backtest via Acerbi-Szekely (2014) Z2 test."""
    valid = np.isfinite(returns_c2c) & np.isfinite(sigma2_forecasts) & (sigma2_forecasts > 0)
    r = returns_c2c[valid]
    s2 = sigma2_forecasts[valid]
    n = len(r)

    sigma = np.sqrt(s2)
    z_alpha = sp_stats.norm.ppf(alpha)
    var_level = z_alpha * sigma
    es_level = -sigma * sp_stats.norm.pdf(z_alpha) / alpha

    violations = r < var_level
    n_viol = int(np.sum(violations))

    if n_viol < 2:
        return {'z2_stat': np.nan, 'p_value': np.nan, 'n_violations': n_viol,
                'n': n, 'alpha': float(alpha)}

    # Acerbi-Szekely Z2
    z2 = np.sum(r[violations] / es_level[violations]) / (n * alpha) + 1
    # Under null, z2 ~ N(0, 1/n * something). Use bootstrap.
    rng = np.random.RandomState(42)
    boot_z2 = []
    for _ in range(5000):
        idx = rng.randint(0, n, n)
        r_b = r[idx]
        es_b = es_level[idx]
        var_b = var_level[idx]
        viol_b = r_b < var_b
        if np.sum(viol_b) > 0:
            z2_b = np.sum(r_b[viol_b] / es_b[viol_b]) / (n * alpha) + 1
            boot_z2.append(z2_b)
    if len(boot_z2) > 100:
        p_val = np.mean(np.array(boot_z2) <= z2)
    else:
        p_val = np.nan

    return {
        'z2_stat': float(z2),
        'p_value': float(p_val),
        'n_violations': n_viol,
        'n': n,
        'alpha': float(alpha),
        'reject_at_5pct': bool(p_val < 0.05) if np.isfinite(p_val) else None,
    }


# ============================================================
# DM Tests
# ============================================================
def pairwise_dm_tests(model_losses, model_names):
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
                d = li - lj
                d_mean = np.mean(d)
                n_d = len(d)
                max_lag = int(np.floor(n_d ** (1/3)))
                d_centered = d - d_mean
                gamma = np.zeros(max_lag + 1)
                for k in range(max_lag + 1):
                    gamma[k] = np.mean(d_centered[k:] * d_centered[:n_d-k])
                hac_var = gamma[0] + 2 * sum((1 - k/(max_lag+1)) * gamma[k] for k in range(1, max_lag+1))
                t_stat = d_mean / np.sqrt(hac_var / n_d) if hac_var > 0 else 0
                p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), n_d-1))

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
def make_charts(df_oos, forecasts_dict, target_oos, charts_dir, k880_comparison=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Chart 1: QLIKE comparison (K880v2 vs K880)
    fig, ax = plt.subplots(figsize=(12, 7))
    names = list(forecasts_dict.keys())
    qlikes_v2 = []
    for name in names:
        ql = qlike_loss_array(target_oos, forecasts_dict[name])
        valid = ql[np.isfinite(ql)]
        qlikes_v2.append(np.mean(valid) if len(valid) > 0 else np.nan)

    x = np.arange(len(names))
    width = 0.35

    if k880_comparison:
        qlikes_v1 = [k880_comparison.get(n, np.nan) for n in names]
        bars1 = ax.bar(x - width/2, qlikes_v1, width, label='K880 (with lookahead bug)',
                       color='#e74c3c', alpha=0.7, edgecolor='black', linewidth=0.5)
        bars2 = ax.bar(x + width/2, qlikes_v2, width, label='K880v2 (FIXED)',
                       color='#2ecc71', edgecolor='black', linewidth=0.5)
        for bar, q in zip(bars1, qlikes_v1):
            if np.isfinite(q):
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                        f'{q:.3f}', ha='center', va='bottom', fontsize=9, color='#e74c3c')
        for bar, q in zip(bars2, qlikes_v2):
            if np.isfinite(q):
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                        f'{q:.3f}', ha='center', va='bottom', fontsize=9, color='#27ae60')
        ax.legend(fontsize=11)
    else:
        colors = ['#e74c3c' if q == min(qlikes_v2) else '#3498db' for q in qlikes_v2]
        bars = ax.bar(names, qlikes_v2, color=colors, edgecolor='black', linewidth=0.5)
        for bar, q in zip(bars, qlikes_v2):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                    f'{q:.3f}', ha='center', va='bottom', fontsize=10)

    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=15, ha='right')
    ax.set_ylabel('QLIKE (lower = better)', fontsize=12)
    ax.set_title('K880v2: QLIKE — PRG Fixed (No Lookahead) vs K880\nSPY OOS 2019-2026', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'qlike_comparison_v1_vs_v2.png'), dpi=150)
    plt.close()

    # Chart 2: Rolling QLIKE ratio
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
        ax.set_title('K880v2: Rolling QLIKE Ratio — Fixed PRG Extended vs GJR (SPY OOS)', fontsize=13)
        ax.set_ylabel('QLIKE Ratio (< 1 = PRG better)')
        ax.legend(loc='upper left', fontsize=9)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'rolling_qlike_ratio.png'), dpi=150)
        plt.close()

    # Chart 3: DM t-stat comparison K880 vs K880v2
    fig, ax = plt.subplots(figsize=(8, 6))
    prg_pairs = ['GJR_vs_PRG_Extended', 'HAR_vs_PRG_Extended',
                 'PRG_Extended_vs_Separate']
    k880_dm_t = {
        'GJR_vs_PRG_Extended': 6.00,
        'HAR_vs_PRG_Extended': 7.31,
        'PRG_Extended_vs_Separate': -6.69,
    }
    ax.set_title('K880v2: Was PRG DM advantage a lookahead artifact?', fontsize=13)
    ax.set_ylabel('DM t-statistic (|t| > 3 = Harvey PASS)')
    ax.axhline(3.0, color='green', linestyle='--', alpha=0.5, label='Harvey +3.0')
    ax.axhline(-3.0, color='green', linestyle='--', alpha=0.5, label='Harvey -3.0')
    ax.axhline(0, color='black', linestyle='-', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'dm_comparison_placeholder.png'), dpi=150)
    plt.close()

    print(f"  Charts saved to {charts_dir}")


# ============================================================
# MAIN
# ============================================================
def main():
    import builtins
    _original_print = builtins.print
    def print(*args, **kwargs):
        kwargs.setdefault('flush', True)
        _original_print(*args, **kwargs)

    print("=" * 70)
    print("K880v2: PRG Without Lookahead — Critical Fix of K880")
    print("  Fix 1: h_intraday uses forecast h_overnight, not realized r2_overnight")
    print("  Fix 2: VaR includes Cov(overnight, intraday) term")
    print("  Fix 3: MLE rejects h<=0, enforces stationarity")
    print("=" * 70)

    # Warm up numba
    print("\n  Warming up numba JIT...")
    _d = np.array([0.01, -0.02, 0.015, -0.005, 0.01], dtype=np.float64)
    _gjr_negll_numba(1e-5, 0.1, 0.05, 0.85, _d)
    _garch_negll_numba(1e-5, 0.1, 0.85, _d)
    _prg_negll_fixed_numba(np.zeros(8), _d, np.abs(_d),
                            np.array([0,1,0,1,0], dtype=np.int64), 5, False)
    _prg_propagate_fixed_numba(1e-5, 0.1, 0.85, 0.0, 1e-5, 0.1, 0.85, 0.0,
                                _d, _d, _d**2, _d**2, 0, 2, 1e-5)
    _gjr_propagate_numba(1e-5, 0.1, 0.05, 0.85, _d, 1e-5, 1, 4)
    _garch_propagate_numba(1e-5, 0.1, 0.85, _d, 1e-5, 1, 4)
    print("  JIT done.")

    t0 = datetime.now()

    # ---- Data ----
    print("\n[1/7] Loading SPY data...")
    df = load_spy_data()

    print(f"\n  Descriptive statistics:")
    print(f"    Total days: {len(df)}")
    print(f"    Date range: {df.index[0].date()} to {df.index[-1].date()}")
    print(f"    c2c: mean={df['r_c2c'].mean():.6f}, std={df['r_c2c'].std():.4f}")
    print(f"    Overnight: mean={df['r_overnight'].mean():.6f}, std={df['r_overnight'].std():.4f}")
    print(f"    Intraday: mean={df['r_intra'].mean():.6f}, std={df['r_intra'].std():.4f}")
    ov_share = df['r2_overnight'].mean() / df['sigma2_fullday'].mean() * 100
    print(f"    Overnight var share: {ov_share:.1f}%")

    # IS/OOS
    is_mask = df.index <= IS_END_DATE
    is_end = int(np.sum(is_mask))
    n_oos = len(df) - is_end
    print(f"\n  IS: {is_end} days, OOS: {n_oos} days")
    print(f"  IS: {df.index[0].date()} to {IS_END_DATE}")
    print(f"  OOS: {df.index[is_end].date()} to {df.index[-1].date()}")

    returns_c2c = df['r_c2c'].values
    r_overnight = df['r_overnight'].values
    r_intra = df['r_intra'].values
    r2_overnight = df['r2_overnight'].values
    r2_intra = df['r2_intra'].values
    sigma2_fullday = df['sigma2_fullday'].values

    # ---- Model forecasts ----
    print("\n[2/7] Running OOS forecasts (all 5 models)...")

    print("  GJR-GARCH...")
    gjr_fc = gjr_oos_forecast(returns_c2c, is_end, refit_freq=REFIT_FREQ)
    print(f"    {np.sum(np.isfinite(gjr_fc[is_end:]))} valid forecasts")

    print("  HAR...")
    har_fc = har_oos_forecast(sigma2_fullday, is_end, refit_freq=REFIT_FREQ)
    print(f"    {np.sum(np.isfinite(har_fc[is_end:]))} valid forecasts")

    print("  PRG Basic (6 params, FIXED)...")
    prg_basic_fc, prg_b_ov, prg_b_in = prg_oos_forecast_fixed(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end, extended=False, refit_freq=PRG_REFIT_FREQ
    )
    print(f"    {np.sum(np.isfinite(prg_basic_fc[is_end:]))} valid forecasts")

    print("  PRG Extended (8 params, FIXED)...")
    prg_ext_fc, prg_e_ov, prg_e_in = prg_oos_forecast_fixed(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end, extended=True, refit_freq=PRG_REFIT_FREQ
    )
    print(f"    {np.sum(np.isfinite(prg_ext_fc[is_end:]))} valid forecasts")

    print("  Separate GARCH...")
    sep_fc = separate_garch_oos(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end, refit_freq=REFIT_FREQ
    )
    print(f"    {np.sum(np.isfinite(sep_fc[is_end:]))} valid forecasts")

    # Sanity
    print("\n  Sanity check (forecast range):")
    for name, fc in [('GJR', gjr_fc), ('HAR', har_fc), ('PRG_Basic', prg_basic_fc),
                      ('PRG_Extended', prg_ext_fc), ('Separate', sep_fc)]:
        valid_fc = fc[is_end:][np.isfinite(fc[is_end:])]
        if len(valid_fc) > 0:
            print(f"    {name}: min={valid_fc.min():.2e}, mean={valid_fc.mean():.2e}, max={valid_fc.max():.2e}")
            if valid_fc.min() <= 0:
                print(f"    *** WARNING: {name} has non-positive forecasts! ***")

    # ---- Layer 1: Loss Functions ----
    print("\n[3/7] Layer 1: Loss Functions...")
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
              f"MAE={losses['MAE']:.4e}, MZ-R2={losses['MZ_R2']:.3f}")

    for metric in ['QLIKE', 'MSE', 'MAE', 'HMSE']:
        vals = {n: layer1[n][metric] for n in model_names_list if np.isfinite(layer1[n][metric])}
        if vals:
            best = min(vals, key=vals.get)
            print(f"    Best {metric}: {best} ({vals[best]:.4f})")

    # ---- Layer 2: MCS ----
    print("\n[4/7] Layer 2: Model Confidence Set...")
    qlike_losses = {}
    for name in model_names_list:
        qlike_losses[name] = qlike_loss_array(target_oos, forecasts_oos[name])

    surviving, eliminated = model_confidence_set(qlike_losses, alpha=0.10, n_boot=5000)
    print(f"    Surviving (alpha=0.10): {surviving}")
    print(f"    Eliminated: {eliminated}")
    layer2 = {'surviving': surviving, 'eliminated': {k: float(v) for k, v in eliminated.items()}, 'alpha': 0.10}

    # ---- Layer 3: Spearman ----
    print("\n  Layer 3: Spearman Rank Correlation...")
    layer3 = {}
    for name in model_names_list:
        sp = spearman_with_bootstrap(target_oos, forecasts_oos[name])
        layer3[name] = sp
        print(f"    {name}: rho={sp['rho']:.3f} [{sp['ci_lo']:.3f}, {sp['ci_hi']:.3f}]")

    # ---- Layer 4: VaR with Cov ----
    print("\n[5/7] Layer 4: VaR Backtesting (with Cov correction)...")
    layer4 = {}
    r_c2c_oos = returns_c2c[is_end:]
    r_ov_oos = r_overnight[is_end:]
    r_in_oos = r_intra[is_end:]

    # For non-PRG models, no component forecasts
    for name in ['GJR', 'HAR', 'Separate']:
        vr = var_backtest_with_cov(r_c2c_oos, r_ov_oos, r_in_oos,
                                    forecasts_oos[name], None, None)
        layer4[name] = vr
        for level in ['VaR_1pct', 'VaR_5pct']:
            v = vr[level]
            kp = 'PASS' if v.get('kupiec_pass') else 'FAIL'
            cp = 'PASS' if v.get('cc_pass') else 'FAIL'
            print(f"    {name} {level}: VR={v['violation_rate']:.3f}, "
                  f"Kupiec {kp} (p={v.get('kupiec_p', 0):.3f}), CC {cp}, Basel {v['basel']}")

    # For PRG models, use component forecasts + Cov
    for name, ov_fc, in_fc in [('PRG_Basic', prg_b_ov[is_end:], prg_b_in[is_end:]),
                                ('PRG_Extended', prg_e_ov[is_end:], prg_e_in[is_end:])]:
        vr = var_backtest_with_cov(r_c2c_oos, r_ov_oos, r_in_oos,
                                    forecasts_oos[name], ov_fc, in_fc)
        layer4[name] = vr
        for level in ['VaR_1pct', 'VaR_5pct']:
            v = vr[level]
            kp = 'PASS' if v.get('kupiec_pass') else 'FAIL'
            cp = 'PASS' if v.get('cc_pass') else 'FAIL'
            print(f"    {name} {level}: VR={v['violation_rate']:.3f}, "
                  f"Kupiec {kp} (p={v.get('kupiec_p', 0):.3f}), CC {cp}, Basel {v['basel']}")
        if 'cov_stats' in vr:
            cs = vr['cov_stats']
            print(f"    {name} Cov stats: mean={cs['mean_cov']:.2e}, as % of total={cs['cov_as_pct_of_total']:.1f}%")

    # ---- Layer 4b: ES ----
    print("\n  Layer 4b: ES Backtesting (Acerbi-Szekely, alpha=2.5%)...")
    layer4b = {}
    for name in model_names_list:
        es_r = es_backtest(r_c2c_oos, forecasts_oos[name], alpha=0.025)
        layer4b[name] = es_r
        rej = 'REJECT' if es_r.get('reject_at_5pct') else 'PASS'
        print(f"    {name}: Z2={es_r['z2_stat']:.3f}, p={es_r['p_value']:.3f}, {rej}")

    # ---- Layer 5: DM Tests ----
    print("\n[6/7] Layer 5: Pairwise DM Tests...")
    dm_results = pairwise_dm_tests(qlike_losses, model_names_list)

    for pair, result in dm_results.items():
        print(f"    {pair}: t={result['t_stat']:.2f}, "
              f"Harvey {'PASS' if result['harvey_pass'] else 'FAIL'}, "
              f"Winner: {result['winner']}")

    # =========================================================
    # CRITICAL COMPARISON: K880 vs K880v2
    # =========================================================
    print("\n" + "=" * 70)
    print("CRITICAL COMPARISON: K880 (buggy) vs K880v2 (fixed)")
    print("=" * 70)

    k880_results = {
        'GJR': {'QLIKE': 0.854, 'DM_vs_PRGExt': 6.00},
        'HAR': {'QLIKE': 1.464, 'DM_vs_PRGExt': 7.31},
        'PRG_Basic': {'QLIKE': 0.758},
        'PRG_Extended': {'QLIKE': 0.748},
        'Separate': {'QLIKE': 0.867, 'DM_vs_PRGExt': -6.69},
    }

    print("\n  QLIKE comparison:")
    print(f"    {'Model':<15} {'K880 (bug)':>12} {'K880v2 (fix)':>12} {'Change':>10}")
    print(f"    {'-'*49}")
    for name in model_names_list:
        v1 = k880_results[name]['QLIKE']
        v2 = layer1[name]['QLIKE']
        pct = (v2 - v1) / v1 * 100
        arrow = "^" if v2 > v1 else "v" if v2 < v1 else "="
        print(f"    {name:<15} {v1:>12.4f} {v2:>12.4f} {pct:>+8.1f}% {arrow}")

    # DM comparison
    print("\n  DM t-stat comparison (PRG_Extended vs others):")
    print(f"    {'Pair':<30} {'K880 t':>8} {'K880v2 t':>8} {'K880v2 Harvey':>14}")
    print(f"    {'-'*60}")

    key_pairs = {
        'GJR_vs_PRG_Extended': ('GJR', 6.00),
        'HAR_vs_PRG_Extended': ('HAR', 7.31),
        'PRG_Extended_vs_Separate': ('Separate', -6.69),
    }
    for pair_key, (_, k880_t) in key_pairs.items():
        if pair_key in dm_results:
            v2_t = dm_results[pair_key]['t_stat']
            harvey = 'PASS' if dm_results[pair_key]['harvey_pass'] else 'FAIL'
            print(f"    {pair_key:<30} {k880_t:>8.2f} {v2_t:>8.2f} {harvey:>14}")

    # The critical verdict
    prg_vs_gjr_key = [k for k in dm_results if 'PRG_Extended' in k and 'GJR' in k]
    if prg_vs_gjr_key:
        key = prg_vs_gjr_key[0]
        t_v2 = dm_results[key]['t_stat']
        harvey = dm_results[key]['harvey_pass']

        print(f"\n  *** CRITICAL VERDICT ***")
        print(f"  K880 (buggy) PRG_Ext vs GJR: DM t = 6.00 (Harvey PASS)")
        print(f"  K880v2 (fixed) PRG_Ext vs GJR: DM t = {t_v2:.2f} (Harvey {'PASS' if harvey else 'FAIL'})")

        if harvey:
            print(f"  ==> PRG advantage SURVIVES after fixing lookahead! DM t={t_v2:.2f} > 3.0")
            print(f"  ==> The K880 result was NOT primarily a lookahead artifact.")
            print(f"  ==> Cross-recursion provides genuine forecasting value on SPY.")
            verdict = "SURVIVES"
        elif abs(t_v2) > 1.96:
            print(f"  ==> PRG advantage WEAKENED but still significant (t={t_v2:.2f})")
            print(f"  ==> Part of K880 DM was lookahead artifact, but PRG still better at 5% level")
            verdict = "WEAKENED_BUT_SIGNIFICANT"
        else:
            print(f"  ==> PRG advantage COLLAPSED after fixing lookahead! t={t_v2:.2f}")
            print(f"  ==> K880 DM t=6.00 was INDEED a lookahead artifact!")
            verdict = "COLLAPSED_ARTIFACT"
    else:
        verdict = "UNKNOWN"
        t_v2 = np.nan

    # Cross-recursion test
    prg_vs_sep_key = [k for k in dm_results if 'PRG_Extended' in k and 'Separate' in k]
    if prg_vs_sep_key:
        key = prg_vs_sep_key[0]
        t_xr = dm_results[key]['t_stat']
        print(f"\n  Cross-recursion value (PRG vs Separate): DM t = {t_xr:.2f} "
              f"(K880: -6.69, Harvey {'PASS' if dm_results[key]['harvey_pass'] else 'FAIL'})")

    # ---- Charts ----
    print("\n[7/7] Generating charts...")
    df_oos = df.iloc[is_end:]
    k880_qlikes = {n: k880_results[n]['QLIKE'] for n in model_names_list}
    make_charts(df_oos, forecasts_oos, target_oos, CHARTS_DIR, k880_comparison=k880_qlikes)

    # ---- Compile results ----
    elapsed = (datetime.now() - t0).total_seconds()
    print(f"\n  Total runtime: {elapsed:.1f}s")

    # Key findings
    findings = []

    qlikes_v2 = {n: layer1[n]['QLIKE'] for n in model_names_list}
    best_model = min(qlikes_v2, key=qlikes_v2.get)
    findings.append(f"Best QLIKE: {best_model} ({qlikes_v2[best_model]:.4f})")

    if prg_vs_gjr_key:
        findings.append(f"PRG_Ext vs GJR: DM t={t_v2:.2f} (K880 had 6.00). Verdict: {verdict}")

    if prg_vs_sep_key:
        findings.append(f"Cross-recursion (PRG vs Sep): DM t={dm_results[prg_vs_sep_key[0]]['t_stat']:.2f}")

    findings.append(f"MCS surviving: {surviving}")
    findings.append(f"Verdict: {verdict}")

    # QLIKE changes
    for name in ['PRG_Basic', 'PRG_Extended']:
        v1 = k880_results[name]['QLIKE']
        v2 = layer1[name]['QLIKE']
        pct = (v2 - v1) / v1 * 100
        findings.append(f"{name} QLIKE: {v1:.4f} -> {v2:.4f} ({pct:+.1f}%)")

    results = {
        'experiment_id': 'K880v2',
        'title': 'PRG Without Lookahead — Critical Fix of K880',
        'type': 'empirical',
        'data_source': 'yfinance (SPY)',
        'period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'is_period': f"{df.index[0].date()} to {IS_END_DATE}",
        'oos_period': f"{df.index[is_end].date()} to {df.index[-1].date()}",
        'n_is': int(is_end),
        'n_oos': int(n_oos),
        'bugs_fixed': {
            'bug1_lookahead': 'h_intraday now uses h_overnight FORECAST instead of realized r2_overnight[t]',
            'bug2_cov': 'VaR now includes 2*Cov(overnight, intraday) in sigma2_c2c',
            'bug3_stationarity': 'MLE rejects h<=0 with np.inf, enforces alpha+beta<0.999',
        },
        'session_decomposition': {
            'overnight_var_share_pct': float(ov_share),
            'intraday_var_share_pct': float(100 - ov_share),
        },
        'layer1_loss_functions': layer1,
        'layer2_mcs': layer2,
        'layer3_spearman': layer3,
        'layer4_var': layer4,
        'layer4b_es': layer4b,
        'layer5_dm_tests': dm_results,
        'k880_vs_k880v2': {
            'k880_prg_ext_qlike': 0.748,
            'k880v2_prg_ext_qlike': float(layer1['PRG_Extended']['QLIKE']),
            'k880_dm_prg_vs_gjr': 6.00,
            'k880v2_dm_prg_vs_gjr': float(t_v2) if np.isfinite(t_v2) else None,
            'verdict': verdict,
        },
        'key_findings': findings,
        'runtime_seconds': float(elapsed),
        'refit_freq_gjr_har': REFIT_FREQ,
        'refit_freq_prg': PRG_REFIT_FREQ,
        'references': [
            'Patton (2011): Volatility forecast comparison using imperfect proxies',
            'Hansen, Lunde & Nason (2011): Model Confidence Set',
            'Bollerslev & Ghysels (1996): Periodic GARCH',
            'Corsi (2009): HAR-RV',
            'Lai et al. (2024): PRS concept',
            'Kupiec (1995): VaR test',
            'Christoffersen (1998): Conditional coverage',
            'Acerbi & Szekely (2014): ES backtest',
        ],
    }

    # JSON serialize
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
    print(f"  Charts in {CHARTS_DIR}/")

    print("\n" + "=" * 70)
    print("K880v2 KEY FINDINGS:")
    for f_str in findings:
        print(f"  * {f_str}")
    print("=" * 70)


if __name__ == '__main__':
    main()
