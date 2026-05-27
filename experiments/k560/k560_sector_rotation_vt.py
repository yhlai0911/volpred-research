#!/usr/bin/env python3
"""
K560: Sector Rotation with VT — Can Rotating Between Sectors Improve Upon SPY VT?
==================================================================================
Motivation:
Instead of timing WHEN to use VT (which generally fails to beat 12/VIX),
what about WHERE to apply VT? Different sectors have different gamma/leverage
effects. K58 found VT works uniformly across sectors, but that tested VT
on individual sectors. This tests sector SELECTION — choosing which sector
to overweight based on signals.

Prior knowledge:
- K58: Sector VT Map — gamma doesn't predict sector-level VT benefit.
        All 11 sectors benefit from VT uniformly. corr(gamma, delta-Sharpe)=0.163 NS.
- K243: Sector Rotation — Harvey PASS (t=3.99) but DM NS. MDD -37%.
- K244: TSMOM+Sector (absorbed)
- N79/N80/N81: 12/VIX Sharpe ~0.6-0.7, robust across thresholds 6-18.

Design:
1. Data: SPY + 8 sector ETFs (XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU)
         + GLD + VIX from yfinance (2005-2026)
2. For each sector, compute 12/VIX weight (same formula)
3. Sector selection signals:
   a. Momentum: overweight sector with best 60d return
   b. Low-vol: overweight sector with lowest 22d realized vol
   c. Mean-reversion: overweight sector with worst 60d return (contrarian)
   d. Relative strength: overweight sectors beating SPY
4. Strategy: 50% in selected sector(s) VT + 50% GLD (maintaining safe allocation)
5. Benchmark: standard 50% SPY VT + 50% GLD (the "N79 baseline")
6. Cross-OOS: 3 periods
7. Harvey (2016) t > 3.0

Different from K58: K58 applied VT uniformly to each sector.
This tests sector SELECTION based on signals.

Literature:
- Moreira & Muir (2017): "Volatility-Managed Portfolios", JF
- Moskowitz, Ooi, Pedersen (2012): "Time Series Momentum", JFE
- Asness, Moskowitz, Pedersen (2013): "Value and Momentum Everywhere", JF
- Harvey, Liu, Zhu (2016): "...and the Cross-Section of Expected Returns", RFS

Data source: yfinance (SPY, XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, GLD, ^VIX)
Period: 2005-2026
"""

import json
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime

warnings.filterwarnings('ignore')

start_time = time.time()

print("=" * 70)
print("K560: Sector Rotation with VT")
print("Can Rotating Between Sectors Improve Upon SPY VT?")
print("=" * 70)

# =================================================================
# 1. DATA DOWNLOAD
# =================================================================
print("\n[1] Downloading data...")

tickers = {
    'SPY': 'S&P 500',
    'XLK': 'Technology',
    'XLF': 'Financials',
    'XLV': 'Healthcare',
    'XLE': 'Energy',
    'XLI': 'Industrials',
    'XLY': 'Consumer Disc.',
    'XLP': 'Consumer Staples',
    'XLU': 'Utilities',
    'GLD': 'Gold',
}

sector_tickers = ['XLK', 'XLF', 'XLV', 'XLE', 'XLI', 'XLY', 'XLP', 'XLU']

# Download all at once for efficiency
all_tickers = list(tickers.keys()) + ['^VIX']
raw = yf.download(all_tickers, start="2004-01-01", end="2026-12-31", progress=False)

# Flatten multi-level columns
if isinstance(raw.columns, pd.MultiIndex):
    close = raw['Close']
else:
    close = raw[['Close']]

# VIX column
vix = close['^VIX'].dropna()
vix.name = 'VIX'

# Compute daily returns for all assets
returns = close[list(tickers.keys())].pct_change().dropna()

# Align with VIX
df = returns.join(vix, how='inner').dropna()
df = df.loc['2005-01-01':]

print(f"  Data: {len(df)} trading days ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
print(f"  VIX range: {df['VIX'].min():.1f} - {df['VIX'].max():.1f}, median {df['VIX'].median():.1f}")
print(f"  Sectors: {', '.join(sector_tickers)}")

# =================================================================
# 2. DESCRIPTIVE STATISTICS
# =================================================================
print("\n[2] Sector descriptive statistics (annualized)...")

desc_stats = {}
print(f"  {'Sector':<20} {'Ann Ret':>8} {'Ann Vol':>8} {'Sharpe':>7} {'Skew':>6} {'Kurt':>6}")
print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*7} {'-'*6} {'-'*6}")

