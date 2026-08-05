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
def quiet_platform():
    """Neutralise facts from outside the org.

    Tests about inbox/cadence semantics must not depend on the live platform
    queue or on how long ago the manager last patrolled.
    """
    from datetime import datetime, timezone

    def _mark(root: Path) -> None:
        (root / "manager" / "state.json").write_text(json.dumps({
            "last_patrol": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }), encoding="utf-8")

    return _mark


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


def test_dept_send_and_gate(org_root: Path, quiet_platform) -> None:
    quiet_platform(org_root)
    assert run_tool("org_admin.py", "create", "alpha", root=org_root).returncode == 0

    gate = evaluate_gate(org_root, platform_facts=lambda: [])
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

    gate = evaluate_gate(org_root, platform_facts=lambda: [])
    assert gate["fire"] is True
    assert any("alpha" in r for r in gate["reasons"])


def test_dept_send_refuses_inactive(org_root: Path, quiet_platform) -> None:
    quiet_platform(org_root)
    assert run_tool("org_admin.py", "create", "beta", root=org_root).returncode == 0
    assert run_tool("org_admin.py", "suspend", "beta", root=org_root).returncode == 0
    result = run_tool(
        "dept_send.py", "beta", "--from", "manager", "--task", "x", root=org_root,
    )
    assert result.returncode == 1
    gate = evaluate_gate(org_root, platform_facts=lambda: [])
    assert gate["fire"] is False, "suspended dept must not trigger the gate"


def test_boss_intake_triggers_gate(org_root: Path, quiet_platform) -> None:
    quiet_platform(org_root)
    result = run_tool("org_intake.py", "--boss-message", "急件", root=org_root)
    assert result.returncode == 0, result.stderr
    gate = evaluate_gate(org_root, platform_facts=lambda: [])
    assert gate["fire"] is True
    assert any("manager inbox" in r for r in gate["reasons"])


def test_future_due_item_does_not_fire(org_root: Path, quiet_platform) -> None:
    quiet_platform(org_root)
    assert run_tool("org_admin.py", "create", "gamma", root=org_root).returncode == 0
    result = run_tool(
        "dept_send.py", "gamma", "--from", "manager", "--task", "later",
        "--due", "2099-01-01T00:00:00Z", root=org_root,
    )
    assert result.returncode == 0, result.stderr
    gate = evaluate_gate(org_root, platform_facts=lambda: [])
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


def test_declared_cadence_actually_wakes_a_department(org_root: Path, quiet_platform) -> None:
    quiet_platform(org_root)
    """A cadence the gate never reads is a decoration, not a schedule."""
    assert run_tool("org_admin.py", "create", "infra", "--min-cadence", "daily",
                    root=org_root).returncode == 0

    gate = evaluate_gate(org_root, platform_facts=lambda: [])

    assert gate["fire"] is True
    assert any("never run" in r and "infra" in r for r in gate["reasons"])


def test_cadence_is_satisfied_by_a_recent_run(org_root: Path, quiet_platform) -> None:
    quiet_platform(org_root)
    from datetime import datetime, timezone
    assert run_tool("org_admin.py", "create", "infra", "--min-cadence", "daily",
                    root=org_root).returncode == 0
    state = org_root / "departments" / "infra" / "state.json"
    state.write_text(json.dumps({
        "last_run": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }), encoding="utf-8")

    gate = evaluate_gate(org_root, platform_facts=lambda: [])

    assert not any("infra" in r for r in gate["reasons"]), gate


def test_on_demand_department_is_not_woken_by_the_clock(org_root: Path, quiet_platform) -> None:
    quiet_platform(org_root)
    assert run_tool("org_admin.py", "create", "ondemand", root=org_root).returncode == 0

    gate = evaluate_gate(org_root, platform_facts=lambda: [])

    assert gate["fire"] is False, "an idle on-demand dept must not burn a wake"


def test_departments_are_told_they_have_no_schedule(org_root: Path) -> None:
    """A department that thinks it has a dispatch slot reports phantom next-runs.

    Observed 2026-08-05: the research pane printed "⏭ 下次任務 … hourly-dispatch"
    because it read CLAUDE.md's orchestrator reporting protocol as its own.
    """
    assert run_tool("org_admin.py", "create", "alpha", root=org_root).returncode == 0
    import shutil
    shutil.copy(REPO / "storage" / "org" / "policy.md", org_root / "policy.md")

    identity = _core.identity_prompt(org_root, "alpha")

    assert "部門沒有自己的排程" in identity
    assert "hourly-dispatch" in identity, "the exact leaked instruction must be named"
    assert "回報對象是經理" in identity


