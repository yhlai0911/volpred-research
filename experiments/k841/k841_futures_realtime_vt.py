"""
K841: TAIFEX Night Session Stale-Daily-VIX Overlay Evaluation
==============================================================

Original hypothesis (proposed by user, 2026-04-03):
  Taiwan stocks trade 9:00-13:30, but TAIFEX TX night session 15:00-05:00
  covers US market hours. A tradable intraday VIX signal could in principle
  adjust exposure before the next cash-market open. This implementation has
  only daily VIX closes, however, so it evaluates a stale as-of signal and
  must not be described as real-time hedging.

Strategies:
  S0: Buy & Hold 0050.TW (baseline)
  S1: 8.63/VIX next-day adjustment (existing strategy)
  S2: Buy-and-hold 0050.TW plus an always-on TX night hedge
  S3: VIX spike guard (only hedge when VIX jumps > +2 points)

Data:
  - TAIFEX TX tick data (Big5 CSV), night session from 2017-05-16
  - VIX (yfinance ^VIX, daily)
  - 0050.TW (yfinance, with clean_tw50_data)

References:
  - K687: Correct-lag VT strategies cannot beat BH 50/50 on Sharpe
  - K688: VT wins on CRRA utility for gamma >= 5
  - K697: VIX predicts vol magnitude (corr 0.57) but not direction (corr 0.04)

Error log rules:
  - 0050.TW: must use clean_tw50_data
  - signal.shift(1): VIX uses previous day
  - The legacy full-file-volume contract rule is ex-post, not executable
  - Night session liquidity ~57% of day session
  - Only use data from 2017-05-16 onwards
"""

import argparse
import glob
import hashlib
import json
import os
import sys
import time
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, as_completed
from volpred.stats.model_evaluation import (
    dm_test as canonical_dm_test,
    strategy_dm_test,
)

warnings.filterwarnings('ignore')

# Constants
TAIFEX_DIR = os.environ.get(
    'VOLPRED_TAIFEX_DIR',
    '/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python',
)
NIGHT_SESSION_START = 20170516  # First day with night session data
ANALYSIS_END = 20260402  # Freeze the published sample for methodology-only repair
YFINANCE_END_EXCLUSIVE = '2026-04-03'
VIX_ANCHOR = 8.63  # Taiwan VT anchor from existing strategy
MIN_FILE_SIZE = 100  # Skip empty/corrupt files
FUTURES_TX_COST_PCT = 0.0001  # ~2 ticks round-trip ≈ 0.01%
WEIGHT_CHANGE_THRESHOLD = 0.05  # Only trade if weight change > 5%
FORECAST_HORIZON = 1
HARVEY_LIU_ZHU_THRESHOLD = 3.0
HAC_LAG_SENSITIVITY = (0, 1, 5, 10, 20)
EXPECTED_ANALYSIS_SLICE_SHA256 = '79970c5d4fdc2b998511e27923671e0e56d5d102358fc856ea5cc6ee42ad617b'
SCRIPT_DIR = Path(__file__).resolve().parent
YFINANCE_SNAPSHOT_PATH = SCRIPT_DIR / 'data' / 'k841_yfinance_snapshot.csv'
EXPECTED_YFINANCE_SNAPSHOT_SHA256 = 'e099454ea239f8b5bbc999c5536dafc16b99af57a3afde9a028f371aa869a899'
LEGACY_DM_EVIDENCE_PATH = SCRIPT_DIR / 'k841_legacy_dm_losses.npz'
EXPECTED_LEGACY_DM_EVIDENCE_SHA256 = 'a2121b3923942c45ae3de97dd6d938cab4fed99eeeb2858fb5510de4b02b7352'
LEGACY_SOURCE_COMMIT = '76aa426d0fee034cf012d21c89489c033cdae58e'

# Time boundaries (HHMMSS format integer)
NIGHT_START = 150000
NIGHT_END_NEXTDAY = 50000  # 05:00 next day
DAY_START = 84500
DAY_END = 134500


def parse_single_tx_file(filepath):
    """Parse a single TX CSV file, extract night/day session OHLC for near-month."""
    try:
        fsize = os.path.getsize(filepath)
        if fsize < MIN_FILE_SIZE:
            raise ValueError(f'TAIFEX file is too small: {filepath} ({fsize} bytes)')

        df = pd.read_csv(filepath, encoding='big5', low_memory=False)

        # Filter to TX only (should already be, but safe)
        df = df[df['商品代號'].str.strip() == 'TX']
        if df.empty:
            raise ValueError(f'TAIFEX file contains no TX rows: {filepath}')

        # Identify near-month by highest total volume
        vol_by_exp = df.groupby('到期月份(週別)')['成交數量(B+S)'].sum()
        near_month = vol_by_exp.idxmax()
        df = df[df['到期月份(週別)'] == near_month].copy()

        # Get trading date from filename
        basename = os.path.basename(filepath)
        # Daily_YYYY_MM_DDTX.csv
        parts = basename.replace('Daily_', '').replace('TX.csv', '').split('_')
        file_date_str = ''.join(parts)  # YYYYMMDD
        file_date = int(file_date_str)

        result = {'file_date': file_date, 'near_month': int(near_month)}

        # === Night session ===
        # A Monday file can contain Friday PM + Saturday AM + Monday day rows.
        # Therefore the continuation date is the calendar day after the actual
        # >=15:00 start date, not necessarily file_date. The old first/last-date
        # shortcut silently dropped every Saturday-AM continuation.
        night_start_rows = df[
            (df['成交日期'] < file_date) & (df['成交時間'] >= NIGHT_START)
        ]
        if night_start_rows.empty:
            result['night_session_status'] = 'unavailable_no_pm_start'
            result['night_ticks'] = 0
        else:
            night_start_date = int(night_start_rows['成交日期'].max())
            continuation_date = int(
                (pd.to_datetime(str(night_start_date), format='%Y%m%d') + pd.Timedelta(days=1))
                .strftime('%Y%m%d')
            )
            night_p1 = df[
                (df['成交日期'] == night_start_date)
                & (df['成交時間'] >= NIGHT_START)
            ]
            night_p2 = df[
                (df['成交日期'] == continuation_date)
                & (df['成交時間'] < NIGHT_END_NEXTDAY)
            ]
            night_df = pd.concat([night_p1, night_p2]).sort_values(
                ['成交日期', '成交時間'], kind='stable'
            )
            if len(night_df) < 2:
                raise RuntimeError(
                    f'Night session has fewer than two ticks in {filepath}: '
                    f'{night_start_date}->{continuation_date}'
                )
            observed_dates = set(int(value) for value in night_df['成交日期'].unique())
            if not observed_dates.issubset({night_start_date, continuation_date}):
                raise RuntimeError(f'Night session identity escaped its two calendar dates: {filepath}')
            result.update({
                'night_session_status': 'available',
                'night_start_date': night_start_date,
                'night_continuation_date': continuation_date,
                'night_open': float(night_df.iloc[0]['成交價格']),
                'night_close': float(night_df.iloc[-1]['成交價格']),
                'night_high': float(night_df['成交價格'].max()),
                'night_low': float(night_df['成交價格'].min()),
                'night_volume': float(night_df['成交數量(B+S)'].sum()),
                'night_ticks': int(len(night_df)),
            })

        # === Day session ===
        day_df = df[(df['成交日期'] == file_date) &
                    (df['成交時間'] >= DAY_START) &
                    (df['成交時間'] <= DAY_END)]

        if len(day_df) < 2:
            raise RuntimeError(f'Day session has fewer than two ticks in {filepath}')
        day_df = day_df.sort_values('成交時間', kind='stable')
        result['day_open'] = float(day_df.iloc[0]['成交價格'])
        result['day_close'] = float(day_df.iloc[-1]['成交價格'])
        result['day_high'] = float(day_df['成交價格'].max())
        result['day_low'] = float(day_df['成交價格'].min())
        result['day_volume'] = float(day_df['成交數量(B+S)'].sum())
        result['day_ticks'] = int(len(day_df))

        return result

    except Exception as exc:
        raise RuntimeError(f'Failed to parse TAIFEX source file {filepath}') from exc


