"""
K501 Article Figure Generator
Generates figures for the general-audience article on SSVS Return Prediction
"""
import json
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# Load results
results_path = os.path.join(os.path.dirname(__file__), '..', 'k501_return_prediction_results.json')
with open(results_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

output_dir = os.path.dirname(__file__)

# ----------------------------------------------------------------
# Figure 1: Cross-asset OOS R² comparison bar chart (best model)
# ----------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))

assets = ['SPY', 'QQQ', '0050.TW (台股)']
best_models = ['AR1', 'Ridge', 'SSVS-OLS']
r2_values = [1.78, 1.47, 15.59]
harvey_pass = [False, False, True]

colors = ['#d9534f' if not p else '#28a745' for p in harvey_pass]

bars = ax.bar(assets, r2_values, color=colors, width=0.5, edgecolor='white', linewidth=1.5)

# Add value labels on bars
for bar, val, model, passed in zip(bars, r2_values, best_models, harvey_pass):
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.2,
            f'{val:.1f}%', ha='center', va='bottom', fontsize=13, fontweight='bold')
    verdict = 'PASS 統計顯著' if passed else 'FAIL 統計不顯著'
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height()/2,
            verdict, ha='center', va='center', fontsize=9,
            color='white', fontweight='bold')

ax.set_ylabel('樣本外 OOS R²（%）', fontsize=12)
ax.set_title('三個市場的報酬預測準確度比較（K501）\n樣本外期間：2020–2026', fontsize=13, fontweight='bold')
ax.set_ylim(0, 19)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.tick_params(axis='x', labelsize=12)
ax.tick_params(axis='y', labelsize=11)

# Legend
red_patch = mpatches.Patch(color='#d9534f', label='未通過統計顯著性門檻')
green_patch = mpatches.Patch(color='#28a745', label='通過統計顯著性門檻')
ax.legend(handles=[red_patch, green_patch], loc='upper left', fontsize=10)

fig.tight_layout()
fig.savefig(os.path.join(output_dir, 'fig1_oos_r2_comparison.png'), dpi=150, bbox_inches='tight')
plt.close(fig)
print("Saved fig1_oos_r2_comparison.png")

# ----------------------------------------------------------------
# Figure 2: Sharpe ratio comparison — c2c vs o2o degradation (Taiwan)
# Using I8 reference numbers from critical_caveat_taiwan
# ----------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))

categories = ['收盤到收盤\n（c2c，含隔夜）', '開盤到開盤\n（o2o，可交易）']
sharpe_vals = [3.09, 0.87]
bar_colors = ['#f0ad4e', '#17a2b8']

bars = ax.bar(categories, sharpe_vals, color=bar_colors, width=0.45,
              edgecolor='white', linewidth=1.5)

for bar, val in zip(bars, sharpe_vals):
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.05,
            f'{val:.2f}', ha='center', va='bottom', fontsize=16, fontweight='bold')

# Annotation arrow
ax.annotate('', xy=(1, 0.87), xytext=(0, 3.09),
            arrowprops=dict(arrowstyle='->', color='#d9534f', lw=2.5,
                            connectionstyle='arc3,rad=-0.15'))
ax.text(0.55, 1.9, '降低 72%', fontsize=13, color='#d9534f',
        fontweight='bold', ha='center', rotation=-50)

ax.set_ylabel('年化 Sharpe Ratio', fontsize=12)
ax.set_title('台股策略：同一個訊號，兩種實作方式\n（依 I8 時區偏差分析）', fontsize=13, fontweight='bold')
ax.set_ylim(0, 3.8)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.tick_params(axis='x', labelsize=12)
ax.tick_params(axis='y', labelsize=11)

ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5, linewidth=1.2)
ax.text(1.25, 1.05, '一般策略\n可接受門檻', fontsize=9, color='gray', ha='center')

fig.tight_layout()
fig.savefig(os.path.join(output_dir, 'fig2_c2c_vs_o2o_sharpe.png'), dpi=150, bbox_inches='tight')
plt.close(fig)
print("Saved fig2_c2c_vs_o2o_sharpe.png")

print("All figures generated successfully.")
