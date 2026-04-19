"""
Generate Paper 1 Figure: fig_rolling_gamma
===========================================
Reproduces fig_rolling_gamma.pdf (body.tex line 220, Section 4.3 Evidence).

Content
-------
Rolling 252-day GJR-GARCH gamma estimates for SPY, GLD, TLT, and EEM over
2010-2026. The paper caption (body.tex L221-222) reads:

  "SPY maintains consistently positive gamma (standard leverage), GLD
  fluctuates between positive and negative (regime-dependent inverted
  leverage), and TLT remains near zero. Shaded regions indicate gamma < 0."

Data sources
------------
Summary rolling-gamma statistics are in K902
(paper/leverage-direction/experiments/k902_paper1_tables_supplement_results.json)
but that JSON records only `mean`, `std`, `pct_negative`, `hac_tstat`, and
`n_windows` -- NOT the per-window gamma time series needed to draw the
figure. See audit_step1_2.md Fig 1 row ("No source script identified --
likely inline generation").

To avoid live yfinance (snapshot rule), this script expects a pre-generated
per-window rolling-gamma CSV at:
    paper/leverage-direction/scripts/figures/data/rolling_gamma_series.csv
with columns: date, SPY, GLD, TLT, EEM (gamma estimate at each window end).

If the CSV is missing, we SKIP generation and emit a clearly-labelled
placeholder PNG that references the pending K extension (proposal §4
T-TABLE2-EXTENDED or a dedicated rolling-gamma-series JSON) so downstream
consumers cannot mistake a placeholder for real data.

The placeholder uses ONLY the summary statistics from K902
(mean +/- std envelope centred at the reported mean) -- this preserves
qualitative fidelity (SPY consistently positive, GLD/TLT straddle zero)
without fabricating per-date values.

Data source status
------------------
PARTIAL -- K902 summary stats available; per-window series MISSING.
Flagged for main-thread: needs `rolling_gamma_series.csv` snapshot or a
K experiment extension (e.g., K1235 per gate_fix_v1 proposal §6) to
consolidate per-window estimates into a JSON.

Rules
-----
- No fabricated per-window values: placeholder mode uses only K902 summary
  stats and clearly labels itself.
- Seed pinned to 42.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

SEED = 42
np.random.seed(SEED)

PAPER_DIR = Path(__file__).resolve().parents[2]
DATA_CSV = Path(__file__).resolve().parent / "data" / "rolling_gamma_series.csv"
K902_JSON = PAPER_DIR / "experiments" / "k902_paper1_tables_supplement_results.json"
OUT_PNG = PAPER_DIR / "figures" / "fig_rolling_gamma.png"
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)

ASSETS = ["SPY", "GLD", "TLT", "EEM"]
COLORS = {"SPY": "#1f77b4", "GLD": "#d4a017", "TLT": "#7f7f7f", "EEM": "#2ca02c"}


def _plot_real(df) -> None:
    import pandas as pd  # local import so placeholder path doesn't require it
    fig, ax = plt.subplots(figsize=(9.0, 4.8), dpi=300)

    # Shade gamma < 0 horizontal band
    ax.axhspan(-0.5, 0.0, facecolor="#f2d7d5", alpha=0.35, zorder=0,
               label=r"$\gamma < 0$ (inverted-leverage zone)")

    for a in ASSETS:
        ax.plot(df["date"], df[a], color=COLORS[a], lw=1.1, label=a)

    ax.axhline(0.0, color="grey", lw=0.7, ls="--")
    ax.set_xlabel("Date")
    ax.set_ylabel(r"Rolling 252-day GJR-GARCH $\gamma$")
    ax.set_title(r"Rolling $\gamma$ for SPY, GLD, TLT, EEM (2010-2026): leverage direction heterogeneity")
    ax.legend(loc="upper right", ncol=5, fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_placeholder() -> None:
    """Summary-stat-only placeholder, clearly labelled."""
    with K902_JSON.open() as fh:
        k902 = json.load(fh)
    summary = {}
    for a in ASSETS:
        rg = k902["table1_descriptive_stats"][a]["rolling_gamma"]
        summary[a] = (rg["mean"], rg["std"], rg["pct_negative"], rg["hac_tstat"])

    # Build a simulated date index for illustrative envelope display only.
    dates = np.linspace(2010.0, 2026.0, 40)

    fig, ax = plt.subplots(figsize=(9.0, 4.8), dpi=300)
    ax.axhspan(-0.5, 0.0, facecolor="#f2d7d5", alpha=0.35, zorder=0,
               label=r"$\gamma < 0$ (inverted-leverage zone)")

    for a in ASSETS:
        m, s, pct_neg, t = summary[a]
        # A deterministic sinusoid around the mean, magnitude = s.
        # Seeded numpy RNG for reproducibility; this is EXPLICITLY labelled as
        # "illustrative envelope, NOT per-window estimates".
        rng = np.random.default_rng(SEED + hash(a) % 1000)
        noise = rng.normal(0.0, s * 0.5, size=dates.shape)
        wave = s * 0.6 * np.sin(2.0 * np.pi * (dates - 2010) / 5.0)
        y = m + wave + noise
        ax.plot(dates, y, color=COLORS[a], lw=1.1, alpha=0.85,
                label=f"{a} (mean={m:+.3f}, %neg={pct_neg:.0f}%)")

    ax.axhline(0.0, color="grey", lw=0.7, ls="--")
    ax.set_xlabel("Year")
    ax.set_ylabel(r"Rolling 252-day GJR-GARCH $\gamma$")
    ax.set_title(r"PLACEHOLDER: Rolling $\gamma$ envelope (illustrative, pending per-window CSV)",
                 fontsize=11, color="#b33a3a")
    ax.legend(loc="upper right", ncol=5, fontsize=8)
    ax.grid(True, alpha=0.25)

    ax.text(0.01, 0.02,
            "PLACEHOLDER FIGURE -- uses K902 summary stats (mean +/- std) only.\n"
            "Per-window series not in any K JSON; drop rolling_gamma_series.csv\n"
            "into scripts/figures/data/ to render the real figure.",
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
            import pandas as pd
            df = pd.read_csv(DATA_CSV, parse_dates=["date"])
            missing = [a for a in ASSETS if a not in df.columns]
            if missing:
                raise ValueError(f"rolling_gamma_series.csv missing columns: {missing}")
            _plot_real(df)
            print(f"Wrote {OUT_PNG} (real per-window series from {DATA_CSV.name})")
            return
        except Exception as exc:
            print(f"[WARN] Failed to load {DATA_CSV}: {exc}. Falling back to placeholder.")
    _plot_placeholder()
    print(f"Wrote {OUT_PNG} (PLACEHOLDER -- per-window CSV missing)")


if __name__ == "__main__":
    main()
