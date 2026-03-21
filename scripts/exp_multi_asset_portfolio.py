#!/usr/bin/env python3
"""
K55: Can Adding a Third Asset Beat 50/50 SPY/GLD?
==================================================
50/50 SPY/GLD + 12/VIX is the "unbeatable" portfolio (K2/K16/K19/K24/K54).
This experiment tests whether adding a 3rd or 4th asset can improve it.

Candidates:
- TLT (long-term bonds) — good in rate cuts, bad in rate hikes
- IEF (intermediate bonds) — less duration risk
- TIP (TIPS) — inflation hedge
- BTC-USD (Bitcoin) — uncorrelated but volatile (coskewness=-0.61)
- VNQ (Real Estate) — income + diversification

Allocation methods:
- Equal weight
- Custom tilts (40/40/20, 45/45/10)
- Mean-variance optimal
- Risk-parity (inverse vol)

All with 12/VIX overlay, monthly rebalance, lagged weights, TC=0.05%.
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
from scipy.optimize import minimize
import warnings
warnings.filterwarnings('ignore')

# ══════════════════════════════════════════════════════════════════════
# DATA
# ══════════════════════════════════════════════════════════════════════
print("=" * 80)
print("  K55: Multi-Asset Portfolio — Can a 3rd Asset Beat 50/50 SPY/GLD?")
print("=" * 80)
print("\nDownloading data...")

tickers = ['SPY', 'GLD', 'TLT', 'IEF', 'TIP', 'BTC-USD', 'VNQ', 'SHY']
raw = {}
for t in tickers:
    start = '2005-01-01' if t != 'BTC-USD' else '2014-09-01'
    df = yf.download(t, start=start, progress=False)
    if 'Close' in df.columns:
        raw[t] = df['Close'].squeeze()
    else:
        raw[t] = df[('Close', t)].squeeze()
    print(f"  {t}: {raw[t].index[0].strftime('%Y-%m-%d')} to {raw[t].index[-1].strftime('%Y-%m-%d')} ({len(raw[t])} obs)")

vix_df = yf.download('^VIX', start='2005-01-01', progress=False)
if 'Close' in vix_df.columns:
    vix = vix_df['Close'].squeeze()
else:
    vix = vix_df[('Close', '^VIX')].squeeze()
print(f"  VIX: {vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')}")

# ── Align non-BTC assets (from GLD inception ~2004-11) ──────────────
core_tickers = ['SPY', 'GLD', 'TLT', 'IEF', 'TIP', 'VNQ', 'SHY']
idx_core = raw['SPY'].index
for t in core_tickers[1:]:
    idx_core = idx_core.intersection(raw[t].index)
idx_core = idx_core.intersection(vix.index)

prices_core = {t: raw[t].loc[idx_core] for t in core_tickers}
vix_core = vix.loc[idx_core]

# Compute returns
rets_core = {t: prices_core[t].pct_change().dropna() for t in core_tickers}
idx_ret = rets_core['SPY'].index
for t in core_tickers[1:]:
    idx_ret = idx_ret.intersection(rets_core[t].index)

for t in core_tickers:
    rets_core[t] = rets_core[t].loc[idx_ret]
vix_aligned = vix_core.reindex(idx_ret).ffill()

print(f"\nCore data: {idx_ret[0].strftime('%Y-%m-%d')} to {idx_ret[-1].strftime('%Y-%m-%d')}, {len(idx_ret)} days")

# ── BTC alignment (separate, shorter history) ──────────────────────
btc_start = raw['BTC-USD'].index[0]
idx_btc = idx_ret[idx_ret >= btc_start]
# BTC has gaps on weekends/holidays — forward fill
btc_prices = raw['BTC-USD'].reindex(idx_btc).ffill()
btc_ret = btc_prices.pct_change().dropna()
idx_btc_ret = idx_btc[1:]  # after pct_change

print(f"BTC data: {idx_btc_ret[0].strftime('%Y-%m-%d')} to {idx_btc_ret[-1].strftime('%Y-%m-%d')}, {len(idx_btc_ret)} days")


# ══════════════════════════════════════════════════════════════════════
# STRATEGY ENGINE
# ══════════════════════════════════════════════════════════════════════
TC = 0.0005  # 0.05% per trade

def monthly_rebalance_mask(dates):
    """Return boolean mask for month-end rebalance dates."""
    months = pd.Series(dates).dt.to_period('M')
    mask = months != months.shift(-1)
    mask.iloc[-1] = True
    mask.index = dates
    return mask

def compute_multi_asset_strategy(asset_rets: dict, ret_shy, vix_series,
                                  allocations: dict, name: str,
                                  vt_rule='12/VIX', per_asset_vt=None):
    """
    Compute multi-asset portfolio with 12/VIX overlay.

    asset_rets: {ticker: pd.Series of returns}
    allocations: {ticker: weight} (must sum to 1.0)
    vt_rule: '12/VIX' (default), 'none' (buy & hold)
    per_asset_vt: optional dict {ticker: callable(vix) -> weight}
    """
    dates = list(asset_rets.values())[0].index
    rebal_mask = monthly_rebalance_mask(dates)

    port_ret = pd.Series(0.0, index=dates)
    prev_weights = None  # for TC calculation
    current_vt_weight = 1.0

    for i, date in enumerate(dates):
        # At rebalance dates, update VT weight using LAGGED VIX
        if i > 0 and rebal_mask.iloc[i-1]:
            v = vix_series.iloc[i-1]
            if vt_rule == '12/VIX':
                current_vt_weight = min(12.0 / v, 1.0)
            elif vt_rule == 'none':
                current_vt_weight = 1.0
            else:
                current_vt_weight = min(12.0 / v, 1.0)

        # Calculate portfolio return
        daily_ret = 0.0
        new_weights = {}
        for ticker, alloc in allocations.items():
            if per_asset_vt and ticker in per_asset_vt:
                v = vix_series.iloc[max(i-1, 0)]
                w = np.clip(per_asset_vt[ticker](v), 0, 1)
            else:
                w = current_vt_weight

            new_weights[ticker] = w
            sleeve_ret = w * asset_rets[ticker].iloc[i] + (1 - w) * ret_shy.iloc[i]
            daily_ret += alloc * sleeve_ret

        # Transaction costs at rebalance
        if i > 0 and rebal_mask.iloc[i-1] and prev_weights is not None:
            tc = 0.0
            for ticker, alloc in allocations.items():
                tc += TC * abs(new_weights[ticker] - prev_weights.get(ticker, new_weights[ticker])) * alloc
            daily_ret -= tc

        if rebal_mask.iloc[max(i-1, 0)] or prev_weights is None:
            prev_weights = new_weights.copy()

        port_ret.iloc[i] = daily_ret

    return port_ret

def compute_metrics(returns, name, rf_annual=0.02):
    """Compute Sharpe, MDD, Calmar, Sortino, and other metrics."""
    n = len(returns)
    if n < 20:
        return None

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
    n_years = n / 252
    sharpe_se = 1 / np.sqrt(n_years)
    sharpe_t = sharpe / sharpe_se

    # Skewness, Kurtosis
    skew = float(returns.skew())
    kurt = float(returns.kurtosis())

    # Total return
    total_ret = float(cum.iloc[-1] - 1) * 100

    return {
        'name': name,
        'ann_return': round(ann_ret * 100, 2),
        'ann_vol': round(ann_vol * 100, 2),
        'sharpe': round(sharpe, 3),
        'sharpe_t': round(sharpe_t, 2),
        'mdd': round(mdd * 100, 2),
        'calmar': round(calmar, 3),
        'sortino': round(sortino, 3),
        'skewness': round(skew, 3),
        'kurtosis': round(kurt, 3),
        'total_return': round(total_ret, 1),
        'n_days': n,
        'n_years': round(n_years, 1),
    }

def sharpe_diff_test(r1, r2):
    """Jobson-Korkie-Memmel test for Sharpe ratio difference."""
    n = len(r1)
    mu1, mu2 = r1.mean(), r2.mean()
    s1, s2 = r1.std(), r2.std()
    if s1 == 0 or s2 == 0:
        return 0, 1.0
    rho = np.corrcoef(r1, r2)[0, 1]
    sr1 = mu1 / s1
    sr2 = mu2 / s2
    theta = (1/n) * (2 * (1 - rho) + 0.5 * (sr1**2 + sr2**2 - 2*sr1*sr2*rho))
    z = (sr1 - sr2) / np.sqrt(theta) if theta > 0 else 0
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return round(z, 3), round(p, 4)


# ══════════════════════════════════════════════════════════════════════
# DEFINE STRATEGIES
# ══════════════════════════════════════════════════════════════════════

strategies = {}

# ── Baselines ──
strategies['B0: 50/50 SPY/GLD Buy&Hold'] = {
    'alloc': {'SPY': 0.5, 'GLD': 0.5},
    'vt': 'none',
    'desc': 'No VT, static 50/50',
    'uses_btc': False,
}
strategies['B1: 50/50 SPY/GLD 12/VIX'] = {
    'alloc': {'SPY': 0.5, 'GLD': 0.5},
    'vt': '12/VIX',
    'desc': 'Baseline: 50/50 + 12/VIX (the benchmark to beat)',
    'uses_btc': False,
}
strategies['B2: 60/40 SPY/TLT Buy&Hold'] = {
    'alloc': {'SPY': 0.6, 'TLT': 0.4},
    'vt': 'none',
    'desc': 'Classic 60/40 without VT',
    'uses_btc': False,
}
strategies['B3: 60/40 SPY/TLT 12/VIX'] = {
    'alloc': {'SPY': 0.6, 'TLT': 0.4},
    'vt': '12/VIX',
    'desc': 'Classic 60/40 + 12/VIX',
    'uses_btc': False,
}

# ── 3-Asset Equal Weight ──
strategies['A1: 33/33/33 SPY/GLD/TLT'] = {
    'alloc': {'SPY': 1/3, 'GLD': 1/3, 'TLT': 1/3},
    'vt': '12/VIX',
    'desc': 'Equal weight 3-asset + 12/VIX',
    'uses_btc': False,
}
strategies['A2: 33/33/33 SPY/GLD/IEF'] = {
    'alloc': {'SPY': 1/3, 'GLD': 1/3, 'IEF': 1/3},
    'vt': '12/VIX',
    'desc': 'Equal weight with intermediate bonds',
    'uses_btc': False,
}
strategies['A3: 33/33/33 SPY/GLD/TIP'] = {
    'alloc': {'SPY': 1/3, 'GLD': 1/3, 'TIP': 1/3},
    'vt': '12/VIX',
    'desc': 'Equal weight with TIPS',
    'uses_btc': False,
}
strategies['A4: 33/33/33 SPY/GLD/VNQ'] = {
    'alloc': {'SPY': 1/3, 'GLD': 1/3, 'VNQ': 1/3},
    'vt': '12/VIX',
    'desc': 'Equal weight with REITs',
    'uses_btc': False,
}

# ── 3-Asset Custom Tilts ──
strategies['A5: 40/40/20 SPY/GLD/TLT'] = {
    'alloc': {'SPY': 0.4, 'GLD': 0.4, 'TLT': 0.2},
    'vt': '12/VIX',
    'desc': 'Tilt toward SPY/GLD with TLT diversifier',
    'uses_btc': False,
}
strategies['A6: 40/40/20 SPY/GLD/IEF'] = {
    'alloc': {'SPY': 0.4, 'GLD': 0.4, 'IEF': 0.2},
    'vt': '12/VIX',
    'desc': 'Tilt toward SPY/GLD with IEF diversifier',
    'uses_btc': False,
}
strategies['A7: 40/40/20 SPY/GLD/TIP'] = {
    'alloc': {'SPY': 0.4, 'GLD': 0.4, 'TIP': 0.2},
    'vt': '12/VIX',
    'desc': 'Tilt toward SPY/GLD with TIPS diversifier',
    'uses_btc': False,
}
strategies['A8: 40/40/20 SPY/GLD/VNQ'] = {
    'alloc': {'SPY': 0.4, 'GLD': 0.4, 'VNQ': 0.2},
    'vt': '12/VIX',
    'desc': 'Tilt toward SPY/GLD with REIT diversifier',
    'uses_btc': False,
}

# ── BTC allocations (small) ──
strategies['A9: 45/45/10 SPY/GLD/BTC'] = {
    'alloc': {'SPY': 0.45, 'GLD': 0.45, 'BTC-USD': 0.10},
    'vt': '12/VIX',
    'desc': 'Small BTC allocation (10%)',
    'uses_btc': True,
}
strategies['A10: 47/47/5 SPY/GLD/BTC'] = {
    'alloc': {'SPY': 0.475, 'GLD': 0.475, 'BTC-USD': 0.05},
    'vt': '12/VIX',
    'desc': 'Minimal BTC allocation (5%)',
    'uses_btc': True,
}

# ── 4-Asset ──
strategies['A11: 30/30/20/20 SPY/GLD/TLT/IEF'] = {
    'alloc': {'SPY': 0.3, 'GLD': 0.3, 'TLT': 0.2, 'IEF': 0.2},
    'vt': '12/VIX',
    'desc': '4-asset: equity/gold/long bond/mid bond',
    'uses_btc': False,
}
strategies['A12: 30/30/20/20 SPY/GLD/TLT/TIP'] = {
    'alloc': {'SPY': 0.3, 'GLD': 0.3, 'TLT': 0.2, 'TIP': 0.2},
    'vt': '12/VIX',
    'desc': '4-asset: equity/gold/long bond/TIPS',
    'uses_btc': False,
}
strategies['A13: 25/25/25/25 SPY/GLD/TLT/IEF'] = {
    'alloc': {'SPY': 0.25, 'GLD': 0.25, 'TLT': 0.25, 'IEF': 0.25},
    'vt': '12/VIX',
    'desc': '4-asset equal weight',
    'uses_btc': False,
}

# ── All Weather inspired ──
strategies['A14: 30/15/40/15 SPY/GLD/TLT/TIP'] = {
    'alloc': {'SPY': 0.3, 'GLD': 0.15, 'TLT': 0.4, 'TIP': 0.15},
    'vt': '12/VIX',
    'desc': 'All Weather inspired + 12/VIX',
    'uses_btc': False,
}


# ══════════════════════════════════════════════════════════════════════
# RUN EXPERIMENTS
# ══════════════════════════════════════════════════════════════════════
periods = {
    'full': ('2007-01-03', None),
    'oos': ('2023-01-03', None),
    'pre_covid': ('2007-01-03', '2019-12-31'),
    'covid': ('2020-01-01', '2021-06-30'),
    'rate_hike': ('2022-01-01', '2023-12-31'),
    'post_rate_hike': ('2024-01-01', None),
}

results = {}
all_returns_full = {}  # for statistical tests

print("\n" + "=" * 80)
print("  Running strategies...")
print("=" * 80)

for strat_name, strat_conf in strategies.items():
    uses_btc = strat_conf['uses_btc']

    for period_name, (start, end) in periods.items():
        # Build date mask
        if uses_btc:
            dates = idx_btc_ret
        else:
            dates = idx_ret

        mask = dates >= start
        if end:
            mask &= dates <= end

        period_dates = dates[mask]
        if len(period_dates) < 30:
            continue

        # Build asset returns dict for this strategy
        asset_rets = {}
        for ticker in strat_conf['alloc']:
            if ticker == 'BTC-USD':
                asset_rets[ticker] = btc_ret.loc[period_dates]
            else:
                asset_rets[ticker] = rets_core[ticker].loc[period_dates]

        shy_ret = rets_core['SHY'].loc[period_dates]
        vix_s = vix_aligned.loc[period_dates]

        # Compute strategy
        port_ret = compute_multi_asset_strategy(
            asset_rets, shy_ret, vix_s,
            strat_conf['alloc'], strat_name,
            vt_rule=strat_conf['vt']
        )

        metrics = compute_metrics(port_ret, strat_name)
        if metrics is None:
            continue

        if period_name not in results:
            results[period_name] = {}
        results[period_name][strat_name] = metrics

        # Save full-period returns for statistical tests
        if period_name == 'full':
            all_returns_full[strat_name] = port_ret

    print(f"  {strat_name} — done")


# ══════════════════════════════════════════════════════════════════════
# RISK PARITY & MEAN-VARIANCE OPTIMIZATION
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("  Computing Optimized Portfolios...")
print("=" * 80)

def compute_risk_parity_weights(cov_matrix, tickers_list):
    """Inverse-volatility risk parity weights."""
    vols = np.sqrt(np.diag(cov_matrix))
    inv_vol = 1.0 / vols
    weights = inv_vol / inv_vol.sum()
    return {t: round(w, 4) for t, w in zip(tickers_list, weights)}

def compute_mv_optimal_weights(mean_rets, cov_matrix, tickers_list, rf=0.02/252):
    """Mean-variance optimal (max Sharpe) with long-only constraint."""
    n = len(tickers_list)

    def neg_sharpe(w):
        port_ret = np.dot(w, mean_rets)
        port_vol = np.sqrt(np.dot(w, np.dot(cov_matrix, w)))
        return -(port_ret - rf) / port_vol if port_vol > 0 else 0

    constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1}]
    bounds = [(0.05, 0.60)] * n  # min 5%, max 60% per asset
    x0 = np.ones(n) / n

    result = minimize(neg_sharpe, x0, method='SLSQP',
                      bounds=bounds, constraints=constraints)
    if result.success:
        return {t: round(w, 4) for t, w in zip(tickers_list, result.x)}
    else:
        return {t: round(1/n, 4) for t in tickers_list}

# Use IS period (2007-2022) for optimization, OOS (2023+) for evaluation
is_end = '2022-12-31'
oos_start = '2023-01-03'

is_mask = (idx_ret >= '2007-01-03') & (idx_ret <= is_end)
is_dates = idx_ret[is_mask]

# 3-asset optimization: SPY/GLD + {TLT, IEF, TIP, VNQ}
opt_configs = {
    'SPY/GLD/TLT': ['SPY', 'GLD', 'TLT'],
    'SPY/GLD/IEF': ['SPY', 'GLD', 'IEF'],
    'SPY/GLD/TIP': ['SPY', 'GLD', 'TIP'],
    'SPY/GLD/VNQ': ['SPY', 'GLD', 'VNQ'],
    'SPY/GLD/TLT/IEF': ['SPY', 'GLD', 'TLT', 'IEF'],
}

opt_results = {}

for config_name, tickers_list in opt_configs.items():
    # Build returns matrix (IS period)
    ret_matrix = pd.DataFrame({t: rets_core[t].loc[is_dates] for t in tickers_list})
    mean_rets = ret_matrix.mean().values
    cov_matrix = ret_matrix.cov().values

    # Risk Parity
    rp_weights = compute_risk_parity_weights(cov_matrix, tickers_list)
    rp_name = f'RP: {config_name}'
    print(f"  {rp_name}: {rp_weights}")

    # Mean-Variance
    mv_weights = compute_mv_optimal_weights(mean_rets, cov_matrix, tickers_list)
    mv_name = f'MV: {config_name}'
    print(f"  {mv_name}: {mv_weights}")

    opt_results[config_name] = {
        'risk_parity': rp_weights,
        'mean_variance': mv_weights,
    }

    # Add optimized strategies to run
    for opt_type, weights in [('RP', rp_weights), ('MV', mv_weights)]:
        sname = f'{opt_type}: {config_name}'
        strategies[sname] = {
            'alloc': weights,
            'vt': '12/VIX',
            'desc': f'{opt_type} optimized {config_name} + 12/VIX (IS: 2007-2022)',
            'uses_btc': False,
        }

        # Run for all periods
        for period_name, (start, end) in periods.items():
            mask = idx_ret >= start
            if end:
                mask &= idx_ret <= end
            period_dates = idx_ret[mask]
            if len(period_dates) < 30:
                continue

            asset_rets = {t: rets_core[t].loc[period_dates] for t in tickers_list}
            shy_ret = rets_core['SHY'].loc[period_dates]
            vix_s = vix_aligned.loc[period_dates]

            port_ret = compute_multi_asset_strategy(
                asset_rets, shy_ret, vix_s,
                weights, sname, vt_rule='12/VIX'
            )

            metrics = compute_metrics(port_ret, sname)
            if metrics is None:
                continue

            if period_name not in results:
                results[period_name] = {}
            results[period_name][sname] = metrics

            if period_name == 'full':
                all_returns_full[sname] = port_ret


# ══════════════════════════════════════════════════════════════════════
# STATISTICAL TESTS
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("  Statistical Tests vs B1 Baseline (50/50 SPY/GLD 12/VIX)")
print("=" * 80)

baseline_key = 'B1: 50/50 SPY/GLD 12/VIX'
baseline_ret = all_returns_full[baseline_key]

stat_tests = {}
for name, ret in all_returns_full.items():
    if name == baseline_key:
        continue
    # Align dates (BTC strategies have shorter history)
    common_idx = ret.index.intersection(baseline_ret.index)
    if len(common_idx) < 100:
        continue
    z, p = sharpe_diff_test(ret.loc[common_idx].values, baseline_ret.loc[common_idx].values)

    delta_sharpe = results['full'][name]['sharpe'] - results['full'][baseline_key]['sharpe']
    stat_tests[name] = {
        'delta_sharpe': round(delta_sharpe, 3),
        'jkm_z': z,
        'jkm_p': p,
        'significant_005': p < 0.05,
        'significant_010': p < 0.10,
    }

# Also test vs baseline on OOS period only
stat_tests_oos = {}
if 'oos' in results and baseline_key in results['oos']:
    oos_mask = idx_ret >= oos_start
    baseline_oos = baseline_ret.loc[baseline_ret.index[baseline_ret.index >= oos_start]]

    for name, ret in all_returns_full.items():
        if name == baseline_key:
            continue
        oos_ret = ret.loc[ret.index[ret.index >= oos_start]]
        common_idx = oos_ret.index.intersection(baseline_oos.index)
        if len(common_idx) < 50:
            continue
        z, p = sharpe_diff_test(oos_ret.loc[common_idx].values, baseline_oos.loc[common_idx].values)

        if name in results.get('oos', {}) and baseline_key in results.get('oos', {}):
            ds = results['oos'][name]['sharpe'] - results['oos'][baseline_key]['sharpe']
        else:
            ds = 0
        stat_tests_oos[name] = {
            'delta_sharpe_oos': round(ds, 3),
            'jkm_z': z,
            'jkm_p': p,
            'significant_005': p < 0.05,
        }


# ══════════════════════════════════════════════════════════════════════
# CORRELATION & DIVERSIFICATION ANALYSIS
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("  Asset Correlation Matrix (Full Sample)")
print("=" * 80)

corr_tickers = ['SPY', 'GLD', 'TLT', 'IEF', 'TIP', 'VNQ']
corr_df = pd.DataFrame({t: rets_core[t] for t in corr_tickers}).corr()
corr_dict = {}
print(f"\n{'':>6}", end='')
for t in corr_tickers:
    print(f"  {t:>6}", end='')
print()
for t1 in corr_tickers:
    print(f"{t1:>6}", end='')
    corr_dict[t1] = {}
    for t2 in corr_tickers:
        v = corr_df.loc[t1, t2]
        print(f"  {v:>6.3f}", end='')
        corr_dict[t1][t2] = round(v, 3)
    print()

# Crisis correlations (VIX > 25)
print(f"\n{'':>6}", end='')
crisis_mask_full = vix_aligned > 25
for t in corr_tickers:
    print(f"  {t:>6}", end='')
print("   [VIX > 25 only]")
corr_crisis = pd.DataFrame({t: rets_core[t][crisis_mask_full] for t in corr_tickers}).corr()
crisis_corr_dict = {}
for t1 in corr_tickers:
    print(f"{t1:>6}", end='')
    crisis_corr_dict[t1] = {}
    for t2 in corr_tickers:
        v = corr_crisis.loc[t1, t2]
        print(f"  {v:>6.3f}", end='')
        crisis_corr_dict[t1][t2] = round(v, 3)
    print()

# Rate hike period correlations (2022-2023)
print(f"\n{'':>6}", end='')
rh_mask = (idx_ret >= '2022-01-01') & (idx_ret <= '2023-12-31')
for t in corr_tickers:
    print(f"  {t:>6}", end='')
print("   [Rate Hike 2022-2023]")
corr_rh = pd.DataFrame({t: rets_core[t][rh_mask] for t in corr_tickers}).corr()
rh_corr_dict = {}
for t1 in corr_tickers:
    print(f"{t1:>6}", end='')
    rh_corr_dict[t1] = {}
    for t2 in corr_tickers:
        v = corr_rh.loc[t1, t2]
        print(f"  {v:>6.3f}", end='')
        rh_corr_dict[t1][t2] = round(v, 3)
    print()


# ══════════════════════════════════════════════════════════════════════
# DISPLAY RESULTS
# ══════════════════════════════════════════════════════════════════════
period_labels = {
    'full': 'Full Sample (2007-present)',
    'oos': 'Out-of-Sample (2023-present)',
    'pre_covid': 'Pre-COVID (2007-2019)',
    'covid': 'COVID (2020-2021H1)',
    'rate_hike': 'Rate Hike (2022-2023)',
    'post_rate_hike': 'Post Rate Hike (2024-present)',
}

for period_name in ['full', 'oos', 'rate_hike']:
    if period_name not in results:
        continue
    print(f"\n{'=' * 120}")
    print(f"  {period_labels.get(period_name, period_name)}")
    print(f"{'=' * 120}")
    print(f"{'Strategy':<38} | {'Sharpe':>7} | {'t-stat':>7} | {'MDD%':>7} | {'Calmar':>7} | {'Sortino':>7} | {'Ann%':>7} | {'Vol%':>6} | {'Total%':>7}")
    print("-" * 120)

    # Sort by Sharpe
    sorted_strats = sorted(results[period_name].items(), key=lambda x: x[1]['sharpe'], reverse=True)

    for name, m in sorted_strats:
        marker = ' ***' if name == baseline_key else ''
        print(f"{name:<38} | {m['sharpe']:>7.3f} | {m['sharpe_t']:>7.2f} | {m['mdd']:>7.1f} | "
              f"{m['calmar']:>7.3f} | {m['sortino']:>7.3f} | {m['ann_return']:>7.1f} | {m['ann_vol']:>6.1f} | {m['total_return']:>7.1f}{marker}")

# ── Statistical Tests Display ──
print(f"\n{'=' * 120}")
print(f"  Sharpe Difference Tests vs Baseline (B1: 50/50 SPY/GLD 12/VIX)")
print(f"  Full Sample — Jobson-Korkie-Memmel Test")
print(f"{'=' * 120}")
print(f"{'Strategy':<38} | {'ΔSharpe':>8} | {'z-stat':>8} | {'p-value':>8} | {'Sig 5%':>7} | {'Sig 10%':>7}")
print("-" * 90)

sorted_tests = sorted(stat_tests.items(), key=lambda x: x[1]['delta_sharpe'], reverse=True)
for name, test in sorted_tests:
    sig5 = "YES" if test['significant_005'] else "no"
    sig10 = "YES" if test['significant_010'] else "no"
    print(f"{name:<38} | {test['delta_sharpe']:>+8.3f} | {test['jkm_z']:>8.3f} | {test['jkm_p']:>8.4f} | {sig5:>7} | {sig10:>7}")

# OOS tests
if stat_tests_oos:
    print(f"\n{'=' * 120}")
    print(f"  Sharpe Difference Tests — OOS Period (2023-present)")
    print(f"{'=' * 120}")
    print(f"{'Strategy':<38} | {'ΔSharpe':>8} | {'z-stat':>8} | {'p-value':>8} | {'Sig 5%':>7}")
    print("-" * 85)

    sorted_oos = sorted(stat_tests_oos.items(), key=lambda x: x[1]['delta_sharpe_oos'], reverse=True)
    for name, test in sorted_oos:
        sig5 = "YES" if test['significant_005'] else "no"
        print(f"{name:<38} | {test['delta_sharpe_oos']:>+8.3f} | {test['jkm_z']:>8.3f} | {test['jkm_p']:>8.4f} | {sig5:>7}")


# ══════════════════════════════════════════════════════════════════════
# SUB-PERIOD ROBUSTNESS
# ══════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 120}")
print(f"  Sub-Period Robustness: How Many Periods Does Each Strategy Beat Baseline?")
print(f"{'=' * 120}")

sub_periods = ['full', 'oos', 'pre_covid', 'covid', 'rate_hike', 'post_rate_hike']
baseline_sharpes = {}
for sp in sub_periods:
    if sp in results and baseline_key in results[sp]:
        baseline_sharpes[sp] = results[sp][baseline_key]['sharpe']

# Count wins
win_counts = {}
for strat_name in strategies:
    if strat_name == baseline_key:
        continue
    wins_sharpe = 0
    wins_mdd = 0
    valid_periods = 0
    for sp in sub_periods:
        if sp in results and strat_name in results[sp] and baseline_key in results[sp]:
            valid_periods += 1
            if results[sp][strat_name]['sharpe'] > results[sp][baseline_key]['sharpe']:
                wins_sharpe += 1
            if results[sp][strat_name]['mdd'] > results[sp][baseline_key]['mdd']:
                wins_mdd += 1
    if valid_periods > 0:
        win_counts[strat_name] = {
            'sharpe_wins': wins_sharpe,
            'mdd_wins': wins_mdd,
            'total_periods': valid_periods,
        }

print(f"{'Strategy':<38} | {'Sharpe Wins':>12} | {'MDD Wins':>12}")
print("-" * 70)
sorted_wins = sorted(win_counts.items(), key=lambda x: (x[1]['sharpe_wins'], x[1]['mdd_wins']), reverse=True)
for name, wc in sorted_wins:
    print(f"{name:<38} | {wc['sharpe_wins']:>4}/{wc['total_periods']:<7} | {wc['mdd_wins']:>4}/{wc['total_periods']:<7}")


# ══════════════════════════════════════════════════════════════════════
# ASSET-LEVEL ANALYSIS
# ══════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 120}")
print(f"  Individual Asset Performance (Full Sample, annualized)")
print(f"{'=' * 120}")
print(f"{'Asset':<10} | {'Ann Ret%':>8} | {'Ann Vol%':>8} | {'Sharpe':>7} | {'MDD%':>7} | {'Skew':>7} | {'Kurt':>7}")
print("-" * 70)

for t in ['SPY', 'GLD', 'TLT', 'IEF', 'TIP', 'VNQ']:
    r = rets_core[t]
    ann_r = r.mean() * 252 * 100
    ann_v = r.std() * np.sqrt(252) * 100
    sr = (r.mean() * 252 - 0.02) / (r.std() * np.sqrt(252)) if r.std() > 0 else 0
    cum = (1 + r).cumprod()
    mdd = ((cum - cum.cummax()) / cum.cummax()).min() * 100
    sk = r.skew()
    ku = r.kurtosis()
    print(f"{t:<10} | {ann_r:>8.2f} | {ann_v:>8.2f} | {sr:>7.3f} | {mdd:>7.1f} | {sk:>7.3f} | {ku:>7.1f}")


# ══════════════════════════════════════════════════════════════════════
# CONCLUSION
# ══════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 120}")
print(f"  CONCLUSION")
print(f"{'=' * 120}")

# Find best overall (full sample)
best_full_sharpe = max(results['full'].items(), key=lambda x: x[1]['sharpe'])
best_full_mdd = max(results['full'].items(), key=lambda x: x[1]['mdd'])

# Any significant improvement?
any_sig_005 = any(t['significant_005'] for t in stat_tests.values())
any_sig_010 = any(t['significant_010'] for t in stat_tests.values())

# Significant strategies
sig_strategies_005 = [n for n, t in stat_tests.items() if t['significant_005']]
sig_strategies_010 = [n for n, t in stat_tests.items() if t['significant_010']]

# Best OOS
if 'oos' in results:
    best_oos_sharpe = max(
        [(n, m) for n, m in results['oos'].items()],
        key=lambda x: x[1]['sharpe']
    )
    best_oos_mdd = max(
        [(n, m) for n, m in results['oos'].items()],
        key=lambda x: x[1]['mdd']
    )

conclusion = []
conclusion.append(f"Baseline: B1 50/50 SPY/GLD 12/VIX — Sharpe={results['full'][baseline_key]['sharpe']:.3f}, MDD={results['full'][baseline_key]['mdd']:.1f}%")
conclusion.append(f"Best Full-Sample Sharpe: {best_full_sharpe[0]} — Sharpe={best_full_sharpe[1]['sharpe']:.3f}")
conclusion.append(f"Best Full-Sample MDD: {best_full_mdd[0]} — MDD={best_full_mdd[1]['mdd']:.1f}%")

if 'oos' in results:
    conclusion.append(f"Best OOS Sharpe: {best_oos_sharpe[0]} — Sharpe={best_oos_sharpe[1]['sharpe']:.3f}")
    conclusion.append(f"Best OOS MDD: {best_oos_mdd[0]} — MDD={best_oos_mdd[1]['mdd']:.1f}%")

conclusion.append(f"Any strategy significantly (p<0.05) beats baseline? {'YES: ' + str(sig_strategies_005) if any_sig_005 else 'NO'}")
conclusion.append(f"Any strategy marginally (p<0.10) beats baseline? {'YES: ' + str(sig_strategies_010) if any_sig_010 else 'NO'}")

# Rate hike analysis
if 'rate_hike' in results and baseline_key in results['rate_hike']:
    rh_baseline = results['rate_hike'][baseline_key]
    rh_better = [(n, m) for n, m in results['rate_hike'].items()
                 if m['sharpe'] > rh_baseline['sharpe'] and n != baseline_key]
    rh_better.sort(key=lambda x: x[1]['sharpe'], reverse=True)
    if rh_better:
        conclusion.append(f"Rate Hike winners (beat baseline Sharpe {rh_baseline['sharpe']:.3f}): " +
                          ", ".join(f"{n}({m['sharpe']:.3f})" for n, m in rh_better[:5]))
    else:
        conclusion.append(f"Rate Hike: NO strategy beats baseline")

# Sub-period consistency
most_consistent = max(win_counts.items(), key=lambda x: x[1]['sharpe_wins'])
conclusion.append(f"Most consistent (Sharpe wins): {most_consistent[0]} ({most_consistent[1]['sharpe_wins']}/{most_consistent[1]['total_periods']} periods)")

for line in conclusion:
    print(f"  {line}")


# ══════════════════════════════════════════════════════════════════════
# SAVE RESULTS
# ══════════════════════════════════════════════════════════════════════
output = {
    "experiment": "K55: Can Adding a Third Asset Beat 50/50 SPY/GLD?",
    "description": (
        "50/50 SPY/GLD + 12/VIX is the 'unbeatable' portfolio. "
        "This tests 3-asset (TLT/IEF/TIP/VNQ/BTC) and 4-asset configurations, "
        "plus risk-parity and mean-variance optimization, "
        "to determine if any combination can beat the baseline."
    ),
    "proposed_by": "用戶",
    "executed_by": "Claude",
    "timestamp": datetime.now().isoformat(),
    "config": {
        "start": "2007-01-03",
        "oos_start": "2023-01-03",
        "rebalance": "monthly",
        "tc_per_trade": TC,
        "cash_proxy": "SHY",
        "rf_annual": 0.02,
        "btc_start": str(btc_start.date()),
        "optimization_is_period": "2007-2022",
    },
    "strategies": {name: conf['desc'] for name, conf in strategies.items()},
    "results": {},
    "statistical_tests_full": stat_tests,
    "statistical_tests_oos": stat_tests_oos,
    "optimization_weights": opt_results,
    "correlations": {
        "full_sample": corr_dict,
        "crisis_vix_gt_25": crisis_corr_dict,
        "rate_hike_2022_2023": rh_corr_dict,
    },
    "sub_period_wins": win_counts,
    "conclusion": conclusion,
}

# Add period results
for period_name in results:
    output['results'][period_name] = {}
    for strat_name in results[period_name]:
        output['results'][period_name][strat_name] = results[period_name][strat_name]

outpath = '/Users/yhlai0911/Dropbox/自我研究波動預測模型/storage/experiments/multi_asset_portfolio.json'
with open(outpath, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)
print(f"\nSaved to {outpath}")
print("Done!")
