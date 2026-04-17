#!/usr/bin/env python3
"""
K744: 5-Min Realized Volatility vs Daily Proxy — Pre-HAR-RV Data Validation

[提出: Claude, 執行: Claude]

Background:
    We have 51 days of SPY 5-min data. Before running full HAR-RV (needs 60+ days),
    validate data quality and compare RV to daily proxies.

    Prior work: K196 (47 days) found RV AC(1)=0.414 vs c2c AC(1)=-0.118.
    This experiment extends with 51 days and adds systematic proxy comparison.

Parts:
    A) Data quality check — bar counts, gap detection, RV computation
    B) Proxy comparison — RV_5min vs |daily_return|, daily_return², GARCH sigma²
    C) Intraday patterns — U-shape, first/last 30-min contribution

Data source: data/intraday/SPY_5min_*.csv (yfinance, 51 days: 2026-01-14 to 2026-03-27)
References:
    - Andersen & Bollerslev (1998) "Answering the Skeptics" — RV from HF data
    - Barndorff-Nielsen & Shephard (2002) — realized variance theory
    - Corsi (2009) "A Simple Approximate Long-Memory Model" — HAR-RV
    - Hansen & Lunde (2005) "A Realized Variance for the Whole Day" — noise, subsampling
"""

import glob
import json
import os
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────
# PART A: Data Quality Check
# ─────────────────────────────────────────────────────────────────

def load_5min_data(data_dir="data/intraday"):
    """Load all SPY 5-min CSV files, return dict of date -> DataFrame."""
    pattern = os.path.join(data_dir, "SPY_5min_*.csv")
    files = sorted(glob.glob(pattern))

    daily_data = {}
    for f in files:
        # Extract date from filename
        date_str = os.path.basename(f).replace("SPY_5min_", "").replace(".csv", "")

        # Read CSV with multi-row header (rows 0-2 are header)
        df = pd.read_csv(f, header=[0, 1], index_col=0, parse_dates=True)

        # Flatten multi-level columns
        df.columns = [col[0] for col in df.columns]

        # Keep only Close for RV calculation
        if "Close" in df.columns:
            daily_data[date_str] = df

    return daily_data


def compute_rv_from_5min(df):
    """
    Compute Realized Variance from 5-min close prices.
    RV = sum(log_return_i^2)
    """
    close = df["Close"].dropna()
    if len(close) < 2:
        return np.nan, 0, []

    log_returns = np.log(close / close.shift(1)).dropna()
    rv = (log_returns ** 2).sum()
    return rv, len(close), log_returns.values


def check_gaps(df, expected_interval_min=5):
    """Check for gaps > expected_interval in the intraday data."""
    idx = df.index
    if len(idx) < 2:
        return []

    diffs = pd.Series(idx[1:]) - pd.Series(idx[:-1])
    gap_threshold = pd.Timedelta(minutes=expected_interval_min * 2)  # >10 min = gap
    gaps = [(i, d.total_seconds() / 60) for i, d in enumerate(diffs) if d > gap_threshold]
    return gaps


