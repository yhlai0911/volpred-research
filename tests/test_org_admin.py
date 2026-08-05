"""Hermetic tests for the disk-persisted org layer (scripts/org/).

All tests operate on tmp_path — never on canonical storage/org
(project_canonical_write_test_leak_gate).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ORG_SCRIPTS = REPO / "scripts" / "org"

sys.path.insert(0, str(ORG_SCRIPTS))
import _core  # noqa: E402
from manager_tick import evaluate_gate  # noqa: E402


def run_tool(tool: str, *args: str, root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ORG_SCRIPTS / tool), "--root", str(root), *args],
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def org_root(tmp_path: Path) -> Path:
    root = tmp_path / "org"
    result = run_tool("org_admin.py", "init", root=root)
    assert result.returncode == 0, result.stderr
    return root


def test_init_creates_skeleton(org_root: Path) -> None:
    assert (org_root / "registry.json").exists()
    assert (org_root / "manager" / "charter.md").exists()
    assert (org_root / "manager" / "inbox" / "_archive").is_dir()
    assert (org_root / "manager" / "outbox" / "proposals").is_dir()
    registry = json.loads((org_root / "registry.json").read_text())
    assert registry["version"] == _core.REGISTRY_VERSION
    assert registry["departments"] == {}


def test_create_retire_roundtrip(org_root: Path) -> None:
    result = run_tool(
        "org_admin.py", "create", "testdept", "--title", "測試部",
        "--task-types", "experiment", "--paths", "experiments/", root=org_root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    ddir = org_root / "departments" / "testdept"
    assert (ddir / "charter.md").exists()
    assert (ddir / "journal.md").exists()
    assert (ddir / "inbox" / "_archive").is_dir()
    charter = (ddir / "charter.md").read_text()
    assert "{name}" not in charter  # template fully rendered
    assert "testdept" in charter

    registry = json.loads((org_root / "registry.json").read_text())
    assert registry["departments"]["testdept"]["status"] == "active"
    assert registry["departments"]["testdept"]["owned_task_types"] == ["experiment"]

    result = run_tool("org_admin.py", "retire", "testdept", "--reason", "test", root=org_root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not ddir.exists()
    assert (org_root / "departments" / "_retired" / "testdept" / "charter.md").exists()
    registry = json.loads((org_root / "registry.json").read_text())
    assert registry["departments"]["testdept"]["status"] == "retired"

    bulletins = list((org_root / "bulletin").glob("*.md"))
    assert bulletins, "structural changes must be recorded in the bulletin"
    text = bulletins[0].read_text()
    assert "department created: testdept" in text
    assert "department retired: testdept" in text


def test_create_rejects_reserved_path(org_root: Path) -> None:
    result = run_tool(
        "org_admin.py", "create", "sneaky", "--paths", "src/volpred/ops/", root=org_root,
    )
    assert result.returncode == 1
    assert "reserved zone" in result.stdout
    assert not (org_root / "departments" / "sneaky").exists()


def test_create_rejects_path_and_type_overlap(org_root: Path) -> None:
    assert run_tool(
        "org_admin.py", "create", "first", "--paths", "storage/foo/",
        "--task-types", "experiment", root=org_root,
    ).returncode == 0
    overlap_path = run_tool(
        "org_admin.py", "create", "second", "--paths", "storage/foo/bar/", root=org_root,
    )
    assert overlap_path.returncode == 1
    assert "owned by first" in overlap_path.stdout
    overlap_type = run_tool(
        "org_admin.py", "create", "third", "--task-types", "experiment", root=org_root,
    )
    assert overlap_type.returncode == 1
    assert "owned by first" in overlap_type.stdout


def test_dept_send_and_gate(org_root: Path) -> None:
    assert run_tool("org_admin.py", "create", "alpha", root=org_root).returncode == 0

    gate = evaluate_gate(org_root)
    assert gate["fire"] is False, gate

    result = run_tool(
        "dept_send.py", "alpha", "--from", "manager", "--priority", "P2",
        "--task", "do the thing", root=org_root,
    )
    assert result.returncode == 0, result.stderr
    item_path = Path(result.stdout.strip())
    assert item_path.exists()
    item = json.loads(item_path.read_text())
    assert item["to"] == "alpha" and item["priority"] == "P2"

    gate = evaluate_gate(org_root)
    assert gate["fire"] is True
    assert any("alpha" in r for r in gate["reasons"])


def test_dept_send_refuses_inactive(org_root: Path) -> None:
    assert run_tool("org_admin.py", "create", "beta", root=org_root).returncode == 0
    assert run_tool("org_admin.py", "suspend", "beta", root=org_root).returncode == 0
    result = run_tool(
        "dept_send.py", "beta", "--from", "manager", "--task", "x", root=org_root,
    )
    assert result.returncode == 1
    gate = evaluate_gate(org_root)
    assert gate["fire"] is False, "suspended dept must not trigger the gate"


def test_boss_intake_triggers_gate(org_root: Path) -> None:
    result = run_tool("org_intake.py", "--boss-message", "急件", root=org_root)
    assert result.returncode == 0, result.stderr
    gate = evaluate_gate(org_root)
    assert gate["fire"] is True
    assert any("manager inbox" in r for r in gate["reasons"])


def test_future_due_item_does_not_fire(org_root: Path) -> None:
    assert run_tool("org_admin.py", "create", "gamma", root=org_root).returncode == 0
    result = run_tool(
        "dept_send.py", "gamma", "--from", "manager", "--task", "later",
        "--due", "2099-01-01T00:00:00Z", root=org_root,
    )
    assert result.returncode == 0, result.stderr
    gate = evaluate_gate(org_root)
    assert gate["fire"] is False, gate


def test_every_brief_carries_the_org_policy(org_root: Path) -> None:
    """The decision chain lives in one file, not copied into seven charters."""
    assert run_tool("org_admin.py", "create", "alpha", root=org_root).returncode == 0
    (org_root / "policy.md").write_text("# 通則\n- 部門遇決策問經理\n", encoding="utf-8")

    dept = _core.build_brief(org_root, "alpha")
    manager = _core.build_manager_brief(org_root)

    assert "部門遇決策問經理" in dept
    assert "部門遇決策問經理" in manager


def test_missing_policy_is_reported_not_hidden(org_root: Path) -> None:
    assert run_tool("org_admin.py", "create", "alpha", root=org_root).returncode == 0

    brief = _core.build_brief(org_root, "alpha")

    assert "policy.md 不存在" in brief, "a missing standing-rules file must be visible, not silent"
