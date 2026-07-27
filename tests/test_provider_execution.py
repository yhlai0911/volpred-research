from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event, Thread

import pytest

from volpred.ops.execution import (
    BlockerKind,
    ExecutionAttempt,
    ExecutionRequest,
    ProbePolicy,
    ProviderDescriptor,
    ProviderExecution,
    ProviderObservation,
    VerifiedExecutionCheckpoint,
)
from volpred.ops.execution._testing import InMemoryProviderExecutionStore


NOW = datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc)


class FakeProvider:
    def __init__(
        self,
        *,
        probe_outcomes: list[BlockerKind | None] | None = None,
        attempts: list[ExecutionAttempt] | None = None,
    ) -> None:
        self.probe_outcomes = list(probe_outcomes or [None])
        self.attempts = list(
            attempts
            or [
                ExecutionAttempt(
                    kind="completed",
                    result_ref="result://ok",
                    evidence_ref="receipt://ok",
                )
            ]
        )
        self.probe_calls = 0
        self.execute_calls: list[
            tuple[ExecutionRequest, VerifiedExecutionCheckpoint | None]
        ] = []

    def probe(self, descriptor: ProviderDescriptor, *, observed_at: datetime):
        self.probe_calls += 1
        blocker = self.probe_outcomes.pop(0)
        return ProviderObservation(
            provider_id=descriptor.provider_id,
            observed_at=observed_at,
            blocker=blocker,
            evidence_ref=f"probe://{descriptor.provider_id}/{self.probe_calls}",
        )

    def execute(
        self,
        request: ExecutionRequest,
        *,
        resume_checkpoint: VerifiedExecutionCheckpoint | None,
    ) -> ExecutionAttempt:
        self.execute_calls.append((request, resume_checkpoint))
        return self.attempts.pop(0)


def descriptor(
    provider_id: str,
    *,
    semantic_classes: frozenset[str] = frozenset({"code-change"}),
    capabilities: frozenset[str] = frozenset({"python"}),
    attestations: frozenset[str] = frozenset({"zero-paid"}),
    auth_surface: str = "subscription_oauth",
    metered_paid: bool = False,
    api_key_env: str | None = None,
) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        semantic_classes=semantic_classes,
        capabilities=capabilities,
        attestations=attestations,
        auth_surface=auth_surface,
        metered_paid=metered_paid,
        api_key_env=api_key_env,
        probe_cost_units=1,
    )


def request(
    *,
    key: str = "work-1:attempt",
    semantic_class: str = "code-change",
    checkpoint: VerifiedExecutionCheckpoint | None = None,
) -> ExecutionRequest:
    return ExecutionRequest(
        idempotency_key=key,
        work_id="work-1",
        semantic_class=semantic_class,
        required_capabilities=frozenset({"python"}),
        required_attestations=frozenset({"zero-paid"}),
        payload_ref="payload://work-1",
        resume_checkpoint=checkpoint,
    )


def engine(
    providers: list[tuple[ProviderDescriptor, FakeProvider]],
    *,
    clock=lambda: NOW,
    policy: ProbePolicy | None = None,
) -> ProviderExecution:
    return ProviderExecution(
        providers=providers,
        store=InMemoryProviderExecutionStore(),
        clock=clock,
        probe_policy=policy or ProbePolicy(),
    )


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"metered_paid": True}, "metered-paid"),
        ({"api_key_env": "ANTHROPIC_API_KEY"}, "API-key"),
        ({"auth_surface": "api_key"}, "subscription/OAuth"),
    ],
)
def test_startup_rejects_any_paid_or_api_key_provider(patch, message) -> None:
    base = descriptor("bad")
    with pytest.raises(ValueError, match=message):
        engine([(replace(base, **patch), FakeProvider())])


def test_selection_rejects_non_equivalent_provider_without_probing_it() -> None:
    adapter = FakeProvider()
    execution = engine(
        [
            (
                descriptor(
                    "article-writer",
                    semantic_classes=frozenset({"article-writing"}),
                ),
                adapter,
            )
        ]
    )

    outcome = execution.execute(request())

    assert outcome.kind == "blocked"
    assert outcome.blocker == BlockerKind.POLICY_DENIAL
    assert adapter.probe_calls == 0
    assert adapter.execute_calls == []


@pytest.mark.parametrize(
    "blocker",
    [
        BlockerKind.QUOTA,
        BlockerKind.AUTH,
        BlockerKind.PROVIDER_UNAVAILABLE,
        BlockerKind.POLICY_DENIAL,
    ],
)
def test_probe_preserves_typed_blocker(blocker: BlockerKind) -> None:
    execution = engine(
        [(descriptor("claude"), FakeProvider(probe_outcomes=[blocker]))]
    )

    outcome = execution.execute(request())

    assert outcome.kind == "blocked"
    assert outcome.blocker == blocker
    assert outcome.evidence_refs == ("probe://claude/1",)


