"""
K964: Earnings Season Volatility Patterns — SPY 20yr Analysis
=============================================================
Research question: Does SPY exhibit systematically different volatility
during earnings seasons (the ~5-week windows when most S&P 500 companies
report quarterly results)?

Data source: yfinance (SPY, ^VIX), 2006-01-01 to 2026-04-07
Method: Descriptive statistics, Welch t-test, Mann-Whitney U, OLS regression
Seed: 42 (for any random operations)

References:
- Patell & Wolfson (1984): Earnings announcements and intraday volatility
- Savor & Wilson (2016): Earnings announcements and systematic risk
- Dubinsky et al. (2019): Aggregate earnings surprises and market volatility
"""

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from scipy import stats
import statsmodels.api as sm
import json
import os
from datetime import datetime

np.random.seed(42)

# ============================================================
# Step 1: Data Preparation
# ============================================================
print("=" * 60)
print("K964: Earnings Season Volatility Patterns")
print("=" * 60)

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Download data
print("\n[1] Downloading SPY and VIX data (2006-2026)...")
spy = yf.download('SPY', start='2006-01-01', end='2026-04-07', progress=False)
vix = yf.download('^VIX', start='2006-01-01', end='2026-04-07', progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

print(f"  SPY: {len(spy)} days, {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
print(f"  VIX: {len(vix)} days, {vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')}")

# Calculate returns and volatility measures
df = pd.DataFrame(index=spy.index)
df['spy_close'] = spy['Close']
df['spy_return'] = spy['Close'].pct_change()
df['abs_return'] = df['spy_return'].abs()
df['sq_return'] = df['spy_return'] ** 2
df['rv5'] = df['sq_return'].rolling(5).mean() * 252  # annualized 5-day RV
df['rv20'] = df['sq_return'].rolling(20).mean() * 252  # annualized 20-day RV
df['vix'] = vix['Close'].reindex(df.index)
df = df.dropna()

print(f"  Combined dataset: {len(df)} days after dropping NaN")

# Define earnings seasons
def is_earnings_season(date):
    """
    Approximate earnings season windows (when most S&P 500 companies report):
    Q4 earnings: Jan 10 - Feb 15
    Q1 earnings: Apr 10 - May 15
    Q2 earnings: Jul 10 - Aug 15
    Q3 earnings: Oct 10 - Nov 15
    """
    m, d = date.month, date.day
    if m == 1 and d >= 10: return 'Q4_earnings'
    if m == 2 and d <= 15: return 'Q4_earnings'
    if m == 4 and d >= 10: return 'Q1_earnings'
    if m == 5 and d <= 15: return 'Q1_earnings'
    if m == 7 and d >= 10: return 'Q2_earnings'
    if m == 8 and d <= 15: return 'Q2_earnings'
    if m == 10 and d >= 10: return 'Q3_earnings'
    if m == 11 and d <= 15: return 'Q3_earnings'
    return 'non_earnings'

df['earnings_period'] = df.index.map(is_earnings_season)
df['is_earnings'] = (df['earnings_period'] != 'non_earnings').astype(int)

n_earnings = df['is_earnings'].sum()
n_non = len(df) - n_earnings
print(f"  Earnings season days: {n_earnings} ({100*n_earnings/len(df):.1f}%)")
print(f"  Non-earnings days: {n_non} ({100*n_non/len(df):.1f}%)")

# ============================================================
# Step 2: Descriptive Statistics
# ============================================================
print("\n[2] Descriptive Statistics")
print("-" * 60)

earn_mask = df['is_earnings'] == 1
non_mask = df['is_earnings'] == 0

metrics = ['abs_return', 'sq_return', 'rv5', 'rv20', 'vix']
metric_labels = ['|Return|', 'Return^2', '5d RV (ann)', '20d RV (ann)', 'VIX']

desc_stats = {}
for m, label in zip(metrics, metric_labels):
    earn_vals = df.loc[earn_mask, m]
    non_vals = df.loc[non_mask, m]
    desc_stats[label] = {
        'earnings_mean': float(earn_vals.mean()),
        'earnings_median': float(earn_vals.median()),
        'earnings_std': float(earn_vals.std()),
        'non_earnings_mean': float(non_vals.mean()),
        'non_earnings_median': float(non_vals.median()),
        'non_earnings_std': float(non_vals.std()),
        'ratio': float(earn_vals.mean() / non_vals.mean()),
    }
    print(f"  {label:16s}: Earnings={earn_vals.mean():.6f}  Non={non_vals.mean():.6f}  Ratio={earn_vals.mean()/non_vals.mean():.3f}")

# Monthly average vol
monthly_vol = df.groupby(df.index.month)['abs_return'].mean()
print("\n  Monthly avg |return|:")
month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
for i, (m, v) in enumerate(monthly_vol.items()):
    print(f"    {month_names[i]}: {v:.5f}")

# Per-quarter earnings stats
print("\n  Per-quarter earnings stats:")
quarter_stats = {}
for q in ['Q4_earnings', 'Q1_earnings', 'Q2_earnings', 'Q3_earnings']:
    q_mask = df['earnings_period'] == q
    q_vals = df.loc[q_mask, 'abs_return']
    quarter_stats[q] = {
        'n': int(q_mask.sum()),
        'mean_abs_return': float(q_vals.mean()),
        'mean_rv20': float(df.loc[q_mask, 'rv20'].mean()),
        'mean_vix': float(df.loc[q_mask, 'vix'].mean()),
    }
    print(f"    {q}: N={q_mask.sum()}, |ret|={q_vals.mean():.5f}, rv20={df.loc[q_mask,'rv20'].mean():.4f}, VIX={df.loc[q_mask,'vix'].mean():.1f}")

# ============================================================
# Step 3: Statistical Tests
# ============================================================
print("\n[3] Statistical Tests")
print("-" * 60)

test_results = {}

# 3a: Welch t-test on |return|
earn_abs = df.loc[earn_mask, 'abs_return']
non_abs = df.loc[non_mask, 'abs_return']
t_stat, p_val = stats.ttest_ind(earn_abs, non_abs, equal_var=False)
test_results['welch_t_abs_return'] = {'t': float(t_stat), 'p': float(p_val), 'significant_3': bool(abs(t_stat) > 3.0)}
print(f"  Welch t-test (|return|): t={t_stat:.3f}, p={p_val:.4f}, |t|>3: {abs(t_stat)>3.0}")

# 3b: Welch t-test on rv20
earn_rv = df.loc[earn_mask, 'rv20']
non_rv = df.loc[non_mask, 'rv20']
t_stat2, p_val2 = stats.ttest_ind(earn_rv, non_rv, equal_var=False)
test_results['welch_t_rv20'] = {'t': float(t_stat2), 'p': float(p_val2), 'significant_3': bool(abs(t_stat2) > 3.0)}
print(f"  Welch t-test (RV20): t={t_stat2:.3f}, p={p_val2:.4f}, |t|>3: {abs(t_stat2)>3.0}")

# 3c: Welch t-test on VIX
earn_vix = df.loc[earn_mask, 'vix']
non_vix = df.loc[non_mask, 'vix']
t_stat3, p_val3 = stats.ttest_ind(earn_vix, non_vix, equal_var=False)
test_results['welch_t_vix'] = {'t': float(t_stat3), 'p': float(p_val3), 'significant_3': bool(abs(t_stat3) > 3.0)}
print(f"  Welch t-test (VIX): t={t_stat3:.3f}, p={p_val3:.4f}, |t|>3: {abs(t_stat3)>3.0}")

# 3d: Mann-Whitney U test (non-parametric)
u_stat, u_pval = stats.mannwhitneyu(earn_abs, non_abs, alternative='two-sided')
test_results['mannwhitney_abs_return'] = {'U': float(u_stat), 'p': float(u_pval)}
print(f"  Mann-Whitney U (|return|): U={u_stat:.0f}, p={u_pval:.4f}")

u_stat2, u_pval2 = stats.mannwhitneyu(earn_rv, non_rv, alternative='two-sided')
test_results['mannwhitney_rv20'] = {'U': float(u_stat2), 'p': float(u_pval2)}
print(f"  Mann-Whitney U (RV20): U={u_stat2:.0f}, p={u_pval2:.4f}")

# 3e: OLS Regression: RV_t = alpha + beta*EarningsDummy + gamma*VIX_{t-1} + epsilon
print("\n  OLS Regression: rv20 = a + b*earnings_dummy + g*VIX_lag1")
df['vix_lag1'] = df['vix'].shift(1)
reg_df = df.dropna(subset=['rv20', 'is_earnings', 'vix_lag1'])

X = sm.add_constant(reg_df[['is_earnings', 'vix_lag1']])
y = reg_df['rv20']
model = sm.OLS(y, X).fit(cov_type='HC1')  # heteroskedasticity-robust

print(model.summary().tables[1])

reg_results = {
    'const': {'coef': float(model.params['const']), 't': float(model.tvalues['const']), 'p': float(model.pvalues['const'])},
    'is_earnings': {'coef': float(model.params['is_earnings']), 't': float(model.tvalues['is_earnings']), 'p': float(model.pvalues['is_earnings'])},
    'vix_lag1': {'coef': float(model.params['vix_lag1']), 't': float(model.tvalues['vix_lag1']), 'p': float(model.pvalues['vix_lag1'])},
    'r_squared': float(model.rsquared),
    'r_squared_adj': float(model.rsquared_adj),
    'n_obs': int(model.nobs),
}
test_results['ols_regression'] = reg_results

# Per-quarter regression
print("\n  Per-quarter OLS (each quarter dummy separately):")
quarter_reg = {}
for q in ['Q4_earnings', 'Q1_earnings', 'Q2_earnings', 'Q3_earnings']:
    reg_df[f'is_{q}'] = (reg_df['earnings_period'] == q).astype(int)

X_q = sm.add_constant(reg_df[['is_Q4_earnings', 'is_Q1_earnings', 'is_Q2_earnings', 'is_Q3_earnings', 'vix_lag1']])
y_q = reg_df['rv20']
model_q = sm.OLS(y_q, X_q).fit(cov_type='HC1')
print(model_q.summary().tables[1])

for q in ['is_Q4_earnings', 'is_Q1_earnings', 'is_Q2_earnings', 'is_Q3_earnings']:
    quarter_reg[q] = {
        'coef': float(model_q.params[q]),
        't': float(model_q.tvalues[q]),
        'p': float(model_q.pvalues[q]),
    }
test_results['per_quarter_regression'] = quarter_reg

# ============================================================
# Step 4: Conditional Analysis
# ============================================================
print("\n[4] Conditional Analysis")
print("-" * 60)

# 4a: High vs Low VIX
conditional_results = {}
for vix_regime, vix_label in [(df['vix'] > 20, 'high_vix'), (df['vix'] <= 20, 'low_vix')]:
    sub = df[vix_regime]
    e = sub[sub['is_earnings'] == 1]['abs_return']
    n = sub[sub['is_earnings'] == 0]['abs_return']
    if len(e) > 30 and len(n) > 30:
        t, p = stats.ttest_ind(e, n, equal_var=False)
        conditional_results[vix_label] = {
            'n_earnings': int(len(e)),
            'n_non': int(len(n)),
            'mean_earnings': float(e.mean()),
            'mean_non': float(n.mean()),
            'ratio': float(e.mean() / n.mean()),
            't': float(t),
            'p': float(p),
        }
        print(f"  {vix_label}: earn={e.mean():.5f} vs non={n.mean():.5f} (ratio={e.mean()/n.mean():.3f}, t={t:.3f}, p={p:.4f})")

# 4b: Rolling 5-year window stability
print("\n  Rolling 5-year earnings effect:")
rolling_effects = []
years = sorted(df.index.year.unique())
for start_yr in range(years[0], years[-1] - 3):
    end_yr = start_yr + 5
    mask_yr = (df.index.year >= start_yr) & (df.index.year < end_yr)
    sub = df[mask_yr]
    e = sub[sub['is_earnings'] == 1]['abs_return']
    n = sub[sub['is_earnings'] == 0]['abs_return']
    if len(e) > 50 and len(n) > 50:
        ratio = float(e.mean() / n.mean())
        t, p = stats.ttest_ind(e, n, equal_var=False)
        rolling_effects.append({
            'window': f"{start_yr}-{end_yr}",
            'ratio': ratio,
            't': float(t),
            'p': float(p),
            'n_earnings': int(len(e)),
        })
        sig = '*' if abs(t) > 1.96 else ''
        print(f"    {start_yr}-{end_yr}: ratio={ratio:.3f}, t={t:.2f} {sig}")

# ============================================================
# Step 5: Visualizations
# ============================================================
print("\n[5] Creating visualizations...")

# Plot 1: Monthly average volatility bar chart
fig, ax = plt.subplots(figsize=(10, 6))
colors = []
# Color earnings months differently
earnings_months = {1, 2, 4, 5, 7, 8, 10, 11}  # months that overlap with earnings seasons
for m in range(1, 13):
    colors.append('#d35400' if m in earnings_months else '#2980b9')

bars = ax.bar(range(1, 13), monthly_vol.values, color=colors, edgecolor='white', linewidth=0.5)
ax.set_xticks(range(1, 13))
ax.set_xticklabels(month_names)
ax.set_ylabel('Average |Daily Return|', fontsize=12)
ax.set_title('SPY Monthly Average Absolute Return (2006-2026)\nOrange = Months Overlapping Earnings Season', fontsize=13)
ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=2))
ax.grid(axis='y', alpha=0.3)
ax.axhline(y=df['abs_return'].mean(), color='gray', linestyle='--', alpha=0.5, label=f"Overall mean: {df['abs_return'].mean():.4f}")
ax.legend()
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k964_monthly_vol.png'), dpi=150)
plt.close()
print("  Saved k964_monthly_vol.png")

