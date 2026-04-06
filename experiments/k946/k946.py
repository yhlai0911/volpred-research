"""
K946: VIX Regime-Conditional Rebalancing
=========================================
Hypothesis: A strategy that only adjusts allocation when VIX enters extreme
regimes (calm <15 or stress >=25), holding 50/50 otherwise, can reduce turnover
while maintaining or improving risk-adjusted returns.

Data: SPY, GLD, ^VIX from yfinance (2006-2026)
Lag: VIX_{t-1} determines weight at t (shift(1))
Seed: np.random.seed(42) for any random operations
"""

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
import os
from datetime import datetime

np.random.seed(42)

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. Data Download
# ============================================================
print("Downloading data...")
spy = yf.download("SPY", start="2005-12-01", end="2026-04-06", auto_adjust=True)
gld = yf.download("GLD", start="2005-12-01", end="2026-04-06", auto_adjust=True)
vix = yf.download("^VIX", start="2005-12-01", end="2026-04-06", auto_adjust=True)

# Handle MultiIndex columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
    gld.columns = gld.columns.get_level_values(0)
    vix.columns = vix.columns.get_level_values(0)

# Daily returns
spy_ret = spy['Close'].pct_change()
gld_ret = gld['Close'].pct_change()
vix_close = vix['Close']

# Align all series
df = pd.DataFrame({
    'spy_ret': spy_ret,
    'gld_ret': gld_ret,
    'vix': vix_close
}).dropna()

# Filter to 2006-01-01 onwards (need some history for VIX)
df = df.loc['2006-01-01':]
print(f"Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, N={len(df)}")

# ============================================================
# 2. Strategy Definitions
# ============================================================

# Lagged VIX (t-1) -- THIS IS THE LAG
vix_lag = df['vix'].shift(1)  # CRITICAL: shift(1) for lookahead prevention

def calc_portfolio_return(w_spy, spy_ret, gld_ret, cost_bps=10):
    """Calculate portfolio return with transaction costs."""
    w_gld = 1.0 - w_spy
    gross_ret = w_spy * spy_ret + w_gld * gld_ret

    # Transaction cost: 10bps single-side per weight change
    w_change = w_spy.diff().abs()
    cost = w_change * (cost_bps / 10000.0)  # single-side cost on SPY weight change
    # GLD weight change is same magnitude
    cost = cost + (1.0 - w_spy).diff().abs() * (cost_bps / 10000.0)
    cost = cost.fillna(0)

    net_ret = gross_ret - cost
    return gross_ret, net_ret, w_change.fillna(0)

# Strategy 1: Buy-and-Hold 50/50 with annual rebalance
w_bh = pd.Series(0.5, index=df.index)
# Annual rebalance: only change weights on first trading day of each year
# (In practice, drift is small for 50/50, so turnover is minimal)

# Strategy 2: 12/VIX (daily)
w_12vix = (12.0 / vix_lag).clip(0, 1)

# Strategy 3: Regime-Only VT
def regime_only_vt(vix_lag):
    """Only act in extreme regimes, hold 50/50 in normal."""
    w = pd.Series(np.nan, index=vix_lag.index)
    w[vix_lag < 15] = 0.80  # calm: overweight stocks
    w[vix_lag >= 25] = 0.30  # stress: underweight stocks
    w[(vix_lag >= 15) & (vix_lag < 25)] = 0.50  # normal: hold 50/50
    return w

w_regime = regime_only_vt(vix_lag)

# Strategy 4: Smooth Regime VT (4 bins)
def smooth_regime_vt(vix_lag):
    """4-bin regime with wider hold zone."""
    w = pd.Series(np.nan, index=vix_lag.index)
    w[vix_lag < 12] = 0.80    # very calm
    w[(vix_lag >= 12) & (vix_lag < 20)] = 0.50  # normal-low: hold
    w[(vix_lag >= 20) & (vix_lag < 30)] = 0.50  # normal-high: hold
    w[vix_lag >= 30] = 0.20    # severe stress
    return w

w_smooth = smooth_regime_vt(vix_lag)

