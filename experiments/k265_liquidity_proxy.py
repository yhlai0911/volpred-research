"""
K265: Liquidity Premium — Can Bid-Ask Spread Proxies Predict Vol?
=================================================================

Hypothesis:
  Liquidity (ease of trading) is a fundamental driver of volatility — illiquid
  markets are more volatile. K154 found order flow imbalance has marginal signal
  beyond VIX. Can we capture the liquidity → vol link using daily OHLCV data
  (no tick data needed)?

Liquidity Proxy Features (all from daily OHLCV):
  1. Amihud illiquidity: |return| / dollar_volume (rolling 22d mean)
     - Amihud (2002) "Illiquidity and stock returns"
  2. Roll spread: 2 * sqrt(-cov(r_t, r_{t-1})) (Roll 1984)
     - Implicit spread from serial covariance of returns
  3. High-low spread: Corwin-Schultz (2012) estimator from daily High/Low
     - Exploits the fact that daily high/low ratio reflects both vol and spread
  4. Volume turnover: volume / 20d_avg_volume (relative volume)
  5. Price impact: |return| / sqrt(volume) (Kyle's lambda proxy)

Method:
  1. For each feature × asset:
     - Partial correlation with future 22d RV, controlling for VIX
     - Harvey (2016) threshold: |t| > 3.0 for significance
  2. Best features → GARCH-X (external regressor)
  3. Granger causality: does liquidity deterioration LEAD vol spikes?
  4. OOS evaluation: 2023-01-01 ~ 2024-12-31

Data:
  - SPY, QQQ, GLD, TLT from yfinance (2005-2024)
  - VIX (^VIX) as control variable
  - All real data, no simulations

Literature:
  - Amihud (2002) "Illiquidity and stock returns"
  - Roll (1984) "A simple implicit measure of the effective bid-ask spread"
  - Corwin & Schultz (2012) "A simple way to estimate bid-ask spreads"
  - Kyle (1985) "Continuous auctions and insider trading"

[提出: 用戶 (K154 extension + microstructure direction), 執行: Claude]
"""

import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ============================================================
# CONFIG
# ============================================================
DATA_START = "2005-01-01"
DATA_END = "2026-12-31"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
WINDOW = 2000
ASSETS = ["SPY", "QQQ", "GLD", "TLT"]
VIX_TICKER = "^VIX"
RV_WINDOW = 22  # 22-day realized volatility
ROLL_WINDOW = 22  # Rolling window for liquidity proxies
HARVEY_THRESHOLD = 3.0