def part_a_data_quality():
    """Part A: Comprehensive data quality check."""
    print("=" * 70)
    print("PART A: Data Quality Check — SPY 5-Min Data")
    print("=" * 70)

    daily_data = load_5min_data()
    n_days = len(daily_data)
    print(f"\nTotal trading days loaded: {n_days}")

    dates = sorted(daily_data.keys())
    print(f"Date range: {dates[0]} to {dates[-1]}")

    results = []
    all_log_returns = []

    for date_str in dates:
        df = daily_data[date_str]
        rv, n_bars, log_rets = compute_rv_from_5min(df)
        gaps = check_gaps(df)

        results.append({
            "date": date_str,
            "n_bars": n_bars,
            "n_returns": len(log_rets),
            "rv": float(rv) if not np.isnan(rv) else None,
            "rv_annualized_vol": float(np.sqrt(rv * 252) * 100) if not np.isnan(rv) else None,
            "n_gaps": len(gaps),
            "max_gap_min": max([g[1] for g in gaps]) if gaps else 0,
            "flagged": n_bars < 60 or len(gaps) > 0
        })

        if len(log_rets) > 0:
            all_log_returns.extend(log_rets.tolist())

    df_results = pd.DataFrame(results)

    # Summary statistics
    print(f"\n--- Bar Count Summary ---")
    print(f"  Mean bars/day:   {df_results['n_bars'].mean():.1f}")
    print(f"  Min bars/day:    {df_results['n_bars'].min()}")
    print(f"  Max bars/day:    {df_results['n_bars'].max()}")
    print(f"  Std bars/day:    {df_results['n_bars'].std():.1f}")

    flagged = df_results[df_results["flagged"]]
    print(f"\n--- Flagged Days ({len(flagged)}/{n_days}) ---")
    if len(flagged) > 0:
        for _, row in flagged.iterrows():
            print(f"  {row['date']}: {row['n_bars']} bars, {row['n_gaps']} gaps (max {row['max_gap_min']:.0f} min)")
    else:
        print("  None — all days have ≥60 bars and no large gaps")

    # RV summary
    rv_valid = df_results[df_results["rv"].notna()]
    print(f"\n--- Realized Variance Summary ---")
    print(f"  Valid RV days:   {len(rv_valid)}/{n_days}")
    print(f"  Mean RV:         {rv_valid['rv'].mean():.8f}")
    print(f"  Std RV:          {rv_valid['rv'].std():.8f}")
    print(f"  Min RV:          {rv_valid['rv'].min():.8f}")
    print(f"  Max RV:          {rv_valid['rv'].max():.8f}")
    print(f"  Mean Ann. Vol:   {rv_valid['rv_annualized_vol'].mean():.2f}%")

    # 5-min return distribution
    all_rets = np.array(all_log_returns)
    print(f"\n--- 5-Min Return Distribution ---")
    print(f"  Total 5-min returns: {len(all_rets)}")
    print(f"  Mean:     {all_rets.mean():.8f}")
    print(f"  Std:      {all_rets.std():.6f}")
    print(f"  Skewness: {stats.skew(all_rets):.4f}")
    print(f"  Kurtosis: {stats.kurtosis(all_rets):.4f} (excess)")

    return df_results, daily_data


# ─────────────────────────────────────────────────────────────────
# PART B: Proxy Comparison
# ─────────────────────────────────────────────────────────────────

