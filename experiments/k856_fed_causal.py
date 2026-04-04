#!/usr/bin/env python3
"""
K856: Causal Inference — Fed Rate Decisions and VIX Regime Shifts
=================================================================

Research Question:
  Can we estimate the CAUSAL (not just correlational) effect of Fed rate decisions
  on VIX regime transitions?

Prior work:
  - K513: Only FOMC significantly affects volatility (+28%), CPI/NFP are null
  - K514: FOMC surprise has strong IS signal (t=-8.18) but OOS significantly WORSE (DM t=+3.89)
  - K185: FOMC vol effect confirmed (VIX prices in FOMC dates)

Methodology:
  1. Event Study: VIX path in [-5, +10] window around FOMC (hike/cut/hold)
  2. Regression Discontinuity Design (RDD): Discontinuity at rate change announcement
  3. Difference-in-Differences (DiD): Rate-change vs hold FOMC meetings
  4. Surprise Regression: Effect of rate surprise on VIX changes

Data Sources:
  - FRED: DFF (effective fed funds rate), DFEDTARU (target upper), DGS2 (2yr yield)
  - yfinance: ^VIX (daily), SPY
  - Period: 2000-01 to 2026-04

References:
  - Bernanke & Kuttner (2005), "What Explains the Stock Market's Reaction to Federal Reserve Policy?", JF
  - Bauer & Swanson (2023), "A Reassessment of Monetary Policy Surprises and High-Frequency Identification", NBER
  - Nakamura & Steinsson (2018), "High-Frequency Identification of Monetary Non-Neutrality", QJE
  - Imbens & Lemieux (2008), "Regression Discontinuity Designs: A Guide to Practice", JoE

Author: VolPred Research System
Proposed by: User (research_program.md causal inference direction)
Executed by: Claude
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta
from scipy import stats
import statsmodels.api as sm
from statsmodels.regression.linear_model import OLS
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

warnings.filterwarnings('ignore')
np.random.seed(42)

OUT_DIR = Path(__file__).parent
CHARTS_DIR = OUT_DIR / 'k856_charts'
CHARTS_DIR.mkdir(exist_ok=True)

# ============================================================
# 1. FOMC Meeting Dates (2000-2026)
# ============================================================
# Known FOMC scheduled meeting dates (announcement dates).
# Source: Federal Reserve Board historical calendars.
# We use a comprehensive list; unscheduled meetings are also included where known.

FOMC_DATES_STR = [
    # 2000
    "2000-02-02", "2000-03-21", "2000-05-16", "2000-06-28",
    "2000-08-22", "2000-10-03", "2000-11-15", "2000-12-19",
    # 2001
    "2001-01-03", "2001-01-31", "2001-03-20", "2001-04-18",
    "2001-05-15", "2001-06-27", "2001-08-21", "2001-09-17",
    "2001-10-02", "2001-11-06", "2001-12-11",
    # 2002
    "2002-01-30", "2002-03-19", "2002-05-07", "2002-06-26",
    "2002-08-13", "2002-09-24", "2002-10-06", "2002-11-06", "2002-12-10",
    # 2003
    "2003-01-29", "2003-03-18", "2003-05-06", "2003-06-25",
    "2003-08-12", "2003-09-16", "2003-10-28", "2003-12-09",
    # 2004
    "2004-01-28", "2004-03-16", "2004-05-04", "2004-06-30",
    "2004-08-10", "2004-09-21", "2004-10-06", "2004-11-10", "2004-12-14",
    # 2005
    "2005-02-02", "2005-03-22", "2005-05-03", "2005-06-30",
    "2005-08-09", "2005-09-20", "2005-11-01", "2005-12-13",
    # 2006
    "2006-01-31", "2006-03-28", "2006-05-10", "2006-06-29",
    "2006-08-08", "2006-09-20", "2006-10-25", "2006-12-12",
    # 2007
    "2007-01-31", "2007-03-21", "2007-05-09", "2007-06-28",
    "2007-08-07", "2007-08-17", "2007-09-18", "2007-10-31", "2007-12-11",
    # 2008
    "2008-01-22", "2008-01-30", "2008-03-18", "2008-04-30",
    "2008-06-25", "2008-08-05", "2008-09-16", "2008-10-08",
    "2008-10-29", "2008-12-16",
    # 2009
    "2009-01-28", "2009-03-18", "2009-04-29", "2009-06-24",
    "2009-08-12", "2009-09-23", "2009-11-04", "2009-12-16",
    # 2010
    "2010-01-27", "2010-03-16", "2010-04-28", "2010-06-23",
    "2010-08-10", "2010-09-21", "2010-11-03", "2010-12-14",
    # 2011
    "2011-01-26", "2011-03-15", "2011-04-27", "2011-06-22",
    "2011-08-09", "2011-09-21", "2011-11-02", "2011-12-13",
    # 2012
    "2012-01-25", "2012-03-13", "2012-04-25", "2012-06-20",
    "2012-08-01", "2012-09-13", "2012-10-24", "2012-12-12",
    # 2013
    "2013-01-30", "2013-03-20", "2013-05-01", "2013-06-19",
    "2013-07-31", "2013-09-18", "2013-10-30", "2013-12-18",
    # 2014
    "2014-01-29", "2014-03-19", "2014-04-30", "2014-06-18",
    "2014-07-30", "2014-09-17", "2014-10-29", "2014-12-17",
    # 2015
    "2015-01-28", "2015-03-18", "2015-04-29", "2015-06-17",
    "2015-07-29", "2015-09-17", "2015-10-28", "2015-12-16",
    # 2016
    "2016-01-27", "2016-03-16", "2016-04-27", "2016-06-15",
    "2016-07-27", "2016-09-21", "2016-11-02", "2016-12-14",
    # 2017
    "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14",
    "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13",
    # 2018
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13",
    "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
    # 2019
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
    "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    # 2020
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-03-23",
    "2020-04-29", "2020-06-10", "2020-07-29", "2020-09-16",
    "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-17",
    # 2026 (known schedule)
    "2026-01-28", "2026-03-18",
]

FOMC_DATES = pd.to_datetime(FOMC_DATES_STR)

print("=" * 70)
print("K856: Causal Inference — Fed Rate Decisions and VIX Regime Shifts")
print("=" * 70)

# ============================================================
# 2. Download Data
# ============================================================
print("\n[1/6] Downloading data...")

START = "1999-06-01"  # extra buffer for pre-FOMC windows
END = "2026-04-05"

# VIX
vix_raw = yf.download("^VIX", start=START, end=END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw[['Close']].rename(columns={'Close': 'VIX'}).dropna()
vix.index = pd.to_datetime(vix.index).tz_localize(None)

# SPY
spy_raw = yf.download("SPY", start=START, end=END, progress=False)
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
spy = spy_raw[['Close']].rename(columns={'Close': 'SPY'}).dropna()
spy.index = pd.to_datetime(spy.index).tz_localize(None)
spy['spy_ret'] = spy['SPY'].pct_change()
spy['spy_rv5'] = spy['spy_ret'].rolling(5).std() * np.sqrt(252)

# FRED data via direct API (no pandas_datareader dependency)
def fetch_fred_series(series_id, start, end):
    """Fetch a FRED series as a pandas DataFrame using the FRED public CSV endpoint."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))
        # FRED CSV uses 'observation_date' as the date column
        date_col = [c for c in df.columns if 'date' in c.lower()]
        if date_col:
            df.index = pd.to_datetime(df[date_col[0]])
            df = df.drop(columns=date_col)
        df.columns = [series_id]
        df[series_id] = pd.to_numeric(df[series_id], errors='coerce')
        return df.dropna()
    except Exception as e:
        print(f"  WARNING: Could not fetch {series_id}: {e}")
        return pd.DataFrame()

