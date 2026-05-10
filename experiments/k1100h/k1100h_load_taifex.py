"""
K1100h — TAIFEX tick-level loader / 5-min & 15-min bar builder
==============================================================

Purpose
-------
Read 2017-2021 TAIFEX TX1 tick CSV files (Big5 encoded), build:
  1) 5-min bars (last-tick per bin) with day/night session tags
  2) 15-min bars (re-aggregated from 5-min)
  3) Daily intraday-derived features (for K1100h Phase 1 daily PRG with
     tick-derived exog):
       - rv_5min       : sum_{k} r_{t,k}^2  (Andersen-Bollerslev 1998 RV)
       - rv_parkinson  : (1 / 4 ln 2) * (ln(H/L))^2  (Parkinson 1980)
       - intraday_mom  : (close - open) / open in day session
       - hod_rv_ratio  : first-half-day RV / full-day RV (early-information ratio)
       - rv_lag1       : RV[t-1]  (HAR-style lag-1 — explicitly shifted)
       - bipower_var   : Barndorff-Nielsen & Shephard (2004) bipower variation
                         (jump-robust)

Lookahead discipline
--------------------
- ALL features here are pure aggregates of tick t — none use t+1 ticks
- Daily features at date t are computed from session t's intraday ticks only
- DO NOT pre-shift features here. The PRG kernel in `k1100h.py` reads
  `exog_mat[t - 1, :]` internally (always lag-1; equivalent to K1100g_d5's
  `exog_contemp=False` mode). Pre-shifting in this loader would compound
  to lag-2 and BREAK comparability with K1100g_d5.
- This loader's role: faithful tick → bar → daily-feature aggregation.

Scope
-----
- Source: ~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_YYYY_MM_DDTX1.csv
- Period: 2017-05-16 (stable schema) -> 2021-12-31 (matches K1100g cache)
- Day session: 08:45 - 13:45 (300 min = 60 x 5-min bars)
- Night session: 15:00 - 05:00 next day (filed under file_date = day-session date)
- Drops 集合競價 ticks (開盤集合競價=='*') — they are non-tradable boundary
- Cache: data/_taifex_5min_2017-2021.parquet ; data/_taifex_daily_features.parquet

Author: Claude (K1100h Phase 1)
Date: 2026-05-09
Seed: 42
"""
from __future__ import annotations

import re
import time
import warnings
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

TAIFEX_DIR = Path.home() / "Dropbox/TAIFEXDATA/TAIFEXDATA/python"

CACHE_5MIN = DATA_DIR / "_taifex_5min_2017-2021.parquet"
CACHE_DAILY = DATA_DIR / "_taifex_daily_features_2017-2021.parquet"

START_YEAR = 2017
END_YEAR = 2021

DAY_OPEN = pd.Timedelta("08:45:00")
DAY_CLOSE = pd.Timedelta("13:45:00")
NIGHT_OPEN = pd.Timedelta("15:00:00")
# Night close is 05:00 of NEXT calendar day → handled by timestamp bucketing


# ----------------------------------------------------------------------
# 1. Single-file loader
# ----------------------------------------------------------------------
COLS_RAW = [
    "trade_date",   # 成交日期
    "symbol",       # 商品代號
    "contract_mo",  # 到期月份(週別)
    "trade_time",   # 成交時間
    "price",        # 成交價格
    "qty",          # 成交數量(B+S)
    "near_price",   # 近月價格
    "far_price",    # 遠月價格
    "auction_flag", # 開盤集合競價
    "ts",           # 時間戳記
]


def load_one_file(fn: Path) -> pd.DataFrame:
    """Read one Daily_*TX1.csv with Big5 encoding, return clean tick frame."""
    df = pd.read_csv(fn, encoding="big5", low_memory=False, na_values=["-"])
    df.columns = COLS_RAW

    # Drop 集合競價 ticks (boundary, not tradable in our resample)
    df = df[df["auction_flag"] != "*"].copy()

    # Numeric coercion (price/qty могут быть строкой при '-')
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce")
    df = df.dropna(subset=["price", "qty"])
    df = df[df["price"] > 0]

    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    df = df.dropna(subset=["ts"])

    df["contract_mo"] = df["contract_mo"].astype(str).str.strip()

    return df[["ts", "price", "qty", "contract_mo"]].reset_index(drop=True)


