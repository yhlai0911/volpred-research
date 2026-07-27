from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from volpred.ops.execution.probe import (
    DurableProviderProbeLedger,
    ProbeOutcome,
    ProbePolicyError,
)
from volpred.ops.execution.registry import DEFAULT_REGISTRY_PATH

T0 = datetime(2026, 7, 27, 14, 0, tzinfo=UTC)


class Clock:
    def __init__(self, value: datetime = T0) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def portable_registry(tmp_path: Path) -> Path:
    payload = json.loads(DEFAULT_REGISTRY_PATH.read_text())
    executable = Path(sys.executable).resolve()
    executable_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
    for provider in payload["providers"]:
        provider["executables"] = [
            {"realpath": str(executable), "sha256": executable_sha}
        ]
    path = tmp_path / "provider_registry.json"
    path.write_text(json.dumps(payload, sort_keys=True))
    return path


def _ledger(
    tmp_path: Path,
    portable_registry: Path,
    clock: Clock,
) -> DurableProviderProbeLedger:
    return DurableProviderProbeLedger(
        path=tmp_path / "provider_probe_ledger.json",
        registry_path=portable_registry,
        clock=clock,
        token_factory=lambda: f"token-{clock.value.timestamp():.0f}",
    )


def _reserve(
    ledger: DurableProviderProbeLedger,
    *,
    environment: dict[str, str] | None = None,
):
    return ledger.reserve(
        provider_id="codex-cli",
        model_id="gpt-5.6-sol",
        executable_path=sys.executable,
        environment=environment or {},
    )


def test_quota_observations_back_off_and_bind_actual_identity(
    tmp_path: Path,
    portable_registry: Path,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)

    first = _reserve(ledger)
    assert first.acquired is True
    receipt1 = ledger.settle(
        token=first.token,
        outcome=ProbeOutcome.QUOTA_BLOCKED,
        evidence_ref="probe://codex/quota/1",
    )
    assert receipt1.provider_id == "codex-cli"
    assert receipt1.model_id == "gpt-5.6-sol"
    assert receipt1.executable_realpath == str(Path(sys.executable).resolve())
    assert receipt1.executable_sha256 == hashlib.sha256(
        Path(sys.executable).resolve().read_bytes()
    ).hexdigest()
    assert receipt1.registry_sha256 == first.registry_sha256
    assert receipt1.cost_units == 1
    assert receipt1.consecutive_failures == 1
    assert receipt1.next_probe_at == T0 + timedelta(minutes=5)

    clock.value = receipt1.next_probe_at
    second = _reserve(ledger)
    receipt2 = ledger.settle(
        token=second.token,
        outcome=ProbeOutcome.QUOTA_BLOCKED,
        evidence_ref="probe://codex/quota/2",
    )
    assert receipt2.consecutive_failures == 2
    assert receipt2.next_probe_at == clock.value + timedelta(minutes=10)
    assert receipt2.previous_receipt_sha256 == receipt1.receipt_sha256


def test_backoff_saturates_at_registry_maximum_without_reset_clock_guessing(
    tmp_path: Path,
    portable_registry: Path,
) -> None:
    payload = json.loads(portable_registry.read_text())
    payload["probe_policy"]["max_probe_cost_units"] = 100
    portable_registry.write_text(json.dumps(payload, sort_keys=True))
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)
    delays: list[timedelta] = []

    for index in range(6):
        reservation = _reserve(ledger)
        assert reservation.acquired is True
        receipt = ledger.settle(
            token=reservation.token,
            outcome=ProbeOutcome.QUOTA_BLOCKED,
            evidence_ref=f"probe://codex/quota/{index}",
        )
        delays.append(receipt.next_probe_at - clock.value)
        clock.value = receipt.next_probe_at

    assert delays == [
        timedelta(minutes=5),
        timedelta(minutes=10),
        timedelta(minutes=20),
        timedelta(minutes=40),
        timedelta(hours=1),
        timedelta(hours=1),
    ]


@pytest.mark.parametrize(
    "outcome",
    [
        ProbeOutcome.HEALTHY,
        ProbeOutcome.QUOTA_BLOCKED,
        ProbeOutcome.AUTH_BLOCKED,
        ProbeOutcome.PROVIDER_UNAVAILABLE,
        ProbeOutcome.POLICY_DENIED,
    ],
)
def test_outcome_vocabulary_is_typed_and_durable(
    tmp_path: Path,
    portable_registry: Path,
    outcome: ProbeOutcome,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)
    reservation = _reserve(ledger)

    receipt = ledger.settle(
        token=reservation.token,
        outcome=outcome,
        evidence_ref=f"probe://codex/{outcome.value}",
    )

    reloaded = _ledger(tmp_path, portable_registry, clock)
    assert reloaded.receipts() == (receipt,)
    assert reloaded.provider_state("codex-cli").outcome is outcome


