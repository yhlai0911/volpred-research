"""K681: VIX Percentile Strategy on Taiwan and International Markets

Motivation:
  K679/K680 validated VIX percentile strategy (w = 1 - percentile(VIX, 252d))
  with Sharpe 1.68 vs 12/VIX 1.08 on 50/50 SPY/GLD. Cross-OOS 5/5 wins,
  Harvey t=3.157. Key question: does this advantage transfer globally,
  or is it US-specific?

Markets tested:
  a. 0050.TW (Taiwan ETF, using VIX_{t-1} for timezone lag)
  b. 50/50 0050.TW+GLD (Taiwan + Gold)
  c. EFA (International Developed Markets ex-US)
  d. 50/50 SPY/GLD (US baseline, for comparison)

Each market compared: Percentile vs 12/VIX vs Buy-and-Hold.

Taiwan-specific: VIX_{t-1} (US closes before TW opens), monthly rebalancing
option, TX cost 18.5 bps.

References:
  - K679: VIX Percentile Strategy (Sharpe 1.68 vs 1.08)
  - K680: Cross-OOS validation (5/5 wins, t=3.157)
  - Copeland & Copeland (1999), Market Timing with VIX
  - Our K-series: Taiwan VT strategies (K461, vix_leading_guard)

Data source: yfinance (SPY, GLD, 0050.TW, EFA, ^VIX)
Period: 2010-01-01 to 2026-03-27

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
START_DATE = "2009-01-01"   # Extra year for 252d warmup
END_DATE = "2026-03-27"
EVAL_START = "2010-01-04"   # After 252d warmup from 2009
ROLLING_WINDOW = 252        # 1 year for percentile
TC_BPS_US = 5               # US transaction cost (bps, one-way)
TC_BPS_TW = 18.5            # Taiwan transaction cost (bps, one-way) — includes tax + commission
RF_DAILY = 0.04 / 252       # ~4% annual risk-free


def download_data():
    """Download all required data."""
    tickers = {
        "SPY": "SPY",
        "GLD": "GLD",
        "0050.TW": "0050.TW",
        "EFA": "EFA",
        "VIX": "^VIX",
    }

    prices = {}
    for name, ticker in tickers.items():
        print(f"  Downloading {ticker}...")
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        prices[name] = df["Close"].copy()
        prices[name].name = name

    # Combine into single DataFrame
    all_prices = pd.concat(prices.values(), axis=1)
    all_prices.columns = list(prices.keys())

    # Forward-fill missing prices (different trading calendars)
    all_prices = all_prices.ffill()

    # Compute returns
    returns = all_prices.pct_change()
    returns.columns = [f"{c}_ret" for c in all_prices.columns]

    # Combine prices and returns
    data = pd.concat([all_prices, returns], axis=1)
    data = data.dropna(subset=["VIX"])  # Need VIX for all strategies

    print(f"  Combined data: {data.index[0].date()} to {data.index[-1].date()}, {len(data)} days")
    print(f"  Non-null counts: SPY={data['SPY'].notna().sum()}, GLD={data['GLD'].notna().sum()}, "
          f"0050.TW={data['0050.TW'].notna().sum()}, EFA={data['EFA'].notna().sum()}")
    return data


def compute_vix_percentile(data, window=ROLLING_WINDOW):
    """Compute rolling VIX percentile rank."""
    vix = data["VIX"].values
    percentile = np.full(len(vix), np.nan)

    for i in range(window, len(vix)):
        window_vals = vix[i - window:i]
        percentile[i] = sp_stats.percentileofscore(window_vals, vix[i]) / 100.0

    data = data.copy()
    data["vix_percentile"] = percentile

    # VIX_{t-1} for Taiwan (US closes before TW opens)
    data["vix_lag1"] = data["VIX"].shift(1)

    # Lagged percentile for Taiwan
    percentile_lag = np.full(len(vix), np.nan)
    for i in range(window + 1, len(vix)):
        window_vals = vix[i - 1 - window:i - 1]
        percentile_lag[i] = sp_stats.percentileofscore(window_vals, vix[i - 1]) / 100.0

    data["vix_percentile_lag1"] = percentile_lag

    return data


def compute_weights(data):
    """Compute strategy weights for all markets."""
    vix = data["VIX"]
    vix_lag = data["vix_lag1"]
    pct = data["vix_percentile"]
    pct_lag = data["vix_percentile_lag1"]

    # --- US/EFA weights (use contemporaneous VIX) ---
    # 12/VIX
    data["w_12vix_us"] = np.minimum(12.0 / vix, 1.0)
    # Percentile
    data["w_pct_us"] = 1.0 - pct

    # --- Taiwan weights (use VIX_{t-1}) ---
    # 12/VIX with lag
    data["w_12vix_tw"] = np.minimum(12.0 / vix_lag, 1.0)
    # Percentile with lag
    data["w_pct_tw"] = 1.0 - pct_lag

    return data


def apply_monthly_rebalance(weights_daily):
    """Convert daily weights to monthly rebalancing (hold weight for entire month)."""
    monthly = weights_daily.copy()
    current_weight = np.nan

    prev_month = None
    for i in range(len(monthly)):
        idx = monthly.index[i]
        this_month = (idx.year, idx.month)
        if this_month != prev_month:
            # New month: update weight
            current_weight = monthly.iloc[i]
            prev_month = this_month
        else:
            # Same month: hold previous weight
            monthly.iloc[i] = current_weight

    return monthly


def backtest_single_asset(data, ret_col, weight_col, name, tc_bps, monthly_rebal=False):
    """Backtest a single-asset VT strategy."""
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()

    # Drop rows where either return or weight is NaN
    valid_mask = df[ret_col].notna() & df[weight_col].notna()
    df = df[valid_mask]

    if len(df) < 100:
        return None

    weights = df[weight_col].copy()

    # Apply monthly rebalancing if requested
    if monthly_rebal:
        weights = apply_monthly_rebalance(weights)

    weights_arr = weights.values
    asset_ret = df[ret_col].values
    tc_rate = tc_bps / 10000.0

    strategy_ret = np.zeros(len(df))
    prev_w = 0.0

    for i in range(len(df)):
        w = weights_arr[i]
        if np.isnan(w):
            w = prev_w

        tc = abs(w - prev_w) * tc_rate
        strategy_ret[i] = w * asset_ret[i] + (1 - w) * RF_DAILY - tc
        prev_w = w

    # Metrics
    cum_ret = np.cumprod(1 + strategy_ret)
    total_ret = cum_ret[-1] - 1
    n_years = len(df) / 252.0
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    ann_ret = np.mean(strategy_ret) * 252
    ann_vol = np.std(strategy_ret, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = (cum_ret - running_max) / running_max
    mdd = np.min(drawdowns)

    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = strategy_ret[strategy_ret < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = (ann_ret - 0.04) / downside_vol if downside_vol > 0 else 0

    # Turnover
    weight_changes = np.abs(np.diff(weights_arr[~np.isnan(weights_arr)]))
    avg_daily_turnover = np.mean(weight_changes) if len(weight_changes) > 0 else 0
    annual_turnover = avg_daily_turnover * 252

    # Net Sharpe (TC already embedded, but report gross vs net)
    gross_ret = np.zeros(len(df))
    prev_w2 = 0.0
    for i in range(len(df)):
        w = weights_arr[i]
        if np.isnan(w):
            w = prev_w2
        gross_ret[i] = w * asset_ret[i] + (1 - w) * RF_DAILY
        prev_w2 = w

    gross_ann_ret = np.mean(gross_ret) * 252
    gross_ann_vol = np.std(gross_ret, ddof=1) * np.sqrt(252)
    gross_sharpe = (gross_ann_ret - 0.04) / gross_ann_vol if gross_ann_vol > 0 else 0

    return {
        "strategy": name,
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "gross_sharpe": round(gross_sharpe, 3),
        "sortino": round(sortino, 3),
        "mdd_pct": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "ann_ret_pct": round(ann_ret * 100, 2),
        "avg_weight": round(float(np.nanmean(weights_arr)), 3),
        "annual_turnover": round(annual_turnover, 2),
        "tc_bps": tc_bps,
        "monthly_rebal": monthly_rebal,
        "n_days": len(df),
        "n_years": round(n_years, 1),
        "total_return_pct": round(total_ret * 100, 2),
    }


def backtest_portfolio(data, ret_cols, alloc_weights, weight_col, name, tc_bps, monthly_rebal=False):
    """Backtest a multi-asset portfolio VT strategy (e.g. 50/50 0050+GLD)."""
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()

    # Compute portfolio return
    portfolio_ret = sum(alloc_weights[i] * df[rc] for i, rc in enumerate(ret_cols))
    portfolio_ret.name = "portfolio_ret"
    df["portfolio_ret"] = portfolio_ret

    # Drop rows where portfolio return or weight is NaN
    valid_mask = df["portfolio_ret"].notna() & df[weight_col].notna()
    df = df[valid_mask]

    if len(df) < 100:
        return None

    weights = df[weight_col].copy()
    if monthly_rebal:
        weights = apply_monthly_rebalance(weights)

    weights_arr = weights.values
    port_ret = df["portfolio_ret"].values
    tc_rate = tc_bps / 10000.0

    strategy_ret = np.zeros(len(df))
    prev_w = 0.0

    for i in range(len(df)):
        w = weights_arr[i]
        if np.isnan(w):
            w = prev_w
        tc = abs(w - prev_w) * tc_rate
        strategy_ret[i] = w * port_ret[i] + (1 - w) * RF_DAILY - tc
        prev_w = w

    cum_ret = np.cumprod(1 + strategy_ret)
    total_ret = cum_ret[-1] - 1
    n_years = len(df) / 252.0
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    ann_ret = np.mean(strategy_ret) * 252
    ann_vol = np.std(strategy_ret, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = (cum_ret - running_max) / running_max
    mdd = np.min(drawdowns)
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    downside = strategy_ret[strategy_ret < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = (ann_ret - 0.04) / downside_vol if downside_vol > 0 else 0

    weight_changes = np.abs(np.diff(weights_arr[~np.isnan(weights_arr)]))
    avg_daily_turnover = np.mean(weight_changes) if len(weight_changes) > 0 else 0
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
        "avg_weight": round(float(np.nanmean(weights_arr)), 3),
        "annual_turnover": round(annual_turnover, 2),
        "tc_bps": tc_bps,
        "monthly_rebal": monthly_rebal,
        "n_days": len(df),
        "n_years": round(n_years, 1),
        "total_return_pct": round(total_ret * 100, 2),
    }


def buy_and_hold_metrics(data, ret_col, name):
    """Compute buy-and-hold metrics for a single asset."""
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()
    ret = df[ret_col].dropna()

    if len(ret) < 100:
        return None

    cum_ret = (1 + ret).cumprod()
    total_ret = float(cum_ret.iloc[-1] - 1)
    n_years = len(ret) / 252.0
    cagr = (1 + total_ret) ** (1 / n_years) - 1

    ann_ret = float(ret.mean() * 252)
    ann_vol = float(ret.std() * np.sqrt(252))
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

    running_max = np.maximum.accumulate(cum_ret.values)
    dd = (cum_ret.values - running_max) / running_max
    mdd = float(np.min(dd))

    return {
        "strategy": f"Buy-and-Hold {name}",
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "mdd_pct": round(mdd * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "ann_ret_pct": round(ann_ret * 100, 2),
        "n_days": len(ret),
        "n_years": round(n_years, 1),
    }


def buy_and_hold_portfolio_metrics(data, ret_cols, alloc_weights, name):
    """Compute buy-and-hold metrics for a portfolio."""
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()

    port_ret = sum(alloc_weights[i] * df[rc] for i, rc in enumerate(ret_cols))
    port_ret = port_ret.dropna()

    if len(port_ret) < 100:
        return None

    cum_ret = (1 + port_ret).cumprod()
    total_ret = float(cum_ret.iloc[-1] - 1)
    n_years = len(port_ret) / 252.0
    cagr = (1 + total_ret) ** (1 / n_years) - 1

    ann_ret = float(port_ret.mean() * 252)
    ann_vol = float(port_ret.std() * np.sqrt(252))
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

    running_max = np.maximum.accumulate(cum_ret.values)
    dd = (cum_ret.values - running_max) / running_max
    mdd = float(np.min(dd))

    return {
        "strategy": f"Buy-and-Hold {name}",
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "mdd_pct": round(mdd * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "ann_ret_pct": round(ann_ret * 100, 2),
        "n_days": len(port_ret),
        "n_years": round(n_years, 1),
    }


def dm_test(data, ret_col, weight_col_a, weight_col_b, name_a, name_b, monthly_rebal=False):
    """Diebold-Mariano style t-test comparing two strategies' daily returns."""
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()

    valid = df[ret_col].notna() & df[weight_col_a].notna() & df[weight_col_b].notna()
    df = df[valid]

    if len(df) < 100:
        return None

    wa = df[weight_col_a].copy()
    wb = df[weight_col_b].copy()
    if monthly_rebal:
        wa = apply_monthly_rebalance(wa)
        wb = apply_monthly_rebalance(wb)

    ret = df[ret_col].values
    ra = wa.values * ret + (1 - wa.values) * RF_DAILY
    rb = wb.values * ret + (1 - wb.values) * RF_DAILY

    diff = ra - rb
    diff = diff[~np.isnan(diff)]

    if len(diff) < 50:
        return None

    t_stat = float(np.mean(diff) / (np.std(diff, ddof=1) / np.sqrt(len(diff))))
    p_val = float(2 * sp_stats.t.sf(abs(t_stat), df=len(diff) - 1))

    return {
        "comparison": f"{name_a} vs {name_b}",
        "mean_diff_bps": round(float(np.mean(diff) * 10000), 3),
        "t_stat": round(t_stat, 3),
        "p_value": round(p_val, 4),
        "significant_5pct": p_val < 0.05,
        "harvey_pass": abs(t_stat) > 3.0,
        "n_obs": len(diff),
    }


