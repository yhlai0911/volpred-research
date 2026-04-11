#!/usr/bin/env python3
"""
K1045: A4f vs GJR Residual Diagnostic Suite (Paper 9 Support)
=============================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  Paper 9 needs comprehensive residual diagnostics to demonstrate A4f model
  adequacy beyond QLIKE and VaR metrics. This experiment performs a full
  diagnostic suite on standardized residuals z_t = r_t / sigma_t for both
  GJR and A4f models in the OOS period (2019-2026).

Diagnostics:
  1. Distributional Tests: JB, KS, AD, PIT
  2. Independence Tests: Ljung-Box on z_t and z_t^2, ARCH-LM, Runs test
  3. Moment Diagnostics: skewness, kurtosis, rolling moments, QQ-plot
  4. Model Comparison: side-by-side GJR vs A4f
  5. A4f-specific: E[g]=1 test, g_t ACF, tau stability, Corr(z_t, VIX)

Data: SPY 2005-01-01 to 2026-04-10 (yfinance), OOS: 2019-01-01 onward
Window: 2000, refit_every: 63
VIX from ^VIX

References:
  - Engle & Rangel (2008): Spline-GARCH. RFS 21(3):1187-1222.
  - Engle, Ghysels & Sohn (2013): Stock Market Volatility. RES 95(3):776-797.
  - Patton (2011): Volatility forecast comparison. J Econometrics 160:246-256.
  - Jarque & Bera (1980): Efficient tests for normality. Economics Letters.
  - Ljung & Box (1978): On a measure of lack of fit. Biometrika 65(2):297-303.
  - Engle (1982): ARCH. Econometrica 50(4):987-1007.
  - Christoffersen (1998): Evaluating interval forecasts. IER 39(4):841-862.

Author: VolPred Research System
Date: 2026-04-11
Seed: 42
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import datetime, timezone
from scipy import stats as sp_stats
from scipy.optimize import minimize, minimize_scalar
from numba import njit
import math

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1045"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuration
DATA_START = '2004-01-01'
DATA_END = '2026-12-31'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f vs GJR Residual Diagnostic Suite")
print("  Comprehensive residual analysis for Paper 9")
print("=" * 70)

# ============================================================
# 1. Data Loading
# ============================================================
def load_data():
    import yfinance as yf
    spy = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
    vix = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
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
def gjr_nll_normal(omega, alpha, gamma, beta, returns):
    h = gjr_h(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll

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
    # First get normal A4f as starting point
    bounds_n = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
                (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj_n(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            v = a4f_nll_normal(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10
    best_res_n, best_nll_n = None, 1e10
    var0 = np.var(returns)
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

    # Joint MLE with Student-t
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
# 4. OOS Forecasting with full state output
# ============================================================
def oos_forecast_full(df, model_name, window=WINDOW, refit_every=REFIT_EVERY):
    """OOS forecast returning h, tau, g, df arrays."""
    oos_start_idx = np.where(df.index >= OOS_START)[0][0]
    T = len(df)
    forecasts = np.full(T, np.nan)
    tau_arr = np.full(T, np.nan)
    g_arr = np.full(T, np.nan)
    df_arr = np.full(T, np.nan)
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
            df_arr[t] = p[4]
            r_prev = returns[t-1]
            r2p = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h_t = omega + alpha * r2p + gamma * r2p * ind + beta * h_prev
            h_t = max(h_t, 1e-16)
            forecasts[t] = h_t
            h_prev = h_t
        else:  # A4f_t
            theta0, theta1, omega, alpha, gamma, beta = p[0], p[1], p[2], p[3], p[4], p[5]
            df_arr[t] = p[6]
            tau_t = max(theta0 + theta1 * vix2[t-1], 1e-16)
            u_prev = returns[t-1] / np.sqrt(tau_t)
            u2 = u_prev ** 2
            ind = 1.0 if returns[t-1] < 0 else 0.0
            g_t = omega + alpha * u2 + gamma * u2 * ind + beta * g_prev
            g_t = max(g_t, 1e-16)
            forecasts[t] = tau_t * g_t
            tau_arr[t] = tau_t
            g_arr[t] = g_t
            g_prev = g_t
            h_prev = tau_t * g_t

    return forecasts, tau_arr, g_arr, df_arr

# ============================================================
# 5. Diagnostic Tests
# ============================================================
def compute_standardized_residuals(returns, h, df_est=None):
    """Compute z_t = r_t / sigma_t. If df_est provided, also compute PIT."""
    mask = ~np.isnan(h) & (h > 0)
    z = np.full_like(returns, np.nan)
    z[mask] = returns[mask] / np.sqrt(h[mask])
    return z

def jarque_bera_test(z):
    z_clean = z[~np.isnan(z)]
    stat, p = sp_stats.jarque_bera(z_clean)
    return {'statistic': float(stat), 'p_value': float(p), 'n': len(z_clean)}

def ks_test_normal(z):
    z_clean = z[~np.isnan(z)]
    stat, p = sp_stats.kstest(z_clean, 'norm', args=(np.mean(z_clean), np.std(z_clean)))
    return {'statistic': float(stat), 'p_value': float(p)}

def ks_test_t(z, df_val):
    z_clean = z[~np.isnan(z)]
    scale = np.sqrt((df_val - 2) / df_val)
    stat, p = sp_stats.kstest(z_clean, 't', args=(df_val, 0, scale))
    return {'statistic': float(stat), 'p_value': float(p)}

def anderson_darling_normal(z):
    z_clean = z[~np.isnan(z)]
    res = sp_stats.anderson(z_clean, dist='norm')
    return {'statistic': float(res.statistic),
            'critical_values': {f'{cv}%': float(sl) for cv, sl in zip(res.significance_level, res.critical_values)},
            'reject_5pct': bool(res.statistic > res.critical_values[2])}

def pit_test(z, df_val=None):
    """PIT: z_t -> F(z_t) should be U(0,1). Test with KS against uniform."""
    z_clean = z[~np.isnan(z)]
    if df_val is not None and df_val > 2:
        scale = np.sqrt((df_val - 2) / df_val)
        u = sp_stats.t.cdf(z_clean, df_val, loc=0, scale=scale)
    else:
        u = sp_stats.norm.cdf(z_clean)
    ks_stat, ks_p = sp_stats.kstest(u, 'uniform')
    return {'ks_statistic': float(ks_stat), 'ks_p_value': float(ks_p),
            'u_mean': float(np.mean(u)), 'u_std': float(np.std(u)),
            'u_values': u}

def ljung_box_test(z, lags=[1, 5, 10, 20]):
    """Ljung-Box test on z and z^2."""
    from statsmodels.stats.diagnostic import acorr_ljungbox
    z_clean = z[~np.isnan(z)]
    results_z = {}
    results_z2 = {}
    for lag in lags:
        if lag >= len(z_clean):
            continue
        res = acorr_ljungbox(z_clean, lags=[lag], return_df=True)
        results_z[f'lag_{lag}'] = {
            'statistic': float(res['lb_stat'].values[0]),
            'p_value': float(res['lb_pvalue'].values[0])
        }
        res2 = acorr_ljungbox(z_clean**2, lags=[lag], return_df=True)
        results_z2[f'lag_{lag}'] = {
            'statistic': float(res2['lb_stat'].values[0]),
            'p_value': float(res2['lb_pvalue'].values[0])
        }
    return {'z': results_z, 'z_squared': results_z2}

def arch_lm_test(z, lags=[1, 5, 10]):
    """ARCH-LM test (Engle 1982)."""
    from statsmodels.stats.diagnostic import het_arch
    z_clean = z[~np.isnan(z)]
    results = {}
    for lag in lags:
        if lag >= len(z_clean) - 1:
            continue
        lm_stat, lm_p, f_stat, f_p = het_arch(z_clean, nlags=lag)
        results[f'lag_{lag}'] = {
            'lm_statistic': float(lm_stat), 'lm_p_value': float(lm_p),
            'f_statistic': float(f_stat), 'f_p_value': float(f_p)
        }
    return results

def runs_test(z):
    """Runs test for independence (non-parametric)."""
    z_clean = z[~np.isnan(z)]
    median_z = np.median(z_clean)
    signs = (z_clean > median_z).astype(int)
    n1 = np.sum(signs)
    n2 = len(signs) - n1
    # Count runs
    runs = 1
    for i in range(1, len(signs)):
        if signs[i] != signs[i-1]:
            runs += 1
    # Expected runs and variance
    n = n1 + n2
    if n1 == 0 or n2 == 0:
        return {'runs': int(runs), 'expected': float('nan'), 'z_stat': float('nan'), 'p_value': float('nan')}
    expected = 1 + 2 * n1 * n2 / n
    var_runs = 2 * n1 * n2 * (2 * n1 * n2 - n) / (n**2 * (n - 1))
    if var_runs <= 0:
        return {'runs': int(runs), 'expected': float(expected), 'z_stat': float('nan'), 'p_value': float('nan')}
    z_stat = (runs - expected) / np.sqrt(var_runs)
    p_val = 2 * (1 - sp_stats.norm.cdf(abs(z_stat)))
    return {'runs': int(runs), 'expected': float(expected),
            'z_stat': float(z_stat), 'p_value': float(p_val)}

def moment_diagnostics(z):
    """Skewness, kurtosis, and t-tests."""
    z_clean = z[~np.isnan(z)]
    n = len(z_clean)
    skew = float(sp_stats.skew(z_clean))
    kurt = float(sp_stats.kurtosis(z_clean, fisher=True))  # excess kurtosis
    # SE of skewness ~ sqrt(6/n), SE of kurtosis ~ sqrt(24/n)
    se_skew = np.sqrt(6.0 / n)
    se_kurt = np.sqrt(24.0 / n)
    t_skew = skew / se_skew
    t_kurt = kurt / se_kurt  # testing excess kurtosis = 0
    return {
        'mean': float(np.mean(z_clean)),
        'std': float(np.std(z_clean)),
        'skewness': skew, 'se_skewness': float(se_skew),
        't_skewness': float(t_skew), 'p_skewness': float(2 * (1 - sp_stats.norm.cdf(abs(t_skew)))),
        'excess_kurtosis': kurt, 'se_kurtosis': float(se_kurt),
        't_kurtosis': float(t_kurt), 'p_kurtosis': float(2 * (1 - sp_stats.norm.cdf(abs(t_kurt)))),
        'n': n
    }

def rolling_moments(z, window=252):
    """Rolling skewness and kurtosis."""
    z_series = pd.Series(z)
    roll_skew = z_series.rolling(window).skew()
    roll_kurt = z_series.rolling(window).kurt()
    return roll_skew.values, roll_kurt.values

def acf_values(z, nlags=40):
    """Compute ACF for z and z^2."""
    z_clean = z[~np.isnan(z)]
    from statsmodels.tsa.stattools import acf as sm_acf
    acf_z = sm_acf(z_clean, nlags=nlags, fft=True)
    acf_z2 = sm_acf(z_clean**2, nlags=nlags, fft=True)
    return acf_z, acf_z2

# ============================================================
# 6. A4f-Specific Diagnostics
# ============================================================
def a4f_specific_diagnostics(g_arr, tau_arr, z, vix, dates):
    """Diagnostics specific to A4f decomposition."""
    mask = ~np.isnan(g_arr) & ~np.isnan(tau_arr)
    g_clean = g_arr[mask]
    tau_clean = tau_arr[mask]
    z_clean = z[mask]
    vix_clean = vix[mask]

    # E[g] = 1 test
    g_mean = float(np.mean(g_clean))
    g_std = float(np.std(g_clean))
    g_se = g_std / np.sqrt(len(g_clean))
    g_t_stat = (g_mean - 1.0) / g_se if g_se > 0 else 0.0
    g_p_val = 2 * (1 - sp_stats.norm.cdf(abs(g_t_stat)))

    # g_t autocorrelation
    from statsmodels.tsa.stattools import acf as sm_acf
    acf_g = sm_acf(g_clean, nlags=20, fft=True)

    # tau stability
    tau_mean = float(np.mean(tau_clean))
    tau_std = float(np.std(tau_clean))
    tau_cv = tau_std / tau_mean if tau_mean > 0 else 0.0
    tau_min = float(np.min(tau_clean))
    tau_max = float(np.max(tau_clean))

    # Correlation(z_t, VIX)
    corr_z_vix = float(np.corrcoef(z_clean, vix_clean)[0, 1])
    # t-test for correlation
    n_corr = len(z_clean)
    t_corr = corr_z_vix * np.sqrt(n_corr - 2) / np.sqrt(1 - corr_z_vix**2) if abs(corr_z_vix) < 1 else 0
    p_corr = 2 * (1 - sp_stats.t.cdf(abs(t_corr), n_corr - 2))

    return {
        'g_mean': g_mean, 'g_std': g_std, 'g_se': float(g_se),
        'g_t_stat_vs_1': float(g_t_stat), 'g_p_val_vs_1': float(g_p_val),
        'g_acf_1': float(acf_g[1]), 'g_acf_5': float(acf_g[5]),
        'g_acf_10': float(acf_g[10]), 'g_acf_20': float(acf_g[20]),
        'tau_mean': tau_mean, 'tau_std': tau_std, 'tau_cv': float(tau_cv),
        'tau_min': tau_min, 'tau_max': tau_max,
        'tau_annualized_vol_range': f"{np.sqrt(tau_min)*np.sqrt(252)*100:.1f}% - {np.sqrt(tau_max)*np.sqrt(252)*100:.1f}%",
        'corr_z_vix': corr_z_vix, 't_corr_z_vix': float(t_corr), 'p_corr_z_vix': float(p_corr),
        'n': len(g_clean)
    }

# ============================================================
# 7. Plotting Functions
# ============================================================
def plot_qq(z_gjr, z_a4f, df_gjr, df_a4f, save_path):
    """QQ-plot: GJR vs A4f standardized residuals against Student-t."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    for ax, z, df_val, title in [
        (axes[0], z_gjr, df_gjr, 'GJR-t'),
        (axes[1], z_a4f, df_a4f, 'A4f-t')
    ]:
        z_clean = np.sort(z[~np.isnan(z)])
        n = len(z_clean)
        theoretical = sp_stats.t.ppf(np.linspace(0.001, 0.999, n), df_val,
                                      scale=np.sqrt((df_val-2)/df_val))
        ax.scatter(theoretical, z_clean, s=1, alpha=0.3, color='steelblue')
        lims = [min(theoretical.min(), z_clean.min()), max(theoretical.max(), z_clean.max())]
        ax.plot(lims, lims, 'r-', linewidth=1.5, label='45-degree line')
        ax.set_xlabel(f'Theoretical Student-t(df={df_val:.1f})')
        ax.set_ylabel('Sample Quantiles')
        ax.set_title(f'{title} QQ-Plot (OOS 2019-2026)')
        ax.legend()
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")

