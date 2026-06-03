"""
K653 Figure Generator — wealth_paths.png and sharpe_mdd_scatter.png
"""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import os

# Load results
results_path = os.path.join(os.path.dirname(__file__), '..', 'k653_results.json')
with open(results_path) as f:
    r = json.load(f)

behavioral = r['behavioral_results']
bootstrap_sig = r['bootstrap_significance']

# ─── Labels & colors ───────────────────────────────────────────────────────────
labels = {
    'perfect_follower': 'Perfect Follower\n(嚴格執行 12/VIX)',
    'news_reactor':     'News Reactor\n(VIX spike 減半配置)',
    'overrider':        'Overrider\n(VIX>25 全現金)',
    'performance_chaser': 'Performance Chaser\n(追漲殺跌)',
    'panic_seller':     'Panic Seller\n(跌3%清倉)',
    'lazy_rebalancer':  'Lazy Rebalancer\n(拖延再平衡)',
}
colors = {
    'perfect_follower':   '#2196F3',   # blue — baseline
    'news_reactor':       '#4CAF50',   # green — winner
    'overrider':          '#8BC34A',   # light green — 2nd
    'performance_chaser': '#FF9800',   # orange
    'panic_seller':       '#F44336',   # red
    'lazy_rebalancer':    '#9C27B0',   # purple — worst
}

order = ['news_reactor', 'overrider', 'perfect_follower', 'performance_chaser', 'panic_seller', 'lazy_rebalancer']

# ─── Figure 1: Terminal Wealth + Sharpe bar chart ──────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(14, 7))
fig.suptitle('K653: 六種投資行為模擬結果\n(SPY/GLD 50/50 + 12/VIX 再平衡策略, 2010–2026)', fontsize=14, fontweight='bold')

# Left: Terminal Wealth
ax1 = axes[0]
tw_vals = [behavioral[k]['terminal_wealth'] / 1e3 for k in order]
bar_colors = [colors[k] for k in order]
short_labels = [
    'News Reactor', 'Overrider', 'Perfect\nFollower', 'Perf.\nChaser', 'Panic\nSeller', 'Lazy\nRebalancer'
]
bars = ax1.bar(short_labels, tw_vals, color=bar_colors, edgecolor='white', linewidth=0.8, alpha=0.9)

# Annotate bars with value + significance
sig_map = {
    'news_reactor':       '***',
    'overrider':          '',
    'performance_chaser': '',
    'panic_seller':       '',
    'lazy_rebalancer':    '***',
}
for i, (bar, k) in enumerate(zip(bars, order)):
    h = bar.get_height()
    sig = sig_map.get(k, '')
    ax1.text(bar.get_x() + bar.get_width()/2, h + 5, f'${h:.0f}K\n{sig}',
             ha='center', va='bottom', fontsize=8.5, fontweight='bold' if sig else 'normal')

# Baseline line
baseline_tw = behavioral['perfect_follower']['terminal_wealth'] / 1e3
ax1.axhline(baseline_tw, color='#2196F3', linestyle='--', linewidth=1.5, alpha=0.7, label=f'Perfect Follower = ${baseline_tw:.0f}K')
ax1.set_ylabel('Terminal Wealth (千美元, 初始 $100K)', fontsize=11)
ax1.set_title('到期財富比較（2010–2026）', fontsize=12)
ax1.legend(fontsize=9)
ax1.set_ylim(0, max(tw_vals) * 1.15)
ax1.tick_params(axis='x', labelsize=9)

# Right: Sharpe ratio bars
ax2 = axes[1]
sharpe_vals = [behavioral[k]['sharpe'] for k in order]
bars2 = ax2.bar(short_labels, sharpe_vals, color=bar_colors, edgecolor='white', linewidth=0.8, alpha=0.9)
for bar, v in zip(bars2, sharpe_vals):
    ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02, f'{v:.3f}',
             ha='center', va='bottom', fontsize=9, fontweight='bold')
ax2.axhline(behavioral['perfect_follower']['sharpe'], color='#2196F3', linestyle='--', linewidth=1.5, alpha=0.7,
            label=f'Perfect Follower = {behavioral["perfect_follower"]["sharpe"]:.3f}')
ax2.set_ylabel('年化 Sharpe 比率 (年化 252 日)', fontsize=11)
ax2.set_title('Sharpe 比率比較', fontsize=12)
ax2.legend(fontsize=9)
ax2.set_ylim(0, max(sharpe_vals) * 1.15)
ax2.tick_params(axis='x', labelsize=9)

