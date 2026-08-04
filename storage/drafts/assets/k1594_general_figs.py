"""K1594 general-article charts — 兩張圖：踩線次數校準 + 緩衝線寬度。

所有數字硬對齊 experiments/k1594/k1594_results.json（cells[*].oos_evaluation.models[*]），
不從 README 或任務敘述轉抄。
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

for cand in ["PingFang HK", "Heiti TC", "Arial Unicode MS"]:
    try:
        font_manager.findfont(cand, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [cand]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[3]
RES = ROOT / "experiments/k1594/k1594_results.json"
OUT = Path(__file__).resolve().parent
res = json.loads(RES.read_text())

MODELS = ["HS250", "HS1000", "VIXRegime1000", "KOWCPI-lite"]
LABELS = ["近 250 天\n一視同仁", "近 1000 天\n一視同仁", "恐慌程度\n分組", "相似度\n加權"]
COLORS = ["#b8c6d0", "#8aa3b5", "#4e7d9b", "#d1603d"]

CELLS = [
    ("TLT_alpha0.05", "長天期公債（每 20 天允許踩 1 次）"),
    ("HYG_alpha0.05", "高收益公司債（每 20 天允許踩 1 次）"),
    ("TLT_alpha0.01", "長天期公債（每 100 天允許踩 1 次）"),
    ("HYG_alpha0.01", "高收益公司債（每 100 天允許踩 1 次）"),
]


def cell_models(cell_key):
    cell = res["cells"][cell_key]
    return {m["model"]: m for m in cell["oos_evaluation"]["models"]}


# ---------------- Figure 1: 踩線次數 vs 應該的次數 ----------------
fig, axes = plt.subplots(2, 2, figsize=(12.6, 8.6))
for ax, (key, title) in zip(axes.ravel(), CELLS):
    mm = cell_models(key)
    counts = [mm[m]["backtest"]["n_violations"] for m in MODELS]
    n = res["cells"][key]["n_oos"]
    alpha = res["cells"][key]["alpha"]
    expected = n * alpha
    bars = ax.bar(range(4), counts, color=COLORS, edgecolor="#3a4a55", width=0.64)
    ax.axhline(expected, color="#1b5c80", ls="--", lw=1.5)
    ax.set_xlim(-0.6, 4.25)
    ax.text(3.42, expected, f"應該約\n{expected:.0f} 次", color="#1b5c80",
            fontsize=9.5, ha="left", va="center")
    for b, c in zip(bars, counts):
        ax.text(b.get_x() + b.get_width() / 2, c + max(counts) * 0.02, str(c),
                ha="center", fontsize=11, weight="bold")
    ax.set_xticks(range(4))
    ax.set_xticklabels(LABELS, fontsize=9.5)
    ax.set_ylim(0, max(max(counts), expected) * 1.22)
    ax.set_ylabel("實際踩線天數", fontsize=10.5)
    ax.set_title(title, fontsize=12, weight="bold", pad=10)
    ax.spines[["top", "right"]].set_visible(False)

fig.suptitle("2887 個交易日裡，四種畫線方法各被踩線幾次", fontsize=14.5, weight="bold")
fig.text(0.5, 0.005,
         "資料期間 2015-01-01 至 2026-06-30；每天用前 1000 個交易日重新畫線。長條越接近虛線越好。",
         ha="center", fontsize=9.5, color="#555")
fig.tight_layout(rect=[0, 0.025, 1, 0.955])
fig.savefig(OUT / "k1594_general_breaches.png", dpi=150)
plt.close(fig)

# ---------------- Figure 2: 緩衝線寬度（相對最基本做法 = 100）----------------
fig, ax = plt.subplots(figsize=(11.6, 5.6))
group_labels = ["長天期公債\n每 20 天 1 次", "高收益公司債\n每 20 天 1 次",
                "長天期公債\n每 100 天 1 次", "高收益公司債\n每 100 天 1 次"]
width = 0.2
for i, m in enumerate(MODELS):
    vals = []
    for key, _ in CELLS:
        mm = cell_models(key)
        vals.append(mm[m]["mean_var_width"] / mm["HS250"]["mean_var_width"] * 100)
    xs = [g + (i - 1.5) * width for g in range(4)]
    bars = ax.bar(xs, vals, width=width, color=COLORS[i],
                  edgecolor="#3a4a55", label=LABELS[i].replace("\n", ""))
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.4, f"{v:.1f}",
                ha="center", fontsize=8.6)

ax.axhline(100, color="#1b5c80", ls="--", lw=1.3)
ax.set_xticks(range(4))
ax.set_xticklabels(group_labels, fontsize=10)
ax.set_ylim(80, 117)
ax.set_ylabel("平均緩衝線寬度（最基本做法 = 100）", fontsize=10.5)
ax.set_title("同樣一條風險線，誰畫得比較貼身", fontsize=13.5, weight="bold", pad=26)
ax.legend(fontsize=9.5, ncol=4, loc="upper center", frameon=False,
          bbox_to_anchor=(0.5, 1.06))
ax.spines[["top", "right"]].set_visible(False)
fig.text(0.5, 0.005, "數字越低代表同一條線佔用的緩衝越少；但要搭配踩線次數一起看才有意義。",
         ha="center", fontsize=9.5, color="#555")
fig.tight_layout(rect=[0, 0.03, 1, 1])
fig.savefig(OUT / "k1594_general_width.png", dpi=150)
plt.close(fig)

print("wrote k1594_general_breaches.png / k1594_general_width.png")
for key, _ in CELLS:
    mm = cell_models(key)
    print(key, {m: round(mm[m]["mean_var_width"] / mm["HS250"]["mean_var_width"] * 100, 1)
                for m in MODELS})
