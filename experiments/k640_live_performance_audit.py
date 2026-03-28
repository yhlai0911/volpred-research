"""
K640: Live Performance Audit (2025-01 to 2026-03)
==================================================
Audit of all VolPred strategies using LIVE paper trading data.
This is the ultimate test: how do strategies perform on truly unseen data,
in a period with tariff uncertainty, VIX spikes, and market turmoil?

Data source: storage/paper_trading.json (live tracked portfolio returns)
             storage/strategy_metrics.json (backtest metrics for comparison)
             yfinance (VIX, SPY, TLT for benchmarks and regime analysis)
Period: 2025-01-02 to 2026-03-27 (~15 months)

References:
- Harvey, C. R. (2016). Lucky factors. Journal of Investment Management.
- DeMiguel, V., Garlappi, L., & Uppal, R. (2009). Optimal versus naive
  diversification. Review of Financial Studies, 22(5), 1915-1953.
"""

import json
import numpy as np
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings('ignore')

# ─── Configuration ───────────────────────────────────────────────
LIVE_START = "2025-01-02"
LIVE_END = "2026-03-27"
ANNUALIZE_FACTOR = 252  # trading days per year
TX_COST_BPS = 10  # 10 bps round-trip transaction cost assumption

# Active strategies (from STRATEGY_REGISTRY)
ACTIVE_STRATEGIES = [
    'slow_vt', 'risk_parity', 'simple_12vix', 'recommended_5050',
    'taiwan_8.63vix', 'vix_leading_guard', 'vix_cond_leverage',
    'taiwan_hybrid_leverage', 'piecewise_conservative', 'fear_dca'
]

# All strategies including inactive (for completeness)
ALL_STRATEGIES = ACTIVE_STRATEGIES + [
    'taiwan_spy_momentum', 'tz_tw_jp_5050', 'global_vt_tz', 'adaptive_tier'
]

STRATEGY_DISPLAY = {
    'slow_vt': 'GARCH VT (SPY)',
    'risk_parity': 'Risk Parity (SPY+GLD)',
    'simple_12vix': '12/VIX (SPY)',
    'recommended_5050': '50/50 SPY/GLD',
    'taiwan_8.63vix': '台灣 VT (0050.TW)',
    'taiwan_spy_momentum': '台股動量 (0050.TW)',
    'tz_tw_jp_5050': 'TW+JP 50/50 TZ',
    'global_vt_tz': 'Global US VT + TW TZ',
    'vix_leading_guard': 'VIX+景氣領先 (0050.TW)',
    'vix_cond_leverage': 'VIX 條件槓桿',
    'taiwan_hybrid_leverage': '台股混合槓桿',
    'piecewise_conservative': '保守型 VT (Piecewise)',
    'fear_dca': '恐慌加碼定期定額',
    'adaptive_tier': 'Adaptive Tier',
}


def load_paper_trading():
    """Load paper trading data."""
    with open('storage/paper_trading.json') as f:
        return json.load(f)


def load_backtest_metrics():
    """Load backtest strategy metrics."""
    with open('storage/strategy_metrics.json') as f:
        return json.load(f)


def get_live_returns(entries, start=LIVE_START, end=LIVE_END):
    """Extract live-period returns, filtering out None values."""
    live = []
    dates = []
    for e in entries:
        td = e['trade_date']
        if td < start or td > end:
            continue
        pr = e.get('portfolio_return')
        if pr is None:
            continue
        live.append(pr)
        dates.append(td)
    return np.array(live), dates