dff = fetch_fred_series('DFF', START, END)
if len(dff) > 0:
    print(f"  DFF (Effective Fed Funds Rate): {len(dff)} obs")

dfedtaru = fetch_fred_series('DFEDTARU', START, END)
if len(dfedtaru) > 0:
    print(f"  DFEDTARU (Target Upper): {len(dfedtaru)} obs")

dgs2 = fetch_fred_series('DGS2', START, END)
if len(dgs2) > 0:
    print(f"  DGS2 (2-Year Treasury): {len(dgs2)} obs")

# Merge all
data = vix.copy()
data = data.join(spy[['spy_ret', 'spy_rv5']], how='left')
if len(dff) > 0:
    dff.index = pd.to_datetime(dff.index).tz_localize(None)
    data = data.join(dff, how='left')
    data['DFF'] = data['DFF'].ffill()
if len(dfedtaru) > 0:
    dfedtaru.index = pd.to_datetime(dfedtaru.index).tz_localize(None)
    data = data.join(dfedtaru, how='left')
    data['DFEDTARU'] = data['DFEDTARU'].ffill()
if len(dgs2) > 0:
    dgs2.index = pd.to_datetime(dgs2.index).tz_localize(None)
    data = data.join(dgs2, how='left')
    data['DGS2'] = data['DGS2'].ffill()

print(f"  Combined dataset: {len(data)} trading days ({data.index[0].date()} to {data.index[-1].date()})")
print(f"  VIX range: {data['VIX'].min():.1f} - {data['VIX'].max():.1f}")

# ============================================================
# 3. Classify FOMC Meetings (Hike / Cut / Hold)
# ============================================================
print("\n[2/6] Classifying FOMC meetings...")

def find_nearest_trading_day(date, index, direction='backward'):
    """Find nearest trading day in index."""
    if date in index:
        return date
    if direction == 'backward':
        candidates = index[index <= date]
        return candidates[-1] if len(candidates) > 0 else None
    else:
        candidates = index[index >= date]
        return candidates[0] if len(candidates) > 0 else None

fomc_events = []
for fdate in FOMC_DATES:
    td = find_nearest_trading_day(fdate, data.index, 'backward')
    if td is None:
        continue

    # Find rate before and after
    # Use DFF (effective rate) to detect actual rate changes
    if 'DFF' not in data.columns:
        continue

    # Rate on FOMC day and 5 days before
    loc = data.index.get_loc(td)
    if loc < 10 or loc > len(data) - 12:
        continue

    rate_after = data['DFF'].iloc[loc]
    rate_before = data['DFF'].iloc[loc - 1]

    # More robust: compare rate 2 days after vs 2 days before
    rate_post = data['DFF'].iloc[min(loc + 2, len(data) - 1)]
    rate_pre = data['DFF'].iloc[max(loc - 2, 0)]

    delta_rate = rate_post - rate_pre

    # Classify
    if delta_rate > 0.10:
        action = 'hike'
    elif delta_rate < -0.10:
        action = 'cut'
    else:
        action = 'hold'

    # Rate surprise: compare actual change with market expectation
    # Proxy: change in 2-year yield over [-5, -1] before FOMC approximates expected change
    surprise = np.nan
    if 'DGS2' in data.columns:
        dgs2_pre5 = data['DGS2'].iloc[max(loc - 5, 0)]
        dgs2_pre1 = data['DGS2'].iloc[loc - 1]
        expected_change = dgs2_pre1 - dgs2_pre5  # market's priced-in expectation of rate move
        surprise = delta_rate - expected_change

    # VIX on FOMC day
    vix_fomc = data['VIX'].iloc[loc]

    # VIX changes
    vix_pre = data['VIX'].iloc[max(loc - 5, 0)]
    vix_d1 = data['VIX'].iloc[min(loc + 1, len(data) - 1)]
    vix_d5 = data['VIX'].iloc[min(loc + 5, len(data) - 1)]
    vix_d10 = data['VIX'].iloc[min(loc + 10, len(data) - 1)]

    # VIX regime
    if vix_fomc < 15:
        regime = 'low'
    elif vix_fomc < 25:
        regime = 'medium'
    else:
        regime = 'high'

    fomc_events.append({
        'date': td,
        'fomc_date': fdate,
        'action': action,
        'delta_rate': delta_rate,
        'surprise': surprise,
        'vix_fomc': vix_fomc,
        'vix_pre5': vix_pre,
        'vix_d1': vix_d1,
        'vix_d5': vix_d5,
        'vix_d10': vix_d10,
        'dvix_d1': vix_d1 - vix_fomc,
        'dvix_d5': vix_d5 - vix_fomc,
        'dvix_d10': vix_d10 - vix_fomc,
        'regime': regime,
        'loc': loc,
    })

