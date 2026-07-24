"""Tests for sync_full's article path after the WS-C3 engine merge.

History: this file originally pinned `_article_hash` — the 2026-06-03 3-strike
fix (docs/refactor_plan_prepublish_content_gate.md, 根因 B) for the
timestamp-gated incremental filter that silently skipped content edits.
WS-C3 (2026-07-20, refactor_plan_ops_master_2026_07 §1.3 A1) deleted that
engine: change detection is now owned solely by
volpred.ops.feed_sync.compute_diff (feed projection vs actual Supabase rows),
and sync_full delegates its per-article selection there. The filename is kept
so CI history lines up; the tests now pin:

  1. sync_full syncs exactly the compute_diff insert+update set (delegation);
  2. the original 3-strike regression — a content edit WITHOUT any timestamp
     bump still syncs — through the new engine;
  3. failed frontend-cache purges are recorded in state and force a re-sync
     next run even when the projection already matches (the successor of the
     old "withhold the hash" retry);
  4. engine-A state keys (article_hashes / articles_last_ts) are actively
     removed — no second detection criterion may hide in the state file.
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


def _write_feed(storage: Path, items: list[dict]) -> Path:
    reports = storage / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    feed_path = reports / "feed.json"
    feed_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return feed_path


def _state_path(storage: Path) -> Path:
    return storage / ".supabase_sync_state.json"


def _item(slug: str, **overrides) -> dict:
    base = {
        "id": slug,
        "title": f"Article {slug}",
        "content": f"content of {slug}",
        "status": "published",
        "audience": "research",
        "category": "milestone",
        "details": {"experiment_refs": ["K1413"]},
        "published_at": "2026-06-03T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _capture_sync_article(monkeypatch):
    synced: list[dict] = []

    def fake_sync_article(item: dict, storage_dir="storage") -> bool:
        synced.append(dict(item))
        return True

    monkeypatch.setattr(supabase_sync, "sync_article", fake_sync_article)
    return synced


def test_sync_full_delegates_selection_to_compute_diff(tmp_path, monkeypatch):
    """sync_full must push exactly compute_diff's insert+update set, in feed
    order — it holds no per-article change criterion of its own anymore."""
    storage = tmp_path / "storage"
    _write_feed(storage, [_item("mile_a"), _item("mile_b"), _item("mile_c")])
    synced = _capture_sync_article(monkeypatch)

    monkeypatch.setattr(
        "volpred.ops.feed_sync.compute_diff",
        lambda storage_dir="storage": {
            "insert": ["mile_c"],
            "update": ["mile_a"],
            "delete": [],
        },
    )

    counts = supabase_sync.sync_full(storage)

    assert counts["articles"] == 2
    assert [i["id"] for i in synced] == ["mile_a", "mile_c"]  # feed order


def test_content_change_without_timestamp_bump_detected(tmp_path, monkeypatch):
    """The original 3-strike regression, through the canonical engine: editing
    content while leaving every timestamp untouched must still sync."""
    storage = tmp_path / "storage"
    feed_item = _item("mile_k1413", content="最新年化波動率達 0.6463（非晶片層）。")
    _write_feed(storage, [feed_item])
    synced = _capture_sync_article(monkeypatch)

    db_row = {
        "slug": "mile_k1413",
        "title": feed_item["title"],
        "status": "published",
        "audience": "research",
        "category": "milestone",
        "phase": None,
        "published_at": feed_item["published_at"],  # identical timestamp
        "content": "基礎設施層最抖，全期年化波動率達 0.517。",  # stale body
        "details": {"experiment_refs": ["K1413"]},
    }
    monkeypatch.setattr(
        "volpred.ops.feed_sync._fetch_supabase_articles",
        lambda *a, **k: {"mile_k1413": db_row},
    )
    monkeypatch.setattr(
        "volpred.ops.feed_sync._fetch_supabase_article_tags", lambda *a, **k: {}
    )

    counts = supabase_sync.sync_full(storage)

    assert counts["articles"] == 1
    assert synced[0]["content"] == feed_item["content"]


def test_sync_full_clean_projection_syncs_nothing(tmp_path, monkeypatch):
    """A DB row identical to the written projection must not be re-pushed
    (the old hash engine re-pushed on any local ledger miss)."""
    storage = tmp_path / "storage"
    feed_item = _item("mile_clean")
    _write_feed(storage, [feed_item])
    synced = _capture_sync_article(monkeypatch)

    db_row = {
        "slug": "mile_clean",
        "title": feed_item["title"],
        "status": "published",
        "audience": "research",
        "category": "milestone",
        "phase": None,
        "published_at": feed_item["published_at"],
        "content": feed_item["content"],
        "details": {"experiment_refs": ["K1413"]},
    }
    monkeypatch.setattr(
        "volpred.ops.feed_sync._fetch_supabase_articles",
        lambda *a, **k: {"mile_clean": db_row},
    )
    monkeypatch.setattr(
        "volpred.ops.feed_sync._fetch_supabase_article_tags", lambda *a, **k: {}
    )

    counts = supabase_sync.sync_full(storage)

    assert counts["articles"] == 0
    assert synced == []


def test_sync_full_ignores_stale_single_report_content(tmp_path, monkeypatch):
    """2026-06-29 correction regression: feed.json is the article source of
    truth; a stale reports/<id>.json single must never win."""
    storage = tmp_path / "storage"
    feed_item = _item(
        "mile_stale_single",
        title="Current feed article",
        content="CURRENT FEED CONTENT",
    )
    _write_feed(storage, [feed_item])
    (storage / "reports" / "mile_stale_single.json").write_text(
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
    synced = _capture_sync_article(monkeypatch)
    monkeypatch.setattr(
        "volpred.ops.feed_sync._fetch_supabase_articles", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        "volpred.ops.feed_sync._fetch_supabase_article_tags", lambda *a, **k: {}
    )

    counts = supabase_sync.sync_full(storage)

    assert counts["articles"] == 1
    assert synced[0]["content"] == "CURRENT FEED CONTENT"
    assert synced[0]["status"] == "published"
    assert synced[0]["title"] == "Current feed article"


def test_purge_retry_forces_resync_when_projection_clean(tmp_path, monkeypatch):
    """Successor of the old 'withhold the hash' retry: a slug whose frontend
    cache purge failed must be re-synced next run, even when the feed file is
    untouched and the DB projection already matches."""
    storage = tmp_path / "storage"
    feed_path = _write_feed(storage, [_item("mile_retry")])
    _state_path(storage).write_text(
        json.dumps(
            {
                "feed_mtime": feed_path.stat().st_mtime,  # gate closed
                "purge_retry_slugs": ["mile_retry"],
            }
        )
    )
    synced = _capture_sync_article(monkeypatch)
    monkeypatch.setattr(
        "volpred.ops.feed_sync.compute_diff",
        lambda storage_dir="storage": {"insert": [], "update": [], "delete": []},
    )

    counts = supabase_sync.sync_full(storage)

    assert counts["articles"] == 1
    assert [i["id"] for i in synced] == ["mile_retry"]
    state = json.loads(_state_path(storage).read_text())
    assert state["purge_retry_slugs"] == []  # purge succeeded -> cleared


def test_failed_purge_recorded_in_state_for_retry(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    _write_feed(storage, [_item("mile_purgefail")])

    def fake_sync_article(item: dict, storage_dir="storage") -> bool:
        # DB write succeeds but the frontend cache purge fails (recorded the
        # way revalidate_article_cache records it).
        supabase_sync._REVALIDATE_FAILURES.append(item["id"])
        return True

    monkeypatch.setattr(supabase_sync, "sync_article", fake_sync_article)
    monkeypatch.setattr(
        "volpred.ops.feed_sync.compute_diff",
        lambda storage_dir="storage": {
            "insert": [],
            "update": ["mile_purgefail"],
            "delete": [],
        },
    )

    counts = supabase_sync.sync_full(storage)

    assert counts["articles"] == 1  # DB write itself succeeded
    assert counts["cache_purge_failed"] == ["mile_purgefail"]
    state = json.loads(_state_path(storage).read_text())
    assert state["purge_retry_slugs"] == ["mile_purgefail"]


def test_engine_a_state_keys_are_removed(tmp_path, monkeypatch):
    """不留兩套: legacy article_hashes / articles_last_ts must be scrubbed from
    the state file so no second change criterion can silently persist."""
    storage = tmp_path / "storage"
    _write_feed(storage, [_item("mile_scrub")])
    _state_path(storage).write_text(
        json.dumps(
            {
                "feed_mtime": 0,  # gate open
                "article_hashes": {"mile_scrub": "deadbeef"},
                "articles_last_ts": "2026-06-03T00:00:00+00:00",
            }
        )
    )
    _capture_sync_article(monkeypatch)
    monkeypatch.setattr(
        "volpred.ops.feed_sync.compute_diff",
        lambda storage_dir="storage": {"insert": [], "update": [], "delete": []},
    )

    supabase_sync.sync_full(storage)

    state = json.loads(_state_path(storage).read_text())
    assert "article_hashes" not in state
    assert "articles_last_ts" not in state


def test_mtime_gate_skips_without_diffing(tmp_path, monkeypatch):
    """Unchanged feed + no pending purge retries -> no diff, no fetch, no push
    (sync_full keeps its cheap incremental short-circuit)."""
    storage = tmp_path / "storage"
    feed_path = _write_feed(storage, [_item("mile_gate")])
    _state_path(storage).write_text(
        json.dumps({"feed_mtime": feed_path.stat().st_mtime})
    )
    synced = _capture_sync_article(monkeypatch)

    def boom(storage_dir="storage"):
        raise AssertionError("compute_diff must not run when the gate is closed")

    monkeypatch.setattr("volpred.ops.feed_sync.compute_diff", boom)

    counts = supabase_sync.sync_full(storage)

    assert counts["articles"] == 0
    assert synced == []


# --- _select_rows pagination (unrelated to the engine merge; kept as-is) -----


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


def test_sync_article_preserves_server_resident_view_display(monkeypatch):
    """A re-sync must not clobber DB-resident details keys: view_display
    (view-count seeds) exists ONLY in the DB row, and wholesale details
    overwrites were silently destroying it since 2026-07-18."""
    monkeypatch.delenv("VOLPRED_NO_REMOTE_WRITE", raising=False)
    posted: list[tuple[str, dict]] = []

    def fake_post(table, data):
        posted.append((table, data))
        return True

    def fake_select(table, *, select="*", order_by=None, **filters):
        if select == "details":  # the resident-key pre-read
            return [
                {
                    "details": {
                        "experiment_refs": ["K_old"],
                        "view_display": {"seed": 742, "baseline_real": 38},
                    }
                }
            ]
        return [  # the post-write read-back
            {
                "slug": filters.get("slug"),
                "status": "published",
                "published_at": "2026-07-20T00:00:00+00:00",
                "audience": "research",
            }
        ]

    monkeypatch.setattr(supabase_sync, "_post", fake_post)
    monkeypatch.setattr(supabase_sync, "_select_rows", fake_select)
    monkeypatch.setattr(supabase_sync, "_patch_where", lambda *a, **k: True)
    monkeypatch.setattr(supabase_sync, "revalidate_article_cache", lambda s: True)

    ok = supabase_sync.sync_article_projection(
        _item("mile_seeded", published_at="2026-07-20T00:00:00+00:00")
    )

    assert ok is True
    row = posted[0][1]
    assert row["details"]["view_display"] == {"seed": 742, "baseline_real": 38}
    # Canonical keys still come from the feed item, not the old DB row.
    assert row["details"]["experiment_refs"] == ["K1413"]


def test_sync_article_fails_closed_when_resident_read_fails(monkeypatch, capsys):
    """If the resident-key pre-read fails, writing blind would destroy
    view_display unrecoverably — refuse to write and let the diff retry."""
    monkeypatch.delenv("VOLPRED_NO_REMOTE_WRITE", raising=False)
    posted: list = []
    monkeypatch.setattr(
        supabase_sync, "_post", lambda *a, **k: posted.append(a) or True
    )

    def boom(table, *, select="*", order_by=None, **filters):
        raise RuntimeError("supabase read down")

    monkeypatch.setattr(supabase_sync, "_select_rows", boom)

    ok = supabase_sync.sync_article_projection(_item("mile_readfail"))

    assert ok is False
    assert posted == []
    assert "resident-details read failed" in capsys.readouterr().out


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
