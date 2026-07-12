"""K1684 R2 — gap-complete, active-contract, ETF-close-anchored 5-min RV for TAIFEX TX.

Why this module exists (Codex R1 blocker #2)
--------------------------------------------
K854 built the realized measure from `Daily_*TX1.csv` (a single pre-filtered contract
series) and summed the squared 5-min returns of THREE SEPARATE sessions:

    RV_K854(D) = RV(night PM 15:00-24:00) + RV(night AM 00:00-05:00) + RV(day 08:45-13:45)

Three things are wrong with that for a close-to-close VaR application:

 1. Every SESSION-BOUNDARY jump is dropped: 13:45 -> 15:00 (the 75-minute pause between
    the day close and the evening open), 05:00 -> 08:45 (the 3h45m pause before the day
    open), and the PM -> AM midnight seam. A close-to-close variance has to contain them.
 2. `TX1` is one contract file. The preamble rule is: pick, for EACH trade date, the
    contract with the largest traded volume across ALL TX contracts.
 3. The day session runs to 13:45 but the ETF (0050.TW) closes at 13:30. RV(D) therefore
    carried 15 minutes of information from AFTER the start of the return window it is used
    to forecast -- an information-set overlap.

This module fixes all three:

    RV(D) = sum of squared 5-min log returns along ONE CONTINUOUS PRICE PATH running
            13:30(D-1) -> 13:30(D)

exactly the window of 0050's close-to-close return r_D, with every boundary jump entering
as a single 5-min-bar-to-bar return. The whole path is taken from ONE contract -- the
active contract of trade date D -- so a rollover never injects a basis jump into the path.
Because the path ENDS at 13:30(D), RV(D) is fully known at 0050's close on day D, i.e. at
the exact instant r_{D+1}'s window opens. The 13:30/13:45 overlap is sealed by construction.

TAIFEX trade-date convention (verified in-script, not assumed): the file for trade date D
holds the after-hours session stamped on calendar day D-1 (15:00-24:00), the early-morning
session on calendar D (00:00-05:00), and the day session on calendar D (08:45-13:45).
The `時間戳記` column carries the true calendar datetime, so no convention has to be guessed.

Raw columns (big5): 成交日期, 商品代號, 到期月份(週別), 成交時間, 成交價格,
                    成交數量(B+S), 近月價格, 遠月價格, 開盤集合競價, 時間戳記
"""

import os
import glob
import numpy as np
import pandas as pd

TICK_DIR = "/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python"

ETF_CLOSE_HHMMSS = 133000        # 0050.TW / TWSE close -- the anchor of every window
DAY_SESSION_END = 134500         # TAIFEX day session close
DAY_SESSION_START = 84500
NIGHT_PM_START = 150000
NIGHT_AM_END = 50000
BAR_SECONDS = 300                # 5-minute bars

# Contracts kept for the cross-file stitch. The next trade date's active contract has to be
# retrievable from THIS file's post-close tail, so more than the front month must be kept.
TAIL_MIN_VOLUME_SHARE = 0.0005
TAIL_MAX_CONTRACTS = 6


def _bars_from_ticks(ts_epoch, price):
    """Last trade in each 5-minute bucket. Bucket key = floor(epoch / 300)."""
    if len(ts_epoch) == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)
    order = np.argsort(ts_epoch, kind='stable')
    ts_epoch, price = ts_epoch[order], price[order]
    bucket = ts_epoch // BAR_SECONDS
    # last observation within each bucket (arrays are sorted, so the last index wins)
    last_pos = np.flatnonzero(np.r_[bucket[1:] != bucket[:-1], True])
    return ts_epoch[last_pos], price[last_pos]