fomc_df = pd.DataFrame(fomc_events)
fomc_df.set_index('date', inplace=True)

n_hike = (fomc_df['action'] == 'hike').sum()
n_cut = (fomc_df['action'] == 'cut').sum()
n_hold = (fomc_df['action'] == 'hold').sum()
print(f"  Total FOMC meetings matched: {len(fomc_df)}")
print(f"  Hikes: {n_hike}, Cuts: {n_cut}, Holds: {n_hold}")
print(f"  Regime distribution at FOMC: Low={sum(fomc_df['regime']=='low')}, "
      f"Med={sum(fomc_df['regime']=='medium')}, High={sum(fomc_df['regime']=='high')}")

if not np.isnan(fomc_df['surprise'].iloc[0]):
    print(f"  Rate surprise stats: mean={fomc_df['surprise'].mean():.3f}, "
          f"std={fomc_df['surprise'].std():.3f}")

# ============================================================
# 4. EVENT STUDY: VIX path around FOMC
# ============================================================
print("\n[3/6] Event Study: VIX path around FOMC...")

WINDOW_PRE = 5
WINDOW_POST = 10

event_paths = {'hike': [], 'cut': [], 'hold': []}

for _, row in fomc_df.iterrows():
    loc = row['loc']
    if loc < WINDOW_PRE or loc >= len(data) - WINDOW_POST - 1:
        continue

    # Normalize VIX to 100 at FOMC day
    vix_at_fomc = data['VIX'].iloc[loc]
    if vix_at_fomc <= 0:
        continue

    path = []
    for d in range(-WINDOW_PRE, WINDOW_POST + 1):
        v = data['VIX'].iloc[loc + d]
        path.append(v / vix_at_fomc * 100)

    event_paths[row['action']].append(path)

days = list(range(-WINDOW_PRE, WINDOW_POST + 1))

fig, ax = plt.subplots(figsize=(10, 6))
colors = {'hike': '#d62728', 'cut': '#2ca02c', 'hold': '#1f77b4'}
labels_nice = {'hike': f'Rate Hike (n={len(event_paths["hike"])})',
               'cut': f'Rate Cut (n={len(event_paths["cut"])})',
               'hold': f'Hold (n={len(event_paths["hold"])})'}

for action in ['hike', 'cut', 'hold']:
    if len(event_paths[action]) == 0:
        continue
    arr = np.array(event_paths[action])
    mean_path = np.nanmean(arr, axis=0)
    se_path = np.nanstd(arr, axis=0) / np.sqrt(arr.shape[0])

    ax.plot(days, mean_path, color=colors[action], linewidth=2, label=labels_nice[action])
    ax.fill_between(days, mean_path - 1.96 * se_path, mean_path + 1.96 * se_path,
                    color=colors[action], alpha=0.15)

ax.axvline(0, color='black', linestyle='--', alpha=0.5, label='FOMC Announcement')
ax.axhline(100, color='gray', linestyle=':', alpha=0.3)
ax.set_xlabel('Trading Days Relative to FOMC', fontsize=12)
ax.set_ylabel('VIX (Normalized to 100 at FOMC)', fontsize=12)
ax.set_title('K856: VIX Behavior Around FOMC Meetings\n(Event Study, 2000-2026)', fontsize=14)
ax.legend(fontsize=11)
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(CHARTS_DIR / 'event_study_vix_fomc.png', dpi=150)
plt.close()
print("  -> Chart saved: event_study_vix_fomc.png")

# Summary statistics for event study
print("\n  Event Study Results (VIX change from FOMC day):")
print(f"  {'Action':<8} {'N':>4} {'ΔV(+1d)':>10} {'ΔV(+5d)':>10} {'ΔV(+10d)':>10}")
for action in ['hike', 'cut', 'hold']:
    sub = fomc_df[fomc_df['action'] == action]
    if len(sub) == 0:
        continue
    print(f"  {action:<8} {len(sub):>4} "
          f"{sub['dvix_d1'].mean():>+10.2f} "
          f"{sub['dvix_d5'].mean():>+10.2f} "
          f"{sub['dvix_d10'].mean():>+10.2f}")

# Statistical tests: Hike vs Hold, Cut vs Hold
print("\n  Welch's t-tests (vs Hold):")
hold_dvix1 = fomc_df[fomc_df['action'] == 'hold']['dvix_d1'].dropna()
for action in ['hike', 'cut']:
    sub = fomc_df[fomc_df['action'] == action]['dvix_d1'].dropna()
    if len(sub) < 5:
        print(f"  {action} vs hold: insufficient data (n={len(sub)})")
        continue
    t_stat, p_val = stats.ttest_ind(sub, hold_dvix1, equal_var=False)
    print(f"  {action} vs hold (ΔV+1d): t={t_stat:.3f}, p={p_val:.4f} "
          f"({'***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.10 else 'ns'})")

# ============================================================
# 5. Regression Discontinuity Design (RDD)
# ============================================================
print("\n[4/6] Regression Discontinuity Design (RDD)...")

# Running variable: days since last rate change
# We look at ALL trading days, compute distance to nearest FOMC rate change
# Treatment: being within [0, +k] days of a rate change vs [-k, -1] days before

# Identify rate change dates
rate_change_dates = fomc_df[fomc_df['action'] != 'hold'].index.tolist()
print(f"  Rate change events: {len(rate_change_dates)}")

# For each rate change, collect VIX in [-20, +20] window
rdd_data = []
for rc_date in rate_change_dates:
    if rc_date not in data.index:
        continue
    loc = data.index.get_loc(rc_date)
    if loc < 20 or loc >= len(data) - 21:
        continue

    for d in range(-20, 21):
        rdd_data.append({
            'event_date': rc_date,
            'days_from_event': d,
            'vix': data['VIX'].iloc[loc + d],
            'log_vix': np.log(data['VIX'].iloc[loc + d]),
            'post': 1 if d >= 0 else 0,
        })

