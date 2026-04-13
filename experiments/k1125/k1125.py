"""
K1125 - OFI x Lee-Mykland Jump Detection
========================================

Follow-up to K1124 (which found: |OFI| high -> next 5-min RV LOWER, a mean-reversion pattern).

**Hypothesis**: K1124 used diffusive RV as target. Jumps are discrete tail events with a
different mechanism: large |OFI| may reflect informed-trader filling orders, making a
jump in the NEXT bar more likely. This experiment tests whether |OFI| predicts jumps,
even when it fails to predict diffusive vol.

**Method**:
  1. Compute Lee-Mykland (2008) jump statistic L_t = |r_t| / sigma_hat_t per bar,
     where sigma_hat is rolling bipower variation (K=16 past returns, strictly past).
  2. Multi-test Gumbel-adjusted critical value at alpha=0.01.
  3. Target: jump_{t+1} in {0,1}.  Features from bar t only (no current-bar leak).
  4. Models:
       M1: P(jump_{t+1} | lag jump indicator)  -- baseline
       M2: + |OFI|_t
       M3: + signed OFI_t
       M4: + |OFI|_t x VIX_t interaction (regime)
  5. Strict OOS: IS 2017-2019, OOS 2020-2021.
  6. Metrics: AUC, Brier score, log-likelihood, with DM-style test on LL diffs.

**Safeguards (from error_log K1124):**
  - All features from bar t predicting jump at bar t+1 (no same-bar leak).
  - Day boundaries: sigma_hat recomputed per day (do not mix overnight).
  - Jump at first K bars of each day is NaN (insufficient history for BV).
  - Last bar of each day excluded (no t+1 in same day).
  - Fixed seed 42 for any random operations.

References:
  - Lee, S.S., Mykland, P.A. (2008). Jumps in Financial Markets: A New Nonparametric
    Test and Jump Dynamics. Review of Financial Studies 21(6), 2535-2563.
  - Cont, R., Kukanov, A., Stoikov, S. (2014). The Price Impact of Order Book Events.
    J Financial Econometrics 12(1), 47-88.
"""
import numpy as np
import pandas as pd
from pathlib import Path
import json
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler

np.random.seed(42)

ROOT = Path(__file__).parent
CACHE_PATH = ROOT / "_cache_bars_2017-01-01_2021-12-31.parquet"

# ============================================================
# 1. LOAD DATA
# ============================================================
print("=" * 70)
print("K1125 - OFI x Lee-Mykland Jump Detection")
print("=" * 70)
t0 = datetime.now()

df = pd.read_parquet(CACHE_PATH)
df = df.sort_values(["date", "bar"]).reset_index(drop=True)
print(f"Loaded {len(df):,} bars across {df['date'].nunique()} days")
print(f"Period: {df['date'].min()} to {df['date'].max()}")

# ============================================================
# 2. LEE-MYKLAND JUMP DETECTION (per day, strictly past window)
# ============================================================
print("\n[Step 2] Computing Lee-Mykland jump statistic per day...")
MU1 = np.sqrt(2.0 / np.pi)
K_WIN = 16

def compute_jumps_per_day(day_df: pd.DataFrame, K: int = K_WIN):
    """
    Per-day BV: sigma_hat_t uses strictly past returns r_{t-K},...,r_{t-1} (K returns).
    BV_hat = (1/mu1^2) * (1/(K-1)) * sum_{j=t-K+1}^{t-1} |r_{j-1}||r_j|
    (K-1 pair products from the K past returns; Lee-Mykland 2008 Appendix A.3 form.)
    """
    r = day_df["log_ret"].values
    n = len(r)
    sigma_hat = np.full(n, np.nan)
    abs_r = np.abs(r)
    pairs = abs_r[:-1] * abs_r[1:]  # pairs[p] = |r_p|*|r_{p+1}|, length n-1
    for t in range(K, n):
        # Cover returns r_{t-K},...,r_{t-1}: pair positions [t-K, t-2] (K-1 products)
        start = t - K
        stop = t - 1  # slice end-exclusive -> includes position t-2
        if start >= 0 and stop <= len(pairs):
            window_pairs = pairs[start:stop]
            if len(window_pairs) == K - 1:
                bv = window_pairs.sum() / ((K - 1) * MU1**2)
                sigma_hat[t] = np.sqrt(max(bv, 1e-16))
    L = abs_r / sigma_hat
    return sigma_hat, L

