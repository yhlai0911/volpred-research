"""
K1152 — Relative-magnitude θ_EAV cross-market analysis
        Absolute universality vs scale artifact test

Pure post-processing — no new MLE.
Reads results from K1145 (TW), K1147 (US), K1150 (JP).

Author: Claude (承接 K1150 next_tasks K1152)
Date: 2026-04-13
Random seed: 42 (all bootstrap computations)
"""

import json
import math
import os
import pathlib
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy import stats

np.random.seed(42)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = pathlib.Path(__file__).resolve().parent
# This script lives in a worktree; the prior experiment JSONs are in the main repo.
# Walk up from BASE to find the directory that contains experiments/k1145/
def find_repo_root(start: pathlib.Path) -> pathlib.Path:
    for parent in [start, *start.parents]:
        if (parent / "experiments" / "k1145").exists():
            return parent
    raise RuntimeError(f"Cannot find repo root (containing experiments/k1145) from {start}")

REPO = find_repo_root(BASE)
print(f"[K1152] Repo root: {REPO}")

K1145_JSON = REPO / "experiments" / "k1145" / "k1145_results.json"
K1147_JSON = REPO / "experiments" / "k1147" / "k1147_results.json"
K1150_JSON = REPO / "experiments" / "k1150" / "k1150_results.json"

OUT_DIR = BASE  # save PNGs and results here

# ---------------------------------------------------------------------------
# Load raw results
# ---------------------------------------------------------------------------
with open(K1145_JSON) as f:
    tw = json.load(f)
with open(K1147_JSON) as f:
    us = json.load(f)
with open(K1150_JSON) as f:
    jp = json.load(f)

print("[K1152] Loaded results from K1145 / K1147 / K1150")

# ---------------------------------------------------------------------------
# Step 1 — Extract θ_EAV point estimates and bootstrap draws
# ---------------------------------------------------------------------------
theta_abs = {
    "TW": tw["main_fit_eav_window_1"]["theta_eav"],
    "US": us["main_fit_eav_window_1"]["theta_eav"],
    "JP": jp["main_fit_eav_window_1"]["theta_eav"],
}

boot_draws = {
    "TW": np.array(tw["cluster_bootstrap"]["draws"]),
    "US": np.array(us["cluster_bootstrap"]["draws"]),
    "JP": np.array(jp["cluster_bootstrap"]["draws"]),
}

boot_se = {
    "TW": tw["cluster_bootstrap"]["se"],
    "US": us["cluster_bootstrap"]["se"],
    "JP": jp["cluster_bootstrap"]["se"],
}

print("[K1152] θ_EAV absolute:")
for m, v in theta_abs.items():
    print(f"  {m}: {v:.4e}  (bootstrap SE={boot_se[m]:.4e})")

# ---------------------------------------------------------------------------
# Step 2 — avg_σ² per market (empirical pooled: std_r^2 from panel_diagnostic)
# ---------------------------------------------------------------------------
# std_r is the standard deviation of log-returns across all stock×day obs
# std_r^2 is the empirical average conditional variance proxy for the pooled panel

avg_sigma2 = {
    "TW": tw["panel_diagnostic"]["std_r"] ** 2,
    "US": us["panel_diagnostic"]["std_r"] ** 2,
    "JP": jp["panel_diagnostic"]["std_r"] ** 2,
}

print("\n[K1152] avg_σ² (empirical std_r^2):")
for m, v in avg_sigma2.items():
    print(f"  {m}: {v:.4e}")

# ---------------------------------------------------------------------------
# Step 3 — θ_rel = θ_EAV / avg_σ²
# ---------------------------------------------------------------------------
theta_rel = {m: theta_abs[m] / avg_sigma2[m] for m in ["TW", "US", "JP"]}

# Propagate CI for θ_rel via bootstrap:
#   θ_rel_b = θ_EAV_b / avg_σ²  (avg_σ² treated as fixed — it's a data constant, not estimated)
# Delta-method SE: SE(θ_rel) = SE(θ_EAV) / avg_σ²
boot_draws_rel = {m: boot_draws[m] / avg_sigma2[m] for m in ["TW", "US", "JP"]}

