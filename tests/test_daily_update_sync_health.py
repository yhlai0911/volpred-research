"""Regression tests for daily_update sync-health calendar awareness."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _import_helpers():
    from daily_update import (  # type: ignore
        _build_sync_health_local_state,
        _sync_health_date_table_is_fresh,
        _sync_health_effective_data_date,
        _sync_health_timestamp_is_fresh,
    )

    return (
        _build_sync_health_local_state,
        _sync_health_date_table_is_fresh,
        _sync_health_effective_data_date,
        _sync_health_timestamp_is_fresh,
    )


def _holiday_state():
    build_state, *_ = _import_helpers()
    return build_state(
        {
            "_market_daily": {
                "2026-07-03": {"spy_close": 744.78},
                "2026-07-04": {"spy_close": 744.78},
            },
            "slow_vt": {
                "entries": [
                    {"trade_date": "2026-07-02", "data_date": "2026-07-01"},
                    {"trade_date": "2026-07-03", "data_date": "2026-07-02"},
                ]
            },
            "risk_parity": {
                "entries": [
                    {"trade_date": "2026-07-02", "data_date": "2026-07-01"},
                    {"trade_date": "2026-07-03", "data_date": "2026-07-02"},
                ]
            },
        }
    )


def test_sync_health_maps_weekend_market_daily_to_latest_spy_data_date() -> None:
    """A no-new-data weekend _market_daily row should not create drift noise."""
    _, date_is_fresh, effective_data_date, _ = _import_helpers()
    state = _holiday_state()

    assert state["latest_data_date"] == "2026-07-02"
    assert state["latest_calendar_date"] == "2026-07-04"
    assert effective_data_date("2026-07-04", state) == "2026-07-02"

    ok, observed, expected = date_is_fresh("2026-07-04", state)
    assert ok is True
    assert observed == "2026-07-02"
    assert expected == "2026-07-02"


def test_sync_health_still_flags_date_table_stuck_before_latest_data_date() -> None:
    """Calendar tolerance must not hide a real missed daily_update sync."""
    _, date_is_fresh, _, _ = _import_helpers()
    state = _holiday_state()

    ok, observed, expected = date_is_fresh("2026-07-02", state)
    assert ok is False
    assert observed == "2026-07-01"
    assert expected == "2026-07-02"


def test_sync_health_strategy_signals_use_update_date_not_spy_data_date() -> None:
    """strategy_signals.updated_at can be after the SPY data date on holidays."""
    *_, timestamp_is_fresh = _import_helpers()
    state = _holiday_state()

    ok, observed, expected = timestamp_is_fresh("2026-07-04T00:03:00+00:00", state)
    assert ok is True
    assert observed == "2026-07-04"
    assert expected == "2026-07-04"

    stale_ok, stale_observed, stale_expected = timestamp_is_fresh(
        "2026-07-03T00:03:00+00:00",
        state,
    )
    assert stale_ok is False
    assert stale_observed == "2026-07-03"
    assert stale_expected == "2026-07-04"
