#!/usr/bin/env python3
"""
K847: Decomposing 0050.TW Overnight Gap Using TAIFEX TX Tick Data
==================================================================

Core Insight (from K817/K502):
  0050.TW close-to-close return has 77-93% in overnight gap.
  Previously labeled "not tradable" -- but TX night session HAS tick data!

We decompose the overnight gap into 5 time slots:
  Gap A:  TX 13:45 close -> TX 15:00 night open    (NO trading, 1.25hr)
  Slot B: TX 15:00 -> TX 21:30                      (YES, pre-US session)
  Slot C: TX 21:30 -> TX 04:00 next day             (YES, US trading hours)
  Slot D: TX 04:00 -> TX 05:00                      (YES, pre-close)
  Gap E:  TX 05:00 -> 0050.TW 09:00 open            (NO trading, 4hr)

Key Questions:
  1. How much of the stock gap falls in each slot?
  2. What fraction is TRADABLE (Slot B+C+D) vs NOT TRADABLE (Gap A+E)?
  3. Does Slot C (US hours) dominate?
  4. Correlation between each slot and SPY contemporaneous return?

Error log rules:
  - 0050.TW: must use clean_tw50_data
  - TAIFEX: filter max-volume expiry, volume int(float()), Big5, >100 bytes
  - Time codes: 6-digit HHMMSS after 2017/05/16

Data: TAIFEX TX tick (2017-05-16+), yfinance (0050.TW, SPY)
References:
  - K843: Night session strategy analysis (Sharpe 0.788 BH night)
  - K817/K502: 77-93% of 0050.TW c2c return in overnight gap
  - K812: Close-to-close artifact (INVALID)

File structure per Daily_YYYY_MM_DDTX.csv (DD = day session date):
  - Date 1 (prev calendar day): night session evening 15:00-23:59
  - Date 2 (DD, or for 3-date files, middle date): night morning 00:00-04:59
  - Date 2/3 (DD): day session 08:45-13:45
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from scipy import stats
import yfinance as yf

warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from volpred.utils import clean_tw50_data

# ── Configuration ──
DATA_DIR = '/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python'
MIN_FILE_SIZE = 100
OUTPUT_FILE = os.path.join(os.path.dirname(__file__),
                           'k847_overnight_gap_decomposition_results.json')
NIGHT_SESSION_START = 20170516


def safe_volume(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def parse_tx_file(filepath):
    """
    Parse a TAIFEX TX daily CSV and extract key prices.

    Each file Daily_YYYY_MM_DDTX.csv (DD = day session date) contains:
      - Night session evening (prev calendar day, times >= 150000)
      - Night session morning (times < 50000, same day or middle date)
      - Day session (times 84500-134500)

    Returns dict with:
      - day_date: the day session calendar date (int YYYYMMDD)
      - day_close: last price in day session (13:45)
      - day_open: first price in day session (08:45)
      - night_open: first price in night session (15:00)
      - pre_us_close: last price before 21:30
      - at_4am: last price before 04:00 (or first after if missing)
      - night_close: last price in night session (<05:00)
      - tick counts per slot
    """
    try:
        if os.path.getsize(filepath) < MIN_FILE_SIZE:
            return None

        df = pd.read_csv(filepath, encoding='big5')
        if len(df) < 10:
            return None

        df.columns = ['date', 'product', 'expiry', 'time', 'price', 'volume',
                      'near_price', 'far_price', 'open_auction', 'timestamp']

        df = df[df['product'].str.strip() == 'TX'].copy()
        if len(df) < 10:
            return None

        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['volume'] = df['volume'].apply(safe_volume)
        df['time'] = pd.to_numeric(df['time'], errors='coerce').fillna(0).astype(int)
        df['date'] = pd.to_numeric(df['date'], errors='coerce').fillna(0).astype(int)
        df = df.dropna(subset=['price'])

        if len(df) < 10:
            return None

        dates = sorted(df['date'].unique())
        if len(dates) < 2:
            return None

        # Identify parts:
        # Evening night session: earliest date, times >= 150000
        # Morning night session: times < 50000 (could be dates[1] or dates[-1] if 2 dates)
        # Day session: latest date, times >= 84500
        night_evening_date = dates[0]
        day_session_date = dates[-1]

        night_evening = df[(df['date'] == night_evening_date) & (df['time'] >= 150000)]

        # Morning part: any date with times < 50000
        # For 2-date files: day_session_date has both morning (00:00-05:00) and day (08:45-13:45)
        # For 3-date files: middle date has morning, last date has day session
        night_morning = df[df['time'] < 50000]
        day_session = df[(df['date'] == day_session_date) &
                         (df['time'] >= 84500) & (df['time'] <= 134500)]

        night_all = pd.concat([night_evening, night_morning])
        if len(night_all) < 5 or len(day_session) < 5:
            return None

        # Max-volume expiry for night session
        vol_by_expiry = night_all.groupby('expiry')['volume'].sum()
        if len(vol_by_expiry) == 0:
            return None
        max_expiry = vol_by_expiry.idxmax()

        # Filter to max expiry
        night_evening_f = night_evening[night_evening['expiry'] == max_expiry]
        night_morning_f = night_morning[night_morning['expiry'] == max_expiry]
        day_session_f = day_session[day_session['expiry'] == max_expiry]

        if len(night_evening_f) < 3 or len(day_session_f) < 3:
            return None

        result = {
            'file': os.path.basename(filepath),
            'day_date': int(day_session_date),
        }

        # Day session open and close
        result['day_open'] = float(day_session_f.iloc[0]['price'])
        result['day_close'] = float(day_session_f.iloc[-1]['price'])

        # Night session open (first tick >= 150000)
        result['night_open'] = float(night_evening_f.iloc[0]['price'])

        # Pre-US close (last tick < 213000 in evening)
        pre_us = night_evening_f[night_evening_f['time'] < 213000]
        if len(pre_us) > 0:
            result['pre_us_close'] = float(pre_us.iloc[-1]['price'])
        else:
            result['pre_us_close'] = result['night_open']

        # US open (first tick >= 213000 in evening)
        us_ticks = night_evening_f[night_evening_f['time'] >= 213000]

        # At 04:00 boundary
        pre_4am = night_morning_f[night_morning_f['time'] < 40000]
        post_4am = night_morning_f[night_morning_f['time'] >= 40000]

        if len(pre_4am) > 0:
            result['at_4am'] = float(pre_4am.iloc[-1]['price'])
        elif len(us_ticks) > 0:
            # If no morning ticks before 4am, use last evening tick
            result['at_4am'] = float(us_ticks.iloc[-1]['price'])
        else:
            return None

        # Night session close (last tick < 050000)
        if len(night_morning_f) > 0:
            result['night_close'] = float(night_morning_f.iloc[-1]['price'])
        elif len(post_4am) > 0:
            result['night_close'] = float(post_4am.iloc[-1]['price'])
        else:
            return None

        # Tick counts
        result['n_ticks_evening'] = len(night_evening_f)
        result['n_ticks_pre_us'] = len(pre_us)
        result['n_ticks_us_evening'] = len(us_ticks)
        result['n_ticks_pre_4am'] = len(pre_4am)
        result['n_ticks_post_4am'] = len(post_4am)

        return result

    except Exception as e:
        return None


def main():
    t0 = time.time()
    print("=" * 70)
    print("K847: Decomposing 0050.TW Overnight Gap Using TAIFEX TX Tick Data")
    print("=" * 70)

    # ── Step 1: Load TAIFEX tick data ──
    print("\n[1/5] Loading TAIFEX TX tick data...")

    all_files = sorted([
        os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR)
        if f.startswith('Daily_') and f.endswith('TX.csv')
    ])

    # Filter to post night-session era
    filtered_files = []
    for f in all_files:
        parts = os.path.basename(f).split('_')
        try:
            y, m, d = int(parts[1]), int(parts[2]), int(parts[3][:2])
            fdate = y * 10000 + m * 100 + d
            if fdate >= NIGHT_SESSION_START:
                filtered_files.append(f)
        except (ValueError, IndexError):
            continue

    print(f"  Found {len(filtered_files)} files post-2017-05-16")

    # Parallel parsing
    parsed_days = []
    n_workers = min(8, os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(parse_tx_file, f): f for f in filtered_files}
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                parsed_days.append(result)

    parsed_days.sort(key=lambda x: x['day_date'])
    print(f"  Successfully parsed {len(parsed_days)} trading days")

    if len(parsed_days) < 100:
        print("ERROR: Too few valid days.")
        return

    # ── Step 2: Load stock data ──
    print("\n[2/5] Loading stock data (0050.TW, SPY)...")

    tw50 = yf.download('0050.TW', start='2017-01-01', end='2026-12-31',
                        progress=False, auto_adjust=True)
    if hasattr(tw50.columns, 'levels'):
        tw50.columns = [c[0] if isinstance(c, tuple) else c for c in tw50.columns]
    tw50.index = pd.to_datetime(tw50.index)
    # Clean split artifacts using the utility
    tw50['Close'], _ = clean_tw50_data(tw50['Close'])
    tw50['Open'], _ = clean_tw50_data(tw50['Open'])

    spy = yf.download('SPY', start='2017-01-01', end='2026-12-31',
                       progress=False, auto_adjust=True)
    if hasattr(spy.columns, 'levels'):
        spy.columns = [c[0] if isinstance(c, tuple) else c for c in spy.columns]
    spy.index = pd.to_datetime(spy.index)

    print(f"  0050.TW: {len(tw50)} days, SPY: {len(spy)} days")

    # ── Step 3: Build gap decomposition ──
    print("\n[3/5] Building gap decomposition dataset...")

    # Create lookup: day_date -> parsed data
    tx_by_date = {d['day_date']: d for d in parsed_days}
    tx_dates = sorted(tx_by_date.keys())

    records = []
    for i in range(1, len(tx_dates)):
        today_date = tx_dates[i]
        prev_date = tx_dates[i - 1]

        today = tx_by_date[today_date]
        prev = tx_by_date[prev_date]

        # We need:
        # Gap A = today's night_open - prev's day_close  (TX 13:45 -> TX 15:00)
        # Slot B = today's pre_us_close - today's night_open  (TX 15:00 -> 21:30)
        # Slot C = today's at_4am - today's pre_us_close  (TX 21:30 -> 04:00)
        # Slot D = today's night_close - today's at_4am  (TX 04:00 -> 05:00)
        # Gap E = today's day_open (TX 08:45) - today's night_close (TX 05:00)

        # NOTE: "today's night session" actually starts the evening BEFORE today's day session.
        # The file Daily_YYYY_MM_DDTX.csv has the night session that ends the morning of DD
        # and the day session of DD. So today's night_open is the previous evening,
        # and prev's day_close is prev's 13:45.

        # But wait: the night session in today's file opened the previous evening.
        # Gap A = that night open - the day close that preceded it.
        # The "prev" file's day_close is the day session close from a different date.
        # We need: the day session close from the SAME day that the night session opened.

        # For today's file:
        #   - night session evening = prev calendar day evening
        #   - night session morning = today early morning
        #   - day session = today 08:45-13:45

        # Gap A links: prev file's day_close (13:45) -> today file's night_open (15:00)
        # This is correct ONLY if prev file's day session date is one trading day before
        # today's night session evening date. Since files are consecutive trading days,
        # this should hold for normal consecutive days.

        prev_day_close = prev.get('day_close')
        night_open = today.get('night_open')
        pre_us = today.get('pre_us_close')
        at_4am = today.get('at_4am')
        night_close = today.get('night_close')
        day_open = today.get('day_open')

        if not all([prev_day_close, night_open, pre_us, at_4am, night_close, day_open]):
            continue
        if prev_day_close <= 0 or night_open <= 0:
            continue

        # Compute slot returns (log-return style for additivity)
        gap_a = (night_open - prev_day_close) / prev_day_close
        slot_b = (pre_us - night_open) / night_open
        slot_c = (at_4am - pre_us) / pre_us if pre_us > 0 else 0
        slot_d = (night_close - at_4am) / at_4am if at_4am > 0 else 0
        gap_e = (day_open - night_close) / night_close if night_close > 0 else 0

        # Match with 0050.TW
        try:
            dt = pd.Timestamp(str(today_date))
        except Exception:
            continue

        if dt not in tw50.index:
            continue

        tw_idx = tw50.index.get_loc(dt)
        if tw_idx < 1:
            continue

        tw_prev_dt = tw50.index[tw_idx - 1]
        tw_open = float(tw50.loc[dt, 'Open'])
        tw_close = float(tw50.loc[dt, 'Close'])
        tw_prev_close = float(tw50.loc[tw_prev_dt, 'Close'])

        if tw_prev_close <= 0 or tw_open <= 0:
            continue

        stock_gap = (tw_open - tw_prev_close) / tw_prev_close
        stock_c2c = (tw_close - tw_prev_close) / tw_prev_close
        stock_intraday = (tw_close - tw_open) / tw_open

        # TX full overnight: product of (1+slot) - 1
        tx_overnight = ((1 + gap_a) * (1 + slot_b) * (1 + slot_c) *
                        (1 + slot_d) * (1 + gap_e)) - 1

        # Match SPY (the night session covers the US trading day of the previous calendar date)
        # Need to find which US trading day the night session covers
        spy_ret = None
        # Try the previous calendar day and nearby
        for delta in [0, -1, 1, -2]:
            try_dt = dt + pd.Timedelta(days=delta)
            if try_dt in spy.index:
                spy_ret = float((spy.loc[try_dt, 'Close'] - spy.loc[try_dt, 'Open']) /
                               spy.loc[try_dt, 'Open'])
                break

        # Actually, the night session evening date is prev calendar day of today.
        # US markets trade during TW evening/early morning.
        # If today is Wed (TW), night session was Tue evening -> Wed morning,
        # which covers US Tuesday trading session (Tue 9:30-16:00 ET = Tue 21:30-Wed 05:00 TW)
        # So SPY date = prev TW trading day? No, SPY date = the date of Tue in US calendar.
        # Let's try: dt - 1 day for regular days
        spy_ret = None
        for delta in [-1, 0, -2]:
            try_dt = dt + pd.Timedelta(days=delta)
            if try_dt in spy.index:
                spy_close = float(spy.loc[try_dt, 'Close'])
                spy_open = float(spy.loc[try_dt, 'Open'])
                if spy_open > 0:
                    spy_ret = (spy_close - spy_open) / spy_open
                    break

        rec = {
            'day_date': int(today_date),
            'stock_gap': stock_gap,
            'stock_c2c': stock_c2c,
            'stock_intraday': stock_intraday,
            'gap_a': gap_a,
            'slot_b': slot_b,
            'slot_c': slot_c,
            'slot_d': slot_d,
            'gap_e': gap_e,
            'tx_overnight': tx_overnight,
            'spy_ret': spy_ret,
        }
        records.append(rec)

    df = pd.DataFrame(records)
    df['day_date_dt'] = pd.to_datetime(df['day_date'].astype(str))
    print(f"  Merged dataset: {len(df)} trading days")

    if len(df) < 50:
        print("ERROR: Too few merged days.")
        return

    # ── Step 4: Statistical Analysis ──
    print("\n[4/5] Statistical Analysis...")

    # 4a: Descriptive statistics
    print("\n  --- Descriptive Statistics (daily returns, bps) ---")
    slot_cols = ['gap_a', 'slot_b', 'slot_c', 'slot_d', 'gap_e', 'stock_gap', 'stock_c2c']
    desc_stats = {}
    for col in slot_cols:
        s = df[col].dropna()
        if len(s) < 10:
            continue
        desc_stats[col] = {
            'n': len(s),
            'mean_bps': round(float(s.mean() * 10000), 2),
            'std_bps': round(float(s.std() * 10000), 2),
            'median_bps': round(float(s.median() * 10000), 2),
            'skew': round(float(s.skew()), 3),
            'kurtosis': round(float(s.kurtosis()), 3),
            'min_bps': round(float(s.min() * 10000), 2),
            'max_bps': round(float(s.max() * 10000), 2),
            'ann_return_pct': round(float(s.mean() * 252 * 100), 2),
            'ann_vol_pct': round(float(s.std() * np.sqrt(252) * 100), 2),
            'sharpe': round(float(s.mean() / s.std() * np.sqrt(252)), 3) if s.std() > 0 else 0,
        }
        d = desc_stats[col]
        print(f"  {col:15s}: mean={d['mean_bps']:+7.2f}bps, "
              f"std={d['std_bps']:7.2f}bps, "
              f"ann_ret={d['ann_return_pct']:+7.2f}%, "
              f"Sharpe={d['sharpe']:+.3f}, n={d['n']}")

    # 4b: Variance decomposition
    print("\n  --- Variance Decomposition (Cov with stock_gap / Var of stock_gap) ---")
    valid = df.dropna(subset=['gap_a', 'slot_b', 'slot_c', 'slot_d', 'gap_e', 'stock_gap'])
    print(f"  Valid days with all 5 slots + stock gap: {len(valid)}")

    variance_decomp = {}
    if len(valid) > 50:
        var_gap = valid['stock_gap'].var()
        for col in ['gap_a', 'slot_b', 'slot_c', 'slot_d', 'gap_e']:
            cov = valid[col].cov(valid['stock_gap'])
            pct = float(cov / var_gap * 100) if var_gap > 0 else 0
            variance_decomp[col] = {
                'cov_with_gap': float(cov),
                'pct_of_variance': round(pct, 1),
            }
            print(f"  {col:10s}: {pct:+6.1f}% of stock gap variance")

        # Tradable vs non-tradable
        tradable = valid['slot_b'] + valid['slot_c'] + valid['slot_d']
        non_tradable = valid['gap_a'] + valid['gap_e']
        residual = valid['stock_gap'] - (valid['gap_a'] + valid['slot_b'] +
                                          valid['slot_c'] + valid['slot_d'] + valid['gap_e'])

        trad_var_pct = float(tradable.cov(valid['stock_gap']) / var_gap * 100)
        nontrad_var_pct = float(non_tradable.cov(valid['stock_gap']) / var_gap * 100)
        resid_var_pct = float(residual.cov(valid['stock_gap']) / var_gap * 100)

        print(f"\n  TRADABLE (B+C+D): {trad_var_pct:+.1f}% of stock gap variance")
        print(f"  NON-TRADABLE (A+E): {nontrad_var_pct:+.1f}% of stock gap variance")
        print(f"  RESIDUAL: {resid_var_pct:+.1f}%")

    # 4c: Mean decomposition
    print("\n  --- Mean Decomposition ---")
    mean_decomp = {}
    if len(valid) > 50:
        gap_mean = valid['stock_gap'].mean()
        print(f"  Stock gap mean: {gap_mean*10000:+.2f} bps/day")

        for col in ['gap_a', 'slot_b', 'slot_c', 'slot_d', 'gap_e']:
            m = valid[col].mean()
            pct = float(m / gap_mean * 100) if abs(gap_mean) > 1e-10 else 0
            mean_decomp[col] = {
                'mean_bps': round(float(m * 10000), 2),
                'pct_of_mean_gap': round(pct, 1),
            }
            print(f"  {col:10s}: {m*10000:+7.2f} bps ({pct:+7.1f}% of mean gap)")

        residual_mean = gap_mean - sum(valid[c].mean() for c in ['gap_a', 'slot_b', 'slot_c', 'slot_d', 'gap_e'])
        print(f"  Residual: {residual_mean*10000:+7.2f} bps")

        # Tradable mean
        trad_mean = sum(valid[c].mean() for c in ['slot_b', 'slot_c', 'slot_d'])
        nontrad_mean = sum(valid[c].mean() for c in ['gap_a', 'gap_e'])
        trad_mean_pct = float(trad_mean / gap_mean * 100) if abs(gap_mean) > 1e-10 else 0
        nontrad_mean_pct = float(nontrad_mean / gap_mean * 100) if abs(gap_mean) > 1e-10 else 0
        print(f"\n  TRADABLE mean: {trad_mean*10000:+.2f} bps ({trad_mean_pct:+.1f}% of gap)")
        print(f"  NON-TRADABLE mean: {nontrad_mean*10000:+.2f} bps ({nontrad_mean_pct:+.1f}% of gap)")

    # 4d: OLS Regression
    print("\n  --- OLS: stock_gap ~ gap_a + slot_b + slot_c + slot_d + gap_e ---")
    regression_results = {}
    if len(valid) > 50:
        X = valid[['gap_a', 'slot_b', 'slot_c', 'slot_d', 'gap_e']].values
        X_c = np.column_stack([np.ones(len(X)), X])
        y = valid['stock_gap'].values

        beta, _, _, _ = np.linalg.lstsq(X_c, y, rcond=None)
        y_hat = X_c @ beta
        ss_res = np.sum((y - y_hat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r_sq = 1 - ss_res / ss_tot

        n_obs = len(y)
        k = X_c.shape[1]
        mse = ss_res / (n_obs - k)
        var_beta = mse * np.linalg.inv(X_c.T @ X_c).diagonal()
        se_beta = np.sqrt(np.abs(var_beta))
        t_stats = beta / se_beta

        reg_names = ['const', 'gap_a', 'slot_b', 'slot_c', 'slot_d', 'gap_e']
        for i, name in enumerate(reg_names):
            pval = float(2 * (1 - stats.t.cdf(abs(t_stats[i]), n_obs - k)))
            regression_results[name] = {
                'beta': round(float(beta[i]), 6),
                'se': round(float(se_beta[i]), 6),
                't_stat': round(float(t_stats[i]), 2),
                'p_value': round(pval, 6),
            }
            sig = '***' if abs(t_stats[i]) > 3.0 else ('**' if abs(t_stats[i]) > 2.0 else '')
            print(f"  {name:10s}: beta={beta[i]:+.4f}, t={t_stats[i]:+7.2f} {sig}")

        print(f"  R-squared: {r_sq:.4f}, N: {n_obs}")
        regression_results['r_squared'] = round(float(r_sq), 4)
        regression_results['n_obs'] = n_obs

    # 4e: Tradable vs Non-Tradable summary
    print("\n  --- Tradable vs Non-Tradable Summary ---")
    tradable_summary = {}
    if len(valid) > 50:
        tradable = valid['slot_b'] + valid['slot_c'] + valid['slot_d']
        non_tradable = valid['gap_a'] + valid['gap_e']

        for label, series in [('tradable_BCD', tradable), ('non_tradable_AE', non_tradable)]:
            ann_ret = float(series.mean() * 252 * 100)
            ann_vol = float(series.std() * np.sqrt(252) * 100)
            sharpe = float(series.mean() / series.std() * np.sqrt(252)) if series.std() > 0 else 0
            var_pct = float(series.cov(valid['stock_gap']) / var_gap * 100)
            mean_pct = float(series.mean() / gap_mean * 100) if abs(gap_mean) > 1e-10 else 0

            tradable_summary[label] = {
                'ann_return_pct': round(ann_ret, 2),
                'ann_vol_pct': round(ann_vol, 2),
                'sharpe': round(sharpe, 3),
                'variance_pct': round(var_pct, 1),
                'mean_pct': round(mean_pct, 1),
            }
            print(f"  {label}:")
            print(f"    Ann return: {ann_ret:+.2f}%, Vol: {ann_vol:.2f}%, Sharpe: {sharpe:.3f}")
            print(f"    Variance contribution: {var_pct:+.1f}%, Mean contribution: {mean_pct:+.1f}%")

    # 4f: Correlations with SPY
    print("\n  --- Correlations with SPY ---")
    spy_valid = df.dropna(subset=['spy_ret'])
    corr_with_spy = {}
    for col in ['gap_a', 'slot_b', 'slot_c', 'slot_d', 'gap_e', 'stock_gap']:
        sub = spy_valid.dropna(subset=[col])
        if len(sub) > 50:
            r, p = stats.pearsonr(sub[col], sub['spy_ret'])
            rho, rho_p = stats.spearmanr(sub[col], sub['spy_ret'])
            corr_with_spy[col] = {
                'pearson_r': round(float(r), 4),
                'pearson_p': float(p),
                'spearman_rho': round(float(rho), 4),
                'n': len(sub),
            }
            sig = '***' if p < 0.001 else ('**' if p < 0.01 else ('*' if p < 0.05 else ''))
            print(f"  {col:15s}: r={r:+.4f} {sig}, rho={rho:+.4f}, n={len(sub)}")

    # 4g: Cross-correlations between slots
    print("\n  --- Cross-Correlations Between Slots ---")
    slot_cross = {}
    for c1 in ['gap_a', 'slot_b', 'slot_c', 'slot_d', 'gap_e']:
        for c2 in ['gap_a', 'slot_b', 'slot_c', 'slot_d', 'gap_e']:
            if c1 >= c2:
                continue
            sub = df.dropna(subset=[c1, c2])
            if len(sub) > 50:
                r, p = stats.pearsonr(sub[c1], sub[c2])
                key = f"{c1}_vs_{c2}"
                slot_cross[key] = {'r': round(float(r), 4), 'p': float(p)}
                sig = '***' if p < 0.001 else ''
                print(f"  {key:30s}: r={r:+.4f} {sig}")

    # 4h: Yearly breakdown
    print("\n  --- Yearly Breakdown ---")
    df['year'] = df['day_date_dt'].dt.year
    yearly = {}
    for year in sorted(df['year'].unique()):
        ydf = df[df['year'] == year].dropna(subset=['gap_a', 'slot_b', 'slot_c', 'slot_d', 'gap_e', 'stock_gap'])
        if len(ydf) < 20:
            continue

        gm = ydf['stock_gap'].mean()
        tm = (ydf['slot_b'] + ydf['slot_c'] + ydf['slot_d']).mean()
        nm = (ydf['gap_a'] + ydf['gap_e']).mean()
        cm = ydf['slot_c'].mean()

        yearly[int(year)] = {
            'n_days': len(ydf),
            'stock_gap_bps': round(float(gm * 10000), 2),
            'tradable_bps': round(float(tm * 10000), 2),
            'tradable_pct': round(float(tm / gm * 100), 1) if abs(gm) > 1e-10 else 0,
            'slot_c_bps': round(float(cm * 10000), 2),
            'slot_c_pct': round(float(cm / gm * 100), 1) if abs(gm) > 1e-10 else 0,
        }
        y = yearly[int(year)]
        print(f"  {year}: gap={y['stock_gap_bps']:+7.2f}bps, "
              f"tradable={y['tradable_pct']:+7.1f}%, "
              f"slot_c={y['slot_c_pct']:+7.1f}%, "
              f"n={y['n_days']}")

    # 4i: How much of the "overnight gap alpha" does night session capture?
    print("\n  --- Night Session Capture Rate ---")
    if len(valid) > 50:
        # K843 showed BH Night Session = Sharpe 0.788
        # Night session = Slot B + C + D (tradable part)
        # Stock gap = full overnight including non-tradable parts
        # Capture rate = tradable / stock_gap variance explained

        # Also: correlation between tradable part and stock gap
        r_trad, p_trad = stats.pearsonr(tradable, valid['stock_gap'])
        r_full, p_full = stats.pearsonr(
            valid['gap_a'] + valid['slot_b'] + valid['slot_c'] + valid['slot_d'] + valid['gap_e'],
            valid['stock_gap']
        )

        print(f"  Corr(tradable B+C+D, stock_gap): {r_trad:+.4f}")
        print(f"  Corr(all TX slots, stock_gap): {r_full:+.4f}")

        capture_stats = {
            'corr_tradable_vs_stock_gap': round(float(r_trad), 4),
            'corr_all_tx_vs_stock_gap': round(float(r_full), 4),
            'tradable_variance_pct': tradable_summary.get('tradable_BCD', {}).get('variance_pct', 0),
            'night_session_sharpe_k843': 0.788,  # From K843 reference
        }
    else:
        capture_stats = {}

    # ── Step 5: Save ──
    print("\n[5/5] Saving results...")
    runtime = time.time() - t0

    results = {
        'experiment_id': 'K847',
        'title': 'Decomposing 0050.TW Overnight Gap Using TAIFEX TX Tick Data',
        'date': datetime.now().isoformat(),
        'data_source': 'TAIFEX TX tick data + yfinance (0050.TW, SPY)',
        'data_period': f"{parsed_days[0]['day_date']} - {parsed_days[-1]['day_date']}",
        'n_parsed_days': len(parsed_days),
        'n_merged_days': len(df),
        'n_valid_all_slots': len(valid),
        'runtime_seconds': round(runtime, 1),
        'prior_work': {
            'K843': 'Night session BH Sharpe 0.788',
            'K817_K502': '77-93% of 0050.TW c2c return in overnight gap',
            'K812': 'INVALID: c2c artifact Sharpe 3.4',
        },
        'slot_definitions': {
            'gap_a': 'TX 13:45 -> TX 15:00 (NOT tradable, 1.25hr gap)',
            'slot_b': 'TX 15:00 -> TX 21:30 (TRADABLE, pre-US)',
            'slot_c': 'TX 21:30 -> TX 04:00 (TRADABLE, US hours)',
            'slot_d': 'TX 04:00 -> TX 05:00 (TRADABLE, pre-close)',
            'gap_e': 'TX 05:00 -> stock 09:00 (NOT tradable, 4hr)',
        },
        'descriptive_statistics': desc_stats,
        'variance_decomposition': variance_decomp,
        'mean_decomposition': mean_decomp,
        'regression': regression_results,
        'tradable_vs_nontradable': tradable_summary,
        'correlations_with_spy': corr_with_spy,
        'slot_cross_correlations': slot_cross,
        'yearly_analysis': yearly,
        'night_session_capture': capture_stats,
        'limitations': [
            'TX futures != 0050.TW spot (basis risk)',
            'Gap E includes futures-to-stock basis adjustment',
            'Night session liquidity varies across slots',
            'TX contract rollover effects not fully modeled',
            'Data starts 2017-05-16 (night session introduction)',
            'SPY date matching approximate (TW/US calendar mismatch)',
        ],
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n  Saved to {OUTPUT_FILE}")
    print(f"  Runtime: {runtime:.1f}s")

    # ── Summary ──
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if tradable_summary:
        ts = tradable_summary.get('tradable_BCD', {})
        ns = tradable_summary.get('non_tradable_AE', {})
        print(f"\n  TRADABLE (Slot B+C+D):")
        print(f"    {ts.get('variance_pct', 0):+.1f}% of gap variance")
        print(f"    {ts.get('mean_pct', 0):+.1f}% of mean gap")
        print(f"    Sharpe: {ts.get('sharpe', 0):.3f}")
        print(f"\n  NON-TRADABLE (Gap A + Gap E):")
        print(f"    {ns.get('variance_pct', 0):+.1f}% of gap variance")
        print(f"    {ns.get('mean_pct', 0):+.1f}% of mean gap")

    if variance_decomp:
        print(f"\n  Slot C (US hours):")
        print(f"    {variance_decomp.get('slot_c', {}).get('pct_of_variance', 0):+.1f}% of gap variance")

    if corr_with_spy and 'slot_c' in corr_with_spy:
        print(f"\n  SPY correlations:")
        print(f"    Slot C vs SPY: r={corr_with_spy['slot_c']['pearson_r']:+.4f}")
        if 'stock_gap' in corr_with_spy:
            print(f"    Stock gap vs SPY: r={corr_with_spy['stock_gap']['pearson_r']:+.4f}")

    print(f"\n  Runtime: {runtime:.1f}s")


if __name__ == '__main__':
    main()
