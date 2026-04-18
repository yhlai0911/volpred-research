"""K1204 — Paper 2 §5 publication-quality figure panels.

Figures:
    A  N-extension Spearman ρ trajectory with 95% CI band
    B  Panel Harvey |t| trajectory (joint log_analyst)
    C  Two-level R² structure (between vs within)
    D  EM residual taxonomy (θ_rel vs inst_pct by region)
    E  K1163 EU robustness (K1153 N=18 vs K1163 N=30)

All figures saved as 300-dpi PNG + matching PDF.
Random seed 42 for any jitter/bootstrap.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

np.random.seed(42)

OUT_DIR = Path(__file__).resolve().parent
RESULTS = OUT_DIR / "k1204_results.json"
MAIN_REPO_EXP_DIR = Path("/Users/yhlai0911/Desktop/volpred-research/experiments")

# Publication-quality rc
plt.rcParams.update({
    "figure.dpi": 120,
    "savefig.dpi": 300,
    "font.size": 11,
    "font.family": "DejaVu Sans",
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 9,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "savefig.bbox": "tight",
})


def save_fig(fig: plt.Figure, name: str) -> None:
    png = OUT_DIR / f"{name}.png"
    pdf = OUT_DIR / f"{name}.pdf"
    fig.savefig(png, dpi=300)
    fig.savefig(pdf)
    plt.close(fig)
    print(f"  wrote {png.name} and {pdf.name}")


def spearman_ci_fisher(rho: float, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Approximate 95% CI for Spearman ρ via Fisher z-transform (small-n caveat)."""

    if n < 4 or abs(rho) >= 1.0:
        return (rho, rho)
    z = 0.5 * math.log((1 + rho) / (1 - rho))
    se = 1.0 / math.sqrt(n - 3)
    from scipy.stats import norm  # type: ignore
    z_crit = norm.ppf(0.5 + conf / 2)
    lo, hi = z - z_crit * se, z + z_crit * se
    return (math.tanh(lo), math.tanh(hi))


def figure_A_trajectory(results: dict[str, Any]) -> None:
    """ρ across K-series with 95% CI band + significance lines."""

    traj = [row for row in results["n_extension_trajectory"] if row["spearman_rho"] is not None]
    labels = [f"{row['experiment_id']}\nN={row['N']}" for row in traj]
    rhos = [row["spearman_rho"] for row in traj]
    ps = [row["spearman_p"] for row in traj]
    Ns = [row["N"] for row in traj]

    lo_ci, hi_ci = zip(*[spearman_ci_fisher(r, n) for r, n in zip(rhos, Ns)])

    x = np.arange(len(traj))
    fig, ax = plt.subplots(figsize=(9, 5))

    ax.fill_between(x, lo_ci, hi_ci, alpha=0.25, color="#3b6ea8", label="95% CI (Fisher z)")
    ax.plot(x, rhos, marker="o", markersize=9, color="#1f3f6f", lw=2, zorder=3, label="Spearman ρ")

    for xi, rho, p, row in zip(x, rhos, ps, traj):
        verdict = row["verdict"]
        color = {
            "STRENGTHENED": "#2c7a2c", "PARTIAL": "#d47a0a", "DATA_LIMITED": "#b03030",
        }.get(verdict, "#555555")
        ax.annotate(
            f"ρ={rho:.3f}\np={p:.3f}",
            xy=(xi, rho),
            xytext=(0, 18 if xi % 2 == 0 else -36),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            color=color,
            weight="bold",
        )

    ax.axhline(0, color="black", lw=0.6)
    ax.axhline(0.5, color="#888", ls="--", lw=0.8, label="ρ=0.5 reference")

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(-0.05, 1.05)
    ax.set_ylabel("Cross-market Spearman ρ (inst_pct vs θ_rel)")
    ax.set_title("Figure A — Cross-market ρ across N-extension trajectory (K1165 → K1171)")
    ax.legend(loc="lower left")

    # Annotate each iteration's added markets below x-axis
    added = [row["markets_added"] for row in traj]
    for xi, label in zip(x, added):
        ax.annotate(
            label,
            xy=(xi, -0.02),
            xytext=(0, -38),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color="#666",
            rotation=0,
            annotation_clip=False,
        )

    fig.subplots_adjust(bottom=0.22)
    save_fig(fig, "k1204_figure_A_trajectory_rho")


