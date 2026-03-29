"""K695: EWMA Optimal Lambda for VT Strategy (Lag-Corrected)

Motivation:
K687/K690 showed EWMA VT is the most lag-robust strategy (ratio 0.756) and
closest to BH 50/50 on Sharpe. The standard lambda=0.94 is from RiskMetrics
(1996). Is it actually optimal for our VT use case?

Analysis:
  1. Lambda sweep: λ ∈ {0.88, 0.90, 0.92, 0.94, 0.96, 0.97, 0.98, 0.99}
  2. EWMA VT with PROPER LAG:
     - sigma_t = sqrt(lambda * sigma_{t-1}^2 + (1-lambda) * r_{t-1}^2)
     - weight_t = target_vol / sigma_{t-1}  (USE t-1 sigma for t's return!)
  3. Apply to 50/50 SPY/GLD portfolio
  4. Full backtest 2007-2026, NET of 5bp TX costs
  5. Metrics: Sharpe, MDD, CAGR, Sortino, Calmar, lag robustness ratio
  6. Cross-OOS for best 3 lambdas

Data source: yfinance (SPY, GLD, ^VIX)
Period: 2006-01-01 to 2026-03-27
Evaluation: 2007-01-03 to 2026-03-27 (1y warmup for EWMA burn-in)

ALL signals are PROPERLY LAGGED (signal from t-1, return at t). No exceptions.

References:
  - K687: Definitive lag-corrected strategy ranking (EWMA VT Sharpe ~0.38)
  - K690: Weight smoothness analysis (EWMA VT lag ratio 0.756)
  - RiskMetrics (1996): Technical Document (EWMA λ=0.94 original)
  - JPMorgan (1996): RiskMetrics — Technical Document, 4th ed.
  - Zumbach (2007): The RiskMetrics 2006 Methodology
  - Fleming, Kirby & Ostdiek (2001): The Economic Value of Volatility Timing
  - Kirby & Ostdiek (2012): It's All in the Timing
  - Harvey et al. (2016): ...and the Cross-Section of Expected Returns (t>3.0)
  - Diebold & Mariano (1995): Comparing Predictive Accuracy

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
EVAL_START = "2007-01-03"       # 1y warmup for EWMA burn-in
TC_BPS = 5                     # Transaction cost in basis points (one-way)
RF_ANNUAL = 0.04               # Risk-free rate for Sharpe calculation
RF_DAILY = RF_ANNUAL / 252
TARGET_VOL = 0.10              # 10% annualized target volatility
WEIGHT_CAP = 1.5               # Max weight
BOOTSTRAP_REPS = 5000
RESULTS_FILE = Path(__file__).parent / "k695_results.json"

# Lambda sweep values
LAMBDAS = [0.88, 0.90, 0.92, 0.94, 0.96, 0.97, 0.98, 0.99]

# Lag values for robustness analysis
LAGS = [0, 1, 2, 3, 5]


# ============================================================================
# Data Download
# ============================================================================
def download_data():
    """Download SPY, GLD, VIX data from yfinance."""
    print("=" * 70)
    print("K695: EWMA OPTIMAL LAMBDA FOR VT STRATEGY (LAG-CORRECTED)")
    print("=" * 70)
    print("\nDownloading data from yfinance...")

    tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
    raw = {}

    for name, ticker in tickers.items():
        df = yf.download(ticker, start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        raw[name] = df
        print(f"  {name}: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")

    spy_ret = raw["SPY"]["Close"].pct_change().dropna()
    spy_ret.name = "spy_ret"
    gld_ret = raw["GLD"]["Close"].pct_change().dropna()
    gld_ret.name = "gld_ret"
    vix_close = raw["VIX"]["Close"].copy()
    vix_close.name = "vix"

    data = pd.concat([spy_ret, gld_ret, vix_close], axis=1).dropna()

    # 50/50 portfolio returns
    data["port_ret"] = 0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]

    print(f"\n  Merged data: {len(data)} rows, {data.index[0].date()} to {data.index[-1].date()}")
    print(f"\n  Descriptive statistics:")
    print(f"    SPY daily return: mean={data['spy_ret'].mean()*252*100:.2f}% ann, "
          f"std={data['spy_ret'].std()*np.sqrt(252)*100:.2f}% ann")
    print(f"    GLD daily return: mean={data['gld_ret'].mean()*252*100:.2f}% ann, "
          f"std={data['gld_ret'].std()*np.sqrt(252)*100:.2f}% ann")
    print(f"    50/50 portfolio: mean={data['port_ret'].mean()*252*100:.2f}% ann, "
          f"std={data['port_ret'].std()*np.sqrt(252)*100:.2f}% ann")
    print(f"    VIX: mean={data['vix'].mean():.2f}, std={data['vix'].std():.2f}, "
          f"min={data['vix'].min():.2f}, max={data['vix'].max():.2f}")

    return data


# ============================================================================
# EWMA Volatility with Proper Lag
# ============================================================================
def compute_ewma_vt_weights(port_returns, lam, target_vol=TARGET_VOL,
                             weight_cap=WEIGHT_CAP, lag=1):
    """Compute EWMA VT weights with PROPER LAGGING.

    EWMA variance update:
        sigma^2_t = lambda * sigma^2_{t-1} + (1-lambda) * r^2_{t-1}

    Weight at time t:
        w_t = target_vol / (sigma_{t-lag} * sqrt(252))

    With lag=1 (default): we use sigma from the PREVIOUS day to set
    today's weight. This is the implementable version — no lookahead.

    Parameters
    ----------
    port_returns : pd.Series
        Daily portfolio returns (50/50 SPY/GLD)
    lam : float
        EWMA decay factor (0 < lambda < 1)
    target_vol : float
        Annualized target volatility (default: 0.10 = 10%)
    weight_cap : float
        Maximum weight (default: 1.5)
    lag : int
        Number of days to lag the signal (default: 1)

    Returns
    -------
    pd.Series
        Lagged weight series
    """
    n = len(port_returns)
    var = np.zeros(n)
    ret_vals = port_returns.values

    # Initialize with squared first return
    var[0] = ret_vals[0] ** 2

    # EWMA recursion: var[t] = lam * var[t-1] + (1-lam) * r[t-1]^2
    # Note: r[t-1] is used, not r[t] — this is the standard EWMA formulation
    # where today's variance estimate uses yesterday's return
    for i in range(1, n):
        var[i] = lam * var[i - 1] + (1 - lam) * ret_vals[i - 1] ** 2

    # Convert to annualized vol
    vol_daily = np.sqrt(np.maximum(var, 1e-12))
    vol_ann = pd.Series(vol_daily * np.sqrt(252), index=port_returns.index)

    # Compute raw weights: target_vol / vol_ann
    raw_weights = np.minimum(target_vol / vol_ann, weight_cap)

    # Create Series
    raw_w_series = pd.Series(raw_weights, index=port_returns.index, name=f"w_ewma_{lam}")

    # Apply lag: shift by 'lag' days
    # lag=1: use yesterday's weight for today's return (implementable)
    # lag=0: use today's weight for today's return (lookahead — for comparison only)
    lagged_w = raw_w_series.shift(lag)

    return lagged_w, raw_w_series, vol_ann


# ============================================================================
# Backtest Engine
# ============================================================================
def backtest_strategy(data, weights, name, tc_bps=TC_BPS, eval_start=EVAL_START):
    """Backtest an EWMA VT strategy with given weight series.

    Strategy: w * (50/50 SPY/GLD) + (1-w) * rf
    Returns are NET of transaction costs.
    """
    eval_mask = data.index >= eval_start
    df = data[eval_mask].copy()
    w = weights[eval_mask].copy()

    if len(df) == 0:
        return None

    port_ret = df["port_ret"].values
    w_vals = w.values

    # Compute returns
    gross_returns = np.zeros(len(df))
    net_returns = np.zeros(len(df))
    tc_rate = tc_bps / 10000.0
    prev_w = 0.0

    for i in range(len(df)):
        wi = w_vals[i]
        if np.isnan(wi):
            wi = prev_w  # carry forward if NaN

        gross_returns[i] = wi * port_ret[i] + (1 - wi) * RF_DAILY
        tc = abs(wi - prev_w) * tc_rate
        net_returns[i] = gross_returns[i] - tc
        prev_w = wi

    # Compute metrics on NET returns
    cum_ret = np.cumprod(1 + net_returns)
    total_ret = cum_ret[-1] - 1
    n_years = len(df) / 252.0
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    ann_ret = np.mean(net_returns) * 252
    ann_vol = np.std(net_returns, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = (cum_ret - running_max) / running_max
    mdd = float(np.min(drawdowns))

    # Calmar ratio
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino ratio
    downside = net_returns[net_returns < 0]
    downside_vol = (np.std(downside, ddof=1) * np.sqrt(252)
                    if len(downside) > 0 else ann_vol)
    sortino = (ann_ret - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0

    # Weight stats
    valid_w = w_vals[~np.isnan(w_vals)]
    avg_weight = float(np.mean(valid_w)) if len(valid_w) > 0 else 0

    # Weight autocorrelation (smoothness proxy)
    if len(valid_w) > 1:
        weight_autocorr = float(np.corrcoef(valid_w[:-1], valid_w[1:])[0, 1])
    else:
        weight_autocorr = np.nan

    # Annual turnover
    weight_changes = np.abs(np.diff(valid_w))
    avg_daily_turnover = float(np.mean(weight_changes)) if len(weight_changes) > 0 else 0
    annual_turnover = avg_daily_turnover * 252

    return {
        "strategy": name,
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "mdd_pct": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "ann_ret_pct": round(ann_ret * 100, 2),
        "avg_weight": round(avg_weight, 3),
        "weight_autocorr": round(weight_autocorr, 4) if not np.isnan(weight_autocorr) else None,
        "annual_turnover": round(annual_turnover, 4),
        "total_return_pct": round(total_ret * 100, 2),
        "n_days": len(df),
        "n_years": round(n_years, 1),
        "net_returns": net_returns,   # Keep for DM test
    }


# ============================================================================
# Statistical Tests
# ============================================================================
def dm_test_hac(returns_1, returns_2):
    """Diebold-Mariano test with Newey-West HAC standard errors.

    Tests H0: E[d_t] = 0 where d_t = r_{1,t} - r_{2,t}
    Positive t-stat → strategy 1 outperforms strategy 2.
    """
    d = returns_1 - returns_2
    n = len(d)

    if n < 30:
        return {"t_stat": np.nan, "p_value": np.nan, "mean_diff_bps": np.nan,
                "n_obs": n, "harvey_pass": False}

    mean_d = np.mean(d)

    # Newey-West HAC variance estimation
    bandwidth = max(1, int(n ** (1 / 3)))
    gamma_0 = np.var(d, ddof=1)
    nw_var = gamma_0

    for k in range(1, bandwidth + 1):
        gamma_k = np.mean((d[k:] - mean_d) * (d[:-k] - mean_d))
        weight = 1 - k / (bandwidth + 1)  # Bartlett kernel
        nw_var += 2 * weight * gamma_k

    se = np.sqrt(max(nw_var, 0) / n)
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


def bootstrap_sharpe_ci(net_returns_a, net_returns_b, n_reps=BOOTSTRAP_REPS):
    """Bootstrap 95% CI for Sharpe difference between two strategies."""
    n = len(net_returns_a)
    sharpe_diffs = np.zeros(n_reps)

    for b in range(n_reps):
        idx = np.random.choice(n, size=n, replace=True)
        a = net_returns_a[idx]
        b_arr = net_returns_b[idx]

        s_a = ((np.mean(a) * 252 - RF_ANNUAL) /
               (np.std(a, ddof=1) * np.sqrt(252))) if np.std(a) > 0 else 0
        s_b = ((np.mean(b_arr) * 252 - RF_ANNUAL) /
               (np.std(b_arr, ddof=1) * np.sqrt(252))) if np.std(b_arr) > 0 else 0
        sharpe_diffs[b] = s_a - s_b

    return {
        "mean_diff": round(float(np.mean(sharpe_diffs)), 4),
        "median_diff": round(float(np.median(sharpe_diffs)), 4),
        "ci_95": [round(float(np.percentile(sharpe_diffs, 2.5)), 4),
                  round(float(np.percentile(sharpe_diffs, 97.5)), 4)],
        "ci_90": [round(float(np.percentile(sharpe_diffs, 5)), 4),
                  round(float(np.percentile(sharpe_diffs, 95)), 4)],
        "pct_positive": round(float(np.mean(sharpe_diffs > 0) * 100), 1),
        "significant_95": float(np.percentile(sharpe_diffs, 2.5)) > 0,
        "significant_90": float(np.percentile(sharpe_diffs, 5)) > 0,
        "n_reps": n_reps,
    }


# ============================================================================
# Lambda Sweep
# ============================================================================
def run_lambda_sweep(data):
    """Run full lambda sweep with lag=1 (implementable)."""
    print("\n" + "=" * 70)
    print("LAMBDA SWEEP (ALL LAG=1, NET 5bp TX)")
    print("=" * 70)

    # Also compute BH 50/50 benchmark
    eval_mask = data.index >= EVAL_START
    df_eval = data[eval_mask]
    port_ret_eval = df_eval["port_ret"].values
    bh_returns = port_ret_eval.copy()  # BH = 100% in 50/50 portfolio
    bh_cum = np.cumprod(1 + bh_returns)
    bh_total = bh_cum[-1] - 1
    bh_n_years = len(df_eval) / 252.0
    bh_cagr = (1 + bh_total) ** (1 / bh_n_years) - 1
    bh_ann_ret = np.mean(bh_returns) * 252
    bh_ann_vol = np.std(bh_returns, ddof=1) * np.sqrt(252)
    bh_sharpe = (bh_ann_ret - RF_ANNUAL) / bh_ann_vol
    bh_running_max = np.maximum.accumulate(bh_cum)
    bh_dd = (bh_cum - bh_running_max) / bh_running_max
    bh_mdd = float(np.min(bh_dd))

    bh_info = {
        "strategy": "BH 50/50",
        "sharpe": round(bh_sharpe, 3),
        "cagr_pct": round(bh_cagr * 100, 2),
        "mdd_pct": round(bh_mdd * 100, 2),
        "ann_vol_pct": round(bh_ann_vol * 100, 2),
        "ann_ret_pct": round(bh_ann_ret * 100, 2),
    }
    print(f"\n  Benchmark (BH 50/50): Sharpe={bh_sharpe:.3f}, "
          f"CAGR={bh_cagr*100:.2f}%, MDD={bh_mdd*100:.2f}%")

    results = {}
    for lam in LAMBDAS:
        print(f"\n  --- λ = {lam} ---")
        # Compute EWMA VT weights with lag=1
        lagged_w, raw_w, vol_ann = compute_ewma_vt_weights(
            data["port_ret"], lam=lam, lag=1)

        # Backtest
        result = backtest_strategy(data, lagged_w, f"EWMA_VT_λ={lam}", tc_bps=TC_BPS)

        if result is None:
            print(f"    Skipped (no data)")
            continue

        # DM test vs BH 50/50
        dm = dm_test_hac(result["net_returns"], bh_returns)

        # Vol stats — vol_ann is a pd.Series from compute_ewma_vt_weights
        eval_vol = vol_ann[eval_mask]
        eval_vol_vals = eval_vol.values if hasattr(eval_vol, 'values') else eval_vol
        vol_stats = {
            "mean_vol_pct": round(float(np.mean(eval_vol_vals) * 100), 2),
            "median_vol_pct": round(float(np.median(eval_vol_vals) * 100), 2),
            "std_vol_pct": round(float(np.std(eval_vol_vals) * 100), 2),
        }

        result_clean = {k: v for k, v in result.items() if k != "net_returns"}
        result_clean["lambda"] = lam
        result_clean["dm_vs_bh"] = dm
        result_clean["vol_stats"] = vol_stats

        results[str(lam)] = result_clean
        # Store net_returns for later cross-comparison
        results[str(lam)]["_net_returns"] = result["net_returns"]

        print(f"    Sharpe={result['sharpe']:.3f}, CAGR={result['cagr_pct']:.2f}%, "
              f"MDD={result['mdd_pct']:.2f}%, Sortino={result['sortino']:.3f}")
        print(f"    Avg weight={result['avg_weight']:.3f}, "
              f"Weight autocorr={result['weight_autocorr']}, "
              f"Annual TO={result['annual_turnover']:.4f}")
        print(f"    DM vs BH: t={dm['t_stat']:.3f}, p={dm['p_value']:.4f}, "
              f"Harvey pass={dm['harvey_pass']}")
        print(f"    Vol stats: mean={vol_stats['mean_vol_pct']:.2f}%, "
              f"std={vol_stats['std_vol_pct']:.2f}%")

    return results, bh_info, bh_returns


# ============================================================================
# Lag Robustness Analysis
# ============================================================================
def lag_robustness_analysis(data):
    """Compute Sharpe at different lags for each lambda.

    Lag robustness ratio = Sharpe(lag=1) / Sharpe(lag=0)
    Higher ratio = more robust to implementation lag.
    """
    print("\n" + "=" * 70)
    print("LAG ROBUSTNESS ANALYSIS")
    print("=" * 70)

    lag_results = {}

    for lam in LAMBDAS:
        lag_sharpes = {}
        for lag in LAGS:
            lagged_w, _, _ = compute_ewma_vt_weights(
                data["port_ret"], lam=lam, lag=lag)
            result = backtest_strategy(data, lagged_w,
                                        f"EWMA_VT_λ={lam}_lag={lag}",
                                        tc_bps=TC_BPS)
            if result:
                lag_sharpes[f"lag_{lag}"] = result["sharpe"]

        # Lag robustness ratio
        if "lag_0" in lag_sharpes and lag_sharpes["lag_0"] != 0:
            ratio_1_0 = lag_sharpes.get("lag_1", 0) / lag_sharpes["lag_0"]
        else:
            ratio_1_0 = np.nan

        lag_results[str(lam)] = {
            "sharpes_by_lag": lag_sharpes,
            "lag_robustness_ratio": round(float(ratio_1_0), 4) if not np.isnan(ratio_1_0) else None,
        }

        lag_str = ", ".join(f"lag{k.split('_')[1]}={v:.3f}"
                           for k, v in lag_sharpes.items())
        print(f"  λ={lam}: {lag_str}, ratio={ratio_1_0:.3f}")

    return lag_results


# ============================================================================
# Cross-OOS Validation
# ============================================================================
def cross_oos_validation(data, top_lambdas, bh_returns_full):
    """Cross-OOS validation with 5 non-overlapping periods for top 3 lambdas."""
    print("\n" + "=" * 70)
    print("CROSS-OOS VALIDATION (5 PERIODS)")
    print("=" * 70)

    oos_periods = {
        "OOS1_GFC":       ("2008-01-02", "2009-12-31"),
        "OOS2_Recovery":  ("2011-01-03", "2013-12-31"),
        "OOS3_LowVol":    ("2015-01-02", "2017-12-29"),
        "OOS4_COVID":     ("2020-01-02", "2021-12-31"),
        "OOS5_PostHike":  ("2023-01-03", "2024-12-31"),
    }

    all_results = {}

    for lam in top_lambdas:
        print(f"\n  --- λ = {lam} ---")
        strat_results = []

        for period_name, (start, end) in oos_periods.items():
            # Compute weights using FULL data up to end (EWMA needs history)
            # But evaluate only within the period
            lagged_w, _, _ = compute_ewma_vt_weights(
                data["port_ret"], lam=lam, lag=1)

            mask = (data.index >= start) & (data.index <= end)
            period_data = data[mask]

            if len(period_data) < 50:
                print(f"    {period_name}: skipped ({len(period_data)} days)")
                continue

            # Backtest on this period
            result = backtest_strategy(data, lagged_w, f"EWMA_VT_λ={lam}",
                                        tc_bps=TC_BPS, eval_start=start)
            # Trim to period
            period_mask_full = (data.index >= start) & (data.index <= end)
            period_net = result["net_returns"] if result else None

            # Need to re-backtest specifically for this period
            period_w = lagged_w[period_mask_full]
            period_result = backtest_strategy(
                data[period_mask_full], period_w,
                f"EWMA_VT_λ={lam}", tc_bps=TC_BPS,
                eval_start=start)

            # BH benchmark for this period
            bh_period_ret = data.loc[period_mask_full, "port_ret"].values

            if period_result is None or len(bh_period_ret) < 50:
                continue

            # BH Sharpe for period
            bh_ann_ret = np.mean(bh_period_ret) * 252
            bh_ann_vol = np.std(bh_period_ret, ddof=1) * np.sqrt(252)
            bh_sharpe = (bh_ann_ret - RF_ANNUAL) / bh_ann_vol if bh_ann_vol > 0 else 0

            # DM test
            dm = dm_test_hac(period_result["net_returns"], bh_period_ret)

            period_entry = {
                "period": period_name,
                "dates": f"{start} to {end}",
                "n_days": len(period_data),
                "sharpe": period_result["sharpe"],
                "cagr_pct": period_result["cagr_pct"],
                "mdd_pct": period_result["mdd_pct"],
                "avg_weight": period_result["avg_weight"],
                "bh_sharpe": round(bh_sharpe, 3),
                "sharpe_diff_vs_bh": round(period_result["sharpe"] - bh_sharpe, 4),
                "beats_bh": period_result["sharpe"] > bh_sharpe,
                "dm_t_stat": dm["t_stat"],
                "dm_p_value": dm["p_value"],
                "dm_harvey_pass": dm["harvey_pass"],
            }

            strat_results.append(period_entry)
            print(f"    {period_name}: Sharpe={period_result['sharpe']:.3f} vs "
                  f"BH={bh_sharpe:.3f}, diff={period_entry['sharpe_diff_vs_bh']:+.4f}, "
                  f"DM t={dm['t_stat']:.3f}")

        # Aggregate
        if strat_results:
            wins = sum(1 for r in strat_results if r["beats_bh"])
            sharpe_diffs = [r["sharpe_diff_vs_bh"] for r in strat_results]

            aggregate = {
                "n_periods": len(strat_results),
                "wins_vs_bh": wins,
                "losses_vs_bh": len(strat_results) - wins,
                "avg_sharpe_diff": round(float(np.mean(sharpe_diffs)), 4),
                "min_sharpe_diff": round(float(np.min(sharpe_diffs)), 4),
                "max_sharpe_diff": round(float(np.max(sharpe_diffs)), 4),
                "consistent": wins == len(strat_results),
            }
            strat_results.append({"aggregate": aggregate})
            print(f"    AGGREGATE: {wins}/{len(strat_results)-1} periods beat BH, "
                  f"avg Sharpe diff = {aggregate['avg_sharpe_diff']:+.4f}")

        all_results[str(lam)] = strat_results

    return all_results


# ============================================================================
# Best Lambda Pair Comparison
# ============================================================================
def compare_best_lambdas(sweep_results, bh_returns):
    """Bootstrap comparison between top 3 lambdas and BH 50/50."""
    print("\n" + "=" * 70)
    print("BOOTSTRAP COMPARISON: TOP LAMBDAS vs BH 50/50")
    print("=" * 70)

    # Sort by Sharpe
    sorted_lambdas = sorted(
        [(k, v["sharpe"]) for k, v in sweep_results.items() if "_net_returns" in v],
        key=lambda x: x[1], reverse=True
    )

    comparisons = {}
    for lam_str, sharpe in sorted_lambdas[:3]:
        net_ret = sweep_results[lam_str]["_net_returns"]
        bs = bootstrap_sharpe_ci(net_ret, bh_returns)
        comparisons[lam_str] = bs
        print(f"  λ={lam_str}: Sharpe diff vs BH = {bs['mean_diff']:+.4f} "
              f"[{bs['ci_95'][0]:+.4f}, {bs['ci_95'][1]:+.4f}] 95% CI, "
              f"P(VT > BH) = {bs['pct_positive']:.1f}%")

    # Also compare best vs λ=0.94 (RiskMetrics default)
    if "0.94" in sweep_results and sorted_lambdas[0][0] != "0.94":
        best_lam = sorted_lambdas[0][0]
        best_ret = sweep_results[best_lam]["_net_returns"]
        rm_ret = sweep_results["0.94"]["_net_returns"]
        bs_best_vs_rm = bootstrap_sharpe_ci(best_ret, rm_ret)
        comparisons["best_vs_0.94"] = {
            "best_lambda": best_lam,
            "bootstrap": bs_best_vs_rm,
        }
        print(f"\n  Best (λ={best_lam}) vs RiskMetrics (λ=0.94):")
        print(f"    Sharpe diff = {bs_best_vs_rm['mean_diff']:+.4f} "
              f"[{bs_best_vs_rm['ci_95'][0]:+.4f}, {bs_best_vs_rm['ci_95'][1]:+.4f}] "
              f"95% CI")

    return comparisons


# ============================================================================
# Main
# ============================================================================
def main():
    """Run complete EWMA optimal lambda analysis."""
    print("\n" + "=" * 70)
    print("K695: EWMA OPTIMAL LAMBDA FOR VT STRATEGY")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    np.random.seed(42)

    # Step 1: Download data
    data = download_data()

    # Step 2: Lambda sweep (all lag=1)
    sweep_results, bh_info, bh_returns = run_lambda_sweep(data)

    # Step 3: Lag robustness analysis
    lag_results = lag_robustness_analysis(data)

    # Step 4: Find top 3 lambdas by NET Sharpe
    sorted_lambdas = sorted(
        [(k, v["sharpe"]) for k, v in sweep_results.items() if "sharpe" in v],
        key=lambda x: x[1], reverse=True
    )
    top_3_lambdas = [float(k) for k, _ in sorted_lambdas[:3]]
    print(f"\n  TOP 3 LAMBDAS BY NET SHARPE:")
    for rank, (lam_str, sharpe) in enumerate(sorted_lambdas[:3], 1):
        print(f"    #{rank}: λ={lam_str}, Sharpe={sharpe:.3f}")

    # Step 5: Cross-OOS validation for top 3
    oos_results = cross_oos_validation(data, top_3_lambdas, bh_returns)

    # Step 6: Bootstrap comparisons
    bootstrap_results = compare_best_lambdas(sweep_results, bh_returns)

    # ============================================================================
    # Summary
    # ============================================================================
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)

    print(f"\n  Benchmark: BH 50/50, Sharpe={bh_info['sharpe']:.3f}")
    print(f"\n  {'Lambda':>8} | {'Sharpe':>8} | {'CAGR%':>8} | {'MDD%':>8} | "
          f"{'Sortino':>8} | {'AvgW':>6} | {'WAutocorr':>10} | {'LagRatio':>9}")
    print("  " + "-" * 85)

    for lam in LAMBDAS:
        lam_str = str(lam)
        if lam_str in sweep_results:
            r = sweep_results[lam_str]
            lr = lag_results.get(lam_str, {})
            lag_ratio = lr.get("lag_robustness_ratio", "N/A")
            lag_ratio_str = f"{lag_ratio:.3f}" if isinstance(lag_ratio, float) else lag_ratio
            print(f"  {lam:>8.2f} | {r['sharpe']:>8.3f} | {r['cagr_pct']:>7.2f}% | "
                  f"{r['mdd_pct']:>7.2f}% | {r['sortino']:>8.3f} | "
                  f"{r['avg_weight']:>6.3f} | {r.get('weight_autocorr', 'N/A'):>10} | "
                  f"{lag_ratio_str:>9}")

    best_lam_str, best_sharpe = sorted_lambdas[0]
    print(f"\n  BEST LAMBDA: {best_lam_str} (Sharpe={best_sharpe:.3f})")
    print(f"  RiskMetrics λ=0.94 Sharpe: {sweep_results.get('0.94', {}).get('sharpe', 'N/A')}")

    # Is λ=0.94 actually the best?
    rm_sharpe = sweep_results.get("0.94", {}).get("sharpe", 0)
    if best_lam_str == "0.94":
        print("  CONCLUSION: RiskMetrics λ=0.94 IS the optimal lambda for VT.")
    elif abs(best_sharpe - rm_sharpe) < 0.02:
        print(f"  CONCLUSION: λ={best_lam_str} marginally better than 0.94 "
              f"(Δ={best_sharpe - rm_sharpe:+.3f}), practically equivalent.")
    else:
        print(f"  CONCLUSION: λ={best_lam_str} meaningfully better than 0.94 "
              f"(Δ={best_sharpe - rm_sharpe:+.3f}).")

    # ============================================================================
    # Save results
    # ============================================================================
    # Clean up net_returns (not JSON serializable)
    clean_sweep = {}
    for k, v in sweep_results.items():
        clean_v = {kk: vv for kk, vv in v.items() if kk != "_net_returns"}
        clean_sweep[k] = clean_v

    output = {
        "experiment_id": "K695",
        "title": "EWMA Optimal Lambda for VT Strategy (Lag-Corrected)",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{EVAL_START} to {END_DATE}",
        "methodology": {
            "ewma_formula": "sigma^2_t = lambda * sigma^2_{t-1} + (1-lambda) * r^2_{t-1}",
            "weight_formula": "w_t = min(target_vol / sigma_{t-1}, 1.5)",
            "lag": "ALL signals lagged by 1 day (implementable)",
            "portfolio": "50/50 SPY/GLD",
            "target_vol": TARGET_VOL,
            "weight_cap": WEIGHT_CAP,
            "tx_cost_bps": TC_BPS,
            "rf_annual": RF_ANNUAL,
        },
        "benchmark": bh_info,
        "lambda_sweep": clean_sweep,
        "lag_robustness": lag_results,
        "cross_oos": oos_results,
        "bootstrap_comparisons": bootstrap_results,
        "ranking": {
            "by_net_sharpe": [(k, v) for k, v in sorted_lambdas],
            "best_lambda": float(best_lam_str),
            "best_sharpe": best_sharpe,
            "riskmetrics_lambda": 0.94,
            "riskmetrics_sharpe": rm_sharpe,
        },
        "references": [
            "K687: Definitive lag-corrected strategy ranking",
            "K690: Weight smoothness and lag robustness analysis",
            "RiskMetrics (1996): Technical Document, JPMorgan",
            "Zumbach (2007): The RiskMetrics 2006 Methodology",
            "Fleming, Kirby & Ostdiek (2001): Economic Value of Volatility Timing, JFE",
            "Harvey et al. (2016): ...and the Cross-Section of Expected Returns",
        ],
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Results saved to: {RESULTS_FILE}")
    print(f"\n{'=' * 70}")
    print("K695 COMPLETE")
    print(f"{'=' * 70}")

    return output


if __name__ == "__main__":
    main()
