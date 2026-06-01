#!/usr/bin/env python3
"""Create reader-facing charts for K538."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
RESULTS = json.loads((ROOT / "k538_meta_labeling_results.json").read_text())

MODEL_ORDER = ["logistic", "xgboost", "random_forest"]
MODEL_LABELS = {
    "logistic": "Logistic",
    "xgboost": "XGBoost",
    "random_forest": "Random\nForest",
}


def plot_auc_and_cross_oos() -> None:
    auc_vals = [RESULTS["model_summary"][m]["auc_mean"] for m in MODEL_ORDER]
    meta_sharpes = [RESULTS["model_summary"][m]["meta_sharpe_mean"] for m in MODEL_ORDER]
    vt_sharpe = RESULTS["model_summary"]["logistic"]["vt_sharpe_mean"]
    bh_sharpe = RESULTS["model_summary"]["logistic"]["bh_sharpe_mean"]

    x = np.arange(len(MODEL_ORDER))

    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.8))

    ax = axes[0]
    bars = ax.bar(x, auc_vals, color=["#9ecae1", "#fdae6b", "#74c476"], width=0.6)
    ax.axhline(0.5, color="#444444", linestyle="--", linewidth=1.3, alpha=0.8)
    ax.text(len(x) - 0.35, 0.502, "coin flip", color="#444444", ha="right", va="bottom", fontsize=9)
    for bar, val in zip(bars, auc_vals):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 0.004, f"{val:.3f}", ha="center", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_LABELS[m] for m in MODEL_ORDER])
    ax.set_ylim(0.45, 0.55)
    ax.set_ylabel("Cross-OOS AUC")
    ax.set_title("K538: all three classifiers stayed near coin-flip AUC")
    ax.grid(axis="y", alpha=0.18)

    ax = axes[1]
    width = 0.22
    ax.bar(x - width, meta_sharpes, width, label="Meta strategy", color="#1f77b4")
    ax.bar(x, [vt_sharpe] * len(x), width, label="VT baseline", color="#ff7f0e")
    ax.bar(x + width, [bh_sharpe] * len(x), width, label="Buy & hold", color="#7f7f7f")
    for i, val in enumerate(meta_sharpes):
        ax.text(i - width, val + 0.03, f"{val:.3f}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_LABELS[m] for m in MODEL_ORDER])
    ax.set_ylabel("Average Sharpe across 3 OOS periods")
    ax.set_title("Cross-OOS average looked fine, but it still did not beat B&H")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.grid(axis="y", alpha=0.18)
    ax.set_ylim(0, max(meta_sharpes + [vt_sharpe, bh_sharpe]) * 1.18)

    fig.tight_layout()
    fig.savefig(ROOT / "k538_auc_cross_oos.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_walkforward_behavior() -> None:
    wf = RESULTS["walkforward_results"]
    meta_sharpes = [wf[m]["meta_sharpe"] for m in MODEL_ORDER]
    vt_usage = [wf[m]["vt_usage_pct"] * 100 for m in MODEL_ORDER]
    switches = [wf[m]["n_switches"] for m in MODEL_ORDER]
    vt_sharpe = wf["logistic"]["vt_sharpe"]
    bh_sharpe = wf["logistic"]["bh_sharpe"]

    x = np.arange(len(MODEL_ORDER))

    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.8))

    ax = axes[0]
    width = 0.22
    ax.bar(x - width, meta_sharpes, width, label="Meta strategy", color="#1f77b4")
    ax.bar(x, [vt_sharpe] * len(x), width, label="VT baseline", color="#ff7f0e")
    ax.bar(x + width, [bh_sharpe] * len(x), width, label="Buy & hold", color="#7f7f7f")
    for i, val in enumerate(meta_sharpes):
        ax.text(i - width, val + 0.02, f"{val:.3f}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_LABELS[m] for m in MODEL_ORDER])
    ax.set_ylabel("Walk-forward Sharpe")
    ax.set_title("Walk-forward: none of the models improved on plain VT")
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    ax.grid(axis="y", alpha=0.18)
    ax.set_ylim(0, max([vt_sharpe, bh_sharpe] + meta_sharpes) * 1.18)

    ax = axes[1]
    width = 0.34
    ax.bar(x - width / 2, vt_usage, width, label="VT usage %", color="#2ca02c")
    ax2 = ax.twinx()
    ax2.bar(x + width / 2, switches, width, label="Switches", color="#d62728", alpha=0.78)
    for i, val in enumerate(vt_usage):
        ax.text(i - width / 2, val + 2.5, f"{val:.1f}%", ha="center", fontsize=8, color="#2ca02c")
    for i, val in enumerate(switches):
        ax2.text(i + width / 2, val + 22, f"{val}", ha="center", fontsize=8, color="#d62728")
    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_LABELS[m] for m in MODEL_ORDER])
    ax.set_ylabel("Share of days using VT")
    ax2.set_ylabel("Number of switches")
    ax.set_title("The models drifted into three weak behaviors")
    ax.grid(axis="y", alpha=0.18)
    ax.set_ylim(0, 100)
    ax2.set_ylim(0, max(switches) * 1.18)

    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, frameon=False, fontsize=8, loc="upper left")

    fig.tight_layout()
    fig.savefig(ROOT / "k538_walkforward_behavior.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    plot_auc_and_cross_oos()
    plot_walkforward_behavior()
