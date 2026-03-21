"""
VIX Seasonality / Cyclical Pattern Analysis
============================================
Research question: Does VIX exhibit exploitable seasonal or cyclical patterns?
- Day-of-week effect
- Month-of-year effect
- Options expiration effect
- Strategy implications

[提出: User, 執行: Claude]
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import pandas as pd
from scipy import stats
from volpred.data.manager import DataManager

pd.set_option('display.float_format', '{:.4f}'.format)
pd.set_option('display.width', 120)

# ==============================================================================
# 1. Load Data
# ==============================================================================
print("=" * 80)
print("VIX SEASONALITY / CYCLICAL PATTERN ANALYSIS")
print("=" * 80)

dm = DataManager()
vix_data = dm.get_price_data("^VIX", "2010-01-01", "2026-12-31")
spy_data = dm.get_price_data("SPY", "2010-01-01", "2026-12-31")

# Use close for VIX level (columns are lowercase)
vix = vix_data['close'].copy()
vix.index = pd.to_datetime(vix.index)
vix.name = 'VIX'

spy_close = spy_data['close'].copy()
spy_close.index = pd.to_datetime(spy_close.index)

# Align dates
common_idx = vix.index.intersection(spy_close.index)
vix = vix.loc[common_idx]
spy_close = spy_close.loc[common_idx]

# Compute changes
vix_change = vix.diff()
vix_pct_change = vix.pct_change() * 100  # in percent
spy_ret = spy_close.pct_change() * 100

print(f"\nData range: {vix.index[0].date()} to {vix.index[-1].date()}")
print(f"Total trading days: {len(vix)}")
print(f"Mean VIX: {vix.mean():.2f}, Std: {vix.std():.2f}")

# ==============================================================================
# 2. Day-of-Week Analysis
# ==============================================================================
print("\n" + "=" * 80)
print("SECTION 2: DAY-OF-WEEK ANALYSIS")
print("=" * 80)

dow_names = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday'}

# Create day-of-week column
df = pd.DataFrame({
    'VIX': vix,
    'VIX_change': vix_change,
    'VIX_pct': vix_pct_change,
    'SPY_ret': spy_ret,
    'DOW': vix.index.dayofweek,
    'Month': vix.index.month,
    'Year': vix.index.year,
})
df = df.dropna()

# 2a. Mean VIX level by day of week
print("\n--- Mean VIX Level by Day of Week ---")
dow_vix = df.groupby('DOW')['VIX'].agg(['mean', 'median', 'std', 'count'])
dow_vix.index = dow_vix.index.map(dow_names)
print(dow_vix)

# 2b. Mean VIX change by day of week
print("\n--- Mean VIX Change (points) by Day of Week ---")
dow_change = df.groupby('DOW')['VIX_change'].agg(['mean', 'median', 'std', 'count'])
dow_change.index = dow_change.index.map(dow_names)
print(dow_change)

# t-test for each day: is mean change significantly different from 0?
print("\n--- t-tests: VIX change != 0 by day ---")
for day_num, day_name in dow_names.items():
    subset = df[df['DOW'] == day_num]['VIX_change']
    t_stat, p_val = stats.ttest_1samp(subset, 0)
    n = len(subset)
    print(f"  {day_name:10s}: mean={subset.mean():+.4f}, t={t_stat:+.3f}, p={p_val:.4f}, n={n}")

# 2c. Mean VIX % change by day of week
print("\n--- Mean VIX % Change by Day of Week ---")
dow_pct = df.groupby('DOW')['VIX_pct'].agg(['mean', 'median', 'std', 'count'])
dow_pct.index = dow_pct.index.map(dow_names)
print(dow_pct)

# t-test for each day: is mean % change significantly different from 0?
print("\n--- t-tests: VIX % change != 0 by day ---")
for day_num, day_name in dow_names.items():
    subset = df[df['DOW'] == day_num]['VIX_pct']
    t_stat, p_val = stats.ttest_1samp(subset, 0)
    n = len(subset)
    print(f"  {day_name:10s}: mean={subset.mean():+.4f}%, t={t_stat:+.3f}, p={p_val:.4f}, n={n}")

# 2d. ANOVA: do days differ from each other?
groups = [df[df['DOW'] == d]['VIX_pct'].values for d in range(5)]
f_stat, p_anova = stats.f_oneway(*groups)
print(f"\nOne-way ANOVA (VIX % change ~ DOW): F={f_stat:.3f}, p={p_anova:.4f}")

# Kruskal-Wallis (non-parametric)
h_stat, p_kw = stats.kruskal(*groups)
print(f"Kruskal-Wallis (VIX % change ~ DOW): H={h_stat:.3f}, p={p_kw:.4f}")

# 2e. SPY returns by day of week
print("\n--- Mean SPY Return (%) by Day of Week ---")
dow_spy = df.groupby('DOW')['SPY_ret'].agg(['mean', 'median', 'std', 'count'])
dow_spy.index = dow_spy.index.map(dow_names)
print(dow_spy)

# ==============================================================================
# 3. Month-of-Year Analysis
# ==============================================================================
print("\n" + "=" * 80)
print("SECTION 3: MONTH-OF-YEAR ANALYSIS")
print("=" * 80)

month_names = {1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun',
               7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'}

# 3a. Mean VIX level by month
print("\n--- Mean VIX Level by Month ---")
month_vix = df.groupby('Month')['VIX'].agg(['mean', 'median', 'std', 'count'])
month_vix.index = month_vix.index.map(month_names)
print(month_vix)

# 3b. Mean VIX % change by month
print("\n--- Mean VIX % Change by Month ---")
month_pct = df.groupby('Month')['VIX_pct'].agg(['mean', 'median', 'std', 'count'])
month_pct.index = month_pct.index.map(month_names)
print(month_pct)

# t-test for each month
print("\n--- t-tests: VIX % change != 0 by month ---")
for m in range(1, 13):
    subset = df[df['Month'] == m]['VIX_pct']
    t_stat, p_val = stats.ttest_1samp(subset, 0)
    print(f"  {month_names[m]:3s}: mean={subset.mean():+.4f}%, t={t_stat:+.3f}, p={p_val:.4f}, n={len(subset)}")

# ANOVA across months
groups_m = [df[df['Month'] == m]['VIX_pct'].values for m in range(1, 13)]
f_stat_m, p_anova_m = stats.f_oneway(*groups_m)
print(f"\nOne-way ANOVA (VIX % change ~ Month): F={f_stat_m:.3f}, p={p_anova_m:.4f}")

h_stat_m, p_kw_m = stats.kruskal(*groups_m)
print(f"Kruskal-Wallis (VIX % change ~ Month): H={h_stat_m:.3f}, p={p_kw_m:.4f}")

# 3c. Monthly VIX level seasonality (compute monthly average VIX, then average across years)
print("\n--- Monthly Average VIX (across years) ---")
monthly_avg = df.groupby([df.index.year, df.index.month])['VIX'].mean()
monthly_avg.index.names = ['Year', 'Month']
monthly_avg = monthly_avg.reset_index()
month_season = monthly_avg.groupby('Month')['VIX'].agg(['mean', 'std', 'count'])
month_season.index = month_season.index.map(month_names)
print(month_season)

# ==============================================================================
# 4. Options Expiration Effect
# ==============================================================================
print("\n" + "=" * 80)
print("SECTION 4: OPTIONS EXPIRATION EFFECT")
print("=" * 80)

# Monthly options expire on 3rd Friday of each month
# VIX settlement is on the Wednesday 30 days before the next month's 3rd Friday
# But for simplicity, we'll look at the 3rd Friday effect

def third_friday(year, month):
    """Return the 3rd Friday of the given month/year."""
    # Find first day of month
    first = pd.Timestamp(year, month, 1)
    # Find first Friday
    offset = (4 - first.dayofweek) % 7  # 4 = Friday
    first_friday = first + pd.Timedelta(days=offset)
    third_friday = first_friday + pd.Timedelta(weeks=2)
    return third_friday

# Generate all 3rd Fridays in our data range
exp_dates = []
for year in range(2010, 2027):
    for month in range(1, 13):
        tf = third_friday(year, month)
        if tf in vix.index:
            exp_dates.append(tf)

print(f"Found {len(exp_dates)} monthly expiration dates in data")

# Quarterly expiration (Mar, Jun, Sep, Dec)
quarterly_months = {3, 6, 9, 12}
quarterly_exp = [d for d in exp_dates if d.month in quarterly_months]
monthly_only_exp = [d for d in exp_dates if d.month not in quarterly_months]

print(f"  Quarterly expirations: {len(quarterly_exp)}")
print(f"  Monthly-only expirations: {len(monthly_only_exp)}")

# VIX behavior around expiration: -5 to +5 days
print("\n--- VIX Change Around Monthly Expiration (day 0 = expiration Friday) ---")
window_days = 5
exp_effects = {}

for offset in range(-window_days, window_days + 1):
    changes = []
    for exp_date in exp_dates:
        # Find the trading day at this offset
        exp_idx = vix.index.get_loc(exp_date)
        target_idx = exp_idx + offset
        if 0 <= target_idx < len(vix) and target_idx - 1 >= 0:
            change = vix_pct_change.iloc[target_idx]
            if not np.isnan(change):
                changes.append(change)
    exp_effects[offset] = changes

for offset in range(-window_days, window_days + 1):
    changes = exp_effects[offset]
    mean_chg = np.mean(changes)
    t_stat, p_val = stats.ttest_1samp(changes, 0)
    label = "<<< EXP DAY" if offset == 0 else ""
    print(f"  Day {offset:+2d}: mean={mean_chg:+.4f}%, t={t_stat:+.3f}, p={p_val:.4f}, n={len(changes)} {label}")

# Compare expiration week vs non-expiration week
print("\n--- Expiration Week vs Non-Expiration Week ---")
exp_week_changes = []
non_exp_week_changes = []

# Create a set of dates that are within the expiration week (Mon-Fri containing 3rd Friday)
exp_week_dates = set()
for exp_date in exp_dates:
    # Get the Monday of the week
    dow = exp_date.dayofweek
    monday = exp_date - pd.Timedelta(days=dow)
    for d in range(5):
        exp_week_dates.add(monday + pd.Timedelta(days=d))

for idx in df.index:
    if idx in exp_week_dates:
        exp_week_changes.append(df.loc[idx, 'VIX_pct'])
    else:
        non_exp_week_changes.append(df.loc[idx, 'VIX_pct'])

exp_week_changes = np.array(exp_week_changes)
non_exp_week_changes = np.array(non_exp_week_changes)

print(f"  Expiration week: mean={np.mean(exp_week_changes):+.4f}%, std={np.std(exp_week_changes):.4f}%, n={len(exp_week_changes)}")
print(f"  Non-exp week:    mean={np.mean(non_exp_week_changes):+.4f}%, std={np.std(non_exp_week_changes):.4f}%, n={len(non_exp_week_changes)}")

t_exp, p_exp = stats.ttest_ind(exp_week_changes, non_exp_week_changes)
print(f"  Two-sample t-test: t={t_exp:.3f}, p={p_exp:.4f}")

# Mann-Whitney U test (non-parametric)
u_stat, p_mw = stats.mannwhitneyu(exp_week_changes, non_exp_week_changes, alternative='two-sided')
print(f"  Mann-Whitney U: U={u_stat:.0f}, p={p_mw:.4f}")

# ==============================================================================
# 5. Quarterly Expiration Effect
# ==============================================================================
print("\n--- Quarterly vs Monthly-Only Expiration ---")
q_changes_on_day = []
m_changes_on_day = []

for exp_date in quarterly_exp:
    if exp_date in vix_pct_change.index:
        val = vix_pct_change.loc[exp_date]
        if not np.isnan(val):
            q_changes_on_day.append(val)

for exp_date in monthly_only_exp:
    if exp_date in vix_pct_change.index:
        val = vix_pct_change.loc[exp_date]
        if not np.isnan(val):
            m_changes_on_day.append(val)

print(f"  Quarterly exp day: mean={np.mean(q_changes_on_day):+.4f}%, n={len(q_changes_on_day)}")
print(f"  Monthly exp day:   mean={np.mean(m_changes_on_day):+.4f}%, n={len(m_changes_on_day)}")
t_qm, p_qm = stats.ttest_ind(q_changes_on_day, m_changes_on_day)
print(f"  t-test: t={t_qm:.3f}, p={p_qm:.4f}")

# ==============================================================================
# 6. Interaction: DOW x Month (VIX level)
# ==============================================================================
print("\n" + "=" * 80)
print("SECTION 5: INTERACTION EFFECTS")
print("=" * 80)

# Is the Monday effect stronger in certain months?
print("\n--- Monday VIX % Change by Month ---")
monday_data = df[df['DOW'] == 0]
for m in range(1, 13):
    subset = monday_data[monday_data['Month'] == m]['VIX_pct']
    if len(subset) > 5:
        t_stat, p_val = stats.ttest_1samp(subset, 0)
        print(f"  {month_names[m]:3s}: mean={subset.mean():+.4f}%, t={t_stat:+.3f}, p={p_val:.4f}, n={len(subset)}")

# Friday effect by month
print("\n--- Friday VIX % Change by Month ---")
friday_data = df[df['DOW'] == 4]
for m in range(1, 13):
    subset = friday_data[friday_data['Month'] == m]['VIX_pct']
    if len(subset) > 5:
        t_stat, p_val = stats.ttest_1samp(subset, 0)
        print(f"  {month_names[m]:3s}: mean={subset.mean():+.4f}%, t={t_stat:+.3f}, p={p_val:.4f}, n={len(subset)}")

# ==============================================================================
# 7. Sub-period Stability
# ==============================================================================
print("\n" + "=" * 80)
print("SECTION 6: SUB-PERIOD STABILITY (DOW effect)")
print("=" * 80)

# Split into 4 sub-periods
periods = [
    ("2010-2013", "2010-01-01", "2013-12-31"),
    ("2014-2017", "2014-01-01", "2017-12-31"),
    ("2018-2021", "2018-01-01", "2021-12-31"),
    ("2022-2026", "2022-01-01", "2026-12-31"),
]

for period_name, start, end in periods:
    sub = df[(df.index >= start) & (df.index <= end)]
    print(f"\n--- {period_name} (n={len(sub)}) ---")
    for day_num, day_name in dow_names.items():
        subset = sub[sub['DOW'] == day_num]['VIX_pct']
        t_stat, p_val = stats.ttest_1samp(subset, 0)
        sig = "*" if p_val < 0.05 else ""
        print(f"  {day_name:10s}: mean={subset.mean():+.4f}%, t={t_stat:+.3f}, p={p_val:.4f} {sig}")

# ==============================================================================
# 8. Strategy Simulation: DOW-adjusted VT
# ==============================================================================
print("\n" + "=" * 80)
print("SECTION 7: STRATEGY SIMULATION — DOW-ADJUSTED 12/VIX VT")
print("=" * 80)

# Baseline: 12/VIX strategy
# Weight = min(1, 12/VIX)
vix_aligned = vix.reindex(spy_close.index).ffill()
spy_ret_aligned = spy_close.pct_change()

# Drop NaN
valid = ~(vix_aligned.isna() | spy_ret_aligned.isna())
vix_a = vix_aligned[valid]
spy_r = spy_ret_aligned[valid]

# Baseline 12/VIX
weight_base = (12.0 / vix_a.shift(1)).clip(0, 1)
ret_base = weight_base * spy_r
ret_base = ret_base.dropna()

# DOW-adjusted strategies
df_strat = pd.DataFrame({
    'spy_ret': spy_r,
    'vix': vix_a,
    'weight_base': weight_base,
    'DOW': spy_r.index.dayofweek,
})
df_strat = df_strat.dropna()

# Strategy 1: Reduce Monday exposure by 20%
weight_dow1 = df_strat['weight_base'].copy()
weight_dow1[df_strat['DOW'] == 0] *= 0.8  # Reduce Monday
ret_dow1 = weight_dow1 * df_strat['spy_ret']

# Strategy 2: Reduce Monday by 20%, Increase Friday by 20% (capped at 1)
weight_dow2 = df_strat['weight_base'].copy()
weight_dow2[df_strat['DOW'] == 0] *= 0.8
weight_dow2[df_strat['DOW'] == 4] = (weight_dow2[df_strat['DOW'] == 4] * 1.2).clip(0, 1)
ret_dow2 = weight_dow2 * df_strat['spy_ret']

# Strategy 3: Skip Mondays entirely
weight_dow3 = df_strat['weight_base'].copy()
weight_dow3[df_strat['DOW'] == 0] = 0
ret_dow3 = weight_dow3 * df_strat['spy_ret']

# Strategy 4: Expiration week reduction (reduce by 20%)
exp_week_set = exp_week_dates
weight_exp = df_strat['weight_base'].copy()
weight_exp[weight_exp.index.isin(exp_week_set)] *= 0.8
ret_exp = weight_exp * df_strat['spy_ret']

# Buy-and-hold SPY
ret_bh = df_strat['spy_ret']

def compute_metrics(returns, name):
    """Compute Sharpe, MDD, total return."""
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # t-stat for Sharpe
    n = len(returns)
    t_sharpe = sharpe * np.sqrt(n / 252)

    # MDD
    cum = (1 + returns).cumprod()
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    mdd = dd.min()

    # Total return
    total_ret = cum.iloc[-1] - 1

    return {
        'name': name,
        'ann_ret': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        't_sharpe': t_sharpe,
        'mdd': mdd,
        'total_ret': total_ret,
        'n': n,
    }

strategies = {
    'Buy&Hold SPY': ret_bh,
    '12/VIX Baseline': ret_base.reindex(df_strat.index).dropna(),
    'DOW1: Mon-20%': ret_dow1,
    'DOW2: Mon-20%,Fri+20%': ret_dow2,
    'DOW3: Skip Monday': ret_dow3,
    'ExpWeek: -20%': ret_exp,
}

results = []
for name, rets in strategies.items():
    r = compute_metrics(rets, name)
    results.append(r)

results_df = pd.DataFrame(results).set_index('name')
print("\n--- Strategy Comparison ---")
print(results_df[['ann_ret', 'ann_vol', 'sharpe', 't_sharpe', 'mdd', 'total_ret', 'n']].to_string(float_format='{:.4f}'.format))

# Diebold-Mariano test: each variant vs baseline
print("\n--- Diebold-Mariano Tests (vs 12/VIX Baseline) ---")
baseline_rets = strategies['12/VIX Baseline']

for name, rets in strategies.items():
    if name == '12/VIX Baseline' or name == 'Buy&Hold SPY':
        continue
    # Align
    common = baseline_rets.index.intersection(rets.index)
    base_r = baseline_rets.loc[common]
    alt_r = rets.loc[common]

    # DM test using squared returns as loss
    d = alt_r**2 - base_r**2  # Negative means alternative has lower variance (not useful)
    # Actually, compare cumulative returns
    d = alt_r - base_r  # Positive means alternative is better
    mean_d = d.mean()
    std_d = d.std()
    t_dm = mean_d / (std_d / np.sqrt(len(d))) if std_d > 0 else 0
    p_dm = 2 * (1 - stats.norm.cdf(abs(t_dm)))
    print(f"  {name:25s}: mean_diff={mean_d*252*100:.2f} bps/yr, t={t_dm:.3f}, p={p_dm:.4f}")

# ==============================================================================
# 9. Regression Analysis
# ==============================================================================
print("\n" + "=" * 80)
print("SECTION 8: REGRESSION ANALYSIS")
print("=" * 80)

# VIX_pct_change = a + b1*Mon + b2*Tue + b3*Thu + b4*Fri + e (Wed is base)
from numpy.linalg import lstsq

df_reg = df[['VIX_pct', 'DOW', 'Month']].dropna().copy()

# Day-of-week dummies (Wed=base)
for d in [0, 1, 3, 4]:
    df_reg[f'D{d}'] = (df_reg['DOW'] == d).astype(float)

# Month dummies (Jan=base)
for m in range(2, 13):
    df_reg[f'M{m}'] = (df_reg['Month'] == m).astype(float)

# Full model: DOW + Month
X_cols = [f'D{d}' for d in [0, 1, 3, 4]] + [f'M{m}' for m in range(2, 13)]
X = df_reg[X_cols].values
X = np.column_stack([np.ones(len(X)), X])  # add intercept
y = df_reg['VIX_pct'].values

beta, residuals, rank, sv = lstsq(X, y, rcond=None)
y_hat = X @ beta
resid = y - y_hat
n, k = X.shape
s2 = np.sum(resid**2) / (n - k)
cov_beta = s2 * np.linalg.inv(X.T @ X)
se_beta = np.sqrt(np.diag(cov_beta))
t_stats = beta / se_beta
p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), n - k))

col_names = ['Intercept'] + X_cols
print("\n--- OLS: VIX_pct ~ DOW dummies + Month dummies ---")
print(f"{'Variable':12s} {'Coeff':>10s} {'SE':>10s} {'t-stat':>10s} {'p-value':>10s}")
print("-" * 55)
for name, b, se, t, p in zip(col_names, beta, se_beta, t_stats, p_vals):
    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    print(f"{name:12s} {b:10.4f} {se:10.4f} {t:10.3f} {p:10.4f} {sig}")

# F-test for DOW dummies jointly
# H0: all DOW coefficients = 0
R_dow = np.zeros((4, k))
for i, col_idx in enumerate([1, 2, 3, 4]):  # D0, D1, D3, D4
    R_dow[i, col_idx] = 1
r_dow = np.zeros(4)
diff_dow = R_dow @ beta - r_dow
F_dow = (diff_dow @ np.linalg.inv(R_dow @ cov_beta @ R_dow.T / s2 * s2) @ diff_dow) / 4
p_F_dow = 1 - stats.f.cdf(F_dow, 4, n - k)
print(f"\nJoint F-test (DOW dummies = 0): F={F_dow:.3f}, p={p_F_dow:.4f}")

# F-test for Month dummies jointly
R_month = np.zeros((11, k))
for i, col_idx in enumerate(range(5, 16)):  # M2 through M12
    R_month[i, col_idx] = 1
r_month = np.zeros(11)
diff_month = R_month @ beta - r_month
F_month = (diff_month @ np.linalg.inv(R_month @ cov_beta @ R_month.T / s2 * s2) @ diff_month) / 11
p_F_month = 1 - stats.f.cdf(F_month, 11, n - k)
print(f"Joint F-test (Month dummies = 0): F={F_month:.3f}, p={p_F_month:.4f}")

R2 = 1 - np.sum(resid**2) / np.sum((y - y.mean())**2)
print(f"\nR-squared: {R2:.6f}")
print(f"Adjusted R-squared: {1 - (1-R2)*(n-1)/(n-k-1):.6f}")

# ==============================================================================
# 10. VIX Term Structure Seasonality (if VIX level varies by month)
# ==============================================================================
print("\n" + "=" * 80)
print("SECTION 9: VIX LEVEL SEASONALITY — KRUSKAL-WALLIS")
print("=" * 80)

# Test: does VIX LEVEL differ by month?
groups_level = [df[df['Month'] == m]['VIX'].values for m in range(1, 13)]
h_level, p_level = stats.kruskal(*groups_level)
print(f"Kruskal-Wallis (VIX level ~ Month): H={h_level:.3f}, p={p_level:.4f}")

# Pairwise: highest vs lowest month
month_means = {m: df[df['Month'] == m]['VIX'].mean() for m in range(1, 13)}
highest_month = max(month_means, key=month_means.get)
lowest_month = min(month_means, key=month_means.get)
print(f"\nHighest mean VIX month: {month_names[highest_month]} ({month_means[highest_month]:.2f})")
print(f"Lowest mean VIX month:  {month_names[lowest_month]} ({month_means[lowest_month]:.2f})")

t_hl, p_hl = stats.ttest_ind(
    df[df['Month'] == highest_month]['VIX'],
    df[df['Month'] == lowest_month]['VIX']
)
print(f"t-test (highest vs lowest): t={t_hl:.3f}, p={p_hl:.4f}")

# ==============================================================================
# 11. SUMMARY & CONCLUSIONS
# ==============================================================================
print("\n" + "=" * 80)
print("SECTION 10: SUMMARY & CONCLUSIONS")
print("=" * 80)

print("""
KEY FINDINGS:
=============

