#!/usr/bin/env python3
"""
K762: Action-First Meta-Model — Strategy Consensus Trading Policy
=================================================================
[提出: Codex (7th suggestion), 執行: Claude]

Can we learn a trading policy from our own 14-strategy ensemble?
Rather than forecasting volatility, we use the "wisdom of crowds" —
if most of our strategies agree on direction, follow the consensus.

Parts:
  A) Extract meta-features from paper_trading.json + market data
  B) Build consensus signal (% of strategies bullish)
  C) Backtest consensus-based SPY/GLD allocation
  D) Feature importance: which meta-feature best predicts next-month return?

References:
  - López de Prado (2018) Advances in Financial Machine Learning — meta-labeling
  - Surowiecki (2004) The Wisdom of Crowds
  - Timmermann (2006) Forecast Combinations, Handbook of Economic Forecasting
  - K756: Meta-labeling null result (daily AUC 0.48-0.52 = coin flip)
  - K475/K482: Equal-weight ensemble beats sophisticated weighting

Data: paper_trading.json + yfinance (^VIX, SPY, GLD)
Period: 2023-01-04 to present (COMMON_START)
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
import warnings
import os
warnings.filterwarnings('ignore')

COMMON_START = '2023-01-04'
TX_COST_BPS = 10  # 10 bps per leg per trade
RESULTS_PATH = 'experiments/k762_meta_model_results.json'

# ============================================================
# Part A: Extract meta-features from paper_trading.json
# ============================================================

def load_paper_trading():
    """Load paper trading data and build daily DataFrames."""
    with open('storage/paper_trading.json') as f:
        pt = json.load(f)

    all_strats = [k for k in pt.keys() if k != '_market_daily']
    market = pt['_market_daily']

    # Build strategy weight DataFrame (SPY weight for US strategies, total risky weight for others)
    weight_records = {}
    for strat in all_strats:
        entries = pt[strat]['entries']
        strat_weights = {}
        for e in entries:
            date = e.get('data_date') or e.get('trade_date')
            if date and e.get('portfolio_return') is not None:
                # Total risky asset weight (sum of all non-cash weights)
                w = e.get('weights', {})
                total_risky = sum(w.values())
                strat_weights[date] = total_risky
        weight_records[strat] = strat_weights

    # Build portfolio return DataFrame
    return_records = {}
    for strat in all_strats:
        entries = pt[strat]['entries']
        strat_returns = {}
        for e in entries:
            date = e.get('data_date') or e.get('trade_date')
            if date and e.get('portfolio_return') is not None:
                strat_returns[date] = e['portfolio_return']
        return_records[strat] = strat_returns

    weights_df = pd.DataFrame(weight_records)
    weights_df.index = pd.to_datetime(weights_df.index)
    weights_df = weights_df.sort_index()

    returns_df = pd.DataFrame(return_records)
    returns_df.index = pd.to_datetime(returns_df.index)
    returns_df = returns_df.sort_index()

    # Market daily
    market_df = pd.DataFrame.from_dict(market, orient='index')
    market_df.index = pd.to_datetime(market_df.index)
    market_df = market_df.sort_index()

    return weights_df, returns_df, market_df, all_strats


def download_market_data():
    """Download VIX, SPY, GLD from yfinance."""
    tickers = ['^VIX', 'SPY', 'GLD']
    data = {}
    for t in tickers:
        df = yf.download(t, start='2022-06-01', end=datetime.now().strftime('%Y-%m-%d'),
                        progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        data[t] = df
    return data


def build_meta_features(weights_df, returns_df, market_df, market_data, all_strats):
    """Build daily meta-features from strategy weights and market data."""

    # US-focused strategies (trade SPY or SPY+GLD)
    us_strats = ['slow_vt', 'risk_parity', 'simple_12vix', 'recommended_5050',
                 'vix_cond_leverage', 'piecewise_conservative', 'fear_dca', 'adaptive_tier']

    # Only use US strategies for consensus (TW/JP strategies have different trading days)
    us_weights = weights_df[us_strats].copy()

    features = pd.DataFrame(index=us_weights.index)

    # 1. VIX level
    vix = market_data['^VIX']['Close'].copy()
    vix.index = vix.index.tz_localize(None) if vix.index.tz else vix.index
    features['vix_level'] = vix.reindex(features.index, method='ffill')

    # 2. VIX 5-day change (momentum)
    features['vix_5d_change'] = features['vix_level'].pct_change(5)

    # 3. SPY 20-day realized vol (annualized)
    spy_close = market_data['SPY']['Close'].copy()
    spy_close.index = spy_close.index.tz_localize(None) if spy_close.index.tz else spy_close.index
    spy_ret = spy_close.pct_change()
    features['spy_rv20'] = spy_ret.rolling(20).std().reindex(features.index, method='ffill') * np.sqrt(252)

    # 4. Number of strategies "bullish" (total risky weight > 60%)
    bullish_threshold = 0.60
    bearish_threshold = 0.40

    n_bullish = (us_weights > bullish_threshold).sum(axis=1)
    n_bearish = (us_weights < bearish_threshold).sum(axis=1)
    n_total = us_weights.notna().sum(axis=1)

    features['n_bullish'] = n_bullish
    features['n_bearish'] = n_bearish
    features['n_strategies'] = n_total

    # 5. Strategy agreement ratio (% with same direction as majority)
    bullish_pct = n_bullish / n_total
    features['bullish_pct'] = bullish_pct
    features['agreement_ratio'] = np.maximum(bullish_pct, 1 - bullish_pct)

    # 6. Average strategy weight (proxy for overall risk appetite)
    features['avg_weight'] = us_weights.mean(axis=1)

    # 7. Weight dispersion (std of weights across strategies)
    features['weight_dispersion'] = us_weights.std(axis=1)

    # 8. SPY momentum (20-day return)
    features['spy_mom_20d'] = spy_close.pct_change(20).reindex(features.index, method='ffill')

    # 9. GLD momentum (20-day return)
    gld_close = market_data['GLD']['Close'].copy()
    gld_close.index = gld_close.index.tz_localize(None) if gld_close.index.tz else gld_close.index
    features['gld_mom_20d'] = gld_close.pct_change(20).reindex(features.index, method='ffill')

    # 10. VIX regime (percentile rank over trailing 252 days)
    features['vix_percentile'] = features['vix_level'].rolling(252, min_periods=60).rank(pct=True)

    return features, us_strats


# ============================================================
# Part B: Consensus Signal
# ============================================================

def build_consensus_signal(features):
    """Build consensus signal based on strategy agreement.

    Rules:
    - >70% bullish → strong consensus → high allocation (80% risky)
    - <30% bullish → strong bearish → low allocation (20% risky)
    - 30-70% → mixed → default (50%)

    Also build:
    - Proportional: weight = bullish_pct
    - VIX-adjusted: consensus * VIX percentile adjustment
    """
    signals = pd.DataFrame(index=features.index)

    bp = features['bullish_pct']

    # Signal 1: Discrete consensus (3-tier)
    discrete = pd.Series(0.5, index=features.index)
    discrete[bp > 0.70] = 0.80
    discrete[bp < 0.30] = 0.20
    signals['discrete_consensus'] = discrete

    # Signal 2: Proportional consensus (continuous)
    # Map bullish_pct [0, 1] → allocation [0.2, 0.8]
    signals['proportional_consensus'] = 0.2 + 0.6 * bp

    # Signal 3: Average weight (direct use as allocation)
    signals['avg_weight_signal'] = features['avg_weight'].clip(0.1, 0.9)

    # Signal 4: VIX-adjusted consensus
    # When VIX percentile is high (scary), scale down even if consensus is bullish
    vix_adj = 1.0 - 0.5 * features['vix_percentile'].fillna(0.5)
    signals['vix_adj_consensus'] = (0.2 + 0.6 * bp) * vix_adj
    signals['vix_adj_consensus'] = signals['vix_adj_consensus'].clip(0.1, 0.9)

    # Signal 5: Agreement-weighted consensus
    # High agreement → follow consensus more aggressively
    agree = features['agreement_ratio'].fillna(0.5)
    base = 0.5 + (bp - 0.5) * 2  # Scale direction
    signals['agreement_weighted'] = 0.5 + (base - 0.5) * agree
    signals['agreement_weighted'] = signals['agreement_weighted'].clip(0.1, 0.9)

    return signals


# ============================================================
# Part C: Backtest
# ============================================================

def backtest_strategy(signal_weights, spy_ret, gld_ret, name, rebal_freq='monthly',
                      tx_cost_bps=TX_COST_BPS):
    """Backtest a SPY/GLD strategy with proper lag and TX costs.

    signal_weights: Series of SPY allocation (0-1), rest goes to GLD
    Uses signal.shift(1) for proper lag.
    """
    # CRITICAL: shift signal by 1 day (use yesterday's signal for today's return)
    lagged_signal = signal_weights.shift(1)

    # Align all series
    common_idx = lagged_signal.dropna().index.intersection(spy_ret.dropna().index).intersection(gld_ret.dropna().index)
    common_idx = common_idx[common_idx >= COMMON_START]

    sig = lagged_signal.reindex(common_idx)
    sr = spy_ret.reindex(common_idx)
    gr = gld_ret.reindex(common_idx)

    # Monthly rebalancing: only change weights at month boundaries
    if rebal_freq == 'monthly':
        # Mark first day of each month
        months = sig.index.to_period('M')
        first_of_month = ~months.duplicated()

        # Forward-fill signal within months (only update at month start)
        monthly_sig = sig.copy()
        monthly_sig[~first_of_month] = np.nan
        monthly_sig = monthly_sig.ffill()
        sig = monthly_sig

    # Portfolio return: w_spy * r_spy + w_gld * r_gld
    # w_gld = 1 - w_spy (fully invested, no cash for simplicity in backtest)
    port_ret = sig * sr + (1 - sig) * gr

    # Transaction costs: charge on both legs when weights change
    weight_change = sig.diff().abs()
    # Each leg: SPY change + GLD change (= 2 * SPY change since GLD = 1-SPY)
    total_turnover = 2 * weight_change  # both legs
    tx_drag = total_turnover * tx_cost_bps / 10000

    port_ret_net = port_ret - tx_drag

    # Statistics
    n_days = len(port_ret_net.dropna())
    ann_ret = port_ret_net.mean() * 252
    ann_vol = port_ret_net.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = (1 + port_ret_net).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = port_ret_net[port_ret_net < 0]
    downside_vol = downside.std() * np.sqrt(252)
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0

    return {
        'name': name,
        'n_days': n_days,
        'ann_return': round(ann_ret, 4),
        'ann_vol': round(ann_vol, 4),
        'sharpe': round(sharpe, 4),
        'mdd': round(mdd, 4),
        'calmar': round(calmar, 4),
        'sortino': round(sortino, 4),
        'avg_spy_weight': round(sig.mean(), 4),
        'turnover_pa': round(total_turnover.sum() / (n_days / 252), 4),
        'tx_drag_pa': round(tx_drag.sum() / (n_days / 252) * 10000, 2),  # bps/year
    }, port_ret_net, cum


def cross_oos_test(signal_weights, spy_ret, gld_ret, name, n_periods=5):
    """Cross-OOS: split into n non-overlapping periods, test each as OOS."""
    # Use full available range
    lagged_signal = signal_weights.shift(1)
    common_idx = lagged_signal.dropna().index.intersection(spy_ret.dropna().index).intersection(gld_ret.dropna().index)
    common_idx = common_idx[common_idx >= COMMON_START]

    # Split into n_periods
    total_days = len(common_idx)
    period_size = total_days // n_periods

    results = []
    for i in range(n_periods):
        start = common_idx[i * period_size]
        end = common_idx[min((i + 1) * period_size - 1, total_days - 1)]

        mask = (signal_weights.index >= start) & (signal_weights.index <= end)
        sub_signal = signal_weights[mask]

        stats, _, _ = backtest_strategy(sub_signal, spy_ret, gld_ret,
                                         f'{name}_P{i+1}', rebal_freq='monthly')
        stats['period'] = f'{start.strftime("%Y-%m-%d")} to {end.strftime("%Y-%m-%d")}'
        results.append(stats)

    return results


# ============================================================
# Part D: Feature Importance
# ============================================================

def feature_importance_analysis(features, spy_ret, gld_ret):
    """Which meta-feature best predicts next-month portfolio return?"""
    from scipy import stats as scipy_stats

    # Monthly returns (50/50 portfolio as target)
    spy_m = spy_ret.resample('ME').sum()
    gld_m = gld_ret.resample('ME').sum()
    port_m = 0.5 * spy_m + 0.5 * gld_m

    # Monthly features (end-of-month values, lagged by 1 month)
    feat_m = features.resample('ME').last()

    # Align
    common = feat_m.index.intersection(port_m.dropna().index)
    feat_m = feat_m.reindex(common)
    port_m = port_m.reindex(common)

    # Shift features by 1 month (predict NEXT month return)
    feat_lagged = feat_m.shift(1)

    # Drop NaN
    valid = feat_lagged.dropna(how='all').index.intersection(port_m.dropna().index)
    feat_lagged = feat_lagged.reindex(valid)
    port_m = port_m.reindex(valid)

    results = {}
    feature_names = ['vix_level', 'vix_5d_change', 'spy_rv20', 'bullish_pct',
                     'agreement_ratio', 'avg_weight', 'weight_dispersion',
                     'spy_mom_20d', 'gld_mom_20d', 'vix_percentile']

    for feat in feature_names:
        if feat in feat_lagged.columns:
            x = feat_lagged[feat].dropna()
            y = port_m.reindex(x.index).dropna()
            x = x.reindex(y.index)

            if len(x) > 10:
                corr, pval = scipy_stats.pearsonr(x, y)
                slope, intercept, r, p, se = scipy_stats.linregress(x, y)
                results[feat] = {
                    'corr': round(corr, 4),
                    'pval': round(pval, 4),
                    'r_squared': round(r**2, 4),
                    'slope': round(slope, 6),
                    'n_months': len(x),
                }

    return results


# ============================================================
# Main Execution
# ============================================================

def main():
    print("=" * 70)
    print("K762: Action-First Meta-Model — Strategy Consensus Trading Policy")
    print("=" * 70)

    # Step 1: Load data
    print("\n[1/6] Loading paper trading data...")
    weights_df, returns_df, market_df, all_strats = load_paper_trading()
    print(f"  Loaded {len(all_strats)} strategies, {len(weights_df)} days")
    print(f"  Date range: {weights_df.index[0].strftime('%Y-%m-%d')} to {weights_df.index[-1].strftime('%Y-%m-%d')}")

    print("\n[2/6] Downloading market data...")
    market_data = download_market_data()

    spy_close = market_data['SPY']['Close'].copy()
    spy_close.index = spy_close.index.tz_localize(None) if spy_close.index.tz else spy_close.index
    gld_close = market_data['GLD']['Close'].copy()
    gld_close.index = gld_close.index.tz_localize(None) if gld_close.index.tz else gld_close.index

    spy_ret = spy_close.pct_change()
    gld_ret = gld_close.pct_change()

    # Step 2: Build meta-features
    print("\n[3/6] Building meta-features...")
    features, us_strats = build_meta_features(weights_df, returns_df, market_df,
                                               market_data, all_strats)
    print(f"  US strategies used for consensus: {us_strats}")
    print(f"  Features shape: {features.shape}")
    print(f"  Feature summary:")
    for col in features.columns:
        vals = features[col].dropna()
        if len(vals) > 0:
            print(f"    {col:25s}: mean={vals.mean():.4f}, std={vals.std():.4f}, "
                  f"min={vals.min():.4f}, max={vals.max():.4f}")

    # Step 3: Build consensus signals
    print("\n[4/6] Building consensus signals...")
    signals = build_consensus_signal(features)
    print(f"  Signal types: {list(signals.columns)}")
    for col in signals.columns:
        vals = signals[col].dropna()
        print(f"    {col:30s}: mean={vals.mean():.4f}, std={vals.std():.4f}")

    # Step 4: Backtest all strategies
    print("\n[5/6] Backtesting strategies...")

    # Baselines
    baselines = {
        'BH_5050': pd.Series(0.5, index=features.index),
        'BH_SPY': pd.Series(1.0, index=features.index),
        '12/VIX': (12 / features['vix_level']).clip(0, 1),
    }

    all_results = []
    all_cumrets = {}

    # Backtest baselines
    for name, sig in baselines.items():
        stats, ret, cum = backtest_strategy(sig, spy_ret, gld_ret, name,
                                            rebal_freq='daily' if name == 'BH_5050' else 'monthly')
        all_results.append(stats)
        all_cumrets[name] = cum
        print(f"  {name:30s}: Sharpe={stats['sharpe']:.4f}, MDD={stats['mdd']:.4f}, "
              f"Ann.Ret={stats['ann_return']:.4f}")

    # Backtest consensus signals
    for col in signals.columns:
        stats, ret, cum = backtest_strategy(signals[col], spy_ret, gld_ret,
                                            f'Consensus_{col}', rebal_freq='monthly')
        all_results.append(stats)
        all_cumrets[f'Consensus_{col}'] = cum
        print(f"  Consensus_{col:20s}: Sharpe={stats['sharpe']:.4f}, MDD={stats['mdd']:.4f}, "
              f"Ann.Ret={stats['ann_return']:.4f}")

    # Rank by Sharpe
    all_results.sort(key=lambda x: x['sharpe'], reverse=True)
    print("\n  === RANKING BY SHARPE ===")
    for i, r in enumerate(all_results):
        print(f"  {i+1}. {r['name']:35s} Sharpe={r['sharpe']:.4f} MDD={r['mdd']:.4f} "
              f"Ann.Ret={r['ann_return']:.4f} Sortino={r['sortino']:.4f}")

    # Step 5: Cross-OOS
    print("\n[5b/6] Cross-OOS validation (5 periods)...")

    # Test best consensus signal vs baselines
    best_consensus_name = None
    best_consensus_sharpe = -999
    for r in all_results:
        if r['name'].startswith('Consensus_'):
            if r['sharpe'] > best_consensus_sharpe:
                best_consensus_sharpe = r['sharpe']
                best_consensus_name = r['name'].replace('Consensus_', '')

    print(f"  Best consensus signal: {best_consensus_name}")

    oos_strategies = {
        'BH_5050': baselines['BH_5050'],
        '12/VIX': baselines['12/VIX'],
        f'Consensus_{best_consensus_name}': signals[best_consensus_name],
    }
    # Also test proportional and avg_weight
    for extra in ['proportional_consensus', 'avg_weight_signal']:
        if extra != best_consensus_name:
            oos_strategies[f'Consensus_{extra}'] = signals[extra]

    oos_results = {}
    for name, sig in oos_strategies.items():
        oos = cross_oos_test(sig, spy_ret, gld_ret, name, n_periods=5)
        oos_results[name] = oos
        sharpes = [r['sharpe'] for r in oos]
        wins = sum(1 for r in oos if r['sharpe'] > 0)
        print(f"  {name:35s}: Sharpes={[r['sharpe'] for r in oos]}, "
              f"Mean={np.mean(sharpes):.4f}, Wins={wins}/5")

    # Cross-OOS: consensus vs 50/50
    print("\n  === CROSS-OOS: CONSENSUS vs 50/50 ===")
    bh_sharpes = [r['sharpe'] for r in oos_results['BH_5050']]
    for name in oos_strategies:
        if name == 'BH_5050':
            continue
        strat_sharpes = [r['sharpe'] for r in oos_results[name]]
        wins = sum(1 for s, b in zip(strat_sharpes, bh_sharpes) if s > b)
        print(f"  {name:35s} beats 50/50 in {wins}/5 periods")

    # Step 6: Feature importance
    print("\n[6/6] Feature importance analysis...")
    feat_imp = feature_importance_analysis(features, spy_ret, gld_ret)
    print(f"  {'Feature':25s} {'Corr':>8s} {'p-value':>8s} {'R²':>8s} {'N months':>10s}")
    print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")
    for feat, vals in sorted(feat_imp.items(), key=lambda x: abs(x[1]['corr']), reverse=True):
        print(f"  {feat:25s} {vals['corr']:8.4f} {vals['pval']:8.4f} {vals['r_squared']:8.4f} {vals['n_months']:10d}")

    # ============================================================
    # Descriptive Statistics
    # ============================================================
    print("\n" + "=" * 70)
    print("DESCRIPTIVE STATISTICS")
    print("=" * 70)

    # Strategy agreement over time
    print("\n  Strategy Agreement Distribution:")
    bp = features['bullish_pct'].dropna()
    print(f"    Mean bullish%: {bp.mean():.3f}")
    print(f"    Std:           {bp.std():.3f}")
    print(f"    Days >70% bullish: {(bp > 0.7).sum()} ({(bp > 0.7).mean()*100:.1f}%)")
    print(f"    Days <30% bullish: {(bp < 0.3).sum()} ({(bp < 0.3).mean()*100:.1f}%)")
    print(f"    Days 30-70% (mixed): {((bp >= 0.3) & (bp <= 0.7)).sum()} "
          f"({((bp >= 0.3) & (bp <= 0.7)).mean()*100:.1f}%)")

    # Correlation between consensus and next-day return
    from scipy import stats as scipy_stats
    port_daily = 0.5 * spy_ret + 0.5 * gld_ret
    consensus_lagged = features['bullish_pct'].shift(1)  # proper lag

    common = consensus_lagged.dropna().index.intersection(port_daily.dropna().index)
    common = common[common >= COMMON_START]

    if len(common) > 30:
        x = consensus_lagged.reindex(common)
        y = port_daily.reindex(common)
        corr, pval = scipy_stats.pearsonr(x, y)
        print(f"\n  Daily: bullish_pct(t-1) vs portfolio_return(t)")
        print(f"    Corr: {corr:.4f}, p-value: {pval:.4f}, n={len(common)}")

    # ============================================================
    # Save results
    # ============================================================

    results_json = {
        'experiment_id': 'K762',
        'title': 'Action-First Meta-Model — Strategy Consensus Trading Policy',
        'proposer': 'Codex (7th suggestion)',
        'executor': 'Claude',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'paper_trading.json + yfinance (^VIX, SPY, GLD)',
        'period': f'{COMMON_START} to {datetime.now().strftime("%Y-%m-%d")}',
        'n_strategies_total': len(all_strats),
        'n_us_strategies_for_consensus': len(us_strats),
        'us_strategies': us_strats,
        'tx_cost_bps': TX_COST_BPS,
        'rebalancing': 'monthly',
        'backtest_results': all_results,
        'cross_oos_results': {k: v for k, v in oos_results.items()},
        'feature_importance': feat_imp,
        'consensus_distribution': {
            'mean_bullish_pct': round(bp.mean(), 4),
            'std_bullish_pct': round(bp.std(), 4),
            'pct_strong_bullish': round((bp > 0.7).mean(), 4),
            'pct_strong_bearish': round((bp < 0.3).mean(), 4),
            'pct_mixed': round(((bp >= 0.3) & (bp <= 0.7)).mean(), 4),
        },
        'daily_consensus_predictive_corr': round(corr, 4) if len(common) > 30 else None,
        'daily_consensus_predictive_pval': round(pval, 4) if len(common) > 30 else None,
        'references': [
            'López de Prado (2018) Advances in Financial Machine Learning',
            'Surowiecki (2004) The Wisdom of Crowds',
            'Timmermann (2006) Forecast Combinations, Handbook of Economic Forecasting',
            'K756: Meta-labeling null result (daily AUC 0.48-0.52)',
            'K475/K482: Equal-weight ensemble beats sophisticated weighting',
        ],
        'key_findings': [],  # Populated below
        'limitations': [
            'Only ~3 years of data (2023-2026) — short sample',
            '14 strategies are not fully independent (many share VIX as input)',
            'Consensus signal is slow-moving (strategies change gradually)',
            'Monthly rebalancing may miss regime changes',
            'No TX on individual underlying strategies (only on meta-portfolio)',
        ],
    }

    # Determine key findings
    findings = []

    # Compare best consensus to 50/50
    bh_sharpe = next(r['sharpe'] for r in all_results if r['name'] == 'BH_5050')
    vix_sharpe = next(r['sharpe'] for r in all_results if r['name'] == '12/VIX')
    best_consensus = next(r for r in all_results if r['name'].startswith('Consensus_')
                         and r['sharpe'] == best_consensus_sharpe)

    findings.append(f"Best consensus signal ({best_consensus['name']}): Sharpe={best_consensus['sharpe']:.4f} "
                    f"vs 50/50={bh_sharpe:.4f} vs 12/VIX={vix_sharpe:.4f}")

    if best_consensus['sharpe'] > bh_sharpe:
        findings.append(f"Consensus BEATS 50/50 by {best_consensus['sharpe'] - bh_sharpe:.4f} Sharpe points")
    else:
        findings.append(f"Consensus FAILS to beat 50/50 (delta={best_consensus['sharpe'] - bh_sharpe:.4f})")

    # Feature importance finding
    if feat_imp:
        best_feat = max(feat_imp.items(), key=lambda x: abs(x[1]['corr']))
        findings.append(f"Best monthly predictor: {best_feat[0]} (corr={best_feat[1]['corr']:.4f}, "
                        f"p={best_feat[1]['pval']:.4f})")

    # Consensus distribution finding
    findings.append(f"Strategies mostly agree: {bp.mean()*100:.1f}% bullish on average, "
                    f"strong consensus {(bp > 0.7).mean()*100:.1f}% + {(bp < 0.3).mean()*100:.1f}% "
                    f"= {((bp > 0.7) | (bp < 0.3)).mean()*100:.1f}% of days")

    results_json['key_findings'] = findings

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results_json, f, indent=2, default=str)

    print(f"\n  Results saved to {RESULTS_PATH}")

    # ============================================================
    # Summary
    # ============================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for finding in findings:
        print(f"  • {finding}")

    print("\n  Limitations:")
    for lim in results_json['limitations']:
        print(f"  - {lim}")

    return results_json


if __name__ == '__main__':
    results = main()
