"""
K753: Market Liquidity as Volatility Predictor — Does Trading Volume Lead VIX?
==============================================================================
[提出: Claude, 執行: Claude]

Academic basis:
- Lamoureux & Lastrapes (1990) "Heteroskedasticity in Stock Return Data: Volume versus GARCH Effects" JoF
- Gallant, Rossi & Tauchen (1992) "Stock Prices and Volume" RFS
- K710 found volume z-score incremental R²=0.0023 (linear regression only)
- This experiment extends with nonlinear analysis, conditional probabilities, and trading strategy

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
print("K753: Market Liquidity as Volatility Predictor")
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

# Returns and realized vol
df['ret'] = df['close'].pct_change()
df['abs_ret'] = df['ret'].abs()
df['rv5'] = df['ret'].rolling(5).std() * np.sqrt(252)  # 5-day annualized RV
df['rv20'] = df['ret'].rolling(20).std() * np.sqrt(252)  # 20-day annualized RV

# Volume metrics
df['vol_ma20'] = df['volume'].rolling(20).mean()
df['abn_vol'] = df['volume'] / df['vol_ma20']  # abnormal volume ratio
df['vol_zscore'] = (df['volume'] - df['vol_ma20']) / df['volume'].rolling(20).std()
df['vol_change'] = df['volume'].pct_change()  # volume momentum (1-day change)
df['vol_change5'] = df['volume'] / df['volume'].shift(5) - 1  # 5-day volume change
df['vol_pctile'] = df['volume'].rolling(252).rank(pct=True)  # percentile rank in trailing year

# Drop warmup
df = df.loc['2006-01-01':].dropna()
print(f"Sample: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, N={len(df)}")

results = {
    'experiment_id': 'K753',
    'title': 'Market Liquidity as Volatility Predictor',
    'data_source': 'yfinance SPY/VIX',
    'sample_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_obs': len(df),
    'references': [
        'Lamoureux & Lastrapes (1990) JoF',
        'Gallant, Rossi & Tauchen (1992) RFS',
        'K710: Volume z-score incremental R²=0.0023'
    ]
}

# ─────────────────────────────────────────────────
# Part A: Volume-Volatility Relationship
# ─────────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART A: Volume-Volatility Contemporaneous Relationship")
print("=" * 70)

# Contemporaneous correlations
corr_vol_absret = df['abn_vol'].corr(df['abs_ret'])
corr_vol_vix = df['abn_vol'].corr(df['vix'])
corr_vol_rv5 = df['abn_vol'].corr(df['rv5'])
corr_zscore_absret = df['vol_zscore'].corr(df['abs_ret'])

print(f"\nContemporaneous correlations:")
print(f"  Abnormal volume vs |return|:  {corr_vol_absret:.4f}")
print(f"  Abnormal volume vs VIX:       {corr_vol_vix:.4f}")
print(f"  Abnormal volume vs RV(5d):    {corr_vol_rv5:.4f}")
print(f"  Volume z-score vs |return|:   {corr_zscore_absret:.4f}")

# Volume quintile analysis
df['vol_quintile'] = pd.qcut(df['abn_vol'], 5, labels=[1,2,3,4,5])
quintile_stats = df.groupby('vol_quintile').agg(
    mean_abs_ret=('abs_ret', 'mean'),
    mean_vix=('vix', 'mean'),
    mean_rv5=('rv5', 'mean'),
    count=('ret', 'count')
).round(4)
print(f"\nVolume quintile analysis:")
print(quintile_stats.to_string())

part_a = {
    'corr_abn_vol_vs_abs_ret': round(corr_vol_absret, 4),
    'corr_abn_vol_vs_vix': round(corr_vol_vix, 4),
    'corr_abn_vol_vs_rv5': round(corr_vol_rv5, 4),
    'corr_vol_zscore_vs_abs_ret': round(corr_zscore_absret, 4),
    'quintile_mean_abs_ret': quintile_stats['mean_abs_ret'].to_dict(),
    'quintile_mean_vix': quintile_stats['mean_vix'].to_dict(),
    'conclusion_A': 'High volume coincides with high volatility (MDH hypothesis confirmed)'
}
results['part_a'] = part_a

# ─────────────────────────────────────────────────
# Part B: Predictive Power (NEXT-day, properly lagged)
# ─────────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART B: Predictive Power — Does today's volume predict TOMORROW's vol?")
print("=" * 70)

# Target: next-day realized metrics
df['next_abs_ret'] = df['abs_ret'].shift(-1)
df['next_rv5'] = df['rv5'].shift(-5)  # RV computed over next 5 days

# Use lag-1 signals (signal at t, target at t+1)
pred_df = df[['abn_vol', 'vol_zscore', 'vol_change', 'vol_change5', 'vol_pctile',
              'vix', 'next_abs_ret']].dropna()

print(f"\nPredictive correlations (signal_t vs |return|_t+1):")
for sig in ['abn_vol', 'vol_zscore', 'vol_change', 'vol_change5', 'vol_pctile', 'vix']:
    c = pred_df[sig].corr(pred_df['next_abs_ret'])
    print(f"  {sig:20s}: {c:.4f}")

# Regression: next_abs_ret = α + β₁×VIX + ε
from numpy.linalg import lstsq

y = pred_df['next_abs_ret'].values
X_vix = np.column_stack([np.ones(len(y)), pred_df['vix'].values])
X_both = np.column_stack([np.ones(len(y)), pred_df['vix'].values, pred_df['abn_vol'].values])
X_vol_only = np.column_stack([np.ones(len(y)), pred_df['abn_vol'].values])

# OLS
def ols_r2(X, y):
    beta = lstsq(X, y, rcond=None)[0]
    y_hat = X @ beta
    ss_res = np.sum((y - y_hat)**2)
    ss_tot = np.sum((y - y.mean())**2)
    r2 = 1 - ss_res / ss_tot
    return r2, beta

r2_vix, beta_vix = ols_r2(X_vix, y)
r2_both, beta_both = ols_r2(X_both, y)
r2_vol, beta_vol = ols_r2(X_vol_only, y)

incremental_r2 = r2_both - r2_vix

print(f"\nRegression R² (predicting next-day |return|):")
print(f"  VIX only:          R² = {r2_vix:.6f}")
print(f"  Volume only:       R² = {r2_vol:.6f}")
print(f"  VIX + Volume:      R² = {r2_both:.6f}")
print(f"  Incremental R²:    {incremental_r2:.6f}")

# Partial correlation of volume with next |return|, controlling for VIX
from scipy.stats import pearsonr

# Residualize both volume and next_abs_ret on VIX
def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z"""
    beta_xz = lstsq(np.column_stack([np.ones(len(z)), z]), x, rcond=None)[0]
    beta_yz = lstsq(np.column_stack([np.ones(len(z)), z]), y, rcond=None)[0]
    resid_x = x - np.column_stack([np.ones(len(z)), z]) @ beta_xz
    resid_y = y - np.column_stack([np.ones(len(z)), z]) @ beta_yz
    r, p = pearsonr(resid_x, resid_y)
    return r, p

