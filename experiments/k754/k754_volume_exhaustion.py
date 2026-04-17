"""
K754: Volume Exhaustion Effect — Does Extreme Volume Predict Lower Future VIX?
==============================================================================
[提出: Claude (from K753 finding), 執行: Claude]

Background:
K753 found that extreme volume days (>2x 20-day average) have the LOWEST subsequent
VIX spike probability (12.6% vs 21% unconditional). This "volume exhaustion" effect
suggests that after extreme trading, uncertainty is RESOLVED.

Academic basis:
- Lamoureux & Lastrapes (1990) "Heteroskedasticity in Stock Return Data" JoF
- Gallant, Rossi & Tauchen (1992) "Stock Prices and Volume" RFS
- Foster & Viswanathan (1990) "A Theory of Interday Volume" RFS — informed traders
  exhaust their information edge through trading
- K753: extreme volume days have p(spike)=12.6% vs unconditional 21%

Hypothesis: After extreme volume, uncertainty is RESOLVED → lower future volatility.

Data source: yfinance SPY/^VIX 2006-2026
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

print("=" * 70)
print("K754: Volume Exhaustion Effect")
print("=" * 70)

# ─────────────────────────────────────────────────
# Data Collection
# ─────────────────────────────────────────────────
print("\n[1] Downloading data...")
spy = yf.download("SPY", start="2005-01-01", end="2026-03-30", progress=False)
vix = yf.download("^VIX", start="2005-01-01", end="2026-03-30", progress=False)

# Handle multi-level columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Align
df = pd.DataFrame(index=spy.index)
df['close'] = spy['Close']
df['volume'] = spy['Volume']
df['vix'] = vix['Close'].reindex(spy.index, method='ffill')
df = df.dropna()

# Returns
df['ret'] = df['close'].pct_change()
df['abs_ret'] = df['ret'].abs()

# Realized vol (forward-looking for analysis, NOT for trading signals)
df['fwd_rv1'] = df['ret'].shift(-1).abs() * np.sqrt(252)  # next-day annualized |return|
df['fwd_rv5'] = df['ret'].shift(-1).rolling(5).apply(
    lambda x: x.std() * np.sqrt(252) if len(x) == 5 else np.nan
)  # shift(-1) then rolling(5) = days t+1 to t+5
# Correct forward 5d RV: use future 5 days
fwd_rets = pd.DataFrame()
for i in range(1, 6):
    fwd_rets[f'r{i}'] = df['ret'].shift(-i)
df['fwd_rv5'] = fwd_rets.std(axis=1) * np.sqrt(252)

# Forward 22d RV
fwd_rets22 = pd.DataFrame()
for i in range(1, 23):
    fwd_rets22[f'r{i}'] = df['ret'].shift(-i)
df['fwd_rv22'] = fwd_rets22.std(axis=1) * np.sqrt(252)

# VIX change
df['vix_chg_1d'] = df['vix'].shift(-1) - df['vix']  # next-day VIX change
df['vix_chg_5d'] = df['vix'].shift(-5) - df['vix']  # 5-day VIX change

# Volume metrics (backward-looking — safe for signals)
df['vol_ma20'] = df['volume'].rolling(20).mean()
df['abn_vol'] = df['volume'] / df['vol_ma20']
df['vol_zscore'] = (df['volume'] - df['vol_ma20']) / df['volume'].rolling(20).std()

# Direction on extreme volume day
df['is_up'] = (df['ret'] > 0).astype(int)

# Drop warmup
df = df.loc['2006-01-01':].copy()
# Drop rows where forward RV can't be computed
analysis_df = df.dropna(subset=['fwd_rv5', 'fwd_rv22', 'vix_chg_1d', 'vix_chg_5d']).copy()

print(f"Sample: {analysis_df.index[0].strftime('%Y-%m-%d')} to {analysis_df.index[-1].strftime('%Y-%m-%d')}, N={len(analysis_df)}")

results = {
    'experiment_id': 'K754',
    'title': 'Volume Exhaustion Effect — Does Extreme Volume Predict Lower Future VIX?',
    'data_source': 'yfinance SPY/^VIX',
    'sample_period': f"{analysis_df.index[0].strftime('%Y-%m-%d')} to {analysis_df.index[-1].strftime('%Y-%m-%d')}",
    'n_obs': len(analysis_df),
    'references': [
        'Lamoureux & Lastrapes (1990) JoF',
        'Gallant, Rossi & Tauchen (1992) RFS',
        'Foster & Viswanathan (1990) RFS',
        'K753: extreme volume p(spike)=12.6% vs 21% unconditional'
    ]
}

# ═══════════════════════════════════════════════════
# Part A: Volume Exhaustion Characterization
# ═══════════════════════════════════════════════════
print("\n" + "=" * 70)
print("Part A: Volume Exhaustion Characterization")
print("=" * 70)

# Define extreme volume: >2x 20-day average
extreme_mask = analysis_df['abn_vol'] > 2.0
extreme_days = analysis_df[extreme_mask]
n_extreme = len(extreme_days)
n_total = len(analysis_df)
pct_extreme = n_extreme / n_total * 100

print(f"\nExtreme volume days (abn_vol > 2.0): {n_extreme} ({pct_extreme:.1f}%)")
print(f"Total trading days: {n_total}")

# Frequency per year
yearly_counts = extreme_days.groupby(extreme_days.index.year).size()
print(f"\nExtreme volume days per year:")
for yr, cnt in yearly_counts.items():
    print(f"  {yr}: {cnt}")
avg_per_year = yearly_counts.mean()
print(f"  Average: {avg_per_year:.1f}/year")

# Clustering: how often do extreme days cluster?
if n_extreme > 1:
    extreme_idx = analysis_df.index.get_indexer(extreme_days.index)
    gaps = np.diff(extreme_idx)
    pct_next_day = (gaps == 1).sum() / len(gaps) * 100
    median_gap = np.median(gaps)
    print(f"\nClustering: {pct_next_day:.1f}% of extreme days are followed by another extreme day")
    print(f"Median gap between extreme days: {median_gap:.0f} trading days")

# What market conditions cause extreme volume?
extreme_stats = {
    'mean_abs_ret': float(extreme_days['abs_ret'].mean()),
    'mean_ret': float(extreme_days['ret'].mean()),
    'pct_down': float((extreme_days['ret'] < 0).mean() * 100),
    'mean_vix': float(extreme_days['vix'].mean()),
    'median_vix': float(extreme_days['vix'].median()),
}
normal_stats = {
    'mean_abs_ret': float(analysis_df[~extreme_mask]['abs_ret'].mean()),
    'mean_ret': float(analysis_df[~extreme_mask]['ret'].mean()),
    'pct_down': float((analysis_df[~extreme_mask]['ret'] < 0).mean() * 100),
    'mean_vix': float(analysis_df[~extreme_mask]['vix'].mean()),
    'median_vix': float(analysis_df[~extreme_mask]['vix'].median()),
}

print(f"\nExtreme vol days vs Normal days:")
print(f"  Mean |return|:  {extreme_stats['mean_abs_ret']*100:.3f}% vs {normal_stats['mean_abs_ret']*100:.3f}%")
print(f"  Mean return:    {extreme_stats['mean_ret']*100:.3f}% vs {normal_stats['mean_ret']*100:.3f}%")
print(f"  % down days:    {extreme_stats['pct_down']:.1f}% vs {normal_stats['pct_down']:.1f}%")
print(f"  Mean VIX:       {extreme_stats['mean_vix']:.1f} vs {normal_stats['mean_vix']:.1f}")

# Direction breakdown
n_extreme_up = (extreme_days['ret'] > 0).sum()
n_extreme_down = (extreme_days['ret'] <= 0).sum()
print(f"\nExtreme volume by direction: {n_extreme_up} up days, {n_extreme_down} down days")

# Granular thresholds
thresholds = [1.5, 2.0, 2.5, 3.0, 4.0]
threshold_counts = {}
for t in thresholds:
    mask_t = analysis_df['abn_vol'] > t
    threshold_counts[str(t)] = int(mask_t.sum())
    print(f"  abn_vol > {t}x: {mask_t.sum()} days ({mask_t.sum()/n_total*100:.1f}%)")

results['part_a'] = {
    'n_extreme_days': n_extreme,
    'pct_extreme': round(pct_extreme, 2),
    'avg_per_year': round(avg_per_year, 1),
    'pct_next_day_cluster': round(pct_next_day, 1),
    'median_gap_days': float(median_gap),
    'extreme_stats': extreme_stats,
    'normal_stats': normal_stats,
    'n_extreme_up': int(n_extreme_up),
    'n_extreme_down': int(n_extreme_down),
    'yearly_counts': {str(k): int(v) for k, v in yearly_counts.items()},
    'threshold_counts': threshold_counts,
}

# ═══════════════════════════════════════════════════
# Part B: Forward Vol Prediction after Extreme Volume
# ═══════════════════════════════════════════════════
print("\n" + "=" * 70)
print("Part B: Forward Volatility after Extreme Volume")
print("=" * 70)

# Compare forward RV after extreme vs normal volume days
def compare_groups(extreme, normal, metric_name):
    """T-test + Cohen's d for two groups."""
    t_stat, p_val = stats.ttest_ind(extreme, normal, equal_var=False)
    d = (extreme.mean() - normal.mean()) / np.sqrt((extreme.std()**2 + normal.std()**2) / 2)
    return {
        'extreme_mean': float(extreme.mean()),
        'extreme_median': float(extreme.median()),
        'normal_mean': float(normal.mean()),
        'normal_median': float(normal.median()),
        'diff': float(extreme.mean() - normal.mean()),
        'diff_pct': float((extreme.mean() - normal.mean()) / normal.mean() * 100),
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'cohens_d': float(d),
        'n_extreme': int(len(extreme)),
        'n_normal': int(len(normal)),
    }

