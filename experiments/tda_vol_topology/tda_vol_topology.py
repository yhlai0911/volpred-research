"""
K131: Topological Data Analysis of Volatility Regimes
[提出: Gemini G2, 執行: Claude]

Treat volatility as a dynamical system and study its topological structure
in multi-dimensional space using Persistent Homology.

Questions:
1. Do topological features (loops, connected components) carry predictive
   information about future realized volatility?
2. Are there topological early-warning signals before market crashes?
3. Does TDA add information beyond what VIX already provides?
"""

import numpy as np
import pandas as pd
import yfinance as yf
from ripser import ripser
from scipy import stats
from scipy.spatial.distance import pdist, squareform
import warnings
import json
import os
from datetime import datetime

warnings.filterwarnings("ignore")

# ============================================================
# 1. DATA LOADING
# ============================================================
print("=" * 70)
print("K131: Topological Data Analysis of Volatility Regimes")
print("=" * 70)

# Download SPY + VIX
print("\n[1] Loading data from yfinance ...")
spy = yf.download("SPY", start="2006-01-01", end="2025-01-01", progress=False)
vix = yf.download("^VIX", start="2006-01-01", end="2025-01-01", progress=False)

# Handle multi-level columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Merge
df = pd.DataFrame({
    "spy_close": spy["Close"],
    "vix": vix["Close"],
})
df = df.dropna()

# Compute features
df["spy_ret"] = np.log(df["spy_close"] / df["spy_close"].shift(1))
df["vix_change"] = df["vix"].pct_change()
df["rv22"] = df["spy_ret"].rolling(22).std() * np.sqrt(252) * 100  # annualized %
df["rv22_fwd"] = df["rv22"].shift(-22)  # forward 22-day RV for prediction
df = df.dropna()

