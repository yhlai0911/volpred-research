"""Generate plots for K1116 results."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT_DIR = Path(__file__).parent
with open(OUT_DIR / "k1116_results.json") as f:
    R = json.load(f)

# ============ Plot 1: IS vs OOS QLIKE (detect overfit) ============
fig, ax = plt.subplots(figsize=(9, 5.5))
models = list(R["is_oos_comparison"].keys())
is_q = [R["is_oos_comparison"][m]["IS_QLIKE"] for m in models]
oos_q = [R["is_oos_comparison"][m]["OOS_QLIKE"] for m in models]
# Clip M5 OOS for display (it blew up to ~60 - that's the point but kills scale)
oos_q_disp = [min(v, 0.0) for v in oos_q]
oos_q_blown = [v if v > 0 else None for v in oos_q]

x = np.arange(len(models))
w = 0.35
b1 = ax.bar(x - w / 2, is_q, w, label="IS QLIKE", color="#2e7db5")
b2 = ax.bar(x + w / 2, oos_q_disp, w, label="OOS QLIKE (clipped)", color="#e68a1e")
# annotate blown-up M5
for i, (m, v_blown) in enumerate(zip(models, oos_q_blown)):
    if v_blown is not None:
        ax.annotate(f"OOS QLIKE\n= +{v_blown:.1f}\n(OVERFIT)",
                    xy=(i + w / 2, 0), xytext=(i + w / 2, -2.0),
                    ha="center", va="bottom", fontsize=9, color="red",
                    arrowprops=dict(arrowstyle="->", color="red"))

ax.set_xticks(x)
ax.set_xticklabels(models, rotation=20, ha="right")
ax.set_ylabel("QLIKE loss (lower is better)")
ax.set_title("K1116: IS vs OOS QLIKE — Alternative Data Models\n(M5 catastrophically overfits; alt-data worsens OOS)")
ax.axhline(0, color="black", lw=0.5)
ax.legend()
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(OUT_DIR / "k1116_is_vs_oos_qlike.png", dpi=120, bbox_inches="tight")
print(f"Saved {OUT_DIR / 'k1116_is_vs_oos_qlike.png'}")
plt.close()

# ============ Plot 2: DM t-stats full OOS + regime ============
fig, ax = plt.subplots(figsize=(9, 5.5))
# Full OOS DM tests vs baseline
challengers_full = {}
for k, v in R["dm_tests_full_oos"].items():
    if v.get("t_stat") is None:
        continue
    name = k.split("_vs_")[1]
    challengers_full[name] = v["t_stat"]

# Regime: calm
challengers_calm = {}
calm = R["dm_tests_by_regime"].get("calm", {})
if isinstance(calm, dict) and calm.get("n", 0) >= 10:
    for k, v in calm.items():
        if isinstance(v, dict) and v.get("t_stat") is not None:
            name = k.split("_vs_")[1]
            challengers_calm[name] = v["t_stat"]

model_list = sorted(set(list(challengers_full.keys()) + list(challengers_calm.keys())))
x = np.arange(len(model_list))
w = 0.35
t_full = [challengers_full.get(m, 0) for m in model_list]
t_calm = [challengers_calm.get(m, 0) for m in model_list]

colors_full = ["#d62728" if t < -2 else ("#2ca02c" if t > 2 else "#7f7f7f") for t in t_full]
colors_calm = ["#d62728" if t < -2 else ("#2ca02c" if t > 2 else "#7f7f7f") for t in t_calm]

ax.bar(x - w / 2, t_full, w, label="Full OOS (n=170)", color=colors_full, alpha=0.85)
ax.bar(x + w / 2, t_calm, w, label="Calm regime (n=111)", color=colors_calm, alpha=0.85, hatch="//")
ax.axhline(2, color="green", linestyle="--", lw=1, label="Harvey +2 (challenger wins)")
ax.axhline(-2, color="red", linestyle="--", lw=1, label="Harvey -2 (baseline wins)")
ax.axhline(0, color="black", lw=0.5)
ax.set_xticks(x)
ax.set_xticklabels(model_list, rotation=20, ha="right")
ax.set_ylabel("DM-HLN t-stat  (vs M2_AR1_VIX baseline)")
ax.set_title("K1116: DM-HLN t-statistics — Alternative Data vs VIX Baseline\n(Negative = alt-data worse; all significant negatives = NULL confirmed)")
ax.legend(loc="lower left")
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(OUT_DIR / "k1116_dm_tstats.png", dpi=120, bbox_inches="tight")
print(f"Saved {OUT_DIR / 'k1116_dm_tstats.png'}")
plt.close()

# ============ Plot 3: BH-adj p-values + sign ============
fig, ax = plt.subplots(figsize=(9, 4.8))
kws = list(R["keyword_analysis_IS_M5"].keys())
bh_p = [R["keyword_analysis_IS_M5"][k]["p_value_bh_adj"] for k in kws]
coefs = [R["keyword_analysis_IS_M5"][k]["coef"] for k in kws]
colors = ["#2ca02c" if c > 0 else "#d62728" for c in coefs]

x = np.arange(len(kws))
ax.bar(x, -np.log10(bh_p), color=colors, alpha=0.85)
ax.axhline(-np.log10(0.10), color="gray", linestyle="--", lw=1, label="BH p=0.10 threshold")
ax.axhline(-np.log10(0.05), color="black", linestyle="--", lw=1, label="BH p=0.05 threshold")
ax.set_xticks(x)
ax.set_xticklabels([k.replace("_lag1", "") for k in kws], rotation=0)
ax.set_ylabel("-log10(BH-adjusted p-value)")
ax.set_title("K1116: IS BH-adjusted Significance (M5 joint model)\nGreen=positive coef, Red=negative coef")
ax.legend()
ax.grid(axis="y", alpha=0.3)
# Annotate sign
for i, (k, c) in enumerate(zip(kws, coefs)):
    sign = "+" if c > 0 else "-"
    ax.annotate(f"β={c:+.2e}", xy=(i, -np.log10(bh_p[i])), xytext=(0, 6), textcoords="offset points",
                ha="center", fontsize=8)
plt.tight_layout()
plt.savefig(OUT_DIR / "k1116_bh_significance.png", dpi=120, bbox_inches="tight")
print(f"Saved {OUT_DIR / 'k1116_bh_significance.png'}")
plt.close()

print("\nAll plots generated.")
