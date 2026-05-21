#!/usr/bin/env python3
"""Daily VIXTWN (Taiwan VIX) data collector.

Downloads daily closing VIXTWN from TAIFEX and appends to local CSV.
Free data source: rolling ~3-4 months from TAIFEX website.
Run daily via cron to accumulate long-term history.

Source: https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{YYYYMM}new.txt
Data available since: 2006-12-18 (via paid E-Data Shop)
Free data: rolling last 3-4 months only

Run: uv run python scripts/collect_vixtwn.py
Output: data/vixtwn/vixtwn_daily.csv

Exit codes (2026-05-04 silent-fail fix):
  0 = success (any month with records, including same-day pickup)
  1 = total fetch failure (all attempted months failed → cron exit code
      surfaces in storage/logs/cron/collect_tw.log; check_alerts'
      host_cron_fail then triggers per .claude/rules/alert.md)
"""
import csv
import sys
from datetime import datetime
from pathlib import Path

import requests


OUTPUT_DIR = Path("data/vixtwn")
OUTPUT_FILE = OUTPUT_DIR / "vixtwn_daily.csv"
TAIFEX_URL = "https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{ym}new.txt"


def fetch_month(year_month: str) -> list[dict]:
    """Fetch VIXTWN daily data for a given YYYYMM."""
    url = TAIFEX_URL.format(ym=year_month)
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"  {year_month}: fetch failed ({e})")
        return []

    # Try multiple encodings
    for enc in ["utf-8", "big5", "cp950"]:
        try:
            text = r.content.decode(enc)
            break
        except UnicodeDecodeError:
            text = r.text

    records = []
    for line in text.strip().split("\n"):
        parts = line.strip().split("\t")
        # TAIFEX format: 7 tab-separated fields with empty fields
        # [date, time, '', '', vix_close, '', vix_avg]
        if len(parts) >= 5:
            date_str = parts[0].strip()
            if len(date_str) == 8 and date_str.isdigit():
                # Find numeric values (skip empty fields)
                nums = [p.strip() for p in parts[2:] if p.strip()]
                if len(nums) >= 1:
                    try:
                        vix_close = float(nums[0])
                        vix_avg = float(nums[1]) if len(nums) >= 2 else vix_close
                        records.append({
                            "date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}",
                            "vixtwn_close": vix_close,
                            "vixtwn_1min_avg": vix_avg,
                        })
                    except ValueError:
                        continue

    return records


def load_existing() -> set[str]:
    """Load existing dates from CSV."""
    if not OUTPUT_FILE.exists():
        return set()
    existing = set()
    with open(OUTPUT_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing.add(row["date"])
    return existing


def save_records(records: list[dict], existing: set[str]):
    """Append new records to CSV."""
    new_records = [r for r in records if r["date"] not in existing]
    if not new_records:
        return 0

    file_exists = OUTPUT_FILE.exists()
    with open(OUTPUT_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "vixtwn_close", "vixtwn_1min_avg"])
        if not file_exists:
            writer.writeheader()
        writer.writerows(new_records)

    return len(new_records)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    existing = load_existing()
    print(f"=== VIXTWN Daily Collector: {now.strftime('%Y-%m-%d')} ===")
    print(f"  Existing records: {len(existing)}")

    # Fetch last 6 months (TAIFEX keeps ~3-4 months, but try wider to be safe)
    months_to_fetch = []
    for delta in range(6):
        m = now.month - delta
        y = now.year
        if m <= 0:
            m += 12
            y -= 1
        months_to_fetch.append(f"{y}{m:02d}")

    all_records = []
    fetch_failures: list[str] = []
    for ym in sorted(months_to_fetch):
        records = fetch_month(ym)
        if records:
            all_records.extend(records)
            print(f"  {ym}: {len(records)} days ({records[0]['date']} to {records[-1]['date']})")
        else:
            # fetch_month already prints "fetch failed" on exception; an
            # empty return on success is rare but possible if TAIFEX returns
            # an empty file. Track so we can distinguish total-failure from
            # same-day-not-yet-published.
            fetch_failures.append(ym)

    # Save
    n_new = save_records(all_records, existing)
    total = len(existing) + n_new

    print(f"\n  New records: {n_new}")
    print(f"  Total records: {total}")
    print(f"  Saved to: {OUTPUT_FILE}")

    if all_records:
        latest = sorted(all_records, key=lambda x: x["date"])[-1]
        print(f"  Latest VIXTWN: {latest['vixtwn_close']} ({latest['date']})")

    # 2026-05-04 silent-fail fix: previously fetch_month exception caught,
    # main() unconditional return None → cron exit 0 even when 6/6 months
    # failed (e.g. transient DNS). check_alerts host_cron_fail therefore
    # never triggered. Now: total failure → non-zero exit so cron log
    # records `=== exit 1 ===` and alert system catches it.
    if fetch_failures and not all_records:
        print(
            f"\n  [collect_vixtwn] FAIL: all {len(fetch_failures)} months "
            f"returned no records ({fetch_failures}). Likely transient DNS "
            f"or TAIFEX outage; check_alerts will surface as host_cron_fail.",
            file=sys.stderr,
        )
        return 1
    if fetch_failures:
        # Partial: some months OK, others empty. Warn but don't fail —
        # same-day publish lag is normal for the current month early in
        # the trading day, and a stale month edge is harmless if the
        # daily total is current.
        print(f"  [collect_vixtwn] WARN: {len(fetch_failures)} month(s) "
              f"empty: {fetch_failures} (may be transient or pre-publish)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