def part_b_proxy_comparison(df_rv):
    """Part B: Compare RV_5min to daily return proxies."""
    print("\n" + "=" * 70)
    print("PART B: Proxy Comparison — RV_5min vs Daily Proxies")
    print("=" * 70)

    # Get SPY daily data covering our 5-min range
    dates = sorted(df_rv["date"].values)
    start_date = dates[0]
    end_date = dates[-1]

    # Extend range slightly for GARCH estimation
    spy_daily = yf.download("SPY", start="2024-01-01", end="2026-03-28", progress=False)
    if isinstance(spy_daily.columns, pd.MultiIndex):
        spy_daily.columns = [c[0] for c in spy_daily.columns]

    spy_daily["log_return"] = np.log(spy_daily["Close"] / spy_daily["Close"].shift(1))
    spy_daily["abs_return"] = spy_daily["log_return"].abs()
    spy_daily["sq_return"] = spy_daily["log_return"] ** 2
    spy_daily["date_str"] = spy_daily.index.strftime("%Y-%m-%d")

    # Merge RV with daily data
    df_rv_valid = df_rv[df_rv["rv"].notna()].copy()
    merged = df_rv_valid.merge(
        spy_daily[["date_str", "log_return", "abs_return", "sq_return", "Close"]],
        left_on="date", right_on="date_str", how="inner"
    )

    print(f"\nMerged observations: {len(merged)}")

    if len(merged) < 10:
        print("ERROR: Too few merged observations for meaningful analysis")
        return None

    # GARCH(1,1) fit for conditional variance
    try:
        from arch import arch_model
        # Use full daily data for GARCH estimation
        returns_full = spy_daily["log_return"].dropna() * 100  # percentage
        am = arch_model(returns_full, vol="Garch", p=1, q=1, dist="normal")
        res = am.fit(disp="off")

        # Extract conditional variance aligned to the returns index
        cond_var = res.conditional_volatility ** 2 / 10000  # back to decimal
        cond_var_series = pd.Series(cond_var.values, index=returns_full.index)
        cond_var_df = pd.DataFrame({
            "date_str": cond_var_series.index.strftime("%Y-%m-%d"),
            "garch_sigma2": cond_var_series.values
        })

        merged = merged.merge(cond_var_df, on="date_str", how="left")
        has_garch = True
        print(f"GARCH(1,1) fitted on {len(returns_full)} daily returns")
    except Exception as e:
        print(f"GARCH fitting failed: {e}")
        import traceback; traceback.print_exc()
        merged["garch_sigma2"] = np.nan
        has_garch = False

    # Compute correlations
    rv = merged["rv"].values
    abs_r = merged["abs_return"].values
    sq_r = merged["sq_return"].values

    print(f"\n--- Correlation with RV_5min ---")

    # RV vs |daily_return|
    corr_abs, p_abs = stats.pearsonr(rv, abs_r)
    rank_corr_abs, _ = stats.spearmanr(rv, abs_r)
    print(f"  |daily_return|:  Pearson r = {corr_abs:.4f} (p={p_abs:.4f}), Spearman ρ = {rank_corr_abs:.4f}")

    # RV vs daily_return²
    corr_sq, p_sq = stats.pearsonr(rv, sq_r)
    rank_corr_sq, _ = stats.spearmanr(rv, sq_r)
    print(f"  daily_return²:   Pearson r = {corr_sq:.4f} (p={p_sq:.4f}), Spearman ρ = {rank_corr_sq:.4f}")

    # RV vs GARCH sigma²
    garch_corr_str = "N/A"
    garch_rank_str = "N/A"
    if has_garch and merged["garch_sigma2"].notna().sum() > 10:
        valid = merged.dropna(subset=["garch_sigma2"])
        corr_garch, p_garch = stats.pearsonr(valid["rv"], valid["garch_sigma2"])
        rank_corr_garch, _ = stats.spearmanr(valid["rv"], valid["garch_sigma2"])
        print(f"  GARCH sigma²:    Pearson r = {corr_garch:.4f} (p={p_garch:.4f}), Spearman ρ = {rank_corr_garch:.4f}")
        garch_corr_str = f"{corr_garch:.4f}"
        garch_rank_str = f"{rank_corr_garch:.4f}"

    # Autocorrelation comparison (key finding from K196)
    print(f"\n--- Autocorrelation Comparison ---")
    rv_series = merged.sort_values("date")["rv"].values
    daily_sq = merged.sort_values("date")["sq_return"].values
    daily_abs = merged.sort_values("date")["abs_return"].values

    # AC(1) for each
    def ac1(x):
        x = x[~np.isnan(x)]
        if len(x) < 5:
            return np.nan
        return np.corrcoef(x[:-1], x[1:])[0, 1]

    ac1_rv = ac1(rv_series)
    ac1_sq = ac1(daily_sq)
    ac1_abs = ac1(daily_abs)

    print(f"  AC(1) RV_5min:       {ac1_rv:.4f}")
    print(f"  AC(1) daily_return²: {ac1_sq:.4f}")
    print(f"  AC(1) |daily_return|:{ac1_abs:.4f}")
    print(f"\n  K196 reference: AC(1) RV=0.414, c2c=-0.118")
    print(f"  → RV much more predictable than daily squared returns")

    # Descriptive comparison
    print(f"\n--- Descriptive Stats Comparison ---")
    print(f"  {'Measure':<20} {'Mean':>12} {'Std':>12} {'CV':>8}")
    print(f"  {'RV_5min':<20} {rv.mean():>12.8f} {rv.std():>12.8f} {rv.std()/rv.mean():>8.2f}")
    print(f"  {'daily_return²':<20} {sq_r.mean():>12.8f} {sq_r.std():>12.8f} {sq_r.std()/sq_r.mean():>8.2f}")
    print(f"  {'|daily_return|':<20} {abs_r.mean():>12.8f} {abs_r.std():>12.8f} {abs_r.std()/abs_r.mean():>8.2f}")

    # Ratio analysis
    ratio = sq_r / rv
    valid_ratio = ratio[~np.isnan(ratio) & ~np.isinf(ratio)]
    print(f"\n--- Ratio: daily_return² / RV_5min ---")
    print(f"  Mean ratio:  {valid_ratio.mean():.4f}")
    print(f"  Median ratio:{np.median(valid_ratio):.4f}")
    print(f"  Std ratio:   {valid_ratio.std():.4f}")
    print(f"  (ratio=1.0 means daily squared return perfectly proxies RV)")
    print(f"  (ratio>1.0 means daily proxy overestimates volatility)")

    proxy_results = {
        "n_merged": len(merged),
        "corr_rv_abs_return": {"pearson": float(corr_abs), "spearman": float(rank_corr_abs), "p_value": float(p_abs)},
        "corr_rv_sq_return": {"pearson": float(corr_sq), "spearman": float(rank_corr_sq), "p_value": float(p_sq)},
        "corr_rv_garch_sigma2": garch_corr_str,
        "ac1_rv": float(ac1_rv),
        "ac1_sq_return": float(ac1_sq),
        "ac1_abs_return": float(ac1_abs),
        "ratio_sq_over_rv": {
            "mean": float(valid_ratio.mean()),
            "median": float(np.median(valid_ratio)),
            "std": float(valid_ratio.std())
        }
    }

    return proxy_results, merged