print(f"   Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"   Observations: {len(df)}")
print(f"   VIX range: {df['vix'].min():.1f} - {df['vix'].max():.1f}")
print(f"   RV22 range: {df['rv22'].min():.1f}% - {df['rv22'].max():.1f}%")

# ============================================================
# 2. DEFINE EMBEDDINGS
# ============================================================
print("\n[2] Constructing volatility embeddings ...")

# Embedding A: (VIX, ΔVIX, RV22) — vol state space
emb_A = df[["vix", "vix_change", "rv22"]].values.copy()
# Standardize each dimension
for j in range(emb_A.shape[1]):
    mu, sd = emb_A[:, j].mean(), emb_A[:, j].std()
    emb_A[:, j] = (emb_A[:, j] - mu) / sd

# Embedding B: Time-delay embedding (VIX_t, VIX_{t-5}, VIX_{t-22})
vix_vals = df["vix"].values
emb_B_raw = np.column_stack([
    vix_vals[22:],
    vix_vals[17:-5],
    vix_vals[:-22],
])
# Standardize
for j in range(emb_B_raw.shape[1]):
    mu, sd = emb_B_raw[:, j].mean(), emb_B_raw[:, j].std()
    emb_B_raw[:, j] = (emb_B_raw[:, j] - mu) / sd

print(f"   Embedding A (VIX, ΔVIX, RV22): shape {emb_A.shape}")
print(f"   Embedding B (VIX_t, VIX_t-5, VIX_t-22): shape {emb_B_raw.shape}")

# ============================================================
# 3. SLIDING WINDOW PERSISTENT HOMOLOGY
# ============================================================
print("\n[3] Computing sliding-window Persistent Homology ...")
print("    (window=252 days, step=5 days, this may take a few minutes)")

WINDOW = 252
STEP = 5
MAX_DIM = 1   # H0 and H1
MAX_PTS = 200  # subsample within each window for speed

def compute_topo_features(point_cloud, maxdim=1):
    """Compute topological features from a point cloud using Ripser."""
    n = point_cloud.shape[0]

    # Subsample if too many points
    if n > MAX_PTS:
        idx = np.random.choice(n, MAX_PTS, replace=False)
        idx.sort()
        point_cloud = point_cloud[idx]

    # Run Ripser
    result = ripser(point_cloud, maxdim=maxdim, thresh=3.0)
    diagrams = result["dgms"]

    features = {}
    for dim in range(maxdim + 1):
        dgm = diagrams[dim]
        # Remove infinite death points
        finite = dgm[np.isfinite(dgm[:, 1])]

        if len(finite) == 0:
            features[f"H{dim}_total_pers"] = 0.0
            features[f"H{dim}_max_pers"] = 0.0
            features[f"H{dim}_mean_pers"] = 0.0
            features[f"H{dim}_count"] = 0
            features[f"H{dim}_entropy"] = 0.0
            continue

        lifetimes = finite[:, 1] - finite[:, 0]
        lifetimes = lifetimes[lifetimes > 0]

        if len(lifetimes) == 0:
            features[f"H{dim}_total_pers"] = 0.0
            features[f"H{dim}_max_pers"] = 0.0
            features[f"H{dim}_mean_pers"] = 0.0
            features[f"H{dim}_count"] = 0
            features[f"H{dim}_entropy"] = 0.0
            continue

        features[f"H{dim}_total_pers"] = np.sum(lifetimes)
        features[f"H{dim}_max_pers"] = np.max(lifetimes)
        features[f"H{dim}_mean_pers"] = np.mean(lifetimes)
        features[f"H{dim}_count"] = len(lifetimes)

        # Persistence entropy
        probs = lifetimes / lifetimes.sum()
        probs = probs[probs > 0]
        features[f"H{dim}_entropy"] = -np.sum(probs * np.log(probs))

    return features

# Run sliding window on Embedding A
np.random.seed(42)
dates_A = df.index.values
topo_records = []

n_windows = (len(emb_A) - WINDOW) // STEP + 1
print(f"    Total windows: {n_windows}")

for i in range(0, len(emb_A) - WINDOW, STEP):
    window_data = emb_A[i:i + WINDOW]
    window_end_date = dates_A[i + WINDOW - 1]

    # Corresponding VIX and RV at window end
    idx_end = i + WINDOW - 1
    vix_end = df["vix"].iloc[idx_end]
    rv22_end = df["rv22"].iloc[idx_end]
    rv22_fwd_end = df["rv22_fwd"].iloc[idx_end] if idx_end < len(df) else np.nan

    feats = compute_topo_features(window_data, maxdim=MAX_DIM)
    feats["date"] = window_end_date
    feats["vix"] = vix_end
    feats["rv22"] = rv22_end
    feats["rv22_fwd"] = rv22_fwd_end

    topo_records.append(feats)

    if (len(topo_records)) % 100 == 0:
        print(f"    ... {len(topo_records)}/{n_windows} windows done")

topo_df = pd.DataFrame(topo_records)
topo_df["date"] = pd.to_datetime(topo_df["date"])
topo_df = topo_df.set_index("date")
topo_df = topo_df.dropna(subset=["rv22_fwd"])

print(f"    Completed: {len(topo_df)} windows with valid forward RV")

# ============================================================
# 3b. ALSO RUN ON EMBEDDING B (time-delay)
# ============================================================
print("\n[3b] Computing PH for Embedding B (time-delay) ...")

dates_B = df.index.values[22:]  # offset by 22 for time-delay
topo_records_B = []

for i in range(0, len(emb_B_raw) - WINDOW, STEP):
    window_data = emb_B_raw[i:i + WINDOW]
    window_end_date = dates_B[i + WINDOW - 1]

    idx_end = i + WINDOW - 1 + 22  # offset
    if idx_end >= len(df):
        continue
    vix_end = df["vix"].iloc[idx_end]
    rv22_fwd_end = df["rv22_fwd"].iloc[idx_end] if idx_end < len(df) else np.nan

    feats = compute_topo_features(window_data, maxdim=MAX_DIM)
    feats["date"] = window_end_date
    feats["vix"] = vix_end
    feats["rv22_fwd"] = rv22_fwd_end

    topo_records_B.append(feats)

topo_df_B = pd.DataFrame(topo_records_B)
topo_df_B["date"] = pd.to_datetime(topo_df_B["date"])
topo_df_B = topo_df_B.set_index("date")
topo_df_B = topo_df_B.dropna(subset=["rv22_fwd"])

print(f"    Completed: {len(topo_df_B)} windows")

# ============================================================
# 4. PREDICTIVE ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("[4] Predictive Analysis: Topological Features → Future RV")
print("=" * 70)

topo_features = [
    "H0_total_pers", "H0_max_pers", "H0_entropy",
    "H1_total_pers", "H1_max_pers", "H1_mean_pers", "H1_count", "H1_entropy",
]

print("\n--- Embedding A: (VIX, ΔVIX, RV22) ---")
print(f"{'Feature':<20} {'r(fwd_RV)':<12} {'p-value':<12} {'partial_r':<12} {'partial_p':<12}")
print("-" * 68)

results_A = {}
for feat in topo_features:
    if feat not in topo_df.columns:
        continue

    x = topo_df[feat].values
    y = topo_df["rv22_fwd"].values
    v = topo_df["vix"].values

    # Raw correlation
    r, p = stats.pearsonr(x, y)

    # Partial correlation controlling for VIX
    # partial_r(X,Y|Z) = (r_XY - r_XZ * r_YZ) / sqrt((1-r_XZ^2)(1-r_YZ^2))
    r_xz, _ = stats.pearsonr(x, v)
    r_yz, _ = stats.pearsonr(y, v)

    numer = r - r_xz * r_yz
    denom = np.sqrt((1 - r_xz**2) * (1 - r_yz**2))
    partial_r = numer / denom if denom > 0 else 0

    # Partial correlation p-value (approximate)
    n = len(x)
    t_stat = partial_r * np.sqrt((n - 3) / (1 - partial_r**2)) if abs(partial_r) < 1 else 0
    partial_p = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 3))

    print(f"{feat:<20} {r:>8.4f}    {p:>10.2e}  {partial_r:>8.4f}    {partial_p:>10.2e}")
    results_A[feat] = {"r": r, "p": p, "partial_r": partial_r, "partial_p": partial_p}

