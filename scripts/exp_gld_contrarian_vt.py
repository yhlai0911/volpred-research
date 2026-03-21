#!/usr/bin/env python3
"""
K54: GLD Contrarian VT Strategy
================================
K53 discovered GLD has NEGATIVE TSMOM loading in VT — VT acts as contrarian
for safe-haven assets. This experiment tests whether inverting VT for GLD
(increase GLD when VIX is high) improves portfolio performance.

Strategies tested:
1. Baseline: 50/50 SPY/GLD, both use 12/VIX (current)
2. Inverse GLD: SPY 12/VIX + GLD VIX/12 (capped at 1.0)
3. Static GLD: SPY 12/VIX + GLD fixed 50%
4. VIX Step GLD: SPY 12/VIX + GLD step function based on VIX
5. Hybrid contrarian: SPY 12/VIX + GLD (2 - 12/VIX, capped [0,1])
6. Buy-and-hold 50/50 (no VT at all)

All weights lagged, monthly rebalance, TC = 0.05% per trade.
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats

# ── Data ───────────────────────────────────────────────────────────
print("Downloading data...")
spy = yf.download('SPY', start='2006-01-01', progress=False)['Close'].squeeze()
gld = yf.download('GLD', start='2006-01-01', progress=False)['Close'].squeeze()
vix = yf.download('^VIX', start='2006-01-01', progress=False)['Close'].squeeze()
shy = yf.download('SHY', start='2006-01-01', progress=False)['Close'].squeeze()

# Align all series
idx = spy.index.intersection(gld.index).intersection(vix.index).intersection(shy.index)
spy, gld, vix, shy = spy.loc[idx], gld.loc[idx], vix.loc[idx], shy.loc[idx]

# Returns
ret_spy = spy.pct_change().dropna()
ret_gld = gld.pct_change().dropna()
ret_shy = shy.pct_change().dropna()

# Align returns
idx_ret = ret_spy.index.intersection(ret_gld.index).intersection(ret_shy.index)
ret_spy = ret_spy.loc[idx_ret]
ret_gld = ret_gld.loc[idx_ret]
ret_shy = ret_shy.loc[idx_ret]
vix_aligned = vix.reindex(idx_ret).ffill()

print(f"Data: {idx_ret[0].strftime('%Y-%m-%d')} to {idx_ret[-1].strftime('%Y-%m-%d')}, {len(idx_ret)} days")

# ── Strategy Functions ─────────────────────────────────────────────
TC = 0.0005  # 0.05% per trade

def monthly_rebalance_mask(dates):
    """Return boolean mask for month-end rebalance dates."""
    months = pd.Series(dates).dt.to_period('M')
    mask = months != months.shift(-1)
    mask.iloc[-1] = True
    mask.index = dates
    return mask

def compute_strategy(ret_spy, ret_gld, ret_shy, vix_series,
                     spy_weight_fn, gld_weight_fn, name,
                     spy_alloc=0.5, gld_alloc=0.5):
    """
    Compute portfolio return with monthly rebalancing and TC.

    spy_weight_fn(vix) -> equity weight for SPY sleeve [0, 1]
    gld_weight_fn(vix) -> equity weight for GLD sleeve [0, 1]

    Each sleeve: weight * asset_return + (1-weight) * SHY_return
    Portfolio = spy_alloc * SPY_sleeve + gld_alloc * GLD_sleeve
    """
    rebal_mask = monthly_rebalance_mask(ret_spy.index)

    # Initialize
    port_ret = pd.Series(0.0, index=ret_spy.index)
    prev_spy_w = None
    prev_gld_w = None
    current_spy_w = 0.5  # initial
    current_gld_w = 0.5

    for i, date in enumerate(ret_spy.index):
        # At rebalance dates, update weights using LAGGED VIX (previous day)
        if i > 0 and rebal_mask.iloc[i-1]:
            # Use VIX from the rebalance decision date (previous day)
            v = vix_series.iloc[i-1]
            current_spy_w = np.clip(spy_weight_fn(v), 0, 1)
            current_gld_w = np.clip(gld_weight_fn(v), 0, 1)

        # Calculate sleeve returns
        spy_sleeve = current_spy_w * ret_spy.iloc[i] + (1 - current_spy_w) * ret_shy.iloc[i]
        gld_sleeve = current_gld_w * ret_gld.iloc[i] + (1 - current_gld_w) * ret_shy.iloc[i]

        # Portfolio return
        daily_ret = spy_alloc * spy_sleeve + gld_alloc * gld_sleeve

        # Transaction costs at rebalance
        if i > 0 and rebal_mask.iloc[i-1]:
            if prev_spy_w is not None:
                tc = TC * (abs(current_spy_w - prev_spy_w) * spy_alloc +
                          abs(current_gld_w - prev_gld_w) * gld_alloc)
                daily_ret -= tc
            prev_spy_w = current_spy_w
            prev_gld_w = current_gld_w

        port_ret.iloc[i] = daily_ret

    return port_ret

def compute_metrics(returns, name, rf_annual=0.02):
    """Compute Sharpe, MDD, Calmar, Sortino."""
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = (ann_ret - rf_annual) / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = returns[returns < 0].std() * np.sqrt(252)
    sortino = (ann_ret - rf_annual) / downside if downside > 0 else 0

    # Sharpe t-stat
    n_years = len(returns) / 252
    sharpe_se = 1 / np.sqrt(n_years)
    sharpe_t = sharpe / sharpe_se

    return {
        'name': name,
        'ann_return': round(ann_ret * 100, 2),
        'ann_vol': round(ann_vol * 100, 2),
        'sharpe': round(sharpe, 3),
        'sharpe_t': round(sharpe_t, 2),
        'mdd': round(mdd * 100, 2),
        'calmar': round(calmar, 3),
        'sortino': round(sortino, 3),
        'n_days': len(returns),
        'n_years': round(n_years, 1),
    }

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test for equal predictive accuracy (using returns as loss)."""
    d = e1 - e2  # difference in returns
    n = len(d)
    mean_d = d.mean()
    # HAC variance (Newey-West with h-1 lags)
    var_d = d.var()
    for k in range(1, h):
        var_d += 2 * (1 - k/h) * np.cov(d[k:], d[:-k])[0,1]
    se_d = np.sqrt(var_d / n)
    t_stat = mean_d / se_d if se_d > 0 else 0
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))
    return t_stat, p_value