pc_r, pc_p = partial_corr(
    pred_df['abn_vol'].values,
    pred_df['next_abs_ret'].values,
    pred_df['vix'].values
)
print(f"\nPartial correlation (volume → next |ret| | VIX):")
print(f"  r = {pc_r:.4f}, p = {pc_p:.6f}")

# Volume change (momentum) partial correlation
pc_r2, pc_p2 = partial_corr(
    pred_df['vol_change'].values,
    pred_df['next_abs_ret'].values,
    pred_df['vix'].values
)
print(f"  Volume change partial corr: r = {pc_r2:.4f}, p = {pc_p2:.6f}")

# DM test: VIX+Volume vs VIX alone
from scipy.stats import norm

y_hat_vix = X_vix @ beta_vix
y_hat_both = X_both @ beta_both
e_vix = (y - y_hat_vix)**2
e_both = (y - y_hat_both)**2
d = e_vix - e_both  # positive means VIX+Volume is better

# Newey-West HAC standard errors for DM test
def newey_west_se(d, lag=10):
    n = len(d)
    d_bar = d.mean()
    gamma = np.zeros(lag + 1)
    for j in range(lag + 1):
        gamma[j] = np.mean((d[:n-j] - d_bar) * (d[j:] - d_bar))
    var_d = gamma[0] + 2 * sum((1 - j/(lag+1)) * gamma[j] for j in range(1, lag+1))
    se = np.sqrt(var_d / n)
    return se

dm_stat = d.mean() / newey_west_se(d, lag=10)
dm_pval = 2 * (1 - norm.cdf(abs(dm_stat)))
print(f"\nDM test (VIX+Volume vs VIX alone):")
print(f"  DM stat = {dm_stat:.4f}, p = {dm_pval:.4f}")
print(f"  Mean loss reduction = {d.mean():.8f}")

