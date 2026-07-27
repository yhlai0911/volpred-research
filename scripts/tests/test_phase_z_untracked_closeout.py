"""A failed-closeout claim must always have an exit (2026-07-18).

The incident: `scripts/gen_codex_cli_reference.py` was pinned by a rejected
PHASE-Z candidate, stayed UNTRACKED, and was then edited. That put it in a
bucket with no escape under the old classifier:

  - dirty          → not "landed"
  - drifted        → not "unresolved"
  - untracked      → `git log --since=<receipt> --name-only` can never name it,
                     so "carried forward" is false BY DEFINITION, not "not yet"

…which is the `conflicts` bucket, which emitted a CRITICAL every fire and had
no state transition out of itself. The only off switch was a human deleting
`.git/volpred_phase_z_failed_closeout.json`. The boss got paged twice about the
same alert 25+ hours apart.

These pins are about the CLASS, not the one file: every bucket a pinned path can
land in must terminate, and the drifted bucket must terminate WITHOUT human
action. `tests/test_worker_hang_log_capture.py` was the same shape one edit away
from firing.
"""
from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import phase_z


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r.parent, "init", "-q", "-b", "main", str(r))
    _git(r, "config", "user.email", "t@t.t")
    _git(r, "config", "user.name", "t")
    hook = r / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    (r / "seed.txt").write_text("seed\n")
    _git(r, "add", "seed.txt")
    _git(r, "commit", "-qm", "seed")
    return r


def _block(repo: Path) -> None:
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho '[pre-commit] BLOCKED — fake gate' >&2\nexit 1\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)


def _unblock(repo: Path) -> None:
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)


def _receipt(repo: Path) -> Path:
    return repo / ".git" / phase_z._FAILED_CLOSEOUT_BASENAME


def _fire(repo: Path, alerts: list[dict]) -> dict:
    return phase_z.run_phase_z(
        repo_root=repo, now_hhmm="07:07",
        test_runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
        alert_fn=lambda **k: alerts.append(k) or {},
    )


def _recover(repo: Path, alerts: list[dict]) -> dict:
    return phase_z.recover_failed_closeout(
        repo_root=repo,
        test_runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
        alert_fn=lambda **k: alerts.append(k) or {},
    )


