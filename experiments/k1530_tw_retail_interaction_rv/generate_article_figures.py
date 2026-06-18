"""Generate supplemental article figures for K1530 retail-interaction pilot."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt


HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "k1530_tw_retail_interaction_rv_results.json"
OUT_PATH = HERE / "fig_b_oos_dm_harvey_gate.png"


def _label(spec: dict) -> str:
    target = "squared return" if spec["target"] == "r2_ann" else "Parkinson range"
    proxy = "residual retail" if spec["signal"].startswith("retail_residual") else "margin activity"
    return f"{target}\n{proxy}"


def main() -> None:
    data = json.loads(RESULTS_PATH.read_text())
    specs = data["specs"]
    labels = [_label(s) for s in specs]
    dm_t = [s["dm_t_augmented_vs_baseline"] for s in specs]

    fig, ax = plt.subplots(figsize=(8.4, 4.5))
    colors = ["#4f7cac" if t > -3 else "#2f9e44" for t in dm_t]
    ax.barh(labels, dm_t, color=colors, edgecolor="#243447", linewidth=0.8)
    ax.axvline(0, color="#222222", linewidth=0.8)
    ax.axvline(-3, color="#d1495b", linestyle="--", linewidth=1.4)
    ax.text(-3, -0.55, "Harvey gate = -3", color="#8d1f33", ha="center", va="bottom", fontsize=9)
    for i, t in enumerate(dm_t):
        ax.text(t - 0.08, i, f"{t:.2f}", ha="right", va="center", fontsize=10)
    ax.set_xlim(min(-3.35, min(dm_t) - 0.35), 0.25)
    ax.set_xlabel("DM t for augmented model vs baseline (more negative is better)")
    ax.set_title("K1530 — OOS gains are suggestive but do not clear Harvey's gate")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT_PATH, dpi=150)
    plt.close(fig)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