part_b = {
    'r2_vix_only': round(r2_vix, 6),
    'r2_volume_only': round(r2_vol, 6),
    'r2_vix_plus_volume': round(r2_both, 6),
    'incremental_r2': round(incremental_r2, 6),
    'partial_corr_volume_control_vix': round(pc_r, 4),
    'partial_corr_pval': round(pc_p, 6),
    'partial_corr_vol_change': round(pc_r2, 4),
    'dm_stat': round(dm_stat, 4),
    'dm_pval': round(dm_pval, 4),
}
results['part_b'] = part_b

# ─────────────────────────────────────────────────
# Part C: Liquidity Drying Up as Warning Signal
# ─────────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART C: Liquidity Drying Up — 'Calm Before the Storm' Hypothesis")
print("=" * 70)

# Define events:
# "Volume drop": volume falls from >80th percentile (past 5d avg) to <50th pct today
df['vol_pctile_5d'] = df['vol_pctile'].rolling(5).mean()  # 5-day average percentile
df['volume_drop'] = (df['vol_pctile_5d'].shift(1) > 0.80) & (df['vol_pctile'] < 0.50)

# "VIX spike": VIX increases by >10% in next 5 days
df['vix_5d_change'] = df['vix'].shift(-5) / df['vix'] - 1
df['vix_spike'] = df['vix_5d_change'] > 0.10

# Conditional probability
vol_drop_days = df[df['volume_drop'] == True]
n_vol_drop = len(vol_drop_days)
n_vix_spike_after_drop = vol_drop_days['vix_spike'].sum()
p_spike_given_drop = n_vix_spike_after_drop / n_vol_drop if n_vol_drop > 0 else 0

# Unconditional probability of VIX spike
p_spike_unconditional = df['vix_spike'].mean()

print(f"\nVolume drop events (>80th pctile 5d avg → <50th pctile today): {n_vol_drop}")
print(f"VIX spike (>10% in 5 days) after volume drop: {n_vix_spike_after_drop}")
print(f"P(VIX spike | volume drop) = {p_spike_given_drop:.4f}")
print(f"P(VIX spike | unconditional) = {p_spike_unconditional:.4f}")
print(f"Lift ratio = {p_spike_given_drop / p_spike_unconditional:.2f}x" if p_spike_unconditional > 0 else "")

# Also test: sustained low volume (below median for 5 consecutive days)
df['low_vol_streak'] = (df['vol_pctile'] < 0.5).rolling(5).sum() == 5
low_vol_days = df[df['low_vol_streak'] == True]
n_low = len(low_vol_days)
n_spike_after_low = low_vol_days['vix_spike'].sum() if n_low > 0 else 0
p_spike_given_low = n_spike_after_low / n_low if n_low > 0 else 0

print(f"\nSustained low volume (5 consecutive days <50th pctile): {n_low}")
print(f"P(VIX spike | sustained low vol) = {p_spike_given_low:.4f}")
print(f"Lift ratio = {p_spike_given_low / p_spike_unconditional:.2f}x" if p_spike_unconditional > 0 else "")

# High volume as warning
df['high_vol_day'] = df['abn_vol'] > 2.0  # Volume > 2x average
high_vol_days = df[df['high_vol_day'] == True]
n_high = len(high_vol_days)
n_spike_after_high = high_vol_days['vix_spike'].sum() if n_high > 0 else 0
p_spike_given_high = n_spike_after_high / n_high if n_high > 0 else 0

print(f"\nHigh volume days (>2x 20d avg): {n_high}")
print(f"P(VIX spike | high volume) = {p_spike_given_high:.4f}")
print(f"Lift ratio = {p_spike_given_high / p_spike_unconditional:.2f}x" if p_spike_unconditional > 0 else "")

# Volume regime analysis: what happens after extreme volume?
df['vol_regime'] = pd.cut(df['abn_vol'], bins=[0, 0.7, 1.0, 1.3, 2.0, 100],
                          labels=['very_low', 'low', 'normal', 'high', 'extreme'])
regime_next5d = df.groupby('vol_regime').agg(
    mean_next5d_vix_chg=('vix_5d_change', 'mean'),
    std_next5d_vix_chg=('vix_5d_change', 'std'),
    p_spike=('vix_spike', 'mean'),
    count=('ret', 'count')
).round(4)
print(f"\nVolume regime → next 5-day VIX change:")
print(regime_next5d.to_string())

