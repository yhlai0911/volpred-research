#!/usr/bin/env python3
"""
K883: TAIFEX Tick-Level PRG — True Session-Frequency with Volume-Based Rollover
=================================================================================

Research Question (EMPIRICAL):
  Does a Periodic Realized GARCH (PRG) using TRUE tick-level data from TAIFEX TX
  (volume-based rollover, NOT TX1) dominate GJR-GARCH and HAR-RV for forecasting
  full-day variance?

KEY DIFFERENCES from K874c:
  1. TX volume-based rollover (NOT TX1): group by 到期月份, select highest volume
  2. 2-session PRG matching PRS TAIFEX design:
     - Session A = overnight: r = log(open_regular_t / close_regular_{t-1})
       x_A = RV_night (5-min tick) + r²_gap1 + r²_gap2
     - Session B = regular trading: r = log(close_regular / open_regular)
       x_B = RV_intra (5-min tick from day session)
  3. True session returns from tick data, not OHLC approximation
  4. Common target σ²_fullday = x_A + x_B (tick-based)

Model: h_n = ω_{s_n} + α_{s_n}·x_{n-1} + β_{s_n}·h_{n-1}
  Extended: + γ_{s_n}·x_{n-1}·I(r_{n-1}<0)

Benchmarks:
  a. GJR-GARCH(1,1) on close-to-close returns
  b. HAR-RV on log(RV_total)
  c. Separate GARCH per session (no cross-recursion)
  d. PRG Basic (6 params) and PRG Extended (8 params)

Evaluation (common target σ²_fullday):
  Layer 1: QLIKE, MSE, MAE, HMSE, Spearman
  Layer 2: DM test pairwise (Harvey |t|>3.0)
  Layer 3: VaR 1%+5% (Kupiec + Christoffersen + Basel)
  Layer 4: ES (Acerbi-Szekely + Fissler-Ziegel)

OOS: IS 60%, OOS 40%, rolling refit every 63 days

Error log rules:
  - DM test: use dm_test from volpred.stats.model_evaluation (Newey-West HAC)
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])
  - TX: volume-based contract selection, NOT TX1
  - Periodic Model: use prior session realized info to predict next (NOT lookahead)
  - VaR+ES: Kupiec+CC at 1%+5%, Acerbi-Szekely for ES

Data: TAIFEX TX tick ~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_{YYYY}_{MM}_{DD}TX.csv
  Big5 encoding, 2017-05-15 to 2025-12-31 (night session era)

References:
  - Lai et al. (2024): Periodic GARCH with regime switching (PRS)
  - Bollerslev & Ghysels (1996): Periodic GARCH
  - Corsi (2009): HAR-RV model
  - Hansen & Lunde (2005): Realized GARCH, optimal RV weighting
  - Patton (2011): QLIKE proxy-robust loss
  - Kupiec (1995): VaR back-testing
  - Christoffersen (1998): Conditional coverage VaR test
  - Acerbi & Szekely (2014): ES back-testing
  - Fissler & Ziegel (2016): Joint elicitability of VaR and ES

Author: VolPred Research System
Date: 2026-04-05
"""

import os
import sys
import glob
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from scipy import stats as sp_stats
from scipy.optimize import minimize
from numba import njit

warnings.filterwarnings('ignore')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
from volpred.stats.model_evaluation import dm_test

