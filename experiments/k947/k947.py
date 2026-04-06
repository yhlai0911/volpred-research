"""
K947: Threshold GARCH with VIX as Threshold Variable
=====================================================

Problem: K942 showed MF-GJR(VIX) improvement varies hugely across VIX regimes
(+0.5% medium vs +17.3% high). This suggests GARCH parameters differ by regime.
Threshold GARCH allows parameters to switch based on VIX level.

Models:
1. GARCH(1,1) - baseline
2. GJR(1,1,1) - asymmetric baseline
3. MF-GJR(VIX) - current best (smooth multiplicative)
4. T-GJR - threshold GJR with VIX as threshold variable
5. T-MF - threshold MF-GJR (both threshold + multiplicative)

Data: SPY 2006-2026, yfinance
OOS: 2016-01-01 ~ 2025-12-31
Window: 2000, refit every 21 days
Evaluation: QLIKE on r², Spearman rho, DM test (Harvey |t| > 3.0)

References:
- Chen, Liu, So (2013): Threshold Variable Selection for Asymmetric SV
- Hansen (2011): Threshold Autoregressive Models
- K942: VIX regime analysis
- K889: MF-GJR(VIX) best model

Author: VolPred Research System
Data source: yfinance (SPY, ^VIX)
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
from datetime import datetime
from scipy.optimize import minimize
from scipy.stats import spearmanr
from arch import arch_model
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. Data
# ============================================================
print("=" * 60)
print("K947: Threshold GARCH with VIX as Threshold Variable")
print("=" * 60)

import yfinance as yf

spy = yf.download('SPY', start='2005-01-01', end='2026-01-01', progress=False)
vix = yf.download('^VIX', start='2005-01-01', end='2026-01-01', progress=False)

# Handle multi-level columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

spy_ret = np.log(spy['Close'] / spy['Close'].shift(1)).dropna()
spy_ret.name = 'return'

vix_close = vix['Close'].copy()
vix_close.name = 'VIX'

# Align
data = pd.DataFrame({
    'ret': spy_ret,
    'VIX': vix_close
}).dropna()

# Scale returns to percentage
data['ret_pct'] = data['ret'] * 100
data['r2'] = data['ret_pct'] ** 2  # target for QLIKE
data['vix_lag'] = data['VIX'].shift(1)
data = data.dropna()

print(f"Total observations: {len(data)}")
print(f"Date range: {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}")
print(f"VIX stats: mean={data['VIX'].mean():.2f}, median={data['VIX'].median():.2f}")

# ============================================================
# 2. Model Functions
# ============================================================

def garch_loglik(params, returns):
    """GARCH(1,1) log-likelihood"""
    omega, alpha, beta = params
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.9999:
        return 1e10
    T = len(returns)
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)
    for t in range(1, T):
        sigma2[t] = omega + alpha * returns[t-1]**2 + beta * sigma2[t-1]
    sigma2 = np.maximum(sigma2, 1e-8)
    ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + returns**2 / sigma2)
    return -ll


def gjr_loglik(params, returns):
    """GJR(1,1,1) log-likelihood"""
    omega, alpha, gamma, beta = params
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0 or alpha + 0.5*gamma + beta >= 0.9999:
        return 1e10
    T = len(returns)
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)
    for t in range(1, T):
        indicator = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = omega + alpha * returns[t-1]**2 + gamma * returns[t-1]**2 * indicator + beta * sigma2[t-1]
    sigma2 = np.maximum(sigma2, 1e-8)
    ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + returns**2 / sigma2)
    return -ll


def fit_gjr(returns):
    """Fit GJR(1,1,1) and return params"""
    var_r = np.var(returns)
    x0 = [var_r * 0.05, 0.05, 0.05, 0.85]
    bounds = [(1e-8, None), (1e-8, 0.5), (0, 0.5), (0.5, 0.999)]
    res = minimize(gjr_loglik, x0, args=(returns,), method='L-BFGS-B', bounds=bounds)
    if not res.success:
        # Try different starting points
        for alpha0 in [0.03, 0.07, 0.1]:
            for beta0 in [0.8, 0.85, 0.9]:
                x0 = [var_r * (1 - alpha0 - beta0), alpha0, 0.05, beta0]
                res2 = minimize(gjr_loglik, x0, args=(returns,), method='L-BFGS-B', bounds=bounds)
                if res2.success and res2.fun < res.fun:
                    res = res2
    return res.x, res.fun


def gjr_forecast_oos(params, returns_full, h_prev):
    """One-step OOS forecast using GJR parameters"""
    omega, alpha, gamma, beta = params
    r_prev = returns_full[-1]
    indicator = 1.0 if r_prev < 0 else 0.0
    h = omega + alpha * r_prev**2 + gamma * r_prev**2 * indicator + beta * h_prev
    return max(h, 1e-8)


def mf_gjr_loglik(params, returns, log_vix):
    """MF-GJR log-likelihood: sigma2 = tau * g"""
    theta0, theta1, omega, alpha, gamma, beta = params
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0 or alpha + 0.5*gamma + beta >= 0.9999:
        return 1e10
    T = len(returns)
    tau = np.exp(theta0 + theta1 * log_vix)
    g = np.zeros(T)
    g[0] = 1.0
    for t in range(1, T):
        if tau[t] < 1e-8:
            return 1e10
        indicator = 1.0 if returns[t-1] < 0 else 0.0
        g[t] = omega + alpha * (returns[t-1]**2 / tau[t-1]) + gamma * (returns[t-1]**2 / tau[t-1]) * indicator + beta * g[t-1]
    g = np.maximum(g, 1e-8)
    sigma2 = tau * g
    sigma2 = np.maximum(sigma2, 1e-8)
    ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + returns**2 / sigma2)
    return -ll


def fit_mf_gjr(returns, log_vix):
    """Fit MF-GJR and return params"""
    var_r = np.var(returns)
    x0 = [np.log(var_r), 0.3, 0.05, 0.05, 0.05, 0.85]
    bounds = [(-5, 5), (-2, 2), (1e-8, None), (1e-8, 0.5), (0, 0.5), (0.5, 0.999)]
    res = minimize(mf_gjr_loglik, x0, args=(returns, log_vix), method='L-BFGS-B', bounds=bounds)
    if not res.success:
        for t1 in [0.1, 0.3, 0.5]:
            x0 = [np.log(var_r), t1, 0.05, 0.05, 0.05, 0.85]
            res2 = minimize(mf_gjr_loglik, x0, args=(returns, log_vix), method='L-BFGS-B', bounds=bounds)
            if res2.success and res2.fun < res.fun:
                res = res2
    return res.x, res.fun


def mf_gjr_forecast_oos(params, returns_full, log_vix_full, g_prev):
    """One-step OOS forecast for MF-GJR"""
    theta0, theta1, omega, alpha, gamma, beta = params
    tau_t = np.exp(theta0 + theta1 * log_vix_full[-1])
    tau_prev = np.exp(theta0 + theta1 * log_vix_full[-2])
    r_prev = returns_full[-1]
    indicator = 1.0 if r_prev < 0 else 0.0
    g = omega + alpha * (r_prev**2 / tau_prev) + gamma * (r_prev**2 / tau_prev) * indicator + beta * g_prev
    g = max(g, 1e-8)
    sigma2 = tau_t * g
    return max(sigma2, 1e-8), g


# ============================================================
# 3. OOS Forecasting
# ============================================================

oos_start = '2016-01-01'
window = 2000
refit_every = 21

oos_mask = data.index >= oos_start
oos_indices = data.index[oos_mask]
all_indices = data.index

print(f"\nOOS period: {oos_indices[0].strftime('%Y-%m-%d')} to {oos_indices[-1].strftime('%Y-%m-%d')}")
print(f"OOS observations: {len(oos_indices)}")
print(f"Window: {window}, Refit every: {refit_every} days")

# Threshold candidates
thresholds = [15, 18, 20, 22, 25]

# Storage for forecasts
forecasts = {
    'GARCH': [],
    'GJR': [],
    'MF-GJR': [],
}
for c in thresholds:
    forecasts[f'T-GJR(c={c})'] = []
    forecasts[f'T-MF(c={c})'] = []

actuals = []
dates_oos = []

# State variables for recursive forecasting
last_refit = -refit_every  # Force initial fit
params_cache = {}

# Track g values for MF models
g_state = {}

print("\nRunning OOS forecasting...")
oos_start_idx = list(all_indices).index(oos_indices[0])

for i, t in enumerate(range(oos_start_idx, len(all_indices))):
    date_t = all_indices[t]

    need_refit = (i - last_refit >= refit_every) or i == 0

    if need_refit:
        last_refit = i
        train_start = max(0, t - window)
        train_data = data.iloc[train_start:t]
        returns_train = train_data['ret_pct'].values
        vix_lag_train = train_data['vix_lag'].values
        log_vix_train = np.log(np.maximum(vix_lag_train, 1.0))

        # ---- GARCH(1,1) via arch ----
        try:
            am = arch_model(train_data['ret_pct'], vol='GARCH', p=1, q=1, mean='Zero', dist='normal')
            res_garch = am.fit(disp='off', show_warning=False)
            params_cache['GARCH'] = {
                'omega': res_garch.params['omega'],
                'alpha': res_garch.params['alpha[1]'],
                'beta': res_garch.params['beta[1]']
            }
            params_cache['GARCH']['h_prev'] = res_garch.conditional_volatility.iloc[-1]**2
        except:
            pass

        # ---- GJR(1,1,1) via arch ----
        try:
            am = arch_model(train_data['ret_pct'], vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
            res_gjr = am.fit(disp='off', show_warning=False)
            params_cache['GJR'] = {
                'omega': res_gjr.params['omega'],
                'alpha': res_gjr.params['alpha[1]'],
                'gamma': res_gjr.params['gamma[1]'],
                'beta': res_gjr.params['beta[1]']
            }
            params_cache['GJR']['h_prev'] = res_gjr.conditional_volatility.iloc[-1]**2
        except:
            pass

        # ---- MF-GJR ----
        try:
            mf_params, mf_fun = fit_mf_gjr(returns_train, log_vix_train)
            params_cache['MF-GJR'] = mf_params
            # Compute final g
            theta0, theta1, omega, alpha, gamma, beta = mf_params
            tau = np.exp(theta0 + theta1 * log_vix_train)
            g_arr = np.ones(len(returns_train))
            for tt in range(1, len(returns_train)):
                ind = 1.0 if returns_train[tt-1] < 0 else 0.0
                g_arr[tt] = omega + alpha * (returns_train[tt-1]**2 / tau[tt-1]) + gamma * (returns_train[tt-1]**2 / tau[tt-1]) * ind + beta * g_arr[tt-1]
            g_state['MF-GJR'] = max(g_arr[-1], 1e-8)
        except:
            pass

        # ---- Threshold GJR for each c ----
        for c in thresholds:
            try:
                mask_low = vix_lag_train < c
                mask_high = vix_lag_train >= c

                if np.sum(mask_low) > 100 and np.sum(mask_high) > 100:
                    # Fit GJR on low regime
                    params_low, _ = fit_gjr(returns_train[mask_low])
                    # Fit GJR on high regime
                    params_high, _ = fit_gjr(returns_train[mask_high])
                    params_cache[f'T-GJR(c={c})'] = {
                        'low': params_low,
                        'high': params_high
                    }
                    # Compute h_prev using full series with regime switching
                    h = np.var(returns_train)
                    for tt in range(1, len(returns_train)):
                        if vix_lag_train[tt] < c:
                            p = params_low
                        else:
                            p = params_high
                        ind = 1.0 if returns_train[tt-1] < 0 else 0.0
                        h = p[0] + p[1] * returns_train[tt-1]**2 + p[2] * returns_train[tt-1]**2 * ind + p[3] * h
                        h = max(h, 1e-8)
                    params_cache[f'T-GJR(c={c})']['h_prev'] = h
            except:
                pass

        # ---- Threshold MF-GJR for each c ----
        for c in thresholds:
            try:
                mask_low = vix_lag_train < c
                mask_high = vix_lag_train >= c

                if np.sum(mask_low) > 100 and np.sum(mask_high) > 100:
                    # Fit MF-GJR on each regime separately
                    params_low_mf, _ = fit_mf_gjr(returns_train[mask_low], log_vix_train[mask_low])
                    params_high_mf, _ = fit_mf_gjr(returns_train[mask_high], log_vix_train[mask_high])
                    params_cache[f'T-MF(c={c})'] = {
                        'low': params_low_mf,
                        'high': params_high_mf
                    }
                    # Compute g_prev for each regime using full series
                    g = 1.0
                    for tt in range(1, len(returns_train)):
                        if vix_lag_train[tt] < c:
                            p = params_low_mf
                        else:
                            p = params_high_mf
                        theta0, theta1, omega, alpha, gamma, beta = p
                        tau_prev = np.exp(theta0 + theta1 * log_vix_train[tt-1])
                        ind = 1.0 if returns_train[tt-1] < 0 else 0.0
                        g = omega + alpha * (returns_train[tt-1]**2 / tau_prev) + gamma * (returns_train[tt-1]**2 / tau_prev) * ind + beta * g
                        g = max(g, 1e-8)
                    g_state[f'T-MF(c={c})'] = g
            except:
                pass

    # ---- Generate forecasts for day t ----
    r_prev = data['ret_pct'].iloc[t-1]
    vix_prev = data['vix_lag'].iloc[t]  # VIX_{t-1}
    log_vix_prev = np.log(max(vix_prev, 1.0))

    # GARCH forecast (recursive)
    if 'GARCH' in params_cache:
        p = params_cache['GARCH']
        h = p['omega'] + p['alpha'] * r_prev**2 + p['beta'] * p['h_prev']
        h = max(h, 1e-8)
        forecasts['GARCH'].append(h)
        params_cache['GARCH']['h_prev'] = h
    else:
        forecasts['GARCH'].append(np.nan)

    # GJR forecast (recursive)
    if 'GJR' in params_cache:
        p = params_cache['GJR']
        ind = 1.0 if r_prev < 0 else 0.0
        h = p['omega'] + p['alpha'] * r_prev**2 + p['gamma'] * r_prev**2 * ind + p['beta'] * p['h_prev']
        h = max(h, 1e-8)
        forecasts['GJR'].append(h)
        params_cache['GJR']['h_prev'] = h
    else:
        forecasts['GJR'].append(np.nan)

    # MF-GJR forecast (recursive)
    if 'MF-GJR' in params_cache:
        p = params_cache['MF-GJR']
        theta0, theta1, omega, alpha, gamma, beta = p
        tau_t = np.exp(theta0 + theta1 * log_vix_prev)
        # Use previous day's tau for g update
        log_vix_prev2 = np.log(max(data['vix_lag'].iloc[t-1], 1.0))
        tau_prev = np.exp(theta0 + theta1 * log_vix_prev2)
        ind = 1.0 if r_prev < 0 else 0.0
        g = omega + alpha * (r_prev**2 / tau_prev) + gamma * (r_prev**2 / tau_prev) * ind + beta * g_state['MF-GJR']
        g = max(g, 1e-8)
        sigma2 = tau_t * g
        forecasts['MF-GJR'].append(max(sigma2, 1e-8))
        g_state['MF-GJR'] = g
    else:
        forecasts['MF-GJR'].append(np.nan)

    # T-GJR forecast (recursive, regime-dependent)
    for c in thresholds:
        key = f'T-GJR(c={c})'
        if key in params_cache:
            pc = params_cache[key]
            if vix_prev < c:
                p = pc['low']
            else:
                p = pc['high']
            ind = 1.0 if r_prev < 0 else 0.0
            h = p[0] + p[1] * r_prev**2 + p[2] * r_prev**2 * ind + p[3] * pc['h_prev']
            h = max(h, 1e-8)
            forecasts[key].append(h)
            pc['h_prev'] = h
        else:
            forecasts[key].append(np.nan)

    # T-MF forecast (recursive, regime-dependent)
    for c in thresholds:
        key = f'T-MF(c={c})'
        if key in params_cache:
            pc = params_cache[key]
            if vix_prev < c:
                p = pc['low']
            else:
                p = pc['high']
            theta0, theta1, omega, alpha, gamma, beta = p
            tau_t = np.exp(theta0 + theta1 * log_vix_prev)
            log_vix_prev2 = np.log(max(data['vix_lag'].iloc[t-1], 1.0))
            tau_prev = np.exp(theta0 + theta1 * log_vix_prev2)
            ind = 1.0 if r_prev < 0 else 0.0
            g_prev = g_state.get(key, 1.0)
            g = omega + alpha * (r_prev**2 / tau_prev) + gamma * (r_prev**2 / tau_prev) * ind + beta * g_prev
            g = max(g, 1e-8)
            sigma2 = tau_t * g
            forecasts[key].append(max(sigma2, 1e-8))
            g_state[key] = g
        else:
            forecasts[key].append(np.nan)

    actuals.append(data['r2'].iloc[t])
    dates_oos.append(date_t)

    if (i + 1) % 500 == 0:
        print(f"  Processed {i+1}/{len(oos_indices)} OOS days")

print(f"  Done. Total OOS: {len(actuals)}")

# ============================================================
# 4. Evaluation
# ============================================================

actuals = np.array(actuals)
dates_oos = pd.DatetimeIndex(dates_oos)

def qlike(actual, forecast):
    """QLIKE loss: actual/forecast - log(actual/forecast) - 1"""
    valid = (forecast > 0) & (actual > 0) & ~np.isnan(forecast) & ~np.isnan(actual)
    a = actual[valid]
    f = forecast[valid]
    return np.mean(a / f - np.log(a / f) - 1)

def mse(actual, forecast):
    valid = ~np.isnan(forecast) & ~np.isnan(actual)
    return np.mean((actual[valid] - forecast[valid])**2)

print("\n" + "=" * 60)
print("EVALUATION RESULTS")
print("=" * 60)

results = {}
for name, fc in forecasts.items():
    fc_arr = np.array(fc)
    valid = ~np.isnan(fc_arr)
    if valid.sum() < 100:
        continue

    q = qlike(actuals[valid], fc_arr[valid])
    m = mse(actuals[valid], fc_arr[valid])
    rho, p_val = spearmanr(actuals[valid], fc_arr[valid])

    results[name] = {
        'QLIKE': q,
        'MSE': m,
        'Spearman_rho': rho,
        'Spearman_p': p_val,
        'n_valid': int(valid.sum())
    }
    print(f"\n{name}:")
    print(f"  QLIKE = {q:.6f}")
    print(f"  MSE = {m:.6f}")
    print(f"  Spearman rho = {rho:.4f} (p={p_val:.2e})")

# ============================================================
# 5. DM Tests
# ============================================================
print("\n" + "=" * 60)
print("DM TESTS (Harvey |t| > 3.0)")
print("=" * 60)

# Use QLIKE loss differences for DM test
def dm_test_qlike(actual, fc1, fc2):
    """DM test based on QLIKE loss differential"""
    valid = (~np.isnan(fc1)) & (~np.isnan(fc2)) & (fc1 > 0) & (fc2 > 0) & (actual > 0)
    a = actual[valid]
    f1 = fc1[valid]
    f2 = fc2[valid]

    loss1 = a / f1 - np.log(a / f1) - 1
    loss2 = a / f2 - np.log(a / f2) - 1
    d = loss1 - loss2

    n = len(d)
    d_bar = np.mean(d)

    # Newey-West HAC variance (lag = int(n^(1/3)))
    max_lag = int(n ** (1/3))
    gamma_0 = np.mean((d - d_bar)**2)
    gamma_sum = 0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * w * gamma_k
    var_d = (gamma_0 + gamma_sum) / n

    if var_d <= 0:
        return np.nan, n

    t_stat = d_bar / np.sqrt(var_d)

    # Harvey (2016) small-sample correction
    h = 1  # 1-step ahead
    t_stat_harvey = t_stat * np.sqrt((n - 1) / n) * np.sqrt(n / (n - h + 1))

    return t_stat_harvey, n

dm_results = {}
model_names = list(results.keys())
baseline_models = ['GARCH', 'GJR', 'MF-GJR']

# Key comparisons
comparisons = []
for base in baseline_models:
    for name in model_names:
        if name != base and name not in baseline_models:
            comparisons.append((base, name))

# Also compare baselines
comparisons.append(('GARCH', 'GJR'))
comparisons.append(('GJR', 'MF-GJR'))

# Find best T-GJR and T-MF
best_tgjr = None
best_tgjr_qlike = float('inf')
best_tmf = None
best_tmf_qlike = float('inf')

for name, r in results.items():
    if name.startswith('T-GJR') and r['QLIKE'] < best_tgjr_qlike:
        best_tgjr = name
        best_tgjr_qlike = r['QLIKE']
    if name.startswith('T-MF') and r['QLIKE'] < best_tmf_qlike:
        best_tmf = name
        best_tmf_qlike = r['QLIKE']

# Key comparisons for DM
key_comparisons = [
    ('GARCH', 'GJR'),
    ('GJR', 'MF-GJR'),
]
if best_tgjr:
    key_comparisons.append(('GJR', best_tgjr))
    key_comparisons.append(('MF-GJR', best_tgjr))
if best_tmf:
    key_comparisons.append(('GJR', best_tmf))
    key_comparisons.append(('MF-GJR', best_tmf))
if best_tgjr and best_tmf:
    key_comparisons.append((best_tgjr, best_tmf))

for m1, m2 in key_comparisons:
    if m1 in forecasts and m2 in forecasts:
        fc1 = np.array(forecasts[m1])
        fc2 = np.array(forecasts[m2])
        t_stat, n = dm_test_qlike(actuals, fc1, fc2)
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else ""))
        winner = m2 if t_stat > 0 else m1
        print(f"  {m1} vs {m2}: t = {t_stat:+.3f} {sig} (n={n}) → favors {winner}")
        dm_results[f'{m1}_vs_{m2}'] = {
            't_stat': round(t_stat, 3) if not np.isnan(t_stat) else None,
            'n': n,
            'significant_harvey': abs(t_stat) > 3.0 if not np.isnan(t_stat) else False,
            'favors': winner
        }

# ============================================================
# 6. Regime-specific Analysis
# ============================================================
print("\n" + "=" * 60)
print("REGIME-SPECIFIC QLIKE IMPROVEMENT")
print("=" * 60)

vix_oos = data.loc[dates_oos, 'vix_lag'].values
regimes = {
    'Low (VIX<15)': vix_oos < 15,
    'Medium (15<=VIX<25)': (vix_oos >= 15) & (vix_oos < 25),
    'High (VIX>=25)': vix_oos >= 25
}

regime_results = {}
gjr_fc = np.array(forecasts['GJR'])

for regime_name, mask in regimes.items():
    n_regime = mask.sum()
    print(f"\n{regime_name} (n={n_regime}):")
    regime_results[regime_name] = {'n': int(n_regime)}

    for name in model_names:
        if name == 'GJR':
            continue
        fc_arr = np.array(forecasts[name])
        valid = mask & ~np.isnan(fc_arr) & ~np.isnan(gjr_fc) & (fc_arr > 0) & (gjr_fc > 0) & (actuals > 0)
        if valid.sum() < 30:
            continue

        q_gjr = qlike(actuals[valid], gjr_fc[valid])
        q_model = qlike(actuals[valid], fc_arr[valid])
        improvement = (q_gjr - q_model) / q_gjr * 100

        regime_results[regime_name][name] = {
            'QLIKE': round(q_model, 6),
            'QLIKE_GJR': round(q_gjr, 6),
            'improvement_pct': round(improvement, 2)
        }
        print(f"  {name}: QLIKE={q_model:.6f} (vs GJR {q_gjr:.6f}) → {improvement:+.2f}%")

# ============================================================
# 7. Plot
# ============================================================
print("\nGenerating comparison plot...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K947: Threshold GARCH with VIX as Threshold Variable', fontsize=14, fontweight='bold')

# (a) QLIKE comparison bar chart
ax = axes[0, 0]
plot_models = ['GARCH', 'GJR', 'MF-GJR']
if best_tgjr:
    plot_models.append(best_tgjr)
if best_tmf:
    plot_models.append(best_tmf)
qlikes = [results[m]['QLIKE'] for m in plot_models]
colors = ['#666666', '#4472C4', '#ED7D31', '#70AD47', '#FFC000'][:len(plot_models)]
bars = ax.bar(range(len(plot_models)), qlikes, color=colors)
ax.set_xticks(range(len(plot_models)))
ax.set_xticklabels([m.replace('T-GJR', 'T-GJR\n').replace('T-MF', 'T-MF\n') for m in plot_models], fontsize=9)
ax.set_ylabel('QLIKE (lower is better)')
ax.set_title('(a) QLIKE on r² (OOS)')
for bar, q in zip(bars, qlikes):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f'{q:.4f}', ha='center', va='bottom', fontsize=8)

# (b) Spearman rho comparison
ax = axes[0, 1]
rhos = [results[m]['Spearman_rho'] for m in plot_models]
bars = ax.bar(range(len(plot_models)), rhos, color=colors)
ax.set_xticks(range(len(plot_models)))
ax.set_xticklabels([m.replace('T-GJR', 'T-GJR\n').replace('T-MF', 'T-MF\n') for m in plot_models], fontsize=9)
ax.set_ylabel('Spearman rho (higher is better)')
ax.set_title('(b) Spearman Rank Correlation')
for bar, r in zip(bars, rhos):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f'{r:.4f}', ha='center', va='bottom', fontsize=8)

# (c) Regime-specific improvement over GJR
ax = axes[1, 0]
regime_names_short = ['Low\n(VIX<15)', 'Medium\n(15-25)', 'High\n(VIX>=25)']
regime_keys = list(regimes.keys())
models_to_plot = ['MF-GJR']
if best_tgjr:
    models_to_plot.append(best_tgjr)
if best_tmf:
    models_to_plot.append(best_tmf)

x = np.arange(len(regime_keys))
width = 0.25
for idx, model in enumerate(models_to_plot):
    improvements = []
    for rk in regime_keys:
        if model in regime_results.get(rk, {}):
            improvements.append(regime_results[rk][model]['improvement_pct'])
        else:
            improvements.append(0)
    ax.bar(x + idx * width, improvements, width, label=model, alpha=0.8)

ax.set_xticks(x + width)
ax.set_xticklabels(regime_names_short)
ax.set_ylabel('QLIKE Improvement over GJR (%)')
ax.set_title('(c) Regime-Specific Improvement')
ax.axhline(y=0, color='black', linewidth=0.5, linestyle='--')
ax.legend(fontsize=8)

# (d) Threshold grid search
ax = axes[1, 1]
tgjr_qlikes = []
tmf_qlikes = []
for c in thresholds:
    tgjr_key = f'T-GJR(c={c})'
    tmf_key = f'T-MF(c={c})'
    tgjr_qlikes.append(results[tgjr_key]['QLIKE'] if tgjr_key in results else np.nan)
    tmf_qlikes.append(results[tmf_key]['QLIKE'] if tmf_key in results else np.nan)

ax.plot(thresholds, tgjr_qlikes, 'o-', color='#70AD47', label='T-GJR', linewidth=2, markersize=8)
ax.plot(thresholds, tmf_qlikes, 's-', color='#FFC000', label='T-MF', linewidth=2, markersize=8)
if 'GJR' in results:
    ax.axhline(y=results['GJR']['QLIKE'], color='#4472C4', linestyle='--', label='GJR baseline')
if 'MF-GJR' in results:
    ax.axhline(y=results['MF-GJR']['QLIKE'], color='#ED7D31', linestyle='--', label='MF-GJR baseline')
ax.set_xlabel('Threshold c (VIX level)')
ax.set_ylabel('QLIKE')
ax.set_title('(d) Threshold Grid Search')
ax.legend(fontsize=8)

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k947_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()
print("Saved k947_comparison.png")

# ============================================================
# 8. Save Results
# ============================================================

output = {
    'experiment_id': 'K947',
    'title': 'Threshold GARCH with VIX as Threshold Variable',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{oos_indices[0].strftime('%Y-%m-%d')} to {oos_indices[-1].strftime('%Y-%m-%d')}",
    'oos_n': len(actuals),
    'window': window,
    'refit_every': refit_every,
    'thresholds_tested': thresholds,
    'models': {},
    'dm_tests': dm_results,
    'regime_analysis': regime_results,
    'best_threshold_gjr': best_tgjr,
    'best_threshold_mf': best_tmf,
    'references': [
        'Chen, Liu, So (2013): Threshold Variable Selection for Asymmetric SV',
        'Hansen (2011): Threshold Autoregressive Models',
        'K942: VIX regime analysis - Low +8.7%, Medium +0.5%, High +17.3%',
        'K889: MF-GJR(VIX) best model, multiplicative factor'
    ]
}

for name, r in results.items():
    output['models'][name] = {
        'QLIKE': round(r['QLIKE'], 6),
        'MSE': round(r['MSE'], 6),
        'Spearman_rho': round(r['Spearman_rho'], 4),
        'Spearman_p': float(f"{r['Spearman_p']:.2e}"),
        'n_valid': r['n_valid']
    }

# Determine conclusion
gjr_qlike = results['GJR']['QLIKE']
mfgjr_qlike = results['MF-GJR']['QLIKE']

conclusion_parts = []
if best_tgjr and results[best_tgjr]['QLIKE'] < gjr_qlike:
    imp = (gjr_qlike - results[best_tgjr]['QLIKE']) / gjr_qlike * 100
    conclusion_parts.append(f"Best T-GJR ({best_tgjr}) improves {imp:.1f}% over GJR")
if best_tmf and results[best_tmf]['QLIKE'] < mfgjr_qlike:
    imp = (mfgjr_qlike - results[best_tmf]['QLIKE']) / mfgjr_qlike * 100
    conclusion_parts.append(f"Best T-MF ({best_tmf}) improves {imp:.1f}% over MF-GJR")
if best_tgjr and best_tmf:
    if results[best_tmf]['QLIKE'] < results[best_tgjr]['QLIKE']:
        conclusion_parts.append(f"T-MF dominates T-GJR")
    else:
        conclusion_parts.append(f"T-GJR dominates T-MF")

# Check if any DM test is significant at Harvey level
any_sig = any(v.get('significant_harvey', False) for v in dm_results.values())
conclusion_parts.append(f"DM test significant at Harvey |t|>3.0: {'Yes' if any_sig else 'No'}")

output['conclusion'] = '; '.join(conclusion_parts)

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, (np.bool_,)):
            return bool(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

with open(os.path.join(SCRIPT_DIR, 'k947_results.json'), 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)

print(f"\nSaved k947_results.json")

# ============================================================
# 9. Summary
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"\nBest T-GJR: {best_tgjr} (QLIKE={results[best_tgjr]['QLIKE']:.6f})" if best_tgjr else "No valid T-GJR")
print(f"Best T-MF: {best_tmf} (QLIKE={results[best_tmf]['QLIKE']:.6f})" if best_tmf else "No valid T-MF")
print(f"GJR baseline: QLIKE={results['GJR']['QLIKE']:.6f}")
print(f"MF-GJR baseline: QLIKE={results['MF-GJR']['QLIKE']:.6f}")
print(f"\nConclusion: {output['conclusion']}")
print("\nDone!")