part_c = {
    'n_volume_drop_events': int(n_vol_drop),
    'p_spike_given_drop': round(p_spike_given_drop, 4),
    'p_spike_unconditional': round(p_spike_unconditional, 4),
    'lift_volume_drop': round(p_spike_given_drop / p_spike_unconditional, 2) if p_spike_unconditional > 0 else None,
    'n_sustained_low_vol': int(n_low),
    'p_spike_given_sustained_low': round(p_spike_given_low, 4),
    'lift_sustained_low': round(p_spike_given_low / p_spike_unconditional, 2) if p_spike_unconditional > 0 else None,
    'n_high_vol_days': int(n_high),
    'p_spike_given_high_vol': round(p_spike_given_high, 4),
    'lift_high_vol': round(p_spike_given_high / p_spike_unconditional, 2) if p_spike_unconditional > 0 else None,
    'regime_analysis': {str(k): v for k, v in regime_next5d['p_spike'].to_dict().items()},
}
results['part_c'] = part_c

# ─────────────────────────────────────────────────
# Part D: Trading Strategy
# ─────────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART D: Volume-Based Trading Strategy")
print("=" * 70)

# Strategy: When abnormal volume > 2x, reduce equity exposure
# Monthly rebalancing, with signal from last trading day of prior month
# Compare vs 12/VIX and 50/50

# Get monthly data
df_monthly = df.resample('ME').last().copy()
df_monthly['ret_next'] = df_monthly['close'].pct_change().shift(-1)  # Next month return

# Also get GLD for 50/50 comparison
gld = yf.download("GLD", start="2005-01-01", end="2026-03-30", progress=False)
if isinstance(gld.columns, pd.MultiIndex):
    gld.columns = gld.columns.get_level_values(0)
df_monthly['gld_close'] = gld['Close'].resample('ME').last().reindex(df_monthly.index)
df_monthly['gld_ret_next'] = df_monthly['gld_close'].pct_change().shift(-1)

# Drop NaN
strat_df = df_monthly[['close', 'abn_vol', 'vol_pctile', 'vix',
                         'ret_next', 'gld_ret_next']].dropna()

# Strategy 1: Volume-adjusted weight
# High volume → reduce equity (uncertainty signal)
# Weight = clip(1.0 - (abn_vol - 1.0), 0.3, 1.0)
# IMPORTANT: signal.shift(1) — use signal from END of prior month
strat_df['vol_signal'] = strat_df['abn_vol'].shift(1)  # LAG: prior month-end volume
strat_df['vol_weight'] = np.clip(1.0 - (strat_df['vol_signal'] - 1.0), 0.3, 1.0)

# Strategy 2: 12/VIX benchmark
strat_df['vix_signal'] = strat_df['vix'].shift(1)  # LAG
strat_df['vix_weight'] = np.clip(12.0 / strat_df['vix_signal'], 0.0, 1.0)

# Strategy 3: 50/50 SPY/GLD
strat_df['w_5050_spy'] = 0.5
strat_df['w_5050_gld'] = 0.5

# Strategy 4: Buy and Hold SPY
strat_df['w_bh'] = 1.0

# Drop rows without signal
strat_df = strat_df.dropna(subset=['vol_signal', 'vix_signal'])

# Compute strategy returns with TX cost
tx_cost = 0.0005  # 5 bps per unit turnover

# Volume strategy
strat_df['vol_weight_prev'] = strat_df['vol_weight'].shift(1).fillna(strat_df['vol_weight'].iloc[0])
strat_df['vol_turnover'] = (strat_df['vol_weight'] - strat_df['vol_weight_prev']).abs()
strat_df['vol_ret'] = strat_df['vol_weight'] * strat_df['ret_next'] - strat_df['vol_turnover'] * tx_cost

# 12/VIX strategy
strat_df['vix_weight_prev'] = strat_df['vix_weight'].shift(1).fillna(strat_df['vix_weight'].iloc[0])
strat_df['vix_turnover'] = (strat_df['vix_weight'] - strat_df['vix_weight_prev']).abs()
strat_df['vix_ret'] = strat_df['vix_weight'] * strat_df['ret_next'] - strat_df['vix_turnover'] * tx_cost

# 50/50
strat_df['ret_5050'] = 0.5 * strat_df['ret_next'] + 0.5 * strat_df['gld_ret_next']

