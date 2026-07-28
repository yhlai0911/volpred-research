# K1720 — Codex round 2 review (rev2, read-only)

You reviewed K1720 rev1 and returned **FAIL** with five findings (R1–R5). The authors ran a bounded
remediation. This is round 2: decide whether rev2 is certifiable.

## Scope — READ ONLY

Review root: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/`

- `K1720.py` (52,614 bytes, sha256 `bf431b7b80410f151dbab5d1e39089adc415ac5f8f9e8d4de7edf4bcfa79cc30`)
- `K1720_results.json` — canonical numbers; `remediation.items[]` is the authors' own account of each fix
- `README.md`
- `reproduce_spec.json`
- `rev1_K1720_results_snapshot.json` — rev1 numbers, sha256 `1c3aafbe8a9d3c506159f8e638884af50c29c18d08399e4d1219aefd9f62e9b8`
- your round-1 verdict: `storage/ops/codex_reviews/k1720_verdict.md`

**Do not modify anything, do not re-run the experiment, do not merge.** Output is the verdict file only.

## Already verified by the main thread (do not re-spend effort, but do challenge if you disagree)

- `reproduce_spec.entrypoint.sha256` == `K1720_results.code_trace.sha256` == the on-disk `K1720.py`
  (`bf431b7b…`, 52,614 B) — spec and results come from the same bytes.
- README's headline numbers were recomputed against `K1720_results.json` and match to the digit:
  QQQ H1 +0.407 / t=4.93 / p=8.2e-07; H1b +2.75 / t=1.62 / p=0.104; H2 all-days −0.0072 / t=−0.58 /
  p=0.561; H2 big-days +0.0164 / t=1.08 / p=0.279; n_classifiable 659 = 719 − 60.

## Your job — adjudicate each round-1 finding, then look for what rev2 introduced

**R1 — `prev_close` from previous full 7-bar session, `r_intra` spanning half-days.**
Claimed fix: `build_session_panel()` now resolves prior-session close on the full calendar (pass 1)
before the 7-bar analysis filter (pass 2); a close counts as observed only if its last bar starts
15:30 or 11:30. Evidence given: 8 changed `prev_close` days per complex (2023-11-27, 2024-07-05,
2024-12-02, 2024-12-26, 2025-07-07, 2025-12-01, 2025-12-26, 2026-02-03). **Verify in the code that
the two passes are actually ordered as claimed and that the half-day bar-start whitelist cannot let a
mid-session data gap impersonate a close.** Are the 8 dates the complete set they should be?

**R2 — H1 used iid percentile bootstrap + Welch t; neither handles volatility clustering.**
Claimed fix: primary inference is now Newey-West HAC event-dummy regression on `log(lasthour_vol)`
plus a stationary bootstrap (Politis & Romano 1994) with expected block length
`1.75*T^(1/3)` = 15.23 from `volpred.stats.mcs._auto_block_length`; Welch/iid retained as labelled
diagnostics; the verdict's `crude_robust` leg now reads the HAC p. **Check the HAC bandwidth rule
matches the repo canonical `dm_test` as README §110 claims, that the bootstrap is applied to the
joint (vol, event) series (not vol alone), and that no diagnostic statistic still feeds a verdict.**

**R3 — "~fully explained" / "is absorbed" overstated a null.**
Claimed fix: verdict rationale, `H1b.identification_note`, `limitations` and README now say "no sharp
joint mechanism detected at this resolution and specification", explicitly a failure to detect, not a
refutation and not evidence of absorption. **Sweep README and every string in the results JSON for
any surviving absorption/explanation language.**

**R4 — QQQ/SPY called an independent replication; 12 tests on nominal p; 14:30 over-claimed.**
Claimed fix: `replication_status` withdraws independence (calls it a consistency check on a highly
correlated complex); Holm across all 12 time-of-day tests, `hac_p` renamed `hac_p_nominal` with
`hac_p_holm` added; every profile row `status='exploratory'`. Reported outcome: **0 of 12 survive
Holm**; smallest nominal p = 0.0044 (SPX 10:30) → Holm p = 0.0527. **Verify the Holm family is the
right 12 and that no bar-level claim survives anywhere in README.**

**R5 — "~2 years / ~500 sessions" contradicted the actual sample.**
Claimed fix: `sample_provenance` emitted from the panel; the power-limitation string is formatted at
run time so it cannot drift. Reconciliation: 730 calendar − 10 non-7bar = 720, − 1 first day = 719.
**Confirm no hardcoded sample claim survives anywhere.**

Then, independently of R1–R5:

- **Lookahead.** `event_threshold` is "expanding `shift(1)` top-decile of `|r_intra|`, min 60d".
  Verify in code that the threshold at day *t* uses only data through *t−1*, and that the 60-day
  warmup is excluded rather than silently classified.
- **Did the remediation introduce anything new?** Diff rev2 against `rev1_K1720_results_snapshot.json`.
  Any number that moved should be explained by R1's 8 changed days or R2's inference switch. Flag any
  unexplained movement.
- **Is `NULL` the honest verdict?** `verdict.primary = "NULL"` with `crude_amplification_robust_both_complexes = true`.
  Check the pre-registered ladder in README §117–121 was applied as written and not adjusted after
  seeing results.

## Output contract

Write to `storage/ops/codex_reviews/k1720_r2_verdict.md`. **First non-empty line exactly one of:**

```
VERDICT: PASS
VERDICT: FAIL
```

`PASS` = all five round-1 findings genuinely resolved and no new blocking defect; the experiment can
merge and be written into the knowledge base. `FAIL` = at least one finding not really fixed, or a new
blocking defect. For every R1–R5 give an explicit `RESOLVED` / `NOT_RESOLVED` with the file:line or
JSON path you checked. List non-blocking nits separately.

A `PASS` merges this into main permanently. Be adversarial — a paper-thin fix that only changes
wording is `NOT_RESOLVED`.