extreme_df = analysis_df[extreme_mask].copy()
normal_df = analysis_df[~extreme_mask].copy()

# Forward realized vol: 1d, 5d, 22d
fwd_rv_results = {}
for metric, label in [('fwd_rv1', '1-day'), ('fwd_rv5', '5-day'), ('fwd_rv22', '22-day')]:
    comp = compare_groups(extreme_df[metric].dropna(), normal_df[metric].dropna(), label)
    fwd_rv_results[metric] = comp
    print(f"\n{label} forward RV:")
    print(f"  After extreme vol: {comp['extreme_mean']:.4f} (median {comp['extreme_median']:.4f})")
    print(f"  After normal vol:  {comp['normal_mean']:.4f} (median {comp['normal_median']:.4f})")
    print(f"  Difference: {comp['diff']:+.4f} ({comp['diff_pct']:+.1f}%)")
    print(f"  t-stat: {comp['t_stat']:.3f}, p-value: {comp['p_value']:.4f}, Cohen's d: {comp['cohens_d']:.3f}")

# VIX change after extreme volume
vix_chg_results = {}
for metric, label in [('vix_chg_1d', '1-day VIX change'), ('vix_chg_5d', '5-day VIX change')]:
    comp = compare_groups(extreme_df[metric].dropna(), normal_df[metric].dropna(), label)
    vix_chg_results[metric] = comp
    print(f"\n{label}:")
    print(f"  After extreme vol: {comp['extreme_mean']:+.3f}")
    print(f"  After normal vol:  {comp['normal_mean']:+.3f}")
    print(f"  Difference: {comp['diff']:+.3f}")
    print(f"  t-stat: {comp['t_stat']:.3f}, p-value: {comp['p_value']:.4f}")

