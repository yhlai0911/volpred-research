"""Hermetic tests for supabase_sync.reconcile_article_deletes.

Covers the 2026-07-14 ghost-mirror fix: the push path (sync_full/sync_article)
is upsert-only, so Supabase `articles` rows for articles absent from the
canonical feed.json accumulate as ghosts (200 found: ~156 draft + 44 retracted).
reconcile_article_deletes removes remote-only rows, guarded by a floor (never
delete against a tiny/corrupt feed), a cap (never mass-delete), a live FK
contract, and a complete read-back-verified recovery dump.

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


def _stub_supabase(
    monkeypatch,
    remote_rows: list[dict],
    *,
    cascade_rows: dict[str, list[dict]] | None = None,
):
    """Stub the three Supabase touch points; return a recorder of deleted slugs."""
    deleted: list[str] = []
    captured = cascade_rows or {}

    monkeypatch.setattr(
        supabase_sync,
        "_select_rows",
        lambda *a, **k: list(remote_rows),
    )

    def _select_rows_in(table, column, values, *, select="*"):
        assert select == "*"
        allowed = {str(value) for value in values}
        return [
            dict(row)
            for row in captured.get(table, [])
            if str(row.get(column) or "") in allowed
        ]

    monkeypatch.setattr(
        supabase_sync,
        "_select_rows_in",
        _select_rows_in,
    )
    monkeypatch.setattr(
        supabase_sync,
        "_read_article_delete_dependency_contract",
        lambda: tuple(sorted(supabase_sync.ARTICLE_DELETE_CASCADE_CONTRACT)),
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
    complete article and every cascading child are dumped before deletion."""
    storage = _write_feed(tmp_path, 600)
    ghosts = [
        {
            "id": "uuid-g1",
            "slug": "mile_ghost1",
            "status": "draft",
            "content": "full remote body",
        },
        {"id": "uuid-g2", "slug": "mile_ghost2", "status": "retracted"},
        {"id": "uuid-g3", "slug": "mile_ghost3", "status": "draft"},
    ]
    remote = _remote_rows(600, ghosts)
    cascades = {
        "article_impressions": [
            {"id": "imp1", "article_id": "uuid-g2", "viewed_at": "2026-07-01"},
            {"id": "imp2", "article_id": "uuid-g2", "viewed_at": "2026-07-02"},
        ],
        "article_reactions": [
            {"id": "reaction1", "article_id": "uuid-g1", "reaction": "like"},
        ],
        "article_relations": [
            {
                "id": "relation1",
                "source_id": "uuid-g1",
                "target_id": "uuid-0001",
            },
            {
                "id": "relation2",
                "source_id": "uuid-0002",
                "target_id": "uuid-g2",
            },
        ],
        "article_tags": [
            {"article_id": "uuid-g3", "tag_id": "tag-1"},
        ],
        "comments": [
            {"id": "comment1", "article_id": "uuid-g1", "body": "keep me"},
        ],
        "question_articles": [
            {"question_id": "question1", "article_id": "uuid-g2"},
        ],
    }
    deleted = _stub_supabase(
        monkeypatch,
        remote,
        cascade_rows=cascades,
    )

    res = supabase_sync.reconcile_article_deletes(storage, apply=True)

    assert res["aborted"] is False
    assert res["local_count"] == 600
    assert res["remote_count"] == 603
    assert res["ghost_count"] == 3
    assert res["deleted"] == 3
    assert res["failed"] == 0
    # Only ghost slugs deleted — never a legitimate local article.
    assert sorted(deleted) == ["mile_ghost1", "mile_ghost2", "mile_ghost3"]

    # Recovery v2 is immutable and read-back verified before delete. It keeps
    # the complete article plus every live cascading relation.
    files = _dump_files(storage)
    assert len(files) == 1
    lines = [json.loads(x) for x in files[0].read_text().splitlines() if x.strip()]
    assert len(lines) == 3
    assert {rec["article"]["slug"] for rec in lines} == {
        "mile_ghost1", "mile_ghost2", "mile_ghost3",
    }
    assert res["impressions_dumped"] == 2
    assert res["dump_sha256"]
    assert res["cascade_rows_dumped"] == {
        "article_impressions": 2,
        "article_reactions": 1,
        "article_relations": 2,
        "article_tags": 1,
        "comments": 1,
        "question_articles": 1,
    }
    assert {record["schema_version"] for record in lines} == {
        "supabase-article-delete-recovery.v2"
    }
    assert {record["canonical_feed_sha256"] for record in lines} == {
        res["canonical_feed_sha256"]
    }
    g1 = next(r for r in lines if r["article"]["slug"] == "mile_ghost1")
    g2 = next(r for r in lines if r["article"]["slug"] == "mile_ghost2")
    assert g1["article"]["content"] == "full remote body"
    assert len(g1["cascade_rows"]["article_reactions"]) == 1
    assert len(g1["cascade_rows"]["article_relations"]) == 1
    assert len(g1["cascade_rows"]["comments"]) == 1
    assert len(g2["cascade_rows"]["article_impressions"]) == 2
    assert len(g2["cascade_rows"]["article_relations"]) == 1
    assert len(g2["cascade_rows"]["question_articles"]) == 1


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


