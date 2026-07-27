from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from volpred.ops.execution.probe import (
    DurableProviderProbeLedger,
    ProbeAdmission,
    ProbeObservation,
    ProbeOutcome,
    ProbePolicyError,
)

T0 = datetime(2026, 7, 27, 14, 0, tzinfo=UTC)


class Clock:
    def __init__(self, value: datetime = T0) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def portable_registry(tmp_path: Path) -> Path:
    executable = Path(sys.executable).resolve()
    executable_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
    forbidden_env = [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_BEDROCK_BASE_URL",
        "ANTHROPIC_CUSTOM_HEADERS",
        "ANTHROPIC_FOUNDRY_API_KEY",
        "ANTHROPIC_FOUNDRY_BASE_URL",
        "ANTHROPIC_VERTEX_BASE_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_PROFILE",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_SKIP_BEDROCK_AUTH",
        "CLAUDE_CODE_SKIP_VERTEX_AUTH",
        "CODEX_API_KEY",
        "CODEX_HOME",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_ORGANIZATION",
    ]
    payload = {
        "schema_version": "provider-registry.v1",
        "probe_policy": {
            "minimum_interval_seconds": 300,
            "maximum_backoff_seconds": 3600,
            "window_seconds": 3600,
            "max_probe_cost_units": 6,
            "reservation_ttl_seconds": 120,
        },
        "providers": [
            {
                "provider_id": "codex-cli",
                "executables": [
                    {
                        "realpath": str(executable),
                        "sha256": executable_sha,
                    }
                ],
                "model_ids": ["gpt-5.6-sol"],
                "auth": {
                    "surface": "desktop_subscription",
                    "api_key_env": None,
                    "auto_reload": False,
                    "settings_surface": None,
                    "forbidden_env": forbidden_env,
                },
                "billing": {
                    "mode": "subscription_included",
                    "metered": False,
                    "uses_credits": False,
                    "paid_overflow": False,
                },
                "semantic_classes": ["agentic-execution"],
                "capabilities": ["filesystem", "shell"],
                "attestations": ["subscription-authenticated", "zero-paid"],
                "formal_gate_eligible": False,
                "enabled": True,
                "probe_cost_units": 1,
                "health_state": {
                    "initial": "unknown",
                    "probe_required": True,
                },
            }
        ],
    }
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


def _run(
    ledger: DurableProviderProbeLedger,
    *,
    outcome: ProbeOutcome = ProbeOutcome.HEALTHY,
    evidence_ref: str = "probe://codex/healthy",
    environment: dict[str, str] | None = None,
    perform_probe=None,
):
    callback = perform_probe or (
        lambda _reservation: ProbeObservation(
            outcome=outcome,
            evidence_ref=evidence_ref,
        )
    )
    return ledger.run(
        provider_id="codex-cli",
        model_id="gpt-5.6-sol",
        executable_path=sys.executable,
        environment=environment or {},
        perform_probe=callback,
    )


def test_quota_observations_back_off_and_bind_actual_identity(
    tmp_path: Path,
    portable_registry: Path,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)

    first = _run(
        ledger,
        outcome=ProbeOutcome.QUOTA_BLOCKED,
        evidence_ref="probe://codex/quota/1",
    )
    assert first.admission is ProbeAdmission.ACQUIRED
    assert first.receipt is not None
    receipt1 = first.receipt
    assert receipt1.provider_id == "codex-cli"
    assert receipt1.model_id == "gpt-5.6-sol"
    assert receipt1.executable_realpath == str(Path(sys.executable).resolve())
    assert receipt1.executable_sha256 == hashlib.sha256(
        Path(sys.executable).resolve().read_bytes()
    ).hexdigest()
    assert receipt1.registry_sha256 == hashlib.sha256(
        portable_registry.read_bytes()
    ).hexdigest()
    assert receipt1.cost_units == 1
    assert receipt1.consecutive_failures == 1
    assert receipt1.next_probe_at == T0 + timedelta(minutes=5)

    backed_off = _run(
        ledger,
        perform_probe=lambda _reservation: pytest.fail(
            "backoff must precede provider I/O"
        ),
    )
    assert backed_off.admission is ProbeAdmission.BACKOFF
    assert backed_off.outcome is None

    clock.value = receipt1.next_probe_at
    second = _run(
        ledger,
        outcome=ProbeOutcome.QUOTA_BLOCKED,
        evidence_ref="probe://codex/quota/2",
    )
    assert second.receipt is not None
    receipt2 = second.receipt
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
        result = _run(
            ledger,
            outcome=ProbeOutcome.QUOTA_BLOCKED,
            evidence_ref=f"probe://codex/quota/{index}",
        )
        assert result.admission is ProbeAdmission.ACQUIRED
        assert result.receipt is not None
        receipt = result.receipt
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
    result = _run(
        ledger,
        outcome=outcome,
        evidence_ref=f"probe://codex/{outcome.value}",
    )
    assert result.receipt is not None
    receipt = result.receipt

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

    first = _run(ledger)
    assert first.receipt is not None
    receipt = first.receipt

    too_soon = _run(
        ledger,
        perform_probe=lambda _reservation: pytest.fail(
            "minimum interval must precede provider I/O"
        ),
    )
    assert too_soon.admission is ProbeAdmission.MINIMUM_INTERVAL
    assert too_soon.outcome is None
    assert too_soon.reason == "minimum_interval"
    assert too_soon.next_probe_at == receipt.next_probe_at

    clock.value = receipt.next_probe_at
    over_budget = _run(
        ledger,
        perform_probe=lambda _reservation: pytest.fail(
            "budget denial must precede provider I/O"
        ),
    )
    assert over_budget.admission is ProbeAdmission.BUDGET_EXHAUSTED
    assert over_budget.outcome is None
    assert over_budget.reason == "budget_exhausted"
    assert over_budget.next_probe_at == T0 + timedelta(hours=1)

    clock.value = T0 + timedelta(hours=1)
    reset = _run(ledger)
    assert reset.admission is ProbeAdmission.ACQUIRED


