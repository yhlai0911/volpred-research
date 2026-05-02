#!/usr/bin/env python3
"""
K1264: TX Futures Overnight Gap Strategy
==========================================
[提出: 用戶, 執行: Claude]

延伸 K515 (SPY-conditioned overnight gap alpha 真實 10.73bp/day, t=4.06) 與
K625 (SPY ETF cost-killing finding: 18.55bp round-trip 致命)。

Hypothesis:
  H0: TX 期貨 overnight gap (close → open) Sharpe ≤ 0 after 5bp round-trip
  H1: TX overnight Sharpe > 0.5 + cross-OOS 4/5 → listing candidate
  H2: SPY-conditioned 條件報酬 ≥ unconditional 1.5×

Strategy:
  S1 unconditional: long TX overnight (close → next-day open) 100% capital
  S2 SPY-conditioned: long TX overnight if SPY(t-1 overnight, US) > 0
  Lag: signal.shift(1) on SPY signal — today's TX position 由 yesterday's
       SPY-overnight 決定 (避免 lookahead)
  Sell TX at next-day open

Data:
  - TAIFEX TX tick CSVs (/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_*TX.csv)
  - 2017-05-16 onwards (after night session introduced for consistency)
  - 跳過夜盤！只用日盤 close (last tick before 13:45) → 次日盤 open (first tick after 08:45)
  - SPY: yfinance, overnight return = (Open_t - Close_{t-1}) / Close_{t-1}

Cost: 2.5bp/leg × 2 legs = 5bp round-trip (per research_program.md L424 + 用戶 spec)

Three-Gate Listing (per K1100g_d1):
  1. Net Sharpe > 0.5 (after 5bp cost)
  2. DM-HLN |t| > 3.0 vs zero (mean-diff t-test for return ≠ 0)
  3. Cross-OOS: 4/5 個年度視窗 (2018/2020/2022/2023/2024) 同方向

Error log rules applied:
  - signal.shift(1) on SPY signal
  - Fixed seed = 42
  - 零夜盤 (避免 K842 22:00-03:00 noise)
  - Friday→Monday outlier 與 holiday gap separately reported
  - max-volume expiry filter per K843 pattern
"""

import os
import json
import time
import warnings
import glob
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, as_completed
from scipy import stats

warnings.filterwarnings('ignore')

np.random.seed(42)

# ============================================================
# Constants
# ============================================================
DATA_DIR = '/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python'
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
START_DATE = 20170516  # First date with night session (per K843)
MIN_FILE_SIZE = 100

DAY_OPEN_TIME  = 84500   # 08:45:00
DAY_CLOSE_TIME = 134500  # 13:45:00

# Cost: 2.5bp per leg × 2 legs = 5bp round-trip
TX_COST_RT = 0.0005  # 5bp = 0.05%

# ============================================================
# 1. TX file parser (per file → daily close + next-day open)
# ============================================================