def load_tx_data_parallel(start_date=NIGHT_SESSION_START, n_workers=8):
    """Load all TX files in parallel, return DataFrame with night/day session data."""
    pattern = os.path.join(TAIFEX_DIR, 'Daily_*TX.csv')
    all_files = sorted(glob.glob(pattern))

    # Filter: only main TX files (not TX1, TX2 etc.), and >= start_date
    valid_files = []
    for f in all_files:
        basename = os.path.basename(f)
        # Must end with TX.csv (not TX1.csv, TX2.csv)
        if not basename.endswith('TX.csv'):
            continue
        # Extract date
        parts = basename.replace('Daily_', '').replace('TX.csv', '').split('_')
        try:
            fdate = int(''.join(parts))
            if start_date <= fdate <= ANALYSIS_END:
                valid_files.append(f)
        except ValueError:  # silent-ok: malformed noncanonical filenames are not experiment inputs.
            continue

    print(f"Loading {len(valid_files)} TX files from {start_date}...")
    t0 = time.time()

    results = []
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(parse_single_tx_file, f): f for f in valid_files}
        for future in as_completed(futures):
            r = future.result()
            if r is not None:
                results.append(r)

    tx_df = pd.DataFrame(results)
    if tx_df.empty:
        raise RuntimeError('No TAIFEX rows were parsed for the frozen sample')
    if tx_df['file_date'].duplicated().any():
        duplicates = tx_df.loc[tx_df['file_date'].duplicated(), 'file_date'].tolist()
        raise RuntimeError(f'Duplicate TAIFEX file dates after parsing: {duplicates[:10]}')
    tx_df = tx_df.sort_values('file_date').reset_index(drop=True)
    elapsed = time.time() - t0
    print(f"Loaded {len(tx_df)} trading days in {elapsed:.1f}s")

    # Convert file_date to datetime
    tx_df['date'] = pd.to_datetime(tx_df['file_date'].astype(str), format='%Y%m%d')

    return tx_df