def figure_B_panel_t(results: dict[str, Any]) -> None:
    """Panel joint log_analyst t monotonic strengthening."""

    seq = results["panel_harvey_t_joint"]["sequence"]
    kids = [k for k, _ in seq]
    ts = [t for _, t in seq]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(seq))

    ax.bar(x, ts, color="#3b6ea8", alpha=0.85, edgecolor="#1f3f6f", lw=1.2)
    for xi, t in zip(x, ts):
        ax.annotate(
            f"{t:.3f}",
            xy=(xi, t),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            weight="bold",
        )

    ax.axhline(3.0, color="#b03030", ls="--", lw=1.2, label="Harvey |t|>3 threshold")
    ax.axhline(1.96, color="#d47a0a", ls=":", lw=1.0, label="|t|>1.96 (naive 5%)")

    ax.set_xticks(x)
    ax.set_xticklabels(kids)
    ax.set_ylabel("Panel joint regression log_analyst |t|")
    ax.set_title(
        "Figure B — Within-market analyst-coverage mechanism strengthens monotonically\n"
        "(joint panel OLS with market FE + inst_pct + log_mcap controls)"
    )
    ax.set_ylim(0, max(ts) * 1.18)
    ax.legend(loc="lower right")

    save_fig(fig, "k1204_figure_B_panel_harvey_t")


def figure_C_two_level(results: dict[str, Any]) -> None:
    """Between-market inst_pct R² vs within-market log_analyst R² side-by-side."""

    traj = [row for row in results["n_extension_trajectory"] if row["between_r2_inst_pct"] is not None]
    kids = [row["experiment_id"] for row in traj]
    between = [row["between_r2_inst_pct"] for row in traj]
    within = [row["within_r2_log_analyst"] for row in traj]
    ratios = [b / w if w else np.nan for b, w in zip(between, within)]

    x = np.arange(len(traj))
    width = 0.35

    fig, ax1 = plt.subplots(figsize=(9, 5))

    b1 = ax1.bar(x - width / 2, between, width, label="Between-market R² (inst_pct)", color="#3b6ea8")
    b2 = ax1.bar(x + width / 2, within, width, label="Within-market R² (log_analyst)", color="#d47a0a")

    for xi, val in zip(x - width / 2, between):
        ax1.annotate(f"{val:.3f}", xy=(xi, val), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=9)
    for xi, val in zip(x + width / 2, within):
        ax1.annotate(f"{val:.3f}", xy=(xi, val), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=9)

    ax1.set_xticks(x)
    ax1.set_xticklabels(kids)
    ax1.set_ylabel("Simple R² (demeaned / cross-market)")
    ax1.set_ylim(0, max(between) * 1.2)
    ax1.legend(loc="upper left")

    ax2 = ax1.twinx()
    ax2.plot(x, ratios, marker="D", color="#2c7a2c", lw=2, label="Between/Within ratio")
    for xi, r in zip(x, ratios):
        if not np.isnan(r):
            ax2.annotate(
                f"{r:.1f}×",
                xy=(xi, r),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
                fontsize=9,
                color="#2c7a2c",
                weight="bold",
            )
    ax2.set_ylabel("Between/Within R² ratio", color="#2c7a2c")
    ax2.tick_params(axis="y", labelcolor="#2c7a2c")
    ax2.grid(False)

    ax1.set_title(
        "Figure C — Two-level R² structure: cross-market inst_pct dominates, within-market analyst secondary"
    )

    save_fig(fig, "k1204_figure_C_two_level_r2")


