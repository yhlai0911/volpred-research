#!/usr/bin/env python3
"""
K507: Dynamic SPY/GLD Allocation Strategy
==========================================
Background: 50/50 SPY/GLD + 12/VIX is the best retail strategy (Sharpe ~0.83).
But 50/50 is fixed — maybe dynamic allocation based on market conditions can improve.

This is NOT about VT (target volatility). It's about **asset allocation weights**.

Strategies tested:
1. VIX-Based Dynamic Allocation (shift to GLD when VIX high)
2. Momentum-Based Allocation (follow winning asset)
3. Inverse Vol Weighting (Risk Parity Lite)
4. Combined (VIX + Momentum)

All strategies overlay 12/VIX VT on top.
Benchmark: Static 50/50 SPY/GLD + 12/VIX

Backtest: 2006-2025 (~20 years)
TX cost: 0.05% per rebalance (monthly)
Cross-OOS: 5 periods (4-year each)

References:
- Asness et al. (2012) "Value and Momentum Everywhere" JF
- Qian (2005) "Risk Parity Portfolios" PanAgora
- K458 meta-analysis, N79 12/VIX, Q21 optimal retail portfolio
"""

import json
import sys
import os
import warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings("ignore")

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import yfinance as yf


def get_data():
    """Fetch SPY, GLD, VIX data directly from yfinance."""
    def _download(ticker):
        df = yf.download(ticker, start="2005-01-01", end="2026-12-31", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_localize(None)
        return df

    spy = _download("SPY")
    gld = _download("GLD")
    vix = _download("^VIX")

    # Compute returns
    spy['returns'] = spy['Close'].pct_change()
    gld['returns'] = gld['Close'].pct_change()

    return spy, gld, vix


def compute_vt_weight(vix_level):
    """12/VIX target volatility weight, capped at 1.0."""
    return min(12.0 / max(vix_level, 1.0), 1.0)


def strategy_static_5050(spy_ret, gld_ret, vix_series, **kwargs):
    """Benchmark: Static 50/50 SPY/GLD + 12/VIX."""
    aligned = pd.DataFrame({
        'spy_ret': spy_ret,
        'gld_ret': gld_ret,
        'vix': vix_series
    }).dropna()

    vt_weight = aligned['vix'].shift(1).apply(compute_vt_weight)
    port_ret = 0.5 * aligned['spy_ret'] + 0.5 * aligned['gld_ret']
    total_ret = vt_weight * port_ret

    # Monthly rebalancing TX cost
    # For static 50/50, we still pay TX when VT weight changes
    weight_changes = vt_weight.diff().abs().fillna(0)
    # Group by month, take first day's change
    monthly_rebal = weight_changes.groupby(pd.Grouper(freq='ME')).sum() * 0.0005
    tx_daily = monthly_rebal.reindex(total_ret.index, method='ffill').fillna(0) / 21  # spread over month

    return total_ret, aligned.index, pd.Series(0.5, index=aligned.index), pd.Series(0.5, index=aligned.index)


def strategy_vix_dynamic(spy_ret, gld_ret, vix_series, **kwargs):
    """
    Strategy 1: VIX-Based Dynamic Allocation
    - VIX < 15: 70/30 SPY/GLD (bull market offense)
    - VIX 15-25: 50/50 (standard)
    - VIX > 25: 30/70 SPY/GLD (defensive)
    """
    aligned = pd.DataFrame({
        'spy_ret': spy_ret,
        'gld_ret': gld_ret,
        'vix': vix_series
    }).dropna()

    prev_vix = aligned['vix'].shift(1)

    spy_w = pd.Series(0.5, index=aligned.index)
    spy_w[prev_vix < 15] = 0.70
    spy_w[prev_vix > 25] = 0.30
    gld_w = 1.0 - spy_w

    vt_weight = prev_vix.apply(compute_vt_weight)
    port_ret = spy_w * aligned['spy_ret'] + gld_w * aligned['gld_ret']
    total_ret = vt_weight * port_ret

    return total_ret, aligned.index, spy_w, gld_w


def strategy_momentum(spy_ret, gld_ret, vix_series, spy_price=None, gld_price=None, lookback=63, **kwargs):
    """
    Strategy 2: Momentum-Based Allocation
    - SPY 3-month return > GLD 3-month return -> 70/30
    - SPY < GLD -> 30/70
    - Difference < 2% -> 50/50
    """
    aligned = pd.DataFrame({
        'spy_ret': spy_ret,
        'gld_ret': gld_ret,
        'vix': vix_series,
        'spy_price': spy_price,
        'gld_price': gld_price
    }).dropna()

    spy_mom = aligned['spy_price'].pct_change(lookback).shift(1)
    gld_mom = aligned['gld_price'].pct_change(lookback).shift(1)
    mom_diff = spy_mom - gld_mom

    spy_w = pd.Series(0.5, index=aligned.index)
    spy_w[mom_diff > 0.02] = 0.70
    spy_w[mom_diff < -0.02] = 0.30
    gld_w = 1.0 - spy_w

    prev_vix = aligned['vix'].shift(1)
    vt_weight = prev_vix.apply(compute_vt_weight)
    port_ret = spy_w * aligned['spy_ret'] + gld_w * aligned['gld_ret']
    total_ret = vt_weight * port_ret

    return total_ret, aligned.index, spy_w, gld_w


def strategy_inv_vol(spy_ret, gld_ret, vix_series, lookback=63, **kwargs):
    """
    Strategy 3: Inverse Volatility Weighting (Risk Parity Lite)
    w_SPY = (1/σ_SPY) / (1/σ_SPY + 1/σ_GLD)
    w_GLD = (1/σ_GLD) / (1/σ_SPY + 1/σ_GLD)
    """
    aligned = pd.DataFrame({
        'spy_ret': spy_ret,
        'gld_ret': gld_ret,
        'vix': vix_series
    }).dropna()

    spy_vol = aligned['spy_ret'].rolling(lookback).std().shift(1)
    gld_vol = aligned['gld_ret'].rolling(lookback).std().shift(1)

    inv_spy = 1.0 / spy_vol.clip(lower=0.001)
    inv_gld = 1.0 / gld_vol.clip(lower=0.001)
    total_inv = inv_spy + inv_gld

    spy_w = inv_spy / total_inv
    gld_w = inv_gld / total_inv

    prev_vix = aligned['vix'].shift(1)
    vt_weight = prev_vix.apply(compute_vt_weight)
    port_ret = spy_w * aligned['spy_ret'] + gld_w * aligned['gld_ret']
    total_ret = vt_weight * port_ret

    return total_ret, aligned.index, spy_w, gld_w


def strategy_combined(spy_ret, gld_ret, vix_series, spy_price=None, gld_price=None, lookback=63, **kwargs):
    """
    Strategy 4: Combined VIX + Momentum
    - Average the SPY weights from Strategy 1 and Strategy 2
    """
    aligned = pd.DataFrame({
        'spy_ret': spy_ret,
        'gld_ret': gld_ret,
        'vix': vix_series,
        'spy_price': spy_price,
        'gld_price': gld_price
    }).dropna()

    prev_vix = aligned['vix'].shift(1)

    # VIX component
    vix_spy_w = pd.Series(0.5, index=aligned.index)
    vix_spy_w[prev_vix < 15] = 0.70
    vix_spy_w[prev_vix > 25] = 0.30

    # Momentum component
    spy_mom = aligned['spy_price'].pct_change(lookback).shift(1)
    gld_mom = aligned['gld_price'].pct_change(lookback).shift(1)
    mom_diff = spy_mom - gld_mom

    mom_spy_w = pd.Series(0.5, index=aligned.index)
    mom_spy_w[mom_diff > 0.02] = 0.70
    mom_spy_w[mom_diff < -0.02] = 0.30

    # Average
    spy_w = 0.5 * vix_spy_w + 0.5 * mom_spy_w
    gld_w = 1.0 - spy_w

    vt_weight = prev_vix.apply(compute_vt_weight)
    port_ret = spy_w * aligned['spy_ret'] + gld_w * aligned['gld_ret']
    total_ret = vt_weight * port_ret

    return total_ret, aligned.index, spy_w, gld_w


def compute_metrics(returns, tx_cost_annual=0.006, rf_annual=0.0):
    """Compute strategy metrics from daily returns series."""
    returns = returns.dropna()
    if len(returns) < 252:
        return {}

    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    max_dd = dd.min()

    # Sortino
    downside = returns[returns < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    # Calmar
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    # Net Sharpe (after monthly rebalancing TX cost)
    # ~12 rebalances/year, 0.05% each = 0.6% annual
    net_ret = ann_ret - tx_cost_annual
    net_sharpe = net_ret / ann_vol if ann_vol > 0 else 0

    return {
        'ann_return': round(ann_ret, 4),
        'ann_vol': round(ann_vol, 4),
        'sharpe': round(sharpe, 3),
        'net_sharpe': round(net_sharpe, 3),
        'max_dd': round(max_dd, 4),
        'calmar': round(calmar, 3),
        'sortino': round(sortino, 3),
        'n_days': len(returns),
        'cum_return': round(float(cum.iloc[-1] - 1), 4),
    }


def compute_tx_cost(spy_w, monthly=True):
    """
    Compute realistic TX costs from weight changes.
    0.05% per rebalance, monthly frequency.
    """
    spy_w = spy_w.dropna()
    if len(spy_w) == 0:
        return 0.0

    if monthly:
        # Monthly endpoints
        monthly_w = spy_w.resample('ME').last()
        w_changes = monthly_w.diff().abs().fillna(0)
        # Each rebalance costs 0.05% on the turnover
        total_tx = (w_changes * 0.0005 * 2).sum()  # *2 for both legs
    else:
        w_changes = spy_w.diff().abs().fillna(0)
        total_tx = (w_changes * 0.0005 * 2).sum()

    n_years = len(spy_w) / 252
    annual_tx = total_tx / n_years if n_years > 0 else 0
    return annual_tx


def diebold_mariano_test(e1, e2, h=1):
    """
    Diebold-Mariano test for equal predictive accuracy.
    H0: both forecasts have equal accuracy.
    e1, e2: forecast errors (or loss differentials).
    Returns: DM statistic and p-value.
    """
    from scipy import stats
    d = e1 - e2  # loss differential
    d = d.dropna()
    n = len(d)
    if n < 10:
        return 0, 1.0

    d_mean = d.mean()
    # Newey-West HAC variance with h-1 lags
    gamma_0 = np.var(d, ddof=1)
    d_var = gamma_0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        d_var += 2 * gamma_k

    d_var = max(d_var, 1e-10)
    dm_stat = d_mean / np.sqrt(d_var / n)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n-1))

    return dm_stat, p_value


