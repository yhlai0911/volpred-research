"""Collect TWSE intraday order/trade flow (MI_5MINS — 每5秒委託成交統計).

Why this exists
---------------
The TWSE `MI_5MINS` endpoint returns, for one trading day, the cumulative
order-book + trade statistics sampled every 5 seconds across the session
(09:00:00 → 13:30:00): cumulative buy/sell order counts & volumes, and
cumulative matched-trade count / volume / value. This is genuine intraday
order-flow / buy-sell-pressure data that exists NOWHERE in yfinance.

Unlike the yfinance 5-min OHLC (0050/SPY) collector — which must archive daily
because yfinance only retains ~60 days — `MI_5MINS` DOES serve history (verified
back to at least 2016-01-04). So we can both (a) backfill all available history
and (b) keep appending the latest day going forward.

Output
------
One CSV per trading day:
  data/intraday/twse_orderflow/twse_mi5mins_<YYYY-MM-DD>.csv
Columns = the endpoint's own `fields` (時間, 累積委託買進筆數, ...) + a leading
`date` column. Non-trading days (stat != "OK") write nothing and are logged.

Usage
-----
  # single day (daily cron piggyback):
  uv run python scripts/collect_twse_orderflow.py --date 20260617
  uv run python scripts/collect_twse_orderflow.py --date today

  # backfill all available history (resumable, skip-existing, rate-limited):
  uv run python scripts/collect_twse_orderflow.py --backfill --start 20120102

Research honesty / etiquette
----------------------------
- Idempotent: existing non-empty day files are skipped (safe to re-run / resume).
- Rate-limited: --sleep seconds between requests (default 4.0) to avoid a TWSE
  IP ban; on HTTP error / block, the day is skipped (not written) so a later run
  retries it.
- No fabrication: only days the endpoint returns stat=="OK" with data are saved.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT / "data" / "intraday" / "twse_orderflow"
ENDPOINT = "https://www.twse.com.tw/exchangeReport/MI_5MINS?response=json&date={ymd}"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)


def _fetch(ymd: str, timeout: float = 30.0) -> dict | None:
    """Fetch one day's MI_5MINS JSON. Returns parsed dict or None on error."""
    req = urllib.request.Request(ENDPOINT.format(ymd=ymd), headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # network / HTTP / parse — caller retries on next run
        print(f"  [twse_orderflow] {ymd} fetch error: {exc}")
        return None


def _out_path(d: date) -> Path:
    return OUTPUT_DIR / f"twse_mi5mins_{d.isoformat()}.csv"


def collect_day(d: date, *, timeout: float = 30.0) -> str:
    """Fetch + save one trading day. Returns: 'saved' | 'exists' | 'no_data' | 'error'."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = _out_path(d)
    if out.exists() and out.stat().st_size > 0:
        return "exists"
    payload = _fetch(d.strftime("%Y%m%d"), timeout=timeout)
    if payload is None:
        return "error"
    if payload.get("stat") != "OK":
        return "no_data"  # weekend / holiday / not-yet-published
    fields = payload.get("fields") or []
    rows = payload.get("data") or []
    if not fields or not rows:
        return "no_data"
    tmp = out.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", *fields])
        for r in rows:
            writer.writerow([d.isoformat(), *r])
    tmp.replace(out)  # atomic
    return "saved"


def _iter_days(start: date, end: date):
    cur = start
    while cur <= end:
        # Skip weekends client-side to save requests (TWSE has no Sat/Sun data).
        if cur.weekday() < 5:
            yield cur
        cur += timedelta(days=1)


def backfill(start: date, end: date, *, sleep: float) -> dict:
    counts = {"saved": 0, "exists": 0, "no_data": 0, "error": 0}
    total = sum(1 for _ in _iter_days(start, end))
    print(f"[twse_orderflow] backfill {start} → {end} ({total} weekday candidates), sleep={sleep}s")
    i = 0
    for d in _iter_days(start, end):
        i += 1
        out = _out_path(d)
        if out.exists() and out.stat().st_size > 0:
            counts["exists"] += 1
            continue
        status = collect_day(d)
        counts[status] = counts.get(status, 0) + 1
        if status == "saved":
            print(f"  [{i}/{total}] {d} saved")
        elif status == "error":
            print(f"  [{i}/{total}] {d} ERROR (will retry on re-run)")
        # polite spacing only when we actually hit the network
        if status in ("saved", "no_data", "error"):
            time.sleep(sleep)
    print(f"[twse_orderflow] backfill done: {counts}")
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect TWSE MI_5MINS intraday order-flow")
    ap.add_argument("--date", help="single day YYYYMMDD or 'today'")
    ap.add_argument("--backfill", action="store_true", help="backfill a date range")
    ap.add_argument("--start", help="backfill start YYYYMMDD (default 20120102)")
    ap.add_argument("--end", help="backfill end YYYYMMDD (default today)")
    ap.add_argument("--sleep", type=float, default=4.0, help="seconds between requests (default 4.0)")
    args = ap.parse_args()

    today = date.today()
    if args.backfill:
        start = datetime.strptime(args.start, "%Y%m%d").date() if args.start else date(2012, 1, 2)
        end = datetime.strptime(args.end, "%Y%m%d").date() if args.end else today
        backfill(start, end, sleep=args.sleep)
        return 0

    # single day (default = today)
    if not args.date or args.date == "today":
        d = today
    else:
        d = datetime.strptime(args.date, "%Y%m%d").date()
    status = collect_day(d)
    print(f"[twse_orderflow] {d} -> {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
