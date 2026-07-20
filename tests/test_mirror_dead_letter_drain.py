"""Mirror failures must dead-letter and then be drained, like Supabase ones.

WS-C4 (docs/refactor_plan_ops_master_2026_07.md §7). Two halves of one loop
used to be missing:

  1. On the publish/unpublish paths the Mirror PUT's return value was dropped,
     so a rejected PUT was a bare ``print``. That is the shape of the "401 for
     a month" incident — a projection silently diverging with nothing counting
     it.
  2. ``.failed_mirror_syncs.json`` (added by WS-C1 for the update path) had no
     consumer. A write-only dead-letter queue is exactly the bug the Supabase
     drain was written to fix in 2026-06.

These tests inject a failing Mirror, assert the id lands in the queue, then let
the drain retry it against a now-healthy Mirror and assert the queue empties.

Mocking follows test_publish_draft_update_gateway.py: patch the Publisher's
remote method and REMOTE_URL rather than touching the network.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from volpred.publisher.publisher import Publisher  # noqa: E402

MILE_ID = "mile_mirror_c4"
MIRROR_QUEUE = ".failed_mirror_syncs.json"


def _load_drain_module():
    module_path = SCRIPTS / "drain_failed_supabase_syncs.py"
    spec = importlib.util.spec_from_file_location("drain_failed_supabase_syncs_c4", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """A publisher rooted in tmp_path, with remote writes nominally enabled."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VOLPRED_NO_REMOTE_WRITE", raising=False)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "https://mirror.test", raising=False)
    (tmp_path / "storage" / "reports").mkdir(parents=True)
    return tmp_path / "storage"


def _queue(storage_dir: Path, name: str = MIRROR_QUEUE) -> list:
    path = storage_dir / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _article(pub_id: str = MILE_ID) -> dict:
    return {"id": pub_id, "title": "Mirror C4", "status": "published", "content": "Body."}


# --- half 1: the publish path dead-letters a rejected Mirror PUT -------------


def test_failed_mirror_put_on_publish_is_dead_lettered(storage, monkeypatch):
    publisher = Publisher(storage_dir=str(storage))
    monkeypatch.setattr(publisher, "_sync_report_to_remote", lambda pub_id, item: False)

    publisher._append_to_feed(_article())

    assert _queue(storage) == [MILE_ID]


def test_successful_mirror_put_leaves_queue_empty(storage, monkeypatch):
    publisher = Publisher(storage_dir=str(storage))
    monkeypatch.setattr(publisher, "_sync_report_to_remote", lambda pub_id, item: True)

    publisher._append_to_feed(_article())

    assert _queue(storage) == []


def test_disabled_mirror_does_not_dead_letter(storage, monkeypatch):
    """No REMOTE_URL means nothing was attempted, so nothing failed.

    Without this, every offline/test run would queue every article and bury the
    genuine failures the alert is supposed to surface.
    """
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    publisher = Publisher(storage_dir=str(storage))

    publisher._append_to_feed(_article())

    assert _queue(storage) == []


def test_remote_write_kill_switch_does_not_dead_letter(storage, monkeypatch):
    monkeypatch.setenv("VOLPRED_NO_REMOTE_WRITE", "1")
    publisher = Publisher(storage_dir=str(storage))

    publisher._append_to_feed(_article())

    assert _queue(storage) == []


def test_failed_mirror_put_on_unpublish_is_dead_lettered(storage, monkeypatch):
    publisher = Publisher(storage_dir=str(storage))
    monkeypatch.setattr(publisher, "_sync_report_to_remote", lambda pub_id, item: True)
    publisher._append_to_feed(_article())
    monkeypatch.setattr(publisher, "_sync_report_to_remote", lambda pub_id, item: False)
    monkeypatch.setitem(sys.modules, "supabase_sync", _stub_supabase(ok=True))

    assert publisher.unpublish(MILE_ID) is True
    assert _queue(storage) == [MILE_ID]


def _stub_supabase(*, ok: bool):
    import types

    module = types.ModuleType("supabase_sync")
    module.sync_article = lambda item, storage_dir=None: ok
    return module


# --- half 2: the drain retries the Mirror queue ------------------------------


