"""
K757bv2: Taiwan CoVaR Contagion Structure — CLEAN 0050.TW Data
===============================================================
Reruns K757b (fixed CoVaR analysis) with split-artifact-corrected 0050.TW data.

Problem in K757b:
  - Used raw yfinance 0050.TW data that has a split artifact at 2014-01-02
  - Pre-2014 prices ~4x too high
  - This corrupts: return correlations (including crisis/calm), RV computation,
    Granger causality tests, CoVaR analysis, and VT prediction models

Fix:
  - Uses `from volpred.utils import clean_tw50_data` for 0050.TW
  - Pre-2014 prices divided by 4
  - Returns recomputed from clean prices

Note: 2330.TW, 2881.TW, 2882.TW are NOT affected (they have different split history).

Key questions:
  1. Does financials→TSMC Granger causality survive?
  2. Does CoVaR significance hold?
  3. Does correlation structure change materially?

Data source: yfinance (0050.TW, 2330.TW, 2881.TW, 2882.TW, ^VIX) with split correction
Period: 2010-01-01 to 2026-03-31

[提出: User (split artifact fix), 執行: Claude]
Author: VolPred Research System
Date: 2026-03-31
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
import yfinance as yf

# CRITICAL FIX
from volpred.utils import clean_tw50_data

warnings.filterwarnings('ignore')

# ============================================================
# Part 0: Data Download — CLEAN 0050.TW
# ============================================================
print("=" * 70)
print("K757bv2: Taiwan CoVaR Contagion Structure (CLEAN 0050.TW)")
print("=" * 70)

start_period = '2010-01-01'
end_period = '2026-03-31'

# Download TW assets
tw_tickers = {
    '0050': '0050.TW',
    'TSMC': '2330.TW',
    'Fubon': '2881.TW',
    'Cathay': '2882.TW',
}

tw_data = {}
for name, ticker in tw_tickers.items():
    print(f"Downloading {name} ({ticker})...")
    df = yf.download(ticker, start=start_period, end=end_period, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if name == '0050':
        # CLEAN the split artifact
        prices_raw = df['Close'].copy()
        prices_clean, returns_clean = clean_tw50_data(prices_raw)
        tw_data[name] = prices_clean
        print(f"  {name} (CLEAN): {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

        # Verify fix
        split_date = pd.Timestamp('2014-01-02')
        if split_date in prices_clean.index:
            pre_dates = prices_clean.index[prices_clean.index < split_date]
            if len(pre_dates) > 0:
                pre_clean = float(prices_clean.loc[pre_dates[-1]])
                post_clean = float(prices_clean.loc[split_date])
                pre_raw = float(prices_raw.loc[pre_dates[-1]])
                post_raw = float(prices_raw.loc[split_date])
                print(f"    Split check: RAW {pre_raw:.2f}→{post_raw:.2f} (ratio {pre_raw/post_raw:.2f}), "
                      f"CLEAN {pre_clean:.2f}→{post_clean:.2f} (ratio {pre_clean/post_clean:.2f})")
    else:
        tw_data[name] = df['Close'].copy()
        print(f"  {name}: {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Build TW prices DataFrame
tw_prices = pd.DataFrame(tw_data).dropna()
print(f"\nTW merged dataset: {len(tw_prices)} obs, {tw_prices.index[0].strftime('%Y-%m-%d')} to {tw_prices.index[-1].strftime('%Y-%m-%d')}")

# Download VIX
print(f"Downloading VIX...")
vix_df = yf.download('^VIX', start=start_period, end=end_period, progress=False)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix_raw = vix_df['Close'].copy()
print(f"  VIX: {len(vix_df)} obs")

# Align VIX to TW calendar
vix_aligned = vix_raw.reindex(tw_prices.index, method='ffill')
n_ffilled = vix_aligned.notna().sum() - vix_raw.reindex(tw_prices.index).notna().sum()
print(f"VIX aligned to TW calendar: {vix_aligned.notna().sum()} obs ({n_ffilled} forward-filled)")

valid_mask = vix_aligned.notna()
tw_prices = tw_prices[valid_mask]
vix_aligned = vix_aligned[valid_mask]

prices = tw_prices.copy()
prices['VIX'] = vix_aligned
print(f"Final merged dataset: {len(prices)} obs")

# Returns
assets = ['0050', 'TSMC', 'Fubon', 'Cathay']
returns = prices[assets].pct_change().dropna()
print(f"Returns: {len(returns)} obs")

# Realized volatility
rv = returns.rolling(20).std() * np.sqrt(252)
rv = rv.dropna()

results = {
    'experiment_id': 'K757bv2',
    'title': 'Taiwan CoVaR Contagion Structure — CLEAN 0050.TW Data',
    'data_source': 'yfinance + clean_tw50_data (volpred.utils)',
    'data_fix': 'Pre-2014 0050.TW prices divided by 4 (split ratio); other TW tickers unaffected',
    'original_experiment': 'K757b',
    'tickers': {**tw_tickers, 'VIX': '^VIX'},
    'period': f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    'n_obs_prices': len(prices),
    'n_obs_returns': len(returns),
    'n_vix_ffilled': int(n_ffilled),
    'proposer': 'User (split artifact fix)',
    'executor': 'Claude',
}

# ============================================================
# Part A: Pairwise Correlation Structure
# ============================================================
print("\n" + "=" * 70)
print("Part A: Pairwise Correlation Structure (CLEAN)")
print("=" * 70)

corr_full = returns[assets].corr()
print("\nFull-sample return correlations:")
print(corr_full.round(3))

results['part_a'] = {'full_sample_corr': corr_full.to_dict()}

# Rolling correlations
roll_window = 60
pairs = [('0050', 'TSMC'), ('0050', 'Fubon'), ('0050', 'Cathay'),
         ('TSMC', 'Fubon'), ('TSMC', 'Cathay'), ('Fubon', 'Cathay')]

rolling_corr_stats = {}
for a, b in pairs:
    rc = returns[a].rolling(roll_window).corr(returns[b]).dropna()
    pair_key = f"{a}-{b}"
    rolling_corr_stats[pair_key] = {
        'mean': float(rc.mean()), 'std': float(rc.std()),
        'min': float(rc.min()), 'max': float(rc.max()),
    }
    print(f"\n{pair_key}: mean={rc.mean():.3f}, std={rc.std():.3f}, range=[{rc.min():.3f}, {rc.max():.3f}]")

results['part_a']['rolling_60d_corr'] = rolling_corr_stats

# Crisis vs calm
vix_for_regime = prices['VIX'].reindex(returns.index)
crisis_mask = vix_for_regime > 30
calm_mask = vix_for_regime <= 20
n_crisis = int(crisis_mask.sum())
n_calm = int(calm_mask.sum())

crisis_corr = {}
calm_corr = {}
for a, b in pairs:
    pair_key = f"{a}-{b}"
    if crisis_mask.sum() > 30:
        crisis_corr[pair_key] = float(returns.loc[crisis_mask, a].corr(returns.loc[crisis_mask, b]))
    if calm_mask.sum() > 30:
        calm_corr[pair_key] = float(returns.loc[calm_mask, a].corr(returns.loc[calm_mask, b]))

print(f"\nCrisis (VIX>30): {n_crisis} days")
for k, v in crisis_corr.items():
    print(f"  {k}: {v:.3f}")
print(f"\nCalm (VIX<=20): {n_calm} days")
for k, v in calm_corr.items():
    print(f"  {k}: {v:.3f}")

results['part_a']['crisis_corr'] = crisis_corr
results['part_a']['calm_corr'] = calm_corr
results['part_a']['n_crisis_days'] = n_crisis
results['part_a']['n_calm_days'] = n_calm

# ============================================================
# Part B: Granger Causality (AIC lag selection)
# ============================================================
print("\n" + "=" * 70)
print("Part B: Granger Causality Network (RV) — AIC lag selection (CLEAN)")
print("=" * 70)

# ADF tests
print("\nADF tests on realized vol:")
adf_results = {}
for asset in assets:
    adf_stat, adf_p, _, _, _, _ = adfuller(rv[asset].dropna(), maxlag=10)
    adf_results[asset] = {'stat': float(adf_stat), 'p_value': float(adf_p)}
    print(f"  {asset}: ADF stat={adf_stat:.3f}, p={adf_p:.6f}")

use_diff = any(r['p_value'] > 0.05 for r in adf_results.values())
if use_diff:
    print("\nSome RV non-stationary -> using first-differenced RV")
    rv_test = rv.diff().dropna()
else:
    rv_test = rv.copy()

gc_pairs = [
    ('0050', 'TSMC'), ('TSMC', '0050'),
    ('0050', 'Fubon'), ('Fubon', '0050'),
    ('0050', 'Cathay'), ('Cathay', '0050'),
    ('TSMC', 'Fubon'), ('Fubon', 'TSMC'),
    ('TSMC', 'Cathay'), ('Cathay', 'TSMC'),
    ('Fubon', 'Cathay'), ('Cathay', 'Fubon'),
]

granger_results = {}
print(f"\n{'X -> Y':<20} {'AIC Lag':>8} {'F-stat':>10} {'p-value':>10} {'Sig':>5}")
print("-" * 55)

for x_name, y_name in gc_pairs:
    gc_data = pd.DataFrame({'y': rv_test[y_name], 'x': rv_test[x_name]}).dropna()
    try:
        var_model = VAR(gc_data[['y', 'x']])
        lag_order_result = var_model.select_order(maxlags=10)
        aic_lag = max(1, min(lag_order_result.aic, 10))

        gc_test = grangercausalitytests(gc_data[['y', 'x']], maxlag=aic_lag, verbose=False)
        f_stat = gc_test[aic_lag][0]['ssr_ftest'][0]
        p_val = gc_test[aic_lag][0]['ssr_ftest'][1]

        sig = '***' if p_val < 0.001 else '**' if p_val < 0.01 else '*' if p_val < 0.05 else ''
        pair_key = f"{x_name}->{y_name}"
        granger_results[pair_key] = {
            'aic_lag': int(aic_lag), 'f_stat': float(f_stat),
            'p_value': float(p_val), 'significant': p_val < 0.05
        }
        print(f"{pair_key:<20} {aic_lag:>8} {f_stat:>10.3f} {p_val:>10.6f} {sig:>5}")
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
# Part C: CoVaR — Adrian & Brunnermeier (2016)
# ============================================================
print("\n" + "=" * 70)
print("Part C: CoVaR Analysis — Adrian & Brunnermeier (2016) (CLEAN)")
print("=" * 70)


def compute_covar_ab2016(y_returns, x_returns, state_vars=None, tau=0.05):
    """Proper Adrian & Brunnermeier (2016) CoVaR. Same as K757b."""
    df = pd.DataFrame({'y': y_returns, 'x': x_returns}).dropna()
    if state_vars is not None:
        for col in state_vars.columns:
            df[col] = state_vars[col]
        df = df.dropna()

    n = len(df)
    if n < 200:
        return None

    state_cols = list(state_vars.columns) if state_vars is not None else []

    X_var_x = pd.DataFrame(index=df.index)
    X_var_x['x_lag1'] = df['x'].shift(1)
    for col in state_cols:
        X_var_x[f'{col}_lag1'] = df[col].shift(1)
    X_var_x['const'] = 1.0

    valid = X_var_x.notna().all(axis=1)
    X_var_x = X_var_x[valid]
    x_dep = df['x'][valid]
    y_dep = df['y'][valid]

    if len(x_dep) < 200:
        return None

    try:
        model_var_x_tau = QuantReg(x_dep, X_var_x)
        res_var_x_tau = model_var_x_tau.fit(q=tau, max_iter=5000)
        var_x_tau = res_var_x_tau.predict(X_var_x)

        model_var_x_med = QuantReg(x_dep, X_var_x)
        res_var_x_med = model_var_x_med.fit(q=0.50, max_iter=5000)
        var_x_med = res_var_x_med.predict(X_var_x)
    except Exception as e:
        print(f"  VaR_x estimation failed: {e}")
        return None

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

    X_eval_distress = X_covar.copy()
    X_eval_distress['x_lag1'] = var_x_tau.values
    X_eval_median = X_covar.copy()
    X_eval_median['x_lag1'] = var_x_med.values

    covar_distress = res_covar_tau.predict(X_eval_distress)
    covar_median = res_covar_med.predict(X_eval_median)
    delta_covar = covar_distress - covar_median

    unconditional_var = np.percentile(y_dep, tau * 100)
    beta_x_tau = float(res_covar_tau.params.get('x_lag1', np.nan))
    beta_x_tau_pval = float(res_covar_tau.pvalues.get('x_lag1', np.nan))

    return {
        'covar_distress_mean': float(covar_distress.mean()),
        'covar_median_mean': float(covar_median.mean()),
        'delta_covar_mean': float(delta_covar.mean()),
        'delta_covar_std': float(delta_covar.std()),
        'unconditional_var': float(unconditional_var),
        'var_x_tau_mean': float(var_x_tau.mean()),
        'var_x_med_mean': float(var_x_med.mean()),
        'beta_x_tau': beta_x_tau,
        'beta_x_tau_pval': beta_x_tau_pval,
        'n_obs': int(len(y_dep)),
        'delta_covar_series': delta_covar,
        'covar_index': y_dep.index,
    }


state = pd.DataFrame({
    'vix_level': prices['VIX'],
    'mkt_vol': returns['0050'].rolling(20).std() * np.sqrt(252),
}).reindex(returns.index)

covar_pairs = [
    ('0050', 'TSMC', 'TSMC -> 0050'),
    ('0050', 'Fubon', 'Fubon -> 0050'),
    ('0050', 'Cathay', 'Cathay -> 0050'),
    ('TSMC', 'Fubon', 'Fubon -> TSMC'),
]

covar_results = {}
print(f"\n{'Pair':<20} {'DeltaCoVaR':>12} {'beta(x,tau)':>12} {'p-value':>10}")
print("-" * 58)

covar_series_data = {}
for y_name, x_name, label in covar_pairs:
    result = compute_covar_ab2016(returns[y_name], returns[x_name], state_vars=state, tau=0.05)

    if result is not None:
        covar_series_data[label] = {
            'delta_covar': result['delta_covar_series'],
            'index': result['covar_index'],
        }
        result_json = {k: v for k, v in result.items()
                       if k not in ['delta_covar_series', 'covar_index']}
        covar_results[label] = result_json

        sig = '***' if result['beta_x_tau_pval'] < 0.001 else '**' if result['beta_x_tau_pval'] < 0.01 else '*' if result['beta_x_tau_pval'] < 0.05 else ''
        print(f"{label:<20} {result['delta_covar_mean']:>12.6f} {result['beta_x_tau']:>12.4f} {result['beta_x_tau_pval']:>9.4f}{sig}")
    else:
        print(f"{label:<20} FAILED")

results['part_c'] = {'covar_analysis': covar_results}

# Time-varying DeltaCoVaR for TSMC -> 0050
if 'TSMC -> 0050' in covar_series_data:
    dc = covar_series_data['TSMC -> 0050']['delta_covar']
    idx = covar_series_data['TSMC -> 0050']['index']

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

    print(f"\nTime-varying DeltaCoVaR (TSMC → 0050):")
    for period, vals in periods.items():
        print(f"  {period}: mean={vals['mean_delta_covar']:.6f}, std={vals['std_delta_covar']:.6f}")

    from scipy.stats import linregress
    dc_values = dc.values
    time_idx = np.arange(len(dc_values))
    slope, intercept, r, p, se = linregress(time_idx, dc_values)
    print(f"  Trend: slope={slope:.2e}, r²={r**2:.4f}, p={p:.6f}")

    results['part_c']['tsmc_covar_periods'] = periods
    results['part_c']['tsmc_covar_trend'] = {
        'slope': float(slope), 'r_squared': float(r**2), 'p_value': float(p),
    }

# ============================================================
# Part D: TSMC RV as Predictor (Beyond VIX)
# ============================================================
print("\n" + "=" * 70)
print("Part D: TSMC RV as Predictor for 0050 VT (CLEAN)")
print("=" * 70)

from sklearn.linear_model import LinearRegression
from scipy.stats import spearmanr

rv5 = returns.rolling(5).std() * np.sqrt(252)

pred_df = pd.DataFrame({
    '0050_rv': rv5['0050'],
    'TSMC_rv': rv5['TSMC'].shift(1),
    'Fubon_rv': rv5['Fubon'].shift(1),
    'Cathay_rv': rv5['Cathay'].shift(1),
    'VIX': prices['VIX'].shift(1),
    'TSMC_ret_abs': returns['TSMC'].abs().shift(1),
}).dropna()

pred_df['target'] = returns['0050'].abs().shift(-1)
pred_df = pred_df.dropna()

print(f"Prediction sample: {len(pred_df)} obs")

X1 = pred_df[['VIX']]
X2 = pred_df[['VIX', 'TSMC_rv']]
X3 = pred_df[['VIX', 'TSMC_rv', 'Fubon_rv', 'Cathay_rv']]
X4 = pred_df[['TSMC_rv']]
y = pred_df['target']

oos_window = 500
models_oos = {'VIX_only': [], 'VIX+TSMC': [], 'VIX+TSMC+Fin': [], 'TSMC_only': []}
model_Xs = {'VIX_only': X1, 'VIX+TSMC': X2, 'VIX+TSMC+Fin': X3, 'TSMC_only': X4}

print("Out-of-sample evaluation (rolling 500-day window)...")
for i in range(oos_window, len(pred_df) - 1):
    for mname, X in model_Xs.items():
        X_train = X.iloc[i - oos_window:i]
        y_train = y.iloc[i - oos_window:i]
        X_test = X.iloc[i:i + 1]
        y_test = y.iloc[i]
        reg = LinearRegression().fit(X_train, y_train)
        pred = reg.predict(X_test)[0]
        models_oos[mname].append((y_test, pred))

print(f"\n{'Model':<20} {'R^2 OOS':>10} {'QLIKE':>10} {'Spearman':>10}")
print("-" * 55)

oos_metrics = {}
for mname, preds in models_oos.items():
    actual = np.array([p[0] for p in preds])
    predicted = np.maximum(np.array([p[1] for p in preds]), 1e-8)

    ss_res = np.sum((actual - predicted) ** 2)
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    r2_oos = 1 - ss_res / ss_tot
    qlike = np.mean(np.log(predicted) + actual / predicted)
    rho, p_rho = spearmanr(actual, predicted)

    oos_metrics[mname] = {
        'r2_oos': float(r2_oos), 'qlike': float(qlike),
        'spearman_rho': float(rho), 'spearman_p': float(p_rho),
        'n': len(preds),
    }
    print(f"{mname:<20} {r2_oos:>10.4f} {qlike:>10.4f} {rho:>10.4f}")

results['part_d'] = {'oos_prediction': oos_metrics}

# Partial correlation
from numpy.linalg import lstsq
X_vix = pred_df['VIX'].values.reshape(-1, 1)
X_vix_c = np.column_stack([X_vix, np.ones(len(X_vix))])

beta1, _, _, _ = lstsq(X_vix_c, pred_df['0050_rv'].values, rcond=None)
resid_0050 = pred_df['0050_rv'].values - X_vix_c @ beta1

beta2, _, _, _ = lstsq(X_vix_c, pred_df['TSMC_rv'].values, rcond=None)
resid_tsmc = pred_df['TSMC_rv'].values - X_vix_c @ beta2

partial_r, partial_p = spearmanr(resid_0050, resid_tsmc)
print(f"\nPartial corr TSMC_RV -> 0050_RV | VIX: rho={partial_r:.4f}, p={partial_p:.2e}")

results['part_d']['partial_corr_tsmc_0050_given_vix'] = {
    'spearman_rho': float(partial_r), 'p_value': float(partial_p),
}

# ============================================================
# Part E: Comparison with K757b (raw data)
# ============================================================
print("\n" + "=" * 70)
print("Part E: K757b (raw) vs K757bv2 (clean) Comparison")
print("=" * 70)

k757b_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k757b_taiwan_covar_fixed_results.json'
comparison = {}
try:
    with open(k757b_path) as f:
        k757b = json.load(f)

    # Sample size
    orig_n = k757b.get('n_obs_returns', 0)
    new_n = results['n_obs_returns']
    print(f"\nSample size: K757b={orig_n}, K757bv2={new_n} (diff={new_n - orig_n})")
    comparison['sample_size_diff'] = new_n - orig_n

    # Correlation comparison
    print("\nFull-sample correlations (0050 pairs):")
    orig_corr = k757b.get('part_a', {}).get('full_sample_corr', {})
    for pair in ['TSMC', 'Fubon', 'Cathay']:
        old_val = orig_corr.get('0050', {}).get(pair, 'N/A')
        new_val = float(corr_full.loc['0050', pair])
        delta = new_val - old_val if isinstance(old_val, (int, float)) else 'N/A'
        print(f"  0050-{pair}: {old_val:.4f} → {new_val:.4f} (Δ={delta:+.4f})" if isinstance(delta, float) else f"  0050-{pair}: {old_val} → {new_val:.4f}")

    comparison['corr_changes'] = {
        f'0050-{p}': {
            'old': orig_corr.get('0050', {}).get(p),
            'new': float(corr_full.loc['0050', p]),
        } for p in ['TSMC', 'Fubon', 'Cathay']
    }

    # Granger comparison
    print("\nGranger causality comparison:")
    orig_gc = k757b.get('part_b', {}).get('granger_causality', {})
    gc_changes = []
    for pair_key, new_vals in granger_results.items():
        if isinstance(new_vals, dict) and 'aic_lag' in new_vals:
            orig_vals = orig_gc.get(pair_key, {})
            if isinstance(orig_vals, dict) and 'significant' in orig_vals:
                orig_sig = orig_vals['significant']
                new_sig = new_vals['significant']
                if orig_sig != new_sig:
                    direction = "sig→insig" if orig_sig else "insig→sig"
                    gc_changes.append(f"{pair_key}: {direction}")
                    print(f"  {pair_key}: {direction} (p: {orig_vals.get('p_value', '?'):.4f} → {new_vals['p_value']:.4f})")

    if not gc_changes:
        print("  No significance changes in Granger causality")
    comparison['granger_significance_changes'] = gc_changes

    # CoVaR comparison
    print("\nCoVaR comparison:")
    orig_covar = k757b.get('part_c', {}).get('covar_analysis', {})
    covar_changes = {}
    for label, new_cv in covar_results.items():
        orig_cv = orig_covar.get(label, {})
        if orig_cv:
            old_dc = orig_cv.get('delta_covar_mean', float('nan'))
            new_dc = new_cv.get('delta_covar_mean', float('nan'))
            old_sig = orig_cv.get('beta_x_tau_pval', 1) < 0.05
            new_sig = new_cv.get('beta_x_tau_pval', 1) < 0.05
            sig_change = "CHANGED" if old_sig != new_sig else "same"
            print(f"  {label}: DeltaCoVaR {old_dc:.6f} → {new_dc:.6f}, sig: {sig_change}")
            covar_changes[label] = {
                'delta_covar_old': old_dc, 'delta_covar_new': new_dc,
                'significant_old': old_sig, 'significant_new': new_sig,
                'significance_changed': old_sig != new_sig,
            }
    comparison['covar_changes'] = covar_changes

    # OOS prediction comparison
    print("\nOOS prediction comparison:")
    orig_oos = k757b.get('part_d', {}).get('oos_prediction', {})
    for mname in ['VIX_only', 'VIX+TSMC']:
        old_r2 = orig_oos.get(mname, {}).get('r2_oos', 'N/A')
        new_r2 = oos_metrics.get(mname, {}).get('r2_oos', 'N/A')
        print(f"  {mname}: R²OOS {old_r2:.4f} → {new_r2:.4f}" if isinstance(old_r2, float) else f"  {mname}: {old_r2} → {new_r2}")

    comparison['loaded_original'] = True

except FileNotFoundError:
    comparison['loaded_original'] = False
    print("K757b results not found for comparison.")

results['part_e'] = {'comparison_with_k757b': comparison}

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY (K757bv2 — CLEAN 0050.TW)")
print("=" * 70)

findings = []

tsmc_0050_corr = corr_full.loc['0050', 'TSMC']
fin_0050_corr = (corr_full.loc['0050', 'Fubon'] + corr_full.loc['0050', 'Cathay']) / 2
findings.append(f"A: 0050-TSMC corr = {tsmc_0050_corr:.3f}, 0050-Fin avg = {fin_0050_corr:.3f}")

sig_gc = [(k, v) for k, v in granger_results.items() if isinstance(v, dict) and v.get('significant')]
findings.append(f"B: Significant Granger causality: {len(sig_gc)}/12 pairs")
for k, v in sig_gc:
    findings.append(f"   {k}: F={v['f_stat']:.2f}, p={v['p_value']:.6f}")

tsmc_cv = covar_results.get('TSMC -> 0050', {})
if tsmc_cv:
    findings.append(f"C: TSMC DeltaCoVaR→0050 = {tsmc_cv.get('delta_covar_mean', 0):.6f}, "
                    f"beta={tsmc_cv.get('beta_x_tau', 0):.4f}, p={tsmc_cv.get('beta_x_tau_pval', 1):.4f}")

vix_r2 = oos_metrics.get('VIX_only', {}).get('r2_oos', 0)
vix_tsmc_r2 = oos_metrics.get('VIX+TSMC', {}).get('r2_oos', 0)
findings.append(f"D: VIX-only OOS R²={vix_r2:.4f}, VIX+TSMC={vix_tsmc_r2:.4f}, gain={vix_tsmc_r2-vix_r2:+.4f}")
findings.append(f"D: Partial corr TSMC_RV→0050_RV|VIX = {partial_r:.4f} (p={partial_p:.2e})")

for f in findings:
    print(f)

results['summary'] = {'findings': findings}
results['references'] = [
    'K757b: Taiwan CoVaR contagion (raw 0050.TW, fixed A&B2016)',
    'Adrian & Brunnermeier (2016) CoVaR, American Economic Review',
    'K738: VT insurance cost-benefit',
]
results['timestamp'] = datetime.now().isoformat()

# Save
output_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k757bv2_taiwan_covar_clean_results.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\nResults saved to {output_path}")
print("K757bv2 complete.")