# VIX baseline
r_vix, p_vix = stats.pearsonr(topo_df["vix"].values, topo_df["rv22_fwd"].values)
print(f"\n{'VIX (baseline)':<20} {r_vix:>8.4f}    {p_vix:>10.2e}")

print("\n--- Embedding B: (VIX_t, VIX_{t-5}, VIX_{t-22}) ---")
print(f"{'Feature':<20} {'r(fwd_RV)':<12} {'p-value':<12}")
print("-" * 44)

results_B = {}
for feat in topo_features:
    if feat not in topo_df_B.columns:
        continue
    x = topo_df_B[feat].values
    y = topo_df_B["rv22_fwd"].values
    r, p = stats.pearsonr(x, y)
    print(f"{feat:<20} {r:>8.4f}    {p:>10.2e}")
    results_B[feat] = {"r": r, "p": p}

r_vix_B, p_vix_B = stats.pearsonr(topo_df_B["vix"].values, topo_df_B["rv22_fwd"].values)
print(f"\n{'VIX (baseline)':<20} {r_vix_B:>8.4f}    {p_vix_B:>10.2e}")

# ============================================================
# 5. CRISIS ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("[5] Crisis Topological Analysis")
print("=" * 70)

# Define crisis periods (pre-crisis = 6 months before)
crises = {
    "GFC (2008)": {
        "pre": ("2007-06-01", "2007-12-31"),
        "during": ("2008-09-01", "2009-03-31"),
    },
    "COVID (2020)": {
        "pre": ("2019-09-01", "2020-02-15"),
        "during": ("2020-02-16", "2020-05-31"),
    },
    "VIXpocalypse (2018)": {
        "pre": ("2017-06-01", "2017-12-31"),
        "during": ("2018-01-15", "2018-04-30"),
    },
    "Taper Tantrum (2013)": {
        "pre": ("2012-09-01", "2013-04-30"),
        "during": ("2013-05-01", "2013-09-30"),
    },
}

# Normal period baseline
normal_mask = (topo_df.index >= "2012-01-01") & (topo_df.index <= "2017-06-01")
normal_data = topo_df[normal_mask]

print(f"\nNormal period baseline (2012-2017H1): {len(normal_data)} windows")
for feat in ["H1_total_pers", "H1_max_pers", "H1_count", "H1_entropy"]:
    if feat in normal_data.columns:
        mu = normal_data[feat].mean()
        sd = normal_data[feat].std()
        print(f"  {feat}: mean={mu:.3f}, std={sd:.3f}")