# ============================================================
# Configuration
# ============================================================
DATA_DIR = os.path.expanduser("~/Dropbox/TAIFEXDATA/TAIFEXDATA/python")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k883_results.json")
CHARTS_DIR = os.path.join(SCRIPT_DIR, "k883_charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# Session boundaries (HHMMSS integer)
NIGHT_PM_START = 150000
NIGHT_PM_END   = 235959
NIGHT_AM_START = 0
NIGHT_AM_END   = 50000
DAY_START      = 84500
DAY_END        = 134500

# OOS config
IS_FRACTION = 0.60
REFIT_FREQ  = 126  # sessions (~63 trading days)

NIGHT_SESSION_START_DATE = "2017-05-15"

# ============================================================
# Numba-accelerated kernels
# ============================================================

@njit(cache=True)
def _prg_negll(params, r, x, s, n, extended):
    """PRG negative log-likelihood (numba)."""
    if extended:
        omega0, alpha0, beta0, omega1, alpha1, beta1, gamma0, gamma1 = params[0], params[1], params[2], params[3], params[4], params[5], params[6], params[7]
    else:
        omega0, alpha0, beta0, omega1, alpha1, beta1 = params[0], params[1], params[2], params[3], params[4], params[5]
        gamma0, gamma1 = 0.0, 0.0

    # Init h from sample variance of first 50 returns
    h0 = 0.0
    cnt = min(50, n)
    for i in range(cnt):
        h0 += r[i] ** 2
    h0 /= cnt
    if h0 < 1e-12:
        h0 = 1e-8

    h_prev = h0
    ll = 0.0

    for t in range(1, n):
        st = int(s[t])
        x_prev = x[t - 1]
        r_prev = r[t - 1]

        if st == 0:
            lev = gamma0 * x_prev * (1.0 if r_prev < 0 else 0.0)
            h_t = omega0 + alpha0 * x_prev + lev + beta0 * h_prev
        else:
            lev = gamma1 * x_prev * (1.0 if r_prev < 0 else 0.0)
            h_t = omega1 + alpha1 * x_prev + lev + beta1 * h_prev

        if h_t <= 0:
            return 1e15

        ll += -0.5 * np.log(2 * np.pi) - 0.5 * np.log(h_t) - 0.5 * r[t] ** 2 / h_t
        h_prev = h_t

    return -ll


@njit(cache=True)
def _prg_recursive(params, r, x, s, n, extended):
    """Compute full h series for PRG."""
    if extended:
        omega0, alpha0, beta0, omega1, alpha1, beta1, gamma0, gamma1 = params[0], params[1], params[2], params[3], params[4], params[5], params[6], params[7]
    else:
        omega0, alpha0, beta0, omega1, alpha1, beta1 = params[0], params[1], params[2], params[3], params[4], params[5]
        gamma0, gamma1 = 0.0, 0.0

    h = np.empty(n)
    cnt = min(50, n)
    h0 = 0.0
    for i in range(cnt):
        h0 += r[i] ** 2
    h0 /= cnt
    if h0 < 1e-12:
        h0 = 1e-8
    h[0] = h0

    for t in range(1, n):
        st = int(s[t])
        x_prev = x[t - 1]
        r_prev = r[t - 1]

        if st == 0:
            lev = gamma0 * x_prev * (1.0 if r_prev < 0 else 0.0)
            h[t] = omega0 + alpha0 * x_prev + lev + beta0 * h[t - 1]
        else:
            lev = gamma1 * x_prev * (1.0 if r_prev < 0 else 0.0)
            h[t] = omega1 + alpha1 * x_prev + lev + beta1 * h[t - 1]

        if h[t] < 1e-12:
            h[t] = 1e-12

    return h


@njit(cache=True)
def _gjr_negll(omega, alpha, gamma_p, beta, r, n):
    """GJR-GARCH negative log-likelihood (numba)."""
    h0 = 0.0
    cnt = min(50, n)
    for i in range(cnt):
        h0 += r[i] ** 2
    h0 /= cnt
    if h0 < 1e-12:
        h0 = 1e-8

    h_prev = h0
    ll = 0.0
    for t in range(1, n):
        indicator = 1.0 if r[t - 1] < 0 else 0.0
        h_t = omega + alpha * r[t - 1] ** 2 + gamma_p * r[t - 1] ** 2 * indicator + beta * h_prev
        if h_t <= 0:
            return 1e15
        ll += -0.5 * np.log(2 * np.pi) - 0.5 * np.log(h_t) - 0.5 * r[t] ** 2 / h_t
        h_prev = h_t
    return -ll


@njit(cache=True)
def _gjr_propagate(omega, alpha, gamma_p, beta, r, h0, start, end):
    """Propagate GJR state from start to end, return final h."""
    h = h0
    for t in range(start, end):
        indicator = 1.0 if r[t - 1] < 0 else 0.0
        h = omega + alpha * r[t - 1] ** 2 + gamma_p * r[t - 1] ** 2 * indicator + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _sep_garch_negll(omega, alpha, beta, r_sess, x_sess, n_sess):
    """Separate GARCH per session negative log-likelihood."""
    h0 = 0.0
    cnt = min(30, n_sess)
    for i in range(cnt):
        h0 += r_sess[i] ** 2
    h0 /= cnt
    if h0 < 1e-12:
        h0 = 1e-8

    h_prev = h0
    ll = 0.0
    for t in range(1, n_sess):
        h_t = omega + alpha * x_sess[t - 1] + beta * h_prev
        if h_t <= 0:
            return 1e15
        ll += -0.5 * np.log(2 * np.pi) - 0.5 * np.log(h_t) - 0.5 * r_sess[t] ** 2 / h_t
        h_prev = h_t
    return -ll


# ============================================================
# Tick data processing
# ============================================================

def time_to_5min_bucket(time_int):
    """Convert HHMMSS int to 5-min bucket label."""
    h = time_int // 10000
    m = (time_int % 10000) // 100
    m5 = (m // 5) * 5
    return h * 100 + m5


def safe_volume(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def process_single_file(filepath):
    """Process one TX daily file -> session-level RV and prices."""
    basename = os.path.basename(filepath)
    try:
        parts = basename.replace("Daily_", "").replace("TX.csv", "").split("_")
        date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
    except Exception:
        return None

    if os.path.getsize(filepath) < 100:
        return None

    try:
        df = pd.read_csv(filepath, encoding='big5', dtype=str, low_memory=False)
    except Exception:
        try:
            df = pd.read_csv(filepath, encoding='cp950', dtype=str, low_memory=False)
        except Exception:
            return None

    if len(df) < 10:
        return None

    try:
        df['time_int'] = pd.to_numeric(df.iloc[:, 3], errors='coerce').astype('Int64')
        df['price'] = pd.to_numeric(df.iloc[:, 4], errors='coerce')
        df['volume'] = df.iloc[:, 5].apply(safe_volume)
        df = df.dropna(subset=['price', 'time_int'])
        df['time_int'] = df['time_int'].astype(int)
    except Exception:
        return None

    if len(df) < 10:
        return None

    # --- Volume-based contract selection (TX, NOT TX1) ---
    df['delivery'] = df.iloc[:, 2].astype(str).str.strip()
    vol_by_delivery = df.groupby('delivery')['volume'].sum()
    if len(vol_by_delivery) > 0:
        best_contract = vol_by_delivery.idxmax()
        df = df[df['delivery'] == best_contract]

    t = df['time_int'].values
    p = df['price'].values

    night_pm_mask = (t >= NIGHT_PM_START) & (t <= NIGHT_PM_END)
    night_am_mask = (t >= NIGHT_AM_START) & (t <= NIGHT_AM_END)
    day_mask = (t >= DAY_START) & (t <= DAY_END)

    def build_5min_returns(session_t, session_p):
        """Build 5-min log returns from tick prices."""
        if len(session_t) < 5:
            return np.array([])
        buckets = np.array([time_to_5min_bucket(ti) for ti in session_t])
        unique_buckets = np.unique(buckets)
        bar_closes = []
        for b in unique_buckets:
            bucket_mask = buckets == b
            bar_closes.append(session_p[bucket_mask][-1])
        bar_closes = np.array(bar_closes, dtype=float)
        if len(bar_closes) >= 2:
            return np.diff(np.log(bar_closes))
        return np.array([])

    def compute_rv(rets):
        if len(rets) < 1:
            return np.nan
        return float(np.sum(rets ** 2))

    # Compute 5-min RV for each sub-session
    day_rets = build_5min_returns(t[day_mask], p[day_mask])
    night_pm_rets = build_5min_returns(t[night_pm_mask], p[night_pm_mask])
    night_am_rets = build_5min_returns(t[night_am_mask], p[night_am_mask])

    # Concatenate night sub-sessions for night RV
    night_rets = np.concatenate([night_pm_rets, night_am_rets]) \
        if (len(night_pm_rets) > 0 or len(night_am_rets) > 0) else np.array([])

    rv_day = compute_rv(day_rets)
    rv_night = compute_rv(night_rets)

    # Key prices
    day_p = p[day_mask]
    night_pm_p = p[night_pm_mask]
    night_am_p = p[night_am_mask]

    day_open = float(day_p[0]) if len(day_p) > 0 else np.nan
    day_close = float(day_p[-1]) if len(day_p) > 0 else np.nan

    if len(night_am_p) > 0:
        night_close = float(night_am_p[-1])
    elif len(night_pm_p) > 0:
        night_close = float(night_pm_p[-1])
    else:
        night_close = np.nan

    night_open = float(night_pm_p[0]) if len(night_pm_p) > 0 else np.nan

    # Returns
    day_return = np.log(day_close / day_open) if (
        day_open > 0 and not np.isnan(day_open) and not np.isnan(day_close)
    ) else np.nan

    night_return = np.log(night_close / night_open) if (
        night_open > 0 and not np.isnan(night_open) and not np.isnan(night_close)
    ) else np.nan

    # Count 5-min bars for diagnostics
    n_day_bars = len(day_rets)
    n_night_bars = len(night_rets)

    return {
        'date': date_str,
        'rv_day': rv_day if not np.isnan(rv_day) else None,
        'rv_night': rv_night if not np.isnan(rv_night) else None,
        'day_open': day_open if not np.isnan(day_open) else None,
        'day_close': day_close if not np.isnan(day_close) else None,
        'night_open': night_open if not np.isnan(night_open) else None,
        'night_close': night_close if not np.isnan(night_close) else None,
        'day_return': day_return if not np.isnan(day_return) else None,
        'night_return': night_return if not np.isnan(night_return) else None,
        'n_day_bars': n_day_bars,
        'n_night_bars': n_night_bars,
        'contract': best_contract if 'best_contract' in dir() else None,
    }


def load_all_rv_data():
    """Load TX files (night session era) and compute 5-min RV."""
    pattern = os.path.join(DATA_DIR, "Daily_*TX.csv")
    all_files = sorted(glob.glob(pattern))

    cutoff_start = "Daily_2017_05_15"
    cutoff_end = "Daily_2026"
    files = [f for f in all_files
             if os.path.basename(f) >= cutoff_start
             and os.path.basename(f) < cutoff_end
             and 'TX1' not in os.path.basename(f)
             and 'TX2' not in os.path.basename(f)]

    print(f"  Found {len(files)} TX files (2017-05-15 to 2025-12-31)")

    results = []
    errors = 0
    n_workers = min(8, os.cpu_count() or 4)
    print(f"  Using {n_workers} parallel workers...")

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(process_single_file, f): f for f in files}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            if done_count % 500 == 0:
                print(f"    Processed {done_count}/{len(files)} files...")
            try:
                result = future.result()
                if result is not None and result.get('rv_day') is not None:
                    results.append(result)
                else:
                    errors += 1
            except Exception:
                errors += 1

    print(f"  Loaded: {len(results)} days, Errors: {errors}")

    df = pd.DataFrame(results)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    for col in ['rv_day', 'rv_night', 'day_open', 'day_close',
                'night_open', 'night_close', 'day_return', 'night_return']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


# ============================================================
# Build session-level series (2-session: overnight + intraday)
# ============================================================

def build_session_series(rv_df):
    """
    Build alternating session series.

    For each trading day t:
      Session 2*t (type=0, OVERNIGHT):
        r = log(day_open_t / day_close_{t-1})  [overnight gap: close→open]
        x = rv_night_{t-1 to t} + r²_gap
          where rv_night is the 5-min RV of the night session that ends before day open
          For simplicity: x = r²_overnight (gap squared) + rv_night if available
          Actually: the "overnight" period is from yesterday's close to today's open.
          The night session (15:00 to 05:00) runs DURING this gap.
          x_A = rv_night (5-min RV from night session) + r²_gap1 + r²_gap2

      Session 2*t+1 (type=1, INTRADAY):
        r = log(day_close_t / day_open_t) [intraday return]
        x = rv_day (5-min RV from regular session)

    Common target: σ²_fullday = x_A + x_B for each day

    CRITICAL: This is NOT lookahead because:
      - Session 0 (overnight) forecast uses x from PREVIOUS session 1 (yesterday intraday)
      - Session 1 (intraday) forecast uses x from CURRENT session 0 (today overnight)
        BUT the overnight period ENDED before the day session started (05:00 < 08:45)
    """
    df = rv_df.copy()
    df = df.dropna(subset=['day_open', 'day_close', 'rv_day'])

    # Compute overnight gap: log(open_today / close_yesterday)
    df['prev_day_close'] = df['day_close'].shift(1)
    df['overnight_gap'] = np.log(df['day_open'] / df['prev_day_close'])
    df['r2_overnight_gap'] = df['overnight_gap'] ** 2

    # Compute gap returns between sessions:
    # gap1 = close_regular_{t-1} -> open_night_{t-1}  (13:45 -> 15:00 same day)
    # gap2 = close_night_{t-1 to t} -> open_regular_t  (05:00 -> 08:45 same day)
    # These are non-trading gaps (no ticks), so use r² as realized measure

    df['prev_night_close'] = df['night_close'].shift(1)
    # gap1: from day_close to night_open (same day, night opens at 15:00 after day closes at 13:45)
    # Actually: night session on the file for date D starts after day session of day D-1
    # The TX file for "date D" contains night session that starts evening of D-1 and day session of D

    # For the TAIFEX file dated 2024-01-02TX.csv:
    #   - Night session data: from 2023-12-29 15:00 to ... (starts previous trading day)
    #   - Day session data: 2024-01-02 08:45 to 13:45
    #
    # So for day t:
    #   night_open (from file date t) = price at ~15:00 on trading day t-1
    #   night_close (from file date t) = price at ~05:00 on morning of day t
    #   day_open (from file date t) = price at 08:45 on day t
    #   day_close (from file date t) = price at 13:45 on day t
    #
    # Overnight period = day_close_{t-1} to day_open_t
    # This includes: gap1 (13:45 -> 15:00) + night session (15:00 -> 05:00) + gap2 (05:00 -> 08:45)
    #
    # x_overnight = r²_gap1 + rv_night + r²_gap2
    # But gap1 = log(night_open_t / day_close_{t-1})
    # gap2 = log(day_open_t / night_close_t)  if night_close available
    #
    # Note: night_open in file t corresponds to the SAME calendar day as day_close_{t-1}

    # gap1: day_close_{t-1} to night_open_t (from same file)
    # Since file date t's night_open corresponds to the previous trading day's 15:00
    df['gap1'] = np.log(df['night_open'] / df['prev_day_close'])
    df['r2_gap1'] = df['gap1'] ** 2

    # gap2: night_close_t to day_open_t (both from file date t)
    df['gap2'] = np.log(df['day_open'] / df['night_close'])
    df['r2_gap2'] = df['gap2'] ** 2

    # x_overnight = rv_night + r²_gap1 + r²_gap2 (or just r²_total_overnight as fallback)
    df['x_overnight'] = df['rv_night'].fillna(0) + df['r2_gap1'].fillna(0) + df['r2_gap2'].fillna(0)
    # Fallback: if night RV missing, use overnight gap squared
    mask_no_night = df['rv_night'].isna()
    df.loc[mask_no_night, 'x_overnight'] = df.loc[mask_no_night, 'r2_overnight_gap']

    # x_intraday = rv_day (5-min realized variance from day session ticks)
    df['x_intraday'] = df['rv_day']

    # Full-day realized variance: x_A + x_B
    df['rv_fullday'] = df['x_overnight'] + df['x_intraday']

    # Drop first row (needs previous day close)
    df = df.iloc[1:]

    # Build alternating session series
    sessions = []
    dates = df.index.tolist()

    for dt in dates:
        row = df.loc[dt]
        if pd.isna(row['overnight_gap']) or pd.isna(row['day_return']) or pd.isna(row['rv_day']):
            continue

        # Session type 0: OVERNIGHT
        sessions.append({
            'date': dt,
            'session_type': 0,
            'r': float(row['overnight_gap']),
            'x': float(row['x_overnight']),
        })
        # Session type 1: INTRADAY
        sessions.append({
            'date': dt,
            'session_type': 1,
            'r': float(row['day_return']),
            'x': float(row['x_intraday']),
        })

    sess_df = pd.DataFrame(sessions)

    # Add fullday target: for each pair of sessions on same date, target = x_overnight + x_intraday
    # Each day has 2 rows; the "daily target" is x_ov + x_intra
    # For evaluation: aggregate session-level forecasts to daily forecasts
    print(f"  Built session series: {len(sess_df)} sessions from {len(dates)} available days")
    print(f"  Valid days: {len(sess_df) // 2}")

    # Also return daily-level data for daily benchmarks
    daily_df = df[['overnight_gap', 'x_overnight', 'day_return', 'x_intraday', 'rv_fullday',
                   'rv_day', 'rv_night', 'day_close']].copy()
    daily_df = daily_df.dropna(subset=['rv_fullday'])

    return sess_df, daily_df


# ============================================================
# PRG Estimation
# ============================================================

def estimate_prg(r, x, s, extended=False, n_starts=5):
    """Estimate PRG via MLE with multiple random starts (numba-accelerated)."""
    n = len(r)
    n_params = 8 if extended else 6

    eps = 1e-8
    if extended:
        bounds = [
            (eps, 1e-2), (eps, 2.0), (eps, 0.999),  # omega0, alpha0, beta0
            (eps, 1e-2), (eps, 2.0), (eps, 0.999),  # omega1, alpha1, beta1
            (0.0, 2.0), (0.0, 2.0),                  # gamma0, gamma1
        ]
    else:
        bounds = [
            (eps, 1e-2), (eps, 2.0), (eps, 0.999),
            (eps, 1e-2), (eps, 2.0), (eps, 0.999),
        ]

    best_nll = np.inf
    best_params = None

    var_ov = np.var(r[s == 0]) if np.sum(s == 0) > 10 else 1e-5
    var_in = np.var(r[s == 1]) if np.sum(s == 1) > 10 else 1e-5
    rng = np.random.RandomState(42)

    # Ensure arrays are float64 for numba
    r_f = r.astype(np.float64)
    x_f = x.astype(np.float64)
    s_f = s.astype(np.float64)

    ext_flag = 1.0 if extended else 0.0

    for start_i in range(n_starts):
        if start_i == 0:
            x0 = [var_ov * 0.05, 0.15, 0.80, var_in * 0.05, 0.15, 0.80]
            if extended:
                x0 += [0.05, 0.05]
        else:
            x0 = [
                rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.40), rng.uniform(0.50, 0.95),
                rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.40), rng.uniform(0.50, 0.95),
            ]
            if extended:
                x0 += [rng.uniform(0.0, 0.2), rng.uniform(0.0, 0.2)]

        try:
            def obj(params):
                p = np.array(params, dtype=np.float64)
                return _prg_negll(p, r_f, x_f, s_f, n, extended)

            result = minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                              options={'maxiter': 2000, 'ftol': 1e-10})
            if result.fun < best_nll:
                best_nll = result.fun
                best_params = result.x
        except Exception:
            continue

    return best_params, -best_nll if best_params is not None else None


