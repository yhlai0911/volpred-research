#!/usr/bin/env python3
"""
GBM vs GJR-GARCH QLIKE Cross-Validation
=========================================
Critical verification: Does GBM's -18.7% QLIKE improvement on SPY generalize?

Tests:
  - 5 assets: SPY, QQQ, GLD, TLT, EEM
  - 3 OOS periods: 2023-2024, 2020-2022, 2018-2020
  - 2 feature sets: Full (5 features) vs Minimal (2 features)
  - Baseline: GJR-GARCH(1,1) rolling w=2000

Feature snooping check: if Full >> Minimal, features may be overfitted.
Cross-asset check: if only works on SPY, it's asset-specific.
Cross-period check: if only works in one period, it's period-specific.
"""

import sys
import time
import warnings
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

def log(msg=""):
    print(msg, flush=True)


# ============================================================
# Data download
# ============================================================
def download_data(ticker, start="2005-01-01", end="2025-12-31"):
    """Download OHLCV + VIX data."""
    import yfinance as yf

    log(f"  Downloading {ticker}...")
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()

    # Returns in percentage (×100) for GARCH compatibility
    df["returns_pct"] = df["Close"].pct_change() * 100
    df["returns_decimal"] = df["Close"].pct_change()

    # Range (High-Low)/Close as fraction
    df["range"] = (df["High"] - df["Low"]) / df["Close"]

    # Realized variance proxy: squared percentage returns
    df["rv_proxy"] = df["returns_pct"] ** 2

    df = df.dropna()
    return df


def download_vix(start="2005-01-01", end="2025-12-31"):
    """Download VIX index."""
    import yfinance as yf
    log("  Downloading ^VIX...")
    vix = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    return vix[["Close"]].rename(columns={"Close": "VIX"}).dropna()


# ============================================================
# GJR-GARCH rolling forecast
# ============================================================
def gjr_garch_rolling(returns_pct, oos_start_idx, oos_end_idx, window=2000):
    """
    Rolling GJR-GARCH(1,1) one-step-ahead variance forecasts.
    returns_pct: percentage returns (×100).
    Returns: array of variance forecasts in percentage-squared units.
    """
    from arch import arch_model

    n_oos = oos_end_idx - oos_start_idx
    forecasts = np.full(n_oos, np.nan)

    for i in range(n_oos):
        t = oos_start_idx + i
        train_start = max(0, t - window)
        train_data = returns_pct[train_start:t]

        if len(train_data) < 500:
            continue

        try:
            am = arch_model(train_data, vol="GARCH", p=1, o=1, q=1,
                           dist="normal", mean="Zero", rescale=False)
            res = am.fit(disp="off", show_warning=False)
            fcast = res.forecast(horizon=1)
            # Variance in pct^2 units
            forecasts[i] = fcast.variance.iloc[-1, 0]
        except Exception:
            pass

    return forecasts


# ============================================================
# GBM rolling forecast
# ============================================================
def build_features(asset_df, vix_df, feature_set="full"):
    """
    Build feature matrix aligned with asset dates.
    Target: squared percentage return (rv_proxy = returns_pct^2).

    Full features: vix_lag, asset_lag5, vix_change, asset_range, asset_lag
    Minimal features: vix_lag, asset_lag5
    """
    # Merge asset with VIX
    merged = asset_df[["returns_pct", "rv_proxy", "range"]].copy()
    merged = merged.join(vix_df[["VIX"]], how="left")
    merged["VIX"] = merged["VIX"].ffill()
    merged = merged.dropna(subset=["VIX"])

    # Lag features (all lagged by 1 to avoid lookahead)
    merged["vix_lag"] = merged["VIX"].shift(1)
    merged["asset_lag"] = merged["rv_proxy"].shift(1)  # yesterday's squared return
    merged["asset_lag5"] = merged["rv_proxy"].rolling(5).mean().shift(1)  # 5-day avg
    merged["vix_change"] = merged["VIX"].pct_change().shift(1)
    merged["asset_range"] = merged["range"].shift(1)

    merged = merged.dropna()

    if feature_set == "full":
        feature_cols = ["vix_lag", "asset_lag", "asset_lag5", "vix_change", "asset_range"]
    elif feature_set == "minimal":
        feature_cols = ["vix_lag", "asset_lag5"]
    else:
        raise ValueError(f"Unknown feature set: {feature_set}")

    return merged, feature_cols


