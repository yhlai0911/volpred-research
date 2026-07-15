from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent


def load_results() -> dict:
    path = ROOT / "experiments/k1365/K1365_results.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "PingFang TC",
                "Heiti TC",
                "Arial Unicode MS",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#CBD5E1",
            "axes.labelcolor": "#334155",
            "xtick.color": "#475569",
            "ytick.color": "#475569",
        }
    )


def chart_leader_share(results: dict) -> None:
    group_keys = ["sp500", "nasdaq100", "russell2000", "em"]
    labels = ["SPY\n標普 500", "QQQ\nNasdaq-100", "IWM\nRussell 2000", "EEM\n新興市場"]
    values = [results["groups"][key]["mean_leader_volume_share"] * 100 for key in group_keys]
    colors = ["#2563EB", "#D97706", "#16A34A", "#DC2626"]

    fig, ax = plt.subplots(figsize=(10, 5.8))
    bars = ax.bar(labels, values, color=colors, width=0.68)
    ax.set_ylim(0, 105)
    ax.set_ylabel("老牌 ETF 佔同組成交量（%）")
    ax.set_title("同一個指數有多張入場券，交易仍集中在老牌 ETF")
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 1.2,
            f"{value:.1f}%",
            ha="center",
            va="bottom",
            fontsize=11,
            color="#0F172A",
        )
    fig.text(
        0.01,
        0.01,
        "資料來源：yfinance 調整後日線成交量；各組採所有 ETF 都有資料的共同期間。",
        fontsize=9,
        color="#64748B",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(OUT / "k1365_leader_share_corrected.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def _t_value(results: dict, group: str, target: str) -> float:
    rows = [
        row
        for row in results["regressions"]
        if row["group"] == group
        and row["signal"] == "leader_share_z_l1"
        and row["target"] == target
    ]
    if len(rows) != 1:
        raise ValueError(f"expected one row for {group}/{target}, found {len(rows)}")
    return float(rows[0]["hac_t"])


def chart_predictive_strength(results: dict) -> None:
    group_keys = ["sp500", "nasdaq100", "russell2000", "em"]
    labels = ["標普 500", "Nasdaq-100", "Russell 2000", "新興市場"]
    next_range = [_t_value(results, key, "next_range_vol") for key in group_keys]
    forward_five = [_t_value(results, key, "forward5_rv") for key in group_keys]

    x = np.arange(len(group_keys))
    width = 0.34
    fig, ax = plt.subplots(figsize=(10, 5.8))
    bars_a = ax.bar(x - width / 2, next_range, width, color="#2563EB", label="隔日盤中震盪")
    bars_b = ax.bar(x + width / 2, forward_five, width, color="#D97706", label="未來五日波動")
    ax.axhline(3, color="#B91C1C", linestyle="--", linewidth=1.4, label="正向嚴格門檻 +3")
    ax.axhline(-3, color="#475569", linestyle="--", linewidth=1.2, label="反向門檻 -3")
    ax.axhline(0, color="#64748B", linewidth=1.0)
    ax.set_xticks(x, labels)
    ax.set_ylabel("預測關係的統計強度")
    ax.set_title("交易越集中，後續波動沒有穩定上升")
    ax.set_ylim(-4.1, 4.1)
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper left", ncol=2)
    for bars in (bars_a, bars_b):
        for bar in bars:
            value = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + (0.12 if value >= 0 else -0.18),
                f"{value:+.2f}",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=10,
                color="#0F172A",
            )
    fig.text(
        0.01,
        0.01,
        "訊號只用前一日資料；未來五日控制項已改為前一個完整五日區塊。",
        fontsize=9,
        color="#64748B",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(OUT / "k1365_predictive_strength_corrected.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    configure_style()
    results = load_results()
    chart_leader_share(results)
    chart_predictive_strength(results)


if __name__ == "__main__":
    main()
