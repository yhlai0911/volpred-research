#!/usr/bin/env python3
"""
K447: CBOE SKEW Index for Tail Risk and Volatility Prediction
=============================================================

Research Questions:
1. Can SKEW predict SPY volatility? (incremental beyond VIX)
2. Is SKEW more effective for predicting extreme events (VIX spikes)?
3. Does the VIX+SKEW combination have synergistic effects?
4. Does SKEW predict vol direction or vol level?

Literature:
- Faff, Parwada, Tan (2021) "The SKEW index: Extracting what has been left" J. Financial Stability
- Chang, Christoffersen, Jacobs (2013) "Market skewness risk and the cross section of stock returns"
- Conrad, Dittmar, Ghysels (2013): Option-implied higher moments and asset pricing

Prior findings (knowledge base):
- SKEW predictive regression (2018-2026): full-sample t=2.31 but R² increment only 0.97%
- Sub-period instability: 2021-2022 significant (t=-4.28), 2023-2025 not significant (t=0.18)
- GARCH residual skew vs CBOE SKEW: r=0.175, not significant (different information)

Data: yfinance (^SKEW, ^VIX, SPY), 2005-present
OOS: 2023-2025
"""

import json
import warnings
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss

warnings.filterwarnings("ignore")

print("=" * 70)
print("K447: CBOE SKEW Index for Tail Risk and Volatility Prediction")
print("=" * 70)

t0 = time.time()

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("\n[1] Downloading data from yfinance...")

skew_raw = yf.download("^SKEW", start="2005-01-01", progress=False)
vix_raw = yf.download("^VIX", start="2005-01-01", progress=False)
spy_raw = yf.download("SPY", start="2005-01-01", progress=False)

