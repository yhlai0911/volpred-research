"""
Generate Paper 1 Figure: fig_vix_weight_timeline
=================================================
Reproduces fig_vix_weight_timeline.pdf (body.tex line 460, Section 4.8
Implied-Volatility Targeting).

Content
-------
Two-panel figure:
  Top: VIX level (2007-2026) with the sigma_target = 12% threshold line.
  Bottom: SPY weight from the 12/VIX rule, w_t = 12 / VIX_t (capped at 1.5
          per the paper's weight clip convention).
Caption (body.tex L461): "Crisis periods show weights of 15-30%."

Data sources
------------
VIX daily history is not bundled in any paper-folder JSON. The script
expects a pre-generated CSV:
    paper/leverage-direction/scripts/figures/data/vix_daily.csv
with columns: date, vix (%).

If missing, placeholder mode synthesises a VIX-like path (mean-reverting to
~19 with crisis spikes at known dates) explicitly labelled as synthetic.

Data source status
------------------
MISSING -- vix_daily.csv needs a bundled snapshot. A one-off yfinance pull
stored as CSV (with timestamp + fetch_date recorded) would be the natural
replication-package artefact. Main thread can do this.

Rules
-----
- No live yfinance at runtime; placeholder is SYNTHETIC and labelled.
- Seed pinned to 42.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

SEED = 42

PAPER_DIR = Path(__file__).resolve().parents[2]
DATA_CSV = PAPER_DIR / "data" / "vix_daily.csv"
OUT_PNG = PAPER_DIR / "figures" / "fig_vix_weight_timeline.png"
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)

SIGMA_TARGET = 12.0
WEIGHT_CAP = 1.5  # Paper Section 3.5 weight clip [0, 1.5]


def _build_figure(dates, vix, placeholder: bool) -> None:
    weight = np.clip(SIGMA_TARGET / np.maximum(vix, 1e-3), 0.0, WEIGHT_CAP)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9.5, 5.8), dpi=300,
                                    sharex=True, height_ratios=[1.0, 1.0])

    # Top: VIX
    ax1.plot(dates, vix, color="#1f77b4", lw=0.7, label="VIX")
    ax1.axhline(SIGMA_TARGET, color="#c0392b", lw=1.0, ls="--",
                label=fr"$\sigma_\mathrm{{target}}$ = {SIGMA_TARGET:.0f}%")
    ax1.set_ylabel("VIX level (%)")
    ax1.legend(loc="upper right", fontsize=9)
    ax1.grid(True, alpha=0.25)
    ax1.set_ylim(8, max(90, vix.max() * 1.05))

    # Bottom: 12/VIX weight
    ax2.fill_between(dates, 0, weight * 100.0, color="#2ca02c", alpha=0.4,
                     label=r"SPY weight = min($\sigma_\mathrm{target}$/VIX, 1.5) (in %)")
    ax2.axhline(100.0, color="grey", lw=0.8, ls=":", alpha=0.7)
    ax2.axhline(WEIGHT_CAP * 100.0, color="#c0392b", lw=0.8, ls=":", alpha=0.7,
                label=f"Weight cap = {int(WEIGHT_CAP*100)}%")
    ax2.set_ylabel("SPY weight (%)")
    ax2.set_xlabel("Year" if placeholder else "Date")
    ax2.legend(loc="upper right", fontsize=9)
    ax2.grid(True, alpha=0.25)
    ax2.set_ylim(0, WEIGHT_CAP * 110.0)

    title = r"VIX and SPY weight under 12/VIX rule (2007-2026)"
    if placeholder:
        title = "PLACEHOLDER: " + title + " (synthetic VIX, pending daily CSV)"
        fig.suptitle(title, fontsize=11.5,
                     color=("#b33a3a" if placeholder else "black"))
        ax2.text(0.01, 0.04,
                 "PLACEHOLDER -- synthetic VIX path with known spike dates.\n"
                 "Drop vix_daily.csv (date,vix) into scripts/figures/data/.",
                 transform=ax2.transAxes, fontsize=7.5, color="#b33a3a",
                 verticalalignment="bottom",
                 bbox=dict(boxstyle="round,pad=0.4", facecolor="#fff7f7",
                           edgecolor="#b33a3a", alpha=0.95))
    else:
        fig.suptitle(title, fontsize=11.5)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_real() -> None:
    import pandas as pd
    df = pd.read_csv(DATA_CSV, parse_dates=["date"]).sort_values("date")
    _build_figure(df["date"].values, df["vix"].values, placeholder=False)


def _plot_placeholder() -> None:
    rng = np.random.default_rng(SEED)
    # Daily 2007-01 to 2026-04, ~4850 trading days
    n = 4850
    t = np.linspace(2007.0, 2026.33, n)

    # OU-like process reverting to 19 with occasional spikes
    vix = np.empty(n)
    vix[0] = 20.0
    theta, mu, sigma = 0.08, 19.0, 0.9
    eps = rng.normal(0.0, 1.0, size=n)
    for i in range(1, n):
        vix[i] = vix[i-1] + theta * (mu - vix[i-1]) + sigma * eps[i]

    # Crisis spikes: GFC Oct 2008, Flash Aug 2011, China Aug 2015,
    # Feb 2018 vol, Dec 2018 Q4, COVID Mar 2020, 2022 rate, 2024-25 tariff
    spike_centres = [2008.78, 2011.62, 2015.67, 2018.15, 2018.95,
                     2020.22, 2022.45, 2025.30]
    spike_mags = [60.0, 25.0, 15.0, 25.0, 20.0, 55.0, 22.0, 25.0]
    spike_width = [0.05, 0.04, 0.03, 0.02, 0.03, 0.03, 0.03, 0.03]
    for c, m, w in zip(spike_centres, spike_mags, spike_width):
        vix += m * np.exp(-((t - c) / w) ** 2)

    vix = np.clip(vix, 8.0, 90.0)

    _build_figure(t, vix, placeholder=True)


def main() -> None:
    if DATA_CSV.exists():
        try:
            _plot_real()
            print(f"Wrote {OUT_PNG} (real series from {DATA_CSV.name})")
            return
        except Exception as exc:
            print(f"[WARN] Failed to read {DATA_CSV}: {exc}. Using placeholder.")
    _plot_placeholder()
    print(f"Wrote {OUT_PNG} (PLACEHOLDER -- vix_daily.csv missing)")


if __name__ == "__main__":
    main()