def _tick():
    import importlib.util
    spec = importlib.util.spec_from_file_location("manager_tick_mod", ORG_SCRIPTS / "manager_tick.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_wake_refuses_to_stack_headless_rounds(org_root: Path) -> None:
    """A 30-minute tick must not pile coordinators on a slow round."""
    tick = _tick()
    _core.write_lease(org_root, "manager", {"runner": "headless"})

    result = tick.wake_manager(org_root, ["reason"])

    assert result["woken"] is False
    assert "already in flight" in result["reason"]


def test_wake_does_not_interrupt_a_busy_cockpit_manager(org_root: Path, monkeypatch) -> None:
    tick = _tick()
    _core.write_lease(org_root, "manager", {"runner": "herdr", "pane_id": "w1:p1"})
    import subprocess

    class _R:
        returncode = 0
        stdout = json.dumps({"result": {"agent": {"agent_status": "working"}}})
        stderr = ""

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: (calls.append(cmd), _R())[1])

    result = tick.wake_manager(org_root, ["reason"])

    assert result["woken"] is False and "不打斷" in result["reason"]
    assert not any("prompt" in c for c in calls)


def test_wake_prompts_an_idle_cockpit_manager(org_root: Path, monkeypatch) -> None:
    tick = _tick()
    _core.write_lease(org_root, "manager", {"runner": "herdr", "pane_id": "w1:p1"})
    import subprocess
    sent = []

    class _Get:
        returncode = 0
        stdout = json.dumps({"result": {"agent": {"agent_status": "idle"}}})
        stderr = ""

    class _Ok:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def _run(cmd, **k):
        if "prompt" in cmd:
            sent.append(cmd)
            return _Ok()
        return _Get()

    monkeypatch.setattr(subprocess, "run", _run)

    result = tick.wake_manager(org_root, ["manager inbox has 2 items"])

    assert result["woken"] is True and result["via"] == "cockpit"
    assert "manager inbox has 2 items" in sent[0][-1], "the wake must say why it woke"


def test_manager_brief_carries_the_platform_queue(org_root: Path, monkeypatch) -> None:
    """A coordinator blind to the canonical queue dispatches against a fiction."""
    import subprocess

    class _R:
        returncode = 0
        stdout = json.dumps({
            "backbone": {"heartbeat_age_min": 0.4, "current_job": None, "auth_blocked": False},
            "queue": {"pending": 98, "pending_by_priority": {"p1": 7, "p2": 56},
                      "blocked": 18, "in_flight": 1,
                      "top_pending": [{"id": "K1451", "p": 1, "type": "daily_article"}]},
            "content_pool": {}, "alerts": {"sent_last_24h": 0}, "git": {},
        })
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())

    brief = _core.build_manager_brief(org_root)

    assert "98" in brief and "P1=7" in brief
    assert "blocked 18" in brief
    assert "K1451" in brief


def test_manager_is_told_loudly_when_platform_state_is_unavailable(org_root: Path, monkeypatch) -> None:
    import subprocess

    def _explode(*a, **k):
        raise OSError("snapshot unavailable")

    monkeypatch.setattr(subprocess, "run", _explode)

    brief = _core.build_manager_brief(org_root)

    assert "無法取得平台全局狀態" in brief, "blindness must be visible, never silent"
    assert "不要當作沒事" in brief


def test_manager_owes_a_patrol_even_with_an_empty_org(org_root: Path, monkeypatch) -> None:
    """An empty inbox never meant an idle platform."""
    tick = _tick()
    import subprocess

    class _R:
        returncode = 0
        stdout = json.dumps({"queue": {}, "content_pool": {}, "alerts": {}})
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())

    gate = tick.evaluate_gate(org_root)

    assert gate["fire"] is True
    assert any("巡檢" in r for r in gate["reasons"])


def test_recent_patrol_stops_the_clock(org_root: Path, monkeypatch) -> None:
    from datetime import datetime, timezone
    tick = _tick()
    import subprocess

    class _R:
        returncode = 0
        stdout = json.dumps({"queue": {}, "content_pool": {}, "alerts": {}})
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    (org_root / "manager" / "state.json").write_text(json.dumps({
        "last_patrol": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }), encoding="utf-8")

    gate = tick.evaluate_gate(org_root)

    assert gate["fire"] is False, "a just-patrolled, quiet org must not burn a wake"


