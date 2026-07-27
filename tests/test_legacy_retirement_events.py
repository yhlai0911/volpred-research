from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest

from volpred.ops import legacy_retirement_events
from volpred.ops.legacy_retirement import LegacyRetirementInputError
from volpred.ops.legacy_retirement_events import (
    append_legacy_business_fire,
    append_orphan_work_event,
    load_verified_legacy_business_fire_events,
    load_verified_orphan_work_events,
    materialize_duplicate_effect_signal,
    materialize_legacy_business_fire_signal,
)


class _DuplicateEffectRpc:
    backend_sha256 = "b" * 64

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call(self, function: str, payload: dict[str, object]) -> object:
        self.calls.append((function, payload))
        return self.payload


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


def test_orphan_tripwire_is_durable_hash_chained_and_idempotent(
    tmp_path: Path,
) -> None:
    first_at = datetime(2026, 7, 27, 11, 30, tzinfo=UTC)
    first = append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="worktree-dispatch-slot-1-deadbeef",
        job_id="deadbeef",
        occurred_at=first_at,
    )
    replay = append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="worktree-dispatch-slot-1-deadbeef",
        job_id="deadbeef",
        occurred_at=first_at + timedelta(minutes=1),
    )
    second = append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-2-cafebabe",
        branch="worktree-dispatch-slot-2-cafebabe",
        job_id="cafebabe",
        occurred_at=first_at + timedelta(minutes=2),
    )

    events = load_verified_orphan_work_events(tmp_path)

    assert replay == first
    assert [event["sequence"] for event in events] == [1, 2]
    assert all(
        event["schema_version"] == "orphan-work-retirement-event.v1"
        for event in events
    )
    assert all("event_kind" not in event for event in events)
    assert events[1]["previous_event_sha256"] == events[0]["event_sha256"]
    assert oct(first.stat().st_mode & 0o777) == "0o600"
    assert oct(second.parent.stat().st_mode & 0o777) == "0o700"


def test_orphan_tripwire_resolves_unreadable_branch_monotonically(
    tmp_path: Path,
) -> None:
    first_at = datetime(2026, 7, 27, 11, 30, tzinfo=UTC)
    detected = append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="unresolved",
        job_id="deadbeef",
        occurred_at=first_at,
    )
    resolved = append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="worktree-dispatch-slot-1-deadbeef",
        job_id="deadbeef",
        occurred_at=first_at + timedelta(minutes=1),
    )
    replay = append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="worktree-dispatch-slot-1-deadbeef",
        job_id="deadbeef",
        occurred_at=first_at + timedelta(minutes=2),
    )

    events = load_verified_orphan_work_events(tmp_path)

    assert resolved != detected
    assert replay == resolved
    assert [event["branch"] for event in events] == [
        "unresolved",
        "worktree-dispatch-slot-1-deadbeef",
    ]
    with pytest.raises(LegacyRetirementInputError, match="identity drifted"):
        append_orphan_work_event(
            tmp_path,
            workspace="dispatch-slot-1-deadbeef",
            branch="worktree-dispatch-slot-1-deadbeef-drift",
            job_id="deadbeef",
        )