def compute_metrics(returns, dates, strategy_key=None, entries=None):
    """Compute comprehensive performance metrics from daily returns."""
    if len(returns) == 0:
        return None

    n_days = len(returns)
    years = n_days / ANNUALIZE_FACTOR

    # Cumulative return
    cum_ret = np.prod(1 + returns) - 1

    # CAGR
    if years > 0 and cum_ret > -1:
        cagr = (1 + cum_ret) ** (1 / years) - 1
    else:
        cagr = float('nan')

    # Annualized volatility
    ann_vol = np.std(returns, ddof=1) * np.sqrt(ANNUALIZE_FACTOR)

    # Sharpe ratio (assuming 0 risk-free rate for simplicity, consistent with backtest)
    if ann_vol > 0:
        sharpe = cagr / ann_vol
    else:
        sharpe = float('nan')

    # Max drawdown
    cum_values = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cum_values)
    drawdowns = cum_values / running_max - 1
    max_dd = np.min(drawdowns)

    # Max drawdown duration (in trading days)
    in_dd = cum_values < running_max
    if np.any(in_dd):
        dd_starts = np.where(np.diff(np.concatenate(([False], in_dd)).astype(int)) == 1)[0]
        dd_ends = np.where(np.diff(np.concatenate((in_dd, [False])).astype(int)) == -1)[0]
        if len(dd_starts) > 0 and len(dd_ends) > 0:
            # Handle ongoing drawdown
            if len(dd_ends) < len(dd_starts):
                dd_ends = np.append(dd_ends, n_days - 1)
            max_dd_days = int(np.max(dd_ends - dd_starts))
        else:
            max_dd_days = 0
    else:
        max_dd_days = 0

    # Calmar ratio
    calmar = cagr / abs(max_dd) if abs(max_dd) > 0 else float('nan')

    # Sortino ratio
    downside_returns = returns[returns < 0]
    if len(downside_returns) > 0:
        downside_vol = np.std(downside_returns, ddof=1) * np.sqrt(ANNUALIZE_FACTOR)
        sortino = cagr / downside_vol if downside_vol > 0 else float('nan')
    else:
        sortino = float('nan')

    # Win rate
    win_rate = np.mean(returns > 0) * 100

    # VaR and CVaR (95%)
    var_95 = np.percentile(returns, 5) * 100
    cvar_95 = np.mean(returns[returns <= np.percentile(returns, 5)]) * 100

    # Best/worst day
    best_day = np.max(returns) * 100
    worst_day = np.min(returns) * 100

    # Transaction cost estimation
    # Count weight changes (rebalance events)
    n_rebalances = 0
    if entries is not None:
        live_entries = [e for e in entries
                        if e['trade_date'] >= LIVE_START
                        and e['trade_date'] <= LIVE_END
                        and e.get('portfolio_return') is not None]
        for i in range(1, len(live_entries)):
            w_prev = live_entries[i-1].get('weights', {})
            w_curr = live_entries[i].get('weights', {})
            # Sum of absolute weight changes
            all_assets = set(list(w_prev.keys()) + list(w_curr.keys()))
            turnover = sum(abs(w_curr.get(a, 0) - w_prev.get(a, 0)) for a in all_assets)
            if turnover > 0.01:  # threshold for counting as rebalance
                n_rebalances += 1

    # Net Sharpe (after estimated TX costs)
    # Estimate annual turnover from rebalance count
    # Each rebalance ~average turnover. Simplified: TX cost = n_rebalances * avg_turnover * TX_COST_BPS
    avg_turnover_per_rebalance = 0.3  # rough estimate
    annual_tx_cost = (n_rebalances / years) * avg_turnover_per_rebalance * (TX_COST_BPS / 10000)
    net_cagr = cagr - annual_tx_cost
    net_sharpe = net_cagr / ann_vol if ann_vol > 0 else float('nan')

    # Latest position (from entries)
    latest_weights = {}
    if entries is not None:
        live_entries = [e for e in entries
                        if e['trade_date'] >= LIVE_START
                        and e['trade_date'] <= LIVE_END]
        if live_entries:
            latest = live_entries[-1]
            latest_weights = latest.get('weights', {})

    return {
        'trading_days': n_days,
        'period_years': round(years, 2),
        'cumulative_return_pct': round(cum_ret * 100, 2),
        'cagr_pct': round(cagr * 100, 2),
        'annualized_vol_pct': round(ann_vol * 100, 2),
        'sharpe': round(sharpe, 3),
        'sortino': round(sortino, 3),
        'max_drawdown_pct': round(max_dd * 100, 2),
        'max_drawdown_days': max_dd_days,
        'calmar': round(calmar, 3),
        'win_rate_pct': round(win_rate, 1),
        'var_95_pct': round(var_95, 2),
        'cvar_95_pct': round(cvar_95, 2),
        'best_day_pct': round(best_day, 2),
        'worst_day_pct': round(worst_day, 2),
        'n_rebalances': n_rebalances,
        'est_annual_tx_cost_pct': round(annual_tx_cost * 100, 3),
        'net_sharpe': round(net_sharpe, 3),
        'latest_weights': {k: round(v, 4) for k, v in latest_weights.items()},
    }