def run_cross_oos(spy_ret, gld_ret, vix_close, spy_price, gld_price, strategies):
    """
    5-period cross-OOS validation.
    Each period is ~4 years.
    """
    # Find common date range
    aligned = pd.DataFrame({
        'spy_ret': spy_ret,
        'gld_ret': gld_ret,
        'vix': vix_close,
        'spy_price': spy_price,
        'gld_price': gld_price
    }).dropna()

    dates = aligned.index
    n = len(dates)
    period_size = n // 5

    results = {}
    for name, func in strategies.items():
        results[name] = {'oos_metrics': [], 'oos_sharpes': []}

    for fold in range(5):
        oos_start = fold * period_size
        oos_end = (fold + 1) * period_size if fold < 4 else n

        oos_dates = dates[oos_start:oos_end]
        oos_start_date = str(oos_dates[0].date())
        oos_end_date = str(oos_dates[-1].date())

        print(f"  Fold {fold+1}: {oos_start_date} to {oos_end_date} ({len(oos_dates)} days)")

        for name, func in strategies.items():
            oos_spy_ret = aligned.loc[oos_dates, 'spy_ret']
            oos_gld_ret = aligned.loc[oos_dates, 'gld_ret']
            oos_vix = aligned.loc[oos_dates, 'vix']
            oos_spy_price = aligned.loc[oos_dates, 'spy_price']
            oos_gld_price = aligned.loc[oos_dates, 'gld_price']

            # Need lookback data for momentum/vol
            lookback = 63
            extended_start = max(0, oos_start - lookback)
            extended_dates = dates[extended_start:oos_end]

            ext_spy_ret = aligned.loc[extended_dates, 'spy_ret']
            ext_gld_ret = aligned.loc[extended_dates, 'gld_ret']
            ext_vix = aligned.loc[extended_dates, 'vix']
            ext_spy_price = aligned.loc[extended_dates, 'spy_price']
            ext_gld_price = aligned.loc[extended_dates, 'gld_price']

            total_ret, idx, spy_w, gld_w = func(
                ext_spy_ret, ext_gld_ret, ext_vix,
                spy_price=ext_spy_price, gld_price=ext_gld_price,
                lookback=lookback
            )

            # Trim to OOS period only
            total_ret = total_ret.loc[total_ret.index.isin(oos_dates)]
            spy_w = spy_w.loc[spy_w.index.isin(oos_dates)]

            metrics = compute_metrics(total_ret)
            tx = compute_tx_cost(spy_w)
            metrics['annual_tx'] = round(tx, 6)
            metrics['oos_period'] = f"{oos_start_date} to {oos_end_date}"

            results[name]['oos_metrics'].append(metrics)
            results[name]['oos_sharpes'].append(metrics.get('sharpe', 0))

    return results