@pytest.mark.parametrize(
    ("event_index", "field", "value"),
    [
        (0, "branch", "worktree-dispatch-slot-1-deadbeef"),
        (1, "job_id", "cafebabe"),
    ],
)
def test_orphan_loader_rejects_rehashed_invalid_resolution_history(
    tmp_path: Path,
    event_index: int,
    field: str,
    value: str,
) -> None:
    first_at = datetime(2026, 7, 27, 11, 30, tzinfo=UTC)
    append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="unresolved",
        job_id="deadbeef",
        occurred_at=first_at,
    )
    append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="worktree-dispatch-slot-1-deadbeef",
        job_id="deadbeef",
        occurred_at=first_at + timedelta(minutes=1),
    )
    spec = legacy_retirement_events._orphan_event_spec()
    directory = legacy_retirement_events._dimension_event_directory(
        tmp_path,
        "orphan_work",
    )
    paths = sorted(directory.glob("*.json"))
    payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in paths
    ]
    payloads[event_index][field] = value
    previous_sha = None
    for path, payload in zip(paths, payloads, strict=True):
        payload["previous_event_sha256"] = previous_sha
        payload["event_sha256"] = legacy_retirement_events._event_sha(payload)
        legacy_retirement_events._atomic_replace_payload(path, payload)
        previous_sha = payload["event_sha256"]
    head = legacy_retirement_events._build_durable_head(
        spec,
        event=payloads[-1],
    )
    legacy_retirement_events._atomic_replace_payload(
        legacy_retirement_events._dimension_head_path(
            tmp_path,
            "orphan_work",
        ),
        head,
    )

    with pytest.raises(LegacyRetirementInputError, match="history is invalid"):
        load_verified_orphan_work_events(tmp_path)


def test_orphan_tripwire_rejects_identity_drift_and_truncation(
    tmp_path: Path,
) -> None:
    first_at = datetime(2026, 7, 27, 11, 30, tzinfo=UTC)
    append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="worktree-dispatch-slot-1-deadbeef",
        job_id="deadbeef",
        occurred_at=first_at,
    )
    second = append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-2-cafebabe",
        branch="worktree-dispatch-slot-2-cafebabe",
        job_id="cafebabe",
        occurred_at=first_at + timedelta(minutes=1),
    )

    with pytest.raises(LegacyRetirementInputError, match="identity drifted"):
        append_orphan_work_event(
            tmp_path,
            workspace="dispatch-slot-1-deadbeef",
            branch="worktree-dispatch-slot-1-deadbeef-drift",
            job_id="deadbeef",
        )

    second.unlink()
    with pytest.raises(LegacyRetirementInputError, match="durable head"):
        load_verified_orphan_work_events(tmp_path)


def test_orphan_tripwire_rejects_tamper_and_symlink(tmp_path: Path) -> None:
    path = append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="worktree-dispatch-slot-1-deadbeef",
        job_id="deadbeef",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["workspace"] = "dispatch-slot-1-cafebabe"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LegacyRetirementInputError, match="chain is invalid"):
        load_verified_orphan_work_events(tmp_path)

    ledger = path.parent
    for child in ledger.iterdir():
        child.unlink()
    ledger.rmdir()
    target = tmp_path / "untrusted-ledger"
    target.mkdir()
    os.symlink(target, ledger)
    with pytest.raises(LegacyRetirementInputError, match="traverses symlink"):
        load_verified_orphan_work_events(tmp_path)


def test_orphan_tripwire_recovers_crash_between_event_and_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_replace = legacy_retirement_events._atomic_replace_payload
    fail_once = {"armed": True}

    def fail_first_head(path: Path, payload: dict[str, object]) -> None:
        if path.name == "orphan_work.json" and fail_once["armed"]:
            fail_once["armed"] = False
            raise OSError("injected head publish crash")
        real_replace(path, payload)

    monkeypatch.setattr(
        legacy_retirement_events,
        "_atomic_replace_payload",
        fail_first_head,
    )
    with pytest.raises(OSError, match="injected head publish crash"):
        append_orphan_work_event(
            tmp_path,
            workspace="dispatch-slot-1-deadbeef",
            branch="worktree-dispatch-slot-1-deadbeef",
            job_id="deadbeef",
        )
    with pytest.raises(LegacyRetirementInputError, match="needs recovery"):
        load_verified_orphan_work_events(tmp_path)

    path = append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="worktree-dispatch-slot-1-deadbeef",
        job_id="deadbeef",
    )
    events = load_verified_orphan_work_events(tmp_path)

    assert path.exists()
    assert len(events) == 1
    assert events[0]["workspace"] == "dispatch-slot-1-deadbeef"
    assert not (
        tmp_path
        / "storage"
        / "ops"
        / "legacy_retirement_event_heads"
        / ".orphan_work.append-intent.json"
    ).exists()


