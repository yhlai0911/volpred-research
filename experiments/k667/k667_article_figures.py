"""K667 Article Figures — research-audience article
Generates 3 publication-quality PNG figures for the K667 VT insurance cost analysis.
"""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path

# Load results
results_path = Path(__file__).parent / "k667_results.json"
with open(results_path) as f:
    data = json.load(f)

# Font fallbacks (Chinese support)
plt.rcParams['font.family'] = ['Heiti TC', 'Apple LiGothic Medium', 'Arial Unicode MS',
                                'DejaVu Sans', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

OUT_DIR = Path(__file__).parent
PERIOD = "2006-01-04 至 2026-03-27（20.2年，5,089 交易日）"
SOURCE = "資料來源：yfinance SPY/GLD/VIX；實驗 K667"

COLORS = {
    'BH_SPY': '#D62728',          # red
    '12/VIX_SPY': '#FF7F0E',      # orange
    'BH_50/50': '#2CA02C',        # green
    '50/50+VT': '#1F77B4',        # blue
    'BH_60/40': '#9467BD',        # purple
    'ATM_PUT': '#8C564B',         # brown
}

# ── Figure 1: Premium vs MDD Reduction scatter ──────────────────────────────
fig1, ax1 = plt.subplots(figsize=(9, 6))

# Strategies from insurance_premiums (use BH_SPY as base for all)
strategies = [
    ('BH_SPY → 12/VIX SPY', 2.505, 27.87, COLORS['12/VIX_SPY'], 'o'),
    ('BH_SPY → BH 50/50', -2.123, 23.45, COLORS['BH_50/50'], 's'),
    ('BH_SPY → 50/50+VT', 1.334, 43.73, COLORS['50/50+VT'], 'D'),
    ('BH_SPY → BH 60/40', -1.843, 21.0, COLORS['BH_60/40'], '^'),
]

# ATM put option — scale MDD improvement proportional to VT (approximate)
atm_premium = 26.1
# ATM put roughly similar MDD protection to 12/VIX_SPY
ax1.scatter(atm_premium, 27.87, s=180, color=COLORS['ATM_PUT'], marker='P',
            zorder=5, label='ATM Put Option (估算)', edgecolors='black', linewidths=0.8)
ax1.annotate('ATM Put\n(26.1%/yr)', (atm_premium, 27.87),
             xytext=(22.5, 24), fontsize=9,
             arrowprops=dict(arrowstyle='->', color='gray', lw=0.8))

for name, prem, mdd_imp, color, marker in strategies:
    ax1.scatter(prem, mdd_imp, s=160, color=color, marker=marker,
                zorder=5, edgecolors='black', linewidths=0.8)
    offset_x = 0.15 if prem >= 0 else -0.15
    ha = 'left' if prem >= 0 else 'right'
    ax1.annotate(name.split(' → ')[1].replace(' ', '\n', 1),
                 (prem, mdd_imp), xytext=(prem + offset_x, mdd_imp + 1.5),
                 fontsize=8.5, ha=ha)

ax1.axvline(0, color='gray', lw=0.8, linestyle='--', alpha=0.5)
ax1.axhline(0, color='gray', lw=0.8, linestyle='--', alpha=0.5)

ax1.set_xlabel('年化保費（%，正值 = 為保護付出的報酬損失）', fontsize=11)
ax1.set_ylabel('MDD 改善幅度（百分點，vs BH SPY）', fontsize=11)
ax1.set_title('Portfolio Protection Cost-Efficiency\n各策略年化保費 vs MDD 改善效果', fontsize=12)

ax1.annotate(f'* 右下象限 = 高保費低保護（較差）\n* 左上象限 = 負保費（本身就更好）\n* 右上象限 = 正保費高保護',
             xy=(0.02, 0.98), xycoords='axes fraction',
             va='top', fontsize=8, color='gray')

ax1.set_xlim(-5, 30)
ax1.set_ylim(0, 50)
ax1.grid(alpha=0.3)

fig1.text(0.5, 0.01, f'{SOURCE}；{PERIOD}', ha='center', fontsize=8, color='gray')
fig1.tight_layout(rect=[0, 0.04, 1, 1])
fig1.savefig(OUT_DIR / 'k667_article_fig1.png', dpi=150, bbox_inches='tight')
print("Saved fig1: k667_article_fig1.png")
plt.close()

# ── Figure 2: Break-even crisis frequency ────────────────────────────────────
fig2, ax2 = plt.subplots(figsize=(8, 5))

# Break-even analysis: how often do crises need to occur for premium to break even?
strategies_be = [
    ('12/VIX SPY\n(vs BH SPY)', 2.505, 2.2, COLORS['12/VIX_SPY']),
    ('50/50+VT\n(vs BH SPY)', 1.334, 25.5, COLORS['50/50+VT']),
]

x = np.arange(len(strategies_be))
bars = ax2.bar(x, [s[2] for s in strategies_be],
               color=[s[3] for s in strategies_be],
               width=0.5, edgecolor='black', linewidth=0.8, alpha=0.85)

# Actual historical crisis interval line
historical = 5.0
ax2.axhline(historical, color='#D62728', lw=2.0, linestyle='--',
            label=f'歷史實際 MDD>20% 發生頻率（每 {historical:.0f} 年一次）')

ax2.set_xticks(x)
ax2.set_xticklabels([s[0] for s in strategies_be], fontsize=11)
ax2.set_ylabel('Break-Even 危機間隔（年）\n（保費剛好等於避開損失的最低發生頻率）', fontsize=10)
ax2.set_title('Break-Even Crisis Frequency Analysis\n多少年發生一次危機才「值回保費」', fontsize=12)

for bar, (_, prem, be_yrs, _) in zip(bars, strategies_be):
    ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
             f'{be_yrs:.1f} 年', ha='center', va='bottom', fontsize=12, fontweight='bold')

