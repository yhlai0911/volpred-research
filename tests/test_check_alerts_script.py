from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


def _load_check_alerts_module():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "check_alerts.py"
    spec = importlib.util.spec_from_file_location("check_alerts_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_auto_trigger_release_pool_if_due_records_fallback_observability(tmp_path: Path, monkeypatch):
    check_alerts = _load_check_alerts_module()
    monkeypatch.setattr(check_alerts, "PROJECT_ROOT", tmp_path)

    settings_path = tmp_path / "storage" / ".release_settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "mode": "auto",
                "interval_minutes": 60,
                "last_released_at": "2026-04-23T10:00:00+00:00",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    def _fake_run(cmd, cwd, capture_output, text, timeout):
        assert cwd == str(tmp_path)
        assert capture_output is True
        assert text is True
        assert timeout == 180
        return subprocess.CompletedProcess(cmd, 0, stdout="released\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = check_alerts._auto_trigger_release_pool_if_due()

    assert result["triggered"] is True
    assert result["ok"] is True

    release_log = (tmp_path / "storage" / "logs" / "cron" / "release_pool.log").read_text(encoding="utf-8")
    assert "check_alerts fallback fire" in release_log

    cron_last_run = json.loads((tmp_path / "storage" / "ops" / "cron_last_run.json").read_text(encoding="utf-8"))
    from datetime import datetime

    expected = datetime.fromisoformat(result["end_at"]).isoformat(timespec="seconds")
    assert cron_last_run["release_pool"] == expected


def test_release_pool_fallback_warns_on_corrupt_cron_state(tmp_path: Path, monkeypatch, capsys):
    check_alerts = _load_check_alerts_module()
    monkeypatch.setattr(check_alerts, "PROJECT_ROOT", tmp_path)
    state_path = tmp_path / "storage" / "ops" / "cron_last_run.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{bad json", encoding="utf-8")

    check_alerts._record_release_pool_fallback_fire(
        start_iso="2026-06-23T00:00:00+00:00",
        end_iso="2026-06-23T00:00:05+00:00",
        returncode=0,
    )

    captured = capsys.readouterr()
    assert "[check_alerts] WARN cron_last_run JSON read failed; using empty object" in captured.err
    assert "cron_last_run.json" in captured.err
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state == {"release_pool": "2026-06-23T00:00:05+00:00"}


def test_piggy_back_drift_warns_on_bad_state_source(tmp_path: Path, monkeypatch, capsys):
    check_alerts = _load_check_alerts_module()
    monkeypatch.setattr(check_alerts, "PROJECT_ROOT", tmp_path)
    state_path = tmp_path / "storage" / "ops" / "cron_last_run.json"
    config_path = tmp_path / "config" / "runtime_schedules.json"
    state_path.parent.mkdir(parents=True)
    config_path.parent.mkdir(parents=True)
    state_path.write_text("{bad json", encoding="utf-8")
    config_path.write_text(json.dumps({"system_crontab": {"items": []}}), encoding="utf-8")

    result = check_alerts._check_piggy_back_drift({"ok": True, "jobs": []})

    captured = capsys.readouterr()
    assert result == {"drift_count": 0, "drifts": []}
    assert "[check_alerts] WARN cron_last_run JSON read failed; using empty object" in captured.err
    assert "piggy-back-drift: none" in captured.out


def test_piggy_back_drift_warns_on_bad_job_timestamp(tmp_path: Path, monkeypatch, capsys):
    check_alerts = _load_check_alerts_module()
    monkeypatch.setattr(check_alerts, "PROJECT_ROOT", tmp_path)
    state_path = tmp_path / "storage" / "ops" / "cron_last_run.json"
    config_path = tmp_path / "config" / "runtime_schedules.json"
    state_path.parent.mkdir(parents=True)
    config_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({"paper_sync_all": "not-a-timestamp"}),
        encoding="utf-8",
    )
    config_path.write_text(
        json.dumps(
            {
                "system_crontab": {
                    "items": [
                        {
                            "id": "paper_sync_all",
                            "cron": "0 * * * *",
                            "host_crontab_managed": True,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = check_alerts._check_piggy_back_drift({"ok": True, "jobs": []})

    captured = capsys.readouterr()
    # 2026-07-10: this used to assert drift_count == 0 — the old loop `continue`d
    # past an unparsable marker, so a corrupt timestamp warned to stderr and then
    # vanished from the drift summary that log scrapers actually read. A marker we
    # cannot parse means we cannot tell whether the job ran; that IS drift. The
    # stderr WARN (the test's real contract) is unchanged.
    assert result["drift_count"] == 1
    assert result["drifts"] == ["unparsable_marker: paper_sync_all 'not-a-timestamp'"]
    assert "[check_alerts] WARN cron_last_run timestamp parse failed" in captured.err
    assert "job_id=paper_sync_all" in captured.err
    # WS-D1: parsing moved into volpred.ops.schedules.job_liveness; the WARN now
    # carries the raw marker instead of datetime's "Invalid isoformat string".
    assert "not-a-timestamp" in captured.err
    assert "piggy-back-drift:" in captured.out


def test_piggy_back_drift_reports_wrapper_drift(tmp_path: Path, monkeypatch):
    """launchd execs ~/.volpred/bin, not scripts/ — a stale live copy must surface here.

    2026-07-10: 11 of 40 wrappers had drifted, unnoticed, because nothing compared
    the two. This is the host half of the gate; the CI half is
    scripts/tests/test_cron_wrapper_manifest.py.
    """
    check_alerts = _load_check_alerts_module()
    monkeypatch.setattr(check_alerts, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        check_alerts,
        "_wrapper_drift_entries",
        lambda: ["wrapper_drift: release_pool live=5d5424471871 canonical=0abd01281e76"],
    )

    result = check_alerts._check_piggy_back_drift({"ok": True, "jobs": []})

    assert "wrapper_drift: release_pool live=5d5424471871 canonical=0abd01281e76" in result["drifts"]
    assert result["drift_count"] == 1


def test_wrapper_drift_entries_fails_loud_not_silent(monkeypatch):
    """A dead detector must not read as 'no drift' — that is how this class hides."""
    check_alerts = _load_check_alerts_module()
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(check_alerts, "PROJECT_ROOT", root)

    import sync_cron_wrappers

    def _boom(*_args, **_kwargs):
        raise RuntimeError("manifest unreadable")

    monkeypatch.setattr(sync_cron_wrappers, "detect_live_drift", _boom)

    entries = check_alerts._wrapper_drift_entries()
    assert entries == ["wrapper_drift_check_failed: RuntimeError: manifest unreadable"]


def test_wrapper_drift_entries_quiet_on_a_non_checkout_root(tmp_path: Path, monkeypatch):
    """Guards the exact-equality assertions above: a bare tmp PROJECT_ROOT adds no entries."""
    check_alerts = _load_check_alerts_module()
    monkeypatch.setattr(check_alerts, "PROJECT_ROOT", tmp_path)
    assert check_alerts._wrapper_drift_entries() == []


def test_append_next_task_locked_routes_machine_p1_through_gateway_clamp(tmp_path: Path):
    """2026-07-21 dispatch-lanes absorb: the CI-red P1 writer must pass the
    append_task_record admission clamp — machine-source P1 is admitted as P2
    (priority_capped_from=1). Timeliness rides on dispatch_preempt + the CI
    watcher's request_fire loop, not on the priority digit."""
    check_alerts = _load_check_alerts_module()
    queue = tmp_path / "next_tasks.json"
    task = check_alerts._build_ci_repair_task(
        {"databaseId": 999001, "attempt": 1, "headSha": "abc123def", "url": "https://x/runs/999001"},
        now_iso="2026-07-21T00:00:00+00:00",
    )
    assert task["priority"] == 1  # builder still declares P1 intent
    assert "repair_commit=pending_post_commit" in task["description"]
    assert "不自行 commit/push" in task["description"]

    created = check_alerts._append_next_task_locked(task, queue)

    assert created is True
    persisted = json.loads(queue.read_text(encoding="utf-8"))
    assert [t["id"] for t in persisted] == ["ci-red-999001"]
    assert persisted[0]["priority"] == 2
    assert persisted[0]["priority_capped_from"] == 1
    assert persisted[0]["dispatch_preempt"] is True  # the actual timeliness carrier survives

    # id-dedup contract preserved: replay returns False, queue unchanged.
    replay = check_alerts._build_ci_repair_task(
        {"databaseId": 999001, "attempt": 1, "headSha": "abc123def", "url": "https://x/runs/999001"},
        now_iso="2026-07-21T01:00:00+00:00",
    )
    assert check_alerts._append_next_task_locked(replay, queue) is False
    assert len(json.loads(queue.read_text(encoding="utf-8"))) == 1


def test_append_next_task_locked_keeps_time_critical_machine_p1(tmp_path: Path):
    """Clamp pass-through: a machine-built time-critical type keeps P1 (the
    2026-07-12 boss directive lives in task_urgency, not in this caller)."""
    check_alerts = _load_check_alerts_module()
    queue = tmp_path / "next_tasks.json"
    task = {
        "id": "evt_x",
        "title": "event",
        "task_type": "event_article",
        "priority": 1,
        "status": "pending",
        "source": "auto_remediation",
        "created_at": "2026-07-21T00:00:00+00:00",
    }
    assert check_alerts._append_next_task_locked(task, queue) is True
    persisted = json.loads(queue.read_text(encoding="utf-8"))
    assert persisted[0]["priority"] == 1
    assert "priority_capped_from" not in persisted[0]


def test_every_module_level_call_target_actually_exists():
    """Guard the merge-loss class: a call site outliving its definition.

    2026-07-22: merge 883903a96 took the agent branch's rewritten
    ``_append_next_task_locked`` and deleted the immediately-adjacent
    ``_ci_incident_store_sync`` along with it, while all three call sites
    survived.  Nothing failed at import time — the NameError only fired when
    ``_reduce_ci_run`` reached line 1788 at runtime, which is inside the hourly
    cron.  check_alerts.py then died on every run for 16 hours (alerting AND
    auto-remediation both down, since the orphan reaper sits past the crash
    point) and no test noticed.

    Importing the module is not enough to catch this, so walk the AST and
    assert every private ``_foo(...)`` call resolves to something defined in
    the module.  This generalises: it catches the next deletion too, not just
    this one.
    """
    import ast

    check_alerts = _load_check_alerts_module()
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "check_alerts.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    # Locally-bound names (imports, assignments, params) are legitimate targets too.
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.arg):
            defined.add(node.arg)

    missing = sorted(
        {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id.startswith("_")
            and node.func.id not in defined
            and not hasattr(check_alerts, node.func.id)
        }
    )
    assert not missing, f"call sites with no definition in check_alerts.py: {missing}"

    # The specific casualty, pinned by name so a re-deletion names itself.
    assert callable(getattr(check_alerts, "_ci_incident_store_sync", None))
