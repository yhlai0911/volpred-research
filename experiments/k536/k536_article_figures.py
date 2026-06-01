#!/usr/bin/env python3
"""Create reader-facing charts for K536."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
RESULTS = json.loads((ROOT / "k536_evt_var_results.json").read_text())

MODEL_ORDER = [
    "GJR-Normal",
    "GJR-Student-t",
    "GJR-EVT",
    "HAR-Normal",
    "HAR-EVT",
    "HistSim",
]

MODEL_LABELS = {
    "GJR-Normal": "GJR\nNormal",
    "GJR-Student-t": "GJR\nStudent-t",
    "GJR-EVT": "GJR\nEVT",
    "HAR-Normal": "HAR\nNormal",
    "HAR-EVT": "HAR\nEVT",
    "HistSim": "HistSim",
}


def plot_violation_rates() -> None:
    eval_1 = RESULTS["evaluation"]["0.01"]
    eval_25 = RESULTS["evaluation"]["0.025"]
    vals_1 = [eval_1[m]["violation_rate"] * 100 for m in MODEL_ORDER]
    vals_25 = [eval_25[m]["violation_rate"] * 100 for m in MODEL_ORDER]
    x = np.arange(len(MODEL_ORDER))
    width = 0.36

    fig, ax = plt.subplots(figsize=(10.4, 5.6))
    ax.bar(x - width / 2, vals_1, width, label="1% target", color="#1f77b4")
    ax.bar(x + width / 2, vals_25, width, label="2.5% target", color="#ff7f0e")
    ax.axhline(1.0, color="#1f77b4", linestyle="--", linewidth=1.4, alpha=0.7)
    ax.axhline(2.5, color="#ff7f0e", linestyle="--", linewidth=1.4, alpha=0.7)
    ax.text(len(x) - 0.3, 1.07, "expected 1%", color="#1f77b4", ha="right", fontsize=9)
    ax.text(len(x) - 0.3, 2.57, "expected 2.5%", color="#ff7f0e", ha="right", fontsize=9)

    for i, v in enumerate(vals_1):
        ax.text(i - width / 2, v + 0.12, f"{v:.2f}%", ha="center", va="bottom", fontsize=8)
    for i, v in enumerate(vals_25):
        ax.text(i + width / 2, v + 0.12, f"{v:.2f}%", ha="center", va="bottom", fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_LABELS[m] for m in MODEL_ORDER])
    ax.set_ylabel("Observed violation rate")
    ax.set_title("K536: HAR only becomes calibrated after adding EVT")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.18)
    ax.set_ylim(0, max(vals_25) * 1.2)
    fig.tight_layout()
    fig.savefig(ROOT / "k536_violation_rates.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_trinity_scores() -> None:
    rankings = RESULTS["rankings"]
    scores = [rankings[m] for m in MODEL_ORDER]
    colors = ["#9ecae1", "#9ecae1", "#9ecae1", "#fdae6b", "#2ca02c", "#c7c7c7"]

    fig, ax = plt.subplots(figsize=(9.8, 5.2))
    bars = ax.bar(range(len(MODEL_ORDER)), scores, color=colors)
    for bar, score in zip(bars, scores):
        ax.text(bar.get_x() + bar.get_width() / 2, score + 0.18, f"{score}", ha="center", fontsize=9)

    ax.set_xticks(range(len(MODEL_ORDER)))
    ax.set_xticklabels([MODEL_LABELS[m] for m in MODEL_ORDER])
    ax.set_ylabel("Score across 1% and 2.5% checks")
    ax.set_title("K536: HAR-EVT is the only model that clears both levels")
    ax.grid(axis="y", alpha=0.18)
    ax.set_ylim(0, max(scores) * 1.2)
    fig.tight_layout()
    fig.savefig(ROOT / "k536_trinity_scores.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    plot_violation_rates()
    plot_trinity_scores()