def plot_acf_z2(z_gjr, z_a4f, save_path):
    """ACF of z^2 for GJR vs A4f."""
    from statsmodels.tsa.stattools import acf as sm_acf
    nlags = 40
    z_gjr_clean = z_gjr[~np.isnan(z_gjr)]
    z_a4f_clean = z_a4f[~np.isnan(z_a4f)]
    acf_gjr = sm_acf(z_gjr_clean**2, nlags=nlags, fft=True)
    acf_a4f = sm_acf(z_a4f_clean**2, nlags=nlags, fft=True)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    ci_gjr = 1.96 / np.sqrt(len(z_gjr_clean))
    ci_a4f = 1.96 / np.sqrt(len(z_a4f_clean))

    for ax, acf_vals, ci, title in [
        (axes[0], acf_gjr, ci_gjr, 'GJR-t: ACF of z_t^2'),
        (axes[1], acf_a4f, ci_a4f, 'A4f-t: ACF of z_t^2')
    ]:
        lags = np.arange(1, nlags + 1)
        ax.bar(lags, acf_vals[1:], width=0.6, color='steelblue', alpha=0.7)
        ax.axhline(y=ci, color='red', linestyle='--', linewidth=1, label=f'95% CI (+/-{ci:.3f})')
        ax.axhline(y=-ci, color='red', linestyle='--', linewidth=1)
        ax.axhline(y=0, color='black', linewidth=0.5)
        ax.set_xlabel('Lag')
        ax.set_ylabel('ACF')
        ax.set_title(title)
        ax.legend()
        ax.set_xlim(0.5, nlags + 0.5)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")

