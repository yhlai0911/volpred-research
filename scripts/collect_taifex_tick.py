#!/usr/bin/env python3
"""Build the canonical TAIFEX 5-minute realized-variance series.

The local TAIFEX archive contains one Big5/CP950 CSV per trading day.  Older
files have nine columns and five-digit time values; newer files have ten
columns, six-digit time values, and the night session.  This collector reads
columns by their header meaning, normalizes those schema variants, selects the
highest-volume monthly TX contract for each trading day, and computes returns
only within a session.  Consequently neither contract-roll gaps nor the two
closed-market gaps are counted as realized variance.

Contract selection uses the completed day's total volume because this file is
an end-of-day realized measure.  The recorded ``selection_rule`` makes that
choice explicit; consumers must not treat it as a same-day real-time signal.

Default source:
  ~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_YYYY_MM_DDTX.csv

Canonical output:
  data/intraday/taifex_5min_rv.csv

``rv_5min`` is the homogeneous day-session series available for the full
history.  ``rv_night`` and ``rv_total`` are explicit opt-in fields from the
2017 night-session era onward; pre-night rows keep ``rv_night`` missing.

The default invocation is incremental and idempotent.  A source file is
reprocessed only when its size or nanosecond mtime changes.  With no changed
source, the output is deliberately left untouched so freshness monitoring
cannot be fooled by a no-op run.

Examples:
  uv run python scripts/collect_taifex_tick.py
  uv run python scripts/collect_taifex_tick.py --full-rebuild --workers 6 \
      --require-correlation 0.9
"""

from __future__ import annotations

import argparse
import fcntl
import math
import os
import re
import shutil
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = (
    Path.home() / "Dropbox" / "TAIFEXDATA" / "TAIFEXDATA" / "python"
)
DEFAULT_OUTPUT = ROOT / "data" / "intraday" / "taifex_5min_rv.csv"
DEFAULT_VALIDATION_DIR = ROOT / "data" / "intraday"
LOCK_PATH = ROOT / "storage" / "ops" / "locks" / "taifex_5min_rv.lock"

SOURCE_PATTERN = re.compile(r"^Daily_(\d{4})_(\d{2})_(\d{2})TX\.csv$")
MIN_SOURCE_BYTES = 100
DAY_START = 8 * 10000 + 45 * 100
DAY_END = 13 * 10000 + 45 * 100
NIGHT_PM_START = 15 * 10000
NIGHT_AM_END = 5 * 10000

OUTPUT_COLUMNS = [
    "date",
    "active_contract",
    "selection_rule",
    "is_roll",
    "has_night",
    "rv_5min",
    "rv_day",
    "rv_night",
    "rv_total",
    "bpv_day",
    "bpv_night",
    "bpv_total",
    "jump_day",
    "jump_night",
    "jump_total",
    "day_return",
    "night_return",
    "day_open",
    "day_close",
    "night_open",
    "night_close",
    "day_n_bars",
    "night_n_bars",
    "day_n_ticks",
    "night_n_ticks",
    "source_file",
    "source_size",
    "source_mtime_ns",
]

HEADER_ALIASES = {
    "trade_date": ("成交日期",),
    "symbol": ("商品代號",),
    "contract": ("到期月份(週別)", "到期月份（週別）", "到期月份"),
    "trade_time": ("成交時間",),
    "price": ("成交價格",),
    "volume": ("成交數量(B+S)", "成交數量（B+S）", "成交數量"),
    "auction": ("開盤集合競價",),
}


class SourceFormatError(RuntimeError):
    """A non-empty TAIFEX source file cannot be normalized safely."""


def _date_from_filename(path: Path) -> pd.Timestamp:
    match = SOURCE_PATTERN.fullmatch(path.name)
    if not match:
        raise SourceFormatError(f"unexpected source filename: {path.name}")
    year, month, day = map(int, match.groups())
    return pd.Timestamp(year=year, month=month, day=day)


def list_source_files(source_dir: Path) -> list[Path]:
    """Return TX all-contract files in deterministic trading-date order."""
    if not source_dir.is_dir():
        raise FileNotFoundError(f"TAIFEX source directory not found: {source_dir}")
    return sorted(
        (path for path in source_dir.glob("Daily_*TX.csv") if SOURCE_PATTERN.fullmatch(path.name)),
        key=lambda path: path.name,
    )


def _normalize_header(value: object) -> str:
    return str(value).lstrip("\ufeff").strip()