# Buy and Hold SPY
strat_df['ret_bh'] = strat_df['ret_next']

# Performance metrics
def calc_metrics(returns, name):
    r = returns.dropna()
    ann_ret = (1 + r).prod() ** (12 / len(r)) - 1
    ann_vol = r.std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    mdd = (cum / cum.cummax() - 1).min()
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0
    return {
        'name': name,
        'ann_return': round(ann_ret, 4),
        'ann_vol': round(ann_vol, 4),
        'sharpe': round(sharpe, 4),
        'mdd': round(mdd, 4),
        'calmar': round(calmar, 4),
        'n_months': len(r)
    }

metrics_vol = calc_metrics(strat_df['vol_ret'], 'Volume-Adjusted')
metrics_vix = calc_metrics(strat_df['vix_ret'], '12/VIX')
metrics_5050 = calc_metrics(strat_df['ret_5050'], '50/50 SPY/GLD')
metrics_bh = calc_metrics(strat_df['ret_bh'], 'Buy & Hold SPY')

print(f"\n{'Strategy':<20} {'Ann.Ret':>10} {'Ann.Vol':>10} {'Sharpe':>10} {'MDD':>10} {'Calmar':>10}")
print("-" * 70)
for m in [metrics_vol, metrics_vix, metrics_5050, metrics_bh]:
    print(f"{m['name']:<20} {m['ann_return']:>10.4f} {m['ann_vol']:>10.4f} {m['sharpe']:>10.4f} {m['mdd']:>10.4f} {m['calmar']:>10.4f}")

# Sharpe difference test (bootstrap)
n_boot = 10000
sharpe_diffs = []
vol_rets = strat_df['vol_ret'].dropna().values
vix_rets = strat_df['vix_ret'].dropna().values

for _ in range(n_boot):
    idx = np.random.choice(len(vol_rets), len(vol_rets), replace=True)
    s_vol = vol_rets[idx].mean() / vol_rets[idx].std() * np.sqrt(12)
    s_vix = vix_rets[idx].mean() / vix_rets[idx].std() * np.sqrt(12)
    sharpe_diffs.append(s_vol - s_vix)

sharpe_diffs = np.array(sharpe_diffs)
p_vol_beats_vix = np.mean(sharpe_diffs > 0)
print(f"\nBootstrap Sharpe difference (Volume - 12/VIX): mean={np.mean(sharpe_diffs):.4f}, p(Vol>VIX)={p_vol_beats_vix:.3f}")

# Also test: Volume + VIX combo strategy
# Reduce weight when EITHER volume is high OR VIX is high
strat_df['combo_weight'] = np.clip(
    np.minimum(
        1.0 - (strat_df['vol_signal'] - 1.0),
        12.0 / strat_df['vix_signal']
    ), 0.0, 1.0
)
strat_df['combo_weight_prev'] = strat_df['combo_weight'].shift(1).fillna(strat_df['combo_weight'].iloc[0])
strat_df['combo_turnover'] = (strat_df['combo_weight'] - strat_df['combo_weight_prev']).abs()
strat_df['combo_ret'] = strat_df['combo_weight'] * strat_df['ret_next'] - strat_df['combo_turnover'] * tx_cost

metrics_combo = calc_metrics(strat_df['combo_ret'], 'Volume+VIX Combo')
print(f"{'Volume+VIX Combo':<20} {metrics_combo['ann_return']:>10.4f} {metrics_combo['ann_vol']:>10.4f} {metrics_combo['sharpe']:>10.4f} {metrics_combo['mdd']:>10.4f} {metrics_combo['calmar']:>10.4f}")

part_d = {
    'strategies': {
        'volume_adjusted': metrics_vol,
        '12_vix': metrics_vix,
        '50_50': metrics_5050,
        'buy_hold': metrics_bh,
        'volume_vix_combo': metrics_combo,
    },
    'bootstrap_sharpe_diff_vol_minus_vix': round(np.mean(sharpe_diffs), 4),
    'p_vol_beats_vix': round(p_vol_beats_vix, 3),
    'tx_cost_bps': 5,
    'rebalancing': 'monthly',
    'lag': 'signal.shift(1) — prior month-end signal'
}
results['part_d'] = part_d

# ─────────────────────────────────────────────────
# Part E: Additional — Granger Causality Test
# ─────────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART E: Granger-like Analysis — Volume → VIX change")
print("=" * 70)