def download_data():
    """Download OHLCV data for all assets + VIX."""
    print("=" * 70)
    print("K265: Liquidity Premium — Bid-Ask Spread Proxies for Vol Prediction")
    print("=" * 70)
    print(f"\nDownloading data: {ASSETS} + VIX, {DATA_START} to {DATA_END}")

    all_tickers = ASSETS + [VIX_TICKER]
    data = {}
    for ticker in all_tickers:
        df = yf.download(ticker, start=DATA_START, end=DATA_END, auto_adjust=True, progress=False)
        if df.empty:
            print(f"  WARNING: No data for {ticker}")
            continue
        # Flatten multi-level columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[ticker] = df
        print(f"  {ticker}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

    return data


def compute_liquidity_features(df, asset_name):
    """
    Compute 5 liquidity proxy features from OHLCV data.

    Returns DataFrame with columns: amihud, roll_spread, cs_spread, rel_volume, price_impact
    """
    close = df["Close"].values.flatten()
    high = df["High"].values.flatten()
    low = df["Low"].values.flatten()
    volume = df["Volume"].values.flatten().astype(float)
    idx = df.index

    ret = np.full(len(close), np.nan)
    ret[1:] = np.diff(np.log(close))

    dollar_volume = close * volume

    # 1. Amihud Illiquidity: |return| / dollar_volume, rolling 22d mean
    amihud_raw = np.abs(ret) / np.where(dollar_volume > 0, dollar_volume, np.nan)
    amihud = pd.Series(amihud_raw, index=idx).rolling(ROLL_WINDOW, min_periods=15).mean()
    # Scale to make interpretable (multiply by 1e10 for SPY-scale)
    amihud = amihud * 1e10

    # 2. Roll Spread: 2 * sqrt(-cov(r_t, r_{t-1}))
    # If cov > 0 (positive autocorrelation), set to 0 (no spread signal)
    ret_series = pd.Series(ret, index=idx)
    ret_lag = ret_series.shift(1)

    def roll_spread_func(window_data):
        r = window_data.values
        r_lag = ret_lag.reindex(window_data.index).values
        mask = ~(np.isnan(r) | np.isnan(r_lag))
        if mask.sum() < 10:
            return np.nan
        cov_val = np.cov(r[mask], r_lag[mask])[0, 1]
        if cov_val >= 0:
            return 0.0  # No negative autocorrelation → no spread signal
        return 2.0 * np.sqrt(-cov_val)

    roll_spread = ret_series.rolling(ROLL_WINDOW, min_periods=15).apply(
        roll_spread_func, raw=False
    )

    # 3. Corwin-Schultz High-Low Spread Estimator
    # S = (2*(exp(alpha) - 1)) / (1 + exp(alpha))
    # alpha = (sqrt(2*beta) - sqrt(beta)) / (3 - 2*sqrt(2)) - sqrt(gamma/(3 - 2*sqrt(2)))
    # beta = sum of (log(H_i/L_i))^2 for 2 consecutive days
    # gamma = (log(max(H_t,H_{t-1})/min(L_t,L_{t-1})))^2
    log_hl = np.log(np.where(low > 0, high / low, np.nan))
    log_hl_sq = log_hl ** 2

    cs_spread_arr = np.full(len(close), np.nan)
    for t in range(1, len(close)):
        if np.isnan(log_hl[t]) or np.isnan(log_hl[t - 1]):
            continue
        beta = log_hl_sq[t] + log_hl_sq[t - 1]
        h2 = max(high[t], high[t - 1])
        l2 = min(low[t], low[t - 1])
        if l2 <= 0 or h2 <= 0:
            continue
        gamma = (np.log(h2 / l2)) ** 2
        sqrt2 = np.sqrt(2)
        denom = 3 - 2 * sqrt2
        if denom == 0:
            continue
        alpha_val = (np.sqrt(2 * beta) - np.sqrt(beta)) / denom - np.sqrt(gamma / denom)
        if alpha_val > 0:
            spread = 2 * (np.exp(alpha_val) - 1) / (1 + np.exp(alpha_val))
        else:
            spread = 0.0
        cs_spread_arr[t] = spread

    cs_spread = pd.Series(cs_spread_arr, index=idx).rolling(ROLL_WINDOW, min_periods=15).mean()

    # 4. Relative Volume (volume / 20d average volume)
    avg_vol = pd.Series(volume, index=idx).rolling(20, min_periods=10).mean()
    rel_volume = pd.Series(volume, index=idx) / avg_vol

    # 5. Price Impact: |return| / sqrt(volume) (Kyle's lambda proxy)
    price_impact_raw = np.abs(ret) / np.sqrt(np.where(volume > 0, volume, np.nan))
    price_impact = pd.Series(price_impact_raw, index=idx).rolling(ROLL_WINDOW, min_periods=15).mean()
    # Scale
    price_impact = price_impact * 1e4

    features = pd.DataFrame(
        {
            "amihud": amihud,
            "roll_spread": roll_spread,
            "cs_spread": cs_spread,
            "rel_volume": rel_volume,
            "price_impact": price_impact,
        },
        index=idx,
    )

    print(f"\n  {asset_name} liquidity features computed:")
    for col in features.columns:
        valid = features[col].dropna()
        print(f"    {col}: mean={valid.mean():.6f}, std={valid.std():.6f}, obs={len(valid)}")

    return features


def compute_realized_vol(df, window=22):
    """Compute forward-looking 22d realized volatility (annualized)."""
    close = df["Close"].values.flatten()
    ret = np.full(len(close), np.nan)
    ret[1:] = np.diff(np.log(close))
    ret_series = pd.Series(ret, index=df.index)

    # Forward-looking RV: sum of squared returns over next 22 days
    rv = ret_series.pow(2).rolling(window, min_periods=window).sum().shift(-window)
    rv_ann = np.sqrt(rv * 252)  # Annualized
    return rv


def partial_correlation_analysis(features_df, rv_series, vix_series, asset_name):
    """
    Compute partial correlation of each liquidity feature with future RV,
    controlling for VIX level.

    Returns dict of {feature: {partial_r, t_stat, p_value, n_obs}}
    """
    print(f"\n--- Partial Correlation Analysis: {asset_name} ---")
    print(f"{'Feature':<15} {'Partial r':>10} {'t-stat':>10} {'p-value':>10} {'N':>8} {'Harvey?':>8}")
    print("-" * 65)

    results = {}
    for feat_name in features_df.columns:
        # Align all series
        combined = pd.DataFrame(
            {
                "feat": features_df[feat_name],
                "rv": rv_series,
                "vix": vix_series,
            }
        ).dropna()

        if len(combined) < 100:
            print(f"  {feat_name}: insufficient data ({len(combined)} obs)")
            continue

        x = combined["feat"].values
        y = combined["rv"].values
        z = combined["vix"].values

        # Partial correlation: regress x on z, regress y on z, correlate residuals
        # x_resid = x - z * (z'z)^-1 * z'x
        z_mat = np.column_stack([np.ones(len(z)), z])
        beta_x = np.linalg.lstsq(z_mat, x, rcond=None)[0]
        beta_y = np.linalg.lstsq(z_mat, y, rcond=None)[0]
        x_resid = x - z_mat @ beta_x
        y_resid = y - z_mat @ beta_y

        n = len(x_resid)
        partial_r = np.corrcoef(x_resid, y_resid)[0, 1]

        # t-test for partial correlation
        t_stat = partial_r * np.sqrt((n - 3) / (1 - partial_r**2))
        p_val = 2 * (1 - stats.t.cdf(np.abs(t_stat), df=n - 3))

        passes_harvey = "YES" if np.abs(t_stat) > HARVEY_THRESHOLD else "no"
        print(
            f"  {feat_name:<15} {partial_r:>10.4f} {t_stat:>10.2f} {p_val:>10.4f} {n:>8d} {passes_harvey:>8}"
        )

        results[feat_name] = {
            "partial_r": float(partial_r),
            "t_stat": float(t_stat),
            "p_value": float(p_val),
            "n_obs": int(n),
            "passes_harvey": bool(np.abs(t_stat) > HARVEY_THRESHOLD),
        }

    return results


def granger_causality_test(features_df, rv_series, asset_name, max_lag=5):
    """
    Test if liquidity features Granger-cause future realized volatility.

    Uses F-test: Unrestricted model includes lagged features, restricted does not.
    """
    print(f"\n--- Granger Causality Test: {asset_name} (max_lag={max_lag}) ---")
    print(f"{'Feature':<15} {'Best Lag':>8} {'F-stat':>10} {'p-value':>10} {'Direction':>12}")
    print("-" * 60)

    results = {}
    for feat_name in features_df.columns:
        combined = pd.DataFrame(
            {"feat": features_df[feat_name], "rv": rv_series}
        ).dropna()

        if len(combined) < 200:
            continue

        rv_vals = combined["rv"].values
        feat_vals = combined["feat"].values

        best_f = 0
        best_p = 1
        best_lag = 1

        for lag in range(1, max_lag + 1):
            n = len(rv_vals) - lag
            if n < 50:
                continue

            # Restricted model: RV_t = a + b1*RV_{t-1} + ... + bL*RV_{t-L}
            Y = rv_vals[lag:]
            X_restricted = np.column_stack(
                [np.ones(n)] + [rv_vals[lag - j - 1 : -j - 1 if j + 1 < lag else n + lag - j - 1] for j in range(lag)]
            )

            # Fix: build lagged arrays properly
            Y = rv_vals[lag:]
            n = len(Y)
            X_r_cols = [np.ones(n)]
            for j in range(1, lag + 1):
                X_r_cols.append(rv_vals[lag - j : lag - j + n])
            X_restricted = np.column_stack(X_r_cols)

            # Unrestricted: add lagged features
            X_u_cols = list(X_r_cols)
            for j in range(1, lag + 1):
                X_u_cols.append(feat_vals[lag - j : lag - j + n])
            X_unrestricted = np.column_stack(X_u_cols)

            try:
                beta_r = np.linalg.lstsq(X_restricted, Y, rcond=None)[0]
                beta_u = np.linalg.lstsq(X_unrestricted, Y, rcond=None)[0]

                rss_r = np.sum((Y - X_restricted @ beta_r) ** 2)
                rss_u = np.sum((Y - X_unrestricted @ beta_u) ** 2)

                k_r = X_restricted.shape[1]
                k_u = X_unrestricted.shape[1]
                df1 = k_u - k_r
                df2 = n - k_u

                if df2 <= 0 or df1 <= 0 or rss_u <= 0:
                    continue

                f_stat = ((rss_r - rss_u) / df1) / (rss_u / df2)
                p_val = 1 - stats.f.cdf(f_stat, df1, df2)

                if f_stat > best_f:
                    best_f = f_stat
                    best_p = p_val
                    best_lag = lag
            except Exception:
                continue

        direction = "LEADS" if best_p < 0.05 else "no"
        print(
            f"  {feat_name:<15} {best_lag:>8d} {best_f:>10.2f} {best_p:>10.4f} {direction:>12}"
        )

        results[feat_name] = {
            "best_lag": int(best_lag),
            "f_stat": float(best_f),
            "p_value": float(best_p),
            "granger_causes": bool(best_p < 0.05),
        }

    return results


def garch_x_evaluation(df, features_df, vix_series, asset_name):
    """
    Compare GARCH + Liquidity Adjustment vs plain GJR-GARCH.

    Two-step approach (since arch library's x= is mean-equation only):
    1. GJR-GARCH → 1-step conditional variance σ²_GARCH
    2. Rolling regression: RV_22d = a + b*σ²_GARCH_22d + c*liq_feature
       vs restricted: RV_22d = a + b*σ²_GARCH_22d

    OOS evaluation with QLIKE.
    """
    print(f"\n--- GARCH + Liquidity Adjustment Evaluation: {asset_name} ---")

    close = df["Close"].values.flatten()
    ret_pct = np.full(len(close), np.nan)
    ret_pct[1:] = 100.0 * np.diff(np.log(close))
    ret_series = pd.Series(ret_pct, index=df.index)

    # Forward 22d RV for evaluation
    ret_raw = ret_series / 100.0
    rv_22d = ret_raw.pow(2).rolling(22, min_periods=22).sum().shift(-22)

    # OOS period
    oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)
    oos_dates = df.index[oos_mask]

    if len(oos_dates) < 100:
        print(f"  Insufficient OOS data for {asset_name}")
        return None

    print(f"  OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()} ({len(oos_dates)} days)")

    # Step 1: Full-sample GJR-GARCH to get conditional variance series
    print("  Step 1: Fitting full-sample GJR-GARCH for conditional variance...")
    full_ret = ret_series.dropna()
    try:
        model_full = arch_model(full_ret, vol="GARCH", p=1, o=1, q=1, dist="t")
        res_full = model_full.fit(disp="off", show_warning=False)
        cond_var = res_full.conditional_volatility ** 2 / 1e4  # daily variance in decimal
        cond_var_22d = cond_var.rolling(22, min_periods=22).mean() * 22  # 22d variance
    except Exception as e:
        print(f"  GARCH fit failed: {e}")
        return None

    # Find best liquidity feature
    best_features = []
    for feat_name in features_df.columns:
        combined = pd.DataFrame(
            {"feat": features_df[feat_name], "rv": rv_22d, "vix": vix_series}
        ).dropna()
        if len(combined) < 500:
            continue
        z_mat = np.column_stack([np.ones(len(combined)), combined["vix"].values])
        x = combined["feat"].values
        y = combined["rv"].values
        try:
            beta_x = np.linalg.lstsq(z_mat, x, rcond=None)[0]
            beta_y = np.linalg.lstsq(z_mat, y, rcond=None)[0]
            x_r = x - z_mat @ beta_x
            y_r = y - z_mat @ beta_y
            pr = np.abs(np.corrcoef(x_r, y_r)[0, 1])
            best_features.append((feat_name, pr))
        except Exception:
            continue

    best_features.sort(key=lambda x: -x[1])
    # Use top 3 features individually
    top_features = [f[0] for f in best_features[:3]]
    print(f"  Top features: {[(f[0], f'{f[1]:.4f}') for f in best_features[:3]]}")

    # Step 2: Rolling OOS regression
    print("  Step 2: Rolling OOS regression with liquidity adjustment...")

    all_results = {}
    for top_feature in top_features:
        oos_results = {"baseline_qlike": [], "enhanced_qlike": [], "dates": [], "rv_actual": []}

        reg_window = 500  # Regression training window
        step = 5

        for oos_idx in range(0, len(oos_dates), step):
            date = oos_dates[oos_idx]
            loc = df.index.get_loc(date)

            if loc < reg_window + 22:
                continue

            # Get training data for regression
            train_slice = slice(loc - reg_window, loc)

            garch_var_train = cond_var_22d.iloc[train_slice] if loc - reg_window < len(cond_var_22d) else None
            rv_train = rv_22d.iloc[train_slice]
            feat_train = features_df[top_feature].iloc[train_slice]

            combined_train = pd.DataFrame({
                "garch_var": garch_var_train,
                "rv": rv_train,
                "feat": feat_train,
            }).dropna()

            if len(combined_train) < 100:
                continue

            # Actual future RV at forecast point
            rv_actual = rv_22d.iloc[loc] if loc < len(rv_22d) else np.nan
            if np.isnan(rv_actual) or rv_actual <= 0:
                continue

            # Current GARCH variance and feature value
            garch_now = cond_var_22d.iloc[loc] if loc < len(cond_var_22d) else np.nan
            feat_now = features_df[top_feature].iloc[loc] if loc < len(features_df) else np.nan
            if np.isnan(garch_now) or np.isnan(feat_now):
                continue

            Y = combined_train["rv"].values
            X_base = np.column_stack([np.ones(len(Y)), combined_train["garch_var"].values])
            X_enhanced = np.column_stack([X_base, combined_train["feat"].values])

            try:
                # Baseline: RV = a + b * GARCH_var
                beta_base = np.linalg.lstsq(X_base, Y, rcond=None)[0]
                forecast_base = beta_base[0] + beta_base[1] * garch_now
                forecast_base = max(forecast_base, 1e-8)  # Floor

                # Enhanced: RV = a + b * GARCH_var + c * liq_feature
                beta_enh = np.linalg.lstsq(X_enhanced, Y, rcond=None)[0]
                forecast_enh = beta_enh[0] + beta_enh[1] * garch_now + beta_enh[2] * feat_now
                forecast_enh = max(forecast_enh, 1e-8)  # Floor

                oos_results["dates"].append(str(date.date()))
                oos_results["rv_actual"].append(float(rv_actual))
                oos_results["baseline_qlike"].append(float(np.log(forecast_base) + rv_actual / forecast_base))
                oos_results["enhanced_qlike"].append(float(np.log(forecast_enh) + rv_actual / forecast_enh))
            except Exception:
                continue

        if len(oos_results["dates"]) < 20:
            continue

        baseline_ql = np.array(oos_results["baseline_qlike"])
        enhanced_ql = np.array(oos_results["enhanced_qlike"])

        mean_base = np.mean(baseline_ql)
        mean_enh = np.mean(enhanced_ql)
        diff = enhanced_ql - baseline_ql

        # DM test (negative DM = enhanced better)
        n = len(diff)
        std_diff = np.std(diff, ddof=1)
        if std_diff > 0:
            dm_stat = np.mean(diff) / (std_diff / np.sqrt(n))
            dm_p = 2 * (1 - stats.t.cdf(np.abs(dm_stat), df=n - 1))
        else:
            dm_stat = 0.0
            dm_p = 1.0

        improvement_pct = (mean_base - mean_enh) / np.abs(mean_base) * 100
        sig = mean_enh < mean_base and dm_p < 0.05

        print(f"\n    Feature: {top_feature}")
        print(f"      Baseline QLIKE:  {mean_base:.6f}")
        print(f"      Enhanced QLIKE:  {mean_enh:.6f}")
        print(f"      Improvement:     {improvement_pct:+.2f}%")
        print(f"      DM stat:         {dm_stat:.3f}")
        print(f"      DM p-value:      {dm_p:.4f}")
        print(f"      Significant?     {'YES' if sig else 'NO'}")

        all_results[top_feature] = {
            "n_forecasts": len(oos_results["dates"]),
            "baseline_qlike": float(mean_base),
            "enhanced_qlike": float(mean_enh),
            "improvement_pct": float(improvement_pct),
            "dm_stat": float(dm_stat),
            "dm_p_value": float(dm_p),
            "significant": sig,
        }

    # Pick best feature result
    if not all_results:
        return None

    best_feat_name = min(all_results, key=lambda k: all_results[k]["enhanced_qlike"])
    best = all_results[best_feat_name]

    return {
        "asset": asset_name,
        "top_feature": best_feat_name,
        "all_features_tested": all_results,
        "n_forecasts": best["n_forecasts"],
        "baseline_qlike": best["baseline_qlike"],
        "garchx_qlike": best["enhanced_qlike"],
        "improvement_pct": best["improvement_pct"],
        "dm_stat": best["dm_stat"],
        "dm_p_value": best["dm_p_value"],
        "garchx_significant": best["significant"],
    }


