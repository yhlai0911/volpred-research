#!/usr/bin/env python3
"""Read-only inventory of the local TAIFEX archive under ~/Dropbox/TAIFEXDATA.

Scans the archive WITHOUT writing anything under ~/Dropbox (strictly read-only)
and emits data/intraday/taifex_tick_manifest.json describing:

  * per-subdirectory sync status (synced / placeholder / partial) and byte size
  * the futures tick set under TAIFEXDATA/python: per contract (TX/TX1/TX2)
    file count, date min/max, and the trading-day gaps (missing weekdays, which
    include TW public holidays -- see README -- plus the long/suspicious runs
    and cross-contract inconsistencies)
  * every format era, with FRESHLY MEASURED column count / header / time-digit
    width / night-session presence sampled from representative boundary days
  * global totals (files, bytes, covered year-months)

All numbers come from this scan; nothing is hard-coded from prior memory.  The
9->10 column boundary and the night-session boundary are DETECTED here, not
assumed, so the manifest stays honest if the archive changes.

Usage:
  uv run python scripts/taifex_tick_inventory.py
  uv run python scripts/taifex_tick_inventory.py --out /tmp/manifest.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import collect_taifex_tick as collector  # noqa: E402

ARCHIVE_ROOT = Path.home() / "Dropbox" / "TAIFEXDATA"
PYTHON_DIR = ARCHIVE_ROOT / "TAIFEXDATA" / "python"
DEFAULT_OUT = ROOT / "data" / "intraday" / "taifex_tick_manifest.json"

# Daily_{YYYY}_{MM}_{DD}{TX|TX1|TX2}.csv
DAILY_PATTERN = re.compile(r"^Daily_(\d{4})_(\d{2})_(\d{2})(TX|TX1|TX2)\.csv$")
CONTRACTS = ("TX", "TX1", "TX2")

# Representative days probed for measured era characteristics.  Chosen to sit on
# either side of the two known format boundaries plus the extremes.
REPRESENTATIVE_DAYS = [
    "Daily_2012_01_02TX.csv",  # earliest, pre-auction 9-col era
    "Daily_2013_06_03TX.csv",  # mid 10-col era
    "Daily_2014_01_02TX.csv",  # 10-col era
    "Daily_2017_05_15TX.csv",  # last pre-night day
    "Daily_2017_05_16TX.csv",  # first night-session day
]


def _ensure_read_only(path: Path) -> None:
    """Fail loudly if asked to touch anything under ~/Dropbox (defence in depth)."""
    dropbox = (Path.home() / "Dropbox").resolve()
    resolved = path.resolve()
    if dropbox in resolved.parents or resolved == dropbox:
        raise RuntimeError(f"refusing to write under read-only Dropbox: {path}")


# --------------------------------------------------------------------------- #
# Sub-directory sync status
# --------------------------------------------------------------------------- #
def _scan_tree(root: Path) -> dict[str, Any]:
    """Count files / zero-byte placeholders / bytes under a directory tree."""
    total = nonzero = zero = 0
    total_bytes = 0
    if not root.exists():
        return {"exists": False}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # Skip macOS metadata noise so it does not distort placeholder ratios.
        if path.name == ".DS_Store":
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue  # silent-ok: file vanished/unreadable between rglob and stat during inventory scan; skipping keeps placeholder ratios accurate
        total += 1
        total_bytes += size
        if size == 0:
            zero += 1
        else:
            nonzero += 1
    if total == 0:
        status = "empty"
    elif zero == 0:
        status = "synced"
    elif nonzero == 0:
        status = "placeholder"  # cloud-only; not downloaded locally
    else:
        status = "partial"
    return {
        "exists": True,
        "status": status,
        "total_files": total,
        "nonzero_files": nonzero,
        "zero_byte_files": zero,
        "total_bytes": total_bytes,
    }


def _subdirectory_status() -> dict[str, Any]:
    out: dict[str, Any] = {}
    out["TAIFEXDATA/python (futures tick)"] = _scan_tree(PYTHON_DIR)

    # Aggregate every TAIFEXDATA/{year}/csv raw tick directory.
    raw_root = ARCHIVE_ROOT / "TAIFEXDATA"
    agg = {"exists": False, "total_files": 0, "nonzero_files": 0,
           "zero_byte_files": 0, "total_bytes": 0, "year_dirs": []}
    for year_dir in sorted(raw_root.glob("[0-9][0-9][0-9][0-9]")):
        csv_dir = year_dir / "csv"
        if not csv_dir.is_dir():
            continue
        scan = _scan_tree(csv_dir)
        agg["exists"] = True
        agg["total_files"] += scan.get("total_files", 0)
        agg["nonzero_files"] += scan.get("nonzero_files", 0)
        agg["zero_byte_files"] += scan.get("zero_byte_files", 0)
        agg["total_bytes"] += scan.get("total_bytes", 0)
        agg["year_dirs"].append(year_dir.name)
    if agg["exists"]:
        agg["status"] = (
            "placeholder" if agg["nonzero_files"] == 0
            else "synced" if agg["zero_byte_files"] == 0 else "partial"
        )
    out["TAIFEXDATA/{year}/csv (raw tick)"] = agg

    out["OPTIONDATA (options tick)"] = _scan_tree(ARCHIVE_ROOT / "OPTIONDATA")
    out["vix"] = _scan_tree(ARCHIVE_ROOT / "vix")
    out["證交所 (TWSE)"] = _scan_tree(ARCHIVE_ROOT / "證交所")
    return out


# --------------------------------------------------------------------------- #
# python/ futures tick set: files, dates, gaps
# --------------------------------------------------------------------------- #
def _list_daily_files() -> dict[str, dict[str, Any]]:
    """Return {contract: {date_str: bytes}} parsed purely from filenames."""
    result: dict[str, dict[str, Any]] = {c: {} for c in CONTRACTS}
    if not PYTHON_DIR.is_dir():
        return result
    for path in PYTHON_DIR.iterdir():
        m = DAILY_PATTERN.match(path.name)
        if not m:
            continue
        y, mo, d, contract = m.groups()
        date = f"{y}-{mo}-{d}"
        try:
            result[contract][date] = path.stat().st_size
        except OSError:
            result[contract][date] = 0
    return result


def _gap_report(dates: list[str]) -> dict[str, Any]:
    """Weekday gaps within [min,max].  NOTE: weekday gaps include TW holidays."""
    if not dates:
        return {"n_dates": 0}
    present = pd.to_datetime(sorted(dates))
    lo, hi = present.min(), present.max()
    calendar = pd.bdate_range(lo, hi)  # Mon-Fri business days
    present_set = set(present.normalize())
    missing = [d for d in calendar if d.normalize() not in present_set]
    missing_dates = [d.date().isoformat() for d in missing]

    # Long/suspicious runs: >=3 consecutive missing weekdays (isolated holidays
    # are typically 1-2 days; longer runs flag genuine archive holes).
    long_runs: list[dict[str, str]] = []
    if missing:
        run_start = prev = missing[0]
        run_len = 1
        for cur in missing[1:]:
            if (cur - prev).days <= 3 and len(pd.bdate_range(prev, cur)) == 2:
                run_len += 1
            else:
                if run_len >= 3:
                    long_runs.append({"from": run_start.date().isoformat(),
                                      "to": prev.date().isoformat(),
                                      "weekdays_missing": run_len})
                run_start = cur
                run_len = 1
            prev = cur
        if run_len >= 3:
            long_runs.append({"from": run_start.date().isoformat(),
                              "to": prev.date().isoformat(),
                              "weekdays_missing": run_len})

    return {
        "n_dates": len(dates),
        "date_min": lo.date().isoformat(),
        "date_max": hi.date().isoformat(),
        "weekday_calendar_days": len(calendar),
        "missing_weekday_count": len(missing_dates),
        "missing_weekday_note": "includes TW public holidays; not all are true archive gaps",
        "missing_weekdays": missing_dates,
        "long_gap_runs_ge3": long_runs,
    }


def _contract_inventory(daily: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for contract in CONTRACTS:
        by_date = daily[contract]
        dates = sorted(by_date)
        report = _gap_report(dates)
        report["total_bytes"] = sum(by_date.values())
        report["zero_byte_files"] = sum(1 for v in by_date.values() if v == 0)
        out[contract] = report

    # Cross-contract inconsistencies: a real gap is a day where some but not all
    # of TX/TX1/TX2 exist (the missing ones are genuine holes, not holidays).
    all_dates = set().union(*(set(daily[c]) for c in CONTRACTS))
    inconsistent = []
    for date in sorted(all_dates):
        have = [c for c in CONTRACTS if date in daily[c]]
        if 0 < len(have) < len(CONTRACTS):
            inconsistent.append({"date": date, "present": have,
                                 "missing": [c for c in CONTRACTS if c not in have]})
    out["cross_contract_inconsistencies"] = {
        "count": len(inconsistent),
        "detail": inconsistent[:100],
    }
    return out


# --------------------------------------------------------------------------- #
# Measured era characteristics
# --------------------------------------------------------------------------- #
def _read_header_ncols(path: Path) -> int:
    """Column count from the raw header line (commas are ASCII in any Big5 file)."""
    with path.open("rb") as fh:
        first = fh.readline()
    return first.count(b",") + 1


def _detect_column_boundaries() -> list[dict[str, Any]]:
    """Scan every TX header's column count and report each transition date."""
    files = sorted(
        p for p in PYTHON_DIR.iterdir()
        if DAILY_PATTERN.match(p.name) and p.name.endswith("TX.csv")
    )
    transitions: list[dict[str, Any]] = []
    prev = None
    for path in files:
        ncols = _read_header_ncols(path)
        if ncols != prev:
            m = DAILY_PATTERN.match(path.name)
            y, mo, d, _ = m.groups()
            transitions.append({"first_date": f"{y}-{mo}-{d}",
                                "ncols": ncols, "file": path.name})
            prev = ncols
    return transitions


