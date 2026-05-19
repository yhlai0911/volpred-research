"""
K1381: Taiwan Tech Sector Vol as Leading Indicator for 0050.TW

Tests whether TSMC (2330.TW) and MediaTek (2454.TW) realized volatility
can predict Taiwan broad market (0050.TW) volatility via HAR-X models.

Methodology:
- RV proxy: squared log return r^2 (Patton 2011)
- Data cleaning: |log-return| > 0.5 flagged as corporate action / data error
  and treated as NaN (standard daily data practice)
- Models: HAR, HAR_X_TSMC, HAR_X_MTK, HAR_X_TECH, HAR_X_VIX, HAR_X_ALL
- OLS via numpy lstsq; forecasts clamped to [eps, inf) to ensure positivity
- 70/30 OOS split (time-ordered)
- QLIKE loss: mean(r^2/sigma^2 - log(sigma^2) - 1)
- DM test with Harvey (1997) threshold |t| > 3.0
- Granger causality F-test (lag=5)
- LOOKAHEAD PREVENTION: all features use .shift(1)
"""

import numpy as np
import pandas as pd
import json
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats

# Fix seed for reproducibility
np.random.seed(42)

# -----------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(
    REPO_ROOT,
    "paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv",
)
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

print(f"[K1381] REPO_ROOT: {REPO_ROOT}")
print(f"[K1381] DATA_PATH: {DATA_PATH}")

# -----------------------------------------------------------------------
# Load data
# -----------------------------------------------------------------------
df_raw = pd.read_csv(DATA_PATH, index_col=0, parse_dates=True)
df_raw.sort_index(inplace=True)

print(f"[K1381] Raw shape: {df_raw.shape}")

# Use adjusted close prices
price_0050 = df_raw["0050_tw_adj_close"]
price_tsmc = df_raw["2330_tw_adj_close"]
price_mtk  = df_raw["2454_tw_adj_close"]
vix_close  = df_raw["vix_adj_close"]

# -----------------------------------------------------------------------
# Compute daily log returns with outlier cleaning
# Corporate actions / data errors produce |log-return| > 0.5 (+/-65% in levels)
# These are masked as NaN before computing RV
# -----------------------------------------------------------------------
LOG_RETURN_THRESHOLD = 0.5  # |r| > 0.5 => data error or corporate action

def clean_log_returns(prices, threshold=LOG_RETURN_THRESHOLD):
    """Compute log returns and NaN out extreme observations."""
    r = np.log(prices / prices.shift(1))
    n_outliers = (r.abs() > threshold).sum()
    if n_outliers > 0:
        print(f"    [clean] {prices.name}: masking {n_outliers} observations with |r|>{threshold}")
        r[r.abs() > threshold] = np.nan
    return r

ret_0050 = clean_log_returns(price_0050)
ret_tsmc  = clean_log_returns(price_tsmc)
ret_mtk   = clean_log_returns(price_mtk)

# RV proxy: squared log return (Patton 2011 proxy-robust choice for daily data)
rv_0050 = ret_0050 ** 2
rv_tsmc  = ret_tsmc  ** 2
rv_mtk   = ret_mtk  ** 2

# VIX: convert annualised pct vol to daily variance scale
# VIX (e.g. 20) -> daily vol = 20/(100*sqrt(252)) ≈ 0.0126 -> daily var ≈ 1.58e-4
# Using vix^2 / (100^2 * 252) = vix^2 / 2520000
vix_rv = (vix_close ** 2) / (100.0 ** 2 * 252.0)

# Combine into a DataFrame and drop NaN rows
data = pd.DataFrame({
    "rv_0050": rv_0050,
    "rv_tsmc": rv_tsmc,
    "rv_mtk":  rv_mtk,
    "vix_rv":  vix_rv,
}).dropna()

