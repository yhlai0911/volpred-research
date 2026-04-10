"""
K1021: A4f-VIX9D with Joint Student-t Degrees of Freedom Estimation
====================================================================
Data: SPY/QQQ 2005-2026 (yfinance), VIX9D (^VIX9D)
OOS: adjusted to VIX9D availability (~2011+), window=2000, refit/63d
Models:
  M1: A4f-VIX9D-N         (Normal innovations baseline)
  M2: A4f-VIX9D-t-joint   (Student-t, df jointly estimated via MLE)
  M3: A4f-VIX9D-t-fixed5  (Student-t, df=5 fixed)
  M4: A4f-VIX9D-t-fixed8  (Student-t, df=8 fixed)
  M5: A4f-VIX9D-skewt     (Skewed Student-t, df+skew jointly estimated)

Evaluation: QLIKE on r^2, DM test (Harvey t>3.0),
            VaR (1%, 2.5%, 5%), ES (2.5%), Scorecard
Cross-asset: QQQ

Research Questions:
1. Does joint df estimation beat fixed df (grid search)?
2. Is df time-varying across rolling windows?
3. QLIKE impact small but VaR/ES impact large?

References:
- Engle & Rangel (2008): Spline-GARCH
- Patton (2011): QLIKE loss, proxy-robust ranking
- Kupiec (1995), Christoffersen (1998): VaR backtesting
- Engle & Manganelli (2004): DQ test
- Acerbi & Szekely (2014): ES backtesting
- Hansen (1994): Skewed Student-t distribution
- Harvey (2016): t>3.0 threshold for multiple testing
- K988/K1004: A4f-VIX9D prior results

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
from scipy.special import gammaln
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
def load_data(asset='SPY', vix9d_ticker='^VIX9D'):
    """Load asset + VIX9D data."""
    print(f"\nLoading {asset} + {vix9d_ticker}...")
    price = yf.download(asset, start='2004-01-01', end='2026-12-31', progress=False)
    vix9d = yf.download(vix9d_ticker, start='2004-01-01', end='2026-12-31', progress=False)

    for d in [price, vix9d]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    df = pd.DataFrame(index=price.index)
    df['close'] = price['Close']
    df['vix9d'] = vix9d['Close'].reindex(price.index, method='ffill')
    df['ret'] = np.log(df['close'] / df['close'].shift(1))
    df = df.dropna()
    df['ret'] = df['ret'].clip(-0.20, 0.20)
    df['r2'] = df['ret'] ** 2
    df['vix9d2'] = (df['vix9d'] / 100) ** 2

    vix9d_start = df[df['vix9d'].notna()].index[0]
    print(f"  {asset} data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")
    print(f"  VIX9D available from: {vix9d_start.date()}")
    return df

# ============================================================
# 2. Numba-accelerated GARCH recursions
# ============================================================
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

@njit
def skewt_logpdf_sum(returns, h, df, lam):
    """
    Hansen (1994) skewed Student-t log-likelihood.
    lam in (-1, 1) controls skewness.
    """
    T = len(returns)
    # Constants
    c_val = math.lgamma((df + 1.0) / 2.0) - math.lgamma(df / 2.0) - 0.5 * np.log(np.pi * (df - 2.0))
    a_val = 4.0 * lam * np.exp(c_val) * ((df - 2.0) / (df - 1.0))
    b2 = 1.0 + 3.0 * lam * lam - a_val * a_val
    b_val = np.sqrt(b2)

    ll = 0.0
    for t in range(T):
        sigma = np.sqrt(h[t])
        if sigma < 1e-16:
            sigma = 1e-16
        # Standardize
        z = returns[t] / sigma
        # Hansen transform
        y = (b_val * z + a_val)
        if y < 0:
            denom = 1.0 - lam
        else:
            denom = 1.0 + lam
        arg = 1.0 + (1.0 / (df - 2.0)) * (y / denom) ** 2
        ll += c_val + np.log(b_val) - np.log(sigma) - (df + 1.0) / 2.0 * np.log(arg)
    return ll


# ============================================================
# 3. Fitting functions
# ============================================================
def fit_a4f_normal(returns, vix2):
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


def fit_a4f_t_joint(returns, vix2):
    """Fit A4f with Student-t innovations, df jointly estimated."""
    res_n = fit_a4f_normal(returns, vix2)
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (2.1, 100.0)]
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
                           options={'maxiter': 500})
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


def fit_a4f_t_fixed(returns, vix2, fixed_df):
    """Fit A4f with Student-t innovations, df fixed."""
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_recursion(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            ll = t_logpdf_sum(returns, h, fixed_df)
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10
    res_n = fit_a4f_normal(returns, vix2)
    best_res, best_nll = None, 1e10
    for theta1_init in [0.3, 0.8, 2.0]:
        p0 = [res_n['params'][0], theta1_init, res_n['params'][2],
              res_n['params'][3], res_n['params'][4], res_n['params'][5]]
        try:
            res = minimize(obj, p0, method='L-BFGS-B', bounds=bounds,
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
            'converged': best_res.success, 'nll': best_res.fun,
            'df': fixed_df}


def fit_a4f_skewt(returns, vix2):
    """Fit A4f with Hansen (1994) Skewed Student-t, df+skew jointly estimated."""
    res_n = fit_a4f_normal(returns, vix2)
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999),
              (2.1, 100.0), (-0.9, 0.9)]
    def obj(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_recursion(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            ll = skewt_logpdf_sum(returns, h, p[6], p[7])
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        for lam_init in [-0.2, 0.0, 0.2]:
            p0 = list(res_n['params']) + [df_init, lam_init]
            try:
                res = minimize(obj, p0, method='L-BFGS-B', bounds=bounds,
                               options={'maxiter': 500})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except:
                continue
    if best_res is None:
        p0 = list(res_n['params']) + [8.0, -0.1]
        best_res = minimize(obj, p0, method='L-BFGS-B', bounds=bounds)
    h, tau, g = a4f_recursion(best_res.x[0], best_res.x[1], best_res.x[2],
                               best_res.x[3], best_res.x[4], best_res.x[5],
                               returns, vix2)
    return {'params': best_res.x, 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success, 'nll': best_res.fun,
            'df': best_res.x[6], 'skew': best_res.x[7]}


# ============================================================
# 4. OOS forecasting
# ============================================================
def oos_forecast(df, model_name, oos_start_date, window=2000, refit_every=63, fixed_df=None):
    """
    model_name: 'A4f_N', 'A4f_t_joint', 'A4f_t_fixed', 'A4f_skewt'
    """
    oos_start_idx = np.where(df.index >= oos_start_date)[0][0]
    T = len(df)
    forecasts = np.full(T, np.nan)
    df_estimates = np.full(T, np.nan)
    skew_estimates = np.full(T, np.nan)
    returns = df['ret'].values
    vix2_vals = df['vix9d2'].values

    last_fit = None
    last_fit_idx = -refit_every
    g_prev = np.nan

    for t in range(oos_start_idx, T):
        # Refit?
        if t - last_fit_idx >= refit_every or last_fit is None:
            s = max(0, t - window)
            tr = returns[s:t]
            tv = vix2_vals[s:t]

            if model_name == 'A4f_N':
                last_fit = fit_a4f_normal(tr, tv)
            elif model_name == 'A4f_t_joint':
                last_fit = fit_a4f_t_joint(tr, tv)
            elif model_name == 'A4f_t_fixed':
                last_fit = fit_a4f_t_fixed(tr, tv, fixed_df)
            elif model_name == 'A4f_skewt':
                last_fit = fit_a4f_skewt(tr, tv)

            last_fit_idx = t
            g_prev = last_fit.get('g', np.array([1.0]))[-1]

        p = last_fit['params']
        theta0, theta1, omega, alpha, gamma, beta = p[0], p[1], p[2], p[3], p[4], p[5]

        if model_name == 'A4f_t_joint':
            df_estimates[t] = p[6]
        elif model_name == 'A4f_t_fixed':
            df_estimates[t] = fixed_df
        elif model_name == 'A4f_skewt':
            df_estimates[t] = p[6]
            skew_estimates[t] = p[7]

        tau_t = max(theta0 + theta1 * vix2_vals[t-1], 1e-16)
        u_prev = returns[t-1] / np.sqrt(tau_t)
        u2 = u_prev ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        g_t = omega + alpha * u2 + gamma * u2 * ind + beta * g_prev
        g_t = max(g_t, 1e-16)
        forecasts[t] = tau_t * g_t
        g_prev = g_t

    return forecasts, df_estimates, skew_estimates


# ============================================================
# 5. Evaluation functions
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


def compute_var_es_normal(sigma, alpha):
    """VaR and ES from Normal distribution."""
    q = norm.ppf(alpha)
    var_v = sigma * q
    es_v = sigma * (-norm.pdf(q) / alpha)
    return var_v, es_v

def compute_var_es_t(sigma, df_vals, alpha):
    """VaR and ES from Student-t distribution with scale correction."""
    T = len(sigma)
    var_v = np.full(T, np.nan)
    es_v = np.full(T, np.nan)
    for i in range(T):
        s = sigma[i]
        if np.isnan(s) or s <= 0:
            continue
        df = df_vals[i]
        if np.isnan(df) or df <= 2:
            continue
        sf = np.sqrt((df - 2.0) / df)
        q = t_dist.ppf(alpha, df)
        var_v[i] = s * q * sf
        pdf_q = t_dist.pdf(q, df)
        es_v[i] = s * sf * (-pdf_q / alpha) * ((df + q**2) / (df - 1))
    return var_v, es_v

def hansen_skewt_quantile(alpha, df, lam):
    """
    Quantile function for Hansen (1994) skewed Student-t.
    Returns the standardized quantile (zero mean, unit variance).
    """
    c = np.exp(gammaln((df+1)/2) - gammaln(df/2)) / np.sqrt(np.pi*(df-2))
    a = 4 * lam * c * ((df-2)/(df-1))
    b = np.sqrt(1 + 3*lam**2 - a**2)

    threshold = (1 - lam) / 2

    if alpha < threshold:
        # Left regime: F(x) = (1-lam) * t_cdf(...)
        p_adj = alpha / (1 - lam)
        q_t = t_dist.ppf(p_adj, df)
        q = (q_t * (1 - lam) * np.sqrt((df-2)/df) - a) / b
    else:
        # Right regime: F(x) = (1-lam)/2 + (1+lam) * [t_cdf(...) - 0.5]
        p_adj = (alpha - threshold) / (1 + lam) + 0.5
        q_t = t_dist.ppf(p_adj, df)
        q = (q_t * (1 + lam) * np.sqrt((df-2)/df) - a) / b

    return q


def compute_var_es_skewt(sigma, df_vals, skew_vals, alpha):
    """VaR and ES from Hansen (1994) Skewed Student-t using analytical quantile + MC for ES."""
    T = len(sigma)
    var_v = np.full(T, np.nan)
    es_v = np.full(T, np.nan)

    # Pre-compute ES via simulation once per unique (df, lam) pair
    # Cache (rounded) to avoid redundant simulation
    es_cache = {}
    rng = np.random.default_rng(42)
    n_sim = 100000

    for i in range(T):
        s = sigma[i]
        if np.isnan(s) or s <= 0:
            continue
        df = df_vals[i]
        lam = skew_vals[i]
        if np.isnan(df) or df <= 2 or np.isnan(lam):
            continue

        # Analytical VaR quantile
        q = hansen_skewt_quantile(alpha, df, lam)
        var_v[i] = s * q

        # ES via cached simulation
        cache_key = (round(df, 1), round(lam, 2))
        if cache_key not in es_cache:
            df_r, lam_r = cache_key
            c = np.exp(gammaln((df_r+1)/2) - gammaln(df_r/2)) / np.sqrt(np.pi*(df_r-2))
            a = 4 * lam_r * c * ((df_r-2)/(df_r-1))
            b_val = np.sqrt(1 + 3*lam_r**2 - a**2)
            sf = np.sqrt((df_r-2)/df_r)

            # Generate skew-t draws via two-piece construction
            u = rng.random(n_sim)
            threshold_val = (1 - lam_r) / 2
            t_draws = np.abs(rng.standard_t(df_r, n_sim))
            draws = np.where(
                u < threshold_val,
                (-t_draws * (1 - lam_r) * sf - a) / b_val,
                (t_draws * (1 + lam_r) * sf - a) / b_val
            )
            q_std = hansen_skewt_quantile(alpha, df_r, lam_r)
            tail = draws[draws <= q_std]
            if len(tail) > 0:
                es_cache[cache_key] = np.mean(tail)
            else:
                es_cache[cache_key] = q_std * 1.5  # fallback

        es_v[i] = s * es_cache[cache_key]

    return var_v, es_v


def var_es_evaluation(returns_arr, var_v, es_v, alpha):
    """Evaluate VaR and ES given pre-computed values."""
    mask = ~np.isnan(var_v) & ~np.isnan(es_v)
    ret = returns_arr[mask]
    vv = var_v[mask]
    ev = es_v[mask]
    sig = np.sqrt(vv**2)  # placeholder for sigma in DQ

    violations = (ret < vv).astype(int)
    T = len(ret)
    viol_rate = np.sum(violations) / T

    uc_stat, uc_p = kupiec_test(violations, T, alpha)
    cc_stat, cc_p = christoffersen_cc_test(violations)
    dq_stat, dq_p = dq_test(violations, alpha, ret, np.abs(vv))

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
        'UC_stat': round(float(uc_stat), 3), 'UC_p': round(float(uc_p), 4),
        'CC_stat': round(float(cc_stat), 3), 'CC_p': round(float(cc_p), 4),
        'DQ_stat': round(float(dq_stat), 3), 'DQ_p': round(float(dq_p), 4),
        'Basel': basel,
        'ES_Z1': round(float(es_z1), 4) if es_z1 is not None else None,
        'ES_Z1_p': round(float(es_z1_p), 4) if es_z1_p is not None else None,
        'ES_Z2': round(float(es_z2), 4) if es_z2 is not None else None,
        'ES_Z2_p': round(float(es_z2_p), 4) if es_z2_p is not None else None,
        'scorecard': scorecard,
    }


# ============================================================
# 6. Run one asset
# ============================================================
def run_asset(asset, vix9d_ticker, oos_start_date):
    print(f"\n{'='*70}")
    print(f"Asset: {asset}")
    print(f"{'='*70}")

    df = load_data(asset, vix9d_ticker)

    # Determine OOS start
    vix9d_first = df[df['vix9d'].notna()].index[0]
    min_oos_idx = 2000
    desired_oos_idx = np.where(df.index >= oos_start_date)[0]
    if len(desired_oos_idx) == 0:
        print(f"  ERROR: OOS start {oos_start_date} is beyond data range")
        return None
    desired_oos_idx = desired_oos_idx[0]
    vix9d_idx = np.where(df.index >= vix9d_first)[0][0]
    actual_oos_start = max(desired_oos_idx, min_oos_idx, vix9d_idx + 500)
    actual_oos_date = df.index[actual_oos_start].strftime('%Y-%m-%d')
    print(f"  Adjusted OOS start: {actual_oos_date} (need VIX9D + window)")

    # Model configurations
    model_configs = [
        ('A4f-VIX9D-N',        'A4f_N',       None),
        ('A4f-VIX9D-t-joint',  'A4f_t_joint', None),
        ('A4f-VIX9D-t-fixed5', 'A4f_t_fixed', 5.0),
        ('A4f-VIX9D-t-fixed8', 'A4f_t_fixed', 8.0),
        ('A4f-VIX9D-skewt',    'A4f_skewt',   None),
    ]

    oos_mask = np.array(df.index >= actual_oos_date)
    returns_oos = df['ret'].values[oos_mask]
    r2_oos = df['r2'].values[oos_mask]
    n_oos = int(oos_mask.sum())
    oos_dates = df.index[oos_mask]
    print(f"  OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()}, N={n_oos}")

    results = {}
    forecasts_all = {}
    df_all = {}
    skew_all = {}

    for label, model_type, fixed_df in model_configs:
        print(f"\n--- {label} ---")
        t0 = time.time()
        h_forecast, df_est, skew_est = oos_forecast(
            df, model_type, actual_oos_date,
            window=2000, refit_every=63, fixed_df=fixed_df
        )
        elapsed = time.time() - t0
        print(f"  Elapsed: {elapsed:.1f}s")

        h_oos = h_forecast[oos_mask]
        df_oos = df_est[oos_mask]
        skew_oos = skew_est[oos_mask]
        sigma_oos = np.sqrt(np.maximum(h_oos, 1e-16))
        forecasts_all[label] = h_oos
        df_all[label] = df_oos
        skew_all[label] = skew_oos

        ql = qlike(r2_oos, h_oos)
        print(f"  QLIKE = {ql:.6f}")

        # Compute VaR/ES based on distribution
        var_results = {}
        for alpha in [0.01, 0.025, 0.05]:
            if model_type == 'A4f_N':
                var_v, es_v = compute_var_es_normal(sigma_oos, alpha)
            elif model_type == 'A4f_skewt':
                var_v, es_v = compute_var_es_skewt(sigma_oos, df_oos, skew_oos, alpha)
            else:
                var_v, es_v = compute_var_es_t(sigma_oos, df_oos, alpha)

            ve = var_es_evaluation(returns_oos, var_v, es_v, alpha)
            var_results[str(alpha)] = ve
            print(f"  VaR {alpha*100:.1f}%: viol={ve['violation_rate']:.2f}% "
                  f"(expect {alpha*100:.1f}%), score={ve['scorecard']}")

        # Mean df and skew across OOS
        valid_df = df_oos[~np.isnan(df_oos)]
        mean_df = float(np.mean(valid_df)) if len(valid_df) > 0 else None
        std_df = float(np.std(valid_df)) if len(valid_df) > 0 else None

        valid_skew = skew_oos[~np.isnan(skew_oos)]
        mean_skew = float(np.mean(valid_skew)) if len(valid_skew) > 0 else None

        model_result = {
            'qlike': round(float(ql), 6),
            'var_es': var_results,
            'mean_df': round(mean_df, 3) if mean_df is not None else None,
            'std_df': round(std_df, 3) if std_df is not None else None,
            'mean_skew': round(mean_skew, 4) if mean_skew is not None else None,
        }
        results[label] = model_result
        print(f"  Mean df = {mean_df}, std df = {std_df}")
        if mean_skew is not None:
            print(f"  Mean skew (lambda) = {mean_skew:.4f}")

    # DM tests
    print("\n--- DM Tests (QLIKE losses) ---")
    ql_losses = {}
    for label in forecasts_all:
        h = forecasts_all[label]
        mask = ~np.isnan(h) & (h > 0)
        losses = np.full(len(r2_oos), np.nan)
        losses[mask] = r2_oos[mask] / h[mask] + np.log(h[mask])
        ql_losses[label] = losses

    dm_results = {}
    # Key comparisons
    comparisons = [
        ('A4f-VIX9D-t-joint', 'A4f-VIX9D-N', 't-joint vs Normal'),
        ('A4f-VIX9D-skewt', 'A4f-VIX9D-N', 'skewt vs Normal'),
        ('A4f-VIX9D-skewt', 'A4f-VIX9D-t-joint', 'skewt vs t-joint'),
        ('A4f-VIX9D-t-joint', 'A4f-VIX9D-t-fixed5', 't-joint vs t-fixed5'),
        ('A4f-VIX9D-t-joint', 'A4f-VIX9D-t-fixed8', 't-joint vs t-fixed8'),
        ('A4f-VIX9D-t-fixed5', 'A4f-VIX9D-t-fixed8', 't-fixed5 vs t-fixed8'),
    ]
    for m1, m2, desc in comparisons:
        t_stat, p_val = dm_test(ql_losses[m1], ql_losses[m2])
        sig = "***" if abs(t_stat) > 3.0 else "**" if abs(t_stat) > 2.0 else "*" if abs(t_stat) > 1.64 else ""
        print(f"  {desc}: t={t_stat:.3f}, p={p_val:.4f} {sig}")
        dm_results[desc] = {'t_stat': round(float(t_stat), 3),
                            'p_val': round(float(p_val), 4),
                            'significant_harvey': abs(t_stat) > 3.0}

    results['dm_tests'] = dm_results
    results['oos_period'] = {'start': str(oos_dates[0].date()),
                             'end': str(oos_dates[-1].date()),
                             'n': n_oos}

    # Collect df evolution for joint model
    df_evolution = {}
    for label in ['A4f-VIX9D-t-joint', 'A4f-VIX9D-skewt']:
        valid = df_all[label]
        vals = valid[~np.isnan(valid)]
        if len(vals) > 0:
            df_evolution[label] = {
                'dates': [str(d.date()) for d in oos_dates[~np.isnan(valid)]],
                'df_values': [round(float(v), 2) for v in vals]
            }

    # Collect skew evolution
    skew_evolution = {}
    for label in ['A4f-VIX9D-skewt']:
        valid = skew_all[label]
        vals = valid[~np.isnan(valid)]
        if len(vals) > 0:
            skew_evolution[label] = {
                'dates': [str(d.date()) for d in oos_dates[~np.isnan(valid)]],
                'skew_values': [round(float(v), 4) for v in vals]
            }

    # VaR violation timeline data
    violation_timeline = {}
    for label in forecasts_all:
        h = forecasts_all[label]
        sigma = np.sqrt(np.maximum(h, 1e-16))
        df_oos_l = df_all[label]
        skew_oos_l = skew_all[label]

        if label == 'A4f-VIX9D-N':
            var_v, _ = compute_var_es_normal(sigma, 0.025)
        elif label == 'A4f-VIX9D-skewt':
            var_v, _ = compute_var_es_skewt(sigma, df_oos_l, skew_oos_l, 0.025)
        else:
            var_v, _ = compute_var_es_t(sigma, df_oos_l, 0.025)

        viols = (returns_oos < var_v).astype(int)
        viol_dates = [str(d.date()) for d, v in zip(oos_dates, viols) if v == 1 and not np.isnan(var_v[list(oos_dates).index(d)])]
        violation_timeline[label] = viol_dates

    return results, df_evolution, skew_evolution, violation_timeline, oos_dates


# ============================================================
# 7. Plotting
# ============================================================
def plot_df_evolution(df_evolution, oos_dates, asset, script_dir):
    """Plot 1: df estimate evolution across rolling windows."""
    fig, ax = plt.subplots(figsize=(12, 5))

    for label, data in df_evolution.items():
        dates = pd.to_datetime(data['dates'])
        vals = data['df_values']
        # Deduplicate (step function from rolling)
        ax.plot(dates, vals, label=label, alpha=0.8, linewidth=1.2)

    ax.axhline(y=5.0, color='red', linestyle='--', alpha=0.5, label='df=5 (fixed)')
    ax.axhline(y=8.0, color='green', linestyle='--', alpha=0.5, label='df=8 (fixed)')
    ax.set_xlabel('Date', fontsize=11)
    ax.set_ylabel('Degrees of Freedom (df)', fontsize=11)
    ax.set_title(f'K1021: Student-t df Evolution Across Rolling Windows ({asset})', fontsize=13)
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    path = os.path.join(script_dir, f'k1021_df_evolution_{asset.lower()}.png')
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved: {path}")
    return path


def plot_var_scorecard(results_by_asset, script_dir):
    """Plot 2: VaR scorecard heatmap (models x tests)."""
    # Build scorecard matrix for SPY
    models = ['A4f-VIX9D-N', 'A4f-VIX9D-t-joint', 'A4f-VIX9D-t-fixed5',
              'A4f-VIX9D-t-fixed8', 'A4f-VIX9D-skewt']
    alphas = ['0.01', '0.025', '0.05']
    tests = ['UC', 'CC', 'DQ', 'Basel']

    spy_results = results_by_asset.get('SPY', {})

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    for ax_idx, alpha_key in enumerate(alphas):
        alpha_label = {'0.01': '1%', '0.025': '2.5%', '0.05': '5%'}[alpha_key]
        matrix = np.zeros((len(models), len(tests)))
        for i, model in enumerate(models):
            if model in spy_results:
                ve = spy_results[model].get('var_es', {}).get(alpha_key, {})
                if ve:
                    matrix[i, 0] = 1 if ve.get('UC_p', 0) > 0.05 else 0
                    matrix[i, 1] = 1 if ve.get('CC_p', 0) > 0.05 else 0
                    matrix[i, 2] = 1 if ve.get('DQ_p', 0) > 0.05 else 0
                    matrix[i, 3] = 1 if ve.get('Basel', 'RED') == 'GREEN' else 0

        ax = axes[ax_idx]
        im = ax.imshow(matrix, cmap='RdYlGn', vmin=0, vmax=1, aspect='auto')
        ax.set_xticks(range(len(tests)))
        ax.set_xticklabels(tests, fontsize=9)
        ax.set_yticks(range(len(models)))
        short_names = ['Normal', 't-joint', 't-fix5', 't-fix8', 'skew-t']
        ax.set_yticklabels(short_names, fontsize=9)
        ax.set_title(f'VaR {alpha_label}', fontsize=11)

        for i in range(len(models)):
            for j in range(len(tests)):
                text = 'PASS' if matrix[i, j] == 1 else 'FAIL'
                color = 'white' if matrix[i, j] == 0 else 'black'
                ax.text(j, i, text, ha='center', va='center', fontsize=8,
                        fontweight='bold', color=color)

    plt.suptitle('K1021: VaR Scorecard - SPY (Models x Tests)', fontsize=13, y=1.02)
    plt.tight_layout()
    path = os.path.join(script_dir, 'k1021_var_scorecard.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {path}")
    return path


def plot_violation_timeline(violation_timeline, oos_dates, returns_oos, asset, script_dir):
    """Plot 3: VaR violation timeline comparison."""
    fig, ax = plt.subplots(figsize=(14, 6))

    # Plot returns
    ax.plot(oos_dates, returns_oos, color='gray', alpha=0.3, linewidth=0.5, label='Returns')

    models_to_plot = ['A4f-VIX9D-N', 'A4f-VIX9D-t-joint', 'A4f-VIX9D-skewt']
    colors = {'A4f-VIX9D-N': 'red', 'A4f-VIX9D-t-joint': 'blue', 'A4f-VIX9D-skewt': 'green'}
    markers = {'A4f-VIX9D-N': 'x', 'A4f-VIX9D-t-joint': 'o', 'A4f-VIX9D-skewt': 's'}
    offsets = {'A4f-VIX9D-N': -0.003, 'A4f-VIX9D-t-joint': 0.0, 'A4f-VIX9D-skewt': 0.003}

    for model in models_to_plot:
        if model in violation_timeline:
            viol_dates = pd.to_datetime(violation_timeline[model])
            y_pos = np.full(len(viol_dates), -0.06 + offsets[model])
            short = model.replace('A4f-VIX9D-', '')
            ax.scatter(viol_dates, y_pos, marker=markers[model], color=colors[model],
                      s=30, alpha=0.7, label=f'{short} violations ({len(viol_dates)})',
                      zorder=5)

    ax.set_xlabel('Date', fontsize=11)
    ax.set_ylabel('Return', fontsize=11)
    ax.set_title(f'K1021: VaR 2.5% Violation Timeline ({asset})', fontsize=13)
    ax.legend(loc='lower left', fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color='black', linewidth=0.5)
    plt.tight_layout()
    path = os.path.join(script_dir, f'k1021_violation_timeline_{asset.lower()}.png')
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved: {path}")
    return path


def plot_qlike_comparison(results_by_asset, script_dir):
    """Plot 4 (bonus): QLIKE bar comparison across models."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    models = ['A4f-VIX9D-N', 'A4f-VIX9D-t-joint', 'A4f-VIX9D-t-fixed5',
              'A4f-VIX9D-t-fixed8', 'A4f-VIX9D-skewt']
    short_names = ['Normal', 't-joint', 't-fix5', 't-fix8', 'skew-t']
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7']

    for ax_idx, asset in enumerate(['SPY', 'QQQ']):
        if asset not in results_by_asset:
            continue
        res = results_by_asset[asset]
        qlikes = [res[m]['qlike'] for m in models if m in res]
        ax = axes[ax_idx]
        bars = ax.bar(range(len(qlikes)), qlikes, color=colors[:len(qlikes)], edgecolor='black', linewidth=0.5)
        ax.set_xticks(range(len(qlikes)))
        ax.set_xticklabels(short_names[:len(qlikes)], fontsize=9, rotation=15)
        ax.set_ylabel('QLIKE', fontsize=11)
        ax.set_title(f'{asset}', fontsize=12)
        ax.grid(True, axis='y', alpha=0.3)

        # Add value labels
        for bar, val in zip(bars, qlikes):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                    f'{val:.4f}', ha='center', va='bottom', fontsize=8)

    plt.suptitle('K1021: QLIKE Comparison (lower = better)', fontsize=13)
    plt.tight_layout()
    path = os.path.join(script_dir, 'k1021_qlike_comparison.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {path}")
    return path


# ============================================================
# 8. Main
# ============================================================
def main():
    print("=" * 70)
    print("K1021: A4f-VIX9D with Joint Student-t df Estimation")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Seed: 42")

    results_all = {}
    df_evol_all = {}
    skew_evol_all = {}
    viol_timeline_all = {}

    for asset in ['SPY', 'QQQ']:
        out = run_asset(asset, '^VIX9D', '2019-01-01')
        if out is not None:
            results, df_evolution, skew_evolution, viol_timeline, oos_dates = out
            results_all[asset] = results
            df_evol_all[asset] = df_evolution
            skew_evol_all[asset] = skew_evolution
            viol_timeline_all[asset] = viol_timeline

    # Summary table
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    models = ['A4f-VIX9D-N', 'A4f-VIX9D-t-joint', 'A4f-VIX9D-t-fixed5',
              'A4f-VIX9D-t-fixed8', 'A4f-VIX9D-skewt']

    for asset in results_all:
        print(f"\n--- {asset} ---")
        print(f"{'Model':<22} {'QLIKE':>10} {'df':>8} {'skew':>8} "
              f"{'VaR1%':>8} {'VaR2.5%':>8} {'VaR5%':>8}")
        print("-" * 80)
        res = results_all[asset]
        for m in models:
            if m in res:
                r = res[m]
                ql = f"{r['qlike']:.4f}"
                df_str = f"{r['mean_df']:.1f}" if r.get('mean_df') else "N/A"
                sk_str = f"{r['mean_skew']:.3f}" if r.get('mean_skew') else "N/A"
                v1 = res[m]['var_es']['0.01']['scorecard']
                v25 = res[m]['var_es']['0.025']['scorecard']
                v5 = res[m]['var_es']['0.05']['scorecard']
                print(f"{m:<22} {ql:>10} {df_str:>8} {sk_str:>8} "
                      f"{v1:>8} {v25:>8} {v5:>8}")

    # Plots
    print("\n--- Generating Plots ---")
    plot_paths = []

    # Plot 1: df evolution for SPY
    if 'SPY' in df_evol_all:
        p = plot_df_evolution(df_evol_all['SPY'], None, 'SPY', SCRIPT_DIR)
        plot_paths.append(p)

    # Plot 2: VaR scorecard
    p = plot_var_scorecard(results_all, SCRIPT_DIR)
    plot_paths.append(p)

    # Plot 3: Violation timeline (need OOS data)
    if 'SPY' in viol_timeline_all:
        # Re-run to get returns for plot (fetch fresh)
        df_spy = load_data('SPY', '^VIX9D')
        vix9d_first = df_spy[df_spy['vix9d'].notna()].index[0]
        min_oos_idx = 2000
        desired = np.where(df_spy.index >= '2019-01-01')[0][0]
        vix9d_idx = np.where(df_spy.index >= vix9d_first)[0][0]
        actual = max(desired, min_oos_idx, vix9d_idx + 500)
        actual_date = df_spy.index[actual].strftime('%Y-%m-%d')
        oos_mask = np.array(df_spy.index >= actual_date)
        returns_oos = df_spy['ret'].values[oos_mask]
        oos_dates = df_spy.index[oos_mask]
        p = plot_violation_timeline(viol_timeline_all['SPY'], oos_dates, returns_oos,
                                    'SPY', SCRIPT_DIR)
        plot_paths.append(p)

    # Plot 4: QLIKE comparison
    p = plot_qlike_comparison(results_all, SCRIPT_DIR)
    plot_paths.append(p)

    # Save results
    output = {
        'experiment': 'K1021',
        'title': 'A4f-VIX9D with Joint Student-t df Estimation',
        'timestamp': datetime.now().isoformat(),
        'seed': 42,
        'methodology': {
            'models': {
                'M1': 'A4f-VIX9D-N (Normal)',
                'M2': 'A4f-VIX9D-t-joint (Student-t, df jointly estimated)',
                'M3': 'A4f-VIX9D-t-fixed5 (Student-t, df=5 fixed)',
                'M4': 'A4f-VIX9D-t-fixed8 (Student-t, df=8 fixed)',
                'M5': 'A4f-VIX9D-skewt (Hansen 1994 skewed Student-t)',
            },
            'a4f_spec': 'sigma2 = tau_t * g_t; tau_t = theta0 + theta1*VIX9D2; g_t = omega + alpha*u2 + gamma*u2*I + beta*g',
            'window': 2000,
            'refit_every': 63,
            'data_source': 'yfinance',
            'assets': ['SPY', 'QQQ'],
            'oos_target': '2019-2026',
        },
        'references': [
            'Engle & Rangel (2008) Spline-GARCH',
            'Patton (2011) QLIKE',
            'Hansen (1994) Skewed Student-t',
            'Kupiec (1995) VaR LR test',
            'Christoffersen (1998) conditional coverage',
            'Engle & Manganelli (2004) DQ test',
            'Acerbi & Szekely (2014) ES backtest',
            'Harvey (2016) t>3.0',
        ],
        'results': results_all,
        'plots': [os.path.basename(p) for p in plot_paths],
    }

    results_path = os.path.join(SCRIPT_DIR, 'k1021_results.json')
    with open(results_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to: {results_path}")


if __name__ == '__main__':
    main()
