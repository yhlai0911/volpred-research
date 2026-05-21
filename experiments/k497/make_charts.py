"""K497 charts: ranking heatmap, Spearman matrix, MCS intersection bar."""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).parent
RESULTS = json.loads((HERE / "k497_loss_sensitivity_results.json").read_text())

models = RESULTS["models"]
losses = ["QLIKE", "MSE", "MAE", "HMSE", "HMAE"]

# Order models by mean rank for nicer display
mean_rank = {m: RESULTS["model_rank_summary"][m]["mean_rank"] for m in models}
ordered_models = sorted(models, key=lambda m: mean_rank[m])


# ---------------- Chart 1: ranking heatmap ----------------
def chart_rankings():
    rk = RESULTS["rankings"]
    M = np.zeros((len(ordered_models), len(losses)), dtype=int)
    for i, m in enumerate(ordered_models):
        for j, lf in enumerate(losses):
            M[i, j] = rk[lf][m]
    fig, ax = plt.subplots(figsize=(8.2, 5.6))
    im = ax.imshow(M, cmap="RdYlGn_r", vmin=1, vmax=8, aspect="auto")
    ax.set_xticks(range(len(losses)))
    ax.set_xticklabels(losses, fontsize=11)
    ax.set_yticks(range(len(ordered_models)))
    ax.set_yticklabels(ordered_models, fontsize=10)
    for i in range(len(ordered_models)):
        for j in range(len(losses)):
            ax.text(j, i, str(M[i, j]), ha="center", va="center",
                    color="black", fontsize=11, fontweight="bold")
    ax.set_title("K497 — Model Ranking under 5 Patton Loss Functions (1=best, 8=worst)",
                 fontsize=12)
    ax.set_xlabel("Loss function")
    ax.set_ylabel("Model (sorted by mean rank)")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Rank")
    fig.tight_layout()
    out = HERE / "k497_ranking_heatmap.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


# ---------------- Chart 2: Spearman pairwise matrix ----------------
def chart_spearman():
    S = RESULTS["spearman_correlation_matrix"]
    M = np.array([[S[a][b] for b in losses] for a in losses])
    fig, ax = plt.subplots(figsize=(6.6, 5.4))
    im = ax.imshow(M, cmap="RdYlBu_r", vmin=0.0, vmax=1.0, aspect="auto")
    ax.set_xticks(range(len(losses)))
    ax.set_xticklabels(losses, fontsize=11)
    ax.set_yticks(range(len(losses)))
    ax.set_yticklabels(losses, fontsize=11)
    for i in range(len(losses)):
        for j in range(len(losses)):
            v = M[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                    color="white" if v < 0.5 else "black", fontsize=11)
    avg = RESULTS["average_pairwise_spearman"]
    ax.set_title(f"K497 — Pairwise Spearman ρ between Loss-induced Rankings\n"
                 f"average ρ = {avg:.4f} (MODERATELY STABLE)", fontsize=11)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Spearman ρ")
    fig.tight_layout()
    out = HERE / "k497_spearman_matrix.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


# ---------------- Chart 3: MCS inclusion fraction bar ----------------
def chart_mcs():
    summary = RESULTS["model_rank_summary"]
    frac = [summary[m]["in_mcs_fraction"] for m in ordered_models]
    count = [summary[m]["in_mcs_count"] for m in ordered_models]
    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    colors = ["#2a9d8f" if f >= 0.8 else "#e9c46a" if f >= 0.4 else "#e76f51"
              for f in frac]
    bars = ax.barh(ordered_models[::-1], frac[::-1], color=colors[::-1])
    for bar, c, f in zip(bars, count[::-1], frac[::-1]):
        ax.text(f + 0.02, bar.get_y() + bar.get_height() / 2,
                f"{c}/5  ({f:.0%})", va="center", fontsize=10)
    ax.set_xlim(0, 1.15)
    ax.set_xlabel("MCS inclusion fraction across 5 loss functions")
    ax.set_title("K497 — MCS Inclusion Across 5 Patton Losses\n"
                 "universal_superior = empty  (no model is in MCS under all 5 losses)",
                 fontsize=11)
    ax.axvline(1.0, color="black", lw=0.8, ls="--", alpha=0.4)
    fig.tight_layout()
    out = HERE / "k497_mcs_intersection.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


if __name__ == "__main__":
    p1 = chart_rankings()
    p2 = chart_spearman()
    p3 = chart_mcs()
    print(p1)
    print(p2)
    print(p3)