def gbm_rolling(merged_df, feature_cols, oos_start_idx, oos_end_idx,
                retrain_every=63, min_train=2000):
    """
    Rolling GBM one-step-ahead variance forecasts.

    Target: rv_proxy (squared percentage returns).
    Expanding window with periodic retraining.
    Returns: array of forecasts in pct^2 units.
    """
    from sklearn.ensemble import GradientBoostingRegressor

    X = merged_df[feature_cols].values
    y = merged_df["rv_proxy"].values

    n_oos = oos_end_idx - oos_start_idx
    forecasts = np.full(n_oos, np.nan)

    model = None
    last_train_idx = -999

    for i in range(n_oos):
        t = oos_start_idx + i

        # Retrain if needed
        if (i - last_train_idx) >= retrain_every or model is None:
            train_end = t
            if train_end < min_train:
                continue

            X_train = X[:train_end]
            y_train = y[:train_end]

            model = GradientBoostingRegressor(
                n_estimators=100,
                max_depth=3,
                learning_rate=0.05,
                subsample=0.8,
                random_state=42,
            )
            model.fit(X_train, y_train)
            last_train_idx = i

        # Forecast
        try:
            pred = model.predict(X[t:t+1])[0]
            # Floor at small positive value
            forecasts[i] = max(pred, 1e-6)
        except Exception:
            pass

    return forecasts


# ============================================================
# Evaluation metrics
# ============================================================
def qlike(actual, forecast):
    """
    QLIKE loss: actual/forecast + log(forecast) - 1 - log(actual)
    Both in same units (pct^2).
    Lower is better.
    """
    mask = np.isfinite(actual) & np.isfinite(forecast) & (actual > 0) & (forecast > 0)
    a = actual[mask]
    f = forecast[mask]
    return np.mean(a / f + np.log(f)), mask.sum()


def dm_test(actual, forecast1, forecast2, loss="qlike"):
    """
    Diebold-Mariano test.
    H0: forecast1 and forecast2 have equal predictive accuracy.
    Negative t-stat means forecast2 is better.
    """
    mask = (np.isfinite(actual) & np.isfinite(forecast1) & np.isfinite(forecast2) &
            (actual > 0) & (forecast1 > 0) & (forecast2 > 0))
    a = actual[mask]
    f1 = forecast1[mask]
    f2 = forecast2[mask]

    if loss == "qlike":
        loss1 = a / f1 + np.log(f1)
        loss2 = a / f2 + np.log(f2)
    else:
        loss1 = (a - f1) ** 2
        loss2 = (a - f2) ** 2

    d = loss1 - loss2  # negative means f2 is better
    n = len(d)

    if n < 30:
        return np.nan, np.nan, n

    d_bar = np.mean(d)
    # Newey-West HAC variance with bandwidth = floor(n^(1/3))
    bw = int(np.floor(n ** (1/3)))
    gamma0 = np.var(d, ddof=1)
    nw_var = gamma0
    for j in range(1, bw + 1):
        weight = 1 - j / (bw + 1)
        gamma_j = np.mean((d[j:] - d_bar) * (d[:-j] - d_bar))
        nw_var += 2 * weight * gamma_j

    se = np.sqrt(nw_var / n)
    if se < 1e-12:
        return 0.0, 1.0, n

    t_stat = d_bar / se
    p_val = 2 * stats.t.sf(abs(t_stat), df=n - 1)

    return t_stat, p_val, n