print()
for crisis_name, periods in crises.items():
    print(f"\n--- {crisis_name} ---")
    for phase, (start, end) in periods.items():
        mask = (topo_df.index >= start) & (topo_df.index <= end)
        subset = topo_df[mask]
        if len(subset) == 0:
            print(f"  {phase}: no data in window")
            continue

        print(f"  {phase} ({start} to {end}): {len(subset)} windows")
        for feat in ["H1_total_pers", "H1_max_pers", "H1_count", "H1_entropy"]:
            if feat not in subset.columns:
                continue
            val = subset[feat].mean()
            # Z-score relative to normal
            normal_mu = normal_data[feat].mean()
            normal_sd = normal_data[feat].std()
            z = (val - normal_mu) / normal_sd if normal_sd > 0 else 0
            print(f"    {feat}: mean={val:.3f} (z={z:+.2f})")

# ============================================================
# 6. REGIME CLASSIFICATION USING TOPOLOGICAL FEATURES
# ============================================================
print("\n" + "=" * 70)
print("[6] Regime Classification via Topological Features")
print("=" * 70)

# Classify VIX regimes
topo_df["vix_regime"] = pd.cut(
    topo_df["vix"],
    bins=[0, 15, 20, 25, 100],
    labels=["Low (<15)", "Medium (15-20)", "High (20-25)", "Crisis (>25)"],
)

print("\nTopological features by VIX regime:")
print(f"{'Regime':<18} {'N':<6} {'H1_total':<10} {'H1_max':<10} {'H1_count':<10} {'H1_entropy':<12}")
print("-" * 66)

for regime in ["Low (<15)", "Medium (15-20)", "High (20-25)", "Crisis (>25)"]:
    sub = topo_df[topo_df["vix_regime"] == regime]
    if len(sub) == 0:
        continue
    print(f"{regime:<18} {len(sub):<6} "
          f"{sub['H1_total_pers'].mean():<10.3f} "
          f"{sub['H1_max_pers'].mean():<10.3f} "
          f"{sub['H1_count'].mean():<10.1f} "
          f"{sub['H1_entropy'].mean():<12.3f}")

# Kruskal-Wallis test: does H1_total_pers differ across regimes?
groups = [topo_df[topo_df["vix_regime"] == r]["H1_total_pers"].dropna().values
          for r in ["Low (<15)", "Medium (15-20)", "High (20-25)", "Crisis (>25)"]
          if len(topo_df[topo_df["vix_regime"] == r]) > 0]
if len(groups) >= 2:
    kw_stat, kw_p = stats.kruskal(*groups)
    print(f"\nKruskal-Wallis test (H1_total_pers across regimes): H={kw_stat:.2f}, p={kw_p:.2e}")

# ============================================================
# 7. INCREMENTAL PREDICTIVE POWER (BEYOND VIX)
# ============================================================
print("\n" + "=" * 70)
print("[7] Incremental Predictive Power Beyond VIX")
print("=" * 70)

# Multiple regression: rv22_fwd ~ VIX + H1_total_pers + H1_max_pers
from numpy.linalg import lstsq

y = topo_df["rv22_fwd"].values
X_vix = np.column_stack([np.ones(len(y)), topo_df["vix"].values])
X_full = np.column_stack([
    np.ones(len(y)),
    topo_df["vix"].values,
    topo_df["H1_total_pers"].values,
    topo_df["H1_max_pers"].values,
    topo_df["H1_entropy"].values,
])

# R-squared for VIX-only model
beta_vix, _, _, _ = lstsq(X_vix, y, rcond=None)
y_hat_vix = X_vix @ beta_vix
ss_res_vix = np.sum((y - y_hat_vix) ** 2)
ss_tot = np.sum((y - y.mean()) ** 2)
r2_vix = 1 - ss_res_vix / ss_tot

# R-squared for full model
beta_full, _, _, _ = lstsq(X_full, y, rcond=None)
y_hat_full = X_full @ beta_full
ss_res_full = np.sum((y - y_hat_full) ** 2)
r2_full = 1 - ss_res_full / ss_tot

# F-test for incremental R²
n = len(y)
p_restricted = X_vix.shape[1]
p_full = X_full.shape[1]
df1 = p_full - p_restricted
df2 = n - p_full
f_stat = ((ss_res_vix - ss_res_full) / df1) / (ss_res_full / df2)
f_pval = 1 - stats.f.cdf(f_stat, df1, df2)

print(f"\nModel: RV22_fwd ~ predictors")
print(f"  VIX only:           R² = {r2_vix:.4f}")
print(f"  VIX + TDA features: R² = {r2_full:.4f}")
print(f"  ΔR²:                     {r2_full - r2_vix:.4f}")
print(f"  F-test:             F({df1},{df2}) = {f_stat:.2f}, p = {f_pval:.2e}")

