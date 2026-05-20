"""K678 plots for general-audience article.

Generates:
  (a) k678_corr_heatmap.png      — 14x14 correlation heatmap
  (b) k678_top_bottom_pairs.png  — top 5 + bottom 5 pair correlations bar
  (c) k678_market_avg.png        — cross-market vs same-market avg rho

All numbers read directly from k678_results.json (no fabrication).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
RESULTS = json.loads((ROOT / "k678_results.json").read_text())

# Set serif font for academic look (avoid CJK font issue by using English labels in heatmap axes)
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "figure.dpi": 110,
})

# ---- (a) 14x14 correlation heatmap ------------------------------------------
strategy_keys_ranked = [s["key"] for s in sorted(
    RESULTS["strategy_stats"], key=lambda s: s["avg_corr_with_others"]
)]
# Map key -> display label (short, market-tagged)
LABEL = {
    "taiwan_hybrid_leverage": "TW Hybrid Lev",
    "tz_tw_jp_5050": "TW+JP 50/50 TZ",
    "taiwan_spy_momentum": "TW Momentum",
    "vix_leading_guard": "VIX+Lead (TW)",
    "taiwan_8.63vix": "TW VT (0050)",
    "global_vt_tz": "Global VT+TZ",
    "fear_dca": "Fear DCA (US)",
    "piecewise_conservative": "Piecewise VT (US)",
    "adaptive_tier": "Adaptive Tier (US)",
    "slow_vt": "GARCH VT (SPY)",
    "simple_12vix": "12/VIX (SPY)",
    "recommended_5050": "50/50 SPY/GLD",
    "vix_cond_leverage": "VIX Cond Lev (US)",
    "risk_parity": "Risk Parity (US)",
}

cm = RESULTS["correlation_matrix"]
n = len(strategy_keys_ranked)
M = np.zeros((n, n))
for i, ki in enumerate(strategy_keys_ranked):
    for j, kj in enumerate(strategy_keys_ranked):
        M[i, j] = cm[ki][kj]

fig, ax = plt.subplots(figsize=(10.5, 9))
im = ax.imshow(M, cmap="RdYlBu_r", vmin=-0.1, vmax=1.0, aspect="auto")
ax.set_xticks(range(n))
ax.set_yticks(range(n))
labels = [LABEL[k] for k in strategy_keys_ranked]
ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
ax.set_yticklabels(labels, fontsize=9)
for i in range(n):
    for j in range(n):
        v = M[i, j]
        color = "white" if v > 0.65 or v < 0.0 else "black"
        ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                fontsize=7, color=color)
cbar = plt.colorbar(im, ax=ax, fraction=0.038, pad=0.04)
cbar.set_label("Pearson rho", fontsize=10)
ax.set_title(
    "K678: 14-Strategy Daily Return Correlation Matrix\n"
    "(rows/cols sorted by avg-rho; 2022-01-03 to 2026-03-27)",
    fontsize=12,
)
plt.tight_layout()
out_a = ROOT / "k678_corr_heatmap.png"
fig.savefig(out_a, dpi=140, bbox_inches="tight")
plt.close(fig)
print(f"WROTE {out_a}")

# ---- (b) Top 5 + Bottom 5 pair correlations ---------------------------------
pairs = RESULTS["all_pairs_sorted"]
top5 = pairs[:5]
bot5 = pairs[-5:][::-1]  # ascending → descending so smallest first stays at bottom

PAIR_LABEL = {
    ("slow_vt", "simple_12vix"): "GARCH VT (SPY) <-> 12/VIX (SPY)",
    ("piecewise_conservative", "adaptive_tier"): "Piecewise VT <-> Adaptive Tier",
    ("recommended_5050", "vix_cond_leverage"): "50/50 SPY/GLD <-> VIX Cond Lev",
    ("risk_parity", "recommended_5050"): "Risk Parity <-> 50/50 SPY/GLD",
    ("simple_12vix", "fear_dca"): "12/VIX (SPY) <-> Fear DCA",
    ("taiwan_8.63vix", "taiwan_hybrid_leverage"): "TW VT (0050) <-> TW Hybrid Lev",
    ("taiwan_spy_momentum", "taiwan_hybrid_leverage"): "TW Momentum <-> TW Hybrid Lev",
    ("taiwan_hybrid_leverage", "fear_dca"): "TW Hybrid Lev <-> Fear DCA (US)",
    ("risk_parity", "tz_tw_jp_5050"): "Risk Parity <-> TW+JP 50/50 TZ",
    ("tz_tw_jp_5050", "piecewise_conservative"): "TW+JP 50/50 TZ <-> Piecewise VT",
}


def _plabel(p):
    return PAIR_LABEL.get((p["strat1"], p["strat2"])) or f"{p['name1']} <-> {p['name2']}"


fig, axes = plt.subplots(1, 2, figsize=(13, 5.4))
# Top 5 (high rho)
ax1 = axes[0]
top_labels = [_plabel(p) for p in top5]
top_vals = [p["correlation"] for p in top5]
y = np.arange(len(top5))
bars1 = ax1.barh(y, top_vals, color="#c0392b", edgecolor="black", height=0.65)
ax1.set_yticks(y)
ax1.set_yticklabels(top_labels, fontsize=9)
ax1.invert_yaxis()
ax1.set_xlim(0, 1.05)
ax1.set_xlabel("Pearson rho")
ax1.set_title("Top 5 Most Correlated Pairs (suspect 'duplicate' strategies)")
for i, v in enumerate(top_vals):
    ax1.text(v + 0.01, i, f"{v:.4f}", va="center", fontsize=9)
ax1.axvline(0.9, ls="--", color="grey", lw=1)
ax1.grid(axis="x", alpha=0.3)

# Bottom 5 (low rho)
ax2 = axes[1]
bot_labels = [_plabel(p) for p in bot5]
bot_vals = [p["correlation"] for p in bot5]
y2 = np.arange(len(bot5))
bars2 = ax2.barh(y2, bot_vals, color="#2c7a7b", edgecolor="black", height=0.65)
ax2.set_yticks(y2)
ax2.set_yticklabels(bot_labels, fontsize=9)
ax2.invert_yaxis()
ax2.set_xlim(0, 0.18)
ax2.set_xlabel("Pearson rho")
ax2.set_title("Bottom 5 Least Correlated Pairs (genuine diversification)")
for i, v in enumerate(bot_vals):
    ax2.text(v + 0.003, i, f"{v:.4f}", va="center", fontsize=9)
ax2.grid(axis="x", alpha=0.3)

fig.suptitle(
    "K678: Strategy Pair Correlations — Top 5 vs Bottom 5 (out of 91 pairs)",
    fontsize=12,
)
plt.tight_layout()
out_b = ROOT / "k678_top_bottom_pairs.png"
fig.savefig(out_b, dpi=140, bbox_inches="tight")
plt.close(fig)
print(f"WROTE {out_b}")

# ---- (c) Cross-market vs same-market avg rho --------------------------------
# Tag each strategy as 'US' or 'TW' (or 'GLOBAL') by underlying market.
MKT = {
    "slow_vt": "US",
    "simple_12vix": "US",
    "risk_parity": "US",
    "recommended_5050": "US",
    "vix_cond_leverage": "US",
    "piecewise_conservative": "US",
    "adaptive_tier": "US",
    "fear_dca": "US",
    "taiwan_8.63vix": "TW",
    "taiwan_spy_momentum": "TW",
    "taiwan_hybrid_leverage": "TW",
    "vix_leading_guard": "TW",
    "tz_tw_jp_5050": "GLOBAL",
    "global_vt_tz": "GLOBAL",
}

us_us, tw_tw, cross = [], [], []
for p in pairs:
    m1, m2 = MKT[p["strat1"]], MKT[p["strat2"]]
    if m1 == "US" and m2 == "US":
        us_us.append(p["correlation"])
    elif m1 == "TW" and m2 == "TW":
        tw_tw.append(p["correlation"])
    elif {m1, m2} == {"US", "TW"}:
        cross.append(p["correlation"])
    # GLOBAL bucket excluded from this 3-way split (mixed exposure)

groups = {
    "Same-market: US-US": us_us,
    "Same-market: TW-TW": tw_tw,
    "Cross-market: US-TW": cross,
}
counts = {k: len(v) for k, v in groups.items()}
means = {k: float(np.mean(v)) for k, v in groups.items()}
medians = {k: float(np.median(v)) for k, v in groups.items()}

fig, ax = plt.subplots(figsize=(9.5, 5.5))
labels_c = list(groups.keys())
mean_vals = [means[k] for k in labels_c]
med_vals = [medians[k] for k in labels_c]
x = np.arange(len(labels_c))
w = 0.35
b1 = ax.bar(x - w / 2, mean_vals, w, label="Mean rho", color="#34495e", edgecolor="black")
b2 = ax.bar(x + w / 2, med_vals, w, label="Median rho", color="#7f8c8d", edgecolor="black")
ax.set_xticks(x)
ax.set_xticklabels([f"{k}\n(n={counts[k]} pairs)" for k in labels_c], fontsize=10)
ax.set_ylabel("Pearson rho")
ax.set_title("K678: Same-Market vs Cross-Market Pair Correlation\n"
             "Cross-market is the dominant diversification axis")
ax.axhline(RESULTS["summary"]["avg_correlation"], ls="--", color="red", lw=1,
           label=f"Overall avg rho = {RESULTS['summary']['avg_correlation']:.4f}")
ax.set_ylim(0, 0.75)
for bars in (b1, b2):
    for bar in bars:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, h + 0.015, f"{h:.3f}",
                ha="center", fontsize=9)
ax.grid(axis="y", alpha=0.3)
ax.legend(loc="upper right")
plt.tight_layout()
out_c = ROOT / "k678_market_avg.png"
fig.savefig(out_c, dpi=140, bbox_inches="tight")
plt.close(fig)
print(f"WROTE {out_c}")

# Echo summary stats so we can confirm before publish
print("\n=== group stats ===")
for k in groups:
    print(f"{k}: n={counts[k]} mean={means[k]:.4f} median={medians[k]:.4f}")
