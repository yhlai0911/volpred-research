#!/usr/bin/env python3
"""Collect Taiwan business-cycle indicators from the official NDC tables.

The NDC site is an Angular application whose data request is protected against
plain HTTP clients.  This collector launches an installed Chrome through
Playwright, reads the rendered official tables, validates their schema, stores
the exact source snapshot, atomically upserts the canonical CSV, and reads the
written values back.

NDC normally publishes on the 27th with an approximately two-month lag.

Usage:
    uv run python scripts/collect_ndc_bci.py
    uv run python scripts/collect_ndc_bci.py --check
    uv run python scripts/collect_ndc_bci.py --force
    uv run python scripts/collect_ndc_bci.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volpred.ops.scheduled_writer_commit import (  # noqa: E402
    commit_owned_outputs,
    dirty_paths_before_write,
    writable_output_paths,
)

BCI_PATH = PROJECT_ROOT / "storage" / "macro" / "tw_dgbas_bci_m.csv"
SOURCE_SNAPSHOT_PATH = (
    PROJECT_ROOT / "storage" / "macro" / "ndc_bci_source_latest.json"
)

NDC_ORIGIN = "https://index.ndc.gov.tw"
PERIOD_RE = re.compile(r"^(?P<year>\d{4})-(?P<month>0[1-9]|1[0-2])$")
CANONICAL_PERIOD_RE = re.compile(r"^(?P<year>\d{4})M(?P<month>0[1-9]|1[0-2])$")


class NdcCollectionError(RuntimeError):
    """Raised when the official source cannot be validated safely."""


@dataclass(frozen=True)
class SeriesSpec:
    key: str
    item: str
    unit: str
    source_url: str
    source_code: str
    source_name: str
    source_unit: str
    caption: str
    headers: tuple[str, ...]
    value_column: int
    decimal_places: int | None = None


NDC_DATA_PAGE = f"{NDC_ORIGIN}/n/zh_tw/data/eco/indicators_table1"
NDC_DATA_ENDPOINT = f"{NDC_ORIGIN}/n/json/data/eco/indicators"
SERIES_SPECS = (
    SeriesSpec(
        key="leading_indicator",
        item="景氣領先指標不含趨勢指數(點)",
        # The canonical CSV already carries the unit in ``item`` and historically
        # stores this base series with an empty unit column.
        unit="",
        source_url=f"{NDC_ORIGIN}/n/zh_tw/data/eco/indicators_table2",
        source_code="SR0051",
        source_name="領先指標不含趨勢指數",
        source_unit="(點)",
        caption="領先指標",
        headers=("年月", "領先指標不含趨勢指數(點)"),
        value_column=1,
        decimal_places=2,
    ),
    SeriesSpec(
        key="signal_score",
        item="景氣對策信號(分)",
        unit="",
        source_url=f"{NDC_ORIGIN}/n/zh_tw/data/eco/indicators_table1",
        source_code="SR0005",
        source_name="景氣對策信號",
        source_unit="(分)",
        caption="景氣對策信號",
        headers=("年月", "景氣對策信號(燈號)", "景氣對策信號(分)"),
        value_column=2,
        decimal_places=1,
    ),
)
SPEC_BY_KEY = {spec.key: spec for spec in SERIES_SPECS}


def _period_key(value: str | None) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    match = CANONICAL_PERIOD_RE.fullmatch(value)
    if match is None:
        return None
    return int(match.group("year")), int(match.group("month"))


def _canonical_period(value: str) -> str:
    match = PERIOD_RE.fullmatch(value.strip())
    if match is None:
        raise NdcCollectionError(f"invalid NDC period: {value!r}")
    return f"{match.group('year')}M{match.group('month')}"


def _expected_period(target_date: date) -> str:
    month = target_date.month - 2
    year = target_date.year
    if month <= 0:
        month += 12
        year -= 1
    return f"{year}M{month:02d}"


def _numeric_text(value: str, *, decimal_places: int | None) -> str:
    raw = value.strip().replace(",", "")
    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise NdcCollectionError(f"invalid NDC numeric value: {value!r}") from exc
    if not number.is_finite():
        raise NdcCollectionError(f"non-finite NDC numeric value: {value!r}")
    if decimal_places is not None:
        quantum = Decimal(1).scaleb(-decimal_places)
        return format(number.quantize(quantum), f".{decimal_places}f")
    normalized = format(number.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def _latest_period_for_item(csv_path: Path, item_name: str) -> str | None:
    latest_key: tuple[int, int] | None = None
    latest_text: str | None = None
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("item") != item_name:
                continue
            period = row.get("period")
            key = _period_key(period)
            if key is not None and (latest_key is None or key > latest_key):
                latest_key = key
                latest_text = period
    return latest_text


def freshness_report(
    csv_path: Path = BCI_PATH,
    *,
    target_date: date | None = None,
) -> dict[str, Any]:
    target = target_date or datetime.now().date()
    expected = _expected_period(target)
    expected_key = _period_key(expected)
    series: dict[str, Any] = {}
    if not csv_path.exists():
        for spec in SERIES_SPECS:
            series[spec.key] = {
                "item": spec.item,
                "latest_period": None,
                "fresh": False,
            }
        return {
            "path": str(csv_path),
            "expected_period": expected,
            "fresh": False,
            "available": False,
            "series": series,
        }

    for spec in SERIES_SPECS:
        latest = _latest_period_for_item(csv_path, spec.item)
        latest_key = _period_key(latest)
        series[spec.key] = {
            "item": spec.item,
            "latest_period": latest,
            "fresh": bool(
                latest_key is not None
                and expected_key is not None
                and latest_key >= expected_key
            ),
        }
    return {
        "path": str(csv_path),
        "expected_period": expected,
        "fresh": all(value["fresh"] for value in series.values()),
        "available": True,
        "series": series,
    }


def _chrome_executable(explicit: str | None = None) -> str | None:
    candidates = [
        explicit,
        os.environ.get("NDC_CHROME_EXECUTABLE"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return None


def _source_period(value: str) -> str:
    if not re.fullmatch(r"\d{6}", value):
        raise NdcCollectionError(f"invalid NDC API period: {value!r}")
    return _canonical_period(f"{value[:4]}-{value[4:]}")


def _table_from_api_payload(payload: dict[str, Any], spec: SeriesSpec) -> dict[str, Any]:
    line = payload.get("line")
    if not isinstance(line, dict):
        raise NdcCollectionError("NDC API response has no line registry")
    matches = [
        value
        for value in line.values()
        if isinstance(value, dict) and value.get("code") == spec.source_code
    ]
    if len(matches) != 1:
        raise NdcCollectionError(
            f"{spec.key} source code {spec.source_code} matched {len(matches)} series"
        )
    source = matches[0]
    if source.get("name") != spec.source_name or source.get("unit") != spec.source_unit:
        raise NdcCollectionError(
            f"{spec.key} source metadata mismatch: "
            f"name={source.get('name')!r} unit={source.get('unit')!r}"
        )
    data = source.get("data")
    if not isinstance(data, list):
        raise NdcCollectionError(f"{spec.key} source data is not a list")

    rows: list[list[str]] = []
    for point in data:
        if not isinstance(point, dict) or point.get("y") is None:
            continue
        period = _source_period(str(point.get("x") or ""))
        display_period = f"{period[:4]}-{period[5:]}"
        value = _numeric_text(
            str(point["y"]),
            decimal_places=spec.decimal_places,
        )
        if spec.value_column == 1:
            rows.append([display_period, value])
        else:
            rows.append([display_period, "", value])
    if not rows:
        raise NdcCollectionError(f"{spec.key} source contains no numeric observations")
    rows.sort(key=lambda row: _period_key(_canonical_period(row[0])) or (0, 0))
    return {
        "key": spec.key,
        "item": spec.item,
        "unit": spec.unit,
        "freq": "M",
        "source_url": spec.source_url,
        "source_endpoint": NDC_DATA_ENDPOINT,
        "source_code": spec.source_code,
        "source_name": spec.source_name,
        "source_unit": spec.source_unit,
        "caption": spec.caption,
        "headers": list(spec.headers),
        "rows": rows,
    }


def fetch_ndc_tables(
    *,
    chrome_executable: str | None = None,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Fetch both required official tables with a real browser engine."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise NdcCollectionError(
            "Playwright is required; install the project development dependencies"
        ) from exc

    executable = _chrome_executable(chrome_executable)
    observed = (captured_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload: dict[str, Any] | None = None
    with sync_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {
            "headless": True,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if executable:
            launch_kwargs["executable_path"] = executable
        else:
            launch_kwargs["channel"] = "chrome"
        try:
            browser = playwright.chromium.launch(**launch_kwargs)
        except Exception as exc:
            raise NdcCollectionError(f"cannot launch Chrome: {exc}") from exc
        try:
            failures: list[str] = []
            for attempt in range(1, 4):
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"
                    )
                )
                page = context.new_page()
                try:
                    with page.expect_response(
                        lambda response: response.url == NDC_DATA_ENDPOINT,
                        timeout=30_000,
                    ) as response_info:
                        page.goto(
                            NDC_DATA_PAGE,
                            wait_until="domcontentloaded",
                            timeout=30_000,
                        )
                    response = response_info.value
                    if response.status != 200:
                        raise NdcCollectionError(
                            f"NDC API returned HTTP {response.status}"
                        )
                    candidate = response.json()
                    if not isinstance(candidate, dict):
                        raise NdcCollectionError("NDC API response is not an object")
                    payload = candidate
                    break
                except Exception as exc:
                    failures.append(f"attempt {attempt}: {exc}")
                finally:
                    context.close()
            if payload is None:
                raise NdcCollectionError(
                    "NDC API response was not observed after 3 attempts; "
                    + " | ".join(failures)
                )
        except Exception as exc:
            raise NdcCollectionError(f"NDC browser fetch failed: {exc}") from exc
        finally:
            browser.close()

    tables = [_table_from_api_payload(payload, spec) for spec in SERIES_SPECS]
    revision_notice: list[str] = []
    memo = payload.get("memo")
    if isinstance(memo, dict):
        for section in memo.values():
            if not isinstance(section, dict):
                continue
            entries = section.get("li")
            if isinstance(entries, list):
                revision_notice.extend(
                    str(entry).strip() for entry in entries if str(entry).strip()
                )
    snapshot = {
        "schema_version": 1,
        "source": "National Development Council Business Indicators DataBase",
        "source_origin": NDC_ORIGIN,
        "captured_at": observed.isoformat(),
        "collector": "scripts/collect_ndc_bci.py",
        "transport": "playwright_chrome_official_json_response",
        "source_endpoint": NDC_DATA_ENDPOINT,
        "source_latest_date": payload.get("latest_date"),
        "source_revision_notice": revision_notice,
        "tables": tables,
    }
    validate_snapshot(snapshot)
    snapshot["content_sha256"] = _snapshot_content_sha256(snapshot)
    return snapshot


def _snapshot_content_sha256(snapshot: dict[str, Any]) -> str:
    payload = {key: value for key, value in snapshot.items() if key != "content_sha256"}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    if snapshot.get("schema_version") != 1:
        raise NdcCollectionError("unsupported NDC snapshot schema")
    if snapshot.get("source_origin") != NDC_ORIGIN:
        raise NdcCollectionError("NDC snapshot source origin mismatch")
    if snapshot.get("source_endpoint") != NDC_DATA_ENDPOINT:
        raise NdcCollectionError("NDC snapshot endpoint mismatch")
    revision_notice = snapshot.get("source_revision_notice")
    if not isinstance(revision_notice, list) or not revision_notice:
        raise NdcCollectionError("NDC snapshot has no revision notice")
    tables = snapshot.get("tables")
    if not isinstance(tables, list) or len(tables) != len(SERIES_SPECS):
        raise NdcCollectionError("NDC snapshot must contain both required tables")

    seen_keys: set[str] = set()
    for table in tables:
        if not isinstance(table, dict):
            raise NdcCollectionError("NDC snapshot table must be an object")
        key = table.get("key")
        spec = SPEC_BY_KEY.get(key)
        if spec is None or key in seen_keys:
            raise NdcCollectionError(f"unexpected or duplicate NDC series: {key!r}")
        seen_keys.add(key)
        if table.get("source_url") != spec.source_url:
            raise NdcCollectionError(f"{key} source URL mismatch")
        if table.get("source_endpoint") != NDC_DATA_ENDPOINT:
            raise NdcCollectionError(f"{key} source endpoint mismatch")
        if table.get("source_code") != spec.source_code:
            raise NdcCollectionError(f"{key} source code mismatch")
        if table.get("source_name") != spec.source_name:
            raise NdcCollectionError(f"{key} source name mismatch")
        if table.get("source_unit") != spec.source_unit:
            raise NdcCollectionError(f"{key} source unit mismatch")
        if table.get("caption") != spec.caption:
            raise NdcCollectionError(f"{key} caption mismatch")
        if tuple(table.get("headers") or ()) != spec.headers:
            raise NdcCollectionError(f"{key} headers mismatch")
        if table.get("item") != spec.item or table.get("freq") != "M":
            raise NdcCollectionError(f"{key} canonical metadata mismatch")
        rows = table.get("rows")
        if not isinstance(rows, list) or not rows:
            raise NdcCollectionError(f"{key} has no source rows")

        previous: tuple[int, int] | None = None
        observed_periods: set[str] = set()
        for row in rows:
            if not isinstance(row, list) or len(row) != len(spec.headers):
                raise NdcCollectionError(f"{key} row width mismatch: {row!r}")
            period = _canonical_period(str(row[0]))
            period_key = _period_key(period)
            if period in observed_periods:
                raise NdcCollectionError(f"{key} duplicate period: {period}")
            if previous is not None and period_key is not None and period_key <= previous:
                raise NdcCollectionError(f"{key} periods are not strictly increasing")
            observed_periods.add(period)
            previous = period_key
            _numeric_text(
                str(row[spec.value_column]),
                decimal_places=spec.decimal_places,
            )

    expected_keys = set(SPEC_BY_KEY)
    if seen_keys != expected_keys:
        raise NdcCollectionError(
            f"NDC snapshot series mismatch: expected={sorted(expected_keys)} "
            f"observed={sorted(seen_keys)}"
        )

    expected_hash = snapshot.get("content_sha256")
    if expected_hash is not None and expected_hash != _snapshot_content_sha256(snapshot):
        raise NdcCollectionError("NDC snapshot content hash mismatch")


def _snapshot_updates(snapshot: dict[str, Any]) -> dict[tuple[str, str], dict[str, str]]:
    updates: dict[tuple[str, str], dict[str, str]] = {}
    for table in snapshot["tables"]:
        spec = SPEC_BY_KEY[table["key"]]
        for row in table["rows"]:
            period = _canonical_period(str(row[0]))
            updates[(spec.item, period)] = {
                "item": spec.item,
                "unit": spec.unit,
                "freq": "M",
                "period": period,
                "value": _numeric_text(
                    str(row[spec.value_column]),
                    decimal_places=spec.decimal_places,
                ),
            }
    return updates


def _atomic_write_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["item", "unit", "freq", "period", "value"],
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:  # silent-ok: replace/remove already consumed temp
            pass
        raise


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:  # silent-ok: replace/remove already consumed temp
            pass
        raise


def apply_snapshot(
    csv_path: Path,
    snapshot: dict[str, Any],
    *,
    snapshot_path: Path | None = None,
) -> dict[str, Any]:
    """Validate, atomically upsert, and read back one official snapshot."""
    validate_snapshot(snapshot)
    updates = _snapshot_updates(snapshot)
    if not csv_path.exists():
        existing_rows: list[dict[str, str]] = []
    else:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["item", "unit", "freq", "period", "value"]:
                raise NdcCollectionError(
                    f"unexpected canonical CSV schema: {reader.fieldnames!r}"
                )
            existing_rows = [dict(row) for row in reader]

    target_items = {spec.item for spec in SERIES_SPECS}
    target_groups: dict[str, dict[str, dict[str, str]]] = {
        item: {} for item in target_items
    }
    first_target_index: dict[str, int] = {}
    output_skeleton: list[dict[str, str] | tuple[str, str]] = []
    duplicate_keys: set[tuple[str, str]] = set()

    for row in existing_rows:
        item = row.get("item", "")
        period = row.get("period", "")
        if item not in target_items:
            output_skeleton.append(row)
            continue
        key = (item, period)
        if period in target_groups[item]:
            duplicate_keys.add(key)
            continue
        target_groups[item][period] = row
        if item not in first_target_index:
            first_target_index[item] = len(output_skeleton)
            output_skeleton.append(("target_group", item))

    if duplicate_keys:
        raise NdcCollectionError(
            f"duplicate canonical CSV keys: {sorted(duplicate_keys)!r}"
        )

    inserted = 0
    revised = 0
    unchanged = 0
    for key, incoming in updates.items():
        item, period = key
        previous = target_groups[item].get(period)
        if previous is None:
            inserted += 1
        elif previous != incoming:
            revised += 1
        else:
            unchanged += 1
        target_groups[item][period] = incoming

    for item in target_items:
        if item not in first_target_index:
            output_skeleton.append(("target_group", item))

    output_rows: list[dict[str, str]] = []
    emitted_groups: set[str] = set()
    for entry in output_skeleton:
        if isinstance(entry, dict):
            output_rows.append(entry)
            continue
        _, item = entry
        if item in emitted_groups:
            continue
        emitted_groups.add(item)
        group_rows = list(target_groups[item].values())
        group_rows.sort(key=lambda row: _period_key(row.get("period")) or (0, 0))
        output_rows.extend(group_rows)

    _atomic_write_csv(csv_path, output_rows)
    if snapshot_path is not None:
        _atomic_write_json(snapshot_path, snapshot)
    readback = verify_snapshot(csv_path, snapshot)
    return {
        "inserted": inserted,
        "revised": revised,
        "unchanged": unchanged,
        "row_count": len(output_rows),
        "readback_verified": readback["verified"],
        "latest_periods": readback["latest_periods"],
    }


def verify_snapshot(csv_path: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    expected = _snapshot_updates(snapshot)
    observed: dict[tuple[str, str], dict[str, str]] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("item", ""), row.get("period", ""))
            if key in expected:
                if key in observed:
                    raise NdcCollectionError(f"duplicate row after write: {key!r}")
                observed[key] = dict(row)

    mismatches = {
        key: {"expected": value, "observed": observed.get(key)}
        for key, value in expected.items()
        if observed.get(key) != value
    }
    if mismatches:
        raise NdcCollectionError(f"NDC CSV readback mismatch: {mismatches!r}")
    latest_periods = {
        spec.key: _latest_period_for_item(csv_path, spec.item) for spec in SERIES_SPECS
    }
    return {
        "verified": True,
        "verified_rows": len(expected),
        "latest_periods": latest_periods,
    }


def _load_snapshot(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise NdcCollectionError("snapshot input must contain one JSON object")
    validate_snapshot(payload)
    return payload


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _dirty_output_paths(paths: Iterable[Path]) -> list[str]:
    relative = [path.resolve().relative_to(PROJECT_ROOT).as_posix() for path in paths]
    completed = subprocess.run(
        [
            "git",
            "--literal-pathspecs",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *relative,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        raise NdcCollectionError(
            f"cannot verify NDC output Git state: {completed.stderr.strip()[:300]}"
        )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect official NDC BCI data")
    parser.add_argument("--check", action="store_true", help="Only check freshness")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fetch even when both canonical series already meet the expected period",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate the official tables without writing files",
    )
    parser.add_argument(
        "--snapshot-input",
        type=Path,
        help="Replay a previously captured source snapshot instead of launching Chrome",
    )
    parser.add_argument(
        "--chrome-executable",
        help="Explicit Chrome/Chromium executable path",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Leave verified outputs in the working tree instead of self-committing",
    )
    parser.add_argument("--csv-path", type=Path, default=BCI_PATH)
    parser.add_argument("--snapshot-path", type=Path, default=SOURCE_SNAPSHOT_PATH)
    args = parser.parse_args()

    before = freshness_report(args.csv_path)
    if args.check:
        _print_json(before)
        return 0
    if before["fresh"] and not args.force and args.snapshot_input is None:
        _print_json(
            {
                "ok": True,
                "action": "skip",
                "reason": "fresh",
                "freshness": before,
            }
        )
        return 0

    output_paths = [args.csv_path, args.snapshot_path]
    dirty_before: frozenset[str] = frozenset()
    if not args.dry_run:
        dirty_before = dirty_paths_before_write(
            PROJECT_ROOT,
            output_paths,
            label="collect_ndc_bci",
        )
        writable = set(
            writable_output_paths(
                PROJECT_ROOT,
                output_paths,
                dirty_before=dirty_before,
                label="collect_ndc_bci",
            )
        )
        required = {
            path.resolve().relative_to(PROJECT_ROOT).as_posix()
            for path in output_paths
        }
        if writable != required:
            _print_json(
                {
                    "ok": False,
                    "action": "blocked_dirty_output",
                    "dirty_before": sorted(dirty_before),
                }
            )
            return 1

    try:
        snapshot = (
            _load_snapshot(args.snapshot_input)
            if args.snapshot_input is not None
            else fetch_ndc_tables(chrome_executable=args.chrome_executable)
        )
        if args.dry_run:
            _print_json(
                {
                    "ok": True,
                    "action": "dry_run",
                    "content_sha256": snapshot.get("content_sha256"),
                    "tables": [
                        {
                            "key": table["key"],
                            "row_count": len(table["rows"]),
                            "latest_period": _canonical_period(table["rows"][-1][0]),
                        }
                        for table in snapshot["tables"]
                    ],
                }
            )
            return 0
        applied = apply_snapshot(
            args.csv_path,
            snapshot,
            snapshot_path=args.snapshot_path,
        )
        after = freshness_report(args.csv_path)
    except (  # silent-ok: structured failure is emitted and exits nonzero
        NdcCollectionError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        _print_json({"ok": False, "action": "failed", "error": str(exc)})
        return 1

    if not after["fresh"] or not applied["readback_verified"]:
        _print_json(
            {
                "ok": False,
                "action": "failed_postcondition",
                "applied": applied,
                "freshness": after,
            }
        )
        return 1

    committed_paths: list[str] = []
    if not args.no_commit:
        committed_paths = commit_owned_outputs(
            PROJECT_ROOT,
            output_paths,
            dirty_before=dirty_before,
            message=(
                "data(ndc): refresh official BCI through "
                f"{after['expected_period']}"
            ),
            label="collect_ndc_bci",
        )
        try:
            remaining_dirty = _dirty_output_paths(output_paths)
        except (  # silent-ok: structured failure is emitted and exits nonzero
            NdcCollectionError,
            OSError,
            subprocess.TimeoutExpired,
        ) as exc:
            _print_json(
                {
                    "ok": False,
                    "action": "failed_commit_readback",
                    "error": str(exc),
                    "committed_paths": committed_paths,
                }
            )
            return 1
        if remaining_dirty:
            _print_json(
                {
                    "ok": False,
                    "action": "failed_commit_postcondition",
                    "committed_paths": committed_paths,
                    "remaining_dirty": remaining_dirty,
                }
            )
            return 1

    _print_json(
        {
            "ok": True,
            "action": "updated",
            "source_snapshot": str(args.snapshot_path),
            "content_sha256": snapshot.get("content_sha256"),
            "applied": applied,
            "freshness": after,
            "committed_paths": committed_paths,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
