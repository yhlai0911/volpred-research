#!/usr/bin/env python3
"""Render the data-bound charts used by the K1675 general article.

The closure-candidate classification comes from K1675's derivation audit.
The before/after metrics come from the clean-data reruns K758v2 and K739bv2.
No values are copied from article prose.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

plt.rcParams["font.family"] = ["Heiti TC", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render_residual_audit(k1675: dict) -> None:
    audit = k1675["derivation_audit"]
    accepted = [
        {"date": date, "category": "確認停市", "detail": "日曆漏列；獨立來源亦無交易"}
        for date in audit["source_b_residual_scan_accepted"]
    ]

    reason_map = {
        "0050 有真實行情": ("ETF 證明有開市", "0050 有真實行情"),
        "TWSE 融資券有資料": ("官方資料證明有開市", "TWSE 融資券有資料"),
        "緊鄰預定連假": ("日曆邊界誤標", "緊鄰春節連假"),
    }
    rejected = []
    for row in audit["source_b_residual_scan_rejected"]:
        category, detail = next(
            mapped for prefix, mapped in reason_map.items() if row["reason"].startswith(prefix)
        )
        rejected.append({"date": row["date"], "category": category, "detail": detail})

    rows = sorted(accepted + rejected, key=lambda row: row["date"])
    assert len(rows) == 6
    assert len(accepted) == 1 and len(rejected) == 5
    assert len(audit["source_a_library_typhoons"]) == 15

    colors = {
        "確認停市": "#2A9D8F",
        "ETF 證明有開市": "#457B9D",
        "官方資料證明有開市": "#E9C46A",
        "日曆邊界誤標": "#E76F51",
    }

    fig, ax = plt.subplots(figsize=(11, 6.4), dpi=180)
    y = list(range(len(rows)))
    ax.barh(y, [1] * len(rows), color=[colors[row["category"]] for row in rows], height=0.62)
    ax.set_yticks(y, [row["date"] for row in rows], fontsize=10)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.0)
    ax.set_xticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    for yi, row in zip(y, rows):
        ax.text(0.025, yi, f"{row['category']}｜{row['detail']}", va="center", ha="left",
                color="white" if row["category"] != "官方資料證明有開市" else "#333333",
                fontsize=10, fontweight="bold")

    ax.set_title("缺一根 K 線不等於停市：6 個殘差候選只有 1 個成立",
                 loc="left", fontsize=17, fontweight="bold", pad=22)
    ax.text(0, -0.13,
            "日曆套件另列 15 個颱風停市日；殘差掃描補到 2024-10-31 康芮，並剔除 5 個假候選。",
            transform=ax.transAxes, fontsize=10.5, color="#4D4D4D")
    fig.text(0.99, 0.012, "資料：K1675 derivation_audit（2012–2025）", ha="right",
             fontsize=8, color="#777777")
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    fig.savefig(OUT / "k1675_residual_candidate_audit.png", bbox_inches="tight")
    plt.close(fig)


def render_bad_row_consequences(k758v2: dict, k739bv2: dict) -> None:
    k758_compare = k758v2["comparison_with_original"]
    k739_compare = k739bv2["comparison_k739b_vs_k739bv2"]

    panels = [
        {
            "title": "0050 年化波動率",
            "before": float(k758_compare["original_tw_vol"]),
            "after": float(k758_compare["new_tw_vol"]),
            "suffix": "%",
            "ylim": (0, 30),
        },
        {
            "title": "VIX 解釋未來波動的比例",
            "before": float(k739_compare["test1"]["r2_vix_old"]) * 100,
            "after": float(k739_compare["test1"]["r2_vix_new"]) * 100,
            "suffix": "%",
            "ylim": (0, 30),
        },
        {
            "title": "每日調整策略評分",
            "before": float(k739_compare["test4"]["sharpe_changes"]["daily"]["old"]),
            "after": float(k739_compare["test4"]["sharpe_changes"]["daily"]["new"]),
            "suffix": "",
            "ylim": (0, 1.35),
        },
    ]

    fig, axes = plt.subplots(1, 3, figsize=(12, 5.8), dpi=180)
    for ax, panel in zip(axes, panels):
        vals = [panel["before"], panel["after"]]
        bars = ax.bar([0, 1], vals, color=["#B8B8B8", "#2A9D8F"], width=0.58)
        ax.set_xticks([0, 1], ["未清理", "清理後"], fontsize=10)
        ax.set_ylim(*panel["ylim"])
        ax.set_title(panel["title"], fontsize=12, fontweight="bold", pad=12)
        ax.grid(axis="y", alpha=0.22)
        ax.spines[["top", "right"]].set_visible(False)
        for bar, value in zip(bars, vals):
            label = f"{value:.2f}{panel['suffix']}"
            ax.text(bar.get_x() + bar.get_width() / 2, value + panel["ylim"][1] * 0.035,
                    label, ha="center", va="bottom", fontsize=11, fontweight="bold")

    fig.suptitle("同一筆 0050 假斷點，三個回測答案一起變形",
                 x=0.05, ha="left", fontsize=18, fontweight="bold")
    fig.text(0.05, 0.035,
             "2014-01-02 的幻影拆股斷點被移除後：風險估計下降，VIX 解釋力與策略評分大幅回升。",
             fontsize=10.5, color="#4D4D4D")
    fig.text(0.99, 0.012, "資料：K758v2、K739bv2 results JSON", ha="right",
             fontsize=8, color="#777777")
    fig.tight_layout(rect=[0, 0.08, 1, 0.90], w_pad=2.5)
    fig.savefig(OUT / "k1675_bad_row_consequences.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    k1675 = load_json(OUT / "k1675_results.json")
    k758v2 = load_json(ROOT / "experiments/k758v2/k758v2_tw_cross_border_hedge_results.json")
    k739bv2 = load_json(ROOT / "experiments/k739bv2/k739bv2_taiwan_vt_clean_results.json")
    render_residual_audit(k1675)
    render_bad_row_consequences(k758v2, k739bv2)
    print("wrote k1675_residual_candidate_audit.png")
    print("wrote k1675_bad_row_consequences.png")


if __name__ == "__main__":
    main()
