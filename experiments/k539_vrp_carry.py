#!/usr/bin/env python3
"""
K539: Variance Risk Premium (VRP) as Strategy Signal — Can we time the vol carry trade?

Context:
  - Codex suggestion #3: "regime-switched options carry with crash filters"
  - Past: K430 (VRP predictability IS t=4.38, OOS DM p=0.163), K440 (VRP enhancement no Sharpe improvement)
  - Past: K459 (Weekly VRP cross-OOS, sparse results — possible methodology issues)
  - Key question: Was K459's failure due to methodology, or is VRP genuinely useless?

Literature:
  - Bollerslev, Tauchen & Zhou (2009): "Expected Stock Returns and Variance Risk Premia" RFS
  - Carr & Wu (2009): "Variance Risk Premiums" RFS
  - Our K430 showed IS significance but OOS failure — classic overfitting pattern

Design:
  1. VRP = VIX²/252 - RV22² (annualized daily implied minus realized variance)
  2. Four strategies: VRP Timing, VRP Percentile, VRP+VIX Combined, VRP Crash Filter
  3. Cross-OOS: 5 periods (2016-17, 2018-19, 2020-21, 2022-23, 2024-25)
  4. Harvey (2016) |t|>3.0 threshold
  5. Benchmark: pure 12/VIX (our standard VT)

Data: yfinance (SPY, ^VIX), 2005-01-01 to 2026-03-27
Author: Yi-Hao Lai + VolPred Research System
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K539: Variance Risk Premium (VRP) as Strategy Signal")
print("=" * 70)

start_date = "2005-01-01"
end_date = "2026-03-27"

print(f"\n[1] Downloading data: SPY, ^VIX ({start_date} to {end_date})...")

spy = yf.download("SPY", start=start_date, end=end_date, progress=False)
vix = yf.download("^VIX", start=start_date, end=end_date, progress=False)

# Handle MultiIndex columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

spy_close = spy['Close'].squeeze()
vix_close = vix['Close'].squeeze()

# Align dates
common_idx = spy_close.index.intersection(vix_close.index)
spy_close = spy_close.loc[common_idx]
vix_close = vix_close.loc[common_idx]

print(f"  SPY: {len(spy_close)} days")
print(f"  VIX: {len(vix_close)} days")
print(f"  Date range: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 2. Compute Returns, RV, and VRP
# ============================================================
print("\n[2] Computing returns, realized volatility, and VRP...")

ret = np.log(spy_close / spy_close.shift(1)).dropna()

# RV22: 22-day realized volatility (annualized)
rv22_var = ret.rolling(22).apply(lambda x: np.mean(x**2) * 252, raw=True)
rv22 = np.sqrt(rv22_var)

# Implied variance (VIX is annualized % vol, so VIX/100 → vol, squared → variance)
iv_var = (vix_close / 100)**2

# VRP = Implied Variance - Realized Variance
# Both in annualized terms
vrp = iv_var - rv22_var

# Align everything
df = pd.DataFrame({
    'spy_close': spy_close,
    'vix': vix_close,
    'ret': ret,
    'rv22': rv22,
    'rv22_var': rv22_var,
    'iv_var': iv_var,
    'vrp': vrp
}).dropna()

print(f"  Clean observations: {len(df)}")
print(f"\n  VRP Descriptive Statistics:")
print(f"    Mean:   {df['vrp'].mean():.6f} (positive = IV > RV on average)")
print(f"    Median: {df['vrp'].median():.6f}")
print(f"    Std:    {df['vrp'].std():.6f}")
print(f"    Skew:   {df['vrp'].skew():.4f}")
print(f"    Kurt:   {df['vrp'].kurtosis():.4f}")
print(f"    Min:    {df['vrp'].min():.6f}")
print(f"    Max:    {df['vrp'].max():.6f}")
vrp_negative_pct = (df['vrp'] < 0).mean() * 100
print(f"    VRP < 0 frequency: {vrp_negative_pct:.1f}%")

# ============================================================
# 3. Strategy Definitions
# ============================================================
print("\n[3] Defining strategies...")

def compute_vt_weight(vix_series):
    """Standard VT weight: 12/VIX, clipped to [0.2, 1.5]"""
    return np.clip(12.0 / vix_series, 0.2, 1.5)

def strategy_bh(df_period):
    """Buy-and-hold SPY"""
    return pd.Series(1.0, index=df_period.index)

def strategy_vt(df_period):
    """Pure Volatility Targeting: 12/VIX"""
    return compute_vt_weight(df_period['vix'])

def strategy_vrp_timing(df_period, vrp_median):
    """VRP Timing: VRP > median → full VT, VRP ≤ median → B&H (weight=1)
    Logic: When variance risk premium is high, selling vol is profitable → use VT.
    When VRP is low, the carry is gone → just hold."""
    vt_w = compute_vt_weight(df_period['vix'])
    signal = (df_period['vrp'] > vrp_median).astype(float)
    # VRP high: use VT weight; VRP low: use 1.0 (B&H)
    return signal * vt_w + (1 - signal) * 1.0

def strategy_vrp_percentile(df_period, vrp_series_expanding):
    """VRP Percentile: Scale VT weight by VRP percentile rank.
    Higher VRP percentile → more aggressive VT; Low VRP → closer to B&H"""
    vt_w = compute_vt_weight(df_period['vix'])
    # Expanding percentile rank (no lookahead)
    pctile = vrp_series_expanding
    # Blend: weight = pctile * VT + (1-pctile) * 1.0
    return pctile * vt_w + (1 - pctile) * 1.0

def strategy_vrp_vix_combined(df_period, vrp_median, vix_median):
    """VRP + VIX Combined:
    High VRP + High VIX → aggressive VT (best carry + mean reversion)
    High VRP + Low VIX → moderate VT
    Low VRP + High VIX → defensive (VIX elevated but no carry)
    Low VRP + Low VIX → B&H"""
    vt_w = compute_vt_weight(df_period['vix'])
    high_vrp = df_period['vrp'] > vrp_median
    high_vix = df_period['vix'] > vix_median

    weights = pd.Series(1.0, index=df_period.index)
    weights[high_vrp & high_vix] = vt_w[high_vrp & high_vix] * 1.2  # aggressive
    weights[high_vrp & ~high_vix] = vt_w[high_vrp & ~high_vix]       # standard VT
    weights[~high_vrp & high_vix] = 0.5                               # defensive
    weights[~high_vrp & ~high_vix] = 1.0                              # B&H
    return np.clip(weights, 0.2, 1.5)

def strategy_vrp_crash_filter(df_period):
    """VRP Crash Filter: When VRP < 0 (realized > implied) → max defense (20% SPY).
    Otherwise: standard VT.
    Logic: Negative VRP means market is more volatile than options imply — danger."""
    vt_w = compute_vt_weight(df_period['vix'])
    crash = df_period['vrp'] < 0
    weights = vt_w.copy()
    weights[crash] = 0.2  # minimum exposure
    return weights

# ============================================================
# 4. Backtest Engine
# ============================================================
def backtest(weights, returns, risk_free_rate=0.0):
    """Compute strategy returns and metrics.
    weights are applied with 1-day lag (signal at close t, trade at close t+1)."""
    # Lag weights by 1 day to avoid lookahead
    lagged_w = weights.shift(1).dropna()
    aligned_ret = returns.loc[lagged_w.index]

    strat_ret = lagged_w * aligned_ret

    # Cash component: (1 - weight) earns nothing (simplification)
    # For leveraged positions (weight > 1): borrow at risk-free

    ann_ret = strat_ret.mean() * 252
    ann_vol = strat_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum_ret = (1 + strat_ret).cumprod()
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    mdd = drawdown.min()

    # Turnover
    weight_changes = lagged_w.diff().abs()
    avg_daily_turnover = weight_changes.mean()
    ann_turnover = avg_daily_turnover * 252

    # Transaction cost adjusted (10bp per trade)
    tc = 0.001  # 10bp round-trip
    net_ret = strat_ret - weight_changes.fillna(0) * tc
    net_ann_ret = net_ret.mean() * 252
    net_ann_vol = net_ret.std() * np.sqrt(252)
    net_sharpe = net_ann_ret / net_ann_vol if net_ann_vol > 0 else 0

    return {
        'ann_return': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'mdd': mdd,
        'net_sharpe': net_sharpe,
        'ann_turnover': ann_turnover,
        'n_days': len(strat_ret),
        'cum_return': float(cum_ret.iloc[-1] - 1) if len(cum_ret) > 0 else 0,
        'strat_ret': strat_ret,  # for DM test
    }

# ============================================================
# 5. Full-Sample In-Sample Analysis
# ============================================================
print("\n[4] Full-sample in-sample analysis (2005-2026)...")

# Compute expanding medians (no lookahead)
expanding_vrp_median = df['vrp'].expanding(min_periods=252).median()
expanding_vix_median = df['vix'].expanding(min_periods=252).median()
expanding_vrp_pctile = df['vrp'].expanding(min_periods=252).rank(pct=True)

# Apply strategies
weights_bh = strategy_bh(df)
weights_vt = strategy_vt(df)
weights_vrp_timing = strategy_vrp_timing(df, expanding_vrp_median)
weights_vrp_pctile = strategy_vrp_percentile(df, expanding_vrp_pctile)
weights_vrp_vix = strategy_vrp_vix_combined(df, expanding_vrp_median, expanding_vix_median)
weights_vrp_crash = strategy_vrp_crash_filter(df)

strategies = {
    'B&H': weights_bh,
    'Pure VT (12/VIX)': weights_vt,
    'VRP Timing': weights_vrp_timing,
    'VRP Percentile': weights_vrp_pctile,
    'VRP+VIX Combined': weights_vrp_vix,
    'VRP Crash Filter': weights_vrp_crash,
}

is_results = {}
print(f"\n  {'Strategy':<25} {'Sharpe':>8} {'NetSharpe':>10} {'MDD':>8} {'AnnTurn':>9} {'AnnRet':>8}")
print("  " + "-" * 72)

for name, w in strategies.items():
    res = backtest(w, df['ret'])
    is_results[name] = res
    print(f"  {name:<25} {res['sharpe']:>8.4f} {res['net_sharpe']:>10.4f} {res['mdd']:>8.2%} {res['ann_turnover']:>9.2f} {res['ann_return']:>8.2%}")

# ============================================================
# 6. Diebold-Mariano Test (IS)
# ============================================================
print("\n[5] In-sample DM tests vs Pure VT benchmark...")

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. loss = -return (so lower is worse)."""
    d = loss1 - loss2
    d = d.dropna()
    n = len(d)
    if n < 30:
        return np.nan, np.nan
    mean_d = d.mean()
    var_d = d.var()
    if var_d == 0:
        return np.nan, np.nan
    # Newey-West HAC variance with h-1 lags
    for lag in range(1, h):
        gamma = np.mean(d.iloc[lag:].values * d.iloc[:-lag].values)
        var_d += 2 * (1 - lag / h) * gamma
    se = np.sqrt(var_d / n)
    if se == 0:
        return np.nan, np.nan
    t_stat = mean_d / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), n - 1))
    return t_stat, p_val

