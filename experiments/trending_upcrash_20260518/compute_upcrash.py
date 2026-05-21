"""
Up-Crash Episode Analysis
=========================
Topic: When markets surge fast (SPY/QQQ monthly +5%+) while VIX stays low or falls,
what happens to realized volatility in the following 20 trading days?

This is the VolPred-angle reconstruction of the "positive QQQ-call correlation" phenomenon
observed in options markets — independently computed from primary sources (yfinance).

Data: SPY, QQQ, ^VIX  (2014-01-01 to 2026-05-15)
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import yfinance as yf
from scipy import stats
import warnings
import os

warnings.filterwarnings('ignore')

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── 1. Download data ────────────────────────────────────────────────────────
print("Downloading data from yfinance...")

def get_close(ticker, start, end):
    """Download and return Close price as a clean 1-D Series."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    close = raw["Close"]
    # yfinance may return DataFrame with multi-level columns; squeeze to Series
    if isinstance(close, pd.DataFrame):
        close = close.squeeze()
    return close.rename(ticker)

spy = get_close("SPY", "2014-01-01", "2026-05-16")
qqq = get_close("QQQ", "2014-01-01", "2026-05-16")
vix = get_close("^VIX", "2014-01-01", "2026-05-16")

# Align to same dates
common_idx = spy.index.intersection(qqq.index).intersection(vix.index)
spy = spy.loc[common_idx]
qqq = qqq.loc[common_idx]
vix = vix.loc[common_idx]

# Daily returns
spy_ret = spy.pct_change().dropna()
qqq_ret = qqq.pct_change().dropna()

print(f"Data range: {spy.index[0].date()} to {spy.index[-1].date()}")
print(f"Total trading days: {len(spy)}")

# ─── 2. Monthly stats ────────────────────────────────────────────────────────
# Group by year-month
spy_monthly = spy_ret.resample('ME').apply(lambda x: (1 + x).prod() - 1)
qqq_monthly = qqq_ret.resample('ME').apply(lambda x: (1 + x).prod() - 1)
vix_monthly_avg = vix.resample('ME').mean()

# VIX monthly change = current month avg - prior month avg
vix_monthly_change = vix_monthly_avg.pct_change()

# Align to same months
monthly_index = spy_monthly.index.intersection(qqq_monthly.index).intersection(vix_monthly_change.index)
spy_monthly = spy_monthly.loc[monthly_index]
qqq_monthly = qqq_monthly.loc[monthly_index]
vix_monthly_change_aligned = vix_monthly_change.loc[monthly_index]
vix_monthly_avg_aligned = vix_monthly_avg.loc[monthly_index]

print(f"\nMonthly data range: {monthly_index[0].date()} to {monthly_index[-1].date()}")
print(f"Total months: {len(monthly_index)}")

# ─── 3. Compute post-episode 20-day realized vol ─────────────────────────────
# For each month, compute RV of the NEXT 20 trading days (no lookahead — we use
# the next calendar month's first 20 trading days as the forward window)
post_rv = {}
all_dates = spy_ret.index

for i, month_end in enumerate(monthly_index):
    # Forward window: trading days AFTER month_end
    future_days = all_dates[all_dates > month_end]
    if len(future_days) >= 20:
        window = spy_ret.loc[future_days[:20]]
        # Annualized daily RV
        rv = window.std() * np.sqrt(252)
        post_rv[month_end] = rv

post_rv_series = pd.Series(post_rv)

# ─── 4. Classify episodes ────────────────────────────────────────────────────
# "Up crash episode": SPY monthly return >= +5% AND VIX change <= 0%
# (market surged, but VIX didn't go up — options market not getting cheaper,
# with heavy call buying suppressing vol compression)
up_crash_mask = (spy_monthly >= 0.05) & (vix_monthly_change_aligned <= 0.0)

# Strong up + VIX ROSE: market surged but fear gauge went up (normal hedging)
strong_up_vix_rise_mask = (spy_monthly >= 0.05) & (vix_monthly_change_aligned > 0.0)