theta_rel_boot_mean = {m: float(np.mean(boot_draws_rel[m])) for m in ["TW", "US", "JP"]}
theta_rel_boot_se = {m: float(np.std(boot_draws_rel[m])) for m in ["TW", "US", "JP"]}
theta_rel_ci95_lo = {m: float(np.percentile(boot_draws_rel[m], 2.5)) for m in ["TW", "US", "JP"]}
theta_rel_ci95_hi = {m: float(np.percentile(boot_draws_rel[m], 97.5)) for m in ["TW", "US", "JP"]}
theta_rel_t = {m: theta_rel[m] / theta_rel_boot_se[m] for m in ["TW", "US", "JP"]}

print("\n[K1152] θ_rel = θ_EAV / avg_σ²:")
print(f"{'Market':6s} {'θ_rel':>12s} {'boot_SE':>12s} {'t':>8s} {'CI_lo':>12s} {'CI_hi':>12s}")
for m in ["TW", "US", "JP"]:
    print(f"{m:6s} {theta_rel[m]:12.4f} {theta_rel_boot_se[m]:12.4f} "
          f"{theta_rel_t[m]:8.3f} {theta_rel_ci95_lo[m]:12.4f} {theta_rel_ci95_hi[m]:12.4f}")

# ---------------------------------------------------------------------------
# Step 4 — Wald test: H0: θ_rel_TW = θ_rel_US = θ_rel_JP
# Approach: parametric Wald using bootstrap SEs (independent markets → off-diagonal=0)
# Chi-square(2) under H0
# ---------------------------------------------------------------------------
# Construct contrasts:  δ1 = θ_rel_US - θ_rel_TW,  δ2 = θ_rel_JP - θ_rel_TW
delta1 = theta_rel["US"] - theta_rel["TW"]
delta2 = theta_rel["JP"] - theta_rel["TW"]

# Variance of contrasts (independence assumed across markets)
se_delta1_sq = theta_rel_boot_se["US"]**2 + theta_rel_boot_se["TW"]**2
se_delta2_sq = theta_rel_boot_se["JP"]**2 + theta_rel_boot_se["TW"]**2
# Covariance of δ1 and δ2 (share TW term)
cov_delta12 = theta_rel_boot_se["TW"]**2

# Wald matrix  W = [δ1, δ2]  @ Sigma^{-1} @ [δ1, δ2]'
Sigma = np.array([[se_delta1_sq, cov_delta12],
                  [cov_delta12,  se_delta2_sq]])
delta_vec = np.array([delta1, delta2])
Sigma_inv = np.linalg.inv(Sigma)
W_stat = float(delta_vec @ Sigma_inv @ delta_vec)
W_df = 2
W_p = float(1 - stats.chi2.cdf(W_stat, df=W_df))

print(f"\n[K1152] Wald test H0: θ_rel_TW = θ_rel_US = θ_rel_JP")
print(f"  δ1 (US-TW) = {delta1:.4f},  δ2 (JP-TW) = {delta2:.4f}")
print(f"  Wald χ²({W_df}) = {W_stat:.3f},  p = {W_p:.4f}")

# ---------------------------------------------------------------------------
# Step 5 — CI overlap check
# ---------------------------------------------------------------------------
def ci_overlap(lo1, hi1, lo2, hi2):
    return max(lo1, lo2) <= min(hi1, hi2)

overlap_TW_US = ci_overlap(theta_rel_ci95_lo["TW"], theta_rel_ci95_hi["TW"],
                            theta_rel_ci95_lo["US"], theta_rel_ci95_hi["US"])
overlap_TW_JP = ci_overlap(theta_rel_ci95_lo["TW"], theta_rel_ci95_hi["TW"],
                            theta_rel_ci95_lo["JP"], theta_rel_ci95_hi["JP"])