def cross_asset_summary(all_partial, all_granger, all_garchx):
    """Cross-asset summary of liquidity features."""
    print("\n" + "=" * 70)
    print("CROSS-ASSET SUMMARY")
    print("=" * 70)

    # 1. Partial correlation summary
    print("\n--- Partial r with future 22d RV (controlling for VIX) ---")
    features = ["amihud", "roll_spread", "cs_spread", "rel_volume", "price_impact"]
    print(f"{'Feature':<15}", end="")
    for asset in ASSETS:
        print(f"  {asset:>10}", end="")
    print(f"  {'Harvey Pass':>12}")
    print("-" * 75)

    feature_pass_count = {}
    for feat in features:
        print(f"  {feat:<15}", end="")
        passes = 0
        for asset in ASSETS:
            if asset in all_partial and feat in all_partial[asset]:
                pr = all_partial[asset][feat]["partial_r"]
                t = all_partial[asset][feat]["t_stat"]
                marker = "*" if all_partial[asset][feat]["passes_harvey"] else ""
                print(f"  {pr:>9.4f}{marker}", end="")
                if all_partial[asset][feat]["passes_harvey"]:
                    passes += 1
            else:
                print(f"  {'N/A':>10}", end="")
        print(f"  {passes}/{len(ASSETS):>10}")
        feature_pass_count[feat] = passes

    # 2. Granger causality summary
    print("\n--- Granger Causality: Liquidity → Vol? ---")
    print(f"{'Feature':<15}", end="")
    for asset in ASSETS:
        print(f"  {asset:>10}", end="")
    print(f"  {'Causes Vol':>12}")
    print("-" * 75)

    for feat in features:
        print(f"  {feat:<15}", end="")
        causes = 0
        for asset in ASSETS:
            if asset in all_granger and feat in all_granger[asset]:
                p = all_granger[asset][feat]["p_value"]
                marker = "LEADS" if all_granger[asset][feat]["granger_causes"] else "no"
                print(f"  {marker:>10}", end="")
                if all_granger[asset][feat]["granger_causes"]:
                    causes += 1
            else:
                print(f"  {'N/A':>10}", end="")
        print(f"  {causes}/{len(ASSETS):>10}")

    # 3. GARCH-X summary
    print("\n--- GARCH-X OOS Performance (vs GJR-GARCH baseline) ---")
    print(f"{'Asset':<8} {'Top Feature':<15} {'Base QLIKE':>12} {'GARCHX QLIKE':>13} {'Improv%':>10} {'DM stat':>10} {'Sig?':>6}")
    print("-" * 80)

    garchx_wins = 0
    for asset in ASSETS:
        if asset in all_garchx and all_garchx[asset] is not None:
            r = all_garchx[asset]
            sig = "YES" if r["garchx_significant"] else "no"
            print(
                f"  {asset:<8} {r['top_feature']:<15} {r['baseline_qlike']:>12.6f} "
                f"{r['garchx_qlike']:>13.6f} {r['improvement_pct']:>+10.2f} "
                f"{r['dm_stat']:>10.3f} {sig:>6}"
            )
            if r["garchx_significant"]:
                garchx_wins += 1
        else:
            print(f"  {asset:<8} {'N/A':<15}")

    return feature_pass_count, garchx_wins


