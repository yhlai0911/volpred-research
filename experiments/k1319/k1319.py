"""
K1319: HAR + Wavelet Decomposition — Daily RV Forecasting (Preliminary)
Seed: 42

Forecast origin: end-of-day t (RV_t observed).
Target: RV_{t+1} = rv.shift(-1) at row t.
Features at row t: rv[t], rv[t-4:t+1] avg, rv[t-21:t+1] avg   (all ≤ t, clean).
HAR-W window: rv[t-WINDOW+1 : t+1]  (64 days ending inclusive at t).
No extra shift is applied — each row t only sees {RV_1,...,RV_t}.
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pywt
from scipy import stats
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

warnings.filterwarnings("ignore")
RNG = np.random.default_rng(42)

DATA_PATH = Path("paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv")
OUT_DIR = Path("experiments/k1319")
OOS_START = "2020-01-01"
WAVELET = "db4"
DWT_LEVEL = 4
WINDOW = 64  # days for DWT window (ending inclusive at t)


# ── 1. Load data ──────────────────────────────────────────────────────────────
df_raw = pd.read_csv(DATA_PATH, parse_dates=["date"])
df = df_raw[["date", "spy_adj_close"]].dropna().copy()
df = df[df["date"] >= "2010-01-01"].reset_index(drop=True)
df["log_ret"] = np.log(df["spy_adj_close"]).diff()
df["rv"] = df["log_ret"] ** 2   # daily RV proxy (squared log return)
df = df.dropna().reset_index(drop=True)

n = len(df)
print(f"Total observations after 2010: {n}")

# ── 2. HAR features — no extra shift; at row t we use rv[t] (end-of-day t) ──
# Target: rv_{t+1}.  Features: rv_t, 5-day avg ending t, 22-day avg ending t.
# This is 1-step-ahead, forecast origin = close of day t.
df["rv_d"] = df["rv"]                      # rv_t (today's RV)
df["rv_w"] = df["rv"].rolling(5).mean()    # (1/5)*sum(rv_{t-4}..rv_t)
df["rv_m"] = df["rv"].rolling(22).mean()   # (1/22)*sum(rv_{t-21}..rv_t)
df["rv_target"] = df["rv"].shift(-1)       # rv_{t+1}: NEXT DAY — lookahead-free

# ── 3. Wavelet HAR features — window [t-WINDOW+1, t] (inclusive) ─────────────
def build_har_w_features(rv_series, window=WINDOW, level=DWT_LEVEL, wavelet=WAVELET):
    """
    Multi-scale wavelet energy features using past W days of RV.
    Feature for each level = mean(coeff^2) — always non-negative, interpretable
    as volatility energy at that frequency band.

    Raw last-coefficient features caused negative OLS predictions because DWT
    detail coefficients can be negative even when RV >= 0.  Energy features
    are guaranteed non-negative and directly analogous to the rolling-variance
    components in standard HAR.

    Window: rv[t-W+1 .. t] inclusive — causal, no future leakage.
    """
    rv_arr = rv_series.values
    total = len(rv_arr)
    feat_names = [f"energy_cA{level}"] + [f"energy_cD{l}" for l in range(level, 0, -1)]
    rows = []
    for t in range(total):
        if t < window - 1:
            rows.append([np.nan] * len(feat_names))
            continue
        window_rv = np.array(rv_arr[t - window + 1: t + 1], dtype=np.float64)
        coeffs = pywt.wavedec(window_rv, wavelet, level=level)
        feat_row = [float(np.mean(c ** 2)) for c in coeffs]   # energy per band
        rows.append(feat_row)
    return pd.DataFrame(rows, columns=feat_names, index=rv_series.index)


print("Building HAR-W features...")
har_w_feats = build_har_w_features(df["rv"])   # pass rv directly, no pre-shift
df = pd.concat([df, har_w_feats], axis=1)

# ── 4. Train / OOS split ──────────────────────────────────────────────────────
mask_oos = df["date"] >= OOS_START
mask_is = ~mask_oos

har_cols = ["rv_d", "rv_w", "rv_m"]
har_w_cols = [c for c in df.columns if c.startswith("energy_")]
required_har = ["rv_target"] + har_cols
required_harw = ["rv_target"] + har_cols + har_w_cols

df_is = df[mask_is].dropna(subset=required_har).copy()
df_oos = df[mask_oos].dropna(subset=required_har).copy()
print(f"IS (HAR): {len(df_is)}, OOS: {len(df_oos)}")

df_is_w = df[mask_is].dropna(subset=required_harw).copy()
df_oos_w = df[mask_oos].dropna(subset=required_harw).copy()
print(f"IS (HAR-W, after window warmup): {len(df_is_w)}, OOS: {len(df_oos_w)}")

# ── 5. Fit models ─────────────────────────────────────────────────────────────
def fit_ols(X_train, y_train, X_test):
    X_tr = add_constant(np.array(X_train, dtype=float), has_constant="add")
    X_te = add_constant(np.array(X_test,  dtype=float), has_constant="add")
    return OLS(np.array(y_train, dtype=float), X_tr).fit().predict(X_te)


# EWMA baseline (λ=0.94) — forecast at end-of-day t for t+1
# Uses rv[0..t] inclusive; no lookahead.
ewma_lambda = 0.94
rv_vals = df["rv"].values
ewma_pred = []
for i in df_oos.index:
    idx = df.index.get_loc(i)                    # position in full df
    rv_past = rv_vals[:idx + 1]                  # rv[0..t] inclusive
    w = (1 - ewma_lambda) * ewma_lambda ** np.arange(len(rv_past) - 1, -1, -1)
    w /= w.sum()
    ewma_pred.append(float(np.dot(w, rv_past)))

df_oos = df_oos.copy()
df_oos["ewma_pred"] = ewma_pred

# HAR
har_pred = fit_ols(df_is[har_cols], df_is["rv_target"], df_oos[har_cols])
df_oos["har_pred"] = har_pred

# HAR-W (OOS aligned to df_oos_w — warmup rows excluded)
harw_pred = fit_ols(df_is_w[har_w_cols], df_is_w["rv_target"], df_oos_w[har_w_cols])
df_oos_w = df_oos_w.copy()
df_oos_w["harw_pred"] = harw_pred

# ── 6. Metrics ────────────────────────────────────────────────────────────────
def qlike(y, yhat, eps=1e-8):
    h = np.maximum(yhat, eps)
    return float(np.mean(np.log(h) + y / h))

def mse_metric(y, yhat):
    return float(np.mean((y - yhat) ** 2))

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano with Harvey-Leybourne-Newbold (1997) small-sample correction.

    Args:
        loss1, loss2: per-period loss arrays (e.g. QLIKE_t per model).
        h: forecast horizon (default 1).
    Returns:
        (t_stat, p_value) — positive t means loss1 > loss2 (model 2 better).
    """
    d = np.asarray(loss1, float) - np.asarray(loss2, float)
    T = len(d)
    d_bar = d.mean()
    # Long-run variance with HAC (h-1 lags for h-step-ahead, so 0 lags for h=1)
    gamma0 = np.var(d, ddof=1)
    if gamma0 == 0:
        return 0.0, 1.0
    dm = d_bar / np.sqrt(gamma0 / T)
    # HLN (1997) correction: t_HLN = DM * sqrt((T+1-2h+h(h-1)/T) / T)
    # For h=1: factor = sqrt((T-1) / T)
    hlf = (T + 1 - 2 * h + h * (h - 1) / T) / T
    t_stat = dm * np.sqrt(hlf)
    p_val = float(2 * stats.t.sf(abs(t_stat), df=T - 1))
    return float(t_stat), p_val