all_sigma = np.full(len(df), np.nan)
all_L = np.full(len(df), np.nan)
for date, idx in df.groupby("date").groups.items():
    idx_arr = np.array(idx)
    day_df = df.loc[idx_arr]
    sigma_hat, L = compute_jumps_per_day(day_df, K=K_WIN)
    all_sigma[idx_arr] = sigma_hat
    all_L[idx_arr] = L

df["sigma_hat"] = all_sigma
df["L_stat"] = all_L

n_valid_global = np.isfinite(all_L).sum()
alpha = 0.01
C_n = np.sqrt(2*np.log(n_valid_global)) - 0.5*(np.log(np.log(n_valid_global)) + np.log(4*np.pi)) / np.sqrt(2*np.log(n_valid_global))
S_n = 1.0 / np.sqrt(2*np.log(n_valid_global))
beta_n = -np.log(-np.log(1-alpha))
thresh_multi = C_n + S_n * beta_n
thresh_single = np.sqrt(2 * np.log(1.0 / 0.01))

print(f"  Valid L obs: {n_valid_global:,}")
print(f"  Multi-test threshold (Gumbel, alpha=0.01): {thresh_multi:.3f}")
print(f"  Single-test threshold (alpha=0.01): {thresh_single:.3f}")

df["jump_multi"] = (df["L_stat"] > thresh_multi).astype(int)
df.loc[~np.isfinite(df["L_stat"]), "jump_multi"] = -1
df["jump_single"] = (df["L_stat"] > thresh_single).astype(int)
df.loc[~np.isfinite(df["L_stat"]), "jump_single"] = -1

n_jump_multi = (df["jump_multi"] == 1).sum()
n_jump_single = (df["jump_single"] == 1).sum()
print(f"  Jumps (multi): {n_jump_multi} ({n_jump_multi/n_valid_global*100:.2f}%)")
print(f"  Jumps (single): {n_jump_single} ({n_jump_single/n_valid_global*100:.2f}%)")

df["jump"] = df["jump_multi"]

# ============================================================
# 3. BUILD FEATURE / TARGET (jump_{t+1} given features at t)
# ============================================================
print("\n[Step 3] Building features and targets...")

df["jump_next"] = -1
df["ofi_abs"] = df["ofi"].abs()

for date, gdf in df.groupby("date"):
    idx = gdf.index.values
    jumps = gdf["jump"].values
    jump_next = np.full(len(gdf), -1)
    jump_next[:-1] = jumps[1:]
    df.loc[idx, "jump_next"] = jump_next

valid_mask = (df["jump_next"].isin([0, 1])) & df["ofi"].notna() & df["log_ret"].notna()
valid_mask &= np.isfinite(df["L_stat"])

df_valid = df[valid_mask].copy().reset_index(drop=True)
print(f"  Valid bars for prediction: {len(df_valid):,}")
print(f"  Jump rate (target): {df_valid['jump_next'].mean()*100:.3f}%")

