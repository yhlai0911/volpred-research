"""K1711 figures. Reads the results JSON — never recomputes a number.

Labels are ASCII on purpose: matplotlib's default font has no CJK glyphs and
would render tofu boxes (docs/error_log.md §I).
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
FIGS = HERE / "figures"

MODEL_ORDER = ["RW", "AR1", "HAR", "HAR-A", "TimesFM", "TTM",
               "TimesFM-MZ", "TTM-MZ", "COMB-EW", "COMB-MZ", "COMB-GR"]
TSFM_BEARING = {"TimesFM", "TTM", "TimesFM-MZ", "TTM-MZ",
                "COMB-EW", "COMB-MZ", "COMB-GR"}


def _cells(results: dict, proxy: str, window: str = "pseudo_oos",
           horizon: int | None = None) -> list[dict]:
    cells = [c for c in results["cells"]
             if c["proxy"] == proxy and c["window"] == window]
    if horizon is not None:
        cells = [c for c in cells if c["horizon"] == horizon]
    return cells


def fig_mcs_membership(results: dict) -> None:
    """Primary-cell mean loss and MCS membership; never invent survivor p-values."""
    cells = _cells(results, "rv", horizon=1)
    fig, axes = plt.subplots(1, len(cells), figsize=(13.5, 6.2), constrained_layout=True)
    for ax, c in zip(np.atleast_1d(axes), cells):
        mean = c["mean_loss"]["qlike"]
        winner = min(mean.values())
        excess = np.array([[100 * (mean[m] / winner - 1)] for m in MODEL_ORDER])
        im = ax.imshow(excess, cmap="YlOrRd", vmin=0, vmax=max(25, float(excess.max())),
                       aspect="auto")
        survivors = set(c["mcs"]["qlike"]["superior_set_by_alpha"]["0.1"])
        ax.set_xticks([0], [f"{c['asset']}\nn={c['n_scored']}"])
        ax.set_yticks(range(len(MODEL_ORDER)), MODEL_ORDER, fontsize=8)
        for i, m in enumerate(MODEL_ORDER):
            ax.text(0, i, f"{excess[i, 0]:.1f}%", ha="center", va="center", fontsize=8,
                    fontweight="bold" if m in survivors else "normal")
            if m in survivors:
                ax.add_patch(plt.Rectangle((-.5, i - .5), 1, 1, fill=False,
                                           edgecolor="black", lw=2.0))
        ax.set_title("boxed = MCS survivor", fontsize=9)
        fig.colorbar(im, ax=ax, fraction=0.05, label="QLIKE excess vs cell winner (%)")
    fig.suptitle("K1711 primary MCS: TSFM-bearing models survive, but membership is not a win",
                 fontsize=12, fontweight="bold")
    fig.savefig(FIGS / "fig1_primary_mcs_membership.png", dpi=150)
    plt.close(fig)


def fig_cumulative_loss_diff(results: dict, series: dict) -> None:
    """Cumulative QLIKE(model) - QLIKE(HAR). Below zero = beating HAR.

    A real edge accumulates steadily; an artefact is one cliff on one day. The
    picture is the only honest way to tell those apart before trusting a t-stat.
    """
    assets = [c["asset"] for c in _cells(results, "rv", horizon=1)]
    fig, axes = plt.subplots(1, len(assets), figsize=(15, 4.4), constrained_layout=True)

    show = ["TimesFM-MZ", "TTM-MZ", "COMB-EW", "COMB-MZ", "COMB-GR"]
    for ax, asset in zip(np.atleast_1d(axes), assets):
        s = series[f"{asset}|h1|rv|pseudo_oos"]
        dates = pd.to_datetime(s["dates"])
        har = np.asarray(s["qlike"]["HAR"])
        for m in show:
            d = np.cumsum(np.asarray(s["qlike"][m]) - har)
            ax.plot(dates, d, lw=1.3, label=m)
        ax.axhline(0, color="black", lw=1.0)
        ax.set_title(f"{asset} (h=1)", fontsize=10)
        ax.tick_params(labelsize=8)
        ax.grid(alpha=0.25)
    np.atleast_1d(axes)[0].set_ylabel("cumulative QLIKE minus HAR")
    np.atleast_1d(axes)[-1].legend(fontsize=8, loc="upper left")

    fig.suptitle("Cumulative loss differential vs log-HAR (below 0 = better than HAR)",
                 fontsize=12, fontweight="bold")
    fig.savefig(FIGS / "fig2_cumulative_loss_diff.png", dpi=150)
    plt.close(fig)


def fig_proxy_robustness(results: dict) -> None:
    """Does the superior set survive swapping the evaluation proxy (RV -> r^2)?

    Patton (2011) establishes QLIKE ranking robustness for conditionally unbiased
    proxies. Squared open-to-close return meets that condition only under idealized
    assumptions such as zero conditional intraday mean; K1711 also floors exact zeros.
    This panel is therefore approximate proxy sensitivity, not an exact theorem check.
    """
    fig, ax = plt.subplots(figsize=(11, 5), constrained_layout=True)

    cells_rv = _cells(results, "rv", horizon=1)
    cols, grid = [], []
    for c in cells_rv:
        c_r2 = next(x for x in _cells(results, "r2", horizon=1)
                    if x["asset"] == c["asset"] and x["horizon"] == c["horizon"])
        in_rv = set(c["mcs"]["qlike"]["superior_set_by_alpha"]["0.1"])
        in_r2 = set(c_r2["mcs"]["qlike"]["superior_set_by_alpha"]["0.1"])
        cols.append(f"{c['asset']}\nh={c['horizon']}")
        grid.append([(2 if m in in_rv else 0) + (1 if m in in_r2 else 0)
                     for m in MODEL_ORDER])

    M = np.array(grid).T
    cmap = matplotlib.colors.ListedColormap(
        ["#f0f0f0", "#9ecae1", "#fdae6b", "#31a354"]
    )
    ax.imshow(M, cmap=cmap, vmin=0, vmax=3, aspect="auto")
    ax.set_xticks(range(len(cols)), cols, fontsize=8)
    ax.set_yticks(range(len(MODEL_ORDER)), MODEL_ORDER, fontsize=9)
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            ax.text(j, i, {0: "-", 1: "r2", 2: "RV", 3: "both"}[M[i, j]],
                    ha="center", va="center", fontsize=8)

    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in
               ["#31a354", "#9ecae1", "#fdae6b", "#f0f0f0"]]
    ax.legend(handles, ["in MCS under both proxies", "only under r^2 proxy",
                        "only under RV proxy", "in neither"],
              fontsize=8, loc="center left", bbox_to_anchor=(1.02, 0.5))
    ax.set_title("MCS membership (QLIKE, alpha=0.10) under two variance proxies",
                 fontsize=11, fontweight="bold")
    fig.savefig(FIGS / "fig3_proxy_robustness.png", dpi=150)
    plt.close(fig)


def fig_calibration(results: dict) -> None:
    """What the Mincer-Zarnowitz step is actually worth, in mean-loss terms."""
    cells = _cells(results, "rv", horizon=1)
    fig, ax = plt.subplots(figsize=(9.5, 4.8), constrained_layout=True)

    pairs = [("TimesFM", "TimesFM-MZ"), ("TTM", "TTM-MZ")]
    width = 0.35
    x = np.arange(len(cells) * len(pairs))
    labels, raw_v, mz_v, har_v = [], [], [], []

    for c in cells:
        for raw, mz in pairs:
            labels.append(f"{c['asset']}\n{raw}")
            raw_v.append(c["mean_loss"]["qlike"][raw])
            mz_v.append(c["mean_loss"]["qlike"][mz])
            har_v.append(c["mean_loss"]["qlike"]["HAR"])

    ax.bar(x - width / 2, raw_v, width, label="zero-shot, uncalibrated", color="#d95f02")
    ax.bar(x + width / 2, mz_v, width, label="after Mincer-Zarnowitz", color="#1b9e77")
    for i, hv in enumerate(har_v):
        ax.plot([i - 0.5, i + 0.5], [hv, hv], color="black", lw=1.8,
                label="log-HAR" if i == 0 else None)

    ax.set_xticks(x, labels, fontsize=7.5)
    ax.set_ylabel("mean QLIKE (h=1, lower is better)")
    ax.set_yscale("log")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    ax.set_title("Zero-shot vs Mincer-Zarnowitz-recalibrated TSFM, against the log-HAR bar",
                 fontsize=11, fontweight="bold")
    fig.savefig(FIGS / "fig4_calibration.png", dpi=150)
    plt.close(fig)


def main() -> None:
    FIGS.mkdir(exist_ok=True)
    results = json.loads((HERE / "k1711_results.json").read_text())
    series = json.loads((HERE / "k1711_series.json").read_text())

    fig_mcs_membership(results)
    fig_cumulative_loss_diff(results, series)
    fig_proxy_robustness(results)
    fig_calibration(results)
    print("wrote", *(p.name for p in sorted(FIGS.glob("*.png"))))


if __name__ == "__main__":
    main()
