"""
K759: Financial Sector Early Warning System for TSMC Volatility

Background:
- K757b confirmed financials Granger-cause TSMC vol (Fubon F=5.59, Cathay F=3.01, both p<0.001)
- This experiment builds a PRACTICAL early warning indicator from that finding

Part A: Composite Financial Stress Index
- Equal-weighted 20-day RV of Fubon (2881.TW) + Cathay (2882.TW)
- Threshold: 75th percentile → "financial stress" signal
- Lead time analysis: how many days before TSMC vol spikes?

Part B: Predictive Power
- Financial stress index predicts next-5-day TSMC RV?
- Partial correlation controlling for VIX
- Incremental info beyond VIX? (DM test)
- ROC: predict TSMC >2-sigma vol events

Part C: Trading Application
- When financial stress signal fires: reduce 0050.TW weight by 50%
- Compare vs standard 8.63/VIX Taiwan VT
- Monthly rebalancing with stress override
- signal.shift(1) for all signals
- TX 10 bps for TW

Prior work:
- K757b: Financials Granger-cause TSMC vol (Fubon→TSMC F=5.59, Cathay→TSMC F=3.01)
- K739b: Taiwan VT cross-validation (TW calendar primary methodology)
- T16: TSMC vol r=0.885 with 0050 but no Granger causality
- K82: TSMC explains 52.5% of 0050 variance

References:
- Adrian & Brunnermeier (2016) "CoVaR", American Economic Review
- Diebold & Mariano (1995) "Comparing Predictive Accuracy", JBES
- Engle & Manganelli (2004) "CAViaR", JBES

Data source: yfinance (0050.TW, 2330.TW, 2881.TW, 2882.TW, ^VIX)
Period: 2010-01-01 to 2026-03-29

[提出: Claude (from K757b direction), 執行: Claude]
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
from datetime import datetime, timezone
from scipy import stats
from sklearn.metrics import roc_auc_score, roc_curve

warnings.filterwarnings('ignore')

# ============================================================
# Part 0: Data Download — TW calendar primary (K739b methodology)
# ============================================================
print("=" * 70)
print("K759: Financial Sector Early Warning System for TSMC Volatility")
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
    df = yf.download(ticker, start='2010-01-01', end='2026-03-30', progress=False)
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
vix_df = yf.download('^VIX', start='2010-01-01', end='2026-03-30', progress=False)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix_raw = vix_df['Close'].copy()
print(f"  VIX: {len(vix_df)} obs")

# FIX from K739b review: Reindex VIX to TW trading calendar, forward-fill
# This keeps TW-only trading days by carrying the most recent available VIX value forward
vix_aligned = vix_raw.reindex(tw_prices.index, method='ffill')
n_ffilled = int(vix_aligned.notna().sum() - vix_raw.reindex(tw_prices.index).notna().sum())
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
    'experiment_id': 'K759',
    'title': 'Financial Sector Early Warning System for TSMC Volatility',
    'data_source': 'yfinance',
    'tickers': {**tw_tickers, 'VIX': '^VIX'},
    'prior_work': 'K757b (Granger causality confirmed), K739b (TW calendar methodology)',
    'period': f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    'n_obs_prices': len(prices),
    'n_obs_returns': len(returns),
    'n_vix_ffilled': n_ffilled,
    'proposer': 'Claude (from K757b direction)',
    'executor': 'Claude',
}

# ============================================================
# Part A: Composite Financial Stress Index
# ============================================================
print("\n" + "=" * 70)
print("Part A: Composite Financial Stress Index")
print("=" * 70)

# A1: Build composite index = equal-weighted 20-day RV of Fubon + Cathay
fin_rv = rv[['Fubon', 'Cathay']].copy()
composite_fsi = fin_rv.mean(axis=1)  # Equal-weighted
composite_fsi.name = 'FSI'

print(f"\nFinancial Stress Index (FSI) = mean(Fubon_RV20, Cathay_RV20)")
print(f"  N obs: {composite_fsi.notna().sum()}")
print(f"  Mean: {composite_fsi.mean():.4f}")
print(f"  Std:  {composite_fsi.std():.4f}")
print(f"  Median: {composite_fsi.median():.4f}")
print(f"  P75: {composite_fsi.quantile(0.75):.4f}")
print(f"  P90: {composite_fsi.quantile(0.90):.4f}")
print(f"  P95: {composite_fsi.quantile(0.95):.4f}")
print(f"  Skew: {composite_fsi.skew():.3f}")
print(f"  Kurt: {composite_fsi.kurtosis():.3f}")

# A2: Stress signal: FSI > 75th percentile
threshold_75 = composite_fsi.quantile(0.75)
threshold_90 = composite_fsi.quantile(0.90)
stress_signal = (composite_fsi > threshold_75).astype(int)
severe_stress = (composite_fsi > threshold_90).astype(int)

n_stress_days = stress_signal.sum()
n_severe_days = severe_stress.sum()
print(f"\nStress signal (FSI > P75 = {threshold_75:.4f}): {n_stress_days} days ({100*n_stress_days/len(stress_signal):.1f}%)")
print(f"Severe stress (FSI > P90 = {threshold_90:.4f}): {n_severe_days} days ({100*n_severe_days/len(severe_stress):.1f}%)")

# A3: Lead time analysis — when FSI spikes, how many days before TSMC RV spikes?
# Define TSMC vol spike: TSMC RV > 2-sigma above mean
tsmc_rv = rv['TSMC']
tsmc_rv_mean = tsmc_rv.mean()
tsmc_rv_std = tsmc_rv.std()
tsmc_spike_threshold = tsmc_rv_mean + 2 * tsmc_rv_std
tsmc_spike = (tsmc_rv > tsmc_spike_threshold).astype(int)
n_tsmc_spikes = tsmc_spike.sum()
print(f"\nTSMC vol spike threshold (mean + 2*std): {tsmc_spike_threshold:.4f}")
print(f"  TSMC vol spike days: {n_tsmc_spikes} ({100*n_tsmc_spikes/len(tsmc_spike):.1f}%)")

# Lead-lag: for each TSMC spike, check if FSI stress was active N days before
lead_lags = [1, 2, 3, 5, 10, 15, 20]
lead_lag_results = {}

# Align indices
common_idx = tsmc_spike.index.intersection(stress_signal.index)
tsmc_spike_aligned = tsmc_spike.loc[common_idx]
stress_aligned = stress_signal.loc[common_idx]
severe_aligned = severe_stress.loc[common_idx]

print(f"\nLead-lag analysis (FSI stress → TSMC vol spike):")
print(f"{'Lead (days)':<15} {'P(spike|stress)':<20} {'P(spike|no_stress)':<22} {'Lift':<10} {'N_stress':<10}")
print("-" * 77)

for lag in lead_lags:
    # Shift stress signal forward by `lag` days: stress at t predicts spike at t+lag
    stress_lagged = stress_aligned.shift(lag).dropna().astype(int)
    spike_at_lead = tsmc_spike_aligned.reindex(stress_lagged.index)

    # Drop NaN
    valid = stress_lagged.notna() & spike_at_lead.notna()
    sl = stress_lagged[valid]
    sp = spike_at_lead[valid]

    # Conditional probabilities
    stress_mask = sl == 1
    no_stress_mask = sl == 0

    if stress_mask.sum() > 0 and no_stress_mask.sum() > 0:
        p_spike_given_stress = sp[stress_mask].mean()
        p_spike_given_no_stress = sp[no_stress_mask].mean()
        lift = p_spike_given_stress / max(p_spike_given_no_stress, 1e-10)
        print(f"{lag:<15} {p_spike_given_stress:<20.4f} {p_spike_given_no_stress:<22.4f} {lift:<10.2f} {stress_mask.sum():<10}")

        lead_lag_results[f"lead_{lag}d"] = {
            'p_spike_given_stress': round(float(p_spike_given_stress), 4),
            'p_spike_given_no_stress': round(float(p_spike_given_no_stress), 4),
            'lift': round(float(lift), 2),
            'n_stress_days': int(stress_mask.sum()),
            'n_no_stress_days': int(no_stress_mask.sum()),
        }

# A4: Cluster analysis — how often does FSI stress persist?
stress_runs = []
current_run = 0
for v in stress_signal:
    if v == 1:
        current_run += 1
    else:
        if current_run > 0:
            stress_runs.append(current_run)
        current_run = 0
if current_run > 0:
    stress_runs.append(current_run)

if stress_runs:
    print(f"\nStress episode clustering:")
    print(f"  Number of episodes: {len(stress_runs)}")
    print(f"  Mean duration: {np.mean(stress_runs):.1f} days")
    print(f"  Median duration: {np.median(stress_runs):.1f} days")
    print(f"  Max duration: {max(stress_runs)} days")
    print(f"  Min duration: {min(stress_runs)} days")

results['part_a'] = {
    'fsi_stats': {
        'mean': round(float(composite_fsi.mean()), 4),
        'std': round(float(composite_fsi.std()), 4),
        'median': round(float(composite_fsi.median()), 4),
        'p75': round(float(threshold_75), 4),
        'p90': round(float(threshold_90), 4),
        'p95': round(float(composite_fsi.quantile(0.95)), 4),
        'skew': round(float(composite_fsi.skew()), 3),
        'kurtosis': round(float(composite_fsi.kurtosis()), 3),
    },
    'stress_days': int(n_stress_days),
    'severe_stress_days': int(n_severe_days),
    'tsmc_spike_threshold': round(float(tsmc_spike_threshold), 4),
    'tsmc_spike_days': int(n_tsmc_spikes),
    'lead_lag_analysis': lead_lag_results,
    'stress_episodes': {
        'count': len(stress_runs),
        'mean_duration': round(float(np.mean(stress_runs)), 1) if stress_runs else None,
        'median_duration': round(float(np.median(stress_runs)), 1) if stress_runs else None,
        'max_duration': int(max(stress_runs)) if stress_runs else None,
    },
}

# ============================================================
# Part B: Predictive Power
# ============================================================
print("\n" + "=" * 70)
print("Part B: Predictive Power")
print("=" * 70)

# B1: Does FSI predict next-5-day TSMC RV?
# Forward TSMC RV: average of next 5 days
tsmc_rv_fwd5 = tsmc_rv.rolling(5).mean().shift(-5)

# Build regression DataFrame
reg_df = pd.DataFrame({
    'FSI': composite_fsi,
    'VIX': prices['VIX'].reindex(composite_fsi.index),
    'TSMC_RV': tsmc_rv,
    'TSMC_RV_fwd5': tsmc_rv_fwd5,
}).dropna()

print(f"\nRegression sample: {len(reg_df)} obs")

# B1a: Simple correlation FSI → future TSMC RV
corr_fsi_future = reg_df['FSI'].corr(reg_df['TSMC_RV_fwd5'])
corr_vix_future = reg_df['VIX'].corr(reg_df['TSMC_RV_fwd5'])
print(f"\nSimple correlations with future TSMC RV (5d):")
print(f"  FSI:  {corr_fsi_future:.4f}")
print(f"  VIX:  {corr_vix_future:.4f}")

# B1b: Partial correlation FSI → future TSMC RV | VIX
# partial_corr(X,Y|Z) = corr(resid(X~Z), resid(Y~Z))
from numpy.linalg import lstsq

def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z."""
    z_mat = np.column_stack([z, np.ones(len(z))])
    # Residualize x
    coef_x, _, _, _ = lstsq(z_mat, x, rcond=None)
    resid_x = x - z_mat @ coef_x
    # Residualize y
    coef_y, _, _, _ = lstsq(z_mat, y, rcond=None)
    resid_y = y - z_mat @ coef_y
    return np.corrcoef(resid_x, resid_y)[0, 1]