# ─── B.2: Conditional on direction ───
print("\n--- Conditional on direction ---")
extreme_up = extreme_df[extreme_df['ret'] > 0]
extreme_down = extreme_df[extreme_df['ret'] <= 0]

direction_results = {}
for direction_label, sub_df in [('extreme_up', extreme_up), ('extreme_down', extreme_down)]:
    dir_res = {}
    for metric, label in [('fwd_rv5', '5d RV'), ('vix_chg_1d', '1d VIX chg'), ('vix_chg_5d', '5d VIX chg')]:
        vals = sub_df[metric].dropna()
        dir_res[metric] = {
            'mean': float(vals.mean()),
            'median': float(vals.median()),
            'n': int(len(vals)),
        }
    direction_results[direction_label] = dir_res
    print(f"\n  {direction_label} (N={len(sub_df)}):")
    for metric in ['fwd_rv5', 'vix_chg_1d', 'vix_chg_5d']:
        print(f"    {metric}: mean={dir_res[metric]['mean']:.4f}, median={dir_res[metric]['median']:.4f}")

# Normal days comparison
normal_res = {}
for metric in ['fwd_rv5', 'vix_chg_1d', 'vix_chg_5d']:
    vals = normal_df[metric].dropna()
    normal_res[metric] = {'mean': float(vals.mean()), 'median': float(vals.median()), 'n': int(len(vals))}
direction_results['normal'] = normal_res
print(f"\n  normal (N={len(normal_df)}):")
for metric in ['fwd_rv5', 'vix_chg_1d', 'vix_chg_5d']:
    print(f"    {metric}: mean={normal_res[metric]['mean']:.4f}, median={normal_res[metric]['median']:.4f}")

# ─── B.3: Partial correlation controlling for VIX level ───
print("\n--- Partial correlation (controlling for VIX level) ---")
from numpy.linalg import lstsq

def partial_corr(x, y, z):
    """Partial correlation between x and y, controlling for z."""
    # Regress x on z
    z_arr = np.column_stack([z, np.ones(len(z))])
    x_resid = x - z_arr @ lstsq(z_arr, x, rcond=None)[0]
    y_resid = y - z_arr @ lstsq(z_arr, y, rcond=None)[0]
    return float(np.corrcoef(x_resid, y_resid)[0, 1])

valid = analysis_df.dropna(subset=['abn_vol', 'fwd_rv5', 'vix'])
pc_vol_rv5 = partial_corr(valid['abn_vol'].values, valid['fwd_rv5'].values, valid['vix'].values)
pc_vol_vixchg = partial_corr(valid['abn_vol'].values, valid['vix_chg_5d'].values, valid['vix'].values)

print(f"  Partial corr (abn_vol, fwd_rv5 | VIX): {pc_vol_rv5:.4f}")
print(f"  Partial corr (abn_vol, vix_chg_5d | VIX): {pc_vol_vixchg:.4f}")