def sharpe_diff_test(r1, r2):
    """Test H0: Sharpe1 = Sharpe2 using Jobson-Korkie with Memmel correction."""
    n = len(r1)
    mu1, mu2 = r1.mean(), r2.mean()
    s1, s2 = r1.std(), r2.std()
    rho = np.corrcoef(r1, r2)[0, 1]

    sr1 = mu1 / s1
    sr2 = mu2 / s2

    # Jobson-Korkie statistic with Memmel correction
    theta = (1/n) * (2 * (1 - rho) + 0.5 * (sr1**2 + sr2**2 - 2*sr1*sr2*rho))
    z = (sr1 - sr2) / np.sqrt(theta) if theta > 0 else 0
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return z, p

# ── Define Strategies ──────────────────────────────────────────────
strategies = {
    'S0: Buy&Hold 50/50': {
        'spy_fn': lambda v: 1.0,
        'gld_fn': lambda v: 1.0,
        'desc': 'No VT, static 50/50 SPY/GLD'
    },
    'S1: Baseline 12/VIX': {
        'spy_fn': lambda v: min(12/v, 1.0),
        'gld_fn': lambda v: min(12/v, 1.0),
        'desc': 'Current: both SPY and GLD use 12/VIX'
    },
    'S2: Inverse GLD (VIX/12)': {
        'spy_fn': lambda v: min(12/v, 1.0),
        'gld_fn': lambda v: min(v/12, 1.0),
        'desc': 'SPY 12/VIX + GLD VIX/12 (capped 1.0)'
    },
    'S3: Static GLD 50%': {
        'spy_fn': lambda v: min(12/v, 1.0),
        'gld_fn': lambda v: 0.5,
        'desc': 'SPY 12/VIX + GLD always 50%'
    },
    'S4: VIX Step GLD': {
        'spy_fn': lambda v: min(12/v, 1.0),
        'gld_fn': lambda v: 1.0 if v > 25 else (0.8 if v > 20 else (0.5 if v > 15 else 0.3)),
        'desc': 'SPY 12/VIX + GLD step: VIX>25→100%, >20→80%, >15→50%, ≤15→30%'
    },
    'S5: Hybrid Contrarian': {
        'spy_fn': lambda v: min(12/v, 1.0),
        'gld_fn': lambda v: np.clip(2 - 12/v, 0, 1),
        'desc': 'SPY 12/VIX + GLD (2 - 12/VIX): mirror of SPY weight'
    },
    'S6: Mild Contrarian': {
        'spy_fn': lambda v: min(12/v, 1.0),
        'gld_fn': lambda v: np.clip(0.5 + (v - 15) * 0.03, 0.3, 1.0),
        'desc': 'SPY 12/VIX + GLD: 50% base + 3% per VIX point above 15'
    },
    'S7: Anti-corr Switch': {
        'spy_fn': lambda v: min(12/v, 1.0),
        'gld_fn': lambda v: 1.0 if v > 20 else min(12/v, 1.0),
        'desc': 'SPY 12/VIX + GLD: when VIX>20 go full GLD, else follow 12/VIX'
    },
}