# ============================================================
# 4. LOAD VIX FOR REGIME INTERACTION
# ============================================================
print("\n[Step 4] Loading daily VIX...")
has_vix = False
try:
    import yfinance as yf
    vix = yf.download("^VIX", start="2016-12-01", end="2022-01-31", progress=False, auto_adjust=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix_df = vix[["Close"]].reset_index()
    vix_df.columns = ["date", "vix"]
    vix_df["date"] = pd.to_datetime(vix_df["date"]).dt.normalize()
    vix_df = vix_df.dropna().drop_duplicates("date").sort_values("date").reset_index(drop=True)
    vix_df["vix_lag1"] = vix_df["vix"].shift(1)
    vix_df["vix_lag1"] = vix_df["vix_lag1"].ffill()
    df_valid["date_norm"] = pd.to_datetime(df_valid["date"]).dt.normalize()
    df_valid = df_valid.merge(vix_df[["date","vix_lag1"]].rename(columns={"date":"date_norm"}),
                              on="date_norm", how="left")
    df_valid["vix_lag1"] = df_valid["vix_lag1"].ffill()
    vix_missing = df_valid["vix_lag1"].isna().sum()
    print(f"  VIX: {len(vix_df)} days, missing merge: {vix_missing}")
    has_vix = df_valid["vix_lag1"].notna().all()
except Exception as e:
    print(f"  VIX load failed: {e}")
    df_valid["vix_lag1"] = np.nan

# ============================================================
# 5. FEATURE MATRIX
# ============================================================
print("\n[Step 5] Building feature matrix...")
df_valid["jump_curr"] = df_valid["jump"].clip(lower=0)
df_valid["ofi_t"] = df_valid["ofi"]
df_valid["ofi_abs_t"] = df_valid["ofi"].abs()
df_valid["year"] = df_valid["date"].dt.year
# Note: vix_z must be standardized using IS-only stats to avoid OOS leakage.
# Compute after splitting so we can use IS mean/std only.
if has_vix:
    is_mask_tmp = df_valid["year"].isin([2017, 2018, 2019])
    vix_is_mean = df_valid.loc[is_mask_tmp, "vix_lag1"].mean()
    vix_is_std = df_valid.loc[is_mask_tmp, "vix_lag1"].std()
    df_valid["vix_z"] = (df_valid["vix_lag1"] - vix_is_mean) / vix_is_std
    df_valid["ofi_abs_vix"] = df_valid["ofi_abs_t"] * df_valid["vix_z"]
    print(f"  VIX z-scored using IS-only stats: mean={vix_is_mean:.2f}, std={vix_is_std:.2f}")
is_mask = df_valid["year"].isin([2017, 2018, 2019])
oos_mask = df_valid["year"].isin([2020, 2021])

print(f"  IS: {is_mask.sum():,}  OOS: {oos_mask.sum():,}")
print(f"  IS jump rate: {df_valid.loc[is_mask, 'jump_next'].mean()*100:.3f}%")
print(f"  OOS jump rate: {df_valid.loc[oos_mask, 'jump_next'].mean()*100:.3f}%")

# ============================================================
# 6. FIT LOGISTIC REGRESSION
# ============================================================
print("\n[Step 6] Fitting logistic regressions...")

y_is = df_valid.loc[is_mask, "jump_next"].values.astype(int)
y_oos = df_valid.loc[oos_mask, "jump_next"].values.astype(int)

def fit_predict(features_is, features_oos, y_is, y_oos, name):
    sc = StandardScaler()
    Xi = sc.fit_transform(features_is)
    Xo = sc.transform(features_oos)
    model = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs", random_state=42)
    model.fit(Xi, y_is)
    p_is = model.predict_proba(Xi)[:, 1]
    p_oos = model.predict_proba(Xo)[:, 1]
    eps = 1e-7
    p_is = np.clip(p_is, eps, 1-eps)
    p_oos = np.clip(p_oos, eps, 1-eps)
    return {
        "name": name,
        "n_features": int(features_is.shape[1]),
        "coefs": model.coef_[0].tolist(),
        "intercept": float(model.intercept_[0]),
        "auc_is": float(roc_auc_score(y_is, p_is) if len(np.unique(y_is))>1 else np.nan),
        "auc_oos": float(roc_auc_score(y_oos, p_oos) if len(np.unique(y_oos))>1 else np.nan),
        "brier_is": float(brier_score_loss(y_is, p_is)),
        "brier_oos": float(brier_score_loss(y_oos, p_oos)),
        "ll_is": float(-log_loss(y_is, p_is)),
        "ll_oos": float(-log_loss(y_oos, p_oos)),
        "p_oos": p_oos,
        "p_is": p_is,
    }

base_rate_is = y_is.mean()
p0_is = np.clip(np.full_like(y_is, base_rate_is, dtype=float), 1e-7, 1-1e-7)
p0_oos = np.clip(np.full_like(y_oos, base_rate_is, dtype=float), 1e-7, 1-1e-7)
M0 = {"name":"M0_constant", "n_features":0,
      "auc_is":0.5,"auc_oos":0.5,
      "brier_is":float(brier_score_loss(y_is,p0_is)),
      "brier_oos":float(brier_score_loss(y_oos,p0_oos)),
      "ll_is":float(-log_loss(y_is,p0_is)),
      "ll_oos":float(-log_loss(y_oos,p0_oos)),
      "p_oos":p0_oos, "p_is":p0_is}

M1 = fit_predict(df_valid.loc[is_mask, ["jump_curr"]].values,
                 df_valid.loc[oos_mask, ["jump_curr"]].values,
                 y_is, y_oos, "M1_lagjump")
M2 = fit_predict(df_valid.loc[is_mask, ["jump_curr","ofi_abs_t"]].values,
                 df_valid.loc[oos_mask, ["jump_curr","ofi_abs_t"]].values,
                 y_is, y_oos, "M2_lagjump_ofiabs")
M3 = fit_predict(df_valid.loc[is_mask, ["jump_curr","ofi_abs_t","ofi_t"]].values,
                 df_valid.loc[oos_mask, ["jump_curr","ofi_abs_t","ofi_t"]].values,
                 y_is, y_oos, "M3_lagjump_ofiabs_signed")
if has_vix:
    M4 = fit_predict(df_valid.loc[is_mask, ["jump_curr","ofi_abs_t","ofi_t","vix_z","ofi_abs_vix"]].values,
                     df_valid.loc[oos_mask, ["jump_curr","ofi_abs_t","ofi_t","vix_z","ofi_abs_vix"]].values,
                     y_is, y_oos, "M4_regime")
else:
    M4 = {"name":"M4_regime","note":"skipped_missing_vix"}

# ============================================================
# 7. DM tests
# ============================================================
print("\n[Step 7] Diebold-Mariano-style tests on LL...")

def dm_ll(p1, p2, y):
    eps = 1e-7
    p1c = np.clip(p1, eps, 1-eps)
    p2c = np.clip(p2, eps, 1-eps)
    ll1 = y * np.log(p1c) + (1-y) * np.log(1-p1c)
    ll2 = y * np.log(p2c) + (1-y) * np.log(1-p2c)
    d = ll2 - ll1
    n = len(d)
    mean_d = d.mean()
    if mean_d == 0:
        return {"t":0.0, "mean_d":0.0, "n":int(n)}
    q = max(1, int(np.ceil(n**(1/3))))
    d_dm = d - mean_d
    gamma_0 = (d_dm**2).mean()
    var_nw = gamma_0
    for k in range(1, q+1):
        gamma_k = (d_dm[k:] * d_dm[:-k]).mean()
        w_k = 1.0 - k/(q+1)
        var_nw += 2 * w_k * gamma_k
    se = np.sqrt(max(var_nw, 1e-16) / n)
    t = mean_d / se
    return {"t":float(t), "mean_d":float(mean_d), "se":float(se), "n":int(n)}

dm_M2_vs_M1 = dm_ll(M1["p_oos"], M2["p_oos"], y_oos)
dm_M3_vs_M2 = dm_ll(M2["p_oos"], M3["p_oos"], y_oos)
dm_M3_vs_M1 = dm_ll(M1["p_oos"], M3["p_oos"], y_oos)
if has_vix:
    dm_M4_vs_M3 = dm_ll(M3["p_oos"], M4["p_oos"], y_oos)
    dm_M4_vs_M1 = dm_ll(M1["p_oos"], M4["p_oos"], y_oos)

# ============================================================
# 8. |OFI| distribution by jump status
# ============================================================
print("\n[Step 8] |OFI| distribution analysis...")
from scipy import stats as sps

jump_bars = df_valid[df_valid["jump_next"]==1]["ofi_abs_t"].values
nojump_bars = df_valid[df_valid["jump_next"]==0]["ofi_abs_t"].values
welch = sps.ttest_ind(jump_bars, nojump_bars, equal_var=False)
ks = sps.ks_2samp(jump_bars, nojump_bars)
mw = sps.mannwhitneyu(jump_bars, nojump_bars, alternative="two-sided")

ofi_dist = {
    "n_jump": int(len(jump_bars)),
    "n_nojump": int(len(nojump_bars)),
    "jump_ofi_mean": float(jump_bars.mean()),
    "jump_ofi_median": float(np.median(jump_bars)),
    "nojump_ofi_mean": float(nojump_bars.mean()),
    "nojump_ofi_median": float(np.median(nojump_bars)),
    "welch_t": float(welch.statistic),
    "welch_p": float(welch.pvalue),
    "ks_stat": float(ks.statistic),
    "ks_p": float(ks.pvalue),
    "mw_p": float(mw.pvalue),
}
print(f"  Jump bars (N={ofi_dist['n_jump']}): |OFI|_mean={ofi_dist['jump_ofi_mean']:.4f}")
print(f"  No-jump (N={ofi_dist['n_nojump']}): |OFI|_mean={ofi_dist['nojump_ofi_mean']:.4f}")
print(f"  Welch t={ofi_dist['welch_t']:+.3f} p={ofi_dist['welch_p']:.4e}")

# ============================================================
# 9. Sub-period OOS stability
# ============================================================
print("\n[Step 9] Sub-period OOS stability...")
oos_rows = df_valid[oos_mask]
is_2020_in_oos = (oos_rows["year"]==2020).values
is_2021_in_oos = (oos_rows["year"]==2021).values

def subperiod_metrics(y_sub, p1, p2):
    if len(y_sub) == 0 or len(np.unique(y_sub))<2:
        return {}
    return {
        "n": int(len(y_sub)),
        "base_rate": float(y_sub.mean()),
        "auc_M1": float(roc_auc_score(y_sub, p1)),
        "auc_M2": float(roc_auc_score(y_sub, p2)),
        "brier_M1": float(brier_score_loss(y_sub, p1)),
        "brier_M2": float(brier_score_loss(y_sub, p2)),
    }

y_2020 = df_valid.loc[oos_mask][is_2020_in_oos]["jump_next"].values
y_2021 = df_valid.loc[oos_mask][is_2021_in_oos]["jump_next"].values

sub_2020 = {
    "M1_vs_M2": subperiod_metrics(y_2020, M1["p_oos"][is_2020_in_oos], M2["p_oos"][is_2020_in_oos]),
    "M1_vs_M3": subperiod_metrics(y_2020, M1["p_oos"][is_2020_in_oos], M3["p_oos"][is_2020_in_oos]),
}
sub_2021 = {
    "M1_vs_M2": subperiod_metrics(y_2021, M1["p_oos"][is_2021_in_oos], M2["p_oos"][is_2021_in_oos]),
    "M1_vs_M3": subperiod_metrics(y_2021, M1["p_oos"][is_2021_in_oos], M3["p_oos"][is_2021_in_oos]),
}

# ============================================================
# 10. Triple-threshold verdict
# ============================================================
auc_impr = M2["auc_oos"] - M1["auc_oos"]
brier_impr_pct = (M1["brier_oos"] - M2["brier_oos"]) / M1["brier_oos"] * 100

subperiod_stable = False
if sub_2020.get("M1_vs_M2") and sub_2021.get("M1_vs_M2"):
    s20 = sub_2020["M1_vs_M2"]
    s21 = sub_2021["M1_vs_M2"]
    subperiod_stable = (s20.get("auc_M2",0) > s20.get("auc_M1",0)) and (s21.get("auc_M2",0) > s21.get("auc_M1",0))

verdict = {
    "auc_improvement_abs": float(auc_impr),
    "auc_threshold_abs": 0.02,
    "auc_pass": bool(auc_impr > 0.02),
    "brier_improvement_pct": float(brier_impr_pct),
    "brier_threshold_pct": 5.0,
    "brier_pass": bool(brier_impr_pct > 5.0),
    "subperiod_stable": bool(subperiod_stable),
    "triple_pass": bool((auc_impr > 0.02) and (brier_impr_pct > 5.0) and subperiod_stable),
}

# ============================================================
# 11. Save results
# ============================================================
print("\n[Step 11] Assembling results...")

def scrub(d):
    if not isinstance(d, dict):
        return d
    return {k: v for k, v in d.items() if k not in ("p_oos", "p_is")}

results = {
    "experiment_id": "K1125",
    "title": "OFI x Lee-Mykland Jump Detection on TAIFEX TX",
    "timestamp": datetime.now().isoformat(),
    "data_source": "TAIFEX TX futures tick data (via K1124 cached bars)",
    "period": f"{df['date'].min()} to {df['date'].max()}",
    "n_bars_total": int(len(df)),
    "n_valid_prediction": int(len(df_valid)),
    "jump_detection": {
        "method": "Lee-Mykland (2008) L_t=|r|/sigma with rolling BV K=16 strictly past",
        "K_window": K_WIN,
        "alpha": alpha,
        "threshold_multi_Gumbel": float(thresh_multi),
        "threshold_single": float(thresh_single),
        "n_jumps_multi": int(n_jump_multi),
        "n_jumps_single": int(n_jump_single),
        "jump_rate_multi_pct": float(n_jump_multi / n_valid_global * 100),
        "jump_rate_single_pct": float(n_jump_single / n_valid_global * 100),
    },
    "IS_period": "2017-2019",
    "OOS_period": "2020-2021",
    "n_IS": int(is_mask.sum()),
    "n_OOS": int(oos_mask.sum()),
    "IS_jump_rate_pct": float(y_is.mean()*100),
    "OOS_jump_rate_pct": float(y_oos.mean()*100),
    "models": {
        "M0_constant": scrub(M0),
        "M1_lagjump": scrub(M1),
        "M2_lagjump_ofiabs": scrub(M2),
        "M3_lagjump_ofiabs_signed": scrub(M3),
        "M4_regime": scrub(M4),
    },
    "dm_tests": {
        "M2_vs_M1": dm_M2_vs_M1,
        "M3_vs_M2": dm_M3_vs_M2,
        "M3_vs_M1": dm_M3_vs_M1,
    },
    "ofi_distribution_by_jump": ofi_dist,
    "subperiod_OOS": {"2020": sub_2020, "2021": sub_2021},
    "triple_threshold_verdict": verdict,
    "references": [
        "Lee & Mykland (2008), Review of Financial Studies 21(6), 2535-2563",
        "Cont, Kukanov, Stoikov (2014), J Financial Econometrics 12(1), 47-88",
    ],
    "runtime_sec": (datetime.now()-t0).total_seconds(),
}
if has_vix:
    results["dm_tests"]["M4_vs_M3"] = dm_M4_vs_M3
    results["dm_tests"]["M4_vs_M1"] = dm_M4_vs_M1

print("\n" + "=" * 70)
print("RESULTS SUMMARY")
print("=" * 70)
print(f"Jump rate (multi-test alpha=0.01): {results['jump_detection']['jump_rate_multi_pct']:.2f}%")
print(f"\n{'Model':<28} {'AUC IS':>8} {'AUC OOS':>9} {'Brier OOS':>11} {'LL OOS':>10}")
for mname in ("M0_constant","M1_lagjump","M2_lagjump_ofiabs","M3_lagjump_ofiabs_signed","M4_regime"):
    m = results["models"][mname]
    if "auc_oos" in m:
        print(f"{mname:<28} {m['auc_is']:>8.4f} {m['auc_oos']:>9.4f} {m['brier_oos']:>11.6f} {m['ll_oos']:>10.4f}")
    else:
        print(f"{mname:<28} [skipped]")

print(f"\nDM tests (t-stat, positive = M_latter better on LL):")
for k, v in results["dm_tests"].items():
    print(f"  {k}: t={v['t']:+.3f}, delta_mean_LL={v['mean_d']:+.2e}")

print(f"\n|OFI| by jump status: jump_mean={ofi_dist['jump_ofi_mean']:.4f} vs nojump_mean={ofi_dist['nojump_ofi_mean']:.4f}")
print(f"  Welch t={ofi_dist['welch_t']:+.3f}, p={ofi_dist['welch_p']:.4e}")

print(f"\nTriple threshold verdict:")
print(f"  AUC impr M2-M1={verdict['auc_improvement_abs']:+.4f} (thr 0.02) -> {'PASS' if verdict['auc_pass'] else 'FAIL'}")
print(f"  Brier impr M2-M1={verdict['brier_improvement_pct']:+.2f}% (thr 5%) -> {'PASS' if verdict['brier_pass'] else 'FAIL'}")
print(f"  Sub-period stable -> {'PASS' if verdict['subperiod_stable'] else 'FAIL'}")
print(f"  === TRIPLE: {'PASS' if verdict['triple_pass'] else 'FAIL'} ===")
print(f"\nRuntime: {results['runtime_sec']:.1f}s")

out_path = ROOT / "k1125_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved: {out_path}")