# Plot 2: Earnings vs Non-Earnings box plot
fig, axes = plt.subplots(1, 3, figsize=(14, 5))

# |Return|
bp1 = axes[0].boxplot(
    [df.loc[non_mask, 'abs_return'] * 100, df.loc[earn_mask, 'abs_return'] * 100],
    labels=['Non-Earnings', 'Earnings'],
    patch_artist=True,
    showfliers=False  # hide outliers for clarity
)
bp1['boxes'][0].set_facecolor('#2980b9')
bp1['boxes'][1].set_facecolor('#d35400')
axes[0].set_ylabel('|Daily Return| (%)')
axes[0].set_title('Absolute Return')

# RV20
bp2 = axes[1].boxplot(
    [df.loc[non_mask, 'rv20'] * 100, df.loc[earn_mask, 'rv20'] * 100],
    labels=['Non-Earnings', 'Earnings'],
    patch_artist=True,
    showfliers=False
)
bp2['boxes'][0].set_facecolor('#2980b9')
bp2['boxes'][1].set_facecolor('#d35400')
axes[1].set_ylabel('20d RV (ann, %)')
axes[1].set_title('20-Day Realized Volatility')

# VIX
bp3 = axes[2].boxplot(
    [df.loc[non_mask, 'vix'], df.loc[earn_mask, 'vix']],
    labels=['Non-Earnings', 'Earnings'],
    patch_artist=True,
    showfliers=False
)
bp3['boxes'][0].set_facecolor('#2980b9')
bp3['boxes'][1].set_facecolor('#d35400')
axes[2].set_ylabel('VIX Level')
axes[2].set_title('VIX')