# All other months
other_mask = ~(spy_monthly >= 0.05)

# Filter to months with available post-RV
valid_months = post_rv_series.index

up_crash_months = monthly_index[up_crash_mask]
up_crash_months = up_crash_months[up_crash_months.isin(valid_months)]

strong_up_vix_rise_months = monthly_index[strong_up_vix_rise_mask]
strong_up_vix_rise_months = strong_up_vix_rise_months[strong_up_vix_rise_months.isin(valid_months)]

other_months = monthly_index[other_mask]
other_months = other_months[other_months.isin(valid_months)]

# Post-RV for each group
up_crash_rv = post_rv_series.loc[up_crash_months]
strong_up_vix_rise_rv = post_rv_series.loc[strong_up_vix_rise_months]
other_rv = post_rv_series.loc[other_months]

# ─── 5. Key stats ────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("KEY STATS — UP CRASH EPISODE ANALYSIS (SPY / QQQ / VIX)")
print("="*65)

print(f"\n--- Up-Crash Episodes (SPY ≥ +5% AND VIX change ≤ 0%) ---")
print(f"  Count: {len(up_crash_months)} episodes")
print(f"  Months:")
for m in up_crash_months:
    spy_r = spy_monthly.loc[m]
    vix_c = vix_monthly_change_aligned.loc[m]
    vix_lvl = vix_monthly_avg_aligned.loc[m]
    post_r = post_rv_series.loc[m] if m in post_rv_series.index else float('nan')
    print(f"    {m.strftime('%Y-%m')}: SPY={spy_r:+.1%}, VIX_chg={vix_c:+.1%}, "
          f"VIX_avg={vix_lvl:.1f}, Next20d_RV={post_r:.1%}")

print(f"\n  Post-episode 20d Realized Vol:")
print(f"    Mean : {up_crash_rv.mean():.3f} ({up_crash_rv.mean()*100:.1f}%)")
print(f"    Median: {up_crash_rv.median():.3f} ({up_crash_rv.median()*100:.1f}%)")
print(f"    Min  : {up_crash_rv.min():.3f} ({up_crash_rv.min()*100:.1f}%)")
print(f"    Max  : {up_crash_rv.max():.3f} ({up_crash_rv.max()*100:.1f}%)")

print(f"\n--- Strong Up + VIX Rose (SPY ≥ +5% but VIX change > 0%) ---")
print(f"  Count: {len(strong_up_vix_rise_months)} months")
print(f"  Post-episode 20d Realized Vol:")
print(f"    Mean : {strong_up_vix_rise_rv.mean():.3f} ({strong_up_vix_rise_rv.mean()*100:.1f}%)")
print(f"    Median: {strong_up_vix_rise_rv.median():.3f} ({strong_up_vix_rise_rv.median()*100:.1f}%)")

print(f"\n--- All Other Months (SPY < +5%) ---")
print(f"  Count: {len(other_months)} months")
print(f"  Post-episode 20d Realized Vol:")
print(f"    Mean : {other_rv.mean():.3f} ({other_rv.mean()*100:.1f}%)")
print(f"    Median: {other_rv.median():.3f} ({other_rv.median()*100:.1f}%)")

# T-test: up crash vs other months
t_stat, p_val = stats.ttest_ind(up_crash_rv.values, other_rv.values, equal_var=False)
print(f"\n  T-test (up crash vs other months):")
print(f"    t-stat: {t_stat:.3f}")
print(f"    p-value: {p_val:.4f}")
if p_val < 0.05:
    print(f"    → Statistically significant difference (p < 0.05)")
else:
    print(f"    → Not statistically significant (p ≥ 0.05)")

# T-test: up crash vs strong-up-VIX-rose
t_stat2, p_val2 = stats.ttest_ind(up_crash_rv.values, strong_up_vix_rise_rv.values, equal_var=False)
print(f"\n  T-test (up crash vs strong-up + VIX rose):")
print(f"    t-stat: {t_stat2:.3f}")
print(f"    p-value: {p_val2:.4f}")

