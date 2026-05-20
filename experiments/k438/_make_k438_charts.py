"""Regenerate K438 charts from results.json (originals lost from disk).

Charts (3):
  1. oos_qlike_comparison.png  — bar chart of OOS QLIKE: GJR baseline vs 3 GARCH-X variants
  2. delta_coefficients.png    — δ point estimate ± 1.96·SE for VRP / VIX / VRP+VIX joint
  3. param_stability.png       — δ trajectory across 24 rolling refit windows

All data sourced from k438_garchx_vrp_results.json (real, no synthetic).
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "k438_garchx_vrp_results.json"


def main() -> None:
    data = json.loads(RESULTS.read_text())
    plt.rcParams["font.family"] = ["DejaVu Sans"]

    # ---- Chart 1: oos_qlike_comparison.png ---------------------------------
    oos = data["oos_evaluation"]
    impr = data["improvements_vs_baseline"]
    labels = ["GJR baseline", "GARCH-X (VRP)", "GARCH-X (VIX)", "GARCH-X (VRP+VIX)"]
    keys = ["GJR_baseline", "GARCH_X_VRP", "GARCH_X_VIX", "GARCH_X_VRP_VIX"]
    qlikes = [oos[k]["qlike"] for k in keys]
    pct_change = [0.0] + [impr[k]["qlike_pct_change"] for k in keys[1:]]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    colors = ["#7f7f7f", "#1f77b4", "#d62728", "#9467bd"]
    bars = ax.bar(labels, qlikes, color=colors, edgecolor="black", linewidth=0.6)
    for bar, q, pc in zip(bars, qlikes, pct_change):
        height = bar.get_height()
        if pc == 0:
            txt = f"QLIKE = {q:.4f}\n(baseline)"
        else:
            txt = f"QLIKE = {q:.4f}\n({pc:+.2f}%)"
        ax.text(bar.get_x() + bar.get_width() / 2, height + 0.001,
                txt, ha="center", va="bottom", fontsize=9.5)
    ax.set_ylabel("OOS QLIKE (lower is better)", fontsize=11)
    ax.set_title("K438: Out-of-Sample QLIKE — GJR vs GARCH-X variants",
                 fontsize=12, fontweight="bold")
    ymin = min(qlikes) - 0.01
    ymax = max(qlikes) + 0.018
    ax.set_ylim(ymin, ymax)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(HERE / "oos_qlike_comparison.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("wrote oos_qlike_comparison.png")

    # ---- Chart 2: delta_coefficients.png -----------------------------------
    sig = data["delta_significance"]
    rows = [
        ("VRP only\n(GARCH-X)", sig["VRP"]["delta"], sig["VRP"]["se"],
         sig["VRP"]["t_stat"], sig["VRP"]["p_value"], sig["VRP"]["passes_harvey"]),
        ("VIX only\n(GARCH-X)", sig["VIX"]["delta"], sig["VIX"]["se"],
         sig["VIX"]["t_stat"], sig["VIX"]["p_value"], sig["VIX"]["passes_harvey"]),
        ("VRP in joint\n(VRP+VIX)", sig["VRP_VIX"]["delta_VRP"], sig["VRP_VIX"]["se_VRP"],
         sig["VRP_VIX"]["t_stat_VRP"], sig["VRP_VIX"]["p_value_VRP"],
         abs(sig["VRP_VIX"]["t_stat_VRP"]) > 3.0),
        ("VIX in joint\n(VRP+VIX)", sig["VRP_VIX"]["delta_VIX"], sig["VRP_VIX"]["se_VIX"],
         sig["VRP_VIX"]["t_stat_VIX"], sig["VRP_VIX"]["p_value_VIX"],
         abs(sig["VRP_VIX"]["t_stat_VIX"]) > 3.0),
    ]

    fig, ax = plt.subplots(figsize=(10, 5.8))
    xs = np.arange(len(rows))
    deltas = np.array([r[1] for r in rows])
    ses = np.array([r[2] for r in rows])
    ts = np.array([r[3] for r in rows])
    harvey = [r[5] for r in rows]
    bar_colors = ["#1f77b4" if h else "#d3d3d3" for h in harvey]

    ax.bar(xs, deltas, yerr=1.96 * ses, capsize=8,
           color=bar_colors, edgecolor="black", linewidth=0.7,
           error_kw={"linewidth": 1.4, "ecolor": "#333333"})
    ax.axhline(0, color="black", linewidth=0.8)

    for i, (label, d, se, t, p, h) in enumerate(rows):
        sig_str = "Harvey PASS" if h else "Harvey FAIL"
        ax.text(i, d + (1.96 * se if d >= 0 else -1.96 * se) + (0.005 if d >= 0 else -0.012),
                f"δ={d:.4f}\nt={t:.2f}\n{sig_str}",
                ha="center", va="bottom" if d >= 0 else "top", fontsize=9)

    ax.set_xticks(xs)
    ax.set_xticklabels([r[0] for r in rows])
    ax.set_ylabel("δ (variance-equation exogenous coefficient)", fontsize=11)
    ax.set_title("K438: δ point estimates (95% CI) — Harvey t>3 gate",
                 fontsize=12, fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)

    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, color="#1f77b4", label="Harvey PASS (|t|>3)"),
        plt.Rectangle((0, 0), 1, 1, color="#d3d3d3", label="Harvey FAIL"),
    ]
    ax.legend(handles=legend_handles, loc="upper left", framealpha=0.9)
    fig.tight_layout()
    fig.savefig(HERE / "delta_coefficients.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("wrote delta_coefficients.png")

    # ---- Chart 3: param_stability.png --------------------------------------
    # 24 rolling refit windows. results.json only stores summary stats per
    # window-set (mean/std/min/max + n_pos/n_neg/sign_changes); plot
    # mean ± std band per spec, side-by-side, plus annotate sign-change count.
    stab = data["param_stability"]
    specs = [
        ("VRP only", stab["GARCH_X_VRP"]["delta"]),
        ("VIX only", stab["GARCH_X_VIX"]["delta"]),
        ("VRP (joint)", stab["GARCH_X_VRP_VIX"]["delta_VRP"]),
        ("VIX (joint)", stab["GARCH_X_VRP_VIX"]["delta_VIX"]),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    # Left: VRP-related (small magnitude)
    for ax_idx, group in enumerate([[0, 2], [1, 3]]):
        ax = axes[ax_idx]
        for j, idx in enumerate(group):
            label, st = specs[idx]
            mean = st["mean"]
            std = st["std"]
            mn = st["min"]
            mx = st["max"]
            n_pos = st["n_positive"]
            n_neg = st["n_negative"]
            n_sc = st["sign_changes"]
            x = j
            ax.errorbar([x], [mean], yerr=[[mean - mn], [mx - mean]],
                        fmt="o", capsize=10, markersize=8, linewidth=1.5,
                        color="#1f77b4" if n_neg == 0 else "#d62728",
                        label="min/max range")
            # ±1 std band overlay
            ax.fill_between([x - 0.15, x + 0.15], [mean - std, mean - std],
                            [mean + std, mean + std],
                            color="#1f77b4" if n_neg == 0 else "#d62728",
                            alpha=0.25)
            ax.text(x, mx + (mx - mn) * 0.1 + abs(mean) * 0.05,
                    f"μ={mean:.4f}\nσ={std:.4f}\n+/-/SC={n_pos}/{n_neg}/{n_sc}",
                    ha="center", va="bottom", fontsize=9)

        ax.set_xticks(range(len(group)))
        ax.set_xticklabels([specs[idx][0] for idx in group])
        ax.axhline(0, color="black", linewidth=0.8, linestyle=":")
        ax.set_ylabel("δ across 24 rolling refits")
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)
        ax.set_title("VRP coefficient" if ax_idx == 0 else "VIX coefficient",
                     fontsize=11, fontweight="bold")

    fig.suptitle("K438: δ stability across 24 rolling refit windows "
                 "(±std band, full min/max range, sign-flip count)",
                 fontsize=12, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(HERE / "param_stability.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("wrote param_stability.png")


if __name__ == "__main__":
    main()