fig.suptitle('SPY: Earnings Season vs Non-Earnings Season (2006-2026)', fontsize=14, y=1.02)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k964_earnings_vs_non.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k964_earnings_vs_non.png")

# Plot 3: Rolling 5-year effect stability
fig, ax = plt.subplots(figsize=(10, 5))
windows = [r['window'] for r in rolling_effects]
ratios = [r['ratio'] for r in rolling_effects]
t_vals = [r['t'] for r in rolling_effects]

color_roll = ['#d35400' if abs(t) > 1.96 else '#bdc3c7' for t in t_vals]
ax.bar(range(len(windows)), ratios, color=color_roll, edgecolor='white', linewidth=0.5)
ax.axhline(y=1.0, color='black', linestyle='--', alpha=0.5)
ax.set_xticks(range(len(windows)))
ax.set_xticklabels(windows, rotation=45, ha='right', fontsize=8)
ax.set_ylabel('Earnings / Non-Earnings |Return| Ratio')
ax.set_title('Rolling 5-Year Earnings Effect Stability\nOrange = Significant at 5% level', fontsize=13)
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k964_rolling_effect.png'), dpi=150)
plt.close()
print("  Saved k964_rolling_effect.png")

# ============================================================
# Step 6: Summary & Trading Implications
# ============================================================
print("\n[6] Summary")
print("=" * 60)

