#!/usr/bin/env python3
"""
K562: K560 Sector Momentum VT — Deep Validation for Listing
=============================================================
Motivation:
K560 found Sector Momentum Top-1 + VT achieves Sharpe 2.157, DM t=10.36, 3/3 OOS.
This is potentially the strongest strategy candidate. But critical caveats need
validation before listing:
  1. High daily turnover (14.4%) — is it practical at lower rebalancing frequencies?
  2. Only 3 OOS periods — need 5+ for robust validation
  3. Momentum window sensitivity — is 60d special or is there a wide safe zone?
  4. Transaction cost sensitivity — at what TX cost does it break even?

Strategy: Each day, select the sector ETF with the best 60-day momentum.
Apply 12/VIX weight to that sector. Other 50% in GLD.

8-point validation checklist:
1. Harvey t>3.0 with Newey-West HAC on daily returns
2. Cross-OOS: 5+ periods (two split schemes)
3. Rebalancing Frequency Sensitivity (daily/weekly/monthly)
4. Momentum Window Sensitivity (20/40/60/90/120/252d)
5. Transaction Costs (0/5/10/20/50 bps)
6. Number of Sectors (Top-1/2/3)
7. Bootstrap (5000 reps, 95% CI, P(win))
8. Drawdown Analysis (GFC, COVID, 2022)

Prior knowledge:
- K560: Sector Rotation VT — Momentum Top-1 Sharpe 2.157, DM t=10.36, 3/3 OOS
- K58: Sector VT Map — all sectors benefit from VT uniformly
- K243: Sector Rotation — Harvey PASS (t=3.99) but DM NS, MDD -37%
- N79/N80/N81: 12/VIX Sharpe ~0.6-0.7, robust across thresholds 6-18

Literature:
- Moreira & Muir (2017): Volatility-Managed Portfolios, JF
- Moskowitz, Ooi, Pedersen (2012): Time Series Momentum, JFE
- Asness, Moskowitz, Pedersen (2013): Value and Momentum Everywhere, JF
- Harvey, Liu, Zhu (2016): ...and the Cross-Section of Expected Returns, RFS
- Jegadeesh & Titman (1993): Returns to Buying Winners, JF

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

print("=" * 80)
print("K562: K560 Sector Momentum VT — Deep Validation for Listing")
print("8-Point Validation Checklist")
print("=" * 80)

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

all_tickers = list(tickers.keys()) + ['^VIX']
raw = yf.download(all_tickers, start="2004-01-01", end="2026-12-31", progress=False)

if isinstance(raw.columns, pd.MultiIndex):
    close = raw['Close']
else:
    close = raw[['Close']]

vix = close['^VIX'].dropna()
vix.name = 'VIX'

returns = close[list(tickers.keys())].pct_change().dropna()

df = returns.join(vix, how='inner').dropna()
df = df.loc['2005-01-01':]

print(f"  Data: {len(df)} trading days ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
print(f"  VIX range: {df['VIX'].min():.1f} - {df['VIX'].max():.1f}, median {df['VIX'].median():.1f}")

# =================================================================
# HELPER FUNCTIONS
# =================================================================

def compute_metrics(returns_arr, ann_factor=252):
    """Compute standard performance metrics from daily returns."""
    ret = pd.Series(returns_arr).dropna()
    n = len(ret)
    if n < 100:
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
    downside = ret[ret < 0]
    downside_vol = downside.std() * np.sqrt(ann_factor) if len(downside) > 0 else 1e-8
    sortino = ann_ret / downside_vol
    return {
        'n_days': n, 'ann_return': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4), 'sharpe': round(float(sharpe), 4),
        'mdd': round(float(mdd), 4), 'cagr': round(float(cagr), 4),
        'calmar': round(float(calmar), 4), 'sortino': round(float(sortino), 4),
    }


def newey_west_t_stat(diff_returns, max_lags=None):
    """
    T-test with Newey-West HAC standard errors.
    H0: mean(diff) = 0.
    Returns t-stat and p-value.
    """
    d = np.array(diff_returns, dtype=float)
    n = len(d)
    d_mean = np.mean(d)

    if max_lags is None:
        max_lags = int(np.floor(4 * (n / 100) ** (2/9)))

    # Newey-West variance estimator
    gamma_0 = np.mean((d - d_mean) ** 2)
    nw_var = gamma_0
    for lag in range(1, max_lags + 1):
        w = 1 - lag / (max_lags + 1)  # Bartlett kernel
        gamma_j = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        nw_var += 2 * w * gamma_j

    se = np.sqrt(nw_var / n)
    if se < 1e-12:
        return 0.0, 1.0

    t_stat = d_mean / se
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_value)


def compute_strategy_returns(df_in, sector_tickers, mom_window=60, top_n=1,
                              rebal_freq='daily'):
    """
    Compute sector momentum VT + GLD strategy returns.

    Parameters:
    - mom_window: lookback for momentum signal
    - top_n: number of top sectors to hold
    - rebal_freq: 'daily', 'weekly', 'monthly'

    Returns: (strategy_rets, benchmark_rets, turnover, selections)
    """
    df_work = df_in.copy()

    # Compute momentum signals
    for t in sector_tickers:
        df_work[f'mom_{t}'] = df_work[t].rolling(mom_window).sum()

    df_work = df_work.dropna(subset=[f'mom_{sector_tickers[0]}'])

    n_days = len(df_work)
    vt_weights = np.clip(12.0 / df_work['VIX'].values, 0, 1)
    gld_rets = df_work['GLD'].values
    spy_rets = df_work['SPY'].values

    # Pre-compute sector return and momentum arrays
    sec_ret_arr = {t: df_work[t].values for t in sector_tickers}
    sec_mom_arr = {t: df_work[f'mom_{t}'].values for t in sector_tickers}

    # Determine rebalancing days
    dates = df_work.index
    if rebal_freq == 'daily':
        rebal_days = set(range(n_days))
    elif rebal_freq == 'weekly':
        # Rebalance on Mondays (weekday=0)
        rebal_days = set()
        for i, d in enumerate(dates):
            if d.weekday() == 0:  # Monday
                rebal_days.add(i)
        # Ensure day 0 is a rebal day
        rebal_days.add(0)
    elif rebal_freq == 'monthly':
        # Rebalance on first trading day of each month
        rebal_days = set()
        current_month = None
        for i, d in enumerate(dates):
            ym = (d.year, d.month)
            if ym != current_month:
                rebal_days.add(i)
                current_month = ym
    else:
        rebal_days = set(range(n_days))

    strat_rets = np.full(n_days, np.nan)
    bench_rets = np.full(n_days, np.nan)
    selections = [None]
    current_selection = None

    for i in range(1, n_days):
        prev = i - 1
        vt_w = vt_weights[prev]
        gld_r = gld_rets[i]
        spy_r = spy_rets[i]

        # Benchmark: 50% SPY VT + 50% GLD
        bench_rets[i] = 0.5 * vt_w * spy_r + 0.5 * gld_r

        # Update selection on rebal days
        if i in rebal_days or current_selection is None:
            moms = {t: sec_mom_arr[t][prev] for t in sector_tickers}
            sorted_sectors = sorted(sector_tickers, key=lambda t: moms[t], reverse=True)
            current_selection = sorted_sectors[:top_n]

        selections.append(tuple(current_selection))

        # Strategy return
        avg_sec_ret = np.mean([sec_ret_arr[t][i] for t in current_selection])
        strat_rets[i] = 0.5 * vt_w * avg_sec_ret + 0.5 * gld_r

    # Compute turnover
    valid_selections = [s for s in selections if s is not None]
    changes = sum(1 for i in range(1, len(valid_selections)) if valid_selections[i] != valid_selections[i-1])
    turnover = changes / (len(valid_selections) - 1) if len(valid_selections) > 1 else 0

    return strat_rets, bench_rets, turnover, selections, df_work.index


# =================================================================
# 2. BASELINE REPLICATION (confirm K560 numbers)
# =================================================================
print("\n[2] Baseline replication (confirm K560 numbers)...")

strat_daily, bench_daily, turnover_daily, sel_daily, idx_daily = \
    compute_strategy_returns(df, sector_tickers, mom_window=60, top_n=1, rebal_freq='daily')

m_strat = compute_metrics(strat_daily)
m_bench = compute_metrics(bench_daily)

print(f"  Momentum Top-1 (daily): Sharpe={m_strat['sharpe']:.3f}, CAGR={m_strat['cagr']:.1%}, MDD={m_strat['mdd']:.1%}")
print(f"  SPY VT + GLD benchmark: Sharpe={m_bench['sharpe']:.3f}, CAGR={m_bench['cagr']:.1%}, MDD={m_bench['mdd']:.1%}")
print(f"  Daily turnover: {turnover_daily:.1%}")

# =================================================================
# VALIDATION 1: Harvey t>3.0 with Newey-West HAC
# =================================================================
print("\n" + "=" * 80)
print("VALIDATION 1: Harvey (2016) t>3.0 with Newey-West HAC")
print("=" * 80)

diff_daily = strat_daily - bench_daily
nw_t, nw_p = newey_west_t_stat(diff_daily)
simple_t, simple_p = stats.ttest_1samp(diff_daily, 0)

print(f"  Newey-West HAC t-stat:  {nw_t:.3f}  (p={nw_p:.6f})")
print(f"  Simple t-stat:          {simple_t:.3f}  (p={simple_p:.6f})")
print(f"  Harvey threshold: |t| > 3.0")
print(f"  RESULT: {'PASS' if abs(nw_t) > 3.0 else 'FAIL'} (NW t={nw_t:.3f})")

# Also test with different lag structures
print("\n  Sensitivity to NW lag truncation:")
for nlags in [1, 5, 10, 20, 50]:
    t_val, p_val = newey_west_t_stat(diff_daily, max_lags=nlags)
    print(f"    Lags={nlags:>2}: t={t_val:.3f}, p={p_val:.6f}  {'PASS' if abs(t_val) > 3.0 else 'FAIL'}")

harvey_results = {
    'nw_t_stat': round(nw_t, 3),
    'nw_p_value': round(nw_p, 6),
    'simple_t_stat': round(float(simple_t), 3),
    'simple_p_value': round(float(simple_p), 6),
    'harvey_pass': abs(nw_t) > 3.0,
    'lag_sensitivity': {}
}
for nlags in [1, 5, 10, 20, 50]:
    t_val, _ = newey_west_t_stat(diff_daily, max_lags=nlags)
    harvey_results['lag_sensitivity'][f'lags_{nlags}'] = round(t_val, 3)


# =================================================================
# VALIDATION 2: Cross-OOS (5+ periods, two split schemes)
# =================================================================
print("\n" + "=" * 80)
print("VALIDATION 2: Cross-OOS Validation (5+ periods, two schemes)")
print("=" * 80)

# Scheme A: 4-year OOS blocks
scheme_a = [
    ('Scheme A1', '2005-04-01', '2009-12-31', '2006-01-01', '2009-12-31'),
    ('Scheme A2', '2005-04-01', '2013-12-31', '2010-01-01', '2013-12-31'),
    ('Scheme A3', '2005-04-01', '2017-12-31', '2014-01-01', '2017-12-31'),
    ('Scheme A4', '2005-04-01', '2021-12-31', '2018-01-01', '2021-12-31'),
    ('Scheme A5', '2005-04-01', '2025-12-31', '2022-01-01', '2026-12-31'),
]

# Scheme B: Alternative splits (staggered 4-year windows)
scheme_b = [
    ('Scheme B1', '2004-01-01', '2011-12-31', '2008-01-01', '2011-12-31'),
    ('Scheme B2', '2004-01-01', '2015-12-31', '2012-01-01', '2015-12-31'),
    ('Scheme B3', '2004-01-01', '2019-12-31', '2016-01-01', '2019-12-31'),
    ('Scheme B4', '2004-01-01', '2023-12-31', '2020-01-01', '2023-12-31'),
    ('Scheme B5', '2004-01-01', '2026-12-31', '2024-01-01', '2026-12-31'),
]

cross_oos_results = {}

for scheme_name, periods in [('Scheme_A', scheme_a), ('Scheme_B', scheme_b)]:
    print(f"\n  --- {scheme_name} ---")
    scheme_results = []
    strat_wins = 0
    total = 0

    for label, is_start, is_end, oos_start, oos_end in periods:
        # Filter to OOS period
        oos_mask = (df.index >= oos_start) & (df.index <= oos_end)
        df_oos = df.loc[oos_mask]

        if len(df_oos) < 100:
            print(f"    {label}: OOS too short ({len(df_oos)} days), skipping")
            continue

        # Run strategy on OOS data
        s_rets, b_rets, _, _, _ = compute_strategy_returns(
            df_oos, sector_tickers, mom_window=60, top_n=1, rebal_freq='daily'
        )

        m_s = compute_metrics(s_rets)
        m_b = compute_metrics(b_rets)

        if m_s is None or m_b is None:
            print(f"    {label}: Insufficient data, skipping")
            continue

        total += 1
        if m_s['sharpe'] > m_b['sharpe']:
            strat_wins += 1

        nw_t_oos, nw_p_oos = newey_west_t_stat(s_rets - b_rets)

        print(f"    {label} ({oos_start} to {oos_end}): "
              f"Strat Sharpe={m_s['sharpe']:.3f}, Bench Sharpe={m_b['sharpe']:.3f}, "
              f"NW t={nw_t_oos:.2f}  {'WIN' if m_s['sharpe'] > m_b['sharpe'] else 'LOSE'}")

        scheme_results.append({
            'label': label,
            'oos_period': f"{oos_start} to {oos_end}",
            'oos_days': int(m_s['n_days']),
            'strat_sharpe': m_s['sharpe'],
            'bench_sharpe': m_b['sharpe'],
            'strat_cagr': m_s['cagr'],
            'strat_mdd': m_s['mdd'],
            'nw_t_stat': round(nw_t_oos, 3),
            'nw_p_value': round(nw_p_oos, 4),
            'win': m_s['sharpe'] > m_b['sharpe'],
        })

    win_rate = strat_wins / total if total > 0 else 0
    print(f"  {scheme_name} summary: {strat_wins}/{total} OOS wins ({win_rate:.0%})")
    cross_oos_results[scheme_name] = {
        'periods': scheme_results,
        'wins': strat_wins,
        'total': total,
        'win_rate': round(win_rate, 2),
    }


# =================================================================
# VALIDATION 3: Rebalancing Frequency Sensitivity
# =================================================================
print("\n" + "=" * 80)
print("VALIDATION 3: Rebalancing Frequency Sensitivity")
print("=" * 80)

rebal_results = {}
print(f"\n  {'Frequency':<12} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'Turnover':>10} {'NW t':>8}")
print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*8}")

for freq in ['daily', 'weekly', 'monthly']:
    s_rets, b_rets, to, _, _ = compute_strategy_returns(
        df, sector_tickers, mom_window=60, top_n=1, rebal_freq=freq
    )
    m_s = compute_metrics(s_rets)
    m_b = compute_metrics(b_rets)
    nw_t_val, nw_p_val = newey_west_t_stat(s_rets - b_rets)

    if m_s:
        print(f"  {freq:<12} {m_s['sharpe']:>8.3f} {m_s['cagr']:>7.1%} {m_s['mdd']:>7.1%} "
              f"{to:>9.1%} {nw_t_val:>8.3f}")

        rebal_results[freq] = {
            'metrics': m_s,
            'benchmark_sharpe': m_b['sharpe'] if m_b else None,
            'turnover': round(to, 4),
            'nw_t_stat': round(nw_t_val, 3),
            'nw_p_value': round(nw_p_val, 6),
            'harvey_pass': abs(nw_t_val) > 3.0,
        }

# Also test bi-weekly
# Approximate bi-weekly by rebalancing every other Monday
s_rets_bw, b_rets_bw, _, sel_bw, idx_bw = compute_strategy_returns(
    df, sector_tickers, mom_window=60, top_n=1, rebal_freq='daily'
)
# Manual bi-weekly: keep selections from weekly, but only update every 2nd Monday
df_bw = df.copy()
for t in sector_tickers:
    df_bw[f'mom_{t}'] = df_bw[t].rolling(60).sum()
df_bw = df_bw.dropna(subset=[f'mom_{sector_tickers[0]}'])

n_bw = len(df_bw)
vt_w_bw = np.clip(12.0 / df_bw['VIX'].values, 0, 1)
gld_bw = df_bw['GLD'].values
spy_bw = df_bw['SPY'].values
sec_ret_bw = {t: df_bw[t].values for t in sector_tickers}
sec_mom_bw = {t: df_bw[f'mom_{t}'].values for t in sector_tickers}

bw_strat = np.full(n_bw, np.nan)
bw_bench = np.full(n_bw, np.nan)
bw_selection = None
monday_count = 0
bw_changes = 0

for i in range(1, n_bw):
    prev = i - 1
    d = df_bw.index[i]
    if d.weekday() == 0:
        monday_count += 1

    if (d.weekday() == 0 and monday_count % 2 == 1) or bw_selection is None:
        moms = {t: sec_mom_bw[t][prev] for t in sector_tickers}
        new_sel = max(sector_tickers, key=lambda t: moms[t])
        if bw_selection is not None and new_sel != bw_selection:
            bw_changes += 1
        bw_selection = new_sel

    bw_strat[i] = 0.5 * vt_w_bw[prev] * sec_ret_bw[bw_selection][i] + 0.5 * gld_bw[i]
    bw_bench[i] = 0.5 * vt_w_bw[prev] * spy_bw[i] + 0.5 * gld_bw[i]

bw_turnover = bw_changes / (n_bw - 1)
m_bw = compute_metrics(bw_strat)
nw_t_bw, nw_p_bw = newey_west_t_stat(bw_strat - bw_bench)

if m_bw:
    print(f"  {'bi-weekly':<12} {m_bw['sharpe']:>8.3f} {m_bw['cagr']:>7.1%} {m_bw['mdd']:>7.1%} "
          f"{bw_turnover:>9.1%} {nw_t_bw:>8.3f}")
    rebal_results['bi-weekly'] = {
        'metrics': m_bw,
        'turnover': round(bw_turnover, 4),
        'nw_t_stat': round(nw_t_bw, 3),
        'harvey_pass': abs(nw_t_bw) > 3.0,
    }

# Key question: does monthly still beat benchmark?
monthly_sharpe = rebal_results.get('monthly', {}).get('metrics', {}).get('sharpe', 0)
bench_sharpe = rebal_results.get('monthly', {}).get('benchmark_sharpe', 0)
print(f"\n  KEY FINDING: Monthly rebalancing Sharpe = {monthly_sharpe:.3f} vs benchmark {bench_sharpe:.3f}")
print(f"  {'DEPLOYABLE at monthly frequency' if monthly_sharpe > bench_sharpe else 'NOT deployable at monthly frequency'}")


# =================================================================
# VALIDATION 4: Momentum Window Sensitivity
# =================================================================
print("\n" + "=" * 80)
print("VALIDATION 4: Momentum Window Sensitivity")
print("=" * 80)

window_results = {}
print(f"\n  {'Window':>8} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'NW t':>8} {'Harvey':>8}")
print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

for window in [20, 40, 60, 90, 120, 252]:
    s_rets, b_rets, to, _, _ = compute_strategy_returns(
        df, sector_tickers, mom_window=window, top_n=1, rebal_freq='daily'
    )
    m_s = compute_metrics(s_rets)
    m_b = compute_metrics(b_rets)
    nw_t_val, nw_p_val = newey_west_t_stat(s_rets - b_rets)

    if m_s:
        result = 'PASS' if abs(nw_t_val) > 3.0 else 'FAIL'
        print(f"  {window:>5}d {m_s['sharpe']:>8.3f} {m_s['cagr']:>7.1%} {m_s['mdd']:>7.1%} "
              f"{nw_t_val:>8.3f} {result:>8}")
        window_results[f'{window}d'] = {
            'metrics': m_s,
            'turnover': round(to, 4),
            'nw_t_stat': round(nw_t_val, 3),
            'harvey_pass': abs(nw_t_val) > 3.0,
        }

# Find the "safe zone"
safe_windows = [w for w, r in window_results.items() if r['harvey_pass']]
print(f"\n  Safe zone (Harvey PASS): {', '.join(safe_windows)}")
best_window = max(window_results.items(), key=lambda x: x[1]['metrics']['sharpe'])
print(f"  Best window: {best_window[0]} (Sharpe={best_window[1]['metrics']['sharpe']:.3f})")


# =================================================================
# VALIDATION 5: Transaction Cost Sensitivity
# =================================================================
print("\n" + "=" * 80)
print("VALIDATION 5: Transaction Cost Sensitivity")
print("=" * 80)

# First compute with daily rebalancing (worst case)
s_rets_base, b_rets_base, turnover_base, sel_base, _ = compute_strategy_returns(
    df, sector_tickers, mom_window=60, top_n=1, rebal_freq='daily'
)

tx_results = {}
print(f"\n  Daily rebalancing (turnover={turnover_base:.1%}):")
print(f"  {'TX (bps)':>10} {'Gross Sh':>9} {'Net Sh':>8} {'Net CAGR':>9} {'Ann Drag':>10} {'Harvey':>8}")
print(f"  {'-'*10} {'-'*9} {'-'*8} {'-'*9} {'-'*10} {'-'*8}")

gross_m = compute_metrics(s_rets_base)

for tx_bps in [0, 5, 10, 20, 50]:
    # Daily drag = turnover * 2 (buy+sell) * tx_cost * 0.5 (equity portion)
    daily_drag = turnover_base * 2 * (tx_bps / 10000) * 0.5
    annual_drag = daily_drag * 252
    net_rets = s_rets_base - daily_drag
    m_net = compute_metrics(net_rets)
    nw_t_net, _ = newey_west_t_stat(net_rets - b_rets_base)

    if m_net:
        result = 'PASS' if abs(nw_t_net) > 3.0 else 'FAIL'
        print(f"  {tx_bps:>7} bp {gross_m['sharpe']:>9.3f} {m_net['sharpe']:>8.3f} "
              f"{m_net['cagr']:>8.1%} {annual_drag:>9.2%} {result:>8}")
        tx_results[f'{tx_bps}bp_daily'] = {
            'metrics': m_net,
            'annual_drag': round(annual_drag, 4),
            'nw_t_stat': round(nw_t_net, 3),
            'harvey_pass': abs(nw_t_net) > 3.0,
        }

# Now with monthly rebalancing (practical case)
s_rets_m, b_rets_m, turnover_m, sel_m, _ = compute_strategy_returns(
    df, sector_tickers, mom_window=60, top_n=1, rebal_freq='monthly'
)

print(f"\n  Monthly rebalancing (turnover={turnover_m:.1%}):")
print(f"  {'TX (bps)':>10} {'Gross Sh':>9} {'Net Sh':>8} {'Net CAGR':>9} {'Ann Drag':>10} {'Harvey':>8}")
print(f"  {'-'*10} {'-'*9} {'-'*8} {'-'*9} {'-'*10} {'-'*8}")

gross_m_monthly = compute_metrics(s_rets_m)

for tx_bps in [0, 5, 10, 20, 50]:
    daily_drag = turnover_m * 2 * (tx_bps / 10000) * 0.5
    annual_drag = daily_drag * 252
    net_rets = s_rets_m - daily_drag
    m_net = compute_metrics(net_rets)
    nw_t_net, _ = newey_west_t_stat(net_rets - b_rets_m)

    if m_net:
        result = 'PASS' if abs(nw_t_net) > 3.0 else 'FAIL'
        print(f"  {tx_bps:>7} bp {gross_m_monthly['sharpe']:>9.3f} {m_net['sharpe']:>8.3f} "
              f"{m_net['cagr']:>8.1%} {annual_drag:>9.2%} {result:>8}")
        tx_results[f'{tx_bps}bp_monthly'] = {
            'metrics': m_net,
            'annual_drag': round(annual_drag, 4),
            'nw_t_stat': round(nw_t_net, 3),
            'harvey_pass': abs(nw_t_net) > 3.0,
        }

# Breakeven TX cost (where net Sharpe = benchmark Sharpe)
bench_sharpe_full = compute_metrics(b_rets_base)['sharpe']
print(f"\n  Benchmark Sharpe: {bench_sharpe_full:.3f}")
for freq_label, s_r, b_r, to in [
    ('daily', s_rets_base, b_rets_base, turnover_base),
    ('monthly', s_rets_m, b_rets_m, turnover_m)
]:
    # Binary search for breakeven
    lo, hi = 0, 500
    for _ in range(50):
        mid = (lo + hi) / 2
        drag = to * 2 * (mid / 10000) * 0.5
        net = s_r - drag
        m_n = compute_metrics(net)
        if m_n and m_n['sharpe'] > bench_sharpe_full:
            lo = mid
        else:
            hi = mid
    breakeven_bps = (lo + hi) / 2
    print(f"  Breakeven TX cost ({freq_label} rebal): ~{breakeven_bps:.0f} bps")
    tx_results[f'breakeven_{freq_label}'] = round(breakeven_bps, 1)


# =================================================================
# VALIDATION 6: Number of Sectors (Top-1 vs Top-2 vs Top-3)
# =================================================================
print("\n" + "=" * 80)
print("VALIDATION 6: Number of Sectors (Concentration)")
print("=" * 80)

topn_results = {}
print(f"\n  {'Top-N':>6} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'Turnover':>10} {'NW t':>8}")
print(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*8}")

for top_n in [1, 2, 3, 4, 5]:
    s_rets, b_rets, to, _, _ = compute_strategy_returns(
        df, sector_tickers, mom_window=60, top_n=top_n, rebal_freq='daily'
    )
    m_s = compute_metrics(s_rets)
    nw_t_val, _ = newey_west_t_stat(s_rets - b_rets)

    if m_s:
        print(f"  Top-{top_n:<3} {m_s['sharpe']:>8.3f} {m_s['cagr']:>7.1%} {m_s['mdd']:>7.1%} "
              f"{to:>9.1%} {nw_t_val:>8.3f}")
        topn_results[f'top_{top_n}'] = {
            'metrics': m_s,
            'turnover': round(to, 4),
            'nw_t_stat': round(nw_t_val, 3),
            'harvey_pass': abs(nw_t_val) > 3.0,
        }

# Also test with monthly rebalancing
print(f"\n  Monthly rebalancing:")
print(f"  {'Top-N':>6} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'NW t':>8}")
print(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

for top_n in [1, 2, 3]:
    s_rets, b_rets, to, _, _ = compute_strategy_returns(
        df, sector_tickers, mom_window=60, top_n=top_n, rebal_freq='monthly'
    )
    m_s = compute_metrics(s_rets)
    nw_t_val, _ = newey_west_t_stat(s_rets - b_rets)

    if m_s:
        print(f"  Top-{top_n:<3} {m_s['sharpe']:>8.3f} {m_s['cagr']:>7.1%} {m_s['mdd']:>7.1%} "
              f"{nw_t_val:>8.3f}")
        topn_results[f'top_{top_n}_monthly'] = {
            'metrics': m_s,
            'nw_t_stat': round(nw_t_val, 3),
            'harvey_pass': abs(nw_t_val) > 3.0,
        }


# =================================================================
# VALIDATION 7: Bootstrap (5000 reps)
# =================================================================
print("\n" + "=" * 80)
print("VALIDATION 7: Bootstrap Analysis (5000 reps)")
print("=" * 80)

np.random.seed(42)
n_bootstrap = 5000

# Bootstrap for daily rebalancing
diff_daily_full = strat_daily - bench_daily
n_obs = len(diff_daily_full)

boot_sharpes_strat = np.zeros(n_bootstrap)
boot_sharpes_bench = np.zeros(n_bootstrap)
boot_sharpe_diffs = np.zeros(n_bootstrap)

print("  Running bootstrap...")
for b in range(n_bootstrap):
    idx = np.random.choice(n_obs, size=n_obs, replace=True)
    s_boot = strat_daily[idx]
    b_boot = bench_daily[idx]

    s_sharpe = s_boot.mean() / s_boot.std() * np.sqrt(252) if s_boot.std() > 0 else 0
    b_sharpe = b_boot.mean() / b_boot.std() * np.sqrt(252) if b_boot.std() > 0 else 0

    boot_sharpes_strat[b] = s_sharpe
    boot_sharpes_bench[b] = b_sharpe
    boot_sharpe_diffs[b] = s_sharpe - b_sharpe

# 95% CI
ci_low_diff = np.percentile(boot_sharpe_diffs, 2.5)
ci_high_diff = np.percentile(boot_sharpe_diffs, 97.5)
p_win = np.mean(boot_sharpe_diffs > 0)

ci_low_strat = np.percentile(boot_sharpes_strat, 2.5)
ci_high_strat = np.percentile(boot_sharpes_strat, 97.5)

print(f"\n  Strategy Sharpe: {np.mean(boot_sharpes_strat):.3f} "
      f"[95% CI: {ci_low_strat:.3f} to {ci_high_strat:.3f}]")
print(f"  Sharpe difference (strat - bench): {np.mean(boot_sharpe_diffs):.3f} "
      f"[95% CI: {ci_low_diff:.3f} to {ci_high_diff:.3f}]")
print(f"  P(strategy wins): {p_win:.1%}")
print(f"  RESULT: {'CI excludes zero — significant' if ci_low_diff > 0 else 'CI includes zero — NOT significant'}")

# Also bootstrap for monthly rebalancing
s_rets_month, b_rets_month, _, _, _ = compute_strategy_returns(
    df, sector_tickers, mom_window=60, top_n=1, rebal_freq='monthly'
)

n_obs_m = len(s_rets_month)
boot_diffs_monthly = np.zeros(n_bootstrap)

for b in range(n_bootstrap):
    idx = np.random.choice(n_obs_m, size=n_obs_m, replace=True)
    s_boot = s_rets_month[idx]
    b_boot = b_rets_month[idx]
    s_sh = s_boot.mean() / s_boot.std() * np.sqrt(252) if s_boot.std() > 0 else 0
    b_sh = b_boot.mean() / b_boot.std() * np.sqrt(252) if b_boot.std() > 0 else 0
    boot_diffs_monthly[b] = s_sh - b_sh

ci_low_m = np.percentile(boot_diffs_monthly, 2.5)
ci_high_m = np.percentile(boot_diffs_monthly, 97.5)
p_win_m = np.mean(boot_diffs_monthly > 0)

print(f"\n  Monthly rebalancing bootstrap:")
print(f"  Sharpe difference: {np.mean(boot_diffs_monthly):.3f} "
      f"[95% CI: {ci_low_m:.3f} to {ci_high_m:.3f}]")
print(f"  P(strategy wins): {p_win_m:.1%}")

bootstrap_results = {
    'n_reps': n_bootstrap,
    'daily': {
        'mean_sharpe': round(float(np.mean(boot_sharpes_strat)), 3),
        'ci_95_sharpe': [round(float(ci_low_strat), 3), round(float(ci_high_strat), 3)],
        'mean_sharpe_diff': round(float(np.mean(boot_sharpe_diffs)), 3),
        'ci_95_diff': [round(float(ci_low_diff), 3), round(float(ci_high_diff), 3)],
        'p_win': round(float(p_win), 4),
        'significant': bool(ci_low_diff > 0),
    },
    'monthly': {
        'mean_sharpe_diff': round(float(np.mean(boot_diffs_monthly)), 3),
        'ci_95_diff': [round(float(ci_low_m), 3), round(float(ci_high_m), 3)],
        'p_win': round(float(p_win_m), 4),
        'significant': bool(ci_low_m > 0),
    }
}


# =================================================================
# VALIDATION 8: Drawdown Analysis (GFC, COVID, 2022)
# =================================================================
print("\n" + "=" * 80)
print("VALIDATION 8: Drawdown Analysis (Crisis Episodes)")
print("=" * 80)

# Episodes
episodes = [
    ('GFC Peak-Trough', '2007-10-01', '2009-03-31'),
    ('GFC Full', '2007-10-01', '2009-12-31'),
    ('2011 Euro Crisis', '2011-05-01', '2011-10-31'),
    ('2015 China Fear', '2015-08-01', '2015-10-31'),
    ('2018 Vol Shock', '2018-01-26', '2018-12-31'),
    ('COVID Crash', '2020-02-19', '2020-03-23'),
    ('COVID Full', '2020-02-19', '2020-06-30'),
    ('2022 Bear Market', '2022-01-01', '2022-10-31'),
    ('2022 Full Year', '2022-01-01', '2022-12-31'),
]

drawdown_results = {}

# Compute cumulative returns for the full period
strat_cum_daily = pd.Series((1 + strat_daily).cumprod(), index=idx_daily)
bench_cum_daily = pd.Series((1 + bench_daily).cumprod(), index=idx_daily)

# Also compute for monthly
s_rets_monthly_full, b_rets_monthly_full, _, _, idx_monthly = compute_strategy_returns(
    df, sector_tickers, mom_window=60, top_n=1, rebal_freq='monthly'
)
strat_cum_monthly = pd.Series((1 + s_rets_monthly_full).cumprod(), index=idx_monthly)
bench_cum_monthly = pd.Series((1 + b_rets_monthly_full).cumprod(), index=idx_monthly)

print(f"\n  {'Episode':<25} {'Strat(D)':>9} {'Bench(D)':>9} {'Strat(M)':>9} {'Bench(M)':>9}")
print(f"  {'-'*25} {'-'*9} {'-'*9} {'-'*9} {'-'*9}")

for ep_name, ep_start, ep_end in episodes:
    mask_d = (strat_cum_daily.index >= ep_start) & (strat_cum_daily.index <= ep_end)
    mask_m = (strat_cum_monthly.index >= ep_start) & (strat_cum_monthly.index <= ep_end)

    if mask_d.sum() < 5:
        continue

    # Daily rebal drawdown during episode
    s_ep_d = strat_cum_daily[mask_d]
    b_ep_d = bench_cum_daily[mask_d]

    s_ret_d = (s_ep_d.iloc[-1] / s_ep_d.iloc[0] - 1)
    b_ret_d = (b_ep_d.iloc[-1] / b_ep_d.iloc[0] - 1)

    # Monthly rebal
    if mask_m.sum() >= 5:
        s_ep_m = strat_cum_monthly[mask_m]
        b_ep_m = bench_cum_monthly[mask_m]
        s_ret_m = (s_ep_m.iloc[-1] / s_ep_m.iloc[0] - 1)
        b_ret_m = (b_ep_m.iloc[-1] / b_ep_m.iloc[0] - 1)
        m_str_s = f"{s_ret_m:>8.1%}"
        m_str_b = f"{b_ret_m:>8.1%}"
    else:
        s_ret_m = None
        b_ret_m = None
        m_str_s = f"{'N/A':>8}"
        m_str_b = f"{'N/A':>8}"

    print(f"  {ep_name:<25} {s_ret_d:>8.1%} {b_ret_d:>8.1%} {m_str_s:>9} {m_str_b:>9}")

    drawdown_results[ep_name] = {
        'daily_strat_return': round(float(s_ret_d), 4),
        'daily_bench_return': round(float(b_ret_d), 4),
        'monthly_strat_return': round(float(s_ret_m), 4) if s_ret_m is not None else None,
        'monthly_bench_return': round(float(b_ret_m), 4) if b_ret_m is not None else None,
    }

# Worst drawdown analysis for each frequency
print("\n  Maximum Drawdown Analysis:")
for freq_name, s_cum in [('Daily', strat_cum_daily), ('Monthly', strat_cum_monthly)]:
    peak = s_cum.cummax()
    dd = (s_cum - peak) / peak
    worst_dd = dd.min()
    worst_dd_date = dd.idxmin()
    # Find peak date before worst drawdown
    peak_date = s_cum[:worst_dd_date].idxmax()
    # Find recovery date
    recovery_mask = s_cum[worst_dd_date:] >= s_cum[peak_date]
    if recovery_mask.any():
        recovery_date = recovery_mask.idxmax()
        recovery_days = len(s_cum[worst_dd_date:recovery_date])
    else:
        recovery_date = 'Not recovered'
        recovery_days = None

    print(f"  {freq_name}: MDD={worst_dd:.1%}, Peak={peak_date.strftime('%Y-%m-%d')}, "
          f"Trough={worst_dd_date.strftime('%Y-%m-%d')}, "
          f"Recovery={'%s (%d days)' % (recovery_date.strftime('%Y-%m-%d'), recovery_days) if recovery_days else recovery_date}")


# =================================================================
# ADDITIONAL: Cross-OOS for Monthly Rebalancing
# =================================================================
print("\n" + "=" * 80)
print("BONUS: Cross-OOS for Monthly Rebalancing (5 periods)")
print("=" * 80)

monthly_oos_results = []
scheme_a_monthly = [
    ('M-OOS1', '2006-01-01', '2009-12-31'),
    ('M-OOS2', '2010-01-01', '2013-12-31'),
    ('M-OOS3', '2014-01-01', '2017-12-31'),
    ('M-OOS4', '2018-01-01', '2021-12-31'),
    ('M-OOS5', '2022-01-01', '2026-12-31'),
]

wins_m = 0
total_m = 0

print(f"  {'Period':<12} {'OOS':>22} {'Strat Sh':>9} {'Bench Sh':>9} {'NW t':>7} {'Result':>8}")
print(f"  {'-'*12} {'-'*22} {'-'*9} {'-'*9} {'-'*7} {'-'*8}")

for label, oos_start, oos_end in scheme_a_monthly:
    oos_mask = (df.index >= oos_start) & (df.index <= oos_end)
    df_oos = df.loc[oos_mask]

    if len(df_oos) < 100:
        continue

    s_rets_oos, b_rets_oos, _, _, _ = compute_strategy_returns(
        df_oos, sector_tickers, mom_window=60, top_n=1, rebal_freq='monthly'
    )

    m_s = compute_metrics(s_rets_oos)
    m_b = compute_metrics(b_rets_oos)

    if m_s is None or m_b is None:
        continue

    total_m += 1
    win = m_s['sharpe'] > m_b['sharpe']
    if win:
        wins_m += 1

    nw_t_val, _ = newey_west_t_stat(s_rets_oos - b_rets_oos)

    print(f"  {label:<12} {oos_start} to {oos_end} {m_s['sharpe']:>9.3f} {m_b['sharpe']:>9.3f} "
          f"{nw_t_val:>7.2f} {'WIN' if win else 'LOSE':>8}")

    monthly_oos_results.append({
        'label': label,
        'oos_period': f"{oos_start} to {oos_end}",
        'strat_sharpe': m_s['sharpe'],
        'bench_sharpe': m_b['sharpe'],
        'nw_t_stat': round(nw_t_val, 3),
        'win': win,
    })

print(f"\n  Monthly OOS: {wins_m}/{total_m} wins ({wins_m/total_m:.0%})" if total_m > 0 else "  No valid periods")


# =================================================================
# FINAL SUMMARY & VERDICT
# =================================================================
print("\n" + "=" * 80)
print("FINAL VALIDATION SUMMARY")
print("=" * 80)

# Collect all validation results
v1_pass = abs(harvey_results['nw_t_stat']) > 3.0
v2_pass_a = cross_oos_results.get('Scheme_A', {}).get('win_rate', 0) >= 0.8
v2_pass_b = cross_oos_results.get('Scheme_B', {}).get('win_rate', 0) >= 0.8
v3_monthly_works = rebal_results.get('monthly', {}).get('metrics', {}).get('sharpe', 0) > \
                    rebal_results.get('monthly', {}).get('benchmark_sharpe', 0)
v3_weekly_works = rebal_results.get('weekly', {}).get('metrics', {}).get('sharpe', 0) > \
                   rebal_results.get('weekly', {}).get('benchmark_sharpe', 0)
v4_wide_zone = len(safe_windows) >= 3
v5_survives_20bp = tx_results.get('20bp_daily', {}).get('harvey_pass', False)
v6_top1_best = topn_results.get('top_1', {}).get('metrics', {}).get('sharpe', 0) >= \
                topn_results.get('top_2', {}).get('metrics', {}).get('sharpe', 0)
v7_bootstrap_sig = bootstrap_results['daily']['significant']
v7_bootstrap_monthly_sig = bootstrap_results['monthly']['significant']

daily_sharpe = rebal_results.get('daily', {}).get('metrics', {}).get('sharpe', 0)
weekly_sharpe = rebal_results.get('weekly', {}).get('metrics', {}).get('sharpe', 0)
monthly_sharpe_val = rebal_results.get('monthly', {}).get('metrics', {}).get('sharpe', 0)

summary_lines = [
    f"  1. Harvey NW t>3.0:           {'PASS' if v1_pass else 'FAIL'} (t={harvey_results['nw_t_stat']:.3f})",
    f"  2. Cross-OOS (Scheme A):      {'PASS' if v2_pass_a else 'FAIL'} ({cross_oos_results.get('Scheme_A', {}).get('wins', 0)}/{cross_oos_results.get('Scheme_A', {}).get('total', 0)} wins)",
    f"     Cross-OOS (Scheme B):      {'PASS' if v2_pass_b else 'FAIL'} ({cross_oos_results.get('Scheme_B', {}).get('wins', 0)}/{cross_oos_results.get('Scheme_B', {}).get('total', 0)} wins)",
    f"  3. Rebal Sensitivity:         Daily={daily_sharpe:.3f}, Weekly={weekly_sharpe:.3f}, Monthly={monthly_sharpe_val:.3f}",
    f"     Monthly beats benchmark:   {'YES' if v3_monthly_works else 'NO'}",
    f"  4. Window Sensitivity:        Safe zone: {', '.join(safe_windows)}",
    f"     Wide zone (>=3 windows):   {'YES' if v4_wide_zone else 'NO'}",
    f"  5. TX Cost Robustness:        Survives 20bp (daily): {'YES' if v5_survives_20bp else 'NO'}",
    f"     Breakeven (daily):         ~{tx_results.get('breakeven_daily', 'N/A')} bps",
    f"     Breakeven (monthly):       ~{tx_results.get('breakeven_monthly', 'N/A')} bps",
    f"  6. Concentration:             Top-1 best: {'YES' if v6_top1_best else 'NO'}",
    f"  7. Bootstrap (daily):         {'SIGNIFICANT' if v7_bootstrap_sig else 'NOT significant'} (P(win)={bootstrap_results['daily']['p_win']:.1%})",
    f"     Bootstrap (monthly):       {'SIGNIFICANT' if v7_bootstrap_monthly_sig else 'NOT significant'} (P(win)={bootstrap_results['monthly']['p_win']:.1%})",
    f"  8. Drawdown:                  See crisis episode table above",
]

for line in summary_lines:
    print(line)

# Overall verdict
pass_count = sum([
    v1_pass, v2_pass_a, v2_pass_b, v3_monthly_works, v4_wide_zone,
    v5_survives_20bp, v7_bootstrap_sig, v7_bootstrap_monthly_sig
])
total_checks = 8

print(f"\n  OVERALL: {pass_count}/{total_checks} validation checks passed")

if v3_monthly_works and v1_pass and v7_bootstrap_monthly_sig:
    verdict = "RECOMMENDED FOR LISTING (monthly rebalancing)"
    recommendation = "monthly"
elif v1_pass and v7_bootstrap_sig:
    verdict = "CONDITIONALLY RECOMMENDED (daily rebalancing only — high TX cost risk)"
    recommendation = "daily_only"
else:
    verdict = "NOT RECOMMENDED FOR LISTING"
    recommendation = "none"

print(f"  VERDICT: {verdict}")
print(f"\n  RECOMMENDED CONFIG:")
print(f"    Rebalancing: {'Monthly' if recommendation == 'monthly' else 'Daily'}")
print(f"    Sectors: Top-1 momentum (60d)")
print(f"    Allocation: 50% sector VT + 50% GLD")
print(f"    VT weight: 12/VIX clipped [0,1]")

# =================================================================
# SAVE RESULTS
# =================================================================
elapsed = time.time() - start_time

results = {
    'experiment_id': 'K562',
    'title': 'K560 Sector Momentum VT — Deep Validation for Listing (8-Point Checklist)',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance',
    'assets': list(tickers.keys()) + ['^VIX'],
    'period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_days': len(df),
    'methodology': {
        'strategy': 'Sector Momentum Top-1 + VT + GLD',
        'vt_formula': '12/VIX clipped [0,1]',
        'portfolio_structure': '50% top-1 momentum sector VT + 50% GLD',
        'sectors': sector_tickers,
        'validation_points': 8,
    },
    'prior_knowledge': {
        'K560': 'Sector Rotation VT: Momentum Top-1 Sharpe 2.157, DM t=10.36, 3/3 OOS, 14.4% daily turnover',
        'K58': 'Sector VT Map: all sectors benefit from VT uniformly',
        'K243': 'Sector Rotation: Harvey PASS (t=3.99) but DM NS, MDD -37%',
    },
    'references': [
        'Moreira & Muir (2017): Volatility-Managed Portfolios, JF',
        'Moskowitz, Ooi, Pedersen (2012): Time Series Momentum, JFE',
        'Asness, Moskowitz, Pedersen (2013): Value and Momentum Everywhere, JF',
        'Harvey, Liu, Zhu (2016): ...and the Cross-Section of Expected Returns, RFS',
        'Jegadeesh & Titman (1993): Returns to Buying Winners, JF',
    ],
    'baseline_replication': {
        'daily_sharpe': m_strat['sharpe'] if m_strat else None,
        'daily_cagr': m_strat['cagr'] if m_strat else None,
        'daily_mdd': m_strat['mdd'] if m_strat else None,
        'daily_turnover': round(turnover_daily, 4),
        'benchmark_sharpe': m_bench['sharpe'] if m_bench else None,
    },
    'validation_1_harvey': harvey_results,
    'validation_2_cross_oos': cross_oos_results,
    'validation_3_rebal_frequency': rebal_results,
    'validation_4_momentum_window': window_results,
    'validation_5_transaction_costs': tx_results,
    'validation_6_concentration': topn_results,
    'validation_7_bootstrap': bootstrap_results,
    'validation_8_drawdowns': drawdown_results,
    'monthly_oos_validation': monthly_oos_results,
    'final_summary': {
        'pass_count': pass_count,
        'total_checks': total_checks,
        'v1_harvey_pass': v1_pass,
        'v2a_cross_oos_pass': v2_pass_a,
        'v2b_cross_oos_pass': v2_pass_b,
        'v3_monthly_works': v3_monthly_works,
        'v4_wide_window_zone': v4_wide_zone,
        'v5_survives_20bp': v5_survives_20bp,
        'v6_top1_best': v6_top1_best,
        'v7_bootstrap_daily_sig': v7_bootstrap_sig,
        'v7_bootstrap_monthly_sig': v7_bootstrap_monthly_sig,
        'verdict': verdict,
        'recommendation': recommendation,
        'recommended_config': {
            'rebalancing': 'monthly' if recommendation == 'monthly' else 'daily',
            'sectors': 'Top-1 momentum (60d)',
            'allocation': '50% sector VT + 50% GLD',
            'vt_weight': '12/VIX clipped [0,1]',
        },
    },
    'runtime_seconds': round(elapsed, 1),
}

output_path = 'experiments/k562/k562_k560_sector_validation_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print(f"Runtime: {elapsed:.1f} seconds")