def test_platform_backlog_alone_wakes_the_manager(org_root: Path, monkeypatch) -> None:
    from datetime import datetime, timezone
    tick = _tick()
    import subprocess

    class _R:
        returncode = 0
        stdout = json.dumps({"queue": {"pending_by_priority": {"p1": 7}, "blocked": 18},
                             "content_pool": {"draft": 2}, "alerts": {}})
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    (org_root / "manager" / "state.json").write_text(json.dumps({
        "last_patrol": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }), encoding="utf-8")

    gate = tick.evaluate_gate(org_root)

    assert gate["fire"] is True
    assert any("P1 pending" in r for r in gate["reasons"])
    assert any("draft 池" in r for r in gate["reasons"])


def test_policy_tells_departments_to_use_the_org_channel_when_stuck(org_root: Path) -> None:
    """member_success diagnosed correctly, then asked the human instead of the org."""
    assert run_tool("org_admin.py", "create", "alpha", root=org_root).returncode == 0
    import shutil
    shutil.copy(REPO / "storage" / "org" / "policy.md", org_root / "policy.md")

    identity = _core.identity_prompt(org_root, "alpha")

    assert "不是問視窗前的人" in identity
    assert "--to-manager" in identity, "the blocked-report command must be in reach"
    assert "老闆不是你的上級介面" in identity


def test_handled_request_without_a_reply_is_surfaced(org_root: Path, quiet_platform) -> None:
    """Help that never comes back makes the boss the transport layer."""
    quiet_platform(org_root)
    for d in ("content", "research"):
        assert run_tool("org_admin.py", "create", d, root=org_root).returncode == 0
    assert run_tool("dept_send.py", "research", "--from", "content",
                    "--task", "請幫我確認數字", "--no-wake", root=org_root).returncode == 0

    inbox = _core.dept_dir(org_root, "research") / "inbox"
    item = next(inbox.glob("*.json"))
    archive = inbox / "_archive"
    archive.mkdir(exist_ok=True)
    item.replace(archive / item.name)

    gate = _tick().evaluate_gate(org_root, platform_facts=lambda: [])

    assert any("沒有回覆" in r for r in gate["reasons"]), gate


def test_a_replied_request_is_not_flagged(org_root: Path, quiet_platform) -> None:
    quiet_platform(org_root)
    for d in ("content", "research"):
        assert run_tool("org_admin.py", "create", d, root=org_root).returncode == 0
    assert run_tool("dept_send.py", "research", "--from", "content",
                    "--task", "請幫我確認數字", "--no-wake", root=org_root).returncode == 0
    inbox = _core.dept_dir(org_root, "research") / "inbox"
    item_path = next(inbox.glob("*.json"))
    rid = json.loads(item_path.read_text())["id"]
    assert run_tool("dept_send.py", "content", "--from", "research", "--reply-to", rid,
                    "--task", "結果：42", "--no-wake", root=org_root).returncode == 0
    archive = inbox / "_archive"
    archive.mkdir(exist_ok=True)
    item_path.replace(archive / item_path.name)

    gate = _tick().evaluate_gate(org_root, platform_facts=lambda: [])

    assert not any("沒有回覆" in r for r in gate["reasons"]), gate