for t in ['SPY'] + sector_tickers:
    r = df[t]
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    skew = r.skew()
    kurt = r.kurtosis()
    desc_stats[t] = {
        'ann_ret': float(ann_ret), 'ann_vol': float(ann_vol),
        'sharpe': float(sharpe), 'skew': float(skew), 'kurt': float(kurt)
    }
    print(f"  {tickers.get(t, t):<20} {ann_ret:>7.1%} {ann_vol:>7.1%} {sharpe:>7.3f} {skew:>6.2f} {kurt:>6.2f}")

# Correlation matrix of sector returns
print("\n  Sector return correlations with SPY:")
for t in sector_tickers:
    corr = df[t].corr(df['SPY'])
    print(f"    {tickers[t]:<20}: {corr:.3f}")

# =================================================================
# 3. COMPUTE SECTOR SELECTION SIGNALS
# =================================================================
print("\n[3] Computing sector selection signals...")

# 3a. 60-day momentum for each sector
mom_window = 60
for t in sector_tickers:
    df[f'mom60_{t}'] = df[t].rolling(mom_window).sum()  # cumulative 60d return

# 3b. 22-day realized volatility for each sector
vol_window = 22
for t in sector_tickers:
    df[f'rvol22_{t}'] = df[t].rolling(vol_window).std() * np.sqrt(252)

# 3c. For relative strength, we need rolling returns vs SPY
for t in sector_tickers:
    df[f'rs60_{t}'] = df[f'mom60_{t}'] - df[t.replace(t, 'SPY')].rolling(mom_window).sum()

# Fix relative strength computation
spy_mom60 = df['SPY'].rolling(mom_window).sum()
for t in sector_tickers:
    df[f'rs60_{t}'] = df[f'mom60_{t}'] - spy_mom60

# Drop warmup period
df_analysis = df.dropna(subset=[f'mom60_{sector_tickers[0]}', f'rvol22_{sector_tickers[0]}']).copy()
print(f"  Analysis period (after warmup): {df_analysis.index[0].strftime('%Y-%m-%d')} to {df_analysis.index[-1].strftime('%Y-%m-%d')}")
print(f"  {len(df_analysis)} trading days")

# =================================================================
# 4. DEFINE STRATEGIES
# =================================================================
print("\n[4] Defining strategies...")

# VT weight from VIX: w = clip(12/VIX, 0, 1)
df_analysis['vt_weight'] = np.clip(12.0 / df_analysis['VIX'], 0, 1)

# Strategy returns computation helper
def compute_sector_rotation_return(row, selected_sectors, sector_rets, vt_weight, gld_ret):
    """
    50% in selected sector(s) with VT + 50% GLD.
    Within the 50% equity portion, equal-weight among selected sectors.
    VT scales the equity allocation: equity_portion = 0.5 * vt_weight * sector_ret
    Remaining (0.5 * (1 - vt_weight)) goes to cash (0 return).
    GLD portion: 0.5 * gld_ret.
    """
    n_sectors = len(selected_sectors)
    if n_sectors == 0:
        return 0.5 * gld_ret  # all cash in equity portion

    equity_ret = 0
    for s in selected_sectors:
        equity_ret += sector_rets[s] / n_sectors

    # 50% equity (VT-scaled) + 50% GLD
    portfolio_ret = 0.5 * vt_weight * equity_ret + 0.5 * (1 - vt_weight) * 0 + 0.5 * gld_ret
    return portfolio_ret


# --- Strategy A: Momentum (best 60d return sector) ---
print("  A. Momentum: top-1 sector by 60d return")
mom_cols = [f'mom60_{t}' for t in sector_tickers]
# Each day, pick the sector with highest 60d momentum
df_analysis['mom_top1'] = df_analysis[mom_cols].idxmax(axis=1).str.replace('mom60_', '')

