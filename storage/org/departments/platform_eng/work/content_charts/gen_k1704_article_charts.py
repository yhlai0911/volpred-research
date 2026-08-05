"""Charts for the K1704 general-audience article (which yardstick you measure with).

Every number is read from experiments/k1704/K1704_results.json at run time:

  1. k1704_general_qlike_by_proxy.png -- QLIKE for three models against six
     volatility proxies. r2_day sits an order of magnitude above the rest
     (~2.86 vs ~0.13), so the six proxies get their own facet and their own
     y-scale instead of one shared axis that would flatten the other five into
     a single line. Each facet is annotated with its own winner.
  2. k1704_general_split_oos.png -- the same three models on the consensus
     target, first half vs second half of the out-of-sample window, with the
     window dates and sample sizes read from the JSON (n_oos), not typed in.

Palette reuses the repo's validated general-audience set (#1D4ED8 / #B45309 /
#15803D on a light surface, as in scripts/gen_k1356_article_charts.py). Every
bar carries a direct value label, so nothing depends on hue alone.
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
RESULTS = ROOT / "experiments" / "k1704" / "K1704_results.json"
ASSETS = ROOT / "storage" / "assets"

C_WIN = "#1D4ED8"
C_MID = "#B45309"
C_LOSE = "#15803D"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

MODEL_ORDER = ["HAR_RV5", "EWMA_R2", "GJR_GARCH"]
MODEL_LABELS = {
    "HAR_RV5": "HAR-RV（用已實現波動的階梯模型）",
    "EWMA_R2": "EWMA（指數加權移動平均）",
    "GJR_GARCH": "GJR-GARCH",
}
MODEL_SHORT = {"HAR_RV5": "HAR-RV", "EWMA_R2": "EWMA", "GJR_GARCH": "GJR-GARCH"}
MODEL_COLORS = {"HAR_RV5": C_WIN, "EWMA_R2": C_MID, "GJR_GARCH": C_LOSE}

TARGET_ORDER = [
    "rv_1min", "rv_5min", "rv_10min", "parkinson", "r2_day", "consensus_weighted",
]
TARGET_LABELS = {
    "rv_1min": "1 分鐘已實現波動",
    "rv_5min": "5 分鐘已實現波動",
    "rv_10min": "10 分鐘已實現波動",
    "parkinson": "Parkinson（高低價區間）",
    "r2_day": "日報酬平方",
    "consensus_weighted": "共識加權",
}


def _frame(ax) -> None:
    ax.set_facecolor(C_SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(C_GRID)
    ax.grid(axis="y", alpha=0.25, color=C_GRID)
    ax.set_axisbelow(True)


def chart_qlike_by_proxy(results: dict, out: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 7.4))
    fig.patch.set_facecolor(C_SURFACE)

    winners = []
    for ax, target in zip(axes.ravel(), TARGET_ORDER):
        metrics = results["targets"][target]["metrics"]
        values = [metrics[m]["qlike"] for m in MODEL_ORDER]
        best = MODEL_ORDER[int(np.argmin(values))]
        winners.append(best)
        _frame(ax)
        bars = ax.bar(
            range(len(MODEL_ORDER)), values,
            color=[MODEL_COLORS[m] for m in MODEL_ORDER],
            width=0.62,
        )
        for rect, value in zip(bars, values):
            ax.text(
                rect.get_x() + rect.get_width() / 2, rect.get_height(),
                f"{value:.3f}", ha="center", va="bottom",
                fontsize=10, color=C_TEXT,
            )
        ax.set_xticks(range(len(MODEL_ORDER)), [MODEL_SHORT[m] for m in MODEL_ORDER])
        ax.tick_params(colors=C_TEXT, labelsize=9)
        ax.set_ylim(0, max(values) * 1.22)
        ax.set_title(TARGET_LABELS[target], fontsize=11, color=C_TEXT, pad=8)
        ax.set_ylabel("QLIKE（越低越好）", fontsize=9, color=C_MUTED)

    unanimous = len(set(winners)) == 1
    headline = (
        f"換六種尺規量同一件事，贏家都是 {MODEL_SHORT[winners[0]]}——變的只有分數大小"
        if unanimous
        else "不同尺規會量出不同贏家"
    )
    fig.suptitle(headline, fontsize=15, fontweight="bold", color=C_TEXT, y=0.985)
    fig.text(
        0.01, 0.015,
        "資料：experiments/k1704/K1704_results.json（.targets.<proxy>.metrics.<model>.qlike）。"
        "六格各自有 y 軸刻度——日報酬平方的數值比其他五格大一個量級，共用刻度會把它們壓平。",
        fontsize=8, color=C_MUTED,
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.955))
    fig.savefig(out, dpi=180, facecolor=C_SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


def chart_split_oos(results: dict, out: Path) -> None:
    split = results["split_oos_robustness"]
    halves = ["early_oos", "late_oos"]
    half_labels = []
    series = {m: [] for m in MODEL_ORDER}
    for half in halves:
        node = split[half]
        consensus = node["consensus_target"]
        half_labels.append(
            f"{'前段' if half == 'early_oos' else '後段'}\n"
            f"{node['date_start']} – {node['date_end']}\n"
            f"n = {consensus['n_oos']}"
        )
        for model in MODEL_ORDER:
            series[model].append(consensus["metrics"][model]["qlike"])

    x = np.arange(len(halves))
    width = 0.26
    fig, ax = plt.subplots(figsize=(10.2, 5.8))
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)

    for i, model in enumerate(MODEL_ORDER):
        offset = (i - 1) * width
        bars = ax.bar(
            x + offset, series[model], width,
            color=MODEL_COLORS[model], label=MODEL_LABELS[model],
        )
        for rect, value in zip(bars, series[model]):
            ax.text(
                rect.get_x() + rect.get_width() / 2, rect.get_height(),
                f"{value:.3f}", ha="center", va="bottom",
                fontsize=10, color=C_TEXT,
            )

    ax.set_xticks(x, half_labels)
    ax.tick_params(colors=C_TEXT)
    ax.set_ylabel("QLIKE（越低越好）", color=C_TEXT)
    ax.set_ylim(0, max(max(v) for v in series.values()) * 1.2)
    ax.legend(frameon=False, fontsize=9, loc="upper left")

    winners = [
        MODEL_ORDER[int(np.argmin([series[m][i] for m in MODEL_ORDER]))]
        for i in range(len(halves))
    ]
    ax.set_title(
        f"把樣本外切成前後兩半，贏家都是 {MODEL_SHORT[winners[0]]}"
        if len(set(winners)) == 1
        else "前後兩段的贏家不同——排序不穩定",
        fontsize=15, fontweight="bold", color=C_TEXT, pad=12,
    )
    fig.text(
        0.01, 0.02,
        "資料：experiments/k1704/K1704_results.json（.split_oos_robustness.<half>."
        "consensus_target.metrics.<model>.qlike，樣本數取自同節點的 n_oos）",
        fontsize=8, color=C_MUTED,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=180, facecolor=C_SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


def main() -> int:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    ASSETS.mkdir(parents=True, exist_ok=True)
    chart_qlike_by_proxy(results, ASSETS / "k1704_general_qlike_by_proxy.png")
    chart_split_oos(results, ASSETS / "k1704_general_split_oos.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