def refresh_yfinance_snapshot():
    """Download and atomically freeze the only Yahoo fields used by K841."""
    import yfinance as yf

    print('Refreshing frozen VIX and 0050.TW snapshot from yfinance...')

    vix = yf.download(
        '^VIX', start='2017-01-01', end=YFINANCE_END_EXCLUSIVE,
        auto_adjust=True, progress=False, threads=False,
    )
    if vix.empty:
        raise RuntimeError('yfinance returned no ^VIX data for the frozen sample')
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix_close = vix['Close'].squeeze()
    if isinstance(vix_close, pd.DataFrame):
        vix_close = vix_close.iloc[:, 0]
    vix_close = vix_close.rename('vix_close')

    tw50 = yf.download(
        '0050.TW', start='2017-01-01', end=YFINANCE_END_EXCLUSIVE,
        auto_adjust=True, progress=False, threads=False,
    )
    if tw50.empty:
        raise RuntimeError('yfinance returned no 0050.TW data for the frozen sample')
    if isinstance(tw50.columns, pd.MultiIndex):
        tw50.columns = tw50.columns.get_level_values(0)
    tw50_open = tw50['Open'].squeeze()
    tw50_close = tw50['Close'].squeeze()
    if isinstance(tw50_open, pd.DataFrame):
        tw50_open = tw50_open.iloc[:, 0]
    if isinstance(tw50_close, pd.DataFrame):
        tw50_close = tw50_close.iloc[:, 0]

    snapshot = pd.concat(
        [
            vix_close,
            tw50_open.rename('tw50_adjusted_open'),
            tw50_close.rename('tw50_adjusted_close'),
        ],
        axis=1,
    ).sort_index()
    snapshot.index = pd.to_datetime(snapshot.index).tz_localize(None)
    snapshot.index.name = 'date'
    if snapshot.index.duplicated().any() or not snapshot.index.is_monotonic_increasing:
        raise RuntimeError('Downloaded yfinance snapshot dates are not unique and increasing')
    if snapshot[['vix_close', 'tw50_adjusted_open', 'tw50_adjusted_close']].notna().sum().min() < 2000:
        raise RuntimeError('Downloaded yfinance snapshot has unexpectedly sparse fields')

    payload = snapshot.to_csv(
        index=True,
        date_format='%Y-%m-%d',
        float_format='%.10f',
        lineterminator='\n',
    )
    YFINANCE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = YFINANCE_SNAPSHOT_PATH.with_name(f'.{YFINANCE_SNAPSHOT_PATH.name}.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, YFINANCE_SNAPSHOT_PATH)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    snapshot_hash = sha256_file(YFINANCE_SNAPSHOT_PATH)
    print(f'Frozen yfinance snapshot sha256: {snapshot_hash}')
    return snapshot_hash


def load_vix_and_0050():
    """Load VIX and 0050.TW from the committed, hash-pinned snapshot."""
    from volpred.utils import clean_tw50_data

    if not YFINANCE_SNAPSHOT_PATH.exists():
        raise RuntimeError(
            f'Missing frozen yfinance snapshot: {YFINANCE_SNAPSHOT_PATH}. '
            'Run this script once with --refresh-yfinance-snapshot.'
        )
    snapshot_hash = sha256_file(YFINANCE_SNAPSHOT_PATH)
    if snapshot_hash != EXPECTED_YFINANCE_SNAPSHOT_SHA256:
        raise RuntimeError(
            'Frozen yfinance snapshot changed: '
            f'expected {EXPECTED_YFINANCE_SNAPSHOT_SHA256}, got {snapshot_hash}'
        )

    print('Loading VIX and 0050.TW from frozen local snapshot...')
    snapshot = pd.read_csv(
        YFINANCE_SNAPSHOT_PATH,
        parse_dates=['date'],
        index_col='date',
        float_precision='round_trip',
    )
    required = {'vix_close', 'tw50_adjusted_open', 'tw50_adjusted_close'}
    if set(snapshot.columns) != required:
        raise RuntimeError(
            'Frozen yfinance snapshot schema changed: '
            f'expected {sorted(required)}, got {sorted(snapshot.columns)}'
        )
    if snapshot.index.duplicated().any() or not snapshot.index.is_monotonic_increasing:
        raise RuntimeError('Frozen yfinance snapshot dates are not unique and increasing')
    expected_counts = {
        'vix_close': 2325,
        'tw50_adjusted_open': 2244,
        'tw50_adjusted_close': 2244,
    }
    if (
        len(snapshot) != 2399
        or snapshot.index[0] != pd.Timestamp('2017-01-03')
        or snapshot.index[-1] != pd.Timestamp('2026-04-02')
        or snapshot.notna().sum().to_dict() != expected_counts
    ):
        raise RuntimeError('Frozen yfinance snapshot row count or date bounds changed')
    if not snapshot['tw50_adjusted_open'].isna().equals(snapshot['tw50_adjusted_close'].isna()):
        raise RuntimeError('Frozen 0050 Open/Close missingness does not match')
    for column in sorted(required):
        observed = snapshot[column].dropna().to_numpy(dtype=float)
        if not np.isfinite(observed).all() or not (observed > 0).all():
            raise RuntimeError(f'Frozen yfinance snapshot has invalid values in {column}')

    vix_close = snapshot['vix_close'].dropna().rename('vix')
    tw50 = snapshot[['tw50_adjusted_open', 'tw50_adjusted_close']].dropna()
    tw50_prices = tw50['tw50_adjusted_close']
    clean_prices, clean_returns = clean_tw50_data(tw50_prices)
    tw50_close = clean_prices.rename('tw50_close')
    tw50_ret = clean_returns.rename('tw50_ret')
    tw50_open_raw = tw50['tw50_adjusted_open']
    # Apply the exact close-cleaning scale to Open so gap and intraday returns
    # use the same split-adjusted price basis.
    close_scale = clean_prices / tw50_prices
    tw50_open = (tw50_open_raw * close_scale).rename('tw50_open')
    tw50_gap_ret = (tw50_open / clean_prices.shift(1) - 1.0).rename('tw50_gap_ret')
    tw50_intraday_ret = (clean_prices / tw50_open - 1.0).rename('tw50_intraday_ret')
    valid_open = np.isfinite(tw50_open) & (tw50_open > 0)
    if not bool(valid_open.loc[tw50_open.index >= '2017-01-01'].all()):
        raise RuntimeError('0050.TW contains non-positive or non-finite adjusted Open prices')

    print(f"  VIX: {len(vix_close)} days, 0050.TW: {len(tw50_close)} days")
    return (
        vix_close,
        tw50_close,
        tw50_ret,
        tw50_gap_ret,
        tw50_intraday_ret,
        snapshot_hash,
    )


def compute_strategies(
    tx_df,
    vix,
    tw50_close,
    tw50_ret,
    tw50_gap_ret,
    tw50_intraday_ret,
):
    """Compute all strategy returns."""

    # Build a merged DataFrame
    # Index: trading date (day session date)
    merged = pd.DataFrame(index=tx_df['date'])

    # Add TX data
    for col in ['night_open', 'night_close', 'night_high', 'night_low', 'night_volume',
                'night_session_status', 'night_start_date', 'night_continuation_date',
                'day_open', 'day_close', 'day_volume', 'night_ticks']:
        if col in tx_df.columns:
            merged[col] = tx_df[col].values

    # Add VIX with CORRECT timing for night session hedge
    # CRITICAL TIMING (Taiwan time):
    #   Taiwan day T file contains:
    #     Night session: (T-1) 15:00 to (T) 05:00
    #     Day session:   (T) 08:45 to (T) 13:45
    #
    #   US VIX(T-1) closes at ~04:00 Taiwan time on day T
    #     = DURING the night session, NOT before it starts
    #
    #   Night session starts at 15:00 Taiwan time on (T-1)
    #     = Before US market opens for day (T-1)
    #
    # Therefore:
    #   - For DAY SESSION signal (S1): use VIX(T-1) = most recent VIX before date T
    #     This is correct because day session starts at 08:45 on T, well after VIX(T-1) closes at 04:00
    #   - For NIGHT SESSION hedge (S2/S3): use the last VIX close strictly
    #     before the actual >=15:00 night_start_date carried by the TX file.
    #     This as-of rule handles US holidays without assuming "second row".
    #
    # vix_for_day   = VIX(T-1): for day session S1 strategy (available by 08:45 Taiwan time on T)
    # vix_for_night = last US close before actual night_start_date

    vix_df = vix.to_frame()
    vix_df.index = pd.to_datetime(vix_df.index).tz_localize(None)

    merged['vix_for_day'] = np.nan    # VIX(T-1): for S1 day session
    merged['vix_for_night'] = np.nan  # last VIX close before actual night start
    merged['vix_current'] = np.nan    # VIX(T-1): for reference

    vix_dates = sorted(vix_df.index)
    for i, date in enumerate(merged.index):
        # VIX dates strictly before this Taiwan date
        prev_vix_dates = [d for d in vix_dates if d < date]
        if len(prev_vix_dates) >= 1:
            # VIX(T-1): most recent US close before Taiwan date T
            merged.loc[date, 'vix_for_day'] = vix_df.loc[prev_vix_dates[-1], 'vix']
            merged.loc[date, 'vix_current'] = vix_df.loc[prev_vix_dates[-1], 'vix']
        night_start_value = merged.loc[date, 'night_start_date']
        if pd.notna(night_start_value):
            night_start_date = pd.to_datetime(
                str(int(night_start_value)), format='%Y%m%d'
            )
            night_vix_dates = [d for d in vix_dates if d < night_start_date]
            if night_vix_dates:
                merged.loc[date, 'vix_for_night'] = vix_df.loc[
                    night_vix_dates[-1], 'vix'
                ]

    # Add 0050.TW data
    tw50_close_df = tw50_close.to_frame()
    tw50_close_df.index = pd.to_datetime(tw50_close_df.index).tz_localize(None)
    tw50_ret_df = tw50_ret.to_frame()
    tw50_ret_df.index = pd.to_datetime(tw50_ret_df.index).tz_localize(None)
    tw50_gap_df = tw50_gap_ret.to_frame()
    tw50_gap_df.index = pd.to_datetime(tw50_gap_df.index).tz_localize(None)
    tw50_intraday_df = tw50_intraday_ret.to_frame()
    tw50_intraday_df.index = pd.to_datetime(tw50_intraday_df.index).tz_localize(None)

    # Match by date
    for date in merged.index:
        if date in tw50_close_df.index:
            merged.loc[date, 'tw50_close'] = tw50_close_df.loc[date, 'tw50_close']
        if date in tw50_ret_df.index:
            merged.loc[date, 'tw50_ret'] = tw50_ret_df.loc[date, 'tw50_ret']
        if date in tw50_gap_df.index:
            merged.loc[date, 'tw50_gap_ret'] = tw50_gap_df.loc[date, 'tw50_gap_ret']
        if date in tw50_intraday_df.index:
            merged.loc[date, 'tw50_intraday_ret'] = tw50_intraday_df.loc[date, 'tw50_intraday_ret']

    # Drop rows without essential data
    merged = merged.dropna(subset=[
        'vix_for_day', 'tw50_ret',
        'tw50_gap_ret', 'tw50_intraday_ret',
    ])
    available_without_signal = merged['night_session_status'].eq('available') & merged[
        'vix_for_night'
    ].isna()
    if bool(available_without_signal.any()):
        raise RuntimeError(
            'Tradable night sessions lack an as-of VIX signal: '
            + ', '.join(str(value.date()) for value in merged.index[available_without_signal][:10])
        )
    reconstructed = (
        (1.0 + merged['tw50_gap_ret'])
        * (1.0 + merged['tw50_intraday_ret'])
        - 1.0
    )
    if not np.allclose(reconstructed, merged['tw50_ret'], atol=1e-12, rtol=1e-10):
        raise RuntimeError('0050.TW gap/intraday returns do not reconstruct close-to-close return')
    print(f"Merged dataset: {len(merged)} trading days ({merged.index[0].date()} to {merged.index[-1].date()})")

    # === Signals with CORRECT timing ===
    # S1 (day session): uses vix_for_day = VIX(T-1), known by 08:45 Taiwan time
    merged['target_weight_day'] = np.minimum(VIX_ANCHOR / merged['vix_for_day'], 1.0)
    # S2/S3 (night session): last VIX close before the actual TX night start.
    merged['target_weight_night'] = np.minimum(VIX_ANCHOR / merged['vix_for_night'], 1.0)

    # === S0: Buy & Hold 0050.TW ===
    merged['s0_ret'] = merged['tw50_ret']

    # === S1: 8.63/VIX open rebalance ===
    # VIX(T-1) becomes available before the Taiwan open on T, but after the
    # T-1 close -> T open gap has already accrued. The previous held weight
    # applies to the gap; the new weight applies only open -> close.
    merged['s1_weight'] = merged['target_weight_day']
    s1_weight = merged['s1_weight'].copy()
    prev_w = 1.0
    s1_trade_cost = pd.Series(0.0, index=merged.index)
    s1_overnight_weight = pd.Series(0.0, index=merged.index)
    for i in range(len(s1_weight)):
        s1_overnight_weight.iloc[i] = prev_w
        w = s1_weight.iloc[i]
        if abs(w - prev_w) < WEIGHT_CHANGE_THRESHOLD:
            s1_weight.iloc[i] = prev_w  # Keep previous weight
        else:
            # Approximate stock trading cost as position change
            # For simplicity: 0.1425% commission + 0.3% tax on sells (standard TW)
            # But we simplify to a proportional cost
            s1_trade_cost.iloc[i] = abs(w - prev_w) * 0.003  # ~0.3% per unit traded
            prev_w = w
    merged['s1_weight_adj'] = s1_weight
    merged['s1_overnight_weight'] = s1_overnight_weight
    merged['s1_stock_gross_ret'] = (
        (1.0 + merged['s1_overnight_weight'] * merged['tw50_gap_ret'])
        * (1.0 + merged['s1_weight_adj'] * merged['tw50_intraday_ret'])
        - 1.0
    )
    merged['s1_trade_cost'] = s1_trade_cost
    merged['s1_ret'] = merged['s1_stock_gross_ret'] - merged['s1_trade_cost']

    # === S2: Night session hedge ===
    # Logic: Always hold 0050.TW. If target_weight < 1, hedge difference via TX short at night.
    # Night session return = (night_close - night_open) / night_open
    # Hedge return = -(1 - target_weight) * night_return (short exposure)
    # Total = tw50_ret + hedge_return

    merged['night_available'] = (
        merged['night_session_status'].eq('available')
        & merged['night_open'].notna()
        & merged['night_close'].notna()
        & (merged['night_open'] > 0)
    )
    merged['night_ret'] = np.where(
        merged['night_available'],
        (merged['night_close'] - merged['night_open']) / merged['night_open'],
        np.nan,
    )

    # Night hedge uses the last VIX close available before the actual night start.
    merged['hedge_ratio'] = np.maximum(1.0 - merged['target_weight_night'], 0.0)  # How much to short

    # Each observation is one nightly open->close hedge. The position is
    # closed at 05:00 and reopened at 15:00, so every active night pays the
    # round-trip cost even when the target ratio is unchanged from yesterday.
    prev_hedge = 0.0
    hedge_ratio_adj = merged['hedge_ratio'].copy()
    for i in range(len(hedge_ratio_adj)):
        if not bool(merged['night_available'].iloc[i]):
            hedge_ratio_adj.iloc[i] = 0.0
            continue
        h = hedge_ratio_adj.iloc[i]
        if abs(h - prev_hedge) < WEIGHT_CHANGE_THRESHOLD:
            hedge_ratio_adj.iloc[i] = prev_hedge
        else:
            prev_hedge = h
    merged['hedge_ratio_adj'] = hedge_ratio_adj.where(merged['night_available'], 0.0)
    s2_trade_cost = merged['hedge_ratio_adj'].abs() * FUTURES_TX_COST_PCT

    # S2 return: stock return + futures hedge return - cost
    # When we short TX at night: if market drops, we gain from short
    # hedge_return = -hedge_ratio * night_return (negative of long)
    merged['s2_hedge_ret'] = np.where(
        merged['night_available'],
        -merged['hedge_ratio_adj'] * merged['night_ret'],
        0.0,
    )
    merged['s2_ret'] = merged['tw50_ret'] + merged['s2_hedge_ret'] - s2_trade_cost

    # === S3: VIX Spike Guard ===
    # Only hedge when VIX has jumped > +2 points
    # Difference between consecutive as-of night signals; both observations
    # were available before their respective night sessions.
    merged['vix_change'] = merged['vix_for_night'].ffill().diff()
    spike_mask = (merged['vix_change'] > 2.0) & merged['night_available']

    merged['s3_hedge_ret'] = np.where(
        spike_mask,
        -merged['night_ret'] * 0.5,  # Hedge 50% when spike detected
        0.0
    )
    s3_trade_cost = np.where(spike_mask, FUTURES_TX_COST_PCT * 0.5, 0.0)
    merged['s3_ret'] = merged['tw50_ret'] + merged['s3_hedge_ret'] - s3_trade_cost

    # === S4: Conditional Night Hedge (only when VIX > 20) ===
    # More selective: only hedge at night when VIX is elevated
    vix_elevated = (merged['vix_for_night'] > 20) & merged['night_available']
    s4_hedge_ratio = np.where(vix_elevated, merged['hedge_ratio_adj'], 0.0)
    merged['s4_hedge_ret'] = np.where(
        vix_elevated,
        -pd.Series(s4_hedge_ratio, index=merged.index) * merged['night_ret'],
        0.0
    )
    s4_trade_cost = pd.Series(s4_hedge_ratio, index=merged.index).abs() * FUTURES_TX_COST_PCT
    merged['s4_ret'] = merged['tw50_ret'] + merged['s4_hedge_ret'] - s4_trade_cost

    # === S5: Full VT = S1 day + S2 night ===
    # Day return scaled by VIX weight (like S1), plus night hedge
    # This is the "complete" implementation: reduce 0050.TW during day AND hedge at night
    merged['s5_ret'] = merged['s1_ret'] + merged['s2_hedge_ret'] - s2_trade_cost

    return merged


def compute_metrics(returns, name, rf=0.0):
    """Compute standard performance metrics."""
    returns = returns.dropna()
    n = len(returns)
    if n < 20:
        return {'name': name, 'n': n, 'error': 'insufficient data'}

    ann_factor = 252
    cum_ret = (1 + returns).cumprod()
    total_ret = cum_ret.iloc[-1] - 1
    years = n / ann_factor
    cagr = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0
    ann_vol = returns.std() * np.sqrt(ann_factor)
    sharpe = (returns.mean() - rf / ann_factor) / returns.std() * np.sqrt(ann_factor) if returns.std() > 0 else 0

    # Max drawdown
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    mdd = drawdown.min()

    # Calmar ratio
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = returns[returns < 0].std() * np.sqrt(ann_factor)
    sortino = (cagr - rf) / downside if downside > 0 else 0

    return {
        'name': name,
        'n': n,
        'cagr': round(cagr, 4),
        'ann_vol': round(ann_vol, 4),
        'sharpe': round(sharpe, 4),
        'mdd': round(mdd, 4),
        'calmar': round(calmar, 4),
        'sortino': round(sortino, 4),
        'total_return': round(total_ret, 4),
    }


def canonical_hac_lag(n, h=FORECAST_HORIZON):
    """Mirror the canonical DM bandwidth for transparent diagnostics."""
    return max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))


