import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / "k1373_results.json"


def load_results():
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def plot_pooled_windows(results):
    pooled = results["pooled"]
    labels = ["前 10 天", "除息日", "後 10 天", "控制日"]
    values = [
        pooled["mean_absr_pre"],
        pooled["mean_absr_exdate"],
        pooled["mean_absr_post"],
        pooled["mean_absr_control"],
    ]
    colors = ["#8fb9a8", "#d97b66", "#9cb7d8", "#c9c9c9"]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, values, color=colors, edgecolor="black", linewidth=0.8)
    ax.set_ylabel("平均絕對報酬率 |r|")
    ax.set_title("K1373：除息前後各時段的 pooled 波動")
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            val + 0.00015,
            f"{val:.4%}",
            ha="center",
            va="bottom",
            fontsize=10,
        )

    note = (
        f"Pre vs 控制日 p={pooled['ttest_pre_vs_control']['p_value']:.4f} | "
        f"除息日 vs 控制日 p={pooled['ttest_exdate_vs_control']['p_value']:.4f}"
    )
    ax.text(0.02, 0.97, note, transform=ax.transAxes, va="top", fontsize=9)
    plt.tight_layout()
    fig.savefig(ROOT / "k1373_pooled_windows.png", dpi=160)
    plt.close(fig)


def plot_per_asset_ratios(results):
    per_asset = results["per_asset"]
    tickers = list(per_asset.keys())
    ratios = [
        per_asset[t]["mean_absr_exdate"] / per_asset[t]["mean_absr_control"]
        for t in tickers
    ]
    ds = [per_asset[t]["cohens_d"] for t in tickers]
    colors = ["#d97b66" if d >= 0.5 else "#7da0c9" for d in ds]

    fig, ax = plt.subplots(figsize=(8.5, 5))
    bars = ax.bar(tickers, ratios, color=colors, edgecolor="black", linewidth=0.8)
    ax.axhline(1.0, color="black", linewidth=1.0)
    ax.set_ylabel("除息日 / 控制日 平均 |r| 比值")
    ax.set_title("K1373：五檔資產的除息日波動放大倍數")
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)

    for bar, ratio, d in zip(bars, ratios, ds):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            ratio + 0.015,
            f"{ratio:.2f}x\n d={d:.2f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    ax.text(
        0.02,
        0.97,
        "紅色 = Cohen's d >= 0.5；只有 2882.TW 達中等效果量",
        transform=ax.transAxes,
        va="top",
        fontsize=9,
    )
    plt.tight_layout()
    fig.savefig(ROOT / "k1373_asset_ratios.png", dpi=160)
    plt.close(fig)


def main():
    results = load_results()
    plot_pooled_windows(results)
    plot_per_asset_ratios(results)
    print("saved:", ROOT / "k1373_pooled_windows.png")
    print("saved:", ROOT / "k1373_asset_ratios.png")


if __name__ == "__main__":
    main()
