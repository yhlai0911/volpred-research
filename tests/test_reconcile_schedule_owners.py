from __future__ import annotations

from pathlib import Path

import pytest

from scripts import reconcile_schedule_owners as owners
from scripts.reconcile_schedule_owners import audit_owner_plan, build_owner_plan


def config(mode: str = "canary") -> dict:
    return {
        "metadata": {"timezone": "Asia/Taipei"},
        "daemons": [],
        "schedule_materialization": {
            "generation": "g1",
            "mode": mode,
            "active_since": "2026-07-26T10:00:00Z" if mode == "active" else None,
            "active_jobs": (
                {"host_job": {"activated_at": "2026-07-26T10:00:00Z"}}
                if mode == "canary"
                else {}
            ),
        },
        "system_crontab": {
            "items": [
                {
                    "id": "host_job",
                    "cron": "0 * * * *",
                    "wrapper_script": "/bin/true",
                    "host_crontab_managed": True,
                },
                {
                    "id": "launch_job",
                    "cron": "15 * * * *",
                    "wrapper_script": "/bin/true",
                    "host_crontab_managed": False,
                    "mechanism": "launchd",
                    "launchagent_label": "com.volpred.launch-job",
                },
            ]
        },
    }


def test_canary_plan_has_one_owner_per_job() -> None:
    plan = build_owner_plan(config())

    assert plan["operations_core_job_ids"] == ["host_job"]
    assert plan["legacy_job_ids"] == ["launch_job"]
    assert plan["legacy_labels_to_bootout"] == ["com.volpred.host-job"]


def test_active_plan_decommissions_legacy_launchagent() -> None:
    plan = build_owner_plan(config(mode="active"))

    assert plan["operations_core_job_ids"] == ["host_job", "launch_job"]
    assert plan["legacy_job_ids"] == []
    assert plan["legacy_labels_to_bootout"] == [
        "com.volpred.host-job",
        "com.volpred.launch-job",
    ]


def test_audit_reports_host_and_launchagent_conflicts() -> None:
    plan = build_owner_plan(config(mode="active"))
    audit = audit_owner_plan(
        plan,
        crontab_text=(
            "0 * * * * /bin/true >> /tmp/x 2>&1 # volpred-host-job\n"
        ),
        loaded_labels={
            "com.volpred.operations-core-scheduler",
            "com.volpred.launch-job",
        },
    )

    assert audit["ok"] is False
    assert {item["surface"] for item in audit["conflicts"]} == {
        "host_crontab",
        "com.volpred.launch-job",
    }


def test_audit_green_requires_core_clock() -> None:
    plan = build_owner_plan(config())
    missing = audit_owner_plan(plan, crontab_text="", loaded_labels=set())
    green = audit_owner_plan(
        plan,
        crontab_text="",
        loaded_labels={"com.volpred.operations-core-scheduler"},
    )

    assert missing["ok"] is False
    assert green["ok"] is True
    assert green["status"] == "owner_surfaces_verified"


def test_audit_green_requires_every_active_control_plane_daemon() -> None:
    runtime = config()
    runtime["daemons"] = [
        {
            "id": "volpred-dispatch-supervisor",
            "type": "launchd_keepalive_daemon",
            "label": "com.volpred.dispatch-supervisor",
            "plist": "ops/launchd/com.volpred.dispatch-supervisor.plist",
        }
    ]
    plan = build_owner_plan(runtime)

    missing = audit_owner_plan(
        plan,
        crontab_text="",
        loaded_labels={"com.volpred.operations-core-scheduler"},
    )
    green = audit_owner_plan(
        plan,
        crontab_text="",
        loaded_labels={
            "com.volpred.operations-core-scheduler",
            "com.volpred.dispatch-supervisor",
        },
    )

    assert missing["ok"] is False
    assert missing["conflicts"] == [
        {
            "job_id": "volpred-dispatch-supervisor",
            "surface": "com.volpred.dispatch-supervisor",
            "reason": "required control-plane daemon not loaded",
        }
    ]
    assert green["ok"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", None),
        ("label", ""),
        ("plist", 7),
    ],
)
def test_active_control_plane_daemon_requires_nonempty_string_identity(
    field: str,
    value: object,
) -> None:
    runtime = config()
    daemon = {
        "id": "volpred-dispatch-supervisor",
        "type": "launchd_keepalive_daemon",
        "label": "com.volpred.dispatch-supervisor",
        "plist": "ops/launchd/com.volpred.dispatch-supervisor.plist",
    }
    daemon[field] = value
    runtime["daemons"] = [daemon]

    with pytest.raises(
        RuntimeError,
        match=rf"active launchd_keepalive_daemon has invalid {field}",
    ):
        build_owner_plan(runtime)


