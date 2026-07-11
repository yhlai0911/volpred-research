#!/usr/bin/env python3
"""K1639 general-audience article charts.

Source: experiments/k1639/k1639_results.json + experiments/k1639/data/k1639_net_returns.csv
Outputs: storage/drafts/assets/K1639_*.png
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams["font.sans-serif"] = ["PingFang HK", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path("/Users/yhlai0911/volpred-research")
EXP = ROOT / "experiments" / "k1639"
OUT = ROOT / "storage" / "drafts" / "assets"
OUT.mkdir(parents=True, exist_ok=True)

res = json.loads((EXP / "k1639_results.json").read_text())
net = res["net_performance"]

LABEL = {
    "equal_weight": "等權重",
    "inverse_vol": "反波動加權",
    "erc_risk_parity": "ERC 風險平價",
    "min_variance": "最小變異",
    "hrp": "HRP 階層式",
    "herc_erc": "HERC 階層式",
    "nco_minvar": "NCO 階層式",
    "schur_block_mv": "Schur 階層式",
}
SIMPLE = {"equal_weight", "inverse_vol", "erc_risk_parity", "min_variance"}
C_SIMPLE = "#2E6FA8"
C_HIER = "#D9822B"

# ── 圖1 Sharpe 長條圖 ────────────────────────────────────────────────
order = sorted(net, key=lambda k: net[k]["sharpe"], reverse=True)
vals = [net[k]["sharpe"] for k in order]
cols = [C_SIMPLE if k in SIMPLE else C_HIER for k in order]

fig, ax = plt.subplots(figsize=(9.2, 5.0), dpi=170)
bars = ax.bar(range(len(order)), vals, color=cols, width=0.66)
for i, v in enumerate(vals):
    ax.text(i, v + 0.012, f"{v:.3f}", ha="center", fontsize=9.5, color="#333")
ax.set_xticks(range(len(order)))
ax.set_xticklabels([LABEL[k] for k in order], fontsize=9.5)
ax.set_ylabel("樣本外淨夏普值（扣除交易成本）", fontsize=10)
ax.set_ylim(0, max(vals) * 1.16)
ax.set_title(
    "圖1　4,585 天樣本外實測：階層式方法沒有一個擠進前兩名",
    fontsize=12.5,
    pad=13,
)
ax.grid(axis="y", alpha=0.25, linewidth=0.7)
ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
handles = [
    plt.Rectangle((0, 0), 1, 1, color=C_SIMPLE),
    plt.Rectangle((0, 0), 1, 1, color=C_HIER),
]
ax.legend(handles, ["傳統方法", "階層式方法"], fontsize=9.5, frameon=False, loc="upper right")
fig.text(
    0.012,
    0.015,
    "資料：yfinance 調整後收盤價，11 檔 ETF，2008-04-11 至 2026-07-02（4,585 個交易日）。實驗 K1639。",
    fontsize=8,
    color="#666",
)
fig.tight_layout(rect=(0, 0.035, 1, 1))
fig.savefig(OUT / "K1639_sharpe_bar.png")
plt.close(fig)

# ── 圖2 累積淨值 ────────────────────────────────────────────────────
rets = pd.read_csv(EXP / "data" / "k1639_net_returns.csv", parse_dates=["Date"]).set_index("Date")
cum = (1 + rets).cumprod()

show = ["equal_weight", "inverse_vol", "erc_risk_parity", "hrp", "herc_erc", "nco_minvar"]
style = {
    "equal_weight": dict(color="#1B4F72", lw=2.2),
    "inverse_vol": dict(color="#2E86C1", lw=2.0),
    "erc_risk_parity": dict(color="#5DADE2", lw=2.0),
    "hrp": dict(color="#D9822B", lw=1.8),
    "herc_erc": dict(color="#E8A54B", lw=1.8),
    "nco_minvar": dict(color="#B03A2E", lw=1.6, ls="--"),
}

fig, ax = plt.subplots(figsize=(9.6, 5.4), dpi=170)
for k in show:
    ax.plot(cum.index, cum[k], label=f"{LABEL[k]}（{net[k]['sharpe']:.2f}）", **style[k])
ax.set_ylabel("1 元本金的累積淨值（扣成本）", fontsize=10)
ax.set_title(
    "圖2　把 1 元放進去，18 年後長成多少（括號內為淨夏普值）",
    fontsize=12.5,
    pad=13,
)
ax.legend(fontsize=9.2, frameon=False, loc="upper left")
ax.grid(alpha=0.25, linewidth=0.7)
ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
fig.text(
    0.012,
    0.015,
    "資料：yfinance 調整後收盤價，11 檔 ETF，每月再平衡，交易成本 5 bps。實驗 K1639。",
    fontsize=8,
    color="#666",
)
fig.tight_layout(rect=(0, 0.035, 1, 1))
fig.savefig(OUT / "K1639_cumulative.png")
plt.close(fig)

# ── 圖3 有效持股數 vs 換手率 ────────────────────────────────────────
OFFSET = {
    "equal_weight": (0, 10, "center"),
    "inverse_vol": (0, 10, "center"),
    "erc_risk_parity": (0, 10, "center"),
    "min_variance": (-10, -6, "right"),
    "hrp": (0, -32, "center"),
    "herc_erc": (0, 10, "center"),
    "nco_minvar": (0, -32, "center"),
    "schur_block_mv": (0, 10, "center"),
}

fig, ax = plt.subplots(figsize=(9.2, 5.2), dpi=170)
for k in net:
    x = net[k]["avg_effective_n"]
    y = net[k]["annual_turnover"] * 100
    c = C_SIMPLE if k in SIMPLE else C_HIER
    ax.scatter(x, y, s=150, color=c, zorder=3, edgecolor="white", linewidth=1.2)
    dx, dy, ha = OFFSET[k]
    ax.annotate(
        f"{LABEL[k]}\n夏普 {net[k]['sharpe']:.2f}",
        (x, y),
        textcoords="offset points",
        xytext=(dx, dy),
        ha=ha,
        fontsize=8.8,
        color="#333",
    )
ax.set_xlabel("實際上真正分散到幾檔（有效持股數，最多 11）", fontsize=10)
ax.set_ylabel("每年換手率（%）", fontsize=10)
ax.set_title(
    "圖3　越用力精算共變異數的方法，持股越集中、換手越兇（右下角兩個幾乎不估）",
    fontsize=12,
    pad=13,
)
ax.set_xlim(0.6, 12.4)
ax.set_ylim(-12, 205)
ax.grid(alpha=0.25, linewidth=0.7)
ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
fig.text(
    0.012,
    0.015,
    "資料：K1639 樣本外 4,585 天平均權重與月頻再平衡換手率。有效持股數 = 1 / 權重平方和。",
    fontsize=8,
    color="#666",
)
fig.tight_layout(rect=(0, 0.035, 1, 1))
fig.savefig(OUT / "K1639_concentration.png")
plt.close(fig)

print("wrote:", *(p.name for p in sorted(OUT.glob("K1639_*.png"))))
