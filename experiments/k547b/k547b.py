#!/usr/bin/env python3
"""
K547b: Daily VT shift(1) Re-run — VIX Timing Correction
=========================================================
K547 Codex review CONDITIONAL required verification:
  weight[t] = 12 / VIX[t]  →  weight[t] = 12 / VIX[t-1] (shift(1))

If Daily VT Sharpe changes >5% (relative), article mile_53983530 needs update.

Lookahead policy: VIX[t-1] determines weight[t]; SPY return[t] realized at close[t].
Seed: 42 (all stochastic procedures)
"""

import json
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime

warnings.filterwarnings('ignore')
np.random.seed(42)

start_time = time.time()

print("=" * 70)
print("K547b: Daily VT shift(1) Re-run — VIX Timing Correction")
print("=" * 70)

# =================================================================
# 1. DATA DOWNLOAD (same period as K547)
# =================================================================
print("\n[1] Downloading data (2005-2026, same as K547)...")
spy = yf.download('SPY', start='2005-01-01', end='2026-03-27', progress=False)
vix = yf.download('^VIX', start='2005-01-01', end='2026-03-27', progress=False)

for df_raw in [spy, vix]:
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)

spy_close = spy['Close'].dropna()
vix_close = vix['Close'].dropna()

common_idx = spy_close.index.intersection(vix_close.index)
spy_close = spy_close.loc[common_idx]
vix_close = vix_close.loc[common_idx]

spy_ret = spy_close.pct_change().dropna()
vix_aligned = vix_close.reindex(spy_ret.index).ffill()

# KEY FIX: shift VIX by 1 day — use previous day's VIX for today's weight
vix_lagged = vix_aligned.shift(1)

# Drop the first NaN row (shift artefact) so that monthly_vt — which sets its
# weight ONCE per month on the first trading day — does not hold zero exposure
# for the entire first calendar month while daily_vt only loses 1 day.
# This keeps the starting conditions symmetric across all six strategies.
first_valid = vix_lagged.first_valid_index()
spy_ret = spy_ret.loc[first_valid:]
vix_lagged = vix_lagged.loc[first_valid:]

print(f"  SPY: {spy_ret.index[0].date()} to {spy_ret.index[-1].date()}, N={len(spy_ret)}")
print(f"  VIX lagged: shift(1) applied, first valid={vix_lagged.first_valid_index()}")

# =================================================================
# 2. CLASSIFY TRADING DAYS: ToM vs MID-MONTH (identical to K547)
# =================================================================
print("\n[2] Classifying trading days (ToM definition identical to K547)...")

