"""K687: Post-Correction Strategy Ranking — What ACTUALLY Works After All Bug Fixes

DEFINITIVE ranking of all VIX-based allocation strategies after fixing:
  - K686: VIX percentile lookahead bias (100% artifact)
  - K618/K619: KAN neural network bugs
  - K621/K623: MF2-GARCH estimation bugs

ALL signals are PROPERLY LAGGED (signal from t-1, return at t). No exceptions.

Strategies tested:
  a. 12/VIX:         w_t = min(12 / VIX_{t-1}, 1.5) on 50/50 SPY/GLD
  b. Piecewise:       VIX_{t-1}<15 → 100%, 15-20 → linear, ≥20 → 0% on 50/50
  c. P3-AGG Lookup:   VIX_{t-1}<15 → 80%, 15-25 → 45%, >25 → 10% on 50/50
  d. VIX Percentile:  w_t = 1 - percentile_rank(VIX_{t-1}, prior 252d) on 50/50
  e. EWMA VT:         sigma from EWMA(λ=0.94) lagged, target vol 10% on 50/50
  f. Buy-and-Hold 50/50 SPY/GLD (benchmark)
  g. Buy-and-Hold SPY (reference)

Data source: yfinance (SPY, GLD, ^VIX)
Period: 2006-01-01 to 2026-03-27
Evaluation: 2007-01-03 to 2026-03-27 (1y warmup for rolling stats)

Evaluation metrics (all on NET returns after 5bp TX):
  - Sharpe, CAGR, MDD, Sortino, Calmar
  - Diebold-Mariano test (NW HAC) vs BH 50/50 benchmark
  - Cross-OOS (5 periods) for top 3 strategies

References:
  - K686: Corrected VIX percentile (lookahead artifact confirmed)
  - K679-K685: VIX percentile series (all had lookahead bugs)
  - K618/K619: KAN bugs found by Codex
  - Copeland & Copeland (1999), Market Timing with VIX
  - Harvey et al. (2016), ...and the Cross-Section of Expected Returns (t>3.0)
  - Diebold & Mariano (1995), Comparing Predictive Accuracy
  - RiskMetrics (1996), Technical Document (EWMA λ=0.94)

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
EVAL_START = "2007-01-03"       # 1y warmup for rolling stats
ROLLING_WINDOW = 252            # 1 year for percentile / EWMA warmup
TC_BPS = 5                     # Transaction cost in basis points (one-way)
RF_ANNUAL = 0.04               # Risk-free rate for Sharpe calculation
RF_DAILY = RF_ANNUAL / 252
BOOTSTRAP_REPS = 5000           # Bootstrap replications for CI
EWMA_LAMBDA = 0.94             # RiskMetrics EWMA decay factor
TARGET_VOL = 0.10              # 10% annualized target volatility
VIX_12_CAP = 1.5               # Cap for 12/VIX weight


# ============================================================================
# Data Download
# ============================================================================
def download_data():
    """Download SPY, GLD, VIX data from yfinance."""
    print("=" * 70)
    print("DOWNLOADING DATA")
    print("=" * 70)

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
    print(f"\n  Merged data: {len(data)} rows, {data.index[0].date()} to {data.index[-1].date()}")

    # Descriptive stats
    print(f"\n  Descriptive statistics:")
    print(f"    SPY daily return: mean={data['spy_ret'].mean()*252*100:.2f}% ann, "
          f"std={data['spy_ret'].std()*np.sqrt(252)*100:.2f}% ann")
    print(f"    GLD daily return: mean={data['gld_ret'].mean()*252*100:.2f}% ann, "
          f"std={data['gld_ret'].std()*np.sqrt(252)*100:.2f}% ann")
    print(f"    VIX: mean={data['vix'].mean():.2f}, median={data['vix'].median():.2f}, "
          f"std={data['vix'].std():.2f}, min={data['vix'].min():.2f}, max={data['vix'].max():.2f}")

    return data


# ============================================================================
# Signal Computation (ALL LAGGED)
# ============================================================================
def compute_rolling_percentile_strict(vix_series, window=ROLLING_WINDOW):
    """Rolling percentile rank, STRICTLY excluding current value.

    For day i: rank VIX[i] against the PRIOR window values
    (VIX[i-window], ..., VIX[i-1]). Current VIX[i] NOT in comparison.
    """
    result = pd.Series(index=vix_series.index, dtype=float)
    vals = vix_series.values

    for i in range(window, len(vals)):
        prior_window = vals[i - window:i]  # [i-window, ..., i-1] exclusive of i
        current = vals[i]
        pct_rank = np.sum(prior_window <= current) / len(prior_window)
        result.iloc[i] = pct_rank

    return result


def compute_ewma_vol(returns, lam=EWMA_LAMBDA):
    """EWMA volatility (RiskMetrics), returns annualized vol series."""
    var = np.zeros(len(returns))
    var[0] = returns.iloc[0] ** 2 if len(returns) > 0 else 0.0001

    for i in range(1, len(returns)):
        var[i] = lam * var[i - 1] + (1 - lam) * returns.iloc[i] ** 2

    vol_daily = np.sqrt(var)
    vol_ann = vol_daily * np.sqrt(252)

    return pd.Series(vol_ann, index=returns.index, name="ewma_vol")


def compute_all_signals(data):
    """Compute ALL strategy signals, then LAG by 1 day.

    CRITICAL: Every signal is computed on day t, then shifted to apply on day t+1.
    This eliminates ALL lookahead bias.
    """
    print("\n" + "=" * 70)
    print("COMPUTING SIGNALS (ALL LAGGED BY 1 DAY)")
    print("=" * 70)

    vix = data["vix"]
    data = data.copy()

    # --- 50/50 portfolio returns (used as base for VT strategies) ---
    data["port_ret"] = 0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]

    # ================================================================
    # (a) 12/VIX: w = min(12 / VIX, cap)
    # ================================================================
    raw_12vix = np.minimum(12.0 / vix, VIX_12_CAP)
    data["w_12vix"] = raw_12vix.shift(1)  # LAG
    print(f"  12/VIX: raw mean weight = {raw_12vix.mean():.3f}, cap = {VIX_12_CAP}")

    # ================================================================
    # (b) Piecewise: VIX<15 → 100%, 15-20 → linear, ≥20 → 0%
    # ================================================================
    def piecewise_weight(v):
        if v < 15:
            return 1.0
        elif v < 20:
            return 1.0 - (v - 15) / (20 - 15)  # Linear from 100% to 0%
        else:
            return 0.0

    raw_piecewise = vix.apply(piecewise_weight)
    data["w_piecewise"] = raw_piecewise.shift(1)  # LAG
    print(f"  Piecewise: raw mean weight = {raw_piecewise.mean():.3f}")

    # ================================================================
    # (c) P3-AGG Lookup: VIX<15 → 80%, 15-25 → 45%, >25 → 10%
    # ================================================================
    def p3agg_weight(v):
        if v < 15:
            return 0.80
        elif v <= 25:
            return 0.45
        else:
            return 0.10

    raw_p3agg = vix.apply(p3agg_weight)
    data["w_p3agg"] = raw_p3agg.shift(1)  # LAG
    print(f"  P3-AGG: raw mean weight = {raw_p3agg.mean():.3f}")

    # ================================================================
    # (d) VIX Percentile (lagged): w = 1 - percentile_rank(VIX, prior 252d)
    # ================================================================
    print("  Computing rolling percentile (strict, 252d)...")
    raw_percentile = compute_rolling_percentile_strict(vix, ROLLING_WINDOW)
    raw_pct_weight = 1.0 - raw_percentile
    data["w_percentile"] = raw_pct_weight.shift(1)  # LAG
    valid_pct = raw_pct_weight.dropna()
    print(f"  Percentile: raw mean weight = {valid_pct.mean():.3f}, "
          f"{len(valid_pct)} valid values")

    # ================================================================
    # (e) EWMA VT: target vol / realized vol (on 50/50 portfolio)
    # ================================================================
    print("  Computing EWMA vol (λ=0.94)...")
    ewma_vol = compute_ewma_vol(data["port_ret"], EWMA_LAMBDA)
    # Target vol weight: w = target_vol / realized_vol, capped at 1.5
    raw_ewma_w = np.minimum(TARGET_VOL / ewma_vol.replace(0, np.nan), 1.5)
    data["w_ewma_vt"] = raw_ewma_w.shift(1)  # LAG
    valid_ewma = raw_ewma_w.dropna()
    print(f"  EWMA VT: raw mean weight = {valid_ewma.mean():.3f}, "
          f"mean vol = {ewma_vol.mean()*100:.2f}% ann")

    # ================================================================
    # (f) Buy-and-Hold 50/50 (constant weight = 1.0)
    # ================================================================
    data["w_bh5050"] = 1.0  # No lag needed — constant
    print(f"  BH 50/50: constant weight = 1.0")

    # ================================================================
    # (g) Buy-and-Hold SPY (different portfolio: 100% SPY, w=1.0)
    # ================================================================
    data["w_bhspy"] = 1.0   # Handled specially in backtest
    print(f"  BH SPY: constant weight = 1.0 (100% SPY, no GLD)")

    # Report eval-period coverage
    print(f"\n  Signal coverage in eval period ({EVAL_START} onwards):")
    eval_mask = data.index >= EVAL_START
    for col in ["w_12vix", "w_piecewise", "w_p3agg", "w_percentile", "w_ewma_vt"]:
        valid = data.loc[eval_mask, col].notna().sum()
        total = eval_mask.sum()
        print(f"    {col}: {valid}/{total} valid ({valid/total*100:.1f}%)")

    return data


# ============================================================================
# Backtest Engine
# ============================================================================
def backtest_strategy(data, weight_col, name, tc_bps=TC_BPS,
                      eval_start=EVAL_START, use_spy_only=False):
    """Backtest a strategy with given LAGGED weight column.

    For most strategies: w * (50/50 SPY/GLD) + (1-w) * rf
    For BH SPY: w * (100% SPY) + (1-w) * rf

    Returns are NET of transaction costs.
    """
    eval_mask = data.index >= eval_start
    df = data[eval_mask].copy()

    if len(df) == 0:
        return None

    weights = df[weight_col].values
    spy_ret = df["spy_ret"].values
    gld_ret = df["gld_ret"].values

    # Base portfolio
    if use_spy_only:
        portfolio_ret = spy_ret
    else:
        portfolio_ret = 0.5 * spy_ret + 0.5 * gld_ret

    # Compute returns
    gross_returns = np.zeros(len(df))
    net_returns = np.zeros(len(df))
    tc_rate = tc_bps / 10000.0
    prev_w = 0.0

    for i in range(len(df)):
        w = weights[i]
        if np.isnan(w):
            w = prev_w  # carry forward if NaN

        gross_returns[i] = w * portfolio_ret[i] + (1 - w) * RF_DAILY
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
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = (cum_ret - running_max) / running_max
    mdd = float(np.min(drawdowns))

    # Calmar ratio
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino ratio (downside deviation)
    downside = net_returns[net_returns < 0]
    downside_vol = (np.std(downside, ddof=1) * np.sqrt(252)
                    if len(downside) > 0 else ann_vol)
    sortino = (ann_ret - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0

    # Average weight
    valid_w = weights[~np.isnan(weights)]
    avg_weight = float(np.mean(valid_w)) if len(valid_w) > 0 else 0

    # Annual turnover
    weight_changes = np.abs(np.diff(valid_w))
    avg_daily_turnover = float(np.mean(weight_changes)) if len(weight_changes) > 0 else 0
    annual_turnover = avg_daily_turnover * 252

    # Total TX cost drag (annualized bps)
    all_changes = np.abs(np.diff(np.concatenate([[0], valid_w])))
    total_tc_drag_ann = float(np.mean(all_changes) * tc_rate * 252 * 10000)

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
        "annual_turnover": round(annual_turnover, 2),
        "tc_drag_bps_ann": round(total_tc_drag_ann, 2),
        "total_return_pct": round(total_ret * 100, 2),
        "n_days": len(df),
        "n_years": round(n_years, 1),
        "net_returns": net_returns,    # Keep for DM test
        "gross_returns": gross_returns,
    }


# ============================================================================
# Statistical Tests
# ============================================================================
def dm_test_hac(returns_1, returns_2, h=1):
    """Diebold-Mariano test with Newey-West HAC standard errors.

    Tests H0: E[d_t] = 0 where d_t = r_{1,t} - r_{2,t}
    Positive t-stat → strategy 1 outperforms strategy 2.
    Uses NET returns (after TX costs).
    Bartlett kernel, bandwidth = int(n^(1/3)).
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
# Cross-OOS Validation
# ============================================================================
def cross_oos_validation(data, top_strategies):
    """Cross-OOS validation with 5 non-overlapping periods for top strategies.

    Each strategy is tested on 5 distinct market regimes.
    """
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

    for strat_name, weight_col, use_spy_only in top_strategies:
        strat_results = []
        print(f"\n  --- {strat_name} ---")

        for period_name, (start, end) in oos_periods.items():
            mask = (data.index >= start) & (data.index <= end)
            period_data = data[mask]

            if len(period_data) < 50:
                print(f"    {period_name}: skipped ({len(period_data)} days)")
                continue

            result = backtest_strategy(period_data, weight_col, strat_name,
                                       tc_bps=TC_BPS, eval_start=start,
                                       use_spy_only=use_spy_only)
            bh_result = backtest_strategy(period_data, "w_bh5050", "BH 50/50",
                                          tc_bps=0, eval_start=start)

            if result is None or bh_result is None:
                continue

            dm = dm_test_hac(result["net_returns"], bh_result["net_returns"])

            period_result = {
                "period": period_name,
                "dates": f"{start} to {end}",
                "n_days": len(period_data),
                "sharpe": result["sharpe"],
                "cagr_pct": result["cagr_pct"],
                "mdd_pct": result["mdd_pct"],
                "avg_weight": result["avg_weight"],
                "bh_sharpe": bh_result["sharpe"],
                "bh_cagr_pct": bh_result["cagr_pct"],
                "sharpe_diff_vs_bh": round(result["sharpe"] - bh_result["sharpe"], 4),
                "beats_bh": result["sharpe"] > bh_result["sharpe"],
                "dm_t_stat": dm["t_stat"],
                "dm_p_value": dm["p_value"],
                "dm_harvey_pass": dm["harvey_pass"],
            }

            strat_results.append(period_result)
            print(f"    {period_name}: Sharpe={result['sharpe']:.3f} vs "
                  f"BH={bh_result['sharpe']:.3f}, "
                  f"diff={period_result['sharpe_diff_vs_bh']:+.4f}, "
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
                "std_sharpe_diff": round(float(np.std(sharpe_diffs)), 4),
                "robustness": {
                    "win_rate_4of5": wins >= 4,
                    "avg_improvement_positive": float(np.mean(sharpe_diffs)) > 0,
                    "no_catastrophic_loss": float(np.min(sharpe_diffs)) > -0.5,
                    "PASS": (wins >= 4
                             and float(np.mean(sharpe_diffs)) > 0
                             and float(np.min(sharpe_diffs)) > -0.5),
                },
            }

            print(f"  AGGREGATE: {wins}/{len(strat_results)} wins vs BH, "
                  f"avg diff={aggregate['avg_sharpe_diff']:+.4f}, "
                  f"PASS={aggregate['robustness']['PASS']}")
        else:
            aggregate = {"error": "No valid OOS periods"}

        all_results[strat_name] = {
            "periods": strat_results,
            "aggregate": aggregate,
        }

    return all_results