# ─── B.4: Quantile analysis — more granular ───
print("\n--- Quantile analysis of forward vol by volume level ---")
analysis_df['vol_decile'] = pd.qcut(analysis_df['abn_vol'], 10, labels=False, duplicates='drop') + 1

decile_results = {}
for dec in sorted(analysis_df['vol_decile'].unique()):
    sub = analysis_df[analysis_df['vol_decile'] == dec]
    decile_results[int(dec)] = {
        'n': int(len(sub)),
        'mean_abn_vol': round(float(sub['abn_vol'].mean()), 3),
        'fwd_rv5_mean': round(float(sub['fwd_rv5'].mean()), 4),
        'fwd_rv22_mean': round(float(sub['fwd_rv22'].mean()), 4),
        'vix_chg_5d_mean': round(float(sub['vix_chg_5d'].mean()), 4),
    }
    print(f"  Decile {dec} (abn_vol ~{sub['abn_vol'].mean():.2f}x, N={len(sub)}): "
          f"fwd_rv5={sub['fwd_rv5'].mean():.4f}, fwd_rv22={sub['fwd_rv22'].mean():.4f}, "
          f"vix_chg5d={sub['vix_chg_5d'].mean():+.3f}")

# Check monotonicity
dec_keys = sorted(decile_results.keys())
fwd_rv5_vals = [decile_results[k]['fwd_rv5_mean'] for k in dec_keys]
# Spearman rank correlation between decile and forward RV
rho_dec, p_rho_dec = stats.spearmanr(dec_keys, fwd_rv5_vals)
print(f"\n  Spearman(decile, fwd_rv5): rho={rho_dec:.4f}, p={p_rho_dec:.4f}")

results['part_b'] = {
    'forward_rv': fwd_rv_results,
    'vix_change': vix_chg_results,
    'direction_conditional': direction_results,
    'partial_corr_vol_rv5_ctrl_vix': round(pc_vol_rv5, 4),
    'partial_corr_vol_vixchg5_ctrl_vix': round(pc_vol_vixchg, 4),
    'decile_analysis': decile_results,
    'spearman_decile_fwd_rv5': {'rho': round(rho_dec, 4), 'p': round(p_rho_dec, 4)},
}

# ═══════════════════════════════════════════════════
# Part C: Volume Exhaustion Trading Strategy
# ═══════════════════════════════════════════════════
print("\n" + "=" * 70)
print("Part C: Volume Exhaustion Trading Strategy")
print("=" * 70)

# Strategy: After extreme volume, INCREASE equity weight for 5 days
# Logic: uncertainty resolved → expect lower vol → tilt toward equity
# Use monthly rebalancing for baseline, event-driven overlay

# ─── C.1: Build strategy signals ───
# Use abn_vol from t-1 (LAGGED!) to decide weight at t
# signal.shift(1) is critical — we use YESTERDAY's volume to set TODAY's weight
abn_vol_lagged = analysis_df['abn_vol'].shift(1)  # LAGGED signal

# Strategy: base = 12/VIX weight (as in existing strategy),
# but BOOST by 20% (additive) when yesterday had extreme volume
# Cap at 1.0 (100% equity)
vix_lagged = analysis_df['vix'].shift(1)
base_weight = np.clip(12.0 / vix_lagged, 0, 1)

# Volume Exhaustion overlay: boost equity for 5 days after extreme volume
# Mark the 5 days following an extreme volume day
extreme_flag_lagged = (abn_vol_lagged > 2.0).astype(float)
# Extend the flag to cover 5 days
boost_window = extreme_flag_lagged.rolling(5, min_periods=1).max()

BOOST = 0.15  # add 15% equity allocation after extreme volume
vol_exhaust_weight = np.clip(base_weight + BOOST * boost_window, 0, 1)

# Alternative: pure volume-exhaustion strategy (simpler)
# High volume → next day increase equity; low volume → decrease
# Weight = 12/VIX * (1 + alpha * I(extreme volume yesterday))
ALPHA = 0.25
vol_exhaust_simple = np.clip(base_weight * (1 + ALPHA * extreme_flag_lagged), 0, 1)

# Baseline strategies
bh_5050_weight = pd.Series(0.5, index=analysis_df.index)
twelve_vix_weight = base_weight.copy()

# ─── C.2: Compute returns with TX costs ───
TX_COST = 0.0005  # 5 bps per leg

def compute_strategy_returns(weights, returns, tx_cost=TX_COST):
    """Compute portfolio returns with transaction costs."""
    # weights are for SPY, rest in cash (0 return)
    w = weights.copy()
    r = returns.copy()

    # Align
    common = w.dropna().index.intersection(r.dropna().index)
    w = w.loc[common]
    r = r.loc[common]

    # Transaction costs: |delta_w| for SPY + |delta_w| for cash (= 2 * |delta_w| one way, but sum abs)
    delta_w = w.diff().abs()
    tx = delta_w * tx_cost * 2  # both legs
    tx.iloc[0] = w.iloc[0] * tx_cost * 2  # initial allocation

    # Portfolio return
    port_ret = w * r - tx
    return port_ret