def prg_recursive_oos(params, r_all, x_all, s_all, extended=False):
    """Run full recursive PRG to get h series."""
    n = len(r_all)
    p = np.array(params, dtype=np.float64)
    r_f = r_all.astype(np.float64)
    x_f = x_all.astype(np.float64)
    s_f = s_all.astype(np.float64)
    return _prg_recursive(p, r_f, x_f, s_f, n, extended)


# ============================================================
# Separate GARCH per session (benchmark)
# ============================================================

def estimate_separate_garch(r, x, s, session_type):
    """Estimate standard GARCH(1,1) on ONE session type only."""
    mask = s == session_type
    r_sess = r[mask].astype(np.float64)
    x_sess = x[mask].astype(np.float64)
    n_sess = len(r_sess)

    if n_sess < 30:
        return None, None

    eps = 1e-8
    bounds = [(eps, 1e-2), (eps, 2.0), (eps, 0.999)]
    best_nll = np.inf
    best_params = None
    rng = np.random.RandomState(42)
    var_sess = np.var(r_sess)

    for i in range(5):
        if i == 0:
            x0 = [var_sess * 0.05, 0.15, 0.80]
        else:
            x0 = [rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.4), rng.uniform(0.5, 0.95)]

        try:
            def obj(params):
                return _sep_garch_negll(params[0], params[1], params[2],
                                        r_sess, x_sess, n_sess)
            result = minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                              options={'maxiter': 1000, 'ftol': 1e-10})
            if result.fun < best_nll:
                best_nll = result.fun
                best_params = result.x
        except Exception:
            continue

    return best_params, -best_nll if best_params is not None else None


