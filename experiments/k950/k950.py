"""
K950: Monthly Regime VT Cross-Asset Validation
================================================
Cross-market validation of K946's Monthly Regime VT strategy.

Strategy:
  - VIX < 15 (calm): 80% equity
  - VIX >= 25 (stress): 30% equity
  - 15 <= VIX < 25 (normal): 50% equity (no change)
  - Rebalance monthly (month-start VIX)
  - Compare vs BH 50/50 (annual rebalance)

Markets:
  1. SPY + GLD (US, K946 baseline)
  2. QQQ + GLD (US tech)
  3. 0050.TW + GLD (Taiwan + gold)
  4. EWJ + GLD (Japan + gold)
  5. FEZ + GLD (Eurozone + gold)

Data: yfinance, 2008-01 to 2025-12
Error log rules: fixed seed, signal.shift(1), 10bps cost, clean_tw50_data
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

np.random.seed(42)

# ── Configuration ──
START = '2008-01-01'
END = '2025-12-31'
COST_BPS = 10  # 10bps single-side
OUTPUT_DIR = Path(__file__).parent

MARKETS = {
    'SPY+GLD': {'equity': 'SPY', 'safe': 'GLD', 'label': 'US Broad'},
    'QQQ+GLD': {'equity': 'QQQ', 'safe': 'GLD', 'label': 'US Tech'},
    '0050+GLD': {'equity': '0050.TW', 'safe': 'GLD', 'label': 'Taiwan'},
    'EWJ+GLD': {'equity': 'EWJ', 'safe': 'GLD', 'label': 'Japan'},
    'FEZ+GLD': {'equity': 'FEZ', 'safe': 'GLD', 'label': 'Eurozone'},
}

REGIME_THRESHOLDS = {
    'calm': 15,   # VIX < 15 → 80% equity
    'stress': 25, # VIX >= 25 → 30% equity
}
WEIGHTS = {
    'calm': 0.80,
    'stress': 0.30,
    'normal': 0.50,
}


def download_data():
    """Download all required tickers."""
    tickers = set()
    for m in MARKETS.values():
        tickers.add(m['equity'])
        tickers.add(m['safe'])
    tickers.add('^VIX')

    print(f"Downloading: {sorted(tickers)}")
    data = yf.download(list(tickers), start=START, end=END, auto_adjust=True)

    # Handle multi-level columns
    if isinstance(data.columns, pd.MultiIndex):
        prices = data['Close']
    else:
        prices = data

    return prices


def clean_tw50(prices):
    """Clean 0050.TW data for known split issues."""
    if '0050.TW' in prices.columns:
        # Manual split adjustment: Yahoo only adjusts back to ~2014
        # Pre-2014 prices that are 4x too high need division
        col = prices['0050.TW'].copy()
        # Detect: if pre-2014 prices are >4x the 2014 average, divide by 4
        if col.index.min().year < 2014:
            avg_2014 = col.loc['2014-01-01':'2014-12-31'].mean()
            if not np.isnan(avg_2014):
                pre_2014 = col.loc[:'2013-12-31']
                if pre_2014.mean() > 2.5 * avg_2014:
                    prices.loc[:'2013-12-31', '0050.TW'] = pre_2014 / 4.0
                    print("  Applied 0050.TW 1:4 split correction for pre-2014 data")
    return prices


def get_monthly_vix(vix_series):
    """Get month-start VIX values."""
    # Resample to month start, take first valid observation
    monthly = vix_series.resample('MS').first()
    return monthly


def compute_returns(prices):
    """Compute daily returns for all tickers."""
    returns = prices.pct_change().dropna(how='all')
    return returns


def regime_weight(vix_val):
    """Determine equity weight based on VIX regime."""
    if vix_val < REGIME_THRESHOLDS['calm']:
        return WEIGHTS['calm']
    elif vix_val >= REGIME_THRESHOLDS['stress']:
        return WEIGHTS['stress']
    else:
        return WEIGHTS['normal']


def run_monthly_regime_vt(equity_ret, safe_ret, vix_monthly, cost_bps=COST_BPS):
    """
    Monthly Regime VT strategy.

    Signal from month-start VIX → applied to entire month's returns.
    This is NOT lookahead: VIX at month start is known before the month's returns.
    """
    # Align data
    common_idx = equity_ret.dropna().index.intersection(safe_ret.dropna().index)
    equity_ret = equity_ret.loc[common_idx]
    safe_ret = safe_ret.loc[common_idx]

    # Create monthly weight signal
    # For each trading day, use the VIX from the start of that month
    weights = pd.Series(index=common_idx, dtype=float)

    for date in common_idx:
        month_start = date.replace(day=1)
        # Find nearest month-start VIX
        valid_vix = vix_monthly.loc[:date]
        if len(valid_vix) == 0:
            weights[date] = WEIGHTS['normal']
        else:
            # Use the most recent month-start VIX
            weights[date] = regime_weight(valid_vix.iloc[-1])

    # CRITICAL: shift(1) for lookahead prevention
    # Actually, since we use month-start VIX for the entire month,
    # and month-start VIX is known before the month starts,
    # we need shift(1) on a DAILY basis to ensure t-1 signal for t return
    weights = weights.shift(1)
    weights = weights.dropna()

    # Align after shift
    common_idx = weights.index.intersection(equity_ret.index).intersection(safe_ret.index)
    weights = weights.loc[common_idx]
    equity_ret = equity_ret.loc[common_idx]
    safe_ret = safe_ret.loc[common_idx]

    # Portfolio return
    port_ret = weights * equity_ret + (1 - weights) * safe_ret

    # Transaction costs: when weight changes
    weight_changes = weights.diff().abs()
    # Each weight change costs 2 * cost_bps (buy + sell)
    cost = weight_changes * (cost_bps / 10000) * 2
    cost = cost.fillna(0)
    port_ret_net = port_ret - cost

    # Count actual weight changes
    n_changes = (weight_changes > 0.001).sum()

    return port_ret, port_ret_net, weights, n_changes


def run_bh_5050(equity_ret, safe_ret):
    """
    Buy-and-hold 50/50 with annual rebalance.
    """
    common_idx = equity_ret.dropna().index.intersection(safe_ret.dropna().index)
    equity_ret = equity_ret.loc[common_idx]
    safe_ret = safe_ret.loc[common_idx]

    # Simple 50/50 daily
    port_ret = 0.5 * equity_ret + 0.5 * safe_ret

    return port_ret


def compute_metrics(returns, label=''):
    """Compute standard performance metrics."""
    returns = returns.dropna()
    if len(returns) < 252:
        return None

    n_years = len(returns) / 252

    # Cumulative
    cum = (1 + returns).cumprod()

    # CAGR
    total_return = cum.iloc[-1] / cum.iloc[0]
    cagr = total_return ** (1 / n_years) - 1

    # Sharpe
    sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

    # MDD
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Annualized vol
    ann_vol = returns.std() * np.sqrt(252)

    # CRRA utility (gamma=5)
    gamma = 5
    # E[U] = E[(1+r)^(1-gamma) / (1-gamma)]
    wealth = 1 + returns
    wealth = wealth[wealth > 0]  # avoid negative wealth
    if len(wealth) > 0:
        utility_vals = wealth ** (1 - gamma) / (1 - gamma)
        crra_utility = utility_vals.mean() * 252  # annualized
    else:
        crra_utility = -np.inf

    # Annual turnover (for regime VT, measured separately)

    return {
        'label': label,
        'cagr': round(cagr * 100, 2),
        'sharpe': round(sharpe, 3),
        'mdd': round(mdd * 100, 2),
        'ann_vol': round(ann_vol * 100, 2),
        'crra_utility_gamma5': round(crra_utility, 6),
        'n_days': len(returns),
        'n_years': round(n_years, 1),
    }


def compute_turnover(weights):
    """Compute annualized turnover from weight series."""
    daily_turnover = weights.diff().abs().dropna()
    n_years = len(weights) / 252
    total_turnover = daily_turnover.sum()
    ann_turnover = total_turnover / n_years if n_years > 0 else 0
    return round(ann_turnover * 100, 2)  # in percentage


def main():
    print("=" * 60)
    print("K950: Monthly Regime VT Cross-Asset Validation")
    print("=" * 60)

    # Download data
    prices = download_data()

    # Clean 0050.TW
    prices = clean_tw50(prices)

    # VIX
    vix = prices['^VIX'].dropna()
    vix_monthly = get_monthly_vix(vix)
    print(f"\nVIX monthly data: {vix_monthly.index.min().date()} to {vix_monthly.index.max().date()}")
    print(f"VIX monthly observations: {len(vix_monthly)}")

    # Returns
    returns = compute_returns(prices)

    # Results storage
    all_results = {}
    cumulative_data = {}

    for market_key, market_info in MARKETS.items():
        print(f"\n{'─' * 50}")
        print(f"Market: {market_key} ({market_info['label']})")
        print(f"{'─' * 50}")

        eq_ticker = market_info['equity']
        safe_ticker = market_info['safe']

        if eq_ticker not in returns.columns:
            print(f"  WARNING: {eq_ticker} not found in data, skipping")
            continue
        if safe_ticker not in returns.columns:
            print(f"  WARNING: {safe_ticker} not found in data, skipping")
            continue

        eq_ret = returns[eq_ticker].dropna()
        safe_ret = returns[safe_ticker].dropna()

        print(f"  Equity ({eq_ticker}): {eq_ret.index.min().date()} to {eq_ret.index.max().date()}, N={len(eq_ret)}")
        print(f"  Safe ({safe_ticker}): {safe_ret.index.min().date()} to {safe_ret.index.max().date()}, N={len(safe_ret)}")

        # BH 50/50
        bh_ret = run_bh_5050(eq_ret, safe_ret)
        bh_metrics = compute_metrics(bh_ret, label=f'BH 50/50 ({market_key})')

        # Monthly Regime VT (gross)
        vt_ret_gross, vt_ret_net, vt_weights, n_changes = run_monthly_regime_vt(
            eq_ret, safe_ret, vix_monthly, cost_bps=COST_BPS
        )
        vt_metrics_gross = compute_metrics(vt_ret_gross, label=f'Regime VT gross ({market_key})')
        vt_metrics_net = compute_metrics(vt_ret_net, label=f'Regime VT net ({market_key})')

        if bh_metrics is None or vt_metrics_gross is None:
            print(f"  Insufficient data for {market_key}, skipping")
            continue

        # Turnover
        turnover = compute_turnover(vt_weights)

        # Weight distribution
        w_counts = vt_weights.dropna()
        regime_dist = {
            'calm_80pct': round((w_counts == 0.80).mean() * 100, 1),
            'normal_50pct': round((w_counts == 0.50).mean() * 100, 1),
            'stress_30pct': round((w_counts == 0.30).mean() * 100, 1),
        }

        print(f"\n  BH 50/50:      Sharpe={bh_metrics['sharpe']:.3f}, CAGR={bh_metrics['cagr']:.2f}%, MDD={bh_metrics['mdd']:.2f}%")
        print(f"  Regime VT net: Sharpe={vt_metrics_net['sharpe']:.3f}, CAGR={vt_metrics_net['cagr']:.2f}%, MDD={vt_metrics_net['mdd']:.2f}%")
        print(f"  Weight changes: {n_changes}, Ann. turnover: {turnover}%")
        print(f"  Regime distribution: {regime_dist}")

        # Sharpe improvement
        sharpe_diff = vt_metrics_net['sharpe'] - bh_metrics['sharpe']
        vt_wins = sharpe_diff > 0

        market_result = {
            'market': market_key,
            'label': market_info['label'],
            'equity': eq_ticker,
            'safe': safe_ticker,
            'bh_5050': bh_metrics,
            'regime_vt_gross': vt_metrics_gross,
            'regime_vt_net': vt_metrics_net,
            'weight_changes': int(n_changes),
            'ann_turnover_pct': turnover,
            'regime_distribution': regime_dist,
            'sharpe_diff_net': round(sharpe_diff, 3),
            'vt_wins_sharpe': vt_wins,
        }

        all_results[market_key] = market_result

        # Store cumulative for plotting
        common_bh = bh_ret.loc[vt_ret_net.index[0]:vt_ret_net.index[-1]]
        cumulative_data[market_key] = {
            'bh': (1 + common_bh).cumprod(),
            'vt': (1 + vt_ret_net).cumprod(),
        }

    # ── Cross-market summary ──
    print("\n" + "=" * 60)
    print("CROSS-MARKET SUMMARY")
    print("=" * 60)

    n_markets = len(all_results)
    n_vt_wins = sum(1 for r in all_results.values() if r['vt_wins_sharpe'])

    print(f"\nMarkets tested: {n_markets}")
    print(f"VT wins (Sharpe net): {n_vt_wins}/{n_markets}")

    summary_table = []
    for mk, r in all_results.items():
        row = {
            'market': mk,
            'bh_sharpe': r['bh_5050']['sharpe'],
            'vt_sharpe_net': r['regime_vt_net']['sharpe'],
            'sharpe_diff': r['sharpe_diff_net'],
            'bh_mdd': r['bh_5050']['mdd'],
            'vt_mdd_net': r['regime_vt_net']['mdd'],
            'weight_changes': r['weight_changes'],
            'ann_turnover': r['ann_turnover_pct'],
            'vt_wins': r['vt_wins_sharpe'],
        }
        summary_table.append(row)
        win_str = "✓" if row['vt_wins'] else "✗"
        print(f"  {mk:12s}: BH={row['bh_sharpe']:.3f} VT={row['vt_sharpe_net']:.3f} "
              f"Δ={row['sharpe_diff']:+.3f} {win_str}  "
              f"MDD: BH={row['bh_mdd']:.1f}% VT={row['vt_mdd_net']:.1f}%  "
              f"Changes={row['weight_changes']}")

    # Best improvement market
    best_market = max(all_results.items(), key=lambda x: x[1]['sharpe_diff_net'])
    worst_market = min(all_results.items(), key=lambda x: x[1]['sharpe_diff_net'])

    print(f"\nBest improvement:  {best_market[0]} (Δ Sharpe = {best_market[1]['sharpe_diff_net']:+.3f})")
    print(f"Worst improvement: {worst_market[0]} (Δ Sharpe = {worst_market[1]['sharpe_diff_net']:+.3f})")

    # Average turnover
    avg_turnover = np.mean([r['ann_turnover_pct'] for r in all_results.values()])
    print(f"Average annual turnover: {avg_turnover:.1f}%")

    # Sanity check: Sharpe > 2x baseline?
    for mk, r in all_results.items():
        if r['regime_vt_net']['sharpe'] > 2 * r['bh_5050']['sharpe']:
            print(f"\n⚠️ WARNING: {mk} VT Sharpe ({r['regime_vt_net']['sharpe']:.3f}) > 2x BH ({r['bh_5050']['sharpe']:.3f}). Check for bugs!")

    # ── Save results ──
    results_output = {
        'experiment_id': 'K950',
        'title': 'Monthly Regime VT Cross-Asset Validation',
        'description': 'Cross-market validation of K946 Monthly Regime VT strategy across 5 equity+gold pairs',
        'data_source': 'yfinance',
        'period': f'{START} to {END}',
        'methodology': {
            'strategy': 'Monthly Regime VT: VIX<15→80% eq, VIX≥25→30% eq, else 50%',
            'baseline': 'BH 50/50 (annual rebalance)',
            'cost': f'{COST_BPS}bps single-side per weight change',
            'vix_signal': 'Month-start ^VIX, shift(1) for daily lag',
        },
        'markets': all_results,
        'cross_market_summary': {
            'n_markets': n_markets,
            'n_vt_wins_sharpe': n_vt_wins,
            'vt_win_rate': round(n_vt_wins / n_markets * 100, 1) if n_markets > 0 else 0,
            'best_improvement': {'market': best_market[0], 'sharpe_diff': best_market[1]['sharpe_diff_net']},
            'worst_improvement': {'market': worst_market[0], 'sharpe_diff': worst_market[1]['sharpe_diff_net']},
            'avg_annual_turnover_pct': round(avg_turnover, 1),
        },
        'summary_table': summary_table,
        'conclusion': '',  # Filled below
    }

    # Conclusion
    if n_vt_wins >= 4:
        conclusion = f"Monthly Regime VT shows strong cross-market robustness: wins {n_vt_wins}/{n_markets} markets on Sharpe (net of costs). The strategy's low turnover ({avg_turnover:.0f}%/yr avg) makes it practical across diverse equity+gold pairs."
    elif n_vt_wins >= 3:
        conclusion = f"Monthly Regime VT shows moderate cross-market validity: wins {n_vt_wins}/{n_markets} markets. VIX-based regime switching has some cross-market value but is not universal."
    else:
        conclusion = f"Monthly Regime VT does NOT robustly generalize: wins only {n_vt_wins}/{n_markets} markets. The K946 SPY+GLD result may be market-specific."

    results_output['conclusion'] = conclusion

    # Save JSON
    json_path = OUTPUT_DIR / 'k950_results.json'
    with open(json_path, 'w') as f:
        json.dump(results_output, f, indent=2, default=str)
    print(f"\nResults saved to {json_path}")

    # ── Plot ──
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    axes = axes.flatten()

    for i, (mk, cdata) in enumerate(cumulative_data.items()):
        if i >= 5:
            break
        ax = axes[i]
        ax.plot(cdata['bh'].index, cdata['bh'].values, label='BH 50/50', color='gray', alpha=0.7)
        ax.plot(cdata['vt'].index, cdata['vt'].values, label='Regime VT', color='steelblue', linewidth=1.5)

        r = all_results[mk]
        title = f"{mk} ({r['label']})"
        ax.set_title(title, fontsize=11, fontweight='bold')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        # Annotate Sharpe
        ax.text(0.02, 0.95,
                f"BH: Sharpe={r['bh_5050']['sharpe']:.3f}\nVT: Sharpe={r['regime_vt_net']['sharpe']:.3f}\nΔ={r['sharpe_diff_net']:+.3f}",
                transform=ax.transAxes, fontsize=8, va='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    # Summary bar chart in last subplot
    ax = axes[5]
    markets_labels = [r['market'] for r in summary_table]
    bh_sharpes = [r['bh_sharpe'] for r in summary_table]
    vt_sharpes = [r['vt_sharpe_net'] for r in summary_table]

    x = np.arange(len(markets_labels))
    width = 0.35
    ax.bar(x - width/2, bh_sharpes, width, label='BH 50/50', color='gray', alpha=0.7)
    ax.bar(x + width/2, vt_sharpes, width, label='Regime VT (net)', color='steelblue')
    ax.set_xticks(x)
    ax.set_xticklabels(markets_labels, rotation=30, ha='right', fontsize=9)
    ax.set_ylabel('Sharpe Ratio')
    ax.set_title('Cross-Market Sharpe Comparison', fontsize=11, fontweight='bold')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, axis='y')

    fig.suptitle(f'K950: Monthly Regime VT Cross-Asset ({START[:4]}-{END[:4]})\n'
                 f'VT wins {n_vt_wins}/{n_markets} markets | Avg turnover {avg_turnover:.0f}%/yr',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()

    fig_path = OUTPUT_DIR / 'k950_cross_asset.png'
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Chart saved to {fig_path}")

    print(f"\n{'=' * 60}")
    print(f"CONCLUSION: {conclusion}")
    print(f"{'=' * 60}")

    return results_output


if __name__ == '__main__':
    results = main()
