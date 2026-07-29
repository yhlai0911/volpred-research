from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import custody_receipt


def _custody(coalition_id: int = 73) -> dict[str, object]:
    return {
        "version": 2,
        "host_uuid": "92515cc4-ec37-5659-923e-c700da4843a4",
        "boot_session_uuid": "05699489-50d5-4a6d-b11b-7aa4550f48ca",
        "resource_coalition_id": coalition_id,
        "trusted_unique_ids": [1001],
    }


def _ledger(repo: Path) -> Path:
    return repo / custody_receipt.RECEIPTS_RELPATH


def _lines(repo: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in _ledger(repo).read_text(encoding="utf-8").splitlines()
    ]


def test_bind_is_durable_and_read_returns_the_pending_generation(
    tmp_path: Path,
) -> None:
    with pytest.raises(custody_receipt.CustodyLedgerUnavailable):
        custody_receipt.read_pending_producer_custodies(tmp_path)

    assert custody_receipt.initialize_producer_custody_ledger(
        tmp_path,
        migration_confirmed_quiescent=True,
    )
    assert custody_receipt.read_pending_producer_custodies(tmp_path) == []

    assert custody_receipt.bind_producer_custody(
        tmp_path,
        job_id="job-1",
        attempt=1,
        custody=_custody(),
        bound_at="2026-07-29T07:30:00+00:00",
    )

    assert custody_receipt.read_pending_producer_custodies(tmp_path) == [
        {
            "job_id": "job-1",
            "attempt": 1,
            "custody": _custody(),
            "bound_at": "2026-07-29T07:30:00+00:00",
        }
    ]
    assert _ledger(tmp_path).read_bytes().endswith(b"\n")


def test_duplicate_bind_is_idempotent_but_conflicting_custody_fails_closed(
    tmp_path: Path,
) -> None:
    custody_receipt.initialize_producer_custody_ledger(
        tmp_path,
        migration_confirmed_quiescent=True,
    )
    kwargs = {
        "job_id": "job-1",
        "attempt": 2,
        "custody": _custody(),
        "bound_at": "2026-07-29T07:31:00+00:00",
    }
    assert custody_receipt.bind_producer_custody(tmp_path, **kwargs)
    assert not custody_receipt.bind_producer_custody(tmp_path, **kwargs)
    assert len(_lines(tmp_path)) == 1

    with pytest.raises(custody_receipt.CustodyBindingConflict):
        custody_receipt.bind_producer_custody(
            tmp_path,
            job_id="job-1",
            attempt=2,
            custody=_custody(coalition_id=99),
        )
    assert len(_lines(tmp_path)) == 1


def test_release_requires_positive_drain_and_is_idempotent(tmp_path: Path) -> None:
    custody_receipt.initialize_producer_custody_ledger(
        tmp_path,
        migration_confirmed_quiescent=True,
    )
    assert custody_receipt.bind_producer_custody(
        tmp_path,
        job_id="job-1",
        attempt=1,
        custody=_custody(),
        bound_at="2026-07-29T07:32:00+00:00",
    )

    with pytest.raises(custody_receipt.CustodyDrainUnconfirmed):
        custody_receipt.release_producer_custody(
            tmp_path,
            job_id="job-1",
            attempt=1,
            drain_confirmed=False,
        )
    assert len(custody_receipt.read_pending_producer_custodies(tmp_path)) == 1

    assert custody_receipt.release_producer_custody(
        tmp_path,
        job_id="job-1",
        attempt=1,
        drain_confirmed=True,
        released_at="2026-07-29T07:33:00+00:00",
    )
    assert custody_receipt.read_pending_producer_custodies(tmp_path) == []
    assert not custody_receipt.release_producer_custody(
        tmp_path,
        job_id="job-1",
        attempt=1,
        drain_confirmed=True,
    )
    assert len(_lines(tmp_path)) == 2
    assert _lines(tmp_path)[1] == {
        "schema_version": 1,
        "event": "producer_custody_released",
        "job_id": "job-1",
        "attempt": 1,
        "custody": _custody(),
        "bound_at": "2026-07-29T07:32:00+00:00",
        "drain_confirmed": True,
        "drain_confirmed_at": "2026-07-29T07:33:00+00:00",
        "released_at": "2026-07-29T07:33:00+00:00",
    }


