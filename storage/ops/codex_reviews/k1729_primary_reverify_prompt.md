# K1729 — Primary-path Codex certification (fallback PASS re-verification)

You are the PRIMARY-PATH independent Codex reviewer. This experiment (K1729) already
carries a **fallback** PASS (two non-Codex reviewers on 2026-07-21, when Codex CLI hit a
hard usage-limit). Per `.claude/rules/experiments.md`, a fallback PASS is NOT closure;
these exact bytes REQUIRE primary-path Codex re-verification before K1729 may be treated
as closed. Credits have reset (today ≥ 2026-07-25), so you are that primary path now.

## What K1729 is

Does an **intraday VIX-futures roll signal (HAR-DAILY)** beat **HAR-RV5** at forecasting
next-day realized volatility? Head-to-head via Diebold-Mariano with Harvey small-sample
correction. Headline result: **HAR_RV5_WINS on both targets, |t|>3** (t = -3.671 / -3.370).
The conclusion is NARROW: predictive gain is non-zero; it does NOT claim the data line is
"worth maintaining" (that was retracted).

## Frozen bytes under review (do NOT accept any other copy)

Read ONLY these, in the main repo working tree:
- `experiments/K1729/README.md`      sha256 9adaaaeb5906230590fa4aa8bde6ad680c562c5fb231953b201e2aabe21d397b
- `experiments/K1729/k1729.py`       sha256 74ddae0e123be5eee0784568d98617ee64c2e2fb1034776ddf0eda934d0631b7
- `experiments/K1729/k1729_results.json` sha256 2f30de1989439d6c6e4b94b989bfa9b3960c47f3804ef4c3f2ac9d0f191886e8

If any file's on-disk sha256 does not match the above, STOP and return
`VERDICT: FAIL` with defect "reviewed bytes drifted from frozen snapshot".

## What you must independently certify (the fallback reviewers claimed these; verify them)

1. **Lookahead / timing**: signal at t-1, return at t. Confirm `k1729.py` lags the signal
   (explicit `.shift(1)` or equivalent) and that no same-day signal×same-day return path
   exists. This is the highest-risk item — check it first.

2. **Defect 1 repair — target-side ex-post contract selection** (rev1 FAIL, now claimed
   repaired). The ex-ante RULE E (hold front monthly contract through its published
   3rd-Wednesday settlement, holiday-adjusted, then roll) should make 2545/2550 OOS rows
   (99.80%) ex-ante determined; the 5 exceptions are early-volume-migration settlement days.
   Verify the ex-ante-only ledger AND the drop-all-127-roll-days robustness BOTH still keep
   HAR_RV5_WINS with |t|>3 (claimed t = -3.584 / -3.665 dropping roll days). Confirm the
   machine verdict actually REQUIRES the ex-ante ledger to concur (not just the primary ledger).

3. **Defect 2 repair — operational overclaim retraction**. README §7 must no longer say
   "this data line is worth maintaining"; it may claim only a non-zero predictive gain.
   Confirm the retraction is real and no equivalent overclaim survives elsewhere.

4. **Nested-DM adjudication**. `k1729.py` was flagged `primary_raw_dm` by the
   nested-dm-misuse gate; the fallback adjudicated it a false positive because HAR-RV5
   (5-min RV d/w/m) and HAR-DAILY (daily open-to-close squared-return d/w/m) have DISJOINT
   regressor sets → neither nests the other → raw DM is valid. Verify this reasoning against
   the actual regressor construction in the code, and against the non-degeneracy evidence in
   results.json (forecast corr 0.778/0.791, mean relative gap ~20%, loss-diff std 0.364/0.713,
   exact-zero fraction 0.0%). Is the false-positive call sound?

5. **Number-to-code integrity**: spot-check that the headline t-stats, the ex-ante row
   counts, and the DM statistics in README/results.json are actually produced by the code
   path (no hand-typed or stale numbers). Seed is fixed where randomness enters.

## Bar

CONDITIONAL_PASS or above = closure-eligible. A clean, leak-free, honestly-narrowed result
with the two rev1 defects genuinely repaired should be **PASS**. Return **FAIL** only on a
real surviving defect (lookahead, a number that does not reproduce from the code, a
surviving overclaim, or an unsound nested-DM adjudication).

## Output format (required)

```
VERDICT: <PASS | CONDITIONAL_PASS | FAIL>
REVIEWER: <your model id / effort>
LOOKAHEAD_CHECK: <pass/fail + one line>
DEFECT_1_EXANTE_LEDGER: <verified / not verified + evidence>
DEFECT_2_RETRACTION: <verified / not verified>
NESTED_DM_ADJUDICATION: <sound / unsound + why>
NUMBER_INTEGRITY: <ok / issues>
BLOCKING_DEFECTS:
- <one per line, or "none">
NOTES: <brief>
```