pcorr_fsi = partial_corr(
    reg_df['FSI'].values,
    reg_df['TSMC_RV_fwd5'].values,
    reg_df['VIX'].values
)
print(f"\nPartial correlation FSI → TSMC_RV_fwd5 | VIX: {pcorr_fsi:.4f}")

# Test significance of partial correlation
n = len(reg_df)
t_stat_pcorr = pcorr_fsi * np.sqrt((n - 3) / (1 - pcorr_fsi**2))
p_val_pcorr = 2 * (1 - stats.t.cdf(abs(t_stat_pcorr), n - 3))
print(f"  t-stat: {t_stat_pcorr:.3f}, p-value: {p_val_pcorr:.6f}")

# B2: Regression: TSMC_RV_fwd5 ~ FSI + VIX vs TSMC_RV_fwd5 ~ VIX
from statsmodels.api import OLS, add_constant

# Model 1: VIX only
X_vix = add_constant(reg_df[['VIX']])
y = reg_df['TSMC_RV_fwd5']
model_vix = OLS(y, X_vix).fit(cov_type='HC1')
print(f"\nModel 1: TSMC_RV_fwd5 ~ VIX")
print(f"  R²: {model_vix.rsquared:.4f}, Adj R²: {model_vix.rsquared_adj:.4f}")
print(f"  VIX coef: {model_vix.params['VIX']:.6f} (t={model_vix.tvalues['VIX']:.2f}, p={model_vix.pvalues['VIX']:.4f})")

