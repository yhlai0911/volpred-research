"""
K440: VRP-Enhanced Volatility Targeting Strategy
=================================================

Research question: Can VRP (Volatility Risk Premium) signal improve standard
12/VIX volatility targeting, exploiting the behavioral asymmetry discovered
in K430 (low VRP → vol decline 92%, high VRP → vol increase 84%)?

Literature:
- Bollerslev, Tauchen, Zhou (2009) RFS: VRP predicts returns and vol
- Moreira & Muir (2017) JoF 72(4):1611-1644: Volatility-Managed Portfolios
- K430: Extreme VRP behavioral asymmetry confirmed
- K436: VRP predictive power robust (DM p=0.018 non-overlapping, bootstrap p=0.000)

Strategies compared:
1. Buy-and-hold SPY
2. Standard 12/VIX VT
3. VRP-discrete VT (threshold-based)
4. VRP-continuous VT (z-score-based)
5. 50/50 SPY/GLD + 12/VIX VT
6. 50/50 SPY/GLD + VRP-enhanced VT

Data: yfinance (SPY, ^VIX, GLD)
IS: 2006-2022 (with 252-day warmup for VRP percentile)
OOS: 2023-01-01 ~ 2025-12-31
Cross-OOS: 5 sub-period bootstrap

Author: VolPred Research System
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats

warnings.filterwarnings('ignore')

# =============================================================================
# 1. DATA COLLECTION
# =============================================================================
print("=" * 70)
print("K440: VRP-Enhanced Volatility Targeting Strategy")
print("=" * 70)

# Download data
print("\n[1/7] Downloading data from yfinance...")
spy = yf.download('SPY', start='2005-01-01', end='2026-01-01', progress=False)
vix = yf.download('^VIX', start='2005-01-01', end='2026-01-01', progress=False)
gld = yf.download('GLD', start='2005-01-01', end='2026-01-01', progress=False)

# Handle multi-level columns
for df_name, df in [('SPY', spy), ('VIX', vix), ('GLD', gld)]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Align dates
common_idx = spy.index.intersection(vix.index).intersection(gld.index)
spy = spy.loc[common_idx]
vix = vix.loc[common_idx]
gld = gld.loc[common_idx]

print(f"  SPY: {spy.index[0].date()} to {spy.index[-1].date()} ({len(spy)} obs)")
print(f"  VIX: {vix.index[0].date()} to {vix.index[-1].date()} ({len(vix)} obs)")
print(f"  GLD: {gld.index[0].date()} to {gld.index[-1].date()} ({len(gld)} obs)")

# Compute returns and realized vol
spy_ret = spy['Close'].pct_change()
gld_ret = gld['Close'].pct_change()
vix_close = vix['Close']

# 21-day realized volatility (annualized)
rv_21 = spy_ret.rolling(21).std() * np.sqrt(252) * 100  # in % to match VIX

# VRP = VIX - RV_21
vrp = vix_close - rv_21

# VRP percentile rank (rolling 252 days)
vrp_pct = vrp.rolling(252).rank(pct=True)

# VRP z-score (rolling 252 days)
vrp_mean = vrp.rolling(252).mean()
vrp_std = vrp.rolling(252).std()
vrp_z = (vrp - vrp_mean) / vrp_std

# Drop NaN (need 252 warmup)
valid_idx = vrp_pct.dropna().index
spy_ret = spy_ret.loc[valid_idx]
gld_ret = gld_ret.loc[valid_idx]
vix_close = vix_close.loc[valid_idx]
rv_21 = rv_21.loc[valid_idx]
vrp = vrp.loc[valid_idx]
vrp_pct = vrp_pct.loc[valid_idx]
vrp_z = vrp_z.loc[valid_idx]

print(f"\n  After warmup: {valid_idx[0].date()} to {valid_idx[-1].date()} ({len(valid_idx)} obs)")

# =============================================================================
# 2. DESCRIPTIVE STATISTICS & DIAGNOSTICS
# =============================================================================
print("\n[2/7] Descriptive statistics & diagnostics...")

def compute_desc_stats(series, name):
    s = series.dropna()
    return {
        'name': name,
        'N': len(s),
        'mean': float(s.mean()),
        'std': float(s.std()),
        'skew': float(s.skew()),
        'kurtosis': float(s.kurtosis()),
        'min': float(s.min()),
        'p10': float(s.quantile(0.10)),
        'p25': float(s.quantile(0.25)),
        'median': float(s.median()),
        'p75': float(s.quantile(0.75)),
        'p90': float(s.quantile(0.90)),
        'max': float(s.max()),
    }

desc_stats = {
    'spy_ret': compute_desc_stats(spy_ret * 100, 'SPY Daily Return (%)'),
    'gld_ret': compute_desc_stats(gld_ret * 100, 'GLD Daily Return (%)'),
    'vix': compute_desc_stats(vix_close, 'VIX Close'),
    'rv_21': compute_desc_stats(rv_21, 'RV_21 (ann %)'),
    'vrp': compute_desc_stats(vrp, 'VRP (VIX - RV_21)'),
    'vrp_pct': compute_desc_stats(vrp_pct, 'VRP Percentile (rolling 252)'),
    'vrp_z': compute_desc_stats(vrp_z, 'VRP Z-score (rolling 252)'),
}

for k, v in desc_stats.items():
    print(f"  {v['name']}: mean={v['mean']:.3f}, std={v['std']:.3f}, "
          f"skew={v['skew']:.3f}, kurt={v['kurtosis']:.3f}, N={v['N']}")

# ADF test on VRP
from statsmodels.tsa.stattools import adfuller
adf_result = adfuller(vrp.dropna(), maxlag=21)
print(f"\n  ADF test on VRP: stat={adf_result[0]:.4f}, p={adf_result[1]:.2e}, "
      f"stationary={'Yes' if adf_result[1] < 0.05 else 'No'}")

# Ljung-Box test on VRP
from statsmodels.stats.diagnostic import acorr_ljungbox
lb_result = acorr_ljungbox(vrp.dropna(), lags=[10], return_df=True)
lb_stat = float(lb_result['lb_stat'].values[0])
lb_pval = float(lb_result['lb_pvalue'].values[0])
print(f"  Ljung-Box(10) on VRP: stat={lb_stat:.2f}, p={lb_pval:.4f}")

# =============================================================================
# 3. STRATEGY DEFINITIONS
# =============================================================================
print("\n[3/7] Computing strategy weights...")

# Risk-free rate proxy (3-month T-bill, ~5% recent, ~2% historical avg)
rf_daily = 0.02 / 252  # conservative 2% annual

# --- Strategy 1: Buy & Hold SPY ---
w_bh = pd.Series(1.0, index=valid_idx)

# --- Strategy 2: Standard 12/VIX VT ---
target_vol = 12.0
w_vt = (target_vol / vix_close).clip(upper=1.5)  # cap at 150%

# --- Strategy 3: VRP-Discrete VT ---
# From K430: Low VRP (<P10) → vol decline 92% → increase exposure
#            High VRP (>P90) → vol increase 84% → decrease exposure
def vrp_discrete_adjustment(pct_val):
    if pd.isna(pct_val):
        return 1.0
    if pct_val < 0.10:  # low VRP = post-shock, vol will decline
        return 1.3  # increase exposure 30%
    elif pct_val > 0.90:  # high VRP = fear, vol will increase
        return 0.7  # decrease exposure 30%
    else:
        return 1.0  # no adjustment

vrp_disc_adj = vrp_pct.apply(vrp_discrete_adjustment)
w_vrp_disc = (w_vt * vrp_disc_adj).clip(upper=1.5)

# --- Strategy 4: VRP-Continuous VT ---
# Linear adjustment based on VRP z-score
# Reduce when VRP high (vol will increase), increase when low (vol will decline)
vrp_cont_adj = (1.0 - 0.15 * vrp_z).clip(0.5, 1.5)
w_vrp_cont = (w_vt * vrp_cont_adj).clip(upper=1.5)

# --- Strategy 5: 50/50 SPY/GLD + 12/VIX VT ---
# Weight allocated to risky portfolio (50/50 SPY/GLD)
blend_ret = 0.5 * spy_ret + 0.5 * gld_ret
w_blend_vt = w_vt.copy()  # same VT weight applied to the blend

# --- Strategy 6: 50/50 SPY/GLD + VRP-enhanced VT ---
# Use continuous VRP adjustment on the blend (more robust than discrete)
w_blend_vrp = (w_vt * vrp_cont_adj).clip(upper=1.5)

# Compute daily strategy returns
strat_returns = pd.DataFrame(index=valid_idx)
strat_returns['BH_SPY'] = spy_ret
strat_returns['VT_12VIX'] = w_vt.shift(1) * spy_ret + (1 - w_vt.shift(1)) * rf_daily
strat_returns['VRP_Discrete_VT'] = w_vrp_disc.shift(1) * spy_ret + (1 - w_vrp_disc.shift(1)) * rf_daily
strat_returns['VRP_Continuous_VT'] = w_vrp_cont.shift(1) * spy_ret + (1 - w_vrp_cont.shift(1)) * rf_daily
strat_returns['Blend_VT'] = w_blend_vt.shift(1) * blend_ret + (1 - w_blend_vt.shift(1)) * rf_daily
strat_returns['Blend_VRP_VT'] = w_blend_vrp.shift(1) * blend_ret + (1 - w_blend_vrp.shift(1)) * rf_daily
strat_returns = strat_returns.dropna()

print(f"  Strategy returns computed: {strat_returns.index[0].date()} to {strat_returns.index[-1].date()}")
print(f"  Total observations: {len(strat_returns)}")

# Weight statistics
weight_stats = {}
for name, w in [('VT_12VIX', w_vt), ('VRP_Discrete_VT', w_vrp_disc),
                ('VRP_Continuous_VT', w_vrp_cont), ('Blend_VT', w_blend_vt),
                ('Blend_VRP_VT', w_blend_vrp)]:
    w_valid = w.loc[strat_returns.index]
    weight_stats[name] = {
        'mean': float(w_valid.mean()),
        'std': float(w_valid.std()),
        'min': float(w_valid.min()),
        'max': float(w_valid.max()),
        'pct_at_cap': float((w_valid >= 1.49).mean() * 100),
    }
    print(f"  {name}: mean_w={w_valid.mean():.3f}, std_w={w_valid.std():.3f}, "
          f"at_cap={weight_stats[name]['pct_at_cap']:.1f}%")

# =============================================================================
# 4. TURNOVER ANALYSIS
# =============================================================================
print("\n[4/7] Turnover analysis...")

turnover_stats = {}
for name, w in [('VT_12VIX', w_vt), ('VRP_Discrete_VT', w_vrp_disc),
                ('VRP_Continuous_VT', w_vrp_cont), ('Blend_VT', w_blend_vt),
                ('Blend_VRP_VT', w_blend_vrp)]:
    w_valid = w.loc[strat_returns.index]
    daily_turnover = w_valid.diff().abs()
    ann_turnover = daily_turnover.mean() * 252
    turnover_stats[name] = {
        'daily_mean_turnover': float(daily_turnover.mean()),
        'annual_turnover': float(ann_turnover),
    }
    print(f"  {name}: annual_turnover={ann_turnover:.2f}")

# =============================================================================
# 5. PERFORMANCE EVALUATION (Full, IS, OOS)
# =============================================================================
print("\n[5/7] Performance evaluation...")

def evaluate_performance(returns_df, rf_annual=0.02, tx_cost_bps=10):
    """Compute standard performance metrics."""
    results = {}
    for col in returns_df.columns:
        r = returns_df[col].dropna()
        n = len(r)
        ann_ret = r.mean() * 252
        ann_vol = r.std() * np.sqrt(252)
        sharpe = (ann_ret - rf_annual) / ann_vol if ann_vol > 0 else 0

        # Sortino
        downside = r[r < 0]
        downside_vol = downside.std() * np.sqrt(252)
        sortino = (ann_ret - rf_annual) / downside_vol if downside_vol > 0 else 0

        # Max drawdown
        cum = (1 + r).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        max_dd = dd.min()

        # Calmar
        calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

        # Net Sharpe (after TX costs, monthly rebalancing = ~12 tx/year)
        # Estimate turnover for non-BH strategies
        annual_tx_cost = tx_cost_bps / 10000 * 12  # rough: 12 rebalances/yr
        net_sharpe = ((ann_ret - rf_annual) - annual_tx_cost) / ann_vol if ann_vol > 0 else 0

        results[col] = {
            'n_obs': n,
            'ann_return': float(ann_ret),
            'ann_volatility': float(ann_vol),
            'sharpe': float(sharpe),
            'sortino': float(sortino),
            'max_drawdown': float(max_dd),
            'calmar': float(calmar),
            'net_sharpe': float(net_sharpe),
            'skewness': float(r.skew()),
            'kurtosis': float(r.kurtosis()),
        }
    return results

# Split IS/OOS
oos_start = '2023-01-01'
is_mask = strat_returns.index < oos_start
oos_mask = strat_returns.index >= oos_start

is_returns = strat_returns[is_mask]
oos_returns = strat_returns[oos_mask]

print(f"  IS: {is_returns.index[0].date()} to {is_returns.index[-1].date()} ({len(is_returns)} obs)")
print(f"  OOS: {oos_returns.index[0].date()} to {oos_returns.index[-1].date()} ({len(oos_returns)} obs)")

full_perf = evaluate_performance(strat_returns)
is_perf = evaluate_performance(is_returns)
oos_perf = evaluate_performance(oos_returns)

print("\n  === FULL PERIOD ===")
print(f"  {'Strategy':<22} {'Sharpe':>8} {'Return':>8} {'Vol':>8} {'MaxDD':>8} {'Calmar':>8} {'Sortino':>8}")
print(f"  {'-'*70}")
for col in strat_returns.columns:
    p = full_perf[col]
    print(f"  {col:<22} {p['sharpe']:>8.3f} {p['ann_return']:>7.1%} {p['ann_volatility']:>7.1%} "
          f"{p['max_drawdown']:>7.1%} {p['calmar']:>8.3f} {p['sortino']:>8.3f}")

print("\n  === IN-SAMPLE ===")
print(f"  {'Strategy':<22} {'Sharpe':>8} {'Return':>8} {'Vol':>8} {'MaxDD':>8}")
print(f"  {'-'*55}")
for col in strat_returns.columns:
    p = is_perf[col]
    print(f"  {col:<22} {p['sharpe']:>8.3f} {p['ann_return']:>7.1%} {p['ann_volatility']:>7.1%} "
          f"{p['max_drawdown']:>7.1%}")

print("\n  === OUT-OF-SAMPLE ===")
print(f"  {'Strategy':<22} {'Sharpe':>8} {'Return':>8} {'Vol':>8} {'MaxDD':>8}")
print(f"  {'-'*55}")
for col in strat_returns.columns:
    p = oos_perf[col]
    print(f"  {col:<22} {p['sharpe']:>8.3f} {p['ann_return']:>7.1%} {p['ann_volatility']:>7.1%} "
          f"{p['max_drawdown']:>7.1%}")

# =============================================================================
# 6. STATISTICAL TESTS
# =============================================================================
print("\n[6/7] Statistical tests...")

def diebold_mariano_returns(r1, r2, h=1):
    """DM test for return differences (two-sided)."""
    d = r1 - r2
    d_mean = d.mean()
    d_var = d.var()
    n = len(d)
    # Newey-West with h-1 lags
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        d_var += 2 * (1 - k / h) * gamma_k
    dm_stat = d_mean / np.sqrt(d_var / n)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_value)

def sharpe_difference_test(r1, r2, n):
    """Jobson-Korkie test for Sharpe ratio difference (approx)."""
    mu1, mu2 = r1.mean(), r2.mean()
    s1, s2 = r1.std(), r2.std()
    sr1, sr2 = mu1 / s1, mu2 / s2
    rho = np.corrcoef(r1, r2)[0, 1]
    # Ledoit-Wolf (2008) approx SE
    se = np.sqrt((1/n) * (2 * (1 - rho) + 0.5 * (sr1**2 + sr2**2 - 2*sr1*sr2*rho)))
    t_stat = (sr1 - sr2) / se if se > 0 else 0
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_value), float(sr1 - sr2)

# DM tests: each VRP strategy vs its baseline
dm_tests = {}

# VRP Discrete vs Standard VT
dm_stat, dm_p = diebold_mariano_returns(
    strat_returns['VRP_Discrete_VT'].values,
    strat_returns['VT_12VIX'].values
)
dm_tests['VRP_Discrete_vs_VT'] = {
    'dm_stat': dm_stat, 'p_value': dm_p,
    'significant_5pct': dm_p < 0.05,
    'harvey_significant': abs(dm_stat) > 3.0,
}

# VRP Continuous vs Standard VT
dm_stat, dm_p = diebold_mariano_returns(
    strat_returns['VRP_Continuous_VT'].values,
    strat_returns['VT_12VIX'].values
)
dm_tests['VRP_Continuous_vs_VT'] = {
    'dm_stat': dm_stat, 'p_value': dm_p,
    'significant_5pct': dm_p < 0.05,
    'harvey_significant': abs(dm_stat) > 3.0,
}

# Blend VRP vs Blend VT
dm_stat, dm_p = diebold_mariano_returns(
    strat_returns['Blend_VRP_VT'].values,
    strat_returns['Blend_VT'].values
)
dm_tests['Blend_VRP_vs_Blend_VT'] = {
    'dm_stat': dm_stat, 'p_value': dm_p,
    'significant_5pct': dm_p < 0.05,
    'harvey_significant': abs(dm_stat) > 3.0,
}

# OOS-only DM tests
dm_tests_oos = {}
for name_pair, (s1, s2) in [
    ('VRP_Discrete_vs_VT', ('VRP_Discrete_VT', 'VT_12VIX')),
    ('VRP_Continuous_vs_VT', ('VRP_Continuous_VT', 'VT_12VIX')),
    ('Blend_VRP_vs_Blend_VT', ('Blend_VRP_VT', 'Blend_VT')),
]:
    r1 = oos_returns[s1].values
    r2 = oos_returns[s2].values
    dm_stat, dm_p = diebold_mariano_returns(r1, r2)
    dm_tests_oos[name_pair] = {
        'dm_stat': dm_stat, 'p_value': dm_p,
        'significant_5pct': dm_p < 0.05,
        'harvey_significant': abs(dm_stat) > 3.0,
    }

# Sharpe difference tests (full period)
sharpe_tests = {}
for name_pair, (s1, s2) in [
    ('VRP_Discrete_vs_VT', ('VRP_Discrete_VT', 'VT_12VIX')),
    ('VRP_Continuous_vs_VT', ('VRP_Continuous_VT', 'VT_12VIX')),
    ('Blend_VRP_vs_Blend_VT', ('Blend_VRP_VT', 'Blend_VT')),
]:
    t_stat, p_val, sr_diff = sharpe_difference_test(
        strat_returns[s1].values, strat_returns[s2].values, len(strat_returns)
    )
    sharpe_tests[name_pair] = {
        't_stat': t_stat, 'p_value': p_val,
        'sharpe_diff': sr_diff,
        'significant_5pct': p_val < 0.05,
        'harvey_significant': abs(t_stat) > 3.0,
    }

print("\n  === DM TESTS (Full Period) ===")
for name, t in dm_tests.items():
    print(f"  {name}: DM={t['dm_stat']:.4f}, p={t['p_value']:.4f}, "
          f"sig_5%={t['significant_5pct']}, Harvey(|t|>3)={t['harvey_significant']}")

print("\n  === DM TESTS (OOS Only) ===")
for name, t in dm_tests_oos.items():
    print(f"  {name}: DM={t['dm_stat']:.4f}, p={t['p_value']:.4f}, "
          f"sig_5%={t['significant_5pct']}, Harvey(|t|>3)={t['harvey_significant']}")

print("\n  === SHARPE DIFFERENCE TESTS (Full Period) ===")
for name, t in sharpe_tests.items():
    print(f"  {name}: t={t['t_stat']:.4f}, p={t['p_value']:.4f}, "
          f"SR_diff={t['sharpe_diff']:.4f}, Harvey(|t|>3)={t['harvey_significant']}")

# =============================================================================
# 7. CROSS-OOS BOOTSTRAP (5 sub-periods)
# =============================================================================
print("\n[7/7] Cross-OOS bootstrap validation...")

# Define 5 rolling OOS windows (each ~2 years IS, ~1 year OOS)
cross_oos_periods = [
    ('2010-01-01', '2014-12-31', '2015-01-01', '2016-12-31'),
    ('2012-01-01', '2016-12-31', '2017-01-01', '2018-12-31'),
    ('2014-01-01', '2018-12-31', '2019-01-01', '2020-12-31'),
    ('2016-01-01', '2020-12-31', '2021-01-01', '2022-12-31'),
    ('2018-01-01', '2022-12-31', '2023-01-01', '2025-12-31'),
]

cross_oos_results = []
for is_start, is_end, oos_start_p, oos_end_p in cross_oos_periods:
    oos_mask_p = (strat_returns.index >= oos_start_p) & (strat_returns.index <= oos_end_p)
    oos_r = strat_returns[oos_mask_p]

    if len(oos_r) < 50:
        continue

    period_perf = evaluate_performance(oos_r)
    cross_oos_results.append({
        'oos_period': f"{oos_start_p} to {oos_end_p}",
        'n_obs': len(oos_r),
        'BH_SPY_sharpe': period_perf['BH_SPY']['sharpe'],
        'VT_12VIX_sharpe': period_perf['VT_12VIX']['sharpe'],
        'VRP_Discrete_sharpe': period_perf['VRP_Discrete_VT']['sharpe'],
        'VRP_Continuous_sharpe': period_perf['VRP_Continuous_VT']['sharpe'],
        'Blend_VT_sharpe': period_perf['Blend_VT']['sharpe'],
        'Blend_VRP_sharpe': period_perf['Blend_VRP_VT']['sharpe'],
        'VRP_disc_beats_VT': period_perf['VRP_Discrete_VT']['sharpe'] > period_perf['VT_12VIX']['sharpe'],
        'VRP_cont_beats_VT': period_perf['VRP_Continuous_VT']['sharpe'] > period_perf['VT_12VIX']['sharpe'],
        'Blend_VRP_beats_Blend': period_perf['Blend_VRP_VT']['sharpe'] > period_perf['Blend_VT']['sharpe'],
    })

print("\n  === CROSS-OOS RESULTS ===")
print(f"  {'OOS Period':<25} {'BH':>7} {'VT':>7} {'VRP_D':>7} {'VRP_C':>7} {'BL_VT':>7} {'BL_VRP':>7}")
print(f"  {'-'*68}")
for r in cross_oos_results:
    print(f"  {r['oos_period']:<25} {r['BH_SPY_sharpe']:>7.3f} {r['VT_12VIX_sharpe']:>7.3f} "
          f"{r['VRP_Discrete_sharpe']:>7.3f} {r['VRP_Continuous_sharpe']:>7.3f} "
          f"{r['Blend_VT_sharpe']:>7.3f} {r['Blend_VRP_sharpe']:>7.3f}")

# Win rates
if cross_oos_results:
    n_periods = len(cross_oos_results)
    disc_wins = sum(r['VRP_disc_beats_VT'] for r in cross_oos_results)
    cont_wins = sum(r['VRP_cont_beats_VT'] for r in cross_oos_results)
    blend_wins = sum(r['Blend_VRP_beats_Blend'] for r in cross_oos_results)
    print(f"\n  VRP Discrete beats VT: {disc_wins}/{n_periods} ({disc_wins/n_periods:.0%})")
    print(f"  VRP Continuous beats VT: {cont_wins}/{n_periods} ({cont_wins/n_periods:.0%})")
    print(f"  Blend VRP beats Blend: {blend_wins}/{n_periods} ({blend_wins/n_periods:.0%})")

# Bootstrap (1000 reps) for Sharpe confidence intervals
print("\n  Running bootstrap (1000 reps) for Sharpe CIs...")
np.random.seed(42)
n_boot = 1000
boot_sharpe_diffs = {
    'VRP_Disc_minus_VT': [],
    'VRP_Cont_minus_VT': [],
    'Blend_VRP_minus_Blend': [],
}

oos_data = strat_returns[strat_returns.index >= '2023-01-01']
n_oos = len(oos_data)

for _ in range(n_boot):
    idx = np.random.choice(n_oos, size=n_oos, replace=True)

    for s1, s2, key in [
        ('VRP_Discrete_VT', 'VT_12VIX', 'VRP_Disc_minus_VT'),
        ('VRP_Continuous_VT', 'VT_12VIX', 'VRP_Cont_minus_VT'),
        ('Blend_VRP_VT', 'Blend_VT', 'Blend_VRP_minus_Blend'),
    ]:
        r1 = oos_data[s1].values[idx]
        r2 = oos_data[s2].values[idx]
        sr1 = r1.mean() / r1.std() * np.sqrt(252) if r1.std() > 0 else 0
        sr2 = r2.mean() / r2.std() * np.sqrt(252) if r2.std() > 0 else 0
        boot_sharpe_diffs[key].append(sr1 - sr2)

bootstrap_results = {}
for key, diffs in boot_sharpe_diffs.items():
    diffs = np.array(diffs)
    bootstrap_results[key] = {
        'mean': float(diffs.mean()),
        'std': float(diffs.std()),
        'ci_2_5': float(np.percentile(diffs, 2.5)),
        'ci_97_5': float(np.percentile(diffs, 97.5)),
        'pct_positive': float((diffs > 0).mean() * 100),
    }
    print(f"  {key}: mean={diffs.mean():.4f}, 95% CI=[{np.percentile(diffs, 2.5):.4f}, "
          f"{np.percentile(diffs, 97.5):.4f}], P(>0)={(diffs > 0).mean():.1%}")

# =============================================================================
# 8. REGIME-CONDITIONAL ANALYSIS
# =============================================================================
print("\n  === REGIME-CONDITIONAL ANALYSIS ===")

# How does VRP-VT perform in different VIX regimes?
vix_at_trade = vix_close.loc[strat_returns.index].shift(1)
regime_results = {}

for regime_name, condition in [
    ('low_vix_<15', vix_at_trade < 15),
    ('mid_vix_15-25', (vix_at_trade >= 15) & (vix_at_trade < 25)),
    ('high_vix_>25', vix_at_trade >= 25),
]:
    r_regime = strat_returns[condition].dropna()
    if len(r_regime) < 50:
        continue
    regime_perf = evaluate_performance(r_regime)
    regime_results[regime_name] = {
        'n_obs': len(r_regime),
        'BH_sharpe': regime_perf['BH_SPY']['sharpe'],
        'VT_sharpe': regime_perf['VT_12VIX']['sharpe'],
        'VRP_Disc_sharpe': regime_perf['VRP_Discrete_VT']['sharpe'],
        'VRP_Cont_sharpe': regime_perf['VRP_Continuous_VT']['sharpe'],
    }
    print(f"  {regime_name} (N={len(r_regime)}): "
          f"BH={regime_perf['BH_SPY']['sharpe']:.3f}, "
          f"VT={regime_perf['VT_12VIX']['sharpe']:.3f}, "
          f"VRP_D={regime_perf['VRP_Discrete_VT']['sharpe']:.3f}, "
          f"VRP_C={regime_perf['VRP_Continuous_VT']['sharpe']:.3f}")

# =============================================================================
# 9. SENSITIVITY ANALYSIS: VRP adjustment strength
# =============================================================================
print("\n  === SENSITIVITY: VRP ADJUSTMENT STRENGTH ===")

sensitivity_results = []
for strength in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]:
    adj = (1.0 - strength * vrp_z).clip(0.5, 1.5)
    w_sens = (w_vt * adj).clip(upper=1.5)
    r_sens = w_sens.shift(1) * spy_ret + (1 - w_sens.shift(1)) * rf_daily
    r_sens = r_sens.loc[strat_returns.index].dropna()

    sr = (r_sens.mean() * 252 - 0.02) / (r_sens.std() * np.sqrt(252))
    cum = (1 + r_sens).cumprod()
    mdd = ((cum - cum.cummax()) / cum.cummax()).min()
    to = w_sens.diff().abs().mean() * 252

    sensitivity_results.append({
        'strength': float(strength),
        'sharpe': float(sr),
        'max_dd': float(mdd),
        'annual_turnover': float(to),
    })
    print(f"  strength={strength:.2f}: Sharpe={sr:.4f}, MaxDD={mdd:.2%}, Turnover={to:.2f}")

# =============================================================================
# COMPILE RESULTS
# =============================================================================
print("\n" + "=" * 70)
print("COMPILING RESULTS...")

# Determine conclusion
best_vrp_sharpe = max(full_perf['VRP_Discrete_VT']['sharpe'],
                      full_perf['VRP_Continuous_VT']['sharpe'])
baseline_sharpe = full_perf['VT_12VIX']['sharpe']
sharpe_improvement = best_vrp_sharpe - baseline_sharpe

# Check Harvey threshold
any_harvey_significant = any(
    t.get('harvey_significant', False)
    for t in list(sharpe_tests.values()) + list(dm_tests.values())
)

conclusion_parts = []
if sharpe_improvement > 0:
    conclusion_parts.append(f"VRP enhancement improves Sharpe by {sharpe_improvement:.4f}")
else:
    conclusion_parts.append(f"VRP enhancement does NOT improve Sharpe (diff={sharpe_improvement:.4f})")

if any_harvey_significant:
    conclusion_parts.append("Passes Harvey (2016) |t|>3.0 threshold")
else:
    conclusion_parts.append("Does NOT pass Harvey (2016) |t|>3.0 threshold")

# Cross-OOS consistency
if cross_oos_results:
    max_win_rate = max(
        sum(r['VRP_disc_beats_VT'] for r in cross_oos_results) / len(cross_oos_results),
        sum(r['VRP_cont_beats_VT'] for r in cross_oos_results) / len(cross_oos_results),
    )
    conclusion_parts.append(f"Best cross-OOS win rate: {max_win_rate:.0%}")

conclusion = "; ".join(conclusion_parts)

results = {
    'experiment_id': 'k440',
    'title': 'VRP-Enhanced Volatility Targeting Strategy',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, ^VIX, GLD)',
    'data_period': f"{strat_returns.index[0].date()} to {strat_returns.index[-1].date()}",
    'n_observations': len(strat_returns),
    'is_period': f"{is_returns.index[0].date()} to {is_returns.index[-1].date()}",
    'oos_period': f"{oos_returns.index[0].date()} to {oos_returns.index[-1].date()}",
    'is_n': len(is_returns),
    'oos_n': len(oos_returns),
    'literature': [
        'Bollerslev, Tauchen, Zhou (2009) RFS 22(11):4463-4492 — VRP predicts returns and vol',
        'Moreira & Muir (2017) JoF 72(4):1611-1644 — Volatility-Managed Portfolios',
        'K430 (internal): Extreme VRP behavioral asymmetry (low VRP → vol decline 92%, high VRP → vol increase 84%)',
        'K436 (internal): VRP predictive power robust (DM p=0.018, bootstrap p=0.000)',
    ],
    'strategy_design': {
        'baseline': '12/VIX standard VT, w_t = 12/VIX capped at 150%',
        'vrp_discrete': 'VRP_pct<10% → 1.3x, VRP_pct>90% → 0.7x, else 1.0x',
        'vrp_continuous': '1 - 0.15*VRP_zscore, clipped [0.5, 1.5]',
        'blend': '50/50 SPY/GLD + VT weight',
        'rf_assumption': '2% annual (conservative)',
    },
    'descriptive_statistics': desc_stats,
    'adf_test_vrp': {
        'statistic': float(adf_result[0]),
        'p_value': float(adf_result[1]),
        'stationary': bool(adf_result[1] < 0.05),
    },
    'ljung_box_vrp': {
        'statistic': lb_stat,
        'p_value': lb_pval,
        'significant': bool(lb_pval < 0.05),
    },
    'weight_statistics': weight_stats,
    'turnover_statistics': turnover_stats,
    'full_period_performance': full_perf,
    'is_performance': is_perf,
    'oos_performance': oos_perf,
    'dm_tests_full': dm_tests,
    'dm_tests_oos': dm_tests_oos,
    'sharpe_difference_tests': sharpe_tests,
    'cross_oos_results': cross_oos_results,
    'cross_oos_summary': {
        'n_periods': len(cross_oos_results),
        'VRP_disc_wins': sum(r['VRP_disc_beats_VT'] for r in cross_oos_results) if cross_oos_results else 0,
        'VRP_cont_wins': sum(r['VRP_cont_beats_VT'] for r in cross_oos_results) if cross_oos_results else 0,
        'Blend_VRP_wins': sum(r['Blend_VRP_beats_Blend'] for r in cross_oos_results) if cross_oos_results else 0,
    },
    'bootstrap_sharpe_diff_oos': bootstrap_results,
    'regime_conditional': regime_results,
    'sensitivity_analysis': sensitivity_results,
    'conclusion': conclusion,
    'limitations': [
        'VRP percentile uses rolling 252-day window — lookback dependency',
        'Transaction costs estimated at 10bps monthly — may underestimate daily VT',
        'GLD available only from 2004 — shorter history for blend strategies',
        'VIX is closing value — intraday VRP may differ',
        'Harvey (2016) threshold is conservative — borderline improvements may be real but undetectable',
        'No GARCH-based VRP tested — only VIX - RV_21',
    ],
}

# Save results
output_path = 'experiments/k440_vrp_strategy_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")

# Final summary
print("\n" + "=" * 70)
print("FINAL CONCLUSION")
print("=" * 70)
print(f"\n  {conclusion}")
print(f"\n  Full-period Sharpe: BH={full_perf['BH_SPY']['sharpe']:.3f}, "
      f"VT={full_perf['VT_12VIX']['sharpe']:.3f}, "
      f"VRP_D={full_perf['VRP_Discrete_VT']['sharpe']:.3f}, "
      f"VRP_C={full_perf['VRP_Continuous_VT']['sharpe']:.3f}")
print(f"  OOS Sharpe: BH={oos_perf['BH_SPY']['sharpe']:.3f}, "
      f"VT={oos_perf['VT_12VIX']['sharpe']:.3f}, "
      f"VRP_D={oos_perf['VRP_Discrete_VT']['sharpe']:.3f}, "
      f"VRP_C={oos_perf['VRP_Continuous_VT']['sharpe']:.3f}")
print(f"  Blend OOS: Blend_VT={oos_perf['Blend_VT']['sharpe']:.3f}, "
      f"Blend_VRP={oos_perf['Blend_VRP_VT']['sharpe']:.3f}")

# Check for anomalies
print("\n  === ANOMALY CHECK ===")
for s in strat_returns.columns:
    if full_perf[s]['sharpe'] > 3.0:
        print(f"  WARNING: {s} Sharpe={full_perf[s]['sharpe']:.3f} suspiciously high!")
    if full_perf[s]['max_drawdown'] > -0.01:
        print(f"  WARNING: {s} MaxDD={full_perf[s]['max_drawdown']:.4f} suspiciously small!")
    if full_perf[s]['ann_volatility'] < 0.01:
        print(f"  WARNING: {s} vol={full_perf[s]['ann_volatility']:.4f} suspiciously low!")

print("\n  All checks passed. No anomalies detected." if not any(
    full_perf[s]['sharpe'] > 3.0 or full_perf[s]['max_drawdown'] > -0.01
    for s in strat_returns.columns
) else "")

print("\nDone.")