# ----------------------------------------------------------------------
# 2. Session tagging
# ----------------------------------------------------------------------
def tag_session(ts_series: pd.Series, file_date: pd.Timestamp) -> pd.Series:
    """Tag each tick as 'day' or 'night' based on session window.

    A file Daily_YYYY_MM_DD<X>.csv contains:
      - night ticks of file_date-1 (15:00 file_date-1 → 23:59 file_date-1)
      - night ticks early file_date (00:00 → 05:00)
      - day ticks file_date (08:45 → 13:45)
    All night ticks are bucketed under "session_date = file_date" for our
    purpose (matching K1100g cache convention).

    Returns Series of {'day','night','other'}.
    """
    t = ts_series.dt.time
    out = pd.Series(["other"] * len(ts_series), index=ts_series.index, dtype=object)

    # Day session 08:45-13:45 of file_date
    is_day = (
        (ts_series.dt.date == file_date.date())
        & (ts_series.dt.hour * 3600 + ts_series.dt.minute * 60 + ts_series.dt.second
           >= 8 * 3600 + 45 * 60)
        & (ts_series.dt.hour * 3600 + ts_series.dt.minute * 60 + ts_series.dt.second
           <= 13 * 3600 + 45 * 60)
    )
    out[is_day] = "day"

    # Night session: 15:00 file_date-1 ... 05:00 file_date
    prev_date = (file_date - pd.Timedelta(days=1)).date()
    is_night_eve = (
        (ts_series.dt.date == prev_date)
        & (ts_series.dt.hour >= 15)
    )
    is_night_morn = (
        (ts_series.dt.date == file_date.date())
        & (ts_series.dt.hour < 5)
    ) | (
        (ts_series.dt.date == file_date.date())
        & (ts_series.dt.hour == 5)
        & (ts_series.dt.minute == 0)
        & (ts_series.dt.second == 0)
    )
    out[is_night_eve | is_night_morn] = "night"
    return out


# ----------------------------------------------------------------------
# 3. Build 5-min bars from one file
# ----------------------------------------------------------------------
def build_5min_bars(tick_df: pd.DataFrame, file_date: pd.Timestamp) -> pd.DataFrame:
    """Resample tick → 5-min bars. Returns one row per (session_date, session, bar_start)."""
    if tick_df.empty:
        return pd.DataFrame()

    tick_df = tick_df.copy()
    tick_df["session"] = tag_session(tick_df["ts"], file_date)
    tick_df = tick_df[tick_df["session"].isin(["day", "night"])]
    if tick_df.empty:
        return pd.DataFrame()

    # 5-min bins by ts floor
    tick_df["bar_start"] = tick_df["ts"].dt.floor("5min")

    g = tick_df.groupby(["session", "bar_start"], sort=True)
    bars = g.agg(
        open=("price", "first"),
        close=("price", "last"),
        high=("price", "max"),
        low=("price", "min"),
        n_ticks=("price", "count"),
        volume=("qty", "sum"),
    ).reset_index()

    bars["session_date"] = file_date.normalize()
    bars["contract_mo"] = tick_df["contract_mo"].iloc[0]  # TX1 is near, single contract
    return bars


# ----------------------------------------------------------------------
# 4. Build all 5-min bars for date range
# ----------------------------------------------------------------------
def list_tx1_files(start_year: int, end_year: int) -> List[Path]:
    pattern = re.compile(r"Daily_(\d{4})_(\d{2})_(\d{2})TX1\.csv")
    files = []
    for fn in sorted(TAIFEX_DIR.glob("Daily_*TX1.csv")):
        m = pattern.match(fn.name)
        if not m:
            continue
        y = int(m.group(1))
        if start_year <= y <= end_year:
            files.append(fn)
    return files


def build_5min_cache(force: bool = False) -> pd.DataFrame:
    """Build full 5-min cache for 2017-05-16 to 2021-12-31."""
    if CACHE_5MIN.exists() and not force:
        print(f"[cache hit] {CACHE_5MIN}")
        return pd.read_parquet(CACHE_5MIN)

    files = list_tx1_files(START_YEAR, END_YEAR)
    print(f"  Found {len(files)} TX1 files in {START_YEAR}-{END_YEAR}")

    all_bars: List[pd.DataFrame] = []
    t0 = time.time()
    for i, fn in enumerate(files):
        m = re.match(r"Daily_(\d{4})_(\d{2})_(\d{2})TX1\.csv", fn.name)
        file_date = pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)),
                                  day=int(m.group(3)))
        # Skip pre-2017-05-16 (no stable night session schema)
        if file_date < pd.Timestamp("2017-05-16"):
            continue
        try:
            tick_df = load_one_file(fn)
            bars = build_5min_bars(tick_df, file_date)
            if not bars.empty:
                all_bars.append(bars)
        except Exception as e:
            print(f"  [warn] {fn.name}: {e}")
        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(files)}] elapsed={elapsed:.1f}s")

    if not all_bars:
        raise RuntimeError("No bars built — check data path / encoding")

    bars_df = pd.concat(all_bars, ignore_index=True)
    bars_df = bars_df.sort_values(["session_date", "session", "bar_start"]).reset_index(drop=True)
    bars_df.to_parquet(CACHE_5MIN, index=False)
    print(f"  Cached {len(bars_df):,} 5-min bars → {CACHE_5MIN}")
    return bars_df


