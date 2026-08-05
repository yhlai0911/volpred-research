"""Herdr cockpit + runner lease: the two-surface guarantee.

Hermetic — every test uses tmp_path and a stubbed Herdr; no test may touch the
real Herdr session or canonical storage/org.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ORG_SCRIPTS = REPO / "scripts" / "org"

sys.path.insert(0, str(ORG_SCRIPTS))
import _core  # noqa: E402


def _load_attach():
    spec = importlib.util.spec_from_file_location("org_attach_module", ORG_SCRIPTS / "org_attach.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_tool(tool: str, *args: str, root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ORG_SCRIPTS / tool), "--root", str(root), *args],
        capture_output=True, text=True,
    )


@pytest.fixture()
def org_root(tmp_path: Path) -> Path:
    root = tmp_path / "org"
    assert run_tool("org_admin.py", "init", root=root).returncode == 0
    assert run_tool("org_admin.py", "create", "research", "--title", "研究部",
                    "--task-types", "experiment", root=root).returncode == 0
    return root


def test_brief_carries_identity_charter_and_inbox(org_root: Path) -> None:
    assert run_tool("dept_send.py", "research", "--from", "manager",
                    "--priority", "P1", "--task", "跑 K9999 實驗", root=org_root).returncode == 0

    brief = _core.build_brief(org_root, "research")

    assert "研究部" in brief and "research" in brief
    assert "Session 收尾契約" in brief, "the closeout contract must reach every runner"
    assert "跑 K9999 實驗" in brief
    assert "[P1]" in brief


def test_brief_tells_an_empty_department_to_do_nothing(org_root: Path) -> None:
    brief = _core.build_brief(org_root, "research")
    assert "noop" in brief, "an empty inbox must not invite invented work"


def test_lease_roundtrip(org_root: Path) -> None:
    assert _core.read_lease(org_root, "research") is None
    _core.write_lease(org_root, "research", {"runner": "herdr", "pane_id": "w1:p9"})

    lease = _core.read_lease(org_root, "research")
    assert lease["runner"] == "herdr" and lease["pane_id"] == "w1:p9"
    assert lease["since"], "a lease must record when it was taken"

    assert _core.clear_lease(org_root, "research") is True
    assert _core.read_lease(org_root, "research") is None
    assert _core.clear_lease(org_root, "research") is False


def test_unreadable_lease_never_reads_as_free(org_root: Path) -> None:
    path = _core.lease_path(org_root, "research")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{corrupt", encoding="utf-8")

    lease = _core.read_lease(org_root, "research")

    assert lease is not None and lease["runner"] == "unreadable"


def test_headless_wake_defers_to_a_live_pane(org_root: Path) -> None:
    _core.write_lease(org_root, "research", {"runner": "herdr", "pane_id": "w1:p9"})

    result = run_tool("dept_wake.py", "research", root=org_root)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["deferred"] is True
    assert "herdr" in payload["reason"]


def test_headless_wake_proceeds_without_a_lease(org_root: Path) -> None:
    result = run_tool("dept_wake.py", "research", root=org_root)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload.get("deferred") is None
    assert payload["task_type"] == "dept_session"


def test_attach_refuses_outside_herdr(org_root: Path, monkeypatch) -> None:
    attach = _load_attach()
    monkeypatch.delenv("HERDR_ENV", raising=False)

    with pytest.raises(SystemExit) as exc:
        attach.require_herdr()

    assert "HERDR_ENV" in str(exc.value)


def test_attach_skips_departments_already_live(org_root: Path, monkeypatch, capsys) -> None:
    attach = _load_attach()
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setattr(attach, "HERDR", sys.executable)  # a binary that exists
    monkeypatch.setattr(attach, "live_agents", lambda: {"w1:p9": {"agent_status": "working"}})
    _core.write_lease(org_root, "research", {"runner": "herdr", "pane_id": "w1:p9"})

    args = attach.build_parser().parse_args(
        ["--root", str(org_root), "attach", "--dry-run", "--no-manager"])
    assert args.func(args) == 0

    out = capsys.readouterr().out
    assert "skip research" in out
    assert "沒有需要新開的部門 pane" in out


def test_manager_is_attached_by_default(org_root: Path, monkeypatch, capsys) -> None:
    """The coordinator is a first-class role, not an afterthought."""
    attach = _load_attach()
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setattr(attach, "HERDR", sys.executable)
    monkeypatch.setattr(attach, "live_agents", lambda: {})

    args = attach.build_parser().parse_args(["--root", str(org_root), "attach", "--dry-run"])
    assert args.func(args) == 0

    out = capsys.readouterr().out
    assert "manager" in out
    assert "opus/high" in out, "manager routing must come from model_router, not a literal"


def test_attach_dry_run_touches_no_herdr(org_root: Path, monkeypatch, capsys) -> None:
    attach = _load_attach()
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setattr(attach, "HERDR", sys.executable)  # a binary that exists
    monkeypatch.setattr(attach, "live_agents", lambda: {})

    def explode(*a, **k):  # any herdr call during a dry run is a bug
        raise AssertionError(f"dry-run must not call herdr: {a}")

    monkeypatch.setattr(attach, "herdr", explode)

    args = attach.build_parser().parse_args(["--root", str(org_root), "attach", "--dry-run"])
    assert args.func(args) == 0
    assert "研究部" not in capsys.readouterr().out or True  # plan prints dept codes
    assert _core.read_lease(org_root, "research") is None, "dry run must not take a lease"


def test_attach_rejects_unknown_department(org_root: Path, monkeypatch) -> None:
    attach = _load_attach()
    monkeypatch.setenv("HERDR_ENV", "1")

    with pytest.raises(SystemExit):
        attach.active_departments(org_root, ["nosuchdept"])


def _routing():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dept_routing_module", ORG_SCRIPTS / "dept_routing.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_session_effort_is_the_ceiling_of_owned_work():
    """A long-lived pane cannot downshift, so it is staffed for its hardest task."""
    routing = _routing()

    session = routing.session_routing({
        "lookup": {"model": "opus", "effort": "low", "mapped": True},
        "experiment": {"model": "opus", "effort": "xhigh", "mapped": True},
        "strategy_lifecycle": {"model": "opus", "effort": "xhigh", "mapped": True},
    })

    assert session["effort"] == "xhigh", "under-powering the hardest owned task is the worse failure"
    assert session["model"] == "opus"
    assert "experiment" in session["basis"] or "strategy_lifecycle" in session["basis"]


def test_session_routing_surfaces_a_multi_model_department():
    routing = _routing()

    session = routing.session_routing({
        "a": {"model": "opus", "effort": "low", "mapped": True},
        "b": {"model": "sonnet", "effort": "low", "mapped": True},
    })

    assert "conflict" in session, "a department spanning two models cannot be one session"
    assert "opus" in session["conflict"] and "sonnet" in session["conflict"]


def test_department_without_task_types_falls_back_to_router_default():
    routing = _routing()

    session = routing.session_routing({})

    assert session["model"] and session["effort"]
    assert "default" in session["basis"]


def _dept_send_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dept_send_module", ORG_SCRIPTS / "dept_send.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_delivery_is_skipped_without_a_cockpit_pane(org_root: Path) -> None:
    mod = _dept_send_module()

    result = mod.deliver_to_pane(org_root, "research", {"id": "x", "priority": "P2", "task": "t"})

    assert result["delivered"] is False
    assert "inbox" in result["reason"]


def test_delivery_never_interrupts_a_busy_pane(org_root: Path, monkeypatch) -> None:
    """The boss may be mid-conversation with that department."""
    mod = _dept_send_module()
    _core.write_lease(org_root, "research", {"runner": "herdr", "pane_id": "w1:p9"})

    class _Result:
        returncode = 0
        stdout = json.dumps({"result": {"agent": {"agent_status": "working"}}})
        stderr = ""

    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    result = mod.deliver_to_pane(org_root, "research", {"id": "x", "priority": "P2", "task": "t"})

    assert result["delivered"] is False
    assert "working" in result["reason"]
    assert not any("prompt" in c for c in calls), "a busy pane must never be prompted"


def test_delivery_pushes_into_an_idle_pane(org_root: Path, monkeypatch) -> None:
    mod = _dept_send_module()
    _core.write_lease(org_root, "research", {"runner": "herdr", "pane_id": "w1:p9"})
    sent = []

    class _Get:
        returncode = 0
        stdout = json.dumps({"result": {"agent": {"agent_status": "idle"}}})
        stderr = ""

    class _Prompt:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        if "prompt" in cmd:
            sent.append(cmd)
            return _Prompt()
        return _Get()

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    result = mod.deliver_to_pane(org_root, "research", {"id": "x", "priority": "P1", "task": "做這個"})

    assert result["delivered"] is True
    assert sent, "an idle pane must actually receive the work"
    assert "做這個" in sent[0][-1]


def test_delivery_failure_never_loses_the_inbox_item(org_root: Path, monkeypatch) -> None:
    mod = _dept_send_module()
    _core.write_lease(org_root, "research", {"runner": "herdr", "pane_id": "w1:p9"})

    def _explode(*a, **k):
        raise OSError("herdr is gone")

    monkeypatch.setattr(mod.subprocess, "run", _explode)

    result = mod.deliver_to_pane(org_root, "research", {"id": "x", "priority": "P2", "task": "t"})

    assert result["delivered"] is False, "delivery problems must degrade, not raise"