def test_crashed_reservation_is_recovered_only_after_durable_expiry(
    tmp_path: Path,
    portable_registry: Path,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)
    class SimulatedProcessCrash(BaseException):
        pass

    with pytest.raises(SimulatedProcessCrash):
        _run(
            ledger,
            perform_probe=lambda _reservation: (_ for _ in ()).throw(
                SimulatedProcessCrash()
            ),
        )

    concurrent = _run(
        _ledger(tmp_path, portable_registry, clock),
        perform_probe=lambda _reservation: pytest.fail(
            "concurrent reservation must precede provider I/O"
        ),
    )
    assert concurrent.admission is ProbeAdmission.PROBE_IN_PROGRESS
    assert concurrent.outcome is None
    assert concurrent.reason == "probe_in_progress"

    clock.value += timedelta(minutes=2)
    ttl_released_but_interval_held = _run(
        ledger,
        perform_probe=lambda _reservation: pytest.fail(
            "reservation TTL must not bypass the minimum interval"
        ),
    )
    assert (
        ttl_released_but_interval_held.admission
        is ProbeAdmission.MINIMUM_INTERVAL
    )
    assert ttl_released_but_interval_held.outcome is None

    clock.value += timedelta(minutes=3)
    recovered = _run(ledger)
    assert recovered.admission is ProbeAdmission.ACQUIRED
    assert recovered.receipt is not None


def test_v1_reservation_shape_remains_readable_without_policy_field(
    tmp_path: Path,
    portable_registry: Path,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)

    class SimulatedProcessCrash(BaseException):
        pass

    with pytest.raises(SimulatedProcessCrash):
        _run(
            ledger,
            perform_probe=lambda _reservation: (_ for _ in ()).throw(
                SimulatedProcessCrash()
            ),
        )

    payload = json.loads(ledger.path.read_text())
    assert "reservation_ttl_seconds" not in payload["reservations"][0]
    reread = _run(
        _ledger(tmp_path, portable_registry, clock),
        perform_probe=lambda _reservation: pytest.fail(
            "existing v1 reservation must remain readable and block provider I/O"
        ),
    )
    assert reread.admission is ProbeAdmission.PROBE_IN_PROGRESS


def test_probe_finishing_after_reservation_ttl_gets_late_receipt(
    tmp_path: Path,
    portable_registry: Path,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)

    def slow_probe(_reservation):
        clock.value += timedelta(minutes=3)
        return ProbeObservation(
            outcome=ProbeOutcome.HEALTHY,
            evidence_ref="probe://codex/slow-healthy",
        )

    result = _run(ledger, perform_probe=slow_probe)

    assert result.admission is ProbeAdmission.ACQUIRED
    assert result.outcome is ProbeOutcome.HEALTHY
    assert result.receipt is not None
    assert result.receipt.evidence_ref == (
        "late+probe://codex/slow-healthy"
    )
    assert result.receipt.observed_at == clock.value


def test_atomic_replace_failure_preserves_last_verified_ledger(
    tmp_path: Path,
    portable_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)
    first = _run(ledger)
    assert first.receipt is not None
    receipt = first.receipt
    before = ledger.path.read_bytes()
    clock.value = receipt.next_probe_at

    from volpred.ops.execution import probe

    monkeypatch.setattr(
        probe.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("injected replace crash")),
    )
    with pytest.raises(OSError, match="injected"):
        _run(ledger)

    assert ledger.path.read_bytes() == before
    assert _ledger(tmp_path, portable_registry, clock).receipts() == (receipt,)


def test_registry_is_reloaded_before_each_reservation(
    tmp_path: Path,
    portable_registry: Path,
) -> None:
    clock = Clock()
    ledger = _ledger(tmp_path, portable_registry, clock)
    first = _run(ledger)
    assert first.receipt is not None
    settled = first.receipt

    payload = json.loads(portable_registry.read_text())
    payload["probe_policy"]["max_probe_cost_units"] = 1
    portable_registry.write_text(json.dumps(payload, sort_keys=True))
    clock.value = settled.next_probe_at

    decision = _run(
        ledger,
        perform_probe=lambda _reservation: pytest.fail(
            "reloaded budget denial must precede provider I/O"
        ),
    )
    assert decision.admission is ProbeAdmission.BUDGET_EXHAUSTED
    assert decision.outcome is None
    assert decision.reason == "budget_exhausted"
    assert hashlib.sha256(portable_registry.read_bytes()).hexdigest() != (
        settled.registry_sha256
    )


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
    assert result.admission is ProbeAdmission.POLICY_DENIED
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
    _run(ledger)
    payload = json.loads(ledger.path.read_text())
    payload["receipts"][0]["cost_units"] = 0
    ledger.path.write_text(json.dumps(payload))

    with pytest.raises(ProbePolicyError, match="hash|ledger"):
        _run(ledger)
