"""
Generate Paper 1 Figure: fig_cumulative_returns
================================================
Reproduces fig_cumulative_returns.pdf (body.tex line 246, Section 4.5
Cross-Asset Results).

Content
-------
Cumulative log-return paths for SPY Buy-and-Hold vs. Hybrid VT (2014-2026).
Caption (body.tex L247-248): "The Hybrid VT achieves comparable terminal
wealth with substantially reduced drawdowns, particularly during the 2020
COVID crash, 2022 rate-hiking cycle, and 2025-26 Iran/Hormuz crisis."

Data sources
------------
Daily SPY returns and Hybrid VT weights are not consolidated in any current
paper-folder JSON. K799 has per-day OOS diagnostics for 2023-24 only.

Script requires a pre-generated CSV:
    paper/leverage-direction/scripts/figures/data/spy_bh_vs_vt.csv
with columns: date, bh_cum (cumulative log-return of SPY B&H), vt_cum
(cumulative log-return of Hybrid VT, with same rebalancing/smoothing as paper
Section 3.5: target 10% ann, 5-day MA, weight clip [0,1.5]).

If missing, the placeholder mode generates two synthetic paths:
  (a) B&H: empirical headline SPY CAGR ~ 9.5%/yr and realised-vol ~ 18%/yr
  (b) VT: ~1 percentage point lower CAGR, ~35% lower drawdowns (Section 4.5
      results: VT is Sharpe-equivalent with 1/3 less MDD).
and labels itself clearly as synthetic.

Data source status
------------------
MISSING -- spy_bh_vs_vt.csv needs production from a daily-series backtest.
Main-thread action: extend reproduce.py or create K1237 to dump B&H and VT
daily cumulative returns (2014-01 to 2026-04) as CSV.

Rules
-----
- No live yfinance; placeholder is SYNTHETIC and labelled.
- Seed pinned to 42.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

SEED = 42

PAPER_DIR = Path(__file__).resolve().parents[2]
DATA_CSV = Path(__file__).resolve().parent / "data" / "spy_bh_vs_vt.csv"
OUT_PNG = PAPER_DIR / "figures" / "fig_cumulative_returns.png"
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)

# Crisis annotations (body.tex L247-248 highlights three)
CRISES = [
    ("COVID-19",       2020.20, 2020.50),
    ("2022 Rate Hike", 2022.00, 2022.80),
    ("Iran/Hormuz",    2025.30, 2026.10),
]


def _plot_from_csv() -> None:
    import pandas as pd
    df = pd.read_csv(DATA_CSV, parse_dates=["date"]).sort_values("date")
    fig, ax = plt.subplots(figsize=(9.5, 4.8), dpi=300)

    for (label, y0, y1) in CRISES:
        ax.axvspan(pd.to_datetime(f"{int(y0)}-{int((y0 % 1)*12+1):02d}-01"),
                   pd.to_datetime(f"{int(y1)}-{int((y1 % 1)*12+1):02d}-01"),
                   color="#f7c3c3", alpha=0.35, zorder=0)

    ax.plot(df["date"], df["bh_cum"], color="#888888", lw=1.1,
            label="SPY Buy & Hold")
    ax.plot(df["date"], df["vt_cum"], color="#1f77b4", lw=1.3,
            label="Hybrid VT (GJR+VIX switch)")

    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative log return")
    ax.set_title("SPY Buy-and-Hold vs Hybrid VT: comparable terminal wealth, smaller drawdowns (2014-2026)")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_placeholder() -> None:
    """Synthetic 2014-2026 daily paths with headline-consistent moments."""
    rng = np.random.default_rng(SEED)
    # 2014-01 to 2026-04 ~ 3100 trading days
    n = 3100
    t = np.linspace(2014.0, 2026.33, n)

    # B&H: 9.5%/yr drift, 18%/yr vol daily
    mu_bh = 0.095 / 252
    sigma_bh = 0.18 / np.sqrt(252)
    shocks = rng.normal(0.0, 1.0, size=n)
    r_bh = mu_bh + sigma_bh * shocks

    # Inject crisis drawdowns
    for (_, y0, y1) in CRISES:
        mask = (t >= y0) & (t <= y1)
        # Scale shocks up to produce larger negative mean during the crisis
        r_bh[mask] -= 0.005 * np.abs(rng.normal(0.0, 1.0, size=mask.sum()))

    # VT: lower vol (target 10%) implies smaller moves; use 60% shock and
    # avoid full crisis hit due to volatility scaling
    r_vt = 0.60 * r_bh + 0.0002
    for (_, y0, y1) in CRISES:
        mask = (t >= y0) & (t <= y1)
        # VT reduces exposure during crises -- attenuate negative shocks
        r_vt[mask] *= 0.55

    bh_cum = np.cumsum(r_bh)
    vt_cum = np.cumsum(r_vt)

    fig, ax = plt.subplots(figsize=(9.5, 4.8), dpi=300)
    for (label, y0, y1) in CRISES:
        ax.axvspan(y0, y1, color="#f7c3c3", alpha=0.35, zorder=0)
        ax.text((y0 + y1) / 2, ax.get_ylim()[1] * 0.95, label,
                fontsize=8, ha="center", color="#7a2323",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor="none", alpha=0.7))

    ax.plot(t, bh_cum, color="#888888", lw=1.1, label="SPY Buy & Hold")
    ax.plot(t, vt_cum, color="#1f77b4", lw=1.3, label="Hybrid VT (GJR+VIX switch)")

    ax.set_xlabel("Year")
    ax.set_ylabel("Cumulative log return")
    ax.set_title("PLACEHOLDER: SPY B&H vs Hybrid VT (synthetic, pending daily-series CSV)",
                 color="#b33a3a")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.25)

    ax.text(0.01, 0.02,
            "PLACEHOLDER -- synthetic paths with headline moments\n"
            "(SPY CAGR ~9.5%, VT CAGR ~8%). Drop spy_bh_vs_vt.csv into\n"
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
            _plot_from_csv()
            print(f"Wrote {OUT_PNG} (real series from {DATA_CSV.name})")
            return
        except Exception as exc:
            print(f"[WARN] Failed to read {DATA_CSV}: {exc}. Using placeholder.")
    _plot_placeholder()
    print(f"Wrote {OUT_PNG} (PLACEHOLDER -- spy_bh_vs_vt.csv missing)")


if __name__ == "__main__":
    main()
