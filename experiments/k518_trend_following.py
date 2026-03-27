#!/usr/bin/env python3
"""
K518: Trend Following / Moving Average Strategy
================================================
Compare price-based timing (MA crossover) vs buy-and-hold,
and test MA + VT overlay.

Strategies:
  1. SMA(200) Timing — Price > 200-day SMA → invested, else cash
  2. Faber 10-Month SMA — Price > 10-month SMA → invested, else cash
  3. Golden Cross — SMA(50) > SMA(200) → invested, else cash
  4. Dual Momentum (Antonacci) — 12-month SPY return + relative vs AGG
  5. MA(200) + VT Overlay — SMA(200) filter + 12/VIX weight

Assets: SPY (primary) + 50/50 SPY/GLD blend
Backtest: 2000-2025
TX: 0.05% per trade (one-way)
Cross-OOS: 5 periods

References:
  - Moskowitz, Ooi, Pedersen (2012) "Time Series Momentum" JFE
  - Faber (2007) "A Quantitative Approach to Tactical Asset Allocation"
  - Glabadanidis (2015) MA timing after TX
  - Antonacci (2014) "Dual Momentum Investing"

Author: VolPred Research System (K518)
Date: 2026-03-26
"""

import json
import warnings
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ─── CONFIG ───
TX_COST = 0.0005  # 0.05% one-way
RISK_FREE_ANNUAL = 0.02  # approximate
START_DATE = "1999-01-01"  # extra buffer for MA computation
END_DATE = "2025-12-31"

# Cross-OOS periods (5 non-overlapping ~5-year windows)
OOS_PERIODS = [
    ("2000-06-01", "2005-05-31"),
    ("2005-06-01", "2010-05-31"),
    ("2010-06-01", "2015-05-31"),
    ("2015-06-01", "2020-05-31"),
    ("2020-06-01", "2025-03-25"),
]