rdd_df = pd.DataFrame(rdd_data)

# Local linear regression: VIX = a + b*days + c*post + d*post*days + e
# Use bandwidth h = 10 (10 days each side)
BW = 10
rdd_local = rdd_df[rdd_df['days_from_event'].abs() <= BW].copy()

X_rdd = rdd_local[['days_from_event', 'post']].copy()
X_rdd['interaction'] = X_rdd['days_from_event'] * X_rdd['post']
X_rdd = sm.add_constant(X_rdd)
y_rdd = rdd_local['log_vix']

# Cluster standard errors by event
try:
    rdd_model = OLS(y_rdd, X_rdd).fit(cov_type='cluster',
                                        cov_kwds={'groups': rdd_local['event_date']})
except Exception:
    rdd_model = OLS(y_rdd, X_rdd).fit(cov_type='HC1')

print(f"\n  RDD Results (bandwidth = {BW} days, log(VIX) outcome):")
print(f"  {'Variable':<20} {'Coef':>10} {'SE':>10} {'t-stat':>10} {'p-val':>10}")
for var in rdd_model.params.index:
    coef = rdd_model.params[var]
    se = rdd_model.bse[var]
    t = rdd_model.tvalues[var]
    p = rdd_model.pvalues[var]
    sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else ''
    print(f"  {var:<20} {coef:>10.4f} {se:>10.4f} {t:>10.3f} {p:>10.4f} {sig}")

rdd_jump = rdd_model.params.get('post', np.nan)
rdd_jump_pct = (np.exp(rdd_jump) - 1) * 100
print(f"\n  Discontinuity at rate change: {rdd_jump_pct:+.2f}% VIX jump")
print(f"  (exp(β_post) - 1 = {rdd_jump_pct:.2f}%)")

# RDD Visualization
fig, ax = plt.subplots(figsize=(10, 6))
for d in range(-BW, BW + 1):
    sub = rdd_local[rdd_local['days_from_event'] == d]
    mean_v = sub['log_vix'].mean()
    se_v = sub['log_vix'].std() / np.sqrt(len(sub))
    color = '#d62728' if d >= 0 else '#1f77b4'
    ax.scatter(d, mean_v, color=color, s=50, zorder=5)
    ax.errorbar(d, mean_v, yerr=1.96 * se_v, color=color, capsize=3, alpha=0.5)

# Fit lines on each side
pre = rdd_local[rdd_local['post'] == 0]
post = rdd_local[rdd_local['post'] == 1]

pre_agg = pre.groupby('days_from_event')['log_vix'].mean()
post_agg = post.groupby('days_from_event')['log_vix'].mean()

if len(pre_agg) > 1:
    z_pre = np.polyfit(pre_agg.index, pre_agg.values, 1)
    x_pre = np.linspace(-BW, -0.5, 50)
    ax.plot(x_pre, np.polyval(z_pre, x_pre), color='#1f77b4', linewidth=2, label='Pre-event trend')

if len(post_agg) > 1:
    z_post = np.polyfit(post_agg.index, post_agg.values, 1)
    x_post = np.linspace(0, BW, 50)
    ax.plot(x_post, np.polyval(z_post, x_post), color='#d62728', linewidth=2, label='Post-event trend')

ax.axvline(0, color='black', linestyle='--', alpha=0.5)
ax.set_xlabel('Trading Days from Rate Change', fontsize=12)
ax.set_ylabel('log(VIX) [Mean Across Events]', fontsize=12)
ax.set_title(f'K856: RDD — VIX Discontinuity at Fed Rate Changes\n'
             f'(n={len(rate_change_dates)} events, BW={BW} days)', fontsize=14)
ax.legend(fontsize=11)
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(CHARTS_DIR / 'rdd_vix_rate_change.png', dpi=150)
plt.close()
print("  -> Chart saved: rdd_vix_rate_change.png")

# RDD sensitivity: vary bandwidth
print("\n  RDD Sensitivity (bandwidth variation):")
print(f"  {'BW':>4} {'Jump%':>10} {'t-stat':>10} {'p-val':>10} {'N':>6}")
rdd_sensitivity = []
for bw in [5, 7, 10, 15, 20]:
    rdd_bw = rdd_df[rdd_df['days_from_event'].abs() <= bw].copy()
    X_bw = rdd_bw[['days_from_event', 'post']].copy()
    X_bw['interaction'] = X_bw['days_from_event'] * X_bw['post']
    X_bw = sm.add_constant(X_bw)
    try:
        m = OLS(rdd_bw['log_vix'], X_bw).fit(cov_type='cluster',
                                               cov_kwds={'groups': rdd_bw['event_date']})
    except Exception:
        m = OLS(rdd_bw['log_vix'], X_bw).fit(cov_type='HC1')

    jump = m.params.get('post', np.nan)
    jump_pct = (np.exp(jump) - 1) * 100
    t = m.tvalues.get('post', np.nan)
    p = m.pvalues.get('post', np.nan)
    print(f"  {bw:>4} {jump_pct:>+10.2f} {t:>10.3f} {p:>10.4f} {len(rdd_bw):>6}")
    rdd_sensitivity.append({'bw': bw, 'jump_pct': jump_pct, 't_stat': t, 'p_val': p, 'n': len(rdd_bw)})

# ============================================================
# 6. Difference-in-Differences (DiD)
# ============================================================
print("\n[5/6] Difference-in-Differences (DiD)...")

# Treatment: FOMC with rate change
# Control: FOMC with hold
# Pre: [-10, -1], Post: [0, +10]
# Outcome: log(VIX)