print("\n" + "="*65)

# ─── 6. Chart 1: Scatter — QQQ return vs VIX change, colored by post-RV ─────
print("\nGenerating Chart 1: Scatter plot...")

# Build a combined df for scatter
scatter_df = pd.DataFrame({
    'qqq_ret': qqq_monthly,
    'vix_change': vix_monthly_change_aligned,
    'spy_ret': spy_monthly,
    'vix_avg': vix_monthly_avg_aligned,
}, index=monthly_index)

scatter_df = scatter_df.dropna()
scatter_df = scatter_df.join(post_rv_series.rename('post_rv'), how='left').dropna()

# Classify each point
def classify(row):
    if row['spy_ret'] >= 0.05 and row['vix_change'] <= 0.0:
        return 'up_crash'
    elif row['spy_ret'] >= 0.05:
        return 'strong_up_vix_rise'
    else:
        return 'other'

scatter_df['group'] = scatter_df.apply(classify, axis=1)

fig1, ax1 = plt.subplots(figsize=(10, 7))

# Color by post-RV intensity
vmin = scatter_df['post_rv'].quantile(0.05)
vmax = scatter_df['post_rv'].quantile(0.95)

# Plot non-up-crash months first (background)
non_uc = scatter_df[scatter_df['group'] != 'up_crash']
sc = ax1.scatter(
    non_uc['qqq_ret'] * 100,
    non_uc['vix_change'] * 100,
    c=non_uc['post_rv'],
    cmap='RdYlGn_r',
    vmin=vmin, vmax=vmax,
    alpha=0.55, s=45, zorder=2
)

# Up-crash episodes highlighted
uc = scatter_df[scatter_df['group'] == 'up_crash']
ax1.scatter(
    uc['qqq_ret'] * 100,
    uc['vix_change'] * 100,
    c=uc['post_rv'],
    cmap='RdYlGn_r',
    vmin=vmin, vmax=vmax,
    alpha=0.95, s=160, zorder=4,
    edgecolors='black', linewidths=1.5
)

# Label up-crash episodes
for idx, row in uc.iterrows():
    ax1.annotate(
        idx.strftime('%Y-%m'),
        xy=(row['qqq_ret'] * 100, row['vix_change'] * 100),
        xytext=(7, 4),
        textcoords='offset points',
        fontsize=8, color='#222222', fontweight='bold'
    )

# Reference lines
ax1.axhline(0, color='gray', linewidth=0.8, linestyle='--', alpha=0.6)
ax1.axvline(5, color='gray', linewidth=0.8, linestyle='--', alpha=0.6)

# Shade the up-crash quadrant
ax1.axvspan(5, ax1.get_xlim()[1] if ax1.get_xlim()[1] > 5 else 20,
            alpha=0.06, color='red', ymin=0, ymax=0.5)

cbar = plt.colorbar(sc, ax=ax1)
cbar.set_label('後 20 交易日 Realized Vol（年化）', fontsize=10)
cbar.ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:.0%}'))

ax1.set_xlabel('QQQ 當月報酬率 (%)', fontsize=12)
ax1.set_ylabel('VIX 月均值變化率 (%)', fontsize=12)
ax1.set_title('QQQ 月報酬 vs VIX 月變化\n顏色 = 後 20 交易日 Realized Vol；黑框 = Up-Crash 事件',
              fontsize=13, fontweight='bold')

# Legend
legend_elements = [
    mpatches.Patch(facecolor='black', edgecolor='black', label=f'Up-Crash episodes (n={len(uc)})'),
    mpatches.Patch(facecolor='lightgray', edgecolor='gray', label='其他月份'),
]
ax1.legend(handles=legend_elements, loc='upper left', fontsize=9)

ax1.grid(True, alpha=0.3)
fig1.tight_layout()
chart1_path = os.path.join(OUTPUT_DIR, 'upcrash_scatter.png')
fig1.savefig(chart1_path, dpi=150, bbox_inches='tight')
plt.close(fig1)
print(f"Chart 1 saved: {chart1_path}")

