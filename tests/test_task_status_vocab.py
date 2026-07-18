"""Tests for the next_tasks status controlled vocabulary + corruption-safe writer.

Covers the single enforcement owner in ``src/volpred/ops/next_tasks.py`` and the
CI baseline gate in ``scripts/validate_next_tasks_status.py``. See that module's
docstring for the 27-row legacy baseline and the 2026-07-05 corruption incident.
"""
from __future__ import annotations

import fcntl
import json
import subprocess
import sys
from pathlib import Path

import pytest

from volpred.ops import next_tasks as nt

ROOT = Path(__file__).resolve().parents[1]
REAL_NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
VALIDATOR = ROOT / "scripts" / "validate_next_tasks_status.py"
BASELINE = 27
# Frozen 2026-07-18: blocked rows carrying no blocked_until. See
# next_tasks.LEGACY_BLOCKED_WITHOUT_UNTIL_BASELINE for provenance.
BLOCKED_NO_UNTIL_BASELINE = 0


# ---------------------------------------------------------------- vocabulary --

def test_every_vocab_status_validates():
    for status in nt.TASK_STATUSES:
        assert nt.is_valid_status(status)
        assert nt.validate_task_status(status) == status


def test_validate_task_status_is_case_and_whitespace_tolerant():
    assert nt.validate_task_status("  Pending  ") == "pending"
    assert nt.is_valid_status(" SUCCEEDED ")


@pytest.mark.parametrize(
    "bad",
    ["completed", "partially_completed", "superseded_audience_null_fix", "totally_made_up", ""],
)
def test_out_of_vocab_raises(bad):
    assert not nt.is_valid_status(bad)
    with pytest.raises(nt.InvalidTaskStatus):
        nt.validate_task_status(bad)


# --------------------------------------------------- serialize-first / no corrupt --

