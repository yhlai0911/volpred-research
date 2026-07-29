"""Tests for the 2026-07-19 dispatch burst window (task `assign_cadde1b5`).

The owner asked for continuous dispatch until 16:00 with per-task Telegram
reports, then an automatic return to the hourly cadence. The failure mode worth
testing is not "does it fire" — it is "does it ever STOP": a burst that outlives
its window quietly turns a one-afternoon exception into the permanent setting.

Run::
    uv run pytest scripts/tests/test_dispatch_burst.py -v
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from volpred.ops import dispatch_burst


@pytest.fixture
def paths(tmp_path):
    state = tmp_path / "dispatch_state.json"
    state.write_text(json.dumps({"completions": [{"outcome": "success"}]}), encoding="utf-8")
    return tmp_path / "burst.json", state


def _open(path, *, delta_s: int) -> datetime:
    until = datetime.now(timezone.utc) + timedelta(seconds=delta_s)
    dispatch_burst.open_window(until=until.isoformat(), reason="test", path=path)
    return until


def test_open_window_is_active(paths):
    burst, state = paths
    _open(burst, delta_s=3600)
    got = dispatch_burst.status(path=burst, state_path=state)
    assert got["active"] is True
    assert got["seconds_left"] > 3500


def test_expiry_deactivates_without_any_cleanup_step(paths):
    burst, state = paths
    _open(burst, delta_s=-1)
    got = dispatch_burst.status(path=burst, state_path=state)
    assert got["active"] is False
    assert got["reason"] == "expired"
    # The file deliberately survives: a cleanup that must succeed to end the
    # burst is a cleanup whose failure extends the burst.
    assert burst.exists()


def test_no_window_is_inactive(paths):
    burst, state = paths
    assert dispatch_burst.status(path=burst, state_path=state)["reason"] == "no_window"


@pytest.mark.parametrize("payload", ["{ broken", json.dumps({"reason": "no until key"})])
def test_corrupt_window_fails_closed_to_inactive(paths, payload):
    burst, state = paths
    burst.write_text(payload, encoding="utf-8")
    assert dispatch_burst.active(path=burst, state_path=state) is False


def test_unparseable_until_is_inactive(paths):
    burst, state = paths
    burst.write_text(json.dumps({"until": "not-a-date"}), encoding="utf-8")
    got = dispatch_burst.status(path=burst, state_path=state)
    assert got == {"active": False, "reason": "unparseable_until", "window": {"until": "not-a-date"}}


def test_open_rejects_an_unparseable_deadline(tmp_path):
    # A window with no valid end is a window that never ends.
    with pytest.raises(ValueError):
        dispatch_burst.open_window(until="soon", reason="x", path=tmp_path / "b.json")


def test_quota_streak_suspends_but_does_not_end_the_window(paths):
    burst, state = paths
    _open(burst, delta_s=3600)
    state.write_text(json.dumps({"completions": [
        {"outcome": "quota_blocked"}, {"outcome": "quota_blocked"}]}), encoding="utf-8")
    got = dispatch_burst.status(path=burst, state_path=state)
    assert got["active"] is False
    assert got["reason"] == "quota_suspended"
    # Suspended, not closed: quota resolves on a clock, so the window resumes.
    state.write_text(json.dumps({"completions": [
        {"outcome": "quota_blocked"}, {"outcome": "success"}]}), encoding="utf-8")
    assert dispatch_burst.active(path=burst, state_path=state) is True


def test_close_window_is_an_early_stop(paths):
    burst, state = paths
    _open(burst, delta_s=3600)
    assert dispatch_burst.close_window(path=burst) is True
    assert dispatch_burst.active(path=burst, state_path=state) is False
    assert dispatch_burst.close_window(path=burst) is False