# Strategy 5: Monthly Regime (only check VIX on first day of month)
def monthly_regime_vt(vix_lag, df_index):
    """Same as regime-only but only check at month start."""
    w = pd.Series(np.nan, index=df_index)

    # Get month-start dates
    month_starts = df_index.to_series().groupby(df_index.to_period('M')).first()

    current_w = 0.5  # start at 50/50
    for date in df_index:
        if date in month_starts.values:
            v = vix_lag.loc[date]
            if pd.notna(v):
                if v < 15:
                    current_w = 0.80
                elif v >= 25:
                    current_w = 0.30
                else:
                    current_w = 0.50
        w.loc[date] = current_w
    return w

w_monthly = monthly_regime_vt(vix_lag, df.index)

# ============================================================
# 3. Calculate Returns for All Strategies
# ============================================================
strategies = {
    'BH 50/50': w_bh,
    '12/VIX (Daily)': w_12vix,
    'Regime-Only VT': w_regime,
    'Smooth Regime VT': w_smooth,
    'Monthly Regime VT': w_monthly,
}

results = {}
for name, w in strategies.items():
    w = w.dropna()
    common_idx = w.index.intersection(df.index)
    w_aligned = w.loc[common_idx]
    spy_r = df.loc[common_idx, 'spy_ret']
    gld_r = df.loc[common_idx, 'gld_ret']

    gross, net, w_chg = calc_portfolio_return(w_aligned, spy_r, gld_r)

    # Drop first row (NaN from shift)
    gross = gross.dropna()
    net = net.dropna()

    # Equity curves
    eq_gross = (1 + gross).cumprod()
    eq_net = (1 + net).cumprod()

    # Metrics
    ann_ret_gross = (eq_gross.iloc[-1] ** (252 / len(gross))) - 1
    ann_ret_net = (eq_net.iloc[-1] ** (252 / len(net))) - 1
    ann_vol = gross.std() * np.sqrt(252)
    sharpe_gross = ann_ret_gross / ann_vol if ann_vol > 0 else 0
    sharpe_net = ann_ret_net / ann_vol if ann_vol > 0 else 0

    # MDD
    roll_max = eq_gross.cummax()
    dd = (eq_gross - roll_max) / roll_max
    mdd = dd.min()

    # Calmar
    calmar = ann_ret_gross / abs(mdd) if mdd != 0 else 0

    # CRRA Utility
    def crra_utility(returns, gamma):
        if gamma == 1:
            return np.mean(np.log(1 + returns))
        else:
            return np.mean(((1 + returns) ** (1 - gamma) - 1) / (1 - gamma))

    crra_3 = crra_utility(gross, 3) * 252  # annualized
    crra_5 = crra_utility(gross, 5) * 252
    crra_7 = crra_utility(gross, 7) * 252

    # Turnover (annualized)
    daily_turnover = w_chg.loc[common_idx].dropna()
    ann_turnover = daily_turnover.mean() * 252

    # Count regime changes (days where weight actually changes)
    weight_changes = (w_aligned.diff().abs() > 0.001).sum()

    results[name] = {
        'ann_ret_gross': round(float(ann_ret_gross), 4),
        'ann_ret_net': round(float(ann_ret_net), 4),
        'ann_vol': round(float(ann_vol), 4),
        'sharpe_gross': round(float(sharpe_gross), 4),
        'sharpe_net': round(float(sharpe_net), 4),
        'mdd': round(float(mdd), 4),
        'calmar': round(float(calmar), 4),
        'crra_3': round(float(crra_3), 6),
        'crra_5': round(float(crra_5), 6),
        'crra_7': round(float(crra_7), 6),
        'ann_turnover': round(float(ann_turnover), 4),
        'weight_changes': int(weight_changes),
        'n_obs': len(gross),
        'equity_gross': eq_gross,
        'equity_net': eq_net,
        'weights': w_aligned,
        'returns_gross': gross,
    }

# ============================================================
# 4. Sub-period Analysis
# ============================================================
sub_periods = {
    'GFC Recovery (2008-2012)': ('2008-01-01', '2012-12-31'),
    'Bull Market (2013-2019)': ('2013-01-01', '2019-12-31'),
    'COVID+ Era (2020-2025)': ('2020-01-01', '2025-12-31'),
}