# ============================================================
# 8. TOPOLOGICAL EARLY WARNING: PRE-CRASH BEHAVIOR
# ============================================================
print("\n" + "=" * 70)
print("[8] Topological Early Warning Signals")
print("=" * 70)

# For each crisis, check if H1 features spike BEFORE the crash
print("\nH1_total_pers percentile rank in the 6 months before each crash:")
all_h1 = topo_df["H1_total_pers"].values

for crisis_name, periods in crises.items():
    pre_start, pre_end = periods["pre"]
    during_start, during_end = periods["during"]

    pre_mask = (topo_df.index >= pre_start) & (topo_df.index <= pre_end)
    during_mask = (topo_df.index >= during_start) & (topo_df.index <= during_end)

    pre_vals = topo_df.loc[pre_mask, "H1_total_pers"]
    during_vals = topo_df.loc[during_mask, "H1_total_pers"]

    if len(pre_vals) == 0 or len(during_vals) == 0:
        print(f"  {crisis_name}: insufficient data")
        continue

    pre_pct = stats.percentileofscore(all_h1, pre_vals.mean())
    during_pct = stats.percentileofscore(all_h1, during_vals.mean())

    print(f"  {crisis_name}:")
    print(f"    Pre-crisis:  mean H1_total = {pre_vals.mean():.3f} "
          f"(percentile: {pre_pct:.0f}%)")
    print(f"    During:      mean H1_total = {during_vals.mean():.3f} "
          f"(percentile: {during_pct:.0f}%)")

    # Was there a RISING TREND in H1 before the crash?
    if len(pre_vals) >= 5:
        x_time = np.arange(len(pre_vals))
        slope, intercept, r_val, p_val, _ = stats.linregress(x_time, pre_vals.values)
        print(f"    Pre-crisis trend: slope={slope:.4f}, r={r_val:.3f}, p={p_val:.3f}")

# ============================================================
# 9. PERSISTENCE LANDSCAPE DISTANCE (simplified)
# ============================================================
print("\n" + "=" * 70)
print("[9] Wasserstein-like Distance Between Regime Diagrams")
print("=" * 70)

# Compare persistence diagrams between regimes using bottleneck-like metric
# We'll use total persistence as a proxy for diagram complexity

low_h1 = topo_df[topo_df["vix_regime"] == "Low (<15)"]["H1_total_pers"].values
high_h1 = topo_df[topo_df["vix_regime"] == "Crisis (>25)"]["H1_total_pers"].values

if len(low_h1) > 0 and len(high_h1) > 0:
    ks_stat, ks_p = stats.ks_2samp(low_h1, high_h1)
    mw_stat, mw_p = stats.mannwhitneyu(low_h1, high_h1, alternative="two-sided")

    print(f"\nH1 Total Persistence: Low VIX vs Crisis VIX")
    print(f"  Low VIX:    mean={np.mean(low_h1):.3f}, median={np.median(low_h1):.3f}")
    print(f"  Crisis VIX: mean={np.mean(high_h1):.3f}, median={np.median(high_h1):.3f}")
    print(f"  KS test:    D={ks_stat:.3f}, p={ks_p:.2e}")
    print(f"  Mann-Whitney: U={mw_stat:.0f}, p={mw_p:.2e}")

# ============================================================
# 10. SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("[10] SUMMARY & CONCLUSIONS")
print("=" * 70)

# Key metrics for summary
best_raw_r = max(results_A.values(), key=lambda x: abs(x["r"]))
best_feat_raw = [k for k, v in results_A.items() if v == best_raw_r][0]
best_partial = max(results_A.values(), key=lambda x: abs(x["partial_r"]))
best_feat_partial = [k for k, v in results_A.items() if v == best_partial][0]

