#!/usr/bin/env python3
"""Create reader-facing charts for K698."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
RESULTS = json.loads((ROOT / "k698_results.json").read_text())


def plot_strategy_comparison() -> None:
    strategies = RESULTS["strategies"]
    names = [s["name"] for s in strategies]
    labels = [
        "BH\n50/50",
        "Daily\ncontra",
        "VIX+\ncontra",
        "Weekly\ncontra",
        "5d MR",
        "5d MR\n+ VIX",
        "12/VIX",
    ]
    sharpe_net = [s["sharpe_net"] for s in strategies]
    mdd_net = [abs(s["max_dd_net"]) * 100 for s in strategies]

    x = np.arange(len(names))
    width = 0.36

    fig, ax = plt.subplots(figsize=(11.0, 5.6))
    ax.bar(x - width / 2, sharpe_net, width, label="Net Sharpe", color="#1f77b4")
    ax2 = ax.twinx()
    ax2.bar(x + width / 2, mdd_net, width, label="Net max drawdown %", color="#ff9896", alpha=0.82)

    for i, val in enumerate(sharpe_net):
        ax.text(i - width / 2, val + 0.015, f"{val:.3f}", ha="center", fontsize=8, color="#1f77b4")
    for i, val in enumerate(mdd_net):
        ax2.text(i + width / 2, val + 0.8, f"{val:.1f}%", ha="center", fontsize=8, color="#c0392b")

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Net Sharpe")
    ax2.set_ylabel("Net max drawdown")
    ax.set_title("K698: a simple daily contrarian tilt beat the common baselines")
    ax.grid(axis="y", alpha=0.18)
    ax.set_ylim(0, max(sharpe_net) * 1.22)
    ax2.set_ylim(0, max(mdd_net) * 1.18)

    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, frameon=False, fontsize=8, loc="upper right")

    fig.tight_layout()
    fig.savefig(ROOT / "k698_strategy_comparison.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_turnover_tradeoff() -> None:
    daily = RESULTS["sensitivity_daily_threshold"]
    weekly = RESULTS["sensitivity_weekly_threshold"]

    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.8))

    for ax, rows, title, best in [
        (axes[0], daily, "Daily trigger variants", RESULTS["sensitivity_daily_best"]),
        (axes[1], weekly, "Weekly trigger variants", RESULTS["sensitivity_weekly_best"]),
    ]:
        turnover = [r["turnover_ann"] for r in rows]
        sharpe = [r["sharpe_net"] for r in rows]
        active = [r["pct_active"] for r in rows]
        sc = ax.scatter(turnover, sharpe, c=active, cmap="viridis", s=55, alpha=0.85)
        ax.scatter(
            [best["turnover_ann"]],
            [best["sharpe_net"]],
            marker="*",
            s=260,
            color="#d62728",
            edgecolor="black",
            linewidth=0.6,
            zorder=5,
        )
        ax.text(
            best["turnover_ann"] + 0.25,
            best["sharpe_net"] + 0.01,
            f"best {best['sharpe_net']:.3f}",
            fontsize=8,
            color="#d62728",
        )
        ax.axhline(RESULTS["strategies"][0]["sharpe_net"], color="#7f7f7f", linestyle="--", linewidth=1.2)
        ax.set_xlabel("Annual turnover")
        ax.set_ylabel("Net Sharpe")
        ax.set_title(title)
        ax.grid(alpha=0.18)

    cbar = fig.colorbar(sc, ax=axes.ravel().tolist(), shrink=0.94)
    cbar.set_label("Active days %")
    fig.suptitle("More trading did not automatically create more net alpha", fontsize=13)
    fig.tight_layout()
    fig.savefig(ROOT / "k698_turnover_tradeoff.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    plot_strategy_comparison()
    plot_turnover_tradeoff()
