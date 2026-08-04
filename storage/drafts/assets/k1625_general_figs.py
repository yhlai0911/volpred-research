"""K1625 general-article charts — 兩張圖：極端費率後的高波動比率 + 訊號強度是否過門檻。

所有數字硬對齊 experiments/k1625/k1625_results.json
（per_asset[*].conditional_high_rv_rates.h5 與 primary_tstats），
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
RES = ROOT / "experiments/k1625/k1625_results.json"
OUT = Path(__file__).resolve().parent
res = json.loads(RES.read_text())

ASSETS = [("BTC", "比特幣"), ("ETH", "以太幣")]

# ---------------- Figure 1: 極端費率隔天起算，未來五天落入高波動的比率 ----------------
BUCKETS = [
    ("non_extreme", "平常日", "#b8c6d0"),
    ("negative_funding_extreme", "空方付錢\n（費率極低）", "#8aa3b5"),
    ("positive_funding_extreme", "多方付錢\n（費率極高）", "#d1603d"),
]

fig, axes = plt.subplots(1, 2, figsize=(12.2, 5.4))
for ax, (key, name) in zip(axes, ASSETS):
    h5 = res["per_asset"][key]["conditional_high_rv_rates"]["h5"]
    base = h5["base_high_rv_rate"] * 100
    vals = [h5[b]["high_rv_rate"] * 100 for b, _, _ in BUCKETS]
    ns = [h5[b]["n"] for b, _, _ in BUCKETS]
    colors = [c for _, _, c in BUCKETS]
    bars = ax.bar(range(len(vals)), vals, color=colors, width=0.62)
    ax.axhline(base, color="#555555", linestyle="--", linewidth=1.2)
    ax.text(
        -0.44, base + 0.6, f"全期平均 {base:.1f}%",
        color="#555555", fontsize=10, ha="left",
    )
    for bar, v, n in zip(bars, vals, ns):
        ax.text(
            bar.get_x() + bar.get_width() / 2, v + 0.5,
            f"{v:.1f}%\n({n} 天)", ha="center", fontsize=10.5,
        )
    ax.set_xticks(range(len(vals)))
    ax.set_xticklabels([lab for _, lab, _ in BUCKETS], fontsize=11)
    ax.set_ylim(0, 36)
    ax.set_ylabel("接下來五天落入高波動的比率")
    ax.set_title(f"{name}（{h5['n']} 個交易日）", fontsize=13)
    ax.spines[["top", "right"]].set_visible(False)

fig.suptitle("資金費率走到極端之後，未來五天有多容易變成高波動週", fontsize=15)
fig.tight_layout(rect=(0, 0, 1, 0.94))
fig.savefig(OUT / "k1625_general_rates.png", dpi=150)
plt.close(fig)

# ---------------- Figure 2: 訊號強度 vs 事先講好的門檻 ----------------
TERMS = [
    ("funding_z_lag1", "費率高低\n（連續強弱）"),
    ("neg_extreme_lag1", "空方付錢\n（費率極低）"),
    ("pos_extreme_lag1", "多方付錢\n（費率極高）"),
    ("asymmetry_pos_minus_neg", "多空兩端\n的落差"),
]
lookup = {
    (r["asset"], r["term"]): r
    for r in res["primary_tstats"]
    if r["horizon"] == 5 and r["is_regime_model"]
}
threshold = res["config"]["harvey_abs_t_threshold"]

fig, ax = plt.subplots(figsize=(11.4, 5.6))
width = 0.36
xs = range(len(TERMS))
for i, (key, name) in enumerate(ASSETS):
    vals = [abs(lookup[(key, t)]["t"]) for t, _ in TERMS]
    offs = [x + (i - 0.5) * width for x in xs]
    color = "#d1603d" if key == "BTC" else "#4e7d9b"
    bars = ax.bar(offs, vals, width=width, color=color, label=name)
    for bar, v in zip(bars, vals):
        ax.text(
            bar.get_x() + bar.get_width() / 2, v + 0.08,
            f"{v:.2f}", ha="center", fontsize=10.5,
        )
ax.axhline(threshold, color="#333333", linestyle="--", linewidth=1.4)
ax.text(
    len(TERMS) - 0.55, threshold + 0.12,
    f"事先講好的門檻：{threshold:.0f} 倍", fontsize=11, ha="right",
)
ax.set_xticks(list(xs))
ax.set_xticklabels([lab for _, lab in TERMS], fontsize=11)
ax.set_ylabel("訊號大小相對於它自身估計誤差的倍數")
ax.set_ylim(0, 4.6)
ax.set_title("四個問法、兩個幣，只有一格站上門檻", fontsize=14)
ax.legend(frameon=False, fontsize=11)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(OUT / "k1625_general_strength.png", dpi=150)
plt.close(fig)

print("wrote", OUT / "k1625_general_rates.png", OUT / "k1625_general_strength.png")
