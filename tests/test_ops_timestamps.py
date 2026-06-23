"""Tests for volpred.ops.timestamps.parse_iso_warn."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from volpred.ops.timestamps import parse_iso_warn


def test_parse_iso_string_tz_aware(capsys):
    dt = parse_iso_warn("2026-06-23T13:00:00+08:00", "dispatch", "blocked_until")
    assert dt == datetime(2026, 6, 23, 13, 0, tzinfo=datetime.fromisoformat("2026-06-23T13:00:00+08:00").tzinfo)
    assert capsys.readouterr().err == ""


def test_parse_iso_string_z_suffix(capsys):
    dt = parse_iso_warn("2026-06-23T05:00:00Z", "dispatch", "completed_at")
    assert dt == datetime(2026, 6, 23, 5, 0, tzinfo=timezone.utc)
    assert capsys.readouterr().err == ""


def test_parse_naive_attaches_assume_tz(capsys):
    dt = parse_iso_warn("2026-06-23T05:00:00", "dispatch", "ts")
    assert dt.tzinfo is timezone.utc
    assert dt.hour == 5
    assert capsys.readouterr().err == ""


def test_parse_naive_assume_tz_none_returns_naive(capsys):
    dt = parse_iso_warn("2026-06-23T05:00:00", "dispatch", "ts", assume_tz=None)
    assert dt.tzinfo is None
    assert capsys.readouterr().err == ""


def test_none_returns_fallback_silently(capsys):
    sentinel = object()
    assert parse_iso_warn(None, "tag", "field", fallback=sentinel) is sentinel
    assert capsys.readouterr().err == ""


def test_empty_string_returns_fallback_silently(capsys):
    assert parse_iso_warn("   ", "tag", "field", fallback=None) is None
    assert capsys.readouterr().err == ""


def test_invalid_parse_warns_and_returns_fallback(capsys):
    sentinel = object()
    result = parse_iso_warn("not-a-date", "dispatch", "blocked_until", fallback=sentinel, task_id="t1")
    assert result is sentinel
    err = capsys.readouterr().err
    assert "[dispatch] WARN blocked_until parse failed" in err
    assert "field=blocked_until" in err
    assert "raw=not-a-date" in err
    assert "err=ValueError" in err
    assert "task_id=t1" in err


def test_truncates_raw_in_warn(capsys):
    huge = "x" * 500
    parse_iso_warn(huge, "tag", "field")
    err = capsys.readouterr().err
    assert "raw=" in err
    assert "x" * 80 in err
    # 500 raw chars 不該整段進 stderr
    assert "x" * 200 not in err


def test_ctx_kwargs_forwarded(capsys):
    parse_iso_warn("bad", "refill", "event_date", item_id="evt_42", source="event_jobs")
    err = capsys.readouterr().err
    assert "item_id=evt_42" in err
    assert "source=event_jobs" in err


def test_date_only_string_parses_as_midnight(capsys):
    dt = parse_iso_warn("2026-06-23", "tag", "event_date")
    assert dt == datetime(2026, 6, 23, tzinfo=timezone.utc)
    assert capsys.readouterr().err == ""


def test_int_raw_is_treated_as_failure(capsys):
    sentinel = object()
    result = parse_iso_warn(12345, "tag", "field", fallback=sentinel)
    assert result is sentinel
    err = capsys.readouterr().err
    assert "parse failed" in err
