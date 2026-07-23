"""WS-H4 Step 1 regression — `--dry-run` must be a真 read-only pass.

Before 2026-07-20, `continue_task_dispatch.py --dry-run` was a false flag:
`main()` declared it but never read `args.dry_run`, so a "dry" invocation still
ran retire/sweep/refill/promote against storage/next_tasks.json
(docs/dispatch-decision-pipeline-design.md §1.2). These tests pin the repaired
semantics:

  * dry-run: next_tasks.json is byte-identical before/after; no report file;
    the covered-article sweep runs with apply=False; refill stages never import.
  * non-dry (control): the same fixture DOES mutate the pool (promote path),
    and the covered-article sweep runs with apply=True — guards against an
    inverted flag that would silently make production dispatch read-only.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "continue_task_dispatch.py"
SPEC = importlib.util.spec_from_file_location("continue_task_dispatch_dry_run_module", MODULE_PATH)
assert SPEC and SPEC.loader
ctd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ctd)


def _seed_tasks() -> list[dict]:
    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    return [
        {
            "id": "art-1", "title": "article task", "task_type": "daily_article",
            "priority": 3, "status": "pending", "created_at": fresh,
        },
        {
            "id": "ops-1", "title": "ops task", "task_type": "platform_ops",
            "priority": 2, "status": "pending", "created_at": fresh,
        },
    ]


def _wire_fixture(monkeypatch, tmp_path: Path) -> tuple[Path, dict]:
    """Hermetic build_report fixture. Returns (next_tasks_path, spy dict).

    The refill generator modules are replaced with booby-traps that raise on
    call: in dry-run they must never be reached (the early return happens
    before their in-function imports), and in the control run we swap them for
    quiet zero-add fakes explicitly.
    """
    q = tmp_path / "next_tasks.json"
    q.write_text(json.dumps(_seed_tasks(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    feed = tmp_path / "feed.json"
    feed.write_text("[]\n", encoding="utf-8")

    monkeypatch.setattr(ctd, "NEXT_TASKS", q)
    monkeypatch.setattr(ctd, "FEED_PATH", feed)
    monkeypatch.setattr(ctd, "WORK_LOG", tmp_path / "work_log.json")
    monkeypatch.setattr(ctd, "REPORT_PATH", tmp_path / "dispatch_report_latest.json")
    monkeypatch.setattr(
        ctd, "_slot_budget",
        SimpleNamespace(
            occupancy=lambda: {"occupied": 0, "worktrees": [], "active_agents": [], "stale": []},
            budget=lambda: {"cap": 4, "reason": "test-fixture", "p1_only_slots": 0, "occupied": 0},
            STALE_HOURS=30,
        ),
    )
    # Max-temptation signal: releasable drafts == 0 → a non-dry run promotes
    # starved articles AND fires the draft-pool refill. Dry-run must do neither.
    monkeypatch.setattr(ctd, "_releasable_draft_count", lambda: 0)

    spy: dict = {"retire_apply": []}
    retire_mod = ModuleType("mark_covered_article_tasks")

    def _fake_sweep(apply: bool) -> dict:
        spy["retire_apply"].append(apply)
        return {"scanned": 0, "retired": [], "applied": bool(apply)}

    retire_mod.sweep = _fake_sweep
    monkeypatch.setitem(sys.modules, "mark_covered_article_tasks", retire_mod)

    def _trap(name: str) -> ModuleType:
        mod = ModuleType(name)

        def _boom(*_a, **_k):
            raise AssertionError(f"{name} must not run during --dry-run")

        mod.generate = _boom
        mod.refill = _boom
        mod.refill_event_candidates = _boom
        return mod

    for name in ("generate_diverse_tasks", "refill_task_pool",
                 "refill_reader_facing_pool", "generate_research_backlog"):
        monkeypatch.setitem(sys.modules, name, _trap(name))
    return q, spy


def test_dry_run_build_report_leaves_next_tasks_byte_identical(monkeypatch, tmp_path) -> None:
    q, spy = _wire_fixture(monkeypatch, tmp_path)
    before = q.read_bytes()

    report = ctd.build_report(auto_refill=True, dry_run=True)

    assert q.read_bytes() == before  # the H4-0 acceptance criterion, verbatim
    assert report["dry_run"] is True
    assert spy["retire_apply"] == [False]  # detection ran, retirement did not
    assert report["refill"]["dry_run"] is True
    assert report["refill"]["added"] == 0
    assert report["draft_pool_refill"]["dry_run"] is True
    assert report["draft_pool_refill"]["would_promote_starved"] is True
    # the pool itself is untouched: art-1 keeps its original priority
    saved = json.loads(q.read_text(encoding="utf-8"))
    assert next(t for t in saved if t["id"] == "art-1")["priority"] == 3


def test_dry_run_main_writes_nothing(monkeypatch, tmp_path, capsys) -> None:
    q, _spy = _wire_fixture(monkeypatch, tmp_path)
    before = q.read_bytes()
    monkeypatch.setattr(sys, "argv", ["continue_task_dispatch.py", "--dry-run", "--report"])

    rc = ctd.main()

    assert rc == 0
    assert q.read_bytes() == before
    assert not ctd.REPORT_PATH.exists()  # --report + --dry-run stays on stdout
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "report NOT written" in out


def test_non_dry_run_control_still_mutates_pool(monkeypatch, tmp_path) -> None:
    """Inverted-flag guard: without --dry-run the same fixture must write."""
    q, spy = _wire_fixture(monkeypatch, tmp_path)
    # swap the booby-traps for quiet zero-add fakes so the real refill path runs
    diverse = ModuleType("generate_diverse_tasks")
    diverse.generate = lambda dry_run=False: {"ok": True, "added": 0, "added_ids": [], "by_type": {}}
    event = ModuleType("refill_reader_facing_pool")
    event.refill_event_candidates = lambda horizon_days=14: {"added": []}
    article = ModuleType("refill_task_pool")
    article.refill = lambda target, dry_run=False, reader_facing_only=False: {
        "ok": True, "added": 0, "reason": "no_new_candidates_passing_filter",
    }
    research = ModuleType("generate_research_backlog")
    research.generate = lambda dry_run=False, max_new=0: {"ok": True, "added": 0}
    for name, mod in (("generate_diverse_tasks", diverse),
                      ("refill_reader_facing_pool", event),
                      ("refill_task_pool", article),
                      ("generate_research_backlog", research)):
        monkeypatch.setitem(sys.modules, name, mod)

    report = ctd.build_report(auto_refill=True, dry_run=False)

    assert report["dry_run"] is False
    assert spy["retire_apply"] == [True]  # real pass retires for real
    # releasable==0 → the promote path ran and rewrote the pool: art-1 is P1 now
    saved = json.loads(q.read_text(encoding="utf-8"))
    assert next(t for t in saved if t["id"] == "art-1")["priority"] == 1
