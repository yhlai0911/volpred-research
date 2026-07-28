#!/usr/bin/env python3
"""Charts for the K1406 general-audience draft.

Every plotted value is read programmatically from
experiments/k1406/k1406_results.json — nothing is hard-coded here.

Run:
    uv run python storage/drafts/assets/k1406_general_figs.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "experiments" / "k1406" / "k1406_results.json"
OUT = REPO / "storage" / "drafts" / "assets"

# Chinese font — avoid tofu boxes on macOS.
for cand in ("Heiti TC", "Songti TC", "PingFang TC", "Arial Unicode MS"):
    try:
        font_manager.findfont(cand, fallback_to_default=False)
        plt.rcParams["font.family"] = cand
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

D = json.loads(SRC.read_text(encoding="utf-8"))
R = D["results"]

CELLS = ["SPY_1y", "SPY_3y", "0050.TW_1y", "0050.TW_3y"]
LABELS = ["美股\n一年", "美股\n三年", "台股\n一年", "台股\n三年"]

INK = "#1b1b1f"
BLUE = "#2f6f9f"
SAND = "#c9a227"
GREY = "#8a8f98"


def fig_win_rates() -> Path:
    """Total-return win rate vs capital-efficiency win rate, four cells."""
    fv = [R[c]["group_a"]["overall"]["lump_win_rate_fv"] * 100 for c in CELLS]
    irr = [R[c]["group_a"]["overall"]["lump_win_rate_irr"] * 100 for c in CELLS]

    fig, ax = plt.subplots(figsize=(8.4, 4.8), dpi=200)
    x = range(len(CELLS))
    w = 0.36
    b1 = ax.bar([i - w / 2 for i in x], fv, w, color=BLUE, label="總報酬（期末金額）勝率")
    b2 = ax.bar([i + w / 2 for i in x], irr, w, color=SAND, label="資金效率（每塊錢年化）勝率")

    ax.axhline(50, color=GREY, lw=1.2, ls="--", zorder=0)
    ax.text(-0.42, 44.5, "五成＝擲硬幣", color=GREY, fontsize=9, ha="left")

    for bars in (b1, b2):
        for bar in bars:
            ax.annotate(f"{bar.get_height():.1f}%",
                        (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        ha="center", va="bottom", fontsize=9, color=INK)

    ax.set_xticks(list(x))
    ax.set_xticklabels(LABELS, fontsize=10)
    ax.set_ylabel("一次投入贏過分批投入的路徑比例（%）", fontsize=10)
    ax.set_ylim(0, 88)
    ax.set_title("同一批路徑，換個口徑就換個答案", fontsize=13, pad=12)
    ax.legend(frameon=False, fontsize=9, loc="upper left", ncols=2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()

    out = OUT / "k1406_general_winrate_two_yardsticks.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_dip_cost() -> Path:
    """Waiting-for-a-dip: win rate and idle-cash share at the one-tenth threshold."""
    win = [R[c]["group_b"]["dip_10pct"]["overall"]["dip_win_rate_fv"] * 100 for c in CELLS]
    drag = [R[c]["group_b"]["dip_10pct"]["overall"]["mean_cash_drag"] * 100 for c in CELLS]

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.4), dpi=200)

    ax = axes[0]
    bars = ax.bar(LABELS, win, color=BLUE, width=0.6)
    ax.axhline(50, color=GREY, lw=1.2, ls="--", zorder=0)
    for bar in bars:
        ax.annotate(f"{bar.get_height():.1f}%",
                    (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_ylim(0, 66)
    ax.set_ylabel("等回檔贏過照表操課的路徑比例（%）", fontsize=10)
    ax.set_title("等回檔的勝率，四格全低於五成", fontsize=12, pad=10)
    ax.spines[["top", "right"]].set_visible(False)

    ax = axes[1]
    bars = ax.bar(LABELS, drag, color=SAND, width=0.6)
    for bar in bars:
        ax.annotate(f"{bar.get_height():.1f}%",
                    (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_ylim(0, 80)
    ax.set_ylabel("錢平均躺在帳戶裡的時間比例（%）", fontsize=10)
    ax.set_title("代價：等待期間錢沒在市場裡", fontsize=12, pad=10)
    ax.spines[["top", "right"]].set_visible(False)

    fig.suptitle("回檔一成才進場：勝率與閒置成本", fontsize=13, y=1.02)
    fig.tight_layout()

    out = OUT / "k1406_general_dip_cost.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for p in (fig_win_rates(), fig_dip_cost()):
        print("wrote", p.relative_to(REPO))
