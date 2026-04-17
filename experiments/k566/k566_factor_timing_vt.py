#!/usr/bin/env python3
"""
K566: Fama-French Factor Timing with VT — Can Factor Momentum Improve Equity Selection?
=========================================================================================

Motivation:
Instead of sector rotation (K560 — proved to be a microstructure/daily-rebalancing artifact
per K562/K563: weekly Sharpe dropped to 1.1, monthly to 1.23 < benchmark 1.34), what about
FACTOR rotation? Fama-French factors (value, momentum, quality, size) have well-documented
premia. Can we combine factor timing with VT?

Key design difference from K560: MONTHLY rebalancing only (daily proven to be artifact).
This forces us to find genuine factor timing alpha, not rebalancing frequency alpha.

Prior knowledge:
- K560: Sector rotation + VT: Daily Sharpe 2.16 but monthly 1.23 (< benchmark 1.34)
- K562: Deep validation showed monthly sector momentum FAILS
- K563: Weekly sector momentum Harvey t=2.73 FAIL — alpha decays monotonically with frequency
- K58: Sector VT Map — all sectors benefit from VT uniformly
- N79-N89: 12/VIX is the best lazy VT strategy (Sharpe ~0.6-0.7)
- K226: Factor exposure analysis (prior work)

Design:
1. Factor ETF proxies (all from yfinance):
   - Value: VLUE (iShares MSCI USA Value Factor)
   - Momentum: MTUM (iShares MSCI USA Momentum Factor)
   - Quality: QUAL (iShares MSCI USA Quality Factor)
   - Size (small cap): IWM (iShares Russell 2000)
   - Low Volatility: USMV (iShares MSCI USA Min Vol)
   - Market: SPY (benchmark)
2. VT weight = min(12/VIX, 1.0) applied to selected factor ETF (not SPY)
3. Selection rules (all monthly rebalanced):
   a. Momentum factor rotation: pick factor ETF with best 60d return
   b. Low-vol factor: always use USMV instead of SPY
   c. Quality tilt: always use QUAL instead of SPY
   d. Factor momentum + VT: rotate among top-2 factors monthly
   e. Equal-weight all 5 factors
   f. Momentum top-1 (20d lookback for sensitivity)
4. All paired with 50% GLD
5. Benchmark: SPY VT + GLD (standard 12/VIX)
6. Monthly rebalancing (practical, avoids K560 artifact)
7. Cross-OOS: 3 periods
8. Harvey (2016) t > 3.0
9. Transaction costs: 5 bps per trade

Key insight: Factor ETFs existed from ~2013. Limited history (~11 years) but useful for
recent regime (post-QE, COVID, rate hikes). We acknowledge this limitation.

Literature:
- Moreira & Muir (2017): "Volatility-Managed Portfolios", JF
- Asness, Moskowitz, Pedersen (2013): "Value and Momentum Everywhere", JF
- Arnott, Harvey, Kalesnik, Linnainmaa (2021): "Reports of Value's Death May Be Greatly
  Exaggerated", Financial Analysts Journal
- Harvey, Liu, Zhu (2016): "...and the Cross-Section of Expected Returns", RFS
- Fama & French (2015): "A five-factor model", JFE
- Gupta & Kelly (2019): "Factor Momentum Everywhere", JFE

Data source: yfinance (VLUE, MTUM, QUAL, IWM, USMV, SPY, GLD, ^VIX)
Period: 2014-2026 (limited by factor ETF inception dates)
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
print("K566: Fama-French Factor Timing with VT")
print("Can Factor Momentum Improve Equity Selection?")
print("=" * 70)

# =================================================================
# 1. DATA DOWNLOAD
# =================================================================
print("\n[1] Downloading data...")

factor_etfs = {
    'VLUE': 'Value (MSCI USA Value)',
    'MTUM': 'Momentum (MSCI USA Mom)',
    'QUAL': 'Quality (MSCI USA Quality)',
    'IWM': 'Size (Russell 2000)',
    'USMV': 'Low-Vol (MSCI Min Vol)',
}

all_tickers_map = {
    'SPY': 'S&P 500 (Benchmark)',
    'GLD': 'Gold',
    **factor_etfs,
}

factor_tickers = list(factor_etfs.keys())
all_tickers = list(all_tickers_map.keys()) + ['^VIX']

# Download all at once
raw = yf.download(all_tickers, start="2012-01-01", end="2026-12-31", progress=False)

# Flatten multi-level columns
if isinstance(raw.columns, pd.MultiIndex):
    close = raw['Close']
else:
    close = raw[['Close']]

# VIX column
vix = close['^VIX'].dropna()
vix.name = 'VIX'

# Check data availability for each factor ETF
print("\n  Factor ETF data availability:")
for t in factor_tickers:
    series = close[t].dropna()
    print(f"    {t} ({factor_etfs[t]}): {series.index[0].strftime('%Y-%m-%d')} to {series.index[-1].strftime('%Y-%m-%d')} ({len(series)} days)")

# Compute daily returns
returns = close[list(all_tickers_map.keys())].pct_change()

# Align with VIX and drop NAs
df = returns.join(vix, how='inner').dropna()

# Start from 2014 to ensure all factor ETFs have data
df = df.loc['2014-01-01':]

print(f"\n  Analysis data: {len(df)} trading days ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
print(f"  VIX range: {df['VIX'].min():.1f} - {df['VIX'].max():.1f}, median {df['VIX'].median():.1f}")

# =================================================================
# 2. DESCRIPTIVE STATISTICS
# =================================================================
print("\n[2] Factor ETF descriptive statistics (annualized)...")

desc_stats = {}
print(f"  {'Factor ETF':<30} {'Ann Ret':>8} {'Ann Vol':>8} {'Sharpe':>7} {'Skew':>6} {'Kurt':>6} {'Corr SPY':>9}")
print(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*7} {'-'*6} {'-'*6} {'-'*9}")

for t in ['SPY'] + factor_tickers + ['GLD']:
    r = df[t]
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    skew_val = r.skew()
    kurt_val = r.kurtosis()
    corr_spy = r.corr(df['SPY'])
    desc_stats[t] = {
        'ann_ret': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 4),
        'skew': round(float(skew_val), 4),
        'kurt': round(float(kurt_val), 4),
        'corr_spy': round(float(corr_spy), 4),
    }
    label = all_tickers_map.get(t, t)
    print(f"  {label:<30} {ann_ret:>7.1%} {ann_vol:>7.1%} {sharpe:>7.3f} {skew_val:>6.2f} {kurt_val:>6.2f} {corr_spy:>9.3f}")

# Factor ETF correlation matrix
print("\n  Factor ETF return correlations:")
factor_plus_spy = ['SPY'] + factor_tickers
corr_matrix = df[factor_plus_spy].corr()
header = f"  {'':>10}"
for t in factor_plus_spy:
    header += f" {t:>6}"
print(header)
for t1 in factor_plus_spy:
    row = f"  {t1:>10}"
    for t2 in factor_plus_spy:
        row += f" {corr_matrix.loc[t1, t2]:>6.3f}"
    print(row)

# =================================================================
# 3. COMPUTE FACTOR SELECTION SIGNALS
# =================================================================
print("\n[3] Computing factor selection signals...")

# 3a. 60-day momentum for each factor ETF
mom_window_60 = 60
for t in factor_tickers:
    df[f'mom60_{t}'] = df[t].rolling(mom_window_60).sum()  # cumulative 60d return

# 3b. 20-day momentum (sensitivity check)
mom_window_20 = 20
for t in factor_tickers:
    df[f'mom20_{t}'] = df[t].rolling(mom_window_20).sum()

# 3c. 22-day realized volatility for each factor
vol_window = 22
for t in factor_tickers:
    df[f'rvol22_{t}'] = df[t].rolling(vol_window).std() * np.sqrt(252)

# Drop warmup period
warmup_cols = [f'mom60_{factor_tickers[0]}', f'rvol22_{factor_tickers[0]}']
df_analysis = df.dropna(subset=warmup_cols).copy()
print(f"  Analysis period (after warmup): {df_analysis.index[0].strftime('%Y-%m-%d')} to {df_analysis.index[-1].strftime('%Y-%m-%d')}")
print(f"  {len(df_analysis)} trading days")

# =================================================================
# 4. DEFINE MONTHLY REBALANCING DATES
# =================================================================
print("\n[4] Setting up monthly rebalancing...")

# Identify month-end dates (last trading day of each month)
df_analysis['year_month'] = df_analysis.index.to_period('M')
month_ends = df_analysis.groupby('year_month').apply(lambda x: x.index[-1])
rebal_dates = set(pd.Timestamp(d) for d in month_ends.values)
print(f"  Monthly rebalance dates: {len(rebal_dates)} months")
print(f"  First rebal: {pd.Timestamp(min(rebal_dates)).strftime('%Y-%m-%d')}, Last: {pd.Timestamp(max(rebal_dates)).strftime('%Y-%m-%d')}")

# =================================================================
# 5. COMPUTE VT WEIGHT
# =================================================================
df_analysis['vt_weight'] = np.clip(12.0 / df_analysis['VIX'], 0, 1)

# =================================================================
# 6. DEFINE AND COMPUTE STRATEGIES (MONTHLY REBALANCING)
# =================================================================
print("\n[5] Computing strategy returns (monthly rebalancing)...")

n_days = len(df_analysis)
dates = df_analysis.index
gld_rets = df_analysis['GLD'].values
spy_rets = df_analysis['SPY'].values
vt_weights = df_analysis['vt_weight'].values

# Pre-compute factor arrays
factor_ret_arrays = {t: df_analysis[t].values for t in factor_tickers}
mom60_arrays = {t: df_analysis[f'mom60_{t}'].values for t in factor_tickers}
mom20_arrays = {t: df_analysis[f'mom20_{t}'].values for t in factor_tickers}
rvol22_arrays = {t: df_analysis[f'rvol22_{t}'].values for t in factor_tickers}

# Initialize return arrays
strategy_names = [
    'benchmark_spy_vt_gld',         # 50% SPY VT + 50% GLD
    'benchmark_spy_bh_gld',         # 50% SPY BH + 50% GLD
    'mom_top1_60d',                 # A: best factor by 60d return
    'mom_top1_20d',                 # B: best factor by 20d return (sensitivity)
    'mom_top2_60d',                 # C: top-2 factors by 60d return
    'static_usmv',                  # D: always USMV (low-vol)
    'static_qual',                  # E: always QUAL (quality)
    'equal_weight_5factors',        # F: equal-weight all 5 factors
    'mom_top1_60d_daily',           # G: daily rebal for comparison (expect artifact)
]

strat_returns = {name: np.zeros(n_days) for name in strategy_names}

strategy_labels = {
    'benchmark_spy_vt_gld': 'Benchmark: 50% SPY VT + 50% GLD',
    'benchmark_spy_bh_gld': 'Benchmark: 50% SPY BH + 50% GLD',
    'mom_top1_60d': 'A. Monthly Mom Top-1 (60d) VT+GLD',
    'mom_top1_20d': 'B. Monthly Mom Top-1 (20d) VT+GLD',
    'mom_top2_60d': 'C. Monthly Mom Top-2 (60d) VT+GLD',
    'static_usmv': 'D. Static USMV VT + GLD',
    'static_qual': 'E. Static QUAL VT + GLD',
    'equal_weight_5factors': 'F. EW 5 Factors VT + GLD',
    'mom_top1_60d_daily': 'G. Daily Mom Top-1 (60d) VT+GLD',
}

# Track selections for turnover and analysis
monthly_selections_60d = []  # (date, selected_factor)
monthly_selections_20d = []
monthly_selections_top2 = []

# Current monthly selections (persist between rebalances)
current_top1_60d = None
current_top1_20d = None
current_top2_60d = None

for i in range(n_days):
    vt_w = vt_weights[i]
    gld_r = gld_rets[i]
    spy_r = spy_rets[i]
    date = dates[i]

    # Benchmarks (daily rebalanced VT weight, which is the standard)
    strat_returns['benchmark_spy_vt_gld'][i] = 0.5 * vt_w * spy_r + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r
    strat_returns['benchmark_spy_bh_gld'][i] = 0.5 * spy_r + 0.5 * gld_r

    # Get factor data for this day
    fac_rets = {t: factor_ret_arrays[t][i] for t in factor_tickers}
    fac_mom60 = {t: mom60_arrays[t][i] for t in factor_tickers}
    fac_mom20 = {t: mom20_arrays[t][i] for t in factor_tickers}

    # --- Monthly rebalancing: update selections on rebal dates ---
    if date in rebal_dates or current_top1_60d is None:
        # A. Momentum top-1 (60d)
        current_top1_60d = max(factor_tickers, key=lambda t: fac_mom60[t])
        monthly_selections_60d.append((date, current_top1_60d))

        # B. Momentum top-1 (20d)
        current_top1_20d = max(factor_tickers, key=lambda t: fac_mom20[t])
        monthly_selections_20d.append((date, current_top1_20d))

        # C. Top-2 factors (60d)
        sorted_by_mom = sorted(factor_tickers, key=lambda t: fac_mom60[t], reverse=True)
        current_top2_60d = sorted_by_mom[:2]
        monthly_selections_top2.append((date, tuple(current_top2_60d)))

    # A. Monthly momentum top-1 (60d)
    strat_returns['mom_top1_60d'][i] = 0.5 * vt_w * fac_rets[current_top1_60d] + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

    # B. Monthly momentum top-1 (20d)
    strat_returns['mom_top1_20d'][i] = 0.5 * vt_w * fac_rets[current_top1_20d] + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

    # C. Monthly momentum top-2 (60d) — equal-weight
    avg_top2 = np.mean([fac_rets[t] for t in current_top2_60d])
    strat_returns['mom_top2_60d'][i] = 0.5 * vt_w * avg_top2 + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

    # D. Static USMV (always low-vol)
    strat_returns['static_usmv'][i] = 0.5 * vt_w * fac_rets['USMV'] + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

    # E. Static QUAL (always quality)
    strat_returns['static_qual'][i] = 0.5 * vt_w * fac_rets['QUAL'] + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

    # F. Equal-weight all 5 factors
    avg_all = np.mean([fac_rets[t] for t in factor_tickers])
    strat_returns['equal_weight_5factors'][i] = 0.5 * vt_w * avg_all + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

    # G. Daily rebalanced momentum (for artifact comparison)
    daily_best = max(factor_tickers, key=lambda t: fac_mom60[t])
    strat_returns['mom_top1_60d_daily'][i] = 0.5 * vt_w * fac_rets[daily_best] + 0.5 * (1 - vt_w) * 0 + 0.5 * gld_r

# Store returns in DataFrame
for name, rets in strat_returns.items():
    df_analysis[f'ret_{name}'] = rets

print(f"  Computed {len(strategy_names)} strategies over {n_days} days")

# =================================================================
# 7. PERFORMANCE METRICS (Full Sample)
# =================================================================
print("\n[6] Full-sample performance metrics...")


def compute_metrics(rets):
    """Compute Sharpe, CAGR, MDD, Calmar, Sortino from daily returns."""
    rets = np.array(rets)
    if len(rets) < 252 or np.std(rets) == 0:
        return None

    ann_ret = np.mean(rets) * 252
    ann_vol = np.std(rets) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # CAGR
    cum = np.cumprod(1 + rets)
    years = len(rets) / 252
    cagr = (cum[-1] ** (1.0 / years) - 1) if cum[-1] > 0 and years > 0 else 0

    # MDD
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    mdd = np.min(dd)

    # Calmar
    calmar = cagr / abs(mdd) if abs(mdd) > 0.001 else 0

    # Sortino
    downside = rets[rets < 0]
    downside_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0

    return {
        'sharpe': round(float(sharpe), 4),
        'cagr': round(float(cagr), 4),
        'mdd': round(float(mdd), 4),
        'calmar': round(float(calmar), 4),
        'sortino': round(float(sortino), 4),
        'ann_ret': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4),
        'n_days': int(len(rets)),
    }


full_results = {}
print(f"\n  {'Strategy':<42} {'Sharpe':>7} {'CAGR':>7} {'MDD':>8} {'Calmar':>7} {'Sortino':>8}")
print(f"  {'-'*42} {'-'*7} {'-'*7} {'-'*8} {'-'*7} {'-'*8}")

for key, label in strategy_labels.items():
    m = compute_metrics(df_analysis[f'ret_{key}'].values)
    if m:
        full_results[key] = m
        marker = ' ***' if key != 'benchmark_spy_vt_gld' and m['sharpe'] > full_results.get('benchmark_spy_vt_gld', {}).get('sharpe', 99) else ''
        print(f"  {label:<42} {m['sharpe']:>7.3f} {m['cagr']:>6.1%} {m['mdd']:>7.1%} "
              f"{m['calmar']:>7.3f} {m['sortino']:>8.3f}{marker}")

# =================================================================
# 8. FACTOR SELECTION ANALYSIS
# =================================================================
print("\n[7] Factor selection analysis...")

# 8a. Monthly selection frequency (60d momentum)
print("\n  A. Monthly Mom Top-1 (60d) — factor selection frequency:")
selections_60d = [s[1] for s in monthly_selections_60d]
sel_freq_60d = pd.Series(selections_60d).value_counts(normalize=True)
for factor, freq in sel_freq_60d.items():
    print(f"    {factor_etfs.get(factor, factor):<30}: {freq:.1%}")

# 8b. Monthly selection frequency (20d momentum)
print("\n  B. Monthly Mom Top-1 (20d) — factor selection frequency:")
selections_20d = [s[1] for s in monthly_selections_20d]
sel_freq_20d = pd.Series(selections_20d).value_counts(normalize=True)
for factor, freq in sel_freq_20d.items():
    print(f"    {factor_etfs.get(factor, factor):<30}: {freq:.1%}")

# 8c. Monthly turnover (how often selection changes)
def compute_monthly_turnover(selections):
    """Fraction of months where selection changes."""
    if len(selections) <= 1:
        return 0
    changes = sum(1 for i in range(1, len(selections)) if selections[i] != selections[i - 1])
    return changes / (len(selections) - 1)

turnover_60d = compute_monthly_turnover(selections_60d)
turnover_20d = compute_monthly_turnover(selections_20d)
turnover_top2 = compute_monthly_turnover([s[1] for s in monthly_selections_top2])

print(f"\n  Monthly turnover rates:")
print(f"    Mom Top-1 (60d): {turnover_60d:.1%} months change")
print(f"    Mom Top-1 (20d): {turnover_20d:.1%} months change")
print(f"    Mom Top-2 (60d): {turnover_top2:.1%} months change")

# Transaction cost impact (monthly rebalancing)
tx_cost_bps = 5
print(f"\n  Transaction cost impact ({tx_cost_bps} bps one-way, monthly rebalancing):")
for name, turnover_rate in [('Mom Top-1 (60d)', turnover_60d),
                             ('Mom Top-1 (20d)', turnover_20d),
                             ('Mom Top-2 (60d)', turnover_top2)]:
    # Monthly cost: turnover * 2 (buy+sell) * tx_cost * 0.5 (equity portion) / 12 months
    # Actually: fraction of months that change * 2 * cost per trade * 0.5
    annual_cost = turnover_rate * 12 * 2 * (tx_cost_bps / 10000) * 0.5  # ~12 potential changes/yr
    # Correction: turnover_rate is already fraction of rebalances that change
    # Annual trades = 12 * turnover_rate, each trade costs 2*5bp on equity portion (0.5)
    annual_cost = 12 * turnover_rate * 2 * (tx_cost_bps / 10000) * 0.5
    print(f"    {name:<25}: {annual_cost:.3%} annual drag ({12 * turnover_rate:.1f} trades/yr)")

# =================================================================
# 9. NET-OF-COSTS PERFORMANCE
# =================================================================
print("\n[8] Net-of-transaction-costs performance...")

# Monthly TX cost: when selection changes, incur 2 * 5bp on equity portion
# Per-day cost = (annual trades * 2 * 5bp * 0.5) / 252
rotation_strategies_annual_cost = {
    'mom_top1_60d': 12 * turnover_60d * 2 * (tx_cost_bps / 10000) * 0.5,
    'mom_top1_20d': 12 * turnover_20d * 2 * (tx_cost_bps / 10000) * 0.5,
    'mom_top2_60d': 12 * turnover_top2 * 2 * (tx_cost_bps / 10000) * 0.5,
    'mom_top1_60d_daily': 252 * 0.15 * 2 * (tx_cost_bps / 10000) * 0.5,  # ~15% daily turnover estimate
    # Static strategies: rebalance monthly (VT weight changes but no factor selection change)
    'static_usmv': 0,
    'static_qual': 0,
    'equal_weight_5factors': 0,
}

net_results = {}
print(f"\n  {'Strategy':<42} {'Gross Sh':>8} {'Net Sh':>7} {'Net CAGR':>8} {'TX Drag':>8}")
print(f"  {'-'*42} {'-'*8} {'-'*7} {'-'*8} {'-'*8}")

for key, label in strategy_labels.items():
    gross = df_analysis[f'ret_{key}'].values.copy()
    annual_drag = rotation_strategies_annual_cost.get(key, 0)
    daily_drag = annual_drag / 252
    net_rets = gross - daily_drag

    m = compute_metrics(net_rets)
    if m:
        net_results[key] = m
        gross_sharpe = full_results.get(key, {}).get('sharpe', 0)
        print(f"  {label:<42} {gross_sharpe:>8.3f} {m['sharpe']:>7.3f} {m['cagr']:>7.1%} {annual_drag:>7.2%}")

# =================================================================
# 10. DAILY vs MONTHLY REBALANCING COMPARISON
# =================================================================
print("\n[9] Daily vs Monthly rebalancing comparison (K560 artifact check)...")
print(f"    This is the KEY test: does factor momentum survive monthly rebalancing?")

daily_sharpe = full_results.get('mom_top1_60d_daily', {}).get('sharpe', 0)
monthly_sharpe = full_results.get('mom_top1_60d', {}).get('sharpe', 0)
benchmark_sharpe = full_results.get('benchmark_spy_vt_gld', {}).get('sharpe', 0)

print(f"\n    Daily rebal Mom Top-1:   Sharpe {daily_sharpe:.3f}")
print(f"    Monthly rebal Mom Top-1: Sharpe {monthly_sharpe:.3f}")
print(f"    Benchmark SPY VT+GLD:   Sharpe {benchmark_sharpe:.3f}")
print(f"    Daily-Monthly gap:       {daily_sharpe - monthly_sharpe:+.3f}")
print(f"    Monthly vs Benchmark:    {monthly_sharpe - benchmark_sharpe:+.3f}")

if daily_sharpe > monthly_sharpe + 0.2:
    print(f"    >>> WARNING: Large daily-monthly gap ({daily_sharpe - monthly_sharpe:.3f}) suggests rebalancing artifact (same as K560)")
if monthly_sharpe < benchmark_sharpe:
    print(f"    >>> RESULT: Monthly factor momentum FAILS to beat benchmark (same pattern as K560/K563)")
else:
    print(f"    >>> RESULT: Monthly factor momentum beats benchmark by {monthly_sharpe - benchmark_sharpe:.3f}")

# =================================================================
# 11. CROSS-OOS VALIDATION (3 periods)
# =================================================================
print("\n[10] Cross-OOS validation (3 periods)...")

# Given data starts ~2014, we need to split carefully
# Factor ETFs are relatively recent, so periods are shorter
oos_periods = [
    ('2014-04-01', '2017-12-31', '2018-01-01', '2020-06-30'),  # IS: ~3.75yr, OOS: 2.5yr
    ('2016-01-01', '2020-06-30', '2020-07-01', '2023-06-30'),  # IS: 4.5yr, OOS: 3yr (COVID era)
    ('2018-01-01', '2023-06-30', '2023-07-01', '2026-03-27'),  # IS: 5.5yr, OOS: ~2.75yr (recent)
]

cross_oos_results = []

for period_idx, (is_start, is_end, oos_start, oos_end) in enumerate(oos_periods):
    print(f"\n  --- OOS Period {period_idx + 1}: IS {is_start} to {is_end}, OOS {oos_start} to {oos_end} ---")

    oos_mask = (df_analysis.index >= oos_start) & (df_analysis.index <= oos_end)
    df_oos = df_analysis.loc[oos_mask]

    if len(df_oos) < 126:  # minimum ~6 months
        print(f"    OOS too short ({len(df_oos)} days), skipping")
        continue

    period_results = {
        'period': period_idx + 1,
        'oos_start': oos_start,
        'oos_end': oos_end,
        'oos_days': len(df_oos),
    }

    print(f"    OOS: {len(df_oos)} days")
    print(f"    {'Strategy':<42} {'Sharpe':>7} {'CAGR':>7} {'MDD':>8}")
    print(f"    {'-'*42} {'-'*7} {'-'*7} {'-'*8}")

    for key, label in strategy_labels.items():
        m = compute_metrics(df_oos[f'ret_{key}'].values)
        if m:
            period_results[key] = m
            print(f"    {label:<42} {m['sharpe']:>7.3f} {m['cagr']:>6.1%} {m['mdd']:>7.1%}")
        else:
            # Even if too short for full metrics, compute Sharpe
            oos_rets = df_oos[f'ret_{key}'].values
            if len(oos_rets) > 0 and np.std(oos_rets) > 0:
                s = np.mean(oos_rets) / np.std(oos_rets) * np.sqrt(252)
                period_results[key] = {'sharpe': round(float(s), 4)}
                print(f"    {label:<42} {s:>7.3f}   (short)")

    cross_oos_results.append(period_results)

# OOS Sharpe summary
print("\n  OOS Sharpe Summary (across 3 periods):")
print(f"  {'Strategy':<42} {'OOS1':>7} {'OOS2':>7} {'OOS3':>7} {'Mean':>7}")
print(f"  {'-'*42} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")

oos_sharpe_summary = {}
for key, label in strategy_labels.items():
    sharpes = []
    for pr in cross_oos_results:
        if key in pr and pr[key] and 'sharpe' in pr[key]:
            sharpes.append(pr[key]['sharpe'])
        else:
            sharpes.append(np.nan)

    oos_sharpe_summary[key] = sharpes
    valid = [s for s in sharpes if not np.isnan(s)]
    if len(valid) >= 2:
        mean_s = np.mean(valid)
        s_strs = [f"{s:>7.3f}" if not np.isnan(s) else f"{'N/A':>7}" for s in sharpes]
        print(f"  {label:<42} {''.join(s_strs)} {mean_s:>7.3f}")

# Count how many OOS periods each strategy beats benchmark
print("\n  OOS periods beating benchmark:")
bench_oos = oos_sharpe_summary.get('benchmark_spy_vt_gld', [])
for key, label in strategy_labels.items():
    if key.startswith('benchmark'):
        continue
    strat_oos = oos_sharpe_summary.get(key, [])
    wins = sum(1 for s, b in zip(strat_oos, bench_oos)
               if not np.isnan(s) and not np.isnan(b) and s > b)
    total = sum(1 for s, b in zip(strat_oos, bench_oos)
                if not np.isnan(s) and not np.isnan(b))
    print(f"    {label:<42}: {wins}/{total}")

# =================================================================
# 12. STATISTICAL TESTS
# =================================================================
print("\n[11] Statistical tests (vs benchmark SPY VT + GLD)...")

benchmark_rets = df_analysis['ret_benchmark_spy_vt_gld'].values


def diebold_mariano_test(r1, r2, h=1):
    """Diebold-Mariano test comparing two return series.
    H0: E[d_t] = 0 where d_t = r1_t - r2_t
    Uses Newey-West variance.
    Positive t-stat means r1 > r2.
    """
    d = r1 - r2
    d_mean = np.mean(d)
    n = len(d)

    # Newey-West with optimal lag selection
    max_lag = int(np.ceil(n ** (1 / 3)))  # Optimal lag ~ n^(1/3)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, max_lag + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        w_k = 1 - k / (max_lag + 1)  # Bartlett kernel
        gamma_sum += 2 * w_k * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma_0 / n

    t_stat = d_mean / np.sqrt(var_d) if var_d > 0 else 0
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

    return t_stat, p_value


# Harvey (2016) threshold: t > 3.0
print(f"\n  Harvey (2016) threshold: |t| > 3.0 (Newey-West SE)")
print(f"  {'Strategy':<42} {'DM t-stat':>10} {'p-value':>8} {'Result':>12}")
print(f"  {'-'*42} {'-'*10} {'-'*8} {'-'*12}")

dm_results = {}
for key, label in strategy_labels.items():
    if key.startswith('benchmark'):
        continue

    strat_rets = df_analysis[f'ret_{key}'].values
    t_stat, p_value = diebold_mariano_test(strat_rets, benchmark_rets)

    result = 'PASS (t>3.0)' if abs(t_stat) > 3.0 and t_stat > 0 else 'FAIL'
    dm_results[key] = {
        't_stat': round(float(t_stat), 3),
        'p_value': round(float(p_value), 4),
        'harvey_pass': bool(abs(t_stat) > 3.0 and t_stat > 0),
    }
    print(f"  {label:<42} {t_stat:>10.3f} {p_value:>8.4f} {result:>12}")

# T-test for mean return difference
print(f"\n  T-test for mean return difference vs benchmark:")
print(f"  {'Strategy':<42} {'Delta Ret':>10} {'t-stat':>8} {'p-value':>8}")
print(f"  {'-'*42} {'-'*10} {'-'*8} {'-'*8}")

for key, label in strategy_labels.items():
    if key.startswith('benchmark'):
        continue

    strat_rets = df_analysis[f'ret_{key}'].values
    diff = strat_rets - benchmark_rets
    t_stat, p_value = stats.ttest_1samp(diff, 0)
    ann_diff = np.mean(diff) * 252
    print(f"  {label:<42} {ann_diff:>9.2%} {t_stat:>8.3f} {p_value:>8.4f}")

# =================================================================
# 13. SUB-PERIOD ANALYSIS
# =================================================================
print("\n[12] Sub-period robustness (Sharpe by era)...")

sub_periods = [
    ('2014-2016', 'Post-Taper'),
    ('2017-2019', 'Low Vol'),
    ('2020-2021', 'COVID Era'),
    ('2022-2023', 'Rate Hikes'),
    ('2024-2026', 'Recent'),
]

sub_period_results = {}
header = f"  {'Strategy':<40}"
for period, label in sub_periods:
    header += f" {label:>12}"
print(header)
print(f"  {'-'*40}" + f" {'-'*12}" * len(sub_periods))

for key, label in strategy_labels.items():
    row = f"  {label[:40]:<40}"
    sub_period_results[key] = {}
    for period, plabel in sub_periods:
        start, end = period.split('-')
        mask = (df_analysis.index.year >= int(start)) & (df_analysis.index.year <= int(end))
        sub = df_analysis.loc[mask, f'ret_{key}']
        m = compute_metrics(sub)
        if m:
            sub_period_results[key][plabel] = m['sharpe']
            row += f" {m['sharpe']:>12.3f}"
        else:
            # Short period fallback
            if len(sub) > 0 and np.std(sub) > 0:
                s = float(np.mean(sub) / np.std(sub) * np.sqrt(252))
                sub_period_results[key][plabel] = round(s, 4)
                row += f" {s:>12.3f}"
            else:
                row += f" {'N/A':>12}"
    print(row)

# =================================================================
# 14. VIX REGIME ANALYSIS
# =================================================================
print("\n[13] Factor selection by VIX regime...")

df_analysis['vix_regime'] = pd.cut(df_analysis['VIX'],
                                    bins=[0, 15, 20, 30, 100],
                                    labels=['Low (<15)', 'Normal (15-20)', 'Elevated (20-30)', 'Crisis (>30)'])

# Which factors get selected in each regime?
# Use the monthly selections data
sel_df = pd.DataFrame(monthly_selections_60d, columns=['date', 'factor'])
sel_df = sel_df.set_index('date')
sel_df = sel_df.join(df_analysis[['VIX', 'vix_regime']], how='left')

print("\n  Mom Top-1 (60d) factor selection by VIX regime:")
for regime in ['Low (<15)', 'Normal (15-20)', 'Elevated (20-30)', 'Crisis (>30)']:
    mask = sel_df['vix_regime'] == regime
    n_months = mask.sum()
    if n_months > 0:
        freq = sel_df.loc[mask, 'factor'].value_counts(normalize=True).head(3)
        top_str = ', '.join([f"{factor_etfs.get(f, f)} {pct:.0%}" for f, pct in freq.items()])
        print(f"    {regime:<20} (n={n_months:>3}): {top_str}")

# Performance by VIX regime
print("\n  Strategy Sharpe by VIX regime:")
print(f"  {'Strategy':<42} {'Low':>8} {'Normal':>8} {'Elevated':>8} {'Crisis':>8}")
print(f"  {'-'*42} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

for key, label in strategy_labels.items():
    row = f"  {label[:42]:<42}"
    for regime in ['Low (<15)', 'Normal (15-20)', 'Elevated (20-30)', 'Crisis (>30)']:
        mask = df_analysis['vix_regime'] == regime
        sub = df_analysis.loc[mask, f'ret_{key}']
        if len(sub) > 0 and np.std(sub) > 0:
            s = float(np.mean(sub) / np.std(sub) * np.sqrt(252))
            row += f" {s:>8.2f}"
        else:
            row += f" {'N/A':>8}"
    print(row)

# =================================================================
# 15. COMPILE RESULTS & CONCLUSION
# =================================================================
print("\n[14] Compiling results...")

elapsed = time.time() - start_time

# Determine main conclusion
benchmark_sharpe_val = full_results.get('benchmark_spy_vt_gld', {}).get('sharpe', 0)
best_monthly_key = None
best_monthly_sharpe = -99
for key in strategy_labels:
    if key.startswith('benchmark') or key == 'mom_top1_60d_daily':
        continue
    s = full_results.get(key, {}).get('sharpe', -99)
    if s > best_monthly_sharpe:
        best_monthly_sharpe = s
        best_monthly_key = key

any_harvey_pass = any(v.get('harvey_pass', False) for k, v in dm_results.items()
                      if k != 'mom_top1_60d_daily')

# OOS consistency
bench_oos_s = oos_sharpe_summary.get('benchmark_spy_vt_gld', [])
best_oos_s = oos_sharpe_summary.get(best_monthly_key, [])
oos_consistent = all(
    b is not None and r is not None and not np.isnan(b) and not np.isnan(r) and r > b
    for b, r in zip(bench_oos_s, best_oos_s)
)

# Daily vs monthly gap (artifact check)
daily_mom_sharpe = full_results.get('mom_top1_60d_daily', {}).get('sharpe', 0)
monthly_mom_sharpe = full_results.get('mom_top1_60d', {}).get('sharpe', 0)
artifact_gap = daily_mom_sharpe - monthly_mom_sharpe

conclusion_parts = []

# Monthly vs benchmark
if best_monthly_sharpe > benchmark_sharpe_val:
    conclusion_parts.append(
        f"Best monthly factor rotation ({strategy_labels[best_monthly_key]}) "
        f"Sharpe {best_monthly_sharpe:.3f} vs benchmark {benchmark_sharpe_val:.3f} (+{best_monthly_sharpe - benchmark_sharpe_val:.3f})."
    )
else:
    conclusion_parts.append(
        f"No monthly factor rotation strategy beats SPY VT+GLD benchmark "
        f"(Sharpe {benchmark_sharpe_val:.3f}). Best: {best_monthly_sharpe:.3f}."
    )

# Harvey test
if any_harvey_pass:
    passing = [strategy_labels[k] for k, v in dm_results.items()
               if v.get('harvey_pass') and k != 'mom_top1_60d_daily']
    conclusion_parts.append(f"Harvey t>3.0 PASS: {', '.join(passing)}.")
else:
    conclusion_parts.append("No monthly strategy passes Harvey (2016) t>3.0.")

# Artifact check
if artifact_gap > 0.2:
    conclusion_parts.append(
        f"Daily-monthly gap: {artifact_gap:.3f} — significant rebalancing artifact confirmed "
        f"(same pattern as K560/K563 sector rotation)."
    )
elif artifact_gap > 0.05:
    conclusion_parts.append(f"Moderate daily-monthly gap: {artifact_gap:.3f}.")
else:
    conclusion_parts.append(f"Small daily-monthly gap: {artifact_gap:.3f} — no rebalancing artifact.")

# OOS
if oos_consistent:
    conclusion_parts.append("Best strategy is OOS-consistent across all 3 periods.")
else:
    conclusion_parts.append("NOT OOS-consistent across all periods.")

conclusion = ' '.join(conclusion_parts)

print(f"\n{'=' * 70}")
print(f"CONCLUSION: {conclusion}")
print(f"{'=' * 70}")

# Compile full results JSON
results = {
    'experiment_id': 'K566',
    'title': 'Fama-French Factor Timing with VT — Can Factor Momentum Improve Equity Selection?',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance',
    'assets': ['SPY', 'VLUE', 'MTUM', 'QUAL', 'IWM', 'USMV', 'GLD', '^VIX'],
    'period': f"{df_analysis.index[0].strftime('%Y-%m-%d')} to {df_analysis.index[-1].strftime('%Y-%m-%d')}",
    'n_days': len(df_analysis),
    'methodology': {
        'vt_formula': '12/VIX clipped [0,1]',
        'portfolio_structure': '50% equity (VT-scaled) + 50% GLD',
        'factor_etfs': factor_etfs,
        'rebalancing': 'monthly (last trading day of month)',
        'selection_signals': [
            'momentum_60d (top-1 and top-2)',
            'momentum_20d (sensitivity)',
            'static_low_vol (USMV)',
            'static_quality (QUAL)',
            'equal_weight_5_factors',
        ],
        'cross_oos_periods': 3,
        'harvey_threshold': 3.0,
        'transaction_cost': '5 bps one-way per trade',
    },
    'prior_knowledge': {
        'K560': 'Sector rotation + VT: Daily Sharpe 2.16, monthly 1.23 < benchmark 1.34 (artifact)',
        'K562': 'Deep validation confirmed monthly sector momentum FAILS',
        'K563': 'Weekly sector momentum Harvey t=2.73 FAIL — alpha decays with frequency',
        'K226': 'Factor exposure analysis',
        'N79': '12/VIX is the best lazy VT (Sharpe ~0.7)',
    },
    'references': [
        'Moreira & Muir (2017): Volatility-Managed Portfolios, JF',
        'Asness, Moskowitz, Pedersen (2013): Value and Momentum Everywhere, JF',
        'Arnott, Harvey, Kalesnik, Linnainmaa (2021): Reports of Values Death May Be Greatly Exaggerated, FAJ',
        'Harvey, Liu, Zhu (2016): ...and the Cross-Section of Expected Returns, RFS',
        'Fama & French (2015): A five-factor model, JFE',
        'Gupta & Kelly (2019): Factor Momentum Everywhere, JFE',
    ],
    'descriptive_statistics': desc_stats,
    'full_sample_results': full_results,
    'net_of_costs_results': net_results,
    'factor_selection_frequency': {
        'mom_top1_60d': {k: round(float(v), 4) for k, v in sel_freq_60d.items()},
        'mom_top1_20d': {k: round(float(v), 4) for k, v in sel_freq_20d.items()},
    },
    'turnover': {
        'mom_top1_60d_monthly': round(float(turnover_60d), 4),
        'mom_top1_20d_monthly': round(float(turnover_20d), 4),
        'mom_top2_60d_monthly': round(float(turnover_top2), 4),
    },
    'daily_vs_monthly_comparison': {
        'daily_mom_sharpe': round(float(daily_mom_sharpe), 4),
        'monthly_mom_sharpe': round(float(monthly_mom_sharpe), 4),
        'benchmark_sharpe': round(float(benchmark_sharpe_val), 4),
        'artifact_gap': round(float(artifact_gap), 4),
        'artifact_detected': artifact_gap > 0.2,
    },
    'cross_oos_results': cross_oos_results,
    'oos_sharpe_summary': {k: [round(float(s), 4) if not np.isnan(s) else None for s in v]
                           for k, v in oos_sharpe_summary.items()},
    'dm_tests': dm_results,
    'sub_period_results': sub_period_results,
    'conclusion': conclusion,
    'harvey_pass': any_harvey_pass,
    'oos_consistent': oos_consistent,
    'limitations': [
        'Factor ETFs only available since ~2013, so sample is ~11 years (vs 20+ years for sector ETFs)',
        'Factor ETFs have tracking error vs theoretical Fama-French factors',
        'VLUE/MTUM/QUAL are MSCI factor indices which may differ from academic factor definitions',
        'IWM (Russell 2000) is a size proxy but includes both value and growth small caps',
        'Results may not generalize to other markets or factor definitions',
        'Monthly rebalancing tested per K560/K563 artifact lesson — daily results not trustworthy',
    ],
    'runtime_seconds': round(elapsed, 1),
}

# Save results
output_path = 'experiments/k566_factor_timing_vt_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print(f"Runtime: {elapsed:.1f} seconds")