def _header_mapping(columns: Iterable[object]) -> dict[str, object]:
    normalized = {_normalize_header(column): column for column in columns}
    mapped: dict[str, object] = {}
    for semantic, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapped[semantic] = normalized[alias]
                break
    required = {"trade_date", "contract", "trade_time", "price", "volume"}
    missing = sorted(required - mapped.keys())
    if missing:
        raise SourceFormatError(f"missing semantic columns: {', '.join(missing)}")
    return mapped


def _read_with_encoding(path: Path, encoding: str) -> pd.DataFrame:
    header = pd.read_csv(path, encoding=encoding, nrows=0)
    mapping = _header_mapping(header.columns)
    usecols = list(dict.fromkeys(mapping.values()))
    frame = pd.read_csv(
        path,
        encoding=encoding,
        dtype=str,
        usecols=usecols,
        low_memory=False,
    )
    rename = {actual: semantic for semantic, actual in mapping.items()}
    return frame.rename(columns=rename)


def read_taifex_ticks(path: Path) -> pd.DataFrame:
    """Read and normalize a nine- or ten-column TAIFEX TX daily file."""
    if not path.exists() or path.stat().st_size < MIN_SOURCE_BYTES:
        raise SourceFormatError("source file is absent or empty")

    last_error: Exception | None = None
    frame: pd.DataFrame | None = None
    for encoding in ("big5", "cp950", "utf-8-sig"):
        try:
            frame = _read_with_encoding(path, encoding)
            break
        except (UnicodeDecodeError, UnicodeError, SourceFormatError) as exc:
            last_error = exc
    if frame is None:
        raise SourceFormatError(f"cannot decode/normalize {path.name}: {last_error}")

    if "symbol" in frame:
        frame = frame[frame["symbol"].astype(str).str.strip().eq("TX")].copy()
    if "auction" in frame:
        frame = frame[~frame["auction"].astype(str).str.strip().eq("*")].copy()

    frame["contract"] = frame["contract"].astype(str).str.strip()
    frame = frame[frame["contract"].str.fullmatch(r"\d{6}", na=False)].copy()
    frame["trade_date"] = pd.to_numeric(frame["trade_date"], errors="coerce")
    frame["trade_time"] = pd.to_numeric(frame["trade_time"], errors="coerce")
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    frame = frame.dropna(subset=["trade_date", "trade_time", "price", "volume"])
    frame = frame[(frame["price"] > 0) & (frame["trade_time"].between(0, 235959))]
    if len(frame) < 10:
        raise SourceFormatError("fewer than ten valid monthly-contract ticks")

    frame["trade_date"] = frame["trade_date"].astype("int64")
    frame["trade_time"] = frame["trade_time"].astype("int64")
    frame["contract"] = frame["contract"].astype("int64")
    frame["_row_order"] = np.arange(len(frame), dtype=np.int64)
    return frame[
        ["trade_date", "contract", "trade_time", "price", "volume", "_row_order"]
    ]


def pick_active_contract(frame: pd.DataFrame) -> int:
    """Select one monthly contract for the whole trading day by total volume."""
    volume = frame.groupby("contract", sort=True)["volume"].sum(min_count=1)
    if volume.empty or volume.isna().all():
        raise SourceFormatError("no valid contract volume")
    return int(volume.idxmax())


