"""Tests for stale-claim reclaim logic in claim_next_task (Phase B.4)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops.local_control_plane import (
    AGENT_STALE_SECONDS,
    AUTO_PREFERRED_SESSION_KEY,
    admin_override_claim,
    claim_next_task,
    create_task,
    heartbeat_agent,
    _agent_path,
    _task_path,
    _load_task,
)


def _set_heartbeat(storage_dir: Path, agent_name: str, seconds_ago: int) -> None:
    """Rewrite an agent session with a heartbeat_at N seconds in the past."""
    session_key = AUTO_PREFERRED_SESSION_KEY.get(agent_name, agent_name)
    path = _agent_path(session_key, storage_dir=str(storage_dir))
    session = json.loads(path.read_text())
    ts = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()
    session["heartbeat_at"] = ts
    session["updated_at"] = ts
    path.write_text(json.dumps(session, indent=2))


def test_stale_agent_claim_is_reclaimed(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")

    # Both agents online, claude claims a task then its heartbeat goes stale
    heartbeat_agent(agent_name="claude", storage_dir=storage_dir)
    heartbeat_agent(agent_name="codex", storage_dir=storage_dir)

    task = create_task(
        title="stuck-task",
        description="claude claimed then died",
        task_family="research",
        preferred_agent="auto",
        fallback_allowed=True,
        storage_dir=storage_dir,
    )

    # Claude claims
    claimed = claim_next_task("claude", storage_dir=storage_dir)
    assert claimed is not None
    assert claimed["id"] == task["id"]
    assert claimed["status"] == "claimed"

    # Claude goes stale (heartbeat well past AGENT_STALE_SECONDS)
    _set_heartbeat(Path(storage_dir), "claude", seconds_ago=AGENT_STALE_SECONDS + 60)

    # Refresh codex heartbeat so codex is fresh
    heartbeat_agent(agent_name="codex", storage_dir=storage_dir)

    # Codex attempts to claim → should reclaim claude's stale claim and grab it
    next_claim = claim_next_task("codex", storage_dir=storage_dir)
    assert next_claim is not None, "codex should be able to claim the reclaimed task"
    assert next_claim["id"] == task["id"]
    assert next_claim["claimed_by"] == "codex"

    # Verify writer log captured the reclaim
    log_path = tmp_path / "storage" / "ops" / "writer_log.jsonl"
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    reclaim_entries = [e for e in entries if e["subsystem"] == "control_plane" and "reclaimed" in (e.get("result") or "")]
    assert len(reclaim_entries) >= 1
    assert reclaim_entries[0]["record_id"] == task["id"]
    assert reclaim_entries[0]["actor"] == "system"


def test_admin_override_claim_assigns_specific_agent(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")

    heartbeat_agent(agent_name="claude", storage_dir=storage_dir)
    heartbeat_agent(agent_name="codex", storage_dir=storage_dir)

    task = create_task(
        title="admin-assign",
        description="specific agent",
        preferred_agent="auto",
        storage_dir=storage_dir,
    )

    assigned = admin_override_claim(
        task["id"], agent_name="codex", actor="admin-user", storage_dir=storage_dir
    )
    assert assigned["status"] == "claimed"
    assert assigned["claimed_by"] == "codex"

    log_entries = [
        json.loads(line)
        for line in (tmp_path / "storage" / "ops" / "writer_log.jsonl").read_text().splitlines()
        if line.strip()
    ]
    override_entries = [e for e in log_entries if "admin_override_claim_by_codex" in (e.get("result") or "")]
    assert len(override_entries) == 1
    assert override_entries[0]["actor"] == "admin-user"


def test_admin_override_claim_rejects_terminal_task(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    heartbeat_agent(agent_name="claude", storage_dir=storage_dir)
    task = create_task(
        title="will-be-cancelled",
        description="t",
        storage_dir=storage_dir,
    )

    # Manually mark cancelled
    task_path = _task_path(task["id"], storage_dir=storage_dir)
    payload = json.loads(task_path.read_text())
    payload["status"] = "cancelled"
    task_path.write_text(json.dumps(payload))

    import pytest as _pytest
    with _pytest.raises(ValueError, match="cancelled"):
        admin_override_claim(
            task["id"], agent_name="claude", actor="admin", storage_dir=storage_dir
        )


def test_fresh_agent_claim_is_not_reclaimed(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")

    heartbeat_agent(agent_name="claude", storage_dir=storage_dir)

    task = create_task(
        title="happy-path",
        description="no stale",
        preferred_agent="claude",
        storage_dir=storage_dir,
    )
    claim_next_task("claude", storage_dir=storage_dir)

    # Codex with fresh heartbeat, but claude is still alive → should not steal
    heartbeat_agent(agent_name="codex", storage_dir=storage_dir)
    stolen = claim_next_task("codex", storage_dir=storage_dir)
    assert stolen is None, "codex should not reclaim a fresh claude's task"

    # Task status unchanged
    current = _load_task(task["id"], storage_dir=storage_dir)
    assert current["status"] == "claimed"
    assert current["claimed_by"] == "claude"