# ── Run Experiments ────────────────────────────────────────────────
periods = {
    'full': ('2007-01-03', None),
    'oos': ('2023-01-03', None),
    'gfc': ('2008-01-01', '2010-12-31'),
    'covid': ('2020-01-01', '2021-06-30'),
    'post_covid': ('2021-07-01', '2023-12-31'),
}

results = {}
all_returns = {}

for period_name, (start, end) in periods.items():
    mask = ret_spy.index >= start
    if end:
        mask &= ret_spy.index <= end

    r_spy = ret_spy[mask]
    r_gld = ret_gld[mask]
    r_shy = ret_shy[mask]
    v = vix_aligned[mask]

    period_results = {}

    for strat_name, strat_config in strategies.items():
        port_ret = compute_strategy(r_spy, r_gld, r_shy, v,
                                     strat_config['spy_fn'], strat_config['gld_fn'],
                                     strat_name)
        metrics = compute_metrics(port_ret, strat_name)
        period_results[strat_name] = metrics

        if period_name == 'full':
            all_returns[strat_name] = port_ret

    results[period_name] = period_results

# ── Statistical Tests (Full Sample) ──────────────────────────────
baseline_ret = all_returns['S1: Baseline 12/VIX']
stat_tests = {}

for name, ret in all_returns.items():
    if name == 'S1: Baseline 12/VIX':
        continue
    z, p = sharpe_diff_test(ret.values, baseline_ret.values)
    stat_tests[name] = {
        'sharpe_diff_z': round(z, 3),
        'sharpe_diff_p': round(p, 4),
        'significant_0.05': p < 0.05,
    }

# ── Weight Analysis ──────────────────────────────────────────────
print("\n" + "="*80)
print("GLD Contrarian VT Strategy Analysis")
print("="*80)

# VIX distribution for context
full_vix = vix_aligned[ret_spy.index >= '2007-01-03']
print(f"\nVIX Distribution (2007-present):")
print(f"  Mean: {full_vix.mean():.1f}, Median: {full_vix.median():.1f}")
print(f"  P25: {full_vix.quantile(0.25):.1f}, P75: {full_vix.quantile(0.75):.1f}")
print(f"  % > 20: {(full_vix > 20).mean()*100:.1f}%, % > 25: {(full_vix > 25).mean()*100:.1f}%")

