"""
K864 圖表生成腳本
Heterogeneous ABM — Strategy Diversity vs VT Crowding

輸出：
  storage/drafts/k864_fig1_flash_crash.png  — 閃崩頻率：同質 vs 異質
  storage/drafts/k864_fig2_paradox.png      — 個體 Sharpe vs 系統閃崩（悖論圖）

資料來源：experiments/k864/k864_results.json
"""

import json
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── 載入資料 ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS_PATH = os.path.join(BASE_DIR, 'experiments', 'k864', 'k864_results.json')
OUT_DIR = os.path.join(BASE_DIR, 'storage', 'drafts')

with open(RESULTS_PATH, 'r') as f:
    data = json.load(f)

hom = data['homogeneous_results']
het = data['heterogeneous_results']

fracs   = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]
labels  = ['0%', '10%', '20%', '30%', '50%', '70%', '100%']
frac_keys = ['0%', '10%', '20%', '30%', '50%', '70%', '100%']

def safe_mean(d, key):
    v = d.get(key, {})
    if isinstance(v, dict):
        return v.get('mean', np.nan)
    return np.nan

def safe_ci(d, key):
    v = d.get(key, {})
    if isinstance(v, dict):
        ci = v.get('bootstrap_ci_95', None)
        if ci and len(ci) == 2:
            return ci
    return [np.nan, np.nan]

# ── 圖 1：閃崩頻率 + 市場波動率（雙 y 軸）─────────────────
hom_fc  = [safe_mean(hom.get(k, {}), 'flash_crash_freq') for k in frac_keys]
het_fc  = [safe_mean(het.get(k, {}), 'flash_crash_freq') for k in frac_keys[1:]]  # het starts at 10%
het_fc_x = fracs[1:]

hom_vol = [safe_mean(hom.get(k, {}), 'ann_vol') for k in frac_keys]
het_vol = [safe_mean(het.get(k, {}), 'ann_vol') for k in frac_keys[1:]]

fig, ax1 = plt.subplots(figsize=(9, 5.5))

color_hom = '#2563EB'   # blue
color_het = '#DC2626'   # red
color_vol_hom = '#93C5FD'
color_vol_het = '#FCA5A5'

ax1.plot(fracs, hom_fc, 'o-', color=color_hom, linewidth=2.2, markersize=7,
         label='閃崩頻率（同質型）', zorder=3)
ax1.plot(het_fc_x, het_fc, 's--', color=color_het, linewidth=2.2, markersize=7,
         label='閃崩頻率（異質型）', zorder=3)
ax1.set_xlabel('VT 策略採用率', fontsize=12)
ax1.set_ylabel('閃崩次數 / 年', fontsize=12, color='#1e293b')
ax1.set_xticks(fracs)
ax1.set_xticklabels(labels, fontsize=10)
ax1.tick_params(axis='y', labelsize=10)
ax1.set_ylim(bottom=0)

ax2 = ax1.twinx()
ax2.plot(fracs, [v * 100 for v in hom_vol], 'o:', color=color_vol_hom,
         linewidth=1.5, markersize=5, label='市場波動率（同質型）%')
ax2.plot(het_fc_x, [v * 100 for v in het_vol], 's:', color=color_vol_het,
         linewidth=1.5, markersize=5, label='市場波動率（異質型）%')
ax2.set_ylabel('年化市場波動率 (%)', fontsize=11, color='#475569')
ax2.tick_params(axis='y', labelsize=10)
ax2.set_ylim(bottom=0)

# 50% 標注
ax1.axvline(x=0.5, color='#64748b', linestyle=':', linewidth=1.2, alpha=0.7)
ax1.text(0.51, 3.0, '50% 臨界點', fontsize=9.5, color='#64748b')

# 在 50% 點標數字
ax1.annotate('3.20次/年', xy=(0.5, 3.203), xytext=(0.57, 3.4),
             fontsize=9, color=color_het,
             arrowprops=dict(arrowstyle='->', color=color_het, lw=1.2))
