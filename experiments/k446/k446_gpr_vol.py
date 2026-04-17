"""
K446: Geopolitical Risk Index (GPR) and Stock Market Volatility
================================================================
Research Questions:
1. Can GPR predict SPY realized volatility? (incremental info beyond VIX)
2. Is GPR more effective in specific regimes? (war vs peace)
3. What is the GPR-VIX relationship? (contemporaneous vs lead/lag)

Literature:
- Caldara & Iacoviello (2022) AER 112(4):1194-1225
- Kannadhasan & Das (2020) J. Business Research
- 2023 ScienceDirect: ML models for GPR vol forecasting

Data Sources:
- GPR daily index: Caldara & Iacoviello website (matteoiacoviello.com/gpr.htm)
  - Index normalized: 1985-2019 = 100
  - Based on newspaper text analysis (10 major newspapers)
- SPY, ^VIX: yfinance
- Sample: 2000-01-01 to 2026-03-23 (full available overlap)
- OOS: 2023-01-01 to 2024-12-31

[提出: 用戶, 執行: Claude]
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from sklearn.linear_model import Ridge

warnings.filterwarnings("ignore")

RESULTS_FILE = os.path.join(os.path.dirname(__file__), "k446_gpr_vol_results.json")

# ============================================================
# STEP 1: Load GPR Data
# ============================================================
def load_gpr_data():
    """Load GPR daily data from local cache or download."""
    cache_path = "/tmp/gpr_daily.xls"
    if not os.path.exists(cache_path):
        import urllib.request
        url = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"
        urllib.request.urlretrieve(url, cache_path)
        print(f"Downloaded GPR data to {cache_path}")

    df = pd.read_excel(cache_path)
    # Use the 'date' column as index
    gpr = df[["date", "GPRD", "GPRD_ACT", "GPRD_THREAT"]].copy()
    gpr.columns = ["date", "gpr", "gpr_act", "gpr_threat"]
    gpr["date"] = pd.to_datetime(gpr["date"])
    gpr = gpr.set_index("date").sort_index()
    # Drop any NaN
    gpr = gpr.dropna(subset=["gpr"])
    return gpr


# ============================================================
# STEP 2: Load SPY and VIX
# ============================================================
def load_market_data(start="2000-01-01", end="2026-03-25"):
    """Load SPY and VIX from yfinance."""
    spy = yf.download("SPY", start=start, end=end, progress=False)
    vix = yf.download("^VIX", start=start, end=end, progress=False)

    # Handle MultiIndex columns from yfinance
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    # SPY returns and realized volatility
    spy_ret = spy["Close"].pct_change().dropna()
    spy_ret.name = "spy_ret"

    # Realized volatility: 21-day rolling std (annualized)
    rv21 = spy_ret.rolling(21).std() * np.sqrt(252) * 100  # in % terms
    rv21.name = "rv21"

    # 5-day forward realized vol (target)
    rv5_fwd = spy_ret.rolling(5).std().shift(-5) * np.sqrt(252) * 100
    rv5_fwd.name = "rv5_fwd"

    # 21-day forward realized vol (target)
    rv21_fwd = spy_ret.rolling(21).std().shift(-21) * np.sqrt(252) * 100
    rv21_fwd.name = "rv21_fwd"

    # VIX close
    vix_close = vix["Close"].copy()
    vix_close.name = "vix"

    return spy_ret, rv21, rv5_fwd, rv21_fwd, vix_close


# ============================================================
# STEP 3: Merge and Prepare Features
# ============================================================
def prepare_dataset(gpr, spy_ret, rv21, rv5_fwd, rv21_fwd, vix_close):
    """Merge all data and create features."""
    # Combine all series
    df = pd.DataFrame(index=spy_ret.index)
    df["spy_ret"] = spy_ret
    df["rv21"] = rv21
    df["rv5_fwd"] = rv5_fwd
    df["rv21_fwd"] = rv21_fwd
    df["vix"] = vix_close

    # Align GPR to trading days (forward fill weekends/holidays)
    gpr_aligned = gpr.reindex(df.index, method="ffill")
    df["gpr"] = gpr_aligned["gpr"]
    df["gpr_act"] = gpr_aligned["gpr_act"]
    df["gpr_threat"] = gpr_aligned["gpr_threat"]

    # GPR features
    df["gpr_ma7"] = df["gpr"].rolling(7).mean()
    df["gpr_ma21"] = df["gpr"].rolling(21).mean()
    df["gpr_std21"] = df["gpr"].rolling(21).std()
    df["gpr_zscore"] = (df["gpr"] - df["gpr_ma21"]) / df["gpr_std21"]
    df["gpr_change"] = df["gpr"].pct_change(5)  # 5-day change
    df["gpr_log"] = np.log1p(df["gpr"])

    # VIX features
    df["vix_ma5"] = df["vix"].rolling(5).mean()
    df["vix_change"] = df["vix"].pct_change(5)

    # Lagged features (avoid look-ahead bias)
    for col in ["gpr", "gpr_ma7", "gpr_ma21", "gpr_zscore", "gpr_change", "gpr_log",
                 "gpr_act", "gpr_threat",
                 "vix", "vix_ma5", "vix_change", "rv21"]:
        df[f"{col}_lag1"] = df[col].shift(1)

    df = df.dropna()
    return df


# ============================================================
# STEP 4: Descriptive Statistics & Diagnostics
# ============================================================
def descriptive_stats(df):
    """Compute descriptive statistics for key variables."""
    result = {}
    for col in ["gpr", "gpr_act", "gpr_threat", "rv21", "vix", "spy_ret"]:
        s = df[col].dropna()
        result[col] = {
            "mean": float(s.mean()),
            "std": float(s.std()),
            "skew": float(s.skew()),
            "kurtosis": float(s.kurtosis()),
            "min": float(s.min()),
            "max": float(s.max()),
            "n": int(len(s)),
        }
    return result


def correlation_analysis(df):
    """Analyze GPR-VIX-RV correlations."""
    cols = ["gpr", "gpr_act", "gpr_threat", "vix", "rv21", "rv5_fwd", "rv21_fwd"]
    corr = df[cols].corr()

    # Contemporaneous correlations
    contemp = {}
    for c in cols:
        contemp[c] = {c2: round(float(corr.loc[c, c2]), 4) for c2 in cols}

    # Lead/lag analysis: GPR leads VIX?
    lead_lag = {}
    for lag in range(-10, 11):
        gpr_shifted = df["gpr"].shift(lag)
        mask = gpr_shifted.notna() & df["vix"].notna()
        r = float(gpr_shifted[mask].corr(df["vix"][mask]))
        lead_lag[str(lag)] = round(r, 4)

    # GPR-RV lead/lag
    gpr_rv_leadlag = {}
    for lag in range(-10, 11):
        gpr_shifted = df["gpr"].shift(lag)
        mask = gpr_shifted.notna() & df["rv21"].notna()
        r = float(gpr_shifted[mask].corr(df["rv21"][mask]))
        gpr_rv_leadlag[str(lag)] = round(r, 4)

    return {
        "contemporaneous": contemp,
        "gpr_vix_leadlag": lead_lag,
        "gpr_rv_leadlag": gpr_rv_leadlag,
    }


def stationarity_tests(df):
    """ADF tests for key variables."""
    from statsmodels.tsa.stattools import adfuller

    result = {}
    for col in ["gpr", "vix", "rv21"]:
        s = df[col].dropna().values
        # Use max 5000 observations for speed
        if len(s) > 5000:
            s = s[-5000:]
        adf_stat, adf_p, _, _, _, _ = adfuller(s, maxlag=20)
        result[col] = {
            "adf_statistic": round(float(adf_stat), 4),
            "adf_pvalue": round(float(adf_p), 6),
            "stationary": bool(adf_p < 0.05),
        }
    return result


# ============================================================
# STEP 5: Forecasting Models
# ============================================================
def qlike(actual, forecast):
    """QLIKE loss function (scale-independent)."""
    # QLIKE = mean(actual/forecast - log(actual/forecast) - 1)
    # Use variance proxy: actual^2 and forecast^2
    ratio = actual / np.maximum(forecast, 1e-8)
    return float(np.mean(ratio - np.log(ratio) - 1))


def mse(actual, forecast):
    """Mean Squared Error."""
    return float(np.mean((actual - forecast) ** 2))


def r2_oos(actual, forecast):
    """Out-of-sample R-squared."""
    ss_res = np.sum((actual - forecast) ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    return float(1 - ss_res / ss_tot)


def dm_test(e1, e2, h=1):
    """Diebold-Mariano test (two-sided).
    H0: equal predictive accuracy.
    e1, e2: squared forecast errors from model 1 and model 2.
    Returns t-stat and p-value.
    """
    d = e1 - e2
    n = len(d)
    d_bar = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=0)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma_0 / n

    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return float(dm_stat), float(p_value)


def block_bootstrap_pvalue(e1, e2, n_boot=5000, block_size=21, seed=42):
    """Block bootstrap test for forecast comparison.
    H0: Model 1 and Model 2 have equal MSE.
    Returns p-value (two-sided).
    """
    rng = np.random.RandomState(seed)
    d = e1 - e2  # loss differential
    n = len(d)
    observed_stat = np.mean(d)

    # Center the loss differential under H0
    d_centered = d - observed_stat

    boot_stats = np.empty(n_boot)
    n_blocks = int(np.ceil(n / block_size))

    for b in range(n_boot):
        # Draw random block starts
        starts = rng.randint(0, n - block_size + 1, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]
        boot_stats[b] = np.mean(d_centered[indices])

    p_value = float(np.mean(np.abs(boot_stats) >= np.abs(observed_stat)))
    return p_value


def run_forecasting(df, target="rv5_fwd", oos_start="2023-01-01", oos_end="2024-12-31"):
    """Run forecasting competition."""
    oos_start = pd.Timestamp(oos_start)
    oos_end = pd.Timestamp(oos_end)

    # Define feature sets
    feature_sets = {
        "baseline_rv": ["rv21_lag1"],
        "vix_only": ["vix_lag1", "vix_ma5_lag1"],
        "gpr_only": ["gpr_lag1", "gpr_ma7_lag1", "gpr_ma21_lag1", "gpr_zscore_lag1"],
        "gpr_decomposed": ["gpr_act_lag1", "gpr_threat_lag1", "gpr_ma21_lag1"],
        "vix_gpr": ["vix_lag1", "vix_ma5_lag1", "gpr_lag1", "gpr_ma7_lag1", "gpr_zscore_lag1"],
        "kitchen_sink": ["rv21_lag1", "vix_lag1", "vix_ma5_lag1", "vix_change_lag1",
                         "gpr_lag1", "gpr_ma7_lag1", "gpr_ma21_lag1", "gpr_zscore_lag1",
                         "gpr_change_lag1", "gpr_log_lag1", "gpr_act_lag1", "gpr_threat_lag1"],
    }

    results = {}
    forecasts_all = {}

    for name, features in feature_sets.items():
        # Check all features exist
        missing = [f for f in features if f not in df.columns]
        if missing:
            print(f"WARNING: {name} missing features: {missing}")
            continue

        # Prepare data
        mask = df[features + [target]].notna().all(axis=1)
        data = df[mask].copy()

        is_train = data.index < oos_start
        is_oos = (data.index >= oos_start) & (data.index <= oos_end)

        X_train = data.loc[is_train, features].values
        y_train = data.loc[is_train, target].values
        X_oos = data.loc[is_oos, features].values
        y_oos = data.loc[is_oos, target].values

        if len(X_oos) < 50:
            print(f"WARNING: {name} has only {len(X_oos)} OOS observations")
            continue

        # Ridge regression (alpha=1.0)
        model = Ridge(alpha=1.0)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_oos)

        # Ensure positive predictions
        y_pred = np.maximum(y_pred, 0.1)

        # Metrics
        mse_val = mse(y_oos, y_pred)
        qlike_val = qlike(y_oos, y_pred)
        r2_val = r2_oos(y_oos, y_pred)

        # Coefficients
        coefs = {features[i]: round(float(model.coef_[i]), 6) for i in range(len(features))}
        coefs["intercept"] = round(float(model.intercept_), 6)

        results[name] = {
            "features": features,
            "n_train": int(np.sum(is_train)),
            "n_oos": int(np.sum(is_oos)),
            "mse": round(mse_val, 4),
            "rmse": round(np.sqrt(mse_val), 4),
            "qlike": round(qlike_val, 6),
            "r2_oos": round(r2_val, 4),
            "coefficients": coefs,
        }

        forecasts_all[name] = {
            "y_oos": y_oos,
            "y_pred": y_pred,
            "errors_sq": (y_oos - y_pred) ** 2,
        }

        print(f"{name}: MSE={mse_val:.4f}, QLIKE={qlike_val:.6f}, R2_OOS={r2_val:.4f}")

    # DM tests: compare each model to baseline
    if "baseline_rv" in forecasts_all:
        e_base = forecasts_all["baseline_rv"]["errors_sq"]
        for name in forecasts_all:
            if name == "baseline_rv":
                continue
            e_model = forecasts_all[name]["errors_sq"]
            # Align lengths
            n_min = min(len(e_base), len(e_model))
            dm_stat, dm_p = dm_test(e_base[:n_min], e_model[:n_min], h=5)
            boot_p = block_bootstrap_pvalue(e_base[:n_min], e_model[:n_min])

            results[name]["dm_vs_baseline"] = {
                "dm_statistic": round(dm_stat, 4),
                "dm_pvalue": round(dm_p, 6),
                "bootstrap_pvalue": round(boot_p, 4),
                "better_than_baseline": bool(dm_stat > 0 and dm_p < 0.05),
            }

    # DM tests: VIX+GPR vs VIX only
    if "vix_only" in forecasts_all and "vix_gpr" in forecasts_all:
        e_vix = forecasts_all["vix_only"]["errors_sq"]
        e_vixgpr = forecasts_all["vix_gpr"]["errors_sq"]
        n_min = min(len(e_vix), len(e_vixgpr))
        dm_stat, dm_p = dm_test(e_vix[:n_min], e_vixgpr[:n_min], h=5)
        boot_p = block_bootstrap_pvalue(e_vix[:n_min], e_vixgpr[:n_min])
        results["vix_gpr"]["dm_vs_vix_only"] = {
            "dm_statistic": round(dm_stat, 4),
            "dm_pvalue": round(dm_p, 6),
            "bootstrap_pvalue": round(boot_p, 4),
            "gpr_adds_value": bool(dm_stat > 0 and dm_p < 0.05),
        }

    return results, forecasts_all


# ============================================================
# STEP 6: Regime Analysis
# ============================================================
def regime_analysis(df, target="rv5_fwd"):
    """Analyze GPR-volatility relationship across regimes."""
    # Define regimes based on GPR level
    gpr_p75 = df["gpr"].quantile(0.75)
    gpr_p90 = df["gpr"].quantile(0.90)
    gpr_p50 = df["gpr"].quantile(0.50)

    df_temp = df.copy()
    df_temp["gpr_regime"] = "low"
    df_temp.loc[df_temp["gpr"] > gpr_p50, "gpr_regime"] = "medium"
    df_temp.loc[df_temp["gpr"] > gpr_p75, "gpr_regime"] = "high"
    df_temp.loc[df_temp["gpr"] > gpr_p90, "gpr_regime"] = "extreme"

    regime_stats = {}
    for regime in ["low", "medium", "high", "extreme"]:
        subset = df_temp[df_temp["gpr_regime"] == regime]
        if len(subset) < 30:
            continue

        # GPR-RV correlation in this regime
        mask = subset[["gpr", target]].notna().all(axis=1)
        sub = subset[mask]
        corr_gpr_rv = float(sub["gpr"].corr(sub[target]))

        # Average realized vol in this regime
        avg_rv = float(sub[target].mean())
        avg_vix = float(sub["vix"].mean())
        avg_gpr = float(sub["gpr"].mean())

        regime_stats[regime] = {
            "n_obs": int(len(sub)),
            "avg_gpr": round(avg_gpr, 2),
            "avg_vix": round(avg_vix, 2),
            "avg_rv": round(avg_rv, 2),
            "gpr_rv_corr": round(corr_gpr_rv, 4),
        }

    # Rolling correlation: GPR vs RV
    rolling_corr = df[["gpr", target]].dropna()
    rc_126 = rolling_corr["gpr"].rolling(126).corr(rolling_corr[target])

    # Correlation stability
    rc_stats = {
        "mean": round(float(rc_126.mean()), 4),
        "std": round(float(rc_126.std()), 4),
        "min": round(float(rc_126.min()), 4),
        "max": round(float(rc_126.max()), 4),
        "pct_positive": round(float((rc_126 > 0).mean()), 4),
    }

    # Known geopolitical events analysis
    events = {
        "9/11": ("2001-09-01", "2001-12-31"),
        "Iraq_War": ("2003-03-01", "2003-06-30"),
        "Crimea": ("2014-02-01", "2014-06-30"),
        "US_China_Trade": ("2018-03-01", "2019-12-31"),
        "COVID": ("2020-01-01", "2020-06-30"),
        "Ukraine_War": ("2022-02-01", "2022-12-31"),
        "Israel_Hamas": ("2023-10-01", "2024-03-31"),
    }

    event_analysis = {}
    for event_name, (start, end) in events.items():
        mask = (df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))
        if mask.sum() < 10:
            continue
        subset = df[mask]

        # Compare GPR-RV relationship during event vs overall
        gpr_rv_corr = float(subset["gpr"].corr(subset[target])) if subset[target].notna().sum() > 10 else None
        avg_gpr = float(subset["gpr"].mean())
        avg_rv = float(subset[target].mean()) if subset[target].notna().sum() > 0 else None

        event_analysis[event_name] = {
            "n_days": int(mask.sum()),
            "avg_gpr": round(avg_gpr, 2),
            "avg_rv": round(avg_rv, 2) if avg_rv else None,
            "gpr_rv_corr": round(gpr_rv_corr, 4) if gpr_rv_corr else None,
        }

    return {
        "regime_stats": regime_stats,
        "rolling_corr_stats": rc_stats,
        "event_analysis": event_analysis,
        "thresholds": {
            "p50": round(float(gpr_p50), 2),
            "p75": round(float(gpr_p75), 2),
            "p90": round(float(gpr_p90), 2),
        }
    }


# ============================================================
# STEP 7: Granger Causality
# ============================================================
def granger_causality(df, max_lag=10):
    """Test Granger causality: GPR -> VIX and GPR -> RV."""
    from statsmodels.tsa.stattools import grangercausalitytests

    results = {}

    for target_col, target_name in [("vix", "GPR->VIX"), ("rv21", "GPR->RV21")]:
        pair = df[["gpr", target_col]].dropna()
        if len(pair) < 500:
            results[target_name] = {"error": "insufficient data"}
            continue

        # Use last 5000 obs for speed
        if len(pair) > 5000:
            pair = pair.tail(5000)

        # grangercausalitytests expects [y, x] format
        # Testing: does 'gpr' Granger-cause 'target_col'?
        test_data = pair[[target_col, "gpr"]].values

        try:
            gc_results = grangercausalitytests(test_data, maxlag=max_lag, verbose=False)

            lag_results = {}
            for lag in range(1, max_lag + 1):
                f_stat = gc_results[lag][0]["ssr_ftest"][0]
                f_pval = gc_results[lag][0]["ssr_ftest"][1]
                lag_results[str(lag)] = {
                    "f_statistic": round(float(f_stat), 4),
                    "f_pvalue": round(float(f_pval), 6),
                    "significant": bool(f_pval < 0.05),
                }

            results[target_name] = lag_results
        except Exception as e:
            results[target_name] = {"error": str(e)}

    # Reverse: VIX -> GPR
    pair = df[["gpr", "vix"]].dropna()
    if len(pair) > 5000:
        pair = pair.tail(5000)

    try:
        test_data = pair[["gpr", "vix"]].values
        gc_results = grangercausalitytests(test_data, maxlag=max_lag, verbose=False)

        lag_results = {}
        for lag in range(1, max_lag + 1):
            f_stat = gc_results[lag][0]["ssr_ftest"][0]
            f_pval = gc_results[lag][0]["ssr_ftest"][1]
            lag_results[str(lag)] = {
                "f_statistic": round(float(f_stat), 4),
                "f_pvalue": round(float(f_pval), 6),
                "significant": bool(f_pval < 0.05),
            }

        results["VIX->GPR"] = lag_results
    except Exception as e:
        results["VIX->GPR"] = {"error": str(e)}

    return results


# ============================================================
# STEP 8: Incremental Partial Correlation
# ============================================================
def incremental_analysis(df, target="rv5_fwd"):
    """Test if GPR has incremental predictive power after controlling for VIX."""
    from statsmodels.regression.linear_model import OLS
    from statsmodels.tools import add_constant

    mask = df[["vix_lag1", "gpr_lag1", "gpr_zscore_lag1", target]].notna().all(axis=1)
    data = df[mask]

    y = data[target].values

    # Model 1: VIX only
    X1 = add_constant(data[["vix_lag1"]].values)
    m1 = OLS(y, X1).fit()

    # Model 2: VIX + GPR
    X2 = add_constant(data[["vix_lag1", "gpr_lag1"]].values)
    m2 = OLS(y, X2).fit()

    # Model 3: VIX + GPR z-score
    X3 = add_constant(data[["vix_lag1", "gpr_zscore_lag1"]].values)
    m3 = OLS(y, X3).fit()

    # Partial correlation: GPR controlling for VIX
    # Residualize both target and GPR on VIX
    vix_vals = add_constant(data["vix_lag1"].values)
    resid_target = OLS(y, vix_vals).fit().resid
    resid_gpr = OLS(data["gpr_lag1"].values, vix_vals).fit().resid
    resid_gpr_z = OLS(data["gpr_zscore_lag1"].values, vix_vals).fit().resid

    partial_corr_gpr = float(np.corrcoef(resid_target, resid_gpr)[0, 1])
    partial_corr_gpr_z = float(np.corrcoef(resid_target, resid_gpr_z)[0, 1])

    # T-test for partial correlation
    n = len(resid_target)
    t_stat_gpr = partial_corr_gpr * np.sqrt(n - 3) / np.sqrt(1 - partial_corr_gpr**2)
    p_val_gpr = 2 * (1 - stats.t.cdf(abs(t_stat_gpr), df=n - 3))

    t_stat_gpr_z = partial_corr_gpr_z * np.sqrt(n - 3) / np.sqrt(1 - partial_corr_gpr_z**2)
    p_val_gpr_z = 2 * (1 - stats.t.cdf(abs(t_stat_gpr_z), df=n - 3))

    return {
        "vix_only": {
            "r2": round(float(m1.rsquared), 6),
            "adj_r2": round(float(m1.rsquared_adj), 6),
            "aic": round(float(m1.aic), 2),
            "bic": round(float(m1.bic), 2),
        },
        "vix_plus_gpr": {
            "r2": round(float(m2.rsquared), 6),
            "adj_r2": round(float(m2.rsquared_adj), 6),
            "aic": round(float(m2.aic), 2),
            "bic": round(float(m2.bic), 2),
            "gpr_tstat": round(float(m2.tvalues[2]), 4),
            "gpr_pvalue": round(float(m2.pvalues[2]), 6),
        },
        "vix_plus_gpr_zscore": {
            "r2": round(float(m3.rsquared), 6),
            "adj_r2": round(float(m3.rsquared_adj), 6),
            "aic": round(float(m3.aic), 2),
            "bic": round(float(m3.bic), 2),
            "gpr_z_tstat": round(float(m3.tvalues[2]), 4),
            "gpr_z_pvalue": round(float(m3.pvalues[2]), 6),
        },
        "partial_correlations": {
            "gpr_controlling_vix": round(partial_corr_gpr, 6),
            "gpr_controlling_vix_tstat": round(float(t_stat_gpr), 4),
            "gpr_controlling_vix_pvalue": round(float(p_val_gpr), 6),
            "gpr_zscore_controlling_vix": round(partial_corr_gpr_z, 6),
            "gpr_zscore_controlling_vix_tstat": round(float(t_stat_gpr_z), 4),
            "gpr_zscore_controlling_vix_pvalue": round(float(p_val_gpr_z), 6),
            "exceeds_harvey_threshold": bool(abs(t_stat_gpr) > 3.0),
        },
        "n_obs": int(n),
    }


# ============================================================
# STEP 9: Sub-period / Rolling OOS Analysis
# ============================================================
def rolling_oos_analysis(df, target="rv5_fwd", window=500):
    """Expanding window OOS to test stability."""
    features_vix = ["vix_lag1", "vix_ma5_lag1"]
    features_vix_gpr = ["vix_lag1", "vix_ma5_lag1", "gpr_lag1", "gpr_ma7_lag1", "gpr_zscore_lag1"]

    all_cols = features_vix_gpr + [target]
    mask = df[all_cols].notna().all(axis=1)
    data = df[mask].copy()

    dates = data.index
    n = len(data)

    # Start OOS from 2005 onwards (need training data)
    oos_start_idx = max(window, (dates >= pd.Timestamp("2005-01-01")).argmax())

    results_by_year = {}
    errors_vix = []
    errors_vixgpr = []

    for i in range(oos_start_idx, n):
        X_train_vix = data.iloc[:i][features_vix].values
        X_train_gpr = data.iloc[:i][features_vix_gpr].values
        y_train = data.iloc[:i][target].values

        X_test_vix = data.iloc[i:i+1][features_vix].values
        X_test_gpr = data.iloc[i:i+1][features_vix_gpr].values
        y_test = data.iloc[i:i+1][target].values[0]

        # VIX model
        m_vix = Ridge(alpha=1.0).fit(X_train_vix, y_train)
        pred_vix = max(m_vix.predict(X_test_vix)[0], 0.1)

        # VIX+GPR model
        m_gpr = Ridge(alpha=1.0).fit(X_train_gpr, y_train)
        pred_gpr = max(m_gpr.predict(X_test_gpr)[0], 0.1)

        errors_vix.append((y_test - pred_vix) ** 2)
        errors_vixgpr.append((y_test - pred_gpr) ** 2)

        year = dates[i].year
        if year not in results_by_year:
            results_by_year[year] = {"errors_vix": [], "errors_vixgpr": []}
        results_by_year[year]["errors_vix"].append(errors_vix[-1])
        results_by_year[year]["errors_vixgpr"].append(errors_vixgpr[-1])

    # Aggregate by year
    yearly_results = {}
    for year, data_yr in results_by_year.items():
        e_v = np.array(data_yr["errors_vix"])
        e_g = np.array(data_yr["errors_vixgpr"])
        mse_vix = float(e_v.mean())
        mse_gpr = float(e_g.mean())

        yearly_results[str(year)] = {
            "mse_vix": round(mse_vix, 4),
            "mse_vix_gpr": round(mse_gpr, 4),
            "mse_ratio": round(mse_gpr / mse_vix, 4) if mse_vix > 0 else None,
            "gpr_improves": bool(mse_gpr < mse_vix),
            "n_obs": int(len(e_v)),
        }

    # Overall
    errors_vix = np.array(errors_vix)
    errors_vixgpr = np.array(errors_vixgpr)
    dm_stat, dm_p = dm_test(errors_vix, errors_vixgpr, h=5)

    return {
        "yearly_results": yearly_results,
        "overall": {
            "mse_vix": round(float(errors_vix.mean()), 4),
            "mse_vix_gpr": round(float(errors_vixgpr.mean()), 4),
            "dm_statistic": round(dm_stat, 4),
            "dm_pvalue": round(dm_p, 6),
            "n_total_oos": int(len(errors_vix)),
        }
    }


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 70)
    print("K446: Geopolitical Risk Index (GPR) and Stock Market Volatility")
    print("=" * 70)

    # Step 1: Load data
    print("\n[1/8] Loading GPR data...")
    gpr = load_gpr_data()
    print(f"  GPR: {gpr.index.min().date()} to {gpr.index.max().date()}, N={len(gpr)}")

    print("\n[2/8] Loading SPY & VIX...")
    spy_ret, rv21, rv5_fwd, rv21_fwd, vix_close = load_market_data()
    print(f"  SPY: {spy_ret.index.min().date()} to {spy_ret.index.max().date()}, N={len(spy_ret)}")
    print(f"  VIX: {vix_close.index.min().date()} to {vix_close.index.max().date()}, N={len(vix_close)}")

    print("\n[3/8] Preparing dataset...")
    df = prepare_dataset(gpr, spy_ret, rv21, rv5_fwd, rv21_fwd, vix_close)
    print(f"  Merged dataset: {df.index.min().date()} to {df.index.max().date()}, N={len(df)}")

    # Step 2: Diagnostics
    print("\n[4/8] Descriptive statistics & diagnostics...")
    desc_stats = descriptive_stats(df)
    for k, v in desc_stats.items():
        print(f"  {k}: mean={v['mean']:.2f}, std={v['std']:.2f}, skew={v['skew']:.2f}, kurt={v['kurtosis']:.2f}")

    stationarity = stationarity_tests(df)
    for k, v in stationarity.items():
        print(f"  ADF({k}): stat={v['adf_statistic']:.4f}, p={v['adf_pvalue']:.6f}, stationary={v['stationary']}")

    corr_result = correlation_analysis(df)
    print(f"  GPR-VIX contemporaneous corr: {corr_result['contemporaneous']['gpr']['vix']}")
    print(f"  GPR-RV21 contemporaneous corr: {corr_result['contemporaneous']['gpr']['rv21']}")
    print(f"  GPR-RV5fwd contemporaneous corr: {corr_result['contemporaneous']['gpr']['rv5_fwd']}")

    # Step 3: Granger causality
    print("\n[5/8] Granger causality tests...")
    granger = granger_causality(df)
    for test_name, test_result in granger.items():
        if "error" in test_result:
            print(f"  {test_name}: ERROR - {test_result['error']}")
        else:
            sig_lags = [lag for lag, r in test_result.items() if r.get("significant", False)]
            print(f"  {test_name}: significant at lags {sig_lags if sig_lags else 'NONE'}")

    # Step 4: Forecasting
    print("\n[6/8] Forecasting competition (OOS: 2023-2024)...")
    # Run for both 5-day and 21-day forward RV
    forecast_results_5d, forecasts_5d = run_forecasting(df, target="rv5_fwd")
    print("\n  --- 21-day forward RV ---")
    forecast_results_21d, forecasts_21d = run_forecasting(df, target="rv21_fwd")

    # Step 5: Incremental analysis
    print("\n[7/8] Incremental analysis (partial correlations)...")
    incremental_5d = incremental_analysis(df, target="rv5_fwd")
    incremental_21d = incremental_analysis(df, target="rv21_fwd")
    print(f"  RV5fwd: partial corr(GPR|VIX)={incremental_5d['partial_correlations']['gpr_controlling_vix']:.6f}, "
          f"t={incremental_5d['partial_correlations']['gpr_controlling_vix_tstat']:.4f}")
    print(f"  RV21fwd: partial corr(GPR|VIX)={incremental_21d['partial_correlations']['gpr_controlling_vix']:.6f}, "
          f"t={incremental_21d['partial_correlations']['gpr_controlling_vix_tstat']:.4f}")
    print(f"  Harvey (2016) |t|>3.0: 5d={incremental_5d['partial_correlations']['exceeds_harvey_threshold']}, "
          f"21d={incremental_21d['partial_correlations']['exceeds_harvey_threshold']}")

    # Step 6: Regime analysis
    print("\n[8/8] Regime analysis...")
    regime = regime_analysis(df, target="rv5_fwd")
    for r_name, r_stats in regime["regime_stats"].items():
        print(f"  {r_name}: n={r_stats['n_obs']}, avg_gpr={r_stats['avg_gpr']:.1f}, "
              f"avg_rv={r_stats['avg_rv']:.1f}, corr={r_stats['gpr_rv_corr']:.4f}")

    # Rolling OOS (this takes longer)
    print("\n[BONUS] Rolling OOS analysis (expanding window)...")
    rolling_oos = rolling_oos_analysis(df, target="rv5_fwd")
    print(f"  Overall: MSE_VIX={rolling_oos['overall']['mse_vix']:.4f}, "
          f"MSE_VIX+GPR={rolling_oos['overall']['mse_vix_gpr']:.4f}, "
          f"DM p={rolling_oos['overall']['dm_pvalue']:.6f}")

    # ============================================================
    # COMPILE RESULTS
    # ============================================================

    # Determine key findings
    gpr_helps_5d = forecast_results_5d.get("vix_gpr", {}).get("dm_vs_vix_only", {}).get("gpr_adds_value", False)
    partial_significant_5d = incremental_5d["partial_correlations"]["exceeds_harvey_threshold"]
    granger_gpr_vix = any(
        v.get("significant", False)
        for k, v in granger.get("GPR->VIX", {}).items()
        if isinstance(v, dict)
    )
    granger_gpr_rv = any(
        v.get("significant", False)
        for k, v in granger.get("GPR->RV21", {}).items()
        if isinstance(v, dict)
    )

    all_results = {
        "experiment_id": "K446",
        "title": "Geopolitical Risk Index (GPR) and Stock Market Volatility",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_sources": {
            "gpr": "Caldara & Iacoviello (2022), matteoiacoviello.com/gpr.htm, daily GPR index",
            "spy": "yfinance SPY",
            "vix": "yfinance ^VIX",
            "sample_period": f"{df.index.min().date()} to {df.index.max().date()}",
            "n_observations": int(len(df)),
            "oos_period": "2023-01-01 to 2024-12-31",
        },
        "literature": {
            "primary": "Caldara & Iacoviello (2022) AER 112(4):1194-1225",
            "related": [
                "Kannadhasan & Das (2020) J. Business Research",
                "2023 ScienceDirect: ML models for GPR vol forecasting",
            ]
        },
        "diagnostics": {
            "descriptive_stats": desc_stats,
            "stationarity": stationarity,
            "correlations": corr_result,
        },
        "granger_causality": granger,
        "forecasting_rv5_fwd": forecast_results_5d,
        "forecasting_rv21_fwd": forecast_results_21d,
        "incremental_analysis": {
            "rv5_fwd": incremental_5d,
            "rv21_fwd": incremental_21d,
        },
        "regime_analysis": regime,
        "rolling_oos": rolling_oos,
        "key_findings": {
            "gpr_vix_contemporaneous_corr": corr_result["contemporaneous"]["gpr"]["vix"],
            "gpr_rv21_contemporaneous_corr": corr_result["contemporaneous"]["gpr"]["rv21"],
            "granger_gpr_causes_vix": granger_gpr_vix,
            "granger_gpr_causes_rv": granger_gpr_rv,
            "gpr_adds_to_vix_for_5d_rv": gpr_helps_5d,
            "partial_corr_exceeds_harvey": partial_significant_5d,
            "partial_corr_gpr_controlling_vix_5d": incremental_5d["partial_correlations"]["gpr_controlling_vix"],
            "partial_corr_gpr_controlling_vix_21d": incremental_21d["partial_correlations"]["gpr_controlling_vix"],
        },
        "conclusions": [],  # will be filled below
        "limitations": [
            "GPR index is based on English-language newspapers (10 major publications), may miss non-English geopolitical developments",
            "Daily GPR has significant noise; smoothed versions (MA7/MA21) may be more informative",
            "Linear models only; nonlinear/regime-switching effects may exist but are not captured",
            "SPY only; results may differ for international/EM equity indices",
            "OOS period 2023-2024 includes specific geopolitical events (Ukraine war continuation, Israel-Hamas); results may not generalize",
            "No transaction costs or implementability analysis",
        ],
    }

    # Build conclusions based on evidence
    conclusions = []

    if gpr_helps_5d:
        conclusions.append("GPR provides statistically significant incremental information for 5-day RV forecasting beyond VIX (DM test p<0.05)")
    else:
        conclusions.append("GPR does NOT provide statistically significant incremental information for 5-day RV forecasting beyond VIX")

    if partial_significant_5d:
        conclusions.append(f"Partial correlation GPR|VIX exceeds Harvey (2016) |t|>3.0 threshold — robust finding")
    else:
        conclusions.append(f"Partial correlation GPR|VIX does NOT exceed Harvey (2016) |t|>3.0 threshold — weak/null finding")

    if granger_gpr_vix:
        conclusions.append("GPR Granger-causes VIX at some lags — geopolitical risk leads market fear")
    else:
        conclusions.append("GPR does NOT Granger-cause VIX — no leading indicator evidence")

    if granger_gpr_rv:
        conclusions.append("GPR Granger-causes realized volatility — direct predictive channel exists")
    else:
        conclusions.append("GPR does NOT Granger-cause realized volatility — no direct predictive channel")

    # Regime conclusion
    extreme_regime = regime.get("regime_stats", {}).get("extreme", {})
    if extreme_regime:
        conclusions.append(
            f"In extreme GPR regime (>p90): avg RV={extreme_regime['avg_rv']:.1f}%, "
            f"GPR-RV corr={extreme_regime['gpr_rv_corr']:.4f}"
        )

    all_results["conclusions"] = conclusions

    # Save
    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {RESULTS_FILE}")

    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    for c in conclusions:
        print(f"  • {c}")
    print("=" * 70)

    return all_results


if __name__ == "__main__":
    results = main()
