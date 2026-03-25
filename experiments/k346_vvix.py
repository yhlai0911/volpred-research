#!/usr/bin/env python3
"""
K346: VVIX (Volatility of Volatility) — Does Vol-of-Vol Predict Anything?

[提出: Claude, 執行: Claude]

Genuinely new direction: ZERO prior experiments on VVIX in knowledge base.

Data: yfinance — ^VVIX, ^VIX, SPY (real data only)
Focus: Does VVIX contain information BEYOND VIX for predicting SPY volatility?

Sections:
1. VVIX characteristics (distribution, ACF, correlation with VIX)
2. Predictive content: partial r(VVIX, future_SPY_RV | VIX)
3. VVIX as regime transition indicator (K278 connection)
4. VVIX-adjusted VT strategy
5. VVIX lead/lag relationship with VIX
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime, timedelta
import warnings
import json
warnings.filterwarnings('ignore')

# ── 1. Data Download ──────────────────────────────────────────────────────

print("=" * 80)
print("K346: VVIX (Volatility of Volatility) — Does Vol-of-Vol Predict Anything?")
print("=" * 80)
print(f"\nExperiment date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("Data source: yfinance (^VVIX, ^VIX, SPY)")

# Download data — VVIX history is shorter than VIX
start_date = "2007-01-01"
end_date = "2026-03-24"

print(f"\nDownloading data from {start_date} to {end_date}...")

vvix_data = yf.download("^VVIX", start=start_date, end=end_date, progress=False)
vix_data = yf.download("^VIX", start=start_date, end=end_date, progress=False)
spy_data = yf.download("SPY", start=start_date, end=end_date, progress=False)

# Handle multi-level columns from yfinance
for df_name, df in [("VVIX", vvix_data), ("VIX", vix_data), ("SPY", spy_data)]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

print(f"VVIX: {len(vvix_data)} days ({vvix_data.index[0].strftime('%Y-%m-%d')} to {vvix_data.index[-1].strftime('%Y-%m-%d')})")
print(f"VIX:  {len(vix_data)} days ({vix_data.index[0].strftime('%Y-%m-%d')} to {vix_data.index[-1].strftime('%Y-%m-%d')})")
print(f"SPY:  {len(spy_data)} days ({spy_data.index[0].strftime('%Y-%m-%d')} to {spy_data.index[-1].strftime('%Y-%m-%d')})")

# Merge on common dates
df = pd.DataFrame({
    'VVIX': vvix_data['Close'],
    'VIX': vix_data['Close'],
    'SPY_Close': spy_data['Close'],
    'SPY_High': spy_data['High'],
    'SPY_Low': spy_data['Low'],
}).dropna()

# Flatten any remaining multi-level index issues
for col in df.columns:
    if hasattr(df[col], 'values') and len(df[col].values.shape) > 1:
        df[col] = df[col].values.flatten()

# Compute returns and realized volatility
df['SPY_ret'] = np.log(df['SPY_Close'] / df['SPY_Close'].shift(1))
df['SPY_ret_sq'] = df['SPY_ret'] ** 2

# Parkinson RV (5-day and 21-day)
df['park_var'] = (np.log(df['SPY_High'] / df['SPY_Low'])) ** 2 / (4 * np.log(2))
df['RV_5d'] = df['park_var'].rolling(5).mean() * 252  # annualized
df['RV_21d'] = df['park_var'].rolling(21).mean() * 252

# Future RV (forward-looking — for predictive tests)
df['fwd_RV_5d'] = df['park_var'].shift(-5).rolling(5).mean() * 252
# Manual forward-looking: use next 5 days
for i in range(len(df)):
    if i + 5 < len(df):
        df.iloc[i, df.columns.get_loc('fwd_RV_5d')] = df['park_var'].iloc[i+1:i+6].mean() * 252

df['fwd_RV_21d'] = np.nan
for i in range(len(df)):
    if i + 21 < len(df):
        df.iloc[i, df.columns.get_loc('fwd_RV_21d')] = df['park_var'].iloc[i+1:i+22].mean() * 252

# VVIX and VIX changes
df['VVIX_chg'] = df['VVIX'].pct_change()
df['VIX_chg'] = df['VIX'].pct_change()
df['VVIX_log'] = np.log(df['VVIX'])
df['VIX_log'] = np.log(df['VIX'])

df = df.dropna(subset=['SPY_ret', 'RV_5d', 'RV_21d', 'fwd_RV_5d', 'fwd_RV_21d'])

print(f"\nMerged dataset: {len(df)} trading days")
print(f"Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# ── 2. VVIX Characteristics ──────────────────────────────────────────────

print("\n" + "=" * 80)
print("SECTION 1: VVIX Characteristics")
print("=" * 80)

print(f"\n{'Statistic':<25} {'VVIX':>12} {'VIX':>12}")
print("-" * 50)
print(f"{'Mean':<25} {df['VVIX'].mean():>12.2f} {df['VIX'].mean():>12.2f}")
print(f"{'Median':<25} {df['VVIX'].median():>12.2f} {df['VIX'].median():>12.2f}")
print(f"{'Std Dev':<25} {df['VVIX'].std():>12.2f} {df['VIX'].std():>12.2f}")
print(f"{'Skewness':<25} {df['VVIX'].skew():>12.3f} {df['VIX'].skew():>12.3f}")
print(f"{'Kurtosis':<25} {df['VVIX'].kurtosis():>12.3f} {df['VIX'].kurtosis():>12.3f}")
print(f"{'Min':<25} {df['VVIX'].min():>12.2f} {df['VIX'].min():>12.2f}")
print(f"{'Max':<25} {df['VVIX'].max():>12.2f} {df['VIX'].max():>12.2f}")
print(f"{'CV (Std/Mean)':<25} {df['VVIX'].std()/df['VVIX'].mean():>12.3f} {df['VIX'].std()/df['VIX'].mean():>12.3f}")

# Percentiles
print(f"\n{'Percentile':<25} {'VVIX':>12} {'VIX':>12}")
print("-" * 50)
for p in [5, 10, 25, 50, 75, 90, 95]:
    print(f"{'P' + str(p):<25} {np.percentile(df['VVIX'], p):>12.2f} {np.percentile(df['VIX'], p):>12.2f}")

# Correlation: VVIX vs VIX
corr_levels = df['VVIX'].corr(df['VIX'])
corr_changes = df['VVIX_chg'].corr(df['VIX_chg'])
corr_logs = df['VVIX_log'].corr(df['VIX_log'])

print(f"\nVVIX-VIX Correlation:")
print(f"  Levels:  r = {corr_levels:.4f}")
print(f"  Log:     r = {corr_logs:.4f}")
print(f"  Changes: r = {corr_changes:.4f}")
print(f"  → {'HIGH redundancy' if abs(corr_levels) > 0.7 else 'MODERATE redundancy' if abs(corr_levels) > 0.4 else 'LOW redundancy — VVIX carries unique info'}")

# ACF structure
print(f"\nAutocorrelation (VVIX level):")
for lag in [1, 5, 10, 21, 63]:
    acf_val = df['VVIX'].autocorr(lag)
    print(f"  Lag {lag:>2}d: {acf_val:.4f}")

print(f"\nAutocorrelation (VVIX daily change):")
for lag in [1, 5, 10, 21]:
    acf_val = df['VVIX_chg'].dropna().autocorr(lag)
    print(f"  Lag {lag:>2}d: {acf_val:.4f}")

# VVIX/VIX ratio
df['VVIX_VIX_ratio'] = df['VVIX'] / df['VIX']
print(f"\nVVIX/VIX Ratio:")
print(f"  Mean:   {df['VVIX_VIX_ratio'].mean():.3f}")
print(f"  Std:    {df['VVIX_VIX_ratio'].std():.3f}")
print(f"  Min:    {df['VVIX_VIX_ratio'].min():.3f}")
print(f"  Max:    {df['VVIX_VIX_ratio'].max():.3f}")

# ── 3. Predictive Content: Partial Correlations ──────────────────────────

print("\n" + "=" * 80)
print("SECTION 2: Does VVIX Predict BEYOND VIX?")
print("=" * 80)

# Key test: partial r(VVIX, future_RV | VIX)
def partial_corr(x, y, z):
    """Partial correlation of x and y, controlling for z."""
    # Residualize x on z
    mask = ~(np.isnan(x) | np.isnan(y) | np.isnan(z) | np.isinf(x) | np.isinf(y) | np.isinf(z))
    x, y, z = x[mask], y[mask], z[mask]

    slope_xz = np.polyfit(z, x, 1)
    resid_x = x - np.polyval(slope_xz, z)

    slope_yz = np.polyfit(z, y, 1)
    resid_y = y - np.polyval(slope_yz, z)

    r, p = stats.pearsonr(resid_x, resid_y)
    n = len(x)
    t_stat = r * np.sqrt((n - 3) / (1 - r**2)) if abs(r) < 1 else np.inf
    return r, p, t_stat, n

print("\n--- Bivariate correlations with future RV ---")
print(f"{'Predictor':<25} {'Target':<15} {'r':>8} {'p-value':>12} {'t-stat':>8}")
print("-" * 70)

for target_name, target_col in [('fwd_RV_5d', 'fwd_RV_5d'), ('fwd_RV_21d', 'fwd_RV_21d')]:
    mask = df[target_col].notna() & df['VVIX'].notna() & df['VIX'].notna()
    subset = df[mask]

    for pred_name, pred_col in [('VVIX', 'VVIX'), ('VIX', 'VIX'), ('VVIX/VIX ratio', 'VVIX_VIX_ratio'), ('log(VVIX)', 'VVIX_log')]:
        r, p = stats.pearsonr(subset[pred_col], subset[target_col])
        n = len(subset)
        t = r * np.sqrt((n - 2) / (1 - r**2))
        print(f"{pred_name:<25} {target_name:<15} {r:>8.4f} {p:>12.2e} {t:>8.2f}")
    print()

print("\n--- KEY TEST: Partial correlations (controlling for VIX) ---")
print(f"{'Predictor':<25} {'Target':<15} {'partial_r':>10} {'p-value':>12} {'t-stat':>8} {'N':>6}")
print("-" * 80)

results_partial = {}
for target_name, target_col in [('fwd_RV_5d', 'fwd_RV_5d'), ('fwd_RV_21d', 'fwd_RV_21d')]:
    mask = df[target_col].notna()
    subset = df[mask]

    for pred_name, pred_col in [('VVIX', 'VVIX'), ('log(VVIX)', 'VVIX_log'), ('VVIX/VIX ratio', 'VVIX_VIX_ratio')]:
        r, p, t, n = partial_corr(
            subset[pred_col].values,
            subset[target_col].values,
            subset['VIX'].values
        )
        harvey = "PASS (>3.0)" if abs(t) > 3.0 else "FAIL (<3.0)"
        print(f"{pred_name:<25} {target_name:<15} {r:>10.4f} {p:>12.2e} {t:>8.2f} {n:>6}  {harvey}")
        results_partial[f"{pred_name}_vs_{target_name}"] = {
            'partial_r': round(r, 4), 'p': p, 't': round(t, 2), 'n': n
        }
    print()

# Also test: does VVIX predict future ABSOLUTE returns (not just RV)?
df['fwd_abs_ret_5d'] = np.nan
for i in range(len(df)):
    if i + 5 < len(df):
        df.iloc[i, df.columns.get_loc('fwd_abs_ret_5d')] = abs(df['SPY_ret'].iloc[i+1:i+6].sum())

print("\n--- VVIX predicting future |return| (5d) ---")
mask = df['fwd_abs_ret_5d'].notna()
subset = df[mask]
r, p, t, n = partial_corr(
    subset['VVIX'].values, subset['fwd_abs_ret_5d'].values, subset['VIX'].values
)
print(f"partial_r(VVIX, |ret_5d| | VIX) = {r:.4f}, t = {t:.2f}, p = {p:.2e}")

# Does VVIX predict DIRECTION of returns?
df['fwd_ret_5d'] = np.nan
for i in range(len(df)):
    if i + 5 < len(df):
        df.iloc[i, df.columns.get_loc('fwd_ret_5d')] = df['SPY_ret'].iloc[i+1:i+6].sum()

print(f"\n--- VVIX predicting future return DIRECTION (5d) ---")
mask = df['fwd_ret_5d'].notna()
subset = df[mask]
r, p, t, n = partial_corr(
    subset['VVIX'].values, subset['fwd_ret_5d'].values, subset['VIX'].values
)
print(f"partial_r(VVIX, ret_5d | VIX) = {r:.4f}, t = {t:.2f}, p = {p:.2e}")
print(f"  → {'HIGH VVIX predicts negative returns' if r < -0.03 else 'HIGH VVIX predicts positive returns' if r > 0.03 else 'No directional prediction'}")

# ── 4. VVIX Quintile Analysis ────────────────────────────────────────────

print("\n" + "=" * 80)
print("SECTION 3: VVIX Quintile Analysis")
print("=" * 80)

# Conditional on VIX level, does VVIX quintile matter?
df['VIX_tercile'] = pd.qcut(df['VIX'], 3, labels=['Low_VIX', 'Mid_VIX', 'High_VIX'])

mask = df['fwd_RV_5d'].notna()
subset = df[mask].copy()
subset['VVIX_quintile'] = pd.qcut(subset['VVIX'], 5, labels=['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high'])

print("\n--- Future 5d RV by VVIX Quintile ---")
print(f"{'VVIX Q':<12} {'Mean RV':>10} {'Median RV':>12} {'Std RV':>10} {'N':>6}")
print("-" * 52)
for q in ['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high']:
    grp = subset[subset['VVIX_quintile'] == q]['fwd_RV_5d']
    print(f"{q:<12} {grp.mean():>10.4f} {grp.median():>12.4f} {grp.std():>10.4f} {len(grp):>6}")

# Q5/Q1 ratio
q5_rv = subset[subset['VVIX_quintile'] == 'Q5_high']['fwd_RV_5d'].mean()
q1_rv = subset[subset['VVIX_quintile'] == 'Q1_low']['fwd_RV_5d'].mean()
print(f"\nQ5/Q1 mean RV ratio: {q5_rv/q1_rv:.2f}x")

# Within each VIX tercile
print("\n--- Future 5d RV by VVIX Quintile WITHIN VIX Terciles ---")
print("(This tests if VVIX adds info beyond VIX)")
print(f"{'VIX Tercile':<12} {'VVIX Q1':>10} {'VVIX Q3':>10} {'VVIX Q5':>10} {'Q5/Q1':>8} {'t-stat':>8}")
print("-" * 60)

for vix_t in ['Low_VIX', 'Mid_VIX', 'High_VIX']:
    sub_vix = subset[subset['VIX_tercile'] == vix_t].copy()
    if len(sub_vix) < 50:
        continue
    sub_vix['local_VVIX_q'] = pd.qcut(sub_vix['VVIX'], 5, labels=['Q1', 'Q2', 'Q3', 'Q4', 'Q5'], duplicates='drop')

    q1_vals = sub_vix[sub_vix['local_VVIX_q'] == 'Q1']['fwd_RV_5d']
    q3_vals = sub_vix[sub_vix['local_VVIX_q'] == 'Q3']['fwd_RV_5d']
    q5_vals = sub_vix[sub_vix['local_VVIX_q'] == 'Q5']['fwd_RV_5d']

    if len(q1_vals) > 5 and len(q5_vals) > 5:
        t_stat, p_val = stats.ttest_ind(q5_vals, q1_vals, equal_var=False)
        ratio = q5_vals.mean() / q1_vals.mean() if q1_vals.mean() > 0 else np.nan
        print(f"{vix_t:<12} {q1_vals.mean():>10.4f} {q3_vals.mean():>10.4f} {q5_vals.mean():>10.4f} {ratio:>8.2f} {t_stat:>8.2f}")

# ── 5. VVIX as Regime Transition Indicator ───────────────────────────────

print("\n" + "=" * 80)
print("SECTION 4: VVIX as Regime Transition Indicator")
print("=" * 80)

# Define VIX regimes (matching K278)
def vix_regime(v):
    if v < 15: return 'Low'
    elif v < 20: return 'Normal'
    elif v < 30: return 'Elevated'
    else: return 'High'

df['VIX_regime'] = df['VIX'].apply(vix_regime)

# Detect regime transitions
df['regime_shift'] = (df['VIX_regime'] != df['VIX_regime'].shift(1)).astype(int)

# Future regime shift (next 5 days)
df['fwd_regime_shift_5d'] = df['regime_shift'].shift(-1).rolling(5).max()
# Manual forward-looking
df['fwd_regime_shift_5d'] = 0
for i in range(len(df)):
    if i + 5 < len(df):
        df.iloc[i, df.columns.get_loc('fwd_regime_shift_5d')] = df['regime_shift'].iloc[i+1:i+6].max()

# Does high VVIX predict regime transitions?
mask = df['fwd_regime_shift_5d'].notna()
subset = df[mask].copy()
subset['VVIX_quintile'] = pd.qcut(subset['VVIX'], 5, labels=['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high'])

print("\n--- Regime Transition Probability by VVIX Quintile ---")
print(f"{'VVIX Q':<12} {'Transition%':>12} {'N':>6} {'N_transitions':>15}")
print("-" * 48)
for q in ['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high']:
    grp = subset[subset['VVIX_quintile'] == q]
    trans_rate = grp['fwd_regime_shift_5d'].mean() * 100
    n_trans = grp['fwd_regime_shift_5d'].sum()
    print(f"{q:<12} {trans_rate:>12.1f}% {len(grp):>6} {n_trans:>15.0f}")

q5_trans = subset[subset['VVIX_quintile'] == 'Q5_high']['fwd_regime_shift_5d'].mean()
q1_trans = subset[subset['VVIX_quintile'] == 'Q1_low']['fwd_regime_shift_5d'].mean()
print(f"\nQ5 vs Q1 transition rate ratio: {q5_trans/q1_trans:.2f}x" if q1_trans > 0 else "\nQ1 transition rate is 0")

# Chi-squared test
from scipy.stats import chi2_contingency
contingency = pd.crosstab(subset['VVIX_quintile'], subset['fwd_regime_shift_5d'] > 0)
chi2, p_chi, dof, expected = chi2_contingency(contingency)
print(f"Chi-squared test: chi2 = {chi2:.2f}, p = {p_chi:.2e}, dof = {dof}")

# Does VVIX predict DIRECTION of regime transition?
# (Escalation vs de-escalation)
regime_order = {'Low': 0, 'Normal': 1, 'Elevated': 2, 'High': 3}
df['regime_num'] = df['VIX_regime'].map(regime_order)
df['fwd_regime_direction'] = np.nan
for i in range(len(df)):
    if i + 5 < len(df):
        future_regime = df['regime_num'].iloc[i+1:i+6].mean()
        df.iloc[i, df.columns.get_loc('fwd_regime_direction')] = future_regime - df['regime_num'].iloc[i]

print(f"\n--- VVIX vs Direction of Regime Movement ---")
mask = df['fwd_regime_direction'].notna()
subset = df[mask].copy()
subset['VVIX_quintile'] = pd.qcut(subset['VVIX'], 5, labels=['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high'])

print(f"{'VVIX Q':<12} {'Mean Direction':>15} {'t-stat':>8}")
print("-" * 38)
for q in ['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high']:
    grp = subset[subset['VVIX_quintile'] == q]['fwd_regime_direction']
    t, p = stats.ttest_1samp(grp, 0)
    print(f"{q:<12} {grp.mean():>15.4f} {t:>8.2f}")

# ── 6. VVIX Lead/Lag with VIX ────────────────────────────────────────────

print("\n" + "=" * 80)
print("SECTION 5: VVIX Lead/Lag Relationship with VIX")
print("=" * 80)

print("\n--- Cross-correlation: VVIX changes → VIX changes ---")
print("(Positive lag = VVIX leads VIX)")
print(f"{'Lag (days)':<15} {'Cross-corr':>12} {'Interpretation':>30}")
print("-" * 60)

for lag in [-5, -3, -1, 0, 1, 3, 5, 10]:
    if lag >= 0:
        cc = df['VVIX_chg'].corr(df['VIX_chg'].shift(lag))
        interp = f"VVIX leads VIX by {lag}d" if lag > 0 else "contemporaneous"
    else:
        cc = df['VVIX_chg'].corr(df['VIX_chg'].shift(lag))
        interp = f"VIX leads VVIX by {-lag}d"
    print(f"{lag:<15} {cc:>12.4f} {interp:>30}")

# Granger-type test: does VVIX_chg predict VIX_chg?
print("\n--- Granger-type predictive regression ---")
print("VIX_chg(t+h) = a + b1*VIX_chg(t) + b2*VVIX_chg(t) + e")

for horizon in [1, 5, 10]:
    # Compute forward VIX change
    fwd_vix_chg = df['VIX'].pct_change(horizon).shift(-horizon)

    mask = fwd_vix_chg.notna() & df['VVIX_chg'].notna() & df['VIX_chg'].notna()
    y = fwd_vix_chg[mask].values
    X = np.column_stack([
        np.ones(mask.sum()),
        df['VIX_chg'][mask].values,
        df['VVIX_chg'][mask].values
    ])

    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        resid = y - X @ beta
        se = np.sqrt(np.diag(np.linalg.inv(X.T @ X) * np.var(resid)))
        t_vvix = beta[2] / se[2]
        print(f"  h={horizon}d: VVIX_chg coeff = {beta[2]:.4f}, t = {t_vvix:.2f}, {'*' if abs(t_vvix) > 2 else ''}")
    except Exception as e:
        print(f"  h={horizon}d: regression failed ({e})")

# Does VVIX spike BEFORE VIX spikes?
print("\n--- VVIX spikes as early warning for VIX spikes ---")
# Define spikes as >2 std moves
vvix_spike = df['VVIX_chg'] > df['VVIX_chg'].mean() + 2 * df['VVIX_chg'].std()
vix_spike = df['VIX_chg'] > df['VIX_chg'].mean() + 2 * df['VIX_chg'].std()

print(f"VVIX spikes (>2 std): {vvix_spike.sum()} days ({vvix_spike.mean()*100:.1f}%)")
print(f"VIX spikes (>2 std):  {vix_spike.sum()} days ({vix_spike.mean()*100:.1f}%)")

# After VVIX spike, what happens to VIX?
print(f"\nVIX change after VVIX spike:")
for h in [1, 3, 5, 10]:
    fwd_vix = df['VIX'].pct_change(h).shift(-h)
    mask = vvix_spike & fwd_vix.notna()
    if mask.sum() > 5:
        vals = fwd_vix[mask]
        t, p = stats.ttest_1samp(vals, 0)
        print(f"  {h}d ahead: mean VIX chg = {vals.mean()*100:.2f}%, t = {t:.2f}, N = {mask.sum()}")

# ── 7. VVIX-Adjusted VT Strategy ────────────────────────────────────────

print("\n" + "=" * 80)
print("SECTION 6: VVIX-Adjusted VT Strategy (Backtest)")
print("=" * 80)

# Standard VT: w = sigma_target / sigma_realized
# VVIX-adjusted VT: when VVIX is high, reduce position further (more defensive)

# Parameters
sigma_target = 0.10  # 10% annualized target
lookback = 63  # 3-month lookback for sigma estimation

df['sigma_est'] = df['SPY_ret'].rolling(lookback).std() * np.sqrt(252)

# VVIX percentile (rolling 252-day)
df['VVIX_pctl'] = df['VVIX'].rolling(252).rank(pct=True)

# Strategy variants
strategies = {}

# 1. Standard VT (no VVIX)
df['w_standard'] = sigma_target / df['sigma_est']
df['w_standard'] = df['w_standard'].clip(0, 1.5)  # cap leverage

# 2. VVIX-adjusted VT: reduce weight when VVIX is high
# Adjustment: multiply by (1 - VVIX_pctl * adjustment_strength)
for adj_strength in [0.0, 0.3, 0.5, 0.7]:
    col = f'w_vvix_{int(adj_strength*100)}'
    df[col] = df['w_standard'] * (1 - df['VVIX_pctl'] * adj_strength)
    df[col] = df[col].clip(0, 1.5)

# 3. VVIX regime-based VT
df['w_vvix_regime'] = df['w_standard'].copy()
vvix_high = df['VVIX_pctl'] > 0.8
vvix_low = df['VVIX_pctl'] < 0.2
df.loc[vvix_high, 'w_vvix_regime'] = df.loc[vvix_high, 'w_standard'] * 0.5
df.loc[vvix_low, 'w_vvix_regime'] = df.loc[vvix_low, 'w_standard'] * 1.2
df['w_vvix_regime'] = df['w_vvix_regime'].clip(0, 1.5)

# Compute returns (using lag-1 weight — no lookahead)
# Out-of-sample: use last 5 years
oos_start = df.index[-1] - pd.DateOffset(years=5)
oos_mask = df.index >= oos_start

# Compute strategy returns
ret_cols = {}
weight_cols = ['w_standard', 'w_vvix_0', 'w_vvix_30', 'w_vvix_50', 'w_vvix_70', 'w_vvix_regime']
labels = ['Standard VT', 'VVIX adj 0%', 'VVIX adj 30%', 'VVIX adj 50%', 'VVIX adj 70%', 'VVIX regime']

for wc, label in zip(weight_cols, labels):
    df[f'ret_{wc}'] = df[wc].shift(1) * df['SPY_ret']
    ret_cols[label] = f'ret_{wc}'

# Buy-and-hold
df['ret_bnh'] = df['SPY_ret']
ret_cols['Buy & Hold SPY'] = 'ret_bnh'

print(f"\nOut-of-sample period: {df[oos_mask].index[0].strftime('%Y-%m-%d')} to {df[oos_mask].index[-1].strftime('%Y-%m-%d')}")
print(f"OOS days: {oos_mask.sum()}")

print(f"\n{'Strategy':<20} {'Ann Ret':>10} {'Ann Vol':>10} {'Sharpe':>8} {'Max DD':>10} {'Calmar':>8} {'Mean w':>8}")
print("-" * 78)

strategy_results = {}
for label, ret_c in ret_cols.items():
    oos_ret = df.loc[oos_mask, ret_c].dropna()
    if len(oos_ret) < 100:
        continue
    ann_ret = oos_ret.mean() * 252
    ann_vol = oos_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + oos_ret).cumprod()
    drawdown = cum / cum.cummax() - 1
    max_dd = drawdown.min()
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    # Mean weight
    wc = ret_c.replace('ret_', '')
    if wc in df.columns:
        mean_w = df.loc[oos_mask, wc].mean()
    else:
        mean_w = 1.0

    print(f"{label:<20} {ann_ret:>10.4f} {ann_vol:>10.4f} {sharpe:>8.3f} {max_dd:>10.4f} {calmar:>8.3f} {mean_w:>8.3f}")

    strategy_results[label] = {
        'ann_ret': round(ann_ret, 4),
        'ann_vol': round(ann_vol, 4),
        'sharpe': round(sharpe, 3),
        'max_dd': round(max_dd, 4),
        'calmar': round(calmar, 3)
    }

# Statistical test: is VVIX-adjusted VT better than Standard VT?
print("\n--- Diebold-Mariano type test: VVIX-adj vs Standard VT ---")
for adj_label, adj_col in [('VVIX adj 30%', 'ret_w_vvix_30'), ('VVIX adj 50%', 'ret_w_vvix_50'), ('VVIX regime', 'ret_w_vvix_regime')]:
    oos_std = df.loc[oos_mask, 'ret_w_standard'].dropna()
    oos_adj = df.loc[oos_mask, adj_col].dropna()

    # Align
    common_idx = oos_std.index.intersection(oos_adj.index)
    oos_std = oos_std.loc[common_idx]
    oos_adj = oos_adj.loc[common_idx]

    # Difference in squared returns (volatility targeting loss)
    loss_std = (oos_std - sigma_target / np.sqrt(252)) ** 2
    loss_adj = (oos_adj - sigma_target / np.sqrt(252)) ** 2
    d = loss_std - loss_adj  # positive = std is worse

    # Newey-West HAC t-test (simple lag-5)
    mean_d = d.mean()
    var_d = d.var()
    for lag in range(1, 6):
        cov_lag = d.iloc[lag:].values @ d.iloc[:-lag].values / len(d)
        var_d += 2 * (1 - lag/6) * cov_lag
    se_d = np.sqrt(var_d / len(d))
    t_dm = mean_d / se_d if se_d > 0 else 0

    # Also compare Sharpe
    sharpe_std = oos_std.mean() / oos_std.std() * np.sqrt(252) if oos_std.std() > 0 else 0
    sharpe_adj = oos_adj.mean() / oos_adj.std() * np.sqrt(252) if oos_adj.std() > 0 else 0

    print(f"  {adj_label} vs Standard: DM t = {t_dm:.2f}, Sharpe diff = {sharpe_adj - sharpe_std:+.3f}")

# ── 8. VVIX in Tail Events ──────────────────────────────────────────────

print("\n" + "=" * 80)
print("SECTION 7: VVIX Behavior in Tail Events")
print("=" * 80)

# Does VVIX predict extreme SPY moves?
df['fwd_ret_1d'] = df['SPY_ret'].shift(-1)

print("\n--- VVIX quintile vs probability of extreme moves (next day) ---")
mask = df['fwd_ret_1d'].notna()
subset = df[mask].copy()
subset['VVIX_quintile'] = pd.qcut(subset['VVIX'], 5, labels=['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high'])

# Define extreme as |return| > 2%
extreme_threshold = 0.02
print(f"Extreme move: |daily return| > {extreme_threshold*100:.0f}%")
print(f"\n{'VVIX Q':<12} {'P(extreme)':>12} {'P(crash<-2%)':>14} {'P(rally>2%)':>13} {'Mean |ret|':>12}")
print("-" * 66)

for q in ['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high']:
    grp = subset[subset['VVIX_quintile'] == q]
    fwd = grp['fwd_ret_1d']
    p_extreme = (fwd.abs() > extreme_threshold).mean() * 100
    p_crash = (fwd < -extreme_threshold).mean() * 100
    p_rally = (fwd > extreme_threshold).mean() * 100
    mean_abs = fwd.abs().mean() * 100
    print(f"{q:<12} {p_extreme:>12.1f}% {p_crash:>14.1f}% {p_rally:>13.1f}% {mean_abs:>12.3f}%")

# ── 9. Rolling Partial Correlation (Stability Check) ─────────────────────

print("\n" + "=" * 80)
print("SECTION 8: Stability of VVIX Predictive Power (Rolling Window)")
print("=" * 80)

window = 504  # 2 years
partial_r_series = []

for i in range(window, len(df) - 5):
    w = df.iloc[i-window:i]
    if w['fwd_RV_5d'].notna().sum() < window * 0.8:
        continue
    mask_w = w['fwd_RV_5d'].notna()
    w_clean = w[mask_w]
    if len(w_clean) < 100:
        continue

    try:
        r, p, t, n = partial_corr(
            w_clean['VVIX'].values,
            w_clean['fwd_RV_5d'].values,
            w_clean['VIX'].values
        )
        partial_r_series.append({
            'date': df.index[i],
            'partial_r': r,
            't_stat': t
        })
    except:
        pass

pr_df = pd.DataFrame(partial_r_series)
if len(pr_df) > 0:
    print(f"\nRolling partial r(VVIX, fwd_RV_5d | VIX), window = {window}d")
    print(f"{'Statistic':<30} {'Value':>10}")
    print("-" * 42)
    print(f"{'Mean partial r':<30} {pr_df['partial_r'].mean():>10.4f}")
    print(f"{'Std partial r':<30} {pr_df['partial_r'].std():>10.4f}")
    print(f"{'% positive':<30} {(pr_df['partial_r'] > 0).mean()*100:>10.1f}%")
    print(f"{'% significant (|t|>2)':<30} {(pr_df['t_stat'].abs() > 2).mean()*100:>10.1f}%")
    print(f"{'% Harvey pass (|t|>3)':<30} {(pr_df['t_stat'].abs() > 3).mean()*100:>10.1f}%")

    # By era
    print(f"\n{'Era':<30} {'Mean partial r':>15} {'% sig':>8}")
    print("-" * 55)
    for era_name, era_start, era_end in [
        ('2012-2015 (low vol)', '2012-01-01', '2015-12-31'),
        ('2016-2019 (mixed)', '2016-01-01', '2019-12-31'),
        ('2020 (COVID)', '2020-01-01', '2020-12-31'),
        ('2021-2023 (post-COVID)', '2021-01-01', '2023-12-31'),
        ('2024-2026 (recent)', '2024-01-01', '2026-12-31'),
    ]:
        era_mask = (pr_df['date'] >= era_start) & (pr_df['date'] <= era_end)
        if era_mask.sum() > 0:
            era_data = pr_df[era_mask]
            print(f"{era_name:<30} {era_data['partial_r'].mean():>15.4f} {(era_data['t_stat'].abs() > 2).mean()*100:>8.1f}%")

# ── 10. Summary ──────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("SUMMARY: K346 VVIX Results")
print("=" * 80)

print(f"""
Data: {len(df)} trading days, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}
Source: yfinance (^VVIX, ^VIX, SPY)

