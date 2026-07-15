#!/usr/bin/env python3
"""Render reader-facing K1410 charts directly from certified results JSON."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import PercentFormatter


ROOT = Path(__file__).resolve().parents[4]
RESULTS_PATH = ROOT / "experiments" / "k1410" / "k1410_results.json"
OUT_DIR = Path(__file__).resolve().parent

NAVY = "#172554"
BLUE = "#2563EB"
PURPLE = "#7C3AED"
SLATE = "#64748B"
RED = "#DC2626"
BG = "#F8FAFC"
GRID = "#CBD5E1"


def _setup() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["PingFang TC", "Arial Unicode MS", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "axes.titleweight": "bold",
            "axes.titlesize": 20,
            "axes.labelsize": 12,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
        }
    )


def _finish(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def render_crash_timing(results: dict) -> None:
    markets = [("gspc", "美股 S&P 500"), ("twii", "台股加權")]
    year1 = []
    year30 = []
    err1 = [[], []]
    err30 = [[], []]
    ratios = []

    for key, _ in markets:
        block = results["crash_year_risk"][key]
        first = block["curve"][0]
        last = block["curve"][-1]
        year1.append(first["fail_prob"])
        year30.append(last["fail_prob"])
        err1[0].append(first["fail_prob"] - first["ci_lo"])
        err1[1].append(first["ci_hi"] - first["fail_prob"])
        err30[0].append(last["fail_prob"] - last["ci_lo"])
        err30[1].append(last["ci_hi"] - last["fail_prob"])
        ratios.append(block["early_to_late_ratio"])

    fig, ax = plt.subplots(figsize=(11.5, 6.8), facecolor=BG)
    ax.set_facecolor(BG)
    x = np.arange(len(markets))
    width = 0.32
    bars1 = ax.bar(
        x - width / 2,
        year1,
        width,
        color=RED,
        label="退休第 1 年大跌",
        yerr=np.array(err1),
        capsize=5,
    )
    bars30 = ax.bar(
        x + width / 2,
        year30,
        width,
        color=SLATE,
        label="退休第 30 年大跌",
        yerr=np.array(err30),
        capsize=5,
    )
    ax.bar_label(bars1, labels=[f"{v:.1%}" for v in year1], padding=6, fontsize=12, fontweight="bold")
    ax.bar_label(bars30, labels=[f"{v:.1%}" for v in year30], padding=6, fontsize=12, fontweight="bold")

    for i, ratio in enumerate(ratios):
        ax.text(
            i,
            max(year1[i], year30[i]) + 0.095,
            f"前 5 年／末 5 年：{ratio:.2f} 倍",
            ha="center",
            va="bottom",
            color=NAVY,
            fontsize=11,
            fontweight="bold",
        )

    ax.set_title("同樣一次單月 -35%，越早遇到越容易把退休金花光", color=NAVY, pad=20)
    ax.set_xticks(x, [label for _, label in markets])
    ax.set_ylabel("30 年內資產耗盡機率")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylim(0, 0.82)
    ax.grid(axis="y", color=GRID, linewidth=0.8, alpha=0.7)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    fig.text(
        0.5,
        0.015,
        "5,000 條 30 年路徑；100% 股票、年初固定提領。誤差線為 95% 區間。來源：報酬順序風險重跑結果。",
        ha="center",
        color=SLATE,
        fontsize=9.5,
    )
    _finish(fig, OUT_DIR / "k1410_crash_timing.png")


def render_withdrawal_choices(results: dict) -> None:
    strategies = [
        ("WR4.0%_100stock", "固定領 4%", SLATE),
        ("WR3.5%_100stock", "少領到 3.5%", BLUE),
        ("WR4.0%_dynamic_GK", "市場差就少領", PURPLE),
        ("WR5.0%_100stock", "多領到 5%", RED),
    ]
    markets = [("gspc", "美股"), ("twii", "台股")]
    values = {
        market: [results["strategy_evaluation"][market][key]["success_rate"] for key, _, _ in strategies]
        for market, _ in markets
    }

    fig, ax = plt.subplots(figsize=(12, 7.2), facecolor=BG)
    ax.set_facecolor(BG)
    x = np.arange(len(strategies))
    width = 0.32
    bars_us = ax.bar(x - width / 2, values["gspc"], width, color=BLUE, label="美股價格指數")
    bars_tw = ax.bar(x + width / 2, values["twii"], width, color=PURPLE, label="台股價格指數")
    ax.bar_label(bars_us, labels=[f"{v:.1%}" for v in values["gspc"]], padding=4, fontsize=11, fontweight="bold")
    ax.bar_label(bars_tw, labels=[f"{v:.1%}" for v in values["twii"]], padding=4, fontsize=11, fontweight="bold")

    ax.set_title("提領規則比『撐住不動』更能改變模擬結果", color=NAVY, pad=20)
    ax.set_xticks(x, [label for _, label, _ in strategies])
    ax.set_ylabel("30 年內未耗盡的模擬比例")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylim(0, 1.08)
    ax.grid(axis="y", color=GRID, linewidth=0.8, alpha=0.7)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    fig.text(
        0.5,
        0.012,
        "每組 10,000 條歷史重抽路徑；價格指數未含股息，數值用於模型內比較，不是可投資產品的退休預測。",
        ha="center",
        color=SLATE,
        fontsize=9.5,
    )
    _finish(fig, OUT_DIR / "k1410_withdrawal_choices.png")


def main() -> None:
    _setup()
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    render_crash_timing(results)
    render_withdrawal_choices(results)
    print(OUT_DIR / "k1410_crash_timing.png")
    print(OUT_DIR / "k1410_withdrawal_choices.png")


if __name__ == "__main__":
    main()
