"""
K990: SPY→0050.TW Monthly Lead-Lag Strategy
============================================
Background:
  - K983: SPY→0050.TW daily lead-lag r=0.40, OOS R²=15.9% (significant)
  - K984: Daily strategy NULL — TW trading costs (~0.585% round trip) kill alpha
  - Question: Does monthly rebalancing reduce costs enough for lead-lag alpha to survive?

Data source: yfinance (SPY, 0050.TW, ^VIX), 2006-01-01 to 2026-04-07
IS: 2006-2016, OOS: 2017-2026

References:
  - K983 (daily lead-lag significance)
  - K984 (daily strategy null result)
  - Moskowitz, Ooi, Pedersen (2012) "Time series momentum" JFE
"""

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
import os
from datetime import datetime
from scipy import stats

np.random.seed(42)

EXPERIMENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROUND_TRIP_COST = 0.00585  # 0.585% for Taiwan stocks

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K990: SPY→0050.TW Monthly Lead-Lag Strategy")
print("=" * 60)

print("\n[1] Downloading data...")
spy_raw = yf.download('SPY', start='2006-01-01', end='2026-04-07', progress=False)
tw50_raw = yf.download('0050.TW', start='2006-01-01', end='2026-04-07', progress=False)
vix_raw = yf.download('^VIX', start='2006-01-01', end='2026-04-07', progress=False)

# Handle multi-level columns from yfinance
def get_close(df, col='Close'):
    if isinstance(df.columns, pd.MultiIndex):
        # Try to get the column from the first level
        for ticker in df.columns.get_level_values(1).unique():
            if col in df.columns.get_level_values(0):
                return df[col].iloc[:, 0] if isinstance(df[col], pd.DataFrame) else df[col]
        return df.iloc[:, df.columns.get_level_values(0) == col].iloc[:, 0]
    return df[col]

spy_close = get_close(spy_raw, 'Close')
tw50_close = get_close(tw50_raw, 'Close')
vix_close = get_close(vix_raw, 'Close')

# Clean 0050.TW split artifacts
try:
    from volpred.utils import clean_tw50_data
    tw50_close, _ = clean_tw50_data(tw50_close)
except ImportError:
    # Inline fallback
    split_date = pd.Timestamp("2014-01-02")
    if split_date in tw50_close.index:
        pre_mask = tw50_close.index < split_date
        if pre_mask.any():
            last_pre = tw50_close[pre_mask].iloc[-1]
            first_post = tw50_close.loc[split_date]
            ratio = last_pre / first_post
            if 3.5 < ratio < 4.5:
                tw50_close = tw50_close.copy()
                tw50_close[pre_mask] = tw50_close[pre_mask] / 4.0

print(f"  SPY: {spy_close.index[0].date()} to {spy_close.index[-1].date()}, N={len(spy_close)}")
print(f"  0050.TW: {tw50_close.index[0].date()} to {tw50_close.index[-1].date()}, N={len(tw50_close)}")
print(f"  VIX: {vix_close.index[0].date()} to {vix_close.index[-1].date()}, N={len(vix_close)}")

# ============================================================
# 2. Compute Monthly Data
# ============================================================
print("\n[2] Computing monthly data...")

# Resample to month-end
spy_monthly = spy_close.resample('ME').last()
tw50_monthly = tw50_close.resample('ME').last()
vix_monthly = vix_close.resample('ME').last()

# Monthly returns
spy_monthly_ret = spy_monthly.pct_change()
tw50_monthly_ret = tw50_monthly.pct_change()

# SPY 3-month momentum
spy_3m_ret = spy_monthly.pct_change(3)

# Align all series
combined = pd.DataFrame({
    'spy_ret': spy_monthly_ret,
    'tw50_ret': tw50_monthly_ret,
    'spy_3m_ret': spy_3m_ret,
    'vix': vix_monthly,
    'spy_close': spy_monthly,
    'tw50_close': tw50_monthly
}).dropna()

