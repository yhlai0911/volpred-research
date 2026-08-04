"""Charts for the K1706 general-audience article.

Every number is read from experiments/k1706/K1706_results.json at run time.
Only labels, colours and layout are written here.

  1. k1706_general_strata.png -- the difference-in-differences estimate for the
     daily high-low range in the two frozen pre-spread strata, with 95% bands
     built from the stock-clustered standard errors, plus the formal
     narrow-minus-wide contrast and its Holm-adjusted randomization p-values.
  2. k1706_general_eventpath.png -- the month-by-month treated-minus-control
     path of the same range measure, September 2016 as the reference month,
     October 2016 dropped because the pilot phased in during that month.

Palette: #B45309 (narrow pre-spread stratum), #1D4ED8 (wide pre-spread
stratum), #71717A (reference / zero line). Every mark carries a direct value
label, so the figures do not rely on colour discrimination alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "k1706" / "K1706_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_NARROW = "#B45309"
C_WIDE = "#1D4ED8"
C_REF = "#71717A"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

OUTCOME = "range_bps"
STRATA = ("narrow", "wide")
STRATUM_LABEL = {"narrow": "原本價差窄的一組", "wide": "原本價差寬的一組"}
STRATUM_COLOR = {"narrow": C_NARROW, "wide": C_WIDE}

# Month keys as written by the experiment, in calendar order. September 2016 is
# the omitted reference month and is drawn at exactly zero.
MONTH_KEYS = [
    "event_2016-06",
    "event_2016-07",
    "event_2016-08",
    None,  # reference: 2016-09
    "event_2016-11",
    "event_2016-12",
    "event_2017-01",
    "event_2017-02",
]
MONTH_LABEL = [
    "2016\n6月",
    "7月",
    "8月",
    "9月\n(基準)",
    "11月",
    "12月",
    "2017\n1月",
    "2月",
]
# Index of the last pre-pilot month and the first post-pilot month on the axis.
LAST_PRE = 3
FIRST_POST = 4


def load() -> dict:
    with RESULTS.open(encoding="utf-8") as fh:
        return json.load(fh)


def _frame(ax) -> None:
    ax.set_facecolor(C_SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(C_GRID)
    ax.tick_params(colors=C_MUTED, labelsize=10)


def _primary(res: dict, stratum: str) -> dict:
    for row in res["primary_did"]:
        if row["outcome"] == OUTCOME and row["stratum"] == stratum:
            return row
    raise KeyError(f"primary_did row missing: {OUTCOME}/{stratum}")


def _heterogeneity(res: dict) -> dict:
    for row in res["heterogeneity_tests"]:
        if row["outcome"] == OUTCOME:
            return row
    raise KeyError(f"heterogeneity row missing: {OUTCOME}")


def chart_strata(res: dict) -> Path:
    """Range DiD by frozen pre-spread stratum, plus the formal contrast."""
    rows = [_primary(res, s) for s in STRATA]
    het = _heterogeneity(res)

    est = [r["fe_estimate"] for r in rows]
    err = [1.96 * r["fe_cluster_se"] for r in rows]
    x = np.arange(len(STRATA))

    fig, ax = plt.subplots(figsize=(9.6, 5.6), dpi=200)
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)

    bars = ax.bar(
        x,
        est,
        0.46,
        color=[STRATUM_COLOR[s] for s in STRATA],
        zorder=2,
    )
    ax.errorbar(
        x,
        est,
        yerr=err,
        fmt="none",
        ecolor=C_TEXT,
        elinewidth=1.6,
        capsize=8,
        capthick=1.6,
        zorder=3,
    )
    ax.axhline(0, color=C_REF, linewidth=1.4)

    for i, (rect, row) in enumerate(zip(bars, rows)):
        top = est[i] + err[i] if est[i] >= 0 else est[i] - err[i]
        va = "bottom" if est[i] >= 0 else "top"
        off = 8 if est[i] >= 0 else -8
        ax.annotate(
            f"{est[i]:+.2f} bps",
            (rect.get_x() + rect.get_width() / 2, top),
            xytext=(0, off),
            textcoords="offset points",
            ha="center",
            va=va,
            fontsize=13,
            color=C_TEXT,
            fontweight="bold",
        )
        ax.annotate(
            f"隨機重排 p = {row['ri_p']:.3f}\n多重比較校正後 p = {row['ri_p_holm_8']:.3f}\n"
            f"{row['n_stocks']:,} 檔（{row['n_treated']:,} 檔改成 5 美分）",
            (rect.get_x() + rect.get_width() / 2, top),
            xytext=(0, off + (26 if est[i] >= 0 else -26)),
            textcoords="offset points",
            ha="center",
            va=va,
            fontsize=10,
            color=C_MUTED,
        )

    span = max(abs(min(est)) + max(err), max(est) + max(err))
    ax.set_ylim(-span * 1.5, span * 1.55)
    ax.set_xticks(x)
    ax.set_xticklabels([STRATUM_LABEL[s] for s in STRATA], fontsize=12.5, color=C_TEXT)
    ax.set_ylabel("日內高低振幅的變化（bps，正值代表變寬）", fontsize=11, color=C_MUTED)
    ax.set_title(
        "同一條規則，兩組股票走向相反",
        fontsize=15,
        color=C_TEXT,
        fontweight="bold",
        pad=14,
    )
    ax.annotate(
        f"兩組相差 {het['narrow_minus_wide']:+.2f} bps"
        f"（隨機重排 p = {het['ri_p']:.3f}，校正後 p = {het['ri_p_holm_4']:.3f}）",
        (0.5, 0.015),
        xycoords="axes fraction",
        ha="center",
        fontsize=11.5,
        color=C_TEXT,
    )
    ax.grid(axis="y", color=C_GRID, linewidth=0.7, alpha=0.6)
    ax.set_axisbelow(True)

    out = ASSETS / "k1706_general_strata.png"
    fig.tight_layout()
    fig.savefig(out, facecolor=C_SURFACE)
    plt.close(fig)
    return out


def chart_eventpath(res: dict) -> Path:
    """Month-by-month treated-minus-control range path for both strata."""
    series = {}
    for stratum in STRATA:
        coef = res["event_study"][stratum][OUTCOME]["coefficients"]
        series[stratum] = [
            0.0 if key is None else coef[key]["estimate"] for key in MONTH_KEYS
        ]
    narrow_p = res["event_study"]["narrow"][OUTCOME]["coefficients"]

    x = np.arange(len(MONTH_KEYS))

    fig, ax = plt.subplots(figsize=(10.2, 5.6), dpi=200)
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)

    ax.axvspan(LAST_PRE + 0.5, len(MONTH_KEYS) - 0.5, color=C_REF, alpha=0.07)
    ax.axvline((LAST_PRE + FIRST_POST) / 2, color=C_REF, linestyle="--", linewidth=1.6)
    ax.annotate(
        "新規則上線\n(10 月分批上路，整月排除)",
        ((LAST_PRE + FIRST_POST) / 2, 0.965),
        xycoords=("data", "axes fraction"),
        xytext=(7, 0),
        textcoords="offset points",
        ha="left",
        va="top",
        fontsize=10,
        color=C_MUTED,
    )
    ax.axhline(0, color=C_REF, linewidth=1.2)

    for stratum in STRATA:
        ax.plot(
            x,
            series[stratum],
            marker="o",
            markersize=7,
            linewidth=2.4,
            color=STRATUM_COLOR[stratum],
            label=STRATUM_LABEL[stratum],
        )

    for i, key in enumerate(MONTH_KEYS):
        if key is None:
            continue
        val = series["narrow"][i]
        mark = "*" if narrow_p[key]["p"] < 0.01 else ""
        ax.annotate(
            f"{val:+.1f}{mark}",
            (i, val),
            xytext=(0, 11),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            color=C_NARROW,
            fontweight="bold",
        )
        ax.annotate(
            f"{series['wide'][i]:+.1f}",
            (i, series["wide"][i]),
            xytext=(0, -17),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            color=C_WIDE,
            fontweight="bold",
        )

    lo = min(min(series["narrow"]), min(series["wide"]))
    hi = max(max(series["narrow"]), max(series["wide"]))
    pad = (hi - lo) * 0.34
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(-0.5, len(MONTH_KEYS) - 0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(MONTH_LABEL, fontsize=10.5, color=C_TEXT)
    ax.set_ylabel("與對照組的日內振幅差距（bps）", fontsize=11, color=C_MUTED)
    ax.set_title(
        "新規則上線之後，往上跳的只有原本價差窄的那一組",
        fontsize=15,
        color=C_TEXT,
        fontweight="bold",
        pad=14,
    )
    ax.annotate(
        "* 標記處，該月係數的叢集標準誤檢定 p < 0.01",
        (0.5, 0.02),
        xycoords="axes fraction",
        ha="center",
        fontsize=10,
        color=C_MUTED,
    )
    ax.grid(axis="y", color=C_GRID, linewidth=0.7, alpha=0.6)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=11, loc="upper left")

    out = ASSETS / "k1706_general_eventpath.png"
    fig.tight_layout()
    fig.savefig(out, facecolor=C_SURFACE)
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    res = load()
    for path in (chart_strata(res), chart_eventpath(res)):
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