# ─── 7. Chart 2: Box plot — three groups post-20d RV ─────────────────────────
print("Generating Chart 2: Box plot...")

fig2, ax2 = plt.subplots(figsize=(9, 6))

data_groups = [up_crash_rv.values * 100,
               strong_up_vix_rise_rv.values * 100,
               other_rv.values * 100]
labels = [
    f'Up-Crash\n(SPY≥+5%,\nVIX↓)\nn={len(up_crash_rv)}',
    f'強漲+VIX升\n(SPY≥+5%,\nVIX↑)\nn={len(strong_up_vix_rise_rv)}',
    f'一般月份\n(SPY<+5%)\nn={len(other_rv)}'
]
colors = ['#d73027', '#fc8d59', '#91bfdb']

bp = ax2.boxplot(data_groups, labels=labels, patch_artist=True,
                 medianprops=dict(color='black', linewidth=2),
                 whiskerprops=dict(linewidth=1.5),
                 flierprops=dict(marker='o', markerfacecolor='gray', markersize=5, alpha=0.5))

for patch, color in zip(bp['boxes'], colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.75)

# Add mean dots
means = [np.mean(g) for g in data_groups]
ax2.scatter([1, 2, 3], means, marker='D', color='black', zorder=5, s=50, label='平均值')

# Annotate means
for i, (mean, group) in enumerate(zip(means, data_groups)):
    ax2.annotate(f'平均: {mean:.1f}%',
                xy=(i+1, mean),
                xytext=(20, 5), textcoords='offset points',
                fontsize=9, color='black',
                arrowprops=dict(arrowstyle='->', color='black', lw=1))

ax2.set_ylabel('後 20 交易日 Realized Vol（年化, %）', fontsize=12)
ax2.set_title('不同市場情境下的後 20 日 Realized Vol 分布\nSPY 2014-2026',
              fontsize=13, fontweight='bold')
ax2.legend(fontsize=10)
ax2.grid(True, alpha=0.3, axis='y')

# Add significance annotation
if p_val < 0.1:
    sig_text = f'Up-Crash vs 一般: p={p_val:.3f}' + ('*' if p_val < 0.05 else '†')
    ax2.text(0.02, 0.97, sig_text, transform=ax2.transAxes,
             fontsize=9, va='top', color='darkred',
             bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow', alpha=0.8))

fig2.tight_layout()
chart2_path = os.path.join(OUTPUT_DIR, 'upcrash_boxplot.png')
fig2.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close(fig2)
print(f"Chart 2 saved: {chart2_path}")

# ─── 8. Summary for article ──────────────────────────────────────────────────
print("\n" + "="*65)
print("ARTICLE-READY SUMMARY")
print("="*65)
print(f"\nUp-Crash 事件（SPY月漲≥+5% 且 VIX月均變化≤0%）：")
print(f"  2014-2026 共發生 {len(up_crash_months)} 次")
print(f"  後 20 交易日 RV 平均 = {up_crash_rv.mean()*100:.1f}%（年化）")
print(f"  後 20 交易日 RV 中位 = {up_crash_rv.median()*100:.1f}%（年化）")
print(f"\n對照組A（強漲 + VIX 升）：{len(strong_up_vix_rise_months)} 個月")
print(f"  後 20 交易日 RV 平均 = {strong_up_vix_rise_rv.mean()*100:.1f}%")
print(f"\n對照組B（一般月份）：{len(other_months)} 個月")
print(f"  後 20 交易日 RV 平均 = {other_rv.mean()*100:.1f}%")
print(f"\nUp-Crash vs 一般月份: t={t_stat:.2f}, p={p_val:.4f}")
print(f"Up-Crash vs 強漲+VIX升: t={t_stat2:.2f}, p={p_val2:.4f}")
print("\n所有數字來源：yfinance (SPY, QQQ, ^VIX), 計算日期 2026-05-18")
print("="*65)
