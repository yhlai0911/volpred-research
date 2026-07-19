"""Regression tests for release_dates off-cycle selection + cadence gate.

2026-07-19 k528 Codex review: the old per-month max() rule picked 6 off-cycle
FRED entries (seasonal-factor / benchmark revisions filed against the same
release id, later in the month) as NFP event dates, flipping a significance
result. The fix keeps each month's EARLIEST entry and fail-closes when the
resulting sequence does not look like a monthly release calendar.
"""
from __future__ import annotations

import pytest

from volpred.data import event_dates


@pytest.fixture(autouse=True)
def _sandbox_cache_dir(monkeypatch, tmp_path):
    # belt-and-suspenders with use_cache=False: no test may touch the
    # canonical storage/data cache dir (CI repo-state guard, 2026-07-19).
    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)


def _dates(monkeypatch, raw):
    monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(raw))
    return event_dates.release_dates("NFP_US", "2024-01-01", "2024-12-31", use_cache=False)


def test_off_cycle_late_entry_loses_to_regular_release(monkeypatch):
    raw = [
        "2024-01-05",
        "2024-02-02", "2024-02-09",  # 02-09 = off-cycle revision entry, must lose
        "2024-03-08",
    ]
    got = [str(d.date()) for d in _dates(monkeypatch, raw)]
    assert got == ["2024-01-05", "2024-02-02", "2024-03-08"]


def test_shutdown_gap_within_band_passes(monkeypatch):
    # One cancelled month (~77d gap) is a real calendar, not an error.
    raw = ["2024-01-05", "2024-02-02", "2024-04-19", "2024-05-17"]
    got = [str(d.date()) for d in _dates(monkeypatch, raw)]
    assert got == ["2024-01-05", "2024-02-02", "2024-04-19", "2024-05-17"]


def test_collapsed_gap_fails_closed(monkeypatch):
    # A month whose ONLY entry is a late off-cycle date makes the next gap
    # collapse (<20d) — the sequence no longer looks like a release calendar.
    raw = ["2024-01-05", "2024-02-27", "2024-03-07"]
    with pytest.raises(RuntimeError, match="monthly-cadence validation"):
        _dates(monkeypatch, raw)


def test_three_missing_cycles_fail_closed(monkeypatch):
    raw = ["2024-01-05", "2024-06-07"]
    with pytest.raises(RuntimeError, match="monthly-cadence validation"):
        _dates(monkeypatch, raw)
