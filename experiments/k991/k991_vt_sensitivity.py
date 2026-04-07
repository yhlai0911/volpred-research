"""
K991: Taiwan VT Strategy Sensitivity Analysis — k/VIX Parameter Stability
=========================================================================
Tests the robustness of the k parameter in the Taiwan VT strategy w = k/VIX.
Baseline k = 8.63 (target ~15% annualized volatility).

Data sources: yfinance (0050.TW, ^VIX)
Period: 2006-01-01 to 2026-04-07
"""

import json
import warnings
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings('ignore')
np.random.seed(42)

# === Output directory ===
OUT_DIR = Path(__file__).parent
OUT_DIR.mkdir(exist_ok=True)

# === Inline clean_tw50_data (worktree isolation) ===
def clean_tw50_data(prices, returns=None):
    """Fix 0050.TW stock split artifacts."""
    clean_prices = prices.copy()
    split_date = pd.Timestamp("2014-01-02")
    if split_date in clean_prices.index:
        pre_mask = clean_prices.index < split_date
        if pre_mask.any():
            last_pre = clean_prices[pre_mask].iloc[-1]
            first_post = clean_prices.loc[split_date]
            ratio = last_pre / first_post
            if 3.5 < ratio < 4.5:
                clean_prices[pre_mask] = clean_prices[pre_mask] / 4.0
                print(f"  [clean_tw50_data] Fixed split: ratio={ratio:.2f}, divided pre-2014 prices by 4")
    clean_returns = clean_prices.pct_change()
    # Remove extreme returns (> 50%) as artifacts
    extreme_mask = clean_returns.abs() > 0.50
    if extreme_mask.any():
        n_extreme = extreme_mask.sum()
        print(f"  [clean_tw50_data] Removed {n_extreme} extreme returns (>50%)")
        clean_returns[extreme_mask] = 0.0
        base = clean_prices.iloc[0]
        cum = (1 + clean_returns.fillna(0)).cumprod()
        clean_prices = base * cum
    clean_returns = clean_prices.pct_change()
    return clean_prices, clean_returns


# === Download Data ===
print("Downloading 0050.TW...")
tw50_raw = yf.download('0050.TW', start='2006-01-01', end='2026-04-07', progress=False)
print(f"  Raw 0050.TW: {len(tw50_raw)} rows, {tw50_raw.index[0].date()} to {tw50_raw.index[-1].date()}")

print("Downloading ^VIX...")
vix_raw = yf.download('^VIX', start='2006-01-01', end='2026-04-07', progress=False)
print(f"  Raw VIX: {len(vix_raw)} rows")

# === Clean 0050.TW ===
# Handle multi-level columns from yfinance
if isinstance(tw50_raw.columns, pd.MultiIndex):
    tw50_close = tw50_raw['Close'].squeeze()
else:
    tw50_close = tw50_raw['Close']

tw50_prices, tw50_returns = clean_tw50_data(tw50_close)
print(f"  Clean 0050.TW: {len(tw50_prices)} rows")

# === VIX ===
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_close = vix_raw['Close'].squeeze()
else:
    vix_close = vix_raw['Close']

# VIX must use previous day's value for Taiwan (lag)
vix_prev = vix_close.shift(1)

# === Align dates ===
# Taiwan and US have different trading days. Forward-fill VIX to cover TW trading days.
common_idx = tw50_returns.dropna().index
vix_aligned = vix_prev.reindex(common_idx, method='ffill')

# Drop rows where VIX is still NaN
valid_mask = vix_aligned.notna() & tw50_returns.notna()
dates = common_idx[valid_mask[common_idx]]
tw_ret = tw50_returns.loc[dates]
vix_vals = vix_aligned.loc[dates]

print(f"\nAligned data: {len(dates)} trading days, {dates[0].date()} to {dates[-1].date()}")
print(f"VIX range: {vix_vals.min():.1f} - {vix_vals.max():.1f}, mean={vix_vals.mean():.1f}")

# === Parameter Grid ===
K_VALUES = [5, 6, 7, 8, 8.63, 9, 10, 11, 12, 14, 16]
BASELINE_K = 8.63
TX_COST = 0.00585  # Taiwan round-trip cost
WEIGHT_CHANGE_THRESHOLD = 0.10  # Only charge cost when weight changes > 10%
WEIGHT_MIN = 0.2
WEIGHT_MAX = 1.5

