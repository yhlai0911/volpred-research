#!/usr/bin/env python3
"""
K995: VaR/ES Backtesting for MF-GJR-X(A4f) vs GJR-GARCH
=========================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K988 found A4f (τ=θ₀+θ₁VIX², free ω, GJR g_t) significantly beats GJR
  on QLIKE (DM t=+4.48). But better prediction ≠ better risk management
  (K770b lesson). This experiment evaluates VaR/ES performance.

Models:
  1. GJR-GARCH(1,1) - Normal innovations
  2. GJR-t: GJR-GARCH(1,1) - Student-t innovations (fat tails)
  3. A4f: MF-GJR-X (VIX², free omega) - Normal innovations
  4. A4f-t: A4f with Student-t VaR/ES (df estimated from training residuals)

VaR levels: 1%, 2.5%, 5%
ES levels: 2.5%

Backtesting methods:
  - Kupiec (1995) Unconditional Coverage (UC)
  - Christoffersen (1998) Conditional Coverage (CC)
  - Engle & Manganelli (2004) Dynamic Quantile (DQ)
  - Acerbi & Szekely (2014) ES test (Z1, Z2)

Data: SPY 2005-2026, OOS 2019-2026, window=2000, refit/63d (same as K988)

References:
  - Kupiec (1995). J Derivatives 3(2):73-84.
  - Christoffersen (1998). IER 39(4):841-862.
  - Engle & Manganelli (2004). JBES 22(4):367-381.
  - Acerbi & Szekely (2014). Risk 27(11):76-81.
  - K988: MF-GJR-X specification comparison.

Author: VolPred Research System
Date: 2026-04-08
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K995"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k995_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-08'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
VAR_LEVELS = [0.01, 0.025, 0.05]
ES_LEVELS = [0.025]

print("=" * 70, flush=True)
print(f"{EXPERIMENT_ID}: VaR/ES Backtesting — A4f vs GJR vs GJR-t", flush=True)
print("=" * 70, flush=True)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...", flush=True)
import yfinance as yf

raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_close})
df = df.dropna()

oos_mask = np.array(df.index >= OOS_START)
n_total = len(df)
n_oos = oos_mask.sum()
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}", flush=True)
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}", flush=True)

ret = df['log_ret'].values
vix_vals = df['VIX'].values
r2 = ret ** 2

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...", flush=True)
oos_ret = ret[oos_mask]
print(f"  OOS mean return: {np.mean(oos_ret)*252:.4f}", flush=True)
print(f"  OOS std: {np.std(oos_ret)*np.sqrt(252):.4f}", flush=True)
print(f"  OOS skewness: {stats.skew(oos_ret):.3f}", flush=True)
print(f"  OOS kurtosis: {stats.kurtosis(oos_ret):.3f}", flush=True)


# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...", flush=True)


@njit(cache=True)
def gjr_loglik_normal(params, returns):
    """GJR-GARCH(1,1) Normal log-likelihood."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll


def gjr_loglik_t(params, returns):
    """GJR-GARCH(1,1) Student-t log-likelihood (pure Python, no numba due to lgamma)."""
    from scipy.special import gammaln
    omega, alpha, gamma_p, beta, df = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])

    half_dfp1 = (df + 1.0) / 2.0
    half_df = df / 2.0
    log_const = (gammaln(half_dfp1) - gammaln(half_df)
                 - 0.5 * np.log(np.pi * (df - 2.0)))

    for t in range(1, n):
        asym = gamma_p * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10

    # Vectorized log-likelihood
    z2 = returns**2 / h
    ll = np.sum(log_const - half_dfp1 * np.log(1.0 + z2 / (df - 2.0)) - 0.5 * np.log(h))

    return -ll