sub_results = {}
for period_name, (start, end) in sub_periods.items():
    sub_results[period_name] = {}
    for name, w in strategies.items():
        w = w.dropna()
        mask = (df.index >= start) & (df.index <= end)
        sub_idx = df.index[mask]
        common_idx = w.index.intersection(sub_idx)
        if len(common_idx) < 100:
            continue

        w_aligned = w.loc[common_idx]
        spy_r = df.loc[common_idx, 'spy_ret']
        gld_r = df.loc[common_idx, 'gld_ret']

        gross, net, w_chg = calc_portfolio_return(w_aligned, spy_r, gld_r)
        gross = gross.dropna()

        eq = (1 + gross).cumprod()
        ann_ret = (eq.iloc[-1] ** (252 / len(gross))) - 1
        ann_vol = gross.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

        roll_max = eq.cummax()
        dd = (eq - roll_max) / roll_max
        mdd = dd.min()

        sub_results[period_name][name] = {
            'sharpe': round(float(sharpe), 4),
            'ann_ret': round(float(ann_ret), 4),
            'mdd': round(float(mdd), 4),
        }

# ============================================================
# 5. Regime Statistics
# ============================================================
regime_labels = pd.Series('Normal', index=df.index)
regime_labels[vix_lag < 15] = 'Calm'
regime_labels[vix_lag >= 25] = 'Stress'

regime_stats = {}
for regime in ['Calm', 'Normal', 'Stress']:
    mask = regime_labels == regime
    n = mask.sum()
    pct = n / len(df) * 100
    avg_spy = df.loc[mask, 'spy_ret'].mean() * 252
    avg_gld = df.loc[mask, 'gld_ret'].mean() * 252
    vol_spy = df.loc[mask, 'spy_ret'].std() * np.sqrt(252)
    regime_stats[regime] = {
        'n_days': int(n),
        'pct': round(float(pct), 1),
        'ann_spy_ret': round(float(avg_spy), 4),
        'ann_gld_ret': round(float(avg_gld), 4),
        'ann_spy_vol': round(float(vol_spy), 4),
    }

# ============================================================
# 6. Plots
# ============================================================

# Plot 1: Equity Curves
fig, axes = plt.subplots(2, 1, figsize=(14, 10))

colors = {
    'BH 50/50': '#333333',
    '12/VIX (Daily)': '#2196F3',
    'Regime-Only VT': '#E91E63',
    'Smooth Regime VT': '#FF9800',
    'Monthly Regime VT': '#4CAF50',
}

for name in strategies:
    eq = results[name]['equity_gross']
    axes[0].plot(eq.index, eq.values, label=name, color=colors[name],
                 linewidth=2 if name in ['BH 50/50', 'Regime-Only VT'] else 1.2)

axes[0].set_title('K946: Equity Curves (Gross)', fontsize=14, fontweight='bold')
axes[0].set_ylabel('Cumulative Return')
axes[0].legend(loc='upper left', fontsize=9)
axes[0].grid(True, alpha=0.3)
axes[0].set_yscale('log')

# Plot weights over time for regime strategy
w_regime_plot = results['Regime-Only VT']['weights']
axes[1].fill_between(w_regime_plot.index, w_regime_plot.values, 0.5,
                      where=w_regime_plot > 0.5, alpha=0.3, color='green', label='Overweight SPY')
axes[1].fill_between(w_regime_plot.index, w_regime_plot.values, 0.5,
                      where=w_regime_plot < 0.5, alpha=0.3, color='red', label='Underweight SPY')
axes[1].plot(w_regime_plot.index, w_regime_plot.values, color='black', linewidth=0.5)
axes[1].axhline(0.5, color='gray', linestyle='--', linewidth=0.8)
axes[1].set_title('Regime-Only VT: SPY Weight Over Time', fontsize=14, fontweight='bold')
axes[1].set_ylabel('SPY Weight')
axes[1].set_ylim(0, 1)
axes[1].legend(loc='upper right', fontsize=9)
axes[1].grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k946_equity_curves.png'), dpi=150, bbox_inches='tight')
plt.close()

