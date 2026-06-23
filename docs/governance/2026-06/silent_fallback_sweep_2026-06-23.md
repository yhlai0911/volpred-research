# Silent Fallback Governance Sweep — 2026-06-23

## Trigger

`governance_error_log_review_40` was opened because `docs/error_log.md`
crossed the 40 top-level incident bucket.

## Pattern

The recent cluster is dominated by fail-open handlers that preserved runtime
continuity but hid the degraded source:

- bad JSON treated as empty state
- bad timestamps treated as absent / stale / due
- unreadable source files excluded from scans
- subprocess failure collapsed into an empty candidate list

The correct rule is not "crash on every fallback". For ops and publishing
surfaces, fail-open can be correct, but the fallback must emit a path + error
diagnostic so the operator can distinguish "no work" from "source drift".

## Guard Added

Added a reusable AST audit:

```bash
uv run python scripts/audit_silent_fallbacks.py
uv run python scripts/audit_silent_fallbacks.py --json
uv run python scripts/audit_silent_fallbacks.py --strict
```

The audit reports exception handlers in `scripts/` and `src/` that use
`pass`, `continue`, or default-ish `return` without an observable diagnostic.
It is heuristic by design; report mode is for governance triage, while
`--strict` is available once owners have burned down or allowlisted legacy
cases.

Initial run on 2026-06-23 returned 125 suspect handlers after excluding test
directories from recursive scans. This is not a clean gate yet; it is the
backlog map for future targeted burn-down tasks.

## Task Generator Update

Future `governance_error_log_review_*` tasks now include the audit command in
their description when the cluster is silent-fallback shaped, so the next sweep
does not rely on ad hoc grep.
