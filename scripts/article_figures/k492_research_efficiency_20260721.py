#!/usr/bin/env python3
"""K492 general-audience article figures.

Reads experiments/k492/k492_research_efficiency_results.json (primary source)
and renders two PNGs into storage/reports/assets/k492/.

Fig 1 — result distribution of 68 experiments (null / informative / partial /
        positive / meta / correction)
Fig 2 — cross-OOS before/after: 17 classified experiments that looked good on
        a single period, vs how many survived a second sample period.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from plot_style import apply_cjk_style  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402

RESULTS = REPO / "experiments" / "k492" / "k492_research_efficiency_results.json"
OUT_DIR = REPO / "storage" / "reports" / "assets" / "k492"

LABEL_ZH = {
    "null": "沒效果\n(null)",
    "informative": "有資訊\n(informative)",
    "partial": "部分有效\n(partial)",
    "positive": "有效\n(positive)",
    "meta": "回顧\n(meta)",
    "correction": "更正\n(correction)",
}
ORDER = ["null", "informative", "partial", "positive", "meta", "correction"]

C_BAD = "#c0504d"
C_MID = "#9a9a9a"
C_OK = "#4f81bd"


def main() -> int:
    apply_cjk_style(dpi=150)
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    dist = data["result_distribution"]
    n_total = data["n_experiments_classified"]
    null_rate = data["null_rate_pct"]
    pos_rate = data["positive_rate_pct"]
    cross = data["cross_oos_analysis"]
    n_surv = cross["n_survived"]
    n_fail = cross["n_failed"]
    fail_rate = cross["failure_rate_pct"]

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Fig 1 ────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    vals = [dist[k] for k in ORDER]
    colors = [C_BAD, C_MID, C_OK, C_OK, C_MID, C_MID]
    bars = ax.bar([LABEL_ZH[k] for k in ORDER], vals, color=colors, width=0.62)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.4, str(v),
                ha="center", va="bottom", fontsize=12, fontweight="bold")
    ax.set_ylabel("實驗數")
    ax.set_title(
        f"K492：{n_total} 個實驗的結果分佈\n"
        f"沒效果 {null_rate}%，明確有效 {pos_rate}%",
        fontsize=13, pad=12,
    )
    ax.set_ylim(0, max(vals) * 1.22)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linestyle=":")
    ax.set_axisbelow(True)
    fig.tight_layout()
    p1 = OUT_DIR / "k492_result_distribution.png"
    fig.savefig(p1, bbox_inches="tight")
    plt.close(fig)

    # ── Fig 2 ────────────────────────────────────────────────────────────
    n_classified = n_surv + n_fail
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    ax.bar(["單一樣本期\n看起來有效"], [n_classified], color=C_MID, width=0.5)
    ax.text(0, n_classified + 0.3, str(n_classified), ha="center",
            va="bottom", fontsize=13, fontweight="bold")

    ax.bar(["換一個樣本期\n重測"], [n_surv], color=C_OK, width=0.5,
           label=f"存活 {n_surv}")
    ax.bar(["換一個樣本期\n重測"], [n_fail], bottom=[n_surv], color=C_BAD,
           width=0.5, label=f"陣亡 {n_fail}")
    ax.text(1, n_surv / 2, f"存活 {n_surv}", ha="center", va="center",
            fontsize=12, color="white", fontweight="bold")
    ax.text(1, n_surv + n_fail / 2, f"陣亡 {n_fail}", ha="center", va="center",
            fontsize=12, color="white", fontweight="bold")

    ax.set_ylabel("實驗數")
    ax.set_title(
        f"單期有效 vs 跨期存活：{n_classified} 個候選，陣亡率 {fail_rate}%",
        fontsize=13, pad=12,
    )
    ax.set_ylim(0, n_classified * 1.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linestyle=":")
    ax.set_axisbelow(True)
    fig.tight_layout()
    p2 = OUT_DIR / "k492_cross_oos_survival.png"
    fig.savefig(p2, bbox_inches="tight")
    plt.close(fig)

    print(f"wrote {p1}")
    print(f"wrote {p2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
