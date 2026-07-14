from __future__ import annotations

from scripts import daily_checkup, reproduce_check


def _status(issues: list[dict]) -> dict:
    return {
        "schema_version": reproduce_check.STATUS_SCHEMA,
        "generated_at": "2026-07-14T00:00:00+00:00",
        "overall_severity": "warn" if issues else "ok",
        "counts": {},
        "issues": issues,
    }


def test_reproducibility_clean_status_adds_no_finding(monkeypatch) -> None:
    monkeypatch.setattr(reproduce_check, "build_status", lambda *_args, **_kwargs: _status([]))

    assert daily_checkup.check_reproducibility() == []


def test_reproducibility_projects_aggregated_issues_to_fixed_finding_schema(monkeypatch) -> None:
    issues = [
        {
            "experiment_id": "K1",
            "experiment_ids": ["K1"],
            "count": 1,
            "code": "RESULT_MISMATCH",
            "severity": "critical",
            "message": "1 report disagrees",
            "recovery": "audit K1",
        },
        {
            "experiment_id": "aggregate",
            "experiment_ids": [f"K{i}" for i in range(1, 6)],
            "count": 500,
            "code": "PRIORITY_UNVERIFIED",
            "severity": "warn",
            "message": "500 reports missing",
            "recovery": "inventory",
        },
    ]
    monkeypatch.setattr(reproduce_check, "build_status", lambda *_args, **_kwargs: _status(issues))
    monkeypatch.setattr(
        reproduce_check,
        "audit_experiment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("daily must not rerun")),
    )

    findings = daily_checkup.check_reproducibility()

    assert len(findings) == 2
    assert {item["severity"] for item in findings} == {"critical", "warn"}
    assert all(set(item) == {"dimension", "severity", "message", "recovery"} for item in findings)
    assert all(item["dimension"] == "reproducibility" for item in findings)
    assert "K1, K2, K3, K4, K5" in findings[1]["message"]


def test_run_all_turns_reproducibility_checker_exception_into_warning(monkeypatch) -> None:
    checker_names = (
        "check_data_freshness",
        "check_cron_completion",
        "check_content_pipeline",
        "check_live_freshness",
        "check_live_cache",
        "check_mission_progress",
        "check_alert_conditions",
        "check_reader_metrics",
        "check_dedup_calibration",
    )
    for name in checker_names:
        monkeypatch.setattr(daily_checkup, name, lambda: [])

    def fail() -> list[dict]:
        raise RuntimeError("inventory unavailable")

    monkeypatch.setattr(daily_checkup, "check_reproducibility", fail)

    report = daily_checkup.run_all()

    assert report["overall"] == "warn"
    assert report["warn_count"] == 1
    assert report["findings"][0]["dimension"] == "reproducibility"
    assert "inventory unavailable" in report["findings"][0]["message"]
