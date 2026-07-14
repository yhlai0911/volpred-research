"""Hermetic tests for supabase_sync.reconcile_article_deletes.

Covers the 2026-07-14 ghost-mirror fix: the push path (sync_full/sync_article)
is upsert-only, so Supabase `articles` rows for articles absent from the
canonical feed.json accumulate as ghosts (200 found: ~156 draft + 44 retracted).
reconcile_article_deletes removes remote-only rows, guarded by a floor (never
delete against a tiny/corrupt feed) and a cap (never mass-delete), dumping the
removed rows first for recoverability.

All Supabase I/O (_select_rows / _select_rows_in / delete_article) is stubbed —
no network, no credentials, no real DB touched.
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


def _write_feed(tmp_path: Path, n: int) -> Path:
    """Create storage/reports/feed.json with n published articles."""
    storage = tmp_path / "storage"
    (storage / "reports").mkdir(parents=True, exist_ok=True)
    feed = [
        {"id": f"mile_{i:04d}", "status": "published", "title": f"Article {i}"}
        for i in range(n)
    ]
    (storage / "reports" / "feed.json").write_text(
        json.dumps(feed, ensure_ascii=False)
    )
    return storage


def _remote_rows(local_n: int, ghosts: list[dict]) -> list[dict]:
    """Remote projection: all local ids (as slugs) + supplied ghost rows."""
    rows = [
        {"id": f"uuid-{i:04d}", "slug": f"mile_{i:04d}", "status": "published"}
        for i in range(local_n)
    ]
    return rows + ghosts


def _stub_supabase(monkeypatch, remote_rows: list[dict], impressions=None):
    """Stub the three Supabase touch points; return a recorder of deleted slugs."""
    deleted: list[str] = []

    monkeypatch.setattr(supabase_sync, "_select_rows", lambda *a, **k: list(remote_rows))
    monkeypatch.setattr(
        supabase_sync,
        "_select_rows_in",
        lambda *a, **k: list(impressions or []),
    )

    def _fake_delete(slug: str) -> bool:
        deleted.append(slug)
        return True

    monkeypatch.setattr(supabase_sync, "delete_article", _fake_delete)
    return deleted


def _dump_files(storage: Path) -> list[Path]:
    return sorted((storage / "ops").glob("supabase_reconcile_removed_*.jsonl"))


def test_deletes_ghosts_not_in_feed(tmp_path, monkeypatch):
    """Happy path: remote-only slugs are deleted; locals are untouched; the
    removed rows (with impressions) are dumped before deletion."""
    storage = _write_feed(tmp_path, 600)
    ghosts = [
        {"id": "uuid-g1", "slug": "mile_ghost1", "status": "draft"},
        {"id": "uuid-g2", "slug": "mile_ghost2", "status": "retracted"},
        {"id": "uuid-g3", "slug": "mile_ghost3", "status": "draft"},
    ]
    remote = _remote_rows(600, ghosts)
    impressions = [
        {"id": "imp1", "article_id": "uuid-g2", "viewed_at": "2026-07-01"},
        {"id": "imp2", "article_id": "uuid-g2", "viewed_at": "2026-07-02"},
    ]
    deleted = _stub_supabase(monkeypatch, remote, impressions=impressions)

    res = supabase_sync.reconcile_article_deletes(storage, apply=True)

    assert res["aborted"] is False
    assert res["local_count"] == 600
    assert res["remote_count"] == 603
    assert res["ghost_count"] == 3
    assert res["deleted"] == 3
    assert res["failed"] == 0
    # Only ghost slugs deleted — never a legitimate local article.
    assert sorted(deleted) == ["mile_ghost1", "mile_ghost2", "mile_ghost3"]

    # Recoverable dump written BEFORE deletes, one line per removed row, with
    # the cascade-impacted impressions captured for recovery.
    files = _dump_files(storage)
    assert len(files) == 1
    lines = [json.loads(x) for x in files[0].read_text().splitlines() if x.strip()]
    assert len(lines) == 3
    assert {rec["article"]["slug"] for rec in lines} == {
        "mile_ghost1", "mile_ghost2", "mile_ghost3",
    }
    assert res["impressions_dumped"] == 2
    g2 = next(r for r in lines if r["article"]["slug"] == "mile_ghost2")
    assert len(g2["impressions"]) == 2


def test_floor_guard_refuses_when_canonical_too_small(tmp_path, monkeypatch):
    """A feed below `floor` (e.g. empty/corrupt/half-written) must delete
    nothing — this is the guard against wiping the whole table."""
    storage = _write_feed(tmp_path, 3)  # < default floor 500
    ghosts = [
        {"id": f"uuid-g{i}", "slug": f"mile_ghost{i}", "status": "draft"}
        for i in range(5)
    ]
    remote = _remote_rows(3, ghosts)
    deleted = _stub_supabase(monkeypatch, remote)

    res = supabase_sync.reconcile_article_deletes(storage, apply=True)

    assert res["aborted"] is True
    assert "floor" in res["reason"]
    assert res["deleted"] == 0
    assert deleted == []  # delete_article never called
    assert _dump_files(storage) == []  # nothing dumped


def test_cap_abort_when_drift_exceeds_max(tmp_path, monkeypatch):
    """Drift larger than `max_deletes` smells like canonical corruption; abort
    and delete nothing rather than mass-deleting."""
    storage = _write_feed(tmp_path, 600)
    ghosts = [
        {"id": f"uuid-g{i}", "slug": f"mile_ghost{i}", "status": "draft"}
        for i in range(400)  # > default max_deletes 300
    ]
    remote = _remote_rows(600, ghosts)
    deleted = _stub_supabase(monkeypatch, remote)

    res = supabase_sync.reconcile_article_deletes(storage, apply=True)

    assert res["aborted"] is True
    assert "exceeds_max_deletes" in res["reason"]
    assert res["ghost_count"] == 400
    assert res["deleted"] == 0
    assert deleted == []
    assert _dump_files(storage) == []


def test_preview_mode_computes_but_does_not_delete(tmp_path, monkeypatch):
    """apply=False reports the drift without writing or deleting anything."""
    storage = _write_feed(tmp_path, 600)
    ghosts = [{"id": "uuid-g1", "slug": "mile_ghost1", "status": "draft"}]
    remote = _remote_rows(600, ghosts)
    deleted = _stub_supabase(monkeypatch, remote)

    res = supabase_sync.reconcile_article_deletes(storage, apply=False)

    assert res["aborted"] is False
    assert res["ghost_count"] == 1
    assert res["deleted"] == 0
    assert deleted == []
    assert _dump_files(storage) == []


def test_no_drift_is_a_clean_noop(tmp_path, monkeypatch):
    """When remote == feed there is nothing to delete."""
    storage = _write_feed(tmp_path, 600)
    remote = _remote_rows(600, [])
    deleted = _stub_supabase(monkeypatch, remote)

    res = supabase_sync.reconcile_article_deletes(storage, apply=True)

    assert res["aborted"] is False
    assert res["ghost_count"] == 0
    assert res["deleted"] == 0
    assert deleted == []
    assert _dump_files(storage) == []
