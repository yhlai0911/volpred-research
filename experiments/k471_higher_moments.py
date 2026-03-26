#!/usr/bin/env python3
"""
K471: Time-Varying Higher Moments (Conditional Skewness/Kurtosis) for Vol Prediction

Research Questions:
1. Do SPY's conditional skewness/kurtosis vary over time?
2. Can past skewness/kurtosis predict future volatility?
3. Do higher moments provide incremental info beyond GJR-GARCH?

Method:
- Rolling 5d and 21d skewness/kurtosis as features
- Predict 21-day forward realized volatility
- Compare: baseline (lagged RV21) vs + skew vs + kurt vs + both vs Ridge
- OOS: 2023-2025
- Assets: SPY, QQQ, BTC-USD

References:
- Harvey & Siddique (1999) "Conditional Skewness in Asset Pricing Tests" JoF
- Jondeau & Rockinger (2003) "Conditional volatility, skewness, and kurtosis" JEDC
- Leon, Rubio, Serna (2005) "Autoregressive conditional volatility, skewness and kurtosis" QREF

Data: yfinance daily prices
Prior knowledge: K-entry found r=-0.073 for residual higher moments, OOS R² +2.7pp (weak)
"""

import json
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

START_TIME = time.time()

# ============================================================
# 1. Data Collection
# ============================================================
ASSETS = ["SPY", "QQQ", "BTC-USD"]
DATA_START = "2010-01-01"
DATA_END = "2025-12-31"
OOS_START = "2023-01-01"
FWD_WINDOW = 21  # 21-day forward RV

print("=" * 70)
print("K471: Time-Varying Higher Moments for Vol Prediction")
print("=" * 70)
print(f"Assets: {ASSETS}")
print(f"Data period: {DATA_START} to {DATA_END}")
print(f"OOS start: {OOS_START}")
print(f"Forward window: {FWD_WINDOW} days")
print()

