"""The release audit has to be able to see its own trigger.

2026-07-19 R4 (boss 20:14「為什麼文章沒有照排程釋出」): `audit_release_settings.py`
compared local settings against the Supabase row and printed `ok` for nine hours
while the pool released nothing. It was never a drifted field — the LaunchAgent
fires every 6h while `interval_minutes` says 4h, so the configured cadence is
unreachable on the regular path and the hourly `check_alerts` fallback was
quietly carrying the entire release rate. An audit that only reads the config is
checking the map, not the road.

Two checks, both exit 1, because nothing downstream repairs either one.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import audit_release_settings as audit  # noqa: E402


def _plist(monkeypatch, tmp_path, body: bytes):
    home = tmp_path / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    (home / "Library" / "LaunchAgents" / audit._RELEASE_PLIST).write_bytes(body)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))


def _calendar_plist(hours: list[int]) -> bytes:
    entries = "".join(
        f"<dict><key>Minute</key><integer>7</integer>"
        f"<key>Hour</key><integer>{h}</integer></dict>"
        for h in hours
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
        '<plist version="1.0"><dict>'
        "<key>StartCalendarInterval</key><array>" + entries + "</array>"
        "</dict></plist>"
    ).encode()


def test_six_hour_trigger_fails_a_four_hour_interval(monkeypatch, tmp_path):
    """The exact production misalignment this check was written for."""
    _plist(monkeypatch, tmp_path, _calendar_plist([0, 6, 12, 18]))
    monkeypatch.setattr(audit, "_crontab_release_lines", lambda: [])

    result = audit._cadence_check({"interval_minutes": 240})
    assert result["ok"] is False
    assert result["status"] == "cadence_misaligned"
    assert result["launchagent_max_gap_minutes"] == 360


def test_a_matching_trigger_passes(monkeypatch, tmp_path):
    _plist(monkeypatch, tmp_path, _calendar_plist([0, 4, 8, 12, 16, 20]))
    monkeypatch.setattr(audit, "_crontab_release_lines", lambda: [])

    result = audit._cadence_check({"interval_minutes": 240})
    assert result["ok"] is True
    assert result["status"] == "aligned"


def test_wrap_past_midnight_counts_as_a_gap(monkeypatch, tmp_path):
    """Two fires at 00:07 and 01:07 are not an hourly cadence — the other 23
    hours are the real gap."""
    _plist(monkeypatch, tmp_path, _calendar_plist([0, 1]))
    monkeypatch.setattr(audit, "_crontab_release_lines", lambda: [])

    assert audit._cadence_check({"interval_minutes": 240})["ok"] is False


def test_a_crontab_driver_suspends_the_verdict_rather_than_guessing(monkeypatch, tmp_path):
    """A cron entry also driving the pool tightens the real cadence; its schedule
    is not parsed here, so do not claim a misalignment we cannot prove."""
    _plist(monkeypatch, tmp_path, _calendar_plist([0, 6, 12, 18]))
    monkeypatch.setattr(audit, "_crontab_release_lines", lambda: ["*/30 * * * * cron_release_pool.sh"])

    result = audit._cadence_check({"interval_minutes": 240})
    assert result["ok"] is True
    assert result["status"] == "cron_present_not_parsed"


def test_missing_plist_is_unknown_not_a_pass(monkeypatch, tmp_path):
    home = tmp_path / "empty"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(audit, "_crontab_release_lines", lambda: [])

    assert audit._cadence_check({"interval_minutes": 240})["status"] == "unknown"


def test_starved_drafts_are_reported_by_skip_count(monkeypatch, tmp_path):
    """The symptom the field-only audit could not see: 20 skips, still `ok`."""
    import json

    reports = tmp_path / "storage" / "reports"
    reports.mkdir(parents=True)
    (reports / "feed.json").write_text(json.dumps([
        {"id": "mile_stuck", "status": "draft", "title": "blocked",
         "details": {"release_audit_skipped_count": 20}},
        {"id": "mile_fine", "status": "draft", "title": "fresh",
         "details": {"release_audit_skipped_count": 1}},
        {"id": "mile_live", "status": "published", "title": "already out",
         "details": {"release_audit_skipped_count": 30}},
    ]))
    monkeypatch.setattr(audit, "PROJECT_ROOT", tmp_path)

    starved = audit._starved_drafts()
    assert [d["id"] for d in starved] == ["mile_stuck"]
    assert starved[0]["skipped"] == 20