np.savez(ROOT / "k1125_preds.npz",
         y_is=y_is, y_oos=y_oos,
         p_M0_oos=M0["p_oos"], p_M1_oos=M1["p_oos"], p_M2_oos=M2["p_oos"],
         p_M3_oos=M3["p_oos"],
         **({"p_M4_oos": M4["p_oos"]} if has_vix else {}))

# ============================================================
# 12. Plots
# ============================================================
print("\n[Step 12] Plots...")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(12, 10))

ax = axes[0, 0]
L_finite = df["L_stat"][np.isfinite(df["L_stat"])]
ax.hist(L_finite, bins=100, density=True, color="steelblue", alpha=0.7)
ax.axvline(thresh_single, color="orange", linestyle="--", label=f"Single thr={thresh_single:.2f}")
ax.axvline(thresh_multi, color="red", linestyle="-", label=f"Multi thr={thresh_multi:.2f}")
ax.set_xlabel("Lee-Mykland L_t")
ax.set_ylabel("Density")
ax.set_yscale("log")
ax.set_xlim(0, 15)
ax.legend()
ax.set_title("(a) L statistic distribution")

ax = axes[0, 1]
bp = ax.boxplot([df_valid[df_valid["jump_next"]==0]["ofi_abs_t"],
                 df_valid[df_valid["jump_next"]==1]["ofi_abs_t"]],
                 labels=["No Jump (t+1)","Jump (t+1)"], patch_artist=True, showfliers=False)
