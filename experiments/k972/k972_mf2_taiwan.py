"""
K972: MF2-VIX Taiwan Validation — 0050.TW with VIX Lead-Lag

Cross-market validation of K970 (MF2-GARCH on SPY).
Tests whether VIX lead-lag effect amplifies MF2-VIX performance on Taiwan ETF.

Key differences from K970 (SPY):
  - Asset: 0050.TW (Taiwan Top 50 ETF) instead of SPY
  - VIX alignment: use VIX[t-1] (previous US close) for Taiwan day t
    + tau shift(1) = total shift(2): VIX[t-2] -> tau[t-1] -> forecast for t
  - 0050.TW split fix via clean_tw50_data()
  - Taiwan has higher vol (amplification ~4.6x) and US lead-lag

Variants:
  MF2-RV:  tau = 22-day rolling RV of 0050.TW r^2
  MF2-VIX: tau = (VIX_shifted / sqrt(252))^2 (cross-market, shifted)
  MF2-EMA: tau = EMA of 0050.TW r^2 (halflife=22)
  Baseline: standard GJR-GARCH(1,1) on 0050.TW

Data: 0050.TW + ^VIX from yfinance, 2006-2026
IS: 2006-2018, OOS: 2019-2026
Target: r^2 (close-to-close squared return)

References:
  - Conrad, C. & Engle, R. (2025). Two-component GARCH models with exogenous
    long-run dynamics. J. Applied Econometrics.
  - Engle, R., Ghysels, E., & Sohn, B. (2013). Stock market volatility and
    macroeconomic fundamentals. Review of Economics and Statistics.
  - Patton, A.J. (2011). Volatility forecast comparison using imperfect
    volatility proxies. J. Econometrics, 160(1), 246-256.

Data source: yfinance (0050.TW, ^VIX), 2006-01-01 to 2026-04-07
"""

import numpy as np
import pandas as pd
import json
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
import sys
import os

np.random.seed(42)
warnings.filterwarnings('ignore')

# Add project root to path for volpred.utils
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

from volpred.utils import clean_tw50_data

# ============================================================
# 1. Data Download
# ============================================================
import yfinance as yf

print("Downloading 0050.TW and VIX data...")
tw50_raw = yf.download('0050.TW', start='2006-01-01', end='2026-04-07', progress=False)
vix_raw = yf.download('^VIX', start='2006-01-01', end='2026-04-07', progress=False)

# Handle multi-level columns from yfinance
if isinstance(tw50_raw.columns, pd.MultiIndex):
    tw50_raw.columns = tw50_raw.columns.get_level_values(0)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)

# Clean 0050.TW split artifacts
prices_raw = tw50_raw['Close'].squeeze()
clean_prices, clean_returns = clean_tw50_data(prices_raw)

tw50 = pd.DataFrame({
    'Close': clean_prices,
    'ret': clean_returns * 100  # log-approx % returns from pct_change
})

# Use log returns for GARCH consistency
tw50['ret'] = np.log(clean_prices / clean_prices.shift(1)) * 100
tw50 = tw50.dropna(subset=['ret'])

# Squared returns as proxy for realized variance
tw50['r2'] = tw50['ret'] ** 2

print(f"0050.TW: {len(tw50)} obs, {tw50.index[0].date()} to {tw50.index[-1].date()}")

# Descriptive stats
print(f"\n--- Descriptive Statistics (0050.TW daily log returns %) ---")
ret_series = tw50['ret']
print(f"  Mean:     {ret_series.mean():.4f}%")
print(f"  Std:      {ret_series.std():.4f}%")
print(f"  Skewness: {ret_series.skew():.4f}")
print(f"  Kurtosis: {ret_series.kurtosis():.4f}")
print(f"  Min:      {ret_series.min():.4f}%")
print(f"  Max:      {ret_series.max():.4f}%")

# ADF test
from statsmodels.tsa.stattools import adfuller
adf_stat, adf_p, _, _, _, _ = adfuller(ret_series.dropna(), maxlag=20)
print(f"  ADF stat: {adf_stat:.4f}, p-value: {adf_p:.6f}")

# ARCH LM test
from statsmodels.stats.diagnostic import het_arch
arch_lm_stat, arch_lm_p, _, _ = het_arch(ret_series.dropna(), nlags=10)
print(f"  ARCH LM(10): stat={arch_lm_stat:.4f}, p={arch_lm_p:.6f}")