def _run_drain(monkeypatch, storage_dir: Path, *, mirror_ok: bool, dry_run: bool = False):
    """Load the drain module re-rooted at tmp_path and run it."""
    drain = _load_drain_module()
    monkeypatch.setattr(drain, "ROOT", storage_dir.parent)
    monkeypatch.setattr(drain, "QUEUE_PATH", storage_dir / ".failed_supabase_syncs.json")
    monkeypatch.setattr(drain, "MIRROR_QUEUE_PATH", storage_dir / MIRROR_QUEUE)
    monkeypatch.setattr(drain, "FEED_PATH", storage_dir / "reports" / "feed.json")
    monkeypatch.setattr(drain, "_mirror_enabled", lambda: True)
    monkeypatch.setattr(drain, "_resync_mirror", lambda art: mirror_ok)
    monkeypatch.setattr(drain, "guard_canonical_write", lambda path: None)
    monkeypatch.setattr(drain, "dirty_paths_before_write", lambda *a, **k: frozenset())
    monkeypatch.setattr(drain, "writable_output_paths", lambda *a, **k: True)
    monkeypatch.setattr(drain, "commit_owned_outputs", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["drain"] + (["--dry-run"] if dry_run else []))
    assert drain.main() == 0
    return drain


def test_drain_clears_mirror_queue_when_put_recovers(storage, monkeypatch):
    """The whole loop: failed PUT -> queue -> drain against healthy Mirror -> empty."""
    publisher = Publisher(storage_dir=str(storage))
    monkeypatch.setattr(publisher, "_sync_report_to_remote", lambda pub_id, item: False)
    publisher._append_to_feed(_article())
    assert _queue(storage) == [MILE_ID]

    _run_drain(monkeypatch, storage, mirror_ok=True)

    assert _queue(storage) == []


def test_drain_keeps_persistently_failing_mirror_ids(storage, monkeypatch):
    publisher = Publisher(storage_dir=str(storage))
    monkeypatch.setattr(publisher, "_sync_report_to_remote", lambda pub_id, item: False)
    publisher._append_to_feed(_article())

    _run_drain(monkeypatch, storage, mirror_ok=False)

    assert _queue(storage) == [MILE_ID], "a still-broken Mirror must stay queued and alerting"


def test_drain_drops_ids_no_longer_in_feed(storage, monkeypatch):
    (storage / "reports" / "feed.json").write_text("[]", encoding="utf-8")
    (storage / MIRROR_QUEUE).write_text(json.dumps(["mile_deleted"]), encoding="utf-8")

    _run_drain(monkeypatch, storage, mirror_ok=True)

    assert _queue(storage) == []


def test_drain_leaves_mirror_queue_intact_when_mirror_disabled(storage, monkeypatch):
    """A disabled Mirror cannot retry — the queue must survive, not be cleared."""
    (storage / "reports" / "feed.json").write_text(
        json.dumps([_article()]), encoding="utf-8"
    )
    (storage / MIRROR_QUEUE).write_text(json.dumps([MILE_ID]), encoding="utf-8")

    drain = _load_drain_module()
    monkeypatch.setattr(drain, "ROOT", storage.parent)
    monkeypatch.setattr(drain, "QUEUE_PATH", storage / ".failed_supabase_syncs.json")
    monkeypatch.setattr(drain, "MIRROR_QUEUE_PATH", storage / MIRROR_QUEUE)
    monkeypatch.setattr(drain, "FEED_PATH", storage / "reports" / "feed.json")
    monkeypatch.setattr(drain, "_mirror_enabled", lambda: False)
    monkeypatch.setattr(drain, "guard_canonical_write", lambda path: None)
    monkeypatch.setattr(drain, "dirty_paths_before_write", lambda *a, **k: frozenset())
    monkeypatch.setattr(drain, "writable_output_paths", lambda *a, **k: True)
    monkeypatch.setattr(drain, "commit_owned_outputs", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["drain"])

    assert drain.main() == 0
    assert _queue(storage) == [MILE_ID]


def test_drain_dry_run_touches_neither_queue(storage, monkeypatch):
    (storage / "reports" / "feed.json").write_text(
        json.dumps([_article()]), encoding="utf-8"
    )
    (storage / MIRROR_QUEUE).write_text(json.dumps([MILE_ID]), encoding="utf-8")

    _run_drain(monkeypatch, storage, mirror_ok=True, dry_run=True)

    assert _queue(storage) == [MILE_ID]
