#!/usr/bin/env python3
"""
Create reader-facing figures for the K905 article.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / "k905_quantile_vol_forecast_results.json"

MODEL_LABELS = {
    "M1_Normal": "Normal",
    "M2_StudentT": "Student-t",
    "M3_FHS": "FHS",
    "M4_CAViaR": "CAViaR",
    "M5_QuantHAR": "QuantHAR",
}


def load_results() -> dict:
    return json.loads(RESULTS_PATH.read_text())


def make_pinball_chart(results: dict) -> None:
    ranking_1 = results["pinball_ranking"]["1pct"]
    ranking_5 = results["pinball_ranking"]["5pct"]
    models = [item["model"] for item in ranking_1]
    labels = [MODEL_LABELS[m] for m in models]
    vals_1 = [item["pinball"] * 10000 for item in ranking_1]
    map_5 = {item["model"]: item["pinball"] * 10000 for item in ranking_5}
    vals_5 = [map_5[m] for m in models]

    x = np.arange(len(models))
    width = 0.36

    fig, ax = plt.subplots(figsize=(10, 5.6))
    ax.bar(x - width / 2, vals_1, width, label="1% tail", color="#1f77b4")
    ax.bar(x + width / 2, vals_5, width, label="5% tail", color="#ff7f0e")

    for i, v in enumerate(vals_1):
        ax.text(i - width / 2, v + 0.02, f"{v:.2f}", ha="center", va="bottom", fontsize=9)
    for i, v in enumerate(vals_5):
        ax.text(i + width / 2, v + 0.02, f"{v:.2f}", ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Pinball loss x 10,000")
    ax.set_title("K905: simpler FHS still has the lowest tail-loss score")
    ax.legend(frameon=False)
    ax.set_ylim(0, max(vals_5) * 1.18)
    ax.grid(axis="y", alpha=0.18)
    fig.tight_layout()
    fig.savefig(ROOT / "k905_pinball_ranking.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def make_coverage_chart(results: dict) -> None:
    evaluation = results["evaluation"]
    models = list(MODEL_LABELS.keys())
    labels = [MODEL_LABELS[m] for m in models]
    violation_1 = [evaluation[m]["var_1pct"]["violation_rate"] * 100 for m in models]
    violation_5 = [evaluation[m]["var_5pct"]["violation_rate"] * 100 for m in models]

    x = np.arange(len(models))
    width = 0.36

    fig, ax = plt.subplots(figsize=(10, 5.8))
    ax.bar(x - width / 2, violation_1, width, label="Observed 1% breach rate", color="#2ca02c")
    ax.bar(x + width / 2, violation_5, width, label="Observed 5% breach rate", color="#d62728")
    ax.axhline(1.0, color="#2ca02c", linestyle="--", linewidth=1.5, alpha=0.7)
    ax.axhline(5.0, color="#d62728", linestyle="--", linewidth=1.5, alpha=0.7)
    ax.text(len(models) - 0.4, 1.08, "Target 1%", color="#2ca02c", ha="right", fontsize=9)
    ax.text(len(models) - 0.4, 5.08, "Target 5%", color="#d62728", ha="right", fontsize=9)

    for i, v in enumerate(violation_1):
        ax.text(i - width / 2, v + 0.08, f"{v:.2f}%", ha="center", va="bottom", fontsize=9)
    for i, v in enumerate(violation_5):
        ax.text(i + width / 2, v + 0.08, f"{v:.2f}%", ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Out-of-sample violation rate")
    ax.set_title("K905: fancy quantile models did not improve breach calibration")
    ax.legend(frameon=False)
    ax.set_ylim(0, max(violation_5) * 1.25)
    ax.grid(axis="y", alpha=0.18)
    fig.tight_layout()
    fig.savefig(ROOT / "k905_violation_rates.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    results = load_results()
    make_pinball_chart(results)
    make_coverage_chart(results)


if __name__ == "__main__":
    main()