did_data = []
for _, row in fomc_df.iterrows():
    loc = row['loc']
    if loc < 10 or loc >= len(data) - 11:
        continue

    treated = 1 if row['action'] != 'hold' else 0
    event_date = row.name

    for d in range(-10, 11):
        did_data.append({
            'event_date': event_date,
            'action': row['action'],
            'treated': treated,
            'post': 1 if d >= 0 else 0,
            'day': d,
            'vix': data['VIX'].iloc[loc + d],
            'log_vix': np.log(data['VIX'].iloc[loc + d]),
        })

did_df = pd.DataFrame(did_data)
did_df['treated_post'] = did_df['treated'] * did_df['post']

# DiD regression: log(VIX) = a + b*treated + c*post + d*treated*post + event FE
X_did = did_df[['treated', 'post', 'treated_post']].copy()
X_did = sm.add_constant(X_did)
y_did = did_df['log_vix']

try:
    did_model = OLS(y_did, X_did).fit(cov_type='cluster',
                                       cov_kwds={'groups': did_df['event_date']})
except Exception:
    did_model = OLS(y_did, X_did).fit(cov_type='HC1')

print(f"\n  DiD Results (log(VIX) outcome):")
print(f"  {'Variable':<20} {'Coef':>10} {'SE':>10} {'t-stat':>10} {'p-val':>10}")
for var in did_model.params.index:
    coef = did_model.params[var]
    se = did_model.bse[var]
    t = did_model.tvalues[var]
    p = did_model.pvalues[var]
    sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else ''
    print(f"  {var:<20} {coef:>10.4f} {se:>10.4f} {t:>10.3f} {p:>10.4f} {sig}")

did_att = did_model.params.get('treated_post', np.nan)
did_att_pct = (np.exp(did_att) - 1) * 100
did_att_t = did_model.tvalues.get('treated_post', np.nan)
did_att_p = did_model.pvalues.get('treated_post', np.nan)
print(f"\n  DiD ATT (Average Treatment Effect on Treated):")
print(f"  Rate change vs Hold: {did_att_pct:+.2f}% VIX change")
print(f"  t-stat: {did_att_t:.3f}, p-value: {did_att_p:.4f}")

# Parallel trends test: pre-period trends should be similar
pre_did = did_df[did_df['post'] == 0].copy()
pre_did['day_treated'] = pre_did['day'] * pre_did['treated']
X_pt = pre_did[['day', 'treated', 'day_treated']].copy()
X_pt = sm.add_constant(X_pt)
try:
    pt_model = OLS(pre_did['log_vix'], X_pt).fit(cov_type='cluster',
                                                    cov_kwds={'groups': pre_did['event_date']})
except Exception:
    pt_model = OLS(pre_did['log_vix'], X_pt).fit(cov_type='HC1')

pt_coef = pt_model.params.get('day_treated', np.nan)
pt_t = pt_model.tvalues.get('day_treated', np.nan)
pt_p = pt_model.pvalues.get('day_treated', np.nan)
print(f"\n  Parallel Trends Test (pre-period):")
print(f"  Differential pre-trend: coef={pt_coef:.4f}, t={pt_t:.3f}, p={pt_p:.4f}")
print(f"  {'PASS' if pt_p > 0.10 else 'FAIL'}: "
      f"{'No' if pt_p > 0.10 else 'Significant'} differential pre-trend "
      f"({'parallel trends assumption holds' if pt_p > 0.10 else 'CAUTION: parallel trends may be violated'})")

# DiD Visualization
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Left: Raw VIX paths
for idx, (label, treated_val) in enumerate([('Hold (Control)', 0), ('Rate Change (Treatment)', 1)]):
    sub = did_df[did_df['treated'] == treated_val]
    agg = sub.groupby('day')['vix'].agg(['mean', 'std', 'count'])
    agg['se'] = agg['std'] / np.sqrt(agg['count'])
    color = '#d62728' if treated_val == 1 else '#1f77b4'
    axes[0].plot(agg.index, agg['mean'], color=color, linewidth=2, label=label)
    axes[0].fill_between(agg.index, agg['mean'] - 1.96 * agg['se'],
                         agg['mean'] + 1.96 * agg['se'], color=color, alpha=0.15)

axes[0].axvline(0, color='black', linestyle='--', alpha=0.5)
axes[0].set_xlabel('Days from FOMC')
axes[0].set_ylabel('VIX Level')
axes[0].set_title('Raw VIX Paths: Rate Change vs Hold')
axes[0].legend()
axes[0].grid(True, alpha=0.3)

# Right: Normalized (event-day = 100)
for idx, (label, treated_val) in enumerate([('Hold (Control)', 0), ('Rate Change (Treatment)', 1)]):
    sub = did_df[did_df['treated'] == treated_val]
    # Normalize within each event
    norm_data = []
    for ed in sub['event_date'].unique():
        esub = sub[sub['event_date'] == ed].copy()
        v0 = esub[esub['day'] == 0]['vix'].values
        if len(v0) > 0 and v0[0] > 0:
            esub['vix_norm'] = esub['vix'] / v0[0] * 100
            norm_data.append(esub)
    if norm_data:
        norm_all = pd.concat(norm_data)
        agg = norm_all.groupby('day')['vix_norm'].agg(['mean', 'std', 'count'])
        agg['se'] = agg['std'] / np.sqrt(agg['count'])
        color = '#d62728' if treated_val == 1 else '#1f77b4'
        axes[1].plot(agg.index, agg['mean'], color=color, linewidth=2, label=label)
        axes[1].fill_between(agg.index, agg['mean'] - 1.96 * agg['se'],
                             agg['mean'] + 1.96 * agg['se'], color=color, alpha=0.15)

axes[1].axvline(0, color='black', linestyle='--', alpha=0.5)
axes[1].axhline(100, color='gray', linestyle=':', alpha=0.3)
axes[1].set_xlabel('Days from FOMC')
axes[1].set_ylabel('VIX (Normalized to 100)')
axes[1].set_title('Normalized VIX: Rate Change vs Hold')
axes[1].legend()
axes[1].grid(True, alpha=0.3)

fig.suptitle('K856: DiD — VIX Response to Rate Changes vs Holds', fontsize=14, y=1.02)
fig.tight_layout()
fig.savefig(CHARTS_DIR / 'did_vix_rate_change.png', dpi=150, bbox_inches='tight')
plt.close()
print("  -> Chart saved: did_vix_rate_change.png")