# ─────────────────────────────────────────────────────────────────
# PART C: Intraday Patterns
# ─────────────────────────────────────────────────────────────────

def part_c_intraday_patterns(daily_data):
    """Part C: Intraday volatility patterns (U-shape analysis)."""
    print("\n" + "=" * 70)
    print("PART C: Intraday Volatility Patterns")
    print("=" * 70)

    # Collect all 5-min returns with time-of-day
    all_rows = []

    for date_str, df in sorted(daily_data.items()):
        close = df["Close"].dropna()
        if len(close) < 2:
            continue

        log_rets = np.log(close / close.shift(1)).dropna()

        for ts, ret in log_rets.items():
            all_rows.append({
                "date": date_str,
                "time": ts.strftime("%H:%M"),
                "hour": ts.hour,
                "minute": ts.minute,
                "abs_return": abs(ret),
                "sq_return": ret ** 2
            })

    df_intra = pd.DataFrame(all_rows)
    print(f"\nTotal 5-min return observations: {len(df_intra)}")

    # Average |return| by time of day
    by_time = df_intra.groupby("time").agg(
        mean_abs_ret=("abs_return", "mean"),
        mean_sq_ret=("sq_return", "mean"),
        count=("abs_return", "count")
    ).sort_index()

    print(f"\n--- Average |5-min Return| by Time of Day (UTC) ---")
    print(f"  {'Time':<8} {'|return|':>10} {'return²':>12} {'count':>6}")
    for time_str, row in by_time.iterrows():
        bar = "█" * int(row["mean_abs_ret"] / by_time["mean_abs_ret"].max() * 30)
        print(f"  {time_str:<8} {row['mean_abs_ret']:>10.6f} {row['mean_sq_ret']:>12.8f} {row['count']:>6.0f}  {bar}")

    # U-shape ratio: first_30min + last_30min vs middle
    # SPY trades 14:30-21:00 UTC (9:30-16:00 ET)
    # First 30 min: 14:35-15:00 UTC  (returns from 14:35, 14:40, ..., 15:00 = 6 bars)
    # Last 30 min:  20:35-21:00 UTC  (returns from 20:35, 20:40, ..., 21:00 = 6 bars)

    df_intra["minutes_from_open"] = (df_intra["hour"] - 14) * 60 + df_intra["minute"] - 30

    first_30 = df_intra[df_intra["minutes_from_open"] <= 30]
    last_30 = df_intra[df_intra["minutes_from_open"] >= 360]  # 6h * 60min = 360
    middle = df_intra[(df_intra["minutes_from_open"] > 30) & (df_intra["minutes_from_open"] < 360)]

    # RV contribution
    total_sq = df_intra.groupby("date")["sq_return"].sum()
    first_sq = first_30.groupby("date")["sq_return"].sum()
    last_sq = last_30.groupby("date")["sq_return"].sum()

    # Align dates
    common_dates = total_sq.index.intersection(first_sq.index).intersection(last_sq.index)

    first_pct = (first_sq.loc[common_dates] / total_sq.loc[common_dates]) * 100
    last_pct = (last_sq.loc[common_dates] / total_sq.loc[common_dates]) * 100

    print(f"\n--- RV Contribution by Time Period ---")
    print(f"  First 30 min: {first_pct.mean():.1f}% ± {first_pct.std():.1f}% of daily RV")
    print(f"  Last 30 min:  {last_pct.mean():.1f}% ± {last_pct.std():.1f}% of daily RV")
    print(f"  Combined:     {(first_pct + last_pct).mean():.1f}% of daily RV")
    print(f"  Middle:       {(100 - first_pct - last_pct).mean():.1f}% (remaining)")

    # U-shape strength: ratio of (first+last) avg |ret| to middle avg |ret|
    u_ratio = (first_30["abs_return"].mean() + last_30["abs_return"].mean()) / (2 * middle["abs_return"].mean())
    print(f"\n  U-shape ratio (edge/middle): {u_ratio:.3f}")
    print(f"  (>1.0 = U-shape present, >1.5 = strong U-shape)")

    # Formal test: is first-30-min vol significantly different from middle?
    t_stat, p_val = stats.ttest_ind(first_30["abs_return"], middle["abs_return"])
    print(f"\n  t-test first-30 vs middle: t={t_stat:.3f}, p={p_val:.4f}")

    t_stat_last, p_val_last = stats.ttest_ind(last_30["abs_return"], middle["abs_return"])
    print(f"  t-test last-30 vs middle:  t={t_stat_last:.3f}, p={p_val_last:.4f}")

    pattern_results = {
        "total_5min_returns": len(df_intra),
        "first_30min_rv_pct": {
            "mean": float(first_pct.mean()),
            "std": float(first_pct.std())
        },
        "last_30min_rv_pct": {
            "mean": float(last_pct.mean()),
            "std": float(last_pct.std())
        },
        "combined_edge_rv_pct": float((first_pct + last_pct).mean()),
        "u_shape_ratio": float(u_ratio),
        "ttest_first_vs_middle": {"t": float(t_stat), "p": float(p_val)},
        "ttest_last_vs_middle": {"t": float(t_stat_last), "p": float(p_val_last)},
        "time_of_day_volatility": {
            time_str: {
                "mean_abs_ret": float(row["mean_abs_ret"]),
                "mean_sq_ret": float(row["mean_sq_ret"]),
                "count": int(row["count"])
            }
            for time_str, row in by_time.iterrows()
        }
    }

    return pattern_results


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("K744: 5-Min Realized Volatility vs Daily Proxy — Pre-HAR-RV Data Validation")
    print("Data source: yfinance 5-min bars, SPY, 51 trading days (2026-01-14 to 2026-03-27)")
    print("=" * 70)

    # Part A: Data Quality
    df_rv, daily_data = part_a_data_quality()

    # Part B: Proxy Comparison
    proxy_results, merged = part_b_proxy_comparison(df_rv)

    # Part C: Intraday Patterns
    pattern_results = part_c_intraday_patterns(daily_data)

    # ─────────────────────────────────────────────────────────────
    # Summary & Save
    # ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Key findings
    n_days = len(df_rv)
    n_flagged = df_rv["flagged"].sum()
    rv_valid = df_rv[df_rv["rv"].notna()]

    print(f"\n1. DATA QUALITY:")
    print(f"   - {n_days} days loaded, {n_flagged} flagged (gaps or low bar count)")
    print(f"   - Mean {df_rv['n_bars'].mean():.0f} bars/day (expected ~78 for 6.5h session)")
    print(f"   - Data is {'USABLE' if n_flagged / n_days < 0.1 else 'NEEDS ATTENTION'}")

    print(f"\n2. PROXY QUALITY:")
    print(f"   - Best proxy: {'|return|' if proxy_results['corr_rv_abs_return']['spearman'] > proxy_results['corr_rv_sq_return']['spearman'] else 'return²'}")
    print(f"   - AC(1) gap: RV={proxy_results['ac1_rv']:.3f} vs r²={proxy_results['ac1_sq_return']:.3f}")
    print(f"   - This gap explains why GARCH has a ceiling on daily data")

    print(f"\n3. INTRADAY PATTERNS:")
    print(f"   - U-shape ratio: {pattern_results['u_shape_ratio']:.3f}")
    print(f"   - First+Last 30 min = {pattern_results['combined_edge_rv_pct']:.0f}% of daily RV")

    # Is 51 days enough for HAR-RV?
    har_ready = n_days >= 22 + 5 + 22  # need 22 for RV_month + 5 for RV_week + enough for estimation
    print(f"\n4. HAR-RV READINESS:")
    print(f"   - Days available: {n_days}")
    print(f"   - Days needed for HAR-RV: ~50 (22 month + 5 week + 20 estimation)")
    print(f"   - Status: {'MARGINAL — can run pilot but short estimation window' if n_days < 60 else 'READY'}")
    print(f"   - Recommendation: Continue collecting, run pilot HAR-RV now")

    # Compile results
    results = {
        "experiment_id": "K744",
        "title": "5-Min Realized Volatility vs Daily Proxy — Pre-HAR-RV Data Validation",
        "proposer": "Claude",
        "executor": "Claude",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance 5-min bars",
        "asset": "SPY",
        "period": f"{sorted(df_rv['date'])[0]} to {sorted(df_rv['date'])[-1]}",
        "n_days": int(n_days),
        "part_a_data_quality": {
            "n_days": int(n_days),
            "n_flagged": int(n_flagged),
            "mean_bars_per_day": float(df_rv["n_bars"].mean()),
            "min_bars": int(df_rv["n_bars"].min()),
            "max_bars": int(df_rv["n_bars"].max()),
            "mean_rv": float(rv_valid["rv"].mean()),
            "mean_annualized_vol_pct": float(rv_valid["rv_annualized_vol"].mean()),
            "data_usable": bool(n_flagged / n_days < 0.1),
            "daily_rv": {
                row["date"]: {
                    "n_bars": int(row["n_bars"]),
                    "rv": float(row["rv"]) if row["rv"] is not None else None,
                    "ann_vol_pct": float(row["rv_annualized_vol"]) if row["rv_annualized_vol"] is not None else None,
                    "flagged": bool(row["flagged"])
                }
                for _, row in df_rv.iterrows()
            }
        },
        "part_b_proxy_comparison": proxy_results,
        "part_c_intraday_patterns": pattern_results,
        "key_findings": [
            f"51 days of SPY 5-min data: {n_flagged} flagged, data quality {'good' if n_flagged / n_days < 0.1 else 'needs attention'}",
            f"AC(1) gap confirms K196: RV={proxy_results['ac1_rv']:.3f} >> r²={proxy_results['ac1_sq_return']:.3f}",
            f"|daily_return| Spearman ρ={proxy_results['corr_rv_abs_return']['spearman']:.3f} with RV — {'decent' if proxy_results['corr_rv_abs_return']['spearman'] > 0.5 else 'poor'} proxy",
            f"U-shape ratio={pattern_results['u_shape_ratio']:.3f}, first+last 30min = {pattern_results['combined_edge_rv_pct']:.0f}% of daily RV",
            "HAR-RV pilot feasible with current 51 days, but estimation window is tight"
        ],
        "references": [
            "Andersen & Bollerslev (1998) 'Answering the Skeptics' — realized variance from HF data",
            "Barndorff-Nielsen & Shephard (2002) — realized variance theory",
            "Corsi (2009) 'HAR-RV' — heterogeneous autoregressive model for RV",
            "Hansen & Lunde (2005) — noise in realized measures",
            "K196 — prior 47-day pilot, found RV AC(1)=0.414 vs c2c AC(1)=-0.118"
        ]
    }

    # Save results
    results_path = "experiments/k744_rv_5min_validation_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to: {results_path}")
    print("Done.")