# ============================================================
# 2. VIX Alignment (Cross-Market Lag)
# ============================================================
# Taiwan trades when US is closed.
# Use PREVIOUS DAY's VIX close as the VIX reference for Taiwan day t.
# This is the natural information set — when Taiwan opens at 09:00,
# the most recent VIX close is from the prior US session.

vix_close = vix_raw['Close'].squeeze()

# Step 1: Shift VIX by 1 day (use previous close)
vix_shifted = vix_close.shift(1)

# Step 2: Reindex to Taiwan trading days, forward-fill weekends/holidays
vix_tw = vix_shifted.reindex(tw50.index).ffill()

print(f"\nVIX aligned to TW: {vix_tw.notna().sum()} obs")
print(f"VIX TW range: {vix_tw.min():.2f} to {vix_tw.max():.2f}")

# ============================================================
# 3. Long-run component construction
# ============================================================

def compute_tau_rv(r2, window=22):
    """Rolling 22-day realized variance (average of r^2).
    Shifted by 1 to avoid using r2[t] when forecasting r2[t]."""
    tau = r2.rolling(window=window, min_periods=window).mean().shift(1)
    return tau

def compute_tau_vix(vix_level):
    """VIX-based long-run component: (VIX/sqrt(252))^2 = daily implied variance.
    NOTE: vix_level is ALREADY shifted by 1 due to cross-market lag.
    We add another shift(1) so tau uses VIX[t-2] for forecasting day t.
    Total lag = 2 days: VIX[t-2] -> tau[t-1] -> forecast sigma2[t]."""
    tau = ((vix_level / np.sqrt(252)) ** 2).shift(1)
    return tau

def compute_tau_ema(r2, halflife=22):
    """EMA of squared returns.
    Shifted by 1 to avoid data leakage."""
    tau = r2.ewm(halflife=halflife, min_periods=22).mean().shift(1)
    return tau

# Compute all tau variants
tw50['tau_rv'] = compute_tau_rv(tw50['r2'])
tw50['tau_vix'] = compute_tau_vix(vix_tw)
tw50['tau_ema'] = compute_tau_ema(tw50['r2'])

# Floor tau to avoid division by zero
for col in ['tau_rv', 'tau_vix', 'tau_ema']:
    tw50[col] = tw50[col].clip(lower=1e-6)

# Drop rows where any tau is missing
tw50 = tw50.dropna(subset=['tau_rv', 'tau_vix', 'tau_ema'])
print(f"After tau computation: {len(tw50)} obs")

# ============================================================
# 4. IS/OOS Split
# ============================================================
IS_END = '2018-12-31'
OOS_START = '2019-01-02'

is_mask = tw50.index <= IS_END
oos_mask = tw50.index >= OOS_START

tw50_is = tw50[is_mask].copy()
tw50_oos = tw50[oos_mask].copy()

print(f"IS: {len(tw50_is)} obs ({tw50_is.index[0].date()} to {tw50_is.index[-1].date()})")
print(f"OOS: {len(tw50_oos)} obs ({tw50_oos.index[0].date()} to {tw50_oos.index[-1].date()})")

# ============================================================
# 5. GJR-GARCH estimation helpers
# ============================================================
from arch import arch_model

def fit_gjr(returns, dist='t'):
    """Fit GJR-GARCH(1,1) with Student-t errors."""
    am = arch_model(returns, vol='GARCH', p=1, o=1, q=1, dist=dist, mean='Zero')
    res = am.fit(disp='off', show_warning=False)
    return res

def gjr_recursion(params, returns, initial_var):
    """
    Run GJR-GARCH(1,1) recursion with fixed parameters.
    h[t] = omega + alpha*r2[t-1] + gamma*r2[t-1]*I(r[t-1]<0) + beta*h[t-1]
    """
    omega = params['omega']
    alpha = params['alpha[1]']
    gamma = params['gamma[1]']
    beta = params['beta[1]']

    n = len(returns)
    h = np.zeros(n)
    h[0] = initial_var

    r = returns.values if hasattr(returns, 'values') else returns

    for t in range(1, n):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        h[t] = omega + alpha * r[t-1]**2 + gamma * r[t-1]**2 * indicator + beta * h[t-1]
        h[t] = max(h[t], 1e-8)

    return h