bp["boxes"][0].set_facecolor("lightblue")
bp["boxes"][1].set_facecolor("salmon")
ax.set_ylabel("|OFI_t|")
ax.set_title(f"(b) |OFI_t| by jump status at t+1\nWelch t={ofi_dist['welch_t']:+.2f}, p={ofi_dist['welch_p']:.1e}")

ax = axes[1, 0]
model_names = []; aucs = []
for mname in ("M0_constant","M1_lagjump","M2_lagjump_ofiabs","M3_lagjump_ofiabs_signed","M4_regime"):
    m = results["models"][mname]
    if "auc_oos" in m:
        model_names.append(mname.replace("_"," "))
        aucs.append(m["auc_oos"])
xs = np.arange(len(model_names))
ax.bar(xs, aucs, color=["gray"]+["steelblue"]*(len(aucs)-1))
ax.axhline(0.5, color="red", linestyle="--", alpha=0.5)
ax.set_xticks(xs); ax.set_xticklabels(model_names, rotation=35, ha="right", fontsize=9)
ax.set_ylabel("AUC (OOS)")
ax.set_title("(c) OOS AUC")
ax.set_ylim(0.45, max(aucs)+0.05)
for x, auc in zip(xs, aucs):
    ax.text(x, auc+0.003, f"{auc:.4f}", ha="center", fontsize=9)

ax = axes[1, 1]
briers = []; names_b = []
for mname in ("M0_constant","M1_lagjump","M2_lagjump_ofiabs","M3_lagjump_ofiabs_signed","M4_regime"):
    m = results["models"][mname]
    if "brier_oos" in m:
        names_b.append(mname.replace("_"," "))
        briers.append(m["brier_oos"])
xs = np.arange(len(names_b))
ax.bar(xs, briers, color=["gray"]+["coral"]*(len(briers)-1))
ax.set_xticks(xs); ax.set_xticklabels(names_b, rotation=35, ha="right", fontsize=9)
ax.set_ylabel("Brier score (OOS)")
ax.set_title("(d) OOS Brier (lower=better)")
for x, b in zip(xs, briers):
    ax.text(x, b+0.0001, f"{b:.5f}", ha="center", fontsize=8)

plt.tight_layout()
fig_path = ROOT / "k1125_results.png"
plt.savefig(fig_path, dpi=120, bbox_inches="tight")
plt.close()
print(f"Plot saved: {fig_path}")

print("\nK1125 complete.")