def compute_benchmark_returns():
    """Compute SPY buy-and-hold and 60/40 benchmark returns using yfinance."""
    import yfinance as yf

    start_dt = datetime.strptime(LIVE_START, "%Y-%m-%d") - timedelta(days=5)
    end_dt = datetime.strptime(LIVE_END, "%Y-%m-%d") + timedelta(days=3)

    print("Downloading benchmark data (SPY, TLT, ^VIX)...")
    tickers = yf.download(
        ['SPY', 'TLT', '^VIX'],
        start=start_dt.strftime('%Y-%m-%d'),
        end=end_dt.strftime('%Y-%m-%d'),
        auto_adjust=True,
        progress=False
    )

    close = tickers['Close']
    spy_close = close['SPY'].dropna()
    tlt_close = close['TLT'].dropna()
    vix_close = close['^VIX'].dropna()

    # Align to live period
    spy_live = spy_close[spy_close.index >= LIVE_START]
    spy_live = spy_live[spy_live.index <= LIVE_END]
    tlt_live = tlt_close[tlt_close.index >= LIVE_START]
    tlt_live = tlt_live[tlt_live.index <= LIVE_END]
    vix_live = vix_close[vix_close.index >= LIVE_START]
    vix_live = vix_live[vix_live.index <= LIVE_END]

    # Daily returns
    spy_ret = spy_live.pct_change().dropna()
    tlt_ret = tlt_live.pct_change().dropna()

    # Align dates
    common_dates = spy_ret.index.intersection(tlt_ret.index)
    spy_ret_aligned = spy_ret.loc[common_dates]
    tlt_ret_aligned = tlt_ret.loc[common_dates]

    # 60/40 portfolio (daily rebalanced for simplicity)
    port_6040_ret = 0.6 * spy_ret_aligned + 0.4 * tlt_ret_aligned

    return {
        'spy_returns': spy_ret.values,
        'spy_dates': [d.strftime('%Y-%m-%d') for d in spy_ret.index],
        'port_6040_returns': port_6040_ret.values,
        'port_6040_dates': [d.strftime('%Y-%m-%d') for d in port_6040_ret.index],
        'vix_series': vix_live.values,
        'vix_dates': [d.strftime('%Y-%m-%d') for d in vix_live.index],
    }


