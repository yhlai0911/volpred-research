from __future__ import annotations

import requests

import pandas as pd
import pytest

from volpred.data import event_dates


@pytest.fixture(autouse=True)
def isolate_event_date_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)


def test_cpi_release_dates_lock_shutdown_and_rescheduled_dates(monkeypatch):
    raw = [
        "2025-10-24",
        # No November release: October 2025 CPI was cancelled during the shutdown.
        "2025-12-18",
        "2026-01-13",
        "2026-02-13",
        "2026-03-11",
        "2026-04-10",
        "2026-05-12",
    ]
    monkeypatch.setattr(event_dates, "_fetch", lambda *_args, **_kwargs: raw)

    actual = event_dates.cpi_release_dates(
        "2025-10-01",
        "2026-05-31",
        use_cache=False,
    )

    assert actual.equals(pd.DatetimeIndex(pd.to_datetime(raw)))
    assert pd.Timestamp("2025-11-13") not in actual


def test_release_dates_uses_earliest_entry_when_release_has_same_month_revisions(
    monkeypatch,
):
    # 2026-07-19 semantics flip (k528 Codex blocker): off-cycle revision entries
    # are filed LATER in the month than the regular report, so max() picked six
    # wrong NFP dates. The regular release is the month's EARLIEST entry.
    monkeypatch.setattr(
        event_dates,
        "_fetch",
        lambda *_args, **_kwargs: ["2024-02-13", "2024-02-15", "2024-03-12"],
    )

    actual = event_dates.release_dates(
        "CPI_US",
        "2024-02-01",
        "2024-03-31",
        use_cache=False,
    )

    assert actual.equals(
        pd.DatetimeIndex(pd.to_datetime(["2024-02-13", "2024-03-12"]))
    )


def test_release_dates_empty_response_fails_closed(monkeypatch):
    monkeypatch.setattr(event_dates, "_fetch", lambda *_args, **_kwargs: [])

    with pytest.raises(RuntimeError, match="no CPI_US release dates"):
        event_dates.cpi_release_dates(
            "2024-01-01",
            "2024-12-31",
            use_cache=False,
        )


def test_release_dates_api_failure_propagates(monkeypatch):
    def fail(*_args, **_kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(event_dates, "_fetch", fail)

    with pytest.raises(requests.ConnectionError, match="offline"):
        event_dates.cpi_release_dates(
            "2024-01-01",
            "2024-12-31",
            use_cache=False,
        )


def test_missing_api_key_fails_closed(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(event_dates.Path, "exists", lambda _self: False)

    with pytest.raises(RuntimeError, match="FRED_API_KEY not found"):
        event_dates._api_key()