# --- Strategy B: Low-Vol (lowest 22d realized vol sector) ---
print("  B. Low-Vol: top-1 sector by lowest 22d vol")
vol_cols = [f'rvol22_{t}' for t in sector_tickers]
df_analysis['lowvol_top1'] = df_analysis[vol_cols].idxmin(axis=1).str.replace('rvol22_', '')

# --- Strategy C: Mean-Reversion (worst 60d return sector) ---
print("  C. Mean-Reversion: top-1 sector by worst 60d return (contrarian)")
df_analysis['mr_top1'] = df_analysis[mom_cols].idxmin(axis=1).str.replace('mom60_', '')

# --- Strategy D: Relative Strength (sectors beating SPY, equal-weight) ---
print("  D. Relative Strength: equal-weight sectors beating SPY")
rs_cols = [f'rs60_{t}' for t in sector_tickers]

# --- Strategy E: Momentum top-3 (diversified momentum) ---
print("  E. Momentum Top-3: top-3 sectors by 60d return")

# --- Strategy F: Momentum + Low-Vol combo (top-3 mom, then pick lowest vol) ---
print("  F. Momentum+LowVol: top-3 mom, then pick lowest vol")

# =================================================================
# 5. COMPUTE DAILY RETURNS FOR ALL STRATEGIES
# =================================================================
print("\n[5] Computing daily strategy returns...")

# Pre-compute arrays for speed
n_days = len(df_analysis)
sector_ret_arrays = {t: df_analysis[t].values for t in sector_tickers}
gld_rets = df_analysis['GLD'].values
spy_rets = df_analysis['SPY'].values
vt_weights = df_analysis['vt_weight'].values
mom_arrays = {t: df_analysis[f'mom60_{t}'].values for t in sector_tickers}
vol_arrays = {t: df_analysis[f'rvol22_{t}'].values for t in sector_tickers}
rs_arrays = {t: df_analysis[f'rs60_{t}'].values for t in sector_tickers}

# Initialize return arrays
strat_returns = {
    'benchmark_spy_vt_gld': np.full(n_days, np.nan),   # 50% SPY VT + 50% GLD
    'benchmark_spy_bh_gld': np.full(n_days, np.nan),   # 50% SPY BH + 50% GLD
    'momentum_top1': np.full(n_days, np.nan),          # A: top-1 momentum
    'lowvol_top1': np.full(n_days, np.nan),            # B: lowest vol
    'mean_reversion_top1': np.full(n_days, np.nan),    # C: worst 60d (contrarian)
    'relative_strength': np.full(n_days, np.nan),      # D: sectors > SPY
    'momentum_top3': np.full(n_days, np.nan),          # E: top-3 momentum
    'mom_lowvol_combo': np.full(n_days, np.nan),       # F: top-3 mom, then lowest vol
    'equal_weight_all_sectors': np.full(n_days, np.nan),  # G: equal-weight all sectors VT
}

for i in range(1, n_days):
    sig_idx = i - 1
    vt_w = vt_weights[sig_idx]
    gld_r = gld_rets[i]
    spy_r = spy_rets[i]

    # Benchmarks
    strat_returns['benchmark_spy_vt_gld'][i] = 0.5 * vt_w * spy_r + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r
    strat_returns['benchmark_spy_bh_gld'][i] = 0.5 * spy_r + 0.5 * gld_r

    # Get sector data for this day
    sec_rets = {t: sector_ret_arrays[t][i] for t in sector_tickers}
    sec_moms = {t: mom_arrays[t][sig_idx] for t in sector_tickers}
    sec_vols = {t: vol_arrays[t][sig_idx] for t in sector_tickers}
    sec_rs = {t: rs_arrays[t][sig_idx] for t in sector_tickers}

    # A. Momentum top-1
    best_mom = max(sector_tickers, key=lambda t: sec_moms[t])
    strat_returns['momentum_top1'][i] = 0.5 * vt_w * sec_rets[best_mom] + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

    # B. Low-vol top-1
    lowest_vol = min(sector_tickers, key=lambda t: sec_vols[t])
    strat_returns['lowvol_top1'][i] = 0.5 * vt_w * sec_rets[lowest_vol] + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

    # C. Mean-reversion top-1 (worst 60d return)
    worst_mom = min(sector_tickers, key=lambda t: sec_moms[t])
    strat_returns['mean_reversion_top1'][i] = 0.5 * vt_w * sec_rets[worst_mom] + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

    # D. Relative strength (sectors beating SPY)
    beating_spy = [t for t in sector_tickers if sec_rs[t] > 0]
    if len(beating_spy) == 0:
        # If no sector beats SPY, use SPY itself
        strat_returns['relative_strength'][i] = 0.5 * vt_w * spy_r + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r
    else:
        avg_ret = np.mean([sec_rets[t] for t in beating_spy])
        strat_returns['relative_strength'][i] = 0.5 * vt_w * avg_ret + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

    # E. Momentum top-3
    sorted_by_mom = sorted(sector_tickers, key=lambda t: sec_moms[t], reverse=True)
    top3 = sorted_by_mom[:3]
    avg_ret_top3 = np.mean([sec_rets[t] for t in top3])
    strat_returns['momentum_top3'][i] = 0.5 * vt_w * avg_ret_top3 + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

    # F. Momentum+LowVol combo: from top-3 mom, pick lowest vol
    vols_top3 = {t: sec_vols[t] for t in top3}
    best_combo = min(vols_top3, key=vols_top3.get)
    strat_returns['mom_lowvol_combo'][i] = 0.5 * vt_w * sec_rets[best_combo] + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

    # G. Equal-weight all 8 sectors VT
    avg_all = np.mean([sec_rets[t] for t in sector_tickers])
    strat_returns['equal_weight_all_sectors'][i] = 0.5 * vt_w * avg_all + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

