#!/usr/bin/env python3
"""
K255: TSMOM 6_1 Final Validation — Pre-Launch Stress Test
=========================================================
[提出: 用戶, 執行: Claude]

Background: TSMOM 6_1 is the only strategy that passes Harvey (t=4.37)
from 17 strategy experiments. Before launching it on the platform, we
need one final comprehensive validation.

Data: SPY, GLD, TLT, VIX daily from yfinance. FULL available history (2004-2024).

Tests:
  1. Extended backtest (21 years, full performance metrics)
  2. Regime robustness (bull/bear/transition)
  3. Parameter sensitivity (lookback, rebalance freq, start date)
  4. Turnover and TX cost analysis
  5. Drawdown analysis (all >5%, recovery time)
  6. Current positioning (March 2026)
  7. Comparison with existing platform strategies
"""

import json
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────
# 0. Data Acquisition
# ─────────────────────────────────────────────────

def fetch_data():
    """Fetch SPY, GLD, TLT, VIX from yfinance with maximum history."""
    import yfinance as yf

    tickers = {
        "SPY": "SPY",
        "GLD": "GLD",
        "TLT": "TLT",
        "VIX": "^VIX",
    }

    data = {}
    for name, ticker in tickers.items():
        print(f"  Fetching {name} ({ticker})...")
        df = yf.download(ticker, start="2004-01-01", end="2026-12-31",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        print(f"    {name}: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")
        data[name] = df

    return data


# ─────────────────────────────────────────────────
# 1. TSMOM Strategy Implementation
# ─────────────────────────────────────────────────

def compute_tsmom(prices_dict, lookback_months=6, hold_months=1,
                  rebal_freq="monthly", start_offset_months=0):
    """
    Time-Series Momentum (TSMOM) multi-asset strategy.

    For each asset (SPY, GLD, TLT):
      - Look back `lookback_months` months
      - If cumulative return > 0: go LONG (equal weight share)
      - If cumulative return <= 0: go to CASH (SHY proxy = 0%)
      - Rebalance at `rebal_freq` frequency

    Returns daily portfolio returns and weight history.
    """
    # Build aligned price DataFrame
    spy_close = prices_dict["SPY"]["close"].rename("SPY")
    gld_close = prices_dict["GLD"]["close"].rename("GLD")
    tlt_close = prices_dict["TLT"]["close"].rename("TLT")

    prices = pd.concat([spy_close, gld_close, tlt_close], axis=1).dropna()
    assets = ["SPY", "GLD", "TLT"]
    n_assets = len(assets)

    # Daily returns
    returns = prices.pct_change().dropna()
    prices = prices.loc[returns.index]

    # Determine rebalance dates
    lookback_days = lookback_months * 21  # approx trading days per month
    hold_days = hold_months * 21

    # Start after lookback period + offset
    offset_days = start_offset_months * 21
    start_idx = lookback_days + offset_days

    if start_idx >= len(prices):
        raise ValueError(f"Not enough data: need {start_idx} days, have {len(prices)}")

    # Determine rebalance schedule
    if rebal_freq == "monthly":
        # Rebalance on first trading day of each month
        rebal_dates = []
        current_month = None
        for i in range(start_idx, len(prices)):
            dt = prices.index[i]
            ym = (dt.year, dt.month)
            if ym != current_month:
                rebal_dates.append(i)
                current_month = ym
    elif rebal_freq == "bimonthly":
        rebal_dates = []
        current_month = None
        month_count = 0
        for i in range(start_idx, len(prices)):
            dt = prices.index[i]
            ym = (dt.year, dt.month)
            if ym != current_month:
                month_count += 1
                current_month = ym
                if month_count % 2 == 1:
                    rebal_dates.append(i)
    elif rebal_freq == "quarterly":
        rebal_dates = []
        current_quarter = None
        for i in range(start_idx, len(prices)):
            dt = prices.index[i]
            yq = (dt.year, (dt.month - 1) // 3)
            if yq != current_quarter:
                rebal_dates.append(i)
                current_quarter = yq
    else:
        raise ValueError(f"Unknown rebal_freq: {rebal_freq}")

    # Initialize
    weights = pd.DataFrame(0.0, index=prices.index[start_idx:], columns=assets)
    portfolio_returns = pd.Series(0.0, index=prices.index[start_idx:])
    signal_history = pd.DataFrame(0, index=prices.index[start_idx:], columns=assets)

    current_weights = {a: 0.0 for a in assets}
    rebal_set = set(rebal_dates)

    for i in range(start_idx, len(prices)):
        idx = prices.index[i]

        if i in rebal_set:
            # Compute momentum signals
            for asset in assets:
                if i >= lookback_days:
                    past_price = prices[asset].iloc[i - lookback_days]
                    current_price = prices[asset].iloc[i]
                    mom_return = current_price / past_price - 1
                    signal = 1 if mom_return > 0 else 0
                else:
                    signal = 0
                signal_history.loc[idx, asset] = signal

            # Equal weight among assets with positive momentum
            n_long = sum(signal_history.loc[idx, a] for a in assets)
            for asset in assets:
                if signal_history.loc[idx, asset] == 1 and n_long > 0:
                    current_weights[asset] = 1.0 / n_assets  # equal weight per asset slot
                else:
                    current_weights[asset] = 0.0
        else:
            signal_history.loc[idx] = signal_history.iloc[
                signal_history.index.get_loc(idx) - 1
            ] if signal_history.index.get_loc(idx) > 0 else 0

        # Record weights
        for asset in assets:
            weights.loc[idx, asset] = current_weights[asset]

        # Portfolio return
        daily_ret = sum(
            current_weights[a] * returns.loc[idx, a]
            for a in assets
            if idx in returns.index
        )
        portfolio_returns.loc[idx] = daily_ret

    # Cash weight = 1 - sum(asset weights)
    weights["CASH"] = 1.0 - weights[assets].sum(axis=1)

    return portfolio_returns, weights, signal_history


def compute_benchmark_returns(prices_dict, strategy="buy_and_hold_spy"):
    """Compute benchmark strategy returns."""
    spy_close = prices_dict["SPY"]["close"].rename("SPY")
    gld_close = prices_dict["GLD"]["close"].rename("GLD")
    tlt_close = prices_dict["TLT"]["close"].rename("TLT")
    vix_close = prices_dict["VIX"]["close"].rename("VIX")

    prices = pd.concat([spy_close, gld_close, tlt_close], axis=1).dropna()
    returns = prices.pct_change().dropna()

    vix = vix_close.reindex(returns.index).ffill()

    if strategy == "buy_and_hold_spy":
        return returns["SPY"]
    elif strategy == "5050_vt":
        # 50/50 SPY/GLD with 12/VIX scaling, monthly rebalance
        w_scale = (12.0 / vix).clip(0, 1)
        # Lag by 1 day to avoid look-ahead
        w_scale = w_scale.shift(1).fillna(0.5)
        port_ret = 0.5 * w_scale * returns["SPY"] + 0.5 * w_scale * returns["GLD"]
        return port_ret
    elif strategy == "slow_vt":
        # GARCH VT SPY only - approximate with 12/VIX
        w_scale = (12.0 / vix).clip(0, 1)
        w_scale = w_scale.shift(1).fillna(0.5)
        return w_scale * returns["SPY"]
    elif strategy == "risk_parity":
        # Simple risk parity SPY/GLD (equal vol contribution)
        spy_vol = returns["SPY"].rolling(63).std() * np.sqrt(252)
        gld_vol = returns["GLD"].rolling(63).std() * np.sqrt(252)
        inv_vol = (1/spy_vol + 1/gld_vol)
        w_spy = (1/spy_vol) / inv_vol
        w_gld = (1/gld_vol) / inv_vol
        w_spy = w_spy.shift(1).fillna(0.5)
        w_gld = w_gld.shift(1).fillna(0.5)
        return w_spy * returns["SPY"] + w_gld * returns["GLD"]
    elif strategy == "simple_12vix":
        w_scale = (12.0 / vix).clip(0, 1).shift(1).fillna(0.5)
        return w_scale * returns["SPY"]
    elif strategy == "equal_weight":
        return returns[["SPY", "GLD", "TLT"]].mean(axis=1)
    elif strategy == "6040":
        return 0.6 * returns["SPY"] + 0.4 * returns["TLT"]
    else:
        raise ValueError(f"Unknown strategy: {strategy}")


# ─────────────────────────────────────────────────
# 2. Performance Metrics
# ─────────────────────────────────────────────────

def compute_metrics(returns, rf_annual=0.04):
    """Compute comprehensive performance metrics."""
    if len(returns) == 0 or returns.std() == 0:
        return {}

    rf_daily = rf_annual / 252
    excess = returns - rf_daily
    n_years = len(returns) / 252

    ann_ret = (1 + returns.mean()) ** 252 - 1
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = (ann_ret - rf_annual) / ann_vol if ann_vol > 0 else 0

    # Sortino
    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = (ann_ret - rf_annual) / downside_vol if downside_vol > 0 else 0

    # Drawdown
    cum_ret = (1 + returns).cumprod()
    running_max = cum_ret.cummax()
    drawdown = cum_ret / running_max - 1
    mdd = drawdown.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Worst year
    yearly = returns.groupby(returns.index.year).apply(lambda x: (1 + x).prod() - 1)
    worst_year = yearly.min()
    worst_year_label = yearly.idxmin()
    best_year = yearly.max()
    best_year_label = yearly.idxmax()

    # Win rate
    win_rate = (returns > 0).mean()

    # Sharpe t-stat
    sharpe_se = 1 / np.sqrt(n_years) if n_years > 0 else 1
    sharpe_t = sharpe / sharpe_se if sharpe_se > 0 else 0

    return {
        "ann_return": round(ann_ret, 4),
        "ann_vol": round(ann_vol, 4),
        "sharpe": round(sharpe, 3),
        "sharpe_t": round(sharpe_t, 2),
        "sortino": round(sortino, 3),
        "mdd": round(mdd, 4),
        "calmar": round(calmar, 3),
        "worst_year": round(worst_year, 4),
        "worst_year_label": int(worst_year_label),
        "best_year": round(best_year, 4),
        "best_year_label": int(best_year_label),
        "win_rate": round(win_rate, 4),
        "n_years": round(n_years, 1),
        "n_obs": len(returns),
        "passes_harvey": sharpe_t > 3.0,
    }


def compute_turnover(weights):
    """Compute annual turnover from weight DataFrame."""
    weight_changes = weights.diff().abs()
    total_turnover = weight_changes.sum(axis=1).sum()
    n_years = len(weights) / 252
    annual_turnover = total_turnover / n_years if n_years > 0 else 0
    return round(annual_turnover, 2)


def net_sharpe(returns, annual_turnover, tx_bps, rf_annual=0.04):
    """Compute Sharpe after transaction costs."""
    tx_annual = annual_turnover * (tx_bps / 10000)
    tx_daily = tx_annual / 252
    net_returns = returns - tx_daily
    ann_ret = (1 + net_returns.mean()) ** 252 - 1
    ann_vol = net_returns.std() * np.sqrt(252)
    return round((ann_ret - rf_annual) / ann_vol, 3) if ann_vol > 0 else 0


# ─────────────────────────────────────────────────
# 3. Drawdown Analysis
# ─────────────────────────────────────────────────

def analyze_drawdowns(returns, threshold=-0.05):
    """Find all drawdowns exceeding threshold, with recovery times."""
    cum_ret = (1 + returns).cumprod()
    running_max = cum_ret.cummax()
    drawdown = cum_ret / running_max - 1

    drawdowns = []
    in_dd = False
    dd_start = None
    dd_trough = None
    dd_min = 0

    for i in range(len(drawdown)):
        dd_val = drawdown.iloc[i]

        if dd_val < 0 and not in_dd:
            in_dd = True
            dd_start = drawdown.index[i]
            dd_min = dd_val
            dd_trough = drawdown.index[i]

        elif in_dd:
            if dd_val < dd_min:
                dd_min = dd_val
                dd_trough = drawdown.index[i]

            if dd_val >= 0:
                # Recovery
                dd_end = drawdown.index[i]
                if dd_min <= threshold:
                    duration_to_trough = (dd_trough - dd_start).days
                    recovery_time = (dd_end - dd_trough).days
                    total_duration = (dd_end - dd_start).days
                    drawdowns.append({
                        "start": str(dd_start.date()),
                        "trough": str(dd_trough.date()),
                        "end": str(dd_end.date()),
                        "depth": round(dd_min, 4),
                        "days_to_trough": duration_to_trough,
                        "recovery_days": recovery_time,
                        "total_days": total_duration,
                    })
                in_dd = False
                dd_min = 0

    # Handle ongoing drawdown
    if in_dd and dd_min <= threshold:
        duration_to_trough = (dd_trough - dd_start).days
        drawdowns.append({
            "start": str(dd_start.date()),
            "trough": str(dd_trough.date()),
            "end": "ongoing",
            "depth": round(dd_min, 4),
            "days_to_trough": duration_to_trough,
            "recovery_days": None,
            "total_days": None,
        })

    return drawdowns


# ─────────────────────────────────────────────────
# 4. Regime Analysis
# ─────────────────────────────────────────────────

def regime_analysis(tsmom_returns, benchmark_returns, vix_series):
    """Analyze performance across market regimes."""
    # Align all series
    common_idx = tsmom_returns.index.intersection(benchmark_returns.index).intersection(vix_series.index)
    tsmom = tsmom_returns.loc[common_idx]
    bench = benchmark_returns.loc[common_idx]
    vix = vix_series.loc[common_idx]

    # Define regimes
    regimes = {}

    # 1. VIX-based regimes
    regimes["Low VIX (<15)"] = vix < 15
    regimes["Medium VIX (15-25)"] = (vix >= 15) & (vix < 25)
    regimes["High VIX (25-35)"] = (vix >= 25) & (vix < 35)
    regimes["Crisis VIX (>35)"] = vix >= 35

    # 2. Market trend regimes (using SPY 200d MA)
    spy_200d = bench.rolling(200).mean()
    regimes["Bull (above 200d MA)"] = bench.rolling(200).apply(
        lambda x: (1+x).prod() - 1, raw=False
    ) > 0
    regimes["Bear (below 200d MA)"] = ~regimes["Bull (above 200d MA)"]

    # 3. Crisis periods
    crisis_periods = {
        "GFC (2008-2009)": ("2008-01-01", "2009-03-31"),
        "Euro Crisis (2011)": ("2011-07-01", "2011-10-31"),
        "China Scare (2015-2016)": ("2015-08-01", "2016-02-29"),
        "Vol-mageddon (2018 Q4)": ("2018-10-01", "2018-12-31"),
        "COVID (2020 Q1)": ("2020-02-01", "2020-03-31"),
        "Rate Hike (2022)": ("2022-01-01", "2022-12-31"),
    }

    results = {}

    for regime_name, mask in regimes.items():
        if isinstance(mask, pd.Series):
            mask = mask.reindex(common_idx).fillna(False)
            t_ret = tsmom[mask]
            b_ret = bench[mask]
        else:
            continue

        if len(t_ret) < 20:
            continue

        t_metrics = compute_metrics(t_ret)
        b_metrics = compute_metrics(b_ret)

        results[regime_name] = {
            "n_days": len(t_ret),
            "tsmom_ann_ret": t_metrics.get("ann_return", None),
            "tsmom_sharpe": t_metrics.get("sharpe", None),
            "tsmom_mdd": t_metrics.get("mdd", None),
            "bench_ann_ret": b_metrics.get("ann_return", None),
            "bench_sharpe": b_metrics.get("sharpe", None),
            "bench_mdd": b_metrics.get("mdd", None),
            "tsmom_excess_ret": round(
                (t_metrics.get("ann_return", 0) or 0) - (b_metrics.get("ann_return", 0) or 0), 4
            ),
        }

    # Crisis periods
    for crisis_name, (start, end) in crisis_periods.items():
        crisis_mask = (common_idx >= start) & (common_idx <= end)
        t_ret = tsmom[crisis_mask]
        b_ret = bench[crisis_mask]

        if len(t_ret) < 10:
            continue

        t_cum = (1 + t_ret).prod() - 1
        b_cum = (1 + b_ret).prod() - 1

        results[crisis_name] = {
            "n_days": len(t_ret),
            "tsmom_cum_ret": round(float(t_cum), 4),
            "bench_cum_ret": round(float(b_cum), 4),
            "tsmom_mdd": round(float((1 + t_ret).cumprod().div((1 + t_ret).cumprod().cummax()).sub(1).min()), 4),
            "bench_mdd": round(float((1 + b_ret).cumprod().div((1 + b_ret).cumprod().cummax()).sub(1).min()), 4),
            "protection": round(float(t_cum - b_cum), 4),
        }

    return results


# ─────────────────────────────────────────────────
# 5. Parameter Sensitivity
# ─────────────────────────────────────────────────

def parameter_sensitivity(prices_dict):
    """Test different lookback/hold/rebalance combinations."""
    configs = [
        # (lookback_months, hold_months, rebal_freq, label)
        (3, 1, "monthly", "3_1_monthly"),
        (6, 1, "monthly", "6_1_monthly"),
        (9, 1, "monthly", "9_1_monthly"),
        (12, 1, "monthly", "12_1_monthly"),
        (6, 1, "bimonthly", "6_1_bimonthly"),
        (6, 1, "quarterly", "6_1_quarterly"),
    ]

    results = {}
    for lookback, hold, freq, label in configs:
        try:
            port_ret, weights, _ = compute_tsmom(
                prices_dict, lookback_months=lookback, hold_months=hold, rebal_freq=freq
            )
            metrics = compute_metrics(port_ret)
            turnover = compute_turnover(weights)
            metrics["turnover"] = turnover
            metrics["net_sharpe_10bps"] = net_sharpe(port_ret, turnover, 10)
            metrics["net_sharpe_20bps"] = net_sharpe(port_ret, turnover, 20)
            results[label] = metrics
        except Exception as e:
            results[label] = {"error": str(e)}

    return results


def start_date_sensitivity(prices_dict, n_offsets=12):
    """Test path dependency by starting 1-12 months later."""
    results = {}
    for offset in range(n_offsets):
        try:
            port_ret, weights, _ = compute_tsmom(
                prices_dict, lookback_months=6, hold_months=1,
                rebal_freq="monthly", start_offset_months=offset
            )
            metrics = compute_metrics(port_ret)
            results[f"offset_{offset}m"] = {
                "sharpe": metrics.get("sharpe"),
                "ann_return": metrics.get("ann_return"),
                "mdd": metrics.get("mdd"),
                "n_obs": metrics.get("n_obs"),
            }
        except Exception as e:
            results[f"offset_{offset}m"] = {"error": str(e)}

    return results


# ─────────────────────────────────────────────────
# 6. Comparison with Platform Strategies
# ─────────────────────────────────────────────────

def compare_with_platform(tsmom_returns, prices_dict):
    """Compare TSMOM 6_1 with existing platform strategies."""
    benchmarks = {
        "SPY B&H": "buy_and_hold_spy",
        "50/50+VT (12/VIX)": "5050_vt",
        "Slow VT (GARCH proxy)": "slow_vt",
        "Risk Parity (SPY+GLD)": "risk_parity",
        "12/VIX Simple": "simple_12vix",
        "Equal Weight (SPY/GLD/TLT)": "equal_weight",
        "60/40 (SPY/TLT)": "6040",
    }

    results = {}
    for name, strat in benchmarks.items():
        try:
            bench_ret = compute_benchmark_returns(prices_dict, strat)
            # Align
            common = tsmom_returns.index.intersection(bench_ret.index)
            bench_ret = bench_ret.loc[common]
            tsmom_aligned = tsmom_returns.loc[common]

            b_metrics = compute_metrics(bench_ret)

            # DM test (TSMOM vs benchmark)
            diff = tsmom_aligned - bench_ret
            dm_mean = diff.mean()
            dm_se = diff.std() / np.sqrt(len(diff))
            dm_t = dm_mean / dm_se if dm_se > 0 else 0

            results[name] = {
                **b_metrics,
                "dm_t_vs_tsmom": round(float(dm_t), 2),
                "tsmom_wins": dm_t > 0,
            }
        except Exception as e:
            results[name] = {"error": str(e)}

    return results


# ─────────────────────────────────────────────────
# 7. Current Positioning
# ─────────────────────────────────────────────────

def current_positioning(prices_dict):
    """What does TSMOM say RIGHT NOW?"""
    spy_close = prices_dict["SPY"]["close"]
    gld_close = prices_dict["GLD"]["close"]
    tlt_close = prices_dict["TLT"]["close"]

    assets = {"SPY": spy_close, "GLD": gld_close, "TLT": tlt_close}
    lookback_days = 6 * 21  # 6 months

    positioning = {}
    for name, series in assets.items():
        current = series.iloc[-1]
        past = series.iloc[-lookback_days] if len(series) >= lookback_days else series.iloc[0]
        mom_return = current / past - 1
        signal = "LONG" if mom_return > 0 else "CASH"

        positioning[name] = {
            "current_price": round(float(current), 2),
            "price_6m_ago": round(float(past), 2),
            "momentum_return_6m": round(float(mom_return), 4),
            "signal": signal,
            "date": str(series.index[-1].date()),
        }

    n_long = sum(1 for v in positioning.values() if v["signal"] == "LONG")
    total_invested = n_long / len(assets)

    # Recommended weights
    weights = {}
    for name, info in positioning.items():
        if info["signal"] == "LONG":
            weights[name] = round(1.0 / len(assets), 4)
        else:
            weights[name] = 0.0
    weights["CASH"] = round(1.0 - sum(weights.values()), 4)

    return {
        "date": str(spy_close.index[-1].date()),
        "assets": positioning,
        "n_long": n_long,
        "total_invested_pct": round(total_invested * 100, 1),
        "recommended_weights": weights,
    }


# ─────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("K255: TSMOM 6_1 Final Validation — Pre-Launch Stress Test")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    results = {
        "experiment": "K255: TSMOM 6_1 Final Validation — Pre-Launch Stress Test",
        "proposed_by": "User",
        "executed_by": "Claude",
        "timestamp": datetime.now().isoformat(),
        "data_source": "yfinance (SPY, GLD, TLT, ^VIX)",
    }

    # ── Fetch Data ──
    print("[1/7] Fetching data...")
    data = fetch_data()
    results["data_info"] = {
        name: {
            "start": str(df.index[0].date()),
            "end": str(df.index[-1].date()),
            "n_rows": len(df),
        }
        for name, df in data.items()
    }

    # ── Test 1: Extended Backtest ──
    print("\n[2/7] Extended backtest (full history)...")
    tsmom_ret, tsmom_weights, tsmom_signals = compute_tsmom(
        data, lookback_months=6, hold_months=1, rebal_freq="monthly"
    )
    tsmom_metrics = compute_metrics(tsmom_ret)
    tsmom_turnover = compute_turnover(tsmom_weights)
    tsmom_metrics["annual_turnover"] = tsmom_turnover

    print(f"  TSMOM 6_1 Full Backtest:")
    print(f"    Period: {tsmom_ret.index[0].date()} to {tsmom_ret.index[-1].date()}")
    print(f"    Sharpe: {tsmom_metrics['sharpe']:.3f} (t={tsmom_metrics['sharpe_t']:.2f})")
    print(f"    Ann Return: {tsmom_metrics['ann_return']*100:.2f}%")
    print(f"    Ann Vol: {tsmom_metrics['ann_vol']*100:.2f}%")
    print(f"    MDD: {tsmom_metrics['mdd']*100:.2f}%")
    print(f"    Calmar: {tsmom_metrics['calmar']:.3f}")
    print(f"    Sortino: {tsmom_metrics['sortino']:.3f}")
    print(f"    Worst Year: {tsmom_metrics['worst_year']*100:.2f}% ({tsmom_metrics['worst_year_label']})")
    print(f"    Best Year: {tsmom_metrics['best_year']*100:.2f}% ({tsmom_metrics['best_year_label']})")
    print(f"    Passes Harvey (t>3): {tsmom_metrics['passes_harvey']}")

    results["test1_extended_backtest"] = tsmom_metrics

    # Benchmarks for extended backtest
    print("\n  Benchmarks:")
    spy_bh_ret = compute_benchmark_returns(data, "buy_and_hold_spy")
    common = tsmom_ret.index.intersection(spy_bh_ret.index)
    spy_bh_metrics = compute_metrics(spy_bh_ret.loc[common])

    vt5050_ret = compute_benchmark_returns(data, "5050_vt")
    common2 = tsmom_ret.index.intersection(vt5050_ret.index)
    vt5050_metrics = compute_metrics(vt5050_ret.loc[common2])

    ew_ret = compute_benchmark_returns(data, "equal_weight")
    common3 = tsmom_ret.index.intersection(ew_ret.index)
    ew_metrics = compute_metrics(ew_ret.loc[common3])

    s6040_ret = compute_benchmark_returns(data, "6040")
    common4 = tsmom_ret.index.intersection(s6040_ret.index)
    s6040_metrics = compute_metrics(s6040_ret.loc[common4])

    print(f"    SPY B&H:      Sharpe={spy_bh_metrics['sharpe']:.3f}, MDD={spy_bh_metrics['mdd']*100:.1f}%")
    print(f"    50/50+VT:     Sharpe={vt5050_metrics['sharpe']:.3f}, MDD={vt5050_metrics['mdd']*100:.1f}%")
    print(f"    Equal Weight: Sharpe={ew_metrics['sharpe']:.3f}, MDD={ew_metrics['mdd']*100:.1f}%")
    print(f"    60/40:        Sharpe={s6040_metrics['sharpe']:.3f}, MDD={s6040_metrics['mdd']*100:.1f}%")

    results["test1_benchmarks"] = {
        "SPY_BH": spy_bh_metrics,
        "5050_VT": vt5050_metrics,
        "equal_weight": ew_metrics,
        "6040": s6040_metrics,
    }

    # ── Test 2: Regime Robustness ──
    print("\n[3/7] Regime robustness analysis...")
    vix_series = data["VIX"]["close"].reindex(tsmom_ret.index).ffill()
    spy_ret_aligned = compute_benchmark_returns(data, "buy_and_hold_spy")
    regime_results = regime_analysis(tsmom_ret, spy_ret_aligned, vix_series)

    print("  Regime Performance (TSMOM vs SPY B&H):")
    for regime, stats in regime_results.items():
        if "tsmom_sharpe" in stats:
            print(f"    {regime:30s}: TSMOM Sharpe={stats['tsmom_sharpe']:.3f}, "
                  f"SPY Sharpe={stats['bench_sharpe']:.3f}, "
                  f"Excess={stats['tsmom_excess_ret']*100:+.1f}%")
        elif "protection" in stats:
            print(f"    {regime:30s}: TSMOM={stats['tsmom_cum_ret']*100:+.1f}%, "
                  f"SPY={stats['bench_cum_ret']*100:+.1f}%, "
                  f"Protection={stats['protection']*100:+.1f}%")

    results["test2_regime_robustness"] = regime_results

    # ── Test 3: Parameter Sensitivity ──
    print("\n[4/7] Parameter sensitivity analysis...")
    param_results = parameter_sensitivity(data)

    print("  Lookback & Rebalance Sensitivity:")
    print(f"  {'Config':<22s} {'Sharpe':>7s} {'t-stat':>7s} {'Return':>8s} {'MDD':>8s} {'Turnover':>9s} {'NetS@10':>8s} {'NetS@20':>8s}")
    print("  " + "-" * 80)
    for config, stats in param_results.items():
        if "error" in stats:
            print(f"  {config:<22s} ERROR: {stats['error']}")
        else:
            print(f"  {config:<22s} {stats['sharpe']:>7.3f} {stats['sharpe_t']:>7.2f} "
                  f"{stats['ann_return']*100:>7.2f}% {stats['mdd']*100:>7.2f}% "
                  f"{stats['turnover']:>8.2f}x {stats['net_sharpe_10bps']:>8.3f} {stats['net_sharpe_20bps']:>8.3f}")

    results["test3_parameter_sensitivity"] = param_results

    # Start date sensitivity
    print("\n  Start Date Sensitivity (0-11 month offsets):")
    start_results = start_date_sensitivity(data, n_offsets=12)
    sharpes = [v["sharpe"] for v in start_results.values() if "sharpe" in v and v["sharpe"] is not None]
    if sharpes:
        print(f"    Sharpe range: [{min(sharpes):.3f}, {max(sharpes):.3f}]")
        print(f"    Sharpe mean: {np.mean(sharpes):.3f}, std: {np.std(sharpes):.3f}")
        for offset, stats in start_results.items():
            if "sharpe" in stats:
                print(f"    {offset}: Sharpe={stats['sharpe']:.3f}, Ret={stats['ann_return']*100:.2f}%, MDD={stats['mdd']*100:.2f}%")

    results["test3_start_date_sensitivity"] = start_results

    # ── Test 4: Turnover and TX Cost ──
    print("\n[5/7] Turnover and transaction cost analysis...")
    tx_levels = [5, 10, 20, 50, 100]
    tx_results = {"annual_turnover": tsmom_turnover}

    print(f"  Annual Turnover: {tsmom_turnover:.2f}x")
    for bps in tx_levels:
        ns = net_sharpe(tsmom_ret, tsmom_turnover, bps)
        tx_results[f"net_sharpe_{bps}bps"] = ns
        print(f"    Net Sharpe @ {bps:3d} bps: {ns:.3f}")

    # Breakeven TX cost
    gross_sharpe = tsmom_metrics["sharpe"]
    if tsmom_turnover > 0:
        # Binary search for breakeven
        lo, hi = 0, 500
        for _ in range(50):
            mid = (lo + hi) / 2
            ns_mid = net_sharpe(tsmom_ret, tsmom_turnover, mid)
            if ns_mid > 0:
                lo = mid
            else:
                hi = mid
        breakeven_bps = round((lo + hi) / 2, 1)
    else:
        breakeven_bps = float("inf")

    tx_results["breakeven_bps"] = breakeven_bps
    print(f"    Breakeven TX cost: {breakeven_bps:.1f} bps")

    results["test4_turnover_tx"] = tx_results

    # ── Test 5: Drawdown Analysis ──
    print("\n[6/7] Drawdown analysis (all >5%)...")
    drawdowns = analyze_drawdowns(tsmom_ret, threshold=-0.05)

    print(f"  Found {len(drawdowns)} drawdowns > 5%:")
    for i, dd in enumerate(drawdowns):
        rec = f"{dd['recovery_days']}d" if dd["recovery_days"] is not None else "ongoing"
        print(f"    #{i+1}: {dd['depth']*100:.1f}% ({dd['start']} to {dd['end']}) "
              f"trough@{dd['trough']}, recovery={rec}")

    # Max underwater duration
    cum_ret = (1 + tsmom_ret).cumprod()
    running_max = cum_ret.cummax()
    underwater = cum_ret < running_max
    if underwater.any():
        uw_groups = (~underwater).cumsum()
        uw_durations = underwater.groupby(uw_groups).sum()
        max_uw_days = int(uw_durations.max())
    else:
        max_uw_days = 0

    print(f"  Max underwater duration: {max_uw_days} trading days ({max_uw_days/21:.1f} months)")

    results["test5_drawdowns"] = {
        "all_drawdowns": drawdowns,
        "n_drawdowns_gt_5pct": len(drawdowns),
        "max_underwater_days": max_uw_days,
        "max_underwater_months": round(max_uw_days / 21, 1),
    }

    # ── Test 6: Current Positioning ──
    print("\n[7/7] Current positioning...")
    positioning = current_positioning(data)

    print(f"  Date: {positioning['date']}")
    print(f"  Assets with positive 6m momentum: {positioning['n_long']}/3")
    print(f"  Total invested: {positioning['total_invested_pct']:.1f}%")
    for asset, info in positioning["assets"].items():
        print(f"    {asset}: ${info['current_price']:.2f} → "
              f"6m return={info['momentum_return_6m']*100:+.1f}% → {info['signal']}")
    print(f"  Recommended weights: {positioning['recommended_weights']}")

    results["test6_current_positioning"] = positioning

    # ── Test 7: Comparison with Platform Strategies ──
    print("\n[BONUS] Comparison with platform strategies...")
    platform_comparison = compare_with_platform(tsmom_ret, data)

    print(f"  {'Strategy':<28s} {'Sharpe':>7s} {'Return':>8s} {'MDD':>8s} {'DM-t':>7s} {'TSMOM wins':>11s}")
    print("  " + "-" * 75)

    # Add TSMOM itself
    print(f"  {'>>> TSMOM 6_1 <<<':<28s} {tsmom_metrics['sharpe']:>7.3f} "
          f"{tsmom_metrics['ann_return']*100:>7.2f}% {tsmom_metrics['mdd']*100:>7.2f}% "
          f"{'---':>7s} {'---':>11s}")

    for name, stats in platform_comparison.items():
        if "error" in stats:
            print(f"  {name:<28s} ERROR: {stats['error']}")
        else:
            wins = "YES" if stats.get("tsmom_wins") else "NO"
            print(f"  {name:<28s} {stats['sharpe']:>7.3f} "
                  f"{stats['ann_return']*100:>7.2f}% {stats['mdd']*100:>7.2f}% "
                  f"{stats['dm_t_vs_tsmom']:>7.2f} {wins:>11s}")

    results["test7_platform_comparison"] = platform_comparison

    # ── Summary & Launch Decision ──
    print("\n" + "=" * 70)
    print("LAUNCH READINESS ASSESSMENT")
    print("=" * 70)

    checks = []

    # Check 1: Harvey threshold
    passes_harvey = tsmom_metrics.get("passes_harvey", False)
    checks.append(("Harvey t>3.0", passes_harvey, f"t={tsmom_metrics['sharpe_t']:.2f}"))

    # Check 2: Positive Sharpe across all lookbacks
    all_param_positive = all(
        v.get("sharpe", 0) > 0
        for v in param_results.values()
        if "error" not in v
    )
    checks.append(("All lookbacks positive Sharpe", all_param_positive, ""))

    # Check 3: 6_1 is robustly best (or close)
    param_sharpes = {k: v.get("sharpe", 0) for k, v in param_results.items() if "error" not in v}
    best_param = max(param_sharpes, key=param_sharpes.get) if param_sharpes else None
    is_best_or_close = (
        best_param == "6_1_monthly" or
        abs(param_sharpes.get("6_1_monthly", 0) - max(param_sharpes.values())) < 0.05
    ) if param_sharpes else False
    checks.append(("6_1 robustly best", is_best_or_close,
                    f"best={best_param} ({param_sharpes.get(best_param, 0):.3f})"))

    # Check 4: Path dependency low
    if sharpes:
        sharpe_cv = np.std(sharpes) / np.mean(sharpes) if np.mean(sharpes) > 0 else float("inf")
        low_path_dep = sharpe_cv < 0.2
    else:
        sharpe_cv = float("inf")
        low_path_dep = False
    checks.append(("Low path dependency (CV<0.2)", low_path_dep, f"CV={sharpe_cv:.3f}"))

    # Check 5: Net Sharpe > 0 at 50 bps
    net_50 = tx_results.get("net_sharpe_50bps", 0)
    checks.append(("Net Sharpe > 0 @ 50bps", net_50 > 0, f"net={net_50:.3f}"))

    # Check 6: MDD better than SPY
    spy_mdd = spy_bh_metrics.get("mdd", -1)
    tsmom_mdd = tsmom_metrics.get("mdd", -1)
    checks.append(("MDD < SPY B&H", tsmom_mdd > spy_mdd, f"TSMOM={tsmom_mdd*100:.1f}% vs SPY={spy_mdd*100:.1f}%"))

    # Check 7: Crisis protection (at least 3/6 crises)
    crisis_protection = sum(
        1 for k, v in regime_results.items()
        if "protection" in v and v["protection"] > 0
    )
    total_crises = sum(1 for k, v in regime_results.items() if "protection" in v)
    checks.append((f"Crisis protection >=50%", crisis_protection >= total_crises/2 if total_crises > 0 else False,
                    f"{crisis_protection}/{total_crises} crises"))

    # Check 8: Beats 50/50+VT
    tsmom_sharpe = tsmom_metrics.get("sharpe", 0)
    vt5050_sharpe = vt5050_metrics.get("sharpe", 0)
    checks.append(("Beats 50/50+VT Sharpe", tsmom_sharpe > vt5050_sharpe,
                    f"TSMOM={tsmom_sharpe:.3f} vs 5050VT={vt5050_sharpe:.3f}"))

    n_pass = sum(1 for _, passed, _ in checks)
    n_total = len(checks)

    for check_name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {check_name}: {detail}")

    launch_ready = all(passed for _, passed, _ in checks)
    results["launch_assessment"] = {
        "checks": [{
            "name": name,
            "passed": passed,
            "detail": detail,
        } for name, passed, detail in checks],
        "n_pass": sum(1 for _, p, _ in checks if p),
        "n_total": n_total,
        "launch_ready": launch_ready,
    }

    print(f"\n  Overall: {sum(1 for _, p, _ in checks if p)}/{n_total} checks passed")
    if launch_ready:
        print("  >>> LAUNCH APPROVED <<<")
    else:
        failed = [name for name, passed, _ in checks if not passed]
        print(f"  >>> LAUNCH BLOCKED: {', '.join(failed)} <<<")

    # Save results
    output_path = Path("storage/experiments/k255_tsmom_final_validation.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {output_path}")

    return results


if __name__ == "__main__":
    main()