print(f"  Combined monthly data: {combined.index[0].date()} to {combined.index[-1].date()}, N={len(combined)}")

# ============================================================
# 3. Descriptive Statistics & Lead-Lag Check
# ============================================================
print("\n[3] Descriptive statistics...")
print(f"  SPY monthly return: mean={combined['spy_ret'].mean()*100:.2f}%, std={combined['spy_ret'].std()*100:.2f}%")
print(f"  TW50 monthly return: mean={combined['tw50_ret'].mean()*100:.2f}%, std={combined['tw50_ret'].std()*100:.2f}%")
print(f"  VIX mean: {combined['vix'].mean():.1f}")

# Lead-lag correlation: SPY(t-1) → TW50(t)
spy_lag1 = combined['spy_ret'].shift(1)
corr_lag1 = combined['tw50_ret'].corr(spy_lag1)
print(f"\n  Lead-lag correlation (monthly): SPY(t-1) → TW50(t) = {corr_lag1:.4f}")

# t-test for significance
n = len(combined.dropna())
t_stat_corr = corr_lag1 * np.sqrt(n - 2) / np.sqrt(1 - corr_lag1**2)
p_val_corr = 2 * (1 - stats.t.cdf(abs(t_stat_corr), n - 2))
print(f"  t-stat = {t_stat_corr:.3f}, p-value = {p_val_corr:.4f}")

# ============================================================
# 4. Strategy Definitions
# ============================================================
print("\n[4] Defining strategies...")

# All signals use PREVIOUS month data (shift(1) = no lookahead)
signals = pd.DataFrame(index=combined.index)

# Strategy 1: Monthly Binary
# If SPY previous month > 0 → fully invested, else → cash
signals['binary'] = (combined['spy_ret'].shift(1) > 0).astype(float)

# Strategy 2: Monthly Proportional
# w = clip(0.5 + 2 * SPY_prev_month_return, 0, 1.5)
signals['proportional'] = (0.5 + 2.0 * combined['spy_ret'].shift(1)).clip(0, 1.5)

# Strategy 3: Monthly Momentum (3-month)
# SPY 3-month return > 0 → w=1.0, else → w=0.5
signals['momentum'] = np.where(combined['spy_3m_ret'].shift(1) > 0, 1.0, 0.5)

# Strategy 4: Monthly VT + SPY Signal
# w = (8.63/VIX_prev_month) * spy_adj
# spy_adj = 1.2 if SPY prev month > 0, 0.8 if < 0
spy_adj = np.where(combined['spy_ret'].shift(1) > 0, 1.2, 0.8)
signals['vt_spy'] = (8.63 / combined['vix'].shift(1)) * spy_adj
signals['vt_spy'] = signals['vt_spy'].clip(0, 1.5)

# Benchmark 1: Buy & Hold TW50
signals['buy_hold'] = 1.0

# Benchmark 2: Monthly VT (8.63/VIX) without SPY signal
signals['vt_only'] = (8.63 / combined['vix'].shift(1)).clip(0, 1.5)

# Drop first rows with NaN signals
signals = signals.dropna()
tw50_ret_aligned = combined['tw50_ret'].reindex(signals.index)

print(f"  Signal period: {signals.index[0].date()} to {signals.index[-1].date()}, N={len(signals)}")
for col in signals.columns:
    print(f"  {col}: mean_weight={signals[col].mean():.3f}, std={signals[col].std():.3f}")

# ============================================================
# 5. Transaction Cost Calculation
# ============================================================
print("\n[5] Computing returns with transaction costs...")

strategy_names = ['binary', 'proportional', 'momentum', 'vt_spy', 'buy_hold', 'vt_only']
results = {}