def event_study_liquidity_vol(features_df, rv_series, vix_series, asset_name):
    """
    Event study: What happens to vol after liquidity deterioration events?
    Define event: Amihud > 90th percentile (extreme illiquidity)
    """
    print(f"\n--- Event Study: Illiquidity Spikes → Vol ({asset_name}) ---")

    amihud = features_df["amihud"].dropna()
    threshold_90 = amihud.quantile(0.90)
    threshold_95 = amihud.quantile(0.95)

    events_90 = amihud[amihud > threshold_90].index
    events_95 = amihud[amihud > threshold_95].index

    combined = pd.DataFrame({"rv": rv_series, "vix": vix_series}).dropna()

    results = {}
    for label, events in [("P90", events_90), ("P95", events_95)]:
        # Measure RV in 5, 10, 22 days after event
        horizons = [5, 10, 22]
        rv_after = {h: [] for h in horizons}

        for event_date in events:
            loc = combined.index.get_loc(event_date) if event_date in combined.index else None
            if loc is None:
                continue
            for h in horizons:
                if loc + h < len(combined):
                    rv_after[h].append(combined["rv"].iloc[loc + h])

        # Compare to unconditional mean
        unconditional_rv = combined["rv"].mean()

        print(f"  {label} events: {len(events)} days (Amihud > {threshold_90 if label == 'P90' else threshold_95:.6f})")
        for h in horizons:
            if len(rv_after[h]) < 10:
                continue
            conditional_rv = np.mean(rv_after[h])
            ratio = conditional_rv / unconditional_rv
            t_stat, p_val = stats.ttest_1samp(rv_after[h], unconditional_rv)
            print(
                f"    RV after {h:>2}d: {conditional_rv:.6f} vs unconditional {unconditional_rv:.6f} "
                f"(ratio={ratio:.2f}, t={t_stat:.2f}, p={p_val:.4f})"
            )

        results[label] = {
            "n_events": len(events),
            "threshold": float(threshold_90 if label == "P90" else threshold_95),
        }

    return results