def test_queue_dispatch_routes_by_declared_ownership(org_root: Path, tmp_path: Path, monkeypatch) -> None:
    """One queue, one dispatcher: departments receive pointers, not copies."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("queue_dispatch_mod", ORG_SCRIPTS / "queue_dispatch.py")
    qd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qd)

    assert run_tool("org_admin.py", "create", "research", "--task-types", "experiment",
                    root=org_root).returncode == 0
    assert run_tool("org_admin.py", "create", "content", "--task-types", "daily_article",
                    root=org_root).returncode == 0

    pool = tmp_path / "next_tasks.json"
    pool.write_text(json.dumps([
        {"id": "K1", "status": "pending", "task_type": "experiment", "priority": 1},
        {"id": "A1", "status": "pending", "task_type": "daily_article", "priority": 2},
        {"id": "X1", "status": "pending", "task_type": "mystery_type", "priority": 2},
        {"id": "D1", "status": "succeeded", "task_type": "experiment", "priority": 1},
    ]), encoding="utf-8")
    monkeypatch.setattr(qd, "NEXT_TASKS", pool)

    result = qd.plan(org_root)

    assert [t["id"] for t in result["by_dept"]["research"]] == ["K1"]
    assert [t["id"] for t in result["by_dept"]["content"]] == ["A1"]
    assert result["unmapped"] == {"mystery_type": 1}, "an unowned type must be surfaced, not dropped"
    assert "D1" not in json.dumps(result["by_dept"]), "terminal tasks must not be re-dispatched"


def test_queue_dispatch_is_idempotent(org_root: Path, tmp_path: Path, monkeypatch) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("queue_dispatch_mod2", ORG_SCRIPTS / "queue_dispatch.py")
    qd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qd)

    assert run_tool("org_admin.py", "create", "research", "--task-types", "experiment",
                    root=org_root).returncode == 0
    pool = tmp_path / "next_tasks.json"
    pool.write_text(json.dumps([{"id": "K1", "status": "pending",
                                 "task_type": "experiment", "priority": 1}]), encoding="utf-8")
    monkeypatch.setattr(qd, "NEXT_TASKS", pool)

    assert run_tool("dept_send.py", "research", "--from", "manager", "--task", "【canonical】K1",
                    "--canonical-task-id", "K1", "--no-wake", root=org_root).returncode == 0

    result = qd.plan(org_root)

    assert result["by_dept"] == {}, "a task already pointed at must not be dispatched twice"
    assert result["already_dispatched"] == 1


def test_work_items_carry_their_sender_and_a_reply_command(org_root: Path) -> None:
    """A department that must work out who asked will simply not answer."""
    for d in ("research", "content"):
        assert run_tool("org_admin.py", "create", d, root=org_root).returncode == 0
    assert run_tool("dept_send.py", "research", "--from", "content",
                    "--task", "請幫我確認數字", "--no-wake", root=org_root).returncode == 0

    work = _core.work_prompt(org_root, "research")

    assert "來自 content" in work
    assert "--reply-to" in work and "--from research" in work
    assert "dept_send.py content" in work, "the reply must be addressed to the asker"


def test_canonical_pointers_say_how_to_settle(org_root: Path) -> None:
    assert run_tool("org_admin.py", "create", "research", root=org_root).returncode == 0
    assert run_tool("dept_send.py", "research", "--from", "manager", "--task", "【canonical】K1",
                    "--canonical-task-id", "K1", "--no-wake", root=org_root).returncode == 0

    work = _core.work_prompt(org_root, "research")

    assert "task_pool_claim" in work, "settling only the org item would strand the canonical task"
    assert "K1" in work


def test_manager_knows_its_own_cadence(org_root: Path) -> None:
    brief = _core.build_manager_brief(org_root)

    assert "每 30 分鐘" in brief
    assert "你沒有自己的排程" in brief
    assert "下一次閘門評估時間" in brief, "the boss watches this pane and needs the next tick"


def test_idle_department_with_due_work_is_woken(org_root: Path, monkeypatch) -> None:
    """Depending on the coordinator to nudge turns one missed round into starvation."""
    tick = _tick()
    assert run_tool("org_admin.py", "create", "research", root=org_root).returncode == 0
    assert run_tool("dept_send.py", "research", "--from", "manager", "--task", "做這個",
                    "--no-wake", root=org_root).returncode == 0
    _core.write_lease(org_root, "research", {"runner": "herdr", "pane_id": "w1:p9"})
    import subprocess
    sent = []

    class _Get:
        returncode = 0
        stdout = json.dumps({"result": {"agent": {"agent_status": "idle"}}})
        stderr = ""

    class _Ok:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def _run(cmd, **k):
        if "prompt" in cmd:
            sent.append(cmd)
            return _Ok()
        return _Get()

    monkeypatch.setattr(subprocess, "run", _run)

    result = tick.wake_departments(org_root)

    assert result[0]["dept"] == "research" and result[0]["woken"] is True
    assert sent, "an idle department holding due work must actually be prompted"


def test_busy_department_is_not_interrupted_by_delivery(org_root: Path, monkeypatch) -> None:
    tick = _tick()
    assert run_tool("org_admin.py", "create", "research", root=org_root).returncode == 0
    assert run_tool("dept_send.py", "research", "--from", "manager", "--task", "做這個",
                    "--no-wake", root=org_root).returncode == 0
    _core.write_lease(org_root, "research", {"runner": "herdr", "pane_id": "w1:p9"})
    import subprocess

    class _R:
        returncode = 0
        stdout = json.dumps({"result": {"agent": {"agent_status": "working"}}})
        stderr = ""

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: (calls.append(cmd), _R())[1])

    result = tick.wake_departments(org_root)

    assert result[0]["woken"] is False and "不打斷" in result[0]["reason"]
    assert not any("prompt" in c for c in calls)


def test_department_with_an_empty_inbox_is_left_alone(org_root: Path) -> None:
    tick = _tick()
    assert run_tool("org_admin.py", "create", "research", root=org_root).returncode == 0
    _core.write_lease(org_root, "research", {"runner": "herdr", "pane_id": "w1:p9"})

    assert tick.wake_departments(org_root) == [], "no work means no wake, cockpit or not"


def test_unanswered_decision_request_is_flagged(org_root: Path, quiet_platform) -> None:
    """A ruling nobody was told about is the same as no ruling."""
    quiet_platform(org_root)
    assert run_tool("org_admin.py", "create", "research", root=org_root).returncode == 0
    assert run_tool("dept_send.py", "--to-manager", "--from", "research", "--kind", "decision",
                    "--priority", "P1", "--task", "需決策：A 還是 B", root=org_root).returncode == 0

    inbox = org_root / "manager" / "inbox"
    item = next(inbox.glob("*.json"))
    archive = inbox / "_archive"
    archive.mkdir(exist_ok=True)
    item.replace(archive / item.name)

    gate = _tick().evaluate_gate(org_root, platform_facts=lambda: [])

    assert any("經理" in r and "沒有回覆" in r for r in gate["reasons"]), gate


def test_plain_report_needs_no_reply(org_root: Path, quiet_platform) -> None:
    quiet_platform(org_root)
    assert run_tool("org_admin.py", "create", "research", root=org_root).returncode == 0
    assert run_tool("dept_send.py", "--to-manager", "--from", "research",
                    "--task", "本班完成 X", root=org_root).returncode == 0
    inbox = org_root / "manager" / "inbox"
    item = next(inbox.glob("*.json"))
    archive = inbox / "_archive"
    archive.mkdir(exist_ok=True)
    item.replace(archive / item.name)

    gate = _tick().evaluate_gate(org_root, platform_facts=lambda: [])

    assert not any("沒有回覆" in r for r in gate["reasons"]), "status reports are not questions"


def test_everyone_is_told_where_the_org_panorama_is(org_root: Path) -> None:
    """A department that cannot see the org guesses instead of looking."""
    assert run_tool("org_admin.py", "create", "alpha", root=org_root).returncode == 0
    import shutil
    shutil.copy(REPO / "storage" / "org" / "policy.md", org_root / "policy.md")

    dept = _core.identity_prompt(org_root, "alpha")
    manager = _core.build_manager_brief(org_root)

    for text in (dept, manager):
        assert "localhost:8787" in text
    assert "api/org" in dept, "agents must be pointed at the JSON, not the HTML"
    assert "不要當作沒有阻塞" in dept, "a dead dashboard must not read as an all-clear"


# --- intake: the boss's door ----------------------------------------------

@pytest.fixture()
def captured_wake(monkeypatch):
    """Record wake calls instead of spawning a coordinator."""
    import manager_tick

    calls: list[tuple] = []

    def _fake(root, reasons):
        calls.append((root, reasons))
        return {"woken": True, "via": "test"}

    monkeypatch.setattr(manager_tick, "wake_manager", _fake)
    return calls


def test_boss_message_wakes_the_manager_immediately(org_root: Path, captured_wake) -> None:
    """急件直達: the boss does not queue behind a 30-minute tick."""
    import org_intake

    result = org_intake.record_boss_message(org_root, "研究部先停，把 draft 池補起來",
                                            msg_id="1701", canonical_task_id="telegram-1701")

    assert result["created"] is True
    assert result["wake"]["woken"] is True, "the boss's instruction must not wait for the tick"
    assert len(captured_wake) == 1
    assert (org_root / "manager" / "inbox" / "boss_telegram_1701.json").exists()


def test_boss_item_names_the_reply_owner(org_root: Path, captured_wake) -> None:
    """Two handlers, one message: the split has to be stated, not assumed."""
    import org_intake

    org_intake.record_boss_message(org_root, "進度如何", msg_id="1702",
                                   canonical_task_id="telegram-1702")
    item = json.loads((org_root / "manager" / "inbox" / "boss_telegram_1702.json").read_text())

    assert "telegram-1702" in item["task"], "the coordinator must know which task owns the reply"
    assert "不歸你" in item["task"] and "claim" in item["task"], (
        "without an explicit split the coordinator answers the boss a second time"
    )
    assert item["priority"] == "P1" and item["from"] == "boss"


def test_boss_message_without_an_owner_puts_the_reply_on_the_manager(org_root, captured_wake):
    """A hand-filed instruction has no responder behind it — say so."""
    import org_intake

    org_intake.record_boss_message(org_root, "手動轉述的指令", msg_id="1703")
    item = json.loads((org_root / "manager" / "inbox" / "boss_telegram_1703.json").read_text())

    assert "回覆責任在你" in item["task"]


def test_replayed_boss_message_does_not_wake_twice(org_root: Path, captured_wake) -> None:
    """The daemon replays consumed updates after a restart; intake must not re-fire."""
    import org_intake

    first = org_intake.record_boss_message(org_root, "同一則", msg_id="1704")
    second = org_intake.record_boss_message(org_root, "同一則", msg_id="1704")

    assert first["created"] is True and second["created"] is False
    assert len(captured_wake) == 1, "a restart storm must not wake the coordinator once per message"


def test_archived_boss_message_does_not_come_back(org_root: Path, captured_wake) -> None:
    import org_intake

    org_intake.record_boss_message(org_root, "已處理", msg_id="1705")
    inbox = org_root / "manager" / "inbox"
    (inbox / "_archive").mkdir(exist_ok=True)
    (inbox / "boss_telegram_1705.json").rename(inbox / "_archive" / "boss_telegram_1705.json")

    again = org_intake.record_boss_message(org_root, "已處理", msg_id="1705")

    assert again["created"] is False, "an item already handled must not be re-raised"


def test_failed_wake_still_leaves_the_instruction_on_disk(org_root, monkeypatch, quiet_platform):
    """A broken wake costs latency, never the message."""
    import manager_tick
    import org_intake

    quiet_platform(org_root)
    monkeypatch.setattr(manager_tick, "wake_manager",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("herdr gone")))

    result = org_intake.record_boss_message(org_root, "急件", msg_id="1706")

    assert result["created"] is True
    assert result["wake"]["woken"] is False
    assert "下一班 tick 兜底" in result["wake"]["reason"], "a swallowed wake failure must be legible"
    gate = evaluate_gate(org_root, platform_facts=lambda: [])
    assert gate["fire"] is True, "the tick is the fallback — it must still see the item"


# --- intake: the issue tracker's door -------------------------------------

def _issue(number: int, title: str, *labels: str) -> dict:
    return {"number": number, "title": title,
            "labels": [{"name": lbl} for lbl in labels],
            "url": f"https://github.com/x/y/issues/{number}"}


@pytest.fixture()
def github_root(org_root: Path, tmp_path: Path, monkeypatch):
    """An org with departments, a private pool, and a stubbed tracker."""
    import org_intake

    assert run_tool("org_admin.py", "create", "governance", "--task-types", "governance",
                    root=org_root).returncode == 0
    assert run_tool("org_admin.py", "create", "content", "--task-types",
                    "daily_article,daily_digest", root=org_root).returncode == 0

    pool = tmp_path / "next_tasks.json"
    pool.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(org_intake, "NEXT_TASKS", pool)
    monkeypatch.setattr(org_intake, "_gh", lambda: "/bin/true")
    return org_root, pool


def test_single_owner_department_needs_no_prefix(github_root, monkeypatch) -> None:
    import org_intake
    root, _pool = github_root
    monkeypatch.setattr(org_intake, "_open_issues",
                        lambda gh: [_issue(7, "把 gate 盤點清楚", "dept:governance")])

    plan = org_intake.plan_github(root)

    assert [r["number"] for r in plan["routable"]] == [7]
    assert plan["routable"][0]["task_type"] == "governance"


def test_ambiguous_ownership_is_never_guessed(github_root, monkeypatch) -> None:
    """Picking one of a department's task_types for it mis-routes silently."""
    import org_intake
    root, _pool = github_root
    monkeypatch.setattr(org_intake, "_open_issues",
                        lambda gh: [_issue(8, "寫一篇東西", "dept:content")])

    plan = org_intake.plan_github(root)

    assert plan["routable"] == []
    assert plan["unroutable"][0]["number"] == 8
    assert "daily_article" in plan["unroutable"][0]["why_not"], "say what the options were"