# Weight comparison at different VIX levels
vix_levels = [10, 12, 15, 18, 20, 25, 30, 40]
print(f"\n{'VIX':>4} | {'12/VIX':>7} | {'VIX/12':>7} | {'2-12/V':>7} | {'Step':>7} | {'Mild':>7} | {'Switch':>7}")
print("-" * 60)
for v in vix_levels:
    w_base = min(12/v, 1.0)
    w_inv = min(v/12, 1.0)
    w_hybrid = np.clip(2 - 12/v, 0, 1)
    w_step = 1.0 if v > 25 else (0.8 if v > 20 else (0.5 if v > 15 else 0.3))
    w_mild = np.clip(0.5 + (v - 15) * 0.03, 0.3, 1.0)
    w_switch = 1.0 if v > 20 else min(12/v, 1.0)
    print(f"{v:>4} | {w_base:>7.2f} | {w_inv:>7.2f} | {w_hybrid:>7.2f} | {w_step:>7.2f} | {w_mild:>7.2f} | {w_switch:>7.2f}")

# ── Results Display ──────────────────────────────────────────────
for period_name in ['full', 'oos', 'gfc', 'covid']:
    period_labels = {'full': 'Full Sample (2007-present)', 'oos': 'OOS (2023-present)',
                     'gfc': 'GFC (2008-2010)', 'covid': 'COVID (2020-2021H1)'}
    print(f"\n{'='*80}")
    print(f"  {period_labels.get(period_name, period_name)}")
    print(f"{'='*80}")
    print(f"{'Strategy':<30} | {'Sharpe':>7} | {'t-stat':>7} | {'MDD%':>7} | {'Calmar':>7} | {'Sortino':>7} | {'Ann%':>7}")
    print("-" * 95)

    for name in strategies:
        m = results[period_name][name]
        print(f"{name:<30} | {m['sharpe']:>7.3f} | {m['sharpe_t']:>7.2f} | {m['mdd']:>7.1f} | {m['calmar']:>7.3f} | {m['sortino']:>7.3f} | {m['ann_return']:>7.1f}")

# Statistical tests
print(f"\n{'='*80}")
print(f"  Sharpe Difference vs S1 Baseline (Jobson-Korkie-Memmel test)")
print(f"{'='*80}")
print(f"{'Strategy':<30} | {'ΔSharpe':>8} | {'z-stat':>8} | {'p-value':>8} | {'Sig?':>5}")
print("-" * 70)
for name, test in stat_tests.items():
    ds = results['full'][name]['sharpe'] - results['full']['S1: Baseline 12/VIX']['sharpe']
    sig = "YES" if test['significant_0.05'] else "no"
    print(f"{name:<30} | {ds:>+8.3f} | {test['sharpe_diff_z']:>8.3f} | {test['sharpe_diff_p']:>8.4f} | {sig:>5}")

# ── Crisis analysis: GLD behavior when VIX spikes ──────────────
print(f"\n{'='*80}")
print(f"  Crisis Decomposition: GLD behavior when VIX > 25")
print(f"{'='*80}")

full_mask = ret_spy.index >= '2007-01-03'
crisis_mask = vix_aligned[full_mask] > 25
normal_mask = ~crisis_mask

print(f"\nCrisis days: {crisis_mask.sum()} ({crisis_mask.mean()*100:.1f}%)")
print(f"Normal days: {normal_mask.sum()} ({normal_mask.mean()*100:.1f}%)")

# GLD return during crisis vs normal
gld_crisis = ret_gld[full_mask][crisis_mask]
gld_normal = ret_gld[full_mask][normal_mask]
spy_crisis = ret_spy[full_mask][crisis_mask]
spy_normal = ret_spy[full_mask][normal_mask]