# === Periods ===
FULL_START = dates[0]
FULL_END = dates[-1]
OOS_START = pd.Timestamp('2019-01-01')

periods = {
    'full': (FULL_START, FULL_END),
    'oos': (OOS_START, FULL_END),
}


def compute_strategy_metrics(returns_series, ann_factor=252):
    """Compute strategy performance metrics."""
    r = returns_series.dropna()
    if len(r) < 10:
        return {}

    ann_ret = r.mean() * ann_factor
    ann_vol = r.std() * np.sqrt(ann_factor)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    downside = r[r < 0].std() * np.sqrt(ann_factor) if (r < 0).any() else ann_vol
    sortino = ann_ret / downside if downside > 0 else 0

    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    return {
        'ann_return': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 4),
        'sortino': round(float(sortino), 4),
        'mdd': round(float(mdd), 4),
        'calmar': round(float(calmar), 4),
        'n_days': int(len(r)),
    }


def run_strategy(k, tw_ret, vix_vals, dates):
    """Run k/VIX strategy with transaction costs."""
    # Compute raw weight
    w_raw = k / vix_vals
    w_clipped = w_raw.clip(WEIGHT_MIN, WEIGHT_MAX)

    # Lag the weight: use yesterday's signal to trade today
    w_signal = w_clipped.shift(1)

    # Transaction costs: charge when weight changes > threshold
    w_change = w_signal.diff().abs()
    cost_mask = w_change > WEIGHT_CHANGE_THRESHOLD
    tx_costs = pd.Series(0.0, index=dates)
    tx_costs[cost_mask] = TX_COST * w_change[cost_mask]

    # Portfolio return
    port_ret = w_signal * tw_ret - tx_costs
    port_ret = port_ret.dropna()

    # Turnover (annualized)
    daily_turnover = w_change.dropna().mean()
    ann_turnover = daily_turnover * 252

    return port_ret, float(ann_turnover)


# === Run all k values ===
print("\n" + "="*70)
print("Running sensitivity analysis...")
print("="*70)

results = {}

for k in K_VALUES:
    port_ret, turnover = run_strategy(k, tw_ret, vix_vals, dates)

    k_results = {'k': k, 'turnover': round(turnover, 4)}

    for period_name, (p_start, p_end) in periods.items():
        mask = (port_ret.index >= p_start) & (port_ret.index <= p_end)
        period_ret = port_ret[mask]
        metrics = compute_strategy_metrics(period_ret)
        k_results[period_name] = metrics

    # Annual breakdown (2006-2025, plus partial 2026)
    annual = {}
    for year in range(2006, 2027):
        year_mask = port_ret.index.year == year
        if year_mask.sum() > 20:
            year_ret = port_ret[year_mask]
            m = compute_strategy_metrics(year_ret)
            annual[str(year)] = m
    k_results['annual'] = annual

    results[str(k)] = k_results

    full_m = k_results['full']
    oos_m = k_results['oos']
    print(f"  k={k:5.2f} | Full: Sharpe={full_m['sharpe']:6.3f}, MDD={full_m['mdd']:7.3f} | "
          f"OOS: Sharpe={oos_m['sharpe']:6.3f}, MDD={oos_m['mdd']:7.3f} | Turnover={turnover:.2f}")


# === Buy-and-Hold Baseline ===
print("\nBuy-and-Hold baseline:")
for period_name, (p_start, p_end) in periods.items():
    mask = (tw_ret.index >= p_start) & (tw_ret.index <= p_end)
    bh_ret = tw_ret[mask].dropna()
    bh_m = compute_strategy_metrics(bh_ret)
    results[f'bh_{period_name}'] = bh_m
    print(f"  {period_name}: Sharpe={bh_m['sharpe']:.3f}, MDD={bh_m['mdd']:.3f}")


# === Sensitivity Analysis ===
print("\n" + "="*70)
print("Sensitivity Analysis: k=8.63 +/- 20%")
print("="*70)

baseline_sharpe_full = results[str(BASELINE_K)]['full']['sharpe']
baseline_sharpe_oos = results[str(BASELINE_K)]['oos']['sharpe']

sensitivity = {
    'baseline_k': BASELINE_K,
    'baseline_sharpe_full': baseline_sharpe_full,
    'baseline_sharpe_oos': baseline_sharpe_oos,
    'k_range_20pct': [round(BASELINE_K * 0.8, 2), round(BASELINE_K * 1.2, 2)],
}

