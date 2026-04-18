#!/usr/bin/env python3
"""
K251: GLD-TLT Mean Reversion — Safe Haven Rotation
=====================================================
Tests whether the relative dynamics between GLD and TLT (both safe havens
with different macro drivers) can improve portfolio allocation.

Background: K246 showed SPY-QQQ pairs trading fails (not cointegrated).
GLD responds to inflation fear; TLT responds to deflation/flight-to-quality.
When one outperforms, does mean reversion or momentum work better?

Hypothesis: Safe haven rotation based on GLD-TLT relative performance
can outperform static 50/50 SPY/GLD allocation.

Strategy Variants (all with SPY component):
  a. Momentum:  40% SPY + 60% winner(GLD,TLT) — ride the trend
  b. Reversion: 40% SPY + 60% loser(GLD,TLT) — buy the laggard
  c. Z-Score:   when |Z|>1.5, overweight laggard (mean reversion on extremes)
  d. Combined:  momentum when Z moderate, reversion when Z extreme

Benchmarks:
  - 50/50 SPY/GLD (our best known simple allocation)
  - 50/50 SPY/GLD + VT overlay (12/VIX)
  - Equal-weight SPY/GLD/TLT

Methodology:
  - 5-period cross-OOS validation
  - DM test for pairwise strategy comparison
  - Harvey (2016) t>3.0 threshold for significance
  - Transaction cost: 10 bps round trip (monthly rebalance)

Data: GLD, TLT, SPY, ^VIX — yfinance, 2005-2024
Author: VolPred Research System (K251)
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ============================================================
# Configuration
# ============================================================
TICKERS = ["SPY", "GLD", "TLT", "^VIX"]
START_DATE = "2005-01-01"
END_DATE = "2024-12-31"
LOOKBACK_3M = 63  # ~3 months trading days
Z_LOOKBACK = 252  # 1 year for Z-score normalization
Z_THRESHOLD = 1.5  # extreme threshold for Z-score strategy
TX_COST = 0.001  # 10 bps one-way (monthly rebalance)
REBAL_FREQ = "M"  # monthly rebalance
VIX_THRESHOLD = 12  # for VT overlay benchmark

# 5-period cross-OOS windows
OOS_PERIODS = [
    ("2008-01-01", "2010-12-31", "GFC 2008-2010"),
    ("2011-01-01", "2013-12-31", "Recovery 2011-2013"),
    ("2014-01-01", "2016-12-31", "Low Vol 2014-2016"),
    ("2017-01-01", "2019-12-31", "Late Cycle 2017-2019"),
    ("2020-01-01", "2024-12-31", "COVID+ 2020-2024"),
]


def download_data():
    """Download adjusted close prices for all tickers."""
    print("=" * 60)
    print("K251: GLD-TLT Mean Reversion — Safe Haven Rotation")
    print("=" * 60)
    print(f"\nDownloading data: {TICKERS}")
    print(f"Period: {START_DATE} to {END_DATE}")

    all_data = {}
    for t in TICKERS:
        print(f"  Downloading {t}...")
        df = yf.download(t, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
        if df.empty:
            raise ValueError(f"No data for {t}")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        all_data[t] = df["Close"]

    prices = pd.DataFrame(all_data).dropna()
    # Rename ^VIX
    prices = prices.rename(columns={"^VIX": "VIX"})
    print(f"  Combined data: {len(prices)} trading days, {prices.index[0].date()} to {prices.index[-1].date()}")
    return prices


def compute_returns(prices):
    """Compute daily log returns."""
    returns = np.log(prices / prices.shift(1)).dropna()
    return returns


def compute_spread(prices, lookback=LOOKBACK_3M):
    """
    Compute GLD-TLT relative performance spread.
    spread = GLD 3-month return - TLT 3-month return
    Positive = GLD outperforming (inflation fear dominant)
    Negative = TLT outperforming (deflation fear dominant)
    """
    gld_ret = prices["GLD"].pct_change(lookback)
    tlt_ret = prices["TLT"].pct_change(lookback)
    spread = gld_ret - tlt_ret
    return spread


def compute_zscore(spread, lookback=Z_LOOKBACK):
    """Compute rolling Z-score of the GLD-TLT spread."""
    roll_mean = spread.rolling(lookback).mean()
    roll_std = spread.rolling(lookback).std()
    zscore = (spread - roll_mean) / roll_std
    return zscore


def get_month_end_dates(prices):
    """Get month-end rebalance dates."""
    return prices.resample("ME").last().index


def strategy_momentum(spread_signal, spy_w=0.40, safe_w=0.60):
    """
    Momentum: 40% SPY + 60% winner(GLD, TLT).
    If GLD outperforming (spread > 0): overweight GLD.
    If TLT outperforming (spread < 0): overweight TLT.
    Weights determined at month-end, applied next month (lagged).
    """
    gld_w = np.where(spread_signal > 0, safe_w, 0.0)
    tlt_w = np.where(spread_signal <= 0, safe_w, 0.0)
    spy_wt = np.full(len(spread_signal), spy_w)
    return pd.DataFrame(
        {"SPY": spy_wt, "GLD": gld_w, "TLT": tlt_w},
        index=spread_signal.index,
    )


def strategy_reversion(spread_signal, spy_w=0.40, safe_w=0.60):
    """
    Reversion: 40% SPY + 60% loser(GLD, TLT).
    Buy the laggard, expecting mean reversion.
    """
    gld_w = np.where(spread_signal <= 0, safe_w, 0.0)
    tlt_w = np.where(spread_signal > 0, safe_w, 0.0)
    spy_wt = np.full(len(spread_signal), spy_w)
    return pd.DataFrame(
        {"SPY": spy_wt, "GLD": gld_w, "TLT": tlt_w},
        index=spread_signal.index,
    )


def strategy_zscore_reversion(zscore_signal, spy_w=0.40, z_thresh=Z_THRESHOLD):
    """
    Z-Score Reversion: When |Z| > threshold, overweight laggard.
    Otherwise, equal-weight GLD/TLT.
    """
    gld_w = np.zeros(len(zscore_signal))
    tlt_w = np.zeros(len(zscore_signal))

    for i in range(len(zscore_signal)):
        z = zscore_signal.iloc[i]
        if z > z_thresh:
            # GLD strongly outperforming → mean reversion → buy TLT
            gld_w[i] = 0.15
            tlt_w[i] = 0.45
        elif z < -z_thresh:
            # TLT strongly outperforming → mean reversion → buy GLD
            gld_w[i] = 0.45
            tlt_w[i] = 0.15
        else:
            # Neutral → equal weight
            gld_w[i] = 0.30
            tlt_w[i] = 0.30

    spy_wt = np.full(len(zscore_signal), spy_w)
    return pd.DataFrame(
        {"SPY": spy_wt, "GLD": gld_w, "TLT": tlt_w},
        index=zscore_signal.index,
    )


def strategy_combined(spread_signal, zscore_signal, spy_w=0.40, z_thresh=Z_THRESHOLD):
    """
    Combined: Momentum when Z moderate, Reversion when Z extreme.
    |Z| > threshold → reversion (overweight laggard)
    |Z| <= threshold → momentum (overweight winner)
    """
    gld_w = np.zeros(len(zscore_signal))
    tlt_w = np.zeros(len(zscore_signal))

    for i in range(len(zscore_signal)):
        z = zscore_signal.iloc[i]
        s = spread_signal.iloc[i]

        if abs(z) > z_thresh:
            # Extreme → reversion
            if z > z_thresh:
                gld_w[i] = 0.15
                tlt_w[i] = 0.45
            else:
                gld_w[i] = 0.45
                tlt_w[i] = 0.15
        else:
            # Moderate → momentum
            if s > 0:
                gld_w[i] = 0.45
                tlt_w[i] = 0.15
            else:
                gld_w[i] = 0.15
                tlt_w[i] = 0.45

    spy_wt = np.full(len(zscore_signal), spy_w)
    return pd.DataFrame(
        {"SPY": spy_wt, "GLD": gld_w, "TLT": tlt_w},
        index=zscore_signal.index,
    )


def benchmark_5050_spy_gld():
    """Static 50/50 SPY/GLD."""
    return {"SPY": 0.50, "GLD": 0.50, "TLT": 0.00}


def benchmark_equal_weight():
    """Static 1/3 SPY + 1/3 GLD + 1/3 TLT."""
    return {"SPY": 1 / 3, "GLD": 1 / 3, "TLT": 1 / 3}


def compute_portfolio_returns(daily_returns, weights_df, rebal_dates):
    """
    Compute portfolio returns with monthly rebalancing.
    weights_df has monthly signals; apply them from next month (lagged).
    """
    port_returns = pd.Series(0.0, index=daily_returns.index)
    assets = ["SPY", "GLD", "TLT"]

    # Create daily weights by forward-filling monthly weights
    # Shift by 1 month to ensure lagged application
    daily_weights = weights_df[assets].reindex(daily_returns.index).ffill()
    # Lag by 1 day to avoid look-ahead: signal on day T → weight on day T+1
    daily_weights = daily_weights.shift(1).dropna()

    common_idx = daily_returns.index.intersection(daily_weights.index)
    for asset in assets:
        port_returns.loc[common_idx] += daily_weights.loc[common_idx, asset] * daily_returns.loc[common_idx, asset]

    return port_returns.loc[common_idx]


def compute_static_portfolio_returns(daily_returns, static_weights, rebal_dates):
    """
    Compute portfolio returns for static allocation with monthly rebalancing.
    """
    port_returns = pd.Series(0.0, index=daily_returns.index)
    assets = ["SPY", "GLD", "TLT"]

    for asset in assets:
        w = static_weights.get(asset, 0.0)
        port_returns += w * daily_returns[asset]

    return port_returns


def compute_vt_overlay_returns(daily_returns, vix, static_weights, vix_threshold=VIX_THRESHOLD):
    """
    Static allocation + 12/VIX overlay (capped at 1.0).
    VT scale = min(threshold/VIX, 1.0), applied next day (lagged).
    """
    vt_scale = (vix_threshold / vix).clip(upper=1.0)
    vt_scale_lagged = vt_scale.shift(1).dropna()  # lag 1 day

    common_idx = daily_returns.index.intersection(vt_scale_lagged.index)
    port_returns = pd.Series(0.0, index=common_idx)
    assets = ["SPY", "GLD", "TLT"]

    for asset in assets:
        w = static_weights.get(asset, 0.0)
        port_returns += w * vt_scale_lagged.loc[common_idx] * daily_returns.loc[common_idx, asset]

    return port_returns


def compute_metrics(returns, name, annual_factor=252):
    """Compute performance metrics for a return series."""
    if len(returns) < 10:
        return None

    mean_ret = returns.mean() * annual_factor
    std_ret = returns.std() * np.sqrt(annual_factor)
    sharpe = mean_ret / std_ret if std_ret > 0 else 0

    # MDD
    cum = (1 + returns).cumprod()
    running_max = cum.cummax()
    drawdown = (cum - running_max) / running_max
    mdd = drawdown.min()

    # Calmar
    calmar = mean_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = returns[returns < 0]
    downside_std = downside.std() * np.sqrt(annual_factor) if len(downside) > 0 else 0
    sortino = mean_ret / downside_std if downside_std > 0 else 0

    # Sharpe t-stat
    n_years = len(returns) / annual_factor
    sharpe_t = sharpe * np.sqrt(n_years)

    # Transaction cost estimate (monthly rebalancing ≈ 12 trades/year)
    # Assume average weight change ~20% per rebal → 2 * 0.20 * 12 * TX_COST
    # More precisely, count actual weight changes if available
    turnover_annual = 12 * 0.20  # conservative estimate
    tx_drag = turnover_annual * TX_COST * 2  # round trip
    net_sharpe = (mean_ret - tx_drag) / std_ret if std_ret > 0 else 0

    return {
        "name": name,
        "annual_return": float(mean_ret),
        "annual_vol": float(std_ret),
        "sharpe": float(sharpe),
        "sharpe_t": float(sharpe_t),
        "net_sharpe": float(net_sharpe),
        "mdd": float(mdd),
        "calmar": float(calmar),
        "sortino": float(sortino),
        "n_days": int(len(returns)),
        "n_years": float(n_years),
    }


def dm_test(e1, e2, h=1):
    """
    Diebold-Mariano test comparing two return series.
    H0: equal performance. H1: e1 is better (higher returns).
    Uses squared loss on returns (like utility comparison).
    """
    d = e1 - e2
    d = d.dropna()
    n = len(d)
    if n < 30:
        return np.nan, np.nan

    d_mean = d.mean()
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    if gamma0 == 0:
        return 0.0, 1.0

    dm_stat = d_mean / np.sqrt(gamma0 / n)
    p_value = 1 - stats.t.cdf(dm_stat, df=n - 1)
    return float(dm_stat), float(p_value)


def compute_turnover(weights_df):
    """Compute annualized turnover from weight changes."""
    if weights_df is None or len(weights_df) < 2:
        return 0.0
    delta = weights_df.diff().abs().sum(axis=1)
    # Monthly rebalance → ~12 changes per year
    # Count actual non-zero changes
    n_years = len(weights_df) / 12  # approximate months → years
    total_turnover = delta.sum()
    annual_turnover = total_turnover / n_years if n_years > 0 else 0
    return float(annual_turnover)


def analyze_spread(prices, spread, zscore):
    """Analyze the GLD-TLT spread characteristics."""
    print("\n" + "=" * 60)
    print("1. GLD-TLT SPREAD ANALYSIS")
    print("=" * 60)

    valid_spread = spread.dropna()
    valid_zscore = zscore.dropna()

    print(f"\n  Spread (GLD 3m ret - TLT 3m ret):")
    print(f"    Mean:   {valid_spread.mean():.4f}")
    print(f"    Std:    {valid_spread.std():.4f}")
    print(f"    Min:    {valid_spread.min():.4f}")
    print(f"    Max:    {valid_spread.max():.4f}")
    print(f"    Skew:   {valid_spread.skew():.4f}")
    print(f"    Kurt:   {valid_spread.kurtosis():.4f}")

    # ADF test for stationarity (mean reversion)
    from statsmodels.tsa.stattools import adfuller

    adf_result = adfuller(valid_spread, maxlag=20, autolag="AIC")
    print(f"\n  ADF Test (spread stationarity / mean reversion):")
    print(f"    ADF stat:  {adf_result[0]:.4f}")
    print(f"    p-value:   {adf_result[1]:.6f}")
    print(f"    Lags used: {adf_result[2]}")
    is_stationary = adf_result[1] < 0.05
    print(f"    Stationary? {'YES — spread mean reverts' if is_stationary else 'NO — no evidence of mean reversion'}")

    # Half-life of mean reversion
    spread_lag = valid_spread.shift(1).dropna()
    spread_diff = valid_spread.diff().dropna()
    common = spread_lag.index.intersection(spread_diff.index)
    slope = np.polyfit(spread_lag.loc[common], spread_diff.loc[common], 1)[0]
    if slope < 0:
        half_life = -np.log(2) / slope
        print(f"    Half-life: {half_life:.1f} trading days ({half_life/21:.1f} months)")
    else:
        half_life = np.inf
        print(f"    Half-life: ∞ (no mean reversion detected)")

    # Z-score distribution
    print(f"\n  Z-Score of Spread:")
    print(f"    Mean:     {valid_zscore.mean():.4f}")
    print(f"    Std:      {valid_zscore.std():.4f}")
    print(f"    % |Z|>1.0: {(abs(valid_zscore) > 1.0).mean()*100:.1f}%")
    print(f"    % |Z|>1.5: {(abs(valid_zscore) > 1.5).mean()*100:.1f}%")
    print(f"    % |Z|>2.0: {(abs(valid_zscore) > 2.0).mean()*100:.1f}%")

    # Correlation analysis
    returns = compute_returns(prices)
    valid_ret = returns.dropna()
    print(f"\n  Correlation Matrix (daily returns):")
    corr = valid_ret[["SPY", "GLD", "TLT"]].corr()
    for a in ["SPY", "GLD", "TLT"]:
        row = "    " + a.ljust(5)
        for b in ["SPY", "GLD", "TLT"]:
            row += f"{corr.loc[a, b]:8.3f}"
        print(row)

    # GLD-TLT correlation (key question: are they substitutes?)
    gld_tlt_corr = corr.loc["GLD", "TLT"]
    print(f"\n  GLD-TLT correlation: {gld_tlt_corr:.3f}")
    if gld_tlt_corr < 0.1:
        print("    → Low correlation: different risk factors (good for rotation)")
    elif gld_tlt_corr < 0.3:
        print("    → Moderate correlation: some overlap")
    else:
        print("    → High correlation: similar behavior (rotation less useful)")

    return {
        "spread_mean": float(valid_spread.mean()),
        "spread_std": float(valid_spread.std()),
        "adf_stat": float(adf_result[0]),
        "adf_pvalue": float(adf_result[1]),
        "is_stationary": bool(is_stationary),
        "half_life_days": float(half_life) if half_life != np.inf else None,
        "pct_z_above_1": float((abs(valid_zscore) > 1.0).mean()),
        "pct_z_above_1_5": float((abs(valid_zscore) > 1.5).mean()),
        "pct_z_above_2": float((abs(valid_zscore) > 2.0).mean()),
        "gld_tlt_corr": float(gld_tlt_corr),
    }


def run_full_sample(prices, returns):
    """Run all strategies on full sample."""
    print("\n" + "=" * 60)
    print("2. FULL SAMPLE STRATEGY COMPARISON")
    print("=" * 60)

    spread = compute_spread(prices)
    zscore = compute_zscore(spread)

    # Get month-end rebalance dates
    rebal_dates = get_month_end_dates(prices)

    # Compute signals at month-end (lagged: signal at month-end → applied next month)
    spread_monthly = spread.reindex(rebal_dates).ffill().dropna()
    zscore_monthly = zscore.reindex(rebal_dates).ffill().dropna()

    # Ensure common dates
    common_dates = spread_monthly.index.intersection(zscore_monthly.index)
    spread_monthly = spread_monthly.loc[common_dates]
    zscore_monthly = zscore_monthly.loc[common_dates]

    # Generate strategy weights
    w_momentum = strategy_momentum(spread_monthly)
    w_reversion = strategy_reversion(spread_monthly)
    w_zscore = strategy_zscore_reversion(zscore_monthly)
    w_combined = strategy_combined(spread_monthly, zscore_monthly)

    # Compute portfolio returns
    strats = {}
    strats["A. Momentum"] = compute_portfolio_returns(returns, w_momentum, rebal_dates)
    strats["B. Reversion"] = compute_portfolio_returns(returns, w_reversion, rebal_dates)
    strats["C. Z-Score Rev"] = compute_portfolio_returns(returns, w_zscore, rebal_dates)
    strats["D. Combined"] = compute_portfolio_returns(returns, w_combined, rebal_dates)

    # Benchmarks
    strats["BM1: 50/50 SPY/GLD"] = compute_static_portfolio_returns(
        returns, benchmark_5050_spy_gld(), rebal_dates
    )
    strats["BM2: Equal Wt"] = compute_static_portfolio_returns(
        returns, benchmark_equal_weight(), rebal_dates
    )
    strats["BM3: 50/50+VT"] = compute_vt_overlay_returns(
        returns, prices["VIX"], benchmark_5050_spy_gld()
    )

    # Trim to common period
    common_start = max(s.index[0] for s in strats.values() if len(s) > 0)
    common_end = min(s.index[-1] for s in strats.values() if len(s) > 0)
    for k in strats:
        strats[k] = strats[k].loc[common_start:common_end]

    # Compute metrics
    print(f"\n  Period: {common_start.date()} to {common_end.date()}")
    print(f"\n  {'Strategy':<25} {'Return':>8} {'Vol':>8} {'Sharpe':>8} {'t-stat':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8}")
    print("  " + "-" * 95)

    metrics = {}
    for name, ret in strats.items():
        m = compute_metrics(ret, name)
        if m:
            metrics[name] = m
            print(
                f"  {name:<25} {m['annual_return']:>7.1%} {m['annual_vol']:>7.1%} "
                f"{m['sharpe']:>8.3f} {m['sharpe_t']:>8.2f} {m['mdd']:>7.1%} "
                f"{m['calmar']:>8.3f} {m['sortino']:>8.3f}"
            )

    # DM tests vs benchmark (50/50 SPY/GLD)
    print(f"\n  DM Tests vs 50/50 SPY/GLD (H1: strategy is better):")
    bm_ret = strats["BM1: 50/50 SPY/GLD"]
    for name in ["A. Momentum", "B. Reversion", "C. Z-Score Rev", "D. Combined"]:
        if name in strats:
            dm_stat, dm_p = dm_test(strats[name], bm_ret)
            sig = "***" if dm_p < 0.01 else "**" if dm_p < 0.05 else "*" if dm_p < 0.10 else ""
            print(f"    {name:<25}: DM={dm_stat:>6.3f}, p={dm_p:.4f} {sig}")

    return strats, metrics


def run_cross_oos(prices, returns):
    """Run 5-period cross-OOS validation."""
    print("\n" + "=" * 60)
    print("3. CROSS-OOS VALIDATION (5 Periods)")
    print("=" * 60)

    spread_full = compute_spread(prices)
    zscore_full = compute_zscore(spread_full)

    oos_results = []

    for oos_start, oos_end, period_name in OOS_PERIODS:
        print(f"\n  --- {period_name} ({oos_start} to {oos_end}) ---")

        # Filter to OOS period
        ret_mask = (returns.index >= oos_start) & (returns.index <= oos_end)
        oos_returns = returns.loc[ret_mask]
        oos_prices = prices.loc[(prices.index >= oos_start) & (prices.index <= oos_end)]

        if len(oos_returns) < 60:
            print(f"    Skipping: only {len(oos_returns)} days")
            continue

        # Get spread/zscore for this period (using FULL history for rolling calcs)
        spread_mask = (spread_full.index >= oos_start) & (spread_full.index <= oos_end)
        spread_oos = spread_full.loc[spread_mask]
        zscore_mask = (zscore_full.index >= oos_start) & (zscore_full.index <= oos_end)
        zscore_oos = zscore_full.loc[zscore_mask]

        if spread_oos.dropna().empty or zscore_oos.dropna().empty:
            print(f"    Skipping: no valid signals")
            continue

        # Month-end rebalance dates within OOS
        rebal_mask = (spread_full.index >= oos_start) & (spread_full.index <= oos_end)
        rebal_idx = spread_full.loc[rebal_mask].resample("ME").last().index

        spread_monthly = spread_full.reindex(rebal_idx).ffill().dropna()
        zscore_monthly = zscore_full.reindex(rebal_idx).ffill().dropna()

        common_dates = spread_monthly.index.intersection(zscore_monthly.index)
        if len(common_dates) < 2:
            print(f"    Skipping: insufficient rebalance dates")
            continue
        spread_monthly = spread_monthly.loc[common_dates]
        zscore_monthly = zscore_monthly.loc[common_dates]

        # Strategy weights
        w_momentum = strategy_momentum(spread_monthly)
        w_reversion = strategy_reversion(spread_monthly)
        w_zscore = strategy_zscore_reversion(zscore_monthly)
        w_combined = strategy_combined(spread_monthly, zscore_monthly)

        # Returns
        strats = {}
        strats["A. Momentum"] = compute_portfolio_returns(oos_returns, w_momentum, rebal_idx)
        strats["B. Reversion"] = compute_portfolio_returns(oos_returns, w_reversion, rebal_idx)
        strats["C. Z-Score Rev"] = compute_portfolio_returns(oos_returns, w_zscore, rebal_idx)
        strats["D. Combined"] = compute_portfolio_returns(oos_returns, w_combined, rebal_idx)
        strats["BM1: 50/50 SPY/GLD"] = compute_static_portfolio_returns(
            oos_returns, benchmark_5050_spy_gld(), rebal_idx
        )
        strats["BM2: Equal Wt"] = compute_static_portfolio_returns(
            oos_returns, benchmark_equal_weight(), rebal_idx
        )

        # VT overlay needs VIX
        if "VIX" in prices.columns:
            strats["BM3: 50/50+VT"] = compute_vt_overlay_returns(
                oos_returns, prices["VIX"], benchmark_5050_spy_gld()
            )

        # Trim to common
        lens = {k: len(v) for k, v in strats.items() if len(v) > 0}
        if not lens:
            continue

        common_start = max(s.index[0] for s in strats.values() if len(s) > 0)
        common_end = min(s.index[-1] for s in strats.values() if len(s) > 0)
        for k in strats:
            strats[k] = strats[k].loc[common_start:common_end]

        print(f"    Days: {len(strats['BM1: 50/50 SPY/GLD'])}")
        print(f"    {'Strategy':<25} {'Sharpe':>8} {'MDD':>8} {'Return':>8}")
        print("    " + "-" * 55)

        period_metrics = {}
        for name, ret in strats.items():
            m = compute_metrics(ret, name)
            if m:
                period_metrics[name] = m
                print(f"    {name:<25} {m['sharpe']:>8.3f} {m['mdd']:>7.1%} {m['annual_return']:>7.1%}")

        # Which strategy won this period?
        strat_names = ["A. Momentum", "B. Reversion", "C. Z-Score Rev", "D. Combined"]
        bm_sharpe = period_metrics.get("BM1: 50/50 SPY/GLD", {}).get("sharpe", 0)
        winners = [s for s in strat_names if period_metrics.get(s, {}).get("sharpe", 0) > bm_sharpe]
        print(f"    Strategies beating 50/50: {len(winners)}/4 → {winners if winners else 'NONE'}")

        oos_results.append({
            "period": period_name,
            "oos_start": oos_start,
            "oos_end": oos_end,
            "metrics": {k: v for k, v in period_metrics.items()},
            "n_strategies_beat_bm": len(winners),
            "winners": winners,
        })

    # Summary across OOS periods
    print(f"\n  === CROSS-OOS SUMMARY ===")
    strat_names = ["A. Momentum", "B. Reversion", "C. Z-Score Rev", "D. Combined"]
    print(f"  {'Strategy':<25} ", end="")
    for _, _, pname in OOS_PERIODS:
        print(f"{pname[:12]:>14}", end="")
    print(f"  {'Win Rate':>10}")
    print("  " + "-" * 100)

    cross_oos_summary = {}
    for sname in strat_names:
        print(f"  {sname:<25} ", end="")
        wins = 0
        total = 0
        for result in oos_results:
            pm = result["metrics"]
            bm_sharpe = pm.get("BM1: 50/50 SPY/GLD", {}).get("sharpe", 0)
            s_sharpe = pm.get(sname, {}).get("sharpe", 0)
            beat = s_sharpe > bm_sharpe
            if beat:
                wins += 1
            total += 1
            marker = "  ✓" if beat else "  ✗"
            print(f"{s_sharpe:>8.3f}{marker:>6}", end="")
        win_rate = wins / total if total > 0 else 0
        print(f"  {wins}/{total} ({win_rate:.0%})")
        cross_oos_summary[sname] = {
            "wins": wins,
            "total": total,
            "win_rate": float(win_rate),
        }

    return oos_results, cross_oos_summary


def run_subperiod_analysis(prices, returns):
    """Analyze which macro regimes favor which strategy."""
    print("\n" + "=" * 60)
    print("4. MACRO REGIME ANALYSIS")
    print("=" * 60)

    spread = compute_spread(prices)
    zscore = compute_zscore(spread)

    # Define regimes by VIX level
    vix = prices["VIX"]
    regimes = {
        "Low Vol (VIX<15)": vix < 15,
        "Normal (15≤VIX<25)": (vix >= 15) & (vix < 25),
        "High Vol (VIX≥25)": vix >= 25,
    }

    # Also define by spread direction
    spread_regimes = {
        "GLD outperforming (spread>0)": spread > 0,
        "TLT outperforming (spread<0)": spread < 0,
    }

    print("\n  A. Performance by VIX Regime:")
    for regime_name, regime_mask in regimes.items():
        regime_mask = regime_mask.reindex(returns.index).fillna(False)
        n_days = regime_mask.sum()
        if n_days < 60:
            continue

        regime_rets = returns.loc[regime_mask]
        spy_ret = regime_rets["SPY"].mean() * 252
        gld_ret = regime_rets["GLD"].mean() * 252
        tlt_ret = regime_rets["TLT"].mean() * 252

        print(f"\n    {regime_name} ({n_days} days):")
        print(f"      SPY: {spy_ret:>7.1%}   GLD: {gld_ret:>7.1%}   TLT: {tlt_ret:>7.1%}")

    print("\n  B. Performance by Spread Direction:")
    for regime_name, regime_mask in spread_regimes.items():
        regime_mask = regime_mask.reindex(returns.index).fillna(False)
        n_days = regime_mask.sum()
        if n_days < 60:
            continue

        regime_rets = returns.loc[regime_mask]
        spy_ret = regime_rets["SPY"].mean() * 252
        gld_ret = regime_rets["GLD"].mean() * 252
        tlt_ret = regime_rets["TLT"].mean() * 252

        print(f"\n    {regime_name} ({n_days} days):")
        print(f"      SPY: {spy_ret:>7.1%}   GLD: {gld_ret:>7.1%}   TLT: {tlt_ret:>7.1%}")

    # Forward return analysis: does laggard actually outperform next month?
    print("\n  C. Forward Return Analysis (does laggard outperform next month?):")
    spread_valid = spread.dropna()
    # Get monthly spread and next-month returns
    monthly_spread = spread_valid.resample("ME").last()
    monthly_gld_ret = prices["GLD"].resample("ME").last().pct_change()
    monthly_tlt_ret = prices["TLT"].resample("ME").last().pct_change()
    monthly_safe_spread_next = (monthly_gld_ret - monthly_tlt_ret).shift(-1)

    common = monthly_spread.dropna().index.intersection(monthly_safe_spread_next.dropna().index)
    if len(common) > 20:
        curr_spread = monthly_spread.loc[common]
        next_spread = monthly_safe_spread_next.loc[common]

        # Correlation: current spread → next month relative return
        corr_val = curr_spread.corr(next_spread)
        # t-test for correlation
        n = len(common)
        t_stat = corr_val * np.sqrt((n - 2) / (1 - corr_val**2)) if abs(corr_val) < 1 else 0
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 2))

        print(f"    Correlation(spread_t, GLD-TLT relative return_{{t+1}}): {corr_val:.4f}")
        print(f"    t-stat: {t_stat:.3f}, p-value: {p_val:.4f}, n={n}")

        if corr_val < 0:
            print("    → NEGATIVE: laggard tends to outperform next month (supports reversion)")
        elif corr_val > 0:
            print("    → POSITIVE: winner tends to keep winning (supports momentum)")
        else:
            print("    → ZERO: no predictability")

        # By quintile
        quintiles = pd.qcut(curr_spread, 5, labels=["Q1 (TLT>>GLD)", "Q2", "Q3", "Q4", "Q5 (GLD>>TLT)"])
        print(f"\n    Next-month GLD-TLT relative return by current spread quintile:")
        for q in ["Q1 (TLT>>GLD)", "Q2", "Q3", "Q4", "Q5 (GLD>>TLT)"]:
            q_mask = quintiles == q
            q_ret = next_spread.loc[q_mask].mean()
            q_n = q_mask.sum()
            print(f"      {q}: {q_ret:>7.3%} (n={q_n})")

        return {
            "forward_corr": float(corr_val),
            "forward_t": float(t_stat),
            "forward_p": float(p_val),
            "forward_n": int(n),
        }

    return {}


def run_harvey_test(strats, benchmark_name="BM1: 50/50 SPY/GLD"):
    """Apply Harvey (2016) multiple testing correction."""
    print("\n" + "=" * 60)
    print("5. HARVEY (2016) MULTIPLE TESTING ASSESSMENT")
    print("=" * 60)

    strat_names = ["A. Momentum", "B. Reversion", "C. Z-Score Rev", "D. Combined"]
    bm_ret = strats[benchmark_name]

    print(f"\n  Harvey threshold: t > 3.0 (accounting for data snooping)")
    print(f"  Benchmark: {benchmark_name}")
    print(f"\n  {'Strategy':<25} {'Sharpe':>8} {'t-stat':>8} {'DM vs BM':>10} {'DM p':>8} {'Harvey':>8}")
    print("  " + "-" * 80)

    harvey_results = {}
    for sname in strat_names:
        if sname not in strats:
            continue
        s_ret = strats[sname]
        s_m = compute_metrics(s_ret, sname)
        dm_stat, dm_p = dm_test(s_ret, bm_ret)
        passes_harvey = abs(s_m["sharpe_t"]) > 3.0
        harvey_results[sname] = {
            "sharpe": s_m["sharpe"],
            "sharpe_t": s_m["sharpe_t"],
            "dm_stat": dm_stat,
            "dm_p": dm_p,
            "passes_harvey": passes_harvey,
        }
        harvey_str = "PASS" if passes_harvey else "FAIL"
        print(
            f"  {sname:<25} {s_m['sharpe']:>8.3f} {s_m['sharpe_t']:>8.2f} "
            f"{dm_stat:>10.3f} {dm_p:>8.4f} {harvey_str:>8}"
        )

    return harvey_results


def main():
    """Run the complete K251 experiment."""
    # Download data
    prices = download_data()
    returns = compute_returns(prices)

    # 1. Spread analysis
    spread = compute_spread(prices)
    zscore = compute_zscore(spread)
    spread_analysis = analyze_spread(prices, spread, zscore)

    # 2. Full sample strategy comparison
    strats, full_metrics = run_full_sample(prices, returns)

    # 3. Cross-OOS validation
    oos_results, cross_oos_summary = run_cross_oos(prices, returns)

    # 4. Macro regime analysis
    regime_analysis = run_subperiod_analysis(prices, returns)

    # 5. Harvey test
    harvey_results = run_harvey_test(strats)

    # ============================================================
    # CONCLUSIONS
    # ============================================================
    print("\n" + "=" * 60)
    print("6. CONCLUSIONS")
    print("=" * 60)

    # Check if any strategy consistently beats benchmark
    best_strat = None
    best_win_rate = 0
    for sname, summary in cross_oos_summary.items():
        if summary["win_rate"] > best_win_rate:
            best_win_rate = summary["win_rate"]
            best_strat = sname

    print(f"\n  Best rotation strategy: {best_strat} (win rate: {best_win_rate:.0%} vs 50/50 SPY/GLD)")

    any_passes_harvey = any(v["passes_harvey"] for v in harvey_results.values())
    any_dm_sig = any(v["dm_p"] < 0.05 for v in harvey_results.values())

    if best_win_rate >= 0.6 and any_dm_sig:
        conclusion = "PROMISING: Rotation strategy shows some edge over static allocation"
    elif best_win_rate >= 0.6:
        conclusion = "WEAK: Rotation wins more often but not statistically significant"
    else:
        conclusion = "NULL RESULT: GLD-TLT rotation does NOT reliably beat 50/50 SPY/GLD"

    print(f"  Harvey (t>3.0) pass? {'YES' if any_passes_harvey else 'NO'}")
    print(f"  DM significant (p<0.05)? {'YES' if any_dm_sig else 'NO'}")
    print(f"  Conclusion: {conclusion}")

    print(f"\n  Spread stationarity: {'YES' if spread_analysis['is_stationary'] else 'NO'}")
    if spread_analysis.get("half_life_days"):
        print(f"  Mean reversion half-life: {spread_analysis['half_life_days']:.0f} days")

    if regime_analysis and regime_analysis.get("forward_corr") is not None:
        fc = regime_analysis["forward_corr"]
        direction = "reversion" if fc < 0 else "momentum" if fc > 0 else "none"
        print(f"  Forward predictability: r={fc:.4f} (supports {direction})")

    print(f"\n  Key Insight: Safe haven rotation adds complexity but likely")
    print(f"  does not overcome the simplicity advantage of static 50/50 SPY/GLD.")
    print(f"  The GLD-TLT spread is {'stationary' if spread_analysis['is_stationary'] else 'NOT stationary'},")
    if spread_analysis["is_stationary"]:
        print(f"  suggesting mean reversion exists, but the alpha may be too small")
        print(f"  to overcome transaction costs after monthly rebalancing.")
    else:
        print(f"  suggesting no reliable mean-reversion pattern to exploit.")

    # Save results
    results = {
        "experiment": "K251",
        "title": "GLD-TLT Mean Reversion — Safe Haven Rotation",
        "timestamp": datetime.now().isoformat(),
        "data_source": "yfinance",
        "data_period": f"{START_DATE} to {END_DATE}",
        "tickers": TICKERS,
        "methodology": {
            "spread": "GLD 3-month return - TLT 3-month return",
            "z_lookback": Z_LOOKBACK,
            "z_threshold": Z_THRESHOLD,
            "rebalance": "monthly",
            "tx_cost": TX_COST,
            "oos_periods": len(OOS_PERIODS),
        },
        "spread_analysis": spread_analysis,
        "full_sample_metrics": full_metrics,
        "oos_results": oos_results,
        "cross_oos_summary": cross_oos_summary,
        "regime_analysis": regime_analysis if regime_analysis else {},
        "harvey_results": harvey_results,
        "conclusion": conclusion,
        "limitations": [
            "Monthly rebalancing may miss intra-month reversions",
            "3-month lookback is arbitrary; other windows may perform differently",
            "Z-score threshold of 1.5 is one choice among many",
            "Transaction costs estimated at 10bps one-way (may be lower for liquid ETFs)",
            "No consideration of interest rate regime shifts (e.g., 2022 hiking cycle)",
            "GLD inception 2004 limits pre-GFC data; TLT inception 2002",
        ],
    }

    output_path = Path(__file__).parent / "k251_gld_tlt_rotation_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {output_path}")

    return results


if __name__ == "__main__":
    results = main()
