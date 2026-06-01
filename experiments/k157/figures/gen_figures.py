"""Generate K157 figures for the article."""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import os

# Load results
with open('/Users/yhlai0911/Desktop/volpred-research/experiments/k157/k157_correlation_forecasting_results.json') as f:
    data = json.load(f)

out_dir = '/Users/yhlai0911/Desktop/volpred-research/experiments/k157/figures'
os.makedirs(out_dir, exist_ok=True)

# Figure 1: RMSE comparison across models and pairs
pairs = ['SPY-GLD', 'SPY-TLT', 'GLD-TLT']
models = ['Rolling_22d', 'Rolling_63d', 'EWMA_097', 'DCC_GARCH', 'Regime_Switch']
model_labels = ['Rolling\n22d', 'Rolling\n63d', 'EWMA\n0.97', 'DCC-\nGARCH', 'Regime\nSwitch']

colors = ['#e74c3c', '#e67e22', '#3498db', '#2ecc71', '#9b59b6']

fig, axes = plt.subplots(1, 3, figsize=(14, 5))
fig.suptitle('五種模型相關性預測誤差（RMSE）比較\n樣本外期間：2015–2024，114 個觀測值',
             fontsize=13, fontweight='bold', y=1.02)

for i, pair in enumerate(pairs):
    ax = axes[i]
    rmse_vals = [data['correlation_accuracy'][pair][m]['rmse'] for m in models]
    bars = ax.bar(model_labels, rmse_vals, color=colors, edgecolor='white', linewidth=0.5)

    # Highlight best model
    best_idx = np.argmin(rmse_vals)
    bars[best_idx].set_edgecolor('#000000')
    bars[best_idx].set_linewidth(2.5)

    ax.set_title(f'{pair}', fontsize=12, fontweight='bold')
    ax.set_ylabel('RMSE（越低越好）' if i == 0 else '')
    ax.set_ylim(0, max(rmse_vals) * 1.25)

    # Annotate values
    for bar, val in zip(bars, rmse_vals):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.003,
                f'{val:.3f}', ha='center', va='bottom', fontsize=8)

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.set_facecolor('#f8f9fa')

# Add legend for best model
best_patch = mpatches.Patch(facecolor='none', edgecolor='black', linewidth=2.5, label='最佳模型（黑框）')
fig.legend(handles=[best_patch], loc='lower center', ncol=1, fontsize=9, framealpha=0.8)

plt.tight_layout()
plt.savefig(f'{out_dir}/k157_rmse_comparison.png', dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print(f"Saved: {out_dir}/k157_rmse_comparison.png")

# Figure 2: Portfolio Sharpe and MDD comparison (MinVar vs 50/50)
fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
fig.suptitle('最小變異數配置 vs. 等權重 50/50\n樣本外績效比較（2015–2024）',
             fontsize=13, fontweight='bold')

# Sharpe ratios
pair_labels = ['SPY-GLD', 'SPY-TLT', 'GLD-TLT']
sharpe_5050 = [data['portfolio_results'][p]['weights_50_50']['sharpe'] for p in pairs]

# Best MinVar model per pair
best_models = data['best_models']
minvar_keys = {
    'SPY-GLD': f"weights_{best_models['SPY-GLD']}",
    'SPY-TLT': f"weights_{best_models['SPY-TLT']}",
    'GLD-TLT': f"weights_{best_models['GLD-TLT']}",
}
sharpe_minvar = [data['portfolio_results'][p][minvar_keys[p]]['sharpe'] for p in pairs]
mdd_5050 = [abs(data['portfolio_results'][p]['weights_50_50']['max_drawdown']) for p in pairs]
mdd_minvar = [abs(data['portfolio_results'][p][minvar_keys[p]]['max_drawdown']) for p in pairs]

x = np.arange(len(pairs))
width = 0.35

ax1 = axes[0]
b1 = ax1.bar(x - width/2, sharpe_5050, width, label='50/50 等權重', color='#e74c3c', alpha=0.85, edgecolor='white')
b2 = ax1.bar(x + width/2, sharpe_minvar, width, label='最小變異數（最佳模型）', color='#2ecc71', alpha=0.85, edgecolor='white')
ax1.set_ylabel('年化 Sharpe Ratio')
ax1.set_title('Sharpe Ratio（越高越好）')
ax1.set_xticks(x)
ax1.set_xticklabels(pair_labels)
ax1.legend(fontsize=9)
ax1.spines['top'].set_visible(False)
ax1.spines['right'].set_visible(False)
ax1.set_facecolor('#f8f9fa')
for bar, val in zip(list(b1) + list(b2), sharpe_5050 + sharpe_minvar):
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
             f'{val:.3f}', ha='center', va='bottom', fontsize=8)

ax2 = axes[1]
b3 = ax2.bar(x - width/2, mdd_5050, width, label='50/50 等權重', color='#e74c3c', alpha=0.85, edgecolor='white')
b4 = ax2.bar(x + width/2, mdd_minvar, width, label='最小變異數（最佳模型）', color='#2ecc71', alpha=0.85, edgecolor='white')
ax2.set_ylabel('最大回撤（絕對值）')
ax2.set_title('最大回撤（越低越好）')
ax2.set_xticks(x)
ax2.set_xticklabels(pair_labels)
ax2.legend(fontsize=9)
ax2.spines['top'].set_visible(False)
ax2.spines['right'].set_visible(False)
ax2.set_facecolor('#f8f9fa')
for bar, val in zip(list(b3) + list(b4), mdd_5050 + mdd_minvar):
    ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.003,
             f'{val:.3f}', ha='center', va='bottom', fontsize=8)

# Add model label annotations
ax1.text(0.5, -0.18, f'最佳模型：SPY-GLD → {best_models["SPY-GLD"]}  |  SPY-TLT → {best_models["SPY-TLT"]}  |  GLD-TLT → {best_models["GLD-TLT"]}',
         transform=ax1.transAxes, ha='center', va='top', fontsize=8,
         color='#555', style='italic')

plt.tight_layout()
plt.savefig(f'{out_dir}/k157_portfolio_comparison.png', dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print(f"Saved: {out_dir}/k157_portfolio_comparison.png")

print("All figures generated successfully.")
