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
- The new fixed-span panel uses 1,887/1,760/1,510 daily likelihood rows in the
  first window, each mapped to M-1…M-K completed-month mean log-VIX values, and
  filters short-run state through the training tail.

## TDD and institutionalization

- `bounded_multistart_minimize` rejects unsuccessful, non-finite, out-of-bounds
  and penalty-objective results; a failed lower-objective iterate cannot win.
- `fixed_span_midas` owns daily/monthly alignment, completed-month forecast lags,
  bounded fitting, training-tail filtering and Eq.4 current-month-tau recursion.
- Six focused regressions cover A5's slope bound, failed-iterate rejection,
  daily/monthly alignment, partial-month exclusion, state recursion and forbidden
  legacy C3 wording.

## Full live read-back

- Full 1,900-day OOS run completed in 1,336 seconds; 16/16 non-benchmark specs
  are eligible and `n_valid_spa=1,898`.
- A5/C1/C2/C3 each have 1,898 valid forecasts (99.89%) and 31 accepted refits.
  Their new t-statistics versus B0 are +2.617/+2.659/+2.200/+2.378.
- The correction reproduces all four base statistics exactly (`atol=1e-12`),
  then yields SPA_c/SPA_u/White RC `p < 1/499`, Holm 15/16 rejections, and zero
  least-favourable exceedances. Historical A5/C2/C3 tail attribution is gone.
- Final `reproduce_spec.json` hash-binds the base script, optimizer, fixed-span
  helper, loss matrix, base result, correction, inference helper and finalizer;
  network policy is `deny`.

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
- Focused assertions: 49 passed. The pre-commit process exits non-zero only
  because CI-parity correctly sees the new test as untracked; normal parity must
  be rerun after the atomic commit.

## Independent two-axis review

Pending Spec and Standards reviewers. This section must be updated with their
final P1/P2 disposition before closure.
