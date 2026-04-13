"""
K1126 - Regime-Conditional OFI Buy/Sell Asymmetry for Jump Prediction
=====================================================================

Follow-up to K1125 (which found: signed OFI -> jumps, beta=-0.187, sell-side pressure
predicts jumps more strongly). K1128 (VIX tertile split) degenerated because IS-based
VIX cutoffs didn't transfer to OOS (COVID VIX distribution disjoint from IS).

**K1126 design**: use **ex-ante rolling VIX percentile** (trailing 252-day window)
to classify each TAIFEX trading day as Low (<33%), Mid (33-67%), High (>67%)
VIX regime. Within each regime, fit K1125-style logistic regression but split
signed OFI into BUY (max(0, OFI)) and SELL (min(0, OFI)) components to test
asymmetry per regime.

**Hypotheses**:
- H1: Low VIX -> symmetric (normal conditions)
- H2: High VIX -> sell-side |beta| >> buy-side |beta| (fear asymmetry)
- H3: Low VIX -> asymmetric (thin-market sensitivity)

**Lookahead discipline**:
- Rolling VIX percentile uses strictly past 252 trading days (trailing-only)
- Features at bar t -> target jump_{t+1} (no same-bar leak)
- IS 2017-2019, OOS 2020-2021 (plus full-sample regime conditional results)
- Seed 42

References:
  - Lee & Mykland (2008) RFS 21(6), 2535-2563
  - Cont, Kukanov, Stoikov (2014) JFE 12(1), 47-88
  - Harvey (2016) critical t>3 threshold
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
from scipy import stats as sps

np.random.seed(42)

ROOT = Path(__file__).parent
CACHE_PATH = ROOT.parent / "k1124" / "_cache_bars_2017-01-01_2021-12-31.parquet"

print("=" * 72)
print("K1126 - Regime-Conditional OFI Buy/Sell Asymmetry for Jump Prediction")
print("=" * 72)
t0 = datetime.now()

# ============================================================
# 1. LOAD BAR DATA (reuse K1124 cache)
# ============================================================
df = pd.read_parquet(CACHE_PATH)
df = df.sort_values(["date", "bar"]).reset_index(drop=True)
print(f"[Step 1] Loaded {len(df):,} bars across {df['date'].nunique()} days")
print(f"  Period: {df['date'].min()} to {df['date'].max()}")

# ============================================================
# 2. LEE-MYKLAND JUMP DETECTION (identical to K1125)
# ============================================================
print("\n[Step 2] Computing Lee-Mykland jump stat (K=16 per day)...")
MU1 = np.sqrt(2.0 / np.pi)
K_WIN = 16

def compute_jumps_per_day(day_df: pd.DataFrame, K: int = K_WIN):
    r = day_df["log_ret"].values
    n = len(r)
    sigma_hat = np.full(n, np.nan)
    abs_r = np.abs(r)
    pairs = abs_r[:-1] * abs_r[1:]
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

n_valid = np.isfinite(all_L).sum()
alpha = 0.01
C_n = (np.sqrt(2 * np.log(n_valid))
       - 0.5 * (np.log(np.log(n_valid)) + np.log(4 * np.pi)) / np.sqrt(2 * np.log(n_valid)))
S_n = 1.0 / np.sqrt(2 * np.log(n_valid))
beta_n = -np.log(-np.log(1 - alpha))
thresh_multi = C_n + S_n * beta_n

df["jump"] = (df["L_stat"] > thresh_multi).astype(int)
df.loc[~np.isfinite(df["L_stat"]), "jump"] = -1
n_jumps = (df["jump"] == 1).sum()
print(f"  Multi-test threshold (alpha=0.01): {thresh_multi:.3f}")
print(f"  Jumps detected: {n_jumps} ({n_jumps / n_valid * 100:.2f}%)")

# ============================================================
# 3. LOAD VIX + COMPUTE ROLLING 252-DAY PERCENTILE (EX-ANTE)
# ============================================================
print("\n[Step 3] Loading VIX and computing ex-ante rolling percentile (252-day)...")
import yfinance as yf
# Pull extra 2-year history pre-2017 to warm up rolling window
vix = yf.download("^VIX", start="2015-01-01", end="2022-01-31", progress=False, auto_adjust=False)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)
vix_df = vix[["Close"]].reset_index()
vix_df.columns = ["date", "vix"]
vix_df["date"] = pd.to_datetime(vix_df["date"]).dt.normalize()
vix_df = vix_df.dropna().drop_duplicates("date").sort_values("date").reset_index(drop=True)

# vix_lag1 = previous US trading day's VIX close (TAIFEX day session opens after US close overnight)
vix_df["vix_lag1"] = vix_df["vix"].shift(1)

# Trailing 252-day percentile of vix_lag1 using STRICTLY PAST values (exclude current)
def rolling_percentile_rank(s: pd.Series, window: int = 252, min_periods: int = 100) -> pd.Series:
    n = len(s)
    out = np.full(n, np.nan)
    vals = s.values
    for i in range(n):
        lo = max(0, i - window)
        past = vals[lo:i]
        past = past[np.isfinite(past)]
        if len(past) < min_periods:
            continue
        if not np.isfinite(vals[i]):
            continue
        rank = (past < vals[i]).sum() + 0.5 * (past == vals[i]).sum()
        out[i] = rank / len(past)
    return pd.Series(out, index=s.index)

vix_df["vix_pct_roll"] = rolling_percentile_rank(vix_df["vix_lag1"], window=252, min_periods=100)
print(f"  VIX rows: {len(vix_df)}, pct non-null: {vix_df['vix_pct_roll'].notna().sum()}")

# Merge onto TAIFEX bar data by date
df["date_norm"] = pd.to_datetime(df["date"]).dt.normalize()
df = df.merge(
    vix_df[["date", "vix", "vix_lag1", "vix_pct_roll"]].rename(columns={"date": "date_norm"}),
    on="date_norm", how="left"
)
df["vix_lag1"] = df["vix_lag1"].ffill()
df["vix_pct_roll"] = df["vix_pct_roll"].ffill()
print(f"  After merge: vix_pct_roll non-null: {df['vix_pct_roll'].notna().sum()}")

def classify_regime(p):
    if not np.isfinite(p):
        return "unknown"
    if p < 1.0 / 3.0:
        return "low"
    if p > 2.0 / 3.0:
        return "high"
    return "mid"

df["regime"] = df["vix_pct_roll"].apply(classify_regime)
print("  Regime counts (bar-level, full sample):")
print("   ", df["regime"].value_counts().to_dict())

# ============================================================
# 4. BUILD FEATURES / TARGETS
# ============================================================
print("\n[Step 4] Building features and lagged target...")
df["jump_next"] = -1
for date, gdf in df.groupby("date"):
    idx = gdf.index.values
    jumps = gdf["jump"].values
    jn = np.full(len(gdf), -1)
    jn[:-1] = jumps[1:]
    df.loc[idx, "jump_next"] = jn

valid_mask = (
    df["jump_next"].isin([0, 1])
    & df["ofi"].notna()
    & df["log_ret"].notna()
    & np.isfinite(df["L_stat"])
    & df["regime"].isin(["low", "mid", "high"])
)
df_v = df[valid_mask].copy().reset_index(drop=True)
print(f"  Valid bars: {len(df_v):,}")
print(f"  Jump rate (target): {df_v['jump_next'].mean() * 100:.3f}%")

df_v["jump_curr"] = df_v["jump"].clip(lower=0)
df_v["ofi_abs"] = df_v["ofi"].abs()
df_v["ofi_buy"] = df_v["ofi"].clip(lower=0)
df_v["ofi_sell"] = -df_v["ofi"].clip(upper=0)
df_v["year"] = df_v["date"].dt.year

is_mask = df_v["year"].isin([2017, 2018, 2019])
oos_mask = df_v["year"].isin([2020, 2021])
print(f"  IS: {is_mask.sum():,}  OOS: {oos_mask.sum():,}")
print(f"  IS jump rate: {df_v.loc[is_mask, 'jump_next'].mean() * 100:.3f}%")
print(f"  OOS jump rate: {df_v.loc[oos_mask, 'jump_next'].mean() * 100:.3f}%")

print("\n  Regime x Sample bar counts:")
print(pd.crosstab(df_v["regime"], df_v["year"].isin([2020, 2021]).map({True: "OOS", False: "IS"})))

# ============================================================
# 5. PER-REGIME LOGISTIC: signed baseline + buy/sell split
# ============================================================
print("\n[Step 5] Fitting regime-conditional logistic regressions...")

def fit_and_score(X_is, X_oos, y_is, y_oos, name):
    sc = StandardScaler()
    Xi = sc.fit_transform(X_is)
    Xo = sc.transform(X_oos) if len(X_oos) > 0 else np.empty((0, X_is.shape[1]))
    model = LogisticRegression(C=1.0, max_iter=2000, solver="lbfgs", random_state=42)
    model.fit(Xi, y_is)
    p_is = model.predict_proba(Xi)[:, 1]
    p_oos = model.predict_proba(Xo)[:, 1] if len(Xo) > 0 else np.array([])
    eps = 1e-7
    p_is = np.clip(p_is, eps, 1 - eps)
    p_oos = np.clip(p_oos, eps, 1 - eps)
    info = {
        "name": name,
        "n_features": int(X_is.shape[1]),
        "coefs_std": model.coef_[0].tolist(),
        "intercept": float(model.intercept_[0]),
        "n_is": int(len(y_is)),
        "n_oos": int(len(y_oos)),
        "jumps_is": int(y_is.sum()),
        "jumps_oos": int(y_oos.sum()),
        "scaler_mean": sc.mean_.tolist(),
        "scaler_scale": sc.scale_.tolist(),
    }
    if len(y_is) > 0 and len(np.unique(y_is)) > 1:
        info["auc_is"] = float(roc_auc_score(y_is, p_is))
        info["brier_is"] = float(brier_score_loss(y_is, p_is))
        info["ll_is"] = float(-log_loss(y_is, p_is))
    else:
        info["auc_is"] = np.nan
    if len(y_oos) > 0 and len(np.unique(y_oos)) > 1:
        info["auc_oos"] = float(roc_auc_score(y_oos, p_oos))
        info["brier_oos"] = float(brier_score_loss(y_oos, p_oos))
        info["ll_oos"] = float(-log_loss(y_oos, p_oos))
    else:
        info["auc_oos"] = np.nan
    info["_p_is"] = p_is
    info["_p_oos"] = p_oos
    return info

def wald_diff_test(coef1, coef2, cov1_2x2):
    diff = coef1 - coef2
    var_diff = cov1_2x2[0, 0] + cov1_2x2[1, 1] - 2 * cov1_2x2[0, 1]
    se = np.sqrt(max(var_diff, 1e-16))
    z = diff / se
    p = 2 * (1 - sps.norm.cdf(abs(z)))
    return float(z), float(p)

def fit_with_fisher_cov(X, y, seed=42):
    """Fit near-unregularized logistic and return (coefs_full_with_intercept, cov, model)."""
    model = LogisticRegression(C=1e6, max_iter=5000, solver="lbfgs", random_state=seed)
    model.fit(X, y)
    p = model.predict_proba(X)[:, 1]
    p = np.clip(p, 1e-12, 1 - 1e-12)
    W = p * (1 - p)
    Xf = np.hstack([np.ones((len(X), 1)), X])
    H = (Xf.T * W) @ Xf
    try:
        cov = np.linalg.inv(H)
    except np.linalg.LinAlgError:
        cov = np.linalg.pinv(H)
    coefs_full = np.concatenate([[model.intercept_[0]], model.coef_[0]])
    return coefs_full, cov, model

regimes = ["low", "mid", "high"]
regime_results = {}

for reg in regimes:
    print(f"\n  --- Regime: {reg.upper()} ---")
    reg_mask = (df_v["regime"] == reg)
    mask_is = reg_mask & is_mask
    mask_oos = reg_mask & oos_mask
    n_is = int(mask_is.sum())
    n_oos = int(mask_oos.sum())
    print(f"    IS N={n_is:,}  OOS N={n_oos:,}")
    if n_is == 0:
        print("    SKIP (no IS bars)")
        regime_results[reg] = {"skipped": True, "reason": "no IS bars"}
        continue
    y_is = df_v.loc[mask_is, "jump_next"].values.astype(int)
    y_oos = df_v.loc[mask_oos, "jump_next"].values.astype(int) if n_oos > 0 else np.array([], dtype=int)
    n_is_jumps = int(y_is.sum())
    n_oos_jumps = int(y_oos.sum()) if n_oos > 0 else 0
    print(f"    IS jumps={n_is_jumps} ({n_is_jumps/max(n_is,1)*100:.3f}%)  OOS jumps={n_oos_jumps}")

    if n_is_jumps < 5:
        print("    SKIP (too few IS jumps)")
        regime_results[reg] = {"skipped": True, "reason": f"IS jumps={n_is_jumps} < 5",
                               "n_is": n_is, "n_oos": n_oos}
        continue

    # Baseline K1125-M3: jump_curr + ofi_abs + ofi_signed
    X_is_base = df_v.loc[mask_is, ["jump_curr", "ofi_abs", "ofi"]].values
    X_oos_base = (df_v.loc[mask_oos, ["jump_curr", "ofi_abs", "ofi"]].values
                  if n_oos > 0 else np.empty((0, 3)))
    base = fit_and_score(X_is_base, X_oos_base, y_is, y_oos, f"{reg}_M3_signed")

    # Asymmetric: jump_curr + ofi_buy + ofi_sell
    X_is_asym = df_v.loc[mask_is, ["jump_curr", "ofi_buy", "ofi_sell"]].values
    X_oos_asym = (df_v.loc[mask_oos, ["jump_curr", "ofi_buy", "ofi_sell"]].values
                  if n_oos > 0 else np.empty((0, 3)))
    asym = fit_and_score(X_is_asym, X_oos_asym, y_is, y_oos, f"{reg}_M5_buysell")

    # Unregularized coefs + Fisher covariance for Wald (buy vs sell)
    sc_asym = StandardScaler()
    Xi_std = sc_asym.fit_transform(X_is_asym)
    coefs_full, cov, _ = fit_with_fisher_cov(Xi_std, y_is)
    buy_idx = 2
    sell_idx = 3
    cov_bs = np.array([[cov[buy_idx, buy_idx], cov[buy_idx, sell_idx]],
                       [cov[sell_idx, buy_idx], cov[sell_idx, sell_idx]]])
    z_wald, p_wald = wald_diff_test(coefs_full[buy_idx], coefs_full[sell_idx], cov_bs)
    asymmetry_ratio = abs(coefs_full[sell_idx]) / max(abs(coefs_full[buy_idx]), 1e-12)

    regime_results[reg] = {
        "skipped": False,
        "n_is": n_is,
        "n_oos": n_oos,
        "jumps_is": n_is_jumps,
        "jumps_oos": n_oos_jumps,
        "baseline_signed": {k: v for k, v in base.items() if not k.startswith("_")},
        "asymmetric_buysell": {k: v for k, v in asym.items() if not k.startswith("_")},
        "unreg_coefs": {
            "intercept": float(coefs_full[0]),
            "jump_curr": float(coefs_full[1]),
            "buy": float(coefs_full[buy_idx]),
            "sell": float(coefs_full[sell_idx]),
        },
        "wald_buy_vs_sell": {
            "z": float(z_wald),
            "p": float(p_wald),
            "abs_sell_over_buy_ratio": float(asymmetry_ratio),
        },
    }
    print(f"    Baseline M3 AUC: IS={base.get('auc_is', np.nan):.4f} OOS={base.get('auc_oos', np.nan):.4f}")
    print(f"    Asymmetric    AUC: IS={asym.get('auc_is', np.nan):.4f} OOS={asym.get('auc_oos', np.nan):.4f}")
    print(f"    Std coefs (unreg): buy={coefs_full[buy_idx]:+.4f}  sell={coefs_full[sell_idx]:+.4f}")
    print(f"    Wald buy vs sell: z={z_wald:+.3f}, p={p_wald:.4f}, |sell|/|buy|={asymmetry_ratio:.2f}")

# ============================================================
# 6. CROSS-REGIME STABILITY
# ============================================================
print("\n[Step 6] Cross-regime stability summary...")
stability_table = []
for reg in regimes:
    r = regime_results.get(reg, {})
    if r.get("skipped"):
        continue
    w = r["wald_buy_vs_sell"]
    u = r["unreg_coefs"]
    stability_table.append({
        "regime": reg,
        "n_is": r["n_is"],
        "n_oos": r["n_oos"],
        "jumps_is": r["jumps_is"],
        "jumps_oos": r["jumps_oos"],
        "buy_coef": u["buy"],
        "sell_coef": u["sell"],
        "sell_over_buy_abs": w["abs_sell_over_buy_ratio"],
        "wald_z": w["z"],
        "wald_p": w["p"],
        "auc_is_signed": r["baseline_signed"].get("auc_is", np.nan),
        "auc_oos_signed": r["baseline_signed"].get("auc_oos", np.nan),
        "auc_is_asym": r["asymmetric_buysell"].get("auc_is", np.nan),
        "auc_oos_asym": r["asymmetric_buysell"].get("auc_oos", np.nan),
    })
stability_df = pd.DataFrame(stability_table)
print(stability_df.to_string(index=False))

if len(stability_df) >= 2:
    print("\n  Sell/Buy asymmetry by regime:")
    for _, row in stability_df.iterrows():
        print(f"    {row['regime']:5s}: sell={row['sell_coef']:+.4f}  buy={row['buy_coef']:+.4f}  "
              f"|sell|/|buy|={row['sell_over_buy_abs']:.2f}  Wald z={row['wald_z']:+.2f} (p={row['wald_p']:.3f})")

csv_path = ROOT / "k1126_per_regime_table.csv"
stability_df.to_csv(csv_path, index=False)
print(f"  Per-regime table saved: {csv_path}")

# ============================================================
# 7. VERDICT
# ============================================================
print("\n[Step 7] Verdict...")
def get_ratio(reg):
    r = regime_results.get(reg, {})
    if r.get("skipped"):
        return None
    return r["wald_buy_vs_sell"]["abs_sell_over_buy_ratio"], r["wald_buy_vs_sell"]["p"]

low = get_ratio("low")
mid = get_ratio("mid")
high = get_ratio("high")
verdict = {"regime_metrics": {"low": low, "mid": mid, "high": high}}

H2_pass = False
if high is not None:
    z = abs(regime_results["high"]["wald_buy_vs_sell"]["z"])
    H2_pass = (z > 3.0) and (high[0] > 1.5)
verdict["H2_high_fear_asymmetry"] = {
    "criterion": "|Wald z|>3 AND |sell|/|buy|>1.5 in high regime",
    "pass": bool(H2_pass),
}

H3_pass = False
if low is not None and high is not None:
    H3_pass = low[0] > high[0]
verdict["H3_low_thin_market_asymmetry"] = {
    "criterion": "|sell|/|buy| low > high",
    "pass": bool(H3_pass),
}

H1_pass = False
if low is not None and high is not None:
    H1_pass = (0.7 < low[0] < 1.5) and (0.7 < high[0] < 1.5)
verdict["H1_both_symmetric"] = {
    "criterion": "|sell|/|buy| in (0.7, 1.5) for both low and high",
    "pass": bool(H1_pass),
}

if H2_pass:
    verdict_label = "H2: High-VIX fear asymmetry confirmed"
elif H3_pass:
    verdict_label = "H3: Low-VIX thin-market asymmetry (unexpected)"
elif H1_pass:
    verdict_label = "H1: symmetric across regimes (K1125 asymmetry non-regime)"
else:
    verdict_label = "Mixed / no clean hypothesis"
verdict["overall_label"] = verdict_label
print(f"  Verdict: {verdict_label}")

triple = {}
for reg in regimes:
    r = regime_results.get(reg, {})
    if r.get("skipped"):
        triple[reg] = {"skipped": True}
        continue
    z = r["wald_buy_vs_sell"]["z"]
    auc_oos = r["asymmetric_buysell"].get("auc_oos", np.nan)
    triple[reg] = {
        "wald_pass": bool(abs(z) > 3.0),
        "auc_oos": float(auc_oos) if np.isfinite(auc_oos) else None,
        "auc_oos_pass": bool(auc_oos > 0.55) if np.isfinite(auc_oos) else False,
    }
any_regime_passes = any(
    v.get("wald_pass") and v.get("auc_oos_pass")
    for v in triple.values() if not v.get("skipped")
)
verdict["triple_gate_per_regime"] = triple
verdict["triple_gate_overall_pass"] = bool(any_regime_passes)

# ============================================================
# 8. Save results
# ============================================================
print("\n[Step 8] Saving results...")

def clean_for_json(obj):
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [clean_for_json(x) for x in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    return obj

results = {
    "experiment_id": "K1126",
    "title": "Regime-Conditional OFI Buy/Sell Asymmetry for Jump Prediction (TAIFEX TX)",
    "timestamp": datetime.now().isoformat(),
    "data_source": "TAIFEX TX futures 5-min bars (via K1124 cache) + yfinance ^VIX",
    "period": f"{df['date'].min()} to {df['date'].max()}",
    "n_bars_total": int(len(df)),
    "n_valid_prediction": int(len(df_v)),
    "jump_detection": {
        "method": "Lee-Mykland (2008) L_t with bipower variation K=16",
        "threshold_multi_Gumbel": float(thresh_multi),
        "n_jumps": int(n_jumps),
        "jump_rate_pct": float(n_jumps / n_valid * 100),
    },
    "regime_classification": {
        "method": "Ex-ante rolling 252-day VIX percentile of yesterday's VIX close",
        "cutoffs": "low=<33%, mid=33-67%, high=>67%",
        "min_periods": 100,
    },
    "IS_period": "2017-2019",
    "OOS_period": "2020-2021",
    "regime_counts_bar_level": df_v["regime"].value_counts().to_dict(),
    "regime_results": clean_for_json(regime_results),
    "stability_table": stability_df.to_dict(orient="records"),
    "verdict": clean_for_json(verdict),
    "references": [
        "Lee & Mykland (2008) RFS 21(6), 2535-2563",
        "Cont, Kukanov, Stoikov (2014) JFE 12(1), 47-88",
    ],
    "runtime_sec": (datetime.now() - t0).total_seconds(),
}

out_path = ROOT / "k1126_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved: {out_path}")

# ============================================================
# 9. Plots
# ============================================================
print("\n[Step 9] Plots...")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 2, figsize=(13, 5))

ax = axes[0]
if len(stability_df) > 0:
    reg_order = [r for r in ["low", "mid", "high"] if r in stability_df["regime"].values]
    xs = np.arange(len(reg_order))
    buy_vals = [stability_df[stability_df["regime"] == r]["buy_coef"].iloc[0] for r in reg_order]
    sell_vals = [stability_df[stability_df["regime"] == r]["sell_coef"].iloc[0] for r in reg_order]
    width = 0.35
    ax.bar(xs - width/2, buy_vals, width, label="Buy side (+OFI)", color="steelblue")
    ax.bar(xs + width/2, sell_vals, width, label="Sell side (|-OFI|)", color="salmon")
    ax.axhline(0, color="black", linewidth=0.5)
    for xi, r in enumerate(reg_order):
        row = stability_df[stability_df["regime"] == r].iloc[0]
        y_annot = max(abs(row['buy_coef']), abs(row['sell_coef']))
        ax.annotate(f"z={row['wald_z']:+.2f}\np={row['wald_p']:.3f}",
                    xy=(xi, y_annot),
                    ha="center", fontsize=8, va="bottom")
    ax.set_xticks(xs)
    ax.set_xticklabels([r.upper() for r in reg_order])
    ax.set_ylabel("Standardized logistic coef (unreg)")
    ax.set_title("(a) Buy vs Sell OFI coefficients by VIX regime")
    ax.legend()

ax = axes[1]
if len(stability_df) > 0:
    reg_order = [r for r in ["low", "mid", "high"] if r in stability_df["regime"].values]
    xs = np.arange(len(reg_order))
    base_auc = [stability_df[stability_df["regime"] == r]["auc_oos_signed"].iloc[0] for r in reg_order]
    asym_auc = [stability_df[stability_df["regime"] == r]["auc_oos_asym"].iloc[0] for r in reg_order]
    width = 0.35
    ax.bar(xs - width/2, base_auc, width, label="Baseline (signed)", color="gray")
    ax.bar(xs + width/2, asym_auc, width, label="Asymmetric (buy/sell)", color="teal")
    ax.axhline(0.55, color="red", linestyle="--", alpha=0.6, label="Gate 0.55")
    ax.axhline(0.50, color="black", linestyle="-", alpha=0.4)
    ax.set_xticks(xs)
    ax.set_xticklabels([r.upper() for r in reg_order])
    ax.set_ylabel("OOS AUC")
    ax.set_title("(b) OOS AUC: signed vs buy/sell split")
    ax.set_ylim(0.40, 0.75)
    ax.legend()

plt.tight_layout()
fig_path = ROOT / "k1126_regime_coefs_auc.png"
plt.savefig(fig_path, dpi=120, bbox_inches="tight")
plt.close()
print(f"  Plot saved: {fig_path}")

fig, ax = plt.subplots(figsize=(12, 4))
v_plot = vix_df.dropna(subset=["vix_pct_roll"])
ax.plot(v_plot["date"], v_plot["vix_pct_roll"], color="navy", linewidth=0.7)
ax.axhline(1/3, color="green", linestyle="--", alpha=0.6, label="Low/Mid boundary")
ax.axhline(2/3, color="red", linestyle="--", alpha=0.6, label="Mid/High boundary")
ax.set_xlabel("Date")
ax.set_ylabel("Trailing 252d VIX percentile")
ax.set_title("Rolling VIX Percentile (trailing 252 days, ex-ante)")
ax.set_ylim(0, 1)
ax.legend()
plt.tight_layout()
fig2_path = ROOT / "k1126_vix_percentile_timeline.png"
plt.savefig(fig2_path, dpi=120, bbox_inches="tight")
plt.close()
print(f"  Plot saved: {fig2_path}")

print("\n" + "=" * 72)
print("K1126 COMPLETE")
print("=" * 72)
print(f"Verdict: {verdict_label}")
print(f"Triple-gate overall pass: {verdict['triple_gate_overall_pass']}")
print(f"Runtime: {results['runtime_sec']:.1f}s")
