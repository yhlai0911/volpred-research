# K1738 code review

Reviewed on 2026-08-02 against the incomplete checkpoint commit
`f258ae7a4` and the final hash-pinned working-tree artifacts. The review used two
independent axes (repository Standards and task Spec) plus an independent methods
audit. Reviewers inspected the implementation, result JSON, rendered README,
runtime reproduction contract, tests, and frozen input identities.

## Round 1 findings and repairs

All three reviews initially failed. The blocking findings were repaired before
certification:

- Criterion c4 had used raw p-values despite preregistering within-month BH FDR.
  The implementation now computes the F3 family across the three horizons and
  uses `q_bh_F3` (0.01825, 0.01425, 0.12734).
- Effects had been described as “per 1 SD” even though the coefficient is per
  treatment unit and the pooled sample SD is 1.5492. Code, result fields,
  renderer, and prose now use the treatment-unit scale consistently.
- SUE coverage had been measured on an already filtered panel. It is now audited
  independently from the frozen earnings cache: 24,884 constructible records of
  26,954 eligible announcement records (92.3%). The frozen cache identity is an
  explicit reproduction input.
- The follow-up brief's claim that EPS Estimate was a seasonal random-walk proxy
  was contradicted by the frozen source fields. The process note now records and
  rejects that assumption; the treatment is analyst-estimate SUE.
- The common OLS/DML sample (24,519 rows) is now distinguished from the peer-IV
  sample (23,519 rows).
- Firm-held-out cross-fitting still shares calendar months between folds. This is
  disclosed as a limitation; two-way clustered score inference does not remove
  nuisance-fit dependence. Stronger claims require multiway cross-fitting. The
  invalid-IV gate already caps the result to conditional association.

## Final Standards review — PASS

The repository's numerical-integrity, provenance, and claim-calibration rules are
satisfied. F3 BH values drive c4; treatment-unit language is consistent; coverage
is reconstructed from an independent frozen input; all runtime inputs are pinned.
The final stale “approximately 1 SD” phrase was removed. No Standards blocker
remains.

## Final Spec review — PASS

The implementation satisfies the registered task contract: the complete cached
DML continuation ran without network access, all declared stages are present,
lookahead controls are stated, the instrument is treated as invalid rather than
promoted causally, the coverage floor is enforced, and artifact identities agree.
No Spec blocker remains.

## Final methods audit — PASS

The FDR, scale, coverage, sample, and instrument-validity repairs are methodologically
consistent. The shared-month cross-fitting limitation is explicit and is acceptable
only with the current conditional-association cap. No Methods blocker remains.

## Evidence and decision

- Full cached rerun: `uv run python experiments/k1738/K1738.py --no-download`
  (458 seconds; `run_complete=true`; no missing stages).
- Experiment gates: all four gates passed.
- Tests: 37 passed. The pre-commit CI-parity wrapper correctly reported the new
  `reproduce_spec.json` as untracked; it must be rerun after the artifact is tracked.
- Result: `CONDITIONAL_PASS`. Signed-SUE DML is BH-significant at one and two
  months, not three months; subperiod consistency fails. The candidate peer-IV is
  relevant (cluster-robust F=31.78) but substantively invalid, so 2SLS is diagnostic
  only and every reported estimate remains a conditional association.

Final review verdict: **PASS**, with no blocking defects.