def serial_acf(values, max_lag=20):
    """Sample autocorrelation of a loss differential, lags 1..max_lag."""
    values = np.asarray(values, dtype=np.float64)
    centered = values - values.mean()
    denominator = float(np.mean(centered**2))
    if denominator <= 0.0:
        return {str(lag): None for lag in range(1, max_lag + 1)}
    return {
        str(lag): float(np.mean(centered[lag:] * centered[:-lag]) / denominator)
        for lag in range(1, min(max_lag, len(values) - 1) + 1)
    }


def newey_west_mean_t(values, max_lag):
    """Bartlett Newey-West mean t-stat for non-primary lag sensitivity."""
    values = np.asarray(values, dtype=np.float64)
    centered = values - values.mean()
    n = len(values)
    long_run_variance = float(np.mean(centered**2))
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        autocovariance = float(np.mean(centered[lag:] * centered[:-lag]))
        long_run_variance += 2.0 * weight * autocovariance
    if not np.isfinite(long_run_variance) or long_run_variance <= 0.0:
        return None
    return float(values.mean() / np.sqrt(long_run_variance / n))


def loss_dm_diagnostics(loss1, loss2, h=FORECAST_HORIZON):
    """Canonical DM on paired positive risk losses plus dependence diagnostics."""
    loss1 = np.asarray(loss1, dtype=np.float64).reshape(-1)
    loss2 = np.asarray(loss2, dtype=np.float64).reshape(-1)
    if loss1.shape != loss2.shape:
        raise ValueError('Paired DM loss arrays must have identical shapes')
    valid = np.isfinite(loss1) & np.isfinite(loss2)
    loss1 = loss1[valid]
    loss2 = loss2[valid]
    differential = loss1 - loss2
    n = len(differential)
    if n < 20:
        raise ValueError(f'Insufficient paired losses for DM inference: n={n}')

    hac_lag = canonical_hac_lag(n, h=h)
    t_stat, p_value = canonical_dm_test(loss1, loss2, h=h)
    sensitivity_lags = sorted(set((*HAC_LAG_SENSITIVITY, hac_lag)))
    harvey_significant = bool(abs(t_stat) > HARVEY_LIU_ZHU_THRESHOLD)
    return {
        't_stat': float(t_stat),
        'p_value': float(p_value),
        'asset': '0050.TW|TX',
        'n': int(n),
        'horizon': int(h),
        'hac_lag': int(hac_lag),
        'loss_function': 'daily squared strategy return (variance-risk proxy)',
        'mean_loss_differential': float(differential.mean()),
        'loss_differential_acf': serial_acf(differential, max_lag=20),
        'lag_sensitivity_t': {
            str(candidate_lag): newey_west_mean_t(differential, candidate_lag)
            for candidate_lag in sensitivity_lags
        },
        'significant_at_5pct': bool(p_value < 0.05),
        'harvey_significant': harvey_significant,
        'harvey_direction': (
            'strategy_1_higher_variance_risk_loss'
            if harvey_significant and t_stat > 0
            else 'strategy_1_lower_variance_risk_loss'
            if harvey_significant and t_stat < 0
            else 'no_harvey_screened_difference'
        ),
        'harvey_screen': 'Harvey, Liu, and Zhu (2016) |t| > 3 reporting screen',
        'sign_convention': (
            'loss = squared daily return; positive t means strategy 1 has '
            'higher variance-risk loss; this does not rank total utility'
        ),
    }


