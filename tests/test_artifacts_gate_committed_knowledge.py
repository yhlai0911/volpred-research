"""The knowledge half of the artifact gate must evaluate COMMITTED state in ref mode.

Regression for 2026-08-04 k1735: the merge-side gate and the CI gate are the same
script, but merge read the working-tree knowledge.json while CI read the pushed
commit. An uncommitted K1735 entry satisfied the merge gate at 12:43; the push
carried no entry and CI went red at 12:48 (Experiment Artifacts Gate, run
30879353621 on ca712fc). ``--knowledge-ref HEAD`` (now passed by
merge_worktree.sh) makes the merge gate read the committed blob, so both gates
see the same state.

Three properties are locked here:
  1. the working-tree loader DOES see a dirty (uncommitted) entry — CI-checkout
     semantics, where committed == working tree, stay unchanged
  2. the ref loader sees ONLY committed entries — a dirty entry cannot satisfy it
  3. an unreadable ref fails closed (None), which audit_experiment already turns
     into a blocking violation
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_experiment_artifacts.py"

_spec = importlib.util.spec_from_file_location("check_experiment_artifacts", SCRIPT)
cea = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(cea)


def _hermetic_env(home: Path) -> dict[str, str]:
    """Git environment isolated from the user's config, hooks, and identity."""
    env = {**os.environ}
    env.update({
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "gate-test",
        "GIT_AUTHOR_EMAIL": "gate-test@example.invalid",
        "GIT_COMMITTER_NAME": "gate-test",
        "GIT_COMMITTER_EMAIL": "gate-test@example.invalid",
    })
    return env


def _git(cwd: Path, env: dict[str, str], *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(cwd), env=env,
        check=True, capture_output=True, text=True, timeout=30,
    )


@pytest.fixture()
def split_brain_repo(tmp_path: Path) -> Path:
    """A repo where k9001 is committed and k9002 exists only in the working tree."""
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _hermetic_env(home)
    _git(repo, env, "init", "--initial-branch=main")

    knowledge = repo / cea.KNOWLEDGE_REL
    knowledge.parent.mkdir(parents=True)
    knowledge.write_text(json.dumps(
        [{"item_id": "aaaa0001", "content": "[k9001] committed finding"}],
        ensure_ascii=False,
    ), encoding="utf-8")
    _git(repo, env, "add", str(cea.KNOWLEDGE_REL))
    _git(repo, env, "commit", "-m", "knowledge: k9001")

    knowledge.write_text(json.dumps(
        [
            {"item_id": "aaaa0001", "content": "[k9001] committed finding"},
            {"item_id": "aaaa0002", "content": "[k9002] entry written but never committed"},
        ],
        ensure_ascii=False,
    ), encoding="utf-8")
    return repo


def test_worktree_loader_sees_dirty_entry(split_brain_repo: Path) -> None:
    ids = cea.load_knowledge_ids(root=split_brain_repo)
    assert ids is not None
    assert {"k9001", "k9002"} <= ids


def test_ref_loader_sees_only_committed_entries(split_brain_repo: Path) -> None:
    ids = cea.load_knowledge_ids_at_ref("HEAD", root=split_brain_repo)
    assert ids is not None
    assert "k9001" in ids
    assert "k9002" not in ids, (
        "ref mode returned an uncommitted entry — the merge gate would again pass "
        "a state CI is about to reject (the 2026-08-04 k1735 failure mode)"
    )


def test_ref_loader_unreadable_ref_fails_closed(split_brain_repo: Path) -> None:
    assert cea.load_knowledge_ids_at_ref("refs/no/such/ref", root=split_brain_repo) is None


def test_check_cli_accepts_knowledge_ref_flag() -> None:
    """The flag exists end to end — merge_worktree.sh passes it unconditionally."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "check", "--help"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0
    assert "--knowledge-ref" in proc.stdout


def test_merge_gate_call_site_passes_head() -> None:
    """merge_worktree.sh must keep evaluating the committed state, not the dirty tree."""
    merge_script = (REPO_ROOT / "scripts" / "merge_worktree.sh").read_text(encoding="utf-8")
    assert "check --knowledge-ref HEAD" in merge_script
