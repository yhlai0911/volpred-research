"""Digest archive-span gate — daily_digest must curate across the whole
archive, not recap the last week or two (boss requirement 2026-07-01 ×3 +
2026-07-05). Mechanical enforcement of what previously lived only in the
enqueue prompt string.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from volpred.publisher.publisher import _audit_digest_archive_span


def _feed(dates_by_slug: dict[str, str]) -> list[dict]:
    return [{"id": s, "published_at": d} for s, d in dates_by_slug.items()]


DG_DATE = "2026-07-05T00:00:00+00:00"


def _days_ago(n: int) -> str:
    return (datetime(2026, 7, 5, tzinfo=timezone.utc) - timedelta(days=n)).date().isoformat()


def test_recent_recap_is_blocked():
    """All sources within the last ~10 days → span < 14 → BLOCK."""
    feed = _feed({
        "a": _days_ago(1), "b": _days_ago(3), "c": _days_ago(5),
        "d": _days_ago(8), "e": _days_ago(10),
    })
    issues, _ = _audit_digest_archive_span(
        {"digest_articles": ["a", "b", "c", "d", "e"]}, DG_DATE, feed,
    )
    assert issues, "a 10-day-span recap must block"
    assert "recap" in issues[0] or "跨度" in issues[0]


def test_whole_archive_curation_passes_clean():
    """Sources spanning ~3 months with several old ones → no issue, no warn."""
    feed = _feed({
        "a": _days_ago(6), "b": _days_ago(26), "c": _days_ago(46),
        "d": _days_ago(35), "e": _days_ago(83),
    })  # mirrors the real 2026-07-04 digest (span 77d, 4 older than 30d)
    issues, warnings = _audit_digest_archive_span(
        {"digest_articles": ["a", "b", "c", "d", "e"]}, DG_DATE, feed,
    )
    assert issues == []
    assert warnings == []


def test_borderline_span_warns_but_publishes():
    """span 24d, few old sources → WARN not BLOCK (mirrors real 2026-07-03)."""
    feed = _feed({
        "a": _days_ago(5), "b": _days_ago(8), "c": _days_ago(12),
        "d": _days_ago(20), "e": _days_ago(29),
    })
    issues, warnings = _audit_digest_archive_span(
        {"digest_articles": ["a", "b", "c", "d", "e"]}, DG_DATE, feed,
    )
    assert issues == [], "24-day span should warn, not block"
    assert warnings, "borderline digest should warn to reach deeper"


def test_missing_digest_articles_fails_open_with_warning():
    issues, warnings = _audit_digest_archive_span({"digest_articles": []}, DG_DATE, [])
    assert issues == []  # fail-open: never block on missing data
    assert warnings


def test_unresolvable_slugs_fail_open():
    """Slugs not in feed → cannot check → warn, never block."""
    issues, warnings = _audit_digest_archive_span(
        {"digest_articles": ["ghost1", "ghost2", "ghost3"]}, DG_DATE, [],
    )
    assert issues == []
    assert warnings


def test_none_details_is_safe():
    issues, warnings = _audit_digest_archive_span(None, DG_DATE, [])
    assert issues == []


# ---------------------------------------------------------------------------
# Calibration guard: the 5 real recent digests must NOT be false-blocked.
# ---------------------------------------------------------------------------

def test_real_recent_digests_are_not_false_blocked():
    """Regression against the actual 2026-06-30..07-04 digests (measured spans
    24-98 days). None should hard-block; the gate targets genuine recaps only."""
    real = {
        "2026-07-04": [6, 26, 46, 35, 83],   # span 77
        "2026-07-03": [5, 8, 20, 12, 29, 24],  # span 24
        "2026-07-02": [11, 30, 50, 70, 98, 40, 20, 60],  # span 98
        "2026-07-01": [3, 15, 29, 20, 25, 10, 8, 18],  # span 29
        "2026-06-30": [1, 10, 15, 20, 25, 22],  # span 24
    }
    for label, ages in real.items():
        feed = _feed({f"{label}-{i}": _days_ago(a) for i, a in enumerate(ages)})
        slugs = [f"{label}-{i}" for i in range(len(ages))]
        issues, _ = _audit_digest_archive_span({"digest_articles": slugs}, DG_DATE, feed)
        assert issues == [], f"{label} digest must not be false-blocked: {issues}"
