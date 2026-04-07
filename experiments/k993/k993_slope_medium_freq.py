"""
K993: VIX Term Structure Medium-Frequency Strategy (5-22 day horizon)

Background:
- K975: VIX/VIX3M slope provides +2.2% incremental R² for 5d RV (DM p=0.0002)
- K976: Slope added to daily MF2-GARCH → NULL (horizon mismatch)
- Conclusion: slope predictive power lives at 5-22 day horizon

This experiment tests whether slope signal can generate alpha
at weekly (5-day) and monthly (22-day) rebalance frequencies.

Data source: yfinance (SPY, ^VIX, ^VIX3M), 2010-01-01 to 2026-04-07
Reference: K975 (VIX/VIX3M slope R² analysis)

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
import warnings
from datetime import datetime
from scipy import stats

warnings.filterwarnings('ignore')
np.random.seed(42)

OUTPUT_DIR = 'experiments/k993'

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 60)
print("K993: VIX Slope Medium-Frequency Strategy")
print("=" * 60)

import yfinance as yf

print("\n[1] Downloading data...")
spy = yf.download('SPY', start='2010-01-01', end='2026-04-07', progress=False)
vix = yf.download('^VIX', start='2010-01-01', end='2026-04-07', progress=False)
vix3m = yf.download('^VIX3M', start='2010-01-01', end='2026-04-07', progress=False)

# Handle multi-level columns if present
for df_name, df in [('spy', spy), ('vix', vix), ('vix3m', vix3m)]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy_close = spy['Close'].squeeze()
vix_close = vix['Close'].squeeze()
vix3m_close = vix3m['Close'].squeeze()

# Align dates
common_idx = spy_close.index.intersection(vix_close.index).intersection(vix3m_close.index)
spy_close = spy_close.loc[common_idx]
vix_close = vix_close.loc[common_idx]
vix3m_close = vix3m_close.loc[common_idx]

print(f"  SPY: {len(spy_close)} days ({spy_close.index[0].date()} to {spy_close.index[-1].date()})")
print(f"  VIX: {len(vix_close)} days")
print(f"  VIX3M: {len(vix3m_close)} days")
print(f"  Common dates: {len(common_idx)} days")

# ============================================================
# 2. SIGNAL CONSTRUCTION
# ============================================================
print("\n[2] Constructing signals...")

# Daily returns
spy_ret = spy_close.pct_change().dropna()

# VIX slope signal
slope = vix_close / vix3m_close  # < 1 = contango, > 1 = backwardation

print(f"  Slope stats: mean={slope.mean():.4f}, std={slope.std():.4f}")
print(f"  Slope < 0.9 (deep contango): {(slope < 0.9).sum()} days ({(slope < 0.9).mean()*100:.1f}%)")
print(f"  Slope 0.9-1.0 (normal): {((slope >= 0.9) & (slope < 1.0)).sum()} days")
print(f"  Slope 1.0-1.1 (mild backw.): {((slope >= 1.0) & (slope < 1.1)).sum()} days")
print(f"  Slope > 1.1 (strong backw.): {(slope >= 1.1).sum()} days ({(slope >= 1.1).mean()*100:.1f}%)")

# ============================================================
# 3. STRATEGY DEFINITIONS
# ============================================================
print("\n[3] Building strategies...")

def compute_strategy_returns(weights, returns, tc_rate=0.0005):
    """
    Compute strategy returns with transaction costs.
    weights: pd.Series of portfolio weights (already lagged)
    returns: pd.Series of asset returns
    tc_rate: one-way transaction cost rate
    """
    common = weights.index.intersection(returns.index)
    w = weights.loc[common]
    r = returns.loc[common]

    # Transaction costs: proportional to weight change
    weight_change = w.diff().abs()
    weight_change.iloc[0] = w.iloc[0]  # Initial allocation
    tc = weight_change * tc_rate

    strat_ret = w * r - tc
    return strat_ret

def weekly_rebalance_signal(daily_signal, rebal_freq=5):
    """
    Convert daily signal to weekly rebalance: only update every rebal_freq days.
    Returns signal shifted by 1 day (lookahead prevention).
    """
    # Shift signal by 1 day FIRST (use yesterday's signal for today's return)
    lagged_signal = daily_signal.shift(1)

    # Then apply weekly hold: only update on rebalance dates
    weekly_signal = lagged_signal.copy()
    last_val = np.nan
    for i in range(len(weekly_signal)):
        if i % rebal_freq == 0 or np.isnan(last_val):
            last_val = weekly_signal.iloc[i]
        else:
            weekly_signal.iloc[i] = last_val

    return weekly_signal

def monthly_rebalance_signal(daily_signal, rebal_freq=22):
    """Same as weekly but with 22-day frequency."""
    return weekly_rebalance_signal(daily_signal, rebal_freq=rebal_freq)

# --- Strategy 1: Slope VT (Weekly) ---
# Regime-based weights from slope
def slope_weight(s):
    if s < 0.9:
        return 1.2  # Deep contango → risk-on
    elif s < 1.0:
        return 1.0  # Normal contango
    elif s < 1.1:
        return 0.7  # Mild backwardation → reduce
    else:
        return 0.3  # Strong backwardation → defensive

slope_wt_daily = slope.apply(slope_weight)
slope_vt_weekly = weekly_rebalance_signal(slope_wt_daily, rebal_freq=5)
slope_vt_monthly = monthly_rebalance_signal(slope_wt_daily, rebal_freq=22)

# --- Strategy 2: Slope + 12/VIX (Weekly) ---
base_12vix = 12.0 / vix_close
base_12vix = base_12vix.clip(0.2, 1.5)

# Slope adjustment: contango boosts, backwardation cuts
slope_adj = 1.0 + 0.3 * (1.0 - slope)
combined_signal = (base_12vix * slope_adj).clip(0.2, 1.5)

slope_12vix_weekly = weekly_rebalance_signal(combined_signal, rebal_freq=5)
slope_12vix_monthly = monthly_rebalance_signal(combined_signal, rebal_freq=22)

# --- Benchmarks ---
# Buy & Hold
bh_weight = pd.Series(1.0, index=spy_ret.index)

# Daily 12/VIX (lagged by 1 day)
daily_12vix_signal = base_12vix.shift(1)  # signal.shift(1) for lookahead prevention
daily_12vix_signal = daily_12vix_signal.reindex(spy_ret.index)

# Weekly 12/VIX (no slope)
weekly_12vix = weekly_rebalance_signal(base_12vix, rebal_freq=5)

print("  Strategies constructed with proper lag (shift=1)")

# ============================================================
# 4. COMPUTE RETURNS
# ============================================================
print("\n[4] Computing strategy returns...")

strategies = {
    'Buy & Hold': bh_weight,
    'Daily 12/VIX': daily_12vix_signal,
    'Weekly 12/VIX': weekly_12vix,
    'Slope VT (Weekly)': slope_vt_weekly,
    'Slope VT (Monthly)': slope_vt_monthly,
    'Slope+12/VIX (Weekly)': slope_12vix_weekly,
    'Slope+12/VIX (Monthly)': slope_12vix_monthly,
}

# Compute returns with transaction costs
strat_returns = {}
for name, weights in strategies.items():
    w = weights.reindex(spy_ret.index)
    tc_rate = 0.0005 if name != 'Buy & Hold' else 0.0
    strat_returns[name] = compute_strategy_returns(w, spy_ret, tc_rate=tc_rate)

# Drop NaN and align
all_dates = spy_ret.index
for name in strat_returns:
    strat_returns[name] = strat_returns[name].reindex(all_dates)

# ============================================================
# 5. PERFORMANCE METRICS
# ============================================================
print("\n[5] Computing performance metrics...")

def compute_metrics(returns, rf_annual=0.04):
    """Compute standard performance metrics."""
    r = returns.dropna()
    if len(r) < 252:
        return {}

    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    rf_daily = rf_annual / 252
    sharpe = (r.mean() - rf_daily) / r.std() * np.sqrt(252) if r.std() > 0 else 0

    # Sortino
    downside = r[r < 0]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-10
    sortino = (ann_ret - rf_annual) / downside_std

    # MDD
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Turnover (annualized weight changes count)
    # Already captured in TC

    return {
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'sortino': float(sortino),
        'mdd': float(mdd),
        'n_days': int(len(r)),
    }

# Split IS/OOS
is_end = '2018-12-31'
oos_start = '2019-01-01'

results = {}
for name, ret in strat_returns.items():
    is_ret = ret.loc[:is_end].dropna()
    oos_ret = ret.loc[oos_start:].dropna()

    is_metrics = compute_metrics(is_ret)
    oos_metrics = compute_metrics(oos_ret)

    results[name] = {
        'IS': is_metrics,
        'OOS': oos_metrics,
        'Full': compute_metrics(ret.dropna()),
    }

    print(f"\n  {name}:")
    if oos_metrics:
        print(f"    OOS Sharpe: {oos_metrics['sharpe']:.4f}, MDD: {oos_metrics['mdd']:.4f}")
    if is_metrics:
        print(f"    IS  Sharpe: {is_metrics['sharpe']:.4f}, MDD: {is_metrics['mdd']:.4f}")

# ============================================================
# 6. STATISTICAL TESTS
# ============================================================
print("\n[6] Statistical tests (DM test)...")

def dm_test(e1, e2, h=1):
    """
    Diebold-Mariano test for equal predictive accuracy.
    Using squared errors as loss function proxy on returns.
    H0: strategies have equal expected returns.
    Uses differential returns directly.
    """
    d = e1 - e2
    d = d.dropna()
    n = len(d)
    if n < 30:
        return np.nan, np.nan

    d_mean = d.mean()
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k

    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan

    dm_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)

# DM tests: each strategy vs Daily 12/VIX (benchmark)
benchmark_ret = strat_returns['Daily 12/VIX'].dropna()
dm_results = {}

for name, ret in strat_returns.items():
    if name in ['Buy & Hold', 'Daily 12/VIX']:
        continue

    common = benchmark_ret.index.intersection(ret.dropna().index)
    if len(common) < 252:
        continue

    # OOS only
    oos_common = common[common >= oos_start]
    if len(oos_common) < 252:
        continue

    dm_stat, dm_p = dm_test(ret.loc[oos_common], benchmark_ret.loc[oos_common])
    dm_results[name] = {'dm_stat': dm_stat, 'dm_p': dm_p}
    print(f"  {name} vs Daily 12/VIX: DM={dm_stat:.4f}, p={dm_p:.4f}")

# ============================================================
# 7. YEARLY PERFORMANCE
# ============================================================
print("\n[7] Yearly performance...")

yearly_sharpe = {}
for name, ret in strat_returns.items():
    r = ret.dropna()
    yearly = {}
    for year in range(2011, 2026):
        yr_ret = r.loc[str(year)]
        if len(yr_ret) > 100:
            s = yr_ret.mean() / yr_ret.std() * np.sqrt(252) if yr_ret.std() > 0 else 0
            yearly[str(year)] = round(float(s), 4)
    yearly_sharpe[name] = yearly

# Print key comparisons
print("\n  Year  | Slope VT(W) | Slope+12VIX(W) | Daily 12/VIX | B&H")
print("  " + "-" * 65)
for year in range(2019, 2026):
    yr = str(year)
    vals = []
    for name in ['Slope VT (Weekly)', 'Slope+12/VIX (Weekly)', 'Daily 12/VIX', 'Buy & Hold']:
        v = yearly_sharpe.get(name, {}).get(yr, float('nan'))
        vals.append(f"{v:8.3f}")
    print(f"  {yr}  | {'|'.join(vals)}")

# ============================================================
# 8. BACKWARDATION PERIOD ANALYSIS
# ============================================================
print("\n[8] Backwardation period analysis...")

# Define stress periods
stress_periods = {
    'COVID_2020': ('2020-02-19', '2020-03-23'),
    'Bear_2022': ('2022-01-03', '2022-10-12'),
    'VIX_Spike_Aug2024': ('2024-07-15', '2024-08-15'),
}

stress_results = {}
for period_name, (start, end) in stress_periods.items():
    print(f"\n  --- {period_name} ({start} to {end}) ---")
    period_slope = slope.loc[start:end]
    avg_slope = period_slope.mean() if len(period_slope) > 0 else np.nan
    print(f"    Average slope: {avg_slope:.4f}")

    period_perf = {}
    for name, ret in strat_returns.items():
        pr = ret.loc[start:end].dropna()
        if len(pr) > 5:
            cum_ret = (1 + pr).prod() - 1
            period_perf[name] = float(cum_ret)
            print(f"    {name}: cumulative return = {cum_ret*100:.2f}%")

    stress_results[period_name] = {
        'avg_slope': float(avg_slope) if not np.isnan(avg_slope) else None,
        'returns': period_perf
    }

# ============================================================
# 9. TURNOVER ANALYSIS
# ============================================================
print("\n[9] Turnover analysis...")

turnover_stats = {}
for name, weights in strategies.items():
    w = weights.reindex(spy_ret.index).dropna()
    if len(w) < 252:
        continue
    daily_turnover = w.diff().abs()
    ann_turnover = daily_turnover.mean() * 252
    n_trades = (daily_turnover > 0.001).sum()
    turnover_stats[name] = {
        'ann_turnover': float(ann_turnover),
        'n_weight_changes': int(n_trades),
        'avg_weight': float(w.mean()),
    }
    print(f"  {name}: ann_turnover={ann_turnover:.4f}, weight_changes={n_trades}, avg_weight={w.mean():.4f}")

# ============================================================
# 10. PLOTS
# ============================================================
print("\n[10] Generating plots...")

# --- Plot 1: Cumulative Returns ---
fig, axes = plt.subplots(2, 1, figsize=(14, 10))

for period_name, period_label, ax in [
    (slice(None, is_end), 'In-Sample (2010-2018)', axes[0]),
    (slice(oos_start, None), 'Out-of-Sample (2019-2026)', axes[1]),
]:
    for name in ['Buy & Hold', 'Daily 12/VIX', 'Weekly 12/VIX',
                 'Slope VT (Weekly)', 'Slope+12/VIX (Weekly)']:
        ret = strat_returns[name].loc[period_name].dropna()
        cum = (1 + ret).cumprod()
        ax.plot(cum.index.to_numpy(), cum.values, label=name, alpha=0.8)

    ax.set_title(f'{period_label}', fontsize=13)
    ax.set_ylabel('Cumulative Return')
    ax.legend(fontsize=9, loc='upper left')
    ax.grid(True, alpha=0.3)

plt.suptitle('K993: VIX Slope Medium-Frequency Strategy — Cumulative Returns', fontsize=14, y=1.02)
plt.tight_layout()
plt.savefig(f'{OUTPUT_DIR}/k993_cumulative_returns.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k993_cumulative_returns.png")

# --- Plot 2: Slope Regime + Strategy Weights ---
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

# Slope time series
ax1 = axes[0]
ax1.plot(slope.index.to_numpy(), slope.values, color='navy', alpha=0.6, linewidth=0.5)
ax1.axhline(y=1.0, color='red', linestyle='--', alpha=0.5, label='Contango/Backw. boundary')
ax1.axhline(y=0.9, color='green', linestyle='--', alpha=0.5, label='Deep contango')
ax1.fill_between(slope.index.to_numpy(), 0, slope.values, where=(slope > 1.0).values, alpha=0.2, color='red', label='Backwardation')
ax1.set_ylabel('VIX/VIX3M Slope')
ax1.set_title('VIX Term Structure Slope')
ax1.legend(fontsize=8)
ax1.grid(True, alpha=0.3)

# Slope VT weights
ax2 = axes[1]
w_svt = slope_vt_weekly.dropna()
ax2.plot(w_svt.index.to_numpy(), w_svt.values, color='blue', alpha=0.7, linewidth=0.5)
ax2.set_ylabel('Weight')
ax2.set_title('Slope VT (Weekly) — Portfolio Weight')
ax2.grid(True, alpha=0.3)

# Slope + 12/VIX weights
ax3 = axes[2]
w_comb = slope_12vix_weekly.dropna()
ax3.plot(w_comb.index.to_numpy(), w_comb.values, color='purple', alpha=0.7, linewidth=0.5)
ax3.set_ylabel('Weight')
ax3.set_title('Slope+12/VIX (Weekly) — Portfolio Weight')
ax3.grid(True, alpha=0.3)

plt.suptitle('K993: VIX Slope Regime & Strategy Weights', fontsize=14, y=1.02)
plt.tight_layout()
plt.savefig(f'{OUTPUT_DIR}/k993_slope_regime.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k993_slope_regime.png")

# ============================================================
# 11. RESULTS JSON
# ============================================================
print("\n[11] Saving results...")

output = {
    'experiment_id': 'K993',
    'title': 'VIX Term Structure Medium-Frequency Strategy',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY, ^VIX, ^VIX3M)',
    'data_period': f"{spy_close.index[0].date()} to {spy_close.index[-1].date()}",
    'n_common_days': int(len(common_idx)),
    'reference': 'K975 (VIX/VIX3M slope +2.2% R² for 5d RV)',
    'methodology': {
        'signal': 'VIX/VIX3M slope ratio',
        'rebalance_frequencies': ['daily', 'weekly (5d)', 'monthly (22d)'],
        'transaction_cost': '0.05% per weight change',
        'IS_period': '2010-2018',
        'OOS_period': '2019-2026',
        'lag': 'signal.shift(1) applied before rebalance logic',
        'seed': 42,
    },
    'strategies': {},
    'dm_tests_vs_daily_12vix': dm_results,
    'yearly_sharpe': yearly_sharpe,
    'stress_periods': stress_results,
    'turnover': turnover_stats,
    'slope_stats': {
        'mean': float(slope.mean()),
        'std': float(slope.std()),
        'pct_contango': float((slope < 1.0).mean()),
        'pct_deep_contango': float((slope < 0.9).mean()),
        'pct_backwardation': float((slope >= 1.0).mean()),
        'pct_strong_backwardation': float((slope >= 1.1).mean()),
    },
}

for name in results:
    output['strategies'][name] = results[name]

with open(f'{OUTPUT_DIR}/k993_slope_medium_freq_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

print("  Saved k993_slope_medium_freq_results.json")

# ============================================================
# 12. CONCLUSION
# ============================================================
print("\n" + "=" * 60)
print("CONCLUSION")
print("=" * 60)

# Compare OOS Sharpe
oos_sharpes = {}
for name in results:
    if results[name]['OOS']:
        oos_sharpes[name] = results[name]['OOS']['sharpe']

best = max(oos_sharpes, key=oos_sharpes.get) if oos_sharpes else 'N/A'
print(f"\n  Best OOS Sharpe: {best} = {oos_sharpes.get(best, 'N/A'):.4f}")
print(f"  Daily 12/VIX OOS Sharpe: {oos_sharpes.get('Daily 12/VIX', 'N/A'):.4f}")

# Check if slope adds value
slope_weekly_sharpe = oos_sharpes.get('Slope+12/VIX (Weekly)', 0)
daily_12vix_sharpe = oos_sharpes.get('Daily 12/VIX', 0)
weekly_12vix_sharpe = oos_sharpes.get('Weekly 12/VIX', 0)

print(f"\n  Slope+12/VIX (Weekly) vs Daily 12/VIX:")
print(f"    Sharpe diff: {slope_weekly_sharpe - daily_12vix_sharpe:+.4f}")

dm_slope = dm_results.get('Slope+12/VIX (Weekly)', {})
if dm_slope:
    print(f"    DM test: stat={dm_slope['dm_stat']:.4f}, p={dm_slope['dm_p']:.4f}")
    sig = "SIGNIFICANT" if abs(dm_slope.get('dm_stat', 0)) > 3.0 else "NOT significant (Harvey threshold |t|>3.0)"
    print(f"    {sig}")

print(f"\n  Weekly 12/VIX vs Daily 12/VIX:")
print(f"    Sharpe diff: {weekly_12vix_sharpe - daily_12vix_sharpe:+.4f}")
print(f"    (Weekly rebalance preserves/loses how much of daily?)")

# Final verdict
slope_adds_alpha = (slope_weekly_sharpe > daily_12vix_sharpe + 0.05) and \
                   dm_slope.get('dm_p', 1.0) < 0.05

if slope_adds_alpha:
    print("\n  ★ POSITIVE: Slope signal adds alpha at medium frequency")
else:
    print("\n  ☆ NULL/MARGINAL: Slope signal does NOT clearly add alpha as a strategy")
    print("    K975's +2.2% R² for 5d RV prediction does not translate to tradeable alpha")
    print("    This is consistent with K976: slope is a volatility predictor, not a return predictor")

print("\n  Done.")