def process_file(filepath):
    """One trade-date file -> the active contract's bars + every contract's post-close tail.

    Returns None when the file is unusable. The caller stitches consecutive dates.
    """
    base = os.path.basename(filepath)
    try:
        parts = base.replace('Daily_', '').replace('TX.csv', '').split('_')
        trade_date = f'{parts[0]}-{parts[1]}-{parts[2]}'
    except Exception:
        return None
    if os.path.getsize(filepath) < 200:
        return None

    try:
        df = pd.read_csv(filepath, encoding='big5', dtype=str, low_memory=False)
    except Exception:
        try:
            df = pd.read_csv(filepath, encoding='cp950', dtype=str, low_memory=False)
        except Exception:
            return None
    if len(df) < 20 or df.shape[1] < 10:
        return None

    delivery = df.iloc[:, 2].astype(str).str.strip()
    time_int = pd.to_numeric(df.iloc[:, 3], errors='coerce')
    price = pd.to_numeric(df.iloc[:, 4], errors='coerce')
    volume = pd.to_numeric(df.iloc[:, 5], errors='coerce').fillna(0.0)
    ts = pd.to_datetime(df.iloc[:, 9], errors='coerce')

    ok = price.notna() & time_int.notna() & ts.notna() & (price > 0)
    # Calendar-spread legs ("202403/202406") are a different instrument: drop them.
    ok &= ~delivery.str.contains('/', regex=False)
    if ok.sum() < 20:
        return None

    delivery, time_int = delivery[ok].values, time_int[ok].astype(int).values
    price, volume = price[ok].values, volume[ok].values
    ts_epoch = (ts[ok].values.astype('datetime64[s]').astype(np.int64))

    # The RV(D) window CLOSES at 13:30 on D. Anything that decides what RV(D) is -- including
    # WHICH contract it is measured on -- may therefore only use information available by then.
    # Ranking contracts on the whole file's volume would peek at the 13:30-13:45 post-close
    # trades (and R1's blocker list is exactly about that 15-minute sliver), so the active
    # contract is chosen on the volume traded INSIDE the window.
    in_window = ((time_int >= NIGHT_PM_START)                                    # evening, cal. D-1
                 | (time_int <= NIGHT_AM_END)                                    # early a.m., cal. D
                 | ((time_int >= DAY_SESSION_START) & (time_int <= ETF_CLOSE_HHMMSS)))  # day, cal. D
    if in_window.sum() < 20:
        return None
    vol_win = pd.Series(volume[in_window]).groupby(delivery[in_window]).sum().sort_values(
        ascending=False)
    total_win = float(vol_win.sum())
    if total_win <= 0:
        return None
    active = str(vol_win.index[0])

    # diagnostic: would ranking on the FULL day (incl. the post-close sliver) have chosen
    # a different contract? If this is never non-zero the restriction costs nothing.
    vol_full = pd.Series(volume).groupby(delivery).sum().sort_values(ascending=False)
    active_full_day = str(vol_full.index[0])

    # (1) the active contract's path inside the window (day session truncated at 13:30)
    keep_main = (delivery == active) & in_window
    bt, bp = _bars_from_ticks(ts_epoch[keep_main], price[keep_main])

    # (2) EVERY liquid contract's closing anchor + post-close tail. The NEXT trade date's window
    #     opens at TODAY's 13:30 and its active contract may already be a different month
    #     (rollover), so this has to be stored per contract, not only for today's active one.
    #
    #     Anchor rule (symmetric with the way the main path ENDS): the last trade at or before
    #     13:30:00. Using a bucketed bar here instead would leave the window's left edge a few
    #     seconds earlier than the previous window's right edge and double-count the sliver
    #     between them.
    tails = {}
    kept = [c for c in vol_full.index[:TAIL_MAX_CONTRACTS]
            if vol_full[c] / float(vol_full.sum()) >= TAIL_MIN_VOLUME_SHARE]
    for c in kept:
        day_c = (delivery == c) & (time_int >= DAY_SESSION_START) & (time_int <= DAY_SESSION_END)
        pre = day_c & (time_int <= ETF_CLOSE_HHMMSS)
        post = day_c & (time_int > ETF_CLOSE_HHMMSS)
        if pre.sum() < 1:
            continue
        pre_ts, pre_px = ts_epoch[pre], price[pre]
        last = int(np.argmax(pre_ts))                     # last trade at or before 13:30:00
        t_tail, p_tail = _bars_from_ticks(ts_epoch[post], price[post])
        tails[str(c)] = {
            'anchor_ts': int(pre_ts[last]),
            'anchor_price': float(pre_px[last]),
            'tail_ts': t_tail.tolist(),
            'tail_price': p_tail.tolist(),
        }

    return {
        'trade_date': trade_date,
        'active_contract': active,
        'active_contract_full_day_volume': active_full_day,
        'active_choice_differs_from_full_day': bool(active != active_full_day),
        'active_volume_share': float(vol_win.iloc[0] / total_win),
        'total_volume_in_window': total_win,
        'n_contracts': int(len(vol_win)),
        'bar_ts': bt.tolist(),
        'bar_price': bp.tolist(),
        'tails': tails,
    }


def _rv_from_path(ts_arr, p_arr):
    """Sum of squared 5-min log returns along one continuous path."""
    if len(p_arr) < 2:
        return np.nan, 0
    lp = np.log(np.asarray(p_arr, dtype=float))
    d = np.diff(lp)
    return float(np.sum(d ** 2)), int(len(d))