# Align all OOS observations to common index (HAR-W warmup may drop some rows)
common_idx = df_oos_w.index.intersection(
    df_oos.dropna(subset=["ewma_pred", "har_pred"]).index
)
y     = df_oos.loc[common_idx, "rv_target"].values.astype(float)
f_ewma = df_oos.loc[common_idx, "ewma_pred"].values.astype(float)
f_har  = df_oos.loc[common_idx, "har_pred"].values.astype(float)
f_harw = df_oos_w.loc[common_idx, "harw_pred"].values.astype(float)
print(f"OOS comparison observations (common): {len(y)}")

# Per-period QLIKE losses
eps = 1e-8
loss_ewma = np.log(np.maximum(f_ewma, eps)) + y / np.maximum(f_ewma, eps)
loss_har   = np.log(np.maximum(f_har,  eps)) + y / np.maximum(f_har,  eps)
loss_harw  = np.log(np.maximum(f_harw, eps)) + y / np.maximum(f_harw, eps)

qlike_ewma = loss_ewma.mean()
qlike_har  = loss_har.mean()
qlike_harw = loss_harw.mean()

mse_ewma = mse_metric(y, f_ewma)
mse_har  = mse_metric(y, f_har)
mse_harw = mse_metric(y, f_harw)

# DM tests: positive t_stat ⟹ first model has higher loss ⟹ second model better
dm_harw_vs_har_stat, dm_harw_vs_har_p = dm_test(loss_harw, loss_har)  # test HAR-W vs HAR
dm_har_vs_ewma_stat, dm_har_vs_ewma_p = dm_test(loss_har,  loss_ewma)

