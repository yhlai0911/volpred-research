from __future__ import annotations

from scripts import reconcile_schedule_owners as owners
from scripts.reconcile_schedule_owners import audit_owner_plan, build_owner_plan


def config(mode: str = "canary") -> dict:
    return {
        "metadata": {"timezone": "Asia/Taipei"},
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
