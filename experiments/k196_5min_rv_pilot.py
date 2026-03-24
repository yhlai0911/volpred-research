"""
K196: 5-Minute Realized Variance Pilot — Extended Analysis
==========================================================
[提出: User, 執行: Claude]

Background:
- K188 proved ceiling is in DATA not MODEL
- K156 found overnight gaps = 47.4% of variance, BPV most predictable
- We now have ~47 days of accumulated 5-min SPY data

Research Questions:
1. Does RV from 5-min data provide a better forecast target than c2c r²?
2. HAR-RV model vs GJR-GARCH — which forecasts better with RV target?
3. BPV vs RV — which is more forecastable?

Methodology:
1. Load 5-min intraday data → compute daily RV, BPV, JV
2. HAR-RV: RV_t = β0 + β1*RV_{t-1} + β5*mean(RV_{t-5:t-1}) + β22*mean(RV_{t-22:t-1})
3. Also HAR-BPV variant
4. GJR-GARCH on close-to-close returns
5. QLIKE with RV as target (not r²)
6. Expanding-window pseudo-OOS from day 30 onward

PRELIMINARY: 47 days is too short for proper OOS. Results are indicative only.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------------------
# 1. DATA LOADING
# ---------------------------------------------------------------------------

# In worktree, data/ may not have intraday — use main repo
_repo_root = Path(__file__).resolve().parent.parent
_main_repo = Path("/Users/yhlai0911/Desktop/volpred-research")
DATA_DIR = (_main_repo / "data" / "intraday") if (_main_repo / "data" / "intraday").exists() else (_repo_root / "data" / "intraday")
STORAGE_DIR = _repo_root / "storage" / "experiments"


def load_5min_data():
    """Load all SPY 5-min CSV files, return dict date -> DataFrame."""
    files = sorted(DATA_DIR.glob("SPY_5min_*.csv"))
    daily_data = {}

    for f in files:
        date_str = f.stem.replace("SPY_5min_", "")
        df = pd.read_csv(f, skiprows=2)  # skip ticker + NaN rows
        df.columns = ["Datetime", "Close", "High", "Low", "Open", "Volume"]
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df["Open"] = pd.to_numeric(df["Open"], errors="coerce")
        df["High"] = pd.to_numeric(df["High"], errors="coerce")
        df["Low"] = pd.to_numeric(df["Low"], errors="coerce")
        df = df.dropna(subset=["Close"])

        # Filter to regular trading hours: 13:30-20:00 UTC = 9:30-16:00 ET
        # Keep bars from 13:30 to 19:55 (each bar covers the NEXT 5 min)
        df = df[(df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute >= 13 * 60 + 30) &
                (df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute <= 20 * 60 + 55)]
        df = df.sort_values("Datetime").reset_index(drop=True)

        if len(df) >= 10:
            daily_data[date_str] = df

    return daily_data


# ---------------------------------------------------------------------------
# 2. RV DECOMPOSITION
# ---------------------------------------------------------------------------

def compute_daily_rv_components(daily_data):
    """Compute RV, BPV, JV, overnight gap, semivariance for each day."""
    dates = sorted(daily_data.keys())
    results = []

    for i, date in enumerate(dates):
        df = daily_data[date]
        close_prices = df["Close"].values
        open_prices = df["Open"].values

        # Log returns (5-min)
        log_close = np.log(close_prices)
        r = np.diff(log_close)

        if len(r) < 5:
            continue

        # (a) Realized Variance
        rv = np.sum(r ** 2)

        # (b) Bipower Variation: BPV = (π/2) * Σ |r_i| * |r_{i-1}|
        abs_r = np.abs(r)
        bpv = (np.pi / 2) * np.sum(abs_r[1:] * abs_r[:-1])

        # (c) Jump Variation
        jv = max(rv - bpv, 0)

        # (d) Realized Semivariance
        rs_neg = np.sum(r[r < 0] ** 2)
        rs_pos = np.sum(r[r >= 0] ** 2)

        # (e) Overnight Gap
        overnight_gap_sq = 0.0
        overnight_return = np.nan
        if i > 0:
            prev_date = dates[i - 1]
            prev_df = daily_data[prev_date]
            prev_close = prev_df["Close"].iloc[-1]
            today_open = open_prices[0]
            overnight_return = np.log(today_open) - np.log(prev_close)
            overnight_gap_sq = overnight_return ** 2

        # (f) Close-to-close return (intraday only: open_bar_1 -> close_bar_last)
        c2c_return_intraday = np.log(close_prices[-1]) - np.log(close_prices[0])
        c2c_var = c2c_return_intraday ** 2

        # (g) Full day return including overnight
        if i > 0:
            prev_close = daily_data[dates[i - 1]]["Close"].iloc[-1]
            full_return = np.log(close_prices[-1]) - np.log(prev_close)
            full_var = full_return ** 2
        else:
            full_return = c2c_return_intraday
            full_var = c2c_var

        # Total = intraday RV + overnight
        total_rv = rv + overnight_gap_sq

        results.append({
            "date": date,
            "rv": rv,
            "bpv": bpv,
            "jv": jv,
            "rs_neg": rs_neg,
            "rs_pos": rs_pos,
            "overnight_sq": overnight_gap_sq,
            "overnight_return": overnight_return,
            "intraday_rv": rv,
            "total_rv": total_rv,
            "c2c_var": c2c_var,
            "full_var": full_var,
            "n_bars": len(r),
            "intraday_return": c2c_return_intraday,
            "full_return": full_return,
        })

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# 3. HAR-RV MODEL
# ---------------------------------------------------------------------------

def construct_har_features(series, min_history=22):
    """Build HAR features: daily, weekly (5d), monthly (22d) lagged averages.

    Returns:
        X: DataFrame with columns [rv_1, rv_5, rv_22]
        y: target series (aligned)
        valid_idx: valid indices
    """
    n = len(series)
    X_rows = []
    y_vals = []
    indices = []

    for t in range(min_history, n):
        rv_1 = series.iloc[t - 1]
        rv_5 = series.iloc[t - 5:t].mean()
        rv_22 = series.iloc[t - 22:t].mean() if t >= 22 else series.iloc[:t].mean()

        X_rows.append([rv_1, rv_5, rv_22])
        y_vals.append(series.iloc[t])
        indices.append(t)

    X = pd.DataFrame(X_rows, columns=["rv_1", "rv_5", "rv_22"], index=indices)
    y = pd.Series(y_vals, index=indices)
    return X, y


def har_expanding_oos(series, first_oos=30, min_train=25):
    """Expanding-window HAR-RV pseudo-OOS forecast.

    For each t >= first_oos:
        Train on [0, t-1], forecast t.
    """
    n = len(series)
    if n < first_oos + 1:
        return None

    forecasts = []
    actuals = []
    dates_oos = []

    for t in range(first_oos, n):
        # Build HAR features on training window
        train_series = series.iloc[:t]
        X_train, y_train = construct_har_features(train_series, min_history=22)

        if len(X_train) < 5:
            continue

        # OLS fit: y = Xβ + ε
        X_mat = np.column_stack([np.ones(len(X_train)), X_train.values])
        y_vec = y_train.values

        try:
            beta = np.linalg.lstsq(X_mat, y_vec, rcond=None)[0]
        except np.linalg.LinAlgError:
            continue

        # Forecast for t
        rv_1 = series.iloc[t - 1]
        rv_5 = series.iloc[t - 5:t].mean()
        rv_22 = series.iloc[max(0, t - 22):t].mean()
        x_new = np.array([1.0, rv_1, rv_5, rv_22])
        forecast = x_new @ beta

        # Floor at small positive number
        forecast = max(forecast, 1e-10)

        forecasts.append(forecast)
        actuals.append(series.iloc[t])
        dates_oos.append(t)

    return {
        "forecasts": np.array(forecasts),
        "actuals": np.array(actuals),
        "indices": dates_oos,
    }


# ---------------------------------------------------------------------------
# 4. GJR-GARCH (simplified, no arch dependency)
# ---------------------------------------------------------------------------

def gjr_garch_expanding_oos(returns, first_oos=30):
    """Expanding-window GJR-GARCH(1,1) via MLE.

    σ²_t = ω + α*ε²_{t-1} + γ*ε²_{t-1}*I(ε<0) + β*σ²_{t-1}
    """
    from scipy.optimize import minimize

    n = len(returns)
    if n < first_oos + 1:
        return None

    def gjr_nll(params, ret):
        """Negative log-likelihood for GJR-GARCH(1,1)."""
        omega, alpha, gamma, beta = params
        T = len(ret)
        sigma2 = np.zeros(T)
        sigma2[0] = np.var(ret)

        for t in range(1, T):
            indicator = 1.0 if ret[t - 1] < 0 else 0.0
            sigma2[t] = (omega + alpha * ret[t - 1] ** 2
                         + gamma * ret[t - 1] ** 2 * indicator
                         + beta * sigma2[t - 1])
            sigma2[t] = max(sigma2[t], 1e-12)

        ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + ret ** 2 / sigma2)
        return -ll

    forecasts = []
    actuals_r2 = []
    dates_oos = []

    for t in range(first_oos, n):
        train_ret = returns[:t]
        var_ret = np.var(train_ret)

        x0 = [var_ret * 0.05, 0.05, 0.05, 0.85]
        bounds = [(1e-10, None), (1e-6, 0.5), (0.0, 0.5), (0.5, 0.9999)]

        try:
            res = minimize(gjr_nll, x0, args=(train_ret,), method='L-BFGS-B',
                           bounds=bounds, options={'maxiter': 500})
            if not res.success:
                continue
            omega, alpha, gamma, beta_p = res.x
        except Exception:
            continue

        # Compute in-sample sigma2 for full training window
        sigma2 = np.zeros(len(train_ret))
        sigma2[0] = var_ret
        for s in range(1, len(train_ret)):
            ind = 1.0 if train_ret[s - 1] < 0 else 0.0
            sigma2[s] = (omega + alpha * train_ret[s - 1] ** 2
                         + gamma * train_ret[s - 1] ** 2 * ind
                         + beta_p * sigma2[s - 1])
            sigma2[s] = max(sigma2[s], 1e-12)

        # One-step forecast
        last_ret = train_ret[-1]
        last_sigma2 = sigma2[-1]
        ind = 1.0 if last_ret < 0 else 0.0
        h_forecast = (omega + alpha * last_ret ** 2
                      + gamma * last_ret ** 2 * ind
                      + beta_p * last_sigma2)
        h_forecast = max(h_forecast, 1e-12)

        forecasts.append(h_forecast)
        actuals_r2.append(returns[t] ** 2)
        dates_oos.append(t)

    return {
        "forecasts": np.array(forecasts),
        "actuals_r2": np.array(actuals_r2),
        "indices": dates_oos,
    }


# ---------------------------------------------------------------------------
# 5. LOSS FUNCTIONS
# ---------------------------------------------------------------------------

def qlike(actual, forecast):
    """QLIKE loss: mean(actual/forecast - log(actual/forecast) - 1).
    Lower is better. Robust loss function for variance forecasting.
    """
    ratio = actual / forecast
    # Avoid log(0)
    ratio = np.maximum(ratio, 1e-12)
    return np.mean(ratio - np.log(ratio) - 1)


def mse(actual, forecast):
    """Mean Squared Error."""
    return np.mean((actual - forecast) ** 2)


def mae(actual, forecast):
    """Mean Absolute Error."""
    return np.mean(np.abs(actual - forecast))


def r_squared_oos(actual, forecast):
    """Out-of-sample R² = 1 - MSE(forecast) / Var(actual)."""
    ss_res = np.sum((actual - forecast) ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    if ss_tot == 0:
        return np.nan
    return 1 - ss_res / ss_tot


def mincer_zarnowitz(actual, forecast):
    """Mincer-Zarnowitz regression: actual = a + b*forecast + e.
    Returns (a, b, R², p_value for H0: a=0, b=1).
    """
    n = len(actual)
    X = np.column_stack([np.ones(n), forecast])
    try:
        beta = np.linalg.lstsq(X, actual, rcond=None)[0]
        fitted = X @ beta
        ss_res = np.sum((actual - fitted) ** 2)
        ss_tot = np.sum((actual - np.mean(actual)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan

        # F-test for joint H0: a=0, b=1
        residuals = actual - fitted
        sigma2 = ss_res / (n - 2) if n > 2 else np.nan
        XtX_inv = np.linalg.inv(X.T @ X)
        se = np.sqrt(np.diag(sigma2 * XtX_inv))

        # Individual t-tests
        t_a = beta[0] / se[0] if se[0] > 0 else np.nan
        t_b = (beta[1] - 1) / se[1] if se[1] > 0 else np.nan

        return {
            "intercept": float(beta[0]),
            "slope": float(beta[1]),
            "R2": float(r2),
            "t_intercept": float(t_a),
            "t_slope_minus1": float(t_b),
        }
    except Exception:
        return {"intercept": np.nan, "slope": np.nan, "R2": np.nan}


# ---------------------------------------------------------------------------
# 6. MAIN ANALYSIS
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("K196: 5-Minute Realized Variance Pilot — Extended Analysis")
    print("=" * 70)

    # -----------------------------------------------------------------------
    # Step 1: Load data
    # -----------------------------------------------------------------------
    daily_data = load_5min_data()
    print(f"\nLoaded 5-min data for {len(daily_data)} trading days")

    dates_available = sorted(daily_data.keys())
    print(f"Date range: {dates_available[0]} to {dates_available[-1]}")

    # -----------------------------------------------------------------------
    # Step 2: Compute RV components
    # -----------------------------------------------------------------------
    rv_df = compute_daily_rv_components(daily_data)
    print(f"RV computed for {len(rv_df)} days")
    print(f"\n*** PRELIMINARY: {len(rv_df)} days — too short for definitive OOS ***")

    # -----------------------------------------------------------------------
    # Step 3: Descriptive statistics
    # -----------------------------------------------------------------------
    print("\n" + "-" * 50)
    print("A. VARIANCE DECOMPOSITION (Annualized Vol = sqrt(252 * var))")
    print("-" * 50)

    ann = np.sqrt(252)
    for var_name in ["rv", "bpv", "jv", "overnight_sq", "total_rv", "c2c_var"]:
        s = rv_df[var_name]
        vol = np.sqrt(s.mean()) * ann * 100
        print(f"  {var_name:15s}: mean={s.mean():.6f}  "
              f"ann_vol={vol:.1f}%  std={s.std():.6f}")

    # Decomposition shares
    total_mean = rv_df["total_rv"].mean()
    print(f"\n  Decomposition shares of total variance:")
    print(f"    BPV (continuous):  {rv_df['bpv'].mean() / total_mean * 100:.1f}%")
    print(f"    JV  (jumps):       {rv_df['jv'].mean() / total_mean * 100:.1f}%")
    print(f"    Overnight gap:     {rv_df['overnight_sq'].mean() / total_mean * 100:.1f}%")
    print(f"    Intraday RV:       {rv_df['rv'].mean() / total_mean * 100:.1f}%")

    # -----------------------------------------------------------------------
    # Step 4: Autocorrelation structure
    # -----------------------------------------------------------------------
    print("\n" + "-" * 50)
    print("B. AUTOCORRELATION STRUCTURE (predictability indicator)")
    print("-" * 50)

    for var_name in ["rv", "bpv", "jv", "overnight_sq", "total_rv", "c2c_var"]:
        s = rv_df[var_name].dropna()
        ac1 = s.autocorr(lag=1) if len(s) > 1 else np.nan
        ac5 = s.autocorr(lag=5) if len(s) > 5 else np.nan
        print(f"  {var_name:15s}: AC(1)={ac1:.3f}  AC(5)={ac5:.3f}")

    # -----------------------------------------------------------------------
    # Step 5: Log-RV analysis (HAR typically uses log-RV)
    # -----------------------------------------------------------------------
    print("\n" + "-" * 50)
    print("C. LOG-RV AUTOCORRELATION (more Gaussian, standard in HAR)")
    print("-" * 50)

    rv_df["log_rv"] = np.log(rv_df["rv"].clip(lower=1e-12))
    rv_df["log_bpv"] = np.log(rv_df["bpv"].clip(lower=1e-12))
    rv_df["log_total_rv"] = np.log(rv_df["total_rv"].clip(lower=1e-12))

    for var_name in ["log_rv", "log_bpv", "log_total_rv"]:
        s = rv_df[var_name].dropna()
        ac1 = s.autocorr(lag=1) if len(s) > 1 else np.nan
        ac5 = s.autocorr(lag=5) if len(s) > 5 else np.nan
        print(f"  {var_name:15s}: AC(1)={ac1:.3f}  AC(5)={ac5:.3f}")

    # -----------------------------------------------------------------------
    # Step 6: HAR-RV pseudo-OOS
    # -----------------------------------------------------------------------
    print("\n" + "-" * 50)
    print("D. HAR-RV PSEUDO-OOS FORECAST (expanding window, day >=30)")
    print("-" * 50)

    # HAR-RV on RV
    har_rv_result = har_expanding_oos(rv_df["rv"].reset_index(drop=True), first_oos=30)

    # HAR-RV on BPV
    har_bpv_result = har_expanding_oos(rv_df["bpv"].reset_index(drop=True), first_oos=30)

    # HAR-RV on log-RV (predict log, evaluate on level)
    har_log_rv_result = har_expanding_oos(rv_df["log_rv"].reset_index(drop=True), first_oos=30)

    # HAR-RV on total_rv (including overnight)
    har_total_result = har_expanding_oos(rv_df["total_rv"].reset_index(drop=True), first_oos=30)

    har_models = {
        "HAR-RV": (har_rv_result, rv_df["rv"].reset_index(drop=True)),
        "HAR-BPV": (har_bpv_result, rv_df["bpv"].reset_index(drop=True)),
        "HAR-logRV": (har_log_rv_result, rv_df["log_rv"].reset_index(drop=True)),
        "HAR-TotalRV": (har_total_result, rv_df["total_rv"].reset_index(drop=True)),
    }

    har_scores = {}

    for name, (result, target_series) in har_models.items():
        if result is None:
            print(f"  {name}: insufficient data")
            continue

        forecasts = result["forecasts"]
        actuals = result["actuals"]
        n_oos = len(forecasts)

        # Filter out floored forecasts (1e-10) caused by undertrained OLS
        # These indicate OLS produced negative forecasts — not meaningful
        valid_mask = forecasts > 1e-8  # anything above floor
        n_floored = int(np.sum(~valid_mask))

        if name == "HAR-logRV":
            # Convert log forecasts back to level for QLIKE
            forecasts_level = np.exp(forecasts)
            actuals_level = np.exp(actuals)
            ql = qlike(actuals_level[valid_mask], forecasts_level[valid_mask]) if valid_mask.sum() > 2 else np.nan
            r2_oos = r_squared_oos(actuals[valid_mask], forecasts[valid_mask]) if valid_mask.sum() > 2 else np.nan
            mz = mincer_zarnowitz(actuals[valid_mask], forecasts[valid_mask]) if valid_mask.sum() > 2 else {"intercept": np.nan, "slope": np.nan, "R2": np.nan}
            print(f"\n  {name} (n_oos={n_oos}, floored={n_floored}):")
            print(f"    QLIKE (level):     {ql:.6f}" if not np.isnan(ql) else "    QLIKE (level):     N/A")
            print(f"    R²_OOS (log):      {r2_oos:.4f}" if not np.isnan(r2_oos) else "    R²_OOS (log):      N/A")
            print(f"    MZ: a={mz['intercept']:.4f}, b={mz['slope']:.4f}, R²={mz['R2']:.4f}")
            har_scores[name] = {"QLIKE": float(ql) if not np.isnan(ql) else None,
                                "R2_OOS": float(r2_oos) if not np.isnan(r2_oos) else None,
                                "MZ_R2": float(mz["R2"]), "n_oos": n_oos,
                                "n_floored": n_floored}
        else:
            fc_valid = forecasts[valid_mask]
            ac_valid = actuals[valid_mask]
            if len(fc_valid) < 3:
                print(f"\n  {name} (n_oos={n_oos}, floored={n_floored}): too few valid forecasts")
                continue
            ql = qlike(ac_valid, fc_valid)
            m = mse(ac_valid, fc_valid)
            r2_oos = r_squared_oos(ac_valid, fc_valid)
            mz = mincer_zarnowitz(ac_valid, fc_valid)
            print(f"\n  {name} (n_oos={n_oos}, valid={len(fc_valid)}, floored={n_floored}):")
            print(f"    QLIKE:    {ql:.6f}")
            print(f"    MSE:      {m:.10f}")
            print(f"    R²_OOS:   {r2_oos:.4f}")
            print(f"    MZ: a={mz['intercept']:.6f}, b={mz['slope']:.4f}, R²={mz['R2']:.4f}")
            har_scores[name] = {"QLIKE": float(ql), "MSE": float(m),
                                "R2_OOS": float(r2_oos), "MZ_R2": float(mz["R2"]),
                                "n_oos": n_oos, "n_valid": len(fc_valid),
                                "n_floored": n_floored}

    # -----------------------------------------------------------------------
    # Step 7: GJR-GARCH pseudo-OOS
    # -----------------------------------------------------------------------
    print("\n" + "-" * 50)
    print("E. GJR-GARCH PSEUDO-OOS FORECAST (close-to-close returns)")
    print("-" * 50)

    # Use full returns (including overnight) for GARCH
    returns = rv_df["full_return"].dropna().values

    garch_result = gjr_garch_expanding_oos(returns, first_oos=30)

    garch_scores = {}
    if garch_result is not None:
        gf = garch_result["forecasts"]
        ga_r2 = garch_result["actuals_r2"]
        n_garch = len(gf)

        # GARCH forecasts σ² for full returns. Compare to:
        # (a) r² as target (traditional)
        # (b) RV as target (improved)
        # (c) total_rv as target (RV + overnight)

        # Get aligned RV values for GARCH OOS dates
        garch_indices = garch_result["indices"]
        rv_aligned = rv_df["rv"].iloc[garch_indices].values
        total_rv_aligned = rv_df["total_rv"].iloc[garch_indices].values

        # (a) GARCH vs r² (traditional evaluation)
        ql_r2 = qlike(ga_r2, gf)
        r2_oos_r2 = r_squared_oos(ga_r2, gf)
        mz_r2 = mincer_zarnowitz(ga_r2, gf)

        print(f"\n  GJR-GARCH vs r² target (n_oos={n_garch}):")
        print(f"    QLIKE:    {ql_r2:.6f}")
        print(f"    R²_OOS:   {r2_oos_r2:.4f}")
        print(f"    MZ: a={mz_r2['intercept']:.6f}, b={mz_r2['slope']:.4f}, R²={mz_r2['R2']:.4f}")

        garch_scores["GJR-GARCH_vs_r2"] = {"QLIKE": float(ql_r2),
                                             "R2_OOS": float(r2_oos_r2),
                                             "MZ_R2": float(mz_r2["R2"]),
                                             "n_oos": n_garch}

        # (b) GARCH vs RV target (intraday only)
        ql_rv = qlike(rv_aligned, gf)
        r2_oos_rv = r_squared_oos(rv_aligned, gf)
        mz_rv = mincer_zarnowitz(rv_aligned, gf)

        print(f"\n  GJR-GARCH vs RV target (n_oos={n_garch}):")
        print(f"    QLIKE:    {ql_rv:.6f}")
        print(f"    R²_OOS:   {r2_oos_rv:.4f}")
        print(f"    MZ: a={mz_rv['intercept']:.6f}, b={mz_rv['slope']:.4f}, R²={mz_rv['R2']:.4f}")

        garch_scores["GJR-GARCH_vs_RV"] = {"QLIKE": float(ql_rv),
                                             "R2_OOS": float(r2_oos_rv),
                                             "MZ_R2": float(mz_rv["R2"]),
                                             "n_oos": n_garch}

        # (c) GARCH vs total_rv target (intraday + overnight)
        ql_trv = qlike(total_rv_aligned, gf)
        r2_oos_trv = r_squared_oos(total_rv_aligned, gf)
        mz_trv = mincer_zarnowitz(total_rv_aligned, gf)

        print(f"\n  GJR-GARCH vs Total RV target (n_oos={n_garch}):")
        print(f"    QLIKE:    {ql_trv:.6f}")
        print(f"    R²_OOS:   {r2_oos_trv:.4f}")
        print(f"    MZ: a={mz_trv['intercept']:.6f}, b={mz_trv['slope']:.4f}, R²={mz_trv['R2']:.4f}")

        garch_scores["GJR-GARCH_vs_TotalRV"] = {"QLIKE": float(ql_trv),
                                                  "R2_OOS": float(r2_oos_trv),
                                                  "MZ_R2": float(mz_trv["R2"]),
                                                  "n_oos": n_garch}
    else:
        print("  GJR-GARCH: estimation failed")

    # -----------------------------------------------------------------------
    # Step 8: Head-to-head comparison with RV as target
    # -----------------------------------------------------------------------
    print("\n" + "-" * 50)
    print("F. HEAD-TO-HEAD: HAR-RV vs GJR-GARCH (RV as target)")
    print("-" * 50)

    # Align forecasts to same OOS dates
    if har_rv_result is not None and garch_result is not None:
        har_indices = set(har_rv_result["indices"])
        garch_indices_set = set(garch_result["indices"])
        common_indices = sorted(har_indices & garch_indices_set)

        if len(common_indices) > 3:
            # Get aligned data
            har_idx_map = {idx: i for i, idx in enumerate(har_rv_result["indices"])}
            garch_idx_map = {idx: i for i, idx in enumerate(garch_result["indices"])}

            har_fc = np.array([har_rv_result["forecasts"][har_idx_map[i]] for i in common_indices])
            garch_fc = np.array([garch_result["forecasts"][garch_idx_map[i]] for i in common_indices])
            rv_target = rv_df["rv"].iloc[common_indices].values

            # Filter out floored HAR forecasts for fair comparison
            valid_h2h = har_fc > 1e-8
            har_fc = har_fc[valid_h2h]
            garch_fc = garch_fc[valid_h2h]
            rv_target = rv_target[valid_h2h]
            n_dropped = int(np.sum(~valid_h2h))
            if n_dropped > 0:
                print(f"  (Dropped {n_dropped} floored HAR forecast(s) for fair comparison)")

            ql_har = qlike(rv_target, har_fc)
            ql_garch = qlike(rv_target, garch_fc)

            r2_har = r_squared_oos(rv_target, har_fc)
            r2_garch = r_squared_oos(rv_target, garch_fc)

            mae_har = mae(rv_target, har_fc)
            mae_garch = mae(rv_target, garch_fc)

            print(f"\n  Common OOS days: {len(common_indices)}")
            print(f"  {'Metric':<20s} {'HAR-RV':>12s} {'GJR-GARCH':>12s} {'Winner':>10s}")
            print(f"  {'-'*54}")

            ql_winner = "HAR-RV" if ql_har < ql_garch else "GJR-GARCH"
            r2_winner = "HAR-RV" if r2_har > r2_garch else "GJR-GARCH"
            mae_winner = "HAR-RV" if mae_har < mae_garch else "GJR-GARCH"

            print(f"  {'QLIKE':<20s} {ql_har:>12.6f} {ql_garch:>12.6f} {ql_winner:>10s}")
            print(f"  {'R²_OOS':<20s} {r2_har:>12.4f} {r2_garch:>12.4f} {r2_winner:>10s}")
            print(f"  {'MAE':<20s} {mae_har:>12.8f} {mae_garch:>12.8f} {mae_winner:>10s}")

            # Diebold-Mariano test (QLIKE differentials)
            d_ql = (rv_target / har_fc - np.log(rv_target / har_fc) - 1) - \
                   (rv_target / garch_fc - np.log(rv_target / garch_fc) - 1)
            dm_stat = np.mean(d_ql) / (np.std(d_ql) / np.sqrt(len(d_ql))) if np.std(d_ql) > 0 else 0
            dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
            print(f"\n  Diebold-Mariano test (QLIKE): stat={dm_stat:.3f}, p={dm_pval:.4f}")
            if dm_pval < 0.10:
                dm_winner = "HAR-RV" if dm_stat < 0 else "GJR-GARCH"
                print(f"    → Significantly better: {dm_winner} (p < 0.10)")
            else:
                print(f"    → No significant difference (p = {dm_pval:.4f})")

            head_to_head = {
                "common_oos_days": len(common_indices),
                "QLIKE_HAR": float(ql_har),
                "QLIKE_GARCH": float(ql_garch),
                "R2_OOS_HAR": float(r2_har),
                "R2_OOS_GARCH": float(r2_garch),
                "MAE_HAR": float(mae_har),
                "MAE_GARCH": float(mae_garch),
                "DM_stat": float(dm_stat),
                "DM_pval": float(dm_pval),
            }
        else:
            print("  Not enough common OOS days for comparison")
            head_to_head = None
    else:
        print("  One or both models failed — cannot compare")
        head_to_head = None

    # -----------------------------------------------------------------------
    # Step 9: BPV predictability advantage
    # -----------------------------------------------------------------------
    print("\n" + "-" * 50)
    print("G. BPV vs RV PREDICTABILITY (K156 confirmation)")
    print("-" * 50)

    if har_bpv_result is not None and har_rv_result is not None:
        # Align to common dates
        bpv_indices = set(har_bpv_result["indices"])
        rv_indices = set(har_rv_result["indices"])
        common_bpv_rv = sorted(bpv_indices & rv_indices)

        if len(common_bpv_rv) > 3:
            bpv_idx_map = {idx: i for i, idx in enumerate(har_bpv_result["indices"])}
            rv_idx_map = {idx: i for i, idx in enumerate(har_rv_result["indices"])}

            bpv_fc = np.array([har_bpv_result["forecasts"][bpv_idx_map[i]] for i in common_bpv_rv])
            rv_fc = np.array([har_rv_result["forecasts"][rv_idx_map[i]] for i in common_bpv_rv])
            bpv_actual = rv_df["bpv"].iloc[common_bpv_rv].values
            rv_actual = rv_df["rv"].iloc[common_bpv_rv].values

            # Filter out floored forecasts from both
            valid_bpv = bpv_fc > 1e-8
            valid_rv = rv_fc > 1e-8
            valid_both = valid_bpv & valid_rv

            bpv_fc = bpv_fc[valid_both]
            rv_fc = rv_fc[valid_both]
            bpv_actual = bpv_actual[valid_both]
            rv_actual = rv_actual[valid_both]

            r2_bpv = r_squared_oos(bpv_actual, bpv_fc)
            r2_rv = r_squared_oos(rv_actual, rv_fc)

            ql_bpv = qlike(bpv_actual, bpv_fc)
            ql_rv = qlike(rv_actual, rv_fc)

            print(f"  HAR-BPV: R²_OOS={r2_bpv:.4f}, QLIKE={ql_bpv:.6f}")
            print(f"  HAR-RV:  R²_OOS={r2_rv:.4f}, QLIKE={ql_rv:.6f}")
            print(f"  BPV more predictable: R² {'YES' if r2_bpv > r2_rv else 'NO'}, "
                  f"QLIKE {'YES' if ql_bpv < ql_rv else 'NO'}")

            bpv_comparison = {
                "R2_OOS_BPV": float(r2_bpv),
                "R2_OOS_RV": float(r2_rv),
                "QLIKE_BPV": float(ql_bpv),
                "QLIKE_RV": float(ql_rv),
                "BPV_more_predictable_R2": bool(r2_bpv > r2_rv),
                "BPV_more_predictable_QLIKE": bool(ql_bpv < ql_rv),
            }
        else:
            bpv_comparison = None
            print("  Insufficient common OOS days")
    else:
        bpv_comparison = None
        print("  Insufficient data for comparison")

    # -----------------------------------------------------------------------
    # Step 10: Correlation between RV and c2c r²
    # -----------------------------------------------------------------------
    print("\n" + "-" * 50)
    print("H. RV vs CLOSE-TO-CLOSE r² CORRELATION")
    print("-" * 50)

    corr_rv_c2c = rv_df["rv"].corr(rv_df["c2c_var"])
    corr_rv_fullvar = rv_df["rv"].corr(rv_df["full_var"])
    corr_totalrv_fullvar = rv_df["total_rv"].corr(rv_df["full_var"])
    corr_bpv_rv = rv_df["bpv"].corr(rv_df["rv"])

    print(f"  corr(RV_5min, c2c_var):       {corr_rv_c2c:.4f}")
    print(f"  corr(RV_5min, full_var):       {corr_rv_fullvar:.4f}")
    print(f"  corr(total_rv, full_var):      {corr_totalrv_fullvar:.4f}")
    print(f"  corr(BPV, RV):                 {corr_bpv_rv:.4f}")

    # Ratio of RV information
    rv_mean = rv_df["rv"].mean()
    c2c_mean = rv_df["c2c_var"].mean()
    full_mean = rv_df["full_var"].mean()
    total_mean2 = rv_df["total_rv"].mean()

    print(f"\n  Mean RV_5min:     {rv_mean:.6f}")
    print(f"  Mean c2c_var:     {c2c_mean:.6f}")
    print(f"  Mean full_var:    {full_mean:.6f}")
    print(f"  Mean total_rv:    {total_mean2:.6f}")
    print(f"  RV/c2c ratio:     {rv_mean / c2c_mean:.2f}x")
    print(f"    → RV from 5-min captures {rv_mean / c2c_mean:.1f}x more variance than c2c r²")

    rv_c2c_analysis = {
        "corr_rv_c2c": float(corr_rv_c2c),
        "corr_rv_fullvar": float(corr_rv_fullvar),
        "corr_totalrv_fullvar": float(corr_totalrv_fullvar),
        "corr_bpv_rv": float(corr_bpv_rv),
        "mean_rv": float(rv_mean),
        "mean_c2c_var": float(c2c_mean),
        "rv_to_c2c_ratio": float(rv_mean / c2c_mean),
    }

    # -----------------------------------------------------------------------
    # Step 11: Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print(f"\nData: {len(rv_df)} trading days ({rv_df['date'].iloc[0]} to {rv_df['date'].iloc[-1]})")
    print(f"OOS period: ~{len(rv_df) - 30} days (expanding window from day 30)")
    print(f"\n*** STATUS: PRELIMINARY (47 days << 250 days needed for proper OOS) ***")

    print(f"\nKey findings (provisional):")

    if head_to_head:
        qlike_pct = (head_to_head["QLIKE_GARCH"] - head_to_head["QLIKE_HAR"]) / head_to_head["QLIKE_GARCH"] * 100
        print(f"  1. HAR-RV vs GJR-GARCH (QLIKE, RV target): "
              f"{'HAR-RV wins' if head_to_head['QLIKE_HAR'] < head_to_head['QLIKE_GARCH'] else 'GARCH wins'} "
              f"by {abs(qlike_pct):.1f}%")
        print(f"     DM test p-value: {head_to_head['DM_pval']:.4f}")

    if bpv_comparison:
        print(f"  2. BPV more predictable than RV: "
              f"R² {'confirmed' if bpv_comparison['BPV_more_predictable_R2'] else 'NOT confirmed'}, "
              f"QLIKE {'confirmed' if bpv_comparison['BPV_more_predictable_QLIKE'] else 'NOT confirmed'}")

    print(f"  3. RV captures {rv_mean / c2c_mean:.1f}x more variance than c2c r²")
    print(f"  4. corr(RV, c2c_var) = {corr_rv_c2c:.3f}")

    # -----------------------------------------------------------------------
    # Save results
    # -----------------------------------------------------------------------
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    results = {
        "experiment": "K196",
        "title": "5-Minute Realized Variance Pilot — Extended Analysis",
        "status": "PRELIMINARY",
        "data_days": len(rv_df),
        "oos_days": len(rv_df) - 30,
        "date_range": f"{rv_df['date'].iloc[0]} to {rv_df['date'].iloc[-1]}",
        "timestamp": datetime.now().isoformat(),
        "decomposition": {
            "bpv_share_pct": float(rv_df["bpv"].mean() / total_mean * 100),
            "jv_share_pct": float(rv_df["jv"].mean() / total_mean * 100),
            "overnight_share_pct": float(rv_df["overnight_sq"].mean() / total_mean * 100),
            "intraday_share_pct": float(rv_df["rv"].mean() / total_mean * 100),
        },
        "autocorrelation": {
            var: {"AC1": float(rv_df[var].autocorr(1)),
                  "AC5": float(rv_df[var].autocorr(5))}
            for var in ["rv", "bpv", "jv", "overnight_sq", "total_rv"]
        },
        "har_scores": har_scores,
        "garch_scores": garch_scores,
        "head_to_head": head_to_head,
        "bpv_comparison": bpv_comparison,
        "rv_c2c_analysis": rv_c2c_analysis,
    }

    results_path = STORAGE_DIR / "k196_5min_rv_pilot.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {results_path}")

    return results


if __name__ == "__main__":
    results = main()
