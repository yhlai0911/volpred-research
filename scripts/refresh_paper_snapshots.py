"""Refresh paper/<id>/data/*.csv snapshots from yfinance / FRED.

Background: paper data snapshots (e.g. paper/garch-x-vix/data/spy_vix_*.csv,
paper/taiwan-vt/data/0050+...csv) are pinned per .claude/rules/paper-workflow.md
"data snapshot pinning" rule, but pinning was only enforced at original
authoring — there's no recurring refresh, so snapshots silently age 3-4 weeks
behind live data and reproducer drift surfaces in Table 1 audits (see
2026-05-04 Paper 9 summary_stats discrepancy).

This script:
1. Inventories paper/<id>/data/*.csv files matching known yfinance/FRED schemas
2. For each file, infers tickers from filename + columns
3. Re-downloads via yfinance auto_adjust=False (paper-workflow.md hard rule)
4. Writes back if endpoint date > current last entry; preserves all
   pre-existing rows (idempotent: same data → no diff)
5. Reports per-file old-last vs new-last + n new rows

Usage:
  uv run python scripts/refresh_paper_snapshots.py --dry-run
  uv run python scripts/refresh_paper_snapshots.py --apply
  uv run python scripts/refresh_paper_snapshots.py --apply --paper garch-x-vix
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PAPER_ROOT = ROOT / "paper"
sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.scheduled_writer_commit import (  # noqa: E402
    commit_owned_outputs,
    dirty_paths_before_write,
    writable_output_paths,
)
from volpred.ops.shared_lock import shared_state_lock  # noqa: E402


def _rel(csv_path: Path) -> str:
    """Repo-relative path, tolerating paths outside the checkout (tests)."""
    try:
        return csv_path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return csv_path.resolve().as_posix().lstrip("/")


def _snapshot_lock_name(csv_path: Path) -> str:
    """Per-file lock key. Flattened relpath so two papers never collide."""
    return "paper_snapshot_" + re.sub(r"[^A-Za-z0-9_.-]", "_", _rel(csv_path))


def _read_dates(csv_path: Path) -> list[str]:
    """Date column as raw strings, in file order. Cheap: no full parse."""
    with csv_path.open("r", encoding="utf-8") as fp:
        rows = fp.read().splitlines()
    return [line.split(",", 1)[0] for line in rows[1:] if line.strip()]


def _duplicate_dates(dates: list[str]) -> list[str]:
    seen: set[str] = set()
    dups: list[str] = []
    for d in dates:
        if d in seen and d not in dups:
            dups.append(d)
        seen.add(d)
    return dups

# Per paper-workflow.md: yfinance pulls MUST use auto_adjust=False so
# unadjusted close + adj_close coexist in the same snapshot. Splits/divs
# applied after-the-fact would silently change historical values otherwise.
YF_AUTO_ADJUST = False

# Filename → ticker inference. Keep simple: split on `_` and recognize
# common ticker tokens. Files outside this whitelist are reported as
# "skipped: unknown schema" rather than guessed.
KNOWN_TICKERS = {
    "spy", "vix", "qqq", "eem", "fez",
    "gld", "gvz", "uso", "ovx",
    "tlt", "dia", "iwm",
    "0050", "twii", "2330", "2317", "2454", "0056",
}


def _infer_tickers_from_filename(name: str) -> list[str]:
    """spy_vix_qqq_eem_fez_2000-2026.csv → ['spy','vix','qqq','eem','fez']"""
    stem = Path(name).stem.lower()
    # Strip date range suffix like _2000-2026
    stem = re.sub(r"_\d{4}-\d{4}$", "", stem)
    parts = re.split(r"[_+\-]", stem)
    tickers: list[str] = []
    for p in parts:
        if p in KNOWN_TICKERS:
            tickers.append(p)
    return tickers


FROZEN_TOKENS = ("snapshot", "frozen", "pinned", "locked", "errata", "v1", "v2")


def _filename_end_year(name: str) -> int | None:
    """Return end-year from any `_YYYY-YYYY` segment in stem, else None.

    Filenames like `spy_vix_..._2000-2026.csv` carry the *intended* sample
    period. We scan the WHOLE stem (not just suffix) so mid-stem patterns
    like `spy_gld_2006-2024_rebal_snapshot.csv` are caught. If multiple
    year-ranges appear (rare), the LAST is taken (rightmost = most recent
    intent).

    If end_year < current year, the pin is deliberate (frozen sample) and
    we MUST NOT auto-extend — doing so would silently change published /
    in-review results. Files without any year-range segment are assumed
    live / refreshable.

    Additional safety: if ANY filename token in FROZEN_TOKENS appears, we
    treat as frozen regardless of year (defense for un-dated snapshots).
    """
    stem = Path(name).stem.lower()
    for token in FROZEN_TOKENS:
        if token in stem:
            return 0  # sentinel: frozen-by-token, never refresh
    matches = list(re.finditer(r"(\d{4})-(\d{4})", stem))
    if not matches:
        return None
    return int(matches[-1].group(2))


def _yf_symbol(token: str) -> str:
    """Map filename token → yfinance symbol."""
    mapping = {
        "vix": "^VIX",
        "vix3m": "^VIX3M",
        "vxn": "^VXN",
        "ovx": "^OVX",
        "gvz": "^GVZ",
        "n225": "^N225",
        "twii": "^TWII",
        "0050": "0050.TW",
        "0056": "0056.TW",
        "2330": "2330.TW",
        "2317": "2317.TW",
        "2454": "2454.TW",
    }
    return mapping.get(token, token.upper())


def _refresh_yf_snapshot(csv_path: Path, *, dry_run: bool) -> dict:
    """Re-fetch CSV from yfinance based on filename inference."""
    tickers = _infer_tickers_from_filename(csv_path.name)
    if not tickers:
        return {"file": str(csv_path.relative_to(ROOT)), "skipped": "unknown_schema"}

    # Honor filename end-year pin: never auto-extend a frozen-sample CSV.
    end_year = _filename_end_year(csv_path.name)
    current_year = datetime.now(timezone.utc).year
    if end_year == 0:
        return {
            "file": str(csv_path.relative_to(ROOT)),
            "skipped": "frozen_by_token",
        }
    if end_year is not None and end_year < current_year:
        return {
            "file": str(csv_path.relative_to(ROOT)),
            "skipped": f"frozen_sample_end_{end_year}",
        }

    header = list(pd.read_csv(csv_path, nrows=0).columns)
    if "date" not in [c.lower() for c in header]:
        return {
            "file": str(csv_path.relative_to(ROOT)),
            "skipped": f"non_date_indexed_schema (header[0]={header[0] if header else '?'})",
        }
    df_old = pd.read_csv(csv_path, parse_dates=["date"])
    old_last = df_old["date"].max()
    old_first = df_old["date"].min()
    if pd.isna(old_last):
        return {"file": str(csv_path.relative_to(ROOT)), "skipped": "empty_csv"}

    try:
        import yfinance as yf  # local import — heavy
    except ImportError:
        return {"file": str(csv_path.relative_to(ROOT)), "error": "yfinance_not_installed"}

    yf_symbols = [_yf_symbol(t) for t in tickers]
    end_date = datetime.now(timezone.utc).date().isoformat()
    start_date = old_first.date().isoformat()

    try:
        # Use group_by='ticker' to keep per-ticker columns stable
        raw = yf.download(
            yf_symbols,
            start=start_date,
            end=end_date,
            auto_adjust=YF_AUTO_ADJUST,
            progress=False,
            group_by="ticker",
            threads=False,
        )
    except Exception as exc:
        return {"file": str(csv_path.relative_to(ROOT)), "error": f"yf_download:{exc}"}

    if raw is None or raw.empty:
        return {"file": str(csv_path.relative_to(ROOT)), "error": "yf_empty"}

    # Flatten the MultiIndex (ticker, OHLCV) → columns matching original schema
    # `<ticker>_<field>` lower-case (e.g. spy_adj_close, vix_close).
    flat = pd.DataFrame()
    for sym in yf_symbols:
        if sym not in (raw.columns.get_level_values(0).unique() if hasattr(raw.columns, "get_level_values") else [sym]):
            continue
        sub = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
        token = next(t for t in tickers if _yf_symbol(t) == sym)
        for field in ("Open", "High", "Low", "Close", "Adj Close", "Volume"):
            if field in sub.columns:
                colname = f"{token}_{field.lower().replace(' ', '_')}"
                flat[colname] = sub[field]
    flat.index.name = "date"
    flat = flat.reset_index()
    flat["date"] = pd.to_datetime(flat["date"]).dt.tz_localize(None)

    new_last = flat["date"].max()
    n_added = int((flat["date"] > old_last).sum())

    result = {
        "file": str(csv_path.relative_to(ROOT)),
        "tickers": tickers,
        "old_last": str(old_last.date()),
        "new_last": str(new_last.date()) if pd.notna(new_last) else None,
        "n_old_rows": len(df_old),
        "n_new_rows": len(flat),
        "n_added": n_added,
    }

    if dry_run:
        result["dry_run"] = True
        return result

    if n_added == 0:
        result["written"] = False
        return result

    # Everything above (yfinance download) is slow and side-effect free, so it
    # runs unlocked. Everything below re-reads and mutates the CSV, so it must
    # hold the per-file lock: `old_last` was read minutes ago, before the
    # download, and a concurrent refresh may have appended in the meantime.
    # Without the lock both processes see the same stale `old_last`, both
    # append the same block, and the file ends up with byte-identical duplicate
    # dates (K1685 found 2026-05-04..05-15 doubled in the Paper 9 snapshot).
    with shared_state_lock(_snapshot_lock_name(csv_path)):
        return _append_new_rows_locked(csv_path, flat, list(df_old.columns), result)


def _append_new_rows_locked(
    csv_path: Path, flat: pd.DataFrame, target_cols: list[str], result: dict
) -> dict:
    """Append strictly-new dated rows. Caller MUST hold the per-file lock."""
    # Fail closed on a contaminated file: appending to it would bury the
    # damage under more rows and every consumer keeps reading dupes. Repair
    # via --repair-duplicates first.
    dates_before = _read_dates(csv_path)
    preexisting_dupes = _duplicate_dates(dates_before)
    if preexisting_dupes:
        result["written"] = False
        result["error"] = (
            f"preexisting_duplicate_dates:{len(preexisting_dupes)} "
            f"(first={preexisting_dupes[0]}) — run --repair-duplicates"
        )
        return result

    # Re-read the boundary UNDER the lock. This is the value that matters;
    # the pre-download `old_last` is only a dry-run estimate.
    current_last = pd.Timestamp(max(dates_before)) if dates_before else None
    existing = set(dates_before)

    # APPEND-ONLY policy (2026-05-04 hard rule): paper reproduction depends
    # on byte-stable historical rows. yfinance refetch can return values
    # that differ in low-significance digits even for old dates (rounding,
    # adjustment timing) and pandas to_csv float-format also loses
    # precision on round-trip. So we DO NOT rewrite existing rows at all — we
    # open the CSV in text-append mode and write only NEW rows after the
    # existing last date.
    new_only = flat if current_last is None else flat[flat["date"] > current_last]
    new_only = new_only.copy()
    new_only["_date_str"] = new_only["date"].dt.strftime("%Y-%m-%d")
    # Belt and braces: drop anything already on file (a date can be present
    # out of order) and any dupes inside the fetched frame itself.
    new_only = new_only[~new_only["_date_str"].isin(existing)]
    new_only = new_only.drop_duplicates(subset="_date_str", keep="first")
    new_only = new_only.sort_values("date")

    if new_only.empty:
        result["written"] = False
        result["append_only_note"] = "no_strictly_new_dates"
        result["n_added"] = 0
        return result

    aligned = pd.DataFrame()
    for col in target_cols:
        aligned[col] = new_only[col] if col in new_only.columns else pd.NA
    aligned["date"] = new_only["_date_str"].values
    aligned = aligned[target_cols]

    # Write rows verbatim using csv module — bypass pandas float-format.
    # New rows use yfinance's default float repr; old rows are untouched
    # so their original float repr survives.
    import csv as _csv
    size_before = csv_path.stat().st_size
    with csv_path.open("a", newline="", encoding="utf-8") as fp:
        writer = _csv.writer(fp)
        for _, row in aligned.iterrows():
            writer.writerow(["" if pd.isna(v) else v for v in row.tolist()])
        fp.flush()

    # Post-write verification, still under the lock: if we somehow produced a
    # duplicate date, roll the file back to its exact pre-append bytes rather
    # than leave a corrupt snapshot on disk.
    dupes_after = _duplicate_dates(_read_dates(csv_path))
    if dupes_after:
        with csv_path.open("r+", encoding="utf-8") as fp:
            fp.truncate(size_before)
        result["written"] = False
        result["error"] = f"post_write_duplicate_dates:{dupes_after} — rolled back"
        return result

    result["written"] = True
    result["append_only_appended"] = len(aligned)
    result["n_added"] = len(aligned)
    return result


def _repair_duplicate_dates(csv_path: Path, *, dry_run: bool) -> dict:
    """Drop byte-identical duplicate rows, keeping the first occurrence.

    Only safe when the dupes are byte-identical: that is the signature of the
    concurrent double-append, and dropping a byte-identical copy leaves every
    surviving row exactly as originally written (append-only policy intact).
    Non-identical dupes mean something else went wrong — refuse and report.
    """
    rel = _rel(csv_path)
    with shared_state_lock(_snapshot_lock_name(csv_path)):
        text = csv_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if not lines:
            return {"file": rel, "skipped": "empty_csv"}
        header, body = lines[0], [l for l in lines[1:] if l.strip()]

        by_date: dict[str, list[str]] = {}
        for line in body:
            by_date.setdefault(line.split(",", 1)[0], []).append(line)
        dupes = {d: rows for d, rows in by_date.items() if len(rows) > 1}
        if not dupes:
            return {"file": rel, "repaired": False, "note": "no_duplicate_dates"}

        conflicting = {d: rows for d, rows in dupes.items() if len(set(rows)) > 1}
        if conflicting:
            return {
                "file": rel,
                "repaired": False,
                "error": (
                    f"non_identical_duplicate_dates:{sorted(conflicting)} — "
                    "not a double-append; needs manual adjudication"
                ),
            }

        kept: list[str] = []
        seen: set[str] = set()
        for line in body:
            date = line.split(",", 1)[0]
            if date in seen:
                continue
            seen.add(date)
            kept.append(line)

        report = {
            "file": rel,
            "duplicate_dates": sorted(dupes),
            "rows_before": len(body),
            "rows_after": len(kept),
            "rows_dropped": len(body) - len(kept),
        }
        if dry_run:
            report["dry_run"] = True
            report["repaired"] = False
            return report

        tmp = csv_path.with_suffix(csv_path.suffix + ".repair.tmp")
        tmp.write_text("\n".join([header, *kept]) + "\n", encoding="utf-8")
        tmp.replace(csv_path)

        remaining = _duplicate_dates(_read_dates(csv_path))
        if remaining:  # pragma: no cover — defensive
            report["repaired"] = False
            report["error"] = f"still_duplicated_after_repair:{remaining}"
            return report
        report["repaired"] = True
        return report


def _iter_paper_csvs(paper_filter: str | None) -> list[Path]:
    csvs: list[Path] = []
    for paper_dir in sorted(PAPER_ROOT.iterdir()):
        if not paper_dir.is_dir():
            continue
        if paper_filter and paper_dir.name != paper_filter:
            continue
        data_dir = paper_dir / "data"
        if not data_dir.exists():
            continue
        for csv in sorted(data_dir.glob("*.csv")):
            csvs.append(csv)
    return csvs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report only, no writes")
    parser.add_argument("--apply", action="store_true", help="write refreshed CSVs")
    parser.add_argument("--paper", default=None, help="restrict to one paper (e.g. garch-x-vix)")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    parser.add_argument(
        "--repair-duplicates",
        action="store_true",
        help="drop byte-identical duplicate-date rows left by a concurrent double-append",
    )
    args = parser.parse_args()

    if not (args.dry_run or args.apply):
        print("error: must specify --dry-run or --apply", file=sys.stderr)
        return 2

    csvs = _iter_paper_csvs(args.paper)

    if args.repair_duplicates:
        reports = [_repair_duplicate_dates(c, dry_run=args.dry_run) for c in csvs]
        touched = [r for r in reports if r.get("duplicate_dates") or "error" in r]
        if args.json:
            print(json.dumps({"results": touched}, ensure_ascii=False, indent=2))
        else:
            print(f"[repair] checked={len(reports)} affected={len(touched)}")
            for r in touched:
                if "error" in r:
                    print(f"  ERROR  {r['file']}: {r['error']}")
                else:
                    verb = "WOULD-DROP" if r.get("dry_run") else "DROPPED"
                    print(f"  {verb} {r['file']}: {r['rows_dropped']} row(s), "
                          f"dates={r['duplicate_dates']}")
        return 1 if any("error" in r for r in touched) else 0
    dirty_before = (
        dirty_paths_before_write(ROOT, csvs, label="refresh") if args.apply else frozenset()
    )
    writable_paths = set(
        writable_output_paths(
            ROOT,
            csvs,
            dirty_before=dirty_before,
            label="refresh",
        )
        if args.apply
        else ()
    )
    results = []
    for csv in csvs:
        if args.apply and csv.relative_to(ROOT).as_posix() not in writable_paths:
            results.append({
                "file": str(csv.relative_to(ROOT)),
                "skipped": "preexisting_dirty_output",
            })
            continue
        results.append(_refresh_yf_snapshot(csv, dry_run=args.dry_run))

    summary = {
        "checked": len(results),
        "skipped": sum(1 for r in results if "skipped" in r),
        "errors": sum(1 for r in results if "error" in r),
        "would_update": sum(1 for r in results if r.get("dry_run") and r.get("n_added", 0) > 0),
        "written": sum(1 for r in results if r.get("written") is True),
    }
    payload = {"summary": summary, "results": results}

    if args.apply:
        written = [csv for csv, r in zip(csvs, results) if r.get("written")]
        commit_owned_outputs(
            ROOT,
            written,
            dirty_before=dirty_before,
            message=f"chore(paper-data): refresh {len(written)} snapshot CSV(s)",
            label="refresh",
        )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"[refresh] checked={summary['checked']} "
              f"skipped={summary['skipped']} errors={summary['errors']} "
              f"would_update={summary['would_update']} written={summary['written']}")
        for r in results:
            if "error" in r:
                print(f"  ERROR  {r['file']}: {r['error']}")
            elif "skipped" in r:
                print(f"  SKIP   {r['file']}: {r['skipped']}")
            elif r.get("n_added", 0) > 0:
                action = "WROTE" if r.get("written") else "WOULD-WRITE"
                print(f"  {action} {r['file']}: {r['old_last']} → {r['new_last']} (+{r['n_added']} rows)")
            else:
                print(f"  fresh  {r['file']}: {r['old_last']} (no new data)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
