"""K696: The Cost of Being Out — What If VT Just Reduced Weight Instead of Going to Cash?

Motivation:
K687 showed BH 50/50 beats all VT strategies on Sharpe (after lag correction).
K688 showed VT wins on CRRA utility for gamma>=5 (risk-averse investors benefit).
The root issue: VT strategies go to ZERO or very low exposure during high VIX,
missing the rebounds that follow crises. What if VT NEVER went below a minimum
floor (e.g. 30-50%), keeping some exposure even during crises?

Analysis:
  1. Download SPY, GLD, VIX daily data via yfinance (2006-01-01 to 2026-03-27)
  2. Implement 12/VIX on 50/50 SPY/GLD with PROPER 1-day LAG
  3. Test minimum exposure floors: {0%, 10%, 20%, 30%, 40%, 50%, 60%, 70%}
     weight = max(floor, min(12/VIX_{t-1}, 1.0))
  4. Evaluate NET of 5bp TX cost: Sharpe, MDD, CAGR
  5. Find optimal floor that maximizes Sharpe
  6. Quantify the trade-off: floor vs Sharpe vs MDD vs CAGR
  7. Compare all floors against BH 50/50 (floor=100%)

Key insight: The floor represents a trade-off:
  - Floor 0% = full VT (best MDD, worst CAGR)
  - Floor 100% = BH (worst MDD, best CAGR)
  - Somewhere in between might be optimal

Data source: yfinance (SPY, GLD, ^VIX), 2006-01-01 to 2026-03-27
Evaluation: 2007-01-03 to 2026-03-27 (1y warmup for VIX availability)

References:
  - K687: Definitive lag-corrected strategy ranking (BH 50/50 beats all VT on Sharpe)
  - K688: CRRA utility framework (VT wins for gamma>=5)
  - K690: Weight Smoothness and Lag Robustness
  - Copeland & Copeland (1999): Market Timing with VIX
  - Fleming, Kirby & Ostdiek (2001): The Economic Value of Volatility Timing
  - Kirby & Ostdiek (2012): It's All in the Timing
  - Harvey et al. (2016): ...and the Cross-Section of Expected Returns

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
EVAL_START = "2007-01-03"
TC_BPS = 5
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
FLOORS = [0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70]
RESULTS_FILE = Path(__file__).parent / "k696_results.json"


# ============================================================================
# Data Download
# ============================================================================
def download_data():
    """Download SPY, GLD, VIX data from yfinance."""
    print("=" * 70)
    print("K696: THE COST OF BEING OUT")
    print("What If VT Just Reduced Weight Instead of Going to Cash?")
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
    print(f"\n  Merged: {len(data)} rows, {data.index[0].date()} to {data.index[-1].date()}")
    print(f"  VIX: mean={data['vix'].mean():.2f}, std={data['vix'].std():.2f}, "
          f"min={data['vix'].min():.2f}, max={data['vix'].max():.2f}")

    return data


# ============================================================================
# Descriptive Statistics
# ============================================================================
def descriptive_stats(data):
    """Print descriptive statistics for the dataset."""
    print("\n" + "=" * 70)
    print("DESCRIPTIVE STATISTICS")
    print("=" * 70)

    port_ret = 0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]

    for name, series in [("SPY returns", data["spy_ret"]),
                          ("GLD returns", data["gld_ret"]),
                          ("50/50 Portfolio", port_ret),
                          ("VIX", data["vix"])]:
        print(f"\n  {name}:")
        print(f"    N={len(series)}, Mean={series.mean():.6f}, Std={series.std():.6f}")
        print(f"    Skew={series.skew():.4f}, Kurt={series.kurtosis():.4f}")
        print(f"    Min={series.min():.6f}, Max={series.max():.6f}")

    # VIX distribution relevant to floors
    vix = data["vix"]
    vix_12 = 12.0 / vix  # raw 12/VIX weight (uncapped)
    print(f"\n  12/VIX raw weight distribution:")
    print(f"    Mean={vix_12.mean():.4f}, Median={vix_12.median():.4f}")
    for pct in [5, 10, 25, 50, 75, 90, 95]:
        print(f"    P{pct:02d}={vix_12.quantile(pct/100):.4f}", end="  ")
    print()

    # What fraction of days would each floor be binding?
    capped_12vix = np.minimum(vix_12, 1.0)
    print(f"\n  Fraction of days each floor would be binding (12/VIX capped at 1.0):")
    for floor in FLOORS:
        binding = (capped_12vix < floor).mean()
        print(f"    Floor {floor*100:3.0f}%: {binding*100:.1f}% of days floor binds")

    return {
        "n_obs": len(data),
        "spy_mean": round(float(data["spy_ret"].mean()), 6),
        "gld_mean": round(float(data["gld_ret"].mean()), 6),
        "vix_mean": round(float(vix.mean()), 2),
        "vix_std": round(float(vix.std()), 2),
        "twelve_over_vix_mean": round(float(vix_12.mean()), 4),
        "twelve_over_vix_median": round(float(vix_12.median()), 4),
    }


# ============================================================================
# Performance Metrics
# ============================================================================
def annualised_sharpe(returns, rf_daily=RF_DAILY):
    """Annualised Sharpe ratio from daily returns."""
    excess = returns - rf_daily
    mu = np.mean(excess)
    sigma = np.std(excess, ddof=1)
    if sigma == 0 or np.isnan(sigma):
        return np.nan
    return float(mu / sigma * np.sqrt(252))


def compute_cagr(returns):
    """CAGR from daily returns."""
    n = len(returns)
    if n == 0:
        return np.nan
    cum = np.prod(1 + returns)
    if cum <= 0:
        return np.nan
    return float(cum ** (252 / n) - 1)


def compute_mdd(returns):
    """Maximum drawdown from daily returns."""
    cum = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    return float(dd.min())


def compute_sortino(returns, rf_daily=RF_DAILY):
    """Annualised Sortino ratio."""
    excess = returns - rf_daily
    downside = excess[excess < 0]
    if len(downside) < 2:
        return np.nan
    downside_std = np.std(downside, ddof=1)
    if downside_std == 0:
        return np.nan
    return float(np.mean(excess) / downside_std * np.sqrt(252))


def compute_calmar(cagr, mdd):
    """Calmar ratio = CAGR / |MDD|."""
    if mdd == 0 or np.isnan(mdd):
        return np.nan
    return float(cagr / abs(mdd))


def compute_annual_turnover(weights):
    """Annual turnover = sum of |Δw| / n_years."""
    dw = np.diff(weights)
    n_years = len(weights) / 252
    if n_years == 0:
        return np.nan
    return float(np.sum(np.abs(dw)) / n_years)


# ============================================================================
# Backtest Engine
# ============================================================================
def backtest_floor(data, floor, eval_start=EVAL_START, tc_bps=TC_BPS):
    """Backtest 12/VIX strategy with a minimum exposure floor.

    Signal: weight_t = max(floor, min(12 / VIX_{t-1}, 1.0))
    Return: weight_t * port_ret_t + (1 - weight_t) * rf_daily - tx_cost

    All signals use 1-day lag (VIX_{t-1} determines weight for day t).
    """
    vix = data["vix"]

    # Compute raw 12/VIX signal (before lag)
    raw_weight = np.minimum(12.0 / vix, 1.0)

    # Apply floor
    floored_weight = np.maximum(raw_weight, floor)

    # Apply 1-day lag: shift(1) means yesterday's signal for today
    lagged_weight = floored_weight.shift(1)

    # Restrict to evaluation period
    eval_mask = data.index >= eval_start
    df = data[eval_mask].copy()
    w = lagged_weight[eval_mask].values
    port_ret = (0.5 * df["spy_ret"] + 0.5 * df["gld_ret"]).values

    # Find valid range (drop NaN from lag)
    valid_mask = ~np.isnan(w)
    if valid_mask.sum() < 252:
        return None

    w_valid = w[valid_mask]
    ret_valid = port_ret[valid_mask]

    # Compute net returns with transaction costs
    tc_rate = tc_bps / 10000.0
    net_returns = np.zeros(len(w_valid))
    prev_w = w_valid[0]  # start at first weight (no TC for initial position)

    for i in range(len(w_valid)):
        w_i = w_valid[i]
        # Transaction cost for weight change
        tc = tc_rate * abs(w_i - prev_w)
        # Gross return: w * port_ret + (1-w) * rf_daily
        gross = w_i * ret_valid[i] + (1 - w_i) * RF_DAILY
        net_returns[i] = gross - tc
        prev_w = w_i

    # Compute performance metrics
    sharpe = annualised_sharpe(net_returns)
    cagr = compute_cagr(net_returns)
    mdd = compute_mdd(net_returns)
    sortino = compute_sortino(net_returns)
    calmar = compute_calmar(cagr, mdd)
    ann_vol = float(np.std(net_returns, ddof=1) * np.sqrt(252))
    turnover = compute_annual_turnover(w_valid)
    mean_weight = float(np.mean(w_valid))
    median_weight = float(np.median(w_valid))
    min_weight = float(np.min(w_valid))
    max_weight = float(np.max(w_valid))
    frac_at_floor = float(np.mean(w_valid <= floor + 1e-8)) if floor > 0 else 0.0

    # Cumulative return
    cum_return = float(np.prod(1 + net_returns) - 1)

    return {
        "floor_pct": round(floor * 100, 0),
        "sharpe": round(sharpe, 4),
        "cagr": round(cagr, 4),
        "mdd": round(mdd, 4),
        "sortino": round(sortino, 4) if not np.isnan(sortino) else None,
        "calmar": round(calmar, 4) if not np.isnan(calmar) else None,
        "ann_vol": round(ann_vol, 4),
        "cumulative_return": round(cum_return, 4),
        "annual_turnover": round(turnover, 4),
        "mean_weight": round(mean_weight, 4),
        "median_weight": round(median_weight, 4),
        "min_weight": round(min_weight, 4),
        "max_weight": round(max_weight, 4),
        "frac_at_floor": round(frac_at_floor, 4),
        "n_days": int(valid_mask.sum()),
    }


def backtest_bh(data, eval_start=EVAL_START):
    """Backtest buy-and-hold 50/50 SPY/GLD (floor=100%, no timing)."""
    eval_mask = data.index >= eval_start
    df = data[eval_mask].copy()
    port_ret = (0.5 * df["spy_ret"] + 0.5 * df["gld_ret"]).values

    sharpe = annualised_sharpe(port_ret)
    cagr = compute_cagr(port_ret)
    mdd = compute_mdd(port_ret)
    sortino = compute_sortino(port_ret)
    calmar = compute_calmar(cagr, mdd)
    ann_vol = float(np.std(port_ret, ddof=1) * np.sqrt(252))
    cum_return = float(np.prod(1 + port_ret) - 1)

    return {
        "floor_pct": 100.0,
        "sharpe": round(sharpe, 4),
        "cagr": round(cagr, 4),
        "mdd": round(mdd, 4),
        "sortino": round(sortino, 4) if not np.isnan(sortino) else None,
        "calmar": round(calmar, 4) if not np.isnan(calmar) else None,
        "ann_vol": round(ann_vol, 4),
        "cumulative_return": round(cum_return, 4),
        "annual_turnover": 0.0,
        "mean_weight": 1.0,
        "median_weight": 1.0,
        "min_weight": 1.0,
        "max_weight": 1.0,
        "frac_at_floor": 1.0,
        "n_days": int(eval_mask.sum()),
    }


# ============================================================================
# Main Analysis
# ============================================================================
def run_floor_sweep(data):
    """Test all floor values and compare against BH."""
    print("\n" + "=" * 70)
    print("FLOOR SWEEP: 12/VIX with Minimum Exposure Floors")
    print("Signal: weight_t = max(floor, min(12/VIX_{t-1}, 1.0))")
    print(f"TX cost: {TC_BPS} bps, Rf: {RF_ANNUAL*100:.1f}%")
    print("=" * 70)

    results = {}

    # Test each floor
    for floor in FLOORS:
        r = backtest_floor(data, floor)
        if r is None:
            print(f"\n  Floor {floor*100:3.0f}%: INSUFFICIENT DATA")
            continue
        results[f"floor_{int(floor*100)}"] = r
        print(f"\n  Floor {floor*100:3.0f}%: Sharpe={r['sharpe']:.4f}, "
              f"CAGR={r['cagr']*100:.2f}%, MDD={r['mdd']*100:.2f}%, "
              f"Turnover={r['annual_turnover']:.2f}, "
              f"MeanW={r['mean_weight']:.3f}, FloorBind={r['frac_at_floor']*100:.1f}%")

    # BH benchmark
    bh = backtest_bh(data)
    results["bh_5050"] = bh
    print(f"\n  BH 50/50: Sharpe={bh['sharpe']:.4f}, "
          f"CAGR={bh['cagr']*100:.2f}%, MDD={bh['mdd']*100:.2f}%")

    return results


def analyze_optimal_floor(sweep_results):
    """Analyze which floor maximizes Sharpe and other insights."""
    print("\n" + "=" * 70)
    print("ANALYSIS: OPTIMAL FLOOR")
    print("=" * 70)

    bh = sweep_results.get("bh_5050", {})
    bh_sharpe = bh.get("sharpe", np.nan)

    # Collect floor results (exclude BH)
    floor_data = []
    for key, val in sweep_results.items():
        if key.startswith("floor_"):
            floor_data.append(val)

    if not floor_data:
        print("  No floor results available")
        return {}

    # Sort by floor
    floor_data.sort(key=lambda x: x["floor_pct"])

    # Print comparison table
    print(f"\n  {'Floor':>6s} | {'Sharpe':>7s} | {'CAGR':>7s} | {'MDD':>8s} | "
          f"{'Sortino':>8s} | {'Calmar':>7s} | {'Vol':>6s} | {'Turnover':>8s} | "
          f"{'MeanW':>6s} | {'FloorBind':>9s}")
    print(f"  {'-'*6}-+-{'-'*7}-+-{'-'*7}-+-{'-'*8}-+-"
          f"{'-'*8}-+-{'-'*7}-+-{'-'*6}-+-{'-'*8}-+-"
          f"{'-'*6}-+-{'-'*9}")

    for d in floor_data:
        sortino_str = f"{d['sortino']:.4f}" if d['sortino'] is not None else "N/A"
        calmar_str = f"{d['calmar']:.4f}" if d['calmar'] is not None else "N/A"
        print(f"  {d['floor_pct']:5.0f}% | {d['sharpe']:7.4f} | "
              f"{d['cagr']*100:6.2f}% | {d['mdd']*100:7.2f}% | "
              f"{sortino_str:>8s} | {calmar_str:>7s} | "
              f"{d['ann_vol']*100:5.2f}% | {d['annual_turnover']:8.2f} | "
              f"{d['mean_weight']:6.3f} | {d['frac_at_floor']*100:8.1f}%")

    # BH row
    bh_sortino = f"{bh['sortino']:.4f}" if bh.get('sortino') is not None else "N/A"
    bh_calmar = f"{bh['calmar']:.4f}" if bh.get('calmar') is not None else "N/A"
    print(f"  {'BH':>5s}  | {bh['sharpe']:7.4f} | "
          f"{bh['cagr']*100:6.2f}% | {bh['mdd']*100:7.2f}% | "
          f"{bh_sortino:>8s} | {bh_calmar:>7s} | "
          f"{bh['ann_vol']*100:5.2f}% | {bh['annual_turnover']:8.2f} | "
          f"{bh['mean_weight']:6.3f} | {bh['frac_at_floor']*100:8.1f}%")

    # Find optimal floor for each metric
    best_sharpe = max(floor_data, key=lambda x: x["sharpe"])
    best_cagr = max(floor_data, key=lambda x: x["cagr"])
    best_mdd = max(floor_data, key=lambda x: x["mdd"])  # MDD is negative, max = least drawdown

    # For Sortino and Calmar, handle None
    sortino_valid = [d for d in floor_data if d["sortino"] is not None]
    calmar_valid = [d for d in floor_data if d["calmar"] is not None]
    best_sortino = max(sortino_valid, key=lambda x: x["sortino"]) if sortino_valid else None
    best_calmar = max(calmar_valid, key=lambda x: x["calmar"]) if calmar_valid else None

    print(f"\n  Optimal floors:")
    print(f"    Best Sharpe:  floor={best_sharpe['floor_pct']:.0f}% → Sharpe={best_sharpe['sharpe']:.4f}")
    print(f"    Best CAGR:    floor={best_cagr['floor_pct']:.0f}% → CAGR={best_cagr['cagr']*100:.2f}%")
    print(f"    Best MDD:     floor={best_mdd['floor_pct']:.0f}% → MDD={best_mdd['mdd']*100:.2f}%")
    if best_sortino:
        print(f"    Best Sortino: floor={best_sortino['floor_pct']:.0f}% → Sortino={best_sortino['sortino']:.4f}")
    if best_calmar:
        print(f"    Best Calmar:  floor={best_calmar['floor_pct']:.0f}% → Calmar={best_calmar['calmar']:.4f}")

    # At what floor does VT START beating BH on Sharpe?
    beating_bh = [d for d in floor_data if d["sharpe"] > bh_sharpe]
    if beating_bh:
        first_beating = min(beating_bh, key=lambda x: x["floor_pct"])
        last_beating = max(beating_bh, key=lambda x: x["floor_pct"])
        print(f"\n  Floors beating BH 50/50 on Sharpe ({bh_sharpe:.4f}):")
        for d in beating_bh:
            print(f"    Floor {d['floor_pct']:.0f}%: Sharpe={d['sharpe']:.4f} "
                  f"(+{(d['sharpe'] - bh_sharpe):.4f})")
        print(f"    Range: {first_beating['floor_pct']:.0f}% to {last_beating['floor_pct']:.0f}%")
    else:
        print(f"\n  NO floor beats BH 50/50 on Sharpe ({bh_sharpe:.4f})")
        # Find closest
        closest = min(floor_data, key=lambda x: abs(x["sharpe"] - bh_sharpe))
        print(f"    Closest: floor={closest['floor_pct']:.0f}% with Sharpe={closest['sharpe']:.4f} "
              f"(gap={bh_sharpe - closest['sharpe']:.4f})")

    # MDD improvement vs BH
    print(f"\n  MDD improvement vs BH ({bh['mdd']*100:.2f}%):")
    for d in floor_data:
        mdd_improvement = (d["mdd"] - bh["mdd"]) / abs(bh["mdd"]) * 100
        print(f"    Floor {d['floor_pct']:3.0f}%: MDD={d['mdd']*100:.2f}% "
              f"({mdd_improvement:+.1f}% vs BH)")

    # CAGR cost of each floor vs BH
    print(f"\n  CAGR cost vs BH ({bh['cagr']*100:.2f}%):")
    for d in floor_data:
        cagr_diff = (d["cagr"] - bh["cagr"]) * 100
        print(f"    Floor {d['floor_pct']:3.0f}%: CAGR={d['cagr']*100:.2f}% "
              f"({cagr_diff:+.2f}pp)")

    analysis = {
        "best_sharpe_floor": best_sharpe["floor_pct"],
        "best_sharpe_value": best_sharpe["sharpe"],
        "best_cagr_floor": best_cagr["floor_pct"],
        "best_cagr_value": best_cagr["cagr"],
        "best_mdd_floor": best_mdd["floor_pct"],
        "best_mdd_value": best_mdd["mdd"],
        "bh_sharpe": bh_sharpe,
        "bh_cagr": bh["cagr"],
        "bh_mdd": bh["mdd"],
        "floors_beating_bh_sharpe": [d["floor_pct"] for d in beating_bh],
        "n_floors_beating_bh": len(beating_bh),
    }

    if best_sortino:
        analysis["best_sortino_floor"] = best_sortino["floor_pct"]
        analysis["best_sortino_value"] = best_sortino["sortino"]
    if best_calmar:
        analysis["best_calmar_floor"] = best_calmar["floor_pct"]
        analysis["best_calmar_value"] = best_calmar["calmar"]

    return analysis


def marginal_analysis(sweep_results):
    """Compute marginal changes per 10pp floor increase."""
    print("\n" + "=" * 70)
    print("MARGINAL ANALYSIS: Change per 10pp Floor Increase")
    print("=" * 70)

    floor_data = []
    for key, val in sweep_results.items():
        if key.startswith("floor_"):
            floor_data.append(val)
    floor_data.sort(key=lambda x: x["floor_pct"])

    if len(floor_data) < 2:
        return {}

    marginals = []
    print(f"\n  {'From→To':>12s} | {'ΔSharpe':>8s} | {'ΔCAGR':>8s} | {'ΔMDD':>8s} | "
          f"{'ΔVol':>7s} | {'ΔTurnover':>9s}")
    print(f"  {'-'*12}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-"
          f"{'-'*7}-+-{'-'*9}")

    for i in range(1, len(floor_data)):
        prev = floor_data[i - 1]
        curr = floor_data[i]
        d_sharpe = curr["sharpe"] - prev["sharpe"]
        d_cagr = (curr["cagr"] - prev["cagr"]) * 100
        d_mdd = (curr["mdd"] - prev["mdd"]) * 100
        d_vol = (curr["ann_vol"] - prev["ann_vol"]) * 100
        d_turnover = curr["annual_turnover"] - prev["annual_turnover"]

        label = f"{prev['floor_pct']:.0f}%→{curr['floor_pct']:.0f}%"
        print(f"  {label:>12s} | {d_sharpe:+8.4f} | {d_cagr:+7.2f}pp | "
              f"{d_mdd:+7.2f}pp | {d_vol:+6.2f}pp | {d_turnover:+9.2f}")

        marginals.append({
            "from_floor": prev["floor_pct"],
            "to_floor": curr["floor_pct"],
            "delta_sharpe": round(d_sharpe, 4),
            "delta_cagr_pp": round(d_cagr, 2),
            "delta_mdd_pp": round(d_mdd, 2),
            "delta_vol_pp": round(d_vol, 2),
            "delta_turnover": round(d_turnover, 2),
        })

    # Find the floor step with the largest Sharpe improvement
    if marginals:
        best_step = max(marginals, key=lambda x: x["delta_sharpe"])
        print(f"\n  Largest Sharpe improvement: "
              f"{best_step['from_floor']:.0f}%→{best_step['to_floor']:.0f}% "
              f"(+{best_step['delta_sharpe']:.4f})")

    return {"marginals": marginals}


def crisis_period_analysis(data):
    """Analyze floor strategy performance during specific crisis periods."""
    print("\n" + "=" * 70)
    print("CRISIS PERIOD ANALYSIS")
    print("=" * 70)

    # Define crisis periods
    crises = {
        "GFC (2008-09 to 2009-03)": ("2008-09-01", "2009-03-31"),
        "COVID Crash (2020-02 to 2020-04)": ("2020-02-15", "2020-04-30"),
        "2022 Bear (2022-01 to 2022-10)": ("2022-01-01", "2022-10-31"),
    }

    # Also define recovery periods (first 6 months after crisis)
    recoveries = {
        "GFC Recovery (2009-03 to 2009-09)": ("2009-03-09", "2009-09-30"),
        "COVID Recovery (2020-03 to 2020-09)": ("2020-03-23", "2020-09-30"),
        "2022 Recovery (2022-10 to 2023-04)": ("2022-10-12", "2023-04-30"),
    }

    crisis_results = {}

    for period_name, (start, end) in {**crises, **recoveries}.items():
        mask = (data.index >= start) & (data.index <= end)
        period_data = data[mask]

        if len(period_data) < 10:
            continue

        port_ret = (0.5 * period_data["spy_ret"] + 0.5 * period_data["gld_ret"]).values
        vix = data["vix"]

        print(f"\n  {period_name} ({len(period_data)} days):")
        print(f"    VIX range: {period_data['vix'].min():.1f} - {period_data['vix'].max():.1f}")

        period_results = {}

        # BH return
        bh_cum = float(np.prod(1 + port_ret) - 1)
        period_results["BH"] = round(bh_cum * 100, 2)
        print(f"    BH 50/50: {bh_cum*100:+.2f}%")

        # Each floor
        for floor in [0.0, 0.20, 0.40, 0.60]:
            raw_w = np.minimum(12.0 / vix, 1.0)
            floored_w = np.maximum(raw_w, floor)
            lagged_w = floored_w.shift(1)
            w_period = lagged_w[mask].values

            valid = ~np.isnan(w_period)
            if valid.sum() < 5:
                continue

            w_v = w_period[valid]
            r_v = port_ret[valid]
            weighted_ret = w_v * r_v + (1 - w_v) * RF_DAILY
            cum = float(np.prod(1 + weighted_ret) - 1)

            period_results[f"floor_{int(floor*100)}"] = round(cum * 100, 2)
            print(f"    Floor {floor*100:3.0f}%: {cum*100:+.2f}% "
                  f"(avg weight: {np.mean(w_v):.3f})")

        crisis_results[period_name] = period_results

    return crisis_results


def t_test_vs_bh(data, best_floor):
    """Two-sided t-test: does the best floor significantly differ from BH?"""
    print("\n" + "=" * 70)
    print(f"T-TEST: Floor {best_floor*100:.0f}% vs BH 50/50")
    print("=" * 70)

    vix = data["vix"]
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()
    port_ret = (0.5 * df["spy_ret"] + 0.5 * df["gld_ret"]).values

    # Floor strategy returns
    raw_w = np.minimum(12.0 / vix, 1.0)
    floored_w = np.maximum(raw_w, best_floor)
    lagged_w = floored_w.shift(1)
    w = lagged_w[eval_mask].values

    valid = ~np.isnan(w)
    w_v = w[valid]
    r_v = port_ret[valid]

    tc_rate = TC_BPS / 10000.0
    floor_returns = np.zeros(len(w_v))
    prev_w = w_v[0]
    for i in range(len(w_v)):
        tc = tc_rate * abs(w_v[i] - prev_w)
        floor_returns[i] = w_v[i] * r_v[i] + (1 - w_v[i]) * RF_DAILY - tc
        prev_w = w_v[i]

    bh_returns = port_ret[valid]

    # Paired t-test on daily return differences
    diff = floor_returns - bh_returns
    t_stat, p_value = sp_stats.ttest_1samp(diff, 0)

    mean_diff = np.mean(diff) * 252 * 100  # annualized pp
    se_diff = np.std(diff, ddof=1) / np.sqrt(len(diff)) * np.sqrt(252) * 100

    print(f"  N = {len(diff)} daily observations")
    print(f"  Mean daily diff = {np.mean(diff)*10000:.4f} bps")
    print(f"  Annualized diff = {mean_diff:.2f} pp")
    print(f"  t-statistic = {t_stat:.4f}")
    print(f"  p-value = {p_value:.4f}")
    print(f"  Harvey (2016) threshold: |t| > 3.0 → {'PASS' if abs(t_stat) > 3.0 else 'FAIL'}")

    return {
        "floor_pct": best_floor * 100,
        "n_obs": len(diff),
        "mean_daily_diff_bps": round(float(np.mean(diff) * 10000), 4),
        "annualized_diff_pp": round(float(mean_diff), 2),
        "t_statistic": round(float(t_stat), 4),
        "p_value": round(float(p_value), 4),
        "passes_harvey_threshold": bool(abs(t_stat) > 3.0),
    }


# ============================================================================
# Main
# ============================================================================
def main():
    start_time = datetime.now()

    # Download data
    data = download_data()

    # Descriptive statistics
    desc_stats = descriptive_stats(data)

    # Floor sweep
    sweep_results = run_floor_sweep(data)

    # Optimal floor analysis
    analysis = analyze_optimal_floor(sweep_results)

    # Marginal analysis
    marginals = marginal_analysis(sweep_results)

    # Crisis period analysis
    crisis = crisis_period_analysis(data)

    # T-test for best floor vs BH
    best_floor_pct = analysis.get("best_sharpe_floor", 0)
    t_test = t_test_vs_bh(data, best_floor_pct / 100.0)

    elapsed = (datetime.now() - start_time).total_seconds()

    # =============================================
    # Final Summary
    # =============================================
    print(f"\n{'=' * 70}")
    print(f"K696 FINAL SUMMARY")
    print(f"{'=' * 70}")

    bh_sharpe = analysis.get("bh_sharpe", np.nan)
    best_sharpe = analysis.get("best_sharpe_value", np.nan)
    best_floor = analysis.get("best_sharpe_floor", np.nan)

    print(f"\n  BH 50/50 Sharpe:     {bh_sharpe:.4f}")
    print(f"  Best floor Sharpe:   {best_sharpe:.4f} (floor={best_floor:.0f}%)")
    print(f"  Sharpe difference:   {best_sharpe - bh_sharpe:+.4f}")
    print(f"  Floors beating BH:   {analysis.get('n_floors_beating_bh', 0)}")
    print(f"  t-test p-value:      {t_test.get('p_value', 'N/A')}")

    # Key narrative
    if analysis.get("n_floors_beating_bh", 0) > 0:
        print(f"\n  ★ FINDING: Floor(s) {analysis['floors_beating_bh_sharpe']} beat BH on Sharpe!")
        print(f"    → A minimum exposure floor CAN improve VT vs pure BH")
    else:
        print(f"\n  ★ FINDING: No floor beats BH on Sharpe")
        print(f"    → Even with floors, 12/VIX cannot overcome the CAGR drag")

    # The trade-off insight
    print(f"\n  Trade-off summary:")
    print(f"    Floor  0% → pure VT: best MDD protection, worst CAGR")
    print(f"    Floor 70% → mostly BH: small MDD benefit, near-BH CAGR")
    print(f"    Floor 100% → pure BH: no MDD protection, best CAGR")

    # =============================================
    # Save results
    # =============================================
    results = {
        "experiment_id": "K696",
        "title": "The Cost of Being Out — Minimum Exposure Floors for VT Strategies",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "yfinance",
        "data_period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{EVAL_START} to {END_DATE}",
        "floors_tested": [f * 100 for f in FLOORS],
        "tx_cost_bps": TC_BPS,
        "rf_annual": RF_ANNUAL,
        "signal": "weight_t = max(floor, min(12/VIX_{t-1}, 1.0))",
        "lag": "1 day (proper)",
        "portfolio": "50/50 SPY/GLD",
        "elapsed_seconds": round(elapsed, 1),
        "descriptive_stats": desc_stats,
        "floor_sweep_results": sweep_results,
        "optimal_floor_analysis": analysis,
        "marginal_analysis": marginals,
        "crisis_period_analysis": crisis,
        "t_test_best_vs_bh": t_test,
        "key_findings": {
            "best_sharpe_floor_pct": analysis.get("best_sharpe_floor"),
            "best_sharpe_value": analysis.get("best_sharpe_value"),
            "bh_sharpe": analysis.get("bh_sharpe"),
            "does_any_floor_beat_bh": analysis.get("n_floors_beating_bh", 0) > 0,
            "floors_beating_bh": analysis.get("floors_beating_bh_sharpe", []),
        },
        "references": [
            "K687: Definitive lag-corrected strategy ranking (BH 50/50 beats all VT on Sharpe)",
            "K688: CRRA utility framework (VT wins for gamma>=5)",
            "K690: Weight Smoothness and Lag Robustness",
            "Copeland & Copeland (1999): Market Timing with VIX",
            "Fleming, Kirby & Ostdiek (2001): The Economic Value of Volatility Timing",
            "Kirby & Ostdiek (2012): It's All in the Timing",
            "Harvey et al. (2016): ...and the Cross-Section of Expected Returns",
        ],
        "limitations": [
            "Only tests 12/VIX signal; other VT signals may respond differently to floors",
            "Floor values tested in 10pp increments; finer grid might find better optimum",
            "TX cost model simplified (fixed 5bps); real costs vary",
            "50/50 SPY/GLD only; other allocations may shift optimal floor",
            "Sample period includes unprecedented Fed QE; floor benefit may change in future regimes",
            "No out-of-sample split; optimal floor likely overfits in-sample",
        ],
    }

    print(f"\n{'=' * 70}")
    print(f"SAVING RESULTS to {RESULTS_FILE}")
    print(f"{'=' * 70}")

    RESULTS_FILE.write_text(json.dumps(results, indent=2, default=str))
    print(f"  Saved. Elapsed: {elapsed:.1f}s")

    return results


if __name__ == "__main__":
    main()