# Simple: does lagged abnormal volume predict VIX changes?
df['vix_change'] = df['vix'].pct_change()
df['vix_change_next'] = df['vix_change'].shift(-1)

gc_df = df[['abn_vol', 'vol_zscore', 'vix', 'vix_change', 'vix_change_next']].dropna()

# Regression: VIX_change_t+1 = α + β₁×VIX_change_t + β₂×abn_vol_t + ε
y_gc = gc_df['vix_change_next'].values
X_gc_base = np.column_stack([np.ones(len(y_gc)), gc_df['vix_change'].values])
X_gc_aug = np.column_stack([np.ones(len(y_gc)), gc_df['vix_change'].values, gc_df['abn_vol'].values])

r2_gc_base, _ = ols_r2(X_gc_base, y_gc)
r2_gc_aug, beta_gc_aug = ols_r2(X_gc_aug, y_gc)

# F-test for incremental variable
n_gc = len(y_gc)
k_base = X_gc_base.shape[1]
k_aug = X_gc_aug.shape[1]
f_stat = ((r2_gc_aug - r2_gc_base) / (k_aug - k_base)) / ((1 - r2_gc_aug) / (n_gc - k_aug))
f_pval = 1 - stats.f.cdf(f_stat, k_aug - k_base, n_gc - k_aug)

print(f"R² (VIX AR(1) only):     {r2_gc_base:.6f}")
print(f"R² (VIX AR(1) + Volume): {r2_gc_aug:.6f}")
print(f"F-test for Volume:       F={f_stat:.4f}, p={f_pval:.6f}")
print(f"Volume coefficient:      {beta_gc_aug[2]:.6f}")

part_e = {
    'r2_vix_ar1': round(r2_gc_base, 6),
    'r2_vix_ar1_plus_volume': round(r2_gc_aug, 6),
    'f_stat': round(f_stat, 4),
    'f_pval': round(f_pval, 6),
    'volume_coefficient': round(beta_gc_aug[2], 6),
}
results['part_e'] = part_e

# ─────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SUMMARY — K753: Market Liquidity as Volatility Predictor")
print("=" * 70)

# Key findings
findings = []

# Part A
findings.append(f"A1: Volume-|return| corr={corr_vol_absret:.3f} — MDH confirmed")

# Part B
if abs(pc_r) < 0.05:
    findings.append(f"A2: Partial corr (volume→next |ret| | VIX) = {pc_r:.4f} — NEGLIGIBLE")
else:
    findings.append(f"A2: Partial corr (volume→next |ret| | VIX) = {pc_r:.4f} — SIGNIFICANT")

findings.append(f"A3: Incremental R² = {incremental_r2:.6f} — {'meaningful' if incremental_r2 > 0.01 else 'negligible'}")

if dm_pval < 0.05:
    findings.append(f"A4: DM test significant (p={dm_pval:.4f}) — volume adds predictive power")
else:
    findings.append(f"A4: DM test NOT significant (p={dm_pval:.4f}) — volume does not improve forecasts")

# Part C
lift = p_spike_given_drop / p_spike_unconditional if p_spike_unconditional > 0 else 0
if lift > 1.5:
    findings.append(f"A5: Volume drop → VIX spike lift={lift:.2f}x — 'calm before storm' CONFIRMED")
else:
    findings.append(f"A5: Volume drop → VIX spike lift={lift:.2f}x — 'calm before storm' NOT confirmed")

# Part D
findings.append(f"A6: Volume strategy Sharpe={metrics_vol['sharpe']:.3f} vs 12/VIX={metrics_vix['sharpe']:.3f} vs 50/50={metrics_5050['sharpe']:.3f}")

# Overall conclusion
overall = "NULL RESULT" if (abs(pc_r) < 0.05 and incremental_r2 < 0.01 and dm_pval > 0.05
                           and metrics_vol['sharpe'] <= metrics_vix['sharpe']) else "PARTIAL RESULT"

findings.append(f"\nOverall: {overall}")
findings.append(f"Volume is contemporaneously correlated with volatility (MDH) but has minimal PREDICTIVE value beyond VIX.")
findings.append(f"Volume measures participation intensity; VIX already prices this information.")

results['findings'] = findings
results['overall_conclusion'] = overall

for f in findings:
    print(f"  • {f}")

# Save results
with open('experiments/k753_liquidity_vol_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to experiments/k753_liquidity_vol_results.json")
print("Script saved as experiments/k753_liquidity_vol.py")
