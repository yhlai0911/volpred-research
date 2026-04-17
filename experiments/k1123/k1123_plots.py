"""K1123 plots: weight trajectory, cumulative returns, risk metrics comparison."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).parent
DATA_DIR = OUT_DIR / "data"


def load_data():
    bt = pd.read_parquet(DATA_DIR / "backtest.parquet")
    with open(OUT_DIR / "k1123_results.json") as f:
        res = json.load(f)
    return bt, res


def plot_weight_trajectory(bt, res):
    """3-panel weight evolution for S1, S4, B2 (representative)."""
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)

    strategies = [("B2", "B2 Rolling Risk-Parity"),
                   ("S1", "S1 NFCI-regime (step)"),
                   ("S4", "S4 Smooth tilt (z-score)")]
    colors = {"SPY": "#1f77b4", "GLD": "#ff7f0e", "TLT": "#2ca02c"}

    for ax, (strat, title) in zip(axes, strategies):
        ax.stackplot(bt.index,
                     bt[f"w_{strat}_SPY"], bt[f"w_{strat}_GLD"], bt[f"w_{strat}_TLT"],
                     labels=["SPY", "GLD", "TLT"],
                     colors=[colors["SPY"], colors["GLD"], colors["TLT"]],
                     alpha=0.8)
        ax.set_ylabel("Weight")
        ax.set_title(title, loc="left")
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", ncol=3, fontsize=9)

    axes[-1].set_xlabel("Date")
    fig.suptitle("K1123 Weight Trajectory (B2 vs S1 vs S4)", fontsize=13, y=1.00)
    fig.tight_layout()
    out_path = OUT_DIR / "weight_trajectory.png"
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    print(f"Saved {out_path}")
    plt.close()


def plot_cumulative_returns(bt, res):
    """Cumulative wealth for all 7 strategies."""
    fig, ax = plt.subplots(figsize=(12, 6))

    strategies = ["B0", "B1", "B2", "S1", "S2", "S3", "S4"]
    labels = {
        "B0": "B0 50/50 SPY/GLD (K1121 moat)",
        "B1": "B1 40/30/30 SPY/GLD/TLT",
        "B2": "B2 Rolling Risk-Parity",
        "S1": "S1 NFCI-regime",
        "S2": "S2 EPU-regime",
        "S3": "S3 Combined (OR)",
        "S4": "S4 Smooth tilt",
    }
    ls_map = {"B0": "-", "B1": "--", "B2": "-.", "S1": "-", "S2": "-", "S3": "-", "S4": "-"}
    lw_map = {"B0": 2.5, "B1": 1.5, "B2": 1.5, "S1": 1.2, "S2": 1.2, "S3": 1.2, "S4": 1.2}

    for s in strategies:
        r = bt[f"r_{s}"].fillna(0)
        eq = (1 + r).cumprod()
        ax.plot(bt.index, eq, label=labels[s], linestyle=ls_map[s], linewidth=lw_map[s])

    ax.set_ylabel("Cumulative wealth (starting 1.0, net of 5 bps TX)")
    ax.set_xlabel("Date")
    ax.set_title("K1123 Cross-asset alt-data allocation (SPY+GLD+TLT): cumulative returns")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    ax.axvline(pd.Timestamp("2023-01-01"), color="red", linestyle=":", alpha=0.5, label="IS/OOS split")

    fig.tight_layout()
    out_path = OUT_DIR / "cumulative_returns_vs_baselines.png"
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    print(f"Saved {out_path}")
    plt.close()


def plot_risk_metrics(bt, res):
    """Bar chart: Sharpe + MDD + Calmar by strategy."""
    strategies = ["B0", "B1", "B2", "S1", "S2", "S3", "S4"]
    colors = ["#2ca02c"] + ["#888888"] * 2 + ["#d62728"] * 4

    m = res["full_sample_metrics"]
    sharpes = [m[s]["sharpe"] for s in strategies]
    mdds = [abs(m[s]["max_drawdown"]) for s in strategies]
    calmars = [m[s]["calmar"] for s in strategies]
    cagrs = [m[s]["cagr"] for s in strategies]

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))

    ax = axes[0, 0]
    ax.bar(strategies, sharpes, color=colors)
    ax.set_ylabel("Sharpe (full, net TX)")
    ax.set_title("Sharpe ratio (full sample)")
    ax.grid(alpha=0.3, axis="y")
    for i, v in enumerate(sharpes):
        ax.text(i, v + 0.02, f"{v:.2f}", ha="center", fontsize=8)
    ax.axhline(1.310, color="black", linestyle="--", alpha=0.3, label="B0 50/50 moat")
    ax.legend(fontsize=8)

    ax = axes[0, 1]
    ax.bar(strategies, mdds, color=colors)
    ax.set_ylabel("|Max drawdown|")
    ax.set_title("Max drawdown (absolute)")
    ax.grid(alpha=0.3, axis="y")
    for i, v in enumerate(mdds):
        ax.text(i, v + 0.003, f"{v:.3f}", ha="center", fontsize=8)

    ax = axes[1, 0]
    ax.bar(strategies, calmars, color=colors)
    ax.set_ylabel("Calmar (CAGR / |MDD|)")
    ax.set_title("Calmar ratio")
    ax.grid(alpha=0.3, axis="y")
    for i, v in enumerate(calmars):
        ax.text(i, v + 0.005, f"{v:.3f}", ha="center", fontsize=8)

    ax = axes[1, 1]
    ax.bar(strategies, [c * 100 for c in cagrs], color=colors)
    ax.set_ylabel("CAGR (%)")
    ax.set_title("CAGR annualized (net of 5 bps TX)")
    ax.grid(alpha=0.3, axis="y")
    for i, v in enumerate(cagrs):
        ax.text(i, v * 100 + 0.2, f"{v*100:.1f}%", ha="center", fontsize=8)

    fig.suptitle("K1123 Risk-return comparison: B0 50/50 dominates", fontsize=13)
    fig.tight_layout()
    out_path = OUT_DIR / "risk_metrics_comparison.png"
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    print(f"Saved {out_path}")
    plt.close()


def plot_regime_sharpe(res):
    """Regime-conditional Sharpe: stress vs calm."""
    regime = res["regime_conditional"]
    strategies = ["B0", "B1", "B2", "S1", "S2", "S3", "S4"]
    stress_sr = [regime[s]["stress_sharpe"] for s in strategies]
    calm_sr = [regime[s]["calm_sharpe"] for s in strategies]

    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(strategies))
    w = 0.35
    ax.bar(x - w/2, stress_sr, w, label=f"Stress days (N={regime['_stress_days_count']})", color="#d62728")
    ax.bar(x + w/2, calm_sr, w, label=f"Calm days (N={regime['_calm_days_count']})", color="#2ca02c")
    ax.set_xticks(x)
    ax.set_xticklabels(strategies)
    ax.set_ylabel("Sharpe ratio (conditional)")
    ax.set_title("K1123 Regime-conditional Sharpe: stress vs calm days")
    ax.grid(alpha=0.3, axis="y")
    ax.legend()
    for i, (sr, sc) in enumerate(zip(stress_sr, calm_sr)):
        ax.text(i - w/2, sr + 0.02, f"{sr:.2f}", ha="center", fontsize=8)
        ax.text(i + w/2, sc + 0.02, f"{sc:.2f}", ha="center", fontsize=8)

    fig.tight_layout()
    out_path = OUT_DIR / "regime_conditional_sharpe.png"
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    print(f"Saved {out_path}")
    plt.close()


if __name__ == "__main__":
    bt, res = load_data()
    plot_weight_trajectory(bt, res)
    plot_cumulative_returns(bt, res)
    plot_risk_metrics(bt, res)
    plot_regime_sharpe(res)
    print("All plots saved to", OUT_DIR)
