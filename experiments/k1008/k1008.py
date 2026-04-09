"""
K1008: Regime-Weighted Conformal VaR (RWC) vs Standard Conformal
================================================================
Data: SPY 2005-2026 (yfinance), VIX as regime variable
OOS: 2019-2026, window=2000, refit/63d, calibration window W=500

Models (6 total):
  1. GJR_t + Parametric VaR/ES
  2. GJR_t + Standard Conformal VaR/ES
  3. GJR_t + RWC (bandwidth h=3,5,8)
  4. A4f_t + Parametric VaR/ES
  5. A4f_t + Standard Conformal VaR/ES
  6. A4f_t + RWC (bandwidth h=3,5,8)

Evaluation: VaR (1%, 2.5%, 5%) UC/CC/DQ, ES (2.5%) Acerbi-Szekely

References:
- arXiv:2602.03903 (2026): Regime-Weighted Conformal Prediction
- Vovk et al. (2005): Conformal prediction framework
- Gibbs & Candes (2021): Adaptive conformal inference
- Patton (2011): QLIKE, proxy-robust evaluation
- Kupiec (1995), Christoffersen (1998): VaR backtesting
- Acerbi & Szekely (2014): ES backtesting
- Harvey (2016): t>3.0 threshold
- Engle & Rangel (2008): Spline-GARCH (A4f basis)
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
from datetime import datetime
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import t as t_dist, chi2, norm
import math
import yfinance as yf
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. Data
# ============================================================
def load_data():
    spy = yf.download('SPY', start='2004-01-01', end='2026-12-31', progress=False)
    vix = yf.download('^VIX', start='2004-01-01', end='2026-12-31', progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    df = pd.DataFrame(index=spy.index)
    df['close'] = spy['Close']
    df['vix'] = vix['Close'].reindex(spy.index, method='ffill')
    df['ret'] = np.log(df['close'] / df['close'].shift(1))
    df = df.dropna()
    df['ret'] = df['ret'].clip(-0.20, 0.20)
    df['r2'] = df['ret'] ** 2
    df['vix2'] = (df['vix'] / 100) ** 2
    print(f"Data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")
    return df

# ============================================================
# 2. Numba-accelerated GARCH recursions (from K1000)
# ============================================================
@njit
def gjr_h(omega, alpha, gamma, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        r2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * r2 + gamma * r2 * ind + beta * h[t-1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h

@njit
def t_logpdf_sum(returns, h, df):
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

# ============================================================
# 3. Fitting functions
# ============================================================
def fit_gjr_t(returns):
    var0 = np.var(returns)
    bounds = [(1e-10, var0*10), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]
    def obj(p):
        if p[1] + 0.5*p[2] + p[3] >= 1.0:
            return 1e10
        try:
            h = gjr_h(p[0], p[1], p[2], p[3], returns)
            ll = t_logpdf_sum(returns, h, p[4])
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        x0 = [var0 * 0.05, 0.05, 0.05, 0.90, df_init]
        try:
            res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except:
            continue
    h = gjr_h(best_res.x[0], best_res.x[1], best_res.x[2], best_res.x[3], returns)
    return {'params': best_res.x, 'h': h, 'converged': best_res.success,
            'nll': best_res.fun, 'df': best_res.x[4]}


def fit_a4f_t_joint(returns, vix2):
    # First get Normal estimates as starting point
    bounds_n = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
                (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    var0 = np.var(returns)
    def obj_n(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_recursion(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            T = len(returns)
            ll = 0.0
            for t in range(T):
                ll += np.log(h[t]) + returns[t]**2 / h[t]
            return 0.5 * ll if np.isfinite(0.5*ll) else 1e10
        except:
            return 1e10
    best_n, best_nll_n = None, 1e10
    for theta1_init in [0.3, 0.8, 2.0]:
        for omega_init in [0.02, 0.08]:
            x0 = [1e-5, theta1_init, omega_init, 0.04, 0.06, 0.90]
            try:
                res = minimize(obj_n, x0, method='L-BFGS-B', bounds=bounds_n, options={'maxiter': 300})
                if res.fun < best_nll_n:
                    best_nll_n = res.fun
                    best_n = res
            except:
                continue
    if best_n is None:
        x0 = [1e-5, 0.5, 0.05, 0.04, 0.06, 0.90]
        best_n = minimize(obj_n, x0, method='L-BFGS-B', bounds=bounds_n)

    # Joint t estimation
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]
    def obj(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_recursion(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            ll = t_logpdf_sum(returns, h, p[6])
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        p0 = list(best_n.x) + [df_init]
        try:
            res = minimize(obj, p0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except:
            continue
    h, tau, g = a4f_recursion(best_res.x[0], best_res.x[1], best_res.x[2],
                               best_res.x[3], best_res.x[4], best_res.x[5],
                               returns, vix2)
    return {'params': best_res.x, 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success, 'nll': best_res.fun,
            'df': best_res.x[6]}

# ============================================================
# 4. OOS forecasting — returns h, df for each t
# ============================================================
def oos_forecast(df, model_name, window=2000, refit_every=63):
    oos_start_idx = np.where(df.index >= '2019-01-01')[0][0]
    T = len(df)
    forecasts = np.full(T, np.nan)
    df_estimates = np.full(T, np.nan)
    returns = df['ret'].values
    vix2 = df['vix2'].values

    last_fit = None
    last_fit_idx = -refit_every
    h_prev = np.nan
    g_prev = np.nan

    for t in range(oos_start_idx, T):
        if t - last_fit_idx >= refit_every or last_fit is None:
            s = max(0, t - window)
            tr = returns[s:t]
            tv = vix2[s:t]

            if model_name == 'GJR_t':
                last_fit = fit_gjr_t(tr)
            elif model_name == 'A4f_t':
                last_fit = fit_a4f_t_joint(tr, tv)

            last_fit_idx = t
            h_prev = last_fit['h'][-1]
            g_prev = last_fit.get('g', np.array([1.0]))[-1]

        p = last_fit['params']

        if model_name == 'GJR_t':
            omega, alpha, gamma, beta = p[0], p[1], p[2], p[3]
            df_estimates[t] = p[4]
            r_prev = returns[t-1]
            r2p = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h_t = omega + alpha * r2p + gamma * r2p * ind + beta * h_prev
            h_t = max(h_t, 1e-16)
            forecasts[t] = h_t
            h_prev = h_t
        else:  # A4f_t
            theta0, theta1, omega, alpha, gamma, beta = p[0], p[1], p[2], p[3], p[4], p[5]
            df_estimates[t] = p[6]
            tau_t = max(theta0 + theta1 * vix2[t-1], 1e-16)
            u_prev = returns[t-1] / np.sqrt(tau_t)
            u2 = u_prev ** 2
            ind = 1.0 if returns[t-1] < 0 else 0.0
            g_t = omega + alpha * u2 + gamma * u2 * ind + beta * g_prev
            g_t = max(g_t, 1e-16)
            forecasts[t] = tau_t * g_t
            g_prev = g_t

    return forecasts, df_estimates

# ============================================================
# 5. Parametric VaR/ES
# ============================================================
def compute_var_es_parametric(sigma, df_vals, alpha):
    T = len(sigma)
    var_v = np.full(T, np.nan)
    es_v = np.full(T, np.nan)
    for i in range(T):
        s = sigma[i]
        if np.isnan(s) or s <= 0:
            continue
        if not np.isnan(df_vals[i]) and df_vals[i] > 2:
            df = df_vals[i]
            sf = np.sqrt((df-2)/df)
            q = t_dist.ppf(alpha, df)
            var_v[i] = s * q * sf
            pdf_q = t_dist.pdf(q, df)
            es_v[i] = s * sf * (-pdf_q / alpha) * ((df + q**2) / (df - 1))
        else:
            q = norm.ppf(alpha)
            var_v[i] = s * q
            es_v[i] = s * (-norm.pdf(q) / alpha)
    return var_v, es_v

# ============================================================
# 6. Conformal VaR/ES methods
# ============================================================
def compute_standardized_residuals(returns, h, oos_mask):
    """Compute z_t = r_t / sigma_t for all OOS points."""
    sigma = np.sqrt(h)
    z = np.full_like(returns, np.nan)
    valid = oos_mask & ~np.isnan(h) & (h > 0)
    z[valid] = returns[valid] / sigma[valid]
    return z


def standard_conformal_var_es(returns, h, vix_levels, oos_mask, alpha, cal_window=500):
    """Standard conformal: equal weight on calibration residuals."""
    T = len(returns)
    sigma = np.sqrt(h)
    z = compute_standardized_residuals(returns, h, oos_mask)

    var_v = np.full(T, np.nan)
    es_v = np.full(T, np.nan)

    oos_indices = np.where(oos_mask)[0]

    for t in oos_indices:
        # Calibration set: last cal_window OOS residuals before t
        cal_start = max(oos_indices[0], t - cal_window)
        cal_indices = np.arange(cal_start, t)
        cal_z = z[cal_indices]
        valid = ~np.isnan(cal_z)
        cal_z = cal_z[valid]

        if len(cal_z) < 30:
            # Not enough calibration data, use parametric
            continue

        # Standard conformal: equal weight quantile
        q_conf = np.quantile(cal_z, alpha)

        s_t = sigma[t]
        if np.isnan(s_t) or s_t <= 0:
            continue

        var_v[t] = s_t * q_conf

        # ES: average of residuals below quantile
        tail_z = cal_z[cal_z <= q_conf]
        if len(tail_z) > 0:
            es_v[t] = s_t * np.mean(tail_z)
        else:
            es_v[t] = var_v[t]  # fallback

    return var_v, es_v


def rwc_conformal_var_es(returns, h, vix_levels, oos_mask, alpha,
                         cal_window=500, bandwidth=5.0):
    """Regime-Weighted Conformal: Gaussian kernel on VIX for calibration weights."""
    T = len(returns)
    sigma = np.sqrt(h)
    z = compute_standardized_residuals(returns, h, oos_mask)

    var_v = np.full(T, np.nan)
    es_v = np.full(T, np.nan)

    oos_indices = np.where(oos_mask)[0]

    for t in oos_indices:
        cal_start = max(oos_indices[0], t - cal_window)
        cal_indices = np.arange(cal_start, t)
        cal_z = z[cal_indices]
        cal_vix = vix_levels[cal_indices]
        valid = ~np.isnan(cal_z) & ~np.isnan(cal_vix)
        cal_z = cal_z[valid]
        cal_vix = cal_vix[valid]

        if len(cal_z) < 30:
            continue

        s_t = sigma[t]
        if np.isnan(s_t) or s_t <= 0:
            continue

        vix_t = vix_levels[t]
        if np.isnan(vix_t):
            continue

        # Gaussian kernel weights based on VIX similarity
        weights = np.exp(-0.5 * ((vix_t - cal_vix) / bandwidth) ** 2)
        weights_sum = weights.sum()
        if weights_sum < 1e-12:
            # All weights ~0 => fallback to equal weight
            q_conf = np.quantile(cal_z, alpha)
        else:
            weights = weights / weights_sum

            # Weighted quantile: sort by z, cumulate weights, find alpha crossing
            sort_idx = np.argsort(cal_z)
            sorted_z = cal_z[sort_idx]
            sorted_w = weights[sort_idx]
            cum_w = np.cumsum(sorted_w)
            # Find first index where cumulative weight >= alpha
            idx_alpha = np.searchsorted(cum_w, alpha)
            if idx_alpha >= len(sorted_z):
                idx_alpha = len(sorted_z) - 1
            q_conf = sorted_z[idx_alpha]

        var_v[t] = s_t * q_conf

        # Weighted ES: weighted average of residuals below quantile
        below = cal_z <= q_conf
        if np.sum(below) > 0:
            if weights_sum >= 1e-12:
                w_below = weights[below]
                w_below_sum = w_below.sum()
                if w_below_sum > 0:
                    es_v[t] = s_t * np.average(cal_z[below], weights=w_below)
                else:
                    es_v[t] = s_t * np.mean(cal_z[below])
            else:
                es_v[t] = s_t * np.mean(cal_z[below])
        else:
            es_v[t] = var_v[t]

    return var_v, es_v

# ============================================================
# 7. Statistical tests (from K1000)
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

def dq_test(violations, alpha, sigma_arr):
    T = len(violations)
    hit = violations.astype(float) - alpha
    X = np.column_stack([np.ones(T-1), hit[:-1], sigma_arr[1:]])
    y = hit[1:]
    try:
        XtX_inv = np.linalg.inv(X.T @ X)
        beta = XtX_inv @ X.T @ y
        dq_stat = (beta.T @ X.T @ X @ beta) / (alpha * (1 - alpha))
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

# ============================================================
# 8. Evaluate one VaR/ES configuration
# ============================================================
def evaluate_var_es(returns_arr, var_v, es_v, sigma_arr, alpha_level, label):
    """Full VaR/ES evaluation for one model at one alpha level."""
    # Align on valid points
    valid = ~np.isnan(var_v) & ~np.isnan(es_v) & ~np.isnan(returns_arr)
    r = returns_arr[valid]
    v = var_v[valid]
    e = es_v[valid]
    s = sigma_arr[valid]
    T = len(r)
    if T < 50:
        return {'label': label, 'alpha': alpha_level, 'T': T, 'error': 'insufficient_data'}

    violations = (r < v).astype(int)
    viol_rate = np.mean(violations)

    # UC test
    uc_stat, uc_p = kupiec_test(violations, T, alpha_level)
    # CC test
    cc_stat, cc_p = christoffersen_cc_test(violations)
    # DQ test
    dq_stat, dq_p = dq_test(violations, alpha_level, s)

    # Basel traffic light (250-day window approx)
    window_250 = min(T, 250)
    last_viols = np.sum(violations[-window_250:])
    if last_viols <= int(alpha_level * window_250 * 1.5) + 1:
        basel = 'Green'
    elif last_viols <= int(alpha_level * window_250 * 2.5) + 2:
        basel = 'Yellow'
    else:
        basel = 'Red'

    # Trinity
    trinity = 'PASS' if (uc_p > 0.05 and cc_p > 0.05 and basel == 'Green') else 'FAIL'

    # ES test (only at 2.5%)
    es_z1, es_p = (np.nan, np.nan)
    if alpha_level == 0.025:
        es_z1, es_p = acerbi_szekely_z1(r, v, e, alpha_level)

    return {
        'label': label,
        'alpha': alpha_level,
        'T': T,
        'viol_rate': round(viol_rate, 5),
        'viol_count': int(np.sum(violations)),
        'UC_stat': round(float(uc_stat), 4),
        'UC_p': round(float(uc_p), 4),
        'CC_stat': round(float(cc_stat), 4),
        'CC_p': round(float(cc_p), 4),
        'DQ_stat': round(float(dq_stat), 4),
        'DQ_p': round(float(dq_p), 4),
        'Basel': basel,
        'Trinity': trinity,
        'ES_z1': round(float(es_z1), 4) if not np.isnan(es_z1) else None,
        'ES_p': round(float(es_p), 4) if not np.isnan(es_p) else None,
    }

# ============================================================
# 9. Main
# ============================================================
def main():
    print("=" * 70)
    print("K1008: Regime-Weighted Conformal VaR (RWC)")
    print("=" * 70)

    df = load_data()

    # --- OOS forecasts for both base models ---
    print("\n--- GJR_t OOS forecasting ---")
    h_gjr, df_gjr = oos_forecast(df, 'GJR_t', window=2000, refit_every=63)
    print("GJR_t: done")

    print("\n--- A4f_t OOS forecasting ---")
    h_a4f, df_a4f = oos_forecast(df, 'A4f_t', window=2000, refit_every=63)
    print("A4f_t: done")

    # OOS mask
    oos_start_idx = np.where(df.index >= '2019-01-01')[0][0]
    oos_mask = np.zeros(len(df), dtype=bool)
    oos_mask[oos_start_idx:] = True

    returns = df['ret'].values
    vix_levels = df['vix'].values  # Raw VIX level for kernel

    # sigma
    sigma_gjr = np.sqrt(np.where(h_gjr > 0, h_gjr, np.nan))
    sigma_a4f = np.sqrt(np.where(h_a4f > 0, h_a4f, np.nan))

    # --- QLIKE comparison ---
    r2 = df['r2'].values
    oos_r2 = r2[oos_mask]
    oos_h_gjr = h_gjr[oos_mask]
    oos_h_a4f = h_a4f[oos_mask]
    valid_gjr = ~np.isnan(oos_h_gjr) & (oos_h_gjr > 0)
    valid_a4f = ~np.isnan(oos_h_a4f) & (oos_h_a4f > 0)
    qlike_gjr = np.mean(oos_r2[valid_gjr] / oos_h_gjr[valid_gjr] + np.log(oos_h_gjr[valid_gjr]))
    qlike_a4f = np.mean(oos_r2[valid_a4f] / oos_h_a4f[valid_a4f] + np.log(oos_h_a4f[valid_a4f]))
    print(f"\nQLIKE - GJR_t: {qlike_gjr:.6f}, A4f_t: {qlike_a4f:.6f}")

    # --- Alpha levels ---
    alpha_levels = [0.01, 0.025, 0.05]
    bandwidths = [3.0, 5.0, 8.0]

    all_results = []

    for base_model, h_vals, df_vals, sigma_vals in [
        ('GJR_t', h_gjr, df_gjr, sigma_gjr),
        ('A4f_t', h_a4f, df_a4f, sigma_a4f),
    ]:
        print(f"\n{'='*50}")
        print(f"Base model: {base_model}")
        print(f"{'='*50}")

        for alpha in alpha_levels:
            print(f"\n--- alpha = {alpha} ---")

            # 1) Parametric
            var_param, es_param = compute_var_es_parametric(sigma_vals, df_vals, alpha)
            res = evaluate_var_es(returns[oos_mask], var_param[oos_mask], es_param[oos_mask],
                                  sigma_vals[oos_mask], alpha, f"{base_model}_Parametric")
            all_results.append(res)
            print(f"  Parametric: viol={res['viol_rate']:.4f} UC_p={res['UC_p']:.3f} "
                  f"CC_p={res['CC_p']:.3f} Trinity={res['Trinity']}")

            # 2) Standard Conformal
            var_sc, es_sc = standard_conformal_var_es(
                returns, h_vals, vix_levels, oos_mask, alpha, cal_window=500)
            res = evaluate_var_es(returns[oos_mask], var_sc[oos_mask], es_sc[oos_mask],
                                  sigma_vals[oos_mask], alpha, f"{base_model}_StdConformal")
            all_results.append(res)
            print(f"  StdConformal: viol={res['viol_rate']:.4f} UC_p={res['UC_p']:.3f} "
                  f"CC_p={res['CC_p']:.3f} Trinity={res['Trinity']}")

            # 3) RWC at different bandwidths
            for bw in bandwidths:
                var_rwc, es_rwc = rwc_conformal_var_es(
                    returns, h_vals, vix_levels, oos_mask, alpha,
                    cal_window=500, bandwidth=bw)
                res = evaluate_var_es(returns[oos_mask], var_rwc[oos_mask], es_rwc[oos_mask],
                                      sigma_vals[oos_mask], alpha,
                                      f"{base_model}_RWC_h{int(bw)}")
                all_results.append(res)
                print(f"  RWC(h={bw}): viol={res['viol_rate']:.4f} UC_p={res['UC_p']:.3f} "
                      f"CC_p={res['CC_p']:.3f} Trinity={res['Trinity']}")

    # --- Summary ---
    print("\n" + "=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)

    # Count Trinity PASS per model
    trinity_counts = {}
    for r in all_results:
        label = r['label']
        if label not in trinity_counts:
            trinity_counts[label] = {'pass': 0, 'total': 0}
        trinity_counts[label]['total'] += 1
        if r.get('Trinity') == 'PASS':
            trinity_counts[label]['pass'] += 1

    print(f"\n{'Model':<30} {'PASS/Total':>12}")
    print("-" * 45)
    for label, counts in sorted(trinity_counts.items()):
        print(f"{label:<30} {counts['pass']}/{counts['total']:>5}")

    # ES results at 2.5%
    print(f"\n{'Model':<30} {'ES_z1':>8} {'ES_p':>8}")
    print("-" * 50)
    for r in all_results:
        if r.get('ES_z1') is not None:
            print(f"{r['label']:<30} {r['ES_z1']:>8.4f} {r['ES_p']:>8.4f}")

    # --- Regime analysis: VaR performance in high vs low VIX ---
    print("\n" + "=" * 70)
    print("REGIME ANALYSIS: High VIX (>=25) vs Low VIX (<25)")
    print("=" * 70)

    regime_results = []
    for base_model, h_vals, df_vals, sigma_vals in [
        ('GJR_t', h_gjr, df_gjr, sigma_gjr),
        ('A4f_t', h_a4f, df_a4f, sigma_a4f),
    ]:
        for alpha in [0.025]:  # Focus on 2.5%
            # Parametric
            var_param, es_param = compute_var_es_parametric(sigma_vals, df_vals, alpha)
            # Standard Conformal
            var_sc, es_sc = standard_conformal_var_es(
                returns, h_vals, vix_levels, oos_mask, alpha, cal_window=500)
            # RWC h=5
            var_rwc, es_rwc = rwc_conformal_var_es(
                returns, h_vals, vix_levels, oos_mask, alpha,
                cal_window=500, bandwidth=5.0)

            for regime_name, regime_cond in [('High_VIX', vix_levels >= 25),
                                              ('Low_VIX', vix_levels < 25)]:
                regime_oos = oos_mask & regime_cond
                n_regime = np.sum(regime_oos)
                if n_regime < 30:
                    continue

                for label, var_v, es_v in [
                    (f"{base_model}_Param", var_param, es_param),
                    (f"{base_model}_StdConf", var_sc, es_sc),
                    (f"{base_model}_RWC5", var_rwc, es_rwc),
                ]:
                    r_reg = returns[regime_oos]
                    v_reg = var_v[regime_oos]
                    valid = ~np.isnan(v_reg)
                    if np.sum(valid) < 20:
                        continue
                    viol_rate = np.mean(r_reg[valid] < v_reg[valid])
                    regime_results.append({
                        'regime': regime_name,
                        'label': label,
                        'n': int(np.sum(valid)),
                        'viol_rate': round(viol_rate, 4),
                        'target': alpha,
                    })

    print(f"\n{'Regime':<12} {'Model':<25} {'N':>6} {'Viol%':>8} {'Target':>8}")
    print("-" * 65)
    for r in regime_results:
        print(f"{r['regime']:<12} {r['label']:<25} {r['n']:>6} {r['viol_rate']:>8.4f} {r['target']:>8.4f}")

    # --- Save results ---
    results = {
        'experiment_id': 'K1008',
        'title': 'Regime-Weighted Conformal VaR (RWC) vs Standard Conformal',
        'data_source': 'yfinance (SPY, ^VIX)',
        'data_period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'oos_period': f"{df.index[oos_start_idx].date()} to {df.index[-1].date()}",
        'oos_n': int(np.sum(oos_mask)),
        'window': 2000,
        'refit_every': 63,
        'cal_window': 500,
        'bandwidths': bandwidths,
        'qlike': {
            'GJR_t': round(qlike_gjr, 6),
            'A4f_t': round(qlike_a4f, 6),
        },
        'var_es_results': all_results,
        'trinity_summary': {k: v for k, v in trinity_counts.items()},
        'regime_analysis': regime_results,
        'references': [
            'arXiv:2602.03903 (2026) Regime-Weighted Conformal Prediction',
            'Vovk et al. (2005) Conformal prediction',
            'Gibbs & Candes (2021) Adaptive conformal inference',
            'Patton (2011) QLIKE',
            'Kupiec (1995) VaR UC test',
            'Christoffersen (1998) CC test',
            'Acerbi & Szekely (2014) ES backtest',
            'Harvey (2016) t>3.0 threshold',
        ],
        'timestamp': datetime.now().isoformat(),
    }

    out_path = os.path.join(SCRIPT_DIR, 'k1008_results.json')
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

    return results


if __name__ == '__main__':
    results = main()