# Model 2: VIX + FSI
X_both = add_constant(reg_df[['VIX', 'FSI']])
model_both = OLS(y, X_both).fit(cov_type='HC1')
print(f"\nModel 2: TSMC_RV_fwd5 ~ VIX + FSI")
print(f"  R²: {model_both.rsquared:.4f}, Adj R²: {model_both.rsquared_adj:.4f}")
print(f"  VIX coef: {model_both.params['VIX']:.6f} (t={model_both.tvalues['VIX']:.2f}, p={model_both.pvalues['VIX']:.4f})")
print(f"  FSI coef: {model_both.params['FSI']:.6f} (t={model_both.tvalues['FSI']:.2f}, p={model_both.pvalues['FSI']:.4f})")

delta_r2 = model_both.rsquared - model_vix.rsquared
print(f"\n  ΔR²: {delta_r2:.4f} ({100*delta_r2:.2f}%)")

# B3: Diebold-Mariano test — does FSI add info beyond VIX?
# Forecast errors from both models
e1 = model_vix.resid  # VIX only
e2 = model_both.resid  # VIX + FSI
d = e1**2 - e2**2  # loss differential (MSE)

# DM test with HAC standard errors
from statsmodels.stats.diagnostic import acorr_ljungbox
dm_mean = d.mean()
# Newey-West HAC SE
from statsmodels.regression.linear_model import OLS as OLS2
dm_reg = OLS2(d, np.ones(len(d))).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
dm_t = float(dm_reg.tvalues.iloc[0]) if hasattr(dm_reg.tvalues, 'iloc') else float(dm_reg.tvalues[0])
dm_p = float(dm_reg.pvalues.iloc[0]) if hasattr(dm_reg.pvalues, 'iloc') else float(dm_reg.pvalues[0])
print(f"\nDiebold-Mariano test (VIX-only vs VIX+FSI):")
print(f"  Mean loss diff: {dm_mean:.6f}")
print(f"  DM t-stat (HAC): {dm_t:.3f}")
print(f"  DM p-value: {dm_p:.4f}")

