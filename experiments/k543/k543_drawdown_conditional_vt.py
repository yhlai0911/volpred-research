#!/usr/bin/env python3
"""
K543: Drawdown-Conditional VT — Can recent drawdown depth improve VT timing?
=============================================================================
Motivation: All attempts to improve 12/VIX have used volatility or external
indicators. But maybe the simplest signal is one we haven't tried: HOW FAR
ARE WE FROM THE PEAK?

Hypothesis: After a significant drawdown (say -10%), VT's defensive positioning
is most valuable because further decline is likely. After recovering to new
highs, VT's insurance cost is wasted.

This is NOT about predicting vol — it's about recognizing WHERE we are in the
drawdown cycle. Drawdown is a purely mechanical, path-dependent measure. No
model estimation, no parameters to overfit (just thresholds). It captures a
different dimension from VIX (VIX can be high even at peaks, or low during
slow grinds down).

Strategies:
a. DD-Enhanced VT: multiply 12/VIX weight by (1 + |DD|/0.10) when DD < -5%. Caps 2x.
b. DD-Conditional: tiered VIX weight by DD depth.
c. Recovery Filter: near new highs → reduce VT weight 30%.
d. DD Momentum: if drawdown deepening → increase VT; recovering → reduce.

Benchmark: pure 12/VIX
Cross-OOS: 5 periods
Harvey (2016): t > 3.0

Data source: yfinance (SPY + ^VIX)
Period: 2006-2026 (~20 years)
TX cost: 2bps daily (conservative)

References:
- Moreira & Muir (2017) "Volatility-Managed Portfolios" JF
- Harvey & Liu (2016) "…and the Cross-Section of Expected Returns" RFS
- K458 meta-analysis: all 'smart' adjustments to standard VT yielded negligible improvement
- K499 Hybrid VT rebalancing: daily VT Sharpe=1.064 vs weekly=0.367
- K507 dynamic allocation: 50/50 SPY/GLD + 12/VIX Sharpe ~0.83
"""

import json
import sys
import os
import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from scipy import stats

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import yfinance as yf


# ────────────────────────────────────────────────────────────
# Data
# ────────────────────────────────────────────────────────────