def test_probe_is_bounded_by_minimum_interval_and_exponential_backoff() -> None:
    now = NOW

    def clock() -> datetime:
        return now

    adapter = FakeProvider(
        probe_outcomes=[BlockerKind.QUOTA, BlockerKind.QUOTA, None]
    )
    execution = engine(
        [(descriptor("claude"), adapter)],
        clock=clock,
        policy=ProbePolicy(
            minimum_interval=timedelta(minutes=5),
            maximum_backoff=timedelta(minutes=20),
            window=timedelta(hours=1),
            max_probe_cost_units=2,
        ),
    )

    first = execution.execute(request(key="first"))
    immediate = execution.execute(request(key="immediate"))
    now += timedelta(minutes=5)
    second = execution.execute(request(key="second"))
    now += timedelta(minutes=9)
    still_backing_off = execution.execute(request(key="still-backing-off"))

    assert first.blocker == BlockerKind.QUOTA
    assert immediate.blocker == BlockerKind.QUOTA
    assert second.blocker == BlockerKind.QUOTA
    assert still_backing_off.blocker == BlockerKind.QUOTA
    assert adapter.probe_calls == 2

    now += timedelta(minutes=51)
    recovered = execution.execute(request(key="recovered"))
    assert recovered.kind == "completed"
    assert adapter.probe_calls == 3


def test_equivalent_allowlisted_provider_reroutes_after_quota() -> None:
    claude = FakeProvider(probe_outcomes=[BlockerKind.QUOTA])
    codex = FakeProvider()
    execution = engine(
        [
            (descriptor("claude"), claude),
            (descriptor("codex"), codex),
        ]
    )

    outcome = execution.execute(request())

    assert outcome.kind == "completed"
    assert outcome.provider_id == "codex"
    assert claude.execute_calls == []
    assert len(codex.execute_calls) == 1
    assert outcome.evidence_refs == (
        "probe://claude/1",
        "probe://codex/1",
        "receipt://ok",
    )


def test_resume_passes_exact_verified_checkpoint_to_recovered_provider() -> None:
    checkpoint = VerifiedExecutionCheckpoint(
        checkpoint_id="checkpoint-1",
        artifact_ref="artifact://checkpoint-1",
        artifact_sha256="a" * 64,
        verification_ref="pytest://checkpoint-1",
    )
    adapter = FakeProvider()
    execution = engine([(descriptor("codex"), adapter)])

    outcome = execution.execute(request(checkpoint=checkpoint))

    assert outcome.kind == "completed"
    assert adapter.execute_calls == [(request(checkpoint=checkpoint), checkpoint)]
    assert outcome.resume_checkpoint_id == "checkpoint-1"


def test_invalid_checkpoint_cannot_be_presented_as_verified() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        VerifiedExecutionCheckpoint(
            checkpoint_id="checkpoint-1",
            artifact_ref="artifact://checkpoint-1",
            artifact_sha256="not-a-sha",
            verification_ref="pytest://checkpoint-1",
        )


def test_candidate_effect_replay_is_exact_once_and_adapter_has_no_effect_api() -> None:
    adapter = FakeProvider(
        attempts=[
            ExecutionAttempt(
                kind="candidate_effect_request",
                result_ref="effect-request://immutable-1",
                evidence_ref="receipt://candidate-1",
            )
        ]
    )
    execution = engine([(descriptor("codex"), adapter)])
    original = request()

    first = execution.execute(original)
    replay = execution.execute(original)

    assert first == replay
    assert first.kind == "candidate_effect_request"
    assert len(adapter.execute_calls) == 1
    assert not hasattr(adapter, "commit")
    assert not hasattr(adapter, "send")


def test_idempotency_key_conflict_fails_closed_before_provider_io() -> None:
    adapter = FakeProvider()
    execution = engine([(descriptor("codex"), adapter)])
    execution.execute(request())

    with pytest.raises(ValueError, match="idempotency"):
        execution.execute(replace(request(), payload_ref="payload://different"))

    assert len(adapter.execute_calls) == 1


def test_observe_requires_real_evidence_and_never_accepts_reset_time() -> None:
    execution = engine([(descriptor("claude"), FakeProvider())])

    with pytest.raises(ValueError, match="evidence"):
        execution.observe(
            ProviderObservation(
                provider_id="claude",
                observed_at=NOW,
                blocker=BlockerKind.QUOTA,
                evidence_ref="",
            )
        )

    assert "reset" not in ProviderObservation.__dataclass_fields__