for name in strategy_names:
    w = signals[name]
    ret = tw50_ret_aligned

    # Gross return (weight * TW50 return)
    gross_ret = w * ret

    # Transaction cost: proportional to weight change
    weight_change = w.diff().abs()
    weight_change.iloc[0] = w.iloc[0]  # Initial investment
    tc = weight_change * ROUND_TRIP_COST

    # Net return
    net_ret = gross_ret - tc

    # Cumulative
    cum_ret = (1 + net_ret).cumprod()

    # Stats
    ann_ret = net_ret.mean() * 12
    ann_vol = net_ret.std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Sortino
    downside = net_ret[net_ret < 0].std() * np.sqrt(12)
    sortino = ann_ret / downside if downside > 0 else 0

    # MDD
    peak = cum_ret.cummax()
    dd = (cum_ret - peak) / peak
    mdd = dd.min()

    # Turnover (annualized)
    annual_turnover = weight_change.mean() * 12

    # Win rate
    win_rate = (net_ret > 0).mean()

    # Total TC paid
    total_tc = tc.sum()

    results[name] = {
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'sortino': float(sortino),
        'mdd': float(mdd),
        'cum_return': float(cum_ret.iloc[-1] - 1),
        'annual_turnover': float(annual_turnover),
        'win_rate': float(win_rate),
        'total_tc_paid': float(total_tc),
        'mean_weight': float(w.mean()),
        'net_returns': net_ret,
        'cum_returns': cum_ret,
        'weights': w
    }

print("\n  Full Sample Results:")
print(f"  {'Strategy':<20} {'Sharpe':>8} {'Ann Ret':>10} {'Ann Vol':>10} {'MDD':>8} {'Turnover':>10}")
print(f"  {'-'*66}")
for name in strategy_names:
    r = results[name]
    print(f"  {name:<20} {r['sharpe']:>8.3f} {r['ann_return']*100:>9.2f}% {r['ann_vol']*100:>9.2f}% {r['mdd']*100:>7.2f}% {r['annual_turnover']:>9.3f}")

# ============================================================
# 6. IS/OOS Split
# ============================================================
print("\n[6] IS/OOS Analysis...")
is_end = pd.Timestamp('2016-12-31')
oos_start = pd.Timestamp('2017-01-01')

is_oos_results = {}

for period_name, mask in [('IS (2006-2016)', signals.index <= is_end),
                           ('OOS (2017-2026)', signals.index > is_end)]:
    is_oos_results[period_name] = {}
    print(f"\n  {period_name}:")
    print(f"  {'Strategy':<20} {'Sharpe':>8} {'Ann Ret':>10} {'Ann Vol':>10} {'MDD':>8}")
    print(f"  {'-'*56}")

    for name in strategy_names:
        w = signals[name][mask]
        ret = tw50_ret_aligned[mask]
        gross_ret = w * ret
        weight_change = w.diff().abs()
        weight_change.iloc[0] = w.iloc[0]
        tc = weight_change * ROUND_TRIP_COST
        net_ret = gross_ret - tc
        cum_ret = (1 + net_ret).cumprod()

        ann_ret = net_ret.mean() * 12
        ann_vol = net_ret.std() * np.sqrt(12)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        mdd = ((cum_ret - cum_ret.cummax()) / cum_ret.cummax()).min()

        is_oos_results[period_name][name] = {
            'sharpe': float(sharpe),
            'ann_return': float(ann_ret),
            'ann_vol': float(ann_vol),
            'mdd': float(mdd)
        }

        print(f"  {name:<20} {sharpe:>8.3f} {ann_ret*100:>9.2f}% {ann_vol*100:>9.2f}% {mdd*100:>7.2f}%")

# ============================================================
# 7. Annual Returns Analysis
# ============================================================
print("\n[7] Annual returns by strategy...")

annual_returns = {}
for name in strategy_names:
    net_ret = results[name]['net_returns']
    annual = net_ret.groupby(net_ret.index.year).apply(lambda x: (1 + x).prod() - 1)
    annual_returns[name] = annual

print(f"\n  {'Year':<8}", end='')
for name in strategy_names:
    print(f" {name[:12]:>12}", end='')
print()