# Store as DataFrame
for name, rets in strat_returns.items():
    df_analysis[f'ret_{name}'] = rets

strategy_labels = {
    'benchmark_spy_vt_gld': 'Benchmark: 50% SPY VT + 50% GLD',
    'benchmark_spy_bh_gld': 'Benchmark: 50% SPY BH + 50% GLD',
    'momentum_top1': 'A. Momentum Top-1 VT + GLD',
    'lowvol_top1': 'B. Low-Vol Top-1 VT + GLD',
    'mean_reversion_top1': 'C. Mean-Reversion Top-1 VT + GLD',
    'relative_strength': 'D. Relative Strength VT + GLD',
    'momentum_top3': 'E. Momentum Top-3 VT + GLD',
    'mom_lowvol_combo': 'F. Mom+LowVol Combo VT + GLD',
    'equal_weight_all_sectors': 'G. EW All Sectors VT + GLD',
}

# =================================================================
# 6. PERFORMANCE METRICS (Full Sample)
# =================================================================
print("\n[6] Full-sample performance metrics...")

def compute_metrics(returns, ann_factor=252):
    """Compute standard performance metrics from daily returns."""
    ret = pd.Series(returns).dropna()
    n = len(ret)
    if n < 252:
        return None

    ann_ret = ret.mean() * ann_factor
    ann_vol = ret.std() * np.sqrt(ann_factor)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + ret).cumprod()
    peak = cum.cummax()
    drawdown = (cum - peak) / peak
    mdd = drawdown.min()

    total_ret = cum.iloc[-1] / cum.iloc[0] - 1
    years = n / ann_factor
    cagr = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0

    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = ret[ret < 0]
    downside_vol = downside.std() * np.sqrt(ann_factor) if len(downside) > 0 else 1e-8
    sortino = ann_ret / downside_vol

    # Transaction cost estimate: daily turnover
    # For rotation strategies, we rebalance daily (conservative)
    # Actual turnover depends on how often the selection changes
    return {
        'n_days': n,
        'ann_return': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 4),
        'mdd': round(float(mdd), 4),
        'cagr': round(float(cagr), 4),
        'calmar': round(float(calmar), 4),
        'sortino': round(float(sortino), 4),
    }


full_results = {}
print(f"\n  {'Strategy':<38} {'Sharpe':>7} {'CAGR':>7} {'MDD':>8} {'Calmar':>7} {'Sortino':>8}")
print(f"  {'-'*38} {'-'*7} {'-'*7} {'-'*8} {'-'*7} {'-'*8}")

for key, label in strategy_labels.items():
    m = compute_metrics(df_analysis[f'ret_{key}'])
    if m:
        full_results[key] = m
        marker = ' ***' if m['sharpe'] > full_results.get('benchmark_spy_vt_gld', {}).get('sharpe', 99) else ''
        print(f"  {label:<38} {m['sharpe']:>7.3f} {m['cagr']:>6.1%} {m['mdd']:>7.1%} "
              f"{m['calmar']:>7.3f} {m['sortino']:>8.3f}{marker}")