def fit_gjr_normal(returns):
    """Fit GJR-GARCH(1,1) Normal."""
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik_normal, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def fit_gjr_t(returns):
    """Fit GJR-GARCH(1,1) Student-t."""
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90, 8.0],
        [var0 * 0.02, 0.03, 0.08, 0.88, 5.0],
        [var0 * 0.10, 0.08, 0.10, 0.80, 12.0],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999), (3.01, 50.0)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik_t, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def gjr_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR forecast."""
    omega, alpha, gamma, beta = params[:4]
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


def fit_a4f(returns, vix_v):
    """Fit A4f: τ = max(θ₀ + θ₁VIX²_{t-1}, eps), free omega, GJR g_t.
    Normal innovations."""
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_v[0]
    vix_lag[1:] = vix_v[:-1]

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)

        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        eg = omega_g / (1.0 - persist)

        g = np.empty(n)
        g[0] = eg
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        ll = 0.0
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag**2) + 1e-8
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def estimate_df_from_residuals(standardized_residuals):
    """Estimate Student-t df from standardized residuals using MLE.
    The residuals z should have mean~0, var~1."""
    z = standardized_residuals
    # MLE for df: maximize sum of log(t_pdf(z_i; df)) with scale=sqrt((df-2)/df)
    def neg_ll(df_val):
        df = float(df_val)
        if df <= 2.01:
            return 1e10
        scale = np.sqrt((df - 2.0) / df)
        return -np.sum(stats.t.logpdf(z / scale, df) - np.log(scale))

    best = optimize.minimize_scalar(neg_ll, bounds=(3.0, 50.0), method='bounded')
    return best.x


# ============================================================
# SECTION 4: VaR/ES FUNCTIONS
# ============================================================

def var_normal(sigma, alpha):
    """VaR_α = σ × z_α (left tail)."""
    return sigma * stats.norm.ppf(alpha)


def es_normal(sigma, alpha):
    """ES_α = σ × (-φ(z_α)/α)."""
    z_alpha = stats.norm.ppf(alpha)
    return sigma * (-stats.norm.pdf(z_alpha) / alpha)


def var_student_t(sigma, alpha, df):
    """VaR with Student-t: z_α = t_inv(α,df) × sqrt((df-2)/df)."""
    t_q = stats.t.ppf(alpha, df)
    scale = np.sqrt((df - 2.0) / df)
    return sigma * t_q * scale


def es_student_t(sigma, alpha, df):
    """ES with Student-t."""
    t_q = stats.t.ppf(alpha, df)
    t_pdf = stats.t.pdf(t_q, df)
    scale = np.sqrt((df - 2.0) / df)
    return sigma * (-(t_pdf * (df + t_q**2) / ((df - 1.0) * alpha)) * scale)


# ============================================================
# SECTION 5: BACKTESTING FUNCTIONS
# ============================================================

def kupiec_uc_test(violations, n, alpha):
    """Kupiec (1995) UC LR test."""
    n_viol = np.sum(violations)
    pi_hat = n_viol / n if n > 0 else 0.0
    if n_viol == 0 or n_viol == n:
        return {'stat': 0.0, 'p_value': 1.0 if n_viol == 0 else 0.0,
                'violation_rate': float(pi_hat), 'n_violations': int(n_viol), 'n': n}

    log_l_null = n_viol * np.log(alpha) + (n - n_viol) * np.log(1 - alpha)
    log_l_alt = n_viol * np.log(pi_hat) + (n - n_viol) * np.log(1 - pi_hat)
    lr = -2.0 * (log_l_null - log_l_alt)
    p_value = 1.0 - stats.chi2.cdf(max(lr, 0), 1)
    return {'stat': float(lr), 'p_value': float(p_value),
            'violation_rate': float(pi_hat), 'n_violations': int(n_viol), 'n': n}


def christoffersen_cc_test(violations, n, alpha):
    """Christoffersen (1998) CC test."""
    uc = kupiec_uc_test(violations, n, alpha)
    n00, n01, n10, n11 = 0, 0, 0, 0
    for t in range(1, len(violations)):
        v0, v1 = violations[t-1], violations[t]
        if v0 == 0 and v1 == 0: n00 += 1
        elif v0 == 0 and v1 == 1: n01 += 1
        elif v0 == 1 and v1 == 0: n10 += 1
        else: n11 += 1

    pi01 = n01 / max(n00 + n01, 1)
    pi11 = n11 / max(n10 + n11, 1)
    pi_hat = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)

    eps = 1e-16
    if (n00 + n01) > 0 and (n10 + n11) > 0 and 0 < pi_hat < 1:
        log_l_ind = 0.0
        if n00 > 0: log_l_ind += n00 * np.log(max(1 - pi01, eps))
        if n01 > 0: log_l_ind += n01 * np.log(max(pi01, eps))
        if n10 > 0: log_l_ind += n10 * np.log(max(1 - pi11, eps))
        if n11 > 0: log_l_ind += n11 * np.log(max(pi11, eps))
        log_l_null_ind = (n00 + n10) * np.log(max(1 - pi_hat, eps)) + (n01 + n11) * np.log(max(pi_hat, eps))
        lr_ind = max(-2.0 * (log_l_null_ind - log_l_ind), 0.0)
    else:
        lr_ind = 0.0

    lr_cc = uc['stat'] + lr_ind
    p_cc = 1.0 - stats.chi2.cdf(lr_cc, 2)
    p_ind = 1.0 - stats.chi2.cdf(lr_ind, 1)
    return {'stat_cc': float(lr_cc), 'p_cc': float(p_cc),
            'stat_ind': float(lr_ind), 'p_ind': float(p_ind),
            'stat_uc': uc['stat'], 'p_uc': uc['p_value'],
            'violation_rate': uc['violation_rate'],
            'n_violations': uc['n_violations'], 'n': n}


def dq_test(violations, var_series, returns, alpha, n_lags=4):
    """Engle & Manganelli (2004) DQ test."""
    hits = violations.astype(float) - alpha
    n = len(hits)
    if n <= n_lags + 2:
        return {'stat': float('nan'), 'p_value': float('nan')}
    max_lag = min(n_lags, n - 1)
    X_list = [np.ones(n - max_lag)]
    for lag in range(1, max_lag + 1):
        X_list.append(hits[max_lag - lag:n - lag])
    X_list.append(var_series[max_lag:])
    X = np.column_stack(X_list)
    y = hits[max_lag:]
    try:
        XtX_inv = np.linalg.inv(X.T @ X)
        beta_hat = XtX_inv @ X.T @ y
        dq_stat = float((beta_hat @ X.T @ X @ beta_hat) / (alpha * (1 - alpha)))
        dq_stat = max(dq_stat, 0.0)
        p_value = 1.0 - stats.chi2.cdf(dq_stat, X.shape[1])
    except np.linalg.LinAlgError:
        dq_stat, p_value = np.nan, np.nan
    return {'stat': float(dq_stat), 'p_value': float(p_value)}


def acerbi_szekely_z1(returns, es_series, var_series, alpha):
    """Acerbi & Szekely (2014) Z1 test."""
    violations = returns < var_series
    n_viol = np.sum(violations)
    if n_viol == 0:
        return {'stat': 0.0, 'p_value': 1.0, 'n_violations': 0}
    z1 = np.mean(returns[violations] / es_series[violations]) + 1.0
    T = len(returns)
    n_boot = 1000
    z1_boot = np.empty(n_boot)
    rng = np.random.default_rng(42)
    for b in range(n_boot):
        idx = rng.integers(0, T, size=T)
        br, bv, be = returns[idx], var_series[idx], es_series[idx]
        bviol = br < bv
        z1_boot[b] = (np.mean(br[bviol] / be[bviol]) + 1.0) if np.sum(bviol) > 0 else 0.0
    p_value = np.mean(z1_boot <= z1)
    return {'stat': float(z1), 'p_value': float(p_value), 'n_violations': int(n_viol)}


def acerbi_szekely_z2(returns, es_series, var_series, alpha):
    """Acerbi & Szekely (2014) Z2 test."""
    T = len(returns)
    violations = returns < var_series
    n_viol = np.sum(violations)
    if n_viol == 0:
        return {'stat': 0.0, 'p_value': 1.0, 'n_violations': 0}
    z2 = (1.0 / (T * alpha)) * np.sum(returns[violations] / es_series[violations]) + 1.0
    n_boot = 1000
    z2_boot = np.empty(n_boot)
    rng = np.random.default_rng(43)
    for b in range(n_boot):
        idx = rng.integers(0, T, size=T)
        br, bv, be = returns[idx], var_series[idx], es_series[idx]
        bviol = br < bv
        z2_boot[b] = ((1.0/(T*alpha)) * np.sum(br[bviol]/be[bviol]) + 1.0) if np.sum(bviol) > 0 else 0.0
    p_value = np.mean(z2_boot <= z2)
    return {'stat': float(z2), 'p_value': float(p_value), 'n_violations': int(n_viol)}


# ============================================================
# SECTION 6: OOS FORECASTING
# ============================================================
print("\n[6] Out-of-sample forecasting...", flush=True)

oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  OOS observations: {n_oos_actual}", flush=True)

# 3 variance models: GJR_Normal, GJR_t, A4f
# Then we apply both Normal and t-distribution VaR/ES to A4f
sigma_forecasts = {
    'GJR': np.full(n_oos_actual, np.nan),
    'GJR_t': np.full(n_oos_actual, np.nan),
    'A4f': np.full(n_oos_actual, np.nan),
}

# States
states = {
    'GJR': {'h': None, 'params': None},
    'GJR_t': {'h': None, 'params': None, 'df': None},
    'A4f': {'g': None, 'params': None, 'tau_prev': None, 'df_residual': None},
}

df_history = {'GJR_t': [], 'A4f_residual': []}
refit_count = 0

print(f"  Refit every {REFIT_EVERY} days", flush=True)

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 250 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos_actual} ({elapsed:.0f}s)", flush=True)

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix_vals[train_start:abs_idx]
        n_train = len(train_ret)

        # --- GJR Normal ---
        gjr_params = fit_gjr_normal(train_ret)
        if gjr_params is not None:
            states['GJR']['params'] = gjr_params
            h = np.var(train_ret)
            for i in range(1, n_train):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            states['GJR']['h'] = h

        # --- GJR-t ---
        gjr_t_params = fit_gjr_t(train_ret)
        if gjr_t_params is not None:
            states['GJR_t']['params'] = gjr_t_params
            states['GJR_t']['df'] = gjr_t_params[4]
            df_history['GJR_t'].append(float(gjr_t_params[4]))
            h = np.var(train_ret)
            for i in range(1, n_train):
                h = gjr_forecast_1step(gjr_t_params, h, train_ret[i-1])
            states['GJR_t']['h'] = h

        # --- A4f ---
        a4f_params = fit_a4f(train_ret, train_vix)
        if a4f_params is not None:
            states['A4f']['params'] = a4f_params
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params

            vix_lag_tr = np.empty(n_train)
            vix_lag_tr[0] = train_vix[0]
            vix_lag_tr[1:] = train_vix[:-1]
            tau_train = np.maximum(theta0 + theta1 * vix_lag_tr**2, 1e-16)

            persist = alpha_p + gamma_p / 2.0 + beta_p
            eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
            g = eg
            # Also collect standardized residuals for df estimation
            std_resid = np.empty(n_train)
            for i in range(n_train):
                sigma2_i = tau_train[i] * g
                std_resid[i] = train_ret[i] / np.sqrt(max(sigma2_i, 1e-16))
                if i < n_train - 1:
                    u_prev = train_ret[i] / np.sqrt(max(tau_train[i+1] if i+1 < n_train else tau_train[i], 1e-16))
                    asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                    g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                    g = max(g, 1e-10)

            states['A4f']['g'] = g
            states['A4f']['tau_prev'] = tau_train[-1]

            # Estimate df from standardized residuals
            df_est = estimate_df_from_residuals(std_resid[10:])  # skip first few
            states['A4f']['df_residual'] = df_est
            df_history['A4f_residual'].append(float(df_est))

    # --- Generate forecasts ---
    r_prev = ret[abs_idx - 1]

    # GJR Normal
    p = states['GJR']['params']
    if p is not None:
        h_prev = states['GJR']['h']
        h_new = gjr_forecast_1step(p, h_prev, r_prev)
        sigma_forecasts['GJR'][t_idx] = np.sqrt(h_new)
        states['GJR']['h'] = h_new

    # GJR-t
    p = states['GJR_t']['params']
    if p is not None:
        h_prev = states['GJR_t']['h']
        h_new = gjr_forecast_1step(p, h_prev, r_prev)
        sigma_forecasts['GJR_t'][t_idx] = np.sqrt(h_new)
        states['GJR_t']['h'] = h_new

    # A4f
    p = states['A4f']['params']
    if p is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = p
        vix_prev = vix_vals[abs_idx - 1]
        tau_t = max(theta0 + theta1 * vix_prev**2, 1e-16)

        g_prev = states['A4f']['g']
        u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
        g_new = max(g_new, 1e-10)

        sigma2 = tau_t * g_new
        sigma_forecasts['A4f'][t_idx] = np.sqrt(sigma2)
        states['A4f']['g'] = g_new
        states['A4f']['tau_prev'] = tau_t

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s, {refit_count} refits", flush=True)

for name in ['GJR_t']:
    if df_history[name]:
        print(f"  {name} df: mean={np.mean(df_history[name]):.2f}, "
              f"range=[{np.min(df_history[name]):.2f}, {np.max(df_history[name]):.2f}]", flush=True)
if df_history['A4f_residual']:
    print(f"  A4f residual df: mean={np.mean(df_history['A4f_residual']):.2f}, "
          f"range=[{np.min(df_history['A4f_residual']):.2f}, {np.max(df_history['A4f_residual']):.2f}]", flush=True)


# ============================================================
# SECTION 7: VaR/ES COMPUTATION
# ============================================================
print("\n[7] Computing VaR and ES...", flush=True)

oos_returns = ret[oos_mask]

# 4 "model-distribution" combos:
# GJR_Normal, GJR_t, A4f_Normal, A4f_t
model_dist_combos = [
    ('GJR_Normal', 'GJR', 'normal', None),
    ('GJR_t', 'GJR_t', 'student_t', lambda: states['GJR_t']['df']),
    ('A4f_Normal', 'A4f', 'normal', None),
    ('A4f_t', 'A4f', 'student_t', lambda: states['A4f']['df_residual']),
]

var_results = {}
es_results = {}

for combo_name, sigma_key, dist, df_func in model_dist_combos:
    sigma = sigma_forecasts[sigma_key]
    valid = ~np.isnan(sigma)
    n_valid = np.sum(valid)
    print(f"  {combo_name}: {n_valid}/{n_oos_actual} valid", flush=True)

    df_val = df_func() if df_func else None

    for alpha in VAR_LEVELS:
        key = f"{combo_name}_VaR_{alpha}"
        var_s = np.full(n_oos_actual, np.nan)
        for t in range(n_oos_actual):
            if np.isnan(sigma[t]):
                continue
            if dist == 'student_t' and df_val is not None:
                var_s[t] = var_student_t(sigma[t], alpha, df_val)
            else:
                var_s[t] = var_normal(sigma[t], alpha)
        var_results[key] = var_s

    for alpha in ES_LEVELS:
        key = f"{combo_name}_ES_{alpha}"
        es_s = np.full(n_oos_actual, np.nan)
        for t in range(n_oos_actual):
            if np.isnan(sigma[t]):
                continue
            if dist == 'student_t' and df_val is not None:
                es_s[t] = es_student_t(sigma[t], alpha, df_val)
            else:
                es_s[t] = es_normal(sigma[t], alpha)
        es_results[key] = es_s


# ============================================================
# SECTION 8: BACKTESTING
# ============================================================
print("\n[8] Running backtests...", flush=True)

all_results = {}

for combo_name, sigma_key, dist, df_func in model_dist_combos:
    all_results[combo_name] = {}
    sigma = sigma_forecasts[sigma_key]
    valid = ~np.isnan(sigma)

    for alpha in VAR_LEVELS:
        var_key = f"{combo_name}_VaR_{alpha}"
        var_s = var_results[var_key]
        mask = valid & ~np.isnan(var_s)
        ret_v = oos_returns[mask]
        var_v = var_s[mask]
        n_v = len(ret_v)
        violations = (ret_v < var_v).astype(int)

        uc = kupiec_uc_test(violations, n_v, alpha)
        cc = christoffersen_cc_test(violations, n_v, alpha)
        dq = dq_test(violations, var_v, ret_v, alpha)

        rk = f"VaR_{alpha}"
        all_results[combo_name][rk] = {
            'alpha': alpha, 'n': n_v,
            'violation_rate': uc['violation_rate'],
            'n_violations': uc['n_violations'],
            'expected_violations': round(alpha * n_v, 1),
            'UC': {'stat': uc['stat'], 'p_value': uc['p_value']},
            'CC': {'stat': cc['stat_cc'], 'p_value': cc['p_cc'],
                   'IND_stat': cc['stat_ind'], 'IND_p_value': cc['p_ind']},
            'DQ': {'stat': dq['stat'], 'p_value': dq['p_value']},
        }
        print(f"  {combo_name} VaR({alpha}): viol={uc['n_violations']}/{n_v} "
              f"({uc['violation_rate']:.4f}), UC p={uc['p_value']:.3f}, "
              f"CC p={cc['p_cc']:.3f}, DQ p={dq['p_value']:.3f}", flush=True)

    for alpha in ES_LEVELS:
        var_key = f"{combo_name}_VaR_{alpha}"
        es_key = f"{combo_name}_ES_{alpha}"
        var_s = var_results[var_key]
        es_s = es_results[es_key]
        mask = valid & ~np.isnan(var_s) & ~np.isnan(es_s)
        ret_v = oos_returns[mask]
        var_v = var_s[mask]
        es_v = es_s[mask]

        z1 = acerbi_szekely_z1(ret_v, es_v, var_v, alpha)
        z2 = acerbi_szekely_z2(ret_v, es_v, var_v, alpha)

        rk = f"ES_{alpha}"
        all_results[combo_name][rk] = {
            'alpha': alpha,
            'Z1': {'stat': z1['stat'], 'p_value': z1['p_value'], 'n_violations': z1['n_violations']},
            'Z2': {'stat': z2['stat'], 'p_value': z2['p_value'], 'n_violations': z2['n_violations']},
        }
        print(f"  {combo_name} ES({alpha}): Z1={z1['stat']:.4f} (p={z1['p_value']:.3f}), "
              f"Z2={z2['stat']:.4f} (p={z2['p_value']:.3f})", flush=True)


# ============================================================
# SECTION 9: SUMMARY
# ============================================================
print("\n" + "=" * 80, flush=True)
print("SUMMARY: VaR Backtesting Results", flush=True)
print("=" * 80, flush=True)

combo_names = [c[0] for c in model_dist_combos]
header = f"{'Model':<16} {'Alpha':<8} {'Viol%':<8} {'UC p':<8} {'CC p':<8} {'DQ p':<8} {'Pass?':<6}"
print(header, flush=True)
print("-" * 80, flush=True)

for cn in combo_names:
    for alpha in VAR_LEVELS:
        r = all_results[cn][f"VaR_{alpha}"]
        passed = (r['UC']['p_value'] > 0.05 and r['CC']['p_value'] > 0.05 and r['DQ']['p_value'] > 0.05)
        print(f"{cn:<16} {alpha:<8} {r['violation_rate']:<8.4f} {r['UC']['p_value']:<8.3f} "
              f"{r['CC']['p_value']:<8.3f} {r['DQ']['p_value']:<8.3f} {'PASS' if passed else 'FAIL':<6}", flush=True)

print("\n" + "=" * 80, flush=True)
print("SUMMARY: ES Backtesting Results (α=2.5%)", flush=True)
print("=" * 80, flush=True)
header_es = f"{'Model':<16} {'Z1 stat':<10} {'Z1 p':<8} {'Z2 stat':<10} {'Z2 p':<8} {'Pass?':<6}"
print(header_es, flush=True)
print("-" * 80, flush=True)

for cn in combo_names:
    rk = f"ES_{ES_LEVELS[0]}"
    if rk in all_results[cn]:
        r = all_results[cn][rk]
        passed = r['Z1']['p_value'] > 0.05 and r['Z2']['p_value'] > 0.05
        print(f"{cn:<16} {r['Z1']['stat']:<10.4f} {r['Z1']['p_value']:<8.3f} "
              f"{r['Z2']['stat']:<10.4f} {r['Z2']['p_value']:<8.3f} {'PASS' if passed else 'FAIL':<6}", flush=True)

# ============================================================
# SECTION 10: SCORECARD
# ============================================================
print("\n[10] Model scorecard...", flush=True)
for cn in combo_names:
    var_pass = sum(1 for a in VAR_LEVELS
                   if all_results[cn][f"VaR_{a}"]['UC']['p_value'] > 0.05
                   and all_results[cn][f"VaR_{a}"]['CC']['p_value'] > 0.05
                   and all_results[cn][f"VaR_{a}"]['DQ']['p_value'] > 0.05)
    es_pass = sum(1 for a in ES_LEVELS
                  if f"ES_{a}" in all_results[cn]
                  and all_results[cn][f"ES_{a}"]['Z1']['p_value'] > 0.05
                  and all_results[cn][f"ES_{a}"]['Z2']['p_value'] > 0.05)
    print(f"  {cn}: VaR {var_pass}/{len(VAR_LEVELS)} PASS, ES {es_pass}/{len(ES_LEVELS)} PASS", flush=True)


# ============================================================
# SECTION 11: SAVE
# ============================================================
print("\n[11] Saving results...", flush=True)

def ser(obj):
    if isinstance(obj, (np.integer,)): return int(obj)
    elif isinstance(obj, (np.floating,)): return float(obj)
    elif isinstance(obj, np.ndarray): return obj.tolist()
    elif isinstance(obj, dict): return {k: ser(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)): return [ser(x) for x in obj]
    return obj

elapsed_total = time.time() - START_TIME

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'VaR/ES Backtesting: MF-GJR-X(A4f) vs GJR-GARCH',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {
        'asset': 'SPY', 'source': 'yfinance',
        'period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        'n_total': n_total, 'n_oos': n_oos_actual,
        'oos_start': OOS_START, 'window': WINDOW,
        'refit_every': REFIT_EVERY, 'n_refits': refit_count,
    },
    'models': combo_names,
    'var_levels': VAR_LEVELS,
    'es_levels': ES_LEVELS,
    'df_estimates': ser(df_history),
    'backtest_results': ser(all_results),
    'elapsed_seconds': round(elapsed_total, 1),
    'references': [
        'Kupiec (1995) J Derivatives 3(2):73-84',
        'Christoffersen (1998) IER 39(4):841-862',
        'Engle & Manganelli (2004) JBES 22(4):367-381',
        'Acerbi & Szekely (2014) Risk 27(11):76-81',
        'K988: MF-GJR-X specification comparison (DM t=+4.48)',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n  Results saved to {RESULTS_PATH}", flush=True)
print(f"  Total elapsed: {elapsed_total:.0f}s", flush=True)
print("\n" + "=" * 70, flush=True)
print(f"{EXPERIMENT_ID} COMPLETE", flush=True)
print("=" * 70, flush=True)