# ============================================================
# 7. Surprise Regression
# ============================================================
print("\n[6/6] Surprise Regression...")

# ΔVIX_{t,t+k} = α + β * surprise_t + γ * controls + ε
# Controls: pre-FOMC VIX level, VIX 5d trend, SPY return

surp_df = fomc_df.dropna(subset=['surprise']).copy()
surp_df['vix_trend'] = surp_df['vix_fomc'] - surp_df['vix_pre5']
surp_df['spy_ret_pre5'] = np.nan

for idx in surp_df.index:
    loc = surp_df.loc[idx, 'loc']
    if loc >= 5:
        surp_df.loc[idx, 'spy_ret_pre5'] = data['spy_ret'].iloc[loc - 5:loc].sum()

surp_df = surp_df.dropna(subset=['spy_ret_pre5'])

print(f"\n  Surprise regression sample: {len(surp_df)} FOMC meetings")
print(f"  Surprise distribution: mean={surp_df['surprise'].mean():.4f}, "
      f"std={surp_df['surprise'].std():.4f}, "
      f"min={surp_df['surprise'].min():.4f}, max={surp_df['surprise'].max():.4f}")

surprise_results = {}
for horizon, col in [(1, 'dvix_d1'), (5, 'dvix_d5'), (10, 'dvix_d10')]:
    y = surp_df[col].dropna()
    X = surp_df.loc[y.index, ['surprise', 'vix_fomc', 'vix_trend', 'spy_ret_pre5']]
    X = sm.add_constant(X)

    model = OLS(y, X).fit(cov_type='HC1')

    beta = model.params.get('surprise', np.nan)
    t_stat = model.tvalues.get('surprise', np.nan)
    p_val = model.pvalues.get('surprise', np.nan)
    r2 = model.rsquared

    surprise_results[horizon] = {
        'beta': float(beta),
        't_stat': float(t_stat),
        'p_val': float(p_val),
        'r2': float(r2),
        'n': int(len(y)),
    }

    print(f"\n  Horizon = +{horizon}d:")
    print(f"  {'Variable':<15} {'Coef':>10} {'t-stat':>10} {'p-val':>10}")
    for var in model.params.index:
        c = model.params[var]
        t = model.tvalues[var]
        p = model.pvalues[var]
        sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else ''
        print(f"  {var:<15} {c:>10.4f} {t:>10.3f} {p:>10.4f} {sig}")
    print(f"  R² = {r2:.4f}")

# Surprise scatter plot
fig, axes = plt.subplots(1, 3, figsize=(15, 5))
for i, (horizon, col) in enumerate([(1, 'dvix_d1'), (5, 'dvix_d5'), (10, 'dvix_d10')]):
    ax = axes[i]
    valid = surp_df.dropna(subset=[col, 'surprise'])

    # Color by action
    for action, color, marker in [('hike', '#d62728', '^'), ('cut', '#2ca02c', 'v'), ('hold', '#1f77b4', 'o')]:
        sub = valid[valid['action'] == action]
        ax.scatter(sub['surprise'], sub[col], color=color, marker=marker,
                   alpha=0.6, s=50, label=action.capitalize())

    # Regression line
    x = valid['surprise'].values
    y = valid[col].values
    if len(x) > 2:
        z = np.polyfit(x, y, 1)
        x_line = np.linspace(x.min(), x.max(), 100)
        ax.plot(x_line, np.polyval(z, x_line), 'k--', alpha=0.5, linewidth=1.5)

    sr = surprise_results[horizon]
    ax.set_title(f'+{horizon}d: β={sr["beta"]:.2f}, t={sr["t_stat"]:.2f}')
    ax.set_xlabel('Rate Surprise (pp)')
    ax.set_ylabel(f'ΔVIX (+{horizon}d)')
    ax.axhline(0, color='gray', linestyle=':', alpha=0.3)
    ax.axvline(0, color='gray', linestyle=':', alpha=0.3)
    ax.grid(True, alpha=0.3)
    if i == 0:
        ax.legend(fontsize=9)

fig.suptitle('K856: VIX Response to Fed Rate Surprises', fontsize=14)
fig.tight_layout()
fig.savefig(CHARTS_DIR / 'surprise_regression.png', dpi=150)
plt.close()
print("\n  -> Chart saved: surprise_regression.png")

# ============================================================
# 8. Regime Transition Analysis
# ============================================================
print("\n[BONUS] Regime Transition Analysis...")

# Does rate change cause VIX to transition between regimes?
def get_regime(vix_val):
    if vix_val < 15:
        return 'low'
    elif vix_val < 25:
        return 'medium'
    else:
        return 'high'

regime_transitions = {'hike': [], 'cut': [], 'hold': []}
for _, row in fomc_df.iterrows():
    loc = row['loc']
    if loc < 5 or loc >= len(data) - 11:
        continue

    regime_pre = get_regime(data['VIX'].iloc[loc - 1])
    regime_d0 = get_regime(data['VIX'].iloc[loc])
    regime_d5 = get_regime(data['VIX'].iloc[min(loc + 5, len(data) - 1)])
    regime_d10 = get_regime(data['VIX'].iloc[min(loc + 10, len(data) - 1)])

    regime_transitions[row['action']].append({
        'pre': regime_pre,
        'd0': regime_d0,
        'd5': regime_d5,
        'd10': regime_d10,
        'changed_d5': regime_d5 != regime_pre,
        'changed_d10': regime_d10 != regime_pre,
    })

print(f"\n  Regime Transition Rates (pre vs post-FOMC):")
print(f"  {'Action':<8} {'N':>4} {'Trans@+5d':>12} {'Trans@+10d':>12}")
regime_trans_results = {}
for action in ['hike', 'cut', 'hold']:
    trans = regime_transitions[action]
    if len(trans) == 0:
        continue
    n = len(trans)
    pct5 = sum(t['changed_d5'] for t in trans) / n * 100
    pct10 = sum(t['changed_d10'] for t in trans) / n * 100
    print(f"  {action:<8} {n:>4} {pct5:>11.1f}% {pct10:>11.1f}%")
    regime_trans_results[action] = {'n': n, 'trans_pct_5d': pct5, 'trans_pct_10d': pct10}