def regime_analysis(vix_series, vix_dates, strategy_returns_map):
    """Analyze VIX regime and strategy performance during spikes."""
    vix = np.array(vix_series)

    avg_vix = float(np.mean(vix))
    median_vix = float(np.median(vix))
    max_vix = float(np.max(vix))
    min_vix = float(np.min(vix))
    max_vix_date = vix_dates[int(np.argmax(vix))]

    days_above_20 = int(np.sum(vix > 20))
    days_above_25 = int(np.sum(vix > 25))
    days_above_30 = int(np.sum(vix > 30))
    days_above_35 = int(np.sum(vix > 35))

    # Identify VIX spike periods (VIX > 25)
    spike_periods = []
    in_spike = False
    spike_start = None
    for i, (v, d) in enumerate(zip(vix, vix_dates)):
        if v > 25 and not in_spike:
            in_spike = True
            spike_start = i
        elif v <= 25 and in_spike:
            in_spike = False
            spike_periods.append({
                'start': vix_dates[spike_start],
                'end': vix_dates[i-1],
                'days': i - spike_start,
                'peak_vix': round(float(np.max(vix[spike_start:i])), 1),
                'peak_date': vix_dates[spike_start + int(np.argmax(vix[spike_start:i]))]
            })
    # Handle ongoing spike
    if in_spike:
        spike_periods.append({
            'start': vix_dates[spike_start],
            'end': vix_dates[-1],
            'days': len(vix) - spike_start,
            'peak_vix': round(float(np.max(vix[spike_start:])), 1),
            'peak_date': vix_dates[spike_start + int(np.argmax(vix[spike_start:]))]
        })

    # Strategy performance during VIX > 25 periods
    vix_date_set = set(vix_dates)
    high_vix_dates = set(d for d, v in zip(vix_dates, vix) if v > 25)

    strategy_spike_performance = {}
    for strat_key, (returns, dates) in strategy_returns_map.items():
        # Find returns on VIX > 25 days
        spike_returns = []
        normal_returns = []
        for r, d in zip(returns, dates):
            if d in high_vix_dates:
                spike_returns.append(r)
            elif d in vix_date_set:
                normal_returns.append(r)

        spike_returns = np.array(spike_returns) if spike_returns else np.array([])
        normal_returns = np.array(normal_returns) if normal_returns else np.array([])

        strategy_spike_performance[strat_key] = {
            'spike_days': len(spike_returns),
            'spike_avg_return_pct': round(float(np.mean(spike_returns) * 100), 3) if len(spike_returns) > 0 else None,
            'spike_cum_return_pct': round(float((np.prod(1 + spike_returns) - 1) * 100), 2) if len(spike_returns) > 0 else None,
            'normal_avg_return_pct': round(float(np.mean(normal_returns) * 100), 3) if len(normal_returns) > 0 else None,
            'spike_vs_normal_diff_bps': round(
                float((np.mean(spike_returns) - np.mean(normal_returns)) * 10000), 1
            ) if len(spike_returns) > 0 and len(normal_returns) > 0 else None,
        }

    return {
        'avg_vix': round(avg_vix, 2),
        'median_vix': round(median_vix, 2),
        'max_vix': round(max_vix, 2),
        'min_vix': round(min_vix, 2),
        'max_vix_date': max_vix_date,
        'days_above_20': days_above_20,
        'days_above_25': days_above_25,
        'days_above_30': days_above_30,
        'days_above_35': days_above_35,
        'spike_periods_vix25': spike_periods,
        'strategy_spike_performance': strategy_spike_performance,
    }


def compute_equal_weight_meta(strategy_returns_map, active_only=True):
    """Compute equal-weight meta-portfolio of all (active) strategies."""
    keys = ACTIVE_STRATEGIES if active_only else ALL_STRATEGIES

    # Collect all dates with returns
    all_dates = set()
    for k in keys:
        if k in strategy_returns_map:
            _, dates = strategy_returns_map[k]
            all_dates.update(dates)

    all_dates = sorted(all_dates)

    meta_returns = []
    meta_dates = []
    for d in all_dates:
        day_returns = []
        for k in keys:
            if k not in strategy_returns_map:
                continue
            returns, dates = strategy_returns_map[k]
            date_to_idx = {dt: i for i, dt in enumerate(dates)}
            if d in date_to_idx:
                day_returns.append(returns[date_to_idx[d]])
        if len(day_returns) >= 3:  # need at least 3 strategies
            meta_returns.append(np.mean(day_returns))
            meta_dates.append(d)

    return np.array(meta_returns), meta_dates


