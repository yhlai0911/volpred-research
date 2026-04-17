#!/usr/bin/env python3
"""
K627: Momentum + VT Hybrid Strategy
======================================
Can combining VIX-based VT with price momentum improve risk-adjusted returns?

Motivation:
  Our VT strategies use VIX for risk scaling. Momentum (trend-following) is a
  well-documented factor. This experiment tests whether momentum overlays
  improve the core 12/VIX strategy.

Prior knowledge:
  - K (N102): Multi-factor VIX enhancements provide marginal improvement
    (+0.008 to +0.022 Sharpe). 12/VIX single-factor confirmed sufficient.
  - K (N74/N76): VT alpha decomposition: 88% market + 6% trend + 6% variance mgmt.
    VT is NOT trend following (Simpson's paradox). Trend effect concentrated
    in calm markets/crises, absent in moderate-vol.
  - K (VIX Momentum): VIX 5d momentum FAILED cross-validation (avg delta +0.005).
  - J2: Dynamic multi-asset VT (SPY+TLT) underperformed pure SPY VT.

Strategy variants (OOS: 2023-01-01 to 2024-12-31):
  a. Baseline: 12/VIX → w_t = min(12/VIX_t, 1.5) into SPY, rest cash
  b. VT + SMA Filter: 12/VIX ONLY when SPY > 200d SMA, else 100% cash
  c. VT + Dual Momentum: 12/VIX into whichever of SPY/GLD has higher 12M return
  d. VT + MACD Boost: 12/VIX base, +20% when MACD bullish, -20% bearish
  e. VT + Combined: SMA filter + dual momentum (majority vote)
  f. Pure 50/50 SPY/GLD (existing strategy reference)
  g. Buy-and-hold SPY (benchmark)

Evaluation:
  - Sharpe, MDD, Calmar, total return, trades/year, TX cost impact
  - Bootstrap Sharpe difference (5000 reps) vs baseline

References:
  - Moreira & Muir (2017) "Volatility-Managed Portfolios", JoF 72(4):1611-1644
  - Antonacci (2014) "Dual Momentum Investing", McGraw-Hill
  - Moskowitz, Ooi & Pedersen (2012) "Time series momentum", JFE 104(2):228-250
  - Hood & Raughtigan (2024/2025) "VT alpha from implicit trend-following"

Data source: yfinance (SPY, GLD, ^VIX), 2006-01-01 to 2026-03-27
Transaction cost: 2bp round-trip for US ETFs (per references/transaction-costs.md)
"""

import json
import sys
import os
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

warnings.filterwarnings('ignore')

# === Transaction cost constants (from references/transaction-costs.md) ===
US_ROUND_TRIP_BPS = 2.0  # 2bp round-trip for US ETFs
TX_COST = US_ROUND_TRIP_BPS / 10000  # 0.0002

# === Parameters ===
DATA_START = '2006-01-01'
DATA_END = '2026-03-27'
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
VIX_TARGET = 12.0
MAX_WEIGHT = 1.5
BOOTSTRAP_REPS = 5000
SMA_WINDOW = 200
MOMENTUM_MONTHS = 12  # ~252 trading days
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
MACD_BOOST = 0.20  # +/- 20%


def download_data():
    """Download SPY, GLD, ^VIX from yfinance."""
    import yfinance as yf

    tickers = ['SPY', 'GLD', '^VIX']
    data = {}
    for ticker in tickers:
        print(f"  Downloading {ticker}...")
        df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
        if hasattr(df.columns, 'droplevel') and isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        data[ticker] = df

    return data


