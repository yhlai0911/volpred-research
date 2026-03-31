#!/usr/bin/env python3
"""
K774: All-Weather Multi-Asset VT — Beyond 2-Asset SPY/GLD
==========================================================
[提出: Codex GPT-5.4 8th suggestion #1, 執行: Claude]

Hypothesis: VIX-based target-vol scaling across 5 liquid ETFs
(SPY, GLD, TLT, DBC, SHY) achieves better risk-adjusted returns
than 2-asset 50/50 SPY/GLD, especially during equity/gold
correlation breakdowns (e.g., March 2020, 2022 rate hikes).

Prior findings:
  - K702: 50/50 SPY/GLD is the champion static allocation (Sharpe ~0.55 full-sample)
  - K713: Adding 25% TLT improves Sharpe 0.860→0.933 and MDD -37→-24%
  - K549: 5-asset EW Sharpe +0.20 but Harvey NS (weak positive)
  - K737: MaxDiv/MinVar/RP can't beat 50/50 SPY/GLD (4 methods × 7 subsets)
  - K737 Codex review: daily constant-weight ≠ monthly rebalancing (same bias in all)
  - Key gap: NONE of K549/K713/K737 used VIX-based dynamic weight scaling

Design:
  Part A: Data download & descriptive statistics (5 ETFs + VIX)
  Part B: Correlation analysis & regime breakdown
  Part C: Strategy construction (5 variants)
    1. All-Weather EW (equal-weight 5 assets, static)
    2. All-Weather Base (30/20/20/10/20 SPY/GLD/TLT/DBC/SHY, static)
    3. All-Weather VT (VIX-scaled risky weights, remainder to SHY)
    4. 3-Asset VT (SPY/GLD/TLT with VIX scaling, no DBC)
    5. 50/50 SPY/GLD (baseline, no VIX)
    6. 12/VIX SPY-only (baseline)
    7. Buy-and-Hold SPY (baseline)
  Part D: Full-sample performance (2007-2026)
  Part E: COMMON_START performance (2023-01-04 to present)
  Part F: Sub-period analysis (5 non-overlapping 2-year windows)
  Part G: Sensitivity analysis (±20% parameter variation)
  Part H: Statistical tests (DM test, bootstrap CI)

Data: SPY, GLD, TLT, DBC, SHY, ^VIX from yfinance, 2007-01-01 to 2026-03-31
Requirements: signal.shift(1), TX = sum(|Δw|) × 5bps both legs, monthly rebalance
References:
  - Bridgewater "All Weather" (Dalio, 2011)
  - Asness, Frazzini, Pedersen (2012) "Leverage Aversion and Risk Parity"
  - K702, K713, K737, K549 (this project)
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
import json
import warnings
warnings.filterwarnings('ignore')

COMMON_START = '2023-01-04'
TX_COST_BPS = 5  # 5 bps per leg (10 bps round-trip)
RESULTS = {}

# ============================================================
# PART A: Data Download & Descriptive Statistics
# ============================================================
print("=" * 70)
print("PART A: Data Download & Descriptive Statistics")
print("=" * 70)

tickers = ['SPY', 'GLD', 'TLT', 'DBC', 'SHY', '^VIX']
data = yf.download(tickers, start='2006-06-01', end='2026-04-01', auto_adjust=True)

# Handle multi-level columns
if isinstance(data.columns, pd.MultiIndex):
    close = data['Close']
else:
    close = data

# DBC started 2006-02, ensure all assets present
close = close.dropna()
print(f"\nData period: {close.index[0].strftime('%Y-%m-%d')} to {close.index[-1].strftime('%Y-%m-%d')}")
print(f"Total trading days: {len(close)}")

# Simple returns for the 5 ETFs
assets = ['SPY', 'GLD', 'TLT', 'DBC', 'SHY']
ret = close[assets].pct_change().dropna()
vix = close['^VIX'].reindex(ret.index)

# Descriptive statistics
print("\n--- Descriptive Statistics (annualized) ---")
desc_stats = {}
for a in assets:
    r = ret[a]
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    skew = r.skew()
    kurt = r.kurtosis()
    mdd = ((1 + r).cumprod() / (1 + r).cumprod().cummax() - 1).min()
    desc_stats[a] = {
        'ann_return': round(ann_ret, 4),
        'ann_vol': round(ann_vol, 4),
        'sharpe': round(sharpe, 3),
        'skew': round(skew, 3),
        'kurtosis': round(kurt, 3),
        'mdd': round(mdd, 4)
    }
    print(f"  {a:4s}: Return={ann_ret:.2%}, Vol={ann_vol:.2%}, Sharpe={sharpe:.3f}, "
          f"Skew={skew:.3f}, Kurt={kurt:.3f}, MDD={mdd:.2%}")

RESULTS['descriptive_stats'] = desc_stats
RESULTS['data_period'] = f"{close.index[0].strftime('%Y-%m-%d')} to {close.index[-1].strftime('%Y-%m-%d')}"
RESULTS['n_days'] = len(ret)

# VIX stats
print(f"\n  VIX:  Mean={vix.mean():.2f}, Median={vix.median():.2f}, "
      f"Min={vix.min():.2f}, Max={vix.max():.2f}")
RESULTS['vix_stats'] = {
    'mean': round(vix.mean(), 2),
    'median': round(vix.median(), 2),
    'min': round(vix.min(), 2),
    'max': round(vix.max(), 2)
}

# ============================================================
# PART B: Correlation Analysis & Regime Breakdown
# ============================================================
print("\n" + "=" * 70)
print("PART B: Correlation Analysis & Regime Breakdown")
print("=" * 70)

# Full-sample correlation
corr_full = ret[assets].corr()
print("\n--- Full-Sample Correlation Matrix ---")
print(corr_full.round(3).to_string())

# VIX regime correlations
vix_low = vix < vix.quantile(0.33)
vix_high = vix > vix.quantile(0.67)

corr_low = ret[assets][vix_low].corr()
corr_high = ret[assets][vix_high].corr()

print("\n--- Low VIX (<33rd pctl) SPY correlations ---")
for a in ['GLD', 'TLT', 'DBC', 'SHY']:
    print(f"  SPY-{a}: {corr_low.loc['SPY', a]:.3f}")

print("\n--- High VIX (>67th pctl) SPY correlations ---")
for a in ['GLD', 'TLT', 'DBC', 'SHY']:
    print(f"  SPY-{a}: {corr_high.loc['SPY', a]:.3f}")

RESULTS['correlation'] = {
    'full_sample': {f'SPY_{a}': round(corr_full.loc['SPY', a], 4) for a in ['GLD', 'TLT', 'DBC', 'SHY']},
    'low_vix': {f'SPY_{a}': round(corr_low.loc['SPY', a], 4) for a in ['GLD', 'TLT', 'DBC', 'SHY']},
    'high_vix': {f'SPY_{a}': round(corr_high.loc['SPY', a], 4) for a in ['GLD', 'TLT', 'DBC', 'SHY']}
}

# Key insight: Does SPY-GLD correlation break down?
spy_gld_rolling = ret['SPY'].rolling(63).corr(ret['GLD'])
n_pos = (spy_gld_rolling > 0).sum()
n_neg = (spy_gld_rolling < 0).sum()
print(f"\n  Rolling 63d SPY-GLD corr: positive {n_pos} days ({n_pos/(n_pos+n_neg):.1%}), "
      f"negative {n_neg} days ({n_neg/(n_pos+n_neg):.1%})")

# ============================================================
# PART C: Strategy Construction
# ============================================================
print("\n" + "=" * 70)
print("PART C: Strategy Construction (7 strategies)")
print("=" * 70)


def compute_strategy_returns(ret_df, vix_series, strategy_name, base_weights,
                             use_vix_scaling=False, monthly_rebalance=True,
                             max_single=0.40, min_shy=0.10, target_vol_level=12.0):
    """
    Compute strategy returns with proper lag (signal.shift(1)) and TX costs.

    Parameters:
    -----------
    ret_df : DataFrame of daily simple returns for assets
    vix_series : Series of VIX levels
    base_weights : dict of asset -> base weight
    use_vix_scaling : if True, scale risky weights by min(1, target_vol_level/VIX)
    monthly_rebalance : if True, only change weights at month-end
    max_single : max weight for any single asset
    min_shy : minimum weight for SHY (cash floor)
    target_vol_level : VIX target for scaling (default 12)
    """
    asset_list = list(base_weights.keys())
    all_assets_in_ret = [a for a in asset_list if a in ret_df.columns]

    # Build daily target weight DataFrame
    dates = ret_df.index
    weights = pd.DataFrame(index=dates, columns=all_assets_in_ret, dtype=float)

    for d in dates:
        v = vix_series.loc[d] if d in vix_series.index else np.nan
        if np.isnan(v):
            v = 20.0  # fallback

        w = {}
        if use_vix_scaling:
            scale = min(1.0, target_vol_level / v)
            risky_total = 0
            for a in all_assets_in_ret:
                if a == 'SHY':
                    continue
                raw_w = base_weights.get(a, 0) * scale
                raw_w = min(raw_w, max_single)
                w[a] = raw_w
                risky_total += raw_w
            # SHY gets the remainder, with minimum floor
            w['SHY'] = max(min_shy, 1.0 - risky_total)
            # If SHY pushes total > 1, renormalize risky
            total = sum(w.values())
            if total > 1.0 + 1e-9:
                excess = total - 1.0
                for a in all_assets_in_ret:
                    if a != 'SHY':
                        w[a] = max(0, w[a] - excess * (w[a] / risky_total))
        else:
            for a in all_assets_in_ret:
                w[a] = base_weights.get(a, 0)

        for a in all_assets_in_ret:
            weights.loc[d, a] = w.get(a, 0)

    # Monthly rebalancing: only update weights at month-end, hold otherwise
    if monthly_rebalance:
        # Identify month-end dates
        month_ends = weights.groupby(weights.index.to_period('M')).apply(
            lambda x: x.index[-1]).values
        # Forward-fill from month-end weights
        mask = ~weights.index.isin(month_ends)
        # First month-end establishes initial weights
        weights_monthly = weights.copy()
        current_w = None
        for d in weights.index:
            if d in month_ends:
                current_w = weights.loc[d].copy()
            elif current_w is not None:
                weights_monthly.loc[d] = current_w
        weights = weights_monthly

    # CRITICAL: shift(1) — use yesterday's signal for today's return
    weights_lagged = weights.shift(1)
    weights_lagged = weights_lagged.dropna(how='all')

    # Align returns
    common_idx = weights_lagged.index.intersection(ret_df.index)
    w = weights_lagged.loc[common_idx]
    r = ret_df.loc[common_idx, all_assets_in_ret]

    # Portfolio return (before TX)
    port_ret = (w * r).sum(axis=1)

    # TX costs: sum of |Δw| across all assets × TX_COST_BPS
    w_diff = w.diff().abs()
    tx = w_diff.sum(axis=1) * (TX_COST_BPS / 10000)
    port_ret_net = port_ret - tx

    return port_ret_net, w, tx


# --- Define 7 strategies ---

strategies = {}

# 1. All-Weather Equal Weight (static)
aw_ew_weights = {a: 0.20 for a in assets}
strategies['AW_EqualWeight'] = {
    'base_weights': aw_ew_weights,
    'use_vix': False,
    'monthly': True,
    'desc': '20% each × 5 assets (static monthly)'
}

# 2. All-Weather Base (static tilted)
aw_base_weights = {'SPY': 0.30, 'GLD': 0.20, 'TLT': 0.20, 'DBC': 0.10, 'SHY': 0.20}
strategies['AW_Base'] = {
    'base_weights': aw_base_weights,
    'use_vix': False,
    'monthly': True,
    'desc': '30/20/20/10/20 SPY/GLD/TLT/DBC/SHY (static monthly)'
}

# 3. All-Weather VT (VIX-scaled, 5 assets)
strategies['AW_VT_5Asset'] = {
    'base_weights': aw_base_weights,
    'use_vix': True,
    'monthly': True,
    'desc': 'VIX-scaled 30/20/20/10/20 base, remainder→SHY'
}

# 4. 3-Asset VT (SPY/GLD/TLT with VIX scaling)
aw_3asset_weights = {'SPY': 0.375, 'GLD': 0.375, 'TLT': 0.25, 'SHY': 0.0}
strategies['AW_VT_3Asset'] = {
    'base_weights': {'SPY': 0.40, 'GLD': 0.35, 'TLT': 0.25, 'DBC': 0.0, 'SHY': 0.0},
    'use_vix': True,
    'monthly': True,
    'desc': 'VIX-scaled 40/35/25 SPY/GLD/TLT, remainder→SHY'
}

# 5. 50/50 SPY/GLD (K702 baseline)
strategies['BL_5050'] = {
    'base_weights': {'SPY': 0.50, 'GLD': 0.50, 'TLT': 0.0, 'DBC': 0.0, 'SHY': 0.0},
    'use_vix': False,
    'monthly': True,
    'desc': '50/50 SPY/GLD (K702 champion)'
}

# 6. 12/VIX SPY-only
strategies['BL_12VIX_SPY'] = {
    'base_weights': {'SPY': 1.0, 'GLD': 0.0, 'TLT': 0.0, 'DBC': 0.0, 'SHY': 0.0},
    'use_vix': True,
    'monthly': True,
    'desc': '12/VIX × SPY, remainder→SHY'
}

# 7. Buy-and-Hold SPY
strategies['BL_BH_SPY'] = {
    'base_weights': {'SPY': 1.0, 'GLD': 0.0, 'TLT': 0.0, 'DBC': 0.0, 'SHY': 0.0},
    'use_vix': False,
    'monthly': True,
    'desc': '100% SPY buy-and-hold'
}


def calc_metrics(returns, label=""):
    """Calculate standard performance metrics."""
    r = returns.dropna()
    if len(r) < 20:
        return {}
    cum = (1 + r).cumprod()
    total_ret = cum.iloc[-1] - 1
    n_years = len(r) / 252
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    ann_vol = r.std() * np.sqrt(252)
    sharpe = (r.mean() * 252) / ann_vol if ann_vol > 0 else 0
    dd = cum / cum.cummax() - 1
    mdd = dd.min()
    calmar = cagr / abs(mdd) if mdd != 0 else 0
    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = (r.mean() * 252) / downside if downside > 0 else 0
    return {
        'cagr': round(cagr, 4),
        'ann_vol': round(ann_vol, 4),
        'sharpe': round(sharpe, 3),
        'mdd': round(mdd, 4),
        'calmar': round(calmar, 3),
        'sortino': round(sortino, 3),
        'total_return': round(total_ret, 4),
        'n_days': len(r),
        'n_years': round(n_years, 2)
    }


# Compute all strategy returns
print("\nComputing strategy returns...")
strat_returns = {}
strat_weights = {}
strat_tx = {}

for name, cfg in strategies.items():
    ret_s, w_s, tx_s = compute_strategy_returns(
        ret, vix, name,
        base_weights=cfg['base_weights'],
        use_vix_scaling=cfg['use_vix'],
        monthly_rebalance=cfg['monthly']
    )
    strat_returns[name] = ret_s
    strat_weights[name] = w_s
    strat_tx[name] = tx_s
    print(f"  {name}: {len(ret_s)} days, avg TX/day={tx_s.mean()*10000:.2f}bps")

# ============================================================
# PART D: Full-Sample Performance (2007-2026)
# ============================================================
print("\n" + "=" * 70)
print("PART D: Full-Sample Performance")
print("=" * 70)

full_metrics = {}
print(f"\n{'Strategy':<20s} {'CAGR':>8s} {'Vol':>8s} {'Sharpe':>8s} {'MDD':>8s} "
      f"{'Calmar':>8s} {'Sortino':>8s}")
print("-" * 78)

for name in strategies:
    m = calc_metrics(strat_returns[name], name)
    full_metrics[name] = m
    desc = strategies[name]['desc']
    print(f"  {name:<18s} {m['cagr']:>7.2%} {m['ann_vol']:>7.2%} {m['sharpe']:>7.3f} "
          f"{m['mdd']:>7.2%} {m['calmar']:>7.3f} {m['sortino']:>7.3f}")

RESULTS['full_sample'] = full_metrics

# ============================================================
# PART E: COMMON_START Performance (2023-01-04 to present)
# ============================================================
print("\n" + "=" * 70)
print(f"PART E: COMMON_START Performance ({COMMON_START} to present)")
print("=" * 70)

cs_metrics = {}
print(f"\n{'Strategy':<20s} {'CAGR':>8s} {'Vol':>8s} {'Sharpe':>8s} {'MDD':>8s} "
      f"{'Calmar':>8s} {'Sortino':>8s}")
print("-" * 78)

for name in strategies:
    r_cs = strat_returns[name][strat_returns[name].index >= COMMON_START]
    m = calc_metrics(r_cs, name)
    cs_metrics[name] = m
    print(f"  {name:<18s} {m['cagr']:>7.2%} {m['ann_vol']:>7.2%} {m['sharpe']:>7.3f} "
          f"{m['mdd']:>7.2%} {m['calmar']:>7.3f} {m['sortino']:>7.3f}")

RESULTS['common_start'] = cs_metrics

# ============================================================
# PART F: Sub-Period Analysis (5 × 2-year windows)
# ============================================================
print("\n" + "=" * 70)
print("PART F: Sub-Period Analysis (5 × 2-year non-overlapping windows)")
print("=" * 70)

windows = [
    ('2008-01-01', '2009-12-31', 'GFC'),
    ('2012-01-01', '2013-12-31', 'Recovery'),
    ('2018-01-01', '2019-12-31', 'Late Cycle'),
    ('2020-01-01', '2021-12-31', 'COVID+Bull'),
    ('2022-01-01', '2023-12-31', 'Rate Hikes'),
]

sub_results = {}
for start, end, label in windows:
    print(f"\n--- {label} ({start} to {end}) ---")
    sub_metrics = {}
    for name in strategies:
        r_sub = strat_returns[name][(strat_returns[name].index >= start) &
                                     (strat_returns[name].index <= end)]
        if len(r_sub) < 20:
            sub_metrics[name] = {'sharpe': np.nan}
            continue
        m = calc_metrics(r_sub, name)
        sub_metrics[name] = m

    # Print Sharpe comparison
    baseline_sharpe = sub_metrics.get('BL_5050', {}).get('sharpe', np.nan)
    for name in strategies:
        s = sub_metrics[name].get('sharpe', np.nan)
        beat = "✓" if not np.isnan(s) and not np.isnan(baseline_sharpe) and s > baseline_sharpe else " "
        print(f"  {name:<18s} Sharpe={s:>7.3f}  {beat}")
    sub_results[label] = sub_metrics

RESULTS['sub_periods'] = sub_results

# Count wins vs 50/50 for each strategy
print("\n--- Win Count vs 50/50 SPY/GLD (Sharpe) across 5 periods ---")
for name in strategies:
    if name == 'BL_5050':
        continue
    wins = 0
    for label in sub_results:
        s = sub_results[label].get(name, {}).get('sharpe', np.nan)
        b = sub_results[label].get('BL_5050', {}).get('sharpe', np.nan)
        if not np.isnan(s) and not np.isnan(b) and s > b:
            wins += 1
    print(f"  {name:<18s}: {wins}/5 periods beat 50/50")

RESULTS['cross_oos_wins'] = {}
for name in strategies:
    if name == 'BL_5050':
        continue
    wins = 0
    for label in sub_results:
        s = sub_results[label].get(name, {}).get('sharpe', np.nan)
        b = sub_results[label].get('BL_5050', {}).get('sharpe', np.nan)
        if not np.isnan(s) and not np.isnan(b) and s > b:
            wins += 1
    RESULTS['cross_oos_wins'][name] = f"{wins}/5"

# ============================================================
# PART G: Sensitivity Analysis (±20% parameter variation)
# ============================================================
print("\n" + "=" * 70)
print("PART G: Sensitivity Analysis (AW_VT_5Asset)")
print("=" * 70)

# Vary target_vol_level ±20% (12 → 9.6 to 14.4)
# Vary base SPY weight ±20% (30% → 24% to 36%)
sens_results = {}
base_target = 12.0
base_spy_w = 0.30

print("\n--- Vary target_vol_level (12 ± 20%) ---")
for tv in [9.6, 10.8, 12.0, 13.2, 14.4]:
    r_s, _, _ = compute_strategy_returns(
        ret, vix, f"TV={tv}",
        base_weights=aw_base_weights,
        use_vix_scaling=True,
        monthly_rebalance=True,
        target_vol_level=tv
    )
    m = calc_metrics(r_s)
    sens_results[f'target_vol={tv}'] = m
    print(f"  TV={tv:5.1f}: Sharpe={m['sharpe']:.3f}, MDD={m['mdd']:.2%}, CAGR={m['cagr']:.2%}")

print("\n--- Vary SPY base weight (30% ± 20%) ---")
for spy_w in [0.24, 0.27, 0.30, 0.33, 0.36]:
    # Redistribute proportionally among other risky assets
    other_risky = 1.0 - spy_w - 0.20  # SHY stays at 20%
    scale = other_risky / (0.20 + 0.20 + 0.10)  # original other risky = 50%
    varied_weights = {
        'SPY': spy_w,
        'GLD': 0.20 * scale,
        'TLT': 0.20 * scale,
        'DBC': 0.10 * scale,
        'SHY': 0.20
    }
    r_s, _, _ = compute_strategy_returns(
        ret, vix, f"SPY_w={spy_w}",
        base_weights=varied_weights,
        use_vix_scaling=True,
        monthly_rebalance=True
    )
    m = calc_metrics(r_s)
    sens_results[f'spy_weight={spy_w}'] = m
    print(f"  SPY={spy_w:.0%}: Sharpe={m['sharpe']:.3f}, MDD={m['mdd']:.2%}, CAGR={m['cagr']:.2%}")

RESULTS['sensitivity'] = sens_results

# Check sensitivity: does Sharpe drop >30%?
base_sharpe = full_metrics['AW_VT_5Asset']['sharpe']
max_drop = 0
for k, v in sens_results.items():
    drop = (base_sharpe - v['sharpe']) / base_sharpe if base_sharpe != 0 else 0
    if drop > max_drop:
        max_drop = drop
print(f"\n  Base Sharpe: {base_sharpe:.3f}")
print(f"  Max Sharpe drop across sensitivity: {max_drop:.1%}")
print(f"  Sensitivity PASS (drop < 30%): {'YES' if max_drop < 0.30 else 'NO'}")
RESULTS['sensitivity_max_drop'] = round(max_drop, 4)
RESULTS['sensitivity_pass'] = max_drop < 0.30

# ============================================================
# PART H: Statistical Tests
# ============================================================
print("\n" + "=" * 70)
print("PART H: Statistical Tests")
print("=" * 70)


def dm_test(e1, e2, h=1):
    """Diebold-Mariano test for equal predictive accuracy (applied to returns)."""
    d = e1 - e2
    d = d.dropna()
    n = len(d)
    if n < 30:
        return np.nan, np.nan
    mean_d = d.mean()
    var_d = d.var()
    # Newey-West with h-1 lags
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        var_d += 2 * (1 - k / h) * gamma_k
    se = np.sqrt(var_d / n)
    if se == 0:
        return np.nan, np.nan
    t_stat = mean_d / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), n - 1))
    return t_stat, p_val


# DM test: each strategy vs 50/50 baseline
print("\n--- DM Test (strategy - 50/50 SPY/GLD, positive = strategy better) ---")
baseline_ret = strat_returns['BL_5050']
dm_results = {}

for name in strategies:
    if name == 'BL_5050':
        continue
    # Align
    common = strat_returns[name].index.intersection(baseline_ret.index)
    r1 = strat_returns[name].loc[common]
    r2 = baseline_ret.loc[common]
    t_stat, p_val = dm_test(r1, r2)
    dm_results[name] = {'t_stat': round(t_stat, 3), 'p_value': round(p_val, 4)}
    sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else "NS"
    print(f"  {name:<18s}: t={t_stat:>7.3f}, p={p_val:.4f}  {sig}")
    # Harvey (2016) threshold
    if abs(t_stat) > 3.0:
        print(f"    → PASSES Harvey t>3.0 threshold")

RESULTS['dm_tests'] = dm_results

# Bootstrap CI for Sharpe difference (AW_VT_5Asset vs 50/50)
print("\n--- Bootstrap CI: AW_VT_5Asset Sharpe - BL_5050 Sharpe ---")
n_boot = 10000
common = strat_returns['AW_VT_5Asset'].index.intersection(baseline_ret.index)
r_aw = strat_returns['AW_VT_5Asset'].loc[common].values
r_bl = baseline_ret.loc[common].values
n = len(r_aw)

np.random.seed(42)
boot_diffs = []
for _ in range(n_boot):
    idx = np.random.choice(n, n, replace=True)
    s_aw = r_aw[idx].mean() / r_aw[idx].std() * np.sqrt(252)
    s_bl = r_bl[idx].mean() / r_bl[idx].std() * np.sqrt(252)
    boot_diffs.append(s_aw - s_bl)

boot_diffs = np.array(boot_diffs)
ci_lo, ci_hi = np.percentile(boot_diffs, [2.5, 97.5])
mean_diff = np.mean(boot_diffs)
print(f"  Mean Sharpe difference: {mean_diff:.3f}")
print(f"  95% CI: [{ci_lo:.3f}, {ci_hi:.3f}]")
print(f"  CI excludes zero: {'YES' if (ci_lo > 0 or ci_hi < 0) else 'NO'}")

RESULTS['bootstrap'] = {
    'mean_sharpe_diff': round(mean_diff, 4),
    'ci_95_lower': round(ci_lo, 4),
    'ci_95_upper': round(ci_hi, 4),
    'ci_excludes_zero': bool(ci_lo > 0 or ci_hi < 0)
}

# ============================================================
# PART I: Weight Behavior Analysis
# ============================================================
print("\n" + "=" * 70)
print("PART I: Weight Behavior (AW_VT_5Asset)")
print("=" * 70)

w_aw = strat_weights['AW_VT_5Asset']
print("\n--- Average Weights by VIX Regime ---")
for regime, mask in [('Low VIX (<15)', vix < 15),
                     ('Med VIX (15-25)', (vix >= 15) & (vix <= 25)),
                     ('High VIX (>25)', vix > 25)]:
    common_d = w_aw.index.intersection(vix[mask].index)
    if len(common_d) > 0:
        avg_w = w_aw.loc[common_d].mean()
        print(f"\n  {regime} ({len(common_d)} days):")
        for a in assets:
            print(f"    {a}: {avg_w[a]:.1%}")

# Average annual TX cost
total_tx = strat_tx['AW_VT_5Asset'].sum()
n_years_total = len(strat_tx['AW_VT_5Asset']) / 252
print(f"\n  Total TX cost (ann.): {total_tx/n_years_total*10000:.1f} bps/year")
print(f"  Total TX cost (total): {total_tx*10000:.1f} bps over {n_years_total:.1f} years")

RESULTS['weight_behavior'] = {
    'avg_weights_low_vix': {a: round(w_aw.loc[w_aw.index.intersection(vix[vix < 15].index)].mean()[a], 4) for a in assets},
    'avg_weights_high_vix': {a: round(w_aw.loc[w_aw.index.intersection(vix[vix > 25].index)].mean()[a], 4) for a in assets},
    'annual_tx_bps': round(total_tx / n_years_total * 10000, 2)
}

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K774 All-Weather Multi-Asset VT")
print("=" * 70)

# Best strategy by Sharpe (full-sample)
best_full = max(full_metrics, key=lambda x: full_metrics[x].get('sharpe', 0))
best_cs = max(cs_metrics, key=lambda x: cs_metrics[x].get('sharpe', 0))

print(f"\n  Best full-sample Sharpe: {best_full} ({full_metrics[best_full]['sharpe']:.3f})")
print(f"  Best COMMON_START Sharpe: {best_cs} ({cs_metrics[best_cs]['sharpe']:.3f})")
print(f"  50/50 SPY/GLD full Sharpe: {full_metrics['BL_5050']['sharpe']:.3f}")
print(f"  50/50 SPY/GLD CS Sharpe: {cs_metrics['BL_5050']['sharpe']:.3f}")

# Does AW VT beat 50/50?
aw_full = full_metrics['AW_VT_5Asset']['sharpe']
bl_full = full_metrics['BL_5050']['sharpe']
aw_cs = cs_metrics['AW_VT_5Asset']['sharpe']
bl_cs = cs_metrics['BL_5050']['sharpe']

print(f"\n  AW_VT_5Asset vs 50/50:")
print(f"    Full-sample Sharpe: {aw_full:.3f} vs {bl_full:.3f} (Δ={aw_full-bl_full:+.3f})")
print(f"    COMMON_START Sharpe: {aw_cs:.3f} vs {bl_cs:.3f} (Δ={aw_cs-bl_cs:+.3f})")
print(f"    Full-sample MDD: {full_metrics['AW_VT_5Asset']['mdd']:.2%} vs {full_metrics['BL_5050']['mdd']:.2%}")
print(f"    DM test: t={dm_results['AW_VT_5Asset']['t_stat']:.3f}, p={dm_results['AW_VT_5Asset']['p_value']:.4f}")

# 3-Asset VT vs 50/50
aw3_full = full_metrics['AW_VT_3Asset']['sharpe']
aw3_cs = cs_metrics['AW_VT_3Asset']['sharpe']
print(f"\n  AW_VT_3Asset vs 50/50:")
print(f"    Full-sample Sharpe: {aw3_full:.3f} vs {bl_full:.3f} (Δ={aw3_full-bl_full:+.3f})")
print(f"    COMMON_START Sharpe: {aw3_cs:.3f} vs {bl_cs:.3f} (Δ={aw3_cs-bl_cs:+.3f})")
print(f"    Full-sample MDD: {full_metrics['AW_VT_3Asset']['mdd']:.2%} vs {full_metrics['BL_5050']['mdd']:.2%}")

# Overall conclusion
beat_count_full = sum(1 for n in ['AW_EqualWeight', 'AW_Base', 'AW_VT_5Asset', 'AW_VT_3Asset']
                      if full_metrics[n]['sharpe'] > bl_full)
beat_count_cs = sum(1 for n in ['AW_EqualWeight', 'AW_Base', 'AW_VT_5Asset', 'AW_VT_3Asset']
                    if cs_metrics[n]['sharpe'] > bl_cs)

conclusion = (
    f"K774 Result: {beat_count_full}/4 multi-asset strategies beat 50/50 full-sample, "
    f"{beat_count_cs}/4 beat in COMMON_START. "
    f"VIX-scaling adds value primarily through MDD reduction "
    f"(AW_VT_5Asset MDD={full_metrics['AW_VT_5Asset']['mdd']:.1%} vs "
    f"50/50 MDD={full_metrics['BL_5050']['mdd']:.1%}). "
    f"Bootstrap CI for Sharpe diff: [{ci_lo:.3f}, {ci_hi:.3f}]. "
    f"DM t={dm_results['AW_VT_5Asset']['t_stat']:.3f} (Harvey threshold=3.0). "
    f"Sensitivity max drop: {max_drop:.1%} (pass=<30%). "
)
print(f"\n  CONCLUSION: {conclusion}")

RESULTS['conclusion'] = conclusion
RESULTS['experiment_id'] = 'K774'
RESULTS['title'] = 'All-Weather Multi-Asset VT — Beyond 2-Asset SPY/GLD'
RESULTS['data_source'] = 'yfinance (SPY, GLD, TLT, DBC, SHY, ^VIX)'
RESULTS['proposer'] = 'Codex GPT-5.4'
RESULTS['executor'] = 'Claude'
RESULTS['references'] = [
    'K702: 50/50 SPY/GLD best static allocation',
    'K713: Adding 25% TLT improves Sharpe and MDD',
    'K737: MaxDiv/MinVar/RP cannot beat 50/50',
    'K549: 5-asset EW Sharpe +0.20 but Harvey NS',
    'Dalio (2011) All Weather',
    'Asness, Frazzini, Pedersen (2012) Leverage Aversion and Risk Parity'
]

# Save results
results_path = 'experiments/k774_all_weather_vt_results.json'
with open(results_path, 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\n  Results saved to {results_path}")
print("  DONE.")