years = sorted(annual_returns['buy_hold'].index)
for year in years:
    print(f"  {year:<8}", end='')
    for name in strategy_names:
        if year in annual_returns[name].index:
            print(f" {annual_returns[name][year]*100:>11.2f}%", end='')
        else:
            print(f" {'N/A':>12}", end='')
    print()

# ============================================================
# 8. Statistical Tests
# ============================================================
print("\n[8] Statistical tests...")

# Test: Is excess return over buy_hold significant?
bh_ret = results['buy_hold']['net_returns']
test_results = {}

for name in ['binary', 'proportional', 'momentum', 'vt_spy', 'vt_only']:
    excess = results[name]['net_returns'] - bh_ret
    t_stat, p_val = stats.ttest_1samp(excess.dropna(), 0)
    test_results[name] = {
        'excess_mean_monthly': float(excess.mean()),
        'excess_ann': float(excess.mean() * 12),
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'significant_5pct': bool(p_val < 0.05),
        'significant_10pct': bool(p_val < 0.10)
    }
    print(f"  {name} vs buy_hold: excess={excess.mean()*1200:.2f} bps/month, t={t_stat:.3f}, p={p_val:.4f} {'*' if p_val < 0.05 else ''}")

# Test: VT+SPY vs VT-only
excess_vt = results['vt_spy']['net_returns'] - results['vt_only']['net_returns']
t_vt, p_vt = stats.ttest_1samp(excess_vt.dropna(), 0)
test_results['vt_spy_vs_vt_only'] = {
    'excess_mean_monthly': float(excess_vt.mean()),
    'excess_ann': float(excess_vt.mean() * 12),
    't_stat': float(t_vt),
    'p_value': float(p_vt),
    'significant_5pct': bool(p_vt < 0.05)
}
print(f"\n  VT+SPY vs VT-only: excess={excess_vt.mean()*1200:.2f} bps/month, t={t_vt:.3f}, p={p_vt:.4f} {'*' if p_vt < 0.05 else ''}")

# ============================================================
# 9. OOS-only statistical tests
# ============================================================
print("\n[9] OOS statistical tests...")

oos_mask = signals.index > is_end
oos_test_results = {}

for name in ['binary', 'proportional', 'momentum', 'vt_spy', 'vt_only']:
    w_oos = signals[name][oos_mask]
    ret_oos = tw50_ret_aligned[oos_mask]

    gross_ret = w_oos * ret_oos
    weight_change = w_oos.diff().abs()
    weight_change.iloc[0] = w_oos.iloc[0]
    tc = weight_change * ROUND_TRIP_COST
    net_ret = gross_ret - tc

    bh_ret_oos = ret_oos  # buy_hold weight=1
    excess = net_ret - bh_ret_oos
    t_stat, p_val = stats.ttest_1samp(excess.dropna(), 0)

    oos_test_results[name] = {
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'significant_5pct': bool(p_val < 0.05)
    }
    print(f"  OOS {name} vs buy_hold: t={t_stat:.3f}, p={p_val:.4f} {'*' if p_val < 0.05 else ''}")

# ============================================================
# 10. Plots
# ============================================================
print("\n[10] Generating plots...")

# Plot 1: Cumulative returns
fig, axes = plt.subplots(2, 1, figsize=(14, 10))

# Full sample
ax = axes[0]
colors = {'binary': '#e74c3c', 'proportional': '#3498db', 'momentum': '#2ecc71',
          'vt_spy': '#9b59b6', 'buy_hold': '#7f8c8d', 'vt_only': '#f39c12'}
labels = {'binary': 'Monthly Binary', 'proportional': 'Monthly Proportional',
          'momentum': '3-Month Momentum', 'vt_spy': 'VT + SPY Signal',
          'buy_hold': 'Buy & Hold TW50', 'vt_only': 'VT Only (8.63/VIX)'}

for name in strategy_names:
    ax.plot(results[name]['cum_returns'].index.to_numpy(), results[name]['cum_returns'].values,
            label=f"{labels[name]} (SR={results[name]['sharpe']:.2f})",
            color=colors[name], linewidth=1.5 if name in ['vt_spy', 'vt_only'] else 1.0,
            linestyle='--' if name == 'buy_hold' else '-')