def test_runtime_rejects_string_blockers_despite_python_type_erasure() -> None:
    with pytest.raises(ValueError, match="BlockerKind"):
        ProviderObservation(
            provider_id="claude",
            observed_at=NOW,
            blocker="quota",  # type: ignore[arg-type]
            evidence_ref="probe://bad",
        )
    with pytest.raises(ValueError, match="BlockerKind"):
        ExecutionAttempt(
            kind="blocked",
            result_ref=None,
            evidence_ref="attempt://bad",
            blocker="quota",  # type: ignore[arg-type]
        )


def test_concurrent_same_idempotency_key_executes_provider_once() -> None:
    entered = Event()
    release = Event()

    class BlockingProvider(FakeProvider):
        def execute(self, request, *, resume_checkpoint):
            self.execute_calls.append((request, resume_checkpoint))
            entered.set()
            assert release.wait(timeout=2)
            return ExecutionAttempt(
                kind="candidate_effect_request",
                result_ref="effect-request://one",
                evidence_ref="attempt://one",
            )

    adapter = BlockingProvider()
    execution = engine(
        [(descriptor("codex"), adapter)],
        policy=ProbePolicy(minimum_interval=timedelta(hours=1)),
    )
    outcomes = []
    first = Thread(target=lambda: outcomes.append(execution.execute(request())))
    first.start()
    assert entered.wait(timeout=2)

    concurrent = execution.execute(request())
    release.set()
    first.join(timeout=2)

    assert concurrent.kind == "blocked"
    assert concurrent.blocker == BlockerKind.EXECUTION_IN_PROGRESS
    assert outcomes[0].kind == "candidate_effect_request"
    assert len(adapter.execute_calls) == 1
    assert execution.execute(request()) == outcomes[0]


def test_concurrent_requests_share_one_atomic_probe_reservation() -> None:
    entered = Event()
    release = Event()

    class BlockingProbeProvider(FakeProvider):
        def probe(self, descriptor, *, observed_at):
            self.probe_calls += 1
            entered.set()
            assert release.wait(timeout=2)
            return ProviderObservation(
                provider_id=descriptor.provider_id,
                observed_at=observed_at,
                blocker=None,
                evidence_ref="probe://one",
            )

    adapter = BlockingProbeProvider()
    execution = engine([(descriptor("codex"), adapter)])
    outcomes = []
    first = Thread(
        target=lambda: outcomes.append(execution.execute(request(key="one")))
    )
    first.start()
    assert entered.wait(timeout=2)

    concurrent = execution.execute(request(key="two"))
    release.set()
    first.join(timeout=2)

    assert concurrent.kind == "blocked"
    assert concurrent.blocker == BlockerKind.PROVIDER_UNAVAILABLE
    assert outcomes[0].kind == "completed"
    assert adapter.probe_calls == 1
    assert len(adapter.execute_calls) == 1


def test_probe_exception_is_typed_and_reroutes_to_equivalent_provider() -> None:
    class BrokenProbe(FakeProvider):
        def probe(self, descriptor, *, observed_at):
            self.probe_calls += 1
            raise OSError("token-redacted outage")

    broken = BrokenProbe()
    healthy = FakeProvider()
    outcome = engine(
        [
            (descriptor("claude"), broken),
            (descriptor("codex"), healthy),
        ]
    ).execute(request())

    assert outcome.kind == "completed"
    assert outcome.provider_id == "codex"
    assert outcome.evidence_refs[0] == "provider-exception://claude/OSError"


def test_execute_exception_is_typed_and_reroutes_to_equivalent_provider() -> None:
    class BrokenExecution(FakeProvider):
        def execute(self, request, *, resume_checkpoint):
            self.execute_calls.append((request, resume_checkpoint))
            raise RuntimeError("provider transport died")

    broken = BrokenExecution()
    healthy = FakeProvider()
    outcome = engine(
        [
            (descriptor("claude"), broken),
            (descriptor("codex"), healthy),
        ]
    ).execute(request())

    assert outcome.kind == "completed"
    assert outcome.provider_id == "codex"
    assert "provider-exception://claude/RuntimeError" in outcome.evidence_refs


def test_stale_and_future_observations_cannot_move_backoff_clock() -> None:
    execution = engine([(descriptor("claude"), FakeProvider())])
    execution.observe(
        ProviderObservation(
            provider_id="claude",
            observed_at=NOW,
            blocker=BlockerKind.QUOTA,
            evidence_ref="probe://current",
        )
    )

    with pytest.raises(ValueError, match="older"):
        execution.observe(
            ProviderObservation(
                provider_id="claude",
                observed_at=NOW - timedelta(seconds=1),
                blocker=None,
                evidence_ref="probe://stale",
            )
        )
    with pytest.raises(ValueError, match="future"):
        execution.observe(
            ProviderObservation(
                provider_id="claude",
                observed_at=NOW + timedelta(seconds=6),
                blocker=None,
                evidence_ref="probe://future",
            )
        )
