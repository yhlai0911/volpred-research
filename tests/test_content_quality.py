"""Tests for `volpred.ops.content_quality` patrol checks.

Constructed scenarios mirror the four content problems boss spotted on
2026-06-24 (digest duplicate, 標題前綴重複, rhythm drought) plus their
green-path counterparts so the check doesn't false-positive on normal days.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from volpred.ops import content_quality as cq

TPE = ZoneInfo("Asia/Taipei")


def _write_feed(tmp_path: Path, items: list[dict]) -> Path:
    storage = tmp_path / "storage"
    (storage / "reports").mkdir(parents=True)
    (storage / "reports" / "feed.json").write_text(
        json.dumps(items, ensure_ascii=False),
        encoding="utf-8",
    )
    return storage


def _entry(
    item_id: str,
    *,
    published_at: datetime,
    status: str = "published",
    title: str | None = None,
    content_type: str | None = None,
) -> dict:
    return {
        "id": item_id,
        "status": status,
        "title": title or f"Article {item_id}",
        "content_type": content_type,
        "published_at": published_at.astimezone(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# check_daily_digest_uniqueness
# ---------------------------------------------------------------------------


def test_digest_uniqueness_ok_single(tmp_path):
    today_tpe = datetime(2026, 6, 24, 10, 0, tzinfo=TPE)
    storage = _write_feed(
        tmp_path,
        [
            _entry(
                "mile_a",
                published_at=today_tpe.replace(hour=2),
                title="每日精選導讀｜A",
                content_type="daily_digest",
            )
        ],
    )
    result = cq.check_daily_digest_uniqueness(str(storage), now=today_tpe)
    assert result["status"] == "ok"
    assert result["published_count"] == 1


def test_digest_uniqueness_breach_two_on_same_day(tmp_path):
    """The exact 2026-06-24 incident: two digests both published 02:xx TPE."""
    today_tpe = datetime(2026, 6, 24, 10, 0, tzinfo=TPE)
    storage = _write_feed(
        tmp_path,
        [
            _entry(
                "mile_f3e389cf",
                published_at=today_tpe.replace(hour=2, minute=16),
                title="每日精選導讀｜隔夜波動率",
                content_type="daily_digest",
            ),
            _entry(
                "mile_1597b341",
                published_at=today_tpe.replace(hour=2, minute=34),
                title="每日精選導讀｜分散投資的幻覺",
                content_type="daily_digest",
            ),
        ],
    )
    result = cq.check_daily_digest_uniqueness(str(storage), now=today_tpe)
    assert result["status"] == "duplicate"
    assert result["published_count"] == 2
    assert {x["id"] for x in result["items"]} == {"mile_f3e389cf", "mile_1597b341"}


def test_digest_uniqueness_recognises_by_title_prefix_without_content_type(tmp_path):
    today_tpe = datetime(2026, 6, 24, 10, 0, tzinfo=TPE)
    storage = _write_feed(
        tmp_path,
        [
            _entry(
                "mile_a",
                published_at=today_tpe.replace(hour=2),
                title="每日精選導讀｜A",
                content_type=None,
            ),
            _entry(
                "mile_b",
                published_at=today_tpe.replace(hour=3),
                title="每日精選導讀｜B",
                content_type=None,
            ),
        ],
    )
    result = cq.check_daily_digest_uniqueness(str(storage), now=today_tpe)
    assert result["status"] == "duplicate"


def test_digest_uniqueness_unpublished_excluded(tmp_path):
    today_tpe = datetime(2026, 6, 24, 10, 0, tzinfo=TPE)
    storage = _write_feed(
        tmp_path,
        [
            _entry(
                "mile_dup",
                published_at=today_tpe.replace(hour=2, minute=16),
                title="每日精選導讀｜retracted",
                content_type="daily_digest",
                status="unpublished",
            ),
            _entry(
                "mile_kept",
                published_at=today_tpe.replace(hour=2, minute=34),
                title="每日精選導讀｜kept",
                content_type="daily_digest",
            ),
        ],
    )
    result = cq.check_daily_digest_uniqueness(str(storage), now=today_tpe)
    assert result["status"] == "ok"
    assert result["published_count"] == 1


def test_digest_uniqueness_ignores_other_days(tmp_path):
    today_tpe = datetime(2026, 6, 24, 10, 0, tzinfo=TPE)
    yesterday = today_tpe - timedelta(days=1)
    storage = _write_feed(
        tmp_path,
        [
            _entry(
                "mile_today",
                published_at=today_tpe.replace(hour=2),
                title="每日精選導讀｜today",
                content_type="daily_digest",
            ),
            _entry(
                "mile_yesterday",
                published_at=yesterday.replace(hour=2),
                title="每日精選導讀｜yesterday",
                content_type="daily_digest",
            ),
        ],
    )
    result = cq.check_daily_digest_uniqueness(str(storage), now=today_tpe)
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# check_title_format
# ---------------------------------------------------------------------------


def test_title_format_flags_digest_prefix_duplication(tmp_path):
    today_tpe = datetime(2026, 6, 24, 10, 0, tzinfo=TPE)
    storage = _write_feed(
        tmp_path,
        [
            _entry(
                "mile_a",
                published_at=today_tpe,
                title="每日精選導讀｜分散投資的幻覺",
                content_type="daily_digest",
            ),
        ],
    )
    result = cq.check_title_format(str(storage))
    issues = {f["issue"] for f in result["findings"]}
    assert "digest_prefix_duplicates_section_header" in issues


def test_title_format_normal_non_digest_with_pipe_ok(tmp_path):
    today_tpe = datetime(2026, 6, 24, 10, 0, tzinfo=TPE)
    storage = _write_feed(
        tmp_path,
        [
            _entry(
                "mile_normal",
                published_at=today_tpe,
                title="VIX 倒掛｜CPI 前夕的訊號",
                content_type=None,
            )
        ],
    )
    result = cq.check_title_format(str(storage))
    assert result["status"] == "ok"


def test_title_format_flags_overly_long(tmp_path):
    today_tpe = datetime(2026, 6, 24, 10, 0, tzinfo=TPE)
    storage = _write_feed(
        tmp_path,
        [_entry("mile_long", published_at=today_tpe, title="A" * 200)],
    )
    result = cq.check_title_format(str(storage))
    assert any(f["issue"] == "too_long" for f in result["findings"])


# ---------------------------------------------------------------------------
# check_publish_rhythm
# ---------------------------------------------------------------------------


def test_rhythm_burst_detected_inside_active_window(tmp_path):
    now_tpe = datetime(2026, 6, 24, 11, 0, tzinfo=TPE)
    storage = _write_feed(
        tmp_path,
        [
            _entry("a", published_at=now_tpe - timedelta(minutes=5)),
            _entry("b", published_at=now_tpe - timedelta(minutes=15)),
            _entry("c", published_at=now_tpe - timedelta(minutes=20)),
        ],
    )
    result = cq.check_publish_rhythm(str(storage), now=now_tpe.astimezone(timezone.utc))
    assert result["status"] == "burst"
    assert len(result["burst_pairs"]) >= 1


def test_rhythm_drought_detected_inside_active_window(tmp_path):
    now_tpe = datetime(2026, 6, 24, 14, 0, tzinfo=TPE)
    storage = _write_feed(
        tmp_path,
        [
            _entry("a", published_at=now_tpe - timedelta(hours=4)),
            _entry("b", published_at=now_tpe - timedelta(hours=8)),
        ],
    )
    result = cq.check_publish_rhythm(str(storage), now=now_tpe.astimezone(timezone.utc))
    assert result["status"] == "drought"


def test_rhythm_quiet_outside_active_window(tmp_path):
    """Overnight (02:00 TPE) we deliberately do not raise rhythm alerts."""
    now_tpe = datetime(2026, 6, 24, 2, 30, tzinfo=TPE)
    storage = _write_feed(
        tmp_path,
        [_entry("a", published_at=now_tpe - timedelta(hours=10))],
    )
    result = cq.check_publish_rhythm(str(storage), now=now_tpe.astimezone(timezone.utc))
    assert result["status"] == "inactive_window"


def test_rhythm_ok_steady_inside_active_window(tmp_path):
    now_tpe = datetime(2026, 6, 24, 14, 0, tzinfo=TPE)
    storage = _write_feed(
        tmp_path,
        [
            _entry("a", published_at=now_tpe - timedelta(minutes=45)),
            _entry("b", published_at=now_tpe - timedelta(minutes=120)),
        ],
    )
    result = cq.check_publish_rhythm(str(storage), now=now_tpe.astimezone(timezone.utc))
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# content_quality_snapshot
# ---------------------------------------------------------------------------


def test_snapshot_aggregates_all_checks(tmp_path):
    now_tpe = datetime(2026, 6, 24, 11, 0, tzinfo=TPE)
    storage = _write_feed(
        tmp_path,
        [
            _entry(
                "mile_dup_1",
                published_at=now_tpe.replace(hour=2),
                title="每日精選導讀｜A",
                content_type="daily_digest",
            ),
            _entry(
                "mile_dup_2",
                published_at=now_tpe.replace(hour=3),
                title="每日精選導讀｜B",
                content_type="daily_digest",
            ),
        ],
    )
    snapshot = cq.content_quality_snapshot(
        str(storage), now=now_tpe.astimezone(timezone.utc)
    )
    assert set(snapshot) >= {
        "generated_at",
        "publish_rhythm",
        "daily_digest_uniqueness",
        "title_format",
    }
    assert snapshot["daily_digest_uniqueness"]["status"] == "duplicate"
    title_issues = {f["issue"] for f in snapshot["title_format"]["findings"]}
    assert "digest_prefix_duplicates_section_header" in title_issues


def test_snapshot_empty_feed(tmp_path):
    storage = _write_feed(tmp_path, [])
    snapshot = cq.content_quality_snapshot(str(storage))
    assert snapshot["daily_digest_uniqueness"]["status"] == "ok"
    assert snapshot["title_format"]["status"] == "ok"
