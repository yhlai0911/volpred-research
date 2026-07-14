"""Hermetic tests for reaper paper-build-artifact recognition (2026-07-14).

Regression for the PHASE-Z streak alert class: reproduce.py verification
dirties tracked paper artifacts (volatile results fields + rebuilt PDF) that
explicit-path session commits necessarily miss. Uses a throwaway git repo
(per feedback_hermetic_git_in_tests) — never touches the real repository.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import reap_orphan_deliverables as reap  # noqa: E402


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"PATH": "/usr/bin:/bin:/usr/local/bin",
                        "HOME": str(cwd),
                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture()
def fake_repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init", "-q")
    # Identity belongs to the throwaway repo, not to _git()'s env: the code under
    # test shells out to `git commit` with the ambient environment, which on a CI
    # runner carries no user.name/user.email. Without this the production commit
    # dies with "Author identity unknown" and the test only passes on a laptop
    # that happens to have a global gitconfig.
    _git(tmp_path, "config", "user.email", "reaper-test@example.invalid")
    _git(tmp_path, "config", "user.name", "Reaper Test")
    d = tmp_path / "paper" / "demo"
    (d / "experiments").mkdir(parents=True)
    (d / "main.tex").write_text("\\documentclass{article}")
    (d / "main.pdf").write_bytes(b"%PDF-old")
    (d / "experiments" / "k1_results.json").write_text(json.dumps(
        {"timestamp": "old", "runtime_seconds": 1.0, "sharpe": 0.51}))
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    monkeypatch.setattr(reap, "ROOT", tmp_path)
    monkeypatch.setattr(reap, "GRACE_SECONDS", 0)
    return tmp_path


def test_volatile_only_results_and_clean_pdf_collectable(fake_repo: Path) -> None:
    d = fake_repo / "paper" / "demo"
    (d / "experiments" / "k1_results.json").write_text(json.dumps(
        {"timestamp": "new", "runtime_seconds": 2.0, "sharpe": 0.51}))
    (d / "main.pdf").write_bytes(b"%PDF-rebuilt")
    scan = reap.scan_paper_build_artifacts()
    kinds = {e["path"]: e for e in scan["collectable"]}
    assert "paper/demo/experiments/k1_results.json" in kinds
    assert "paper/demo/main.pdf" in kinds
    assert scan["held"] == []
    out = reap.collect_paper_artifacts(scan["collectable"])
    assert out and out[0]["committed"] is True
    status = subprocess.run(["git", "status", "--porcelain"], cwd=fake_repo,
                            capture_output=True, text=True)
    assert status.stdout.strip() == ""


def test_real_result_change_is_held(fake_repo: Path) -> None:
    d = fake_repo / "paper" / "demo"
    (d / "experiments" / "k1_results.json").write_text(json.dumps(
        {"timestamp": "new", "runtime_seconds": 2.0, "sharpe": 0.99}))  # 數字變了
    scan = reap.scan_paper_build_artifacts()
    held = {e["path"]: e["reason"] for e in scan["held"]}
    assert held.get("paper/demo/experiments/k1_results.json") == "content_changed"
    assert not any(e["path"].endswith("k1_results.json") for e in scan["collectable"])


def test_pdf_with_dirty_tex_is_held(fake_repo: Path) -> None:
    d = fake_repo / "paper" / "demo"
    (d / "main.tex").write_text("\\documentclass{article} % edited")
    (d / "main.pdf").write_bytes(b"%PDF-rebuilt")
    scan = reap.scan_paper_build_artifacts()
    held = [e for e in scan["held"] if e["path"] == "paper/demo/main.pdf"]
    assert held and held[0]["reason"].startswith("sources_dirty")
    assert not any(e["path"].endswith(".pdf") for e in scan["collectable"])