def test_malformed_ledger_fails_closed_for_read_bind_and_release(
    tmp_path: Path,
) -> None:
    _ledger(tmp_path).parent.mkdir(parents=True)
    original = b'{"schema_version":1,"event":'
    _ledger(tmp_path).write_bytes(original)

    with pytest.raises(custody_receipt.CustodyLedgerInvalid):
        custody_receipt.read_pending_producer_custodies(tmp_path)
    with pytest.raises(custody_receipt.CustodyLedgerInvalid):
        custody_receipt.bind_producer_custody(
            tmp_path,
            job_id="job-1",
            attempt=1,
            custody=_custody(),
        )
    with pytest.raises(custody_receipt.CustodyLedgerInvalid):
        custody_receipt.release_producer_custody(
            tmp_path,
            job_id="job-1",
            attempt=1,
            drain_confirmed=True,
        )
    assert _ledger(tmp_path).read_bytes() == original


def test_null_timestamp_and_io_failure_are_not_misread_as_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ledger(tmp_path).parent.mkdir(parents=True)
    _ledger(tmp_path).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event": "producer_custody_bound",
                "job_id": "job-1",
                "attempt": 1,
                "custody": _custody(),
                "bound_at": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(custody_receipt.CustodyLedgerInvalid):
        custody_receipt.read_pending_producer_custodies(tmp_path)

    _ledger(tmp_path).write_bytes(b"")
    real_open = Path.open

    def unavailable_open(path: Path, *args, **kwargs):
        if path == _ledger(tmp_path):
            raise OSError("simulated read failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unavailable_open)
    with pytest.raises(custody_receipt.CustodyLedgerUnavailable):
        custody_receipt.read_pending_producer_custodies(tmp_path)


def test_wrong_generation_key_cannot_release_an_existing_binding(
    tmp_path: Path,
) -> None:
    custody_receipt.initialize_producer_custody_ledger(
        tmp_path,
        migration_confirmed_quiescent=True,
    )
    assert custody_receipt.bind_producer_custody(
        tmp_path,
        job_id="job-1",
        attempt=1,
        custody=_custody(),
    )

    assert not custody_receipt.release_producer_custody(
        tmp_path,
        job_id="job-1",
        attempt=2,
        drain_confirmed=True,
    )
    assert [
        (row["job_id"], row["attempt"])
        for row in custody_receipt.read_pending_producer_custodies(tmp_path)
    ] == [("job-1", 1)]
    assert len(_lines(tmp_path)) == 1


def test_released_generation_is_terminal_and_cannot_be_rebound(
    tmp_path: Path,
) -> None:
    custody_receipt.initialize_producer_custody_ledger(
        tmp_path,
        migration_confirmed_quiescent=True,
    )
    assert custody_receipt.bind_producer_custody(
        tmp_path,
        job_id="job-terminal",
        attempt=1,
        custody=_custody(),
    )
    assert custody_receipt.release_producer_custody(
        tmp_path,
        job_id="job-terminal",
        attempt=1,
        drain_confirmed=True,
    )

    with pytest.raises(custody_receipt.CustodyBindingConflict):
        custody_receipt.bind_producer_custody(
            tmp_path,
            job_id="job-terminal",
            attempt=1,
            custody=_custody(),
        )


def test_ledger_initialization_requires_explicit_quiescence(
    tmp_path: Path,
) -> None:
    with pytest.raises(custody_receipt.CustodyDrainUnconfirmed):
        custody_receipt.initialize_producer_custody_ledger(
            tmp_path,
            migration_confirmed_quiescent=False,
        )
    assert not _ledger(tmp_path).exists()

    assert custody_receipt.initialize_producer_custody_ledger(
        tmp_path,
        migration_confirmed_quiescent=True,
    )
    assert custody_receipt.read_pending_producer_custodies(tmp_path) == []
    assert not custody_receipt.initialize_producer_custody_ledger(
        tmp_path,
        migration_confirmed_quiescent=True,
    )


def test_reconcile_releases_only_after_positive_kernel_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    custody_receipt.initialize_producer_custody_ledger(
        tmp_path,
        migration_confirmed_quiescent=True,
    )
    assert custody_receipt.bind_producer_custody(
        tmp_path,
        job_id="job-recover",
        attempt=1,
        custody=_custody(),
    )
    monkeypatch.setattr(
        "scripts.dispatch_supervisor.procutil.producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [],
    )

    result = custody_receipt.reconcile_pending_producer_custodies(tmp_path)

    assert result["ok"] is True
    assert result["released"] == [{"job_id": "job-recover", "attempt": 1}]
    assert custody_receipt.read_pending_producer_custodies(tmp_path) == []
