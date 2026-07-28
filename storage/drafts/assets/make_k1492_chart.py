#!/usr/bin/env python3
"""K1492 general-audience chart: BTC peg-vs-flow decomposition (QLIKE improvement).

Numbers sourced byte-for-byte from experiments/k1492/k1492_results.json
(btc_horse_race block). No invented figures.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "experiments/k1492/k1492_results.json"
OUT = Path(__file__).resolve().parent / "k1492_peg_vs_flow.png"

data = json.loads(RESULTS.read_text())
hr = data["btc_horse_race"]

flow = hr["flow_only"]["qlike_improvement_vs_baseline"]
peg = hr["peg_only"]["qlike_improvement_vs_baseline"]
full = hr["full"]["qlike_improvement_vs_baseline"]
flow_p = hr["flow_only"]["dm_hln_pvalue_vs_baseline"]
peg_p = hr["peg_only"]["dm_hln_pvalue_vs_baseline"]
full_p = hr["full"]["dm_hln_pvalue_vs_baseline"]

# CJK font
for cand in ["Heiti TC", "Arial Unicode MS", "STHeiti", "Hiragino Sans GB"]:
    if any(f.name == cand for f in fm.fontManager.ttflist):
        plt.rcParams["font.family"] = cand
        break
plt.rcParams["axes.unicode_minus"] = False

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
GOOD = "#0ca30c"      # significant signal
NULL = "#898781"      # no signal (reads gray by design)

labels = ["流出量模型\n(資金撤離 USDT/USDC)", "脫鉤幅度模型\n(價格偏離 $1)", "兩者合併"]
vals = [flow, peg, full]
pvals = [flow_p, peg_p, full_p]
colors = [NULL, GOOD, GOOD]

fig, ax = plt.subplots(figsize=(8.4, 5.2), dpi=170)
fig.patch.set_facecolor(SURFACE)
ax.set_facecolor(SURFACE)

x = range(len(vals))
bars = ax.bar(x, vals, width=0.6, color=colors, zorder=3, edgecolor=SURFACE, linewidth=1.5)

# zero baseline
ax.axhline(0, color="#c3c2b7", linewidth=1.2, zorder=2)

ax.set_ylim(-0.0011, 0.0072)
ax.set_xticks(list(x))
ax.set_xticklabels(labels, fontsize=11, color=INK)
ax.set_ylabel("QLIKE 預測改善（越高越準，0 = 沒幫助）", fontsize=11, color=INK2)
ax.set_title("拆解比特幣波動訊號：流出量幾乎是零，脫鉤幅度扛下全部",
             fontsize=13.5, color=INK, pad=14, weight="bold")

# direct labels: value + significance
def fmt_p(p):
    if p >= 0.10:
        return f"p={p:.3f}（和雜訊沒兩樣）"
    return f"p≈{p:.0e}（統計上穩固）"

for i, (b, v, p) in enumerate(zip(bars, vals, pvals)):
    top = b.get_height()
    if top >= 0:
        ytxt = top + 0.00028
        va = "bottom"
    else:
        ytxt = top - 0.00028
        va = "top"
    vlabel = "≈ 0" if abs(v) < 1e-4 else f"{v:+.5f}"
    ax.text(b.get_x() + b.get_width() / 2, ytxt, vlabel,
            ha="center", va=va, fontsize=11.5, color=INK, weight="bold", zorder=4)
    ax.text(b.get_x() + b.get_width() / 2, 0.0068, fmt_p(p),
            ha="center", va="top", fontsize=9.5, color=INK2, zorder=4)

for s in ["top", "right"]:
    ax.spines[s].set_visible(False)
for s in ["left", "bottom"]:
    ax.spines[s].set_color("#c3c2b7")
ax.tick_params(colors=MUTED, labelsize=10)
ax.yaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
ax.set_axisbelow(True)

fig.text(0.5, 0.008,
         "資料：DefiLlama 穩定幣供給／脫鉤價格 + yfinance BTC-USD｜樣本外 2024-01-01 起，共 895 個交易日｜VolPred 研究筆記",
         ha="center", fontsize=8, color=MUTED)

fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(OUT, facecolor=SURFACE, bbox_inches="tight")
print("wrote", OUT)
print("flow", flow, flow_p)
print("peg", peg, peg_p)
print("full", full, full_p)
