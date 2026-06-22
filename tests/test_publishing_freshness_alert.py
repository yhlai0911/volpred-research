"""Regression gate for the 2026-06-22 發文脫班 dead-man switch.

Incident: hourly dispatch's pinned claude binary was deleted by auto-update →
generator produced 0 content for ~12h → release filter blocked the stale pool →
only 1 article published, yet check_alerts breach_count=0 (every job exited 0,
nothing watched the actual published-feed OUTCOME). These tests assert the
outcome-based publishing_freshness dead-man switch fires CRITICAL on that exact
condition, and does NOT false-positive overnight or when content is fresh.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops.alerts import (
    PUBLISH_FRESHNESS_CRITICAL_HOURS,
    _parse_publishing_freshness_state,
)

_TPE = timezone(timedelta(hours=8))


def _write_feed(storage_dir: Path, newest_published: datetime | None) -> None:
    reports = storage_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    feed = []
    if newest_published is not None:
        feed.append(
            {
                "id": "mile_test",
                "status": "published",
                "published_at": newest_published.astimezone(timezone.utc).isoformat(),
                "title": "test",
            }
        )
        # an older one + a draft, to ensure max() + status filter work
        feed.append(
            {
                "id": "mile_old",
                "status": "published",
                "published_at": (newest_published - timedelta(days=2)).astimezone(timezone.utc).isoformat(),
            }
        )
        feed.append({"id": "mile_draft", "status": "draft", "published_at": None})
    (reports / "feed.json").write_text(json.dumps(feed))


def test_breaches_critical_when_stale_in_active_window(tmp_path: Path) -> None:
    # now = 14:00 Taipei (active window); newest published 08:00 Taipei = 6h gap.
    now = datetime(2026, 6, 22, 14, 0, tzinfo=_TPE)
    _write_feed(tmp_path, datetime(2026, 6, 22, 8, 0, tzinfo=_TPE))
    state = _parse_publishing_freshness_state(str(tmp_path), now.astimezone(timezone.utc))
    assert state["breached"] is True
    assert state["level"] == "critical"
    assert state["details"]["publish_gap_hours"] >= PUBLISH_FRESHNESS_CRITICAL_HOURS


def test_no_breach_when_fresh(tmp_path: Path) -> None:
    now = datetime(2026, 6, 22, 14, 0, tzinfo=_TPE)
    _write_feed(tmp_path, datetime(2026, 6, 22, 13, 0, tzinfo=_TPE))  # 1h ago
    state = _parse_publishing_freshness_state(str(tmp_path), now.astimezone(timezone.utc))
    assert state["breached"] is False


def test_no_breach_overnight_even_if_stale(tmp_path: Path) -> None:
    # 03:00 Taipei is outside the active window — expected low activity, no alarm.
    now = datetime(2026, 6, 22, 3, 0, tzinfo=_TPE)
    _write_feed(tmp_path, datetime(2026, 6, 21, 18, 0, tzinfo=_TPE))  # 9h ago
    state = _parse_publishing_freshness_state(str(tmp_path), now.astimezone(timezone.utc))
    assert state["breached"] is False


def test_breaches_when_no_published_articles_in_active_window(tmp_path: Path) -> None:
    now = datetime(2026, 6, 22, 14, 0, tzinfo=_TPE)
    _write_feed(tmp_path, None)  # empty feed / nothing ever published
    state = _parse_publishing_freshness_state(str(tmp_path), now.astimezone(timezone.utc))
    assert state["breached"] is True
    assert state["level"] == "critical"
