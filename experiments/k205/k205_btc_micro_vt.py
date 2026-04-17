#!/usr/bin/env python3
"""
K205: BTC Weekend Volatility and Microstructure-Based VT
=========================================================
[提出: 用戶, 執行: Claude]

Background: K202 found BTC-specific features beat VIX:
  - Range ratio: r=0.353 (correlated with future vol)
  - BTC-SPY correlation: DM t=4.54 (predictive of regime)
  - Weekend vol ratio: BTC trades 24/7, weekends have different microstructure

Research Question:
  Can we build a BTC-specific VT using microstructure features that
  outperforms the generic 12/VIX approach for crypto?

Methodology:
  1. BTC-specific vol predictors:
     - Range ratio: (High-Low)/Close (rolling 22d average)
     - BTC-SPY 252d rolling correlation
     - Weekend vol ratio: rolling ratio of weekend to weekday squared returns
  2. BTC VT strategies (walk-forward, rolling 252d train, monthly rebalance):
     - Buy-and-Hold (benchmark)
     - Base: 12/VIX monthly
     - Range-based: use range_ratio to scale position (high range -> reduce)
     - Corr-based: when BTC-SPY corr < 0 (decoupled), reduce BTC position
     - Weekend-based: adjust for weekend vol anomaly
     - Combined: multi-factor VT
  3. OOS: 2023-2024
  4. Statistical: DM test, Harvey threshold (t>3.0)

Data: BTC-USD, SPY, ^VIX daily from yfinance.
"""

import warnings
warnings.filterwarnings("ignore")

import json
import os
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

RESULTS_FILE = Path(__file__).resolve().parent / "k205_btc_micro_vt_results.json"


# =============================================================================
# 1. DATA LOADING
# =============================================================================