ax.set_title('K990: Monthly SPY→TW50 Lead-Lag Strategies (Full Sample)', fontsize=14)
ax.set_ylabel('Cumulative Return (Growth of $1)')
ax.legend(loc='upper left', fontsize=9)
ax.grid(True, alpha=0.3)
ax.set_yscale('log')

# OOS only
ax = axes[1]
for name in strategy_names:
    oos_cum = results[name]['cum_returns'][results[name]['cum_returns'].index > is_end]
    if len(oos_cum) > 0:
        oos_cum_norm = oos_cum / oos_cum.iloc[0]
        oos_sharpe = is_oos_results['OOS (2017-2026)'][name]['sharpe']
        ax.plot(oos_cum_norm.index.to_numpy(), oos_cum_norm.values,
                label=f"{labels[name]} (SR={oos_sharpe:.2f})",
                color=colors[name], linewidth=1.5 if name in ['vt_spy', 'vt_only'] else 1.0,
                linestyle='--' if name == 'buy_hold' else '-')

ax.set_title('K990: OOS Period (2017-2026)', fontsize=14)
ax.set_ylabel('Cumulative Return (Growth of $1)')
ax.legend(loc='upper left', fontsize=9)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(EXPERIMENT_DIR, 'k990_cumulative_returns.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k990_cumulative_returns.png")

# Plot 2: Annual returns heatmap-style bar chart
fig, ax = plt.subplots(figsize=(14, 8))
x = np.arange(len(years))
width = 0.13
offsets = [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5]

for i, name in enumerate(strategy_names):
    vals = [annual_returns[name].get(y, 0) * 100 for y in years]
    ax.bar(x + offsets[i] * width, vals, width, label=labels[name], color=colors[name], alpha=0.8)

ax.set_title('K990: Annual Returns by Strategy (%)', fontsize=14)
ax.set_xlabel('Year')
ax.set_ylabel('Annual Return (%)')
ax.set_xticks(x)
ax.set_xticklabels(years, rotation=45)
ax.legend(loc='upper left', fontsize=8, ncol=2)
ax.grid(True, alpha=0.3, axis='y')
ax.axhline(y=0, color='black', linewidth=0.5)

plt.tight_layout()
plt.savefig(os.path.join(EXPERIMENT_DIR, 'k990_annual_returns.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k990_annual_returns.png")

# ============================================================
# 11. Save Results JSON
# ============================================================
print("\n[11] Saving results...")

output = {
    'experiment_id': 'K990',
    'title': 'SPY→0050.TW Monthly Lead-Lag Strategy',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance',
    'data_period': f"{combined.index[0].date()} to {combined.index[-1].date()}",
    'sample_size_months': len(combined),
    'is_period': '2006-2016',
    'oos_period': '2017-2026',
    'round_trip_cost': ROUND_TRIP_COST,
    'references': ['K983 (daily lead-lag r=0.40)', 'K984 (daily strategy NULL)'],
    'monthly_leadlag_correlation': {
        'spy_t_minus_1_to_tw50_t': float(corr_lag1),
        't_stat': float(t_stat_corr),
        'p_value': float(p_val_corr)
    },
    'full_sample_results': {
        name: {k: v for k, v in results[name].items() if k not in ['net_returns', 'cum_returns', 'weights']}
        for name in strategy_names
    },
    'is_oos_results': is_oos_results,
    'annual_returns': {
        name: {str(y): float(v) for y, v in annual_returns[name].items()}
        for name in strategy_names
    },
    'statistical_tests': test_results,
    'oos_statistical_tests': oos_test_results,
    'conclusion': '',  # Will be filled after analysis
    'key_findings': []
}

# ============================================================
# 12. Conclusions
# ============================================================
print("\n[12] Analysis & Conclusions...")

# Find best strategy
best_name = max(['binary', 'proportional', 'momentum', 'vt_spy'],
                key=lambda n: results[n]['sharpe'])
best_sharpe = results[best_name]['sharpe']
vt_only_sharpe = results['vt_only']['sharpe']
bh_sharpe = results['buy_hold']['sharpe']

# OOS best
oos_best_name = max(['binary', 'proportional', 'momentum', 'vt_spy'],
                     key=lambda n: is_oos_results['OOS (2017-2026)'][n]['sharpe'])
oos_best_sharpe = is_oos_results['OOS (2017-2026)'][oos_best_name]['sharpe']
oos_vt_sharpe = is_oos_results['OOS (2017-2026)']['vt_only']['sharpe']

findings = []

# Finding 1: Monthly lead-lag correlation
if abs(corr_lag1) > 0.1 and p_val_corr < 0.05:
    findings.append(f"Monthly SPY(t-1)→TW50(t) correlation = {corr_lag1:.3f} (significant, p={p_val_corr:.4f})")
else:
    findings.append(f"Monthly SPY(t-1)→TW50(t) correlation = {corr_lag1:.3f} (weak/insignificant, p={p_val_corr:.4f})")

# Finding 2: Cost reduction
daily_tc_est = 122 * ROUND_TRIP_COST  # K984: 122 trades
monthly_tc_total = sum(results[best_name]['total_tc_paid'] for _ in [1])
findings.append(f"Monthly rebalancing: total TC paid = {results[best_name]['total_tc_paid']*100:.2f}% vs daily ~{daily_tc_est*100:.1f}%")

# Finding 3: Best strategy performance
findings.append(f"Best lead-lag strategy: {best_name} (Sharpe={best_sharpe:.3f}, full sample)")
findings.append(f"VT-only benchmark: Sharpe={vt_only_sharpe:.3f}, Buy&Hold: Sharpe={bh_sharpe:.3f}")

# Finding 4: SPY signal overlay value
vt_spy_improvement = results['vt_spy']['sharpe'] - results['vt_only']['sharpe']
findings.append(f"VT+SPY signal overlay vs VT-only: Sharpe diff = {vt_spy_improvement:+.3f}, t={t_vt:.3f}, p={p_vt:.4f}")

# Finding 5: OOS persistence
findings.append(f"OOS best: {oos_best_name} (Sharpe={oos_best_sharpe:.3f}), VT-only OOS: Sharpe={oos_vt_sharpe:.3f}")

# Determine overall conclusion
if oos_best_sharpe > oos_vt_sharpe + 0.1 and oos_test_results.get(oos_best_name, {}).get('significant_5pct', False):
    conclusion = f"POSITIVE: Monthly SPY lead-lag adds value to TW50 allocation. Best: {oos_best_name} (OOS Sharpe={oos_best_sharpe:.3f} vs VT-only {oos_vt_sharpe:.3f}). Monthly rebalancing reduces costs enough for alpha to survive."
elif oos_best_sharpe > oos_vt_sharpe:
    conclusion = f"MARGINAL: Monthly SPY lead-lag shows slight improvement (OOS best {oos_best_name} Sharpe={oos_best_sharpe:.3f} vs VT-only {oos_vt_sharpe:.3f}), but not statistically significant. Cost reduction helps but alpha is weak at monthly frequency."
else:
    conclusion = f"NULL: Monthly SPY lead-lag does NOT improve over VT-only at monthly frequency. OOS best {oos_best_name} Sharpe={oos_best_sharpe:.3f} vs VT-only {oos_vt_sharpe:.3f}. Lead-lag alpha may be too short-lived for monthly rebalancing."

output['conclusion'] = conclusion
output['key_findings'] = findings

# Save JSON
with open(os.path.join(EXPERIMENT_DIR, 'k990_monthly_leadlag_results.json'), 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Conclusion: {conclusion}")
print(f"\n  Key findings:")
for f in findings:
    print(f"    - {f}")

print("\n" + "=" * 60)
print("K990 Complete.")
print("=" * 60)
