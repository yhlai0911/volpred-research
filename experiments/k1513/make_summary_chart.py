"""K1513 secondary chart — DM p-value distribution by regime.

Visualizes why 0/36 cells survive Bonferroni:
- Left panel: high-vol regime p-value histogram + Bonferroni / raw alpha lines.
- Right panel: low-vol regime p-value histogram + same lines.

Output: experiments/k1513/k1513_pvalue_distribution.png
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = ROOT / "experiments" / "k1513"
RESULTS = EXP_DIR / "k1513_results.json"
OUT = EXP_DIR / "k1513_pvalue_distribution.png"


def main() -> None:
    data = json.loads(RESULTS.read_text())
    cells = data["cells"]
    p_high = np.array([c["dm_p_high"] for c in cells], dtype=float)
    p_low = np.array([c["dm_p_low"] for c in cells], dtype=float)
    alpha_raw = data["summary"]["alpha_raw"]
    alpha_bonf = data["summary"]["alpha_bonferroni"]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    bins = np.linspace(0.0, 1.0, 21)

    for ax, p_vals, title in (
        (axes[0], p_high, f"高波動 regime (n_cells={len(p_high)})"),
        (axes[1], p_low, f"低波動 regime (n_cells={len(p_low)})"),
    ):
        ax.hist(p_vals, bins=bins, color="#4477aa", edgecolor="white", alpha=0.85)
        ax.axvline(alpha_raw, color="#bb5566", linestyle="--", linewidth=1.4,
                   label=f"raw α={alpha_raw}")
        ax.axvline(alpha_bonf, color="#cc3311", linestyle="-", linewidth=1.4,
                   label=f"Bonferroni α≈{alpha_bonf:.4f}")
        ax.set_xlabel("DM p-value")
        ax.set_title(title)
        ax.grid(axis="y", linestyle=":", alpha=0.5)
        ax.set_xlim(0.0, 1.0)
        below_raw = int((p_vals < alpha_raw).sum())
        below_bonf = int((p_vals < alpha_bonf).sum())
        ax.text(0.97, 0.92,
                f"< raw α: {below_raw} cells\n< Bonferroni α: {below_bonf} cells",
                transform=ax.transAxes, ha="right", va="top",
                fontsize=10,
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))
        ax.legend(loc="upper right", fontsize=9, bbox_to_anchor=(0.97, 0.78))

    axes[0].set_ylabel("Cell 數")
    fig.suptitle(
        "K1513 — DM p-value 分佈：raw α 抓到 4 cell，Bonferroni 過後歸零",
        fontsize=12, y=1.02,
    )

    # Use a font that handles CJK — fallback to default if unavailable.
    plt.rcParams["font.family"] = ["PingFang TC", "Heiti TC", "Arial Unicode MS",
                                   "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig.tight_layout()
    fig.savefig(OUT, dpi=140, bbox_inches="tight")
    print(f"saved: {OUT}")


if __name__ == "__main__":
    main()