def download_data():
    """Download SPY, GLD, AGG, ^VIX data."""
    tickers = {
        "SPY": "SPY",
        "GLD": "GLD",
        "AGG": "AGG",
        "VIX": "^VIX",
    }
    data = {}
    for name, ticker in tickers.items():
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[name] = df
        print(f"  {name}: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    return data


def compute_signals(prices, vix=None):
    """
    Compute all strategy signals from price series.
    Returns DataFrame of daily signals (1=invested, 0=cash, float for VT).
    """
    df = pd.DataFrame(index=prices.index)
    df["price"] = prices
    df["ret"] = prices.pct_change()

    # SMA(200)
    df["sma200"] = prices.rolling(200).mean()
    df["sig_sma200"] = (prices > df["sma200"]).astype(float)

    # 10-month SMA ≈ 210 trading days
    df["sma210"] = prices.rolling(210).mean()
    df["sig_faber"] = (prices > df["sma210"]).astype(float)

    # Golden Cross: SMA(50) vs SMA(200)
    df["sma50"] = prices.rolling(50).mean()
    df["sig_golden"] = (df["sma50"] > df["sma200"]).astype(float)

    # VT overlay: SMA(200) filter + 12/VIX weight
    if vix is not None:
        vix_aligned = vix.reindex(prices.index).ffill()
        vt_weight = np.clip(12.0 / vix_aligned, 0.0, 1.5)
        df["sig_ma_vt"] = df["sig_sma200"] * vt_weight
    else:
        df["sig_ma_vt"] = np.nan

    return df


def compute_dual_momentum(spy_prices, agg_prices):
    """
    Dual Momentum (Antonacci):
    - SPY 12-month return > 0 AND SPY > AGG → SPY (signal=1)
    - SPY 12-month return > 0 AND SPY < AGG → AGG (signal=-1, meaning hold AGG)
    - SPY 12-month return ≤ 0 → cash (signal=0)

    Returns: signal series aligned to SPY index
    """
    # 252 trading days ≈ 12 months
    spy_mom = spy_prices.pct_change(252)

    # Align AGG to SPY index
    agg_aligned = agg_prices.reindex(spy_prices.index).ffill()
    agg_mom = agg_aligned.pct_change(252)

    signal = pd.Series(0.0, index=spy_prices.index)
    # SPY momentum positive
    pos_mom = spy_mom > 0
    # SPY beats AGG
    spy_beats = spy_mom > agg_mom
    signal[pos_mom & spy_beats] = 1.0   # hold SPY
    signal[pos_mom & ~spy_beats] = -1.0  # hold AGG (we'll handle returns separately)

    return signal, agg_aligned


def backtest_strategy(prices, signal, tx_cost=TX_COST, label="strategy"):
    """
    Backtest a long-only timing strategy.
    signal: 1=invested, 0=cash, float=partial position.
    Returns daily return series (after TX).
    """
    ret = prices.pct_change()

    # Align and drop NaN
    valid = signal.notna() & ret.notna()
    sig = signal[valid].copy()
    r = ret[valid].copy()

    # Detect trades (signal changes)
    sig_shift = sig.shift(1).fillna(0)
    trades = (sig != sig_shift).astype(float)

    # Strategy return = signal(t-1) * return(t) - TX on trade days
    # Use previous day's signal for today's return
    strat_ret = sig.shift(1).fillna(0) * r - trades * tx_cost

    return strat_ret


def backtest_dual_momentum(spy_prices, agg_prices, signal, tx_cost=TX_COST):
    """
    Dual momentum: signal=1 → SPY, signal=-1 → AGG, signal=0 → cash.
    """
    spy_ret = spy_prices.pct_change()
    agg_aligned = agg_prices.reindex(spy_prices.index).ffill()
    agg_ret = agg_aligned.pct_change()

    valid = signal.notna() & spy_ret.notna() & agg_ret.notna()
    sig = signal[valid].copy()
    spy_r = spy_ret[valid].copy()
    agg_r = agg_ret[valid].copy()

    sig_prev = sig.shift(1).fillna(0)
    trades = (sig != sig.shift(1)).astype(float)

    strat_ret = pd.Series(0.0, index=sig.index)
    strat_ret[sig_prev == 1] = spy_r[sig_prev == 1]
    strat_ret[sig_prev == -1] = agg_r[sig_prev == -1]
    strat_ret -= trades * tx_cost

    return strat_ret


def compute_metrics(returns, rf_annual=RISK_FREE_ANNUAL):
    """Compute performance metrics from daily return series."""
    if len(returns) < 20:
        return {}
    rf_daily = rf_annual / 252
    excess = returns - rf_daily

    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = excess.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

    # Max drawdown
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    max_dd = dd.min()

    # Calmar
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    # Sortino
    downside = returns[returns < 0]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-6
    sortino = (ann_ret - rf_annual) / downside_std

    # Win rate
    win_rate = (returns > 0).mean()

    # Skewness / kurtosis
    skew = returns.skew()
    kurt = returns.kurtosis()

    return {
        "ann_return": round(ann_ret, 4),
        "ann_vol": round(ann_vol, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "win_rate": round(win_rate, 4),
        "skew": round(skew, 4),
        "kurtosis": round(kurt, 4),
        "n_days": len(returns),
    }


def compute_trade_stats(signal):
    """Count number of trades and % time invested."""
    valid = signal.dropna()
    if len(valid) == 0:
        return {"n_trades": 0, "pct_invested": 0}
    changes = (valid != valid.shift(1)).sum()
    pct_invested = (valid > 0).mean()
    return {
        "n_trades": int(changes),
        "pct_invested": round(float(pct_invested), 4),
    }


def harvey_test(strat_returns, bh_returns):
    """
    Test if strategy Sharpe is significantly better than buy-and-hold.
    Uses Jobson-Korkie (1981) / Ledoit-Wolf (2008) test.
    Returns t-statistic and p-value.
    Harvey (2016) threshold: t > 3.0.
    """
    n = min(len(strat_returns), len(bh_returns))
    # Align
    idx = strat_returns.index.intersection(bh_returns.index)
    s = strat_returns.loc[idx].values
    b = bh_returns.loc[idx].values

    n = len(s)
    if n < 30:
        return 0, 1.0

    mu_s, mu_b = s.mean(), b.mean()
    sig_s, sig_b = s.std(), b.std()
    cov_sb = np.cov(s, b)[0, 1]

    # Sharpe difference test (Ledoit-Wolf 2008)
    sr_s = mu_s / sig_s if sig_s > 0 else 0
    sr_b = mu_b / sig_b if sig_b > 0 else 0

    # Approximate variance of Sharpe difference
    # Using HAC-robust approach
    diff = s / sig_s - b / sig_b if sig_s > 0 and sig_b > 0 else s - b
    se = diff.std() / np.sqrt(n)
    t_stat = (sr_s - sr_b) / se if se > 0 else 0
    p_val = 1 - stats.norm.cdf(t_stat)  # one-sided

    return round(t_stat, 4), round(p_val, 4)


def run_cross_oos(prices, signal_func, oos_periods, bh_returns_full, label="", **kwargs):
    """
    Run cross-OOS validation.
    signal_func: function(prices_slice, **kwargs) → signal series
    Returns list of per-period results.
    """
    results = []
    for i, (start, end) in enumerate(oos_periods):
        mask = (prices.index >= start) & (prices.index <= end)
        p_slice = prices[mask]
        if len(p_slice) < 100:
            continue

        if "agg_prices" in kwargs:
            sig, _ = signal_func(p_slice, kwargs["agg_prices"])
            strat_ret = backtest_dual_momentum(
                p_slice, kwargs["agg_prices"], sig, TX_COST
            )
        elif "vix" in kwargs:
            # Need full-length for SMA computation; compute on full, then slice
            sig_full = signal_func(prices, vix=kwargs["vix"])
            sig = sig_full[mask]
            strat_ret = backtest_strategy(p_slice, sig, TX_COST, label)
        else:
            # Compute signal on full history, slice OOS
            sig_full = signal_func(prices)
            sig = sig_full[mask]
            strat_ret = backtest_strategy(p_slice, sig, TX_COST, label)

        bh_mask = (bh_returns_full.index >= start) & (bh_returns_full.index <= end)
        bh_ret = bh_returns_full[bh_mask]

        # Align
        common_idx = strat_ret.index.intersection(bh_ret.index)
        strat_ret = strat_ret.loc[common_idx]
        bh_ret = bh_ret.loc[common_idx]

        m_strat = compute_metrics(strat_ret)
        m_bh = compute_metrics(bh_ret)
        t_stat, p_val = harvey_test(strat_ret, bh_ret)

        beats_bh = m_strat.get("sharpe", 0) > m_bh.get("sharpe", 0)

        results.append({
            "period": f"{start} to {end}",
            "period_idx": i + 1,
            "strategy_metrics": m_strat,
            "buyhold_metrics": m_bh,
            "sharpe_diff": round(m_strat.get("sharpe", 0) - m_bh.get("sharpe", 0), 4),
            "harvey_t": t_stat,
            "harvey_p": p_val,
            "beats_buyhold": beats_bh,
        })

    return results


def signal_sma200(prices, **kwargs):
    """SMA(200) signal on full history."""
    sma = prices.rolling(200).mean()
    return (prices > sma).astype(float)


def signal_faber(prices, **kwargs):
    """Faber 10-month SMA signal."""
    sma = prices.rolling(210).mean()
    return (prices > sma).astype(float)


def signal_golden(prices, **kwargs):
    """Golden Cross signal."""
    sma50 = prices.rolling(50).mean()
    sma200 = prices.rolling(200).mean()
    return (sma50 > sma200).astype(float)


def signal_dual_momentum(spy_prices, agg_prices, **kwargs):
    """Dual Momentum signal."""
    spy_mom = spy_prices.pct_change(252)
    agg_aligned = agg_prices.reindex(spy_prices.index).ffill()
    agg_mom = agg_aligned.pct_change(252)

    signal = pd.Series(0.0, index=spy_prices.index)
    pos_mom = spy_mom > 0
    spy_beats = spy_mom > agg_mom
    signal[pos_mom & spy_beats] = 1.0
    signal[pos_mom & ~spy_beats] = -1.0
    return signal, agg_aligned


def signal_ma_vt(prices, vix=None, **kwargs):
    """MA(200) + VT overlay."""
    sma200 = prices.rolling(200).mean()
    ma_sig = (prices > sma200).astype(float)
    if vix is not None:
        vix_aligned = vix.reindex(prices.index).ffill()
        vt_weight = np.clip(12.0 / vix_aligned, 0.0, 1.5)
        return ma_sig * vt_weight
    return ma_sig


def run_full_backtest(prices, signal, bh_returns, label=""):
    """Full-period backtest."""
    strat_ret = backtest_strategy(prices, signal, TX_COST, label)
    common = strat_ret.index.intersection(bh_returns.index)
    strat_ret = strat_ret.loc[common]
    bh_sub = bh_returns.loc[common]

    m_strat = compute_metrics(strat_ret)
    m_bh = compute_metrics(bh_sub)
    t_stat, p_val = harvey_test(strat_ret, bh_sub)
    trade_stats = compute_trade_stats(signal.loc[common])

    return {
        "strategy_metrics": m_strat,
        "buyhold_metrics": m_bh,
        "sharpe_diff": round(m_strat.get("sharpe", 0) - m_bh.get("sharpe", 0), 4),
        "harvey_t": t_stat,
        "harvey_p": p_val,
        "trade_stats": trade_stats,
    }


def run_blend_backtest(spy_prices, gld_prices, signal_spy, signal_gld, bh_spy_ret, bh_gld_ret, label=""):
    """50/50 SPY/GLD blend backtest."""
    spy_strat = backtest_strategy(spy_prices, signal_spy, TX_COST)
    gld_strat = backtest_strategy(gld_prices, signal_gld, TX_COST)

    # Align all
    common = spy_strat.index.intersection(gld_strat.index)
    common = common.intersection(bh_spy_ret.index).intersection(bh_gld_ret.index)

    blend_strat = 0.5 * spy_strat.loc[common] + 0.5 * gld_strat.loc[common]
    blend_bh = 0.5 * bh_spy_ret.loc[common] + 0.5 * bh_gld_ret.loc[common]

    m_strat = compute_metrics(blend_strat)
    m_bh = compute_metrics(blend_bh)
    t_stat, p_val = harvey_test(blend_strat, blend_bh)

    return {
        "strategy_metrics": m_strat,
        "buyhold_metrics": m_bh,
        "sharpe_diff": round(m_strat.get("sharpe", 0) - m_bh.get("sharpe", 0), 4),
        "harvey_t": t_stat,
        "harvey_p": p_val,
    }


def main():
    t0 = time.time()
    print("=" * 70)
    print("K518: Trend Following / Moving Average Strategy")
    print("=" * 70)

    # ─── 1. Download Data ───
    print("\n[1/5] Downloading data...")
    data = download_data()

    spy = data["SPY"]["Close"].squeeze()
    gld = data["GLD"]["Close"].squeeze()
    agg = data["AGG"]["Close"].squeeze()
    vix = data["VIX"]["Close"].squeeze()

    # Descriptive stats
    print(f"\n[DATA] SPY: {len(spy)} days, {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
    spy_ret = spy.pct_change().dropna()
    print(f"  Mean daily ret: {spy_ret.mean()*252:.4f} (ann)")
    print(f"  Std daily ret:  {spy_ret.std()*np.sqrt(252):.4f} (ann)")
    print(f"  Skew: {spy_ret.skew():.4f}, Kurtosis: {spy_ret.kurtosis():.4f}")

    # ─── 2. Compute Signals ───
    print("\n[2/5] Computing signals...")
    sig_sma200_spy = signal_sma200(spy)
    sig_faber_spy = signal_faber(spy)
    sig_golden_spy = signal_golden(spy)
    sig_dm_spy, agg_aligned = signal_dual_momentum(spy, agg)
    sig_mavt_spy = signal_ma_vt(spy, vix=vix)

    # GLD signals for blend
    sig_sma200_gld = signal_sma200(gld)
    sig_faber_gld = signal_faber(gld)
    sig_golden_gld = signal_golden(gld)
    sig_mavt_gld = signal_ma_vt(gld, vix=vix)

    bh_spy = spy.pct_change().dropna()
    bh_gld = gld.pct_change().dropna()

    # Signal statistics
    strategies = {
        "SMA(200)": sig_sma200_spy,
        "Faber_10M": sig_faber_spy,
        "Golden_Cross": sig_golden_spy,
        "MA+VT": sig_mavt_spy,
    }
    print("\nSignal statistics (SPY):")
    for name, sig in strategies.items():
        ts = compute_trade_stats(sig)
        print(f"  {name}: {ts['n_trades']} trades, {ts['pct_invested']*100:.1f}% time invested")

    dm_ts = compute_trade_stats(sig_dm_spy)
    print(f"  Dual_Momentum: {dm_ts['n_trades']} trades, {(sig_dm_spy != 0).mean()*100:.1f}% time NOT cash")

    # ─── 3. Full Period Backtest ───
    print("\n[3/5] Full-period backtest (SPY)...")
    results = {"experiment_id": "K518", "title": "Trend Following / Moving Average Strategy",
               "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
               "data_source": "yfinance (SPY, GLD, AGG, ^VIX)",
               "backtest_period": f"{spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}",
               "tx_cost": TX_COST,
               "references": [
                   "Moskowitz, Ooi, Pedersen (2012) Time Series Momentum, JFE",
                   "Faber (2007) A Quantitative Approach to Tactical Asset Allocation",
                   "Glabadanidis (2015) MA timing after TX",
                   "Antonacci (2014) Dual Momentum Investing",
               ]}

    # --- SPY strategies ---
    full_results_spy = {}

    # SMA(200)
    r = run_full_backtest(spy, sig_sma200_spy, bh_spy, "SMA200")
    full_results_spy["SMA200"] = r
    print(f"  SMA(200): Sharpe={r['strategy_metrics']['sharpe']:.4f} vs BH={r['buyhold_metrics']['sharpe']:.4f} (diff={r['sharpe_diff']:+.4f}, t={r['harvey_t']:.2f})")

    # Faber
    r = run_full_backtest(spy, sig_faber_spy, bh_spy, "Faber")
    full_results_spy["Faber_10M"] = r
    print(f"  Faber 10M: Sharpe={r['strategy_metrics']['sharpe']:.4f} vs BH={r['buyhold_metrics']['sharpe']:.4f} (diff={r['sharpe_diff']:+.4f}, t={r['harvey_t']:.2f})")

    # Golden Cross
    r = run_full_backtest(spy, sig_golden_spy, bh_spy, "Golden")
    full_results_spy["Golden_Cross"] = r
    print(f"  Golden Cross: Sharpe={r['strategy_metrics']['sharpe']:.4f} vs BH={r['buyhold_metrics']['sharpe']:.4f} (diff={r['sharpe_diff']:+.4f}, t={r['harvey_t']:.2f})")

    # Dual Momentum (special handling)
    dm_strat_ret = backtest_dual_momentum(spy, agg, sig_dm_spy, TX_COST)
    common_dm = dm_strat_ret.index.intersection(bh_spy.index)
    dm_strat_ret = dm_strat_ret.loc[common_dm]
    bh_dm = bh_spy.loc[common_dm]
    m_dm = compute_metrics(dm_strat_ret)
    m_bh_dm = compute_metrics(bh_dm)
    t_dm, p_dm = harvey_test(dm_strat_ret, bh_dm)
    full_results_spy["Dual_Momentum"] = {
        "strategy_metrics": m_dm,
        "buyhold_metrics": m_bh_dm,
        "sharpe_diff": round(m_dm.get("sharpe", 0) - m_bh_dm.get("sharpe", 0), 4),
        "harvey_t": t_dm,
        "harvey_p": p_dm,
        "trade_stats": compute_trade_stats(sig_dm_spy),
    }
    print(f"  Dual Momentum: Sharpe={m_dm['sharpe']:.4f} vs BH={m_bh_dm['sharpe']:.4f} (diff={m_dm['sharpe'] - m_bh_dm['sharpe']:+.4f}, t={t_dm:.2f})")

    # MA + VT
    r = run_full_backtest(spy, sig_mavt_spy, bh_spy, "MA+VT")
    full_results_spy["MA_VT_Overlay"] = r
    print(f"  MA+VT: Sharpe={r['strategy_metrics']['sharpe']:.4f} vs BH={r['buyhold_metrics']['sharpe']:.4f} (diff={r['sharpe_diff']:+.4f}, t={r['harvey_t']:.2f})")

    results["full_period_SPY"] = full_results_spy

    # --- 50/50 SPY/GLD blend ---
    print("\n  50/50 SPY/GLD Blend:")
    blend_results = {}
    for name, sig_spy, sig_gld in [
        ("SMA200", sig_sma200_spy, sig_sma200_gld),
        ("Faber_10M", sig_faber_spy, sig_faber_gld),
        ("Golden_Cross", sig_golden_spy, sig_golden_gld),
        ("MA_VT_Overlay", sig_mavt_spy, sig_mavt_gld),
    ]:
        r = run_blend_backtest(spy, gld, sig_spy, sig_gld, bh_spy, bh_gld, name)
        blend_results[name] = r
        print(f"    {name}: Sharpe={r['strategy_metrics']['sharpe']:.4f} vs BH={r['buyhold_metrics']['sharpe']:.4f} (diff={r['sharpe_diff']:+.4f})")

    results["full_period_blend"] = blend_results

    # ─── 4. Cross-OOS Validation ───
    print("\n[4/5] Cross-OOS validation (5 periods)...")
    cross_oos_results = {}

    # SMA(200) cross-OOS
    oos_sma = run_cross_oos(spy, signal_sma200, OOS_PERIODS, bh_spy, "SMA200")
    cross_oos_results["SMA200"] = oos_sma
    wins = sum(1 for r in oos_sma if r["beats_buyhold"])
    print(f"  SMA(200): {wins}/{len(oos_sma)} periods beat B&H")
    for r in oos_sma:
        print(f"    {r['period']}: Sharpe diff={r['sharpe_diff']:+.4f}, t={r['harvey_t']:.2f}")

    # Faber cross-OOS
    oos_fab = run_cross_oos(spy, signal_faber, OOS_PERIODS, bh_spy, "Faber")
    cross_oos_results["Faber_10M"] = oos_fab
    wins = sum(1 for r in oos_fab if r["beats_buyhold"])
    print(f"  Faber 10M: {wins}/{len(oos_fab)} periods beat B&H")
    for r in oos_fab:
        print(f"    {r['period']}: Sharpe diff={r['sharpe_diff']:+.4f}, t={r['harvey_t']:.2f}")

    # Golden Cross cross-OOS
    oos_gc = run_cross_oos(spy, signal_golden, OOS_PERIODS, bh_spy, "Golden")
    cross_oos_results["Golden_Cross"] = oos_gc
    wins = sum(1 for r in oos_gc if r["beats_buyhold"])
    print(f"  Golden Cross: {wins}/{len(oos_gc)} periods beat B&H")
    for r in oos_gc:
        print(f"    {r['period']}: Sharpe diff={r['sharpe_diff']:+.4f}, t={r['harvey_t']:.2f}")

    # Dual Momentum cross-OOS (special)
    print("  Dual Momentum cross-OOS:")
    oos_dm = []
    for i, (start, end) in enumerate(OOS_PERIODS):
        mask = (spy.index >= start) & (spy.index <= end)
        spy_slice = spy[mask]
        if len(spy_slice) < 100:
            continue
        sig_dm_slice, _ = signal_dual_momentum(spy_slice, agg)
        dm_ret_slice = backtest_dual_momentum(spy_slice, agg, sig_dm_slice, TX_COST)
        bh_mask = (bh_spy.index >= start) & (bh_spy.index <= end)
        bh_slice = bh_spy[bh_mask]
        common_idx = dm_ret_slice.index.intersection(bh_slice.index)
        dm_ret_slice = dm_ret_slice.loc[common_idx]
        bh_slice = bh_slice.loc[common_idx]
        m_s = compute_metrics(dm_ret_slice)
        m_b = compute_metrics(bh_slice)
        t_s, p_s = harvey_test(dm_ret_slice, bh_slice)
        beats = m_s.get("sharpe", 0) > m_b.get("sharpe", 0)
        oos_dm.append({
            "period": f"{start} to {end}",
            "period_idx": i + 1,
            "strategy_metrics": m_s,
            "buyhold_metrics": m_b,
            "sharpe_diff": round(m_s.get("sharpe", 0) - m_b.get("sharpe", 0), 4),
            "harvey_t": t_s,
            "harvey_p": p_s,
            "beats_buyhold": beats,
        })
    cross_oos_results["Dual_Momentum"] = oos_dm
    wins = sum(1 for r in oos_dm if r["beats_buyhold"])
    print(f"  Dual Momentum: {wins}/{len(oos_dm)} periods beat B&H")
    for r in oos_dm:
        print(f"    {r['period']}: Sharpe diff={r['sharpe_diff']:+.4f}, t={r['harvey_t']:.2f}")

    # MA+VT cross-OOS
    oos_mavt = run_cross_oos(spy, signal_ma_vt, OOS_PERIODS, bh_spy, "MA+VT", vix=vix)
    cross_oos_results["MA_VT_Overlay"] = oos_mavt
    wins = sum(1 for r in oos_mavt if r["beats_buyhold"])
    print(f"  MA+VT: {wins}/{len(oos_mavt)} periods beat B&H")
    for r in oos_mavt:
        print(f"    {r['period']}: Sharpe diff={r['sharpe_diff']:+.4f}, t={r['harvey_t']:.2f}")

    results["cross_oos"] = cross_oos_results

    # ─── 5. Summary & Conclusion ───
    print("\n[5/5] Summary...")
    print("\n" + "=" * 70)
    print("FULL-PERIOD SUMMARY (SPY)")
    print("=" * 70)
    print(f"{'Strategy':<20} {'Sharpe':>8} {'BH Sharpe':>10} {'Diff':>8} {'Harvey t':>10} {'MDD':>8} {'AnnRet':>8}")
    print("-" * 70)
    for name, r in full_results_spy.items():
        s = r["strategy_metrics"]
        b = r["buyhold_metrics"]
        print(f"{name:<20} {s['sharpe']:>8.4f} {b['sharpe']:>10.4f} {r['sharpe_diff']:>+8.4f} {r['harvey_t']:>10.2f} {s['max_drawdown']:>8.2%} {s['ann_return']:>8.2%}")

    print("\nCROSS-OOS SUMMARY")
    print("-" * 70)
    for name, periods in cross_oos_results.items():
        wins = sum(1 for r in periods if r["beats_buyhold"])
        avg_diff = np.mean([r["sharpe_diff"] for r in periods])
        max_t = max(r["harvey_t"] for r in periods)
        print(f"{name:<20} {wins}/{len(periods)} periods beat B&H, avg Sharpe diff={avg_diff:+.4f}, max t={max_t:.2f}")

    # Determine if any strategy passes all criteria
    print("\n" + "=" * 70)
    print("LISTING CRITERIA CHECK")
    print("=" * 70)
    listing_candidates = []
    for name in full_results_spy:
        full = full_results_spy[name]
        oos = cross_oos_results.get(name, [])
        wins = sum(1 for r in oos if r["beats_buyhold"])
        total = len(oos)

        net_sharpe_ok = full["strategy_metrics"]["sharpe"] > full["buyhold_metrics"]["sharpe"]
        cross_oos_ok = wins >= 4 if total == 5 else False
        harvey_ok = full["harvey_t"] > 3.0

        status = "PASS" if (net_sharpe_ok and cross_oos_ok and harvey_ok) else "FAIL"
        reasons = []
        if not net_sharpe_ok:
            reasons.append("Net Sharpe <= B&H")
        if not cross_oos_ok:
            reasons.append(f"Cross-OOS {wins}/{total} < 4/5")
        if not harvey_ok:
            reasons.append(f"Harvey t={full['harvey_t']:.2f} < 3.0")

        print(f"  {name:<20}: {status}  {'  |  '.join(reasons) if reasons else 'All criteria met'}")
        if status == "PASS":
            listing_candidates.append(name)

    results["listing_candidates"] = listing_candidates
    results["conclusion"] = (
        f"Tested 5 trend following strategies. "
        f"{len(listing_candidates)} passed all listing criteria (Net Sharpe > B&H, Cross-OOS >= 4/5, Harvey t > 3.0). "
        f"{'Candidates: ' + ', '.join(listing_candidates) if listing_candidates else 'No strategy meets listing standards.'}"
    )

    # ─── Regime Analysis ───
    print("\n" + "=" * 70)
    print("REGIME ANALYSIS: MA strategies in different VIX regimes")
    print("=" * 70)
    vix_aligned = vix.reindex(spy.index).ffill()
    regimes = {
        "Low VIX (<15)": vix_aligned < 15,
        "Normal (15-25)": (vix_aligned >= 15) & (vix_aligned < 25),
        "High VIX (>=25)": vix_aligned >= 25,
    }

    regime_results = {}
    for regime_name, mask in regimes.items():
        regime_days = mask.sum()
        if regime_days < 50:
            continue
        print(f"\n  {regime_name} ({regime_days} days):")
        regime_data = {}
        for strat_name, sig in [("SMA200", sig_sma200_spy), ("Faber_10M", sig_faber_spy),
                                 ("Golden_Cross", sig_golden_spy), ("MA_VT", sig_mavt_spy)]:
            strat_ret = backtest_strategy(spy, sig, TX_COST)
            bh_ret_full = spy.pct_change()
            common = strat_ret.index.intersection(bh_ret_full.index)
            strat_regime = strat_ret.loc[common][mask.reindex(common).fillna(False)]
            bh_regime = bh_ret_full.loc[common][mask.reindex(common).fillna(False)]
            if len(strat_regime) < 30:
                continue
            m_s = compute_metrics(strat_regime)
            m_b = compute_metrics(bh_regime)
            regime_data[strat_name] = {
                "strategy_sharpe": m_s.get("sharpe", 0),
                "bh_sharpe": m_b.get("sharpe", 0),
                "diff": round(m_s.get("sharpe", 0) - m_b.get("sharpe", 0), 4),
            }
            print(f"    {strat_name}: Sharpe={m_s.get('sharpe', 0):.4f} vs BH={m_b.get('sharpe', 0):.4f}")
        regime_results[regime_name] = regime_data

    results["regime_analysis"] = regime_results

    # ─── Save Results ───
    elapsed = time.time() - t0
    results["elapsed_seconds"] = round(elapsed, 1)

    out_path = "experiments/k518_trend_following_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n{'=' * 70}")
    print(f"Completed in {elapsed:.1f}s")
    print(f"Results saved to {out_path}")
    print(f"{'=' * 70}")

    return results


if __name__ == "__main__":
    main()
