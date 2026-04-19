"""
Generate Paper 1 Figure: fig_vix_garch_ratio
=============================================
Reproduces fig_vix_garch_ratio.pdf (body.tex line 227, Section 4.3 / Hybrid VT).

Content
-------
Time series of the VIX / GARCH conditional-volatility ratio (2014-2026).
Caption (body.tex L228-229): "The horizontal line at 1.3 marks the Hybrid VT
switching threshold (~ long-run VRP median of 1.31). Ratio spikes precede
major drawdowns; the Hybrid VT switches to VIX-based weights when the ratio
exceeds this threshold."

Data sources
------------
The per-day (VIX, GARCH-sigma) series is not currently consolidated in any
paper/leverage-direction/experiments/*.json. K799 contains per-day VaR /
QLIKE series but only for 2023-24 OOS (see layer_3.results keys); K902
contains the static gamma params per asset but no time series.

Script requires a pre-generated CSV at:
    paper/leverage-direction/scripts/figures/data/vix_garch_ratio.csv
with columns: date, vix (%), garch_sigma_ann (%), ratio.

If the CSV is missing, we fall back to a clearly-labelled PLACEHOLDER that
generates a synthetic path with known spike dates (2015, 2018, 2020, 2022)
anchored to the long-run VRP median 1.31. The placeholder is explicitly
marked and cannot be mistaken for real data.

Data source status
------------------
MISSING -- vix_garch_ratio.csv needs to be produced from a run that stores
per-day VIX alongside per-day GARCH sigma. Candidate K: extend K799 to
emit a daily-series JSON, or new K (e.g. K1236) pairing downloaded VIX
snapshot with the GJR fit of K902.

Rules
-----
- No live yfinance: placeholder mode is SYNTHETIC and clearly labelled.
- Seed pinned to 42.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

SEED = 42

PAPER_DIR = Path(__file__).resolve().parents[2]
DATA_CSV = Path(__file__).resolve().parent / "data" / "vix_garch_ratio.csv"
OUT_PNG = PAPER_DIR / "figures" / "fig_vix_garch_ratio.png"
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)

THRESHOLD = 1.30  # Hybrid VT switching threshold (paper L228)


def _plot_real() -> None:
    import pandas as pd
    df = pd.read_csv(DATA_CSV, parse_dates=["date"]).sort_values("date")
    ratio = df["ratio"].values

    fig, ax = plt.subplots(figsize=(9.5, 4.5), dpi=300)

    # Shade high-ratio periods
    above = ratio > THRESHOLD
    ax.fill_between(df["date"], THRESHOLD, ratio, where=above,
                    color="#e74c3c", alpha=0.25, step="mid",
                    label=f"Ratio > {THRESHOLD} (VIX-switch on)")

    ax.plot(df["date"], ratio, color="#1f77b4", lw=0.9, label="VIX / GARCH ratio")
    ax.axhline(THRESHOLD, color="#c0392b", lw=1.0, ls="--",
               label=f"Hybrid VT switching threshold = {THRESHOLD}")
    ax.axhline(1.0, color="grey", lw=0.7, ls=":", alpha=0.7)

    ax.set_xlabel("Date")
    ax.set_ylabel("VIX / GARCH-sigma (annualised-to-annualised)")
    ax.set_title("VIX/GARCH ratio (2014-2026): spikes precede major drawdowns")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_placeholder() -> None:
    """Synthetic ratio path anchored to known VRP median + stylised crisis spikes."""
    rng = np.random.default_rng(SEED)
    # Monthly frequency 2014-01 to 2026-04 (~148 months)
    months = np.arange(148)
    t = 2014 + months / 12.0

    # Baseline mean-reverting process around VRP median 1.31
    noise = rng.normal(0.0, 0.07, size=months.shape)
    baseline = 1.31 + 0.5 * noise  # std ~ 0.035 which is low

    # Known crisis spike centres (year): Aug-2015 China, Feb-2018 vol,
    # Dec-2018 Q4, Mar-2020 COVID, Nov-2021 Omicron, Jun-2022 rate, Apr-2025 tariff.
    spike_centres = [2015.67, 2018.15, 2018.95, 2020.25, 2021.85,
                     2022.45, 2025.30]
    spike_mags = [1.2, 1.0, 1.1, 2.4, 0.9, 1.4, 0.8]
    for c, m in zip(spike_centres, spike_mags):
        baseline += m * np.exp(-((t - c) / 0.25) ** 2)

    ratio = baseline

    fig, ax = plt.subplots(figsize=(9.5, 4.5), dpi=300)
    above = ratio > THRESHOLD
    ax.fill_between(t, THRESHOLD, ratio, where=above,
                    color="#e74c3c", alpha=0.25, step="mid",
                    label=f"Ratio > {THRESHOLD} (VIX-switch on)")
    ax.plot(t, ratio, color="#1f77b4", lw=0.9, label="VIX / GARCH ratio (synthetic)")
    ax.axhline(THRESHOLD, color="#c0392b", lw=1.0, ls="--",
               label=f"Hybrid VT switching threshold = {THRESHOLD}")
    ax.axhline(1.0, color="grey", lw=0.7, ls=":", alpha=0.7)

    ax.set_xlabel("Year")
    ax.set_ylabel("VIX / GARCH-sigma (annualised-to-annualised)")
    ax.set_title("PLACEHOLDER: VIX/GARCH ratio (synthetic, pending per-day CSV)",
                 color="#b33a3a")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.25)
    ax.text(0.01, 0.02,
            "PLACEHOLDER -- synthetic path anchored to VRP median 1.31 with\n"
            "stylised crisis spikes. Drop vix_garch_ratio.csv into\n"
            "scripts/figures/data/ to render the real figure.",
            transform=ax.transAxes, fontsize=7.5, color="#b33a3a",
            verticalalignment="bottom",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#fff7f7",
                      edgecolor="#b33a3a", alpha=0.95))
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    if DATA_CSV.exists():
        try:
            _plot_real()
            print(f"Wrote {OUT_PNG} (real ratio series from {DATA_CSV.name})")
            return
        except Exception as exc:
            print(f"[WARN] Failed to read {DATA_CSV}: {exc}. Using placeholder.")
    _plot_placeholder()
    print(f"Wrote {OUT_PNG} (PLACEHOLDER -- vix_garch_ratio.csv missing)")


if __name__ == "__main__":
    main()