def prepare_signals(data):
    """Compute all momentum signals (no lookahead)."""
    spy = data['SPY']['Close'].copy()
    gld = data['GLD']['Close'].copy()
    vix = data['^VIX']['Close'].copy()

    # Align all to common dates
    common_idx = spy.index.intersection(gld.index).intersection(vix.index)
    spy = spy.loc[common_idx].sort_index()
    gld = gld.loc[common_idx].sort_index()
    vix = vix.loc[common_idx].sort_index()

    # Daily returns (for portfolio simulation)
    spy_ret = spy.pct_change()
    gld_ret = gld.pct_change()

    # === Momentum signals (all computed at time t, used at t+1) ===

    # 1. SMA crossover: SPY > 200-day SMA
    sma_200 = spy.rolling(SMA_WINDOW).mean()
    sma_bullish = (spy > sma_200).astype(int)

    # 2. Return momentum: SPY 12-month return > 0
    mom_252 = spy.pct_change(252)
    ret_mom_bullish = (mom_252 > 0).astype(int)

    # 3. Dual momentum: SPY 12M return > GLD 12M return
    spy_12m = spy.pct_change(252)
    gld_12m = gld.pct_change(252)
    dual_mom_spy = (spy_12m > gld_12m).astype(int)  # 1=hold SPY, 0=hold GLD

    # 4. MACD: 12-day EMA > 26-day EMA
    ema_fast = spy.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = spy.ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    macd_bullish = (macd_line > macd_signal_line).astype(int)

    # 5. VIX weight: min(12/VIX, 1.5)
    vix_weight = np.minimum(VIX_TARGET / vix, MAX_WEIGHT)

    signals = pd.DataFrame({
        'spy_close': spy,
        'gld_close': gld,
        'vix': vix,
        'spy_ret': spy_ret,
        'gld_ret': gld_ret,
        'vix_weight': vix_weight,
        'sma_bullish': sma_bullish,
        'ret_mom_bullish': ret_mom_bullish,
        'dual_mom_spy': dual_mom_spy,
        'macd_bullish': macd_bullish,
    }, index=common_idx)

    return signals


def simulate_strategy(signals, strategy_name, oos_start, oos_end):
    """
    Simulate a strategy and return daily returns with TX costs.

    All signals at time t determine position for t+1 (no lookahead).
    Transaction costs applied when position changes.
    """
    oos_mask = (signals.index >= oos_start) & (signals.index <= oos_end)
    df = signals[oos_mask].copy()

    if len(df) == 0:
        return pd.Series(dtype=float), 0

    n = len(df)
    daily_returns = np.zeros(n)
    position_changes = 0

    # Track previous weights for TX cost
    prev_spy_w = 0.0
    prev_gld_w = 0.0

    for i in range(1, n):
        # Signals from previous day (t-1) determine today's position
        vw = df['vix_weight'].iloc[i-1]
        sma = df['sma_bullish'].iloc[i-1]
        dual = df['dual_mom_spy'].iloc[i-1]
        macd = df['macd_bullish'].iloc[i-1]
        ret_mom = df['ret_mom_bullish'].iloc[i-1]

        spy_w = 0.0
        gld_w = 0.0

        if strategy_name == 'baseline_12vix':
            # a. Baseline: 12/VIX into SPY
            spy_w = vw
            gld_w = 0.0

        elif strategy_name == 'vt_sma_filter':
            # b. VT + SMA Filter: 12/VIX only when SPY > 200d SMA
            if sma == 1:
                spy_w = vw
            else:
                spy_w = 0.0
            gld_w = 0.0

        elif strategy_name == 'vt_dual_momentum':
            # c. VT + Dual Momentum: 12/VIX into winner of SPY vs GLD (12M)
            if dual == 1:
                spy_w = vw
                gld_w = 0.0
            else:
                spy_w = 0.0
                gld_w = vw

        elif strategy_name == 'vt_macd_boost':
            # d. VT + MACD Boost: 12/VIX +/-20% based on MACD
            if macd == 1:
                spy_w = vw * (1.0 + MACD_BOOST)
            else:
                spy_w = vw * (1.0 - MACD_BOOST)
            spy_w = min(spy_w, MAX_WEIGHT)
            gld_w = 0.0

        elif strategy_name == 'vt_combined':
            # e. Combined: SMA filter + dual momentum (majority vote)
            # Signals: sma_bullish, ret_mom_bullish, macd_bullish
            bullish_count = sma + ret_mom + macd

            if bullish_count >= 2:  # majority bullish
                if dual == 1:
                    spy_w = vw
                    gld_w = 0.0
                else:
                    spy_w = 0.0
                    gld_w = vw
            else:
                # majority bearish → reduce to 50% of VT weight
                spy_w = vw * 0.5
                gld_w = 0.0

        elif strategy_name == 'pure_5050':
            # f. 50/50 SPY/GLD (static)
            spy_w = 0.5
            gld_w = 0.5

        elif strategy_name == 'buy_hold_spy':
            # g. Buy-and-hold SPY
            spy_w = 1.0
            gld_w = 0.0

        # Calculate portfolio return
        spy_r = df['spy_ret'].iloc[i]
        gld_r = df['gld_ret'].iloc[i]

        # Handle NaN returns
        if np.isnan(spy_r):
            spy_r = 0.0
        if np.isnan(gld_r):
            gld_r = 0.0

        port_ret = spy_w * spy_r + gld_w * gld_r

        # Transaction cost: proportional to absolute weight change
        weight_change = abs(spy_w - prev_spy_w) + abs(gld_w - prev_gld_w)
        tx_cost = weight_change * TX_COST

        if weight_change > 0.001:  # meaningful position change
            position_changes += 1

        daily_returns[i] = port_ret - tx_cost
        prev_spy_w = spy_w
        prev_gld_w = gld_w

    ret_series = pd.Series(daily_returns, index=df.index)
    return ret_series, position_changes