# ============================================================
# 6. Model estimation and OOS forecasting
# ============================================================

results = {}

# --- 6a. Baseline GJR-GARCH ---
print("\n=== Baseline GJR-GARCH (0050.TW) ===")
res_gjr = fit_gjr(tw50_is['ret'])
print(f"  Convergence: {res_gjr.convergence_flag == 0}")
params_gjr = res_gjr.params
print(f"  omega={params_gjr['omega']:.6f}, alpha={params_gjr['alpha[1]']:.6f}, "
      f"gamma={params_gjr['gamma[1]']:.6f}, beta={params_gjr['beta[1]']:.6f}")
persistence = params_gjr['alpha[1]'] + params_gjr['gamma[1]']/2 + params_gjr['beta[1]']
print(f"  Persistence: {persistence:.4f}")

if 'nu' in params_gjr.index:
    print(f"  Student-t df: {params_gjr['nu']:.4f}")

# Check persistence < 1
if persistence >= 1.0:
    print("  WARNING: persistence >= 1.0, model may be non-stationary!")

# OOS recursion for baseline
last_is_h = res_gjr.conditional_volatility.iloc[-1] ** 2
last_is_r = tw50_is['ret'].iloc[-1]
last_is_r2 = last_is_r ** 2
last_is_ind = 1.0 if last_is_r < 0 else 0.0
initial_var_gjr = (params_gjr['omega'] + params_gjr['alpha[1]'] * last_is_r2
                   + params_gjr['gamma[1]'] * last_is_r2 * last_is_ind
                   + params_gjr['beta[1]'] * last_is_h)

oos_h_gjr = gjr_recursion(params_gjr, tw50_oos['ret'], initial_var_gjr)
results['GJR'] = {
    'forecast': oos_h_gjr,
    'params': {k: float(v) for k, v in params_gjr.items()},
    'persistence': float(persistence)
}

# --- 6b. MF2 variants ---
tau_variants = {
    'MF2-RV': 'tau_rv',
    'MF2-VIX': 'tau_vix',
    'MF2-EMA': 'tau_ema'
}

for name, tau_col in tau_variants.items():
    print(f"\n=== {name} (0050.TW) ===")

    # Standardize IS returns by long-run component
    tau_is = tw50_is[tau_col].values
    r_tilde_is = tw50_is['ret'].values / np.sqrt(tau_is)

    # Fit GJR on standardized returns
    r_tilde_series = pd.Series(r_tilde_is, index=tw50_is.index)
    res_mf2 = fit_gjr(r_tilde_series)
    params_mf2 = res_mf2.params
    print(f"  Convergence: {res_mf2.convergence_flag == 0}")
    print(f"  omega={params_mf2['omega']:.6f}, alpha={params_mf2['alpha[1]']:.6f}, "
          f"gamma={params_mf2['gamma[1]']:.6f}, beta={params_mf2['beta[1]']:.6f}")
    p_mf2 = params_mf2['alpha[1]'] + params_mf2['gamma[1]']/2 + params_mf2['beta[1]']
    print(f"  Persistence (short-run): {p_mf2:.4f}")

    # OOS: standardize returns by tau, then run GJR recursion
    tau_oos = tw50_oos[tau_col].values
    r_tilde_oos = tw50_oos['ret'].values / np.sqrt(tau_oos)

    # Compute proper one-step-ahead forecast for short-run component
    last_is_g = res_mf2.conditional_volatility.iloc[-1] ** 2
    last_is_rtilde = r_tilde_is[-1]
    last_is_rtilde2 = last_is_rtilde ** 2
    last_is_ind_mf2 = 1.0 if last_is_rtilde < 0 else 0.0
    initial_var_mf2 = (params_mf2['omega'] + params_mf2['alpha[1]'] * last_is_rtilde2
                       + params_mf2['gamma[1]'] * last_is_rtilde2 * last_is_ind_mf2
                       + params_mf2['beta[1]'] * last_is_g)
    r_tilde_series_oos = pd.Series(r_tilde_oos, index=tw50_oos.index)
    oos_g = gjr_recursion(params_mf2, r_tilde_series_oos, initial_var_mf2)

    # Final forecast: sigma2 = tau * g
    oos_h_mf2 = tau_oos * oos_g

    results[name] = {
        'forecast': oos_h_mf2,
        'params': {k: float(v) for k, v in params_mf2.items()},
        'persistence_short': float(p_mf2),
        'tau_col': tau_col
    }

