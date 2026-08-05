"""Charts for the K1465 general-audience article (day-of-week effects in vol).

Every number is read from experiments/k1465/k1465_results.json at run time; the
experiment is never re-run.

  1. k1465_general_dow_mean_vs_median.png -- overnight and intraday squared
     returns by weekday, mean next to median. The mean/median gap is the story:
     a handful of days drag the average around while the typical day barely
     moves.
  2. k1465_general_vrp_flat.png -- the variance risk premium by weekday, full
     sample and out-of-sample, with both Kruskal-Wallis p-values on the chart.
  3. k1465_general_oos_equity.png -- the requested equity curve is NOT possible:
     .backtest_oos.strat_ret / bh_ret hold summary statistics, not a daily
     series, and the brief says never re-run the backtest to manufacture one.
     Per that same brief this falls back to the Sharpe / max-drawdown pair,
     read from the JSON.

The sample-size caveat from the brief is enforced in code: .dow_descriptive_full
.r_on_sq_x1e4.n carries a x1e4 scale defect (7,720,000), so counts are taken
from .dow_descriptive_full.vrp.n instead.

Palette reuses the repo's validated general-audience set (#1D4ED8 / #B45309 /
#15803D on a light surface, as in scripts/gen_k1356_article_charts.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False


def _repo_root() -> Path:
    """Find the repo root by marker, so this file can move to scripts/ unedited."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "experiments").is_dir() and (parent / "storage").is_dir():
            return parent
    raise SystemExit("repo root not found (no ancestor holds experiments/ and storage/)")


ROOT = _repo_root()
RESULTS = ROOT / "experiments" / "k1465" / "k1465_results.json"
ASSETS = ROOT / "storage" / "assets"

C_FULL = "#1D4ED8"
C_OOS = "#B45309"
C_ALT = "#15803D"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

DOW = ["0", "1", "2", "3", "4"]
DOW_LABELS = ["週一", "週二", "週三", "週四", "週五"]


