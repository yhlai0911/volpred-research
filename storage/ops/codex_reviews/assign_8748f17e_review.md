# assign_8748f17e — Matt implement / TDD / code-review receipt

Review fixed point: `cb3e9f30f`

## Ticket scope

- Add the missing privileged, evidence-gated owner-transfer actuator for
  `incident.lifecycle` and `provider.execution`.
- Keep both production owners on `legacy` until the parent Work Coordinator
  owner is transferred under its consumed seven-day gate.
- Support compare-and-set cutover, exact replay, rollback and durable receipts
  without granting mutation authority to `service_role`.

## TDD evidence

- Manifest tests bind the exact acceptance, regression and live-preflight bytes,
  canonical JSON identity, source/parent generations and a fixed 15-minute TTL.
- PostgreSQL 17 tests apply the migration twice and cover parent-owner denial,
  incident/provider cutover, exact transfer and stage replay, rollback,
  parent rollback after staging, migration replay, FORCE RLS and role ACLs.
- Attestation regressions accept a receipt-bound `operations_core/2` chain while
  still rejecting owner, generation, contract, chronology and receipt drift.
- Final adjacent suite: **125 passed**; Ruff, `py_compile` and diff check passed.

## Two-axis review

### Spec review — PASS

The implementation closes the previously missing transfer mechanism without
claiming that Issue #12 or #13 acceptance has passed. A manifest cannot be staged
unless `work.coordinate` is currently `operations_core` at the exact generation
bound into the manifest and its own gate is consumed. Transfer and rollback are
generation-CAS operations with immutable receipts and exact replay semantics.

Final verdict: **PASS**, no remaining P1/P2.

### Standards review — PASS

The Python interface is small and capability-generic. PostgreSQL owns the
transactional invariant: all mutation functions are private SECURITY DEFINER
functions with fixed search paths; gate tables use FORCE RLS; `service_role` can
only read the two public attestations. Stage and transfer share the lock order
`work owner → gate → capability owner`, preventing a replay/transfer lock cycle.
Migration replay preserves owner generation and receipt count.

Final verdict: **PASS**, no remaining P1/P2.

## Production read-back

- Exact migration `20260802054000` was applied independently and recorded as
  `gated_incident_provider_owner_transfer`; broad `db push` was not used.
- Both gate tables are owned by `volpred_ops_definer` with RLS and FORCE RLS.
- Private stage/transfer/post-mutation functions are unavailable to
  `service_role`; public incident/provider reads remain STABLE and readable.
- Fresh owner census at `2026-08-02T05:53:02Z` has no probe errors and still
  reports exactly five expected legacy owners. Incident and provider remain
  `legacy/1`; this deployment did not bypass Issue #9, #12 or #13.

## Release decision

The bounded actuator slice is **`root_cause_fixed_and_verified`**. The T40
umbrella remains **`contained`**: Issue #9 cannot be cut over before its real-time
gate matures, and Issue #12/#13 acceptance evidence must be completed before
their manifests are prepared or their owners transferred.