overlap_US_JP = ci_overlap(theta_rel_ci95_lo["US"], theta_rel_ci95_hi["US"],
                            theta_rel_ci95_lo["JP"], theta_rel_ci95_hi["JP"])

print(f"\n[K1152] 95% CI overlap:")
print(f"  TW ∩ US: {overlap_TW_US}")
print(f"  TW ∩ JP: {overlap_TW_JP}")
print(f"  US ∩ JP: {overlap_US_JP}")

# Magnitude ratio
ratio_US_TW_abs = theta_abs["US"] / theta_abs["TW"]
ratio_JP_TW_abs = theta_abs["JP"] / theta_abs["TW"]
ratio_US_TW_rel = theta_rel["US"] / theta_rel["TW"]
ratio_JP_TW_rel = theta_rel["JP"] / theta_rel["TW"]

print(f"\n[K1152] Magnitude ratios (vs TW):")
print(f"  Absolute θ_EAV: US/TW={ratio_US_TW_abs:.3f}, JP/TW={ratio_JP_TW_abs:.3f}")
print(f"  Relative θ_rel: US/TW={ratio_US_TW_rel:.3f}, JP/TW={ratio_JP_TW_rel:.3f}")

# ---------------------------------------------------------------------------
# Step 6 — Permutation/bootstrap test of θ_rel equality
# Use the bootstrap draws to test H0: θ_rel equal across markets via bootstrap Wald
# ---------------------------------------------------------------------------
n_boot = min(len(boot_draws_rel["TW"]), len(boot_draws_rel["US"]), len(boot_draws_rel["JP"]))
# Observed Wald stat already computed above as W_stat
# Bootstrap distribution: resample draws jointly (same index) → compute Wald stat each time
# Since draws are independent bootstrap samples (each market resampled independently),
# we can pair them by index i
boot_Wald = []
for i in range(n_boot):
    d1_b = boot_draws_rel["US"][i] - boot_draws_rel["TW"][i]
    d2_b = boot_draws_rel["JP"][i] - boot_draws_rel["TW"][i]
    # Under H0, center at observed means
    d1_centered = d1_b - delta1
    d2_centered = d2_b - delta2
    dvec_b = np.array([d1_centered, d2_centered])
    W_b = float(dvec_b @ Sigma_inv @ dvec_b)
    boot_Wald.append(W_b)

boot_Wald = np.array(boot_Wald)
boot_Wald_p = float(np.mean(boot_Wald >= W_stat))
print(f"\n[K1152] Bootstrap Wald p-value (H0: θ_rel equal): {boot_Wald_p:.4f}")

# ---------------------------------------------------------------------------
# Step 7 — Summary verdict
# CI overlap interpretation
# ---------------------------------------------------------------------------
all_ci_overlap = overlap_TW_US and overlap_TW_JP and overlap_US_JP
if W_p > 0.05 and all_ci_overlap:
    verdict = "SCALE_ADJUSTED_UNIVERSAL"
    verdict_desc = "θ_rel 三市場 CI 全部重疊，Wald p > 0.05 → scale-adjusted universal"
elif W_p < 0.05 and not all_ci_overlap:
    verdict = "MARKET_SPECIFIC_AFTER_SCALING"
    verdict_desc = "θ_rel 三市場 Wald p < 0.05，部分 CI 不重疊 → 市場特性在 scaling 後仍有差異"
else:
    verdict = "PARTIAL_CONVERGENCE"
    verdict_desc = "部分重疊或 Wald 邊界顯著"

print(f"\n[K1152] Verdict: {verdict}")
print(f"  {verdict_desc}")

# ---------------------------------------------------------------------------
# Step 8 — Figures
# ---------------------------------------------------------------------------
MARKETS = ["TW", "US", "JP"]
colors = {"TW": "#2196F3", "US": "#F44336", "JP": "#4CAF50"}
labels = {"TW": "台灣 (K1145\nN=31)", "US": "美國 (K1147\nN=30)", "JP": "日本 (K1150\nN=30)"}

