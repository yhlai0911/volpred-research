#!/usr/bin/env python3
"""Convert raw TAIFEX daily tick CSVs into the canonical parquet tick layer.

Reads a single raw ``Daily_YYYY_MM_DD{TX|TX1|TX2}.csv`` (Big5/CP950, one of three
format eras), normalizes it to a stable canonical schema using the SAME
header-based era-normalization as ``collect_taifex_tick.py`` (imported, not
re-implemented, so the two layers cannot drift), validates it, and writes:

    data/intraday/taifex_tick/<contract>/<yyyymm>.parquet

where ``<contract>`` is the file variant TX (merged), TX1 (front month) or TX2
(second month).  Each monthly parquet accumulates every trading day of that
month for that variant.

Canonical schema (one row per tick):
    trade_date      int    YYYYMMDD
    symbol          str    商品代號 (e.g. TX)
    contract_month  str    到期月份(週別)
    trade_time      int    HHMMSS (raw; leading zeros may be dropped pre-2017)
    price           float  成交價
    volume          int    成交量 (B+S)
    near_price      float  近月價格 ('-' -> NaN)
    far_price       float  遠月價格 ('-' -> NaN)
    is_auction      bool   開盤集合競價 mark ('*'); False for the 9-col 2012 era
    is_night        bool   night session tick (15:00-05:00), 2017-05-16 onward
    timestamp       str    時間戳記 (raw)

Validation per day (rows>0; prices positive; trade_time in a legal session;
night flag only where night actually exists; auction share sane) is reported and
gates the write.

This fire validates only a REPRESENTATIVE SAMPLE across all three eras (plus
TX1).  A full 33G rebuild is heavy and must go through the compute queue:

    uv run python scripts/compute_queue.py enqueue \
        --script scripts/taifex_tick_to_canonical.py \
        --title "TAIFEX tick canonical full rebuild" -- --full-rebuild

Examples:
  uv run python scripts/taifex_tick_to_canonical.py --sample
  uv run python scripts/taifex_tick_to_canonical.py --file Daily_2017_05_16TX.csv
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

SOURCE_DIR = Path.home() / "Dropbox" / "TAIFEXDATA" / "TAIFEXDATA" / "python"
OUTPUT_ROOT = ROOT / "data" / "intraday" / "taifex_tick"

DAILY_PATTERN = re.compile(r"^Daily_(\d{4})_(\d{2})_(\d{2})(TX|TX1|TX2)\.csv$")

# The canonical layer keeps the near/far quote and raw timestamp that the RV
# collector discards, so its alias set is a superset of the collector's.
CANONICAL_ALIASES = {
    **collector.HEADER_ALIASES,
    "near_price": ("近月價格",),
    "far_price": ("遠月價格",),
    "timestamp": ("時間戳記",),
}
CANONICAL_REQUIRED = (
    "trade_date", "symbol", "contract", "trade_time", "price", "volume",
)

# The night session begins 2017-05-16; before it, night rows must not exist.
NIGHT_ERA_START = 20170516

CANONICAL_COLUMNS = [
    "trade_date", "symbol", "contract_month", "trade_time", "price", "volume",
    "near_price", "far_price", "is_auction", "is_night", "timestamp",
]


def parse_filename(name: str) -> tuple[int, str, str]:
    """Return (trade_date_int, variant, yyyymm) or raise on an unexpected name."""
    m = DAILY_PATTERN.match(name)
    if not m:
        raise collector.SourceFormatError(f"unexpected source filename: {name}")
    y, mo, d, variant = m.groups()
    return int(f"{y}{mo}{d}"), variant, f"{y}{mo}"


def read_canonical(path: Path) -> pd.DataFrame:
    """Read one raw daily file and normalize it to the canonical schema."""
    if not path.exists() or path.stat().st_size < collector.MIN_SOURCE_BYTES:
        raise collector.SourceFormatError(f"source file absent or empty: {path.name}")

    frame = None
    last_error: Exception | None = None
    for encoding in collector.SOURCE_ENCODINGS:
        try:
            head = pd.read_csv(path, encoding=encoding, nrows=0)
            mapping = collector.map_semantic_columns(
                head.columns, CANONICAL_ALIASES, CANONICAL_REQUIRED
            )
            usecols = list(dict.fromkeys(mapping.values()))
            raw = pd.read_csv(path, encoding=encoding, dtype=str,
                              usecols=usecols, low_memory=False)
            frame = raw.rename(columns={v: k for k, v in mapping.items()})
            break
        except (UnicodeDecodeError, UnicodeError, collector.SourceFormatError) as exc:
            last_error = exc
    if frame is None:
        raise collector.SourceFormatError(
            f"cannot decode/normalize {path.name}: {last_error}"
        )

    out = pd.DataFrame()
    out["trade_date"] = pd.to_numeric(frame["trade_date"], errors="coerce").astype("Int64")
    out["symbol"] = frame["symbol"].astype(str).str.strip()
    out["contract_month"] = frame["contract"].astype(str).str.strip()
    out["trade_time"] = pd.to_numeric(frame["trade_time"], errors="coerce").astype("Int64")
    out["price"] = pd.to_numeric(frame["price"], errors="coerce")
    out["volume"] = pd.to_numeric(frame["volume"], errors="coerce").astype("Int64")

    for src, dst in (("near_price", "near_price"), ("far_price", "far_price")):
        if src in frame:
            col = frame[src].astype(str).str.strip().replace({"-": None, "": None})
            out[dst] = pd.to_numeric(col, errors="coerce")
        else:
            out[dst] = pd.NA

    if "auction" in frame:
        out["is_auction"] = frame["auction"].astype(str).str.strip().eq("*")
    else:
        out["is_auction"] = False  # 9-column 2012 era has no auction column

    t = out["trade_time"]
    out["is_night"] = (
        (t >= collector.NIGHT_PM_START) | ((t > 0) & (t <= collector.NIGHT_AM_END))
    ).fillna(False)

    out["timestamp"] = frame["timestamp"].astype(str) if "timestamp" in frame else ""

    out = out.dropna(subset=["trade_date", "trade_time", "price", "volume"])
    return out[CANONICAL_COLUMNS].reset_index(drop=True)


def validate_day(frame: pd.DataFrame, trade_date: int) -> dict[str, Any]:
    """Validate one canonical trading day; return a report with a pass flag."""
    n = len(frame)
    t = frame["trade_time"].astype("int64")
    day_mask = t.between(collector.DAY_START, collector.DAY_END)
    night_mask = (t >= collector.NIGHT_PM_START) | ((t > 0) & (t <= collector.NIGHT_AM_END))
    auction = frame["is_auction"].fillna(False)
    # "Other" = neither day nor night, not an auction mark, and not the t==0
    # pre-open placeholder.  A healthy day has almost none.
    other = (~day_mask) & (~night_mask) & (~auction) & (t != 0)

    n_night = int(night_mask.sum())
    n_auction = int(auction.sum())
    n_other = int(other.sum())
    n_nonpos_price = int((frame["price"] <= 0).sum())
    other_frac = n_other / n if n else 0.0

    checks = {
        "rows_gt_0": n > 0,
        "all_prices_positive": n_nonpos_price == 0,
        "trade_time_in_session": other_frac < 0.01,
        "night_flag_consistent": (trade_date >= NIGHT_ERA_START) or (n_night == 0),
        "auction_share_sane": n_auction <= max(50, int(0.05 * n)),
    }
    return {
        "trade_date": trade_date,
        "rows": n,
        "day_rows": int(day_mask.sum()),
        "night_rows": n_night,
        "auction_rows": n_auction,
        "out_of_session_rows": n_other,
        "nonpositive_price_rows": n_nonpos_price,
        "contracts": int(frame["contract_month"].nunique()),
        "checks": checks,
        "passed": all(checks.values()),
    }


def _merge_parquet(path: Path, new: pd.DataFrame) -> pd.DataFrame:
    """Merge new rows into an existing monthly parquet, de-duplicating."""
    if path.exists():
        prior = pd.read_parquet(path)
        combined = pd.concat([prior, new], ignore_index=True)
    else:
        combined = new
    combined = combined.drop_duplicates(
        subset=["trade_date", "symbol", "contract_month", "trade_time",
                "price", "volume", "timestamp"]
    ).reset_index(drop=True)
    combined = combined.sort_values(
        ["trade_date", "trade_time"], kind="stable"
    ).reset_index(drop=True)
    return combined


def convert_file(name: str, *, write: bool = True) -> dict[str, Any]:
    """Convert one raw daily file, validate it, and (optionally) write parquet."""
    path = SOURCE_DIR / name
    trade_date, variant, yyyymm = parse_filename(name)
    frame = read_canonical(path)
    report = validate_day(frame, trade_date)
    report.update({"file": name, "variant": variant, "yyyymm": yyyymm})

    if write and report["passed"]:
        out_path = OUTPUT_ROOT / variant / f"{yyyymm}.parquet"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        merged = _merge_parquet(out_path, frame)
        merged.to_parquet(out_path, index=False)
        report["parquet"] = str(out_path)
        report["parquet_rows_after_merge"] = len(merged)
    return report


# Representative sample: every era boundary + a volatile recent day + TX1.
SAMPLE_FILES = [
    "Daily_2012_01_02TX.csv",   # era A: 9-col, day-only
    "Daily_2012_06_14TX.csv",   # era B first day: 10-col + auction
    "Daily_2014_01_02TX.csv",   # era B mid
    "Daily_2017_05_15TX.csv",   # era B last pre-night day
    "Daily_2017_05_16TX.csv",   # era C first day: night session appears
    "Daily_2020_03_16TX.csv",   # era C volatile (COVID crash) day
    "Daily_2026_07_14TX.csv",   # era C most recent day
    "Daily_2017_05_16TX1.csv",  # TX1 front-month, era C
    "Daily_2026_07_14TX1.csv",  # TX1 front-month, recent
]


def run_sample(write: bool = True) -> int:
    print(f"canonical output root: {OUTPUT_ROOT}")
    n_pass = 0
    reports = []
    for name in SAMPLE_FILES:
        if not (SOURCE_DIR / name).exists():
            print(f"  SKIP (absent): {name}")
            continue
        rep = convert_file(name, write=write)
        reports.append(rep)
        flag = "PASS" if rep["passed"] else "FAIL"
        n_pass += rep["passed"]
        print(f"  [{flag}] {name} rows={rep['rows']:,} day={rep['day_rows']:,} "
              f"night={rep['night_rows']:,} auction={rep['auction_rows']} "
              f"other={rep['out_of_session_rows']} contracts={rep['contracts']}"
              + (f" -> {rep.get('parquet')}" if rep.get('parquet') else ""))
        if not rep["passed"]:
            failed = [k for k, v in rep["checks"].items() if not v]
            print(f"        failed checks: {failed}")
    print(f"\nsample: {n_pass}/{len(reports)} days passed validation")
    return 0 if reports and n_pass == len(reports) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sample", action="store_true",
                   help="convert+validate the representative cross-era sample")
    g.add_argument("--file", help="convert a single Daily_*.csv by name")
    g.add_argument("--full-rebuild", action="store_true",
                   help="convert the WHOLE archive (heavy ~33G; run via compute_queue)")
    ap.add_argument("--no-write", action="store_true",
                    help="validate only; do not write parquet")
    args = ap.parse_args()

    if not SOURCE_DIR.is_dir():
        print(f"error: source dir not found: {SOURCE_DIR}", file=sys.stderr)
        return 1

    if args.sample:
        return run_sample(write=not args.no_write)
    if args.file:
        rep = convert_file(args.file, write=not args.no_write)
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        return 0 if rep["passed"] else 1
    if args.full_rebuild:
        files = sorted(p.name for p in SOURCE_DIR.iterdir()
                       if DAILY_PATTERN.match(p.name))
        print(f"full rebuild: {len(files):,} files. This is HEAVY (~33G).")
        n_pass = 0
        for i, name in enumerate(files, 1):
            try:
                rep = convert_file(name, write=not args.no_write)
                n_pass += rep["passed"]
            except Exception as exc:  # noqa: BLE001
                print(f"  [error] {name}: {exc}")
            if i % 250 == 0:
                print(f"  {i:,}/{len(files):,} processed")
        print(f"full rebuild: {n_pass:,}/{len(files):,} days passed")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