# Find k values within +/- 20%
k_low = BASELINE_K * 0.8   # 6.90
k_high = BASELINE_K * 1.2  # 10.36

print(f"\nBaseline k={BASELINE_K}: Sharpe(full)={baseline_sharpe_full:.4f}, Sharpe(OOS)={baseline_sharpe_oos:.4f}")
print(f"20% range: [{k_low:.2f}, {k_high:.2f}]")

within_range = {}
for k in K_VALUES:
    if k_low <= k <= k_high:
        full_s = results[str(k)]['full']['sharpe']
        oos_s = results[str(k)]['oos']['sharpe']
        full_drop = (baseline_sharpe_full - full_s) / abs(baseline_sharpe_full) * 100 if baseline_sharpe_full != 0 else 0
        oos_drop = (baseline_sharpe_oos - oos_s) / abs(baseline_sharpe_oos) * 100 if baseline_sharpe_oos != 0 else 0
        within_range[str(k)] = {
            'sharpe_full': full_s,
            'sharpe_oos': oos_s,
            'sharpe_drop_full_pct': round(full_drop, 2),
            'sharpe_drop_oos_pct': round(oos_drop, 2),
        }
        print(f"  k={k:5.2f}: Sharpe(full)={full_s:.4f} ({full_drop:+.1f}%), Sharpe(OOS)={oos_s:.4f} ({oos_drop:+.1f}%)")

sensitivity['within_20pct_range'] = within_range

# Check pass/fail for listing criterion #4
max_drop_full = max(abs(v['sharpe_drop_full_pct']) for v in within_range.values())
max_drop_oos = max(abs(v['sharpe_drop_oos_pct']) for v in within_range.values())
pass_criterion = max_drop_full < 30 and max_drop_oos < 30

sensitivity['max_drop_full_pct'] = round(max_drop_full, 2)
sensitivity['max_drop_oos_pct'] = round(max_drop_oos, 2)
sensitivity['pass_listing_criterion_4'] = pass_criterion
print(f"\nMax Sharpe drop (full): {max_drop_full:.1f}%")
print(f"Max Sharpe drop (OOS): {max_drop_oos:.1f}%")
print(f"Listing criterion #4 (drop < 30%): {'PASS' if pass_criterion else 'FAIL'}")


# === Find Optimal k ===
optimal_k_full = max(K_VALUES, key=lambda k: results[str(k)]['full']['sharpe'])
optimal_k_oos = max(K_VALUES, key=lambda k: results[str(k)]['oos']['sharpe'])

sensitivity['optimal_k_full'] = optimal_k_full
sensitivity['optimal_k_oos'] = optimal_k_oos
print(f"\nOptimal k (full sample): {optimal_k_full}")
print(f"Optimal k (OOS 2019+): {optimal_k_oos}")


# === Finer Grid around baseline ===
print("\n" + "="*70)
print("Fine grid: k = 6.0 to 12.0, step 0.5")
print("="*70)

fine_k = np.arange(6.0, 12.5, 0.5)
fine_results = {}

for k in fine_k:
    port_ret, turnover = run_strategy(k, tw_ret, vix_vals, dates)

    for period_name, (p_start, p_end) in periods.items():
        mask = (port_ret.index >= p_start) & (port_ret.index <= p_end)
        period_ret = port_ret[mask]
        m = compute_strategy_metrics(period_ret)
        if period_name not in fine_results:
            fine_results[period_name] = {'k': [], 'sharpe': [], 'mdd': [], 'ann_return': [], 'sortino': []}
        fine_results[period_name]['k'].append(float(k))
        fine_results[period_name]['sharpe'].append(m['sharpe'])
        fine_results[period_name]['mdd'].append(m['mdd'])
        fine_results[period_name]['ann_return'].append(m['ann_return'])
        fine_results[period_name]['sortino'].append(m['sortino'])

fine_optimal_full = fine_results['full']['k'][np.argmax(fine_results['full']['sharpe'])]
fine_optimal_oos = fine_results['oos']['k'][np.argmax(fine_results['oos']['sharpe'])]
print(f"Fine grid optimal k (full): {fine_optimal_full}")
print(f"Fine grid optimal k (OOS): {fine_optimal_oos}")

sensitivity['fine_grid_optimal_full'] = fine_optimal_full
sensitivity['fine_grid_optimal_oos'] = fine_optimal_oos


