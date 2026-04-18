"""Tests for Phase B (signals / curate) + Phase C (session identity) refactor.

Covers:
  - resolve_session_key() canonical + legacy inputs
  - heartbeat_agent with session_key writes {session_key}.json
  - Three concurrent sessions (claude-supervisor, claude-worker, codex-worker)
    can coexist without overwriting one another
  - claim_next_task records claimed_by_session_key / claimed_by_role
  - complete_task propagates signal_payload + session_key into TaskRecord and
    ExecutionReceipt
  - list_pending_curations / curate_task workflow
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from volpred.ops.local_control_plane import (
    AUTO_PREFERRED_SESSION_KEY,
    SESSION_KEY_SPEC,
    _agent_path,
    claim_next_task,
    complete_task,
    create_task,
    curate_task,
    fail_task,
    get_task,
    heartbeat_agent,
    list_agent_sessions,
    list_pending_curations,
    resolve_session_key,
)


def test_resolve_session_key_accepts_canonical_session_key():
    key, agent, role = resolve_session_key(session_key="claude-supervisor")
    assert key == "claude-supervisor"
    assert agent == "claude"
    assert role == "supervisor"


def test_resolve_session_key_accepts_legacy_agent_name_defaults_to_worker():
    key, agent, role = resolve_session_key(agent_name="claude")
    assert key == "claude-worker"
    assert agent == "claude"
    assert role == "worker"


def test_resolve_session_key_accepts_agent_plus_role():
    key, agent, role = resolve_session_key(agent_name="claude", role="supervisor")
    assert key == "claude-supervisor"
    assert agent == "claude"
    assert role == "supervisor"


def test_resolve_session_key_rejects_conflicting_session_key_and_agent():
    with pytest.raises(ValueError, match="conflicts with session_key"):
        resolve_session_key(session_key="claude-supervisor", agent_name="codex")


def test_resolve_session_key_rejects_unknown_combination():
    with pytest.raises(ValueError, match="not a supported session"):
        resolve_session_key(agent_name="codex", role="supervisor")


def test_resolve_session_key_requires_input():
    with pytest.raises(ValueError, match="session_key or agent_name"):
        resolve_session_key()


def test_heartbeat_agent_writes_file_keyed_on_session_key(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(session_key="claude-supervisor", storage_dir=storage_dir)
    expected = _agent_path("claude-supervisor", storage_dir=storage_dir)
    assert expected.exists(), "session file should live under claude-supervisor.json"
    payload = json.loads(expected.read_text())
    assert payload["session_key"] == "claude-supervisor"
    assert payload["role"] == "supervisor"
    assert payload["agent_name"] == "claude"


def test_heartbeat_legacy_agent_name_still_works_and_maps_to_worker(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(agent_name="claude", storage_dir=storage_dir)
    expected = _agent_path("claude-worker", storage_dir=storage_dir)
    assert expected.exists(), "legacy --agent claude should default to worker role"
    payload = json.loads(expected.read_text())
    assert payload["role"] == "worker"
    assert payload["session_key"] == "claude-worker"


def test_three_concurrent_sessions_do_not_collide(tmp_path: Path):
    """The whole point of Phase C: 3-terminal workflow must not have sessions
    stomping on each other."""
    storage_dir = str(tmp_path / "storage")

    heartbeat_agent(
        session_key="claude-supervisor",
        terminal_label="VSCode T1",
        storage_dir=storage_dir,
    )
    heartbeat_agent(
        session_key="claude-worker",
        terminal_label="VSCode T2",
        storage_dir=storage_dir,
    )
    heartbeat_agent(
        session_key="codex-worker",
        terminal_label="VSCode T3",
        storage_dir=storage_dir,
    )

    sessions = list_agent_sessions(storage_dir=storage_dir)
    session_keys = {str(session.get("session_key")) for session in sessions}
    assert session_keys == {
        "claude-supervisor",
        "claude-worker",
        "codex-worker",
    }

    # Verify each kept its own terminal_label (no cross-pollution).
    label_by_key = {
        str(s.get("session_key")): s.get("terminal_label") for s in sessions
    }
    assert label_by_key["claude-supervisor"] == "VSCode T1"
    assert label_by_key["claude-worker"] == "VSCode T2"
    assert label_by_key["codex-worker"] == "VSCode T3"


def test_claim_records_session_key_and_role(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(session_key="claude-worker", storage_dir=storage_dir)
    task = create_task(
        title="claim-with-session-key",
        description="session identity propagation",
        task_family="research",
        preferred_agent="claude",
        storage_dir=storage_dir,
    )
    claimed = claim_next_task(session_key="claude-worker", storage_dir=storage_dir)
    assert claimed is not None
    assert claimed["id"] == task["id"]
    assert claimed["claimed_by"] == "claude"
    assert claimed["claimed_by_session_key"] == "claude-worker"
    assert claimed["claimed_by_role"] == "worker"


def test_supervisor_session_does_not_block_worker_claim(tmp_path: Path):
    """claude-supervisor being busy must not keep claude-worker from claiming."""
    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(
        session_key="claude-supervisor",
        status="busy",
        storage_dir=storage_dir,
    )
    heartbeat_agent(session_key="claude-worker", storage_dir=storage_dir)

    task = create_task(
        title="worker-only",
        description="claude-worker must still be able to claim",
        task_family="research",
        preferred_agent="claude",
        storage_dir=storage_dir,
    )
    claimed = claim_next_task(session_key="claude-worker", storage_dir=storage_dir)
    assert claimed is not None, (
        "supervisor being busy must not prevent worker from claiming"
    )
    assert claimed["id"] == task["id"]
    assert claimed["claimed_by_session_key"] == "claude-worker"


def test_complete_task_persists_signal_payload(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(session_key="codex-worker", storage_dir=storage_dir)
    task = create_task(
        title="codex-signal-payload",
        description="verify signal payload round-trips",
        task_family="code",
        preferred_agent="codex",
        storage_dir=storage_dir,
    )
    claim_next_task(session_key="codex-worker", storage_dir=storage_dir)

    signal = {
        "summary_text": "refactor succeeded",
        "null_result": False,
        "knowledge_candidates": [
            {
                "topic": "session_identity",
                "one_line_finding": "session_key model supports 3 concurrent terminals",
                "evidence_paths": ["tests/test_session_identity_and_curate.py"],
                "confidence": "strong",
            }
        ],
        "followup_task_candidates": [
            {
                "title": "update docs with session-key examples",
                "priority": "P4",
                "preferred_family": "content",
            }
        ],
        "frontend_impact": {"pipeline": "none", "requires_sync": False},
    }
    result = complete_task(
        task["id"],
        session_key="codex-worker",
        summary="structural refactor clean",
        signal_payload=signal,
        storage_dir=storage_dir,
    )
    assert result["task"]["status"] == "succeeded"
    assert result["task"]["signal_payload"]["summary_text"] == "refactor succeeded"
    assert result["task"]["claimed_by_session_key"] == "codex-worker"
    assert result["task"]["claimed_by_role"] == "worker"

    # Receipt must also record session_key/role + the signal payload.
    receipt = result["receipt"]
    assert receipt["session_key"] == "codex-worker"
    assert receipt["role"] == "worker"
    assert receipt["signal_payload"]["knowledge_candidates"][0]["topic"] == "session_identity"


def test_fail_task_persists_signal_payload(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(session_key="claude-worker", storage_dir=storage_dir)
    task = create_task(
        title="fails-with-signal",
        description="signal captured even on failure",
        task_family="research",
        preferred_agent="claude",
        storage_dir=storage_dir,
    )
    claim_next_task(session_key="claude-worker", storage_dir=storage_dir)

    result = fail_task(
        task["id"],
        session_key="claude-worker",
        error="convergence_failure",
        summary="estimator diverged",
        signal_payload={"null_result": True, "experience_candidates": [{"lesson": "multistart"}]},
        storage_dir=storage_dir,
    )
    assert result["task"]["status"] == "failed"
    assert result["task"]["signal_payload"]["null_result"] is True
    assert result["receipt"]["signal_payload"]["experience_candidates"][0]["lesson"] == "multistart"
    assert result["receipt"]["role"] == "worker"


def test_pending_curations_and_curate_flow(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(session_key="claude-worker", storage_dir=storage_dir)

    # Task 1: completed but not curated
    task1 = create_task(
        title="awaiting-curation",
        description="worker done, supervisor should promote",
        task_family="research",
        preferred_agent="claude",
        storage_dir=storage_dir,
    )
    claim_next_task(session_key="claude-worker", storage_dir=storage_dir)
    complete_task(
        task1["id"],
        session_key="claude-worker",
        summary="finding A",
        signal_payload={"knowledge_candidates": [{"topic": "A", "one_line_finding": "A"}]},
        storage_dir=storage_dir,
    )

    # Task 2: completed AND already curated
    task2 = create_task(
        title="already-curated",
        description="supervisor finished this loop",
        task_family="research",
        preferred_agent="claude",
        storage_dir=storage_dir,
    )
    claim_next_task(session_key="claude-worker", storage_dir=storage_dir)
    complete_task(
        task2["id"], session_key="claude-worker", summary="done", storage_dir=storage_dir
    )
    curate_task(
        task2["id"],
        actor="claude-supervisor",
        promoted=["research_program.md"],
        notes="promoted",
        storage_dir=storage_dir,
    )

    pending = list_pending_curations(storage_dir=storage_dir)
    pending_ids = {str(p.get("id")) for p in pending}
    assert task1["id"] in pending_ids
    assert task2["id"] not in pending_ids, "already-curated task must not appear"

    # Curate task1 and verify promotion trail is recorded.
    curated = curate_task(
        task1["id"],
        actor="claude-supervisor",
        promoted=["storage/memory/knowledge.json", "research_program.md"],
        notes="k-index updated",
        storage_dir=storage_dir,
    )
    assert curated["curated_by"] == "claude-supervisor"
    assert curated["curated_promoted"] == [
        "storage/memory/knowledge.json",
        "research_program.md",
    ]
    assert curated["curated_notes"] == "k-index updated"

    still_pending = list_pending_curations(storage_dir=storage_dir)
    assert all(str(p.get("id")) != task1["id"] for p in still_pending)


def test_curate_rejects_non_succeeded_task(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    task = create_task(
        title="queued-not-curatable",
        description="cannot curate queued task",
        task_family="research",
        storage_dir=storage_dir,
    )
    with pytest.raises(ValueError, match="Only succeeded tasks"):
        curate_task(task["id"], actor="claude-supervisor", storage_dir=storage_dir)


def test_session_key_spec_constant_covers_all_canonical_keys():
    assert set(SESSION_KEY_SPEC) == {
        "claude-supervisor",
        "claude-worker",
        "codex-worker",
    }
    assert AUTO_PREFERRED_SESSION_KEY == {
        "claude": "claude-worker",
        "codex": "codex-worker",
    }