def figure_D_em_taxonomy(results: dict[str, Any]) -> None:
    """θ_rel vs inst_pct colored by region; K1173 refined layer overlaid."""

    taxonomy = results["em_residual_taxonomy"]
    k1173 = results["k1173_em_proxy_refinement"]

    color_map = {
        "developed": "#1f3f6f",
        "EM_above_ladder": "#b03030",
        "other_EM": "#d47a0a",
        "AU_below_ladder": "#2c7a2c",
    }
    label_map = {
        "developed": "Developed (TW/EU/JP/US)",
        "EM_above_ladder": "EM above-ladder (BR/CA/IN/MX)",
        "other_EM": "Other EM (CH/HK/KR/ID)",
        "AU_below_ladder": "AU below-ladder",
    }

    fig, ax = plt.subplots(figsize=(9, 5.5))

    # Baseline yfinance points
    region_points: dict[str, list[dict[str, Any]]] = {}
    for row in taxonomy:
        region_points.setdefault(row["region"], []).append(row)

    for region, rows in region_points.items():
        xs = [r["inst_pct_mean"] for r in rows]
        ys = [r["theta_rel"] for r in rows]
        ax.scatter(
            xs,
            ys,
            s=120,
            color=color_map[region],
            edgecolor="black",
            lw=0.6,
            alpha=0.85,
            label=label_map[region],
            zorder=3,
        )
        for row, x, y in zip(rows, xs, ys):
            ax.annotate(
                row["market"],
                xy=(x, y),
                xytext=(6, 4),
                textcoords="offset points",
                fontsize=9,
                weight="bold",
            )

    # K1173 refined EM layer as lighter overlays with arrows
    refined_vals = k1173["per_market_diff_mean"]  # diff_mean = refined - yfinance
    # We need baseline inst_pct from K1173 per-market; use baseline row from each market
    baseline_inst = {row["market"]: row["inst_pct_mean"] for row in taxonomy}
    theta_rel_lookup = {row["market"]: row["theta_rel"] for row in taxonomy}

    for mkt, diff in refined_vals.items():
        if mkt not in baseline_inst:
            continue
        base_x = baseline_inst[mkt]
        base_y = theta_rel_lookup[mkt]
        refined_x = base_x + diff
        ax.annotate(
            "",
            xy=(refined_x, base_y),
            xytext=(base_x, base_y),
            arrowprops=dict(arrowstyle="->", color="#8b2a8b", lw=1.5, alpha=0.85),
        )
        ax.scatter(
            [refined_x],
            [base_y],
            s=60,
            facecolor="none",
            edgecolor="#8b2a8b",
            lw=1.8,
            marker="s",
            zorder=4,
        )

    # Ladder reference: linear fit through developed markets
    dev = region_points.get("developed", [])
    if len(dev) >= 2:
        xs = np.array([r["inst_pct_mean"] for r in dev])
        ys = np.array([r["theta_rel"] for r in dev])
        slope, intercept = np.polyfit(xs, ys, 1)
        xr = np.linspace(0.1, 0.8, 50)
        ax.plot(
            xr,
            slope * xr + intercept,
            ls="--",
            color="#1f3f6f",
            lw=1.0,
            alpha=0.6,
            label=f"Developed ladder fit (slope={slope:.2f})",
        )

    purple_patch = mpatches.Patch(
        color="#8b2a8b",
        label="K1173 refined-proxy shift (SEBI/simplywall.st)",
    )
    handles, _ = ax.get_legend_handles_labels()
    handles.append(purple_patch)
    ax.legend(handles=handles, loc="upper left", fontsize=9)

    ax.set_xlabel("Institutional ownership fraction (mean across stocks)")
    ax.set_ylabel("θ_rel (cross-market relative EAV loading)")
    ax.set_title(
        "Figure D — EM residual taxonomy: EM above-ladder cost-of-capital scale factor + AU below-ladder exception\n"
        f"K1173 refined proxy: Δρ = {k1173['delta_rho']:+.3f} (NULL; structural not proxy artefact)"
    )

    save_fig(fig, "k1204_figure_D_em_residual_taxonomy")


