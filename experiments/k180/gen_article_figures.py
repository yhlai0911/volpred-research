from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "k180_directional_change_results.json"


def load_results() -> dict:
    return json.loads(RESULTS.read_text())


def save_best_improvement_chart(data: dict) -> Path:
    assets = ["SPY", "QQQ", "GLD", "TLT", "BTC"]
    best_improvement = []
    best_dm_t = []
    for asset in assets:
        rows = data["results_by_asset"][asset]["garchx_by_theta"]
        best = max(rows.items(), key=lambda kv: kv[1]["qlike_pct_change"])
        best_improvement.append(best[1]["qlike_pct_change"])
        best_dm_t.append(best[1]["dm_t"])

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    x = np.arange(len(assets))

    axes[0].bar(x, best_improvement, color=["#355C7D", "#355C7D", "#355C7D", "#355C7D", "#C06C84"])
    axes[0].set_xticks(x, assets)
    axes[0].set_ylabel("Best QLIKE improvement (%)")
    axes[0].set_title("Best-case gain from DC features is still tiny")
    axes[0].axhline(0, color="black", linewidth=0.8)
    for i, value in enumerate(best_improvement):
        axes[0].text(i, value + 0.05, f"{value:.2f}%", ha="center", fontsize=9)

    axes[1].bar(x, best_dm_t, color=["#6C5B7B"] * 5)
    axes[1].set_xticks(x, assets)
    axes[1].set_ylabel("Best DM t-stat")
    axes[1].set_title("None of the best cases are statistically convincing")
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].axhline(3.0, color="#D95F02", linestyle="--", linewidth=1.2, label="Harvey 3.0")
    axes[1].axhline(-3.0, color="#D95F02", linestyle="--", linewidth=1.2)
    axes[1].legend(frameon=False, fontsize=9, loc="lower left")
    for i, value in enumerate(best_dm_t):
        axes[1].text(i, value - 0.18, f"{value:.2f}", ha="center", fontsize=9)

    fig.suptitle("K180: DC features do not break the forecasting ceiling", fontsize=13, y=1.02)
    fig.tight_layout()
    out = ROOT / "k180_article_best_improvement.png"
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return out


def save_event_stats_chart(data: dict) -> Path:
    assets = ["SPY", "QQQ", "GLD", "TLT", "BTC"]
    events = [data["dc_descriptive_stats"][asset]["events_yr_0.5%"] for asset in assets]
    duration = [data["dc_descriptive_stats"][asset]["mean_dur_0.5%"] for asset in assets]
    overshoot = [data["dc_descriptive_stats"][asset]["mean_os_ratio_0.5%"] for asset in assets]

    fig, ax1 = plt.subplots(figsize=(9.5, 5))
    x = np.arange(len(assets))
    width = 0.36

    ax1.bar(x - width / 2, events, width=width, color="#2A9D8F", label="Events per year (0.5%)")
    ax1.set_ylabel("Events per year")
    ax1.set_xticks(x, assets)
    ax1.set_title("DC events are frequent, especially in BTC")

    ax2 = ax1.twinx()
    ax2.bar(x + width / 2, duration, width=width, color="#E9C46A", label="Mean duration (days)")
    ax2.plot(x, overshoot, color="#D1495B", marker="o", linewidth=1.8, label="Mean overshoot ratio")
    ax2.set_ylabel("Duration / overshoot")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, frameon=False, ncol=3, loc="upper left", fontsize=9)

    for i, value in enumerate(events):
        ax1.text(i - width / 2, value + 2.2, f"{value:.0f}", ha="center", fontsize=8)
    for i, value in enumerate(duration):
        ax2.text(i + width / 2, value + 0.35, f"{value:.1f}", ha="center", fontsize=8)

    fig.tight_layout()
    out = ROOT / "k180_article_event_stats.png"
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    data = load_results()
    outputs = [
        save_best_improvement_chart(data),
        save_event_stats_chart(data),
    ]
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
