from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from scripts import fire_receipt
from volpred.ops import fire_manifest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "scripts" / "hooks" / "record_fire_manifest.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "seed.txt")
    _git(root, "commit", "-qm", "seed")
    return root


def _load_hook():
    spec = importlib.util.spec_from_file_location("record_fire_manifest", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_posttool_hook_records_written_path(repo: Path) -> None:
    fire_manifest.open_manifest(repo, fire_id="job-1", actor="slot-1")
    target = repo / "new.py"
    target.write_text("x = 1\n", encoding="utf-8")
    hook = _load_hook()

    assert hook.record_payload(
        {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
        env={"VOLPRED_FIRE_ID": "job-1", "VOLPRED_FIRE_REPO_ROOT": str(repo)},
    )
    entry = fire_manifest.read(repo, "job-1")["entries"][0]
    assert entry["path"] == "new.py"
    assert entry["tool"] == "Write"


def test_hook_without_fire_identity_is_a_noop(repo: Path) -> None:
    target = repo / "new.py"
    target.write_text("x = 1\n", encoding="utf-8")
    assert _load_hook().record_payload(
        {"tool_name": "Write", "tool_input": {"file_path": str(target)}}, env={}
    ) is False


def test_project_settings_register_manifest_posttool_hook() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    registrations = [
        hook
        for group in settings["hooks"]["PostToolUse"]
        if group.get("matcher") == "Edit|Write|MultiEdit|NotebookEdit"
        for hook in group.get("hooks", [])
    ]
    assert any("record_fire_manifest.py" in hook.get("command", "") for hook in registrations)


def test_fire_receipt_seals_the_declared_change_set(repo: Path, monkeypatch) -> None:
    fire_manifest.open_manifest(repo, fire_id="job-1", actor="slot-1")
    target = repo / "new.py"
    target.write_text("x = 1\n", encoding="utf-8")
    fire_manifest.record(repo, "job-1", "new.py")
    monkeypatch.setenv("VOLPRED_FIRE_ID", "job-1")

    rc = fire_receipt.main([
        "--repo-root", str(repo),
        "--subject", "declare output | regression test",
    ])

    assert rc == 0
    manifest = fire_manifest.read(repo, "job-1")
    assert manifest["state"] == fire_manifest.STATE_SEALED
    assert manifest["seal"]["paths"][0]["path"] == "new.py"