@pytest.mark.parametrize("dimension", ["legacy_business_fire", "orphan_work"])
def test_local_event_append_recovers_partial_temporary_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dimension: str,
) -> None:
    real_install = legacy_retirement_events._install_event_payload
    fail_once = {"armed": True}

    def leave_partial_temporary(
        root: Path,
        spec,
        *,
        event_path: Path,
        event: dict[str, object],
    ) -> None:
        if fail_once["armed"]:
            fail_once["armed"] = False
            temporary = legacy_retirement_events._pending_event_temp_path(
                root,
                spec,
                str(event["event_id"]),
            )
            temporary.write_bytes(b'{"partial"')
            raise OSError("injected partial event crash")
        real_install(
            root,
            spec,
            event_path=event_path,
            event=event,
        )

    monkeypatch.setattr(
        legacy_retirement_events,
        "_install_event_payload",
        leave_partial_temporary,
    )
    if dimension == "orphan_work":
        append = lambda: append_orphan_work_event(
            tmp_path,
            workspace="dispatch-slot-1-deadbeef",
            branch="worktree-dispatch-slot-1-deadbeef",
            job_id="deadbeef",
        )
        load = lambda: load_verified_orphan_work_events(tmp_path)
        spec = legacy_retirement_events._orphan_event_spec()
    else:
        append = lambda: append_legacy_business_fire(tmp_path)
        load = lambda: load_verified_legacy_business_fire_events(tmp_path)
        spec = legacy_retirement_events._legacy_event_spec()

    with pytest.raises(OSError, match="injected partial event crash"):
        append()
    with legacy_retirement_events._dimension_event_append_lock(
        tmp_path,
        dimension,
    ):
        legacy_retirement_events._recover_pending_append(tmp_path, spec)

    events = load()
    assert len(events) == 1
    assert not legacy_retirement_events._dimension_pending_path(
        tmp_path,
        dimension,
    ).exists()
    assert not list(
        legacy_retirement_events._dimension_head_path(
            tmp_path,
            dimension,
        ).parent.glob(f".{dimension}.*.event.tmp")
    )


def test_orphan_materializer_uses_verified_sequence_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = datetime(2026, 7, 27, 11, 35, tzinfo=UTC)
    append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="worktree-dispatch-slot-1-deadbeef",
        job_id="deadbeef",
        occurred_at=boundary - timedelta(minutes=1),
    )
    append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-2-cafebabe",
        branch="worktree-dispatch-slot-2-cafebabe",
        job_id="cafebabe",
        occurred_at=boundary,
    )
    monkeypatch.setattr(
        legacy_retirement_events,
        "_previous_dimension_signal",
        lambda _root, _dimension: {
            "schema_version": "legacy-retirement-signal.v1",
            "dimension": "orphan_work",
            "producer": "operations_core",
            "window_to": boundary.isoformat(),
            "high_watermark": 1,
        },
    )

    path = legacy_retirement_events.materialize_orphan_work_signal(
        tmp_path,
        observed_at=boundary,
    )
    signal = json.loads(path.read_text(encoding="utf-8"))

    assert signal["dimension"] == "orphan_work"
    assert signal["count"] == 1
    assert signal["high_watermark"] == 2
    assert signal["window_from"] == boundary.isoformat()
    assert signal["window_to"] == boundary.isoformat()
    assert len(signal["evidence_refs"]) == 1
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_orphan_materializer_advances_over_resolution_without_double_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = datetime(2026, 7, 27, 11, 35, tzinfo=UTC)
    append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="unresolved",
        job_id="deadbeef",
        occurred_at=boundary - timedelta(minutes=1),
    )
    append_orphan_work_event(
        tmp_path,
        workspace="dispatch-slot-1-deadbeef",
        branch="worktree-dispatch-slot-1-deadbeef",
        job_id="deadbeef",
        occurred_at=boundary,
    )
    monkeypatch.setattr(
        legacy_retirement_events,
        "_previous_dimension_signal",
        lambda _root, _dimension: {
            "schema_version": "legacy-retirement-signal.v1",
            "dimension": "orphan_work",
            "producer": "operations_core",
            "window_to": (boundary - timedelta(seconds=1)).isoformat(),
            "high_watermark": 1,
        },
    )

    path = legacy_retirement_events.materialize_orphan_work_signal(
        tmp_path,
        observed_at=boundary,
    )
    signal = json.loads(path.read_text(encoding="utf-8"))

    assert signal["count"] == 0
    assert signal["high_watermark"] == 2
    assert len(signal["evidence_refs"]) == 1


