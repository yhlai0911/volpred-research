from __future__ import annotations

from datetime import date

from scripts.populate_upcoming_events import SLOT_CONFIG, build_event_item


def _tplus0(event_type: str, event_date: date) -> dict:
    slot, days_before, priority, announce_hour = next(
        row for row in SLOT_CONFIG[event_type] if row[0] == "T+0"
    )
    return build_event_item(
        event_date,
        event_type,
        slot,
        days_before,
        priority,
        announce_hour,
    )


def test_fomc_release_clock_converts_new_york_date_to_taipei_next_day() -> None:
    item = _tplus0("FOMC", date(2026, 7, 29))

    assert item["not_before"] == "2026-07-30T02:00:00+08:00"


def test_us_data_release_clock_observes_new_york_daylight_saving() -> None:
    item = _tplus0("CPI_US", date(2026, 7, 14))

    assert item["not_before"] == "2026-07-14T20:30:00+08:00"