def figure_E_k1163_robustness(results: dict[str, Any]) -> None:
    """K1163 EU full-coverage robustness: side-by-side bars + cluster bounds."""

    r = results["k1163_eu_robustness"]

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.8))

    # Panel E1: θ_rel comparison with cluster boundaries
    ax = axes[0]
    labels = ["K1153\n(N=18 DAX-heavy)", "K1163\n(N=30 full EU)"]
    thetas = [r["theta_rel_k1153"], r["theta_rel_k1163"]]
    colors = ["#d47a0a", "#3b6ea8"]
    x = np.arange(2)
    ax.bar(x, thetas, color=colors, edgecolor="black", lw=1)

    ci_lo, ci_hi = r["eu_k1163_boot_ci95"]
    ax.errorbar(
        [1],
        [r["theta_rel_k1163"]],
        yerr=[[r["theta_rel_k1163"] - ci_lo], [ci_hi - r["theta_rel_k1163"]]],
        fmt="none",
        ecolor="black",
        capsize=6,
        lw=1.5,
    )

    for xi, t in zip(x, thetas):
        ax.annotate(f"{t:.3f}", xy=(xi, t), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=10, weight="bold")

    ax.axhline(r["cluster_upper_low"], color="#2c7a2c", ls="--", lw=1.2, label=f"Low cluster upper = {r['cluster_upper_low']}")
    ax.axhline(r["cluster_lower_high"], color="#b03030", ls="--", lw=1.2, label=f"High cluster lower = {r['cluster_lower_high']}")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("θ_rel (EU)")
    ax.set_title("E1 — θ_rel stays in LOW cluster under full coverage")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_ylim(0, 0.35)

    # Panel E2: bootstrap t and placebo z evolution
    ax2 = axes[1]
    metrics = ["cluster boot t", "placebo z"]
    k1153_vals = [r["boot_t_k1153"], r["placebo_z_k1153"]]
    k1163_vals = [r["boot_t_k1163"], r["placebo_z_k1163"]]
    xpos = np.arange(2)
    w = 0.35
    ax2.bar(xpos - w / 2, k1153_vals, w, label="K1153 N=18", color="#d47a0a", edgecolor="black", lw=1)
    ax2.bar(xpos + w / 2, k1163_vals, w, label="K1163 N=30", color="#3b6ea8", edgecolor="black", lw=1)

    for xi, v in zip(xpos - w / 2, k1153_vals):
        ax2.annotate(f"{v:.2f}", xy=(xi, v), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=9)
    for xi, v in zip(xpos + w / 2, k1163_vals):
        ax2.annotate(f"{v:.2f}", xy=(xi, v), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=9)

    ax2.axhline(3.0, color="#555", ls=":", lw=0.8, label="|t|>3 Harvey")
    ax2.set_xticks(xpos)
    ax2.set_xticklabels(metrics)
    ax2.set_ylabel("Test statistic value")
    ax2.set_title("E2 — Cluster boot t and placebo z STRENGTHEN with full coverage")
    ax2.legend(loc="upper left", fontsize=8)

    fig.suptitle(
        "Figure E — K1163 EU full-coverage robustness (verdict: "
        f"{r['verdict_label']})",
        y=1.02,
    )
    save_fig(fig, "k1204_figure_E_k1163_eu_robustness")


def main() -> None:
    with RESULTS.open("r", encoding="utf-8") as handle:
        results = json.load(handle)

    print("Building 5 publication-grade figures for Paper 2 §5...")
    figure_A_trajectory(results)
    figure_B_panel_t(results)
    figure_C_two_level(results)
    figure_D_em_taxonomy(results)
    figure_E_k1163_robustness(results)
    print("All figures written to", OUT_DIR)


if __name__ == "__main__":
    main()
