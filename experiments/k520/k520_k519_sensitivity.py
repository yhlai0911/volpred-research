#!/usr/bin/env python3
"""
K520: K519 S2 VT-Sized Overnight — Sensitivity Analysis (上架前必做驗證)
=====================================================================
[提出: 用戶, 執行: Claude]

Background:
  K519 S2 VT-Sized Overnight passed all listing criteria:
    - Net Sharpe 1.079 (>0.93 K516 baseline)
    - 5/5 cross-OOS positive
    - t=4.26 (Harvey threshold met)
    - MDD -4.4%

  This experiment tests robustness across 6 sensitivity dimensions:
    1. TX Cost: 1-20 bps
    2. VIX Threshold: 15-30 and unlimited
    3. SPY Signal: 1-day, 2-day, 5-day momentum, no signal
    4. VT Sizing: K=6-12, position cap=0.5x-1.5x
    5. Start Date: 2010-2018
    6. Gap Return Diagnostics: autocorrelation + distribution

  Goal: Determine "safe zone" where strategy remains effective.
  If only a narrow parameter range works → overfitting → do NOT list.

References:
  - K519: Premium Futures Strategy — S2 VT-Sized Overnight, Sharpe 1.079
  - K516: Overnight Gap Futures — Sharpe 0.93 at 5bp TX, 5/5 cross-OOS
  - Moreira & Muir (2017): Volatility-Managed Portfolios, JoF
  - Lou, Polk, Skouras (2019): A Tug of War, JFE
"""

import json
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats

warnings.filterwarnings('ignore')

start_time = time.time()

# ============================================================
# 1. Data Collection (same as K519)
# ============================================================
print("=" * 70)
print("K520: K519 S2 VT-Sized Overnight — Sensitivity Analysis")
print("=" * 70)

print("\n[1] Downloading data...")
tw50 = yf.download('0050.TW', start='2010-01-01', end='2026-01-01', progress=False)
spy = yf.download('SPY', start='2010-01-01', end='2026-01-01', progress=False)
vix = yf.download('^VIX', start='2010-01-01', end='2026-01-01', progress=False)

for df_raw in [tw50, spy, vix]:
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)

print(f"  0050.TW: {len(tw50)} days")
print(f"  SPY:     {len(spy)} days")
print(f"  VIX:     {len(vix)} days")

# ============================================================
# 2. Compute Returns (identical to K519)
# ============================================================
print("\n[2] Computing returns...")

tw_close = tw50['Close'].copy()
tw_open = tw50['Open'].copy()

valid_mask = (tw_close > 0) & (tw_open > 0) & tw_close.notna() & tw_open.notna()
tw_close = tw_close[valid_mask]
tw_open = tw_open[valid_mask]

gap_ret = (tw_open - tw_close.shift(1)) / tw_close.shift(1)
gap_ret = gap_ret.dropna()

intraday_ret = (tw_close - tw_open) / tw_open
intraday_ret = intraday_ret.dropna()

c2c_ret = tw_close.pct_change().dropna()

for s in [gap_ret, intraday_ret, c2c_ret]:
    outlier = s.abs() > 0.15
    if outlier.sum() > 0:
        s.drop(s[outlier].index, inplace=True)

spy_close = spy['Close'].copy()
spy_ret = spy_close.pct_change().dropna()
vix_close = vix['Close'].copy()

# ============================================================
# 3. Align Data (identical to K519)
# ============================================================
print("\n[3] Aligning data...")

df = pd.DataFrame(index=tw50.index)
df['gap_ret'] = gap_ret
df['intraday_ret'] = intraday_ret
df['c2c_ret'] = c2c_ret
df['tw_close'] = tw_close
df['tw_open'] = tw_open

# SPY: merge_asof for previous US trading day
spy_daily = spy_ret.to_frame('spy_ret')
spy_reset = spy_daily.reset_index()
spy_reset.columns = ['spy_date', 'spy_ret']
spy_reset['spy_date'] = pd.to_datetime(spy_reset['spy_date'])
spy_reset = spy_reset.dropna().sort_values('spy_date')

