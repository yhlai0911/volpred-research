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

Every admitted property also has a value contract. Identifiers are bounded
opaque strings that exclude email-like syntax; all other values are closed
enums. Nested objects, undeclared enum values, and attempts to hide financial
profile data inside an allowed property are rejected by both the tracer and
the PostgreSQL trigger.

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
  and identity link; it replaces event rows with keyed dedupe tombstones so
  delayed delivery cannot recreate cleared history;
- `delete` removes raw events, identity links, merge receipts, and preferences.

Delete retains only HMAC-SHA-256 subject tombstones and one minimal,
HMAC-bound deletion receipt. The required secret is supplied to the store,
must contain at least 32 bytes, and must remain stable for the lifetime of
existing tombstones. PostgreSQL also pins the configured key ID and a keyed
verifier in a one-row, append-only identity table; a missing or drifted secret
fails closed before any adapter operation. These artifacts prevent delayed
upstream event or merge replays from recreating deleted data without storing
the original identity. A late merge that reveals a new alias of a deleted
identity tombstones that alias before rejecting the merge. Earlier
privacy-action receipts for linked aliases are removed, and their delayed
replay cannot recreate a preference.

Event idempotency is bound to a canonical payload digest. Retention purge
replaces an expired raw row with keyed event/payload digests, so a delayed
matching replay remains expired and a conflicting payload using the same key
fails closed.

`inspect_privacy()` returns only opt-out state and counts for raw events,
projected events, and identity links. It never returns event properties or an
identity list.

## Storage and access

`InMemoryAnalyticsStore` is the fast contract implementation.
`PostgresAnalyticsStore` is the durable implementation backed by migration
`*_analytics_privacy_tracer.sql`.

PostgreSQL state lives in the private `volpred_analytics` schema. `PUBLIC`,
`anon`, and `authenticated` receive no schema, table, or sequence privileges.
All tables use forced row-level security. A dedicated non-login,
non-superuser, non-bypass `volpred_analytics_worker` role has only the grants
and command-specific RLS policies needed by the backend adapter. Tombstone and
digest-key tables have no worker `DELETE` privilege; event mutation is limited
to the canonical `user_id` merge column. A database trigger independently
rejects undeclared/nested property values, retention drift, and timestamps more
than five minutes in the future.

Admin reads go through `admin_summary()`, which returns only event kind and
group count for a time interval. There is no Admin method for raw events,
identities, or financial-profile segmentation.

## Verification

- `tests/test_analytics_privacy_tracer.py` covers dictionary validation,
  dedupe, merge, retention, aggregate-only reads, opt-out, clear, delete, and
  deletion-replay suppression.
- `tests/test_postgres_analytics_privacy.py` applies the migration to an
  ephemeral PostgreSQL 17 instance twice and reruns durable lifecycle,
  forced-RLS/worker privileges, DB-side value validation, retention, payload
  binding, identity conflict, and replay checks.

The migration is a deployable artifact, not proof of production application.
Production rollout must use the normal Supabase migration workflow and verify
the migration receipt plus post-deploy schema privileges before wiring a live
caller.

## 2026-07-27 implementation acceptance

Issue #5 implementation is accepted at commit `7c6660dc4`:

- clean-checkout analytics/privacy suites: 21 passed;
- independent Matt-flow Spec review: PASS;
- independent Standards review: PASS, zero findings;
- full repository suite: 5,372 passed, 2 skipped, 12 failed in concurrently
  changing Change Delivery / Git actuator / canonical-writer inventory paths;
  none of the failures touch analytics code or this migration.

The linked Supabase migration ledger contains unrelated local-only and
remote-only versions, so broad `db push` remains prohibited. On 2026-07-27 the
two exact files were applied independently and recorded as production receipts
`20260727100227 analytics_privacy_tracer` and
`20260727100422 analytics_ingress_rpc`.

Production read-back confirms all nine `volpred_analytics` tables use RLS plus
forced RLS; `PUBLIC`, `anon`, and `authenticated` have no schema/table/RPC
access; and only `service_role` may execute the fixed-search-path,
security-definer ingress RPC. The Zeabur caller computes all HMAC digests
server-side. Its stable secret lives in macOS Keychain service
`volpred-analytics-tombstone`; the deploy script injects it into a sibling
temporary variable file, excludes every `.env*` file from the upload tree, and
fails closed if the credential is absent. Deployment
`6a6736c7225290ec74322de0` read back both required runtime variables while
confirming `.env.production` was absent from the container source tree.

Live ingress accepted a keyed canary, persisted the matching digest and 30-day
expiry, then returned `duplicate=true` for an exact replay. Desktop/mobile
browser E2E subsequently produced impression, click, depth, and qualified
action rows with one distinct idempotency key per row.