# Add premium labels
for bar, (name, prem, be_yrs, _) in zip(bars, strategies_be):
    ax2.text(bar.get_x() + bar.get_width()/2, be_yrs/2,
             f'保費 {prem:.2f}%/yr', ha='center', va='center',
             fontsize=9, color='white', fontweight='bold')

ax2.annotate('歷史每 5 年一次\n→ 12/VIX SPY 偏貴（需 2.2 年），\n50/50+VT 超划算（需 25.5 年）',
             xy=(0.5, historical),
             xytext=(0.7, historical + 5),
             xycoords=('data', 'data'),
             fontsize=9, color='#D62728',
             arrowprops=dict(arrowstyle='->', color='#D62728', lw=0.8))

ax2.legend(fontsize=9, loc='upper left')
ax2.set_ylim(0, 32)
ax2.grid(axis='y', alpha=0.3)

fig2.text(0.5, 0.01, f'{SOURCE}；{PERIOD}；危機定義：MDD>20%，歷史共 4 次',
          ha='center', fontsize=8, color='gray')
fig2.tight_layout(rect=[0, 0.04, 1, 1])
fig2.savefig(OUT_DIR / 'k667_article_fig2.png', dpi=150, bbox_inches='tight')
print("Saved fig2: k667_article_fig2.png")
plt.close()

# ── Figure 3: Annual premium time series ─────────────────────────────────────
annual = data['annual_premiums_by_year']
years = [d['year'] for d in annual]
premiums = [d['premium_pct'] for d in annual]

fig3, ax3 = plt.subplots(figsize=(12, 5))

# Color bars: negative = VT earns (crisis, green); positive = VT costs (red)
bar_colors = ['#2CA02C' if p < 0 else '#D62728' for p in premiums]
bars = ax3.bar(years, premiums, color=bar_colors, edgecolor='black',
               linewidth=0.4, alpha=0.8, width=0.7)

ax3.axhline(0, color='black', lw=0.8)

# Mark mean
mean_prem = 3.696
ax3.axhline(mean_prem, color='#1F77B4', lw=1.5, linestyle='--',
            label=f'年化平均保費 {mean_prem:.2f}%/yr（t={2.245:.3f}, p={0.037:.3f}）')

# Annotate crisis years
crisis_years_detail = {
    2008: 'GFC',
    2018: '美股拋售',
    2022: '升息熊市',
}
for year, label in crisis_years_detail.items():
    idx = years.index(year)
    p = premiums[idx]
    ax3.annotate(label, (year, p - 0.5),
                 xytext=(year, p - 3), ha='center', fontsize=8, color='#2CA02C',
                 arrowprops=dict(arrowstyle='->', color='#2CA02C', lw=0.7))

ax3.set_xlabel('年份', fontsize=11)
ax3.set_ylabel('年化保費（%）\n正值 = VT 策略落後 BH SPY（付出保費）\n負值 = VT 表現超越 BH（賺回保費）',
               fontsize=9)
ax3.set_title('K667: Annual VT Insurance Premium by Year（12/VIX SPY vs BH SPY）\n逐年保費：平均 3.70%/yr，危機年份負保費（VT 賺回）', fontsize=12)

ax3.legend(fontsize=9, loc='upper right')
ax3.set_xticks(years)
ax3.set_xticklabels(years, rotation=45, ha='right', fontsize=8)
ax3.grid(axis='y', alpha=0.3)

# Add VT costs/earns annotation
ax3.text(0.02, 0.95, f'17/20 年 VT 付出保費；3/20 年危機負保費',
         transform=ax3.transAxes, fontsize=9, va='top', color='gray')

fig3.text(0.5, 0.01, f'{SOURCE}；{PERIOD}；20 年資料，共 {len(annual)} 個年度觀測值',
          ha='center', fontsize=8, color='gray')
fig3.tight_layout(rect=[0, 0.04, 1, 1])
fig3.savefig(OUT_DIR / 'k667_article_fig3.png', dpi=150, bbox_inches='tight')
print("Saved fig3: k667_article_fig3.png")
plt.close()

print("\nAll 3 figures saved to experiments/k667/")