# SPY multi-day momentum
spy_2d = spy_close.pct_change(2).to_frame('spy_2d')
spy_2d_reset = spy_2d.reset_index()
spy_2d_reset.columns = ['spy_date', 'spy_2d']
spy_2d_reset['spy_date'] = pd.to_datetime(spy_2d_reset['spy_date'])
spy_2d_reset = spy_2d_reset.dropna().sort_values('spy_date')

spy_5d = spy_close.pct_change(5).to_frame('spy_5d')
spy_5d_reset = spy_5d.reset_index()
spy_5d_reset.columns = ['spy_date', 'spy_5d']
spy_5d_reset['spy_date'] = pd.to_datetime(spy_5d_reset['spy_date'])
spy_5d_reset = spy_5d_reset.dropna().sort_values('spy_date')

df_reset = df.reset_index()
date_col = [c for c in df_reset.columns if 'date' in c.lower() or 'Date' in c or c == 'Price']
if date_col:
    date_col = date_col[0]
else:
    date_col = df_reset.columns[0]
if date_col != 'tw_date':
    df_reset.rename(columns={date_col: 'tw_date'}, inplace=True)
df_reset['tw_date'] = pd.to_datetime(df_reset['tw_date'])
df_for_merge = df_reset[['tw_date']].sort_values('tw_date')

# Merge SPY 1-day
merged = pd.merge_asof(df_for_merge, spy_reset, left_on='tw_date', right_on='spy_date', direction='backward')
df['spy_ret_prev'] = merged.set_index('tw_date')['spy_ret']

# Merge SPY 2-day
merged_2d = pd.merge_asof(df_for_merge, spy_2d_reset, left_on='tw_date', right_on='spy_date', direction='backward')
df['spy_2d_prev'] = merged_2d.set_index('tw_date')['spy_2d']

# Merge SPY 5-day
merged_5d = pd.merge_asof(df_for_merge, spy_5d_reset, left_on='tw_date', right_on='spy_date', direction='backward')
df['spy_5d_prev'] = merged_5d.set_index('tw_date')['spy_5d']

# VIX
vix_reset = vix_close.reset_index()
if isinstance(vix_reset.columns, pd.MultiIndex):
    vix_reset.columns = ['_'.join(str(c) for c in col).strip('_') for col in vix_reset.columns]
vix_reset.columns = ['vix_date', 'vix_close']
vix_reset['vix_date'] = pd.to_datetime(vix_reset['vix_date'])
vix_reset = vix_reset.dropna().sort_values('vix_date')

merged_vix = pd.merge_asof(df_for_merge, vix_reset, left_on='tw_date', right_on='vix_date', direction='backward')
df['vix_prev'] = merged_vix.set_index('tw_date')['vix_close']