# --- Figure 1: Absolute vs Relative side-by-side ---
fig, axes = plt.subplots(1, 2, figsize=(12, 5.5))
fig.suptitle("K1152 — EAV Effect: Absolute vs Scale-Adjusted (θ/σ²)",
             fontsize=14, fontweight="bold", y=1.01)

# Panel A: Absolute θ_EAV
ax = axes[0]
x = np.arange(3)
vals_abs = [theta_abs[m] * 1e5 for m in MARKETS]  # scale to ×1e-5 for readability
lo_abs = [(theta_abs[m] - 1.96 * boot_se[m]) * 1e5 for m in MARKETS]
hi_abs = [(theta_abs[m] + 1.96 * boot_se[m]) * 1e5 for m in MARKETS]
bars_abs = ax.bar(x, vals_abs, color=[colors[m] for m in MARKETS], alpha=0.85,
                   width=0.55, edgecolor="black", linewidth=0.8)
for xi, lo, hi in zip(x, lo_abs, hi_abs):
    ax.plot([xi, xi], [lo, hi], color="black", linewidth=2.0, zorder=5)
    ax.plot([xi - 0.12, xi + 0.12], [lo, lo], color="black", linewidth=1.5, zorder=5)
    ax.plot([xi - 0.12, xi + 0.12], [hi, hi], color="black", linewidth=1.5, zorder=5)

ax.set_xticks(x)
ax.set_xticklabels([labels[m] for m in MARKETS], fontsize=10)
ax.set_ylabel("θ_EAV (×1e⁻⁵)", fontsize=11)
ax.set_title("(A) Absolute θ_EAV\n(raw estimation units)", fontsize=11)
ax.axhline(0, color="gray", linestyle="--", linewidth=0.8)
ax.tick_params(axis="y", labelsize=9)

# Add value annotations
for xi, v in zip(x, vals_abs):
    ax.text(xi, v + max(vals_abs) * 0.03, f"{v:.2f}", ha="center", va="bottom",
            fontsize=10, fontweight="bold")

ax.set_ylim(bottom=0, top=max(hi_abs) * 1.25)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

# Panel B: Relative θ_rel = θ_EAV / avg_σ²
ax = axes[1]
vals_rel = [theta_rel[m] for m in MARKETS]
lo_rel_arr = [theta_rel_ci95_lo[m] for m in MARKETS]
hi_rel_arr = [theta_rel_ci95_hi[m] for m in MARKETS]
bars_rel = ax.bar(x, vals_rel, color=[colors[m] for m in MARKETS], alpha=0.85,
                   width=0.55, edgecolor="black", linewidth=0.8)
for xi, lo, hi in zip(x, lo_rel_arr, hi_rel_arr):
    ax.plot([xi, xi], [lo, hi], color="black", linewidth=2.0, zorder=5)
    ax.plot([xi - 0.12, xi + 0.12], [lo, lo], color="black", linewidth=1.5, zorder=5)
    ax.plot([xi - 0.12, xi + 0.12], [hi, hi], color="black", linewidth=1.5, zorder=5)

ax.set_xticks(x)
ax.set_xticklabels([labels[m] for m in MARKETS], fontsize=10)
ax.set_ylabel("θ_EAV / avg_σ²  (scale-free)", fontsize=11)
ax.set_title(f"(B) Relative θ_rel = θ_EAV / σ²\nWald χ²(2)={W_stat:.2f}, p={W_p:.3f}", fontsize=11)
ax.axhline(0, color="gray", linestyle="--", linewidth=0.8)
ax.tick_params(axis="y", labelsize=9)

for xi, v in zip(x, vals_rel):
    ax.text(xi, v + max(vals_rel) * 0.03, f"{v:.3f}", ha="center", va="bottom",
            fontsize=10, fontweight="bold")

ax.set_ylim(bottom=0, top=max(hi_rel_arr) * 1.3)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