def stitch(records):
    """Turn per-file records into the ETF-close-anchored RV series.

    RV(D) spans 13:30(D-1) -> 13:30(D), entirely on trade date D's active contract.
    """
    records = [r for r in records if r is not None]
    records.sort(key=lambda x: x['trade_date'])
    rows = []
    for k in range(1, len(records)):
        cur, prev = records[k], records[k - 1]
        c = cur['active_contract']
        bar_ts = np.asarray(cur['bar_ts'], dtype=np.int64)
        bar_p = np.asarray(cur['bar_price'], dtype=float)
        if len(bar_ts) < 10:
            continue

        tail = prev['tails'].get(c)
        if tail is None:
            # the active contract did not trade in the previous day's closing window:
            # the path cannot be closed back to 13:30(D-1). Declare, do not fudge.
            rows.append({'date': cur['trade_date'], 'rv_c2c': np.nan,
                         'active_contract': c, 'anchor_complete': False})
            continue

        pre_ts = np.asarray([tail['anchor_ts']] + list(tail['tail_ts']), dtype=np.int64)
        pre_p = np.asarray([tail['anchor_price']] + list(tail['tail_price']), dtype=float)

        ts_path = np.concatenate([pre_ts, bar_ts])
        p_path = np.concatenate([pre_p, bar_p])
        order = np.argsort(ts_path, kind='stable')
        ts_path, p_path = ts_path[order], p_path[order]

        rv, n_ret = _rv_from_path(ts_path, p_path)

        # component decomposition (diagnostics only -- the headline RV is the path sum)
        dt = pd.to_datetime(ts_path, unit='s')
        hhmmss = (dt.hour * 10000 + dt.minute * 100 + dt.second).values
        lp = np.log(p_path)
        d2 = np.diff(lp) ** 2
        h0, h1 = hhmmss[:-1], hhmmss[1:]
        post_close = (h0 >= ETF_CLOSE_HHMMSS) & (h1 <= DAY_SESSION_END) & (h1 > ETF_CLOSE_HHMMSS)
        gap_pause = (h0 <= DAY_SESSION_END) & (h0 >= DAY_SESSION_START) & (h1 >= NIGHT_PM_START)
        night = ((h0 >= NIGHT_PM_START) | (h0 <= NIGHT_AM_END)) & \
                ((h1 >= NIGHT_PM_START) | (h1 <= NIGHT_AM_END))
        gap_open = ((h0 <= NIGHT_AM_END) | (h0 >= NIGHT_PM_START)) & (h1 >= DAY_SESSION_START) \
            & (h1 <= DAY_SESSION_END)
        day = (h0 >= DAY_SESSION_START) & (h0 <= ETF_CLOSE_HHMMSS) & \
              (h1 >= DAY_SESSION_START) & (h1 <= ETF_CLOSE_HHMMSS)

        rows.append({
            'date': cur['trade_date'],
            'rv_c2c': rv,
            'n_returns': n_ret,
            # information-set audit: the path must END at 13:30 of the trade date and START at
            # 13:30 of the previous trade date. Anything later than 13:30 at the end would mean
            # RV(D) contains ticks the ETF close cannot see -- the exact overlap R1 was blocked on.
            'path_start_ts': str(dt[0]),
            'path_end_ts': str(dt[-1]),
            'path_start_hhmmss': int(hhmmss[0]),
            'path_end_hhmmss': int(hhmmss[-1]),
            'active_contract': c,
            'active_volume_share': cur['active_volume_share'],
            'active_choice_differs_from_full_day': cur['active_choice_differs_from_full_day'],
            'rolled': bool(c != prev['active_contract']),
            'anchor_complete': True,
            'rv_post_close_1330_1345': float(np.sum(d2[post_close])),
            'rv_gap_1345_to_1500': float(np.sum(d2[gap_pause])),
            'rv_night': float(np.sum(d2[night])),
            'rv_gap_0500_to_0845': float(np.sum(d2[gap_open])),
            'rv_day_0845_1330': float(np.sum(d2[day])),
        })

    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date').sort_index()


def build(start_date='2016-12-01', end_date='2026-01-01', workers=None, verbose=True):
    from concurrent.futures import ProcessPoolExecutor
    files = sorted(glob.glob(os.path.join(TICK_DIR, 'Daily_*TX.csv')))
    lo = f"Daily_{start_date.replace('-', '_')}"
    hi = f"Daily_{end_date.replace('-', '_')}"
    files = [f for f in files if lo <= os.path.basename(f) < hi]
    if verbose:
        print(f'  {len(files)} all-contract TX tick files in [{start_date}, {end_date})',
              flush=True)
    workers = workers or max(1, (os.cpu_count() or 4) - 1)
    out = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, rec in enumerate(ex.map(process_file, files, chunksize=8)):
            out.append(rec)
            if verbose and (i + 1) % 250 == 0:
                print(f'    {i + 1}/{len(files)}', flush=True)
    return stitch(out)
