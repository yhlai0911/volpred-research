#!/usr/bin/env python3
"""Regression tests for the foreign-path disposition actuator.

`volpred.ops.foreign_incident` de-rates the scheduler's slot cap while paths sit
uncommitted with no owner, but nothing in the system could ever make those paths
clean — PHASE-Z skips foreign files by construction, agents are barred from
mutating the shared checkout, and guess-based adoption was banned by D1. Every
fire ran at half capacity and no fire could exit the state on its own.

These tests pin the three invariants that make an exit safe. Losing any one of
them turns the actuator into the failure it was built to end:

  - it touches ONLY the declared paths (the 2026-07-10 `git add -A` incident);
  - it refuses to act unless the bytes survive elsewhere first;
  - it verifies the post-state mechanically instead of self-declaring success.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from volpred.ops.foreign_disposition import (  # noqa: E402
    DispositionError,
    _commit_message,
    apply_disposition,
    load_disposition,
    preflight,
)

ACTOR = "test-actor"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args],
                          check=True, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "commit.gpgsign", "false")
    (r / "tracked.py").write_text("original\n", encoding="utf-8")
    (r / "bystander.py").write_text("bystander\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "base", "--no-verify")
    return r


def _spec(**paths: tuple[str, str]) -> dict:
    return {
        "adjudicated_by": "test",
        "incident": "test_incident",
        "paths": {rel: {"action": a, "reason": why} for rel, (a, why) in paths.items()},
    }


# ── disposition schema ───────────────────────────────────────────────────────

def test_commit_message_identifies_codex_adjudication() -> None:
    disposition = {
        "adjudicated_by": "codex-vscode",
        "incident": "phase-z-foreign-example",
        "paths": {"artifact.txt": {"action": "commit", "reason": "verified output"}},
    }

    message = _commit_message(disposition, ["artifact.txt"])

    assert message.startswith("[codex] chore(foreign):")


def test_load_rejects_missing_signature_and_reason(tmp_path: Path) -> None:
    """A disposition with no author or no reason is state nobody can re-derive."""
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"paths": {"a.py": {"action": "delete", "reason": "x"}}}),
                 encoding="utf-8")
    with pytest.raises(DispositionError, match="adjudicated_by"):
        load_disposition(p)

    p.write_text(json.dumps({"adjudicated_by": "me",
                             "paths": {"a.py": {"action": "delete"}}}), encoding="utf-8")
    with pytest.raises(DispositionError, match="reason"):
        load_disposition(p)


def test_load_rejects_escaping_paths_and_unknown_actions(tmp_path: Path) -> None:
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"adjudicated_by": "me",
                             "paths": {"../etc/passwd": {"action": "delete", "reason": "x"}}}),
                 encoding="utf-8")
    with pytest.raises(DispositionError, match=r"\.\."):
        load_disposition(p)

    p.write_text(json.dumps({"adjudicated_by": "me",
                             "paths": {"a.py": {"action": "purge", "reason": "x"}}}),
                 encoding="utf-8")
    with pytest.raises(DispositionError, match="action"):
        load_disposition(p)


# ── invariant 2: bytes must survive first ────────────────────────────────────

def test_preflight_refuses_when_bytes_are_not_retrievable(repo: Path) -> None:
    """An untracked file with no quarantine ref has exactly one copy — deleting
    it is data loss, not cleanup."""
    (repo / "orphan.py").write_text("only copy\n", encoding="utf-8")
    report = preflight(repo, _spec(**{"orphan.py": ("delete", "no owner")}))
    assert report["ready"] is False
    assert "orphan.py" in report["refusals"][0]
    assert report["paths"]["orphan.py"]["retrievable"] is False


def test_apply_is_all_or_nothing_when_one_path_is_refused(repo: Path) -> None:
    (repo / "tracked.py").write_text("edited\n", encoding="utf-8")
    (repo / "orphan.py").write_text("only copy\n", encoding="utf-8")
    report = apply_disposition(
        repo,
        _spec(**{"tracked.py": ("delete", "superseded"),
                 "orphan.py": ("delete", "no owner")}),
        actor=ACTOR,
    )
    assert report["applied"] is False
    assert report["stage"] == "preflight"
    # The safe path must NOT have been processed on its own.
    assert (repo / "tracked.py").read_text(encoding="utf-8") == "edited\n"


# ── delete / commit behaviour ────────────────────────────────────────────────

def test_delete_restores_tracked_file_from_head(repo: Path) -> None:
    (repo / "tracked.py").write_text("edited\n", encoding="utf-8")
    report = apply_disposition(
        repo, _spec(**{"tracked.py": ("delete", "owner reworked it in a worktree")}),
        actor=ACTOR,
    )
    assert report["verified"] is True
    assert report["results"]["tracked.py"] == "restored_from_head"
    assert (repo / "tracked.py").read_text(encoding="utf-8") == "original\n"


def test_commit_lands_only_declared_paths(repo: Path) -> None:
    """`git commit -- <paths>` must leave a concurrently-edited bystander alone."""
    (repo / "tracked.py").write_text("adopted\n", encoding="utf-8")
    (repo / "bystander.py").write_text("someone else is editing this\n", encoding="utf-8")

    report = apply_disposition(
        repo, _spec(**{"tracked.py": ("commit", "belongs to main")}), actor=ACTOR,
    )
    assert report["verified"] is True
    assert report["results"]["tracked.py"] == "committed"
    assert report["commit"]

    committed = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert committed == ["tracked.py"]
    # The bystander's uncommitted work is still uncommitted and still intact.
    assert (repo / "bystander.py").read_text(encoding="utf-8") == "someone else is editing this\n"
    assert "bystander.py" in _git(repo, "status", "--porcelain").stdout


def test_untracked_file_is_removable_once_quarantined(repo: Path, monkeypatch) -> None:
    """Retrievability may come from a quarantine ref rather than HEAD."""
    (repo / "stray.py").write_text("stray\n", encoding="utf-8")
    monkeypatch.setattr(
        "volpred.ops.foreign_disposition.quarantine_covered_paths",
        lambda *a, **k: {"stray.py"},
    )
    report = apply_disposition(
        repo, _spec(**{"stray.py": ("delete", "checkpointed into quarantine ref")}),
        actor=ACTOR,
    )
    assert report["verified"] is True
    assert report["results"]["stray.py"] == "removed_untracked"
    assert not (repo / "stray.py").exists()


# ── invariant 1 + 3: no collateral, verified post-state ──────────────────────

def test_leave_is_recorded_without_touching_the_file(repo: Path) -> None:
    """`leave` is a signed non-decision — it must not make the incident closeable
    by pretending the path got handled."""
    (repo / "tracked.py").write_text("edited\n", encoding="utf-8")
    report = apply_disposition(
        repo, _spec(**{"tracked.py": ("leave", "owner task assign_x still open")}),
        actor=ACTOR,
    )
    assert report["applied"] is True
    assert report["paths"]["tracked.py"]["verdict"] == "leave"
    assert "tracked.py" not in report["results"]
    assert (repo / "tracked.py").read_text(encoding="utf-8") == "edited\n"
    assert "tracked.py" in _git(repo, "status", "--porcelain").stdout


def test_already_clean_path_is_a_noop_not_a_failure(repo: Path) -> None:
    report = apply_disposition(
        repo, _spec(**{"tracked.py": ("delete", "already cleaned by its owner")}),
        actor=ACTOR,
    )
    assert report["verified"] is True
    assert report["paths"]["tracked.py"]["verdict"] == "noop"


def test_dry_run_writes_nothing(repo: Path) -> None:
    (repo / "tracked.py").write_text("edited\n", encoding="utf-8")
    report = apply_disposition(
        repo, _spec(**{"tracked.py": ("delete", "x")}), actor=ACTOR, dry_run=True,
    )
    assert report["applied"] is False
    assert report["stage"] == "dry_run"
    assert (repo / "tracked.py").read_text(encoding="utf-8") == "edited\n"
