"""K680: Cross-OOS Validation of VIX Percentile Strategy (K679)

Motivation:
  K679 found VIX percentile-based strategy (w = 1 - VIX_percentile_252d)
  with Sharpe 1.68 vs 12/VIX 1.08 (t=3.375, Harvey PASS). This is potentially
  the biggest strategy innovation in the research program. But per K459's lesson
  (53% false positive rate without cross-OOS), we MUST validate across multiple
  non-overlapping periods before considering this as a real improvement.

Cross-OOS Design:
  5 non-overlapping OOS periods, each >= 2 years:
    OOS1: 2008-01 to 2009-12 (GFC)
    OOS2: 2011-01 to 2013-12 (post-GFC recovery)
    OOS3: 2015-01 to 2017-12 (low vol bull)
    OOS4: 2020-01 to 2021-12 (COVID + recovery)
    OOS5: 2023-01 to 2024-12 (post-hike normalization)

  For each period: Sharpe, MDD, DM test, daily win rate.
  Robustness: Must win >= 4/5 on Sharpe, avg improvement > 0, no catastrophic loss.

Sensitivity:
  Percentile window: 126d, 252d, 504d

Bootstrap: 5000 reps full-sample Sharpe difference CI

Strategies:
  a. 12/VIX (baseline): w = min(12/VIX, 1.0) applied to 50/50 SPY/GLD
  b. Percentile: w = 1 - percentile(VIX, rolling window) applied to 50/50 SPY/GLD

References:
  - K679: VIX Percentile-Based Strategy (Sharpe 1.68 vs 1.08)
  - K459: Weekly VRP Cross-OOS (53% false positive lesson)
  - K474/K476: Cross-OOS validation methodology
  - Copeland & Copeland (1999), Market Timing with VIX
  - Harvey et al. (2016), t > 3.0 threshold for multiple testing

Data source: yfinance (SPY, GLD, ^VIX)
Period: 2006-01-01 to 2026-03-27

Author: VolPred Research System
Date: 2026-03-28
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
START_DATE = "2006-01-01"
END_DATE = "2026-03-27"
WARMUP_DAYS = 504  # Max rolling window we test (504d needs 504d warmup)
TC_BPS = 5         # Transaction cost in basis points (one-way)
RF_DAILY = 0.04 / 252  # ~4% annual risk-free for cash portion
RF_ANNUAL = 0.04
BOOTSTRAP_REPS = 5000
ROLLING_WINDOWS = [126, 252, 504]  # Sensitivity analysis windows

# 5 non-overlapping OOS periods
OOS_PERIODS = {
    "OOS1_GFC": ("2008-01-02", "2009-12-31"),
    "OOS2_Recovery": ("2011-01-03", "2013-12-31"),
    "OOS3_LowVol": ("2015-01-02", "2017-12-29"),
    "OOS4_COVID": ("2020-01-02", "2021-12-31"),
    "OOS5_PostHike": ("2023-01-03", "2024-12-31"),
}


def download_data():
    """Download SPY, GLD, VIX data."""
    print("Downloading SPY, GLD, ^VIX data...")
    spy = yf.download("SPY", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    gld = yf.download("GLD", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)

    # Handle MultiIndex columns from newer yfinance
    for df in [spy, gld, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    spy_ret = spy["Close"].pct_change().dropna()
    spy_ret.name = "spy_ret"
    gld_ret = gld["Close"].pct_change().dropna()
    gld_ret.name = "gld_ret"
    vix_close = vix["Close"].copy()
    vix_close.name = "vix"

    data = pd.concat([spy_ret, gld_ret, vix_close], axis=1).dropna()
    print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}, {len(data)} days")
    return data


def compute_rolling_percentile(vix_series, window):
    """Compute rolling percentile rank of VIX using vectorized approach."""
    vals = vix_series.values
    n = len(vals)
    result = np.full(n, np.nan)

    for i in range(window, n):
        window_vals = vals[i - window:i]
        # percentileofscore: percentage of values <= current value
        result[i] = sp_stats.percentileofscore(window_vals, vals[i]) / 100.0

    return pd.Series(result, index=vix_series.index, name=f"pct_{window}")


def compute_strategy_returns(data, weight_col_or_array, spy_ret_col="spy_ret",
                              gld_ret_col="gld_ret", tc_bps=TC_BPS):
    """Compute strategy daily returns with transaction costs.

    Returns numpy array of daily strategy returns (same length as data).
    """
    if isinstance(weight_col_or_array, str):
        weights = data[weight_col_or_array].values.copy()
    else:
        weights = np.asarray(weight_col_or_array).copy()

    spy_ret = data[spy_ret_col].values
    gld_ret = data[gld_ret_col].values
    portfolio_ret = 0.5 * spy_ret + 0.5 * gld_ret

    tc_rate = tc_bps / 10000.0
    strategy_ret = np.zeros(len(data))
    prev_w = 0.0

    for i in range(len(data)):
        w = weights[i]
        if np.isnan(w):
            w = prev_w
        tc = abs(w - prev_w) * tc_rate
        strategy_ret[i] = w * portfolio_ret[i] + (1 - w) * RF_DAILY - tc
        prev_w = w

    return strategy_ret


def compute_period_metrics(returns, n_days=None):
    """Compute Sharpe, MDD, CAGR, Sortino for a return series."""
    if n_days is None:
        n_days = len(returns)

    if len(returns) < 10:
        return None

    ann_ret = np.mean(returns) * 252
    ann_vol = np.std(returns, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0.0

    # Max drawdown
    cum = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cum)
    drawdowns = (cum - running_max) / running_max
    mdd = float(np.min(drawdowns))

    # CAGR
    total_ret = cum[-1] - 1
    n_years = n_days / 252.0
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    # Sortino
    downside = returns[returns < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = (ann_ret - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0

    # Calmar
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    return {
        "sharpe": round(sharpe, 4),
        "mdd_pct": round(mdd * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "ann_ret_pct": round(ann_ret * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "n_days": n_days,
    }


def dm_test(returns_1, returns_2, h=1):
    """Diebold-Mariano test on return differences.

    Tests H0: E[d_t] = 0 where d_t = r_{1,t} - r_{2,t}
    Positive t-stat means strategy 1 > strategy 2.

    Uses Newey-West HAC standard errors for robustness.
    """
    d = returns_1 - returns_2
    n = len(d)

    if n < 30:
        return {"t_stat": np.nan, "p_value": np.nan, "mean_diff_bps": np.nan}

    mean_d = np.mean(d)

    # Newey-West HAC variance (bandwidth = int(n^(1/3)))
    bandwidth = max(1, int(n ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    nw_var = gamma_0

    for k in range(1, bandwidth + 1):
        gamma_k = np.mean((d[k:] - mean_d) * (d[:-k] - mean_d))
        weight = 1 - k / (bandwidth + 1)  # Bartlett kernel
        nw_var += 2 * weight * gamma_k

    se = np.sqrt(nw_var / n)
    t_stat = mean_d / se if se > 0 else 0
    p_value = 2 * sp_stats.t.sf(abs(t_stat), df=n - 1)

    return {
        "t_stat": round(float(t_stat), 4),
        "p_value": round(float(p_value), 6),
        "mean_diff_bps": round(float(mean_d * 10000), 4),
        "n_obs": n,
        "nw_bandwidth": bandwidth,
        "harvey_pass": abs(t_stat) > 3.0,
    }


def bootstrap_sharpe_diff(returns_pct, returns_base, n_reps=BOOTSTRAP_REPS):
    """Bootstrap confidence interval for Sharpe difference.

    Returns: mean diff, CI_lower, CI_upper, p_value (two-sided)
    """
    n = len(returns_pct)
    diff_sharpes = np.zeros(n_reps)

    for b in range(n_reps):
        idx = np.random.randint(0, n, size=n)
        r_pct = returns_pct[idx]
        r_base = returns_base[idx]

        s_pct = (np.mean(r_pct) * 252 - RF_ANNUAL) / (np.std(r_pct, ddof=1) * np.sqrt(252)) \
            if np.std(r_pct, ddof=1) > 0 else 0
        s_base = (np.mean(r_base) * 252 - RF_ANNUAL) / (np.std(r_base, ddof=1) * np.sqrt(252)) \
            if np.std(r_base, ddof=1) > 0 else 0

        diff_sharpes[b] = s_pct - s_base

    mean_diff = float(np.mean(diff_sharpes))
    ci_lower = float(np.percentile(diff_sharpes, 2.5))
    ci_upper = float(np.percentile(diff_sharpes, 97.5))
    # Two-sided p-value: proportion of bootstraps where diff <= 0
    p_value = float(np.mean(diff_sharpes <= 0))

    return {
        "mean_sharpe_diff": round(mean_diff, 4),
        "ci_95_lower": round(ci_lower, 4),
        "ci_95_upper": round(ci_upper, 4),
        "p_value": round(min(p_value, 1 - p_value) * 2, 6),  # Two-sided
        "ci_excludes_zero": ci_lower > 0 or ci_upper < 0,
        "n_reps": n_reps,
    }


def run_cross_oos(data, percentile_window=252):
    """Run cross-OOS validation for a given percentile window.

    Returns dict with per-period and aggregate results.
    """
    print(f"\n{'='*70}")
    print(f"Cross-OOS Validation — Percentile Window = {percentile_window}d")
    print(f"{'='*70}")

    # Compute rolling percentile for this window
    vix_pct = compute_rolling_percentile(data["vix"], percentile_window)
    data_with_pct = data.copy()
    data_with_pct["vix_percentile"] = vix_pct

    # Compute weights
    # Percentile strategy: w = 1 - percentile
    data_with_pct["w_percentile"] = 1.0 - data_with_pct["vix_percentile"]
    # 12/VIX baseline: w = min(12/VIX, 1.0)
    data_with_pct["w_12vix"] = np.minimum(12.0 / data_with_pct["vix"], 1.0)

    # Compute full-sample strategy returns (for bootstrap later)
    # Need to compute returns for the full valid period
    valid_mask = data_with_pct["vix_percentile"].notna()
    data_valid = data_with_pct[valid_mask].copy()

    full_ret_pct = compute_strategy_returns(data_valid, "w_percentile")
    full_ret_12vix = compute_strategy_returns(data_valid, "w_12vix")

    period_results = {}
    sharpe_wins = 0
    sharpe_diffs = []

    for period_name, (start, end) in OOS_PERIODS.items():
        print(f"\n--- {period_name}: {start} to {end} ---")

        # Filter to this OOS period
        mask = (data_with_pct.index >= start) & (data_with_pct.index <= end)
        period_data = data_with_pct[mask].copy()

        # Check if we have valid percentile data
        valid_pct = period_data["vix_percentile"].notna()
        period_data = period_data[valid_pct]

        if len(period_data) < 50:
            print(f"  WARNING: Only {len(period_data)} valid days, skipping")
            period_results[period_name] = {"error": f"Too few valid days: {len(period_data)}"}
            continue

        print(f"  {len(period_data)} trading days")
        print(f"  VIX: mean={period_data['vix'].mean():.2f}, "
              f"min={period_data['vix'].min():.2f}, max={period_data['vix'].max():.2f}")

        # Compute returns for this period
        ret_pct = compute_strategy_returns(period_data, "w_percentile")
        ret_12vix = compute_strategy_returns(period_data, "w_12vix")

        # Compute metrics
        metrics_pct = compute_period_metrics(ret_pct)
        metrics_12vix = compute_period_metrics(ret_12vix)

        if metrics_pct is None or metrics_12vix is None:
            print(f"  ERROR: Could not compute metrics")
            period_results[period_name] = {"error": "Metrics computation failed"}
            continue

        # DM test
        dm = dm_test(ret_pct, ret_12vix)

        # Daily win rate: % of days where Percentile return > 12/VIX return
        daily_diff = ret_pct - ret_12vix
        win_rate = float(np.mean(daily_diff > 0))

        # Average weight comparison
        avg_w_pct = float(period_data["w_percentile"].mean())
        avg_w_12vix = float(period_data["w_12vix"].mean())

        sharpe_diff = metrics_pct["sharpe"] - metrics_12vix["sharpe"]
        sharpe_diffs.append(sharpe_diff)

        if sharpe_diff > 0:
            sharpe_wins += 1

        period_result = {
            "start": start,
            "end": end,
            "n_days": len(period_data),
            "vix_stats": {
                "mean": round(float(period_data["vix"].mean()), 2),
                "std": round(float(period_data["vix"].std()), 2),
                "min": round(float(period_data["vix"].min()), 2),
                "max": round(float(period_data["vix"].max()), 2),
            },
            "percentile_strategy": metrics_pct,
            "baseline_12vix": metrics_12vix,
            "sharpe_diff": round(sharpe_diff, 4),
            "percentile_wins_sharpe": sharpe_diff > 0,
            "dm_test": dm,
            "daily_win_rate": round(win_rate, 4),
            "avg_weight_percentile": round(avg_w_pct, 4),
            "avg_weight_12vix": round(avg_w_12vix, 4),
        }

        period_results[period_name] = period_result

        # Print summary
        print(f"  Percentile:  Sharpe={metrics_pct['sharpe']:.4f}, "
              f"MDD={metrics_pct['mdd_pct']:.2f}%, CAGR={metrics_pct['cagr_pct']:.2f}%")
        print(f"  12/VIX:      Sharpe={metrics_12vix['sharpe']:.4f}, "
              f"MDD={metrics_12vix['mdd_pct']:.2f}%, CAGR={metrics_12vix['cagr_pct']:.2f}%")
        print(f"  Sharpe diff: {sharpe_diff:+.4f} "
              f"{'WIN' if sharpe_diff > 0 else 'LOSS'}")
        print(f"  DM test: t={dm['t_stat']:.4f}, p={dm['p_value']:.6f} "
              f"{'HARVEY PASS' if dm['harvey_pass'] else ''}")
        print(f"  Win rate: {win_rate:.1%}")
        print(f"  Avg weight: Pct={avg_w_pct:.3f}, 12/VIX={avg_w_12vix:.3f}")

    # Aggregate results
    n_periods = len([p for p in period_results.values() if "error" not in p])
    avg_sharpe_diff = float(np.mean(sharpe_diffs)) if sharpe_diffs else 0
    min_sharpe_diff = float(np.min(sharpe_diffs)) if sharpe_diffs else 0
    max_sharpe_diff = float(np.max(sharpe_diffs)) if sharpe_diffs else 0

    # Check robustness criteria
    passes_win_rate = sharpe_wins >= 4  # Must win >= 4/5
    passes_avg_diff = avg_sharpe_diff > 0  # Avg improvement > 0
    passes_no_catastrophe = min_sharpe_diff > -0.5  # No catastrophic underperformance
    overall_pass = passes_win_rate and passes_avg_diff and passes_no_catastrophe

    aggregate = {
        "percentile_window": percentile_window,
        "n_oos_periods": n_periods,
        "sharpe_wins": sharpe_wins,
        "sharpe_losses": n_periods - sharpe_wins,
        "avg_sharpe_diff": round(avg_sharpe_diff, 4),
        "min_sharpe_diff": round(min_sharpe_diff, 4),
        "max_sharpe_diff": round(max_sharpe_diff, 4),
        "robustness_criteria": {
            "win_rate_4of5": passes_win_rate,
            "avg_improvement_positive": passes_avg_diff,
            "no_catastrophic_loss": passes_no_catastrophe,
            "OVERALL_PASS": overall_pass,
        },
    }

    print(f"\n{'='*70}")
    print(f"AGGREGATE — Window={percentile_window}d")
    print(f"{'='*70}")
    print(f"  Sharpe wins: {sharpe_wins}/{n_periods}")
    print(f"  Avg Sharpe diff: {avg_sharpe_diff:+.4f}")
    print(f"  Min Sharpe diff: {min_sharpe_diff:+.4f}")
    print(f"  Max Sharpe diff: {max_sharpe_diff:+.4f}")
    print(f"  Win rate >= 4/5: {'PASS' if passes_win_rate else 'FAIL'}")
    print(f"  Avg diff > 0:    {'PASS' if passes_avg_diff else 'FAIL'}")
    print(f"  No catastrophe:  {'PASS' if passes_no_catastrophe else 'FAIL'}")
    print(f"  OVERALL: {'*** PASS ***' if overall_pass else '--- FAIL ---'}")

    return {
        "periods": period_results,
        "aggregate": aggregate,
        "full_ret_pct": full_ret_pct,
        "full_ret_12vix": full_ret_12vix,
    }


def sensitivity_analysis(data):
    """Test percentile window sensitivity: 126d, 252d, 504d."""
    print("\n" + "=" * 70)
    print("SENSITIVITY ANALYSIS: Percentile Window")
    print("=" * 70)

    all_results = {}
    for window in ROLLING_WINDOWS:
        result = run_cross_oos(data, percentile_window=window)
        all_results[window] = {
            "periods": result["periods"],
            "aggregate": result["aggregate"],
        }

        # Store full-sample returns for 252d (default) bootstrap
        if window == 252:
            all_results["_full_ret_pct_252"] = result["full_ret_pct"]
            all_results["_full_ret_12vix_252"] = result["full_ret_12vix"]

    # Compare across windows
    print("\n" + "=" * 70)
    print("WINDOW COMPARISON SUMMARY")
    print("=" * 70)
    print(f"{'Window':>8} | {'Wins':>5} | {'Avg Diff':>10} | {'Min Diff':>10} | {'PASS':>6}")
    print("-" * 55)
    for w in ROLLING_WINDOWS:
        agg = all_results[w]["aggregate"]
        print(f"{w:>6}d | {agg['sharpe_wins']:>3}/{agg['n_oos_periods']} | "
              f"{agg['avg_sharpe_diff']:>+10.4f} | {agg['min_sharpe_diff']:>+10.4f} | "
              f"{'PASS' if agg['robustness_criteria']['OVERALL_PASS'] else 'FAIL':>6}")

    return all_results


def run_bootstrap(ret_pct, ret_12vix):
    """Run bootstrap test on full-sample Sharpe difference."""
    print("\n" + "=" * 70)
    print(f"BOOTSTRAP: {BOOTSTRAP_REPS} reps, Full Sample Sharpe Difference")
    print("=" * 70)

    np.random.seed(42)
    result = bootstrap_sharpe_diff(ret_pct, ret_12vix, n_reps=BOOTSTRAP_REPS)

    print(f"  Mean Sharpe diff: {result['mean_sharpe_diff']:+.4f}")
    print(f"  95% CI: [{result['ci_95_lower']:+.4f}, {result['ci_95_upper']:+.4f}]")
    print(f"  CI excludes zero: {result['ci_excludes_zero']}")
    print(f"  p-value (two-sided): {result['p_value']:.6f}")

    return result


def run_full_sample_dm(ret_pct, ret_12vix):
    """Run full-sample DM test with HAC standard errors."""
    print("\n" + "=" * 70)
    print("FULL-SAMPLE DM TEST (Newey-West HAC)")
    print("=" * 70)

    dm = dm_test(ret_pct, ret_12vix)

    print(f"  t-stat: {dm['t_stat']:.4f}")
    print(f"  p-value: {dm['p_value']:.6f}")
    print(f"  Mean diff: {dm['mean_diff_bps']:.4f} bps/day")
    print(f"  NW bandwidth: {dm['nw_bandwidth']}")
    print(f"  Harvey (2016) t>3.0: {'PASS' if dm['harvey_pass'] else 'FAIL'}")

    return dm


def rolling_sharpe_comparison(data, window=252):
    """Compute rolling Sharpe for both strategies to visualize consistency."""
    print("\n--- Rolling Sharpe Comparison ---")

    vix_pct = compute_rolling_percentile(data["vix"], window)
    data_with_pct = data.copy()
    data_with_pct["vix_percentile"] = vix_pct
    data_with_pct["w_percentile"] = 1.0 - data_with_pct["vix_percentile"]
    data_with_pct["w_12vix"] = np.minimum(12.0 / data_with_pct["vix"], 1.0)

    valid_mask = data_with_pct["vix_percentile"].notna()
    data_valid = data_with_pct[valid_mask].copy()

    ret_pct = compute_strategy_returns(data_valid, "w_percentile")
    ret_12vix = compute_strategy_returns(data_valid, "w_12vix")

    # Rolling 252-day Sharpe
    roll_sharpe_pct = []
    roll_sharpe_12vix = []
    roll_dates = []

    for i in range(252, len(ret_pct)):
        r_pct = ret_pct[i-252:i]
        r_12v = ret_12vix[i-252:i]

        s_pct = (np.mean(r_pct) * 252 - RF_ANNUAL) / (np.std(r_pct, ddof=1) * np.sqrt(252))
        s_12v = (np.mean(r_12v) * 252 - RF_ANNUAL) / (np.std(r_12v, ddof=1) * np.sqrt(252))

        roll_sharpe_pct.append(s_pct)
        roll_sharpe_12vix.append(s_12v)
        roll_dates.append(data_valid.index[i].strftime("%Y-%m-%d"))

    # Compute summary stats
    roll_diff = np.array(roll_sharpe_pct) - np.array(roll_sharpe_12vix)
    pct_positive = float(np.mean(roll_diff > 0))

    result = {
        "pct_days_percentile_higher_rolling_sharpe": round(pct_positive, 4),
        "avg_rolling_sharpe_diff": round(float(np.mean(roll_diff)), 4),
        "std_rolling_sharpe_diff": round(float(np.std(roll_diff)), 4),
        "min_rolling_sharpe_diff": round(float(np.min(roll_diff)), 4),
        "max_rolling_sharpe_diff": round(float(np.max(roll_diff)), 4),
    }

    print(f"  % of time Percentile has higher rolling Sharpe: {pct_positive:.1%}")
    print(f"  Avg rolling Sharpe diff: {np.mean(roll_diff):+.4f}")
    print(f"  Range: [{np.min(roll_diff):+.4f}, {np.max(roll_diff):+.4f}]")

    return result


def turnover_analysis(data, window=252):
    """Compare turnover between strategies — high turnover erodes real returns."""
    print("\n--- Turnover Analysis ---")

    vix_pct = compute_rolling_percentile(data["vix"], window)
    data_with_pct = data.copy()
    data_with_pct["vix_percentile"] = vix_pct
    data_with_pct["w_percentile"] = 1.0 - data_with_pct["vix_percentile"]
    data_with_pct["w_12vix"] = np.minimum(12.0 / data_with_pct["vix"], 1.0)

    valid_mask = data_with_pct["vix_percentile"].notna()
    data_valid = data_with_pct[valid_mask]

    w_pct = data_valid["w_percentile"].values
    w_12vix = data_valid["w_12vix"].values

    # Daily absolute weight change
    turnover_pct = np.abs(np.diff(w_pct[~np.isnan(w_pct)]))
    turnover_12vix = np.abs(np.diff(w_12vix[~np.isnan(w_12vix)]))

    avg_daily_to_pct = float(np.mean(turnover_pct))
    avg_daily_to_12vix = float(np.mean(turnover_12vix))
    annual_to_pct = avg_daily_to_pct * 252
    annual_to_12vix = avg_daily_to_12vix * 252

    # Impact at various TC levels
    tc_levels = [5, 10, 20, 30, 50]
    tc_impact = {}
    for tc in tc_levels:
        cost_pct = annual_to_pct * tc / 10000 * 100  # as % of portfolio
        cost_12vix = annual_to_12vix * tc / 10000 * 100
        tc_impact[f"{tc}bps"] = {
            "percentile_annual_cost_pct": round(cost_pct, 3),
            "12vix_annual_cost_pct": round(cost_12vix, 3),
            "incremental_cost_pct": round(cost_pct - cost_12vix, 3),
        }

    result = {
        "avg_daily_turnover_percentile": round(avg_daily_to_pct, 6),
        "avg_daily_turnover_12vix": round(avg_daily_to_12vix, 6),
        "annual_turnover_percentile": round(annual_to_pct, 2),
        "annual_turnover_12vix": round(annual_to_12vix, 2),
        "turnover_ratio_pct_vs_12vix": round(annual_to_pct / annual_to_12vix, 2)
            if annual_to_12vix > 0 else None,
        "tc_sensitivity": tc_impact,
    }

    print(f"  Annual turnover — Percentile: {annual_to_pct:.2f}, 12/VIX: {annual_to_12vix:.2f}")
    print(f"  Turnover ratio (Pct/12VIX): {result['turnover_ratio_pct_vs_12vix']}x")
    print(f"  At 5 bps: incremental cost = {tc_impact['5bps']['incremental_cost_pct']:.3f}% p.a.")
    print(f"  At 20 bps: incremental cost = {tc_impact['20bps']['incremental_cost_pct']:.3f}% p.a.")

    return result


def main():
    print("=" * 70)
    print("K680: Cross-OOS Validation of VIX Percentile Strategy (K679)")
    print("=" * 70)
    print("Validating: w = 1 - VIX_percentile(252d) vs w = min(12/VIX, 1.0)")
    print("On 50/50 SPY/GLD portfolio")
    print()

    # Step 1: Download data
    data = download_data()

    # Step 2: Descriptive statistics
    print("\n--- Data Descriptive Statistics ---")
    vix = data["vix"]
    print(f"  VIX: mean={vix.mean():.2f}, std={vix.std():.2f}, "
          f"skew={vix.skew():.2f}, kurt={vix.kurtosis():.2f}")
    print(f"  SPY returns: mean={data['spy_ret'].mean()*252*100:.2f}% ann, "
          f"vol={data['spy_ret'].std()*np.sqrt(252)*100:.2f}%")
    print(f"  GLD returns: mean={data['gld_ret'].mean()*252*100:.2f}% ann, "
          f"vol={data['gld_ret'].std()*np.sqrt(252)*100:.2f}%")

    data_descriptive = {
        "vix": {
            "mean": round(float(vix.mean()), 2),
            "std": round(float(vix.std()), 2),
            "skew": round(float(vix.skew()), 2),
            "kurt": round(float(vix.kurtosis()), 2),
            "min": round(float(vix.min()), 2),
            "max": round(float(vix.max()), 2),
        },
        "spy_ann_ret_pct": round(float(data["spy_ret"].mean() * 252 * 100), 2),
        "spy_ann_vol_pct": round(float(data["spy_ret"].std() * np.sqrt(252) * 100), 2),
        "gld_ann_ret_pct": round(float(data["gld_ret"].mean() * 252 * 100), 2),
        "gld_ann_vol_pct": round(float(data["gld_ret"].std() * np.sqrt(252) * 100), 2),
        "n_days": len(data),
        "date_range": f"{data.index[0].date()} to {data.index[-1].date()}",
    }

    # Step 3: Sensitivity analysis (runs cross-OOS for each window)
    sensitivity_results = sensitivity_analysis(data)

    # Extract the 252d results (our main interest)
    main_result = sensitivity_results[252]
    full_ret_pct = sensitivity_results["_full_ret_pct_252"]
    full_ret_12vix = sensitivity_results["_full_ret_12vix_252"]

    # Step 4: Full-sample DM test with HAC
    full_dm = run_full_sample_dm(full_ret_pct, full_ret_12vix)

    # Step 5: Bootstrap
    bootstrap_result = run_bootstrap(full_ret_pct, full_ret_12vix)

    # Step 6: Full-sample metrics
    print("\n--- Full Sample Metrics (252d window) ---")
    full_metrics_pct = compute_period_metrics(full_ret_pct)
    full_metrics_12vix = compute_period_metrics(full_ret_12vix)
    print(f"  Percentile: Sharpe={full_metrics_pct['sharpe']:.4f}, "
          f"CAGR={full_metrics_pct['cagr_pct']:.2f}%, MDD={full_metrics_pct['mdd_pct']:.2f}%")
    print(f"  12/VIX:     Sharpe={full_metrics_12vix['sharpe']:.4f}, "
          f"CAGR={full_metrics_12vix['cagr_pct']:.2f}%, MDD={full_metrics_12vix['mdd_pct']:.2f}%")

    # Step 7: Rolling Sharpe comparison
    rolling_result = rolling_sharpe_comparison(data, window=252)

    # Step 8: Turnover analysis
    turnover_result = turnover_analysis(data, window=252)

    # ============================================================================
    # Compile results
    # ============================================================================

    # Clean up sensitivity results (remove internal arrays)
    clean_sensitivity = {}
    for w in ROLLING_WINDOWS:
        clean_sensitivity[f"{w}d"] = {
            "periods": sensitivity_results[w]["periods"],
            "aggregate": sensitivity_results[w]["aggregate"],
        }

    # Determine best window
    best_window = max(ROLLING_WINDOWS,
                      key=lambda w: sensitivity_results[w]["aggregate"]["avg_sharpe_diff"])
    best_agg = sensitivity_results[best_window]["aggregate"]

    # Overall verdict
    main_agg = main_result["aggregate"]
    overall_verdict = main_agg["robustness_criteria"]["OVERALL_PASS"]

    # Key findings
    findings = []
    findings.append(
        f"252d window: {main_agg['sharpe_wins']}/{main_agg['n_oos_periods']} OOS wins, "
        f"avg Sharpe diff = {main_agg['avg_sharpe_diff']:+.4f}"
    )
    findings.append(
        f"Best window: {best_window}d ({best_agg['sharpe_wins']}/{best_agg['n_oos_periods']} wins, "
        f"avg diff = {best_agg['avg_sharpe_diff']:+.4f})"
    )
    findings.append(
        f"Full-sample DM test: t={full_dm['t_stat']:.4f}, "
        f"Harvey PASS={full_dm['harvey_pass']}"
    )
    findings.append(
        f"Bootstrap 95% CI: [{bootstrap_result['ci_95_lower']:+.4f}, "
        f"{bootstrap_result['ci_95_upper']:+.4f}], "
        f"excludes zero={bootstrap_result['ci_excludes_zero']}"
    )
    findings.append(
        f"Full-sample Percentile: Sharpe={full_metrics_pct['sharpe']:.4f}, "
        f"MDD={full_metrics_pct['mdd_pct']:.2f}%"
    )
    findings.append(
        f"Full-sample 12/VIX: Sharpe={full_metrics_12vix['sharpe']:.4f}, "
        f"MDD={full_metrics_12vix['mdd_pct']:.2f}%"
    )
    findings.append(
        f"Turnover: Percentile {turnover_result['annual_turnover_percentile']:.1f} vs "
        f"12/VIX {turnover_result['annual_turnover_12vix']:.1f} "
        f"({turnover_result['turnover_ratio_pct_vs_12vix']}x)"
    )
    findings.append(
        f"Rolling Sharpe: Percentile higher {rolling_result['pct_days_percentile_higher_rolling_sharpe']:.1%} "
        f"of the time"
    )

    # Per-period summary for quick reference
    period_summary = []
    for pname in OOS_PERIODS:
        pr = main_result["periods"].get(pname, {})
        if "error" in pr:
            period_summary.append({"period": pname, "error": pr["error"]})
        else:
            period_summary.append({
                "period": pname,
                "pct_sharpe": pr["percentile_strategy"]["sharpe"],
                "12vix_sharpe": pr["baseline_12vix"]["sharpe"],
                "sharpe_diff": pr["sharpe_diff"],
                "win": pr["percentile_wins_sharpe"],
                "dm_t": pr["dm_test"]["t_stat"],
                "dm_p": pr["dm_test"]["p_value"],
                "pct_mdd": pr["percentile_strategy"]["mdd_pct"],
                "12vix_mdd": pr["baseline_12vix"]["mdd_pct"],
                "win_rate": pr["daily_win_rate"],
            })

    # Final verdict message
    if overall_verdict:
        verdict_msg = (
            f"VALIDATED: VIX Percentile (252d) passes cross-OOS with "
            f"{main_agg['sharpe_wins']}/{main_agg['n_oos_periods']} wins. "
            f"Bootstrap CI excludes zero. Recommend as upgrade to 12/VIX."
        )
    else:
        failures = []
        if not main_agg["robustness_criteria"]["win_rate_4of5"]:
            failures.append(f"win rate {main_agg['sharpe_wins']}/{main_agg['n_oos_periods']} < 4/5")
        if not main_agg["robustness_criteria"]["avg_improvement_positive"]:
            failures.append(f"avg Sharpe diff {main_agg['avg_sharpe_diff']:+.4f} <= 0")
        if not main_agg["robustness_criteria"]["no_catastrophic_loss"]:
            failures.append(f"min Sharpe diff {main_agg['min_sharpe_diff']:+.4f} < -0.5")
        verdict_msg = (
            f"FAILED: VIX Percentile (252d) fails cross-OOS. "
            f"Failures: {'; '.join(failures)}. "
            f"K679 full-sample result may be data-mined."
        )

    results = {
        "experiment_id": "K680",
        "title": "Cross-OOS Validation of VIX Percentile Strategy (K679)",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "data_period": f"{START_DATE} to {END_DATE}",
        "methodology": {
            "design": "5 non-overlapping OOS periods, each >= 2 years",
            "percentile_strategy": "w = 1 - percentile_rank(VIX, rolling_window)",
            "baseline": "w = min(12/VIX, 1.0)",
            "portfolio": "50/50 SPY/GLD, cash remainder at 4% annual RF",
            "transaction_cost": f"{TC_BPS} bps one-way",
            "bootstrap": f"{BOOTSTRAP_REPS} replications",
            "robustness_criteria": {
                "win_rate": ">= 4/5 OOS periods on Sharpe",
                "avg_improvement": "> 0",
                "no_catastrophe": "min Sharpe diff > -0.5",
            },
        },
        "references": [
            "K679: VIX Percentile Strategy (Sharpe 1.68 vs 1.08, t=3.375)",
            "K459: Cross-OOS validation (53% false positive lesson)",
            "K474/K476: Cross-OOS methodology",
            "Harvey et al. (2016), ...and the Cross-Section of Expected Returns, t>3.0",
            "Copeland & Copeland (1999), Market Timing with VIX",
        ],
        "data_descriptive": data_descriptive,
        "main_result_252d": {
            "period_summary": period_summary,
            "aggregate": main_agg,
        },
        "sensitivity_by_window": {
            f"{w}d": sensitivity_results[w]["aggregate"] for w in ROLLING_WINDOWS
        },
        "best_window": {
            "window_days": best_window,
            "sharpe_wins": best_agg["sharpe_wins"],
            "avg_sharpe_diff": best_agg["avg_sharpe_diff"],
        },
        "full_sample_metrics": {
            "percentile_252d": full_metrics_pct,
            "baseline_12vix": full_metrics_12vix,
        },
        "full_sample_dm_test": full_dm,
        "bootstrap": bootstrap_result,
        "rolling_sharpe_comparison": rolling_result,
        "turnover_analysis": turnover_result,
        "cross_oos_detail": clean_sensitivity,
        "overall_verdict": overall_verdict,
        "verdict_message": verdict_msg,
        "key_findings": findings,
    }

    # Print final verdict
    print("\n" + "=" * 70)
    print("FINAL VERDICT")
    print("=" * 70)
    print(f"  {verdict_msg}")
    print()

    for i, f in enumerate(findings, 1):
        print(f"  {i}. {f}")

    # Save
    out_path = Path(__file__).parent / "k680_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

    return results


if __name__ == "__main__":
    main()