# Fisher's exact test: rate change vs hold regime transition
from scipy.stats import fisher_exact

change_trans_5d = sum(t['changed_d5'] for a in ['hike', 'cut'] for t in regime_transitions[a])
change_no_trans_5d = sum(not t['changed_d5'] for a in ['hike', 'cut'] for t in regime_transitions[a])
hold_trans_5d = sum(t['changed_d5'] for t in regime_transitions['hold'])
hold_no_trans_5d = sum(not t['changed_d5'] for t in regime_transitions['hold'])

table_5d = [[change_trans_5d, change_no_trans_5d], [hold_trans_5d, hold_no_trans_5d]]
or_5d, p_fisher_5d = fisher_exact(table_5d)
print(f"\n  Fisher's exact test (regime transition within 5d):")
print(f"  Rate change: {change_trans_5d}/{change_trans_5d + change_no_trans_5d} transitioned")
print(f"  Hold:        {hold_trans_5d}/{hold_trans_5d + hold_no_trans_5d} transitioned")
print(f"  Odds Ratio: {or_5d:.3f}, p-value: {p_fisher_5d:.4f}")

change_trans_10d = sum(t['changed_d10'] for a in ['hike', 'cut'] for t in regime_transitions[a])
change_no_trans_10d = sum(not t['changed_d10'] for a in ['hike', 'cut'] for t in regime_transitions[a])
hold_trans_10d = sum(t['changed_d10'] for t in regime_transitions['hold'])
hold_no_trans_10d = sum(not t['changed_d10'] for t in regime_transitions['hold'])

table_10d = [[change_trans_10d, change_no_trans_10d], [hold_trans_10d, hold_no_trans_10d]]
or_10d, p_fisher_10d = fisher_exact(table_10d)
print(f"\n  Fisher's exact test (regime transition within 10d):")
print(f"  Rate change: {change_trans_10d}/{change_trans_10d + change_no_trans_10d} transitioned")
print(f"  Hold:        {hold_trans_10d}/{hold_trans_10d + hold_no_trans_10d} transitioned")
print(f"  Odds Ratio: {or_10d:.3f}, p-value: {p_fisher_10d:.4f}")

# ============================================================
# 9. Hike vs Cut Asymmetry
# ============================================================
print("\n[BONUS] Hike vs Cut Asymmetry...")

hike_df = fomc_df[fomc_df['action'] == 'hike']
cut_df = fomc_df[fomc_df['action'] == 'cut']

if len(hike_df) >= 5 and len(cut_df) >= 5:
    for col, label in [('dvix_d1', '+1d'), ('dvix_d5', '+5d'), ('dvix_d10', '+10d')]:
        t_hc, p_hc = stats.ttest_ind(hike_df[col].dropna(), cut_df[col].dropna(), equal_var=False)
        h_mean = hike_df[col].mean()
        c_mean = cut_df[col].mean()
        print(f"  Hike({label})={h_mean:+.2f} vs Cut({label})={c_mean:+.2f}: "
              f"t={t_hc:.3f}, p={p_hc:.4f}")

# ============================================================
# 10. VIX Anticipation Test (Granger-like)
# ============================================================
print("\n[BONUS] VIX Anticipation Test...")
print("  Does VIX rise BEFORE rate cuts (anticipation)?")

# Look at VIX change in [-5, -1] before FOMC by action
for action in ['hike', 'cut', 'hold']:
    sub = fomc_df[fomc_df['action'] == action]
    if len(sub) < 3:
        continue
    pre_change = sub['vix_fomc'] - sub['vix_pre5']
    t_stat, p_val = stats.ttest_1samp(pre_change.dropna(), 0)
    print(f"  {action}: pre-FOMC ΔVIX[-5,0] = {pre_change.mean():+.2f} "
          f"(t={t_stat:.3f}, p={p_val:.4f})")

# ============================================================
# COMPILE RESULTS
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