# B4: ROC analysis — can FSI predict TSMC >2-sigma vol events?
# Binary target: TSMC vol spike within next 5 days
tsmc_spike_fwd5 = tsmc_spike.rolling(5).max().shift(-5)  # 1 if any spike in next 5 days

roc_df = pd.DataFrame({
    'FSI': composite_fsi,
    'VIX': prices['VIX'].reindex(composite_fsi.index),
    'spike_fwd5': tsmc_spike_fwd5,
}).dropna()

print(f"\nROC analysis sample: {len(roc_df)} obs")
print(f"  Spike events (any in next 5d): {int(roc_df['spike_fwd5'].sum())} ({100*roc_df['spike_fwd5'].mean():.1f}%)")

# AUC for FSI
auc_fsi = roc_auc_score(roc_df['spike_fwd5'], roc_df['FSI'])
fpr_fsi, tpr_fsi, thresholds_fsi = roc_curve(roc_df['spike_fwd5'], roc_df['FSI'])

# AUC for VIX
auc_vix = roc_auc_score(roc_df['spike_fwd5'], roc_df['VIX'])
fpr_vix, tpr_vix, thresholds_vix = roc_curve(roc_df['spike_fwd5'], roc_df['VIX'])

# AUC for FSI + VIX (logistic regression score)
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

scaler = StandardScaler()
X_combo = scaler.fit_transform(roc_df[['FSI', 'VIX']])
lr = LogisticRegression(random_state=42).fit(X_combo, roc_df['spike_fwd5'])
combo_score = lr.predict_proba(X_combo)[:, 1]
auc_combo = roc_auc_score(roc_df['spike_fwd5'], combo_score)

print(f"\nROC AUC scores:")
print(f"  FSI alone:  {auc_fsi:.4f}")
print(f"  VIX alone:  {auc_vix:.4f}")
print(f"  FSI + VIX:  {auc_combo:.4f}")
print(f"  ΔAUC (combo - VIX): {auc_combo - auc_vix:.4f}")

# B5: Bootstrap test for AUC difference significance
n_boot = 5000
np.random.seed(42)
auc_diffs_boot = []
for i in range(n_boot):
    idx = np.random.choice(len(roc_df), len(roc_df), replace=True)
    y_b = roc_df['spike_fwd5'].values[idx]
    if y_b.sum() == 0 or y_b.sum() == len(y_b):
        continue
    auc_vix_b = roc_auc_score(y_b, roc_df['VIX'].values[idx])
    auc_fsi_b = roc_auc_score(y_b, roc_df['FSI'].values[idx])
    auc_diffs_boot.append(auc_fsi_b - auc_vix_b)