print(f"""
EXPERIMENT K131: Topological Data Analysis of Volatility Regimes
================================================================

Data: SPY + VIX, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}
Method: Persistent Homology on 3D volatility embeddings
        (252-day sliding window, step=5 days)

KEY FINDINGS:

1. PREDICTIVE POWER (raw correlation with future RV22):
   - Best TDA feature: {best_feat_raw} (r={best_raw_r['r']:.4f}, p={best_raw_r['p']:.2e})
   - VIX baseline: r={r_vix:.4f}
   - Verdict: {'TDA features have raw predictive power' if best_raw_r['p'] < 0.05 else 'TDA features have NO significant raw prediction'}

2. INCREMENTAL POWER BEYOND VIX:
   - Partial r (best): {best_feat_partial} = {best_partial['partial_r']:.4f} (p={best_partial['partial_p']:.2e})
   - ΔR² (VIX+TDA vs VIX-only): {r2_full - r2_vix:.4f}
   - F-test p-value: {f_pval:.2e}
   - Verdict: {'TDA adds significant incremental information' if f_pval < 0.05 else 'TDA does NOT add significant information beyond VIX'}

3. REGIME DISCRIMINATION:
   - KS test (low vs crisis): D={ks_stat:.3f}, p={ks_p:.2e}
   - Verdict: {'Topological structure differs across VIX regimes' if ks_p < 0.05 else 'No significant topological difference across regimes'}

4. EARLY WARNING:
   - Pre-crisis topological changes detected: check individual crisis results above.

5. METHODOLOGICAL NOTE:
   - TDA captures shape/structure of the volatility manifold
   - H0 = connected components (market fragmentation)
   - H1 = loops/cycles (recurrent volatility patterns)
   - Novel application to financial time series

CONCLUSION:
""")

# Dynamic conclusion
if f_pval < 0.05 and any(v["partial_p"] < 0.05 for v in results_A.values()):
    conclusion = ("TDA provides statistically significant incremental information "
                   "about future volatility beyond VIX. However, the ΔR² is small "
                   f"({r2_full - r2_vix:.4f}), suggesting limited practical value for "
                   "standalone prediction. The topological structure of volatility "
                   "does encode meaningful regime information.")
elif ks_p < 0.05:
    conclusion = ("TDA successfully discriminates between VIX regimes (the topological "
                   "structure of volatility IS different in crisis vs calm periods), "
                   "but this information is already captured by VIX itself. "
                   "TDA does NOT add predictive power beyond VIX for forecasting "
                   "future realized volatility. This is consistent with the "
                   "'VIX sufficient statistic' finding from Phase J.")
else:
    conclusion = ("TDA does not provide useful information beyond what VIX already "
                   "captures. The topological analysis is an interesting descriptive "
                   "tool but has no predictive advantage for volatility forecasting.")

print(conclusion)

# ============================================================
# 11. SAVE RESULTS
# ============================================================
print("\n[11] Saving results ...")

output = {
    "experiment_id": "K131",
    "title": "Topological Data Analysis of Volatility Regimes",
    "proposed_by": "Gemini G2",
    "executed_by": "Claude",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "method": "Persistent Homology (Vietoris-Rips complex) on 3D volatility embeddings",
    "data_period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    "n_observations": int(len(df)),
    "n_windows": int(len(topo_df)),
    "embedding_A": {
        "dims": "(VIX, ΔVIX, RV22)",
        "raw_correlations": {k: {"r": float(v["r"]), "p": float(v["p"])}
                             for k, v in results_A.items()},
        "partial_correlations": {k: {"partial_r": float(v["partial_r"]),
                                     "partial_p": float(v["partial_p"])}
                                  for k, v in results_A.items()},
    },
    "embedding_B": {
        "dims": "(VIX_t, VIX_t-5, VIX_t-22)",
        "correlations": {k: {"r": float(v["r"]), "p": float(v["p"])}
                          for k, v in results_B.items()},
    },
    "incremental_r2": {
        "r2_vix_only": float(r2_vix),
        "r2_vix_plus_tda": float(r2_full),
        "delta_r2": float(r2_full - r2_vix),
        "f_stat": float(f_stat),
        "f_pval": float(f_pval),
    },
    "regime_discrimination": {
        "ks_stat": float(ks_stat),
        "ks_pval": float(ks_p),
        "low_vix_H1_mean": float(np.mean(low_h1)),
        "crisis_vix_H1_mean": float(np.mean(high_h1)),
    },
    "vix_baseline_r": float(r_vix),
    "conclusion": conclusion,
    "verdict": "null" if f_pval >= 0.05 else "marginal",
}

out_path = "/Users/yhlai0911/Desktop/volpred-research/experiments/tda_vol_topology/tda_vol_topology_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"   Saved to {out_path}")

print("\n✓ K131 complete.")
