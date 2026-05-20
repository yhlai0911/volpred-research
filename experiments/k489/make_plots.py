"""K489 publication plots: bar chart, heatmap, slope-RV scatter."""
import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent
RESULTS = json.loads((EXP_DIR / 'k489_vix_term_structure_results.json').read_text())

# Style
plt.rcParams.update({
    'figure.dpi': 130,
    'savefig.dpi': 150,
    'font.size': 11,
    'axes.titlesize': 12,
    'axes.labelsize': 10,
    'figure.facecolor': 'white',
    'axes.facecolor': 'white',
    'axes.spines.top': False,
    'axes.spines.right': False,
})

# ---- Figure 1: matched-tenor R² (lag baseline vs IV-only vs IV+lag+TS) ----
matched = RESULTS['part_a_matched_tenor']
pairs = ['VIX9D→RV_5d', 'VIX→RV_21d', 'VIX3M→RV_63d']
labels = ['VIX9D → RV(5天)', 'VIX → RV(21天)', 'VIX3M → RV(63天)']
r2_lag = [matched[p]['RV_lag']['r2'] for p in pairs]
r2_iv = [matched[p]['IV_only']['r2'] for p in pairs]
r2_full = [matched[p]['IV+RV_lag+TS']['r2'] for p in pairs]

fig, ax = plt.subplots(figsize=(8.5, 4.6))
x = np.arange(len(pairs))
w = 0.27
b1 = ax.bar(x - w, r2_lag, w, label='Lag persistence (基準)', color='#9aa0a6')
b2 = ax.bar(x, r2_iv, w, label='IV only (matched tenor)', color='#1f77b4')
b3 = ax.bar(x + w, r2_full, w, label='IV + Lag + Term Structure', color='#2ca02c')
ax.axhline(0, color='#444', linewidth=0.7)
ax.set_xticks(x)
ax.set_xticklabels(labels)
ax.set_ylabel('OOS R² (2023–2026)')
ax.set_title('K489：三個 horizon 的 OOS R² — IV 加上期限結構真的有幫助嗎？')
ax.legend(loc='upper right', frameon=False, fontsize=9)
for bars in (b1, b2, b3):
    for b in bars:
        v = b.get_height()
        ax.text(b.get_x() + b.get_width()/2, v + (0.012 if v >= 0 else -0.022),
                f'{v:.3f}', ha='center', va='bottom' if v >= 0 else 'top', fontsize=8.5)
ax.set_ylim(min(r2_lag) - 0.06, max(r2_full) + 0.08)
ax.grid(axis='y', alpha=0.25, linewidth=0.6)
fig.tight_layout()
fig.savefig(EXP_DIR / 'fig1_matched_tenor_r2.png', bbox_inches='tight')
plt.close(fig)

# ---- Figure 2: cross-tenor R² heatmap ----
cross = RESULTS['part_b_cross_tenor']
iv_keys = ['iv_9d', 'iv_30d', 'iv_90d']
rv_keys = ['rv_5d', 'rv_21d', 'rv_63d']
iv_labels = ['VIX9D (9d)', 'VIX (30d)', 'VIX3M (90d)']
rv_labels = ['RV 5天', 'RV 21天', 'RV 63天']
M = np.zeros((3, 3))
for i, ivk in enumerate(iv_keys):
    for j, rvk in enumerate(rv_keys):
        M[i, j] = cross[f'{ivk}→{rvk}']['r2_oos']

fig, ax = plt.subplots(figsize=(7.6, 5.2))
im = ax.imshow(M, cmap='RdYlGn', vmin=-0.05, vmax=0.45, aspect='auto')
ax.set_xticks(range(3)); ax.set_xticklabels(rv_labels)
ax.set_yticks(range(3)); ax.set_yticklabels(iv_labels)
ax.set_xlabel('預測目標 (Realized Vol horizon)')
ax.set_ylabel('VIX 期限')
ax.set_title('K489：所有 IV-tenor × RV-horizon 組合的 OOS R²\n（綠色=高，紅色=低；對角線=matched tenor）')
for i in range(3):
    for j in range(3):
        v = M[i, j]
        color = 'white' if v < 0.05 else 'black'
        ax.text(j, i, f'{v:.3f}', ha='center', va='center', color=color, fontsize=11, fontweight='bold')
# Highlight diagonal
for k in range(3):
    ax.add_patch(plt.Rectangle((k - 0.5, k - 0.5), 1, 1, fill=False, edgecolor='black', linewidth=2.0))
fig.colorbar(im, ax=ax, label='OOS R²', shrink=0.78)
fig.tight_layout()
fig.savefig(EXP_DIR / 'fig2_cross_tenor_heatmap.png', bbox_inches='tight')
plt.close(fig)

# ---- Figure 3: term-structure slope conditional RV ----
cond = RESULTS['part_d_conditional_rv']
labels3 = [
    'Strong\nBackwardation\n(slope<-0.02)',
    'Mild\nBackwardation\n(-0.02≤slope<0)',
    'Flat\n(|slope|≤0.005)',
    'Mild\nContango\n(0<slope≤0.02)',
    'Strong\nContango\n(slope>0.02)',
]
keys3 = [
    'Strong Backwardation (slope<-0.02)',
    'Mild Backwardation (-0.02≤slope<0)',
    'Flat (|slope|≤0.005)',
    'Mild Contango (0<slope≤0.02)',
    'Strong Contango (slope>0.02)',
]
rv5 = [cond[k]['rv_5d_mean'] for k in keys3]
rv21 = [cond[k]['rv_21d_mean'] for k in keys3]
rv63 = [cond[k]['rv_63d_mean'] for k in keys3]
ns = [cond[k]['n'] for k in keys3]

fig, ax = plt.subplots(figsize=(9.2, 4.8))
x = np.arange(len(labels3))
w = 0.27
ax.bar(x - w, rv5, w, label='RV 5天 (mean)', color='#d62728')
ax.bar(x, rv21, w, label='RV 21天 (mean)', color='#ff7f0e')
ax.bar(x + w, rv63, w, label='RV 63天 (mean)', color='#1f77b4')
ax.set_xticks(x); ax.set_xticklabels(labels3, fontsize=9)
ax.set_ylabel('未來實現波動率 (annualized)')
ax.set_title('K489：期限結構斜率分組 vs 未來 realized vol\n（backwardation 對應顯著高未來 RV，contango 反之）')
for i, n in enumerate(ns):
    ax.text(i, max(rv5[i], rv21[i], rv63[i]) + 0.012, f'n={n}', ha='center', fontsize=8.5, color='#555')
ax.legend(frameon=False, loc='upper right', fontsize=9)
ax.grid(axis='y', alpha=0.25)
fig.tight_layout()
fig.savefig(EXP_DIR / 'fig3_slope_regime_rv.png', bbox_inches='tight')
plt.close(fig)

print("Generated: fig1_matched_tenor_r2.png, fig2_cross_tenor_heatmap.png, fig3_slope_regime_rv.png")
