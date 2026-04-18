"""
K757b: Taiwan CoVaR Contagion Structure — FIXED (3 bugs from Codex review)

Fixes applied to K757:
1. HIGH: Proper Adrian & Brunnermeier (2016) CoVaR implementation
   - Step 1: VaR_x(q) via quantile regression of x on lagged x + state vars
   - Step 2: CoVaR_{y|x} via quantile regression of y on x + state vars, evaluated at x = VaR_x(q)
   - Step 3: DeltaCoVaR = CoVaR_{y|x=VaR_x(5%)} - CoVaR_{y|x=VaR_x(50%)}
2. MEDIUM: Granger causality lag selection by AIC (not min-p loop)
3. MEDIUM: TW trading calendar as primary, forward-fill US VIX to TW dates

Research question: How does volatility/risk transmit across Taiwan's concentrated market?
- 0050.TW (index ETF), 2330.TW (TSMC), 2881.TW (Fubon FHC), 2882.TW (Cathay FHC)
- Pairwise rolling correlations, Granger causality, CoVaR (Adrian & Brunnermeier 2016)

Prior work:
- K757: Original version with 3 bugs identified by Codex review
- T16: TSMC vol r=0.885 with 0050 but no Granger causality; SPY Granger-causes 0050
- K82: TSMC explains 52.5% of 0050 variance; rolling beta 0.38->0.72

References:
- Adrian & Brunnermeier (2016) "CoVaR", American Economic Review
- Acharya et al. (2017) "Measuring Systemic Risk", RFS
- Engle & Manganelli (2004) "CAViaR", JBES

Data source: yfinance (0050.TW, 2330.TW, 2881.TW, 2882.TW, ^VIX)
Period: 2010-01-01 to 2026-03-28

[提出: Codex rescue (K757 review), 執行: Claude]
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
from datetime import datetime
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
from statsmodels.tsa.api import VAR
from statsmodels.regression.quantile_regression import QuantReg

warnings.filterwarnings('ignore')

# ============================================================
# Part 0: Data Download — FIX #3: TW calendar primary, ffill VIX
# ============================================================
print("=" * 70)
print("K757b: Taiwan CoVaR Contagion Structure (FIXED)")
print("=" * 70)

import yfinance as yf

# Download TW assets separately from US VIX
tw_tickers = {
    '0050': '0050.TW',
    'TSMC': '2330.TW',
    'Fubon': '2881.TW',
    'Cathay': '2882.TW',
}

# Download TW assets
tw_data = {}
for name, ticker in tw_tickers.items():
    print(f"Downloading {name} ({ticker})...")
    df = yf.download(ticker, start='2010-01-01', end='2026-03-29', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    tw_data[name] = df['Close'].copy()
    print(f"  {name}: {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Build TW prices DataFrame — inner join on TW assets only
tw_prices = pd.DataFrame(tw_data)
tw_prices = tw_prices.dropna()
print(f"\nTW merged dataset: {len(tw_prices)} obs, {tw_prices.index[0].strftime('%Y-%m-%d')} to {tw_prices.index[-1].strftime('%Y-%m-%d')}")

# Download VIX separately
print(f"Downloading VIX (^VIX)...")
vix_df = yf.download('^VIX', start='2010-01-01', end='2026-03-29', progress=False)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix_raw = vix_df['Close'].copy()
print(f"  VIX: {len(vix_df)} obs")

# FIX #3: Reindex VIX to TW trading calendar, forward-fill
# This keeps TW-only trading days (e.g., TW open but US closed for holiday)
# by carrying the most recent available VIX value forward
vix_aligned = vix_raw.reindex(tw_prices.index, method='ffill')
n_ffilled = vix_aligned.notna().sum() - vix_raw.reindex(tw_prices.index).notna().sum()
print(f"\nVIX aligned to TW calendar: {vix_aligned.notna().sum()} obs ({n_ffilled} forward-filled)")

# Drop any leading NaN (before first VIX observation)
valid_mask = vix_aligned.notna()
tw_prices = tw_prices[valid_mask]
vix_aligned = vix_aligned[valid_mask]

# Combine into single prices DataFrame
prices = tw_prices.copy()
prices['VIX'] = vix_aligned

print(f"Final merged dataset: {len(prices)} obs, {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")

# Compute simple returns for TW assets only
assets = ['0050', 'TSMC', 'Fubon', 'Cathay']
returns = prices[assets].pct_change().dropna()
print(f"Returns: {len(returns)} obs")

# Realized volatility (20-day rolling std, annualized)
rv = returns.rolling(20).std() * np.sqrt(252)
rv = rv.dropna()

results = {
    'experiment_id': 'K757b',
    'title': 'Taiwan CoVaR Contagion Structure (Fixed)',
    'data_source': 'yfinance',
    'tickers': {**tw_tickers, 'VIX': '^VIX'},
    'fixes_applied': [
        'FIX #1 (HIGH): Proper Adrian & Brunnermeier (2016) CoVaR — estimate VaR_x first, then condition on it',
        'FIX #2 (MEDIUM): Granger causality lag selection by AIC via VAR, not min-p loop',
        'FIX #3 (MEDIUM): TW calendar primary, forward-fill US VIX — no more dropping TW-only days',
    ],
    'period': f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    'n_obs_prices': len(prices),
    'n_obs_returns': len(returns),
    'n_vix_ffilled': int(n_ffilled),
}

# ============================================================
# Part A: Pairwise Correlation Structure (unchanged logic)
# ============================================================
print("\n" + "=" * 70)
print("Part A: Pairwise Correlation Structure")
print("=" * 70)

# Full-sample return correlations
corr_full = returns[assets].corr()
print("\nFull-sample return correlations:")
print(corr_full.round(3))

results['part_a'] = {
    'full_sample_corr': corr_full.to_dict(),
}

# Rolling 60-day correlations
roll_window = 60
pairs = [('0050', 'TSMC'), ('0050', 'Fubon'), ('0050', 'Cathay'),
         ('TSMC', 'Fubon'), ('TSMC', 'Cathay'), ('Fubon', 'Cathay')]

rolling_corr_stats = {}
for a, b in pairs:
    rc = returns[a].rolling(roll_window).corr(returns[b]).dropna()
    pair_key = f"{a}-{b}"
    rolling_corr_stats[pair_key] = {
        'mean': float(rc.mean()),
        'std': float(rc.std()),
        'min': float(rc.min()),
        'max': float(rc.max()),
        'q5': float(rc.quantile(0.05)),
        'q95': float(rc.quantile(0.95)),
        'pct_below_0.3': float((rc < 0.3).mean() * 100),
        'pct_above_0.8': float((rc > 0.8).mean() * 100),
    }
    print(f"\n{pair_key}: mean={rc.mean():.3f}, std={rc.std():.3f}, range=[{rc.min():.3f}, {rc.max():.3f}]")

results['part_a']['rolling_60d_corr'] = rolling_corr_stats

# Correlation stability: crisis vs calm
vix_for_regime = prices['VIX'].reindex(returns.index)
crisis_mask = vix_for_regime > 30
calm_mask = vix_for_regime <= 20
n_crisis = int(crisis_mask.sum())
n_calm = int(calm_mask.sum())
print(f"\nCrisis days (VIX>30): {n_crisis}, Calm days (VIX<=20): {n_calm}")

crisis_corr = {}
calm_corr = {}
for a, b in pairs:
    pair_key = f"{a}-{b}"
    if crisis_mask.sum() > 30:
        crisis_corr[pair_key] = float(returns.loc[crisis_mask, a].corr(returns.loc[crisis_mask, b]))
    if calm_mask.sum() > 30:
        calm_corr[pair_key] = float(returns.loc[calm_mask, a].corr(returns.loc[calm_mask, b]))

print("\nCrisis correlations (VIX>30):")
for k, v in crisis_corr.items():
    print(f"  {k}: {v:.3f}")

print("\nCalm correlations (VIX<=20):")
for k, v in calm_corr.items():
    print(f"  {k}: {v:.3f}")

results['part_a']['crisis_corr'] = crisis_corr
results['part_a']['calm_corr'] = calm_corr
results['part_a']['n_crisis_days'] = n_crisis
results['part_a']['n_calm_days'] = n_calm

# ============================================================
# Part B: Granger Causality Network — FIX #2: AIC lag selection
# ============================================================
print("\n" + "=" * 70)
print("Part B: Granger Causality Network (Realized Vol) — AIC lag selection")
print("=" * 70)

# ADF tests first
print("\nADF tests on realized vol:")
adf_results = {}
for asset in assets:
    adf_stat, adf_p, _, _, _, _ = adfuller(rv[asset].dropna(), maxlag=10)
    adf_results[asset] = {'stat': float(adf_stat), 'p_value': float(adf_p)}
    print(f"  {asset}: ADF stat={adf_stat:.3f}, p={adf_p:.6f} {'stationary' if adf_p < 0.05 else 'non-stationary'}")

# If non-stationary, use first-differenced RV
use_diff = any(r['p_value'] > 0.05 for r in adf_results.values())
if use_diff:
    print("\nSome RV series non-stationary -> using first-differenced RV")
    rv_test = rv.diff().dropna()
else:
    rv_test = rv.copy()

# FIX #2: Use VAR model with AIC for lag selection, then Granger F-test at that lag
gc_pairs = [
    ('0050', 'TSMC'), ('TSMC', '0050'),
    ('0050', 'Fubon'), ('Fubon', '0050'),
    ('0050', 'Cathay'), ('Cathay', '0050'),
    ('TSMC', 'Fubon'), ('Fubon', 'TSMC'),
    ('TSMC', 'Cathay'), ('Cathay', 'TSMC'),
    ('Fubon', 'Cathay'), ('Cathay', 'Fubon'),
]

granger_results = {}
print("\nGranger Causality Tests (AIC lag selection)")
print(f"{'X -> Y':<20} {'AIC Lag':>8} {'F-stat':>10} {'p-value':>10} {'Significant':>12}")
print("-" * 65)

for x_name, y_name in gc_pairs:
    gc_data = pd.DataFrame({
        'y': rv_test[y_name],
        'x': rv_test[x_name]
    }).dropna()

    try:
        # Step 1: Use VAR to select optimal lag by AIC
        var_model = VAR(gc_data[['y', 'x']])
        lag_order_result = var_model.select_order(maxlags=10)
        aic_lag = lag_order_result.aic
        # Ensure at least lag=1
        if aic_lag < 1:
            aic_lag = 1
        if aic_lag > 10:
            aic_lag = 10

        # Step 2: Run Granger causality at the AIC-selected lag only
        gc_test = grangercausalitytests(gc_data[['y', 'x']], maxlag=aic_lag, verbose=False)
        f_stat = gc_test[aic_lag][0]['ssr_ftest'][0]
        p_val = gc_test[aic_lag][0]['ssr_ftest'][1]

        sig = '***' if p_val < 0.001 else '**' if p_val < 0.01 else '*' if p_val < 0.05 else ''
        pair_key = f"{x_name}->{y_name}"
        granger_results[pair_key] = {
            'aic_lag': int(aic_lag),
            'f_stat': float(f_stat),
            'p_value': float(p_val),
            'significant': p_val < 0.05
        }
        print(f"{pair_key:<20} {aic_lag:>8} {f_stat:>10.3f} {p_val:>10.6f} {sig:>12}")
    except Exception as e:
        print(f"{x_name}->{y_name}: ERROR - {e}")
        granger_results[f"{x_name}->{y_name}"] = {'error': str(e)}

results['part_b'] = {
    'adf_results': adf_results,
    'used_differenced_rv': use_diff,
    'lag_selection_method': 'AIC via statsmodels VAR.select_order()',
    'granger_causality': granger_results,
}

# ============================================================
# Part C: CoVaR — FIX #1: Proper Adrian & Brunnermeier (2016)
# ============================================================
print("\n" + "=" * 70)
print("Part C: CoVaR Analysis — Proper Adrian & Brunnermeier (2016)")
print("=" * 70)


def compute_covar_ab2016(y_returns, x_returns, state_vars=None, tau=0.05):
    """
    Proper Adrian & Brunnermeier (2016) CoVaR implementation.

    Step 1: Estimate VaR_x(q) via quantile regression:
            X_t = alpha_x + beta_x * M_{t-1} + eps
            VaR_x(q) = predicted value at quantile q

    Step 2: Estimate CoVaR_{y|x}(q) via quantile regression:
            Y_t = alpha_y + beta_y * X_{t-1} + gamma_y * M_{t-1} + eps
            CoVaR_{y|x=VaR_x(q)} = alpha_y + beta_y * VaR_x(q) + gamma_y * M_{t-1}

    Step 3: DeltaCoVaR = CoVaR_{y|x=VaR_x(5%)} - CoVaR_{y|x=VaR_x(50%)}

    Parameters
    ----------
    y_returns : pd.Series
        System/portfolio returns (e.g., 0050)
    x_returns : pd.Series
        Institution returns (e.g., TSMC)
    state_vars : pd.DataFrame or None
        Conditioning state variables (e.g., VIX, market vol)
    tau : float
        Quantile level for VaR (default 0.05 = 5%)

    Returns
    -------
    dict with CoVaR statistics, or None if estimation fails
    """
    # Align data
    df = pd.DataFrame({'y': y_returns, 'x': x_returns}).dropna()

    if state_vars is not None:
        for col in state_vars.columns:
            df[col] = state_vars[col]
        df = df.dropna()

    n = len(df)
    if n < 200:
        return None

    # ---- Step 1: Estimate VaR_x(q) ----
    # Regress x on lagged state vars (and optionally lagged x)
    state_cols = list(state_vars.columns) if state_vars is not None else []

    # X equation regressors: lagged x + lagged state vars
    X_var_x = pd.DataFrame(index=df.index)
    X_var_x['x_lag1'] = df['x'].shift(1)
    for col in state_cols:
        X_var_x[f'{col}_lag1'] = df[col].shift(1)
    X_var_x['const'] = 1.0

    # Drop NaN from shift
    valid = X_var_x.notna().all(axis=1)
    X_var_x = X_var_x[valid]
    x_dep = df['x'][valid]
    y_dep = df['y'][valid]

    if len(x_dep) < 200:
        return None

    try:
        # VaR_x at distress quantile (tau)
        model_var_x_tau = QuantReg(x_dep, X_var_x)
        res_var_x_tau = model_var_x_tau.fit(q=tau, max_iter=5000)
        var_x_tau = res_var_x_tau.predict(X_var_x)  # Time-varying VaR_x(tau)

        # VaR_x at median (0.50)
        model_var_x_med = QuantReg(x_dep, X_var_x)
        res_var_x_med = model_var_x_med.fit(q=0.50, max_iter=5000)
        var_x_med = res_var_x_med.predict(X_var_x)  # Time-varying VaR_x(50%)
    except Exception as e:
        print(f"  VaR_x estimation failed: {e}")
        return None

    # ---- Step 2: Estimate CoVaR_{y|x}(q) ----
    # Regress y on lagged x + lagged state vars at quantile tau
    X_covar = pd.DataFrame(index=X_var_x.index)
    X_covar['x_lag1'] = df['x'].shift(1).reindex(X_var_x.index)
    for col in state_cols:
        X_covar[f'{col}_lag1'] = df[col].shift(1).reindex(X_var_x.index)
    X_covar['const'] = 1.0

    try:
        model_covar_tau = QuantReg(y_dep, X_covar)
        res_covar_tau = model_covar_tau.fit(q=tau, max_iter=5000)

        model_covar_med = QuantReg(y_dep, X_covar)
        res_covar_med = model_covar_med.fit(q=0.50, max_iter=5000)
    except Exception as e:
        print(f"  CoVaR estimation failed: {e}")
        return None

    # ---- Step 3: Compute CoVaR by substituting VaR_x into the y equation ----
    # CoVaR_{y|x=VaR_x(tau)} = alpha_y + beta_y * VaR_x(tau) + gamma_y * M_{t-1}
    # CoVaR_{y|x=VaR_x(50%)} = alpha_y + beta_y * VaR_x(50%) + gamma_y * M_{t-1}

    # Build X matrix with VaR_x substituted for x_lag1
    X_eval_distress = X_covar.copy()
    X_eval_distress['x_lag1'] = var_x_tau.values  # Condition on x being at its VaR

    X_eval_median = X_covar.copy()
    X_eval_median['x_lag1'] = var_x_med.values  # Condition on x being at its median

    covar_distress = res_covar_tau.predict(X_eval_distress)  # CoVaR when x is in distress
    covar_median = res_covar_med.predict(X_eval_median)      # CoVaR when x is at median

    delta_covar = covar_distress - covar_median

    # Unconditional VaR for comparison
    unconditional_var = np.percentile(y_dep, tau * 100)

    # CoVaR beta on x (sensitivity of y's tail to x)
    beta_x_tau = float(res_covar_tau.params.get('x_lag1', np.nan))
    beta_x_tau_pval = float(res_covar_tau.pvalues.get('x_lag1', np.nan))
    beta_x_med = float(res_covar_med.params.get('x_lag1', np.nan))

    # Average VaR_x values
    mean_var_x_tau = float(var_x_tau.mean())
    mean_var_x_med = float(var_x_med.mean())

    return {
        'covar_distress_mean': float(covar_distress.mean()),
        'covar_distress_std': float(covar_distress.std()),
        'covar_median_mean': float(covar_median.mean()),
        'delta_covar_mean': float(delta_covar.mean()),
        'delta_covar_std': float(delta_covar.std()),
        'delta_covar_q5': float(np.percentile(delta_covar, 5)),
        'delta_covar_q95': float(np.percentile(delta_covar, 95)),
        'unconditional_var': float(unconditional_var),
        'var_x_tau_mean': mean_var_x_tau,
        'var_x_med_mean': mean_var_x_med,
        'beta_x_tau': beta_x_tau,
        'beta_x_tau_pval': beta_x_tau_pval,
        'beta_x_med': beta_x_med,
        'n_obs': int(len(y_dep)),
        # For time-varying analysis
        'delta_covar_series': delta_covar,
        'covar_index': y_dep.index,
    }


# State variables: VIX level and market vol (lagged via ffill alignment)
state = pd.DataFrame({
    'vix_level': prices['VIX'],
    'mkt_vol': returns['0050'].rolling(20).std() * np.sqrt(252),
}).reindex(returns.index)

# CoVaR pairs: contribution of each asset to 0050
covar_pairs = [
    ('0050', 'TSMC', 'TSMC -> 0050'),
    ('0050', 'Fubon', 'Fubon -> 0050'),
    ('0050', 'Cathay', 'Cathay -> 0050'),
    ('TSMC', 'Fubon', 'Fubon -> TSMC'),
]

covar_results = {}
print(f"\nCoVaR at tau=0.05 — Proper Adrian & Brunnermeier (2016)")
print(f"{'Pair':<20} {'DeltaCoVaR':>12} {'Std':>10} {'VaR_x(5%)':>12} {'VaR_x(50%)':>12} {'beta(x,tau)':>12} {'p-value':>10} {'Uncondit VaR':>14}")
print("-" * 115)

covar_series_data = {}  # Store for Part D

for y_name, x_name, label in covar_pairs:
    result = compute_covar_ab2016(
        returns[y_name],
        returns[x_name],
        state_vars=state,
        tau=0.05
    )

    if result is not None:
        # Store series for later use
        covar_series_data[label] = {
            'delta_covar': result['delta_covar_series'],
            'index': result['covar_index'],
        }

        # Remove non-serializable items for JSON
        result_json = {k: v for k, v in result.items()
                       if k not in ['delta_covar_series', 'covar_index']}
        covar_results[label] = result_json

        sig = '***' if result['beta_x_tau_pval'] < 0.001 else '**' if result['beta_x_tau_pval'] < 0.01 else '*' if result['beta_x_tau_pval'] < 0.05 else ''
        print(f"{label:<20} {result['delta_covar_mean']:>12.6f} {result['delta_covar_std']:>10.6f} {result['var_x_tau_mean']:>12.6f} {result['var_x_med_mean']:>12.6f} {result['beta_x_tau']:>12.4f} {result['beta_x_tau_pval']:>9.4f}{sig} {result['unconditional_var']:>14.6f}")
    else:
        print(f"{label:<20} FAILED")

results['part_c'] = {'covar_analysis': covar_results}

# Time-varying DeltaCoVaR: Is TSMC's contribution increasing?
print("\n--- Time-Varying DeltaCoVaR for TSMC -> 0050 ---")
if 'TSMC -> 0050' in covar_series_data:
    dc = covar_series_data['TSMC -> 0050']['delta_covar']
    idx = covar_series_data['TSMC -> 0050']['index']

    # Split into 3-year periods
    periods = {}
    for yr_start in range(2011, 2025, 3):
        yr_end = yr_start + 3
        mask = (idx.year >= yr_start) & (idx.year < yr_end)
        if mask.sum() > 50:
            period_key = f"{yr_start}-{yr_end}"
            periods[period_key] = {
                'mean_delta_covar': float(dc[mask].mean()),
                'std_delta_covar': float(dc[mask].std()),
                'n_obs': int(mask.sum()),
            }

    print(f"{'Period':<12} {'Mean DeltaCoVaR':>16} {'Std':>10} {'N':>6}")
    print("-" * 48)
    for period, vals in periods.items():
        print(f"{period:<12} {vals['mean_delta_covar']:>16.6f} {vals['std_delta_covar']:>10.6f} {vals['n_obs']:>6}")

    # Trend test: regress DeltaCoVaR on time
    from scipy.stats import linregress
    dc_values = dc.values
    time_idx = np.arange(len(dc_values))
    slope, intercept, r, p, se = linregress(time_idx, dc_values)
    print(f"\nLinear trend in DeltaCoVaR: slope={slope:.2e}, r^2={r**2:.4f}, p={p:.6f}")

    results['part_c']['tsmc_covar_periods'] = periods
    results['part_c']['tsmc_covar_trend'] = {
        'slope': float(slope),
        'r_squared': float(r**2),
        'p_value': float(p),
        'interpretation': 'TSMC systemic risk increasing' if slope < 0 and p < 0.05 else
                         'No significant trend' if p >= 0.05 else 'TSMC systemic risk decreasing'
    }

# ============================================================
# Part D: Implications for VT — Does TSMC RV improve 0050 prediction?
# ============================================================
print("\n" + "=" * 70)
print("Part D: TSMC RV as Predictor for 0050 VT (Beyond VIX)")
print("=" * 70)

from sklearn.linear_model import LinearRegression
from scipy.stats import spearmanr

# Use 5-day RV instead of 20-day for more responsiveness
rv5 = returns.rolling(5).std() * np.sqrt(252)

# Predictors (all lagged by 1 day) — signal.shift(1)
pred_df = pd.DataFrame({
    '0050_rv': rv5['0050'],
    'TSMC_rv': rv5['TSMC'].shift(1),       # signal.shift(1)
    'Fubon_rv': rv5['Fubon'].shift(1),     # signal.shift(1)
    'Cathay_rv': rv5['Cathay'].shift(1),   # signal.shift(1)
    'VIX': prices['VIX'].shift(1),         # signal.shift(1) — lagged for Taiwan
    'TSMC_ret_abs': returns['TSMC'].abs().shift(1),  # signal.shift(1)
}).dropna()

# Target: next-day 0050 absolute return (proxy for realized vol)
pred_df['target'] = returns['0050'].abs().shift(-1)  # Next-day |return|
pred_df = pred_df.dropna()

print(f"Prediction sample: {len(pred_df)} obs")

# Model 1: VIX only
X1 = pred_df[['VIX']]
# Model 2: VIX + TSMC_rv
X2 = pred_df[['VIX', 'TSMC_rv']]
# Model 3: VIX + TSMC_rv + Financial_rv
X3 = pred_df[['VIX', 'TSMC_rv', 'Fubon_rv', 'Cathay_rv']]
# Model 4: TSMC_rv only (no VIX)
X4 = pred_df[['TSMC_rv']]

y = pred_df['target']

# OOS evaluation (rolling 500-day window)
oos_window = 500
models_oos = {'VIX_only': [], 'VIX+TSMC': [], 'VIX+TSMC+Fin': [], 'TSMC_only': []}
model_Xs = {'VIX_only': X1, 'VIX+TSMC': X2, 'VIX+TSMC+Fin': X3, 'TSMC_only': X4}

print("\nOut-of-sample evaluation (rolling 500-day window)...")
for i in range(oos_window, len(pred_df) - 1):
    for mname, X in model_Xs.items():
        X_train = X.iloc[i - oos_window:i]
        y_train = y.iloc[i - oos_window:i]
        X_test = X.iloc[i:i + 1]
        y_test = y.iloc[i]

        reg = LinearRegression().fit(X_train, y_train)
        pred = reg.predict(X_test)[0]
        models_oos[mname].append((y_test, pred))

# Compute R^2 OOS and QLIKE
print(f"\n{'Model':<20} {'R^2 OOS':>10} {'QLIKE':>10} {'Spearman rho':>12} {'N':>6}")
print("-" * 62)

oos_metrics = {}
for mname, preds in models_oos.items():
    actual = np.array([p[0] for p in preds])
    predicted = np.array([p[1] for p in preds])

    # Clip predictions to positive
    predicted = np.maximum(predicted, 1e-8)

    # R^2 OOS
    ss_res = np.sum((actual - predicted) ** 2)
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    r2_oos = 1 - ss_res / ss_tot

    # QLIKE
    qlike = np.mean(np.log(predicted) + actual / predicted)

    # Spearman
    rho, p_rho = spearmanr(actual, predicted)

    oos_metrics[mname] = {
        'r2_oos': float(r2_oos),
        'qlike': float(qlike),
        'spearman_rho': float(rho),
        'spearman_p': float(p_rho),
        'n': len(preds),
    }
    print(f"{mname:<20} {r2_oos:>10.4f} {qlike:>10.4f} {rho:>12.4f} {len(preds):>6}")

results['part_d'] = {'oos_prediction': oos_metrics}

# Partial correlation: TSMC_RV -> 0050_RV | VIX
from numpy.linalg import lstsq

X_vix = pred_df['VIX'].values.reshape(-1, 1)
X_vix_c = np.column_stack([X_vix, np.ones(len(X_vix))])

# Residualize 0050_rv on VIX
beta1, _, _, _ = lstsq(X_vix_c, pred_df['0050_rv'].values, rcond=None)
resid_0050 = pred_df['0050_rv'].values - X_vix_c @ beta1

# Residualize TSMC_rv on VIX
beta2, _, _, _ = lstsq(X_vix_c, pred_df['TSMC_rv'].values, rcond=None)
resid_tsmc = pred_df['TSMC_rv'].values - X_vix_c @ beta2

partial_r, partial_p = spearmanr(resid_0050, resid_tsmc)
print(f"\nPartial correlation TSMC_RV -> 0050_RV | VIX: rho={partial_r:.4f}, p={partial_p:.2e}")

results['part_d']['partial_corr_tsmc_0050_given_vix'] = {
    'spearman_rho': float(partial_r),
    'p_value': float(partial_p),
    'interpretation': 'TSMC RV adds information beyond VIX' if partial_p < 0.05 and abs(partial_r) > 0.1 else 'TSMC RV adds minimal information beyond VIX'
}

# ============================================================
# Part E: Comparison with K757 (original buggy version)
# ============================================================
print("\n" + "=" * 70)
print("Part E: K757 vs K757b Comparison")
print("=" * 70)

# Load original results for comparison
original_path = os.path.join(os.path.dirname(__file__), 'k757_taiwan_covar_results.json')
comparison = {}
if os.path.exists(original_path):
    with open(original_path, 'r') as f:
        k757_orig = json.load(f)

    print("\nKey differences after fixes:")
    print("-" * 60)

    # Sample size difference (FIX #3: more TW days kept)
    orig_n = k757_orig.get('n_obs_returns', 0)
    new_n = results['n_obs_returns']
    print(f"Sample size: K757={orig_n}, K757b={new_n} (diff={new_n - orig_n})")
    comparison['sample_size_diff'] = new_n - orig_n

    # Granger: AIC lag vs min-p lag
    print("\nGranger causality (AIC lag vs min-p lag):")
    orig_gc = k757_orig.get('part_b', {}).get('granger_causality', {})
    for pair_key, new_vals in granger_results.items():
        if isinstance(new_vals, dict) and 'aic_lag' in new_vals:
            # Map pair_key format: K757b uses '->' while K757 uses unicode arrow
            orig_key_arrow = pair_key.replace('->', '\u2192')
            orig_vals = orig_gc.get(orig_key_arrow, orig_gc.get(pair_key, {}))
            if isinstance(orig_vals, dict) and 'best_lag' in orig_vals:
                orig_lag = orig_vals['best_lag']
                new_lag = new_vals['aic_lag']
                orig_sig = orig_vals.get('significant', False)
                new_sig = new_vals.get('significant', False)
                changed = ''
                if orig_sig != new_sig:
                    changed = f' *** CHANGED: {"sig->insig" if orig_sig else "insig->sig"}'
                print(f"  {pair_key}: lag {orig_lag}(minp) -> {new_lag}(AIC), p: {orig_vals.get('p_value', '?'):.4f} -> {new_vals['p_value']:.4f}{changed}")

    # CoVaR comparison
    print("\nCoVaR (proper A&B2016 vs original):")
    orig_covar = k757_orig.get('part_c', {}).get('covar_analysis', {})
    for label, new_cv in covar_results.items():
        # Try to match original label format
        orig_label = label
        orig_cv = orig_covar.get(orig_label, {})
        if orig_cv:
            orig_dc = orig_cv.get('delta_covar_mean', float('nan'))
            new_dc = new_cv.get('delta_covar_mean', float('nan'))
            print(f"  {label}: DeltaCoVaR {orig_dc:.6f} (orig) -> {new_dc:.6f} (fixed)")
            print(f"    VaR_x(5%)={new_cv.get('var_x_tau_mean', 'N/A'):.6f}, VaR_x(50%)={new_cv.get('var_x_med_mean', 'N/A'):.6f}")

    comparison['loaded_original'] = True
else:
    comparison['loaded_original'] = False
    print("Original K757 results not found for comparison.")

results['part_e'] = {'comparison_with_k757': comparison}

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY (K757b — Fixed)")
print("=" * 70)

findings = []

# A: Correlation structure
tsmc_0050_corr = corr_full.loc['0050', 'TSMC']
fin_0050_corr = (corr_full.loc['0050', 'Fubon'] + corr_full.loc['0050', 'Cathay']) / 2
findings.append(f"A1: 0050-TSMC correlation = {tsmc_0050_corr:.3f}, 0050-Financials avg = {fin_0050_corr:.3f}")

if crisis_corr and calm_corr:
    crisis_diff = crisis_corr.get('0050-TSMC', 0) - calm_corr.get('0050-TSMC', 0)
    findings.append(f"A2: Crisis-Calm correlation shift (0050-TSMC): {crisis_diff:+.3f}")

# B: Granger causality (AIC-based)
sig_gc = [(k, v) for k, v in granger_results.items() if isinstance(v, dict) and v.get('significant')]
findings.append(f"B1: Significant Granger causality pairs (AIC lag): {len(sig_gc)}/12")
for k, v in sig_gc:
    findings.append(f"    {k}: F={v['f_stat']:.2f}, p={v['p_value']:.6f}, AIC lag={v['aic_lag']}")

# C: CoVaR (proper A&B 2016)
if covar_results:
    tsmc_cv = covar_results.get('TSMC -> 0050', {})
    fubon_cv = covar_results.get('Fubon -> 0050', {})
    if tsmc_cv:
        findings.append(f"C1: TSMC DeltaCoVaR to 0050 = {tsmc_cv.get('delta_covar_mean', 0):.6f} (proper A&B 2016)")
        findings.append(f"    VaR_TSMC(5%) mean = {tsmc_cv.get('var_x_tau_mean', 0):.6f}, VaR_TSMC(50%) mean = {tsmc_cv.get('var_x_med_mean', 0):.6f}")
        findings.append(f"    beta(x, tau=0.05) = {tsmc_cv.get('beta_x_tau', 0):.4f}, p = {tsmc_cv.get('beta_x_tau_pval', 1):.4f}")
    if fubon_cv:
        findings.append(f"C2: Fubon DeltaCoVaR to 0050 = {fubon_cv.get('delta_covar_mean', 0):.6f}")
    if tsmc_cv and fubon_cv:
        tsmc_dc = abs(tsmc_cv.get('delta_covar_mean', 0))
        fubon_dc = abs(fubon_cv.get('delta_covar_mean', 0))
        if fubon_dc > 0:
            ratio = tsmc_dc / fubon_dc
            findings.append(f"C3: |TSMC/Fubon| systemic risk ratio = {ratio:.2f}x")

# D: VT implications
if oos_metrics:
    vix_only_r2 = oos_metrics.get('VIX_only', {}).get('r2_oos', 0)
    vix_tsmc_r2 = oos_metrics.get('VIX+TSMC', {}).get('r2_oos', 0)
    improvement = vix_tsmc_r2 - vix_only_r2
    findings.append(f"D1: VIX-only OOS R^2 = {vix_only_r2:.4f}, VIX+TSMC = {vix_tsmc_r2:.4f}, improvement = {improvement:+.4f}")

findings.append(f"D2: Partial corr TSMC_RV->0050_RV|VIX = {partial_r:.4f} (p={partial_p:.2e})")

# Bug fix impact
findings.append(f"E1: FIX #1 (CoVaR): Now estimates VaR_x(q) first, then conditions CoVaR on it — proper A&B 2016")
findings.append(f"E2: FIX #2 (Granger): AIC lag selection via VAR, not min-p data-mining")
findings.append(f"E3: FIX #3 (Calendar): TW-primary calendar, {n_ffilled} TW-only days preserved via VIX ffill")

for f in findings:
    print(f)

results['summary'] = {
    'findings': findings,
    'conclusion': '',
}

# Generate conclusion
conclusion_parts = []
conclusion_parts.append(f"Taiwan market shows high concentration: 0050-TSMC corr={tsmc_0050_corr:.3f}.")

if sig_gc:
    gc_directions = [k for k, _ in sig_gc]
    conclusion_parts.append(f"With AIC lag selection, Granger causality found in {len(sig_gc)} directions: {', '.join(gc_directions)}.")
else:
    conclusion_parts.append("No significant Granger causality in realized vol with proper AIC lag selection.")

tsmc_cv = covar_results.get('TSMC -> 0050')
if tsmc_cv:
    beta_x = tsmc_cv.get('beta_x_tau', 0)
    pval_x = tsmc_cv.get('beta_x_tau_pval', 1)
    if pval_x < 0.05:
        conclusion_parts.append(f"Proper A&B(2016) CoVaR confirms TSMC has significant tail-risk contribution to 0050 (beta={beta_x:.4f}, p={pval_x:.4f}).")
    else:
        conclusion_parts.append(f"With proper A&B(2016) CoVaR, TSMC tail-risk contribution to 0050 is not significant (beta={beta_x:.4f}, p={pval_x:.4f}).")

conclusion_parts.append(f"TSMC RV adds {'meaningful' if abs(partial_r) > 0.1 else 'minimal'} information beyond VIX for 0050 prediction (partial rho={partial_r:.4f}).")

conclusion = ' '.join(conclusion_parts)
results['summary']['conclusion'] = conclusion
print(f"\n{conclusion}")

# ============================================================
# Save results
# ============================================================
output_path = os.path.join(os.path.dirname(__file__), 'k757b_taiwan_covar_fixed_results.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\nResults saved to {output_path}")
print("K757b complete.")
