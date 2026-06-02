"""
Generate cross-section skew bar chart for trending_repost article
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

# Data from fetch_iv_skew.py output
data = {
    'ticker': ['META', 'GOOGL', 'MSFT', 'AMZN', 'NVDA', 'SPY'],
    'skew_vol_pts': [-5.29, -1.52, -0.69, -0.61, -1.01, 9.47],
    'atm_iv': [35.37, 32.91, 32.58, 32.70, 41.72, 12.97],
    'rv_30d': [26.85, 28.70, 32.26, 24.54, 40.86, 9.51],
    'iv_rv_ratio': [1.317, 1.147, 1.010, 1.333, 1.021, 1.364],
}
df = pd.DataFrame(data)

fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
fig.suptitle('AI Mega-Cap Options: IV Skew & Vol Premium\n(Snapshot 2026-06-03, 25-30 days to expiry)',
             fontsize=12, fontweight='bold', y=1.02)

# --- Chart 1: 25Δ Put-Call Skew (vol pts) ---
ax1 = axes[0]
colors = ['#E63946' if t == 'SPY' else '#457B9D' for t in df['ticker']]
bars = ax1.bar(df['ticker'], df['skew_vol_pts'], color=colors, edgecolor='white', linewidth=0.8)

ax1.axhline(0, color='black', linewidth=0.8, linestyle='--', alpha=0.6)
ax1.set_ylabel('Put IV − Call IV (vol points, %)', fontsize=10)
ax1.set_title('25Δ Put−Call Skew\n(put at 90% spot vs call at 110% spot)', fontsize=10)
ax1.set_xlabel('Ticker', fontsize=10)

# Add value labels
for bar, val in zip(bars, df['skew_vol_pts']):
    y_pos = val + 0.2 if val >= 0 else val - 0.5
    ax1.text(bar.get_x() + bar.get_width()/2, y_pos, f'{val:+.1f}',
             ha='center', va='bottom' if val >= 0 else 'top', fontsize=9, fontweight='bold')

# Annotations
ax1.annotate('Call skew:\nmarket bids up upside',
             xy=(-0.1, -5.29), xytext=(1.5, -7.5),
             fontsize=7.5, color='#457B9D',
             arrowprops=dict(arrowstyle='->', color='#457B9D', lw=0.8))
ax1.annotate('SPY baseline:\nput premium = crash insurance',
             xy=(5, 9.47), xytext=(3.2, 10.5),
             fontsize=7.5, color='#E63946',
             arrowprops=dict(arrowstyle='->', color='#E63946', lw=0.8))

# Legend
spy_patch = mpatches.Patch(color='#E63946', label='SPY (baseline)')
ai_patch = mpatches.Patch(color='#457B9D', label='AI Mega-Caps')
ax1.legend(handles=[ai_patch, spy_patch], fontsize=8, loc='upper left')
ax1.set_ylim(-10, 13)
ax1.grid(axis='y', alpha=0.3, linestyle=':')

# --- Chart 2: ATM IV vs 30d Realized Vol (IV-RV bar chart) ---
ax2 = axes[1]
x = np.arange(len(df['ticker']))
width = 0.35

bars_iv = ax2.bar(x - width/2, df['atm_iv'], width, label='ATM IV (%)', color='#1D3557', alpha=0.85)
bars_rv = ax2.bar(x + width/2, df['rv_30d'], width, label='30d RV (%)', color='#A8DADC', alpha=0.85, edgecolor='#457B9D')

ax2.set_ylabel('Volatility (%)', fontsize=10)
ax2.set_title('ATM Implied Vol vs 30-Day Realized Vol\n(IV premium = ATM IV / RV)', fontsize=10)
ax2.set_xticks(x)
ax2.set_xticklabels(df['ticker'])
ax2.set_xlabel('Ticker', fontsize=10)
ax2.legend(fontsize=8)
ax2.grid(axis='y', alpha=0.3, linestyle=':')

# IV/RV ratio annotations
for i, (iv, rv, ratio) in enumerate(zip(df['atm_iv'], df['rv_30d'], df['iv_rv_ratio'])):
    ax2.text(i, max(iv, rv) + 0.8, f'×{ratio:.2f}',
             ha='center', fontsize=8, color='#E63946', fontweight='bold')

ax2.text(0.98, 0.97, '×N = IV/RV ratio', transform=ax2.transAxes,
         fontsize=7.5, ha='right', va='top', color='#E63946',
         bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.8))

plt.tight_layout()
out_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/trending_repost_2026_06_03_ai_capex_skew/chart_skew_crosssection.png'
plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='white')
print(f'Chart saved: {out_path}')
plt.close()