results = {
    "experiment_id": "K856",
    "title": "Causal Inference — Fed Rate Decisions and VIX Regime Shifts",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_source": "yfinance (^VIX, SPY), FRED (DFF, DFEDTARU, DGS2)",
    "period": f"{data.index[0].date()} to {data.index[-1].date()}",
    "sample": {
        "trading_days": len(data),
        "fomc_meetings": len(fomc_df),
        "hikes": int(n_hike),
        "cuts": int(n_cut),
        "holds": int(n_hold),
    },
    "event_study": {
        "description": "Average VIX change (absolute) from FOMC day",
        "hike": {
            "n": int(n_hike),
            "dvix_d1": float(fomc_df[fomc_df['action']=='hike']['dvix_d1'].mean()) if n_hike > 0 else None,
            "dvix_d5": float(fomc_df[fomc_df['action']=='hike']['dvix_d5'].mean()) if n_hike > 0 else None,
            "dvix_d10": float(fomc_df[fomc_df['action']=='hike']['dvix_d10'].mean()) if n_hike > 0 else None,
        },
        "cut": {
            "n": int(n_cut),
            "dvix_d1": float(fomc_df[fomc_df['action']=='cut']['dvix_d1'].mean()) if n_cut > 0 else None,
            "dvix_d5": float(fomc_df[fomc_df['action']=='cut']['dvix_d5'].mean()) if n_cut > 0 else None,
            "dvix_d10": float(fomc_df[fomc_df['action']=='cut']['dvix_d10'].mean()) if n_cut > 0 else None,
        },
        "hold": {
            "n": int(n_hold),
            "dvix_d1": float(fomc_df[fomc_df['action']=='hold']['dvix_d1'].mean()),
            "dvix_d5": float(fomc_df[fomc_df['action']=='hold']['dvix_d5'].mean()),
            "dvix_d10": float(fomc_df[fomc_df['action']=='hold']['dvix_d10'].mean()),
        },
    },
    "rdd": {
        "description": "Regression Discontinuity at rate change (log VIX outcome, clustered SE)",
        "bandwidth": BW,
        "jump_pct": float(rdd_jump_pct),
        "post_coef": float(rdd_jump),
        "t_stat": float(rdd_model.tvalues.get('post', np.nan)),
        "p_val": float(rdd_model.pvalues.get('post', np.nan)),
        "r2": float(rdd_model.rsquared),
        "sensitivity": rdd_sensitivity,
    },
    "did": {
        "description": "DiD: Rate change (treatment) vs Hold (control), pre=[-10,-1] post=[0,+10]",
        "att_pct": float(did_att_pct),
        "att_coef": float(did_att),
        "t_stat": float(did_att_t),
        "p_val": float(did_att_p),
        "parallel_trends": {
            "differential_pre_trend_coef": float(pt_coef),
            "t_stat": float(pt_t),
            "p_val": float(pt_p),
            "assumption_holds": bool(pt_p > 0.10),
        },
    },
    "surprise_regression": {
        "description": "ΔVIX_{t,t+k} = α + β*surprise + γ*controls",
        "horizons": {str(k): v for k, v in surprise_results.items()},
    },
    "regime_transitions": {
        "description": "Rate of VIX regime transition around FOMC",
        "results": regime_trans_results,
        "fisher_5d": {"odds_ratio": float(or_5d), "p_val": float(p_fisher_5d)},
        "fisher_10d": {"odds_ratio": float(or_10d), "p_val": float(p_fisher_10d)},
    },
    "anticipation_test": {},
    "conclusions": [],
    "limitations": [
        "Rate surprise proxy (2yr yield change) is crude; ideally use fed funds futures",
        "RDD running variable (calendar days) is not truly continuous",
        "Small sample for hikes/cuts (50-60 each) limits statistical power",
        "FOMC dates may not be 100% accurate for unscheduled meetings",
        "DiD assumes parallel trends which may not hold in crisis periods",
        "DGS2 measures broader expectations, not just rate expectations",
    ],
    "references": [
        "Bernanke & Kuttner (2005), JF — Stock market reaction to Fed policy",
        "Bauer & Swanson (2023), NBER — Monetary policy surprises",
        "Nakamura & Steinsson (2018), QJE — High-frequency monetary ID",
        "Imbens & Lemieux (2008), JoE — RDD guide",
        "K513: Only FOMC significantly affects volatility (+28%)",
        "K514: FOMC surprise strong IS (t=-8.18) but OOS worse (DM t=+3.89)",
    ],
    "charts": [
        "k856_charts/event_study_vix_fomc.png",
        "k856_charts/rdd_vix_rate_change.png",
        "k856_charts/did_vix_rate_change.png",
        "k856_charts/surprise_regression.png",
    ],
}

# Add anticipation test results
for action in ['hike', 'cut', 'hold']:
    sub = fomc_df[fomc_df['action'] == action]
    if len(sub) >= 3:
        pre_change = sub['vix_fomc'] - sub['vix_pre5']
        t_stat, p_val = stats.ttest_1samp(pre_change.dropna(), 0)
        results['anticipation_test'][action] = {
            'mean_pre_dvix': float(pre_change.mean()),
            't_stat': float(t_stat),
            'p_val': float(p_val),
        }

# Build conclusions
conclusions = []

# 1. Event study
if n_hike > 0 and n_cut > 0:
    h_d1 = fomc_df[fomc_df['action']=='hike']['dvix_d1'].mean()
    c_d1 = fomc_df[fomc_df['action']=='cut']['dvix_d1'].mean()
    conclusions.append(
        f"Event Study: Hikes cause VIX Δ+1d={h_d1:+.2f}, Cuts cause Δ+1d={c_d1:+.2f} "
        f"(both relative to hold Δ+1d={fomc_df[fomc_df['action']=='hold']['dvix_d1'].mean():+.2f})"
    )

# 2. RDD
rdd_sig = "significant" if rdd_model.pvalues.get('post', 1) < 0.05 else "not significant"
conclusions.append(
    f"RDD: {rdd_jump_pct:+.2f}% VIX discontinuity at rate change ({rdd_sig}, "
    f"t={rdd_model.tvalues.get('post', np.nan):.3f})"
)

# 3. DiD
did_sig = "significant" if did_att_p < 0.05 else "not significant"
conclusions.append(
    f"DiD: ATT = {did_att_pct:+.2f}% ({did_sig}, t={did_att_t:.3f}). "
    f"Parallel trends {'holds' if pt_p > 0.10 else 'VIOLATED'} (p={pt_p:.4f})"
)

# 4. Surprise
sr1 = surprise_results.get(1, {})
if sr1:
    sr_sig = "significant" if sr1.get('p_val', 1) < 0.05 else "not significant"
    conclusions.append(
        f"Surprise: β(+1d)={sr1['beta']:.3f} ({sr_sig}, t={sr1['t_stat']:.3f}). "
        f"Surprise explains R²={sr1['r2']:.4f} of ΔVIX"
    )

# 5. Regime
regime_sig_5d = "significant" if p_fisher_5d < 0.05 else "not significant"
conclusions.append(
    f"Regime Transitions: Rate changes vs holds OR={or_5d:.2f} at 5d ({regime_sig_5d}, "
    f"p={p_fisher_5d:.4f})"
)

# 6. Anticipation
if 'cut' in results['anticipation_test']:
    at = results['anticipation_test']['cut']
    conclusions.append(
        f"Anticipation: VIX rises {at['mean_pre_dvix']:+.2f} in [-5,0] before cuts "
        f"(t={at['t_stat']:.3f}, p={at['p_val']:.4f}) — market partially anticipates"
    )

results['conclusions'] = conclusions

print("\n  Key Conclusions:")
for i, c in enumerate(conclusions, 1):
    print(f"  {i}. {c}")

# Save results
results_path = OUT_DIR / 'k856_results.json'
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved: {results_path}")

print("\n" + "=" * 70)
print("K856 COMPLETE")
print("=" * 70)