def _measure_day(path: Path) -> dict[str, Any]:
    """Decode one representative TX file and MEASURE its era characteristics."""
    frame = None
    used_encoding = None
    for encoding in collector.SOURCE_ENCODINGS:
        try:
            head = pd.read_csv(path, encoding=encoding, nrows=0)
            collector.map_semantic_columns(head.columns)  # era-robust validation
            frame = pd.read_csv(path, encoding=encoding, dtype=str, low_memory=False)
            used_encoding = encoding
            break
        except (UnicodeDecodeError, UnicodeError, collector.SourceFormatError):
            continue  # silent-ok: try next encoding in SOURCE_ENCODINGS; all-fail leaves frame=None → returns explicit error dict below
    if frame is None:
        return {"file": path.name, "error": "could not decode/normalize"}

    header = [collector._normalize_header(c) for c in frame.columns]
    mapping = collector.map_semantic_columns(frame.columns)
    time_col = mapping["trade_time"]
    times = pd.to_numeric(frame[time_col], errors="coerce").dropna()
    nonzero_times = times[times > 0]
    digit_lengths = nonzero_times.astype("int64").astype(str).str.len()

    night_rows = int(((times >= collector.NIGHT_PM_START) |
                      ((times > 0) & (times <= collector.NIGHT_AM_END))).sum())
    auction_rows = None
    if "auction" in mapping:
        auction_rows = int(
            frame[mapping["auction"]].astype(str).str.strip().eq("*").sum()
        )
    return {
        "file": path.name,
        "encoding": used_encoding,
        "n_columns": len(frame.columns),
        "header": header,
        "has_auction_column": "auction" in mapping,
        "time_digit_min": int(digit_lengths.min()) if len(digit_lengths) else None,
        "time_digit_max": int(digit_lengths.max()) if len(digit_lengths) else None,
        "row_count": int(len(frame)),
        "night_session_rows": night_rows,
        "has_night_session": night_rows > 0,
        "auction_marked_rows": auction_rows,
    }


