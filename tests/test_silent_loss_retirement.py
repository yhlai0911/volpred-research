from __future__ import annotations

import json
from pathlib import Path

import pytest

from volpred.ops.legacy_retirement import LegacyRetirementInputError
from volpred.ops.silent_loss_retirement import materialize_silent_loss_signal


class FakeRpc:
    backend_sha256 = "b" * 64

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call(self, function: str, payload: dict[str, object]) -> object:
        self.calls.append((function, payload))
        return self.payload


def _event(
    *,
    sequence: int = 1,
    detected_at: str = "2026-07-27T11:31:00+00:00",
) -> dict[str, object]:
    return {
        "sequence": sequence,
        "work_id": "work-silent-loss",
        "work_version": 3,
        "violation_kind": "deadline_missed",
        "work_status": "running",
        "deadline": "2026-07-27T11:30:00+00:00",
        "detected_at": detected_at,
    }


def test_materializes_exact_silent_loss_sequence_delta(tmp_path: Path) -> None:
    rpc = FakeRpc(
        {
            "schema_version": "silent-loss-retirement-events.v1",
            "observed_at": "2026-07-27T11:32:00+00:00",
            "after_sequence": 0,
            "high_watermark": 1,
            "events": [_event()],
            "active_violations": [_event()],
        }
    )

    path = materialize_silent_loss_signal(tmp_path, rpc_client=rpc)  # type: ignore[arg-type]
    signal = json.loads(path.read_text(encoding="utf-8"))

    assert rpc.calls == [
        (
            "volpred_reconcile_silent_loss_retirement_events",
            {"p_after_sequence": 0},
        )
    ]
    assert signal["dimension"] == "silent_loss"
    assert signal["producer"] == "operations_core"
    assert signal["count"] == 1
    assert signal["high_watermark"] == 1
    assert signal["window_from"] == "2026-07-27T11:31:00+00:00"
    assert signal["window_to"] == "2026-07-27T11:32:00+00:00"
    assert len(signal["evidence_refs"]) == 1


def test_clean_silent_loss_snapshot_is_backend_bound(tmp_path: Path) -> None:
    rpc = FakeRpc(
        {
            "schema_version": "silent-loss-retirement-events.v1",
            "observed_at": "2026-07-27T11:32:00+00:00",
            "after_sequence": 0,
            "high_watermark": 0,
            "events": [],
            "active_violations": [],
        }
    )

    path = materialize_silent_loss_signal(tmp_path, rpc_client=rpc)  # type: ignore[arg-type]
    signal = json.loads(path.read_text(encoding="utf-8"))

    assert signal["count"] == 0
    assert signal["high_watermark"] == 0
    assert signal["evidence_refs"] == [
        (
            "operations-core-work://silent-loss/high-watermark/"
            f"0/backend/{'b' * 64}"
        )
    ]


def test_silent_loss_signal_rejects_sequence_gap(tmp_path: Path) -> None:
    rpc = FakeRpc(
        {
            "schema_version": "silent-loss-retirement-events.v1",
            "observed_at": "2026-07-27T11:32:00+00:00",
            "after_sequence": 0,
            "high_watermark": 2,
            "events": [_event(sequence=2)],
            "active_violations": [_event(sequence=2)],
        }
    )

    with pytest.raises(
        LegacyRetirementInputError,
        match="sequence coverage",
    ):
        materialize_silent_loss_signal(tmp_path, rpc_client=rpc)  # type: ignore[arg-type]


def test_late_visible_event_stays_in_current_cursor_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.silent_loss_retirement._previous_dimension_signal",
        lambda _root, _dimension: {
            "schema_version": "legacy-retirement-signal.v1",
            "dimension": "silent_loss",
            "producer": "operations_core",
            "observed_at": "2026-07-27T11:32:00+00:00",
            "window_from": "2026-07-27T11:30:00+00:00",
            "window_to": "2026-07-27T11:32:00+00:00",
            "count": 0,
            "high_watermark": 0,
            "evidence_refs": ["test://initial"],
        },
    )
    rpc = FakeRpc(
        {
            "schema_version": "silent-loss-retirement-events.v1",
            "observed_at": "2026-07-27T11:35:00+00:00",
            "after_sequence": 0,
            "high_watermark": 1,
            "events": [
                _event(detected_at="2026-07-27T11:31:00+00:00")
            ],
            "active_violations": [
                _event(detected_at="2026-07-27T11:31:00+00:00")
            ],
        }
    )

    path = materialize_silent_loss_signal(tmp_path, rpc_client=rpc)  # type: ignore[arg-type]
    signal = json.loads(path.read_text(encoding="utf-8"))

    assert signal["count"] == 1
    assert signal["window_from"] == "2026-07-27T11:32:00+00:00"
    assert signal["window_to"] == "2026-07-27T11:35:00+00:00"


def test_unresolved_violation_remains_nonzero_after_cursor_advances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.silent_loss_retirement._previous_dimension_signal",
        lambda _root, _dimension: {
            "schema_version": "legacy-retirement-signal.v1",
            "dimension": "silent_loss",
            "producer": "operations_core",
            "observed_at": "2026-07-27T11:32:00+00:00",
            "window_from": "2026-07-27T11:30:00+00:00",
            "window_to": "2026-07-27T11:32:00+00:00",
            "count": 1,
            "high_watermark": 1,
            "evidence_refs": ["test://violation"],
        },
    )
    rpc = FakeRpc(
        {
            "schema_version": "silent-loss-retirement-events.v1",
            "observed_at": "2026-07-27T11:35:00+00:00",
            "after_sequence": 1,
            "high_watermark": 1,
            "events": [],
            "active_violations": [_event()],
        }
    )

    path = materialize_silent_loss_signal(tmp_path, rpc_client=rpc)  # type: ignore[arg-type]
    signal = json.loads(path.read_text(encoding="utf-8"))

    assert signal["count"] == 1
    assert signal["high_watermark"] == 1
    assert signal["window_from"] == "2026-07-27T11:32:00+00:00"
