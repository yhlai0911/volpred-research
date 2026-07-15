"""Regression tests for daily_update.daily_publish_decision (2026-07-15 incident).

Boss report: 「一天兩組每日更新 … 7/15 的操作依據 7/13 的資料」。 The 14:15
intraday retry received a stale yfinance response (last row 2026-07-13) after
the 08:03 run had published on 2026-07-14 data. The old guard skipped only on
EQUALITY, so backwards data read as "changed" and published a second,
stale-data pair for the same day. The near-dup gate is intentionally waived
for these bulletins, so this decision function is the sole gate.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

_spec = importlib.util.spec_from_file_location(
    "daily_update", REPO / "scripts" / "daily_update.py"
)
daily_update = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(daily_update)

decide = daily_update.daily_publish_decision


def test_incident_regression_stale_upstream_data_is_skipped():
    """The exact 2026-07-15 14:15 inputs: last published 07-14, fetch returned 07-13."""
    skip, reason = decide("2026-07-14", "2026-07-13", None)
    assert skip is True
    assert reason.startswith("data_regressed")


def test_same_close_intraday_rerun_is_skipped():
    skip, reason = decide("2026-07-14", "2026-07-14", None)
    assert skip is True
    assert reason == "unchanged"


def test_fresh_close_publishes():
    skip, reason = decide("2026-07-14", "2026-07-15", None)
    assert skip is False
    assert reason == "fresh"


def test_tw_closed_skips_even_with_fresh_data():
    skip, reason = decide("2026-07-14", "2026-07-15", "颱風假")
    assert skip is True
    assert reason.startswith("tw_closed")


def test_first_ever_publish_with_no_history_publishes():
    skip, reason = decide(None, "2026-07-15", None)
    assert skip is False
    assert reason == "fresh"