# ----------------------------------------------------------------------
# 5. Daily intraday-derived features
# ----------------------------------------------------------------------
def build_daily_features(bars_df: pd.DataFrame, force: bool = False) -> pd.DataFrame:
    """Aggregate 5-min bars to daily intraday features (day session only).

    Each daily row contains:
      - day_open, day_close, day_high, day_low
      - day_rv_5min       : sum of squared 5-min log returns (within day)
      - day_rv_parkinson  : (1/(4 ln2)) * (ln(H/L))^2
      - day_intraday_mom  : log(close/open)
      - day_hod_rv_ratio  : first-half-day RV / full-day RV
      - day_bipower_var   : (pi/2) * sum |r_k| |r_{k-1}|  (jump-robust)
      - day_n_bars        : number of 5-min bars (sanity check, expect ~60)

    NOTE: NO .shift() applied here. shift to t-1 happens in PRG script when
    these features are used as predictive exog at time t.
    """
    if CACHE_DAILY.exists() and not force:
        print(f"[cache hit] {CACHE_DAILY}")
        return pd.read_parquet(CACHE_DAILY)

    day_bars = bars_df[bars_df["session"] == "day"].copy()
    day_bars = day_bars.sort_values(["session_date", "bar_start"]).reset_index(drop=True)

    rows = []
    for date, grp in day_bars.groupby("session_date"):
        grp = grp.sort_values("bar_start").reset_index(drop=True)
        n = len(grp)
        if n < 20:  # need at least 20 bars (~1.67h) for stable RV
            continue

        # 5-min log returns within day session
        prices = grp["close"].values.astype(float)
        rets = np.log(prices[1:] / prices[:-1])

        rv_5min = float(np.sum(rets ** 2))
        bipower = float(np.pi / 2.0 * np.sum(np.abs(rets[1:]) * np.abs(rets[:-1]))) if len(rets) >= 2 else np.nan

        H = float(grp["high"].max())
        L = float(grp["low"].min())
        rv_park = float((1.0 / (4.0 * np.log(2.0))) * (np.log(H / L) ** 2)) if L > 0 else np.nan

        op = float(grp["open"].iloc[0])
        cl = float(grp["close"].iloc[-1])
        intraday_mom = float(np.log(cl / op))

        # First-half-day RV ratio (first n/2 bars)
        half = n // 2
        if half >= 5:
            rets_half = rets[:half - 1]  # returns within first half (n/2 bars → n/2-1 rets)
            rv_half = float(np.sum(rets_half ** 2))
            hod_ratio = rv_half / rv_5min if rv_5min > 0 else np.nan
        else:
            hod_ratio = np.nan

        rows.append({
            "date": date,
            "day_open": op,
            "day_close": cl,
            "day_high": H,
            "day_low": L,
            "day_rv_5min": rv_5min,
            "day_rv_parkinson": rv_park,
            "day_intraday_mom": intraday_mom,
            "day_hod_rv_ratio": hod_ratio,
            "day_bipower_var": bipower,
            "day_n_bars": n,
        })

    daily = pd.DataFrame(rows)
    daily = daily.sort_values("date").reset_index(drop=True)
    daily.to_parquet(CACHE_DAILY, index=False)
    print(f"  Cached {len(daily)} daily-feature rows → {CACHE_DAILY}")
    return daily


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print(f"[{time.strftime('%H:%M:%S')}] Building 5-min bar cache ...")
    bars = build_5min_cache(force=False)
    print(f"  bars rows={len(bars):,}  date range="
          f"{bars['session_date'].min()} ... {bars['session_date'].max()}")

    print(f"\n[{time.strftime('%H:%M:%S')}] Building daily intraday features ...")
    daily = build_daily_features(bars, force=False)
    print(f"  daily rows={len(daily)}  "
          f"date range={daily['date'].min()} ... {daily['date'].max()}")
    print(f"\n  Sample features (first 3):")
    print(daily.head(3).to_string())
    print(f"\n  Cache disk usage:")
    for p in [CACHE_5MIN, CACHE_DAILY]:
        if p.exists():
            mb = p.stat().st_size / 1024 / 1024
            print(f"    {p.name}: {mb:.1f} MB")