# Determine overall conclusion
earnings_beta = reg_results['is_earnings']
vix_controlled = abs(earnings_beta['t']) > 3.0
unconditional_sig = abs(test_results['welch_t_abs_return']['t']) > 3.0

if vix_controlled:
    conclusion = "SIGNIFICANT: Earnings season has incremental vol effect even after VIX control"
elif unconditional_sig:
    conclusion = "PARTIALLY SIGNIFICANT: Earnings effect exists unconditionally but absorbed by VIX"
else:
    conclusion = "NOT SIGNIFICANT: No systematic earnings season volatility effect (VIX sufficiency confirmed)"

print(f"  Conclusion: {conclusion}")
print(f"  Earnings/Non ratio (|return|): {desc_stats['|Return|']['ratio']:.3f}")
print(f"  Unconditional t-stat: {test_results['welch_t_abs_return']['t']:.3f}")
print(f"  VIX-controlled t-stat: {earnings_beta['t']:.3f}")
print(f"  Regression R^2: {reg_results['r_squared']:.4f}")

# Trading strategy implications
if abs(earnings_beta['t']) < 2.0:
    strategy_implication = "Calendar-based VT overlay NOT justified — VIX already captures earnings season vol"
elif abs(earnings_beta['t']) < 3.0:
    strategy_implication = "Weak evidence for calendar overlay — monitor but not actionable"
