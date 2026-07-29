from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from volpred.ops.legacy_retirement import (
    LegacyRetirementInputError,
    append_current_retirement_observation,
    append_retirement_observation,
    assess_hourly_dispatch_retirement,
    assess_sustained_clean_receipts,
    load_verified_retirement_observations,
)

NOW = datetime(2026, 7, 27, 10, 30, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def _owner_report(
    *,
    ok: bool = True,
    audited_at: datetime = NOW,
) -> dict[str, object]:
    return {
        "schema_version": "formal-owner-census.v1",
        "ok": ok,
        "status": "unique_owners_verified" if ok else "ownership_blocked",
        "inventory_sha256": "a" * 64,
        "blockers": [] if ok else [{"capability": "work.coordinate"}],
        "capabilities": [{"capability": "work.coordinate"}],
        "audited_at": audited_at.isoformat(),
    }


def _receipt(observed_at: datetime, *, index: int) -> dict[str, object]:
    return {
        "schema_version": "legacy-retirement-observation-bundle.v1",
        "receipt_id": f"receipt-{index:03d}",
        "observed_at": observed_at.isoformat(),
        "formal_owner_census": {
            "ok": True,
            "inventory_sha256": f"{index + 1:064x}",
        },
        "violations": {
            "silent_loss": 0,
            "duplicate_effect": 0,
            "orphan_work": 0,
            "unknown_ownership": 0,
            "legacy_business_fire": 0,
        },
        "evidence": {
            key: {
                "source_ref": f"receipt://{key}/{index}",
                "snapshot_sha256": f"{index + offset + 1:064x}",
            }
            for offset, key in enumerate(
                (
                    "silent_loss",
                    "duplicate_effect",
                    "orphan_work",
                    "unknown_ownership",
                    "legacy_business_fire",
                )
            )
        },
    }


def _write_runtime_files(root: Path, *, retired: bool = True) -> None:
    (root / "config").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "ops" / "launchd").mkdir(parents=True)
    (root / "config" / "runtime_schedules.json").write_text(
        json.dumps(
            {
                "cron_jobs": [
                    {
                        "id": "volpred-hourly-dispatch",
                        "status": "retired" if retired else "active",
                        "command": "/Users/test/.volpred/bin/cron_hourly_dispatch.sh",
                        "canonical_script": "scripts/cron_hourly_dispatch.sh",
                        "tcc_bypass_copy": "~/.volpred/bin/cron_hourly_dispatch.sh",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "config" / "scheduled_writer_ownership.json").write_text(
        json.dumps(
            {
                "jobs": {
                    "volpred-hourly-dispatch": {
                        "entrypoint": "scripts/cron_hourly_dispatch.sh",
                        "policy": "deprecated",
                    }
                },
                "launchagents": {
                    "com.volpred.hourly-dispatch": {
                        "job_id": "volpred-hourly-dispatch",
                        "status": "retired",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "config" / "cron_wrapper_manifest.json").write_text(
        json.dumps(
            {
                "wrappers": {
                    "cron_hourly_dispatch.sh": "a" * 64,
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "scripts" / "cron_hourly_dispatch.sh").write_text(
        "#!/bin/sh\n",
        encoding="utf-8",
    )
    (root / "ops" / "launchd" / "com.volpred.hourly-dispatch.plist").write_text(
        "<plist/>",
        encoding="utf-8",
    )


def test_repository_has_physically_retired_hourly_dispatch_surfaces() -> None:
    """The rollback artifact may exist only under scripts/_legacy."""
    runtime = json.loads(
        (ROOT / "config" / "runtime_schedules.json").read_text(encoding="utf-8")
    )
    row = next(
        item
        for item in runtime["cron_jobs"]
        if item["id"] == "volpred-hourly-dispatch"
    )
    assert row["status"] == "retired"
    assert row["schedule"] == "7 * * * *"
    assert isinstance(row.get("pregate"), dict)
    assert {"command", "canonical_script", "tcc_bypass_copy"}.isdisjoint(row)

    ownership = json.loads(
        (ROOT / "config" / "scheduled_writer_ownership.json").read_text(
            encoding="utf-8"
        )
    )
    assert "volpred-hourly-dispatch" not in ownership["jobs"]
    assert "com.volpred.hourly-dispatch" not in ownership["launchagents"]

    manifest = json.loads(
        (ROOT / "config" / "cron_wrapper_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert "cron_hourly_dispatch.sh" not in manifest["wrappers"]
    assert not (ROOT / "scripts" / "cron_hourly_dispatch.sh").exists()
    assert (
        ROOT / "scripts" / "_legacy" / "cron_hourly_dispatch.sh"
    ).is_file()
    assert not (
        ROOT / "scripts" / "_legacy" / "cron_hourly_dispatch.sh"
    ).stat().st_mode & 0o111
    assert not (
        ROOT / "ops" / "launchd" / "com.volpred.hourly-dispatch.plist"
    ).exists()


def _rehash_receipt(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("receipt_sha256", None)
    raw = (
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    payload["receipt_sha256"] = hashlib.sha256(raw).hexdigest()


def _write_signals(
    root: Path,
    observed_at: datetime,
    *,
    window_from: datetime | None = None,
    high_watermark: int | None = None,
) -> None:
    signal_dir = root / "storage" / "ops" / "legacy_retirement_signals"
    signal_dir.mkdir(parents=True, exist_ok=True)
    for dimension in (
        "silent_loss",
        "duplicate_effect",
        "orphan_work",
        "legacy_business_fire",
    ):
        path = signal_dir / f"{dimension}.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "legacy-retirement-signal.v1",
                    "dimension": dimension,
                    "producer": "operations_core",
                    "observed_at": observed_at.isoformat(),
                    "window_from": (
                        window_from or observed_at - timedelta(hours=1)
                    ).isoformat(),
                    "window_to": observed_at.isoformat(),
                    "high_watermark": (
                        high_watermark
                        if high_watermark is not None
                        else int(observed_at.timestamp())
                    ),
                    "count": 0,
                    "evidence_refs": [f"live://{dimension}/1"],
                }
            ),
            encoding="utf-8",
        )


def test_append_only_bundle_rehashes_typed_source_bytes(tmp_path: Path) -> None:
    _write_signals(tmp_path, NOW)

    bundle = append_retirement_observation(
        root=tmp_path,
        owner_report=_owner_report(),
        observed_at=NOW,
    )

    verified = load_verified_retirement_observations(tmp_path)
    assert len(verified) == 1
    assert verified[0]["receipt_id"] == bundle.name
    assert verified[0]["violations"] == {
        "silent_loss": 0,
        "duplicate_effect": 0,
        "orphan_work": 0,
        "unknown_ownership": 0,
        "legacy_business_fire": 0,
    }


def test_owner_blockers_are_recorded_without_starting_a_clean_suffix(
    tmp_path: Path,
) -> None:
    _write_signals(tmp_path, NOW)

    append_current_retirement_observation(
        root=tmp_path,
        owner_report=_owner_report(ok=False),
        observed_at=NOW,
        batch_not_before=NOW.replace(minute=0, second=0, microsecond=0),
    )

    verified = load_verified_retirement_observations(tmp_path)
    assert verified[0]["formal_owner_census"]["ok"] is False
    assert verified[0]["violations"]["unknown_ownership"] == 1
    assessment = assess_sustained_clean_receipts(
        verified,
        assessed_at=NOW,
    )
    assert assessment.ready is False
    assert assessment.observation_count == 0
    assert "clean_window_incomplete" in assessment.reason_codes


def test_fresh_mixed_hour_signal_batch_is_rejected_before_append(
    tmp_path: Path,
) -> None:
    observed_at = NOW.replace(minute=2)
    hour_start = observed_at.replace(minute=0, second=0, microsecond=0)
    _write_signals(tmp_path, observed_at)
    stale_dimension = (
        tmp_path
        / "storage"
        / "ops"
        / "legacy_retirement_signals"
        / "duplicate_effect.json"
    )
    payload = json.loads(stale_dimension.read_text(encoding="utf-8"))
    previous_batch_at = hour_start - timedelta(minutes=1)
    payload["observed_at"] = previous_batch_at.isoformat()
    payload["window_to"] = previous_batch_at.isoformat()
    payload["window_from"] = (previous_batch_at - timedelta(hours=1)).isoformat()
    stale_dimension.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        LegacyRetirementInputError,
        match="precedes required materialization boundary",
    ):
        append_current_retirement_observation(
            root=tmp_path,
            owner_report=_owner_report(audited_at=observed_at),
            observed_at=observed_at,
            batch_not_before=hour_start,
        )

    observations = (
        tmp_path / "storage" / "ops" / "legacy_retirement_observations"
    )
    assert not observations.exists()


def test_operations_core_owns_hourly_retirement_observation_recording() -> None:
    root = Path(__file__).resolve().parents[1]
    runtime = json.loads(
        (root / "config" / "runtime_schedules.json").read_text(encoding="utf-8")
    )
    observer = next(
        item
        for item in runtime["system_crontab"]["items"]
        if item["id"] == "legacy_retirement_observe"
    )
    materializer = next(
        item
        for item in runtime["system_crontab"]["items"]
        if item["id"] == "legacy_retirement_signal_materialize"
    )

    assert runtime["schedule_materialization"]["mode"] == "active"
    assert "legacy_retirement_observe" in (
        runtime["schedule_materialization"]["active_jobs"]
    )
    assert observer["cron"] == "2 * * * *"
    assert materializer["cron"] == "*/5 * * * *"
    assert observer["host_crontab_managed"] is False
    assert observer["piggy_back_enabled"] is False
    assert observer["staleness_expected_minutes"] == 75
    assert observer["wrapper_script"].endswith(
        "/cron_legacy_retirement_observe.sh"
    )
    assert "record_legacy_retirement_observation.py" in observer["matchers"]
    assert "materialize_legacy_retirement_signal_batch.py" in (
        materializer["matchers"]
    )

    override = runtime["schedule_materialization"]["job_overrides"][
        "legacy_retirement_observe"
    ]
    assert override == {
        "catch_up": "skip",
        "max_attempts": 3,
        "retry_delay_seconds": 60,
        "timeout_seconds": 300,
    }

    ownership = json.loads(
        (root / "config" / "scheduled_writer_ownership.json").read_text(
            encoding="utf-8"
        )
    )
    owner = ownership["jobs"]["legacy_retirement_observe"]
    assert owner["entrypoint"] == "scripts/cron_legacy_retirement_observe.sh"
    assert owner["policy"] == "no_repo_tracked_output"
    assert owner["tracked_outputs"] == []
    materializer_owner = ownership["jobs"][
        "legacy_retirement_signal_materialize"
    ]
    assert materializer_owner["policy"] == "no_repo_tracked_output"
    assert materializer_owner["tracked_outputs"] == []

    wrapper = (
        root / "scripts" / "cron_legacy_retirement_observe.sh"
    ).read_text(encoding="utf-8")
    assert wrapper.count("scripts/record_legacy_retirement_observation.py") == 1
    assert "materialize_" not in wrapper
    assert "source scripts/cron_lib.sh || exit 1" in wrapper
    assert 'cron_emit_start "legacy_retirement_observe" || exit 1' in wrapper
    assert 'cron_emit_start "legacy_retirement_observe"' in wrapper
    assert 'cron_emit_exit "legacy_retirement_observe"' in wrapper
    assert "exit \"$_ec\"" in wrapper

    gitignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "storage/ops/legacy_retirement_observations/" in gitignore
    assert "storage/ops/legacy_retirement_signals/" in gitignore
    signal_directory = "storage/ops/legacy_retirement_signals"
    tracked_signals = subprocess.run(
        ["git", "ls-files", "-z", "--", signal_directory],
        cwd=root,
        capture_output=True,
        check=True,
    )
    assert tracked_signals.stdout == b""
    for name in (
        ".batch.lock",
        ".materialize.lock",
        "duplicate_effect.json",
        "legacy_business_fire.json",
        "orphan_work.json",
        "silent_loss.json",
    ):
        ignored = subprocess.run(
            [
                "git",
                "check-ignore",
                "--no-index",
                "-q",
                "--",
                f"{signal_directory}/{name}",
            ],
            cwd=root,
            check=False,
        )
        assert ignored.returncode == 0, name


def test_observation_rejects_stale_owner_or_noncanonical_signal_paths(
    tmp_path: Path,
) -> None:
    _write_signals(tmp_path, NOW)
    with pytest.raises(
        LegacyRetirementInputError,
        match="owner census snapshot is stale",
    ):
        append_retirement_observation(
            root=tmp_path,
            owner_report=_owner_report(audited_at=NOW - timedelta(minutes=1)),
            observed_at=NOW,
        )

    signal_dir = tmp_path / "storage" / "ops" / "legacy_retirement_signals"
    external = tmp_path / "external-signals"
    signal_dir.rename(external)
    signal_dir.symlink_to(external, target_is_directory=True)
    with pytest.raises(
        LegacyRetirementInputError,
        match="must not traverse symlink",
    ):
        append_retirement_observation(
            root=tmp_path,
            owner_report=_owner_report(),
            observed_at=NOW,
        )


def test_observation_directory_symlink_is_rejected(
    tmp_path: Path,
) -> None:
    _write_signals(tmp_path, NOW)
    observations = tmp_path / "storage" / "ops" / "legacy_retirement_observations"
    external = tmp_path / "external-observations"
    external.mkdir()
    observations.symlink_to(external, target_is_directory=True)

    with pytest.raises(
        LegacyRetirementInputError,
        match="must not traverse symlink",
    ):
        append_retirement_observation(
            root=tmp_path,
            owner_report=_owner_report(),
            observed_at=NOW,
        )


@pytest.mark.parametrize("failure", ["coverage_gap", "watermark_regression"])
def test_event_coverage_must_be_gap_free_and_monotonic(
    tmp_path: Path,
    failure: str,
) -> None:
    first_time = NOW - timedelta(minutes=1)
    _write_signals(tmp_path, first_time)
    append_retirement_observation(
        root=tmp_path,
        owner_report=_owner_report(audited_at=first_time),
        observed_at=first_time,
    )
    _write_signals(
        tmp_path,
        NOW,
        window_from=(
            first_time - timedelta(seconds=1)
            if failure == "coverage_gap"
            else first_time
        ),
        high_watermark=(
            int(first_time.timestamp()) - 1
            if failure == "watermark_regression"
            else None
        ),
    )

    with pytest.raises(
        LegacyRetirementInputError,
        match="coverage is not gap-free|high_watermark regressed",
    ):
        append_retirement_observation(
            root=tmp_path,
            owner_report=_owner_report(),
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    "tamper",
    ["snapshot", "source_ref", "count", "chain"],
)
def test_forged_bundle_cannot_advance_window(
    tmp_path: Path,
    tamper: str,
) -> None:
    _write_signals(tmp_path, NOW - timedelta(minutes=1))
    first = append_retirement_observation(
        root=tmp_path,
        owner_report=_owner_report(audited_at=NOW - timedelta(minutes=1)),
        observed_at=NOW - timedelta(minutes=1),
    )
    _write_signals(
        tmp_path,
        NOW,
        window_from=NOW - timedelta(minutes=1),
    )
    second = append_retirement_observation(
        root=tmp_path,
        owner_report=_owner_report(),
        observed_at=NOW,
    )
    target = second / "receipt.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    if tamper == "snapshot":
        (first / "sources" / "duplicate_effect.json").write_text("{}", encoding="utf-8")
    elif tamper == "source_ref":
        payload["evidence"]["orphan_work"]["source_ref"] = "manual://fake"
        _rehash_receipt(payload)
        target.write_text(json.dumps(payload), encoding="utf-8")
    elif tamper == "count":
        payload["violations"]["silent_loss"] = 0 + 1
        _rehash_receipt(payload)
        target.write_text(json.dumps(payload), encoding="utf-8")
    else:
        payload["previous_receipt_sha256"] = "f" * 64
        target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        LegacyRetirementInputError,
        match=(
            "hash is invalid|source_ref is not canonical|count drifted|chain is invalid"
        ),
    ):
        load_verified_retirement_observations(tmp_path)


def test_fourteen_continuous_days_are_required(tmp_path: Path) -> None:
    receipts = [
        _receipt(NOW - timedelta(days=14) + timedelta(hours=index), index=index)
        for index in range(14 * 24 + 1)
    ]

    report = assess_sustained_clean_receipts(
        receipts,
        assessed_at=NOW,
        required_window=timedelta(days=14),
        max_gap=timedelta(minutes=75),
        max_age=timedelta(minutes=75),
    )

    assert report.ready is True
    assert report.reason_codes == ()
    assert report.observation_count == 14 * 24 + 1


def test_violation_restarts_the_clean_window(tmp_path: Path) -> None:
    receipts = [
        _receipt(NOW - timedelta(days=15) + timedelta(hours=index), index=index)
        for index in range(15 * 24 + 1)
    ]
    receipts[23]["violations"]["duplicate_effect"] = 1  # type: ignore[index]

    report = assess_sustained_clean_receipts(
        receipts,
        assessed_at=NOW,
        required_window=timedelta(days=14),
        max_gap=timedelta(minutes=75),
        max_age=timedelta(minutes=75),
    )

    assert report.ready is True
    assert report.recorded_from == (NOW - timedelta(days=14)).isoformat()


def test_gap_and_stale_tail_fail_closed() -> None:
    receipts = [
        _receipt(NOW - timedelta(days=14), index=0),
        _receipt(NOW - timedelta(minutes=90), index=1),
    ]

    report = assess_sustained_clean_receipts(
        receipts,
        assessed_at=NOW,
        required_window=timedelta(days=14),
        max_gap=timedelta(minutes=75),
        max_age=timedelta(minutes=75),
    )

    assert report.ready is False
    assert set(report.reason_codes) == {
        "observation_gap",
        "observation_stale",
        "clean_window_incomplete",
    }


def test_fourteen_clean_days_after_historical_gap_are_ready() -> None:
    receipts = [
        _receipt(NOW - timedelta(days=16), index=0),
        *[
            _receipt(
                NOW - timedelta(days=14) + timedelta(hours=index),
                index=index + 1,
            )
            for index in range(14 * 24 + 1)
        ],
    ]

    report = assess_sustained_clean_receipts(
        receipts,
        assessed_at=NOW,
        required_window=timedelta(days=14),
        max_gap=timedelta(minutes=75),
        max_age=timedelta(minutes=75),
    )

    assert report.ready is True
    assert report.reason_codes == ()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda receipt: receipt.update(receipt_id="receipt-000"),
            "duplicate receipt_id",
        ),
        (
            lambda receipt: receipt["evidence"].pop("orphan_work"),
            "evidence must contain",
        ),
        (
            lambda receipt: receipt["formal_owner_census"].update(ok=False),
            "formal owner census",
        ),
        (
            lambda receipt: receipt["violations"].update(silent_loss=-1),
            "non-negative integer",
        ),
    ],
)
def test_malformed_observation_is_rejected(mutate, message: str) -> None:
    first = _receipt(NOW - timedelta(hours=1), index=0)
    second = _receipt(NOW, index=1)
    mutate(second)
    with pytest.raises(LegacyRetirementInputError, match=message):
        assess_sustained_clean_receipts(
            [first, second],
            assessed_at=NOW,
        )


def test_existing_rollback_artifacts_keep_retirement_blocked(tmp_path: Path) -> None:
    _write_runtime_files(tmp_path)

    report = assess_hourly_dispatch_retirement(
        root=tmp_path,
        owner_report=_owner_report(),
        sustained_clean_report={"ready": True, "reason_codes": []},
        host_evidence={
            "label_loaded": False,
            "live_wrapper_exists": True,
            "observed_at": NOW.isoformat(),
        },
        assessed_at=NOW,
    )

    assert report.ready is False
    assert set(report.blocker_codes) == {
        "canonical_wrapper_present",
        "live_wrapper_present",
        "launchd_plist_present",
        "runtime_command_reference_present",
        "runtime_canonical_reference_present",
        "runtime_tcc_reference_present",
        "wrapper_manifest_reference_present",
        "writer_launchagent_reference_present",
        "writer_registry_reference_present",
    }
    assert "launchd_label_loaded" not in report.blocker_codes


def test_broken_canonical_symlink_is_not_treated_as_retired(
    tmp_path: Path,
) -> None:
    _write_runtime_files(tmp_path)
    wrapper = tmp_path / "scripts" / "cron_hourly_dispatch.sh"
    wrapper.unlink()
    wrapper.symlink_to(tmp_path / "missing-target")

    report = assess_hourly_dispatch_retirement(
        root=tmp_path,
        owner_report=_owner_report(),
        sustained_clean_report={"ready": True, "reason_codes": []},
        host_evidence={
            "label_loaded": False,
            "live_wrapper_exists": False,
            "observed_at": NOW.isoformat(),
        },
        assessed_at=NOW,
    )

    assert "canonical_wrapper_present" in report.blocker_codes


def test_formal_owner_and_soak_are_mandatory_even_after_artifact_removal(
    tmp_path: Path,
) -> None:
    _write_runtime_files(tmp_path)
    (tmp_path / "scripts" / "cron_hourly_dispatch.sh").unlink()
    (tmp_path / "ops" / "launchd" / "com.volpred.hourly-dispatch.plist").unlink()
    runtime = json.loads((tmp_path / "config" / "runtime_schedules.json").read_text())
    row = runtime["cron_jobs"][0]
    row.pop("command")
    row.pop("canonical_script")
    row.pop("tcc_bypass_copy")
    (tmp_path / "config" / "runtime_schedules.json").write_text(
        json.dumps(runtime),
        encoding="utf-8",
    )
    ownership = json.loads(
        (tmp_path / "config" / "scheduled_writer_ownership.json").read_text()
    )
    ownership["jobs"].pop("volpred-hourly-dispatch")
    ownership["launchagents"].pop("com.volpred.hourly-dispatch")
    (tmp_path / "config" / "scheduled_writer_ownership.json").write_text(
        json.dumps(ownership),
        encoding="utf-8",
    )
    manifest = json.loads(
        (tmp_path / "config" / "cron_wrapper_manifest.json").read_text()
    )
    manifest["wrappers"].pop("cron_hourly_dispatch.sh")
    (tmp_path / "config" / "cron_wrapper_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    report = assess_hourly_dispatch_retirement(
        root=tmp_path,
        owner_report=_owner_report(ok=False),
        sustained_clean_report={
            "ready": False,
            "reason_codes": ["clean_window_incomplete"],
        },
        host_evidence={
            "label_loaded": False,
            "live_wrapper_exists": False,
            "observed_at": NOW.isoformat(),
        },
        assessed_at=NOW,
    )

    assert set(report.blocker_codes) == {
        "formal_owner_census_blocked",
        "sustained_clean_blocked",
    }


def test_retirement_can_be_verified_only_after_all_surfaces_are_absent(
    tmp_path: Path,
) -> None:
    _write_runtime_files(tmp_path)
    (tmp_path / "scripts" / "cron_hourly_dispatch.sh").unlink()
    (tmp_path / "ops" / "launchd" / "com.volpred.hourly-dispatch.plist").unlink()
    for file_name in (
        "runtime_schedules.json",
        "scheduled_writer_ownership.json",
        "cron_wrapper_manifest.json",
    ):
        path = tmp_path / "config" / file_name
        payload = json.loads(path.read_text(encoding="utf-8"))
        if file_name == "runtime_schedules.json":
            row = payload["cron_jobs"][0]
            row.pop("command", None)
            row.pop("canonical_script", None)
            row.pop("tcc_bypass_copy", None)
        elif file_name == "scheduled_writer_ownership.json":
            payload["jobs"].pop("volpred-hourly-dispatch")
            payload["launchagents"].pop("com.volpred.hourly-dispatch")
        else:
            payload["wrappers"].pop("cron_hourly_dispatch.sh")
        path.write_text(json.dumps(payload), encoding="utf-8")

    report = assess_hourly_dispatch_retirement(
        root=tmp_path,
        owner_report=_owner_report(),
        sustained_clean_report={"ready": True, "reason_codes": []},
        host_evidence={
            "label_loaded": False,
            "live_wrapper_exists": False,
            "observed_at": NOW.isoformat(),
        },
        assessed_at=NOW,
    )

    assert report.ready is True
    assert report.status == "physically_retired_verified"
    assert report.blocker_codes == ()
