#!/usr/bin/env python3
"""
K551: VIX-Conditional Leverage — Deep Validation for Potential Listing

K548 found VIX-Conditional Leverage (1.5x when VIX<15, 1.0x when VIX>25) achieves
Sharpe 1.497, CAGR 18.26%, 5/5 cross-OOS wins. This is comprehensive validation
before considering strategy listing per CLAUDE.md standards.

Validation checklist:
  1. Harvey (2016) t>3.0: DM test with Newey-West HAC
  2. 5-Period Cross-OOS with TWO different period splits
  3. Sensitivity analysis: leverage range, VIX threshold grid
  4. Transaction cost impact + breakeven TX cost
  5. Borrowing cost sensitivity (0-8%)
  6. Drawdown analysis during GFC, COVID, 2022
  7. Bootstrap confidence intervals (5000 reps)
  8. Taiwan test: 0050.TW with 8.63/VIX

References:
  Harvey et al. (2016) "...and the Cross-Section of Expected Returns" RFS — t>3.0 threshold
  Moreira & Muir (2017) "Volatility-Managed Portfolios" JF
  K548 (this system): Original VIX-Conditional Leverage finding
  K550: Adaptive VIX threshold analysis

Author: VolPred Research System (Claude)
Data: yfinance (SPY, GLD, ^VIX, ^IRX, 0050.TW), 2005-2026
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ─────────────────────────── Config ───────────────────────────
START = "2004-12-01"
END = "2026-03-27"
BORROWING_SPREAD = 0.005  # 50bps above risk-free
FALLBACK_RF = 0.04
N_BOOTSTRAP = 5000
np.random.seed(42)

# Cross-OOS periods — Primary split (from K548)
OOS_PRIMARY = [
    ("2005-06-01", "2009-05-31"),
    ("2009-06-01", "2013-05-31"),
    ("2013-06-01", "2017-05-31"),
    ("2017-06-01", "2021-05-31"),
    ("2021-06-01", "2026-03-27"),
]

# Cross-OOS periods — Alternative split (requested)
OOS_ALTERNATIVE = [
    ("2005-06-01", "2008-12-31"),
    ("2009-01-01", "2012-12-31"),
    ("2013-01-01", "2016-12-31"),
    ("2017-01-01", "2019-12-31"),
    ("2020-01-01", "2022-12-31"),
    ("2023-01-01", "2026-03-27"),
]

# Crisis periods for drawdown analysis
CRISIS_PERIODS = {
    "GFC": ("2007-10-01", "2009-06-30"),
    "COVID": ("2020-01-15", "2020-06-30"),
    "2022_Bear": ("2022-01-01", "2022-12-31"),
}


def download_data():
    """Download SPY, GLD, VIX, and risk-free rate."""
    print("=" * 70)
    print("DOWNLOADING DATA")
    print("=" * 70)
    spy = yf.download("SPY", start=START, end=END, progress=False)
    gld = yf.download("GLD", start=START, end=END, progress=False)
    vix = yf.download("^VIX", start=START, end=END, progress=False)

    try:
        irx = yf.download("^IRX", start=START, end=END, progress=False)
        rf_available = len(irx) > 100
    except Exception:
        irx = None
        rf_available = False

    for df in [spy, gld, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    if irx is not None and isinstance(irx.columns, pd.MultiIndex):
        irx.columns = irx.columns.get_level_values(0)

    data = pd.DataFrame(index=spy.index)
    data["spy_close"] = spy["Close"]
    data["gld_close"] = gld["Close"]
    data["vix"] = vix["Close"]

    if rf_available and irx is not None and len(irx) > 0:
        data["rf_annual"] = irx["Close"].reindex(data.index).ffill() / 100
        data["rf_daily"] = data["rf_annual"] / 252
        print(f"  Risk-free rate from ^IRX: mean={data['rf_annual'].mean()*100:.2f}%")
    else:
        data["rf_annual"] = FALLBACK_RF
        data["rf_daily"] = FALLBACK_RF / 252
        print(f"  Using fallback risk-free rate: {FALLBACK_RF*100:.1f}%")

    data = data.ffill().dropna()
    data["spy_ret"] = data["spy_close"].pct_change()
    data["gld_ret"] = data["gld_close"].pct_change()
    data = data.dropna()
    data["vix_weight"] = np.minimum(12.0 / data["vix"], 1.0)
    data = data.iloc[1:]  # remove first row with NaN returns

    print(f"  Data: {data.index[0].date()} to {data.index[-1].date()}, N={len(data)}")
    return data


def compute_base_returns(data):
    """Base 50/50 VT returns (unleveraged)."""
    w = data["vix_weight"]
    return w * (0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]) + (1 - w) * data["rf_daily"]


def compute_vix_conditional_returns(data, low_vix=15, high_vix=25, max_lev=1.5,
                                     borrow_spread=BORROWING_SPREAD, borrow_override=None):
    """
    VIX-Conditional Leverage returns.
    lev = max_lev when VIX < low_vix, 1.0 when VIX > high_vix, linear between.
    """
    w = data["vix_weight"]
    vix_cond_lev = np.clip(
        max_lev - (max_lev - 1.0) * (data["vix"] - low_vix) / (high_vix - low_vix),
        1.0, max_lev
    )
    effective_lev = w * vix_cond_lev
    gross_ret = effective_lev * (0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]) + \
                (1 - effective_lev) * data["rf_daily"]

    # Borrowing cost
    if borrow_override is not None:
        borrow_daily = borrow_override / 252
    else:
        borrow_daily = data["rf_daily"] + borrow_spread / 252

    borrow_cost = np.maximum(effective_lev - 1, 0) * borrow_daily
    return gross_ret - borrow_cost, vix_cond_lev, effective_lev


def compute_metrics(returns_series, rf_series=None):
    """Standard performance metrics."""
    r = returns_series.dropna()
    if len(r) < 126:
        return None

    cum = (1 + r).cumprod()
    total_return = cum.iloc[-1] - 1
    years = len(r) / 252
    cagr = (1 + total_return) ** (1 / years) - 1
    ann_vol = r.std() * np.sqrt(252)

    if rf_series is not None:
        rf_aligned = rf_series.reindex(r.index).fillna(FALLBACK_RF / 252)
        excess = r - rf_aligned
    else:
        excess = r - FALLBACK_RF / 252
    sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else 0

    running_max = cum.cummax()
    drawdown = cum / running_max - 1
    mdd = drawdown.min()
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    downside = excess[excess < 0]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-8
    sortino = excess.mean() * 252 / downside_std

    # Underwater duration
    underwater = drawdown < 0
    if underwater.any():
        groups = (~underwater).cumsum()
        underwater_durations = underwater.groupby(groups).sum()
        max_underwater = underwater_durations.max()
    else:
        max_underwater = 0

    return {
        "cagr": round(cagr * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "skew": round(r.skew(), 3),
        "kurtosis": round(r.kurtosis(), 3),
        "total_return_pct": round(total_return * 100, 2),
        "years": round(years, 1),
        "n_days": len(r),
        "max_underwater_days": int(max_underwater),
    }


# ═══════════════════════════════════════════════════════════════
# TEST 1: Harvey (2016) DM Test with Newey-West HAC
# ═══════════════════════════════════════════════════════════════
def test_harvey_dm(strat_ret, base_ret, max_lag=10):
    """
    Diebold-Mariano test on daily returns using Newey-West HAC.
    H0: strategy has same mean return as base.
    Uses return difference (not squared returns — we want to test mean return difference).
    Also test Sharpe difference via Jobson-Korkie-Memmel.
    """
    print("\n" + "=" * 70)
    print("TEST 1: HARVEY (2016) STATISTICAL SIGNIFICANCE")
    print("=" * 70)

    # Align returns
    idx = strat_ret.index.intersection(base_ret.index)
    s = strat_ret.loc[idx].values
    b = base_ret.loc[idx].values
    d = s - b  # return difference
    n = len(d)

    # --- 1a: DM test on mean return difference with Newey-West ---
    d_mean = np.mean(d)

    # Newey-West HAC variance with optimal bandwidth
    # Bandwidth selection: Andrews (1991) — use Bartlett kernel with lag = int(4*(n/100)^(2/9))
    opt_lag = int(4 * (n / 100) ** (2 / 9))
    print(f"  Newey-West optimal bandwidth: {opt_lag} lags")

    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, opt_lag + 1):
        w = 1 - k / (opt_lag + 1)  # Bartlett kernel
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * w * gamma_k
    nw_var = (gamma0 + gamma_sum) / n

    if nw_var <= 0:
        print("  WARNING: Negative NW variance, using simple variance")
        nw_var = gamma0 / n

    dm_t = d_mean / np.sqrt(nw_var)
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_t)))

    print(f"\n  DM Test (mean return difference, NW HAC):")
    print(f"    Mean daily return diff: {d_mean*10000:.4f} bps")
    print(f"    Annualized return diff: {d_mean*252*100:.2f}%")
    print(f"    DM t-statistic: {dm_t:.4f}")
    print(f"    p-value: {dm_p:.6f}")
    print(f"    Harvey (2016) t>3.0: {'PASS ✓' if abs(dm_t) > 3.0 else 'FAIL ✗'}")

    # --- 1b: Jobson-Korkie-Memmel Sharpe difference test ---
    rf_daily = FALLBACK_RF / 252
    e_s = s - rf_daily
    e_b = b - rf_daily
    mu_s, mu_b = np.mean(e_s), np.mean(e_b)
    s_s, s_b = np.std(e_s, ddof=1), np.std(e_b, ddof=1)
    sr_s, sr_b = mu_s / s_s, mu_b / s_b
    rho = np.corrcoef(e_s, e_b)[0, 1]

    # Memmel (2003) corrected variance for Sharpe diff
    theta = (1 / n) * (
        2 * (1 - rho) + 0.5 * (sr_s ** 2 + sr_b ** 2 - 2 * sr_s * sr_b * rho ** 2)
    )
    if theta > 0:
        jkm_z = (sr_s - sr_b) / np.sqrt(theta)
        jkm_p = 2 * (1 - stats.norm.cdf(abs(jkm_z)))
    else:
        jkm_z, jkm_p = np.nan, np.nan

    print(f"\n  Jobson-Korkie-Memmel Sharpe Diff Test:")
    print(f"    Strategy daily Sharpe: {sr_s*np.sqrt(252):.4f}")
    print(f"    Base daily Sharpe:     {sr_b*np.sqrt(252):.4f}")
    print(f"    Sharpe diff:           {(sr_s-sr_b)*np.sqrt(252):.4f}")
    print(f"    Correlation (ρ):       {rho:.4f}")
    print(f"    JKM z-statistic:       {jkm_z:.4f}")
    print(f"    JKM p-value:           {jkm_p:.6f}")
    print(f"    Harvey t>3.0:          {'PASS ✓' if abs(jkm_z) > 3.0 else 'FAIL ✗'}")

    # --- 1c: Also test with squared returns (volatility loss) ---
    d_sq = s ** 2 - b ** 2
    d_sq_mean = np.mean(d_sq)
    gamma0_sq = np.var(d_sq, ddof=1)
    gamma_sum_sq = 0
    for k in range(1, opt_lag + 1):
        w = 1 - k / (opt_lag + 1)
        gamma_k_sq = np.cov(d_sq[k:], d_sq[:-k])[0, 1]
        gamma_sum_sq += 2 * w * gamma_k_sq
    nw_var_sq = (gamma0_sq + gamma_sum_sq) / n
    if nw_var_sq > 0:
        dm_sq_t = d_sq_mean / np.sqrt(nw_var_sq)
        dm_sq_p = 2 * (1 - stats.norm.cdf(abs(dm_sq_t)))
    else:
        dm_sq_t, dm_sq_p = np.nan, np.nan

    print(f"\n  DM Test (squared returns, variance loss):")
    print(f"    t-stat: {dm_sq_t:.4f}, p-value: {dm_sq_p:.6f}")

    return {
        "dm_return_diff": {
            "daily_diff_bps": round(d_mean * 10000, 4),
            "annualized_diff_pct": round(d_mean * 252 * 100, 2),
            "t_stat": round(dm_t, 4),
            "p_value": round(dm_p, 6),
            "nw_bandwidth": opt_lag,
            "pass_harvey_3": abs(dm_t) > 3.0,
        },
        "jkm_sharpe_diff": {
            "strat_sharpe": round(sr_s * np.sqrt(252), 4),
            "base_sharpe": round(sr_b * np.sqrt(252), 4),
            "sharpe_diff": round((sr_s - sr_b) * np.sqrt(252), 4),
            "correlation": round(rho, 4),
            "z_stat": round(jkm_z, 4),
            "p_value": round(jkm_p, 6),
            "pass_harvey_3": abs(jkm_z) > 3.0 if not np.isnan(jkm_z) else False,
        },
        "dm_variance_loss": {
            "t_stat": round(dm_sq_t, 4) if not np.isnan(dm_sq_t) else None,
            "p_value": round(dm_sq_p, 6) if not np.isnan(dm_sq_p) else None,
        },
    }


# ═══════════════════════════════════════════════════════════════
# TEST 2: Cross-OOS with Two Different Splits
# ═══════════════════════════════════════════════════════════════
def test_cross_oos(data, strat_ret, base_ret):
    """Run cross-OOS on two different period splits."""
    print("\n" + "=" * 70)
    print("TEST 2: CROSS-OOS VALIDATION (TWO SPLITS)")
    print("=" * 70)

    results = {}
    for split_name, periods in [("primary", OOS_PRIMARY), ("alternative", OOS_ALTERNATIVE)]:
        print(f"\n  --- {split_name.upper()} SPLIT ({len(periods)} periods) ---")
        period_results = []
        strat_wins = 0

        for i, (start, end) in enumerate(periods):
            mask = (data.index >= start) & (data.index <= end)
            s_sub = strat_ret.loc[mask]
            b_sub = base_ret.loc[mask]
            rf_sub = data["rf_daily"].loc[mask]

            if len(s_sub) < 126:
                continue

            m_s = compute_metrics(s_sub, rf_sub)
            m_b = compute_metrics(b_sub, rf_sub)

            if m_s and m_b:
                diff = m_s["sharpe"] - m_b["sharpe"]
                win = m_s["sharpe"] > m_b["sharpe"]
                if win:
                    strat_wins += 1

                print(f"    P{i+1} ({start[:4]}-{end[:4]}): "
                      f"Strat={m_s['sharpe']:.3f} vs Base={m_b['sharpe']:.3f} "
                      f"Δ={diff:+.3f} {'WIN' if win else 'LOSE'} | "
                      f"CAGR: {m_s['cagr']:.1f}% vs {m_b['cagr']:.1f}%")

                period_results.append({
                    "period": f"P{i+1}: {start[:4]}-{end[:4]}",
                    "strat_sharpe": m_s["sharpe"],
                    "base_sharpe": m_b["sharpe"],
                    "sharpe_diff": round(diff, 3),
                    "strat_cagr": m_s["cagr"],
                    "base_cagr": m_b["cagr"],
                    "strat_mdd": m_s["mdd"],
                    "base_mdd": m_b["mdd"],
                    "win": win,
                    "n_days": m_s["n_days"],
                })

        n_periods = len(period_results)
        print(f"\n    RESULT: {strat_wins}/{n_periods} wins")

        results[split_name] = {
            "periods": period_results,
            "wins": strat_wins,
            "total": n_periods,
            "win_rate": round(strat_wins / n_periods * 100, 1) if n_periods > 0 else 0,
            "mean_sharpe_diff": round(
                np.mean([p["sharpe_diff"] for p in period_results]), 3
            ) if period_results else 0,
        }

    return results


# ═══════════════════════════════════════════════════════════════
# TEST 3: Sensitivity Analysis
# ═══════════════════════════════════════════════════════════════
def test_sensitivity(data, base_ret):
    """Test sensitivity to leverage level and VIX thresholds."""
    print("\n" + "=" * 70)
    print("TEST 3: SENSITIVITY ANALYSIS")
    print("=" * 70)

    base_m = compute_metrics(base_ret, data["rf_daily"])
    base_sharpe = base_m["sharpe"]
    print(f"  Base Sharpe: {base_sharpe:.3f}")

    # --- 3a: Leverage range (1.1x to 2.0x) with default VIX thresholds ---
    print("\n  --- LEVERAGE RANGE (low=15, high=25) ---")
    lev_results = {}
    for lev in np.arange(1.1, 2.05, 0.1):
        lev = round(lev, 1)
        ret, _, _ = compute_vix_conditional_returns(data, 15, 25, lev)
        m = compute_metrics(ret, data["rf_daily"])
        if m:
            diff = m["sharpe"] - base_sharpe
            print(f"    Lev={lev:.1f}x: Sharpe={m['sharpe']:.3f} (Δ={diff:+.3f}), "
                  f"CAGR={m['cagr']:.1f}%, MDD={m['mdd']:.1f}%")
            lev_results[str(lev)] = {
                "sharpe": m["sharpe"],
                "sharpe_diff": round(diff, 3),
                "cagr": m["cagr"],
                "mdd": m["mdd"],
                "calmar": m["calmar"],
                "sortino": m["sortino"],
            }

    # --- 3b: VIX threshold grid ---
    print("\n  --- VIX THRESHOLD GRID (lev=1.5x) ---")
    low_thresholds = [10, 12, 14, 16, 18]
    high_thresholds = [20, 22, 25, 28, 30]
    grid_results = {}

    # Print header
    header = "        " + "".join(f"  H={h:2d}  " for h in high_thresholds)
    print(header)

    for low in low_thresholds:
        row = f"  L={low:2d}: "
        for high in high_thresholds:
            if high <= low:
                row += "   ---  "
                continue
            ret, _, _ = compute_vix_conditional_returns(data, low, high, 1.5)
            m = compute_metrics(ret, data["rf_daily"])
            if m:
                diff = m["sharpe"] - base_sharpe
                grid_results[f"L{low}_H{high}"] = {
                    "sharpe": m["sharpe"],
                    "sharpe_diff": round(diff, 3),
                    "cagr": m["cagr"],
                    "mdd": m["mdd"],
                }
                row += f" {diff:+.3f} "
            else:
                row += "   N/A  "
        print(row)

    # Identify safe zone
    positive_configs = [k for k, v in grid_results.items() if v["sharpe_diff"] > 0]
    total_configs = len([k for k in grid_results if "N/A" not in str(grid_results.get(k, {}))])
    safe_ratio = len(positive_configs) / total_configs if total_configs > 0 else 0

    print(f"\n  SAFE ZONE: {len(positive_configs)}/{total_configs} configs beat base "
          f"({safe_ratio*100:.1f}%)")

    # Best and worst
    if grid_results:
        best_k = max(grid_results, key=lambda k: grid_results[k]["sharpe_diff"])
        worst_k = min(grid_results, key=lambda k: grid_results[k]["sharpe_diff"])
        print(f"  Best:  {best_k} → Sharpe {grid_results[best_k]['sharpe']:.3f} "
              f"(Δ={grid_results[best_k]['sharpe_diff']:+.3f})")
        print(f"  Worst: {worst_k} → Sharpe {grid_results[worst_k]['sharpe']:.3f} "
              f"(Δ={grid_results[worst_k]['sharpe_diff']:+.3f})")

    return {
        "leverage_range": lev_results,
        "vix_threshold_grid": grid_results,
        "safe_zone_ratio": round(safe_ratio * 100, 1),
        "n_positive": len(positive_configs),
        "n_total_configs": total_configs,
        "best_config": best_k if grid_results else None,
        "worst_config": worst_k if grid_results else None,
    }


# ═══════════════════════════════════════════════════════════════
# TEST 4: Transaction Cost Impact
# ═══════════════════════════════════════════════════════════════
def test_transaction_costs(data, base_ret):
    """Compute turnover and test with various TX cost levels."""
    print("\n" + "=" * 70)
    print("TEST 4: TRANSACTION COST IMPACT")
    print("=" * 70)

    # Compute daily weight changes for the strategy
    w = data["vix_weight"]
    vix_cond_lev = np.clip(1.5 - 0.5 * (data["vix"] - 15) / (25 - 15), 1.0, 1.5)
    effective_weight = w * vix_cond_lev

    # Daily turnover = |Δweight| (both SPY and GLD change together in 50/50)
    daily_turnover = np.abs(effective_weight.diff()).fillna(0)
    annual_turnover = daily_turnover.sum() / (len(data) / 252)
    mean_daily_to = daily_turnover.mean()

    print(f"  Mean daily turnover: {mean_daily_to*100:.4f}%")
    print(f"  Annual turnover: {annual_turnover*100:.1f}%")
    print(f"  Median daily turnover: {daily_turnover.median()*100:.4f}%")
    print(f"  Days with >1% turnover: {(daily_turnover > 0.01).sum()} "
          f"({(daily_turnover > 0.01).mean()*100:.1f}%)")

    # Also compute base turnover for comparison
    base_weight = w.copy()
    base_daily_to = np.abs(base_weight.diff()).fillna(0)
    base_annual_to = base_daily_to.sum() / (len(data) / 252)
    incremental_to = annual_turnover - base_annual_to
    print(f"\n  Base annual turnover: {base_annual_to*100:.1f}%")
    print(f"  INCREMENTAL turnover from leverage: {incremental_to*100:.1f}%")

    # Test with various TX costs
    tx_costs_bps = [0, 5, 10, 20, 50]
    tx_results = {}
    base_m = compute_metrics(base_ret, data["rf_daily"])

    print(f"\n  {'TX Cost':>10} {'Sharpe':>8} {'Δ vs Base':>10} {'CAGR':>8} {'Net Sharpe':>10}")
    print(f"  {'-'*50}")

    strat_ret_gross, _, _ = compute_vix_conditional_returns(data, 15, 25, 1.5)

    for tx_bps in tx_costs_bps:
        tx_cost = tx_bps / 10000
        # TX cost applied to turnover (both buy and sell side)
        tx_drag = daily_turnover * tx_cost * 2  # round-trip
        net_ret = strat_ret_gross - tx_drag
        m = compute_metrics(net_ret, data["rf_daily"])
        if m:
            diff = m["sharpe"] - base_m["sharpe"]
            print(f"  {tx_bps:>7}bps  {m['sharpe']:>7.3f}  {diff:>+9.3f}  "
                  f"{m['cagr']:>7.1f}%  {m['sharpe']:>9.3f}")
            tx_results[f"{tx_bps}bps"] = {
                "sharpe": m["sharpe"],
                "sharpe_diff_vs_base": round(diff, 3),
                "cagr": m["cagr"],
                "mdd": m["mdd"],
                "still_beats_base": diff > 0,
            }

    # Find breakeven TX cost via bisection
    lo, hi = 0, 500  # bps
    for _ in range(30):
        mid = (lo + hi) / 2
        tx_drag = daily_turnover * (mid / 10000) * 2
        net_ret = strat_ret_gross - tx_drag
        m = compute_metrics(net_ret, data["rf_daily"])
        if m and m["sharpe"] > base_m["sharpe"]:
            lo = mid
        else:
            hi = mid
    breakeven = round((lo + hi) / 2, 1)
    print(f"\n  BREAKEVEN TX COST: ~{breakeven:.0f} bps (one-way)")

    return {
        "annual_turnover_pct": round(annual_turnover * 100, 1),
        "base_annual_turnover_pct": round(base_annual_to * 100, 1),
        "incremental_turnover_pct": round(incremental_to * 100, 1),
        "mean_daily_turnover_pct": round(mean_daily_to * 100, 4),
        "tx_cost_results": tx_results,
        "breakeven_tx_bps": breakeven,
    }


# ═══════════════════════════════════════════════════════════════
# TEST 5: Borrowing Cost Sensitivity
# ═══════════════════════════════════════════════════════════════
def test_borrowing_costs(data, base_ret):
    """Test with various fixed borrowing rates."""
    print("\n" + "=" * 70)
    print("TEST 5: BORROWING COST SENSITIVITY")
    print("=" * 70)

    base_m = compute_metrics(base_ret, data["rf_daily"])
    borrow_rates = [0.0, 0.02, 0.04, 0.06, 0.08]
    results = {}

    print(f"  Base Sharpe: {base_m['sharpe']:.3f}, Base CAGR: {base_m['cagr']:.1f}%")
    print(f"\n  {'Borrow Rate':>12} {'Sharpe':>8} {'Δ vs Base':>10} {'CAGR':>8} {'Beats Base?':>12}")
    print(f"  {'-'*55}")

    for rate in borrow_rates:
        ret, _, _ = compute_vix_conditional_returns(
            data, 15, 25, 1.5, borrow_override=rate
        )
        m = compute_metrics(ret, data["rf_daily"])
        if m:
            diff = m["sharpe"] - base_m["sharpe"]
            beats = diff > 0
            print(f"  {rate*100:>10.0f}%  {m['sharpe']:>7.3f}  {diff:>+9.3f}  "
                  f"{m['cagr']:>7.1f}%  {'YES' if beats else 'NO':>11}")
            results[f"{int(rate*100)}pct"] = {
                "sharpe": m["sharpe"],
                "sharpe_diff": round(diff, 3),
                "cagr": m["cagr"],
                "mdd": m["mdd"],
                "beats_base": beats,
            }

    # Find breakeven borrowing rate
    lo, hi = 0, 0.20
    for _ in range(30):
        mid = (lo + hi) / 2
        ret, _, _ = compute_vix_conditional_returns(data, 15, 25, 1.5, borrow_override=mid)
        m = compute_metrics(ret, data["rf_daily"])
        if m and m["sharpe"] > base_m["sharpe"]:
            lo = mid
        else:
            hi = mid
    breakeven_rate = round((lo + hi) / 2 * 100, 1)
    print(f"\n  BREAKEVEN BORROWING RATE: ~{breakeven_rate:.1f}%")

    return {
        "results": results,
        "breakeven_rate_pct": breakeven_rate,
    }


# ═══════════════════════════════════════════════════════════════
# TEST 6: Drawdown Analysis During Crises
# ═══════════════════════════════════════════════════════════════
def test_drawdowns(data, strat_ret, base_ret):
    """Detailed drawdown analysis during crisis periods."""
    print("\n" + "=" * 70)
    print("TEST 6: CRISIS DRAWDOWN ANALYSIS")
    print("=" * 70)

    # Full-sample drawdown comparison
    strat_cum = (1 + strat_ret).cumprod()
    base_cum = (1 + base_ret).cumprod()
    spy_cum = (1 + data["spy_ret"]).cumprod()

    strat_dd = strat_cum / strat_cum.cummax() - 1
    base_dd = base_cum / base_cum.cummax() - 1
    spy_dd = spy_cum / spy_cum.cummax() - 1

    print(f"\n  FULL SAMPLE DRAWDOWN:")
    print(f"    Strategy MDD: {strat_dd.min()*100:.2f}%")
    print(f"    Base MDD:     {base_dd.min()*100:.2f}%")
    print(f"    SPY MDD:      {spy_dd.min()*100:.2f}%")

    crisis_results = {}

    for crisis_name, (start, end) in CRISIS_PERIODS.items():
        mask = (data.index >= start) & (data.index <= end)
        if mask.sum() < 10:
            continue

        s_sub = strat_ret.loc[mask]
        b_sub = base_ret.loc[mask]
        spy_sub = data["spy_ret"].loc[mask]

        # Compute crisis-period cumulative and drawdowns
        s_cum = (1 + s_sub).cumprod()
        b_cum = (1 + b_sub).cumprod()
        spy_c = (1 + spy_sub).cumprod()

        s_dd = (s_cum / s_cum.cummax() - 1).min()
        b_dd = (b_cum / b_cum.cummax() - 1).min()
        spy_dd_crisis = (spy_c / spy_c.cummax() - 1).min()

        s_total = (s_cum.iloc[-1] - 1) * 100
        b_total = (b_cum.iloc[-1] - 1) * 100
        spy_total = (spy_c.iloc[-1] - 1) * 100

        # Mean VIX during crisis
        vix_mean = data["vix"].loc[mask].mean()
        vix_max = data["vix"].loc[mask].max()

        # Mean leverage during crisis
        vix_cond_lev = np.clip(1.5 - 0.5 * (data["vix"].loc[mask] - 15) / 10, 1.0, 1.5)
        mean_lev = vix_cond_lev.mean()

        print(f"\n  {crisis_name} ({start} to {end}):")
        print(f"    VIX: mean={vix_mean:.1f}, max={vix_max:.1f}")
        print(f"    Mean leverage: {mean_lev:.3f}x")
        print(f"    Strategy: MDD={s_dd*100:.2f}%, Total={s_total:+.1f}%")
        print(f"    Base VT:  MDD={b_dd*100:.2f}%, Total={b_total:+.1f}%")
        print(f"    SPY:      MDD={spy_dd_crisis*100:.2f}%, Total={spy_total:+.1f}%")
        print(f"    DD Diff (Strat-Base): {(s_dd-b_dd)*100:+.2f}pp")

        crisis_results[crisis_name] = {
            "period": f"{start} to {end}",
            "vix_mean": round(vix_mean, 1),
            "vix_max": round(vix_max, 1),
            "mean_leverage": round(mean_lev, 3),
            "strat_mdd": round(s_dd * 100, 2),
            "base_mdd": round(b_dd * 100, 2),
            "spy_mdd": round(spy_dd_crisis * 100, 2),
            "strat_total_return": round(s_total, 1),
            "base_total_return": round(b_total, 1),
            "spy_total_return": round(spy_total, 1),
            "dd_diff_pp": round((s_dd - b_dd) * 100, 2),
        }

    # Underwater duration analysis
    strat_underwater = strat_dd < -0.001
    base_underwater = base_dd < -0.001

    def max_underwater_days(underwater_series):
        groups = (~underwater_series).cumsum()
        durations = underwater_series.groupby(groups).sum()
        return int(durations.max()) if len(durations) > 0 else 0

    strat_max_uw = max_underwater_days(strat_underwater)
    base_max_uw = max_underwater_days(base_underwater)

    print(f"\n  UNDERWATER DURATION:")
    print(f"    Strategy max underwater: {strat_max_uw} days")
    print(f"    Base max underwater:     {base_max_uw} days")

    return {
        "full_sample": {
            "strat_mdd": round(strat_dd.min() * 100, 2),
            "base_mdd": round(base_dd.min() * 100, 2),
            "spy_mdd": round(spy_dd.min() * 100, 2),
        },
        "crises": crisis_results,
        "underwater": {
            "strat_max_days": strat_max_uw,
            "base_max_days": base_max_uw,
        },
    }


# ═══════════════════════════════════════════════════════════════
# TEST 7: Bootstrap Confidence Intervals
# ═══════════════════════════════════════════════════════════════
def test_bootstrap(strat_ret, base_ret):
    """Bootstrap confidence intervals for Sharpe difference."""
    print("\n" + "=" * 70)
    print(f"TEST 7: BOOTSTRAP ({N_BOOTSTRAP} replications)")
    print("=" * 70)

    idx = strat_ret.index.intersection(base_ret.index)
    s = strat_ret.loc[idx].values
    b = base_ret.loc[idx].values
    n = len(s)

    rf_daily = FALLBACK_RF / 252
    es = s - rf_daily
    eb = b - rf_daily

    # Observed Sharpe difference
    obs_sr_s = np.mean(es) / np.std(es, ddof=1) * np.sqrt(252)
    obs_sr_b = np.mean(eb) / np.std(eb, ddof=1) * np.sqrt(252)
    obs_diff = obs_sr_s - obs_sr_b
    print(f"  Observed Sharpe diff: {obs_diff:.4f}")

    # Block bootstrap (block size = 21 trading days ≈ 1 month)
    block_size = 21
    n_blocks = n // block_size + 1

    sharpe_diffs = np.zeros(N_BOOTSTRAP)
    strat_wins = 0

    for i in range(N_BOOTSTRAP):
        # Block bootstrap: sample blocks with replacement
        block_starts = np.random.randint(0, n - block_size + 1, n_blocks)
        indices = np.concatenate([np.arange(start, min(start + block_size, n))
                                  for start in block_starts])[:n]

        boot_s = es[indices]
        boot_b = eb[indices]

        sr_s = np.mean(boot_s) / np.std(boot_s, ddof=1) * np.sqrt(252)
        sr_b = np.mean(boot_b) / np.std(boot_b, ddof=1) * np.sqrt(252)
        sharpe_diffs[i] = sr_s - sr_b

        if sr_s > sr_b:
            strat_wins += 1

    ci_025 = np.percentile(sharpe_diffs, 2.5)
    ci_975 = np.percentile(sharpe_diffs, 97.5)
    ci_05 = np.percentile(sharpe_diffs, 5)
    ci_95 = np.percentile(sharpe_diffs, 95)
    p_win = strat_wins / N_BOOTSTRAP

    print(f"  95% CI: [{ci_025:.4f}, {ci_975:.4f}]")
    print(f"  90% CI: [{ci_05:.4f}, {ci_95:.4f}]")
    print(f"  Mean boot diff: {np.mean(sharpe_diffs):.4f}")
    print(f"  Std boot diff:  {np.std(sharpe_diffs):.4f}")
    print(f"  P(strategy > benchmark): {p_win:.4f} ({p_win*100:.1f}%)")
    print(f"  CI excludes zero: {'YES ✓' if ci_025 > 0 else 'NO ✗'}")

    # Also bootstrap CAGR difference
    cagr_diffs = np.zeros(N_BOOTSTRAP)
    for i in range(N_BOOTSTRAP):
        block_starts = np.random.randint(0, n - block_size + 1, n_blocks)
        indices = np.concatenate([np.arange(start, min(start + block_size, n))
                                  for start in block_starts])[:n]
        boot_s_cum = np.prod(1 + s[indices])
        boot_b_cum = np.prod(1 + b[indices])
        years = n / 252
        cagr_s = boot_s_cum ** (1 / years) - 1
        cagr_b = boot_b_cum ** (1 / years) - 1
        cagr_diffs[i] = (cagr_s - cagr_b) * 100

    cagr_ci_025 = np.percentile(cagr_diffs, 2.5)
    cagr_ci_975 = np.percentile(cagr_diffs, 97.5)

    print(f"\n  CAGR Diff Bootstrap:")
    print(f"    Mean: {np.mean(cagr_diffs):.2f}%")
    print(f"    95% CI: [{cagr_ci_025:.2f}%, {cagr_ci_975:.2f}%]")

    return {
        "observed_sharpe_diff": round(obs_diff, 4),
        "boot_mean_diff": round(np.mean(sharpe_diffs), 4),
        "boot_std_diff": round(np.std(sharpe_diffs), 4),
        "ci_95": [round(ci_025, 4), round(ci_975, 4)],
        "ci_90": [round(ci_05, 4), round(ci_95, 4)],
        "p_strat_wins": round(p_win, 4),
        "ci_excludes_zero": ci_025 > 0,
        "block_size": block_size,
        "n_bootstrap": N_BOOTSTRAP,
        "cagr_diff_boot": {
            "mean_pct": round(np.mean(cagr_diffs), 2),
            "ci_95_pct": [round(cagr_ci_025, 2), round(cagr_ci_975, 2)],
        },
    }


# ═══════════════════════════════════════════════════════════════
# TEST 8: Taiwan Test (0050.TW with 8.63/VIX)
# ═══════════════════════════════════════════════════════════════
def test_taiwan(data_us):
    """Test VIX-Conditional Leverage on 0050.TW."""
    print("\n" + "=" * 70)
    print("TEST 8: TAIWAN TEST (0050.TW)")
    print("=" * 70)

    try:
        tw = yf.download("0050.TW", start="2005-01-01", end=END, progress=False)
        if isinstance(tw.columns, pd.MultiIndex):
            tw.columns = tw.columns.get_level_values(0)
        tw_ret = tw["Close"].pct_change().dropna()
        tw_ret.name = "tw_ret"
    except Exception as e:
        print(f"  ERROR downloading 0050.TW: {e}")
        return {"error": str(e)}

    # Use US VIX (1-day lag for Taiwan — US market leads)
    vix = data_us["vix"].shift(1).reindex(tw_ret.index).ffill().dropna()
    common = tw_ret.index.intersection(vix.index)
    tw_ret = tw_ret.loc[common]
    vix = vix.loc[common]

    if len(tw_ret) < 252:
        print(f"  Insufficient data: {len(tw_ret)} days")
        return {"error": "insufficient_data", "n_days": len(tw_ret)}

    print(f"  Data: {tw_ret.index[0].date()} to {tw_ret.index[-1].date()}, N={len(tw_ret)}")

    # Base: 8.63/VIX weight for Taiwan (from K461)
    tw_threshold = 8.63
    tw_weight = np.minimum(tw_threshold / vix, 1.0)
    rf_daily = 0.01 / 252  # ~1% Taiwan risk-free

    # Base Taiwan VT: just tw_weight * 0050.TW + (1-tw_weight) * rf
    # (Simplified: no GLD equivalent for TW, just equity VT)
    base_tw_ret = tw_weight * tw_ret + (1 - tw_weight) * rf_daily

    # VIX-Conditional Leverage for Taiwan
    # Same idea: 1.5x when VIX<15, 1.0x when VIX>25
    vix_cond_lev = np.clip(1.5 - 0.5 * (vix - 15) / 10, 1.0, 1.5)
    effective_lev = tw_weight * vix_cond_lev
    strat_tw_ret = effective_lev * tw_ret + (1 - effective_lev) * rf_daily
    borrow_cost = np.maximum(effective_lev - 1, 0) * (rf_daily + BORROWING_SPREAD / 252)
    strat_tw_ret = strat_tw_ret - borrow_cost

    # Also test with Taiwan-specific thresholds (lower VIX sensitivity)
    # TW amplification ~4.6x, so low-VIX threshold might be different
    vix_cond_lev_tw = np.clip(1.5 - 0.5 * (vix - 12) / 8, 1.0, 1.5)
    effective_lev_tw = tw_weight * vix_cond_lev_tw
    strat_tw_alt = effective_lev_tw * tw_ret + (1 - effective_lev_tw) * rf_daily
    borrow_cost_alt = np.maximum(effective_lev_tw - 1, 0) * (rf_daily + BORROWING_SPREAD / 252)
    strat_tw_alt = strat_tw_alt - borrow_cost_alt

    # Buy & hold for comparison
    tw_bh_ret = tw_ret.copy()

    rf_series = pd.Series(rf_daily, index=tw_ret.index)

    base_m = compute_metrics(base_tw_ret, rf_series)
    strat_m = compute_metrics(strat_tw_ret, rf_series)
    strat_alt_m = compute_metrics(strat_tw_alt, rf_series)
    bh_m = compute_metrics(tw_bh_ret, rf_series)

    results = {}
    for name, m in [("base_8.63_VT", base_m), ("VIX_cond_lev_15_25", strat_m),
                     ("VIX_cond_lev_12_20_TW", strat_alt_m), ("buy_hold", bh_m)]:
        if m:
            print(f"\n  {name}:")
            print(f"    Sharpe={m['sharpe']:.3f}, CAGR={m['cagr']:.1f}%, MDD={m['mdd']:.1f}%")
            results[name] = m

    if strat_m and base_m:
        diff = strat_m["sharpe"] - base_m["sharpe"]
        print(f"\n  Sharpe improvement: {diff:+.3f}")
        print(f"  {'POSITIVE for Taiwan' if diff > 0 else 'NOT POSITIVE for Taiwan'}")
        results["sharpe_diff_vs_base"] = round(diff, 3)

    return results


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    start_time = datetime.now(timezone.utc)
    print("=" * 70)
    print("K551: VIX-CONDITIONAL LEVERAGE — DEEP VALIDATION")
    print("=" * 70)

    # Download data
    data = download_data()

    # Compute base and strategy returns
    base_ret = compute_base_returns(data)
    strat_ret, vix_cond_lev, effective_lev = compute_vix_conditional_returns(data, 15, 25, 1.5)

    # Full-sample metrics
    print("\n" + "=" * 70)
    print("FULL SAMPLE METRICS")
    print("=" * 70)
    base_m = compute_metrics(base_ret, data["rf_daily"])
    strat_m = compute_metrics(strat_ret, data["rf_daily"])
    spy_m = compute_metrics(data["spy_ret"], data["rf_daily"])

    for name, m in [("Base 50/50 VT", base_m), ("VIX-Cond Lev", strat_m), ("SPY B&H", spy_m)]:
        if m:
            print(f"  {name:20s}: Sharpe={m['sharpe']:.3f}, CAGR={m['cagr']:.1f}%, "
                  f"MDD={m['mdd']:.1f}%, Calmar={m['calmar']:.3f}, "
                  f"Sortino={m['sortino']:.3f}")

    # Leverage statistics
    print(f"\n  Leverage stats:")
    print(f"    Mean: {vix_cond_lev.mean():.3f}x")
    print(f"    % days at 1.5x: {(vix_cond_lev >= 1.499).mean()*100:.1f}%")
    print(f"    % days at 1.0x: {(vix_cond_lev <= 1.001).mean()*100:.1f}%")
    print(f"    % days between: {((vix_cond_lev > 1.001) & (vix_cond_lev < 1.499)).mean()*100:.1f}%")

    # ═══════════════════════════ RUN ALL TESTS ═══════════════════════════
    all_results = {
        "experiment_id": "K551",
        "title": "K548 VIX-Conditional Leverage — Deep Validation",
        "timestamp": start_time.isoformat(),
        "data_source": "yfinance (SPY, GLD, ^VIX, ^IRX, 0050.TW)",
        "data_period": f"{data.index[0].date()} to {data.index[-1].date()}",
        "n_days": len(data),
        "strategy": {
            "name": "VIX-Conditional Leverage on 50/50 SPY/GLD VT",
            "rule": "Leverage = 1.5x when VIX<15, 1.0x when VIX>25, linear interp between",
            "base": "50/50 SPY/GLD with 12/VIX weighting (cap=1.0)",
            "borrowing_cost": "^IRX + 50bps spread",
        },
        "full_sample": {
            "base": base_m,
            "strategy": strat_m,
            "spy_bh": spy_m,
            "leverage_stats": {
                "mean": round(vix_cond_lev.mean(), 3),
                "pct_at_max": round((vix_cond_lev >= 1.499).mean() * 100, 1),
                "pct_at_min": round((vix_cond_lev <= 1.001).mean() * 100, 1),
                "pct_between": round(((vix_cond_lev > 1.001) & (vix_cond_lev < 1.499)).mean() * 100, 1),
            },
        },
    }

    # Test 1: Harvey DM test
    all_results["test1_harvey"] = test_harvey_dm(strat_ret, base_ret)

    # Test 2: Cross-OOS
    all_results["test2_cross_oos"] = test_cross_oos(data, strat_ret, base_ret)

    # Test 3: Sensitivity
    all_results["test3_sensitivity"] = test_sensitivity(data, base_ret)

    # Test 4: Transaction costs
    all_results["test4_tx_costs"] = test_transaction_costs(data, base_ret)

    # Test 5: Borrowing costs
    all_results["test5_borrowing_costs"] = test_borrowing_costs(data, base_ret)

    # Test 6: Drawdowns
    all_results["test6_drawdowns"] = test_drawdowns(data, strat_ret, base_ret)

    # Test 7: Bootstrap
    all_results["test7_bootstrap"] = test_bootstrap(strat_ret, base_ret)

    # Test 8: Taiwan
    all_results["test8_taiwan"] = test_taiwan(data)

    # ═══════════════════════════ VERDICT ═══════════════════════════
    print("\n" + "=" * 70)
    print("FINAL VERDICT")
    print("=" * 70)

    t1 = all_results["test1_harvey"]
    t2 = all_results["test2_cross_oos"]
    t3 = all_results["test3_sensitivity"]
    t4 = all_results["test4_tx_costs"]
    t5 = all_results["test5_borrowing_costs"]
    t7 = all_results["test7_bootstrap"]

    checks = {
        "harvey_dm_t3": t1["dm_return_diff"]["pass_harvey_3"],
        "harvey_jkm_t3": t1["jkm_sharpe_diff"]["pass_harvey_3"],
        "cross_oos_primary_4_of_5": t2["primary"]["wins"] >= 4,
        "cross_oos_alt_4_of_6": t2["alternative"]["wins"] >= 4,
        "sensitivity_safe_zone_gt50": t3["safe_zone_ratio"] > 50,
        "breakeven_tx_gt_10bps": t4["breakeven_tx_bps"] > 10,
        "survives_6pct_borrow": t5["results"].get("6pct", {}).get("beats_base", False),
        "bootstrap_ci_excludes_zero": t7["ci_excludes_zero"],
        "bootstrap_p_win_gt_80": t7["p_strat_wins"] > 0.80,
    }

    all_pass = True
    for check_name, passed in checks.items():
        status = "PASS ✓" if passed else "FAIL ✗"
        if not passed:
            all_pass = False
        print(f"  [{status}] {check_name}")

    n_pass = sum(checks.values())
    n_total = len(checks)
    print(f"\n  OVERALL: {n_pass}/{n_total} checks passed")

    if all_pass:
        verdict = "ALL CHECKS PASS — Strategy validated for listing consideration"
    elif n_pass >= 7:
        verdict = f"MOSTLY PASS ({n_pass}/{n_total}) — Review failed checks before listing"
    else:
        verdict = f"INSUFFICIENT ({n_pass}/{n_total}) — Not ready for listing"

    print(f"  VERDICT: {verdict}")

    all_results["verdict"] = {
        "checks": {k: v for k, v in checks.items()},
        "n_pass": n_pass,
        "n_total": n_total,
        "overall": verdict,
        "listable": all_pass or n_pass >= 7,
    }

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    all_results["elapsed_seconds"] = round(elapsed, 1)
    print(f"\n  Elapsed: {elapsed:.1f}s")

    # Save results
    out_path = Path(__file__).parent / "k551_k548_validation_results.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return all_results


if __name__ == "__main__":
    main()
