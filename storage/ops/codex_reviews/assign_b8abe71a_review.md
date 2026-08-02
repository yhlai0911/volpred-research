# assign_b8abe71a — K1380_v4 model-integrity / inference closure receipt

Review fixed point: `f200ef1c2cf8cbb852dc185491e945b6239a7302`

## Scope

- Determine whether A5/C2/C3 were genuinely poor or were broken implementations.
- Audit knowledge for the superseded RC/SPA numbers and downstream use of the loss matrix.
- Independently review the canonical RC/SPA correction semantics.
- Preserve Paper 9 C3's prohibition on the old single-spec-RC and least-favourable-SPA readings.

## Symptom and root-cause evidence

- The old matrix reproduced A5/C2/C3 t-statistics of −11.209/−21.067/−9.963 and
  144/499 least-favourable exceedances attributed only to those specs.
- In the same first 2,000-day window, old A5 declared a positive VIX-slope bound
  but did not pass bounds to Nelder-Mead; it accepted `theta=(-2.4740,-0.35099)`.
  The repaired fit returns `theta=(-11.6674,+0.13040)`.
- Old C1/C2/C3 likelihoods contained only K+1 daily returns: 7/13/25 for
  K=6/12/24. C1 was therefore permanently rejected by its `<10` guard; C2/C3
  were estimated on tiny, frequency-misaligned samples and started OOS at `g=1`.
- After the full-history repair, the new fixed-span panel uses 2,000/2,000/2,000
  daily likelihood rows in the first C1/C2/C3 window. Each is mapped to M-1…M-K
  completed-month mean log-VIX values and filters state through the training tail.

## TDD and institutionalization

- `bounded_multistart_minimize` rejects unsuccessful, non-finite, out-of-bounds
  and penalty-objective results; a failed lower-objective iterate cannot win.
- `fixed_span_midas` owns daily/monthly alignment, completed-month forecast lags,
  bounded fitting, training-tail filtering and Eq.4 current-month-tau recursion.
- Focused regressions cover A5's slope bound, failed-iterate rejection,
  full-history daily/monthly alignment, partial-month exclusion, state recursion,
  B-series canonical optimizer use, stale-state clearing, finite Monte Carlo
  p-values, long-run scaling, one full-chain entrypoint and forbidden legacy C3 wording.

## Full live read-back

- Final full 1,900-day OOS run completed in 1,415 seconds; 13 non-benchmark specs
  are eligible and `n_valid_spa=1,898`.
- A5/C1/C2/C3 each have 1,898 valid forecasts (99.89%) and 31 accepted refits.
  Their new raw-scale diagnostic t-statistics are +2.617/+2.844/+2.261/+2.394.
- B1/B2/B3 clear old state before every scheduled refit; 24/23/29 of 31 fits
  passed the fail-closed contract. Their 76.68%/73.42%/93.26% coverage is below
  95%, so all three are excluded rather than silently filled with stale forecasts.
- B0 applies the same stale-state rule and has 31/31 accepted refit receipts.
- The correction reproduces all four base statistics exactly (`atol=1e-12`),
  then yields long-run-scale SPA_l/c/u and White RC `p=0.0020`, Holm 13/13
  rejections (A4f adjusted `p=0.0260`), and zero least-favourable exceedances.
  Historical A5/C2/C3 tail attribution is gone.
- Final `reproduce_spec.json` has `run_pipeline.py` as its only entrypoint and
  hash-binds both child scripts, data, optimizer, fixed-span and inference helpers,
  loss matrix, base result and canonical result; runtime=1,419 seconds and network
  policy is `deny`. Both child scripts refuse standalone execution. Stage files are
  individually atomic; the multi-file chain is explicitly non-atomic and partial
  interruption is detected by output/spec/commit hash mismatch.

## Knowledge audit

- Exact indexed/targeted audit found no knowledge entry repeating p=0.2886 or the
  old single-spec RC headline. It did find K1583 (`item_id=2e9fbbd9`), whose MCS
  conclusion consumed the broken K1380 matrix.
- K1583 was revised through `scripts/revise_knowledge_entry.py`, not hand-edited:
  verdict `SUPERSEDED`, old bytes retained in `revisions[]`, and a rerun on the
  rebuilt matrix is required before any replacement conclusion.

## Gates before independent review

- Artifact gate: PASS (strict spec, result identity clean).
- Experiment-integrity gate: PASS (4/4).
- Focused assertions: 40 passed. The pre-commit process exits non-zero only
  because CI-parity correctly sees the new test as untracked; normal parity must
  be rerun after the atomic commit.

## Independent two-axis review

The first Spec and Standards rounds both returned FAIL and identified false base
labels, partial first-month VIX, raw-SD studentization, exact-zero Monte Carlo p-values,
duplicate B fail-open fitting and partial-stage reproduce specs. The second round
found stale B0 benchmark state plus three evidence/provenance overclaims. Every item
was fixed, regression-covered and included in a subsequent full-chain rerun.

Third-round byte-bound verdicts:

- **Spec: PASS**, no remaining P1/P2. It independently read back B0 31/31 receipts,
  C1/C2/C3 first-window 2,000 rows, truthful non-atomic pipeline metadata and current
  source/result/spec hashes.
- **Standards: PASS**, no remaining P1/P2. It independently read back all 7 inputs,
  2 declared outputs, canonical result identity, stale-report deletion, focused tests,
  ruff, strict artifact gate and 4/4 integrity gates.

Machine-readable disposition: `experiments/K1380_v4/review_verdict.json`.

After pre-commit required an inline `silent-ok` explanation on the per-start optimizer
exception, the helper was changed without behavioral effect and the full 1,900-day
pipeline was rerun again. Final Spec and Standards delta reviews both PASS; they
verified helper hash `594b08da…` and unchanged scientific outputs.

The first post-commit clean-clone rerun matched all 112 numeric scalars but correctly
failed on two artifact-generation pointers: the base output hash and its derived
generation ID. Root cause was wall-clock elapsed/timestamp embedded in the declared
base output. Those non-scientific fields were removed rather than ignored, and a fifth
full-chain run rebuilt deterministic base/canonical artifacts (1,419.066-second spec).

Final reproducibility-delta review also passed on both axes with no P1/P2. The Spec
review verified that model, loss, valid-mask, B0 comparator, RC/SPA/Holm and verdict
bytes did not change; the Standards review verified all pinned hashes and confirmed
that the delta introduced no new lint finding. Both reviewers require the same final
closure gate: commit these deterministic bytes, then replace the retained pre-fix FAIL
report only with a new clean-clone PASS receipt.