# Footnote
fig.text(0.5, 0.01, '*** = bootstrap t 檢定 p<0.001 (n=10,000, block_size=20)；正號表示 News Reactor/Overrider 財富顯著高於 Perfect Follower',
         ha='center', fontsize=8, style='italic', color='gray')

plt.tight_layout(rect=[0, 0.04, 1, 0.96])
out1 = os.path.join(os.path.dirname(__file__), 'wealth_paths.png')
plt.savefig(out1, dpi=120, bbox_inches='tight')
plt.close()
print(f"Saved: {out1}")

# ─── Figure 2: Sharpe vs |MDD| scatter ────────────────────────────────────────
fig2, ax = plt.subplots(figsize=(10, 7))

for k in order:
    beh = behavioral[k]
    sharpe = beh['sharpe']
    mdd_abs = abs(beh['mdd']) * 100   # convert to percent
    color = colors[k]
    label_str = labels[k].replace('\n', ' ')

    # Highlight the two key strategies
    if k in ('news_reactor', 'perfect_follower'):
        marker = 'D'
        ms = 160
        edge = 'black'
        lw = 1.5
    elif k == 'lazy_rebalancer':
        marker = 'X'
        ms = 160
        edge = 'black'
        lw = 1.5
    else:
        marker = 'o'
        ms = 100
        edge = color
        lw = 0.5

    ax.scatter(mdd_abs, sharpe, s=ms, color=color, edgecolors=edge, linewidths=lw,
               marker=marker, zorder=5, alpha=0.92)

    # Label offsets (avoid overlap)
    offsets = {
        'news_reactor': (-0.4, 0.04),
        'perfect_follower': (0.1, 0.03),
        'overrider': (0.1, 0.02),
        'performance_chaser': (0.05, -0.08),
        'panic_seller': (-1.1, -0.07),
        'lazy_rebalancer': (0.05, 0.04),
    }
    dx, dy = offsets.get(k, (0.05, 0.03))
    ax.annotate(label_str, (mdd_abs, sharpe),
                xytext=(mdd_abs + dx, sharpe + dy),
                fontsize=9, color=color,
                fontweight='bold' if k in ('news_reactor', 'perfect_follower', 'lazy_rebalancer') else 'normal')

# Arrow from Perfect Follower to News Reactor
pf_mdd = abs(behavioral['perfect_follower']['mdd']) * 100
pf_sh  = behavioral['perfect_follower']['sharpe']
nr_mdd = abs(behavioral['news_reactor']['mdd']) * 100
nr_sh  = behavioral['news_reactor']['sharpe']
ax.annotate('', xy=(nr_mdd, nr_sh), xytext=(pf_mdd, pf_sh),
            arrowprops=dict(arrowstyle='->', color='gray', lw=1.5, linestyle='dashed'))
ax.text((pf_mdd + nr_mdd)/2 - 0.9, (pf_sh + nr_sh)/2 + 0.02,
        '更低回撤\n+更高 Sharpe', fontsize=8.5, color='gray', ha='center')

ax.set_xlabel('最大回撤幅度 |MDD| (%)', fontsize=12)
ax.set_ylabel('年化 Sharpe 比率', fontsize=12)
ax.set_title('K653: Sharpe vs 最大回撤 散點圖\n六種投資行為比較（D=菱形=重點策略，X=最差）', fontsize=13, fontweight='bold')

# Ideal quadrant annotation
ax.axvline(pf_mdd, color='#2196F3', linestyle=':', alpha=0.4, linewidth=1)
ax.axhline(pf_sh,  color='#2196F3', linestyle=':', alpha=0.4, linewidth=1)
ax.text(nr_mdd - 0.3, 1.15, '理想區間\n(低回撤 + 高 Sharpe)', fontsize=8, color='gray', ha='right')

# Legend
patches = [mpatches.Patch(color=colors[k], label=labels[k].replace('\n', ' ')) for k in order]
ax.legend(handles=patches, fontsize=8.5, loc='lower right')

fig2.text(0.5, 0.01, '資料來源：yfinance SPY/GLD/^VIX；期間 2010-01-01 至 2026-03-27（4,081 交易日）；初始財富 $100,000',
          ha='center', fontsize=8, style='italic', color='gray')

plt.tight_layout(rect=[0, 0.04, 1, 1])
out2 = os.path.join(os.path.dirname(__file__), 'sharpe_mdd_scatter.png')
plt.savefig(out2, dpi=120, bbox_inches='tight')
plt.close()
print(f"Saved: {out2}")

print("All figures generated successfully.")