KEY FINDINGS:

1. VVIX Characteristics:
   - Mean: {df['VVIX'].mean():.1f}, Std: {df['VVIX'].std():.1f}
   - VVIX-VIX correlation (levels): {corr_levels:.3f}
   - VVIX-VIX correlation (changes): {corr_changes:.3f}
   → {'VVIX is largely redundant with VIX' if corr_levels > 0.7 else 'VVIX carries unique information beyond VIX'}

2. Predictive Content (partial r controlling for VIX):
""")

for key, val in results_partial.items():
    pred, target = key.split('_vs_')
    harvey = "PASS Harvey" if abs(val['t']) > 3.0 else "FAIL Harvey"
    print(f"   {pred} → {target}: partial_r = {val['partial_r']:.4f}, t = {val['t']:.2f} ({harvey})")

print(f"""
3. Regime Transition Prediction:
   - Q5(high VVIX)/Q1(low VVIX) transition rate: {q5_trans/q1_trans:.2f}x
   - Chi-squared test: p = {p_chi:.2e}
   → {'VVIX significantly predicts regime transitions' if p_chi < 0.01 else 'Weak/no regime transition prediction'}

4. VVIX-Adjusted VT Strategy:
""")
for label in ['Standard VT', 'VVIX adj 50%', 'VVIX regime']:
    if label in strategy_results:
        sr = strategy_results[label]
        print(f"   {label}: Sharpe = {sr['sharpe']:.3f}, MaxDD = {sr['max_dd']:.4f}")

if len(pr_df) > 0:
    print(f"""
