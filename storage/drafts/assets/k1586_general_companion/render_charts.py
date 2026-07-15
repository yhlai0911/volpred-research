#!/usr/bin/env python3
"""Render reader-facing K1586 charts from the certified results package."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[4]
RESULTS_PATH = ROOT / "experiments" / "K1586" / "K1586_results.json"
OUT_DIR = Path(__file__).resolve().parent

NAVY = "#172554"
BLUE = "#2563EB"
TEAL = "#0F766E"
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
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
        }
    )


def _finish(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUT_DIR / name, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def render_event_window(results: dict) -> None:
    h2 = results["hypotheses"]["H2_USDC_SVB_event"]
    labels = ["SHY\n1 至 3 年", "BIL\n1 至 3 個月"]
    control = [h2["SHY"]["control_mean_abs_bps"], h2["BIL"]["control_mean_abs_bps"]]
    event = [h2["SHY"]["event_mean_abs_bps"], h2["BIL"]["event_mean_abs_bps"]]
    ratios = [h2["SHY"]["ratio"], h2["BIL"]["ratio"]]
    passed = [
        h2["SHY"]["p_value_bonf_n2"] < 0.05
        and h2["SHY"]["block_bootstrap"]["p_bonf_n2"] < 0.05,
        h2["BIL"]["p_value_bonf_n2"] < 0.05
        and h2["BIL"]["block_bootstrap"]["p_bonf_n2"] < 0.05,
    ]

    fig, ax = plt.subplots(figsize=(11.5, 6.8), facecolor=BG)
    ax.set_facecolor(BG)
    x = np.arange(len(labels))
    width = 0.32
    normal_bars = ax.bar(x - width / 2, control, width, color=SLATE, label="對照期 50 個交易日")
    event_bars = ax.bar(x + width / 2, event, width, color=[RED, TEAL], label="事件窗 11 個交易日")
    ax.bar_label(normal_bars, labels=[f"{v:.2f}" for v in control], padding=4, fontsize=11)
    ax.bar_label(event_bars, labels=[f"{v:.2f}" for v in event], padding=4, fontsize=12, fontweight="bold")

    for idx, (ratio, is_pass) in enumerate(zip(ratios, passed)):
        verdict = "通過雙重檢查" if is_pass else "差異未過門檻"
        ax.text(
            idx,
            max(control[idx], event[idx]) + 4.5,
            f"{ratio:.2f} 倍｜{verdict}",
            ha="center",
            color=NAVY,
            fontsize=11,
            fontweight="bold",
        )

    ax.set_title("USDC 脫鉤事件窗：兩種短債的反應差很多", color=NAVY, pad=20)
    ax.set_xticks(x, labels)
    ax.set_ylabel("每日絕對價格變動幅度（基點）")
    ax.set_ylim(0, 48)
    ax.grid(axis="y", color=GRID, linewidth=0.8, alpha=0.7)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper right")
    fig.text(
        0.5,
        0.035,
        "事件窗為 2023-03-10 前後各 5 個交易日，共 11 天；量的是每日絕對變動幅度，不是月度波動率。",
        ha="center",
        color=SLATE,
        fontsize=9.5,
    )
    fig.text(
        0.5,
        0.012,
        "資料來源：DefiLlama、FRED、yfinance；穩定幣與短債事件窗重跑結果。",
        ha="center",
        color=SLATE,
        fontsize=9,
    )
    _finish(fig, "k1586_event_window.png")


def render_daily_null(results: dict) -> None:
    h1 = results["hypotheses"]["H1_lead_lag"]
    lags = np.arange(1, 6)
    p_1mo = [h1["DGS1MO_RV"]["granger"][f"lag_{lag}"]["p_value"] for lag in lags]
    p_3mo = [h1["DGS3MO_RV"]["granger"][f"lag_{lag}"]["p_value"] for lag in lags]

    fig, ax = plt.subplots(figsize=(11.5, 6.8), facecolor=BG)
    ax.set_facecolor(BG)
    ax.plot(lags, p_1mo, marker="o", linewidth=2.5, color=BLUE, label="1 個月期公債利率")
    ax.plot(lags, p_3mo, marker="o", linewidth=2.5, color=TEAL, label="3 個月期公債利率")
    ax.axhspan(0, 0.05, color=RED, alpha=0.10)
    ax.axhline(0.05, color=RED, linestyle="--", linewidth=1.4, label="通過門檻 0.05")

    minimum = min(p_1mo + p_3mo)
    ax.text(
        5.0,
        minimum + 0.055,
        f"最低也有 {minimum:.3f}",
        ha="right",
        color=NAVY,
        fontsize=12,
        fontweight="bold",
    )
    ax.set_title("平常日：穩定幣市值變化沒有提前報警", color=NAVY, pad=20)
    ax.set_xlabel("穩定幣市值變化領先幾個交易日")
    ax.set_ylabel("顯著性檢查數值（越低越有訊號）")
    ax.set_xticks(lags)
    ax.set_ylim(0, 1.0)
    ax.grid(color=GRID, linewidth=0.8, alpha=0.7)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    fig.text(
        0.5,
        0.03,
        "共檢查 5 個領先天數 × 2 種短端利率；控制利率波動自身慣性後，10 組全部未過 0.05。",
        ha="center",
        color=SLATE,
        fontsize=9.5,
    )
    fig.text(
        0.5,
        0.008,
        "樣本：2020-04-06 至 2026-06-26，共 1,557 個營業日。資料來源：DefiLlama、FRED。",
        ha="center",
        color=SLATE,
        fontsize=9,
    )
    _finish(fig, "k1586_daily_null.png")


def main() -> None:
    _setup()
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    render_event_window(results)
    render_daily_null(results)
    print(OUT_DIR / "k1586_event_window.png")
    print(OUT_DIR / "k1586_daily_null.png")


if __name__ == "__main__":
    main()
