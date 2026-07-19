# Codex primary-path review — K1731 arm B rev6 (post-FAIL remediation round)

You are the primary-path reviewer. Round 5 returned **FAIL** with seven blocking issues (B1–B7).
Rev6 is the remediation round. **Your scope this round is narrow and specific:**

1. Are the B1–B7 fixes actually in place, in the bytes, and sufficient?
2. Did the remediation introduce any NEW claim–evidence gap?

Do **not** re-litigate points that round 5 already passed unless rev6's edits touched them.
Do **not** carry forward round 5's verdict — review the current bytes.

## Where everything lives

Working tree (read-only for you):

```
.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/
```

The bytes under review are frozen at
`storage/ops/codex_reviews/k1731_armB_rev6_freeze.txt` (sha256 manifest, 11 files).
If any file you read does not match its listed hash, **stop and say so** — the review is
invalidated and must be re-run.

Read, at minimum:

- `README.md` — the claim surface under review
- `k1731_armB_rev6.json` — this round's self-report (`blocking_issues_addressed`, `b1_decision`,
  `regression_check`, `verification_summary`, `detector_coverage_gap_found`, `followup_needed`)
- `k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json` — **PRIMARY** artifact (untouched
  by rev6; rev6 claims to have altered no estimated number)
- `k1731_es_mixture_check.py` + `k1731_es_mixture_check_results.json` (B6 seed fix)
- `k1731_armB_verification.py` + `k1731_armB_traceability_rows.json` (B2/B7 checker extension)
- `k1731_regression_check_results.json` (the no-drift claim)
- `k1731_gevreg_midas_ssvs_returns.py`, `k1731_models.py`, `k1731_scoring.py` (estimation path —
  rev6 claims these are untouched; verify)

**Do not cite** `k1731_gevreg_midas_ssvs_returns_results.json` or `..._results_corrected.json` —
both stamped `do_not_cite`, superseded by rev5.

## The seven issues you are adjudicating

For each: state what you checked, what the bytes said, and PASS/FAIL **for that issue**.

- **B1 — nested-DM misuse.** Rev6 chose to **retract** the "bounded macro null" claim rather than
  attempt a correction. Verify the retraction is complete and consistent across §1, §3.2, §3.3b,
  §6 and the summary tables — a retraction that survives in the headline but leaks back into a
  body table is a FAIL. Then check the reasoning itself: rev6 argues the comparison is nested via
  a coefficient mask (`k1731_gevreg_midas_ssvs_returns.py:163`, `active[n_beta - n_macro:] = 0.0`)
  and that the **expanding** window (`:129`) closes the Giacomini–White escape hatch, so
  West (1996) / Clark–McCracken applies and the DM statistic is not asymptotically normal.
  Derive this yourself — if the argument is wrong in either direction (i.e. the comparison is NOT
  nested, or the retraction was unnecessary), say so. Rev6 also folds arm A's cross-arm
  t = +2.13 into the same defect class; check that too.
- **B2 — leaf count.** README said 3,776; the gate says 3,834. Confirm no stale 3,776 survives
  outside the changelog, and that the traceability checker was extended to cover gate/meta numbers
  (it previously claimed "zero mismatches" while structurally blind to them).
- **B3 — superseded 5-day-block losses.** 0.1305 / 0.1433 / 0.1656 replaced with rev5's
  `oos.robustness_full_weeks_only.*`. Verify the replacements against the rev5 JSON field by field.
- **B4 — GARCH state lookup.** rev5 declares `garch_origin_lag_trading_days = 1`; §4 previously
  contradicted it. Verify the rewritten §4 matches the code's actual lag, not the JSON's label.
- **B5 — over-broad attribution.** "Any difference between the two arms is attributable to the
  target and nothing else" — verify the narrowed version is now supported by the enumerated
  differences and does not smuggle the old claim back in weaker wording.
- **B6 — non-reproducible seed.** `hash(name)` (randomized per process) replaced with
  `hashlib.sha256`. Verify determinism and that the regenerated
  `k1731_es_mixture_check_results.json` is consistent with the declared seed.
- **B7 — provenance / review-trail overclaim.** "Every file below carries provenance" was false for
  `k1731_quickmode_results.json`; §10 said two review rounds where four are documented. Verify both.

## Two findings rev6 ADDED beyond your round-5 list — adjudicate these too

- **The nested-DM detector has a coverage gap.** `audit_nested_dm_misuse` cannot see nesting
  expressed as a coefficient mask, so its PASS on K1731 is a **false negative**. Rev6 says this
  gate's PASS must not be cited as clearing B1. Confirm the gap from the detector's source, and
  say whether the repo-wide 193-site baseline is therefore an undercount.
- **Arm A's numbers come from a quick-mode artifact** (§5.3), including the cross-arm
  t = +2.13. Judge whether any surviving README claim leans on quick-mode numbers without saying so.

## Structural checks

1. **No estimated number moved.** `regression_check` claims 3,834 leaves / 0 out-of-allowlist /
   `drift_detected: false`. The allow-list is imported from the audited finalizer
   (`FINALIZE_OWNED_KEYS`) — a structural conflict of interest. Verify the allow-listed keys are
   provably narrative-only, i.e. that this coupling cannot wave a real drift through.
2. **Traceability negative control.** rev6 claims an injected stale value correctly produces
   MISMATCH. Verify the negative control actually exercises the checker rather than asserting on a
   hand-set flag.
3. **Provenance invariant.** Exactly one artifact carries `is_primary=true`; superseded files carry
   `do_not_cite` with a supersession reason. Verify in the JSONs, not in print output.
4. **Nothing earlier rounds fixed was silently re-broken.** §10 has the review trail.

## Standing repo rules you are enforcing

- No lookahead: signals lagged in code; baselines use the same lag.
- DM tests on nested models need the appropriate correction; HAC alone does not license a bound.
- Results that look too good are ~90% a bug.
- Research honesty outranks a clean narrative. **A null written up as a null is a PASS. A retraction
  that is honest and complete is a PASS — it is not a defect that rev6 chose to retract rather than
  to rescue the claim.**

## Output

Write a Markdown report whose FIRST line is exactly one of:

`VERDICT: PASS`
`VERDICT: FAIL`

FAIL if any of B1–B7 is unfixed or only cosmetically fixed, if the remediation introduced a new
claim–evidence gap, or if any gate is structurally unable to catch what it purports to catch.

Then one short section per issue (B1–B7, the two added findings, the four structural checks):
what you checked, what the bytes said, your judgement.

End with `## Blocking issues` (empty if PASS). Each entry must be actionable without re-deriving
your reasoning: file, line or field, what is wrong, what would fix it.