def dm_test_portfolio(data, ret_cols, alloc_weights, weight_col_a, weight_col_b, name_a, name_b, monthly_rebal=False):
    """DM test for portfolio strategies."""
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()

    port_ret = sum(alloc_weights[i] * df[rc] for i, rc in enumerate(ret_cols))
    df["port_ret"] = port_ret

    valid = df["port_ret"].notna() & df[weight_col_a].notna() & df[weight_col_b].notna()
    df = df[valid]

    if len(df) < 100:
        return None

    wa = df[weight_col_a].copy()
    wb = df[weight_col_b].copy()
    if monthly_rebal:
        wa = apply_monthly_rebalance(wa)
        wb = apply_monthly_rebalance(wb)

    ret = df["port_ret"].values
    ra = wa.values * ret + (1 - wa.values) * RF_DAILY
    rb = wb.values * ret + (1 - wb.values) * RF_DAILY

    diff = ra - rb
    diff = diff[~np.isnan(diff)]

    if len(diff) < 50:
        return None

    t_stat = float(np.mean(diff) / (np.std(diff, ddof=1) / np.sqrt(len(diff))))
    p_val = float(2 * sp_stats.t.sf(abs(t_stat), df=len(diff) - 1))

    return {
        "comparison": f"{name_a} vs {name_b}",
        "mean_diff_bps": round(float(np.mean(diff) * 10000), 3),
        "t_stat": round(t_stat, 3),
        "p_value": round(p_val, 4),
        "significant_5pct": p_val < 0.05,
        "harvey_pass": abs(t_stat) > 3.0,
        "n_obs": len(diff),
    }