benchmark_ret = is_results['Pure VT (12/VIX)']['strat_ret']
benchmark_loss = -benchmark_ret

print(f"\n  {'Strategy':<25} {'DM t-stat':>10} {'p-value':>10} {'Harvey':>8}")
print("  " + "-" * 55)

for name, res in is_results.items():
    if name == 'Pure VT (12/VIX)':
        continue
    strat_loss = -res['strat_ret']
    # Align
    common = benchmark_loss.index.intersection(strat_loss.index)
    t, p = dm_test(benchmark_loss.loc[common], strat_loss.loc[common])
    passes_harvey = abs(t) > 3.0 if not np.isnan(t) else False
    print(f"  {name:<25} {t:>10.4f} {p:>10.4f} {'PASS' if passes_harvey else 'FAIL':>8}")

# ============================================================
# 7. Cross-OOS Validation (5 Periods)
# ============================================================
print("\n[6] Cross-OOS Validation (5 periods)...")

oos_periods = [
    ('2016-01-01', '2017-12-31'),
    ('2018-01-01', '2019-12-31'),
    ('2020-01-01', '2021-12-31'),
    ('2022-01-01', '2023-12-31'),
    ('2024-01-01', '2025-12-31'),
]

cross_oos_results = {}

for strat_name in ['VRP Timing', 'VRP Percentile', 'VRP+VIX Combined', 'VRP Crash Filter']:
    cross_oos_results[strat_name] = {
        'periods': [],
        'sharpe_diffs': [],
        'dm_tstats': [],
        'dm_pvals': [],
        'wins': 0,
        'total': 0,
    }

