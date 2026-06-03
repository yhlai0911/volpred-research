#!/usr/bin/env python3
"""
K573 Efficiency Frontier Figure
Generates: experiments/k573/figures/efficiency_frontier.png

X-axis: MDD 改善幅度 (pp)
Y-axis: CAGR 犧牲比例 (%/yr)
Three strategies plotted with breakeven VIX labels.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# --- Data from k573_insurance_pricing_results.json ---
strategies = {
    '12/VIX\n(標準型)': {
        'mdd_improvement': 19.8,
        'cagr_cost': 4.27,
        'efficiency': 4.64,
        'breakeven_vix': 26.6,
        'color': '#2c7bb6',
        'marker': 'o',
        'size': 200,
    },
    'Piecewise\n(保守型)': {
        'mdd_improvement': 10.92,
        'cagr_cost': 7.88,
        'efficiency': 1.39,
        'breakeven_vix': 25.7,
        'color': '#d7191c',
        'marker': 's',
        'size': 200,
    },
    'VIX-Conditional\nLeverage': {
        'mdd_improvement': 7.60,
        'cagr_cost': 0.29,
        'efficiency': 26.21,
        'breakeven_vix': 32.4,
        'color': '#1a9641',
        'marker': '^',
        'size': 220,
    },
}

fig, ax = plt.subplots(figsize=(9, 6.5))
fig.patch.set_facecolor('#fafafa')
ax.set_facecolor('#fafafa')

# Plot each strategy
for name, s in strategies.items():
    ax.scatter(
        s['mdd_improvement'],
        s['cagr_cost'],
        s=s['size'],
        c=s['color'],
        marker=s['marker'],
        zorder=5,
        edgecolors='white',
        linewidths=1.5,
        label=None,
    )
    # Annotation with breakeven VIX
    offset_x = {
        '12/VIX\n(標準型)': 0.4,
        'Piecewise\n(保守型)': -3.5,
        'VIX-Conditional\nLeverage': 0.3,
    }
    offset_y = {
        '12/VIX\n(標準型)': 0.35,
        'Piecewise\n(保守型)': -0.55,
        'VIX-Conditional\nLeverage': 0.3,
    }
    ha = {
        '12/VIX\n(標準型)': 'left',
        'Piecewise\n(保守型)': 'left',
        'VIX-Conditional\nLeverage': 'left',
    }
    label_text = f"{name.replace(chr(10), ' ')}\n效率: {s['efficiency']:.1f} pp/pp\n損益平衡 VIX: {s['breakeven_vix']}"
    ax.annotate(
        label_text,
        xy=(s['mdd_improvement'], s['cagr_cost']),
        xytext=(s['mdd_improvement'] + offset_x[name], s['cagr_cost'] + offset_y[name]),
        fontsize=9,
        color=s['color'],
        fontweight='bold',
        ha=ha[name],
        va='bottom',
        arrowprops=dict(arrowstyle='-', color=s['color'], lw=1.0),
    )

# Draw efficiency iso-curves (constant pp MDD per pp CAGR)
mdd_range = np.linspace(0.5, 25, 300)
for eff, ls, alpha, lbl in [
    (1.39, ':', 0.5, 'Efficiency = 1.39 (Piecewise)'),
    (4.64, '--', 0.6, 'Efficiency = 4.64 (12/VIX)'),
    (26.21, '-.', 0.5, 'Efficiency = 26.21 (Leverage)'),
]:
    cagr_curve = mdd_range / eff
    ax.plot(mdd_range, cagr_curve, ls=ls, color='gray', alpha=alpha, linewidth=1)

# Add "better" region arrow annotation
ax.annotate(
    '← 更低成本\n↓ 更大 MDD 保護',
    xy=(2.5, 0.8),
    fontsize=8,
    color='#555',
    style='italic',
)

# Labels, ticks, grid
ax.set_xlabel('MDD 改善幅度（百分點）', fontsize=12, labelpad=8)
ax.set_ylabel('CAGR 犧牲比例（%/yr）', fontsize=12, labelpad=8)
ax.set_title(
    'K573：三種 VT 策略效率前緣\nMDD 改善 vs. CAGR 成本',
    fontsize=13, fontweight='bold', pad=12
)

ax.set_xlim(0, 26)
ax.set_ylim(-0.5, 10)
ax.grid(True, linestyle='--', alpha=0.4)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

# Legend patches
patches = [
    mpatches.Patch(color=s['color'], label=name.replace('\n', ' '))
    for name, s in strategies.items()
]
ax.legend(handles=patches, loc='upper right', fontsize=9, framealpha=0.8)

# Footer note
fig.text(
    0.5, 0.01,
    '資料：yfinance，期間 2005-01-04 至 2026-03-26，5,340 交易日。'
    '效率 = MDD 改善幅度(pp) ÷ CAGR 犧牲比例(%)',
    ha='center', fontsize=7.5, color='#777'
)

plt.tight_layout(rect=[0, 0.04, 1, 1])
out_path = 'experiments/k573/figures/efficiency_frontier.png'
plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='#fafafa')
print(f"Saved: {out_path}")