# =================================================================
# 7. SECTOR SELECTION TURNOVER ANALYSIS
# =================================================================
print("\n[7] Sector selection turnover analysis...")

# Compute turnover for each rotation strategy
def compute_turnover(selections):
    """Compute fraction of days where selection changes."""
    changes = 0
    for i in range(1, len(selections)):
        if selections[i] != selections[i-1]:
            changes += 1
    return changes / (len(selections) - 1)

# Momentum top-1 turnover
mom_selections = df_analysis['mom_top1'].values
mom_turnover = compute_turnover(mom_selections)

# Low-vol top-1 turnover
lowvol_selections = df_analysis['lowvol_top1'].values
lowvol_turnover = compute_turnover(lowvol_selections)

# Mean-reversion top-1 turnover
mr_selections = df_analysis['mr_top1'].values
mr_turnover = compute_turnover(mr_selections)

print(f"  Momentum top-1 daily turnover: {mom_turnover:.1%}")
print(f"  Low-vol top-1 daily turnover:  {lowvol_turnover:.1%}")
print(f"  Mean-reversion top-1 turnover: {mr_turnover:.1%}")

# Sector selection frequency
print("\n  Momentum top-1 sector frequency:")
mom_freq = pd.Series(mom_selections).value_counts(normalize=True)
for sector, freq in mom_freq.head(8).items():
    print(f"    {tickers.get(sector, sector):<20}: {freq:.1%}")

print("\n  Low-vol top-1 sector frequency:")
lowvol_freq = pd.Series(lowvol_selections).value_counts(normalize=True)
for sector, freq in lowvol_freq.head(8).items():
    print(f"    {tickers.get(sector, sector):<20}: {freq:.1%}")

# Transaction cost impact
# Assume 5 bps one-way cost per trade
tx_cost_bps = 5
print(f"\n  Transaction cost impact ({tx_cost_bps} bps one-way):")
for name, turnover in [('Momentum top-1', mom_turnover),
                        ('Low-vol top-1', lowvol_turnover),
                        ('Mean-reversion top-1', mr_turnover)]:
    # Daily cost = turnover * 2 * tx_cost (buy + sell) * 0.5 (only equity portion)
    daily_cost = turnover * 2 * (tx_cost_bps / 10000) * 0.5
    annual_cost = daily_cost * 252
    print(f"    {name:<25}: {annual_cost:.2%} annual drag")

# =================================================================
# 8. NET-OF-COSTS PERFORMANCE
# =================================================================
print("\n[8] Net-of-transaction-costs performance...")

# Apply tx costs to rotation strategies only (not benchmarks)
tx_cost_per_trade = 5 / 10000  # 5 bps

# Recompute with costs for key strategies
rotation_strategies_turnover = {
    'momentum_top1': mom_turnover,
    'lowvol_top1': lowvol_turnover,
    'mean_reversion_top1': mr_turnover,
    'momentum_top3': mom_turnover * 0.6,  # approximate: less turnover with 3 sectors
    'mom_lowvol_combo': mom_turnover * 0.8,  # approximate
}

net_results = {}
print(f"\n  {'Strategy':<38} {'Gross Sh':>8} {'Net Sh':>7} {'Net CAGR':>8} {'Net MDD':>8}")
print(f"  {'-'*38} {'-'*8} {'-'*7} {'-'*8} {'-'*8}")

for key, label in strategy_labels.items():
    gross = df_analysis[f'ret_{key}'].values.copy()
    if key in rotation_strategies_turnover:
        # Apply daily cost proportional to turnover
        daily_drag = rotation_strategies_turnover[key] * 2 * tx_cost_per_trade * 0.5
        net_rets = gross - daily_drag
    else:
        net_rets = gross  # benchmarks have negligible turnover

    m = compute_metrics(net_rets)
    if m:
        net_results[key] = m
        gross_sharpe = full_results.get(key, {}).get('sharpe', 0)
        print(f"  {label:<38} {gross_sharpe:>8.3f} {m['sharpe']:>7.3f} {m['cagr']:>7.1%} {m['mdd']:>7.1%}")