def sub_period_sharpe(data, ret_col, weight_col, tc_bps, monthly_rebal=False):
    """Compute Sharpe in sub-periods for robustness."""
    eval_data = data[data.index >= EVAL_START].copy()

    periods = {
        "2010-2014": ("2010-01-01", "2014-12-31"),
        "2015-2019": ("2015-01-01", "2019-12-31"),
        "2020-2026": ("2020-01-01", END_DATE),
    }

    results = {}
    for pname, (start, end) in periods.items():
        mask = (eval_data.index >= start) & (eval_data.index <= end)
        pdata = eval_data[mask]

        valid = pdata[ret_col].notna() & pdata[weight_col].notna()
        pdata = pdata[valid]

        if len(pdata) < 50:
            results[pname] = None
            continue

        weights = pdata[weight_col].copy()
        if monthly_rebal:
            weights = apply_monthly_rebalance(weights)

        w = weights.values
        r = pdata[ret_col].values
        tc_rate = tc_bps / 10000.0

        strat_ret = np.zeros(len(pdata))
        prev_w = 0.0
        for i in range(len(pdata)):
            wi = w[i] if not np.isnan(w[i]) else prev_w
            tc = abs(wi - prev_w) * tc_rate
            strat_ret[i] = wi * r[i] + (1 - wi) * RF_DAILY - tc
            prev_w = wi

        ann_ret = np.mean(strat_ret) * 252
        ann_vol = np.std(strat_ret, ddof=1) * np.sqrt(252)
        sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

        cum = np.cumprod(1 + strat_ret)
        running_max = np.maximum.accumulate(cum)
        dd = (cum - running_max) / running_max
        mdd = float(np.min(dd))

        results[pname] = {
            "sharpe": round(sharpe, 3),
            "ann_ret_pct": round(ann_ret * 100, 2),
            "mdd_pct": round(mdd * 100, 2),
            "n_days": len(pdata),
        }

    return results