ax1.annotate('0.46次/年', xy=(0.5, 0.463), xytext=(0.35, 0.8),
             fontsize=9, color=color_hom,
             arrowprops=dict(arrowstyle='->', color=color_hom, lw=1.2))

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2,
           loc='upper left', fontsize=9, framealpha=0.9)

plt.title('圖1：策略多樣化讓閃崩更頻繁，而非更少\n'
          '（Monte Carlo 200 sims，1000 agents，2520 交易日）',
          fontsize=11.5, pad=12)
fig.tight_layout()
fig.savefig(os.path.join(OUT_DIR, 'k864_fig1_flash_crash.png'), dpi=150, bbox_inches='tight')
plt.close()
print("fig1 saved")

# ── 圖 2：個體 Sharpe vs 系統閃崩（悖論圖）───────────────
# 同質 Sharpe 在高採用率下崩潰，異質 Sharpe 保持
hom_sharpe = []
het_sharpe = []
for k in frac_keys[1:]:
    hs = hom.get(k, {}).get('vt_sharpe')
    hets = het.get(k, {}).get('vt_sharpe')
    hom_sharpe.append(hs['mean'] if isinstance(hs, dict) else np.nan)
    het_sharpe.append(hets['mean'] if isinstance(hets, dict) else np.nan)

het_fc_for_plot = [safe_mean(het.get(k, {}), 'flash_crash_freq') for k in frac_keys[1:]]

fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(11, 5.2))

# 左：個體 Sharpe
ax_left.plot(het_fc_x, hom_sharpe, 'o-', color=color_hom, linewidth=2.2, markersize=7,
             label='同質型 VT')
ax_left.plot(het_fc_x, het_sharpe, 's--', color=color_het, linewidth=2.2, markersize=7,
             label='異質型 VT')
ax_left.axhline(0, color='#94a3b8', linestyle='-', linewidth=0.8)
ax_left.set_xlabel('VT 策略採用率', fontsize=11)
ax_left.set_ylabel('個別 VT 策略 Sharpe 比率', fontsize=11)
ax_left.set_xticks(het_fc_x)
ax_left.set_xticklabels(labels[1:], fontsize=10)
ax_left.legend(fontsize=10)
ax_left.set_title('個體績效：異質型更好', fontsize=11.5, pad=8)

# 標 70% 的差異
ax_left.annotate('0.376', xy=(0.7, 0.376), xytext=(0.56, 0.42),
                 fontsize=9.5, color=color_het,
                 arrowprops=dict(arrowstyle='->', color=color_het, lw=1.2))
ax_left.annotate('0.083', xy=(0.7, 0.083), xytext=(0.56, -0.02),
                 fontsize=9.5, color=color_hom,
                 arrowprops=dict(arrowstyle='->', color=color_hom, lw=1.2))

# 右：系統閃崩（雙向箭頭說明悖論）
ax_right.bar(np.array(het_fc_x) - 0.02, [safe_mean(hom.get(k, {}), 'flash_crash_freq') for k in frac_keys[1:]],
             width=0.04, color=color_hom, alpha=0.85, label='同質型市場閃崩/年')
ax_right.bar(np.array(het_fc_x) + 0.02, het_fc_for_plot,
             width=0.04, color=color_het, alpha=0.85, label='異質型市場閃崩/年')
ax_right.set_xlabel('VT 策略採用率', fontsize=11)
ax_right.set_ylabel('市場閃崩次數 / 年', fontsize=11)
ax_right.set_xticks(het_fc_x)
ax_right.set_xticklabels(labels[1:], fontsize=10)
ax_right.legend(fontsize=10)
ax_right.set_title('系統風險：異質型更差', fontsize=11.5, pad=8)

fig.suptitle('圖2：個體贏、市場輸 — 策略多樣化的悖論\n'
             '（資料來源：K864 Monte Carlo 模擬，200 sims）',
             fontsize=11.5, y=1.01)
fig.tight_layout()
fig.savefig(os.path.join(OUT_DIR, 'k864_fig2_paradox.png'), dpi=150, bbox_inches='tight')
plt.close()
print("fig2 saved")
print("Done.")