# ============================================================
# Main experiment
# ============================================================
def run_experiment():
    log("=" * 80)
    log("GBM vs GJR-GARCH QLIKE Cross-Validation")
    log("=" * 80)
    log()

    assets = ["SPY", "QQQ", "GLD", "TLT", "EEM"]

    # OOS periods: (name, start_date, end_date)
    oos_periods = [
        ("2023-2024", "2023-01-01", "2024-12-31"),
        ("2020-2022", "2020-01-01", "2022-12-31"),
        ("2018-2020", "2018-01-01", "2019-12-31"),
    ]

    feature_sets = ["full", "minimal"]

    # Download all data
    log("PHASE 1: Downloading data")
    log("-" * 40)

    vix_df = download_vix(start="2003-01-01")
    log(f"  VIX: {len(vix_df)} days ({vix_df.index[0].date()} to {vix_df.index[-1].date()})")

    asset_data = {}
    for ticker in assets:
        df = download_data(ticker, start="2003-01-01")
        asset_data[ticker] = df
        log(f"  {ticker}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

    log()
    log("PHASE 2: Running experiments")
    log("=" * 80)

    # Results storage
    results = []

    for ticker in assets:
        df = asset_data[ticker]

        for period_name, oos_start, oos_end in oos_periods:
            log(f"\n{'='*60}")
            log(f"  {ticker} | OOS: {period_name}")
            log(f"{'='*60}")

            # Determine OOS indices for GARCH (using raw returns)
            oos_mask = (df.index >= oos_start) & (df.index <= oos_end)
            if oos_mask.sum() < 30:
                log(f"  SKIP: Only {oos_mask.sum()} OOS days")
                continue

            oos_dates = df.index[oos_mask]
            oos_start_idx_raw = np.where(oos_mask)[0][0]
            oos_end_idx_raw = np.where(oos_mask)[0][-1] + 1

            log(f"  OOS range: {oos_dates[0].date()} to {oos_dates[-1].date()} ({len(oos_dates)} days)")
            log(f"  Training data before OOS: {oos_start_idx_raw} days")

            # ── GJR-GARCH baseline ──
            log(f"  Running GJR-GARCH(1,1) rolling w=2000...")
            t0 = time.time()
            gjr_forecasts = gjr_garch_rolling(
                df["returns_pct"].values,
                oos_start_idx_raw, oos_end_idx_raw,
                window=2000
            )
            gjr_time = time.time() - t0
            gjr_valid = np.isfinite(gjr_forecasts).sum()
            log(f"    Done in {gjr_time:.1f}s, {gjr_valid}/{len(gjr_forecasts)} valid")

            # Actual realized variance (squared pct returns)
            actual_rv = df["rv_proxy"].values[oos_start_idx_raw:oos_end_idx_raw]

            # GJR QLIKE
            gjr_qlike, gjr_n = qlike(actual_rv, gjr_forecasts)
            log(f"    GJR QLIKE = {gjr_qlike:.4f} (n={gjr_n})")

            # ── GBM variants ──
            for fset in feature_sets:
                log(f"  Running GBM ({fset} features)...")

                # Build features
                merged, feature_cols = build_features(df, vix_df, feature_set=fset)
                log(f"    Features: {feature_cols}")
                log(f"    Merged data: {len(merged)} days")

                # Map OOS dates to merged index
                merged_dates = merged.index
                oos_in_merged = merged_dates.isin(oos_dates)

                if oos_in_merged.sum() < 30:
                    log(f"    SKIP: Only {oos_in_merged.sum()} OOS days in merged data")
                    continue

                oos_merged_indices = np.where(oos_in_merged)[0]
                oos_start_merged = oos_merged_indices[0]
                oos_end_merged = oos_merged_indices[-1] + 1

                log(f"    OOS in merged: idx {oos_start_merged} to {oos_end_merged}")
                log(f"    Training data before OOS: {oos_start_merged} days")

                t0 = time.time()
                gbm_forecasts_merged = gbm_rolling(
                    merged, feature_cols,
                    oos_start_merged, oos_end_merged,
                    retrain_every=63, min_train=2000
                )
                gbm_time = time.time() - t0
                gbm_valid = np.isfinite(gbm_forecasts_merged).sum()
                log(f"    Done in {gbm_time:.1f}s, {gbm_valid}/{len(gbm_forecasts_merged)} valid")

                # Actual for merged subset
                actual_merged = merged["rv_proxy"].values[oos_start_merged:oos_end_merged]

                # GBM QLIKE
                gbm_qlike, gbm_n = qlike(actual_merged, gbm_forecasts_merged)
                log(f"    GBM QLIKE = {gbm_qlike:.4f} (n={gbm_n})")

                # We need to align GJR and GBM for fair DM test
                # Map merged OOS dates back to raw df indices for GJR
                merged_oos_dates = merged_dates[oos_start_merged:oos_end_merged]

                # Get GJR forecasts for same dates
                gjr_aligned = np.full(len(merged_oos_dates), np.nan)
                for j, d in enumerate(merged_oos_dates):
                    raw_idx = df.index.get_loc(d)
                    offset = raw_idx - oos_start_idx_raw
                    if 0 <= offset < len(gjr_forecasts):
                        gjr_aligned[j] = gjr_forecasts[offset]

                # Compute GJR QLIKE on same dates for fair comparison
                gjr_qlike_aligned, gjr_n_aligned = qlike(actual_merged, gjr_aligned)

                # Improvement
                if gjr_qlike_aligned > 0:
                    improvement = (gbm_qlike - gjr_qlike_aligned) / abs(gjr_qlike_aligned) * 100
                else:
                    improvement = np.nan

                # DM test
                dm_t, dm_p, dm_n = dm_test(actual_merged, gjr_aligned, gbm_forecasts_merged)

                log(f"    Aligned GJR QLIKE = {gjr_qlike_aligned:.4f}")
                log(f"    QLIKE improvement = {improvement:+.1f}%")
                log(f"    DM test: t={dm_t:.3f}, p={dm_p:.4f} (n={dm_n})")

                sig = ""
                if dm_p < 0.01:
                    sig = "***"
                elif dm_p < 0.05:
                    sig = "**"
                elif dm_p < 0.10:
                    sig = "*"

                results.append({
                    "Asset": ticker,
                    "OOS": period_name,
                    "Features": fset,
                    "GJR_QLIKE": gjr_qlike_aligned,
                    "GBM_QLIKE": gbm_qlike,
                    "Improvement_%": improvement,
                    "DM_t": dm_t,
                    "DM_p": dm_p,
                    "n": dm_n,
                    "Sig": sig,
                })

    # ============================================================
    # Summary tables
    # ============================================================
    log("\n\n")
    log("=" * 100)
    log("COMPREHENSIVE RESULTS TABLE")
    log("=" * 100)

    df_results = pd.DataFrame(results)

    # Full features table
    log("\n>>> FULL FEATURES (vix_lag, asset_lag, asset_lag5, vix_change, asset_range)")
    log("-" * 100)
    log(f"{'Asset':<6} {'OOS':<12} {'GJR_QLIKE':>10} {'GBM_QLIKE':>10} {'Improv%':>10} {'DM_t':>8} {'DM_p':>8} {'n':>5} {'Sig':>4}")
    log("-" * 100)

    full = df_results[df_results["Features"] == "full"]
    for _, row in full.iterrows():
        log(f"{row['Asset']:<6} {row['OOS']:<12} {row['GJR_QLIKE']:>10.4f} {row['GBM_QLIKE']:>10.4f} "
            f"{row['Improvement_%']:>+10.1f} {row['DM_t']:>8.3f} {row['DM_p']:>8.4f} {row['n']:>5d} {row['Sig']:>4}")

    # Summary stats for full features
    if len(full) > 0:
        log("-" * 100)
        n_better = (full["Improvement_%"] < 0).sum()
        n_sig = (full["DM_p"] < 0.05).sum()
        n_sig_better = ((full["DM_p"] < 0.05) & (full["DM_t"] < 0)).sum()
        mean_imp = full["Improvement_%"].mean()
        median_imp = full["Improvement_%"].median()
        log(f"SUMMARY: {n_better}/{len(full)} cases GBM better | {n_sig_better}/{len(full)} significantly better (p<0.05)")
        log(f"  Mean improvement: {mean_imp:+.1f}% | Median: {median_imp:+.1f}%")

    # Minimal features table
    log("\n>>> MINIMAL FEATURES (vix_lag, asset_lag5 only)")
    log("-" * 100)
    log(f"{'Asset':<6} {'OOS':<12} {'GJR_QLIKE':>10} {'GBM_QLIKE':>10} {'Improv%':>10} {'DM_t':>8} {'DM_p':>8} {'n':>5} {'Sig':>4}")
    log("-" * 100)

    minimal = df_results[df_results["Features"] == "minimal"]
    for _, row in minimal.iterrows():
        log(f"{row['Asset']:<6} {row['OOS']:<12} {row['GJR_QLIKE']:>10.4f} {row['GBM_QLIKE']:>10.4f} "
            f"{row['Improvement_%']:>+10.1f} {row['DM_t']:>8.3f} {row['DM_p']:>8.4f} {row['n']:>5d} {row['Sig']:>4}")

    if len(minimal) > 0:
        log("-" * 100)
        n_better = (minimal["Improvement_%"] < 0).sum()
        n_sig_better = ((minimal["DM_p"] < 0.05) & (minimal["DM_t"] < 0)).sum()
        mean_imp = minimal["Improvement_%"].mean()
        median_imp = minimal["Improvement_%"].median()
        log(f"SUMMARY: {n_better}/{len(minimal)} cases GBM better | {n_sig_better}/{len(minimal)} significantly better (p<0.05)")
        log(f"  Mean improvement: {mean_imp:+.1f}% | Median: {median_imp:+.1f}%")

    # Feature snooping check
    log("\n>>> FEATURE SNOOPING CHECK (Full vs Minimal)")
    log("-" * 80)
    if len(full) > 0 and len(minimal) > 0:
        full_mean = full["Improvement_%"].mean()
        min_mean = minimal["Improvement_%"].mean()
        log(f"  Full features mean improvement:    {full_mean:+.1f}%")
        log(f"  Minimal features mean improvement: {min_mean:+.1f}%")
        diff = full_mean - min_mean
        log(f"  Difference (Full - Minimal):       {diff:+.1f}%")
        if abs(diff) > 5:
            log(f"  WARNING: Large gap suggests feature snooping risk!")
        else:
            log(f"  Gap is small — feature snooping risk appears LOW")

    # Cross-asset summary
    log("\n>>> CROSS-ASSET SUMMARY (Full features, averaged across OOS periods)")
    log("-" * 60)
    if len(full) > 0:
        asset_summary = full.groupby("Asset").agg({
            "Improvement_%": "mean",
            "DM_t": "mean",
            "DM_p": "mean",
        }).round(3)
        for asset, row in asset_summary.iterrows():
            log(f"  {asset:<6}: Mean Improvement {row['Improvement_%']:+.1f}%, Mean DM_t={row['DM_t']:.3f}, Mean p={row['DM_p']:.3f}")

    # Cross-period summary
    log("\n>>> CROSS-PERIOD SUMMARY (Full features, averaged across assets)")
    log("-" * 60)
    if len(full) > 0:
        period_summary = full.groupby("OOS").agg({
            "Improvement_%": "mean",
            "DM_t": "mean",
            "DM_p": "mean",
        }).round(3)
        for period, row in period_summary.iterrows():
            log(f"  {period:<12}: Mean Improvement {row['Improvement_%']:+.1f}%, Mean DM_t={row['DM_t']:.3f}, Mean p={row['DM_p']:.3f}")

    # Final verdict
    log("\n" + "=" * 80)
    log("VERDICT")
    log("=" * 80)

    if len(full) > 0:
        n_total = len(full)
        n_sig_better = ((full["DM_p"] < 0.05) & (full["DM_t"] < 0)).sum()
        n_sig_worse = ((full["DM_p"] < 0.05) & (full["DM_t"] > 0)).sum()
        n_better = (full["Improvement_%"] < 0).sum()
        mean_imp = full["Improvement_%"].mean()

        # Check if SPY-specific
        spy_results = full[full["Asset"] == "SPY"]
        non_spy = full[full["Asset"] != "SPY"]
        spy_mean = spy_results["Improvement_%"].mean() if len(spy_results) > 0 else 0
        non_spy_mean = non_spy["Improvement_%"].mean() if len(non_spy) > 0 else 0

        log(f"  Total experiments: {n_total}")
        log(f"  GBM better (any): {n_better}/{n_total} ({n_better/n_total*100:.0f}%)")
        log(f"  GBM significantly better (p<0.05): {n_sig_better}/{n_total}")
        log(f"  GBM significantly worse (p<0.05): {n_sig_worse}/{n_total}")
        log(f"  Mean QLIKE improvement: {mean_imp:+.1f}%")
        log(f"  SPY-only mean: {spy_mean:+.1f}% | Non-SPY mean: {non_spy_mean:+.1f}%")
        log()

        if n_sig_better >= n_total * 0.6 and abs(spy_mean - non_spy_mean) < 10:
            log("  CONCLUSION: GENUINE BREAKTHROUGH — GBM consistently beats GJR-GARCH")
        elif n_sig_better >= 3 and n_better >= n_total * 0.5:
            log("  CONCLUSION: PARTIAL SUCCESS — GBM helps on some assets/periods")
        elif n_sig_better <= 1 and abs(spy_mean) > abs(non_spy_mean) * 2:
            log("  CONCLUSION: FALSE ALARM — Likely SPY-specific overfitting")
        elif n_sig_worse > n_sig_better:
            log("  CONCLUSION: FALSE ALARM — GBM is actually WORSE than GJR-GARCH")
        else:
            log("  CONCLUSION: INCONCLUSIVE — Mixed results, needs further investigation")

    log()
    return df_results


if __name__ == "__main__":
    t_start = time.time()
    results = run_experiment()
    elapsed = time.time() - t_start
    log(f"\nTotal runtime: {elapsed/60:.1f} minutes")