def main():
    t0 = time.time()

    # 1. Download data
    data = download_data()
    if VIX_TICKER not in data:
        print("ERROR: VIX data not available")
        sys.exit(1)

    vix_close = data[VIX_TICKER]["Close"]
    if isinstance(vix_close, pd.DataFrame):
        vix_close = vix_close.iloc[:, 0]

    # 2. Process each asset
    all_partial = {}
    all_granger = {}
    all_garchx = {}
    all_events = {}

    for asset in ASSETS:
        if asset not in data:
            print(f"\nSkipping {asset}: no data")
            continue

        df = data[asset]
        print(f"\n{'='*70}")
        print(f"Processing: {asset}")
        print(f"{'='*70}")

        # Compute liquidity features
        features_df = compute_liquidity_features(df, asset)

        # Compute forward 22d RV
        close_vals = df["Close"].values.flatten()
        ret_raw = np.full(len(close_vals), np.nan)
        ret_raw[1:] = np.diff(np.log(close_vals))
        ret_series = pd.Series(ret_raw, index=df.index)
        rv_22d = ret_series.pow(2).rolling(22, min_periods=22).sum().shift(-22)

        # Align VIX
        vix_aligned = vix_close.reindex(df.index).ffill()

        # A. Partial correlation
        partial_results = partial_correlation_analysis(features_df, rv_22d, vix_aligned, asset)
        all_partial[asset] = partial_results

        # B. Granger causality
        granger_results = granger_causality_test(features_df, rv_22d, asset)
        all_granger[asset] = granger_results

        # C. GARCH-X OOS
        garchx_results = garch_x_evaluation(df, features_df, vix_aligned, asset)
        all_garchx[asset] = garchx_results

        # D. Event study
        event_results = event_study_liquidity_vol(features_df, rv_22d, vix_aligned, asset)
        all_events[asset] = event_results

    # 3. Cross-asset summary
    feature_pass_count, garchx_wins = cross_asset_summary(all_partial, all_granger, all_garchx)

    # 4. Final verdict
    print("\n" + "=" * 70)
    print("K265 FINAL VERDICT")
    print("=" * 70)

    any_harvey = any(v > 0 for v in feature_pass_count.values())
    print(f"\n  Any feature passes Harvey (|t|>3.0)?  {'YES' if any_harvey else 'NO'}")
    print(f"  GARCH-X significant improvements:      {garchx_wins}/{len(ASSETS)}")

    if not any_harvey and garchx_wins == 0:
        verdict = "NULL RESULT"
        explanation = (
            "Liquidity proxies from daily OHLCV do NOT add predictive power for "
            "future volatility beyond VIX. This is consistent with VIX sufficiency "
            "(K152, J3, J4). The information in bid-ask spread proxies is likely "
            "already captured by VIX through the options market."
        )
    elif garchx_wins > 0:
        verdict = "PARTIAL SIGNAL"
        explanation = (
            f"GARCH-X with liquidity features shows improvement in {garchx_wins}/{len(ASSETS)} "
            "assets. However, the signal may be marginal and needs cross-OOS validation."
        )
    else:
        verdict = "WEAK SIGNAL"
        explanation = (
            "Some features pass Harvey threshold in partial correlation but "
            "GARCH-X does not significantly improve OOS. Marginal signal only."
        )

    print(f"\n  Verdict: {verdict}")
    print(f"  {explanation}")

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.1f}s")

    # 5. Save results
    output = {
        "experiment": "K265",
        "title": "Liquidity Premium — Bid-Ask Spread Proxies for Vol Prediction",
        "hypothesis": "Liquidity proxies from daily OHLCV can predict future volatility beyond VIX",
        "data_source": "yfinance (real data)",
        "data_period": f"{DATA_START} to {DATA_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        "assets": ASSETS,
        "features_tested": [
            "amihud (Amihud 2002)",
            "roll_spread (Roll 1984)",
            "cs_spread (Corwin-Schultz 2012)",
            "rel_volume (relative volume)",
            "price_impact (Kyle lambda proxy)",
        ],
        "methodology": [
            "Partial correlation with future 22d RV controlling for VIX",
            "Granger causality test (F-test, max 5 lags)",
            "GARCH-X OOS evaluation vs GJR-GARCH baseline",
            "Event study: illiquidity spikes → subsequent vol",
        ],
        "partial_correlations": all_partial,
        "granger_causality": all_granger,
        "garchx_oos": {k: v for k, v in all_garchx.items() if v is not None},
        "event_study": all_events,
        "feature_harvey_pass_count": feature_pass_count,
        "garchx_wins": garchx_wins,
        "verdict": verdict,
        "explanation": explanation,
        "runtime_seconds": round(elapsed, 1),
        "limitations": [
            "Daily OHLCV proxies are noisy estimates of true bid-ask spread",
            "Corwin-Schultz estimator can produce negative/zero values",
            "Roll spread requires negative autocorrelation (often zero for liquid assets)",
            "Amihud measure is sensitive to dollar volume scaling",
            "GARCH-X may not fully capture nonlinear liquidity-vol relationship",
        ],
    }

    results_path = PROJECT_ROOT / "experiments" / "k265_liquidity_proxy_results.json"
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_path}")

    return output


if __name__ == "__main__":
    results = main()
