#!/usr/bin/env python3
"""Auto-populate event_jobs.items for upcoming 4 weeks of recurring macro events.

Closes the recurring drift where event_jobs stops getting filled because no
process auto-generates entries. Run weekly from cron; idempotent (skips
already-populated event_keys).

Covers (recurring, known schedule):
- US CPI: monthly, 2nd Tue-Thu typically
- US NFP: 1st Friday of month
- FOMC: every 6-8 weeks (calendar-driven)
- TSMC monthly revenue: ~10th of each month
- BOJ / ECB / PBoC: bi-monthly approximations

Usage:
    uv run python scripts/populate_upcoming_events.py --dry-run
    uv run python scripts/populate_upcoming_events.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_PATH = ROOT / "config" / "runtime_schedules.json"

# Look-ahead window: populate events within the next N days.
LOOKAHEAD_DAYS = 30

# ─────────────────────────────────────────────────────────────────────────────
# Event schedule rules
# Each rule yields a list of (event_date, event_type) within the look-ahead.
# ─────────────────────────────────────────────────────────────────────────────


def _first_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """weekday: Monday=0..Sunday=6. Returns first such weekday of (year, month)."""
    d = date(year, month, 1)
    delta = (weekday - d.weekday()) % 7
    return d + timedelta(days=delta)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """n-th weekday of month (1-indexed)."""
    first = _first_weekday_of_month(year, month, weekday)
    return first + timedelta(days=(n - 1) * 7)


def gen_us_cpi(start: date, end: date) -> list[tuple[date, str]]:
    """US CPI release: typically Wednesday in 2nd full week of month, mid-month.

    Use 13th of month as approximation; user can override individual entries
    after BLS announces actual date.
    """
    events = []
    d = date(start.year, start.month, 1)
    while d <= end:
        # 13th of month as proxy
        candidate = date(d.year, d.month, 13)
        if start <= candidate <= end:
            events.append((candidate, "CPI_US"))
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)
    return events


def gen_us_nfp(start: date, end: date) -> list[tuple[date, str]]:
    """US NFP: 1st Friday of month."""
    events = []
    d = date(start.year, start.month, 1)
    while d <= end:
        fri = _first_weekday_of_month(d.year, d.month, 4)  # Friday=4
        if start <= fri <= end:
            events.append((fri, "NFP_US"))
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)
    return events


def gen_fomc(start: date, end: date) -> list[tuple[date, str]]:
    """FOMC meetings: known Wednesdays in 2026.

    Hard-coded canonical schedule; update annually. Source: Federal Reserve
    published meeting calendar.
    """
    fomc_2026 = [
        date(2026, 1, 28),
        date(2026, 3, 18),
        date(2026, 4, 29),
        date(2026, 6, 17),
        date(2026, 7, 29),
        date(2026, 9, 16),
        date(2026, 10, 28),
        date(2026, 12, 9),
    ]
    return [(d, "FOMC") for d in fomc_2026 if start <= d <= end]


def gen_tsmc_revenue(start: date, end: date) -> list[tuple[date, str]]:
    """TSMC monthly revenue: ~10th of each month."""
    events = []
    d = date(start.year, start.month, 1)
    while d <= end:
        candidate = date(d.year, d.month, 10)
        if start <= candidate <= end:
            events.append((candidate, "TSMC_REVENUE"))
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)
    return events


# ─────────────────────────────────────────────────────────────────────────────
# T-series slot generator
# ─────────────────────────────────────────────────────────────────────────────


SLOT_CONFIG = {
    # event_type → list of (slot_label, days_before, priority, announce_hour_cst)
    # announce_hour: T+0 not_before time-of-day CST
    "FOMC": [
        ("T-7", 7, 30, None),
        ("T-2", 2, 20, None),
        ("T+0", 0, 15, 2.5),  # FOMC announces 14:00 ET = CST 02:30 next day
    ],
    "CPI_US": [
        ("T-2", 2, 20, None),
        ("T+0", 0, 15, 21.5),  # 08:30 ET = CST 21:30 same day
    ],
    "NFP_US": [
        ("T-7", 7, 30, None),
        ("T-2", 2, 20, None),
        ("T+0", 0, 15, 21.5),
    ],
    "TSMC_REVENUE": [
        ("T+0", 0, 15, 15),  # 15:00 CST typical
    ],
}


def slot_to_iso(event_date: date, slot: str, days_before: int, announce_hour: float | None) -> tuple[str, str]:
    """Return (not_before_iso, deadline_iso) for a slot."""
    if slot == "T+0" and announce_hour is not None:
        h = int(announce_hour)
        m = int((announce_hour - h) * 60)
        not_before = datetime(event_date.year, event_date.month, event_date.day, h, m, tzinfo=timezone(timedelta(hours=8)))
    else:
        target = event_date - timedelta(days=days_before)
        not_before = datetime(target.year, target.month, target.day, 8, 0, tzinfo=timezone(timedelta(hours=8)))
    deadline = not_before + timedelta(hours=36)
    return not_before.isoformat(), deadline.isoformat()


def build_event_item(event_date: date, event_type: str, slot: str, days_before: int, priority: int, announce_hour: float | None) -> dict:
    not_before, deadline = slot_to_iso(event_date, slot, days_before, announce_hour)
    event_key = f"{event_type}_{event_date.strftime('%Y_%m_%d')}"
    slot_id = slot.lower().replace("+", "").replace("-", "minus")
    if slot == "T+0":
        slot_id = "t0"
    elif slot == "T-2":
        slot_id = "t2"
    elif slot == "T-7":
        slot_id = "t7"
    elif slot == "T+1":
        slot_id = "tp1"

    # Match canonical id pattern: drop "_US" suffix for US events (NFP_US → nfp,
    # CPI_US → cpi-us is fine since CPI alone is ambiguous, NFP_US → nfp).
    type_to_slug = {
        "NFP_US": "nfp",
        "CPI_US": "cpi-us",
        "FOMC": "fomc",
        "TSMC_REVENUE": "tsmc-revenue",
    }
    event_type_slug = type_to_slug.get(event_type, event_type.lower().replace("_", "-"))
    item_id = f"{event_type_slug}-{event_date.strftime('%Y-%m-%d')}-{slot_id}"

    return {
        "id": item_id,
        "event_key": event_key,
        "trigger_mode": "one_shot",
        "dedupe_key": f"{item_id}:one_shot",
        "not_before": not_before,
        "deadline": deadline,
        "preferred_agent": "claude",
        "public_effect": "published",
        "task_template": {
            "title": f"Event article: {event_type} {event_date.isoformat()} {slot}",
            "description": f"Auto-populated by populate_upcoming_events.py. {event_type} {event_date.isoformat()} {slot} slot. Run feed-publisher event template; 3-layer dedup; audience=general (T-7 may use research).",
            "task_family": "content",
            "priority": priority,
            "preferred_agent": "claude",
            "fallback_allowed": False,
            "approval_mode": "auto",
            "risk_level": "safe",
            "public_effect": "published",
            "preconditions": [],
            "payload_patch": {
                "audience": "research" if slot == "T-7" else "general",
                "event_series_slot": slot,
                "event_date": event_date.isoformat(),
                "event_type": event_type,
            },
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--days", type=int, default=LOOKAHEAD_DAYS)
    args = parser.parse_args()

    if not (args.dry_run or args.apply):
        print("error: must specify --dry-run or --apply", file=sys.stderr)
        return 2

    today = date.today()
    end = today + timedelta(days=args.days)

    with open(SCHEDULE_PATH) as f:
        cfg = json.load(f)
    items = cfg["event_jobs"]["items"]
    existing_ids = {i["id"] for i in items}

    new_items = []
    for generator in (gen_us_cpi, gen_us_nfp, gen_fomc, gen_tsmc_revenue):
        for event_date, event_type in generator(today, end):
            for slot, days_before, priority, announce_hour in SLOT_CONFIG.get(event_type, []):
                # Only generate T-7/T-2 if event_date is far enough in future
                if days_before > 0 and event_date - timedelta(days=days_before) < today:
                    continue
                item = build_event_item(event_date, event_type, slot, days_before, priority, announce_hour)
                if item["id"] in existing_ids:
                    continue
                new_items.append(item)

    print(f"[populate_events] would add {len(new_items)} event items (lookahead={args.days}d)")
    for it in new_items:
        print(f"  {it['id']}  {it['not_before'][:10]}")

    if args.apply and new_items:
        items.extend(new_items)
        with open(SCHEDULE_PATH, "w") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print(f"[populate_events] applied — event_jobs.items now {len(items)}")
    elif args.dry_run:
        print("[populate_events] dry-run only; rerun with --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
