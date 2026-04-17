#!/usr/bin/env python3
"""
K845: TX Futures VT Strategy Listing Evaluation
================================================
Evaluate whether TX VT (8.63/VIX on TX Futures) meets the 5 listing criteria
defined in CLAUDE.md for strategy onboarding.

5 Listing Criteria:
  1. Same-period comparison: Sharpe >= median of listed strategies
  2. Cross-OOS: 5 non-overlapping 2-year periods, beat BH 50/50 SPY/GLD >= 3/5
  3. Codex review: No HIGH severity bugs (done by main thread, not here)
  4. Sensitivity: parameter ±20% → Sharpe drop < 30%
  5. MDD: Same-period MDD < -20%

Data: TAIFEX TX tick data + yfinance (^VIX, 0050.TW, SPY, GLD)
Period: 2017-05-16 ~ 2026-04-02

Error log rules applied:
  - 0050.TW: must use clean_tw50_data
  - signal.shift(1): VIX uses previous day
  - DM test: use volpred.stats.model_evaluation.strategy_dm_test
  - Sharpe > 2x baseline = likely bug, investigate first

References:
  - K844: TX Futures VT vs 0050.TW Stock VT (baseline experiment)
  - K817: US→Taiwan spillover, 77-93% alpha in overnight gap

[提出: 用戶(上架評估), 執行: Claude]
Author: VolPred Research System
Date: 2026-04-03
"""

import os
import sys
import json
import glob
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
TAIFEX_DIR = '/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python'
NIGHT_SESSION_START_DATE = 20170516
VIX_ANCHOR = 8.63
MIN_FILE_SIZE = 100
FUTURES_TX_COST_PCT = 0.0001   # 2 ticks round-trip ≈ 0.01%
STOCK_TX_COST_PCT = 0.0034     # 0.34% round-trip for 0050.TW

# Time boundaries (HHMMSS format)
NIGHT_PM_START = 150000
NIGHT_PM_END = 235959
NIGHT_AM_START = 0
NIGHT_AM_END = 50000
DAY_START = 84500
DAY_END = 134500

# Paper trading common start for Test 1
COMMON_START = "2023-01-04"

# ============================================================
# TX Data Loading (reuse K844 logic)
# ============================================================

def parse_tx_file(filepath):
    """Parse a TX file, extract night/day session prices for near-month contract."""
    try:
        fsize = os.path.getsize(filepath)
        if fsize < MIN_FILE_SIZE:
            return None

        df = pd.read_csv(filepath, encoding='big5', low_memory=False)
        if len(df) < 2:
            return None

        col_product = df.columns[1]
        df = df[df[col_product].str.strip() == 'TX']
        if df.empty:
            return None

        col_date = df.columns[0]
        col_expiry = df.columns[2]
        col_time = df.columns[3]
        col_price = df.columns[4]
        col_volume = df.columns[5]

        df['price'] = pd.to_numeric(df[col_price], errors='coerce')
        df['volume'] = pd.to_numeric(df[col_volume].apply(lambda x: str(x).replace(',', '')), errors='coerce')
        df['time_int'] = pd.to_numeric(df[col_time], errors='coerce').astype('Int64')
        df['trade_date'] = pd.to_numeric(df[col_date], errors='coerce').astype('Int64')
        df['expiry'] = df[col_expiry].astype(str).str.strip()
        df = df.dropna(subset=['price', 'time_int'])

        if len(df) == 0:
            return None

        vol_by_exp = df.groupby('expiry')['volume'].sum()
        near_month = vol_by_exp.idxmax()
        df = df[df['expiry'] == near_month].copy()

        basename = os.path.basename(filepath)
        parts = basename.replace('Daily_', '').replace('TX.csv', '').split('_')
        file_date = int(''.join(parts))

        t = df['time_int'].values
        prices = df['price'].values
        volumes = df['volume'].values

        result = {'file_date': file_date, 'near_month': near_month}

        # Night session
        night_pm_mask = (t >= NIGHT_PM_START) & (t <= NIGHT_PM_END)
        night_am_mask = (t >= NIGHT_AM_START) & (t <= NIGHT_AM_END)
        night_mask = night_pm_mask | night_am_mask
        night_prices = prices[night_mask]
        night_times = t[night_mask]

        if len(night_prices) >= 2:
            sort_key = np.where(night_times >= NIGHT_PM_START, night_times - 240000, night_times)
            sort_idx = np.argsort(sort_key)
            night_prices = night_prices[sort_idx]
            result['night_open'] = float(night_prices[0])
            result['night_close'] = float(night_prices[-1])

        # Day session
        day_mask = (t >= DAY_START) & (t <= DAY_END)
        day_prices = prices[day_mask]
        day_times = t[day_mask]

        if len(day_prices) >= 2:
            sort_idx = np.argsort(day_times)
            day_prices = day_prices[sort_idx]
            result['day_open'] = float(day_prices[0])
            result['day_close'] = float(day_prices[-1])

        return result
    except Exception:
        return None