print(f"\n{'':>15} | {'Crisis (VIX>25)':>18} | {'Normal (VIX≤25)':>18}")
print(f"{'':>15} | {'Ann Mean%':>8} {'Ann Vol%':>8} | {'Ann Mean%':>8} {'Ann Vol%':>8}")
print("-" * 65)
print(f"{'SPY':>15} | {spy_crisis.mean()*252*100:>8.1f} {spy_crisis.std()*np.sqrt(252)*100:>8.1f} | {spy_normal.mean()*252*100:>8.1f} {spy_normal.std()*np.sqrt(252)*100:>8.1f}")
print(f"{'GLD':>15} | {gld_crisis.mean()*252*100:>8.1f} {gld_crisis.std()*np.sqrt(252)*100:>8.1f} | {gld_normal.mean()*252*100:>8.1f} {gld_normal.std()*np.sqrt(252)*100:>8.1f}")
print(f"{'SPY-GLD corr':>15} | {np.corrcoef(spy_crisis, gld_crisis)[0,1]:>8.3f} {'':>8} | {np.corrcoef(spy_normal, gld_normal)[0,1]:>8.3f}")

# ── Correlation regime analysis ──────────────────────────────────
print(f"\n{'='*80}")
print(f"  Rolling 63d SPY-GLD Correlation by VIX Regime")
print(f"{'='*80}")

full_spy = ret_spy[full_mask]
full_gld = ret_gld[full_mask]
full_vix_s = vix_aligned[full_mask]

# Rolling correlation
roll_corr = full_spy.rolling(63).corr(full_gld)

for threshold in [15, 20, 25, 30]:
    high_vix = full_vix_s > threshold
    corr_high = roll_corr[high_vix].mean()
    corr_low = roll_corr[~high_vix].mean()
    n_high = high_vix.sum()
    print(f"  VIX > {threshold}: corr = {corr_high:.3f} (n={n_high:,d})  |  VIX ≤ {threshold}: corr = {corr_low:.3f}")

# ── Additional: GLD momentum during VIX spikes ──────────────────
print(f"\n{'='*80}")
print(f"  GLD Forward Returns After VIX Spike (VIX crosses above 25)")
print(f"{'='*80}")

# Identify VIX spike events (crosses above 25)
vix_above = full_vix_s > 25
spike_starts = vix_above & ~vix_above.shift(1, fill_value=False)
spike_dates = spike_starts[spike_starts].index

fwd_returns = {}
for h in [5, 10, 21, 63]:
    fwd = []
    for d in spike_dates:
        loc = full_gld.index.get_loc(d)
        if loc + h < len(full_gld):
            fwd_ret = (1 + full_gld.iloc[loc:loc+h]).prod() - 1
            fwd.append(fwd_ret)
    fwd = np.array(fwd)
    t_stat = fwd.mean() / (fwd.std() / np.sqrt(len(fwd))) if len(fwd) > 1 else 0
    fwd_returns[h] = {
        'mean': fwd.mean() * 100,
        'median': np.median(fwd) * 100,
        'win_rate': (fwd > 0).mean() * 100,
        't': t_stat,
        'n': len(fwd)
    }
    print(f"  {h:>2}d forward: mean={fwd.mean()*100:+.2f}%, median={np.median(fwd)*100:+.2f}%, "
          f"win={100*(fwd>0).mean():.0f}%, t={t_stat:.2f}, n={len(fwd)}")