auc_diffs_boot = np.array(auc_diffs_boot)
auc_diff_mean = auc_diffs_boot.mean()
auc_diff_se = auc_diffs_boot.std()
auc_diff_ci = (np.percentile(auc_diffs_boot, 2.5), np.percentile(auc_diffs_boot, 97.5))
print(f"\nBootstrap AUC difference (FSI - VIX), {n_boot} reps:")
print(f"  Mean diff: {auc_diff_mean:.4f}")
print(f"  SE: {auc_diff_se:.4f}")
print(f"  95% CI: [{auc_diff_ci[0]:.4f}, {auc_diff_ci[1]:.4f}]")

results['part_b'] = {
    'n_obs': len(reg_df),
    'simple_corr_fsi_future': round(float(corr_fsi_future), 4),
    'simple_corr_vix_future': round(float(corr_vix_future), 4),
    'partial_corr_fsi_given_vix': round(float(pcorr_fsi), 4),
    'partial_corr_t': round(float(t_stat_pcorr), 3),
    'partial_corr_p': round(float(p_val_pcorr), 6),
    'model_vix_only': {
        'r2': round(float(model_vix.rsquared), 4),
        'adj_r2': round(float(model_vix.rsquared_adj), 4),
        'vix_coef': round(float(model_vix.params['VIX']), 6),
        'vix_t': round(float(model_vix.tvalues['VIX']), 2),
    },
    'model_vix_plus_fsi': {
        'r2': round(float(model_both.rsquared), 4),
        'adj_r2': round(float(model_both.rsquared_adj), 4),
        'vix_coef': round(float(model_both.params['VIX']), 6),
        'vix_t': round(float(model_both.tvalues['VIX']), 2),
        'fsi_coef': round(float(model_both.params['FSI']), 6),
        'fsi_t': round(float(model_both.tvalues['FSI']), 2),
        'fsi_p': round(float(model_both.pvalues['FSI']), 6),
    },
    'delta_r2': round(float(delta_r2), 4),
    'dm_test': {
        'mean_loss_diff': round(float(dm_mean), 6),
        'dm_t_hac': round(float(dm_t), 3),
        'dm_p': round(float(dm_p), 4),
    },
    'roc_analysis': {
        'n_obs': len(roc_df),
        'spike_rate': round(float(roc_df['spike_fwd5'].mean()), 4),
        'auc_fsi': round(float(auc_fsi), 4),
        'auc_vix': round(float(auc_vix), 4),
        'auc_combo': round(float(auc_combo), 4),
        'delta_auc_combo_vs_vix': round(float(auc_combo - auc_vix), 4),
    },
    'bootstrap_auc_diff': {
        'n_boot': n_boot,
        'mean_diff_fsi_vs_vix': round(float(auc_diff_mean), 4),
        'se': round(float(auc_diff_se), 4),
        'ci_95_lower': round(float(auc_diff_ci[0]), 4),
        'ci_95_upper': round(float(auc_diff_ci[1]), 4),
    },
}

# ============================================================
# Part C: Trading Application
# ============================================================
print("\n" + "=" * 70)
print("Part C: Trading Application")
print("=" * 70)

# C1: Build strategy returns
# Get 0050 returns aligned with signals
ret_0050 = returns['0050']

# VIX for 8.63/VIX strategy
vix_for_strategy = prices['VIX'].reindex(ret_0050.index)

# Strategy 1: Standard 8.63/VIX Taiwan VT (baseline)
# Weight = min(8.63 / VIX, 1.5) — capped at 150%
# signal.shift(1): use yesterday's VIX for today's weight
w_vt_raw = 8.63 / vix_for_strategy
w_vt = w_vt_raw.clip(0, 1.5)
w_vt_signal = w_vt.shift(1)  # ← CRITICAL: signal.shift(1)

# Strategy 2: VT with Financial Stress Override
# Same as VT, but when FSI stress fires, reduce weight by 50%
stress_for_strategy = stress_signal.reindex(ret_0050.index).fillna(0)
stress_shifted = stress_for_strategy.shift(1)  # ← CRITICAL: signal.shift(1)

w_override_raw = w_vt_signal.copy()
# When stress, reduce weight by 50%
stress_mask_strat = stress_shifted == 1
w_override = w_override_raw.copy()
w_override[stress_mask_strat] = w_override_raw[stress_mask_strat] * 0.5