spy_ret = analysis_df['ret'].copy()

# Restrict to 2006-2026 for clean comparison
strat_start = '2006-01-01'
strat_end = '2026-03-28'

strategies = {
    'vol_exhaust_overlay': vol_exhaust_weight,
    'vol_exhaust_simple': vol_exhaust_simple,
    '12_vix': twelve_vix_weight,
    'bh_50': bh_5050_weight,
}

strat_results = {}
for name, w in strategies.items():
    port_ret = compute_strategy_returns(w, spy_ret)
    port_ret = port_ret.loc[strat_start:strat_end].dropna()

    cum = (1 + port_ret).cumprod()
    ann_ret = (cum.iloc[-1]) ** (252 / len(port_ret)) - 1
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    mdd = (cum / cum.cummax() - 1).min()
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    strat_results[name] = {
        'ann_return': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 4),
        'mdd': round(float(mdd), 4),
        'calmar': round(float(calmar), 4),
        'n_days': int(len(port_ret)),
    }

    print(f"\n  {name}:")
    print(f"    Return: {ann_ret*100:.2f}%, Vol: {ann_vol*100:.2f}%, Sharpe: {sharpe:.4f}")
    print(f"    MDD: {mdd*100:.2f}%, Calmar: {calmar:.4f}")

# ─── C.3: Cross-OOS validation (5 non-overlapping 2-year periods) ───
print("\n--- Cross-OOS Validation (5 periods) ---")

oos_periods = [
    ('2006-01-01', '2007-12-31'),
    ('2008-01-01', '2009-12-31'),
    ('2010-01-01', '2015-12-31'),
    ('2016-01-01', '2019-12-31'),
    ('2020-01-01', '2025-12-31'),
]

oos_results = []
for i, (start, end) in enumerate(oos_periods, 1):
    period_ret_exhaust = compute_strategy_returns(vol_exhaust_simple, spy_ret).loc[start:end].dropna()
    period_ret_baseline = compute_strategy_returns(bh_5050_weight, spy_ret).loc[start:end].dropna()

    if len(period_ret_exhaust) < 100:
        print(f"  Period {i} ({start} to {end}): insufficient data")
        continue

    cum_e = (1 + period_ret_exhaust).cumprod()
    cum_b = (1 + period_ret_baseline).cumprod()

    sharpe_e = period_ret_exhaust.mean() / period_ret_exhaust.std() * np.sqrt(252)
    sharpe_b = period_ret_baseline.mean() / period_ret_baseline.std() * np.sqrt(252)

    wins = 'Exhaust' if sharpe_e > sharpe_b else 'BH 50/50'

    oos_results.append({
        'period': f"{start} to {end}",
        'sharpe_exhaust': round(float(sharpe_e), 4),
        'sharpe_baseline': round(float(sharpe_b), 4),
        'winner': wins,
        'n_days': int(len(period_ret_exhaust)),
    })

    print(f"  Period {i} ({start}-{end}): Exhaust Sharpe={sharpe_e:.4f}, BH={sharpe_b:.4f} → {wins}")

wins_count = sum(1 for r in oos_results if r['winner'] == 'Exhaust')
print(f"\n  Exhaust wins {wins_count}/{len(oos_results)} OOS periods")

# ─── C.4: DM test for strategy comparison ───
print("\n--- Diebold-Mariano Test ---")
ret_exhaust = compute_strategy_returns(vol_exhaust_simple, spy_ret).loc[strat_start:strat_end].dropna()
ret_12vix = compute_strategy_returns(twelve_vix_weight, spy_ret).loc[strat_start:strat_end].dropna()

# Align
common_idx = ret_exhaust.index.intersection(ret_12vix.index)
d = ret_exhaust.loc[common_idx] - ret_12vix.loc[common_idx]  # difference in returns
dm_stat = d.mean() / (d.std() / np.sqrt(len(d)))
dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
print(f"  DM stat (exhaust vs 12/VIX): {dm_stat:.4f}, p-value: {dm_pval:.4f}")

results['part_c'] = {
    'boost_parameter': BOOST,
    'alpha_parameter': ALPHA,
    'tx_cost_bps': TX_COST * 10000,
    'strategies': strat_results,
    'cross_oos': oos_results,
    'oos_wins': f"{wins_count}/{len(oos_results)}",
    'dm_test_vs_12vix': {'stat': round(float(dm_stat), 4), 'p_value': round(float(dm_pval), 4)},
}

# ═══════════════════════════════════════════════════
# Part D: Robustness — Different Extreme Thresholds
# ═══════════════════════════════════════════════════
print("\n" + "=" * 70)
print("Part D: Robustness — Sensitivity to Extreme Volume Threshold")
print("=" * 70)