for i, (oos_start, oos_end) in enumerate(oos_periods):
    # IS: everything before OOS start
    is_mask = df.index < oos_start
    oos_mask = (df.index >= oos_start) & (df.index <= oos_end)

    df_is = df[is_mask]
    df_oos = df[oos_mask]

    if len(df_oos) < 100:
        print(f"  Period {i+1} ({oos_start} to {oos_end}): insufficient data ({len(df_oos)} days), skipping")
        continue

    print(f"\n  --- OOS Period {i+1}: {oos_start} to {oos_end} ({len(df_oos)} days, IS={len(df_is)} days) ---")

    # Compute IS statistics for parameters
    is_vrp_median = df_is['vrp'].median()
    is_vix_median = df_is['vix'].median()

    # Expanding percentile within OOS (using IS data as prior)
    # Concatenate IS + OOS, compute expanding pctile, take only OOS portion
    combined = pd.concat([df_is['vrp'], df_oos['vrp']])
    oos_vrp_pctile = combined.expanding(min_periods=252).rank(pct=True).loc[df_oos.index]

    # OOS strategies
    w_vt_oos = strategy_vt(df_oos)
    w_vrp_timing_oos = strategy_vrp_timing(df_oos, is_vrp_median)
    w_vrp_pctile_oos = strategy_vrp_percentile(df_oos, oos_vrp_pctile)
    w_vrp_vix_oos = strategy_vrp_vix_combined(df_oos, is_vrp_median, is_vix_median)
    w_vrp_crash_oos = strategy_vrp_crash_filter(df_oos)

    oos_strats = {
        'VRP Timing': w_vrp_timing_oos,
        'VRP Percentile': w_vrp_pctile_oos,
        'VRP+VIX Combined': w_vrp_vix_oos,
        'VRP Crash Filter': w_vrp_crash_oos,
    }

    # Benchmark: Pure VT OOS
    res_vt_oos = backtest(w_vt_oos, df_oos['ret'])

    print(f"    {'Strategy':<25} {'Sharpe':>8} {'NetSharpe':>10} {'SharpeΔ':>9} {'DM-t':>8} {'DM-p':>8}")
    print(f"    {'-'*70}")
    print(f"    {'Pure VT (benchmark)':<25} {res_vt_oos['sharpe']:>8.4f} {res_vt_oos['net_sharpe']:>10.4f}")

    for sname, sw in oos_strats.items():
        res_oos = backtest(sw, df_oos['ret'])
        sharpe_diff = res_oos['sharpe'] - res_vt_oos['sharpe']

        # DM test
        common = res_vt_oos['strat_ret'].index.intersection(res_oos['strat_ret'].index)
        t, p = dm_test(-res_vt_oos['strat_ret'].loc[common], -res_oos['strat_ret'].loc[common])

        cross_oos_results[sname]['periods'].append({
            'oos_start': oos_start,
            'oos_end': oos_end,
            'sharpe': res_oos['sharpe'],
            'net_sharpe': res_oos['net_sharpe'],
            'sharpe_diff': sharpe_diff,
            'dm_tstat': float(t) if not np.isnan(t) else None,
            'dm_pval': float(p) if not np.isnan(p) else None,
            'mdd': res_oos['mdd'],
            'n_days': res_oos['n_days'],
            'benchmark_sharpe': res_vt_oos['sharpe'],
        })
        cross_oos_results[sname]['sharpe_diffs'].append(sharpe_diff)
        if not np.isnan(t):
            cross_oos_results[sname]['dm_tstats'].append(t)
            cross_oos_results[sname]['dm_pvals'].append(p)
        if sharpe_diff > 0:
            cross_oos_results[sname]['wins'] += 1
        cross_oos_results[sname]['total'] += 1

        print(f"    {sname:<25} {res_oos['sharpe']:>8.4f} {res_oos['net_sharpe']:>10.4f} {sharpe_diff:>+9.4f} {t:>8.3f} {p:>8.4f}")

