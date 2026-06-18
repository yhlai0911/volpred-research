"""Generate supplemental article figures for K1512.

The core experiment script already creates fig_a_dml_theta_with_ci.png.
This helper derives an article-facing p-value chart directly from
k1512_results.json so feed drafts can include two real figures.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "k1512_results.json"
OUT_PATH = HERE / "fig_b_pvalue_gate.png"


def main() -> None:
    data = json.loads(RESULTS_PATH.read_text())
    factors = ["MTUM", "VLUE", "QUAL"]
    pvals = [data["per_factor"][f]["nw_p"] for f in factors]
    alpha = data["per_factor"][factors[0]]["bonferroni_alpha"]

    fig, ax = plt.subplots(figsize=(7, 4.2))
    colors = ["#5b8def" if p < alpha else "#b8bec8" for p in pvals]
    ax.bar(factors, pvals, color=colors, edgecolor="#293241", linewidth=0.9)
    ax.axhline(alpha, color="#d1495b", linestyle="--", linewidth=1.3)
    ax.text(
        2.45,
        alpha + 0.015,
        f"3-factor gate = {alpha:.3f}",
        color="#8d1f33",
        ha="right",
        va="bottom",
        fontsize=9,
    )
    for i, p in enumerate(pvals):
        ax.text(i, p + 0.018, f"{p:.3f}", ha="center", va="bottom", fontsize=10)
    ax.set_ylim(0, max(pvals) * 1.22)
    ax.set_ylabel("Two-sided NW p-value")
    ax.set_title("K1512 — none of the factor ETF effects pass the 3-factor gate")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT_PATH, dpi=140)
    plt.close(fig)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
