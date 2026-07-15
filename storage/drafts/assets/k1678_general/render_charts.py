#!/usr/bin/env python3
"""Render reader-facing K1678 charts from the reviewed result package."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[4]
RESULTS_PATH = ROOT / "experiments" / "K1678" / "K1678_results.json"
OUT_DIR = Path(__file__).resolve().parent

NAVY = "#172554"
BLUE = "#2563EB"
TEAL = "#0F766E"
AMBER = "#B45309"
RED = "#DC2626"
SLATE = "#64748B"
GRID = "#CBD5E1"
BG = "#F8FAFC"


def _setup() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["PingFang TC", "Heiti TC", "Arial Unicode MS", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "axes.titleweight": "bold",
            "axes.titlesize": 20,
            "axes.labelsize": 12,
            "xtick.labelsize": 10.5,
            "ytick.labelsize": 10.5,
        }
    )


def _finish(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUT_DIR / name, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def render_attention_gate(results: dict) -> None:
    rows = results["primary_results"]
    outcome_names = {
        "rv": "整體波動",
        "dsv": "下行波動",
        "left_tail": "最大跌幅",
        "downside_gap": "向下跳空",
    }
    labels = [f"{row['horizon']} 日｜{outcome_names[row['outcome']]}" for row in rows]
    strength = [abs(float(row["t_hac"])) for row in rows]
    colors = [BLUE if row["horizon"] == 1 else TEAL for row in rows]

    fig, ax = plt.subplots(figsize=(11.5, 7.4), facecolor=BG)
    ax.set_facecolor(BG)
    y = np.arange(len(labels))
    bars = ax.barh(y, strength, color=colors, height=0.62)
    ax.axvline(3.0, color=RED, linestyle="--", linewidth=1.6, label="嚴格門檻 3.0")
    ax.bar_label(bars, labels=[f"{value:.2f}" for value in strength], padding=5, fontsize=10.5)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 3.35)
    ax.set_xlabel("統計強度的絕對值")
    ax.set_title("Wikipedia 注意力：八個放大檢查全未過門檻", color=NAVY, pad=20)
    ax.grid(axis="x", color=GRID, linewidth=0.8, alpha=0.75)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.legend(frameon=False, loc="lower right")
    fig.text(
        0.5,
        0.028,
        "一日與五日各檢查整體波動、下行波動、最大跌幅、向下跳空；最高只有 1.26。",
        ha="center",
        color=SLATE,
        fontsize=9.5,
    )
    fig.text(
        0.5,
        0.008,
        "資料來源：SEC 指控事件與公眾注意力重跑結果；八格調整後數字皆為 1.0。",
        ha="center",
        color=SLATE,
        fontsize=9,
    )
    _finish(fig, "k1678_attention_gate.png")


def render_direct_risk(results: dict) -> None:
    rows = results["primary_results"]
    selected = [
        next(row for row in rows if row["outcome"] == outcome and row["horizon"] == horizon)
        for horizon, outcome in ((1, "left_tail"), (1, "downside_gap"), (5, "left_tail"), (5, "downside_gap"))
    ]
    labels = ["隔日最大跌幅", "隔日向下跳空", "五日最大跌幅", "五日向下跳空"]
    values = [float(row["direct_event_minus_control_mean"]) for row in selected]
    strengths = [float(row["direct_event_minus_control_t_hac"]) for row in selected]
    colors = [AMBER, AMBER, TEAL, TEAL]

    fig, ax = plt.subplots(figsize=(11.5, 6.8), facecolor=BG)
    ax.set_facecolor(BG)
    x = np.arange(len(labels))
    bars = ax.bar(x, values, color=colors, width=0.62)
    ax.bar_label(
        bars,
        labels=[f"+{value:.2f} 個百分點\n強度 {strength:.2f}" for value, strength in zip(values, strengths)],
        padding=5,
        fontsize=10.5,
    )
    ax.set_xticks(x, labels)
    ax.set_ylabel("SEC 指控日期減去配對日期的差距（百分點）")
    ax.set_ylim(0, max(values) * 1.32)
    ax.set_title("事件日期較危險，市場級注意力仍分不出哪場更糟", color=NAVY, pad=20)
    ax.grid(axis="y", color=GRID, linewidth=0.8, alpha=0.75)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(
        0.5,
        0.03,
        "圖中是次要的事件本身比較；它不能證明操縱、Wikipedia 熱度或任何單一機制造成跌幅。",
        ha="center",
        color=SLATE,
        fontsize=9.5,
    )
    fig.text(
        0.5,
        0.008,
        "每場事件配三個同股票對照日；多檔股票落在同一天時先按日期平均。",
        ha="center",
        color=SLATE,
        fontsize=9,
    )
    _finish(fig, "k1678_direct_risk.png")


def main() -> None:
    _setup()
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    render_attention_gate(results)
    render_direct_risk(results)
    print(OUT_DIR / "k1678_attention_gate.png")
    print(OUT_DIR / "k1678_direct_risk.png")


if __name__ == "__main__":
    main()