def test_serialize_first_leaves_file_intact_when_serialization_fails(tmp_path, monkeypatch):
    """Core corruption-fix evidence: a mid-serialize failure must not truncate.

    Simulate ``json.dumps`` blowing up (the real trigger was a lone surrogate
    raising UnicodeEncodeError). Because serialize happens BEFORE truncate, the
    original file content must survive completely intact.
    """
    p = tmp_path / "next_tasks.json"
    original = '[\n  {"id": "keep", "status": "pending", "priority": 1}\n]\n'
    p.write_text(original, encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise ValueError("serialization blew up mid-write")

    monkeypatch.setattr(nt.json, "dumps", boom)

    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            with pytest.raises(ValueError):
                nt.write_tasks_to_handle(
                    fh,
                    [
                        {"id": "keep", "status": "pending", "priority": 1},
                        {"id": "new", "status": "pending", "priority": 2},
                    ],
                )
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    assert p.read_text(encoding="utf-8") == original


def test_write_tasks_to_handle_is_serialize_first_then_truncate_on_success(tmp_path):
    p = tmp_path / "next_tasks.json"
    p.write_text('[{"id": "old", "status": "pending", "priority": 1}]\n', encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            nt.write_tasks_to_handle(fh, [{"id": "new", "status": "succeeded", "priority": 2}])
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    written = json.loads(p.read_text(encoding="utf-8"))
    assert written == [{"id": "new", "status": "succeeded", "priority": 2}]


def test_write_tasks_to_handle_scrubs_lone_surrogate(tmp_path):
    """The exact 2026-07-05 failure mode: a lone surrogate must be scrubbed, not
    raised mid-write."""
    p = tmp_path / "next_tasks.json"
    p.write_text("[]\n", encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            nt.write_tasks_to_handle(
                fh, [{"id": "surro", "status": "failed", "result": "bad char \udce9 here"}]
            )
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    # File is valid JSON and readable (surrogate replaced, not left dangling).
    written = json.loads(p.read_text(encoding="utf-8"))
    assert written[0]["id"] == "surro"


def test_audit_is_non_fatal_on_legacy_pollution(tmp_path, capsys):
    """A payload carrying a legacy out-of-vocab row must still write (not raise),
    but the pollution must be observable on stderr."""
    p = tmp_path / "next_tasks.json"
    p.write_text("[]\n", encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            nt.write_tasks_to_handle(
                fh,
                [
                    {"id": "legacy", "status": "completed", "priority": 3},
                    {"id": "ok", "status": "pending", "priority": 3},
                ],
            )
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    assert json.loads(p.read_text(encoding="utf-8"))[0]["status"] == "completed"
    # Observable, but not as stderr noise on the hot dispatch path: the count is
    # returned to callers and CI's baseline gate is the hard stop. stderr fires
    # only ABOVE the frozen baseline — see test_status_audit_warns_above_baseline.
    assert nt._audit_task_statuses([{"id": "legacy", "status": "completed"}]) == 1
    assert "out-of-vocab" not in capsys.readouterr().err


# ------------------------------------------------------- content materializer --

def test_content_materializer_routes_through_hardened_writer(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from volpred.ops import content

    def fake_project_path(*parts: str) -> Path:
        path = tmp_path
        for part in parts:
            path = path / part
        return path

    monkeypatch.setattr(content, "project_path", fake_project_path)

    calls: list[int] = []
    real_writer = nt.write_tasks_to_handle

    def spy(fh, tasks):
        calls.append(len(tasks))
        return real_writer(fh, tasks)

    monkeypatch.setattr(content, "write_tasks_to_handle", spy)

    result = content._materialize_release_audit_fix_task(
        item={"id": "art-1", "title": "Test Article"},
        audit_issues=["missing chart"],
        skip_count=1,
        storage_dir="storage",
        now=datetime.now(timezone.utc),
    )

    assert result["created"] is True
    assert calls, "materializer did not route through write_tasks_to_handle"
    written = json.loads((tmp_path / "storage" / "next_tasks.json").read_text())
    assert written[0]["status"] == "pending"
    assert nt.is_valid_status(written[0]["status"])


# ----------------------------------------------------- questions materializer --

def test_questions_materializer_routes_through_hardened_writer(tmp_path, monkeypatch):
    from volpred.ops import questions

    def fake_project_path(*parts: str) -> Path:
        path = tmp_path
        for part in parts:
            path = path / part
        return path

    monkeypatch.setattr(questions, "project_path", fake_project_path)
    monkeypatch.setattr(
        questions,
        "get_member_question_ranking_summary",
        lambda source="user", limit=10: {
            "health": {"researching": 0},
            "ranked_table": [
                {
                    "question_id": "abc12345-0000-0000-0000-000000000000",
                    "question": "測試提問？",
                    "proposer": "tester",
                    "status": "ranked",
                    "score": 6.0,
                    "created_at": "2020-01-01T00:00:00+00:00",
                }
            ],
            "pending_questions": [],
        },
    )

    calls: list[int] = []
    real_writer = nt.write_tasks_to_handle

    def spy(fh, tasks):
        calls.append(len(tasks))
        return real_writer(fh, tasks)

    monkeypatch.setattr(questions, "write_tasks_to_handle", spy)

    result = questions.ensure_member_qa_task()

    assert result["created"] is True
    assert calls, "materializer did not route through write_tasks_to_handle"
    written = json.loads((tmp_path / "storage" / "next_tasks.json").read_text())
    assert written[0]["task_type"] == "member_qa"
    assert nt.is_valid_status(written[0]["status"])


# ------------------------------------------------------------ migrate guard --

def test_migrate_rejects_invalid_derived_status(monkeypatch):
    import importlib

    migrate = importlib.import_module("scripts.migrate_blocked_lane_terminal")
    monkeypatch.setattr(migrate, "terminal_status_for_deprecated", lambda task: "not_a_real_status")

    tasks = [{"id": "k1", "status": "blocked", "blocked_reason": "deprecated"}]
    with pytest.raises(nt.InvalidTaskStatus):
        migrate.migrate_tasks(tasks)


def test_migrate_accepts_valid_derived_status():
    import importlib

    migrate = importlib.import_module("scripts.migrate_blocked_lane_terminal")
    tasks = [{"id": "k1", "status": "blocked", "blocked_reason": "deprecated", "title": "duplicate arc"}]
    migrate.migrate_tasks(tasks)
    assert nt.is_valid_status(tasks[0]["status"])


# --------------------------------------------------------- CI baseline gate --

def test_validator_passes_on_current_file():
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--baseline", str(BASELINE)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_current_out_of_vocab_count_matches_frozen_baseline():
    from scripts import validate_next_tasks_status as vns

    tasks = json.loads(REAL_NEXT_TASKS.read_text(encoding="utf-8"))
    assert vns.count_out_of_vocab(tasks) == BASELINE


def test_validator_flags_one_injected_out_of_vocab_row(tmp_path):
    from scripts import validate_next_tasks_status as vns

    tasks = json.loads(REAL_NEXT_TASKS.read_text(encoding="utf-8"))
    current = vns.count_out_of_vocab(tasks)  # frozen baseline, computed not hardcoded
    tasks.append({"id": "injected", "status": "hand_written_bogus", "priority": 3})
    fixture = tmp_path / "next_tasks.json"
    fixture.write_text(json.dumps(tasks), encoding="utf-8")

    # current+1 out-of-vocab rows -> exceeds baseline -> exit 1
    over = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", str(fixture), "--baseline", str(current)],
        capture_output=True,
        text=True,
    )
    assert over.returncode == 1, over.stdout + over.stderr

    # raising the baseline by exactly one absorbs the injected row -> exit 0
    at = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", str(fixture), "--baseline", str(current + 1)],
        capture_output=True,
        text=True,
    )
    assert at.returncode == 0, at.stdout + at.stderr


# ------------------------------------------- whole-file path must never brick --


def test_baseline_constant_mirrors_validator_default():
    """The module and the deps-free CI validator must not drift apart."""
    src = VALIDATOR.read_text(encoding="utf-8")
    for line in src.splitlines():
        if line.startswith("DEFAULT_BASELINE"):
            validator_baseline = int(line.split("=", 1)[1].strip())
            break
    else:
        pytest.fail("validate_next_tasks_status.py has no DEFAULT_BASELINE")
    assert nt.LEGACY_OUT_OF_VOCAB_BASELINE == validator_baseline == BASELINE


def test_whole_file_write_tolerates_malformed_legacy_priority(tmp_path, capsys):
    """One bad priority must not fail the write for every other row.

    `normalize_task_priority` is strict by design for a row a caller just built.
    On the whole-file path that strictness would make one malformed legacy row
    brick every materializer write -- the bricking `_audit_task_statuses`
    already refuses to cause.
    """
    tasks = [
        {"id": "good", "status": "pending", "priority": 2},
        {"id": "legacy-bad", "status": "succeeded", "priority": {"nested": "junk"}},
        {"id": "also-good", "status": "pending", "priority": "P3"},
    ]
    p = tmp_path / "next_tasks.json"
    p.write_text("[]", encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        nt.write_tasks_to_handle(fh, tasks)

    written = json.loads(p.read_text(encoding="utf-8"))
    assert [t["id"] for t in written] == ["good", "legacy-bad", "also-good"]
    assert written[2]["priority"] == 3, "well-formed legacy label still normalized"
    assert written[1]["priority"] == {"nested": "junk"}, "bad row left untouched"
    assert "malformed priority" in capsys.readouterr().err


def test_status_audit_is_quiet_at_or_below_baseline(tmp_path, capsys):
    """A frozen, known fact must not be re-warned on every dispatch write."""
    tasks = [{"id": "legacy", "status": "completed", "priority": 3}]
    p = tmp_path / "next_tasks.json"
    p.write_text("[]", encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        nt.write_tasks_to_handle(fh, tasks)
    assert "out-of-vocab" not in capsys.readouterr().err


# ------------------------------------------------- blocked_until invariant --
# Mechanical regression stop for the infinite-parking hole (boss Telegram msg
# 937, 2026-07-18): a blocked row with no blocked_until is unreachable by
# scripts/unblock_expired_blocked_tasks.py's expiry sweep, so it parks forever.
# This file is the single enforcement owner for the gate; scripts/daily_checkup.py
# already reports the >30d blocked-rot dimension and is deliberately NOT extended
# with a second check of the same concern.


def _count_blocked_without_until(tasks) -> int:
    n = 0
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if str(t.get("status") or "").strip().lower() != "blocked":
            continue
        until = t.get("blocked_until")
        if until is None or (isinstance(until, str) and not until.strip()):
            n += 1
    return n


def test_blocked_without_until_baseline_constant_mirrors_module():
    assert nt.LEGACY_BLOCKED_WITHOUT_UNTIL_BASELINE == BLOCKED_NO_UNTIL_BASELINE


def test_real_queue_blocked_without_until_at_or_below_baseline():
    """THE gate: any NEW blocked row lacking an exit fails CI."""
    tasks = json.loads(REAL_NEXT_TASKS.read_text(encoding="utf-8"))
    count = _count_blocked_without_until(tasks)
    assert count <= BLOCKED_NO_UNTIL_BASELINE, (
        f"{count} blocked rows have no blocked_until (baseline "
        f"{BLOCKED_NO_UNTIL_BASELINE}). A blocked row with no expiry can never be "
        "re-pended by scripts/unblock_expired_blocked_tasks.py -- it parks forever. "
        "Set blocked_until via scripts/mark_task_blocked.py, or call "
        "volpred.ops.next_tasks.enforce_blocked_until in the writer."
    )


def test_enforce_blocked_until_autofills_on_strict_path():
    task = {"id": "k1", "status": "blocked", "blocked_reason": "prior_attempts_failed"}
    assert nt.enforce_blocked_until(task) is True
    # Filled value must be a parseable future ISO timestamp.
    from datetime import datetime, timezone

    assert datetime.fromisoformat(task["blocked_until"]) > datetime.now(timezone.utc)


def test_enforce_blocked_until_is_a_noop_for_non_blocked_and_for_valid_rows():
    pending = {"id": "k2", "status": "pending"}
    assert nt.enforce_blocked_until(pending) is False
    assert "blocked_until" not in pending

    ok = {"id": "k3", "status": "blocked", "blocked_until": "2026-08-01T00:00:00+00:00"}
    assert nt.enforce_blocked_until(ok) is False
    assert ok["blocked_until"] == "2026-08-01T00:00:00+00:00"


def test_enforce_blocked_until_raises_on_unusable_value():
    with pytest.raises(nt.InvalidBlockedUntil):
        nt.enforce_blocked_until({"id": "k4", "status": "blocked", "blocked_until": 1234})


def test_blocked_until_audit_is_quiet_on_well_formed_blocked_rows(tmp_path, capsys):
    """A properly-expiring block is the normal case and must stay silent."""
    tasks = [
        {"id": "b1", "status": "blocked", "priority": 3, "blocked_until": "2099-01-01T00:00:00+00:00"},
        {"id": "p1", "status": "pending", "priority": 3},
    ]
    p = tmp_path / "next_tasks.json"
    p.write_text("[]", encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        nt.write_tasks_to_handle(fh, tasks)
    assert "blocked_until" not in capsys.readouterr().err


def test_blocked_until_audit_never_raises_and_never_rewrites(tmp_path, capsys):
    """Whole-file contract: report, but do not brick the write and do not 修資料.

    Raising here would fail EVERY materializer (content, questions, claim,
    complete) the moment one bad row existed -- the same bricking
    ``_audit_task_statuses`` refuses to cause. Auto-filling would instead erase
    the evidence the adjudication queue works from.
    """
    tasks = [{"id": "no-exit", "status": "blocked", "priority": 3}]
    p = tmp_path / "next_tasks.json"
    p.write_text("[]", encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        nt.write_tasks_to_handle(fh, tasks)  # must not raise
    written = json.loads(p.read_text(encoding="utf-8"))
    assert written[0]["id"] == "no-exit"
    assert "blocked_until" not in written[0], "audit must report, not rewrite"
    assert nt._audit_blocked_until(tasks) == 1


def test_blocked_until_audit_warns_above_baseline(tmp_path, capsys):
    tasks = [
        {"id": f"legacy-{i}", "status": "blocked", "priority": 3}
        for i in range(nt.LEGACY_BLOCKED_WITHOUT_UNTIL_BASELINE + 1)
    ]
    p = tmp_path / "next_tasks.json"
    p.write_text("[]", encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        nt.write_tasks_to_handle(fh, tasks)
    err = capsys.readouterr().err
    assert "ABOVE frozen baseline" in err
    assert "park forever" in err


def test_status_audit_warns_above_baseline(tmp_path, capsys):
    tasks = [
        {"id": f"bad-{i}", "status": "totally_made_up", "priority": 3}
        for i in range(nt.LEGACY_OUT_OF_VOCAB_BASELINE + 1)
    ]
    p = tmp_path / "next_tasks.json"
    p.write_text("[]", encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        nt.write_tasks_to_handle(fh, tasks)
    err = capsys.readouterr().err
    assert "ABOVE frozen baseline" in err
