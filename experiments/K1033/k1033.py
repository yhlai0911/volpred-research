#!/usr/bin/env python3
"""
K1033: A4f Refit Frequency Sensitivity (Paper 9 Robustness)
============================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  Paper 9 uses refit_every=63 (quarterly) for all A4f experiments.
  Reviewers will ask: "Are results sensitive to refit frequency?"
  This experiment tests 5 refit frequencies: 21, 42, 63, 126, 252.

  If QLIKE and DM t-stats are stable across frequencies → robust.
  If not → need to discuss optimal refit strategy (also a contribution).

  K783b tested window size sensitivity (w=2000 default is reasonable).
  This is the refit frequency dimension of sensitivity analysis.

Assets: SPY and QQQ (strongest A4f effects from K988/K994).

Models:
  - GJR-t(df=8) — baseline
  - A4f-VIX-t(df=8) — τ = θ₀ + θ₁ × VIX²

Configuration:
  DATA_START = '2005-01-01'
  OOS_START  = '2019-01-01'
  WINDOW     = 2000
  DF_FIXED   = 8
  seed       = 42

Evaluation:
  - QLIKE on r² (Patton 2011)
  - DM test (Harvey t>3.0) for each refit frequency
  - VaR 2.5% and 1% Kupiec test
  - Spearman rank correlation
  - Summary table: refit freq vs QLIKE and DM t-stat
  - Robustness: coefficient of variation of QLIKE across refit freqs

References:
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and
    Macroeconomic Fundamentals. RES 95(3):776-797.
  - Engle & Rangel (2008). Spline-GARCH. RFS 21(3):1187-1222.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold for multiple testing.
  - Kupiec (1995). Verifying the Accuracy of Risk Measurement Models.
  - Acerbi & Szekely (2014). Back-testing Expected Shortfall.
  - K988: A4f champion for SPY (DM t=+4.48 vs GJR, refit=63)
  - K1003: A4f sensitivity (13/16 PASS)
  - K783b: Window size sensitivity (w=2000 reasonable default)
  - K1030: European market test (refit=63)

Author: VolPred Research System
Date: 2026-04-10
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
from scipy.special import gammaln
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1033"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike as qlike_func, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1033_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
OOS_START = '2019-01-01'
WINDOW = 2000
DF_FIXED = 8
REFIT_FREQS = [21, 42, 63, 126, 252]  # monthly, bi-monthly, quarterly, semi-annual, annual
ASSETS = ['SPY', 'QQQ']

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f Refit Frequency Sensitivity (Paper 9 Robustness)")
print(f"  Assets: {ASSETS}")
print(f"  Refit frequencies: {REFIT_FREQS}")
print("=" * 70)


# ============================================================
# GARCH RECURSIONS (from K1030)
# ============================================================

def gjr_recursion(omega, alpha, gamma, beta, returns):
    """GJR-GARCH(1,1) variance recursion."""
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns[:min(250, T)])
    for t in range(1, T):
        u2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * u2 + gamma * u2 * ind + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    return h


def student_t_const(df):
    return float(gammaln((df + 1) / 2) - gammaln(df / 2) - 0.5 * np.log(np.pi * (df - 2)))

T_CONST_8 = student_t_const(DF_FIXED)


def gjr_nll_t(omega, alpha, gamma, beta, df, t_const, returns):
    h = gjr_recursion(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += t_const - 0.5 * np.log(h[t]) - (df + 1) / 2 * np.log(1 + returns[t]**2 / (h[t] * (df - 2)))
    return -ll


def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, fear2):
    """A4f multiplicative GARCH-X recursion.
    tau_t = max(theta0 + theta1 * fear2_{t-1}, eps)
    u_{t-1} = r_{t-1} / sqrt(tau_t)
    g_t = omega + alpha*u^2 + gamma*u^2*I(u<0) + beta*g_{t-1}
    sigma2_t = tau_t * g_t
    """
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)

    tau[0] = theta0 + theta1 * fear2[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]

    for t in range(1, T):
        tau[t] = theta0 + theta1 * fear2[t-1]
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


def a4f_nll_t(theta0, theta1, omega, alpha, gamma, beta, df, t_const, returns, fear2):
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, fear2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += t_const - 0.5 * np.log(h[t]) - (df + 1) / 2 * np.log(1 + returns[t]**2 / (h[t] * (df - 2)))
    return -ll


# ============================================================
# MODEL FITTING
# ============================================================

def fit_gjr_t(returns, df=DF_FIXED):
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
        [var0 * 0.01, 0.04, 0.04, 0.92],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    def nll(params):
        omega, alpha, gamma, beta = params
        if alpha + gamma / 2 + beta >= 0.999:
            return 1e10
        return gjr_nll_t(omega, alpha, gamma, beta, float(df), T_CONST_8, returns)

    for s in starts:
        try:
            res = optimize.minimize(nll, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500, 'ftol': 1e-10})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def fit_a4f_t(returns, fear_vals, df=DF_FIXED):
    var0 = np.var(returns)
    fear2_mean = np.mean(fear_vals**2) + 1e-8
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.1, var0 / fear2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / fear2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / fear2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
        [var0 * 0.01, var0 / fear2_mean * 2.0, 0.08, 0.04, 0.04, 0.92],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    def nll(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if alpha + gamma_p / 2 + beta >= 0.999 or omega_g <= 0:
            return 1e10
        return a4f_nll_t(theta0, theta1, omega_g, alpha, gamma_p, beta,
                         float(df), T_CONST_8, returns, fear_vals**2)

    for s in starts:
        try:
            res = optimize.minimize(nll, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500, 'ftol': 1e-10})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


# ============================================================
# OOS FORECASTING
# ============================================================

def oos_forecast_gjr_t(ret, oos_mask, window, refit_every, df=DF_FIXED):
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)
    forecasts = np.full(n_oos, np.nan)
    params = None
    last_fit = -refit_every
    h_prev = None
    r_prev = None

    for i, t in enumerate(oos_indices):
        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_gjr_t(train_ret, df)
            if params is None:
                continue
            last_fit = t
            omega, alpha, gamma, beta = params
            h_series = gjr_recursion(omega, alpha, gamma, beta, train_ret)
            h_prev = h_series[-1]
            r_prev = train_ret[-1]
        else:
            omega, alpha, gamma, beta = params
            u2 = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h_prev = max(omega + alpha * u2 + gamma * u2 * ind + beta * h_prev, 1e-10)
            r_prev = ret[t-1]

        if params is None:
            continue
        omega, alpha, gamma, beta = params
        u2 = ret[t-1] ** 2
        ind = 1.0 if ret[t-1] < 0 else 0.0
        forecasts[i] = max(omega + alpha * u2 + gamma * u2 * ind + beta * h_prev, 1e-10)

    return forecasts


def oos_forecast_a4f_t(ret, fear_vals, oos_mask, window, refit_every, df=DF_FIXED):
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)
    forecasts = np.full(n_oos, np.nan)
    params = None
    last_fit = -refit_every
    g_prev = None
    r_prev_val = None

    for i, t in enumerate(oos_indices):
        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            train_fear = fear_vals[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_a4f_t(train_ret, train_fear, df)
            if params is None:
                continue
            last_fit = t
            theta0, theta1, omega_g, alpha, gamma_p, beta = params
            _, _, g_series = a4f_recursion(
                theta0, theta1, omega_g, alpha, gamma_p, beta,
                train_ret, train_fear**2
            )
            g_prev = g_series[-1]
            r_prev_val = train_ret[-1]
        else:
            theta0, theta1, omega_g, alpha, gamma_p, beta = params
            tau_curr = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)
            u_prev = r_prev_val / np.sqrt(tau_curr)
            u2 = u_prev ** 2
            ind = 1.0 if r_prev_val < 0 else 0.0
            g_prev = max(omega_g + alpha * u2 + gamma_p * u2 * ind + beta * g_prev, 1e-10)
            r_prev_val = ret[t-1]

        if params is None:
            continue
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau_t = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)
        u_prev_fc = ret[t-1] / np.sqrt(tau_t)
        u2_fc = u_prev_fc ** 2
        ind_fc = 1.0 if ret[t-1] < 0 else 0.0
        g_fc = max(omega_g + alpha * u2_fc + gamma_p * u2_fc * ind_fc + beta * g_prev, 1e-10)
        forecasts[i] = tau_t * g_fc

    return forecasts


# ============================================================
# VAR / ES BACKTESTING
# ============================================================

def var_backtest_kupiec(returns_oos, forecasts, alpha_level=0.025, df=DF_FIXED):
    valid = ~np.isnan(forecasts)
    ret = returns_oos[valid]
    fc = forecasts[valid]
    n = len(ret)
    if n < 100:
        return np.nan, alpha_level, np.nan, np.nan, 'SKIP'

    t_q = stats.t.ppf(alpha_level, df)
    var_series = t_q * np.sqrt(fc * (df - 2) / df)
    violations = (ret < var_series).sum()
    vr = violations / n

    if violations == 0:
        lr = -2 * n * np.log(1 - alpha_level)
    elif violations == n:
        lr = -2 * n * np.log(alpha_level)
    else:
        lr = -2 * (np.log((1 - alpha_level)**(n - violations) * alpha_level**violations)
                    - np.log((1 - vr)**(n - violations) * vr**violations))

    p_value = 1 - stats.chi2.cdf(lr, 1)
    pass_flag = 'PASS' if p_value > 0.05 else 'FAIL'
    return float(vr), alpha_level, float(lr), float(p_value), pass_flag


def es_backtest(returns_oos, forecasts, alpha_level=0.025, df=DF_FIXED):
    valid = ~np.isnan(forecasts)
    ret = returns_oos[valid]
    fc = forecasts[valid]
    n = len(ret)
    if n < 100:
        return np.nan, np.nan, np.nan, 'SKIP'

    t_q = stats.t.ppf(alpha_level, df)
    scale = np.sqrt((df - 2) / df)
    var_series = t_q * scale * np.sqrt(fc)

    t_pdf = stats.t.pdf(t_q, df)
    es_factor = -(df + t_q**2) / (df - 1) * t_pdf / alpha_level
    es_series = es_factor * scale * np.sqrt(fc)

    violations_mask = ret < var_series
    n_viol = violations_mask.sum()
    if n_viol == 0:
        return 0.0, np.nan, np.nan, 'SKIP'

    z_stat = 1 / (n * alpha_level) * np.sum(ret[violations_mask] / es_series[violations_mask]) + 1
    p_value = stats.norm.cdf(z_stat)
    pass_flag = 'PASS' if p_value > 0.05 else 'FAIL'
    return float(z_stat), float(p_value), float(n_viol / n), pass_flag


# ============================================================
# DATA LOADING
# ============================================================
print("\n[1] Loading data from yfinance...")
import yfinance as yf

# Load VIX
vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_series = vix_raw['Close'].copy() / 100.0
print(f"  VIX: {len(vix_series)} obs ({vix_series.index[0].strftime('%Y-%m-%d')} to {vix_series.index[-1].strftime('%Y-%m-%d')})")


# ============================================================
# MAIN LOOP: ASSET x REFIT FREQUENCY
# ============================================================

all_results = {}

for asset in ASSETS:
    print(f"\n{'='*70}")
    print(f"  Asset: {asset}")
    print(f"{'='*70}")

    # Download price data
    raw = yf.download(asset, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    prices = raw['Close'].copy()
    log_ret = np.log(prices / prices.shift(1))

    # Align with VIX
    df_data = pd.DataFrame({
        'price': prices,
        'log_ret': log_ret,
        'VIX': vix_series,
    })
    df_data = df_data.dropna()
    n_total = len(df_data)

    print(f"  Data: {df_data.index[0].strftime('%Y-%m-%d')} to {df_data.index[-1].strftime('%Y-%m-%d')}, n={n_total}")

    oos_mask = np.array(df_data.index >= OOS_START)
    n_oos = oos_mask.sum()
    print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

    ret = df_data['log_ret'].values
    vix_vals = df_data['VIX'].values
    r2 = ret ** 2

    oos_indices = np.where(oos_mask)[0]
    oos_r2_vals = r2[oos_indices]
    oos_ret = ret[oos_indices]

    # Descriptive stats (once per asset)
    desc = {
        'n_total': int(n_total),
        'n_oos': int(n_oos),
        'data_start': df_data.index[0].strftime('%Y-%m-%d'),
        'data_end': df_data.index[-1].strftime('%Y-%m-%d'),
        'oos_mean_return_ann': float(np.mean(oos_ret) * 252),
        'oos_vol_ann': float(np.std(oos_ret) * np.sqrt(252)),
        'oos_skewness': float(stats.skew(oos_ret)),
        'oos_kurtosis': float(stats.kurtosis(oos_ret)),
    }
    print(f"  OOS vol (ann.): {desc['oos_vol_ann']:.4f}")
    print(f"  OOS skew: {desc['oos_skewness']:.3f}, kurtosis: {desc['oos_kurtosis']:.3f}")

    asset_results = {
        'descriptive_stats': desc,
        'refit_results': {},
    }

    for refit_every in REFIT_FREQS:
        print(f"\n  --- Refit every {refit_every} days ---")

        # GJR-t
        t0 = time.time()
        fc_gjr = oos_forecast_gjr_t(ret, oos_mask, WINDOW, refit_every, DF_FIXED)
        t_gjr = time.time() - t0
        valid_gjr = int(np.sum(~np.isnan(fc_gjr)))
        n_refits_gjr = max(1, n_oos // refit_every)
        print(f"    GJR: {t_gjr:.1f}s, valid={valid_gjr}, ~{n_refits_gjr} refits")

        # A4f-VIX-t
        t0 = time.time()
        fc_a4f = oos_forecast_a4f_t(ret, vix_vals, oos_mask, WINDOW, refit_every, DF_FIXED)
        t_a4f = time.time() - t0
        valid_a4f = int(np.sum(~np.isnan(fc_a4f)))
        print(f"    A4f: {t_a4f:.1f}s, valid={valid_a4f}")

        # Align valid obs
        valid = ~np.isnan(fc_gjr) & ~np.isnan(fc_a4f)
        fc_gjr_v = fc_gjr[valid]
        fc_a4f_v = fc_a4f[valid]
        r2_v = oos_r2_vals[valid]
        ret_v = oos_ret[valid]
        n_valid = len(r2_v)
        print(f"    Valid aligned obs: {n_valid}")

        # QLIKE
        qlike_gjr = float(qlike_func(r2_v, fc_gjr_v))
        qlike_a4f = float(qlike_func(r2_v, fc_a4f_v))
        print(f"    QLIKE GJR: {qlike_gjr:.6f}, A4f: {qlike_a4f:.6f}")

        # DM test
        loss_gjr = np.log(fc_gjr_v) + r2_v / fc_gjr_v
        loss_a4f = np.log(fc_a4f_v) + r2_v / fc_a4f_v
        dm_t, dm_p = dm_test(loss_a4f, loss_gjr)
        sig_harvey = abs(dm_t) > 3.0
        print(f"    DM: t={dm_t:.3f}, p={dm_p:.4f}, {'SIG' if sig_harvey else 'n.s.'}")

        # Spearman
        sp_gjr, _ = spearman_corr(r2_v, fc_gjr_v)
        sp_a4f, _ = spearman_corr(r2_v, fc_a4f_v)
        print(f"    Spearman GJR: {sp_gjr:.4f}, A4f: {sp_a4f:.4f}")

        # QLIKE improvement
        improve_pct = (qlike_gjr - qlike_a4f) / qlike_gjr * 100
        print(f"    QLIKE improvement: {improve_pct:.2f}%")

        # VaR/ES backtesting
        var_es = {}
        for alpha_label, alpha_val in [('2.5%', 0.025), ('1%', 0.01)]:
            var_es[f'VaR_{alpha_label}'] = {}
            var_es[f'ES_{alpha_label}'] = {}

            for model_name, fc_arr in [('GJR', fc_gjr_v), ('A4f_VIX', fc_a4f_v)]:
                vr, _, lr, pv, pf = var_backtest_kupiec(ret_v, fc_arr, alpha_val, DF_FIXED)
                var_es[f'VaR_{alpha_label}'][model_name] = {
                    'violation_rate': vr, 'kupiec_p': pv, 'pass': pf
                }

                z, pv_es, vr_es, pf_es = es_backtest(ret_v, fc_arr, alpha_val, DF_FIXED)
                var_es[f'ES_{alpha_label}'][model_name] = {
                    'z_stat': z, 'p_value': pv_es, 'pass': pf_es
                }

            # Print VaR summary
            for model_name in ['GJR', 'A4f_VIX']:
                vr_25 = var_es['VaR_2.5%'][model_name]
                es_25 = var_es['ES_2.5%'][model_name]
                print(f"    {model_name} VaR2.5%: VR={vr_25['violation_rate']:.4f} [{vr_25['pass']}] | "
                      f"ES: [{es_25['pass']}]")

        # Store results for this refit frequency
        asset_results['refit_results'][str(refit_every)] = {
            'refit_every': refit_every,
            'n_valid': n_valid,
            'n_refits_approx': n_refits_gjr,
            'gjr': {
                'qlike': qlike_gjr,
                'spearman': float(sp_gjr),
                'time_s': round(t_gjr, 1),
                'n_valid': valid_gjr,
            },
            'a4f_vix': {
                'qlike': qlike_a4f,
                'spearman': float(sp_a4f),
                'time_s': round(t_a4f, 1),
                'n_valid': valid_a4f,
            },
            'dm_test': {
                'dm_t': round(float(dm_t), 4),
                'dm_p': round(float(dm_p), 4),
                'significant_harvey': sig_harvey,
            },
            'qlike_improvement_pct': round(float(improve_pct), 2),
            'var_es_backtesting': var_es,
        }

    all_results[asset] = asset_results


# ============================================================
# ROBUSTNESS ANALYSIS
# ============================================================
print(f"\n{'='*70}")
print("ROBUSTNESS ANALYSIS")
print(f"{'='*70}")

robustness = {}

for asset in ASSETS:
    ar = all_results[asset]
    refit_res = ar['refit_results']

    qlike_gjr_vals = []
    qlike_a4f_vals = []
    dm_t_vals = []
    improve_vals = []
    refit_keys = sorted(refit_res.keys(), key=lambda x: int(x))

    for rk in refit_keys:
        rr = refit_res[rk]
        qlike_gjr_vals.append(rr['gjr']['qlike'])
        qlike_a4f_vals.append(rr['a4f_vix']['qlike'])
        dm_t_vals.append(rr['dm_test']['dm_t'])
        improve_vals.append(rr['qlike_improvement_pct'])

    qlike_gjr_arr = np.array(qlike_gjr_vals)
    qlike_a4f_arr = np.array(qlike_a4f_vals)
    dm_t_arr = np.array(dm_t_vals)
    improve_arr = np.array(improve_vals)

    # Coefficient of Variation
    cv_gjr = float(np.std(qlike_gjr_arr) / np.mean(qlike_gjr_arr)) if np.mean(qlike_gjr_arr) != 0 else np.nan
    cv_a4f = float(np.std(qlike_a4f_arr) / np.mean(qlike_a4f_arr)) if np.mean(qlike_a4f_arr) != 0 else np.nan

    # Range of DM t-stats
    dm_range = float(np.max(dm_t_arr) - np.min(dm_t_arr))
    dm_mean = float(np.mean(dm_t_arr))
    dm_min = float(np.min(dm_t_arr))
    dm_max = float(np.max(dm_t_arr))

    # How many refit freqs pass Harvey threshold?
    n_sig = int(np.sum(np.abs(dm_t_arr) > 3.0))

    # QLIKE improvement range
    improve_range = float(np.max(improve_arr) - np.min(improve_arr))
    improve_mean = float(np.mean(improve_arr))

    # VaR pass counts
    var_pass_gjr = 0
    var_pass_a4f = 0
    es_pass_gjr = 0
    es_pass_a4f = 0
    total_var_tests = 0
    for rk in refit_keys:
        rr = refit_res[rk]
        for alpha_label in ['2.5%', '1%']:
            total_var_tests += 1
            if rr['var_es_backtesting'][f'VaR_{alpha_label}']['GJR']['pass'] == 'PASS':
                var_pass_gjr += 1
            if rr['var_es_backtesting'][f'VaR_{alpha_label}']['A4f_VIX']['pass'] == 'PASS':
                var_pass_a4f += 1
            if rr['var_es_backtesting'][f'ES_{alpha_label}']['GJR']['pass'] == 'PASS':
                es_pass_gjr += 1
            if rr['var_es_backtesting'][f'ES_{alpha_label}']['A4f_VIX']['pass'] == 'PASS':
                es_pass_a4f += 1

    robustness[asset] = {
        'qlike_gjr_cv': round(cv_gjr, 6),
        'qlike_a4f_cv': round(cv_a4f, 6),
        'dm_t_mean': round(dm_mean, 4),
        'dm_t_min': round(dm_min, 4),
        'dm_t_max': round(dm_max, 4),
        'dm_t_range': round(dm_range, 4),
        'n_harvey_significant': n_sig,
        'n_refit_tested': len(REFIT_FREQS),
        'qlike_improvement_mean_pct': round(improve_mean, 2),
        'qlike_improvement_range_pct': round(improve_range, 2),
        'var_pass_gjr': f'{var_pass_gjr}/{total_var_tests}',
        'var_pass_a4f': f'{var_pass_a4f}/{total_var_tests}',
        'es_pass_gjr': f'{es_pass_gjr}/{total_var_tests}',
        'es_pass_a4f': f'{es_pass_a4f}/{total_var_tests}',
    }

    print(f"\n  {asset}:")
    print(f"    QLIKE CV (GJR): {cv_gjr:.6f}, (A4f): {cv_a4f:.6f}")
    print(f"    DM t-stat: mean={dm_mean:.3f}, range=[{dm_min:.3f}, {dm_max:.3f}]")
    print(f"    Harvey significant: {n_sig}/{len(REFIT_FREQS)}")
    print(f"    QLIKE improvement: mean={improve_mean:.2f}%, range={improve_range:.2f}%")
    print(f"    VaR PASS: GJR {var_pass_gjr}/{total_var_tests}, A4f {var_pass_a4f}/{total_var_tests}")
    print(f"    ES PASS:  GJR {es_pass_gjr}/{total_var_tests}, A4f {es_pass_a4f}/{total_var_tests}")


# Overall robustness verdict
overall_robust = True
for asset in ASSETS:
    rb = robustness[asset]
    if rb['n_harvey_significant'] < 3:
        overall_robust = False
    if rb['qlike_a4f_cv'] > 0.05:  # CV > 5% = not robust
        overall_robust = False

verdict = 'ROBUST' if overall_robust else 'MIXED'
print(f"\n  Overall robustness verdict: {verdict}")


# ============================================================
# CHARTS
# ============================================================
print("\n[Charts] Generating...")

# Chart 1: QLIKE vs Refit Frequency
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

for idx, asset in enumerate(ASSETS):
    ax = axes[idx]
    ar = all_results[asset]
    refit_res = ar['refit_results']
    refit_keys = sorted(refit_res.keys(), key=lambda x: int(x))
    freqs = [int(k) for k in refit_keys]

    qlike_gjr_vals = [refit_res[k]['gjr']['qlike'] for k in refit_keys]
    qlike_a4f_vals = [refit_res[k]['a4f_vix']['qlike'] for k in refit_keys]

    ax.plot(freqs, qlike_gjr_vals, 'o-', color='#1f77b4', label='GJR-t', linewidth=2, markersize=8)
    ax.plot(freqs, qlike_a4f_vals, 's-', color='#d62728', label='A4f-VIX-t', linewidth=2, markersize=8)

    ax.set_xlabel('Refit Frequency (trading days)', fontsize=12)
    ax.set_ylabel('QLIKE', fontsize=12)
    ax.set_title(f'{asset}', fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)
    ax.set_xticks(freqs)
    ax.set_xticklabels(['21\n(M)', '42\n(2M)', '63\n(Q)', '126\n(6M)', '252\n(Y)'])
    ax.grid(True, alpha=0.3)

    # Annotate improvement
    for i, k in enumerate(refit_keys):
        imp = refit_res[k]['qlike_improvement_pct']
        ax.annotate(f'{imp:.1f}%', (freqs[i], qlike_a4f_vals[i]),
                    textcoords="offset points", xytext=(0, -18),
                    ha='center', fontsize=9, color='#d62728')

fig.suptitle('K1033: QLIKE vs Refit Frequency — A4f-VIX Robustness', fontsize=15, fontweight='bold')
plt.tight_layout()
chart1_path = os.path.join(SCRIPT_DIR, 'k1033_qlike_vs_refit.png')
plt.savefig(chart1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart1_path}")


# Chart 2: DM t-stat vs Refit Frequency
fig, ax = plt.subplots(figsize=(10, 6))

x_positions = np.arange(len(REFIT_FREQS))
bar_width = 0.35

for idx, asset in enumerate(ASSETS):
    ar = all_results[asset]
    refit_res = ar['refit_results']
    refit_keys = sorted(refit_res.keys(), key=lambda x: int(x))
    dm_vals = [refit_res[k]['dm_test']['dm_t'] for k in refit_keys]

    offset = -bar_width/2 + idx * bar_width
    bars = ax.bar(x_positions + offset, dm_vals, bar_width, label=asset,
                  color=['#1f77b4', '#ff7f0e'][idx], alpha=0.85, edgecolor='black', linewidth=0.5)

    # Add value labels
    for j, v in enumerate(dm_vals):
        ax.text(x_positions[j] + offset, v + 0.1, f'{v:.2f}',
                ha='center', va='bottom', fontsize=9, fontweight='bold')

# Harvey threshold lines
ax.axhline(y=3.0, color='red', linestyle='--', linewidth=1.5, alpha=0.7, label='Harvey |t|=3.0')
ax.axhline(y=-3.0, color='red', linestyle='--', linewidth=1.5, alpha=0.7)
ax.axhline(y=0, color='black', linewidth=0.5)

ax.set_xlabel('Refit Frequency (trading days)', fontsize=12)
ax.set_ylabel('DM t-statistic (A4f vs GJR)', fontsize=12)
ax.set_title('K1033: DM t-statistic Stability Across Refit Frequencies', fontsize=14, fontweight='bold')
ax.set_xticks(x_positions)
ax.set_xticklabels(['21\n(Monthly)', '42\n(Bi-monthly)', '63\n(Quarterly)',
                     '126\n(Semi-annual)', '252\n(Annual)'])
ax.legend(fontsize=11)
ax.grid(True, axis='y', alpha=0.3)

plt.tight_layout()
chart2_path = os.path.join(SCRIPT_DIR, 'k1033_dm_vs_refit.png')
plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart2_path}")


# Chart 3: Summary heatmap — QLIKE improvement % by asset x refit
fig, ax = plt.subplots(figsize=(10, 4))

data_matrix = []
for asset in ASSETS:
    ar = all_results[asset]
    refit_res = ar['refit_results']
    refit_keys = sorted(refit_res.keys(), key=lambda x: int(x))
    row = [refit_res[k]['qlike_improvement_pct'] for k in refit_keys]
    data_matrix.append(row)

data_matrix = np.array(data_matrix)
im = ax.imshow(data_matrix, cmap='RdYlGn', aspect='auto')

ax.set_xticks(np.arange(len(REFIT_FREQS)))
ax.set_xticklabels([f'{f}\n({"M" if f==21 else "2M" if f==42 else "Q" if f==63 else "6M" if f==126 else "Y"})'
                     for f in REFIT_FREQS])
ax.set_yticks(np.arange(len(ASSETS)))
ax.set_yticklabels(ASSETS)

# Add text annotations
for i in range(len(ASSETS)):
    for j in range(len(REFIT_FREQS)):
        text = ax.text(j, i, f'{data_matrix[i, j]:.1f}%',
                       ha='center', va='center', fontsize=12, fontweight='bold')

ax.set_xlabel('Refit Frequency (trading days)', fontsize=12)
ax.set_title('K1033: QLIKE Improvement (A4f vs GJR) by Asset and Refit Frequency',
             fontsize=13, fontweight='bold')
plt.colorbar(im, ax=ax, label='QLIKE Improvement (%)', shrink=0.8)
plt.tight_layout()
chart3_path = os.path.join(SCRIPT_DIR, 'k1033_improvement_heatmap.png')
plt.savefig(chart3_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart3_path}")


# ============================================================
# SUMMARY TABLE (for paper)
# ============================================================
print(f"\n{'='*70}")
print("SUMMARY TABLE (for Paper 9)")
print(f"{'='*70}")

header = f"{'Asset':<6} {'Refit':<8} {'QLIKE_GJR':<12} {'QLIKE_A4f':<12} {'Improv%':<10} {'DM_t':<8} {'Harvey':<8}"
print(header)
print("-" * len(header))

for asset in ASSETS:
    ar = all_results[asset]
    refit_res = ar['refit_results']
    refit_keys = sorted(refit_res.keys(), key=lambda x: int(x))
    for rk in refit_keys:
        rr = refit_res[rk]
        sig_marker = 'SIG ***' if rr['dm_test']['significant_harvey'] else 'n.s.'
        print(f"{asset:<6} {rk:<8} {rr['gjr']['qlike']:<12.6f} {rr['a4f_vix']['qlike']:<12.6f} "
              f"{rr['qlike_improvement_pct']:<10.2f} {rr['dm_test']['dm_t']:<8.3f} {sig_marker:<8}")


# ============================================================
# SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME
print(f"\nTotal elapsed time: {elapsed:.1f}s ({elapsed/60:.1f}m)")

final_results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'A4f Refit Frequency Sensitivity (Paper 9 Robustness)',
    'description': 'Tests A4f-VIX model stability across 5 refit frequencies (21/42/63/126/252 days) for SPY and QQQ',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance',
    'configuration': {
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'window': WINDOW,
        'df_fixed': DF_FIXED,
        'refit_frequencies': REFIT_FREQS,
        'assets': ASSETS,
        'seed': 42,
    },
    'asset_results': all_results,
    'robustness_analysis': robustness,
    'overall_verdict': verdict,
    'references': [
        'Engle, Ghysels & Sohn (2013). RES 95(3):776-797',
        'Engle & Rangel (2008). RFS 21(3):1187-1222',
        'Patton (2011). J Econometrics 160:246-256',
        'Harvey et al. (2016). t>3.0 threshold',
        'Kupiec (1995). Journal of Derivatives 3:73-84',
        'Acerbi & Szekely (2014). ES backtesting',
    ],
    'related_experiments': ['K988', 'K1003', 'K783b', 'K1030'],
    'elapsed_time_s': round(elapsed, 1),
    'charts': [
        'k1033_qlike_vs_refit.png',
        'k1033_dm_vs_refit.png',
        'k1033_improvement_heatmap.png',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)
print(f"\nResults saved to: {RESULTS_PATH}")

print(f"\n{'='*70}")
print(f"K1033 COMPLETE")
print(f"{'='*70}")
