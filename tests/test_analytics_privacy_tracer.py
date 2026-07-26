from __future__ import annotations

import pytest

from volpred.analytics import (
    ANALYTICS_EVENT_DICTIONARY,
    AnalyticsEvent,
    AnalyticsPrivacyTracer,
    InMemoryAnalyticsStore,
)


def test_event_dictionary_declares_privacy_and_dedupe_contract() -> None:
    impression = ANALYTICS_EVENT_DICTIONARY["content_impression"]

    assert impression.purpose == "measure first-party content reach"
    assert impression.required_fields == frozenset({"content_id", "surface"})
    assert impression.optional_fields == frozenset({"referrer_class"})
    assert impression.raw_retention_days == 30
    assert impression.identity_contract == "anonymous_or_authenticated"
    assert impression.dedupe_contract == "idempotency_key"

    assert set(ANALYTICS_EVENT_DICTIONARY) == {
        "content_impression",
        "content_click",
        "read_depth",
        "qualified_action",
        "return_visit",
    }
    for definition in ANALYTICS_EVENT_DICTIONARY.values():
        assert definition.purpose
        assert definition.required_fields
        assert definition.raw_retention_days == 30
        assert definition.identity_contract == "anonymous_or_authenticated"
        assert definition.dedupe_contract == "idempotency_key"


def test_record_rejects_fields_outside_the_event_dictionary() -> None:
    tracer = AnalyticsPrivacyTracer(InMemoryAnalyticsStore())

    with pytest.raises(
        ValueError,
        match="undeclared analytics fields: portfolio_position",
    ):
        tracer.record(
            AnalyticsEvent(
                idempotency_key="impression:home:anon-1:2026-07-26",
                kind="content_impression",
                occurred_at="2026-07-26T15:40:00+00:00",
                anonymous_id="anon-1",
                user_id=None,
                properties={
                    "content_id": "article-1",
                    "surface": "home",
                    "portfolio_position": "long",
                },
            )
        )


def test_raw_retention_is_executable_not_only_documented() -> None:
    tracer = AnalyticsPrivacyTracer(InMemoryAnalyticsStore())
    tracer.record(
        AnalyticsEvent(
            idempotency_key="impression:retention:anon-1",
            kind="content_impression",
            occurred_at="2026-06-01T00:00:00+00:00",
            anonymous_id="anon-retention",
            user_id=None,
            properties={"content_id": "article-1", "surface": "home"},
        )
    )

    assert (
        tracer.purge_expired(before="2026-06-30T23:59:59+00:00") == 0
    )
    assert tracer.purge_expired(before="2026-07-01T00:00:00+00:00") == 1
    assert tracer.inspect_privacy("anonymous:anon-retention").raw_event_count == 0


def test_identity_merge_is_replay_safe_and_admin_summary_is_aggregate_only() -> None:
    tracer = AnalyticsPrivacyTracer(InMemoryAnalyticsStore())
    event = AnalyticsEvent(
        idempotency_key="impression:home:anon-1:2026-07-26",
        kind="content_impression",
        occurred_at="2026-07-26T15:40:00+00:00",
        anonymous_id="anon-1",
        user_id=None,
        properties={"content_id": "article-1", "surface": "home"},
    )

    first = tracer.record(event)
    replay = tracer.record(event)
    merged = tracer.merge_identity(
        idempotency_key="identity-merge:anon-1:user-1",
        anonymous_id="anon-1",
        user_id="user-1",
        merged_at="2026-07-26T15:45:00+00:00",
    )
    merge_replay = tracer.merge_identity(
        idempotency_key="identity-merge:anon-1:user-1",
        anonymous_id="anon-1",
        user_id="user-1",
        merged_at="2026-07-26T15:45:00+00:00",
    )

    assert first.duplicate is False
    assert replay.duplicate is True
    assert replay.event_id == first.event_id
    assert merged.merged_events == 1
    assert merged.duplicate is False
    assert merge_replay.duplicate is True
    assert tracer.admin_summary(
        start_at="2026-07-26T00:00:00+00:00",
        end_at="2026-07-27T00:00:00+00:00",
    ) == (
        {
            "event_kind": "content_impression",
            "event_count": 1,
        },
    )