def separate_garch_recursive_oos(params_0, params_1, r_all, x_all, s_all):
    """Run separate GARCH for each session type (no cross-session recursion)."""
    n = len(r_all)
    h = np.full(n, np.nan)
    h_state = {0: 1e-6, 1: 1e-6}

    mask0 = s_all == 0
    mask1 = s_all == 1
    h_state[0] = np.var(r_all[mask0][:min(50, mask0.sum())]) if mask0.sum() > 10 else 1e-6
    h_state[1] = np.var(r_all[mask1][:min(50, mask1.sum())]) if mask1.sum() > 10 else 1e-6
    if h_state[0] < 1e-12: h_state[0] = 1e-8
    if h_state[1] < 1e-12: h_state[1] = 1e-8

    prev_x = {0: None, 1: None}

    for t in range(n):
        st = int(s_all[t])
        params = params_0 if st == 0 else params_1
        if params is None:
            h[t] = h_state[st]
            prev_x[st] = x_all[t]
            continue

        omega, alpha, beta = params
        if prev_x[st] is not None:
            h_new = omega + alpha * prev_x[st] + beta * h_state[st]
            h_new = max(h_new, 1e-12)
            h_state[st] = h_new
            h[t] = h_new
        else:
            h[t] = h_state[st]

        prev_x[st] = x_all[t]

    return h


# ============================================================
# GJR-GARCH benchmark (daily, on close-to-close)
# ============================================================

def gjr_oos_forecast(returns, is_end, refit_freq=63):
    """GJR-GARCH(1,1) on daily close-to-close returns with rolling refit."""
    n = len(returns)
    r = returns.astype(np.float64)
    forecasts = np.full(n, np.nan)

    eps = 1e-8
    bounds = [(eps, 1e-3), (eps, 0.5), (0.0, 0.5), (eps, 0.999)]
    current_params = None
    h_state = np.var(r[:min(50, n)])

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            r_train = r[:t]
            best_nll = np.inf
            best_p = None
            rng = np.random.RandomState(42)

            for i in range(3):
                if i == 0:
                    x0 = [np.var(r_train) * 0.05, 0.08, 0.06, 0.85]
                else:
                    x0 = [rng.uniform(1e-8, 1e-4), rng.uniform(0.02, 0.2),
                           rng.uniform(0.0, 0.15), rng.uniform(0.7, 0.95)]
                try:
                    def obj(params):
                        return _gjr_negll(params[0], params[1], params[2], params[3],
                                          r_train, len(r_train))
                    result = minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                                      options={'maxiter': 1000})
                    if result.fun < best_nll:
                        best_nll = result.fun
                        best_p = result.x
                except Exception:
                    continue

            if best_p is not None:
                current_params = best_p
                h_state = _gjr_propagate(
                    current_params[0], current_params[1],
                    current_params[2], current_params[3],
                    r[:t], np.var(r[:min(50, t)]), 1, t)

        if current_params is not None:
            omega, alpha, gamma_p, beta = current_params
            indicator = 1.0 if r[t - 1] < 0 else 0.0
            h_state = omega + alpha * r[t - 1] ** 2 + gamma_p * r[t - 1] ** 2 * indicator + beta * h_state
            if h_state < 1e-12:
                h_state = 1e-12
            forecasts[t] = h_state

    return forecasts


# ============================================================
# HAR-RV benchmark (daily)
# ============================================================

def har_oos_forecast(rv_total, is_end, refit_freq=63):
    """HAR-RV on log(RV_total) with rolling refit."""
    eps = 1e-12
    log_rv = np.log(np.clip(rv_total, eps, None))
    n = len(log_rv)

    log_rv_d = pd.Series(log_rv).shift(1).values
    log_rv_5d = pd.Series(log_rv).rolling(5).mean().shift(1).values
    log_rv_22d = pd.Series(log_rv).rolling(22).mean().shift(1).values

    forecasts = np.full(n, np.nan)
    beta = None

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            train_start = 22
            y_train = log_rv[train_start:t]
            X_train = np.column_stack([
                log_rv_d[train_start:t],
                log_rv_5d[train_start:t],
                log_rv_22d[train_start:t],
            ])
            valid = np.all(np.isfinite(X_train), axis=1) & np.isfinite(y_train)
            if valid.sum() < 50:
                continue
            y_t = y_train[valid]
            X_c = np.column_stack([np.ones(len(y_t)), X_train[valid]])
            try:
                beta = np.linalg.lstsq(X_c, y_t, rcond=None)[0]
            except Exception:
                continue

        if beta is not None and np.isfinite(log_rv_d[t]) and np.isfinite(log_rv_5d[t]) and np.isfinite(log_rv_22d[t]):
            x_t = np.array([1.0, log_rv_d[t], log_rv_5d[t], log_rv_22d[t]])
            forecasts[t] = np.exp(x_t @ beta)

    return forecasts


# ============================================================
# Evaluation metrics
# ============================================================