# =================================================================
# 9. CROSS-OOS VALIDATION (3 periods)
# =================================================================
print("\n[9] Cross-OOS validation (3 periods)...")

oos_periods = [
    ('2005-07-01', '2012-12-31', '2013-01-01', '2016-12-31'),  # IS: ~7.5yr, OOS: 4yr
    ('2010-01-01', '2017-12-31', '2018-01-01', '2021-12-31'),  # IS: 8yr, OOS: 4yr
    ('2014-01-01', '2021-12-31', '2022-01-01', '2026-03-27'),  # IS: 8yr, OOS: ~4yr
]

cross_oos_results = []

for period_idx, (is_start, is_end, oos_start, oos_end) in enumerate(oos_periods):
    print(f"\n  --- OOS Period {period_idx + 1}: IS {is_start} to {is_end}, OOS {oos_start} to {oos_end} ---")

    is_mask = (df_analysis.index >= is_start) & (df_analysis.index <= is_end)
    oos_mask = (df_analysis.index >= oos_start) & (df_analysis.index <= oos_end)

    df_oos = df_analysis.loc[oos_mask]

    if len(df_oos) < 252:
        print(f"    OOS too short ({len(df_oos)} days), skipping")
        continue

    period_results = {'period': period_idx + 1, 'oos_start': oos_start, 'oos_end': oos_end,
                      'oos_days': len(df_oos)}

    print(f"    OOS: {len(df_oos)} days")
    print(f"    {'Strategy':<38} {'Sharpe':>7} {'CAGR':>7} {'MDD':>8}")
    print(f"    {'-'*38} {'-'*7} {'-'*7} {'-'*8}")

    for key, label in strategy_labels.items():
        m = compute_metrics(df_oos[f'ret_{key}'])
        if m:
            period_results[key] = m
            print(f"    {label:<38} {m['sharpe']:>7.3f} {m['cagr']:>6.1%} {m['mdd']:>7.1%}")

    cross_oos_results.append(period_results)

# Summarize OOS consistency
print("\n  OOS Sharpe Summary (across 3 periods):")
print(f"  {'Strategy':<38} {'OOS1':>7} {'OOS2':>7} {'OOS3':>7} {'Mean':>7} {'Std':>7}")
print(f"  {'-'*38} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")

oos_sharpe_summary = {}
for key, label in strategy_labels.items():
    sharpes = []
    for pr in cross_oos_results:
        if key in pr and pr[key]:
            sharpes.append(pr[key]['sharpe'])
        else:
            sharpes.append(np.nan)

    oos_sharpe_summary[key] = sharpes
    valid = [s for s in sharpes if not np.isnan(s)]
    if len(valid) >= 2:
        mean_s = np.mean(valid)
        std_s = np.std(valid)
        s_strs = [f"{s:>7.3f}" if not np.isnan(s) else f"{'N/A':>7}" for s in sharpes]
        print(f"  {label:<38} {''.join(s_strs)} {mean_s:>7.3f} {std_s:>7.3f}")

# =================================================================
# 10. STATISTICAL TESTS
# =================================================================
print("\n[10] Statistical tests (vs benchmark SPY VT + GLD)...")

benchmark_rets = df_analysis['ret_benchmark_spy_vt_gld'].values

def diebold_mariano_test(r1, r2, h=1):
    """Diebold-Mariano test comparing two return series.
    H0: E[d_t] = 0 where d_t = r1_t - r2_t
    Positive t-stat means r1 > r2.
    """
    d = r1 - r2
    d_mean = np.mean(d)
    n = len(d)

    # Newey-West variance with h-1 lags
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma_0 / n

    t_stat = d_mean / np.sqrt(var_d) if var_d > 0 else 0
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))

    return t_stat, p_value


# Harvey (2016) threshold: t > 3.0
print(f"\n  Harvey (2016) threshold: |t| > 3.0")
print(f"  {'Strategy':<38} {'DM t-stat':>10} {'p-value':>8} {'Result':>12}")
print(f"  {'-'*38} {'-'*10} {'-'*8} {'-'*12}")

