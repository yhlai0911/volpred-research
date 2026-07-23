"""Tests for src/volpred/ops/feed_sync.py — content-hash drift detection.

Covers 2026-04-20 fix per K1257 article incident: compute_diff now detects
content drift beyond just status/title/published_at, so post-publish content
edits propagate to Supabase.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from volpred.ops.feed_sync import compute_diff, reconcile_content_from_singles


@pytest.fixture(autouse=True)
def _no_production_tag_reads(monkeypatch):
    """`compute_diff()` fetches article TAGS as well as articles.

    Every test below patched `_fetch_supabase_articles` but not
    `_fetch_supabase_article_tags`, so each run issued three real `_select_rows`
    reads against **production Supabase** (articles / article_tags / tags). It
    went unnoticed because credentials were always present locally; on a
    credential-less checkout it surfaced as `Missing SUPABASE_URL` (2026-07-10,
    while wiring pytest into CI). Autouse so a new test in this file cannot
    reintroduce the prod read by forgetting one patch.
    """
    monkeypatch.setattr(
        "volpred.ops.feed_sync._fetch_supabase_article_tags", lambda *a, **k: {}
    )


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def test_compute_diff_detects_content_change_even_when_metadata_identical(tmp_path, monkeypatch):
    """When feed and DB share same title/status/published_at but content differs,
    compute_diff must mark for UPDATE."""
    feed_item = {
        "id": "mile_test001",
        "title": "Test Article",
        "status": "published",
        "published_at": "2026-04-20T00:00:00+00:00",
        "content": "Original content v1",
    }
    db_row = {
        "slug": "mile_test001",
        "title": "Test Article",
        "status": "published",
        "audience": "research",
        "published_at": "2026-04-20T00:00:00+00:00",
        "content": "Extended content v2 with more analysis",  # Post-publish extension
    }

    storage = tmp_path / "storage"
    storage.mkdir()
    reports = storage / "reports"
    reports.mkdir()
    feed_path = reports / "feed.json"
    feed_path.write_text('[{"id": "mile_test001", "title": "Test Article", '
                         '"status": "published", '
                         '"published_at": "2026-04-20T00:00:00+00:00", '
                         '"content": "Original content v1"}]')

    with patch("volpred.ops.feed_sync._fetch_supabase_articles", return_value={"mile_test001": db_row}):
        diff = compute_diff(storage_dir=str(storage))

    assert "mile_test001" in diff["update"], (
        "Content change must trigger UPDATE even when title/status/published_at match"
    )


def test_compute_diff_no_change_when_content_identical(tmp_path, monkeypatch):
    """When content + metadata all match, no UPDATE needed."""
    identical_content = "Same content everywhere"
    feed_path_dir = tmp_path / "storage" / "reports"
    feed_path_dir.mkdir(parents=True)
    (feed_path_dir / "feed.json").write_text(
        f'[{{"id": "mile_same", "title": "Same", "status": "published", '
        f'"published_at": "2026-04-20T00:00:00+00:00", '
        f'"content": "{identical_content}"}}]'
    )
    db_row = {
        "slug": "mile_same",
        "title": "Same",
        "status": "published",
        "audience": "research",
        "category": "milestone",
        "published_at": "2026-04-20T00:00:00+00:00",
        "content": identical_content,
    }
    with patch("volpred.ops.feed_sync._fetch_supabase_articles", return_value={"mile_same": db_row}):
        diff = compute_diff(storage_dir=str(tmp_path / "storage"))
    assert "mile_same" not in diff["update"]
    assert "mile_same" not in diff["insert"]
    assert "mile_same" not in diff["delete"]


def test_compute_diff_still_detects_title_change(tmp_path, monkeypatch):
    """Regression: metadata-only drift (pre-fix behavior) still works."""
    feed_path_dir = tmp_path / "storage" / "reports"
    feed_path_dir.mkdir(parents=True)
    (feed_path_dir / "feed.json").write_text(
        '[{"id": "mile_t2", "title": "New Title", "status": "published", '
        '"published_at": "2026-04-20T00:00:00+00:00", '
        '"content": "Same content"}]'
    )
    db_row = {
        "slug": "mile_t2",
        "title": "Old Title",  # DIFFERENT
        "status": "published",
        "audience": "research",
        "published_at": "2026-04-20T00:00:00+00:00",
        "content": "Same content",
    }
    with patch("volpred.ops.feed_sync._fetch_supabase_articles", return_value={"mile_t2": db_row}):
        diff = compute_diff(storage_dir=str(tmp_path / "storage"))
    assert "mile_t2" in diff["update"]


def test_compute_diff_detects_audience_only_change(tmp_path, monkeypatch):
    """A local audience correction must update the remote projection.

    Regression: feed-sync previously omitted ``audience`` from both its remote
    SELECT and comparison, so a general -> research backfill looked clean when
    every other article field matched.
    """
    feed_path_dir = tmp_path / "storage" / "reports"
    feed_path_dir.mkdir(parents=True)
    (feed_path_dir / "feed.json").write_text(
        '[{"id": "mile_audience", "title": "Same", "status": "published", '
        '"audience": "research", '
        '"published_at": "2026-04-20T00:00:00+00:00", '
        '"content": "Same content"}]'
    )
    db_row = {
        "slug": "mile_audience",
        "title": "Same",
        "status": "published",
        "audience": "general",  # only drift
        "category": "milestone",
        "published_at": "2026-04-20T00:00:00+00:00",
        "content": "Same content",
    }

    selects: list[str] = []

    def fake_select(table, *, select="*", order_by=None, **filters):
        assert table == "articles"
        selects.append(select)
        return [db_row]

    monkeypatch.setattr("volpred.ops.feed_sync._select_rows", fake_select)
    diff = compute_diff(storage_dir=str(tmp_path / "storage"))

    assert diff["update"] == ["mile_audience"]
    assert selects == [
        "slug,status,title,published_at,updated_at,content,details,"
        "audience,category,phase"
    ]


def test_compute_diff_description_fallback_for_content(tmp_path, monkeypatch):
    """Feed item using 'description' field (not 'content') should hash description."""
    feed_path_dir = tmp_path / "storage" / "reports"
    feed_path_dir.mkdir(parents=True)
    (feed_path_dir / "feed.json").write_text(
        '[{"id": "mile_t3", "title": "T3", "status": "published", '
        '"published_at": "2026-04-20T00:00:00+00:00", '
        '"description": "content-as-description"}]'
    )
    db_row = {
        "slug": "mile_t3",
        "title": "T3",
        "status": "published",
        "audience": "research",
        "category": "milestone",
        "published_at": "2026-04-20T00:00:00+00:00",
        "content": "content-as-description",
    }
    with patch("volpred.ops.feed_sync._fetch_supabase_articles", return_value={"mile_t3": db_row}):
        diff = compute_diff(storage_dir=str(tmp_path / "storage"))
    assert "mile_t3" not in diff["update"], (
        "feed 'description' field should hash-match DB 'content' field"
    )


# --- WS-C3 (2026-07-20): compute_diff is the single canonical change engine --
#
# sync_full's parallel _article_hash/timestamp criterion was deleted; these
# tests pin that compute_diff covers every change class the hash engine
# covered (category, full details) plus phase, and stays idempotent against
# its own written projection.

import json as _json


def _write_feed(tmp_path, item: dict) -> str:
    feed_dir = tmp_path / "storage" / "reports"
    feed_dir.mkdir(parents=True, exist_ok=True)
    (feed_dir / "feed.json").write_text(
        _json.dumps([item], ensure_ascii=False), encoding="utf-8"
    )
    return str(tmp_path / "storage")


def _clean_pair() -> tuple[dict, dict]:
    """A feed item and a DB row that are projection-identical (diff clean)."""
    feed_item = {
        "id": "mile_ws_c3",
        "title": "WS-C3 base",
        "status": "published",
        "audience": "research",
        "category": "milestone",
        "published_at": "2026-07-20T00:00:00+00:00",
        "content": "base content",
        "details": {"experiment_refs": ["K1700"]},
    }
    db_row = {
        "slug": "mile_ws_c3",
        "title": "WS-C3 base",
        "status": "published",
        "audience": "research",
        "category": "milestone",
        "phase": None,
        "published_at": "2026-07-20T00:00:00+00:00",
        "content": "base content",
        "details": {"experiment_refs": ["K1700"]},
    }
    return feed_item, db_row


def _diff_for(tmp_path, feed_item: dict, db_row: dict) -> dict:
    storage = _write_feed(tmp_path, feed_item)
    with patch(
        "volpred.ops.feed_sync._fetch_supabase_articles",
        return_value={db_row["slug"]: db_row},
    ):
        return compute_diff(storage_dir=storage)


def test_clean_pair_is_clean(tmp_path):
    """Baseline sanity: the fixture pair must produce an empty diff, or every
    mutation test below would pass vacuously."""
    feed_item, db_row = _clean_pair()
    diff = _diff_for(tmp_path, feed_item, db_row)
    assert diff["update"] == [] and diff["insert"] == []


def test_compute_diff_detects_category_only_change(tmp_path):
    """Engine-A parity: category was in _article_hash but not compared here.

    A category correction (e.g. milestone -> member_qa) must re-sync now that
    compute_diff is the only change engine."""
    feed_item, db_row = _clean_pair()
    feed_item["category"] = "qa_special"
    diff = _diff_for(tmp_path, feed_item, db_row)
    assert diff["update"] == ["mile_ws_c3"]


def test_compute_diff_detects_details_change_outside_experiment_refs(tmp_path):
    """Engine-A parity: the FULL details jsonb is compared, not just
    experiment_refs — fb_post_url / event_series_slot / digest metadata edits
    must propagate."""
    feed_item, db_row = _clean_pair()
    feed_item["details"] = {
        "experiment_refs": ["K1700"],
        "fb_post_url": "https://facebook.com/x",
    }
    diff = _diff_for(tmp_path, feed_item, db_row)
    assert diff["update"] == ["mile_ws_c3"]


def test_compute_diff_projects_retraction_audit_metadata(tmp_path):
    """A retraction is not synced if only its status reaches Supabase.

    Successor, errata and explicit no-successor metadata live at feed top level
    but must be projected into the remote details jsonb column.
    """
    feed_item, db_row = _clean_pair()
    feed_item.update(
        {
            "status": "retracted",
            "retracted_reason": "material factual error",
            "retracted_superseded_by": ["mile_successor"],
            "retracted_errata_ref": "task:correction-1",
            "retracted_no_successor_reason": None,
            "retraction_schema_version": 1,
        }
    )
    db_row["status"] = "retracted"

    diff = _diff_for(tmp_path, feed_item, db_row)
    assert diff["update"] == ["mile_ws_c3"]

    db_row["details"] = {
        **db_row["details"],
        "retracted_reason": "material factual error",
        "retracted_superseded_by": ["mile_successor"],
        "retracted_errata_ref": "task:correction-1",
        "retracted_no_successor_reason": None,
        "retraction_schema_version": 1,
    }
    diff = _diff_for(tmp_path, feed_item, db_row)
    assert diff["update"] == []


def test_compute_diff_still_detects_experiment_refs_change(tmp_path):
    """Regression for the 2026-04-26 K-id migration case, now covered via the
    full-details comparison instead of the deleted refs-only check."""
    feed_item, db_row = _clean_pair()
    feed_item["details"] = {"experiment_refs": ["K1700", "K1701"]}
    diff = _diff_for(tmp_path, feed_item, db_row)
    assert diff["update"] == ["mile_ws_c3"]


def test_compute_diff_detects_phase_change(tmp_path):
    """phase is a written column both old engines missed; compare it so the
    invariant 'every non-derived written column is compared' holds."""
    feed_item, db_row = _clean_pair()
    feed_item["phase"] = "research_myth_vix"
    diff = _diff_for(tmp_path, feed_item, db_row)
    assert diff["update"] == ["mile_ws_c3"]


def test_compute_diff_idempotent_after_last_updated_at_injection(tmp_path):
    """sync_article injects top-level last_updated_at into details; the differ
    must apply the same projection or the row would re-update forever."""
    feed_item, db_row = _clean_pair()
    feed_item["last_updated_at"] = "2026-07-20T09:00:00+08:00"
    db_row["details"] = {
        "experiment_refs": ["K1700"],
        "last_updated_at": "2026-07-20T09:00:00+08:00",
    }
    diff = _diff_for(tmp_path, feed_item, db_row)
    assert diff["update"] == [], "projection-identical row must not re-sync"
    # ...and a NOT-yet-injected DB row must be flagged exactly once.
    db_row["details"] = {"experiment_refs": ["K1700"]}
    diff = _diff_for(tmp_path, feed_item, db_row)
    assert diff["update"] == ["mile_ws_c3"]


def test_compute_diff_ignores_server_resident_view_display(tmp_path):
    """details.view_display is PATCHed straight into the DB row by
    seed_article_view_counts.py and never exists in canonical feed.json.
    Its presence is NOT drift (first full-details dry-run flagged 1576/1854
    rows solely because of it), and a stray feed-side copy must not flag
    either (stripped from both sides)."""
    feed_item, db_row = _clean_pair()
    db_row["details"] = {
        "experiment_refs": ["K1700"],
        "view_display": {"seed": 742, "baseline_real": 38},
    }
    diff = _diff_for(tmp_path, feed_item, db_row)
    assert diff["update"] == []

    feed_item["details"] = {
        "experiment_refs": ["K1700"],
        "view_display": {"seed": 1, "baseline_real": 0},  # stray feed copy
    }
    diff = _diff_for(tmp_path, feed_item, db_row)
    assert diff["update"] == []


def test_compute_diff_idempotent_when_status_key_missing(tmp_path):
    """sync_article defaults a missing status key to 'published'; the differ
    mirrors that default so the row cannot re-update forever."""
    feed_item, db_row = _clean_pair()
    feed_item.pop("status")
    diff = _diff_for(tmp_path, feed_item, db_row)
    assert diff["update"] == []


# Equivalence gate vs deleted engine A: every _ARTICLE_HASH_FIELDS mutation
# that changes the WRITTEN row must be flagged by compute_diff. Recorded
# reasonable difference: raw top-level `excerpt` was hashed by engine A but is
# NOT written to Supabase (the row's excerpt derives from content), so A
# re-pushed a byte-identical row while B correctly stays quiet.
@pytest.mark.parametrize(
    ("field", "new_value", "expect_update"),
    [
        ("content", "edited content", True),
        ("title", "WS-C3 base v2", True),
        ("status", "draft", True),
        ("audience", "member_qa", True),  # explicit non-general reclassifies
        ("category", "qa_special", True),
        ("details", {"experiment_refs": ["K1700"], "note": "x"}, True),
        ("excerpt", "raw excerpt not written to the row", False),
    ],
)
def test_engine_a_hash_field_coverage(tmp_path, field, new_value, expect_update):
    feed_item, db_row = _clean_pair()
    feed_item[field] = new_value
    diff = _diff_for(tmp_path, feed_item, db_row)
    assert (diff["update"] == ["mile_ws_c3"]) is expect_update, (
        f"engine-A hash field {field!r}: compute_diff coverage mismatch"
    )


def test_reconcile_content_from_singles_warns_on_bad_single_json(tmp_path, capsys):
    reports = tmp_path / "storage" / "reports"
    reports.mkdir(parents=True)
    (reports / "feed.json").write_text(
        '[{"id": "mile_good", "title": "Good", "content": "short"}]',
        encoding="utf-8",
    )
    (reports / "mile_good.json").write_text(
        '{"id": "mile_good", "content": "short but not enough gain"}',
        encoding="utf-8",
    )
    (reports / "mile_bad.json").write_text("{bad json", encoding="utf-8")

    result = reconcile_content_from_singles(
        storage_dir=tmp_path / "storage",
        dry_run=True,
        min_gain=100,
    )

    captured = capsys.readouterr()
    assert result["checked_singles"] == 2
    assert result["invalid_singles"] == 1
    assert result["updated"] == 0
    assert "[feed_sync] WARN single article JSON read failed; skipping" in captured.out
    assert "mile_bad.json" in captured.out
    assert "JSONDecodeError" in captured.out
