#!/usr/bin/env python3
"""Render the K1704 cross-proxy QLIKE comparison from the result artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


MODEL_ORDER = ["HAR_RV5", "EWMA_R2", "GJR_GARCH"]
MODEL_LABELS = {"HAR_RV5": "HAR-RV5", "EWMA_R2": "EWMA-R²", "GJR_GARCH": "GJR-GARCH"}
TARGET_LABELS = {
    "rv_1min": "RV 1m",
    "rv_5min": "RV 5m",
    "rv_10min": "RV 10m",
    "parkinson": "Parkinson",
    "r2_day": "Day r²",
    "consensus_weighted": "Consensus",
}


def render(results_path: Path, output_path: Path) -> None:
    results = json.loads(results_path.read_text(encoding="utf-8"))
    targets = list(TARGET_LABELS)
    values = {
        model: [results["targets"][target]["metrics"][model]["qlike"] for target in targets]
        for model in MODEL_ORDER
    }

    x = np.arange(len(targets))
    width = 0.24
    colors = ["#176B87", "#64CCC5", "#DAA520"]
    fig, ax = plt.subplots(figsize=(11.5, 6.4), constrained_layout=True)
    for offset, model, color in zip((-width, 0.0, width), MODEL_ORDER, colors):
        ax.bar(x + offset, values[model], width, label=MODEL_LABELS[model], color=color)

    ax.set_title("K1704 — HAR ranking is stable across six volatility targets", loc="left", weight="bold")
    ax.set_ylabel("Out-of-sample QLIKE (lower is better)")
    ax.set_xticks(x, [TARGET_LABELS[target] for target in targets])
    ax.grid(axis="y", alpha=0.22)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncols=3, loc="upper left")
    ax.text(
        0.0,
        -0.16,
        "Common OOS ledger: 2,016 days, 2018-02-01 to 2026-07-14. "
        "Each target's 10% MCS is the singleton {HAR-RV5}.",
        transform=ax.transAxes,
        fontsize=9,
        color="#444444",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    parser.add_argument("--results", type=Path, default=here / "K1704_results.json")
    parser.add_argument("--output", type=Path, default=here / "K1704_qlike_by_proxy.png")
    args = parser.parse_args()
    render(args.results, args.output)


if __name__ == "__main__":
    main()