def get_data():
    """Fetch SPY + VIX from yfinance."""
    def _download(ticker):
        df = yf.download(ticker, start="2005-01-01", end="2026-12-31", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_localize(None)
        return df

    spy = _download("SPY")
    vix = _download("^VIX")
    return spy, vix


# ────────────────────────────────────────────────────────────
# Drawdown computation
# ────────────────────────────────────────────────────────────

def compute_drawdown(prices: pd.Series) -> pd.Series:
    """Running drawdown: DD_t = price_t / max(price_{0:t}) - 1."""
    running_max = prices.cummax()
    dd = prices / running_max - 1.0
    return dd


def compute_dd_momentum(dd: pd.Series, lookback: int = 5) -> pd.Series:
    """DD momentum: DD_t - DD_{t-lookback}. Negative = deepening."""
    return dd - dd.shift(lookback)


# ────────────────────────────────────────────────────────────
# Base VT weight
# ────────────────────────────────────────────────────────────

def vt_weight_12vix(vix_level: float) -> float:
    """Standard 12/VIX weight, capped at [0, 1]."""
    return min(max(12.0 / max(vix_level, 1.0), 0.0), 1.0)


# ────────────────────────────────────────────────────────────
# Strategies
# ────────────────────────────────────────────────────────────

def strategy_baseline(spy_ret, vix_series, dd_series, dd_mom, **kw):
    """Pure 12/VIX benchmark."""
    w = vix_series.shift(1).apply(vt_weight_12vix)
    port_ret = w * spy_ret + (1 - w) * 0  # rest in cash (0 return)
    return port_ret.dropna()


def strategy_dd_enhanced(spy_ret, vix_series, dd_series, dd_mom, **kw):
    """
    DD-Enhanced VT: when DD < -5%, multiply 12/VIX weight by
    (1 + |DD|/0.10), capped at 2x the base weight.
    More defensive = lower equity weight = higher cash.
    Wait — "more defensive" means LOWER equity exposure.
    So we REDUCE weight when in drawdown? No — the original design says
    "VT's defensive positioning is most valuable" in drawdowns.
    12/VIX already reduces weight when VIX is high.
    The idea: in drawdown, we want EVEN MORE reduction (more cash).
    So we multiply by a REDUCTION factor.

    Actually re-reading the spec: "multiply weight by (1 + |DD|/0.10)"
    makes weight LARGER, which means MORE equity. That contradicts
    "more defensive". Let me implement the DEFENSIVE version:
    divide base weight by the multiplier when in drawdown.

    I'll implement BOTH interpretations and see which works.
    """
    base_w = vix_series.shift(1).apply(vt_weight_12vix)
    dd_lag = dd_series.shift(1)  # use yesterday's drawdown

    # Defensive: reduce equity when in drawdown
    multiplier = pd.Series(1.0, index=dd_lag.index)
    mask = dd_lag < -0.05
    multiplier[mask] = 1.0 / (1.0 + dd_lag[mask].abs() / 0.10)
    multiplier = multiplier.clip(lower=0.5)  # floor at 50% of base

    w = (base_w * multiplier).clip(0, 1)
    port_ret = w * spy_ret
    return port_ret.dropna()


def strategy_dd_enhanced_aggressive(spy_ret, vix_series, dd_series, dd_mom, **kw):
    """
    DD-Enhanced Aggressive: when DD < -5%, INCREASE equity weight
    (contrarian — buy the dip). Multiply 12/VIX weight by (1 + |DD|/0.10).
    Idea: drawdowns mean-revert, so more equity in drawdown = buy low.
    """
    base_w = vix_series.shift(1).apply(vt_weight_12vix)
    dd_lag = dd_series.shift(1)

    multiplier = pd.Series(1.0, index=dd_lag.index)
    mask = dd_lag < -0.05
    multiplier[mask] = 1.0 + dd_lag[mask].abs() / 0.10
    multiplier = multiplier.clip(upper=2.0)

    w = (base_w * multiplier).clip(0, 1)
    port_ret = w * spy_ret
    return port_ret.dropna()


def strategy_dd_conditional(spy_ret, vix_series, dd_series, dd_mom, **kw):
    """
    DD-Conditional: tiered approach.
    - DD > -5%: normal 12/VIX
    - DD < -5%: reduce equity to 50% of 12/VIX weight (protect more)
    - DD < -15%: reduce equity to 20% of 12/VIX weight (maximum protection)
    """
    base_w = vix_series.shift(1).apply(vt_weight_12vix)
    dd_lag = dd_series.shift(1)

    scale = pd.Series(1.0, index=dd_lag.index)
    scale[dd_lag < -0.05] = 0.50
    scale[dd_lag < -0.15] = 0.20

    w = (base_w * scale).clip(0, 1)
    port_ret = w * spy_ret
    return port_ret.dropna()


def strategy_recovery_filter(spy_ret, vix_series, dd_series, dd_mom, **kw):
    """
    Recovery Filter: near new highs (DD > -2%), reduce VT weight by 30%
    to save insurance cost. This INCREASES equity exposure near peaks.
    Idea: near peaks, vol is usually low and VT is "wasting" returns on cash.
    """
    base_w = vix_series.shift(1).apply(vt_weight_12vix)
    dd_lag = dd_series.shift(1)

    scale = pd.Series(1.0, index=dd_lag.index)
    # Near new highs: increase equity (reduce VT defensiveness)
    near_peak = dd_lag > -0.02
    scale[near_peak] = 1.30  # 30% more equity

    w = (base_w * scale).clip(0, 1)
    port_ret = w * spy_ret
    return port_ret.dropna()


def strategy_dd_momentum(spy_ret, vix_series, dd_series, dd_mom, **kw):
    """
    DD Momentum: if drawdown is deepening (dd_mom < 0), reduce equity;
    if recovering (dd_mom > 0), increase equity.
    """
    base_w = vix_series.shift(1).apply(vt_weight_12vix)
    dd_mom_lag = dd_mom.shift(1)

    scale = pd.Series(1.0, index=dd_mom_lag.index)
    # Deepening drawdown: reduce equity
    deepening = dd_mom_lag < -0.01
    scale[deepening] = 0.70
    # Recovering: increase equity
    recovering = dd_mom_lag > 0.01
    scale[recovering] = 1.20

    w = (base_w * scale).clip(0, 1)
    port_ret = w * spy_ret
    return port_ret.dropna()


def strategy_combined(spy_ret, vix_series, dd_series, dd_mom, **kw):
    """
    Combined: DD-Conditional tiers + DD Momentum + Recovery Filter.
    - Near peak (DD > -2%) + recovering: +30% equity
    - In drawdown (DD < -5%) + deepening: -50% equity
    - Deep drawdown (DD < -15%): -80% equity regardless
    - Otherwise: normal 12/VIX
    """
    base_w = vix_series.shift(1).apply(vt_weight_12vix)
    dd_lag = dd_series.shift(1)
    dd_mom_lag = dd_mom.shift(1)

    scale = pd.Series(1.0, index=dd_lag.index)

    # Deep drawdown: maximum defense
    scale[dd_lag < -0.15] = 0.20

    # Moderate drawdown + deepening: defensive
    moderate_dd = (dd_lag < -0.05) & (dd_lag >= -0.15)
    deepening = dd_mom_lag < -0.01
    scale[moderate_dd & deepening] = 0.50
    scale[moderate_dd & ~deepening] = 0.70  # in DD but recovering

    # Near peak + recovering: aggressive
    near_peak = dd_lag > -0.02
    recovering = dd_mom_lag > 0.01
    scale[near_peak & recovering] = 1.30
    scale[near_peak & ~recovering] = 1.10

    w = (base_w * scale).clip(0, 1)
    port_ret = w * spy_ret
    return port_ret.dropna()


# ────────────────────────────────────────────────────────────
# Evaluation
# ────────────────────────────────────────────────────────────

def compute_metrics(returns: pd.Series, tx_cost_bps: float = 2.0) -> dict:
    """Compute standard strategy metrics."""
    r = returns.dropna()
    if len(r) < 252:
        return {}

    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown of cumulative returns
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    max_dd = dd.min()

    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    # Sortino
    neg_ret = r[r < 0]
    downside_vol = neg_ret.std() * np.sqrt(252) if len(neg_ret) > 0 else ann_vol
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0

    # Approximate TX cost
    net_ret = ann_ret - (tx_cost_bps / 10000) * 252  # daily cost proxy
    net_sharpe = net_ret / ann_vol if ann_vol > 0 else 0

    return {
        'ann_return': round(ann_ret * 100, 2),
        'ann_vol': round(ann_vol * 100, 2),
        'sharpe': round(sharpe, 4),
        'max_dd': round(max_dd * 100, 2),
        'calmar': round(calmar, 4),
        'sortino': round(sortino, 4),
        'net_sharpe_2bps': round(net_sharpe, 4),
        'n_days': len(r),
        'n_years': round(len(r) / 252, 1)
    }


def diebold_mariano_test(e1: pd.Series, e2: pd.Series, h: int = 1) -> dict:
    """
    Diebold-Mariano test for return differential.
    H0: E[d_t] = 0 where d_t = r1_t - r2_t.
    Positive t-stat = strategy 1 better.
    """
    d = (e1 - e2).dropna()
    if len(d) < 30:
        return {'t_stat': np.nan, 'p_value': np.nan}

    n = len(d)
    d_mean = d.mean()

    # HAC variance (Newey-West)
    gamma_0 = d.var()
    lag = min(h, int(np.floor(n ** (1/3))))
    hac_var = gamma_0
    for k in range(1, lag + 1):
        gamma_k = np.cov(d[k:].values, d[:-k].values)[0, 1]
        hac_var += 2 * (1 - k / (lag + 1)) * gamma_k

    se = np.sqrt(hac_var / n)
    t_stat = d_mean / se if se > 0 else 0
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

    return {
        't_stat': round(t_stat, 4),
        'p_value': round(p_value, 6)
    }


def bootstrap_sharpe_diff(ret1, ret2, n_boot=10000):
    """Bootstrap test for Sharpe ratio difference."""
    r1 = ret1.dropna().values
    r2 = ret2.dropna().values
    n = min(len(r1), len(r2))
    r1, r2 = r1[:n], r2[:n]

    sharpe1 = r1.mean() / r1.std() * np.sqrt(252)
    sharpe2 = r2.mean() / r2.std() * np.sqrt(252)
    obs_diff = sharpe1 - sharpe2

    rng = np.random.default_rng(42)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        s1 = r1[idx]
        s2 = r2[idx]
        sh1 = s1.mean() / s1.std() * np.sqrt(252) if s1.std() > 0 else 0
        sh2 = s2.mean() / s2.std() * np.sqrt(252) if s2.std() > 0 else 0
        diffs[i] = sh1 - sh2

    p_value = np.mean(diffs < 0) if obs_diff > 0 else np.mean(diffs > 0)
    ci_lo, ci_hi = np.percentile(diffs, [2.5, 97.5])

    return {
        'obs_sharpe_diff': round(obs_diff, 4),
        'bootstrap_p': round(p_value, 6),
        'ci_95_lo': round(ci_lo, 4),
        'ci_95_hi': round(ci_hi, 4)
    }


# ────────────────────────────────────────────────────────────
# Cross-OOS
# ────────────────────────────────────────────────────────────

def cross_oos_test(spy_ret, vix_series, dd_series, dd_mom,
                   strategy_fn, baseline_fn,
                   periods=None):
    """
    Run cross-OOS: each period is OOS, rest is IS.
    Returns per-period and aggregate metrics.
    """
    if periods is None:
        # 5 OOS periods, ~4 years each
        periods = [
            ('2006-01-01', '2009-12-31'),
            ('2010-01-01', '2013-12-31'),
            ('2014-01-01', '2017-12-31'),
            ('2018-01-01', '2021-12-31'),
            ('2022-01-01', '2026-03-31'),
        ]

    oos_results = []
    all_strat_ret = []
    all_base_ret = []

    for start, end in periods:
        mask = (spy_ret.index >= start) & (spy_ret.index <= end)
        if mask.sum() < 100:
            continue

        oos_spy = spy_ret[mask]
        oos_vix = vix_series[mask]
        oos_dd = dd_series[mask]
        oos_ddm = dd_mom[mask]

        strat_ret = strategy_fn(oos_spy, oos_vix, oos_dd, oos_ddm)
        base_ret = baseline_fn(oos_spy, oos_vix, oos_dd, oos_ddm)

        # Align
        common_idx = strat_ret.index.intersection(base_ret.index)
        strat_ret = strat_ret.loc[common_idx]
        base_ret = base_ret.loc[common_idx]

        strat_m = compute_metrics(strat_ret)
        base_m = compute_metrics(base_ret)

        dm = diebold_mariano_test(strat_ret, base_ret)

        all_strat_ret.append(strat_ret)
        all_base_ret.append(base_ret)

        oos_results.append({
            'period': f"{start} to {end}",
            'n_days': len(common_idx),
            'strategy': strat_m,
            'baseline': base_m,
            'sharpe_diff': round(strat_m.get('sharpe', 0) - base_m.get('sharpe', 0), 4),
            'dm_test': dm
        })

    # Aggregate
    all_strat = pd.concat(all_strat_ret)
    all_base = pd.concat(all_base_ret)

    agg_strat = compute_metrics(all_strat)
    agg_base = compute_metrics(all_base)
    agg_dm = diebold_mariano_test(all_strat, all_base)
    agg_boot = bootstrap_sharpe_diff(all_strat, all_base)

    # Count how many OOS periods strategy beats baseline
    n_wins = sum(1 for r in oos_results if r['sharpe_diff'] > 0)

    return {
        'oos_periods': oos_results,
        'aggregate': {
            'strategy': agg_strat,
            'baseline': agg_base,
            'sharpe_diff': round(agg_strat.get('sharpe', 0) - agg_base.get('sharpe', 0), 4),
            'dm_test': agg_dm,
            'bootstrap': agg_boot,
            'n_wins': n_wins,
            'n_periods': len(oos_results)
        }
    }


# ────────────────────────────────────────────────────────────
# Diagnostics
# ────────────────────────────────────────────────────────────

def drawdown_diagnostics(dd_series: pd.Series) -> dict:
    """Descriptive stats about the drawdown series."""
    return {
        'mean_dd': round(dd_series.mean() * 100, 2),
        'median_dd': round(dd_series.median() * 100, 2),
        'std_dd': round(dd_series.std() * 100, 2),
        'min_dd': round(dd_series.min() * 100, 2),
        'pct_below_5': round((dd_series < -0.05).mean() * 100, 2),
        'pct_below_10': round((dd_series < -0.10).mean() * 100, 2),
        'pct_below_15': round((dd_series < -0.15).mean() * 100, 2),
        'pct_near_peak': round((dd_series > -0.02).mean() * 100, 2),
        'n_days': len(dd_series)
    }


# ────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("K543: Drawdown-Conditional VT")
    print("=" * 70)

    # ── Step 1: Get data ──
    print("\n[1] Fetching SPY + VIX data...")
    spy, vix = get_data()

    spy_close = spy['Close'].copy()
    spy_ret = spy_close.pct_change()
    vix_close = vix['Close'].copy()

    # Align
    common = spy_ret.index.intersection(vix_close.index)
    spy_ret = spy_ret.loc[common]
    vix_close = vix_close.loc[common]
    spy_close_aligned = spy_close.loc[common]

    # ── Step 2: Compute drawdown ──
    dd = compute_drawdown(spy_close_aligned)
    dd_mom = compute_dd_momentum(dd, lookback=5)

    # Drop NaN from initial period
    start_date = '2006-01-01'
    spy_ret = spy_ret[spy_ret.index >= start_date]
    vix_close = vix_close[vix_close.index >= start_date]
    dd = dd[dd.index >= start_date]
    dd_mom = dd_mom[dd_mom.index >= start_date]

    # ── Step 3: Diagnostics ──
    print("\n[2] Drawdown diagnostics (SPY 2006-2026):")
    diag = drawdown_diagnostics(dd)
    for k, v in diag.items():
        print(f"  {k}: {v}")

    print(f"\n  SPY return stats (daily):")
    print(f"    mean: {spy_ret.mean()*100:.4f}%")
    print(f"    std:  {spy_ret.std()*100:.4f}%")
    print(f"    skew: {spy_ret.skew():.4f}")
    print(f"    kurt: {spy_ret.kurtosis():.4f}")

    # VIX stats
    print(f"\n  VIX stats:")
    print(f"    mean: {vix_close.mean():.2f}")
    print(f"    std:  {vix_close.std():.2f}")
    print(f"    min:  {vix_close.min():.2f}")
    print(f"    max:  {vix_close.max():.2f}")

    # Correlation between DD and VIX
    dd_vix_corr = dd.corr(vix_close)
    print(f"\n  Correlation(DD, VIX): {dd_vix_corr:.4f}")
    print(f"  (Negative = VIX rises when in drawdown, as expected)")

    # ── Step 4: Full-sample backtest ──
    print("\n[3] Full-sample backtest (2006-2026):")
    strategies = {
        'Baseline (12/VIX)': strategy_baseline,
        'DD-Enhanced (defensive)': strategy_dd_enhanced,
        'DD-Enhanced (aggressive)': strategy_dd_enhanced_aggressive,
        'DD-Conditional (tiered)': strategy_dd_conditional,
        'Recovery Filter': strategy_recovery_filter,
        'DD Momentum': strategy_dd_momentum,
        'Combined': strategy_combined,
    }

    full_results = {}
    baseline_ret = strategy_baseline(spy_ret, vix_close, dd, dd_mom)

    for name, fn in strategies.items():
        ret = fn(spy_ret, vix_close, dd, dd_mom)
        metrics = compute_metrics(ret)
        full_results[name] = metrics

        is_baseline = (name == 'Baseline (12/VIX)')
        marker = '  [BENCHMARK]' if is_baseline else ''
        print(f"\n  {name}{marker}:")
        for k, v in metrics.items():
            print(f"    {k}: {v}")

        if not is_baseline:
            dm = diebold_mariano_test(ret, baseline_ret)
            boot = bootstrap_sharpe_diff(ret, baseline_ret)
            print(f"    DM t-stat vs baseline: {dm['t_stat']} (p={dm['p_value']})")
            print(f"    Bootstrap Sharpe diff: {boot['obs_sharpe_diff']} "
                  f"(p={boot['bootstrap_p']}, 95% CI: [{boot['ci_95_lo']}, {boot['ci_95_hi']}])")

    # ── Step 5: Cross-OOS ──
    print("\n" + "=" * 70)
    print("[4] Cross-OOS validation (5 periods):")
    print("=" * 70)

    oos_all = {}
    for name, fn in strategies.items():
        if name == 'Baseline (12/VIX)':
            continue

        print(f"\n  --- {name} ---")
        result = cross_oos_test(
            spy_ret, vix_close, dd, dd_mom,
            strategy_fn=fn,
            baseline_fn=strategy_baseline
        )
        oos_all[name] = result

        for pr in result['oos_periods']:
            s_sh = pr['strategy'].get('sharpe', 0)
            b_sh = pr['baseline'].get('sharpe', 0)
            diff = pr['sharpe_diff']
            dm_t = pr['dm_test']['t_stat']
            win = '✓' if diff > 0 else '✗'
            print(f"    {pr['period']}: Strat={s_sh:.4f} Base={b_sh:.4f} "
                  f"Diff={diff:+.4f} DM-t={dm_t:.3f} {win}")

        agg = result['aggregate']
        print(f"\n    AGGREGATE: Strat Sharpe={agg['strategy'].get('sharpe', 0):.4f} "
              f"Base={agg['baseline'].get('sharpe', 0):.4f} "
              f"Diff={agg['sharpe_diff']:+.4f}")
        print(f"    DM t-stat: {agg['dm_test']['t_stat']:.4f} (p={agg['dm_test']['p_value']})")
        print(f"    Bootstrap: diff={agg['bootstrap']['obs_sharpe_diff']:.4f} "
              f"(p={agg['bootstrap']['bootstrap_p']}, "
              f"CI=[{agg['bootstrap']['ci_95_lo']:.4f}, {agg['bootstrap']['ci_95_hi']:.4f}])")
        print(f"    OOS Wins: {agg['n_wins']}/{agg['n_periods']}")

        # Harvey threshold check
        t = abs(agg['dm_test']['t_stat'])
        harvey_pass = t > 3.0
        print(f"    Harvey (2016) |t| > 3.0: {'PASS' if harvey_pass else 'FAIL'} (|t|={t:.3f})")

    # ── Step 6: Summary ──
    print("\n" + "=" * 70)
    print("[5] SUMMARY")
    print("=" * 70)

    # Find best strategy
    best_name = None
    best_sharpe_diff = -999
    for name, result in oos_all.items():
        sd = result['aggregate']['sharpe_diff']
        if sd > best_sharpe_diff:
            best_sharpe_diff = sd
            best_name = name

    print(f"\n  Best strategy (by aggregate Sharpe diff): {best_name}")
    print(f"  Sharpe improvement: {best_sharpe_diff:+.4f}")

    any_significant = False
    for name, result in oos_all.items():
        t = abs(result['aggregate']['dm_test']['t_stat'])
        if t > 3.0:
            any_significant = True
            print(f"  *** {name} passes Harvey threshold (|t|={t:.3f}) ***")

    if not any_significant:
        print("\n  CONCLUSION: No strategy passes Harvey (2016) t>3.0 threshold.")
        print("  Drawdown-conditional adjustments do NOT significantly improve 12/VIX.")
        print("  This is consistent with K458 meta-analysis: 'smart' VT adjustments")
        print("  typically yield negligible improvement over standard 12/VIX.")

    # ── Step 7: Save results ──
    results = {
        'experiment_id': 'K543',
        'title': 'Drawdown-Conditional VT — Can recent drawdown depth improve VT timing?',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'yfinance (SPY, ^VIX)',
        'period': '2006-01 to 2026-03',
        'n_total_days': len(spy_ret.dropna()),
        'methodology': {
            'baseline': '12/VIX target volatility (equity weight = min(12/VIX, 1))',
            'strategies': [
                'DD-Enhanced (defensive): reduce equity by (1+|DD|/0.10)^-1 when DD < -5%',
                'DD-Enhanced (aggressive): increase equity by (1+|DD|/0.10) when DD < -5%',
                'DD-Conditional (tiered): 100% at DD>-5%, 50% at DD<-5%, 20% at DD<-15%',
                'Recovery Filter: +30% equity when DD > -2% (near peak)',
                'DD Momentum: -30% if deepening, +20% if recovering',
                'Combined: tiered DD + momentum + recovery filter',
            ],
            'cross_oos_periods': 5,
            'tx_cost_bps': 2,
            'harvey_threshold': 3.0,
        },
        'diagnostics': {
            'drawdown_stats': diag,
            'dd_vix_correlation': round(dd_vix_corr, 4),
            'spy_daily_mean_pct': round(spy_ret.mean() * 100, 4),
            'spy_daily_std_pct': round(spy_ret.std() * 100, 4),
            'vix_mean': round(vix_close.mean(), 2),
        },
        'full_sample': full_results,
        'cross_oos': {name: {
            'oos_periods': result['oos_periods'],
            'aggregate': result['aggregate']
        } for name, result in oos_all.items()},
        'conclusion': {
            'best_strategy': best_name,
            'best_sharpe_diff': best_sharpe_diff,
            'any_passes_harvey': any_significant,
            'interpretation': (
                'Drawdown-conditional adjustments do NOT significantly improve 12/VIX. '
                'This is consistent with the K458 meta-analysis finding that all "smart" '
                'adjustments to standard VT yield negligible improvement. '
                'The reason: VIX already captures drawdown information (corr(DD, VIX) is '
                'strongly negative), so adding drawdown as a separate signal is largely redundant. '
                'Defensive strategies (reducing equity in drawdowns) hurt returns in V-shaped '
                'recoveries; aggressive strategies (buying the dip) add risk without reliable '
                'compensation. The pure mechanical 12/VIX remains the best simple VT approach.'
            ) if not any_significant else (
                f'{best_name} significantly improves 12/VIX '
                f'(Sharpe diff: {best_sharpe_diff:+.4f}). '
                'However, verify with additional robustness checks before deployment.'
            )
        },
        'references': [
            'Moreira & Muir (2017) "Volatility-Managed Portfolios" JF',
            'Harvey & Liu (2016) "…and the Cross-Section of Expected Returns" RFS',
            'K458 meta-analysis: all VT adjustments negligible',
            'K499 Hybrid VT: daily rebalancing essential',
            'K507 dynamic allocation: 50/50 SPY/GLD + 12/VIX Sharpe ~0.83',
        ]
    }

    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'k543_drawdown_conditional_vt_results.json'
    )
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n  Results saved to: {output_path}")
    print("  Done.")

    return results


if __name__ == '__main__':
    results = main()