def plot_pit_histogram(pit_gjr, pit_a4f, save_path):
    """PIT histogram: should be uniform if model is correct."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    n_bins = 20

    for ax, u, title in [
        (axes[0], pit_gjr, 'GJR-t: PIT Histogram'),
        (axes[1], pit_a4f, 'A4f-t: PIT Histogram')
    ]:
        ax.hist(u, bins=n_bins, density=True, color='steelblue', alpha=0.7, edgecolor='white')
        ax.axhline(y=1.0, color='red', linestyle='--', linewidth=1.5, label='U(0,1) reference')
        ax.set_xlabel('PIT value u_t = F(z_t)')
        ax.set_ylabel('Density')
        ax.set_title(title)
        ax.legend()
        ax.set_xlim(0, 1)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")

def plot_rolling_moments(dates, roll_skew_gjr, roll_kurt_gjr, roll_skew_a4f, roll_kurt_a4f, save_path):
    """Rolling skewness and kurtosis comparison."""
    fig, axes = plt.subplots(2, 1, figsize=(14, 8))

    mask_gjr = ~np.isnan(roll_skew_gjr)
    mask_a4f = ~np.isnan(roll_skew_a4f)

    # Rolling skewness
    ax = axes[0]
    ax.plot(dates[mask_gjr], roll_skew_gjr[mask_gjr], color='coral', alpha=0.7, linewidth=0.8, label='GJR-t')
    ax.plot(dates[mask_a4f], roll_skew_a4f[mask_a4f], color='steelblue', alpha=0.7, linewidth=0.8, label='A4f-t')
    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax.set_ylabel('Rolling Skewness (252d)')
    ax.set_title('Rolling Skewness of Standardized Residuals')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Rolling kurtosis
    ax = axes[1]
    mask_gjr_k = ~np.isnan(roll_kurt_gjr)
    mask_a4f_k = ~np.isnan(roll_kurt_a4f)
    ax.plot(dates[mask_gjr_k], roll_kurt_gjr[mask_gjr_k], color='coral', alpha=0.7, linewidth=0.8, label='GJR-t')
    ax.plot(dates[mask_a4f_k], roll_kurt_a4f[mask_a4f_k], color='steelblue', alpha=0.7, linewidth=0.8, label='A4f-t')
    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax.set_ylabel('Rolling Excess Kurtosis (252d)')
    ax.set_title('Rolling Kurtosis of Standardized Residuals')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")

def plot_a4f_decomposition(dates, tau_arr, g_arr, h_arr, save_path):
    """A4f decomposition: tau, g, and h=tau*g."""
    mask = ~np.isnan(tau_arr)
    fig, axes = plt.subplots(3, 1, figsize=(14, 10))

    ax = axes[0]
    ax.plot(dates[mask], np.sqrt(tau_arr[mask]) * np.sqrt(252) * 100,
            color='steelblue', linewidth=0.8)
    ax.set_ylabel('Annualized Vol (%)')
    ax.set_title('A4f: tau_t (VIX-driven long-run component)')
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    ax.plot(dates[mask], g_arr[mask], color='coral', linewidth=0.8)
    ax.axhline(y=1.0, color='black', linestyle='--', linewidth=1)
    ax.set_ylabel('g_t')
    ax.set_title('A4f: g_t (short-run GARCH component, E[g]=1)')
    ax.grid(True, alpha=0.3)

    ax = axes[2]
    ax.plot(dates[mask], np.sqrt(h_arr[mask]) * np.sqrt(252) * 100,
            color='purple', linewidth=0.8)
    ax.set_ylabel('Annualized Vol (%)')
    ax.set_title('A4f: h_t = tau_t * g_t (total conditional variance)')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")

# ============================================================
# 8. Main Execution
# ============================================================
def main():
    print("\n[1/6] Loading data...")
    df = load_data()
    oos_mask = df.index >= OOS_START
    oos_dates = df.index[oos_mask]
    print(f"  OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()}, N_OOS={oos_mask.sum()}")

    print("\n[2/6] Running OOS forecasts (GJR-t)...")
    t0 = time.time()
    h_gjr, _, _, df_gjr = oos_forecast_full(df, 'GJR_t')
    print(f"  GJR-t done in {time.time()-t0:.1f}s")

    print("\n[3/6] Running OOS forecasts (A4f-t)...")
    t0 = time.time()
    h_a4f, tau_a4f, g_a4f, df_a4f = oos_forecast_full(df, 'A4f_t')
    print(f"  A4f-t done in {time.time()-t0:.1f}s")

    # Standardized residuals
    returns = df['ret'].values
    z_gjr = compute_standardized_residuals(returns, h_gjr)
    z_a4f = compute_standardized_residuals(returns, h_a4f)

    # Median df for distributional tests
    df_gjr_med = float(np.nanmedian(df_gjr[oos_mask]))
    df_a4f_med = float(np.nanmedian(df_a4f[oos_mask]))
    print(f"\n  Median df: GJR={df_gjr_med:.2f}, A4f={df_a4f_med:.2f}")

    # Focus on OOS
    z_gjr_oos = z_gjr[oos_mask]
    z_a4f_oos = z_a4f[oos_mask]
    vix_oos = df['vix'].values[oos_mask]

    results = {
        'experiment_id': EXPERIMENT_ID,
        'asset': 'SPY',
        'data_source': 'yfinance',
        'data_period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'oos_period': f"{oos_dates[0].date()} to {oos_dates[-1].date()}",
        'n_total': len(df),
        'n_oos': int(oos_mask.sum()),
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'seed': 42,
        'models': ['GJR_t', 'A4f_t'],
        'median_df_gjr': df_gjr_med,
        'median_df_a4f': df_a4f_med,
    }

    # ============================================================
    # Diagnostic Suite
    # ============================================================
    print("\n[4/6] Running diagnostic tests...")

    for model_name, z_oos, df_med in [('GJR_t', z_gjr_oos, df_gjr_med),
                                       ('A4f_t', z_a4f_oos, df_a4f_med)]:
        print(f"\n  --- {model_name} ---")
        diag = {}

        # Distributional
        print(f"    Distributional tests...")
        diag['jarque_bera'] = jarque_bera_test(z_oos)
        diag['ks_normal'] = ks_test_normal(z_oos)
        diag['ks_student_t'] = ks_test_t(z_oos, df_med)
        diag['anderson_darling'] = anderson_darling_normal(z_oos)
        pit_res = pit_test(z_oos, df_med)
        diag['pit_ks'] = {k: v for k, v in pit_res.items() if k != 'u_values'}
        if model_name == 'GJR_t':
            pit_gjr_u = pit_res['u_values']
        else:
            pit_a4f_u = pit_res['u_values']

        # Independence
        print(f"    Independence tests...")
        diag['ljung_box'] = ljung_box_test(z_oos)
        diag['arch_lm'] = arch_lm_test(z_oos)
        diag['runs_test'] = runs_test(z_oos)

        # Moments
        print(f"    Moment diagnostics...")
        diag['moments'] = moment_diagnostics(z_oos)

        results[model_name] = diag
        print(f"    JB p={diag['jarque_bera']['p_value']:.4f}, "
              f"KS(t) p={diag['ks_student_t']['p_value']:.4f}, "
              f"AD reject@5%={diag['anderson_darling']['reject_5pct']}")
        print(f"    LB(z^2,10) p={diag['ljung_box']['z_squared']['lag_10']['p_value']:.4f}, "
              f"ARCH-LM(10) p={diag['arch_lm']['lag_10']['lm_p_value']:.4f}")
        print(f"    Skew={diag['moments']['skewness']:.4f} (p={diag['moments']['p_skewness']:.4f}), "
              f"ExKurt={diag['moments']['excess_kurtosis']:.4f} (p={diag['moments']['p_kurtosis']:.4f})")

    # A4f-specific diagnostics
    print(f"\n  --- A4f-specific diagnostics ---")
    a4f_diag = a4f_specific_diagnostics(
        g_a4f[oos_mask], tau_a4f[oos_mask], z_a4f_oos,
        vix_oos, oos_dates)
    results['A4f_specific'] = a4f_diag
    print(f"    E[g]={a4f_diag['g_mean']:.4f} (t={a4f_diag['g_t_stat_vs_1']:.2f}, p={a4f_diag['g_p_val_vs_1']:.4f})")
    print(f"    g ACF(1)={a4f_diag['g_acf_1']:.4f}, ACF(5)={a4f_diag['g_acf_5']:.4f}")
    print(f"    tau CV={a4f_diag['tau_cv']:.4f}, range: {a4f_diag['tau_annualized_vol_range']}")
    print(f"    Corr(z,VIX)={a4f_diag['corr_z_vix']:.4f} (p={a4f_diag['p_corr_z_vix']:.4f})")

    # Also compute Corr(z_gjr, VIX) for comparison
    z_gjr_clean = z_gjr_oos[~np.isnan(z_gjr_oos)]
    vix_for_gjr = vix_oos[~np.isnan(z_gjr_oos)]
    corr_gjr_vix = float(np.corrcoef(z_gjr_clean, vix_for_gjr)[0, 1])
    n_corr_gjr = len(z_gjr_clean)
    t_corr_gjr = corr_gjr_vix * np.sqrt(n_corr_gjr - 2) / np.sqrt(1 - corr_gjr_vix**2) if abs(corr_gjr_vix) < 1 else 0
    p_corr_gjr = 2 * (1 - sp_stats.t.cdf(abs(t_corr_gjr), n_corr_gjr - 2))
    results['GJR_t']['corr_z_vix'] = corr_gjr_vix
    results['GJR_t']['t_corr_z_vix'] = float(t_corr_gjr)
    results['GJR_t']['p_corr_z_vix'] = float(p_corr_gjr)
    print(f"    GJR Corr(z,VIX)={corr_gjr_vix:.4f} (p={p_corr_gjr:.4f})")

    # Model comparison summary
    print("\n  --- Model Comparison Summary ---")
    comp = {}
    for metric in ['jarque_bera', 'ks_student_t', 'pit_ks']:
        gjr_p = results['GJR_t'][metric].get('p_value', results['GJR_t'][metric].get('ks_p_value', 0))
        a4f_p = results['A4f_t'][metric].get('p_value', results['A4f_t'][metric].get('ks_p_value', 0))
        comp[metric] = {'GJR_p': float(gjr_p), 'A4f_p': float(a4f_p),
                        'better': 'A4f' if a4f_p > gjr_p else 'GJR'}
        print(f"    {metric}: GJR p={gjr_p:.4f}, A4f p={a4f_p:.4f} -> {comp[metric]['better']}")

    for lag in [1, 5, 10]:
        key = f'lag_{lag}'
        gjr_p = results['GJR_t']['arch_lm'][key]['lm_p_value']
        a4f_p = results['A4f_t']['arch_lm'][key]['lm_p_value']
        comp[f'arch_lm_{key}'] = {'GJR_p': float(gjr_p), 'A4f_p': float(a4f_p),
                                   'better': 'A4f' if a4f_p > gjr_p else 'GJR'}
        print(f"    ARCH-LM({lag}): GJR p={gjr_p:.4f}, A4f p={a4f_p:.4f} -> {comp[f'arch_lm_{key}']['better']}")

    comp['corr_z_vix_abs'] = {
        'GJR': abs(corr_gjr_vix), 'A4f': abs(results['A4f_specific']['corr_z_vix']),
        'better': 'A4f' if abs(results['A4f_specific']['corr_z_vix']) < abs(corr_gjr_vix) else 'GJR'
    }
    print(f"    |Corr(z,VIX)|: GJR={abs(corr_gjr_vix):.4f}, A4f={abs(results['A4f_specific']['corr_z_vix']):.4f} -> {comp['corr_z_vix_abs']['better']}")

    results['comparison'] = comp

    # Count wins
    a4f_wins = sum(1 for v in comp.values() if v.get('better') == 'A4f')
    gjr_wins = sum(1 for v in comp.values() if v.get('better') == 'GJR')
    results['summary'] = {
        'a4f_wins': a4f_wins, 'gjr_wins': gjr_wins,
        'total_tests': len(comp),
        'verdict': 'A4f residuals are diagnostically superior' if a4f_wins > gjr_wins
                   else 'GJR residuals are diagnostically superior' if gjr_wins > a4f_wins
                   else 'Models are diagnostically similar'
    }
    print(f"\n  Wins: A4f={a4f_wins}, GJR={gjr_wins} -> {results['summary']['verdict']}")

    # ============================================================
    # Plots
    # ============================================================
    print("\n[5/6] Generating plots...")

    plot_qq(z_gjr_oos, z_a4f_oos, df_gjr_med, df_a4f_med,
            os.path.join(SCRIPT_DIR, 'k1045_qq_plot.png'))

    plot_acf_z2(z_gjr_oos, z_a4f_oos,
                os.path.join(SCRIPT_DIR, 'k1045_acf_z2.png'))

    plot_pit_histogram(pit_gjr_u, pit_a4f_u,
                       os.path.join(SCRIPT_DIR, 'k1045_pit_histogram.png'))

    # Rolling moments
    roll_skew_gjr, roll_kurt_gjr = rolling_moments(z_gjr_oos)
    roll_skew_a4f, roll_kurt_a4f = rolling_moments(z_a4f_oos)
    plot_rolling_moments(oos_dates, roll_skew_gjr, roll_kurt_gjr,
                         roll_skew_a4f, roll_kurt_a4f,
                         os.path.join(SCRIPT_DIR, 'k1045_rolling_moments.png'))

    # A4f decomposition
    plot_a4f_decomposition(oos_dates, tau_a4f[oos_mask], g_a4f[oos_mask],
                           h_a4f[oos_mask],
                           os.path.join(SCRIPT_DIR, 'k1045_a4f_decomposition.png'))

    # ============================================================
    # Save Results
    # ============================================================
    print("\n[6/6] Saving results...")
    results['execution_time_s'] = round(time.time() - START_TIME, 1)
    results['timestamp'] = datetime.now(timezone.utc).isoformat()

    results_path = os.path.join(SCRIPT_DIR, 'k1045_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Results saved to {results_path}")

    # Print concise table for Paper 9
    print("\n" + "=" * 70)
    print("PAPER 9 RESIDUAL DIAGNOSTIC TABLE")
    print("=" * 70)
    print(f"{'Test':<30} {'GJR-t p-val':>15} {'A4f-t p-val':>15} {'Better':>8}")
    print("-" * 70)
    print(f"{'Jarque-Bera':<30} {results['GJR_t']['jarque_bera']['p_value']:>15.4f} {results['A4f_t']['jarque_bera']['p_value']:>15.4f} {'A4f' if results['A4f_t']['jarque_bera']['p_value'] > results['GJR_t']['jarque_bera']['p_value'] else 'GJR':>8}")
    print(f"{'KS (Student-t)':<30} {results['GJR_t']['ks_student_t']['p_value']:>15.4f} {results['A4f_t']['ks_student_t']['p_value']:>15.4f} {'A4f' if results['A4f_t']['ks_student_t']['p_value'] > results['GJR_t']['ks_student_t']['p_value'] else 'GJR':>8}")
    print(f"{'Anderson-Darling':<30} {'Reject' if results['GJR_t']['anderson_darling']['reject_5pct'] else 'Pass':>15} {'Reject' if results['A4f_t']['anderson_darling']['reject_5pct'] else 'Pass':>15}")
    print(f"{'PIT KS':<30} {results['GJR_t']['pit_ks']['ks_p_value']:>15.4f} {results['A4f_t']['pit_ks']['ks_p_value']:>15.4f} {'A4f' if results['A4f_t']['pit_ks']['ks_p_value'] > results['GJR_t']['pit_ks']['ks_p_value'] else 'GJR':>8}")
    print(f"{'LB z^2 (lag 10)':<30} {results['GJR_t']['ljung_box']['z_squared']['lag_10']['p_value']:>15.4f} {results['A4f_t']['ljung_box']['z_squared']['lag_10']['p_value']:>15.4f} {'A4f' if results['A4f_t']['ljung_box']['z_squared']['lag_10']['p_value'] > results['GJR_t']['ljung_box']['z_squared']['lag_10']['p_value'] else 'GJR':>8}")
    print(f"{'ARCH-LM (lag 10)':<30} {results['GJR_t']['arch_lm']['lag_10']['lm_p_value']:>15.4f} {results['A4f_t']['arch_lm']['lag_10']['lm_p_value']:>15.4f} {'A4f' if results['A4f_t']['arch_lm']['lag_10']['lm_p_value'] > results['GJR_t']['arch_lm']['lag_10']['lm_p_value'] else 'GJR':>8}")
    print(f"{'Runs test':<30} {results['GJR_t']['runs_test']['p_value']:>15.4f} {results['A4f_t']['runs_test']['p_value']:>15.4f} {'A4f' if results['A4f_t']['runs_test']['p_value'] > results['GJR_t']['runs_test']['p_value'] else 'GJR':>8}")
    print(f"{'|Corr(z,VIX)|':<30} {abs(corr_gjr_vix):>15.4f} {abs(results['A4f_specific']['corr_z_vix']):>15.4f} {'A4f' if abs(results['A4f_specific']['corr_z_vix']) < abs(corr_gjr_vix) else 'GJR':>8}")
    print("-" * 70)
    print(f"{'Skewness':<30} {results['GJR_t']['moments']['skewness']:>15.4f} {results['A4f_t']['moments']['skewness']:>15.4f}")
    print(f"{'Excess Kurtosis':<30} {results['GJR_t']['moments']['excess_kurtosis']:>15.4f} {results['A4f_t']['moments']['excess_kurtosis']:>15.4f}")
    print(f"{'Std(z)':<30} {results['GJR_t']['moments']['std']:>15.4f} {results['A4f_t']['moments']['std']:>15.4f}")
    print("=" * 70)
    print(f"\nA4f-specific: E[g]={a4f_diag['g_mean']:.4f}, tau CV={a4f_diag['tau_cv']:.4f}")
    print(f"Total execution time: {results['execution_time_s']:.1f}s")

    return results


if __name__ == '__main__':
    results = main()