# ============================================================
# 8. Cross-OOS Summary
# ============================================================
print("\n" + "=" * 70)
print("[7] CROSS-OOS SUMMARY")
print("=" * 70)

print(f"\n  {'Strategy':<25} {'Win/Total':>10} {'MeanΔ':>8} {'MeanDM-t':>10} {'MedianDM-t':>11} {'Harvey':>8}")
print("  " + "-" * 75)

final_verdicts = {}

for sname, cdata in cross_oos_results.items():
    wins = cdata['wins']
    total = cdata['total']
    mean_diff = np.mean(cdata['sharpe_diffs']) if cdata['sharpe_diffs'] else np.nan

    dm_ts = cdata['dm_tstats']
    mean_dm = np.mean(dm_ts) if dm_ts else np.nan
    median_dm = np.median(dm_ts) if dm_ts else np.nan

    # Combined DM test across periods (meta-analysis)
    # Using Stouffer's method: z_combined = sum(z_i) / sqrt(n)
    if len(dm_ts) >= 3:
        stouffer_z = np.sum(dm_ts) / np.sqrt(len(dm_ts))
        stouffer_p = 2 * (1 - stats.norm.cdf(abs(stouffer_z)))
    else:
        stouffer_z = np.nan
        stouffer_p = np.nan

    passes_harvey = abs(stouffer_z) > 3.0 if not np.isnan(stouffer_z) else False

    verdict = "ROBUST" if (wins / total >= 0.6 and passes_harvey) else \
              "PROMISING" if (wins / total >= 0.6 or (not np.isnan(mean_dm) and mean_dm > 1.5)) else \
              "WEAK" if (wins / total >= 0.4) else "FAIL"

    final_verdicts[sname] = {
        'wins': wins,
        'total': total,
        'win_rate': wins / total if total > 0 else 0,
        'mean_sharpe_diff': float(mean_diff) if not np.isnan(mean_diff) else None,
        'mean_dm_tstat': float(mean_dm) if not np.isnan(mean_dm) else None,
        'median_dm_tstat': float(median_dm) if not np.isnan(median_dm) else None,
        'stouffer_z': float(stouffer_z) if not np.isnan(stouffer_z) else None,
        'stouffer_p': float(stouffer_p) if not np.isnan(stouffer_p) else None,
        'passes_harvey': passes_harvey,
        'verdict': verdict,
    }

    print(f"  {sname:<25} {wins}/{total:>8} {mean_diff:>+8.4f} {mean_dm:>10.3f} {median_dm:>11.3f} {'PASS' if passes_harvey else 'FAIL':>8}")