def test_orphan_materializer_emits_verified_empty_high_watermark(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 27, 11, 35, tzinfo=UTC)

    path = legacy_retirement_events.materialize_orphan_work_signal(
        tmp_path,
        observed_at=now,
    )
    signal = json.loads(path.read_text(encoding="utf-8"))

    assert signal["count"] == 0
    assert signal["high_watermark"] == 0
    assert signal["window_from"] == now.isoformat()
    assert signal["evidence_refs"] == [
        "legacy-retirement-event-ledger://orphan_work/high-watermark/0"
    ]


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
    assert "materialize_orphan_work_signal.py" in item["matchers"]
    wrapper = (
        root / "scripts" / "cron_legacy_retirement_signal_materialize.sh"
    ).read_text(encoding="utf-8")
    assert wrapper.index("materialize_duplicate_effect_signal.py") < wrapper.index(
        "materialize_orphan_work_signal.py"
    )


def test_duplicate_effect_signal_uses_exact_database_sequence_delta(
    tmp_path: Path,
) -> None:
    rpc = _DuplicateEffectRpc(
        {
            "schema_version": "duplicate-effect-retirement-events.v1",
            "observed_at": "2026-07-27T11:10:00+00:00",
            "after_sequence": 0,
            "high_watermark": 2,
            "events": [
                {
                    "sequence": 1,
                    "effect_id": "effect-one",
                    "first_delivered_attempt_count": 1,
                    "offending_attempt_count": 2,
                    "offending_evidence_sha256": "1" * 64,
                    "detected_at": "2026-07-27T11:08:00+00:00",
                },
                {
                    "sequence": 2,
                    "effect_id": "effect-two",
                    "first_delivered_attempt_count": 3,
                    "offending_attempt_count": 2,
                    "offending_evidence_sha256": "2" * 64,
                    "detected_at": "2026-07-27T11:09:00+00:00",
                },
            ],
        }
    )

    path = materialize_duplicate_effect_signal(tmp_path, rpc_client=rpc)  # type: ignore[arg-type]
    signal = json.loads(path.read_text(encoding="utf-8"))

    assert rpc.calls == [
        (
            "volpred_read_duplicate_effect_retirement_events",
            {"p_after_sequence": 0},
        )
    ]
    assert signal["count"] == 2
    assert signal["high_watermark"] == 2
    assert signal["window_from"] == "2026-07-27T11:08:00+00:00"
    assert signal["window_to"] == "2026-07-27T11:10:00+00:00"
    assert len(signal["evidence_refs"]) == 2


def test_duplicate_effect_signal_rejects_gap_or_cursor_drift(
    tmp_path: Path,
) -> None:
    rpc = _DuplicateEffectRpc(
        {
            "schema_version": "duplicate-effect-retirement-events.v1",
            "observed_at": "2026-07-27T11:10:00+00:00",
            "after_sequence": 0,
            "high_watermark": 2,
            "events": [],
        }
    )

    with pytest.raises(
        LegacyRetirementInputError,
        match="sequence coverage",
    ):
        materialize_duplicate_effect_signal(tmp_path, rpc_client=rpc)  # type: ignore[arg-type]