def qlike(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    r, f = realized[valid], forecast[valid]
    return float(np.mean(r / f - np.log(r / f) - 1))


def qlike_loss_array(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    loss = np.full(len(realized), np.nan)
    r, f = realized[valid], forecast[valid]
    loss[valid] = r / f - np.log(r / f) - 1
    return loss


def mse_val(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast)
    return float(np.mean((realized[valid] - forecast[valid]) ** 2))


def mae_val(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast)
    return float(np.mean(np.abs(realized[valid] - forecast[valid])))


def hmse_val(realized, forecast):
    """Heteroskedastic MSE: mean((1 - realized/forecast)^2)."""
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    r, f = realized[valid], forecast[valid]
    return float(np.mean((1 - r / f) ** 2))


def spearman_corr(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast)
    if valid.sum() < 10:
        return np.nan, np.nan
    rho, p = sp_stats.spearmanr(realized[valid], forecast[valid])
    return float(rho), float(p)


# ============================================================
# VaR + ES back-testing
# ============================================================

def compute_var_es(sigma2_forecast, alpha_level, df_t=5):
    """
    Compute VaR and ES from variance forecast using Student-t distribution.
    VaR_alpha = sigma * t_{inv}(alpha, df)
    ES_alpha  = sigma * (-f(t_inv(alpha,df)) * (df + t_inv^2) / ((df-1) * alpha))
    """
    sigma = np.sqrt(np.clip(sigma2_forecast, 1e-12, None))
    # Scale for standardized Student-t: sqrt((df-2)/df)
    scale = np.sqrt((df_t - 2) / df_t)
    z_alpha = sp_stats.t.ppf(alpha_level, df_t)
    var_t = sigma * z_alpha / scale  # negative number

    # ES for Student-t
    f_val = sp_stats.t.pdf(z_alpha, df_t)
    es_t = sigma / scale * (-f_val * (df_t + z_alpha ** 2) / ((df_t - 1) * alpha_level))

    return var_t, es_t


def kupiec_test(violations, n_obs, alpha):
    """Kupiec (1995) unconditional coverage test."""
    n_viol = np.sum(violations)
    p_hat = n_viol / n_obs if n_obs > 0 else 0
    if p_hat == 0 or p_hat == 1:
        return np.nan, np.nan

    lr = 2 * (n_viol * np.log(p_hat / alpha) + (n_obs - n_viol) * np.log((1 - p_hat) / (1 - alpha)))
    p_value = 1 - sp_stats.chi2.cdf(lr, 1)
    return float(lr), float(p_value)


def christoffersen_test(violations):
    """Christoffersen (1998) conditional coverage (independence) test."""
    n = len(violations)
    if n < 4:
        return np.nan, np.nan

    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if violations[i - 1] == 0 and violations[i] == 0:
            n00 += 1
        elif violations[i - 1] == 0 and violations[i] == 1:
            n01 += 1
        elif violations[i - 1] == 1 and violations[i] == 0:
            n10 += 1
        else:
            n11 += 1

    if (n00 + n01) == 0 or (n10 + n11) == 0 or n01 + n11 == 0:
        return np.nan, np.nan

    p01 = n01 / (n00 + n01)
    p11 = n11 / (n10 + n11)
    p_hat = (n01 + n11) / n

    try:
        lr_ind = 2 * (
            n00 * np.log(max(1 - p01, 1e-15) / max(1 - p_hat, 1e-15))
            + n01 * np.log(max(p01, 1e-15) / max(p_hat, 1e-15))
            + n10 * np.log(max(1 - p11, 1e-15) / max(1 - p_hat, 1e-15))
            + n11 * np.log(max(p11, 1e-15) / max(p_hat, 1e-15))
        )
    except (ValueError, ZeroDivisionError):
        return np.nan, np.nan

    p_value = 1 - sp_stats.chi2.cdf(lr_ind, 1)
    return float(lr_ind), float(p_value)


def acerbi_szekely_test(returns, var_forecast, es_forecast, alpha, n_boot=1000):
    """Acerbi & Szekely (2014) ES back-test (Test 2: Z2 statistic)."""
    violations = returns < var_forecast
    n_viol = np.sum(violations)
    if n_viol < 3:
        return np.nan, np.nan

    # Z2 = (1/T) * sum( r_t * I(r_t < VaR_t) / (alpha * ES_t) ) + 1
    es_safe = np.where(np.abs(es_forecast) > 1e-15, es_forecast, -1e-15)
    z2 = np.mean(returns * violations / (alpha * es_safe)) + 1

    # Bootstrap p-value
    rng = np.random.RandomState(42)
    z2_boot = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.choice(len(returns), len(returns), replace=True)
        r_b = returns[idx]
        v_b = var_forecast[idx]
        es_b = es_forecast[idx]
        viol_b = r_b < v_b
        es_safe_b = np.where(np.abs(es_b) > 1e-15, es_b, -1e-15)
        z2_boot[b] = np.mean(r_b * viol_b / (alpha * es_safe_b)) + 1

    p_value = np.mean(z2_boot <= z2)
    return float(z2), float(p_value)


def basel_traffic_light(violation_rate, alpha):
    """Basel traffic light for VaR back-testing."""
    ratio = violation_rate / alpha
    if ratio <= 1.0:
        return "GREEN"
    elif ratio <= 1.5:
        return "YELLOW"
    else:
        return "RED"


def run_var_backtest(returns, sigma2_forecast, alpha_level=0.01, df_t=5):
    """Full VaR + ES back-test."""
    valid = np.isfinite(returns) & np.isfinite(sigma2_forecast) & (sigma2_forecast > 0)
    r = returns[valid]
    s2 = sigma2_forecast[valid]
    n_obs = len(r)

    if n_obs < 50:
        return None

    var_f, es_f = compute_var_es(s2, alpha_level, df_t)

    violations = (r < var_f).astype(int)
    viol_rate = np.mean(violations)

    kup_lr, kup_p = kupiec_test(violations, n_obs, alpha_level)
    cc_lr, cc_p = christoffersen_test(violations)
    as_z2, as_p = acerbi_szekely_test(r, var_f, es_f, alpha_level)
    traffic = basel_traffic_light(viol_rate, alpha_level)

    return {
        'alpha': alpha_level,
        'n_obs': n_obs,
        'n_violations': int(np.sum(violations)),
        'violation_rate': float(viol_rate),
        'expected_rate': alpha_level,
        'kupiec_LR': kup_lr,
        'kupiec_p': kup_p,
        'christoffersen_LR': cc_lr,
        'christoffersen_p': cc_p,
        'acerbi_szekely_Z2': as_z2,
        'acerbi_szekely_p': as_p,
        'basel_traffic_light': traffic,
    }


# ============================================================
# Charts
# ============================================================

def make_charts(model_results, daily_df_oos, charts_dir):
    """Generate comparison charts."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Chart 1: QLIKE comparison bar chart
    fig, ax = plt.subplots(figsize=(10, 6))
    names = []
    qlikes = []
    for name, data in model_results.items():
        if 'qlike_fullday' in data and data['qlike_fullday'] is not None:
            names.append(name)
            qlikes.append(data['qlike_fullday'])

    if len(names) > 0:
        sorted_idx = np.argsort(qlikes)
        names = [names[i] for i in sorted_idx]
        qlikes = [qlikes[i] for i in sorted_idx]
        colors = ['#e74c3c' if q == min(qlikes) else '#3498db' for q in qlikes]
        bars = ax.barh(range(len(names)), qlikes, color=colors)
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names, fontsize=10)
        ax.set_xlabel('QLIKE (lower = better)', fontsize=12)
        ax.set_title('K883: Full-Day QLIKE — TAIFEX TX Tick-Level PRG\n(OOS, common target σ² = RV_overnight + RV_intraday)', fontsize=12)
        for bar, val in zip(bars, qlikes):
            ax.text(bar.get_width() + max(qlikes) * 0.01, bar.get_y() + bar.get_height() / 2,
                    f'{val:.4f}', va='center', fontsize=9)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'qlike_comparison.png'), dpi=150)
        plt.close()

    # Chart 2: Spearman rank correlation
    fig, ax = plt.subplots(figsize=(10, 6))
    names_sp = []
    rhos = []
    for name, data in model_results.items():
        if 'spearman_fullday' in data and data['spearman_fullday'] is not None:
            names_sp.append(name)
            rhos.append(data['spearman_fullday'])

    if len(names_sp) > 0:
        sorted_idx = np.argsort(rhos)[::-1]
        names_sp = [names_sp[i] for i in sorted_idx]
        rhos = [rhos[i] for i in sorted_idx]
        colors = ['#e74c3c' if r == max(rhos) else '#3498db' for r in rhos]
        bars = ax.barh(range(len(names_sp)), rhos, color=colors)
        ax.set_yticks(range(len(names_sp)))
        ax.set_yticklabels(names_sp, fontsize=10)
        ax.set_xlabel('Spearman ρ (higher = better)', fontsize=12)
        ax.set_title('K883: Spearman Rank Correlation on Full-Day Variance', fontsize=12)
        for bar, val in zip(bars, rhos):
            ax.text(bar.get_width() + 0.005, bar.get_y() + bar.get_height() / 2,
                    f'{val:.4f}', va='center', fontsize=9)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'spearman_comparison.png'), dpi=150)
        plt.close()

    # Chart 3: DM test heatmap
    model_names = list(model_results.keys())
    n_models = len(model_names)
    dm_matrix = np.zeros((n_models, n_models))
    for i in range(n_models):
        for j in range(n_models):
            key = f'{model_names[i]}_vs_{model_names[j]}'
            if 'dm_tests' in model_results.get(model_names[i], {}):
                dm_dict = model_results[model_names[i]].get('dm_tests', {})
                if key in dm_dict:
                    dm_matrix[i, j] = dm_dict[key].get('t_stat', 0)

    if n_models > 1:
        fig, ax = plt.subplots(figsize=(8, 7))
        im = ax.imshow(dm_matrix, cmap='RdBu_r', vmin=-6, vmax=6)
        ax.set_xticks(range(n_models))
        ax.set_yticks(range(n_models))
        ax.set_xticklabels(model_names, rotation=45, ha='right', fontsize=8)
        ax.set_yticklabels(model_names, fontsize=8)
        for i in range(n_models):
            for j in range(n_models):
                ax.text(j, i, f'{dm_matrix[i, j]:.2f}', ha='center', va='center', fontsize=7)
        ax.set_title('K883: DM Test t-statistics\n(negative = row better than column)', fontsize=11)
        plt.colorbar(im, ax=ax, shrink=0.8)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'dm_heatmap.png'), dpi=150)
        plt.close()

    # Chart 4: Rolling 63-day QLIKE
    fig, ax = plt.subplots(figsize=(14, 6))
    for name, data in model_results.items():
        if 'qlike_series' in data and data['qlike_series'] is not None:
            series = np.array(data['qlike_series'])
            if len(series) > 63:
                rolling = pd.Series(series).rolling(63, min_periods=30).mean().values
                ax.plot(range(len(rolling)), rolling, label=name, alpha=0.8)
    ax.set_xlabel('OOS Trading Day', fontsize=12)
    ax.set_ylabel('Rolling 63-day Mean QLIKE', fontsize=12)
    ax.set_title('K883: Rolling QLIKE Over OOS Period', fontsize=12)
    ax.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'rolling_qlike.png'), dpi=150)
    plt.close()

    # Chart 5: VaR violations timeline
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    for ax_i, alpha in enumerate([0.01, 0.05]):
        ax = axes[ax_i]
        for name, data in model_results.items():
            var_key = f'var_backtest_{int(alpha*100)}pct'
            if var_key in data and data[var_key] is not None:
                vr = data[var_key].get('violation_rate', np.nan)
                n_v = data[var_key].get('n_violations', 0)
                traffic = data[var_key].get('basel_traffic_light', '?')
                ax.bar(name, vr * 100, label=f'{name} ({traffic})', alpha=0.8)
        ax.axhline(y=alpha * 100, color='red', linestyle='--', label=f'Expected {alpha*100}%')
        ax.set_ylabel('Violation Rate (%)')
        ax.set_title(f'VaR {int(alpha*100)}% Back-test')
        ax.legend(fontsize=8)
    plt.suptitle('K883: VaR Back-test Violation Rates', fontsize=12)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'var_backtest.png'), dpi=150)
    plt.close()

    print(f"  Charts saved to {charts_dir}")


# ============================================================
# Main
# ============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("K883: TAIFEX Tick-Level PRG — True Session-Frequency")
    print("      Volume-Based Rollover (TX, NOT TX1)")
    print("=" * 70)

    # ----------------------------------------------------------
    # 1. Load tick data
    # ----------------------------------------------------------
    print("\n[1/9] Loading TAIFEX TX tick data...")
    rv_df = load_all_rv_data()
    print(f"  Loaded {len(rv_df)} trading days: {rv_df.index[0].date()} to {rv_df.index[-1].date()}")

    # ----------------------------------------------------------
    # 2. Build session series
    # ----------------------------------------------------------
    print("\n[2/9] Building 2-session alternating series...")
    sess_df, daily_df = build_session_series(rv_df)

    r_arr = sess_df['r'].values.astype(np.float64)
    x_arr = sess_df['x'].values.astype(np.float64)
    s_arr = sess_df['session_type'].values.astype(np.float64)

    # Descriptive stats
    desc_stats = {}
    for stype, sname in [(0, 'overnight'), (1, 'intraday')]:
        mask = s_arr == stype
        r_s = r_arr[mask]
        x_s = x_arr[mask]
        desc_stats[sname] = {
            'n': int(mask.sum()),
            'r_mean': float(np.nanmean(r_s)),
            'r_std': float(np.nanstd(r_s)),
            'r_skew': float(sp_stats.skew(r_s[np.isfinite(r_s)])),
            'r_kurt': float(sp_stats.kurtosis(r_s[np.isfinite(r_s)])),
            'x_mean': float(np.nanmean(x_s)),
            'x_median': float(np.nanmedian(x_s)),
            'x_std': float(np.nanstd(x_s)),
        }
        print(f"  {sname.upper()} (n={desc_stats[sname]['n']}): "
              f"r_mean={desc_stats[sname]['r_mean']:.6f}, r_std={desc_stats[sname]['r_std']:.6f}, "
              f"x_mean={desc_stats[sname]['x_mean']:.2e}")

    # Full-day target (at daily level)
    rv_fullday = daily_df['rv_fullday'].values

    # ----------------------------------------------------------
    # 3. OOS split
    # ----------------------------------------------------------
    n_sessions = len(sess_df)
    n_days = len(daily_df)
    is_end_sess = int(n_sessions * IS_FRACTION)
    if is_end_sess % 2 != 0:
        is_end_sess += 1
    is_end_days = is_end_sess // 2

    print(f"\n[3/9] OOS split:")
    print(f"  Sessions: IS={is_end_sess}, OOS={n_sessions - is_end_sess}")
    print(f"  Days: IS={is_end_days}, OOS={n_days - is_end_days}")

    # ----------------------------------------------------------
    # 4. Estimate & forecast: PRG Basic (6 params)
    # ----------------------------------------------------------
    print("\n[4/9] PRG Basic (6 params)...")
    model_results = {}

    # With rolling refit
    r_is = r_arr[:is_end_sess]
    x_is = x_arr[:is_end_sess]
    s_is = s_arr[:is_end_sess]

    params_basic, ll_basic = estimate_prg(r_is, x_is, s_is, extended=False, n_starts=5)
    if params_basic is not None:
        print(f"  omega_0={params_basic[0]:.2e}, alpha_0={params_basic[1]:.4f}, beta_0={params_basic[2]:.4f}")
        print(f"  omega_1={params_basic[3]:.2e}, alpha_1={params_basic[4]:.4f}, beta_1={params_basic[5]:.4f}")
        print(f"  Persistence: ov={params_basic[1]+params_basic[2]:.4f}, intra={params_basic[4]+params_basic[5]:.4f}")

        # Rolling refit OOS
        h_basic_all = np.full(n_sessions, np.nan)
        current_params_b = params_basic.copy()

        # First pass through IS to get initial h state
        h_full = prg_recursive_oos(current_params_b, r_arr, x_arr, s_arr, extended=False)
        h_basic_all[:is_end_sess] = h_full[:is_end_sess]

        # OOS with rolling refit
        for t in range(is_end_sess, n_sessions):
            if (t - is_end_sess) % REFIT_FREQ == 0:
                p_new, ll_new = estimate_prg(r_arr[:t], x_arr[:t], s_arr[:t],
                                             extended=False, n_starts=3)
                if p_new is not None:
                    current_params_b = p_new
                # Recompute full h up to t
                h_full = prg_recursive_oos(current_params_b, r_arr[:t+1], x_arr[:t+1],
                                           s_arr[:t+1], extended=False)
                h_basic_all[t] = h_full[t]
            else:
                # Just propagate one step
                st = int(s_arr[t])
                omega = np.array([current_params_b[0], current_params_b[3]])
                alpha = np.array([current_params_b[1], current_params_b[4]])
                beta_p = np.array([current_params_b[2], current_params_b[5]])
                h_prev = h_basic_all[t - 1] if not np.isnan(h_basic_all[t - 1]) else 1e-8
                h_basic_all[t] = omega[st] + alpha[st] * x_arr[t - 1] + beta_p[st] * h_prev
                if h_basic_all[t] < 1e-12:
                    h_basic_all[t] = 1e-12

        # Aggregate to daily: h_day = h_overnight + h_intraday
        h_basic_daily = np.full(n_days, np.nan)
        for d in range(n_days):
            i_ov = 2 * d      # session index for overnight
            i_in = 2 * d + 1  # session index for intraday
            if i_in < n_sessions:
                h_ov = h_basic_all[i_ov] if not np.isnan(h_basic_all[i_ov]) else 0
                h_in = h_basic_all[i_in] if not np.isnan(h_basic_all[i_in]) else 0
                h_basic_daily[d] = h_ov + h_in

        print(f"  PRG Basic OOS forecasts: {np.sum(np.isfinite(h_basic_daily[is_end_days:]))} days")
    else:
        print("  FAILED to estimate PRG Basic!")
        h_basic_daily = np.full(n_days, np.nan)

    # ----------------------------------------------------------
    # 5. PRG Extended (8 params with leverage)
    # ----------------------------------------------------------
    print("\n[5/9] PRG Extended (8 params, with leverage)...")
    params_ext, ll_ext = estimate_prg(r_is, x_is, s_is, extended=True, n_starts=5)
    if params_ext is not None:
        print(f"  omega_0={params_ext[0]:.2e}, alpha_0={params_ext[1]:.4f}, beta_0={params_ext[2]:.4f}")
        print(f"  omega_1={params_ext[3]:.2e}, alpha_1={params_ext[4]:.4f}, beta_1={params_ext[5]:.4f}")
        print(f"  gamma_0={params_ext[6]:.4f}, gamma_1={params_ext[7]:.4f}")

        h_ext_all = np.full(n_sessions, np.nan)
        current_params_e = params_ext.copy()

        h_full_e = prg_recursive_oos(current_params_e, r_arr, x_arr, s_arr, extended=True)
        h_ext_all[:is_end_sess] = h_full_e[:is_end_sess]

        for t in range(is_end_sess, n_sessions):
            if (t - is_end_sess) % REFIT_FREQ == 0:
                p_new, ll_new = estimate_prg(r_arr[:t], x_arr[:t], s_arr[:t],
                                             extended=True, n_starts=3)
                if p_new is not None:
                    current_params_e = p_new
                h_full_e = prg_recursive_oos(current_params_e, r_arr[:t+1], x_arr[:t+1],
                                             s_arr[:t+1], extended=True)
                h_ext_all[t] = h_full_e[t]
            else:
                st = int(s_arr[t])
                omega = np.array([current_params_e[0], current_params_e[3]])
                alpha = np.array([current_params_e[1], current_params_e[4]])
                beta_p = np.array([current_params_e[2], current_params_e[5]])
                gamma = np.array([current_params_e[6], current_params_e[7]])
                h_prev = h_ext_all[t - 1] if not np.isnan(h_ext_all[t - 1]) else 1e-8
                lev = gamma[st] * x_arr[t - 1] * (1.0 if r_arr[t - 1] < 0 else 0.0)
                h_ext_all[t] = omega[st] + alpha[st] * x_arr[t - 1] + lev + beta_p[st] * h_prev
                if h_ext_all[t] < 1e-12:
                    h_ext_all[t] = 1e-12

        h_ext_daily = np.full(n_days, np.nan)
        for d in range(n_days):
            i_ov = 2 * d
            i_in = 2 * d + 1
            if i_in < n_sessions:
                h_ov = h_ext_all[i_ov] if not np.isnan(h_ext_all[i_ov]) else 0
                h_in = h_ext_all[i_in] if not np.isnan(h_ext_all[i_in]) else 0
                h_ext_daily[d] = h_ov + h_in

        print(f"  PRG Extended OOS forecasts: {np.sum(np.isfinite(h_ext_daily[is_end_days:]))} days")
    else:
        print("  FAILED to estimate PRG Extended!")
        h_ext_daily = np.full(n_days, np.nan)

    # ----------------------------------------------------------
    # 6. Separate GARCH per session (no cross-recursion)
    # ----------------------------------------------------------
    print("\n[6/9] Separate GARCH per session (no cross-recursion)...")
    params_sep0, ll_sep0 = estimate_separate_garch(r_is, x_is, s_is.astype(int), 0)
    params_sep1, ll_sep1 = estimate_separate_garch(r_is, x_is, s_is.astype(int), 1)

    if params_sep0 is not None:
        print(f"  Session 0 (overnight): omega={params_sep0[0]:.2e}, alpha={params_sep0[1]:.4f}, beta={params_sep0[2]:.4f}")
    if params_sep1 is not None:
        print(f"  Session 1 (intraday): omega={params_sep1[0]:.2e}, alpha={params_sep1[1]:.4f}, beta={params_sep1[2]:.4f}")

    h_sep_all = separate_garch_recursive_oos(params_sep0, params_sep1, r_arr, x_arr, s_arr.astype(int))

    h_sep_daily = np.full(n_days, np.nan)
    for d in range(n_days):
        i_ov = 2 * d
        i_in = 2 * d + 1
        if i_in < n_sessions:
            h_ov = h_sep_all[i_ov] if not np.isnan(h_sep_all[i_ov]) else 0
            h_in = h_sep_all[i_in] if not np.isnan(h_sep_all[i_in]) else 0
            h_sep_daily[d] = h_ov + h_in

    print(f"  Separate GARCH OOS: {np.sum(np.isfinite(h_sep_daily[is_end_days:]))} days")

    # ----------------------------------------------------------
    # 7. GJR-GARCH benchmark (daily c2c returns)
    # ----------------------------------------------------------
    print("\n[7/9] GJR-GARCH on close-to-close returns...")
    # Build daily close-to-close returns
    daily_close = daily_df['day_close'].values.astype(np.float64)
    # Drop NaN from close prices before computing returns
    valid_close = np.isfinite(daily_close)
    c2c_returns = np.full(len(daily_close), np.nan)
    for i in range(1, len(daily_close)):
        if valid_close[i] and valid_close[i - 1] and daily_close[i - 1] > 0:
            c2c_returns[i] = np.log(daily_close[i] / daily_close[i - 1])

    # For GJR: need contiguous non-NaN series. Fill the first entry with 0.
    c2c_returns[0] = 0.0
    # Replace any remaining NaN with 0 (very rare, just to keep array clean for numba)
    c2c_clean = np.where(np.isfinite(c2c_returns), c2c_returns, 0.0)

    h_gjr_daily = gjr_oos_forecast(c2c_clean, is_end_days, refit_freq=63)
    print(f"  GJR OOS forecasts: {np.sum(np.isfinite(h_gjr_daily[is_end_days:]))} days")

    # ----------------------------------------------------------
    # 8. HAR-RV benchmark (daily)
    # ----------------------------------------------------------
    print("\n[8/9] HAR-RV on daily RV_total...")
    h_har_daily = har_oos_forecast(rv_fullday, is_end_days, refit_freq=63)
    print(f"  HAR-RV OOS forecasts: {np.sum(np.isfinite(h_har_daily[is_end_days:]))} days")

    # ----------------------------------------------------------
    # 9. Evaluate all models
    # ----------------------------------------------------------
    print("\n[9/9] Evaluation on OOS period...")

    # OOS targets and returns
    target_oos = rv_fullday[is_end_days:]
    c2c_oos = c2c_clean[is_end_days:]

    model_forecasts = {
        'PRG_Basic': h_basic_daily[is_end_days:],
        'PRG_Extended': h_ext_daily[is_end_days:],
        'Separate_GARCH': h_sep_daily[is_end_days:],
        'GJR_GARCH': h_gjr_daily[is_end_days:],
        'HAR_RV': h_har_daily[is_end_days:],
    }

    # Compute metrics for each model
    for name, forecast in model_forecasts.items():
        result = {}
        valid = np.isfinite(target_oos) & np.isfinite(forecast) & (forecast > 0) & (target_oos > 0)
        n_valid = valid.sum()
        result['n_oos'] = int(n_valid)

        if n_valid < 50:
            print(f"  {name}: insufficient OOS data ({n_valid})")
            model_results[name] = result
            continue

        result['qlike_fullday'] = qlike(target_oos, forecast)
        result['mse_fullday'] = mse_val(target_oos, forecast)
        result['mae_fullday'] = mae_val(target_oos, forecast)
        result['hmse_fullday'] = hmse_val(target_oos, forecast)

        rho, p_sp = spearman_corr(target_oos, forecast)
        result['spearman_fullday'] = rho
        result['spearman_p'] = p_sp

        # QLIKE loss series for DM test and rolling chart
        result['qlike_series'] = qlike_loss_array(target_oos, forecast).tolist()

        # VaR back-test at 1% and 5%
        for alpha in [0.01, 0.05]:
            var_result = run_var_backtest(c2c_oos, forecast, alpha_level=alpha, df_t=5)
            result[f'var_backtest_{int(alpha*100)}pct'] = var_result

        model_results[name] = result
        print(f"  {name}: QLIKE={result['qlike_fullday']:.6f}, Spearman={rho:.4f}, "
              f"n={n_valid}")

    # DM tests (pairwise, QLIKE loss)
    print("\n  DM Tests (pairwise, Harvey |t|>3.0):")
    model_names = list(model_forecasts.keys())
    dm_results_all = {}
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            name_i = model_names[i]
            name_j = model_names[j]
            loss_i = qlike_loss_array(target_oos, model_forecasts[name_i])
            loss_j = qlike_loss_array(target_oos, model_forecasts[name_j])

            valid_both = np.isfinite(loss_i) & np.isfinite(loss_j)
            if valid_both.sum() < 50:
                continue

            t_stat, p_val = dm_test(loss_i[valid_both], loss_j[valid_both], h=1)
            sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "")
            winner = name_i if t_stat < 0 else name_j
            print(f"    {name_i} vs {name_j}: t={t_stat:.3f}, p={p_val:.4f} {sig} "
                  f"(winner: {winner})")

            key_ij = f'{name_i}_vs_{name_j}'
            key_ji = f'{name_j}_vs_{name_i}'
            dm_entry = {
                't_stat': float(t_stat),
                'p_value': float(p_val),
                'significant_harvey': abs(t_stat) > 3.0,
                'winner': winner,
            }
            dm_results_all[key_ij] = dm_entry

            # Store in model results
            if 'dm_tests' not in model_results.get(name_i, {}):
                model_results.setdefault(name_i, {})['dm_tests'] = {}
            model_results[name_i]['dm_tests'][key_ij] = dm_entry

            # Reverse
            dm_entry_rev = dm_entry.copy()
            dm_entry_rev['t_stat'] = -float(t_stat)
            if 'dm_tests' not in model_results.get(name_j, {}):
                model_results.setdefault(name_j, {})['dm_tests'] = {}
            model_results[name_j]['dm_tests'][key_ji] = dm_entry_rev

    # Parameters summary
    params_summary = {}
    if params_basic is not None:
        params_summary['PRG_Basic'] = {
            'omega_0': float(params_basic[0]), 'alpha_0': float(params_basic[1]),
            'beta_0': float(params_basic[2]),
            'omega_1': float(params_basic[3]), 'alpha_1': float(params_basic[4]),
            'beta_1': float(params_basic[5]),
            'persistence_ov': float(params_basic[1] + params_basic[2]),
            'persistence_in': float(params_basic[4] + params_basic[5]),
            'loglik': ll_basic,
        }
    if params_ext is not None:
        params_summary['PRG_Extended'] = {
            'omega_0': float(params_ext[0]), 'alpha_0': float(params_ext[1]),
            'beta_0': float(params_ext[2]),
            'omega_1': float(params_ext[3]), 'alpha_1': float(params_ext[4]),
            'beta_1': float(params_ext[5]),
            'gamma_0': float(params_ext[6]), 'gamma_1': float(params_ext[7]),
            'persistence_ov': float(params_ext[1] + params_ext[2]),
            'persistence_in': float(params_ext[4] + params_ext[5]),
            'loglik': ll_ext,
        }
    if params_sep0 is not None:
        params_summary['Separate_GARCH_overnight'] = {
            'omega': float(params_sep0[0]), 'alpha': float(params_sep0[1]),
            'beta': float(params_sep0[2]),
            'persistence': float(params_sep0[1] + params_sep0[2]),
            'loglik': ll_sep0,
        }
    if params_sep1 is not None:
        params_summary['Separate_GARCH_intraday'] = {
            'omega': float(params_sep1[0]), 'alpha': float(params_sep1[1]),
            'beta': float(params_sep1[2]),
            'persistence': float(params_sep1[1] + params_sep1[2]),
            'loglik': ll_sep1,
        }

    # Generate charts
    print("\n  Generating charts...")
    try:
        make_charts(model_results, daily_df.iloc[is_end_days:], CHARTS_DIR)
    except Exception as e:
        print(f"  Chart generation error: {e}")

    # ----------------------------------------------------------
    # Save results
    # ----------------------------------------------------------
    elapsed = time.time() - t0

    # Clean up model_results for JSON serialization
    for name in model_results:
        if 'qlike_series' in model_results[name]:
            # Keep only summary, not full series in JSON
            series = model_results[name]['qlike_series']
            if series is not None:
                valid_s = [v for v in series if v is not None and np.isfinite(v)]
                model_results[name]['qlike_series_summary'] = {
                    'mean': float(np.mean(valid_s)) if valid_s else None,
                    'median': float(np.median(valid_s)) if valid_s else None,
                    'std': float(np.std(valid_s)) if valid_s else None,
                    'n': len(valid_s),
                }
            del model_results[name]['qlike_series']

    # Find overall winner
    qlikes_all = {name: model_results[name].get('qlike_fullday')
                  for name in model_results if model_results[name].get('qlike_fullday') is not None}
    winner = min(qlikes_all, key=qlikes_all.get) if qlikes_all else "N/A"

    output = {
        'experiment_id': 'K883',
        'title': 'TAIFEX Tick-Level PRG — True Session-Frequency with Volume-Based Rollover',
        'date': datetime.now().isoformat(),
        'data_source': 'TAIFEX TX tick data (volume-based rollover)',
        'data_period': f"{rv_df.index[0].date()} to {rv_df.index[-1].date()}",
        'n_trading_days': len(daily_df),
        'n_sessions': n_sessions,
        'is_days': is_end_days,
        'oos_days': n_days - is_end_days,
        'refit_freq_sessions': REFIT_FREQ,
        'descriptive_stats': desc_stats,
        'parameters': params_summary,
        'model_results': model_results,
        'dm_tests': dm_results_all,
        'winner_qlike': winner,
        'conclusion': (
            f"QLIKE winner: {winner}. "
            f"QLIKE scores: {', '.join(f'{k}={v:.6f}' for k, v in sorted(qlikes_all.items(), key=lambda x: x[1]))}. "
            f"Based on TAIFEX TX tick data with volume-based rollover (NOT TX1), "
            f"2-session PRG (overnight + intraday) with 5-min realized variance."
        ),
        'elapsed_seconds': elapsed,
        'references': [
            'Lai et al. (2024): Periodic GARCH with regime switching',
            'Bollerslev & Ghysels (1996): Periodic GARCH',
            'Corsi (2009): HAR-RV model',
            'Hansen & Lunde (2005): Realized GARCH',
            'Patton (2011): QLIKE proxy-robust loss',
            'Kupiec (1995): VaR back-testing',
            'Christoffersen (1998): Conditional coverage',
            'Acerbi & Szekely (2014): ES back-testing',
        ],
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n{'=' * 70}")
    print(f"K883 COMPLETE in {elapsed:.1f}s")
    print(f"Winner (QLIKE): {winner}")
    print(f"Results: {OUTPUT_FILE}")
    print(f"Charts: {CHARTS_DIR}")
    print(f"{'=' * 70}")

    return output


if __name__ == '__main__':
    main()
