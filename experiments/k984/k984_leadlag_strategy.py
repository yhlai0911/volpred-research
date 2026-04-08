"""
K984: SPY→0050.TW Lead-Lag Trading Strategy
============================================
Based on K983 findings: SPY(t) → 0050.TW(t+1) correlation = 0.40, OOS R² = 15.9%

Tests 4 strategies exploiting the SPY→TW50 lead-lag relationship:
1. Binary Signal (SPY up → hold, SPY down → cash)
2. Proportional Signal (weight proportional to SPY return)
3. Threshold Signal (4-tier weight based on SPY return magnitude)
4. Lead-Lag + VT Overlay (VT base weight adjusted by SPY signal)

Data source: yfinance (SPY, 0050.TW, ^VIX)
Period: 2010-01-01 to 2026-04-07
IS: 2010-2018, OOS: 2019-2026

CRITICAL: signal.shift(1) applied — yesterday's SPY close determines today's TW50 position
Taiwan round-trip cost: ~0.585% (0.1425% buy + 0.1425% sell + 0.3% securities tax)
Trade threshold: weight change > 10% to trigger cost

References:
- K983: SPY→0050.TW lead-lag correlation analysis
- Eun & Shim (1989): International transmission of stock market movements
- Hamao, Masulis & Ng (1990): Correlations in price changes across markets
"""

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
import warnings
from datetime import datetime
from volpred.utils import clean_tw50_data

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. Data Download & Alignment
# ============================================================
print("=" * 60)
print("K984: SPY→0050.TW Lead-Lag Trading Strategy")
print("=" * 60)

print("\n[1] Downloading data...")
spy_df = yf.download('SPY', start='2010-01-01', end='2026-04-07', progress=False)
tw50_df = yf.download('0050.TW', start='2010-01-01', end='2026-04-07', progress=False)
vix_df = yf.download('^VIX', start='2010-01-01', end='2026-04-07', progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy_df.columns, pd.MultiIndex):
    spy_df.columns = spy_df.columns.get_level_values(0)
if isinstance(tw50_df.columns, pd.MultiIndex):
    tw50_df.columns = tw50_df.columns.get_level_values(0)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)

# Extract close prices
spy_close = spy_df['Close'].squeeze()
tw50_close = tw50_df['Close'].squeeze()
vix_close = vix_df['Close'].squeeze()

# Clean TW50 data (split adjustment)
tw50_close_clean, tw50_ret_clean = clean_tw50_data(tw50_close)

# SPY returns
spy_ret = spy_close.pct_change()

# Align dates: use intersection of SPY and TW50 trading days
# Key insight: we need SPY return on day t to trade TW50 on day t+1
# But SPY and TW50 have different trading calendars
# Strategy: for each TW50 trading day, find the most recent SPY return

# Create a common date range
all_tw_dates = tw50_ret_clean.dropna().index
all_spy_dates = spy_ret.dropna().index

# For each TW50 date, get the most recent SPY return (could be same day or previous day)
# This naturally handles the lag: SPY closes ~4:00 PM ET, TW50 opens ~9:00 AM next day (TW time)
spy_ret_aligned = spy_ret.reindex(all_tw_dates, method='ffill')
tw50_ret_aligned = tw50_ret_clean.reindex(all_tw_dates)

# VIX aligned to TW50 dates (use previous day's VIX for Taiwan — VIX lag rule)
vix_aligned = vix_close.reindex(all_tw_dates, method='ffill')

# Drop NaN
mask = spy_ret_aligned.notna() & tw50_ret_aligned.notna() & vix_aligned.notna()
spy_ret_aligned = spy_ret_aligned[mask]
tw50_ret_aligned = tw50_ret_aligned[mask]
vix_aligned = vix_aligned[mask]

