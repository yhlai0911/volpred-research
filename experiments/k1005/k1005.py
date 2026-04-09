"""
K1005: Proxy-Reliance Conformal VaR — Conformal vs Parametric VaR for GJR and A4f
==================================================================================
Data: SPY 2005-2026 (yfinance), OOS: 2019-2026, window=2000, refit/63d
Models: GJR_t, A4f_t_joint (best from K1000)
VaR methods: Parametric-t, Split Conformal, Adaptive Conformal (ACI)
Conformal calibration window W=500
Evaluation: violation rate, UC, CC, DQ, Basel, ES (Acerbi-Szekely), scorecard

References:
- arXiv:2603.22569 (2026): Conformal prediction for VaR with proxy-reliance control
- Gibbs & Candès (2021): Adaptive conformal inference (ACI)
- Vovk et al. (2005): Algorithmic learning in a random world (conformal prediction)
- Patton (2011): QLIKE loss, proxy-robust ranking
- Kupiec (1995), Christoffersen (1998): VaR backtesting
- Acerbi & Szekely (2014): ES backtesting
- Harvey (2016): t>3.0 threshold for multiple testing
- Engle & Rangel (2008): Spline-GARCH (A4f foundation)

Proxy-reliance question: Parametric VaR depends on distributional assumption (Student-t).
Conformal VaR only needs exchangeability of standardized residuals — distribution-free.
If conformal VaR matches or beats parametric, the distributional assumption is unnecessary.
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
import time
import math
from datetime import datetime
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import t as t_dist, chi2, norm
import yfinance as yf
from numba import njit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

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
    # First get normal-distribution A4f for initialization
    bounds_n = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
                (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]

    @njit
    def _a4f_nll_normal(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
        h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2)
        T = len(returns)
        ll = 0.0
        for t in range(T):
            ll += np.log(h[t]) + returns[t]**2 / h[t]
        return 0.5 * ll

    def obj_n(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            v = _a4f_nll_normal(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10

    best_res_n, best_nll_n = None, 1e10
    for theta1_init in [0.3, 0.8, 2.0]:
        for omega_init in [0.02, 0.08]:
            x0 = [1e-5, theta1_init, omega_init, 0.04, 0.06, 0.90]
            try:
                res = minimize(obj_n, x0, method='L-BFGS-B', bounds=bounds_n,
                               options={'maxiter': 300})
                if res.fun < best_nll_n:
                    best_nll_n = res.fun
                    best_res_n = res
            except:
                continue
    if best_res_n is None:
        x0 = [1e-5, 0.5, 0.05, 0.04, 0.06, 0.90]
        best_res_n = minimize(obj_n, x0, method='L-BFGS-B', bounds=bounds_n)

    # Joint t
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
        p0 = list(best_res_n.x) + [df_init]
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
# 4. OOS forecasting with standardized residuals
# ============================================================
def oos_forecast(df, model_name, window=2000, refit_every=63):
    """Returns: h_forecast, df_estimates, std_residuals (all length T)."""
    oos_start_idx = np.where(df.index >= '2019-01-01')[0][0]
    T = len(df)
    forecasts = np.full(T, np.nan)
    df_estimates = np.full(T, np.nan)
    std_residuals = np.full(T, np.nan)
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

            if model_name == 'GJR_t':
                last_fit = fit_gjr_t(tr)
            elif model_name == 'A4f_t_joint':
                last_fit = fit_a4f_t_joint(tr, tv)

            last_fit_idx = t
            h_prev = last_fit['h'][-1]
            g_prev = last_fit.get('g', np.array([1.0]))[-1]

            # Compute in-sample standardized residuals for conformal calibration
            h_is = last_fit['h']
            tr_aligned = tr[-len(h_is):]
            sigma_is = np.sqrt(h_is)
            z_is = tr_aligned / sigma_is
            last_fit['z_is'] = z_is  # store for conformal

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
        else:  # A4f_t_joint
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

        # Standardized residual for this period (realized)
        if t > 0 and forecasts[t] > 0:
            std_residuals[t] = returns[t] / np.sqrt(forecasts[t])

    return forecasts, df_estimates, std_residuals

# ============================================================
# 5. VaR Methods
# ============================================================
def compute_parametric_var_es(sigma, df_vals, alpha):
    """Parametric VaR/ES from sigma and Student-t df."""
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


def compute_conformal_var_es(sigma, returns, h_forecast, alpha, W=500):
    """Split Conformal VaR/ES using sliding window of standardized residuals.

    VaR_t = sigma_t * quantile(z_{t-W:t-1}, alpha)
    ES_t = sigma_t * mean(z_{z < quantile})
    Uses only past residuals (no lookahead).
    """
    T = len(sigma)
    var_v = np.full(T, np.nan)
    es_v = np.full(T, np.nan)

    # Pre-compute all standardized residuals (only past data used at each t)
    z_all = np.full(T, np.nan)
    for t in range(T):
        if h_forecast[t] > 0 and not np.isnan(h_forecast[t]):
            z_all[t] = returns[t] / np.sqrt(h_forecast[t])

    for t in range(W, T):
        s = sigma[t]
        if np.isnan(s) or s <= 0:
            continue

        # Calibration set: standardized residuals from [t-W, t-1]
        z_cal = z_all[t-W:t]
        valid = ~np.isnan(z_cal)
        if np.sum(valid) < 50:
            continue
        z_valid = z_cal[valid]

        # Conformal quantile
        q_alpha = np.quantile(z_valid, alpha)
        var_v[t] = s * q_alpha  # negative number (left tail)

        # ES: mean of z below the quantile, scaled by sigma
        z_below = z_valid[z_valid <= q_alpha]
        if len(z_below) > 0:
            es_v[t] = s * np.mean(z_below)
        else:
            es_v[t] = var_v[t]  # conservative fallback

    return var_v, es_v


def compute_aci_var_es(sigma, returns, h_forecast, alpha, W=500, gamma_aci=0.01):
    """Adaptive Conformal Inference (ACI) VaR/ES.

    Gibbs & Candès (2021): Dynamically adjust alpha_t to achieve target coverage.
    alpha_t+1 = alpha + gamma * (I(r_t < VaR_t) - alpha)

    This makes the coverage self-correcting: if too many violations, alpha_t
    increases (more conservative); if too few, alpha_t decreases.
    """
    T = len(sigma)
    var_v = np.full(T, np.nan)
    es_v = np.full(T, np.nan)

    z_all = np.full(T, np.nan)
    for t in range(T):
        if h_forecast[t] > 0 and not np.isnan(h_forecast[t]):
            z_all[t] = returns[t] / np.sqrt(h_forecast[t])

    alpha_t = alpha  # initial adaptive alpha

    for t in range(W, T):
        s = sigma[t]
        if np.isnan(s) or s <= 0:
            continue

        z_cal = z_all[t-W:t]
        valid = ~np.isnan(z_cal)
        if np.sum(valid) < 50:
            continue
        z_valid = z_cal[valid]

        # Use adaptive alpha_t, clipped to valid range
        alpha_eff = np.clip(alpha_t, 0.001, 0.20)

        q_alpha = np.quantile(z_valid, alpha_eff)
        var_v[t] = s * q_alpha

        z_below = z_valid[z_valid <= q_alpha]
        if len(z_below) > 0:
            es_v[t] = s * np.mean(z_below)
        else:
            es_v[t] = var_v[t]

        # Update adaptive alpha based on realized violation
        # Gibbs & Candes (2021): alpha_{t+1} = alpha_t + gamma * (alpha - I(r_t < VaR_t))
        # When violation occurs (I=1), alpha_t decreases -> more conservative
        # When no violation (I=0), alpha_t increases -> less conservative
        if not np.isnan(returns[t]):
            violation = 1.0 if returns[t] < var_v[t] else 0.0
            alpha_t = alpha_t + gamma_aci * (alpha - violation)

    return var_v, es_v

# ============================================================
# 6. Evaluation functions
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


def evaluate_var(returns_arr, var_v, es_v, sigma, alpha, label=""):
    """Full VaR/ES evaluation with scorecard."""
    mask = ~np.isnan(var_v) & ~np.isnan(returns_arr)
    ret = returns_arr[mask]
    vv = var_v[mask]
    ev = es_v[mask]
    sig = sigma[mask]
    violations = (ret < vv).astype(int)
    T = len(ret)
    if T == 0:
        return {'error': 'no valid data'}

    viol_rate = np.sum(violations) / T
    uc_stat, uc_p = kupiec_test(violations, T, alpha)
    cc_stat, cc_p = christoffersen_cc_test(violations)
    dq_stat, dq_p = dq_test(violations, alpha, ret, sig)

    es_z1 = es_z1_p = es_z2 = es_z2_p = None
    if abs(alpha - 0.025) < 0.001:
        es_z1, es_z1_p = acerbi_szekely_z1(ret, vv, ev, alpha)
        es_z2, es_z2_p = acerbi_szekely_z2(ret, ev, alpha)

    expected = T * alpha
    n_viol = np.sum(violations)
    if n_viol <= expected * 1.5:
        basel = "GREEN"
    elif n_viol <= expected * 2.0:
        basel = "YELLOW"
    else:
        basel = "RED"

    n_pass = sum([uc_p > 0.05, cc_p > 0.05, dq_p > 0.05, basel == "GREEN"])
    if abs(alpha - 0.025) < 0.001 and es_z1_p is not None:
        n_pass_total = n_pass + sum([es_z1_p > 0.05, es_z2_p > 0.05])
        scorecard = f"{n_pass_total}/6"
    else:
        scorecard = f"{n_pass}/4"

    result = {
        'alpha': alpha, 'T': T,
        'violations': int(n_viol),
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
    return result


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

# ============================================================
# 7. Plotting
# ============================================================
def plot_scorecard_comparison(results, save_path):
    """Bar chart comparing scorecards across methods."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 6))
    alphas = [0.01, 0.025, 0.05]
    alpha_labels = ['VaR 1%', 'VaR 2.5%', 'VaR 5%']

    for ax_idx, (alpha_val, alpha_label) in enumerate(zip(alphas, alpha_labels)):
        alpha_key = str(alpha_val)
        methods = []
        scores = []
        colors = []
        color_map = {
            'GJR_t': '#1f77b4',
            'A4f_t_joint': '#ff7f0e',
        }

        for model_name in ['GJR_t', 'A4f_t_joint']:
            for var_method in ['parametric', 'conformal', 'aci']:
                key = f"{model_name}_{var_method}"
                if key in results and alpha_key in results[key]:
                    sc = results[key][alpha_key]['scorecard']
                    num, denom = sc.split('/')
                    score_pct = int(num) / int(denom) * 100
                    methods.append(f"{model_name.replace('_t_joint','_t').replace('_t','')}\n{var_method}")
                    scores.append(score_pct)
                    base_color = color_map.get(model_name, '#333')
                    if var_method == 'parametric':
                        colors.append(base_color)
                    elif var_method == 'conformal':
                        # lighter
                        import matplotlib.colors as mcolors
                        rgb = mcolors.to_rgb(base_color)
                        lighter = tuple(min(1, c + 0.3) for c in rgb)
                        colors.append(lighter)
                    else:
                        import matplotlib.colors as mcolors
                        rgb = mcolors.to_rgb(base_color)
                        darker = tuple(max(0, c - 0.15) for c in rgb)
                        colors.append(darker)

        bars = ax_idx
        ax = axes[ax_idx]
        x = np.arange(len(methods))
        ax.bar(x, scores, color=colors, edgecolor='black', linewidth=0.5)
        ax.set_xticks(x)
        ax.set_xticklabels(methods, fontsize=7, rotation=45, ha='right')
        ax.set_ylabel('Scorecard Pass Rate (%)')
        ax.set_title(alpha_label, fontsize=12, fontweight='bold')
        ax.set_ylim(0, 110)
        ax.axhline(y=100, color='green', linestyle='--', alpha=0.5, label='Perfect')
        ax.axhline(y=66.7, color='orange', linestyle='--', alpha=0.5, label='4/6')

    plt.suptitle('K1005: Conformal vs Parametric VaR — Scorecard Comparison',
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")


def plot_violation_rates(results, save_path):
    """Violation rate comparison across methods."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 6))
    alphas = [0.01, 0.025, 0.05]
    alpha_labels = ['VaR 1%', 'VaR 2.5%', 'VaR 5%']

    for ax_idx, (alpha_val, alpha_label) in enumerate(zip(alphas, alpha_labels)):
        alpha_key = str(alpha_val)
        methods = []
        viol_rates = []
        colors = []

        for model_name in ['GJR_t', 'A4f_t_joint']:
            for var_method in ['parametric', 'conformal', 'aci']:
                key = f"{model_name}_{var_method}"
                if key in results and alpha_key in results[key]:
                    vr = results[key][alpha_key]['violation_rate']
                    label = f"{model_name.replace('_t_joint','_t').replace('_t','')}\n{var_method}"
                    methods.append(label)
                    viol_rates.append(vr)
                    if var_method == 'parametric':
                        colors.append('#1f77b4' if 'GJR' in model_name else '#ff7f0e')
                    elif var_method == 'conformal':
                        colors.append('#aec7e8' if 'GJR' in model_name else '#ffbb78')
                    else:
                        colors.append('#08306b' if 'GJR' in model_name else '#d95f02')

        ax = axes[ax_idx]
        x = np.arange(len(methods))
        ax.bar(x, viol_rates, color=colors, edgecolor='black', linewidth=0.5)
        ax.axhline(y=alpha_val*100, color='red', linestyle='--', linewidth=2,
                   label=f'Target {alpha_val*100:.1f}%')
        ax.set_xticks(x)
        ax.set_xticklabels(methods, fontsize=7, rotation=45, ha='right')
        ax.set_ylabel('Violation Rate (%)')
        ax.set_title(alpha_label, fontsize=12, fontweight='bold')
        ax.legend(fontsize=8)

    plt.suptitle('K1005: Violation Rates — Conformal vs Parametric',
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")

# ============================================================
# 8. Main
# ============================================================
def main():
    print("=" * 70)
    print("K1005: Proxy-Reliance Conformal VaR")
    print("Conformal vs Parametric VaR for GJR_t and A4f_t_joint")
    print("=" * 70)

    # Warm up numba
    _dummy = np.random.randn(100)
    _ = gjr_h(1e-6, 0.05, 0.05, 0.9, _dummy)
    _ = t_logpdf_sum(_dummy, np.abs(_dummy) + 1e-6, 5.0)
    _dv = np.ones(100) * 0.0004
    _ = a4f_recursion(1e-5, 0.5, 0.05, 0.04, 0.06, 0.9, _dummy, _dv)
    print("Numba JIT compiled.")

    df = load_data()

    models = ['GJR_t', 'A4f_t_joint']
    var_methods = ['parametric', 'conformal', 'aci']
    W = 500  # conformal calibration window
    GAMMA_ACI = 0.01  # ACI learning rate

    oos_mask = np.array(df.index >= '2019-01-01')
    returns_full = df['ret'].values
    returns_oos = df['ret'].values[oos_mask]
    r2_oos = df['r2'].values[oos_mask]

    all_results = {}

    for model_name in models:
        print(f"\n{'='*50}")
        print(f"Model: {model_name}")
        print(f"{'='*50}")

        t0 = time.time()
        h_forecast, df_est, std_resid = oos_forecast(df, model_name, window=2000, refit_every=63)
        elapsed = time.time() - t0
        print(f"  OOS forecast elapsed: {elapsed:.1f}s")

        h_oos = h_forecast[oos_mask]
        df_oos = df_est[oos_mask]
        sigma_oos = np.sqrt(h_oos)

        # QLIKE (same for all VaR methods since forecasts are the same)
        ql = qlike(r2_oos, h_oos)
        print(f"  QLIKE = {ql:.6f}")

        for var_method in var_methods:
            key = f"{model_name}_{var_method}"
            print(f"\n  --- {var_method} ---")
            var_results = {}

            for alpha in [0.01, 0.025, 0.05]:
                if var_method == 'parametric':
                    var_v, es_v = compute_parametric_var_es(sigma_oos, df_oos, alpha)
                elif var_method == 'conformal':
                    # Need full-sample h for computing z; use oos portion
                    # But conformal needs a calibration window of past z values
                    # Use full forecast series, then mask to OOS
                    h_full = h_forecast
                    sigma_full = np.sqrt(np.where(h_full > 0, h_full, np.nan))
                    var_full, es_full = compute_conformal_var_es(
                        sigma_full, returns_full, h_full, alpha, W=W)
                    var_v = var_full[oos_mask]
                    es_v = es_full[oos_mask]
                elif var_method == 'aci':
                    h_full = h_forecast
                    sigma_full = np.sqrt(np.where(h_full > 0, h_full, np.nan))
                    var_full, es_full = compute_aci_var_es(
                        sigma_full, returns_full, h_full, alpha, W=W, gamma_aci=GAMMA_ACI)
                    var_v = var_full[oos_mask]
                    es_v = es_full[oos_mask]

                ve = evaluate_var(returns_oos, var_v, es_v, sigma_oos, alpha)
                var_results[str(alpha)] = ve

                print(f"    VaR {alpha*100:.1f}%: viol={ve['violation_rate']:.2f}% "
                      f"(target={alpha*100:.1f}%) "
                      f"UC_p={ve['UC_p']:.3f} CC_p={ve['CC_p']:.3f} "
                      f"DQ_p={ve['DQ_p']:.3f} Basel={ve['Basel']} "
                      f"Score={ve['scorecard']}")
                if abs(alpha - 0.025) < 0.001 and ve.get('ES_Z1') is not None:
                    print(f"    ES 2.5%: Z1={ve['ES_Z1']:.4f}(p={ve['ES_Z1_p']:.3f}) "
                          f"Z2={ve['ES_Z2']:.4f}(p={ve['ES_Z2_p']:.3f})")

            all_results[key] = var_results

    # ============================================================
    # Summary comparison
    # ============================================================
    print("\n" + "=" * 70)
    print("SUMMARY: Scorecard Comparison")
    print("=" * 70)
    print(f"{'Method':<25} {'VaR 1%':>10} {'VaR 2.5%':>10} {'VaR 5%':>10}")
    print("-" * 55)
    for model_name in models:
        for var_method in var_methods:
            key = f"{model_name}_{var_method}"
            label = f"{model_name}+{var_method}"
            scores = []
            for alpha in [0.01, 0.025, 0.05]:
                alpha_key = str(alpha)
                if key in all_results and alpha_key in all_results[key]:
                    scores.append(all_results[key][alpha_key]['scorecard'])
                else:
                    scores.append('N/A')
            print(f"{label:<25} {scores[0]:>10} {scores[1]:>10} {scores[2]:>10}")

    print("\n" + "=" * 70)
    print("SUMMARY: Violation Rates (%)")
    print("=" * 70)
    print(f"{'Method':<25} {'VaR 1%':>10} {'VaR 2.5%':>10} {'VaR 5%':>10}")
    print(f"{'TARGET':<25} {'1.00':>10} {'2.50':>10} {'5.00':>10}")
    print("-" * 55)
    for model_name in models:
        for var_method in var_methods:
            key = f"{model_name}_{var_method}"
            label = f"{model_name}+{var_method}"
            rates = []
            for alpha in [0.01, 0.025, 0.05]:
                alpha_key = str(alpha)
                if key in all_results and alpha_key in all_results[key]:
                    rates.append(f"{all_results[key][alpha_key]['violation_rate']:.2f}")
                else:
                    rates.append('N/A')
            print(f"{label:<25} {rates[0]:>10} {rates[1]:>10} {rates[2]:>10}")

    # ============================================================
    # Compute aggregate scorecard per method
    # ============================================================
    print("\n" + "=" * 70)
    print("AGGREGATE SCORECARDS")
    print("=" * 70)
    for model_name in models:
        for var_method in var_methods:
            key = f"{model_name}_{var_method}"
            total_pass = 0
            total_tests = 0
            for alpha in [0.01, 0.025, 0.05]:
                alpha_key = str(alpha)
                if key in all_results and alpha_key in all_results[key]:
                    sc = all_results[key][alpha_key]['scorecard']
                    num, denom = sc.split('/')
                    total_pass += int(num)
                    total_tests += int(denom)
            if total_tests > 0:
                all_results[key]['aggregate_scorecard'] = f"{total_pass}/{total_tests}"
                all_results[key]['aggregate_pass_rate'] = round(total_pass / total_tests * 100, 1)
                print(f"  {key}: {total_pass}/{total_tests} = {total_pass/total_tests*100:.1f}%")

    # ============================================================
    # Plots
    # ============================================================
    print("\n--- Generating plots ---")
    plot_scorecard_comparison(all_results,
                             os.path.join(SCRIPT_DIR, 'k1005_scorecard_comparison.png'))
    plot_violation_rates(all_results,
                        os.path.join(SCRIPT_DIR, 'k1005_violation_rates.png'))

    # ============================================================
    # Save results
    # ============================================================
    output = {
        'experiment': 'K1005',
        'title': 'Proxy-Reliance Conformal VaR',
        'description': 'Conformal vs Parametric VaR for GJR_t and A4f_t_joint',
        'data_source': 'yfinance (SPY, ^VIX)',
        'data_period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'oos_period': '2019-01-01 to present',
        'n_total': len(df),
        'n_oos': int(np.sum(oos_mask)),
        'models': models,
        'var_methods': var_methods,
        'conformal_window': W,
        'aci_gamma': GAMMA_ACI,
        'window': 2000,
        'refit_every': 63,
        'seed': 42,
        'references': [
            'arXiv:2603.22569 (2026) - Conformal prediction for VaR with proxy-reliance',
            'Gibbs & Candes (2021) - Adaptive Conformal Inference',
            'Vovk et al. (2005) - Conformal prediction',
            'Patton (2011) - QLIKE, proxy-robust',
            'Kupiec (1995) - VaR unconditional coverage',
            'Christoffersen (1998) - VaR conditional coverage',
            'Acerbi & Szekely (2014) - ES backtesting',
            'Harvey (2016) - t>3.0 threshold',
        ],
        'results': all_results,
        'timestamp': datetime.utcnow().isoformat(),
    }

    results_path = os.path.join(SCRIPT_DIR, 'k1005_results.json')
    with open(results_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}")

    return output


if __name__ == '__main__':
    main()