threshold_sensitivity = {}
for thresh in [1.5, 2.0, 2.5, 3.0]:
    flag_t = (abn_vol_lagged > thresh).astype(float)
    w_t = np.clip(base_weight * (1 + ALPHA * flag_t), 0, 1)
    ret_t = compute_strategy_returns(w_t, spy_ret).loc[strat_start:strat_end].dropna()

    cum_t = (1 + ret_t).cumprod()
    ann_ret_t = cum_t.iloc[-1] ** (252/len(ret_t)) - 1
    ann_vol_t = ret_t.std() * np.sqrt(252)
    sharpe_t = ann_ret_t / ann_vol_t if ann_vol_t > 0 else 0
    mdd_t = (cum_t / cum_t.cummax() - 1).min()

    n_triggers = int(flag_t.sum())

    threshold_sensitivity[str(thresh)] = {
        'sharpe': round(float(sharpe_t), 4),
        'ann_return': round(float(ann_ret_t), 4),
        'mdd': round(float(mdd_t), 4),
        'n_triggers': n_triggers,
    }
    print(f"  Threshold {thresh}x: Sharpe={sharpe_t:.4f}, Return={ann_ret_t*100:.2f}%, "
          f"MDD={mdd_t*100:.2f}%, Triggers={n_triggers}")

# Compare base 12/VIX
base_12vix_sharpe = strat_results['12_vix']['sharpe']
print(f"\n  Base 12/VIX Sharpe: {base_12vix_sharpe:.4f}")
print(f"  Best threshold Sharpe: {max(v['sharpe'] for v in threshold_sensitivity.values()):.4f}")

results['part_d'] = {
    'threshold_sensitivity': threshold_sensitivity,
    'base_12vix_sharpe': base_12vix_sharpe,
}

# ═══════════════════════════════════════════════════
# Part E: Volume Exhaustion Mechanism — What Happens After?
# ═══════════════════════════════════════════════════
print("\n" + "=" * 70)
print("Part E: Post-Extreme Volume Day-by-Day Analysis")
print("=" * 70)

# Track what happens day by day after extreme volume
# Avoid overlapping windows: skip if another extreme day is within 5 days before
extreme_indices = analysis_df.index[extreme_mask]
clean_extreme_indices = []
for idx in extreme_indices:
    pos = analysis_df.index.get_loc(idx)
    # Check no other extreme day in previous 5 days
    if len(clean_extreme_indices) == 0 or (pos - analysis_df.index.get_loc(clean_extreme_indices[-1])) > 5:
        clean_extreme_indices.append(idx)

print(f"Non-overlapping extreme volume events: {len(clean_extreme_indices)} (from {n_extreme} total)")

day_by_day = {}
for lag in range(1, 11):  # t+1 to t+10
    rets = []
    vix_chgs = []
    for evt_date in clean_extreme_indices:
        pos = analysis_df.index.get_loc(evt_date)
        if pos + lag < len(analysis_df):
            fwd_date = analysis_df.index[pos + lag]
            rets.append(analysis_df.loc[fwd_date, 'ret'])
            vix_chgs.append(analysis_df.loc[fwd_date, 'vix'] - analysis_df.loc[evt_date, 'vix'])

    rets = np.array(rets)
    vix_chgs = np.array(vix_chgs)

    # Compare to unconditional
    t_ret, p_ret = stats.ttest_1samp(rets, analysis_df['ret'].mean())
    t_vix, p_vix = stats.ttest_1samp(vix_chgs, 0)

    day_by_day[lag] = {
        'mean_ret': round(float(rets.mean()), 6),
        'mean_vix_chg': round(float(vix_chgs.mean()), 4),
        't_ret': round(float(t_ret), 3),
        'p_ret': round(float(p_ret), 4),
        't_vix_chg': round(float(t_vix), 3),
        'p_vix_chg': round(float(p_vix), 4),
        'n_events': len(rets),
    }

    print(f"  t+{lag:2d}: mean_ret={rets.mean()*100:+.4f}%, "
          f"VIX_chg={vix_chgs.mean():+.3f} "
          f"(t_ret={t_ret:.2f}, p={p_ret:.3f} | t_vix={t_vix:.2f}, p={p_vix:.3f})")

# Cumulative return over 5 and 10 days after extreme volume
cum_5d = []
cum_10d = []
for evt_date in clean_extreme_indices:
    pos = analysis_df.index.get_loc(evt_date)
    if pos + 5 < len(analysis_df):
        r5 = analysis_df['ret'].iloc[pos+1:pos+6].sum()
        cum_5d.append(r5)
    if pos + 10 < len(analysis_df):
        r10 = analysis_df['ret'].iloc[pos+1:pos+11].sum()
        cum_10d.append(r10)

