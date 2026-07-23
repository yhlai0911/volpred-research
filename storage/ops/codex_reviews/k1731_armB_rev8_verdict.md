# Codex Round-8 Review — `assign_24ebe308`

## Scope

- Baseline: `03c0fb8ca71f305c7f9d91673cc5fc38c2275d04`
- Frozen target: `bb57bda984475a4732051b8f96a09697bb9f7236`
- Review limited to `03c0fb8ca..bb57bda98`; later commits are excluded.
- All 20 SHA-256 entries in `k1731_armB_rev8_freeze.txt` match the target blobs.

## Checks

- Nested/non-nested DM branching passes. `NESTED_BENCHMARKS={"GEV-HAR"}`
  drives a shared source/finalizer implementation; nested rows are
  `diagnostic_only_not_a_test` with `hac_pm1p96se_*_no_coverage`, while
  non-nested rows retain CI semantics.
- Canonical regeneration and numeric drift pass. Reapplying the frozen source
  and finalizer in memory to all three rev7 artifacts produced zero leaf
  mismatches after excluding `finalized_utc`. Numeric change/add/remove counts
  were zero; all 16 renamed numeric leaves retained exact values. The frozen
  drift artifact also records 64/64 interval leaves rechecked with zero mismatch.
- README headline, section 3.3, and section 6 correctly downgrade the claim to
  weak in-sample selection plus an uncorrected directional OOS diagnostic.

## Blocking finding — unsupported OOS null remains on a canonical artifact surface

The canonical finalizer still says a low PIP is "evidence of no effect" and that
"the arm B null rests most solidly on CPI, UNRATE, VIX and TERM" in
`ARM_A_ENGINE_ISSUES[*].why_it_matters`:

- `bb57bda98:experiments/k1731/k1731_finalize_report.py:278-287`

The finalizer regenerates that text into all three result artifacts, including
the only citeable primary artifact:

- `k1731_gevreg_midas_ssvs_returns_results.json:56`
- `k1731_gevreg_midas_ssvs_returns_results_corrected.json:71`
- `k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json:71`

This contradicts the README and `headline_verdict`, and violates the required
claim downgrade. It is not superseded prose or a hand-edit: canonical
regeneration actively recreates it.

The 107-check gate misses this surface. Its artifact prose scan covers only the
nested rows, `headline_verdict`, and `cross_arm_comparison`; its concept scan
covers only README. Therefore 107/107 plus zero README violations is a silent
false pass for this claim.

## Non-blocking gate weakness

`k1731_rev8_drift_check.py` fails on changed numeric leaves and interval-rerun
mismatches, but not on numeric additions/removals. Independent leaf comparison
confirmed there are no numeric additions/removals in the frozen artifacts, so
this does not create a second blocker for round 8.

VERDICT: FAIL
