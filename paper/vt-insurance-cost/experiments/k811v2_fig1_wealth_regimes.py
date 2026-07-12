#!/usr/bin/env python3
"""Figure 1: cumulative wealth of S0/S1/S2/S4 (log scale) with VoV-regime shading.

Data: bundled snapshot CSVs in paper/vt-insurance-cost/data/ (raw Close,
2012-2024 VVIX-reliable sample). Strategy rules and CAGR convention are the
reproduce.py / K811v2 ones via k811v2_paper_panel.

Gate: the script asserts each plotted curve's K811v2-style CAGR against the
Table 1 values (S0 12.51 / S1 7.11 / S2 11.14 / S4 7.89, tolerance 0.1pp)
BEFORE writing any figure file. Assert failure -> no figure.

Output: figures/fig1_wealth_regimes.pdf + .png (300 dpi).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FixedLocator, NullFormatter, ScalarFormatter

# k811v2_paper_panel inserts the paper dir into sys.path; import it first so
# reproduce.py resolves when this script runs from any cwd.
from k811v2_paper_panel import build_daily_panel  # noqa: I001

import reproduce  # noqa: E402

PAPER_DIR = Path(__file__).resolve().parent.parent
FIG_DIR = PAPER_DIR / "figures"

# Table 1 (main.tex:129) CAGR anchors, % per annum, tolerance 0.1pp.
TABLE1_CAGR = {"S0": 12.51, "S1": 7.11, "S2": 11.14, "S4": 7.89}
CAGR_TOL_PP = 0.10

EVENTS = [
    ("2018-02-05", "Volmageddon\n(Feb 2018)"),
    ("2020-03-16", "COVID-19 crash\n(Mar 2020)"),
]


def wealth_curve(log_rets: np.ndarray) -> np.ndarray:
    cum = np.exp(np.nancumsum(log_rets))
    return cum / cum[0]  # k811 convention: normalize by first cumulative point


def contiguous_spans(mask: np.ndarray) -> list[tuple[int, int]]:
    """Index spans [start, end] (inclusive) of True runs in a boolean mask."""
    spans = []
    start = None
    for i, flag in enumerate(mask):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            spans.append((start, i - 1))
            start = None
    if start is not None:
        spans.append((start, len(mask) - 1))
    return spans


def main() -> None:
    panel = build_daily_panel()
    series = {
        "S0": panel.s0_net,
        "S1": panel.s1_net,
        "S2": panel.s2_net,
        "S4": panel.s4_net,
    }

    # --- Gate: reproduce Table 1 CAGRs before drawing anything ---
    for name, rets in series.items():
        cagr = reproduce.compute_k811_style_cagr(rets)
        diff = cagr - TABLE1_CAGR[name]
        assert abs(diff) <= CAGR_TOL_PP, (
            f"{name} CAGR {cagr:.3f}% deviates from Table 1 "
            f"{TABLE1_CAGR[name]}% by {diff:+.3f}pp (> {CAGR_TOL_PP}pp)"
        )
        print(f"  CAGR gate {name}: computed {cagr:.3f}% vs Table 1 "
              f"{TABLE1_CAGR[name]}% (diff {diff:+.3f}pp) OK")

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["STIXGeneral", "Times New Roman", "DejaVu Serif"],
            "mathtext.fontset": "stix",
            "font.size": 9,
            "axes.linewidth": 0.7,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "pdf.fonttype": 42,
        }
    )

    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    dates = panel.dates.to_pydatetime()

    # Background: high-VoV regime (lagged VoV z-score > 1), light shading.
    high_vov = np.nan_to_num(panel.vov_zscore_lag, nan=0.0) > 1.0
    for start, end in contiguous_spans(high_vov):
        ax.axvspan(dates[start], dates[end], color="0.90", lw=0, zorder=0)

    # Grayscale-distinguishable: lightness + line style jointly encode identity.
    styles = {
        "S0": dict(color="0.0", ls="-", lw=1.5, label="S0: Buy-and-hold SPY"),
        "S1": dict(color="0.45", ls="--", lw=1.2, label="S1: Always VT (12/VIX)"),
        "S2": dict(color="0.2", ls="-.", lw=1.4, label="S2: VoV-conditional VT"),
        "S4": dict(color="0.55", ls=":", lw=1.4, label="S4: 50/50 SPY/GLD"),
    }
    for name, rets in series.items():
        ax.plot(dates, wealth_curve(rets), zorder=3, **styles[name])

    for date_str, label in EVENTS:
        event_date = np.datetime64(date_str)
        ax.axvline(event_date.astype("datetime64[D]").astype(object),
                   color="0.3", ls=(0, (1, 2)), lw=0.8, zorder=2)
        ax.annotate(
            label,
            xy=(event_date.astype("datetime64[D]").astype(object), 1.0),
            xycoords=("data", "axes fraction"),
            xytext=(4, -4),
            textcoords="offset points",
            ha="left",
            va="top",
            fontsize=7.5,
            color="0.25",
        )

    ax.set_yscale("log")
    yticks = [0.8, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0]
    ax.yaxis.set_major_locator(FixedLocator(yticks))
    fmt = ScalarFormatter()
    fmt.set_scientific(False)
    ax.yaxis.set_major_formatter(fmt)
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_ylabel("Cumulative wealth (initial = 1, log scale)")

    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(dates[0], dates[-1])

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="0.85", lw=0.5, zorder=1)
    ax.legend(loc="upper left", frameon=False, fontsize=8)

    # Shading key, kept textual to stay journal-sober.
    ax.annotate(
        "Shaded: high-VoV regime (lagged VVIX $z$-score $> 1$)",
        xy=(0.0, -0.14),
        xycoords="axes fraction",
        fontsize=7.5,
        color="0.35",
    )

    fig.tight_layout()
    FIG_DIR.mkdir(exist_ok=True)
    for suffix in ("pdf", "png"):
        out = FIG_DIR / f"fig1_wealth_regimes.{suffix}"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        print(f"  wrote {out}")

    for name, rets in series.items():
        print(f"  terminal wealth {name}: {wealth_curve(rets)[-1]:.3f}")


if __name__ == "__main__":
    main()