# Add overlap annotation
overlap_text = (
    f"95% CI Overlap:\n"
    f"TW∩US: {'✓' if overlap_TW_US else '✗'}  "
    f"TW∩JP: {'✓' if overlap_TW_JP else '✗'}  "
    f"US∩JP: {'✓' if overlap_US_JP else '✗'}"
)
ax.text(0.5, -0.18, overlap_text, transform=ax.transAxes, fontsize=9,
        ha="center", va="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8))

plt.tight_layout()
out1 = OUT_DIR / "k1152_abs_vs_rel_theta.png"
plt.savefig(out1, dpi=150, bbox_inches="tight")
plt.close()
print(f"[K1152] Saved: {out1}")

# --- Figure 2: Bootstrap distribution of θ_rel for each market + pairwise comparison ---
fig, axes = plt.subplots(1, 3, figsize=(14, 5))
fig.suptitle("K1152 — Bootstrap Distribution of θ_rel (scale-adjusted EAV effect)",
             fontsize=13, fontweight="bold", y=1.01)

for i, m in enumerate(MARKETS):
    ax = axes[i]
    draws_r = boot_draws_rel[m]
    ax.hist(draws_r, bins=25, color=colors[m], alpha=0.75, edgecolor="white",
            linewidth=0.5, density=True)
    ax.axvline(theta_rel[m], color="black", linewidth=2.0, linestyle="-", label=f"Point est = {theta_rel[m]:.3f}")
    ax.axvline(theta_rel_ci95_lo[m], color="black", linewidth=1.2, linestyle="--", label="95% CI")
    ax.axvline(theta_rel_ci95_hi[m], color="black", linewidth=1.2, linestyle="--")
    ax.axvline(0, color="red", linewidth=1.0, linestyle=":", alpha=0.7, label="θ_rel = 0")
    ax.set_title(f"{m}: θ_rel = {theta_rel[m]:.3f}\nt = {theta_rel_t[m]:.2f}, boot SE = {theta_rel_boot_se[m]:.4f}",
                 fontsize=10)
    ax.set_xlabel("θ_rel = θ_EAV / avg_σ²", fontsize=9)
    ax.set_ylabel("Density", fontsize=9)
    ax.legend(fontsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

plt.tight_layout()
out2 = OUT_DIR / "k1152_bootstrap_rel_distributions.png"
plt.savefig(out2, dpi=150, bbox_inches="tight")
plt.close()
print(f"[K1152] Saved: {out2}")

# ---------------------------------------------------------------------------
# Step 9 — Save results JSON
# ---------------------------------------------------------------------------
results = {
    "experiment_id": "K1152",
    "title": "Relative-magnitude θ_EAV cross-market analysis: absolute universality vs scale artifact",
    "proposer": "Claude (承接 K1150 next_tasks K1152)",
    "executor": "Claude",
    "timestamp_utc": "2026-04-13",
    "random_seed": 42,
    "data_source": "Post-processing of K1145 / K1147 / K1150 results JSONs (no new MLE)",
    "input_experiments": {
        "TW": "K1145",
        "US": "K1147",
        "JP": "K1150"
    },
    "markets": {
        "TW": {
            "theta_eav_abs": theta_abs["TW"],
            "avg_sigma2": avg_sigma2["TW"],
            "theta_rel": theta_rel["TW"],
            "theta_rel_boot_mean": theta_rel_boot_mean["TW"],
            "theta_rel_boot_se": theta_rel_boot_se["TW"],
            "theta_rel_t": theta_rel_t["TW"],
            "theta_rel_ci95_lo": theta_rel_ci95_lo["TW"],
            "theta_rel_ci95_hi": theta_rel_ci95_hi["TW"],
        },
        "US": {
            "theta_eav_abs": theta_abs["US"],
            "avg_sigma2": avg_sigma2["US"],
            "theta_rel": theta_rel["US"],
            "theta_rel_boot_mean": theta_rel_boot_mean["US"],
            "theta_rel_boot_se": theta_rel_boot_se["US"],
            "theta_rel_t": theta_rel_t["US"],
            "theta_rel_ci95_lo": theta_rel_ci95_lo["US"],
            "theta_rel_ci95_hi": theta_rel_ci95_hi["US"],
        },
        "JP": {
            "theta_eav_abs": theta_abs["JP"],
            "avg_sigma2": avg_sigma2["JP"],
            "theta_rel": theta_rel["JP"],
            "theta_rel_boot_mean": theta_rel_boot_mean["JP"],
            "theta_rel_boot_se": theta_rel_boot_se["JP"],
            "theta_rel_t": theta_rel_t["JP"],
            "theta_rel_ci95_lo": theta_rel_ci95_lo["JP"],
            "theta_rel_ci95_hi": theta_rel_ci95_hi["JP"],
        },
    },
    "wald_test": {
        "H0": "theta_rel_TW = theta_rel_US = theta_rel_JP",
        "delta1_US_minus_TW": float(delta1),
        "delta2_JP_minus_TW": float(delta2),
        "chi2_stat": float(W_stat),
        "df": int(W_df),
        "chi2_p_asymptotic": float(W_p),
        "bootstrap_p": float(boot_Wald_p),
    },
    "ci_overlap": {
        "TW_US": bool(overlap_TW_US),
        "TW_JP": bool(overlap_TW_JP),
        "US_JP": bool(overlap_US_JP),
        "all_overlap": bool(all_ci_overlap),
    },
    "magnitude_ratios": {
        "absolute": {
            "US_vs_TW": float(ratio_US_TW_abs),
            "JP_vs_TW": float(ratio_JP_TW_abs),
        },
        "relative": {
            "US_vs_TW": float(ratio_US_TW_rel),
            "JP_vs_TW": float(ratio_JP_TW_rel),
        }
    },
    "verdict": verdict,
    "verdict_description": verdict_desc,
    "figures": [
        str(out1.name),
        str(out2.name),
    ],
}

out_json = OUT_DIR / "k1152_results.json"
with open(out_json, "w") as f:
    json.dump(results, f, indent=2)
print(f"\n[K1152] Results saved: {out_json}")

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("K1152 FINAL SUMMARY")
print("=" * 60)
print(f"\nAbsolute θ_EAV × 1e5:")
print(f"  TW = {theta_abs['TW']*1e5:.3f},  US = {theta_abs['US']*1e5:.3f},  JP = {theta_abs['JP']*1e5:.3f}")
print(f"  Ratio US/TW = {ratio_US_TW_abs:.3f},  JP/TW = {ratio_JP_TW_abs:.3f}")
print(f"\nAvg σ² (empirical):")
print(f"  TW = {avg_sigma2['TW']:.4e},  US = {avg_sigma2['US']:.4e},  JP = {avg_sigma2['JP']:.4e}")
print(f"\nRelative θ_rel = θ_EAV / avg_σ²:")
print(f"  TW = {theta_rel['TW']:.4f} [{theta_rel_ci95_lo['TW']:.4f}, {theta_rel_ci95_hi['TW']:.4f}]")
print(f"  US = {theta_rel['US']:.4f} [{theta_rel_ci95_lo['US']:.4f}, {theta_rel_ci95_hi['US']:.4f}]")
print(f"  JP = {theta_rel['JP']:.4f} [{theta_rel_ci95_lo['JP']:.4f}, {theta_rel_ci95_hi['JP']:.4f}]")
print(f"  Ratio US/TW = {ratio_US_TW_rel:.3f},  JP/TW = {ratio_JP_TW_rel:.3f}")
print(f"\nWald test H0 (θ_rel equal): χ²(2) = {W_stat:.3f},  p = {W_p:.4f}")
print(f"Bootstrap Wald p = {boot_Wald_p:.4f}")
print(f"CI overlap: TW∩US={overlap_TW_US}, TW∩JP={overlap_TW_JP}, US∩JP={overlap_US_JP}")
print(f"\n>>> VERDICT: {verdict}")
print(f"    {verdict_desc}")
print("=" * 60)
