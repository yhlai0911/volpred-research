from __future__ import annotations

import json

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
    # Enumerate the real dimension list, never a hand-copied one. The previous
    # hard-coded tuple went stale the moment `worktree_reconcile` was added, and
    # the un-stubbed checker ran for real inside this unit test: quiet on a dev
    # box that has the worktrees, `critical` on a CI clone that has neither the
    # checkouts nor the branches. Deriving the list makes a future dimension
    # impossible to forget.
    for name in daily_checkup.CHECKUP_DIMENSIONS:
        if name == "reproducibility":
            continue
        monkeypatch.setattr(daily_checkup, f"check_{name}", lambda: [])

    def fail() -> list[dict]:
        raise RuntimeError("inventory unavailable")

    monkeypatch.setattr(daily_checkup, "check_reproducibility", fail)

    report = daily_checkup.run_all()

    assert report["overall"] == "warn"
    assert report["warn_count"] == 1
    assert report["findings"][0]["dimension"] == "reproducibility"
    assert "inventory unavailable" in report["findings"][0]["message"]


def test_every_declared_dimension_has_a_checker() -> None:
    """CHECKUP_DIMENSIONS is resolved by name at call time, so a typo would only
    surface as a runtime KeyError swallowed into a warn finding during a real
    checkup. Fail here instead."""
    missing = [
        name for name in daily_checkup.CHECKUP_DIMENSIONS
        if not callable(getattr(daily_checkup, f"check_{name}", None))
    ]
    assert missing == []


def test_fire_manifest_hook_check_warns_when_registration_is_missing(
    tmp_path, monkeypatch,
) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PostToolUse": []}}), encoding="utf-8"
    )
    monkeypatch.setattr(daily_checkup, "ROOT", tmp_path)

    findings = daily_checkup.check_fire_manifest_hook()

    assert len(findings) == 1
    assert findings[0]["dimension"] == "fire_manifest_hook"
    assert findings[0]["severity"] == "warn"
    assert "舊 shadow 診斷" in findings[0]["message"]
    assert "不能授權 commit ownership 切換" in findings[0]["message"]
    assert "Issue #44" in findings[0]["recovery"]