def parse_tx_file(filepath):
    """
    Parse single TX file. Each file represents ONE trading day's tick data:
      Date1 (prev calendar): 15:00-23:59 (night session evening)
      Date2 (current calendar): 00:00-05:00 (night morning) + 08:45-13:45 (day session)

    Returns dict per file:
      - date (day-session calendar date, YYYYMMDD int)
      - day_open: first tick price at/after 08:45 (max-volume expiry)
      - day_close: last tick price at/before 13:45 (max-volume expiry)
      - day_volume: total day-session volume
      - expiry: max-volume expiry on day session
    """
    try:
        if os.path.getsize(filepath) < MIN_FILE_SIZE:
            return None

        df = pd.read_csv(filepath, encoding='big5')
        if len(df) < 10:
            return None

        df.columns = ['date', 'product', 'expiry', 'time', 'price', 'volume',
                      'near_p', 'far_p', 'open_auction', 'ts']

        df = df[df['product'].astype(str).str.strip() == 'TX'].copy()
        if len(df) < 10:
            return None

        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).astype(int)
        df['time'] = pd.to_numeric(df['time'], errors='coerce').fillna(0).astype(int)
        df['date'] = pd.to_numeric(df['date'], errors='coerce').fillna(0).astype(int)
        df['expiry'] = pd.to_numeric(df['expiry'], errors='coerce').fillna(0).astype(int)
        df = df.dropna(subset=['price'])

        if len(df) < 10:
            return None

        dates = sorted(df['date'].unique())
        # Day session = latest date in file (per K843 logic)
        day_date = dates[-1]

        # Day session ticks: 08:45-13:45
        day = df[(df['date'] == day_date) &
                 (df['time'] >= DAY_OPEN_TIME) &
                 (df['time'] <= DAY_CLOSE_TIME)]

        if len(day) < 5:
            return None

        # Find max-volume expiry on day session
        vol_by_exp = day.groupby('expiry')['volume'].sum()
        if len(vol_by_exp) == 0:
            return None
        max_exp = vol_by_exp.idxmax()

        day_max = day[day['expiry'] == max_exp].sort_values('time')
        if len(day_max) < 5:
            return None

        return {
            'day_date': int(day_date),
            'expiry': int(max_exp),
            'day_open': float(day_max.iloc[0]['price']),
            'day_close': float(day_max.iloc[-1]['price']),
            'day_volume': int(day_max['volume'].sum()),
            'n_day_ticks': int(len(day_max)),
            'day_open_time': int(day_max.iloc[0]['time']),
            'day_close_time': int(day_max.iloc[-1]['time']),
        }

    except Exception as e:
        return {'error': str(e), 'file': os.path.basename(filepath)}


def collect_tx_daily(start_date=START_DATE, max_workers=8, sample_limit=None):
    """Collect daily close/open for all TX files since start_date."""
    pattern = os.path.join(DATA_DIR, 'Daily_*TX.csv')
    all_files = sorted(glob.glob(pattern))

    # Filter by date in filename: Daily_YYYY_MM_DDTX.csv
    def parse_filename_date(f):
        try:
            base = os.path.basename(f).replace('Daily_', '').replace('TX.csv', '')
            parts = base.split('_')
            return int(parts[0]) * 10000 + int(parts[1]) * 100 + int(parts[2])
        except Exception:
            return 0

    files = [f for f in all_files if parse_filename_date(f) >= start_date]
    print(f"  Total TX files since {start_date}: {len(files)}")

    if sample_limit:
        files = files[:sample_limit]
        print(f"  SAMPLE_LIMIT applied → {len(files)} files")

    results = []
    errors = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(parse_tx_file, f): f for f in files}
        for i, fut in enumerate(as_completed(futures)):
            r = fut.result()
            if r is None:
                continue
            if 'error' in r:
                errors.append(r)
                continue
            results.append(r)
            if (i + 1) % 200 == 0:
                elapsed = time.time() - t0
                print(f"    Parsed {i+1}/{len(files)} files ({elapsed:.0f}s)")

    print(f"  Successful parses: {len(results)}, errors: {len(errors)}")
    if errors:
        print(f"  First 3 errors: {errors[:3]}")
    return results


# ============================================================
# 2. Build TX daily close/open dataframe
# ============================================================

