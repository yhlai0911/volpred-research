"""Generate 2 charts for K567 general-audience article.

Chart 1: 6-market Sharpe bar comparison (base / us_style / percentile / local_rv)
Chart 2: t-stat vs Harvey threshold scatter (6 markets * 3 variants = 18 points)

Uploads to Supabase Storage and prints URLs.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# Add repo root to path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from volpred.charts.article_charts import upload_chart  # noqa: E402

EXP_DIR = Path(__file__).parent
RESULTS_PATH = EXP_DIR / "k567_international_vt_leverage_results.json"

# Market display names (general audience: 用地區名, 不用 ticker)
MARKET_LABELS = {
    "SPY": "美股\n(SPY)",
    "EFA": "已開發\n市場 (EFA)",
    "EWZ": "巴西\n(EWZ)",
    "EWJ": "日本\n(EWJ)",
    "EWU": "英國\n(EWU)",
    "FXI": "中國\n大型股 (FXI)",
}

MARKETS = ["SPY", "EFA", "EWZ", "EWJ", "EWU", "FXI"]
VARIANTS = [
    ("base", "base_sharpe", "#6c757d", "基準 VT (無槓桿)"),
    ("us_style", "us_style_sharpe", "#0d6efd", "美式槓桿 (VIX<15 加碼)"),
    ("percentile", "percentile_sharpe", "#20c997", "百分位槓桿"),
    ("local_rv", "local_rv_sharpe", "#fd7e14", "本地波動槓桿"),
]


def chart1_sharpe_bars(results: dict) -> Path:
    """6-market grouped bar chart of Sharpe by variant."""
    summary = results["summary"]
    fig, ax = plt.subplots(figsize=(13, 7))

    x = np.arange(len(MARKETS))
    width = 0.2

    for i, (key, json_key, color, label) in enumerate(VARIANTS):
        vals = [summary[m][json_key] for m in MARKETS]
        offset = (i - 1.5) * width
        bars = ax.bar(x + offset, vals, width, color=color, label=label, edgecolor="white", linewidth=0.8)
        # Highlight SPY's base vs best
        for j, v in enumerate(vals):
            ax.text(
                x[j] + offset, v + 0.005,
                f"{v:.3f}",
                ha="center", va="bottom",
                fontsize=7.5, color="#333",
            )

    ax.set_xticks(x)
    ax.set_xticklabels([MARKET_LABELS[m] for m in MARKETS], fontsize=10)
    ax.set_ylabel("Sharpe Ratio (2004-2025, 年化)", fontsize=11)
    ax.set_title(
        "K567: 6 個市場測試 VIX 條件槓桿 — 只有美股略有改善\n(4 種槓桿變形 Sharpe 對比; 越高越好)",
        fontsize=13, fontweight="bold", pad=15,
    )
    ax.axhline(0, color="#999", linewidth=0.6)
    ax.legend(loc="upper right", fontsize=9, ncol=2, framealpha=0.95)
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    ax.set_ylim(0, max(summary[m]["base_sharpe"] for m in MARKETS) * 1.6)

    # Annotate SPY winner
    spy_best = max(
        summary["SPY"]["us_style_sharpe"],
        summary["SPY"]["percentile_sharpe"],
        summary["SPY"]["local_rv_sharpe"],
    )
    ax.annotate(
        "SPY 最佳 +3.6%\n(仍未過嚴格統計門檻)",
        xy=(0 + 1.5 * width, spy_best),
        xytext=(0.8, 0.48),
        fontsize=9, color="#d62728",
        arrowprops=dict(arrowstyle="->", color="#d62728", lw=1.3),
        ha="left",
    )

    fig.tight_layout()
    out = EXP_DIR / "k567_general_sharpe_bars.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def chart2_tstat_scatter(results: dict) -> Path:
    """t-stat scatter: 6 markets x 3 variants = 18 points, with Harvey threshold."""
    full = results["full_results"]
    fig, ax = plt.subplots(figsize=(13, 6.5))

    variant_keys = [
        ("us_style_vs_base", "美式槓桿", "#0d6efd", "o"),
        ("percentile_vs_base", "百分位槓桿", "#20c997", "s"),
        ("local_rv_vs_base", "本地波動槓桿", "#fd7e14", "^"),
    ]

    x = np.arange(len(MARKETS))
    offsets = [-0.18, 0, 0.18]

    for (vkey, vlabel, color, marker), off in zip(variant_keys, offsets):
        ts = [full[m][vkey]["t_stat"] for m in MARKETS]
        ax.scatter(
            x + off, ts,
            s=140, c=color, marker=marker, alpha=0.85,
            edgecolors="white", linewidths=1.5,
            label=vlabel, zorder=3,
        )

    # Harvey thresholds
    ax.axhline(3.0, color="#d62728", linestyle="--", linewidth=2, label="Harvey 嚴格門檻 (|t|=3.0)", zorder=2)
    ax.axhline(-3.0, color="#d62728", linestyle="--", linewidth=2, zorder=2)
    ax.axhline(2.0, color="#bbb", linestyle=":", linewidth=1, label="傳統 5% 門檻 (|t|=2.0)", zorder=1)
    ax.axhline(-2.0, color="#bbb", linestyle=":", linewidth=1, zorder=1)
    ax.axhline(0, color="#333", linewidth=0.5, zorder=1)

    # Highlight pass/fail
    ax.fill_between([-0.5, len(MARKETS) - 0.5], 3.0, 4.5, alpha=0.08, color="#28a745", zorder=0)
    ax.text(5.2, 3.6, "過門檻\n(真槓桿效應)", fontsize=9, color="#28a745", ha="right", va="center", fontweight="bold")
    ax.fill_between([-0.5, len(MARKETS) - 0.5], -4.5, 3.0, alpha=0.05, color="#6c757d", zorder=0)

    ax.set_xticks(x)
    ax.set_xticklabels([MARKET_LABELS[m] for m in MARKETS], fontsize=10)
    ax.set_ylabel("統計顯著性 (t-stat)", fontsize=11)
    ax.set_title(
        "K567: 18 個測試中 0 個過 Harvey 嚴格門檻\n即使 SPY 最佳 variant t=2.47, 仍在噪音區間",
        fontsize=13, fontweight="bold", pad=15,
    )
    ax.set_xlim(-0.5, len(MARKETS) - 0.5)
    ax.set_ylim(-1.5, 4.5)
    ax.legend(loc="lower right", fontsize=9, framealpha=0.95, ncol=2)
    ax.grid(axis="y", alpha=0.25, linestyle="--")

    fig.tight_layout()
    out = EXP_DIR / "k567_general_tstat_scatter.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    with RESULTS_PATH.open() as f:
        results = json.load(f)

    # Font for CJK
    for font in ["Heiti TC", "PingFang TC", "Noto Sans CJK TC", "Arial Unicode MS"]:
        try:
            plt.rcParams["font.sans-serif"] = [font]
            plt.rcParams["axes.unicode_minus"] = False
            break
        except Exception:
            continue

    p1 = chart1_sharpe_bars(results)
    p2 = chart2_tstat_scatter(results)

    print(f"[chart1] saved: {p1}")
    print(f"[chart2] saved: {p2}")

    try:
        url1 = upload_chart(str(p1))
        url2 = upload_chart(str(p2))
        print(f"[chart1_url] {url1}")
        print(f"[chart2_url] {url2}")
    except Exception as e:
        print(f"[upload_error] {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