def load_tx_data(n_workers=8):
    """Load all TX files in parallel."""
    pattern = os.path.join(TAIFEX_DIR, 'Daily_*TX.csv')
    all_files = sorted(glob.glob(pattern))

    valid_files = []
    for f in all_files:
        basename = os.path.basename(f)
        if not basename.endswith('TX.csv'):
            continue
        parts = basename.replace('Daily_', '').replace('TX.csv', '').split('_')
        try:
            fdate = int(''.join(parts))
            if fdate >= NIGHT_SESSION_START_DATE:
                valid_files.append(f)
        except ValueError:
            continue

    print(f"Loading {len(valid_files)} TX files from {NIGHT_SESSION_START_DATE}...")
    t0 = time.time()

    results = []
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(parse_tx_file, f): f for f in valid_files}
        for future in as_completed(futures):
            r = future.result()
            if r is not None:
                results.append(r)

    tx_df = pd.DataFrame(results)
    tx_df = tx_df.sort_values('file_date').reset_index(drop=True)
    print(f"  Loaded {len(tx_df)} trading days in {time.time()-t0:.1f}s")

    tx_df['date'] = pd.to_datetime(tx_df['file_date'].astype(str), format='%Y%m%d')
    return tx_df


def load_market_data():
    """Load VIX, 0050.TW, SPY, GLD from yfinance."""
    import yfinance as yf
    from volpred.utils import clean_tw50_data

    print("\nLoading market data from yfinance...")

    # VIX
    vix = yf.download('^VIX', start='2017-01-01', end='2026-12-31', progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix_close = vix['Close'].squeeze()
    if isinstance(vix_close, pd.DataFrame):
        vix_close = vix_close.iloc[:, 0]
    vix_close.index = pd.to_datetime(vix_close.index).tz_localize(None)

    # 0050.TW
    tw50 = yf.download('0050.TW', start='2017-01-01', end='2026-12-31', progress=False)
    if isinstance(tw50.columns, pd.MultiIndex):
        tw50.columns = tw50.columns.get_level_values(0)
    tw50_close = tw50['Close'].squeeze()
    if isinstance(tw50_close, pd.DataFrame):
        tw50_close = tw50_close.iloc[:, 0]
    tw50_close.index = pd.to_datetime(tw50_close.index).tz_localize(None)
    tw50_prices, tw50_returns = clean_tw50_data(tw50_close)

    # SPY + GLD for BH 50/50 benchmark
    spy = yf.download('SPY', start='2017-01-01', end='2026-12-31', progress=False)
    gld = yf.download('GLD', start='2017-01-01', end='2026-12-31', progress=False)
    for d in [spy, gld]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    spy_close = spy['Close'].squeeze()
    gld_close = gld['Close'].squeeze()
    if isinstance(spy_close, pd.DataFrame):
        spy_close = spy_close.iloc[:, 0]
    if isinstance(gld_close, pd.DataFrame):
        gld_close = gld_close.iloc[:, 0]
    spy_close.index = pd.to_datetime(spy_close.index).tz_localize(None)
    gld_close.index = pd.to_datetime(gld_close.index).tz_localize(None)

    spy_ret = spy_close.pct_change().dropna()
    gld_ret = gld_close.pct_change().dropna()

    print(f"  VIX: {len(vix_close)} days, 0050.TW: {len(tw50_prices)} days")
    print(f"  SPY: {len(spy_ret)} days, GLD: {len(gld_ret)} days")

    return vix_close, tw50_prices, tw50_returns, spy_ret, gld_ret


def calc_metrics(rets):
    """Calculate standard performance metrics from daily returns."""
    rets = np.array(rets)
    n = len(rets)
    if n < 20:
        return None

    ann_ret = np.mean(rets) * 252
    ann_vol = np.std(rets, ddof=1) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1
    mdd = float(np.min(dd))

    years = n / 252
    cagr = cum[-1] ** (1 / years) - 1 if years > 0 else 0
    calmar = cagr / abs(mdd) if mdd != 0 else 0
    total_ret = cum[-1] - 1

    return {
        'n_days': n,
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
        'cagr': float(cagr),
        'total_return': float(total_ret),
        'calmar': float(calmar),
    }


def run_tx_vt_strategy(merged, vix_anchor, tx_cost_pct=FUTURES_TX_COST_PCT):
    """Run 8.63/VIX (or custom anchor) on TX futures full-day return.

    Returns Series of daily strategy returns.
    """
    weight = np.minimum(vix_anchor / merged['vix_t1'], 1.0)
    # signal.shift(1) is already built into vix_t1 (which is VIX from T-1)
    tc = abs(weight - weight.shift(1).fillna(1.0)) * tx_cost_pct
    strat_ret = weight * merged['full_day_ret'] - tc
    return strat_ret, weight


# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    print("=" * 70)
    print("K845: TX Futures VT Strategy Listing Evaluation")
    print("=" * 70)
    t_start = time.time()

    # ----------------------------------------------------------
    # Load data
    # ----------------------------------------------------------
    tx_df = load_tx_data(n_workers=8)
    vix_close, tw50_prices, tw50_returns, spy_ret, gld_ret = load_market_data()

    # Compute TX returns
    tx_df['night_ret'] = np.where(
        tx_df['night_open'].notna() & (tx_df['night_open'] > 0),
        (tx_df['night_close'] - tx_df['night_open']) / tx_df['night_open'],
        np.nan
    )
    tx_df['day_ret'] = np.where(
        tx_df['day_open'].notna() & (tx_df['day_open'] > 0),
        (tx_df['day_close'] - tx_df['day_open']) / tx_df['day_open'],
        np.nan
    )
    tx_df['gap_ret'] = np.where(
        tx_df['night_close'].notna() & tx_df['day_open'].notna() & (tx_df['night_close'] > 0),
        (tx_df['day_open'] - tx_df['night_close']) / tx_df['night_close'],
        np.nan
    )
    tx_df['full_day_ret'] = np.where(
        tx_df['night_ret'].notna() & tx_df['gap_ret'].notna() & tx_df['day_ret'].notna(),
        (1 + tx_df['night_ret']) * (1 + tx_df['gap_ret']) * (1 + tx_df['day_ret']) - 1,
        np.nan
    )
    tx_df['tx_c2c_ret'] = tx_df['day_close'].pct_change()

    # Merge
    merged = tx_df[['date', 'night_open', 'night_close', 'day_open', 'day_close',
                     'night_ret', 'day_ret', 'gap_ret', 'full_day_ret', 'tx_c2c_ret']].copy()
    merged = merged.set_index('date')

    # Add VIX(T-1)
    vix_series = vix_close.copy()
    vix_dates = sorted(vix_series.index)
    vix_for_day = {}
    for date in merged.index:
        prev_vix = [d for d in vix_dates if d < date]
        if len(prev_vix) >= 1:
            vix_for_day[date] = float(vix_series.loc[prev_vix[-1]])
    merged['vix_t1'] = pd.Series(vix_for_day)

    # Add 0050.TW return
    tw50_ret_series = tw50_returns.copy()
    tw50_ret_series.index = pd.to_datetime(tw50_ret_series.index).tz_localize(None)
    merged['tw50_ret'] = tw50_ret_series.reindex(merged.index)

    # Add BH 50/50 SPY/GLD return (on TW trading dates)
    spy_ret_aligned = spy_ret.reindex(merged.index)
    gld_ret_aligned = gld_ret.reindex(merged.index)
    # For TW dates where US didn't trade, use 0 (US market closed)
    merged['spy_ret'] = spy_ret_aligned.fillna(0)
    merged['gld_ret'] = gld_ret_aligned.fillna(0)
    merged['bh5050_ret'] = 0.5 * merged['spy_ret'] + 0.5 * merged['gld_ret']

    # Drop missing critical data
    merged_full = merged.dropna(subset=['vix_t1', 'full_day_ret']).copy()
    print(f"\nMerged dataset: {len(merged_full)} trading days")
    print(f"  Period: {merged_full.index[0].date()} to {merged_full.index[-1].date()}")

    # Run TX VT strategy (baseline anchor = 8.63)
    merged_full['tx_vt_ret'], merged_full['tx_vt_weight'] = run_tx_vt_strategy(merged_full, VIX_ANCHOR)

    # Run 0050.TW VT for comparison
    w_tw = np.minimum(VIX_ANCHOR / merged_full['vix_t1'], 1.0)
    tc_tw = abs(w_tw - w_tw.shift(1).fillna(1.0)) * STOCK_TX_COST_PCT
    merged_full['tw_vt_ret'] = w_tw * merged_full['tw50_ret'].fillna(0) - tc_tw

    # ============================================================
    # TEST 1: Same-Period Comparison (COMMON_START ~ today)
    # ============================================================
    print("\n" + "=" * 70)
    print("TEST 1: Same-Period Comparison (since COMMON_START)")
    print("=" * 70)

    # Load existing strategy metrics
    pt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'storage', 'paper_trading.json')
    pt = json.loads(open(pt_path).read())

    existing_sharpes = {}
    for sid, strat in pt.items():
        if sid.startswith("_"):
            continue
        entries = strat.get("entries", [])
        returns = []
        for e in entries:
            td = e.get("data_date") or e.get("trade_date", "")
            ret = e.get("portfolio_return")
            if td >= COMMON_START and ret is not None:
                returns.append(ret)
        if len(returns) < 50:
            continue
        m = calc_metrics(returns)
        if m:
            existing_sharpes[sid] = m['sharpe']

    # TX VT on same period
    same_period = merged_full.loc[merged_full.index >= COMMON_START]
    tx_vt_same = same_period['tx_vt_ret'].dropna()
    tx_vt_metrics = calc_metrics(tx_vt_same.values)

    median_sharpe = np.median(list(existing_sharpes.values()))
    sorted_sharpes = sorted(existing_sharpes.items(), key=lambda x: x[1], reverse=True)

    print(f"\n  Existing strategies Sharpe (from {COMMON_START}):")
    for sid, s in sorted_sharpes:
        print(f"    {sid}: {s:.3f}")
    print(f"\n  Median Sharpe: {median_sharpe:.3f}")
    print(f"  TX VT Sharpe (same period): {tx_vt_metrics['sharpe']:.3f}")
    print(f"  TX VT MDD (same period): {tx_vt_metrics['mdd']*100:.1f}%")

    test1_pass = tx_vt_metrics['sharpe'] >= median_sharpe
    print(f"\n  TEST 1 RESULT: {'PASS' if test1_pass else 'FAIL'} (Sharpe {tx_vt_metrics['sharpe']:.3f} {'≥' if test1_pass else '<'} median {median_sharpe:.3f})")

    # ============================================================
    # TEST 2: Cross-OOS (5 non-overlapping 2-year periods)
    # ============================================================
    print("\n" + "=" * 70)
    print("TEST 2: Cross-OOS (5 non-overlapping 2-year periods)")
    print("=" * 70)

    # TX data starts 2017-05, so we use:
    # Period 1: 2017-06 to 2019-05 (first full 2 years)
    # Period 2: 2019-06 to 2021-05
    # Period 3: 2021-06 to 2023-05
    # Period 4: 2023-06 to 2025-05
    # Period 5: 2025-06 to 2026-04 (partial, ~10 months)
    # Alternative: standard calendar years
    oos_periods = [
        ('2017-06-01', '2019-05-31', '2017H2-2019H1'),
        ('2019-06-01', '2021-05-31', '2019H2-2021H1'),
        ('2021-06-01', '2023-05-31', '2021H2-2023H1'),
        ('2023-06-01', '2025-05-31', '2023H2-2025H1'),
        ('2025-06-01', '2026-12-31', '2025H2-2026'),  # partial
    ]

    oos_results = {}
    tx_wins_vs_bh5050 = 0
    total_valid_periods = 0

    for start, end, label in oos_periods:
        mask = (merged_full.index >= start) & (merged_full.index <= end)
        sub = merged_full.loc[mask]

        if len(sub) < 100:
            print(f"\n  {label}: Only {len(sub)} days, SKIPPED (need >= 100)")
            continue

        total_valid_periods += 1

        # TX VT returns
        tx_vt_rets = sub['tx_vt_ret'].dropna()
        bh5050_rets = sub['bh5050_ret'].dropna()
        tw_vt_rets = sub['tw_vt_ret'].dropna()

        tx_m = calc_metrics(tx_vt_rets.values)
        bh_m = calc_metrics(bh5050_rets.values)
        tw_m = calc_metrics(tw_vt_rets.values) if len(tw_vt_rets) >= 20 else None

        if tx_m and bh_m:
            wins = tx_m['sharpe'] > bh_m['sharpe']
            if wins:
                tx_wins_vs_bh5050 += 1

            oos_results[label] = {
                'n_days': len(sub),
                'tx_vt_sharpe': tx_m['sharpe'],
                'tx_vt_mdd': tx_m['mdd'],
                'bh5050_sharpe': bh_m['sharpe'],
                'bh5050_mdd': bh_m['mdd'],
                'tw_vt_sharpe': tw_m['sharpe'] if tw_m else None,
                'tw_vt_mdd': tw_m['mdd'] if tw_m else None,
                'tx_vt_wins': wins,
            }

            print(f"\n  {label} ({len(sub)} days):")
            print(f"    TX VT:     Sharpe={tx_m['sharpe']:.3f}, MDD={tx_m['mdd']*100:.1f}%")
            print(f"    BH 50/50:  Sharpe={bh_m['sharpe']:.3f}, MDD={bh_m['mdd']*100:.1f}%")
            if tw_m:
                print(f"    0050 VT:   Sharpe={tw_m['sharpe']:.3f}, MDD={tw_m['mdd']*100:.1f}%")
            print(f"    TX VT {'WINS' if wins else 'LOSES'} vs BH 50/50")

    test2_pass = tx_wins_vs_bh5050 >= 3
    print(f"\n  Summary: TX VT wins {tx_wins_vs_bh5050}/{total_valid_periods} periods vs BH 50/50")
    print(f"  TEST 2 RESULT: {'PASS' if test2_pass else 'FAIL'} (need >= 3/5, got {tx_wins_vs_bh5050}/{total_valid_periods})")

    # ============================================================
    # TEST 3: Codex Review (placeholder - done externally)
    # ============================================================
    print("\n" + "=" * 70)
    print("TEST 3: Codex Review")
    print("=" * 70)
    print("  → Done externally by main thread Claude")
    print("  → Status: PENDING")

    # ============================================================
    # TEST 4: Sensitivity (VIX anchor ±20%)
    # ============================================================
    print("\n" + "=" * 70)
    print("TEST 4: Sensitivity Analysis (VIX anchor ±20%)")
    print("=" * 70)

    base_anchor = VIX_ANCHOR
    anchors_to_test = {
        f'{base_anchor:.2f} (base)': base_anchor,
        f'{base_anchor*0.8:.2f} (-20%)': base_anchor * 0.8,
        f'{base_anchor*1.2:.2f} (+20%)': base_anchor * 1.2,
        f'{base_anchor*0.9:.2f} (-10%)': base_anchor * 0.9,
        f'{base_anchor*1.1:.2f} (+10%)': base_anchor * 1.1,
    }

    sensitivity_results = {}
    base_sharpe = None

    for label, anchor in anchors_to_test.items():
        strat_ret, _ = run_tx_vt_strategy(merged_full, anchor)
        m = calc_metrics(strat_ret.dropna().values)
        if m:
            sensitivity_results[label] = {
                'anchor': float(anchor),
                'sharpe': m['sharpe'],
                'mdd': m['mdd'],
                'ann_return': m['ann_return'],
                'ann_vol': m['ann_vol'],
            }
            if 'base' in label:
                base_sharpe = m['sharpe']
            print(f"  {label}: Sharpe={m['sharpe']:.3f}, MDD={m['mdd']*100:.1f}%, AnnRet={m['ann_return']*100:.1f}%")

    # Check if ±20% Sharpe drops > 30%
    max_drop = 0
    worst_case = ""
    for label, res in sensitivity_results.items():
        if 'base' in label:
            continue
        if base_sharpe and base_sharpe > 0:
            drop = (base_sharpe - res['sharpe']) / base_sharpe * 100
            if drop > max_drop:
                max_drop = drop
                worst_case = label
            print(f"    {label}: Sharpe change = {(res['sharpe']-base_sharpe)/base_sharpe*100:+.1f}%")

    test4_pass = max_drop < 30
    print(f"\n  Worst case: {worst_case} with {max_drop:.1f}% Sharpe drop")
    print(f"  TEST 4 RESULT: {'PASS' if test4_pass else 'FAIL'} (max drop {max_drop:.1f}% {'<' if test4_pass else '>='} 30%)")

    # ============================================================
    # TEST 5: MDD Check
    # ============================================================
    print("\n" + "=" * 70)
    print("TEST 5: MDD Check")
    print("=" * 70)

    # Full period MDD
    full_metrics = calc_metrics(merged_full['tx_vt_ret'].dropna().values)
    full_mdd = full_metrics['mdd']

    # Same-period MDD
    same_mdd = tx_vt_metrics['mdd']

    print(f"  Full period MDD: {full_mdd*100:.1f}%")
    print(f"  Same period (from {COMMON_START}) MDD: {same_mdd*100:.1f}%")

    test5_pass_full = full_mdd > -0.20  # MDD > -20% (less negative = better)
    test5_pass_same = same_mdd > -0.20
    test5_pass = test5_pass_full and test5_pass_same

    print(f"  TEST 5 RESULT (full period): {'PASS' if test5_pass_full else 'FAIL'} (MDD {full_mdd*100:.1f}% {'>' if test5_pass_full else '<='} -20%)")
    print(f"  TEST 5 RESULT (same period): {'PASS' if test5_pass_same else 'FAIL'} (MDD {same_mdd*100:.1f}% {'>' if test5_pass_same else '<='} -20%)")

    # ============================================================
    # DM Tests (supplementary)
    # ============================================================
    print("\n" + "=" * 70)
    print("Supplementary: DM Tests")
    print("=" * 70)

    from volpred.stats.model_evaluation import strategy_dm_test

    dm_tests = {}
    dm_pairs = [
        ('TX VT vs BH 50/50', 'tx_vt_ret', 'bh5050_ret'),
        ('TX VT vs 0050 VT', 'tx_vt_ret', 'tw_vt_ret'),
    ]

    for label, col_a, col_b in dm_pairs:
        a = merged_full[col_a].dropna()
        b = merged_full[col_b].dropna()
        common = a.index.intersection(b.index)
        a = a.loc[common]
        b = b.loc[common]

        if len(a) < 100:
            print(f"  {label}: Insufficient data ({len(a)} days)")
            continue

        try:
            dm_stat, dm_pval = strategy_dm_test(a.values, b.values)
            harvey_pass = abs(dm_stat) > 3.0
            dm_tests[label] = {
                'dm_stat': float(dm_stat),
                'p_value': float(dm_pval),
                'harvey_pass': harvey_pass,
            }
            print(f"  {label}: DM={dm_stat:.3f}, p={dm_pval:.4f}, Harvey {'PASS' if harvey_pass else 'FAIL'}")
        except Exception as e:
            print(f"  {label}: DM test error - {e}")
            diff = a.values - b.values
            t_stat, p_val = stats.ttest_1samp(diff, 0)
            dm_tests[label] = {
                'dm_stat': float(t_stat),
                'p_value': float(p_val),
                'harvey_pass': abs(t_stat) > 3.0,
                'note': 'fallback t-test',
            }
            print(f"  {label}: t-test={t_stat:.3f}, p={p_val:.4f}")

    # ============================================================
    # SUMMARY
    # ============================================================
    print("\n" + "=" * 70)
    print("LISTING EVALUATION SUMMARY")
    print("=" * 70)

    results_summary = {
        'test_1_same_period': {
            'pass': test1_pass,
            'tx_vt_sharpe': tx_vt_metrics['sharpe'],
            'median_sharpe': float(median_sharpe),
            'tx_vt_mdd': tx_vt_metrics['mdd'],
            'period': f"{COMMON_START} ~ {merged_full.index[-1].date()}",
            'existing_sharpes': existing_sharpes,
        },
        'test_2_cross_oos': {
            'pass': test2_pass,
            'wins_vs_bh5050': tx_wins_vs_bh5050,
            'total_periods': total_valid_periods,
            'detail': oos_results,
        },
        'test_3_codex': {
            'pass': None,  # Pending
            'note': 'To be done by main thread',
        },
        'test_4_sensitivity': {
            'pass': test4_pass,
            'max_sharpe_drop_pct': float(max_drop),
            'worst_case': worst_case,
            'detail': sensitivity_results,
        },
        'test_5_mdd': {
            'pass': test5_pass,
            'full_period_mdd': float(full_mdd),
            'same_period_mdd': float(same_mdd),
        },
    }

    all_pass = test1_pass and test2_pass and test4_pass and test5_pass
    # test3 is pending

    print(f"\n  Test 1 (Same-period Sharpe): {'✓ PASS' if test1_pass else '✗ FAIL'}")
    print(f"  Test 2 (Cross-OOS):          {'✓ PASS' if test2_pass else '✗ FAIL'}")
    print(f"  Test 3 (Codex Review):        PENDING")
    print(f"  Test 4 (Sensitivity):         {'✓ PASS' if test4_pass else '✗ FAIL'}")
    print(f"  Test 5 (MDD < -20%):          {'✓ PASS' if test5_pass else '✗ FAIL'}")
    print(f"\n  Overall (excl. Codex): {'ALL PASS' if all_pass else 'NOT ALL PASS'}")

    # Full performance summary
    print(f"\n  Full Period Performance:")
    print(f"    TX VT: Sharpe={full_metrics['sharpe']:.3f}, CAGR={full_metrics['cagr']*100:.1f}%, MDD={full_metrics['mdd']*100:.1f}%")
    print(f"    Period: {merged_full.index[0].date()} ~ {merged_full.index[-1].date()} ({full_metrics['n_days']} days)")

    # Sanity check: Sharpe > 2x any baseline?
    bh5050_full = calc_metrics(merged_full['bh5050_ret'].dropna().values)
    if bh5050_full and full_metrics['sharpe'] > 2 * bh5050_full['sharpe']:
        print(f"\n  ⚠️ WARNING: TX VT Sharpe ({full_metrics['sharpe']:.3f}) > 2x BH 50/50 ({bh5050_full['sharpe']:.3f}) — INVESTIGATE FOR BUGS")

    # ============================================================
    # Save results
    # ============================================================
    final_results = {
        'experiment_id': 'K845',
        'title': 'TX Futures VT Strategy Listing Evaluation',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'TAIFEX TX tick data + yfinance (^VIX, 0050.TW, SPY, GLD)',
        'period': f"{merged_full.index[0].date()} to {merged_full.index[-1].date()}",
        'n_days': int(len(merged_full)),
        'strategy': '8.63/VIX on TX Futures full-day return',
        'vix_anchor': VIX_ANCHOR,
        'tx_cost_pct': FUTURES_TX_COST_PCT,
        'listing_evaluation': results_summary,
        'all_tests_pass_excl_codex': all_pass,
        'full_period_metrics': full_metrics,
        'same_period_metrics': {k: v for k, v in tx_vt_metrics.items()},
        'dm_tests': dm_tests,
        'bh5050_full_metrics': bh5050_full,
        'conclusion': '',
        'limitations': [
            'TX futures do not include dividends (~2-3%/yr gap vs 0050.TW total return)',
            'TX roll costs (~12 rolls/year) not explicitly modeled',
            'Night session liquidity ~57% of day session',
            'BH 50/50 SPY/GLD benchmark uses USD returns, not TWD — currency effect not modeled',
            'Data starts 2017-05 (night session inception), no pre-2017 data',
            'Period 5 of Cross-OOS may be partial',
        ],
        'references': ['K844: TX Futures VT vs 0050.TW Stock VT', 'K817: US→TW spillover'],
    }

    # Build conclusion
    if all_pass:
        conclusion = f"TX VT strategy PASSES all 4 automated listing criteria (Codex pending). "
        conclusion += f"Same-period Sharpe {tx_vt_metrics['sharpe']:.3f} >= median {median_sharpe:.3f}. "
        conclusion += f"Cross-OOS: {tx_wins_vs_bh5050}/{total_valid_periods} wins vs BH 50/50. "
        conclusion += f"Sensitivity: max Sharpe drop {max_drop:.1f}% < 30%. "
        conclusion += f"MDD: {full_mdd*100:.1f}% > -20%."
    else:
        fails = []
        if not test1_pass:
            fails.append(f"Test 1 (Sharpe {tx_vt_metrics['sharpe']:.3f} < median {median_sharpe:.3f})")
        if not test2_pass:
            fails.append(f"Test 2 (Cross-OOS {tx_wins_vs_bh5050}/{total_valid_periods} < 3/5)")
        if not test4_pass:
            fails.append(f"Test 4 (max Sharpe drop {max_drop:.1f}% >= 30%)")
        if not test5_pass:
            fails.append(f"Test 5 (MDD {full_mdd*100:.1f}% <= -20%)")
        conclusion = f"TX VT strategy FAILS listing: {'; '.join(fails)}."

    final_results['conclusion'] = conclusion
    print(f"\n  CONCLUSION: {conclusion}")

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'k845_tx_vt_listing_eval_results.json')
    with open(output_path, 'w') as f:
        json.dump(final_results, f, indent=2, default=str)
    print(f"\n  Results saved to {output_path}")

    elapsed = time.time() - t_start
    print(f"\n  Total time: {elapsed:.1f}s")
    print("\n" + "=" * 70)
    print("K845 COMPLETE")
    print("=" * 70)
