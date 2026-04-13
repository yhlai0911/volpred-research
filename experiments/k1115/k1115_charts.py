"""K1115 chart generation.

Produces 4 charts:
1. k1115_breach_cluster_acf.png   — breach autocorrelation for M1/M3 (IS vs OOS)
2. k1115_5model_trinity.png       — Trinity pass/fail heatmap
3. k1115_oos_quantile_loss.png    — cumulative quantile loss OOS (5 models)
4. k1115_inter_breach_duration.png — inter-breach duration distribution + Hawkes fit
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

OUT_DIR = Path(__file__).parent


def load_results() -> dict:
    with open(OUT_DIR / "k1115_results.json") as f:
        return json.load(f)


def load_breach_history() -> pd.DataFrame:
    return pd.read_csv(OUT_DIR / "breach_history.csv", index_col=0, parse_dates=True)


# ---------------------------------------------------------------------------
# 1) Breach ACF chart
# ---------------------------------------------------------------------------
def plot_breach_acf(results: dict, breach_df: pd.DataFrame):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    lags = 20

    for ax, period in zip(axes, ["IS", "OOS"]):
        if period == "IS":
            mask = (breach_df.index >= "2010-01-01") & (breach_df.index <= "2017-12-31")
        else:
            mask = (breach_df.index >= "2018-01-01") & (breach_df.index <= "2026-04-13")
        for m, color in [("breach_M3", "steelblue")]:
            b = breach_df.loc[mask, m].dropna().values.astype(float)
            if len(b) < 50:
                continue
            # Compute ACF
            b_c = b - b.mean()
            denom = (b_c ** 2).sum()
            acf_vals = []
            for k in range(1, lags + 1):
                acf_vals.append((b_c[k:] * b_c[:-k]).sum() / denom if denom > 0 else 0)
            ax.bar(range(1, lags + 1), acf_vals, alpha=0.7, color=color, label="M3 (GJR-t) breaches")
        # 95% CI: +- 1.96/sqrt(N)
        ci = 1.96 / np.sqrt(mask.sum())
        ax.axhline(ci, color="red", linestyle="--", linewidth=0.8, alpha=0.7, label="95% CI")
        ax.axhline(-ci, color="red", linestyle="--", linewidth=0.8, alpha=0.7)
        ax.axhline(0, color="black", linewidth=0.5)
        ax.set_title(f"{period}: Breach Indicator ACF (M3 GJR-t, α=1%)")
        ax.set_xlabel("Lag (days)")
        ax.set_ylabel("Autocorrelation")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(alpha=0.3)
        # Annotate Ljung-Box p-value
        lb_p = results["per_alpha"]["alpha_01"][period]["M3"]["ljung_box_p"]
        ax.text(0.02, 0.95, f"Ljung-Box(10) p = {lb_p:.3f}",
                transform=ax.transAxes, fontsize=9, verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

    plt.suptitle("K1115: SPY VaR Breach Clustering (M3 GJR-t baseline) — IS vs OOS",
                 fontsize=12, y=1.02)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "k1115_breach_cluster_acf.png", dpi=120, bbox_inches="tight")
    plt.close()
    print("Saved k1115_breach_cluster_acf.png")


# ---------------------------------------------------------------------------
# 2) Trinity heatmap
# ---------------------------------------------------------------------------
def plot_trinity_heatmap(results: dict):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    models = ["M1", "M2", "M3", "M4", "M5"]
    model_names = ["M1 Empirical", "M2 GARCH-N", "M3 GJR-t", "M4 GJR-t+Breach", "M5 GJR-t+Hawkes"]
    tests = ["Kupiec", "Christoffersen\nIndep", "Christoffersen\nCC", "Ljung-Box", "AS Z2 (ES)"]
    # Columns: IS alpha=1%, IS alpha=5%, OOS alpha=1%, OOS alpha=5%

    for idx, alpha_name in enumerate(["alpha_01", "alpha_05"]):
        ax = axes[idx]
        # Rows: models * 2 periods. Cols: tests
        data = np.full((len(models), len(tests) * 2), np.nan)
        for i, m in enumerate(models):
            for p_idx, period in enumerate(["IS", "OOS"]):
                r = results["per_alpha"][alpha_name][period][m]
                vals = [
                    r["kupiec_p"], r["indep_p"], r["cc_p"],
                    r["ljung_box_p"], r["as_z2_p"],
                ]
                for j, v in enumerate(vals):
                    data[i, p_idx * len(tests) + j] = v if v is not None else np.nan

        # Pass/fail: green if p>0.10 (or >0.05 depending), red if p<=0.05, yellow in between
        # Use binary cmap + annotations
        pass_matrix = np.where(data > 0.10, 1, np.where(data > 0.05, 0.5, 0))
        im = ax.imshow(pass_matrix, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")

        col_labels = [f"IS\n{t}" for t in tests] + [f"OOS\n{t}" for t in tests]
        ax.set_xticks(range(len(col_labels)))
        ax.set_xticklabels(col_labels, fontsize=7, rotation=0)
        ax.set_yticks(range(len(models)))
        ax.set_yticklabels(model_names, fontsize=9)
        ax.set_title(f"Trinity + ES Backtest (α = {'1%' if alpha_name == 'alpha_01' else '5%'})", fontsize=11)

        for i in range(len(models)):
            for j in range(len(col_labels)):
                v = data[i, j]
                text = "—" if np.isnan(v) else f"{v:.3f}"
                ax.text(j, i, text, ha="center", va="center", fontsize=7, color="black")

        # Add vertical separator between IS and OOS
        ax.axvline(len(tests) - 0.5, color="black", linewidth=1.5)

    plt.suptitle("K1115: 5-Model Trinity + ES Backtests — p-values (green>0.10, yellow>0.05, red<0.05)",
                 fontsize=12, y=1.02)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "k1115_5model_trinity.png", dpi=120, bbox_inches="tight")
    plt.close()
    print("Saved k1115_5model_trinity.png")


# ---------------------------------------------------------------------------
# 3) Cumulative OOS quantile loss
# ---------------------------------------------------------------------------
def plot_cumulative_quantile_loss(results: dict, breach_df: pd.DataFrame):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    # We need to recompute per-obs quantile loss OOS for each model
    # M3_var, M4_var, M5_var are in breach_history.csv (alpha=0.01 case)
    # For alpha=0.05 we don't have var stored; skip
    # Plot alpha=0.01 detailed; alpha=0.05 from aggregate means
    for idx, alpha in enumerate([0.01, 0.05]):
        ax = axes[idx]
        key = f"alpha_{int(alpha*100):02d}"
        # For alpha=0.01 we plot cumulative QL from breach_df
        if alpha == 0.01:
            oos = breach_df.loc["2018-01-01":"2026-04-13"]
            r = oos["ret"].values
            for model_col, label, color in [
                ("M3_var", "M3 GJR-t", "steelblue"),
                ("M4_var", "M4 +Breach", "orange"),
                ("M5_var", "M5 +Hawkes", "green"),
            ]:
                v = oos[model_col].values
                mask = ~(np.isnan(r) | np.isnan(v))
                ind = (r[mask] < v[mask]).astype(float)
                ql = (alpha - ind) * (r[mask] - v[mask])
                cum_ql = np.cumsum(ql)
                dates = oos.index[mask]
                ax.plot(dates, cum_ql, label=label, color=color, alpha=0.85, linewidth=1.3)
            ax.set_title(f"Cumulative Quantile Loss OOS (α={alpha}, M3-based models)", fontsize=10)
            ax.set_ylabel("Cumulative Loss (lower=better)")
            ax.legend(loc="upper left", fontsize=9)
            ax.grid(alpha=0.3)
        else:
            # Show bar chart of mean QL for alpha=0.05
            models = ["M1", "M2", "M3", "M4", "M5"]
            mean_qls = [results["per_alpha"][key]["OOS"][m]["mean_quantile_loss"] for m in models]
            colors = ["#888", "#4682B4", "#1E90FF", "#FF8C00", "#228B22"]
            ax.bar(models, mean_qls, color=colors, alpha=0.85)
            ax.set_title(f"Mean Quantile Loss OOS (α={alpha})", fontsize=10)
            ax.set_ylabel("Mean Quantile Loss (lower=better)")
            ax.grid(alpha=0.3, axis="y")
            for i, v in enumerate(mean_qls):
                if v is not None:
                    ax.text(i, v, f"{v:.4f}", ha="center", va="bottom", fontsize=8)

    plt.suptitle("K1115: OOS Quantile Loss — Conditional Models vs GJR-t Baseline", y=1.02)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "k1115_oos_quantile_loss.png", dpi=120, bbox_inches="tight")
    plt.close()
    print("Saved k1115_oos_quantile_loss.png")


# ---------------------------------------------------------------------------
# 4) Inter-breach duration distribution + Hawkes fit
# ---------------------------------------------------------------------------
def plot_inter_breach_duration(breach_df: pd.DataFrame):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

    for idx, period in enumerate(["IS", "OOS"]):
        ax = axes[idx]
        if period == "IS":
            mask = (breach_df.index >= "2010-01-01") & (breach_df.index <= "2017-12-31")
        else:
            mask = (breach_df.index >= "2018-01-01") & (breach_df.index <= "2026-04-13")
        b = breach_df.loc[mask, "breach_M3"].dropna().astype(int).values
        breach_positions = np.where(b == 1)[0]
        if len(breach_positions) < 2:
            continue
        durations = np.diff(breach_positions)
        # Plot histogram
        n_bins = min(30, len(np.unique(durations)))
        ax.hist(durations, bins=n_bins, color="steelblue", alpha=0.7, edgecolor="black", label="Observed")
        # Overlay: exponential fit (null: Poisson / independence)
        if len(durations) > 5:
            scale = durations.mean()
            x = np.linspace(0.1, durations.max(), 200)
            expected_pdf = stats.expon.pdf(x, scale=scale)
            # Scale pdf to match histogram counts
            bin_width = (durations.max() - durations.min()) / n_bins if n_bins > 0 else 1
            ax.plot(x, expected_pdf * len(durations) * bin_width,
                    "r-", linewidth=2, label=f"Exponential fit (λ⁻¹={scale:.1f})")
        ax.set_title(f"{period}: Inter-Breach Duration (M3 GJR-t, α=1%)", fontsize=10)
        ax.set_xlabel("Days between consecutive breaches")
        ax.set_ylabel("Frequency")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
        # Annotate
        ax.text(0.6, 0.95,
                f"N breaches = {len(breach_positions)}\nMean dur = {durations.mean():.1f}\nMedian dur = {np.median(durations):.0f}",
                transform=ax.transAxes, fontsize=9, verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

    plt.suptitle("K1115: Inter-Breach Duration — Poisson (exponential) vs Hawkes-like Clustering",
                 y=1.02, fontsize=12)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "k1115_inter_breach_duration.png", dpi=120, bbox_inches="tight")
    plt.close()
    print("Saved k1115_inter_breach_duration.png")


if __name__ == "__main__":
    results = load_results()
    breach_df = load_breach_history()
    plot_breach_acf(results, breach_df)
    plot_trinity_heatmap(results)
    plot_cumulative_quantile_loss(results, breach_df)
    plot_inter_breach_duration(breach_df)
    print("All charts saved.")