@pytest.mark.parametrize("bad_daemons", [{}, "dispatch", [None]])
def test_owner_plan_rejects_malformed_daemon_registry(
    bad_daemons: object,
) -> None:
    runtime = config()
    runtime["daemons"] = bad_daemons

    with pytest.raises(RuntimeError, match="invalid daemons registry"):
        build_owner_plan(runtime)


@pytest.mark.parametrize("daemon_type", [None, "unknown_daemon"])
def test_owner_plan_rejects_missing_or_unknown_daemon_type(
    daemon_type: object,
) -> None:
    runtime = config()
    runtime["daemons"] = [
        {
            "id": "volpred-dispatch-supervisor",
            "type": daemon_type,
            "label": "com.volpred.dispatch-supervisor",
            "plist": "ops/launchd/com.volpred.dispatch-supervisor.plist",
        }
    ]

    with pytest.raises(RuntimeError, match="unsupported daemon type"):
        build_owner_plan(runtime)


def test_audit_accepts_dormant_host_clock_only_with_verified_owner_gate() -> None:
    plan = build_owner_plan(config())
    live_host_line = (
        "0 * * * * /bin/true >> /tmp/x 2>&1 # volpred-host-job\n"
    )

    audit = audit_owner_plan(
        plan,
        crontab_text=live_host_line,
        loaded_labels={"com.volpred.operations-core-scheduler"},
        gated_job_ids={"host_job"},
    )

    assert audit["ok"] is True
    assert audit["conflicts"] == []
    assert audit["dormant_legacy_surfaces"] == [
        {
            "job_id": "host_job",
            "surface": "host_crontab",
            "reason": (
                "legacy clock present but business action suppressed by owner gate"
            ),
        }
    ]