def run_full_backtest(spy_ret, gld_ret, vix_close, spy_price, gld_price, strategies):
    """Run full-sample backtest for all strategies."""
    results = {}

    for name, func in strategies.items():
        total_ret, idx, spy_w, gld_w = func(
            spy_ret, gld_ret, vix_close,
            spy_price=spy_price, gld_price=gld_price,
            lookback=63
        )

        metrics = compute_metrics(total_ret)
        tx = compute_tx_cost(spy_w)
        metrics['annual_tx'] = round(tx, 6)

        # Weight statistics
        spy_w_clean = spy_w.dropna()
        metrics['avg_spy_weight'] = round(spy_w_clean.mean(), 3)
        metrics['std_spy_weight'] = round(spy_w_clean.std(), 3)
        metrics['min_spy_weight'] = round(spy_w_clean.min(), 3)
        metrics['max_spy_weight'] = round(spy_w_clean.max(), 3)

        results[name] = {
            'full_sample': metrics,
            'returns': total_ret,
            'spy_weights': spy_w
        }

    return results


def crisis_analysis(spy_ret, gld_ret, vix_close, spy_price, gld_price, strategies):
    """Analyze performance during crisis periods."""
    crises = {
        'GFC_2008': ('2008-09-01', '2009-03-31'),
        'Euro_Crisis_2011': ('2011-07-01', '2011-10-31'),
        'COVID_2020': ('2020-02-15', '2020-04-15'),
        'Rate_Hike_2022': ('2022-01-01', '2022-12-31'),
        'Iran_Crisis_2026': ('2026-02-15', '2026-03-15'),
    }

    results = {}
    for crisis_name, (start, end) in crises.items():
        results[crisis_name] = {}
        for name, func in strategies.items():
            total_ret, idx, spy_w, gld_w = func(
                spy_ret, gld_ret, vix_close,
                spy_price=spy_price, gld_price=gld_price,
                lookback=63
            )

            try:
                crisis_ret = total_ret.loc[start:end]
                if len(crisis_ret) > 5:
                    cum = (1 + crisis_ret).cumprod()
                    crisis_return = float(cum.iloc[-1] - 1)
                    crisis_mdd = float(((cum - cum.cummax()) / cum.cummax()).min())
                    avg_spy_w = float(spy_w.loc[start:end].mean())
                    results[crisis_name][name] = {
                        'return': round(crisis_return, 4),
                        'max_dd': round(crisis_mdd, 4),
                        'avg_spy_weight': round(avg_spy_w, 3),
                        'n_days': len(crisis_ret)
                    }
            except Exception:
                pass

    return results