def test_title_prefix_selects_the_task_type(github_root, monkeypatch) -> None:
    import org_intake
    root, _pool = github_root
    monkeypatch.setattr(org_intake, "_open_issues",
                        lambda gh: [_issue(9, "[daily_digest] 本週導讀", "dept:content")])

    plan = org_intake.plan_github(root)

    assert plan["routable"][0]["task_type"] == "daily_digest"


def test_prefix_that_the_department_does_not_own_is_refused(github_root, monkeypatch) -> None:
    import org_intake
    root, _pool = github_root
    monkeypatch.setattr(org_intake, "_open_issues",
                        lambda gh: [_issue(10, "[experiment] 跑個實驗", "dept:content")])

    plan = org_intake.plan_github(root)

    assert plan["routable"] == []
    assert "不擁有" in plan["unroutable"][0]["why_not"]


def test_unlabelled_issues_stay_in_the_planning_layer(github_root, monkeypatch) -> None:
    """GitHub is the planning layer; only an explicit dept:* label opts in."""
    import org_intake
    root, _pool = github_root
    monkeypatch.setattr(org_intake, "_open_issues",
                        lambda gh: [_issue(11, "[Plan T40] 大計劃", "ready-for-agent")])

    plan = org_intake.plan_github(root)

    assert plan["routable"] == [] and plan["unroutable"] == []
    assert plan["unlabelled"] == 1


