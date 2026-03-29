"""K683: VIX Percentile vs Piecewise Conservative — Definitive Head-to-Head

Motivation:
  K679/K680 found VIX percentile (Sharpe 1.68, cross-OOS validated, DM t=3.157)
  crushes 12/VIX baseline (1.08). K654 showed Piecewise was dominant in live data
  (K640: Sharpe 3.98 in crisis-heavy 2025) but is actually a risk-tolerance choice
  (19% win rate over 21 years, CAGR 3.1% vs 50/50 11.4%).

  This experiment is the definitive comparison: which should be our NEW default
  recommendation?

Strategies (all on 50/50 SPY/GLD):
  a. VIX Percentile:       w = 1 - percentile_rank(VIX, 252d)
  b. Piecewise Conservative: VIX<12→100%, 12-20→linear, >20→0%
  c. 12/VIX continuous:    w = min(12/VIX, 1.0) — baseline
  d. P3-AGG lookup table:  VIX<15→80%, 15-25→45%, >25→10%
  e. Buy-and-hold 50/50:   w = 1.0 always

References:
  - K679: VIX Percentile Strategy (Sharpe 1.68, t=3.375 Harvey PASS)
  - K680: Percentile Cross-OOS VALIDATED (5/5 wins, DM t=3.157)
  - K654: Piecewise Decomposition (NOT alpha, risk tolerance choice)
  - K569: Piecewise VT Validation (6/8 checks pass)
  - K640: Live Performance Audit (Piecewise Sharpe 3.98 in crisis period)
  - K682: Percentile Lookup Table (P3-AGG 3-row)
  - Copeland & Copeland (1999), Market Timing with VIX

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
EVAL_START = "2007-01-03"  # Need 252d warmup for percentile
ROLLING_WINDOW = 252       # 1 year for percentile calculation
TC_BPS = 5                 # Transaction cost in basis points (one-way)
RF_DAILY = 0.04 / 252      # ~4% annual risk-free for cash portion
N_BOOTSTRAP = 5000         # Bootstrap replications for Sharpe comparison


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
    """Compute rolling VIX percentile rank (vectorized for speed)."""
    result = pd.Series(index=vix_series.index, dtype=float)
    vals = vix_series.values
    for i in range(window, len(vals)):
        window_vals = vals[i - window:i]
        result.iloc[i] = sp_stats.percentileofscore(window_vals, vals[i]) / 100.0
    return result


def compute_all_weights(data):
    """Compute weights for all 5 strategies."""
    vix = data["vix"].values
    n = len(data)

    # --- Strategy 1: VIX Percentile ---
    # w = 1 - percentile_rank(VIX, 252d)
    pct = compute_rolling_percentile(data["vix"]).values
    w_percentile = 1.0 - pct

    # --- Strategy 2: Piecewise Conservative ---
    # VIX<12 → 100%, 12-20 → linear ramp-down, >20 → 0%
    w_piecewise = np.full(n, np.nan)
    for i in range(n):
        v = vix[i]
        if v < 12:
            w_piecewise[i] = 1.0
        elif v <= 20:
            w_piecewise[i] = (20 - v) / 8.0
        else:
            w_piecewise[i] = 0.0

    # --- Strategy 3: 12/VIX continuous (baseline) ---
    w_12vix = np.minimum(12.0 / vix, 1.0)

    # --- Strategy 4: P3-AGG lookup table ---
    # VIX<15 → 80%, 15-25 → 45%, >25 → 10%
    w_p3agg = np.full(n, np.nan)
    for i in range(n):
        v = vix[i]
        if v < 15:
            w_p3agg[i] = 0.80
        elif v <= 25:
            w_p3agg[i] = 0.45
        else:
            w_p3agg[i] = 0.10

    # --- Strategy 5: Buy-and-hold 50/50 ---
    w_bh = np.ones(n)

    data = data.copy()
    data["w_percentile"] = w_percentile
    data["w_piecewise"] = w_piecewise
    data["w_12vix"] = w_12vix
    data["w_p3agg"] = w_p3agg
    data["w_bh"] = w_bh

    return data


def backtest_strategy(data, weight_col, name, tc_bps=TC_BPS):
    """Backtest a 50/50 SPY/GLD strategy with given weight column."""
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()

    if len(df) == 0:
        return None

    weights = df[weight_col].values
    spy_ret = df["spy_ret"].values
    gld_ret = df["gld_ret"].values

    # 50/50 SPY/GLD portfolio return (when invested)
    portfolio_ret = 0.5 * spy_ret + 0.5 * gld_ret

    # Strategy return = w * portfolio_ret + (1 - w) * rf - tc
    strategy_ret = np.zeros(len(df))
    tc_rate = tc_bps / 10000.0

    prev_w = 0.0
    total_tc = 0.0
    for i in range(len(df)):
        w = weights[i]
        if np.isnan(w):
            w = prev_w  # carry forward if NaN
        tc = abs(w - prev_w) * tc_rate
        total_tc += tc
        strategy_ret[i] = w * portfolio_ret[i] + (1 - w) * RF_DAILY - tc
        prev_w = w

    # Also compute gross (no TC) returns for comparison
    strategy_ret_gross = np.zeros(len(df))
    prev_w_g = 0.0
    for i in range(len(df)):
        w = weights[i]
        if np.isnan(w):
            w = prev_w_g
        strategy_ret_gross[i] = w * portfolio_ret[i] + (1 - w) * RF_DAILY
        prev_w_g = w

    # Compute metrics
    cum_ret = np.cumprod(1 + strategy_ret)
    total_ret = cum_ret[-1] - 1
    n_years = len(df) / 252.0
    cagr = (1 + total_ret) ** (1 / n_years) - 1

    ann_ret = np.mean(strategy_ret) * 252
    ann_vol = np.std(strategy_ret, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0  # excess over 4% rf

    # Gross Sharpe
    ann_ret_g = np.mean(strategy_ret_gross) * 252
    ann_vol_g = np.std(strategy_ret_gross, ddof=1) * np.sqrt(252)
    sharpe_gross = (ann_ret_g - 0.04) / ann_vol_g if ann_vol_g > 0 else 0

    # Max drawdown
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = (cum_ret - running_max) / running_max
    mdd = np.min(drawdowns)

    # Calmar ratio
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino ratio (downside deviation)
    downside = strategy_ret[strategy_ret < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = (ann_ret - 0.04) / downside_vol if downside_vol > 0 else 0

    # Monthly loss rate (K648 metric)
    monthly_ret = pd.Series(strategy_ret, index=df.index).resample("ME").sum()
    monthly_loss_rate = (monthly_ret < 0).sum() / len(monthly_ret) * 100

    # Ulcer index (root mean square of drawdowns)
    ulcer_index = np.sqrt(np.mean(drawdowns ** 2)) * 100

    # Average weight (exposure)
    valid_w = weights[~np.isnan(weights)]
    avg_weight = np.mean(valid_w) if len(valid_w) > 0 else 0

    # Turnover
    weight_changes = np.abs(np.diff(valid_w))
    avg_daily_turnover = np.mean(weight_changes) if len(weight_changes) > 0 else 0
    annual_turnover = avg_daily_turnover * 252
    total_tc_pct = total_tc * 100

    return {
        "strategy": name,
        "cagr": round(cagr * 100, 2),
        "sharpe_net": round(sharpe, 3),
        "sharpe_gross": round(sharpe_gross, 3),
        "sortino": round(sortino, 3),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "ann_vol": round(ann_vol * 100, 2),
        "avg_weight": round(avg_weight, 3),
        "annual_turnover": round(annual_turnover, 2),
        "monthly_loss_rate": round(monthly_loss_rate, 1),
        "ulcer_index": round(ulcer_index, 3),
        "total_tc_pct": round(total_tc_pct, 2),
        "total_return_pct": round(total_ret * 100, 2),
        "n_days": len(df),
        "n_years": round(n_years, 1),
        "daily_returns": strategy_ret,  # for bootstrap (not saved to JSON)
        "dates": df.index,              # for regime analysis (not saved to JSON)
    }


def bootstrap_sharpe_comparison(ret_a, ret_b, n_boot=N_BOOTSTRAP, seed=42):
    """Bootstrap comparison of Sharpe ratios between two strategies.

    Returns:
        dict with mean diff, CI, p-value for H0: Sharpe_A = Sharpe_B
    """
    rng = np.random.RandomState(seed)
    n = len(ret_a)

    def sharpe_fn(r):
        ann_ret = np.mean(r) * 252
        ann_vol = np.std(r, ddof=1) * np.sqrt(252)
        return (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

    observed_diff = sharpe_fn(ret_a) - sharpe_fn(ret_b)

    boot_diffs = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        boot_diffs[b] = sharpe_fn(ret_a[idx]) - sharpe_fn(ret_b[idx])

    ci_lower = np.percentile(boot_diffs, 2.5)
    ci_upper = np.percentile(boot_diffs, 97.5)
    p_value = np.mean(boot_diffs <= 0)  # P(diff <= 0)

    return {
        "observed_diff": round(float(observed_diff), 4),
        "bootstrap_mean_diff": round(float(np.mean(boot_diffs)), 4),
        "ci_95_lower": round(float(ci_lower), 4),
        "ci_95_upper": round(float(ci_upper), 4),
        "p_value": round(float(p_value), 4),
        "n_bootstrap": n_boot,
        "significant_5pct": bool(p_value < 0.05 or p_value > 0.95),
    }


def diebold_mariano_test(ret_a, ret_b):
    """Diebold-Mariano style t-test on daily return differences."""
    diff = ret_a - ret_b
    n = len(diff)
    t_stat = float(diff.mean() / (diff.std(ddof=1) / np.sqrt(n)))
    p_val = float(2 * sp_stats.t.sf(abs(t_stat), df=n - 1))

    return {
        "mean_diff_bps": round(float(diff.mean() * 10000), 3),
        "std_diff_bps": round(float(diff.std() * 10000), 3),
        "t_stat": round(t_stat, 3),
        "p_value": round(p_val, 4),
        "harvey_pass": bool(abs(t_stat) > 3.0),
        "n_obs": n,
    }


def regime_analysis(data, results_dict):
    """Analyze performance by VIX regime (calm/elevated/crisis)."""
    eval_data = data[data.index >= EVAL_START].copy()
    vix = eval_data["vix"]

    regimes = {
        "Calm (VIX<15)": vix < 15,
        "Elevated (15<=VIX<25)": (vix >= 15) & (vix < 25),
        "Crisis (VIX>=25)": vix >= 25,
    }

    strategies = [
        ("w_percentile", "VIX Percentile"),
        ("w_piecewise", "Piecewise Conservative"),
        ("w_12vix", "12/VIX"),
        ("w_p3agg", "P3-AGG"),
        ("w_bh", "Buy-and-Hold 50/50"),
    ]

    portfolio_ret = 0.5 * eval_data["spy_ret"] + 0.5 * eval_data["gld_ret"]

    regime_results = {}

    for regime_name, mask in regimes.items():
        regime_data = eval_data[mask]
        n_days = len(regime_data)
        if n_days < 10:
            continue

        regime_info = {
            "n_days": n_days,
            "pct_of_total": round(n_days / len(eval_data) * 100, 1),
            "avg_vix": round(float(regime_data["vix"].mean()), 2),
            "strategies": {},
        }

        regime_portfolio = portfolio_ret.loc[regime_data.index]

        for wcol, sname in strategies:
            w = regime_data[wcol].ffill().fillna(0)
            sr = w * regime_portfolio + (1 - w) * RF_DAILY
            sr = sr.dropna()

            if len(sr) < 5:
                continue

            ann_ret = float(sr.mean() * 252)
            ann_vol = float(sr.std(ddof=1) * np.sqrt(252)) if len(sr) > 1 else 0
            sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

            cum = (1 + sr).cumprod()
            running_max = np.maximum.accumulate(cum.values)
            dd = (cum.values - running_max) / running_max
            mdd = float(np.min(dd))

            regime_info["strategies"][sname] = {
                "avg_weight": round(float(w.mean()), 3),
                "ann_return_pct": round(ann_ret * 100, 2),
                "ann_vol_pct": round(ann_vol * 100, 2),
                "sharpe": round(sharpe, 3),
                "mdd_pct": round(mdd * 100, 2),
                "n_days": len(sr),
            }

        regime_results[regime_name] = regime_info

    return regime_results


def sub_period_analysis(data):
    """Split into meaningful sub-periods for robustness."""
    sub_periods = {
        "GFC (2007-2009)": ("2007-01-03", "2009-12-31"),
        "Recovery (2010-2012)": ("2010-01-01", "2012-12-31"),
        "Bull Run (2013-2019)": ("2013-01-01", "2019-12-31"),
        "COVID+ (2020-2022)": ("2020-01-01", "2022-12-31"),
        "Recent (2023-2026)": ("2023-01-01", "2026-03-27"),
        "Full Pre-COVID (2007-2019)": ("2007-01-03", "2019-12-31"),
        "Full Post-COVID (2020-2026)": ("2020-01-01", "2026-03-27"),
    }

    strategies = [
        ("w_percentile", "VIX Percentile"),
        ("w_piecewise", "Piecewise Conservative"),
        ("w_12vix", "12/VIX"),
        ("w_p3agg", "P3-AGG"),
        ("w_bh", "Buy-and-Hold 50/50"),
    ]

    results = {}
    for period_name, (start, end) in sub_periods.items():
        mask = (data.index >= start) & (data.index <= end)
        period_data = data[mask]

        if len(period_data) < 30:
            continue

        portfolio_ret = 0.5 * period_data["spy_ret"] + 0.5 * period_data["gld_ret"]
        n_years = len(period_data) / 252.0

        period_info = {
            "n_days": len(period_data),
            "n_years": round(n_years, 1),
            "avg_vix": round(float(period_data["vix"].mean()), 2),
            "strategies": {},
        }

        for wcol, sname in strategies:
            w = period_data[wcol].ffill().fillna(0)
            sr = w * portfolio_ret + (1 - w) * RF_DAILY
            sr = sr.dropna()

            if len(sr) < 10:
                continue

            cum = (1 + sr).cumprod()
            total = float(cum.iloc[-1] - 1)
            cagr = ((1 + total) ** (1 / max(n_years, 0.1)) - 1)
            ann_ret = float(sr.mean() * 252)
            ann_vol = float(sr.std(ddof=1) * np.sqrt(252)) if len(sr) > 1 else 0
            sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

            running_max = np.maximum.accumulate(cum.values)
            dd = (cum.values - running_max) / running_max
            mdd = float(np.min(dd))

            monthly_sr = pd.Series(sr.values, index=period_data.index[:len(sr)]).resample("ME").sum()
            monthly_loss_rate = (monthly_sr < 0).sum() / len(monthly_sr) * 100 if len(monthly_sr) > 0 else 0

            period_info["strategies"][sname] = {
                "sharpe": round(sharpe, 3),
                "cagr_pct": round(cagr * 100, 2),
                "mdd_pct": round(mdd * 100, 2),
                "avg_weight": round(float(w.mean()), 3),
                "monthly_loss_rate": round(monthly_loss_rate, 1),
            }

        # Who wins in this period?
        strats = period_info["strategies"]
        if strats:
            best_sharpe = max(strats.items(), key=lambda x: x[1]["sharpe"])
            best_mdd = max(strats.items(), key=lambda x: x[1]["mdd_pct"])  # least negative
            period_info["winner_sharpe"] = best_sharpe[0]
            period_info["winner_mdd"] = best_mdd[0]

        results[period_name] = period_info

    return results


def head_to_head_summary(all_results):
    """Create a clear head-to-head scoring table."""
    metrics = ["sharpe_net", "sortino", "mdd", "calmar", "cagr", "monthly_loss_rate", "ulcer_index"]
    metric_names = ["Sharpe (Net)", "Sortino", "MDD", "Calmar", "CAGR", "Monthly Loss Rate", "Ulcer Index"]
    # For each metric, higher is better except mdd (less negative is better) and
    # monthly_loss_rate / ulcer_index (lower is better)
    higher_is_better = [True, True, True, True, True, False, False]
    # Note: MDD is negative, so "higher" (less negative) is better

    scoring = {}
    for r in all_results:
        scoring[r["strategy"]] = {m: r[m] for m in metrics}

    # Rank strategies per metric
    rankings = {}
    for m, name, hib in zip(metrics, metric_names, higher_is_better):
        vals = [(s, scoring[s][m]) for s in scoring]
        if hib:
            vals.sort(key=lambda x: x[1], reverse=True)
        else:
            vals.sort(key=lambda x: x[1])
        rankings[name] = [(v[0], v[1], rank + 1) for rank, v in enumerate(vals)]

    # Total score (sum of ranks, lower = better)
    total_ranks = {s: 0 for s in scoring}
    for name, ranked in rankings.items():
        for strat, val, rank in ranked:
            total_ranks[strat] += rank

    return {"rankings": rankings, "total_ranks": total_ranks}


def main():
    print("=" * 70)
    print("K683: VIX Percentile vs Piecewise Conservative — Definitive Head-to-Head")
    print("=" * 70)

    # ========================================================================
    # Step 1: Download and prepare data
    # ========================================================================
    data = download_data()

    # Descriptive statistics
    vix = data["vix"]
    print(f"\n--- VIX Descriptive Stats ---")
    print(f"  Mean: {vix.mean():.2f}, Median: {vix.median():.2f}")
    print(f"  Std:  {vix.std():.2f}, Skew: {vix.skew():.2f}, Kurt: {vix.kurtosis():.2f}")
    print(f"  Range: [{vix.min():.2f}, {vix.max():.2f}]")

    vix_stats = {
        "mean": round(float(vix.mean()), 2),
        "median": round(float(vix.median()), 2),
        "std": round(float(vix.std()), 2),
        "skew": round(float(vix.skew()), 2),
        "kurtosis": round(float(vix.kurtosis()), 2),
        "min": round(float(vix.min()), 2),
        "max": round(float(vix.max()), 2),
        "pct_below_15": round(float((vix < 15).sum() / len(vix) * 100), 1),
        "pct_15_to_25": round(float(((vix >= 15) & (vix < 25)).sum() / len(vix) * 100), 1),
        "pct_above_25": round(float((vix >= 25).sum() / len(vix) * 100), 1),
    }

    # ========================================================================
    # Step 2: Compute all strategy weights
    # ========================================================================
    print("\n--- Computing strategy weights ---")
    data = compute_all_weights(data)

    # Weight summary in eval period
    eval_data = data[data.index >= EVAL_START]
    for col, name in [("w_percentile", "VIX Percentile"), ("w_piecewise", "Piecewise"),
                       ("w_12vix", "12/VIX"), ("w_p3agg", "P3-AGG"), ("w_bh", "B&H")]:
        w = eval_data[col].dropna()
        print(f"  {name}: avg={w.mean():.3f}, std={w.std():.3f}, "
              f"min={w.min():.3f}, max={w.max():.3f}")

    # ========================================================================
    # Step 3: Full backtest (2007-2026)
    # ========================================================================
    print("\n" + "=" * 70)
    print("FULL BACKTEST RESULTS (2007-01 to 2026-03)")
    print("=" * 70)

    strategies = [
        ("w_percentile", "VIX Percentile"),
        ("w_piecewise", "Piecewise Conservative"),
        ("w_12vix", "12/VIX (Baseline)"),
        ("w_p3agg", "P3-AGG Lookup"),
        ("w_bh", "Buy-and-Hold 50/50"),
    ]

    all_results = []
    for wcol, sname in strategies:
        result = backtest_strategy(data, wcol, sname)
        if result:
            print(f"\n  {sname}:")
            print(f"    CAGR:              {result['cagr']:.2f}%")
            print(f"    Sharpe (net 5bp):   {result['sharpe_net']:.3f}")
            print(f"    Sharpe (gross):     {result['sharpe_gross']:.3f}")
            print(f"    Sortino:           {result['sortino']:.3f}")
            print(f"    MDD:               {result['mdd']:.2f}%")
            print(f"    Calmar:            {result['calmar']:.3f}")
            print(f"    Ann Vol:           {result['ann_vol']:.2f}%")
            print(f"    Monthly Loss Rate: {result['monthly_loss_rate']:.1f}%")
            print(f"    Ulcer Index:       {result['ulcer_index']:.3f}")
            print(f"    Avg Weight:        {result['avg_weight']:.3f}")
            print(f"    Annual Turnover:   {result['annual_turnover']:.2f}")
            print(f"    Total TX Cost:     {result['total_tc_pct']:.2f}%")
            all_results.append(result)

    # ========================================================================
    # Step 4: Pairwise statistical comparisons
    # ========================================================================
    print("\n" + "=" * 70)
    print("STATISTICAL COMPARISONS (Diebold-Mariano)")
    print("=" * 70)

    comparisons = {}
    strategy_returns = {r["strategy"]: r["daily_returns"] for r in all_results}

    # Compare every pair vs baseline (12/VIX)
    baseline_name = "12/VIX (Baseline)"
    baseline_ret = strategy_returns[baseline_name]
    for name, ret in strategy_returns.items():
        if name == baseline_name:
            continue
        dm = diebold_mariano_test(ret, baseline_ret)
        sig = "***" if dm["harvey_pass"] else ("**" if dm["p_value"] < 0.05 else "ns")
        print(f"\n  {name} vs {baseline_name}: {sig}")
        print(f"    Mean diff: {dm['mean_diff_bps']:.3f} bps/day")
        print(f"    t-stat:    {dm['t_stat']:.3f} (Harvey threshold: 3.0)")
        print(f"    p-value:   {dm['p_value']:.4f}")
        comparisons[f"{name} vs {baseline_name}"] = dm

    # THE KEY COMPARISON: Percentile vs Piecewise
    print("\n" + "-" * 50)
    print("  *** THE KEY COMPARISON: Percentile vs Piecewise ***")
    dm_key = diebold_mariano_test(
        strategy_returns["VIX Percentile"],
        strategy_returns["Piecewise Conservative"],
    )
    sig = "***" if dm_key["harvey_pass"] else ("**" if dm_key["p_value"] < 0.05 else "ns")
    print(f"    Mean diff: {dm_key['mean_diff_bps']:.3f} bps/day")
    print(f"    t-stat:    {dm_key['t_stat']:.3f} {sig}")
    print(f"    p-value:   {dm_key['p_value']:.4f}")
    comparisons["VIX Percentile vs Piecewise Conservative"] = dm_key

    # ========================================================================
    # Step 5: Bootstrap Sharpe comparison
    # ========================================================================
    print("\n" + "=" * 70)
    print("BOOTSTRAP SHARPE COMPARISON (5000 replications)")
    print("=" * 70)

    bootstrap_results = {}

    # Percentile vs 12/VIX
    print("\n  VIX Percentile vs 12/VIX (Baseline):")
    bs1 = bootstrap_sharpe_comparison(
        strategy_returns["VIX Percentile"],
        strategy_returns["12/VIX (Baseline)"],
    )
    print(f"    Observed Sharpe diff: {bs1['observed_diff']:.4f}")
    print(f"    Bootstrap 95% CI:    [{bs1['ci_95_lower']:.4f}, {bs1['ci_95_upper']:.4f}]")
    print(f"    P(diff<=0):          {bs1['p_value']:.4f}")
    bootstrap_results["Percentile vs 12/VIX"] = bs1

    # Percentile vs Piecewise
    print("\n  VIX Percentile vs Piecewise Conservative:")
    bs2 = bootstrap_sharpe_comparison(
        strategy_returns["VIX Percentile"],
        strategy_returns["Piecewise Conservative"],
    )
    print(f"    Observed Sharpe diff: {bs2['observed_diff']:.4f}")
    print(f"    Bootstrap 95% CI:    [{bs2['ci_95_lower']:.4f}, {bs2['ci_95_upper']:.4f}]")
    print(f"    P(diff<=0):          {bs2['p_value']:.4f}")
    bootstrap_results["Percentile vs Piecewise"] = bs2

    # Percentile vs P3-AGG
    print("\n  VIX Percentile vs P3-AGG Lookup:")
    bs3 = bootstrap_sharpe_comparison(
        strategy_returns["VIX Percentile"],
        strategy_returns["P3-AGG Lookup"],
    )
    print(f"    Observed Sharpe diff: {bs3['observed_diff']:.4f}")
    print(f"    Bootstrap 95% CI:    [{bs3['ci_95_lower']:.4f}, {bs3['ci_95_upper']:.4f}]")
    print(f"    P(diff<=0):          {bs3['p_value']:.4f}")
    bootstrap_results["Percentile vs P3-AGG"] = bs3

    # Piecewise vs 12/VIX
    print("\n  Piecewise Conservative vs 12/VIX (Baseline):")
    bs4 = bootstrap_sharpe_comparison(
        strategy_returns["Piecewise Conservative"],
        strategy_returns["12/VIX (Baseline)"],
    )
    print(f"    Observed Sharpe diff: {bs4['observed_diff']:.4f}")
    print(f"    Bootstrap 95% CI:    [{bs4['ci_95_lower']:.4f}, {bs4['ci_95_upper']:.4f}]")
    print(f"    P(diff<=0):          {bs4['p_value']:.4f}")
    bootstrap_results["Piecewise vs 12/VIX"] = bs4

    # ========================================================================
    # Step 6: Regime breakdown
    # ========================================================================
    print("\n" + "=" * 70)
    print("REGIME BREAKDOWN (Calm / Elevated / Crisis)")
    print("=" * 70)

    regime_results = regime_analysis(data, all_results)
    for regime_name, info in regime_results.items():
        print(f"\n  {regime_name} ({info['n_days']} days, {info['pct_of_total']}%, avg VIX={info['avg_vix']})")
        for sname, sinfo in info["strategies"].items():
            print(f"    {sname:25s}: Sharpe={sinfo['sharpe']:+.3f}, "
                  f"MDD={sinfo['mdd_pct']:.1f}%, w={sinfo['avg_weight']:.3f}")

    # ========================================================================
    # Step 7: Sub-period robustness
    # ========================================================================
    print("\n" + "=" * 70)
    print("SUB-PERIOD ROBUSTNESS")
    print("=" * 70)

    sub_periods = sub_period_analysis(data)
    win_count = {s[1]: 0 for s in strategies}
    for period_name, info in sub_periods.items():
        print(f"\n  {period_name} ({info['n_days']} days, avg VIX={info['avg_vix']})")
        for sname, sinfo in info["strategies"].items():
            print(f"    {sname:25s}: Sharpe={sinfo['sharpe']:+.3f}, "
                  f"CAGR={sinfo['cagr_pct']:+.1f}%, MDD={sinfo['mdd_pct']:.1f}%")
        if "winner_sharpe" in info:
            print(f"    >>> Sharpe winner: {info['winner_sharpe']}")
            win_count[info["winner_sharpe"]] = win_count.get(info["winner_sharpe"], 0) + 1

    print("\n  Sub-period Sharpe wins:")
    for s, c in sorted(win_count.items(), key=lambda x: -x[1]):
        print(f"    {s}: {c}/{len(sub_periods)} periods")

    # ========================================================================
    # Step 8: Head-to-head scoring
    # ========================================================================
    print("\n" + "=" * 70)
    print("HEAD-TO-HEAD SCORING (7 metrics, rank 1-5)")
    print("=" * 70)

    h2h = head_to_head_summary(all_results)
    for metric, ranked in h2h["rankings"].items():
        print(f"\n  {metric}:")
        for strat, val, rank in ranked:
            print(f"    #{rank} {strat:25s}: {val}")

    print("\n  TOTAL RANK (lower = better):")
    for strat, total in sorted(h2h["total_ranks"].items(), key=lambda x: x[1]):
        print(f"    {strat:25s}: {total}/35")

    # ========================================================================
    # Step 9: The Verdict
    # ========================================================================
    print("\n" + "=" * 70)
    print("THE VERDICT")
    print("=" * 70)

    # Determine winner
    best_total = min(h2h["total_ranks"].items(), key=lambda x: x[1])
    percentile_result = next(r for r in all_results if r["strategy"] == "VIX Percentile")
    piecewise_result = next(r for r in all_results if r["strategy"] == "Piecewise Conservative")
    baseline_result = next(r for r in all_results if r["strategy"] == "12/VIX (Baseline)")

    verdict_lines = []
    verdict_lines.append(f"Overall winner by composite rank: {best_total[0]} (total rank: {best_total[1]}/35)")
    verdict_lines.append("")
    verdict_lines.append("Percentile vs Piecewise:")
    verdict_lines.append(f"  Sharpe: {percentile_result['sharpe_net']:.3f} vs {piecewise_result['sharpe_net']:.3f}")
    verdict_lines.append(f"  CAGR:   {percentile_result['cagr']:.2f}% vs {piecewise_result['cagr']:.2f}%")
    verdict_lines.append(f"  MDD:    {percentile_result['mdd']:.2f}% vs {piecewise_result['mdd']:.2f}%")
    verdict_lines.append(f"  Sortino:{percentile_result['sortino']:.3f} vs {piecewise_result['sortino']:.3f}")
    verdict_lines.append(f"  DM t:   {dm_key['t_stat']:.3f} (p={dm_key['p_value']:.4f})")
    verdict_lines.append(f"  Boot CI:[{bs2['ci_95_lower']:.4f}, {bs2['ci_95_upper']:.4f}]")
    verdict_lines.append("")

    # Who to recommend for which profile
    verdict_lines.append("RECOMMENDATION BY INVESTOR PROFILE:")
    verdict_lines.append(f"  Return-maximizers:  VIX Percentile (CAGR {percentile_result['cagr']:.1f}%)")
    if piecewise_result['mdd'] > percentile_result['mdd']:
        verdict_lines.append(f"  Risk-averse:        Piecewise Conservative (MDD {piecewise_result['mdd']:.1f}%)")
    else:
        verdict_lines.append(f"  Risk-averse:        VIX Percentile (also lower MDD)")
    verdict_lines.append(f"  Simplicity seekers: P3-AGG Lookup (3 rules, no rolling calculation)")
    verdict_lines.append(f"  Passive investors:  Buy-and-Hold 50/50 (zero effort)")

    for line in verdict_lines:
        print(f"  {line}")

    # ========================================================================
    # Save results
    # ========================================================================

    # Clean results for JSON serialization (remove numpy arrays and datetime indices)
    backtest_summary = []
    for r in all_results:
        summary = {k: v for k, v in r.items() if k not in ("daily_returns", "dates")}
        backtest_summary.append(summary)

    # Determine overall winner
    overall_winner = best_total[0]
    percentile_is_better = percentile_result["sharpe_net"] > piecewise_result["sharpe_net"]

    results = {
        "experiment_id": "K683",
        "title": "VIX Percentile vs Piecewise Conservative — Definitive Head-to-Head",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "data_period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{EVAL_START} to {END_DATE}",
        "n_eval_days": len(data[data.index >= EVAL_START]),
        "methodology": {
            "portfolio": "50/50 SPY/GLD, cash remainder at 4% annual RF",
            "transaction_cost": f"{TC_BPS} bps one-way",
            "rolling_window": ROLLING_WINDOW,
            "bootstrap_replications": N_BOOTSTRAP,
            "strategies": {
                "VIX Percentile": "w = 1 - percentile_rank(VIX, rolling 252d)",
                "Piecewise Conservative": "VIX<12 -> 100%, 12-20 -> linear (20-VIX)/8, >20 -> 0%",
                "12/VIX (Baseline)": "w = min(12/VIX, 1.0)",
                "P3-AGG Lookup": "VIX<15 -> 80%, 15-25 -> 45%, >25 -> 10%",
                "Buy-and-Hold 50/50": "w = 1.0 always",
            },
        },
        "references": [
            "K679: VIX Percentile Strategy (Sharpe 1.68, t=3.375)",
            "K680: Percentile Cross-OOS VALIDATED (5/5 wins, DM t=3.157)",
            "K654: Piecewise Decomposition (NOT alpha, risk tolerance choice)",
            "K569: Piecewise VT Validation (6/8 checks pass)",
            "K640: Live Performance Audit (Piecewise Sharpe 3.98 crisis period)",
            "K682: Percentile Lookup Table (P3-AGG 3-row)",
            "Copeland & Copeland (1999), Market Timing with VIX",
        ],
        "vix_descriptive_stats": vix_stats,
        "backtest_results": backtest_summary,
        "statistical_comparisons": comparisons,
        "bootstrap_sharpe_comparison": bootstrap_results,
        "regime_breakdown": regime_results,
        "sub_period_robustness": sub_periods,
        "sub_period_win_counts": win_count,
        "head_to_head_scoring": {
            "rankings": {k: [(s, v, r) for s, v, r in vals] for k, vals in h2h["rankings"].items()},
            "total_ranks": h2h["total_ranks"],
        },
        "verdict": {
            "overall_winner": overall_winner,
            "percentile_beats_piecewise": percentile_is_better,
            "key_comparison_dm": dm_key,
            "key_comparison_bootstrap": bs2,
            "recommendations": {
                "return_maximizers": "VIX Percentile",
                "risk_averse": "Piecewise Conservative" if piecewise_result["mdd"] > percentile_result["mdd"]
                                else "VIX Percentile",
                "simplicity": "P3-AGG Lookup",
                "passive": "Buy-and-Hold 50/50",
            },
            "verdict_text": verdict_lines,
        },
        "key_findings": [],
    }

    # Generate key findings
    findings = []
    findings.append(
        f"Overall composite winner: {overall_winner} "
        f"(rank {best_total[1]}/35 across 7 metrics)"
    )
    findings.append(
        f"Percentile Sharpe {percentile_result['sharpe_net']:.3f} vs "
        f"Piecewise {piecewise_result['sharpe_net']:.3f} vs "
        f"12/VIX {baseline_result['sharpe_net']:.3f}"
    )
    findings.append(
        f"Percentile CAGR {percentile_result['cagr']:.1f}% vs "
        f"Piecewise {piecewise_result['cagr']:.1f}% vs "
        f"12/VIX {baseline_result['cagr']:.1f}%"
    )
    findings.append(
        f"Percentile MDD {percentile_result['mdd']:.1f}% vs "
        f"Piecewise {piecewise_result['mdd']:.1f}% vs "
        f"12/VIX {baseline_result['mdd']:.1f}%"
    )
    findings.append(
        f"DM test Percentile vs Piecewise: t={dm_key['t_stat']:.3f}, "
        f"p={dm_key['p_value']:.4f}, Harvey {'PASS' if dm_key['harvey_pass'] else 'FAIL'}"
    )
    findings.append(
        f"Bootstrap Percentile vs Piecewise: 95% CI "
        f"[{bs2['ci_95_lower']:.4f}, {bs2['ci_95_upper']:.4f}], p={bs2['p_value']:.4f}"
    )

    # Sub-period winner count
    pct_wins = win_count.get("VIX Percentile", 0)
    pw_wins = win_count.get("Piecewise Conservative", 0)
    findings.append(
        f"Sub-period Sharpe wins: Percentile {pct_wins}/{len(sub_periods)}, "
        f"Piecewise {pw_wins}/{len(sub_periods)}"
    )

    # Regime insight
    for regime_name, info in regime_results.items():
        strats = info["strategies"]
        if "VIX Percentile" in strats and "Piecewise Conservative" in strats:
            pct_s = strats["VIX Percentile"]["sharpe"]
            pw_s = strats["Piecewise Conservative"]["sharpe"]
            findings.append(
                f"Regime {regime_name}: Percentile Sharpe {pct_s:.3f} vs "
                f"Piecewise {pw_s:.3f}"
            )

    results["key_findings"] = findings

    # Print key findings
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)
    for i, f in enumerate(findings, 1):
        print(f"  {i}. {f}")

    # Save to JSON
    out_path = Path(__file__).parent / "k683_results.json"
    with open(out_path, "w") as f_out:
        json.dump(results, f_out, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
