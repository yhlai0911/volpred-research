"""
K1026: Proxy-Reliance Controlled Conformal VaR vs Parametric VaR
================================================================
Inspired by arXiv:2603.22569 (conformal prediction for time series VaR)

Data: SPY 2005-2026 (yfinance)
OOS: 2013-01-02 to end (~13 years)
Window: 2000 (GARCH/A4f), 252 (conformal calibration)
Refit: every 63 days

Models / VaR Methods (5):
  M1: GJR-GARCH + Normal VaR      (baseline, known to fail at 1%)
  M2: GJR-GARCH + Student-t(df=8) (K802 recommended)
  M3: A4f + Student-t(df=8)       (K1021 best)
  M4: Conformal-GJR VaR           (model-agnostic post-calibration on GJR residuals)
  M5: Conformal-A4f VaR           (model-agnostic post-calibration on A4f residuals)

Evaluation:
  VaR levels: 1%, 2.5%, 5%
  Tests: Kupiec (UC), Christoffersen (CC), DQ, Basel traffic light
  ES backtest: Acerbi-Szekely Z1/Z2 (at 2.5%)
  Conditional calibration: VIX high vs low violation rates
  Sharpness: average |VaR| (narrower = better, given coverage OK)

Research Questions:
  1. Can conformal prediction produce valid VaR without distributional assumptions?
  2. How does conformal compare to parametric (Student-t) on coverage and sharpness?
  3. Does the choice of base model (GJR vs A4f) matter for conformal VaR?

References:
  - arXiv:2603.22569: Proxy-reliance controlled conformal VaR
  - Kupiec (1995): Unconditional coverage LR test
  - Christoffersen (1998): Conditional coverage test
  - Engle & Manganelli (2004): DQ test
  - Acerbi & Szekely (2014): ES backtesting
  - K800/K800v2: Conformal heuristic artifact warning
  - K802: GJR + Student-t/Skewed-t = correct VaR solution
  - K1021: A4f + Student-t(df=8) 6/6 PASS at 2.5%
  - Patton (2011): QLIKE proxy-robust ranking

Seed: 42
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
import time
from datetime import datetime
from scipy.optimize import minimize
from scipy.stats import t as t_dist, chi2, norm
import math
import yfinance as yf
from numba import njit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. Data
# ============================================================
def load_data():
    """Load SPY + VIX data."""
    print("\nLoading SPY + VIX...")
    spy = yf.download('SPY', start='2004-01-01', end='2026-12-31', progress=False)
    vix = yf.download('^VIX', start='2004-01-01', end='2026-12-31', progress=False)

    for d in [spy, vix]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    df = pd.DataFrame(index=spy.index)
    df['close'] = spy['Close']
    df['vix'] = vix['Close'].reindex(spy.index, method='ffill')
    df['ret'] = np.log(df['close'] / df['close'].shift(1))
    df = df.dropna()
    df['ret'] = df['ret'].clip(-0.20, 0.20)
    df['r2'] = df['ret'] ** 2
    df['vix2'] = (df['vix'] / 100) ** 2

    print(f"  SPY data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")
    return df


# ============================================================
# 2. Numba-accelerated GARCH recursions
# ============================================================
@njit
def gjr_recursion(omega, alpha, gamma, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = omega / (1.0 - alpha - 0.5 * gamma - beta)
    if h[0] < 1e-16 or not np.isfinite(h[0]):
        h[0] = np.var(returns[:min(100, T)])
    for t in range(1, T):
        r2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * r2 + gamma * r2 * ind + beta * h[t-1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h

@njit
def gjr_nll_normal(omega, alpha, gamma, beta, returns):
    h = gjr_recursion(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll

@njit
def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)
    tau[0] = theta0 + theta1 * vix2[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]
    for t in range(1, T):
        tau[t] = theta0 + theta1 * vix2[t-1]
        if tau[t] < 1e-16:
            tau[t] = 1e-16
        u_prev = returns[t-1] / np.sqrt(tau[t])
        u2 = u_prev ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        g[t] = omega + alpha * u2 + gamma * u2 * ind + beta * g[t-1]
        if g[t] < 1e-16:
            g[t] = 1e-16
        h[t] = tau[t] * g[t]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h, tau, g

@njit
def a4f_nll_normal(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll

@njit
def t_logpdf_sum(returns, h, df):
    """Sum of Student-t logpdf with scale = sigma * sqrt((df-2)/df)."""
    T = len(returns)
    scale_factor = np.sqrt((df - 2.0) / df)
    c = math.lgamma((df + 1.0) / 2.0) - math.lgamma(df / 2.0) - 0.5 * np.log(np.pi * df)
    ll = 0.0
    for t in range(T):
        sigma = np.sqrt(h[t])
        s = sigma * scale_factor
        z = returns[t] / s
        ll += c - np.log(s) - (df + 1.0) / 2.0 * np.log(1.0 + z * z / df)
    return ll


# ============================================================
# 3. Model fitting functions
# ============================================================
def fit_gjr(returns):
    """Fit GJR-GARCH(1,1) with Normal innovations."""
    bounds = [(1e-8, 0.01), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[1] + 0.5*p[2] + p[3] >= 1.0:
            return 1e10
        try:
            v = gjr_nll_normal(p[0], p[1], p[2], p[3], returns)
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for omega_init in [1e-6, 5e-6, 1e-5]:
        for alpha_init in [0.03, 0.06]:
            x0 = [omega_init, alpha_init, 0.08, 0.88]
            try:
                res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                               options={'maxiter': 300})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except:
                continue
    if best_res is None:
        x0 = [5e-6, 0.04, 0.08, 0.88]
        best_res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds)
    h = gjr_recursion(*best_res.x, returns)
    return {'params': best_res.x, 'h': h, 'converged': best_res.success, 'nll': best_res.fun}


def fit_a4f(returns, vix2):
    """Fit A4f with Normal innovations."""
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            v = a4f_nll_normal(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for theta1_init in [0.3, 0.8, 2.0]:
        for omega_init in [0.02, 0.08]:
            x0 = [1e-5, theta1_init, omega_init, 0.04, 0.06, 0.90]
            try:
                res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                               options={'maxiter': 300})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except:
                continue
    if best_res is None:
        x0 = [1e-5, 0.5, 0.05, 0.04, 0.06, 0.90]
        best_res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds)
    h, tau, g = a4f_recursion(best_res.x[0], best_res.x[1], best_res.x[2],
                               best_res.x[3], best_res.x[4], best_res.x[5],
                               returns, vix2)
    return {'params': best_res.x, 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success, 'nll': best_res.fun}


# ============================================================
# 4. OOS Forecasting
# ============================================================
def oos_forecast_gjr(df, oos_start_date, window=2000, refit_every=63):
    """OOS GJR-GARCH forecasting with rolling refit."""
    oos_start_idx = np.where(df.index >= oos_start_date)[0][0]
    T = len(df)
    forecasts = np.full(T, np.nan)
    returns = df['ret'].values

    last_fit = None
    last_fit_idx = -refit_every
    h_prev = np.nan

    for t in range(oos_start_idx, T):
        if t - last_fit_idx >= refit_every or last_fit is None:
            s = max(0, t - window)
            tr = returns[s:t]
            last_fit = fit_gjr(tr)
            last_fit_idx = t
            h_prev = last_fit['h'][-1]

        p = last_fit['params']
        omega, alpha, gamma, beta = p[0], p[1], p[2], p[3]
        r2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h_t = omega + alpha * r2 + gamma * r2 * ind + beta * h_prev
        h_t = max(h_t, 1e-16)
        forecasts[t] = h_t
        h_prev = h_t

    return forecasts


def oos_forecast_a4f(df, oos_start_date, window=2000, refit_every=63):
    """OOS A4f forecasting with rolling refit."""
    oos_start_idx = np.where(df.index >= oos_start_date)[0][0]
    T = len(df)
    forecasts = np.full(T, np.nan)
    returns = df['ret'].values
    vix2_vals = df['vix2'].values

    last_fit = None
    last_fit_idx = -refit_every
    g_prev = np.nan

    for t in range(oos_start_idx, T):
        if t - last_fit_idx >= refit_every or last_fit is None:
            s = max(0, t - window)
            tr = returns[s:t]
            tv = vix2_vals[s:t]
            last_fit = fit_a4f(tr, tv)
            last_fit_idx = t
            g_prev = last_fit['g'][-1]

        p = last_fit['params']
        theta0, theta1, omega, alpha, gamma, beta = p[0], p[1], p[2], p[3], p[4], p[5]
        tau_t = max(theta0 + theta1 * vix2_vals[t-1], 1e-16)
        u_prev = returns[t-1] / np.sqrt(tau_t)
        u2 = u_prev ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        g_t = omega + alpha * u2 + gamma * u2 * ind + beta * g_prev
        g_t = max(g_t, 1e-16)
        forecasts[t] = tau_t * g_t
        g_prev = g_t

    return forecasts


# ============================================================
# 5. VaR Computation Methods
# ============================================================
def compute_var_es_normal(sigma, alpha):
    """VaR and ES from Normal distribution."""
    q = norm.ppf(alpha)
    var_v = sigma * q  # negative value (left tail)
    es_v = sigma * (-norm.pdf(q) / alpha)  # positive magnitude, but we want negative
    es_v = -es_v  # Make negative (loss direction)
    return var_v, es_v


def compute_var_es_t(sigma, df_val, alpha):
    """VaR and ES from Student-t distribution with scale correction."""
    sf = np.sqrt((df_val - 2.0) / df_val)
    q = t_dist.ppf(alpha, df_val)
    var_v = sigma * q * sf
    pdf_q = t_dist.pdf(q, df_val)
    es_v = sigma * sf * (-pdf_q / alpha) * ((df_val + q**2) / (df_val - 1))
    es_v = -es_v  # Make negative (loss direction)
    return var_v, es_v


def compute_conformal_var_es(sigma_arr, returns_arr, alpha, cal_window=252):
    """
    Conformal VaR: use rolling quantile of standardized residuals.

    For each day t:
      1. Compute standardized residuals e_s = r_s / sigma_s for s in [t-cal_window, t-1]
      2. Take the alpha-quantile of these residuals as the dynamic multiplier
      3. VaR_t = sigma_t * Q_alpha(e_{t-cal_window:t-1})
      4. ES_t = sigma_t * mean(e_s | e_s <= Q_alpha) -- empirical tail mean

    This is model-agnostic: any sigma forecast can be used.
    The key insight: instead of assuming a distribution for innovations,
    we let the empirical residual distribution speak for itself.
    """
    T = len(sigma_arr)
    var_v = np.full(T, np.nan)
    es_v = np.full(T, np.nan)

    for t in range(cal_window + 1, T):
        s_t = sigma_arr[t]
        if np.isnan(s_t) or s_t <= 0:
            continue

        # Standardized residuals from calibration window (all using past data only)
        start = t - cal_window
        end = t  # exclusive — uses [start, t-1]
        sig_window = sigma_arr[start:end]
        ret_window = returns_arr[start:end]

        # Filter valid
        valid = ~np.isnan(sig_window) & (sig_window > 0) & ~np.isnan(ret_window)
        if np.sum(valid) < 50:
            continue

        e = ret_window[valid] / sig_window[valid]

        # Conformal VaR: empirical quantile of standardized residuals
        q_alpha = np.quantile(e, alpha)
        var_v[t] = s_t * q_alpha

        # Conformal ES: empirical tail mean
        tail = e[e <= q_alpha]
        if len(tail) > 0:
            es_v[t] = s_t * np.mean(tail)
        else:
            es_v[t] = var_v[t] * 1.5  # fallback

    return var_v, es_v


# ============================================================
# 6. Evaluation Functions
# ============================================================
def kupiec_test(violations, T, alpha):
    n1 = np.sum(violations)
    n0 = T - n1
    pi_hat = n1 / T
    if pi_hat == 0 or pi_hat == 1:
        return 0, 1.0
    lr = 2 * (n1 * np.log(pi_hat / alpha) + n0 * np.log((1 - pi_hat) / (1 - alpha)))
    return lr, 1 - chi2.cdf(lr, 1)


def christoffersen_cc_test(violations):
    T = len(violations)
    n00 = n01 = n10 = n11 = 0
    for t in range(1, T):
        v0, v1 = violations[t-1], violations[t]
        if v0 == 0 and v1 == 0: n00 += 1
        elif v0 == 0 and v1 == 1: n01 += 1
        elif v0 == 1 and v1 == 0: n10 += 1
        else: n11 += 1
    if (n00+n01) == 0 or (n10+n11) == 0:
        return 0, 1.0
    pi01 = n01 / (n00+n01)
    pi11 = n11 / (n10+n11)
    pi = (n01+n11) / T
    if pi in (0,1) or pi01 in (0,1) or pi11 in (0,1):
        return 0, 1.0
    try:
        lr = 2 * (n00*np.log((1-pi01)/(1-pi)) + n01*np.log(pi01/pi)
                   + n10*np.log((1-pi11)/(1-pi)) + n11*np.log(pi11/pi))
    except:
        return 0, 1.0
    if np.isnan(lr):
        return 0, 1.0
    return lr, 1 - chi2.cdf(lr, 1)


def dq_test(violations, alpha, returns_arr, sigma_arr):
    T = len(violations)
    hit = violations.astype(float) - alpha
    X = np.column_stack([np.ones(T-1), hit[:-1], sigma_arr[1:]])
    y = hit[1:]
    try:
        XtX_inv = np.linalg.inv(X.T @ X)
        beta_coef = XtX_inv @ X.T @ y
        dq_stat = (beta_coef.T @ X.T @ X @ beta_coef) / (alpha * (1 - alpha))
        return dq_stat, 1 - chi2.cdf(dq_stat, X.shape[1])
    except:
        return 0, 1.0


def acerbi_szekely_z1(returns_arr, var_vals, es_vals, alpha):
    violations = returns_arr < var_vals
    n_viol = np.sum(violations)
    if n_viol == 0:
        return 0, 1.0
    T = len(returns_arr)
    z1 = np.sum(returns_arr[violations] / es_vals[violations]) / (T * alpha) + 1
    rng = np.random.default_rng(42)
    z1_boot = np.zeros(1000)
    for b in range(1000):
        idx = rng.choice(T, T, replace=True)
        rb = returns_arr[idx]; vb = var_vals[idx]; eb = es_vals[idx]
        viol_b = rb < vb
        if np.sum(viol_b) > 0:
            z1_boot[b] = np.sum(rb[viol_b] / eb[viol_b]) / (T * alpha) + 1
    return z1, float(np.mean(z1_boot <= z1))


def acerbi_szekely_z2(returns_arr, es_vals, alpha):
    T = len(returns_arr)
    k = int(np.floor(T * alpha))
    if k == 0:
        return 0, 1.0
    sorted_ret = np.sort(returns_arr)
    z2 = np.mean(sorted_ret[:k]) / np.mean(es_vals) - 1
    rng = np.random.default_rng(42)
    z2_boot = np.zeros(1000)
    for b in range(1000):
        idx = rng.choice(T, T, replace=True)
        rb = returns_arr[idx]; eb = es_vals[idx]
        z2_boot[b] = np.mean(np.sort(rb)[:k]) / np.mean(eb) - 1
    return z2, float(np.mean(z2_boot <= z2))


def var_es_evaluation(returns_arr, var_v, es_v, alpha, sigma_arr=None):
    """Evaluate VaR and ES given pre-computed values."""
    mask = ~np.isnan(var_v) & ~np.isnan(es_v) & ~np.isnan(returns_arr)
    ret = returns_arr[mask]
    vv = var_v[mask]
    ev = es_v[mask]
    sig = np.abs(vv) if sigma_arr is None else sigma_arr[mask]

    violations = (ret < vv).astype(int)
    T = len(ret)
    viol_rate = np.sum(violations) / T

    uc_stat, uc_p = kupiec_test(violations, T, alpha)
    cc_stat, cc_p = christoffersen_cc_test(violations)
    dq_stat, dq_p = dq_test(violations, alpha, ret, sig)

    es_z1 = es_z1_p = es_z2 = es_z2_p = None
    if abs(alpha - 0.025) < 0.001:
        es_z1, es_z1_p = acerbi_szekely_z1(ret, vv, ev, alpha)
        es_z2, es_z2_p = acerbi_szekely_z2(ret, ev, alpha)

    expected = T * alpha
    actual = np.sum(violations)
    if actual <= expected * 1.5:
        basel = "GREEN"
    elif actual <= expected * 2.0:
        basel = "YELLOW"
    else:
        basel = "RED"

    n_pass = sum([uc_p > 0.05, cc_p > 0.05, dq_p > 0.05, basel == "GREEN"])
    if abs(alpha - 0.025) < 0.001 and es_z1_p is not None:
        n_pass_total = n_pass + sum([es_z1_p > 0.05, es_z2_p > 0.05])
        scorecard = f"{n_pass_total}/6"
    else:
        scorecard = f"{n_pass}/4"

    avg_var = float(np.mean(np.abs(vv)))

    return {
        'alpha': alpha, 'T': T,
        'violations': int(actual),
        'violation_rate': round(viol_rate * 100, 3),
        'expected_rate': round(alpha * 100, 2),
        'UC_stat': round(float(uc_stat), 3), 'UC_p': round(float(uc_p), 4),
        'CC_stat': round(float(cc_stat), 3), 'CC_p': round(float(cc_p), 4),
        'DQ_stat': round(float(dq_stat), 3), 'DQ_p': round(float(dq_p), 4),
        'Basel': basel,
        'ES_Z1': round(float(es_z1), 4) if es_z1 is not None else None,
        'ES_Z1_p': round(float(es_z1_p), 4) if es_z1_p is not None else None,
        'ES_Z2': round(float(es_z2), 4) if es_z2 is not None else None,
        'ES_Z2_p': round(float(es_z2_p), 4) if es_z2_p is not None else None,
        'scorecard': scorecard,
        'avg_var_level': round(avg_var, 6),
    }


# ============================================================
# 7. Conditional calibration (VIX regime)
# ============================================================
def conditional_calibration(returns_arr, var_v, vix_arr, alpha):
    """Check violation rate in high-VIX vs low-VIX regimes."""
    mask = ~np.isnan(var_v) & ~np.isnan(returns_arr) & ~np.isnan(vix_arr)
    ret = returns_arr[mask]
    vv = var_v[mask]
    vix_vals = vix_arr[mask]

    median_vix = np.median(vix_vals)
    high_vix = vix_vals >= median_vix
    low_vix = ~high_vix

    violations = ret < vv

    n_high = np.sum(high_vix)
    n_low = np.sum(low_vix)

    viol_high = np.sum(violations[high_vix]) / n_high if n_high > 0 else np.nan
    viol_low = np.sum(violations[low_vix]) / n_low if n_low > 0 else np.nan

    return {
        'vix_median': round(float(median_vix), 2),
        'viol_rate_high_vix': round(float(viol_high) * 100, 3) if not np.isnan(viol_high) else None,
        'viol_rate_low_vix': round(float(viol_low) * 100, 3) if not np.isnan(viol_low) else None,
        'n_high': int(n_high),
        'n_low': int(n_low),
        'target_rate': round(alpha * 100, 2),
    }


# ============================================================
# 8. QLIKE (for vol forecasting quality comparison)
# ============================================================
def qlike(r2, h):
    mask = ~np.isnan(h) & ~np.isnan(r2) & (h > 0)
    return float(np.mean(r2[mask] / h[mask] + np.log(h[mask])))


# ============================================================
# 9. Main experiment
# ============================================================
def run_experiment():
    t0 = time.time()
    print("=" * 70)
    print("K1026: Conformal VaR vs Parametric VaR")
    print("=" * 70)

    df = load_data()

    oos_start = '2013-01-02'
    window = 2000
    refit_every = 63
    cal_window = 252  # conformal calibration window
    df_fixed = 8  # degrees of freedom for Student-t

    # --- Step 1: OOS sigma forecasts ---
    print("\n[1/5] GJR-GARCH OOS forecasting...")
    h_gjr = oos_forecast_gjr(df, oos_start, window, refit_every)
    sigma_gjr = np.sqrt(h_gjr)

    print("[2/5] A4f OOS forecasting...")
    h_a4f = oos_forecast_a4f(df, oos_start, window, refit_every)
    sigma_a4f = np.sqrt(h_a4f)

    # OOS mask
    oos_idx = df.index >= oos_start
    returns_oos = df['ret'].values.copy()
    vix_oos = df['vix'].values.copy()
    r2_oos = df['r2'].values.copy()

    # --- QLIKE comparison ---
    ql_gjr = qlike(r2_oos[oos_idx], h_gjr[oos_idx])
    ql_a4f = qlike(r2_oos[oos_idx], h_a4f[oos_idx])
    print(f"\n  QLIKE: GJR={ql_gjr:.6f}, A4f={ql_a4f:.6f}")

    # --- Step 2: Compute VaR/ES for all 5 methods at 3 levels ---
    alphas = [0.01, 0.025, 0.05]
    methods = ['M1_GJR_Normal', 'M2_GJR_t8', 'M3_A4f_t8',
               'M4_Conformal_GJR', 'M5_Conformal_A4f']

    print("\n[3/5] Computing VaR/ES for all methods...")
    var_dict = {}  # (method, alpha) -> (var_arr, es_arr)

    for alpha in alphas:
        # M1: GJR + Normal
        var_m1 = sigma_gjr * norm.ppf(alpha)
        es_m1_scale = -norm.pdf(norm.ppf(alpha)) / alpha
        es_m1 = -sigma_gjr * es_m1_scale  # negative (loss)
        var_dict[('M1_GJR_Normal', alpha)] = (var_m1, es_m1)

        # M2: GJR + Student-t(df=8)
        sf = np.sqrt((df_fixed - 2.0) / df_fixed)
        q_t = t_dist.ppf(alpha, df_fixed)
        var_m2 = sigma_gjr * q_t * sf
        pdf_q = t_dist.pdf(q_t, df_fixed)
        es_m2 = -sigma_gjr * sf * (pdf_q / alpha) * ((df_fixed + q_t**2) / (df_fixed - 1))
        var_dict[('M2_GJR_t8', alpha)] = (var_m2, es_m2)

        # M3: A4f + Student-t(df=8)
        var_m3 = sigma_a4f * q_t * sf
        es_m3 = -sigma_a4f * sf * (pdf_q / alpha) * ((df_fixed + q_t**2) / (df_fixed - 1))
        var_dict[('M3_A4f_t8', alpha)] = (var_m3, es_m3)

        # M4: Conformal GJR
        var_m4, es_m4 = compute_conformal_var_es(sigma_gjr, returns_oos, alpha, cal_window)
        var_dict[('M4_Conformal_GJR', alpha)] = (var_m4, es_m4)

        # M5: Conformal A4f
        var_m5, es_m5 = compute_conformal_var_es(sigma_a4f, returns_oos, alpha, cal_window)
        var_dict[('M5_Conformal_A4f', alpha)] = (var_m5, es_m5)

    # --- Step 3: Evaluate all methods ---
    print("\n[4/5] Evaluating VaR backtests...")
    results = {}
    results['qlike'] = {'GJR': ql_gjr, 'A4f': ql_a4f}
    results['var_eval'] = {}
    results['conditional_cal'] = {}

    for method in methods:
        results['var_eval'][method] = {}
        results['conditional_cal'][method] = {}
        for alpha in alphas:
            var_v, es_v = var_dict[(method, alpha)]
            eval_res = var_es_evaluation(returns_oos, var_v, es_v, alpha, sigma_arr=sigma_gjr)
            results['var_eval'][method][str(alpha)] = eval_res

            # Conditional calibration
            cond_cal = conditional_calibration(returns_oos, var_v, vix_oos, alpha)
            results['conditional_cal'][method][str(alpha)] = cond_cal

            status = "PASS" if eval_res['UC_p'] > 0.05 and eval_res['CC_p'] > 0.05 and eval_res['Basel'] == 'GREEN' else "FAIL"
            print(f"  {method:25s} alpha={alpha:.3f}: viol={eval_res['violation_rate']:.2f}% "
                  f"UC_p={eval_res['UC_p']:.3f} CC_p={eval_res['CC_p']:.3f} "
                  f"DQ_p={eval_res['DQ_p']:.3f} Basel={eval_res['Basel']} "
                  f"Score={eval_res['scorecard']} AvgVaR={eval_res['avg_var_level']:.5f} [{status}]")

    # --- Sharpness comparison ---
    print("\n--- Sharpness (average |VaR|) ---")
    sharpness = {}
    for method in methods:
        sharpness[method] = {}
        for alpha in alphas:
            avg_var = results['var_eval'][method][str(alpha)]['avg_var_level']
            sharpness[method][str(alpha)] = avg_var
            print(f"  {method:25s} alpha={alpha:.3f}: avg|VaR|={avg_var:.6f}")
    results['sharpness'] = sharpness

    # --- Conditional calibration summary ---
    print("\n--- Conditional Calibration (VIX regime, alpha=0.025) ---")
    for method in methods:
        cc = results['conditional_cal'][method]['0.025']
        print(f"  {method:25s}: High-VIX={cc['viol_rate_high_vix']:.2f}% "
              f"Low-VIX={cc['viol_rate_low_vix']:.2f}% (target={cc['target_rate']:.2f}%)")

    elapsed = time.time() - t0
    results['metadata'] = {
        'experiment': 'K1026',
        'title': 'Proxy-Reliance Controlled Conformal VaR vs Parametric VaR',
        'asset': 'SPY',
        'oos_start': oos_start,
        'window': window,
        'refit_every': refit_every,
        'cal_window': cal_window,
        'df_fixed': df_fixed,
        'data_source': 'yfinance',
        'seed': 42,
        'elapsed_seconds': round(elapsed, 1),
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
    }

    # --- Step 4: Plots ---
    print("\n[5/5] Generating plots...")
    generate_scorecard_heatmap(results, methods, alphas)
    generate_sharpness_plot(results, methods, alphas)
    generate_var_timeline(df, var_dict, returns_oos, oos_start, methods)

    # --- Save results ---
    results_path = os.path.join(SCRIPT_DIR, 'k1026_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}")

    # --- Print summary ---
    print_summary(results, methods, alphas)

    print(f"\nTotal elapsed: {elapsed:.1f}s")
    return results


# ============================================================
# 10. Plotting functions
# ============================================================
def generate_scorecard_heatmap(results, methods, alphas):
    """VaR scorecard heatmap: methods x levels x pass/fail."""
    fig, ax = plt.subplots(figsize=(12, 6))

    # Build score matrix
    n_methods = len(methods)
    n_alphas = len(alphas)
    score_matrix = np.zeros((n_methods, n_alphas))
    annot_matrix = []

    for i, method in enumerate(methods):
        row = []
        for j, alpha in enumerate(alphas):
            ev = results['var_eval'][method][str(alpha)]
            # Score: count of passes (UC, CC, DQ, Basel)
            passes = sum([
                ev['UC_p'] > 0.05,
                ev['CC_p'] > 0.05,
                ev['DQ_p'] > 0.05,
                ev['Basel'] == 'GREEN',
            ])
            score_matrix[i, j] = passes
            row.append(f"{ev['scorecard']}\n{ev['violation_rate']:.2f}%")
        annot_matrix.append(row)

    # Color map: 0-1=red, 2=orange, 3=yellow, 4=green
    cmap = plt.cm.RdYlGn
    im = ax.imshow(score_matrix, cmap=cmap, vmin=0, vmax=4, aspect='auto')

    # Annotations
    for i in range(n_methods):
        for j in range(n_alphas):
            color = 'white' if score_matrix[i, j] < 2 else 'black'
            ax.text(j, i, annot_matrix[i][j], ha='center', va='center',
                    fontsize=10, fontweight='bold', color=color)

    ax.set_xticks(range(n_alphas))
    ax.set_xticklabels([f"VaR {int(a*100)}%" if a >= 0.05 else f"VaR {a*100:.1f}%" for a in alphas])
    ax.set_yticks(range(n_methods))
    ax.set_yticklabels([m.replace('_', ' ') for m in methods])
    ax.set_title('K1026: VaR Scorecard — Conformal vs Parametric\n'
                 '(score/total, violation rate)', fontsize=13, fontweight='bold')

    cbar = fig.colorbar(im, ax=ax, shrink=0.6)
    cbar.set_label('Tests Passed (out of 4)')
    cbar.set_ticks([0, 1, 2, 3, 4])

    plt.tight_layout()
    path = os.path.join(SCRIPT_DIR, 'k1026_var_scorecard.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path}")


def generate_sharpness_plot(results, methods, alphas):
    """VaR width (sharpness) comparison bar chart."""
    fig, ax = plt.subplots(figsize=(12, 6))

    x = np.arange(len(methods))
    width = 0.25
    colors = ['#e74c3c', '#f39c12', '#2ecc71']

    for j, alpha in enumerate(alphas):
        vals = [results['sharpness'][m][str(alpha)] for m in methods]
        label = f"VaR {int(alpha*100)}%" if alpha >= 0.05 else f"VaR {alpha*100:.1f}%"
        bars = ax.bar(x + j * width - width, vals, width, label=label, color=colors[j], alpha=0.85)
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                    f'{val:.5f}', ha='center', va='bottom', fontsize=7)

    ax.set_xticks(x)
    ax.set_xticklabels([m.replace('_', '\n') for m in methods], fontsize=9)
    ax.set_ylabel('Average |VaR| (lower = sharper)', fontsize=11)
    ax.set_title('K1026: VaR Sharpness — Average VaR Level by Method\n'
                 '(narrower VaR = better, conditional on coverage being correct)',
                 fontsize=12, fontweight='bold')
    ax.legend(loc='upper right')
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    path = os.path.join(SCRIPT_DIR, 'k1026_var_sharpness.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path}")


def generate_var_timeline(df, var_dict, returns_arr, oos_start, methods):
    """Timeline plot showing VaR bounds vs actual returns for 2.5% level."""
    alpha = 0.025
    oos_mask = df.index >= oos_start
    dates = df.index[oos_mask]
    ret_oos = returns_arr[oos_mask]

    fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)

    # Plot subset of methods for clarity
    plot_methods = [
        ('M1_GJR_Normal', '#e74c3c', 'GJR+Normal'),
        ('M2_GJR_t8', '#3498db', 'GJR+Student-t(8)'),
        ('M4_Conformal_GJR', '#2ecc71', 'Conformal-GJR'),
    ]

    # Panel 1: Returns + VaR bounds (GJR-based)
    ax = axes[0]
    ax.plot(dates, ret_oos, color='gray', alpha=0.3, linewidth=0.5, label='Returns')
    for method, color, label in plot_methods:
        var_v = var_dict[(method, alpha)][0][oos_mask]
        ax.plot(dates, var_v, color=color, linewidth=0.8, alpha=0.8, label=f'{label} VaR 2.5%')
    ax.set_title('GJR-based VaR 2.5% Bounds vs Returns', fontweight='bold')
    ax.legend(fontsize=8, loc='lower left')
    ax.set_ylabel('Return')
    ax.grid(alpha=0.2)

    # Panel 2: A4f-based methods
    plot_methods_a4f = [
        ('M3_A4f_t8', '#9b59b6', 'A4f+Student-t(8)'),
        ('M5_Conformal_A4f', '#e67e22', 'Conformal-A4f'),
    ]
    ax = axes[1]
    ax.plot(dates, ret_oos, color='gray', alpha=0.3, linewidth=0.5, label='Returns')
    for method, color, label in plot_methods_a4f:
        var_v = var_dict[(method, alpha)][0][oos_mask]
        ax.plot(dates, var_v, color=color, linewidth=0.8, alpha=0.8, label=f'{label} VaR 2.5%')
    ax.set_title('A4f-based VaR 2.5% Bounds vs Returns', fontweight='bold')
    ax.legend(fontsize=8, loc='lower left')
    ax.set_ylabel('Return')
    ax.grid(alpha=0.2)

    # Panel 3: VaR width comparison over time
    ax = axes[2]
    for method, color, label in plot_methods + plot_methods_a4f:
        var_v = var_dict[(method, alpha)][0][oos_mask]
        # Rolling 63-day average |VaR|
        avg = pd.Series(np.abs(var_v), index=dates).rolling(63, min_periods=20).mean()
        ax.plot(dates, avg, color=color, linewidth=1.0, alpha=0.8, label=f'{label}')
    ax.set_title('Rolling 63-day Average |VaR| (Sharpness over time)', fontweight='bold')
    ax.legend(fontsize=8, loc='upper left')
    ax.set_ylabel('Avg |VaR|')
    ax.grid(alpha=0.2)

    plt.tight_layout()
    path = os.path.join(SCRIPT_DIR, 'k1026_var_timeline.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path}")


# ============================================================
# 11. Summary
# ============================================================
def print_summary(results, methods, alphas):
    """Print a structured summary."""
    print("\n" + "=" * 70)
    print("K1026 SUMMARY: Conformal VaR vs Parametric VaR")
    print("=" * 70)

    # Count passes per method
    print("\n--- Pass Rate by Method ---")
    for method in methods:
        passes = 0
        total = 0
        for alpha in alphas:
            ev = results['var_eval'][method][str(alpha)]
            total += 4  # UC, CC, DQ, Basel
            passes += sum([
                ev['UC_p'] > 0.05,
                ev['CC_p'] > 0.05,
                ev['DQ_p'] > 0.05,
                ev['Basel'] == 'GREEN',
            ])
        print(f"  {method:25s}: {passes}/{total} ({passes/total*100:.0f}%)")

    # Key comparison: conformal vs parametric at 2.5%
    print("\n--- Key Comparison at 2.5% (most informative level) ---")
    for method in methods:
        ev = results['var_eval'][method]['0.025']
        print(f"  {method:25s}: score={ev['scorecard']} viol={ev['violation_rate']:.2f}% "
              f"avg|VaR|={ev['avg_var_level']:.6f}")

    # Conformal advantage analysis
    print("\n--- Conformal vs Parametric Analysis ---")
    for alpha in alphas:
        gjr_t = results['var_eval']['M2_GJR_t8'][str(alpha)]
        conf_gjr = results['var_eval']['M4_Conformal_GJR'][str(alpha)]
        a4f_t = results['var_eval']['M3_A4f_t8'][str(alpha)]
        conf_a4f = results['var_eval']['M5_Conformal_A4f'][str(alpha)]

        alpha_pct = f"{alpha*100:.1f}%" if alpha < 0.05 else f"{int(alpha*100)}%"
        print(f"\n  alpha={alpha_pct}:")
        print(f"    GJR:  t(8) viol={gjr_t['violation_rate']:.2f}% vs Conformal viol={conf_gjr['violation_rate']:.2f}%")
        print(f"    A4f:  t(8) viol={a4f_t['violation_rate']:.2f}% vs Conformal viol={conf_a4f['violation_rate']:.2f}%")
        print(f"    GJR:  t(8) |VaR|={gjr_t['avg_var_level']:.6f} vs Conformal |VaR|={conf_gjr['avg_var_level']:.6f}")
        print(f"    A4f:  t(8) |VaR|={a4f_t['avg_var_level']:.6f} vs Conformal |VaR|={conf_a4f['avg_var_level']:.6f}")


if __name__ == '__main__':
    results = run_experiment()