def risk_loss_dm_diagnostics(returns1, returns2, h=FORECAST_HORIZON):
    """Canonical DM on squared-return risk losses plus dependence diagnostics.

    This is a comparison of daily second moments, not a complete ranking of
    strategy utility or mean return. Positive t means strategy 1 has the larger
    mean squared daily return (higher variance-risk loss).
    """
    aligned = pd.concat(
        [pd.Series(returns1, name='returns1'), pd.Series(returns2, name='returns2')],
        axis=1,
    ).dropna()
    returns1_array = aligned['returns1'].to_numpy(dtype=np.float64)
    returns2_array = aligned['returns2'].to_numpy(dtype=np.float64)
    loss1 = returns1_array ** 2
    loss2 = returns2_array ** 2
    diagnostic = loss_dm_diagnostics(loss1, loss2, h=h)
    strategy_t, strategy_p = strategy_dm_test(
        returns1_array,
        returns2_array,
        h=h,
        loss_fn='variance_risk',
    )
    if not (
        np.isclose(strategy_t, diagnostic['t_stat'], atol=1e-15, rtol=0.0)
        and np.isclose(strategy_p, diagnostic['p_value'], atol=1e-15, rtol=0.0)
    ):
        raise RuntimeError('strategy_dm_test variance_risk diverged from saved pointwise losses')
    diagnostic['implementation'] = (
        "volpred.stats.model_evaluation.strategy_dm_test(loss_fn='variance_risk')"
    )
    return diagnostic, loss1, loss2


