"""K686: VIX Percentile Strategy CORRECTED — Fixing K679 Codex Bugs

CRITICAL CORRECTIONS from Codex review of K679:
  Bug #1 (HIGH): Same-day lookahead — VIX_t signal applied to day-t return.
    FIX: Use VIX_{t-1} signal for day-t return (shift signal by 1 day).
  Bug #2 (HIGH): Used paired t-test, not proper DM test with HAC SE.
    FIX: Diebold-Mariano test with Newey-West HAC on NET returns (after TX).
  Bug #3 (MEDIUM): Rolling percentile may include current VIX.
    FIX: Explicitly exclude current value — rank against prior 252 only.

Purpose:
  Determine whether the K679 Percentile advantage (Sharpe 1.68 vs 1.08)
  was an artifact of lookahead bias or a real improvement.

Strategies (all with 1-day lag):
  a. 12/VIX: w_t = min(12 / VIX_{t-1}, 1.0)
  b. Percentile: w_t = 1 - percentile_rank(VIX_{t-1}, prior 252d excluding VIX_{t-1})
  c. Buy-and-Hold 50/50 SPY/GLD

Data source: yfinance (SPY, GLD, ^VIX)
Period: 2006-01-01 to 2026-03-27
Eval: 2007-01-03 to 2026-03-27

References:
  - K679: Original (buggy) VIX percentile strategy
  - K680: Cross-OOS (also had lookahead bug)
  - Copeland & Copeland (1999), Market Timing with VIX
  - Harvey et al. (2016), ...and the Cross-Section of Expected Returns
  - Diebold & Mariano (1995), Comparing Predictive Accuracy

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
EVAL_START = "2007-01-03"  # Need 252d warmup for rolling stats
ROLLING_WINDOW = 252       # 1 year for percentile
TC_BPS = 5                 # Transaction cost in basis points (one-way)
RF_DAILY = 0.04 / 252      # ~4% annual risk-free for cash portion
BOOTSTRAP_REPS = 5000      # Bootstrap replications for CI


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


def compute_rolling_percentile(vix_series, window=ROLLING_WINDOW):
    """Compute rolling percentile rank, STRICTLY excluding current value.

    For each day i, we rank VIX[i] against the PRIOR `window` values
    (VIX[i-window], ..., VIX[i-1]). The current value VIX[i] is NOT
    included in the comparison window.

    BUG FIX #3: K679 used percentileofscore(vals[i-window:i], vals[i])
    which actually does exclude vals[i] from the window (Python slice
    is exclusive of end). But to be absolutely explicit and clear,
    we use a strict implementation here.
    """
    result = pd.Series(index=vix_series.index, dtype=float)
    vals = vix_series.values

    for i in range(window, len(vals)):
        # Prior window: indices [i-window, i-1], explicitly excluding i
        prior_window = vals[i - window:i]  # This is [i-window, ..., i-1]
        current = vals[i]
        # What fraction of the prior window is <= current value
        pct_rank = np.sum(prior_window <= current) / len(prior_window)
        result.iloc[i] = pct_rank

    return result


def compute_lagged_weights(data):
    """Compute strategy weights using LAGGED signals (BUG FIX #1).

    CRITICAL: We compute weights from day t's VIX, then SHIFT by 1 day
    so that the weight used on day t+1 is based on day t's VIX.
    This eliminates same-day lookahead bias.
    """
    vix = data["vix"]

    # Step 1: Compute raw signals from today's VIX
    print("  Computing rolling percentile (strict exclude current)...")
    raw_percentile = compute_rolling_percentile(vix, ROLLING_WINDOW)

    # Raw 12/VIX weight
    raw_12vix = np.minimum(12.0 / vix, 1.0)

    # Raw percentile weight
    raw_pct_weight = 1.0 - raw_percentile

    # Step 2: SHIFT signals by 1 day (BUG FIX #1)
    # On day t, we use the signal computed from day t-1's VIX
    data = data.copy()
    data["w_12vix"] = raw_12vix.shift(1)        # Yesterday's 12/VIX signal
    data["w_percentile"] = raw_pct_weight.shift(1)  # Yesterday's percentile signal

    # Also store the raw (unlagged) for comparison/diagnosis
    data["w_12vix_unlagged"] = raw_12vix
    data["w_percentile_unlagged"] = raw_pct_weight
    data["vix_percentile_raw"] = raw_percentile

    # Count valid weights
    eval_mask = data.index >= EVAL_START
    for wc in ["w_12vix", "w_percentile"]:
        valid = data.loc[eval_mask, wc].notna().sum()
        total = eval_mask.sum()
        print(f"    {wc}: {valid}/{total} valid weights in eval period")

    return data


def backtest_strategy(data, weight_col, name, tc_bps=TC_BPS, eval_start=EVAL_START):
    """Backtest a 50/50 SPY/GLD strategy with given LAGGED weight column.

    Returns are NET of transaction costs.
    """
    eval_mask = data.index >= eval_start
    df = data[eval_mask].copy()

    if len(df) == 0:
        return None

    weights = df[weight_col].values
    spy_ret = df["spy_ret"].values
    gld_ret = df["gld_ret"].values

    # 50/50 SPY/GLD portfolio return (when invested)
    portfolio_ret = 0.5 * spy_ret + 0.5 * gld_ret

    # Strategy return = w * portfolio_ret + (1 - w) * rf - tc
    gross_returns = np.zeros(len(df))
    net_returns = np.zeros(len(df))
    tc_rate = tc_bps / 10000.0

    prev_w = 0.0
    for i in range(len(df)):
        w = weights[i]
        if np.isnan(w):
            w = prev_w  # carry forward if NaN

        # Gross return
        gross_returns[i] = w * portfolio_ret[i] + (1 - w) * RF_DAILY

        # Transaction cost from weight change
        tc = abs(w - prev_w) * tc_rate
        net_returns[i] = gross_returns[i] - tc
        prev_w = w

    # Compute metrics on NET returns
    cum_ret = np.cumprod(1 + net_returns)
    total_ret = cum_ret[-1] - 1
    n_years = len(df) / 252.0
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    ann_ret = np.mean(net_returns) * 252
    ann_vol = np.std(net_returns, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0  # excess over 4% rf

    # Max drawdown
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = (cum_ret - running_max) / running_max
    mdd = np.min(drawdowns)

    # Calmar ratio
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino ratio (downside deviation)
    downside = net_returns[net_returns < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = (ann_ret - 0.04) / downside_vol if downside_vol > 0 else 0

    # Average weight (exposure)
    valid_w = weights[~np.isnan(weights)]
    avg_weight = np.mean(valid_w) if len(valid_w) > 0 else 0

    # Turnover
    weight_changes = np.abs(np.diff(valid_w))
    avg_daily_turnover = np.mean(weight_changes) if len(weight_changes) > 0 else 0
    annual_turnover = avg_daily_turnover * 252

    # Total TX cost drag
    total_tc_drag_ann = float(np.mean(np.abs(np.diff(np.concatenate([[0], valid_w])))) * tc_rate * 252 * 10000)

    return {
        "strategy": name,
        "cagr": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "ann_vol": round(ann_vol * 100, 2),
        "ann_ret": round(ann_ret * 100, 2),
        "avg_weight": round(avg_weight, 3),
        "annual_turnover": round(annual_turnover, 2),
        "total_tc_drag_bps_ann": round(total_tc_drag_ann, 2),
        "total_return_pct": round(total_ret * 100, 2),
        "n_days": len(df),
        "n_years": round(n_years, 1),
        "net_returns": net_returns,  # Keep for DM test
        "gross_returns": gross_returns,
    }


def dm_test_hac(returns_1, returns_2, h=1):
    """Diebold-Mariano test with Newey-West HAC standard errors (BUG FIX #2).

    Tests H0: E[d_t] = 0 where d_t = r_{1,t} - r_{2,t}
    Positive t-stat means strategy 1 outperforms strategy 2.

    Uses NET returns (after TX costs), not gross returns.
    Uses Bartlett kernel with bandwidth = int(n^(1/3)).
    """
    d = returns_1 - returns_2
    n = len(d)

    if n < 30:
        return {"t_stat": np.nan, "p_value": np.nan, "mean_diff_bps": np.nan}

    mean_d = np.mean(d)

    # Newey-West HAC variance estimation
    bandwidth = max(1, int(n ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    nw_var = gamma_0

    for k in range(1, bandwidth + 1):
        # Autocovariance at lag k
        gamma_k = np.mean((d[k:] - mean_d) * (d[:-k] - mean_d))
        weight = 1 - k / (bandwidth + 1)  # Bartlett kernel
        nw_var += 2 * weight * gamma_k

    se = np.sqrt(max(nw_var, 0) / n)  # Ensure non-negative variance
    t_stat = mean_d / se if se > 0 else 0
    p_value = 2 * sp_stats.t.sf(abs(t_stat), df=n - 1)

    return {
        "t_stat": round(float(t_stat), 4),
        "p_value": round(float(p_value), 6),
        "mean_diff_bps": round(float(mean_d * 10000), 4),
        "n_obs": int(n),
        "nw_bandwidth": int(bandwidth),
        "harvey_pass": abs(t_stat) > 3.0,
    }


def cross_oos_validation(data):
    """Cross-OOS validation with 5 non-overlapping periods (same as K680).

    All with CORRECTED lagged signals.
    """
    oos_periods = {
        "OOS1_GFC":       ("2008-01-02", "2009-12-31"),
        "OOS2_Recovery":  ("2011-01-03", "2013-12-31"),
        "OOS3_LowVol":    ("2015-01-02", "2017-12-29"),
        "OOS4_COVID":     ("2020-01-02", "2021-12-31"),
        "OOS5_PostHike":  ("2023-01-03", "2024-12-31"),
    }

    results = []

    for period_name, (start, end) in oos_periods.items():
        mask = (data.index >= start) & (data.index <= end)
        period_data = data[mask]

        if len(period_data) < 50:
            print(f"  {period_name}: skipped (only {len(period_data)} days)")
            continue

        # Backtest both strategies on this OOS period
        pct_result = backtest_strategy(period_data, "w_percentile", "Percentile",
                                       tc_bps=TC_BPS, eval_start=start)
        vix_result = backtest_strategy(period_data, "w_12vix", "12/VIX",
                                       tc_bps=TC_BPS, eval_start=start)

        if pct_result is None or vix_result is None:
            continue

        # DM test on NET returns
        dm = dm_test_hac(pct_result["net_returns"], vix_result["net_returns"])

        # Daily win rate (percentile beats 12/VIX)
        net_diff = pct_result["net_returns"] - vix_result["net_returns"]
        win_rate = float(np.mean(net_diff > 0))

        period_result = {
            "period": period_name,
            "dates": f"{start} to {end}",
            "n_days": len(period_data),
            "pct_sharpe": pct_result["sharpe"],
            "pct_cagr": pct_result["cagr"],
            "pct_mdd": pct_result["mdd"],
            "pct_avg_weight": pct_result["avg_weight"],
            "12vix_sharpe": vix_result["sharpe"],
            "12vix_cagr": vix_result["cagr"],
            "12vix_mdd": vix_result["mdd"],
            "12vix_avg_weight": vix_result["avg_weight"],
            "sharpe_diff": round(pct_result["sharpe"] - vix_result["sharpe"], 4),
            "pct_wins_sharpe": pct_result["sharpe"] > vix_result["sharpe"],
            "dm_t_stat": dm["t_stat"],
            "dm_p_value": dm["p_value"],
            "dm_harvey_pass": dm["harvey_pass"],
            "daily_win_rate": round(win_rate, 4),
        }

        results.append(period_result)
        print(f"  {period_name}: Pct Sharpe={pct_result['sharpe']:.3f} vs "
              f"12/VIX Sharpe={vix_result['sharpe']:.3f}, "
              f"diff={period_result['sharpe_diff']:.4f}, "
              f"DM t={dm['t_stat']:.3f} (p={dm['p_value']:.4f})")

    # Aggregate
    if len(results) > 0:
        sharpe_wins = sum(1 for r in results if r["pct_wins_sharpe"])
        avg_sharpe_diff = np.mean([r["sharpe_diff"] for r in results])
        min_sharpe_diff = min(r["sharpe_diff"] for r in results)
        max_sharpe_diff = max(r["sharpe_diff"] for r in results)

        aggregate = {
            "n_oos_periods": len(results),
            "sharpe_wins": sharpe_wins,
            "sharpe_losses": len(results) - sharpe_wins,
            "avg_sharpe_diff": round(float(avg_sharpe_diff), 4),
            "min_sharpe_diff": round(float(min_sharpe_diff), 4),
            "max_sharpe_diff": round(float(max_sharpe_diff), 4),
            "robustness_criteria": {
                "win_rate_4of5": sharpe_wins >= 4,
                "avg_improvement_positive": avg_sharpe_diff > 0,
                "no_catastrophic_loss": min_sharpe_diff > -0.5,
                "OVERALL_PASS": (sharpe_wins >= 4 and avg_sharpe_diff > 0
                                 and min_sharpe_diff > -0.5),
            },
        }
    else:
        aggregate = {"n_oos_periods": 0, "error": "No valid OOS periods"}

    return results, aggregate


def bootstrap_sharpe_diff(pct_net_returns, vix_net_returns, n_reps=BOOTSTRAP_REPS):
    """Bootstrap confidence interval for Sharpe difference (on NET returns)."""
    n = len(pct_net_returns)
    sharpe_diffs = np.zeros(n_reps)

    for b in range(n_reps):
        idx = np.random.choice(n, size=n, replace=True)
        pct_b = pct_net_returns[idx]
        vix_b = vix_net_returns[idx]

        # Sharpe for each
        pct_sharpe = (np.mean(pct_b) * 252 - 0.04) / (np.std(pct_b, ddof=1) * np.sqrt(252)) if np.std(pct_b) > 0 else 0
        vix_sharpe = (np.mean(vix_b) * 252 - 0.04) / (np.std(vix_b, ddof=1) * np.sqrt(252)) if np.std(vix_b) > 0 else 0
        sharpe_diffs[b] = pct_sharpe - vix_sharpe

    ci_lower = float(np.percentile(sharpe_diffs, 2.5))
    ci_upper = float(np.percentile(sharpe_diffs, 97.5))
    ci_5_lower = float(np.percentile(sharpe_diffs, 5))
    ci_5_upper = float(np.percentile(sharpe_diffs, 95))
    pct_positive = float(np.mean(sharpe_diffs > 0) * 100)

    return {
        "n_reps": n_reps,
        "mean_diff": round(float(np.mean(sharpe_diffs)), 4),
        "median_diff": round(float(np.median(sharpe_diffs)), 4),
        "ci_95": [round(ci_lower, 4), round(ci_upper, 4)],
        "ci_90": [round(ci_5_lower, 4), round(ci_5_upper, 4)],
        "pct_positive": round(pct_positive, 1),
        "significant_95": ci_lower > 0,  # Entire 95% CI above zero
        "significant_90": ci_5_lower > 0,
    }


def compare_with_k679(corrected_results, k679_results_path=None):
    """Compare corrected results with K679 original (buggy) results."""
    # K679 known values (from results JSON)
    k679_values = {
        "Percentile": {"sharpe": 1.68, "cagr": 15.39, "mdd": -6.74},
        "12/VIX": {"sharpe": 1.079, "cagr": 12.44, "mdd": -9.04},
        "t_stat_paired": 3.375,  # This was a paired t-test, not DM!
    }

    comparison = {"k679_original_buggy": k679_values, "k686_corrected": {}}

    for r in corrected_results:
        name = r["strategy"]
        comparison["k686_corrected"][name] = {
            "sharpe": r["sharpe"],
            "cagr": r["cagr"],
            "mdd": r["mdd"],
        }

    # Compute deltas
    for name in ["Percentile", "12/VIX"]:
        if name in comparison["k686_corrected"]:
            old = k679_values.get(name, {})
            new = comparison["k686_corrected"][name]
            comparison.setdefault("delta", {})[name] = {
                "sharpe_change": round(new["sharpe"] - old.get("sharpe", 0), 3),
                "cagr_change": round(new["cagr"] - old.get("cagr", 0), 2),
            }

    return comparison


def main():
    print("=" * 70)
    print("K686: VIX Percentile Strategy CORRECTED (Fixing K679 Codex Bugs)")
    print("=" * 70)
    print("\nBugs being fixed:")
    print("  #1 (HIGH): Same-day lookahead → Use VIX_{t-1} for day-t return")
    print("  #2 (HIGH): Paired t-test → Proper DM test with Newey-West HAC on NET returns")
    print("  #3 (MED):  Percentile window → Strictly exclude current VIX value")

    # ========================================================================
    # Step 1: Download data
    # ========================================================================
    data = download_data()

    # ========================================================================
    # Step 2: Descriptive statistics
    # ========================================================================
    print("\n--- VIX Descriptive Statistics ---")
    vix = data["vix"]
    vix_descriptive = {
        "mean": round(float(vix.mean()), 2),
        "std": round(float(vix.std()), 2),
        "min": round(float(vix.min()), 2),
        "max": round(float(vix.max()), 2),
        "skewness": round(float(vix.skew()), 2),
        "kurtosis": round(float(vix.kurtosis()), 2),
        "median": round(float(vix.median()), 2),
    }
    for k, v in vix_descriptive.items():
        print(f"  {k}: {v}")

    # ========================================================================
    # Step 3: Compute LAGGED weights (BUG FIX #1 + #3)
    # ========================================================================
    print("\n--- Computing LAGGED Strategy Weights ---")
    data = compute_lagged_weights(data)

    # ========================================================================
    # Step 4: Full-sample backtest (CORRECTED)
    # ========================================================================
    print("\n--- Full-Sample Backtest (CORRECTED, Lagged Signals) ---")
    strategies = [
        ("w_12vix", "12/VIX (Lagged)"),
        ("w_percentile", "Percentile (Lagged)"),
    ]

    # Also run unlagged for direct comparison
    strategies_unlagged = [
        ("w_12vix_unlagged", "12/VIX (Unlagged, K679 bug)"),
        ("w_percentile_unlagged", "Percentile (Unlagged, K679 bug)"),
    ]

    all_results = {}
    backtest_summary = []

    for wcol, sname in strategies + strategies_unlagged:
        result = backtest_strategy(data, wcol, sname)
        if result:
            all_results[sname] = result
            print(f"\n  {sname}:")
            print(f"    CAGR:  {result['cagr']:.2f}%")
            print(f"    NET Sharpe: {result['sharpe']:.3f}")
            print(f"    Sortino: {result['sortino']:.3f}")
            print(f"    MDD:   {result['mdd']:.2f}%")
            print(f"    Calmar: {result['calmar']:.3f}")
            print(f"    Avg Weight: {result['avg_weight']:.3f}")
            print(f"    Ann Turnover: {result['annual_turnover']:.2f}")
            print(f"    TC Drag (bps/yr): {result['total_tc_drag_bps_ann']:.2f}")

            # Save summary (without numpy arrays)
            summary = {k: v for k, v in result.items()
                       if k not in ("net_returns", "gross_returns")}
            backtest_summary.append(summary)

    # ========================================================================
    # Step 5: Buy-and-Hold comparison
    # ========================================================================
    print("\n--- Buy-and-Hold 50/50 Comparison ---")
    eval_data = data[data.index >= EVAL_START]
    portfolio_ret = 0.5 * eval_data["spy_ret"] + 0.5 * eval_data["gld_ret"]
    bh_cum = (1 + portfolio_ret).cumprod()
    bh_total = float(bh_cum.iloc[-1] - 1)
    bh_n_years = len(eval_data) / 252.0
    bh_cagr = (1 + bh_total) ** (1 / bh_n_years) - 1
    bh_ann_vol = float(portfolio_ret.std() * np.sqrt(252))
    bh_ann_ret = float(portfolio_ret.mean() * 252)
    bh_sharpe = (bh_ann_ret - 0.04) / bh_ann_vol if bh_ann_vol > 0 else 0
    bh_running_max = np.maximum.accumulate(bh_cum.values)
    bh_dd = (bh_cum.values - bh_running_max) / bh_running_max
    bh_mdd = float(np.min(bh_dd))
    bh_result = {
        "strategy": "Buy-and-Hold 50/50",
        "cagr": round(bh_cagr * 100, 2),
        "sharpe": round(bh_sharpe, 3),
        "mdd": round(bh_mdd * 100, 2),
    }
    print(f"  Buy-and-Hold: CAGR={bh_cagr*100:.2f}%, Sharpe={bh_sharpe:.3f}, MDD={bh_mdd*100:.2f}%")

    # ========================================================================
    # Step 6: PROPER DM Test with HAC on NET returns (BUG FIX #2)
    # ========================================================================
    print("\n" + "=" * 70)
    print("PROPER DIEBOLD-MARIANO TEST (Newey-West HAC, NET Returns)")
    print("=" * 70)

    # Corrected (lagged) comparison
    pct_lagged = all_results.get("Percentile (Lagged)")
    vix_lagged = all_results.get("12/VIX (Lagged)")

    if pct_lagged and vix_lagged:
        dm_corrected = dm_test_hac(pct_lagged["net_returns"], vix_lagged["net_returns"])
        print(f"\n  CORRECTED Percentile vs 12/VIX (both lagged, NET returns):")
        print(f"    Mean diff: {dm_corrected['mean_diff_bps']:.4f} bps/day")
        print(f"    DM t-stat: {dm_corrected['t_stat']:.4f}")
        print(f"    p-value:   {dm_corrected['p_value']:.6f}")
        print(f"    NW bandwidth: {dm_corrected['nw_bandwidth']}")
        print(f"    Harvey (2016) pass (|t|>3): {dm_corrected['harvey_pass']}")

        # Also test on GROSS returns for comparison
        dm_gross = dm_test_hac(pct_lagged["gross_returns"], vix_lagged["gross_returns"])
        print(f"\n  CORRECTED Percentile vs 12/VIX (lagged, GROSS returns):")
        print(f"    DM t-stat: {dm_gross['t_stat']:.4f}")
        print(f"    p-value:   {dm_gross['p_value']:.6f}")
    else:
        dm_corrected = {"error": "Missing lagged results"}
        dm_gross = {"error": "Missing lagged results"}

    # Unlagged comparison (reproducing K679 bug for verification)
    pct_unlagged = all_results.get("Percentile (Unlagged, K679 bug)")
    vix_unlagged = all_results.get("12/VIX (Unlagged, K679 bug)")

    if pct_unlagged and vix_unlagged:
        # K679-style paired t-test (buggy)
        diff_unlagged = pct_unlagged["net_returns"] - vix_unlagged["net_returns"]
        t_paired = float(diff_unlagged.mean() / (diff_unlagged.std() / np.sqrt(len(diff_unlagged))))
        p_paired = float(2 * sp_stats.t.sf(abs(t_paired), df=len(diff_unlagged) - 1))

        # Proper DM test on unlagged
        dm_unlagged = dm_test_hac(pct_unlagged["net_returns"], vix_unlagged["net_returns"])

        print(f"\n  UNLAGGED (K679 reproduction) — paired t-test:")
        print(f"    Paired t-stat: {t_paired:.4f} (K679 reported: 3.375)")
        print(f"    p-value: {p_paired:.6f}")
        print(f"\n  UNLAGGED — proper DM test with HAC:")
        print(f"    DM t-stat: {dm_unlagged['t_stat']:.4f}")
        print(f"    p-value: {dm_unlagged['p_value']:.6f}")
    else:
        dm_unlagged = {"error": "Missing unlagged results"}
        t_paired = np.nan
        p_paired = np.nan

    # ========================================================================
    # Step 7: Bootstrap CI for Sharpe difference
    # ========================================================================
    print(f"\n--- Bootstrap Sharpe Difference ({BOOTSTRAP_REPS} reps) ---")
    if pct_lagged and vix_lagged:
        np.random.seed(42)
        bootstrap_result = bootstrap_sharpe_diff(
            pct_lagged["net_returns"], vix_lagged["net_returns"],
            n_reps=BOOTSTRAP_REPS
        )
        print(f"  Mean Sharpe diff: {bootstrap_result['mean_diff']:.4f}")
        print(f"  95% CI: [{bootstrap_result['ci_95'][0]:.4f}, {bootstrap_result['ci_95'][1]:.4f}]")
        print(f"  90% CI: [{bootstrap_result['ci_90'][0]:.4f}, {bootstrap_result['ci_90'][1]:.4f}]")
        print(f"  % positive: {bootstrap_result['pct_positive']:.1f}%")
        print(f"  Significant at 95%: {bootstrap_result['significant_95']}")
    else:
        bootstrap_result = {"error": "Missing lagged results"}

    # ========================================================================
    # Step 8: Cross-OOS Validation (CORRECTED)
    # ========================================================================
    print("\n" + "=" * 70)
    print("CROSS-OOS VALIDATION (5 Periods, CORRECTED Lagged Signals)")
    print("=" * 70)
    oos_results, oos_aggregate = cross_oos_validation(data)
    print(f"\n  Aggregate:")
    if "error" not in oos_aggregate:
        print(f"    Sharpe wins: {oos_aggregate['sharpe_wins']}/{oos_aggregate['n_oos_periods']}")
        print(f"    Avg Sharpe diff: {oos_aggregate['avg_sharpe_diff']:.4f}")
        print(f"    Min Sharpe diff: {oos_aggregate['min_sharpe_diff']:.4f}")
        print(f"    Max Sharpe diff: {oos_aggregate['max_sharpe_diff']:.4f}")
        print(f"    OVERALL PASS: {oos_aggregate['robustness_criteria']['OVERALL_PASS']}")

    # ========================================================================
    # Step 9: Compare with K679 original results
    # ========================================================================
    print("\n--- Comparison with K679 (Original Buggy Results) ---")
    corrected_for_compare = [r for r in backtest_summary
                             if "(Lagged)" in r["strategy"]]
    k679_comparison = compare_with_k679(corrected_for_compare)

    for name, delta in k679_comparison.get("delta", {}).items():
        print(f"  {name}:")
        print(f"    Sharpe change: {delta['sharpe_change']:+.3f}")
        print(f"    CAGR change: {delta['cagr_change']:+.2f}%")

    # ========================================================================
    # Step 10: Lookahead Impact Analysis
    # ========================================================================
    print("\n--- Lookahead Bias Impact Analysis ---")
    if pct_lagged and pct_unlagged:
        print(f"  Percentile Unlagged Sharpe: {pct_unlagged['sharpe']:.3f}")
        print(f"  Percentile Lagged Sharpe:   {pct_lagged['sharpe']:.3f}")
        print(f"  Impact of lag fix: {pct_lagged['sharpe'] - pct_unlagged['sharpe']:+.3f}")

    if vix_lagged and vix_unlagged:
        print(f"  12/VIX Unlagged Sharpe: {vix_unlagged['sharpe']:.3f}")
        print(f"  12/VIX Lagged Sharpe:   {vix_lagged['sharpe']:.3f}")
        print(f"  Impact of lag fix: {vix_lagged['sharpe'] - vix_unlagged['sharpe']:+.3f}")

    # Advantage comparison
    if pct_lagged and vix_lagged and pct_unlagged and vix_unlagged:
        unlagged_advantage = pct_unlagged["sharpe"] - vix_unlagged["sharpe"]
        lagged_advantage = pct_lagged["sharpe"] - vix_lagged["sharpe"]
        print(f"\n  Percentile advantage (Sharpe vs 12/VIX):")
        print(f"    Unlagged (buggy):   {unlagged_advantage:+.3f}")
        print(f"    Lagged (corrected): {lagged_advantage:+.3f}")
        print(f"    Change: {lagged_advantage - unlagged_advantage:+.3f}")

        if lagged_advantage > 0.1:
            verdict = "SURVIVES — Percentile advantage is REAL (not an artifact of lookahead)"
        elif lagged_advantage > 0:
            verdict = "MARGINAL — Small advantage remains, may not be economically significant"
        else:
            verdict = "DISAPPEARS — Advantage was an ARTIFACT of lookahead bias"
        print(f"\n  *** VERDICT: {verdict} ***")
    else:
        verdict = "INCONCLUSIVE — Missing comparison data"
        lagged_advantage = None
        unlagged_advantage = None

    # ========================================================================
    # Save results
    # ========================================================================
    results = {
        "experiment_id": "K686",
        "title": "VIX Percentile Strategy CORRECTED (K679 Codex Bugs Fixed)",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "data_period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{EVAL_START} to {END_DATE}",
        "bugs_fixed": {
            "bug_1_lookahead": "VIX_{t-1} signal for day-t return (was: same-day VIX_t)",
            "bug_2_test_type": "DM test with Newey-West HAC on NET returns (was: paired t-test on gross)",
            "bug_3_percentile": "Strictly exclude current VIX from percentile window",
        },
        "methodology": {
            "portfolio": "50/50 SPY/GLD, cash remainder at 4% annual RF",
            "transaction_cost": f"{TC_BPS} bps one-way on weight changes",
            "rolling_window": ROLLING_WINDOW,
            "signal_lag": "1 day (use yesterday's VIX for today's weight)",
            "dm_test": "Newey-West HAC, Bartlett kernel, bandwidth=n^(1/3)",
            "bootstrap": f"{BOOTSTRAP_REPS} replications",
            "cross_oos": "5 non-overlapping periods, same as K680",
        },
        "references": [
            "K679: Original VIX percentile strategy (had 3 bugs)",
            "K680: Cross-OOS validation (also had lookahead bug)",
            "Copeland & Copeland (1999), Market Timing with VIX",
            "Harvey et al. (2016), ...and the Cross-Section of Expected Returns, t>3.0",
            "Diebold & Mariano (1995), Comparing Predictive Accuracy",
        ],
        "vix_descriptive_stats": vix_descriptive,
        "backtest_results": backtest_summary,
        "buy_and_hold": bh_result,
        "dm_test_corrected": {
            "net_returns_lagged": dm_corrected if isinstance(dm_corrected, dict) else {"error": str(dm_corrected)},
            "gross_returns_lagged": dm_gross if isinstance(dm_gross, dict) else {"error": str(dm_gross)},
            "k679_reproduction_paired_ttest": {
                "t_stat": round(float(t_paired), 4) if not np.isnan(t_paired) else None,
                "p_value": round(float(p_paired), 6) if not np.isnan(p_paired) else None,
                "note": "K679 reported t=3.375 using paired t-test on gross returns",
            },
            "unlagged_dm_test": dm_unlagged if isinstance(dm_unlagged, dict) else {"error": str(dm_unlagged)},
        },
        "bootstrap_sharpe_diff": bootstrap_result,
        "cross_oos_validation": {
            "period_results": oos_results,
            "aggregate": oos_aggregate,
        },
        "k679_comparison": k679_comparison,
        "lookahead_impact": {
            "percentile_unlagged_sharpe": pct_unlagged["sharpe"] if pct_unlagged else None,
            "percentile_lagged_sharpe": pct_lagged["sharpe"] if pct_lagged else None,
            "12vix_unlagged_sharpe": vix_unlagged["sharpe"] if vix_unlagged else None,
            "12vix_lagged_sharpe": vix_lagged["sharpe"] if vix_lagged else None,
            "unlagged_advantage": round(float(unlagged_advantage), 3) if unlagged_advantage is not None else None,
            "lagged_advantage": round(float(lagged_advantage), 3) if lagged_advantage is not None else None,
            "verdict": verdict,
        },
        "key_findings": [],  # Filled below
    }

    # Compile key findings
    findings = []

    # Finding 1: Corrected full-sample performance
    if pct_lagged and vix_lagged:
        findings.append(
            f"CORRECTED Percentile: Sharpe={pct_lagged['sharpe']:.3f}, "
            f"CAGR={pct_lagged['cagr']:.2f}% "
            f"(K679 buggy: Sharpe=1.680, CAGR=15.39%)"
        )
        findings.append(
            f"CORRECTED 12/VIX: Sharpe={vix_lagged['sharpe']:.3f}, "
            f"CAGR={vix_lagged['cagr']:.2f}% "
            f"(K679 buggy: Sharpe=1.079, CAGR=12.44%)"
        )

    # Finding 2: DM test result
    if isinstance(dm_corrected, dict) and "t_stat" in dm_corrected:
        findings.append(
            f"DM test (HAC, NET returns): t={dm_corrected['t_stat']:.4f}, "
            f"p={dm_corrected['p_value']:.6f} "
            f"(K679 buggy: paired t=3.375, p=0.0007)"
        )
        findings.append(
            f"Harvey (2016) |t|>3.0 threshold: {'PASS' if dm_corrected['harvey_pass'] else 'FAIL'}"
        )

    # Finding 3: Bootstrap
    if isinstance(bootstrap_result, dict) and "ci_95" in bootstrap_result:
        findings.append(
            f"Bootstrap Sharpe diff 95% CI: [{bootstrap_result['ci_95'][0]:.4f}, "
            f"{bootstrap_result['ci_95'][1]:.4f}], "
            f"{bootstrap_result['pct_positive']:.1f}% positive"
        )

    # Finding 4: Cross-OOS
    if "error" not in oos_aggregate:
        findings.append(
            f"Cross-OOS: {oos_aggregate['sharpe_wins']}/{oos_aggregate['n_oos_periods']} wins, "
            f"avg Sharpe diff={oos_aggregate['avg_sharpe_diff']:.4f}, "
            f"PASS={oos_aggregate['robustness_criteria']['OVERALL_PASS']}"
        )

    # Finding 5: Lookahead impact
    if lagged_advantage is not None and unlagged_advantage is not None:
        findings.append(
            f"Lookahead impact: advantage went from {unlagged_advantage:+.3f} (unlagged) "
            f"to {lagged_advantage:+.3f} (lagged)"
        )

    # Finding 6: Verdict
    findings.append(f"VERDICT: {verdict}")

    results["key_findings"] = findings

    # Save
    out_path = Path(__file__).parent / "k686_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n\nResults saved to {out_path}")

    # Print key findings
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)
    for i, finding in enumerate(findings, 1):
        print(f"  {i}. {finding}")

    return results


if __name__ == "__main__":
    main()
