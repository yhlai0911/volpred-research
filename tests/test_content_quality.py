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


def test_digest_uniqueness_recognises_details_content_type_without_prefix(tmp_path):
    """Publisher writes daily_digest under details.content_type, not top-level."""
    today_tpe = datetime(2026, 6, 24, 10, 0, tzinfo=TPE)
    item = _entry(
        "mile_digest",
        published_at=today_tpe.replace(hour=2),
        title="事件日前別急著躲",
        content_type=None,
    )
    item["details"] = {"content_type": "daily_digest"}
    storage = _write_feed(tmp_path, [item])

    result = cq.check_daily_digest_uniqueness(str(storage), now=today_tpe)

    assert result["status"] == "ok"
    assert result["published_count"] == 1
    assert result["items"][0]["id"] == "mile_digest"


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


# ---------------------------------------------------------------------------
# 2026-06-29 patrol completion: arc_diversity / content_completeness /
# release_deadlock / frontend_render
# ---------------------------------------------------------------------------
def _entry_full(item_id, *, published_at, arc=None, content="", details=None):
    e = _entry(item_id, published_at=published_at)
    e["content"] = content
    if arc is not None:
        e.setdefault("details", {})["arc_signature"] = arc
    if details is not None:
        e["details"] = {**e.get("details", {}), **details}
    return e


def test_arc_diversity_flags_concentration(tmp_path):
    base = datetime(2026, 6, 24, 12, 0, tzinfo=TPE)
    items = [
        _entry_full(f"m{i}", published_at=base - timedelta(hours=i), arc="same_arc")
        for i in range(10)
    ]
    storage = _write_feed(tmp_path, items)
    r = cq.check_arc_diversity(str(storage))
    assert r["status"] == "concentrated"
    assert r["top_axis"] == "same_arc"
    assert r["top_share"] == 1.0


def test_arc_diversity_ok_when_varied(tmp_path):
    base = datetime(2026, 6, 24, 12, 0, tzinfo=TPE)
    items = [
        _entry_full(f"m{i}", published_at=base - timedelta(hours=i), arc=f"arc_{i}")
        for i in range(10)
    ]
    storage = _write_feed(tmp_path, items)
    r = cq.check_arc_diversity(str(storage))
    assert r["status"] == "ok"


def test_content_completeness_chartable_details_not_flagged(tmp_path):
    base = datetime(2026, 6, 24, 12, 0, tzinfo=TPE)
    # No inline chart marker, but details carries numeric metric data the frontend
    # renders → must NOT be flagged missing_chart. Source via K-id in content.
    items = [
        _entry_full(
            "m1",
            published_at=base,
            content="本文回測 K1234 的結果。",
            details={"dm_stat": 2.1, "pvalue": 0.03},
        )
    ]
    storage = _write_feed(tmp_path, items)
    r = cq.check_content_completeness(str(storage))
    assert r["status"] == "ok"


def test_content_completeness_flags_missing_chart(tmp_path):
    base = datetime(2026, 6, 24, 12, 0, tzinfo=TPE)
    items = [
        _entry_full("m1", published_at=base, content="這是純文字內容，引用 K123 為來源。", details={})
    ]
    storage = _write_feed(tmp_path, items)
    r = cq.check_content_completeness(str(storage))
    assert r["status"] == "incomplete"
    assert r["findings"][0]["missing_chart"] is True
    assert r["findings"][0]["missing_source"] is False  # K-id + 來源 present


def test_release_deadlock_when_candidates_empty(tmp_path):
    storage = tmp_path / "storage"
    (storage).mkdir(parents=True)
    (storage / "publication_candidates.json").write_text(
        json.dumps({"candidates": [], "top_10_uncovered": []}), encoding="utf-8"
    )
    r = cq.check_release_deadlock(str(storage))
    assert r["status"] == "deadlock"
    assert r["total"] == 0


def test_release_deadlock_unknown_when_file_missing(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir(parents=True)
    r = cq.check_release_deadlock(str(storage))
    assert r["status"] == "unknown"  # missing file ≠ deadlock (no false critical)


def test_frontend_render_uses_injected_fetcher(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir(parents=True)
    ok = cq.check_frontend_render(str(storage), fetcher=lambda u, t: (200, "<html>fine</html>"))
    assert ok["status"] == "ok"
    react = cq.check_frontend_render(
        str(storage), fetcher=lambda u, t: (200, "Minified React error #418")
    )
    assert react["status"] == "error"
    down = cq.check_frontend_render(str(storage), fetcher=lambda u, t: (500, "oops"))
    assert down["status"] == "error"


def test_frontend_render_fail_open_on_network_error(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir(parents=True)

    def boom(url, timeout):
        raise OSError("network down")

    r = cq.check_frontend_render(str(storage), fetcher=boom)
    assert r["status"] == "unknown"  # fail-open, never a breach


def test_frontend_render_disabled_probe(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir(parents=True)
    r = cq.check_frontend_render(str(storage), probe=False)
    assert r["status"] == "unknown"
    assert r["probed"] is False
