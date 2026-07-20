#!/usr/bin/env python3
"""K740 general-audience figures.

Renders two reader-facing charts for the general-audience companion article.
Every value is read from k740_strategy_meta_analysis_results.json — nothing
is hard-coded in the plotting code.

Run:  .venv/bin/python experiments/k740/k740_general_figs.py
Out:  storage/assets/articles/k740_general_complexity_20260720.png
      storage/assets/articles/k740_general_diversification_20260720.png
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "experiments/k740/k740_strategy_meta_analysis_results.json"
OUT_DIR = ROOT / "storage/assets/articles"
OUT_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.sans-serif"] = [
    "PingFang HK",
    "PingFang TC",
    "Heiti TC",
    "Arial Unicode MS",
    "STHeiti",
    "sans-serif",
]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["axes.facecolor"] = "white"
plt.rcParams["axes.grid"] = True
plt.rcParams["grid.alpha"] = 0.25

data = json.loads(RESULTS.read_text())
metrics = data["strategy_metrics"]
chars = data["characteristics_analysis"]

TIER_LABEL = {1: "規則最陽春", 2: "中等", 3: "規則最多"}


def fig_complexity() -> Path:
    """Complexity tier vs composite score — the null result, in one picture."""
    tiers: dict[int, list[tuple[str, float]]] = {}
    for m in metrics.values():
        tiers.setdefault(m["complexity"], []).append((m["display"], m["composite_score"]))

    fig, ax = plt.subplots(figsize=(11, 6.2))
    colors = {1: "#2a9d8f", 2: "#e9c46a", 3: "#264653"}

    for tier in sorted(tiers):
        pts = tiers[tier]
        xs = [tier + (i - (len(pts) - 1) / 2) * 0.09 for i in range(len(pts))]
        ys = [p[1] for p in pts]
        ax.scatter(xs, ys, s=170, color=colors[tier], zorder=3,
                   edgecolor="white", linewidth=1.4)
        avg = mean(ys)
        ax.hlines(avg, tier - 0.34, tier + 0.34, color=colors[tier],
                  linewidth=3, linestyle="--", zorder=2)
        ax.text(tier + 0.38, avg, f"這一組平均 {avg:.3f}", va="center",
                fontsize=11, color=colors[tier])

    best = max(metrics.values(), key=lambda m: m["composite_score"])
    worst_complex = min(
        (m for m in metrics.values() if m["complexity"] == 3),
        key=lambda m: m["composite_score"],
    )
    ax.annotate(
        f"{best['display']}\n規則最陽春，總分第一 {best['composite_score']:.3f}",
        xy=(best["complexity"], best["composite_score"]),
        xytext=(1.25, 0.90), fontsize=11,
        arrowprops=dict(arrowstyle="->", color="#555"),
    )
    ax.annotate(
        f"{worst_complex['display']}\n規則最多，總分 {worst_complex['composite_score']:.3f}",
        xy=(worst_complex["complexity"], worst_complex["composite_score"]),
        xytext=(2.05, 0.10), fontsize=11,
        arrowprops=dict(arrowstyle="->", color="#555"),
    )

    ax.set_xticks(sorted(tiers))
    ax.set_xticklabels([f"{TIER_LABEL[t]}\n（{len(tiers[t])} 套）" for t in sorted(tiers)],
                       fontsize=12)
    ax.set_ylabel("綜合分數（10 項指標等權加總，滿分 1）", fontsize=12)
    ax.set_ylim(0, 1.0)
    ax.set_xlim(0.55, 3.6)
    ax.set_title("規則越花俏，總分就越高嗎？14 套策略的答案是「看不出來」",
                 fontsize=16, pad=14)
    ax.text(
        0.62, 0.035,
        f"複雜度與風險調整後報酬的等級相關 {chars['complexity_sharpe_correlation']['rho']:.3f}"
        f"（若兩者無關，光靠運氣出現這麼強關聯的機率 {chars['complexity_sharpe_correlation']['p']:.4f}）"
        f"｜資料：2023-01-04~2026-03-27 forward-tracked 紙上交易",
        fontsize=9.5, color="#555",
    )
    fig.tight_layout()
    out = OUT_DIR / "k740_general_complexity_20260720.png"
    fig.savefig(out, dpi=145)
    plt.close(fig)
    return out


def fig_diversification() -> Path:
    """Average risk-adjusted return by what the strategy actually holds."""
    acs = chars["asset_class_sharpes"]
    label = {
        "SPY-only": "只買美股大盤",
        "SPY+GLD": "美股大盤＋黃金",
        "0050.TW": "只買台股 0050",
        "multi-Asia": "台股＋日股",
        "global": "全球多市場",
    }
    counts: dict[str, int] = {}
    for m in metrics.values():
        counts[m["asset_class"]] = counts.get(m["asset_class"], 0) + 1

    order = sorted(acs, key=lambda k: acs[k])
    vals = [acs[k] for k in order]
    names = [f"{label[k]}\n（{counts[k]} 套）" for k in order]

    fig, ax = plt.subplots(figsize=(11, 5.8))
    bars = ax.bar(names, vals, color=["#b5495b", "#e76f51", "#e9c46a", "#2a9d8f", "#264653"],
                  width=0.62, zorder=3)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.06, f"{v:.3f}",
                ha="center", fontsize=13)

    gap = acs["SPY+GLD"] - acs["SPY-only"]
    ax.annotate(
        "", xy=(0, acs["SPY-only"]), xytext=(0, acs["SPY+GLD"]),
        arrowprops=dict(arrowstyle="<->", color="#333", linewidth=1.6),
    )
    ax.text(0.12, (acs["SPY-only"] + acs["SPY+GLD"]) / 2,
            f"同樣是美股，\n多擺一份黃金差 {gap:.3f}", fontsize=11.5, va="center")

    ax.set_ylabel("每承受一分波動換到的報酬（組內平均）", fontsize=12)
    ax.set_ylim(0, max(vals) * 1.22)
    ax.set_title("拉開差距的是「手上有幾種資產」，不是規則寫得多漂亮",
                 fontsize=16, pad=14)
    ax.text(
        -0.45, -max(vals) * 0.20,
        "資料：14 套 forward-tracked 紙上交易策略，2023-01-04~2026-03-27。"
        "各組套數不同、上線時間不同，這是描述性比較，不是隨機分組實驗。",
        fontsize=9.5, color="#555",
    )
    fig.tight_layout()
    out = OUT_DIR / "k740_general_diversification_20260720.png"
    fig.savefig(out, dpi=145, bbox_inches="tight")
    plt.close(fig)
    return out


if __name__ == "__main__":
    for p in (fig_complexity(), fig_diversification()):
        print("wrote", p.relative_to(ROOT))
