#!/usr/bin/env python3
"""K1735 panel builder: raw sources -> one cached sub-return panel for every cell.

Why a separate module
---------------------
The analysis in ``K1735.py`` needs sub-return level data (to form bar-RV at several
sub-return counts m, to truncate jumps, and to calibrate the fat-tail noise floor).
Building it from 3,500+ daily TAIFEX tick files takes minutes, so it is cached to
parquet and rebuilt only when missing or when ``--rebuild`` is passed.

Tick parsing is delegated to ``scripts/collect_taifex_tick.read_taifex_ticks``
(header-based era normalisation, big5/cp950 encodings, monthly-contract filter) so this
layer cannot drift from ``data/intraday/taifex_5min_rv.csv``.

Output schema (long, one row per sub-return)
--------------------------------------------
``cell`` | ``trade_day`` (int32 YYYYMMDD) | ``bar_idx`` (int16) | ``ret`` (float32)
| ``observed`` (bool) | ``price`` (float32, bar close, for the tick-size floor)

Cells and their native sub-return grids
---------------------------------------
=========== ============================ ======== =====================
cell        source                        native   bars per session
=========== ============================ ======== =====================
``tx_day``  TAIFEX TX tick 08:45-13:45    1 min    300
``tx_night``TAIFEX TX tick 15:00-05:00    1 min    840  (2017-05-16 on)
``spy``     yfinance 5-min CSV            5 min     78  (America/New_York)
``tw0050``  yfinance 5-min CSV            5 min     54  (Asia/Taipei)
=========== ============================ ======== =====================

The first trade of a session seeds the return recursion, so bar 1 carries a return like
every other bar -- otherwise the opening bin, the most important point of the U shape,
would be short one sub-return. Minutes with no trade inherit the previous close
(``observed=False``, return 0).

Timezone note: the yfinance CSVs are stamped in **UTC**. 09:30 New York is 14:30 UTC in
January and 13:30 UTC in July, so binning on raw UTC would shift the whole diurnal
profile by an hour twice a year and manufacture a fake "seasonal shape drifts over
time" result. Both yfinance cells are converted to exchange-local time before binning.
TAIFEX ``trade_time`` is already exchange-local.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from collect_taifex_tick import (  # noqa: E402
    SourceFormatError,
    pick_active_contract,
    read_taifex_ticks,
)

DEFAULT_TICK_DIR = Path.home() / "Dropbox" / "TAIFEXDATA" / "TAIFEXDATA" / "python"
PANEL_PATH = Path(__file__).resolve().parent / "data" / "k1735_subreturns.parquet"


def _resolve_yf_dir() -> Path:
    """``data/intraday`` holding the 5-minute CSVs.

    ``data/intraday/*.csv`` is gitignored, so in a linked worktree the CSVs exist only in
    the main checkout. Fall back to the common git dir's parent rather than silently
    building a panel with two of the four cells missing.
    """
    local = REPO_ROOT / "data" / "intraday"
    if any(local.glob("*_5min_*.csv")):
        return local
    try:
        common = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        canonical = Path(common).parent / "data" / "intraday"
        if any(canonical.glob("*_5min_*.csv")):
            return canonical
    except (subprocess.CalledProcessError, OSError):
        pass
    return local


DEFAULT_YF_DIR = _resolve_yf_dir()

DAY_OPEN_HHMM = (8, 45)
DAY_N_BARS = 300  # 08:45 -> 13:45, 1-minute bars
NIGHT_OPEN_HHMM = (15, 0)
NIGHT_N_BARS = 840  # 15:00 -> 05:00 next calendar day, 1-minute bars

# One row per cell: (source kind, bars per session, tick size in price units).
CELL_SPEC = {
    "tx_day": {"kind": "taifex", "n_bars": DAY_N_BARS, "tick_size": 1.0, "sub_minutes": 1},
    "tx_night": {"kind": "taifex", "n_bars": NIGHT_N_BARS, "tick_size": 1.0, "sub_minutes": 1},
    "spy": {
        "kind": "yfinance",
        "n_bars": 78,
        "tick_size": 0.01,
        "sub_minutes": 5,
        "glob": "SPY_5min_*.csv",
        "tz": "America/New_York",
        "open_hhmm": (9, 30),
    },
    "tw0050": {
        "kind": "yfinance",
        "n_bars": 54,
        "tick_size": 0.05,
        "sub_minutes": 5,
        "glob": "0050_TW_5min_*.csv",
        "tz": "Asia/Taipei",
        "open_hhmm": (9, 0),
    },
}


# --------------------------------------------------------------------------- TAIFEX


def _minute_index(trade_time: pd.Series, session: str) -> pd.Series:
    """Minutes since session open, or -1 when the tick falls outside the session."""
    hour = trade_time // 10000
    minute = (trade_time % 10000) // 100
    if session == "day":
        idx = (hour - DAY_OPEN_HHMM[0]) * 60 + (minute - DAY_OPEN_HHMM[1])
        inside = (trade_time >= 84500) & (trade_time <= 134500)
        idx = idx.where(trade_time != 134500, DAY_N_BARS - 1)  # endpoint print
        n_bars = DAY_N_BARS
    elif session == "night":
        evening = trade_time >= 150000
        idx = ((hour - NIGHT_OPEN_HHMM[0]) * 60 + minute).where(
            evening, (hour + 9) * 60 + minute
        )
        inside = (trade_time >= 150000) | (trade_time <= 50000)
        idx = idx.where(trade_time != 50000, NIGHT_N_BARS - 1)
        n_bars = NIGHT_N_BARS
    else:  # pragma: no cover - internal contract
        raise ValueError(f"unknown session: {session}")
    return idx.where(inside & idx.between(0, n_bars - 1), -1).astype("int64")


def _session_subreturns(frame: pd.DataFrame, session: str) -> pd.DataFrame | None:
    n_bars = DAY_N_BARS if session == "day" else NIGHT_N_BARS
    idx = _minute_index(frame["trade_time"], session)
    ticks = frame.loc[idx >= 0].copy()
    if ticks.empty:
        return None
    ticks["bar_idx"] = idx.loc[idx >= 0]
    # Night ticks span two calendar dates; bar_idx already orders evening before morning.
    ticks = ticks.sort_values(["bar_idx", "_row_order"], kind="stable")

    closes = ticks.groupby("bar_idx", sort=True)["price"].last()
    if len(closes) < 2:
        return None

    grid = np.arange(n_bars, dtype=np.int64)
    close_grid = pd.Series(np.nan, index=grid, dtype="float64")
    close_grid.loc[closes.index] = closes.to_numpy(dtype="float64")
    observed = close_grid.notna().to_numpy()
    close_grid = close_grid.ffill().bfill()

    log_close = np.log(close_grid.to_numpy(dtype="float64"))
    prev = np.concatenate(([np.log(float(ticks["price"].iloc[0]))], log_close[:-1]))
    return pd.DataFrame(
        {
            "cell": f"tx_{session}",
            "bar_idx": grid.astype("int16"),
            "ret": (log_close - prev).astype("float32"),
            "observed": observed,
            "price": close_grid.to_numpy(dtype="float32"),
        }
    )


def build_one_tick_file(path_value: str) -> pd.DataFrame | None:
    path = Path(path_value)
    try:
        ticks = read_taifex_ticks(path)
        contract = pick_active_contract(ticks)
    except (SourceFormatError, OSError, ValueError):
        return None
    ticks = ticks.loc[ticks["contract"] == contract]
    if len(ticks) < 100:
        return None

    # The file is named for the *trading day*; night ticks carry the preceding evening's
    # calendar date, so the file name -- not ``trade_date`` -- is the trading-day key.
    stem = path.stem  # Daily_YYYY_MM_DDTX
    trade_day = int(stem[6:10] + stem[11:13] + stem[14:16])

    parts = [
        block
        for session in ("day", "night")
        if (block := _session_subreturns(ticks, session)) is not None
    ]
    if not parts:
        return None
    out = pd.concat(parts, ignore_index=True)
    out.insert(1, "trade_day", np.int32(trade_day))
    return out


def build_taifex(tick_dir: Path, workers: int, limit: int | None) -> pd.DataFrame:
    files = sorted(p for p in tick_dir.glob("Daily_*TX.csv") if p.stat().st_size > 100)
    if limit is not None:
        files = files[:limit]
    if not files:
        raise SystemExit(f"no TX tick files under {tick_dir}")
    print(f"[panel] TAIFEX: {len(files)} files, {workers} workers", file=sys.stderr)
    frames: list[pd.DataFrame] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, block in enumerate(
            pool.map(build_one_tick_file, [str(p) for p in files], chunksize=8)
        ):
            if block is not None:
                frames.append(block)
            if (i + 1) % 1000 == 0:
                print(f"[panel]   {i + 1}/{len(files)}", file=sys.stderr)
    return pd.concat(frames, ignore_index=True)


# ------------------------------------------------------------------------ yfinance


def build_yfinance(cell: str, yf_dir: Path) -> pd.DataFrame:
    spec = CELL_SPEC[cell]
    n_bars, tz, (oh, om) = spec["n_bars"], spec["tz"], spec["open_hhmm"]
    step = spec["sub_minutes"]
    frames: list[pd.DataFrame] = []
    for path in sorted(yf_dir.glob(spec["glob"])):
        # Rows 1-2 are the yfinance multi-index header remnants (Ticker / blank).
        raw = pd.read_csv(path, skiprows=[1, 2], index_col=0, parse_dates=True)
        close = raw["Close"].dropna()
        if len(close) < 2:
            continue
        local = close.index.tz_convert(tz)
        bar_idx = ((local.hour * 60 + local.minute) - (oh * 60 + om)) // step
        keep = (bar_idx >= 0) & (bar_idx < n_bars)
        if keep.sum() < 2:
            continue
        keep = np.asarray(keep)
        px = close.to_numpy(dtype="float64")[keep]
        idx = np.asarray(bar_idx)[keep]
        trade_day = int(local[keep][0].strftime("%Y%m%d"))
        # A trading day may legitimately miss trailing bars (early close); reindex onto
        # the full grid so the balance check downstream sees the gap rather than a
        # silently shortened session.
        grid = pd.Series(np.nan, index=np.arange(n_bars, dtype=np.int64), dtype="float64")
        grid.loc[idx] = px
        observed = grid.notna().to_numpy()
        grid = grid.ffill().bfill()
        log_close = np.log(grid.to_numpy())
        prev = np.concatenate(([log_close[0]], log_close[:-1]))
        frames.append(
            pd.DataFrame(
                {
                    "cell": cell,
                    "trade_day": np.int32(trade_day),
                    "bar_idx": np.arange(n_bars, dtype="int16"),
                    "ret": (log_close - prev).astype("float32"),
                    "observed": observed,
                    "price": grid.to_numpy(dtype="float32"),
                }
            )
        )
    if not frames:
        raise SystemExit(f"no {cell} files under {yf_dir}")
    return pd.concat(frames, ignore_index=True)


# ----------------------------------------------------------------------------- API


def load_or_build(
    *,
    tick_dir: Path = DEFAULT_TICK_DIR,
    yf_dir: Path = DEFAULT_YF_DIR,
    panel_path: Path = PANEL_PATH,
    workers: int | None = None,
    rebuild: bool = False,
    limit: int | None = None,
) -> pd.DataFrame:
    if panel_path.is_file() and not rebuild:
        return pd.read_parquet(panel_path)
    workers = workers or max(1, (os.cpu_count() or 4) - 2)
    parts = [build_taifex(tick_dir, workers, limit)]
    for cell in ("spy", "tw0050"):
        parts.append(build_yfinance(cell, yf_dir))
        print(f"[panel] {cell}: done", file=sys.stderr)
    panel = pd.concat(parts, ignore_index=True)
    panel["cell"] = panel["cell"].astype("category")
    panel = panel.sort_values(["cell", "trade_day", "bar_idx"], kind="stable")
    panel = panel.reset_index(drop=True)
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(panel_path, index=False, compression="zstd")
    print(f"[panel] wrote {panel_path} rows={len(panel):,}", file=sys.stderr)
    return panel


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tick-dir", type=Path, default=DEFAULT_TICK_DIR)
    ap.add_argument("--yf-dir", type=Path, default=DEFAULT_YF_DIR)
    ap.add_argument("--out", type=Path, default=PANEL_PATH)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    panel = load_or_build(
        tick_dir=args.tick_dir,
        yf_dir=args.yf_dir,
        panel_path=args.out,
        workers=args.workers,
        rebuild=args.rebuild,
        limit=args.limit,
    )
    for cell, block in panel.groupby("cell", observed=True):
        print(
            f"{cell}: days={block['trade_day'].nunique()} rows={len(block):,} "
            f"range={block['trade_day'].min()}..{block['trade_day'].max()} "
            f"observed={block['observed'].mean():.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
