from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from volpred.ops.delivery import (
    AcknowledgementExpectation,
    EffectDelivery,
    EffectRequest,
    EffectRequestConflict,
)


NOW = datetime(2026, 7, 24, 1, 30, tzinfo=timezone.utc)


def _request(**overrides: object) -> EffectRequest:
    request = EffectRequest(
        idempotency_key="effect:work-1:telegram:completion",
        work_item_id="work-1",
        work_item_version=7,
        effect_kind="telegram.message.send",
        target_ref="telegram:owner-chat",
        payload_ref="artifact:completion-message-v1",
        payload_sha256="a" * 64,
        risk="sensitive",
        acknowledgement=AcknowledgementExpectation(
            kind="telegram.message.readback",
            target_ref="telegram:owner-chat",
        ),
        requester_ref="agent:codex-worker",
    )
    return replace(request, **overrides)


def _delivery(*, id_factory=lambda: "effect-1") -> EffectDelivery:
    return EffectDelivery(clock=lambda: NOW, id_factory=id_factory)


def test_request_exposes_immutable_effect_intent_without_delivering() -> None:
    view = _delivery().request(_request())

    assert view.schema_version == "effect-request.v1"
    assert view.id == "effect-1"
    assert view.idempotency_key == "effect:work-1:telegram:completion"
    assert view.work_item_id == "work-1"
    assert view.work_item_version == 7
    assert view.effect_kind == "telegram.message.send"
    assert view.target_ref == "telegram:owner-chat"
    assert view.payload_ref == "artifact:completion-message-v1"
    assert view.payload_sha256 == "a" * 64
    assert view.risk == "sensitive"
    assert view.acknowledgement == AcknowledgementExpectation(
        kind="telegram.message.readback",
        target_ref="telegram:owner-chat",
    )
    assert view.requester_ref == "agent:codex-worker"
    assert len(view.request_sha256) == 64
    assert view.status == "requested"
    assert view.created_at == NOW.isoformat()


def test_inspect_returns_requested_effect() -> None:
    delivery = _delivery()
    requested = delivery.request(_request())

    assert delivery.inspect(requested.id) == requested
    with pytest.raises(ValueError, match="unknown EffectRequest"):
        delivery.inspect("missing")


def test_equivalent_replay_returns_original_effect() -> None:
    delivery = _delivery()
    first = delivery.request(_request())

    replay = _request(
        idempotency_key=" effect:work-1:telegram:completion ",
        work_item_id=" work-1 ",
        effect_kind=" telegram.message.send ",
        target_ref=" telegram:owner-chat ",
        payload_ref=" artifact:completion-message-v1 ",
        risk=" sensitive ",
        acknowledgement=AcknowledgementExpectation(
            kind=" telegram.message.readback ",
            target_ref=" telegram:owner-chat ",
        ),
        requester_ref=" agent:codex-worker ",
    )

    assert delivery.request(replay) is first


@pytest.mark.parametrize("case", range(64))
def test_payload_bound_replay_property_holds_across_distinct_intents(
    case: int,
) -> None:
    delivery = _delivery(id_factory=lambda: f"effect-{case}")
    request = _request(
        idempotency_key=f"effect:property:{case}",
        work_item_id=f"work-{case}",
        work_item_version=case + 1,
        target_ref=f"target:{case}",
        payload_ref=f"artifact:{case}",
        payload_sha256=f"{case:064x}",
        acknowledgement=AcknowledgementExpectation(
            kind="provider.readback",
            target_ref=f"target:{case}",
        ),
    )

    first = delivery.request(request)
    assert delivery.request(request) is first
    with pytest.raises(EffectRequestConflict, match="original payload"):
        delivery.request(
            replace(request, payload_sha256=f"{case + 1:064x}")
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("work_item_id", "work-2"),
        ("work_item_version", 8),
        ("effect_kind", "email.message.send"),
        ("target_ref", "telegram:other-chat"),
        ("payload_ref", "artifact:completion-message-v2"),
        ("payload_sha256", "b" * 64),
        ("risk", "destructive"),
        (
            "acknowledgement",
            AcknowledgementExpectation(
                kind="telegram.message.delivery-status",
                target_ref="telegram:owner-chat",
            ),
        ),
        (
            "acknowledgement",
            AcknowledgementExpectation(
                kind="telegram.message.readback",
                target_ref="telegram:other-chat",
            ),
        ),
        ("requester_ref", "agent:other-worker"),
    ],
)
def test_idempotency_key_is_bound_to_every_semantic_field(
    field: str,
    value: object,
) -> None:
    delivery = _delivery()
    delivery.request(_request())

    with pytest.raises(EffectRequestConflict, match="original payload"):
        delivery.request(_request(**{field: value}))


def test_concurrent_replays_materialize_exactly_one_effect() -> None:
    id_calls = 0

    def next_id() -> str:
        nonlocal id_calls
        id_calls += 1
        return f"effect-{id_calls}"

    delivery = _delivery(id_factory=next_id)
    with ThreadPoolExecutor(max_workers=16) as executor:
        views = tuple(executor.map(delivery.request, [_request()] * 32))

    assert {view.id for view in views} == {"effect-1"}
    assert {view.request_sha256 for view in views} == {
        views[0].request_sha256
    }
    assert id_calls == 1


@pytest.mark.parametrize(
    ("effect_request", "message"),
    [
        (_request(idempotency_key=" "), "idempotency_key"),
        (_request(work_item_id=" "), "work_item_id"),
        (_request(work_item_version=0), "work_item_version"),
        (_request(work_item_version=True), "work_item_version"),
        (_request(effect_kind=" "), "effect_kind"),
        (_request(target_ref=" "), "target_ref"),
        (_request(payload_ref=" "), "payload_ref"),
        (_request(payload_sha256="A" * 64), "payload_sha256"),
        (_request(risk="unknown"), "unsupported effect risk"),
        (
            _request(
                acknowledgement=AcknowledgementExpectation(
                    kind=" ",
                    target_ref="telegram:owner-chat",
                )
            ),
            "acknowledgement kind",
        ),
        (
            _request(
                acknowledgement=AcknowledgementExpectation(
                    kind="telegram.message.readback",
                    target_ref=" ",
                )
            ),
            "acknowledgement target_ref",
        ),
        (_request(requester_ref=" "), "requester_ref"),
    ],
)
def test_request_rejects_incomplete_or_unsupported_contract(
    effect_request: EffectRequest,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _delivery().request(effect_request)


def test_request_rejects_ambiguous_clock_and_duplicate_generated_id() -> None:
    ambiguous = EffectDelivery(
        clock=lambda: datetime(2026, 7, 24, 1, 30),
        id_factory=lambda: "effect-1",
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        ambiguous.request(_request())

    delivery = _delivery()
    delivery.request(_request())
    with pytest.raises(ValueError, match="duplicate EffectRequest id"):
        delivery.request(
            _request(idempotency_key="effect:work-1:telegram:second")
        )
