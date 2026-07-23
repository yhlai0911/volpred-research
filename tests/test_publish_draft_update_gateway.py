"""`publish_draft --update` must leave feed / Supabase / Mirror in agreement.

WS-C1 (docs/refactor_plan_ops_master_2026_07.md §3, P2 in the diagnosis):
``apply_update`` used to write feed.json directly and push neither projection,
printing "run feed-sync yourself" instead. One correction therefore forked the
three surfaces and stayed forked until a human remembered. The update path now
goes through the same gateway as a new publish —
``Publisher.rewrite_and_sync_article`` — so one call fans out to the canonical
feed write, the Mirror PUT and the Supabase row, and any projection failure
lands in a dead-letter queue that the retry cron drains.

Mocking follows the existing publisher tests: stub ``supabase_sync.sync_article``
(test_article_correction.py) and patch the Publisher's remote method plus
REMOTE_URL (test_content_release_pool.py) rather than touching the network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from publish_draft import apply_update  # noqa: E402
from volpred.publisher.publisher import Publisher  # noqa: E402

MILE_ID = "mile_gateway"


def _stage_feed(tmp_path: Path) -> Path:
    feed_dir = tmp_path / "storage" / "reports"
    feed_dir.mkdir(parents=True, exist_ok=True)
    feed_path = feed_dir / "feed.json"
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": MILE_ID,
                    "title": "Gateway article",
                    "audience": "research",
                    "phase": "robustness",
                    "tags": ["paper-9"],
                    "status": "published",
                    "content": "Old content.",
                    "description": "Old description snippet.",
                    "details": {"experiment_refs": ["K100"]},
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return feed_path


def _write_draft(tmp_path: Path) -> Path:
    p = tmp_path / "draft.md"
    p.write_text(
        "更新後的第一段，說明修正了哪個數字。\n\n"
        "![chart](https://example.com/a.png)\n"
        "![chart](https://example.com/b.png)\n",
        encoding="utf-8",
    )
    return p


def _args(draft_path: Path, **overrides):
    base = dict(
        draft_path=str(draft_path),
        update=MILE_ID,
        update_action="codex_review_fix",
        update_summary="Numbers re-derived from the corrected run.",
        update_title=None,
        update_description=None,
        no_update_description=False,
        audience=None,
        no_sanitize=False,
        no_image_gate=False,
        dry_run=False,
        sync_supabase=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    """Stage an update run with both projections armed but stubbed.

    The root conftest sets VOLPRED_NO_REMOTE_WRITE=1 so no test can write live
    Supabase/Mirror. The gateway honours that switch by SKIPPING both
    projections, which is exactly what this test needs to disable — the stubs
    below take the network's place.
    """
    import supabase_sync

    monkeypatch.delenv("VOLPRED_NO_REMOTE_WRITE", raising=False)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "https://mirror.example")

    calls = {"supabase": [], "mirror": []}

    def fake_sync_article(item, storage_dir="storage"):
        calls["supabase"].append(dict(item))
        return calls.get("supabase_ok", True)

    def fake_mirror(self, pub_id, item):
        calls["mirror"].append(pub_id)
        return calls.get("mirror_ok", True)

    monkeypatch.setattr(supabase_sync, "sync_article", fake_sync_article)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", fake_mirror)

    import publish_draft

    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)
    monkeypatch.setattr(
        publish_draft,
        "_refresh_publication_candidates_after_feed_change",
        lambda reason: None,
    )

    feed_path = _stage_feed(tmp_path)
    draft = _write_draft(tmp_path)
    return SimpleNamespace(
        tmp_path=tmp_path, feed_path=feed_path, draft=draft, calls=calls
    )


def _feed_article(feed_path: Path) -> dict:
    return json.loads(feed_path.read_text(encoding="utf-8"))[0]


def _queue(tmp_path: Path, name: str) -> list:
    p = tmp_path / "storage" / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def test_update_fans_out_to_feed_supabase_and_mirror(gateway):
    """One --update triggers all three surfaces, with no dead letter."""
    rc = apply_update(_args(gateway.draft))
    assert rc == 0

    art = _feed_article(gateway.feed_path)
    assert art["content"].startswith("更新後的第一段")
    assert art["errata"]["update_action"] == "codex_review_fix"

    # Supabase got the SAME patched entry that landed in feed.json — a stale
    # payload here is the divergence this deliverable exists to kill.
    assert len(gateway.calls["supabase"]) == 1
    assert gateway.calls["supabase"][0]["content"] == art["content"]
    assert gateway.calls["supabase"][0]["id"] == MILE_ID

    assert gateway.calls["mirror"] == [MILE_ID]

    assert _queue(gateway.tmp_path, ".failed_supabase_syncs.json") == []
    assert _queue(gateway.tmp_path, ".failed_mirror_syncs.json") == []


def test_supabase_failure_lands_in_the_dead_letter_queue(gateway):
    gateway.calls["supabase_ok"] = False

    rc = apply_update(_args(gateway.draft))
    assert rc == 0  # feed is canonical and did land; the drain owns the retry

    assert _feed_article(gateway.feed_path)["content"].startswith("更新後的第一段")
    assert _queue(gateway.tmp_path, ".failed_supabase_syncs.json") == [MILE_ID]
    assert gateway.calls["mirror"] == [MILE_ID]


def test_supabase_exception_lands_in_the_dead_letter_queue(gateway, monkeypatch):
    """sync_article raising must not be quieter than sync_article returning False."""
    import supabase_sync

    def boom(*_a, **_kw):
        raise RuntimeError("supabase unreachable")

    monkeypatch.setattr(supabase_sync, "sync_article", boom)

    assert apply_update(_args(gateway.draft)) == 0
    assert _queue(gateway.tmp_path, ".failed_supabase_syncs.json") == [MILE_ID]


def test_mirror_failure_lands_in_the_dead_letter_queue(gateway):
    """Mirror failures used to be a bare print (the '401 for a month' class)."""
    gateway.calls["mirror_ok"] = False

    rc = apply_update(_args(gateway.draft))
    assert rc == 0

    assert _queue(gateway.tmp_path, ".failed_mirror_syncs.json") == [MILE_ID]
    assert _queue(gateway.tmp_path, ".failed_supabase_syncs.json") == []
    assert len(gateway.calls["supabase"]) == 1


def test_dry_run_touches_no_projection(gateway):
    before = gateway.feed_path.read_bytes()

    assert apply_update(_args(gateway.draft, dry_run=True)) == 0

    assert gateway.feed_path.read_bytes() == before
    assert gateway.calls["supabase"] == []
    assert gateway.calls["mirror"] == []


def test_remote_write_kill_switch_skips_projections_without_dead_letters(
    gateway, monkeypatch
):
    """Under VOLPRED_NO_REMOTE_WRITE the gateway skips — it does not 'fail'."""
    monkeypatch.setenv("VOLPRED_NO_REMOTE_WRITE", "1")

    assert apply_update(_args(gateway.draft)) == 0

    assert _feed_article(gateway.feed_path)["content"].startswith("更新後的第一段")
    assert gateway.calls["supabase"] == []
    assert gateway.calls["mirror"] == []
    assert _queue(gateway.tmp_path, ".failed_supabase_syncs.json") == []
    assert _queue(gateway.tmp_path, ".failed_mirror_syncs.json") == []
