#!/usr/bin/env python3
"""
K347: Multi-Instrument Optimal Hedge — SPY + GLD + JPY + ZN Combined
=====================================================================
[提出: 用戶, 執行: Claude]

Background:
  K341: Futures hedging framework (VIX>25 tail hedge most efficient)
  K344: Gold uniquely uncorrelated, adding other commodities hurts
  K345: JPY is daily tail hedge (t=4.91), GLD is long-term diversifier
  K269: SPY-GLD correlation unstable (-0.61 to +0.69)

Key Insight: GLD and JPY provide DIFFERENT types of hedging.
  GLD = long-term diversification. JPY = daily crash protection.
  Can we COMBINE them?

Data: yfinance — SPY, GLD, JPYUSD=X, ZN=F (10yr Treasury Note futures), ^VIX
Methodology:
  1. 4-instrument correlation matrix (full + by VIX regime)
  2. Portfolio construction:
     a. SPY + GLD (benchmark 50/50)
     b. SPY + GLD + JPY (add tail hedge)
     c. SPY + GLD + JPY + ZN (full diversification)
     d. Weights: equal, risk parity, minimum variance
  3. Compare: Sharpe, MDD, tail performance (SPY drops >2%)
  4. KEY QUESTION: does adding JPY to SPY/GLD IMPROVE the portfolio?
  5. 5-period cross-OOS validation

Author: VolPred Research System
Date: 2026-03-25
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from scipy.optimize import minimize
import json
import warnings
warnings.filterwarnings('ignore')

RESULTS = {}

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 80)
print("K347: Multi-Instrument Optimal Hedge — SPY + GLD + JPY + ZN Combined")
print("=" * 80)

tickers = {
    'SPY': 'SPY',
    'GLD': 'GLD',
    'JPY': 'JPYUSD=X',
    'ZN': 'ZN=F',
    'VIX': '^VIX',
}

print("\n[1] Downloading data from yfinance...")
raw = {}
for name, ticker in tickers.items():
    try:
        df = yf.download(ticker, start='2005-01-01', end='2026-03-25',
                         progress=False, auto_adjust=True)
        close = df['Close'].squeeze()
        if len(close) > 100:
            raw[name] = close
            print(f"  {name:5s} ({ticker:12s}): {len(close):,} days, "
                  f"{close.index[0].strftime('%Y-%m-%d')} to "
                  f"{close.index[-1].strftime('%Y-%m-%d')}")
        else:
            print(f"  {name}: insufficient data ({len(close)} rows)")
    except Exception as e:
        print(f"  {name}: FAILED — {e}")

# If ZN=F fails, try TLT as bond proxy
if 'ZN' not in raw or len(raw['ZN']) < 100:
    print("  ZN=F insufficient, trying TLT (20yr Treasury ETF) as bond proxy...")
    try:
        df = yf.download('TLT', start='2005-01-01', end='2026-03-25',
                         progress=False, auto_adjust=True)
        close = df['Close'].squeeze()
        if len(close) > 100:
            raw['ZN'] = close
            print(f"  TLT (proxy for ZN): {len(close):,} days")
    except Exception as e:
        print(f"  TLT also failed: {e}")

# Build returns
print("\n[1b] Building returns...")
asset_returns = {}
for name in ['SPY', 'GLD', 'JPY', 'ZN']:
    if name in raw:
        asset_returns[name] = raw[name].pct_change().dropna()

# Common date range
common_idx = asset_returns['SPY'].index
for name in ['GLD', 'JPY', 'ZN']:
    if name in asset_returns:
        common_idx = common_idx.intersection(asset_returns[name].index)

# VIX levels for regime analysis
vix_levels = raw['VIX'].reindex(common_idx).ffill()

# Aligned returns
ret_df = pd.DataFrame({name: asset_returns[name].reindex(common_idx)
                        for name in ['SPY', 'GLD', 'JPY', 'ZN']
                        if name in asset_returns}).dropna()
common_idx = ret_df.index
vix_levels = vix_levels.reindex(common_idx).ffill().dropna()
ret_df = ret_df.loc[vix_levels.index]
common_idx = ret_df.index

print(f"  Common period: {common_idx[0].strftime('%Y-%m-%d')} to "
      f"{common_idx[-1].strftime('%Y-%m-%d')} ({len(common_idx):,} days)")
print(f"  Assets available: {list(ret_df.columns)}")

RESULTS['data'] = {
    'period': f"{common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}",
    'n_days': len(common_idx),
    'assets': list(ret_df.columns),
    'source': 'yfinance (SPY, GLD, JPYUSD=X, ZN=F/TLT, ^VIX)',
}

# ============================================================
# 2. CORRELATION MATRIX (Full Sample + VIX Regimes)
# ============================================================
print("\n" + "=" * 80)
print("[2] CORRELATION MATRIX")
print("=" * 80)

# Full sample
corr_full = ret_df.corr()
print("\n--- Full Sample Correlation ---")
print(corr_full.round(3).to_string())

# VIX regime thresholds
vix_low_mask = vix_levels < 15
vix_mid_mask = (vix_levels >= 15) & (vix_levels < 25)
vix_high_mask = vix_levels >= 25

print(f"\nVIX regime counts: Low(<15)={vix_low_mask.sum()}, "
      f"Mid(15-25)={vix_mid_mask.sum()}, High(>25)={vix_high_mask.sum()}")

regime_corrs = {}
for regime_name, mask in [('low_vix<15', vix_low_mask),
                           ('mid_vix15-25', vix_mid_mask),
                           ('high_vix>25', vix_high_mask)]:
    sub = ret_df.loc[mask]
    if len(sub) > 50:
        c = sub.corr()
        regime_corrs[regime_name] = c
        print(f"\n--- {regime_name} (n={len(sub)}) ---")
        print(c.round(3).to_string())

RESULTS['correlations'] = {
    'full_sample': corr_full.to_dict(),
    'spy_gld': float(corr_full.loc['SPY', 'GLD']),
    'spy_jpy': float(corr_full.loc['SPY', 'JPY']),
    'spy_zn': float(corr_full.loc['SPY', 'ZN']),
    'gld_jpy': float(corr_full.loc['GLD', 'JPY']),
    'gld_zn': float(corr_full.loc['GLD', 'ZN']),
    'jpy_zn': float(corr_full.loc['JPY', 'ZN']),
}

# Key: correlations shift under stress
if 'high_vix>25' in regime_corrs:
    hc = regime_corrs['high_vix>25']
    lc = regime_corrs['low_vix<15']
    print("\n--- Correlation SHIFT (High VIX - Low VIX) ---")
    shift = hc - lc
    print(shift.round(3).to_string())
    RESULTS['correlations']['stress_shift'] = {
        'spy_gld': float(shift.loc['SPY', 'GLD']),
        'spy_jpy': float(shift.loc['SPY', 'JPY']),
        'spy_zn': float(shift.loc['SPY', 'ZN']),
    }

# ============================================================
# 3. PORTFOLIO CONSTRUCTION
# ============================================================
print("\n" + "=" * 80)
print("[3] PORTFOLIO CONSTRUCTION")
print("=" * 80)


def portfolio_metrics(weights, ret_df, label=""):
    """Calculate portfolio metrics given weights."""
    w = np.array(weights)
    cols = ret_df.columns.tolist()
    port_ret = (ret_df[cols] * w).sum(axis=1)

    ann_ret = port_ret.mean() * 252
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + port_ret).cumprod()
    drawdown = cum / cum.cummax() - 1
    mdd = drawdown.min()

    # Tail performance: days when SPY drops > 2%
    spy_crash = ret_df['SPY'] < -0.02
    n_crash = spy_crash.sum()
    if n_crash > 0:
        tail_ret = port_ret[spy_crash].mean() * 100  # in %
        tail_vol = port_ret[spy_crash].std() * 100
    else:
        tail_ret = 0
        tail_vol = 0

    # Calmar ratio
    calmar = ann_ret / abs(mdd) if abs(mdd) > 0 else 0

    # Sortino ratio
    downside = port_ret[port_ret < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    # Skewness and kurtosis
    skew = float(port_ret.skew())
    kurt = float(port_ret.kurtosis())

    return {
        'label': label,
        'weights': {cols[i]: round(float(w[i]), 4) for i in range(len(w))},
        'ann_return': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 4),
        'mdd': round(float(mdd), 4),
        'calmar': round(float(calmar), 4),
        'sortino': round(float(sortino), 4),
        'skewness': round(skew, 4),
        'kurtosis': round(kurt, 4),
        'n_crash_days': int(n_crash),
        'tail_avg_return_pct': round(float(tail_ret), 4),
        'tail_vol_pct': round(float(tail_vol), 4),
        'port_returns': port_ret,  # keep for OOS
    }


def risk_parity_weights(ret_df):
    """Calculate risk parity weights (inverse volatility)."""
    vols = ret_df.std()
    inv_vols = 1.0 / vols
    return (inv_vols / inv_vols.sum()).values


def min_variance_weights(ret_df):
    """Calculate minimum variance portfolio weights (long-only)."""
    cov = ret_df.cov().values
    n = len(ret_df.columns)

    def objective(w):
        return w @ cov @ w

    constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1}]
    bounds = [(0.0, 1.0)] * n
    w0 = np.ones(n) / n

    res = minimize(objective, w0, method='SLSQP',
                   bounds=bounds, constraints=constraints)
    return res.x if res.success else w0


# --- Define portfolio configurations ---
assets_all = list(ret_df.columns)  # SPY, GLD, JPY, ZN
n_assets = len(assets_all)

# Portfolio A: SPY + GLD only
idx_a = [assets_all.index('SPY'), assets_all.index('GLD')]
# Portfolio B: SPY + GLD + JPY
idx_b = [assets_all.index('SPY'), assets_all.index('GLD'), assets_all.index('JPY')]
# Portfolio C: SPY + GLD + JPY + ZN (all four)
idx_c = list(range(n_assets))

portfolio_configs = []

# --- A: SPY + GLD ---
for scheme, weight_func in [
    ('EW', lambda df: np.ones(len(df.columns)) / len(df.columns)),
    ('RP', risk_parity_weights),
    ('MV', min_variance_weights),
]:
    sub_df = ret_df[['SPY', 'GLD']]
    w_sub = weight_func(sub_df)
    # Map to full weight vector
    w_full = np.zeros(n_assets)
    for i, col in enumerate(['SPY', 'GLD']):
        w_full[assets_all.index(col)] = w_sub[i]
    label = f"A_{scheme}_SPY+GLD"
    portfolio_configs.append((label, w_full))

# Special: 50/50 SPY/GLD (our benchmark)
w_5050 = np.zeros(n_assets)
w_5050[assets_all.index('SPY')] = 0.5
w_5050[assets_all.index('GLD')] = 0.5
portfolio_configs.append(("A_50-50_SPY+GLD", w_5050))

# --- B: SPY + GLD + JPY ---
for scheme, weight_func in [
    ('EW', lambda df: np.ones(len(df.columns)) / len(df.columns)),
    ('RP', risk_parity_weights),
    ('MV', min_variance_weights),
]:
    sub_df = ret_df[['SPY', 'GLD', 'JPY']]
    w_sub = weight_func(sub_df)
    w_full = np.zeros(n_assets)
    for i, col in enumerate(['SPY', 'GLD', 'JPY']):
        w_full[assets_all.index(col)] = w_sub[i]
    label = f"B_{scheme}_SPY+GLD+JPY"
    portfolio_configs.append((label, w_full))

# --- C: SPY + GLD + JPY + ZN ---
for scheme, weight_func in [
    ('EW', lambda df: np.ones(len(df.columns)) / len(df.columns)),
    ('RP', risk_parity_weights),
    ('MV', min_variance_weights),
]:
    sub_df = ret_df[['SPY', 'GLD', 'JPY', 'ZN']]
    w_sub = weight_func(sub_df)
    label = f"C_{scheme}_SPY+GLD+JPY+ZN"
    portfolio_configs.append((label, w_sub))

# Special: 40/20/20/20 (SPY-heavy with equal hedge allocation)
w_custom = np.zeros(n_assets)
w_custom[assets_all.index('SPY')] = 0.40
w_custom[assets_all.index('GLD')] = 0.20
w_custom[assets_all.index('JPY')] = 0.20
w_custom[assets_all.index('ZN')] = 0.20
portfolio_configs.append(("C_40-20-20-20", w_custom))

# Special: 60/15/10/15 (moderate diversification)
w_mod = np.zeros(n_assets)
w_mod[assets_all.index('SPY')] = 0.60
w_mod[assets_all.index('GLD')] = 0.15
w_mod[assets_all.index('JPY')] = 0.10
w_mod[assets_all.index('ZN')] = 0.15
portfolio_configs.append(("C_60-15-10-15", w_mod))

# --- 100% SPY (benchmark) ---
w_spy = np.zeros(n_assets)
w_spy[assets_all.index('SPY')] = 1.0
portfolio_configs.append(("Benchmark_100%SPY", w_spy))

# --- Run all ---
print(f"\nEvaluating {len(portfolio_configs)} portfolio configurations...\n")
print(f"{'Portfolio':<30s} {'Sharpe':>7s} {'AnnRet':>7s} {'AnnVol':>7s} "
      f"{'MDD':>7s} {'Calmar':>7s} {'TailAvg%':>9s} {'Skew':>6s}")
print("-" * 105)

all_results = {}
for label, weights in portfolio_configs:
    m = portfolio_metrics(weights, ret_df, label)
    all_results[label] = m
    print(f"  {label:<28s} {m['sharpe']:>7.3f} {m['ann_return']:>7.3f} "
          f"{m['ann_vol']:>7.3f} {m['mdd']:>7.3f} {m['calmar']:>7.3f} "
          f"{m['tail_avg_return_pct']:>9.4f} {m['skewness']:>6.3f}")

# Store (without port_returns Series)
RESULTS['portfolios'] = {}
for label, m in all_results.items():
    m_copy = {k: v for k, v in m.items() if k != 'port_returns'}
    RESULTS['portfolios'][label] = m_copy

# ============================================================
# 4. KEY COMPARISON: Does Adding JPY/ZN Help?
# ============================================================
print("\n" + "=" * 80)
print("[4] KEY COMPARISON: Does Adding JPY/ZN to SPY+GLD Help?")
print("=" * 80)

# Compare best-in-class from each group
groups = {
    'A (SPY+GLD)': [k for k in all_results if k.startswith('A_')],
    'B (SPY+GLD+JPY)': [k for k in all_results if k.startswith('B_')],
    'C (SPY+GLD+JPY+ZN)': [k for k in all_results if k.startswith('C_')],
}

print("\nBest Sharpe in each group:")
for group_name, keys in groups.items():
    best = max(keys, key=lambda k: all_results[k]['sharpe'])
    m = all_results[best]
    print(f"  {group_name}: {best} (Sharpe={m['sharpe']:.3f}, "
          f"MDD={m['mdd']:.3f}, TailAvg={m['tail_avg_return_pct']:.4f}%)")

print("\nBest Tail Performance (smallest loss during SPY crashes):")
for group_name, keys in groups.items():
    best = max(keys, key=lambda k: all_results[k]['tail_avg_return_pct'])
    m = all_results[best]
    print(f"  {group_name}: {best} (TailAvg={m['tail_avg_return_pct']:.4f}%, "
          f"Sharpe={m['sharpe']:.3f})")

print("\nShallowest MDD in each group:")
for group_name, keys in groups.items():
    best = max(keys, key=lambda k: all_results[k]['mdd'])  # mdd is negative, max = shallowest
    m = all_results[best]
    print(f"  {group_name}: {best} (MDD={m['mdd']:.3f}, Sharpe={m['sharpe']:.3f})")

# ============================================================
# 5. STATISTICAL TESTS — Is the difference significant?
# ============================================================
print("\n" + "=" * 80)
print("[5] STATISTICAL TESTS — Sharpe Ratio Differences")
print("=" * 80)

# Jobson-Korkie test for Sharpe ratio difference (simplified)
def sharpe_diff_test(ret1, ret2, label1, label2):
    """Test if Sharpe ratios differ using HAC-robust approach (Ledoit & Wolf 2008 simplified)."""
    n = len(ret1)
    mu1, mu2 = ret1.mean(), ret2.mean()
    s1, s2 = ret1.std(), ret2.std()
    sr1 = mu1 / s1 * np.sqrt(252) if s1 > 0 else 0
    sr2 = mu2 / s2 * np.sqrt(252) if s2 > 0 else 0

    # Bootstrap test
    np.random.seed(42)
    n_boot = 10000
    boot_diff = np.zeros(n_boot)
    for b in range(n_boot):
        idx = np.random.choice(n, n, replace=True)
        r1b, r2b = ret1.iloc[idx], ret2.iloc[idx]
        sr1b = r1b.mean() / r1b.std() * np.sqrt(252) if r1b.std() > 0 else 0
        sr2b = r2b.mean() / r2b.std() * np.sqrt(252) if r2b.std() > 0 else 0
        boot_diff[b] = sr2b - sr1b

    observed_diff = sr2 - sr1
    p_value = np.mean(boot_diff <= 0) if observed_diff > 0 else np.mean(boot_diff >= 0)
    se = boot_diff.std()
    t_stat = observed_diff / se if se > 0 else 0

    return {
        'sr1': round(sr1, 4), 'sr2': round(sr2, 4),
        'diff': round(observed_diff, 4),
        't_stat': round(t_stat, 4),
        'p_value': round(p_value, 4),
        'se': round(se, 4),
        'ci_95': [round(np.percentile(boot_diff, 2.5), 4),
                  round(np.percentile(boot_diff, 97.5), 4)],
    }

# Key comparisons
comparisons = [
    # Does adding JPY to SPY+GLD help?
    ('A_50-50_SPY+GLD', 'B_EW_SPY+GLD+JPY', "50/50 SPY+GLD vs EW SPY+GLD+JPY"),
    ('A_50-50_SPY+GLD', 'B_RP_SPY+GLD+JPY', "50/50 SPY+GLD vs RP SPY+GLD+JPY"),
    ('A_50-50_SPY+GLD', 'B_MV_SPY+GLD+JPY', "50/50 SPY+GLD vs MV SPY+GLD+JPY"),
    # Does adding ZN on top of JPY help?
    ('B_RP_SPY+GLD+JPY', 'C_RP_SPY+GLD+JPY+ZN', "RP 3-asset vs RP 4-asset"),
    # Best 4-asset vs benchmark
    ('A_50-50_SPY+GLD', 'C_MV_SPY+GLD+JPY+ZN', "50/50 vs MV 4-asset"),
    ('Benchmark_100%SPY', 'C_MV_SPY+GLD+JPY+ZN', "100% SPY vs MV 4-asset"),
]

RESULTS['tests'] = {}
for k1, k2, desc in comparisons:
    r1 = all_results[k1]['port_returns']
    r2 = all_results[k2]['port_returns']
    test = sharpe_diff_test(r1, r2, k1, k2)
    sig = "***" if abs(test['t_stat']) > 3.0 else "**" if abs(test['t_stat']) > 2.0 else "*" if abs(test['t_stat']) > 1.65 else ""
    print(f"\n  {desc}:")
    print(f"    SR1={test['sr1']:.3f}, SR2={test['sr2']:.3f}, "
          f"Diff={test['diff']:+.4f}, t={test['t_stat']:.3f} {sig}, "
          f"p={test['p_value']:.4f}")
    print(f"    95% CI: [{test['ci_95'][0]:.4f}, {test['ci_95'][1]:.4f}]")
    RESULTS['tests'][desc] = test

# ============================================================
# 6. TAIL ANALYSIS — Behavior During SPY Crashes
# ============================================================
print("\n" + "=" * 80)
print("[6] TAIL ANALYSIS — Behavior During SPY Crashes (SPY < -2%)")
print("=" * 80)

spy_crash_mask = ret_df['SPY'] < -0.02
n_crash = spy_crash_mask.sum()
print(f"\nTotal SPY crash days (< -2%): {n_crash}")

# Individual asset behavior during crashes
print("\n--- Individual Asset Returns During SPY Crashes ---")
for col in ret_df.columns:
    crash_rets = ret_df.loc[spy_crash_mask, col]
    avg = crash_rets.mean() * 100
    med = crash_rets.median() * 100
    pos_pct = (crash_rets > 0).mean() * 100
    t, p = stats.ttest_1samp(crash_rets, 0)
    print(f"  {col:5s}: avg={avg:+.3f}%, median={med:+.3f}%, "
          f"positive={pos_pct:.1f}%, t={t:.2f}, p={p:.4f}")

RESULTS['tail_analysis'] = {
    'n_crash_days': int(n_crash),
    'individual_during_crash': {},
}
for col in ret_df.columns:
    crash_rets = ret_df.loc[spy_crash_mask, col]
    t, p = stats.ttest_1samp(crash_rets, 0)
    RESULTS['tail_analysis']['individual_during_crash'][col] = {
        'avg_pct': round(float(crash_rets.mean() * 100), 4),
        'median_pct': round(float(crash_rets.median() * 100), 4),
        'positive_pct': round(float((crash_rets > 0).mean() * 100), 2),
        't_stat': round(float(t), 4),
        'p_value': round(float(p), 4),
    }

# Portfolio tail performance
print("\n--- Portfolio Returns During SPY Crashes ---")
print(f"{'Portfolio':<30s} {'AvgRet%':>8s} {'MedRet%':>8s} {'Pos%':>6s}")
print("-" * 56)

key_ports = ['Benchmark_100%SPY', 'A_50-50_SPY+GLD', 'A_RP_SPY+GLD',
             'B_EW_SPY+GLD+JPY', 'B_RP_SPY+GLD+JPY', 'B_MV_SPY+GLD+JPY',
             'C_EW_SPY+GLD+JPY+ZN', 'C_RP_SPY+GLD+JPY+ZN', 'C_MV_SPY+GLD+JPY+ZN',
             'C_40-20-20-20', 'C_60-15-10-15']

RESULTS['tail_analysis']['portfolios_during_crash'] = {}
for label in key_ports:
    if label in all_results:
        p_ret = all_results[label]['port_returns']
        crash_ret = p_ret[spy_crash_mask]
        avg = crash_ret.mean() * 100
        med = crash_ret.median() * 100
        pos = (crash_ret > 0).mean() * 100
        print(f"  {label:<28s} {avg:>+8.4f} {med:>+8.4f} {pos:>6.1f}")
        RESULTS['tail_analysis']['portfolios_during_crash'][label] = {
            'avg_pct': round(float(avg), 4),
            'median_pct': round(float(med), 4),
            'positive_pct': round(float(pos), 2),
        }

# ============================================================
# 7. 5-PERIOD CROSS-OOS VALIDATION
# ============================================================
print("\n" + "=" * 80)
print("[7] 5-PERIOD CROSS-OOS VALIDATION")
print("=" * 80)

# Split into 5 roughly equal periods
n_total = len(ret_df)
period_size = n_total // 5
periods = []
for i in range(5):
    start_idx = i * period_size
    end_idx = (i + 1) * period_size if i < 4 else n_total
    p_df = ret_df.iloc[start_idx:end_idx]
    periods.append(p_df)
    print(f"  Period {i+1}: {p_df.index[0].strftime('%Y-%m-%d')} to "
          f"{p_df.index[-1].strftime('%Y-%m-%d')} ({len(p_df)} days)")

# For each OOS period, train on the other 4 and evaluate on this one
print("\n--- Cross-OOS: Train weights on 4 periods, test on 1 ---")

oos_results = {label: [] for label in ['A_50-50_SPY+GLD', 'A_RP_SPY+GLD',
                                         'B_RP_SPY+GLD+JPY', 'B_MV_SPY+GLD+JPY',
                                         'C_RP_SPY+GLD+JPY+ZN', 'C_MV_SPY+GLD+JPY+ZN',
                                         'C_40-20-20-20', 'C_60-15-10-15',
                                         'Benchmark_100%SPY']}

for oos_i in range(5):
    # Training data: all except oos_i
    train_dfs = [periods[j] for j in range(5) if j != oos_i]
    train_df = pd.concat(train_dfs)
    test_df = periods[oos_i]

    # Compute weights on training data, apply on test data
    # Fixed-weight portfolios
    for label, w in [('A_50-50_SPY+GLD', w_5050),
                     ('C_40-20-20-20', w_custom),
                     ('C_60-15-10-15', w_mod),
                     ('Benchmark_100%SPY', w_spy)]:
        m = portfolio_metrics(w, test_df, label)
        oos_results[label].append(m['sharpe'])

    # RP / MV computed on training data, applied to test
    # A_RP
    sub_train = train_df[['SPY', 'GLD']]
    w_rp_a = risk_parity_weights(sub_train)
    w_full_rp_a = np.zeros(n_assets)
    for i, col in enumerate(['SPY', 'GLD']):
        w_full_rp_a[assets_all.index(col)] = w_rp_a[i]
    m = portfolio_metrics(w_full_rp_a, test_df, 'A_RP')
    oos_results['A_RP_SPY+GLD'].append(m['sharpe'])

    # B_RP
    sub_train = train_df[['SPY', 'GLD', 'JPY']]
    w_rp_b = risk_parity_weights(sub_train)
    w_full_rp_b = np.zeros(n_assets)
    for i, col in enumerate(['SPY', 'GLD', 'JPY']):
        w_full_rp_b[assets_all.index(col)] = w_rp_b[i]
    m = portfolio_metrics(w_full_rp_b, test_df, 'B_RP')
    oos_results['B_RP_SPY+GLD+JPY'].append(m['sharpe'])

    # B_MV
    sub_train = train_df[['SPY', 'GLD', 'JPY']]
    w_mv_b = min_variance_weights(sub_train)
    w_full_mv_b = np.zeros(n_assets)
    for i, col in enumerate(['SPY', 'GLD', 'JPY']):
        w_full_mv_b[assets_all.index(col)] = w_mv_b[i]
    m = portfolio_metrics(w_full_mv_b, test_df, 'B_MV')
    oos_results['B_MV_SPY+GLD+JPY'].append(m['sharpe'])

    # C_RP
    w_rp_c = risk_parity_weights(train_df)
    m = portfolio_metrics(w_rp_c, test_df, 'C_RP')
    oos_results['C_RP_SPY+GLD+JPY+ZN'].append(m['sharpe'])

    # C_MV
    w_mv_c = min_variance_weights(train_df)
    m = portfolio_metrics(w_mv_c, test_df, 'C_MV')
    oos_results['C_MV_SPY+GLD+JPY+ZN'].append(m['sharpe'])

print(f"\n{'Portfolio':<30s} {'P1':>7s} {'P2':>7s} {'P3':>7s} {'P4':>7s} {'P5':>7s} {'Mean':>7s} {'Std':>7s}")
print("-" * 93)

RESULTS['oos_validation'] = {}
for label in oos_results:
    srs = oos_results[label]
    if len(srs) == 5:
        mean_sr = np.mean(srs)
        std_sr = np.std(srs)
        vals = " ".join(f"{s:>7.3f}" for s in srs)
        print(f"  {label:<28s} {vals} {mean_sr:>7.3f} {std_sr:>7.3f}")
        RESULTS['oos_validation'][label] = {
            'period_sharpes': [round(s, 4) for s in srs],
            'mean_sharpe': round(float(mean_sr), 4),
            'std_sharpe': round(float(std_sr), 4),
        }

# Statistical test: Is mean OOS Sharpe of best multi-asset > SPY+GLD?
print("\n--- OOS Sharpe Paired t-tests ---")
baseline_oos = oos_results['A_50-50_SPY+GLD']

for label in ['B_RP_SPY+GLD+JPY', 'B_MV_SPY+GLD+JPY',
              'C_RP_SPY+GLD+JPY+ZN', 'C_MV_SPY+GLD+JPY+ZN',
              'C_40-20-20-20']:
    if label in oos_results and len(oos_results[label]) == 5:
        diffs = [oos_results[label][i] - baseline_oos[i] for i in range(5)]
        t, p = stats.ttest_1samp(diffs, 0)
        mean_diff = np.mean(diffs)
        print(f"  {label} vs A_50-50: diff={mean_diff:+.4f}, t={t:.3f}, p={p:.4f}")
        RESULTS['oos_validation'][f'test_{label}_vs_baseline'] = {
            'mean_diff': round(float(mean_diff), 4),
            't_stat': round(float(t), 4),
            'p_value': round(float(p), 4),
        }

# ============================================================
# 8. REGIME-CONDITIONAL PERFORMANCE
# ============================================================
print("\n" + "=" * 80)
print("[8] REGIME-CONDITIONAL PERFORMANCE")
print("=" * 80)

key_portfolios = {
    'Benchmark_100%SPY': w_spy,
    'A_50-50_SPY+GLD': w_5050,
    'B_RP_SPY+GLD+JPY': None,  # will compute
    'C_RP_SPY+GLD+JPY+ZN': None,
    'C_MV_SPY+GLD+JPY+ZN': None,
}

# Compute RP/MV weights on full sample for regime analysis
w_rp_b_full = risk_parity_weights(ret_df[['SPY', 'GLD', 'JPY']])
w_full_rp_b_full = np.zeros(n_assets)
for i, col in enumerate(['SPY', 'GLD', 'JPY']):
    w_full_rp_b_full[assets_all.index(col)] = w_rp_b_full[i]
key_portfolios['B_RP_SPY+GLD+JPY'] = w_full_rp_b_full

w_rp_c_full = risk_parity_weights(ret_df)
key_portfolios['C_RP_SPY+GLD+JPY+ZN'] = w_rp_c_full

w_mv_c_full = min_variance_weights(ret_df)
key_portfolios['C_MV_SPY+GLD+JPY+ZN'] = w_mv_c_full

RESULTS['regime_performance'] = {}
for regime_name, mask in [('Low VIX (<15)', vix_low_mask),
                           ('Mid VIX (15-25)', vix_mid_mask),
                           ('High VIX (>25)', vix_high_mask)]:
    sub = ret_df.loc[mask]
    if len(sub) < 50:
        continue

    print(f"\n--- {regime_name} (n={len(sub)}) ---")
    print(f"  {'Portfolio':<30s} {'AnnRet':>7s} {'AnnVol':>7s} {'Sharpe':>7s}")
    print("  " + "-" * 55)

    regime_results = {}
    for label, w in key_portfolios.items():
        if w is not None:
            m = portfolio_metrics(w, sub, label)
            print(f"  {label:<30s} {m['ann_return']:>7.3f} {m['ann_vol']:>7.3f} {m['sharpe']:>7.3f}")
            regime_results[label] = {
                'ann_return': m['ann_return'],
                'ann_vol': m['ann_vol'],
                'sharpe': m['sharpe'],
            }
    RESULTS['regime_performance'][regime_name] = regime_results

# ============================================================
# 9. ROLLING CORRELATION ANALYSIS
# ============================================================
print("\n" + "=" * 80)
print("[9] ROLLING CORRELATION — Stability Check")
print("=" * 80)

# 252-day rolling correlations with SPY
window = 252
rolling_corrs = {}
for col in ['GLD', 'JPY', 'ZN']:
    rc = ret_df['SPY'].rolling(window).corr(ret_df[col])
    rolling_corrs[col] = rc.dropna()

    print(f"\n  SPY-{col} rolling {window}-day correlation:")
    print(f"    Mean={rc.mean():.3f}, Std={rc.std():.3f}, "
          f"Min={rc.min():.3f}, Max={rc.max():.3f}")
    print(f"    % of time negative: {(rc < 0).mean()*100:.1f}%")

    RESULTS[f'rolling_corr_SPY_{col}'] = {
        'mean': round(float(rc.mean()), 4),
        'std': round(float(rc.std()), 4),
        'min': round(float(rc.min()), 4),
        'max': round(float(rc.max()), 4),
        'pct_negative': round(float((rc < 0).mean() * 100), 2),
    }

# Cross-hedge correlations
for pair in [('GLD', 'JPY'), ('GLD', 'ZN'), ('JPY', 'ZN')]:
    rc = ret_df[pair[0]].rolling(window).corr(ret_df[pair[1]])
    print(f"\n  {pair[0]}-{pair[1]} rolling {window}-day correlation:")
    print(f"    Mean={rc.mean():.3f}, Std={rc.std():.3f}")

# ============================================================
# 10. SUMMARY & CONCLUSIONS
# ============================================================
print("\n" + "=" * 80)
print("[10] SUMMARY & CONCLUSIONS")
print("=" * 80)

# Find overall best
all_sharpes = {k: v['sharpe'] for k, v in all_results.items() if 'port_returns' in v}
best_sharpe_label = max(all_sharpes, key=all_sharpes.get)
best_tail_label = max(all_results.keys(),
                       key=lambda k: all_results[k]['tail_avg_return_pct'])

print(f"\n  Data: {RESULTS['data']['period']} ({RESULTS['data']['n_days']:,} trading days)")
print(f"  Assets: {RESULTS['data']['assets']}")
print(f"\n  Best overall Sharpe: {best_sharpe_label} "
      f"(Sharpe={all_results[best_sharpe_label]['sharpe']:.3f})")
print(f"  Best tail protection: {best_tail_label} "
      f"(avg crash day return={all_results[best_tail_label]['tail_avg_return_pct']:.4f}%)")

# Key findings
print("\n  KEY FINDINGS:")

# 1. Does adding JPY help?
a_sr = all_results['A_50-50_SPY+GLD']['sharpe']
b_best = max(all_results[k]['sharpe'] for k in all_results if k.startswith('B_'))
b_best_label = max([k for k in all_results if k.startswith('B_')],
                    key=lambda k: all_results[k]['sharpe'])
diff_ab = b_best - a_sr
print(f"\n  1. Adding JPY to SPY+GLD:")
print(f"     Best B portfolio: {b_best_label} (Sharpe={b_best:.3f})")
print(f"     vs 50/50 SPY+GLD: Sharpe diff = {diff_ab:+.4f}")
if diff_ab > 0:
    print(f"     → JPY IMPROVES the portfolio by {diff_ab:.4f} Sharpe units")
else:
    print(f"     → JPY does NOT improve the portfolio")

# 2. Does adding ZN on top help further?
c_best = max(all_results[k]['sharpe'] for k in all_results if k.startswith('C_'))
c_best_label = max([k for k in all_results if k.startswith('C_')],
                    key=lambda k: all_results[k]['sharpe'])
diff_bc = c_best - b_best
print(f"\n  2. Adding ZN on top of SPY+GLD+JPY:")
print(f"     Best C portfolio: {c_best_label} (Sharpe={c_best:.3f})")
print(f"     vs best B: Sharpe diff = {diff_bc:+.4f}")

# 3. Tail protection comparison
a_tail = all_results['A_50-50_SPY+GLD']['tail_avg_return_pct']
b_tail = max(all_results[k]['tail_avg_return_pct'] for k in all_results if k.startswith('B_'))
c_tail = max(all_results[k]['tail_avg_return_pct'] for k in all_results if k.startswith('C_'))
print(f"\n  3. Tail protection (avg return on SPY crash days):")
print(f"     A (SPY+GLD): {a_tail:+.4f}%")
print(f"     B best (SPY+GLD+JPY): {b_tail:+.4f}%")
print(f"     C best (SPY+GLD+JPY+ZN): {c_tail:+.4f}%")

# 4. MDD comparison
a_mdd = all_results['A_50-50_SPY+GLD']['mdd']
b_mdd = max(all_results[k]['mdd'] for k in all_results if k.startswith('B_'))
c_mdd = max(all_results[k]['mdd'] for k in all_results if k.startswith('C_'))
print(f"\n  4. Maximum Drawdown:")
print(f"     A (SPY+GLD best): {a_mdd:.3f}")
print(f"     B best: {b_mdd:.3f}")
print(f"     C best: {c_mdd:.3f}")

# 5. OOS robustness
if 'oos_validation' in RESULTS:
    print(f"\n  5. OOS Robustness (5-period cross-validation):")
    for label in ['A_50-50_SPY+GLD', 'B_RP_SPY+GLD+JPY', 'C_RP_SPY+GLD+JPY+ZN', 'C_MV_SPY+GLD+JPY+ZN']:
        if label in RESULTS['oos_validation']:
            oos = RESULTS['oos_validation'][label]
            print(f"     {label}: mean Sharpe={oos['mean_sharpe']:.3f} "
                  f"(std={oos['std_sharpe']:.3f})")

RESULTS['conclusions'] = {
    'best_sharpe_portfolio': best_sharpe_label,
    'best_sharpe_value': all_results[best_sharpe_label]['sharpe'],
    'best_tail_portfolio': best_tail_label,
    'best_tail_value': all_results[best_tail_label]['tail_avg_return_pct'],
    'jpy_helps_sharpe': diff_ab > 0,
    'jpy_sharpe_diff': round(diff_ab, 4),
    'zn_helps_sharpe': diff_bc > 0,
    'zn_sharpe_diff': round(diff_bc, 4),
    'jpy_helps_tail': b_tail > a_tail,
    'tail_improvement_a_to_b': round(b_tail - a_tail, 4),
    'tail_improvement_a_to_c': round(c_tail - a_tail, 4),
}

# ============================================================
# SAVE RESULTS
# ============================================================
# Clean up non-serializable items
save_results = {}
for k, v in RESULTS.items():
    if isinstance(v, dict):
        clean = {}
        for k2, v2 in v.items():
            if isinstance(v2, dict):
                clean[k2] = {}
                for k3, v3 in v2.items():
                    if isinstance(v3, (dict, list, str, int, float, bool, type(None))):
                        clean[k2][k3] = v3
                    elif isinstance(v3, (np.integer,)):
                        clean[k2][k3] = int(v3)
                    elif isinstance(v3, (np.floating,)):
                        clean[k2][k3] = float(v3)
                    elif isinstance(v3, np.ndarray):
                        clean[k2][k3] = v3.tolist()
            elif isinstance(v2, (str, int, float, bool, type(None), list)):
                clean[k2] = v2
            elif isinstance(v2, (np.integer,)):
                clean[k2] = int(v2)
            elif isinstance(v2, (np.floating,)):
                clean[k2] = float(v2)
        save_results[k] = clean
    else:
        save_results[k] = v

with open('experiments/k347_multi_hedge_results.json', 'w') as f:
    json.dump(save_results, f, indent=2, default=str)

print("\n\nResults saved to experiments/k347_multi_hedge_results.json")
print("=" * 80)
print("K347 COMPLETE")
print("=" * 80)