# Strategy 3: Monthly rebalancing VT with stress override
# Only rebalance monthly, but allow intra-month stress override
# Monthly VT weight: use first-of-month VIX
monthly_mask = pd.Series(False, index=ret_0050.index)
prev_month = None
for i, dt in enumerate(ret_0050.index):
    if prev_month is None or dt.month != prev_month:
        monthly_mask.iloc[i] = True
        prev_month = dt.month

w_monthly_base = w_vt_signal.copy()
# Forward-fill monthly: only update weight at month boundaries
w_monthly = w_monthly_base.where(monthly_mask).ffill()
# Apply stress override on top
w_monthly_override = w_monthly.copy()
w_monthly_override[stress_mask_strat] = w_monthly[stress_mask_strat] * 0.5

# Strategy 4: Buy and Hold 0050
w_bh = pd.Series(1.0, index=ret_0050.index)

# Calculate portfolio returns (excess = w * r_equity + (1-w) * r_cash; assume cash = 0)
# TX cost: 10 bps per turnover
TX_COST = 0.0010  # 10 bps

def calc_strategy_returns(weights, returns_series, tx_cost=TX_COST):
    """Calculate strategy returns with TX cost."""
    port_ret = weights * returns_series
    # TX cost on weight changes
    w_change = weights.diff().abs().fillna(0)
    tx = w_change * tx_cost
    net_ret = port_ret - tx
    return net_ret.dropna()

strat_names = ['BH_0050', '8.63/VIX_VT', 'VT+FSI_Override', 'Monthly_VT+FSI']
strat_weights = [w_bh, w_vt_signal, w_override, w_monthly_override]
strat_results = {}

print(f"\nStrategy comparison (2010-2026, TX={TX_COST*10000:.0f}bps):")
print(f"{'Strategy':<25} {'CAGR':<10} {'Vol':<10} {'Sharpe':<10} {'MDD':<10} {'Calmar':<10} {'TX_cost':<10}")
print("-" * 85)

for name, w in zip(strat_names, strat_weights):
    net_ret = calc_strategy_returns(w, ret_0050)

    # Drop leading NaN
    net_ret = net_ret.dropna()

    # Metrics
    ann_ret = net_ret.mean() * 252
    ann_vol = net_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum_ret = (1 + net_ret).cumprod()
    peak = cum_ret.cummax()
    dd = (cum_ret - peak) / peak
    mdd = dd.min()

    calmar = ann_ret / abs(mdd) if abs(mdd) > 0 else 0

    # TX cost total
    w_change = w.reindex(net_ret.index).diff().abs().fillna(0)
    total_tx = (w_change * TX_COST).sum()

    print(f"{name:<25} {ann_ret:<10.4f} {ann_vol:<10.4f} {sharpe:<10.3f} {mdd:<10.4f} {calmar:<10.3f} {total_tx:<10.4f}")

    strat_results[name] = {
        'ann_return': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 3),
        'mdd': round(float(mdd), 4),
        'calmar': round(float(calmar), 3),
        'total_tx_cost': round(float(total_tx), 4),
        'n_obs': len(net_ret),
    }

# C2: Rolling Sharpe comparison (252-day rolling)
print(f"\nRolling 252-day Sharpe comparison:")
for name, w in zip(strat_names, strat_weights):
    net_ret = calc_strategy_returns(w, ret_0050).dropna()
    rolling_sharpe = (net_ret.rolling(252).mean() / net_ret.rolling(252).std()) * np.sqrt(252)
    rolling_sharpe = rolling_sharpe.dropna()
    if len(rolling_sharpe) > 0:
        print(f"  {name:<25} mean={rolling_sharpe.mean():.3f}, std={rolling_sharpe.std():.3f}, min={rolling_sharpe.min():.3f}, max={rolling_sharpe.max():.3f}")

# C3: Subsample analysis — crisis vs calm periods
# Use VIX regimes
vix_reindexed = prices['VIX'].reindex(ret_0050.index)
crisis_mask_sub = vix_reindexed > 25  # VIX > 25 = elevated
calm_mask_sub = vix_reindexed <= 25

print(f"\nSubsample: Crisis (VIX>25) vs Calm (VIX<=25)")
for period_name, mask in [('Crisis (VIX>25)', crisis_mask_sub), ('Calm (VIX<=25)', calm_mask_sub)]:
    n_days = mask.sum()
    print(f"\n  {period_name} ({n_days} days):")
    for name, w in zip(strat_names, strat_weights):
        net_ret = calc_strategy_returns(w, ret_0050).dropna()
        sub_ret = net_ret[mask.reindex(net_ret.index, fill_value=False)]
        if len(sub_ret) > 20:
            sr = sub_ret.mean() / sub_ret.std() * np.sqrt(252) if sub_ret.std() > 0 else 0
            print(f"    {name:<25} Sharpe={sr:.3f} (N={len(sub_ret)})")