def main():
    print("=" * 70)
    print("K681: VIX Percentile Strategy on Taiwan and International Markets")
    print("=" * 70)

    # Step 1: Download data
    print("\n--- Step 1: Downloading Data ---")
    data = download_data()

    # Step 2: Descriptive statistics
    print("\n--- Step 2: Descriptive Statistics ---")
    eval_data = data[data.index >= EVAL_START]

    descriptive = {}
    for asset, ret_col in [("SPY", "SPY_ret"), ("GLD", "GLD_ret"), ("0050.TW", "0050.TW_ret"), ("EFA", "EFA_ret")]:
        ret = eval_data[ret_col].dropna()
        if len(ret) > 100:
            ann_ret = float(ret.mean() * 252)
            ann_vol = float(ret.std() * np.sqrt(252))
            descriptive[asset] = {
                "ann_ret_pct": round(ann_ret * 100, 2),
                "ann_vol_pct": round(ann_vol * 100, 2),
                "sharpe_bh": round((ann_ret - 0.04) / ann_vol, 3) if ann_vol > 0 else 0,
                "skew": round(float(ret.skew()), 2),
                "kurt": round(float(ret.kurtosis()), 2),
                "n_days": len(ret),
            }
            print(f"  {asset}: ann_ret={ann_ret*100:.1f}%, ann_vol={ann_vol*100:.1f}%, "
                  f"Sharpe_BH={descriptive[asset]['sharpe_bh']:.3f}, n={len(ret)}")

    vix = eval_data["VIX"].dropna()
    vix_stats = {
        "mean": round(float(vix.mean()), 2),
        "std": round(float(vix.std()), 2),
        "min": round(float(vix.min()), 2),
        "max": round(float(vix.max()), 2),
        "median": round(float(vix.median()), 2),
    }
    print(f"  VIX: mean={vix_stats['mean']}, std={vix_stats['std']}, "
          f"min={vix_stats['min']}, max={vix_stats['max']}")

    # Step 3: Compute VIX percentile
    print("\n--- Step 3: Computing VIX Percentile ---")
    data = compute_vix_percentile(data)

    # Step 4: Compute weights
    print("--- Step 4: Computing Strategy Weights ---")
    data = compute_weights(data)

    # ========================================================================
    # Market A: US Baseline (50/50 SPY/GLD) — for comparison with K679
    # ========================================================================
    print("\n" + "=" * 70)
    print("MARKET A: US Baseline (50/50 SPY/GLD)")
    print("=" * 70)

    us_results = {}

    # Percentile (daily rebal)
    r = backtest_portfolio(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5], "w_pct_us",
                           "Percentile (50/50 SPY/GLD)", TC_BPS_US)
    if r:
        us_results["percentile"] = r
        print(f"  Percentile: Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # 12/VIX (daily rebal)
    r = backtest_portfolio(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5], "w_12vix_us",
                           "12/VIX (50/50 SPY/GLD)", TC_BPS_US)
    if r:
        us_results["12vix"] = r
        print(f"  12/VIX:     Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # Buy-and-Hold
    r = buy_and_hold_portfolio_metrics(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5], "50/50 SPY/GLD")
    if r:
        us_results["buy_hold"] = r
        print(f"  Buy&Hold:   Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # DM test: Percentile vs 12/VIX
    us_dm = dm_test_portfolio(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5],
                              "w_pct_us", "w_12vix_us",
                              "Percentile", "12/VIX")
    if us_dm:
        us_results["dm_test"] = us_dm
        print(f"  DM test: t={us_dm['t_stat']:.3f}, p={us_dm['p_value']:.4f}, Harvey pass={us_dm['harvey_pass']}")

    # ========================================================================
    # Market B: Taiwan 0050.TW (single asset, VIX_{t-1})
    # ========================================================================
    print("\n" + "=" * 70)
    print("MARKET B: Taiwan 0050.TW (VIX_{t-1}, monthly rebal, TC=18.5 bps)")
    print("=" * 70)

    tw_results = {}

    # Percentile (monthly rebal) — Taiwan
    r = backtest_single_asset(data, "0050.TW_ret", "w_pct_tw",
                              "Percentile (0050.TW, monthly)", TC_BPS_TW, monthly_rebal=True)
    if r:
        tw_results["percentile_monthly"] = r
        print(f"  Percentile (monthly): Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # Percentile (daily rebal) — Taiwan
    r = backtest_single_asset(data, "0050.TW_ret", "w_pct_tw",
                              "Percentile (0050.TW, daily)", TC_BPS_TW, monthly_rebal=False)
    if r:
        tw_results["percentile_daily"] = r
        print(f"  Percentile (daily):   Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # 12/VIX (monthly rebal) — Taiwan
    r = backtest_single_asset(data, "0050.TW_ret", "w_12vix_tw",
                              "12/VIX (0050.TW, monthly)", TC_BPS_TW, monthly_rebal=True)
    if r:
        tw_results["12vix_monthly"] = r
        print(f"  12/VIX (monthly):     Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # Buy-and-Hold 0050.TW
    r = buy_and_hold_metrics(data, "0050.TW_ret", "0050.TW")
    if r:
        tw_results["buy_hold"] = r
        print(f"  Buy&Hold:             Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # DM test: Percentile vs 12/VIX (monthly rebal, Taiwan)
    tw_dm = dm_test(data, "0050.TW_ret", "w_pct_tw", "w_12vix_tw",
                    "Percentile", "12/VIX", monthly_rebal=True)
    if tw_dm:
        tw_results["dm_test"] = tw_dm
        print(f"  DM test (monthly): t={tw_dm['t_stat']:.3f}, p={tw_dm['p_value']:.4f}")

    # ========================================================================
    # Market C: Taiwan + Gold (50/50 0050.TW + GLD)
    # ========================================================================
    print("\n" + "=" * 70)
    print("MARKET C: Taiwan + Gold (50/50 0050.TW + GLD, VIX_{t-1})")
    print("=" * 70)

    twgld_results = {}

    # Use average TC: (18.5 + 5) / 2 ≈ 12 bps for mixed portfolio
    TC_MIXED = 12.0

    # Percentile (monthly)
    r = backtest_portfolio(data, ["0050.TW_ret", "GLD_ret"], [0.5, 0.5], "w_pct_tw",
                           "Percentile (50/50 0050+GLD, monthly)", TC_MIXED, monthly_rebal=True)
    if r:
        twgld_results["percentile_monthly"] = r
        print(f"  Percentile (monthly): Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # 12/VIX (monthly)
    r = backtest_portfolio(data, ["0050.TW_ret", "GLD_ret"], [0.5, 0.5], "w_12vix_tw",
                           "12/VIX (50/50 0050+GLD, monthly)", TC_MIXED, monthly_rebal=True)
    if r:
        twgld_results["12vix_monthly"] = r
        print(f"  12/VIX (monthly):     Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # Buy-and-Hold 50/50 0050+GLD
    r = buy_and_hold_portfolio_metrics(data, ["0050.TW_ret", "GLD_ret"], [0.5, 0.5], "50/50 0050+GLD")
    if r:
        twgld_results["buy_hold"] = r
        print(f"  Buy&Hold:             Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # DM test
    twgld_dm = dm_test_portfolio(data, ["0050.TW_ret", "GLD_ret"], [0.5, 0.5],
                                 "w_pct_tw", "w_12vix_tw",
                                 "Percentile", "12/VIX", monthly_rebal=True)
    if twgld_dm:
        twgld_results["dm_test"] = twgld_dm
        print(f"  DM test: t={twgld_dm['t_stat']:.3f}, p={twgld_dm['p_value']:.4f}")

    # ========================================================================
    # Market D: EFA (International Developed, ex-US)
    # ========================================================================
    print("\n" + "=" * 70)
    print("MARKET D: EFA (International Developed Markets)")
    print("=" * 70)

    efa_results = {}

    # Percentile
    r = backtest_single_asset(data, "EFA_ret", "w_pct_us",
                              "Percentile (EFA)", TC_BPS_US)
    if r:
        efa_results["percentile"] = r
        print(f"  Percentile: Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # 12/VIX
    r = backtest_single_asset(data, "EFA_ret", "w_12vix_us",
                              "12/VIX (EFA)", TC_BPS_US)
    if r:
        efa_results["12vix"] = r
        print(f"  12/VIX:     Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # Buy-and-Hold EFA
    r = buy_and_hold_metrics(data, "EFA_ret", "EFA")
    if r:
        efa_results["buy_hold"] = r
        print(f"  Buy&Hold:   Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%, MDD={r['mdd_pct']:.2f}%")

    # DM test: Percentile vs 12/VIX (EFA)
    efa_dm = dm_test(data, "EFA_ret", "w_pct_us", "w_12vix_us",
                     "Percentile", "12/VIX")
    if efa_dm:
        efa_results["dm_test"] = efa_dm
        print(f"  DM test: t={efa_dm['t_stat']:.3f}, p={efa_dm['p_value']:.4f}")

    # ========================================================================
    # Sub-period robustness for all markets
    # ========================================================================
    print("\n" + "=" * 70)
    print("SUB-PERIOD ROBUSTNESS")
    print("=" * 70)

    sub_period_results = {}

    # US
    sp_us_pct = sub_period_sharpe(data, "SPY_ret", "w_pct_us", TC_BPS_US)
    sp_us_12v = sub_period_sharpe(data, "SPY_ret", "w_12vix_us", TC_BPS_US)
    sub_period_results["US_SPY"] = {"percentile": sp_us_pct, "12vix": sp_us_12v}

    print("\n  US (SPY):")
    for period in sp_us_pct:
        if sp_us_pct[period] and sp_us_12v[period]:
            print(f"    {period}: Pct Sharpe={sp_us_pct[period]['sharpe']:.3f}, "
                  f"12/VIX Sharpe={sp_us_12v[period]['sharpe']:.3f}, "
                  f"diff={sp_us_pct[period]['sharpe']-sp_us_12v[period]['sharpe']:.3f}")

    # Taiwan
    sp_tw_pct = sub_period_sharpe(data, "0050.TW_ret", "w_pct_tw", TC_BPS_TW, monthly_rebal=True)
    sp_tw_12v = sub_period_sharpe(data, "0050.TW_ret", "w_12vix_tw", TC_BPS_TW, monthly_rebal=True)
    sub_period_results["Taiwan_0050"] = {"percentile": sp_tw_pct, "12vix": sp_tw_12v}

    print("\n  Taiwan (0050.TW, monthly rebal):")
    for period in sp_tw_pct:
        if sp_tw_pct[period] and sp_tw_12v[period]:
            print(f"    {period}: Pct Sharpe={sp_tw_pct[period]['sharpe']:.3f}, "
                  f"12/VIX Sharpe={sp_tw_12v[period]['sharpe']:.3f}, "
                  f"diff={sp_tw_pct[period]['sharpe']-sp_tw_12v[period]['sharpe']:.3f}")

    # EFA
    sp_efa_pct = sub_period_sharpe(data, "EFA_ret", "w_pct_us", TC_BPS_US)
    sp_efa_12v = sub_period_sharpe(data, "EFA_ret", "w_12vix_us", TC_BPS_US)
    sub_period_results["EFA"] = {"percentile": sp_efa_pct, "12vix": sp_efa_12v}

    print("\n  EFA:")
    for period in sp_efa_pct:
        if sp_efa_pct[period] and sp_efa_12v[period]:
            print(f"    {period}: Pct Sharpe={sp_efa_pct[period]['sharpe']:.3f}, "
                  f"12/VIX Sharpe={sp_efa_12v[period]['sharpe']:.3f}, "
                  f"diff={sp_efa_pct[period]['sharpe']-sp_efa_12v[period]['sharpe']:.3f}")

    # ========================================================================
    # Summary: Cross-market comparison
    # ========================================================================
    print("\n" + "=" * 70)
    print("CROSS-MARKET SUMMARY")
    print("=" * 70)

    summary_table = []

    market_results = {
        "US (50/50 SPY/GLD)": us_results,
        "Taiwan (0050.TW)": tw_results,
        "Taiwan+Gold (50/50)": twgld_results,
        "EFA (Int'l Developed)": efa_results,
    }

    for market_name, mresults in market_results.items():
        pct_key = "percentile" if "percentile" in mresults else "percentile_monthly"
        vix_key = "12vix" if "12vix" in mresults else "12vix_monthly"

        pct = mresults.get(pct_key, {})
        vix12 = mresults.get(vix_key, {})
        bh = mresults.get("buy_hold", {})
        dm = mresults.get("dm_test", {})

        row = {
            "market": market_name,
            "pct_sharpe": pct.get("sharpe"),
            "12vix_sharpe": vix12.get("sharpe"),
            "bh_sharpe": bh.get("sharpe"),
            "sharpe_diff": round(pct.get("sharpe", 0) - vix12.get("sharpe", 0), 3) if pct.get("sharpe") and vix12.get("sharpe") else None,
            "pct_mdd": pct.get("mdd_pct"),
            "pct_cagr": pct.get("cagr_pct"),
            "dm_t": dm.get("t_stat"),
            "dm_p": dm.get("p_value"),
            "pct_wins": pct.get("sharpe", 0) > vix12.get("sharpe", 0) if pct.get("sharpe") and vix12.get("sharpe") else None,
        }
        summary_table.append(row)

        print(f"\n  {market_name}:")
        print(f"    Percentile Sharpe = {pct.get('sharpe', 'N/A')}")
        print(f"    12/VIX     Sharpe = {vix12.get('sharpe', 'N/A')}")
        print(f"    Buy&Hold   Sharpe = {bh.get('sharpe', 'N/A')}")
        if dm:
            print(f"    DM test: t={dm.get('t_stat', 'N/A')}, p={dm.get('p_value', 'N/A')}")

    # ========================================================================
    # Key findings
    # ========================================================================
    findings = []

    # Count wins
    wins = sum(1 for r in summary_table if r.get("pct_wins"))
    total = sum(1 for r in summary_table if r.get("pct_wins") is not None)
    findings.append(f"Percentile beats 12/VIX in {wins}/{total} markets by Sharpe ratio")

    # Significant wins
    sig_wins = sum(1 for r in summary_table if r.get("dm_p") is not None and r["dm_p"] < 0.05 and r.get("sharpe_diff", 0) > 0)
    findings.append(f"Statistically significant wins (p<0.05): {sig_wins}/{total}")

    # Harvey threshold
    harvey_wins = sum(1 for r in summary_table if r.get("dm_t") is not None and abs(r["dm_t"]) > 3.0 and r.get("sharpe_diff", 0) > 0)
    findings.append(f"Harvey t>3.0 threshold: {harvey_wins}/{total}")

    # Best/worst market
    valid_diffs = [(r["market"], r["sharpe_diff"]) for r in summary_table if r.get("sharpe_diff") is not None]
    if valid_diffs:
        best = max(valid_diffs, key=lambda x: x[1])
        worst = min(valid_diffs, key=lambda x: x[1])
        findings.append(f"Largest improvement: {best[0]} (Sharpe diff = {best[1]:.3f})")
        findings.append(f"Smallest improvement: {worst[0]} (Sharpe diff = {worst[1]:.3f})")

    # Taiwan-specific
    if tw_results.get("percentile_monthly") and tw_results.get("12vix_monthly"):
        tw_pct_s = tw_results["percentile_monthly"]["sharpe"]
        tw_12v_s = tw_results["12vix_monthly"]["sharpe"]
        findings.append(f"Taiwan 0050.TW: Percentile Sharpe={tw_pct_s:.3f} vs 12/VIX Sharpe={tw_12v_s:.3f} (monthly rebal, 18.5bp TC)")

    # Is it US-specific?
    non_us_wins = sum(1 for r in summary_table if r.get("pct_wins") and "US" not in r["market"])
    non_us_total = sum(1 for r in summary_table if r.get("pct_wins") is not None and "US" not in r["market"])
    if non_us_total > 0:
        if non_us_wins == non_us_total:
            findings.append(f"Percentile advantage is NOT US-specific — wins in all {non_us_wins} non-US markets")
        elif non_us_wins > 0:
            findings.append(f"Percentile advantage partially transfers: {non_us_wins}/{non_us_total} non-US markets")
        else:
            findings.append("Percentile advantage appears US-specific — no wins in non-US markets")

    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)
    for i, f in enumerate(findings, 1):
        print(f"  {i}. {f}")

    # ========================================================================
    # Save results
    # ========================================================================
    results = {
        "experiment_id": "K681",
        "title": "VIX Percentile Strategy on Taiwan and International Markets",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance (SPY, GLD, 0050.TW, EFA, ^VIX)",
        "data_period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{EVAL_START} to {END_DATE}",
        "methodology": {
            "percentile_strategy": "w = 1 - percentile_rank(VIX, 252d)",
            "baseline": "w = min(12/VIX, 1.0)",
            "taiwan_specific": "Uses VIX_{t-1} for timezone lag, monthly rebalancing",
            "transaction_costs": {
                "US": f"{TC_BPS_US} bps one-way",
                "Taiwan": f"{TC_BPS_TW} bps one-way (includes tax + commission)",
                "Mixed_portfolio": f"{TC_MIXED} bps one-way (weighted average)",
            },
            "risk_free_rate": "4% annual",
        },
        "references": [
            "K679: VIX Percentile Strategy (Sharpe 1.68 vs 1.08)",
            "K680: Cross-OOS validation (5/5 wins, t=3.157)",
            "Copeland & Copeland (1999), Market Timing with VIX",
            "VolPred K461: Taiwan VT with external variables",
        ],
        "descriptive_statistics": descriptive,
        "vix_statistics": vix_stats,
        "market_results": {
            "US_50_50_SPY_GLD": us_results,
            "Taiwan_0050": tw_results,
            "Taiwan_Gold_50_50": twgld_results,
            "EFA_International": efa_results,
        },
        "sub_period_robustness": sub_period_results,
        "cross_market_summary": summary_table,
        "key_findings": findings,
    }

    out_path = Path(__file__).parent / "k681_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
