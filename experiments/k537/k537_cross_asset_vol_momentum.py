#!/usr/bin/env python3
"""
K537: Cross-Asset Volatility Momentum for Equity Vol Timing
============================================================
Source: Codex GPT-5.4 suggestion #1 (2026-03-27)
Hypothesis: Vol shocks in rates, credit, FX, commodities LEAD equity vol.
            Cross-asset stress broadening before VIX catches up → better timing.

Data (yfinance, daily):
  - Equity vol: ^VIX
  - Rates vol: TLT realized vol (proxy for MOVE)
  - Credit stress: HYG-IEF spread return differential
  - FX vol: UUP realized vol
  - Commodity vol: GLD realized vol
  - Vol-of-vol: ^VVIX or rolling std of VIX changes

Design:
  1. RV5 = 5-day mean(|r|) for each asset
  2. Cross-asset stress breadth = count of asset classes with RV5 > 75th pctile
  3. Signals: stress z-score index, VIX complacency, stress momentum
  4. Strategy: breadth >= 3 & VIX < 20 → reduce to 20%; stress decaying & VIX high → add
  5. Benchmark: 12/VIX standard
  6. Cross-OOS: 2020-2021, 2022-2023, 2023-2024 (w=500 for rolling stats)

References:
  - Moreira & Muir (2017), "Volatility-Managed Portfolios", JoF
  - Knowledge N79-N84: 12/VIX baseline Sharpe ~0.607-0.682
  - VIX sufficiency confirmed 31+ times in knowledge base
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings('ignore')

# ── Configuration ──────────────────────────────────────────────
TICKERS = {
    'equity': 'SPY',
    'rates': 'TLT',
    'credit_hy': 'HYG',
    'credit_ig': 'IEF',
    'fx': 'UUP',
    'commodity': 'GLD',
    'vix': '^VIX',
    'vvix': '^VVIX',
}

START_DATE = '2012-01-01'   # UUP starts ~2007, but VVIX starts 2007; use 2012 for all
END_DATE = '2026-03-26'
RV_WINDOW = 5               # 5-day realized vol
ROLLING_W = 500             # rolling window for percentiles/z-scores
PCTILE_THRESH = 75          # stress threshold percentile
BREADTH_ALERT = 3           # breadth >= this triggers defensive
VIX_CALM = 20               # VIX below this = "complacent"
VIX_ELEVATED = 25           # VIX above this = "elevated"

# Cross-OOS periods
OOS_PERIODS = [
    ('2020-01-01', '2021-12-31', 'COVID+Recovery 2020-2021'),
    ('2022-01-01', '2023-12-31', 'Rate Hike 2022-2023'),
    ('2024-01-01', '2024-12-31', 'Recent 2024'),
]


def download_data():
    """Download all required data from yfinance."""
    print("Downloading data from yfinance...")
    all_tickers = list(TICKERS.values())
    data = yf.download(all_tickers, start=START_DATE, end=END_DATE, auto_adjust=True)

    # Handle multi-level columns
    if isinstance(data.columns, pd.MultiIndex):
        close = data['Close']
    else:
        close = data

    # Rename columns for clarity
    rename = {v: k for k, v in TICKERS.items()}
    close = close.rename(columns=rename)

    # Forward fill and drop initial NaN
    close = close.ffill().dropna()
    print(f"  Data shape: {close.shape}, range: {close.index[0].date()} to {close.index[-1].date()}")
    return close


def compute_returns(close):
    """Compute log returns for all assets."""
    returns = np.log(close / close.shift(1)).dropna()
    return returns


def compute_rv5(returns, window=5):
    """Compute 5-day realized vol: mean(|r|) over trailing window."""
    abs_ret = returns.abs()
    rv5 = abs_ret.rolling(window).mean()
    return rv5


def compute_credit_spread_signal(returns):
    """Credit stress = HYG - IEF return differential (negative = stress)."""
    if 'credit_hy' in returns.columns and 'credit_ig' in returns.columns:
        spread_ret = returns['credit_hy'] - returns['credit_ig']
        # Absolute credit spread movement as stress indicator
        rv5_credit = spread_ret.abs().rolling(RV_WINDOW).mean()
        return rv5_credit
    return None


def compute_vov(returns, close):
    """Vol-of-vol: rolling std of daily VIX changes."""
    if 'vvix' in close.columns:
        vvix = close['vvix']
        vov = vvix.pct_change().abs().rolling(RV_WINDOW).mean()
        return vov
    elif 'vix' in close.columns:
        vix_changes = close['vix'].pct_change()
        vov = vix_changes.rolling(20).std()
        return vov
    return None


def build_stress_signals(close, returns, rv5):
    """Build cross-asset stress signals."""
    # Non-equity asset classes for stress measurement
    stress_assets = ['rates', 'fx', 'commodity']
    credit_rv5 = compute_credit_spread_signal(returns)
    vov = compute_vov(returns, close)

    # Build stress DataFrame
    stress_df = pd.DataFrame(index=rv5.index)

    for asset in stress_assets:
        if asset in rv5.columns:
            stress_df[f'rv5_{asset}'] = rv5[asset]

    if credit_rv5 is not None:
        stress_df['rv5_credit'] = credit_rv5

    if vov is not None:
        stress_df['vov'] = vov

    stress_df = stress_df.dropna()

    # Rolling percentiles and z-scores
    n_assets = stress_df.shape[1]
    print(f"  Stress assets tracked: {n_assets} ({list(stress_df.columns)})")

    # Rolling 75th percentile threshold for each asset
    pctile_thresh = stress_df.rolling(ROLLING_W, min_periods=100).quantile(PCTILE_THRESH / 100)

    # Binary: is each asset above its 75th percentile?
    above_thresh = (stress_df > pctile_thresh).astype(int)

    # Stress breadth: count of stressed asset classes
    breadth = above_thresh.sum(axis=1)

    # Z-scores of each stress asset
    rolling_mean = stress_df.rolling(ROLLING_W, min_periods=100).mean()
    rolling_std = stress_df.rolling(ROLLING_W, min_periods=100).std()
    z_scores = (stress_df - rolling_mean) / rolling_std.replace(0, np.nan)

    # Composite stress index: mean z-score across non-equity assets
    stress_index = z_scores.mean(axis=1)

    # 5-day momentum of breadth
    breadth_momentum = breadth.diff(5)

    # VIX level
    vix = close['vix'].reindex(stress_df.index)

    signals = pd.DataFrame({
        'breadth': breadth,
        'stress_index': stress_index,
        'breadth_momentum': breadth_momentum,
        'vix': vix,
    }, index=stress_df.index).dropna()

    return signals


def strategy_cross_asset(signals, spy_returns, benchmark='12/VIX'):
    """
    Cross-asset vol timing strategy.

    Rules:
      - breadth >= 3 AND VIX < 20: "complacent market ignoring cross-asset stress" → 20% SPY
      - breadth >= 3 AND VIX >= 20: "stress acknowledged" → standard 12/VIX
      - stress_index declining (< -0.5) AND VIX > 25: "stress resolving, VIX still elevated" → 80% SPY
      - breadth_momentum >= 2 (rapidly rising stress): reduce to 30% regardless of VIX
      - Otherwise: standard 12/VIX
    """
    # Align
    common = signals.index.intersection(spy_returns.index)
    sig = signals.loc[common]
    ret = spy_returns.loc[common]

    # 12/VIX baseline weights
    vix = sig['vix']
    w_base = (12.0 / vix).clip(0, 1)
    # Smooth with 5-day MA
    w_base = w_base.rolling(5, min_periods=1).mean()

    # Cross-asset overlay weights
    w_cross = w_base.copy()

    # Rule 1: Cross-asset stress high but VIX complacent → defensive
    mask_complacent = (sig['breadth'] >= BREADTH_ALERT) & (vix < VIX_CALM)
    w_cross[mask_complacent] = 0.20

    # Rule 2: Rapidly rising stress breadth → defensive
    mask_rapid = sig['breadth_momentum'] >= 2
    w_cross[mask_rapid] = np.minimum(w_cross[mask_rapid], 0.30)

    # Rule 3: Stress resolving + VIX still elevated → aggressive (mean reversion)
    mask_resolve = (sig['stress_index'] < -0.5) & (vix > VIX_ELEVATED)
    w_cross[mask_resolve] = 0.80

    # Smooth overlay weights
    w_cross = w_cross.rolling(3, min_periods=1).mean()
    w_cross = w_cross.clip(0, 1)

    return ret, w_base, w_cross


def evaluate_strategy(ret, weights, label='Strategy'):
    """Compute Sharpe, MDD, cumulative return, and other metrics."""
    strat_ret = ret * weights
    cum = (1 + strat_ret).cumprod()
    running_max = cum.cummax()
    dd = cum / running_max - 1
    mdd = dd.min()

    ann_ret = strat_ret.mean() * 252
    ann_vol = strat_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    total_ret = cum.iloc[-1] - 1

    # Average weight
    avg_weight = weights.mean()

    # Sortino
    downside = strat_ret[strat_ret < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0

    return {
        'label': label,
        'sharpe': round(sharpe, 4),
        'ann_return': round(ann_ret, 4),
        'ann_vol': round(ann_vol, 4),
        'mdd': round(mdd, 4),
        'total_return': round(total_ret, 4),
        'sortino': round(sortino, 4),
        'avg_weight': round(avg_weight, 4),
        'n_days': len(ret),
    }


def dm_test(e1, e2, h=1):
    """Diebold-Mariano test (two-sided). e1, e2 = loss series."""
    d = e1 - e2
    d = d.dropna()
    n = len(d)
    if n < 30:
        return np.nan, np.nan
    d_mean = d.mean()
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    acov = 0
    for k in range(1, h):
        acov += 2 * np.cov(d[k:], d[:-k])[0, 1] * (1 - k / h) if len(d[k:]) > 1 else 0
    var_d = (gamma0 + acov) / n
    if var_d <= 0:
        return np.nan, np.nan
    dm_stat = d_mean / np.sqrt(var_d)
    from scipy import stats
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return round(dm_stat, 4), round(p_val, 4)


def lead_lag_analysis(signals, spy_returns, close):
    """
    Test whether cross-asset stress leads VIX changes.
    Regress VIX_{t+k} change on stress_index_t for k=1..10.
    """
    from scipy import stats as sp_stats

    common = signals.index.intersection(spy_returns.index)
    sig = signals.loc[common]
    vix = close['vix'].reindex(common)

    results = {}
    for lag in [1, 2, 3, 5, 10]:
        vix_future_change = vix.pct_change(lag).shift(-lag)
        mask = sig['stress_index'].notna() & vix_future_change.notna()
        x = sig['stress_index'][mask].values
        y = vix_future_change[mask].values
        if len(x) > 50:
            slope, intercept, r_value, p_value, std_err = sp_stats.linregress(x, y)
            results[f'lag_{lag}d'] = {
                'slope': round(slope, 6),
                'r_squared': round(r_value**2, 6),
                'p_value': round(p_value, 4),
                't_stat': round(slope / std_err, 3) if std_err > 0 else 0,
                'n': len(x),
            }
    return results


def cross_oos_evaluation(close, returns, rv5, signals, spy_returns):
    """Evaluate strategy on 3 separate OOS periods."""
    results = []
    for start, end, label in OOS_PERIODS:
        # IS: everything before the OOS period, starting from ROLLING_W days after data start
        mask_oos = (signals.index >= start) & (signals.index <= end)
        sig_oos = signals[mask_oos]
        ret_oos = spy_returns.reindex(sig_oos.index).dropna()

        if len(ret_oos) < 50:
            print(f"  Skipping {label}: only {len(ret_oos)} days")
            continue

        # Get common dates
        common = sig_oos.index.intersection(ret_oos.index)
        sig_oos = sig_oos.loc[common]
        ret_oos = ret_oos.loc[common]

        # Compute strategy weights
        vix_oos = sig_oos['vix']
        w_base = (12.0 / vix_oos).clip(0, 1).rolling(5, min_periods=1).mean()

        w_cross = w_base.copy()
        mask_complacent = (sig_oos['breadth'] >= BREADTH_ALERT) & (vix_oos < VIX_CALM)
        w_cross[mask_complacent] = 0.20
        mask_rapid = sig_oos['breadth_momentum'] >= 2
        w_cross[mask_rapid] = np.minimum(w_cross[mask_rapid], 0.30)
        mask_resolve = (sig_oos['stress_index'] < -0.5) & (vix_oos > VIX_ELEVATED)
        w_cross[mask_resolve] = 0.80
        w_cross = w_cross.rolling(3, min_periods=1).mean().clip(0, 1)

        # Buy and hold
        bh = evaluate_strategy(ret_oos, pd.Series(1.0, index=ret_oos.index), f'BuyHold ({label})')
        base = evaluate_strategy(ret_oos, w_base, f'12/VIX ({label})')
        cross = evaluate_strategy(ret_oos, w_cross, f'CrossAsset ({label})')

        # DM test: cross-asset vs 12/VIX using squared return errors
        loss_base = (ret_oos - ret_oos.mean())**2 * (1 - w_base)  # opportunity cost weighted
        loss_cross = (ret_oos - ret_oos.mean())**2 * (1 - w_cross)
        # Actually use return-based comparison: loss = -strategy_return (we want higher returns)
        loss_base_ret = -(ret_oos * w_base)
        loss_cross_ret = -(ret_oos * w_cross)
        dm_stat, dm_p = dm_test(loss_cross_ret, loss_base_ret, h=5)

        # Signal statistics
        n_complacent = mask_complacent.sum()
        n_rapid = mask_rapid.sum()
        n_resolve = mask_resolve.sum()
        n_override = n_complacent + n_rapid + n_resolve
        pct_override = round(100 * n_override / len(sig_oos), 1)

        result = {
            'period': label,
            'n_days': len(ret_oos),
            'buyhold': bh,
            'baseline_12vix': base,
            'cross_asset': cross,
            'sharpe_diff': round(cross['sharpe'] - base['sharpe'], 4),
            'mdd_diff': round(cross['mdd'] - base['mdd'], 4),
            'dm_stat': dm_stat,
            'dm_pvalue': dm_p,
            'signal_stats': {
                'n_complacent_alerts': int(n_complacent),
                'n_rapid_stress_alerts': int(n_rapid),
                'n_resolve_signals': int(n_resolve),
                'pct_days_overridden': pct_override,
            },
        }
        results.append(result)

        print(f"\n  === {label} ({len(ret_oos)} days) ===")
        print(f"    BuyHold:    Sharpe={bh['sharpe']:.3f}, MDD={bh['mdd']:.1%}")
        print(f"    12/VIX:     Sharpe={base['sharpe']:.3f}, MDD={base['mdd']:.1%}, AvgW={base['avg_weight']:.2f}")
        print(f"    CrossAsset: Sharpe={cross['sharpe']:.3f}, MDD={cross['mdd']:.1%}, AvgW={cross['avg_weight']:.2f}")
        print(f"    Sharpe diff: {cross['sharpe'] - base['sharpe']:+.4f}")
        print(f"    MDD diff:   {cross['mdd'] - base['mdd']:+.4f}")
        print(f"    DM test:    stat={dm_stat}, p={dm_p}")
        print(f"    Override %: {pct_override}% of days ({n_override}/{len(sig_oos)})")
        print(f"    Complacent alerts: {n_complacent}, Rapid stress: {n_rapid}, Resolve: {n_resolve}")

    return results


def descriptive_stats(signals, spy_returns):
    """Descriptive statistics of the stress signals."""
    common = signals.index.intersection(spy_returns.index)
    sig = signals.loc[common]

    stats = {}
    for col in sig.columns:
        s = sig[col].dropna()
        stats[col] = {
            'mean': round(s.mean(), 4),
            'std': round(s.std(), 4),
            'min': round(s.min(), 4),
            'max': round(s.max(), 4),
            'skew': round(s.skew(), 4),
            'kurt': round(s.kurtosis(), 4),
            'pct_above_0': round(100 * (s > 0).mean(), 1),
        }

    # Breadth distribution
    breadth = sig['breadth']
    breadth_dist = {}
    for i in range(int(breadth.max()) + 1):
        breadth_dist[str(i)] = round(100 * (breadth == i).mean(), 1)
    stats['breadth_distribution_pct'] = breadth_dist

    # Correlation between stress index and future VIX changes
    vix = sig['vix']
    for lag in [1, 5, 10, 20]:
        vix_change = vix.pct_change(lag).shift(-lag)
        corr = sig['stress_index'].corr(vix_change)
        stats[f'stress_vs_vix_change_{lag}d_corr'] = round(corr, 4) if not np.isnan(corr) else None

    return stats


def full_sample_evaluation(signals, spy_returns, close):
    """Full sample evaluation for overall picture."""
    ret, w_base, w_cross = strategy_cross_asset(signals, spy_returns)

    bh = evaluate_strategy(ret, pd.Series(1.0, index=ret.index), 'BuyHold (Full)')
    base = evaluate_strategy(ret, w_base, '12/VIX (Full)')
    cross = evaluate_strategy(ret, w_cross, 'CrossAsset (Full)')

    # DM test
    loss_base = -(ret * w_base)
    loss_cross = -(ret * w_cross)
    dm_stat, dm_p = dm_test(loss_cross, loss_base, h=5)

    print(f"\n  === Full Sample ({len(ret)} days) ===")
    print(f"    BuyHold:    Sharpe={bh['sharpe']:.3f}, MDD={bh['mdd']:.1%}")
    print(f"    12/VIX:     Sharpe={base['sharpe']:.3f}, MDD={base['mdd']:.1%}")
    print(f"    CrossAsset: Sharpe={cross['sharpe']:.3f}, MDD={cross['mdd']:.1%}")
    print(f"    DM test:    stat={dm_stat}, p={dm_p}")

    return {
        'buyhold': bh,
        'baseline_12vix': base,
        'cross_asset': cross,
        'dm_stat': dm_stat,
        'dm_pvalue': dm_p,
    }


def event_study_analysis(signals, spy_returns, close):
    """
    Event study: what happens to SPY in the 1-20 days AFTER
    cross-asset stress breadth hits >= 3 while VIX is below 20?
    This tests the core timing hypothesis.
    """
    common = signals.index.intersection(spy_returns.index)
    sig = signals.loc[common]
    ret = spy_returns.loc[common]
    vix = sig['vix']

    # Identify "complacent stress" events: first day of breadth>=3 & VIX<20
    # (require 10-day gap between events to avoid clustering)
    stress_complacent = (sig['breadth'] >= BREADTH_ALERT) & (vix < VIX_CALM)

    event_dates = []
    last_event = None
    for date, is_event in stress_complacent.items():
        if is_event:
            if last_event is None or (date - last_event).days >= 10:
                event_dates.append(date)
                last_event = date

    if len(event_dates) < 3:
        return {'n_events': len(event_dates), 'message': 'Too few events for event study'}

    # Forward returns after events
    horizons = [1, 3, 5, 10, 20]
    forward_rets = {h: [] for h in horizons}
    forward_vix_changes = {h: [] for h in horizons}

    for edate in event_dates:
        try:
            idx = ret.index.get_loc(edate)
        except KeyError:
            continue
        for h in horizons:
            if idx + h < len(ret):
                fwd = ret.iloc[idx+1:idx+h+1].sum()  # cumulative forward return
                forward_rets[h].append(fwd)
                # VIX change
                if idx + h < len(vix):
                    vix_chg = (vix.iloc[idx+h] - vix.iloc[idx]) / vix.iloc[idx]
                    forward_vix_changes[h].append(vix_chg)

    from scipy import stats as sp_stats

    results = {
        'n_events': len(event_dates),
        'event_dates': [str(d.date()) for d in event_dates[:10]],  # first 10
    }

    for h in horizons:
        rets_arr = np.array(forward_rets[h])
        vix_arr = np.array(forward_vix_changes[h])
        if len(rets_arr) >= 3:
            t_stat, t_p = sp_stats.ttest_1samp(rets_arr, 0)
            results[f'{h}d_forward'] = {
                'mean_return': round(np.mean(rets_arr), 4),
                'std': round(np.std(rets_arr, ddof=1), 4),
                't_stat': round(t_stat, 3),
                'p_value': round(t_p, 4),
                'n': len(rets_arr),
                'pct_negative': round(100 * (rets_arr < 0).mean(), 1),
            }
        if len(vix_arr) >= 3:
            results[f'{h}d_vix_change'] = {
                'mean': round(np.mean(vix_arr), 4),
                'median': round(np.median(vix_arr), 4),
                'pct_increase': round(100 * (vix_arr > 0).mean(), 1),
            }

    return results


def main():
    print("=" * 70)
    print("K537: Cross-Asset Volatility Momentum for Equity Vol Timing")
    print("=" * 70)
    print(f"Config: RV_WINDOW={RV_WINDOW}, ROLLING_W={ROLLING_W}, "
          f"PCTILE={PCTILE_THRESH}, BREADTH_ALERT={BREADTH_ALERT}")

    # Step 1: Download data
    close = download_data()

    # Check VVIX availability
    has_vvix = 'vvix' in close.columns and close['vvix'].notna().sum() > 100
    print(f"  VVIX available: {has_vvix} ({close.get('vvix', pd.Series()).notna().sum()} valid points)")

    # Step 2: Returns
    returns = compute_returns(close)
    spy_returns = returns['equity']

    # Step 3: Realized vols
    rv5 = compute_rv5(returns, RV_WINDOW)

    # Step 4: Build stress signals
    print("\nBuilding cross-asset stress signals...")
    signals = build_stress_signals(close, returns, rv5)
    print(f"  Signals computed: {signals.shape[0]} days, columns: {list(signals.columns)}")

    # Step 5: Descriptive statistics
    print("\n[1] Descriptive Statistics of Stress Signals")
    desc_stats = descriptive_stats(signals, spy_returns)
    for col, stats in desc_stats.items():
        if isinstance(stats, dict) and 'mean' in stats:
            print(f"    {col}: mean={stats['mean']:.4f}, std={stats['std']:.4f}, "
                  f"skew={stats.get('skew', 'N/A')}, kurt={stats.get('kurt', 'N/A')}")
    print(f"  Breadth distribution: {desc_stats.get('breadth_distribution_pct', {})}")
    for key in ['stress_vs_vix_change_1d_corr', 'stress_vs_vix_change_5d_corr',
                'stress_vs_vix_change_10d_corr', 'stress_vs_vix_change_20d_corr']:
        if key in desc_stats:
            print(f"    {key}: {desc_stats[key]}")

    # Step 6: Lead-lag analysis
    print("\n[2] Lead-Lag Analysis: Does cross-asset stress predict VIX changes?")
    leadlag = lead_lag_analysis(signals, spy_returns, close)
    for lag, res in leadlag.items():
        sig_str = "***" if res['p_value'] < 0.01 else "**" if res['p_value'] < 0.05 else "*" if res['p_value'] < 0.10 else ""
        print(f"    {lag}: slope={res['slope']:.6f}, R²={res['r_squared']:.6f}, "
              f"t={res['t_stat']:.3f}, p={res['p_value']:.4f} {sig_str}")

    # Step 7: Event study
    print("\n[3] Event Study: SPY returns after 'complacent stress' events")
    event_results = event_study_analysis(signals, spy_returns, close)
    print(f"  N events (breadth>=3 & VIX<20): {event_results['n_events']}")
    if 'event_dates' in event_results:
        print(f"  Sample dates: {event_results['event_dates'][:5]}")
    for h in [1, 3, 5, 10, 20]:
        key = f'{h}d_forward'
        if key in event_results:
            r = event_results[key]
            print(f"    {h}-day: mean={r['mean_return']:+.4f}, t={r['t_stat']:.3f}, "
                  f"p={r['p_value']:.4f}, %neg={r['pct_negative']:.0f}%")
        vix_key = f'{h}d_vix_change'
        if vix_key in event_results:
            v = event_results[vix_key]
            print(f"    {h}-day VIX: mean={v['mean']:+.4f}, %increase={v['pct_increase']:.0f}%")

    # Step 8: Full sample strategy evaluation
    print("\n[4] Full Sample Strategy Evaluation")
    full_results = full_sample_evaluation(signals, spy_returns, close)

    # Step 9: Cross-OOS evaluation
    print("\n[5] Cross-OOS Evaluation")
    oos_results = cross_oos_evaluation(close, returns, rv5, signals, spy_returns)

    # Step 10: Summary and conclusion
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Check if cross-asset timing adds value
    oos_sharpe_diffs = [r['sharpe_diff'] for r in oos_results]
    oos_mdd_diffs = [r['mdd_diff'] for r in oos_results]
    oos_dm_pvalues = [r['dm_pvalue'] for r in oos_results if r['dm_pvalue'] is not np.nan and r['dm_pvalue'] is not None]

    avg_sharpe_diff = np.mean(oos_sharpe_diffs) if oos_sharpe_diffs else 0
    avg_mdd_diff = np.mean(oos_mdd_diffs) if oos_mdd_diffs else 0
    any_significant = any(p < 0.05 for p in oos_dm_pvalues) if oos_dm_pvalues else False

    # Lead-lag significance
    leadlag_significant = any(
        res['p_value'] < 0.05 for res in leadlag.values()
    ) if leadlag else False

    # Event study significance
    event_significant = False
    if '5d_forward' in event_results:
        event_significant = event_results['5d_forward'].get('p_value', 1) < 0.05

    conclusion_parts = []
    if leadlag_significant:
        conclusion_parts.append("Cross-asset stress does lead VIX changes (statistically significant)")
    else:
        conclusion_parts.append("Cross-asset stress does NOT reliably lead VIX changes")

    if event_significant:
        conclusion_parts.append("Complacent stress events predict negative SPY forward returns")
    else:
        conclusion_parts.append("Complacent stress events do NOT predict SPY returns significantly")

    if avg_sharpe_diff > 0.05 and any_significant:
        conclusion_parts.append("Cross-asset timing IMPROVES on 12/VIX (significant)")
        verdict = "POSITIVE — cross-asset vol momentum adds value"
    elif avg_sharpe_diff > 0:
        conclusion_parts.append("Slight Sharpe improvement but NOT statistically significant")
        verdict = "MARGINAL — improvement too small to be reliable"
    else:
        conclusion_parts.append("Cross-asset timing does NOT improve on 12/VIX")
        verdict = "NULL RESULT — VIX sufficiency confirmed again"

    for part in conclusion_parts:
        print(f"  - {part}")
    print(f"\n  VERDICT: {verdict}")
    print(f"  Avg OOS Sharpe diff: {avg_sharpe_diff:+.4f}")
    print(f"  Avg OOS MDD diff:   {avg_mdd_diff:+.4f}")

    # Compile results JSON
    results_json = {
        'experiment_id': 'K537',
        'title': 'Cross-Asset Volatility Momentum for Equity Vol Timing',
        'source': 'Codex GPT-5.4 suggestion #1 (2026-03-27)',
        'hypothesis': 'Vol shocks in rates, credit, FX, commodities LEAD equity vol; '
                      'cross-asset stress broadening can time SPY better than 12/VIX alone',
        'data_source': 'yfinance (SPY, TLT, HYG, IEF, UUP, GLD, ^VIX, ^VVIX)',
        'data_period': f'{close.index[0].date()} to {close.index[-1].date()}',
        'sample_size': len(close),
        'config': {
            'rv_window': RV_WINDOW,
            'rolling_w': ROLLING_W,
            'percentile_threshold': PCTILE_THRESH,
            'breadth_alert': BREADTH_ALERT,
            'vix_calm': VIX_CALM,
            'vix_elevated': VIX_ELEVATED,
            'oos_periods': OOS_PERIODS,
        },
        'descriptive_stats': desc_stats,
        'lead_lag_analysis': leadlag,
        'event_study': event_results,
        'full_sample': full_results,
        'cross_oos': oos_results,
        'summary': {
            'avg_oos_sharpe_diff': round(avg_sharpe_diff, 4),
            'avg_oos_mdd_diff': round(avg_mdd_diff, 4),
            'any_dm_significant': any_significant,
            'leadlag_significant': leadlag_significant,
            'event_study_significant': event_significant,
            'verdict': verdict,
            'conclusion': conclusion_parts,
        },
        'references': [
            'Moreira & Muir (2017), Volatility-Managed Portfolios, JoF 72(4):1611-1644',
            'Knowledge N79-N84: 12/VIX baseline (Sharpe ~0.60-0.68)',
            'VIX sufficiency confirmed 31+ times in knowledge base',
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    # Save results
    out_path = Path('experiments/k537_cross_asset_vol_momentum_results.json')
    with open(out_path, 'w') as f:
        json.dump(results_json, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return results_json


if __name__ == '__main__':
    results = main()