def load_data():
    """Download BTC-USD, SPY, ^VIX daily data from yfinance."""
    print("=" * 70)
    print("K205: BTC Weekend Volatility and Microstructure-Based VT")
    print("=" * 70)
    print("\n[1] Loading data from yfinance...")

    start = "2015-01-01"
    end = "2025-01-01"

    btc = yf.download("BTC-USD", start=start, end=end, auto_adjust=True, progress=False)
    spy = yf.download("SPY", start=start, end=end, auto_adjust=True, progress=False)
    vix = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)

    # Flatten multi-level columns if present
    for df in [btc, spy, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    # Build combined DataFrame
    data = pd.DataFrame(index=btc.index)
    data["btc_close"] = btc["Close"]
    data["btc_high"] = btc["High"]
    data["btc_low"] = btc["Low"]
    data["btc_open"] = btc["Open"]
    data["btc_ret"] = np.log(btc["Close"] / btc["Close"].shift(1))

    # SPY - align to BTC dates (BTC trades 24/7, SPY only weekdays)
    spy_aligned = spy["Close"].reindex(btc.index, method="ffill")
    data["spy_close"] = spy_aligned
    data["spy_ret"] = np.log(spy_aligned / spy_aligned.shift(1))

    # VIX - align to BTC dates
    vix_aligned = vix["Close"].reindex(btc.index, method="ffill")
    data["vix"] = vix_aligned

    data = data.dropna()

    print(f"  BTC-USD: {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Total observations: {len(data)}")
    print(f"  BTC ann. vol: {data['btc_ret'].std() * np.sqrt(365):.1%}")
    print(f"  BTC ann. return: {data['btc_ret'].mean() * 365:.1%}")

    return data


# =============================================================================
# 2. MICROSTRUCTURE FEATURES
# =============================================================================

def compute_features(data, range_window=22, corr_window=252, weekend_window=66):
    """
    Compute BTC-specific microstructure features:
    1. Range ratio: (High-Low)/Close, rolling 22d average
    2. BTC-SPY rolling correlation (252d)
    3. Weekend vol ratio: weekend squared returns / weekday squared returns (rolling 66d ~ 3 months)
    """
    print("\n[2] Computing microstructure features...")

    df = data.copy()

    # --- Feature 1: Range ratio ---
    daily_range = (df["btc_high"] - df["btc_low"]) / df["btc_close"]
    df["range_ratio"] = daily_range.rolling(range_window).mean()

    # --- Feature 2: BTC-SPY rolling correlation ---
    df["btc_spy_corr"] = df["btc_ret"].rolling(corr_window).corr(df["spy_ret"])

    # --- Feature 3: Weekend vol ratio ---
    # BTC trades on weekends, equities don't
    # dayofweek: 0=Mon, ..., 4=Fri, 5=Sat, 6=Sun
    df["is_weekend"] = df.index.dayofweek.isin([5, 6]).astype(int)
    df["sq_ret"] = df["btc_ret"] ** 2

    # Rolling weekend vs weekday vol
    weekend_sq = df["sq_ret"].where(df["is_weekend"] == 1, np.nan)
    weekday_sq = df["sq_ret"].where(df["is_weekend"] == 0, np.nan)

    # Use expanding min_periods to avoid NaN at start
    weekend_mean = weekend_sq.rolling(weekend_window, min_periods=10).mean()
    weekday_mean = weekday_sq.rolling(weekend_window, min_periods=10).mean()
    df["weekend_vol_ratio"] = weekend_mean / weekday_mean.replace(0, np.nan)

    df = df.dropna(subset=["range_ratio", "btc_spy_corr", "weekend_vol_ratio"])

    # Summary stats
    print(f"  Feature period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  N obs with all features: {len(df)}")
    print(f"\n  Range ratio (22d avg):")
    print(f"    Mean: {df['range_ratio'].mean():.4f}")
    print(f"    Std:  {df['range_ratio'].std():.4f}")
    print(f"    Median: {df['range_ratio'].median():.4f}")
    print(f"\n  BTC-SPY correlation (252d):")
    print(f"    Mean: {df['btc_spy_corr'].mean():.3f}")
    print(f"    Std:  {df['btc_spy_corr'].std():.3f}")
    print(f"    Min:  {df['btc_spy_corr'].min():.3f}")
    print(f"    Max:  {df['btc_spy_corr'].max():.3f}")
    print(f"\n  Weekend vol ratio:")
    print(f"    Mean: {df['weekend_vol_ratio'].mean():.3f}")
    print(f"    Std:  {df['weekend_vol_ratio'].std():.3f}")
    print(f"    (1.0 = equal weekend/weekday vol)")

    return df


# =============================================================================
# 3. FEATURE PREDICTIVENESS ANALYSIS
# =============================================================================

def analyze_feature_predictiveness(df, forward_days=22):
    """
    Test whether features predict future BTC volatility (realized vol over next 22 days).
    """
    print(f"\n[3] Feature predictiveness (forward {forward_days}d realized vol)...")

    # Forward realized vol: sqrt(sum(r^2)) over next forward_days
    fwd_rv = df["sq_ret"].rolling(forward_days).sum().shift(-forward_days)
    fwd_rv = np.sqrt(fwd_rv) * np.sqrt(365 / forward_days)  # annualized

    valid = df[["range_ratio", "btc_spy_corr", "weekend_vol_ratio"]].copy()
    valid["fwd_rv"] = fwd_rv
    valid = valid.dropna()

    results = {}
    features = ["range_ratio", "btc_spy_corr", "weekend_vol_ratio"]

    for feat in features:
        r, p = stats.pearsonr(valid[feat], valid["fwd_rv"])
        # Rank correlation (more robust)
        rho, p_rho = stats.spearmanr(valid[feat], valid["fwd_rv"])
        results[feat] = {
            "pearson_r": round(float(r), 4),
            "pearson_p": round(float(p), 6),
            "spearman_rho": round(float(rho), 4),
            "spearman_p": round(float(p_rho), 6),
            "n": len(valid),
        }
        print(f"  {feat}:")
        print(f"    Pearson r = {r:.4f} (p = {p:.6f})")
        print(f"    Spearman rho = {rho:.4f} (p = {p_rho:.6f})")

    # Also test VIX
    r_vix, p_vix = stats.pearsonr(valid.index.map(lambda x: df.loc[x, "vix"]).values,
                                   valid["fwd_rv"])
    rho_vix, p_rho_vix = stats.spearmanr(
        valid.index.map(lambda x: df.loc[x, "vix"]).values,
        valid["fwd_rv"]
    )
    results["vix"] = {
        "pearson_r": round(float(r_vix), 4),
        "pearson_p": round(float(p_vix), 6),
        "spearman_rho": round(float(rho_vix), 4),
        "spearman_p": round(float(p_rho_vix), 6),
        "n": len(valid),
    }
    print(f"  VIX (benchmark):")
    print(f"    Pearson r = {r_vix:.4f} (p = {p_vix:.6f})")
    print(f"    Spearman rho = {rho_vix:.4f} (p = {p_rho_vix:.6f})")

    return results


# =============================================================================
# 4. VT STRATEGY IMPLEMENTATIONS
# =============================================================================

def diebold_mariano_test(e1, e2):
    """
    Diebold-Mariano test for equal predictive accuracy.
    H0: E[d_t] = 0 where d_t = e1_t^2 - e2_t^2
    Returns t-stat and p-value (two-sided).
    """
    d = np.array(e1) ** 2 - np.array(e2) ** 2
    d = d[~np.isnan(d)]
    if len(d) < 10:
        return np.nan, np.nan
    mean_d = np.mean(d)
    # Newey-West with lag = int(len(d)^(1/3))
    n = len(d)
    lag = max(1, int(n ** (1 / 3)))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, lag + 1):
        gamma_k = np.mean((d[k:] - mean_d) * (d[:-k] - mean_d))
        gamma_sum += 2 * (1 - k / (lag + 1)) * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    t_stat = mean_d / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_value)


