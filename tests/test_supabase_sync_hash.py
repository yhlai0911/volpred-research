"""Tests for content-hash-based incremental article sync.

3-Strike regression (2026-06-03, docs/refactor_plan_prepublish_content_gate.md,
根因 B): the prior timestamp-gated incremental filter silently skipped articles
whose content was edited without bumping a timestamp. _article_hash makes change
detection content-based and timestamp-decoupled.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# supabase_sync lives in scripts/ (not a package); load it by path.
_SYNC_PATH = Path(__file__).resolve().parent.parent / "scripts" / "supabase_sync.py"
_spec = importlib.util.spec_from_file_location("supabase_sync", _SYNC_PATH)
supabase_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(supabase_sync)  # type: ignore[union-attr]

_article_hash = supabase_sync._article_hash


def _base_item() -> dict:
    return {
        "id": "mile_abcd1234",
        "title": "AI 五層產業鏈的波動率",
        "content": "基礎設施層最抖，全期年化波動率達 0.517。",
        "excerpt": "跨層相關性視角",
        "status": "published",
        "audience": "research",
        "category": "milestone",
        "details": {"experiment_refs": ["K1413"]},
        # Timestamps deliberately fixed across edits to model the silent-skip bug.
        "created_at": "2026-06-03T00:00:00+00:00",
        "published_at": "2026-06-03T00:00:00+00:00",
        "updated_at": "2026-06-03T00:00:00+00:00",
    }


def test_content_change_without_timestamp_bump_detected():
    old = _base_item()
    new = _base_item()
    # Correct the body (the K1413 fix) but DO NOT touch any timestamp.
    new["content"] = "基礎設施層最抖，最新年化波動率達 0.6463（非晶片層）。"
    assert old["updated_at"] == new["updated_at"]  # timestamp identical
    assert _article_hash(old) != _article_hash(new), (
        "content edit must flip the hash even with unchanged timestamps"
    )


def test_identical_item_is_idempotent():
    a = _base_item()
    b = _base_item()
    assert _article_hash(a) == _article_hash(b)
    # Re-hashing the same object is stable.
    assert _article_hash(a) == _article_hash(a)


def test_status_change_detected():
    old = _base_item()
    new = _base_item()
    new["status"] = "draft"
    assert _article_hash(old) != _article_hash(new)


def test_details_change_detected():
    old = _base_item()
    new = _base_item()
    new["details"] = {"experiment_refs": ["K1413", "K1414"]}
    assert _article_hash(old) != _article_hash(new)


def test_non_syncable_field_change_ignored():
    # A field outside _ARTICLE_HASH_FIELDS (e.g. created_at) must not flip hash.
    old = _base_item()
    new = _base_item()
    new["created_at"] = "2030-01-01T00:00:00+00:00"
    assert _article_hash(old) == _article_hash(new)


def test_hash_field_set_matches_plan():
    expected = {"content", "title", "excerpt", "status", "audience", "category", "details"}
    assert set(supabase_sync._ARTICLE_HASH_FIELDS) == expected


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
