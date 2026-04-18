"""Plots for K1117."""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = Path(__file__).parent


def load_results():
    with open(OUT / "k1117_results.json") as f:
        return json.load(f)


def load_pairs():
    return pd.read_csv(OUT / "k1117_matched_pair_losses.csv")


def plot_matched_pair_forecast_comparison():
    r = load_results()
    tests = r["tests"]
    alt_vars = list(tests.keys())
    h1_t = [tests[a]["H1_DM_t"] for a in alt_vars]
    h2_t = [tests[a]["H2_DM_t"] for a in alt_vars]

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(alt_vars))
    w = 0.35
    ax.bar(x - w / 2, h1_t, w, label="H1: Jump-day edge", color="tab:red", alpha=0.8)
    ax.bar(x + w / 2, h2_t, w, label="H2: Non-jump control edge", color="tab:blue", alpha=0.8)
    ax.axhline(2.0, ls="--", color="gray", lw=1, label="|t|=2 nominal threshold")
    ax.axhline(-2.0, ls="--", color="gray", lw=1)
    ax.axhline(3.0, ls=":", color="k", lw=1, label="|t|=3 Harvey threshold")
    ax.axhline(-3.0, ls=":", color="k", lw=1)
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(alt_vars, rotation=0)
    ax.set_ylabel("Paired DM t-stat (positive = alt beats baseline)")
    ax.set_title(f"K1117: Matched-pair DM tests on VIX jumps\n"
                 f"n_pairs={r['match_quality']['n_matched']} | "
                 f"Verdict: {r['verdict']}")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT / "matched_pair_forecast_comparison.png", dpi=120)
    plt.close()
    print("Saved matched_pair_forecast_comparison.png")


def plot_vix_jump_regime():
    import yfinance as yf
    df = pd.read_parquet(OUT / "data" / "market_daily.parquet")
    # annotate 2σ jumps
    dvix = df["vix"].diff()
    sigma = dvix.shift(1).rolling(252, min_periods=252).std()
    is_jump = (dvix.abs() / sigma) > 2.0

    r = load_results()
    n_jumps = r["jump_counts"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                    gridspec_kw={"height_ratios": [2, 1]})
    ax1.plot(df.index, df["vix"], color="tab:blue", lw=0.6, label="VIX")
    ax1.scatter(df.index[is_jump], df.loc[is_jump, "vix"],
                color="tab:red", s=10, alpha=0.7,
                label=f"|ΔVIX|>2σ jump (N={n_jumps.get('primary_2sigma', 0)})")
    ax1.set_ylabel("VIX")
    ax1.set_title("K1117: VIX Jump Events and Regime Matching")
    ax1.legend(loc="upper right")
    ax1.grid(alpha=0.3)

    ax2.plot(df.index, dvix, color="tab:gray", lw=0.4)
    ax2.fill_between(df.index, dvix, 0, where=(dvix > 0), color="tab:red", alpha=0.3)
    ax2.fill_between(df.index, dvix, 0, where=(dvix < 0), color="tab:green", alpha=0.3)
    ax2.set_ylabel("ΔVIX")
    ax2.axhline(0, color="k", lw=0.5)
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT / "vix_jump_regime_plot.png", dpi=120)
    plt.close()
    print("Saved vix_jump_regime_plot.png")


def plot_delta_qlike_distribution():
    r = load_results()
    pdf = load_pairs()
    alt_vars = r["alt_vars_tested"]

    fig, axes = plt.subplots(2, 3, figsize=(14, 7))
    for i, a in enumerate(alt_vars):
        ax = axes.flat[i]
        delta_j = pdf[f"loss_{a}_jump"] - pdf["loss_base_jump"]
        delta_c = pdf[f"loss_{a}_control"] - pdf["loss_base_control"]
        ax.hist(delta_j, bins=30, alpha=0.5, label=f"Jump (mean={delta_j.mean():.3f})",
                color="tab:red")
        ax.hist(delta_c, bins=30, alpha=0.5, label=f"Control (mean={delta_c.mean():.3f})",
                color="tab:blue")
        ax.axvline(0, color="k", lw=0.5)
        ax.set_title(f"{a}: ΔQLIKE (alt − base)")
        ax.set_xlabel("Loss diff")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT / "delta_qlike_distribution.png", dpi=120)
    plt.close()
    print("Saved delta_qlike_distribution.png")


if __name__ == "__main__":
    plot_matched_pair_forecast_comparison()
    plot_vix_jump_regime()
    try:
        plot_delta_qlike_distribution()
    except Exception as e:
        print(f"Skipped delta plot: {e}")