1. DAY-OF-WEEK EFFECT:
   - Check t-tests above. Known hypothesis: VIX rises on Monday, declines on Friday.
   - ANOVA/Kruskal-Wallis tests whether any systematic DOW difference exists.

2. MONTH-OF-YEAR EFFECT:
   - Known hypothesis: VIX higher in Sep-Oct (crash season), lower in Q1/Q4 rally.
   - Check if F-test for month dummies is significant.

3. OPTIONS EXPIRATION:
   - VIX settlement dynamics may cause systematic patterns around expiration.

4. STRATEGY IMPLICATIONS:
   - Harvey (2016) threshold: t > 3 required for new strategy factors.
   - Even if patterns exist statistically, transaction costs from daily rebalancing
     may eliminate any edge.
   - The 12/VIX strategy rebalances monthly, not daily, so DOW effects are irrelevant
     for the current implementation.

5. R-SQUARED:
   - Expected to be near zero — VIX changes are mostly driven by market events,
     not calendar effects.
""")

# ==============================================================================
# 12. Effect Size Summary Table
# ==============================================================================
print("\n--- Effect Size Summary ---")
print(f"{'Pattern':30s} {'Effect':>12s} {'t-stat':>10s} {'|t|>3?':>8s} {'Exploitable?':>15s}")
print("-" * 80)

# Monday effect
mon = df[df['DOW'] == 0]['VIX_pct']
t_mon, p_mon = stats.ttest_1samp(mon, 0)
print(f"{'Monday VIX % change':30s} {mon.mean():+10.4f}% {t_mon:+10.3f} {'YES' if abs(t_mon)>3 else 'NO':>8s} {'Maybe' if abs(t_mon)>3 else 'No':>15s}")

# Friday effect
fri = df[df['DOW'] == 4]['VIX_pct']
t_fri, p_fri = stats.ttest_1samp(fri, 0)
print(f"{'Friday VIX % change':30s} {fri.mean():+10.4f}% {t_fri:+10.3f} {'YES' if abs(t_fri)>3 else 'NO':>8s} {'Maybe' if abs(t_fri)>3 else 'No':>15s}")

# ANOVA DOW
print(f"{'DOW joint effect (ANOVA)':30s} {'F='+str(round(f_stat,2)):>12s} {'p='+str(round(p_anova,4)):>10s} {'':>8s} {'':>15s}")

# Month effect (highest vs lowest)
print(f"{'Month effect (VIX level)':30s} {'H='+str(round(h_level,2)):>12s} {'p='+str(round(p_level,4)):>10s} {'':>8s} {'':>15s}")

# Expiration week
print(f"{'Exp week effect':30s} {'t='+str(round(t_exp,2)):>12s} {'p='+str(round(p_exp,4)):>10s} {'YES' if abs(t_exp)>3 else 'NO':>8s} {'Maybe' if abs(t_exp)>3 else 'No':>15s}")

# Strategy improvement
print(f"\n{'Strategy Sharpe improvements over 12/VIX baseline are shown in Section 7 above.'}")

print("\n" + "=" * 80)
print("EXPERIMENT COMPLETE")
print("=" * 80)
