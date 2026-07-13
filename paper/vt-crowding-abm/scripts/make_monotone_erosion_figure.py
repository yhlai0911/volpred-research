"""
Generate Figure 1 (fig_monotone_erosion.png) for Paper 5 (vt-crowding-abm).

Supersedes scripts/make_tipping_figures.py's fig_tipping_point.png, which drew
shaded "safe zone" / "tipping zone" bands. Those bands encoded the Sharpe-only
detector's discrete-threshold reading, which the exogenous sup-Wald redesign
(K1471, M=500) overturned: the detector rejects flatness in all five cells but
locates no internal break. A figure that shades a tipping zone therefore asserts
a conclusion the data do not support, so the bands are gone.

Outputs
-------
paper/vt-crowding-abm/figures/fig_monotone_erosion.png

Data source (single binding, no transcribed constants)
------------------------------------------------------
experiments/k1471_vt_crowding_redesign/k1471_full_results.json
  cells.cell1_baseline.treatments.VT_baseline.per_adoption.<phi>.sharpe.mean
  cells.cell1_baseline.treatments.VT_baseline.per_adoption.<phi>.sharpe.boot_ci.{ci_lo,ci_hi}

The plotted values are the same ones printed in Table~\\ref{tab:vt_monotone_curve}.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt

PAPER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PAPER_DIR.parents[1]
RESULTS = (
    REPO_ROOT
    / "experiments/k1471_vt_crowding_redesign/k1471_full_results.json"
)
FIG_DIR = PAPER_DIR / "figures"
OUT = FIG_DIR / "fig_monotone_erosion.png"

CELL = "cell1_baseline"
TREATMENT = "VT_baseline"


def load_curve() -> tuple[list[float], list[float], list[float], list[float]]:
    with RESULTS.open(encoding="utf-8") as fh:
        data = json.load(fh)
    per_adoption = data["cells"][CELL]["treatments"][TREATMENT]["per_adoption"]

    rows = []
    for phi_label, payload in per_adoption.items():
        sharpe = payload["sharpe"]
        boot = sharpe["boot_ci"]
        rows.append(
            (
                float(phi_label.rstrip("%")),
                float(sharpe["mean"]),
                float(boot["ci_lo"]),
                float(boot["ci_hi"]),
            )
        )
    rows.sort(key=lambda r: r[0])
    phis, means, los, his = zip(*rows)
    return list(phis), list(means), list(los), list(his)


def main() -> None:
    phis, means, los, his = load_curve()
    yerr_lo = [m - lo for m, lo in zip(means, los)]
    yerr_hi = [hi - m for m, hi in zip(means, his)]

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.errorbar(
        phis,
        means,
        yerr=[yerr_lo, yerr_hi],
        fmt="o-",
        color="#1f4e79",
        ecolor="#1f4e79",
        elinewidth=1.2,
        capsize=4,
        markersize=5,
        linewidth=1.6,
        label="VT Sharpe (mean of 500 MC paths)",
    )
    ax.axhline(0.0, color="grey", linewidth=0.8, linestyle="--", zorder=0)

    ax.set_xlabel(r"VT adoption $\phi$ (\% of agents)".replace("\\%", "%"))
    ax.set_ylabel("Sharpe ratio")
    ax.set_title(
        "VT Sharpe declines monotonically with adoption\n"
        "(canonical cell $\\lambda$=0.005, $\\gamma$=200; path-bootstrap 95% CIs)"
    )
    ax.set_xticks(phis)
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.legend(loc="upper right", frameon=False)
    fig.tight_layout()

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=200)
    print(f"[fig] wrote {OUT.relative_to(REPO_ROOT)}")
    for phi, m, lo, hi in zip(phis, means, los, his):
        print(f"  phi={phi:5.0f}%  sharpe={m:+.3f}  CI=[{lo:+.3f}, {hi:+.3f}]")


if __name__ == "__main__":
    main()