def main():
    print("=" * 70)
    print("K640: LIVE PERFORMANCE AUDIT (2025-01 to 2026-03)")
    print("=" * 70)

    # Load data
    pt_data = load_paper_trading()
    bt_metrics = load_backtest_metrics()

    # ─── 1. Compute live metrics for all strategies ─────────────
    print("\n[1/7] Computing live performance metrics...")
    strategy_metrics = {}
    strategy_returns_map = {}  # for later use

    for strat_key in ALL_STRATEGIES:
        if strat_key not in pt_data:
            print(f"  SKIP {strat_key}: not in paper_trading.json")
            continue

        entries = pt_data[strat_key]['entries']
        returns, dates = get_live_returns(entries)

        if len(returns) == 0:
            print(f"  SKIP {strat_key}: no live returns")
            continue

        metrics = compute_metrics(returns, dates, strat_key, entries)
        strategy_metrics[strat_key] = metrics
        strategy_returns_map[strat_key] = (returns, dates)

        is_active = strat_key in ACTIVE_STRATEGIES
        status = "ACTIVE" if is_active else "inactive"
        print(f"  {strat_key} ({status}): "
              f"Cum={metrics['cumulative_return_pct']:+.1f}%, "
              f"Sharpe={metrics['sharpe']:.2f}, "
              f"MDD={metrics['max_drawdown_pct']:.1f}%, "
              f"Days={metrics['trading_days']}")

    # ─── 2. Benchmarks ──────────────────────────────────────────
    print("\n[2/7] Computing benchmark returns (SPY, 60/40, Meta)...")
    bench = compute_benchmark_returns()

    # SPY benchmark
    spy_metrics = compute_metrics(bench['spy_returns'], bench['spy_dates'])
    print(f"  SPY B&H: Cum={spy_metrics['cumulative_return_pct']:+.1f}%, "
          f"Sharpe={spy_metrics['sharpe']:.2f}, MDD={spy_metrics['max_drawdown_pct']:.1f}%")

    # 60/40 benchmark
    port6040_metrics = compute_metrics(bench['port_6040_returns'], bench['port_6040_dates'])
    print(f"  60/40: Cum={port6040_metrics['cumulative_return_pct']:+.1f}%, "
          f"Sharpe={port6040_metrics['sharpe']:.2f}, MDD={port6040_metrics['max_drawdown_pct']:.1f}%")

    # Equal-weight meta-portfolio
    meta_returns, meta_dates = compute_equal_weight_meta(strategy_returns_map)
    meta_metrics = compute_metrics(meta_returns, meta_dates)
    print(f"  Meta EW: Cum={meta_metrics['cumulative_return_pct']:+.1f}%, "
          f"Sharpe={meta_metrics['sharpe']:.2f}, MDD={meta_metrics['max_drawdown_pct']:.1f}%")

    # ─── 3. Regime analysis ─────────────────────────────────────
    print("\n[3/7] VIX regime analysis...")
    regime = regime_analysis(
        bench['vix_series'], bench['vix_dates'], strategy_returns_map
    )
    print(f"  Avg VIX: {regime['avg_vix']}")
    print(f"  Max VIX: {regime['max_vix']} ({regime['max_vix_date']})")
    print(f"  Days VIX>20: {regime['days_above_20']}")
    print(f"  Days VIX>25: {regime['days_above_25']}")
    print(f"  Days VIX>30: {regime['days_above_30']}")
    print(f"  Spike periods (VIX>25): {len(regime['spike_periods_vix25'])}")
    for sp in regime['spike_periods_vix25']:
        print(f"    {sp['start']} to {sp['end']}: {sp['days']}d, peak={sp['peak_vix']} ({sp['peak_date']})")

    # ─── 4. Net Sharpe ranking ──────────────────────────────────
    print("\n[4/7] Net Sharpe ranking (after TX costs)...")
    ranked = sorted(
        [(k, v) for k, v in strategy_metrics.items()],
        key=lambda x: x[1]['net_sharpe'] if not np.isnan(x[1]['net_sharpe']) else -999,
        reverse=True
    )

    print(f"\n{'Rank':<5} {'Strategy':<30} {'Net Sharpe':>10} {'Sharpe':>8} "
          f"{'CAGR%':>7} {'MDD%':>7} {'Calmar':>7} {'Active':>7}")
    print("-" * 85)
    for rank, (k, v) in enumerate(ranked, 1):
        active = "Y" if k in ACTIVE_STRATEGIES else "N"
        print(f"{rank:<5} {STRATEGY_DISPLAY.get(k, k):<30} "
              f"{v['net_sharpe']:>10.3f} {v['sharpe']:>8.3f} "
              f"{v['cagr_pct']:>7.1f} {v['max_drawdown_pct']:>7.1f} "
              f"{v['calmar']:>7.2f} {active:>7}")

    # Add benchmarks to ranking display
    print("-" * 85)
    print(f"{'---':<5} {'SPY Buy & Hold':<30} "
          f"{'N/A':>10} {spy_metrics['sharpe']:>8.3f} "
          f"{spy_metrics['cagr_pct']:>7.1f} {spy_metrics['max_drawdown_pct']:>7.1f} "
          f"{spy_metrics['calmar']:>7.2f} {'BM':>7}")
    print(f"{'---':<5} {'60/40 SPY/TLT':<30} "
          f"{'N/A':>10} {port6040_metrics['sharpe']:>8.3f} "
          f"{port6040_metrics['cagr_pct']:>7.1f} {port6040_metrics['max_drawdown_pct']:>7.1f} "
          f"{port6040_metrics['calmar']:>7.2f} {'BM':>7}")
    print(f"{'---':<5} {'Meta Equal-Weight':<30} "
          f"{'N/A':>10} {meta_metrics['sharpe']:>8.3f} "
          f"{meta_metrics['cagr_pct']:>7.1f} {meta_metrics['max_drawdown_pct']:>7.1f} "
          f"{meta_metrics['calmar']:>7.2f} {'BM':>7}")

    # ─── 5. Backtest vs Live comparison ─────────────────────────
    print("\n[5/7] Backtest vs Live Sharpe comparison...")
    bt_vs_live = {}
    print(f"\n{'Strategy':<30} {'BT Sharpe':>10} {'Live Sharpe':>12} {'Delta':>8} {'Consistent?':>12}")
    print("-" * 75)
    for k in ALL_STRATEGIES:
        if k not in strategy_metrics or k not in bt_metrics:
            continue
        bt_sharpe = bt_metrics[k].get('sharpe', float('nan'))
        live_sharpe = strategy_metrics[k]['sharpe']
        delta = live_sharpe - bt_sharpe

        # Consistency check: within 1.0 of backtest
        consistent = abs(delta) < 1.0
        label = "YES" if consistent else "DEGRADED" if delta < 0 else "IMPROVED"

        bt_vs_live[k] = {
            'backtest_sharpe': round(bt_sharpe, 3),
            'live_sharpe': round(live_sharpe, 3),
            'delta': round(delta, 3),
            'consistent': label,
        }

        print(f"{STRATEGY_DISPLAY.get(k, k):<30} "
              f"{bt_sharpe:>10.3f} {live_sharpe:>12.3f} "
              f"{delta:>+8.3f} {label:>12}")

    # ─── 6. Monthly breakdown for top strategies ────────────────
    print("\n[6/7] Monthly return breakdown (top 5 by Net Sharpe)...")
    top5 = [k for k, v in ranked[:5]]

    for strat_key in top5:
        returns, dates = strategy_returns_map[strat_key]
        # Group by month
        monthly = {}
        for r, d in zip(returns, dates):
            month_key = d[:7]  # YYYY-MM
            if month_key not in monthly:
                monthly[month_key] = []
            monthly[month_key].append(r)

        print(f"\n  {STRATEGY_DISPLAY.get(strat_key, strat_key)}:")
        print(f"  {'Month':<10} {'Return%':>9} {'Days':>6} {'Win%':>6}")
        for month in sorted(monthly.keys()):
            m_ret = np.prod(1 + np.array(monthly[month])) - 1
            m_days = len(monthly[month])
            m_win = np.mean(np.array(monthly[month]) > 0) * 100
            print(f"  {month:<10} {m_ret*100:>+9.2f} {m_days:>6d} {m_win:>6.0f}")

    # ─── 7. Summary statistics ──────────────────────────────────
    print("\n[7/7] Summary statistics...")

    # Strategies beating SPY
    n_beat_spy = sum(1 for k, v in strategy_metrics.items()
                     if v['sharpe'] > spy_metrics['sharpe'])
    n_beat_6040 = sum(1 for k, v in strategy_metrics.items()
                      if v['sharpe'] > port6040_metrics['sharpe'])

    # Average live Sharpe
    live_sharpes = [v['sharpe'] for v in strategy_metrics.values()
                    if not np.isnan(v['sharpe'])]
    avg_live_sharpe = np.mean(live_sharpes)

    # Strategy with best drawdown protection
    best_dd = min(strategy_metrics.items(),
                  key=lambda x: abs(x[1]['max_drawdown_pct']))

    print(f"  Strategies beating SPY Sharpe ({spy_metrics['sharpe']:.2f}): "
          f"{n_beat_spy}/{len(strategy_metrics)}")
    print(f"  Strategies beating 60/40 Sharpe ({port6040_metrics['sharpe']:.2f}): "
          f"{n_beat_6040}/{len(strategy_metrics)}")
    print(f"  Average live Sharpe: {avg_live_sharpe:.3f}")
    print(f"  Best drawdown protection: {STRATEGY_DISPLAY.get(best_dd[0], best_dd[0])} "
          f"(MDD={best_dd[1]['max_drawdown_pct']:.1f}%)")

    # ─── Compile results ────────────────────────────────────────
    results = {
        'experiment_id': 'K640',
        'title': 'Live Performance Audit (2025-01 to 2026-03)',
        'description': 'Comprehensive audit of all VolPred strategies using 15 months of live paper trading data. Compares live performance to backtest expectations and benchmarks.',
        'data_source': 'storage/paper_trading.json (live tracked), yfinance (benchmarks, VIX)',
        'period': f'{LIVE_START} to {LIVE_END}',
        'methodology': 'Performance metrics computed from actual tracked portfolio returns (not simulated). TX costs estimated at 10bps per round-trip with turnover-based calculation.',
        'strategy_metrics_live': strategy_metrics,
        'benchmarks': {
            'spy_buy_and_hold': spy_metrics,
            'portfolio_60_40': port6040_metrics,
            'meta_equal_weight': meta_metrics,
        },
        'regime_analysis': regime,
        'net_sharpe_ranking': [
            {
                'rank': i+1,
                'strategy': k,
                'display_name': STRATEGY_DISPLAY.get(k, k),
                'net_sharpe': v['net_sharpe'],
                'sharpe': v['sharpe'],
                'is_active': k in ACTIVE_STRATEGIES,
            }
            for i, (k, v) in enumerate(ranked)
        ],
        'backtest_vs_live': bt_vs_live,
        'summary': {
            'total_strategies_audited': len(strategy_metrics),
            'active_strategies': len([k for k in strategy_metrics if k in ACTIVE_STRATEGIES]),
            'strategies_beating_spy_sharpe': n_beat_spy,
            'strategies_beating_6040_sharpe': n_beat_6040,
            'avg_live_sharpe': round(avg_live_sharpe, 3),
            'best_live_sharpe_strategy': ranked[0][0] if ranked else None,
            'best_live_sharpe': ranked[0][1]['sharpe'] if ranked else None,
            'best_drawdown_protection': best_dd[0],
            'best_max_drawdown_pct': best_dd[1]['max_drawdown_pct'],
            'spy_live_sharpe': spy_metrics['sharpe'],
            'port6040_live_sharpe': port6040_metrics['sharpe'],
            'meta_ew_live_sharpe': meta_metrics['sharpe'],
            'vix_avg': regime['avg_vix'],
            'vix_max': regime['max_vix'],
            'vix_spike_days_gt25': regime['days_above_25'],
        },
        'references': [
            'Harvey, C. R. (2016). Lucky factors. Journal of Investment Management.',
            'DeMiguel, V., Garlappi, L., & Uppal, R. (2009). Optimal versus naive diversification. RFS, 22(5).',
        ],
    }

    # Save
    output_path = 'experiments/k640_results.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n✓ Results saved to {output_path}")

    print("\n" + "=" * 70)
    print("AUDIT COMPLETE")
    print("=" * 70)

    return results


if __name__ == '__main__':
    main()
