"""Generate charts for K772 overnight volatility article."""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# Load results
with open('/Users/yhlai0911/Desktop/volpred-research/experiments/k772/k772_overnight_vol_results.json') as f:
    results = json.load(f)

OUT = '/Users/yhlai0911/Desktop/volpred-research/storage/reports/k772_charts/'

# ─── Fig A: Annualized vol bar chart (overnight vs intraday vs total) ────────
fig, ax = plt.subplots(figsize=(7, 4))

labels = ['全天波動率', '盤中波動率', '隔夜波動率']
vals   = [
    results['part_a_variance_decomposition']['annualized_vol_total'] * 100,
    results['part_a_variance_decomposition']['annualized_vol_intraday'] * 100,
    results['part_a_variance_decomposition']['annualized_vol_overnight'] * 100,
]
colors = ['#2c7bb6', '#1a9641', '#d7191c']

bars = ax.bar(labels, vals, color=colors, width=0.5, edgecolor='white', linewidth=0.8)
for bar, v in zip(bars, vals):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
            f'{v:.1f}%', ha='center', va='bottom', fontsize=11, fontweight='bold')

ax.set_ylabel('年化波動率 (%)', fontsize=11)
ax.set_title('SPY 波動率分解：全天 vs 盤中 vs 隔夜（2007-2026）', fontsize=12, pad=10)
ax.set_ylim(0, 24)
ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f%%'))
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.tick_params(labelsize=10)

# Add annotation
ax.text(2, vals[2] + 1.8,
        f'隔夜佔總變異數\n36.8%',
        ha='center', fontsize=9, color='#d7191c',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='#fff0f0', edgecolor='#d7191c', alpha=0.8))

fig.tight_layout()
fig.savefig(OUT + 'fig_a_vol_decomp.png', dpi=150, bbox_inches='tight')
plt.close()
print('fig_a done')

# ─── Fig B: Rolling overnight share by year ───────────────────────────────────
fig, ax = plt.subplots(figsize=(9, 4.5))

yearly = results['part_b_time_varying']['yearly']
years  = [int(y) for y in yearly.keys()]
shares = [v * 100 for v in yearly.values()]

ax.plot(years, shares, color='#2c7bb6', linewidth=2, marker='o', markersize=5, markerfacecolor='white', markeredgewidth=1.5)
ax.fill_between(years, shares, alpha=0.15, color='#2c7bb6')

# Average line
avg = results['part_b_time_varying']['mean_overnight_fraction'] * 100
ax.axhline(avg, color='gray', linestyle='--', linewidth=1.2, label=f'長期均值 {avg:.1f}%')

# Annotate key years
highlights = {
    2020: (52.8, '#d7191c', 'COVID-19\n52.8%'),
    2016: (47.8, '#ff7f00', '2016\n47.8%'),
    2018: (25.1, '#1a9641', '2018\n25.1%'),
    2008: (32.5, '#7b2d8b', '2008 GFC\n32.5%'),
}
for yr, (pct, clr, lbl) in highlights.items():
    if yr in years:
        idx = years.index(yr)
        offset_y = 3.5 if pct > avg else -5.5
        ax.annotate(lbl, xy=(yr, pct), xytext=(yr, pct + offset_y),
                    fontsize=8, color=clr, ha='center',
                    arrowprops=dict(arrowstyle='->', color=clr, lw=1.2))

ax.set_ylabel('隔夜佔總波動率比例 (%)', fontsize=11)
ax.set_xlabel('年份', fontsize=11)
ax.set_title('SPY 隔夜波動率佔比逐年變化（252 日滾動平均）', fontsize=12, pad=10)
ax.set_xlim(2007, 2027)
ax.set_ylim(15, 65)
ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f%%'))
ax.legend(fontsize=9, loc='upper left')
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.tick_params(labelsize=10)
ax.set_xticks(years)
ax.set_xticklabels([str(y) for y in years], rotation=45, ha='right')

fig.tight_layout()
fig.savefig(OUT + 'fig_b_yearly_share.png', dpi=150, bbox_inches='tight')
plt.close()
print('fig_b done')

# ─── Fig C: Model QLIKE ranking ───────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(7, 4))

models_raw = results['part_d_model_comparison']['ranking']
qlike_map  = {k: v['qlike'] for k, v in results['part_d_model_comparison']['metrics'].items()}

# Exclude har_oc_ext (degenerate)
models_show = [m for m in models_raw if m != 'har_oc_ext']
qlikes_show = [qlike_map[m] for m in models_show]

labels_nice = {
    'amem':    'AMEM',
    'gjr':     'GJR-GARCH',
    'har_oc':  'HAR-OC',
    'ewma':    'EWMA',
    'har_rv2': 'HAR-RV',
}
nice = [labels_nice[m] for m in models_show]

colors_bar = ['#d7191c' if i == 0 else '#2c7bb6' for i in range(len(models_show))]

bars = ax.barh(nice[::-1], qlikes_show[::-1], color=colors_bar[::-1],
               edgecolor='white', height=0.55)

for bar, v in zip(bars, qlikes_show[::-1]):
    ax.text(v + 0.004, bar.get_y() + bar.get_height()/2,
            f'{v:.4f}', va='center', fontsize=9.5)

ax.set_xlabel('QLIKE 損失（越低越好）', fontsize=11)
ax.set_title('6 個模型 QLIKE 排名（樣本外 2011-2026）', fontsize=12, pad=10)
ax.set_xlim(1.48, 1.72)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.tick_params(labelsize=10)

# Note about AMEM vs GJR
ax.text(0.98, 0.06,
        '* AMEM vs GJR 差異 p=0.035\n  但未通過 Harvey 修正（邊際）',
        transform=ax.transAxes, ha='right', fontsize=8, color='gray',
        style='italic')

fig.tight_layout()
fig.savefig(OUT + 'fig_c_model_qlike.png', dpi=150, bbox_inches='tight')
plt.close()
print('fig_c done')
print('All charts saved to', OUT)
