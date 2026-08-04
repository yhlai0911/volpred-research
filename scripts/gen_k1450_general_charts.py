"""Charts for the K1450 general-audience article.

Both figures read every number from experiments/k1450/k1450_results.json.

  1. k1450_general_corr_flip.png -- VNQ's forward 21d correlation with SPY and
     with TLT, split by rate regime. The SPY panel is flat across regimes; the
     TLT panel crosses zero. That contrast is the article's spine.
  2. k1450_general_multiple_testing.png -- raw vs multiple-comparison-adjusted
     significance for all five primary contrasts, on a log axis with the 0.05
     line drawn. Only one contrast stays left of the line after adjustment.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "k1450" / "k1450_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

SURFACE = "#fcfcfb"
TEXT_1 = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#d4d4d8"
BLUE = "#2a78d6"      # categorical slot 1 -> 降息（利率往下）
ORANGE = "#eb6834"    # categorical slot 2 -> 升息（利率往上）
NEUTRAL = "#a1a1aa"

REGIME_KEY = 'C(regime, Treatment(reference="rate_down"))[T.rate_up]'

CONTRAST_LABEL = {
    "fwd_rv_vnq": "房地產 ETF 自身波動",
    "fwd_rv_spy": "美股 ETF 自身波動",
    "fwd_rv_tlt": "長天期公債 ETF 自身波動",
    "fwd_corr_vnq_spy": "房地產 × 美股 連動",
    "fwd_corr_vnq_tlt": "房地產 × 長天期公債 連動",
}


def load() -> dict:
    return json.loads(RESULTS.read_text())


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=TEXT_2, length=0)


def fig_corr_flip(data: dict) -> Path:
    s = data["summaries"]
    panels = [
        ("fwd_corr_vnq_spy", "房地產 ETF × 美股 ETF"),
        ("fwd_corr_vnq_tlt", "房地產 ETF × 長天期公債 ETF"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.6), sharey=True)
    fig.patch.set_facecolor(SURFACE)

    for ax, (key, title) in zip(axes, panels):
        down = s[key]["rate_down"]["mean"]
        up = s[key]["rate_up"]["mean"]
        bars = ax.bar(
            [0, 1],
            [down, up],
            width=0.52,
            color=[BLUE, ORANGE],
            zorder=3,
        )
        for rect, val in zip(bars, [down, up]):
            off = 0.035 if val >= 0 else -0.035
            va = "bottom" if val >= 0 else "top"
            ax.text(
                rect.get_x() + rect.get_width() / 2,
                val + off,
                f"{val:+.3f}",
                ha="center",
                va=va,
                fontsize=13,
                color=TEXT_1,
                zorder=4,
            )
        ax.axhline(0, color=TEXT_2, lw=1.2, zorder=2)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["降息期", "升息期"], fontsize=12, color=TEXT_1)
        ax.set_xlim(-0.6, 1.6)
        ax.set_ylim(-0.22, 0.80)
        ax.set_title(title, fontsize=13, color=TEXT_1, pad=12)
        ax.grid(axis="y", color=GRID, lw=0.7, zorder=0)
        _style(ax)

    axes[0].set_ylabel("未來 21 個交易日的相關係數（平均）", fontsize=11, color=TEXT_2)
    axes[0].annotate(
        "兩根幾乎一樣高",
        xy=(0.5, 0.70),
        ha="center",
        fontsize=11,
        color=TEXT_2,
    )
    axes[1].annotate(
        "由負翻正",
        xy=(0.5, 0.70),
        ha="center",
        fontsize=11,
        color=TEXT_2,
    )

    fig.suptitle(
        "升息期改變的是房地產與公債的關係，不是房地產與股市的關係",
        fontsize=15,
        color=TEXT_1,
        y=0.99,
    )
    fig.text(
        0.5,
        0.015,
        "資料：yfinance（VNQ / SPY / TLT / ^TNX），2005-04-06 至 2026-05-07，5,301 個交易日",
        ha="center",
        fontsize=9.5,
        color=TEXT_2,
    )
    fig.tight_layout(rect=(0, 0.045, 1, 0.94))
    out = ASSETS / "k1450_general_corr_flip.png"
    fig.savefig(out, dpi=170, facecolor=SURFACE)
    plt.close(fig)
    return out


def fig_multiple_testing(data: dict) -> Path:
    corr = data["multiple_test_correction"]
    order = sorted(corr, key=lambda k: corr[k]["rank"])
    ys = list(range(len(order)))[::-1]

    fig, ax = plt.subplots(figsize=(9.6, 5.0))
    fig.patch.set_facecolor(SURFACE)

    for y, key in zip(ys, order):
        raw = corr[key]["raw_p"]
        adj = corr[key]["bonferroni_p"]
        ax.plot([raw, adj], [y, y], color=NEUTRAL, lw=2, zorder=2)
        ax.plot([raw], [y], "o", ms=9, color=BLUE, zorder=3)
        ax.plot([adj], [y], "o", ms=9, color=ORANGE, zorder=3)
        ax.text(raw, y + 0.26, f"{raw:.4f}", ha="center", fontsize=10, color=TEXT_2)
        ax.text(adj, y - 0.38, f"{adj:.4f}", ha="center", fontsize=10, color=TEXT_2)

    ax.axvline(0.05, color="#e34948", lw=1.6, ls="--", zorder=1)
    ax.text(
        0.052,
        len(order) - 0.55,
        "0.05 這條線",
        fontsize=10.5,
        color="#e34948",
        va="top",
    )

    ax.set_xscale("log")
    ax.set_xlim(0.0015, 2.6)
    ax.set_xticks([0.002, 0.01, 0.05, 0.2, 1.0])
    ax.set_xticklabels(["0.002", "0.01", "0.05", "0.2", "1.0"], fontsize=11)
    ax.set_yticks(ys)
    ax.set_yticklabels([CONTRAST_LABEL[k] for k in order], fontsize=12, color=TEXT_1)
    ax.set_ylim(-0.75, len(order) - 0.15)
    ax.set_xlabel("差異是巧合的機率（越左邊越不像巧合）", fontsize=11, color=TEXT_2)
    ax.grid(axis="x", color=GRID, lw=0.7, zorder=0)
    _style(ax)

    ax.plot([], [], "o", ms=9, color=BLUE, label="單獨看一項檢定")
    ax.plot([], [], "o", ms=9, color=ORANGE, label="一次做五項後校正")
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.005),
        ncol=2,
        frameon=False,
        fontsize=11,
        labelcolor=TEXT_1,
    )

    fig.suptitle(
        "五項檢定一起做，校正後只剩房地產 × 長天期公債這一項站得住",
        fontsize=15,
        color=TEXT_1,
        y=0.985,
    )
    fig.text(
        0.5,
        0.015,
        "資料：yfinance（VNQ / SPY / TLT / ^TNX），2005-04-06 至 2026-05-07，5,301 個交易日",
        ha="center",
        fontsize=9.5,
        color=TEXT_2,
    )
    fig.tight_layout(rect=(0, 0.045, 1, 0.90))
    out = ASSETS / "k1450_general_multiple_testing.png"
    fig.savefig(out, dpi=170, facecolor=SURFACE)
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    for path in (fig_corr_flip(data), fig_multiple_testing(data)):
        print(path)


if __name__ == "__main__":
    main()
