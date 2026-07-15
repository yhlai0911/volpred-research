"""無人載具系列導讀 — 正文圖表（data-bound 自六集 evidence）。

圖 1: 報酬與代價 — 全名冊/核心六檔/加權指數 同窗口對比（EP0 + EP-Final evidence）
圖 2: 證據階梯 — 六層查核結果（各集 evidence 的卡點數字，經 guide_evidence.json 彙整）

所有數字讀自 evidence JSON，不硬編碼（研究誠實）。
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

DRAFTS = Path(__file__).resolve().parents[1]
EV_FINAL = json.loads((DRAFTS / "drone_ep_final_portfolio_evidence.json").read_text())
OUT = Path(__file__).resolve().parent

for fam in ["Heiti TC", "PingFang TC", "Noto Sans CJK TC", "Noto Sans CJK SC"]:
    if any(fam.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = fam
        break
plt.rcParams["axes.unicode_minus"] = False

NAVY, LIGHT, ACCENT, GRAY = "#1f3a5f", "#7fa8cc", "#0f766e", "#8a8f98"

# ---- 圖 1: 報酬與代價 ----
pc = EV_FINAL["portfolio_comparison"]
bench = pc["core_6_equal"]["benchmark_twii"] if "benchmark_twii" in pc.get("core_6_equal", {}) else None
if bench is None:  # benchmark 位置在頂層或各組內，兩種都試
    bench = EV_FINAL.get("benchmark_twii") or EV_FINAL.get("benchmark")
if bench is None:
    for v in pc.values():
        if isinstance(v, dict) and isinstance(v.get("benchmark_twii"), dict):
            bench = v["benchmark_twii"]
            break
assert bench, "benchmark not found in evidence"

groups = [
    ("全名冊 29 檔等權", pc["all_29_equal"]["total_return"] * 100, LIGHT),
    ("核心六檔等權", pc["core_6_equal"]["total_return"] * 100, NAVY),
    ("加權指數 ^TWII", bench["window_return"] * 100, GRAY),
]
risk = [
    ("年化波動 %", pc["core_6_equal"]["annualized_volatility"] * 100, bench["annualized_volatility"] * 100),
    ("最大回撤 %", abs(pc["core_6_equal"]["max_drawdown"]) * 100, abs(bench["max_drawdown"]) * 100),
]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.6), gridspec_kw={"width_ratios": [1.15, 1]})
names, vals, colors = zip(*groups)
bars = ax1.barh(range(len(vals)), vals, color=colors, height=0.62)
ax1.set_yticks(range(len(vals)), names, fontsize=11)
ax1.invert_yaxis()
for i, v in enumerate(vals):
    ax1.text(v + 1.5, i, f"+{v:.1f}%", va="center", fontsize=11, fontweight="bold")
ax1.set_xlim(0, 125)
ax1.set_title("同一共同窗口的總報酬（2025-06-30 ~ 2026-07-09）", fontsize=12, loc="left")
ax1.spines[["top", "right"]].set_visible(False)

x = range(len(risk))
w = 0.36
ax2.bar([i - w / 2 for i in x], [r[1] for r in risk], w, label="核心六檔", color=NAVY)
ax2.bar([i + w / 2 for i in x], [r[2] for r in risk], w, label="加權指數", color=GRAY)
for i, r in enumerate(risk):
    ax2.text(i - w / 2, r[1] + 0.8, f"{r[1]:.1f}", ha="center", fontsize=10, fontweight="bold")
    ax2.text(i + w / 2, r[2] + 0.8, f"{r[2]:.1f}", ha="center", fontsize=10)
ax2.set_xticks(list(x), [r[0] for r in risk], fontsize=11)
ax2.set_title("追平大盤的代價：兩倍波動、三倍回撤", fontsize=12, loc="left")
ax2.legend(frameon=False, fontsize=10)
ax2.spines[["top", "right"]].set_visible(False)
fig.suptitle("")
fig.tight_layout()
fig.savefig(OUT / "drone_series_guide_fig1_return_vs_cost.png", dpi=160, bbox_inches="tight")
plt.close(fig)

# ---- 圖 2: 證據階梯（六層的卡點） ----
guide_ev = json.loads((OUT / "drone_series_guide_evidence.json").read_text())
ladder = guide_ev["evidence_ladder"]

fig, ax = plt.subplots(figsize=(11, 5.6))
n = len(ladder)
for i, step in enumerate(ladder):
    y = n - 1 - i
    ax.barh(y, 0.92 + i * 0.015, left=i * 0.09, color=NAVY if i % 2 == 0 else LIGHT, height=0.68, alpha=0.92)
    ax.text(i * 0.09 + 0.02, y + 0.02, f"{step['ep']}｜{step['question']}", va="center",
            fontsize=11, fontweight="bold", color="white" if i % 2 == 0 else "#10233c")
    ax.text(i * 0.09 + 0.96 + i * 0.015 + 0.015, y, step["blocker"], va="center", fontsize=10.5, color=ACCENT, fontweight="bold")
ax.set_xlim(0, 1.85)
ax.set_ylim(-0.6, n - 0.3)
ax.axis("off")
ax.set_title("證據階梯：每爬一層問「錢真的進來了嗎」— 六層的答案", fontsize=13, loc="left", pad=14)
fig.text(0.01, 0.01,
         "資料來源：無人載具系列 EP0-EP-Final 六集已發佈文章之 evidence（查核日 2026-07-13；詳各集內文）",
         fontsize=8.5, color=GRAY)
fig.tight_layout()
fig.savefig(OUT / "drone_series_guide_fig2_evidence_ladder.png", dpi=160, bbox_inches="tight")
plt.close(fig)
print("charts done")