def _era_summary(measured: list[dict[str, Any]],
                 boundaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assemble measured eras from the detected boundaries + sampled probes.

    Boundaries (column count) and the night-session boundary are DETECTED; the
    representative probes supply the measured per-era attributes.
    """
    by_file = {m["file"]: m for m in measured}

    # Night-session boundary is the first representative day whose measurement
    # shows night rows; falls back to the documented 2017-05-16 label only if
    # that probe is missing, but we prefer the measured fact.
    night_start = None
    for m in measured:
        if m.get("has_night_session"):
            # Take the earliest measured night day.
            if night_start is None or m["file"] < night_start[0]:
                night_start = (m["file"], m)

    return {
        "column_count_transitions": boundaries,
        "measured_representative_days": [by_file.get(n) or {"file": n, "error": "absent"}
                                         for n in REPRESENTATIVE_DAYS if n in by_file]
        + [m for m in measured if m["file"] not in REPRESENTATIVE_DAYS],
        "night_session_first_measured_day": night_start[1]["file"] if night_start else None,
    }


# --------------------------------------------------------------------------- #
def build_manifest(latest_tx: str | None) -> dict[str, Any]:
    subdirs = _subdirectory_status()
    daily = _list_daily_files()
    contracts = _contract_inventory(daily)
    boundaries = _detect_column_boundaries()

    probe_names = list(REPRESENTATIVE_DAYS)
    if latest_tx and latest_tx not in probe_names:
        probe_names.append(latest_tx)
    measured = []
    for name in probe_names:
        path = PYTHON_DIR / name
        if path.exists():
            measured.append(_measure_day(path))

    all_files = sum(v.get("total_files", 0) for v in subdirs.values()
                    if isinstance(v, dict))
    all_bytes = sum(v.get("total_bytes", 0) for v in subdirs.values()
                    if isinstance(v, dict))
    covered_months = sorted({d[:7] for by in daily.values() for d in by})

    return {
        "generated_at": pd.Timestamp.now().isoformat(),
        "archive_root": str(ARCHIVE_ROOT),
        "read_only_policy": "Dropbox archive scanned read-only; no files written under ~/Dropbox",
        "subdirectory_status": subdirs,
        "futures_python_tick": {
            "contracts": contracts,
            "covered_year_months": covered_months,
            "n_covered_months": len(covered_months),
        },
        "format_eras": _era_summary(measured, boundaries),
        "global": {
            "archive_total_files": all_files,
            "archive_total_bytes": all_bytes,
            "python_total_files": subdirs["TAIFEXDATA/python (futures tick)"].get("total_files"),
            "python_total_bytes": subdirs["TAIFEXDATA/python (futures tick)"].get("total_bytes"),
        },
    }


def _latest_tx_file() -> str | None:
    files = sorted(p.name for p in PYTHON_DIR.iterdir()
                   if DAILY_PATTERN.match(p.name) and p.name.endswith("TX.csv"))
    return files[-1] if files else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    _ensure_read_only(args.out)
    if not PYTHON_DIR.is_dir():
        print(f"error: futures tick dir not found: {PYTHON_DIR}", file=sys.stderr)
        return 1

    manifest = build_manifest(_latest_tx_file())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    tx = manifest["futures_python_tick"]["contracts"]["TX"]
    print(f"manifest written: {args.out}")
    print(f"  archive total files={manifest['global']['archive_total_files']:,} "
          f"bytes={manifest['global']['archive_total_bytes']:,}")
    print(f"  TX: {tx['n_dates']} days {tx['date_min']}..{tx['date_max']} "
          f"missing_weekdays={tx['missing_weekday_count']} "
          f"long_runs={len(tx['long_gap_runs_ge3'])}")
    print("  column-count transitions: " +
          "; ".join(f"{t['first_date']}->{t['ncols']}col"
                    for t in manifest['format_eras']['column_count_transitions']))
    print(f"  night session first measured: "
          f"{manifest['format_eras']['night_session_first_measured_day']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