# C4: Event study — performance around FSI stress episodes
# For each stress onset, track cumulative returns over next 20 days
stress_onsets = []
was_stress = False
for i, (dt, v) in enumerate(stress_signal.items()):
    if v == 1 and not was_stress:
        stress_onsets.append(dt)
    was_stress = (v == 1)

print(f"\nEvent study: {len(stress_onsets)} stress onset episodes")

event_window = 20
event_returns_vt = []
event_returns_override = []
event_returns_bh = []

for onset in stress_onsets:
    # Find index position in ret_0050
    if onset not in ret_0050.index:
        continue
    pos = ret_0050.index.get_loc(onset)
    if pos + event_window >= len(ret_0050):
        continue

    window_idx = ret_0050.index[pos:pos+event_window]

    r_bh = ret_0050.loc[window_idx].values
    r_vt = (w_vt_signal.reindex(window_idx) * ret_0050.loc[window_idx]).values
    r_ov = (w_override.reindex(window_idx) * ret_0050.loc[window_idx]).values

    event_returns_bh.append(r_bh)
    event_returns_vt.append(r_vt)
    event_returns_override.append(r_ov)

if event_returns_bh:
    event_returns_bh = np.array(event_returns_bh)
    event_returns_vt = np.array(event_returns_vt)
    event_returns_override = np.array(event_returns_override)

    cum_bh = np.cumprod(1 + event_returns_bh, axis=1).mean(axis=0) - 1
    cum_vt = np.cumprod(1 + event_returns_vt, axis=1).mean(axis=0) - 1
    cum_ov = np.cumprod(1 + event_returns_override, axis=1).mean(axis=0) - 1

    print(f"  Average cumulative return over {event_window}d after stress onset:")
    print(f"    BH 0050:        {cum_bh[-1]*100:+.2f}%")
    print(f"    8.63/VIX VT:    {cum_vt[-1]*100:+.2f}%")
    print(f"    VT+FSI Override: {cum_ov[-1]*100:+.2f}%")

    strat_results['event_study'] = {
        'n_episodes': len(stress_onsets),
        'window_days': event_window,
        'avg_cum_return_20d': {
            'BH_0050': round(float(cum_bh[-1]), 4),
            '8.63/VIX_VT': round(float(cum_vt[-1]), 4),
            'VT+FSI_Override': round(float(cum_ov[-1]), 4),
        },
    }

# C5: DM test between strategies
print(f"\nDM tests (pairwise):")
dm_pairs = [('VT+FSI_Override', '8.63/VIX_VT'), ('Monthly_VT+FSI', '8.63/VIX_VT')]
dm_test_results = {}

for name_a, name_b in dm_pairs:
    idx_a = strat_names.index(name_a)
    idx_b = strat_names.index(name_b)

    ret_a = calc_strategy_returns(strat_weights[idx_a], ret_0050).dropna()
    ret_b = calc_strategy_returns(strat_weights[idx_b], ret_0050).dropna()

    common = ret_a.index.intersection(ret_b.index)
    d = ret_a.loc[common]**2 - ret_b.loc[common]**2  # MSE loss differential

    # HAC standard errors
    dm_model = OLS(d, np.ones(len(d))).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
    dm_t_val = float(dm_model.tvalues.iloc[0]) if hasattr(dm_model.tvalues, 'iloc') else float(dm_model.tvalues[0])
    dm_p_val = float(dm_model.pvalues.iloc[0]) if hasattr(dm_model.pvalues, 'iloc') else float(dm_model.pvalues[0])
    print(f"  {name_a} vs {name_b}: DM t={dm_t_val:.3f}, p={dm_p_val:.4f}")

    dm_test_results[f"{name_a}_vs_{name_b}"] = {
        'dm_t': round(dm_t_val, 3),
        'dm_p': round(dm_p_val, 4),
    }

strat_results['dm_tests'] = dm_test_results

results['part_c'] = {
    'tx_cost_bps': 10,
    'strategies': strat_results,
}

# ============================================================
# Part D: Cross-OOS Validation (5 non-overlapping 2-year periods)
# ============================================================
print("\n" + "=" * 70)
print("Part D: Cross-OOS Validation")
print("=" * 70)

