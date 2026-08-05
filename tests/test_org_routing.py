"""Hermetic tests for the dept routing projection (scripts/org/dept_routing.py).

All tests operate on tmp_path — never on canonical storage/org
(project_canonical_write_test_leak_gate). The projection must stay a live
join of registry.json × model_router.TASK_TYPE_TO_MODEL — no stored snapshot.
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
sys.path.insert(0, str(REPO / "scripts"))
import org_status  # noqa: E402
from dept_routing import resolve_dept_routing  # noqa: E402
from model_router import TASK_TYPE_TO_MODEL, DEFAULT  # noqa: E402


def run_tool(tool: str, *args: str, root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ORG_SCRIPTS / tool), "--root", str(root), *args],
        capture_output=True,
        text=True,
    )


def _registry(departments: dict) -> dict:
    return {"version": 1, "departments": departments}


def test_projection_matches_canonical_map() -> None:
    reg = _registry(
        {
            "research": {
                "status": "active",
                "title": "研究部",
                "owned_task_types": ["experiment", "lookup"],
            }
        }
    )
    proj = resolve_dept_routing(reg)
    rows = proj["departments"]["research"]["task_routing"]
    assert rows["experiment"]["model"] == TASK_TYPE_TO_MODEL["experiment"][0]
    assert rows["experiment"]["effort"] == TASK_TYPE_TO_MODEL["experiment"][1]
    assert rows["experiment"]["mapped"] is True
    assert rows["lookup"]["effort"] == TASK_TYPE_TO_MODEL["lookup"][1]


def test_unknown_task_type_flagged_not_absorbed() -> None:
    reg = _registry(
        {
            "content": {
                "status": "active",
                "title": "內容部",
                "owned_task_types": ["no_such_type"],
            }
        }
    )
    rows = resolve_dept_routing(reg)["departments"]["content"]["task_routing"]
    assert rows["no_such_type"]["mapped"] is False
    assert (rows["no_such_type"]["model"], rows["no_such_type"]["effort"]) == DEFAULT


def test_retired_dept_excluded_and_empty_dept_noted() -> None:
    reg = _registry(
        {
            "old": {"status": "retired", "owned_task_types": ["experiment"]},
            "resource_monitor": {
                "status": "active",
                "title": "資源監控部",
                "owned_task_types": [],
            },
        }
    )
    proj = resolve_dept_routing(reg)
    assert "old" not in proj["departments"]
    entry = proj["departments"]["resource_monitor"]
    assert entry["task_routing"] == {}
    assert "note" in entry


def test_org_status_collect_carries_routing(tmp_path: Path) -> None:
    root = tmp_path / "org"
    assert run_tool("org_admin.py", "init", root=root).returncode == 0
    assert (
        run_tool(
            "org_admin.py",
            "create",
            "research",
            "--title",
            "研究部",
            "--task-types",
            "experiment,lookup",
            root=root,
        ).returncode
        == 0
    )
    snap = org_status.collect(root)
    routing = snap["departments"]["research"]["task_routing"]
    assert routing["experiment"]["model"] == TASK_TYPE_TO_MODEL["experiment"][0]
    assert routing["experiment"]["mapped"] is True


def test_cli_json_output(tmp_path: Path) -> None:
    root = tmp_path / "org"
    assert run_tool("org_admin.py", "init", root=root).returncode == 0
    assert (
        run_tool(
            "org_admin.py",
            "create",
            "governance",
            "--title",
            "治理部",
            "--task-types",
            "governance",
            root=root,
        ).returncode
        == 0
    )
    result = run_tool("dept_routing.py", "--json", root=root)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "sources" in payload
    row = payload["departments"]["governance"]["task_routing"]["governance"]
    assert (row["model"], row["effort"]) == TASK_TYPE_TO_MODEL["governance"]

    missing = run_tool("dept_routing.py", "--dept", "nope", root=root)
    assert missing.returncode == 1
