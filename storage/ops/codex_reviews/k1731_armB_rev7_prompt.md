# Codex primary-path review — K1731 arm B rev7 (second remediation round)

You are the primary-path reviewer. Round 6 returned **FAIL** with four blocking issues.
Rev7 is the remediation round for exactly those four. **Your scope this round is narrow:**

1. Are the four round-6 blocking issues actually fixed, in the bytes, and sufficiently?
2. Did the remediation introduce any NEW claim–evidence gap?

Do **not** re-litigate what rounds 5–6 already passed unless rev7's edits touched it.
Do **not** carry forward round 6's verdict — review the current bytes.

## Where everything lives

Working tree (read-only for you):

```
/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/
```

Experiment dir: `experiments/k1731/` under that root. The detector files
(`scripts/audit_nested_dm_misuse.py`, `scripts/tests/test_nested_dm_misuse_ratchet.py`,
`storage/ops/nested_dm_misuse_baseline.json`) also live under that worktree root.

The bytes under review are frozen at
`/Users/yhlai0911/volpred-research/storage/ops/codex_reviews/k1731_armB_rev7_freeze.txt`
(sha256 manifest, 15 files: 12 in the experiment dir + 3 repo-level).
If any file you read does not match its listed hash, **stop and say so** — the review is
invalidated. (The dispatch main thread verified all 15 as OK at 10:58; a mismatch now means
something moved under you.)

Read, at minimum:

- `experiments/k1731/README.md` — the claim surface under review
- `experiments/k1731/k1731_armB_rev7_remediation.json` — this round's self-report
  (`blocking_issues`, `detector`, `regression_check`, `ready_justification`,
  `not_touched_this_round`)
- `experiments/k1731/k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json` — **PRIMARY**
  artifact. rev7 edited `cross_arm_comparison` narrative leaves only and claims **zero numeric
  leaves moved**. Verify that claim, do not take it.
- `experiments/k1731/k1731_finalize_report.py` — the canonical generator for that artifact
  (edited this round; newly added to the freeze manifest because rev6 pinned the artifact but
  not the code that writes it)
- `experiments/k1731/k1731_gevreg_midas_ssvs_returns.py` — estimation source. rev7 claims the
  change is **docstring-only** and proves it by AST comparison with docstrings stripped.
- `scripts/audit_nested_dm_misuse.py` + `scripts/tests/test_nested_dm_misuse_ratchet.py` +
  `storage/ops/nested_dm_misuse_baseline.json` — the detector fix

**Do not cite** `k1731_gevreg_midas_ssvs_returns_results.json` or `..._results_corrected.json` —
both stamped `do_not_cite`, superseded by rev5.

## The four issues you are adjudicating

For each: state what you checked, what the bytes said, and PASS/FAIL **for that issue**.

- **B1a — the retraction leaked into the table.** Round 6 found §3.2 still headed
  "bounds, not just p-values" and the nested row still labelled a bold **95% CI**, after the
  surrounding prose had retracted exactly that. rev7 claims: heading → "the four primary
  comparisons"; column → "HAC diagnostic interval"; nested row unbolded with a `†` footnote
  saying it has no coverage guarantee; and an added statement that the three non-nested rows
  *do* keep CI semantics. **Check the whole README, not just §3.2** — a retraction that holds in
  §3.2 but leaks back into §1, §3.3b, §6, §10 or any summary table is a FAIL. Also judge whether
  the new "interval semantics differ by row" framing is itself defensible, or whether it is a
  softer way of keeping the interval alive.

- **B1b — the primary artifact still asserted a demonstrated null.** Round 6 found
  `cross_arm_comparison.what_cannot_be_said` still saying arm A "demonstrably does not" improve
  OOS forecasts, and `correct_reading` writing both arms up as an established OOS null with no
  nested-DM caveat. rev7 claims it **regenerated** the block from `k1731_finalize_report.py`
  (not hand-edited), removed "demonstrably", added a four-element `inference_caveats` array
  (West 1996; Clark–McCracken 2001; expanding window outside Giacomini–White 2006; arm A quick
  mode), and reworded README §3.3b/§6 to the same sentence. Verify: (a) the JSON now says what
  it claims; (b) README, JSON and module docstring actually agree rather than merely
  co-existing; (c) the regeneration claim — does the generator, run on the same inputs, produce
  this block? (d) **zero numeric leaves moved** against the round-6 frozen bytes.

