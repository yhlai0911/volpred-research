"""K871 chart generation for general-audience feed article.

Reads k871_results.json and produces 2 publication-grade PNGs:
  1. k871_oos_r2_comparison.png — Bar chart of OOS R² across 7 model variants
  2. k871_inversion_vol_distribution.png — Mean fwd vol: inverted vs normal regimes

Output paths:
  experiments/k871/k871_oos_r2_comparison.png
  experiments/k871/k871_inversion_vol_distribution.png
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "k871_results.json"


def main() -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    models = data["regression_models"]
    event = data["event_analysis"]

    # ─── Chart 1: OOS R² across 7 model variants ─────────────────────
    label_map = {
        "A_vix_only": "VIX 單獨\n(基準)",
        "B_vix_slope": "VIX + 10Y2Y\n斜率",
        "C_vix_slope_lvl": "VIX + 斜率\n+ 10Y 水準",
        "D_slope_only": "斜率單獨\n(無 VIX)",
        "E_vix_dslope": "VIX + 斜率\n22 日變動",
        "F_slope3m_only": "10Y3M 斜率\n單獨",
        "G_vix_slope3m": "VIX + 10Y3M\n斜率",
    }
    order = [
        "A_vix_only",
        "B_vix_slope",
        "C_vix_slope_lvl",
        "E_vix_dslope",
        "G_vix_slope3m",
        "D_slope_only",
        "F_slope3m_only",
    ]
    labels = [label_map[k] for k in order]
    oos_r2 = [models[k]["OOS_R2"] for k in order]

    # Color: baseline grey, VIX+slope variants blue, slope-only variants red
    colors = []
    for k in order:
        if k == "A_vix_only":
            colors.append("#444444")
        elif "slope_only" in k or "slope3m_only" in k:
            colors.append("#c0392b")
        else:
            colors.append("#2980b9")

    fig, ax = plt.subplots(figsize=(11, 6))
    bars = ax.bar(range(len(order)), oos_r2, color=colors, edgecolor="black", linewidth=0.6)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("樣本外 R² (Out-of-Sample R²)", fontsize=11)
    ax.set_title(
        "K871: 殖利率曲線斜率加入後，預測力幾乎沒變\n"
        "(SPY 22 日 forward RV，2019–2026 OOS, n=1,799)",
        fontsize=12, pad=12,
    )
    ax.axhline(0, color="black", linewidth=0.6)
    ax.axhline(models["A_vix_only"]["OOS_R2"], color="#444444",
               linestyle=":", linewidth=1.2,
               label=f"VIX 基準 R² = {models['A_vix_only']['OOS_R2']:.4f}")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    for bar, val in zip(bars, oos_r2):
        h = bar.get_height()
        offset = 0.005 if h >= 0 else -0.015
        ax.text(bar.get_x() + bar.get_width() / 2, h + offset,
                f"{val:.4f}",
                ha="center", va="bottom" if h >= 0 else "top",
                fontsize=8.5)

    fig.text(0.99, 0.01,
             "資料：FRED (T10Y2Y/T10Y3M/DGS10) + yfinance (SPY/^VIX)。Source: K871 results.json",
             ha="right", fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.025, 1, 1))
    out1 = ROOT / "k871_oos_r2_comparison.png"
    fig.savefig(out1, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out1}")

    # ─── Chart 2: Mean forward RV: inverted vs normal regimes ────────
    fig, ax = plt.subplots(figsize=(9, 6))
    means = [event["mean_rv22_inverted"], event["mean_rv22_normal"]]
    labels2 = [f"曲線倒掛日\n(n={event['n_inversion_days']:,})",
               f"非倒掛日\n(n={6554 - event['n_inversion_days']:,})"]
    colors2 = ["#c0392b", "#2980b9"]

    bars2 = ax.bar(labels2, means, color=colors2, edgecolor="black", linewidth=0.6,
                   width=0.5)
    ax.set_ylabel("平均 22 日 forward 已實現波動率 (年化)", fontsize=11)
    ax.set_title(
        "K871: 殖利率曲線倒掛日的事後波動，反而比正常日略低\n"
        "「倒掛代表高波動」的直覺被資料推翻 (2000–2026, n=6,554)",
        fontsize=12, pad=12,
    )
    ax.set_ylim(0, max(means) * 1.25)

    for bar, val in zip(bars2, means):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 0.005,
                f"{val:.4f}",
                ha="center", va="bottom", fontsize=11, fontweight="bold")

    diff_pct = event["difference_pct"]
    ax.text(0.5, 0.96,
            f"差異：{diff_pct:+.2f}%（倒掛日比正常日低 {abs(diff_pct):.2f}%）",
            transform=ax.transAxes, ha="center", va="top", fontsize=10,
            bbox=dict(facecolor="#fff8dc", edgecolor="#aaaaaa", boxstyle="round,pad=0.4"))

    ax.grid(axis="y", linestyle="--", alpha=0.4)
    fig.text(0.99, 0.01,
             "資料：FRED T10Y2Y + SPY 報酬計算 forward RV22。Source: K871 results.json",
             ha="right", fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.025, 1, 1))
    out2 = ROOT / "k871_inversion_vol_distribution.png"
    fig.savefig(out2, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out2}")


if __name__ == "__main__":
    main()
