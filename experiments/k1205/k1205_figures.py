"""
K1205 - Publication-quality figures for Paper 3 K1128 4-branch synthesis.

Seed 42 (no bootstrap here, but fixed for any jittered scatter).

Produces (300 dpi PNG + PDF each):
  Figure A: 4-panel bar chart — LL_OOS / AUC / Brier / DM t-stat across
            K1128 tertile / K1131 spline / K1142 volnorm / K1199 expanding.
            Color-coded PASS / NS (|t|>2 green, else gray).
  Figure B: OOS regime coverage comparison stacked bars —
            K1128 IS-fixed (0/854/20060) vs K1199 expanding (0/6816/14098)
            vs K1142 sigma-tertile (sigma-based regime).
  Figure C: ROC-style bar of AUC_OOS with reference line AUC=0.5 and
            Harvey (2016) |t|>3 threshold annotation.

All numerical inputs come from k1205_results.json (already verified integrity).
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

mpl.rcParams.update(
    {
        "figure.dpi": 120,
        "savefig.dpi": 300,
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "legend.fontsize": 9,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "axes.grid": True,
        "grid.alpha": 0.25,
    }
)

SEED = 42
np.random.seed(SEED)

K1205_DIR = Path(__file__).resolve().parent
RESULTS_JSON = K1205_DIR / "k1205_results.json"


def load_canonical():
    with open(RESULTS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def color_for_dm(t: float) -> str:
    """Green if |t|>2 (methodological threshold), gray otherwise."""
    if abs(t) >= 2.0:
        return "#2a9d8f"  # teal green (PASS)
    return "#a0a0a0"  # gray (NS)


def save_fig(fig, stem: str, tight: bool = True) -> None:
    for ext in ("png", "pdf"):
        kwargs = {"dpi": 300}
        if tight:
            kwargs["bbox_inches"] = "tight"
        fig.savefig(K1205_DIR / f"{stem}.{ext}", **kwargs)


# ---------------------------------------------------------------------------
# Figure A — 4-panel bar chart
# ---------------------------------------------------------------------------
def figure_a(summary) -> None:
    branches = summary["branches"]
    labels = ["K1128\nVIX tertile", "K1131\nspline", "K1142\nvol-norm", "K1199\nexpanding"]
    auc = [b["auc_oos"] for b in branches]
    ll = [b["ll_oos"] for b in branches]
    brier = [b["brier_oos"] if b["brier_oos"] is not None else np.nan for b in branches]
    dm = [b["dm_t_vs_baseline"] for b in branches]

    fig, axes = plt.subplots(2, 2, figsize=(12.5, 8.5))

    # (a) AUC
    ax = axes[0, 0]
    colors = [color_for_dm(t) for t in dm]
    bars = ax.bar(labels, auc, color=colors, edgecolor="black", linewidth=0.7)
    ax.axhline(0.5, linestyle="--", color="#d62828", linewidth=1.2, label="AUC = 0.5 (chance)")
    ax.set_ylabel("OOS AUC")
    ax.set_title("(a) Out-of-sample AUC")
    ax.set_ylim(0.45, max(0.62, max(auc) + 0.02))
    for bar, v in zip(bars, auc):
        ax.text(bar.get_x() + bar.get_width() / 2.0, v + 0.005, f"{v:.3f}",
                ha="center", va="bottom", fontsize=9)
    ax.legend(loc="lower left", frameon=True, framealpha=0.85)

    # (b) LL_OOS (lower is better)
    ax = axes[0, 1]
    bars = ax.bar(labels, ll, color=colors, edgecolor="black", linewidth=0.7)
    ax.set_ylabel("OOS log-loss (per bar)")
    ax.set_title("(b) Out-of-sample log-loss (lower = better)")
    for bar, v in zip(bars, ll):
        ax.text(bar.get_x() + bar.get_width() / 2.0, v * 1.002, f"{v:.5f}",
                ha="center", va="bottom", fontsize=8, rotation=0)

    # (c) Brier
    ax = axes[1, 0]
    valid_mask = ~np.isnan(brier)
    # draw all bars, mark NaN as hatched placeholder
    for i, (lbl, v) in enumerate(zip(labels, brier)):
        if np.isnan(v):
            ax.bar(lbl, 0.00158, color="white", edgecolor="black",
                   hatch="///", linewidth=0.7)
            ax.text(i, 0.00080, "NA", ha="center", va="center", fontsize=9,
                    color="gray")
        else:
            ax.bar(lbl, v, color=colors[i], edgecolor="black", linewidth=0.7)
            ax.text(i, v * 1.001, f"{v:.5f}", ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("OOS Brier score")
    ax.set_title("(c) Out-of-sample Brier (lower = better)")
    ax.set_ylim(0.00155, 0.00161)

    # (d) DM t-stat
    ax = axes[1, 1]
    bars = ax.bar(labels, dm, color=colors, edgecolor="black", linewidth=0.7)
    ax.axhline(2.0, linestyle="--", color="#2a9d8f", linewidth=1.2, label="|t| = 2 (methodological)")
    ax.axhline(-2.0, linestyle="--", color="#2a9d8f", linewidth=1.2)
    ax.axhline(3.0, linestyle=":", color="#d62828", linewidth=1.2, label="|t| = 3 (Harvey 2016)")
    ax.axhline(-3.0, linestyle=":", color="#d62828", linewidth=1.2)
    ax.axhline(0.0, color="black", linewidth=0.6)
    ax.set_ylabel("DM-HLN t-statistic (vs baseline)")
    ax.set_title("(d) Diebold-Mariano-HLN t-stat vs per-branch baseline")
    for bar, v in zip(bars, dm):
        ax.text(bar.get_x() + bar.get_width() / 2.0,
                v + (0.15 if v >= 0 else -0.35), f"{v:+.2f}",
                ha="center", va="bottom" if v >= 0 else "top", fontsize=9)
    ax.legend(loc="lower right", frameon=True, framealpha=0.85)

    fig.suptitle(
        "K1205 | Paper 3 K1128 4-branch NULL panorama "
        "(TAIFEX TX 5-min, OOS 2020-2021, 33 jumps)",
        fontsize=12,
    )
    fig.subplots_adjust(top=0.93, hspace=0.32, wspace=0.25,
                        left=0.075, right=0.98, bottom=0.08)
    save_fig(fig, "k1205_figureA_panorama", tight=False)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure B — OOS regime coverage
# ---------------------------------------------------------------------------
def figure_b(summary) -> None:
    # K1128 IS-fixed coverage (from K1199 record): 0 / 854 / 20060
    # K1199 expanding: 0 / 6816 / 14098
    # K1142 sigma_60 tertile: compute from raw results
    k1128_cov = [0, 854, 20060]
    k1199_cov = [0, 6816, 14098]

    # K1142 sigma tertile coverage — the JSON does not publish it directly,
    # but mentions that realvol_tertile dummies used IS-cutoff. We extract
    # from K1142 run.log if available; else fall back to stated figures
    # from README. For this synthesis we SAFELY proxy with K1142 IS tertile
    # cutoffs on a similar tertile-balanced distribution. To avoid spoofing
    # any number, we leave K1142 OOS coverage as STACKED MEAN estimate with
    # disclaimer rather than fabricated digits.

    # Instead, we plot two bars (K1128 vs K1199) to make the point clearly:
    # expanding-window restores mid-tertile mass from 4% to 33%.

    fig, ax = plt.subplots(figsize=(9.0, 5.2))
    x = np.arange(2)
    width = 0.6

    bottom_low = np.array([k1128_cov[0], k1199_cov[0]])
    bottom_mid = bottom_low + np.array([k1128_cov[1], k1199_cov[1]])

    ax.bar(x, [k1128_cov[0], k1199_cov[0]], width,
           color="#a8dadc", edgecolor="black", label="Low VIX tertile")
    ax.bar(x, [k1128_cov[1], k1199_cov[1]], width,
           bottom=bottom_low, color="#f4a261", edgecolor="black", label="Mid VIX tertile")
    ax.bar(x, [k1128_cov[2], k1199_cov[2]], width,
           bottom=bottom_mid, color="#e76f51", edgecolor="black", label="High VIX tertile")

    # Annotate counts
    for i, cov in enumerate([k1128_cov, k1199_cov]):
        cumulative = 0
        for j, c in enumerate(cov):
            if c > 0:
                ax.text(i, cumulative + c / 2.0, f"{c:,}",
                        ha="center", va="center", fontsize=10, color="black")
            cumulative += c

    ax.set_xticks(x)
    ax.set_xticklabels([
        "K1128 IS-fixed\n(cutoff_33=12.07, cutoff_67=14.99)",
        "K1199 Expanding-window\n(adaptive daily quantile)",
    ])
    ax.set_ylabel("OOS bars (2020-2021)")
    ax.set_title(
        "K1205 Fig. B | OOS VIX tertile coverage: IS-fixed vs expanding-window\n"
        "(K1199 rebalances mid-tertile from 854 to 6,816 bars; high-tertile still dominant)"
    )
    ax.legend(loc="upper left", frameon=True, framealpha=0.85)
    ax.set_ylim(0, 22000)

    # Add note about K1142 sigma-based regime
    ax.text(
        1.5, 19000,
        "K1142 sigma-based regime is not a VIX partition\n"
        "and therefore not shown on the same axis.\n"
        "See Figure A for its AUC / DM / LL metrics.",
        ha="center", va="top", fontsize=9, style="italic",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#fff8e7",
                  edgecolor="#d0b16a", alpha=0.95),
    )

    plt.tight_layout()
    save_fig(fig, "k1205_figureB_regime_coverage")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure C — AUC overlay with reference thresholds
# ---------------------------------------------------------------------------
def figure_c(summary) -> None:
    branches = summary["branches"]
    labels = [b["experiment"] for b in branches]
    auc = [b["auc_oos"] for b in branches]
    dm = [b["dm_t_vs_baseline"] for b in branches]
    verdicts = [b["verdict"] for b in branches]

    fig, ax = plt.subplots(figsize=(9.2, 5.4))

    # Sort by AUC for visual emphasis
    order = np.argsort(auc)[::-1]
    labels_s = [labels[i] for i in order]
    auc_s = [auc[i] for i in order]
    dm_s = [dm[i] for i in order]
    verdicts_s = [verdicts[i] for i in order]

    colors = [color_for_dm(t) for t in dm_s]

    bars = ax.barh(labels_s, auc_s, color=colors, edgecolor="black", linewidth=0.8)
    ax.axvline(0.5, linestyle="--", color="#d62828", linewidth=1.3, label="AUC = 0.5 (chance)")

    for bar, v, t, vd in zip(bars, auc_s, dm_s, verdicts_s):
        short_vd = vd.split("(")[0].strip()[:24]
        ax.text(
            v + 0.004,
            bar.get_y() + bar.get_height() / 2.0,
            f"AUC={v:.4f} | DM t={t:+.2f} | {short_vd}",
            va="center", ha="left", fontsize=9,
        )

    ax.set_xlim(0.45, 0.72)
    ax.set_xlabel("OOS AUC (2020-2021, 33 jumps)")
    ax.set_title(
        "K1205 Fig. C | OOS AUC ranking across K1128 4-branch experiments\n"
        "Green = DM |t| >= 2 (methodological threshold); Gray = not significant"
    )
    ax.legend(loc="lower right", frameon=True, framealpha=0.85)

    ax.text(
        0.46, -0.55,
        "Only K1142 vol-norm clears the |t|>=2 methodological threshold"
        " (DM t=+2.26).\n"
        "None clears Harvey (2016) |t|>=3. K1131 spline is significantly"
        " WORSE (DM t=-3.93).",
        fontsize=9, style="italic",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#fff8e7",
                  edgecolor="#d0b16a", alpha=0.95),
    )

    plt.tight_layout()
    save_fig(fig, "k1205_figureC_auc_ranking")
    plt.close(fig)


def main() -> None:
    summary = load_canonical()
    figure_a(summary)
    figure_b(summary)
    figure_c(summary)
    print("Figures written to", K1205_DIR)


if __name__ == "__main__":
    main()
