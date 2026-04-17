#!/usr/bin/env python3
"""
K558: K553 Taiwan Hybrid Leverage — Deep Validation for Listing

K553 found Hybrid (RV22_TW + VIX Percentile) leverage for Taiwan achieves:
  Harvey t=6.30, 9/9 OOS, 100% bootstrap, Sharpe +0.248

This experiment performs the SAME 8-point deep validation as K551 (US),
using a BINARY leverage rule (simpler, more implementable):
  When RV22_TW < 20% AND VIX_percentile < 0.3 → leverage 1.5x
  Otherwise → 1.0x (no leverage)

Validation Checklist (8 items, same as K551):
  1. Harvey (2016) t>3.0 with Newey-West HAC
  2. Cross-OOS: TWO different period splits (5+ periods each)
  3. Sensitivity Analysis:
     - RV22 threshold: [15%, 18%, 20%, 22%, 25%]
     - VIX percentile threshold: [0.2, 0.25, 0.3, 0.35, 0.4]
     - Leverage multiplier: [1.2x, 1.3x, 1.5x, 1.8x]
  4. Transaction costs: 0, 5bp, 10bp, 20bp, 50bp
  5. Borrowing costs: 0%, 2%, 4%, 6%
  6. Drawdown analysis: worst episodes
  7. Bootstrap: 5000 reps, 95% CI, P(win)
  8. Robustness: test with 0056.TW (high-dividend ETF) if available

References:
  K553: Taiwan Hybrid Leverage discovery (Variant E best)
  K548: Original VIX-Conditional Leverage (US)
  K551: US deep validation (11/11 OOS, Harvey t=7.90)
  K461: Taiwan VT calibration (8.63/VIX)
  Moreira & Muir (2017) "Volatility-Managed Portfolios" JF
  Harvey et al. (2016) t>3.0 threshold, RFS

Author: VolPred Research System (Claude)
Data: yfinance (0050.TW, 0056.TW, ^VIX), 2005-2026
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
START = "2005-01-01"
END = "2026-03-27"
TW_RF = 0.01  # Taiwan risk-free ~1%
N_BOOTSTRAP = 5000
np.random.seed(42)

# Default strategy parameters (from K553 Variant E best)
DEFAULT_RV_THRESH = 20.0   # RV22_TW < 20% → calm
DEFAULT_VIX_PCTILE = 0.30  # VIX percentile < 0.3 → calm
DEFAULT_LEVERAGE = 1.5     # Leverage when both conditions met

# ─── Cross-OOS Period Splits ───
# Split A: 5 periods, ~3.4 years each (from K553)
OOS_SPLIT_A = [
    ("2009-06-01", "2012-12-31"),
    ("2013-01-01", "2016-05-31"),
    ("2016-06-01", "2019-11-30"),
    ("2019-12-01", "2023-05-31"),
    ("2023-06-01", "2026-03-27"),
]

# Split B: 6 periods, ~2.5-3 years each (different boundaries)
OOS_SPLIT_B = [
    ("2009-06-01", "2011-12-31"),
    ("2012-01-01", "2014-06-30"),
    ("2014-07-01", "2016-12-31"),
    ("2017-01-01", "2019-06-30"),
    ("2019-07-01", "2022-06-30"),
    ("2022-07-01", "2026-03-27"),
]

# Split C: 7 periods, ~2 years each (stress test boundaries)
OOS_SPLIT_C = [
    ("2010-01-01", "2012-03-31"),
    ("2012-04-01", "2014-06-30"),
    ("2014-07-01", "2016-09-30"),
    ("2016-10-01", "2018-12-31"),
    ("2019-01-01", "2021-03-31"),
    ("2021-04-01", "2023-06-30"),
    ("2023-07-01", "2026-03-27"),
]

# Crisis periods for Taiwan
CRISIS_PERIODS = {
    "EU_Crisis_2011": ("2011-07-01", "2012-06-30"),
    "TW_2015_Crash": ("2015-04-01", "2016-01-31"),
    "COVID_2020": ("2020-01-15", "2020-06-30"),
    "2022_Bear": ("2022-01-01", "2022-12-31"),
}


# ═══════════════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════════════
def download_data(ticker="0050.TW"):
    """Download Taiwan ETF and VIX data."""
    print("=" * 70)
    print(f"K558: DOWNLOADING DATA — {ticker}")
    print("=" * 70)

    tw = yf.download(ticker, start=START, end=END, progress=False)
    vix = yf.download("^VIX", start=START, end=END, progress=False)

    for df in [tw, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    data = pd.DataFrame(index=tw.index)
    data["tw_close"] = tw["Close"]
    data["vix_raw"] = vix["Close"].reindex(tw.index)

    # VIX with 1-day lag (US market closes T-1 relative to Taiwan T)
    data["vix"] = data["vix_raw"].shift(1)
    data = data.ffill().dropna()

    data["tw_ret"] = data["tw_close"].pct_change()
    data = data.dropna()
    data = data.iloc[1:]

    # 8.63/VIX weight for Taiwan (from K461)
    data["vt_weight"] = np.minimum(8.63 / data["vix"], 1.0)
    data["rf_daily"] = TW_RF / 252

    # Realized vol (22-day rolling) for Taiwan ETF
    data["rv22_tw"] = data["tw_ret"].rolling(22).std() * np.sqrt(252) * 100

    # Rolling VIX percentile (252-day window)
    data["vix_pctile"] = data["vix"].rolling(252).apply(
        lambda x: stats.percentileofscore(x, x.iloc[-1]) / 100, raw=False
    )

    data = data.dropna()
    print(f"  Data: {data.index[0].date()} to {data.index[-1].date()}, N={len(data)}")

    # ─── Diagnostics ───
    print(f"\n  === DATA DIAGNOSTICS ===")
    ret = data["tw_ret"]
    print(f"  {ticker} return: mean={ret.mean()*252*100:.1f}%/yr, "
          f"vol={ret.std()*np.sqrt(252)*100:.1f}%/yr, "
          f"skew={ret.skew():.2f}, kurt={ret.kurtosis():.2f}")
    print(f"  VIX (lagged): mean={data['vix'].mean():.1f}, "
          f"median={data['vix'].median():.1f}, "
          f"std={data['vix'].std():.1f}")
    print(f"  RV22_TW: mean={data['rv22_tw'].mean():.1f}%, "
          f"median={data['rv22_tw'].median():.1f}%, "
          f"std={data['rv22_tw'].std():.1f}%")
    print(f"  VIX percentile: mean={data['vix_pctile'].mean():.2f}, "
          f"median={data['vix_pctile'].median():.2f}")

    # Distribution of conditions
    for rv_t in [15, 18, 20, 22, 25]:
        pct = (data["rv22_tw"] < rv_t).mean() * 100
        print(f"  RV22_TW < {rv_t}%: {pct:.1f}% of days")
    for vp in [0.2, 0.25, 0.3, 0.35, 0.4]:
        pct = (data["vix_pctile"] < vp).mean() * 100
        print(f"  VIX pctile < {vp}: {pct:.1f}% of days")

    # Both conditions (default)
    both = ((data["rv22_tw"] < DEFAULT_RV_THRESH) &
            (data["vix_pctile"] < DEFAULT_VIX_PCTILE))
    print(f"\n  BOTH conditions met (RV<{DEFAULT_RV_THRESH} AND pctile<{DEFAULT_VIX_PCTILE}): "
          f"{both.mean()*100:.1f}% of days ({both.sum()} days)")

    return data


# ═══════════════════════════════════════════════════════════════
# STRATEGY LOGIC
# ═══════════════════════════════════════════════════════════════
def compute_base_returns(data):
    """Base Taiwan VT: 8.63/VIX * 0050.TW + (1 - 8.63/VIX) * rf."""
    w = data["vt_weight"]
    return w * data["tw_ret"] + (1 - w) * data["rf_daily"]


def compute_hybrid_leverage_returns(data, rv_thresh=DEFAULT_RV_THRESH,
                                     vix_pctile_thresh=DEFAULT_VIX_PCTILE,
                                     leverage=DEFAULT_LEVERAGE,
                                     borrow_rate_annual=0.06,
                                     tx_cost_bp=0):
    """
    Binary hybrid leverage:
      If RV22_TW < rv_thresh AND VIX_percentile < vix_pctile_thresh → lev x
      Else → 1.0x

    Returns: (net_returns_series, leverage_series, n_trades)
    """
    # Signal: both conditions must be true
    calm = ((data["rv22_tw"] < rv_thresh) &
            (data["vix_pctile"] < vix_pctile_thresh))

    lev = pd.Series(1.0, index=data.index)
    lev[calm] = leverage

    w = data["vt_weight"]
    effective_lev = w * lev
    gross_ret = effective_lev * data["tw_ret"] + (1 - effective_lev) * data["rf_daily"]

    # Borrowing cost on leveraged portion
    borrow_daily = borrow_rate_annual / 252
    borrow_cost = np.maximum(effective_lev - 1, 0) * borrow_daily
    net_ret = gross_ret - borrow_cost

    # Transaction costs (on leverage changes)
    lev_changes = lev.diff().abs().fillna(0)
    n_trades = (lev_changes > 0).sum()
    tx_cost = lev_changes * (tx_cost_bp / 10000)
    net_ret = net_ret - tx_cost

    return net_ret, lev, n_trades


def compute_metrics(returns_series, label=""):
    """Standard performance metrics."""
    r = returns_series.dropna()
    if len(r) < 63:
        return None

    cum = (1 + r).cumprod()
    total_return = cum.iloc[-1] - 1
    years = len(r) / 252
    cagr = (1 + total_return) ** (1 / max(years, 0.01)) - 1
    ann_vol = r.std() * np.sqrt(252)

    rf_daily = TW_RF / 252
    excess = r - rf_daily
    sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else 0

    running_max = cum.cummax()
    drawdown = cum / running_max - 1
    mdd = drawdown.min()
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    downside = excess[excess < 0]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-8
    sortino = excess.mean() * 252 / downside_std

    return {
        "cagr": round(cagr * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "total_return_pct": round(total_return * 100, 2),
        "years": round(years, 1),
        "n_days": len(r),
    }


# ═══════════════════════════════════════════════════════════════
# TEST 1: HARVEY (2016) DM TEST WITH NEWEY-WEST HAC
# ═══════════════════════════════════════════════════════════════
def dm_test_harvey(base_ret, strat_ret):
    """Diebold-Mariano test with Newey-West HAC."""
    d = (strat_ret - base_ret).dropna()
    n = len(d)
    d_mean = d.mean()

    max_lag = int(np.ceil(4 * (n / 100) ** (2/9)))
    gamma = np.zeros(max_lag + 1)
    for k in range(max_lag + 1):
        gamma[k] = np.mean((d.values[k:] - d_mean) * (d.values[:n-k] - d_mean))

    nw_var = gamma[0]
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        nw_var += 2 * w * gamma[k]

    se = np.sqrt(nw_var / n)
    t_stat = d_mean / se if se > 0 else 0
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))

    return {
        "t_stat": round(t_stat, 4),
        "p_value": round(p_value, 6),
        "harvey_pass": abs(t_stat) > 3.0,
        "n": n,
        "nw_lags": max_lag,
        "mean_daily_diff": round(d_mean * 10000, 4),  # in bps
        "se": round(se * 10000, 4),
    }


# ═══════════════════════════════════════════════════════════════
# TEST 2: CROSS-OOS
# ═══════════════════════════════════════════════════════════════
def cross_oos_test(data, oos_periods, split_name,
                   rv_thresh=DEFAULT_RV_THRESH,
                   vix_pctile_thresh=DEFAULT_VIX_PCTILE,
                   leverage=DEFAULT_LEVERAGE):
    """Run cross-OOS validation."""
    results = []
    for start, end in oos_periods:
        mask = (data.index >= start) & (data.index <= end)
        sub = data[mask]
        if len(sub) < 63:
            continue

        base_ret = compute_base_returns(sub)
        strat_ret, lev, n_trades = compute_hybrid_leverage_returns(
            sub, rv_thresh, vix_pctile_thresh, leverage
        )

        base_m = compute_metrics(base_ret)
        strat_m = compute_metrics(strat_ret)

        if base_m and strat_m:
            diff = strat_m["sharpe"] - base_m["sharpe"]
            results.append({
                "period": f"{start} to {end}",
                "n_days": len(sub),
                "base_sharpe": base_m["sharpe"],
                "strat_sharpe": strat_m["sharpe"],
                "sharpe_diff": round(diff, 3),
                "win": diff > 0,
                "base_mdd": base_m["mdd"],
                "strat_mdd": strat_m["mdd"],
                "n_trades": int(n_trades),
                "pct_leveraged": round((lev > 1.0).mean() * 100, 1),
            })

    n_wins = sum(1 for r in results if r["win"])
    n_total = len(results)

    return {
        "split_name": split_name,
        "n_wins": n_wins,
        "n_total": n_total,
        "win_rate": round(n_wins / n_total * 100, 1) if n_total > 0 else 0,
        "periods": results,
    }


# ═══════════════════════════════════════════════════════════════
# TEST 3: SENSITIVITY ANALYSIS
# ═══════════════════════════════════════════════════════════════
def sensitivity_analysis(data):
    """Grid sweep over RV threshold, VIX percentile, and leverage."""
    print("\n" + "=" * 70)
    print("TEST 3: SENSITIVITY ANALYSIS")
    print("=" * 70)

    base_ret = compute_base_returns(data)
    base_m = compute_metrics(base_ret)
    base_sharpe = base_m["sharpe"]

    rv_thresholds = [15, 18, 20, 22, 25]
    vix_pctile_thresholds = [0.20, 0.25, 0.30, 0.35, 0.40]
    leverage_levels = [1.2, 1.3, 1.5, 1.8]

    all_results = []
    for rv_t in rv_thresholds:
        for vp in vix_pctile_thresholds:
            for lev in leverage_levels:
                strat_ret, lev_s, n_tr = compute_hybrid_leverage_returns(
                    data, rv_t, vp, lev
                )
                m = compute_metrics(strat_ret)
                if m:
                    diff = m["sharpe"] - base_sharpe
                    pct_lev = (lev_s > 1.0).mean() * 100
                    all_results.append({
                        "rv_thresh": rv_t,
                        "vix_pctile_thresh": vp,
                        "leverage": lev,
                        "sharpe": m["sharpe"],
                        "sharpe_diff": round(diff, 3),
                        "cagr": m["cagr"],
                        "mdd": m["mdd"],
                        "calmar": m["calmar"],
                        "sortino": m["sortino"],
                        "pct_days_leveraged": round(pct_lev, 1),
                        "n_trades": int(n_tr),
                    })

    # Sort by Sharpe
    all_results.sort(key=lambda x: x["sharpe"], reverse=True)

    # Summary stats
    n_positive = sum(1 for r in all_results if r["sharpe_diff"] > 0)
    n_total = len(all_results)
    print(f"  Tested {n_total} configurations")
    print(f"  Positive Sharpe diff: {n_positive}/{n_total} "
          f"({n_positive/n_total*100:.1f}%)")
    print(f"\n  Top 10 configs:")
    for r in all_results[:10]:
        print(f"    RV<{r['rv_thresh']}% VIXp<{r['vix_pctile_thresh']} "
              f"lev={r['leverage']}: Sharpe={r['sharpe']:.3f} "
              f"({r['sharpe_diff']:+.3f}), CAGR={r['cagr']:.1f}%, "
              f"MDD={r['mdd']:.1f}%, days_lev={r['pct_days_leveraged']:.0f}%")

    print(f"\n  Bottom 5 configs:")
    for r in all_results[-5:]:
        print(f"    RV<{r['rv_thresh']}% VIXp<{r['vix_pctile_thresh']} "
              f"lev={r['leverage']}: Sharpe={r['sharpe']:.3f} "
              f"({r['sharpe_diff']:+.3f}), MDD={r['mdd']:.1f}%")

    # "Safe zone" — configs where Sharpe diff > 0.05
    safe_configs = [r for r in all_results if r["sharpe_diff"] > 0.05]
    print(f"\n  Safe zone (Sharpe diff > 0.05): {len(safe_configs)}/{n_total} "
          f"({len(safe_configs)/n_total*100:.1f}%)")

    # Parameter stability: for each parameter, show average Sharpe diff
    print(f"\n  --- Parameter Stability ---")
    for param_name, values in [("rv_thresh", rv_thresholds),
                                ("vix_pctile_thresh", vix_pctile_thresholds),
                                ("leverage", leverage_levels)]:
        print(f"  {param_name}:")
        for val in values:
            subset = [r for r in all_results if r[param_name] == val]
            avg_diff = np.mean([r["sharpe_diff"] for r in subset])
            pct_pos = sum(1 for r in subset if r["sharpe_diff"] > 0) / len(subset) * 100
            print(f"    {val}: avg Sharpe diff={avg_diff:+.3f}, "
                  f"pct positive={pct_pos:.0f}%")

    return {
        "n_configs": n_total,
        "n_positive": n_positive,
        "positive_rate": round(n_positive / n_total * 100, 1),
        "n_safe_zone": len(safe_configs),
        "safe_zone_rate": round(len(safe_configs) / n_total * 100, 1),
        "top10": all_results[:10],
        "bottom5": all_results[-5:],
        "all_results": all_results,
        "base_sharpe": base_sharpe,
        "parameter_stability": {
            "rv_thresh": {str(v): round(np.mean([r["sharpe_diff"]
                          for r in all_results if r["rv_thresh"] == v]), 4)
                          for v in rv_thresholds},
            "vix_pctile_thresh": {str(v): round(np.mean([r["sharpe_diff"]
                                  for r in all_results if r["vix_pctile_thresh"] == v]), 4)
                                  for v in vix_pctile_thresholds},
            "leverage": {str(v): round(np.mean([r["sharpe_diff"]
                         for r in all_results if r["leverage"] == v]), 4)
                         for v in leverage_levels},
        },
    }


# ═══════════════════════════════════════════════════════════════
# TEST 4: TRANSACTION COST SENSITIVITY
# ═══════════════════════════════════════════════════════════════
def transaction_cost_analysis(data):
    """Test impact of different transaction cost levels."""
    print("\n" + "=" * 70)
    print("TEST 4: TRANSACTION COST SENSITIVITY")
    print("=" * 70)

    base_ret = compute_base_returns(data)
    base_m = compute_metrics(base_ret)
    base_sharpe = base_m["sharpe"]

    tx_levels = [0, 5, 10, 20, 50, 100]  # basis points
    results = []

    for tx_bp in tx_levels:
        strat_ret, lev, n_trades = compute_hybrid_leverage_returns(
            data, tx_cost_bp=tx_bp
        )
        m = compute_metrics(strat_ret)
        diff = m["sharpe"] - base_sharpe
        results.append({
            "tx_cost_bp": tx_bp,
            "sharpe": m["sharpe"],
            "sharpe_diff": round(diff, 3),
            "cagr": m["cagr"],
            "mdd": m["mdd"],
            "n_trades": int(n_trades),
            "still_positive": diff > 0,
        })
        status = "PASS" if diff > 0 else "FAIL"
        print(f"  TX={tx_bp:3d}bp: Sharpe={m['sharpe']:.3f} ({diff:+.3f}), "
              f"CAGR={m['cagr']:.1f}%, trades={n_trades}, [{status}]")

    # Find breakeven TX cost
    breakeven = None
    for i in range(len(results) - 1):
        if results[i]["sharpe_diff"] > 0 and results[i+1]["sharpe_diff"] <= 0:
            # Linear interpolation
            x1, y1 = results[i]["tx_cost_bp"], results[i]["sharpe_diff"]
            x2, y2 = results[i+1]["tx_cost_bp"], results[i+1]["sharpe_diff"]
            breakeven = x1 + (0 - y1) * (x2 - x1) / (y2 - y1)
            break
    if breakeven is None and all(r["sharpe_diff"] > 0 for r in results):
        breakeven = f"> {tx_levels[-1]}bp"

    print(f"\n  Breakeven TX cost: {breakeven}")

    return {
        "results": results,
        "breakeven_bp": breakeven,
        "realistic_5bp": next((r for r in results if r["tx_cost_bp"] == 5), None),
        "realistic_10bp": next((r for r in results if r["tx_cost_bp"] == 10), None),
    }


# ═══════════════════════════════════════════════════════════════
# TEST 5: BORROWING COST SENSITIVITY
# ═══════════════════════════════════════════════════════════════
def borrowing_cost_analysis(data):
    """Test impact of different borrowing rates."""
    print("\n" + "=" * 70)
    print("TEST 5: BORROWING COST SENSITIVITY")
    print("=" * 70)

    base_ret = compute_base_returns(data)
    base_m = compute_metrics(base_ret)
    base_sharpe = base_m["sharpe"]

    borrow_rates = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10]
    results = []

    for br in borrow_rates:
        strat_ret, lev, n_trades = compute_hybrid_leverage_returns(
            data, borrow_rate_annual=br
        )
        m = compute_metrics(strat_ret)
        diff = m["sharpe"] - base_sharpe
        results.append({
            "borrow_rate_pct": br * 100,
            "sharpe": m["sharpe"],
            "sharpe_diff": round(diff, 3),
            "cagr": m["cagr"],
            "mdd": m["mdd"],
            "still_positive": diff > 0,
        })
        status = "PASS" if diff > 0 else "FAIL"
        print(f"  Borrow={br*100:.0f}%: Sharpe={m['sharpe']:.3f} ({diff:+.3f}), "
              f"CAGR={m['cagr']:.1f}%, [{status}]")

    # Find breakeven borrow rate
    breakeven = None
    for i in range(len(results) - 1):
        if results[i]["sharpe_diff"] > 0 and results[i+1]["sharpe_diff"] <= 0:
            x1, y1 = results[i]["borrow_rate_pct"], results[i]["sharpe_diff"]
            x2, y2 = results[i+1]["borrow_rate_pct"], results[i+1]["sharpe_diff"]
            breakeven = round(x1 + (0 - y1) * (x2 - x1) / (y2 - y1), 1)
            break
    if breakeven is None and all(r["sharpe_diff"] > 0 for r in results):
        breakeven = f"> {borrow_rates[-1]*100:.0f}%"

    print(f"\n  Breakeven borrow rate: {breakeven}%")
    print(f"  Taiwan margin rate ~6%: "
          f"{'PASS' if any(r['borrow_rate_pct'] == 6 and r['still_positive'] for r in results) else 'FAIL'}")

    return {
        "results": results,
        "breakeven_pct": breakeven,
        "taiwan_6pct": next((r for r in results if r["borrow_rate_pct"] == 6), None),
    }


# ═══════════════════════════════════════════════════════════════
# TEST 6: DRAWDOWN ANALYSIS
# ═══════════════════════════════════════════════════════════════
def drawdown_analysis(data):
    """Analyze worst drawdown episodes."""
    print("\n" + "=" * 70)
    print("TEST 6: DRAWDOWN ANALYSIS")
    print("=" * 70)

    base_ret = compute_base_returns(data)
    strat_ret, lev, _ = compute_hybrid_leverage_returns(data)

    base_cum = (1 + base_ret).cumprod()
    strat_cum = (1 + strat_ret).cumprod()

    base_dd = base_cum / base_cum.cummax() - 1
    strat_dd = strat_cum / strat_cum.cummax() - 1

    # Worst drawdowns for strategy
    print(f"\n  Full period base MDD: {base_dd.min()*100:.1f}%")
    print(f"  Full period strat MDD: {strat_dd.min()*100:.1f}%")
    print(f"  MDD increase: {(strat_dd.min() - base_dd.min())*100:.1f}pp")

    # Crisis period analysis
    crisis_results = {}
    print(f"\n  --- Crisis Periods ---")
    for name, (start, end) in CRISIS_PERIODS.items():
        mask = (data.index >= start) & (data.index <= end)
        sub = data[mask]
        if len(sub) < 5:
            continue

        b_ret = compute_base_returns(sub)
        s_ret, l, _ = compute_hybrid_leverage_returns(sub)

        b_cum = (1 + b_ret).cumprod()
        s_cum = (1 + s_ret).cumprod()

        b_total = (b_cum.iloc[-1] - 1) * 100
        s_total = (s_cum.iloc[-1] - 1) * 100
        b_mdd = (b_cum / b_cum.cummax() - 1).min() * 100
        s_mdd = (s_cum / s_cum.cummax() - 1).min() * 100
        pct_lev = (l > 1.0).mean() * 100

        crisis_results[name] = {
            "base_return": round(b_total, 2),
            "strat_return": round(s_total, 2),
            "base_mdd": round(b_mdd, 2),
            "strat_mdd": round(s_mdd, 2),
            "pct_leveraged": round(pct_lev, 1),
            "n_days": len(sub),
        }
        # Did leverage hurt during crisis?
        hurt = s_mdd < b_mdd
        print(f"  {name}: base_ret={b_total:+.1f}%, strat_ret={s_total:+.1f}%, "
              f"base_MDD={b_mdd:.1f}%, strat_MDD={s_mdd:.1f}%, "
              f"leveraged={pct_lev:.0f}% {'⚠ HURT' if hurt else '✓ OK'}")

    # Top 5 worst drawdown episodes (for strategy)
    # Find drawdown episodes by finding peaks and troughs
    is_peak = (strat_cum == strat_cum.cummax())
    peaks = strat_cum[is_peak].index
    worst_episodes = []

    # Calculate drawdown at each point
    running_max = strat_cum.cummax()
    dd_pct = (strat_cum / running_max - 1) * 100
    worst_point = dd_pct.idxmin()
    worst_dd = dd_pct.min()

    # Find the peak before the worst point
    prev_peaks = peaks[peaks < worst_point]
    if len(prev_peaks) > 0:
        peak_date = prev_peaks[-1]
        worst_episodes.append({
            "peak_date": str(peak_date.date()),
            "trough_date": str(worst_point.date()),
            "drawdown_pct": round(worst_dd, 2),
            "duration_days": (worst_point - peak_date).days,
        })

    return {
        "full_period_base_mdd": round(base_dd.min() * 100, 2),
        "full_period_strat_mdd": round(strat_dd.min() * 100, 2),
        "mdd_increase_pp": round((strat_dd.min() - base_dd.min()) * 100, 2),
        "crisis_periods": crisis_results,
        "worst_drawdown": worst_episodes[0] if worst_episodes else None,
    }


# ═══════════════════════════════════════════════════════════════
# TEST 7: BOOTSTRAP
# ═══════════════════════════════════════════════════════════════
def bootstrap_test(data, n_boot=N_BOOTSTRAP):
    """Block bootstrap for Sharpe difference CI."""
    print("\n" + "=" * 70)
    print("TEST 7: BOOTSTRAP (5000 reps)")
    print("=" * 70)

    base_ret = compute_base_returns(data).values
    strat_ret, _, _ = compute_hybrid_leverage_returns(data)
    strat_ret = strat_ret.values
    n = len(base_ret)
    block_size = 22

    diffs = []
    rf_d = TW_RF / 252
    for _ in range(n_boot):
        n_blocks = int(np.ceil(n / block_size))
        starts = np.random.randint(0, n - block_size, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]

        b_boot = base_ret[indices]
        s_boot = strat_ret[indices]

        b_sharpe = ((b_boot.mean() - rf_d) / b_boot.std() * np.sqrt(252)
                    if b_boot.std() > 0 else 0)
        s_sharpe = ((s_boot.mean() - rf_d) / s_boot.std() * np.sqrt(252)
                    if s_boot.std() > 0 else 0)
        diffs.append(s_sharpe - b_sharpe)

    diffs = np.array(diffs)

    result = {
        "n_bootstrap": n_boot,
        "block_size": block_size,
        "mean_diff": round(np.mean(diffs), 4),
        "median_diff": round(np.median(diffs), 4),
        "std_diff": round(np.std(diffs), 4),
        "ci_2_5": round(np.percentile(diffs, 2.5), 4),
        "ci_97_5": round(np.percentile(diffs, 97.5), 4),
        "ci_5": round(np.percentile(diffs, 5), 4),
        "ci_95": round(np.percentile(diffs, 95), 4),
        "p_win": round((diffs > 0).mean() * 100, 1),
        "p_win_large": round((diffs > 0.05).mean() * 100, 1),
    }

    print(f"  Mean Sharpe diff: {result['mean_diff']:.4f}")
    print(f"  95% CI: [{result['ci_2_5']:.4f}, {result['ci_97_5']:.4f}]")
    print(f"  90% CI: [{result['ci_5']:.4f}, {result['ci_95']:.4f}]")
    print(f"  P(win): {result['p_win']:.1f}%")
    print(f"  P(win > 0.05): {result['p_win_large']:.1f}%")
    print(f"  CI excludes zero: {'YES' if result['ci_2_5'] > 0 else 'NO'}")

    return result


# ═══════════════════════════════════════════════════════════════
# TEST 8: ROBUSTNESS — 0056.TW
# ═══════════════════════════════════════════════════════════════
def robustness_0056(data_0050):
    """Test same strategy on 0056.TW (high-dividend ETF)."""
    print("\n" + "=" * 70)
    print("TEST 8: ROBUSTNESS — 0056.TW (High-Dividend ETF)")
    print("=" * 70)

    try:
        data_0056 = download_data("0056.TW")
    except Exception as e:
        print(f"  ⚠ Failed to download 0056.TW: {e}")
        return {"status": "SKIP", "reason": str(e)}

    if len(data_0056) < 252:
        print(f"  ⚠ Insufficient data for 0056.TW: {len(data_0056)} days")
        return {"status": "SKIP", "reason": f"Only {len(data_0056)} days"}

    base_ret = compute_base_returns(data_0056)
    strat_ret, lev, n_trades = compute_hybrid_leverage_returns(data_0056)

    base_m = compute_metrics(base_ret)
    strat_m = compute_metrics(strat_ret)

    if not base_m or not strat_m:
        return {"status": "SKIP", "reason": "Insufficient data for metrics"}

    diff = strat_m["sharpe"] - base_m["sharpe"]

    # Harvey DM test
    dm = dm_test_harvey(base_ret, strat_ret)

    # Bootstrap
    b_ret = base_ret.values
    s_ret = strat_ret.values
    n = len(b_ret)
    block_size = 22
    diffs_boot = []
    rf_d = TW_RF / 252
    for _ in range(N_BOOTSTRAP):
        n_blocks = int(np.ceil(n / block_size))
        starts = np.random.randint(0, n - block_size, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]
        b_b = b_ret[indices]
        s_b = s_ret[indices]
        b_sh = (b_b.mean() - rf_d) / b_b.std() * np.sqrt(252) if b_b.std() > 0 else 0
        s_sh = (s_b.mean() - rf_d) / s_b.std() * np.sqrt(252) if s_b.std() > 0 else 0
        diffs_boot.append(s_sh - b_sh)
    diffs_boot = np.array(diffs_boot)

    # Cross-OOS on 0056 (use Split A periods that have data)
    oos_results = []
    for start, end in OOS_SPLIT_A:
        mask = (data_0056.index >= start) & (data_0056.index <= end)
        sub = data_0056[mask]
        if len(sub) < 63:
            continue
        b = compute_base_returns(sub)
        s, _, _ = compute_hybrid_leverage_returns(sub)
        bm = compute_metrics(b)
        sm = compute_metrics(s)
        if bm and sm:
            d = sm["sharpe"] - bm["sharpe"]
            oos_results.append({
                "period": f"{start} to {end}",
                "base_sharpe": bm["sharpe"],
                "strat_sharpe": sm["sharpe"],
                "sharpe_diff": round(d, 3),
                "win": d > 0,
            })

    n_wins = sum(1 for r in oos_results if r["win"])

    result = {
        "status": "OK",
        "ticker": "0056.TW",
        "data_period": f"{data_0056.index[0].date()} to {data_0056.index[-1].date()}",
        "n_days": len(data_0056),
        "base_metrics": base_m,
        "strategy_metrics": strat_m,
        "sharpe_diff": round(diff, 3),
        "harvey_dm": dm,
        "bootstrap": {
            "mean_diff": round(np.mean(diffs_boot), 4),
            "ci_2_5": round(np.percentile(diffs_boot, 2.5), 4),
            "ci_97_5": round(np.percentile(diffs_boot, 97.5), 4),
            "p_win": round((diffs_boot > 0).mean() * 100, 1),
        },
        "cross_oos": {
            "n_wins": n_wins,
            "n_total": len(oos_results),
            "win_rate": round(n_wins / len(oos_results) * 100, 1) if oos_results else 0,
            "periods": oos_results,
        },
    }

    print(f"  0056.TW: {result['data_period']}, N={result['n_days']}")
    print(f"  Base Sharpe: {base_m['sharpe']:.3f}, Strat Sharpe: {strat_m['sharpe']:.3f}")
    print(f"  Sharpe diff: {diff:+.3f}")
    print(f"  Harvey t: {dm['t_stat']:.3f}, pass: {dm['harvey_pass']}")
    print(f"  Bootstrap P(win): {result['bootstrap']['p_win']:.1f}%")
    print(f"  Cross-OOS: {n_wins}/{len(oos_results)} wins")

    return result


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    print("╔" + "═" * 68 + "╗")
    print("║  K558: K553 TAIWAN HYBRID LEVERAGE — DEEP VALIDATION FOR LISTING  ║")
    print("╚" + "═" * 68 + "╝")
    print(f"\nStrategy: Binary Hybrid Leverage")
    print(f"  If RV22_TW < {DEFAULT_RV_THRESH}% AND VIX_pctile < {DEFAULT_VIX_PCTILE}")
    print(f"    → leverage {DEFAULT_LEVERAGE}x on 0050.TW VT (8.63/VIX)")
    print(f"  Else → 1.0x (no leverage)")
    print(f"\nValidation: 8-point checklist (same rigor as K551 US)")

    # ─── Download data ───
    data = download_data("0050.TW")

    # ─── Full-sample baseline ───
    print("\n" + "=" * 70)
    print("FULL-SAMPLE BASELINE")
    print("=" * 70)

    base_ret = compute_base_returns(data)
    strat_ret, lev, n_trades = compute_hybrid_leverage_returns(data)

    base_m = compute_metrics(base_ret)
    strat_m = compute_metrics(strat_ret)
    sharpe_diff = strat_m["sharpe"] - base_m["sharpe"]

    print(f"\n  Base (8.63/VIX):  Sharpe={base_m['sharpe']:.3f}, "
          f"CAGR={base_m['cagr']:.2f}%, MDD={base_m['mdd']:.1f}%")
    print(f"  Hybrid Leverage:  Sharpe={strat_m['sharpe']:.3f}, "
          f"CAGR={strat_m['cagr']:.2f}%, MDD={strat_m['mdd']:.1f}%")
    print(f"  Sharpe diff:      {sharpe_diff:+.3f}")
    print(f"  Days leveraged:   {(lev > 1.0).mean()*100:.1f}% ({(lev > 1.0).sum()} days)")
    print(f"  Total trades:     {n_trades}")

    # Leverage diagnostics
    lev_days = lev[lev > 1.0]
    lev_diag = {
        "pct_days_leveraged": round((lev > 1.0).mean() * 100, 1),
        "n_days_leveraged": int((lev > 1.0).sum()),
        "total_trades": int(n_trades),
        "trades_per_year": round(n_trades / (len(data) / 252), 1),
    }

    # ═════════════════ TEST 1: Harvey DM ═════════════════
    print("\n" + "=" * 70)
    print("TEST 1: HARVEY (2016) DM TEST WITH NEWEY-WEST HAC")
    print("=" * 70)

    dm = dm_test_harvey(base_ret, strat_ret)
    print(f"  t-statistic:    {dm['t_stat']:.4f}")
    print(f"  p-value:        {dm['p_value']:.6f}")
    print(f"  Newey-West lags: {dm['nw_lags']}")
    print(f"  Harvey t>3.0:   {'PASS ✓' if dm['harvey_pass'] else 'FAIL ✗'}")
    print(f"  Mean daily diff: {dm['mean_daily_diff']:.4f} bps")

    # ═════════════════ TEST 2: Cross-OOS ═════════════════
    print("\n" + "=" * 70)
    print("TEST 2: CROSS-OOS VALIDATION (3 splits)")
    print("=" * 70)

    oos_a = cross_oos_test(data, OOS_SPLIT_A, "Split A (5 periods)")
    print(f"\n  Split A: {oos_a['n_wins']}/{oos_a['n_total']} wins "
          f"({oos_a['win_rate']:.0f}%)")
    for p in oos_a["periods"]:
        status = "WIN" if p["win"] else "LOSS"
        print(f"    {p['period']}: Sharpe {p['base_sharpe']:.3f} → {p['strat_sharpe']:.3f} "
              f"({p['sharpe_diff']:+.3f}) [{status}] lev={p['pct_leveraged']:.0f}%")

    oos_b = cross_oos_test(data, OOS_SPLIT_B, "Split B (6 periods)")
    print(f"\n  Split B: {oos_b['n_wins']}/{oos_b['n_total']} wins "
          f"({oos_b['win_rate']:.0f}%)")
    for p in oos_b["periods"]:
        status = "WIN" if p["win"] else "LOSS"
        print(f"    {p['period']}: Sharpe {p['base_sharpe']:.3f} → {p['strat_sharpe']:.3f} "
              f"({p['sharpe_diff']:+.3f}) [{status}] lev={p['pct_leveraged']:.0f}%")

    oos_c = cross_oos_test(data, OOS_SPLIT_C, "Split C (7 periods)")
    print(f"\n  Split C: {oos_c['n_wins']}/{oos_c['n_total']} wins "
          f"({oos_c['win_rate']:.0f}%)")
    for p in oos_c["periods"]:
        status = "WIN" if p["win"] else "LOSS"
        print(f"    {p['period']}: Sharpe {p['base_sharpe']:.3f} → {p['strat_sharpe']:.3f} "
              f"({p['sharpe_diff']:+.3f}) [{status}] lev={p['pct_leveraged']:.0f}%")

    total_wins = oos_a["n_wins"] + oos_b["n_wins"] + oos_c["n_wins"]
    total_periods = oos_a["n_total"] + oos_b["n_total"] + oos_c["n_total"]
    print(f"\n  TOTAL: {total_wins}/{total_periods} wins "
          f"({total_wins/total_periods*100:.0f}%)")

    # ═════════════════ TEST 3: Sensitivity ═════════════════
    sensitivity = sensitivity_analysis(data)

    # ═════════════════ TEST 4: TX cost ═════════════════
    tx = transaction_cost_analysis(data)

    # ═════════════════ TEST 5: Borrowing cost ═════════════════
    borrow = borrowing_cost_analysis(data)

    # ═════════════════ TEST 6: Drawdown ═════════════════
    dd = drawdown_analysis(data)

    # ═════════════════ TEST 7: Bootstrap ═════════════════
    boot = bootstrap_test(data)

    # ═════════════════ TEST 8: Robustness 0056.TW ═════════════════
    robust = robustness_0056(data)

    # ═══════════════════════════════════════════════════════════
    # FINAL VERDICT
    # ═══════════════════════════════════════════════════════════
    print("\n" + "╔" + "═" * 68 + "╗")
    print("║                    FINAL VALIDATION VERDICT                       ║")
    print("╚" + "═" * 68 + "╝")

    checks = {
        "1_harvey_t_gt_3": dm["harvey_pass"],
        "2_cross_oos_a": oos_a["win_rate"] >= 80,
        "2_cross_oos_b": oos_b["win_rate"] >= 80,
        "2_cross_oos_c": oos_c["win_rate"] >= 80,
        "3_sensitivity_safe_zone": sensitivity["safe_zone_rate"] > 50,
        "4_tx_10bp_positive": (tx["realistic_10bp"] or {}).get("still_positive", False),
        "5_borrow_6pct_positive": (borrow["taiwan_6pct"] or {}).get("still_positive", False),
        "6_mdd_acceptable": abs(dd["full_period_strat_mdd"]) < abs(dd["full_period_base_mdd"]) * 1.5,
        "7_bootstrap_ci_positive": boot["ci_2_5"] > 0,
        "7_bootstrap_pwin_gt_90": boot["p_win"] > 90,
        "8_robustness_0056": (robust.get("sharpe_diff", 0) > 0
                              if robust.get("status") == "OK" else "SKIP"),
    }

    n_pass = sum(1 for v in checks.values() if v is True or v == True)
    n_fail = sum(1 for v in checks.values() if v is False or v == False)
    n_skip = sum(1 for v in checks.values() if isinstance(v, str) and v == "SKIP")

    print(f"\n  {'Check':<40} {'Result':<10}")
    print(f"  {'-'*40} {'-'*10}")
    for check, result in checks.items():
        if isinstance(result, str) and result == "SKIP":
            status = "SKIP"
        elif result:
            status = "PASS ✓"
        else:
            status = "FAIL ✗"
        print(f"  {check:<40} {status}")

    print(f"\n  PASS: {n_pass}, FAIL: {n_fail}, SKIP: {n_skip}")

    all_critical_pass = (
        checks["1_harvey_t_gt_3"] and
        checks["2_cross_oos_a"] and
        checks["2_cross_oos_b"] and
        checks["7_bootstrap_ci_positive"] and
        checks["7_bootstrap_pwin_gt_90"]
    )

    if all_critical_pass and n_fail <= 2:
        verdict = "PASS — Ready for listing"
        print(f"\n  ★★★★★ VERDICT: {verdict}")
    elif all_critical_pass:
        verdict = "CONDITIONAL PASS — Minor issues, review needed"
        print(f"\n  ★★★★ VERDICT: {verdict}")
    else:
        verdict = "FAIL — Not ready for listing"
        print(f"\n  ★★ VERDICT: {verdict}")

    # ─── Save results ───
    results = {
        "experiment_id": "K558",
        "title": "K553 Taiwan Hybrid Leverage — Deep Validation for Listing",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance (0050.TW, 0056.TW, ^VIX)",
        "data_period": f"{data.index[0].date()} to {data.index[-1].date()}",
        "n_days": len(data),
        "strategy": {
            "description": (f"Binary Hybrid: If RV22_TW < {DEFAULT_RV_THRESH}% "
                          f"AND VIX_pctile < {DEFAULT_VIX_PCTILE} → {DEFAULT_LEVERAGE}x, "
                          f"else 1.0x"),
            "rv_threshold_pct": DEFAULT_RV_THRESH,
            "vix_pctile_threshold": DEFAULT_VIX_PCTILE,
            "leverage_multiplier": DEFAULT_LEVERAGE,
            "base_strategy": "8.63/VIX Taiwan VT (from K461)",
        },
        "references": [
            "K553: Taiwan Hybrid Leverage discovery (Variant E best)",
            "K548: Original VIX-Conditional Leverage (US)",
            "K551: US deep validation (11/11 OOS, Harvey t=7.90)",
            "K461: Taiwan VT calibration (8.63/VIX)",
            "Moreira & Muir (2017) Volatility-Managed Portfolios, JF",
            "Harvey et al. (2016) t>3.0 threshold, RFS",
        ],
        "full_sample": {
            "base": base_m,
            "strategy": strat_m,
            "sharpe_diff": round(sharpe_diff, 3),
            "leverage_diagnostics": lev_diag,
        },
        "test_1_harvey_dm": dm,
        "test_2_cross_oos": {
            "split_a": oos_a,
            "split_b": oos_b,
            "split_c": oos_c,
            "total_wins": total_wins,
            "total_periods": total_periods,
            "overall_win_rate": round(total_wins / total_periods * 100, 1),
        },
        "test_3_sensitivity": {
            "n_configs": sensitivity["n_configs"],
            "n_positive": sensitivity["n_positive"],
            "positive_rate": sensitivity["positive_rate"],
            "safe_zone_rate": sensitivity["safe_zone_rate"],
            "top10": sensitivity["top10"],
            "bottom5": sensitivity["bottom5"],
            "parameter_stability": sensitivity["parameter_stability"],
            "base_sharpe": sensitivity["base_sharpe"],
        },
        "test_4_transaction_costs": tx,
        "test_5_borrowing_costs": borrow,
        "test_6_drawdown": dd,
        "test_7_bootstrap": boot,
        "test_8_robustness_0056": robust,
        "validation_verdict": {
            "checks": {k: str(v) for k, v in checks.items()},
            "n_pass": n_pass,
            "n_fail": n_fail,
            "n_skip": n_skip,
            "verdict": verdict,
        },
    }

    out_path = Path(__file__).parent / "k558_k553_taiwan_validation_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return results


if __name__ == "__main__":
    main()