def _session_metrics(frame: pd.DataFrame, session: str) -> dict[str, Any]:
    if session == "day":
        mask = frame["trade_time"].between(DAY_START, DAY_END)
        endpoint = DAY_END
    elif session == "night":
        mask = (frame["trade_time"] >= NIGHT_PM_START) | (
            frame["trade_time"] <= NIGHT_AM_END
        )
        endpoint = NIGHT_AM_END
    else:  # pragma: no cover - internal contract
        raise ValueError(f"unknown session: {session}")

    ticks = frame.loc[mask].copy()
    if ticks.empty:
        return {
            "rv": math.nan,
            "bpv": math.nan,
            "jump": math.nan,
            "session_return": math.nan,
            "open": math.nan,
            "close": math.nan,
            "n_bars": 0,
            "n_ticks": 0,
        }

    ticks = ticks.sort_values(
        ["trade_date", "trade_time", "_row_order"], kind="stable"
    )
    hour = ticks["trade_time"] // 10000
    minute = (ticks["trade_time"] % 10000) // 100
    minute_of_day = hour * 60 + (minute // 5) * 5
    endpoint_mask = ticks["trade_time"].eq(endpoint)
    minute_of_day = minute_of_day.where(~endpoint_mask, minute_of_day - 5)
    ticks["bar_key"] = ticks["trade_date"] * 1440 + minute_of_day

    closes = ticks.groupby("bar_key", sort=True)["price"].last().astype(float)
    returns = np.diff(np.log(closes.to_numpy())) if len(closes) >= 2 else np.array([])
    rv = float(np.square(returns).sum()) if len(returns) else math.nan
    bpv = (
        float(np.pi / 2.0 * np.sum(np.abs(returns[1:]) * np.abs(returns[:-1])))
        if len(returns) >= 2
        else math.nan
    )
    jump = max(rv - bpv, 0.0) if math.isfinite(rv) and math.isfinite(bpv) else math.nan
    open_price = float(ticks["price"].iloc[0])
    close_price = float(ticks["price"].iloc[-1])
    session_return = float(np.log(close_price / open_price))
    return {
        "rv": rv,
        "bpv": bpv,
        "jump": jump,
        "session_return": session_return,
        "open": open_price,
        "close": close_price,
        "n_bars": int(len(closes)),
        "n_ticks": int(len(ticks)),
    }


def process_tick_file(path_value: str | Path) -> dict[str, Any]:
    """Normalize one file and return one trading-day RV record."""
    path = Path(path_value)
    file_date = _date_from_filename(path)
    frame = read_taifex_ticks(path)
    active_contract = pick_active_contract(frame)
    active = frame[frame["contract"].eq(active_contract)].copy()

    day = _session_metrics(active, "day")
    night = _session_metrics(active, "night")
    if not math.isfinite(day["rv"]):
        raise SourceFormatError("day session has fewer than two 5-minute bars")

    available_rv = [value for value in (day["rv"], night["rv"]) if math.isfinite(value)]
    available_bpv = [value for value in (day["bpv"], night["bpv"]) if math.isfinite(value)]
    rv_total = float(sum(available_rv))
    bpv_total = float(sum(available_bpv)) if available_bpv else math.nan
    jump_total = (
        max(rv_total - bpv_total, 0.0)
        if math.isfinite(rv_total) and math.isfinite(bpv_total)
        else math.nan
    )
    stat = path.stat()
    return {
        "date": file_date.date().isoformat(),
        "active_contract": active_contract,
        "selection_rule": "same_day_max_total_volume_monthly_TX",
        "is_roll": False,  # recomputed after incremental merge
        "has_night": night["n_bars"] >= 2,
        # The primary 14-year series stays day-session-only so its definition
        # does not change when the night session appears in 2017.  Consumers
        # wanting all traded hours must opt into the explicit rv_total field.
        "rv_5min": day["rv"],
        "rv_day": day["rv"],
        "rv_night": night["rv"],
        "rv_total": rv_total,
        "bpv_day": day["bpv"],
        "bpv_night": night["bpv"],
        "bpv_total": bpv_total,
        "jump_day": day["jump"],
        "jump_night": night["jump"],
        "jump_total": jump_total,
        "day_return": day["session_return"],
        "night_return": night["session_return"],
        "day_open": day["open"],
        "day_close": day["close"],
        "night_open": night["open"],
        "night_close": night["close"],
        "day_n_bars": day["n_bars"],
        "night_n_bars": night["n_bars"],
        "day_n_ticks": day["n_ticks"],
        "night_n_ticks": night["n_ticks"],
        "source_file": path.name,
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
    }


def _existing_output(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    frame = pd.read_csv(
        path,
        dtype={
            "source_file": "string",
            "source_size": "Int64",
            "source_mtime_ns": "Int64",
        },
    )
    missing = set(OUTPUT_COLUMNS) - set(frame.columns)
    if missing:
        raise RuntimeError(
            f"canonical output has incompatible schema; use --full-rebuild "
            f"(missing {sorted(missing)})"
        )
    return frame[OUTPUT_COLUMNS]


def _previous_source_names(path: Path) -> set[str]:
    """Read provenance loosely so a full rebuild can also migrate old schemas."""
    if not path.exists() or path.stat().st_size == 0:
        return set()
    try:
        frame = pd.read_csv(path, usecols=["source_file"], dtype={"source_file": "string"})
    except (ValueError, pd.errors.ParserError):
        return set()
    return set(frame["source_file"].dropna().astype(str))


def _changed_sources(
    files: list[Path], existing: pd.DataFrame, full_rebuild: bool
) -> list[Path]:
    if full_rebuild or existing.empty:
        return files
    metadata: dict[str, tuple[int, int]] = {}
    for row in existing[["source_file", "source_size", "source_mtime_ns"]].itertuples(
        index=False
    ):
        if pd.isna(row.source_size) or pd.isna(row.source_mtime_ns):
            continue
        metadata[str(row.source_file)] = (int(row.source_size), int(row.source_mtime_ns))
    changed = []
    for path in files:
        stat = path.stat()
        if metadata.get(path.name) != (stat.st_size, stat.st_mtime_ns):
            changed.append(path)
    return changed


def _process_sources(files: list[Path], workers: int) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    if not files:
        return rows, errors

    if workers <= 1 or len(files) <= 2:
        for path in files:
            try:
                rows.append(process_tick_file(path))
            except Exception as exc:  # noqa: BLE001 - surface per-file error and continue
                errors.append(f"{path.name}: {exc}")
        return rows, errors

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_tick_file, str(path)): path for path in files}
        done = 0
        for future in as_completed(futures):
            path = futures[future]
            done += 1
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001 - same per-file isolation as above
                errors.append(f"{path.name}: {exc}")
            if done % 250 == 0 or done == len(files):
                print(f"  processed {done:,}/{len(files):,} source files")
    return rows, errors