def test_priority_label_is_honoured(github_root, monkeypatch) -> None:
    import org_intake
    root, _pool = github_root
    monkeypatch.setattr(org_intake, "_open_issues",
                        lambda gh: [_issue(12, "急", "dept:governance", "P1")])

    assert org_intake.plan_github(root)["routable"][0]["priority"] == 1


def test_mirroring_creates_one_canonical_task(github_root, monkeypatch) -> None:
    """入池 means the canonical queue — not a second pool in a department inbox."""
    import org_intake
    root, pool = github_root
    monkeypatch.setattr(org_intake, "_open_issues",
                        lambda gh: [_issue(13, "盤點 gate", "dept:governance")])
    monkeypatch.setattr(org_intake.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""))

    result = org_intake.mirror_github(root, apply=True)

    tasks = json.loads(pool.read_text())
    assert [t["id"] for t in tasks] == ["gh-13"]
    assert tasks[0]["issue_ref"] == "#13" and tasks[0]["task_type"] == "governance"
    assert tasks[0]["status"] == "pending"
    assert result["applied"][0]["comment"] == "ok"
    assert "不等於可以關 issue" in tasks[0]["description"], (
        "task completion is not issue closure (docs/agents/issue-tracker.md)"
    )


def test_a_finished_slice_does_not_requeue_its_open_issue(github_root, monkeypatch) -> None:
    """`contained` is the default disposition: the issue stays open on purpose."""
    import org_intake
    root, pool = github_root
    pool.write_text(json.dumps([{"id": "gh-14", "status": "succeeded",
                                 "task_type": "governance", "priority": 2,
                                 "issue_ref": "#14"}]), encoding="utf-8")
    monkeypatch.setattr(org_intake, "_open_issues",
                        lambda gh: [_issue(14, "長跑 issue", "dept:governance")])

    plan = org_intake.plan_github(root)

    assert plan["routable"] == []
    assert plan["mirrored"] == [{"number": 14, "task_id": "gh-14"}]