5. Stability:
   - Mean rolling partial r: {pr_df['partial_r'].mean():.4f}
   - % significant windows: {(pr_df['t_stat'].abs() > 2).mean()*100:.1f}%
   - {'Stable' if (pr_df['t_stat'].abs() > 2).mean() > 0.3 else 'Unstable'} predictive power
""")

# Compute overall assessment
key_partial_r = results_partial.get('VVIX_vs_fwd_RV_5d', {}).get('partial_r', 0)
key_t = results_partial.get('VVIX_vs_fwd_RV_5d', {}).get('t', 0)

if abs(key_t) > 3.0:
    verdict = "VVIX has SIGNIFICANT incremental predictive power beyond VIX (Harvey threshold passed)"
elif abs(key_t) > 2.0:
    verdict = "VVIX has MARGINAL incremental predictive power (t>2 but fails Harvey t>3 threshold)"
elif abs(key_t) > 1.0:
    verdict = "VVIX has WEAK and unreliable incremental predictive power"
else:
    verdict = "VVIX does NOT add meaningful predictive power beyond VIX"

print(f"VERDICT: {verdict}")
print(f"(Key test: partial_r = {key_partial_r:.4f}, t = {key_t:.2f})")

# Save results
results = {
    'experiment': 'K346',
    'title': 'VVIX (Volatility of Volatility) — Does Vol-of-Vol Predict Anything?',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (^VVIX, ^VIX, SPY)',
    'sample_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'sample_size': len(df),
    'vvix_stats': {
        'mean': round(df['VVIX'].mean(), 2),
        'std': round(df['VVIX'].std(), 2),
        'vvix_vix_corr_levels': round(corr_levels, 4),
        'vvix_vix_corr_changes': round(corr_changes, 4),
    },
    'partial_correlations': results_partial,
    'regime_transition': {
        'q5_q1_ratio': round(q5_trans/q1_trans, 2) if q1_trans > 0 else None,
        'chi2_p_value': p_chi,
    },
    'strategy_results': strategy_results,
    'stability': {
        'mean_rolling_partial_r': round(pr_df['partial_r'].mean(), 4) if len(pr_df) > 0 else None,
        'pct_significant': round((pr_df['t_stat'].abs() > 2).mean() * 100, 1) if len(pr_df) > 0 else None,
    },
    'verdict': verdict,
    'key_partial_r': key_partial_r,
    'key_t_stat': key_t,
    'limitations': [
        'VVIX history shorter than VIX (starts ~2007)',
        'Single asset (SPY) — cross-asset validation needed',
        'VT strategy uses simple vol scaling, not GARCH',
        'No transaction cost in backtest',
        'Overlapping windows in RV calculation',
    ]
}

results_path = 'experiments/k346_vvix_results.json'
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {results_path}")

print("\n" + "=" * 80)
print("K346 COMPLETE")
print("=" * 80)