print(f"[K1381] After dropna: {data.shape}")
print(f"[K1381] Date range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"[K1381] rv_0050: mean={data['rv_0050'].mean():.6f}, max={data['rv_0050'].max():.6f}")

# -----------------------------------------------------------------------
# Build HAR features — LOOKAHEAD PREVENTION: shift(1) on all features
# -----------------------------------------------------------------------
# HAR lags of target: daily (t-1), weekly mean (t-5 to t-1), monthly mean (t-22 to t-1)
data["rv_d"]  = data["rv_0050"].shift(1)
data["rv_w"]  = data["rv_0050"].shift(1).rolling(5).mean()
data["rv_m"]  = data["rv_0050"].shift(1).rolling(22).mean()

# Exogenous tech stock features lagged by 1 day (no lookahead)
data["rv_tsmc_lag1"] = data["rv_tsmc"].shift(1)
data["rv_mtk_lag1"]  = data["rv_mtk"].shift(1)
data["vix_rv_lag1"]  = data["vix_rv"].shift(1)

# Drop rows with NaN introduced by rolling windows
data.dropna(inplace=True)
print(f"[K1381] After HAR feature construction: {data.shape}")

n_total = len(data)
n_train = int(n_total * 0.7)
n_test  = n_total - n_train

print(f"[K1381] n_total={n_total}, n_train={n_train}, n_test={n_test}")
print(f"[K1381] Train: {data.index[0].date()} to {data.index[n_train-1].date()}")
print(f"[K1381] Test:  {data.index[n_train].date()} to {data.index[-1].date()}")

# -----------------------------------------------------------------------
# OLS helper (numpy lstsq)
# -----------------------------------------------------------------------
EPS_FORECAST = 1e-10  # clamp floor for forecast positivity

def ols_fit(X, y):
    """OLS via numpy lstsq. Returns (coeffs, fitted_clamped, residuals)."""
    X_c = np.column_stack([np.ones(len(X)), X])
    coeffs, _, _, _ = np.linalg.lstsq(X_c, y, rcond=None)
    fitted_raw = X_c @ coeffs
    fitted = np.maximum(fitted_raw, EPS_FORECAST)  # ensure positive forecasts
    residuals = y - fitted_raw  # residuals from raw (not clamped) for diagnostics
    return coeffs, fitted, residuals


def ols_predict(X_new, coeffs):
    """Predict and clamp to positive values."""
    X_c = np.column_stack([np.ones(len(X_new)), X_new])
    preds_raw = X_c @ coeffs
    return np.maximum(preds_raw, EPS_FORECAST)


# -----------------------------------------------------------------------
# QLIKE loss (Patton 2011)
# -----------------------------------------------------------------------

def qlike(y_true, y_pred, eps=EPS_FORECAST):
    """QLIKE = mean(y_true/y_pred - log(y_pred) - 1)."""
    y_pred_c = np.maximum(y_pred, eps)
    return float(np.mean(y_true / y_pred_c - np.log(y_pred_c) - 1.0))


def qlike_series(y_true, y_pred, eps=EPS_FORECAST):
    """Pointwise QLIKE loss series."""
    y_pred_c = np.maximum(y_pred, eps)
    return y_true / y_pred_c - np.log(y_pred_c) - 1.0


# -----------------------------------------------------------------------
# Model feature matrices
# -----------------------------------------------------------------------
y_all = data["rv_0050"].values
har_base = data[["rv_d", "rv_w", "rv_m"]].values

models_features = {
    "HAR":         har_base,
    "HAR_X_TSMC":  np.column_stack([har_base, data["rv_tsmc_lag1"].values]),
    "HAR_X_MTK":   np.column_stack([har_base, data["rv_mtk_lag1"].values]),
    "HAR_X_TECH":  np.column_stack([har_base, data["rv_tsmc_lag1"].values, data["rv_mtk_lag1"].values]),
    "HAR_X_VIX":   np.column_stack([har_base, data["vix_rv_lag1"].values]),
    "HAR_X_ALL":   np.column_stack([har_base, data["rv_tsmc_lag1"].values, data["rv_mtk_lag1"].values, data["vix_rv_lag1"].values]),
}

# -----------------------------------------------------------------------
# Full-sample QLIKE (in-sample)
# -----------------------------------------------------------------------
full_qlike = {}
model_coefficients = {}

print("\n[K1381] === Full-sample QLIKE ===")
for name, X in models_features.items():
    coeffs, fitted, _ = ols_fit(X, y_all)
    full_qlike[name] = qlike(y_all, fitted)
    model_coefficients[name] = coeffs.tolist()
    print(f"  {name}: {full_qlike[name]:.6f}")

# -----------------------------------------------------------------------
# OOS QLIKE (70/30 split, time-ordered)
# -----------------------------------------------------------------------
extra_cols_arr = {
    "rv_tsmc_lag1": data["rv_tsmc_lag1"].values,
    "rv_mtk_lag1":  data["rv_mtk_lag1"].values,
    "vix_rv_lag1":  data["vix_rv_lag1"].values,
}

def split(arr):
    return arr[:n_train], arr[n_train:]

X_train_base, X_test_base = split(har_base)
y_train, y_test = split(y_all)

# Build train/test feature matrices for each model
def build_oos_matrices(har_tr, har_te, extra_keys):
    """Construct (X_train, X_test) by stacking HAR + extra columns."""
    if not extra_keys:
        return har_tr, har_te
    extra_tr = np.column_stack([split(extra_cols_arr[k])[0] for k in extra_keys])
    extra_te = np.column_stack([split(extra_cols_arr[k])[1] for k in extra_keys])
    return np.column_stack([har_tr, extra_tr]), np.column_stack([har_te, extra_te])

models_extra_keys = {
    "HAR":         [],
    "HAR_X_TSMC":  ["rv_tsmc_lag1"],
    "HAR_X_MTK":   ["rv_mtk_lag1"],
    "HAR_X_TECH":  ["rv_tsmc_lag1", "rv_mtk_lag1"],
    "HAR_X_VIX":   ["vix_rv_lag1"],
    "HAR_X_ALL":   ["rv_tsmc_lag1", "rv_mtk_lag1", "vix_rv_lag1"],
}

oos_qlike = {}
oos_loss_series = {}

print("\n[K1381] === OOS QLIKE ===")
for name, extra_keys in models_extra_keys.items():
    X_tr, X_te = build_oos_matrices(X_train_base, X_test_base, extra_keys)
    coeffs, _, _ = ols_fit(X_tr, y_train)
    y_pred_test = ols_predict(X_te, coeffs)
    oos_qlike[name] = qlike(y_test, y_pred_test)
    oos_loss_series[name] = qlike_series(y_test, y_pred_test)
    print(f"  {name}: {oos_qlike[name]:.6f}")

# -----------------------------------------------------------------------
# DM Test (Harvey 1997) — hand-written
# d = loss_HAR - loss_X  (positive => X model wins)
# -----------------------------------------------------------------------
dm_tests = {}
har_loss = oos_loss_series["HAR"]

dm_model_list = [
    ("HAR_X_TSMC", "HAR_X_TSMC vs HAR"),
    ("HAR_X_MTK",  "HAR_X_MTK vs HAR"),
    ("HAR_X_TECH", "HAR_X_TECH vs HAR"),
    ("HAR_X_VIX",  "HAR_X_VIX vs HAR"),
    ("HAR_X_ALL",  "HAR_X_ALL vs HAR"),
]

print("\n[K1381] === DM Tests ===")
for model_name, label in dm_model_list:
    model_loss = oos_loss_series[model_name]
    d = har_loss - model_loss  # positive => HAR-X has lower loss => wins
    n_d = len(d)
    dm_stat = float(np.mean(d) / (np.std(d, ddof=1) / np.sqrt(n_d)))
    dm_p    = float(2.0 * (1.0 - stats.t.cdf(abs(dm_stat), df=n_d - 1)))
    harvey_pass = abs(dm_stat) > 3.0
    direction = "model2_wins" if dm_stat > 0 else ("model1_wins" if dm_stat < 0 else "tie")
    dm_tests[label] = {
        "dm_t":        round(dm_stat, 4),
        "dm_p":        round(dm_p, 4),
        "harvey_pass": harvey_pass,
        "direction":   direction,
    }
    print(f"  {label}: t={dm_stat:.3f}, p={dm_p:.4f}, Harvey={'PASS' if harvey_pass else 'FAIL'}, {direction}")

# -----------------------------------------------------------------------
# Granger Causality F-test (lag=5), hand-written
# Restricted: HAR (lag-d, lag-w, lag-m) of target
# Unrestricted: HAR + predictor lags 1..5
# Applied on the full aligned cleaned sample
# -----------------------------------------------------------------------

def granger_f_test(target_rv, predictor_rv, lags=5):
    """
    Granger causality F-test.
    Restricted:   y ~ const + HAR(target)
    Unrestricted: y ~ const + HAR(target) + pred_lag1 + ... + pred_lagK
    """
    target_s = pd.Series(target_rv, dtype=float)
    pred_s   = pd.Series(predictor_rv, dtype=float)

    df_g = pd.DataFrame({
        "y":    target_s,
        "rv_d": target_s.shift(1),
        "rv_w": target_s.shift(1).rolling(5).mean(),
        "rv_m": target_s.shift(1).rolling(22).mean(),
    })
    for i in range(1, lags + 1):
        df_g[f"pred_lag{i}"] = pred_s.shift(i)

    df_g.dropna(inplace=True)
    y_g = df_g["y"].values
    n_g = len(y_g)

    har_cols  = ["rv_d", "rv_w", "rv_m"]
    pred_cols = [f"pred_lag{i}" for i in range(1, lags + 1)]

    X_r = df_g[har_cols].values
    X_u = df_g[pred_cols + har_cols].values  # unrestricted

    _, _, resid_r = ols_fit(X_r, y_g)
    _, _, resid_u = ols_fit(X_u, y_g)

    rss_r = float(np.sum(resid_r ** 2))
    rss_u = float(np.sum(resid_u ** 2))
    k_r   = X_r.shape[1] + 1   # +1 for intercept
    k_u   = X_u.shape[1] + 1
    q     = k_u - k_r           # = lags

    f_stat = ((rss_r - rss_u) / q) / (rss_u / (n_g - k_u))
    p_val  = float(1.0 - stats.f.cdf(f_stat, dfn=q, dfd=n_g - k_u))
    print(f"    n={n_g}, RSS_r={rss_r:.6e}, RSS_u={rss_u:.6e}, F={f_stat:.4f}, p={p_val:.4f}")
    return float(f_stat), p_val


print("\n[K1381] === Granger Causality F-tests (lag=5) ===")
print("  TSMC -> 0050:")
granger_tsmc_f, granger_tsmc_p = granger_f_test(data["rv_0050"].values, data["rv_tsmc"].values, lags=5)
print("  MTK -> 0050:")
granger_mtk_f,  granger_mtk_p  = granger_f_test(data["rv_0050"].values, data["rv_mtk"].values,  lags=5)

granger_tests = {
    "TSMC_to_0050": {
        "f_stat":         round(granger_tsmc_f, 4),
        "p_value":        round(granger_tsmc_p, 4),
        "lags":           5,
        "significant_05": bool(granger_tsmc_p < 0.05),
    },
    "MTK_to_0050": {
        "f_stat":         round(granger_mtk_f, 4),
        "p_value":        round(granger_mtk_p, 4),
        "lags":           5,
        "significant_05": bool(granger_mtk_p < 0.05),
    },
}

# -----------------------------------------------------------------------
# Verdict
# -----------------------------------------------------------------------
n_harvey_wins = sum(
    1 for v in dm_tests.values()
    if v["harvey_pass"] and v["direction"] == "model2_wins"
)
n_granger_sig = sum(1 for v in granger_tests.values() if v["significant_05"])

if n_harvey_wins >= 2 and n_granger_sig >= 1:
    verdict_tag = "POSITIVE"
elif n_harvey_wins >= 1 or n_granger_sig >= 1:
    verdict_tag = "MIXED"
else:
    verdict_tag = "NULL"

best_oos_model = min(oos_qlike, key=oos_qlike.get)
har_oos_val    = oos_qlike["HAR"]
best_oos_val   = oos_qlike[best_oos_model]
improvement_pct = 100.0 * (har_oos_val - best_oos_val) / abs(har_oos_val)

key_findings = [
    f"Best OOS model: {best_oos_model} (QLIKE={best_oos_val:.6f}, {improvement_pct:+.2f}% vs HAR={har_oos_val:.6f})",
    f"Harvey (|t|>3.0) significant HAR-X wins: {n_harvey_wins}/5",
    f"Granger causality p<0.05: {n_granger_sig}/2 tech stocks",
    f"TSMC Granger to 0050: F={granger_tests['TSMC_to_0050']['f_stat']}, p={granger_tests['TSMC_to_0050']['p_value']}",
    f"MTK Granger to 0050: F={granger_tests['MTK_to_0050']['f_stat']}, p={granger_tests['MTK_to_0050']['p_value']}",
    f"DM t-stats: " + ", ".join(f"{k.replace(' vs HAR','')}={v['dm_t']}" for k, v in dm_tests.items()),
    f"Data cleaning: log-return outliers (|r|>0.5) masked as NaN to remove corporate action artifacts",
]

if verdict_tag == "POSITIVE":
    verdict_desc = f"{best_oos_model} significantly improves 0050.TW volatility prediction vs HAR (Harvey PASS, Granger significant)"
elif verdict_tag == "MIXED":
    verdict_desc = f"partial evidence — {best_oos_model} shows improvement but not all Harvey-pass or Granger significant"
else:
    verdict_desc = "tech sector volatility does not significantly predict 0050.TW beyond HAR baseline"

verdict_str = f"{verdict_tag} — {verdict_desc}"
print(f"\n[K1381] Verdict: {verdict_str}")

# -----------------------------------------------------------------------
# Save results JSON
# -----------------------------------------------------------------------
results = {
    "experiment_id": "k1381",
    "title": "Taiwan Tech Sector Vol as Leading Indicator for 0050.TW",
    "metadata": {
        "data_source": "paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv",
        "n_total":        n_total,
        "n_train":        n_train,
        "n_test":         n_test,
        "date_range":     f"{data.index[0].date()} to {data.index[-1].date()}",
        "rv_proxy":       "squared log return (Patton 2011)",
        "outlier_filter": f"|log-return| > {LOG_RETURN_THRESHOLD} masked as NaN",
        "forecast_clamp": f"predictions clamped to [{EPS_FORECAST}, inf)",
        "harvey_threshold": 3.0,
        "seed":           42,
    },
    "full_sample_qlike": {k: round(v, 6) for k, v in full_qlike.items()},
    "oos_qlike":         {k: round(v, 6) for k, v in oos_qlike.items()},
    "dm_tests":          dm_tests,
    "granger_tests":     granger_tests,
    "model_coefficients": {k: [round(c, 8) for c in v] for k, v in model_coefficients.items()},
    "verdict":      verdict_str,
    "key_findings": key_findings,
}

results_path = os.path.join(OUT_DIR, "k1381_results.json")
with open(results_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"[K1381] Results saved to {results_path}")

# -----------------------------------------------------------------------
# Plot: 2x3 subplots (figsize=(14,8))
# -----------------------------------------------------------------------
model_names = list(full_qlike.keys())
x_pos = np.arange(len(model_names))

fig, axes = plt.subplots(2, 3, figsize=(14, 8))
fig.suptitle("K1381: Taiwan Tech Sector Vol as Leading Indicator for 0050.TW\n"
             f"(n_total={n_total}, n_test={n_test}, Harvey threshold=3.0)", fontsize=12, fontweight="bold")

# Row 0 Col 0: Full-sample QLIKE
ax = axes[0, 0]
vals_full = [full_qlike[m] for m in model_names]
cols_full = ["steelblue" if m == "HAR" else "darkorange" for m in model_names]
bars0 = ax.bar(x_pos, vals_full, color=cols_full, edgecolor="black", linewidth=0.5)
ax.set_xticks(x_pos); ax.set_xticklabels(model_names, rotation=30, ha="right", fontsize=8)
ax.set_title("Full-Sample QLIKE (lower=better)", fontsize=9)
ax.set_ylabel("QLIKE")
for b, v in zip(bars0, vals_full):
    ax.text(b.get_x() + b.get_width()/2, b.get_height()*1.003, f"{v:.4f}",
            ha="center", va="bottom", fontsize=6.5)

# Row 0 Col 1: OOS QLIKE
ax = axes[0, 1]
vals_oos = [oos_qlike[m] for m in model_names]
cols_oos = ["steelblue" if m == "HAR" else "darkorange" for m in model_names]
bars1 = ax.bar(x_pos, vals_oos, color=cols_oos, edgecolor="black", linewidth=0.5)
ax.set_xticks(x_pos); ax.set_xticklabels(model_names, rotation=30, ha="right", fontsize=8)
ax.set_title("OOS QLIKE — 70/30 split (lower=better)", fontsize=9)
ax.set_ylabel("QLIKE")
for b, v in zip(bars1, vals_oos):
    ax.text(b.get_x() + b.get_width()/2, b.get_height()*1.003, f"{v:.4f}",
            ha="center", va="bottom", fontsize=6.5)

# Row 0 Col 2: DM t-statistics
ax = axes[0, 2]
dm_labels_short = [k.replace(" vs HAR", "") for k in dm_tests.keys()]
dm_t_vals = [dm_tests[k]["dm_t"] for k in dm_tests.keys()]
dm_cols = []
for v in dm_tests.values():
    if v["harvey_pass"] and v["direction"] == "model2_wins":
        dm_cols.append("green")
    elif v["harvey_pass"] and v["direction"] == "model1_wins":
        dm_cols.append("red")
    else:
        dm_cols.append("gray")
dm_x = np.arange(len(dm_labels_short))
ax.bar(dm_x, dm_t_vals, color=dm_cols, edgecolor="black", linewidth=0.5)
ax.axhline(y=3.0,  color="red",   linestyle="--", linewidth=1.2, label="|t|=3.0 Harvey")
ax.axhline(y=-3.0, color="red",   linestyle="--", linewidth=1.2)
ax.axhline(y=0,    color="black", linestyle="-",  linewidth=0.6)
ax.set_xticks(dm_x); ax.set_xticklabels(dm_labels_short, rotation=30, ha="right", fontsize=8)
ax.set_title("DM t-stat vs HAR (|t|>3.0 = Harvey pass)", fontsize=9)
ax.set_ylabel("DM t-statistic")
ax.legend(fontsize=7)

# Row 1 Col 0: Full-sample QLIKE improvement vs HAR (%)
ax = axes[1, 0]
har_fq = full_qlike["HAR"]
imp_full = {m: 100*(har_fq - v)/abs(har_fq) for m, v in full_qlike.items() if m != "HAR"}
imp_names = list(imp_full.keys())
imp_vals  = list(imp_full.values())
imp_cols  = ["green" if v > 0 else "red" for v in imp_vals]
imp_x     = np.arange(len(imp_names))
ax.bar(imp_x, imp_vals, color=imp_cols, edgecolor="black", linewidth=0.5)
ax.axhline(y=0, color="black", linewidth=0.8)
ax.set_xticks(imp_x); ax.set_xticklabels(imp_names, rotation=30, ha="right", fontsize=8)
ax.set_title("Full-Sample QLIKE Improvement vs HAR (%)", fontsize=9)
ax.set_ylabel("Improvement (%)")
for xi, v in zip(imp_x, imp_vals):
    ax.text(xi, v + (0.02 if v >= 0 else -0.05), f"{v:+.2f}%", ha="center", va="bottom", fontsize=7)

# Row 1 Col 1: OOS QLIKE improvement vs HAR (%)
ax = axes[1, 1]
har_oq = oos_qlike["HAR"]
imp_oos  = {m: 100*(har_oq - v)/abs(har_oq) for m, v in oos_qlike.items() if m != "HAR"}
oos_names = list(imp_oos.keys())
oos_vals  = list(imp_oos.values())
oos_cols  = ["green" if v > 0 else "red" for v in oos_vals]
oos_imp_x = np.arange(len(oos_names))
ax.bar(oos_imp_x, oos_vals, color=oos_cols, edgecolor="black", linewidth=0.5)
ax.axhline(y=0, color="black", linewidth=0.8)
ax.set_xticks(oos_imp_x); ax.set_xticklabels(oos_names, rotation=30, ha="right", fontsize=8)
ax.set_title("OOS QLIKE Improvement vs HAR (%)", fontsize=9)
ax.set_ylabel("Improvement (%)")
for xi, v in zip(oos_imp_x, oos_vals):
    ax.text(xi, v + (0.02 if v >= 0 else -0.05), f"{v:+.2f}%", ha="center", va="bottom", fontsize=7)

# Row 1 Col 2: Granger F-statistics
ax = axes[1, 2]
g_names  = ["TSMC→0050", "MTK→0050"]
g_fvals  = [granger_tests["TSMC_to_0050"]["f_stat"], granger_tests["MTK_to_0050"]["f_stat"]]
g_pvals  = [granger_tests["TSMC_to_0050"]["p_value"], granger_tests["MTK_to_0050"]["p_value"]]
g_cols   = ["green" if p < 0.05 else "gray" for p in g_pvals]
g_x      = np.arange(len(g_names))
g_bars   = ax.bar(g_x, g_fvals, color=g_cols, edgecolor="black", linewidth=0.5)
ax.set_xticks(g_x); ax.set_xticklabels(g_names, fontsize=10)
ax.set_title("Granger Causality F-stat (lag=5)\n(green = p<0.05 significant)", fontsize=9)
ax.set_ylabel("F-statistic")
for gb, p in zip(g_bars, g_pvals):
    ax.text(gb.get_x() + gb.get_width()/2, gb.get_height()*1.02,
            f"p={p:.3f}", ha="center", va="bottom", fontsize=9)

plt.tight_layout()
plot_path = os.path.join(OUT_DIR, "k1381_forecast_comparison.png")
plt.savefig(plot_path, dpi=150, bbox_inches="tight")
plt.close()
print(f"[K1381] Plot saved to {plot_path}")

print("\n[K1381] ===== Experiment completed successfully =====")
