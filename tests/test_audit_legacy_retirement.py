from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import scripts.audit_legacy_retirement as audit
from volpred.ops.legacy_retirement import LegacyRetirementInputError

NOW = datetime(2026, 7, 27, 11, 0, tzinfo=UTC)


def test_missing_observation_directory_is_an_empty_blocking_population(
    tmp_path: Path,
) -> None:
    assert audit._load_observations(tmp_path) == []


def test_unreadable_observation_fails_closed(tmp_path: Path) -> None:
    directory = tmp_path / "storage" / "ops" / "legacy_retirement_observations"
    bundle = directory / "00000001-bad"
    (bundle / "sources").mkdir(parents=True)
    (bundle / "receipt.json").write_text("{", encoding="utf-8")

    with pytest.raises(
        LegacyRetirementInputError,
        match="could not read observation receipt",
    ):
        audit._load_observations(tmp_path)


def test_host_probe_reads_live_launchctl_and_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper = tmp_path / "cron_hourly_dispatch.sh"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "PID\tStatus\tLabel\n"
                "-\t0\tcom.volpred.hourly-dispatch\n"
                "42\t0\tcom.volpred.dispatch-supervisor\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(audit.subprocess, "run", fake_run)

    report = audit._probe_host(
        observed_at=NOW,
        live_wrapper=wrapper,
    )

    assert report["label_loaded"] is True
    assert report["live_wrapper_exists"] is True
    assert observed["command"] == ["launchctl", "list"]
    assert observed["kwargs"] == {
        "capture_output": True,
        "text": True,
        "check": True,
        "timeout": 10,
    }


def test_broken_live_wrapper_symlink_is_still_a_physical_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper = tmp_path / "cron_hourly_dispatch.sh"
    wrapper.symlink_to(tmp_path / "missing-target")
    monkeypatch.setattr(
        audit.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr="",
        ),
    )

    report = audit._probe_host(
        observed_at=NOW,
        live_wrapper=wrapper,
    )

    assert report["live_wrapper_exists"] is True


def test_host_probe_error_is_not_interpreted_as_unloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(["launchctl", "list"], 10)

    monkeypatch.setattr(audit.subprocess, "run", timeout)

    with pytest.raises(
        LegacyRetirementInputError,
        match="launchctl owner probe failed",
    ):
        audit._probe_host(observed_at=NOW)


def test_main_distinguishes_blocked_from_invalid(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit,
        "run_audit",
        lambda: {
            "schema_version": "legacy-execution-retirement.v1",
            "ready": False,
            "status": "retirement_blocked",
        },
    )
    assert audit.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "retirement_blocked"

    monkeypatch.setattr(
        audit,
        "run_audit",
        lambda: (_ for _ in ()).throw(LegacyRetirementInputError("bad evidence")),
    )
    assert audit.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "audit_failed"