# === SPY Comparison (12/VIX baseline) ===
print("\n" + "="*70)
print("SPY 12/VIX comparison")
print("="*70)

spy_raw = yf.download('SPY', start='2006-01-01', end='2026-04-07', progress=False)
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_close = spy_raw['Close'].squeeze()
else:
    spy_close = spy_raw['Close']
spy_ret = spy_close.pct_change()

# For SPY, VIX is same-day (no lag needed — same market)
vix_for_spy = vix_close.shift(1)  # Still use prev-day VIX for signal
spy_dates = spy_ret.dropna().index
vix_spy_aligned = vix_for_spy.reindex(spy_dates, method='ffill')
valid_spy = vix_spy_aligned.notna() & spy_ret.notna()
spy_dates_clean = spy_dates[valid_spy[spy_dates]]
spy_ret_clean = spy_ret.loc[spy_dates_clean]
vix_spy_clean = vix_spy_aligned.loc[spy_dates_clean]

spy_comparison = {}
for k in [8.63, 10, 12, 14]:
    w = (k / vix_spy_clean).clip(0.2, 1.5).shift(1)
    port = (w * spy_ret_clean).dropna()

    for period_name, (p_start, p_end) in periods.items():
        mask = (port.index >= p_start) & (port.index <= p_end)
        m = compute_strategy_metrics(port[mask])
        spy_comparison[f'spy_k{k}_{period_name}'] = m
        if period_name == 'oos':
            print(f"  SPY k={k:5.2f} OOS: Sharpe={m['sharpe']:.3f}, MDD={m['mdd']:.3f}")


# ============================================================
# PLOTS
# ============================================================
print("\nGenerating plots...")

# --- Plot 1: Sharpe & MDD vs k ---
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

k_list = K_VALUES
sharpe_full = [results[str(k)]['full']['sharpe'] for k in k_list]
sharpe_oos = [results[str(k)]['oos']['sharpe'] for k in k_list]
mdd_full = [results[str(k)]['full']['mdd'] for k in k_list]
mdd_oos = [results[str(k)]['oos']['mdd'] for k in k_list]

# Sharpe
ax = axes[0]
ax.plot(k_list, sharpe_full, 'b-o', label='Full Sample', markersize=6)
ax.plot(k_list, sharpe_oos, 'r-s', label='OOS (2019+)', markersize=6)
ax.axvline(BASELINE_K, color='green', linestyle='--', alpha=0.7, label=f'Baseline k={BASELINE_K}')
ax.axvspan(k_low, k_high, alpha=0.1, color='green', label='+-20% range')
ax.set_xlabel('k parameter', fontsize=12)
ax.set_ylabel('Sharpe Ratio', fontsize=12)
ax.set_title('Sharpe Ratio vs k', fontsize=14)
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3)

# MDD
ax = axes[1]
ax.plot(k_list, mdd_full, 'b-o', label='Full Sample', markersize=6)
ax.plot(k_list, mdd_oos, 'r-s', label='OOS (2019+)', markersize=6)
ax.axvline(BASELINE_K, color='green', linestyle='--', alpha=0.7, label=f'Baseline k={BASELINE_K}')
ax.axvspan(k_low, k_high, alpha=0.1, color='green', label='+-20% range')
ax.set_xlabel('k parameter', fontsize=12)
ax.set_ylabel('Max Drawdown', fontsize=12)
ax.set_title('Max Drawdown vs k', fontsize=14)
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3)

