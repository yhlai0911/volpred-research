import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_work_shadow_observer_has_one_hourly_append_only_schedule_owner() -> None:
    schedules = json.loads(
        (ROOT / "config" / "runtime_schedules.json").read_text(
            encoding="utf-8"
        )
    )
    matches = [
        item
        for item in schedules["system_crontab"]["items"]
        if item["id"] == "work_shadow_observe"
    ]

    assert len(matches) == 1
    item = matches[0]
    assert item["cron"] == "15 * * * *"
    assert item["host_crontab_managed"] is False
    assert item["piggy_back_enabled"] is True
    assert item["wrapper_script"] == (
        "/Users/yhlai0911/.volpred/bin/cron_work_shadow_observe.sh"
    )

    policy = json.loads(
        (ROOT / "config" / "scheduled_writer_ownership.json").read_text(
            encoding="utf-8"
        )
    )["jobs"]["work_shadow_observe"]
    assert policy == {
        "entrypoint": "scripts/observe_work_shadow.py",
        "policy": "no_repo_tracked_output",
        "tracked_outputs": [],
        "reason": (
            "Hourly Work Coordinator shadow replay only appends ignored "
            "runtime evidence receipts; it does not mutate either queue owner."
        ),
    }

    wrapper = (
        ROOT / "scripts" / "cron_work_shadow_observe.sh"
    ).read_text(encoding="utf-8")
    assert "source scripts/cron_lib.sh" in wrapper
    assert "scripts/observe_work_shadow.py" in wrapper
    assert "work-shadow-replay" not in wrapper

    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "storage/ops/work_shadow_observations/" in ignored
