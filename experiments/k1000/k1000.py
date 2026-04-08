"""
K1000: MF-GJR-X(A4f) + Student-t Joint MLE — 5-Model OOS Comparison
=====================================================================
Data: SPY 2005-2026 (yfinance), OOS: 2019-2026, window=2000, refit/63d
Models: GJR_N, GJR_t, A4f_N, A4f_t_2step, A4f_t_joint
Evaluation: QLIKE on r², DM test (Harvey t>3.0), VaR (1%,2.5%,5%), ES (2.5%)

References:
- Engle & Rangel (2008): Spline-GARCH
- Patton (2011): QLIKE loss, proxy-robust ranking
- Kupiec (1995), Christoffersen (1998): VaR backtesting
- Acerbi & Szekely (2014): ES backtesting
- Harvey (2016): t>3.0 threshold for multiple testing
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
# 2. Numba-accelerated GARCH recursions
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
def gjr_nll_normal(omega, alpha, gamma, beta, returns):
    h = gjr_h(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll  # negative of log-likelihood (to minimize)

@njit
def t_logpdf_sum(returns, h, df):
    """Sum of Student-t logpdf with scale = sigma * sqrt((df-2)/df)."""
    T = len(returns)
    scale_factor = np.sqrt((df - 2.0) / df)
    # t_logpdf = gammaln((df+1)/2) - gammaln(df/2) - 0.5*log(pi*df) - log(scale)
    #            - (df+1)/2 * log(1 + (x/scale)^2/df)
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

@njit
def a4f_nll_normal(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll

# ============================================================
# 3. Fitting functions
# ============================================================
def fit_gjr_normal(returns):
    var0 = np.var(returns)
    bounds = [(1e-10, var0*10), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[1] + 0.5*p[2] + p[3] >= 1.0:
            return 1e10
        try:
            v = gjr_nll_normal(p[0], p[1], p[2], p[3], returns)
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10
    x0 = [var0 * 0.05, 0.05, 0.05, 0.90]
    res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
    h = gjr_h(res.x[0], res.x[1], res.x[2], res.x[3], returns)
    return {'params': res.x, 'h': h, 'converged': res.success, 'nll': res.fun}


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


def fit_a4f_normal(returns, vix2):
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


def fit_a4f_t_2step(returns, vix2):
    res_n = fit_a4f_normal(returns, vix2)
    std_resid = returns / np.sqrt(res_n['h'])
    def neg_ll_df(d):
        if d <= 2.01:
            return 1e10
        scale = np.sqrt((d - 2) / d)
        return -np.sum(t_dist.logpdf(std_resid, d, loc=0, scale=scale))
    res_df = minimize_scalar(neg_ll_df, bounds=(3.0, 50.0), method='bounded')
    df = res_df.x
    return {'params': np.append(res_n['params'], df), 'h': res_n['h'],
            'tau': res_n['tau'], 'g': res_n['g'],
            'converged': res_n['converged'], 'nll': res_n['nll'], 'df': df}


def fit_a4f_t_joint(returns, vix2):
    res_n = fit_a4f_normal(returns, vix2)
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
        p0 = list(res_n['params']) + [df_init]
        try:
            res = minimize(obj, p0, method='L-BFGS-B', bounds=bounds,
                           options={'maxiter': 300})
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
# 4. OOS forecasting
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
        # Refit?
        if t - last_fit_idx >= refit_every or last_fit is None:
            s = max(0, t - window)
            tr = returns[s:t]
            tv = vix2[s:t]

            if model_name == 'GJR_N':
                last_fit = fit_gjr_normal(tr)
            elif model_name == 'GJR_t':
                last_fit = fit_gjr_t(tr)
            elif model_name == 'A4f_N':
                last_fit = fit_a4f_normal(tr, tv)
            elif model_name == 'A4f_t_2step':
                last_fit = fit_a4f_t_2step(tr, tv)
            elif model_name == 'A4f_t_joint':
                last_fit = fit_a4f_t_joint(tr, tv)

            last_fit_idx = t
            h_prev = last_fit['h'][-1]
            g_prev = last_fit.get('g', np.array([1.0]))[-1]

        p = last_fit['params']

        if model_name in ['GJR_N', 'GJR_t']:
            omega, alpha, gamma, beta = p[0], p[1], p[2], p[3]
            if model_name == 'GJR_t':
                df_estimates[t] = p[4]
            r_prev = returns[t-1]
            r2p = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h_t = omega + alpha * r2p + gamma * r2p * ind + beta * h_prev
            h_t = max(h_t, 1e-16)
            forecasts[t] = h_t
            h_prev = h_t
        else:
            theta0, theta1, omega, alpha, gamma, beta = p[0], p[1], p[2], p[3], p[4], p[5]
            if model_name in ['A4f_t_2step', 'A4f_t_joint']:
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
# 5. Evaluation
# ============================================================
def qlike(r2, h):
    mask = ~np.isnan(h) & ~np.isnan(r2) & (h > 0)
    return np.mean(r2[mask] / h[mask] + np.log(h[mask]))

def dm_test(loss1, loss2):
    d = loss1 - loss2
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_bar = np.mean(d)
    max_lag = int(n ** (1/3))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * w * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0
    t_stat = d_bar / np.sqrt(var_d)
    p_val = 2 * (1 - norm.cdf(abs(t_stat)))
    return t_stat, p_val

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

def compute_var_es(sigma, df_vals, alpha):
    """VaR and ES from sigma and df. Normal if df is NaN."""
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

def var_es_evaluation(returns_arr, sigma, df_vals, alpha):
    var_v, es_v = compute_var_es(sigma, df_vals, alpha)
    mask = ~np.isnan(var_v)
    ret = returns_arr[mask]; vv = var_v[mask]; ev = es_v[mask]; sig = sigma[mask]
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
    if np.sum(violations) <= expected * 1.5:
        basel = "GREEN"
    elif np.sum(violations) <= expected * 2.0:
        basel = "YELLOW"
    else:
        basel = "RED"

    n_pass = sum([uc_p > 0.05, cc_p > 0.05, dq_p > 0.05, basel == "GREEN"])
    if abs(alpha - 0.025) < 0.001 and es_z1_p is not None:
        n_pass_total = n_pass + sum([es_z1_p > 0.05, es_z2_p > 0.05])
        scorecard = f"{n_pass_total}/6"
    else:
        scorecard = f"{n_pass}/4"

    return {
        'alpha': alpha, 'T': T,
        'violations': int(np.sum(violations)),
        'violation_rate': round(viol_rate * 100, 2),
        'expected_rate': round(alpha * 100, 2),
        'UC_stat': round(uc_stat, 3), 'UC_p': round(uc_p, 4),
        'CC_stat': round(cc_stat, 3), 'CC_p': round(cc_p, 4),
        'DQ_stat': round(dq_stat, 3), 'DQ_p': round(dq_p, 4),
        'Basel': basel,
        'ES_Z1': round(es_z1, 4) if es_z1 is not None else None,
        'ES_Z1_p': round(es_z1_p, 4) if es_z1_p is not None else None,
        'ES_Z2': round(es_z2, 4) if es_z2 is not None else None,
        'ES_Z2_p': round(es_z2_p, 4) if es_z2_p is not None else None,
        'scorecard': scorecard,
    }

# ============================================================
# 6. Main
# ============================================================
def main():
    print("=" * 70)
    print("K1000: MF-GJR-X(A4f) + Student-t Joint MLE — 5-Model OOS Comparison")
    print("=" * 70)

    # Warm up numba
    _dummy = np.random.randn(100)
    _ = gjr_h(1e-6, 0.05, 0.05, 0.9, _dummy)
    _ = gjr_nll_normal(1e-6, 0.05, 0.05, 0.9, _dummy)
    _ = t_logpdf_sum(_dummy, np.abs(_dummy) + 1e-6, 5.0)
    _dv = np.ones(100) * 0.0004
    _ = a4f_recursion(1e-5, 0.5, 0.05, 0.04, 0.06, 0.9, _dummy, _dv)
    _ = a4f_nll_normal(1e-5, 0.5, 0.05, 0.04, 0.06, 0.9, _dummy, _dv)
    print("Numba JIT compiled.")

    df = load_data()
    models = ['GJR_N', 'GJR_t', 'A4f_N', 'A4f_t_2step', 'A4f_t_joint']
    results = {}
    forecasts_all = {}
    df_all = {}

    oos_mask = np.array(df.index >= '2019-01-01')
    returns_oos = df['ret'].values[oos_mask]
    r2_oos = df['r2'].values[oos_mask]

    for model_name in models:
        print(f"\n--- {model_name} ---")
        import time
        t0 = time.time()
        h_forecast, df_est = oos_forecast(df, model_name, window=2000, refit_every=63)
        elapsed = time.time() - t0
        print(f"  Elapsed: {elapsed:.1f}s")

        h_oos = h_forecast[oos_mask]
        df_oos = df_est[oos_mask]
        sigma_oos = np.sqrt(h_oos)
        forecasts_all[model_name] = h_oos
        df_all[model_name] = df_oos

        ql = qlike(r2_oos, h_oos)
        print(f"  QLIKE = {ql:.6f}")

        var_results = {}
        for alpha in [0.01, 0.025, 0.05]:
            ve = var_es_evaluation(returns_oos, sigma_oos, df_oos, alpha)
            var_results[str(alpha)] = ve
            print(f"  VaR {alpha*100:.1f}%: viol={ve['violation_rate']:.2f}% "
                  f"UC_p={ve['UC_p']:.3f} CC_p={ve['CC_p']:.3f} "
                  f"DQ_p={ve['DQ_p']:.3f} Basel={ve['Basel']} "
                  f"Score={ve['scorecard']}")
            if abs(alpha - 0.025) < 0.001 and ve['ES_Z1'] is not None:
                print(f"  ES 2.5%: Z1={ve['ES_Z1']:.4f}(p={ve['ES_Z1_p']:.3f}) "
                      f"Z2={ve['ES_Z2']:.4f}(p={ve['ES_Z2_p']:.3f})")

        # Final IS fit for param recording
        is_mask = ~oos_mask
        is_ret = df['ret'].values[is_mask][-2000:]
        is_vix2 = df['vix2'].values[is_mask][-2000:]

        if model_name == 'GJR_N':
            final = fit_gjr_normal(is_ret)
            pn = ['omega', 'alpha', 'gamma', 'beta']
        elif model_name == 'GJR_t':
            final = fit_gjr_t(is_ret)
            pn = ['omega', 'alpha', 'gamma', 'beta', 'df']
        elif model_name == 'A4f_N':
            final = fit_a4f_normal(is_ret, is_vix2)
            pn = ['theta0', 'theta1', 'omega', 'alpha', 'gamma', 'beta']
        elif model_name == 'A4f_t_2step':
            final = fit_a4f_t_2step(is_ret, is_vix2)
            pn = ['theta0', 'theta1', 'omega', 'alpha', 'gamma', 'beta', 'df']
        elif model_name == 'A4f_t_joint':
            final = fit_a4f_t_joint(is_ret, is_vix2)
            pn = ['theta0', 'theta1', 'omega', 'alpha', 'gamma', 'beta', 'df']

        persistence = final['params'][pn.index('alpha')] + \
                      0.5 * final['params'][pn.index('gamma')] + \
                      final['params'][pn.index('beta')]

        results[model_name] = {
            'qlike': round(ql, 6),
            'params': {n: round(float(v), 6) for n, v in zip(pn, final['params'])},
            'persistence': round(float(persistence), 4),
            'converged': bool(final['converged']),
            'var_es': var_results,
        }
        print(f"  Params: {results[model_name]['params']}")
        print(f"  Persistence: {persistence:.4f}")

    # DM tests
    print("\n" + "=" * 70)
    print("DM Tests (QLIKE loss, Harvey t>3.0)")
    print("=" * 70)
    dm_results = {}
    for i, m1 in enumerate(models):
        for j, m2 in enumerate(models):
            if i >= j:
                continue
            loss1 = r2_oos / forecasts_all[m1] + np.log(forecasts_all[m1])
            loss2 = r2_oos / forecasts_all[m2] + np.log(forecasts_all[m2])
            ts, pv = dm_test(loss1, loss2)
            key = f"{m1}_vs_{m2}"
            dm_results[key] = {'t_stat': round(ts, 3), 'p_val': round(pv, 4)}
            sig = "***" if abs(ts) > 3.0 else ("**" if abs(ts) > 2.0 else "")
            print(f"  {m1} vs {m2}: t={ts:.3f}, p={pv:.4f} {sig}")

    # Summary
    print("\n" + "=" * 70)
    print("Summary Scorecard (2.5% VaR+ES)")
    print("=" * 70)
    for m in models:
        ve = results[m]['var_es']['0.025']
        df_str = f"{results[m]['params'].get('df', 'N/A')}"
        print(f"  {m:20s}: QLIKE={results[m]['qlike']:.6f}  "
              f"VaR viol={ve['violation_rate']:.2f}%  "
              f"Score={ve['scorecard']}  df={df_str}")

    # Save
    output = {
        'experiment_id': 'K1000',
        'title': 'MF-GJR-X(A4f) + Student-t Joint MLE — 5-Model OOS Comparison',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'yfinance (SPY + ^VIX)',
        'data_period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'oos_period': f"{df.index[oos_mask][0].date()} to {df.index[oos_mask][-1].date()}",
        'n_total': len(df),
        'n_oos': int(oos_mask.sum()),
        'window': 2000,
        'refit_every': 63,
        'seed': 42,
        'models': results,
        'dm_tests': dm_results,
        'references': [
            'Engle & Rangel (2008) Spline-GARCH',
            'Patton (2011) QLIKE loss',
            'Kupiec (1995) UC test',
            'Christoffersen (1998) CC test',
            'Engle & Manganelli (2004) DQ test',
            'Acerbi & Szekely (2014) ES backtest',
            'Harvey (2016) t>3.0 threshold',
        ],
    }
    out_path = os.path.join(SCRIPT_DIR, 'k1000_results.json')
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {out_path}")
    return output


if __name__ == '__main__':
    main()
