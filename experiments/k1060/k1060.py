"""
K1060: Individual Taiwan Stock Earnings Announcement Volatility (EAV)
======================================================================

Research Questions:
1. Do individual Taiwan stocks show earnings announcement volatility (EAV)?
2. If yes, why doesn't it transmit to 0050.TW ETF (K1059 NULL puzzle)?
3. Is EAV uniform across sectors (tech / financial / traditional)?

Hypotheses:
- H1 (Literature baseline): day-0 vol > non-event vol (ratio > 1, t > 0)
- H2 (K1059 extension): If H1 true but 0050.TW NULL -> diversification real
- H3 (Cross-sectoral): EAV strength differs by sector (tech > fin?)

Data Sources:
- 財報公告日.txt (Big5, ~158K records, 1986-2025)
- yfinance daily prices for 10 Taiwan stocks (2010-2025)

References (literature-first principle):
- Patell & Wolfson (1984): vol increase on earnings days (individual stocks)
- Beaver (1968): earnings announcements raise vol + volume
- Savor & Wilson (2016): earnings as systematic risk events
- Ball & Kothari (1991): event studies on earnings
- K1059: TSMC -> 0050.TW NULL (event-study ratio = 1.007)
- K1058: A4f on 0050.TW mixed
- K1050: SPY earnings season uniform improvement

Notes:
- Individual stocks do NOT use clean_tw50_data (that's ETF-specific)
- Random seed: 42
- All numbers must match JSON output (K1016 discipline)
"""

import numpy as np
import pandas as pd
import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import yfinance as yf

np.random.seed(42)
warnings.filterwarnings('ignore')

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
START_TIME = time.time()

# Configuration
START_DATE = '2010-01-01'
END_DATE = '2025-12-31'
ROLLING_WINDOW = 60     # trailing days for baseline r^2 mean
EVENT_WINDOW = 5        # +/- 5 days around announcement
BOOTSTRAP_REPS = 2000

STOCKS = {
    '2330.TW': ('TSMC',             'Tech'),
    '2454.TW': ('MediaTek',         'Tech'),
    '2317.TW': ('Hon Hai',          'Tech'),
    '2308.TW': ('Delta',            'Tech'),
    '2303.TW': ('UMC',              'Tech'),
    '2412.TW': ('Chunghwa Telecom', 'Telecom'),
    '2882.TW': ('Cathay Holdings',  'Financial'),
    '2891.TW': ('CTBC Financial',   'Financial'),
    '2881.TW': ('Fubon Financial',  'Financial'),
    '2002.TW': ('China Steel',      'Traditional'),
}

print("=" * 70)
print("K1060: Individual Taiwan Stock EAV -- 10-stock Event Study")
print("=" * 70)

###############################################################################
# Part 0: Load earnings announcement data
###############################################################################
print("\n[Part 0] Loading earnings announcement data (Big5)...")

with open(DATA_FILE, 'rb') as f:
    raw_text = f.read().decode('big5', errors='replace')

lines = raw_text.strip().split('\n')
records = []
for line in lines[1:]:
    parts = line.strip().split('\t')
    if len(parts) >= 4:
        code = parts[0].strip()
        name = parts[1].strip()
        ym = parts[2].strip()
        date_str = parts[3].strip()
        if date_str:
            try:
                dt = pd.Timestamp(date_str.replace('/', '-'))
                records.append({'code': code, 'name': name, 'ym': ym, 'date': dt})
            except Exception:
                pass

ea_df = pd.DataFrame(records)
print(f"Total announcement records parsed: {len(ea_df):,}")
print(f"Unique companies: {ea_df['code'].nunique():,}")

# Pre-filter to sample stocks
stock_codes = [k.replace('.TW', '') for k in STOCKS.keys()]
ea_sample = ea_df[ea_df['code'].isin(stock_codes)].copy()
ea_sample = ea_sample[(ea_sample['date'] >= START_DATE) & (ea_sample['date'] <= END_DATE)]
print(f"Announcements for 10 sample stocks in {START_DATE}~{END_DATE}: {len(ea_sample)}")