else:
    strategy_implication = "Calendar-based VT overlay worth investigating — earnings dummy adds to VIX"

print(f"  Strategy implication: {strategy_implication}")

# ============================================================
# Save Results
# ============================================================
results = {
    'experiment_id': 'K964',
    'title': 'Earnings Season Volatility Patterns — SPY 20yr Analysis',
    'data_source': 'yfinance (SPY, ^VIX)',
    'period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_obs': int(len(df)),
    'n_earnings_days': int(n_earnings),
    'n_non_earnings_days': int(n_non),
    'earnings_pct': float(100 * n_earnings / len(df)),
    'descriptive_stats': desc_stats,
    'quarter_stats': quarter_stats,
    'statistical_tests': test_results,
    'conditional_analysis': conditional_results,
    'rolling_effects': rolling_effects,
    'monthly_avg_abs_return': {month_names[i]: float(v) for i, v in enumerate(monthly_vol.values)},
    'conclusion': conclusion,
    'strategy_implication': strategy_implication,
    'vix_controlled_significant': bool(vix_controlled),
    'unconditional_significant': bool(unconditional_sig),
    'references': [
        'Patell & Wolfson (1984) - Earnings announcements and intraday volatility',
        'Savor & Wilson (2016) - Earnings announcements and systematic risk',
        'Dubinsky et al. (2019) - Aggregate earnings surprises and market volatility',
        'Harvey (2016) - |t| > 3.0 threshold for multiple testing',
    ],
    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
}

results_path = os.path.join(OUT_DIR, 'k964_earnings_vol_results.json')
with open(results_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\n  Results saved to {results_path}")
print("\nDone.")
