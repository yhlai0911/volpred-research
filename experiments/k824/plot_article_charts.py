import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / "k824_quantile_forecasting_results.json"


def load_results():
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def plot_var_violations(results):
    backtest = results["var_1pct_backtest"]
    models = ["M1_Normal", "M2_StudentT", "M3_QuantReg", "M4_HistSim"]
    labels = ["Normal", "Student-t", "QuantReg", "HistSim"]
    violations = [backtest[m]["n_violations"] for m in models]
    colors = []
    for m in models:
        light = backtest[m]["basel_traffic_light"]
        if light == "green":
            colors.append("#78a55a")
        elif light == "yellow":
            colors.append("#d9b44a")
        else:
            colors.append("#c85c5c")

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, violations, color=colors, edgecolor="black", linewidth=0.8)
    ax.axhline(5.02, color="black", linestyle="--", linewidth=1.2, label="1% 理論期望 ≈ 5.02 次")
    ax.axhline(9, color="#d9b44a", linestyle=":", linewidth=1.2, label="Basel 黃燈上限 = 9 次")
    ax.set_title("K824：1% VaR 回測違反次數")
    ax.set_ylabel("違反次數（502 個交易日）")
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend(fontsize=9)

    for bar, m in zip(bars, models):
        n = backtest[m]["n_violations"]
        rate = backtest[m]["violation_rate"] * 100
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            n + 0.25,
            f"{n} 次\n{rate:.2f}%",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    plt.tight_layout()
    fig.savefig(ROOT / "k824_var_violations.png", dpi=160)
    plt.close(fig)


def plot_pinball_tie(results):
    avg = results["avg_pinball_loss"]
    models = ["M1_Normal", "M2_StudentT", "M3_QuantReg", "M4_HistSim"]
    labels = ["Normal", "Student-t", "QuantReg", "HistSim"]
    values = [avg[m] for m in models]
    colors = ["#b8c6d9", "#95a8d0", "#8fb9a8", "#d97b66"]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, values, color=colors, edgecolor="black", linewidth=0.8)
    ax.set_title("K824：平均 Pinball Loss 幾乎打平")
    ax.set_ylabel("平均 Pinball Loss")
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)

    ymin = min(values) - 0.000002
    ymax = max(values) + 0.000002
    ax.set_ylim(ymin, ymax)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            val + 0.0000002,
            f"{val:.6f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    spread = max(values) - min(values)
    ax.text(
        0.02,
        0.96,
        f"四者最大差距只有 {spread:.8f}",
        transform=ax.transAxes,
        va="top",
        fontsize=9,
    )

    plt.tight_layout()
    fig.savefig(ROOT / "k824_pinball_tie.png", dpi=160)
    plt.close(fig)


def main():
    results = load_results()
    plot_var_violations(results)
    plot_pinball_tie(results)
    print("saved:", ROOT / "k824_var_violations.png")
    print("saved:", ROOT / "k824_pinball_tie.png")


if __name__ == "__main__":
    main()
