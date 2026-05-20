"""K288 figure generation. Reads results.json, plots stability metrics."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# Traditional Chinese font fallback
for cand in ["PingFang TC", "Heiti TC", "STHeiti", "Microsoft JhengHei",
             "Arial Unicode MS"]:
    try:
        font_manager.findfont(cand, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [cand, "DejaVu Sans"]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[2]
RES = json.loads((Path(__file__).parent.parent /
                  "k288_cross_period_stability_results.json").read_text())
OUT = Path(__file__).parent

PERIOD_LABELS = {
    "P1: 2005-2009 (GFC)": "P1\n2005-09\n金融海嘯",
    "P2: 2010-2014 (Recovery+QE)": "P2\n2010-14\n復甦+QE",
    "P3: 2015-2019 (Bull+VolSpk)": "P3\n2015-19\n多頭+波動",
    "P4: 2020-2024 (COVID+Rates)": "P4\n2020-24\n疫情+升息",
}

# ---- Figure 1: Stability score bar (8 findings × score 0-4) ----
fig, ax = plt.subplots(figsize=(11, 5.5))
findings = list(RES["stability_scores"].keys())
scores = [RES["stability_scores"][f] for f in findings]

# Translate F1-F8 labels to Traditional Chinese for general readers
LABEL_MAP = {
    "F1: VIX sufficient": "F1 VIX 已足夠",
    "F2: GJR best/tied": "F2 GJR 最佳",
    "F3: 50/50 > SPY": "F3 50/50 勝 SPY",
    "F4: VT reduces MDD": "F4 VT 降低 MDD",
    "F5: K insensitive": "F5 K 值不敏感",
    "F6: Monthly >= Quarterly": "F6 月再平衡優於季",
    "F7: SPY-GLD corr~0": "F7 SPY-GLD 相關≈0",
    "F8: VT costs 1-4%/yr": "F8 VT 年成本 1-4%",
}
labels_tc = [LABEL_MAP[f] for f in findings]
colors = ["#2ca02c" if s == 4 else "#ff7f0e" if s == 3 else
          "#d4a017" if s == 2 else "#d62728" for s in scores]

bars = ax.bar(labels_tc, scores, color=colors, edgecolor="black", linewidth=0.6)
ax.axhline(4, color="#2ca02c", linestyle="--", alpha=0.4, label="完全穩定 (4/4)")
ax.axhline(3, color="#ff7f0e", linestyle="--", alpha=0.3, label="幾乎穩定 (3/4)")
ax.set_ylim(0, 4.5)
ax.set_ylabel("通過期間數（共 4 期）")
ax.set_title("K288：8 大研究發現跨 4 個歷史期間的穩定性評分",
             fontsize=13, pad=14)
for b, s in zip(bars, scores):
    ax.text(b.get_x() + b.get_width()/2, s + 0.08, str(s),
            ha="center", va="bottom", fontsize=10, fontweight="bold")
ax.legend(loc="upper right", fontsize=9)
ax.tick_params(axis="x", labelsize=9)
plt.xticks(rotation=20, ha="right")
plt.tight_layout()
plt.savefig(OUT / "k288_stability_scores.png", dpi=160, bbox_inches="tight")
plt.close()
print("wrote", OUT / "k288_stability_scores.png")

# ---- Figure 2: F4 VT 降低 MDD (4 periods, BH vs VT) ----
fig, ax = plt.subplots(figsize=(10, 5))
periods = list(RES["findings"]["F4: VT reduces MDD"].keys())
mdd_bh = [abs(RES["findings"]["F4: VT reduces MDD"][p]["mdd_bh"]) * 100 for p in periods]
mdd_vt = [abs(RES["findings"]["F4: VT reduces MDD"][p]["mdd_vt"]) * 100 for p in periods]
imp = [RES["findings"]["F4: VT reduces MDD"][p]["improvement_pct"] for p in periods]

import numpy as np
x = np.arange(len(periods))
w = 0.36
ax.bar(x - w/2, mdd_bh, w, label="買入持有 (B&H)", color="#d62728", alpha=0.85)
ax.bar(x + w/2, mdd_vt, w, label="波動率目標 (VT)", color="#1f77b4", alpha=0.85)
for i, (b, v, im) in enumerate(zip(mdd_bh, mdd_vt, imp)):
    ax.text(i, max(b, v) + 1.2, f"改善\n{im:.0f}%",
            ha="center", va="bottom", fontsize=9, color="#2ca02c", fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels([PERIOD_LABELS[p] for p in periods], fontsize=9)
ax.set_ylabel("最大回撤 |MDD| (%)")
ax.set_title("K288 F4：波動率目標策略在 4 個期間都顯著降低最大回撤",
             fontsize=12, pad=12)
ax.legend(loc="upper right")
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(OUT / "k288_f4_mdd_reduction.png", dpi=160, bbox_inches="tight")
plt.close()
print("wrote", OUT / "k288_f4_mdd_reduction.png")

# ---- Figure 3: F3 50/50 vs SPY Sharpe across periods ----
fig, ax = plt.subplots(figsize=(10, 5))
sh_spy = [RES["findings"]["F3: 50/50 > SPY"][p]["sharpe_spy"] for p in periods]
sh_5050 = [RES["findings"]["F3: 50/50 > SPY"][p]["sharpe_5050"] for p in periods]
diffs = [RES["findings"]["F3: 50/50 > SPY"][p]["diff"] for p in periods]
passes = [RES["findings"]["F3: 50/50 > SPY"][p]["pass"] for p in periods]

ax.bar(x - w/2, sh_spy, w, label="SPY 全買全押", color="#9467bd", alpha=0.85)
ax.bar(x + w/2, sh_5050, w, label="50/50 SPY/GLD", color="#2ca02c", alpha=0.85)
for i, (s, p, d, ok) in enumerate(zip(sh_spy, sh_5050, diffs, passes)):
    top = max(s, p)
    sign = "+" if d > 0 else ""
    color = "#2ca02c" if ok else "#d62728"
    label = ("勝" if ok else "敗")
    ax.text(i, top + 0.05, f"差距 {sign}{d:.2f}\n{label}",
            ha="center", va="bottom", fontsize=9, color=color, fontweight="bold")
ax.axhline(0, color="black", linewidth=0.6)
ax.set_xticks(x)
ax.set_xticklabels([PERIOD_LABELS[p] for p in periods], fontsize=9)
ax.set_ylabel("年化 Sharpe 比率")
ax.set_title("K288 F3：50/50 SPY/GLD 在 4 期間中只贏 2 期（不是萬靈丹）",
             fontsize=12, pad=12)
ax.legend(loc="upper left")
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(OUT / "k288_f3_5050_vs_spy.png", dpi=160, bbox_inches="tight")
plt.close()
print("wrote", OUT / "k288_f3_5050_vs_spy.png")
