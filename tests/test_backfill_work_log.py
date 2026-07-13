from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_backfill_module():
    module_path = ROOT / "scripts" / "backfill_work_log_from_commits.py"
    spec = importlib.util.spec_from_file_location("backfill_work_log_from_commits", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_classify_codex_commit_subject_patterns():
    module = _load_backfill_module()

    cases = [
        ("[codex] complete K1556 macro cojump proxy", ("experiment", "K1556")),
        ("[codex] draft K1406 DCA vs lump sum article", ("daily_article", "K1406")),
        ("[codex] publish daily digest for 2026-06-28", ("daily_digest", None)),
        ("[codex] journal discovery adds variance-risk backlog", ("governance", None)),
        ("[codex] update error.log with release guardrail", ("governance", None)),
        ("[codex] annotate supervisor health process races", ("platform_ops", None)),
    ]

    for subject, expected in cases:
        assert module.classify(subject) == expected


def test_build_entry_records_commit_metadata_and_clean_summary():
    module = _load_backfill_module()
    row = {
        "sha": "abcdef1234567890",
        "ts": "2026-06-28T10:30:00+00:00",
        "subject": "[codex] complete K1556 macro cojump proxy",
    }

    entry = module.build_entry(row)

    assert entry["timestamp"] == row["ts"]
    assert entry["task_type"] == "experiment"
    assert entry["task_id"] == "codex-commit-abcdef123"
    assert entry["summary"] == "complete K1556 macro cojump proxy"
    assert entry["commit"] == row["sha"]
    assert entry["owner"] == "codex"
    assert entry["k_id"] == "K1556"
    assert entry["backfill_source"] == "scripts/backfill_work_log_from_commits.py"
    assert "backfilled_at" in entry


def test_backfill_dedupes_against_the_log_as_it_is_under_the_lock(tmp_path):
    """Backfill's sha filter must run inside the lock, not against a stale snapshot.

    2026-07-13: backfill did a read-modify-write of the whole array with no lock.
    Beyond dropping concurrent entries, its idempotency key (the commit sha) was
    checked against a snapshot read *before* the write — so a commit that another
    writer landed in between would be appended a second time. This pins the fix:
    the entry the concurrent writer added is visible to the dedupe callback.
    """
    module = _load_backfill_module()

    log = tmp_path / "work_log.json"
    lock = tmp_path / ".work_log.lock"
    log.write_text("[]", encoding="utf-8")

    rows = [
        {"sha": "aaa111", "ts": "2026-07-13T01:00:00+08:00", "subject": "[codex] complete K1 alpha"},
        {"sha": "bbb222", "ts": "2026-07-13T02:00:00+08:00", "subject": "[codex] complete K2 beta"},
    ]
    candidates = [module.build_entry(r) for r in rows]

    # Simulate the race: while backfill holds `candidates`, another writer lands
    # the entry for sha aaa111 into the log.
    module.append_entries([module.build_entry(rows[0])], path=log, lock_path=lock)

    def dedupe(existing, cands):
        return module.drop_seen_commits(existing, cands)

    appended, total = module.append_entries(candidates, path=log, lock_path=lock, dedupe=dedupe)

    assert [e["commit"] for e in appended] == ["bbb222"], "re-appended a sha already in the log"
    assert total == 2

    shas = [e["commit"] for e in json.loads(log.read_text(encoding="utf-8"))]
    assert shas == ["aaa111", "bbb222"]
