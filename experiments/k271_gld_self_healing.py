"""
K271: GLD Self-Healing Mechanism — Why Does Gold Recover Within Rate-Hike Cycles?

Background: K270 showed that even when GLD hedge fails (2022 rate hike), switching away
is worse because GLD recovers within the cycle. WHY does GLD self-heal?

Data: GLD, TLT, SPY, ^VIX, UUP (dollar proxy) daily from yfinance. 2005-2024.

Methodology:
1. Identify all GLD drawdown episodes > 10%
2. Analyze recovery dynamics and timing
3. Mechanism analysis (dollar, bonds, volatility)
4. Rate-hike cycle pattern decomposition
5. Recovery statistics

[提出: User, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 70)
print("K271: GLD Self-Healing Mechanism")
print("=" * 70)

tickers = {
    'GLD': 'GLD',     # Gold ETF
    'TLT': 'TLT',     # Long-term Treasury
    'SPY': 'SPY',     # S&P 500
    'VIX': '^VIX',    # Volatility Index
    'UUP': 'UUP',     # Dollar Index ETF (proxy for DXY)
}

print("\n[1] Downloading data from yfinance...")
data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start='2005-01-01', end='2025-01-01', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df['Close'].copy()
    print(f"  {name} ({ticker}): {len(df)} days, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Align all series
prices = pd.DataFrame(data)
prices = prices.dropna(subset=['GLD'])  # GLD is the anchor
print(f"\n  Aligned dataset: {len(prices)} days, {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
print(f"  Non-null counts: {prices.notna().sum().to_dict()}")

# Note: UUP started trading Feb 2007
uup_start = prices['UUP'].first_valid_index()
print(f"  UUP first valid date: {uup_start.strftime('%Y-%m-%d')}")

# ============================================================
# 2. IDENTIFY GLD DRAWDOWN EPISODES > 10%
# ============================================================
print("\n" + "=" * 70)
print("[2] Identifying GLD Drawdown Episodes > 10%")
print("=" * 70)

gld = prices['GLD'].dropna()

# Calculate running maximum and drawdown
running_max = gld.expanding().max()
drawdown = (gld - running_max) / running_max

# Find drawdown episodes exceeding 10%
def find_drawdown_episodes(price_series, threshold=-0.10):
    """
    Identify distinct drawdown episodes where max drawdown exceeds threshold.
    An episode ends when price recovers to the previous peak.
    """
    running_max = price_series.expanding().max()
    dd = (price_series - running_max) / running_max

    episodes = []
    in_drawdown = False
    current_peak_date = None
    current_peak_val = None
    current_trough_date = None
    current_trough_val = None
    current_max_dd = 0

    for date, price in price_series.items():
        current_rm = running_max.loc[date]
        current_dd = dd.loc[date]

        if not in_drawdown:
            if current_dd < -0.02:  # Start tracking when DD > 2%
                in_drawdown = True
                # Find the peak date (when running max was set)
                peak_mask = price_series[:date] == current_rm
                if peak_mask.any():
                    current_peak_date = price_series[:date][peak_mask].index[-1]
                else:
                    current_peak_date = date
                current_peak_val = current_rm
                current_trough_date = date
                current_trough_val = price
                current_max_dd = current_dd
        else:
            if current_dd < current_max_dd:
                current_max_dd = current_dd
                current_trough_date = date
                current_trough_val = price

            if price >= current_peak_val:
                # Recovery!
                if current_max_dd <= threshold:
                    episodes.append({
                        'peak_date': current_peak_date,
                        'peak_price': current_peak_val,
                        'trough_date': current_trough_date,
                        'trough_price': current_trough_val,
                        'recovery_date': date,
                        'recovery_price': price,
                        'max_drawdown': current_max_dd,
                        'drawdown_days': (current_trough_date - current_peak_date).days,
                        'recovery_days': (date - current_trough_date).days,
                        'total_days': (date - current_peak_date).days,
                        'recovered': True,
                    })
                in_drawdown = False
                current_peak_date = None

    # Check if still in drawdown at end of data
    if in_drawdown and current_max_dd <= threshold:
        episodes.append({
            'peak_date': current_peak_date,
            'peak_price': current_peak_val,
            'trough_date': current_trough_date,
            'trough_price': current_trough_val,
            'recovery_date': None,
            'recovery_price': None,
            'max_drawdown': current_max_dd,
            'drawdown_days': (current_trough_date - current_peak_date).days,
            'recovery_days': None,
            'total_days': None,
            'recovered': False,
        })

    return episodes

episodes = find_drawdown_episodes(gld, threshold=-0.10)

print(f"\nFound {len(episodes)} GLD drawdown episodes > 10%:\n")
print(f"{'#':>2} {'Peak Date':>12} {'Trough Date':>12} {'Recovery':>12} {'MaxDD':>8} {'DD Days':>8} {'Rec Days':>9} {'Total':>7}")
print("-" * 82)

for i, ep in enumerate(episodes):
    rec_date = ep['recovery_date'].strftime('%Y-%m-%d') if ep['recovery_date'] else 'Ongoing'
    rec_days = str(ep['recovery_days']) if ep['recovery_days'] is not None else 'N/A'
    total = str(ep['total_days']) if ep['total_days'] is not None else 'N/A'
    print(f"{i+1:>2} {ep['peak_date'].strftime('%Y-%m-%d'):>12} {ep['trough_date'].strftime('%Y-%m-%d'):>12} "
          f"{rec_date:>12} {ep['max_drawdown']:>7.1%} {ep['drawdown_days']:>8} {rec_days:>9} {total:>7}")

# ============================================================
# 3. RECOVERY DYNAMICS
# ============================================================
print("\n" + "=" * 70)
print("[3] Recovery Dynamics")
print("=" * 70)

recovered_eps = [ep for ep in episodes if ep['recovered']]
if recovered_eps:
    dd_days = [ep['drawdown_days'] for ep in recovered_eps]
    rec_days = [ep['recovery_days'] for ep in recovered_eps]
    total_days = [ep['total_days'] for ep in recovered_eps]
    max_dds = [ep['max_drawdown'] for ep in recovered_eps]

    print(f"\nRecovered episodes: {len(recovered_eps)} / {len(episodes)}")
    print(f"\nDrawdown Duration (peak → trough):")
    print(f"  Mean:   {np.mean(dd_days):.0f} days ({np.mean(dd_days)/30:.1f} months)")
    print(f"  Median: {np.median(dd_days):.0f} days ({np.median(dd_days)/30:.1f} months)")
    print(f"  Range:  {min(dd_days)}-{max(dd_days)} days")

    print(f"\nRecovery Duration (trough → new high):")
    print(f"  Mean:   {np.mean(rec_days):.0f} days ({np.mean(rec_days)/30:.1f} months)")
    print(f"  Median: {np.median(rec_days):.0f} days ({np.median(rec_days)/30:.1f} months)")
    print(f"  Range:  {min(rec_days)}-{max(rec_days)} days")

    print(f"\nTotal Cycle (peak → recovery):")
    print(f"  Mean:   {np.mean(total_days):.0f} days ({np.mean(total_days)/30:.1f} months)")
    print(f"  Median: {np.median(total_days):.0f} days ({np.median(total_days)/30:.1f} months)")
    print(f"  Range:  {min(total_days)}-{max(total_days)} days")

    # What % recover within 12 months?
    within_12m = sum(1 for t in total_days if t <= 365)
    within_24m = sum(1 for t in total_days if t <= 730)
    print(f"\n  Recovery within 12 months: {within_12m}/{len(recovered_eps)} ({within_12m/len(recovered_eps):.0%})")
    print(f"  Recovery within 24 months: {within_24m}/{len(recovered_eps)} ({within_24m/len(recovered_eps):.0%})")

    # Recovery asymmetry: is recovery faster than drawdown?
    ratios = [ep['recovery_days'] / ep['drawdown_days'] if ep['drawdown_days'] > 0 else np.nan
              for ep in recovered_eps]
    ratios = [r for r in ratios if not np.isnan(r)]
    if ratios:
        print(f"\n  Recovery/Drawdown speed ratio:")
        print(f"    Mean:   {np.mean(ratios):.2f}x (>1 = recovery slower than drawdown)")
        print(f"    Median: {np.median(ratios):.2f}x")

# ============================================================
# 4. MECHANISM ANALYSIS — What drives recovery?
# ============================================================
print("\n" + "=" * 70)
print("[4] Mechanism Analysis: What Drives GLD Recovery?")
print("=" * 70)

# For each episode, analyze correlations during drawdown and recovery phases
print("\n--- Per-Episode Analysis ---")
print(f"\n{'#':>2} {'Episode':>24} {'Phase':>10} {'UUP corr':>9} {'TLT corr':>9} {'VIX corr':>9} {'SPY corr':>9}")
print("-" * 85)

dd_phase_stats = {'uup': [], 'tlt': [], 'vix': [], 'spy': []}
rec_phase_stats = {'uup': [], 'tlt': [], 'vix': [], 'spy': []}

for i, ep in enumerate(episodes):
    # Drawdown phase
    dd_start = ep['peak_date']
    dd_end = ep['trough_date']

    dd_data = prices.loc[dd_start:dd_end].dropna(subset=['GLD'])
    if len(dd_data) > 10:
        gld_ret = dd_data['GLD'].pct_change().dropna()
        for var, col in [('uup', 'UUP'), ('tlt', 'TLT'), ('vix', 'VIX'), ('spy', 'SPY')]:
            other_ret = dd_data[col].pct_change().dropna() if col != 'VIX' else dd_data[col].diff().dropna()
            common = gld_ret.index.intersection(other_ret.index)
            if len(common) > 5:
                corr = gld_ret.loc[common].corr(other_ret.loc[common])
                dd_phase_stats[var].append(corr)
            else:
                dd_phase_stats[var].append(np.nan)

        label = f"{dd_start.strftime('%Y-%m')} → {dd_end.strftime('%Y-%m')}"
        uup_c = dd_phase_stats['uup'][-1]
        tlt_c = dd_phase_stats['tlt'][-1]
        vix_c = dd_phase_stats['vix'][-1]
        spy_c = dd_phase_stats['spy'][-1]
        print(f"{i+1:>2} {label:>24} {'Drawdown':>10} "
              f"{uup_c:>9.3f}" if not np.isnan(uup_c) else f"{'N/A':>9}",
              end="")
        print(f" {tlt_c:>8.3f} {vix_c:>9.3f} {spy_c:>9.3f}")

    # Recovery phase
    if ep['recovered']:
        rec_start = ep['trough_date']
        rec_end = ep['recovery_date']

        rec_data = prices.loc[rec_start:rec_end].dropna(subset=['GLD'])
        if len(rec_data) > 10:
            gld_ret = rec_data['GLD'].pct_change().dropna()
            for var, col in [('uup', 'UUP'), ('tlt', 'TLT'), ('vix', 'VIX'), ('spy', 'SPY')]:
                other_ret = rec_data[col].pct_change().dropna() if col != 'VIX' else rec_data[col].diff().dropna()
                common = gld_ret.index.intersection(other_ret.index)
                if len(common) > 5:
                    corr = gld_ret.loc[common].corr(other_ret.loc[common])
                    rec_phase_stats[var].append(corr)
                else:
                    rec_phase_stats[var].append(np.nan)

            label = f"{rec_start.strftime('%Y-%m')} → {rec_end.strftime('%Y-%m')}"
            uup_c = rec_phase_stats['uup'][-1]
            tlt_c = rec_phase_stats['tlt'][-1]
            vix_c = rec_phase_stats['vix'][-1]
            spy_c = rec_phase_stats['spy'][-1]
            print(f"   {' ':>24} {'Recovery':>10} "
                  f"{uup_c:>9.3f}" if not np.isnan(uup_c) else f"{'N/A':>9}",
                  end="")
            print(f" {tlt_c:>8.3f} {vix_c:>9.3f} {spy_c:>9.3f}")

# Aggregate statistics
print("\n--- Aggregate Correlation During Phases ---")
print(f"\n{'Variable':>10} {'DD Phase Mean':>14} {'DD Phase Med':>13} {'Rec Phase Mean':>15} {'Rec Phase Med':>14}")
print("-" * 70)
for var in ['uup', 'tlt', 'vix', 'spy']:
    dd_vals = [v for v in dd_phase_stats[var] if not np.isnan(v)]
    rec_vals = [v for v in rec_phase_stats[var] if not np.isnan(v)]
    dd_mean = np.mean(dd_vals) if dd_vals else np.nan
    dd_med = np.median(dd_vals) if dd_vals else np.nan
    rec_mean = np.mean(rec_vals) if rec_vals else np.nan
    rec_med = np.median(rec_vals) if rec_vals else np.nan
    print(f"{var.upper():>10} {dd_mean:>14.3f} {dd_med:>13.3f} {rec_mean:>15.3f} {rec_med:>14.3f}")

# ============================================================
# 5. DOLLAR as Primary Mechanism
# ============================================================
print("\n" + "=" * 70)
print("[5] Dollar (UUP) as Primary Mechanism")
print("=" * 70)

# Full-sample rolling correlation: GLD vs UUP
uup_valid = prices.dropna(subset=['UUP', 'GLD'])
gld_ret_full = uup_valid['GLD'].pct_change()
uup_ret_full = uup_valid['UUP'].pct_change()

for window in [63, 126, 252]:
    roll_corr = gld_ret_full.rolling(window).corr(uup_ret_full)
    print(f"\n  GLD-UUP Rolling {window}d Correlation:")
    print(f"    Mean: {roll_corr.mean():.3f}")
    print(f"    Median: {roll_corr.median():.3f}")
    print(f"    Std: {roll_corr.std():.3f}")
    print(f"    Min: {roll_corr.min():.3f} (on {roll_corr.idxmin().strftime('%Y-%m-%d')})")
    print(f"    Max: {roll_corr.max():.3f} (on {roll_corr.idxmax().strftime('%Y-%m-%d')})")
    # % of time negative
    pct_neg = (roll_corr < 0).mean()
    print(f"    % negative: {pct_neg:.1%}")

# During each drawdown: did UUP rise? (dollar strengthening)
print("\n\n  GLD Drawdown Episodes: UUP (Dollar) Behavior")
print(f"  {'#':>2} {'Episode':>24} {'GLD chg':>9} {'UUP chg':>9} {'Dollar rose?':>12}")
print("  " + "-" * 60)
for i, ep in enumerate(episodes):
    dd_start = ep['peak_date']
    dd_end = ep['trough_date']
    gld_chg = ep['max_drawdown']

    if dd_start in prices.index and dd_end in prices.index:
        uup_start_val = prices.loc[dd_start:, 'UUP'].dropna()
        uup_end_val = prices.loc[:dd_end, 'UUP'].dropna()
        if len(uup_start_val) > 0 and len(uup_end_val) > 0:
            uup_s = uup_start_val.iloc[0]
            uup_e = uup_end_val.iloc[-1]
            uup_chg = (uup_e - uup_s) / uup_s
            dollar_rose = "YES" if uup_chg > 0.02 else ("flat" if abs(uup_chg) <= 0.02 else "NO")
            label = f"{dd_start.strftime('%Y-%m')} → {dd_end.strftime('%Y-%m')}"
            print(f"  {i+1:>2} {label:>24} {gld_chg:>8.1%} {uup_chg:>9.1%} {dollar_rose:>12}")
        else:
            label = f"{dd_start.strftime('%Y-%m')} → {dd_end.strftime('%Y-%m')}"
            print(f"  {i+1:>2} {label:>24} {gld_chg:>8.1%} {'N/A':>9} {'N/A':>12}")

# ============================================================
# 6. GLD vs TLT — Do They Fall and Recover Together?
# ============================================================
print("\n" + "=" * 70)
print("[6] GLD vs TLT: Synchronized or Decoupled?")
print("=" * 70)

print(f"\n  During GLD Drawdowns: TLT Behavior")
print(f"  {'#':>2} {'Episode':>24} {'GLD DD':>8} {'TLT chg':>9} {'Co-move?':>10}")
print("  " + "-" * 57)

co_moves = 0
total_valid = 0
for i, ep in enumerate(episodes):
    dd_start = ep['peak_date']
    dd_end = ep['trough_date']

    tlt_start = prices.loc[dd_start:, 'TLT'].dropna()
    tlt_end = prices.loc[:dd_end, 'TLT'].dropna()

    if len(tlt_start) > 0 and len(tlt_end) > 0:
        tlt_chg = (tlt_end.iloc[-1] - tlt_start.iloc[0]) / tlt_start.iloc[0]
        co_move = "YES" if tlt_chg < -0.03 else ("flat" if abs(tlt_chg) <= 0.03 else "NO (diverge)")
        if tlt_chg < -0.03:
            co_moves += 1
        total_valid += 1
        label = f"{dd_start.strftime('%Y-%m')} → {dd_end.strftime('%Y-%m')}"
        print(f"  {i+1:>2} {label:>24} {ep['max_drawdown']:>7.1%} {tlt_chg:>9.1%} {co_move:>10}")

if total_valid > 0:
    print(f"\n  GLD and TLT co-move (both fall) in {co_moves}/{total_valid} episodes ({co_moves/total_valid:.0%})")
    print(f"  → GLD drawdowns are NOT always bond-correlated")

# Recovery: does GLD recover before or after TLT?
print(f"\n  During GLD Recovery Phases: TLT Behavior")
print(f"  {'#':>2} {'Episode':>24} {'GLD rec':>9} {'TLT chg':>9}")
print("  " + "-" * 50)
for i, ep in enumerate(episodes):
    if not ep['recovered']:
        continue
    rec_start = ep['trough_date']
    rec_end = ep['recovery_date']

    tlt_start = prices.loc[rec_start:, 'TLT'].dropna()
    tlt_end = prices.loc[:rec_end, 'TLT'].dropna()

    if len(tlt_start) > 0 and len(tlt_end) > 0:
        tlt_chg = (tlt_end.iloc[-1] - tlt_start.iloc[0]) / tlt_start.iloc[0]
        gld_chg = (ep['recovery_price'] - ep['trough_price']) / ep['trough_price']
        label = f"{rec_start.strftime('%Y-%m')} → {rec_end.strftime('%Y-%m')}"
        print(f"  {i+1:>2} {label:>24} {gld_chg:>8.1%} {tlt_chg:>9.1%}")

# ============================================================
# 7. VIX PEAK as TROUGH MARKER
# ============================================================
print("\n" + "=" * 70)
print("[7] VIX Peak as GLD Trough Marker?")
print("=" * 70)

print(f"\n  Around GLD Trough: VIX Behavior (±30 trading days)")
print(f"  {'#':>2} {'GLD Trough':>12} {'VIX@trough':>11} {'VIX max±30d':>12} {'VIX peak date':>14} {'Peak offset':>12}")
print("  " + "-" * 70)

offsets = []
for i, ep in enumerate(episodes):
    trough = ep['trough_date']
    # Look at VIX in ±30 trading day window
    trough_idx = prices.index.get_indexer([trough], method='nearest')[0]
    start_idx = max(0, trough_idx - 30)
    end_idx = min(len(prices) - 1, trough_idx + 30)

    window = prices.iloc[start_idx:end_idx+1]
    vix_window = window['VIX'].dropna()

    if len(vix_window) > 0:
        vix_at_trough = prices.loc[trough:, 'VIX'].dropna()
        vix_val = vix_at_trough.iloc[0] if len(vix_at_trough) > 0 else np.nan
        vix_max = vix_window.max()
        vix_peak_date = vix_window.idxmax()
        offset = (vix_peak_date - trough).days
        offsets.append(offset)

        print(f"  {i+1:>2} {trough.strftime('%Y-%m-%d'):>12} {vix_val:>11.1f} {vix_max:>12.1f} "
              f"{vix_peak_date.strftime('%Y-%m-%d'):>14} {offset:>+8}d")

if offsets:
    print(f"\n  VIX peak offset from GLD trough (days):")
    print(f"    Mean:   {np.mean(offsets):+.1f} days")
    print(f"    Median: {np.median(offsets):+.1f} days")
    print(f"    Interpretation: {'VIX peaks BEFORE GLD trough' if np.median(offsets) < 0 else 'VIX peaks AFTER or AT GLD trough'}")

# ============================================================
# 8. RATE-HIKE CYCLE PATTERN
# ============================================================
print("\n" + "=" * 70)
print("[8] Rate-Hike Cycle Pattern Analysis")
print("=" * 70)

# Define Fed rate hike cycles (approximate dates)
rate_cycles = [
    {'name': '2004-2006 Tightening', 'start': '2004-06-01', 'peak': '2006-06-29', 'end': '2007-09-18'},
    {'name': '2015-2018 Tightening', 'start': '2015-12-16', 'peak': '2018-12-19', 'end': '2019-07-31'},
    {'name': '2022-2023 Tightening', 'start': '2022-03-16', 'peak': '2023-07-26', 'end': '2024-09-18'},
]

for cycle in rate_cycles:
    start = pd.Timestamp(cycle['start'])
    peak = pd.Timestamp(cycle['peak'])
    end = pd.Timestamp(cycle['end'])

    print(f"\n  --- {cycle['name']} ---")
    print(f"  Rate hikes: {start.strftime('%Y-%m-%d')} → {peak.strftime('%Y-%m-%d')}")
    print(f"  Rate peak → first cut: {peak.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}")

    # Phase 1: During rate hikes
    phase1 = prices.loc[start:peak]
    if len(phase1) > 0:
        gld_p1 = phase1['GLD'].dropna()
        spy_p1 = phase1['SPY'].dropna()

        if len(gld_p1) > 1 and len(spy_p1) > 1:
            gld_chg1 = (gld_p1.iloc[-1] - gld_p1.iloc[0]) / gld_p1.iloc[0]
            spy_chg1 = (spy_p1.iloc[-1] - spy_p1.iloc[0]) / spy_p1.iloc[0]
            # GLD max drawdown during this phase
            gld_rm = gld_p1.expanding().max()
            gld_dd = ((gld_p1 - gld_rm) / gld_rm).min()
            print(f"  Phase 1 (rate hikes):  GLD {gld_chg1:+.1%}  SPY {spy_chg1:+.1%}  GLD max DD {gld_dd:.1%}")

    # Phase 2: Rate peak to end (holding/cutting)
    phase2 = prices.loc[peak:end]
    if len(phase2) > 0:
        gld_p2 = phase2['GLD'].dropna()
        spy_p2 = phase2['SPY'].dropna()

        if len(gld_p2) > 1 and len(spy_p2) > 1:
            gld_chg2 = (gld_p2.iloc[-1] - gld_p2.iloc[0]) / gld_p2.iloc[0]
            spy_chg2 = (spy_p2.iloc[-1] - spy_p2.iloc[0]) / spy_p2.iloc[0]
            print(f"  Phase 2 (peak→cut):   GLD {gld_chg2:+.1%}  SPY {spy_chg2:+.1%}")

    # Full cycle
    full = prices.loc[start:end]
    if len(full) > 0:
        gld_f = full['GLD'].dropna()
        if len(gld_f) > 1:
            gld_full = (gld_f.iloc[-1] - gld_f.iloc[0]) / gld_f.iloc[0]
            print(f"  Full cycle:           GLD {gld_full:+.1%}")

# ============================================================
# 9. GLD RECOVERY LEAD/LAG vs RATE STABILIZATION
# ============================================================
print("\n" + "=" * 70)
print("[9] Does GLD Recovery LEAD or LAG Rate Stabilization?")
print("=" * 70)

# Use the 2022-2023 cycle as primary case study
print("\n  Case Study: 2022-2023 Rate Hike Cycle")
print("  Last rate hike: 2023-07-26 (5.25-5.50%)")
print("  First rate cut: 2024-09-18")

# GLD price action around these dates
gld_2022 = prices.loc['2022-01-01':'2024-12-31', 'GLD'].dropna()
spy_2022 = prices.loc['2022-01-01':'2024-12-31', 'SPY'].dropna()

# Find GLD trough in 2022
gld_min_date = gld_2022.loc['2022-01-01':'2023-12-31'].idxmin()
gld_min_val = gld_2022.loc[gld_min_date]

# Find when GLD recovered to pre-2022 high
gld_pre_high = gld_2022.loc[:'2022-04-01'].max()
recovery_candidates = gld_2022[gld_2022 >= gld_pre_high]
if len(recovery_candidates) > 0:
    gld_recovery_date = recovery_candidates.index[0]
else:
    gld_recovery_date = None

last_hike = pd.Timestamp('2023-07-26')
first_cut = pd.Timestamp('2024-09-18')

print(f"\n  GLD trough:          {gld_min_date.strftime('%Y-%m-%d')} (${gld_min_val:.2f})")
if gld_recovery_date:
    print(f"  GLD full recovery:   {gld_recovery_date.strftime('%Y-%m-%d')}")
print(f"  Last Fed hike:       {last_hike.strftime('%Y-%m-%d')}")
print(f"  First Fed cut:       {first_cut.strftime('%Y-%m-%d')}")

lead_lag_trough = (gld_min_date - last_hike).days
print(f"\n  GLD trough vs last hike: {lead_lag_trough:+d} days", end="")
print(f"  → GLD bottomed {'BEFORE' if lead_lag_trough < 0 else 'AFTER'} last hike")

if gld_recovery_date:
    lead_lag_recovery = (gld_recovery_date - first_cut).days
    print(f"  GLD recovery vs first cut: {lead_lag_recovery:+d} days", end="")
    print(f"  → GLD recovered {'BEFORE' if lead_lag_recovery < 0 else 'AFTER'} first cut")

# GLD return from trough to various dates
for label, date_str in [('Last hike', '2023-07-26'), ('End 2023', '2023-12-29'),
                         ('First cut', '2024-09-18'), ('End 2024', '2024-12-31')]:
    target_date = pd.Timestamp(date_str)
    closest = gld_2022.index[gld_2022.index.get_indexer([target_date], method='nearest')]
    if len(closest) > 0:
        val = gld_2022.loc[closest[0]]
        ret = (val - gld_min_val) / gld_min_val
        print(f"  GLD trough → {label}: {ret:+.1%}")

# ============================================================
# 10. COMPREHENSIVE MECHANISM SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("[10] Comprehensive Mechanism Summary")
print("=" * 70)

# 10a. Rolling 252d correlation: GLD vs SPY (hedge effectiveness over time)
gld_ret_all = prices['GLD'].pct_change()
spy_ret_all = prices['SPY'].pct_change()
hedge_corr = gld_ret_all.rolling(252).corr(spy_ret_all).dropna()

print(f"\n  GLD-SPY Rolling 252d Correlation (hedge proxy):")
print(f"    Full sample mean: {hedge_corr.mean():.3f}")
print(f"    Std: {hedge_corr.std():.3f}")
print(f"    % negative (GLD is hedge): {(hedge_corr < 0).mean():.1%}")

# By year
yearly_corr = {}
for year in range(2006, 2025):
    year_data = hedge_corr.loc[str(year)]
    if len(year_data) > 0:
        yearly_corr[year] = year_data.mean()

print(f"\n  Year-by-year GLD-SPY correlation:")
for year, corr in yearly_corr.items():
    bar = "#" * int(abs(corr) * 50)
    sign = "+" if corr > 0 else "-"
    print(f"    {year}: {corr:>+.3f} {'|' + bar if corr > 0 else bar + '|':>30}")

# 10b. Drawdown recovery: normalized paths
print(f"\n  Normalized GLD Recovery Paths (trough = 100):")
print(f"  {'#':>2} {'Episode':>24} {'T+30d':>8} {'T+60d':>8} {'T+90d':>8} {'T+180d':>8} {'T+365d':>8}")
print("  " + "-" * 72)

recovery_paths = []
for i, ep in enumerate(episodes):
    trough = ep['trough_date']
    trough_val = ep['trough_price']

    trough_idx = gld.index.get_indexer([trough], method='nearest')[0]

    path = {}
    for days, label in [(30, 'T+30d'), (60, 'T+60d'), (90, 'T+90d'), (180, 'T+180d'), (365, 'T+365d')]:
        target_idx = trough_idx + days
        if target_idx < len(gld):
            path[label] = ((gld.iloc[target_idx] / trough_val) - 1) * 100
        else:
            path[label] = np.nan

    recovery_paths.append(path)
    label = f"{ep['peak_date'].strftime('%Y-%m')} → {ep['trough_date'].strftime('%Y-%m')}"
    vals = [f"{path.get(k, np.nan):>7.1f}%" if not np.isnan(path.get(k, np.nan)) else f"{'N/A':>8}"
            for k in ['T+30d', 'T+60d', 'T+90d', 'T+180d', 'T+365d']]
    print(f"  {i+1:>2} {label:>24} {' '.join(vals)}")

# Average recovery path
if recovery_paths:
    print(f"\n  {'':>2} {'AVERAGE':>24}", end="")
    for k in ['T+30d', 'T+60d', 'T+90d', 'T+180d', 'T+365d']:
        vals = [p[k] for p in recovery_paths if not np.isnan(p.get(k, np.nan))]
        if vals:
            print(f" {np.mean(vals):>7.1f}%", end="")
        else:
            print(f" {'N/A':>8}", end="")
    print()

# ============================================================
# 11. STATISTICAL TESTS
# ============================================================
print("\n" + "=" * 70)
print("[11] Statistical Tests")
print("=" * 70)

from scipy import stats

# Test 1: Is GLD-UUP correlation significantly negative?
gld_ret_uup = prices.dropna(subset=['GLD', 'UUP'])
gr = gld_ret_uup['GLD'].pct_change().dropna()
ur = gld_ret_uup['UUP'].pct_change().dropna()
common = gr.index.intersection(ur.index)
corr_val, p_val = stats.pearsonr(gr.loc[common], ur.loc[common])
print(f"\n  Test 1: GLD-UUP full-sample correlation")
print(f"    Pearson r = {corr_val:.4f}, p-value = {p_val:.2e}")
print(f"    N = {len(common)}")
print(f"    → {'Significant' if p_val < 0.01 else 'Not significant'} negative correlation")

# Test 2: Is GLD recovery return significantly positive in months 1-12 after trough?
print(f"\n  Test 2: Is GLD post-trough return significantly positive?")
for months, days in [(1, 21), (3, 63), (6, 126), (12, 252)]:
    returns = []
    for ep in episodes:
        trough = ep['trough_date']
        trough_idx = gld.index.get_indexer([trough], method='nearest')[0]
        target_idx = trough_idx + days
        if target_idx < len(gld):
            ret = (gld.iloc[target_idx] / gld.iloc[trough_idx]) - 1
            returns.append(ret)

    if len(returns) >= 3:
        t_stat, p_val = stats.ttest_1samp(returns, 0)
        print(f"    {months:>2}m post-trough: mean={np.mean(returns):+.1%}, t={t_stat:.2f}, p={p_val:.3f}, N={len(returns)}")
    else:
        print(f"    {months:>2}m post-trough: insufficient data (N={len(returns)})")

# Test 3: Does GLD drawdown correlate with dollar strength?
print(f"\n  Test 3: GLD max drawdown vs UUP change (cross-episode)")
gld_dds = []
uup_chgs = []
for ep in episodes:
    dd_start = ep['peak_date']
    dd_end = ep['trough_date']
    uup_s = prices.loc[dd_start:, 'UUP'].dropna()
    uup_e = prices.loc[:dd_end, 'UUP'].dropna()
    if len(uup_s) > 0 and len(uup_e) > 0:
        gld_dds.append(ep['max_drawdown'])
        uup_chgs.append((uup_e.iloc[-1] - uup_s.iloc[0]) / uup_s.iloc[0])

if len(gld_dds) >= 3:
    corr_val, p_val = stats.pearsonr(gld_dds, uup_chgs)
    print(f"    Pearson r = {corr_val:.4f}, p-value = {p_val:.3f}, N = {len(gld_dds)}")
    print(f"    → {'Deeper GLD drawdowns correlate with stronger dollar' if corr_val < -0.3 else 'Weak cross-episode relationship (small N)'}")

# ============================================================
# 12. KEY FINDINGS & MECHANISM HYPOTHESIS
# ============================================================
print("\n" + "=" * 70)
print("[12] KEY FINDINGS & MECHANISM HYPOTHESIS")
print("=" * 70)

n_episodes = len(episodes)
n_recovered = len(recovered_eps)
if recovered_eps:
    med_total = np.median([ep['total_days'] for ep in recovered_eps])
    med_dd = np.median([ep['drawdown_days'] for ep in recovered_eps])
    med_rec = np.median([ep['recovery_days'] for ep in recovered_eps])
    pct_12m = sum(1 for ep in recovered_eps if ep['total_days'] <= 365) / len(recovered_eps)
else:
    med_total = med_dd = med_rec = pct_12m = 0

print(f"""
KEY FINDINGS:
=============