def _atomic_write_csv(frame: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", suffix=".tmp", dir=output.parent, delete=False
    )
    tmp_path = Path(handle.name)
    try:
        with handle:
            frame.to_csv(handle, index=False, float_format="%.16g")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, output)
    finally:
        tmp_path.unlink(missing_ok=True)


def update_canonical(
    source_dir: Path,
    output: Path,
    *,
    full_rebuild: bool = False,
    workers: int = 1,
    min_days: int = 2_000,
) -> dict[str, Any]:
    """Incrementally update canonical output and return an auditable summary."""
    files = list_source_files(source_dir)
    if not files:
        raise RuntimeError(f"no TAIFEX TX files found in {source_dir}")
    previous_sources = _previous_source_names(output)
    existing = pd.DataFrame(columns=OUTPUT_COLUMNS) if full_rebuild else _existing_output(output)
    if previous_sources:
        current_names = {path.name for path in files}
        disappeared = sorted(previous_sources - current_names)
        if disappeared:
            preview = ", ".join(disappeared[:5])
            raise RuntimeError(
                f"{len(disappeared)} canonical source file(s) disappeared ({preview}); "
                "canonical output was not changed"
            )
    changed = _changed_sources(files, existing, full_rebuild)
    print(
        f"TAIFEX source: {len(files):,} files; changed/new: {len(changed):,}; "
        f"mode={'full' if full_rebuild else 'incremental'}"
    )

    rows, errors = _process_sources(changed, max(1, workers))
    if errors:
        for error in errors[:20]:
            print(f"  [error] {error}")
        if len(errors) > 20:
            print(f"  [error] ... and {len(errors) - 20} more")
        # A batch is the atomic unit.  Never replace a complete canonical file
        # with a subset merely because some siblings happened to parse first.
        raise RuntimeError(
            f"{len(errors)} source file(s) failed; canonical output was not changed"
        )

    wrote = False
    if rows:
        new = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
        if full_rebuild or existing.empty:
            combined = new
        else:
            replaced = set(new["source_file"].astype(str))
            combined = pd.concat(
                [existing[~existing["source_file"].astype(str).isin(replaced)], new],
                ignore_index=True,
            )
        combined["date"] = pd.to_datetime(combined["date"], errors="raise")
        combined = combined.sort_values(["date", "source_file"], kind="stable")
        combined = combined.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
        combined["is_roll"] = combined["active_contract"].ne(
            combined["active_contract"].shift(1)
        )
        if len(combined):
            combined.loc[combined.index[0], "is_roll"] = False
        combined["date"] = combined["date"].dt.date.astype(str)
        combined = combined[OUTPUT_COLUMNS]
        if len(combined) < min_days:
            raise RuntimeError(
                f"coverage gate failed: {len(combined):,} days < required {min_days:,}"
            )
        _atomic_write_csv(combined, output)
        wrote = True
    else:
        combined = existing

    if combined.empty:
        raise RuntimeError("canonical output is empty")
    if len(combined) < min_days:
        raise RuntimeError(
            f"coverage gate failed: {len(combined):,} days < required {min_days:,}"
        )
    summary = {
        "source_files": len(files),
        "changed_files": len(changed),
        "processed_rows": len(rows),
        "errors": len(errors),
        "output_rows": len(combined),
        "start_date": str(combined["date"].min()),
        "end_date": str(combined["date"].max()),
        "wrote_output": wrote,
    }
    return summary


