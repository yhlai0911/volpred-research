"""
K893 RWC vs HistSim — 圖表生成腳本
生成兩張 matplotlib PNG：
  fig1_violation_rate.png  — SPY α=1% 違規率 bar chart（含 target 水平線）
  fig2_avg_var.png         — SPY α=1% avg_var_pct 比較（HistSim vs RWC）
"""
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# --- 路徑設定 ---
HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(HERE, "k893_regime_conformal_var_results.json")

with open(RESULTS_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

spy = data["assets"]["SPY"]["evaluation"]

# --- 字型設定（PingFang / Noto Sans CJK 優先；失敗時 fallback 英文標注）---
import matplotlib.font_manager as fm
preferred_fonts = [
    "PingFang TC",
    "Noto Sans CJK TC",
    "Noto Sans TC",
    "Apple LiGothic",
    "Heiti TC",
    "Microsoft YaHei",
    "SimHei",
]
available_names = {f.name for f in fm.fontManager.ttflist}
chosen = None
for pf in preferred_fonts:
    if pf in available_names:
        chosen = pf
        break

if chosen:
    plt.rcParams["font.family"] = chosen
else:
    # fallback: use DejaVu / default, label in English
    plt.rcParams["font.family"] = "DejaVu Sans"

plt.rcParams["axes.unicode_minus"] = False


# ============================================================
# Figure 1: SPY α=1% 違規率 bar chart
# ============================================================
specs = ["Normal", "Student-t", "HistSim", "RWC λ=0.05", "RWC λ=0.1", "RWC λ=0.2"]
keys  = ["Normal", "Student-t", "HistSim", "RWC_lam0.05", "RWC_lam0.1", "RWC_lam0.2"]
vrates = [spy[k]["alpha_0.01"]["violation_rate"] * 100 for k in keys]

# 顏色：FAIL 紅，PASS 綠
trinity_pass = [
    spy[k]["alpha_0.01"]["trinity"]["trinity_pass"] for k in keys
]
colors = ["#d62728" if not p else "#2ca02c" for p in trinity_pass]

fig1, ax1 = plt.subplots(figsize=(9, 5), dpi=150)
x = np.arange(len(specs))
bars = ax1.bar(x, vrates, color=colors, width=0.6, zorder=3)

# 水平 target 線
ax1.axhline(1.0, color="navy", linestyle="--", linewidth=1.5, label="Target 1%", zorder=4)

# 數值標注
for bar, vr in zip(bars, vrates):
    ax1.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 0.03,
        f"{vr:.2f}%",
        ha="center", va="bottom", fontsize=9.5
    )

ax1.set_xticks(x)
ax1.set_xticklabels(specs, fontsize=11)
ax1.set_ylabel("違規率（%）" if chosen else "Violation Rate (%)", fontsize=12)
ax1.set_title(
    "SPY 99% VaR 各模型違規率（OOS 2019–2026）\nα=1%，n=1823 天"
    if chosen else
    "SPY 99% VaR Violation Rate by Model (OOS 2019-2026)\nalpha=1%, n=1823 days",
    fontsize=13
)
ax1.set_ylim(0, max(vrates) * 1.25)
ax1.grid(axis="y", alpha=0.4, zorder=0)

# 圖例
pass_patch = mpatches.Patch(color="#2ca02c", label="Trinity PASS")
fail_patch = mpatches.Patch(color="#d62728", label="Trinity FAIL")
ax1.legend(handles=[pass_patch, fail_patch,
                    plt.Line2D([0], [0], color="navy", linestyle="--", linewidth=1.5, label="Target 1%")],
           fontsize=10, loc="upper right")

fig1.tight_layout()
out1 = os.path.join(HERE, "fig1_violation_rate.png")
fig1.savefig(out1, dpi=150)
plt.close(fig1)
print(f"Saved: {out1}")


# ============================================================
# Figure 2: SPY α=1% avg_var_pct 比較
# ============================================================
var_specs = ["HistSim", "RWC λ=0.05", "RWC λ=0.1", "RWC λ=0.2"]
var_keys  = ["HistSim", "RWC_lam0.05", "RWC_lam0.1", "RWC_lam0.2"]
var_vals  = [abs(spy[k]["alpha_0.01"]["avg_var_pct"]) for k in var_keys]

bar_colors = ["#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd"]

fig2, ax2 = plt.subplots(figsize=(8, 5), dpi=150)
x2 = np.arange(len(var_specs))
bars2 = ax2.bar(x2, var_vals, color=bar_colors, width=0.55, zorder=3)

# 標注數值
for bar, vv in zip(bars2, var_vals):
    ax2.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 0.02,
        f"{vv:.3f}%",
        ha="center", va="bottom", fontsize=10
    )

# 標注 tighter 幅度
histsim_val = var_vals[0]
for i, (bar, vv) in enumerate(zip(bars2[1:], var_vals[1:]), start=1):
    pct_tighter = (histsim_val - vv) / histsim_val * 100
    if pct_tighter > 0:
        ax2.annotate(
            f"↑ {pct_tighter:.1f}% tighter",
            xy=(bar.get_x() + bar.get_width() / 2, vv / 2),
            ha="center", va="center", fontsize=8.5, color="white", fontweight="bold"
        )

ax2.set_xticks(x2)
ax2.set_xticklabels(var_specs, fontsize=11)
ax2.set_ylabel("|avg VaR %|（絕對值越小越緊）" if chosen else "|avg VaR %| (smaller = tighter)", fontsize=11)
ax2.set_title(
    "SPY 99% VaR 平均區間寬度比較（OOS 2019–2026）\nα=1%，數值取絕對值；越小代表 VaR interval 越緊"
    if chosen else
    "SPY 99% VaR Interval Width by Model (OOS 2019-2026)\nalpha=1%: smaller abs = tighter interval",
    fontsize=12
)
ax2.set_ylim(0, max(var_vals) * 1.25)
ax2.grid(axis="y", alpha=0.4, zorder=0)

fig2.tight_layout()
out2 = os.path.join(HERE, "fig2_avg_var.png")
fig2.savefig(out2, dpi=150)
plt.close(fig2)
print(f"Saved: {out2}")