def test_opt_out_suppresses_linked_identity_and_all_admin_projections() -> None:
    tracer = AnalyticsPrivacyTracer(InMemoryAnalyticsStore())
    tracer.record(
        AnalyticsEvent(
            idempotency_key="impression:home:anon-1:2026-07-26",
            kind="content_impression",
            occurred_at="2026-07-26T15:40:00+00:00",
            anonymous_id="anon-1",
            user_id=None,
            properties={"content_id": "article-1", "surface": "home"},
        )
    )
    tracer.merge_identity(
        idempotency_key="identity-merge:anon-1:user-1",
        anonymous_id="anon-1",
        user_id="user-1",
        merged_at="2026-07-26T15:45:00+00:00",
    )

    opted_out = tracer.set_opt_out(
        "user:user-1",
        idempotency_key="privacy:opt-out:user-1",
        acted_at="2026-07-26T15:50:00+00:00",
    )
    suppressed = tracer.record(
        AnalyticsEvent(
            idempotency_key="click:article-1:anon-1",
            kind="content_click",
            occurred_at="2026-07-26T15:55:00+00:00",
            anonymous_id="anon-1",
            user_id=None,
            properties={"content_id": "article-1", "surface": "article"},
        )
    )

    assert opted_out.action == "opt_out"
    assert opted_out.duplicate is False
    assert suppressed.accepted is False
    assert suppressed.reason == "opted_out"
    assert tracer.admin_summary(
        start_at="2026-07-26T00:00:00+00:00",
        end_at="2026-07-27T00:00:00+00:00",
    ) == ()
    assert tracer.inspect_privacy("anonymous:anon-1") == tracer.inspect_privacy(
        "user:user-1"
    )
    assert tracer.inspect_privacy("user:user-1").opted_out is True
    assert tracer.inspect_privacy("user:user-1").raw_event_count == 1
    assert tracer.inspect_privacy("user:user-1").projected_event_count == 0
    assert tracer.inspect_privacy("user:user-1").identity_link_count == 1


def test_clear_and_delete_are_replay_safe_and_read_back_every_projection() -> None:
    tracer = AnalyticsPrivacyTracer(InMemoryAnalyticsStore())
    event = AnalyticsEvent(
        idempotency_key="impression:home:anon-2:2026-07-26",
        kind="content_impression",
        occurred_at="2026-07-26T16:00:00+00:00",
        anonymous_id="anon-2",
        user_id=None,
        properties={"content_id": "article-2", "surface": "home"},
    )
    tracer.record(event)
    tracer.merge_identity(
        idempotency_key="identity-merge:anon-2:user-2",
        anonymous_id="anon-2",
        user_id="user-2",
        merged_at="2026-07-26T16:05:00+00:00",
    )
    tracer.set_opt_out(
        "user:user-2",
        idempotency_key="privacy:opt-out:user-2",
        acted_at="2026-07-26T16:10:00+00:00",
    )

    cleared = tracer.clear(
        "user:user-2",
        idempotency_key="privacy:clear:user-2",
        acted_at="2026-07-26T16:15:00+00:00",
    )
    clear_replay = tracer.clear(
        "user:user-2",
        idempotency_key="privacy:clear:user-2",
        acted_at="2026-07-26T16:15:00+00:00",
    )
    after_clear = tracer.inspect_privacy("user:user-2")

    assert cleared.removed_raw_events == 1
    assert clear_replay.duplicate is True
    assert after_clear.opted_out is True
    assert after_clear.raw_event_count == 0
    assert after_clear.projected_event_count == 0
    assert after_clear.identity_link_count == 1

    deleted = tracer.delete(
        "user:user-2",
        idempotency_key="privacy:delete:user-2",
        acted_at="2026-07-26T16:20:00+00:00",
    )
    delete_replay = tracer.delete(
        "user:user-2",
        idempotency_key="privacy:delete:user-2",
        acted_at="2026-07-26T16:20:00+00:00",
    )
    after_delete = tracer.inspect_privacy("user:user-2")
    event_replay_after_delete = tracer.record(event)

    assert deleted.removed_identity_links == 1
    assert delete_replay.duplicate is True
    assert after_delete.opted_out is False
    assert after_delete.raw_event_count == 0
    assert after_delete.projected_event_count == 0
    assert after_delete.identity_link_count == 0
    assert event_replay_after_delete.accepted is False
    assert event_replay_after_delete.reason == "deleted"