# ============================================================
# 7. Evaluation
# ============================================================
print("\n" + "="*60)
print("OOS EVALUATION (0050.TW)")
print("="*60)

r2_oos = tw50_oos['r2'].values
ret_oos = tw50_oos['ret'].values

def qlike(actual, forecast):
    """QLIKE loss: log(h) + r2/h (Patton 2011, proxy-robust)."""
    h = np.maximum(forecast, 1e-8)
    return np.mean(np.log(h) + actual / h)

def mse(actual, forecast):
    """MSE loss."""
    return np.mean((actual - forecast) ** 2)

def mz_regression(actual, forecast):
    """Mincer-Zarnowitz regression: r2 = a + b*h + e."""
    from numpy.linalg import lstsq
    X = np.column_stack([np.ones(len(forecast)), forecast])
    coefs, _, _, _ = lstsq(X, actual, rcond=None)
    y_hat = X @ coefs
    ss_res = np.sum((actual - y_hat) ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    r2_score = 1 - ss_res / ss_tot
    return {'intercept': float(coefs[0]), 'slope': float(coefs[1]), 'R2': float(r2_score)}

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test (two-sided)."""
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n

    if var_d <= 0:
        return {'t_stat': 0.0, 'p_value': 1.0}

    t_stat = d_bar / np.sqrt(var_d)
    from scipy import stats
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return {'t_stat': float(t_stat), 'p_value': float(p_value)}

# Compute losses
model_names = ['GJR', 'MF2-RV', 'MF2-VIX', 'MF2-EMA']
losses_qlike = {}
losses_mse = {}

print(f"\n{'Model':<12} {'QLIKE':>10} {'MSE':>12} {'MZ-R2':>8} {'MZ-slope':>10}")
print("-" * 55)

eval_results = {}
for name in model_names:
    h = results[name]['forecast']
    q = qlike(r2_oos, h)
    m = mse(r2_oos, h)
    mz = mz_regression(r2_oos, h)

    losses_qlike[name] = np.log(np.maximum(h, 1e-8)) + r2_oos / np.maximum(h, 1e-8)
    losses_mse[name] = (r2_oos - h) ** 2

    print(f"{name:<12} {q:>10.4f} {m:>12.4f} {mz['R2']:>8.4f} {mz['slope']:>10.4f}")

    eval_results[name] = {
        'QLIKE': float(q),
        'MSE': float(m),
        'MZ_R2': mz['R2'],
        'MZ_intercept': mz['intercept'],
        'MZ_slope': mz['slope']
    }

# DM tests (all pairs, QLIKE-based)
print(f"\n{'Pair':<25} {'DM-stat':>10} {'p-value':>10} {'Harvey |t|>3':>14}")
print("-" * 62)

dm_results = {}
for i, m1 in enumerate(model_names):
    for m2 in model_names[i+1:]:
        dm = dm_test(losses_qlike[m1], losses_qlike[m2])
        pair = f"{m1} vs {m2}"
        sig = "YES" if abs(dm['t_stat']) > 3.0 else "no"
        print(f"{pair:<25} {dm['t_stat']:>10.3f} {dm['p_value']:>10.4f} {sig:>14}")
        dm_results[pair] = dm

# QLIKE improvement percentages
gjr_qlike = eval_results['GJR']['QLIKE']
improvements = {}
for m in model_names:
    if m != 'GJR':
        improvements[m] = (gjr_qlike - eval_results[m]['QLIKE']) / abs(gjr_qlike) * 100

print(f"\nQLIKE improvements over GJR:")
for m, imp in improvements.items():
    direction = "better" if imp > 0 else "worse"
    print(f"  {m}: {imp:+.2f}% ({direction})")

# ============================================================
# 8. VaR Backtesting
# ============================================================
print("\n" + "="*60)
print("VaR BACKTESTING (0050.TW)")
print("="*60)

from scipy import stats as sp_stats

def var_backtest(returns, forecast_var, alpha=0.05, dist='t', df=5):
    """
    VaR backtesting with Kupiec and Christoffersen tests.
    VaR = mu + sigma * z_alpha (with Student-t scale correction)
    """
    sigma = np.sqrt(np.maximum(forecast_var, 1e-8))

    if dist == 't':
        scale = np.sqrt((df - 2) / df)
        z = sp_stats.t.ppf(alpha, df) * scale
    else:
        z = sp_stats.norm.ppf(alpha)

    var_level = z * sigma  # negative number
    violations = returns < var_level
    n_viol = violations.sum()
    n_total = len(returns)
    viol_rate = n_viol / n_total

    # Kupiec unconditional coverage test
    p_hat = viol_rate
    if p_hat == 0 or p_hat == 1:
        kupiec_stat = 0.0
        kupiec_p = 1.0
    else:
        lr = -2 * ((n_total - n_viol) * np.log((1 - alpha) / (1 - p_hat)) +
                    n_viol * np.log(alpha / p_hat))
        kupiec_stat = float(lr)
        kupiec_p = float(1 - sp_stats.chi2.cdf(abs(lr), 1))

    # Christoffersen independence test
    v = violations.astype(int)
    n00 = np.sum((v[:-1] == 0) & (v[1:] == 0))
    n01 = np.sum((v[:-1] == 0) & (v[1:] == 1))
    n10 = np.sum((v[:-1] == 1) & (v[1:] == 0))
    n11 = np.sum((v[:-1] == 1) & (v[1:] == 1))

    if (n00 + n01) > 0 and (n10 + n11) > 0 and n01 > 0 and n10 > 0:
        pi01 = n01 / (n00 + n01)
        pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
        pi = (n01 + n11) / (n00 + n01 + n10 + n11)

        if pi11 > 0 and pi11 < 1 and pi01 > 0 and pi01 < 1:
            lr_ind = -2 * (
                (n00 + n10) * np.log(1 - pi) + (n01 + n11) * np.log(pi)
                - n00 * np.log(1 - pi01) - n01 * np.log(pi01)
                - n10 * np.log(1 - pi11) - n11 * np.log(pi11)
            )
            christ_stat = float(lr_ind)
            christ_p = float(1 - sp_stats.chi2.cdf(abs(lr_ind), 1))
        else:
            christ_stat = 0.0
            christ_p = 1.0
    else:
        christ_stat = 0.0
        christ_p = 1.0

    return {
        'alpha': alpha,
        'n_violations': int(n_viol),
        'n_total': int(n_total),
        'violation_rate': float(viol_rate),
        'expected_rate': float(alpha),
        'kupiec_stat': kupiec_stat,
        'kupiec_p': kupiec_p,
        'christoffersen_stat': christ_stat,
        'christoffersen_p': christ_p
    }

# Get df from baseline GJR
df_t = float(params_gjr.get('nu', 5.0))

var_results = {}
for alpha_level in [0.01, 0.05]:
    print(f"\nVaR {int(alpha_level*100)}%:")
    print(f"{'Model':<12} {'Violations':>11} {'Rate':>8} {'Expected':>9} {'Kupiec-p':>10} {'Christ-p':>10}")
    print("-" * 63)

    for name in model_names:
        h = results[name]['forecast']
        vb = var_backtest(ret_oos, h, alpha=alpha_level, dist='t', df=df_t)
        key = f"{name}_VaR{int(alpha_level*100)}"
        var_results[key] = vb
        print(f"{name:<12} {vb['n_violations']:>5}/{vb['n_total']:<5} "
              f"{vb['violation_rate']:>8.4f} {vb['expected_rate']:>9.4f} "
              f"{vb['kupiec_p']:>10.4f} {vb['christoffersen_p']:>10.4f}")

# ============================================================
# 9. Cross-Market Comparison with K970 (SPY)
# ============================================================
print("\n" + "="*60)
print("CROSS-MARKET COMPARISON: 0050.TW vs SPY (K970)")
print("="*60)

# Load K970 results for comparison
k970_path = os.path.join(os.path.dirname(__file__), '..', 'k970', 'k970_mf2_garch_results.json')
k970_comparison = {}
if os.path.exists(k970_path):
    with open(k970_path, 'r') as f:
        k970_data = json.load(f)
    print("\nK970 (SPY) vs K972 (0050.TW) QLIKE comparison:")
    print(f"{'Model':<12} {'SPY QLIKE':>12} {'TW QLIKE':>12} {'SPY imp%':>10} {'TW imp%':>10}")
    print("-" * 58)

    for m in model_names:
        spy_q = k970_data['evaluation'].get(m, {}).get('QLIKE', 'N/A')
        tw_q = eval_results[m]['QLIKE']
        spy_imp = k970_data.get('qlike_improvements_pct', {}).get(m, 0.0) if m != 'GJR' else 0.0
        tw_imp = improvements.get(m, 0.0) if m != 'GJR' else 0.0

        if isinstance(spy_q, (int, float)):
            print(f"{m:<12} {spy_q:>12.4f} {tw_q:>12.4f} {spy_imp:>+10.2f} {tw_imp:>+10.2f}")
        else:
            print(f"{m:<12} {'N/A':>12} {tw_q:>12.4f} {'N/A':>10} {tw_imp:>+10.2f}")

    k970_comparison = {
        'spy_evaluation': k970_data.get('evaluation', {}),
        'spy_improvements': k970_data.get('qlike_improvements_pct', {}),
        'tw_evaluation': eval_results,
        'tw_improvements': improvements
    }
else:
    print("  K970 results not found, skipping cross-market comparison")

# ============================================================
# 10. Plots
# ============================================================

# --- 10a. Volatility Components ---
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

for ax, (name, col) in zip(axes, [('RV-22d', 'tau_rv'), ('VIX-implied (cross-mkt)', 'tau_vix'), ('EMA-22d', 'tau_ema')]):
    tau_vals = np.sqrt(tw50[col].values) * np.sqrt(252)  # annualized vol
    dates_all = tw50.index.to_numpy()
    ax.plot(dates_all, tau_vals, color='steelblue', alpha=0.7, linewidth=0.8)
    ax.axvline(pd.Timestamp(IS_END), color='red', linestyle='--', alpha=0.5, label='IS/OOS split')
    ax.set_ylabel('Ann. Vol (%)')
    ax.set_title(f'Long-run component ({name}) — 0050.TW')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('experiments/k972/k972_volatility_components.png', dpi=150, bbox_inches='tight')
plt.close()
print("\nSaved: k972_volatility_components.png")

# --- 10b. OOS Comparison ---
fig, axes = plt.subplots(2, 1, figsize=(14, 8))

# Top: forecasts vs realized
ax = axes[0]
dates_oos = tw50_oos.index.to_numpy()
ax.plot(dates_oos, np.sqrt(r2_oos) * np.sqrt(252), color='gray', alpha=0.3,
        linewidth=0.5, label='|r| (ann.)')
for name, color in zip(model_names, ['black', 'blue', 'red', 'green']):
    h = results[name]['forecast']
    ax.plot(dates_oos, np.sqrt(h) * np.sqrt(252), color=color,
            alpha=0.7, linewidth=0.8, label=name)
ax.set_ylabel('Annualized Vol (%)')
ax.set_title('OOS Volatility Forecasts — 0050.TW (2019-2026)')
ax.legend(loc='upper right', fontsize=8)
ax.grid(True, alpha=0.3)

# Bottom: cumulative QLIKE difference (MF2 vs GJR)
ax = axes[1]
for name, color in zip(['MF2-RV', 'MF2-VIX', 'MF2-EMA'], ['blue', 'red', 'green']):
    diff = losses_qlike['GJR'] - losses_qlike[name]  # positive = MF2 better
    cum_diff = np.cumsum(diff)
    ax.plot(dates_oos, cum_diff, color=color, linewidth=1.0, label=f'{name} gain')
ax.axhline(0, color='black', linestyle='--', alpha=0.3)
ax.set_ylabel('Cumulative QLIKE gain over GJR')
ax.set_title('Cumulative QLIKE Advantage of MF2 over GJR — 0050.TW (positive = MF2 better)')
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('experiments/k972/k972_oos_comparison.png', dpi=150, bbox_inches='tight')
plt.close()
print("Saved: k972_oos_comparison.png")

# ============================================================
# 11. Save Results
# ============================================================

best_model = min(eval_results, key=lambda x: eval_results[x]['QLIKE'])

output = {
    'experiment_id': 'K972',
    'title': 'MF2-VIX Taiwan Validation: 0050.TW with VIX Lead-Lag',
    'method': 'Conrad & Engle (2025) MF2-GARCH applied to Taiwan ETF with cross-market VIX',
    'data_source': 'yfinance (0050.TW, ^VIX)',
    'data_period': f"{tw50.index[0].date()} to {tw50.index[-1].date()}",
    'asset': '0050.TW',
    'baseline_asset_k970': 'SPY',
    'sample_sizes': {
        'total': int(len(tw50)),
        'IS': int(len(tw50_is)),
        'OOS': int(len(tw50_oos))
    },
    'IS_period': f"{tw50_is.index[0].date()} to {tw50_is.index[-1].date()}",
    'OOS_period': f"{tw50_oos.index[0].date()} to {tw50_oos.index[-1].date()}",
    'descriptive_stats': {
        'mean_ret_pct': float(ret_series.mean()),
        'std_ret_pct': float(ret_series.std()),
        'skewness': float(ret_series.skew()),
        'kurtosis': float(ret_series.kurtosis()),
        'adf_stat': float(adf_stat),
        'adf_p': float(adf_p),
        'arch_lm_stat': float(arch_lm_stat),
        'arch_lm_p': float(arch_lm_p)
    },
    'vix_alignment': {
        'method': 'VIX[t-1] shifted + ffill to Taiwan trading days',
        'total_lag_days': 2,
        'rationale': 'Taiwan opens at 09:00 when US is closed; use prior US close VIX + shift(1) for tau'
    },
    'models': {},
    'evaluation': eval_results,
    'dm_tests': dm_results,
    'qlike_improvements_pct': {k: float(v) for k, v in improvements.items()},
    'var_backtesting': var_results,
    'best_model': best_model,
    'cross_market_comparison': k970_comparison,
    'conclusion': '',
    'references': [
        'Conrad, C. & Engle, R. (2025). Two-component GARCH models with exogenous long-run dynamics. J. Applied Econometrics.',
        'Engle, R., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. Review of Economics and Statistics.',
        'Patton, A.J. (2011). Volatility forecast comparison using imperfect volatility proxies. J. Econometrics, 160(1), 246-256.',
        'Harvey, C.R., Liu, Y., & Zhu, H. (2016). ...and the cross-section of expected returns. Review of Financial Studies.'
    ],
    'seed': 42,
    'timestamp': datetime.now().isoformat()
}

# Model details
for name in model_names:
    info = {'params': results[name]['params']}
    if 'persistence' in results[name]:
        info['persistence'] = results[name]['persistence']
    if 'persistence_short' in results[name]:
        info['persistence_short'] = results[name]['persistence_short']
    output['models'][name] = info

# Generate conclusion
conclusion_parts = [
    f"Best model by QLIKE: {best_model} ({eval_results[best_model]['QLIKE']:.4f})",
    f"GJR baseline QLIKE: {gjr_qlike:.4f}",
]
for m, imp in improvements.items():
    direction = "improvement" if imp > 0 else "worse"
    conclusion_parts.append(f"{m}: {abs(imp):.2f}% {direction} over GJR")

# DM significance
sig_pairs = [p for p, v in dm_results.items() if abs(v['t_stat']) > 3.0]
if sig_pairs:
    conclusion_parts.append(f"Significant DM pairs (|t|>3.0): {', '.join(sig_pairs)}")
else:
    conclusion_parts.append("No pairs pass Harvey (2016) |t|>3.0 threshold")

# Cross-market summary
if k970_comparison:
    spy_vix_imp = k970_comparison.get('spy_improvements', {}).get('MF2-VIX', 0)
    tw_vix_imp = improvements.get('MF2-VIX', 0)
    if tw_vix_imp > spy_vix_imp:
        conclusion_parts.append(
            f"MF2-VIX improvement STRONGER on TW ({tw_vix_imp:+.2f}%) vs SPY ({spy_vix_imp:+.2f}%) — lead-lag amplification confirmed"
        )
    else:
        conclusion_parts.append(
            f"MF2-VIX improvement WEAKER on TW ({tw_vix_imp:+.2f}%) vs SPY ({spy_vix_imp:+.2f}%) — lead-lag not dominant"
        )

output['conclusion'] = '; '.join(conclusion_parts)

with open('experiments/k972/k972_mf2_taiwan_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

print("\n" + "="*60)
print("CONCLUSION")
print("="*60)
for part in conclusion_parts:
    print(f"  {part}")

print("\nResults saved to experiments/k972/k972_mf2_taiwan_results.json")
print("Done.")