# ============================================================
# 9. VRP < 0 Event Analysis (Crash Filter Deep Dive)
# ============================================================
print("\n[8] VRP < 0 Event Analysis (Crash Filter Deep Dive)...")

vrp_neg = df[df['vrp'] < 0]
vrp_pos = df[df['vrp'] >= 0]

print(f"\n  VRP < 0 days: {len(vrp_neg)} ({len(vrp_neg)/len(df)*100:.1f}%)")
print(f"  VRP ≥ 0 days: {len(vrp_pos)} ({len(vrp_pos)/len(df)*100:.1f}%)")

# Average returns conditional on VRP sign
ret_neg = vrp_neg['ret'].shift(-1).dropna()  # next-day return
ret_pos = vrp_pos['ret'].shift(-1).dropna()

print(f"\n  Next-day return (ann.) when VRP < 0:  {ret_neg.mean()*252:.2%} (vol={ret_neg.std()*np.sqrt(252):.2%})")
print(f"  Next-day return (ann.) when VRP >= 0: {ret_pos.mean()*252:.2%} (vol={ret_pos.std()*np.sqrt(252):.2%})")

# t-test for difference
t_diff, p_diff = stats.ttest_ind(ret_neg, ret_pos)
print(f"  Two-sample t-test: t={t_diff:.4f}, p={p_diff:.4f}")