# Download data
price_data = {}
for asset in ASSETS:
    try:
        df = yf.download(asset, start=DATA_START, end=DATA_END, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        price_data[asset] = df["Close"].dropna()
        print(f"  {asset}: {len(price_data[asset])} obs, {price_data[asset].index[0].strftime('%Y-%m-%d')} to {price_data[asset].index[-1].strftime('%Y-%m-%d')}")
    except Exception as e:
        print(f"  {asset}: FAILED - {e}")

print()

# ============================================================
# 2. Feature Engineering
# ============================================================
def compute_features(prices: pd.Series) -> pd.DataFrame:
    """Compute rolling higher moments and RV features."""
    ret = np.log(prices / prices.shift(1))

    df = pd.DataFrame(index=prices.index)
    df["ret"] = ret

    # Realized volatility (annualized)
    df["rv21"] = ret.rolling(21).std() * np.sqrt(252)
    df["rv5"] = ret.rolling(5).std() * np.sqrt(252)
    df["rv63"] = ret.rolling(63).std() * np.sqrt(252)

    # Rolling skewness
    df["skew5"] = ret.rolling(5).skew()
    df["skew21"] = ret.rolling(21).skew()
    df["skew63"] = ret.rolling(63).skew()

    # Rolling kurtosis (excess)
    df["kurt5"] = ret.rolling(5).kurt()
    df["kurt21"] = ret.rolling(21).kurt()
    df["kurt63"] = ret.rolling(63).kurt()

    # Asymmetry ratio: proportion of negative returns
    df["neg_ratio21"] = ret.rolling(21).apply(lambda x: (x < 0).mean(), raw=True)

    # Downside semi-variance ratio
    def downside_ratio(x):
        neg = x[x < 0]
        if len(neg) == 0 or x.std() == 0:
            return 0.0
        return neg.std() / x.std()
    df["down_ratio21"] = ret.rolling(21).apply(downside_ratio, raw=True)

    # Forward RV (target) - 21-day forward realized vol
    df["fwd_rv21"] = ret.shift(-FWD_WINDOW).rolling(FWD_WINDOW).std().shift(-FWD_WINDOW + 1) * np.sqrt(252)
    # More precise: use actual forward window
    fwd_rv = []
    for i in range(len(ret)):
        if i + FWD_WINDOW <= len(ret):
            fwd_slice = ret.iloc[i+1:i+1+FWD_WINDOW]
            if len(fwd_slice) == FWD_WINDOW:
                fwd_rv.append(fwd_slice.std() * np.sqrt(252))
            else:
                fwd_rv.append(np.nan)
        else:
            fwd_rv.append(np.nan)
    df["fwd_rv21"] = fwd_rv

    return df


# ============================================================
# 3. Diagnostics: Time-Varying Higher Moments
# ============================================================
print("=" * 70)
print("PART 1: Descriptive Statistics & Time Variation of Higher Moments")
print("=" * 70)

all_features = {}
diagnostics = {}

for asset in ASSETS:
    if asset not in price_data:
        continue

    feat = compute_features(price_data[asset])
    all_features[asset] = feat

    # Focus on 21-day rolling moments
    valid = feat[["skew21", "kurt21", "rv21"]].dropna()

    diag = {
        "n_obs": len(valid),
        "skew21_mean": float(valid["skew21"].mean()),
        "skew21_std": float(valid["skew21"].std()),
        "skew21_min": float(valid["skew21"].min()),
        "skew21_max": float(valid["skew21"].max()),
        "kurt21_mean": float(valid["kurt21"].mean()),
        "kurt21_std": float(valid["kurt21"].std()),
        "kurt21_min": float(valid["kurt21"].min()),
        "kurt21_max": float(valid["kurt21"].max()),
        "skew21_adf_stat": float(stats.pearsonr(valid["skew21"].values[:-1], valid["skew21"].values[1:])[0]),
        "kurt21_adf_stat": float(stats.pearsonr(valid["kurt21"].values[:-1], valid["kurt21"].values[1:])[0]),
    }

    # ADF test for stationarity
    from statsmodels.tsa.stattools import adfuller
    adf_skew = adfuller(valid["skew21"].values, maxlag=10, autolag="AIC")
    adf_kurt = adfuller(valid["kurt21"].values, maxlag=10, autolag="AIC")
    diag["skew21_adf_pvalue"] = float(adf_skew[1])
    diag["kurt21_adf_pvalue"] = float(adf_kurt[1])

    # Ljung-Box for autocorrelation
    from statsmodels.stats.diagnostic import acorr_ljungbox
    lb_skew = acorr_ljungbox(valid["skew21"].values, lags=[10], return_df=True)
    lb_kurt = acorr_ljungbox(valid["kurt21"].values, lags=[10], return_df=True)
    diag["skew21_ljungbox_p"] = float(lb_skew["lb_pvalue"].values[0])
    diag["kurt21_ljungbox_p"] = float(lb_kurt["lb_pvalue"].values[0])

    # Correlation between moments and future vol
    valid_full = feat[["skew5", "skew21", "skew63", "kurt5", "kurt21", "kurt63", "fwd_rv21"]].dropna()
    corrs = {}
    for col in ["skew5", "skew21", "skew63", "kurt5", "kurt21", "kurt63"]:
        r, p = stats.pearsonr(valid_full[col], valid_full["fwd_rv21"])
        corrs[col] = {"r": round(r, 4), "p": round(p, 6)}
    diag["corr_with_fwd_rv21"] = corrs

    diagnostics[asset] = diag

    print(f"\n--- {asset} ({diag['n_obs']} obs) ---")
    print(f"  Skew21: mean={diag['skew21_mean']:.3f}, std={diag['skew21_std']:.3f}, range=[{diag['skew21_min']:.3f}, {diag['skew21_max']:.3f}]")
    print(f"    ADF p-value={diag['skew21_adf_pvalue']:.4f}, Ljung-Box(10) p={diag['skew21_ljungbox_p']:.6f}")
    print(f"  Kurt21: mean={diag['kurt21_mean']:.3f}, std={diag['kurt21_std']:.3f}, range=[{diag['kurt21_min']:.3f}, {diag['kurt21_max']:.3f}]")
    print(f"    ADF p-value={diag['kurt21_adf_pvalue']:.4f}, Ljung-Box(10) p={diag['kurt21_ljungbox_p']:.6f}")
    print(f"  Correlations with fwd RV21:")
    for col, cr in corrs.items():
        sig = "***" if cr["p"] < 0.001 else "**" if cr["p"] < 0.01 else "*" if cr["p"] < 0.05 else ""
        print(f"    {col:>8s}: r={cr['r']:+.4f} (p={cr['p']:.4f}) {sig}")


# ============================================================
# 4. Predictive Regression: OOS Evaluation
# ============================================================
print("\n" + "=" * 70)
print("PART 2: OOS Predictive Regression (2023-2025)")
print("=" * 70)

def qlike(actual, predicted):
    """QLIKE loss (variance form): mean(actual²/predicted² - log(actual²/predicted²) - 1)"""
    # Use volatility form: QLIKE = mean(rv²/sigma² - log(rv²/sigma²) - 1)
    ratio = (actual / predicted) ** 2
    ratio = np.clip(ratio, 1e-10, 1e10)
    return np.mean(ratio - np.log(ratio) - 1)

def mse(actual, predicted):
    return np.mean((actual - predicted) ** 2)

def r_squared_oos(actual, predicted):
    ss_res = np.sum((actual - predicted) ** 2)
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    return 1 - ss_res / ss_tot

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test (two-sided). loss1 - loss2 < 0 means model 1 is better."""
    d = loss1 - loss2
    n = len(d)
    d_mean = d.mean()
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    d_var = gamma0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        d_var += 2 * (1 - k / h) * gamma_k
    d_var = max(d_var, 1e-20)
    dm_stat = d_mean / np.sqrt(d_var / n)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_value)


# Model specifications
MODEL_SPECS = {
    "M1_lagged_rv": ["rv21"],
    "M2_rv_skew": ["rv21", "skew5", "skew21"],
    "M3_rv_kurt": ["rv21", "kurt5", "kurt21"],
    "M4_rv_skew_kurt": ["rv21", "skew5", "skew21", "kurt5", "kurt21"],
    "M5_full": ["rv21", "rv5", "rv63", "skew5", "skew21", "skew63", "kurt5", "kurt21", "kurt63"],
    "M6_kitchen_sink": ["rv21", "rv5", "rv63", "skew5", "skew21", "skew63", "kurt5", "kurt21", "kurt63", "neg_ratio21", "down_ratio21"],
}

results_by_asset = {}

for asset in ASSETS:
    if asset not in all_features:
        continue

    feat = all_features[asset]

    # Prepare data: all features + target
    all_cols = list(set(col for cols in MODEL_SPECS.values() for col in cols)) + ["fwd_rv21"]
    df = feat[all_cols].dropna()

    # Split IS/OOS
    oos_mask = df.index >= OOS_START
    is_data = df[~oos_mask]
    oos_data = df[oos_mask]

    if len(oos_data) < 50:
        print(f"\n{asset}: insufficient OOS data ({len(oos_data)} obs)")
        continue

    print(f"\n--- {asset} ---")
    print(f"  IS: {len(is_data)} obs ({is_data.index[0].strftime('%Y-%m-%d')} to {is_data.index[-1].strftime('%Y-%m-%d')})")
    print(f"  OOS: {len(oos_data)} obs ({oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')})")

    asset_results = {
        "is_n": len(is_data),
        "oos_n": len(oos_data),
        "models": {}
    }

    y_oos = oos_data["fwd_rv21"].values
    base_losses = None  # for DM test vs baseline

    for model_name, features in MODEL_SPECS.items():
        X_is = is_data[features].values
        y_is = is_data["fwd_rv21"].values
        X_oos = oos_data[features].values

        # Use Ridge regression (expanding window would be ideal but
        # for efficiency, we use full IS fit + OOS predict)
        scaler = StandardScaler()
        X_is_sc = scaler.fit_transform(X_is)
        X_oos_sc = scaler.transform(X_oos)

        # Also try OLS (alpha=0) and Ridge (alpha=1)
        for reg_type, alpha in [("OLS", 1e-10), ("Ridge", 1.0)]:
            model = Ridge(alpha=alpha)
            model.fit(X_is_sc, y_is)
            y_pred = model.predict(X_oos_sc)

            # Ensure positive predictions
            y_pred = np.clip(y_pred, 0.01, None)

            # Metrics
            oos_mse = mse(y_oos, y_pred)
            oos_qlike = qlike(y_oos, y_pred)
            oos_r2 = r_squared_oos(y_oos, y_pred)
            oos_corr = float(np.corrcoef(y_oos, y_pred)[0, 1])

            # IS metrics
            y_is_pred = model.predict(X_is_sc)
            y_is_pred = np.clip(y_is_pred, 0.01, None)
            is_r2 = r_squared_oos(y_is, y_is_pred)

            full_name = f"{model_name}_{reg_type}"

            # Squared error losses for DM test
            se_losses = (y_oos - y_pred) ** 2

            # DM test vs baseline (M1)
            dm_stat, dm_p = np.nan, np.nan
            if base_losses is not None:
                dm_stat, dm_p = dm_test(se_losses, base_losses, h=FWD_WINDOW)
            else:
                if model_name == "M1_lagged_rv" and reg_type == "OLS":
                    base_losses = se_losses

            # Coefficients
            coefs = {}
            for i, f in enumerate(features):
                coefs[f] = round(float(model.coef_[i]), 6)
            coefs["intercept"] = round(float(model.intercept_), 6)

            result = {
                "features": features,
                "reg_type": reg_type,
                "is_r2": round(is_r2, 4),
                "oos_mse": round(oos_mse, 6),
                "oos_qlike": round(oos_qlike, 6),
                "oos_r2": round(oos_r2, 4),
                "oos_corr": round(oos_corr, 4),
                "dm_stat_vs_baseline": round(dm_stat, 4) if not np.isnan(dm_stat) else None,
                "dm_pvalue_vs_baseline": round(dm_p, 4) if not np.isnan(dm_p) else None,
                "coefficients": coefs,
            }

            asset_results["models"][full_name] = result

    # Set baseline DM for M1_OLS
    if "M1_lagged_rv_OLS" in asset_results["models"]:
        asset_results["models"]["M1_lagged_rv_OLS"]["dm_stat_vs_baseline"] = 0.0
        asset_results["models"]["M1_lagged_rv_OLS"]["dm_pvalue_vs_baseline"] = 1.0

    results_by_asset[asset] = asset_results

    # Print summary table
    print(f"\n  {'Model':<30s} {'IS R²':>8s} {'OOS R²':>8s} {'OOS QLIKE':>10s} {'OOS Corr':>9s} {'DM p':>8s}")
    print(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*10} {'-'*9} {'-'*8}")
    for mname, mres in asset_results["models"].items():
        dm_p_str = f"{mres['dm_pvalue_vs_baseline']:.4f}" if mres["dm_pvalue_vs_baseline"] is not None else "  base"
        print(f"  {mname:<30s} {mres['is_r2']:>8.4f} {mres['oos_r2']:>8.4f} {mres['oos_qlike']:>10.6f} {mres['oos_corr']:>9.4f} {dm_p_str:>8s}")


# ============================================================
# 5. Expanding Window OOS (Robustness)
# ============================================================
print("\n" + "=" * 70)
print("PART 3: Expanding Window OOS (Monthly Refit)")
print("=" * 70)

expanding_results = {}

for asset in ASSETS:
    if asset not in all_features:
        continue

    feat = all_features[asset]
    all_cols = list(set(col for cols in MODEL_SPECS.values() for col in cols)) + ["fwd_rv21"]
    df = feat[all_cols].dropna()

    oos_mask = df.index >= OOS_START
    oos_dates = df[oos_mask].index

    if len(oos_dates) < 50:
        continue

    # Monthly refit expanding window for key models
    key_models = {
        "M1_lagged_rv": ["rv21"],
        "M4_rv_skew_kurt": ["rv21", "skew5", "skew21", "kurt5", "kurt21"],
        "M5_full": ["rv21", "rv5", "rv63", "skew5", "skew21", "skew63", "kurt5", "kurt21", "kurt63"],
    }

    asset_exp = {}

    for model_name, features in key_models.items():
        preds = []
        actuals = []

        # Refit monthly (every 21 trading days)
        refit_interval = 21
        last_refit = -refit_interval  # force initial fit

        scaler = StandardScaler()
        model = Ridge(alpha=1.0)

        for i, date in enumerate(oos_dates):
            pos = df.index.get_loc(date)

            # Refit if needed
            if i - last_refit >= refit_interval or i == 0:
                X_train = df.iloc[:pos][features].values
                y_train = df.iloc[:pos]["fwd_rv21"].values

                # Remove NaN
                valid_mask = ~np.isnan(X_train).any(axis=1) & ~np.isnan(y_train)
                X_train = X_train[valid_mask]
                y_train = y_train[valid_mask]

                if len(X_train) < 100:
                    continue

                scaler.fit(X_train)
                model.fit(scaler.transform(X_train), y_train)
                last_refit = i

            X_test = df.iloc[pos:pos+1][features].values
            y_test = df.iloc[pos]["fwd_rv21"]

            if np.isnan(X_test).any() or np.isnan(y_test):
                continue

            pred = model.predict(scaler.transform(X_test))[0]
            pred = max(pred, 0.01)

            preds.append(pred)
            actuals.append(y_test)

        preds = np.array(preds)
        actuals = np.array(actuals)

        if len(preds) < 50:
            continue

        exp_mse = mse(actuals, preds)
        exp_qlike = qlike(actuals, preds)
        exp_r2 = r_squared_oos(actuals, preds)
        exp_corr = float(np.corrcoef(actuals, preds)[0, 1])

        asset_exp[model_name] = {
            "n_oos": len(preds),
            "oos_mse": round(exp_mse, 6),
            "oos_qlike": round(exp_qlike, 6),
            "oos_r2": round(exp_r2, 4),
            "oos_corr": round(exp_corr, 4),
        }

    expanding_results[asset] = asset_exp

    print(f"\n--- {asset} (Expanding Window) ---")
    print(f"  {'Model':<25s} {'N':>5s} {'OOS R²':>8s} {'OOS QLIKE':>10s} {'OOS Corr':>9s}")
    print(f"  {'-'*25} {'-'*5} {'-'*8} {'-'*10} {'-'*9}")
    for mname, mres in asset_exp.items():
        print(f"  {mname:<25s} {mres['n_oos']:>5d} {mres['oos_r2']:>8.4f} {mres['oos_qlike']:>10.6f} {mres['oos_corr']:>9.4f}")


# ============================================================
# 6. Sub-period Analysis: When Do Higher Moments Help Most?
# ============================================================
print("\n" + "=" * 70)
print("PART 4: Regime Conditional Analysis")
print("=" * 70)

regime_results = {}

for asset in ASSETS:
    if asset not in all_features:
        continue

    feat = all_features[asset]
    df = feat[["rv21", "skew21", "kurt21", "fwd_rv21"]].dropna()

    # Split into high-vol and low-vol regimes
    rv_median = df["rv21"].median()

    high_vol = df[df["rv21"] > rv_median]
    low_vol = df[df["rv21"] <= rv_median]

    regime_corrs = {}
    for regime_name, regime_data in [("high_vol", high_vol), ("low_vol", low_vol)]:
        corrs = {}
        for col in ["skew21", "kurt21"]:
            r, p = stats.pearsonr(regime_data[col], regime_data["fwd_rv21"])
            corrs[col] = {"r": round(r, 4), "p": round(p, 6)}
        regime_corrs[regime_name] = corrs

    regime_results[asset] = {
        "rv_median": round(rv_median, 4),
        "high_vol_n": len(high_vol),
        "low_vol_n": len(low_vol),
        "regime_correlations": regime_corrs,
    }

    print(f"\n--- {asset} ---")
    print(f"  RV21 median: {rv_median:.4f}")
    print(f"  High-vol regime ({len(high_vol)} obs):")
    for col, cr in regime_corrs["high_vol"].items():
        sig = "*" if cr["p"] < 0.05 else ""
        print(f"    {col} vs fwd_rv21: r={cr['r']:+.4f} (p={cr['p']:.4f}) {sig}")
    print(f"  Low-vol regime ({len(low_vol)} obs):")
    for col, cr in regime_corrs["low_vol"].items():
        sig = "*" if cr["p"] < 0.05 else ""
        print(f"    {col} vs fwd_rv21: r={cr['r']:+.4f} (p={cr['p']:.4f}) {sig}")


# ============================================================
# 7. Granger Causality Tests
# ============================================================
print("\n" + "=" * 70)
print("PART 5: Granger Causality Tests (Skew/Kurt → RV)")
print("=" * 70)

from statsmodels.tsa.stattools import grangercausalitytests

granger_results = {}

for asset in ASSETS:
    if asset not in all_features:
        continue

    feat = all_features[asset]

    asset_granger = {}

    for predictor in ["skew21", "kurt21"]:
        df_gc = feat[["rv21", predictor]].dropna()

        if len(df_gc) < 100:
            continue

        try:
            # Test if predictor Granger-causes rv21 (max 5 lags)
            gc_result = grangercausalitytests(df_gc[["rv21", predictor]].values, maxlag=5, verbose=False)

            gc_pvalues = {}
            for lag in range(1, 6):
                f_test_p = gc_result[lag][0]["ssr_ftest"][1]
                gc_pvalues[f"lag_{lag}"] = round(float(f_test_p), 6)

            # Minimum p-value across lags
            min_p = min(gc_pvalues.values())
            best_lag = min(gc_pvalues, key=gc_pvalues.get)

            asset_granger[predictor] = {
                "pvalues_by_lag": gc_pvalues,
                "min_pvalue": round(min_p, 6),
                "best_lag": best_lag,
                "significant": min_p < 0.05,
            }

            sig = "YES" if min_p < 0.05 else "NO"
            print(f"  {asset} | {predictor} → rv21: min p={min_p:.6f} at {best_lag} [{sig}]")

        except Exception as e:
            print(f"  {asset} | {predictor}: ERROR - {e}")

    granger_results[asset] = asset_granger


# ============================================================
# 8. Incremental R² Analysis
# ============================================================
print("\n" + "=" * 70)
print("PART 6: Incremental R² from Higher Moments (OOS)")
print("=" * 70)

incremental_results = {}

for asset in ASSETS:
    if asset not in results_by_asset:
        continue

    models = results_by_asset[asset]["models"]

    base_r2 = models.get("M1_lagged_rv_OLS", {}).get("oos_r2", None)
    if base_r2 is None:
        continue

    incr = {}
    for mname in ["M2_rv_skew_OLS", "M3_rv_kurt_OLS", "M4_rv_skew_kurt_OLS", "M5_full_OLS", "M6_kitchen_sink_OLS"]:
        if mname in models:
            delta_r2 = models[mname]["oos_r2"] - base_r2
            incr[mname] = {
                "oos_r2": models[mname]["oos_r2"],
                "delta_r2": round(delta_r2, 4),
                "dm_pvalue": models[mname].get("dm_pvalue_vs_baseline"),
            }

    incremental_results[asset] = {
        "baseline_r2": base_r2,
        "increments": incr,
    }

    print(f"\n--- {asset} ---")
    print(f"  Baseline (lagged RV21) OOS R²: {base_r2:.4f}")
    for mname, inc in incr.items():
        sig = "*" if (inc["dm_pvalue"] is not None and inc["dm_pvalue"] < 0.05) else ""
        dm_str = f"DM p={inc['dm_pvalue']:.4f}" if inc["dm_pvalue"] is not None else ""
        sign = "+" if inc["delta_r2"] >= 0 else ""
        print(f"  {mname:<30s}: R²={inc['oos_r2']:.4f} (Δ={sign}{inc['delta_r2']:.4f}) {dm_str} {sig}")


# ============================================================
# 9. Cross-Asset Summary & Conclusion
# ============================================================
print("\n" + "=" * 70)
print("PART 7: Cross-Asset Summary")
print("=" * 70)

# Determine overall conclusion
conclusions = []
for asset in ASSETS:
    if asset not in incremental_results:
        continue
    inc = incremental_results[asset]
    best_delta = max((v["delta_r2"] for v in inc["increments"].values()), default=0)
    best_model = max(inc["increments"], key=lambda k: inc["increments"][k]["delta_r2"]) if inc["increments"] else None

    if best_model:
        dm_p = inc["increments"][best_model].get("dm_pvalue")
        sig = dm_p is not None and dm_p < 0.05
        conclusions.append({
            "asset": asset,
            "baseline_r2": inc["baseline_r2"],
            "best_model": best_model,
            "best_delta_r2": best_delta,
            "dm_significant": sig,
        })

        status = "SIGNIFICANT" if sig else "NOT significant"
        print(f"  {asset}: Baseline R²={inc['baseline_r2']:.4f}, Best improvement: Δ={best_delta:+.4f} ({best_model}) [{status}]")

elapsed = time.time() - START_TIME
print(f"\nTotal elapsed: {elapsed:.1f}s")

# ============================================================
# 10. Save Results
# ============================================================
output = {
    "experiment_id": "K471",
    "title": "Time-Varying Higher Moments (Conditional Skewness/Kurtosis) for Vol Prediction",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance",
    "assets": ASSETS,
    "oos_period": "2023-01-01 to 2025-12-31",
    "forward_window": FWD_WINDOW,
    "method": "Rolling skewness/kurtosis (5d, 21d, 63d) as predictors of 21-day forward RV. Ridge regression. Expanding window monthly refit.",
    "references": [
        "Harvey & Siddique (1999) 'Conditional Skewness in Asset Pricing Tests' JoF",
        "Jondeau & Rockinger (2003) 'Conditional volatility, skewness, and kurtosis' JEDC",
        "Leon, Rubio, Serna (2005) 'Autoregressive conditional volatility, skewness and kurtosis' QREF",
    ],
    "prior_knowledge": "K-entry: residual higher moments r=-0.073, OOS R² +2.7pp (weak improvement)",
    "diagnostics": diagnostics,
    "oos_results": results_by_asset,
    "expanding_window_results": expanding_results,
    "regime_analysis": regime_results,
    "granger_causality": granger_results,
    "incremental_r2": incremental_results,
    "cross_asset_summary": conclusions,
    "elapsed_seconds": round(elapsed, 1),
    "conclusion": "",  # will be filled below
}

# Generate conclusion text
n_sig = sum(1 for c in conclusions if c["dm_significant"])
avg_delta = np.mean([c["best_delta_r2"] for c in conclusions]) if conclusions else 0

if n_sig == 0:
    conclusion = (
        f"Higher moments (rolling skewness/kurtosis) do NOT significantly improve OOS vol prediction "
        f"over lagged RV21 for any of the {len(conclusions)} assets tested. "
        f"Average Δ R² = {avg_delta:+.4f}. "
        f"This confirms the prior finding (r=-0.073, Δ R² +2.7pp) that higher moments provide "
        f"minimal incremental information for volatility forecasting. "
        f"The predictive content of higher moments is already captured by the level of realized volatility."
    )
elif n_sig == len(conclusions):
    conclusion = (
        f"Higher moments significantly improve OOS vol prediction for ALL {len(conclusions)} assets. "
        f"Average Δ R² = {avg_delta:+.4f}. "
        f"This extends Harvey & Siddique (1999) to show conditional higher moments have "
        f"cross-asset predictive power for realized volatility."
    )
else:
    sig_assets = [c["asset"] for c in conclusions if c["dm_significant"]]
    conclusion = (
        f"Mixed results: higher moments significantly improve vol prediction for {sig_assets} "
        f"but not others. Average Δ R² = {avg_delta:+.4f}. "
        f"Asset-specific dynamics matter."
    )

output["conclusion"] = conclusion
print(f"\nCONCLUSION: {conclusion}")

# Save
results_path = "experiments/k471_higher_moments_results.json"
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nResults saved to {results_path}")
print(f"Script: experiments/k471_higher_moments.py")
