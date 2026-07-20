#!/usr/bin/env python3
"""K942 general-audience companion article charts.

Numbers source: /tmp/k942_source.md (= content of mile_2cfa32a4).
  Regime table : VIX<15 +8.7% / VIX 15-25 +0.5% / VIX>25 +17.3%
  Horizon table: 1 week +18.4% / 1 day +6.4% / 1 month -5.7%
Sample: SPY, 2016-2025, yfinance.

Outputs: storage/drafts/assets/vix_when_useful_regime.png
         storage/drafts/assets/vix_when_useful_horizon.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path("/Users/yhlai0911/volpred-research")
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style(dpi=160)

OUT = ROOT / "storage" / "drafts" / "assets"
OUT.mkdir(parents=True, exist_ok=True)

C_POS = "#2E6FA8"
C_HI = "#D9822B"
C_FLAT = "#9AA5B1"
C_NEG = "#C0392B"


def _style(ax) -> None:
    ax.axhline(0, color="#333333", lw=1.0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", color="#DDDDDD", lw=0.7)
    ax.set_axisbelow(True)


def _label(ax, bars, vals) -> None:
    for b, v in zip(bars, vals):
        off = 0.6 if v >= 0 else -1.4
        ax.text(
            b.get_x() + b.get_width() / 2,
            v + off,
            f"{v:+.1f}%",
            ha="center",
            va="bottom" if v >= 0 else "top",
            fontsize=13,
            fontweight="bold",
            color="#222222",
        )


# ── 圖 1：市場狀態 × 預測改善 ────────────────────────────────────
labels = ["極端平靜\n(恐慌指數 < 15)", "一般水準\n(恐慌指數 15-25)", "極端恐慌\n(恐慌指數 > 25)"]
vals = [8.7, 0.5, 17.3]
colors = [C_POS, C_FLAT, C_HI]

fig, ax = plt.subplots(figsize=(8.0, 4.8))
bars = ax.bar(labels, vals, color=colors, width=0.55)
_label(ax, bars, vals)
_style(ax)
ax.set_ylim(-2, 21)
ax.set_ylabel("預測準確度改善幅度", fontsize=11)
ax.set_title("恐慌指數只在兩端有用，中間那段幾乎是零", fontsize=15, fontweight="bold", pad=14)
ax.text(
    1, 4.6, "中間區間等同沒用", ha="center", va="bottom", fontsize=11, color="#5A6570"
)
fig.text(0.01, 0.02, "樣本：SPY，2016-2025（資料來源：yfinance）。此為樣本內觀察幅度，原始分析未附顯著性檢定。", fontsize=8.5, color="#666666")
fig.tight_layout(rect=(0, 0.045, 1, 1))
fig.savefig(OUT / "vix_when_useful_regime.png", bbox_inches="tight")
plt.close(fig)

# ── 圖 2：預測窗口 × 預測改善 ────────────────────────────────────
labels2 = ["1 日", "1 週", "1 個月"]
vals2 = [6.4, 18.4, -5.7]
colors2 = [C_POS, C_HI, C_NEG]

fig, ax = plt.subplots(figsize=(8.0, 4.8))
bars = ax.bar(labels2, vals2, color=colors2, width=0.5)
_label(ax, bars, vals2)
_style(ax)
ax.set_ylim(-10, 23)
ax.set_ylabel("預測準確度改善幅度", fontsize=11)
ax.set_title("看得越遠越沒用：一個月的窗口會倒扣", fontsize=15, fontweight="bold", pad=14)
ax.annotate(
    "",
    xy=(1.28, 18.4),
    xytext=(1.28, -5.7),
    arrowprops=dict(arrowstyle="<->", color="#777777", lw=1.2, linestyle=(0, (4, 3))),
)
ax.text(1.36, 6.0, "落差 24.1\n個百分點", fontsize=11, color="#555555", ha="left")
fig.text(0.01, 0.02, "樣本：SPY，2016-2025（資料來源：yfinance）。此為樣本內觀察幅度，原始分析未附顯著性檢定。", fontsize=8.5, color="#666666")
fig.tight_layout(rect=(0, 0.045, 1, 1))
fig.savefig(OUT / "vix_when_useful_horizon.png", bbox_inches="tight")
plt.close(fig)

print("wrote:", OUT / "vix_when_useful_regime.png")
print("wrote:", OUT / "vix_when_useful_horizon.png")
