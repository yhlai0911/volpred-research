"""
K388: Robust Minimax Portfolio — Optimize for the WORST Case
============================================================
[提出: Claude, 執行: Claude]

跳躍式探索：Mean-variance optimizes for AVERAGE case.
Minimax optimizes for WORST case — maximize the MINIMUM return.

Data: SPY, GLD, VIX daily from yfinance. 2005-2024.
Methodology:
  1. Minimax allocation (maximize worst 22-day return)
  2. Minimax + VT overlay (12/VIX)
  3. Compare: Mean-variance optimal vs Minimax vs Equal weight
  4. Rolling minimax: does optimal worst-case weight change?
  5. Conditional minimax: VIX<20 vs VIX>25
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

print("=" * 70)
print("K388: Robust Minimax Portfolio — Optimize for the WORST Case")
print("=" * 70)

# ============================================================
# 1. Download data
# ============================================================
print("\n[1] Downloading data from yfinance...")
tickers = ['SPY', 'GLD', '^VIX']
data = yf.download(tickers, start='2004-12-01', end='2025-01-01', auto_adjust=True)
prices = data['Close'].dropna()

# Ensure column names
col_map = {}
for c in prices.columns:
    if 'SPY' in str(c).upper():
        col_map[c] = 'SPY'
    elif 'GLD' in str(c).upper():
        col_map[c] = 'GLD'
    elif 'VIX' in str(c).upper():
        col_map[c] = 'VIX'
prices = prices.rename(columns=col_map)

spy = prices['SPY'].dropna()
gld = prices['GLD'].dropna()
vix = prices['VIX'].dropna()

# Align to common dates
common_idx = spy.index.intersection(gld.index).intersection(vix.index)
spy = spy.loc[common_idx]
gld = gld.loc[common_idx]
vix = vix.loc[common_idx]

# Daily returns
spy_ret = spy.pct_change().dropna()
gld_ret = gld.pct_change().dropna()

# Align all
common_idx2 = spy_ret.index.intersection(gld_ret.index).intersection(vix.index)
spy_ret = spy_ret.loc[common_idx2].values
gld_ret = gld_ret.loc[common_idx2].values
vix_vals = vix.loc[common_idx2].values
dates = common_idx2

print(f"  Period: {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
print(f"  Trading days: {len(dates)}")

# ============================================================
# 2. Fast vectorized rolling 22-day return
# ============================================================

def fast_rolling_22d(daily_returns, window=22):
    """Compute rolling 22-day returns using cumulative product — vectorized."""
    cum = np.cumprod(1 + daily_returns)
    # rolling_ret[i] = cum[i] / cum[i-window] - 1
    rolling_ret = cum[window:] / cum[:-window] - 1
    return rolling_ret

def portfolio_metrics(w, spy_r, gld_r):
    """Compute all portfolio metrics for a given SPY weight. Fully vectorized."""
    port = w * spy_r + (1 - w) * gld_r
    r22 = fast_rolling_22d(port)

    worst_22d = np.min(r22)
    pct_5 = np.percentile(r22, 5)
    pct_1 = np.percentile(r22, 1)
    avg_22d = np.mean(r22)

    ann_ret = np.mean(port) * 252
    ann_vol = np.std(port, ddof=1) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = np.cumprod(1 + port)
    running_max = np.maximum.accumulate(cum)
    drawdown = (cum - running_max) / running_max
    max_dd = np.min(drawdown)

    # CVaR
    mask_5 = r22 <= np.percentile(r22, 5)
    cvar_5 = np.mean(r22[mask_5])
    mask_1 = r22 <= np.percentile(r22, 1)
    cvar_1 = np.mean(r22[mask_1])

    return {
        'worst_22d': worst_22d,
        'pct_5_22d': pct_5,
        'pct_1_22d': pct_1,
        'avg_22d': avg_22d,
        'ann_return': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'cvar_5': cvar_5,
        'cvar_1': cvar_1,
    }

# ============================================================
# 3. Minimax allocation — Full sample
# ============================================================
print("\n[2] Computing Minimax allocation (full sample)...")
print("    Testing SPY weights from 0% to 100% in 5% steps\n")

weights = np.arange(0, 1.05, 0.05)
results = []

for w in weights:
    m = portfolio_metrics(w, spy_ret, gld_ret)
    m['spy_weight'] = round(w, 2)
    m['gld_weight'] = round(1 - w, 2)
    results.append(m)

df_results = pd.DataFrame(results)

# Find optimal allocations
minimax_idx = df_results['worst_22d'].idxmax()
sharpe_idx = df_results['sharpe'].idxmax()
pct5_idx = df_results['pct_5_22d'].idxmax()

print("  Full results table:")
print("  " + "-" * 110)
print(f"  {'SPY%':>5} {'GLD%':>5} | {'Worst22d':>9} {'P5_22d':>9} {'P1_22d':>9} | {'AnnRet':>8} {'AnnVol':>8} {'Sharpe':>8} {'MaxDD':>8}")
print("  " + "-" * 110)
for idx, r in df_results.iterrows():
    marker = ""
    if idx == minimax_idx:
        marker = " <-- MINIMAX"
    elif idx == sharpe_idx:
        marker = " <-- MAX SHARPE"
    elif abs(r['spy_weight'] - 0.50) < 0.01:
        marker = " <-- 50/50"
    print(f"  {r['spy_weight']*100:5.0f} {r['gld_weight']*100:5.0f} | {r['worst_22d']:9.4f} {r['pct_5_22d']:9.4f} {r['pct_1_22d']:9.4f} | {r['ann_return']:8.4f} {r['ann_vol']:8.4f} {r['sharpe']:8.4f} {r['max_dd']:8.4f}{marker}")
print("  " + "-" * 110)

print(f"\n  MINIMAX optimal: SPY={df_results.loc[minimax_idx, 'spy_weight']*100:.0f}%"
      f"  (worst 22d = {df_results.loc[minimax_idx, 'worst_22d']:.4f})")
print(f"  MAX SHARPE optimal: SPY={df_results.loc[sharpe_idx, 'spy_weight']*100:.0f}%"
      f"  (Sharpe = {df_results.loc[sharpe_idx, 'sharpe']:.4f})")
print(f"  MINIMAX Sharpe: {df_results.loc[minimax_idx, 'sharpe']:.4f}"
      f"  vs MAX SHARPE worst 22d: {df_results.loc[sharpe_idx, 'worst_22d']:.4f}")

# ============================================================
# 4. Minimax + VT overlay
# ============================================================
print("\n[3] Minimax + VT (12/VIX) overlay...")

vt_weight_factor = np.minimum(1.0, 12.0 / vix_vals)
vt_results = []

for w in weights:
    # Effective SPY weight = w * vt_weight_factor
    eff_spy = w * vt_weight_factor
    port = eff_spy * spy_ret + (1 - eff_spy) * gld_ret
    r22 = fast_rolling_22d(port)

    worst_22d = np.min(r22)
    pct_5 = np.percentile(r22, 5)

    ann_ret = np.mean(port) * 252
    ann_vol = np.std(port, ddof=1) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = np.cumprod(1 + port)
    running_max = np.maximum.accumulate(cum)
    max_dd = np.min((cum - running_max) / running_max)

    vt_results.append({
        'spy_weight': round(w, 2),
        'worst_22d': worst_22d,
        'pct_5_22d': pct_5,
        'ann_return': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'max_dd': max_dd,
    })

df_vt = pd.DataFrame(vt_results)
vt_minimax_idx = df_vt['worst_22d'].idxmax()
vt_sharpe_idx = df_vt['sharpe'].idxmax()

print(f"\n  VT Minimax optimal: SPY base={df_vt.loc[vt_minimax_idx, 'spy_weight']*100:.0f}%"
      f"  (worst 22d = {df_vt.loc[vt_minimax_idx, 'worst_22d']:.4f})")
print(f"  VT Max Sharpe optimal: SPY base={df_vt.loc[vt_sharpe_idx, 'spy_weight']*100:.0f}%"
      f"  (Sharpe = {df_vt.loc[vt_sharpe_idx, 'sharpe']:.4f})")

print("\n  Comparison: Plain vs VT overlay at their respective minimax-optimal weights")
print(f"  {'Metric':<20} {'Plain':>12} {'VT':>12} {'Improvement':>14}")
print("  " + "-" * 60)
plain_mm = df_results.loc[minimax_idx]
vt_mm = df_vt.loc[vt_minimax_idx]
for metric in ['worst_22d', 'pct_5_22d', 'ann_return', 'sharpe', 'max_dd']:
    if metric in plain_mm and metric in vt_mm:
        p_val = plain_mm[metric]
        v_val = vt_mm[metric]
        diff = v_val - p_val
        print(f"  {metric:<20} {p_val:12.4f} {v_val:12.4f} {diff:+14.4f}")

# ============================================================
# 5. Rolling Minimax — 5-year rolling window
# ============================================================
print("\n[4] Rolling Minimax (5-year rolling window)...")

rolling_window_days = 5 * 252  # ~1260 days

rolling_minimax_weights = []
eval_dates_list = []

step = 22  # Monthly evaluation
for end_idx in range(rolling_window_days, len(spy_ret), step):
    start_idx = end_idx - rolling_window_days

    spy_w = spy_ret[start_idx:end_idx]
    gld_w = gld_ret[start_idx:end_idx]

    best_worst = -np.inf
    best_w = 0.5

    for w in np.arange(0, 1.05, 0.05):
        port = w * spy_w + (1 - w) * gld_w
        r22 = fast_rolling_22d(port)
        if len(r22) > 0:
            worst = np.min(r22)
            if worst > best_worst:
                best_worst = worst
                best_w = w

    rolling_minimax_weights.append(best_w)
    eval_dates_list.append(dates[end_idx])

df_rolling = pd.DataFrame({
    'date': eval_dates_list,
    'minimax_spy_weight': rolling_minimax_weights
})

print(f"  Evaluated {len(df_rolling)} monthly windows")
print(f"  Period: {df_rolling['date'].iloc[0].strftime('%Y-%m-%d')} to {df_rolling['date'].iloc[-1].strftime('%Y-%m-%d')}")
print(f"\n  Rolling Minimax SPY weight statistics:")
print(f"    Mean:   {df_rolling['minimax_spy_weight'].mean():.2f}")
print(f"    Median: {df_rolling['minimax_spy_weight'].median():.2f}")
print(f"    Std:    {df_rolling['minimax_spy_weight'].std():.2f}")
print(f"    Min:    {df_rolling['minimax_spy_weight'].min():.2f}")
print(f"    Max:    {df_rolling['minimax_spy_weight'].max():.2f}")

# Decade breakdown
print(f"\n  Period breakdown of rolling minimax SPY weight:")
for label, y_start, y_end in [("2010-2014", 2010, 2015), ("2015-2019", 2015, 2020), ("2020-2024", 2020, 2025)]:
    mask = (df_rolling['date'] >= f'{y_start}-01-01') & (df_rolling['date'] < f'{y_end}-01-01')
    if mask.sum() > 0:
        sub = df_rolling.loc[mask, 'minimax_spy_weight']
        print(f"    {label}: mean={sub.mean():.2f}, median={sub.median():.2f}, std={sub.std():.2f}, range=[{sub.min():.2f}, {sub.max():.2f}]")

# ============================================================
# 6. Conditional Minimax — by VIX regime
# ============================================================
print("\n[5] Conditional Minimax — by VIX regime...")

for regime_name, vix_cond in [("VIX < 20 (calm)", vix_vals < 20),
                                ("VIX 20-25 (elevated)", (vix_vals >= 20) & (vix_vals <= 25)),
                                ("VIX > 25 (stressed)", vix_vals > 25)]:

    regime_spy = spy_ret[vix_cond]
    regime_gld = gld_ret[vix_cond]

    if len(regime_spy) < 50:
        print(f"\n  {regime_name}: insufficient data ({len(regime_spy)} days)")
        continue

    print(f"\n  {regime_name} ({len(regime_spy)} days, {len(regime_spy)/len(spy_ret)*100:.1f}% of sample):")

    best_worst = -np.inf
    best_w = 0.5
    best_sharpe_w = 0.5
    best_sharpe = -np.inf

    for w in weights:
        port = w * regime_spy + (1 - w) * regime_gld
        r22 = fast_rolling_22d(port)

        if len(r22) < 10:
            continue

        worst = np.min(r22)
        ann_ret = np.mean(port) * 252
        ann_vol = np.std(port, ddof=1) * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

        if worst > best_worst:
            best_worst = worst
            best_w = w
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_sharpe_w = w

    print(f"    Minimax optimal: SPY={best_w*100:.0f}% (worst 22d = {best_worst:.4f})")
    print(f"    Max Sharpe:      SPY={best_sharpe_w*100:.0f}% (Sharpe = {best_sharpe:.4f})")
    print(f"    Gap: {abs(best_w - best_sharpe_w)*100:.0f} percentage points")

# ============================================================
# 7. CVaR comparison
# ============================================================
print("\n[6] CVaR (Expected Shortfall) comparison at 5% and 1% levels...")
print(f"\n  {'SPY%':>5} | {'CVaR5%':>9} {'CVaR1%':>9} | {'VT CVaR5%':>10} {'VT CVaR1%':>10}")
print("  " + "-" * 55)

for w in [0.0, 0.20, 0.30, 0.40, 0.50, 0.60, 0.80, 1.0]:
    m_plain = portfolio_metrics(w, spy_ret, gld_ret)

    eff_spy = w * vt_weight_factor
    port_vt = eff_spy * spy_ret + (1 - eff_spy) * gld_ret
    r22_vt = fast_rolling_22d(port_vt)
    mask5_vt = r22_vt <= np.percentile(r22_vt, 5)
    cvar5_vt = np.mean(r22_vt[mask5_vt])
    mask1_vt = r22_vt <= np.percentile(r22_vt, 1)
    cvar1_vt = np.mean(r22_vt[mask1_vt])

    print(f"  {w*100:5.0f} | {m_plain['cvar_5']:9.4f} {m_plain['cvar_1']:9.4f} | {cvar5_vt:10.4f} {cvar1_vt:10.4f}")

# ============================================================
# 8. Minimax regret
# ============================================================
print("\n[7] Minimax Regret analysis...")
print("    (Minimize the maximum shortfall vs the best-performing asset in each period)")

r22_spy_full = fast_rolling_22d(spy_ret)
r22_gld_full = fast_rolling_22d(gld_ret)
best_asset_22d = np.maximum(r22_spy_full, r22_gld_full)

regret_results = []
for w in weights:
    port = w * spy_ret + (1 - w) * gld_ret
    r22_port = fast_rolling_22d(port)

    # Align lengths (they should match since same input length)
    n = min(len(r22_port), len(best_asset_22d))
    regret = best_asset_22d[:n] - r22_port[:n]
    max_regret = np.max(regret)
    avg_regret = np.mean(regret)

    regret_results.append({
        'spy_weight': round(w, 2),
        'max_regret': round(max_regret, 4),
        'avg_regret': round(avg_regret, 4),
    })

df_regret = pd.DataFrame(regret_results)
min_regret_idx = df_regret['max_regret'].idxmin()
min_avg_regret_idx = df_regret['avg_regret'].idxmin()

print(f"\n  Minimax Regret optimal: SPY={df_regret.loc[min_regret_idx, 'spy_weight']*100:.0f}%"
      f"  (max regret = {df_regret.loc[min_regret_idx, 'max_regret']:.4f})")
print(f"  Min Avg Regret:        SPY={df_regret.loc[min_avg_regret_idx, 'spy_weight']*100:.0f}%"
      f"  (avg regret = {df_regret.loc[min_avg_regret_idx, 'avg_regret']:.4f})")

# ============================================================
# 9. Grand comparison table
# ============================================================
print("\n" + "=" * 70)
print("[8] GRAND COMPARISON — All optimization criteria")
print("=" * 70)

# Find CVaR 5% optimal
best_cvar5 = -np.inf
best_cvar5_w = 0.5
for w in weights:
    m = portfolio_metrics(w, spy_ret, gld_ret)
    if m['cvar_5'] > best_cvar5:
        best_cvar5 = m['cvar_5']
        best_cvar5_w = w

criteria = {
    'Minimax (worst 22d)': df_results.loc[minimax_idx, 'spy_weight'],
    'Max Sharpe': df_results.loc[sharpe_idx, 'spy_weight'],
    'CVaR 5% optimal': best_cvar5_w,
    'Minimax Regret': df_regret.loc[min_regret_idx, 'spy_weight'],
    'Equal Weight': 0.50,
    'VT Minimax': df_vt.loc[vt_minimax_idx, 'spy_weight'],
    'VT Max Sharpe': df_vt.loc[vt_sharpe_idx, 'spy_weight'],
}

print(f"\n  {'Criterion':<25} {'SPY%':>6} {'GLD%':>6} | {'AnnRet':>8} {'Sharpe':>8} {'Worst22d':>10} {'MaxDD':>8}")
print("  " + "-" * 85)

for name, w in criteria.items():
    is_vt = name.startswith('VT')
    if is_vt:
        eff_spy = w * vt_weight_factor
        port = eff_spy * spy_ret + (1 - eff_spy) * gld_ret
    else:
        port = w * spy_ret + (1 - w) * gld_ret

    ann_ret = np.mean(port) * 252
    ann_vol = np.std(port, ddof=1) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    r22 = fast_rolling_22d(port)
    worst22 = np.min(r22)
    cum = np.cumprod(1 + port)
    mdd = np.min((cum - np.maximum.accumulate(cum)) / np.maximum.accumulate(cum))

    print(f"  {name:<25} {w*100:6.0f} {(1-w)*100:6.0f} | {ann_ret:8.4f} {sharpe:8.4f} {worst22:10.4f} {mdd:8.4f}")

# ============================================================
# 10. Trade-off analysis
# ============================================================
print("\n" + "=" * 70)
print("[9] TRADE-OFF ANALYSIS — Sharpe vs Worst Case")
print("=" * 70)

mm_w = df_results.loc[minimax_idx, 'spy_weight']
sh_w = df_results.loc[sharpe_idx, 'spy_weight']
mm_sharpe = df_results.loc[minimax_idx, 'sharpe']
sh_sharpe = df_results.loc[sharpe_idx, 'sharpe']
mm_worst = df_results.loc[minimax_idx, 'worst_22d']
sh_worst = df_results.loc[sharpe_idx, 'worst_22d']

sharpe_cost = sh_sharpe - mm_sharpe
worst_improvement = mm_worst - sh_worst

print(f"\n  Moving from Max-Sharpe ({sh_w*100:.0f}% SPY) to Minimax ({mm_w*100:.0f}% SPY):")
print(f"    Sharpe cost:       {sharpe_cost:+.4f} ({sharpe_cost/sh_sharpe*100:+.1f}%)")
print(f"    Worst-case gain:   {worst_improvement:+.4f} ({worst_improvement/abs(sh_worst)*100:+.1f}%)")
if sharpe_cost > 0:
    print(f"    Trade-off ratio:   {abs(worst_improvement/sharpe_cost):.2f}x worst-case improvement per unit Sharpe lost")
else:
    print(f"    No Sharpe cost! Minimax is also better on Sharpe.")

# ============================================================
# 11. Bootstrap CI for minimax weight
# ============================================================
print("\n[10] Bootstrap CI for minimax-optimal SPY weight (10,000 reps)...")

np.random.seed(42)
n_bootstrap = 10000
bootstrap_weights = np.zeros(n_bootstrap)

n_days = len(spy_ret)
block_size = 22

for b in range(n_bootstrap):
    # Block bootstrap
    n_blocks = n_days // block_size + 1
    block_starts = np.random.randint(0, n_days - block_size, size=n_blocks)

    indices = []
    for start in block_starts:
        indices.extend(range(start, start + block_size))
    indices = indices[:n_days]

    boot_spy = spy_ret[indices]
    boot_gld = gld_ret[indices]

    best_worst = -np.inf
    best_w = 0.5

    for w in np.arange(0, 1.05, 0.10):  # Coarser grid for speed
        port = w * boot_spy + (1 - w) * boot_gld
        r22 = fast_rolling_22d(port)
        if len(r22) > 0:
            worst = np.min(r22)
            if worst > best_worst:
                best_worst = worst
                best_w = w

    bootstrap_weights[b] = best_w

    if (b + 1) % 2000 == 0:
        print(f"    ... {b+1}/{n_bootstrap} done")

ci_lower = np.percentile(bootstrap_weights, 2.5)
ci_upper = np.percentile(bootstrap_weights, 97.5)
ci_median = np.median(bootstrap_weights)

print(f"\n  Bootstrap median minimax SPY weight: {ci_median:.2f}")
print(f"  95% CI: [{ci_lower:.2f}, {ci_upper:.2f}]")
print(f"  Distribution:")
for w_val in sorted(np.unique(bootstrap_weights)):
    count = (bootstrap_weights == w_val).sum()
    pct = count / n_bootstrap * 100
    if pct >= 0.5:
        bar = '#' * int(pct)
        print(f"    SPY={w_val*100:3.0f}%: {pct:5.1f}% {bar}")

# ============================================================
# 12. Save results
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

summary = {
    'experiment': 'K388',
    'title': 'Robust Minimax Portfolio — Optimize for Worst Case',
    'data_source': 'yfinance (SPY, GLD, ^VIX)',
    'period': f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
    'n_trading_days': int(len(dates)),
    'plain_minimax': {
        'spy_weight': float(df_results.loc[minimax_idx, 'spy_weight']),
        'worst_22d': float(df_results.loc[minimax_idx, 'worst_22d']),
        'sharpe': float(df_results.loc[minimax_idx, 'sharpe']),
        'max_dd': float(df_results.loc[minimax_idx, 'max_dd']),
    },
    'max_sharpe': {
        'spy_weight': float(df_results.loc[sharpe_idx, 'spy_weight']),
        'worst_22d': float(df_results.loc[sharpe_idx, 'worst_22d']),
        'sharpe': float(df_results.loc[sharpe_idx, 'sharpe']),
        'max_dd': float(df_results.loc[sharpe_idx, 'max_dd']),
    },
    'vt_minimax': {
        'spy_weight': float(df_vt.loc[vt_minimax_idx, 'spy_weight']),
        'worst_22d': float(df_vt.loc[vt_minimax_idx, 'worst_22d']),
        'sharpe': float(df_vt.loc[vt_minimax_idx, 'sharpe']),
        'max_dd': float(df_vt.loc[vt_minimax_idx, 'max_dd']),
    },
    'minimax_regret': {
        'spy_weight': float(df_regret.loc[min_regret_idx, 'spy_weight']),
        'max_regret': float(df_regret.loc[min_regret_idx, 'max_regret']),
    },
    'cvar5_optimal': {
        'spy_weight': float(best_cvar5_w),
    },
    'trade_off': {
        'sharpe_cost': round(float(sharpe_cost), 4),
        'worst_case_gain': round(float(worst_improvement), 4),
    },
    'bootstrap_95ci': {
        'median': float(ci_median),
        'lower': float(ci_lower),
        'upper': float(ci_upper),
    },
    'rolling_minimax': {
        'mean_weight': round(float(df_rolling['minimax_spy_weight'].mean()), 2),
        'std_weight': round(float(df_rolling['minimax_spy_weight'].std()), 2),
        'min_weight': round(float(df_rolling['minimax_spy_weight'].min()), 2),
        'max_weight': round(float(df_rolling['minimax_spy_weight'].max()), 2),
    },
}

results_path = 'experiments/k388_minimax_results.json'
with open(results_path, 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\n  Results saved to: {results_path}")

print(f"""
KEY FINDINGS:
  1. Minimax optimal (worst-case) SPY weight:  {summary['plain_minimax']['spy_weight']*100:.0f}%
     vs Max Sharpe SPY weight:                 {summary['max_sharpe']['spy_weight']*100:.0f}%
     These are {'DIFFERENT' if abs(summary['plain_minimax']['spy_weight'] - summary['max_sharpe']['spy_weight']) > 0.05 else 'SIMILAR'} criteria leading to {'different' if abs(summary['plain_minimax']['spy_weight'] - summary['max_sharpe']['spy_weight']) > 0.05 else 'similar'} allocations

  2. VT overlay shifts minimax optimal to:     {summary['vt_minimax']['spy_weight']*100:.0f}% SPY
     VT improves worst 22d from {summary['plain_minimax']['worst_22d']:.4f} to {summary['vt_minimax']['worst_22d']:.4f}

  3. Bootstrap 95% CI for minimax weight:      [{summary['bootstrap_95ci']['lower']*100:.0f}%, {summary['bootstrap_95ci']['upper']*100:.0f}%]

  4. Rolling minimax weight range:             {summary['rolling_minimax']['min_weight']*100:.0f}% - {summary['rolling_minimax']['max_weight']*100:.0f}%
     (std = {summary['rolling_minimax']['std_weight']*100:.0f}pp -> {'UNSTABLE' if summary['rolling_minimax']['std_weight'] > 0.15 else 'moderately stable' if summary['rolling_minimax']['std_weight'] > 0.08 else 'STABLE'})
""")