def compute_strategy_metrics(returns, rf_daily=0.0):
    """Compute Sharpe, MDD, Calmar, Sortino, etc."""
    r = np.array(returns)
    r = r[~np.isnan(r)]
    if len(r) < 30:
        return {}

    # Use 365 for crypto (trades every day)
    ann_factor = 365

    mean_r = np.mean(r)
    std_r = np.std(r, ddof=1)
    ann_ret = mean_r * ann_factor
    ann_vol = std_r * np.sqrt(ann_factor)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0

    # Sharpe t-stat
    n_years = len(r) / ann_factor
    sharpe_t = sharpe * np.sqrt(n_years)

    # MDD
    cumret = np.cumprod(1 + r)
    running_max = np.maximum.accumulate(cumret)
    drawdown = cumret / running_max - 1
    mdd = np.min(drawdown)

    # Calmar
    calmar = ann_ret / abs(mdd) if abs(mdd) > 0 else 0.0

    # Sortino
    downside = r[r < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(ann_factor) if len(downside) > 1 else ann_vol
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0.0

    # Win rate
    win_rate = np.mean(r > 0)

    # Turnover placeholder (computed separately)
    return {
        "ann_return": round(float(ann_ret), 4),
        "ann_vol": round(float(ann_vol), 4),
        "sharpe": round(float(sharpe), 4),
        "sharpe_t": round(float(sharpe_t), 4),
        "mdd": round(float(mdd), 4),
        "calmar": round(float(calmar), 4),
        "sortino": round(float(sortino), 4),
        "win_rate": round(float(win_rate), 4),
        "n_days": len(r),
        "n_years": round(float(n_years), 2),
    }


def run_vt_strategies(df, oos_start="2023-01-01", oos_end="2024-12-31",
                      train_window=252):
    """
    Run walk-forward VT strategies with monthly rebalance.

    Strategies:
    1. Buy-and-Hold (100% BTC)
    2. 12/VIX monthly (generic VT)
    3. Range-based VT: scale by range_ratio percentile
    4. Corr-based VT: reduce when BTC-SPY corr > threshold (coupled = risky)
    5. Weekend-vol VT: adjust for weekend anomaly
    6. Combined multi-factor VT
    """
    print(f"\n[4] Running VT strategies (OOS: {oos_start} to {oos_end})...")

    oos_mask = (df.index >= oos_start) & (df.index <= oos_end)
    oos_df = df[oos_mask].copy()

    if len(oos_df) < 60:
        print(f"  ERROR: Only {len(oos_df)} OOS days, need >= 60")
        return None

    print(f"  OOS period: {oos_df.index[0].strftime('%Y-%m-%d')} to {oos_df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  OOS days: {len(oos_df)}")

    # Identify month-end dates for rebalancing
    oos_df["month"] = oos_df.index.to_period("M")
    month_ends = oos_df.groupby("month").apply(lambda x: x.index[-1])

    # Strategy returns
    strategies = {
        "buy_hold": [],
        "vix_12": [],
        "range_vt": [],
        "corr_vt": [],
        "weekend_vt": [],
        "combined_vt": [],
    }
    strategy_weights = {k: [] for k in strategies.keys()}
    strategy_dates = []

    # Current weights (start at 100%)
    current_weights = {k: 1.0 for k in strategies.keys()}
    current_weights["buy_hold"] = 1.0

    # Track previous rebalance date
    prev_month = None

    for i, (date, row) in enumerate(oos_df.iterrows()):
        btc_ret_today = row["btc_ret"]
        cur_month = row["month"]

        # Rebalance at start of each new month
        if cur_month != prev_month:
            prev_month = cur_month

            # Look back at training window for feature percentiles
            hist_mask = (df.index < date) & (df.index >= df.index[max(0, df.index.get_loc(date) - train_window)])
            hist = df.loc[hist_mask]

            if len(hist) < 60:
                # Not enough history, keep previous weights
                pass
            else:
                vix_val = row["vix"]
                range_val = row["range_ratio"]
                corr_val = row["btc_spy_corr"]
                wknd_val = row["weekend_vol_ratio"]

                # --- Strategy 2: 12/VIX ---
                w_vix = min(max(12.0 / vix_val, 0.0), 2.0) if vix_val > 0 else 1.0
                current_weights["vix_12"] = w_vix

                # --- Strategy 3: Range-based VT ---
                # High range = high vol expected -> reduce position
                # Percentile of current range in historical distribution
                range_pct = stats.percentileofscore(hist["range_ratio"].dropna(), range_val) / 100.0
                # Inverse: low range -> high weight, high range -> low weight
                # Target vol = 15% annualized for BTC
                target_vol = 0.15
                hist_vol = hist["btc_ret"].std() * np.sqrt(365)
                range_scale = 1.0 - 0.5 * range_pct  # 0.5 to 1.0
                w_range = min(max(target_vol / hist_vol * range_scale, 0.0), 2.0) if hist_vol > 0 else 1.0
                current_weights["range_vt"] = w_range

                # --- Strategy 4: Corr-based VT ---
                # When BTC-SPY highly correlated (>0.5), BTC loses diversification -> reduce
                # When decoupled (corr < 0), BTC is a good diversifier -> increase
                corr_adjustment = 1.0 - 0.5 * max(corr_val, 0)  # 0.5 to 1.0 for positive corr
                if corr_val < 0:
                    corr_adjustment = 1.0 + 0.3 * abs(corr_val)  # 1.0 to 1.3 for negative corr
                w_corr = min(max(target_vol / hist_vol * corr_adjustment, 0.0), 2.0) if hist_vol > 0 else 1.0
                current_weights["corr_vt"] = w_corr

                # --- Strategy 5: Weekend vol VT ---
                # High weekend/weekday vol ratio signals microstructure stress
                # Reduce position when weekend vol elevated
                wknd_pct = stats.percentileofscore(hist["weekend_vol_ratio"].dropna(), wknd_val) / 100.0
                wknd_scale = 1.0 - 0.3 * wknd_pct  # 0.7 to 1.0
                w_wknd = min(max(target_vol / hist_vol * wknd_scale, 0.0), 2.0) if hist_vol > 0 else 1.0
                current_weights["weekend_vt"] = w_wknd

                # --- Strategy 6: Combined multi-factor VT ---
                # Equal-weight combination of three BTC-specific signals
                combined_scale = (range_scale + corr_adjustment + wknd_scale) / 3.0
                w_combined = min(max(target_vol / hist_vol * combined_scale, 0.0), 2.0) if hist_vol > 0 else 1.0
                current_weights["combined_vt"] = w_combined

        # Record returns: weight * BTC return + (1 - weight) * 0 (cash)
        for strat_name in strategies.keys():
            w = current_weights[strat_name]
            strat_ret = w * btc_ret_today
            strategies[strat_name].append(strat_ret)
            strategy_weights[strat_name].append(w)

        strategy_dates.append(date)

    # Compute metrics
    print("\n  Strategy Performance (OOS):")
    print("  " + "-" * 90)
    print(f"  {'Strategy':<20} {'Sharpe':>8} {'Sharpe_t':>9} {'AnnRet':>8} {'AnnVol':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8}")
    print("  " + "-" * 90)

    all_metrics = {}
    for strat_name, rets in strategies.items():
        metrics = compute_strategy_metrics(rets)
        all_metrics[strat_name] = metrics
        avg_w = np.mean(strategy_weights[strat_name])
        metrics["avg_weight"] = round(float(avg_w), 4)
        print(f"  {strat_name:<20} {metrics.get('sharpe',0):>8.4f} {metrics.get('sharpe_t',0):>9.4f} "
              f"{metrics.get('ann_return',0):>8.1%} {metrics.get('ann_vol',0):>8.1%} "
              f"{metrics.get('mdd',0):>8.1%} {metrics.get('calmar',0):>8.4f} "
              f"{metrics.get('sortino',0):>8.4f}  (avg_w={avg_w:.3f})")

    return {
        "strategies": all_metrics,
        "returns": {k: [float(x) for x in v] for k, v in strategies.items()},
        "weights": {k: [float(x) for x in v] for k, v in strategy_weights.items()},
        "dates": [d.strftime("%Y-%m-%d") for d in strategy_dates],
        "oos_start": oos_start,
        "oos_end": oos_end,
    }


# =============================================================================
# 5. STATISTICAL TESTS
# =============================================================================

def run_statistical_tests(strat_results):
    """
    DM test: compare each BTC-specific VT against baselines.
    """
    print("\n[5] Statistical tests (Diebold-Mariano)...")

    returns = strat_results["returns"]
    bh_rets = np.array(returns["buy_hold"])
    vix_rets = np.array(returns["vix_12"])

    # DM test: compare squared returns (volatility of strategy returns as loss)
    # Actually for VT strategies, we compare risk-adjusted returns
    # Use negative returns as "losses" for DM test
    # Or compare cumulative wealth
    # Standard approach: compare strategy excess returns

    comparisons = [
        ("range_vt", "buy_hold", "Range VT vs Buy-Hold"),
        ("corr_vt", "buy_hold", "Corr VT vs Buy-Hold"),
        ("weekend_vt", "buy_hold", "Weekend VT vs Buy-Hold"),
        ("combined_vt", "buy_hold", "Combined VT vs Buy-Hold"),
        ("range_vt", "vix_12", "Range VT vs 12/VIX"),
        ("corr_vt", "vix_12", "Corr VT vs 12/VIX"),
        ("weekend_vt", "vix_12", "Weekend VT vs 12/VIX"),
        ("combined_vt", "vix_12", "Combined VT vs 12/VIX"),
        ("vix_12", "buy_hold", "12/VIX vs Buy-Hold"),
    ]

    dm_results = {}
    print(f"\n  {'Comparison':<30} {'DM t-stat':>10} {'p-value':>10} {'Significant':>12} {'Harvey':>8}")
    print("  " + "-" * 75)

    for strat1, strat2, label in comparisons:
        r1 = np.array(returns[strat1])
        r2 = np.array(returns[strat2])
        # DM test on squared (negative) returns = comparing risk
        # Positive t-stat means strat1 has HIGHER squared loss (worse)
        # We test: does strat1 have different risk-adjusted return?
        t_stat, p_val = diebold_mariano_test(-r1, -r2)

        sig = "Yes" if (p_val is not np.nan and p_val < 0.05) else "No"
        harvey = "PASS" if (t_stat is not np.nan and abs(t_stat) > 3.0) else "FAIL"

        dm_results[label] = {
            "t_stat": round(float(t_stat), 4) if not np.isnan(t_stat) else None,
            "p_value": round(float(p_val), 6) if not np.isnan(p_val) else None,
            "significant_5pct": sig == "Yes",
            "passes_harvey": harvey == "PASS",
        }

        t_str = f"{t_stat:.4f}" if not np.isnan(t_stat) else "N/A"
        p_str = f"{p_val:.6f}" if not np.isnan(p_val) else "N/A"
        print(f"  {label:<30} {t_str:>10} {p_str:>10} {sig:>12} {harvey:>8}")

    # Bootstrap test on MDD difference
    print("\n  Bootstrap MDD comparison (10,000 reps):")
    n_boot = 10000
    mdd_comparisons = [
        ("combined_vt", "buy_hold", "Combined VT vs Buy-Hold MDD"),
        ("vix_12", "buy_hold", "12/VIX vs Buy-Hold MDD"),
        ("combined_vt", "vix_12", "Combined VT vs 12/VIX MDD"),
    ]

    for strat1, strat2, label in mdd_comparisons:
        r1 = np.array(returns[strat1])
        r2 = np.array(returns[strat2])
        n = len(r1)

        mdd_diffs = []
        rng = np.random.RandomState(42)
        for _ in range(n_boot):
            idx = rng.choice(n, size=n, replace=True)
            boot_r1 = r1[idx]
            boot_r2 = r2[idx]

            cum1 = np.cumprod(1 + boot_r1)
            mdd1 = np.min(cum1 / np.maximum.accumulate(cum1) - 1)

            cum2 = np.cumprod(1 + boot_r2)
            mdd2 = np.min(cum2 / np.maximum.accumulate(cum2) - 1)

            mdd_diffs.append(mdd1 - mdd2)  # negative means strat1 has smaller MDD

        mdd_diffs = np.array(mdd_diffs)
        p_mdd = np.mean(mdd_diffs > 0)  # proportion where strat1 has worse MDD

        dm_results[f"{label} (bootstrap)"] = {
            "mean_mdd_diff": round(float(np.mean(mdd_diffs)), 4),
            "p_value": round(float(p_mdd), 4),
            "strat1_better_pct": round(float(1 - p_mdd), 4),
        }
        print(f"  {label}: mean diff = {np.mean(mdd_diffs):.4f}, "
              f"p(strat1 worse MDD) = {p_mdd:.4f}, "
              f"strat1 better {(1-p_mdd)*100:.1f}% of time")

    return dm_results


# =============================================================================
# 6. WEEKEND EFFECT DEEP-DIVE
# =============================================================================

def weekend_effect_analysis(df):
    """
    Characterize the BTC weekend effect:
    - Weekend vs weekday returns
    - Weekend vs weekday volatility
    - Time evolution of weekend effect
    """
    print("\n[6] Weekend Effect Deep-Dive...")

    weekend_mask = df.index.dayofweek.isin([5, 6])
    weekday_mask = ~weekend_mask

    wknd_rets = df.loc[weekend_mask, "btc_ret"]
    wkdy_rets = df.loc[weekday_mask, "btc_ret"]

    print(f"\n  Full sample weekend analysis:")
    print(f"  Weekend days: {len(wknd_rets)}, Weekday days: {len(wkdy_rets)}")
    print(f"  Weekend mean return: {wknd_rets.mean()*365:.2%} ann.")
    print(f"  Weekday mean return: {wkdy_rets.mean()*365:.2%} ann.")
    print(f"  Weekend volatility: {wknd_rets.std()*np.sqrt(365):.2%} ann.")
    print(f"  Weekday volatility: {wkdy_rets.std()*np.sqrt(365):.2%} ann.")
    print(f"  Vol ratio (weekend/weekday): {wknd_rets.std()/wkdy_rets.std():.3f}")

    # t-test for mean difference
    t_mean, p_mean = stats.ttest_ind(wknd_rets, wkdy_rets)
    print(f"  Mean diff t-test: t={t_mean:.4f}, p={p_mean:.4f}")

    # Levene test for variance difference
    lev_stat, lev_p = stats.levene(wknd_rets, wkdy_rets)
    print(f"  Variance diff (Levene): F={lev_stat:.4f}, p={lev_p:.4f}")

    # Year-by-year breakdown
    print(f"\n  Year-by-year weekend vol ratio:")
    yearly_results = {}
    for year in sorted(df.index.year.unique()):
        yr_mask = df.index.year == year
        yr_wknd = df.loc[yr_mask & weekend_mask, "btc_ret"]
        yr_wkdy = df.loc[yr_mask & weekday_mask, "btc_ret"]
        if len(yr_wknd) > 10 and len(yr_wkdy) > 10:
            ratio = yr_wknd.std() / yr_wkdy.std()
            yearly_results[str(year)] = round(float(ratio), 3)
            print(f"    {year}: vol ratio = {ratio:.3f} "
                  f"(wknd vol={yr_wknd.std()*np.sqrt(365):.1%}, "
                  f"wkdy vol={yr_wkdy.std()*np.sqrt(365):.1%})")

    return {
        "weekend_mean_return_ann": round(float(wknd_rets.mean() * 365), 4),
        "weekday_mean_return_ann": round(float(wkdy_rets.mean() * 365), 4),
        "weekend_vol_ann": round(float(wknd_rets.std() * np.sqrt(365)), 4),
        "weekday_vol_ann": round(float(wkdy_rets.std() * np.sqrt(365)), 4),
        "vol_ratio": round(float(wknd_rets.std() / wkdy_rets.std()), 4),
        "mean_diff_t": round(float(t_mean), 4),
        "mean_diff_p": round(float(p_mean), 4),
        "levene_F": round(float(lev_stat), 4),
        "levene_p": round(float(lev_p), 4),
        "yearly_vol_ratios": yearly_results,
    }


# =============================================================================
# 7. CROSS-OOS ROBUSTNESS
# =============================================================================

def cross_oos_robustness(df, train_window=252):
    """
    Test across multiple OOS periods to avoid single-period luck.
    """
    print("\n[7] Cross-OOS Robustness (5 periods)...")

    oos_periods = [
        ("2020-01-01", "2020-12-31", "2020 (COVID)"),
        ("2021-01-01", "2021-12-31", "2021 (Bull)"),
        ("2022-01-01", "2022-12-31", "2022 (Bear)"),
        ("2023-01-01", "2023-12-31", "2023 (Recovery)"),
        ("2024-01-01", "2024-12-31", "2024 (Recent)"),
    ]

    cross_results = {}

    print(f"\n  {'Period':<20} {'BH Sharpe':>10} {'VIX Sharpe':>10} {'Combined Sharpe':>15} "
          f"{'BH MDD':>8} {'VIX MDD':>8} {'Comb MDD':>9}")
    print("  " + "-" * 85)

    for oos_start, oos_end, label in oos_periods:
        strat_res = run_vt_strategies_quiet(df, oos_start, oos_end, train_window)
        if strat_res is None:
            print(f"  {label:<20} SKIPPED (insufficient data)")
            continue

        bh_m = strat_res["strategies"].get("buy_hold", {})
        vix_m = strat_res["strategies"].get("vix_12", {})
        comb_m = strat_res["strategies"].get("combined_vt", {})

        cross_results[label] = {
            "buy_hold": bh_m,
            "vix_12": vix_m,
            "combined_vt": comb_m,
        }

        print(f"  {label:<20} {bh_m.get('sharpe',0):>10.4f} {vix_m.get('sharpe',0):>10.4f} "
              f"{comb_m.get('sharpe',0):>15.4f} "
              f"{bh_m.get('mdd',0):>8.1%} {vix_m.get('mdd',0):>8.1%} "
              f"{comb_m.get('mdd',0):>9.1%}")

    # Count wins
    combined_sharpe_wins = 0
    combined_mdd_wins = 0
    vix_sharpe_wins = 0
    vix_mdd_wins = 0
    n_periods = 0

    for label, res in cross_results.items():
        n_periods += 1
        bh_s = res["buy_hold"].get("sharpe", 0)
        vix_s = res["vix_12"].get("sharpe", 0)
        comb_s = res["combined_vt"].get("sharpe", 0)
        bh_m = res["buy_hold"].get("mdd", 0)
        vix_m = res["vix_12"].get("mdd", 0)
        comb_m = res["combined_vt"].get("mdd", 0)

        if comb_s > bh_s:
            combined_sharpe_wins += 1
        if comb_m > bh_m:  # less negative = better
            combined_mdd_wins += 1
        if vix_s > bh_s:
            vix_sharpe_wins += 1
        if vix_m > bh_m:
            vix_mdd_wins += 1

    print(f"\n  Cross-OOS Summary ({n_periods} periods):")
    print(f"    Combined VT Sharpe > BH: {combined_sharpe_wins}/{n_periods}")
    print(f"    Combined VT MDD > BH:    {combined_mdd_wins}/{n_periods}")
    print(f"    12/VIX Sharpe > BH:      {vix_sharpe_wins}/{n_periods}")
    print(f"    12/VIX MDD > BH:         {vix_mdd_wins}/{n_periods}")

    cross_results["summary"] = {
        "n_periods": n_periods,
        "combined_sharpe_wins_vs_bh": combined_sharpe_wins,
        "combined_mdd_wins_vs_bh": combined_mdd_wins,
        "vix_sharpe_wins_vs_bh": vix_sharpe_wins,
        "vix_mdd_wins_vs_bh": vix_mdd_wins,
    }

    return cross_results


def run_vt_strategies_quiet(df, oos_start, oos_end, train_window=252):
    """Same as run_vt_strategies but without printing."""
    oos_mask = (df.index >= oos_start) & (df.index <= oos_end)
    oos_df = df[oos_mask].copy()

    if len(oos_df) < 30:
        return None

    oos_df["month"] = oos_df.index.to_period("M")
    target_vol = 0.15

    strategies = {
        "buy_hold": [],
        "vix_12": [],
        "range_vt": [],
        "corr_vt": [],
        "weekend_vt": [],
        "combined_vt": [],
    }
    strategy_weights = {k: [] for k in strategies.keys()}

    current_weights = {k: 1.0 for k in strategies.keys()}
    prev_month = None

    for i, (date, row) in enumerate(oos_df.iterrows()):
        btc_ret_today = row["btc_ret"]
        cur_month = row["month"]

        if cur_month != prev_month:
            prev_month = cur_month

            loc_idx = df.index.get_loc(date)
            start_idx = max(0, loc_idx - train_window)
            hist = df.iloc[start_idx:loc_idx]

            if len(hist) < 60:
                pass
            else:
                vix_val = row["vix"]
                range_val = row["range_ratio"]
                corr_val = row["btc_spy_corr"]
                wknd_val = row["weekend_vol_ratio"]
                hist_vol = hist["btc_ret"].std() * np.sqrt(365)

                w_vix = min(max(12.0 / vix_val, 0.0), 2.0) if vix_val > 0 else 1.0
                current_weights["vix_12"] = w_vix

                range_pct = stats.percentileofscore(hist["range_ratio"].dropna(), range_val) / 100.0
                range_scale = 1.0 - 0.5 * range_pct
                w_range = min(max(target_vol / hist_vol * range_scale, 0.0), 2.0) if hist_vol > 0 else 1.0
                current_weights["range_vt"] = w_range

                corr_adjustment = 1.0 - 0.5 * max(corr_val, 0)
                if corr_val < 0:
                    corr_adjustment = 1.0 + 0.3 * abs(corr_val)
                w_corr = min(max(target_vol / hist_vol * corr_adjustment, 0.0), 2.0) if hist_vol > 0 else 1.0
                current_weights["corr_vt"] = w_corr

                wknd_pct = stats.percentileofscore(hist["weekend_vol_ratio"].dropna(), wknd_val) / 100.0
                wknd_scale = 1.0 - 0.3 * wknd_pct
                w_wknd = min(max(target_vol / hist_vol * wknd_scale, 0.0), 2.0) if hist_vol > 0 else 1.0
                current_weights["weekend_vt"] = w_wknd

                combined_scale = (range_scale + corr_adjustment + wknd_scale) / 3.0
                w_combined = min(max(target_vol / hist_vol * combined_scale, 0.0), 2.0) if hist_vol > 0 else 1.0
                current_weights["combined_vt"] = w_combined

        for strat_name in strategies.keys():
            w = current_weights[strat_name]
            strategies[strat_name].append(w * btc_ret_today)
            strategy_weights[strat_name].append(w)

    all_metrics = {}
    for strat_name, rets in strategies.items():
        metrics = compute_strategy_metrics(rets)
        metrics["avg_weight"] = round(float(np.mean(strategy_weights[strat_name])), 4)
        all_metrics[strat_name] = metrics

    return {"strategies": all_metrics, "returns": {k: v for k, v in strategies.items()}}


# =============================================================================
# 8. MAIN
# =============================================================================

def main():
    start_time = datetime.now()

    # 1. Load data
    data = load_data()

    # 2. Compute features
    df = compute_features(data)

    # 3. Feature predictiveness
    pred_results = analyze_feature_predictiveness(df)

    # 4. Run VT strategies (primary OOS: 2023-2024)
    strat_results = run_vt_strategies(df, oos_start="2023-01-01", oos_end="2024-12-31")

    # 5. Statistical tests
    dm_results = run_statistical_tests(strat_results)

    # 6. Weekend effect deep-dive
    weekend_results = weekend_effect_analysis(df)

    # 7. Cross-OOS robustness
    cross_oos = cross_oos_robustness(df)

    # 8. Summary
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n{'='*70}")
    print(f"K205 SUMMARY")
    print(f"{'='*70}")

    primary_metrics = strat_results["strategies"]
    print(f"\n  Primary OOS (2023-2024) Sharpe Ranking:")
    sorted_strats = sorted(primary_metrics.items(), key=lambda x: x[1].get("sharpe", 0), reverse=True)
    for i, (name, m) in enumerate(sorted_strats, 1):
        harvey_pass = "PASS" if m.get("sharpe_t", 0) > 3.0 else "FAIL"
        print(f"    {i}. {name:<20} Sharpe={m.get('sharpe',0):.4f} (t={m.get('sharpe_t',0):.2f}, Harvey {harvey_pass})")

    # Key findings
    best_micro = None
    best_micro_sharpe = -999
    for name in ["range_vt", "corr_vt", "weekend_vt", "combined_vt"]:
        s = primary_metrics[name].get("sharpe", 0)
        if s > best_micro_sharpe:
            best_micro_sharpe = s
            best_micro = name

    bh_sharpe = primary_metrics["buy_hold"].get("sharpe", 0)
    vix_sharpe = primary_metrics["vix_12"].get("sharpe", 0)
    comb_sharpe = primary_metrics["combined_vt"].get("sharpe", 0)

    print(f"\n  Key Findings:")
    print(f"    Best microstructure VT: {best_micro} (Sharpe={best_micro_sharpe:.4f})")
    print(f"    vs Buy-Hold: {'BETTER' if best_micro_sharpe > bh_sharpe else 'WORSE'} "
          f"({best_micro_sharpe:.4f} vs {bh_sharpe:.4f})")
    print(f"    vs 12/VIX: {'BETTER' if best_micro_sharpe > vix_sharpe else 'WORSE'} "
          f"({best_micro_sharpe:.4f} vs {vix_sharpe:.4f})")

    # Cross-OOS summary
    if "summary" in cross_oos:
        s = cross_oos["summary"]
        print(f"\n    Cross-OOS ({s['n_periods']} periods):")
        print(f"      Combined VT > BH Sharpe: {s['combined_sharpe_wins_vs_bh']}/{s['n_periods']}")
        print(f"      Combined VT > BH MDD:    {s['combined_mdd_wins_vs_bh']}/{s['n_periods']}")

    # Weekend effect
    print(f"\n    Weekend Effect:")
    print(f"      Vol ratio (weekend/weekday): {weekend_results['vol_ratio']:.3f}")
    print(f"      Levene test p-value: {weekend_results['levene_p']:.4f}")

    print(f"\n  Elapsed: {elapsed:.1f}s")

    # Save results
    all_results = {
        "experiment": "K205",
        "title": "BTC Weekend Volatility and Microstructure-Based VT",
        "attribution": "[提出: 用戶, 執行: Claude]",
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "data_source": "yfinance (BTC-USD, SPY, ^VIX)",
        "oos_period": "2023-01-01 to 2024-12-31",
        "methodology": {
            "rebalance": "monthly",
            "train_window": 252,
            "target_vol": "15% annualized",
            "weight_cap": 2.0,
            "features": ["range_ratio (22d)", "btc_spy_corr (252d)", "weekend_vol_ratio (66d)"],
        },
        "feature_predictiveness": pred_results,
        "primary_oos_strategies": primary_metrics,
        "statistical_tests": dm_results,
        "weekend_effect": weekend_results,
        "cross_oos": cross_oos,
        "conclusions": {
            "best_microstructure_vt": best_micro,
            "best_micro_sharpe": round(best_micro_sharpe, 4),
            "beats_buy_hold": best_micro_sharpe > bh_sharpe,
            "beats_12_vix": best_micro_sharpe > vix_sharpe,
            "combined_vt_sharpe": round(comb_sharpe, 4),
            "harvey_threshold_met": any(
                primary_metrics[s].get("sharpe_t", 0) > 3.0
                for s in ["range_vt", "corr_vt", "weekend_vt", "combined_vt"]
            ),
        },
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
