"""Privacy boundary for first-party product analytics.

The public tracer validates the event dictionary before an adapter sees data.
Adapters therefore receive only purpose-limited fields and one explicit
idempotency identity.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
from threading import RLock
from collections.abc import Callable
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class AnalyticsEventDefinition:
    purpose: str
    required_fields: frozenset[str]
    optional_fields: frozenset[str]
    raw_retention_days: int
    identity_contract: str
    dedupe_contract: str
    field_contracts: Mapping[str, str]


ANALYTICS_EVENT_DICTIONARY: Mapping[str, AnalyticsEventDefinition] = {
    "content_impression": AnalyticsEventDefinition(
        purpose="measure first-party content reach",
        required_fields=frozenset({"content_id", "surface"}),
        optional_fields=frozenset({"referrer_class"}),
        raw_retention_days=30,
        identity_contract="anonymous_or_authenticated",
        dedupe_contract="idempotency_key",
        field_contracts={
            "content_id": "opaque_identifier",
            "surface": "enum:home|article|search|feed|email",
            "referrer_class": "enum:direct|internal|search|social|email|other",
        },
    ),
    "content_click": AnalyticsEventDefinition(
        purpose="measure first-party content engagement",
        required_fields=frozenset({"content_id", "surface"}),
        optional_fields=frozenset({"target_class"}),
        raw_retention_days=30,
        identity_contract="anonymous_or_authenticated",
        dedupe_contract="idempotency_key",
        field_contracts={
            "content_id": "opaque_identifier",
            "surface": "enum:home|article|search|feed|email",
            "target_class": "enum:article|navigation|cta|external",
        },
    ),
    "read_depth": AnalyticsEventDefinition(
        purpose="measure aggregate content reading depth",
        required_fields=frozenset({"content_id", "depth_bucket"}),
        optional_fields=frozenset({"surface"}),
        raw_retention_days=30,
        identity_contract="anonymous_or_authenticated",
        dedupe_contract="idempotency_key",
        field_contracts={
            "content_id": "opaque_identifier",
            "depth_bucket": "enum:25|50|75|100",
            "surface": "enum:home|article|search|feed|email",
        },
    ),
    "qualified_action": AnalyticsEventDefinition(
        purpose="measure aggregate completion of a declared product action",
        required_fields=frozenset({"content_id", "action"}),
        optional_fields=frozenset({"surface"}),
        raw_retention_days=30,
        identity_contract="anonymous_or_authenticated",
        dedupe_contract="idempotency_key",
        field_contracts={
            "content_id": "opaque_identifier",
            "action": "enum:subscribe|share|save|open_paper|open_experiment",
            "surface": "enum:home|article|search|feed|email",
        },
    ),
    "return_visit": AnalyticsEventDefinition(
        purpose="measure aggregate first-party audience retention",
        required_fields=frozenset({"surface", "return_window"}),
        optional_fields=frozenset(),
        raw_retention_days=30,
        identity_contract="anonymous_or_authenticated",
        dedupe_contract="idempotency_key",
        field_contracts={
            "surface": "enum:home|article|search|feed|email",
            "return_window": "enum:day_1|day_7|day_30",
        },
    ),
}


@dataclass(frozen=True)
class AnalyticsEvent:
    idempotency_key: str
    kind: str
    occurred_at: str
    anonymous_id: str | None
    user_id: str | None
    properties: Mapping[str, Any]

    def canonical_payload_bytes(self) -> bytes:
        occurred_at = datetime.fromisoformat(self.occurred_at)
        canonical = {
            "anonymous_id": self.anonymous_id,
            "kind": self.kind,
            "occurred_at": occurred_at.astimezone(timezone.utc).isoformat(),
            "properties": dict(self.properties),
            "submitted_user_id": self.user_id,
        }
        return json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


@dataclass(frozen=True)
class AnalyticsEventReceipt:
    event_id: str | None
    idempotency_key: str
    accepted: bool
    duplicate: bool
    raw_expires_at: str | None
    reason: str | None = None


@dataclass(frozen=True)
class AnalyticsIdentityMergeReceipt:
    idempotency_key: str
    anonymous_id: str
    user_id: str
    merged_events: int
    duplicate: bool
    merged_at: str


@dataclass(frozen=True)
class AnalyticsPrivacyReadback:
    opted_out: bool
    raw_event_count: int
    projected_event_count: int
    identity_link_count: int


@dataclass(frozen=True)
class AnalyticsPrivacyActionReceipt:
    action: str
    idempotency_key: str
    acted_at: str
    removed_raw_events: int
    removed_identity_links: int
    duplicate: bool


class AnalyticsStore(Protocol):
    def record(
        self,
        event: AnalyticsEvent,
        *,
        raw_expires_at: str,
    ) -> AnalyticsEventReceipt: ...

    def merge_identity(
        self,
        *,
        idempotency_key: str,
        anonymous_id: str,
        user_id: str,
        merged_at: str,
    ) -> AnalyticsIdentityMergeReceipt: ...

    def admin_summary(
        self,
        *,
        start_at: str,
        end_at: str,
    ) -> tuple[dict[str, int | str], ...]: ...

    def set_opt_out(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        idempotency_key: str,
        acted_at: str,
    ) -> AnalyticsPrivacyActionReceipt: ...

    def clear(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        idempotency_key: str,
        acted_at: str,
    ) -> AnalyticsPrivacyActionReceipt: ...

    def delete(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        idempotency_key: str,
        acted_at: str,
    ) -> AnalyticsPrivacyActionReceipt: ...

    def inspect_privacy(
        self,
        *,
        subject_kind: str,
        subject_id: str,
    ) -> AnalyticsPrivacyReadback: ...

    def purge_expired(self, *, before: str) -> int: ...


@dataclass(frozen=True)
class _StoredAnalyticsEvent:
    event_id: str
    event: AnalyticsEvent
    submitted_user_id: str | None
    payload_digest: bytes
    raw_expires_at: str


@dataclass(frozen=True)
class _StoredPrivacyAction:
    receipt: AnalyticsPrivacyActionReceipt
    subject_digest: bytes


class InMemoryAnalyticsStore:
    """Transaction-safe adapter used by the public contract suite."""

    def __init__(self, *, tombstone_secret: bytes) -> None:
        if len(tombstone_secret) < 32:
            raise ValueError(
                "analytics tombstone_secret must contain at least 32 bytes"
            )
        self._lock = RLock()
        self._tombstone_secret = tombstone_secret
        self._events: dict[str, _StoredAnalyticsEvent] = {}
        self._merge_receipts: dict[str, AnalyticsIdentityMergeReceipt] = {}
        self._user_by_anonymous_id: dict[str, str] = {}
        self._opted_out_subjects: set[tuple[str, str]] = set()
        self._privacy_action_receipts: dict[
            str, _StoredPrivacyAction
        ] = {}
        self._deleted_subject_digests: set[bytes] = set()
        self._suppressed_event_keys: dict[bytes, tuple[bytes, str]] = {}
        self._next_event_number = 1

    def record(
        self,
        event: AnalyticsEvent,
        *,
        raw_expires_at: str,
    ) -> AnalyticsEventReceipt:
        with self._lock:
            payload_digest = self._payload_digest(event)
            existing = self._events.get(event.idempotency_key)
            if existing is not None:
                if not hmac.compare_digest(
                    existing.payload_digest, payload_digest
                ):
                    raise ValueError(
                        "analytics event idempotency_key was reused"
                    )
                return AnalyticsEventReceipt(
                    event_id=existing.event_id,
                    idempotency_key=existing.event.idempotency_key,
                    accepted=True,
                    duplicate=True,
                    raw_expires_at=existing.raw_expires_at,
                )
            if self._event_is_deleted(event):
                return AnalyticsEventReceipt(
                    event_id=None,
                    idempotency_key=event.idempotency_key,
                    accepted=False,
                    duplicate=False,
                    raw_expires_at=None,
                    reason="deleted",
                )
            suppression = self._suppressed_event_keys.get(
                self._event_key_digest(event.idempotency_key)
            )
            if suppression is not None:
                suppressed_payload_digest, suppression_reason = suppression
                if not hmac.compare_digest(
                    suppressed_payload_digest, payload_digest
                ):
                    raise ValueError(
                        "analytics event idempotency_key was reused"
                    )
                return AnalyticsEventReceipt(
                    event_id=None,
                    idempotency_key=event.idempotency_key,
                    accepted=False,
                    duplicate=False,
                    raw_expires_at=None,
                    reason=suppression_reason,
                )
            if self._event_is_opted_out(event):
                return AnalyticsEventReceipt(
                    event_id=None,
                    idempotency_key=event.idempotency_key,
                    accepted=False,
                    duplicate=False,
                    raw_expires_at=None,
                    reason="opted_out",
                )
            canonical_user_id = event.user_id
            if event.anonymous_id and canonical_user_id is None:
                canonical_user_id = self._user_by_anonymous_id.get(
                    event.anonymous_id
                )
            elif event.anonymous_id and canonical_user_id is not None:
                linked_user_id = self._user_by_anonymous_id.get(
                    event.anonymous_id
                )
                if (
                    linked_user_id is not None
                    and linked_user_id != canonical_user_id
                ):
                    raise ValueError("conflicting analytics identities")
            submitted_user_id = event.user_id
            if canonical_user_id is not None and event.user_id is None:
                event = replace(event, user_id=canonical_user_id)
            receipt = AnalyticsEventReceipt(
                event_id=f"analytics-event-{self._next_event_number}",
                idempotency_key=event.idempotency_key,
                accepted=True,
                duplicate=False,
                raw_expires_at=raw_expires_at,
            )
            self._next_event_number += 1
            self._events[event.idempotency_key] = _StoredAnalyticsEvent(
                event_id=receipt.event_id,
                event=event,
                submitted_user_id=submitted_user_id,
                payload_digest=payload_digest,
                raw_expires_at=raw_expires_at,
            )
            return receipt

    def _subject_aliases(
        self,
        subject_kind: str,
        subject_id: str,
    ) -> tuple[set[str], set[str]]:
        anonymous_ids: set[str] = set()
        user_ids: set[str] = set()
        if subject_kind == "anonymous":
            anonymous_ids.add(subject_id)
            linked_user = self._user_by_anonymous_id.get(subject_id)
            if linked_user is not None:
                user_ids.add(linked_user)
        else:
            user_ids.add(subject_id)
        if user_ids:
            anonymous_ids.update(
                anonymous_id
                for anonymous_id, user_id in self._user_by_anonymous_id.items()
                if user_id in user_ids
            )
        return anonymous_ids, user_ids

    def _event_matches_subject(
        self,
        event: AnalyticsEvent,
        anonymous_ids: set[str],
        user_ids: set[str],
    ) -> bool:
        return (
            event.anonymous_id in anonymous_ids
            or event.user_id in user_ids
        )

    def _event_is_opted_out(self, event: AnalyticsEvent) -> bool:
        identities = {
            ("anonymous", event.anonymous_id)
            if event.anonymous_id
            else None,
            ("user", event.user_id) if event.user_id else None,
        }
        if any(
            identity in self._opted_out_subjects
            for identity in identities
            if identity is not None
        ):
            return True
        if event.anonymous_id:
            linked_user = self._user_by_anonymous_id.get(event.anonymous_id)
            if ("user", linked_user) in self._opted_out_subjects:
                return True
        if event.user_id:
            return any(
                ("anonymous", anonymous_id) in self._opted_out_subjects
                for anonymous_id, user_id in self._user_by_anonymous_id.items()
                if user_id == event.user_id
            )
        return False

    def _subject_digest(self, subject_kind: str, subject_id: str) -> bytes:
        return self._keyed_digest(
            f"subject:{subject_kind}:{subject_id}".encode("utf-8")
        )

    def _event_key_digest(self, idempotency_key: str) -> bytes:
        return self._keyed_digest(
            f"event-key:{idempotency_key}".encode("utf-8")
        )

    def _payload_digest(self, event: AnalyticsEvent) -> bytes:
        return self._keyed_digest(
            b"event-payload:" + event.canonical_payload_bytes()
        )

    def _keyed_digest(self, value: bytes) -> bytes:
        return hmac.new(
            self._tombstone_secret, value, hashlib.sha256
        ).digest()

    def _event_is_deleted(self, event: AnalyticsEvent) -> bool:
        identities = (
            (("anonymous", event.anonymous_id), ("user", event.user_id))
        )
        return any(
            self._subject_digest(kind, subject_id)
            in self._deleted_subject_digests
            for kind, subject_id in identities
            if subject_id is not None
        )

    def merge_identity(
        self,
        *,
        idempotency_key: str,
        anonymous_id: str,
        user_id: str,
        merged_at: str,
    ) -> AnalyticsIdentityMergeReceipt:
        with self._lock:
            existing = self._merge_receipts.get(idempotency_key)
            if existing is not None:
                if (
                    existing.anonymous_id != anonymous_id
                    or existing.user_id != user_id
                ):
                    raise ValueError(
                        "identity merge idempotency_key was reused"
                    )
                return replace(existing, duplicate=True)
            if any(
                self._subject_digest(kind, subject_id)
                in self._deleted_subject_digests
                for kind, subject_id in (
                    ("anonymous", anonymous_id),
                    ("user", user_id),
                )
            ):
                raise ValueError("cannot merge a deleted analytics identity")
            previous_user = self._user_by_anonymous_id.get(anonymous_id)
            if previous_user is not None and previous_user != user_id:
                raise ValueError(
                    f"anonymous identity already belongs to another user: "
                    f"{anonymous_id}"
                )
            self._user_by_anonymous_id[anonymous_id] = user_id
            merged_events = 0
            for key, stored in tuple(self._events.items()):
                if (
                    stored.event.anonymous_id == anonymous_id
                    and stored.event.user_id != user_id
                ):
                    self._events[key] = replace(
                        stored,
                        event=replace(stored.event, user_id=user_id),
                    )
                    merged_events += 1
            receipt = AnalyticsIdentityMergeReceipt(
                idempotency_key=idempotency_key,
                anonymous_id=anonymous_id,
                user_id=user_id,
                merged_events=merged_events,
                duplicate=False,
                merged_at=merged_at,
            )
            self._merge_receipts[idempotency_key] = receipt
            return receipt

    def admin_summary(
        self,
        *,
        start_at: str,
        end_at: str,
    ) -> tuple[dict[str, int | str], ...]:
        start = datetime.fromisoformat(start_at)
        end = datetime.fromisoformat(end_at)
        with self._lock:
            counts: dict[str, int] = {}
            for stored in self._events.values():
                if self._event_is_opted_out(stored.event):
                    continue
                occurred_at = datetime.fromisoformat(stored.event.occurred_at)
                if start <= occurred_at < end:
                    counts[stored.event.kind] = (
                        counts.get(stored.event.kind, 0) + 1
                    )
            return tuple(
                {
                    "event_kind": event_kind,
                    "event_count": counts[event_kind],
                }
                for event_kind in sorted(counts)
            )

    def _existing_privacy_action(
        self,
        idempotency_key: str,
        *,
        action: str,
        subject_kind: str,
        subject_id: str,
    ) -> AnalyticsPrivacyActionReceipt | None:
        existing = self._privacy_action_receipts.get(idempotency_key)
        if existing is None:
            return None
        if (
            existing.receipt.action != action
            or existing.subject_digest
            != self._subject_digest(subject_kind, subject_id)
        ):
            raise ValueError("privacy action idempotency_key was reused")
        return replace(existing.receipt, duplicate=True)

    def set_opt_out(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        idempotency_key: str,
        acted_at: str,
    ) -> AnalyticsPrivacyActionReceipt:
        with self._lock:
            existing = self._existing_privacy_action(
                idempotency_key,
                action="opt_out",
                subject_kind=subject_kind,
                subject_id=subject_id,
            )
            if existing is not None:
                return existing
            self._opted_out_subjects.add((subject_kind, subject_id))
            receipt = AnalyticsPrivacyActionReceipt(
                action="opt_out",
                idempotency_key=idempotency_key,
                acted_at=acted_at,
                removed_raw_events=0,
                removed_identity_links=0,
                duplicate=False,
            )
            self._privacy_action_receipts[idempotency_key] = (
                _StoredPrivacyAction(
                    receipt=receipt,
                    subject_digest=self._subject_digest(
                        subject_kind, subject_id
                    ),
                )
            )
            return receipt

    def clear(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        idempotency_key: str,
        acted_at: str,
    ) -> AnalyticsPrivacyActionReceipt:
        with self._lock:
            existing = self._existing_privacy_action(
                idempotency_key,
                action="clear",
                subject_kind=subject_kind,
                subject_id=subject_id,
            )
            if existing is not None:
                return existing
            anonymous_ids, user_ids = self._subject_aliases(
                subject_kind, subject_id
            )
            matching_keys = tuple(
                key
                for key, stored in self._events.items()
                if self._event_matches_subject(
                    stored.event, anonymous_ids, user_ids
                )
            )
            for key in matching_keys:
                self._suppressed_event_keys[
                    self._event_key_digest(
                        self._events[key].event.idempotency_key
                    )
                ] = (self._events[key].payload_digest, "cleared")
                del self._events[key]
            receipt = AnalyticsPrivacyActionReceipt(
                action="clear",
                idempotency_key=idempotency_key,
                acted_at=acted_at,
                removed_raw_events=len(matching_keys),
                removed_identity_links=0,
                duplicate=False,
            )
            self._privacy_action_receipts[idempotency_key] = (
                _StoredPrivacyAction(
                    receipt=receipt,
                    subject_digest=self._subject_digest(
                        subject_kind, subject_id
                    ),
                )
            )
            return receipt

    def delete(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        idempotency_key: str,
        acted_at: str,
    ) -> AnalyticsPrivacyActionReceipt:
        with self._lock:
            existing = self._existing_privacy_action(
                idempotency_key,
                action="delete",
                subject_kind=subject_kind,
                subject_id=subject_id,
            )
            if existing is not None:
                return existing
            anonymous_ids, user_ids = self._subject_aliases(
                subject_kind, subject_id
            )
            matching_event_keys = tuple(
                key
                for key, stored in self._events.items()
                if self._event_matches_subject(
                    stored.event, anonymous_ids, user_ids
                )
            )
            for key in matching_event_keys:
                del self._events[key]
            matching_links = tuple(
                anonymous_id
                for anonymous_id, user_id in self._user_by_anonymous_id.items()
                if anonymous_id in anonymous_ids or user_id in user_ids
            )
            for anonymous_id in matching_links:
                del self._user_by_anonymous_id[anonymous_id]
            self._opted_out_subjects.difference_update(
                {("anonymous", value) for value in anonymous_ids}
                | {("user", value) for value in user_ids}
            )
            for key, receipt in tuple(self._merge_receipts.items()):
                if (
                    receipt.anonymous_id in anonymous_ids
                    or receipt.user_id in user_ids
                ):
                    del self._merge_receipts[key]
            self._deleted_subject_digests.update(
                self._subject_digest("anonymous", value)
                for value in anonymous_ids
            )
            self._deleted_subject_digests.update(
                self._subject_digest("user", value)
                for value in user_ids
            )
            deleted_action_digests = {
                self._subject_digest("anonymous", value)
                for value in anonymous_ids
            } | {
                self._subject_digest("user", value)
                for value in user_ids
            }
            for key, stored_action in tuple(
                self._privacy_action_receipts.items()
            ):
                if stored_action.subject_digest in deleted_action_digests:
                    del self._privacy_action_receipts[key]
            receipt = AnalyticsPrivacyActionReceipt(
                action="delete",
                idempotency_key=idempotency_key,
                acted_at=acted_at,
                removed_raw_events=len(matching_event_keys),
                removed_identity_links=len(matching_links),
                duplicate=False,
            )
            self._privacy_action_receipts[idempotency_key] = (
                _StoredPrivacyAction(
                    receipt=receipt,
                    subject_digest=self._subject_digest(
                        subject_kind, subject_id
                    ),
                )
            )
            return receipt

    def inspect_privacy(
        self,
        *,
        subject_kind: str,
        subject_id: str,
    ) -> AnalyticsPrivacyReadback:
        with self._lock:
            anonymous_ids, user_ids = self._subject_aliases(
                subject_kind, subject_id
            )
            matching_events = tuple(
                stored.event
                for stored in self._events.values()
                if self._event_matches_subject(
                    stored.event, anonymous_ids, user_ids
                )
            )
            opted_out = any(
                identity in self._opted_out_subjects
                for identity in (
                    {("anonymous", value) for value in anonymous_ids}
                    | {("user", value) for value in user_ids}
                )
            )
            return AnalyticsPrivacyReadback(
                opted_out=opted_out,
                raw_event_count=len(matching_events),
                projected_event_count=sum(
                    not self._event_is_opted_out(event)
                    for event in matching_events
                ),
                identity_link_count=sum(
                    anonymous_id in anonymous_ids and user_id in user_ids
                    for anonymous_id, user_id
                    in self._user_by_anonymous_id.items()
                ),
            )

    def purge_expired(self, *, before: str) -> int:
        cutoff = datetime.fromisoformat(before)
        with self._lock:
            expired_keys = tuple(
                key
                for key, stored in self._events.items()
                if datetime.fromisoformat(stored.raw_expires_at) <= cutoff
            )
            for key in expired_keys:
                self._suppressed_event_keys[
                    self._event_key_digest(
                        self._events[key].event.idempotency_key
                    )
                ] = (self._events[key].payload_digest, "expired")
                del self._events[key]
            return len(expired_keys)


class AnalyticsPrivacyTracer:
    """Validate and execute the first-party analytics lifecycle."""

    def __init__(
        self,
        store: AnalyticsStore,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _validate_property(
        self,
        field_name: str,
        value: Any,
        contract: str,
    ) -> None:
        if not isinstance(value, str):
            raise ValueError(
                f"analytics field {field_name} must be a string"
            )
        if contract == "opaque_identifier":
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
                raise ValueError(
                    f"analytics field {field_name} has invalid value"
                )
            return
        if contract.startswith("enum:"):
            allowed = frozenset(contract.removeprefix("enum:").split("|"))
            if value not in allowed:
                raise ValueError(
                    f"analytics field {field_name} has invalid value"
                )
            return
        raise RuntimeError(
            f"unknown analytics field contract for {field_name}: {contract}"
        )

    def record(self, event: AnalyticsEvent) -> AnalyticsEventReceipt:
        definition = ANALYTICS_EVENT_DICTIONARY.get(event.kind)
        if definition is None:
            raise ValueError(f"unknown analytics event kind: {event.kind}")
        observed_fields = frozenset(event.properties)
        allowed_fields = definition.required_fields | definition.optional_fields
        undeclared = sorted(observed_fields - allowed_fields)
        if undeclared:
            raise ValueError(
                "undeclared analytics fields: " + ", ".join(undeclared)
            )
        missing = sorted(definition.required_fields - observed_fields)
        if missing:
            raise ValueError(
                "missing required analytics fields: " + ", ".join(missing)
            )
        if frozenset(definition.field_contracts) != allowed_fields:
            raise RuntimeError(
                f"analytics field contracts drifted for {event.kind}"
            )
        for field_name, value in event.properties.items():
            self._validate_property(
                field_name,
                value,
                definition.field_contracts[field_name],
            )
        if not event.idempotency_key.strip():
            raise ValueError("analytics idempotency_key is required")
        if not event.anonymous_id and not event.user_id:
            raise ValueError("analytics event requires an anonymous or user identity")
        occurred_at = datetime.fromisoformat(event.occurred_at)
        if occurred_at.tzinfo is None:
            raise ValueError("analytics occurred_at must be timezone-aware")
        if occurred_at > self._now() + timedelta(minutes=5):
            raise ValueError("analytics occurred_at is too far in the future")
        raw_expires_at = (
            occurred_at + timedelta(days=definition.raw_retention_days)
        ).isoformat()
        return self._store.record(event, raw_expires_at=raw_expires_at)

    def merge_identity(
        self,
        *,
        idempotency_key: str,
        anonymous_id: str,
        user_id: str,
        merged_at: str,
    ) -> AnalyticsIdentityMergeReceipt:
        if not idempotency_key.strip():
            raise ValueError("identity merge idempotency_key is required")
        if not anonymous_id.strip() or not user_id.strip():
            raise ValueError(
                "identity merge requires anonymous_id and user_id"
            )
        observed_at = datetime.fromisoformat(merged_at)
        if observed_at.tzinfo is None:
            raise ValueError("identity merge merged_at must be timezone-aware")
        return self._store.merge_identity(
            idempotency_key=idempotency_key,
            anonymous_id=anonymous_id,
            user_id=user_id,
            merged_at=merged_at,
        )

    def admin_summary(
        self,
        *,
        start_at: str,
        end_at: str,
    ) -> tuple[dict[str, int | str], ...]:
        start = datetime.fromisoformat(start_at)
        end = datetime.fromisoformat(end_at)
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("analytics summary bounds must be timezone-aware")
        if start >= end:
            raise ValueError("analytics summary start_at must precede end_at")
        return self._store.admin_summary(start_at=start_at, end_at=end_at)

    def _privacy_action_inputs(
        self,
        subject_ref: str,
        *,
        idempotency_key: str,
        acted_at: str,
    ) -> tuple[str, str]:
        try:
            subject_kind, subject_id = subject_ref.split(":", maxsplit=1)
        except ValueError as error:
            raise ValueError(
                "analytics subject_ref must be anonymous:<id> or user:<id>"
            ) from error
        if subject_kind not in {"anonymous", "user"} or not subject_id.strip():
            raise ValueError(
                "analytics subject_ref must be anonymous:<id> or user:<id>"
            )
        if not idempotency_key.strip():
            raise ValueError("privacy action idempotency_key is required")
        observed_at = datetime.fromisoformat(acted_at)
        if observed_at.tzinfo is None:
            raise ValueError("privacy action acted_at must be timezone-aware")
        return subject_kind, subject_id

    def set_opt_out(
        self,
        subject_ref: str,
        *,
        idempotency_key: str,
        acted_at: str,
    ) -> AnalyticsPrivacyActionReceipt:
        subject_kind, subject_id = self._privacy_action_inputs(
            subject_ref,
            idempotency_key=idempotency_key,
            acted_at=acted_at,
        )
        return self._store.set_opt_out(
            subject_kind=subject_kind,
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            acted_at=acted_at,
        )

    def clear(
        self,
        subject_ref: str,
        *,
        idempotency_key: str,
        acted_at: str,
    ) -> AnalyticsPrivacyActionReceipt:
        subject_kind, subject_id = self._privacy_action_inputs(
            subject_ref,
            idempotency_key=idempotency_key,
            acted_at=acted_at,
        )
        return self._store.clear(
            subject_kind=subject_kind,
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            acted_at=acted_at,
        )

    def delete(
        self,
        subject_ref: str,
        *,
        idempotency_key: str,
        acted_at: str,
    ) -> AnalyticsPrivacyActionReceipt:
        subject_kind, subject_id = self._privacy_action_inputs(
            subject_ref,
            idempotency_key=idempotency_key,
            acted_at=acted_at,
        )
        return self._store.delete(
            subject_kind=subject_kind,
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            acted_at=acted_at,
        )

    def inspect_privacy(
        self,
        subject_ref: str,
    ) -> AnalyticsPrivacyReadback:
        try:
            subject_kind, subject_id = subject_ref.split(":", maxsplit=1)
        except ValueError as error:
            raise ValueError(
                "analytics subject_ref must be anonymous:<id> or user:<id>"
            ) from error
        if subject_kind not in {"anonymous", "user"} or not subject_id.strip():
            raise ValueError(
                "analytics subject_ref must be anonymous:<id> or user:<id>"
            )
        return self._store.inspect_privacy(
            subject_kind=subject_kind,
            subject_id=subject_id,
        )

    def purge_expired(self, *, before: str) -> int:
        cutoff = datetime.fromisoformat(before)
        if cutoff.tzinfo is None:
            raise ValueError("analytics retention cutoff must be timezone-aware")
        return self._store.purge_expired(before=before)