def _close_series_from_yfinance_file(path: Path) -> pd.Series:
    """Read one saved yfinance 0050 file without assuming flat headers."""
    with path.open("r", encoding="utf-8", errors="replace") as source:
        first_line = source.readline().split(",", 1)[0].strip()
        second_line = source.readline().split(",", 1)[0].strip()
    has_multi_header = first_line == "Price" and second_line == "Ticker"
    if has_multi_header:
        frame = pd.read_csv(path, header=[0, 1], index_col=0)
        close_columns = [column for column in frame.columns if str(column[0]).lower() == "close"]
        if close_columns:
            return pd.to_numeric(frame[close_columns[0]], errors="coerce").dropna()
    frame = pd.read_csv(path, index_col=0)
    close_name = next((column for column in frame.columns if str(column).lower() == "close"), None)
    if close_name is None:
        raise SourceFormatError(f"0050 validation file has no Close column: {path.name}")
    return pd.to_numeric(frame[close_name], errors="coerce").dropna()


def build_0050_validation_rv(validation_dir: Path) -> pd.DataFrame:
    """Recompute 0050 RV within each saved day (never across the overnight gap)."""
    rows = []
    pattern = re.compile(r"^0050_TW_5min_(\d{4}-\d{2}-\d{2})\.csv$")
    for path in sorted(validation_dir.glob("0050_TW_5min_*.csv")):
        match = pattern.fullmatch(path.name)
        if not match:
            continue
        close = _close_series_from_yfinance_file(path)
        if len(close) < 2:
            continue
        returns = np.diff(np.log(close.to_numpy(dtype=float)))
        rows.append({"date": match.group(1), "rv_0050": float(np.square(returns).sum())})
    return pd.DataFrame(rows, columns=["date", "rv_0050"])


def validate_against_0050(output: Path, validation_dir: Path) -> dict[str, Any]:
    """Compare same-calendar-day, day-session RV against saved 0050 5-minute bars."""
    taifex = pd.read_csv(output, usecols=["date", "rv_day"])
    reference = build_0050_validation_rv(validation_dir)
    merged = taifex.merge(reference, on="date", how="inner").dropna()
    correlation = float(merged["rv_day"].corr(merged["rv_0050"])) if len(merged) >= 2 else math.nan
    return {
        "overlap_days": int(len(merged)),
        "start_date": str(merged["date"].min()) if len(merged) else None,
        "end_date": str(merged["date"].max()) if len(merged) else None,
        "pearson_r": correlation,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--full-rebuild", action="store_true")
    parser.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 1))
    parser.add_argument("--min-days", type=int, default=2_000)
    parser.add_argument(
        "--validate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="compare day-session RV with saved 0050 yfinance 5-minute files",
    )
    parser.add_argument("--validation-dir", type=Path, default=DEFAULT_VALIDATION_DIR)
    parser.add_argument("--min-overlap", type=int, default=20)
    parser.add_argument(
        "--require-correlation",
        type=float,
        default=None,
        help="fail when overlap Pearson correlation is below this threshold",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.require_correlation is not None and not args.validate:
        raise RuntimeError("--require-correlation requires validation to be enabled")
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    candidate = args.output
    staged: Path | None = None
    if args.validate:
        descriptor, staged_value = tempfile.mkstemp(
            prefix=f".{args.output.name}.", suffix=".candidate", dir=args.output.parent
        )
        os.close(descriptor)
        staged = Path(staged_value)
        candidate = staged

    try:
        with LOCK_PATH.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if staged is not None and args.output.exists():
                shutil.copy2(args.output, staged)
            summary = update_canonical(
                args.source_dir.expanduser(),
                candidate,
                full_rebuild=args.full_rebuild,
                workers=args.workers,
                min_days=args.min_days,
            )

            if args.validate:
                validation = validate_against_0050(candidate, args.validation_dir)
                print(
                    "0050 overlap validation: "
                    f"n={validation['overlap_days']}, Pearson r={validation['pearson_r']:.6f}, "
                    f"{validation['start_date']}..{validation['end_date']}"
                )
                if validation["overlap_days"] < args.min_overlap:
                    raise RuntimeError(
                        "validation overlap gate failed: "
                        f"{validation['overlap_days']} < {args.min_overlap}"
                    )
                if args.require_correlation is not None and (
                    not math.isfinite(validation["pearson_r"])
                    or validation["pearson_r"] < args.require_correlation
                ):
                    raise RuntimeError(
                        "validation correlation gate failed: "
                        f"{validation['pearson_r']:.6f} < {args.require_correlation:.6f}"
                    )
                if summary["wrote_output"]:
                    os.replace(candidate, args.output)
                    staged = None
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)

    print(
        "TAIFEX canonical: "
        f"{summary['output_rows']:,} days, {summary['start_date']}..{summary['end_date']}, "
        f"wrote={summary['wrote_output']}"
    )
    print(f"completed in {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