def _frame(ax) -> None:
    ax.set_facecolor(C_SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(C_GRID)
    ax.grid(axis="y", alpha=0.25, color=C_GRID)
    ax.set_axisbelow(True)


def _series(node: dict, stat: str) -> list[float]:
    return [node[stat][d] for d in DOW]


def chart_dow_mean_vs_median(results: dict, out: Path) -> None:
    full = results["dow_descriptive_full"]
    # Counts come from vrp.n: the r_*_sq_x1e4 blocks carry a x1e4 scale defect
    # in their own n field (7,720,000 for a 772-day weekday bucket), so quoting
    # them would put a fabricated sample size on a reader-facing chart.
    counts = [full["vrp"]["n"][d] for d in DOW]

    panels = [
        ("r_on_sq_x1e4", "隔夜報酬平方"),
        ("r_id_sq_x1e4", "盤中報酬平方"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.6))
    fig.patch.set_facecolor(C_SURFACE)

    x = np.arange(len(DOW))
    width = 0.38
    for ax, (key, label) in zip(axes, panels):
        node = full[key]
        means = _series(node, "mean")
        medians = _series(node, "median")
        _frame(ax)
        b1 = ax.bar(x - width / 2, means, width, color=C_FULL, label="平均數")
        b2 = ax.bar(x + width / 2, medians, width, color=C_OOS, label="中位數")
        for bars, values in ((b1, means), (b2, medians)):
            for rect, value in zip(bars, values):
                ax.text(
                    rect.get_x() + rect.get_width() / 2, rect.get_height(),
                    f"{value:.2f}", ha="center", va="bottom",
                    fontsize=9, color=C_TEXT,
                )
        ax.set_xticks(x, [f"{lab}\nn={n}" for lab, n in zip(DOW_LABELS, counts)])
        ax.tick_params(colors=C_TEXT)
        # Not "x10^-4" with a superscript minus: PingFang lacks U+207B and it
        # renders as tofu on a reader-facing chart.
        ax.set_ylabel("報酬平方（單位 ×1e-4）", color=C_TEXT)
        ax.set_title(label, fontsize=12, color=C_TEXT, pad=8)
        ax.set_ylim(0, max(means + medians) * 1.2)
        ax.legend(frameon=False, fontsize=9)

    # Across BOTH panels, not just the overnight one: the headline sits above
    # both, so a range computed from one of them would describe half the chart.
    ratios = [
        m / md
        for key, _ in panels
        for m, md in zip(_series(full[key], "mean"), _series(full[key], "median"))
    ]
    fig.suptitle(
        f"平均數是中位數的 {min(ratios):.1f}–{max(ratios):.1f} 倍——被少數大跳動拉走的是平均，不是典型的一天",
        fontsize=14, fontweight="bold", color=C_TEXT, y=0.98,
    )
    fig.text(
        0.01, 0.015,
        "資料：experiments/k1465/k1465_results.json（.dow_descriptive_full）。"
        "樣本數取自 .vrp.n——同區塊 r_*_sq_x1e4 的 n 欄位帶 ×1e4 標度瑕疵，不予引用。",
        fontsize=8, color=C_MUTED,
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.94))
    fig.savefig(out, dpi=180, facecolor=C_SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


def chart_vrp_flat(results: dict, out: Path) -> None:
    full = results["dow_descriptive_full"]["vrp"]
    oos = results["dow_descriptive_oos"]["vrp"]
    kw = results["kruskal_wallis"]
    p_full = kw["vrp_full"]["p"]
    p_oos = kw["vrp_oos"]["p"]

    full_means = _series(full, "mean")
    oos_means = _series(oos, "mean")

    fig, ax = plt.subplots(figsize=(10.4, 5.8))
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)

    x = np.arange(len(DOW))
    ax.plot(x, full_means, marker="o", ms=9, lw=2, color=C_FULL, label="全期")
    ax.plot(x, oos_means, marker="s", ms=9, lw=2, color=C_OOS, label="樣本外")
    for xi, value in zip(x, full_means):
        ax.annotate(f"{value:.4f}", (xi, value), textcoords="offset points",
                    xytext=(0, 12), ha="center", fontsize=9, color=C_TEXT)
    for xi, value in zip(x, oos_means):
        ax.annotate(f"{value:.4f}", (xi, value), textcoords="offset points",
                    xytext=(0, -18), ha="center", fontsize=9, color=C_TEXT)

    ax.set_xticks(x, [
        f"{lab}\n全期 n={full['n'][d]} / 樣本外 n={oos['n'][d]}"
        for lab, d in zip(DOW_LABELS, DOW)
    ])
    ax.tick_params(colors=C_TEXT, labelsize=9)
    ax.set_ylabel("波動率風險溢酬（VRP）平均", color=C_TEXT)
    # y starts at 0 on purpose: a zoomed axis would turn this flat line into a
    # dramatic-looking pattern, which is the exact misreading the article is about.
    ax.set_ylim(0, max(full_means + oos_means) * 1.35)
    ax.legend(frameon=False, loc="upper right")

    ax.text(
        0.015, 0.055,
        f"Kruskal-Wallis 檢定：全期 p = {p_full:.3f}、樣本外 p = {p_oos:.3f}"
        "（兩者都遠大於 0.05，看不出星期別差異）",
        transform=ax.transAxes, fontsize=10, color=C_TEXT,
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "#F4F4F5",
              "edgecolor": C_GRID},
    )

    ax.set_title(
        "星期一到星期五，波動率風險溢酬幾乎是一條平線",
        fontsize=15, fontweight="bold", color=C_TEXT, pad=12,
    )
    fig.text(
        0.01, 0.02,
        "資料：experiments/k1465/k1465_results.json（.dow_descriptive_full.vrp、"
        ".dow_descriptive_oos.vrp、.kruskal_wallis）。y 軸自 0 起算，未做放大縮放。",
        fontsize=8, color=C_MUTED,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=180, facecolor=C_SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


def chart_oos_performance(results: dict, out: Path) -> str:
    """Sharpe / max-drawdown fallback; returns a note for the delivery reply."""
    bt = results["backtest_oos"]
    strat, bh = bt["strat_ret"], bt["bh_ret"]
    has_series = any(isinstance(v, list) for v in (strat, bh))
    if has_series:
        raise SystemExit(
            "backtest_oos now carries a series — revisit: the brief asked for an "
            "equity curve when one exists"
        )

    metrics = [
        ("sharpe", "夏普比率", 1.0),
        ("max_dd", "最大回撤", 100.0),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 5.4))
    fig.patch.set_facecolor(C_SURFACE)

    for ax, (key, label, scale) in zip(axes, metrics):
        values = [strat[key] * scale, bh[key] * scale]
        _frame(ax)
        bars = ax.bar(
            [0, 1], values, width=0.5, color=[C_OOS, C_FULL],
        )
        for rect, value in zip(bars, values):
            ax.text(
                rect.get_x() + rect.get_width() / 2,
                rect.get_height() + (0.02 if value >= 0 else -0.02) * max(
                    1.0, abs(max(values, key=abs))
                ),
                f"{value:.2f}" + ("%" if key == "max_dd" else ""),
                ha="center", va="bottom" if value >= 0 else "top",
                fontsize=12, color=C_TEXT, fontweight="bold",
            )
        ax.axhline(0, color=C_TEXT, lw=1)
        ax.set_xticks([0, 1], ["策略", "買進持有"])
        ax.tick_params(colors=C_TEXT)
        ax.set_title(label, fontsize=12, color=C_TEXT, pad=8)
        # Keep 0 inside the frame. Drawdowns are all negative, and an axis that
        # starts below 0 leaves the bars hanging from the top edge with no
        # baseline to read them against.
        pad = (max(values) - min(values)) * 0.28 or 1.0
        ax.set_ylim(min(min(values) - pad, 0), max(max(values) + pad, 0))

    fig.suptitle(
        f"樣本外 {bt['strat_ret']['n']} 個交易日：策略最終權益 "
        f"{bt['strat_ret']['final_equity']:.4f}，買進持有 "
        f"{bt['bh_ret']['final_equity']:.4f}",
        fontsize=14, fontweight="bold", color=C_TEXT, y=0.98,
    )
    note = (
        "results.json 的 .backtest_oos 只有彙總統計、沒有逐日序列，"
        "依需求規格改以夏普／最大回撤對照呈現，未自行重跑回測補序列。"
    )
    fig.text(
        0.01, 0.015,
        "資料：experiments/k1465/k1465_results.json（.backtest_oos）。" + note,
        fontsize=8, color=C_MUTED,
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.94))
    fig.savefig(out, dpi=180, facecolor=C_SURFACE)
    plt.close(fig)
    print(f"wrote {out}  [{note}]")
    return note


def main() -> int:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    ASSETS.mkdir(parents=True, exist_ok=True)
    chart_dow_mean_vs_median(results, ASSETS / "k1465_general_dow_mean_vs_median.png")
    chart_vrp_flat(results, ASSETS / "k1465_general_vrp_flat.png")
    chart_oos_performance(results, ASSETS / "k1465_general_oos_equity.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
