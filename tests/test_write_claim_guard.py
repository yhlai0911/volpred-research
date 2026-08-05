"""Concurrent-write guard: two sessions must not edit the same scope at once.

The gate is verified by making it BITE, not merely by watching it stay quiet —
a guard that passes both before and after the bug is no guard at all.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "scripts" / "hooks" / "write_claim_guard.py"


def run_hook(file_path: str, session: str, *, env_extra: dict | None = None,
             claim_dir: Path | None = None) -> dict:
    payload = {
        "tool_name": "Edit",
        "session_id": session,
        "tool_input": {"file_path": str(REPO / file_path)},
    }
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home())}
    if claim_dir is not None:
        env["VOLPRED_WRITE_CLAIM_DIR"] = str(claim_dir)
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(payload),
        capture_output=True, text=True, env=env, cwd=str(REPO),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout or "{}")


def decision(out: dict) -> str | None:
    return (out.get("hookSpecificOutput") or {}).get("permissionDecision")


@pytest.fixture()
def claims(tmp_path: Path) -> Path:
    return tmp_path / "claims"


def test_first_writer_is_allowed_and_takes_the_claim(claims: Path) -> None:
    out = run_hook("scripts/org/org_status.py", "session-A", claim_dir=claims)

    assert decision(out) is None, "an unclaimed scope must not interrupt anyone"
    written = list(claims.glob("*.json"))
    assert len(written) == 1
    claim = json.loads(written[0].read_text())
    assert claim["session_id"] == "session-A"
    assert claim["scope"] == "scripts/org/"


def test_same_session_keeps_writing(claims: Path) -> None:
    run_hook("scripts/org/org_status.py", "session-A", claim_dir=claims)

    out = run_hook("scripts/org/dept_send.py", "session-A", claim_dir=claims)

    assert decision(out) is None, "a session must never block itself"


def test_second_session_is_denied_the_same_scope(claims: Path) -> None:
    """The real 2026-08-05 incident: a second session edited scripts/org/."""
    run_hook("scripts/org/org_status.py", "session-A", claim_dir=claims)

    out = run_hook("scripts/org/dept_routing.py", "session-B", claim_dir=claims)

    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "session-A"[:8] in reason, "the block must name who holds it"
    assert "path_claims.py release" in reason, "a block must offer a way out"
    assert "VOLPRED_ALLOW_CONCURRENT_WRITE" in reason


def test_expired_claim_stops_blocking(claims: Path) -> None:
    run_hook("scripts/org/org_status.py", "session-A",
             env_extra={"VOLPRED_WRITE_CLAIM_TTL": "0"}, claim_dir=claims)

    out = run_hook("scripts/org/dept_routing.py", "session-B", claim_dir=claims)

    assert decision(out) is None, "a stale session must not block work forever"


def test_unrelated_scopes_do_not_collide(claims: Path) -> None:
    run_hook("scripts/org/org_status.py", "session-A", claim_dir=claims)

    out = run_hook("paper/README.md", "session-B", claim_dir=claims)

    assert decision(out) is None, "parallel work in different areas must still flow"


def test_shared_directory_is_claimed_per_file(claims: Path) -> None:
    """Claiming all of scripts/ would block every worker and get overridden."""
    run_hook("scripts/token_usage_report.py", "session-A", claim_dir=claims)

    out = run_hook("scripts/daily_update.py", "session-B", claim_dir=claims)

    assert decision(out) is None
    same_file = run_hook("scripts/token_usage_report.py", "session-B", claim_dir=claims)
    assert decision(same_file) == "deny", "the same file is always a clash"


def test_override_is_allowed_but_recorded(claims: Path, tmp_path: Path) -> None:
    log = tmp_path / "overrides.jsonl"
    run_hook("scripts/org/org_status.py", "session-A", claim_dir=claims)

    out = run_hook("scripts/org/dept_routing.py", "session-B", claim_dir=claims,
                   env_extra={"VOLPRED_ALLOW_CONCURRENT_WRITE": "1",
                              "VOLPRED_WRITE_CLAIM_OVERRIDE_LOG": str(log)})

    assert decision(out) == "allow"
    assert log.exists(), "a silent override is indistinguishable from no gate"
    assert "session-A" in log.read_text()


def test_malformed_payload_never_breaks_edit(claims: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input="not json",
        capture_output=True, text=True, cwd=str(REPO),
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()),
             "VOLPRED_WRITE_CLAIM_DIR": str(claims)},
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "{}"


def test_a_department_does_not_block_its_own_next_session(claims: Path) -> None:
    """Observed: content could not land drafts because an earlier content
    session still held storage/drafts/. Successive panes are the same writer."""
    run_hook("storage/drafts/a.md", "session-A", claim_dir=claims,
             env_extra={"VOLPRED_ORG_DEPT": "content"})

    out = run_hook("storage/drafts/b.md", "session-B", claim_dir=claims,
                   env_extra={"VOLPRED_ORG_DEPT": "content"})

    assert decision(out) is None, "the department is the writer, not the session"


def test_another_department_is_still_blocked(claims: Path) -> None:
    run_hook("storage/drafts/a.md", "session-A", claim_dir=claims,
             env_extra={"VOLPRED_ORG_DEPT": "content"})

    out = run_hook("storage/drafts/b.md", "session-B", claim_dir=claims,
                   env_extra={"VOLPRED_ORG_DEPT": "research"})

    assert decision(out) == "deny"
    assert "dept:content" in out["hookSpecificOutput"]["permissionDecisionReason"]
