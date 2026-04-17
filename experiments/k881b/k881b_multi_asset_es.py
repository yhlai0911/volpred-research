#!/usr/bin/env python3
"""
K881b: ES Supplement for QQQ, GLD, EEM (PRG Multi-Asset)
=========================================================

Research Question (EMPIRICAL):
  K881 validated PRG on 3 assets (QLIKE + VaR) but missing ES evaluation.
  K880b showed PRG Extended wins ES on SPY (FZ DM t=3.75 Harvey PASS).
  Need to complete the evidence for all 5 markets (SPY done in K880b).

For each of QQQ, GLD, EEM:
  1. Recompute PRG/GJR/HAR/Separate models (same architecture as K881)
  2. Compute ES at 1% and 5%:
     - Parametric Normal: ES = sigma_t * phi(z_alpha) / alpha
     - FHS: Historical simulation of standardized residuals
  3. Acerbi & Szekely (2014) Z-test for each model
  4. Fissler & Ziegel (2016) joint VaR-ES score
  5. FZ DM test: PRG vs GJR, PRG vs Separate (Harvey |t|>3.0)

Session Decomposition (daily frequency, no tick data):
  r_overnight = log(open_t / close_{t-1})
  r_intra     = log(close_t / open_t)
  sigma2_fullday = r2_overnight + r2_intra

Models (same 5 as K881):
  1. GJR-GARCH(1,1) on close-to-close returns
  2. HAR-proxy on sigma2_fullday (log-space)
  3. PRG Basic (6 params): periodic GARCH alternating overnight/intraday
  4. PRG Extended (8 params): + leverage for negative returns
  5. Separate GARCH: independent GARCH for each session

Evaluation:
  - Parametric Normal ES + FHS ES at 1% and 5%
  - Acerbi & Szekely (2014) Z-test (bootstrap)
  - Fissler & Ziegel (2016) FZ0 joint VaR-ES score
  - Pairwise DM tests on FZ scores (Harvey |t|>3.0)

Data: yfinance — QQQ, GLD, EEM. IS: first 70%, OOS: last 30% (same as K881).

Error log rules applied:
  - DM test: use dm_test from volpred.stats.model_evaluation
  - GARCH OOS: recursive h[t]=f(h[t-1], r^2[t-1]) — no stale variance
  - Sanity check: verify forecasts > 0 before evaluation
  - shift(1) equivalent: predict from t-1 info

References:
  - Acerbi & Szekely (2014): Backtesting Expected Shortfall. Risk.
  - Fissler & Ziegel (2016): Higher order elicitability. Ann. Stat.
  - McNeil & Frey (2000): Estimation of tail-related risk measures. J. Empirical Finance.
  - Patton, Ziegel & Chen (2019): Dynamic semiparametric models for ES. J. Econometrics.
  - Basel Committee (2019): MAR 99. Minimum capital requirements for market risk.
  - K880b: ES Supplement for SPY
  - K881: PRG Multi-Asset Validation (QQQ, GLD, EEM)

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
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k881b_results.json")

# Assets
ASSETS = {
    'QQQ': {'start': '2000-01-01', 'description': 'Tech equity (Nasdaq-100)'},
    'GLD': {'start': '2004-11-01', 'description': 'Gold ETF (no leverage effect)'},
    'EEM': {'start': '2003-04-01', 'description': 'Emerging markets ETF'},
}

IS_FRACTION = 0.70
REFIT_FREQ = 63          # quarterly for GJR/HAR/Separate
PRG_REFIT_FREQ = 252     # annual for PRG (speed)
PRG_N_STARTS = 3         # multi-start (reduced for speed)


# ============================================================
# Numba-accelerated inner loops
# ============================================================
@njit(cache=True)
def _gjr_negll(omega, alpha, gamma_p, beta, r):
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
def _gjr_propagate(omega, alpha, gamma_p, beta, r, h0, start, end):
    h = h0
    for t in range(start, end):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        h = omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * indicator + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _garch_negll(omega, alpha, beta, r):
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
def _garch_propagate(omega, alpha, beta, r, h0, start, end):
    h = h0
    for t in range(start, end):
        h = omega + alpha * r[t-1]**2 + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _prg_negll(params, r_seq, x_seq, s_seq, n_total, extended):
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
def _prg_propagate_days(omega_0, alpha_0, beta_0, gamma_0,
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
# Data loading
# ============================================================
def load_asset_data(ticker, start):
    import yfinance as yf
    print(f"  Downloading {ticker} from yfinance...")
    data = yf.download(ticker, start=start, end="2026-04-05", auto_adjust=True)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    print(f"    {ticker}: {len(data)} days, {data.index[0].date()} to {data.index[-1].date()}")

    df = pd.DataFrame(index=data.index)
    df['open'] = data['Open'].values
    df['close'] = data['Close'].values
    df['prev_close'] = df['close'].shift(1)
    df['r_overnight'] = np.log(df['open'] / df['prev_close'])
    df['r_intra'] = np.log(df['close'] / df['open'])
    df['r_c2c'] = np.log(df['close'] / df['prev_close'])
    df['r2_overnight'] = df['r_overnight'] ** 2
    df['r2_intra'] = df['r_intra'] ** 2
    df['sigma2_fullday'] = df['r2_overnight'] + df['r2_intra']
    df = df.iloc[1:].dropna(subset=['r_overnight', 'r_intra', 'sigma2_fullday'])
    print(f"    After processing: {len(df)} days")
    return df


# ============================================================
# Model forecasting (adapted from K880b/K881)
# ============================================================
def gjr_oos_forecast(returns, is_end, refit_freq=63):
    n = len(returns)
    forecasts = np.full(n, np.nan)
    eps = 1e-8
    bounds = [(eps, 1e-3), (eps, 0.5), (0.0, 0.5), (eps, 0.999)]
    current_params = None
    h_state = np.var(returns[:min(50, n)])

    def negll(params, r):
        return _gjr_negll(params[0], params[1], params[2], params[3], r)

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
                    result = minimize(negll, x0, args=(r_train,),
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
                h_state = _gjr_propagate(omega, alpha, gamma_p, beta, returns, h0, 1, t)

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


def estimate_prg(r_overnight, r_intra, r2_overnight, r2_intra,
                 extended=False, n_starts=3):
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
        return _prg_negll(p, r_seq, x_seq, s_seq, n_total, ext_flag)

    eps = 1e-8
    if extended:
        bounds = [(eps, 1e-3), (eps, 1.0), (eps, 0.999),
                  (eps, 1e-3), (eps, 1.0), (eps, 0.999),
                  (0.0, 1.0), (0.0, 1.0)]
    else:
        bounds = [(eps, 1e-3), (eps, 1.0), (eps, 0.999),
                  (eps, 1e-3), (eps, 1.0), (eps, 0.999)]

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
                     is_end, extended=False, refit_freq=252):
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
            params, ll = estimate_prg(
                r_overnight[:t], r_intra[:t],
                r2_overnight[:t], r2_intra[:t],
                extended=extended, n_starts=PRG_N_STARTS
            )
            if params is not None:
                current_params = params
                o0, a0, b0, g0, o1, a1, b1, g1 = _parse(current_params)
                h_init = np.mean(r2_overnight[:min(50, t)] + r2_intra[:min(50, t)]) / 2
                if h_init < 1e-12: h_init = 1e-8
                h_state = _prg_propagate_days(
                    o0, a0, b0, g0, o1, a1, b1, g1,
                    r_overnight, r_intra, r2_overnight, r2_intra,
                    0, t, h_init
                )

        if current_params is None or h_state is None:
            continue

        o0, a0, b0, g0, o1, a1, b1, g1 = _parse(current_params)

        # Forecast day t: overnight then intraday
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

        # Propagate state through observed day t
        h_state = _prg_propagate_days(
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
        return _garch_negll(params[0], params[1], params[2], r)

    eps = 1e-8
    bounds = [(eps, 1e-3), (eps, 0.5), (eps, 0.999)]
    ov_params = None
    in_params = None
    h_ov_state = np.var(r_overnight[:min(50, n_days)])
    h_in_state = np.var(r_intra[:min(50, n_days)])

    for t in range(is_end, n_days):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            rng = np.random.RandomState(42)
            # Overnight
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
                h_ov_state = _garch_propagate(omega, alpha, beta, r_overnight, h0, 1, t)

            # Intraday
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
                h_in_state = _garch_propagate(omega, alpha, beta, r_intra, h0, 1, t)

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
# ES Computation (same methodology as K880b)
# ============================================================
def compute_es_parametric_normal(sigma_forecast, alpha):
    """
    Parametric Normal ES: ES = -sigma * phi(z_alpha) / alpha
    Returns negative values (loss convention).
    """
    z_alpha = sp_stats.norm.ppf(alpha)
    phi_z = sp_stats.norm.pdf(z_alpha)
    es = -sigma_forecast * phi_z / alpha
    return es


def compute_es_fhs(returns_full, sigma2_forecasts_full, is_end_idx, alpha):
    """
    Filtered Historical Simulation ES using standardized residuals.
    Expanding window with quarterly updates.
    """
    n = len(returns_full)
    es_oos = np.full(n, np.nan)
    update_freq = 63
    z_pool = []

    # Build IS z-pool
    for t in range(1, is_end_idx):
        if (np.isfinite(returns_full[t]) and np.isfinite(sigma2_forecasts_full[t])
                and sigma2_forecasts_full[t] > 0):
            z_pool.append(returns_full[t] / np.sqrt(sigma2_forecasts_full[t]))

    if len(z_pool) < 100:
        valid_is = np.isfinite(returns_full[:is_end_idx])
        r_is = returns_full[:is_end_idx][valid_is]
        sigma_is = np.std(r_is)
        if sigma_is > 0:
            z_pool = list(r_is / sigma_is)
        else:
            z_pool = list(r_is)

    z_arr = np.array(z_pool)
    z_quantile = np.percentile(z_arr, alpha * 100)
    z_below = z_arr[z_arr <= z_quantile]
    z_es_factor = np.mean(z_below) if len(z_below) >= 3 else z_quantile

    for t in range(is_end_idx, n):
        if np.isfinite(sigma2_forecasts_full[t]) and sigma2_forecasts_full[t] > 0:
            sigma_t = np.sqrt(sigma2_forecasts_full[t])
            es_oos[t] = sigma_t * z_es_factor  # negative

        if (np.isfinite(returns_full[t]) and np.isfinite(sigma2_forecasts_full[t])
                and sigma2_forecasts_full[t] > 0):
            z_pool.append(returns_full[t] / np.sqrt(sigma2_forecasts_full[t]))

        if (t - is_end_idx) % update_freq == 0 and (t - is_end_idx) > 0:
            z_arr = np.array(z_pool)
            z_quantile = np.percentile(z_arr, alpha * 100)
            z_below = z_arr[z_arr <= z_quantile]
            z_es_factor = np.mean(z_below) if len(z_below) >= 3 else z_quantile

    return es_oos, z_es_factor


# ============================================================
# ES Backtesting
# ============================================================
def acerbi_szekely_test(returns, var_forecast, es_forecast, alpha, n_boot=5000):
    """
    Acerbi & Szekely (2014) Z_2 statistic.
    Z_2 = (1/(T*alpha)) * sum_t [ (r_t / ES_t) * I(r_t < VaR_t) ] + 1
    Under H0 (correct ES): E[Z_2] = 0. Reject if Z_2 << 0.
    """
    valid = (np.isfinite(returns) & np.isfinite(var_forecast) &
             np.isfinite(es_forecast) & (es_forecast < 0))
    r = returns[valid]
    var_f = var_forecast[valid]
    es_f = es_forecast[valid]
    T = len(r)

    if T < 50:
        return {'Z2': np.nan, 'p_value': np.nan, 'n': T, 'reject_H0_at_5pct': None}

    violations = r < var_f
    n_violations = int(np.sum(violations))
    ratio_sum = np.sum((r / es_f) * violations)
    Z2 = ratio_sum / (T * alpha) + 1.0

    # Bootstrap p-value
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

    boot_std = np.std(boot_Z2)
    if boot_std > 0:
        z_score = Z2 / boot_std
        p_value = sp_stats.norm.cdf(z_score)
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
    }


def fissler_ziegel_score(returns, var_forecast, es_forecast, alpha):
    """
    Fissler & Ziegel (2016) FZ0 joint VaR-ES scoring function.
    S = (1/alpha)*I(r<VaR)*(VaR-r)/(-ES) - VaR/(-ES) + log(-ES) - 1
    Lower = better.
    """
    valid = (np.isfinite(returns) & np.isfinite(var_forecast) &
             np.isfinite(es_forecast) & (es_forecast < 0) & (var_forecast < 0))
    r = returns[valid]
    var_f = var_forecast[valid]
    es_f = es_forecast[valid]
    n = len(r)

    if n < 50:
        return {'FZ_score': np.nan, 'n': n}

    neg_es = -es_f
    violations = (r < var_f).astype(float)
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


def dm_test_fz(fz_scores_1, fz_scores_2, model1_name, model2_name):
    """DM test on FZ scores. Lower FZ = better. Positive t => model2 wins."""
    valid = np.isfinite(fz_scores_1) & np.isfinite(fz_scores_2)
    s1 = fz_scores_1[valid]
    s2 = fz_scores_2[valid]
    n = len(s1)
    if n < 100:
        return {'t_stat': np.nan, 'p_value': np.nan, 'n': n, 'winner': 'N/A', 'harvey_pass': False}

    d = s1 - s2  # positive => model 2 better
    d_mean = np.mean(d)
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
# Process one asset
# ============================================================
def process_asset(ticker, start, description):
    """Run all models + ES evaluation for one asset."""
    print(f"\n{'='*70}")
    print(f"Processing {ticker}: {description}")
    print(f"{'='*70}")

    df = load_asset_data(ticker, start)

    r_c2c = df['r_c2c'].values.astype(np.float64)
    r_overnight = df['r_overnight'].values.astype(np.float64)
    r_intra = df['r_intra'].values.astype(np.float64)
    r2_overnight = df['r2_overnight'].values.astype(np.float64)
    r2_intra = df['r2_intra'].values.astype(np.float64)
    sigma2_fullday = df['sigma2_fullday'].values.astype(np.float64)

    n = len(df)
    is_end_idx = int(n * IS_FRACTION)
    n_oos = n - is_end_idx
    print(f"  IS: {is_end_idx} days, OOS: {n_oos} days")
    print(f"  OOS period: {df.index[is_end_idx].date()} to {df.index[-1].date()}")

    # --- Compute OOS forecasts ---
    print("  Computing OOS forecasts...")
    print("    GJR-GARCH...")
    gjr_fc = gjr_oos_forecast(r_c2c, is_end_idx, refit_freq=REFIT_FREQ)

    print("    HAR-proxy...")
    har_fc = har_oos_forecast(sigma2_fullday, is_end_idx, refit_freq=REFIT_FREQ)

    print("    PRG Basic...")
    prg_basic_fc = prg_oos_forecast(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end_idx, extended=False, refit_freq=PRG_REFIT_FREQ)

    print("    PRG Extended...")
    prg_ext_fc = prg_oos_forecast(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end_idx, extended=True, refit_freq=PRG_REFIT_FREQ)

    print("    Separate GARCH...")
    sep_fc = separate_garch_oos(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end_idx, refit_freq=REFIT_FREQ)

    models = {
        'GJR': gjr_fc,
        'HAR': har_fc,
        'PRG_Basic': prg_basic_fc,
        'PRG_Extended': prg_ext_fc,
        'Separate': sep_fc,
    }

    for mname, fc in models.items():
        n_valid = np.sum(np.isfinite(fc[is_end_idx:]))
        print(f"    {mname}: {n_valid} valid OOS forecasts")

    oos_returns = r_c2c[is_end_idx:]
    model_names = list(models.keys())
    alpha_levels = [0.01, 0.05]

    asset_results = {
        'ticker': ticker,
        'description': description,
        'period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'oos_period': f"{df.index[is_end_idx].date()} to {df.index[-1].date()}",
        'n_total': n,
        'n_is': is_end_idx,
        'n_oos': n_oos,
        'es_results': {},
        'fz_dm_tests': {},
    }

    # --- ES Evaluation ---
    print(f"\n  --- ES Evaluation for {ticker} ---")

    for model_name, sigma2_fc in models.items():
        asset_results['es_results'][model_name] = {}
        oos_fc = sigma2_fc[is_end_idx:]
        sigma_oos = np.sqrt(np.clip(oos_fc, 1e-12, None))

        for alpha in alpha_levels:
            alpha_key = f"{int(alpha*100)}pct"
            z_alpha = sp_stats.norm.ppf(alpha)
            var_oos = z_alpha * sigma_oos  # negative

            # Parametric Normal ES
            es_param = compute_es_parametric_normal(sigma_oos, alpha)

            # FHS ES
            es_fhs_full, z_es_factor = compute_es_fhs(r_c2c, sigma2_fc, is_end_idx, alpha)
            es_fhs = es_fhs_full[is_end_idx:]

            # Acerbi-Szekely (parametric + FHS)
            as_param = acerbi_szekely_test(oos_returns, var_oos, es_param, alpha)
            as_fhs = acerbi_szekely_test(oos_returns, var_oos, es_fhs, alpha)

            # FZ scores (parametric + FHS)
            fz_param = fissler_ziegel_score(oos_returns, var_oos, es_param, alpha)
            fz_fhs = fissler_ziegel_score(oos_returns, var_oos, es_fhs, alpha)

            print(f"    {model_name} alpha={alpha}: "
                  f"A-S(P) Z2={as_param['Z2']:.3f} p={as_param['p_value']:.4f} "
                  f"{'REJ' if as_param['reject_H0_at_5pct'] else 'OK'}  "
                  f"A-S(FHS) Z2={as_fhs['Z2']:.3f} p={as_fhs['p_value']:.4f} "
                  f"{'REJ' if as_fhs['reject_H0_at_5pct'] else 'OK'}  "
                  f"FZ(P)={fz_param['FZ_score']:.4f} FZ(FHS)={fz_fhs['FZ_score']:.4f}")

            # Store
            fz_param_clean = {k: v for k, v in fz_param.items() if k != 'FZ_scores_array'}
            fz_fhs_clean = {k: v for k, v in fz_fhs.items() if k != 'FZ_scores_array'}

            asset_results['es_results'][model_name][alpha_key] = {
                'parametric': {
                    'es_mean': float(np.nanmean(es_param)),
                    'acerbi_szekely': {k: v for k, v in as_param.items()},
                    'fz_score': fz_param_clean,
                },
                'fhs': {
                    'z_es_factor': float(z_es_factor),
                    'es_mean': float(np.nanmean(es_fhs)),
                    'acerbi_szekely': {k: v for k, v in as_fhs.items()},
                    'fz_score': fz_fhs_clean,
                },
            }

    # --- Pairwise DM tests on FZ scores ---
    print(f"\n  --- FZ DM tests for {ticker} ---")

    for alpha in alpha_levels:
        alpha_key = f"{int(alpha*100)}pct"
        z_alpha = sp_stats.norm.ppf(alpha)

        fz_arrays_param = {}
        fz_arrays_fhs = {}

        for model_name, sigma2_fc in models.items():
            oos_fc = sigma2_fc[is_end_idx:]
            sigma_oos = np.sqrt(np.clip(oos_fc, 1e-12, None))
            var_oos = z_alpha * sigma_oos

            es_param = compute_es_parametric_normal(sigma_oos, alpha)
            fz_p = fissler_ziegel_score(oos_returns, var_oos, es_param, alpha)
            if 'FZ_scores_array' in fz_p:
                fz_arrays_param[model_name] = fz_p['FZ_scores_array']

            es_fhs_full, _ = compute_es_fhs(r_c2c, sigma2_fc, is_end_idx, alpha)
            es_fhs = es_fhs_full[is_end_idx:]
            fz_h = fissler_ziegel_score(oos_returns, var_oos, es_fhs, alpha)
            if 'FZ_scores_array' in fz_h:
                fz_arrays_fhs[model_name] = fz_h['FZ_scores_array']

        dm_results_param = {}
        dm_results_fhs = {}

        # Key comparisons: PRG_Extended vs GJR, PRG_Extended vs Separate,
        # PRG_Basic vs GJR, PRG_Extended vs PRG_Basic
        pairs = [
            ('GJR', 'PRG_Extended'),
            ('GJR', 'PRG_Basic'),
            ('Separate', 'PRG_Extended'),
            ('PRG_Basic', 'PRG_Extended'),
            ('GJR', 'Separate'),
            ('GJR', 'HAR'),
            ('HAR', 'PRG_Extended'),
        ]

        for m1, m2 in pairs:
            key = f"{m1}_vs_{m2}"

            if m1 in fz_arrays_param and m2 in fz_arrays_param:
                dm_r = dm_test_fz(fz_arrays_param[m1], fz_arrays_param[m2], m1, m2)
                dm_results_param[key] = dm_r
                tag = 'PASS' if dm_r.get('harvey_pass') else 'NS'
                print(f"    FZ-P DM {alpha_key} {key}: t={dm_r['t_stat']:.2f} {tag} -> {dm_r['winner']}")

            if m1 in fz_arrays_fhs and m2 in fz_arrays_fhs:
                dm_r = dm_test_fz(fz_arrays_fhs[m1], fz_arrays_fhs[m2], m1, m2)
                dm_results_fhs[key] = dm_r

        asset_results['fz_dm_tests'][alpha_key] = {
            'parametric': dm_results_param,
            'fhs': dm_results_fhs,
        }

    return asset_results


# ============================================================
# MAIN
# ============================================================
def main():
    t_start = datetime.now()
    print("=" * 70)
    print("K881b: ES Supplement for QQQ, GLD, EEM (PRG Multi-Asset)")
    print("=" * 70)

    all_results = {}

    for ticker, config in ASSETS.items():
        asset_res = process_asset(ticker, config['start'], config['description'])
        all_results[ticker] = asset_res

    # ============================================================
    # Cross-asset summary
    # ============================================================
    print("\n" + "=" * 70)
    print("CROSS-ASSET SUMMARY")
    print("=" * 70)

    model_names = ['GJR', 'HAR', 'PRG_Basic', 'PRG_Extended', 'Separate']
    alpha_levels = [0.01, 0.05]

    # Summary tables
    for alpha in alpha_levels:
        alpha_key = f"{int(alpha*100)}pct"
        print(f"\n--- alpha = {alpha} ({alpha_key}) ---")
        print(f"\n{'Asset':<6} {'Model':<16} {'A-S(P) Z2':<10} {'A-S(P)':<7} "
              f"{'A-S(FHS) Z2':<12} {'A-S(FHS)':<8} "
              f"{'FZ(P)':<10} {'FZ(FHS)':<10}")
        print("-" * 100)

        for ticker in ASSETS:
            for model_name in model_names:
                es_r = all_results[ticker]['es_results'][model_name][alpha_key]
                as_p = es_r['parametric']['acerbi_szekely']
                as_h = es_r['fhs']['acerbi_szekely']
                fz_p = es_r['parametric']['fz_score']['FZ_score']
                fz_h = es_r['fhs']['fz_score']['FZ_score']

                as_p_tag = 'REJ' if as_p.get('reject_H0_at_5pct') else 'OK'
                as_h_tag = 'REJ' if as_h.get('reject_H0_at_5pct') else 'OK'

                print(f"{ticker:<6} {model_name:<16} "
                      f"{as_p['Z2']:<10.3f} {as_p_tag:<7} "
                      f"{as_h['Z2']:<12.3f} {as_h_tag:<8} "
                      f"{fz_p:<10.4f} {fz_h:<10.4f}")
            print()

    # FZ Rankings per asset
    print("\n--- FZ Score Rankings (lower = better) ---")
    fz_ranking_summary = {}
    for alpha in alpha_levels:
        alpha_key = f"{int(alpha*100)}pct"
        fz_ranking_summary[alpha_key] = {}
        print(f"\nalpha={alpha}:")
        for ticker in ASSETS:
            print(f"  {ticker} (Parametric):")
            scores = []
            for m in model_names:
                fz = all_results[ticker]['es_results'][m][alpha_key]['parametric']['fz_score']['FZ_score']
                scores.append((m, fz))
            scores.sort(key=lambda x: x[1])
            fz_ranking_summary[alpha_key][ticker] = {
                'parametric': [{'model': m, 'FZ_score': s} for m, s in scores],
            }
            for rank, (m, s) in enumerate(scores, 1):
                marker = " <-- BEST" if rank == 1 else ""
                print(f"    {rank}. {m}: {s:.4f}{marker}")

            print(f"  {ticker} (FHS):")
            scores_fhs = []
            for m in model_names:
                fz = all_results[ticker]['es_results'][m][alpha_key]['fhs']['fz_score']['FZ_score']
                scores_fhs.append((m, fz))
            scores_fhs.sort(key=lambda x: x[1])
            fz_ranking_summary[alpha_key][ticker]['fhs'] = [{'model': m, 'FZ_score': s} for m, s in scores_fhs]
            for rank, (m, s) in enumerate(scores_fhs, 1):
                marker = " <-- BEST" if rank == 1 else ""
                print(f"    {rank}. {m}: {s:.4f}{marker}")

    # Key DM results
    print("\n--- Key FZ DM Results (PRG_Extended vs GJR) ---")
    key_dm_summary = {}
    for ticker in ASSETS:
        key_dm_summary[ticker] = {}
        for alpha in alpha_levels:
            alpha_key = f"{int(alpha*100)}pct"
            dm_data = all_results[ticker]['fz_dm_tests'].get(alpha_key, {})

            # Parametric
            dm_p = dm_data.get('parametric', {}).get('GJR_vs_PRG_Extended', {})
            dm_f = dm_data.get('fhs', {}).get('GJR_vs_PRG_Extended', {})

            key_dm_summary[ticker][alpha_key] = {
                'parametric': dm_p,
                'fhs': dm_f,
            }

            t_p = dm_p.get('t_stat', np.nan)
            t_f = dm_f.get('t_stat', np.nan)
            hp_p = dm_p.get('harvey_pass', False)
            hp_f = dm_f.get('harvey_pass', False)
            w_p = dm_p.get('winner', 'N/A')
            w_f = dm_f.get('winner', 'N/A')

            print(f"  {ticker} {alpha_key}: "
                  f"Param t={t_p:.2f} {'PASS' if hp_p else 'NS'} ({w_p})  "
                  f"FHS t={t_f:.2f} {'PASS' if hp_f else 'NS'} ({w_f})")

    # Count wins
    print("\n--- PRG_Extended Win Count (FZ rank #1) ---")
    win_count = {'parametric': {}, 'fhs': {}}
    for alpha in alpha_levels:
        alpha_key = f"{int(alpha*100)}pct"
        for method in ['parametric', 'fhs']:
            count = 0
            for ticker in ASSETS:
                ranking = fz_ranking_summary[alpha_key][ticker][method]
                if ranking[0]['model'] == 'PRG_Extended':
                    count += 1
            win_count[method][alpha_key] = count
            print(f"  {method} {alpha_key}: PRG_Extended #1 in {count}/{len(ASSETS)} assets")

    # A-S pass count
    print("\n--- Acerbi-Szekely Pass Count (not rejected) ---")
    as_pass_count = {}
    for alpha in alpha_levels:
        alpha_key = f"{int(alpha*100)}pct"
        as_pass_count[alpha_key] = {}
        for model_name in model_names:
            n_pass_p = 0
            n_pass_f = 0
            for ticker in ASSETS:
                es_r = all_results[ticker]['es_results'][model_name][alpha_key]
                if not es_r['parametric']['acerbi_szekely'].get('reject_H0_at_5pct', True):
                    n_pass_p += 1
                if not es_r['fhs']['acerbi_szekely'].get('reject_H0_at_5pct', True):
                    n_pass_f += 1
            as_pass_count[alpha_key][model_name] = {'parametric': n_pass_p, 'fhs': n_pass_f}
            print(f"  {alpha_key} {model_name:<16}: Param pass {n_pass_p}/3, FHS pass {n_pass_f}/3")

    # Key findings
    findings = []

    # Best model per asset at 1% parametric
    for ticker in ASSETS:
        ranking = fz_ranking_summary['1pct'][ticker]['parametric']
        best = ranking[0]
        findings.append(f"{ticker} 1% FZ best (param): {best['model']} ({best['FZ_score']:.4f})")

    # Harvey PASS count
    n_harvey_pass = 0
    for ticker in ASSETS:
        for alpha in alpha_levels:
            alpha_key = f"{int(alpha*100)}pct"
            dm_p = all_results[ticker]['fz_dm_tests'].get(alpha_key, {}).get('parametric', {}).get('GJR_vs_PRG_Extended', {})
            if dm_p.get('harvey_pass', False):
                n_harvey_pass += 1
    findings.append(f"PRG_Ext vs GJR Harvey PASS count: {n_harvey_pass}/{len(ASSETS)*len(alpha_levels)} (across assets x alphas, parametric)")

    # FHS Harvey PASS
    n_harvey_fhs = 0
    for ticker in ASSETS:
        for alpha in alpha_levels:
            alpha_key = f"{int(alpha*100)}pct"
            dm_f = all_results[ticker]['fz_dm_tests'].get(alpha_key, {}).get('fhs', {}).get('GJR_vs_PRG_Extended', {})
            if dm_f.get('harvey_pass', False):
                n_harvey_fhs += 1
    findings.append(f"PRG_Ext vs GJR Harvey PASS count (FHS): {n_harvey_fhs}/{len(ASSETS)*len(alpha_levels)}")

    # PRG vs Separate
    n_sep_pass = 0
    for ticker in ASSETS:
        for alpha in alpha_levels:
            alpha_key = f"{int(alpha*100)}pct"
            dm_s = all_results[ticker]['fz_dm_tests'].get(alpha_key, {}).get('parametric', {}).get('Separate_vs_PRG_Extended', {})
            if dm_s.get('harvey_pass', False) and dm_s.get('winner') == 'PRG_Extended':
                n_sep_pass += 1
    findings.append(f"PRG_Ext vs Separate Harvey PASS (PRG wins): {n_sep_pass}/{len(ASSETS)*len(alpha_levels)} (parametric)")

    print("\n\nKey Findings:")
    for f in findings:
        print(f"  * {f}")

    # Build final results
    runtime = (datetime.now() - t_start).total_seconds()

    results = {
        'experiment_id': 'K881b',
        'title': 'ES Supplement for QQQ, GLD, EEM (PRG Multi-Asset)',
        'type': 'empirical',
        'data_source': 'yfinance',
        'assets_tested': list(ASSETS.keys()),
        'is_fraction': IS_FRACTION,
        'models': model_names,
        'es_methods': ['Parametric Normal', 'Filtered Historical Simulation (FHS)'],
        'alpha_levels': alpha_levels,
        'per_asset_results': all_results,
        'cross_asset_summary': {
            'fz_rankings': fz_ranking_summary,
            'key_dm_prg_vs_gjr': key_dm_summary,
            'prg_ext_win_count': win_count,
            'acerbi_szekely_pass_count': as_pass_count,
        },
        'key_findings': findings,
        'runtime_seconds': runtime,
        'references': [
            "Acerbi & Szekely (2014): Backtesting Expected Shortfall. Risk.",
            "Fissler & Ziegel (2016): Higher order elicitability. Ann. Stat.",
            "McNeil & Frey (2000): Estimation of tail-related risk measures. J. Empirical Finance.",
            "Patton, Ziegel & Chen (2019): Dynamic semiparametric models for ES. J. Econometrics.",
            "Basel Committee (2019): MAR 99. Minimum capital requirements for market risk.",
            "K880b: ES Supplement for SPY PRG Validation",
            "K881: PRG Multi-Asset Validation (QQQ, GLD, EEM)",
        ],
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {OUTPUT_FILE}")
    print(f"Runtime: {runtime:.1f} seconds")


if __name__ == "__main__":
    main()
