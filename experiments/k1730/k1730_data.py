"""
K1730 data layer — point-in-time (PIT) feature construction.

Two hard constraints drive every choice in this file:

1.  **Revised macro series must be point-in-time.** FRED's *current* history of
    CPI or payrolls is not what a forecaster saw at the time: the numbers get
    revised, and some early history is backcast. K1655 failed its Codex review
    for exactly this (343/1131 origins predated the index's own first release).
    We therefore pull ALFRED ``output_type=4`` ("initial release only"), which
    returns, for each observation month, the value *as first published* together
    with the date it was first published. At a forecast origin ``t`` we keep only
    observations whose first-release date is strictly before ``t``, and we use
    the first-release value — never a later revision.

2.  **The target must not leak into its own features.** The target for week ``w``
    is the max of daily RV *inside* week ``w``; the origin is the last trading day
    of week ``w-1``. Every feature is built from data stamped at or before that
    origin, and :func:`assert_no_lookahead` re-checks this from the emitted frame
    rather than trusting the construction code.

Data sources
------------
- SPY OHLC: yfinance (1995-01-01 onwards)
- RV proxy: Parkinson (repo canonical, ``volpred.data.preprocessing``)
- CPIAUCSL / PAYEMS / INDPRO / UNRATE: ALFRED first-release PIT
- VIXCLS, DGS10, DTB3: FRED (market data, never revised)
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from volpred.data.preprocessing import compute_realized_variance_proxy

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)

SAMPLE_START = "1995-01-01"
SAMPLE_END = "2026-07-17"

# Monthly macro series that FRED *revises* → require true first-release vintages.
REVISED_MONTHLY = {
    "CPI": "CPIAUCSL",     # headline CPI, SA index
    "NFP": "PAYEMS",       # total nonfarm payrolls
    "IP": "INDPRO",        # industrial production index
    "UNRATE": "UNRATE",    # civilian unemployment rate
}

# Daily market series that are never revised → monthly aggregate is final the
# moment the month closes. No vintage machinery needed, only a calendar lag.
DAILY_MARKET = {
    "VIX": "VIXCLS",
    "DGS10": "DGS10",
    "DTB3": "DTB3",
}

# How each monthly series is transformed into a stationary MIDAS regressor.
# The transform is applied to the *first-release* series, so a value becomes
# available on the first-release date of its own observation month.
MACRO_TRANSFORMS = {
    "CPI": "yoy_log",       # 12-month log inflation
    "NFP": "yoy_log",       # 12-month payroll growth
    "IP": "yoy_log",        # 12-month industrial production growth
    "UNRATE": "diff12",     # 12-month change in unemployment rate
    "VIX": "log_level",     # log of monthly mean VIX
    "TERM": "level",        # DGS10 - DTB3, monthly mean
}

MACRO_VARS = ["CPI", "NFP", "IP", "UNRATE", "VIX", "TERM"]


def _api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    # The worktree does not carry .env.local; the canonical checkout does.
    for root in (Path(__file__).resolve().parents[2],
                 Path.home() / "volpred-research"):
        for cand in (".env.local", ".env"):
            p = root / cand
            if not p.exists():
                continue
            for line in p.read_text().splitlines():
                if line.startswith("FRED_API_KEY"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError(
        "FRED_API_KEY not found. This experiment requires real ALFRED vintages; "
        "there is no offline fallback and none should be added."
    )


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------
# 1. SPY realized variance → weekly block maxima
# ------------------------------------------------------------------

def load_spy_rv(cache: bool = True) -> pd.DataFrame:
    """Daily SPY Parkinson realized variance."""
    cache_path = DATA_DIR / "spy_daily_rv.csv"
    if cache and cache_path.exists():
        log(f"  SPY RV from cache ({cache_path.name})")
        return pd.read_csv(cache_path, parse_dates=["date"]).set_index("date")

    import yfinance as yf
    log("  Downloading SPY OHLC from yfinance...")
    raw = yf.download("SPY", start=SAMPLE_START, end=SAMPLE_END,
                      auto_adjust=False, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()

    # Parkinson is the repo default proxy. We have no intraday SPY back to 1995,
    # and the range estimator is far less noisy than squared close-to-close
    # returns — but it is still a *proxy*, and the README says so.
    rv = compute_realized_variance_proxy(df, method="parkinson")
    out = pd.DataFrame({"rv": rv})
    out = out[out["rv"] > 0].copy()
    out.index.name = "date"
    out.to_csv(cache_path)
    log(f"  SPY daily RV: {len(out)} days, {out.index.min().date()} → {out.index.max().date()}")
    return out


def build_weekly_blocks(daily_rv: pd.DataFrame, min_days: int = 3) -> pd.DataFrame:
    """Non-overlapping weekly block maxima of daily RV.

    Returns one row per week with:
      ``origin``      last trading day of the *previous* week (forecast origin)
      ``block_start`` first trading day of the block week
      ``y``           log of the max daily RV inside the block week
      HAR features    computed from days at or before ``origin``

    Weeks with fewer than ``min_days`` trading days are dropped: a 2-day holiday
    week's maximum is a draw from a different distribution than a 5-day week's,
    and mixing them would show up as spurious tail behaviour.
    """
    d = daily_rv.copy()
    d["log_rv"] = np.log(d["rv"])
    iso = d.index.isocalendar()
    d["week_key"] = iso["year"].astype(int) * 100 + iso["week"].astype(int)

    # HAR components as of each *day* (strictly trailing: shift(1) then roll).
    lag = d["log_rv"].shift(1)
    d["har_d"] = lag
    d["har_w"] = lag.rolling(5).mean()
    d["har_m"] = lag.rolling(22).mean()
    # Level of realized variance over the trailing month, used for the GEV scale.
    d["har_m_level"] = lag.rolling(22).mean()

    rows = []
    week_keys = d["week_key"].unique()
    for i, wk in enumerate(week_keys):
        if i == 0:
            continue  # no previous week to take an origin from
        block = d[d["week_key"] == wk]
        if len(block) < min_days:
            continue
        prev = d[d["week_key"] == week_keys[i - 1]]
        if len(prev) == 0:
            continue
        origin = prev.index[-1]

        # HAR features evaluated ON the origin day use lag = shift(1), i.e. the
        # day before the origin. That is deliberately one day more conservative
        # than necessary; it costs a little information and removes any doubt
        # about same-day availability of the origin's own close.
        feat = d.loc[origin]
        if not np.isfinite([feat["har_d"], feat["har_w"], feat["har_m"]]).all():
            continue

        rows.append({
            "week_key": int(wk),
            "origin": origin,
            "block_start": block.index[0],
            "block_end": block.index[-1],
            "n_days": len(block),
            "y": float(np.log(block["rv"].max())),
            "har_d": float(feat["har_d"]),
            "har_w": float(feat["har_w"]),
            "har_m": float(feat["har_m"]),
        })

    out = pd.DataFrame(rows)
    log(f"  Weekly blocks: {len(out)} weeks, "
        f"{out['block_start'].min().date()} → {out['block_end'].max().date()}")
    return out


# ------------------------------------------------------------------
# 2. ALFRED first-release PIT macro
# ------------------------------------------------------------------

def fetch_first_release(series_id: str, alias: str, cache: bool = True) -> pd.DataFrame:
    """ALFRED initial-release-only observations.

    ``output_type=4`` returns, for every observation period, the value as it was
    *first* published plus ``realtime_start`` = the date of that first
    publication. This is the cleanest PIT primitive FRED exposes: it is immune to
    both revision leakage and to backcast history, because a backcast value has
    no first-release date earlier than the backcast itself.
    """
    cache_path = DATA_DIR / f"{alias}_first_release.csv"
    if cache and cache_path.exists():
        log(f"  {alias} from cache")
        return pd.read_csv(cache_path, parse_dates=["obs_date", "release_date"])

    log(f"  Fetching ALFRED first-release for {series_id} ({alias})...")
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": _api_key(),
            "file_type": "json",
            "output_type": "4",              # initial release only
            "realtime_start": "1776-07-04",  # full vintage span
            "realtime_end": "9999-12-31",
            "observation_start": "1990-01-01",
            "observation_end": SAMPLE_END,
        },
        timeout=90,
    )
    r.raise_for_status()
    obs = r.json().get("observations", [])
    if not obs:
        raise RuntimeError(f"ALFRED returned no observations for {series_id}")

    df = pd.DataFrame(obs)
    df = df[df["value"] != "."].copy()
    df["obs_date"] = pd.to_datetime(df["date"])
    df["release_date"] = pd.to_datetime(df["realtime_start"])
    df["value"] = df["value"].astype(float)

    # A first-release date at the ALFRED sentinel means "no true vintage exists"
    # — the value was backfilled. Those observations cannot be used PIT.
    sentinel = pd.Timestamp("1776-07-04")
    n_backfilled = int((df["release_date"] <= sentinel).sum())
    if n_backfilled:
        log(f"    WARNING {alias}: {n_backfilled} observations have no true vintage; dropping")
        df = df[df["release_date"] > sentinel]

    out = df[["obs_date", "release_date", "value"]].sort_values("obs_date").reset_index(drop=True)
    out.to_csv(cache_path, index=False)
    log(f"    {alias}: {len(out)} obs, first release {out['release_date'].min().date()}, "
        f"median lag {int((out['release_date'] - out['obs_date']).dt.days.median())}d")
    return out


def fetch_fred_daily(series_id: str, alias: str, cache: bool = True) -> pd.Series:
    """Daily FRED market series (not revised)."""
    cache_path = DATA_DIR / f"{alias}_daily.csv"
    if cache and cache_path.exists():
        log(f"  {alias} from cache")
        s = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date")[alias]
        return s

    log(f"  Fetching FRED daily {series_id} ({alias})...")
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": _api_key(),
            "file_type": "json",
            "observation_start": "1990-01-01",
            "observation_end": SAMPLE_END,
        },
        timeout=90,
    )
    r.raise_for_status()
    obs = [o for o in r.json().get("observations", []) if o["value"] != "."]
    s = pd.Series(
        [float(o["value"]) for o in obs],
        index=pd.to_datetime([o["date"] for o in obs]),
        name=alias,
    )
    s.index.name = "date"
    s.to_frame().to_csv(cache_path)
    log(f"    {alias}: {len(s)} obs, {s.index.min().date()} → {s.index.max().date()}")
    return s


def build_monthly_macro(cache: bool = True) -> pd.DataFrame:
    """Monthly macro panel with an explicit availability date per observation.

    Columns: ``obs_month``, ``available_from``, one column per variable in
    :data:`MACRO_VARS`. ``available_from`` is the date on which that month's
    value could first have been used.
    """
    frames = {}

    # --- revised series: transform the first-release series --------------
    for alias, sid in REVISED_MONTHLY.items():
        fr = fetch_first_release(sid, alias, cache=cache)
        s = fr.set_index("obs_date")["value"]
        rel = fr.set_index("obs_date")["release_date"]

        transform = MACRO_TRANSFORMS[alias]
        if transform == "yoy_log":
            val = np.log(s) - np.log(s.shift(12))
        elif transform == "diff12":
            val = s - s.shift(12)
        else:
            raise ValueError(transform)

        # A 12-month transform of month m needs month m-12, which was released
        # long before month m — so availability is still month m's release date.
        frames[alias] = pd.DataFrame({
            "value": val,
            "available_from": rel,
        }).dropna()

    # --- market series: monthly mean, available once the month closes -----
    vix = fetch_fred_daily(DAILY_MARKET["VIX"], "VIX", cache=cache)
    dgs10 = fetch_fred_daily(DAILY_MARKET["DGS10"], "DGS10", cache=cache)
    dtb3 = fetch_fred_daily(DAILY_MARKET["DTB3"], "DTB3", cache=cache)
    term = (dgs10 - dtb3).dropna()

    for alias, series, transform in (("VIX", vix, "log_level"), ("TERM", term, "level")):
        monthly = series.resample("MS").mean().dropna()
        val = np.log(monthly) if transform == "log_level" else monthly
        # Available the day after the month ends — the monthly mean is only
        # complete once the last trading day of the month has printed.
        avail = (monthly.index + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1))
        frames[alias] = pd.DataFrame(
            {"value": val.values, "available_from": avail}, index=monthly.index
        )

    # --- align into one panel -------------------------------------------
    panel = []
    for alias in MACRO_VARS:
        f = frames[alias].copy()
        f.index.name = "obs_month"
        f = f.reset_index()
        f["variable"] = alias
        panel.append(f)
    out = pd.concat(panel, ignore_index=True)
    out = out.sort_values(["variable", "obs_month"]).reset_index(drop=True)

    for alias in MACRO_VARS:
        sub = out[out["variable"] == alias]
        lag_days = (sub["available_from"] - sub["obs_month"]).dt.days
        log(f"    {alias}: {len(sub)} months, availability lag "
            f"median {int(lag_days.median())}d, min {int(lag_days.min())}d")
    return out


def _to_ns(values) -> np.ndarray:
    """Datetime-like → int64 nanoseconds.

    pandas 2.x infers ``datetime64[us]`` for some frames and ``[ns]`` for others,
    and ``.astype('int64')`` silently returns whatever unit it was handed. Every
    datetime comparison in this file goes through here so a unit mismatch cannot
    turn into a wrong-by-1000x comparison.
    """
    return pd.to_datetime(values).values.astype("datetime64[ns]").astype("int64")


def build_midas_lag_tensor(
    weeks: pd.DataFrame,
    macro: pd.DataFrame,
    n_lags: int = 12,
) -> tuple[np.ndarray, np.ndarray]:
    """For each week origin, the ``n_lags`` most recent *available* monthly values.

    Returns
    -------
    tensor : (n_weeks, n_vars, n_lags)
        ``tensor[i, j, k]`` is the value of variable ``j`` at MIDAS lag ``k``
        (k=0 is the most recent available month) as of week ``i``'s origin.
    stamp : (n_weeks, n_vars, n_lags)
        The availability date of each entry, as int64 nanoseconds — kept so the
        lookahead check can verify availability from the emitted data rather
        than trusting this function.

    Rows where any variable has fewer than ``n_lags`` available months are
    returned as NaN and dropped by the caller.
    """
    var_frames = {
        v: macro[macro["variable"] == v].sort_values("available_from").reset_index(drop=True)
        for v in MACRO_VARS
    }

    n_w, n_v = len(weeks), len(MACRO_VARS)
    tensor = np.full((n_w, n_v, n_lags), np.nan)
    stamp = np.zeros((n_w, n_v, n_lags), dtype="int64")

    origins_ns = _to_ns(weeks["origin"])

    for j, v in enumerate(MACRO_VARS):
        f = var_frames[v]
        avail = _to_ns(f["available_from"])
        vals = f["value"].values
        # searchsorted with side='left' → strictly-before semantics: an
        # observation released exactly on the origin date is NOT used.
        idx = np.searchsorted(avail, origins_ns, side="left")
        for i in range(n_w):
            end = idx[i]
            if end < n_lags:
                continue
            tensor[i, j, :] = vals[end - n_lags:end][::-1]   # k=0 is most recent
            stamp[i, j, :] = avail[end - n_lags:end][::-1]

    return tensor, stamp


# ------------------------------------------------------------------
# 3. Lookahead verification
# ------------------------------------------------------------------

def assert_no_lookahead(weeks: pd.DataFrame, stamp: np.ndarray) -> dict:
    """Verify, from the emitted data, that nothing is known before it exists.

    Three independent checks, each of which would have caught a different class
    of bug:
      1. every macro observation used at origin ``t`` was released before ``t``
      2. every origin strictly precedes the start of the block it predicts
      3. blocks do not overlap (a non-overlapping block max is what we claim)
    """
    origins_ns = _to_ns(weeks["origin"])
    used = stamp > 0
    # Broadcast origins over (n_vars, n_lags).
    viol_macro = int(((stamp >= origins_ns[:, None, None]) & used).sum())

    starts = _to_ns(weeks["block_start"])
    viol_origin = int((origins_ns >= starts).sum())

    ends = _to_ns(weeks["block_end"])
    viol_overlap = int((starts[1:] <= ends[:-1]).sum())

    report = {
        "macro_released_before_origin": {"violations": viol_macro,
                                         "n_checked": int(used.sum())},
        "origin_before_block_start": {"violations": viol_origin,
                                      "n_checked": len(weeks)},
        "blocks_non_overlapping": {"violations": viol_overlap,
                                   "n_checked": max(len(weeks) - 1, 0)},
    }
    total = viol_macro + viol_origin + viol_overlap
    report["passed"] = bool(total == 0)
    if total:
        raise AssertionError(f"Lookahead check FAILED: {report}")
    log(f"  Lookahead check PASSED ({used.sum():,} macro cells, {len(weeks)} blocks)")
    return report
