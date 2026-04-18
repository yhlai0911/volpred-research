#!/usr/bin/env python3
"""
K493: GJR-X(VIX9D) Real-Time Signal Analysis
=============================================
Background:
  K490: GJR-X(VIX9D) is best forecaster (3/3 OOS, DM t=6.63)
  K488: But VT strategy using it doesn't beat 12/VIX (risk premium is the feature)
  Question: How do the three sigma signals differ in RECENT PRACTICE?

This is NOT a forecasting experiment — it's a practical signal comparison:
  1. VIX-implied sigma: VIX/100*sqrt(252) annualized → daily sigma_vix
  2. GJR-GARCH sigma: standard rolling GJR
  3. GJR-X(VIX9D) sigma: exogenous VIX9D in variance equation

Analysis:
  - 3 sigma time series (2024-2026)
  - Correlations & divergence patterns
  - Mincer-Zarnowitz regressions (which tracks realized vol best?)
  - Market event analysis: 2024 Aug sell-off, 2025 tariff shock
  - VT weight divergence: when does GJR-X(VIX9D) disagree with 12/VIX?
  - VaR violation analysis (last 6 months)
  - Delta coefficient stability

Data: yfinance SPY + ^VIX + ^VIX9D, 2023-01 to 2026-03
  (2023 is burn-in for GARCH estimation window=500, analysis on 2024-2026)
Efficiency: Single GARCH fit + rolling 1-step forecasts, target < 30s

Refs:
  Patton (2011) Volatility Forecast Comparison Using Imperfect Proxies, JoE
  Mincer & Zarnowitz (1969) The Evaluation of Economic Forecasts
  Kupiec (1995) Techniques for Verifying the Accuracy of Risk Measurement Models
  K490: GJR-X(VIX9D) 3/3 OOS QLIKE winner
  K488: VT strategy comparison

Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats, optimize
from scipy.special import gammaln
from arch import arch_model
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox

warnings.filterwarnings('ignore')

print("=" * 70)
print("K493: GJR-X(VIX9D) Real-Time Signal Analysis")
print("  Practical signal comparison: VIX-implied vs GJR vs GJR-X(VIX9D)")
print("  What would an investor SEE if they started using GJR-X(VIX9D) today?")
print("=" * 70)

t_start = time.time()

# ============================================================
# Configuration
# ============================================================
IS_WINDOW = 500  # rolling estimation window (same as K490)
REFIT_INTERVAL = 21  # refit monthly
ANALYSIS_START = "2024-01-01"  # Analysis period starts here
DATA_START = "2022-01-01"  # Extra history for GARCH burn-in

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")
spy_raw = yf.download('SPY', start=DATA_START, progress=False)
vix_raw = yf.download('^VIX', start=DATA_START, progress=False)
vix9d_raw = yf.download('^VIX9D', start=DATA_START, progress=False)

for df_name, df in [('SPY', spy_raw), ('VIX', vix_raw), ('VIX9D', vix9d_raw)]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df_name == 'SPY':
        spy_raw = df
    elif df_name == 'VIX':
        vix_raw = df
    else:
        vix9d_raw = df

print(f"  SPY:   {spy_raw.index[0].date()} to {spy_raw.index[-1].date()} ({len(spy_raw)} obs)")
print(f"  VIX:   {vix_raw.index[0].date()} to {vix_raw.index[-1].date()} ({len(vix_raw)} obs)")
print(f"  VIX9D: {vix9d_raw.index[0].date()} to {vix9d_raw.index[-1].date()} ({len(vix9d_raw)} obs)")

# ============================================================
# 2. FEATURE COMPUTATION
# ============================================================
print("\n[2] Computing features...")

spy_close = spy_raw['Close'].values.astype(float).ravel()
vix_close = vix_raw['Close'].values.astype(float).ravel()
vix9d_close = vix9d_raw['Close'].values.astype(float).ravel()

# Log returns in %
spy_ret_pct = np.log(spy_close[1:] / spy_close[:-1]) * 100
spy_idx = spy_raw.index[1:]

df_spy = pd.DataFrame({
    'return_pct': spy_ret_pct,
    'r2_proxy': (np.log(spy_close[1:] / spy_close[:-1]))**2,  # decimal squared
}, index=spy_idx)

df_vix = pd.DataFrame({'VIX': vix_close}, index=vix_raw.index)
df_vix9d = pd.DataFrame({'VIX9D': vix9d_close}, index=vix9d_raw.index)

# Merge on date
feat = df_spy.join(df_vix, how='inner').join(df_vix9d, how='inner')
feat = feat.dropna()

# VIX/VIX9D implied daily variance in %² units
feat['vix_daily_var'] = feat['VIX']**2 / 252
feat['vix9d_daily_var'] = feat['VIX9D']**2 / 252

# Realized vol proxy: 5-day rolling variance of returns (in %²)
feat['rv5_pct2'] = feat['return_pct'].rolling(5).var()
# Also compute 1-day squared return as proxy
feat['rv1_pct2'] = feat['return_pct']**2

print(f"  Combined: {len(feat)} obs ({feat.index[0].date()} to {feat.index[-1].date()})")
print(f"  VIX:   mean={feat['VIX'].mean():.1f}, std={feat['VIX'].std():.1f}")
print(f"  VIX9D: mean={feat['VIX9D'].mean():.1f}, std={feat['VIX9D'].std():.1f}")

# ============================================================
# 3. DIAGNOSTICS (CLAUDE.md rule 5)
# ============================================================
print("\n[3] Data diagnostics (analysis period)...")
analysis_mask = feat.index >= ANALYSIS_START
feat_analysis = feat[analysis_mask]
ret_a = feat_analysis['return_pct'].values

adf_stat, adf_p, _, _, _, _ = adfuller(ret_a, maxlag=21)
arch_stat_val, arch_p, _, _ = het_arch(ret_a, nlags=10)
lb = acorr_ljungbox(ret_a**2, lags=[10], return_df=True)

diagnostics = {
    'analysis_period': f"{feat_analysis.index[0].date()} to {feat_analysis.index[-1].date()}",
    'n_analysis': len(feat_analysis),
    'total_obs': len(feat),
    'return_mean_pct': float(np.mean(ret_a)),
    'return_std_pct': float(np.std(ret_a)),
    'return_skew': float(stats.skew(ret_a)),
    'return_kurt': float(stats.kurtosis(ret_a)),
    'vix_mean': float(feat_analysis['VIX'].mean()),
    'vix_std': float(feat_analysis['VIX'].std()),
    'vix9d_mean': float(feat_analysis['VIX9D'].mean()),
    'vix9d_std': float(feat_analysis['VIX9D'].std()),
    'corr_vix_vix9d': float(feat_analysis['VIX'].corr(feat_analysis['VIX9D'])),
    'adf_stat': float(adf_stat),
    'adf_p': float(adf_p),
    'is_stationary': bool(adf_p < 0.05),
    'arch_lm_stat': float(arch_stat_val),
    'arch_lm_p': float(arch_p),
    'has_arch_effects': bool(arch_p < 0.05),
    'ljung_box_sq_p10': float(lb['lb_pvalue'].values[0]),
}

print(f"  Analysis: {diagnostics['n_analysis']} obs, {diagnostics['analysis_period']}")
print(f"  ADF p={adf_p:.2e} ({'stationary' if adf_p < 0.05 else 'NON-STATIONARY'})")
print(f"  ARCH-LM p={arch_p:.2e} ({'YES' if arch_p < 0.05 else 'NO'})")
print(f"  Return: mean={np.mean(ret_a):.4f}%, std={np.std(ret_a):.4f}%, skew={stats.skew(ret_a):.3f}, kurt={stats.kurtosis(ret_a):.3f}")

# ============================================================
# 4. MODEL FUNCTIONS
# ============================================================

def gjr_garchx_loglik(params, returns, exog_lag, n_exog):
    """Custom log-likelihood for GJR-GARCH-X with Student-t."""
    mu = params[0]
    omega = params[1]
    alpha = params[2]
    gamma = params[3]
    beta = params[4]
    deltas = params[5:5+n_exog]
    nu = params[5+n_exog]

    T = len(returns)
    eps = returns - mu
    h = np.zeros(T)
    h[0] = np.var(eps)
    if h[0] <= 0:
        h[0] = 1.0

    for t in range(1, T):
        shock2 = eps[t-1]**2
        asym = shock2 if eps[t-1] < 0 else 0.0
        exog_contrib = 0.0
        for i in range(n_exog):
            exog_contrib += deltas[i] * exog_lag[t, i]
        h[t] = omega + alpha * shock2 + gamma * asym + beta * h[t-1] + exog_contrib
        if h[t] <= 0:
            h[t] = 1e-6

    ll = (
        gammaln((nu + 1) / 2) - gammaln(nu / 2)
        - 0.5 * np.log(np.pi * (nu - 2))
        - 0.5 * np.log(h)
        - (nu + 1) / 2 * np.log(1 + eps**2 / (h * (nu - 2)))
    )
    return -np.sum(ll)


def fit_gjr_garchx(returns_pct, exog_vars, exog_names=None):
    """Fit GJR-GARCH-X with custom MLE. Returns dict with params + h_series."""
    n_exog = len(exog_vars)
    T = len(returns_pct)
    ret = returns_pct.copy()

    exog_lag = np.zeros((T, n_exog))
    for i, xv in enumerate(exog_vars):
        exog_lag[1:, i] = xv[:-1]
        exog_lag[0, i] = xv[0]

    mu0 = np.mean(ret)
    x0 = [mu0, 0.01, 0.05, 0.05, 0.90] + [0.01]*n_exog + [6.0]

    bounds = [
        (-1.0, 1.0),      # mu
        (1e-6, 10.0),     # omega
        (1e-6, 0.5),      # alpha
        (0.0, 0.5),       # gamma
        (0.3, 0.999),     # beta
    ]
    for _ in range(n_exog):
        bounds.append((0.0, 1.0))  # delta
    bounds.append((2.1, 50.0))     # nu

    try:
        result = optimize.minimize(
            gjr_garchx_loglik, x0, args=(ret, exog_lag, n_exog),
            method='L-BFGS-B', bounds=bounds,
            options={'maxiter': 500, 'ftol': 1e-10}
        )

        if not result.success and result.fun > 1e10:
            return None

        mu = result.x[0]
        omega = result.x[1]
        alpha_val = result.x[2]
        gamma_val = result.x[3]
        beta_val = result.x[4]
        deltas = result.x[5:5+n_exog]
        nu = result.x[5+n_exog]

        eps = ret - mu
        h = np.zeros(T)
        h[0] = np.var(eps)
        if h[0] <= 0:
            h[0] = 1.0
        for t in range(1, T):
            shock2 = eps[t-1]**2
            asym = shock2 if eps[t-1] < 0 else 0.0
            exog_c = sum(deltas[i] * exog_lag[t, i] for i in range(n_exog))
            h[t] = omega + alpha_val * shock2 + gamma_val * asym + beta_val * h[t-1] + exog_c
            if h[t] <= 0:
                h[t] = 1e-6

        # 1-step ahead forecast
        shock2_last = eps[-1]**2
        asym_last = shock2_last if eps[-1] < 0 else 0.0
        exog_last = sum(deltas[i] * exog_vars[i][-1] for i in range(n_exog))
        h_forecast = omega + alpha_val * shock2_last + gamma_val * asym_last + beta_val * h[-1] + exog_last
        if h_forecast <= 0:
            h_forecast = 1e-6

        persistence = alpha_val + gamma_val / 2 + beta_val

        param_dict = {
            'mu': float(mu), 'omega': float(omega),
            'alpha': float(alpha_val), 'gamma': float(gamma_val),
            'beta': float(beta_val), 'nu': float(nu),
            'persistence': float(persistence),
        }
        for i in range(n_exog):
            name = exog_names[i] if exog_names else f'delta_{i}'
            param_dict[f'delta_{name}'] = float(deltas[i])

        return {
            'params': param_dict, 'h_series': h, 'h_forecast': float(h_forecast),
            'loglik': float(-result.fun), 'converged': result.success,
        }
    except Exception:
        return None

# ============================================================
# 5. ROLLING SIGMA SIGNALS
# ============================================================
print("\n[4] Computing rolling sigma signals...")

returns_all = feat['return_pct'].values
dates_all = feat.index
vix_var_all = feat['vix_daily_var'].values
vix9d_var_all = feat['vix9d_daily_var'].values
vix_all = feat['VIX'].values
vix9d_all = feat['VIX9D'].values

# Find analysis start index
analysis_start_idx = np.searchsorted(dates_all, pd.Timestamp(ANALYSIS_START))
# Make sure we have enough burn-in
if analysis_start_idx < IS_WINDOW:
    print(f"  WARNING: analysis start idx {analysis_start_idx} < window {IS_WINDOW}")
    analysis_start_idx = IS_WINDOW

n_analysis = len(dates_all) - analysis_start_idx
print(f"  Analysis window: idx {analysis_start_idx} to {len(dates_all)-1} ({n_analysis} days)")

# Storage for rolling forecasts
sigma_vix = np.zeros(n_analysis)      # VIX-implied daily sigma
sigma_gjr = np.zeros(n_analysis)      # GJR sigma
sigma_gjrx = np.zeros(n_analysis)     # GJR-X(VIX9D) sigma
actual_r2 = np.zeros(n_analysis)      # Actual r² (squared return)
actual_rv5 = np.zeros(n_analysis)     # 5-day realized variance
dates_analysis = dates_all[analysis_start_idx:]
delta_vix9d_history = []  # Track delta coefficient over time

n_refits = 0
last_gjr_res = None
last_gjrx_res = None

for i in range(n_analysis):
    t = analysis_start_idx + i

    # VIX-implied sigma: VIX/sqrt(252) → daily std in %
    # VIX is annualized % → daily std = VIX/sqrt(252) in %
    # So daily variance in %² = VIX²/252
    sigma_vix[i] = vix_var_all[t-1]  # Use previous day's VIX (available at close)

    # Actual r²
    actual_r2[i] = returns_all[t]**2
    if t >= 4:
        actual_rv5[i] = np.var(returns_all[t-4:t+1])
    else:
        actual_rv5[i] = actual_r2[i]

    # Refit GARCH models periodically
    need_refit = (i % REFIT_INTERVAL == 0) or (last_gjr_res is None)

    if need_refit:
        window_start = t - IS_WINDOW
        if window_start < 0:
            window_start = 0

        ret_window = returns_all[window_start:t]
        vix9d_var_window = vix9d_var_all[window_start:t]

        # GJR-GARCH (arch package)
        try:
            am = arch_model(ret_window, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
            gjr_res = am.fit(disp='off', show_warning=False)
            last_gjr_res = gjr_res
        except Exception:
            pass

        # GJR-X(VIX9D) (custom MLE)
        gjrx_res = fit_gjr_garchx(ret_window, [vix9d_var_window], exog_names=['VIX9D'])
        if gjrx_res is not None:
            last_gjrx_res = gjrx_res
            delta_vix9d_history.append({
                'date': str(dates_all[t].date()),
                'delta_VIX9D': gjrx_res['params'].get('delta_VIX9D', 0),
                'persistence': gjrx_res['params']['persistence'],
                'omega': gjrx_res['params']['omega'],
                'alpha': gjrx_res['params']['alpha'],
                'gamma': gjrx_res['params']['gamma'],
                'beta': gjrx_res['params']['beta'],
            })

        n_refits += 1

    # GJR forecast: use last fitted model's 1-step forecast logic
    if last_gjr_res is not None:
        try:
            fcast = last_gjr_res.forecast(horizon=1, reindex=False)
            sigma_gjr[i] = fcast.variance.values[-1, 0]
        except Exception:
            # Fallback: use conditional variance last value
            sigma_gjr[i] = last_gjr_res.conditional_volatility[-1]**2

    # GJR-X(VIX9D) forecast
    if last_gjrx_res is not None:
        p = last_gjrx_res['params']
        h_last = last_gjrx_res['h_series'][-1]

        # Update h with new observation
        eps_t = returns_all[t-1] - p['mu']
        shock2 = eps_t**2
        asym = shock2 if eps_t < 0 else 0.0
        delta_v = p.get('delta_VIX9D', 0)

        h_new = p['omega'] + p['alpha'] * shock2 + p['gamma'] * asym + p['beta'] * h_last + delta_v * vix9d_var_all[t-1]
        if h_new <= 0:
            h_new = 1e-6
        sigma_gjrx[i] = h_new

        # Update h_series for next step (rolling forward between refits)
        last_gjrx_res['h_series'] = np.append(last_gjrx_res['h_series'], h_new)

    if (i+1) % 100 == 0:
        print(f"  ... processed {i+1}/{n_analysis} days ({n_refits} refits)")

print(f"  Done: {n_analysis} days, {n_refits} refits")

# ============================================================
# 6. SIGNAL COMPARISON
# ============================================================
print("\n[5] Signal comparison analysis...")

# Convert to DataFrame for easier analysis
signals = pd.DataFrame({
    'date': dates_analysis,
    'sigma_vix': sigma_vix,         # VIX²/252 in %²
    'sigma_gjr': sigma_gjr,         # GARCH h_t in %²
    'sigma_gjrx': sigma_gjrx,       # GARCH-X h_t in %²
    'actual_r2': actual_r2,         # r² in %²
    'actual_rv5': actual_rv5,       # 5d RV in %²
    'vix_level': vix_all[analysis_start_idx:],
    'vix9d_level': vix9d_all[analysis_start_idx:],
}, index=dates_analysis)

# Drop any rows with zero sigma (failed fits)
valid = (signals['sigma_gjr'] > 0) & (signals['sigma_gjrx'] > 0) & (signals['sigma_vix'] > 0)
signals = signals[valid]
print(f"  Valid signal days: {len(signals)}")

# --- 6a. Correlations ---
print("\n  [5a] Sigma correlations:")
corr_matrix = signals[['sigma_vix', 'sigma_gjr', 'sigma_gjrx']].corr()
print(f"    VIX vs GJR:       {corr_matrix.loc['sigma_vix', 'sigma_gjr']:.4f}")
print(f"    VIX vs GJR-X:     {corr_matrix.loc['sigma_vix', 'sigma_gjrx']:.4f}")
print(f"    GJR vs GJR-X:     {corr_matrix.loc['sigma_gjr', 'sigma_gjrx']:.4f}")

# Rank correlations (Spearman)
spearman_vix_gjr = stats.spearmanr(signals['sigma_vix'], signals['sigma_gjr'])[0]
spearman_vix_gjrx = stats.spearmanr(signals['sigma_vix'], signals['sigma_gjrx'])[0]
spearman_gjr_gjrx = stats.spearmanr(signals['sigma_gjr'], signals['sigma_gjrx'])[0]
print(f"    (Spearman) VIX vs GJR:   {spearman_vix_gjr:.4f}")
print(f"    (Spearman) VIX vs GJR-X: {spearman_vix_gjrx:.4f}")
print(f"    (Spearman) GJR vs GJR-X: {spearman_gjr_gjrx:.4f}")

# --- 6b. Mincer-Zarnowitz regressions ---
print("\n  [5b] Mincer-Zarnowitz regressions (actual_r² = a + b·sigma + e):")
mz_results = {}
for name, col in [('VIX-implied', 'sigma_vix'), ('GJR', 'sigma_gjr'), ('GJR-X(VIX9D)', 'sigma_gjrx')]:
    X = signals[col].values
    y = signals['actual_r2'].values

    # OLS: y = a + b*X
    X_mat = np.column_stack([np.ones(len(X)), X])
    beta_hat = np.linalg.lstsq(X_mat, y, rcond=None)[0]
    y_hat = X_mat @ beta_hat
    ss_res = np.sum((y - y_hat)**2)
    ss_tot = np.sum((y - np.mean(y))**2)
    r2 = 1 - ss_res / ss_tot

    # Also test H0: a=0, b=1 (unbiasedness)
    resid = y - y_hat
    se = np.sqrt(np.diag(ss_res / (len(y) - 2) * np.linalg.inv(X_mat.T @ X_mat)))
    t_a = beta_hat[0] / se[0]
    t_b = (beta_hat[1] - 1) / se[1]

    mz_results[name] = {
        'intercept': float(beta_hat[0]),
        'slope': float(beta_hat[1]),
        'R2': float(r2),
        'se_intercept': float(se[0]),
        'se_slope': float(se[1]),
        't_intercept_zero': float(t_a),
        't_slope_one': float(t_b),
        'p_intercept_zero': float(2 * stats.t.sf(abs(t_a), len(y)-2)),
        'p_slope_one': float(2 * stats.t.sf(abs(t_b), len(y)-2)),
    }
    print(f"    {name}: a={beta_hat[0]:.4f}, b={beta_hat[1]:.4f}, R²={r2:.4f}")
    print(f"      H0(a=0): t={t_a:.3f}, H0(b=1): t={t_b:.3f}")

# Also with 5-day RV as target
print("\n  [5b'] M-Z with 5-day RV as target:")
mz_rv5_results = {}
valid_rv5 = signals['actual_rv5'].values > 0
for name, col in [('VIX-implied', 'sigma_vix'), ('GJR', 'sigma_gjr'), ('GJR-X(VIX9D)', 'sigma_gjrx')]:
    X = signals[col].values[valid_rv5]
    y = signals['actual_rv5'].values[valid_rv5]
    X_mat = np.column_stack([np.ones(len(X)), X])
    beta_hat = np.linalg.lstsq(X_mat, y, rcond=None)[0]
    y_hat = X_mat @ beta_hat
    ss_res = np.sum((y - y_hat)**2)
    ss_tot = np.sum((y - np.mean(y))**2)
    r2 = 1 - ss_res / ss_tot
    mz_rv5_results[name] = {'intercept': float(beta_hat[0]), 'slope': float(beta_hat[1]), 'R2': float(r2)}
    print(f"    {name}: a={beta_hat[0]:.4f}, b={beta_hat[1]:.4f}, R²={r2:.4f}")

# --- 6c. QLIKE comparison ---
print("\n  [5c] QLIKE comparison:")
qlike_results = {}
for name, col in [('VIX-implied', 'sigma_vix'), ('GJR', 'sigma_gjr'), ('GJR-X(VIX9D)', 'sigma_gjrx')]:
    h = signals[col].values
    rv = signals['actual_r2'].values
    # QLIKE = mean(rv/h + log(h)), lower is better
    mask = (h > 0) & (rv > 0)
    qlike = np.mean(rv[mask] / h[mask] + np.log(h[mask]))
    qlike_results[name] = float(qlike)
    print(f"    {name}: QLIKE = {qlike:.6f}")

# DM test: GJR-X(VIX9D) vs others
print("\n  [5c'] Diebold-Mariano tests (QLIKE loss differential):")
dm_results = {}
for name, col in [('VIX-implied', 'sigma_vix'), ('GJR', 'sigma_gjr')]:
    h1 = signals[col].values
    h2 = signals['sigma_gjrx'].values
    rv = signals['actual_r2'].values
    mask = (h1 > 0) & (h2 > 0) & (rv > 0)

    loss1 = rv[mask] / h1[mask] + np.log(h1[mask])
    loss2 = rv[mask] / h2[mask] + np.log(h2[mask])
    d = loss1 - loss2  # Positive → GJR-X is better

    n = len(d)
    d_bar = np.mean(d)
    # HAC variance (Newey-West with bandwidth ~ n^(1/3))
    bw = int(np.floor(n**(1/3)))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, bw+1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * (1 - k/(bw+1)) * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma_0 / n

    dm_stat = d_bar / np.sqrt(var_d)
    dm_p = 2 * stats.norm.sf(abs(dm_stat))

    dm_results[f'GJR-X vs {name}'] = {
        'dm_stat': float(dm_stat),
        'p_value': float(dm_p),
        'mean_loss_diff': float(d_bar),
        'gjrx_better': bool(d_bar > 0),
    }
    direction = "GJR-X(VIX9D) better" if d_bar > 0 else f"{name} better"
    sig = "***" if abs(dm_stat) > 2.576 else "**" if abs(dm_stat) > 1.96 else "*" if abs(dm_stat) > 1.645 else ""
    print(f"    GJR-X(VIX9D) vs {name}: DM={dm_stat:.3f} (p={dm_p:.4f}) {sig} [{direction}]")

# ============================================================
# 7. MARKET EVENT ANALYSIS
# ============================================================
print("\n[6] Market event analysis...")

events = [
    {"name": "2024 Aug Sell-off (Japan carry trade)", "start": "2024-07-15", "end": "2024-08-15"},
    {"name": "2024 Nov Election", "start": "2024-10-28", "end": "2024-11-15"},
    {"name": "2025 Q1 Tariff Shock", "start": "2025-02-15", "end": "2025-03-25"},
]

event_results = []
for ev in events:
    mask = (signals.index >= ev['start']) & (signals.index <= ev['end'])
    if mask.sum() == 0:
        print(f"  {ev['name']}: No data in range")
        continue

    ev_data = signals[mask]

    # Mean sigma levels
    mean_vix = ev_data['sigma_vix'].mean()
    mean_gjr = ev_data['sigma_gjr'].mean()
    mean_gjrx = ev_data['sigma_gjrx'].mean()
    mean_actual = ev_data['actual_r2'].mean()

    # Max sigma levels
    max_vix = ev_data['sigma_vix'].max()
    max_gjr = ev_data['sigma_gjr'].max()
    max_gjrx = ev_data['sigma_gjrx'].max()

    # Divergence: GJR-X vs VIX
    divergence = (ev_data['sigma_gjrx'] - ev_data['sigma_vix']).mean()

    # VT weight difference: w = sigma_target / sigma
    # Using sigma_target = 12%/sqrt(252) daily = (12/sqrt(252))² %² for daily var
    sigma_target_daily = (12 / np.sqrt(252))**2 * 10000  # in %² units...
    # Actually, VT weight = sigma_target / sigma_realized
    # sigma as annual: sqrt(h * 252) in %, target=12%
    # w_vix = 12 / (sqrt(sigma_vix * 252))
    # But sigma_vix = VIX²/252, so sqrt(sigma_vix*252) = VIX → w_vix = 12/VIX

    w_vix_mean = np.mean(12.0 / ev_data['vix_level'].values)
    w_gjr_mean = np.mean(12.0 / np.sqrt(ev_data['sigma_gjr'].values * 252))
    w_gjrx_mean = np.mean(12.0 / np.sqrt(ev_data['sigma_gjrx'].values * 252))

    ev_result = {
        'name': ev['name'],
        'n_days': int(mask.sum()),
        'period': f"{ev['start']} to {ev['end']}",
        'mean_sigma_vix': float(mean_vix),
        'mean_sigma_gjr': float(mean_gjr),
        'mean_sigma_gjrx': float(mean_gjrx),
        'mean_actual_r2': float(mean_actual),
        'max_sigma_vix': float(max_vix),
        'max_sigma_gjr': float(max_gjr),
        'max_sigma_gjrx': float(max_gjrx),
        'divergence_gjrx_minus_vix': float(divergence),
        'vt_weight_vix_12pct': float(w_vix_mean),
        'vt_weight_gjr_12pct': float(w_gjr_mean),
        'vt_weight_gjrx_12pct': float(w_gjrx_mean),
    }
    event_results.append(ev_result)

    print(f"\n  {ev['name']} ({ev_result['n_days']} days):")
    print(f"    Mean σ²(daily,%²): VIX={mean_vix:.3f}, GJR={mean_gjr:.3f}, GJR-X={mean_gjrx:.3f}, Actual={mean_actual:.3f}")
    print(f"    Max  σ²(daily,%²): VIX={max_vix:.3f}, GJR={max_gjr:.3f}, GJR-X={max_gjrx:.3f}")
    print(f"    VT weight (σ*=12%): 12/VIX={w_vix_mean:.3f}, GJR={w_gjr_mean:.3f}, GJR-X={w_gjrx_mean:.3f}")
    print(f"    GJR-X − VIX divergence: {divergence:+.4f} %²/day")

# ============================================================
# 8. VT WEIGHT DIVERGENCE ANALYSIS
# ============================================================
print("\n[7] VT weight divergence analysis...")

# Annual sigma from daily variance
signals['annual_sigma_vix'] = np.sqrt(signals['sigma_vix'] * 252)
signals['annual_sigma_gjr'] = np.sqrt(signals['sigma_gjr'] * 252)
signals['annual_sigma_gjrx'] = np.sqrt(signals['sigma_gjrx'] * 252)

# VT weights (target sigma = 12%)
signals['w_vix'] = 12.0 / signals['annual_sigma_vix']
signals['w_gjr'] = 12.0 / signals['annual_sigma_gjr']
signals['w_gjrx'] = 12.0 / signals['annual_sigma_gjrx']

# Cap at 1.5 (150% leverage max)
for c in ['w_vix', 'w_gjr', 'w_gjrx']:
    signals[c] = signals[c].clip(upper=1.5)

# Divergence
signals['w_diff_gjrx_vix'] = signals['w_gjrx'] - signals['w_vix']
signals['w_diff_gjrx_gjr'] = signals['w_gjrx'] - signals['w_gjr']

# Summary stats
w_stats = {
    'mean_w_vix': float(signals['w_vix'].mean()),
    'mean_w_gjr': float(signals['w_gjr'].mean()),
    'mean_w_gjrx': float(signals['w_gjrx'].mean()),
    'std_w_vix': float(signals['w_vix'].std()),
    'std_w_gjr': float(signals['w_gjr'].std()),
    'std_w_gjrx': float(signals['w_gjrx'].std()),
    'corr_w_gjrx_vix': float(signals['w_gjrx'].corr(signals['w_vix'])),
    'corr_w_gjrx_gjr': float(signals['w_gjrx'].corr(signals['w_gjr'])),
    'mean_diff_gjrx_vix': float(signals['w_diff_gjrx_vix'].mean()),
    'std_diff_gjrx_vix': float(signals['w_diff_gjrx_vix'].std()),
    'max_diff_gjrx_vix': float(signals['w_diff_gjrx_vix'].max()),
    'min_diff_gjrx_vix': float(signals['w_diff_gjrx_vix'].min()),
    'pct_gjrx_higher_than_vix': float((signals['w_diff_gjrx_vix'] > 0.01).mean() * 100),
    'pct_gjrx_lower_than_vix': float((signals['w_diff_gjrx_vix'] < -0.01).mean() * 100),
    'pct_similar': float((abs(signals['w_diff_gjrx_vix']) <= 0.01).mean() * 100),
}

print(f"  Mean VT weights: 12/VIX={w_stats['mean_w_vix']:.4f}, GJR={w_stats['mean_w_gjr']:.4f}, GJR-X={w_stats['mean_w_gjrx']:.4f}")
print(f"  Std  VT weights: 12/VIX={w_stats['std_w_vix']:.4f}, GJR={w_stats['std_w_gjr']:.4f}, GJR-X={w_stats['std_w_gjrx']:.4f}")
print(f"  Corr(w_GJR-X, w_VIX): {w_stats['corr_w_gjrx_vix']:.4f}")
print(f"  GJR-X vs 12/VIX divergence:")
print(f"    Mean diff: {w_stats['mean_diff_gjrx_vix']:+.4f}")
print(f"    Std  diff: {w_stats['std_diff_gjrx_vix']:.4f}")
print(f"    Range: [{w_stats['min_diff_gjrx_vix']:+.4f}, {w_stats['max_diff_gjrx_vix']:+.4f}]")
print(f"    GJR-X higher >1%: {w_stats['pct_gjrx_higher_than_vix']:.1f}% of days")
print(f"    GJR-X lower  >1%: {w_stats['pct_gjrx_lower_than_vix']:.1f}% of days")
print(f"    Similar (±1%):     {w_stats['pct_similar']:.1f}% of days")

# Top 10 divergence days
print("\n  Top 10 days where GJR-X(VIX9D) weight differs most from 12/VIX:")
top_div = signals.nlargest(10, 'w_diff_gjrx_vix')[['w_vix', 'w_gjrx', 'w_diff_gjrx_vix', 'vix_level', 'vix9d_level']]
top_div_list = []
for date, row in top_div.iterrows():
    print(f"    {date.date()}: w_VIX={row['w_vix']:.3f}, w_GJR-X={row['w_gjrx']:.3f}, diff={row['w_diff_gjrx_vix']:+.3f} (VIX={row['vix_level']:.1f}, VIX9D={row['vix9d_level']:.1f})")
    top_div_list.append({
        'date': str(date.date()),
        'w_vix': float(row['w_vix']),
        'w_gjrx': float(row['w_gjrx']),
        'diff': float(row['w_diff_gjrx_vix']),
        'vix': float(row['vix_level']),
        'vix9d': float(row['vix9d_level']),
    })

print("\n  Top 10 days where GJR-X(VIX9D) weight is LOWER than 12/VIX:")
bot_div = signals.nsmallest(10, 'w_diff_gjrx_vix')[['w_vix', 'w_gjrx', 'w_diff_gjrx_vix', 'vix_level', 'vix9d_level']]
bot_div_list = []
for date, row in bot_div.iterrows():
    print(f"    {date.date()}: w_VIX={row['w_vix']:.3f}, w_GJR-X={row['w_gjrx']:.3f}, diff={row['w_diff_gjrx_vix']:+.3f} (VIX={row['vix_level']:.1f}, VIX9D={row['vix9d_level']:.1f})")
    bot_div_list.append({
        'date': str(date.date()),
        'w_vix': float(row['w_vix']),
        'w_gjrx': float(row['w_gjrx']),
        'diff': float(row['w_diff_gjrx_vix']),
        'vix': float(row['vix_level']),
        'vix9d': float(row['vix9d_level']),
    })

# ============================================================
# 9. VaR VIOLATION ANALYSIS (last 6 months)
# ============================================================
print("\n[8] VaR violation analysis (last 6 months)...")

# Last ~126 trading days
last_6m = signals.tail(126)
n_var = len(last_6m)

var_results = {}
for name, sigma_col in [('VIX-implied', 'sigma_vix'), ('GJR', 'sigma_gjr'), ('GJR-X(VIX9D)', 'sigma_gjrx')]:
    for alpha in [0.01, 0.05]:
        h = last_6m[sigma_col].values
        ret = np.zeros(n_var)
        # Get actual returns for these dates
        for k, date in enumerate(last_6m.index):
            idx_in_feat = np.where(dates_all == date)[0]
            if len(idx_in_feat) > 0:
                ret[k] = returns_all[idx_in_feat[0]]

        # VaR = mu + z_alpha * sqrt(h), use Student-t quantile with nu~6
        nu_est = 6.0  # approximate from typical GJR fit
        z_alpha = stats.t.ppf(alpha, nu_est)
        var_threshold = z_alpha * np.sqrt(h)  # negative number

        violations = ret < var_threshold
        n_viol = int(violations.sum())
        viol_rate = n_viol / n_var
        expected = alpha * n_var

        # Kupiec test
        if n_viol > 0 and n_viol < n_var:
            lr = -2 * (n_var * np.log(1 - alpha) + 0 -
                      ((n_var - n_viol) * np.log(1 - n_viol/n_var) + n_viol * np.log(n_viol/n_var)))
            # Simplified: use correct Kupiec formula
            p0 = alpha
            p1 = n_viol / n_var
            if p1 > 0 and p1 < 1:
                lr = -2 * ((n_var - n_viol) * np.log((1 - p0) / (1 - p1)) + n_viol * np.log(p0 / p1))
            else:
                lr = 0
            kupiec_p = 1 - stats.chi2.cdf(abs(lr), 1)
        else:
            lr = 0
            kupiec_p = 1.0

        key = f"{name}_{int(alpha*100)}pct"
        var_results[key] = {
            'model': name,
            'alpha': alpha,
            'n_obs': n_var,
            'n_violations': n_viol,
            'violation_rate': float(viol_rate),
            'expected_violations': float(expected),
            'kupiec_stat': float(lr),
            'kupiec_p': float(kupiec_p),
            'kupiec_pass': bool(kupiec_p > 0.05),
        }

        status = "PASS" if kupiec_p > 0.05 else "FAIL"
        print(f"  {name} VaR({int(alpha*100)}%): {n_viol}/{n_var} = {viol_rate:.3f} (expected {alpha:.2f}) [{status}]")

# ============================================================
# 10. DELTA COEFFICIENT STABILITY
# ============================================================
print("\n[9] Delta(VIX9D) coefficient stability...")

if delta_vix9d_history:
    deltas_df = pd.DataFrame(delta_vix9d_history)
    delta_stability = {
        'n_refits': len(deltas_df),
        'delta_mean': float(deltas_df['delta_VIX9D'].mean()),
        'delta_std': float(deltas_df['delta_VIX9D'].std()),
        'delta_min': float(deltas_df['delta_VIX9D'].min()),
        'delta_max': float(deltas_df['delta_VIX9D'].max()),
        'delta_cv': float(deltas_df['delta_VIX9D'].std() / deltas_df['delta_VIX9D'].mean()) if deltas_df['delta_VIX9D'].mean() > 0 else float('inf'),
        'persistence_mean': float(deltas_df['persistence'].mean()),
        'persistence_std': float(deltas_df['persistence'].std()),
        'first_5': deltas_df.head(5)[['date', 'delta_VIX9D', 'persistence']].to_dict('records'),
        'last_5': deltas_df.tail(5)[['date', 'delta_VIX9D', 'persistence']].to_dict('records'),
    }

    print(f"  N refits: {delta_stability['n_refits']}")
    print(f"  Delta(VIX9D): mean={delta_stability['delta_mean']:.4f}, std={delta_stability['delta_std']:.4f}")
    print(f"    Range: [{delta_stability['delta_min']:.4f}, {delta_stability['delta_max']:.4f}]")
    print(f"    CV: {delta_stability['delta_cv']:.3f}")
    print(f"  Persistence: mean={delta_stability['persistence_mean']:.4f}, std={delta_stability['persistence_std']:.4f}")

    print("\n  Delta trajectory (first 5 → last 5):")
    for r in delta_stability['first_5']:
        print(f"    {r['date']}: δ={r['delta_VIX9D']:.4f}, pers={r['persistence']:.4f}")
    print("    ...")
    for r in delta_stability['last_5']:
        print(f"    {r['date']}: δ={r['delta_VIX9D']:.4f}, pers={r['persistence']:.4f}")
else:
    delta_stability = {'n_refits': 0, 'error': 'No successful GJR-X fits'}
    print("  WARNING: No successful GJR-X fits!")

# ============================================================
# 11. CURRENT (LATEST) SIGNALS
# ============================================================
print("\n[10] Current signal snapshot (latest 5 days):")
latest = signals.tail(5)
print(f"  {'Date':>12} {'VIX':>6} {'VIX9D':>6} {'σ²_VIX':>8} {'σ²_GJR':>8} {'σ²_GJR-X':>8} {'w_VIX':>6} {'w_GJR':>6} {'w_GJR-X':>7}")
current_snapshot = []
for date, row in latest.iterrows():
    print(f"  {str(date.date()):>12} {row['vix_level']:>6.1f} {row['vix9d_level']:>6.1f} {row['sigma_vix']:>8.3f} {row['sigma_gjr']:>8.3f} {row['sigma_gjrx']:>8.3f} {row['w_vix']:>6.3f} {row['w_gjr']:>6.3f} {row['w_gjrx']:>7.3f}")
    current_snapshot.append({
        'date': str(date.date()),
        'vix': float(row['vix_level']),
        'vix9d': float(row['vix9d_level']),
        'sigma_vix_pct2': float(row['sigma_vix']),
        'sigma_gjr_pct2': float(row['sigma_gjr']),
        'sigma_gjrx_pct2': float(row['sigma_gjrx']),
        'annual_sigma_vix_pct': float(row['annual_sigma_vix']),
        'annual_sigma_gjr_pct': float(row['annual_sigma_gjr']),
        'annual_sigma_gjrx_pct': float(row['annual_sigma_gjrx']),
        'w_vix': float(row['w_vix']),
        'w_gjr': float(row['w_gjr']),
        'w_gjrx': float(row['w_gjrx']),
    })

# ============================================================
# 12. SUMMARY & RESULTS
# ============================================================
elapsed = time.time() - t_start
print(f"\n{'='*70}")
print(f"COMPLETE in {elapsed:.1f}s")
print(f"{'='*70}")

# Build comprehensive results
results = {
    "experiment_id": "K493",
    "title": "GJR-X(VIX9D) Real-Time Signal Analysis",
    "hypothesis": "Compare practical sigma signals: VIX-implied vs GJR vs GJR-X(VIX9D) in 2024-2026",
    "builds_on": "K490 (GJR-X(VIX9D) best forecaster), K488 (VT doesn't beat 12/VIX)",
    "data_source": "yfinance: SPY, ^VIX, ^VIX9D",
    "data_period": f"{feat.index[0].date()} to {feat.index[-1].date()}",
    "analysis_period": f"{dates_analysis[0].date()} to {dates_analysis[-1].date()}",
    "n_total": len(feat),
    "n_analysis": len(signals),
    "is_window": IS_WINDOW,
    "refit_interval": REFIT_INTERVAL,
    "n_refits": n_refits,
    "execution_time_seconds": round(elapsed, 1),
    "methodology": {
        "signals": [
            "VIX-implied: sigma²_daily = VIX²/252 (in %²)",
            "GJR: standard GJR-GARCH(1,1) with Student-t (arch package)",
            "GJR-X(VIX9D): GJR-GARCH-X with VIX9D²/252 as exogenous (custom MLE)",
        ],
        "rolling": f"Window={IS_WINDOW}, refit every {REFIT_INTERVAL} days",
        "vt_weights": "w = 12% / annualized_sigma, capped at 1.5",
        "evaluation": "Pearson/Spearman correlation, Mincer-Zarnowitz R², QLIKE, DM test, VaR Kupiec",
    },
    "references": [
        "Patton (2011) Volatility Forecast Comparison Using Imperfect Proxies, JoE",
        "Mincer & Zarnowitz (1969) The Evaluation of Economic Forecasts",
        "Kupiec (1995) Techniques for Verifying the Accuracy of Risk Measurement Models",
        "K490: GJR-X(VIX9D) 3/3 OOS, DM t=6.63",
        "K488: VT(GJR-X) doesn't beat VT(12/VIX)",
    ],
    "diagnostics": diagnostics,
    "signal_correlations": {
        "pearson": {
            "vix_gjr": float(corr_matrix.loc['sigma_vix', 'sigma_gjr']),
            "vix_gjrx": float(corr_matrix.loc['sigma_vix', 'sigma_gjrx']),
            "gjr_gjrx": float(corr_matrix.loc['sigma_gjr', 'sigma_gjrx']),
        },
        "spearman": {
            "vix_gjr": float(spearman_vix_gjr),
            "vix_gjrx": float(spearman_vix_gjrx),
            "gjr_gjrx": float(spearman_gjr_gjrx),
        },
    },
    "mincer_zarnowitz_r2_target": mz_results,
    "mincer_zarnowitz_rv5_target": mz_rv5_results,
    "qlike": qlike_results,
    "dm_tests": dm_results,
    "market_events": event_results,
    "vt_weight_analysis": w_stats,
    "top_divergence_gjrx_higher": top_div_list,
    "top_divergence_gjrx_lower": bot_div_list,
    "var_violations_last_6m": var_results,
    "delta_stability": delta_stability,
    "current_snapshot": current_snapshot,
}

# Key findings summary
print("\n" + "=" * 70)
print("KEY FINDINGS")
print("=" * 70)

best_qlike = min(qlike_results, key=qlike_results.get)
print(f"\n1. FORECAST ACCURACY (QLIKE, lower is better):")
for name, val in qlike_results.items():
    marker = " ← BEST" if name == best_qlike else ""
    print(f"   {name}: {val:.6f}{marker}")

print(f"\n2. MINCER-ZARNOWITZ R² (r² proxy):")
for name, res in mz_results.items():
    print(f"   {name}: R²={res['R2']:.4f}, slope={res['slope']:.4f}")

print(f"\n3. SIGNAL CORRELATION:")
print(f"   VIX vs GJR-X(VIX9D): {corr_matrix.loc['sigma_vix', 'sigma_gjrx']:.4f}")
print(f"   GJR vs GJR-X(VIX9D): {corr_matrix.loc['sigma_gjr', 'sigma_gjrx']:.4f}")

print(f"\n4. VT WEIGHT DIVERGENCE (GJR-X vs 12/VIX):")
print(f"   Mean diff: {w_stats['mean_diff_gjrx_vix']:+.4f}")
print(f"   Days GJR-X higher >1%: {w_stats['pct_gjrx_higher_than_vix']:.1f}%")
print(f"   Days GJR-X lower  >1%: {w_stats['pct_gjrx_lower_than_vix']:.1f}%")
print(f"   Days similar (±1%):     {w_stats['pct_similar']:.1f}%")

print(f"\n5. DELTA(VIX9D) STABILITY:")
if isinstance(delta_stability.get('delta_mean'), float):
    print(f"   Mean: {delta_stability['delta_mean']:.4f}, CV: {delta_stability['delta_cv']:.3f}")
    print(f"   Range: [{delta_stability['delta_min']:.4f}, {delta_stability['delta_max']:.4f}]")

print(f"\n6. PRACTICAL IMPLICATION:")
corr_w = w_stats['corr_w_gjrx_vix']
if corr_w > 0.95:
    impl = "GJR-X(VIX9D) gives nearly identical VT weights to 12/VIX — marginal practical value for VT"
elif corr_w > 0.85:
    impl = "GJR-X(VIX9D) agrees with 12/VIX most of the time but diverges in stress — moderate practical value"
else:
    impl = "GJR-X(VIX9D) gives substantially different VT weights — significant practical difference"
print(f"   Weight correlation: {corr_w:.4f}")
print(f"   → {impl}")

results["key_findings"] = {
    "best_qlike_model": best_qlike,
    "mz_r2_best": max(mz_results, key=lambda x: mz_results[x]['R2']),
    "weight_correlation_gjrx_vix": w_stats['corr_w_gjrx_vix'],
    "practical_implication": impl,
    "delta_stable": bool(delta_stability.get('delta_cv', 999) < 0.5) if isinstance(delta_stability.get('delta_cv'), float) else False,
}

# Save results
results_path = 'experiments/k493_signal_comparison_results.json'
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {results_path}")
print(f"Total execution time: {elapsed:.1f}s")
