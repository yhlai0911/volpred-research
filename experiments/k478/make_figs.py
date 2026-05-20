"""Generate publication figures for K478 entropy null result article.

Reads experiments/k478/k478_entropy_vol_results.json and produces:
  - k478_qlike_comparison.png : OOS QLIKE bar chart per model
  - k478_dm_pvalues.png       : DM p-values vs HAR baseline (log scale)
  - k478_granger_summary.png  : Granger F-stat / p-value per entropy feature
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np

ROOT = Path(__file__).resolve().parent
RESULTS = json.loads((ROOT / "k478_entropy_vol_results.json").read_text())

mpl.rcParams["font.family"] = ["Heiti TC", "PingFang TC", "Arial Unicode MS", "sans-serif"]
mpl.rcParams["axes.unicode_minus"] = False


def _save(fig: plt.Figure, name: str) -> Path:
    out = ROOT / name
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")
    return out


def fig_qlike() -> None:
    """OOS QLIKE per model — show M5/M7 explosion + M6 winner."""
    oos = RESULTS["oos_results"]
    # Drop M5/M7 from main panel (n_obs=159 not comparable; QLIKE explodes).
    main_models = ["M1_baseline", "M3_pe", "M4_shannon", "M6_vix"]
    labels = {
        "M1_baseline": "M1 HAR\nbaseline",
        "M3_pe": "M3 HAR+\nPermutation E.",
        "M4_shannon": "M4 HAR+\nShannon E.",
        "M6_vix": "M6 HAR+\nVIX",
    }
    qlike = [oos[m]["qlike"] for m in main_models]
    n_obs = [oos[m]["n_obs"] for m in main_models]

    fig, ax = plt.subplots(figsize=(8, 5))
    colors = ["#4C78A8", "#7C9885", "#7C9885", "#E15759"]
    bars = ax.bar([labels[m] for m in main_models], qlike, color=colors, edgecolor="black", linewidth=0.6)
    for bar, q, n in zip(bars, qlike, n_obs):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.003,
            f"{q:.4f}\n(n={n})",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.axhline(qlike[0], color="#4C78A8", linestyle="--", linewidth=0.8, alpha=0.7,
               label=f"HAR baseline ({qlike[0]:.4f})")
    ax.set_ylabel("OOS QLIKE（越低越好）")
    ax.set_title("K478：樣本外 QLIKE — entropy 變體沒有贏 HAR baseline，VIX 才是贏家")
    ax.set_ylim(0, max(qlike) * 1.18)
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9)
    ax.grid(axis="y", alpha=0.25)
    _save(fig, "k478_qlike_comparison.png")


def fig_dm() -> None:
    """DM p-values per challenger model (vs HAR baseline)."""
    dm = RESULTS["dm_tests_vs_baseline"]
    # Order: entropy variants first, then VIX last for contrast.
    order = ["M3_pe", "M4_shannon", "M6_vix"]
    pretty = {
        "M3_pe": "M3 Permutation Entropy",
        "M4_shannon": "M4 Shannon Entropy",
        "M6_vix": "M6 VIX",
    }
    pvals = [dm[m]["dm_qlike_p"] for m in order]
    gains = [dm[m]["qlike_gain_pct"] for m in order]
    # winner_against_baseline = (t > 0 means baseline beats challenger)
    # In this JSON dm_qlike_t < 0 means challenger beats baseline.
    t_stats = [dm[m]["dm_qlike_t"] for m in order]
    direction = [
        "挑戰者勝（QLIKE 更低）" if t < 0 else "Baseline 勝（QLIKE 更低）"
        for t in t_stats
    ]

    fig, ax = plt.subplots(figsize=(8.4, 5))
    x = np.arange(len(order))
    colors = ["#7C9885", "#7C9885", "#E15759"]
    bars = ax.bar(x, [-np.log10(p) for p in pvals], color=colors, edgecolor="black", linewidth=0.6)

    for bar, p, g, d in zip(bars, pvals, gains, direction):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.05,
            f"顯著性 {p:.3g}\n方向：{d}\nQLIKE 改善 {g:+.2f}%",
            ha="center",
            va="bottom",
            fontsize=8.5,
        )
    ax.axhline(-np.log10(0.05), color="grey", linestyle="--", linewidth=0.8, label="0.05 顯著性門檻")
    ax.set_xticks(x)
    ax.set_xticklabels([pretty[m] for m in order])
    ax.set_ylabel("-log10(顯著性 p)")
    ax.set_title("K478：兩模型比較 vs HAR baseline — entropy 即便顯著也是反向（baseline 勝）")
    ax.set_ylim(0, max(-np.log10(p) for p in pvals) * 1.45)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", alpha=0.25)
    _save(fig, "k478_dm_pvalues.png")


def fig_granger() -> None:
    """Granger causality F-stat + p-value per entropy feature."""
    g = RESULTS["granger_tests"]
    order = ["sampen_lag", "pe_lag", "shannon_lag"]
    pretty = {
        "sampen_lag": "Sample Entropy",
        "pe_lag": "Permutation Entropy",
        "shannon_lag": "Shannon Entropy",
    }
    fstats = [g[k]["f_stat"] for k in order]
    pvals = [g[k]["p_value"] for k in order]

    fig, ax = plt.subplots(figsize=(8, 4.6))
    colors = ["#7C9885", "#A99E5E", "#7C9885"]
    bars = ax.bar([pretty[k] for k in order], fstats, color=colors, edgecolor="black", linewidth=0.6)
    for bar, f, p in zip(bars, fstats, pvals):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.08,
            f"F={f:.3f}\n顯著性 {p:.3g}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.axhline(3.84, color="grey", linestyle="--", linewidth=0.8,
               label="0.05 critical F (~3.84)")
    ax.set_ylabel("Granger F-stat")
    ax.set_title("K478：Granger 因果檢驗 — 三種 entropy 對 RV 的因果訊號都很弱")
    ax.set_ylim(0, max(fstats) * 1.5 + 0.5)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(axis="y", alpha=0.25)
    _save(fig, "k478_granger_summary.png")


if __name__ == "__main__":
    fig_qlike()
    fig_dm()
    fig_granger()