- **B5 — the docstring overclaimed structural identity.** Round 6 found the module docstring
  still saying arm B "holds the entire engine fixed" while three settings demonstrably differ.
  rev7 claims the docstring now says "reuses the same model implementation while these settings
  differ" and enumerates the three uncontrolled differences (macro set 6→5 with IP dropped;
  `garch_origin_lag_trading_days=1` in rev5, absent in arm A; arm A quick vs arm B production),
  and that README's hard count "six things" became "the enumerated shared constructs". Verify
  the docstring-only claim mechanically, and judge whether the new wording is now *accurate* —
  not merely less wrong.

- **detector — the auditor could not see the site it exists to catch.** rev7 added a
  coefficient-mask nesting AST channel (`_coef_mask_ast_evidence`) that fires only on the
  conjunction of (1) a subscript/slice assigned a zero-like value and (2) that same array
  reaching a fit-family call in a restriction-shaped position. Judge:
  (a) does it actually flag `k1731_gevreg_midas_ssvs_returns.py` (`active[n_beta-n_macro:] = 0.0`
      → `fit_gev_reg(..., active=active)`), and is the isolation test real — i.e. with the mask
      construction removed, is it genuinely NOT flagged through some other channel?
  (b) are the two negative controls (zeroed slice as `sample_weight`; restriction-named array
      never reaching an estimator) real tests or assertions on a hand-set flag?
  (c) **is the conjunction narrow enough to be honest and wide enough to be useful?** rev7
      reports 295 files contain a zeroed-subscript assignment and 2 pass the full conjunction.
      Two is a suspiciously clean number — decide whether that is precision or a detector
      shaped to fit exactly the two sites already known.
  (d) the three declared blind spots (predict/forecast-only masks; list-multiplication
      restrictions; cross-module masks) — are they honestly scoped, or do they carve out the
      cases that would have been expensive to catch?

## Also check

1. **The baseline flip is honest.** rev7 flags `experiments/k1730/k1730_gevreg_midas_ssvs.py`
   (arm A) as newly exposed and hands it back rather than repairing it — correct per its brief.
   But it also chose the **more severe** bucket (`review_required`) on the argument that arm A's
   `t=+2.13` is quoted as a cross-arm claim in K1731. Verify the baseline JSON records both new
   sites as exposed and that the counts move as claimed (193→195 sites, 103→105 exposed,
   diagnostic-only unchanged at 90).
2. **Nothing earlier rounds fixed was silently re-broken.** §10 has the review trail. The
   round-6 PASSes (B2 leaf count, B6 ES seed, B7 traceability, provenance invariant) must still
   hold in the current bytes.
3. **Provenance invariant.** Exactly one artifact carries `is_primary=true` with
   `do_not_cite=false`; superseded production artifacts carry `is_primary=false`,
   `do_not_cite=true`, a `superseded_by` and a non-empty `superseded_reason`. Verify in the
   JSONs, not in print output.
4. **The `ready_justification` names what is NOT fixed.** rev7 states the nested-DM inference
   problem itself remains uncorrected (disclosed, not fixed) and arm A remains unrepaired.
   Judge whether the README's claim surface is consistent with that admission — if the README
   reads as though the problem were solved, the admission in the JSON does not rescue it.

## Standing repo rules you are enforcing

- No lookahead: signals lagged in code; baselines use the same lag.
- DM tests on nested models need the appropriate correction; HAC alone does not license a bound.
- Results that look too good are ~90% a bug.
- Research honesty outranks a clean narrative. **A null written up as a null is a PASS. A
  retraction that is honest and complete is a PASS — it is not a defect that this experiment
  chose to disclose the nested-DM problem rather than to correct it, provided the disclosure is
  complete and no claim anywhere still depends on the retracted inference.**

## Output

Write a Markdown report whose FIRST line is exactly one of:

`VERDICT: PASS`
`VERDICT: FAIL`

FAIL if any of B1a / B1b / B5 / detector is unfixed or only cosmetically fixed, if the
remediation introduced a new claim–evidence gap, or if the detector is structurally unable to
catch what it purports to catch.

Then one short section per issue (B1a, B1b, B5, detector, plus the four "also check" items):
what you checked, what the bytes said, your judgement.

End with `## Blocking issues` (empty if PASS). Each entry must be actionable without re-deriving
your reasoning: file, line or field, what is wrong, what would fix it.