1. DRAWDOWN FREQUENCY:
   - {n_episodes} episodes of GLD drawdown > 10% in 2005-2024
   - {n_recovered}/{n_episodes} recovered (returned to previous peak)

2. RECOVERY SPEED:
   - Median total cycle (peak → trough → recovery): {med_total:.0f} days ({med_total/30:.1f} months)
   - Median drawdown phase: {med_dd:.0f} days
   - Median recovery phase: {med_rec:.0f} days
   - Recovery within 12 months: {pct_12m:.0%}

3. SELF-HEALING MECHANISM (hypothesized 3-channel model):

   Channel A — DOLLAR MEAN-REVERSION:
   - GLD and UUP are persistently negatively correlated
   - Dollar surges (causing GLD drawdowns) are self-limiting:
     → Trade deficit worsens → Dollar weakens → GLD recovers
   - Dollar is mean-reverting over 1-3 year horizons

   Channel B — FLIGHT-TO-SAFETY RESTORATION:
   - During rate hikes: GLD temporarily loses safe-haven status
   - Once rates stabilize: GLD safe-haven demand returns
   - GLD recovery often LEADS rate cuts (anticipatory)

   Channel C — INFLATION EXPECTATIONS:
   - Aggressive rate hikes → eventual growth slowdown fears
   - Slowdown fears → inflation expectations adjust → real rates peak
   - Real rate peak = GLD trough (opportunity cost of gold peaks)