def build_tx_df(records):
    """Build dataframe of (date, close_today, open_tomorrow) for overnight gap calc."""
    df = pd.DataFrame(records)
    df['date'] = pd.to_datetime(df['day_date'], format='%Y%m%d')
    df = df.sort_values('date').reset_index(drop=True)

    # Drop duplicates (keep first per date)
    df = df.drop_duplicates(subset='date', keep='first').reset_index(drop=True)

    # Overnight gap: buy close at day t, sell open at day t+1
    # gap_ret_t = (open_{t+1} - close_t) / close_t
    df['next_open'] = df['day_open'].shift(-1)
    df['next_date'] = df['date'].shift(-1)
    df['gap_ret'] = (df['next_open'] - df['day_close']) / df['day_close']

    # Days between trade open and next trade close (1 = normal Mon-Thu, 3 = Fri→Mon)
    df['gap_days'] = (df['next_date'] - df['date']).dt.days

    # Drop last row (no next_open available)
    df = df.dropna(subset=['next_open']).reset_index(drop=True)

    # Outlier filter (|gap| > 5% likely abnormal — TX 5% in 1 day = >7σ)
    n_extreme = (df['gap_ret'].abs() > 0.05).sum()
    print(f"  Extreme |gap|>5% rows: {n_extreme} (kept; flagged in metadata)")

    print(f"  TX gap_ret: n={len(df)}, mean={df['gap_ret'].mean()*10000:.2f} bps, "
          f"std={df['gap_ret'].std()*10000:.2f} bps")
    return df


# ============================================================
# 3. SPY overnight return
# ============================================================