print(f"  SPY raw: {len(spy_df)} days")
print(f"  TW50 raw: {len(tw50_df)} days")
print(f"  Aligned: {len(spy_ret_aligned)} days")
print(f"  Date range: {spy_ret_aligned.index[0].strftime('%Y-%m-%d')} to {spy_ret_aligned.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 2. Split into IS and OOS
# ============================================================
is_end = pd.Timestamp('2018-12-31')
is_mask = spy_ret_aligned.index <= is_end
oos_mask = spy_ret_aligned.index > is_end

print(f"\n[2] IS/OOS split:")
print(f"  IS: {is_mask.sum()} days (to {is_end.strftime('%Y-%m-%d')})")
print(f"  OOS: {oos_mask.sum()} days (from 2019-01-01)")

# ============================================================
# 3. Strategy Definitions
# ============================================================
print("\n[3] Computing strategy signals...")

# --- CRITICAL: signal.shift(1) ---
# SPY return on day t is used to determine TW50 weight on day t+1
# Since spy_ret_aligned is already "most recent SPY return before TW50 date",
# we apply .shift(1) to ensure we use YESTERDAY's SPY signal for TODAY's TW50 trade
spy_signal = spy_ret_aligned.shift(1)  # ← MANDATORY lag

# Taiwan transaction cost
TW_COST_ROUNDTRIP = 0.00585  # 0.585% round trip
TRADE_THRESHOLD = 0.10  # Only count as trade if weight changes > 10%

def apply_tx_cost(weights, returns):
    """Apply Taiwan transaction costs when weight changes > threshold."""
    weight_changes = weights.diff().abs()
    # First day: assume entering from cash
    weight_changes.iloc[0] = abs(weights.iloc[0])

    # Cost only when weight change > threshold
    trade_mask = weight_changes > TRADE_THRESHOLD
    tx_cost = pd.Series(0.0, index=returns.index)
    tx_cost[trade_mask] = weight_changes[trade_mask] * TW_COST_ROUNDTRIP

    strategy_ret = weights * returns - tx_cost
    return strategy_ret, trade_mask.sum()


# Strategy 1: Binary Signal
# SPY up → w=1.0, SPY down → w=0.0
w_binary = (spy_signal > 0).astype(float)

# Strategy 2: Proportional Signal
# w = clip(0.5 + k * SPY_return, 0, 1.5)
# Calibrate k on IS period
spy_signal_is = spy_signal[is_mask].dropna()
# Choose k so that +-1 std SPY return maps to [0, 1]
spy_std_is = spy_signal_is.std()
k_prop = 0.5 / (2 * spy_std_is)  # So +-2 std → [0, 1]
print(f"  Proportional: k={k_prop:.1f} (calibrated on IS, SPY std={spy_std_is:.4f})")
w_proportional = (0.5 + k_prop * spy_signal).clip(0, 1.5)

# Strategy 3: Threshold Signal
# SPY > +1%: w=1.2, SPY > 0%: w=1.0, SPY > -1%: w=0.5, SPY < -1%: w=0.0
w_threshold = pd.Series(1.0, index=spy_signal.index)
w_threshold[spy_signal > 0.01] = 1.2
w_threshold[(spy_signal > 0) & (spy_signal <= 0.01)] = 1.0
w_threshold[(spy_signal > -0.01) & (spy_signal <= 0)] = 0.5
w_threshold[spy_signal <= -0.01] = 0.0

# Strategy 4: Lead-Lag + VT Overlay
# Base: 8.63/VIX (Taiwan VT), shift(1) already applied to VIX via ffill alignment
vix_signal = vix_aligned.shift(1)  # Use previous day's VIX
w_vt_base = (8.63 / vix_signal).clip(0, 1.5)
# Overlay: adjust by SPY direction
lead_lag_adj = 1.0 + 0.5 * np.sign(spy_signal)
w_vt_overlay = (w_vt_base * lead_lag_adj).clip(0, 1.5)

# Benchmarks
w_bh = pd.Series(1.0, index=tw50_ret_aligned.index)  # Buy & Hold TW50
w_vt_only = w_vt_base.copy()  # VT only (no lead-lag)

# ============================================================
# 4. Compute Returns with Transaction Costs
# ============================================================
print("\n[4] Computing returns with transaction costs...")

strategies = {
    'Buy&Hold TW50': (w_bh, 'benchmark'),
    'Binary Signal': (w_binary, 'strategy'),
    'Proportional Signal': (w_proportional, 'strategy'),
    'Threshold Signal': (w_threshold, 'strategy'),
    'VT Only (8.63/VIX)': (w_vt_only, 'benchmark'),
    'VT + Lead-Lag': (w_vt_overlay, 'strategy'),
}

results = {}
for name, (weights, stype) in strategies.items():
    # Drop NaN (from shift)
    valid = weights.notna() & tw50_ret_aligned.notna()
    w = weights[valid]
    r = tw50_ret_aligned[valid]

    strat_ret, n_trades = apply_tx_cost(w, r)

    # Split IS/OOS
    is_ret = strat_ret[strat_ret.index <= is_end]
    oos_ret = strat_ret[strat_ret.index > is_end]

    # Full period metrics
    ann_ret = strat_ret.mean() * 252
    ann_vol = strat_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Sortino
    downside = strat_ret[strat_ret < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    # Max Drawdown
    cum_ret = (1 + strat_ret).cumprod()
    rolling_max = cum_ret.cummax()
    drawdown = (cum_ret - rolling_max) / rolling_max
    mdd = drawdown.min()

    # Win rate (days with positive return)
    win_rate = (strat_ret > 0).mean()

    # Turnover (average absolute weight change per day)
    turnover = w.diff().abs().mean() * 252

    # OOS metrics
    oos_ann_ret = oos_ret.mean() * 252
    oos_ann_vol = oos_ret.std() * np.sqrt(252)
    oos_sharpe = oos_ann_ret / oos_ann_vol if oos_ann_vol > 0 else 0
    oos_cum = (1 + oos_ret).cumprod()
    oos_rolling_max = oos_cum.cummax()
    oos_dd = (oos_cum - oos_rolling_max) / oos_rolling_max
    oos_mdd = oos_dd.min()

    # IS metrics
    is_ann_ret = is_ret.mean() * 252
    is_ann_vol = is_ret.std() * np.sqrt(252)
    is_sharpe = is_ann_ret / is_ann_vol if is_ann_vol > 0 else 0

    results[name] = {
        'type': stype,
        'full': {
            'ann_return': round(float(ann_ret), 4),
            'ann_vol': round(float(ann_vol), 4),
            'sharpe': round(float(sharpe), 4),
            'sortino': round(float(sortino), 4),
            'mdd': round(float(mdd), 4),
            'win_rate': round(float(win_rate), 4),
            'turnover': round(float(turnover), 2),
            'n_trades': int(n_trades),
            'n_days': len(strat_ret),
        },
        'is': {
            'ann_return': round(float(is_ann_ret), 4),
            'ann_vol': round(float(is_ann_vol), 4),
            'sharpe': round(float(is_sharpe), 4),
        },
        'oos': {
            'ann_return': round(float(oos_ann_ret), 4),
            'ann_vol': round(float(oos_ann_vol), 4),
            'sharpe': round(float(oos_sharpe), 4),
            'mdd': round(float(oos_mdd), 4),
        },
        'cum_returns': strat_ret,  # Store for plotting
        'drawdowns': drawdown,
        'weights': w,
    }

    print(f"  {name:25s}: Sharpe={sharpe:.3f} (IS={is_sharpe:.3f}, OOS={oos_sharpe:.3f}), "
          f"MDD={mdd:.1%}, Trades={n_trades}, Turnover={turnover:.1f}")

# ============================================================
# 5. Annual Returns Analysis
# ============================================================
print("\n[5] Annual returns breakdown...")

annual_results = {}
for name, res in results.items():
    cum_ret = res['cum_returns']
    by_year = cum_ret.groupby(cum_ret.index.year)
    annual = {}
    for year, yr_ret in by_year:
        yr_ann = yr_ret.mean() * 252
        yr_vol = yr_ret.std() * np.sqrt(252)
        yr_sharpe = yr_ann / yr_vol if yr_vol > 0 else 0
        annual[int(year)] = {
            'return': round(float(yr_ann), 4),
            'vol': round(float(yr_vol), 4),
            'sharpe': round(float(yr_sharpe), 4),
        }
    annual_results[name] = annual

# Print annual Sharpe comparison
years = sorted(set().union(*[d.keys() for d in annual_results.values()]))
print(f"\n{'Year':>6}", end='')
for name in ['Buy&Hold TW50', 'Binary Signal', 'Threshold Signal', 'VT Only (8.63/VIX)', 'VT + Lead-Lag']:
    print(f"  {name[:15]:>15}", end='')
print()
for year in years:
    print(f"{year:>6}", end='')
    for name in ['Buy&Hold TW50', 'Binary Signal', 'Threshold Signal', 'VT Only (8.63/VIX)', 'VT + Lead-Lag']:
        if year in annual_results.get(name, {}):
            s = annual_results[name][year]['sharpe']
            print(f"  {s:>15.3f}", end='')
        else:
            print(f"  {'N/A':>15}", end='')
    print()

# ============================================================
# 6. Stability Analysis: how often does lead-lag strategy beat B&H?
# ============================================================
print("\n[6] OOS stability: strategy vs B&H by year...")
for name in ['Binary Signal', 'Proportional Signal', 'Threshold Signal', 'VT + Lead-Lag']:
    strat_annual = annual_results[name]
    bh_annual = annual_results['Buy&Hold TW50']
    oos_years = [y for y in years if y >= 2019]
    wins = sum(1 for y in oos_years
               if y in strat_annual and y in bh_annual
               and strat_annual[y]['sharpe'] > bh_annual[y]['sharpe'])
    total = len(oos_years)
    print(f"  {name:25s}: beats B&H in {wins}/{total} OOS years")

# ============================================================
# 7. Plots
# ============================================================
print("\n[7] Generating plots...")

BASE_DIR = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a452eb2f/experiments/k984'

# Plot 1: Cumulative Returns
fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

# Full period
ax = axes[0]
for name in ['Buy&Hold TW50', 'Binary Signal', 'Threshold Signal', 'VT Only (8.63/VIX)', 'VT + Lead-Lag']:
    cum = (1 + results[name]['cum_returns']).cumprod()
    ax.plot(cum.index, cum.values, label=name, linewidth=1.2)
ax.axvline(x=is_end, color='gray', linestyle='--', alpha=0.5, label='IS/OOS split')
ax.set_ylabel('Cumulative Return')
ax.set_title('K984: SPY→0050.TW Lead-Lag Trading Strategies (Full Period)')
ax.legend(loc='upper left', fontsize=9)
ax.grid(True, alpha=0.3)

# OOS only
ax = axes[1]
for name in ['Buy&Hold TW50', 'Binary Signal', 'Threshold Signal', 'VT Only (8.63/VIX)', 'VT + Lead-Lag']:
    cr = results[name]['cum_returns']
    oos_ret = cr[cr.index > is_end]
    cum = (1 + oos_ret).cumprod()
    ax.plot(cum.index, cum.values, label=name, linewidth=1.2)
ax.set_ylabel('Cumulative Return (OOS)')
ax.set_title('OOS Period Only (2019-2026)')
ax.legend(loc='upper left', fontsize=9)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(f'{BASE_DIR}/k984_cumulative_returns.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k984_cumulative_returns.png")

# Plot 2: Annual Returns Heatmap
fig, ax = plt.subplots(figsize=(16, 6))
strat_names = ['Buy&Hold TW50', 'Binary Signal', 'Proportional Signal',
               'Threshold Signal', 'VT Only (8.63/VIX)', 'VT + Lead-Lag']
data_matrix = []
for name in strat_names:
    row = [annual_results[name].get(y, {}).get('return', np.nan) for y in years]
    data_matrix.append(row)

data_matrix = np.array(data_matrix)
im = ax.imshow(data_matrix, cmap='RdYlGn', aspect='auto', vmin=-0.3, vmax=0.3)
ax.set_xticks(range(len(years)))
ax.set_xticklabels(years, rotation=45)
ax.set_yticks(range(len(strat_names)))
ax.set_yticklabels(strat_names)
ax.set_title('K984: Annual Returns by Strategy')

# Add text annotations
for i in range(len(strat_names)):
    for j in range(len(years)):
        val = data_matrix[i, j]
        if not np.isnan(val):
            ax.text(j, i, f'{val:.1%}', ha='center', va='center',
                   fontsize=7, color='black' if abs(val) < 0.15 else 'white')

plt.colorbar(im, ax=ax, label='Annual Return')
plt.tight_layout()
plt.savefig(f'{BASE_DIR}/k984_annual_returns.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k984_annual_returns.png")

# Plot 3: Drawdowns
fig, ax = plt.subplots(figsize=(14, 6))
for name in ['Buy&Hold TW50', 'Binary Signal', 'Threshold Signal', 'VT + Lead-Lag']:
    dd = results[name]['drawdowns']
    ax.fill_between(dd.index, dd.values, 0, alpha=0.2, label=name)
    ax.plot(dd.index, dd.values, linewidth=0.8)
ax.axvline(x=is_end, color='gray', linestyle='--', alpha=0.5, label='IS/OOS split')
ax.set_ylabel('Drawdown')
ax.set_title('K984: Drawdowns by Strategy')
ax.legend(loc='lower left', fontsize=9)
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(f'{BASE_DIR}/k984_drawdowns.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k984_drawdowns.png")

# ============================================================
# 8. Save Results JSON
# ============================================================
print("\n[8] Saving results...")

# Remove non-serializable data
results_json = {}
for name, res in results.items():
    results_json[name] = {
        'type': res['type'],
        'full': res['full'],
        'is': res['is'],
        'oos': res['oos'],
    }

output = {
    'experiment_id': 'K984',
    'title': 'SPY→0050.TW Lead-Lag Trading Strategy',
    'description': 'Tests whether K983 lead-lag finding (SPY→TW50 corr=0.40) can be converted to profitable trading strategies after Taiwan transaction costs (~0.585% round trip)',
    'data_source': 'yfinance (SPY, 0050.TW, ^VIX)',
    'period': '2010-01-01 to 2026-04-07',
    'is_period': '2010-01-01 to 2018-12-31',
    'oos_period': '2019-01-01 to 2026-04-07',
    'n_days_aligned': len(spy_ret_aligned),
    'methodology': {
        'signal_lag': 'signal.shift(1) — yesterday SPY return determines today TW50 weight',
        'tx_cost': '0.585% round trip (Taiwan: 0.1425% buy + 0.1425% sell + 0.3% tax)',
        'trade_threshold': '10% weight change triggers cost',
        'proportional_k': round(float(k_prop), 2),
        'vt_base': '8.63/VIX',
    },
    'strategies': results_json,
    'annual_returns': {name: annual_results[name] for name in strat_names},
    'key_findings': {},
    'references': [
        'K983: SPY→0050.TW lead-lag correlation (corr=0.40, OOS R²=15.9%)',
        'Eun & Shim (1989): International transmission of stock market movements, JFE',
        'Hamao, Masulis & Ng (1990): Correlations in price changes, RFS',
    ],
    'seed': 42,
    'timestamp': datetime.now().isoformat(),
}

# Determine key findings
bh_sharpe_oos = results_json['Buy&Hold TW50']['oos']['sharpe']
best_strat = None
best_sharpe_oos = -999
for name, res in results_json.items():
    if res['type'] == 'strategy':
        if res['oos']['sharpe'] > best_sharpe_oos:
            best_sharpe_oos = res['oos']['sharpe']
            best_strat = name

# Check if best strategy beats B&H by > 2x (sanity check)
if best_sharpe_oos > 2 * abs(bh_sharpe_oos) and abs(bh_sharpe_oos) > 0.1:
    output['key_findings']['WARNING'] = f'Best strategy Sharpe ({best_sharpe_oos:.3f}) > 2x B&H ({bh_sharpe_oos:.3f}) — possible bug, verify lag'

output['key_findings']['best_strategy_oos'] = best_strat
output['key_findings']['best_sharpe_oos'] = round(best_sharpe_oos, 4)
output['key_findings']['bh_sharpe_oos'] = round(bh_sharpe_oos, 4)
output['key_findings']['alpha_after_costs'] = best_sharpe_oos > bh_sharpe_oos

# Lead-lag vs VT-only comparison
vt_only_oos = results_json['VT Only (8.63/VIX)']['oos']['sharpe']
vt_leadlag_oos = results_json['VT + Lead-Lag']['oos']['sharpe']
output['key_findings']['vt_overlay_improvement'] = round(vt_leadlag_oos - vt_only_oos, 4)
output['key_findings']['vt_overlay_helps'] = vt_leadlag_oos > vt_only_oos

# Null result check
if not output['key_findings']['alpha_after_costs']:
    output['key_findings']['conclusion'] = 'NULL RESULT: Lead-lag strategies do not generate alpha after Taiwan transaction costs in OOS period'
else:
    output['key_findings']['conclusion'] = f'{best_strat} generates alpha after costs (OOS Sharpe {best_sharpe_oos:.3f} vs B&H {bh_sharpe_oos:.3f})'

with open(f'{BASE_DIR}/k984_leadlag_strategy_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"  Saved k984_leadlag_strategy_results.json")

# ============================================================
# 9. Summary
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"\nBest lead-lag strategy (OOS): {best_strat}")
print(f"  OOS Sharpe: {best_sharpe_oos:.4f}")
print(f"  B&H TW50 OOS Sharpe: {bh_sharpe_oos:.4f}")
print(f"  Alpha after costs: {output['key_findings']['alpha_after_costs']}")
print(f"\nVT overlay improvement: {output['key_findings']['vt_overlay_improvement']:.4f}")
print(f"  VT Only OOS Sharpe: {vt_only_oos:.4f}")
print(f"  VT + Lead-Lag OOS Sharpe: {vt_leadlag_oos:.4f}")
print(f"\nConclusion: {output['key_findings']['conclusion']}")
print("=" * 60)
