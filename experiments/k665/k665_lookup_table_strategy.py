"""
K665: Can We Simplify 12/VIX to a Lookup Table?
[提出: Claude, 執行: Claude]

Background: 12/VIX is simple math but many retail investors still find
continuous formulas intimidating. Can we replace the continuous 12/VIX
with a simple 5-row lookup table that preserves >95% of the performance?

This builds on:
- K568: 12/VIX is the return-optimal linear function (427 configs tested)
- K569: Piecewise VT achieves highest Sharpe but lower CAGR
- K652/K659: VIX threshold analysis (optimal breakpoints)

Methodology:
1. 12/VIX continuous as reference (50/50 SPY/GLD base)
2. Four lookup tables (3, 5, 5-opt, 7 rows) mapping VIX → allocation
3. Metrics: Sharpe, CAGR, MDD, tracking error, weight changes/year
4. Key question: which table achieves >95% of continuous Sharpe?

Data source: yfinance (SPY, GLD, ^VIX), 2006-01-01 to 2026-03-27
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────
# 1. DATA COLLECTION
# ─────────────────────────────────────────────
print("=" * 70)
print("K665: Can We Simplify 12/VIX to a Lookup Table?")
print("[提出: Claude, 執行: Claude]")
print("=" * 70)

print("\n[1/6] Downloading data from yfinance...")
spy = yf.download("SPY", start="2006-01-01", end="2026-03-28", auto_adjust=True, progress=False)
gld = yf.download("GLD", start="2006-01-01", end="2026-03-28", auto_adjust=True, progress=False)
vix = yf.download("^VIX", start="2006-01-01", end="2026-03-28", auto_adjust=True, progress=False)

# Flatten MultiIndex if present
for df in [spy, gld, vix]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Align dates
common_dates = spy.index.intersection(gld.index).intersection(vix.index)
spy = spy.loc[common_dates]
gld = gld.loc[common_dates]
vix = vix.loc[common_dates]

spy_r = spy['Close'].pct_change().dropna()
gld_r = gld['Close'].pct_change().dropna()
vix_close = vix['Close']

# Align all series to common dates after pct_change
common = spy_r.index.intersection(gld_r.index).intersection(vix_close.index)
spy_r = spy_r.loc[common]
gld_r = gld_r.loc[common]
vix_close = vix_close.loc[common]

print(f"  Data range: {common[0].strftime('%Y-%m-%d')} to {common[-1].strftime('%Y-%m-%d')}")
print(f"  Trading days: {len(common)}")
print(f"  VIX range: {vix_close.min():.1f} - {vix_close.max():.1f}")
print(f"  VIX mean: {vix_close.mean():.1f}, median: {vix_close.median():.1f}")

# ─────────────────────────────────────────────
# 2. DESCRIPTIVE STATISTICS
# ─────────────────────────────────────────────
print("\n[2/6] Descriptive statistics...")

# VIX distribution by bucket (for understanding the data)
vix_buckets = pd.cut(vix_close, bins=[0, 12, 15, 18, 22, 25, 28, 30, 35, 100],
                     labels=['<12', '12-15', '15-18', '18-22', '22-25', '25-28', '28-30', '30-35', '>35'])
vix_dist = vix_buckets.value_counts(normalize=True).sort_index()
print("\n  VIX Distribution:")
for bucket, pct in vix_dist.items():
    print(f"    {bucket:>6s}: {pct*100:5.1f}%")

# SPY/GLD basic stats
print(f"\n  SPY: mean={spy_r.mean()*252*100:.1f}%/yr, vol={spy_r.std()*np.sqrt(252)*100:.1f}%/yr")
print(f"  GLD: mean={gld_r.mean()*252*100:.1f}%/yr, vol={gld_r.std()*np.sqrt(252)*100:.1f}%/yr")
corr_sg = spy_r.corr(gld_r)
print(f"  SPY-GLD correlation: {corr_sg:.3f}")


# ─────────────────────────────────────────────
# 3. DEFINE STRATEGIES
# ─────────────────────────────────────────────
print("\n[3/6] Defining strategies...")

# Risk-free rate proxy (SHY ≈ 2-3% average over period)
rf_annual = 0.02
rf_daily = rf_annual / 252


def continuous_12vix(vix_val):
    """12/VIX continuous, capped at 1.0"""
    return min(12.0 / vix_val, 1.0)


def lookup_table_A(vix_val):
    """Table A: 5 rows — simple intuitive"""
    if vix_val < 12:
        return 1.00
    elif vix_val < 16:
        return 0.80
    elif vix_val < 22:
        return 0.60
    elif vix_val < 30:
        return 0.40
    else:
        return 0.20


def lookup_table_B(vix_val):
    """Table B: 3 rows — simplest possible"""
    if vix_val < 15:
        return 1.00
    elif vix_val < 25:
        return 0.50
    else:
        return 0.20


def lookup_table_C(vix_val):
    """Table C: 7 rows — granular"""
    if vix_val < 12:
        return 1.00
    elif vix_val < 15:
        return 0.90
    elif vix_val < 18:
        return 0.70
    elif vix_val < 22:
        return 0.50
    elif vix_val < 28:
        return 0.35
    elif vix_val < 35:
        return 0.20
    else:
        return 0.10


def lookup_table_D(vix_val):
    """Table D: 5 rows — optimized thresholds from K652/K659"""
    if vix_val < 14:
        return 1.00
    elif vix_val < 18:
        return 0.75
    elif vix_val < 25:
        return 0.50
    elif vix_val < 32:
        return 0.25
    else:
        return 0.10


strategies = {
    'continuous_12vix': continuous_12vix,
    'table_A_5row': lookup_table_A,
    'table_B_3row': lookup_table_B,
    'table_C_7row': lookup_table_C,
    'table_D_5row_opt': lookup_table_D,
}

strategy_descriptions = {
    'continuous_12vix': '12/VIX Continuous (reference)',
    'table_A_5row': 'Table A: 5-row simple (<12/12-16/16-22/22-30/>30)',
    'table_B_3row': 'Table B: 3-row simplest (<15/15-25/>25)',
    'table_C_7row': 'Table C: 7-row granular',
    'table_D_5row_opt': 'Table D: 5-row optimized (K652/K659 thresholds)',
}

print("  Strategies defined:")
for name, desc in strategy_descriptions.items():
    print(f"    - {desc}")


# ─────────────────────────────────────────────
# 4. BACKTEST ALL STRATEGIES
# ─────────────────────────────────────────────
print("\n[4/6] Running backtests...")


def backtest_strategy(weight_func, spy_returns, gld_returns, vix_series, rf_daily_rate):
    """
    Backtest a 50/50 SPY/GLD strategy where weight_func(VIX) determines
    the allocation to the risky portfolio (50/50 SPY/GLD).
    Remainder goes to cash (earns rf).

    Uses PREVIOUS day's VIX to determine TODAY's weight (no look-ahead).
    """
    dates = spy_returns.index
    n = len(dates)

    # Previous day VIX for signal (lag by 1 day to avoid look-ahead)
    prev_vix = vix_series.shift(1)

    weights = np.zeros(n)
    port_returns = np.zeros(n)

    for i in range(n):
        v = prev_vix.iloc[i]
        if pd.isna(v) or v <= 0:
            weights[i] = 0.5  # Default if VIX unavailable
        else:
            weights[i] = weight_func(v)

        # 50/50 SPY/GLD risky portfolio
        risky_return = 0.5 * spy_returns.iloc[i] + 0.5 * gld_returns.iloc[i]

        # Portfolio = weight * risky + (1-weight) * rf
        port_returns[i] = weights[i] * risky_return + (1 - weights[i]) * rf_daily_rate

    # Build cumulative equity curve
    cum_returns = (1 + pd.Series(port_returns, index=dates)).cumprod()

    # Metrics
    total_days = n
    total_years = total_days / 252

    # CAGR
    final_val = cum_returns.iloc[-1]
    cagr = (final_val ** (1 / total_years)) - 1

    # Annualized volatility
    ann_vol = np.std(port_returns) * np.sqrt(252)

    # Sharpe ratio (excess over rf)
    excess_returns = port_returns - rf_daily_rate
    sharpe = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252) if np.std(excess_returns) > 0 else 0

    # Maximum drawdown
    running_max = cum_returns.cummax()
    drawdown = (cum_returns - running_max) / running_max
    mdd = drawdown.min()

    # Calmar ratio
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else np.inf

    # Sortino ratio
    downside = excess_returns[excess_returns < 0]
    downside_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else 1e-10
    sortino = np.mean(excess_returns) * 252 / downside_vol

    # Weight changes per year (days where weight changes)
    weight_series = pd.Series(weights, index=dates)
    weight_changes = (weight_series.diff().abs() > 1e-6).sum()
    weight_changes_per_year = weight_changes / total_years

    # Average weight
    avg_weight = np.mean(weights)

    return {
        'port_returns': pd.Series(port_returns, index=dates),
        'cum_returns': cum_returns,
        'weights': weight_series,
        'cagr': cagr,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'mdd': mdd,
        'calmar': calmar,
        'sortino': sortino,
        'weight_changes_per_year': weight_changes_per_year,
        'avg_weight': avg_weight,
        'total_years': total_years,
    }


# Run all strategies
results = {}
for name, func in strategies.items():
    res = backtest_strategy(func, spy_r, gld_r, vix_close, rf_daily)
    results[name] = res
    print(f"  {strategy_descriptions[name]}:")
    print(f"    Sharpe={res['sharpe']:.3f}, CAGR={res['cagr']*100:.2f}%, "
          f"MDD={res['mdd']*100:.2f}%, Vol={res['ann_vol']*100:.2f}%")
    print(f"    Calmar={res['calmar']:.2f}, Sortino={res['sortino']:.3f}, "
          f"Avg weight={res['avg_weight']*100:.1f}%")
    print(f"    Weight changes/year={res['weight_changes_per_year']:.1f}")

# ─────────────────────────────────────────────
# 5. COMPARISON ANALYSIS
# ─────────────────────────────────────────────
print("\n[5/6] Comparison analysis...")

ref = results['continuous_12vix']
ref_returns = ref['port_returns']
ref_sharpe = ref['sharpe']

print(f"\n  Reference (continuous 12/VIX): Sharpe={ref_sharpe:.3f}")
print()

comparison = {}
for name in strategies:
    res = results[name]

    # Tracking error vs continuous
    if name == 'continuous_12vix':
        tracking_error = 0.0
        correlation = 1.0
    else:
        diff_returns = res['port_returns'] - ref_returns
        tracking_error = np.std(diff_returns) * np.sqrt(252)
        correlation = np.corrcoef(res['port_returns'].values, ref_returns.values)[0, 1]

    # Retention ratio
    retention = res['sharpe'] / ref_sharpe if ref_sharpe > 0 else 0

    # Weight correlation with continuous
    weight_corr = np.corrcoef(res['weights'].values, ref['weights'].values)[0, 1]

    # Weight MAE (mean absolute error)
    weight_mae = np.mean(np.abs(res['weights'].values - ref['weights'].values))

    comp = {
        'description': strategy_descriptions[name],
        'sharpe': round(res['sharpe'], 4),
        'cagr_pct': round(res['cagr'] * 100, 2),
        'mdd_pct': round(res['mdd'] * 100, 2),
        'ann_vol_pct': round(res['ann_vol'] * 100, 2),
        'calmar': round(res['calmar'], 3),
        'sortino': round(res['sortino'], 3),
        'avg_weight_pct': round(res['avg_weight'] * 100, 1),
        'tracking_error_pct': round(tracking_error * 100, 3),
        'return_correlation': round(correlation, 5),
        'weight_correlation': round(weight_corr, 5),
        'weight_mae': round(weight_mae, 4),
        'weight_changes_per_year': round(res['weight_changes_per_year'], 1),
        'retention_ratio': round(retention, 4),
        'passes_95pct_threshold': retention >= 0.95,
    }
    comparison[name] = comp

    print(f"  {strategy_descriptions[name]}:")
    print(f"    Retention ratio: {retention*100:.1f}% {'✓ >95%' if retention >= 0.95 else '✗ <95%'}")
    print(f"    Tracking error: {tracking_error*100:.3f}%")
    print(f"    Return corr: {correlation:.4f}, Weight corr: {weight_corr:.4f}")
    print(f"    Weight MAE: {weight_mae:.4f}")
    print()


# ─────────────────────────────────────────────
# 5b. SUB-PERIOD ANALYSIS
# ─────────────────────────────────────────────
print("  Sub-period analysis (crisis periods)...")

periods = {
    'GFC (2008-2009)': ('2008-01-01', '2009-12-31'),
    'Post-GFC Bull (2010-2014)': ('2010-01-01', '2014-12-31'),
    'Low Vol (2017)': ('2017-01-01', '2017-12-31'),
    'COVID (2020)': ('2020-01-01', '2020-12-31'),
    'Rate Hikes (2022)': ('2022-01-01', '2022-12-31'),
    'Recent (2024-2026)': ('2024-01-01', '2026-03-27'),
}

sub_period_results = {}
for period_name, (start, end) in periods.items():
    period_data = {}
    for strat_name in strategies:
        pr = results[strat_name]['port_returns']
        mask = (pr.index >= start) & (pr.index <= end)
        period_returns = pr.loc[mask]

        if len(period_returns) < 20:
            continue

        cum = (1 + period_returns).cumprod()
        years = len(period_returns) / 252
        cagr = (cum.iloc[-1] ** (1 / years)) - 1
        vol = period_returns.std() * np.sqrt(252)
        sharpe = (period_returns.mean() - rf_daily) / period_returns.std() * np.sqrt(252) if period_returns.std() > 0 else 0
        dd = (cum / cum.cummax() - 1).min()

        period_data[strat_name] = {
            'sharpe': round(sharpe, 3),
            'cagr_pct': round(cagr * 100, 2),
            'mdd_pct': round(dd * 100, 2),
        }

    sub_period_results[period_name] = period_data

    # Print sub-period Sharpe comparison
    ref_sub_sharpe = period_data.get('continuous_12vix', {}).get('sharpe', 0)
    print(f"\n    {period_name} (ref Sharpe={ref_sub_sharpe:.3f}):")
    for sn in ['table_A_5row', 'table_B_3row', 'table_C_7row', 'table_D_5row_opt']:
        if sn in period_data:
            s = period_data[sn]['sharpe']
            ret_ratio = s / ref_sub_sharpe if ref_sub_sharpe != 0 else 0
            print(f"      {sn}: Sharpe={s:.3f} (retention={ret_ratio*100:.1f}%)")


# ─────────────────────────────────────────────
# 5c. SENSITIVITY: DIFFERENT BASE ALLOCATIONS
# ─────────────────────────────────────────────
print("\n\n  Sensitivity: SPY-only (no GLD) comparison...")


def backtest_spy_only(weight_func, spy_returns, vix_series, rf_daily_rate):
    """Same but 100% SPY risky portfolio instead of 50/50 SPY/GLD."""
    dates = spy_returns.index
    n = len(dates)
    prev_vix = vix_series.shift(1)
    weights = np.zeros(n)
    port_returns = np.zeros(n)

    for i in range(n):
        v = prev_vix.iloc[i]
        if pd.isna(v) or v <= 0:
            weights[i] = 0.5
        else:
            weights[i] = weight_func(v)
        port_returns[i] = weights[i] * spy_returns.iloc[i] + (1 - weights[i]) * rf_daily_rate

    cum = (1 + pd.Series(port_returns, index=dates)).cumprod()
    total_years = n / 252
    cagr = (cum.iloc[-1] ** (1 / total_years)) - 1
    excess = port_returns - rf_daily_rate
    sharpe = np.mean(excess) / np.std(excess) * np.sqrt(252) if np.std(excess) > 0 else 0
    mdd = ((cum / cum.cummax()) - 1).min()

    return {'sharpe': round(sharpe, 3), 'cagr_pct': round(cagr * 100, 2), 'mdd_pct': round(mdd * 100, 2)}


spy_only_results = {}
for name, func in strategies.items():
    res = backtest_spy_only(func, spy_r, vix_close, rf_daily)
    spy_only_results[name] = res
    retention = res['sharpe'] / spy_only_results.get('continuous_12vix', {}).get('sharpe', res['sharpe']) if 'continuous_12vix' in spy_only_results else 1.0
    print(f"    {name}: Sharpe={res['sharpe']:.3f}, CAGR={res['cagr_pct']:.2f}%, MDD={res['mdd_pct']:.2f}%")

# Recompute retention for SPY-only
ref_spy_sharpe = spy_only_results['continuous_12vix']['sharpe']
print(f"\n  SPY-only retention ratios (ref Sharpe={ref_spy_sharpe:.3f}):")
for name in ['table_A_5row', 'table_B_3row', 'table_C_7row', 'table_D_5row_opt']:
    s = spy_only_results[name]['sharpe']
    r = s / ref_spy_sharpe if ref_spy_sharpe != 0 else 0
    print(f"    {name}: {r*100:.1f}% {'✓' if r >= 0.95 else '✗'}")


# ─────────────────────────────────────────────
# 6. SAVE RESULTS
# ─────────────────────────────────────────────
print("\n[6/6] Saving results...")

# Determine winner
best_table = None
best_retention = 0
for name in ['table_A_5row', 'table_B_3row', 'table_C_7row', 'table_D_5row_opt']:
    ret = comparison[name]['retention_ratio']
    if ret >= 0.95 and ret > best_retention:
        best_retention = ret
        best_table = name

# If no table passes 95%, pick closest
if best_table is None:
    best_table = max(['table_A_5row', 'table_B_3row', 'table_C_7row', 'table_D_5row_opt'],
                     key=lambda x: comparison[x]['retention_ratio'])
    best_retention = comparison[best_table]['retention_ratio']

# Simplest table that passes 95% (fewest rows)
simplest_passing = None
row_counts = {'table_B_3row': 3, 'table_A_5row': 5, 'table_D_5row_opt': 5, 'table_C_7row': 7}
for name in ['table_B_3row', 'table_A_5row', 'table_D_5row_opt', 'table_C_7row']:
    if comparison[name]['retention_ratio'] >= 0.95:
        simplest_passing = name
        break

# Lookup table definitions for output
table_definitions = {
    'table_A_5row': {
        'rows': 5,
        'rules': [
            {'vix_range': '< 12', 'allocation': '100%'},
            {'vix_range': '12-16', 'allocation': '80%'},
            {'vix_range': '16-22', 'allocation': '60%'},
            {'vix_range': '22-30', 'allocation': '40%'},
            {'vix_range': '> 30', 'allocation': '20%'},
        ]
    },
    'table_B_3row': {
        'rows': 3,
        'rules': [
            {'vix_range': '< 15', 'allocation': '100%'},
            {'vix_range': '15-25', 'allocation': '50%'},
            {'vix_range': '> 25', 'allocation': '20%'},
        ]
    },
    'table_C_7row': {
        'rows': 7,
        'rules': [
            {'vix_range': '< 12', 'allocation': '100%'},
            {'vix_range': '12-15', 'allocation': '90%'},
            {'vix_range': '15-18', 'allocation': '70%'},
            {'vix_range': '18-22', 'allocation': '50%'},
            {'vix_range': '22-28', 'allocation': '35%'},
            {'vix_range': '28-35', 'allocation': '20%'},
            {'vix_range': '> 35', 'allocation': '10%'},
        ]
    },
    'table_D_5row_opt': {
        'rows': 5,
        'rules': [
            {'vix_range': '< 14', 'allocation': '100%'},
            {'vix_range': '14-18', 'allocation': '75%'},
            {'vix_range': '18-25', 'allocation': '50%'},
            {'vix_range': '25-32', 'allocation': '25%'},
            {'vix_range': '> 32', 'allocation': '10%'},
        ]
    },
}

output = {
    'experiment_id': 'K665',
    'title': 'Can We Simplify 12/VIX to a Lookup Table?',
    'proposer': 'Claude',
    'executor': 'Claude',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance',
    'data_period': f"{common[0].strftime('%Y-%m-%d')} to {common[-1].strftime('%Y-%m-%d')}",
    'trading_days': len(common),
    'total_years': round(len(common) / 252, 1),
    'rf_annual': rf_annual,
    'base_portfolio': '50/50 SPY/GLD',
    'vix_statistics': {
        'mean': round(float(vix_close.mean()), 2),
        'median': round(float(vix_close.median()), 2),
        'min': round(float(vix_close.min()), 2),
        'max': round(float(vix_close.max()), 2),
        'std': round(float(vix_close.std()), 2),
        'distribution': {str(k): round(float(v) * 100, 1) for k, v in vix_dist.items()},
    },
    'lookup_tables': table_definitions,
    'full_period_comparison': comparison,
    'sub_period_analysis': sub_period_results,
    'spy_only_comparison': spy_only_results,
    'spy_only_retention': {
        name: round(spy_only_results[name]['sharpe'] / ref_spy_sharpe, 4)
        for name in ['table_A_5row', 'table_B_3row', 'table_C_7row', 'table_D_5row_opt']
    },
    'key_findings': {
        'best_table': best_table,
        'best_retention_ratio': best_retention,
        'simplest_table_passing_95pct': simplest_passing,
        'any_table_passes_95pct': any(comparison[n]['retention_ratio'] >= 0.95
                                      for n in ['table_A_5row', 'table_B_3row', 'table_C_7row', 'table_D_5row_opt']),
        'recommended_action_card': table_definitions.get(best_table, table_definitions.get(simplest_passing, None)),
    },
    'conclusion': '',  # Filled below
    'limitations': [
        'Backtest uses previous-day VIX (1-day lag) — realistic for retail',
        'No transaction costs included (tables change less frequently, advantage for tables)',
        'Risk-free rate assumed constant 2%/yr over entire period',
        'GLD data starts mid-2004, full overlap from 2006',
        'VIX is closing level; intraday VIX may differ',
    ],
    'references': [
        'K568: 12/VIX mathematical optimality (427 function configs)',
        'K569: Piecewise VT (highest Sharpe, lower CAGR)',
        'K652/K659: VIX threshold optimization',
        'Moreira & Muir (2017): Volatility-Managed Portfolios, JoF',
    ],
}

# Generate conclusion
passes = [n for n in ['table_A_5row', 'table_B_3row', 'table_C_7row', 'table_D_5row_opt']
          if comparison[n]['retention_ratio'] >= 0.95]

if passes:
    simplest = min(passes, key=lambda x: row_counts[x])
    output['conclusion'] = (
        f"Yes, 12/VIX can be simplified to a lookup table. "
        f"{len(passes)} of 4 tables achieve >95% of continuous Sharpe. "
        f"The simplest passing table is {simplest} ({row_counts[simplest]} rows) "
        f"with retention ratio {comparison[simplest]['retention_ratio']*100:.1f}%. "
        f"Best overall: {best_table} (retention {best_retention*100:.1f}%). "
        f"Weight changes/yr drop from {comparison['continuous_12vix']['weight_changes_per_year']:.0f} "
        f"(continuous) to {comparison[simplest]['weight_changes_per_year']:.0f} "
        f"({simplest}), reducing trading friction significantly."
    )
else:
    closest = max(['table_A_5row', 'table_B_3row', 'table_C_7row', 'table_D_5row_opt'],
                  key=lambda x: comparison[x]['retention_ratio'])
    output['conclusion'] = (
        f"No lookup table achieves >95% of continuous 12/VIX Sharpe. "
        f"Closest: {closest} with retention ratio {comparison[closest]['retention_ratio']*100:.1f}%. "
        f"The continuous formula provides a meaningful edge that discrete tables cannot fully replicate. "
        f"However, {closest} may still be practical for investors who value simplicity "
        f"over the last few percent of risk-adjusted return."
    )

# Save
outpath = 'experiments/k665_results.json'
with open(outpath, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to {outpath}")

# ─────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

print(f"\n{'Strategy':<35} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'TE':>8} {'Retain':>8} {'Chg/yr':>8}")
print("-" * 85)
for name in ['continuous_12vix', 'table_A_5row', 'table_B_3row', 'table_C_7row', 'table_D_5row_opt']:
    c = comparison[name]
    label = strategy_descriptions[name][:34]
    te = f"{c['tracking_error_pct']:.3f}%" if c['tracking_error_pct'] > 0 else "---"
    retain = f"{c['retention_ratio']*100:.1f}%" if name != 'continuous_12vix' else 'REF'
    print(f"{label:<35} {c['sharpe']:>7.3f} {c['cagr_pct']:>7.2f}% {c['mdd_pct']:>7.2f}% {te:>8} {retain:>8} {c['weight_changes_per_year']:>7.1f}")

print(f"\n{'='*70}")
print(f"CONCLUSION: {output['conclusion']}")
print(f"{'='*70}")

if simplest_passing:
    print(f"\n🏆 VIX ACTION CARD (simplest table that passes 95%):")
    td = table_definitions[simplest_passing]
    print(f"   Table: {simplest_passing} ({td['rows']} rows)")
    print(f"   {'VIX Level':<12} {'Allocation':<12}")
    print(f"   {'-'*24}")
    for rule in td['rules']:
        print(f"   {rule['vix_range']:<12} {rule['allocation']:<12}")
    print(f"\n   Print it. Tape it to your monitor. That's all you need.")
elif best_table:
    print(f"\n📋 BEST TABLE (does not reach 95% but closest):")
    td = table_definitions[best_table]
    print(f"   Table: {best_table} ({td['rows']} rows)")
    print(f"   Retention: {best_retention*100:.1f}%")
    print(f"   {'VIX Level':<12} {'Allocation':<12}")
    print(f"   {'-'*24}")
    for rule in td['rules']:
        print(f"   {rule['vix_range']:<12} {rule['allocation']:<12}")

print(f"\nDone. K665 complete.")