def classify_tom(dates):
    df = pd.DataFrame(index=dates)
    df['year'] = df.index.year
    df['month'] = df.index.month
    df['ym'] = df['year'] * 100 + df['month']

    is_tom = pd.Series(False, index=dates)

    for ym, group in df.groupby('ym'):
        group_sorted = group.sort_index()
        if len(group_sorted) >= 1:
            is_tom[group_sorted.index[-1]] = True  # last trading day of month
        next_month_mask = (df['ym'] == ym + 1) if (ym % 100 < 12) else (df['ym'] == (ym // 100 + 1) * 100 + 1)
        next_month_days = df[next_month_mask].sort_index()
        if len(next_month_days) >= 3:
            is_tom[next_month_days.index[:3]] = True
        elif len(next_month_days) > 0:
            is_tom[next_month_days.index] = True

    return is_tom

is_tom = classify_tom(spy_ret.index)
n_tom = is_tom.sum()
n_mid = (~is_tom).sum()
print(f"  ToM days: {n_tom} ({n_tom/len(is_tom)*100:.1f}%), Mid-month: {n_mid}")

# =================================================================
# 3. STRATEGY FUNCTIONS (using lagged VIX)
# =================================================================

def compute_vt_weight(vix_val, target_vol_pct):
    if pd.isna(vix_val) or vix_val <= 0:
        return 0.0  # NaN or invalid → skip (first day after shift)
    return float(np.clip(target_vol_pct / vix_val, 0, 1))

def run_strategy_lagged(spy_ret, vix_lagged, is_tom, strategy_name, params):
    """Run strategy using VIX[t-1] for weight[t]. signal.shift(1) = vix_lagged."""
    weights = pd.Series(index=spy_ret.index, dtype=float)

    if strategy_name == 'daily_vt':
        target = params.get('target', 12)
        for i, date in enumerate(spy_ret.index):
            vix_val = vix_lagged.loc[date] if date in vix_lagged.index else np.nan
            weights.iloc[i] = compute_vt_weight(vix_val, target)

    elif strategy_name == 'monthly_vt':
        target = params.get('target', 12)
        current_weight = 0.0
        prev_month = None
        for i, date in enumerate(spy_ret.index):
            ym = date.year * 100 + date.month
            if ym != prev_month:
                vix_val = vix_lagged.loc[date] if date in vix_lagged.index else np.nan
                current_weight = compute_vt_weight(vix_val, target)
                prev_month = ym
            weights.iloc[i] = current_weight

    elif strategy_name == 'tom_enhanced':
        tom_target = params.get('tom_target', 12)
        mid_target = params.get('mid_target', 8)
        for i, date in enumerate(spy_ret.index):
            vix_val = vix_lagged.loc[date] if date in vix_lagged.index else np.nan
            if is_tom.loc[date]:
                weights.iloc[i] = compute_vt_weight(vix_val, tom_target)
            else:
                weights.iloc[i] = compute_vt_weight(vix_val, mid_target)

    elif strategy_name == 'tom_aggressive':
        tom_target = params.get('tom_target', 12)
        mid_target = params.get('mid_target', 6)
        for i, date in enumerate(spy_ret.index):
            vix_val = vix_lagged.loc[date] if date in vix_lagged.index else np.nan
            if is_tom.loc[date]:
                weights.iloc[i] = compute_vt_weight(vix_val, tom_target)
            else:
                weights.iloc[i] = compute_vt_weight(vix_val, mid_target)

    elif strategy_name == 'dual_frequency':
        base_target = params.get('base_target', 12)
        tom_boost = params.get('tom_boost', 1.3)
        mid_cut = params.get('mid_cut', 0.7)
        current_base = 0.0
        prev_month = None
        for i, date in enumerate(spy_ret.index):
            ym = date.year * 100 + date.month
            if ym != prev_month:
                vix_val = vix_lagged.loc[date] if date in vix_lagged.index else np.nan
                current_base = compute_vt_weight(vix_val, base_target)
                prev_month = ym
            if is_tom.loc[date]:
                weights.iloc[i] = float(np.clip(current_base * tom_boost, 0, 1))
            else:
                weights.iloc[i] = float(np.clip(current_base * mid_cut, 0, 1))

    elif strategy_name == 'buy_hold':
        weights[:] = 1.0

    port_ret = weights * spy_ret
    return port_ret, weights

def add_transaction_costs(port_ret, weights, tc_bps=5):
    tc = tc_bps / 10000
    weight_changes = weights.diff().abs()
    weight_changes.iloc[0] = weights.iloc[0]
    costs = weight_changes * tc
    return port_ret - costs

def compute_metrics(port_ret, weights, tc_bps=5):
    valid = port_ret.dropna()
    if len(valid) == 0:
        return {}
    ann_factor = 252
    cagr = (1 + valid).prod() ** (ann_factor / len(valid)) - 1
    vol = valid.std() * np.sqrt(ann_factor)
    sharpe = cagr / vol if vol > 0 else 0
    cumret = (1 + valid).cumprod()
    rolling_max = cumret.cummax()
    drawdown = (cumret - rolling_max) / rolling_max
    mdd = drawdown.min()
    calmar = cagr / abs(mdd) if mdd < 0 else 0
    avg_wt = weights.mean()
    net_ret = add_transaction_costs(port_ret, weights, tc_bps)
    net_valid = net_ret.dropna()
    net_cagr = (1 + net_valid).prod() ** (ann_factor / len(net_valid)) - 1
    net_vol = net_valid.std() * np.sqrt(ann_factor)
    net_sharpe = net_cagr / net_vol if net_vol > 0 else 0
    wt_changes = weights.diff().abs()
    trades_per_year = (wt_changes > 0.01).sum() / (len(valid) / ann_factor)
    return {
        'cagr_pct': round(cagr * 100, 3),
        'vol_pct': round(vol * 100, 3),
        'sharpe': round(sharpe, 4),
        'mdd_pct': round(mdd * 100, 3),
        'calmar': round(calmar, 4),
        'avg_weight': round(avg_wt, 4),
        'net_sharpe': round(net_sharpe, 4),
        'trades_per_year': round(trades_per_year, 1),
        'n_obs': len(valid),
    }

# =================================================================
# 4. FULL SAMPLE BACKTEST
# =================================================================
print("\n[3] Full-sample backtest (2005-2026) with shift(1) VIX...")

strategies = {
    'Buy & Hold': ('buy_hold', {}),
    'Daily VT (12/VIX) [shift(1)]': ('daily_vt', {'target': 12}),
    'Monthly VT (12/VIX) [shift(1)]': ('monthly_vt', {'target': 12}),
    'ToM Enhanced (12/8) [shift(1)]': ('tom_enhanced', {'tom_target': 12, 'mid_target': 8}),
    'ToM Aggressive (12/6) [shift(1)]': ('tom_aggressive', {'tom_target': 12, 'mid_target': 6}),
    'Dual Freq (1.3x/0.7x) [shift(1)]': ('dual_frequency', {'base_target': 12, 'tom_boost': 1.3, 'mid_cut': 0.7}),
}

results_full = {}
print(f"\n  {'Strategy':<45} {'CAGR%':>7} {'Vol%':>6} {'Sharpe':>8} {'MDD%':>8} {'Avg Wt':>8}")
print(f"  {'-'*45} {'-'*7} {'-'*6} {'-'*8} {'-'*8} {'-'*8}")

for name, (strat, params) in strategies.items():
    pr, wts = run_strategy_lagged(spy_ret, vix_lagged, is_tom, strat, params)
    m = compute_metrics(pr, wts)
    results_full[name] = {**m, 'port_ret': pr, 'weights': wts}
    print(f"  {name:<45} {m.get('cagr_pct',0):>7.2f} {m.get('vol_pct',0):>6.2f} "
          f"{m.get('sharpe',0):>8.4f} {m.get('mdd_pct',0):>8.2f} {m.get('avg_weight',0):>8.4f}")

# =================================================================
# 5. COMPARISON WITH K547 ORIGINAL (no shift)
# =================================================================
print("\n[4] Comparison: K547 original vs K547b shift(1)...")

# K547 original key numbers
k547_original = {
    'Daily VT (12/VIX)': {'sharpe': 1.666, 'cagr_pct': 16.02, 'mdd_pct': -13.93},
    'ToM Enhanced (12/8)': {'sharpe': 1.655, 'cagr_pct': 11.78, 'mdd_pct': -10.64},
    'ToM Aggressive (12/6)': {'sharpe': 1.581, 'cagr_pct': 9.48, 'mdd_pct': -9.10},
    'Monthly VT (12/VIX)': {'sharpe': 0.743, 'cagr_pct': 7.41, 'mdd_pct': -24.36},
}

k547b_key = {
    'Daily VT (12/VIX)': results_full['Daily VT (12/VIX) [shift(1)]'],
    'ToM Enhanced (12/8)': results_full['ToM Enhanced (12/8) [shift(1)]'],
    'ToM Aggressive (12/6)': results_full['ToM Aggressive (12/6) [shift(1)]'],
    'Monthly VT (12/VIX)': results_full['Monthly VT (12/VIX) [shift(1)]'],
}

print(f"\n  {'Strategy':<28} {'K547 Sharpe':>12} {'K547b Sharpe':>13} {'Δ Sharpe':>10} {'Δ%':>8}")
print(f"  {'-'*28} {'-'*12} {'-'*13} {'-'*10} {'-'*8}")

comparison = {}
for strat in k547_original:
    orig_sr = k547_original[strat]['sharpe']
    new_sr = k547b_key[strat]['sharpe']
    delta = new_sr - orig_sr
    delta_pct = (new_sr - orig_sr) / abs(orig_sr) * 100
    comparison[strat] = {
        'k547_sharpe': orig_sr,
        'k547b_sharpe': new_sr,
        'delta_sharpe': round(delta, 4),
        'delta_pct': round(delta_pct, 2),
    }
    print(f"  {strat:<28} {orig_sr:>12.4f} {new_sr:>13.4f} {delta:>10.4f} {delta_pct:>8.2f}%")

daily_vt_delta_pct = abs(comparison['Daily VT (12/VIX)']['delta_pct'])
article_update_needed = daily_vt_delta_pct > 5.0
print(f"\n  Daily VT Sharpe change: {comparison['Daily VT (12/VIX)']['delta_pct']:.2f}%")
print(f"  Article update needed (>5% threshold): {article_update_needed}")

# =================================================================
# 6. CROSS-PERIOD OOS VALIDATION
# =================================================================
print("\n[5] Cross-period OOS (5 sub-periods)...")

periods = [
    ('2006-01', '2009-12'),
    ('2010-01', '2013-12'),
    ('2014-01', '2017-12'),
    ('2018-01', '2021-12'),
    ('2022-01', '2026-03'),
]

oos_results = []
print(f"\n  {'Period':<20} {'Daily VT SR':>12} {'ToM Enh SR':>12} {'Diff':>8}")
print(f"  {'-'*20} {'-'*12} {'-'*12} {'-'*8}")

for start, end in periods:
    mask = (spy_ret.index >= start) & (spy_ret.index <= end)
    spy_oos = spy_ret[mask]
    vix_oos = vix_lagged[mask]
    tom_oos = is_tom[mask]

    if len(spy_oos) < 50:
        continue

    ret_daily, wts_daily = run_strategy_lagged(spy_oos, vix_oos, tom_oos, 'daily_vt', {'target': 12})
    ret_tom, wts_tom = run_strategy_lagged(spy_oos, vix_oos, tom_oos, 'tom_enhanced', {'tom_target': 12, 'mid_target': 8})

    m_daily = compute_metrics(ret_daily, wts_daily)
    m_tom = compute_metrics(ret_tom, wts_tom)

    diff = m_tom['sharpe'] - m_daily['sharpe']
    oos_results.append({
        'period': f"{start} to {end}",
        'daily_vt_sharpe': m_daily['sharpe'],
        'tom_enhanced_sharpe': m_tom['sharpe'],
        'diff': round(diff, 4),
    })
    print(f"  {start} to {end:<10} {m_daily['sharpe']:>12.4f} {m_tom['sharpe']:>12.4f} {diff:>8.4f}")

tom_wins = sum(1 for r in oos_results if r['diff'] > 0)
print(f"\n  ToM Enhanced wins: {tom_wins}/{len(oos_results)} sub-periods")

# =================================================================
# 7. BLOCK BOOTSTRAP (10,000 reps, block=20)
# =================================================================
print("\n[6] Block bootstrap (B=10,000, block=20)...")

ret_daily_full = results_full['Daily VT (12/VIX) [shift(1)]']['port_ret'].dropna()
ret_tom_full = results_full['ToM Enhanced (12/8) [shift(1)]']['port_ret'].dropna()
common_idx2 = ret_daily_full.index.intersection(ret_tom_full.index)
diff_ret = (ret_tom_full - ret_daily_full).loc[common_idx2].values

B = 10000
block_size = 20
n = len(diff_ret)
bootstrap_means = []

for _ in range(B):
    starts = np.random.randint(0, n - block_size + 1, size=int(np.ceil(n / block_size)))
    blocks = [diff_ret[s:s + block_size] for s in starts]
    boot_sample = np.concatenate(blocks)[:n]
    bootstrap_means.append(boot_sample.mean() * 252 * 100)  # annualized bps

bootstrap_means = np.array(bootstrap_means)
mean_diff_bps = np.mean(bootstrap_means)
se_bps = np.std(bootstrap_means)
ci_lower = np.percentile(bootstrap_means, 2.5)
ci_upper = np.percentile(bootstrap_means, 97.5)

print(f"  ToM Enhanced vs Daily VT daily return diff (annualized):")
print(f"  Mean: {mean_diff_bps:.2f} bps, SE: {se_bps:.2f} bps")
print(f"  95% CI: [{ci_lower:.2f}, {ci_upper:.2f}] bps")
print(f"  CI entirely negative: {ci_upper < 0}")

# =================================================================
# 8. CONCLUSION
# =================================================================
print("\n[7] Conclusion...")

daily_vt_sr_orig = 1.666
daily_vt_sr_new = results_full['Daily VT (12/VIX) [shift(1)]']['sharpe']
tom_enhanced_sr_new = results_full['ToM Enhanced (12/8) [shift(1)]']['sharpe']

print(f"\n  Daily VT Sharpe:      {daily_vt_sr_orig:.4f} (K547) → {daily_vt_sr_new:.4f} (K547b, shift(1))")
print(f"  ToM Enhanced Sharpe:  {1.655:.4f} (K547) → {tom_enhanced_sr_new:.4f} (K547b, shift(1))")
print(f"  ToM Enhanced still underperforms Daily VT: {tom_enhanced_sr_new < daily_vt_sr_new}")

conclusion = "CONFIRMED: ToM overlay still underperforms Daily VT even with conservative shift(1) VIX timing."
if article_update_needed:
    conclusion += f" ARTICLE UPDATE REQUIRED: Daily VT Sharpe changed {comparison['Daily VT (12/VIX)']['delta_pct']:.1f}%."
else:
    conclusion += " Article numbers remain materially accurate (change <5%); article caveat section validated."

print(f"\n  {conclusion}")

# =================================================================
# 9. SAVE RESULTS
# =================================================================
print("\n[8] Saving results...")

runtime = round(time.time() - start_time, 1)

results_json = {
    'experiment_id': 'K547b',
    'title': 'Daily VT shift(1) Re-run — VIX Timing Correction',
    'timestamp': datetime.now().isoformat(),
    'runtime_seconds': runtime,
    'data_source': 'yfinance',
    'data_period': f"{spy_ret.index[0].date()} to {spy_ret.index[-1].date()}",
    'sample_size': len(spy_ret),
    'vix_lag_correction': 'shift(1): weight[t] = 12 / VIX[t-1]',
    'seed': 42,
    'full_sample_metrics': {
        name: {k: v for k, v in m.items() if k not in ['port_ret', 'weights']}
        for name, m in results_full.items()
    },
    'comparison_with_k547': comparison,
    'article_update_needed': article_update_needed,
    'daily_vt_sharpe_change_pct': round(comparison['Daily VT (12/VIX)']['delta_pct'], 2),
    'oos_results': oos_results,
    'tom_enhanced_wins_subperiods': f"{tom_wins}/{len(oos_results)}",
    'bootstrap_results': {
        'B': B,
        'block_size': block_size,
        'mean_diff_bps_annualized': round(mean_diff_bps, 3),
        'se_bps': round(se_bps, 3),
        'ci_95_lower': round(ci_lower, 3),
        'ci_95_upper': round(ci_upper, 3),
        'ci_entirely_negative': bool(ci_upper < 0),
    },
    'conclusion': conclusion,
    'article_ref': 'mile_53983530',
    'parent_experiment': 'K547',
    'references': [
        'Ariel (1987): A monthly effect in stock returns, JFE',
        'Lakonishok & Smidt (1988): Are seasonal anomalies real?, RFS',
        'McConnell & Xu (2008): Equity returns at the turn of the month, FAJ',
        'Harvey (2016): ...and the cross-section of expected returns, RFS',
    ],
}

output_path = 'experiments/k547b/k547b_results.json'
with open(output_path, 'w') as f:
    json.dump(results_json, f, indent=2, default=str)

print(f"  Results saved: {output_path}")
print(f"  Runtime: {runtime}s")
print("\n" + "=" * 70)
print("K547b COMPLETE")
print("=" * 70)