df = df.dropna(subset=['gap_ret', 'intraday_ret', 'spy_ret_prev', 'vix_prev'])
print(f"  Aligned dataset: {len(df)} trading days")
print(f"  Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

N_TOTAL = len(df)

# ============================================================
# Helper Functions
# ============================================================

def compute_metrics(returns, n_total_days=None):
    """Compute strategy metrics from daily return series."""
    returns = returns.dropna()
    n = len(returns)
    if n < 30:
        return None

    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    mdd = ((cum - peak) / peak).min()
    total_ret = cum.iloc[-1] - 1

    years = n / 252
    cagr = (cum.iloc[-1]) ** (1 / years) - 1 if years > 0 and cum.iloc[-1] > 0 else -1

    calmar = ann_ret / abs(mdd) if mdd != 0 else 0
    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else 1
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0

    trading_days = returns[returns != 0]
    if len(trading_days) > 10:
        t_stat, p_val = stats.ttest_1samp(trading_days, 0)
    else:
        t_stat, p_val = 0.0, 1.0

    win_rate = (trading_days > 0).mean() if len(trading_days) > 0 else 0
    n_active = (returns != 0).sum()
    exposure = n_active / n_total_days if n_total_days else n_active / n

    return {
        'n_days': n,
        'n_active': int(n_active),
        'exposure_pct': round(float(exposure * 100), 1),
        'ann_return_pct': round(float(ann_ret * 100), 2),
        'ann_vol_pct': round(float(ann_vol * 100), 2),
        'sharpe': round(float(sharpe), 3),
        'cagr_pct': round(float(cagr * 100), 2),
        'total_return_pct': round(float(total_ret * 100), 2),
        'mdd_pct': round(float(mdd * 100), 2),
        'calmar': round(float(calmar), 3),
        'sortino': round(float(sortino), 3),
        't_stat': round(float(t_stat), 3),
        'p_val': round(float(p_val), 4),
        'win_rate_pct': round(float(win_rate * 100), 1),
    }


def run_s2_strategy(data, tx_bps, vix_thresh, spy_signal_col, k_val, pos_cap):
    """
    Run S2 VT-Sized Overnight strategy with parameterized settings.

    Args:
        data: DataFrame with gap_ret, vix_prev, spy signal columns
        tx_bps: transaction cost in basis points
        vix_thresh: VIX threshold (None = no VIX filter)
        spy_signal_col: column name for SPY signal, or None for no SPY filter
        k_val: K in K/VIX sizing
        pos_cap: maximum position size (e.g., 2.0)

    Returns:
        net return series
    """
    tx_cost = tx_bps / 10000.0

    # VT sizing
    vt_size = (k_val / data['vix_prev']).clip(upper=pos_cap)

    # Signal
    if spy_signal_col is not None and vix_thresh is not None:
        sig_binary = ((data[spy_signal_col] > 0) & (data['vix_prev'] < vix_thresh)).astype(float)
    elif spy_signal_col is not None:
        sig_binary = (data[spy_signal_col] > 0).astype(float)
    elif vix_thresh is not None:
        sig_binary = (data['vix_prev'] < vix_thresh).astype(float)
    else:
        sig_binary = pd.Series(1.0, index=data.index)

    sig = vt_size * sig_binary
    gross = data['gap_ret'] * sig
    net = gross - tx_cost * sig

    return net


OOS_PERIODS = [
    ('2013-01-01', '2015-12-31'),
    ('2016-01-01', '2018-12-31'),
    ('2019-01-01', '2020-12-31'),
    ('2021-01-01', '2023-06-30'),
    ('2023-07-01', '2025-12-31'),
]


def cross_oos_wins(data, tx_bps, vix_thresh, spy_signal_col, k_val, pos_cap):
    """Count how many OOS periods have positive Sharpe."""
    wins = 0
    sharpes = []
    for start, end in OOS_PERIODS:
        mask = (data.index >= start) & (data.index <= end)
        d = data[mask]
        if len(d) < 30:
            sharpes.append(0)
            continue
        net = run_s2_strategy(d, tx_bps, vix_thresh, spy_signal_col, k_val, pos_cap)
        m = compute_metrics(net, n_total_days=len(d))
        if m and m['sharpe'] > 0:
            wins += 1
        sharpes.append(m['sharpe'] if m else 0)
    return wins, sharpes


# ============================================================
# 4. Baseline S2 result
# ============================================================
print("\n[4] Baseline S2 (K519 default params)")
print("=" * 70)
baseline_net = run_s2_strategy(df, tx_bps=5, vix_thresh=25, spy_signal_col='spy_ret_prev',
                                k_val=8.63, pos_cap=2.0)
baseline_m = compute_metrics(baseline_net, n_total_days=N_TOTAL)
baseline_wins, baseline_oos_sharpes = cross_oos_wins(df, 5, 25, 'spy_ret_prev', 8.63, 2.0)

print(f"  Sharpe: {baseline_m['sharpe']}, MDD: {baseline_m['mdd_pct']}%, "
      f"t-stat: {baseline_m['t_stat']}, cross-OOS: {baseline_wins}/5")
print(f"  OOS Sharpes: {baseline_oos_sharpes}")

# ============================================================
# 5. Sensitivity 1: TX Cost
# ============================================================
print("\n\n[5] Sensitivity 1: TX Cost")
print("=" * 70)

tx_levels = [1, 2, 3, 5, 7, 10, 15, 20]
tx_results = []

for tx in tx_levels:
    net = run_s2_strategy(df, tx_bps=tx, vix_thresh=25, spy_signal_col='spy_ret_prev',
                          k_val=8.63, pos_cap=2.0)
    m = compute_metrics(net, n_total_days=N_TOTAL)
    wins, oos_sharpes = cross_oos_wins(df, tx, 25, 'spy_ret_prev', 8.63, 2.0)
    entry = {
        'tx_bps': tx,
        'sharpe': m['sharpe'] if m else 0,
        'ann_return_pct': m['ann_return_pct'] if m else 0,
        'mdd_pct': m['mdd_pct'] if m else 0,
        't_stat': m['t_stat'] if m else 0,
        'cross_oos_wins': wins,
        'oos_sharpes': [round(s, 3) for s in oos_sharpes],
    }
    tx_results.append(entry)
    status = "OK" if m and m['sharpe'] > 0.5 else "WEAK"
    print(f"  {tx:>3} bps: Sharpe={entry['sharpe']:>6.3f}, MDD={entry['mdd_pct']:>6.2f}%, "
          f"t={entry['t_stat']:>5.3f}, OOS={wins}/5  [{status}]")

# Find breakeven
breakeven_tx = None
oos_4_max_tx = None
for r in tx_results:
    if r['sharpe'] < 0.5 and breakeven_tx is None:
        breakeven_tx = r['tx_bps']
    if r['cross_oos_wins'] >= 4:
        oos_4_max_tx = r['tx_bps']

print(f"\n  Breakeven TX (Sharpe < 0.5): {breakeven_tx if breakeven_tx else '>20'} bps")
print(f"  Max TX with cross-OOS >= 4/5: {oos_4_max_tx if oos_4_max_tx else 'None'} bps")

# ============================================================
# 6. Sensitivity 2: VIX Threshold
# ============================================================
print("\n\n[6] Sensitivity 2: VIX Threshold")
print("=" * 70)

vix_thresholds = [15, 18, 20, 22, 25, 30, None]  # None = always
vix_results = []

for vt in vix_thresholds:
    label = f"VIX<{vt}" if vt else "Always"
    net = run_s2_strategy(df, tx_bps=5, vix_thresh=vt, spy_signal_col='spy_ret_prev',
                          k_val=8.63, pos_cap=2.0)
    m = compute_metrics(net, n_total_days=N_TOTAL)
    wins, oos_sharpes = cross_oos_wins(df, 5, vt, 'spy_ret_prev', 8.63, 2.0)
    entry = {
        'vix_threshold': vt if vt else 'always',
        'label': label,
        'sharpe': m['sharpe'] if m else 0,
        'ann_return_pct': m['ann_return_pct'] if m else 0,
        'mdd_pct': m['mdd_pct'] if m else 0,
        't_stat': m['t_stat'] if m else 0,
        'cross_oos_wins': wins,
        'oos_sharpes': [round(s, 3) for s in oos_sharpes],
        'n_active': m['n_active'] if m else 0,
        'exposure_pct': m['exposure_pct'] if m else 0,
    }
    vix_results.append(entry)
    print(f"  {label:>10}: Sharpe={entry['sharpe']:>6.3f}, MDD={entry['mdd_pct']:>6.2f}%, "
          f"t={entry['t_stat']:>5.3f}, OOS={wins}/5, exposure={entry['exposure_pct']:.1f}%")

# ============================================================
# 7. Sensitivity 3: SPY Signal
# ============================================================
print("\n\n[7] Sensitivity 3: SPY Signal Variant")
print("=" * 70)

spy_signals = [
    ('spy_ret_prev', 'SPY 1-day > 0'),
    ('spy_2d_prev', 'SPY 2-day > 0'),
    ('spy_5d_prev', 'SPY 5-day > 0'),
    (None, 'No SPY signal (VIX only)'),
]
spy_results = []

for col, label in spy_signals:
    net = run_s2_strategy(df, tx_bps=5, vix_thresh=25, spy_signal_col=col,
                          k_val=8.63, pos_cap=2.0)
    m = compute_metrics(net, n_total_days=N_TOTAL)
    wins, oos_sharpes = cross_oos_wins(df, 5, 25, col, 8.63, 2.0)
    entry = {
        'signal': label,
        'signal_col': col if col else 'none',
        'sharpe': m['sharpe'] if m else 0,
        'ann_return_pct': m['ann_return_pct'] if m else 0,
        'mdd_pct': m['mdd_pct'] if m else 0,
        't_stat': m['t_stat'] if m else 0,
        'cross_oos_wins': wins,
        'oos_sharpes': [round(s, 3) for s in oos_sharpes],
        'n_active': m['n_active'] if m else 0,
        'exposure_pct': m['exposure_pct'] if m else 0,
    }
    spy_results.append(entry)
    print(f"  {label:<25}: Sharpe={entry['sharpe']:>6.3f}, MDD={entry['mdd_pct']:>6.2f}%, "
          f"t={entry['t_stat']:>5.3f}, OOS={wins}/5, exposure={entry['exposure_pct']:.1f}%")

# ============================================================
# 8. Sensitivity 4: VT Sizing (K and cap)
# ============================================================
print("\n\n[8] Sensitivity 4: VT Sizing (K value + Position Cap)")
print("=" * 70)

k_values = [6, 8, 8.63, 10, 12]
pos_caps = [0.5, 0.8, 1.0, 1.5, 2.0]
sizing_results = []

print(f"  {'K':>6} {'Cap':>5} | {'Sharpe':>7} {'AnnRet%':>8} {'MDD%':>7} {'t':>6} {'OOS':>5}")
print(f"  {'-'*6} {'-'*5} | {'-'*7} {'-'*8} {'-'*7} {'-'*6} {'-'*5}")

for k in k_values:
    for cap in pos_caps:
        net = run_s2_strategy(df, tx_bps=5, vix_thresh=25, spy_signal_col='spy_ret_prev',
                              k_val=k, pos_cap=cap)
        m = compute_metrics(net, n_total_days=N_TOTAL)
        wins, oos_sharpes = cross_oos_wins(df, 5, 25, 'spy_ret_prev', k, cap)
        entry = {
            'k_val': k,
            'pos_cap': cap,
            'sharpe': m['sharpe'] if m else 0,
            'ann_return_pct': m['ann_return_pct'] if m else 0,
            'ann_vol_pct': m['ann_vol_pct'] if m else 0,
            'mdd_pct': m['mdd_pct'] if m else 0,
            't_stat': m['t_stat'] if m else 0,
            'cross_oos_wins': wins,
            'oos_sharpes': [round(s, 3) for s in oos_sharpes],
        }
        sizing_results.append(entry)
        print(f"  {k:>6.2f} {cap:>5.1f} | {entry['sharpe']:>7.3f} {entry['ann_return_pct']:>7.2f}% "
              f"{entry['mdd_pct']:>6.2f}% {entry['t_stat']:>5.3f} {wins}/5")

# ============================================================
# 9. Sensitivity 5: Start Date
# ============================================================
print("\n\n[9] Sensitivity 5: Start Date")
print("=" * 70)

start_dates = ['2010-01-01', '2012-01-01', '2014-01-01', '2016-01-01', '2018-01-01']
start_results = []

for sd in start_dates:
    mask = df.index >= sd
    d = df[mask]
    net = run_s2_strategy(d, tx_bps=5, vix_thresh=25, spy_signal_col='spy_ret_prev',
                          k_val=8.63, pos_cap=2.0)
    m = compute_metrics(net, n_total_days=len(d))

    # Cross-OOS (only periods after start date)
    wins = 0
    oos_sharpes = []
    for s_oos, e_oos in OOS_PERIODS:
        if s_oos < sd:
            continue
        oos_mask = (d.index >= s_oos) & (d.index <= e_oos)
        d_oos = d[oos_mask]
        if len(d_oos) < 30:
            oos_sharpes.append(0)
            continue
        net_oos = run_s2_strategy(d_oos, tx_bps=5, vix_thresh=25, spy_signal_col='spy_ret_prev',
                                   k_val=8.63, pos_cap=2.0)
        m_oos = compute_metrics(net_oos, n_total_days=len(d_oos))
        if m_oos and m_oos['sharpe'] > 0:
            wins += 1
        oos_sharpes.append(m_oos['sharpe'] if m_oos else 0)

    n_applicable = len([s for s, e in OOS_PERIODS if s >= sd])
    entry = {
        'start_date': sd,
        'n_days': len(d),
        'sharpe': m['sharpe'] if m else 0,
        'ann_return_pct': m['ann_return_pct'] if m else 0,
        'mdd_pct': m['mdd_pct'] if m else 0,
        't_stat': m['t_stat'] if m else 0,
        'cross_oos_wins': wins,
        'applicable_periods': n_applicable,
        'oos_sharpes': [round(s, 3) for s in oos_sharpes],
    }
    start_results.append(entry)
    print(f"  From {sd}: {len(d)} days, Sharpe={entry['sharpe']:.3f}, MDD={entry['mdd_pct']:.2f}%, "
          f"t={entry['t_stat']:.3f}, OOS={wins}/{n_applicable}")

# ============================================================
# 10. Gap Return Diagnostics (proxy quality)
# ============================================================
print("\n\n[10] Gap Return Diagnostics (Proxy Quality)")
print("=" * 70)

gap = df['gap_ret']

# Autocorrelation
acf_lags = [1, 2, 3, 5, 10, 20]
acf_values = {}
for lag in acf_lags:
    acf_val = gap.autocorr(lag=lag)
    acf_values[f'lag_{lag}'] = round(float(acf_val), 4)
    print(f"  ACF(gap, lag={lag}): {acf_val:.4f}")

# Ljung-Box test
from scipy.stats import chi2
n_obs = len(gap)
lb_stat = 0
lb_lags = 10
for lag_i in range(1, lb_lags + 1):
    ac = gap.autocorr(lag=lag_i)
    lb_stat += (ac ** 2) / (n_obs - lag_i)
lb_stat *= n_obs * (n_obs + 2)
lb_pval = 1 - chi2.cdf(lb_stat, lb_lags)
print(f"\n  Ljung-Box Q({lb_lags}): stat={lb_stat:.4f}, p-val={lb_pval:.4f}")
print(f"  {'Significant serial correlation' if lb_pval < 0.05 else 'No significant serial correlation'}")

# Distribution
gap_bps = gap * 10000
print(f"\n  Gap return distribution (bps):")
print(f"    Mean:     {gap_bps.mean():.2f}")
print(f"    Std:      {gap_bps.std():.2f}")
print(f"    Skewness: {gap_bps.skew():.3f}")
print(f"    Kurtosis: {gap_bps.kurtosis():.3f}")
print(f"    Min:      {gap_bps.min():.2f}")
print(f"    5%:       {gap_bps.quantile(0.05):.2f}")
print(f"    25%:      {gap_bps.quantile(0.25):.2f}")
print(f"    Median:   {gap_bps.median():.2f}")
print(f"    75%:      {gap_bps.quantile(0.75):.2f}")
print(f"    95%:      {gap_bps.quantile(0.95):.2f}")
print(f"    Max:      {gap_bps.max():.2f}")

# Jarque-Bera test for normality
jb_stat, jb_pval = stats.jarque_bera(gap.dropna())
print(f"\n  Jarque-Bera: stat={jb_stat:.2f}, p-val={jb_pval:.6f}")
print(f"  {'Reject normality (fat-tailed)' if jb_pval < 0.05 else 'Cannot reject normality'}")

# ============================================================
# 11. Safe Zone Analysis
# ============================================================
print("\n\n[11] Safe Zone Analysis")
print("=" * 70)

# TX safe zone
tx_safe = [r for r in tx_results if r['sharpe'] > 0.5 and r['cross_oos_wins'] >= 4]
tx_safe_range = f"1-{max(r['tx_bps'] for r in tx_safe)} bps" if tx_safe else "None"
print(f"  TX Cost safe zone (Sharpe>0.5 & OOS>=4/5): {tx_safe_range}")

# VIX safe zone
vix_safe = [r for r in vix_results if r['sharpe'] > 0.5 and r['cross_oos_wins'] >= 4]
vix_safe_labels = [r['label'] for r in vix_safe]
print(f"  VIX Threshold safe zone: {', '.join(vix_safe_labels) if vix_safe_labels else 'None'}")

# SPY signal safe zone
spy_safe = [r for r in spy_results if r['sharpe'] > 0.5 and r['cross_oos_wins'] >= 4]
spy_safe_labels = [r['signal'] for r in spy_safe]
print(f"  SPY Signal safe zone: {', '.join(spy_safe_labels) if spy_safe_labels else 'None'}")

# Sizing safe zone
sizing_safe = [r for r in sizing_results if r['sharpe'] > 0.5 and r['cross_oos_wins'] >= 4]
sizing_safe_pairs = [(r['k_val'], r['pos_cap']) for r in sizing_safe]
k_range = (min(p[0] for p in sizing_safe_pairs), max(p[0] for p in sizing_safe_pairs)) if sizing_safe_pairs else (None, None)
cap_range = (min(p[1] for p in sizing_safe_pairs), max(p[1] for p in sizing_safe_pairs)) if sizing_safe_pairs else (None, None)
print(f"  K value safe zone: {k_range[0]}-{k_range[1]}" if k_range[0] else "  K value safe zone: None")
print(f"  Position cap safe zone: {cap_range[0]}x-{cap_range[1]}x" if cap_range[0] else "  Position cap safe zone: None")

# Start date
start_safe = [r for r in start_results if r['sharpe'] > 0.5]
print(f"  Start date sensitivity: {'All start dates Sharpe>0.5' if len(start_safe) == len(start_results) else 'Sensitive to start date'}")

# Overall robustness assessment
n_safe_dimensions = 0
for safe_list, dim_name in [
    (tx_safe, 'TX Cost'),
    (vix_safe, 'VIX Threshold'),
    (spy_safe, 'SPY Signal'),
    (sizing_safe, 'VT Sizing'),
]:
    if len(safe_list) >= 2:
        n_safe_dimensions += 1

# Wide parameter zone = NOT overfit
is_robust = n_safe_dimensions >= 3
print(f"\n  Dimensions with wide safe zone (>=2 configs): {n_safe_dimensions}/4")
print(f"  Overall assessment: {'ROBUST — OK to list' if is_robust else 'FRAGILE — do NOT list'}")

# ============================================================
# 12. Compile Results JSON
# ============================================================
elapsed = time.time() - start_time

results_json = {
    'experiment_id': 'K520',
    'title': 'K519 S2 VT-Sized Overnight — Sensitivity Analysis (上架前驗證)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'attribution': '[提出: 用戶, 執行: Claude]',
    'parent_experiment': 'K519',
    'strategy': 'S2: VT-Sized Overnight = (8.63/VIX) * SPY>0 * VIX<25 → overnight gap',
    'data_source': 'yfinance: 0050.TW, SPY, ^VIX',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_trading_days': N_TOTAL,
    'elapsed_seconds': round(elapsed, 1),
    'references': [
        'K519: Premium Futures Strategy — S2 VT-Sized Overnight, Sharpe 1.079, 5/5 OOS',
        'K516: Overnight Gap Futures — Sharpe 0.93 at 5bp TX, 5/5 cross-OOS',
        'Moreira & Muir (2017): Volatility-Managed Portfolios, JoF',
        'Lou, Polk, Skouras (2019): A Tug of War: Overnight vs Intraday Returns, JFE',
    ],

    'baseline': {
        'params': {'tx_bps': 5, 'vix_thresh': 25, 'spy_signal': 'SPY_1d>0', 'k_val': 8.63, 'pos_cap': 2.0},
        'sharpe': baseline_m['sharpe'],
        'mdd_pct': baseline_m['mdd_pct'],
        't_stat': baseline_m['t_stat'],
        'cross_oos_wins': baseline_wins,
        'oos_sharpes': [round(s, 3) for s in baseline_oos_sharpes],
    },

    'sensitivity_1_tx_cost': {
        'description': 'Net Sharpe and cross-OOS wins at different TX cost levels',
        'results': tx_results,
        'breakeven_tx_bps': breakeven_tx if breakeven_tx else '>20',
        'max_tx_oos_4of5': oos_4_max_tx,
        'safe_zone': tx_safe_range,
    },

    'sensitivity_2_vix_threshold': {
        'description': 'Impact of VIX filter threshold on strategy performance',
        'results': vix_results,
        'safe_zone': vix_safe_labels,
    },

    'sensitivity_3_spy_signal': {
        'description': 'SPY signal variant: 1-day, 2-day, 5-day momentum, or none',
        'results': spy_results,
        'safe_zone': spy_safe_labels,
    },

    'sensitivity_4_vt_sizing': {
        'description': 'K/VIX sizing parameter and position cap sensitivity',
        'results': sizing_results,
        'k_safe_range': list(k_range) if k_range[0] else None,
        'cap_safe_range': list(cap_range) if cap_range[0] else None,
    },

    'sensitivity_5_start_date': {
        'description': 'Performance stability across different sample start dates',
        'results': start_results,
        'all_positive': len(start_safe) == len(start_results),
    },

    'gap_return_diagnostics': {
        'autocorrelation': acf_values,
        'ljung_box_Q10': {'statistic': round(float(lb_stat), 4), 'p_value': round(float(lb_pval), 4)},
        'distribution_bps': {
            'mean': round(float(gap_bps.mean()), 2),
            'std': round(float(gap_bps.std()), 2),
            'skewness': round(float(gap_bps.skew()), 3),
            'kurtosis': round(float(gap_bps.kurtosis()), 3),
            'percentiles': {
                'p5': round(float(gap_bps.quantile(0.05)), 2),
                'p25': round(float(gap_bps.quantile(0.25)), 2),
                'p50': round(float(gap_bps.median()), 2),
                'p75': round(float(gap_bps.quantile(0.75)), 2),
                'p95': round(float(gap_bps.quantile(0.95)), 2),
            },
        },
        'jarque_bera': {'statistic': round(float(jb_stat), 2), 'p_value': round(float(jb_pval), 6)},
        'is_fat_tailed': bool(jb_pval < 0.05),
    },

    'safe_zone_summary': {
        'tx_cost': tx_safe_range,
        'vix_threshold': vix_safe_labels,
        'spy_signal': spy_safe_labels,
        'k_value_range': list(k_range) if k_range[0] else None,
        'pos_cap_range': list(cap_range) if cap_range[0] else None,
        'start_date_stable': len(start_safe) == len(start_results),
        'n_robust_dimensions': n_safe_dimensions,
        'overall_assessment': 'ROBUST' if is_robust else 'FRAGILE',
        'listing_recommendation': 'OK to list' if is_robust else 'Do NOT list — overfitting risk',
    },
}

# Save results
output_path = 'experiments/k520_k519_sensitivity_results.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results_json, f, indent=2, ensure_ascii=False, default=str)

print(f"\n\nResults saved to {output_path}")
print(f"Elapsed: {elapsed:.1f}s")

# ============================================================
# 13. Final Summary
# ============================================================
print("\n\n" + "=" * 70)
print("K520 FINAL SUMMARY: SENSITIVITY ANALYSIS")
print("=" * 70)

print(f"\n  Strategy: S2 VT-Sized Overnight (K519)")
print(f"  Baseline: Sharpe {baseline_m['sharpe']}, MDD {baseline_m['mdd_pct']}%, t={baseline_m['t_stat']}, OOS {baseline_wins}/5")

print(f"\n  --- Safe Zones ---")
print(f"  TX Cost:       {tx_safe_range}")
print(f"  VIX Threshold: {', '.join(vix_safe_labels) if vix_safe_labels else 'None'}")
print(f"  SPY Signal:    {', '.join(spy_safe_labels) if spy_safe_labels else 'None'}")
if k_range[0]:
    print(f"  K value:       {k_range[0]}-{k_range[1]}")
if cap_range[0]:
    print(f"  Position cap:  {cap_range[0]}x-{cap_range[1]}x")
print(f"  Start date:    {'Stable' if len(start_safe) == len(start_results) else 'Sensitive'}")

print(f"\n  Robust dimensions: {n_safe_dimensions}/4")
print(f"  VERDICT: {'✅ ROBUST — OK to list' if is_robust else '❌ FRAGILE — do NOT list'}")
print(f"\n  Elapsed: {elapsed:.1f}s")
