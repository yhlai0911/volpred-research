"""K1207 figures.

Three PNGs at 300dpi:
  1. Sector-median θ_EAV by GICS sector (10 sectors)
  2. Per-market sector mix stacked bar (12 markets, AU/BR/IN/MX highlighted)
  3. R² decomposition bar chart (4 models × between-stock R²)

Seed fixed 42 (no random draws used; seed kept for consistency).
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "k1207_results.json"
MIX_CSV = ROOT / "k1207_per_market_sector_mix_pct.csv"
SECTOR_CSV = ROOT / "k1207_sector_median.csv"


def fig1_sector_theta_median() -> None:
    sec = pd.read_csv(SECTOR_CSV)
    sec = sec.sort_values("theta_eav_median", ascending=True)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    colors = ["#1f77b4" if n > 3 else "#aaaaaa" for n in sec["n"]]
    ax.barh(sec["gics_sector"], sec["theta_eav_median"] * 1e4, color=colors, edgecolor="black")
    for i, (v, n) in enumerate(zip(sec["theta_eav_median"], sec["n"])):
        ax.text(v * 1e4 + 0.05, i, f"n={n}", va="center", fontsize=8)
    ax.set_xlabel(r"Median $\theta_{EAV}$ $(\times 10^{-4})$")
    ax.set_title(
        "K1207 Fig 1: per-GICS-sector median θ_EAV (K1171 N=182 pool)\n"
        "grey bars = sectors with n<4 (under-powered)"
    )
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    plt.savefig(ROOT / "k1207_sector_theta_median.png", dpi=300)
    plt.close(fig)
    print("Wrote k1207_sector_theta_median.png")


def fig2_per_market_sector_mix() -> None:
    mix = pd.read_csv(MIX_CSV, index_col=0)
    # Order markets by K1171 inst_pct_mean to match paper narrative order
    # ID low -> US high. Hardcode from README table
    order = ["ID", "CH", "MX", "TW", "HK", "KR", "AU", "IN", "EU", "JP", "BR", "CA", "US"]
    order = [m for m in order if m in mix.index]
    mix = mix.loc[order]
    # Sector ordering: largest totals first
    totals = mix.sum(axis=0).sort_values(ascending=False)
    mix = mix[totals.index]
    # Color palette — 10 distinct colors
    cmap = plt.get_cmap("tab10")
    colors = [cmap(i) for i in range(len(mix.columns))]
    fig, ax = plt.subplots(figsize=(12, 6))
    bottom = np.zeros(len(mix))
    for i, col in enumerate(mix.columns):
        ax.bar(
            mix.index,
            mix[col].values,
            bottom=bottom,
            label=col,
            color=colors[i],
            edgecolor="white",
            linewidth=0.5,
        )
        bottom += mix[col].values
    # Highlight AU/BR/IN/MX tick labels
    for lbl in ax.get_xticklabels():
        if lbl.get_text() in {"AU", "BR", "IN", "MX"}:
            lbl.set_fontweight("bold")
            lbl.set_color("#d62728")
    ax.set_ylabel("Sector share (%)")
    ax.set_ylim(0, 100)
    ax.set_title(
        "K1207 Fig 2: per-market GICS sector composition (ordered by inst_pct_mean)\n"
        "red bold labels = off-ladder residual markets (AU below, BR/IN/MX above)"
    )
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8, frameon=False)
    plt.tight_layout()
    plt.savefig(ROOT / "k1207_per_market_sector_mix.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print("Wrote k1207_per_market_sector_mix.png")


def fig3_r2_decomposition() -> None:
    with RESULTS.open() as fh:
        res = json.load(fh)
    mods = res["analysis2_4model"]
    names = ["M1\nmkt+mcap", "M2\n+inst_pct", "M3\n+sector_FE", "M4\n+inst+sector"]
    r2 = [mods["M1"]["r2"], mods["M2"]["r2"], mods["M3"]["r2"], mods["M4"]["r2"]]
    adj = [mods["M1"]["adj_r2"], mods["M2"]["adj_r2"], mods["M3"]["adj_r2"], mods["M4"]["adj_r2"]]
    x = np.arange(len(names))
    w = 0.38
    fig, ax = plt.subplots(figsize=(9, 5.5))
    b1 = ax.bar(x - w / 2, r2, w, color="#1f77b4", label="R²", edgecolor="black")
    b2 = ax.bar(x + w / 2, adj, w, color="#ff7f0e", label="Adj R²", edgecolor="black")
    for bars in (b1, b2):
        for b in bars:
            h = b.get_height()
            ax.text(
                b.get_x() + b.get_width() / 2, h + 0.005, f"{h:.3f}",
                ha="center", va="bottom", fontsize=8,
            )
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=9)
    ax.set_ylabel("R²")
    ax.set_ylim(0, max(r2) * 1.25)
    ax.set_title(
        "K1207 Fig 3: 4-model R² comparison (K1171 N=182 pool)\n"
        "M3 sector-FE adj-R² jump vs M2 inst-FE: empirical test of K1171 orthogonal claim"
    )
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(ROOT / "k1207_r2_decomposition.png", dpi=300)
    plt.close(fig)
    print("Wrote k1207_r2_decomposition.png")


def main() -> None:
    fig1_sector_theta_median()
    fig2_per_market_sector_mix()
    fig3_r2_decomposition()


if __name__ == "__main__":
    main()