###############################################################################
# Part 1: Download price data and compute r^2
###############################################################################
print("\n[Part 1] Downloading price data for 10 stocks...")

stock_data = {}
for ticker, (name, sector) in STOCKS.items():
    print(f"  Downloading {ticker} ({name}, {sector})...", end=' ')
    try:
        df = yf.download(ticker, start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
        if df is None or len(df) == 0:
            print("EMPTY")
            continue
        # Flatten possible multi-index columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df['Close'].astype(float)
        ret = np.log(close / close.shift(1)).dropna()
        r2 = ret ** 2
        stock_data[ticker] = {
            'name': name,
            'sector': sector,
            'close': close,
            'ret': ret,
            'r2': r2,
        }
        print(f"OK N={len(ret):,}")
    except Exception as exc:
        print(f"FAIL: {exc}")

print(f"\nStocks loaded successfully: {len(stock_data)}/{len(STOCKS)}")

###############################################################################
# Part 2: Event study per stock
###############################################################################
print("\n[Part 2] Per-stock event study...")

per_stock_results = {}
event_window_curves = {}  # ticker -> array of length 2*EVENT_WINDOW+1

for ticker, info in stock_data.items():
    code = ticker.replace('.TW', '')
    dates_ea = ea_sample.loc[ea_sample['code'] == code, 'date'].sort_values().unique()
    dates_ea = pd.DatetimeIndex(dates_ea)

    r2 = info['r2']
    ret = info['ret']

    # Map announcement date -> next available trading day (if announcement is non-trading)
    trading_days = r2.index
    mapped = []
    for d in dates_ea:
        # Use searchsorted to find next trading day >= d
        pos = trading_days.searchsorted(pd.Timestamp(d))
        if pos < len(trading_days):
            mapped.append(trading_days[pos])
    mapped = pd.DatetimeIndex(sorted(set(mapped)))
    n_events = len(mapped)

    # Rolling 60-day mean of r^2 (trailing; shifted by 1 to avoid contamination)
    r2_roll_mean = r2.rolling(ROLLING_WINDOW).mean().shift(1)

    # Abnormal volatility series (r^2 / trailing mean)
    av = r2 / r2_roll_mean
    av = av.replace([np.inf, -np.inf], np.nan)

    # Taiwan earnings are typically announced AFTER market close -> T+1 reaction
    # Build T+1 event dates (next trading day after mapped[t])
    event_positions_base = [trading_days.get_loc(d) for d in mapped if d in trading_days]
    event_positions_t1 = [p + 1 for p in event_positions_base if p + 1 < len(trading_days)]
    mapped_t1 = pd.DatetimeIndex([trading_days[p] for p in event_positions_t1])

    # Event-day (t=0) stats
    event_r2 = r2.reindex(mapped).dropna()
    event_av = av.reindex(mapped).dropna()

    # T+1 event-day stats (Taiwan-specific)
    event_r2_t1 = r2.reindex(mapped_t1).dropna()

    # Non-event window: exclude [-EVENT_WINDOW, +EVENT_WINDOW] around every event
    exclusion = set()
    event_positions = event_positions_base
    for pos in event_positions:
        for k in range(-EVENT_WINDOW, EVENT_WINDOW + 1):
            if 0 <= pos + k < len(trading_days):
                exclusion.add(trading_days[pos + k])
    non_event_mask = ~r2.index.isin(exclusion)
    non_event_r2 = r2[non_event_mask]
    non_event_av = av[non_event_mask].dropna()

    # Core statistics (T+0)
    r2_event_mean = float(event_r2.mean()) if len(event_r2) else np.nan
    r2_nonevent_mean = float(non_event_r2.mean()) if len(non_event_r2) else np.nan
    ratio = r2_event_mean / r2_nonevent_mean if r2_nonevent_mean else np.nan

    # Core statistics (T+1)
    r2_event_mean_t1 = float(event_r2_t1.mean()) if len(event_r2_t1) else np.nan
    ratio_t1 = r2_event_mean_t1 / r2_nonevent_mean if r2_nonevent_mean else np.nan
    if len(event_r2_t1) >= 5 and len(non_event_r2) >= 30:
        t_stat_t1, p_val_t1 = stats.ttest_ind(event_r2_t1.values,
                                              non_event_r2.values,
                                              equal_var=False)
    else:
        t_stat_t1, p_val_t1 = np.nan, np.nan

    # Welch t-test on r^2 (event vs non-event) T+0
    if len(event_r2) >= 5 and len(non_event_r2) >= 30:
        t_stat, p_val = stats.ttest_ind(event_r2.values, non_event_r2.values,
                                        equal_var=False)
    else:
        t_stat, p_val = np.nan, np.nan

    # Bootstrap CI for ratio (paired-independent samples)
    rng = np.random.default_rng(42)
    boot_ratios = []
    nev = event_r2.values
    nne = non_event_r2.values
    if len(nev) >= 5 and len(nne) >= 100:
        for _ in range(BOOTSTRAP_REPS):
            s1 = rng.choice(nev, size=len(nev), replace=True)
            s2 = rng.choice(nne, size=len(nne), replace=True)
            m2 = s2.mean()
            if m2 > 0:
                boot_ratios.append(s1.mean() / m2)
        boot_ratios = np.array(boot_ratios)
        ci_low = float(np.percentile(boot_ratios, 2.5))
        ci_high = float(np.percentile(boot_ratios, 97.5))
        boot_p = float((boot_ratios <= 1.0).mean())  # one-sided p(ratio<=1)
    else:
        ci_low, ci_high, boot_p = np.nan, np.nan, np.nan

    # AV event-day stat (alternative: event AV > 1?)
    av_event_mean = float(event_av.mean()) if len(event_av) else np.nan
    av_nonevent_mean = float(non_event_av.mean()) if len(non_event_av) else np.nan

    # Event window curve: mean r^2 at each offset d in [-EVENT_WINDOW, +EVENT_WINDOW]
    curve = np.zeros(2 * EVENT_WINDOW + 1)
    counts = np.zeros(2 * EVENT_WINDOW + 1)
    for ev_date in mapped:
        if ev_date not in trading_days:
            continue
        pos = trading_days.get_loc(ev_date)
        for idx, k in enumerate(range(-EVENT_WINDOW, EVENT_WINDOW + 1)):
            if 0 <= pos + k < len(trading_days):
                val = r2.iloc[pos + k]
                if not np.isnan(val):
                    curve[idx] += val
                    counts[idx] += 1
    curve = curve / np.maximum(counts, 1)
    # Normalize curve by non-event mean for easier cross-stock compare
    curve_ratio = curve / r2_nonevent_mean if r2_nonevent_mean else curve
    event_window_curves[ticker] = curve_ratio.tolist()

    # Cumulative abnormal vol (CAV) over [-EVENT_WINDOW, +EVENT_WINDOW]
    cav = float(np.nansum(curve_ratio - 1.0))

    per_stock_results[ticker] = {
        'name': info['name'],
        'sector': info['sector'],
        'n_events': int(n_events),
        'n_trading_days': int(len(r2)),
        'r2_event_mean': r2_event_mean,
        'r2_nonevent_mean': r2_nonevent_mean,
        'ratio': float(ratio) if not np.isnan(ratio) else None,
        'ratio_t1': float(ratio_t1) if not np.isnan(ratio_t1) else None,
        't_stat_t1': float(t_stat_t1) if not np.isnan(t_stat_t1) else None,
        'p_value_t1': float(p_val_t1) if not np.isnan(p_val_t1) else None,
        'av_event_mean': av_event_mean,
        'av_nonevent_mean': av_nonevent_mean,
        't_stat': float(t_stat) if not np.isnan(t_stat) else None,
        'p_value': float(p_val) if not np.isnan(p_val) else None,
        'bootstrap_ci_low': ci_low if not np.isnan(ci_low) else None,
        'bootstrap_ci_high': ci_high if not np.isnan(ci_high) else None,
        'bootstrap_p_ratio_le_1': boot_p if not np.isnan(boot_p) else None,
        'cav_11day': cav,
        'event_window_ratio_curve': curve_ratio.tolist(),
    }

    print(f"  {ticker} {info['name']:20s} [{info['sector']:11s}] "
          f"N_ev={n_events:3d} T0_ratio={ratio:.3f} t={t_stat:+.2f} | "
          f"T1_ratio={ratio_t1:.3f} t={t_stat_t1:+.2f} CAV={cav:+.3f}")

###############################################################################
# Part 3: Cross-stock & sectoral analysis
###############################################################################
print("\n[Part 3] Cross-stock summary...")

# Aggregate by sector
sector_rows = []
for ticker, res in per_stock_results.items():
    sector_rows.append({
        'ticker': ticker,
        'name': res['name'],
        'sector': res['sector'],
        'ratio': res['ratio'],
        'ratio_t1': res['ratio_t1'],
        't_stat': res['t_stat'],
        't_stat_t1': res['t_stat_t1'],
        'cav': res['cav_11day'],
        'n_events': res['n_events'],
    })
summary_df = pd.DataFrame(sector_rows)
print(summary_df.to_string(index=False))

sector_agg = summary_df.groupby('sector').agg(
    n_stocks=('ticker', 'count'),
    mean_ratio=('ratio', 'mean'),
    median_ratio=('ratio', 'median'),
    mean_ratio_t1=('ratio_t1', 'mean'),
    mean_t=('t_stat', 'mean'),
    mean_t_t1=('t_stat_t1', 'mean'),
    mean_cav=('cav', 'mean'),
).reset_index()
print("\nSector aggregates:")
print(sector_agg.to_string(index=False))

# Overall ratio across all 10 stocks (equal-weighted cross-section average)
ratios = summary_df['ratio'].dropna().values
ratios_t1 = summary_df['ratio_t1'].dropna().values
t_stats = summary_df['t_stat'].dropna().values
t_stats_t1 = summary_df['t_stat_t1'].dropna().values
positives = int(np.sum(ratios > 1.0))
positives_t1 = int(np.sum(ratios_t1 > 1.0))
n_total = len(ratios)

# Binomial test: ratio > 1 for H1. Null: ratio==1 -> p=0.5 under no effect
try:
    from scipy.stats import binomtest
    bt = binomtest(positives, n_total, p=0.5, alternative='greater')
    binom_p = float(bt.pvalue)
except Exception:
    binom_p = float(stats.binom.sf(positives - 1, n_total, 0.5))

overall_mean_ratio = float(np.mean(ratios))
overall_mean_ratio_t1 = float(np.mean(ratios_t1))
overall_mean_t = float(np.mean(t_stats))
overall_mean_t_t1 = float(np.mean(t_stats_t1))

# One-sample t-test: mean(ratio) > 1?
if n_total >= 3:
    one_t, one_p = stats.ttest_1samp(ratios, popmean=1.0, alternative='greater')
    one_t_t1, one_p_t1 = stats.ttest_1samp(ratios_t1, popmean=1.0, alternative='greater')
else:
    one_t, one_p = np.nan, np.nan
    one_t_t1, one_p_t1 = np.nan, np.nan

# T+1 binomial
try:
    bt_t1 = binomtest(positives_t1, n_total, p=0.5, alternative='greater')
    binom_p_t1 = float(bt_t1.pvalue)
except Exception:
    binom_p_t1 = float(stats.binom.sf(positives_t1 - 1, n_total, 0.5))

print(f"\nOverall T+0: mean ratio={overall_mean_ratio:.4f}, mean t={overall_mean_t:+.3f}, "
      f"{positives}/{n_total} stocks>1, binom p={binom_p:.4f}")
print(f"Overall T+1: mean ratio={overall_mean_ratio_t1:.4f}, mean t={overall_mean_t_t1:+.3f}, "
      f"{positives_t1}/{n_total} stocks>1, binom p={binom_p_t1:.4f}")

###############################################################################
# Part 4: Hypothesis tests
###############################################################################
hypotheses = {
    'H1_literature_baseline': {
        'description': 'Individual stocks day-0 r^2 > non-event r^2 (ratio > 1)',
        'overall_mean_ratio': overall_mean_ratio,
        'positives_vs_total': f"{positives}/{n_total}",
        'binom_p_one_sided': binom_p,
        'one_sample_t': float(one_t) if not np.isnan(one_t) else None,
        'one_sample_p_one_sided': float(one_p) if not np.isnan(one_p) else None,
        'verdict': 'SUPPORTED' if (overall_mean_ratio > 1.0 and binom_p < 0.05) else
                   'WEAK' if overall_mean_ratio > 1.0 else
                   'NOT SUPPORTED',
    },
    'H1b_literature_baseline_T_plus_1': {
        'description': ('Taiwan earnings are typically announced AFTER close -> '
                        'test T+1 reaction. Individual stocks day-0+1 r^2 > non-event r^2.'),
        'overall_mean_ratio_t1': overall_mean_ratio_t1,
        'positives_vs_total_t1': f"{positives_t1}/{n_total}",
        'binom_p_one_sided_t1': binom_p_t1,
        'one_sample_t_t1': float(one_t_t1) if not np.isnan(one_t_t1) else None,
        'one_sample_p_t1': float(one_p_t1) if not np.isnan(one_p_t1) else None,
        'verdict': 'SUPPORTED' if (overall_mean_ratio_t1 > 1.0 and binom_p_t1 < 0.05) else
                   'WEAK' if overall_mean_ratio_t1 > 1.0 else
                   'NOT SUPPORTED',
    },
    'H2_diversification_puzzle': {
        'description': 'If H1 supported but K1059 showed 0050.TW ratio=1.007 -> diversification real',
        'k1059_etf_ratio': 1.007,
        'individual_mean_ratio': overall_mean_ratio,
        'gap': overall_mean_ratio - 1.007,
        'interpretation': (
            'Significant gap supports diversification hypothesis'
            if overall_mean_ratio - 1.007 > 0.02
            else 'Small gap -- individual EAV also weak, diversification not primary driver'
        ),
    },
    'H3_sectoral_heterogeneity': {
        'description': 'EAV strength differs across sectors',
        'sector_mean_ratios': sector_agg.set_index('sector')['mean_ratio'].to_dict(),
        'max_sector': sector_agg.loc[sector_agg['mean_ratio'].idxmax(), 'sector'],
        'min_sector': sector_agg.loc[sector_agg['mean_ratio'].idxmin(), 'sector'],
        'max_min_gap': float(sector_agg['mean_ratio'].max() - sector_agg['mean_ratio'].min()),
    },
}

###############################################################################
# Part 5: Charts
###############################################################################
print("\n[Part 5] Generating charts...")

plt.rcParams.update({'figure.dpi': 120, 'savefig.dpi': 120})

# 5.1 Per-stock EAV bar chart (T+0 and T+1 side by side)
fig, axes = plt.subplots(1, 2, figsize=(14, 6))
colors = {'Tech': '#2E86AB', 'Financial': '#A23B72', 'Traditional': '#F18F01',
          'Telecom': '#6A994E'}

import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

for ax_i, (col_name, title_suffix) in enumerate([('ratio', 'T+0 (announcement day)'),
                                                 ('ratio_t1', 'T+1 (next trading day)')]):
    ax = axes[ax_i]
    sorted_df = summary_df.sort_values(col_name, ascending=True).reset_index(drop=True)
    bar_colors = [colors.get(s, 'gray') for s in sorted_df['sector']]
    ax.barh(range(len(sorted_df)),
            sorted_df[col_name].values,
            color=bar_colors, edgecolor='black', alpha=0.85)
    labels = [f"{t.replace('.TW','')} {n}" for t, n in zip(sorted_df['ticker'],
                                                           sorted_df['name'])]
    ax.set_yticks(range(len(sorted_df)))
    ax.set_yticklabels(labels, fontsize=9)
    ax.axvline(x=1.0, color='red', linestyle='--', lw=1.2)
    ax.axvline(x=1.007, color='black', linestyle=':', lw=1.2)
    ax.set_xlabel('r^2 / non-event r^2 ratio')
    ax.set_title(title_suffix, fontsize=11)
    t_col = 't_stat' if col_name == 'ratio' else 't_stat_t1'
    for i, (r, t) in enumerate(zip(sorted_df[col_name], sorted_df[t_col])):
        ax.text(r + 0.02, i, f't={t:+.2f}', va='center', fontsize=8)
    ax.grid(axis='x', alpha=0.3)

# Legend on the right subplot
sector_handles = [mpatches.Patch(color=c, label=s) for s, c in colors.items()
                  if s in summary_df['sector'].unique()]
line_handles = [
    Line2D([0], [0], color='red', linestyle='--', label='Ratio=1'),
    Line2D([0], [0], color='black', linestyle=':', label='K1059 ETF (1.007)'),
]
axes[1].legend(handles=sector_handles + line_handles, loc='lower right', fontsize=8)

fig.suptitle('K1060: Per-stock Earnings Announcement Volatility (EAV), 2010-2025',
             fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.savefig(SCRIPT_DIR / 'k1060_per_stock_eav.png', bbox_inches='tight')
plt.close()
print("  saved k1060_per_stock_eav.png")

# 5.2 Event window curves for each stock
fig, axes = plt.subplots(5, 2, figsize=(12, 14), sharex=True)
axes = axes.flatten()
offsets = np.arange(-EVENT_WINDOW, EVENT_WINDOW + 1)
for ax, (ticker, info) in zip(axes, stock_data.items()):
    curve = per_stock_results[ticker]['event_window_ratio_curve']
    ax.plot(offsets, curve, marker='o', color=colors.get(info['sector'], 'gray'),
            linewidth=1.6)
    ax.axhline(y=1.0, color='red', linestyle='--', lw=1.0, alpha=0.7)
    ax.axvline(x=0, color='black', linestyle=':', lw=1.0, alpha=0.5)
    ax.set_title(f"{ticker.replace('.TW','')} {info['name']} [{info['sector']}]",
                 fontsize=10)
    ax.set_ylabel('r^2 ratio')
    ax.grid(alpha=0.3)
for ax in axes[-2:]:
    ax.set_xlabel('Trading days relative to announcement (day 0)')
fig.suptitle('K1060: Event Window [-5, +5] r^2 Ratio (event / non-event mean)',
             fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.98])
plt.savefig(SCRIPT_DIR / 'k1060_event_windows.png', bbox_inches='tight')
plt.close()
print("  saved k1060_event_windows.png")

# 5.3 Sectoral comparison
fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

# (a) Sector mean ratios
ax = axes[0]
bar_colors_sec = [colors.get(s, 'gray') for s in sector_agg['sector']]
ax.bar(sector_agg['sector'], sector_agg['mean_ratio'],
       color=bar_colors_sec, edgecolor='black', alpha=0.85)
ax.axhline(y=1.0, color='red', linestyle='--', lw=1.0, label='No-effect baseline')
ax.axhline(y=1.007, color='black', linestyle=':', lw=1.0, label='K1059 0050.TW (1.007)')
ax.set_ylabel('Mean r^2 ratio')
ax.set_title('(a) Sector mean EAV ratio')
for i, (r, n) in enumerate(zip(sector_agg['mean_ratio'], sector_agg['n_stocks'])):
    ax.text(i, r + 0.01, f"{r:.3f}\n(n={n})", ha='center', fontsize=9)
ax.legend(fontsize=8)
ax.grid(axis='y', alpha=0.3)

# (b) Sector mean event-window curves
ax = axes[1]
for sector in sector_agg['sector']:
    members = summary_df.loc[summary_df['sector'] == sector, 'ticker'].tolist()
    if not members:
        continue
    curves = np.array([per_stock_results[t]['event_window_ratio_curve']
                       for t in members])
    mean_curve = curves.mean(axis=0)
    ax.plot(offsets, mean_curve, marker='o',
            color=colors.get(sector, 'gray'), label=f"{sector} (n={len(members)})",
            linewidth=1.8)
ax.axhline(y=1.0, color='red', linestyle='--', lw=1.0)
ax.axvline(x=0, color='black', linestyle=':', lw=1.0)
ax.set_xlabel('Days relative to announcement')
ax.set_ylabel('Mean r^2 ratio')
ax.set_title('(b) Event-window curves by sector')
ax.legend(fontsize=8)
ax.grid(alpha=0.3)

fig.suptitle('K1060: Sectoral Comparison of Earnings Announcement Volatility',
             fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.savefig(SCRIPT_DIR / 'k1060_sectoral_comparison.png', bbox_inches='tight')
plt.close()
print("  saved k1060_sectoral_comparison.png")

###############################################################################
# Part 6: Save results JSON
###############################################################################
elapsed = time.time() - START_TIME
now_iso = datetime.now(timezone.utc).isoformat()

results = {
    'experiment_id': 'K1060',
    'title': 'Individual Taiwan Stock Earnings Announcement Volatility (EAV)',
    'proposer': 'Claude',
    'executor': 'Claude',
    'timestamp_utc': now_iso,
    'runtime_seconds': round(elapsed, 1),
    'random_seed': 42,
    'config': {
        'sample_period': f'{START_DATE} to {END_DATE}',
        'rolling_window_days': ROLLING_WINDOW,
        'event_window_days': EVENT_WINDOW,
        'bootstrap_reps': BOOTSTRAP_REPS,
        'stocks': STOCKS,
    },
    'data_summary': {
        'announcement_records_total': len(ea_df),
        'announcement_records_sample': len(ea_sample),
        'stocks_loaded': len(stock_data),
    },
    'per_stock_results': per_stock_results,
    'sector_aggregates': sector_agg.to_dict('records'),
    'overall_metrics': {
        'mean_ratio_t0': overall_mean_ratio,
        'mean_t_stat_t0': overall_mean_t,
        'ratio_gt_1_count_t0': int(positives),
        'n_stocks': int(n_total),
        'binom_p_t0': binom_p,
        'one_sample_t_t0': float(one_t) if not np.isnan(one_t) else None,
        'one_sample_p_t0': float(one_p) if not np.isnan(one_p) else None,
        'mean_ratio_t1': overall_mean_ratio_t1,
        'mean_t_stat_t1': overall_mean_t_t1,
        'ratio_gt_1_count_t1': int(positives_t1),
        'binom_p_t1': binom_p_t1,
        'one_sample_t_t1': float(one_t_t1) if not np.isnan(one_t_t1) else None,
        'one_sample_p_t1': float(one_p_t1) if not np.isnan(one_p_t1) else None,
    },
    'hypotheses': hypotheses,
    'references': [
        'Patell & Wolfson (1984) J Accounting Research',
        'Beaver (1968) J Accounting Research',
        'Savor & Wilson (2016) JFQA',
        'Ball & Kothari (1991) Accounting Review',
        'K1059 (TSMC -> 0050.TW NULL)',
        'K1058 (A4f on 0050.TW)',
        'K1050 (SPY earnings season)',
    ],
}

out_path = SCRIPT_DIR / 'k1060_results.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\nResults saved to {out_path}")

print("\n" + "=" * 70)
print(f"K1060 done. Elapsed: {elapsed:.1f}s")
print(f"T+0: mean ratio = {overall_mean_ratio:.4f} "
      f"({positives}/{n_total} > 1) -> H1 verdict: "
      f"{hypotheses['H1_literature_baseline']['verdict']}")
print(f"T+1: mean ratio = {overall_mean_ratio_t1:.4f} "
      f"({positives_t1}/{n_total} > 1) -> H1b verdict: "
      f"{hypotheses['H1b_literature_baseline_T_plus_1']['verdict']}")
print("=" * 70)
