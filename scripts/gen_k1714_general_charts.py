"""Charts for the K1714 general-audience article.

Every number is read from experiments/k1714/K1714_results.json at run time.
Only labels, colours and layout are written in this file.

  1. k1714_general_annvol.png -- horizontal bars of the out-of-sample annualised
     volatility of the five minimum-variance portfolios under the headline
     5-day rebalance (tested forecasting model, rolling sample, shrinkage,
     exponential decay, equal weight). The equal-weight bar is drawn in the
     neutral reference colour because it estimates nothing, and a dashed
     vertical line marks the exponential-decay benchmark so the gap to the
     tested model is readable at a glance. Every bar carries its own value
     label plus its annualised turnover.
  2. k1714_general_robustness.png -- dot plot of the tested model's annualised
     volatility across five specifications (headline 5-day, long-only, the
     alternative matrix parameterisation, all 24 asset orderings, and the
     10-day rebalance) against the exponential-decay benchmark that belongs to
     each specification. The 24 orderings are drawn as individual translucent
     dots with min / mean / max labelled, so the reader can see that none of
     them falls below the benchmark line, and the 10-day row is the single
     place where the two markers sit on top of each other.

Palette: #B45309 (tested forecasting model), #1D4ED8 (exponential-decay
benchmark and the other estimated benchmarks), #71717A (neutral reference /
equal weight / zero lines). Every mark carries a direct numeric label, so
neither figure relies on colour discrimination alone.
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
RESULTS = ROOT / "experiments" / "k1714" / "K1714_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_MODEL = "#B45309"
C_BENCH = "#1D4ED8"
C_REF = "#71717A"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

MODEL_KEY = "har_rcov_chol"
BENCH_KEY = "ewma"

# Bars are drawn from the lowest volatility down; the tested model and the
# no-estimation reference are coloured differently from the three benchmarks.
BAR_ORDER = ["ewma", "sample", "ledoit_wolf", "har_rcov_chol", "equal_weight"]
BAR_LABEL = {
    "ewma": "指數衰減加權",
    "sample": "滾動 252 日平均",
    "ledoit_wolf": "收縮估計",
    "har_rcov_chol": "再疊一層預測（受測）",
    "equal_weight": "等權 25%（完全不估計）",
}
BAR_COLOR = {
    "ewma": C_BENCH,
    "sample": C_BENCH,
    "ledoit_wolf": C_BENCH,
    "har_rcov_chol": C_MODEL,
    "equal_weight": C_REF,
}


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


def chart_annvol(res: dict) -> Path:
    """Annualised volatility of the five portfolios, headline 5-day blocks."""
    block = res["results_by_block_length"]["block_5d"]
    metrics = block["metrics"]
    audit = block["audit"]

    vals = [metrics[k]["ann_vol"] * 100.0 for k in BAR_ORDER]
    turns = [metrics[k]["turnover_annualized"] for k in BAR_ORDER]
    bench = metrics[BENCH_KEY]["ann_vol"] * 100.0
    model = metrics[MODEL_KEY]["ann_vol"] * 100.0

    y = np.arange(len(BAR_ORDER))[::-1]

    fig, ax = plt.subplots(figsize=(10.2, 5.8), dpi=200)
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)

    ax.barh(
        y,
        vals,
        0.56,
        color=[BAR_COLOR[k] for k in BAR_ORDER],
        zorder=2,
    )
    ax.axvline(bench, color=C_BENCH, linestyle="--", linewidth=1.6, zorder=3)
    ax.annotate(
        f"最低的一條：{bench:.3f}%",
        (bench, y[0] + 0.52),
        xytext=(6, 0),
        textcoords="offset points",
        ha="left",
        va="bottom",
        fontsize=10.5,
        color=C_BENCH,
    )

    for yi, key, val, turn in zip(y, BAR_ORDER, vals, turns):
        ax.annotate(
            f"{val:.3f}%",
            (val, yi),
            xytext=(8, 0),
            textcoords="offset points",
            ha="left",
            va="center",
            fontsize=13,
            color=C_TEXT,
            fontweight="bold",
        )
        ax.annotate(
            f"每年換手 {turn:.2f} 次",
            (val, yi),
            xytext=(8, -15),
            textcoords="offset points",
            ha="left",
            va="center",
            fontsize=9.5,
            color=C_MUTED,
        )

    ax.annotate(
        f"受測做法比最低的那條高 {model - bench:.3f} 個百分點",
        (model, y[BAR_ORDER.index(MODEL_KEY)]),
        xytext=(0, -34),
        textcoords="offset points",
        ha="left",
        va="center",
        fontsize=10.5,
        color=C_MODEL,
    )

    ax.set_yticks(y)
    ax.set_yticklabels([BAR_LABEL[k] for k in BAR_ORDER], fontsize=12, color=C_TEXT)
    ax.set_xlim(0, max(vals) * 1.28)
    ax.set_xlabel("樣本外年化波動（%，越低越好）", fontsize=11, color=C_MUTED)
    ax.set_title(
        "先估計把波動壓下來，再疊一層預測又推回去",
        fontsize=15.5,
        color=C_TEXT,
        fontweight="bold",
        pad=14,
    )
    ax.annotate(
        f"SPY／QQQ／GLD／TLT 最小變異數組合，"
        f"{audit['oos_start_date']} 至 {audit['oos_end_date']}，"
        f"{metrics[MODEL_KEY]['n_days']:,} 個交易日、每 {audit['block_len']} 天重配一次共 "
        f"{audit['n_rebalances']:,} 次",
        (0.0, -0.155),
        xycoords="axes fraction",
        ha="left",
        fontsize=10,
        color=C_MUTED,
    )
    ax.grid(axis="x", color=C_GRID, linewidth=0.7, alpha=0.6)
    ax.set_axisbelow(True)

    out = ASSETS / "k1714_general_annvol.png"
    fig.tight_layout()
    fig.savefig(out, facecolor=C_SURFACE)
    plt.close(fig)
    return out


def chart_robustness(res: dict) -> Path:
    """Tested model vs its own benchmark across five specifications."""
    b5 = res["results_by_block_length"]["block_5d"]
    b10 = res["results_by_block_length"]["block_10d"]
    perm = b5["cholesky_permutation_sensitivity"]

    base_bench = b5["metrics"][BENCH_KEY]["ann_vol"] * 100.0

    rows = [
        (
            "主設定：每 5 天重配",
            b5["metrics"][MODEL_KEY]["ann_vol"] * 100.0,
            base_bench,
            None,
        ),
        (
            "只做多，不准放空",
            b5["long_only_robustness"]["metrics"][MODEL_KEY]["ann_vol"] * 100.0,
            b5["long_only_robustness"]["metrics"][BENCH_KEY]["ann_vol"] * 100.0,
            None,
        ),
        (
            "換另一種矩陣寫法",
            b5["matrix_log_parameterisation_secondary"]["metrics"][MODEL_KEY]["ann_vol"]
            * 100.0,
            b5["matrix_log_parameterisation_secondary"]["metrics"][BENCH_KEY]["ann_vol"]
            * 100.0,
            None,
        ),
        (
            f"{perm['n_orderings']} 種資產排序全跑",
            perm["ann_vol_mean"] * 100.0,
            base_bench,
            [p["ann_vol"] * 100.0 for p in perm["per_ordering"]],
        ),
        (
            "改成每 10 天重配",
            b10["metrics"][MODEL_KEY]["ann_vol"] * 100.0,
            b10["metrics"][BENCH_KEY]["ann_vol"] * 100.0,
            None,
        ),
    ]

    y = np.arange(len(rows))[::-1]

    fig, ax = plt.subplots(figsize=(10.4, 6.0), dpi=200)
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)

    ax.axvline(base_bench, color=C_BENCH, linestyle="--", linewidth=1.5, zorder=1)
    ax.annotate(
        f"主設定的最低基準 {base_bench:.3f}%",
        (base_bench, y[0] + 0.46),
        xytext=(-6, 0),
        textcoords="offset points",
        ha="right",
        va="bottom",
        fontsize=10,
        color=C_BENCH,
    )

    for yi, (label, model_v, bench_v, cloud) in zip(y, rows):
        ax.plot(
            [bench_v, model_v],
            [yi, yi],
            color=C_GRID,
            linewidth=2.4,
            zorder=2,
            solid_capstyle="round",
        )
        if cloud is not None:
            ax.scatter(
                cloud,
                np.full(len(cloud), yi),
                s=42,
                color=C_MODEL,
                alpha=0.32,
                edgecolors="none",
                zorder=3,
            )
            ax.annotate(
                f"最低 {min(cloud):.3f}%",
                (min(cloud), yi),
                xytext=(0, 13),
                textcoords="offset points",
                ha="center",
                fontsize=9.5,
                color=C_MODEL,
            )
            ax.annotate(
                f"最高 {max(cloud):.3f}%",
                (max(cloud), yi),
                xytext=(0, 13),
                textcoords="offset points",
                ha="center",
                fontsize=9.5,
                color=C_MODEL,
            )
        ax.scatter(
            [bench_v], [yi], s=150, marker="|", color=C_BENCH, linewidths=2.6, zorder=5
        )
        ax.scatter([model_v], [yi], s=110, color=C_MODEL, zorder=6)

        if cloud is None:
            model_text = f"{model_v:.3f}%"
            model_offset = (9, 0)
            model_ha = "left"
        else:
            model_text = f"平均 {model_v:.3f}%"
            model_offset = (0, -20)
            model_ha = "center"
        ax.annotate(
            model_text,
            (model_v, yi),
            xytext=model_offset,
            textcoords="offset points",
            ha=model_ha,
            va="center",
            fontsize=12,
            color=C_MODEL,
            fontweight="bold",
        )
        # When the two markers nearly coincide the left-hand label would sit on
        # top of the dot, so it is dropped one line below instead.
        tight = abs(model_v - bench_v) < 0.08
        ax.annotate(
            f"{bench_v:.3f}%",
            (bench_v, yi),
            xytext=(14, -20) if tight else (-9, -1),
            textcoords="offset points",
            ha="left" if tight else "right",
            va="center",
            fontsize=11,
            color=C_BENCH,
        )

    lo = min(min(r[1], r[2]) for r in rows)
    hi = max(max(r[1], r[2]) for r in rows)
    cloud_all = rows[3][3] or []
    lo = min([lo] + cloud_all)
    hi = max([hi] + cloud_all)
    pad = (hi - lo) * 0.42
    ax.set_xlim(lo - pad, hi + pad)
    ax.set_ylim(-0.7, len(rows) - 0.35)
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=12, color=C_TEXT)
    ax.set_xlabel("樣本外年化波動（%，越低越好）", fontsize=11, color=C_MUTED)
    ax.set_title(
        "換四種設定重跑，受測做法沒有一次落到基準線左邊",
        fontsize=15.5,
        color=C_TEXT,
        fontweight="bold",
        pad=14,
    )
    ax.annotate(
        "圓點＝受測做法；直線標記＝該設定自己的指數衰減加權基準；"
        "半透明圓點＝每一種資產排序各跑一次的結果",
        (0.0, -0.155),
        xycoords="axes fraction",
        ha="left",
        fontsize=10,
        color=C_MUTED,
    )
    ax.grid(axis="x", color=C_GRID, linewidth=0.7, alpha=0.6)
    ax.set_axisbelow(True)

    out = ASSETS / "k1714_general_robustness.png"
    fig.tight_layout()
    fig.savefig(out, facecolor=C_SURFACE)
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    res = load()
    for path in (chart_annvol(res), chart_robustness(res)):
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
