from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from volpred.ops import legacy_retirement_events
from volpred.ops.legacy_retirement import LegacyRetirementInputError
from volpred.ops.legacy_retirement_events import (
    append_legacy_business_fire,
    load_verified_legacy_business_fire_events,
    materialize_legacy_business_fire_signal,
)


def test_tripwire_appends_hash_chained_durable_events(tmp_path: Path) -> None:
    first_at = datetime(2026, 7, 27, 10, tzinfo=UTC)
    first = append_legacy_business_fire(tmp_path, occurred_at=first_at)
    second = append_legacy_business_fire(
        tmp_path,
        occurred_at=first_at + timedelta(minutes=1),
    )

    events = load_verified_legacy_business_fire_events(tmp_path)

    assert [event["sequence"] for event in events] == [1, 2]
    assert events[1]["previous_event_sha256"] == events[0]["event_sha256"]
    assert oct(first.stat().st_mode & 0o777) == "0o600"
    assert oct(second.parent.stat().st_mode & 0o777) == "0o700"


def test_event_tampering_and_deletion_fail_closed(tmp_path: Path) -> None:
    first_at = datetime(2026, 7, 27, 10, tzinfo=UTC)
    first = append_legacy_business_fire(tmp_path, occurred_at=first_at)
    append_legacy_business_fire(
        tmp_path,
        occurred_at=first_at + timedelta(minutes=1),
    )
    first_payload = json.loads(first.read_text(encoding="utf-8"))
    first_payload["pid"] = 999999
    first.write_text(json.dumps(first_payload), encoding="utf-8")

    with pytest.raises(LegacyRetirementInputError, match="chain is invalid"):
        load_verified_legacy_business_fire_events(tmp_path)

    first.unlink()
    with pytest.raises(LegacyRetirementInputError, match="chain is invalid"):
        load_verified_legacy_business_fire_events(tmp_path)


def test_tail_and_whole_ledger_truncation_fail_against_durable_head(
    tmp_path: Path,
) -> None:
    first_at = datetime(2026, 7, 27, 10, tzinfo=UTC)
    append_legacy_business_fire(tmp_path, occurred_at=first_at)
    second = append_legacy_business_fire(
        tmp_path,
        occurred_at=first_at + timedelta(minutes=1),
    )
    second.unlink()
    with pytest.raises(LegacyRetirementInputError, match="durable head"):
        load_verified_legacy_business_fire_events(tmp_path)

    ledger = second.parent
    for path in ledger.iterdir():
        path.unlink()
    ledger.rmdir()
    ledger.parent.rmdir()
    with pytest.raises(LegacyRetirementInputError, match="removed behind"):
        load_verified_legacy_business_fire_events(tmp_path)


def test_materializer_derives_signal_only_from_verified_events(tmp_path: Path) -> None:
    first_at = datetime(2026, 7, 27, 10, tzinfo=UTC)
    append_legacy_business_fire(tmp_path, occurred_at=first_at)
    append_legacy_business_fire(
        tmp_path,
        occurred_at=first_at + timedelta(minutes=1),
    )

    path = materialize_legacy_business_fire_signal(
        tmp_path,
        observed_at=first_at + timedelta(minutes=2),
    )
    signal = json.loads(path.read_text(encoding="utf-8"))

    assert signal == {
        "schema_version": "legacy-retirement-signal.v1",
        "dimension": "legacy_business_fire",
        "producer": "operations_core",
        "observed_at": "2026-07-27T10:02:00+00:00",
        "window_from": "2026-07-27T10:00:00+00:00",
        "window_to": "2026-07-27T10:02:00+00:00",
        "count": 2,
        "high_watermark": 2,
        "evidence_refs": [
            f"legacy-retirement-event://legacy_business_fire/{event['event_sha256']}"
            for event in load_verified_legacy_business_fire_events(tmp_path)
        ],
    }
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_materializer_rejects_future_or_symlinked_ledger(tmp_path: Path) -> None:
    now = datetime(2026, 7, 27, 10, tzinfo=UTC)
    append_legacy_business_fire(
        tmp_path,
        occurred_at=now + timedelta(minutes=1),
    )
    with pytest.raises(LegacyRetirementInputError, match="from the future"):
        materialize_legacy_business_fire_signal(tmp_path, observed_at=now)

    other = tmp_path / "other"
    other.mkdir()
    ledger = (
        tmp_path
        / "storage"
        / "ops"
        / "legacy_retirement_events"
        / "legacy_business_fire"
    )
    for path in ledger.iterdir():
        path.unlink()
    ledger.rmdir()
    os.symlink(other, ledger)
    with pytest.raises(LegacyRetirementInputError, match="traverses symlink"):
        append_legacy_business_fire(tmp_path, occurred_at=now)


def test_materializer_counts_new_sequence_at_equal_time_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = datetime(2026, 7, 27, 10, tzinfo=UTC)
    append_legacy_business_fire(
        tmp_path,
        occurred_at=boundary - timedelta(minutes=1),
    )
    append_legacy_business_fire(tmp_path, occurred_at=boundary)
    monkeypatch.setattr(
        legacy_retirement_events,
        "_previous_signal",
        lambda _root: {
            "schema_version": "legacy-retirement-signal.v1",
            "dimension": "legacy_business_fire",
            "producer": "operations_core",
            "window_to": boundary.isoformat(),
            "high_watermark": 1,
        },
    )

    path = materialize_legacy_business_fire_signal(
        tmp_path,
        observed_at=boundary,
    )
    signal = json.loads(path.read_text(encoding="utf-8"))

    assert signal["count"] == 1
    assert signal["high_watermark"] == 2


def test_legacy_wrapper_records_before_pregate_and_fails_closed() -> None:
    wrapper = (
        Path(__file__).resolve().parents[1] / "scripts" / "cron_hourly_dispatch.sh"
    ).read_text(encoding="utf-8")

    tripwire = wrapper.index("scripts/record_legacy_business_fire.py")
    pregate = wrapper.index("scripts/hourly_dispatch_pregate.py")
    assert tripwire < pregate
    assert "BLOCKED: could not record business-fire event" in wrapper


def test_operations_core_schedule_owns_signal_materialization() -> None:
    root = Path(__file__).resolve().parents[1]
    config = json.loads(
        (root / "config" / "runtime_schedules.json").read_text(encoding="utf-8")
    )
    item = next(
        item
        for item in config["system_crontab"]["items"]
        if item["id"] == "legacy_retirement_signal_materialize"
    )

    assert config["schedule_materialization"]["mode"] == "active"
    assert "legacy_retirement_signal_materialize" in (
        config["schedule_materialization"]["active_jobs"]
    )
    assert item["cron"] == "*/5 * * * *"
    assert item["host_crontab_managed"] is False
    assert item["piggy_back_enabled"] is False
    assert item["wrapper_script"].endswith(
        "/cron_legacy_retirement_signal_materialize.sh"
    )