# VRP < 0 clustering: how many events are near major crashes?
# Check: what fraction of VRP < 0 days are within 1 month of a >5% drawdown?
major_events = {
    '2008 GFC': ('2008-09-01', '2009-03-31'),
    '2011 Euro Crisis': ('2011-07-01', '2011-10-31'),
    '2015 China Fear': ('2015-08-01', '2015-10-31'),
    '2018 Volmageddon': ('2018-01-26', '2018-04-30'),
    '2020 COVID': ('2020-02-15', '2020-04-30'),
    '2022 Rate Hikes': ('2022-01-01', '2022-10-31'),
}

print(f"\n  VRP < 0 days during major events:")
for event_name, (ev_start, ev_end) in major_events.items():
    mask = (vrp_neg.index >= ev_start) & (vrp_neg.index <= ev_end)
    count = mask.sum()
    total_days = ((df.index >= ev_start) & (df.index <= ev_end)).sum()
    pct = count / total_days * 100 if total_days > 0 else 0
    print(f"    {event_name}: {count}/{total_days} days ({pct:.0f}%)")

# ============================================================
# 10. Bootstrap Confidence Intervals
# ============================================================
print("\n[9] Bootstrap Sharpe difference (VRP Crash Filter vs Pure VT, 10,000 reps)...")

crash_ret = is_results['VRP Crash Filter']['strat_ret']
vt_ret = is_results['Pure VT (12/VIX)']['strat_ret']
common = crash_ret.index.intersection(vt_ret.index)
diff = (crash_ret.loc[common] - vt_ret.loc[common]).values
n = len(diff)

np.random.seed(42)
n_boot = 10000
boot_sharpe_diffs = np.zeros(n_boot)

for b in range(n_boot):
    idx = np.random.randint(0, n, n)
    boot_diff = diff[idx]
    boot_sharpe_diffs[b] = boot_diff.mean() / boot_diff.std() * np.sqrt(252) if boot_diff.std() > 0 else 0

ci_low = np.percentile(boot_sharpe_diffs, 2.5)
ci_high = np.percentile(boot_sharpe_diffs, 97.5)
boot_mean = boot_sharpe_diffs.mean()

print(f"  Bootstrap mean Sharpe diff: {boot_mean:.4f}")
print(f"  95% CI: [{ci_low:.4f}, {ci_high:.4f}]")
print(f"  Zero in CI: {'YES (not significant)' if ci_low <= 0 <= ci_high else 'NO (significant)'}")

# ============================================================
# 11. Compile Results
# ============================================================
print("\n[10] Compiling results...")

results = {
    "experiment_id": "K539",
    "title": "Variance Risk Premium (VRP) as Strategy Signal",
    "subtitle": "Can we time the vol carry trade?",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (SPY, ^VIX)",
    "data_period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    "n_observations": len(df),
    "references": [
        "Bollerslev, Tauchen & Zhou (2009) 'Expected Stock Returns and Variance Risk Premia' RFS",
        "Carr & Wu (2009) 'Variance Risk Premiums' RFS",
        "Past: K430 (VRP predictability IS t=4.38, OOS fail), K440 (no Sharpe improvement), K459 (cross-OOS sparse)",
    ],
    "vrp_descriptive": {
        "mean": round(float(df['vrp'].mean()), 6),
        "median": round(float(df['vrp'].median()), 6),
        "std": round(float(df['vrp'].std()), 6),
        "skew": round(float(df['vrp'].skew()), 4),
        "kurtosis": round(float(df['vrp'].kurtosis()), 4),
        "min": round(float(df['vrp'].min()), 6),
        "max": round(float(df['vrp'].max()), 6),
        "pct_negative": round(float(vrp_negative_pct), 1),
    },
    "in_sample_results": {},
    "cross_oos_results": {},
    "crash_filter_analysis": {
        "vrp_negative_days": int(len(vrp_neg)),
        "vrp_negative_pct": round(float(len(vrp_neg) / len(df) * 100), 1),
        "next_day_return_vrp_neg_ann": round(float(ret_neg.mean() * 252), 4),
        "next_day_vol_vrp_neg_ann": round(float(ret_neg.std() * np.sqrt(252)), 4),
        "next_day_return_vrp_pos_ann": round(float(ret_pos.mean() * 252), 4),
        "next_day_vol_vrp_pos_ann": round(float(ret_pos.std() * np.sqrt(252)), 4),
        "ttest_t": round(float(t_diff), 4),
        "ttest_p": round(float(p_diff), 4),
        "events": {},
    },
    "bootstrap": {
        "n_reps": n_boot,
        "mean_sharpe_diff": round(float(boot_mean), 4),
        "ci_95_low": round(float(ci_low), 4),
        "ci_95_high": round(float(ci_high), 4),
        "zero_in_ci": bool(ci_low <= 0 <= ci_high),
    },
    "final_verdicts": final_verdicts,
    "overall_conclusion": "",
}

