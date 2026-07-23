"""
K514 article charts — FOMC VIX-surprise IS vs OOS & Regime correlation
Saves to storage/charts/k514_*.png
"""

import json
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── paths ──────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_PATH = os.path.join(BASE_DIR, "experiments", "k514", "k514_fomc_surprise_results.json")
OUT_DIR = os.path.join(BASE_DIR, "storage", "charts")
os.makedirs(OUT_DIR, exist_ok=True)

with open(RESULTS_PATH) as f:
    R = json.load(f)

# ── shared style ──────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.labelsize": 12,
    "axes.titlesize": 13,
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
})

# ══════════════════════════════════════════════════════════════════════════
# Figure 1 — IS t-stat vs OOS DM t-stat
# ══════════════════════════════════════════════════════════════════════════
fig1, ax1 = plt.subplots(figsize=(7, 5))

is_t = R["regression_results"]["h21"]["vix_surprise_t_m2"]   # -8.18
oos_dm_t = R["oos_prediction"]["dm_t_surp_minus_base"]        # +3.89

labels = ["IS t-stat\n(OLS, h=21)", "OOS DM t-stat\n(surprise vs. baseline)"]
values = [is_t, oos_dm_t]
colors = ["#2ecc71" if v < 0 else "#e74c3c" for v in values]

bars = ax1.bar(labels, values, color=colors, width=0.45, edgecolor="white", linewidth=1.2)

# annotation labels on bars
for bar, val in zip(bars, values):
    ypos = val + (0.2 if val > 0 else -0.5)
    ax1.text(bar.get_x() + bar.get_width() / 2, ypos,
             f"{val:+.2f}", ha="center", va="bottom" if val > 0 else "top",
             fontsize=13, fontweight="bold",
             color=bar.get_facecolor())

ax1.axhline(0, color="#333333", linewidth=0.8)
ax1.axhline(1.96, color="#e74c3c", linewidth=1, linestyle="--", alpha=0.6)
ax1.axhline(-1.96, color="#2ecc71", linewidth=1, linestyle="--", alpha=0.6)

ax1.set_ylabel("t-statistic")
ax1.set_title("K514 — IS Strong Signal Does NOT Imply OOS Usefulness\n(h=21 days; Positive OOS DM t = surprise model is WORSE)", pad=12)

green_patch = mpatches.Patch(color="#2ecc71", label="IS: Significant signal (t=-8.18)")
red_patch   = mpatches.Patch(color="#e74c3c", label="OOS: Surprise significantly WORSE (DM t=+3.89)")
ax1.legend(handles=[green_patch, red_patch], loc="lower left", fontsize=10, framealpha=0.8)

ax1.set_ylim(min(values) * 1.25, max(values) * 1.4)
fig1.tight_layout()
out1 = os.path.join(OUT_DIR, "k514_is_vs_oos.png")
fig1.savefig(out1, dpi=150, bbox_inches="tight")
plt.close(fig1)
print(f"Saved: {out1}")

# ══════════════════════════════════════════════════════════════════════════
# Figure 2 — Regime corr(surprise, fwd_rv21) with p-value annotation
# ══════════════════════════════════════════════════════════════════════════
fig2, ax2 = plt.subplots(figsize=(8, 5))

sub = R["subsample_robustness"]
periods = [
    ("2005-2009\nGFC",     sub["2005-2009 (GFC)"]["corr_fwd21_r"],    sub["2005-2009 (GFC)"]["corr_fwd21_p"],    42),
    ("2010-2014\nRecovery",sub["2010-2014 (Recovery)"]["corr_fwd21_r"], sub["2010-2014 (Recovery)"]["corr_fwd21_p"], 40),
    ("2015-2019\nNormal+", sub["2015-2019 (Normal+)"]["corr_fwd21_r"],  sub["2015-2019 (Normal+)"]["corr_fwd21_p"],  40),
    ("2020-2025\nCOVID+",  sub["2020-2025 (COVID+)"]["corr_fwd21_r"],   sub["2020-2025 (COVID+)"]["corr_fwd21_p"],   43),
]

labels2 = [p[0] for p in periods]
corrs   = [p[1] for p in periods]
pvals   = [p[2] for p in periods]
ns      = [p[3] for p in periods]

bar_colors = []
for c, p in zip(corrs, pvals):
    if p < 0.05:
        bar_colors.append("#2ecc71" if c > 0 else "#e74c3c")
    else:
        bar_colors.append("#bdc3c7")

bars2 = ax2.bar(labels2, corrs, color=bar_colors, width=0.55, edgecolor="white", linewidth=1.2)

# p-value and N annotation above each bar
for bar, corr, p, n in zip(bars2, corrs, pvals, ns):
    xc = bar.get_x() + bar.get_width() / 2
    # p-value label
    if p < 0.01:
        plabel = f"p={p:.3f}**"
    elif p < 0.05:
        plabel = f"p={p:.3f}*"
    else:
        plabel = f"p={p:.2f} (ns)"
    yoff = 0.025 if corr >= 0 else -0.055
    va   = "bottom" if corr >= 0 else "top"
    ax2.text(xc, corr + yoff, plabel, ha="center", va=va, fontsize=9.5, color="#555555")
    # N label inside bar
    ax2.text(xc, corr / 2, f"N={n}", ha="center", va="center", fontsize=9, color="white", fontweight="bold")

ax2.axhline(0, color="#333333", linewidth=0.8)
ax2.set_ylabel("corr (VIX-surprise, fwd_rv21)")
ax2.set_title("K514 — Same Signal, Four Regimes, Four Different Stories\n( * p<0.05; ** p<0.01; grey = not significant )", pad=12)

sig_pos = mpatches.Patch(color="#2ecc71", label="Sig. positive corr (signal works)")
sig_neg = mpatches.Patch(color="#e74c3c", label="Sig. negative corr (signal reverses)")
insig   = mpatches.Patch(color="#bdc3c7", label="Not significant (signal fails)")
ax2.legend(handles=[sig_pos, sig_neg, insig], loc="upper left", fontsize=10, framealpha=0.8)

ax2.set_ylim(-0.6, 0.6)
fig2.tight_layout()
out2 = os.path.join(OUT_DIR, "k514_regime_corr.png")
fig2.savefig(out2, dpi=150, bbox_inches="tight")
plt.close(fig2)
print(f"Saved: {out2}")