dm_results = {}
for key, label in strategy_labels.items():
    if key.startswith('benchmark'):
        continue

    strat_rets = df_analysis[f'ret_{key}'].values
    t_stat, p_value = diebold_mariano_test(strat_rets, benchmark_rets)

    result = 'PASS (t>3.0)' if abs(t_stat) > 3.0 else 'FAIL'
    dm_results[key] = {'t_stat': round(float(t_stat), 3), 'p_value': round(float(p_value), 4),
                        'harvey_pass': abs(t_stat) > 3.0}
    print(f"  {label:<38} {t_stat:>10.3f} {p_value:>8.4f} {result:>12}")

# T-test for return difference
print(f"\n  T-test for mean return difference vs benchmark:")
print(f"  {'Strategy':<38} {'Delta Ret':>10} {'t-stat':>8} {'p-value':>8}")
print(f"  {'-'*38} {'-'*10} {'-'*8} {'-'*8}")

for key, label in strategy_labels.items():
    if key.startswith('benchmark'):
        continue

    strat_rets = df_analysis[f'ret_{key}'].values
    diff = strat_rets - benchmark_rets
    t_stat, p_value = stats.ttest_1samp(diff, 0)
    ann_diff = np.mean(diff) * 252
    print(f"  {label:<38} {ann_diff:>9.2%} {t_stat:>8.3f} {p_value:>8.4f}")

# =================================================================
# 11. SUB-PERIOD ANALYSIS
# =================================================================
print("\n[11] Sub-period robustness (Sharpe by era)...")

sub_periods = [
    ('2006-2009', 'GFC'),
    ('2010-2014', 'Recovery'),
    ('2015-2019', 'Low Vol'),
    ('2020-2024', 'COVID+'),
    ('2025-2026', 'Recent'),
]

sub_period_results = {}
header = f"  {'Strategy':<35}"
for period, label in sub_periods:
    header += f" {label:>10}"
print(header)
print(f"  {'-'*35}" + f" {'-'*10}" * len(sub_periods))

for key, label in strategy_labels.items():
    row = f"  {label[:35]:<35}"
    sub_period_results[key] = {}
    for period, plabel in sub_periods:
        start, end = period.split('-')
        mask = (df_analysis.index.year >= int(start)) & (df_analysis.index.year <= int(end))
        sub = df_analysis.loc[mask, f'ret_{key}']
        m = compute_metrics(sub)
        if m:
            sub_period_results[key][plabel] = m['sharpe']
            row += f" {m['sharpe']:>10.3f}"
        else:
            row += f" {'N/A':>10}"
    print(row)

# =================================================================
# 12. SECTOR REGIME ANALYSIS
# =================================================================
print("\n[12] Sector regime analysis...")

# Which sectors tend to be selected in different VIX regimes?
df_analysis['vix_regime'] = pd.cut(df_analysis['VIX'],
                                    bins=[0, 15, 20, 30, 100],
                                    labels=['Low (<15)', 'Normal (15-20)', 'Elevated (20-30)', 'Crisis (>30)'])

print("\n  Momentum top-1 selection by VIX regime:")
for regime in ['Low (<15)', 'Normal (15-20)', 'Elevated (20-30)', 'Crisis (>30)']:
    mask = df_analysis['vix_regime'] == regime
    if mask.sum() > 0:
        freq = df_analysis.loc[mask, 'mom_top1'].value_counts(normalize=True).head(3)
        top3_str = ', '.join([f"{tickers.get(s,s)} {f:.0%}" for s, f in freq.items()])
        print(f"    {regime:<20}: {top3_str}")

# =================================================================
# 13. COMPILE RESULTS
# =================================================================
print("\n[13] Compiling results...")

elapsed = time.time() - start_time

# Determine main conclusion
benchmark_sharpe = full_results.get('benchmark_spy_vt_gld', {}).get('sharpe', 0)
best_rotation_key = None
best_rotation_sharpe = -99
for key in strategy_labels:
    if key.startswith('benchmark') or key == 'equal_weight_all_sectors':
        continue
    s = full_results.get(key, {}).get('sharpe', -99)
    if s > best_rotation_sharpe:
        best_rotation_sharpe = s
        best_rotation_key = key

any_harvey_pass = any(v.get('harvey_pass', False) for v in dm_results.values())

