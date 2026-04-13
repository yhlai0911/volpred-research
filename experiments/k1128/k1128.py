"""
K1128 - VIX Tertile Regime Split for OFI -> Jump Prediction
============================================================

Follow-up to K1125 (OFI x Lee-Mykland jump detection on TAIFEX TX).

**Motivation**: K1125 found signed-OFI predictive power is **concentrated in 2020 COVID**
(sub-period AUC 0.580) while 2021 calm period shows marginal/no effect (AUC 0.547).
The M4 interaction term (|OFI| * VIX_z) failed catastrophically (DM t=-6.09, AUC<0.5).

K1128 reframes: rather than a *continuous interaction*, split the OOS sample by VIX
tertile (computed from IS 2017-2019 distribution) and re-fit the K1125 M3 model
(`jump_curr + |OFI|_t + OFI_t`) within each tertile. This is a cleaner test of
regime-dependence because:
  - Tertile splits avoid functional-form assumption (linear interaction)
  - Each regime gets its own intercept + slope coefficients
  - Clear hypothesis: high-VIX regime should show strongest signal

**Hypotheses**:
  H1 (main): High-VIX tertile OOS AUC > Mid > Low (monotonic strengthening)
  H2 (DM): High-VIX tertile DM-HLN |t|>2 vs M1 baseline within tertile;
           Low-VIX tertile may be NS
  H3 (coef): beta_|OFI| and |beta_OFI_signed| larger in high than low tertile
  H4 (null): Sample size after split may be too small for power (OOS ~7k per tertile)

**Safeguards**:
  - VIX tertile cutoffs computed on IS 2017-2019 ONLY (no OOS leakage)
  - Test tertile assignment uses IS cutoffs applied to OOS VIX (no look-ahead)
  - VIX is T-1 lag (previous US close, TAIFEX opens next morning)
  - Z-score standardization (for diagnostic only) uses IS mean/std
  - Fit each tertile sub-model on IS rows WITHIN that tertile (3 separate models)
  - Strict lag-1 features: jump_{t+1} = f(features_at_t)

**Data**: Reuse K1125's input pipeline (parquet cache + same jump detection)

References:
  - Lee & Mykland (2008) RFS 21(6), 2535-2563
  - Cont, Kukanov, Stoikov (2014) JFE 12(1), 47-88
  - Ang & Timmermann (2012) regime-switching survey

Author: Claude (worktree agent-k1128)
Date: 2026-04-13
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
# Reuse K1124's cached bars (K1125 also used this)
CACHE_PATH = ROOT.parent / "k1124" / "_cache_bars_2017-01-01_2021-12-31.parquet"

print("=" * 70)
print("K1128 - VIX Tertile Regime Split for OFI -> Jump Prediction")
print("=" * 70)
t0 = datetime.now()

# ============================================================
# 1. LOAD CACHED BARS
# ============================================================
print("\n[Step 1] Loading cached bars...")
df = pd.read_parquet(CACHE_PATH)
df = df.sort_values(["date", "bar"]).reset_index(drop=True)
print(f"  Loaded {len(df):,} bars across {df['date'].nunique()} days")
print(f"  Period: {df['date'].min()} to {df['date'].max()}")

# ============================================================
# 2. LEE-MYKLAND JUMP DETECTION (reuse K1125 BV-fixed formula)
# ============================================================
print("\n[Step 2] Computing Lee-Mykland jump statistic per day...")
MU1 = np.sqrt(2.0 / np.pi)
K_WIN = 16

def compute_jumps_per_day(day_df: pd.DataFrame, K: int = K_WIN):
    """
    Per-day BV using strictly past returns r_{t-K},...,r_{t-1} (K returns, K-1 products).
    Matches K1125 post-Codex-fix specification.
    """
    r = day_df["log_ret"].values
    n = len(r)
    sigma_hat = np.full(n, np.nan)
    abs_r = np.abs(r)
    pairs = abs_r[:-1] * abs_r[1:]  # pairs[p] = |r_p|*|r_{p+1}|
    for t in range(K, n):
        start = t - K
        stop = t - 1
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

df["jump"] = ((df["L_stat"] > thresh_multi) & np.isfinite(df["L_stat"])).astype(int)
df.loc[~np.isfinite(df["L_stat"]), "jump"] = -1

n_jump = (df["jump"] == 1).sum()
print(f"  Valid L obs: {n_valid_global:,}")
print(f"  Multi-test Gumbel threshold (alpha=0.01): {thresh_multi:.3f}")
print(f"  Jumps detected: {n_jump} ({n_jump/n_valid_global*100:.2f}%)")

# ============================================================
# 3. BUILD FEATURES AND jump_{t+1} TARGET
# ============================================================
print("\n[Step 3] Building features and target jump_{t+1}...")

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
# 4. LOAD VIX (T-1 lag)
# ============================================================
print("\n[Step 4] Loading daily VIX (T-1 lag)...")
import yfinance as yf
vix = yf.download("^VIX", start="2016-12-01", end="2022-01-31",
                   progress=False, auto_adjust=False)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)
vix_df = vix[["Close"]].reset_index()
vix_df.columns = ["date", "vix"]
vix_df["date"] = pd.to_datetime(vix_df["date"]).dt.normalize()
vix_df = vix_df.dropna().drop_duplicates("date").sort_values("date").reset_index(drop=True)
vix_df["vix_lag1"] = vix_df["vix"].shift(1)
vix_df["vix_lag1"] = vix_df["vix_lag1"].ffill()

df_valid["date_norm"] = pd.to_datetime(df_valid["date"]).dt.normalize()
df_valid = df_valid.merge(vix_df[["date", "vix_lag1"]].rename(columns={"date": "date_norm"}),
                            on="date_norm", how="left")
df_valid["vix_lag1"] = df_valid["vix_lag1"].ffill()
n_missing_vix = df_valid["vix_lag1"].isna().sum()
print(f"  VIX days: {len(vix_df)}, missing: {n_missing_vix}")
assert n_missing_vix == 0, "VIX merge has missing values, fix upstream"

# ============================================================
# 5. COMPUTE TERTILE CUTOFFS FROM IS-ONLY VIX
# ============================================================
print("\n[Step 5] Computing VIX tertile cutoffs from IS-only data...")
df_valid["year"] = df_valid["date"].dt.year
is_mask = df_valid["year"].isin([2017, 2018, 2019])
oos_mask = df_valid["year"].isin([2020, 2021])

vix_is = df_valid.loc[is_mask, "vix_lag1"].values
cutoff_33 = np.quantile(vix_is, 1/3)
cutoff_67 = np.quantile(vix_is, 2/3)
vix_is_mean = vix_is.mean()
vix_is_std = vix_is.std()
print(f"  IS VIX: min={vix_is.min():.2f}, mean={vix_is_mean:.2f}, std={vix_is_std:.2f}, max={vix_is.max():.2f}")
print(f"  Cutoff (33%): {cutoff_33:.3f}")
print(f"  Cutoff (67%): {cutoff_67:.3f}")

# Assign tertile (using IS-derived cutoffs for all rows)
def assign_tertile(vix_val):
    if vix_val <= cutoff_33:
        return 0  # low
    elif vix_val <= cutoff_67:
        return 1  # mid
    else:
        return 2  # high

df_valid["vix_tertile"] = df_valid["vix_lag1"].apply(assign_tertile)

# Check distribution
print("\n  IS tertile counts:")
is_tertile_counts = df_valid.loc[is_mask, "vix_tertile"].value_counts().sort_index()
for t, n in is_tertile_counts.items():
    print(f"    T{t} (low->high VIX): {n:,}")
print("\n  OOS tertile counts (using IS cutoffs):")
oos_tertile_counts = df_valid.loc[oos_mask, "vix_tertile"].value_counts().sort_index()
for t, n in oos_tertile_counts.items():
    print(f"    T{t} (low->high VIX): {n:,}")
# Report OOS VIX range in each tertile
print("\n  OOS VIX range per tertile:")
for t in range(3):
    rows = df_valid[(oos_mask) & (df_valid["vix_tertile"] == t)]
    if len(rows) > 0:
        print(f"    T{t}: VIX min={rows['vix_lag1'].min():.2f}, mean={rows['vix_lag1'].mean():.2f}, max={rows['vix_lag1'].max():.2f}")

# ============================================================
# 6. BUILD FEATURE COLUMNS
# ============================================================
df_valid["jump_curr"] = df_valid["jump"].clip(lower=0)
df_valid["ofi_t"] = df_valid["ofi"]
df_valid["ofi_abs_t"] = df_valid["ofi"].abs()

FEATURES_M1 = ["jump_curr"]
FEATURES_M3 = ["jump_curr", "ofi_abs_t", "ofi_t"]

# ============================================================
# 7. FIT M1 AND M3 PER TERTILE
# ============================================================
print("\n[Step 7] Fitting M1 and M3 within each VIX tertile...")

def fit_logistic(X_is, y_is, X_oos, y_oos, name):
    """Fit logistic regression with StandardScaler using IS-only stats."""
    sc = StandardScaler()
    Xi = sc.fit_transform(X_is)
    Xo = sc.transform(X_oos)
    model = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs", random_state=42)
    model.fit(Xi, y_is)
    p_is = np.clip(model.predict_proba(Xi)[:, 1], 1e-7, 1-1e-7)
    p_oos = np.clip(model.predict_proba(Xo)[:, 1], 1e-7, 1-1e-7)
    auc_is = roc_auc_score(y_is, p_is) if len(np.unique(y_is)) > 1 else np.nan
    auc_oos = roc_auc_score(y_oos, p_oos) if len(np.unique(y_oos)) > 1 else np.nan
    return {
        "name": name,
        "n_features": int(X_is.shape[1]),
        "coefs": model.coef_[0].tolist(),
        "intercept": float(model.intercept_[0]),
        "scaler_mean": sc.mean_.tolist(),
        "scaler_scale": sc.scale_.tolist(),
        "auc_is": float(auc_is) if not np.isnan(auc_is) else None,
        "auc_oos": float(auc_oos) if not np.isnan(auc_oos) else None,
        "brier_is": float(brier_score_loss(y_is, p_is)),
        "brier_oos": float(brier_score_loss(y_oos, p_oos)),
        "ll_is": float(-log_loss(y_is, p_is)),
        "ll_oos": float(-log_loss(y_oos, p_oos)),
        "n_is": int(len(y_is)),
        "n_oos": int(len(y_oos)),
        "n_is_positive": int(y_is.sum()),
        "n_oos_positive": int(y_oos.sum()),
        "p_oos": p_oos,
    }

def dm_hln_ll(p1, p2, y, name=""):
    """
    DM-HLN test (Harvey-Leybourne-Newbold 1997) on LL differences.
    t > 0 means p2 (latter) has higher LL than p1.
    """
    eps = 1e-7
    p1c = np.clip(p1, eps, 1-eps)
    p2c = np.clip(p2, eps, 1-eps)
    ll1 = y * np.log(p1c) + (1-y) * np.log(1-p1c)
    ll2 = y * np.log(p2c) + (1-y) * np.log(1-p2c)
    d = ll2 - ll1
    n = len(d)
    mean_d = d.mean()
    if abs(mean_d) < 1e-20:
        return {"t": 0.0, "mean_d": 0.0, "se": 0.0, "n": int(n)}
    q = max(1, int(np.ceil(n**(1/3))))
    d_dm = d - mean_d
    gamma_0 = (d_dm**2).mean()
    var_nw = gamma_0
    for k in range(1, q+1):
        if k < n:
            gamma_k = (d_dm[k:] * d_dm[:-k]).mean()
            w_k = 1.0 - k/(q+1)
            var_nw += 2 * w_k * gamma_k
    se = np.sqrt(max(var_nw, 1e-16) / n)
    t_plain = mean_d / se
    # HLN small-sample adjustment: multiplier sqrt((n+1-2h+h(h-1)/n)/n) with h=1
    hln_mult = np.sqrt((n + 1 - 2*1 + 1*(1-1)/n) / n)
    t_hln = t_plain * hln_mult
    return {"t": float(t_hln), "t_plain": float(t_plain),
            "mean_d": float(mean_d), "se": float(se), "n": int(n)}

tertile_results = {}
tertile_names = {0: "low", 1: "mid", 2: "high"}

for t_idx in [0, 1, 2]:
    tname = tertile_names[t_idx]
    print(f"\n  Tertile {t_idx} ({tname} VIX):")

    is_t_mask = is_mask & (df_valid["vix_tertile"] == t_idx)
    oos_t_mask = oos_mask & (df_valid["vix_tertile"] == t_idx)

    n_is_t = is_t_mask.sum()
    n_oos_t = oos_t_mask.sum()
    n_jumps_oos_t = df_valid.loc[oos_t_mask, "jump_next"].sum()
    print(f"    IS N={n_is_t:,}, OOS N={n_oos_t:,}, OOS jumps={int(n_jumps_oos_t)}")

    # Need at least 5 positive cases in IS and OOS to be meaningful
    n_jumps_is_t = df_valid.loc[is_t_mask, "jump_next"].sum()
    if n_jumps_is_t < 5 or n_jumps_oos_t < 5:
        print(f"    SKIP: insufficient jumps (IS={int(n_jumps_is_t)}, OOS={int(n_jumps_oos_t)})")
        tertile_results[tname] = {
            "tertile_idx": t_idx,
            "status": "skipped_insufficient_jumps",
            "n_is": int(n_is_t), "n_oos": int(n_oos_t),
            "n_is_jumps": int(n_jumps_is_t), "n_oos_jumps": int(n_jumps_oos_t),
        }
        continue

    X_is_M1 = df_valid.loc[is_t_mask, FEATURES_M1].values
    y_is_t = df_valid.loc[is_t_mask, "jump_next"].values.astype(int)
    X_oos_M1 = df_valid.loc[oos_t_mask, FEATURES_M1].values
    y_oos_t = df_valid.loc[oos_t_mask, "jump_next"].values.astype(int)

    X_is_M3 = df_valid.loc[is_t_mask, FEATURES_M3].values
    X_oos_M3 = df_valid.loc[oos_t_mask, FEATURES_M3].values

    try:
        M1_t = fit_logistic(X_is_M1, y_is_t, X_oos_M1, y_oos_t, f"M1_tertile_{tname}")
        M3_t = fit_logistic(X_is_M3, y_is_t, X_oos_M3, y_oos_t, f"M3_tertile_{tname}")
        dm_M3_vs_M1 = dm_hln_ll(M1_t["p_oos"], M3_t["p_oos"], y_oos_t,
                                 name=f"M3_vs_M1_{tname}")
    except Exception as e:
        print(f"    ERROR during fit: {e}")
        tertile_results[tname] = {
            "tertile_idx": t_idx, "status": f"error: {e}",
            "n_is": int(n_is_t), "n_oos": int(n_oos_t),
        }
        continue

    print(f"    M1 AUC IS={M1_t['auc_is']:.4f}  OOS={M1_t['auc_oos']:.4f}")
    print(f"    M3 AUC IS={M3_t['auc_is']:.4f}  OOS={M3_t['auc_oos']:.4f}")
    print(f"    M3 coefs (std): jump_curr={M3_t['coefs'][0]:+.3f}  |OFI|={M3_t['coefs'][1]:+.3f}  OFI={M3_t['coefs'][2]:+.3f}")
    print(f"    DM M3 vs M1: t={dm_M3_vs_M1['t']:+.3f} (mean_d={dm_M3_vs_M1['mean_d']:+.2e})")

    # Strip p_oos from saved artifact (too big)
    M1_save = {k: v for k, v in M1_t.items() if k != "p_oos"}
    M3_save = {k: v for k, v in M3_t.items() if k != "p_oos"}

    tertile_results[tname] = {
        "tertile_idx": t_idx,
        "status": "ok",
        "n_is": int(n_is_t),
        "n_oos": int(n_oos_t),
        "n_is_jumps": int(n_jumps_is_t),
        "n_oos_jumps": int(n_jumps_oos_t),
        "vix_range": {
            "is_min": float(df_valid.loc[is_t_mask, "vix_lag1"].min()),
            "is_max": float(df_valid.loc[is_t_mask, "vix_lag1"].max()),
            "oos_min": float(df_valid.loc[oos_t_mask, "vix_lag1"].min()),
            "oos_max": float(df_valid.loc[oos_t_mask, "vix_lag1"].max()),
        },
        "M1": M1_save,
        "M3": M3_save,
        "dm_M3_vs_M1": dm_M3_vs_M1,
    }

# ============================================================
# 8. MONOTONICITY TEST (OOS AUC)
# ============================================================
print("\n[Step 8] Monotonicity test (H1): low -> mid -> high AUC...")
aucs_by_tertile = {}
for tname in ("low", "mid", "high"):
    r = tertile_results.get(tname, {})
    if r.get("status") == "ok" and r["M3"].get("auc_oos") is not None:
        aucs_by_tertile[tname] = r["M3"]["auc_oos"]

auc_low = aucs_by_tertile.get("low")
auc_mid = aucs_by_tertile.get("mid")
auc_high = aucs_by_tertile.get("high")

strict_monotonic = False
partial_monotonic_high_gt_low = False
if auc_low is not None and auc_mid is not None and auc_high is not None:
    strict_monotonic = (auc_low < auc_mid < auc_high)
    partial_monotonic_high_gt_low = (auc_high > auc_low)

monotonic_verdict = {
    "auc_low": auc_low,
    "auc_mid": auc_mid,
    "auc_high": auc_high,
    "strict_monotonic_L_lt_M_lt_H": bool(strict_monotonic),
    "high_minus_low": float((auc_high - auc_low) if (auc_high is not None and auc_low is not None) else np.nan),
    "partial_high_gt_low": bool(partial_monotonic_high_gt_low),
}

# ============================================================
# 9. COEFFICIENT DRIFT ACROSS TERTILES
# ============================================================
print("\n[Step 9] M3 coefficient drift across tertiles...")
coef_drift = {}
feat_names = ["jump_curr", "ofi_abs_t", "ofi_t"]
for tname in ("low", "mid", "high"):
    r = tertile_results.get(tname, {})
    if r.get("status") == "ok":
        coef_drift[tname] = {
            feat_names[i]: float(r["M3"]["coefs"][i]) for i in range(3)
        }
        print(f"  {tname:4s}: jump_curr={coef_drift[tname]['jump_curr']:+.3f}  "
              f"|OFI|={coef_drift[tname]['ofi_abs_t']:+.3f}  "
              f"OFI={coef_drift[tname]['ofi_t']:+.3f}")

# ============================================================
# 10. VERDICT
# ============================================================
print("\n[Step 10] Assembling verdict...")
# Pass criteria:
#   - High-VIX tertile OOS AUC > 0.55 AND high > low by at least 0.02 AND DM t >= 2.0
high_passes_all = False
if tertile_results.get("high", {}).get("status") == "ok":
    high_r = tertile_results["high"]
    high_auc = high_r["M3"]["auc_oos"] or 0
    high_dm = abs(high_r["dm_M3_vs_M1"]["t"]) or 0
    high_vs_low_diff = (auc_high - auc_low) if (auc_high is not None and auc_low is not None) else 0
    high_passes_all = (high_auc > 0.55) and (high_vs_low_diff > 0.02) and (high_dm >= 2.0)

verdict = {
    "high_tertile_auc_gt_0.55": bool(tertile_results.get("high", {}).get("M3", {}).get("auc_oos", 0) or 0 > 0.55),
    "high_minus_low_gt_0.02": bool((auc_high - auc_low) > 0.02) if (auc_high and auc_low) else False,
    "high_dm_abs_ge_2.0": bool(abs(tertile_results.get("high", {}).get("dm_M3_vs_M1", {}).get("t", 0)) >= 2.0),
    "overall_pass": bool(high_passes_all),
}

# ============================================================
# 10b. SECONDARY ANALYSIS: OOS-INTERNAL TERTILES (DESCRIPTIVE ONLY)
# ============================================================
print("\n[Step 10b] Secondary analysis: OOS-internal VIX tertile split")
print("  (DESCRIPTIVE ONLY - cutoffs peek at OOS VIX; not useable for live trading)")
print("  Motivation: 2020-2021 OOS entirely outside IS VIX range (min 15.01 vs IS max 37),")
print("  making IS-based cutoffs degenerate. OOS-internal split isolates regime effect")
print("  conditional on knowing realized VIX regime (pure microstructure-regime mapping).")

# Compute OOS VIX tertile cutoffs on OOS sample
vix_oos = df_valid.loc[oos_mask, "vix_lag1"].values
oos_cutoff_33 = np.quantile(vix_oos, 1/3)
oos_cutoff_67 = np.quantile(vix_oos, 2/3)
print(f"  OOS VIX: min={vix_oos.min():.2f}, mean={vix_oos.mean():.2f}, max={vix_oos.max():.2f}")
print(f"  OOS cutoff 33%: {oos_cutoff_33:.3f}")
print(f"  OOS cutoff 67%: {oos_cutoff_67:.3f}")

# Assign OOS-internal tertile (only for OOS rows)
def assign_oos_tertile(vix_val):
    if vix_val <= oos_cutoff_33:
        return 0
    elif vix_val <= oos_cutoff_67:
        return 1
    else:
        return 2

df_valid["vix_tertile_oos_internal"] = np.nan
df_valid.loc[oos_mask, "vix_tertile_oos_internal"] = df_valid.loc[oos_mask, "vix_lag1"].apply(assign_oos_tertile)

# ALL-IS fitting (full training set, all VIX regimes) — then evaluate per OOS tertile
# This is the cleanest "regime-dependent OOS evaluation" given IS/OOS distribution mismatch.
y_is_all = df_valid.loc[is_mask, "jump_next"].values.astype(int)
y_oos_all = df_valid.loc[oos_mask, "jump_next"].values.astype(int)

X_is_M1_all = df_valid.loc[is_mask, FEATURES_M1].values
X_oos_M1_all = df_valid.loc[oos_mask, FEATURES_M1].values
X_is_M3_all = df_valid.loc[is_mask, FEATURES_M3].values
X_oos_M3_all = df_valid.loc[oos_mask, FEATURES_M3].values

M1_full = fit_logistic(X_is_M1_all, y_is_all, X_oos_M1_all, y_oos_all, "M1_full")
M3_full = fit_logistic(X_is_M3_all, y_is_all, X_oos_M3_all, y_oos_all, "M3_full")

print(f"  Full IS->OOS fit:")
print(f"    M1 AUC IS={M1_full['auc_is']:.4f} OOS={M1_full['auc_oos']:.4f}")
print(f"    M3 AUC IS={M3_full['auc_is']:.4f} OOS={M3_full['auc_oos']:.4f}")

# Per OOS-tertile evaluation of the SAME full-trained model
# (Models fit on full IS; predictions evaluated per OOS tertile)
oos_tertile_eval = {}
for t_idx in [0, 1, 2]:
    tname = tertile_names[t_idx]
    # Get OOS row indices within this tertile
    oos_rows_df = df_valid[oos_mask].reset_index(drop=True)
    tertile_rows_idx = np.where(oos_rows_df["vix_tertile_oos_internal"].values == t_idx)[0]
    if len(tertile_rows_idx) < 50:
        print(f"  {tname}: SKIP (N={len(tertile_rows_idx)})")
        oos_tertile_eval[tname] = {"status": "too_small", "n": int(len(tertile_rows_idx))}
        continue
    y_t = y_oos_all[tertile_rows_idx]
    p1_t = M1_full["p_oos"][tertile_rows_idx]
    p3_t = M3_full["p_oos"][tertile_rows_idx]
    n_jumps = int(y_t.sum())
    if n_jumps < 2 or len(np.unique(y_t)) < 2:
        print(f"  {tname}: SKIP (jumps={n_jumps})")
        oos_tertile_eval[tname] = {"status": "no_positive", "n": int(len(tertile_rows_idx)),
                                    "jumps": n_jumps}
        continue
    try:
        auc_M1 = roc_auc_score(y_t, p1_t)
        auc_M3 = roc_auc_score(y_t, p3_t)
    except Exception as e:
        auc_M1 = auc_M3 = np.nan

    # DM within tertile
    dm_t = dm_hln_ll(p1_t, p3_t, y_t, name=f"M3_vs_M1_{tname}_oos")
    print(f"  {tname} VIX tertile (OOS-internal, N={len(tertile_rows_idx)}, jumps={n_jumps}):")
    print(f"    VIX range: {df_valid.loc[oos_mask].iloc[tertile_rows_idx]['vix_lag1'].min():.2f}-{df_valid.loc[oos_mask].iloc[tertile_rows_idx]['vix_lag1'].max():.2f}")
    print(f"    M1 AUC={auc_M1:.4f}  M3 AUC={auc_M3:.4f}  DM t={dm_t['t']:+.3f}")
    oos_tertile_eval[tname] = {
        "status": "ok",
        "n": int(len(tertile_rows_idx)),
        "jumps": n_jumps,
        "base_rate": float(y_t.mean()),
        "auc_M1": float(auc_M1) if not np.isnan(auc_M1) else None,
        "auc_M3": float(auc_M3) if not np.isnan(auc_M3) else None,
        "brier_M1": float(brier_score_loss(y_t, p1_t)),
        "brier_M3": float(brier_score_loss(y_t, p3_t)),
        "dm_M3_vs_M1": dm_t,
        "vix_min": float(df_valid.loc[oos_mask].iloc[tertile_rows_idx]["vix_lag1"].min()),
        "vix_max": float(df_valid.loc[oos_mask].iloc[tertile_rows_idx]["vix_lag1"].max()),
        "vix_mean": float(df_valid.loc[oos_mask].iloc[tertile_rows_idx]["vix_lag1"].mean()),
    }

# Check monotonicity on OOS-internal split
aucs_oos_int = {}
for tname in ("low", "mid", "high"):
    r = oos_tertile_eval.get(tname, {})
    if r.get("status") == "ok" and r.get("auc_M3") is not None:
        aucs_oos_int[tname] = r["auc_M3"]

mono_oos = None
if len(aucs_oos_int) == 3:
    mono_oos = {
        "strict_increasing": bool(aucs_oos_int["low"] < aucs_oos_int["mid"] < aucs_oos_int["high"]),
        "high_minus_low": float(aucs_oos_int["high"] - aucs_oos_int["low"]),
        "auc_low": aucs_oos_int["low"],
        "auc_mid": aucs_oos_int["mid"],
        "auc_high": aucs_oos_int["high"],
    }
    print(f"\n  OOS-internal monotonicity: L={aucs_oos_int['low']:.3f} M={aucs_oos_int['mid']:.3f} H={aucs_oos_int['high']:.3f}")
    print(f"    Strict L<M<H: {'YES' if mono_oos['strict_increasing'] else 'NO'}")
    print(f"    High - Low: {mono_oos['high_minus_low']:+.4f}")

# ============================================================
# 11. SAVE RESULTS
# ============================================================
runtime = (datetime.now() - t0).total_seconds()
print(f"\n[Step 11] Saving results (runtime={runtime:.1f}s)...")

results = {
    "experiment_id": "K1128",
    "title": "VIX Tertile Regime Split for OFI -> Jump Prediction on TAIFEX TX",
    "timestamp": datetime.now().isoformat(),
    "data_source": "TAIFEX TX futures 5-min bars (reused K1124 cache)",
    "period_IS": "2017-2019",
    "period_OOS": "2020-2021",
    "vix_source": "yfinance ^VIX daily close, T-1 lag applied",
    "n_bars_total": int(len(df)),
    "n_valid_prediction": int(len(df_valid)),
    "jump_detection": {
        "method": "Lee-Mykland (2008) L_t=|r|/sigma with rolling BV K=16 strictly past (same as K1125)",
        "K_window": K_WIN,
        "alpha": alpha,
        "threshold_multi_Gumbel": float(thresh_multi),
        "n_jumps": int(n_jump),
        "jump_rate_pct": float(n_jump / n_valid_global * 100),
    },
    "vix_tertile_cutoffs": {
        "computed_from": "IS 2017-2019 only",
        "cutoff_33": float(cutoff_33),
        "cutoff_67": float(cutoff_67),
        "vix_is_mean": float(vix_is_mean),
        "vix_is_std": float(vix_is_std),
    },
    "features_M1": FEATURES_M1,
    "features_M3": FEATURES_M3,
    "tertile_results": tertile_results,
    "monotonicity": monotonic_verdict,
    "coef_drift_M3": coef_drift,
    "verdict": verdict,
    "secondary_oos_internal_analysis": {
        "note": "OOS-internal tertile cutoffs (DESCRIPTIVE ONLY - uses OOS VIX info). "
                "Motivation: 2020-2021 OOS VIX range (15-83) disjoint from IS (9-37), "
                "making IS-based cutoffs degenerate. This split isolates "
                "regime effect on same full-IS-trained models.",
        "oos_cutoff_33": float(oos_cutoff_33),
        "oos_cutoff_67": float(oos_cutoff_67),
        "M1_full_auc_oos": M1_full.get("auc_oos"),
        "M3_full_auc_oos": M3_full.get("auc_oos"),
        "per_oos_tertile": oos_tertile_eval,
        "monotonicity_oos_internal": mono_oos,
    },
    "references": [
        "Lee & Mykland (2008) RFS 21(6), 2535-2563",
        "Cont, Kukanov, Stoikov (2014) JFE 12(1), 47-88",
        "Harvey, Leybourne, Newbold (1997) IJF 13(2), 281-291",
    ],
    "runtime_sec": runtime,
}

out_path = ROOT / "k1128_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved: {out_path}")

# ============================================================
# 12. PRINT SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("K1128 SUMMARY - VIX TERTILE REGIME SPLIT")
print("=" * 70)
print(f"\n{'Tertile':<8} {'N IS':>8} {'N OOS':>8} {'Jumps OOS':>10} {'M1 AUC':>8} {'M3 AUC':>8} {'DM t':>8}")
for tname in ("low", "mid", "high"):
    r = tertile_results.get(tname, {})
    if r.get("status") == "ok":
        m1_auc = r["M1"]["auc_oos"] or 0
        m3_auc = r["M3"]["auc_oos"] or 0
        dm_t = r["dm_M3_vs_M1"]["t"]
        print(f"{tname:<8} {r['n_is']:>8,} {r['n_oos']:>8,} {r['n_oos_jumps']:>10} "
              f"{m1_auc:>8.4f} {m3_auc:>8.4f} {dm_t:>+8.3f}")
    else:
        print(f"{tname:<8} [SKIP: {r.get('status', 'missing')}]")

print(f"\nMonotonicity H1 (low < mid < high AUC): {'PASS' if strict_monotonic else 'FAIL'}")
if auc_high is not None and auc_low is not None:
    print(f"  High - Low = {auc_high - auc_low:+.4f}")

print(f"\nOverall verdict (AUC>0.55 AND high-low>0.02 AND DM>=2): "
      f"{'PASS' if verdict['overall_pass'] else 'FAIL'}")

print(f"\nM3 signed-OFI coefficient across tertiles:")
for tname in ("low", "mid", "high"):
    if tname in coef_drift:
        print(f"  {tname}: OFI signed={coef_drift[tname]['ofi_t']:+.3f}")

print("\n--- SECONDARY: OOS-internal tertile AUC (descriptive only) ---")
for tname in ("low", "mid", "high"):
    r = oos_tertile_eval.get(tname, {})
    if r.get("status") == "ok":
        print(f"  {tname} (VIX {r['vix_min']:.1f}-{r['vix_max']:.1f}, N={r['n']:,}, jumps={r['jumps']}): "
              f"M3 AUC={r['auc_M3']:.4f}, DM t={r['dm_M3_vs_M1']['t']:+.3f}")
if mono_oos:
    print(f"\n  OOS-internal L<M<H monotonic: {mono_oos['strict_increasing']} "
          f"(high-low={mono_oos['high_minus_low']:+.4f})")

# ============================================================
# 13. PLOTS
# ============================================================
print("\n[Step 13] Plotting...")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(13, 10))

# (a) OOS AUC M1 vs M3 by tertile
ax = axes[0, 0]
tnames = ["low", "mid", "high"]
auc_m1 = [tertile_results.get(n, {}).get("M1", {}).get("auc_oos", 0) or 0 for n in tnames]
auc_m3 = [tertile_results.get(n, {}).get("M3", {}).get("auc_oos", 0) or 0 for n in tnames]
x = np.arange(len(tnames))
w = 0.35
ax.bar(x - w/2, auc_m1, w, label="M1 (lag-jump)", color="gray")
ax.bar(x + w/2, auc_m3, w, label="M3 (+|OFI|+OFI)", color="steelblue")
ax.axhline(0.5, color="red", linestyle="--", alpha=0.5)
ax.set_xticks(x)
ax.set_xticklabels(["Low VIX", "Mid VIX", "High VIX"])
ax.set_ylabel("OOS AUC")
ax.set_title("(a) OOS AUC by VIX Tertile")
ax.legend()
for i, v in enumerate(auc_m3):
    ax.text(i + w/2, v + 0.005, f"{v:.3f}", ha="center", fontsize=9)
ax.set_ylim(0.45, max(max(auc_m3), max(auc_m1)) + 0.04)

# (b) DM t-stats by tertile
ax = axes[0, 1]
dm_ts = [tertile_results.get(n, {}).get("dm_M3_vs_M1", {}).get("t", 0) or 0 for n in tnames]
colors = ["salmon" if t < 2 else "steelblue" for t in dm_ts]
ax.bar(x, dm_ts, color=colors)
ax.axhline(2.0, color="red", linestyle="--", label="|t|=2")
ax.axhline(-2.0, color="red", linestyle="--")
ax.set_xticks(x)
ax.set_xticklabels(["Low VIX", "Mid VIX", "High VIX"])
ax.set_ylabel("DM-HLN t-stat (M3 vs M1)")
ax.set_title("(b) DM t-stat by VIX Tertile")
for i, v in enumerate(dm_ts):
    ax.text(i, v + 0.1 if v >= 0 else v - 0.2, f"{v:+.2f}", ha="center", fontsize=9)
ax.legend()

# (c) |OFI| coefficient across tertiles
ax = axes[1, 0]
ofi_abs_coef = [coef_drift.get(n, {}).get("ofi_abs_t", 0) for n in tnames]
ofi_signed_coef = [coef_drift.get(n, {}).get("ofi_t", 0) for n in tnames]
ax.plot(x, ofi_abs_coef, "o-", label="|OFI| (magnitude)", color="steelblue", markersize=10)
ax.plot(x, ofi_signed_coef, "s-", label="OFI (signed)", color="coral", markersize=10)
ax.axhline(0, color="gray", linestyle="--", alpha=0.5)
ax.set_xticks(x)
ax.set_xticklabels(["Low VIX", "Mid VIX", "High VIX"])
ax.set_ylabel("Standardized logistic coefficient")
ax.set_title("(c) M3 Coefficients Across Tertiles")
ax.legend()

# (d) OOS-internal tertile AUC (secondary analysis — descriptive)
ax = axes[1, 1]
auc_m1_int = [oos_tertile_eval.get(n, {}).get("auc_M1", 0) or 0 for n in tnames]
auc_m3_int = [oos_tertile_eval.get(n, {}).get("auc_M3", 0) or 0 for n in tnames]
ax.bar(x - w/2, auc_m1_int, w, label="M1 (full-IS fit)", color="gray")
ax.bar(x + w/2, auc_m3_int, w, label="M3 (full-IS fit)", color="seagreen")
ax.axhline(0.5, color="red", linestyle="--", alpha=0.5)
ax.set_xticks(x)
ax.set_xticklabels(["Low VIX\n(OOS-int)", "Mid VIX\n(OOS-int)", "High VIX\n(OOS-int)"])
ax.set_ylabel("OOS AUC")
ax.set_title("(d) OOS-internal Tertile AUC (descriptive only)")
ax.legend(fontsize=8)
for i, v in enumerate(auc_m3_int):
    if v > 0:
        ax.text(i + w/2, v + 0.003, f"{v:.3f}", ha="center", fontsize=9)
if max(auc_m3_int + auc_m1_int) > 0:
    ax.set_ylim(0.45, max(max(auc_m3_int), max(auc_m1_int)) + 0.04)

plt.suptitle("K1128: OFI -> Jump Regime-Dependence via VIX Tertile Split", fontsize=13, y=1.0)
plt.tight_layout()
fig_path = ROOT / "k1128_tertile_results.png"
plt.savefig(fig_path, dpi=120, bbox_inches="tight")
plt.close()
print(f"  Plot saved: {fig_path}")

print(f"\nK1128 complete. Runtime: {runtime:.1f}s")