def dataframe_sha256(frame):
    """Hash a canonical CSV serialization of the frozen analysis inputs."""
    payload = frame.to_csv(index=True, date_format='%Y-%m-%d', lineterminator='\n')
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def sha256_file(path):
    """Return the SHA-256 digest of an on-disk artifact."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_save_npz(path, **arrays):
    """Atomically save and verify the pointwise strategy-return artifact."""
    temporary = path.with_name(f'.{path.name}.tmp')
    try:
        with temporary.open('wb') as handle:
            np.savez_compressed(handle, **arrays)
            handle.flush()
            os.fsync(handle.fileno())
        with np.load(temporary, allow_pickle=False) as verified:
            if set(verified.files) != set(arrays):
                raise RuntimeError('NPZ verification failed: key mismatch')
            for key, expected in arrays.items():
                if not np.array_equal(verified[key], expected, equal_nan=True):
                    raise RuntimeError(f'NPZ verification failed for {key}')
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write_json(path, payload):
    """Write results atomically and verify that the temporary JSON parses."""
    temporary = path.with_name(f'.{path.name}.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        with temporary.open(encoding='utf-8') as handle:
            json.load(handle)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_legacy_dm_evidence(expected_dates):
    """Verify and recompute every HAC-only cell from the pinned legacy losses."""
    if not LEGACY_DM_EVIDENCE_PATH.exists():
        raise RuntimeError(f'Missing legacy DM evidence: {LEGACY_DM_EVIDENCE_PATH}')
    artifact_hash = sha256_file(LEGACY_DM_EVIDENCE_PATH)
    if artifact_hash != EXPECTED_LEGACY_DM_EVIDENCE_SHA256:
        raise RuntimeError(
            'Legacy DM evidence changed: '
            f'expected {EXPECTED_LEGACY_DM_EVIDENCE_SHA256}, got {artifact_hash}'
        )

    pairs = (
        ('s2', 's1'), ('s2', 's0'), ('s3', 's0'), ('s3', 's1'),
        ('s4', 's0'), ('s4', 's1'), ('s5', 's1'),
    )
    expected_keys = {'date_ordinal'} | {
        f'{left}_vs_{right}_{suffix}'
        for left, right in pairs
        for suffix in ('loss1', 'loss2')
    }
    diagnostics = {}
    with np.load(LEGACY_DM_EVIDENCE_PATH, allow_pickle=False) as evidence:
        if set(evidence.files) != expected_keys:
            raise RuntimeError('Legacy DM evidence key set changed')
        expected_ordinals = pd.DatetimeIndex(expected_dates).to_numpy(
            dtype='datetime64[D]'
        ).astype(np.int64)
        if not np.array_equal(evidence['date_ordinal'], expected_ordinals):
            raise RuntimeError('Legacy DM evidence dates do not match the frozen final sample')
        for left, right in pairs:
            key = f'{left}_vs_{right}'
            diagnostics[key] = loss_dm_diagnostics(
                evidence[f'{key}_loss1'], evidence[f'{key}_loss2'], h=1
            )
            diagnostics[key]['ledger_exclude'] = True
    return diagnostics, artifact_hash


def analyze_covid_period(merged):
    """Analyze performance during COVID crash (2020-02 to 2020-04)."""
    covid_start = pd.Timestamp('2020-02-20')
    covid_end = pd.Timestamp('2020-04-30')
    covid = merged[(merged.index >= covid_start) & (merged.index <= covid_end)]

    if len(covid) < 5:
        return {'error': 'insufficient COVID period data'}

    results = {}
    for strat in ['s0', 's1', 's2', 's3', 's4', 's5']:
        ret_col = f'{strat}_ret'
        if ret_col in covid.columns:
            rets = covid[ret_col].dropna()
            cum = (1 + rets).cumprod()
            results[strat] = {
                'total_return': round(cum.iloc[-1] - 1, 4),
                'max_drawdown': round(((cum - cum.cummax()) / cum.cummax()).min(), 4),
                'worst_day': round(rets.min(), 4),
                'best_day': round(rets.max(), 4),
                'volatility': round(rets.std() * np.sqrt(252), 4),
                'n_days': len(rets),
            }

    # Night session hedge effectiveness during COVID
    covid_hedged = covid[covid['hedge_ratio_adj'] > 0.01]
    if len(covid_hedged) > 0:
        results['hedge_stats'] = {
            'days_hedged': len(covid_hedged),
            'avg_hedge_ratio': round(covid_hedged['hedge_ratio_adj'].mean(), 4),
            'avg_night_return': round(covid_hedged['night_ret'].mean(), 6),
            'avg_hedge_pnl': round(covid_hedged['s2_hedge_ret'].mean(), 6),
            'total_hedge_pnl': round(covid_hedged['s2_hedge_ret'].sum(), 4),
        }

    return results


def analyze_vix_regimes(merged):
    """Analyze performance by VIX regime."""
    regimes = {
        'low_vix': merged['vix_for_day'] < 15,
        'mid_vix': (merged['vix_for_day'] >= 15) & (merged['vix_for_day'] < 25),
        'high_vix': (merged['vix_for_day'] >= 25) & (merged['vix_for_day'] < 35),
        'extreme_vix': merged['vix_for_day'] >= 35,
    }

    results = {}
    for regime_name, mask in regimes.items():
        regime_data = merged[mask]
        if len(regime_data) < 10:
            continue
        results[regime_name] = {
            'n_days': len(regime_data),
            'avg_vix': round(regime_data['vix_for_day'].mean(), 2),
        }
        for strat in ['s0', 's1', 's2', 's3', 's4', 's5']:
            ret_col = f'{strat}_ret'
            if ret_col in regime_data.columns:
                rets = regime_data[ret_col].dropna()
                results[regime_name][f'{strat}_mean_ret'] = round(rets.mean() * 252, 4)
                results[regime_name][f'{strat}_vol'] = round(rets.std() * np.sqrt(252), 4)

    return results


def analyze_night_session_diagnostics(merged):
    """Summarise explicit session availability without filtering zero returns."""
    night_valid = merged.loc[merged['night_available']].copy()
    if night_valid.empty:
        return {'error': 'no available night sessions'}

    return {
        'sample_days': len(merged),
        'available_night_sessions': len(night_valid),
        'availability_pct': round(len(night_valid) / len(merged) * 100, 1),
        'legitimate_zero_return_sessions': int(night_valid['night_ret'].eq(0.0).sum()),
        'night_ret_mean': round(night_valid['night_ret'].mean(), 6),
        'night_ret_std': round(night_valid['night_ret'].std(), 6),
        'scope': (
            'Within-session TX returns only. No spot-futures basis or tracking-error '
            'claim is made because the legacy selected-contract series can switch expiry.'
        ),
    }


def main():
    print("=" * 70)
    print("K841: TAIFEX Night Session Stale-Daily-VIX Overlay Evaluation")
    print("=" * 70)

    # Step 1: Load TX data
    tx_df = load_tx_data_parallel(start_date=NIGHT_SESSION_START, n_workers=8)

    # Step 2: Load VIX and 0050.TW
    (
        vix,
        tw50_close,
        tw50_ret,
        tw50_gap_ret,
        tw50_intraday_ret,
        yfinance_snapshot_hash,
    ) = load_vix_and_0050()

    # Step 3: Compute strategies
    merged = compute_strategies(
        tx_df,
        vix,
        tw50_close,
        tw50_ret,
        tw50_gap_ret,
        tw50_intraday_ret,
    )
    if merged.index.duplicated().any() or not merged.index.is_monotonic_increasing:
        raise RuntimeError('Frozen K841 dates must be unique and increasing')
    if len(merged) != 2157 or merged.index[-1] != pd.Timestamp('2026-04-02'):
        raise RuntimeError(
            'Frozen K841 sample changed: expected n=2157 ending 2026-04-02, '
            f'got n={len(merged)} ending {merged.index[-1].date()}'
        )
    analysis_input_columns = [
        'night_open', 'night_close', 'night_high', 'night_low', 'night_volume',
        'night_session_status', 'night_start_date', 'night_continuation_date',
        'day_open', 'day_close', 'day_volume', 'night_ticks',
        'vix_for_day', 'vix_for_night', 'tw50_close', 'tw50_ret',
        'tw50_gap_ret', 'tw50_intraday_ret',
    ]
    analysis_slice_hash = dataframe_sha256(merged[analysis_input_columns])
    print(f'Frozen analysis slice sha256: {analysis_slice_hash}')
    if analysis_slice_hash != EXPECTED_ANALYSIS_SLICE_SHA256:
        raise RuntimeError(
            'Frozen K841 analysis inputs changed: '
            f'expected {EXPECTED_ANALYSIS_SLICE_SHA256}, got {analysis_slice_hash}'
        )

    # Step 4: Compute metrics
    print("\n" + "=" * 70)
    print("FULL PERIOD PERFORMANCE")
    print("=" * 70)

    metrics = {}
    for strat, name in [('s0', 'S0: BH 0050.TW'),
                         ('s1', 'S1: 8.63/VIX Next-Day'),
                         ('s2', 'S2: Night Hedge (always)'),
                         ('s3', 'S3: VIX Spike Guard'),
                         ('s4', 'S4: Night Hedge (VIX>20 only)'),
                         ('s5', 'S5: Full VT (day+night)')]:
        m = compute_metrics(merged[f'{strat}_ret'], name)
        metrics[strat] = m
        print(f"\n{name}:")
        for k, v in m.items():
            if k != 'name':
                print(f"  {k}: {v}")

    # Step 5: DM tests
    print("\n" + "=" * 70)
    print("DM TESTS (squared return loss)")
    print("=" * 70)

    # Squared daily return is a variance-risk proxy. It does not rank total
    # strategy utility because it ignores the mean return.
    dm_results = {}
    dm_loss_streams = {}
    primary_overlay_pairs = {'s2_vs_s0', 's3_vs_s0', 's4_vs_s0', 's5_vs_s1'}
    for pair in [('s2', 's1'), ('s2', 's0'), ('s3', 's0'), ('s3', 's1'),
                  ('s4', 's0'), ('s4', 's1'), ('s5', 's1')]:
        key = f'{pair[0]}_vs_{pair[1]}'
        diagnostic, loss1, loss2 = risk_loss_dm_diagnostics(
            merged[f'{pair[0]}_ret'], merged[f'{pair[1]}_ret']
        )
        diagnostic['comparison_role'] = (
            'primary_same_base_overlay_ablation'
            if key in primary_overlay_pairs
            else 'cross_exposure_diagnostic_only'
        )
        dm_results[key] = diagnostic
        dm_loss_streams[f'{key}_loss1'] = loss1
        dm_loss_streams[f'{key}_loss2'] = loss2
        sig = (
            '***' if diagnostic['harvey_significant']
            else ('**' if diagnostic['significant_at_5pct'] else '')
        )
        print(
            f"  {pair[0].upper()} vs {pair[1].upper()}: "
            f"t={diagnostic['t_stat']:.4f}, p={diagnostic['p_value']:.4g}, "
            f"HAC lag={diagnostic['hac_lag']} {sig}"
        )

    legacy_dm_results, legacy_dm_artifact_sha256 = load_legacy_dm_evidence(
        merged.index
    )

    # Step 6: COVID analysis
    print("\n" + "=" * 70)
    print("COVID CRASH ANALYSIS (2020-02 to 2020-04)")
    print("=" * 70)
    covid_results = analyze_covid_period(merged)
    for k, v in covid_results.items():
        print(f"\n  {k}:")
        if isinstance(v, dict):
            for kk, vv in v.items():
                print(f"    {kk}: {vv}")

    # Step 7: VIX regime analysis
    print("\n" + "=" * 70)
    print("VIX REGIME ANALYSIS")
    print("=" * 70)
    regime_results = analyze_vix_regimes(merged)
    for regime, data in regime_results.items():
        print(f"\n  {regime}:")
        for k, v in data.items():
            print(f"    {k}: {v}")

    # Step 8: Night-session data diagnostics
    print("\n" + "=" * 70)
    print("NIGHT-SESSION DATA DIAGNOSTICS")
    print("=" * 70)
    night_session_results = analyze_night_session_diagnostics(merged)
    for k, v in night_session_results.items():
        print(f"  {k}: {v}")

    # Step 9: Trading statistics
    print("\n" + "=" * 70)
    print("TRADING STATISTICS")
    print("=" * 70)

    # S2 hedging stats
    hedged_days = merged[merged['hedge_ratio_adj'] > 0.01]
    print(f"  S2 total days: {len(merged)}")
    print(f"  S2 hedged days: {len(hedged_days)} ({len(hedged_days)/len(merged)*100:.1f}%)")
    print(f"  S2 avg hedge ratio (when active): {hedged_days['hedge_ratio_adj'].mean():.4f}" if len(hedged_days) > 0 else "  No hedged days")
    print(f"  S2 avg night return (when hedged): {hedged_days['night_ret'].mean():.6f}" if len(hedged_days) > 0 else "")

    # S3 spike stats
    spike_days = merged[(merged['vix_change'] > 2.0) & merged['night_available']]
    print(f"\n  S3 spike trigger days: {len(spike_days)} ({len(spike_days)/len(merged)*100:.1f}%)")
    if len(spike_days) > 0:
        print(f"  S3 avg VIX change on spike: {spike_days['vix_change'].mean():.2f}")
        print(f"  S3 avg night return on spike: {spike_days['night_ret'].mean():.6f}")

    # Night session coverage
    has_night = merged[merged['night_ticks'].notna() & (merged['night_ticks'] > 0)]
    print(f"\n  Days with night session data: {len(has_night)} ({len(has_night)/len(merged)*100:.1f}%)")

    # Step 10: Save pointwise evidence and results
    evidence_arrays = {
        'date_ordinal': merged.index.to_numpy(dtype='datetime64[D]').astype(np.int64),
        **{
            f'{strategy}_return': merged[f'{strategy}_ret'].to_numpy(dtype=np.float64)
            for strategy in ['s0', 's1', 's2', 's3', 's4', 's5']
        },
        **dm_loss_streams,
    }
    return_artifact_path = SCRIPT_DIR / 'k841_strategy_returns.npz'
    return_artifact_sha256 = atomic_save_npz(return_artifact_path, **evidence_arrays)

    pre_repair_t = {
        's2_vs_s1': 10.8213,
        's2_vs_s0': -7.1306,
        's3_vs_s0': -1.9712,
        's3_vs_s1': 14.0087,
        's4_vs_s0': -4.4320,
        's4_vs_s1': 12.1384,
        's5_vs_s1': -0.7583,
    }
    classification_changes = {
        key: bool((abs(pre_repair_t[key]) > HARVEY_LIU_ZHU_THRESHOLD)
                  != value['harvey_significant'])
        for key, value in dm_results.items()
    }

    results = {
        'experiment_id': 'K841',
        'title': 'Corrected TAIFEX Night Session VIX-Timed Hedge Evaluation',
        'run_at_utc': datetime.now(timezone.utc).isoformat(),
        'methodology_type': 'empirical strategy-risk comparison',
        'data_source': 'TAIFEX TX tick data + frozen yfinance snapshot (VIX, 0050.TW)',
        'data_source_details': {
            'taifex_contract_rule': 'TX all-contract tick files; choose the highest-volume expiry within each file',
            'taifex_contract_rule_scope': (
                'Legacy ex-post continuous-contract construction, not a canonical or '
                'ex-ante executable roll rule; full-file volume includes the '
                'following day session and roll-date sensitivity is not supplied.'
            ),
            'taifex_directory': TAIFEX_DIR,
            'taifex_files_considered': int(len(tx_df)),
            'yfinance_tickers': ['^VIX', '0050.TW'],
            'yfinance_end_exclusive': YFINANCE_END_EXCLUSIVE,
            'yfinance_snapshot': str(YFINANCE_SNAPSHOT_PATH.relative_to(SCRIPT_DIR)),
            'yfinance_snapshot_sha256': yfinance_snapshot_hash,
            'expected_yfinance_snapshot_sha256': EXPECTED_YFINANCE_SNAPSHOT_SHA256,
            'frozen_analysis_slice_sha256': analysis_slice_hash,
            'expected_analysis_slice_sha256': EXPECTED_ANALYSIS_SLICE_SHA256,
            'strategy_return_artifact': return_artifact_path.name,
            'strategy_return_artifact_sha256': return_artifact_sha256,
            'legacy_dm_evidence_artifact': LEGACY_DM_EVIDENCE_PATH.name,
            'legacy_dm_evidence_sha256': legacy_dm_artifact_sha256,
            'expected_legacy_dm_evidence_sha256': EXPECTED_LEGACY_DM_EVIDENCE_SHA256,
            'legacy_source_commit': LEGACY_SOURCE_COMMIT,
        },
        'data_period': f"{merged.index[0].date()} to {merged.index[-1].date()}",
        'n_trading_days': len(merged),
        'strategies': {
            'S0': 'Buy & Hold 0050.TW',
            'S1': '8.63/VIX rebalance at Taiwan open; prior weight remains on overnight gap',
            'S2': 'Buy & Hold 0050.TW + TX night session hedge (always)',
            'S3': 'VIX spike guard (hedge when VIX > +2)',
            'S4': 'Conditional night hedge (VIX > 20 only)',
            'S5': 'Full VT: S1 day scaling + S2 night hedge',
        },
        'metrics': metrics,
        'dm_tests': dm_results,
        'covid_analysis': covid_results,
        'vix_regime_analysis': regime_results,
        'night_session_diagnostics': night_session_results,
        'trading_stats': {
            's2_hedged_days': len(hedged_days),
            's2_hedged_pct': round(len(hedged_days) / len(merged) * 100, 1),
            's2_avg_hedge_ratio': round(hedged_days['hedge_ratio_adj'].mean(), 4) if len(hedged_days) > 0 else None,
            's3_spike_days': len(spike_days),
            's3_spike_pct': round(len(spike_days) / len(merged) * 100, 1),
            'night_session_coverage': round(len(has_night) / len(merged) * 100, 1),
            'night_session_unavailable_days': int((~merged['night_available']).sum()),
            'night_session_unavailable_dates': [
                str(value.date()) for value in merged.index[~merged['night_available']]
            ],
            'unavailable_night_policy': (
                'No overlay position, PnL, or cost; stock leg remains invested. '
                'Unavailable sessions are explicit and never imputed as a zero night return.'
            ),
        },
        'parameters': {
            'vix_anchor': VIX_ANCHOR,
            'futures_tx_cost': FUTURES_TX_COST_PCT,
            'weight_change_threshold': WEIGHT_CHANGE_THRESHOLD,
            'night_session_start_date': str(NIGHT_SESSION_START),
            'analysis_end': str(ANALYSIS_END),
            'dm_horizon': FORECAST_HORIZON,
            'harvey_liu_zhu_threshold': HARVEY_LIU_ZHU_THRESHOLD,
        },
        'methodology_repair': {
            'supersedes_pre_2026_07_15_k841_dm_inference': True,
            'pre_repair_defects': [
                (
                    'The local DM helper iterated range(h); at h=1 it used only '
                    'gamma[0] and therefore reported iid rather than HAC inference.'
                ),
                (
                    'S1 applied a weight first known at the Taiwan open to the '
                    'same date close-to-close return, including the already-realized gap.'
                ),
                (
                    'Night overlays paid cost only when the ratio changed even though '
                    'each observation closes at 05:00 and reopens at 15:00; S5 also '
                    'omitted the S1 stock rebalance cost.'
                ),
                (
                    'The first/last-date session shortcut dropped Saturday-AM '
                    'continuations stored in Monday TAIFEX files.'
                ),
            ],
            'primary_dm_implementation': (
                "volpred.stats.model_evaluation.strategy_dm_test(loss_fn='variance_risk')"
            ),
            'legacy_loss_dm_implementation': 'volpred.stats.model_evaluation.dm_test',
            'primary_bandwidth_rule': 'max(1, min(ceil(h^(1/3) * n^(1/3)), n//4))',
            'pre_repair_t_statistics': pre_repair_t,
            'hac_only_repair_on_legacy_return_streams': legacy_dm_results,
            'hac_only_harvey_classification_changed': {
                key: bool((abs(pre_repair_t[key]) > HARVEY_LIU_ZHU_THRESHOLD)
                          != legacy_dm_results[key]['harvey_significant'])
                for key in pre_repair_t
            },
            'final_harvey_classification_changed_after_all_repairs': classification_changes,
            'any_final_harvey_classification_changed_after_all_repairs': bool(
                any(classification_changes.values())
            ),
            'comparison_scope': (
                'The sample endpoint is frozen at 2026-04-02. The hac-only table '
                'isolates inference on the legacy return streams; final corrected '
                'statistics also repair the return window and transaction costs, '
                'so final-versus-old differences cannot be attributed to HAC alone.'
            ),
        },
        'references': [
            {
                'authors': 'Diebold, F.X.; Mariano, R.S.',
                'year': 1995,
                'title': 'Comparing Predictive Accuracy',
                'journal': 'Journal of Business & Economic Statistics 13(3), 253-263',
                'doi': '10.1080/07350015.1995.10524599',
            },
            {
                'authors': 'Newey, W.K.; West, K.D.',
                'year': 1987,
                'title': 'A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix',
                'journal': 'Econometrica 55(3), 703-708',
                'doi': '10.2307/1913610',
            },
            {
                'authors': 'Harvey, D.; Leybourne, S.; Newbold, P.',
                'year': 1997,
                'title': 'Testing the equality of prediction mean squared errors',
                'journal': 'International Journal of Forecasting 13(2), 281-291',
                'doi': '10.1016/S0169-2070(96)00719-4',
            },
            {
                'authors': 'Harvey, C.R.; Liu, Y.; Zhu, H.',
                'year': 2016,
                'title': '... and the Cross-Section of Expected Returns',
                'journal': 'Review of Financial Studies 29(1), 5-68',
                'doi': '10.1093/rfs/hhv059',
            },
        ],
        'conclusions': {},
    }

    # Determine conclusions from the current result objects; do not hard-code
    # classifications before the repaired run exists.
    primary_keys = ['s2_vs_s0', 's3_vs_s0', 's4_vs_s0', 's5_vs_s1']
    primary_risk_loss = {
        key: {
            't_stat': dm_results[key]['t_stat'],
            'harvey_significant': dm_results[key]['harvey_significant'],
            'direction': dm_results[key]['harvey_direction'],
            'ledger_exclude': True,
        }
        for key in primary_keys
    }
    final_reversal_keys = [
        key for key, changed in classification_changes.items() if changed
    ]
    conclusions = {
        'verdict': 'CORRECTED_DESCRIPTIVE_STRATEGY_RISK_COMPARISON',
        'hac_only_repair_verdict': 'NO_HARVEY_CLASSIFICATION_REVERSAL',
        'final_reversal_keys_after_timing_cost_and_session_repairs': final_reversal_keys,
        'primary_same_base_risk_loss_comparisons': primary_risk_loss,
        'cross_exposure_diagnostics': {
            key: {
                't_stat': dm_results[key]['t_stat'],
                'harvey_significant': dm_results[key]['harvey_significant'],
                'direction': dm_results[key]['harvey_direction'],
                'ledger_exclude': True,
            }
            for key in ['s2_vs_s1', 's3_vs_s1', 's4_vs_s1']
        },
        'main_finding': (
            'Correcting the h=1 iid DM defect to canonical lag-13 Bartlett HAC '
            'changes every legacy t-statistic but none of the seven legacy '
            '|t|>3 classifications. Final statistics additionally repair the '
            'Taiwan-open return window, nightly round-trip costs, and weekend '
            'session parsing; their directions are generated from dm_results '
            'above. Only same-base comparisons are claim-bearing. Squared-return '
            'risk loss alone does not establish total strategy improvement.'
        ),
        'sharpe_ranking': {k: metrics[k]['sharpe'] for k in ['s0', 's1', 's2', 's3', 's4', 's5']},
        'raw_mdd_diagnostics': {
            'values': {k: metrics[k]['mdd'] for k in ['s0', 's1', 's2', 's3', 's4', 's5']},
            'claim_status': 'descriptive_only_not_exposure_matched',
            'reason': (
                'Realized volatility differs by more than 20% across several '
                'strategies; raw MDD cannot establish timing or hedge skill.'
            ),
        },
        'covid_raw_mdd_diagnostics': {
            'values': {k: covid_results.get(k, {}).get('max_drawdown') for k in ['s0', 's1', 's2', 's5']},
            'claim_status': 'descriptive_only_not_exposure_matched_or_randomization_tested',
        },
        'timing_issue': (
            'Night session starts at 15:00 Taiwan time, before US market opens. '
            'The signal is the last VIX close strictly before each actual night start. '
            'This is at least one US session stale by construction, and can be older '
            'around holidays. The experiment therefore tests a stale daily-VIX overlay, not a '
            'true intraday-VIX hedge.'
        ),
        'scope_limit': (
            'Squared-return DM measures a variance-risk proxy and does not rank '
            'mean return, Sharpe, utility, or causal hedge effectiveness. The '
            'highest-full-file-volume expiry is an ex-post continuous-contract '
            'convention, not a deployable roll rule.'
        ),
        'execution_approximation': (
            'The thresholded S1 stock/cash weight is carried unchanged between '
            'rebalance dates; natural self-financing weight drift is not modelled. '
            'Reported costs and returns therefore remain a transparent allocation '
            'approximation rather than exact portfolio accounting.'
        ),
    }
    results['conclusions'] = conclusions

    print("\n" + "=" * 70)
    print("CONCLUSIONS")
    print("=" * 70)
    for k, v in conclusions.items():
        print(f"  {k}: {v}")

    output_path = SCRIPT_DIR / 'k841_futures_realtime_vt_results.json'
    atomic_write_json(output_path, results)
    print(f"\nResults saved to {output_path}")

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--refresh-yfinance-snapshot',
        action='store_true',
        help='replace the frozen VIX/0050 input snapshot, then exit',
    )
    args = parser.parse_args()
    if args.refresh_yfinance_snapshot:
        refresh_yfinance_snapshot()
    else:
        results = main()
