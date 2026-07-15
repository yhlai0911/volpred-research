from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["PingFang TC", "Heiti TC", "Arial Unicode MS", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#CBD5E1",
            "axes.labelcolor": "#334155",
            "xtick.color": "#475569",
            "ytick.color": "#475569",
        }
    )


def chart_initial_oos(results: dict) -> None:
    targets = ["BKLN", "HYG", "KRE", "IWM"]
    own_har = [
        results["rolling_oos"][target]["pairwise"]["har_vs_har_pc"]["qlike_improvement_pct"]
        for target in targets
    ]
    market = [
        results["rolling_oos"][target]["pairwise"]["har_market_vs_har_market_pc"][
            "qlike_improvement_pct"
        ]
        for target in targets
    ]

    x = np.arange(len(targets))
    width = 0.34
    fig, ax = plt.subplots(figsize=(10, 5.8))
    bars_a = ax.bar(x - width / 2, own_har, width, color="#0F766E", label="只和自身歷史比較")
    bars_b = ax.bar(x + width / 2, market, width, color="#2563EB", label="再控制 SPY / VIX")
    ax.axhline(0, color="#64748B", linewidth=1.1)
    ax.set_xticks(x, targets)
    ax.set_ylabel("加入公開私募信貸代理後的預測誤差改善（%）")
    ax.set_title("第一輪結果：改善集中在貸款與高收益債")
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper right")
    for bars in (bars_a, bars_b):
        for bar in bars:
            value = bar.get_height()
            offset = 0.25 if value >= 0 else -0.55
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + offset,
                f"{value:.2f}%",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=10,
                color="#0F172A",
            )
    fig.text(
        0.01,
        0.01,
        "資料來源：experiment K1332 results；正值代表預測誤差下降，負值代表惡化。",
        fontsize=9,
        color="#64748B",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(OUT / "k1332_initial_oos_improvement.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def chart_robustness(results: dict) -> None:
    horizons = results["method"]["horizons_days"]
    h_nodes = [results["hac_regressions"]["HYG"][f"h{h}"] for h in horizons]
    bdc_t = [node["modelB_bdc_plus_spy"]["bdc_rv_z"]["t"] for node in h_nodes]
    nav_t = [node["modelC_navproxy_plus_spy"]["nav_discount_z"]["t"] for node in h_nodes]

    x = np.arange(len(horizons))
    width = 0.34
    fig, ax = plt.subplots(figsize=(10, 5.8))
    bars_a = ax.bar(x - width / 2, bdc_t, width, color="#94A3B8", label="BDC 整體波動")
    bars_b = ax.bar(x + width / 2, nav_t, width, color="#D97706", label="BIZD 相對 HYG 折價代理")
    ax.axhline(3, color="#B91C1C", linestyle="--", linewidth=1.5, label="嚴格門檻 3")
    ax.axhline(0, color="#64748B", linewidth=1.0)
    ax.set_xticks(x, [f"未來 {h} 日" for h in horizons])
    ax.set_ylabel("控制大盤與自身波動後的統計強度")
    ax.set_title("延伸查核：HYG 只剩最短期的相對折價訊號過關")
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper right")
    for bars in (bars_a, bars_b):
        for bar in bars:
            value = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + (0.10 if value >= 0 else -0.22),
                f"{value:.2f}",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=10,
                color="#0F172A",
            )
    fig.text(
        0.01,
        0.01,
        "資料來源：experiment K1499 results；所有訊號先落後一日，門檻採絕對值大於 3。",
        fontsize=9,
        color="#64748B",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(OUT / "k1499_hyg_spy_control.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    configure_style()
    k1332 = load_json(ROOT / "experiments/k1332/k1332_results.json")
    k1499 = load_json(ROOT / "experiments/k1499/k1499_results.json")
    chart_initial_oos(k1332)
    chart_robustness(k1499)


if __name__ == "__main__":
    main()