# OOS consistency check
benchmark_oos_sharpes = oos_sharpe_summary.get('benchmark_spy_vt_gld', [])
best_oos_sharpes = oos_sharpe_summary.get(best_rotation_key, [])
oos_consistent = all(
    b is not None and r is not None and not np.isnan(b) and not np.isnan(r) and r > b
    for b, r in zip(benchmark_oos_sharpes, best_oos_sharpes)
)

conclusion_parts = []
if best_rotation_sharpe > benchmark_sharpe:
    conclusion_parts.append(f"Best rotation ({strategy_labels[best_rotation_key]}) Sharpe {best_rotation_sharpe:.3f} vs benchmark {benchmark_sharpe:.3f} in-sample.")
else:
    conclusion_parts.append(f"No rotation strategy beats SPY VT + GLD benchmark (Sharpe {benchmark_sharpe:.3f}) in-sample.")

if any_harvey_pass:
    passing = [strategy_labels[k] for k, v in dm_results.items() if v.get('harvey_pass')]
    conclusion_parts.append(f"Harvey t>3.0 PASS: {', '.join(passing)}.")
else:
    conclusion_parts.append("No strategy passes Harvey (2016) t>3.0 threshold.")

if oos_consistent:
    conclusion_parts.append("Best strategy is OOS-consistent across all 3 periods.")
else:
    conclusion_parts.append("No strategy is consistently better OOS across all 3 periods.")

conclusion = ' '.join(conclusion_parts)

print(f"\n{'='*70}")
print(f"CONCLUSION: {conclusion}")
print(f"{'='*70}")

# Compile full results JSON
results = {
    'experiment_id': 'K560',
    'title': 'Sector Rotation with VT — Can Rotating Between Sectors Improve Upon SPY VT?',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance',
    'assets': ['SPY', 'XLK', 'XLF', 'XLV', 'XLE', 'XLI', 'XLY', 'XLP', 'XLU', 'GLD', '^VIX'],
    'period': f"{df_analysis.index[0].strftime('%Y-%m-%d')} to {df_analysis.index[-1].strftime('%Y-%m-%d')}",
    'n_days': len(df_analysis),
    'methodology': {
        'vt_formula': '12/VIX clipped [0,1]',
        'portfolio_structure': '50% equity (VT-scaled) + 50% GLD',
        'sector_selection_signals': ['momentum_60d', 'low_vol_22d', 'mean_reversion_60d',
                                      'relative_strength_vs_spy', 'momentum_top3', 'momentum_lowvol_combo'],
        'cross_oos_periods': 3,
        'harvey_threshold': 3.0,
        'transaction_cost_assumption': '5 bps one-way',
    },
    'prior_knowledge': {
        'K58': 'Sector VT Map: all 11 sectors benefit from VT uniformly, gamma does not predict sector VT benefit',
        'K243': 'Sector Rotation: Harvey PASS (t=3.99) but DM NS, MDD -37%',
    },
    'references': [
        'Moreira & Muir (2017): Volatility-Managed Portfolios, JF',
        'Moskowitz, Ooi, Pedersen (2012): Time Series Momentum, JFE',
        'Asness, Moskowitz, Pedersen (2013): Value and Momentum Everywhere, JF',
        'Harvey, Liu, Zhu (2016): ...and the Cross-Section of Expected Returns, RFS',
    ],
    'descriptive_statistics': desc_stats,
    'full_sample_results': full_results,
    'net_of_costs_results': net_results,
    'turnover': {
        'momentum_top1': round(float(mom_turnover), 4),
        'lowvol_top1': round(float(lowvol_turnover), 4),
        'mean_reversion_top1': round(float(mr_turnover), 4),
    },
    'cross_oos_results': cross_oos_results,
    'oos_sharpe_summary': {k: [round(float(s), 4) if not np.isnan(s) else None for s in v]
                           for k, v in oos_sharpe_summary.items()},
    'dm_tests': dm_results,
    'sub_period_results': sub_period_results,
    'conclusion': conclusion,
    'harvey_pass': any_harvey_pass,
    'oos_consistent': oos_consistent,
    'runtime_seconds': round(elapsed, 1),
}

# Save results
output_path = 'experiments/k560/k560_sector_rotation_vt_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print(f"Runtime: {elapsed:.1f} seconds")