oos_periods = [
    ('2012-01-01', '2013-12-31'),
    ('2014-01-01', '2015-12-31'),
    ('2016-01-01', '2017-12-31'),
    ('2018-01-01', '2019-12-31'),
    ('2020-01-01', '2021-12-31'),
]

oos_results = {}
vt_wins = 0
override_wins = 0

print(f"\n{'Period':<25} {'BH Sharpe':<12} {'VT Sharpe':<12} {'Override Sharpe':<15} {'Winner':<15}")
print("-" * 80)

for start, end in oos_periods:
    period_mask = (ret_0050.index >= start) & (ret_0050.index <= end)

    if period_mask.sum() < 50:
        continue

    sr_bh = sr_vt = sr_ov = 0.0
    for name, w in zip(strat_names[:3], strat_weights[:3]):
        nr = calc_strategy_returns(w, ret_0050).dropna()
        # Filter to OOS period
        sub_mask = (nr.index >= start) & (nr.index <= end)
        sub = nr[sub_mask]

        if len(sub) < 20:
            continue
        sr = sub.mean() / sub.std() * np.sqrt(252) if sub.std() > 0 else 0

        if name == 'BH_0050':
            sr_bh = sr
        elif name == '8.63/VIX_VT':
            sr_vt = sr
        elif name == 'VT+FSI_Override':
            sr_ov = sr

    period_key = f"{start[:4]}-{end[:4]}"
    winner = 'Override' if sr_ov > sr_vt else 'VT'
    if sr_ov > sr_vt:
        override_wins += 1
    else:
        vt_wins += 1

    print(f"{period_key:<25} {sr_bh:<12.3f} {sr_vt:<12.3f} {sr_ov:<15.3f} {winner:<15}")

    oos_results[period_key] = {
        'bh_sharpe': round(float(sr_bh), 3),
        'vt_sharpe': round(float(sr_vt), 3),
        'override_sharpe': round(float(sr_ov), 3),
        'winner': winner,
    }

print(f"\nOverride wins: {override_wins}/5, VT wins: {vt_wins}/5")

results['part_d'] = {
    'oos_periods': oos_results,
    'override_win_rate': f"{override_wins}/5",
    'vt_win_rate': f"{vt_wins}/5",
}

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 70)
print("Summary")
print("=" * 70)

print(f"""
K759 Results Summary:

Part A — Financial Stress Index (FSI):
  - FSI = mean(Fubon_RV20, Cathay_RV20)
  - Threshold P75 = {threshold_75:.4f}
  - {n_stress_days} stress days ({100*n_stress_days/len(stress_signal):.1f}%)
  - {len(stress_runs)} stress episodes, mean duration {np.mean(stress_runs):.1f}d

Part B — Predictive Power:
  - Simple corr FSI→future TSMC RV: {corr_fsi_future:.4f}
  - Partial corr FSI→future TSMC RV | VIX: {pcorr_fsi:.4f} (t={t_stat_pcorr:.2f}, p={p_val_pcorr:.4f})
  - VIX-only R²: {model_vix.rsquared:.4f}, VIX+FSI R²: {model_both.rsquared:.4f}, ΔR²: {delta_r2:.4f}
  - DM test (VIX vs VIX+FSI): t={dm_t:.3f}, p={dm_p:.4f}
  - ROC AUC: FSI={auc_fsi:.4f}, VIX={auc_vix:.4f}, Combo={auc_combo:.4f}

Part C — Trading Application:
  - VT+FSI Override: {'improves' if strat_results.get('VT+FSI_Override', {}).get('sharpe', 0) > strat_results.get('8.63/VIX_VT', {}).get('sharpe', 0) else 'does NOT improve'} on 8.63/VIX VT

Part D — Cross-OOS:
  - Override wins {override_wins}/5 periods
""")

results['summary'] = {
    'fsi_threshold_p75': round(float(threshold_75), 4),
    'fsi_adds_predictive_power': bool(p_val_pcorr < 0.05),
    'partial_corr_significant': bool(p_val_pcorr < 0.05),
    'dm_test_significant': bool(dm_p < 0.05),
    'auc_improvement': round(float(auc_combo - auc_vix), 4),
    'override_improves_sharpe': bool(strat_results.get('VT+FSI_Override', {}).get('sharpe', 0) > strat_results.get('8.63/VIX_VT', {}).get('sharpe', 0)),
    'override_oos_win_rate': f"{override_wins}/5",
}

# Save results
results['timestamp'] = datetime.now(timezone.utc).isoformat()

output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'k759_financial_early_warning_results.json')
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("K759 complete.")