def compute_metrics(returns, position_changes, n_years):
    """Compute strategy performance metrics."""
    if len(returns) == 0 or returns.std() == 0:
        return {
            'sharpe': 0.0, 'mdd': 0.0, 'calmar': 0.0,
            'total_return': 0.0, 'annual_return': 0.0,
            'annual_vol': 0.0, 'trades_per_year': 0.0,
            'total_tx_cost_bps': 0.0
        }

    # Annualized Sharpe (assuming 0% risk-free for simplicity)
    sharpe = returns.mean() / returns.std() * np.sqrt(252)

    # Max drawdown
    cum_ret = (1 + returns).cumprod()
    rolling_max = cum_ret.cummax()
    drawdown = (cum_ret - rolling_max) / rolling_max
    mdd = drawdown.min()

    # Calmar ratio
    annual_return = cum_ret.iloc[-1] ** (252 / len(returns)) - 1
    calmar = annual_return / abs(mdd) if mdd != 0 else 0.0

    # Total return
    total_return = cum_ret.iloc[-1] - 1

    # Annual volatility
    annual_vol = returns.std() * np.sqrt(252)

    # Trades per year
    trades_per_year = position_changes / n_years if n_years > 0 else 0

    # Total TX cost (rough estimate)
    total_tx_bps = position_changes * US_ROUND_TRIP_BPS

    return {
        'sharpe': round(sharpe, 4),
        'mdd': round(mdd, 4),
        'calmar': round(calmar, 4),
        'total_return': round(total_return, 4),
        'annual_return': round(annual_return, 4),
        'annual_vol': round(annual_vol, 4),
        'trades_per_year': round(trades_per_year, 1),
        'total_tx_cost_bps': round(total_tx_bps, 1)
    }


def bootstrap_sharpe_diff(returns_a, returns_b, n_reps=5000, seed=42):
    """
    Bootstrap test for Sharpe ratio difference.
    H0: Sharpe(A) = Sharpe(B)
    Returns: mean diff, std, p-value (two-sided), CI
    """
    rng = np.random.RandomState(seed)
    n = len(returns_a)

    # Observed Sharpe difference
    sharpe_a = returns_a.mean() / returns_a.std() * np.sqrt(252) if returns_a.std() > 0 else 0
    sharpe_b = returns_b.mean() / returns_b.std() * np.sqrt(252) if returns_b.std() > 0 else 0
    obs_diff = sharpe_b - sharpe_a

    # Bootstrap
    boot_diffs = np.zeros(n_reps)
    ra = returns_a.values
    rb = returns_b.values

    for rep in range(n_reps):
        idx = rng.choice(n, size=n, replace=True)
        boot_a = ra[idx]
        boot_b = rb[idx]

        sa = boot_a.mean() / boot_a.std() * np.sqrt(252) if boot_a.std() > 0 else 0
        sb = boot_b.mean() / boot_b.std() * np.sqrt(252) if boot_b.std() > 0 else 0
        boot_diffs[rep] = sb - sa

    # Two-sided p-value under H0 (centered bootstrap)
    centered = boot_diffs - boot_diffs.mean()
    p_value = np.mean(np.abs(centered) >= np.abs(obs_diff))

    ci_lo = np.percentile(boot_diffs, 2.5)
    ci_hi = np.percentile(boot_diffs, 97.5)

    return {
        'obs_diff': round(obs_diff, 4),
        'boot_mean': round(boot_diffs.mean(), 4),
        'boot_std': round(boot_diffs.std(), 4),
        'p_value': round(p_value, 4),
        'ci_95': [round(ci_lo, 4), round(ci_hi, 4)],
        'significant_5pct': bool(p_value < 0.05),
        'significant_10pct': bool(p_value < 0.10)
    }