# Plot 2: Regime Analysis
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# 2a: VIX distribution with regime boundaries
ax = axes[0, 0]
vix_vals = df['vix'].dropna()
ax.hist(vix_vals, bins=80, color='steelblue', alpha=0.7, edgecolor='white')
ax.axvline(15, color='green', linestyle='--', linewidth=2, label='Calm boundary (15)')
ax.axvline(25, color='red', linestyle='--', linewidth=2, label='Stress boundary (25)')
ax.set_title('VIX Distribution & Regime Boundaries', fontsize=12, fontweight='bold')
ax.set_xlabel('VIX')
ax.set_ylabel('Frequency')
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)

# 2b: Regime proportion pie
ax = axes[0, 1]
sizes = [regime_stats[r]['pct'] for r in ['Calm', 'Normal', 'Stress']]
labels_pie = [f"Calm (<15)\n{regime_stats['Calm']['pct']:.1f}%\n{regime_stats['Calm']['n_days']}d",
              f"Normal (15-25)\n{regime_stats['Normal']['pct']:.1f}%\n{regime_stats['Normal']['n_days']}d",
              f"Stress (>=25)\n{regime_stats['Stress']['pct']:.1f}%\n{regime_stats['Stress']['n_days']}d"]
colors_pie = ['#4CAF50', '#FFC107', '#F44336']
ax.pie(sizes, labels=labels_pie, colors=colors_pie, autopct='', startangle=90,
       textprops={'fontsize': 9})
ax.set_title('Time in Each Regime', fontsize=12, fontweight='bold')

# 2c: Sharpe comparison bar chart
ax = axes[1, 0]
names = list(strategies.keys())
sharpes_gross = [results[n]['sharpe_gross'] for n in names]
sharpes_net = [results[n]['sharpe_net'] for n in names]
x = np.arange(len(names))
width = 0.35
bars1 = ax.bar(x - width/2, sharpes_gross, width, label='Gross', color='steelblue', alpha=0.8)
bars2 = ax.bar(x + width/2, sharpes_net, width, label='Net of Costs', color='coral', alpha=0.8)
ax.set_title('Sharpe Ratio Comparison', fontsize=12, fontweight='bold')
ax.set_ylabel('Sharpe Ratio')
ax.set_xticks(x)
ax.set_xticklabels([n.replace(' ', '\n') for n in names], fontsize=8)
ax.legend()
ax.grid(True, alpha=0.3, axis='y')
for bar in bars1:
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
            f'{bar.get_height():.3f}', ha='center', va='bottom', fontsize=7)

# 2d: Turnover comparison
ax = axes[1, 1]
turnovers = [results[n]['ann_turnover'] for n in names]
weight_changes = [results[n]['weight_changes'] for n in names]
bars = ax.bar(x, turnovers, color=[colors[n] for n in names], alpha=0.8)
ax.set_title('Annualized Turnover', fontsize=12, fontweight='bold')
ax.set_ylabel('Turnover')
ax.set_xticks(x)
ax.set_xticklabels([n.replace(' ', '\n') for n in names], fontsize=8)
ax.grid(True, alpha=0.3, axis='y')
for i, bar in enumerate(bars):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
            f'{turnovers[i]:.3f}\n({weight_changes[i]} chg)',
            ha='center', va='bottom', fontsize=7)

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k946_regime_analysis.png'), dpi=150, bbox_inches='tight')
plt.close()

# ============================================================
# 7. Print Summary Table
# ============================================================
print("\n" + "="*100)
print("K946: VIX Regime-Conditional Rebalancing — Full Period Results")
print("="*100)
print(f"{'Strategy':<22} {'Sharpe(G)':>10} {'Sharpe(N)':>10} {'CAGR(G)':>10} {'Vol':>8} {'MDD':>8} {'Calmar':>8} {'Turnover':>10} {'Changes':>8}")
print("-"*100)
for name in strategies:
    r = results[name]
    print(f"{name:<22} {r['sharpe_gross']:>10.4f} {r['sharpe_net']:>10.4f} {r['ann_ret_gross']:>9.2%} {r['ann_vol']:>7.2%} {r['mdd']:>7.2%} {r['calmar']:>8.4f} {r['ann_turnover']:>10.4f} {r['weight_changes']:>8d}")