def main():
    print("=" * 70)
    print("K507: Dynamic SPY/GLD Allocation Strategy")
    print("=" * 70)

    # ---- Data ----
    print("\n[1] Loading data...")
    spy, gld, vix = get_data()

    spy_ret = spy['returns']
    gld_ret = gld['returns']
    spy_price = spy['Close']
    gld_price = gld['Close']
    vix_close = vix['Close']

    # Align all series
    common = spy_ret.index.intersection(gld_ret.index).intersection(vix_close.index)
    spy_ret = spy_ret.loc[common]
    gld_ret = gld_ret.loc[common]
    spy_price = spy_price.loc[common]
    gld_price = gld_price.loc[common]
    vix_close = vix_close.loc[common]

    print(f"  Common period: {common[0].date()} to {common[-1].date()} ({len(common)} days)")
    print(f"  SPY: mean={spy_ret.mean()*252:.3f}, vol={spy_ret.std()*np.sqrt(252):.3f}")
    print(f"  GLD: mean={gld_ret.mean()*252:.3f}, vol={gld_ret.std()*np.sqrt(252):.3f}")
    print(f"  VIX: mean={vix_close.mean():.1f}, range [{vix_close.min():.1f}, {vix_close.max():.1f}]")
    print(f"  SPY-GLD corr: {spy_ret.corr(gld_ret):.3f}")

    # ---- Diagnostics ----
    print("\n[2] Data diagnostics...")
    from scipy import stats

    spy_skew = stats.skew(spy_ret.dropna())
    spy_kurt = stats.kurtosis(spy_ret.dropna())
    gld_skew = stats.skew(gld_ret.dropna())
    gld_kurt = stats.kurtosis(gld_ret.dropna())

    print(f"  SPY: skew={spy_skew:.3f}, excess_kurtosis={spy_kurt:.3f}")
    print(f"  GLD: skew={gld_skew:.3f}, excess_kurtosis={gld_kurt:.3f}")

    # Rolling correlation
    rolling_corr = spy_ret.rolling(252).corr(gld_ret)
    print(f"  Rolling 1Y corr: mean={rolling_corr.mean():.3f}, std={rolling_corr.std():.3f}, range [{rolling_corr.min():.3f}, {rolling_corr.max():.3f}]")

    # VIX regime distribution
    vix_low = (vix_close < 15).sum() / len(vix_close)
    vix_mid = ((vix_close >= 15) & (vix_close <= 25)).sum() / len(vix_close)
    vix_high = (vix_close > 25).sum() / len(vix_close)
    print(f"  VIX regimes: <15={vix_low:.1%}, 15-25={vix_mid:.1%}, >25={vix_high:.1%}")

    # ---- Strategies ----
    strategies = {
        'static_5050': strategy_static_5050,
        'vix_dynamic': strategy_vix_dynamic,
        'momentum': strategy_momentum,
        'inv_vol': strategy_inv_vol,
        'combined': strategy_combined,
    }

    # ---- Full Sample Backtest ----
    print("\n[3] Full-sample backtest (all available data)...")
    full_results = run_full_backtest(spy_ret, gld_ret, vix_close, spy_price, gld_price, strategies)

    print(f"\n  {'Strategy':<20} {'Sharpe':>7} {'Net Sharpe':>11} {'AnnRet':>8} {'AnnVol':>8} {'MaxDD':>8} {'Calmar':>7} {'AvgSPYw':>8}")
    print("  " + "-" * 85)
    for name in strategies:
        m = full_results[name]['full_sample']
        print(f"  {name:<20} {m['sharpe']:>7.3f} {m['net_sharpe']:>11.3f} {m['ann_return']:>8.4f} {m['ann_vol']:>8.4f} {m['max_dd']:>8.4f} {m['calmar']:>7.3f} {m.get('avg_spy_weight', 0.5):>8.3f}")

    # ---- DM Tests (vs benchmark) ----
    print("\n[4] Diebold-Mariano tests vs static 50/50...")
    benchmark_ret = full_results['static_5050']['returns']

    dm_results = {}
    for name in ['vix_dynamic', 'momentum', 'inv_vol', 'combined']:
        strat_ret = full_results[name]['returns']
        # Align
        common_dm = benchmark_ret.index.intersection(strat_ret.index)
        b_ret = benchmark_ret.loc[common_dm]
        s_ret = strat_ret.loc[common_dm]

        # Use squared returns as loss (lower vol = better)
        # Or use negative returns as loss
        # Actually: test if strategy returns are significantly different
        e1 = -b_ret  # negative of returns (lower loss = better)
        e2 = -s_ret
        dm_stat, dm_p = diebold_mariano_test(e1, e2)
        dm_results[name] = {'dm_stat': round(dm_stat, 3), 'dm_p': round(dm_p, 4)}

        sig = "***" if abs(dm_stat) > 3.0 else "**" if abs(dm_stat) > 2.0 else "*" if abs(dm_stat) > 1.65 else ""
        print(f"  {name:<20} DM={dm_stat:>7.3f}, p={dm_p:.4f} {sig}  {'(Harvey t>3.0 pass)' if abs(dm_stat) > 3.0 else ''}")

    # ---- Cross-OOS Validation ----
    print("\n[5] Cross-OOS validation (5 periods)...")
    oos_results = run_cross_oos(spy_ret, gld_ret, vix_close, spy_price, gld_price, strategies)

    print(f"\n  {'Strategy':<20}", end="")
    for i in range(5):
        print(f" {'Fold'+str(i+1):>8}", end="")
    print(f" {'Mean':>8} {'Wins':>5}")
    print("  " + "-" * 75)

    benchmark_sharpes = oos_results['static_5050']['oos_sharpes']

    cross_oos_summary = {}
    for name in strategies:
        sharpes = oos_results[name]['oos_sharpes']
        mean_s = np.mean(sharpes)
        if name != 'static_5050':
            wins = sum(1 for s, b in zip(sharpes, benchmark_sharpes) if s > b)
        else:
            wins = '-'

        print(f"  {name:<20}", end="")
        for s in sharpes:
            print(f" {s:>8.3f}", end="")
        print(f" {mean_s:>8.3f} {wins:>5}")

        cross_oos_summary[name] = {
            'sharpes': [round(s, 3) for s in sharpes],
            'mean_sharpe': round(mean_s, 3),
            'wins_vs_benchmark': wins if name != 'static_5050' else 'N/A'
        }

    # ---- Crisis Analysis ----
    print("\n[6] Crisis period analysis...")
    crisis_results = crisis_analysis(spy_ret, gld_ret, vix_close, spy_price, gld_price, strategies)

    for crisis_name, strats in crisis_results.items():
        if len(strats) == 0:
            continue
        print(f"\n  {crisis_name}:")
        print(f"    {'Strategy':<20} {'Return':>8} {'MaxDD':>8} {'AvgSPYw':>8}")
        for sname, sm in strats.items():
            print(f"    {sname:<20} {sm['return']:>8.4f} {sm['max_dd']:>8.4f} {sm['avg_spy_weight']:>8.3f}")

    # ---- Weight Statistics ----
    print("\n[7] Weight statistics...")
    for name in strategies:
        m = full_results[name]['full_sample']
        if 'avg_spy_weight' in m:
            print(f"  {name:<20} SPY_w: avg={m['avg_spy_weight']:.3f}, std={m['std_spy_weight']:.3f}, range [{m['min_spy_weight']:.3f}, {m['max_spy_weight']:.3f}]")

    # ---- Year-by-Year ----
    print("\n[8] Year-by-year Sharpe comparison...")
    yearly_results = {}
    for name in strategies:
        ret = full_results[name]['returns']
        yearly = ret.groupby(ret.index.year).apply(
            lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0
        )
        yearly_results[name] = yearly

    years = sorted(yearly_results['static_5050'].index)
    print(f"  {'Year':<6}", end="")
    for name in strategies:
        print(f" {name[:12]:>12}", end="")
    print()
    print("  " + "-" * 70)

    win_counts = {name: 0 for name in strategies if name != 'static_5050'}

    for year in years:
        print(f"  {year:<6}", end="")
        bench_val = yearly_results['static_5050'].get(year, 0)
        for name in strategies:
            val = yearly_results[name].get(year, 0)
            print(f" {val:>12.3f}", end="")
            if name != 'static_5050' and val > bench_val:
                win_counts[name] += 1
        print()

    print(f"\n  Win rates vs benchmark:")
    for name, wins in win_counts.items():
        total = len(years)
        print(f"    {name:<20}: {wins}/{total} = {wins/total:.0%}")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    benchmark_sharpe = full_results['static_5050']['full_sample']['sharpe']
    benchmark_net = full_results['static_5050']['full_sample']['net_sharpe']

    any_pass = False
    for name in ['vix_dynamic', 'momentum', 'inv_vol', 'combined']:
        m = full_results[name]['full_sample']
        oos = cross_oos_summary[name]
        dm = dm_results[name]

        sharpe_better = m['sharpe'] > benchmark_sharpe
        net_better = m['net_sharpe'] > benchmark_net
        oos_wins = oos['wins_vs_benchmark']
        oos_pass = oos_wins >= 4
        harvey_pass = abs(dm['dm_stat']) > 3.0

        status = "PASS" if (sharpe_better and net_better and oos_pass and harvey_pass) else "FAIL"
        if status == "PASS":
            any_pass = True

        print(f"\n  {name}:")
        print(f"    Sharpe: {m['sharpe']:.3f} vs {benchmark_sharpe:.3f} {'[OK]' if sharpe_better else '[FAIL]'}")
        print(f"    Net Sharpe: {m['net_sharpe']:.3f} vs {benchmark_net:.3f} {'[OK]' if net_better else '[FAIL]'}")
        print(f"    Cross-OOS: {oos_wins}/5 wins {'[OK]' if oos_pass else '[FAIL]'}")
        print(f"    Harvey t>3.0: DM={dm['dm_stat']:.3f} {'[OK]' if harvey_pass else '[FAIL]'}")
        print(f"    Overall: {status}")

    if not any_pass:
        print("\n  ** No strategy passes all criteria. Static 50/50 + 12/VIX remains optimal. **")

    # ---- Build Results JSON ----
    output = {
        'experiment_id': 'K507',
        'title': 'Dynamic SPY/GLD Allocation Strategy',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'description': 'Test whether dynamic SPY/GLD allocation (VIX-based, momentum, risk parity, combined) can beat static 50/50 + 12/VIX',
        'data': {
            'assets': ['SPY', 'GLD'],
            'source': 'yfinance',
            'period': f"{common[0].date()} to {common[-1].date()}",
            'n_days': len(common),
            'vt_method': '12/VIX',
            'tx_cost': '0.05% per monthly rebalance',
        },
        'diagnostics': {
            'spy_ann_return': round(spy_ret.mean() * 252, 4),
            'spy_ann_vol': round(spy_ret.std() * np.sqrt(252), 4),
            'spy_skew': round(float(spy_skew), 3),
            'spy_excess_kurt': round(float(spy_kurt), 3),
            'gld_ann_return': round(gld_ret.mean() * 252, 4),
            'gld_ann_vol': round(gld_ret.std() * np.sqrt(252), 4),
            'gld_skew': round(float(gld_skew), 3),
            'gld_excess_kurt': round(float(gld_kurt), 3),
            'spy_gld_corr': round(spy_ret.corr(gld_ret), 3),
            'rolling_corr_mean': round(float(rolling_corr.mean()), 3),
            'rolling_corr_std': round(float(rolling_corr.std()), 3),
            'vix_regime_pct': {
                'low_lt15': round(vix_low, 3),
                'mid_15_25': round(vix_mid, 3),
                'high_gt25': round(vix_high, 3),
            },
        },
        'full_sample_results': {},
        'cross_oos': cross_oos_summary,
        'dm_tests': dm_results,
        'crisis_analysis': crisis_results,
        'year_by_year_win_rates': {name: f"{wins}/{len(years)}" for name, wins in win_counts.items()},
        'conclusion': '',
        'references': [
            'Asness, Moskowitz, Pedersen (2013) "Value and Momentum Everywhere", JF',
            'Qian (2005) "Risk Parity Portfolios", PanAgora',
            'K458 meta-analysis, N79 12/VIX, Q21 optimal retail portfolio',
            'DCC-GARCH SPY-GLD (knowledge): 2-asset RP weights independent of rho',
        ],
    }

    for name in strategies:
        m = full_results[name]['full_sample']
        output['full_sample_results'][name] = m

    # Conclusion
    best_name = max(
        ['vix_dynamic', 'momentum', 'inv_vol', 'combined'],
        key=lambda n: full_results[n]['full_sample']['sharpe']
    )
    best_sharpe = full_results[best_name]['full_sample']['sharpe']

    if any_pass:
        output['conclusion'] = f"Dynamic allocation improves on static 50/50. Best: {best_name} (Sharpe {best_sharpe:.3f}). Consider for strategy lineup."
    else:
        output['conclusion'] = (
            f"No dynamic allocation strategy passes all criteria (Sharpe improvement + "
            f"4/5 cross-OOS + Harvey t>3.0). Best candidate: {best_name} (Sharpe {best_sharpe:.3f} "
            f"vs benchmark {benchmark_sharpe:.3f}). Static 50/50 + 12/VIX remains the optimal "
            f"retail strategy. The lack of improvement is consistent with DCC-GARCH finding that "
            f"2-asset RP weights are independent of correlation — the diversification benefit "
            f"from 50/50 is already near-optimal analytically."
        )

    # Save results
    results_path = os.path.join(os.path.dirname(__file__), 'k507_dynamic_allocation_results.json')
    with open(results_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Results saved to: {results_path}")
    print(f"\n  Conclusion: {output['conclusion']}")

    return output


if __name__ == '__main__':
    main()
