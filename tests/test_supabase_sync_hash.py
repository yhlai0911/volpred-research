"""Tests for content-hash-based incremental article sync.

3-Strike regression (2026-06-03, docs/refactor_plan_prepublish_content_gate.md,
根因 B): the prior timestamp-gated incremental filter silently skipped articles
whose content was edited without bumping a timestamp. _article_hash makes change
detection content-based and timestamp-decoupled.
"""
from __future__ import annotations

import importlib.util
import json
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


def test_sync_full_ignores_stale_single_report_content(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    reports = storage / "reports"
    reports.mkdir(parents=True)

    feed_item = {
        "id": "mile_stale_single",
        "title": "Current feed article",
        "content": "CURRENT FEED CONTENT",
        "status": "published",
        "audience": "research",
        "category": "milestone",
        "details": {"experiment_refs": ["K1339"]},
        "published_at": "2026-06-29T00:00:00+00:00",
    }
    (reports / "feed.json").write_text(json.dumps([feed_item]), encoding="utf-8")
    (reports / "mile_stale_single.json").write_text(
        json.dumps(
            {
                "id": "mile_stale_single",
                "title": "Old single article",
                "content": "STALE SINGLE CONTENT",
                "status": "draft",
            }
        ),
        encoding="utf-8",
    )

    synced: list[dict] = []

    def fake_sync_article(item: dict, storage_dir: str | Path = "storage") -> bool:
        synced.append(dict(item))
        return True

    monkeypatch.setattr(supabase_sync, "sync_article", fake_sync_article)

    counts = supabase_sync.sync_full(storage)

    assert counts["articles"] == 1
    assert synced[0]["content"] == "CURRENT FEED CONTENT"
    assert synced[0]["status"] == "published"
    assert synced[0]["title"] == "Current feed article"
    assert synced[0]["content"] != "STALE SINGLE CONTENT"


def _capture_select_rows(monkeypatch, total_rows: int):
    """Mock _request_json so _select_rows pages over `total_rows` synthetic rows.

    Returns (rows, urls) after invoking _select_rows("articles", order_by="id").
    """
    all_rows = [{"id": i, "slug": f"mile_{i:04d}"} for i in range(total_rows)]
    urls: list[str] = []

    def fake_request_json(url, method="GET", data=None):
        urls.append(url)
        # Parse limit/offset out of the URL to serve the right slice.
        import urllib.parse as _up

        q = _up.parse_qs(_up.urlparse(url).query)
        limit = int(q["limit"][0])
        offset = int(q["offset"][0])
        return all_rows[offset : offset + limit]

    monkeypatch.setattr(supabase_sync, "_request_json", fake_request_json)
    rows = supabase_sync._select_rows("articles", select="id,slug", order_by="id")
    return rows, urls


def test_select_rows_paginates_beyond_1000(monkeypatch):
    # 1966 rows (the real articles-table count that exposed the cap bug) must
    # all be returned, not just the first PostgREST page of 1000.
    rows, urls = _capture_select_rows(monkeypatch, 1966)
    assert len(rows) == 1966
    assert [r["id"] for r in rows] == list(range(1966))  # no gaps / dupes
    assert len(urls) == 2  # page0 (1000) + page1 (966, short → stop)
    # Race-safe ordering must be present on every paged request.
    assert all("order=id" in u for u in urls)


def test_select_rows_exact_1000_boundary(monkeypatch):
    # Exactly page_size rows: first full page, then one empty page terminates
    # the loop — no infinite loop, no dropped rows.
    rows, urls = _capture_select_rows(monkeypatch, 1000)
    assert len(rows) == 1000
    assert len(urls) == 2  # full page + empty page
    assert urls[1].endswith("offset=1000")


def test_select_rows_single_short_page(monkeypatch):
    rows, urls = _capture_select_rows(monkeypatch, 137)
    assert len(rows) == 137
    assert len(urls) == 1  # short first page stops immediately


def test_sync_article_readback_repairs_audience_only_drift(monkeypatch):
    """HTTP-successful upsert is not enough: verify reader routing metadata."""
    selected: list[tuple[str, str]] = []
    patches: list[tuple[str, dict, dict]] = []

    monkeypatch.setattr(supabase_sync, "_post", lambda *args, **kwargs: True)

    def fake_select(table, *, select="*", order_by=None, **filters):
        selected.append((table, select))
        return [
            {
                "slug": "mile_audience_readback",
                "status": "published",
                "published_at": "2026-07-15T00:00:00+00:00",
                "audience": "general",
            }
        ]

    def fake_patch(table, filters, row):
        patches.append((table, filters, row))
        return True

    monkeypatch.setattr(supabase_sync, "_select_rows", fake_select)
    monkeypatch.setattr(supabase_sync, "_patch_where", fake_patch)

    ok = supabase_sync.sync_article(
        {
            "id": "mile_audience_readback",
            "title": "Audience correction",
            "content": "Body",
            "status": "published",
            "audience": "research",
            "published_at": "2026-07-15T00:00:00+00:00",
        }
    )

    assert ok is True
    assert selected == [
        ("articles", "slug,status,published_at,audience")
    ]
    assert patches == [
        (
            "articles",
            {"slug": "mile_audience_readback"},
            {
                "status": "published",
                "audience": "research",
                "published_at": "2026-07-15T00:00:00+00:00",
            },
        )
    ]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