# ============================================================================
# Main Experiment
# ============================================================================
def main():
    print("=" * 70)
    print("K687: POST-CORRECTION DEFINITIVE STRATEGY RANKING")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"All signals LAGGED by 1 day. TX cost: {TC_BPS}bp one-way.")
    print(f"Risk-free: {RF_ANNUAL*100:.1f}% annual")
    print()

    np.random.seed(42)

    # ================================
    # Step 1: Download data
    # ================================
    data = download_data()

    # ================================
    # Step 2: Compute all signals
    # ================================
    data = compute_all_signals(data)

    # ================================
    # Step 3: Full-sample backtest
    # ================================
    print("\n" + "=" * 70)
    print("FULL-SAMPLE BACKTEST (2007-2026, NET of 5bp TX)")
    print("=" * 70)

    strategies = [
        ("12/VIX (cap 1.5)",     "w_12vix",     False),
        ("Piecewise VT",         "w_piecewise", False),
        ("P3-AGG Lookup",        "w_p3agg",     False),
        ("VIX Percentile",       "w_percentile", False),
        ("EWMA VT (λ=0.94)",    "w_ewma_vt",   False),
        ("BH 50/50 SPY/GLD",    "w_bh5050",    False),
        ("BH SPY",              "w_bhspy",     True),
    ]

    results = []
    for name, weight_col, use_spy in strategies:
        r = backtest_strategy(data, weight_col, name,
                              tc_bps=TC_BPS if name not in ["BH 50/50 SPY/GLD", "BH SPY"] else 0,
                              use_spy_only=use_spy)
        if r is not None:
            results.append(r)

    # Print summary table
    print(f"\n{'Strategy':<25} {'Sharpe':>7} {'CAGR%':>7} {'MDD%':>8} "
          f"{'Sortino':>8} {'Calmar':>7} {'AvgW':>6} {'TO/yr':>7}")
    print("-" * 85)
    for r in sorted(results, key=lambda x: x["sharpe"], reverse=True):
        print(f"{r['strategy']:<25} {r['sharpe']:>7.3f} {r['cagr_pct']:>7.2f} "
              f"{r['mdd_pct']:>8.2f} {r['sortino']:>8.3f} {r['calmar']:>7.3f} "
              f"{r['avg_weight']:>6.3f} {r['annual_turnover']:>7.2f}")

    # ================================
    # Step 4: DM tests vs BH 50/50
    # ================================
    print("\n" + "=" * 70)
    print("DM TESTS vs BH 50/50 (NW HAC, on NET returns)")
    print("=" * 70)

    bh_result = next(r for r in results if "BH 50/50" in r["strategy"])
    bh_net = bh_result["net_returns"]

    dm_results = {}
    for r in results:
        if "BH 50/50" in r["strategy"]:
            continue
        dm = dm_test_hac(r["net_returns"], bh_net)
        dm_results[r["strategy"]] = dm
        sig = "***" if dm["harvey_pass"] else ("**" if dm["p_value"] < 0.01 else
               ("*" if dm["p_value"] < 0.05 else ""))
        print(f"  {r['strategy']:<25} t={dm['t_stat']:>7.4f}, p={dm['p_value']:.6f}, "
              f"diff={dm['mean_diff_bps']:>6.2f}bps/day {sig}")

    # ================================
    # Step 5: Pairwise DM tests (top strategies)
    # ================================
    print("\n" + "=" * 70)
    print("PAIRWISE DM TESTS (top active strategies)")
    print("=" * 70)

    active_strats = [r for r in results
                     if r["strategy"] not in ["BH 50/50 SPY/GLD", "BH SPY"]]
    active_strats.sort(key=lambda x: x["sharpe"], reverse=True)

    pairwise_dm = {}
    for i in range(len(active_strats)):
        for j in range(i + 1, len(active_strats)):
            a = active_strats[i]
            b = active_strats[j]
            dm = dm_test_hac(a["net_returns"], b["net_returns"])
            key = f"{a['strategy']} vs {b['strategy']}"
            pairwise_dm[key] = dm
            sig = "***" if dm["harvey_pass"] else ""
            print(f"  {key:<50} t={dm['t_stat']:>7.4f} {sig}")

    # ================================
    # Step 6: Bootstrap CIs for top vs BH
    # ================================
    print("\n" + "=" * 70)
    print("BOOTSTRAP SHARPE DIFFERENCE CIs (top strategies vs BH 50/50)")
    print("=" * 70)

    bootstrap_results = {}
    for r in active_strats[:3]:  # Top 3
        print(f"  Bootstrapping {r['strategy']}...", end=" ", flush=True)
        bs = bootstrap_sharpe_ci(r["net_returns"], bh_net, BOOTSTRAP_REPS)
        bootstrap_results[r["strategy"]] = bs
        print(f"Sharpe diff = {bs['mean_diff']:.4f}, "
              f"95% CI = [{bs['ci_95'][0]:.4f}, {bs['ci_95'][1]:.4f}], "
              f"P(positive) = {bs['pct_positive']:.1f}%")

    # ================================
    # Step 7: Cross-OOS for top 3
    # ================================
    # Identify top 3 active strategies by Sharpe
    top3 = [(r["strategy"],
             next(wc for n, wc, _ in strategies if n == r["strategy"]),
             next(spy for n, _, spy in strategies if n == r["strategy"]))
            for r in active_strats[:3]]

    cross_oos_results = cross_oos_validation(data, top3)

    # ================================
    # Step 8: Definitive Ranking & Conclusion
    # ================================
    print("\n" + "=" * 70)
    print("DEFINITIVE RANKING (after ALL bug fixes)")
    print("=" * 70)

    ranking = sorted(results, key=lambda x: x["sharpe"], reverse=True)
    for i, r in enumerate(ranking, 1):
        dm_info = dm_results.get(r["strategy"], {})
        t = dm_info.get("t_stat", "—")
        sig = ""
        if isinstance(t, float):
            sig = " (Harvey PASS)" if abs(t) > 3.0 else ""
            t = f"{t:.3f}"
        print(f"  #{i} {r['strategy']:<25} Sharpe={r['sharpe']:.3f}, "
              f"CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%, "
              f"DM t={t}{sig}")

    # ================================
    # Prepare results JSON
    # ================================

    # Clean results (remove numpy arrays)
    clean_results = []
    for r in ranking:
        clean_r = {k: v for k, v in r.items()
                   if k not in ("net_returns", "gross_returns")}
        clean_results.append(clean_r)

    output = {
        "experiment_id": "K687",
        "title": "Post-Correction Definitive Strategy Ranking",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "description": (
            "Definitive ranking of all VIX-based allocation strategies "
            "after fixing lookahead bias (K686), KAN bugs (K618/K619), "
            "and MF2-GARCH bugs (K621/K623). "
            "ALL signals properly lagged by 1 day."
        ),
        "data_source": "yfinance",
        "data_period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{EVAL_START} to {END_DATE}",
        "configuration": {
            "tx_cost_bps": TC_BPS,
            "rf_annual": RF_ANNUAL,
            "ewma_lambda": EWMA_LAMBDA,
            "target_vol": TARGET_VOL,
            "vix_12_cap": VIX_12_CAP,
            "rolling_window": ROLLING_WINDOW,
            "bootstrap_reps": BOOTSTRAP_REPS,
            "signal_lag": "1 day (ALL strategies)",
        },
        "descriptive_stats": {
            "spy_ann_return_pct": round(data["spy_ret"].mean() * 252 * 100, 2),
            "spy_ann_vol_pct": round(data["spy_ret"].std() * np.sqrt(252) * 100, 2),
            "gld_ann_return_pct": round(data["gld_ret"].mean() * 252 * 100, 2),
            "gld_ann_vol_pct": round(data["gld_ret"].std() * np.sqrt(252) * 100, 2),
            "vix_mean": round(float(data["vix"].mean()), 2),
            "vix_median": round(float(data["vix"].median()), 2),
            "vix_std": round(float(data["vix"].std()), 2),
            "n_days_total": len(data),
        },
        "full_sample_ranking": clean_results,
        "dm_tests_vs_bh5050": dm_results,
        "pairwise_dm_tests": pairwise_dm,
        "bootstrap_sharpe_ci": bootstrap_results,
        "cross_oos_top3": cross_oos_results,
        "definitive_answer": {
            "best_strategy": ranking[0]["strategy"],
            "best_sharpe": ranking[0]["sharpe"],
            "best_cagr": ranking[0]["cagr_pct"],
            "best_mdd": ranking[0]["mdd_pct"],
            "runner_up": ranking[1]["strategy"],
            "runner_up_sharpe": ranking[1]["sharpe"],
            "key_findings": [
                f"After fixing ALL bugs and properly lagging all signals, "
                f"the best strategy is {ranking[0]['strategy']} "
                f"(Sharpe={ranking[0]['sharpe']:.3f})",
                f"DM test vs BH 50/50: "
                f"t={dm_results.get(ranking[0]['strategy'], {}).get('t_stat', 'N/A')}",
                f"Runner-up is {ranking[1]['strategy']} "
                f"(Sharpe={ranking[1]['sharpe']:.3f})",
                ("VIX Percentile with proper lag shows "
                 f"Sharpe={next((r['sharpe'] for r in ranking if r['strategy']=='VIX Percentile'), 'N/A')} "
                 "— the K679 'breakthrough' of Sharpe=1.68 was 100% lookahead artifact"),
            ],
            "corrections_applied": [
                "K686: VIX percentile same-day lookahead bias fixed (shift signal by 1 day)",
                "K686: Rolling percentile strictly excludes current VIX value",
                "K686: DM test uses NW HAC SE instead of paired t-test",
                "K618/K619: KAN neural network results invalidated",
                "K621/K623: MF2-GARCH estimation bugs identified",
                "All strategies: 5bp one-way TX cost applied",
            ],
        },
        "references": [
            "K686: VIX Percentile Corrected (lookahead artifact confirmed)",
            "K679-K685: VIX Percentile series (all had lookahead bugs)",
            "K618/K619: KAN bugs (Codex review)",
            "K621/K623: MF2-GARCH bugs",
            "Copeland & Copeland (1999), Market Timing with VIX",
            "Harvey et al. (2016), ...and the Cross-Section of Expected Returns",
            "Diebold & Mariano (1995), Comparing Predictive Accuracy",
            "RiskMetrics (1996), Technical Document",
        ],
    }

    # Save results
    out_path = Path(__file__).parent / "k687_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n  Results saved to {out_path}")

    # Final verdict
    print("\n" + "=" * 70)
    print("FINAL VERDICT")
    print("=" * 70)
    best = ranking[0]
    print(f"  After fixing ALL bugs (lookahead, KAN, MF2-GARCH),")
    print(f"  the DEFINITIVE best strategy is:")
    print(f"    {best['strategy']}")
    print(f"    Sharpe = {best['sharpe']:.3f}")
    print(f"    CAGR   = {best['cagr_pct']:.2f}%")
    print(f"    MDD    = {best['mdd_pct']:.2f}%")
    print(f"    Calmar = {best['calmar']:.3f}")
    dm_best = dm_results.get(best["strategy"], {})
    if dm_best:
        print(f"    DM vs BH 50/50: t={dm_best.get('t_stat', 'N/A')}, "
              f"Harvey pass={dm_best.get('harvey_pass', 'N/A')}")
    print()

    return output


if __name__ == "__main__":
    results = main()
