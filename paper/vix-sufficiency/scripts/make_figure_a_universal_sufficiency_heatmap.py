"""Generate Figure A — universal cross-asset alt-data sufficiency heatmap.

Source data: K1203 7-asset PIT panorama (pit_shift0), which integrates
K1116c (SPY), K1116f (GLD/TLT/BTC-USD), K1201 (QQQ/USO), K1203 (EEM).

Each cell is the DM-HLN t-statistic of (challenger spec vs native-IV baseline).
Positive  = challenger improves on native IV.
Negative  = native IV is sufficient (alt-data harmful).
Harvey (2016) threshold marked at |t| = 3.0.

Output: paper/vix-sufficiency/figures/figure_a_universal_sufficiency_heatmap.png
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import TwoSlopeNorm

# --- paths ---
PAPER_DIR = Path(__file__).resolve().parents[1]
K1203_RESULTS = (
    PAPER_DIR.parent.parent
    / "experiments"
    / "k1203"
    / "k1203_results.json"
)
OUT_PNG = PAPER_DIR / "figures" / "figure_a_universal_sufficiency_heatmap.png"


def main() -> None:
    with K1203_RESULTS.open() as f:
        payload = json.load(f)

    panorama = payload["panorama_7asset_pit_shift0"]

    # Asset order: equity (SPY, QQQ, EEM), bonds (TLT), commodities (GLD, USO), crypto (BTC-USD)
    assets = ["SPY", "QQQ", "EEM", "TLT", "GLD", "USO", "BTC-USD"]
    # Spec column order — base is AR(1)+native IV check; alt-data are EPU, FinStress, All
    spec_cols = [
        ("base_t", "Base\n(AR1 vs native IV)"),
        ("epu_t", "EPU\n(+ uncertainty)"),
        ("finstress_t", "FinStress\n(+ NFCI/STLFSI)"),
        ("all_t", "All Alt-Data"),
    ]

    matrix = np.array(
        [[panorama[a][s] for s, _ in spec_cols] for a in assets],
        dtype=float,
    )

    fig, ax = plt.subplots(figsize=(8.5, 5.6))

    # Diverging colormap centered at zero; Harvey threshold at +/-3
    vmax = max(4.0, float(np.nanmax(np.abs(matrix))))
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax)
    im = ax.imshow(matrix, cmap="RdBu_r", norm=norm, aspect="auto")

    # Annotate cells with t-stat values, highlight Harvey-passing cells with bold + box
    for i, asset in enumerate(assets):
        for j, (key, _label) in enumerate(spec_cols):
            t = matrix[i, j]
            passes_harvey = abs(t) > 3.0
            color = "white" if abs(t) > 2.5 else "black"
            weight = "bold" if passes_harvey else "normal"
            ax.text(
                j, i,
                f"{t:+.2f}",
                ha="center", va="center",
                color=color, fontsize=10, fontweight=weight,
            )
            if passes_harvey:
                # outline the cell to flag |t|>3
                rect = plt.Rectangle(
                    (j - 0.48, i - 0.48), 0.96, 0.96,
                    fill=False, edgecolor="gold", linewidth=2.0,
                )
                ax.add_patch(rect)

    # Axes
    ax.set_xticks(range(len(spec_cols)))
    ax.set_xticklabels([lbl for _, lbl in spec_cols], fontsize=9)
    ax.set_yticks(range(len(assets)))
    ax.set_yticklabels(assets, fontsize=10)
    ax.set_xlabel("Forecast specification (challenger)", fontsize=11)
    ax.set_ylabel("Asset (prediction target)", fontsize=11)
    ax.set_title(
        "Figure A. Universal cross-asset alt-data sufficiency heatmap\n"
        "DM-HLN $t$-stat: challenger spec vs native-IV baseline (PIT shift0, $N_\\mathrm{OOS}=170$ wk)",
        fontsize=11,
    )

    # Colorbar with Harvey threshold marks
    cbar = fig.colorbar(im, ax=ax, shrink=0.85, pad=0.02)
    cbar.set_label("DM $t$-stat (positive = alt-data improves)", fontsize=10)
    for tval in (-3.0, 3.0):
        cbar.ax.axhline(tval, color="gold", linewidth=1.5, linestyle="--")

    # Footnote
    fig.text(
        0.5, 0.01,
        "Gold border + bold = $|t|>3.0$ Harvey (2016) threshold. "
        "Sources: K1116c (SPY), K1116f (GLD/TLT/BTC-USD), K1201 (QQQ/USO), K1203 (EEM).",
        ha="center", fontsize=8, style="italic",
    )

    plt.tight_layout(rect=[0, 0.04, 1, 1])
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PNG, dpi=200, bbox_inches="tight")
    plt.close(fig)

    print(f"[figure_a] wrote {OUT_PNG}")
    print(f"[figure_a] matrix shape = {matrix.shape}, range = [{matrix.min():.2f}, {matrix.max():.2f}]")

    # Sanity-print Harvey-passing cells
    harvey_passes = []
    for i, a in enumerate(assets):
        for j, (k, _) in enumerate(spec_cols):
            if abs(matrix[i, j]) > 3.0:
                harvey_passes.append((a, k, float(matrix[i, j])))
    print(f"[figure_a] Harvey |t|>3 cells: {len(harvey_passes)}")
    for a, k, t in harvey_passes:
        sign = "alt-data WINS" if t > 0 else "native IV WINS"
        print(f"  - {a:>8} {k:>13}: t={t:+.3f}  ({sign})")


if __name__ == "__main__":
    main()