print(f"\n=== OOS Results ===")
print(f"QLIKE: EWMA={qlike_ewma:.6f}, HAR={qlike_har:.6f}, HAR-W={qlike_harw:.6f}")
print(f"MSE:   EWMA={mse_ewma:.2e}, HAR={mse_har:.2e}, HAR-W={mse_harw:.2e}")
print(f"DM(HAR-W vs HAR, h=1): t={dm_harw_vs_har_stat:.3f}, p={dm_harw_vs_har_p:.4f}")
print(f"DM(HAR vs EWMA, h=1):  t={dm_har_vs_ewma_stat:.3f}, p={dm_har_vs_ewma_p:.4f}")

qlike_imp_pct = (qlike_har - qlike_harw) / abs(qlike_har) * 100
mse_imp_pct   = (mse_har  - mse_harw)  / abs(mse_har)  * 100

# ── 7. Verdict ───────────────────────────────────────────────────────────────
harw_better_qlike = bool(qlike_harw < qlike_har)
harw_better_mse   = bool(mse_harw  < mse_har)
# DM: negative t_stat means HAR-W has lower loss (better); p < 0.05 = sig
dm_sig = bool(dm_harw_vs_har_p < 0.05 and dm_harw_vs_har_stat < 0)

if harw_better_qlike and harw_better_mse and dm_sig:
    verdict = "PASS"
elif harw_better_qlike and dm_sig:
    verdict = "CONDITIONAL_PASS"
else:
    verdict = "NULL"

print(f"\nVerdict: {verdict}")
print(f"  QLIKE improvement vs HAR: {qlike_imp_pct:+.2f}%")
print(f"  MSE improvement vs HAR:   {mse_imp_pct:+.2f}%")
print(f"  DM t-stat: {dm_harw_vs_har_stat:.3f}  p: {dm_harw_vs_har_p:.4f}")

# ── 8. Save results ───────────────────────────────────────────────────────────
results = {
    "experiment_id": "K1319",
    "date": "2026-05-22",
    "verdict": verdict,
    "data": {
        "asset": "SPY",
        "rv_proxy": "squared log return (r^2_t)",
        "period": "2010-01-01 to 2026-05-20",
        "n_total": n,
        "n_is": len(df_is),
        "n_oos": len(df_oos_w),
        "oos_start": OOS_START,
    },
    "models": {
        "wavelet": WAVELET,
        "dwt_levels": DWT_LEVEL,
        "window": WINDOW,
        "har_lags": [1, 5, 22],
        "forecast_origin": "end-of-day t; HAR uses rv[t] (no extra shift); target = rv[t+1]",
    },
    "qlike": {
        "ewma_0.94": round(qlike_ewma, 6),
        "har": round(qlike_har, 6),
        "har_w": round(qlike_harw, 6),
        "harw_vs_har_improvement_pct": round(qlike_imp_pct, 3),
    },
    "mse": {
        "ewma_0.94": round(mse_ewma, 10),
        "har": round(mse_har, 10),
        "har_w": round(mse_harw, 10),
        "harw_vs_har_improvement_pct": round(mse_imp_pct, 3),
    },
    "dm_test": {
        "harw_vs_har_t_stat": round(dm_harw_vs_har_stat, 4),
        "harw_vs_har_pvalue": round(dm_harw_vs_har_p, 4),
        "har_vs_ewma_t_stat": round(dm_har_vs_ewma_stat, 4),
        "har_vs_ewma_pvalue": round(dm_har_vs_ewma_p, 4),
        "correction": "Harvey-Leybourne-Newbold (1997), h=1: factor=sqrt((T-1)/T)",
        "alpha": 0.05,
        "sign_convention": "negative t_stat => HAR-W better (lower loss)",
    },
    "interpretation": {
        "harw_better_qlike": bool(harw_better_qlike),
        "harw_better_mse": bool(harw_better_mse),
        "dm_significant": bool(dm_sig),
        "note": "Preliminary with daily r^2 RV proxy. 5-min RV version deferred to Q2 2026. Wavelet features: mean(coeff^2) energy per level — non-negative by design.",
    },
    "lookahead_audit": {
        "forecast_origin": "end-of-day t",
        "har_features": "rv_d=rv[t], rv_w=rolling(5) ending t, rv_m=rolling(22) ending t — all <= t",
        "harw_features": "DWT on rv[t-63 .. t] (64 days ending inclusive at t) — all <= t",
        "target": "rv_target = rv.shift(-1) = rv[t+1] at row t",
        "status": "CLEAN — both HAR and HAR-W use identical information set {rv_1..rv_t}",
    },
    "seed": 42,
}

OUT_DIR.mkdir(parents=True, exist_ok=True)
out_path = OUT_DIR / "k1319_results.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\nResults saved to {out_path}")