def get_spy_overnight():
    """SPY overnight ret = (Open_t - Close_{t-1}) / Close_{t-1} (US trading days)."""
    spy = yf.download('SPY', start='2017-01-01', end='2027-01-01', progress=False, auto_adjust=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy = spy.copy()
    spy['spy_overnight'] = (spy['Open'] - spy['Close'].shift(1)) / spy['Close'].shift(1)
    spy_on = spy[['spy_overnight']].dropna()
    spy_on.index = pd.to_datetime(spy_on.index)
    spy_on = spy_on.reset_index()
    spy_on.columns = ['us_date', 'spy_overnight']
    spy_on['us_date'] = pd.to_datetime(spy_on['us_date'])
    print(f"  SPY overnight: n={len(spy_on)}, mean={spy_on['spy_overnight'].mean()*10000:.2f} bps")
    return spy_on


def align_spy_to_tx(tx_df, spy_df):
    """
    For TX trade open at TW day t (sell at open of t+1):
      Signal needs: SPY overnight from US trading day BEFORE TW close at t
      US trading day for TW day t = the most recent US date with date < TW date t
      (because US market closes ~04:00 TW time on TW date t, but we trade at TW close 13:45,
       so SPY data from US date == TW date - 0 or 1 is available)
    Use merge_asof backward: for each tw_date, find most recent us_date <= tw_date - 1
    (1-day buffer guarantees no lookahead — we only use signals from at least 1 day prior)
    """
    tx_sorted = tx_df.sort_values('date').reset_index(drop=True)
    spy_sorted = spy_df.sort_values('us_date').reset_index(drop=True)

    # Force datetime64[ns] dtype on both sides (avoids merge_asof us/s precision mismatch)
    tx_sorted['date'] = pd.to_datetime(tx_sorted['date']).astype('datetime64[ns]')
    spy_sorted['us_date'] = pd.to_datetime(spy_sorted['us_date']).astype('datetime64[ns]')

    # IMPORTANT lag: shift TX dates back by 1 day for merge_asof to enforce strict t-1 SPY
    tx_sorted['_lookup_date'] = tx_sorted['date'] - pd.Timedelta(days=1)
    tx_sorted['_lookup_date'] = tx_sorted['_lookup_date'].astype('datetime64[ns]')

    merged = pd.merge_asof(
        tx_sorted.sort_values('_lookup_date'),
        spy_sorted,
        left_on='_lookup_date',
        right_on='us_date',
        direction='backward'
    )
    merged = merged.sort_values('date').reset_index(drop=True)
    merged = merged.drop(columns=['_lookup_date'])
    print(f"  After SPY alignment: n={len(merged)}, "
          f"SPY coverage={merged['spy_overnight'].notna().mean()*100:.1f}%")
    return merged


# ============================================================
# 4. Backtest
# ============================================================

def backtest(signal, gap_ret, tx_cost):
    """
    signal: 0/1 array (1 = take overnight position)
    gap_ret: TX overnight gross return
    tx_cost: round-trip cost (deducted on every signal=1 day)

    Returns dict of metrics.
    """
    sig = signal.astype(float)
    ret = gap_ret.astype(float)

    gross = ret * sig
    net = gross - tx_cost * sig

    n_days = len(ret)
    n_trades = int(sig.sum())
    if n_trades == 0:
        return {'n_days': n_days, 'n_trades': 0, 'sharpe_gross': 0, 'sharpe_net': 0}

    ann_gross = gross.mean() * 252
    vol_gross = gross.std() * np.sqrt(252)
    sharpe_gross = ann_gross / vol_gross if vol_gross > 0 else 0

    ann_net = net.mean() * 252
    vol_net = net.std() * np.sqrt(252)
    sharpe_net = ann_net / vol_net if vol_net > 0 else 0

    cum_gross = (1 + gross).cumprod()
    cum_net = (1 + net).cumprod()

    def mdd(cum):
        peak = cum.cummax()
        return ((cum - peak) / peak).min()

    # T-test on net returns vs zero
    sig_mask = sig > 0
    if sig_mask.sum() > 10:
        t_net, p_net = stats.ttest_1samp(net[sig_mask], 0)
        t_gross, p_gross = stats.ttest_1samp(gross[sig_mask], 0)
    else:
        t_net, p_net, t_gross, p_gross = 0, 1, 0, 1

    # Win rate
    win_rate_net = (net[sig_mask] > 0).mean() if sig_mask.sum() > 0 else 0
    win_rate_gross = (gross[sig_mask] > 0).mean() if sig_mask.sum() > 0 else 0

    return {
        'n_days': int(n_days),
        'n_trades': int(n_trades),
        'exposure_pct': round(n_trades / n_days * 100, 1),
        'mean_gross_bps': round(gross[sig_mask].mean() * 10000, 2) if sig_mask.sum() > 0 else 0,
        'mean_net_bps': round(net[sig_mask].mean() * 10000, 2) if sig_mask.sum() > 0 else 0,
        'ann_return_gross_pct': round(ann_gross * 100, 3),
        'ann_vol_gross_pct': round(vol_gross * 100, 3),
        'sharpe_gross': round(float(sharpe_gross), 3),
        't_stat_gross': round(float(t_gross), 3),
        'p_val_gross': round(float(p_gross), 4),
        'ann_return_net_pct': round(ann_net * 100, 3),
        'ann_vol_net_pct': round(vol_net * 100, 3),
        'sharpe_net': round(float(sharpe_net), 3),
        't_stat_net': round(float(t_net), 3),
        'p_val_net': round(float(p_net), 4),
        'mdd_gross_pct': round(float(mdd(cum_gross)) * 100, 2),
        'mdd_net_pct': round(float(mdd(cum_net)) * 100, 2),
        'win_rate_gross_pct': round(float(win_rate_gross) * 100, 1),
        'win_rate_net_pct': round(float(win_rate_net) * 100, 1),
        'cum_net': cum_net,  # for plotting
        'cum_gross': cum_gross,
        'net_returns': net,
    }


# ============================================================
# 5. Main
# ============================================================

def main():
    t_start = time.time()
    print("=" * 70)
    print("K1264: TX Futures Overnight Gap Strategy")
    print("=" * 70)

    print("\n[1] Parsing TX tick files...")
    sample_limit = int(os.environ.get('K1264_SAMPLE_LIMIT', '0')) or None
    records = collect_tx_daily(start_date=START_DATE, max_workers=8, sample_limit=sample_limit)
    min_required = 50 if sample_limit else 500
    if len(records) < min_required:
        print(f"  ERROR: only {len(records)} valid records (< {min_required}) — abort")
        return

    print(f"\n[2] Building TX daily df...")
    tx_df = build_tx_df(records)

    print(f"\n[3] Fetching SPY overnight...")
    spy_df = get_spy_overnight()

    print(f"\n[4] Aligning SPY signal (merge_asof, lag=1)...")
    df = align_spy_to_tx(tx_df, spy_df)
    df = df.dropna(subset=['gap_ret', 'spy_overnight']).reset_index(drop=True)
    print(f"  Final aligned dataset: {len(df)} rows, "
          f"{df['date'].min().date()} → {df['date'].max().date()}")

    # Friday → Monday gap analysis
    fri_mon_mask = df['gap_days'] >= 3
    print(f"\n[5] Holiday-gap diagnostics:")
    print(f"  Normal (gap_days==1): n={(df['gap_days']==1).sum()}, "
          f"mean={df.loc[df['gap_days']==1, 'gap_ret'].mean()*10000:.2f} bps")
    print(f"  Friday→Monday (gap_days==3): n={(df['gap_days']==3).sum()}, "
          f"mean={df.loc[df['gap_days']==3, 'gap_ret'].mean()*10000:.2f} bps")
    print(f"  Holiday (gap_days>=4): n={(df['gap_days']>=4).sum()}, "
          f"mean={df.loc[df['gap_days']>=4, 'gap_ret'].mean()*10000:.2f} bps")

    # ========================================
    # Strategies
    # ========================================
    print(f"\n[6] Backtesting strategies (TX_COST round-trip = {TX_COST_RT*10000:.1f} bps)")
    print("-" * 70)

    # S1: unconditional always-overnight
    sig1 = pd.Series(1, index=df.index)
    res1 = backtest(sig1, df['gap_ret'], TX_COST_RT)
    print(f"\n  S1 Unconditional (always overnight):")
    print(f"    Trades: {res1['n_trades']}, exposure: {res1['exposure_pct']}%")
    print(f"    Gross: Sharpe={res1['sharpe_gross']:.3f}, "
          f"AnnRet={res1['ann_return_gross_pct']:.2f}%, t={res1['t_stat_gross']:.2f}")
    print(f"    Net:   Sharpe={res1['sharpe_net']:.3f}, "
          f"AnnRet={res1['ann_return_net_pct']:.2f}%, t={res1['t_stat_net']:.2f}")
    print(f"    MDD net: {res1['mdd_net_pct']:.2f}%, Win rate net: {res1['win_rate_net_pct']:.1f}%")

    # S2: SPY-conditioned
    sig2 = (df['spy_overnight'] > 0).astype(int)
    res2 = backtest(sig2, df['gap_ret'], TX_COST_RT)
    print(f"\n  S2 SPY-conditioned (SPY_overnight(t-1) > 0):")
    print(f"    Trades: {res2['n_trades']}, exposure: {res2['exposure_pct']}%")
    print(f"    Gross: Sharpe={res2['sharpe_gross']:.3f}, "
          f"AnnRet={res2['ann_return_gross_pct']:.2f}%, t={res2['t_stat_gross']:.2f}")
    print(f"    Net:   Sharpe={res2['sharpe_net']:.3f}, "
          f"AnnRet={res2['ann_return_net_pct']:.2f}%, t={res2['t_stat_net']:.2f}")
    print(f"    MDD net: {res2['mdd_net_pct']:.2f}%, Win rate net: {res2['win_rate_net_pct']:.1f}%")

    # H2 conditional uplift test
    avg_uncond = df['gap_ret'].mean() * 10000
    avg_cond = df.loc[sig2 == 1, 'gap_ret'].mean() * 10000
    uplift = avg_cond / avg_uncond if abs(avg_uncond) > 1e-9 else float('nan')
    print(f"\n  H2 (conditional uplift): cond_mean={avg_cond:.2f} bps vs "
          f"uncond_mean={avg_uncond:.2f} bps, ratio={uplift:.2f}")

    # ========================================
    # Cross-OOS (5 yearly windows)
    # ========================================
    print(f"\n[7] Cross-OOS Validation (5 yearly windows)")
    print("-" * 70)

    oos_periods = [
        (2018, '2018-01-01', '2018-12-31'),
        (2020, '2020-01-01', '2020-12-31'),
        (2022, '2022-01-01', '2022-12-31'),
        (2023, '2023-01-01', '2023-12-31'),
        (2024, '2024-01-01', '2024-12-31'),
    ]

    cross_oos = {'unconditional': [], 'spy_conditioned': []}

    for year, start, end in oos_periods:
        sub = df[(df['date'] >= start) & (df['date'] <= end)].reset_index(drop=True)
        if len(sub) < 30:
            print(f"  {year}: only {len(sub)} days — skip")
            continue

        sub_sig1 = pd.Series(1, index=sub.index)
        sub_sig2 = (sub['spy_overnight'] > 0).astype(int)

        r1 = backtest(sub_sig1, sub['gap_ret'], TX_COST_RT)
        r2 = backtest(sub_sig2, sub['gap_ret'], TX_COST_RT)

        cross_oos['unconditional'].append({
            'year': year, 'n_days': r1['n_days'],
            'sharpe_net': r1['sharpe_net'],
            'ann_return_net_pct': r1['ann_return_net_pct'],
            't_stat_net': r1['t_stat_net'],
        })
        cross_oos['spy_conditioned'].append({
            'year': year, 'n_days': r2['n_days'],
            'sharpe_net': r2['sharpe_net'],
            'ann_return_net_pct': r2['ann_return_net_pct'],
            't_stat_net': r2['t_stat_net'],
        })

        print(f"  {year}: S1 net Sharpe={r1['sharpe_net']:+.3f}, "
              f"AnnRet={r1['ann_return_net_pct']:+.2f}% | "
              f"S2 net Sharpe={r2['sharpe_net']:+.3f}, "
              f"AnnRet={r2['ann_return_net_pct']:+.2f}%")

    n_pos_uncond = sum(1 for r in cross_oos['unconditional'] if r['sharpe_net'] > 0)
    n_pos_cond = sum(1 for r in cross_oos['spy_conditioned'] if r['sharpe_net'] > 0)
    n_total = len(cross_oos['unconditional'])

    print(f"\n  Cross-OOS positive:")
    print(f"    Unconditional:  {n_pos_uncond}/{n_total}")
    print(f"    SPY-cond:       {n_pos_cond}/{n_total}")

    # ========================================
    # Three-Gate Listing Decision
    # ========================================
    print(f"\n[8] Three-Gate Listing Decision")
    print("-" * 70)

    def evaluate_gate(name, res, n_pos, n_total):
        gate1 = res['sharpe_net'] > 0.5
        gate2 = abs(res['t_stat_net']) > 3.0
        gate3 = (n_pos / n_total) >= 0.8 if n_total > 0 else False  # 4/5
        passes = sum([gate1, gate2, gate3])
        print(f"\n  {name}:")
        print(f"    Gate 1 (Net Sharpe > 0.5):       {'PASS' if gate1 else 'FAIL'} "
              f"(actual={res['sharpe_net']:.3f})")
        print(f"    Gate 2 (|DM-t| vs 0 > 3.0):      {'PASS' if gate2 else 'FAIL'} "
              f"(actual=|{res['t_stat_net']:.2f}|)")
        print(f"    Gate 3 (Cross-OOS 4/5 same dir): {'PASS' if gate3 else 'FAIL'} "
              f"({n_pos}/{n_total})")
        print(f"    → {passes}/3 gates passed")
        if passes == 3:
            verdict = "LIST"
        elif passes >= 2 and gate1:
            verdict = "CONDITIONAL"
        else:
            verdict = "REJECT"
        print(f"    Verdict: {verdict}")
        return {'gate1': gate1, 'gate2': gate2, 'gate3': gate3, 'passes': passes, 'verdict': verdict}

    gates_uncond = evaluate_gate("S1 Unconditional", res1, n_pos_uncond, n_total)
    gates_cond = evaluate_gate("S2 SPY-conditioned", res2, n_pos_cond, n_total)

    # ========================================
    # Charts
    # ========================================
    print(f"\n[9] Generating charts...")
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        # Chart 1: cumulative net return curve
        fig, ax = plt.subplots(figsize=(11, 6))
        ax.plot(df['date'], res1['cum_net'].values, label=f"S1 Unconditional (Sharpe={res1['sharpe_net']:.2f})",
                color='steelblue', linewidth=1.5)
        ax.plot(df['date'], res2['cum_net'].values, label=f"S2 SPY-conditioned (Sharpe={res2['sharpe_net']:.2f})",
                color='darkorange', linewidth=1.5)
        ax.axhline(1.0, color='gray', linestyle='--', linewidth=0.8)
        ax.set_xlabel('Date')
        ax.set_ylabel('Cumulative Net Return')
        ax.set_title(f'K1264 TX Overnight Gap — Cumulative Net Return (cost={TX_COST_RT*10000:.0f}bp RT)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        chart1_path = os.path.join(OUT_DIR, 'k1264_cumulative_return.png')
        plt.savefig(chart1_path, dpi=120)
        plt.close()
        print(f"    Saved: {chart1_path}")

        # Chart 2: cross-OOS Sharpe bar chart
        years = [r['year'] for r in cross_oos['unconditional']]
        s1_sharpes = [r['sharpe_net'] for r in cross_oos['unconditional']]
        s2_sharpes = [r['sharpe_net'] for r in cross_oos['spy_conditioned']]

        x = np.arange(len(years))
        width = 0.35
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(x - width/2, s1_sharpes, width, label='S1 Unconditional', color='steelblue')
        ax.bar(x + width/2, s2_sharpes, width, label='S2 SPY-conditioned', color='darkorange')
        ax.axhline(0.5, color='red', linestyle='--', linewidth=0.8, label='Listing Sharpe gate (0.5)')
        ax.axhline(0.0, color='black', linewidth=0.5)
        ax.set_xticks(x)
        ax.set_xticklabels(years)
        ax.set_xlabel('OOS Year Window')
        ax.set_ylabel('Net Sharpe')
        ax.set_title('K1264 Cross-OOS Net Sharpe by Year')
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        plt.tight_layout()
        chart2_path = os.path.join(OUT_DIR, 'k1264_cross_oos_bar.png')
        plt.savefig(chart2_path, dpi=120)
        plt.close()
        print(f"    Saved: {chart2_path}")
    except Exception as e:
        print(f"    Chart generation failed: {e}")

    # ========================================
    # Save Results JSON
    # ========================================
    print(f"\n[10] Saving results JSON...")

    # Strip pandas Series before JSON serialization
    def strip_series(d):
        return {k: v for k, v in d.items() if not isinstance(v, (pd.Series, pd.DataFrame, np.ndarray))}

    elapsed = time.time() - t_start
    results = {
        'experiment_id': 'K1264',
        'title': 'TX Futures Overnight Gap Strategy',
        'attribution': '[提出: 用戶, 執行: Claude]',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'data_source': 'TAIFEX TX tick CSVs (~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_*TX.csv)',
        'data_period': {
            'start': str(df['date'].min().date()),
            'end': str(df['date'].max().date()),
            'n_trading_days': int(len(df)),
        },
        'tx_cost_round_trip_bps': TX_COST_RT * 10000,
        'methodology': {
            'signal_lag': 'SPY_overnight(t-1) → TX position closed-to-open from t to t+1',
            'session': 'Day session ONLY (08:45-13:45) — no night session',
            'expiry_filter': 'max-volume expiry on day session per file',
            'random_seed': 42,
        },
        'holiday_gap_diagnostics': {
            'normal_1day_n': int((df['gap_days']==1).sum()),
            'normal_1day_mean_bps': round(df.loc[df['gap_days']==1, 'gap_ret'].mean()*10000, 2),
            'fri_to_mon_n': int((df['gap_days']==3).sum()),
            'fri_to_mon_mean_bps': round(df.loc[df['gap_days']==3, 'gap_ret'].mean()*10000, 2),
            'holiday_n': int((df['gap_days']>=4).sum()),
            'holiday_mean_bps': round(df.loc[df['gap_days']>=4, 'gap_ret'].mean()*10000, 2),
        },
        'gap_diagnostics': {
            'mean_bps': round(float(df['gap_ret'].mean()*10000), 2),
            'std_bps': round(float(df['gap_ret'].std()*10000), 2),
            'median_bps': round(float(df['gap_ret'].median()*10000), 2),
            'skew': round(float(df['gap_ret'].skew()), 3),
            'kurtosis': round(float(df['gap_ret'].kurtosis()), 3),
            'pct_positive': round(float((df['gap_ret']>0).mean()*100), 1),
            'sharpe_no_cost': round(float(df['gap_ret'].mean()*252 / (df['gap_ret'].std()*np.sqrt(252))), 3),
        },
        'strategy_S1_unconditional': strip_series(res1),
        'strategy_S2_spy_conditioned': strip_series(res2),
        'h2_conditional_uplift': {
            'unconditional_mean_bps': round(float(avg_uncond), 2),
            'conditional_mean_bps': round(float(avg_cond), 2),
            'ratio': round(float(uplift), 3),
            'passes_1_5x': bool(uplift >= 1.5),
        },
        'cross_oos': {
            'unconditional': cross_oos['unconditional'],
            'spy_conditioned': cross_oos['spy_conditioned'],
            'n_pos_uncond': n_pos_uncond,
            'n_pos_cond': n_pos_cond,
            'n_total': n_total,
        },
        'gates_unconditional': gates_uncond,
        'gates_spy_conditioned': gates_cond,
        'verdict': {
            'unconditional': gates_uncond['verdict'],
            'spy_conditioned': gates_cond['verdict'],
            'listing_recommendation': (
                'YES' if (gates_uncond['verdict'] == 'LIST' or gates_cond['verdict'] == 'LIST')
                else ('CONDITIONAL' if (gates_uncond['verdict'] == 'CONDITIONAL' or gates_cond['verdict'] == 'CONDITIONAL')
                      else 'NO')
            ),
        },
        'references': [
            'K515: SPY ETF overnight gap alpha 10.73bp/day t=4.06 (源頭 finding)',
            'K625: SPY ETF cost-killing 18.55bp round-trip',
            'K843: TAIFEX tick parsing pattern (max-volume expiry, Big5 encoding)',
            'Lou, Polk, Skouras (2019) JFE: Overnight vs Intraday Returns',
        ],
        'limitations': [
            'TX cost 5bp round-trip 是 typical retail 假設 — 實際視 broker 而定',
            '仍未考慮 slippage（fill at exact open/close 假設）',
            'Day-session-only 排除夜盤 information 但避開 night noise',
            'OOS years (2018/2020/2022/2023/2024) 涵蓋多種 regime 但不含 2017 部分樣本',
        ],
        'elapsed_seconds': round(elapsed, 1),
    }

    out_json = os.path.join(OUT_DIR, 'k1264_results.json')
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"    Saved: {out_json}")

    print(f"\n[11] DONE. Elapsed: {elapsed:.0f}s")
    print("=" * 70)
    print(f"FINAL VERDICT:")
    print(f"  S1 Unconditional: {gates_uncond['verdict']} ({gates_uncond['passes']}/3 gates)")
    print(f"  S2 SPY-cond:      {gates_cond['verdict']} ({gates_cond['passes']}/3 gates)")
    print(f"  Listing recommendation: {results['verdict']['listing_recommendation']}")
    print("=" * 70)


if __name__ == '__main__':
    main()
