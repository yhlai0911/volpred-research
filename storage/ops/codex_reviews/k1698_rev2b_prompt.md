# Codex primary-path review — K1698 rev2b (round 3)

You are the primary-path reviewer. This is **round 3**.

- Round 1 (rev1, 2026-07-17) returned **FAIL** with 7 blockers.
- Round 2 (rev2, commit `706587a37`) returned **FAIL**: 1 CRITICAL, 4 MAJOR, 1 MINOR,
  and 2 of the original 7 blockers still open.
- **rev2b** (`23975b1b0`) is the remediation for exactly those round-2 findings.

**Your scope is narrow:**

1. Are the round-2 findings actually fixed, **in the bytes**, and sufficiently?
2. Did the remediation introduce any **new** claim–evidence gap?

Do **not** re-litigate what round 2 already passed unless rev2b's edits touched it.
Do **not** carry round 2's verdict forward — review the current bytes.

## Where everything lives

Working tree (read-only for you):

```
/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/
```

The bytes under review are frozen at
`/Users/yhlai0911/volpred-research/storage/ops/codex_reviews/k1698_rev2b_freeze.txt`
(sha256, 4 files). If any file you read does not match its listed hash, **stop and say so**
— the review is invalidated. (The dispatch main thread verified the tree clean at HEAD
`23975b1b0` when it froze them.)

Read, at minimum:

- `experiments/k1698/README.md` — the claim surface under review (353 lines)
- `experiments/k1698/k1698_rev2_results.json` — **PRIMARY** artifact
- `experiments/k1698/k1698.py` — the generator (3293 lines). Read the code for anything
  you judge; do not take the README's word for what the code does — that is precisely
  how both earlier rounds' defects survived.
- `experiments/k1698/run_log_rev2.txt` — execution receipt

`k1698_rev1_superseded_results.json` is the rev1 artifact, kept only for before/after
audit. **Do not cite it as a current result.**

## The findings you are adjudicating

For each: state what you checked, what the bytes said, and PASS/FAIL **for that finding**.

- **CRITICAL-1 — TOST margin was not renormalisation-invariant.** The margin was a
  fraction of mean QLIKE(GJR), a loss LEVEL; QLIKE's arbitrary additive constant moved
  the basis 1.61 → 2.61 under a +1 shift and flipped the 10% verdict. rev2b claims the
  basis is now a loss DIFFERENCE (predictive gain of the conditional benchmark over an
  unconditional-variance forecast), in which the constant cancels, and that
  `h2_equivalence.margin_invariance_check` re-derives the whole verdict under a +1 shift
  and **raises** if it moves. Verify the invariance claim from the code path, not just
  the two printed p-values — check that the guard actually raises and that the
  unconditional-variance benchmark is itself computed on the aligned target without
  lookahead.
- **MAJOR-2 — `window_volume` was `t <= 13:30`, silently dropping night PM** from the
  selection score. rev2b claims `~tail_mask` instead, and that the leak diagnostic
  corrects 3 days → 2 (2017-01-18, 2017-02-15), still 0 in OOS. Confirm the mask
  actually spans night PM + night AM + day-to-13:30, and that the rule remains
  lookahead-free (nothing after 13:30 of day D enters the score for RV(D)).
- **MAJOR-3 — stamp audit used a file-wide modal trade date** pooled across contracts,
  and coverage exceptions were excused merely for falling outside OOS. rev2b claims:
  per-delivery stamp, verdict uses the **active** contract's own stamp; exceptions
  classified from the data as `market_wide_session_cancellation` vs
  `contract_level_data_gap`; an unexcused contract-level gap **aborts the run anywhere**.
  Reported: 5 exceptions, all market-wide, 0 unexcused, 0 boundary violations, 0 stamp
  failures, 481 OOS days all passing. Verify the abort is real (not a warning) and that
  the market-wide classification is evidence-driven.
- **MAJOR-4 — no DM lag sensitivity** (violates `.claude/rules/experiments.md`). rev2b
  adds it for the gate DM and q2, and reports that **q2's |t|>3 verdict FLIPS across
  bandwidths** ([2.958, 3.140], failing at lags 2 and 20), so q2 is no longer reported as
  clearing the guardrail; the gate DM is stable ([1.469, 1.563]). Check that the README's
  narrative honours the flip everywhere it mentions q2, not only in the sensitivity block.
- **MAJOR-5 — q2 presented as passing a "pre-registered" guardrail** though designed in
  rev2. rev2b marks `PREREGISTRATION_STATUS: POST_HOC`, notes that the generic `dm_pair`
  flag records only |t|>3, and discloses that no multiple-testing correction spans rev2's
  post-hoc comparisons. Check every other post-hoc comparison introduced in rev2/rev2b
  carries the same disclosure — a single un-flagged one reopens this.
- **MINOR-6 — "equivalence only holds at delta >= 20%"** was a grid-placement artifact;
  `delta_min_at_5pct` IS the threshold. Check README and JSON agree.
- **STILL-OPEN-3 — accepting-the-null language on the primary claim surface.** "there is
  no divergence to explain" / "divergence is a construction artifact" was still inside
  `GATE_REASON` and `gate.route`. rev2b claims removal from those strings, with the
  pre-registered verdict MAPPING unchanged and its original text preserved verbatim in
  `route_preregistered_label_verbatim` / `gate_rules_preregistered`, and
  `route_label_amended` flagging the amendment. **Judge whether amending a
  pre-registered route label — even with the original preserved — is legitimate here, or
  whether it is post-hoc rewriting of a pre-registration.** Then sweep the whole README
  and JSON for any surviving accepting-the-null phrasing.
- **STILL-OPEN-7 — review receipt.** rev2b freezes for re-review; the README references
  `experiments/k1698/review_receipt_rev2.json`. **That file does not exist in the tree.**
  Judge whether that is a blocking documentation defect.

## Standing checks (independent of the list above)

- The headline `GATE_VERDICT = H2_REJECTED` with `GATE_ROUTE` = FRL / Journal of
  Forecasting short note. Is the claim surface honest that **both** "HAR wins" and
  "the two are equivalent" are unestablished?
- Any number in the README that is not reproducible from the JSON.
- Any claim of the form "X is fixed" that the code does not support.

## Verdict format

End with exactly one line:

```
VERDICT: PASS | CONDITIONAL_PASS | FAIL
```

`CONDITIONAL_PASS` = mergeable with named, non-inferential edits (wording, docs).
`FAIL` = any surviving claim–evidence gap or unfixed finding. Then list, per finding,
`FINDING-ID: PASS/FAIL — one line of why`, followed by any new issues with severity.
