"""K1198 article 圖表生成 — 兩張 PNG。

Chart 1: 6 個 KB-only 值的 paper vs 重算對照（matched / diverged 分色）。
Chart 2: C3 gold-regime gamma — 76 個 window 的 trailing 252-day return vs gamma 散布，
         bull / bear regime 分色 + 邊界線。
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
RESULTS = json.load(open(HERE.parent / "k1198_results.json"))
OUT = HERE


def fmt(v: float) -> str:
    if abs(v) < 0.01:
        return f"{v:.4f}"
    return f"{v:.3f}"


def chart_one_audit_dashboard() -> Path:
    labels = [
        "T10 avg γ\n(SPY 成分股)",
        "T10 t-stat\n(ETF vs 股)",
        "T11 ES(1%)\nBH",
        "T11 超額\n峰度 BH",
        "T12 Spearman\nρ(γ, β)",
        "C3 t-stat\nbull vs bear",
    ]
    paper = [0.076, -16.92, -4.68, 14.71, 1.000, -4.71]
    redo = [
        RESULTS["table10"]["avg_constituent_gamma"],
        RESULTS["table10"]["t_stat_vs_etf"],
        RESULTS["table11"]["bh_es_1pct"],
        RESULTS["table11"]["bh_kurtosis"],
        RESULTS["table12"]["spearman_rho"],
        RESULTS["c3_gold_regime"]["t_stat_bull_vs_bear"],
    ]
    matched = [False, False, True, True, True, False]

    fig, axes = plt.subplots(2, 3, figsize=(13.5, 7.5))
    fig.suptitle(
        "K1198：6 個 KB-only 值的 paper vs 重算對照",
        fontsize=14,
        fontweight="bold",
        fontfamily=["Heiti TC", "PingFang TC", "sans-serif"],
    )

    for idx, ax in enumerate(axes.flatten()):
        bar_colors = ["#7090c0", "#52c07a" if matched[idx] else "#e07070"]
        bars = ax.bar(["paper", "重算"], [paper[idx], redo[idx]], color=bar_colors, width=0.55)
        ax.set_title(
            labels[idx],
            fontsize=10,
            fontfamily=["Heiti TC", "PingFang TC", "sans-serif"],
        )
        for bar, val in zip(bars, [paper[idx], redo[idx]]):
            offset = max(abs(paper[idx]), abs(redo[idx])) * 0.05
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + (offset if val >= 0 else -offset),
                fmt(val),
                ha="center",
                va="bottom" if val >= 0 else "top",
                fontsize=9,
            )
        ax.axhline(0, color="#888", linewidth=0.6)
        ax.grid(axis="y", alpha=0.25)
        ymax = max(paper[idx], redo[idx])
        ymin = min(paper[idx], redo[idx])
        pad = max(abs(ymax), abs(ymin)) * 0.35 + 0.5
        ax.set_ylim(min(ymin, 0) - pad, max(ymax, 0) + pad)
        verdict = "MATCH" if matched[idx] else "DIFF"
        ax.text(
            0.97,
            0.95,
            verdict,
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=9,
            fontweight="bold",
            color="#2f7d4f" if matched[idx] else "#a83232",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="none", alpha=0.85),
        )

    fig.text(
        0.5,
        0.02,
        "3 個 MATCH（綠）、3 個 DIFF（紅）。Verdict = MODIFY_PAPER：4 個 footnote / 數字更正，論文核心結論不變。",
        ha="center",
        fontsize=9,
        fontfamily=["Heiti TC", "PingFang TC", "sans-serif"],
        color="#444",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    out = OUT / "k1198_audit_dashboard.png"
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_two_gold_regime() -> Path:
    c3 = RESULTS["c3_gold_regime"]
    gammas = np.array(c3["all_gammas"])
    rets = np.array(c3["trailing_rets"])

    bull_mask = rets > 0
    bear_mask = ~bull_mask

    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    ax.scatter(
        rets[bull_mask],
        gammas[bull_mask],
        s=55,
        c="#cda84a",
        edgecolors="#7a6020",
        linewidth=0.7,
        label=f"Bull regime (N={int(bull_mask.sum())})",
        alpha=0.85,
    )
    ax.scatter(
        rets[bear_mask],
        gammas[bear_mask],
        s=55,
        c="#5b78b0",
        edgecolors="#243a66",
        linewidth=0.7,
        label=f"Bear regime (N={int(bear_mask.sum())})",
        alpha=0.85,
    )

    ax.axvline(0, color="#666", linestyle="--", linewidth=0.7)
    ax.axhline(0, color="#666", linestyle="--", linewidth=0.7)

    ax.axhline(
        c3["bull_mean_gamma"],
        xmin=0.5,
        xmax=1.0,
        color="#7a6020",
        linewidth=1.4,
        linestyle="-",
        alpha=0.7,
    )
    ax.axhline(
        c3["bear_mean_gamma"],
        xmin=0.0,
        xmax=0.5,
        color="#243a66",
        linewidth=1.4,
        linestyle="-",
        alpha=0.7,
    )

    ax.text(
        40,
        c3["bull_mean_gamma"] - 0.012,
        f"bull mean γ = {c3['bull_mean_gamma']:.3f}",
        fontsize=9,
        color="#5a4515",
    )
    ax.text(
        -28,
        c3["bear_mean_gamma"] + 0.008,
        f"bear mean γ = +{c3['bear_mean_gamma']:.3f}",
        fontsize=9,
        color="#1a2a4a",
    )

    title = (
        "C3 黃金 leverage direction — 76 個 rolling window 的 γ vs 252 日趨勢報酬\n"
        f"重算 t = {c3['t_stat_bull_vs_bear']:.2f}（p < 0.001），論文原值 t = -4.71（同方向、同顯著）"
    )
    ax.set_title(
        title,
        fontsize=12,
        fontfamily=["Heiti TC", "PingFang TC", "sans-serif"],
    )
    ax.set_xlabel(
        "Trailing 252-day cumulative return (%)",
        fontsize=10,
    )
    ax.set_ylabel("GJR-GARCH γ（leverage parameter）", fontsize=10)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.25)

    out = OUT / "k1198_gold_regime.png"
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out


if __name__ == "__main__":
    p1 = chart_one_audit_dashboard()
    p2 = chart_two_gold_regime()
    print(p1)
    print(p2)
