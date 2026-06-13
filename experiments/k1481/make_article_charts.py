#!/usr/bin/env python3
"""Generate reader-facing charts for K1481 general article."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS_PATH = HERE / "k1481_results.json"
PRICE_0050 = ROOT / "storage" / "macro" / "yf_0050.TW.csv"
PRICE_TWDX = ROOT / "storage" / "macro" / "yf_TWDX.csv"

FIG_MARKET = HERE / "k1481_market_coverage.png"
FIG_GATE = HERE / "k1481_research_gate.png"


def load_yf_cache(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, skiprows=2)
    df.columns = ["date", "close", "high", "low", "open", "volume"]
    df["date"] = pd.to_datetime(df["date"], utc=False)
    df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["close"]).copy()


def plot_market_coverage(results: dict) -> None:
    tw50 = load_yf_cache(PRICE_0050)[["date", "close"]].copy()
    twdx = load_yf_cache(PRICE_TWDX)[["date", "close"]].copy()
    tw50["normalized"] = tw50["close"] / tw50["close"].iloc[0] * 100
    twdx["normalized"] = twdx["close"] / twdx["close"].iloc[0] * 100

    plt.style.use("default")
    fig, ax = plt.subplots(figsize=(10, 5.8))
    ax.plot(tw50["date"], tw50["normalized"], label="0050.TW", color="#0b6e4f", linewidth=2.2)
    ax.plot(twdx["date"], twdx["normalized"], label="USD/TWD", color="#c05621", linewidth=2.0)
    ax.set_title("K1481: repo 內已具備的台灣市場資料", fontsize=16, weight="bold")
    ax.set_ylabel("起點 = 100")
    ax.grid(alpha=0.18)
    ax.legend(frameon=False, loc="upper left")

    for event_name, event_date in {
        "裴洛西訪台": "2022-08-02",
        "2024 總統大選": "2024-01-13",
    }.items():
        ax.axvline(pd.Timestamp(event_date), color="#6b7280", linestyle="--", linewidth=1)
        ax.text(
            pd.Timestamp(event_date),
            ax.get_ylim()[1] * 0.97,
            event_name,
            rotation=90,
            va="top",
            ha="right",
            fontsize=9,
            color="#4b5563",
        )

    note = (
        f"0050.TW: {results['available_local_inputs']['price_series'][0]['start']} to "
        f"{results['available_local_inputs']['price_series'][0]['end']} | "
        f"USD/TWD: {results['available_local_inputs']['price_series'][1]['start']} to "
        f"{results['available_local_inputs']['price_series'][1]['end']}"
    )
    fig.text(0.5, 0.02, note, ha="center", fontsize=9, color="#374151")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(FIG_MARKET, dpi=180)
    plt.close(fig)


def plot_gate_status(results: dict) -> None:
    items = [
        ("0050.TW 價格歷史", 1),
        ("USD/TWD 價格歷史", 1),
        ("事件窗樣本覆蓋", 1),
        ("台灣 country-GPR 序列", 0),
        ("publication_date", 0),
    ]
    labels = [item[0] for item in items]
    values = [item[1] for item in items]
    colors = ["#0b6e4f" if value else "#b91c1c" for value in values]
    texts = ["已具備" if value else "缺資料" for value in values]

    fig, ax = plt.subplots(figsize=(8.8, 5.4))
    y_pos = list(range(len(labels)))
    ax.barh(y_pos, [1] * len(labels), color=colors, alpha=0.92)
    ax.set_yticks(y_pos, labels)
    ax.set_xlim(0, 1.18)
    ax.set_xticks([])
    ax.set_title("能不能誠實回答『台海風險可測價』？", fontsize=16, weight="bold")
    ax.invert_yaxis()
    for y, label in enumerate(texts):
        ax.text(1.03, y, label, va="center", fontsize=11, color="#111827", weight="bold")

    ax.spines[["top", "right", "bottom", "left"]].set_visible(False)
    ax.grid(False)

    verdict = results["verdict"]["overall"]
    fig.text(
        0.5,
        0.04,
        f"Verdict: {verdict} | 缺的是核心自變數與發布時點，不是圖表包裝。",
        ha="center",
        fontsize=10,
        color="#374151",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(FIG_GATE, dpi=180)
    plt.close(fig)


def main() -> None:
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    plot_market_coverage(results)
    plot_gate_status(results)
    print(FIG_MARKET)
    print(FIG_GATE)


if __name__ == "__main__":
    main()