def test_unchanged_loaded_core_plist_is_not_restarted(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "source.plist"
    destination = tmp_path / "Library" / "LaunchAgents" / source.name
    source.write_bytes(
        b"<?xml version='1.0'?><plist version='1.0'><dict/></plist>"
    )
    destination.parent.mkdir(parents=True)
    destination.write_bytes(source.read_bytes())
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def run(command, **_kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(owners, "CORE_PLIST", source)
    monkeypatch.setattr(owners, "CORE_LABEL", "com.volpred.test")
    monkeypatch.setattr(owners.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(owners.subprocess, "run", run)

    owners._install_core_plist()

    assert calls == [
        ["launchctl", "print", f"gui/{owners.os.getuid()}/com.volpred.test"]
    ]


def test_restart_core_reloads_unchanged_plist(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.plist"
    destination = tmp_path / "Library" / "LaunchAgents" / source.name
    source.write_bytes(
        b"<?xml version='1.0'?><plist version='1.0'><dict/></plist>"
    )
    destination.parent.mkdir(parents=True)
    destination.write_bytes(source.read_bytes())
    calls: list[list[str]] = []
    loaded_results = iter([True, True, False, False])

    class Result:
        def __init__(self, returncode: int = 0) -> None:
            self.returncode = returncode

    def run(command, **_kwargs):
        calls.append(command)
        if command[:2] == ["launchctl", "print"]:
            return Result(0 if next(loaded_results) else 1)
        return Result()

    monkeypatch.setattr(owners, "CORE_PLIST", source)
    monkeypatch.setattr(owners, "CORE_LABEL", "com.volpred.test")
    monkeypatch.setattr(owners.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(owners.subprocess, "run", run)

    owners._install_core_plist(restart=True)

    domain = f"gui/{owners.os.getuid()}"
    assert ["launchctl", "bootout", f"{domain}/com.volpred.test"] in calls
    assert ["launchctl", "bootstrap", domain, str(destination)] in calls


def test_apply_restores_missing_required_control_plane_daemon(
    tmp_path, monkeypatch
) -> None:
    runtime = config()
    runtime["daemons"] = [
        {
            "id": "volpred-dispatch-supervisor",
            "type": "launchd_keepalive_daemon",
            "label": "com.volpred.dispatch-supervisor",
            "plist": "ops/launchd/com.volpred.dispatch-supervisor.plist",
        }
    ]
    source = (
        tmp_path
        / "ops"
        / "launchd"
        / "com.volpred.dispatch-supervisor.plist"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(
        b"<?xml version='1.0'?><plist version='1.0'>"
        b"<!-- canonical comments may mention --dry-run -->"
        b"<dict>"
        b"<key>Label</key><string>com.volpred.dispatch-supervisor</string>"
        b"</dict></plist>"
    )
    calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def run(command, **_kwargs):
        calls.append(command)
        if command[:3] == ["plutil", "-extract", "Label"]:
            return Result(stdout="com.volpred.dispatch-supervisor\n")
        if command[:2] == ["launchctl", "print"]:
            return Result(1)
        return Result()

    monkeypatch.setattr(owners, "ROOT", tmp_path)
    monkeypatch.setattr(owners.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(owners, "_install_core_plist", lambda **_kwargs: None)
    monkeypatch.setattr(
        owners,
        "_legacy_gate_covered_job_ids",
        lambda _config: {"host_job", "launch_job"},
    )
    monkeypatch.setattr(
        owners,
        "_run_host_reconcile",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(owners.subprocess, "run", run)

    owners.apply_owner_plan(
        runtime,
        build_owner_plan(runtime),
        config_path=Path("runtime.json"),
        job_id=None,
    )

    destination = (
        tmp_path
        / "Library"
        / "LaunchAgents"
        / "com.volpred.dispatch-supervisor.plist"
    )
    assert destination.read_bytes() == source.read_bytes()
    assert [
        "launchctl",
        "bootstrap",
        f"gui/{owners.os.getuid()}",
        str(destination),
    ] in calls


def test_required_daemon_restore_rejects_repo_escape(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(owners, "ROOT", tmp_path)

    with pytest.raises(
        RuntimeError,
        match="required daemon plist must be repo-relative",
    ):
        owners._restore_missing_required_daemons(
            [
                {
                    "id": "dispatch",
                    "label": "com.volpred.dispatch-supervisor",
                    "plist": "../outside.plist",
                }
            ]
        )


def test_required_daemon_restore_rejects_plist_label_mismatch(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "ops" / "launchd" / "dispatch.plist"
    source.parent.mkdir(parents=True)
    source.write_text("placeholder", encoding="utf-8")

    def run(command, **_kwargs):
        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "com.volpred.wrong\n",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(owners, "ROOT", tmp_path)
    monkeypatch.setattr(owners.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="plist label mismatch"):
        owners._restore_missing_required_daemons(
            [
                {
                    "id": "dispatch",
                    "label": "com.volpred.dispatch-supervisor",
                    "plist": "ops/launchd/dispatch.plist",
                }
            ]
        )


def test_required_daemon_restore_does_not_restart_loaded_daemon(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "ops" / "launchd" / "dispatch.plist"
    source.parent.mkdir(parents=True)
    source.write_text("placeholder", encoding="utf-8")
    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(command)
        stdout = (
            "com.volpred.dispatch-supervisor\n"
            if command[:3] == ["plutil", "-extract", "Label"]
            else ""
        )
        return type(
            "Result",
            (),
            {"returncode": 0, "stdout": stdout, "stderr": ""},
        )()

    monkeypatch.setattr(owners, "ROOT", tmp_path)
    monkeypatch.setattr(owners.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(owners.subprocess, "run", run)

    owners._restore_missing_required_daemons(
        [
            {
                "id": "dispatch",
                "label": "com.volpred.dispatch-supervisor",
                "plist": "ops/launchd/dispatch.plist",
            }
        ]
    )

    assert not any(command[:2] == ["launchctl", "bootstrap"] for command in calls)
    assert not (tmp_path / "Library" / "LaunchAgents" / "dispatch.plist").exists()


@pytest.mark.parametrize("converges_after_failure", [True, False])
def test_required_daemon_restore_handles_concurrent_bootstrap_race(
    tmp_path,
    monkeypatch,
    converges_after_failure: bool,
) -> None:
    source = tmp_path / "ops" / "launchd" / "dispatch.plist"
    source.parent.mkdir(parents=True)
    source.write_text("placeholder", encoding="utf-8")
    print_count = 0

    class Result:
        def __init__(self, returncode: int, stdout: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = "bootstrap failed" if returncode else ""

    def run(command, **kwargs):
        nonlocal print_count
        if command[:3] == ["plutil", "-extract", "Label"]:
            return Result(0, "com.volpred.dispatch-supervisor\n")
        if command[:2] == ["launchctl", "print"]:
            print_count += 1
            loaded = converges_after_failure and print_count > 1
            return Result(0 if loaded else 1)
        if command[:2] == ["launchctl", "bootstrap"]:
            if kwargs.get("check"):
                raise owners.subprocess.CalledProcessError(5, command)
            return Result(5)
        return Result(0)

    monkeypatch.setattr(owners, "ROOT", tmp_path)
    monkeypatch.setattr(owners.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(owners.subprocess, "run", run)

    daemon = {
        "id": "dispatch",
        "label": "com.volpred.dispatch-supervisor",
        "plist": "ops/launchd/dispatch.plist",
    }
    if converges_after_failure:
        owners._restore_missing_required_daemons([daemon])
        assert print_count == 2
    else:
        with pytest.raises(owners.subprocess.CalledProcessError):
            owners._restore_missing_required_daemons([daemon])
