"""Charts for the K1451 general-audience article (credit-spread signal vs VIX).

Every number is read from experiments/k1451/k1451_results.json at run time; the
experiment is never re-run and no data is re-fetched.

  1. k1451_general_leadlag.png -- cross-correlation between the signal and
     future volatility across lags -5..+5, with the confidence band from
     ci_lo/ci_hi and a zero line, so the reader can see immediately which lags
     clear zero at all.
  2. k1451_general_coef_collapse.png -- the same coefficient on its own and
     after VIX level is controlled for, as dot-and-error marks at +-1.96*se_hac.
     The surviving share is computed from the two coefficients, not typed in.

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
RESULTS = ROOT / "experiments" / "k1451" / "k1451_results.json"
ASSETS = ROOT / "storage" / "assets"

C_MAIN = "#1D4ED8"
C_ALT = "#B45309"
C_BAND = "#BFDBFE"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

TERM = "hyg_lqd_chg22_lag1"
CI_Z = 1.96


def _frame(ax) -> None:
    ax.set_facecolor(C_SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(C_GRID)
    ax.set_axisbelow(True)


def chart_leadlag(results: dict, out: Path) -> None:
    block = results["lead_lag_cross_corr"]
    lags = np.asarray(block["lags"], dtype=float)
    corr = np.asarray(block["corr"], dtype=float)
    lo = np.asarray(block["ci_lo"], dtype=float)
    hi = np.asarray(block["ci_hi"], dtype=float)

    fig, ax = plt.subplots(figsize=(10.4, 5.8))
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)
    ax.grid(alpha=0.25, color=C_GRID)

    ax.fill_between(lags, lo, hi, color=C_BAND, alpha=0.75, label="95% 信賴區間")
    ax.plot(lags, corr, color=C_MAIN, lw=2, marker="o", ms=6, label="相關係數")
    ax.axhline(0, color=C_TEXT, lw=1)

    for lag, value, low, high in zip(lags, corr, lo, hi):
        clears = low > 0 or high < 0
        ax.annotate(
            f"{value:+.2f}", (lag, value),
            textcoords="offset points", xytext=(0, 11 if value >= 0 else -16),
            ha="center", fontsize=9,
            color=C_TEXT if clears else C_MUTED,
            fontweight="bold" if clears else "normal",
        )

    ax.set_xticks(lags)
    ax.set_xlabel("落後期（負 = 訊號領先未來波動）", color=C_TEXT)
    ax.set_ylabel("相關係數", color=C_TEXT)
    ax.tick_params(colors=C_TEXT)
    ax.legend(frameon=False, loc="best")
    ax.set_title(
        "訊號與未來波動的相關係數（正負五日落後期）",
        fontsize=15, fontweight="bold", color=C_TEXT, pad=12,
    )
    fig.text(
        0.01, 0.02,
        "資料：experiments/k1451/k1451_results.json（.lead_lag_cross_corr）。"
        "粗體標示信賴區間未跨過 0 的落後期。",
        fontsize=8, color=C_MUTED,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=180, facecolor=C_SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


def chart_coef_collapse(results: dict, out: Path) -> None:
    specs = [
        ("univariate", "只放這個訊號"),
        ("vix_control_level", "再控制 VIX 水準後"),
    ]
    coefs, errs, labels = [], [], []
    for key, label in specs:
        node = results["models"][key][TERM]
        coefs.append(node["coef"])
        errs.append(CI_Z * node["se_hac"])
        labels.append(label)

    surviving = abs(coefs[1]) / abs(coefs[0]) if coefs[0] else float("nan")

    fig, ax = plt.subplots(figsize=(9.6, 4.8))
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)
    ax.grid(axis="x", alpha=0.25, color=C_GRID)

    y = np.arange(len(specs))[::-1]
    for i, (value, err, color) in enumerate(zip(coefs, errs, (C_MAIN, C_ALT))):
        ax.errorbar(
            value, y[i], xerr=err, fmt="o", ms=11, color=color,
            ecolor=color, elinewidth=2.4, capsize=7,
        )
        crosses_zero = abs(value) < err
        ax.annotate(
            f"{value:+.3f}  ({'跨過 0' if crosses_zero else '不跨 0'})",
            (value, y[i]), textcoords="offset points", xytext=(0, 16),
            ha="center", fontsize=10, color=C_TEXT,
        )

    ax.axvline(0, color=C_TEXT, lw=1)
    ax.set_yticks(y, labels)
    ax.set_ylim(-0.6, len(specs) - 0.25)
    ax.set_xlabel("迴歸係數（誤差棒為 ±1.96×HAC 標準誤）", color=C_TEXT)
    ax.tick_params(colors=C_TEXT)
    ax.set_title(
        f"控制 VIX 之後，係數只剩 {surviving:.1%}",
        fontsize=15, fontweight="bold", color=C_TEXT, pad=14,
    )
    fig.text(
        0.01, 0.03,
        "資料：experiments/k1451/k1451_results.json"
        f"（.models.<設定>.{TERM}.coef 與 .se_hac；剩餘比例由兩個係數相除得出）",
        fontsize=8, color=C_MUTED,
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(out, dpi=180, facecolor=C_SURFACE)
    plt.close(fig)
    print(f"wrote {out}  (剩餘比例 {surviving:.2%})")


def main() -> int:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    ASSETS.mkdir(parents=True, exist_ok=True)
    chart_leadlag(results, ASSETS / "k1451_general_leadlag.png")
    chart_coef_collapse(results, ASSETS / "k1451_general_coef_collapse.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
