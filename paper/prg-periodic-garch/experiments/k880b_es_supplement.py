#!/usr/bin/env python3
"""
K880b: ES (Expected Shortfall) Supplement for K880 SPY PRG Validation
======================================================================

Research Question (EMPIRICAL):
  K880 validated PRG on SPY but only performed VaR backtesting.
  This supplement adds ES evaluation — mandatory under Basel III.

Models (same as K880):
  1. GJR-GARCH(1,1) on close-to-close returns
  2. HAR-proxy on σ²_fullday (log-space)
  3. PRG Basic (6 params): periodic GARCH alternating overnight/intraday
  4. PRG Extended (8 params): + leverage for negative returns
  5. Separate GARCH: independent GARCH for each session (no cross-recursion)

ES Methods:
  A. Parametric Normal ES: ES_t = σ_t × φ(z_α) / Φ(z_α)
  B. Standardized residual Historical Simulation ES:
     z_t = r_t / σ_t, then ES from empirical tail of z

ES Backtests:
  1. Acerbi & Szekely (2014):
     Z_2 = (1/T) × Σ_t (r_t / ES_t) × I(r_t < VaR_t) / α + 1
     Under H0: E[Z_2] = 0. Bootstrap for p-value.
  2. Fissler & Ziegel (2016) joint VaR-ES scoring:
     S(VaR, ES, r) = (1/ES)×(VaR - r)×I(r < VaR) - VaR/ES + log(-ES) - 1
     Lower = better.

Levels: 1% and 5%

Data: yfinance SPY OHLC (2000-2026), OOS: 2019-2026
Reuses K880's model architecture (code recomputed, not loaded).

Error log rules applied:
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])
  - Sanity check: verify forecasts > 0
  - shift(1) equivalent: predict from t-1 info

References:
  - Acerbi & Szekely (2014): Backtesting Expected Shortfall. Risk.
  - Fissler & Ziegel (2016): Higher order elicitability and Osband's principle. Ann. Stat.
  - McNeil & Frey (2000): Estimation of tail-related risk measures. J. Empirical Finance.
  - Basel Committee (2019): MAR 99. Minimum capital requirements for market risk.
  - Patton, Ziegel & Chen (2019): Dynamic semiparametric models for ES. J. Econometrics.
  - K880: PRG Cross-Market Validation on SPY

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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k880b_results.json")

# OOS split
IS_END_DATE = "2018-12-31"
REFIT_FREQ = 63         # quarterly refit for GJR/HAR/Separate
PRG_N_STARTS = 5
PRG_REFIT_FREQ = 126    # semi-annual refit for PRG

# ============================================================
# Numba-accelerated inner loops (reused from K880)
# ============================================================
@njit(cache=True)
def _gjr_negll_numba(omega, alpha, gamma_p, beta, r):
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
    h = h0
    for t in range(start, end):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        h = omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * indicator + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _garch_negll_numba(omega, alpha, beta, r):
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
    h = h0
    for t in range(start, end):
        h = omega + alpha * r[t-1]**2 + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _prg_negll_numba(params, r_seq, x_seq, s_seq, n_total, extended):
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
    h = h_init
    for d in range(start_d, end_d):
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
        x_prev_in = r2_overnight[d]
        r_prev_in = r_overnight[d]
        lev = gamma_1 * x_prev_in * (1.0 if r_prev_in < 0 else 0.0)
        h = omega_1 + alpha_1 * x_prev_in + lev + beta_1 * h
        if h < 1e-12:
            h = 1e-12
    return h


# ============================================================
# DATA LOADING
# ============================================================
def load_spy_data():
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

    df = df.iloc[1:].dropna(subset=['r_overnight', 'r_intra', 'sigma2_fullday'])
    print(f"  After processing: {len(df)} days")
    return df


# ============================================================
# MODEL FORECASTING FUNCTIONS (same as K880)
# ============================================================
def gjr_oos_forecast(returns, is_end, refit_freq=63):
    n = len(returns)
    forecasts = np.full(n, np.nan)

    def gjr_negll_wrapper(params, r):
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


def har_oos_forecast(sigma2_series, is_end, refit_freq=63):
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


def estimate_prg_spy(r_overnight, r_intra, r2_overnight, r2_intra,
                     extended=False, n_starts=5):
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
    n_days = len(r_overnight)
    forecasts = np.full(n_days, np.nan)

    current_params = None
    h_state = None

    def _parse(params):
        o0, a0, b0 = params[0], params[1], params[2]
        o1, a1, b1 = params[3], params[4], params[5]
        g0 = params[6] if extended and len(params) > 6 else 0.0
        g1 = params[7] if extended and len(params) > 7 else 0.0
        return o0, a0, b0, g0, o1, a1, b1, g1

    for t in range(is_end, n_days):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            params, ll = estimate_prg_spy(
                r_overnight[:t], r_intra[:t],
                r2_overnight[:t], r2_intra[:t],
                extended=extended, n_starts=PRG_N_STARTS
            )
            if params is not None:
                current_params = params
                o0, a0, b0, g0, o1, a1, b1, g1 = _parse(current_params)
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

        x_prev = r2_intra[t-1]
        r_prev = r_intra[t-1]
        lev = g0 * x_prev * (1.0 if r_prev < 0 else 0.0)
        h_ov_t = o0 + a0 * x_prev + lev + b0 * h_state
        if h_ov_t < 1e-12: h_ov_t = 1e-12

        x_prev_in = r2_overnight[t]
        r_prev_in = r_overnight[t]
        lev = g1 * x_prev_in * (1.0 if r_prev_in < 0 else 0.0)
        h_in_t = o1 + a1 * x_prev_in + lev + b1 * h_ov_t
        if h_in_t < 1e-12: h_in_t = 1e-12

        forecasts[t] = h_ov_t + h_in_t

        h_state = _prg_propagate_days_numba(
            o0, a0, b0, g0, o1, a1, b1, g1,
            r_overnight, r_intra, r2_overnight, r2_intra,
            t, t+1, h_state
        )

    return forecasts


def separate_garch_oos(r_overnight, r_intra, r2_overnight, r2_intra,
                       is_end, refit_freq=63):
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
# ES COMPUTATION
# ============================================================
def compute_es_parametric_normal(sigma_forecast, alpha):
    """
    Parametric Normal ES at level alpha.
    ES_alpha = sigma * phi(z_alpha) / Phi(z_alpha)
    where z_alpha = Phi^{-1}(alpha).
    Note: ES is a negative number (loss convention).
    """
    z_alpha = sp_stats.norm.ppf(alpha)
    phi_z = sp_stats.norm.pdf(z_alpha)
    Phi_z = alpha  # Phi(z_alpha) = alpha by definition
    # ES = -sigma * phi(z_alpha) / alpha (loss = negative return)
    es = -sigma_forecast * phi_z / Phi_z
    return es  # negative values


def compute_es_historical_sim(returns_full, sigma2_forecasts_full, is_end_idx,
                               alpha):
    """
    Historical Simulation ES using standardized residuals (McNeil & Frey 2000).

    For each OOS day t:
    1. Compute z_s = r_s / sigma_s for all s < t where both are valid
    2. Take alpha-quantile and conditional mean below it
    3. ES_t = sigma_t * E[z | z < z_alpha]

    Uses an expanding window of standardized residuals up to each OOS day.
    For efficiency: compute once using all IS+early-OOS data as the pool,
    update every 63 days (quarterly).
    """
    n = len(returns_full)
    es_oos = np.full(n, np.nan)
    z_es_factor_last = np.nan
    z_var_quantile_last = np.nan

    # Build expanding pool of standardized residuals
    update_freq = 63
    z_pool = []

    for t in range(1, is_end_idx):
        if np.isfinite(returns_full[t]) and np.isfinite(sigma2_forecasts_full[t]) and sigma2_forecasts_full[t] > 0:
            z_pool.append(returns_full[t] / np.sqrt(sigma2_forecasts_full[t]))

    # If too few IS residuals, use raw returns for z estimation
    if len(z_pool) < 100:
        # Use unconditional standardized returns from IS
        valid_is = np.isfinite(returns_full[:is_end_idx])
        r_is = returns_full[:is_end_idx][valid_is]
        sigma_is = np.std(r_is)
        z_pool = list(r_is / sigma_is)

    z_arr = np.array(z_pool)
    z_quantile = np.percentile(z_arr, alpha * 100)
    z_below = z_arr[z_arr <= z_quantile]
    z_es_factor = np.mean(z_below) if len(z_below) >= 3 else z_quantile
    z_var_quantile_last = z_quantile
    z_es_factor_last = z_es_factor

    for t in range(is_end_idx, n):
        if np.isfinite(sigma2_forecasts_full[t]) and sigma2_forecasts_full[t] > 0:
            sigma_t = np.sqrt(sigma2_forecasts_full[t])
            es_oos[t] = sigma_t * z_es_factor  # negative

        # Update z pool with this day's realized residual (for next step)
        if (np.isfinite(returns_full[t]) and np.isfinite(sigma2_forecasts_full[t])
                and sigma2_forecasts_full[t] > 0):
            z_pool.append(returns_full[t] / np.sqrt(sigma2_forecasts_full[t]))

        # Periodically update z_es_factor
        if (t - is_end_idx) % update_freq == 0 and (t - is_end_idx) > 0:
            z_arr = np.array(z_pool)
            z_quantile = np.percentile(z_arr, alpha * 100)
            z_below = z_arr[z_arr <= z_quantile]
            z_es_factor = np.mean(z_below) if len(z_below) >= 3 else z_quantile
            z_var_quantile_last = z_quantile
            z_es_factor_last = z_es_factor

    return es_oos, z_es_factor_last, z_var_quantile_last


# ============================================================
# ES BACKTESTING
# ============================================================
def acerbi_szekely_test(returns, var_forecast, es_forecast, alpha, n_boot=5000):
    """
    Acerbi & Szekely (2014) ES backtest — Z_2 statistic.

    Z_2 = (1/(T*alpha)) * sum_t [ (r_t / ES_t) * I(r_t < VaR_t) ] + 1

    Under H0 (correct ES): E[Z_2] = 0.
    Bootstrap p-value by resampling (r_t, VaR_t, ES_t) triples.
    Reject if Z_2 significantly < 0 (ES underestimates tail risk).
    """
    valid = (np.isfinite(returns) & np.isfinite(var_forecast) &
             np.isfinite(es_forecast) & (es_forecast < 0))
    r = returns[valid]
    var_f = var_forecast[valid]
    es_f = es_forecast[valid]
    T = len(r)

    if T < 50:
        return {'Z2': np.nan, 'p_value': np.nan, 'n': T, 'reject': None}

    violations = r < var_f
    n_violations = int(np.sum(violations))

    # Z_2 statistic
    # Sum of r_t/ES_t for violation days, divided by T*alpha
    ratio_sum = np.sum((r / es_f) * violations)
    Z2 = ratio_sum / (T * alpha) + 1.0

    # Bootstrap for p-value
    rng = np.random.RandomState(42)
    boot_Z2 = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, T, T)
        r_b = r[idx]
        var_b = var_f[idx]
        es_b = es_f[idx]
        viol_b = r_b < var_b
        ratio_sum_b = np.sum((r_b / es_b) * viol_b)
        boot_Z2[b] = ratio_sum_b / (T * alpha) + 1.0

    # One-sided p-value: P(Z2_boot <= Z2_observed) under bootstrap distribution
    # Center the bootstrap around the observed value for null hypothesis testing
    # Alternative approach: p-value as fraction of bootstrap samples more extreme
    # Under H0, E[Z2] = 0, so we test if observed Z2 is significantly below 0
    boot_mean = np.mean(boot_Z2)
    boot_std = np.std(boot_Z2)
    if boot_std > 0:
        z_score = Z2 / boot_std  # standardized (centered at 0 under H0)
        p_value = sp_stats.norm.cdf(z_score)  # left-tail: reject if Z2 << 0
    else:
        p_value = 0.5

    reject = bool(p_value < 0.05)

    return {
        'Z2': float(Z2),
        'p_value': float(p_value),
        'n': T,
        'n_violations': n_violations,
        'violation_rate': float(n_violations / T),
        'reject_H0_at_5pct': reject,
        'interpretation': 'ES rejected (underestimates risk)' if reject else 'ES not rejected'
    }


def fissler_ziegel_score(returns, var_forecast, es_forecast, alpha):
    """
    Fissler & Ziegel (2016) consistent joint VaR-ES scoring function.

    S(VaR, ES, r) = (1/(-ES)) * (VaR - r) * I(r < VaR) + VaR/(-ES) + log(-ES) - 1

    This is the FZ0 loss function (homogeneous of degree 0).
    Lower = better. Consistent for joint (VaR, ES) elicitation.
    """
    valid = (np.isfinite(returns) & np.isfinite(var_forecast) &
             np.isfinite(es_forecast) & (es_forecast < 0) & (var_forecast < 0))
    r = returns[valid]
    var_f = var_forecast[valid]
    es_f = es_forecast[valid]
    n = len(r)

    if n < 50:
        return {'FZ_score': np.nan, 'n': n}

    neg_es = -es_f  # positive values
    violations = (r < var_f).astype(float)

    # FZ0 loss: Patton, Ziegel & Chen (2019) Eq. 3
    # S = (1/alpha)*I(r<VaR)*(VaR - r)/(-ES) - VaR/(-ES) + log(-ES) - 1
    # Simplified: using the standard form
    term1 = (1.0 / alpha) * violations * (var_f - r) / neg_es
    term2 = -var_f / neg_es
    term3 = np.log(neg_es)
    term4 = -1.0

    scores = term1 + term2 + term3 + term4
    mean_score = float(np.mean(scores))

    return {
        'FZ_score': mean_score,
        'FZ_scores_array': scores,
        'n': n,
    }


def es_violation_rate(returns, es_forecast):
    """
    ES violation rate: fraction of returns below ES forecast.
    Under correct ES at alpha, this should be < alpha (ES is more extreme than VaR).
    """
    valid = np.isfinite(returns) & np.isfinite(es_forecast) & (es_forecast < 0)
    r = returns[valid]
    es_f = es_forecast[valid]
    n = len(r)
    if n == 0:
        return {'es_violation_rate': np.nan, 'n': 0}
    n_below_es = int(np.sum(r < es_f))
    return {
        'es_violation_rate': float(n_below_es / n),
        'n_below_es': n_below_es,
        'n': n,
    }


def dm_test_fz_scores(fz_scores_1, fz_scores_2, model1_name, model2_name):
    """DM test on FZ scores. Lower FZ = better."""
    valid = np.isfinite(fz_scores_1) & np.isfinite(fz_scores_2)
    s1 = fz_scores_1[valid]
    s2 = fz_scores_2[valid]
    n = len(s1)
    if n < 100:
        return {'t_stat': np.nan, 'p_value': np.nan, 'n': n}

    d = s1 - s2  # positive => model 2 better (lower FZ)
    d_mean = np.mean(d)
    # Newey-West HAC variance
    max_lag = int(np.floor(n ** (1/3)))
    d_centered = d - d_mean
    gamma = np.zeros(max_lag + 1)
    for k in range(max_lag + 1):
        gamma[k] = np.mean(d_centered[k:] * d_centered[:n-k])
    hac_var = gamma[0] + 2 * sum((1 - k/(max_lag+1)) * gamma[k] for k in range(1, max_lag+1))
    t_stat = d_mean / np.sqrt(hac_var / n) if hac_var > 0 else 0.0
    p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), n-1))

    if t_stat > 0:
        winner = model2_name
    elif t_stat < 0:
        winner = model1_name
    else:
        winner = 'tie'

    return {
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'n': n,
        'winner': winner,
        'harvey_pass': bool(abs(t_stat) > 3.0),
    }


# ============================================================
# MAIN
# ============================================================
def main():
    t_start = datetime.now()
    print("=" * 70)
    print("K880b: ES Supplement for SPY PRG Validation")
    print("=" * 70)

    # 1. Load data
    df = load_spy_data()

    # Prepare arrays
    r_c2c = df['r_c2c'].values.astype(np.float64)
    r_overnight = df['r_overnight'].values.astype(np.float64)
    r_intra = df['r_intra'].values.astype(np.float64)
    r2_overnight = df['r2_overnight'].values.astype(np.float64)
    r2_intra = df['r2_intra'].values.astype(np.float64)
    sigma2_fullday = df['sigma2_fullday'].values.astype(np.float64)

    # Find IS end index
    is_end_dt = pd.Timestamp(IS_END_DATE)
    is_end_idx = df.index.get_indexer([is_end_dt], method='ffill')[0]
    if is_end_idx < 0:
        is_end_idx = np.searchsorted(df.index, is_end_dt)
    n_is = is_end_idx
    n_oos = len(df) - is_end_idx
    print(f"\nIS: {n_is} days, OOS: {n_oos} days")
    print(f"OOS period: {df.index[is_end_idx].date()} to {df.index[-1].date()}")

    # 2. Compute OOS forecasts for all models
    print("\n--- Computing OOS forecasts ---")

    print("  GJR-GARCH...")
    gjr_forecasts = gjr_oos_forecast(r_c2c, is_end_idx, refit_freq=REFIT_FREQ)
    print(f"    Valid forecasts: {np.sum(np.isfinite(gjr_forecasts[is_end_idx:]))}")

    print("  HAR-proxy...")
    har_forecasts = har_oos_forecast(sigma2_fullday, is_end_idx, refit_freq=REFIT_FREQ)
    print(f"    Valid forecasts: {np.sum(np.isfinite(har_forecasts[is_end_idx:]))}")

    print("  PRG Basic...")
    prg_basic_forecasts = prg_oos_forecast(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end_idx, extended=False, refit_freq=PRG_REFIT_FREQ
    )
    print(f"    Valid forecasts: {np.sum(np.isfinite(prg_basic_forecasts[is_end_idx:]))}")

    print("  PRG Extended...")
    prg_ext_forecasts = prg_oos_forecast(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end_idx, extended=True, refit_freq=PRG_REFIT_FREQ
    )
    print(f"    Valid forecasts: {np.sum(np.isfinite(prg_ext_forecasts[is_end_idx:]))}")

    print("  Separate GARCH...")
    sep_forecasts = separate_garch_oos(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end_idx, refit_freq=REFIT_FREQ
    )
    print(f"    Valid forecasts: {np.sum(np.isfinite(sep_forecasts[is_end_idx:]))}")

    # Collect all forecasts
    models = {
        'GJR': gjr_forecasts,
        'HAR': har_forecasts,
        'PRG_Basic': prg_basic_forecasts,
        'PRG_Extended': prg_ext_forecasts,
        'Separate': sep_forecasts,
    }

    # OOS returns (c2c for VaR/ES evaluation)
    oos_returns = r_c2c[is_end_idx:]
    oos_dates = df.index[is_end_idx:]

    # 3. ES Evaluation
    print("\n--- ES Evaluation ---")

    alpha_levels = [0.01, 0.05]
    results = {
        'experiment_id': 'K880b',
        'title': 'ES (Expected Shortfall) Supplement for K880 SPY PRG Validation',
        'type': 'empirical',
        'data_source': 'yfinance (SPY)',
        'period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'is_period': f"{df.index[0].date()} to {IS_END_DATE}",
        'oos_period': f"{df.index[is_end_idx].date()} to {df.index[-1].date()}",
        'n_is': int(n_is),
        'n_oos': int(n_oos),
        'es_parametric_normal': {},
        'es_historical_sim': {},
        'acerbi_szekely_tests': {},
        'fissler_ziegel_scores': {},
        'es_violation_rates': {},
        'fz_dm_tests': {},
    }

    # For each model and alpha level
    for model_name, sigma2_fc in models.items():
        print(f"\n  Model: {model_name}")
        results['es_parametric_normal'][model_name] = {}
        results['es_historical_sim'][model_name] = {}
        results['acerbi_szekely_tests'][model_name] = {}
        results['fissler_ziegel_scores'][model_name] = {}
        results['es_violation_rates'][model_name] = {}

        oos_fc = sigma2_fc[is_end_idx:]
        sigma_oos = np.sqrt(np.clip(oos_fc, 1e-12, None))

        for alpha in alpha_levels:
            alpha_key = f"{int(alpha*100)}pct"
            z_alpha = sp_stats.norm.ppf(alpha)

            # VaR forecast
            var_oos = z_alpha * sigma_oos  # negative

            # --- Method A: Parametric Normal ES ---
            es_param = compute_es_parametric_normal(sigma_oos, alpha)

            # --- Method B: Historical Simulation ES ---
            es_hs_full, z_es_factor, z_var_quantile = compute_es_historical_sim(
                r_c2c, sigma2_fc, is_end_idx, alpha
            )
            es_hs = es_hs_full[is_end_idx:]

            # ES violation rates
            evr_param = es_violation_rate(oos_returns, es_param)
            evr_hs = es_violation_rate(oos_returns, es_hs)

            # Acerbi-Szekely test (parametric)
            as_param = acerbi_szekely_test(oos_returns, var_oos, es_param, alpha)
            # Acerbi-Szekely test (historical sim)
            as_hs = acerbi_szekely_test(oos_returns, var_oos, es_hs, alpha)

            # Fissler-Ziegel score (parametric)
            fz_param = fissler_ziegel_score(oos_returns, var_oos, es_param, alpha)
            # Fissler-Ziegel score (historical sim)
            fz_hs = fissler_ziegel_score(oos_returns, var_oos, es_hs, alpha)

            print(f"    alpha={alpha}: "
                  f"Param ES viol rate={evr_param['es_violation_rate']:.4f}, "
                  f"HS ES viol rate={evr_hs['es_violation_rate']:.4f}")
            print(f"      A-S Param Z2={as_param['Z2']:.3f} p={as_param['p_value']:.4f} "
                  f"{'REJECT' if as_param.get('reject_H0_at_5pct') else 'OK'}")
            print(f"      A-S HS    Z2={as_hs['Z2']:.3f} p={as_hs['p_value']:.4f} "
                  f"{'REJECT' if as_hs.get('reject_H0_at_5pct') else 'OK'}")
            print(f"      FZ Param={fz_param['FZ_score']:.4f}, FZ HS={fz_hs['FZ_score']:.4f}")

            # Store results (remove arrays for JSON)
            results['es_parametric_normal'][model_name][alpha_key] = {
                'es_mean': float(np.nanmean(es_param)),
                'es_std': float(np.nanstd(es_param)),
            }
            results['es_historical_sim'][model_name][alpha_key] = {
                'z_es_factor': float(z_es_factor),
                'z_var_quantile': float(z_var_quantile),
                'es_mean': float(np.nanmean(es_hs)),
                'es_std': float(np.nanstd(es_hs)),
            }
            results['es_violation_rates'][model_name][alpha_key] = {
                'parametric': evr_param,
                'historical_sim': evr_hs,
            }
            results['acerbi_szekely_tests'][model_name][alpha_key] = {
                'parametric': {k: v for k, v in as_param.items()},
                'historical_sim': {k: v for k, v in as_hs.items()},
            }
            # Store FZ score (without array)
            fz_param_clean = {k: v for k, v in fz_param.items() if k != 'FZ_scores_array'}
            fz_hs_clean = {k: v for k, v in fz_hs.items() if k != 'FZ_scores_array'}
            results['fissler_ziegel_scores'][model_name][alpha_key] = {
                'parametric': fz_param_clean,
                'historical_sim': fz_hs_clean,
            }

    # 4. Pairwise DM tests on Fissler-Ziegel scores
    print("\n--- Pairwise DM tests on FZ scores ---")
    model_names = list(models.keys())

    for alpha in alpha_levels:
        alpha_key = f"{int(alpha*100)}pct"
        z_alpha = sp_stats.norm.ppf(alpha)

        # Recompute FZ score arrays for DM tests
        fz_arrays_param = {}
        fz_arrays_hs = {}

        for model_name, sigma2_fc in models.items():
            oos_fc = sigma2_fc[is_end_idx:]
            sigma_oos = np.sqrt(np.clip(oos_fc, 1e-12, None))
            var_oos = z_alpha * sigma_oos

            # Parametric ES
            es_param = compute_es_parametric_normal(sigma_oos, alpha)
            fz_p = fissler_ziegel_score(oos_returns, var_oos, es_param, alpha)
            if 'FZ_scores_array' in fz_p:
                fz_arrays_param[model_name] = fz_p['FZ_scores_array']

            # HS ES
            es_hs_full, _, _ = compute_es_historical_sim(r_c2c, sigma2_fc, is_end_idx, alpha)
            es_hs_oos = es_hs_full[is_end_idx:]
            fz_h = fissler_ziegel_score(oos_returns, var_oos, es_hs_oos, alpha)
            if 'FZ_scores_array' in fz_h:
                fz_arrays_hs[model_name] = fz_h['FZ_scores_array']

        # Pairwise DM on parametric FZ
        dm_results_param = {}
        dm_results_hs = {}

        for i in range(len(model_names)):
            for j in range(i+1, len(model_names)):
                m1, m2 = model_names[i], model_names[j]
                key = f"{m1}_vs_{m2}"

                if m1 in fz_arrays_param and m2 in fz_arrays_param:
                    dm_r = dm_test_fz_scores(fz_arrays_param[m1], fz_arrays_param[m2], m1, m2)
                    dm_results_param[key] = dm_r
                    print(f"    FZ-Param DM {alpha_key} {key}: t={dm_r['t_stat']:.2f} "
                          f"{'PASS' if dm_r.get('harvey_pass') else 'NS'} → {dm_r.get('winner')}")

                if m1 in fz_arrays_hs and m2 in fz_arrays_hs:
                    dm_r = dm_test_fz_scores(fz_arrays_hs[m1], fz_arrays_hs[m2], m1, m2)
                    dm_results_hs[key] = dm_r

        results['fz_dm_tests'][alpha_key] = {
            'parametric': dm_results_param,
            'historical_sim': dm_results_hs,
        }

    # 5. Summary table
    print("\n" + "=" * 70)
    print("SUMMARY: ES Evaluation Results")
    print("=" * 70)

    for alpha in alpha_levels:
        alpha_key = f"{int(alpha*100)}pct"
        print(f"\n--- alpha = {alpha} ({alpha_key}) ---")
        print(f"{'Model':<16} {'ES Viol(P)':<12} {'ES Viol(HS)':<12} "
              f"{'A-S Z2(P)':<10} {'A-S p(P)':<9} {'A-S(P)':<8} "
              f"{'A-S Z2(HS)':<10} {'A-S p(HS)':<9} {'A-S(HS)':<8} "
              f"{'FZ(P)':<10} {'FZ(HS)':<10}")
        print("-" * 130)

        for model_name in model_names:
            evr_p = results['es_violation_rates'][model_name][alpha_key]['parametric']['es_violation_rate']
            evr_h = results['es_violation_rates'][model_name][alpha_key]['historical_sim']['es_violation_rate']
            as_p = results['acerbi_szekely_tests'][model_name][alpha_key]['parametric']
            as_h = results['acerbi_szekely_tests'][model_name][alpha_key]['historical_sim']
            fz_p = results['fissler_ziegel_scores'][model_name][alpha_key]['parametric']['FZ_score']
            fz_h = results['fissler_ziegel_scores'][model_name][alpha_key]['historical_sim']['FZ_score']

            as_p_status = 'REJECT' if as_p.get('reject_H0_at_5pct') else 'OK'
            as_h_status = 'REJECT' if as_h.get('reject_H0_at_5pct') else 'OK'

            print(f"{model_name:<16} {evr_p:<12.4f} {evr_h:<12.4f} "
                  f"{as_p['Z2']:<10.3f} {as_p['p_value']:<9.4f} {as_p_status:<8} "
                  f"{as_h['Z2']:<10.3f} {as_h['p_value']:<9.4f} {as_h_status:<8} "
                  f"{fz_p:<10.4f} {fz_h:<10.4f}")

    # 6. Rankings
    print("\n\n--- FZ Score Rankings (lower = better) ---")
    for alpha in alpha_levels:
        alpha_key = f"{int(alpha*100)}pct"
        print(f"\nalpha={alpha} (Parametric ES):")
        fz_scores = [(m, results['fissler_ziegel_scores'][m][alpha_key]['parametric']['FZ_score'])
                     for m in model_names]
        fz_scores.sort(key=lambda x: x[1])
        for rank, (m, s) in enumerate(fz_scores, 1):
            print(f"  {rank}. {m}: {s:.4f}")

        print(f"\nalpha={alpha} (HS ES):")
        fz_scores = [(m, results['fissler_ziegel_scores'][m][alpha_key]['historical_sim']['FZ_score'])
                     for m in model_names]
        fz_scores.sort(key=lambda x: x[1])
        for rank, (m, s) in enumerate(fz_scores, 1):
            print(f"  {rank}. {m}: {s:.4f}")

    # Key findings
    findings = []

    # Best FZ score at 1%
    fz_1p_param = {m: results['fissler_ziegel_scores'][m]['1pct']['parametric']['FZ_score']
                   for m in model_names}
    best_fz_1p = min(fz_1p_param, key=fz_1p_param.get)
    findings.append(f"Best FZ score at 1% (param): {best_fz_1p} ({fz_1p_param[best_fz_1p]:.4f})")

    fz_5p_param = {m: results['fissler_ziegel_scores'][m]['5pct']['parametric']['FZ_score']
                   for m in model_names}
    best_fz_5p = min(fz_5p_param, key=fz_5p_param.get)
    findings.append(f"Best FZ score at 5% (param): {best_fz_5p} ({fz_5p_param[best_fz_5p]:.4f})")

    # Count A-S rejections
    for alpha in alpha_levels:
        alpha_key = f"{int(alpha*100)}pct"
        n_reject_p = sum(1 for m in model_names
                         if results['acerbi_szekely_tests'][m][alpha_key]['parametric'].get('reject_H0_at_5pct'))
        n_reject_h = sum(1 for m in model_names
                         if results['acerbi_szekely_tests'][m][alpha_key]['historical_sim'].get('reject_H0_at_5pct'))
        findings.append(f"A-S rejected at {alpha_key} — Param: {n_reject_p}/5, HS: {n_reject_h}/5")

    # PRG vs GJR FZ DM at 1%
    if '1pct' in results['fz_dm_tests']:
        dm_key = 'GJR_vs_PRG_Extended'
        if dm_key in results['fz_dm_tests']['1pct']['parametric']:
            dm_r = results['fz_dm_tests']['1pct']['parametric'][dm_key]
            findings.append(f"FZ DM 1% PRG_Ext vs GJR: t={dm_r['t_stat']:.2f}, "
                           f"{'Harvey PASS' if dm_r['harvey_pass'] else 'Harvey NS'}, "
                           f"winner={dm_r['winner']}")

    results['key_findings'] = findings
    results['runtime_seconds'] = (datetime.now() - t_start).total_seconds()
    results['references'] = [
        "Acerbi & Szekely (2014): Backtesting Expected Shortfall. Risk.",
        "Fissler & Ziegel (2016): Higher order elicitability. Ann. Stat.",
        "McNeil & Frey (2000): Estimation of tail-related risk measures. J. Empirical Finance.",
        "Patton, Ziegel & Chen (2019): Dynamic semiparametric models for ES. J. Econometrics.",
        "Basel Committee (2019): MAR 99. Minimum capital requirements for market risk.",
        "K880: PRG Cross-Market Validation on SPY",
    ]

    print("\n\nKey Findings:")
    for f in findings:
        print(f"  * {f}")

    # Save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {OUTPUT_FILE}")
    print(f"Runtime: {results['runtime_seconds']:.1f} seconds")


if __name__ == "__main__":
    main()