def test_minimum_interval_and_rolling_budget_are_fail_closed(
    tmp_path: Path,
    portable_registry: Path,
) -> None:
    payload = json.loads(portable_registry.read_text())
    payload["probe_policy"]["max_probe_cost_units"] = 3
    for provider in payload["providers"]:
        if provider["provider_id"] == "codex-cli":
            provider["probe_cost_units"] = 2
    portable_registry.write_text(json.dumps(payload, sort_keys=True))
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)

    first = _reserve(ledger)
    receipt = ledger.settle(
        token=first.token,
        outcome=ProbeOutcome.HEALTHY,
        evidence_ref="probe://codex/healthy",
    )

    too_soon = _reserve(ledger)
    assert too_soon.acquired is False
    assert too_soon.reason == "minimum_interval"
    assert too_soon.next_probe_at == receipt.next_probe_at

    clock.value = receipt.next_probe_at
    over_budget = _reserve(ledger)
    assert over_budget.acquired is False
    assert over_budget.reason == "budget_exhausted"
    assert over_budget.next_probe_at == T0 + timedelta(hours=1)

    clock.value = T0 + timedelta(hours=1)
    reset = _reserve(ledger)
    assert reset.acquired is True


def test_crashed_reservation_is_recovered_only_after_durable_expiry(
    tmp_path: Path,
    portable_registry: Path,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)
    abandoned = _reserve(ledger)

    concurrent = _reserve(_ledger(tmp_path, portable_registry, clock))
    assert concurrent.acquired is False
    assert concurrent.reason == "probe_in_progress"

    clock.value += timedelta(minutes=5)
    recovered = _reserve(ledger)
    assert recovered.acquired is True
    assert recovered.token != abandoned.token
    with pytest.raises(ProbePolicyError, match="reservation"):
        ledger.settle(
            token=abandoned.token,
            outcome=ProbeOutcome.HEALTHY,
            evidence_ref="probe://stale",
        )


def test_atomic_replace_failure_preserves_last_verified_ledger(
    tmp_path: Path,
    portable_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)
    first = _reserve(ledger)
    receipt = ledger.settle(
        token=first.token,
        outcome=ProbeOutcome.HEALTHY,
        evidence_ref="probe://codex/healthy",
    )
    before = ledger.path.read_bytes()
    clock.value = receipt.next_probe_at

    from volpred.ops.execution import probe

    monkeypatch.setattr(
        probe.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("injected replace crash")),
    )
    with pytest.raises(OSError, match="injected"):
        _reserve(ledger)

    assert ledger.path.read_bytes() == before
    assert _ledger(tmp_path, portable_registry, clock).receipts() == (receipt,)


def test_registry_is_reloaded_before_each_reservation(
    tmp_path: Path,
    portable_registry: Path,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)
    first = _reserve(ledger)
    settled = ledger.settle(
        token=first.token,
        outcome=ProbeOutcome.HEALTHY,
        evidence_ref="probe://codex/healthy",
    )

    payload = json.loads(portable_registry.read_text())
    payload["probe_policy"]["max_probe_cost_units"] = 1
    portable_registry.write_text(json.dumps(payload, sort_keys=True))
    clock.value = settled.next_probe_at

    decision = _reserve(ledger)
    assert decision.acquired is False
    assert decision.reason == "budget_exhausted"
    assert decision.registry_sha256 != settled.registry_sha256


def test_alternate_auth_is_denied_before_probe_callback(
    tmp_path: Path,
    portable_registry: Path,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)
    called = False

    def perform_probe(_reservation):
        nonlocal called
        called = True
        raise AssertionError("provider I/O must not happen")

    result = ledger.run(
        provider_id="codex-cli",
        model_id="gpt-5.6-sol",
        executable_path=sys.executable,
        environment={"OPENAI_API_KEY": "sentinel"},
        perform_probe=perform_probe,
    )

    assert called is False
    assert result.outcome is ProbeOutcome.POLICY_DENIED
    assert result.provider_io_attempted is False
    assert result.receipt is not None
    assert result.receipt.registry_sha256 == hashlib.sha256(
        portable_registry.read_bytes()
    ).hexdigest()
    assert ledger.policy_denials() == (result.receipt,)

    replay = ledger.run(
        provider_id="codex-cli",
        model_id="gpt-5.6-sol",
        executable_path=sys.executable,
        environment={"OPENAI_API_KEY": "sentinel"},
        perform_probe=perform_probe,
    )
    assert replay.receipt == result.receipt
    assert ledger.policy_denials() == (result.receipt,)


def test_corrupt_or_truncated_ledger_never_resets_budget(
    tmp_path: Path,
    portable_registry: Path,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)
    reservation = _reserve(ledger)
    ledger.settle(
        token=reservation.token,
        outcome=ProbeOutcome.HEALTHY,
        evidence_ref="probe://codex/healthy",
    )
    payload = json.loads(ledger.path.read_text())
    payload["receipts"][0]["cost_units"] = 0
    ledger.path.write_text(json.dumps(payload))

    with pytest.raises(ProbePolicyError, match="hash|ledger"):
        _reserve(ledger)