plt.suptitle('K991: Taiwan VT (k/VIX) Sensitivity Analysis', fontsize=15, fontweight='bold')
plt.tight_layout()
plt.savefig(OUT_DIR / 'k991_sharpe_vs_k.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k991_sharpe_vs_k.png")

# --- Plot 2: Fine grid Sharpe curve ---
fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(fine_results['full']['k'], fine_results['full']['sharpe'], 'b-o', label='Full Sample', markersize=4)
ax.plot(fine_results['oos']['k'], fine_results['oos']['sharpe'], 'r-s', label='OOS (2019+)', markersize=4)
ax.axvline(BASELINE_K, color='green', linestyle='--', alpha=0.7, label=f'Baseline k={BASELINE_K}')
ax.axvspan(k_low, k_high, alpha=0.1, color='green')
ax.set_xlabel('k parameter', fontsize=12)
ax.set_ylabel('Sharpe Ratio', fontsize=12)
ax.set_title('Fine Grid: Sharpe Ratio vs k (step=0.5)', fontsize=14)
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(OUT_DIR / 'k991_fine_grid_sharpe.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k991_fine_grid_sharpe.png")

# --- Plot 3: Annual Sharpe heatmap ---
years_to_show = list(range(2008, 2026))
k_for_heatmap = [5, 7, 8, 8.63, 9, 10, 12, 14, 16]

heatmap_data = []
for k in k_for_heatmap:
    row = []
    for y in years_to_show:
        ann = results[str(k)].get('annual', {}).get(str(y), {})
        row.append(ann.get('sharpe', np.nan))
    heatmap_data.append(row)

heatmap_arr = np.array(heatmap_data)

fig, ax = plt.subplots(figsize=(16, 6))
im = ax.imshow(heatmap_arr, cmap='RdYlGn', aspect='auto', vmin=-1.5, vmax=2.0)
ax.set_xticks(range(len(years_to_show)))
ax.set_xticklabels(years_to_show, rotation=45)
ax.set_yticks(range(len(k_for_heatmap)))
ax.set_yticklabels([f'k={k}' for k in k_for_heatmap])

# Add text annotations
for i in range(len(k_for_heatmap)):
    for j in range(len(years_to_show)):
        val = heatmap_arr[i, j]
        if not np.isnan(val):
            color = 'white' if abs(val) > 1.0 else 'black'
            ax.text(j, i, f'{val:.2f}', ha='center', va='center', fontsize=7, color=color)

plt.colorbar(im, label='Sharpe Ratio')
ax.set_title('K991: Annual Sharpe Ratio by k Parameter (0050.TW VT)', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig(OUT_DIR / 'k991_annual_comparison.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k991_annual_comparison.png")


# === Save Results JSON ===
output = {
    'experiment_id': 'K991',
    'title': 'Taiwan VT Sensitivity Analysis: k/VIX Parameter Stability',
    'data_source': 'yfinance (0050.TW, ^VIX, SPY)',
    'period': f'{FULL_START.date()} to {FULL_END.date()}',
    'oos_period': f'{OOS_START.date()} to {FULL_END.date()}',
    'n_trading_days': int(len(dates)),
    'method': 'k/VIX weight with clip [0.2, 1.5], shift(1) lag, TX cost 0.585%',
    'parameters': {
        'k_values': K_VALUES,
        'baseline_k': BASELINE_K,
        'weight_clip': [WEIGHT_MIN, WEIGHT_MAX],
        'tx_cost': TX_COST,
        'weight_change_threshold': WEIGHT_CHANGE_THRESHOLD,
    },
    'strategy_results': results,
    'sensitivity_analysis': sensitivity,
    'fine_grid': {
        period: {
            'k': fine_results[period]['k'],
            'sharpe': fine_results[period]['sharpe'],
            'mdd': fine_results[period]['mdd'],
        }
        for period in fine_results
    },
    'spy_comparison': spy_comparison,
    'conclusion': '',  # Will fill below
}

# Generate conclusion
if pass_criterion:
    conclusion = (
        f"PASS: Taiwan VT strategy with k={BASELINE_K} passes listing criterion #4. "
        f"Within +-20% range ({k_low:.2f}-{k_high:.2f}), max Sharpe drop is "
        f"{max_drop_full:.1f}% (full) / {max_drop_oos:.1f}% (OOS), both < 30%. "
        f"Optimal k (full)={optimal_k_full}, optimal k (OOS)={optimal_k_oos}. "
        f"Fine grid optimal: full={fine_optimal_full}, OOS={fine_optimal_oos}. "
        f"The parameter is robust across a wide range."
    )
else:
    conclusion = (
        f"FAIL: Taiwan VT strategy with k={BASELINE_K} does NOT pass listing criterion #4. "
        f"Max Sharpe drop within +-20%: {max_drop_full:.1f}% (full) / {max_drop_oos:.1f}% (OOS). "
        f"At least one exceeds the 30% threshold."
    )

output['conclusion'] = conclusion
print(f"\n{'='*70}")
print(f"CONCLUSION: {conclusion}")
print(f"{'='*70}")

with open(OUT_DIR / 'k991_vt_sensitivity_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to {OUT_DIR / 'k991_vt_sensitivity_results.json'}")

print("\nDone!")