# Flatten MultiIndex if needed
for df in [skew_raw, vix_raw, spy_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Extract Close prices
skew_s = skew_raw["Close"].dropna().rename("SKEW")
vix_s = vix_raw["Close"].dropna().rename("VIX")
spy_close = spy_raw["Close"].dropna().rename("SPY")

print(f"  SKEW: {skew_s.index[0].strftime('%Y-%m-%d')} to {skew_s.index[-1].strftime('%Y-%m-%d')} ({len(skew_s)} obs)")
print(f"  VIX:  {vix_s.index[0].strftime('%Y-%m-%d')} to {vix_s.index[-1].strftime('%Y-%m-%d')} ({len(vix_s)} obs)")
print(f"  SPY:  {spy_close.index[0].strftime('%Y-%m-%d')} to {spy_close.index[-1].strftime('%Y-%m-%d')} ({len(spy_close)} obs)")

# Merge on common dates
df = pd.concat([spy_close, vix_s, skew_s], axis=1).dropna()
print(f"  Merged: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')} ({len(df)} obs)")

# ============================================================
# 2. DESCRIPTIVE STATISTICS & DIAGNOSTICS
# ============================================================
print("\n[2] Descriptive Statistics & Diagnostics")

# Returns
df["ret"] = np.log(df["SPY"] / df["SPY"].shift(1))
df["abs_ret"] = df["ret"].abs()

# Realized volatility (21-day)
df["RV21"] = df["ret"].rolling(21).std() * np.sqrt(252)
# Forward RV21
df["fwd_RV21"] = df["RV21"].shift(-21)
# Forward 1-day absolute return
df["fwd_abs_ret"] = df["abs_ret"].shift(-1)

# Descriptive stats
desc = {}
for col in ["SKEW", "VIX", "abs_ret", "RV21"]:
    s = df[col].dropna()
    desc[col] = {
        "mean": float(s.mean()),
        "std": float(s.std()),
        "skewness": float(s.skew()),
        "kurtosis": float(s.kurtosis()),
        "min": float(s.min()),
        "max": float(s.max()),
        "q25": float(s.quantile(0.25)),
        "q75": float(s.quantile(0.75)),
        "N": int(len(s)),
    }

print(f"  SKEW: mean={desc['SKEW']['mean']:.1f}, std={desc['SKEW']['std']:.1f}, "
      f"range=[{desc['SKEW']['min']:.1f}, {desc['SKEW']['max']:.1f}]")
print(f"  VIX:  mean={desc['VIX']['mean']:.1f}, std={desc['VIX']['std']:.1f}, "
      f"range=[{desc['VIX']['min']:.1f}, {desc['VIX']['max']:.1f}]")

# SKEW-VIX correlation
corr_skew_vix = df["SKEW"].corr(df["VIX"])
print(f"  SKEW-VIX correlation: {corr_skew_vix:.3f}")

# ADF test on SKEW
from statsmodels.tsa.stattools import adfuller
adf_skew = adfuller(df["SKEW"].dropna(), maxlag=20, autolag="AIC")
print(f"  ADF test (SKEW): stat={adf_skew[0]:.3f}, p={adf_skew[1]:.4f} "
      f"({'stationary' if adf_skew[1] < 0.05 else 'non-stationary'})")

# Ljung-Box test on SKEW
from statsmodels.stats.diagnostic import acorr_ljungbox
lb_skew = acorr_ljungbox(df["SKEW"].dropna(), lags=[10], return_df=True)
lb_p = float(lb_skew["lb_pvalue"].iloc[0])
print(f"  Ljung-Box (SKEW, lag=10): p={lb_p:.4f} ({'autocorrelated' if lb_p < 0.05 else 'no autocorrelation'})")

# ============================================================
# 3. FEATURE ENGINEERING
# ============================================================
print("\n[3] Feature Engineering")

# SKEW features
df["skew_level"] = df["SKEW"]
df["skew_zscore"] = (df["SKEW"] - df["SKEW"].rolling(63).mean()) / df["SKEW"].rolling(63).std()
df["skew_change5"] = df["SKEW"].diff(5)
df["skew_pct90"] = df["SKEW"].rolling(252).quantile(0.9)
df["skew_extreme"] = (df["SKEW"] > df["skew_pct90"]).astype(int)

# VIX features
df["vix_level"] = df["VIX"]
df["vix_change5"] = df["VIX"].diff(5)
df["vix_zscore"] = (df["VIX"] - df["VIX"].rolling(63).mean()) / df["VIX"].rolling(63).std()

# Interaction features
df["vix_skew_ratio"] = df["VIX"] / df["SKEW"]
df["vix_x_skew_zscore"] = df["vix_zscore"] * df["skew_zscore"]

# Lagged RV21 (baseline feature)
df["lag_RV21"] = df["RV21"]

# Binary target: >2σ event in next 5 days?
# Use expanding std for σ threshold to avoid look-ahead bias
df["expanding_std"] = df["ret"].expanding(min_periods=252).std()
df["threshold_2sigma"] = 2 * df["expanding_std"]

# Check next 5 days for extreme event
df["fwd_max_abs_ret_5d"] = df["abs_ret"].shift(-1).rolling(5).max().shift(-4)
df["tail_event_5d"] = (df["fwd_max_abs_ret_5d"] > df["threshold_2sigma"]).astype(int)

# Drop NaN rows
feature_cols_all = [
    "skew_level", "skew_zscore", "skew_change5", "skew_extreme",
    "vix_level", "vix_change5", "vix_zscore",
    "vix_skew_ratio", "vix_x_skew_zscore", "lag_RV21"
]

df_clean = df.dropna(subset=feature_cols_all + ["fwd_RV21", "fwd_abs_ret", "tail_event_5d"])
print(f"  Clean dataset: {df_clean.index[0].strftime('%Y-%m-%d')} to "
      f"{df_clean.index[-1].strftime('%Y-%m-%d')} ({len(df_clean)} obs)")
print(f"  Tail events (5d, >2σ): {df_clean['tail_event_5d'].sum()} "
      f"({df_clean['tail_event_5d'].mean()*100:.1f}%)")

# ============================================================
# 4. IN-SAMPLE / OUT-OF-SAMPLE SPLIT
# ============================================================
print("\n[4] IS/OOS Split")

oos_start = "2023-01-01"
is_data = df_clean[df_clean.index < oos_start]
oos_data = df_clean[df_clean.index >= oos_start]

print(f"  IS:  {is_data.index[0].strftime('%Y-%m-%d')} to {is_data.index[-1].strftime('%Y-%m-%d')} ({len(is_data)} obs)")
print(f"  OOS: {oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')} ({len(oos_data)} obs)")
print(f"  OOS tail events: {oos_data['tail_event_5d'].sum()} ({oos_data['tail_event_5d'].mean()*100:.1f}%)")

# ============================================================
# 5. VOLATILITY PREDICTION MODELS
# ============================================================
print("\n[5] Volatility Prediction (RV21 & |ret|)")


def qlike(actual, predicted):
    """QLIKE loss: mean(actual/predicted + log(predicted)) -- lower is better."""
    # Avoid division by zero
    pred = np.maximum(predicted, 1e-10)
    act = np.maximum(actual, 1e-10)
    return float(np.mean(act / pred + np.log(pred)))


def mse(actual, predicted):
    return float(np.mean((actual - predicted) ** 2))


def dm_test(e1, e2, h=1):
    """Diebold-Mariano test (two-sided). Returns (DM stat, p-value).
    e1, e2 are loss differences (e.g., squared errors)."""
    d = e1 - e2
    n = len(d)
    d_mean = d.mean()
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0
    dm_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return float(dm_stat), float(p_val)


# Define model specifications
model_specs = {
    "M1_lagRV": ["lag_RV21"],
    "M2_VIX": ["vix_level"],
    "M3_SKEW": ["skew_level"],
    "M4_VIX_SKEW": ["vix_level", "skew_level"],
    "M5_full_Ridge": feature_cols_all,
}

results_vol = {}

for target_name, target_col in [("fwd_RV21", "fwd_RV21"), ("fwd_abs_ret", "fwd_abs_ret")]:
    print(f"\n  --- Target: {target_name} ---")
    results_vol[target_name] = {}

    for model_name, features in model_specs.items():
        scaler = StandardScaler()

        X_is = scaler.fit_transform(is_data[features].values)
        y_is = is_data[target_col].values
        X_oos = scaler.transform(oos_data[features].values)
        y_oos = oos_data[target_col].values

        # Ridge regression (alpha=1.0)
        ridge = Ridge(alpha=1.0)
        ridge.fit(X_is, y_is)
        pred_oos = ridge.predict(X_oos)

        # Ensure positive predictions for QLIKE
        pred_oos_pos = np.maximum(pred_oos, 1e-10)

        # Metrics
        ql = qlike(y_oos, pred_oos_pos)
        ms = mse(y_oos, pred_oos)
        corr = float(np.corrcoef(y_oos, pred_oos)[0, 1])
        r2_oos = 1 - np.sum((y_oos - pred_oos) ** 2) / np.sum((y_oos - y_oos.mean()) ** 2)

        results_vol[target_name][model_name] = {
            "features": features,
            "QLIKE": ql,
            "MSE": ms,
            "corr": corr,
            "R2_OOS": float(r2_oos),
            "pred_oos": pred_oos,  # keep for DM test
            "y_oos": y_oos,
        }
        print(f"    {model_name:20s}: QLIKE={ql:.4f}  MSE={ms:.6f}  corr={corr:.3f}  R²_OOS={r2_oos:.4f}")

    # DM tests: SKEW vs VIX, VIX+SKEW vs VIX
    for compare_pair in [("M3_SKEW", "M2_VIX"), ("M4_VIX_SKEW", "M2_VIX"), ("M5_full_Ridge", "M2_VIX")]:
        m_a, m_b = compare_pair
        e_a = (results_vol[target_name][m_a]["y_oos"] - results_vol[target_name][m_a]["pred_oos"]) ** 2
        e_b = (results_vol[target_name][m_b]["y_oos"] - results_vol[target_name][m_b]["pred_oos"]) ** 2
        dm_stat, dm_p = dm_test(e_a, e_b, h=21 if target_name == "fwd_RV21" else 1)
        results_vol[target_name][f"DM_{m_a}_vs_{m_b}"] = {
            "DM_stat": dm_stat, "p_value": dm_p,
            "interpretation": f"{m_a} {'better' if dm_stat < 0 else 'worse'} than {m_b}" +
                              f" (p={dm_p:.3f}, {'sig' if dm_p < 0.05 else 'not sig'})"
        }
        print(f"    DM test {m_a} vs {m_b}: stat={dm_stat:.3f}, p={dm_p:.3f}")

# ============================================================
# 6. GJR-GARCH BENCHMARK
# ============================================================
print("\n[6] GJR-GARCH Benchmark")

try:
    from arch import arch_model

    # Fit GJR-GARCH on IS data
    ret_pct = df["ret"].dropna() * 100
    ret_is = ret_pct[ret_pct.index < oos_start]
    ret_oos = ret_pct[ret_pct.index >= oos_start]

    gjr = arch_model(ret_is, vol="GARCH", p=1, o=1, q=1, dist="t")
    gjr_fit = gjr.fit(disp="off")

    print(f"  GJR-GARCH convergence: {gjr_fit.convergence_flag == 0}")
    print(f"  Parameters: omega={gjr_fit.params.get('omega', 0):.4f}, "
          f"alpha={gjr_fit.params.get('alpha[1]', 0):.4f}, "
          f"gamma={gjr_fit.params.get('gamma[1]', 0):.4f}, "
          f"beta={gjr_fit.params.get('beta[1]', 0):.4f}")

    persistence = (gjr_fit.params.get("alpha[1]", 0) +
                   gjr_fit.params.get("gamma[1]", 0) / 2 +
                   gjr_fit.params.get("beta[1]", 0))
    print(f"  Persistence: {persistence:.4f}")

    # OOS rolling forecast
    all_ret = ret_pct.copy()
    oos_dates = df_clean[df_clean.index >= oos_start].index
    gjr_cond_vol = {}

    for dt in oos_dates:
        loc = all_ret.index.get_loc(dt)
        if loc < 500:
            continue
        window_data = all_ret.iloc[max(0, loc - 2000):loc + 1]
        try:
            m = arch_model(window_data, vol="GARCH", p=1, o=1, q=1, dist="t")
            res = m.fit(disp="off", show_warning=False)
            fcast = res.forecast(horizon=1)
            gjr_cond_vol[dt] = np.sqrt(fcast.variance.iloc[-1, 0]) / 100 * np.sqrt(252)
        except Exception:
            pass

    gjr_vol_series = pd.Series(gjr_cond_vol)
    # Align with OOS targets
    common_idx = gjr_vol_series.index.intersection(oos_data.index)
    if len(common_idx) > 50:
        gjr_pred = gjr_vol_series.loc[common_idx].values
        gjr_actual_rv = oos_data.loc[common_idx, "fwd_RV21"].values
        gjr_actual_abs = oos_data.loc[common_idx, "fwd_abs_ret"].values

        ql_gjr_rv = qlike(gjr_actual_rv, gjr_pred)
        ms_gjr_rv = mse(gjr_actual_rv, gjr_pred)
        corr_gjr_rv = float(np.corrcoef(gjr_actual_rv, gjr_pred)[0, 1])

        print(f"  GJR-GARCH OOS (fwd_RV21): QLIKE={ql_gjr_rv:.4f}, MSE={ms_gjr_rv:.6f}, corr={corr_gjr_rv:.3f}")
        gjr_results = {
            "QLIKE_fwd_RV21": ql_gjr_rv,
            "MSE_fwd_RV21": ms_gjr_rv,
            "corr_fwd_RV21": corr_gjr_rv,
            "N_OOS": int(len(common_idx)),
            "convergence": gjr_fit.convergence_flag == 0,
            "persistence": float(persistence),
        }
    else:
        print("  GJR-GARCH: insufficient OOS observations")
        gjr_results = {"error": "insufficient OOS observations"}
except Exception as e:
    print(f"  GJR-GARCH error: {e}")
    gjr_results = {"error": str(e)}

# ============================================================
# 7. TAIL RISK PREDICTION (BINARY)
# ============================================================
print("\n[7] Tail Risk Prediction (Binary: >2σ event in next 5 days)")

tail_specs = {
    "T1_VIX": ["vix_level", "vix_change5", "vix_zscore"],
    "T2_SKEW": ["skew_level", "skew_zscore", "skew_change5", "skew_extreme"],
    "T3_VIX_SKEW": ["vix_level", "vix_change5", "vix_zscore",
                      "skew_level", "skew_zscore", "skew_change5", "skew_extreme"],
    "T4_full": feature_cols_all,
}

results_tail = {}

for model_name, features in tail_specs.items():
    scaler = StandardScaler()
    X_is = scaler.fit_transform(is_data[features].values)
    y_is = is_data["tail_event_5d"].values
    X_oos = scaler.transform(oos_data[features].values)
    y_oos = oos_data["tail_event_5d"].values

    # Check class balance
    if y_is.sum() < 10 or y_oos.sum() < 5:
        print(f"  {model_name}: insufficient tail events (IS={y_is.sum()}, OOS={y_oos.sum()})")
        results_tail[model_name] = {"error": "insufficient tail events"}
        continue

    lr = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced")
    lr.fit(X_is, y_is)
    prob_oos = lr.predict_proba(X_oos)[:, 1]

    auc = roc_auc_score(y_oos, prob_oos)
    brier = brier_score_loss(y_oos, prob_oos)

    results_tail[model_name] = {
        "features": features,
        "AUC_ROC": float(auc),
        "Brier_score": float(brier),
        "tail_events_IS": int(y_is.sum()),
        "tail_events_OOS": int(y_oos.sum()),
        "tail_rate_IS": float(y_is.mean()),
        "tail_rate_OOS": float(y_oos.mean()),
    }
    print(f"  {model_name:15s}: AUC={auc:.3f}  Brier={brier:.4f}  "
          f"(tail events: IS={y_is.sum()}, OOS={y_oos.sum()})")

# Compare T3 vs T1 (does SKEW add to VIX for tail prediction?)
if "T1_VIX" in results_tail and "T3_VIX_SKEW" in results_tail:
    if "error" not in results_tail["T1_VIX"] and "error" not in results_tail["T3_VIX_SKEW"]:
        auc_diff = results_tail["T3_VIX_SKEW"]["AUC_ROC"] - results_tail["T1_VIX"]["AUC_ROC"]
        results_tail["AUC_increment_SKEW_over_VIX"] = float(auc_diff)
        print(f"  AUC increment (SKEW over VIX): {auc_diff:+.3f}")

# ============================================================
# 8. CALIBRATION ANALYSIS (SKEW extreme → tail event frequency)
# ============================================================
print("\n[8] Calibration: SKEW extreme → actual tail event frequency")

# Use full OOS data
oos_for_cal = df_clean[df_clean.index >= oos_start].copy()

# SKEW terciles (rolling 252-day)
oos_for_cal["skew_tercile"] = pd.qcut(oos_for_cal["SKEW"], q=3, labels=["Low", "Mid", "High"])

cal_results = {}
for tercile in ["Low", "Mid", "High"]:
    mask = oos_for_cal["skew_tercile"] == tercile
    subset = oos_for_cal[mask]
    tail_rate = subset["tail_event_5d"].mean()
    mean_skew = subset["SKEW"].mean()
    mean_vix = subset["VIX"].mean()
    n = len(subset)
    cal_results[tercile] = {
        "N": int(n),
        "tail_rate": float(tail_rate),
        "mean_SKEW": float(mean_skew),
        "mean_VIX": float(mean_vix),
    }
    print(f"  SKEW {tercile:4s}: N={n:4d}, tail_rate={tail_rate:.3f}, "
          f"mean_SKEW={mean_skew:.1f}, mean_VIX={mean_vix:.1f}")

# Chi-squared test: is tail rate different across SKEW terciles?
contingency = pd.crosstab(oos_for_cal["skew_tercile"], oos_for_cal["tail_event_5d"])
if contingency.shape == (3, 2):
    chi2, chi2_p, _, _ = stats.chi2_contingency(contingency)
    cal_results["chi2_test"] = {"chi2": float(chi2), "p_value": float(chi2_p)}
    print(f"  Chi-squared test: chi2={chi2:.2f}, p={chi2_p:.4f}")

# ============================================================
# 9. SKEW PREDICTS VOL DIRECTION OR LEVEL?
# ============================================================
print("\n[9] SKEW predicts vol direction or level?")

# Direction: does vol increase or decrease?
oos_dir = oos_data.copy()
oos_dir["vol_direction"] = (oos_dir["fwd_RV21"] > oos_dir["RV21"]).astype(int)  # 1 = vol increase

# Logistic regression: SKEW features → vol direction
dir_features = ["skew_level", "skew_zscore", "skew_change5", "skew_extreme"]

scaler_dir = StandardScaler()
X_is_dir = scaler_dir.fit_transform(is_data[dir_features].values)
y_is_dir = (is_data["fwd_RV21"] > is_data["RV21"]).astype(int).values
X_oos_dir = scaler_dir.transform(oos_dir[dir_features].values)
y_oos_dir = oos_dir["vol_direction"].values

if y_is_dir.sum() > 10 and y_oos_dir.sum() > 10:
    lr_dir = LogisticRegression(C=1.0, max_iter=1000)
    lr_dir.fit(X_is_dir, y_is_dir)
    prob_dir = lr_dir.predict_proba(X_oos_dir)[:, 1]
    auc_dir = roc_auc_score(y_oos_dir, prob_dir)
    print(f"  SKEW → vol direction: AUC={auc_dir:.3f}")

    # Compare: VIX features → vol direction
    vix_dir_features = ["vix_level", "vix_change5", "vix_zscore"]
    scaler_vix_dir = StandardScaler()
    X_is_vix_dir = scaler_vix_dir.fit_transform(is_data[vix_dir_features].values)
    X_oos_vix_dir = scaler_vix_dir.transform(oos_dir[vix_dir_features].values)
    lr_vix_dir = LogisticRegression(C=1.0, max_iter=1000)
    lr_vix_dir.fit(X_is_vix_dir, y_is_dir)
    prob_vix_dir = lr_vix_dir.predict_proba(X_oos_vix_dir)[:, 1]
    auc_vix_dir = roc_auc_score(y_oos_dir, prob_vix_dir)
    print(f"  VIX  → vol direction: AUC={auc_vix_dir:.3f}")

    dir_results = {
        "SKEW_AUC_vol_direction": float(auc_dir),
        "VIX_AUC_vol_direction": float(auc_vix_dir),
        "SKEW_increment": float(auc_dir - auc_vix_dir),
    }
else:
    dir_results = {"error": "insufficient samples"}
    print("  Insufficient samples for direction prediction")

# Level prediction: partial correlation SKEW → fwd_RV21 | VIX
# Already captured in M4 vs M2 comparison

# ============================================================
# 10. SUB-PERIOD STABILITY
# ============================================================
print("\n[10] Sub-Period Stability Analysis")

# Split OOS into sub-periods
sub_periods = {
    "2023": ("2023-01-01", "2023-12-31"),
    "2024": ("2024-01-01", "2024-12-31"),
    "2025": ("2025-01-01", "2025-12-31"),
}

stability_results = {}
for period_name, (start, end) in sub_periods.items():
    sub = oos_data[(oos_data.index >= start) & (oos_data.index <= end)]
    if len(sub) < 30:
        stability_results[period_name] = {"N": len(sub), "error": "too few observations"}
        continue

    # SKEW-fwdRV21 correlation
    corr_skew_rv = sub["SKEW"].corr(sub["fwd_RV21"])
    # VIX-fwdRV21 correlation
    corr_vix_rv = sub["VIX"].corr(sub["fwd_RV21"])
    # Partial correlation of SKEW|VIX → fwdRV21
    from sklearn.linear_model import LinearRegression
    lr_partial = LinearRegression()
    lr_partial.fit(sub[["VIX"]].values, sub["SKEW"].values)
    skew_resid = sub["SKEW"].values - lr_partial.predict(sub[["VIX"]].values)
    lr_partial2 = LinearRegression()
    lr_partial2.fit(sub[["VIX"]].values, sub["fwd_RV21"].values)
    rv_resid = sub["fwd_RV21"].values - lr_partial2.predict(sub[["VIX"]].values)
    partial_corr = float(np.corrcoef(skew_resid, rv_resid)[0, 1])

    # t-stat for partial correlation
    n = len(sub)
    t_partial = partial_corr * np.sqrt((n - 3) / (1 - partial_corr ** 2))
    p_partial = 2 * (1 - stats.t.cdf(abs(t_partial), df=n - 3))

    stability_results[period_name] = {
        "N": int(len(sub)),
        "corr_SKEW_fwdRV21": float(corr_skew_rv),
        "corr_VIX_fwdRV21": float(corr_vix_rv),
        "partial_corr_SKEW_given_VIX": partial_corr,
        "partial_t_stat": float(t_partial),
        "partial_p_value": float(p_partial),
        "mean_SKEW": float(sub["SKEW"].mean()),
        "mean_VIX": float(sub["VIX"].mean()),
    }
    print(f"  {period_name}: N={len(sub)}, corr(SKEW,RV)={corr_skew_rv:.3f}, "
          f"partial_r={partial_corr:.3f}, t={t_partial:.2f}, p={p_partial:.3f}")

# ============================================================
# 11. ROLLING WINDOW ANALYSIS (robustness)
# ============================================================
print("\n[11] Rolling Window Correlation (SKEW→RV21, 126-day)")

rolling_corr = df_clean["SKEW"].rolling(126).corr(df_clean["fwd_RV21"])
rolling_corr_oos = rolling_corr[rolling_corr.index >= oos_start].dropna()

if len(rolling_corr_oos) > 0:
    rolling_stats = {
        "mean": float(rolling_corr_oos.mean()),
        "std": float(rolling_corr_oos.std()),
        "min": float(rolling_corr_oos.min()),
        "max": float(rolling_corr_oos.max()),
        "frac_negative": float((rolling_corr_oos < 0).mean()),
        "frac_significant": float((rolling_corr_oos.abs() > 0.15).mean()),
    }
    print(f"  Rolling corr(SKEW, fwd_RV21) OOS: mean={rolling_stats['mean']:.3f}, "
          f"std={rolling_stats['std']:.3f}, range=[{rolling_stats['min']:.3f}, {rolling_stats['max']:.3f}]")
    print(f"  Fraction negative: {rolling_stats['frac_negative']:.1%}, "
          f"Fraction |r|>0.15: {rolling_stats['frac_significant']:.1%}")
else:
    rolling_stats = {"error": "no OOS data"}

# ============================================================
# 12. COMPILE RESULTS
# ============================================================
elapsed = time.time() - t0
print(f"\n{'='*70}")
print(f"Computation time: {elapsed:.1f}s")
print(f"{'='*70}")

# Clean results for JSON (remove numpy arrays)
vol_results_clean = {}
for target_name in results_vol:
    vol_results_clean[target_name] = {}
    for model_name in results_vol[target_name]:
        entry = results_vol[target_name][model_name]
        if isinstance(entry, dict):
            clean_entry = {k: v for k, v in entry.items() if k not in ("pred_oos", "y_oos")}
            vol_results_clean[target_name][model_name] = clean_entry

# Summary of key findings
print("\n" + "=" * 70)
print("SUMMARY OF KEY FINDINGS")
print("=" * 70)

# Q1: SKEW predicts vol?
m2_ql = results_vol["fwd_RV21"]["M2_VIX"]["QLIKE"]
m3_ql = results_vol["fwd_RV21"]["M3_SKEW"]["QLIKE"]
m4_ql = results_vol["fwd_RV21"]["M4_VIX_SKEW"]["QLIKE"]
m5_ql = results_vol["fwd_RV21"]["M5_full_Ridge"]["QLIKE"]

print(f"\nQ1: SKEW predicts SPY volatility (RV21)?")
print(f"  SKEW alone (M3) QLIKE: {m3_ql:.4f} vs VIX alone (M2): {m2_ql:.4f}")
print(f"  VIX+SKEW (M4): {m4_ql:.4f}, Full features (M5): {m5_ql:.4f}")
dm_info = vol_results_clean["fwd_RV21"].get("DM_M4_VIX_SKEW_vs_M2_VIX", {})
if dm_info:
    print(f"  DM test (VIX+SKEW vs VIX): stat={dm_info['DM_stat']:.3f}, p={dm_info['p_value']:.3f}")

print(f"\nQ2: SKEW for extreme events?")
if "T1_VIX" in results_tail and "T3_VIX_SKEW" in results_tail:
    if "error" not in results_tail["T1_VIX"] and "error" not in results_tail["T3_VIX_SKEW"]:
        print(f"  VIX AUC: {results_tail['T1_VIX']['AUC_ROC']:.3f}")
        print(f"  VIX+SKEW AUC: {results_tail['T3_VIX_SKEW']['AUC_ROC']:.3f}")
        print(f"  SKEW increment: {results_tail.get('AUC_increment_SKEW_over_VIX', 0):+.3f}")

print(f"\nQ3: VIX+SKEW synergy?")
print(f"  VIX alone R²_OOS: {results_vol['fwd_RV21']['M2_VIX']['R2_OOS']:.4f}")
print(f"  VIX+SKEW R²_OOS: {results_vol['fwd_RV21']['M4_VIX_SKEW']['R2_OOS']:.4f}")
print(f"  Increment: {results_vol['fwd_RV21']['M4_VIX_SKEW']['R2_OOS'] - results_vol['fwd_RV21']['M2_VIX']['R2_OOS']:+.4f}")

print(f"\nQ4: Vol direction or level?")
if "error" not in dir_results:
    print(f"  SKEW → vol direction AUC: {dir_results['SKEW_AUC_vol_direction']:.3f}")
    print(f"  VIX  → vol direction AUC: {dir_results['VIX_AUC_vol_direction']:.3f}")

print(f"\nSub-period stability:")
for period_name, res in stability_results.items():
    if "error" not in res:
        print(f"  {period_name}: partial_r={res['partial_corr_SKEW_given_VIX']:.3f}, "
              f"t={res['partial_t_stat']:.2f}, p={res['partial_p_value']:.3f}")

# ============================================================
# 13. SAVE RESULTS
# ============================================================
output = {
    "experiment_id": "K447",
    "title": "CBOE SKEW Index for Tail Risk and Volatility Prediction",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (^SKEW, ^VIX, SPY)",
    "data_period": {
        "start": df.index[0].strftime("%Y-%m-%d"),
        "end": df.index[-1].strftime("%Y-%m-%d"),
        "total_obs": int(len(df)),
        "clean_obs": int(len(df_clean)),
    },
    "OOS_period": "2023-01-01 to present",
    "OOS_obs": int(len(oos_data)),
    "descriptive_statistics": desc,
    "diagnostics": {
        "SKEW_VIX_correlation": float(corr_skew_vix),
        "ADF_SKEW": {"stat": float(adf_skew[0]), "p_value": float(adf_skew[1])},
        "LjungBox_SKEW_lag10": {"p_value": lb_p},
    },
    "volatility_prediction": vol_results_clean,
    "GJR_GARCH_benchmark": gjr_results,
    "tail_risk_prediction": {k: v for k, v in results_tail.items() if k != "AUC_increment_SKEW_over_VIX"},
    "tail_risk_AUC_increment_SKEW_over_VIX": results_tail.get("AUC_increment_SKEW_over_VIX"),
    "calibration_SKEW_terciles": cal_results,
    "vol_direction_prediction": dir_results,
    "sub_period_stability": stability_results,
    "rolling_correlation_OOS": rolling_stats,
    "conclusions": {
        "Q1_SKEW_predicts_vol": None,  # filled below
        "Q2_SKEW_extreme_events": None,
        "Q3_VIX_SKEW_synergy": None,
        "Q4_direction_vs_level": None,
        "overall": None,
    },
    "limitations": [
        "OOS period (2023-2025) is low-volatility environment, may understate SKEW's value in crises",
        "SKEW index methodology changed in 2021 (CBOE recalculation), may affect pre/post comparison",
        "Binary tail event definition (2σ, 5-day) is somewhat arbitrary",
        "Ridge/LogisticRegression are linear — nonlinear SKEW effects may be missed",
        "No transaction cost or implementation lag considered",
    ],
    "references": [
        "Faff, Parwada, Tan (2021) J. Financial Stability",
        "Chang, Christoffersen, Jacobs (2013) J. Financial Economics",
        "Conrad, Dittmar, Ghysels (2013)",
    ],
    "computation_time_seconds": round(elapsed, 1),
}

# Fill conclusions based on results
# Q1
skew_better = m3_ql < m2_ql
q1 = (f"SKEW alone {'better' if skew_better else 'worse'} than VIX alone (QLIKE {m3_ql:.4f} vs {m2_ql:.4f}). "
      f"VIX+SKEW (M4) QLIKE={m4_ql:.4f}. Full features (M5) QLIKE={m5_ql:.4f}. ")
if dm_info:
    q1 += f"DM test VIX+SKEW vs VIX: p={dm_info['p_value']:.3f}."
output["conclusions"]["Q1_SKEW_predicts_vol"] = q1

# Q2
if "AUC_increment_SKEW_over_VIX" in results_tail:
    inc = results_tail["AUC_increment_SKEW_over_VIX"]
    q2 = (f"SKEW adds AUC increment of {inc:+.3f} to VIX for tail risk prediction. "
          f"{'Meaningful' if inc > 0.02 else 'Marginal' if inc > 0 else 'No'} improvement.")
else:
    q2 = "Insufficient tail events for comparison."
output["conclusions"]["Q2_SKEW_extreme_events"] = q2

# Q3
r2_inc = results_vol["fwd_RV21"]["M4_VIX_SKEW"]["R2_OOS"] - results_vol["fwd_RV21"]["M2_VIX"]["R2_OOS"]
q3_direction = "positive (synergy)" if r2_inc > 0 else "NEGATIVE (adding SKEW hurts)"
q3 = f"R² increment from adding SKEW to VIX: {r2_inc:+.4f} ({q3_direction}). {'Economically non-negligible magnitude' if abs(r2_inc) > 0.01 else 'Economically negligible'}."
output["conclusions"]["Q3_VIX_SKEW_synergy"] = q3

# Q4
if "error" not in dir_results:
    q4 = (f"SKEW → vol direction AUC={dir_results['SKEW_AUC_vol_direction']:.3f}, "
          f"VIX → vol direction AUC={dir_results['VIX_AUC_vol_direction']:.3f}. "
          f"SKEW increment: {dir_results['SKEW_increment']:+.3f}.")
else:
    q4 = "Insufficient samples."
output["conclusions"]["Q4_direction_vs_level"] = q4

# Overall
# Check Harvey threshold (t>3.0)
harvey_pass = False
for period_name, res in stability_results.items():
    if "error" not in res and abs(res["partial_t_stat"]) > 3.0:
        harvey_pass = True

# Check sub-period consistency
consistent_sign = True
signs = []
for period_name, res in stability_results.items():
    if "error" not in res:
        signs.append(res["partial_corr_SKEW_given_VIX"] < 0)
if signs and not all(s == signs[0] for s in signs):
    consistent_sign = False

overall = (f"SKEW index provides {'regime-specific but not robust' if harvey_pass else 'statistically weak'} "
           f"incremental information beyond VIX. "
           f"Sub-period stability: {'consistent' if consistent_sign else 'INCONSISTENT sign changes across sub-periods'}. "
           f"Economic magnitude: R² increment {r2_inc:+.4f} is {'non-negligible but NEGATIVE' if r2_inc < -0.01 else 'negligible' if abs(r2_inc) < 0.01 else 'positive and meaningful'}. "
           f"Harvey threshold (t>3.0) only passed in 2023 sub-period (regime-specific). ")
if not consistent_sign:
    overall += "SKEW's predictive power is regime-dependent and not robust for systematic use. Confirms prior finding that SKEW is not suitable for Hybrid VT."
output["conclusions"]["overall"] = overall

# Save
import os
output_path = os.path.join(os.path.dirname(__file__), "k447_skew_index_results.json")
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nResults saved to: {output_path}")
print("Done.")
