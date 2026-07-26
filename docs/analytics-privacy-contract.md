# Analytics Privacy Tracer contract

Issue [#5](https://github.com/yhlai0911/volpred-research/issues/5)
defines the first-party analytics privacy seam. The executable source of truth
is `src/volpred/analytics/privacy.py`; this document explains its boundaries
without duplicating the full field dictionary.

## Event boundary

The canonical `ANALYTICS_EVENT_DICTIONARY` declares each event's:

- single first-party measurement purpose;
- required and optional properties;
- 30-day raw retention;
- anonymous-or-authenticated identity contract; and
- caller-supplied idempotency key dedupe contract.

The five admitted events are `content_impression`, `content_click`,
`read_depth`, `qualified_action`, and `return_visit`. The tracer rejects
unknown events, missing required fields, and every undeclared property before
data reaches an adapter. Portfolio positions, trading intent, and other
financial-profile fields are not part of the dictionary.

Retention is executable through `AnalyticsPrivacyTracer.purge_expired()`.
Every accepted row also carries its own `raw_expires_at`, so a scheduler can
run the purge idempotently without reconstructing retention from prose.

## Identity and privacy lifecycle

Anonymous-to-user merge is transactional and replay-safe. An idempotency-key
replay returns the original merge count and does not count the event twice.
Conflicting ownership of an anonymous identity is rejected.

Privacy actions use explicit `anonymous:<id>` or `user:<id>` subject
references:

- `set_opt_out` immediately removes all linked aliases from aggregate
  projections and rejects later events;
- `clear` removes existing raw events while retaining the opt-out preference
  and identity link;
- `delete` removes raw events, identity links, merge receipts, and preferences.

Delete retains only a SHA-256 subject digest tombstone plus a subject-free
idempotency receipt. The tombstone prevents delayed upstream event or merge
replays from recreating deleted data; neither artifact exposes the original
identity.

`inspect_privacy()` returns only opt-out state and counts for raw events,
projected events, and identity links. It never returns event properties or an
identity list.

## Storage and access

`InMemoryAnalyticsStore` is the fast contract implementation.
`PostgresAnalyticsStore` is the durable implementation backed by migration
`*_analytics_privacy_tracer.sql`.

PostgreSQL state lives in the private `volpred_analytics` schema. `PUBLIC`,
`anon`, and `authenticated` receive no schema, table, or sequence privileges.
All tables also have row-level security enabled without Data API policies.
Only a trusted backend connection is intended to instantiate the adapter.

Admin reads go through `admin_summary()`, which returns only event kind and
group count for a time interval. There is no Admin method for raw events,
identities, or financial-profile segmentation.

## Verification

- `tests/test_analytics_privacy_tracer.py` covers dictionary validation,
  dedupe, merge, retention, aggregate-only reads, opt-out, clear, delete, and
  deletion-replay suppression.
- `tests/test_postgres_analytics_privacy.py` applies the migration to an
  ephemeral PostgreSQL 17 instance and reruns durable lifecycle, RLS,
  privilege, retention, and replay checks.

The migration is a deployable artifact, not proof of production application.
Production rollout must use the normal Supabase migration workflow and verify
the migration receipt plus post-deploy schema privileges before wiring a live
caller.