# ── Save Results ─────────────────────────────────────────────────
output = {
    "experiment": "K54: GLD Contrarian VT — Inverse GLD Weight When VIX High",
    "description": "K53 showed GLD has negative TSMOM loading in VT (contrarian behavior). "
                   "This tests whether inverting GLD's VT weight (increase GLD when VIX high, "
                   "decrease when VIX low) improves the 50/50 SPY/GLD portfolio.",
    "proposed_by": "用戶 (inspired by K53)",
    "executed_by": "Claude",
    "timestamp": datetime.now().isoformat(),
    "config": {
        "start": "2007-01-03",
        "oos_start": "2023-01-03",
        "rebalance": "monthly",
        "tc_per_trade": TC,
        "spy_allocation": 0.5,
        "gld_allocation": 0.5,
        "cash_proxy": "SHY",
        "rf_annual": 0.02,
    },
    "strategies": {name: conf['desc'] for name, conf in strategies.items()},
    "results": {},
    "statistical_tests": stat_tests,
    "crisis_analysis": {
        "crisis_threshold": "VIX > 25",
        "crisis_days_pct": round(crisis_mask.mean() * 100, 1),
        "gld_crisis_ann_return_pct": round(gld_crisis.mean() * 252 * 100, 1),
        "gld_normal_ann_return_pct": round(gld_normal.mean() * 252 * 100, 1),
        "spy_gld_corr_crisis": round(float(np.corrcoef(spy_crisis, gld_crisis)[0,1]), 3),
        "spy_gld_corr_normal": round(float(np.corrcoef(spy_normal, gld_normal)[0,1]), 3),
    },
    "gld_forward_returns_after_vix_spike": {
        f"{h}d": {k: round(v, 2) if isinstance(v, float) else v for k, v in vals.items()}
        for h, vals in fwd_returns.items()
    },
    "vix_distribution": {
        "mean": round(float(full_vix.mean()), 1),
        "median": round(float(full_vix.median()), 1),
        "pct_above_20": round(float((full_vix > 20).mean() * 100), 1),
        "pct_above_25": round(float((full_vix > 25).mean() * 100), 1),
    },
}

# Add period results
for period_name in results:
    output['results'][period_name] = {}
    for strat_name in results[period_name]:
        output['results'][period_name][strat_name] = results[period_name][strat_name]

# ── Conclusion ───────────────────────────────────────────────────
# Find best strategy per period
best = {}
for period in ['full', 'oos']:
    by_sharpe = sorted(results[period].items(), key=lambda x: x[1]['sharpe'], reverse=True)
    by_mdd = sorted(results[period].items(), key=lambda x: x[1]['mdd'], reverse=True)  # less negative = better
    best[period] = {
        'best_sharpe': by_sharpe[0][0],
        'best_sharpe_val': by_sharpe[0][1]['sharpe'],
        'best_mdd': by_mdd[0][0],
        'best_mdd_val': by_mdd[0][1]['mdd'],
    }

# Any significant improvement?
any_significant = any(t['significant_0.05'] for t in stat_tests.values())
best_contrarian = max(
    [(n, results['full'][n]['sharpe']) for n in strategies if n != 'S1: Baseline 12/VIX'],
    key=lambda x: x[1]
)

conclusion_lines = []
conclusion_lines.append(f"Best contrarian: {best_contrarian[0]} (Sharpe={best_contrarian[1]:.3f})")
conclusion_lines.append(f"Baseline: S1 (Sharpe={results['full']['S1: Baseline 12/VIX']['sharpe']:.3f})")
conclusion_lines.append(f"Any significant improvement over baseline? {'YES' if any_significant else 'NO'}")

if not any_significant:
    conclusion_lines.append("CONCLUSION: No contrarian VT variant significantly beats the simple 12/VIX baseline.")
    conclusion_lines.append("K53's negative TSMOM loading does NOT translate to a tradeable contrarian signal.")
    conclusion_lines.append("The 12/VIX rule remains the best simple VT for the 50/50 portfolio.")
else:
    sig_names = [n for n, t in stat_tests.items() if t['significant_0.05']]
    conclusion_lines.append(f"Significant improvements: {sig_names}")

output['conclusion'] = conclusion_lines
output['best_by_period'] = best

print(f"\n{'='*80}")
print(f"  CONCLUSION")
print(f"{'='*80}")
for line in conclusion_lines:
    print(f"  {line}")

# Save
outpath = '/Users/yhlai0911/Desktop/volpred-research/storage/experiments/gld_contrarian_vt.json'
with open(outpath, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)
print(f"\nSaved to {outpath}")
