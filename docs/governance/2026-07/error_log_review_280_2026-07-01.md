# Error Log Governance Sweep 280 - 2026-07-01

## Trigger

`governance_error_log_review_280` was opened because `docs/error_log.md`
crossed the 280 top-level incident bucket. This sweep reviewed the recent 20
top-level entries from `docs/error_log.md:5` through `docs/error_log.md:260`,
compared them with the previous 240-entry sweep, and ran the silent-fallback
audit because the cluster again contained fail-open / hidden-diagnostic cases.

## Recent Cluster

The dominant root-cause patterns are:

1. **Corrected-state and source-version drift on public surfaces.** The
   paper-audit generator replayed stale failure evidence against an article that
   already recorded a post-publish correction (`docs/error_log.md:5`), Supabase
   sync let stale single-report content override canonical feed content
   (`docs/error_log.md:137`), and digest/synthesis copy drifted away from source
   articles and result files (`docs/error_log.md:98`). The repeated failure mode
   is not "bad prose"; it is missing current-artifact selection before opening
   an audit, sync, or public claim path.

2. **Fail-open behavior is repeatedly acceptable, but unobservable fail-open is
   not.** Recent incidents include missing `exit_semantics` for findings exits
   (`docs/error_log.md:25`), persistent alerts that were not escalated as
   recurring root causes (`docs/error_log.md:37`), a daily-update sync hang that
   exceeded ordinary HTTP timeouts (`docs/error_log.md:59`), and multiple
   dashboard / probe fallback repairs (`docs/error_log.md:228`,
   `docs/error_log.md:236`, `docs/error_log.md:244`,
   `docs/error_log.md:252`). The system should continue running through
   degraded probes, but every degraded default needs either a warning, an
   explicit `silent-ok`, or a client-visible error path.

3. **Time alignment and horizon discipline remain the highest-risk research
   class.** K478 exposed forward-label training-tail leakage and one-step DM
   inference applied to 21-day overlapping targets (`docs/error_log.md:76`).
   K566 exposed same-day VIX / momentum signal alignment in a strategy article
   (`docs/error_log.md:118`). These are not cosmetic publication issues; they
   directly change whether a result can be treated as honest OOS evidence.

4. **Keyword gates are still too coarse for topic, repetition, and audit
   decisions.** The SPY cluster catch-all incident (`docs/error_log.md:49`) and
   cross-system keyword false-positive incident (`docs/error_log.md:180`) show
   that keyword matching is useful as a rough prefilter, not as the final
   arbiter of topical concentration, stale-knowledge overlap, or numeric claim
   invalidation.

5. **External and interactive publication queues need value-decay-aware TTLs.**
   The FB awaiting queue had technically pending work that was already losing
   timely reader value (`docs/error_log.md:15`). The actionable rule is to set
   expiry / early-warning thresholds by content half-life, not by the maximum
   time a manual recovery could still be performed.

6. **Article language often outruns the experiment's validation layer.** K1422
   had valid statistical evidence in parts of the experiment but overclaimed
   application-level hedging / stop-loss usefulness and contradicted itself
   between summary and body (`docs/error_log.md:153`). This recurs in source
   reviews: publication gates must check abstract, headings, tables, conclusion,
   and consumer-facing language against the actual results scope.

## Silent Fallback Audit

Commands run during this sweep:

```bash
uv run python scripts/audit_silent_fallbacks.py --json
uv run python scripts/audit_silent_fallbacks.py --strict --baseline storage/qa/silent_fallback_baseline.json --limit 20
```

Initial strict audit found one new baseline-exceeding finding:

- `scripts/generate_diverse_tasks.py:105` caught invalid ISO timestamps and
  returned `None` without warning. Because the caller was a corrected-errata
  skip gate, a malformed timestamp could make the task generator silently fall
  back to unsafe string comparison.

Fix applied in this sweep:

- `scripts/generate_diverse_tasks.py:102` now defines `_warn_diverse()` before
  the timestamp parser.
- `scripts/generate_diverse_tasks.py:106` reports invalid timestamp parse
  failures with field name, raw value, and exception.
- `scripts/generate_diverse_tasks.py:198` parses both `published_at` and
  `last_updated_at` through the warning parser.
- `scripts/generate_diverse_tasks.py:200` now fails closed when either timestamp
  cannot be parsed, so malformed metadata cannot suppress a paper review task.
- `tests/test_generate_diverse_tasks.py:658` and
  `tests/test_generate_diverse_tasks.py:671` lock the bad `last_updated_at` and
  bad `published_at` cases.

Post-fix strict audit result:

- Current findings: 74.
- Baseline findings: 75.
- New findings against baseline: 0.
- Resolved baseline findings: 1.

The resolved baseline item should be removed from
`storage/qa/silent_fallback_baseline.json` in a separate cleanup commit; this
sweep intentionally did not mix baseline churn with the new-root-cause fix.

## Rules Reinforced

- Any generator or audit gate that suppresses work because an item appears
  corrected, reviewed, stale, or duplicated must fail closed when timestamp,
  provenance, or canonical-source parsing fails.
- Public article sync must have a single current source of truth. Legacy single
  reports, cached review evidence, and older downstream artifacts may be used as
  audit context, but must not overwrite canonical feed content or corrected
  current state.
- Cross-source synthesis needs a claim table. At minimum, dates, counts, K
  identifiers, method labels, data frequency, and quoted statistics must be
  checked back to the source article and underlying result artifact.
- Strategy and forecasting reviews must inspect both signal lag and target-end
  embargo. For overlapping multi-day targets, inference horizon must match the
  loss horizon or use an explicit block / HAC alternative.
- Keyword-based concentration, stale-knowledge, and audit-number checks are
  prefilters. Blocking or escalation should move to semantic topic comparison
  or a stricter evidence match before creating user-facing alerts.
- Persistent alerts are root-cause evidence. A repeated warn with the same
  stable alert key should become a dreaming / governance finding before the user
  has to ask why the warning has been present for days.
- External interactive queues require early-warning and expiry thresholds tied
  to content half-life. A post that can still be manually published is not
  automatically still worth publishing.
- Publication language must stay inside the experiment's validation layer. Any
  mention of hedging, stop-loss, position sizing, or portfolio action needs an
  explicit P&L / drawdown / implementation test or a visible caveat that such
  validation was not performed.

## Verification

```bash
uv run pytest tests/test_generate_diverse_tasks.py -q
uv run python scripts/audit_silent_fallbacks.py --strict --baseline storage/qa/silent_fallback_baseline.json --limit 20
uv run python -m py_compile scripts/generate_diverse_tasks.py tests/test_generate_diverse_tasks.py
```

Results on 2026-07-01:

- `tests/test_generate_diverse_tasks.py`: 31 passed.
- Silent fallback strict audit: `findings=74`, `baseline_findings=75`,
  `new=0`, `resolved=1`.
- `py_compile`: passed.