def test_duplicate_effect_signal_assigns_late_commit_to_current_sequence_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.legacy_retirement_events._previous_dimension_signal",
        lambda _root, _dimension: {
            "schema_version": "legacy-retirement-signal.v1",
            "dimension": "duplicate_effect",
            "producer": "operations_core",
            "observed_at": "2026-07-27T11:10:00+00:00",
            "window_from": "2026-07-27T11:00:00+00:00",
            "window_to": "2026-07-27T11:10:00+00:00",
            "count": 0,
            "high_watermark": 0,
            "evidence_refs": ["test://initial"],
        },
    )
    rpc = _DuplicateEffectRpc(
        {
            "schema_version": "duplicate-effect-retirement-events.v1",
            "observed_at": "2026-07-27T11:15:00+00:00",
            "after_sequence": 0,
            "high_watermark": 1,
            "events": [
                {
                    "sequence": 1,
                    "effect_id": "effect-late",
                    "first_delivered_attempt_count": 1,
                    "offending_attempt_count": 2,
                    "offending_evidence_sha256": "3" * 64,
                    "detected_at": "2026-07-27T11:09:59+00:00",
                }
            ],
        }
    )

    path = materialize_duplicate_effect_signal(tmp_path, rpc_client=rpc)  # type: ignore[arg-type]
    signal = json.loads(path.read_text(encoding="utf-8"))

    assert signal["count"] == 1
    assert signal["high_watermark"] == 1
    assert signal["window_from"] == "2026-07-27T11:10:00+00:00"
    assert signal["window_to"] == "2026-07-27T11:15:00+00:00"


def test_duplicate_effect_materialization_serializes_rpc_through_publish(
    tmp_path: Path,
) -> None:
    first_entered = Event()
    release_first = Event()
    second_entered = Event()

    class BlockingRpc(_DuplicateEffectRpc):
        def call(self, function: str, payload: dict[str, object]) -> object:
            first_entered.set()
            assert release_first.wait(timeout=2)
            return super().call(function, payload)

    class ObservedRpc(_DuplicateEffectRpc):
        def call(self, function: str, payload: dict[str, object]) -> object:
            second_entered.set()
            return super().call(function, payload)

    first_rpc = BlockingRpc(
        {
            "schema_version": "duplicate-effect-retirement-events.v1",
            "observed_at": "2026-07-27T11:10:00+00:00",
            "after_sequence": 0,
            "high_watermark": 0,
            "events": [],
        }
    )
    second_rpc = ObservedRpc(
        {
            "schema_version": "duplicate-effect-retirement-events.v1",
            "observed_at": "2026-07-27T11:11:00+00:00",
            "after_sequence": 0,
            "high_watermark": 1,
            "events": [
                {
                    "sequence": 1,
                    "effect_id": "effect-concurrent",
                    "first_delivered_attempt_count": 1,
                    "offending_attempt_count": 2,
                    "offending_evidence_sha256": "4" * 64,
                    "detected_at": "2026-07-27T11:10:30+00:00",
                }
            ],
        }
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            materialize_duplicate_effect_signal,
            tmp_path,
            rpc_client=first_rpc,  # type: ignore[arg-type]
        )
        assert first_entered.wait(timeout=2)
        second = executor.submit(
            materialize_duplicate_effect_signal,
            tmp_path,
            rpc_client=second_rpc,  # type: ignore[arg-type]
        )
        assert not second_entered.wait(timeout=0.1)
        release_first.set()
        first.result(timeout=2)
        second.result(timeout=2)

    signal = json.loads(
        (
            tmp_path
            / "storage"
            / "ops"
            / "legacy_retirement_signals"
            / "duplicate_effect.json"
        ).read_text(encoding="utf-8")
    )
    assert signal["high_watermark"] == 1
    assert signal["count"] == 1