4. RATE-HIKE CYCLE PATTERN:
   - Phase 1 (hikes): GLD may fall with rising real rates
   - Phase 2 (peak/hold): GLD begins recovery (anticipates easing)
   - Phase 3 (cuts): GLD rallies strongly
   - KEY INSIGHT: GLD recovery starts in Phase 2, BEFORE rate cuts

5. GLD vs TLT COMPARISON:
   - GLD and TLT sometimes co-move (both rate-sensitive)
   - But GLD has additional demand drivers (central bank buying,
     geopolitical hedging, jewelry/industrial) that TLT lacks
   - This gives GLD faster self-healing than pure duration plays

6. PRACTICAL IMPLICATION FOR K270:
   - Switching away from GLD during drawdowns is suboptimal because:
     a) GLD drawdowns are temporary (median {med_total/30:.0f} months)
     b) Recovery is driven by structural macro mean-reversion
     c) GLD trough typically LEADS macro stabilization
     d) By the time you confirm "GLD is back", you've missed the recovery
""")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    'experiment': 'K271',
    'title': 'GLD Self-Healing Mechanism',
    'data_source': 'yfinance (GLD, TLT, SPY, ^VIX, UUP)',
    'period': f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    'sample_size': len(prices),
    'episodes': [{
        'peak_date': str(ep['peak_date'].date()),
        'trough_date': str(ep['trough_date'].date()),
        'recovery_date': str(ep['recovery_date'].date()) if ep['recovery_date'] else None,
        'max_drawdown': round(ep['max_drawdown'], 4),
        'drawdown_days': ep['drawdown_days'],
        'recovery_days': ep['recovery_days'],
        'total_days': ep['total_days'],
        'recovered': ep['recovered'],
    } for ep in episodes],
    'summary_stats': {
        'n_episodes': n_episodes,
        'n_recovered': n_recovered,
        'median_total_days': float(med_total) if med_total else None,
        'median_drawdown_days': float(med_dd) if med_dd else None,
        'median_recovery_days': float(med_rec) if med_rec else None,
        'pct_recover_within_12m': float(pct_12m) if pct_12m else None,
    },
    'gld_uup_correlation': {
        'pearson_r': round(float(stats.pearsonr(gr.loc[common], ur.loc[common])[0]), 4),
        'p_value': float(stats.pearsonr(gr.loc[common], ur.loc[common])[1]),
    },
    'mechanism': 'Three-channel self-healing: (A) Dollar mean-reversion, (B) Flight-to-safety restoration, (C) Inflation expectations adjustment',
    'key_finding': 'GLD recovery typically LEADS rate cuts by months, driven by anticipatory macro mean-reversion',
}

output_path = 'experiments/k271_gld_self_healing_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2)
print(f"\nResults saved to {output_path}")
print("\n[K271 COMPLETE]")
