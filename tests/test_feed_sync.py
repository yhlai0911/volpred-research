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

from volpred.ops.feed_sync import compute_diff


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
        "published_at": "2026-04-20T00:00:00+00:00",
        "content": "Same content",
    }
    with patch("volpred.ops.feed_sync._fetch_supabase_articles", return_value={"mile_t2": db_row}):
        diff = compute_diff(storage_dir=str(tmp_path / "storage"))
    assert "mile_t2" in diff["update"]


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
        "published_at": "2026-04-20T00:00:00+00:00",
        "content": "content-as-description",
    }
    with patch("volpred.ops.feed_sync._fetch_supabase_articles", return_value={"mile_t3": db_row}):
        diff = compute_diff(storage_dir=str(tmp_path / "storage"))
    assert "mile_t3" not in diff["update"], (
        "feed 'description' field should hash-match DB 'content' field"
    )