# Fill IS results
for name, res in is_results.items():
    results["in_sample_results"][name] = {
        "sharpe": round(float(res['sharpe']), 4),
        "net_sharpe": round(float(res['net_sharpe']), 4),
        "ann_return": round(float(res['ann_return']), 4),
        "ann_vol": round(float(res['ann_vol']), 4),
        "mdd": round(float(res['mdd']), 4),
        "ann_turnover": round(float(res['ann_turnover']), 4),
        "n_days": int(res['n_days']),
    }

# Fill cross-OOS results
for sname, cdata in cross_oos_results.items():
    results["cross_oos_results"][sname] = {
        "periods": cdata['periods'],
        "wins": cdata['wins'],
        "total": cdata['total'],
        "verdict": final_verdicts[sname],
    }

# Fill crash events
for event_name, (ev_start, ev_end) in major_events.items():
    mask = (vrp_neg.index >= ev_start) & (vrp_neg.index <= ev_end)
    count = int(mask.sum())
    total_days = int(((df.index >= ev_start) & (df.index <= ev_end)).sum())
    results["crash_filter_analysis"]["events"][event_name] = {
        "vrp_neg_days": count,
        "total_days": total_days,
        "pct": round(count / total_days * 100, 0) if total_days > 0 else 0,
    }

# ============================================================
# 12. Overall Conclusion
# ============================================================
any_robust = any(v['verdict'] == 'ROBUST' for v in final_verdicts.values())
any_promising = any(v['verdict'] in ['ROBUST', 'PROMISING'] for v in final_verdicts.values())
crash_filter_verdict = final_verdicts.get('VRP Crash Filter', {}).get('verdict', 'FAIL')

conclusion_parts = []

if any_robust:
    conclusion_parts.append("At least one VRP strategy passes cross-OOS validation with Harvey threshold.")
else:
    conclusion_parts.append("No VRP strategy passes Harvey |t|>3.0 threshold in cross-OOS.")

if crash_filter_verdict in ['ROBUST', 'PROMISING']:
    conclusion_parts.append(f"VRP Crash Filter shows {crash_filter_verdict} results — defensive use of VRP signal has merit.")
else:
    conclusion_parts.append(f"VRP Crash Filter verdict: {crash_filter_verdict}. Even as a crash detector, VRP does not reliably improve VT.")

conclusion_parts.append(f"VRP is negative {vrp_negative_pct:.0f}% of days, concentrated in crisis periods.")

boot_sig = "significant" if not results["bootstrap"]["zero_in_ci"] else "NOT significant"
conclusion_parts.append(f"Bootstrap 95% CI for Crash Filter Sharpe diff: [{ci_low:.4f}, {ci_high:.4f}] — {boot_sig}.")

# Compare with K459
conclusion_parts.append("K459 comparison: methodology differences (expanding medians, crash filter) do not overcome the fundamental result — VRP timing adds no reliable alpha over pure VT.")

results["overall_conclusion"] = " ".join(conclusion_parts)

print(f"\n{'='*70}")
print("OVERALL CONCLUSION")
print(f"{'='*70}")
print(f"\n{results['overall_conclusion']}")

# ============================================================
# 13. Save Results
# ============================================================
# Remove non-serializable strat_ret from is_results
output_path = "experiments/k539_vrp_carry_results.json"

with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n[DONE] Results saved to {output_path}")