def _pin_untracked_failure(repo: Path, rel: str = "scripts/gen_ref.py") -> None:
    """Materialize a pre-retirement receipt without reviving timing auto-claim."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("original agent output\n")
    assert phase_z._ensure_failed_closeout(
        repo,
        owned=[rel],
        reason="commit_nonzero",
        commit_tail="[pre-commit] BLOCKED — legacy fixture",
        receipt={"subject": "legacy rejected fire", "body": "", "task_id": ""},
        runner=subprocess.run,
    )
    assert _receipt(repo).exists()
    # The path must really be untracked — that is the whole premise.
    assert _git(repo, "status", "--porcelain", "--", rel).startswith("??")


# (a) untracked + drifted → must NOT produce an unclosable conflict ──────────
def test_untracked_drifted_releases_and_self_heals(repo: Path):
    _pin_untracked_failure(repo)
    head_before = _git(repo, "rev-parse", "HEAD").strip()
    _unblock(repo)

    (repo / "scripts" / "gen_ref.py").write_text("someone edited this later\n")

    first_alerts: list[dict] = []
    first = _recover(repo, first_alerts)

    assert first["reason"] == "released"
    assert first["released"] == ["scripts/gen_ref.py"]
    # Nothing was committed, overwritten or deleted.
    assert _git(repo, "rev-parse", "HEAD").strip() == head_before
    assert (repo / "scripts" / "gen_ref.py").read_text() == "someone edited this later\n"
    # A warn, not an hourly CRITICAL.
    assert [a["level"] for a in first_alerts] == ["warn"]

    # THE PIN THAT MATTERS: the next pass is silent, with no human intervention.
    second_alerts: list[dict] = []
    second = _recover(repo, second_alerts)
    assert second["reason"] == "no_failed_closeout"
    assert second_alerts == [], f"the alert repeated with no exit: {second_alerts}"
    assert not _receipt(repo).exists()


def test_release_keeps_the_other_claims_recoverable(repo: Path):
    """Releasing one drifted path must not discard the receipt's live ownership.

    The production receipt held 10 paths; exactly one was the poisoned untracked
    file. Dropping the file wholesale (the manual workaround) would have thrown
    away 9 legitimate claims.
    """
    (repo / "poisoned.py").write_text("original\n")
    (repo / "still_mine.py").write_text("untouched agent output\n")
    assert phase_z._ensure_failed_closeout(
        repo,
        owned=["poisoned.py", "still_mine.py"],
        reason="commit_nonzero",
        commit_tail="blocked",
        receipt=None,
        runner=subprocess.run,
    )

    (repo / "poisoned.py").write_text("edited by someone else\n")
    _unblock(repo)

    alerts: list[dict] = []
    result = _recover(repo, alerts)

    assert result["committed"] is True, result
    assert result["released"] == ["poisoned.py"]
    committed = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert "still_mine.py" in committed
    assert "poisoned.py" not in committed, "a released path must not be adopted"
    assert not _receipt(repo).exists()


# (b) untracked + NOT drifted → behaviour unchanged ──────────────────────────
def test_untracked_unchanged_still_recovers_normally(repo: Path):
    """`tests/test_worker_hang_log_capture.py`'s exact state: untracked, pinned,
    byte-identical. It must still be recovered and committed, not released."""
    _pin_untracked_failure(repo, "tests/test_hang.py")
    _unblock(repo)

    alerts: list[dict] = []
    result = _recover(repo, alerts)

    assert result["committed"] is True, result
    assert "released" not in result
    assert "tests/test_hang.py" in _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert not _receipt(repo).exists()
    assert not _git(repo, "status", "--porcelain").strip()


# (c) tracked + carried forward → the 2026-07-17 fix must not regress ────────
def test_tracked_carried_forward_still_closes_silently(repo: Path):
    (repo / "seed.txt").write_text("seed\nagent line\n")  # tracked, modified
    assert phase_z._ensure_failed_closeout(
        repo,
        owned=["seed.txt"],
        reason="commit_nonzero",
        commit_tail="blocked",
        receipt=None,
        runner=subprocess.run,
    )

    _unblock(repo)
    # A later fire commits the tracked path, then a third writer appends again.
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-qm", "later fire carried it forward")
    (repo / "seed.txt").write_text("seed\nagent line\nthird writer\n")

    alerts: list[dict] = []
    result = _recover(repo, alerts)

    assert result["reason"] == "already_closed"
    assert alerts == [], f"a carried-forward receipt must not page anyone: {alerts}"
    assert not _receipt(repo).exists()


# corrupt receipt: the other no-exit state found in the same-class sweep ─────
def test_corrupt_receipt_is_quarantined_not_wedged(repo: Path):
    """An unparseable receipt used to make every later `_ensure_failed_closeout`
    return False forever — ownership silently unrecordable, with no alert."""
    _receipt(repo).write_text("{ this is not json")

    assert phase_z._read_failed_closeout(repo, subprocess.run) is None
    assert not _receipt(repo).exists(), "corrupt receipt must be moved aside"
    quarantined = list((repo / ".git").glob(f"{phase_z._FAILED_CLOSEOUT_BASENAME}.corrupt-*"))
    assert len(quarantined) == 1, quarantined
    assert quarantined[0].read_text() == "{ this is not json", "forensics bytes kept"

    # And the compatibility reader/writer is functional again.
    (repo / "out.txt").write_text("agent output\n")
    assert phase_z._ensure_failed_closeout(
        repo,
        owned=["out.txt"],
        reason="commit_nonzero",
        commit_tail="blocked",
        receipt=None,
        runner=subprocess.run,
    )
    assert _receipt(repo).exists()
    payload = json.loads(_receipt(repo).read_text())
    assert [e["path"] for e in payload["paths"]] == ["out.txt"]


# stuck-foreign CRITICAL: bounded paging, same alert-fatigue class ───────────
def test_stuck_foreign_streak_pages_with_backoff_not_every_fire():
    notifiable = [n for n in range(1, 40) if phase_z._streak_is_notifiable(n)]
    assert notifiable == [3, 6, 12, 24], notifiable
