"""
K258: Options Implied Skew Dynamics — Can Skew Changes Predict Vol Better Than Level?
=====================================================================================
Background:
  K184 found SKEW *level* is absorbed by VIX (partial r ≈ 0 after controlling VIX).
  K210 found VIX/SKEW ratio adds negligible value.
  K212 found VIX sufficiency weakens in high-VIX regimes.

Hypothesis:
  SKEW *dynamics* (changes, acceleration, volatility-of-skew) may contain
  leading information about volatility changes that the static SKEW level
  and VIX do not capture. A rapidly rising SKEW could signal increasing
  tail risk BEFORE VIX reacts.

Data: SPY, ^VIX, ^SKEW daily from yfinance.
  IS: 2006-01-01 to 2022-12-31
  OOS: 2023-01-01 to 2024-12-31

Methodology:
  1. SKEW dynamics features (all lagged 1 day):
     - SKEW_level: raw SKEW index
     - SKEW_change_1d: daily change in SKEW
     - SKEW_change_5d: 5-day change in SKEW
     - SKEW_vol: rolling 22d std of SKEW (volatility of skew)
     - SKEW_VIX_ratio: SKEW/VIX
     - SKEW_acceleration: change_1d(t) - change_1d(t-1) (2nd derivative)
  2. Correlation + partial correlation (controlling VIX AND lagged RV)
  3. IS vs OOS stability of each feature
  4. Best features → GARCH-X model
  5. DM test vs GJR-GARCH baseline
  6. Regime-conditional: VIX<20 vs VIX≥20
  7. Vol direction prediction: does SKEW predict regime transitions?

Statistical standards: Harvey (2016) |t| > 3.0 threshold.
Real yfinance data only.

[提出: 用戶, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
import json
from datetime import datetime
from numpy.linalg import lstsq

np.random.seed(42)

results = {
    "experiment": "K258",
    "title": "Options Implied Skew Dynamics — Can Skew Changes Predict Vol Better Than Level?",
    "proposed_by": "User",
    "executed_by": "Claude",
    "timestamp": datetime.now().isoformat(),
    "data_source": "yfinance (SPY, ^VIX, ^SKEW)",
    "sections": {}
}

# ============================================================
# 1. Download data
# ============================================================
print("=" * 72)
print("K258: Options Implied Skew Dynamics")
print("     Can Skew Changes Predict Vol Better Than Level?")
print("=" * 72)

print("\n[1/9] Downloading data from yfinance...")

DATA_START = "2005-01-01"
DATA_END = "2025-12-31"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"

tickers = {
    "SPY": "SPY",
    "VIX": "^VIX",
    "SKEW": "^SKEW",
}

raw_data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end=DATA_END,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    raw_data[name] = df["close"].copy()
    raw_data[name].name = name
    print(f"  {name}: {len(df)} obs ({df.index[0].date()} ~ {df.index[-1].date()})")

# Build aligned DataFrame
prices = pd.DataFrame(raw_data)
prices = prices.dropna(subset=["VIX", "SKEW"])
prices = prices.ffill()
prices = prices.dropna()
print(f"  Aligned: {len(prices)} obs ({prices.index[0].date()} ~ {prices.index[-1].date()})")

results["sections"]["data"] = {
    "n_obs": len(prices),
    "date_range": f"{prices.index[0].date()} to {prices.index[-1].date()}",
    "skew_stats": {
        "mean": round(float(prices["SKEW"].mean()), 2),
        "std": round(float(prices["SKEW"].std()), 2),
        "min": round(float(prices["SKEW"].min()), 2),
        "max": round(float(prices["SKEW"].max()), 2),
    },
    "vix_stats": {
        "mean": round(float(prices["VIX"].mean()), 2),
        "std": round(float(prices["VIX"].std()), 2),
    },
}

# ============================================================
# 2. Feature engineering
# ============================================================
print("\n[2/9] Computing SKEW dynamics features...")

df = prices.copy()

# SPY returns
df["ret"] = np.log(df["SPY"] / df["SPY"].shift(1))

# Realized vol targets (forward-looking, annualized)
# For each day t, FwdRV_Xd = std(ret[t+1], ..., ret[t+X]) * sqrt(252)
rv_22d = df["ret"].rolling(22).std() * np.sqrt(252)
df["FwdRV_22d"] = rv_22d.shift(-22)

rv_5d = df["ret"].rolling(5).std() * np.sqrt(252)
df["FwdRV_5d"] = rv_5d.shift(-5)

# For 1d, use absolute return as vol proxy (annualized)
df["FwdRV_1d"] = df["ret"].shift(-1).abs() * np.sqrt(252)

# Lagged realized vol (22d)
df["RV_22d"] = df["ret"].rolling(22).std() * np.sqrt(252)

# VIX as annualized vol fraction
df["VIX_frac"] = df["VIX"] / 100.0

# === SKEW dynamics features (all lagged by 1 day for prediction) ===

# 1. SKEW level
df["SKEW_level"] = df["SKEW"].shift(1)

# 2. SKEW 1-day change
df["SKEW_change_1d"] = df["SKEW"].diff(1).shift(1)

# 3. SKEW 5-day change
df["SKEW_change_5d"] = df["SKEW"].diff(5).shift(1)

# 4. SKEW volatility: rolling 22d std of SKEW daily changes
df["SKEW_vol"] = df["SKEW"].diff(1).rolling(22).std().shift(1)

# 5. SKEW/VIX ratio (normalized)
df["SKEW_VIX_ratio"] = (df["SKEW"] / df["VIX"]).shift(1)

# 6. SKEW acceleration (2nd derivative): change in 1d change
skew_change_1d_unlagged = df["SKEW"].diff(1)
df["SKEW_acceleration"] = skew_change_1d_unlagged.diff(1).shift(1)

# VIX regime
df["VIX_regime"] = pd.cut(df["VIX"], bins=[0, 20, 100], labels=["Low (<20)", "High (>=20)"])

# Also finer regimes for detailed analysis
def classify_regime_fine(v):
    if v < 15:
        return "Low (<15)"
    elif v < 20:
        return "Normal (15-20)"
    elif v < 30:
        return "Elevated (20-30)"
    else:
        return "Crisis (>=30)"

df["VIX_regime_fine"] = df["VIX"].apply(classify_regime_fine)

# Lagged controls
df["VIX_lag1"] = df["VIX_frac"].shift(1)
df["RV_22d_lag1"] = df["RV_22d"].shift(1)

# Drop NaN on features (but NOT on all forward RV columns — handle per-horizon later)
df = df.dropna(subset=["SKEW_level", "SKEW_change_1d", "SKEW_change_5d",
                        "SKEW_vol", "SKEW_VIX_ratio", "SKEW_acceleration",
                        "VIX_lag1", "RV_22d_lag1"])
print(f"  After feature computation: {len(df)} obs")

# IS/OOS split
df_is = df[df.index < OOS_START]
df_oos = df[(df.index >= OOS_START) & (df.index <= OOS_END)]
print(f"  IS: {len(df_is)} obs ({df_is.index[0].date()} ~ {df_is.index[-1].date()})")
print(f"  OOS: {len(df_oos)} obs ({df_oos.index[0].date()} ~ {df_oos.index[-1].date()})")

# Regime distribution
for label, sdf in [("IS", df_is), ("OOS", df_oos)]:
    rc = sdf["VIX_regime"].value_counts()
    print(f"  {label} regime: " + ", ".join(f"{k}={v}" for k, v in rc.items()))

FEATURE_NAMES = [
    "SKEW_level",
    "SKEW_change_1d",
    "SKEW_change_5d",
    "SKEW_vol",
    "SKEW_VIX_ratio",
    "SKEW_acceleration",
]

FEATURE_LABELS = {
    "SKEW_level": "SKEW Level",
    "SKEW_change_1d": "SKEW Δ1d",
    "SKEW_change_5d": "SKEW Δ5d",
    "SKEW_vol": "SKEW Vol (22d)",
    "SKEW_VIX_ratio": "SKEW/VIX Ratio",
    "SKEW_acceleration": "SKEW Acceleration",
}

# ============================================================
# 3. Raw and partial correlations
# ============================================================
print("\n[3/9] Correlations with future realized vol...")

def partial_corr_multi(x, y, controls):
    """Partial correlation of x and y controlling for multiple variables.
    Returns (r_partial, t_stat, p_value, n)."""
    mask = ~np.isnan(x) & ~np.isnan(y)
    for c in controls:
        mask &= ~np.isnan(c)
    x_c = x[mask]
    y_c = y[mask]
    ctrl_c = np.column_stack([c[mask] for c in controls])
    n = len(x_c)
    if n < 10:
        return np.nan, np.nan, np.nan, n

    # Residualize x on controls
    X_ctrl = np.column_stack([np.ones(n), ctrl_c])
    beta_x, _, _, _ = lstsq(X_ctrl, x_c, rcond=None)
    resid_x = x_c - X_ctrl @ beta_x

    # Residualize y on controls
    beta_y, _, _, _ = lstsq(X_ctrl, y_c, rcond=None)
    resid_y = y_c - X_ctrl @ beta_y

    # Correlation of residuals
    r, p = stats.pearsonr(resid_x, resid_y)

    # t-stat: df = n - #controls - 2
    df_stat = n - ctrl_c.shape[1] - 2
    if abs(r) >= 1.0:
        t_stat = np.inf * np.sign(r)
    else:
        t_stat = r * np.sqrt(df_stat / (1 - r ** 2))

    return r, t_stat, p, n


HORIZONS = [("1d", "FwdRV_1d"), ("5d", "FwdRV_5d"), ("22d", "FwdRV_22d")]

corr_results = {}

for sample_name, sample_df in [("IS", df_is), ("OOS", df_oos)]:
    corr_results[sample_name] = {}

    print(f"\n  === {sample_name} ===")
    print(f"  {'Feature':<22} {'Horizon':>7} {'Raw r':>8} {'Part r|VIX':>12} {'t(VIX)':>8} "
          f"{'Part r|VIX+RV':>14} {'t(VIX+RV)':>10} {'Harvey':>7}")
    print(f"  {'-'*22} {'-'*7} {'-'*8} {'-'*12} {'-'*8} {'-'*14} {'-'*10} {'-'*7}")

    for feat in FEATURE_NAMES:
        corr_results[sample_name][feat] = {}

        for h_name, h_col in HORIZONS:
            target = sample_df[h_col].values
            feature = sample_df[feat].values
            vix = sample_df["VIX_lag1"].values
            rv_lag = sample_df["RV_22d_lag1"].values

            # Raw correlation
            mask_raw = ~np.isnan(feature) & ~np.isnan(target)
            if np.sum(mask_raw) < 10:
                corr_results[sample_name][feat][h_name] = {
                    "raw_r": None, "partial_r_vix": None, "t_partial_vix": None,
                    "partial_r_vix_rv": None, "t_partial_vix_rv": None,
                    "n": int(np.sum(mask_raw)), "passes_harvey": False,
                }
                print(f"  {FEATURE_LABELS[feat]:<22} {h_name:>7} {'N/A (insufficient data)':>60}")
                continue
            r_raw, p_raw = stats.pearsonr(feature[mask_raw], target[mask_raw])

            # Partial corr controlling for VIX only
            r_vix, t_vix, p_vix, n_vix = partial_corr_multi(feature, target, [vix])

            # Partial corr controlling for VIX + lagged RV
            r_both, t_both, p_both, n_both = partial_corr_multi(
                feature, target, [vix, rv_lag]
            )

            passes_harvey = abs(t_both) > 3.0 if not np.isnan(t_both) else False
            harvey_str = "PASS" if passes_harvey else "fail"

            corr_results[sample_name][feat][h_name] = {
                "raw_r": round(float(r_raw), 4),
                "partial_r_vix": round(float(r_vix), 4) if not np.isnan(r_vix) else None,
                "t_partial_vix": round(float(t_vix), 3) if not np.isnan(t_vix) else None,
                "partial_r_vix_rv": round(float(r_both), 4) if not np.isnan(r_both) else None,
                "t_partial_vix_rv": round(float(t_both), 3) if not np.isnan(t_both) else None,
                "n": int(n_both),
                "passes_harvey": bool(passes_harvey),
            }

            print(f"  {FEATURE_LABELS[feat]:<22} {h_name:>7} {r_raw:>8.4f} "
                  f"{r_vix:>12.4f} {t_vix:>8.3f} "
                  f"{r_both:>14.4f} {t_both:>10.3f} {harvey_str:>7}")

results["sections"]["correlations"] = corr_results

# ============================================================
# 4. IS vs OOS stability analysis
# ============================================================
print("\n[4/9] IS vs OOS stability of SKEW dynamics features...")

stability_results = {}

print(f"\n  {'Feature':<22} {'IS r(22d)':>10} {'OOS r(22d)':>11} {'IS t':>7} {'OOS t':>7} {'Stable?':>8}")
print(f"  {'-'*22} {'-'*10} {'-'*11} {'-'*7} {'-'*7} {'-'*8}")

for feat in FEATURE_NAMES:
    is_res = corr_results["IS"][feat]["22d"]
    oos_res = corr_results["OOS"][feat]["22d"]

    is_r = is_res["partial_r_vix_rv"] or 0
    oos_r = oos_res["partial_r_vix_rv"] or 0
    is_t = is_res["t_partial_vix_rv"] or 0
    oos_t = oos_res["t_partial_vix_rv"] or 0

    # Stable = same sign AND both significant or both not
    same_sign = (is_r * oos_r) > 0
    # Reasonable stability: OOS magnitude > 30% of IS magnitude
    mag_ratio = abs(oos_r) / abs(is_r) if abs(is_r) > 0.001 else 0
    stable = same_sign and mag_ratio > 0.3

    stability_results[feat] = {
        "is_partial_r": is_r,
        "oos_partial_r": oos_r,
        "is_t": is_t,
        "oos_t": oos_t,
        "same_sign": bool(same_sign),
        "magnitude_ratio": round(mag_ratio, 3),
        "stable": bool(stable),
    }

    stable_str = "YES" if stable else "NO"
    print(f"  {FEATURE_LABELS[feat]:<22} {is_r:>10.4f} {oos_r:>11.4f} {is_t:>7.2f} {oos_t:>7.2f} {stable_str:>8}")

results["sections"]["stability"] = stability_results

# ============================================================
# 5. Regime-conditional analysis: VIX<20 vs VIX>=20
# ============================================================
print("\n[5/9] Regime-conditional analysis (VIX<20 vs VIX>=20)...")

regime_results = {}

for regime_label in ["Low (<20)", "High (>=20)"]:
    regime_results[regime_label] = {}

    print(f"\n  === {regime_label} ===")
    print(f"  {'Feature':<22} {'Sample':>5} {'r|VIX+RV':>10} {'t':>8} {'n':>6} {'Harvey':>7}")
    print(f"  {'-'*22} {'-'*5} {'-'*10} {'-'*8} {'-'*6} {'-'*7}")

    for sample_name, sample_df in [("IS", df_is), ("OOS", df_oos)]:
        regime_mask = sample_df["VIX_regime"] == regime_label
        regime_df = sample_df[regime_mask]

        if len(regime_df) < 30:
            print(f"  {'(all features)':<22} {sample_name:>5} {'N/A':>10} {'N/A':>8} {len(regime_df):>6} {'N/A':>7}")
            continue

        regime_results[regime_label][sample_name] = {}

        for feat in FEATURE_NAMES:
            target = regime_df["FwdRV_22d"].values
            feature = regime_df[feat].values
            vix = regime_df["VIX_lag1"].values
            rv_lag = regime_df["RV_22d_lag1"].values

            r, t, p, n = partial_corr_multi(feature, target, [vix, rv_lag])

            passes = abs(t) > 3.0 if not np.isnan(t) else False
            harvey_str = "PASS" if passes else "fail"

            regime_results[regime_label][sample_name][feat] = {
                "partial_r": round(float(r), 4) if not np.isnan(r) else None,
                "t_stat": round(float(t), 3) if not np.isnan(t) else None,
                "n": int(n),
                "passes_harvey": bool(passes),
            }

            print(f"  {FEATURE_LABELS[feat]:<22} {sample_name:>5} "
                  f"{r:>10.4f} {t:>8.3f} {n:>6} {harvey_str:>7}")

results["sections"]["regime_conditional"] = regime_results

# ============================================================
# 6. GARCH-X models with best SKEW features
# ============================================================
print("\n[6/9] GARCH-X models with SKEW dynamics features...")

# Prepare returns for GARCH
spy_ret_is = df_is["ret"].dropna() * 100  # scale for arch package
spy_ret_oos = df_oos["ret"].dropna() * 100

# GJR-GARCH baseline (no exogenous)
print("\n  Fitting GJR-GARCH baseline...")

try:
    base_model = arch_model(spy_ret_is, vol="GARCH", p=1, o=1, q=1, dist="t")
    base_fit = base_model.fit(disp="off")
    base_aic = base_fit.aic
    base_bic = base_fit.bic
    print(f"    IS: AIC={base_aic:.2f}, BIC={base_bic:.2f}")

    # OOS forecasting with expanding window
    n_oos = len(df_oos)
    all_ret = pd.concat([spy_ret_is, spy_ret_oos])

    # Base model OOS forecasts
    base_forecasts = []
    for i in range(n_oos):
        train_end = len(spy_ret_is) + i
        train = all_ret.iloc[:train_end]

        try:
            m = arch_model(train, vol="GARCH", p=1, o=1, q=1, dist="t")
            fit = m.fit(disp="off", show_warning=False)
            fcast = fit.forecast(horizon=1)
            var_pred = fcast.variance.iloc[-1, 0]
            # Convert from daily percentage variance to annualized vol
            vol_pred = np.sqrt(var_pred) * np.sqrt(252) / 100
            base_forecasts.append(vol_pred)
        except Exception:
            base_forecasts.append(np.nan)

    base_forecasts = np.array(base_forecasts)
    print(f"    OOS: {np.sum(~np.isnan(base_forecasts))}/{n_oos} forecasts produced")

    garch_success = True
except Exception as e:
    print(f"    GARCH baseline failed: {e}")
    garch_success = False

# GARCH-X with each feature
garchx_results = {}

if garch_success:
    # For GARCH-X we try adding each feature as exogenous regressor
    # arch package GARCH-X: use x= parameter for variance equation
    # We test using OLS regression on variance forecasts as simpler approach

    print("\n  Testing GARCH + SKEW features via augmented forecast regression...")

    # Use base GARCH conditional variance + each feature → predict future RV
    oos_target = df_oos["FwdRV_22d"].values

    # Base GARCH prediction quality
    mask_valid = ~np.isnan(base_forecasts) & ~np.isnan(oos_target)
    if np.sum(mask_valid) > 30:
        # QLIKE loss
        h_base = base_forecasts[mask_valid]
        rv_actual = oos_target[mask_valid]

        eps = 1e-8
        h_pos = np.maximum(h_base, eps)
        rv_pos = np.maximum(rv_actual, eps)

        qlike_base = np.mean(np.log(h_pos ** 2) + (rv_pos ** 2) / (h_pos ** 2))
        mse_base = np.mean((rv_pos - h_pos) ** 2)

        print(f"\n    Base GJR-GARCH OOS: QLIKE={qlike_base:.4f}, MSE={mse_base:.6f}")
        garchx_results["baseline"] = {
            "qlike": round(float(qlike_base), 4),
            "mse": round(float(mse_base), 6),
        }

        # For each feature: combine GARCH forecast + feature in regression
        for feat in FEATURE_NAMES:
            feat_vals = df_oos[feat].values
            mask_feat = mask_valid & ~np.isnan(feat_vals)

            if np.sum(mask_feat) < 30:
                garchx_results[feat] = {"qlike": None, "note": "insufficient data"}
                continue

            h_f = base_forecasts[mask_feat]
            rv_f = oos_target[mask_feat]
            x_f = feat_vals[mask_feat]

            # Augmented regression: RV_future = a + b*GARCH_forecast + c*feature + e
            X_aug = np.column_stack([np.ones(len(h_f)), h_f, x_f])
            beta, _, _, _ = lstsq(X_aug, rv_f, rcond=None)

            pred_aug = X_aug @ beta
            pred_aug = np.maximum(pred_aug, eps)

            qlike_aug = np.mean(np.log(pred_aug ** 2) + (rv_f ** 2) / (pred_aug ** 2))
            mse_aug = np.mean((rv_f - pred_aug) ** 2)

            # DM test: GARCH baseline vs augmented
            loss_base_i = np.log(np.maximum(h_f, eps) ** 2) + (rv_f ** 2) / (np.maximum(h_f, eps) ** 2)
            loss_aug_i = np.log(pred_aug ** 2) + (rv_f ** 2) / (pred_aug ** 2)
            d = loss_base_i - loss_aug_i  # positive = augmented is better

            n_dm = len(d)
            d_bar = d.mean()
            lag = min(22, n_dm // 3)

            gamma_0 = np.var(d, ddof=1)
            nw_var = gamma_0
            for j in range(1, lag + 1):
                if len(d[j:]) > 1:
                    gamma_j = np.cov(d[j:], d[:-j])[0, 1]
                    nw_var += 2 * (1 - j / (lag + 1)) * gamma_j

            se_dm = np.sqrt(max(nw_var, 1e-16) / n_dm)
            dm_t = d_bar / se_dm if se_dm > 0 else 0
            dm_p = 2 * (1 - stats.norm.cdf(abs(dm_t)))

            passes_dm = abs(dm_t) > 3.0

            garchx_results[feat] = {
                "qlike": round(float(qlike_aug), 4),
                "mse": round(float(mse_aug), 6),
                "delta_qlike": round(float(qlike_base - qlike_aug), 4),
                "dm_t": round(float(dm_t), 3),
                "dm_p": round(float(dm_p), 4),
                "passes_harvey": bool(passes_dm),
                "beta_feature": round(float(beta[2]), 6),
                "n": int(n_dm),
            }

            sig_str = "***" if passes_dm else ("**" if abs(dm_t) > 2.0 else ("*" if abs(dm_t) > 1.65 else ""))
            print(f"    + {FEATURE_LABELS[feat]:<22} QLIKE={qlike_aug:.4f} "
                  f"(Δ={qlike_base - qlike_aug:+.4f}) DM t={dm_t:.3f}{sig_str}")

results["sections"]["garchx"] = garchx_results

# ============================================================
# 7. Vol direction prediction: does SKEW predict regime transitions?
# ============================================================
print("\n[7/9] Does SKEW dynamics predict vol direction changes?")

# Define vol increase: FwdRV_22d > current RV_22d (vol going up)
df["vol_direction"] = (df["FwdRV_22d"] > df["RV_22d"]).astype(int)  # 1 = vol increases

# Define regime transition: moving from Low to High VIX regime in next 22 days
# Simpler: will VIX increase by more than 20% in next 22 days?
df["VIX_fwd_22d"] = df["VIX"].shift(-22)
df["VIX_will_spike"] = ((df["VIX_fwd_22d"] / df["VIX"]) > 1.2).astype(float)

direction_results = {}

for sample_name, sample_df in [("IS", df_is), ("OOS", df_oos)]:
    # Refresh targets for this sample
    sdf = sample_df.copy()
    sdf["vol_direction"] = (sdf["FwdRV_22d"] > sdf["RV_22d"]).astype(int)
    sdf["VIX_fwd_22d"] = df["VIX"].shift(-22).reindex(sdf.index)
    sdf["VIX_will_spike"] = ((sdf["VIX_fwd_22d"] / sdf["VIX"]) > 1.2).astype(float)

    direction_results[sample_name] = {}

    print(f"\n  === {sample_name} ===")
    print(f"  {'Feature':<22} {'VolDir AUC':>11} {'VolDir t':>9} {'Spike AUC':>11} {'Spike t':>9}")
    print(f"  {'-'*22} {'-'*11} {'-'*9} {'-'*11} {'-'*9}")

    for feat in FEATURE_NAMES:
        feat_vals = sdf[feat].values

        # Vol direction prediction
        vol_dir = sdf["vol_direction"].values
        mask1 = ~np.isnan(feat_vals) & ~np.isnan(vol_dir)

        if np.sum(mask1) < 30:
            direction_results[sample_name][feat] = {"vol_dir_auc": None, "spike_auc": None}
            continue

        x1 = feat_vals[mask1]
        y1 = vol_dir[mask1]

        # Point-biserial correlation as proxy for AUC
        r_dir, p_dir = stats.pointbiserialr(y1, x1)
        t_dir = r_dir * np.sqrt((len(y1) - 2) / (1 - r_dir ** 2)) if abs(r_dir) < 1 else np.inf

        # Simple AUC approximation: P(feature|vol_up) > P(feature|vol_down)
        x_up = x1[y1 == 1]
        x_down = x1[y1 == 0]
        if len(x_up) > 0 and len(x_down) > 0:
            # Mann-Whitney U → AUC
            u_stat, u_p = stats.mannwhitneyu(x_up, x_down, alternative="two-sided")
            auc_dir = u_stat / (len(x_up) * len(x_down))
        else:
            auc_dir = 0.5

        # VIX spike prediction
        spike = sdf["VIX_will_spike"].values
        mask2 = ~np.isnan(feat_vals) & ~np.isnan(spike)

        if np.sum(mask2) < 30 or np.sum(spike[mask2]) < 5:
            auc_spike = np.nan
            t_spike = np.nan
        else:
            x2 = feat_vals[mask2]
            y2 = spike[mask2]
            r_spike, p_spike = stats.pointbiserialr(y2, x2)
            t_spike = r_spike * np.sqrt((len(y2) - 2) / (1 - r_spike ** 2)) if abs(r_spike) < 1 else np.inf

            x_sp = x2[y2 == 1]
            x_nsp = x2[y2 == 0]
            if len(x_sp) > 0 and len(x_nsp) > 0:
                u2, _ = stats.mannwhitneyu(x_sp, x_nsp, alternative="two-sided")
                auc_spike = u2 / (len(x_sp) * len(x_nsp))
            else:
                auc_spike = 0.5

        direction_results[sample_name][feat] = {
            "vol_dir_auc": round(float(auc_dir), 4),
            "vol_dir_t": round(float(t_dir), 3),
            "spike_auc": round(float(auc_spike), 4) if not np.isnan(auc_spike) else None,
            "spike_t": round(float(t_spike), 3) if not np.isnan(t_spike) else None,
        }

        auc_sp_str = f"{auc_spike:.4f}" if not np.isnan(auc_spike) else "N/A"
        t_sp_str = f"{t_spike:.3f}" if not np.isnan(t_spike) else "N/A"
        print(f"  {FEATURE_LABELS[feat]:<22} {auc_dir:>11.4f} {t_dir:>9.3f} {auc_sp_str:>11} {t_sp_str:>9}")

results["sections"]["direction_prediction"] = direction_results

# ============================================================
# 8. Multi-period robustness
# ============================================================
print("\n[8/9] Multi-period robustness (partial r|VIX+RV for 22d horizon)...")

oos_periods = [
    ("2011-2012", "2011-01-01", "2012-12-31"),
    ("2015-2016", "2015-01-01", "2016-12-31"),
    ("2018-2019", "2018-01-01", "2019-12-31"),
    ("2020-2021", "2020-01-01", "2021-12-31"),  # includes COVID
    ("2023-2024", "2023-01-01", "2024-12-31"),
]

robustness_results = {}

print(f"\n  {'Feature':<22}", end="")
for period_name, _, _ in oos_periods:
    print(f" {period_name:>12}", end="")
print(f" {'#Pass':>7} {'Consistent':>11}")

print(f"  {'-'*22}", end="")
for _ in oos_periods:
    print(f" {'-'*12}", end="")
print(f" {'-'*7} {'-'*11}")

for feat in FEATURE_NAMES:
    robustness_results[feat] = {}
    n_pass = 0
    signs = []

    print(f"  {FEATURE_LABELS[feat]:<22}", end="")

    for period_name, p_start, p_end in oos_periods:
        period_df = df[(df.index >= p_start) & (df.index <= p_end)]

        if len(period_df) < 30:
            robustness_results[feat][period_name] = {"r": None, "t": None, "n": len(period_df)}
            print(f" {'N/A':>12}", end="")
            continue

        target = period_df["FwdRV_22d"].values
        feature = period_df[feat].values
        vix = period_df["VIX_lag1"].values
        rv_lag = period_df["RV_22d_lag1"].values

        r, t, p, n = partial_corr_multi(feature, target, [vix, rv_lag])

        passes = abs(t) > 3.0 if not np.isnan(t) else False
        if passes:
            n_pass += 1
        if not np.isnan(r):
            signs.append(np.sign(r))

        robustness_results[feat][period_name] = {
            "r": round(float(r), 4) if not np.isnan(r) else None,
            "t": round(float(t), 3) if not np.isnan(t) else None,
            "n": int(n),
            "passes_harvey": bool(passes),
        }

        flag = "*" if passes else ""
        r_str = f"{r:.4f}{flag}" if not np.isnan(r) else "N/A"
        print(f" {r_str:>12}", end="")

    # Consistency: same sign across all periods
    consistent = len(signs) >= 3 and (all(s > 0 for s in signs) or all(s < 0 for s in signs))
    consistent_str = "YES" if consistent else "NO"
    print(f" {n_pass:>7} {consistent_str:>11}")

    robustness_results[feat]["n_harvey_passes"] = n_pass
    robustness_results[feat]["sign_consistent"] = bool(consistent)

results["sections"]["robustness"] = robustness_results

# ============================================================
# 9. Regime-conditional GARCH-X (VIX<20 vs VIX>=20)
# ============================================================
print("\n[9/9] Regime-conditional GARCH-X (K212 insight: test separately)...")

if garch_success and len(garchx_results) > 0:
    regime_garchx_results = {}

    for regime_label in ["Low (<20)", "High (>=20)"]:
        regime_mask_oos = df_oos["VIX_regime"] == regime_label
        regime_oos = df_oos[regime_mask_oos]

        n_regime = len(regime_oos)
        if n_regime < 30:
            print(f"\n  {regime_label}: only {n_regime} obs, skipping")
            regime_garchx_results[regime_label] = {"n": n_regime, "note": "insufficient data"}
            continue

        # Get base forecasts for this regime
        regime_indices = np.where(regime_mask_oos.values)[0]
        regime_base_fc = base_forecasts[regime_indices]
        regime_target = regime_oos["FwdRV_22d"].values

        mask_r = ~np.isnan(regime_base_fc) & ~np.isnan(regime_target)
        if np.sum(mask_r) < 20:
            regime_garchx_results[regime_label] = {"n": np.sum(mask_r), "note": "insufficient valid forecasts"}
            continue

        h_r = regime_base_fc[mask_r]
        rv_r = regime_target[mask_r]
        eps = 1e-8
        h_rp = np.maximum(h_r, eps)
        rv_rp = np.maximum(rv_r, eps)

        qlike_base_r = np.mean(np.log(h_rp ** 2) + (rv_rp ** 2) / (h_rp ** 2))

        print(f"\n  === {regime_label} (N={np.sum(mask_r)}) ===")
        print(f"    Base GJR-GARCH QLIKE: {qlike_base_r:.4f}")

        regime_garchx_results[regime_label] = {
            "n": int(np.sum(mask_r)),
            "baseline_qlike": round(float(qlike_base_r), 4),
            "features": {},
        }

        for feat in FEATURE_NAMES:
            feat_regime = regime_oos[feat].values
            mask_f = mask_r & ~np.isnan(feat_regime[mask_r] if len(feat_regime) == len(mask_r) else feat_regime)

            # Realign
            feat_vals_r = feat_regime[mask_r[:len(feat_regime)]]
            mask_f2 = ~np.isnan(feat_vals_r)

            if np.sum(mask_f2) < 20:
                continue

            h_f2 = h_rp[mask_f2]
            rv_f2 = rv_rp[mask_f2]
            x_f2 = feat_vals_r[mask_f2]

            X_aug = np.column_stack([np.ones(len(h_f2)), h_f2, x_f2])
            beta_r, _, _, _ = lstsq(X_aug, rv_f2, rcond=None)
            pred_r = np.maximum(X_aug @ beta_r, eps)

            qlike_aug_r = np.mean(np.log(pred_r ** 2) + (rv_f2 ** 2) / (pred_r ** 2))

            # DM test within regime
            loss_b = np.log(h_f2 ** 2) + (rv_f2 ** 2) / (h_f2 ** 2)
            loss_a = np.log(pred_r ** 2) + (rv_f2 ** 2) / (pred_r ** 2)
            d_r = loss_b - loss_a

            n_r = len(d_r)
            d_bar_r = d_r.mean()
            lag_r = min(22, n_r // 3)

            gamma_0_r = np.var(d_r, ddof=1)
            nw_var_r = gamma_0_r
            for j in range(1, lag_r + 1):
                if len(d_r[j:]) > 1:
                    gamma_j_r = np.cov(d_r[j:], d_r[:-j])[0, 1]
                    nw_var_r += 2 * (1 - j / (lag_r + 1)) * gamma_j_r

            se_r = np.sqrt(max(nw_var_r, 1e-16) / n_r)
            dm_t_r = d_bar_r / se_r if se_r > 0 else 0
            dm_p_r = 2 * (1 - stats.norm.cdf(abs(dm_t_r)))

            regime_garchx_results[regime_label]["features"][feat] = {
                "qlike": round(float(qlike_aug_r), 4),
                "delta_qlike": round(float(qlike_base_r - qlike_aug_r), 4),
                "dm_t": round(float(dm_t_r), 3),
                "dm_p": round(float(dm_p_r), 4),
                "n": int(n_r),
            }

            sig = "*" if abs(dm_t_r) > 1.65 else ""
            if abs(dm_t_r) > 2.0:
                sig = "**"
            if abs(dm_t_r) > 3.0:
                sig = "***"
            print(f"    + {FEATURE_LABELS[feat]:<22} QLIKE={qlike_aug_r:.4f} "
                  f"(Δ={qlike_base_r - qlike_aug_r:+.4f}) DM t={dm_t_r:.3f}{sig}")

    results["sections"]["regime_garchx"] = regime_garchx_results

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 72)
print("SUMMARY: K258 Options Implied Skew Dynamics")
print("=" * 72)

# Count Harvey passes across all features/horizons
print("\n1. Partial Correlations (controlling for VIX + lagged RV):")
print("   Features that pass Harvey threshold (|t|>3.0) in OOS:")
any_oos_pass = False
for feat in FEATURE_NAMES:
    for h_name, _ in HORIZONS:
        r = corr_results["OOS"][feat][h_name]
        if r.get("passes_harvey"):
            any_oos_pass = True
            print(f"     {FEATURE_LABELS[feat]} ({h_name}): r={r['partial_r_vix_rv']:.4f}, t={r['t_partial_vix_rv']:.3f}")

if not any_oos_pass:
    print("     NONE — no SKEW dynamics feature passes Harvey in OOS")

# IS passes for comparison
print("\n   Features that pass Harvey in IS but not OOS (overfitting risk):")
for feat in FEATURE_NAMES:
    for h_name, _ in HORIZONS:
        is_r = corr_results["IS"][feat][h_name]
        oos_r = corr_results["OOS"][feat][h_name]
        if is_r.get("passes_harvey") and not oos_r.get("passes_harvey"):
            print(f"     {FEATURE_LABELS[feat]} ({h_name}): IS t={is_r['t_partial_vix_rv']:.3f} → OOS t={oos_r['t_partial_vix_rv']:.3f}")

print("\n2. Regime-Conditional (K212 insight: VIX<20 vs VIX>=20):")
for regime_label in ["Low (<20)", "High (>=20)"]:
    print(f"\n   {regime_label}:")
    if regime_label in regime_results and "OOS" in regime_results[regime_label]:
        any_pass_regime = False
        for feat in FEATURE_NAMES:
            if feat in regime_results[regime_label]["OOS"]:
                rr = regime_results[regime_label]["OOS"][feat]
                if rr.get("passes_harvey"):
                    any_pass_regime = True
                    print(f"     {FEATURE_LABELS[feat]}: r={rr['partial_r']:.4f}, t={rr['t_stat']:.3f} PASS")
        if not any_pass_regime:
            print(f"     No features pass Harvey threshold")
    else:
        print(f"     Insufficient data for OOS analysis")

print("\n3. GARCH-X Augmented Forecast (OOS):")
if garchx_results:
    best_feat = None
    best_dm = 0
    for feat in FEATURE_NAMES:
        if feat in garchx_results and garchx_results[feat].get("dm_t") is not None:
            print(f"   {FEATURE_LABELS[feat]}: ΔQLIKE={garchx_results[feat]['delta_qlike']:+.4f}, "
                  f"DM t={garchx_results[feat]['dm_t']:.3f}")
            if abs(garchx_results[feat]["dm_t"]) > abs(best_dm):
                best_dm = garchx_results[feat]["dm_t"]
                best_feat = feat

    if best_feat and abs(best_dm) > 3.0:
        print(f"\n   Best feature: {FEATURE_LABELS[best_feat]} (DM t={best_dm:.3f}) — PASSES Harvey")
    elif best_feat:
        print(f"\n   Best feature: {FEATURE_LABELS[best_feat]} (DM t={best_dm:.3f}) — does NOT pass Harvey")
    else:
        print(f"\n   No valid GARCH-X results")

print("\n4. Multi-Period Robustness:")
for feat in FEATURE_NAMES:
    n_pass = robustness_results[feat].get("n_harvey_passes", 0)
    consistent = robustness_results[feat].get("sign_consistent", False)
    if n_pass > 0 or consistent:
        print(f"   {FEATURE_LABELS[feat]}: {n_pass}/5 periods pass Harvey, sign consistent={consistent}")
any_robust = any(robustness_results[f].get("n_harvey_passes", 0) >= 3 for f in FEATURE_NAMES)
if not any_robust:
    print("   No feature consistently passes Harvey across multiple periods")

print("\n5. Vol Direction Prediction:")
for feat in FEATURE_NAMES:
    if "OOS" in direction_results and feat in direction_results["OOS"]:
        dr = direction_results["OOS"][feat]
        if dr.get("vol_dir_auc") is not None:
            auc = dr["vol_dir_auc"]
            if abs(auc - 0.5) > 0.05:
                print(f"   {FEATURE_LABELS[feat]}: AUC={auc:.4f} (t={dr.get('vol_dir_t', 'N/A')})")

# OVERALL CONCLUSION
print("\n" + "=" * 72)
print("CONCLUSION:")
print("=" * 72)

# Determine if SKEW dynamics adds anything
oos_passes = sum(
    1 for feat in FEATURE_NAMES
    for h_name, _ in HORIZONS
    if corr_results["OOS"][feat][h_name].get("passes_harvey")
)

garchx_passes = sum(
    1 for feat in FEATURE_NAMES
    if feat in garchx_results and garchx_results[feat].get("passes_harvey")
)

robust_passes = sum(
    1 for feat in FEATURE_NAMES
    if robustness_results[feat].get("n_harvey_passes", 0) >= 3
)

if oos_passes == 0 and garchx_passes == 0:
    print("\nSKEW dynamics (changes, acceleration, vol-of-skew) do NOT add")
    print("predictive power beyond VIX + lagged RV for SPY volatility forecasting.")
    print("\nThis extends K184's finding from SKEW *level* to SKEW *dynamics*:")
    print("  - K184: SKEW level absorbed by VIX")
    print("  - K258: SKEW dynamics (changes, acceleration) also absorbed by VIX + RV")
    print("\nImplication: The information in options skew dynamics is already reflected")
    print("in VIX and recent realized vol. Delta-SKEW does NOT lead VIX.")
    conclusion = "SKEW_dynamics_absorbed"
elif oos_passes > 0 or garchx_passes > 0:
    print(f"\nSKEW dynamics show some signal:")
    print(f"  OOS partial correlation passes: {oos_passes}")
    print(f"  GARCH-X DM test passes: {garchx_passes}")
    print(f"  Multi-period robust passes: {robust_passes}")
    if robust_passes >= 2:
        conclusion = "SKEW_dynamics_partial_signal"
        print("\nSome SKEW dynamics features show robust signal beyond VIX.")
    else:
        conclusion = "SKEW_dynamics_weak_signal"
        print("\nBut signal is not robust across periods — likely overfitting.")
else:
    conclusion = "SKEW_dynamics_null"
    print("\nNo conclusive evidence for SKEW dynamics predictive power.")

print("\nLimitations:")
print("  - Single asset (SPY only)")
print("  - SKEW index calculation changed over time (CBOE methodology updates)")
print("  - Options market microstructure effects not controlled")
print("  - OOS period (2023-2024) was relatively low-vol; high-vol regime tests limited by small N")

results["sections"]["summary"] = {
    "conclusion": conclusion,
    "oos_harvey_passes": oos_passes,
    "garchx_dm_passes": garchx_passes,
    "robustness_passes": robust_passes,
    "any_oos_pass": bool(any_oos_pass),
}

# Save results
output_path = "experiments/k258_skew_dynamics_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("=" * 72)