def main():
    print("=" * 70)
    print("K627: Momentum + VT Hybrid Strategy")
    print("=" * 70)

    # 1. Download data
    print("\n[1] Downloading data...")
    data = download_data()

    for ticker, df in data.items():
        print(f"  {ticker}: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

    # 2. Prepare signals
    print("\n[2] Computing momentum signals...")
    signals = prepare_signals(data)
    print(f"  Common dates: {len(signals)} rows")
    print(f"  Date range: {signals.index[0].strftime('%Y-%m-%d')} to {signals.index[-1].strftime('%Y-%m-%d')}")

    # Signal summary in OOS period
    oos_mask = (signals.index >= OOS_START) & (signals.index <= OOS_END)
    oos_signals = signals[oos_mask]
    print(f"\n  OOS period ({OOS_START} to {OOS_END}): {len(oos_signals)} trading days")
    print(f"  SMA bullish %: {oos_signals['sma_bullish'].mean():.1%}")
    print(f"  12M momentum bullish %: {oos_signals['ret_mom_bullish'].mean():.1%}")
    print(f"  Dual momentum (SPY>GLD) %: {oos_signals['dual_mom_spy'].mean():.1%}")
    print(f"  MACD bullish %: {oos_signals['macd_bullish'].mean():.1%}")
    print(f"  VIX mean: {oos_signals['vix'].mean():.1f}, median: {oos_signals['vix'].median():.1f}")
    print(f"  Avg VIX weight: {oos_signals['vix_weight'].mean():.3f}")

    # 3. Simulate all strategies
    print("\n[3] Simulating strategies...")
    strategies = {
        'baseline_12vix': 'a. Baseline 12/VIX',
        'vt_sma_filter': 'b. VT + SMA Filter',
        'vt_dual_momentum': 'c. VT + Dual Momentum',
        'vt_macd_boost': 'd. VT + MACD Boost',
        'vt_combined': 'e. VT + Combined',
        'pure_5050': 'f. Pure 50/50 SPY/GLD',
        'buy_hold_spy': 'g. Buy-Hold SPY',
    }

    n_oos_days = len(oos_signals)
    n_years = n_oos_days / 252

    results = {}
    returns_dict = {}

    for key, label in strategies.items():
        ret, n_trades = simulate_strategy(signals, key, OOS_START, OOS_END)
        metrics = compute_metrics(ret, n_trades, n_years)
        results[key] = {'label': label, 'metrics': metrics}
        returns_dict[key] = ret
        print(f"  {label}: Sharpe={metrics['sharpe']:.3f}, MDD={metrics['mdd']:.1%}, "
              f"Total={metrics['total_return']:.1%}, Trades/yr={metrics['trades_per_year']:.0f}")

    # 4. Comparison table
    print("\n" + "=" * 100)
    print(f"{'Strategy':<30} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'Total':>8} {'Ann.Ret':>8} {'Ann.Vol':>8} {'Tr/yr':>6} {'TX(bp)':>7}")
    print("-" * 100)
    for key, label in strategies.items():
        m = results[key]['metrics']
        print(f"{label:<30} {m['sharpe']:>8.3f} {m['mdd']:>7.1%} {m['calmar']:>8.3f} "
              f"{m['total_return']:>7.1%} {m['annual_return']:>7.1%} {m['annual_vol']:>7.1%} "
              f"{m['trades_per_year']:>6.0f} {m['total_tx_cost_bps']:>7.1f}")
    print("=" * 100)

    # 5. Bootstrap Sharpe difference tests
    print("\n[4] Bootstrap Sharpe difference tests (vs Baseline 12/VIX)...")
    print(f"    {BOOTSTRAP_REPS} bootstrap replications\n")

    baseline_ret = returns_dict['baseline_12vix']
    boot_results = {}

    test_strategies = ['vt_sma_filter', 'vt_dual_momentum', 'vt_macd_boost', 'vt_combined', 'pure_5050']

    print(f"{'Strategy':<30} {'ΔSharpe':>8} {'Boot Mean':>10} {'p-value':>8} {'95% CI':>20} {'Sig@5%':>7}")
    print("-" * 90)

    for key in test_strategies:
        test_ret = returns_dict[key]
        boot = bootstrap_sharpe_diff(baseline_ret, test_ret, n_reps=BOOTSTRAP_REPS)
        boot_results[key] = boot

        ci_str = f"[{boot['ci_95'][0]:+.3f}, {boot['ci_95'][1]:+.3f}]"
        sig_str = "YES*" if boot['significant_5pct'] else "no"

        print(f"{strategies[key]:<30} {boot['obs_diff']:>+8.3f} {boot['boot_mean']:>+10.3f} "
              f"{boot['p_value']:>8.3f} {ci_str:>20} {sig_str:>7}")

    print("-" * 90)

    # 6. MDD comparison (key question: does SMA filter reduce drawdowns?)
    print("\n[5] Drawdown analysis:")
    baseline_mdd = results['baseline_12vix']['metrics']['mdd']
    for key in ['vt_sma_filter', 'vt_dual_momentum', 'vt_combined']:
        strat_mdd = results[key]['metrics']['mdd']
        mdd_change = strat_mdd - baseline_mdd
        print(f"  {strategies[key]}: MDD={strat_mdd:.1%} (vs baseline {baseline_mdd:.1%}, "
              f"change={mdd_change:+.1%})")

    # 7. Signal overlap analysis
    print("\n[6] Signal overlap (OOS period):")
    sma = oos_signals['sma_bullish'].values
    ret_mom = oos_signals['ret_mom_bullish'].values
    macd = oos_signals['macd_bullish'].values
    dual = oos_signals['dual_mom_spy'].values

    all_bullish = ((sma == 1) & (ret_mom == 1) & (macd == 1)).mean()
    all_bearish = ((sma == 0) & (ret_mom == 0) & (macd == 0)).mean()
    mixed = 1 - all_bullish - all_bearish

    print(f"  All signals bullish: {all_bullish:.1%}")
    print(f"  All signals bearish: {all_bearish:.1%}")
    print(f"  Mixed signals: {mixed:.1%}")
    print(f"  SMA-MACD agreement: {(sma == macd).mean():.1%}")
    print(f"  SMA-RetMom agreement: {(sma == ret_mom).mean():.1%}")

    # 8. Summary & interpretation
    print("\n" + "=" * 70)
    print("SUMMARY & INTERPRETATION")
    print("=" * 70)

    best_sharpe_key = max(results.keys(), key=lambda k: results[k]['metrics']['sharpe'])
    best_sharpe = results[best_sharpe_key]['metrics']['sharpe']
    baseline_sharpe = results['baseline_12vix']['metrics']['sharpe']

    print(f"\n  Best Sharpe: {strategies[best_sharpe_key]} ({best_sharpe:.3f})")
    print(f"  Baseline 12/VIX Sharpe: {baseline_sharpe:.3f}")

    # Check if any improvement is statistically significant
    any_significant = any(boot_results[k]['significant_5pct'] for k in boot_results)
    print(f"\n  Any statistically significant improvement? {'YES' if any_significant else 'NO'}")

    if not any_significant:
        print("  → Consistent with prior findings: 12/VIX is the irreducible kernel.")
        print("    Momentum overlays add complexity without reliable improvement.")

    # Check if SMA filter reduces MDD
    sma_mdd = results['vt_sma_filter']['metrics']['mdd']
    base_mdd = results['baseline_12vix']['metrics']['mdd']
    if abs(sma_mdd) < abs(base_mdd):
        mdd_reduction = (abs(base_mdd) - abs(sma_mdd)) / abs(base_mdd) * 100
        print(f"\n  SMA filter reduces MDD by {mdd_reduction:.1f}%")
        print(f"    ({base_mdd:.1%} → {sma_mdd:.1%})")
        sma_sharpe_diff = results['vt_sma_filter']['metrics']['sharpe'] - baseline_sharpe
        print(f"    Sharpe change: {sma_sharpe_diff:+.3f}")
        if sma_sharpe_diff < -0.1:
            print("    BUT at the cost of significantly lower Sharpe — not recommended.")
        else:
            print("    Potential value for risk-averse investors (worth cross-OOS validation).")
    else:
        print(f"\n  SMA filter does NOT reduce MDD ({base_mdd:.1%} vs {sma_mdd:.1%})")

    # 9. Save results
    print("\n[7] Saving results...")

    output = {
        'experiment_id': 'K627',
        'title': 'Momentum + VT Hybrid Strategy',
        'timestamp': datetime.now().isoformat(),
        'data_source': 'yfinance',
        'data_period': f'{DATA_START} to {DATA_END}',
        'oos_period': f'{OOS_START} to {OOS_END}',
        'oos_trading_days': n_oos_days,
        'parameters': {
            'vix_target': VIX_TARGET,
            'max_weight': MAX_WEIGHT,
            'sma_window': SMA_WINDOW,
            'momentum_months': MOMENTUM_MONTHS,
            'macd_fast': MACD_FAST,
            'macd_slow': MACD_SLOW,
            'macd_signal': MACD_SIGNAL,
            'macd_boost': MACD_BOOST,
            'tx_cost_bps': US_ROUND_TRIP_BPS,
            'bootstrap_reps': BOOTSTRAP_REPS,
        },
        'signal_summary_oos': {
            'sma_bullish_pct': round(oos_signals['sma_bullish'].mean(), 4),
            'ret_mom_bullish_pct': round(oos_signals['ret_mom_bullish'].mean(), 4),
            'dual_mom_spy_pct': round(oos_signals['dual_mom_spy'].mean(), 4),
            'macd_bullish_pct': round(oos_signals['macd_bullish'].mean(), 4),
            'vix_mean': round(oos_signals['vix'].mean(), 2),
            'avg_vix_weight': round(oos_signals['vix_weight'].mean(), 4),
            'all_bullish_pct': round(float(all_bullish), 4),
            'all_bearish_pct': round(float(all_bearish), 4),
            'mixed_pct': round(float(mixed), 4),
        },
        'strategy_results': {},
        'bootstrap_tests': {},
        'conclusions': [],
        'references': [
            'Moreira & Muir (2017) "Volatility-Managed Portfolios", JoF 72(4):1611-1644',
            'Antonacci (2014) "Dual Momentum Investing", McGraw-Hill',
            'Moskowitz, Ooi & Pedersen (2012) "Time series momentum", JFE 104(2):228-250',
            'Hood & Raughtigan (2024/2025) "VT alpha from implicit trend-following"',
        ],
    }

    for key, label in strategies.items():
        output['strategy_results'][key] = {
            'label': label,
            **results[key]['metrics']
        }

    for key in test_strategies:
        output['bootstrap_tests'][key] = {
            'label': strategies[key],
            'vs': 'baseline_12vix',
            **boot_results[key]
        }

    # Generate conclusions
    conclusions = []

    if not any_significant:
        conclusions.append(
            "No momentum overlay produces a statistically significant improvement "
            "over baseline 12/VIX (all p>0.05). Confirms the 'irreducible kernel' finding."
        )

    if abs(sma_mdd) < abs(base_mdd):
        mdd_red = (abs(base_mdd) - abs(sma_mdd)) / abs(base_mdd) * 100
        sma_delta_sharpe = results['vt_sma_filter']['metrics']['sharpe'] - baseline_sharpe
        conclusions.append(
            f"SMA filter reduces MDD by {mdd_red:.1f}% "
            f"({base_mdd:.1%} → {sma_mdd:.1%}) "
            f"with Sharpe change of {sma_delta_sharpe:+.3f}. "
            f"{'Worth investigating for risk-averse investors.' if sma_delta_sharpe >= -0.1 else 'But at unacceptable Sharpe cost.'}"
        )
    else:
        conclusions.append(
            f"SMA filter does NOT reduce MDD ({base_mdd:.1%} vs {sma_mdd:.1%}). "
            "No protective value in this OOS period."
        )

    dual_sharpe = results['vt_dual_momentum']['metrics']['sharpe']
    conclusions.append(
        f"Dual momentum (Antonacci-style) Sharpe={dual_sharpe:.3f} vs "
        f"baseline {baseline_sharpe:.3f}. "
        f"{'Marginal improvement' if dual_sharpe > baseline_sharpe else 'No improvement'} — "
        f"asset switching adds complexity without reliable benefit for VT."
    )

    conclusions.append(
        f"OOS 2023-2024 was predominantly bullish (SMA bullish {oos_signals['sma_bullish'].mean():.0%} of days, "
        f"12M momentum bullish {oos_signals['ret_mom_bullish'].mean():.0%}). "
        f"Momentum filters rarely triggered 'bearish' regime, limiting their discriminative power."
    )

    conclusions.append(
        "Limitation: Single OOS period (2023-2024). Cross-OOS validation needed "
        "before any definitive conclusion. This period was predominantly low-vol bullish, "
        "which may understate momentum filter value during bear markets."
    )

    output['conclusions'] = conclusions

    # Save
    results_path = Path(__file__).parent / 'k627_results.json'
    with open(results_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"  Saved to {results_path}")

    # Print conclusions
    print("\n" + "=" * 70)
    print("CONCLUSIONS")
    print("=" * 70)
    for i, c in enumerate(conclusions, 1):
        print(f"\n  {i}. {c}")

    print("\n" + "=" * 70)
    print("K627 complete.")
    print("=" * 70)

    return output


if __name__ == '__main__':
    main()