cum_5d = np.array(cum_5d)
cum_10d = np.array(cum_10d)
print(f"\n  Cumulative 5d return after extreme vol: {cum_5d.mean()*100:+.4f}% (t={stats.ttest_1samp(cum_5d, 0)[0]:.2f})")
print(f"  Cumulative 10d return after extreme vol: {cum_10d.mean()*100:+.4f}% (t={stats.ttest_1samp(cum_10d, 0)[0]:.2f})")
print(f"  Unconditional daily mean return: {analysis_df['ret'].mean()*100:+.4f}%")
print(f"  Expected 5d: {analysis_df['ret'].mean()*5*100:+.4f}%, Expected 10d: {analysis_df['ret'].mean()*10*100:+.4f}%")

results['part_e'] = {
    'n_clean_events': len(clean_extreme_indices),
    'day_by_day': day_by_day,
    'cum_5d_mean': round(float(cum_5d.mean()), 6),
    'cum_10d_mean': round(float(cum_10d.mean()), 6),
    'cum_5d_t': round(float(stats.ttest_1samp(cum_5d, 0)[0]), 3),
    'cum_10d_t': round(float(stats.ttest_1samp(cum_10d, 0)[0]), 3),
    'unconditional_daily_mean': round(float(analysis_df['ret'].mean()), 6),
}

# ═══════════════════════════════════════════════════
# Part F: Extreme Volume UP vs DOWN — Asymmetry
# ═══════════════════════════════════════════════════
print("\n" + "=" * 70)
print("Part F: Asymmetry — Extreme Volume UP vs DOWN days")
print("=" * 70)

# Separate extreme volume UP days and DOWN days
extreme_up_mask = extreme_mask & (analysis_df['ret'] > 0)
extreme_down_mask = extreme_mask & (analysis_df['ret'] <= 0)

for label, mask in [('Extreme UP', extreme_up_mask), ('Extreme DOWN', extreme_down_mask)]:
    sub = analysis_df[mask]
    n = len(sub)

    fwd5 = sub['fwd_rv5'].dropna()
    fwd22 = sub['fwd_rv22'].dropna()
    vchg5 = sub['vix_chg_5d'].dropna()

    # Compare to unconditional
    t_rv5, p_rv5 = stats.ttest_ind(fwd5, normal_df['fwd_rv5'].dropna(), equal_var=False)
    t_vchg, p_vchg = stats.ttest_ind(vchg5, normal_df['vix_chg_5d'].dropna(), equal_var=False)

    print(f"\n  {label} (N={n}):")
    print(f"    fwd_rv5:    {fwd5.mean():.4f} vs normal {normal_df['fwd_rv5'].mean():.4f} "
          f"(t={t_rv5:.2f}, p={p_rv5:.3f})")
    print(f"    fwd_rv22:   {fwd22.mean():.4f} vs normal {normal_df['fwd_rv22'].mean():.4f}")
    print(f"    vix_chg_5d: {vchg5.mean():+.3f} vs normal {normal_df['vix_chg_5d'].mean():+.3f} "
          f"(t={t_vchg:.2f}, p={p_vchg:.3f})")

# Key asymmetry test: is extreme UP different from extreme DOWN?
up_fwd = analysis_df[extreme_up_mask]['fwd_rv5'].dropna()
dn_fwd = analysis_df[extreme_down_mask]['fwd_rv5'].dropna()
t_asym, p_asym = stats.ttest_ind(up_fwd, dn_fwd, equal_var=False)
print(f"\n  Asymmetry (UP vs DOWN) fwd_rv5: t={t_asym:.3f}, p={p_asym:.4f}")
print(f"    UP mean: {up_fwd.mean():.4f}, DOWN mean: {dn_fwd.mean():.4f}")

results['part_f'] = {
    'extreme_up_n': int(extreme_up_mask.sum()),
    'extreme_down_n': int(extreme_down_mask.sum()),
    'extreme_up_fwd_rv5': round(float(up_fwd.mean()), 4),
    'extreme_down_fwd_rv5': round(float(dn_fwd.mean()), 4),
    'normal_fwd_rv5': round(float(normal_df['fwd_rv5'].mean()), 4),
    'asymmetry_t': round(float(t_asym), 3),
    'asymmetry_p': round(float(p_asym), 4),
    'extreme_up_vix_chg5d': round(float(analysis_df[extreme_up_mask]['vix_chg_5d'].mean()), 4),
    'extreme_down_vix_chg5d': round(float(analysis_df[extreme_down_mask]['vix_chg_5d'].mean()), 4),
}

# ═══════════════════════════════════════════════════
# Part G: Sub-period stability
# ═══════════════════════════════════════════════════
print("\n" + "=" * 70)
print("Part G: Sub-period Stability of Volume Exhaustion Effect")
print("=" * 70)

sub_periods = [
    ('2006-2010', '2006-01-01', '2010-12-31'),
    ('2011-2015', '2011-01-01', '2015-12-31'),
    ('2016-2020', '2016-01-01', '2020-12-31'),
    ('2021-2025', '2021-01-01', '2025-12-31'),
]