def test_unroutable_issue_becomes_one_self_terminating_ruling_request(github_root, monkeypatch):
    """A gate that fires forever on an unfixable fact trains everyone to ignore it."""
    import org_intake
    root, _pool = github_root
    monkeypatch.setattr(org_intake, "_open_issues",
                        lambda gh: [_issue(15, "含糊的工作", "dept:content")])

    org_intake.mirror_github(root, apply=True)
    org_intake.mirror_github(root, apply=True)

    items = list((root / "manager" / "inbox").glob("gh_unroutable_*.json"))
    assert len(items) == 1, "the same unroutable issue must not re-file every round"
    item = json.loads(items[0].read_text())
    assert item["kind"] == "decision" and item["issue"] == 15


def test_gate_reports_only_work_the_org_has_not_absorbed(github_root, monkeypatch) -> None:
    """An open issue whose task exists is not a reason to wake anyone."""
    import org_intake
    root, pool = github_root
    pool.write_text(json.dumps([{"id": "gh-16", "status": "pending",
                                 "task_type": "governance", "priority": 2,
                                 "issue_ref": "#16"}]), encoding="utf-8")
    monkeypatch.setattr(org_intake, "_open_issues",
                        lambda gh: [_issue(16, "已入池", "dept:governance"),
                                    _issue(17, "還沒入池", "dept:governance")])

    reasons = org_intake.unmirrored_github_issues(root)

    assert len(reasons) == 1 and "#17" in reasons[0] and "#16" not in reasons[0]


