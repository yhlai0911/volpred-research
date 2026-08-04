"""Charts for the K1654 general-audience article.

Every number is read from experiments/k1654/k1654_results.json at run time.
Only labels, colours and layout are written here.

  1. k1654_general_breaches.png -- how many days each index blew through the
     1-in-100 risk line over the out-of-sample period, for the symmetric
     baseline and for the asymmetric model, against the number the line
     promised. The point of the figure is that the baseline roughly doubles
     its promise on all four indices while the asymmetric model lands near it.
  2. k1654_general_tailsize.png -- the tail-size test statistic for both
     models on all four indices. Higher means the model understated how much
     was actually lost on the days the line was breached. The baseline sits
     outside the pass band on every index; the asymmetric model sits inside
     on every index.

Palette: #B45309 (symmetric baseline), #1D4ED8 (asymmetric model), #71717A
(the promised level / reference). Every mark carries a direct value label, so
the figures do not rely on colour discrimination alone.
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
RESULTS = ROOT / "experiments" / "k1654" / "k1654_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_BASE = "#B45309"
C_SKEW = "#1D4ED8"
C_REF = "#71717A"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

# Reader-facing names. The raw keys are tickers; the results file carries an
# English name, but the article is Traditional Chinese.
LABELS = {
    "SPY": "標普 500",
    "QQQ": "那斯達克 100",
    "^TWII": "台灣加權",
    "^N225": "日經 225",
}
ORDER = ["SPY", "QQQ", "^TWII", "^N225"]


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


def chart_breaches(res: dict) -> Path:
    """1% risk line: promised breaches vs what each model actually took."""
    promised, base, skew = [], [], []
    for key in ORDER:
        cell = res["results"][key]["var_backtests"]["alpha_0.01"]
        promised.append(cell["M0"]["expected_violations"])
        base.append(cell["M0"]["n_violations"])
        skew.append(cell["M2"]["n_violations"])

    x = np.arange(len(ORDER))
    width = 0.36

    fig, ax = plt.subplots(figsize=(9.6, 5.4), dpi=200)
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)

    b1 = ax.bar(x - width / 2, base, width, color=C_BASE, label="對稱常態模型")
    b2 = ax.bar(x + width / 2, skew, width, color=C_SKEW, label="不對稱模型")

    for bars in (b1, b2):
        for rect in bars:
            ax.annotate(
                f"{int(rect.get_height())}",
                (rect.get_x() + rect.get_width() / 2, rect.get_height()),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                fontsize=11,
                color=C_TEXT,
                fontweight="bold",
            )

    for i, val in enumerate(promised):
        ax.hlines(
            val,
            i - width - 0.06,
            i + width + 0.06,
            color=C_REF,
            linestyle="--",
            linewidth=1.8,
        )
        ax.annotate(
            f"該有 {val:.1f} 天",
            (i - width - 0.06, val),
            xytext=(0, 4),
            textcoords="offset points",
            ha="left",
            va="bottom",
            fontsize=9.5,
            color=C_MUTED,
        )

    ax.set_xticks(x)
    ax.set_xticklabels([LABELS[k] for k in ORDER], fontsize=11.5, color=C_TEXT)
    ax.set_ylabel("實際破線天數", fontsize=11, color=C_MUTED)
    ax.set_title(
        "「一百天只該破一次」的風險線，實際被破了幾天",
        fontsize=14.5,
        color=C_TEXT,
        fontweight="bold",
        pad=14,
    )
    ax.set_ylim(0, max(base) * 1.28)
    ax.grid(axis="y", color=C_GRID, linewidth=0.7, alpha=0.6)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=10.5, loc="upper right", ncols=2)

    out = ASSETS / "k1654_general_breaches.png"
    fig.tight_layout()
    fig.savefig(out, facecolor=C_SURFACE)
    plt.close(fig)
    return out


def chart_tailsize(res: dict) -> Path:
    """Tail-size test statistic at the 1% line, both models, all indices."""
    base, skew = [], []
    for key in ORDER:
        cell = res["results"][key]["es_backtests"]["alpha_0.01"]
        base.append(cell["M0"]["Z1"])
        skew.append(cell["M2"]["Z1"])

    y = np.arange(len(ORDER))

    fig, ax = plt.subplots(figsize=(9.6, 5.0), dpi=200)
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)

    lo = min(min(base), min(skew)) - 0.9
    hi = max(max(base), max(skew)) + 1.1

    ax.axvspan(lo, 1.96, color=C_REF, alpha=0.10)
    ax.axvline(1.96, color=C_REF, linestyle="--", linewidth=1.6)
    ax.annotate(
        "這條線的左邊算通過",
        (1.96, -0.46),
        xytext=(-8, 0),
        textcoords="offset points",
        ha="right",
        fontsize=10,
        color=C_MUTED,
    )

    for i in range(len(ORDER)):
        ax.plot([base[i], skew[i]], [y[i], y[i]], color=C_GRID, linewidth=2.2, zorder=1)

    ax.scatter(base, y, s=150, color=C_BASE, zorder=3, label="對稱常態模型")
    ax.scatter(skew, y, s=150, color=C_SKEW, zorder=3, label="不對稱模型")

    for i in range(len(ORDER)):
        ax.annotate(
            f"{base[i]:.2f}",
            (base[i], y[i]),
            xytext=(0, 13),
            textcoords="offset points",
            ha="center",
            fontsize=10.5,
            color=C_BASE,
            fontweight="bold",
        )
        ax.annotate(
            f"{skew[i]:.2f}",
            (skew[i], y[i]),
            xytext=(0, 13),
            textcoords="offset points",
            ha="center",
            fontsize=10.5,
            color=C_SKEW,
            fontweight="bold",
        )

    ax.set_yticks(y)
    ax.set_yticklabels([LABELS[k] for k in ORDER], fontsize=11.5, color=C_TEXT)
    ax.set_ylim(len(ORDER) - 0.4, -0.75)
    ax.set_xlim(lo, hi)
    ax.set_xlabel("破線那些天，實際虧損比模型講的多多少（數字越大低估越嚴重）", fontsize=10.5, color=C_MUTED)
    ax.set_title(
        "破線之後的虧損有多深：對稱模型四個指數全部低估",
        fontsize=14.5,
        color=C_TEXT,
        fontweight="bold",
        pad=14,
    )
    ax.grid(axis="x", color=C_GRID, linewidth=0.7, alpha=0.6)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=10.5, loc="lower right")

    out = ASSETS / "k1654_general_tailsize.png"
    fig.tight_layout()
    fig.savefig(out, facecolor=C_SURFACE)
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    res = load()
    for path in (chart_breaches(res), chart_tailsize(res)):
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