def test_dependency_snapshot_failure_aborts_before_dump_or_delete(
    tmp_path, monkeypatch
):
    storage = _write_feed(tmp_path, 600)
    remote = _remote_rows(
        600,
        [{"id": "uuid-g1", "slug": "mile_ghost1", "status": "draft"}],
    )
    deleted = _stub_supabase(monkeypatch, remote)
    original = supabase_sync._select_rows_in

    def fail_comments(table, column, values, *, select="*"):
        if table == "comments":
            raise RuntimeError("comments unavailable")
        return original(table, column, values, select=select)

    monkeypatch.setattr(supabase_sync, "_select_rows_in", fail_comments)

    res = supabase_sync.reconcile_article_deletes(storage, apply=True)

    assert res["aborted"] is True
    assert res["reason"] == "recovery_snapshot_failed:RuntimeError"
    assert res["deleted"] == 0
    assert deleted == []
    assert _dump_files(storage) == []


def test_live_dependency_contract_drift_aborts_before_child_reads(
    tmp_path, monkeypatch
):
    storage = _write_feed(tmp_path, 600)
    remote = _remote_rows(
        600,
        [{"id": "uuid-g1", "slug": "mile_ghost1", "status": "draft"}],
    )
    deleted = _stub_supabase(monkeypatch, remote)
    child_reads = 0

    def record_child_read(*args, **kwargs):
        nonlocal child_reads
        child_reads += 1
        return []

    monkeypatch.setattr(supabase_sync, "_select_rows_in", record_child_read)
    monkeypatch.setattr(
        supabase_sync,
        "_read_article_delete_dependency_contract",
        lambda: (
            *tuple(sorted(supabase_sync.ARTICLE_DELETE_CASCADE_CONTRACT)),
            ("new_cascade_table", "article_id", "cascade"),
        ),
    )

    res = supabase_sync.reconcile_article_deletes(storage, apply=True)

    assert res["aborted"] is True
    assert res["reason"] == "dependency_contract_drift"
    assert res["deleted"] == 0
    assert child_reads == 0
    assert deleted == []
    assert _dump_files(storage) == []


def test_feed_generation_change_during_capture_aborts_before_dump_or_delete(
    tmp_path, monkeypatch
):
    storage = _write_feed(tmp_path, 600)
    remote = _remote_rows(
        600,
        [{"id": "uuid-g1", "slug": "mile_ghost1", "status": "draft"}],
    )
    deleted = _stub_supabase(monkeypatch, remote)
    mutated = False

    def mutate_feed_once(*args, **kwargs):
        nonlocal mutated
        if not mutated:
            mutated = True
            feed_path = storage / "reports" / "feed.json"
            payload = json.loads(feed_path.read_text())
            payload[0]["title"] = "concurrent edit"
            feed_path.write_text(json.dumps(payload))
        return []

    monkeypatch.setattr(
        supabase_sync,
        "_select_rows_in",
        mutate_feed_once,
    )

    res = supabase_sync.reconcile_article_deletes(storage, apply=True)

    assert res["aborted"] is True
    assert res["reason"] == "canonical_snapshot_changed"
    assert res["deleted"] == 0
    assert deleted == []
    assert _dump_files(storage) == []


def test_dependency_contract_rpc_requires_exact_typed_rows(monkeypatch):
    monkeypatch.setattr(supabase_sync, "require_creds", lambda: None)
    monkeypatch.setattr(supabase_sync, "SUPABASE_URL", "https://example.invalid")
    monkeypatch.setattr(
        supabase_sync,
        "_request_json",
        lambda *args, **kwargs: [
            {
                "table": "comments",
                "column": "article_id",
                "on_delete": "cascade",
            },
            {
                "table": "article_tags",
                "column": "article_id",
                "on_delete": "cascade",
            },
        ],
    )

    assert supabase_sync._read_article_delete_dependency_contract() == (
        ("article_tags", "article_id", "cascade"),
        ("comments", "article_id", "cascade"),
    )

    monkeypatch.setattr(
        supabase_sync,
        "_request_json",
        lambda *args, **kwargs: [{"table": "comments"}],
    )
    with pytest.raises(RuntimeError, match="invalid row"):
        supabase_sync._read_article_delete_dependency_contract()
