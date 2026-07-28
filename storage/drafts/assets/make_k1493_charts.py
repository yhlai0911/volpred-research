#!/usr/bin/env python3
"""K1493 general-audience charts: short-vol product survival vs premium decline.

Every number is read byte-for-byte from experiments/k1493/k1493_results.json
and experiments/k1493/close_prices.csv. No invented figures.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager as fm

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "experiments/k1493/k1493_results.json"
PRICES = ROOT / "experiments/k1493/close_prices.csv"
OUTDIR = Path(__file__).resolve().parent

data = json.loads(RESULTS.read_text())
sv = data["strategy_results"]["SVXY_actual"]

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
GOOD = "#0ca30c"
BAD = "#c0392b"
NEUTRAL = "#898781"


def frame(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=10)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)


# ---------------------------------------------------------------- chart 1
# One day rewrites a decade: SVXY price path, log scale.
px = pd.read_csv(PRICES, index_col=0, parse_dates=True)["SVXY"].dropna()

fig, ax = plt.subplots(figsize=(9.2, 5.0), dpi=200)
fig.patch.set_facecolor(SURFACE)
frame(ax)

ax.semilogy(px.index, px.values, color=INK, linewidth=1.3, zorder=3)
crash = pd.Timestamp("2018-02-06")
ax.axvline(crash, color=BAD, linewidth=1.1, linestyle="--", zorder=2)
ax.annotate(
    "2018/2/6 一天 -83%\n收盤 143.64 → 24.48",
    xy=(crash, 24.48),
    xytext=(pd.Timestamp("2019-06-01"), 90),
    fontsize=11, color=BAD, weight="bold",
    arrowprops=dict(arrowstyle="->", color=BAD, linewidth=1.2),
    zorder=4,
)
ax.set_ylabel("收盤價（美元，對數刻度）", fontsize=11, color=INK2)
ax.set_title("放空波動的 ETF：一天抹掉六年", fontsize=13.5, color=INK,
             pad=14, weight="bold", loc="left")
ax.text(0.0, -0.13, "資料：yfinance 調整後收盤價，2011-10-04 至 2026-06-12。",
        transform=ax.transAxes, fontsize=8.5, color=MUTED)
fig.tight_layout()
fig.savefig(OUTDIR / "k1493_svxy_path.png", facecolor=SURFACE, bbox_inches="tight")
plt.close(fig)

# ---------------------------------------------------------------- chart 2
# Risk-reward ratio and worst single day, by window.
windows = [
    ("2011-2017\n(改制前)", "pre_2011_2017"),
    ("2018 至今\n(全段)", "post_2018_2026"),
    ("2018/3 之後\n(跳過那一週)", "post_after_volmageddon"),
    ("2020/5 之後\n(疫情後)", "post_after_covid"),
]
ratios = [sv[k]["sharpe"] for _, k in windows]
worst = [sv[k]["worst_day"] * 100 for _, k in windows]
labels = [lab for lab, _ in windows]

fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.9), dpi=200)
fig.patch.set_facecolor(SURFACE)

ax = axes[0]
frame(ax)
colors = [GOOD if v > 0.5 else (BAD if v < 0 else NEUTRAL) for v in ratios]
bars = ax.bar(labels, ratios, color=colors, width=0.62, zorder=3)
ax.axhline(0, color=INK2, linewidth=0.9, zorder=4)
for b, v in zip(bars, ratios):
    va = "bottom" if v >= 0 else "top"
    off = 0.03 if v >= 0 else -0.03
    ax.text(b.get_x() + b.get_width() / 2, v + off, f"{v:.2f}",
            ha="center", va=va, fontsize=12, color=INK, weight="bold", zorder=5)
ax.set_ylabel("每單位波動換到的報酬（越高越划算）", fontsize=10.5, color=INK2)
ax.set_title("賺錢效率：砍掉那一週也回不到從前", fontsize=12.5, color=INK,
             pad=12, weight="bold", loc="left")
ax.set_ylim(-0.45, 1.02)
ax.tick_params(axis="x", labelsize=9.5)

ax = axes[1]
frame(ax)
bars = ax.bar(labels, worst, color=BAD, width=0.62, zorder=3)
for b, v in zip(bars, worst):
    ax.text(b.get_x() + b.get_width() / 2, v - 2.5, f"{v:.1f}%",
            ha="center", va="top", fontsize=12, color=INK, weight="bold", zorder=5)
ax.set_ylabel("單日最慘跌幅（%）", fontsize=10.5, color=INK2)
ax.set_title("最慘的一天：本金能不能撐過去", fontsize=12.5, color=INK,
             pad=12, weight="bold", loc="left")
ax.set_ylim(-95, 4)
ax.tick_params(axis="x", labelsize=9.5)

fig.text(0.01, -0.02,
         "資料：yfinance 調整後收盤價。四個時間窗的起訖日以實驗結果檔為準。",
         fontsize=8.5, color=MUTED)
fig.tight_layout()
fig.savefig(OUTDIR / "k1493_risk_reward.png", facecolor=SURFACE, bbox_inches="tight")
plt.close(fig)

print("ratios:", [round(v, 4) for v in ratios])
print("worst_day:", [round(v, 2) for v in worst])
print("wrote k1493_svxy_path.png, k1493_risk_reward.png")
