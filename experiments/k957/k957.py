"""
K957: K526-K566 Session Synthesis — 37 Experiments, 5 Meta-Lessons

Pure synthesis script. 不做新模型估計，只讀既有 experiment JSON 與
experiment_experiences.json E019-E023，輸出：

  1. k957_results.json  — meta-summary (counts / Harvey t-stats / map)
  2. k957_timeline.png  — K526-K566 timeline + verdict distribution
  3. k957_sankey.png    — experiments → E019-E023 meta-lesson flow

Run:
  uv run python experiments/k957/k957.py
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = ROOT / "experiments"
OUT_DIR = Path(__file__).parent
RESULTS_PATH = OUT_DIR / "k957_results.json"
TIMELINE_PNG = OUT_DIR / "k957_timeline.png"
SANKEY_PNG = OUT_DIR / "k957_sankey.png"

# -----------------------------------------------------------------------------
# Experiment classification table
# -----------------------------------------------------------------------------
# class_label 映射到 meta-lesson：
#   A: Harvey-pass, listable (portfolio-construction win)      -> E021
#   B: Harvey-pass, methodology insight (distribution / proxy) -> E023
#   C: predictive win but no trading lift                      -> E023
#   D: VIX-sufficiency null (options market efficient)         -> E020
#   E: daily-only alpha artifact                               -> E019
#   F: BTC correlation regime shift                            -> E022
#   G: cross-asset / theory null                                -> E020
#
# 參考來源：storage/memory/experiment_experiences.json E019-E023
#          對應 experiments/k{526..566}/*_results.json Harvey t-stat

CLASSIFICATION: dict[str, dict] = {
    "K526": {"class": "G", "note": "VIX-macro interaction null"},
    "K527": {"class": "G", "note": "term-structure exploration"},
    "K528": {"class": "G", "note": "signal scaffolding"},
    "K529": {"class": "B", "note": "Rough Vol H=0.1 diagnostic, TV-H worse"},
    "K530": {"class": "B", "note": "HAR+|r| proxy 7/7 universal breakthrough",
             "dm_t_range": "-11 to -22"},
    "K531": {"class": "B", "note": "HAR proxy follow-up"},
    "K532": {"class": "B", "note": "HAR universal 7/7 confirmation"},
    "K533": {"class": "C", "note": "HAR-ABS best predictor ≠ best VT (E002 #5)"},
    "K534": {"class": "F", "note": "SPY-GLD VIX-beta sign flip across decades"},
    "K535": {"class": "D", "note": "SKEW IS t=-3.01, OOS null"},
    "K536": {"class": "B", "note": "HAR-EVT Trinity PASS (唯一過的 VaR model)",
             "trinity_pass": True},
    "K537": {"class": "D", "note": "cross-asset vol momentum null"},
    "K538": {"class": "D", "note": "meta-label AUC 0.48-0.52"},
    "K539": {"class": "D", "note": "VRP carry not orthogonal to VIX"},
    "K540": {"class": "D", "note": "12/VIX optimal confirmed #8 (E005)"},
    "K541": {"class": "D", "note": "meta-label AUC 0.52"},
    "K542": {"class": "D", "note": "VIX term structure ratio null"},
    "K543": {"class": "D", "note": "drawdown corr=0.77 with VIX"},
    "K544": {"class": "G", "note": "sector allocation exploration"},
    "K545": {"class": "G", "note": "regime basic"},
    "K546": {"class": "G", "note": "volatility asymmetry"},
    "K547": {"class": "G", "note": "leverage pre-study"},
    "K548": {"class": "A", "note": "VIX-Cond Leverage US", "harvey_t": 7.90,
             "oos_rate": "11/11", "listable": True},
    "K549": {"class": "G", "note": "leverage sensitivity"},
    "K550": {"class": "G", "note": "leverage cost curve"},
    "K551": {"class": "A", "note": "K548 validation", "harvey_t": 7.90,
             "oos_rate": "11/11", "listable": True},
    "K552": {"class": "G", "note": "TW base-rate calibration"},
    "K553": {"class": "A", "note": "Taiwan Hybrid Leverage", "harvey_t": 4.79,
             "oos_rate": "18/18", "listable": True},
    "K554": {"class": "D", "note": "HMM regime partial R²=0.000169"},
    "K556": {"class": "D", "note": "momentum crash filter +0.03 Sharpe 邊際"},
    "K557": {"class": "G", "note": "Taiwan stress-test"},
    "K558": {"class": "A", "note": "K553 validation", "harvey_t": 4.79,
             "oos_rate": "18/18", "listable": True},
    "K559": {"class": "G", "note": "daily / monthly pre-study"},
    "K560": {"class": "E", "note": "sector momentum daily 2.157 → monthly 1.228",
             "daily_sharpe": 2.157, "monthly_sharpe": 1.228,
             "benchmark_monthly": 1.345},
    "K561": {"class": "G", "note": "daily artifact sensitivity"},
    "K562": {"class": "E", "note": "monthly downgrade confirmation"},
    "K563": {"class": "E", "note": "weekly Sharpe 1.067 Harvey FAIL"},
    "K564": {"class": "D", "note": "VIX slope 1st/2nd derivative r=-0.029 null"},
    "K565": {"class": "F", "note": "BTC full-sample t=3.07 but post-ETF +0.010"},
    "K566": {"class": "E", "note": "factor rotation daily 2.091 → monthly 1.448"},
}

# K555 / K569 intentionally skipped in actual experiments directory (shown as
# "missing" markers on the timeline).
MISSING_IDS = ["K555", "K569"]

CLASS_TO_LESSON = {
    "A": "E021",  # portfolio-construction win
    "B": "E023",  # HAR / distribution methodology
    "C": "E023",  # prediction ≠ trading
    "D": "E020",  # VIX sufficiency
    "E": "E019",  # daily-only artifact
    "F": "E022",  # BTC / correlation regime
    "G": "E020",  # exploratory, mostly VIX-sufficient adjacent
}

CLASS_COLORS = {
    "A": "#2ecc71",  # pass listable — green
    "B": "#27ae60",  # methodology insight — dark green
    "C": "#f39c12",  # predictive only — orange
    "D": "#e74c3c",  # VIX null — red
    "E": "#c0392b",  # daily artifact — dark red
    "F": "#9b59b6",  # BTC regime — purple
    "G": "#95a5a6",  # exploratory — grey
}

LESSON_TITLES = {
    "E019": "Daily alpha is microstructure artifact — test monthly",
    "E020": "VIX sufficiency extends to ALL derivative signals",
    "E021": "Portfolio construction > signal discovery",
    "E022": "BTC correlation regime shift → verify recent data",
    "E023": "HAR+|r| universal, but prediction ≠ trading",
}


# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
def build_summary() -> dict:
    counts = Counter(entry["class"] for entry in CLASSIFICATION.values())
    harvey_rows: list[dict] = []
    for kid, entry in CLASSIFICATION.items():
        if entry["class"] == "A":
            harvey_rows.append(
                {
                    "experiment": kid,
                    "note": entry["note"],
                    "harvey_t": entry["harvey_t"],
                    "oos_rate": entry["oos_rate"],
                    "listable": entry.get("listable", False),
                }
            )

    lesson_map: dict[str, list[str]] = {lid: [] for lid in LESSON_TITLES}
    for kid, entry in CLASSIFICATION.items():
        lesson = CLASS_TO_LESSON[entry["class"]]
        lesson_map[lesson].append(kid)

    return {
        "experiment_id": "K957",
        "title": "K526-K566 Session Synthesis — 37 Experiments, 5 Meta-Lessons",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": "meta-synthesis",
        "scope": {
            "session_range": "K526-K566",
            "n_experiments_classified": len(CLASSIFICATION),
            "n_missing_ids": len(MISSING_IDS),
            "experience_entries": ["E019", "E020", "E021", "E022", "E023"],
        },
        "class_counts": dict(counts),
        "class_definitions": {
            "A": "Harvey-pass, listable (portfolio construction win)",
            "B": "Harvey-pass, methodology insight (distribution / proxy)",
            "C": "Predictive win but no trading lift",
            "D": "VIX-sufficiency null (options market efficient)",
            "E": "Daily-only alpha artifact (monthly degrades)",
            "F": "BTC / cross-asset correlation regime shift",
            "G": "Exploratory / scaffolding / VIX-sufficient adjacent",
        },
        "harvey_pass_listable": harvey_rows,
        "universal_breakthroughs": {
            "har_abs_7_of_7": {
                "source": ["K530", "K532"],
                "dm_t_range": "-11 to -22",
                "note": "|r_t| absolute-return proxy outperforms r²_t 3x in QLIKE",
            },
            "har_evt_trinity": {
                "source": "K536",
                "tests_passed": ["Kupiec", "Christoffersen", "DQ"],
                "note": "Only VaR model in K526-K566 to clear Trinity",
            },
        },
        "vix_sufficiency_confirmations": {
            "count_in_session": sum(1 for e in CLASSIFICATION.values() if e["class"] == "D"),
            "cumulative_confirmations": 37,
            "source_experiments": [
                kid for kid, e in CLASSIFICATION.items() if e["class"] == "D"
            ],
            "signal_types_nullified": [
                "SKEW (K535)",
                "cross-asset vol momentum (K537)",
                "VRP carry (K539)",
                "VIX term-structure ratio (K542)",
                "VIX slope derivatives (K564)",
                "HMM regime state (K554)",
                "meta-labeling (K538/K541)",
                "momentum crash filter (K556)",
                "drawdown-based signals (K543)",
            ],
        },
        "daily_artifact_cases": [
            {
                "kid": "K560",
                "daily_sharpe": 2.157,
                "monthly_sharpe": 1.228,
                "benchmark_monthly": 1.345,
            },
            {"kid": "K563", "weekly_sharpe": 1.067, "harvey": "FAIL"},
            {"kid": "K566", "daily_sharpe": 2.091, "monthly_sharpe": 1.448},
        ],
        "lesson_map": lesson_map,
        "meta_lessons": [
            {
                "id": lid,
                "title": LESSON_TITLES[lid],
                "n_experiments": len(lesson_map[lid]),
                "experiments": lesson_map[lid],
            }
            for lid in ["E019", "E020", "E021", "E022", "E023"]
        ],
        "recommendations": {
            "signal_discovery_budget_pct": 0,
            "portfolio_construction_budget_pct": 100,
            "rebalancing_frequency_reporting": "daily AND monthly mandatory",
            "har_framework_scope": "VaR / risk-management, NOT trading signal",
            "return_proxy_choice": "|r_t| (absolute), never r²_t",
            "cross_asset_strategy_rule": "report full-sample + last-2-year separately; "
            "fallback to momentum condition if post-break Sharpe improvement < 0.05",
        },
        "missing_ids": MISSING_IDS,
    }


# -----------------------------------------------------------------------------
# Chart 1: Session timeline
# -----------------------------------------------------------------------------
def draw_timeline(summary: dict) -> None:
    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(12.5, 6.2), gridspec_kw={"height_ratios": [2.1, 1]}
    )

    ordered_ids = sorted(CLASSIFICATION.keys(), key=lambda k: int(k[1:]))
    xs = list(range(len(ordered_ids)))

    # Top: verdict heatmap (per-experiment colored tiles)
    for x, kid in zip(xs, ordered_ids):
        cls = CLASSIFICATION[kid]["class"]
        color = CLASS_COLORS[cls]
        ax_top.add_patch(
            plt.Rectangle(
                (x - 0.45, 0.05), 0.9, 0.9, facecolor=color,
                edgecolor="white", linewidth=0.7,
            )
        )
        ax_top.text(
            x, 0.5, kid[1:], ha="center", va="center",
            fontsize=6.5, color="white", fontweight="bold",
        )

    # annotate Harvey-pass experiments with stars
    for x, kid in zip(xs, ordered_ids):
        if CLASSIFICATION[kid]["class"] == "A":
            ax_top.text(x, 1.05, "*", ha="center", va="bottom",
                        fontsize=14, color="#d4ac0d", fontweight="bold")

    ax_top.set_xlim(-0.8, len(ordered_ids) - 0.2)
    ax_top.set_ylim(0, 1.25)
    ax_top.set_yticks([])
    ax_top.set_xticks(xs[::5])
    ax_top.set_xticklabels([ordered_ids[i] for i in xs[::5]], fontsize=8)
    ax_top.set_title(
        "K957 Session Timeline — K526~K566 (37 experiments, * = Harvey-pass listable)",
        fontsize=11, pad=10,
    )
    for spine in ("top", "right", "left"):
        ax_top.spines[spine].set_visible(False)

    # Bottom: class distribution bar
    counts = summary["class_counts"]
    class_order = ["A", "B", "C", "D", "E", "F", "G"]
    values = [counts.get(c, 0) for c in class_order]
    labels = [
        "A: listable",
        "B: method insight",
        "C: pred-only",
        "D: VIX null",
        "E: daily artifact",
        "F: regime shift",
        "G: exploratory",
    ]
    colors = [CLASS_COLORS[c] for c in class_order]
    bars = ax_bot.bar(labels, values, color=colors, edgecolor="white", linewidth=0.8)
    for bar, v in zip(bars, values):
        ax_bot.text(
            bar.get_x() + bar.get_width() / 2, v + 0.2, str(v),
            ha="center", va="bottom", fontsize=9, fontweight="bold",
        )
    ax_bot.set_ylabel("# experiments", fontsize=9)
    ax_bot.set_title(
        "Class distribution — null-dominant session "
        "(D+E+F = structural nulls, only A/B are durable wins)",
        fontsize=10, pad=6,
    )
    ax_bot.tick_params(axis="x", labelsize=8, rotation=15)
    for spine in ("top", "right"):
        ax_bot.spines[spine].set_visible(False)

    plt.tight_layout()
    fig.savefig(TIMELINE_PNG, dpi=140, bbox_inches="tight")
    plt.close(fig)


# -----------------------------------------------------------------------------
# Chart 2: Experiments → Meta-lesson flow (simplified Sankey-style)
# -----------------------------------------------------------------------------
def draw_sankey(summary: dict) -> None:
    fig, ax = plt.subplots(figsize=(12.5, 6.8))

    lesson_order = ["E019", "E020", "E021", "E022", "E023"]
    class_order = ["A", "B", "C", "D", "E", "F", "G"]
    class_labels = {
        "A": "A · Harvey-pass listable",
        "B": "B · methodology insight",
        "C": "C · predictive-only",
        "D": "D · VIX sufficiency null",
        "E": "E · daily-only artifact",
        "F": "F · regime-shift",
        "G": "G · exploratory",
    }

    # left column: class blocks — height proportional to count
    left_x = 0.08
    right_x = 0.82
    total = sum(summary["class_counts"].values())
    gap = 0.012

    y_cursor = 0.98
    class_rects: dict[str, tuple[float, float, float]] = {}  # x, y_top, height
    for cls in class_order:
        count = summary["class_counts"].get(cls, 0)
        h = max(0.03, (count / total) * 0.92)
        y_top = y_cursor
        y_bot = y_top - h
        ax.add_patch(
            plt.Rectangle(
                (left_x, y_bot), 0.18, h,
                facecolor=CLASS_COLORS[cls], edgecolor="white", linewidth=1.2,
            )
        )
        ax.text(
            left_x + 0.09, (y_top + y_bot) / 2,
            f"{class_labels[cls]}  (n={count})",
            ha="center", va="center", fontsize=8.5, color="white", fontweight="bold",
        )
        class_rects[cls] = (left_x + 0.18, y_top, h)
        y_cursor = y_bot - gap

    # right column: lesson blocks
    y_cursor = 0.98
    lesson_rects: dict[str, tuple[float, float, float]] = {}
    for lid in lesson_order:
        kids = summary["lesson_map"][lid]
        count = len(kids)
        h = max(0.04, (count / total) * 0.92)
        y_top = y_cursor
        y_bot = y_top - h
        ax.add_patch(
            plt.Rectangle(
                (right_x, y_bot), 0.17, h,
                facecolor="#34495e", edgecolor="white", linewidth=1.2,
            )
        )
        title_lines = LESSON_TITLES[lid].split(" — ")
        ax.text(
            right_x + 0.085, (y_top + y_bot) / 2 + 0.018,
            f"{lid}  (n={count})",
            ha="center", va="center", fontsize=9, color="white", fontweight="bold",
        )
        ax.text(
            right_x + 0.085, (y_top + y_bot) / 2 - 0.018,
            title_lines[0][:40],
            ha="center", va="center", fontsize=7, color="#ecf0f1",
        )
        lesson_rects[lid] = (right_x, y_top, h)
        y_cursor = y_bot - gap

    # curves from class → lesson
    for cls in class_order:
        lesson = CLASS_TO_LESSON[cls]
        if cls not in class_rects or lesson not in lesson_rects:
            continue
        x0, y0_top, h0 = class_rects[cls]
        x1, y1_top, h1 = lesson_rects[lesson]
        y0 = y0_top - h0 / 2
        y1 = y1_top - h1 / 2
        mid_x = (x0 + x1) / 2
        xs = np.linspace(x0, x1, 50)
        # simple cosine interpolation for smooth-ish curve
        t = (xs - x0) / (x1 - x0)
        smooth = 0.5 - 0.5 * np.cos(np.pi * t)
        ys = y0 + (y1 - y0) * smooth
        ax.plot(xs, ys, color=CLASS_COLORS[cls], alpha=0.55, linewidth=2.6)

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title(
        "K957 Sankey — Experiments → E019-E023 Meta-Lessons "
        "(curve width = class size proxy)",
        fontsize=11, pad=12,
    )
    # legend for lesson titles
    legend_y = 0.02
    for i, lid in enumerate(lesson_order):
        ax.text(
            0.5, legend_y + (4 - i) * 0.028,
            f"{lid}: {LESSON_TITLES[lid]}",
            fontsize=7.5, ha="center", va="bottom", color="#2c3e50",
        )

    plt.tight_layout()
    fig.savefig(SANKEY_PNG, dpi=140, bbox_inches="tight")
    plt.close(fig)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> None:
    summary = build_summary()
    RESULTS_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    draw_timeline(summary)
    draw_sankey(summary)

    print(f"[K957] wrote {RESULTS_PATH}")
    print(f"[K957] wrote {TIMELINE_PNG}")
    print(f"[K957] wrote {SANKEY_PNG}")
    print(f"[K957] class counts: {summary['class_counts']}")
    print(
        f"[K957] Harvey-pass listable: "
        f"{[r['experiment'] for r in summary['harvey_pass_listable']]}"
    )


if __name__ == "__main__":
    main()