print(f"\n{'Strategy':<22} {'CRRA(3)':>12} {'CRRA(5)':>12} {'CRRA(7)':>12}")
print("-"*62)
for name in strategies:
    r = results[name]
    print(f"{name:<22} {r['crra_3']:>12.6f} {r['crra_5']:>12.6f} {r['crra_7']:>12.6f}")

print("\n\nRegime Statistics:")
print("-"*70)
for regime, stats in regime_stats.items():
    print(f"  {regime}: {stats['n_days']} days ({stats['pct']:.1f}%), SPY ann ret={stats['ann_spy_ret']:.2%}, SPY vol={stats['ann_spy_vol']:.2%}, GLD ann ret={stats['ann_gld_ret']:.2%}")

print("\n\nSub-Period Sharpe Ratios:")
print("-"*90)
for period_name, subs in sub_results.items():
    print(f"\n  {period_name}:")
    for name, s in subs.items():
        print(f"    {name:<22} Sharpe={s['sharpe']:.4f}  CAGR={s['ann_ret']:.2%}  MDD={s['mdd']:.2%}")

# ============================================================
# 8. Save Results JSON
# ============================================================
output = {
    'experiment_id': 'K946',
    'title': 'VIX Regime-Conditional Rebalancing',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY, GLD, ^VIX)',
    'period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_obs': len(df),
    'lag': 'VIX_{t-1} via shift(1)',
    'transaction_cost': '10bps single-side per weight change',
    'strategies': {},
    'regime_stats': regime_stats,
    'sub_period_sharpes': {},
    'conclusion': '',
}

for name in strategies:
    r = results[name]
    output['strategies'][name] = {
        'ann_ret_gross': r['ann_ret_gross'],
        'ann_ret_net': r['ann_ret_net'],
        'ann_vol': r['ann_vol'],
        'sharpe_gross': r['sharpe_gross'],
        'sharpe_net': r['sharpe_net'],
        'mdd': r['mdd'],
        'calmar': r['calmar'],
        'crra_3': r['crra_3'],
        'crra_5': r['crra_5'],
        'crra_7': r['crra_7'],
        'ann_turnover': r['ann_turnover'],
        'weight_changes': r['weight_changes'],
    }

for period_name, subs in sub_results.items():
    output['sub_period_sharpes'][period_name] = subs

# Determine conclusion
bh_sharpe = results['BH 50/50']['sharpe_net']
regime_sharpe = results['Regime-Only VT']['sharpe_net']
regime_turnover = results['Regime-Only VT']['ann_turnover']
bh_turnover = results['BH 50/50']['ann_turnover']
regime_mdd = results['Regime-Only VT']['mdd']
bh_mdd = results['BH 50/50']['mdd']

# Check CRRA
crra_wins = {}
for gamma_label in ['crra_3', 'crra_5', 'crra_7']:
    best_name = max(strategies.keys(), key=lambda n: results[n][gamma_label])
    crra_wins[gamma_label] = best_name

conclusion_parts = []
conclusion_parts.append(f"BH 50/50 Sharpe(net)={bh_sharpe:.4f} vs Regime-Only VT={regime_sharpe:.4f}")
if regime_sharpe > bh_sharpe:
    conclusion_parts.append("Regime-Only VT beats BH 50/50 on Sharpe (net of costs)")
else:
    conclusion_parts.append("BH 50/50 still wins on Sharpe (net of costs)")

conclusion_parts.append(f"Turnover: BH={bh_turnover:.4f} vs Regime-Only={regime_turnover:.4f}")
conclusion_parts.append(f"MDD: BH={bh_mdd:.2%} vs Regime-Only={regime_mdd:.2%}")
conclusion_parts.append(f"CRRA winners: gamma=3→{crra_wins['crra_3']}, gamma=5→{crra_wins['crra_5']}, gamma=7→{crra_wins['crra_7']}")

output['conclusion'] = '; '.join(conclusion_parts)

with open(os.path.join(OUT_DIR, 'k946_results.json'), 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\n\nConclusion: {output['conclusion']}")
print(f"\nResults saved to {OUT_DIR}/k946_results.json")
print(f"Charts saved to {OUT_DIR}/k946_equity_curves.png and k946_regime_analysis.png")