def test_unreachable_tracker_is_a_no_signal_not_a_crash(github_root, monkeypatch) -> None:
    import org_intake
    root, _pool = github_root
    monkeypatch.setattr(org_intake, "_gh", lambda: None)

    reasons = org_intake.unmirrored_github_issues(root)

    assert len(reasons) == 1 and "unavailable" in reasons[0]
    gate = evaluate_gate(root, check_github=True, platform_facts=lambda: [])
    assert isinstance(gate["reasons"], list), "a missing gh must never break the gate"


def test_intake_source_is_registered_for_the_canonical_queue() -> None:
    """The tmp-pool tests above cannot catch this, and that is the point.

    Provenance is enforced only when the write targets the canonical queue, so
    every test that writes to a tmp pool passes while production fails closed —
    which is exactly what happened on 2026-08-05: the mirror was green in tests
    and raised `_LegacyMappingError` on its first real run. Assert the
    registration directly, reading the source from the code so the two cannot
    drift apart.
    """
    import org_intake
    from volpred.ops.work.legacy import classify_next_task_source

    _label, ingress, _evidence = classify_next_task_source(org_intake.INTAKE_SOURCE)

    assert ingress == "agent", (
        "issue ingress is mechanical: classifying it as user ingress would exempt "
        "it from the machine-P1 clamp and let a label buy boss-level urgency"
    )


# --- batch drain -----------------------------------------------------------

def test_departments_are_told_not_to_wait_for_the_next_wake(org_root: Path) -> None:
    """A 30-minute gate is a floor for sleepers, not a metronome for workers.

    A department that finishes an item and stands down waits up to 30 minutes for
    the next tick, so a 20-minute item occupies a 50-minute slot and the
    department's throughput is cut to a third — with a full inbox sitting there
    the whole time.
    """
    import shutil
    assert run_tool("org_admin.py", "create", "alpha", root=org_root).returncode == 0
    shutil.copy(REPO / "storage" / "org" / "policy.md", org_root / "policy.md")

    identity = _core.identity_prompt(org_root, "alpha")
    work = _core.work_prompt(org_root, "alpha")

    assert "接下一張" in identity, "the standing rule belongs in the org policy, once"
    assert "接下一張" in work
    for text in (identity, work):
        assert "收班條件" in text, "an unbounded drain is how a session runs itself into the ground"


def test_the_wake_message_carries_the_drain_rule(org_root: Path, monkeypatch) -> None:
    """Identity is written when the pane is created — a rule added afterwards
    only reaches a running department through the wake message."""
    import subprocess as sp
    import manager_tick

    assert run_tool("org_admin.py", "create", "alpha", root=org_root).returncode == 0
    assert run_tool("dept_send.py", "alpha", "--from", "manager", "--task", "做事",
                    "--no-wake", root=org_root).returncode == 0
    _core.write_lease(org_root, "alpha", {"runner": "herdr", "pane_id": "w1:p1"})

    sent: list[list[str]] = []

    class _R:
        returncode = 0
        stdout = json.dumps({"result": {"agent": {"agent_status": "idle"}}})
        stderr = ""

    def _run(cmd, **kw):
        sent.append(cmd)
        return _R()

    monkeypatch.setattr(sp, "run", _run)

    manager_tick.wake_departments(org_root)

    prompts = [c[-1] for c in sent if len(c) > 2 and c[1:3] == ["agent", "prompt"]]
    assert prompts, "an idle department holding due work must be woken"
    assert "做完一張直接接下一張" in prompts[0]
