"""K1122 plots: sigmoid curve example + Sharpe heatmap grid."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl

mpl.rcParams["figure.dpi"] = 110

ROOT = Path(__file__).resolve().parent
RESULTS = json.load(open(ROOT / "k1122_results.json"))


def plot_sigmoid_curves():
    z = np.linspace(-3, 3, 400)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    # Left: vary alpha at z0=0
    for a in [0.5, 1, 2, 4]:
        w = 1 / (1 + np.exp(-a * (z - 0)))
        ax[0].plot(z, w, label=f"alpha={a}", lw=2)
    # Reference: step at 70th pct (~ z=0.524 normal)
    ax[0].axvline(0.524, color="k", ls=":", alpha=0.4, label="step thr (70%ile~z=0.52)")
    ax[0].axhline(0.5, color="grey", lw=0.5)
    ax[0].set_xlabel("z (alt-data trailing 252d z-score)")
    ax[0].set_ylabel("w_def (defensive sleeve weight)")
    ax[0].set_title("K1122 sigmoid loading vs alpha (z0=0)")
    ax[0].legend(loc="lower right", fontsize=8)
    ax[0].grid(alpha=0.3)

    # Right: vary z0 at alpha=2
    for z0 in [-0.5, 0, 0.5]:
        w = 1 / (1 + np.exp(-2 * (z - z0)))
        ax[1].plot(z, w, label=f"z0={z0}", lw=2)
    ax[1].axhline(0.5, color="grey", lw=0.5)
    ax[1].set_xlabel("z")
    ax[1].set_ylabel("w_def")
    ax[1].set_title("K1122 sigmoid centre shift (alpha=2)")
    ax[1].legend(loc="lower right", fontsize=8)
    ax[1].grid(alpha=0.3)

    fig.suptitle("K1122 - sigmoid weight curves (continuous loading replaces 70%ile step)",
                 fontsize=11, y=1.02)
    fig.tight_layout()
    out = ROOT / "k1122_sigmoid_curves.png"
    fig.savefig(out, bbox_inches="tight")
    print(f"saved {out}")
    plt.close(fig)


def plot_sharpe_heatmaps():
    """6 heatmaps: 3 drivers x 2 universes; alpha (rows) x z0 (cols),
    cell value = Sharpe - baseline_Sharpe."""
    drivers = ["EPU", "NFCI", "STLFSI4"]
    universes = ["SPY_GLD", "SPY_GLD_TLT"]
    alphas = [0.5, 1.0, 2.0, 4.0]
    z0s = [-0.5, 0.0, 0.5]
    all_specs = RESULTS["all_specs_pair"] + RESULTS["all_specs_3asset"]

    fig, axes = plt.subplots(len(universes), len(drivers),
                             figsize=(13, 7.5), sharey=True)

    # global colour scale
    diffs_all = []
    for s in all_specs:
        d = s["bootstrap_vs_baseline"]["obs_diff"]
        if d is not None and not np.isnan(d):
            diffs_all.append(d)
    vmax = max(abs(min(diffs_all)), abs(max(diffs_all)))

    for i, u in enumerate(universes):
        for j, d in enumerate(drivers):
            ax = axes[i, j]
            mat = np.full((len(alphas), len(z0s)), np.nan)
            pmat = np.full((len(alphas), len(z0s)), np.nan)
            for s in all_specs:
                if s["universe"] != u or s["driver"] != d:
                    continue
                a_idx = alphas.index(s["alpha"])
                z_idx = z0s.index(s["z0"])
                mat[a_idx, z_idx] = s["bootstrap_vs_baseline"]["obs_diff"]
                pmat[a_idx, z_idx] = s["bootstrap_vs_baseline"]["p_value"]
            im = ax.imshow(mat, cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
            for ai in range(len(alphas)):
                for zi in range(len(z0s)):
                    val = mat[ai, zi]
                    pv = pmat[ai, zi]
                    star = "*" if pv < 0.05 else ""
                    txt = f"{val:+.3f}{star}\np={pv:.2f}"
                    color = "white" if abs(val) > vmax * 0.6 else "black"
                    ax.text(zi, ai, txt, ha="center", va="center",
                            fontsize=7, color=color)
            ax.set_xticks(range(len(z0s)))
            ax.set_xticklabels([str(z) for z in z0s])
            ax.set_yticks(range(len(alphas)))
            ax.set_yticklabels([str(a) for a in alphas])
            if i == 0:
                ax.set_title(f"{d}", fontsize=10)
            if j == 0:
                ax.set_ylabel(f"{u}\nalpha", fontsize=9)
            if i == len(universes) - 1:
                ax.set_xlabel("z0")
    fig.suptitle("K1122 Sharpe diff vs 50/50 baseline (Politis-Romano stationary bootstrap)\n"
                 "0/72 specs pass Harvey t>3 - sigmoid does NOT rescue alt-data allocation",
                 fontsize=10, y=1.02)
    fig.colorbar(im, ax=axes, shrink=0.8, label="Sharpe diff (strategy - baseline)")
    out = ROOT / "k1122_sharpe_heatmap.png"
    fig.savefig(out, bbox_inches="tight")
    print(f"saved {out}")
    plt.close(fig)


def plot_summary():
    """One bar chart: number of specs nominal-beat per driver, plus best diff."""
    drivers = ["EPU", "NFCI", "STLFSI4"]
    all_specs = RESULTS["all_specs_pair"] + RESULTS["all_specs_3asset"]
    counts = []
    bests = []
    for d in drivers:
        rows = [s for s in all_specs if s["driver"] == d]
        diffs = [s["bootstrap_vs_baseline"]["obs_diff"] for s in rows]
        counts.append(sum(1 for x in diffs if x > 0))
        bests.append(max(diffs))

    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    bars = ax[0].bar(drivers, counts, color=["#d62728", "#2ca02c", "#1f77b4"])
    ax[0].axhline(24, color="grey", ls=":", label="all (24 specs/driver)")
    ax[0].set_ylabel("# specs nominally beating 50/50")
    ax[0].set_title("K1122: how many sigmoid specs beat baseline?")
    for b, c in zip(bars, counts):
        ax[0].text(b.get_x() + b.get_width()/2, b.get_height() + 0.5,
                   f"{c}/24", ha="center")
    ax[0].set_ylim(0, 28)
    ax[0].legend()
    ax[0].grid(alpha=0.3, axis="y")

    bars2 = ax[1].bar(drivers, bests, color=["#d62728", "#2ca02c", "#1f77b4"])
    ax[1].axhline(0, color="black", lw=0.6)
    ax[1].set_ylabel("Best Sharpe diff vs baseline")
    ax[1].set_title("K1122: max Sharpe diff per driver")
    for b, v in zip(bars2, bests):
        ax[1].text(b.get_x() + b.get_width()/2,
                   v + (0.005 if v > 0 else -0.012),
                   f"{v:+.3f}", ha="center")
    ax[1].grid(alpha=0.3, axis="y")

    fig.suptitle("K1122 - even the best sigmoid spec does NOT clear Harvey or 3/3 stability gates",
                 y=1.02, fontsize=10)
    fig.tight_layout()
    out = ROOT / "k1122_summary.png"
    fig.savefig(out, bbox_inches="tight")
    print(f"saved {out}")
    plt.close(fig)


if __name__ == "__main__":
    plot_sigmoid_curves()
    plot_sharpe_heatmaps()
    plot_summary()