subperiod_results = {}
for label, start, end in sub_periods:
    sub = analysis_df.loc[start:end]
    ext_sub = sub[sub['abn_vol'] > 2.0]
    nrm_sub = sub[sub['abn_vol'] <= 2.0]

    if len(ext_sub) < 5:
        print(f"  {label}: insufficient extreme days ({len(ext_sub)})")
        subperiod_results[label] = {'n_extreme': int(len(ext_sub)), 'note': 'insufficient data'}
        continue

    ext_rv5 = ext_sub['fwd_rv5'].dropna()
    nrm_rv5 = nrm_sub['fwd_rv5'].dropna()

    t_sub, p_sub = stats.ttest_ind(ext_rv5, nrm_rv5, equal_var=False)
    diff_pct = (ext_rv5.mean() - nrm_rv5.mean()) / nrm_rv5.mean() * 100

    subperiod_results[label] = {
        'n_extreme': int(len(ext_sub)),
        'n_normal': int(len(nrm_sub)),
        'extreme_fwd_rv5': round(float(ext_rv5.mean()), 4),
        'normal_fwd_rv5': round(float(nrm_rv5.mean()), 4),
        'diff_pct': round(float(diff_pct), 1),
        't_stat': round(float(t_sub), 3),
        'p_value': round(float(p_sub), 4),
    }

    direction = "LOWER" if diff_pct < 0 else "HIGHER"
    print(f"  {label}: Extreme fwd_rv5={ext_rv5.mean():.4f} vs Normal={nrm_rv5.mean():.4f} "
          f"({direction} by {abs(diff_pct):.1f}%, t={t_sub:.2f}, p={p_sub:.3f}, N_ext={len(ext_sub)})")

results['part_g'] = subperiod_results

# ═══════════════════════════════════════════════════
# Summary & Conclusions
# ═══════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SUMMARY & CONCLUSIONS")
print("=" * 70)

# Determine if exhaustion effect is real
exhaustion_confirmed = fwd_rv_results['fwd_rv5']['diff'] < 0  # extreme vol → lower future vol
strategy_beats_baseline = strat_results['vol_exhaust_simple']['sharpe'] > strat_results['12_vix']['sharpe']
effect_significant = fwd_rv_results['fwd_rv5']['p_value'] < 0.05

conclusions = []
if exhaustion_confirmed:
    conclusions.append(f"Volume exhaustion CONFIRMED: extreme vol days followed by {fwd_rv_results['fwd_rv5']['diff_pct']:.1f}% lower 5d RV")
else:
    conclusions.append(f"Volume exhaustion NOT confirmed: extreme vol days followed by {fwd_rv_results['fwd_rv5']['diff_pct']:+.1f}% different 5d RV")

if effect_significant:
    conclusions.append(f"Effect is statistically significant (p={fwd_rv_results['fwd_rv5']['p_value']:.4f})")
else:
    conclusions.append(f"Effect is NOT statistically significant (p={fwd_rv_results['fwd_rv5']['p_value']:.4f})")

if strategy_beats_baseline:
    conclusions.append(f"Strategy BEATS 12/VIX (Sharpe {strat_results['vol_exhaust_simple']['sharpe']:.4f} vs {strat_results['12_vix']['sharpe']:.4f})")
else:
    conclusions.append(f"Strategy DOES NOT beat 12/VIX (Sharpe {strat_results['vol_exhaust_simple']['sharpe']:.4f} vs {strat_results['12_vix']['sharpe']:.4f})")

for c in conclusions:
    print(f"  • {c}")

# Harvey (2016) threshold check
print(f"\n  Harvey (2016) threshold: |t| > 3.0 required for publication")
print(f"  fwd_rv5 t-stat: {abs(fwd_rv_results['fwd_rv5']['t_stat']):.3f} {'PASS' if abs(fwd_rv_results['fwd_rv5']['t_stat']) > 3.0 else 'FAIL'}")
print(f"  DM test t-stat: {abs(dm_stat):.3f} {'PASS' if abs(dm_stat) > 3.0 else 'FAIL'}")

results['conclusions'] = {
    'exhaustion_confirmed': exhaustion_confirmed,
    'effect_significant': effect_significant,
    'strategy_beats_12vix': strategy_beats_baseline,
    'conclusions': conclusions,
    'harvey_threshold': {
        'fwd_rv5_t': round(float(abs(fwd_rv_results['fwd_rv5']['t_stat'])), 3),
        'dm_test_t': round(float(abs(dm_stat)), 3),
        'fwd_rv5_pass': bool(abs(fwd_rv_results['fwd_rv5']['t_stat']) > 3.0),
        'dm_test_pass': bool(abs(dm_stat) > 3.0),
    }
}

# Save results
output_path = 'experiments/k754_volume_exhaustion_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")
print("\nK754 complete.")
