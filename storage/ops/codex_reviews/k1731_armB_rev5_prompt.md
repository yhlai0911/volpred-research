# Codex primary-path review — K1731 arm B (GEVReg-MIDAS-SSVS, SPY tail-interval forecasts), rev5

You are the primary-path reviewer. This experiment has already been through three Codex rounds
(rev2 / rev3 / rev4). Every earlier `review_verdict.json` is **sha-invalidated by construction**:
this segment changed `k1731_regression_check.py`, `k1731_finalize_report.py`, all three results
JSONs and `README.md`. Review the CURRENT bytes; do not carry forward an earlier verdict.

## Where everything lives

Working tree (read-only for you):

```
.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/
```

Read, at minimum:

- `README.md` (687 lines — this is the claim surface under review)
- `k1731_armB_esfix.json` (this segment's self-report: verdict, regression_check, finalize,
  es_impact, readme_traceability)
- `k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json` — **PRIMARY** artifact
- `k1731_es_mixture_check.py` + `k1731_es_mixture_check_results.json` — the ES estimator proof
- `k1731_regression_check.py` + `k1731_regression_check_results.json` + `regression_baseline/`
- `k1731_finalize_report.py` — provenance stamping
- `k1731_models.py`, `k1731_gevreg_midas_ssvs_returns.py`, `k1731_scoring.py` — the estimation path
- `k1731_armB_verification.json` — the previous segment's verdict (`needs_fix`), i.e. the
  defect this segment claims to have closed

**Do not cite** `k1731_gevreg_midas_ssvs_returns_results.json` or
`..._results_corrected.json` — both are stamped `do_not_cite` and superseded by rev5.

## What this segment claims to have done

The SSVS **expected-shortfall estimator** was wrong and has been replaced:

- old: average, over posterior draws, of each draw's tail expectation beyond *its own* quantile
- new: tail expectation of the **posterior mixture** beyond the reported mixture VaR, closed-form
  given the threshold

Claimed consequences (`es_impact` in `k1731_armB_esfix.json`):

- `conclusion_flipped: false`
- 95%: ES backtest rejection SURVIVES (p 0.0145 → 0.0181, still < 0.05)
- 99%: non-rejection SURVIVES (p 0.0637 → 0.0876, still > 0.05)
- both p-values rise, which is the direction the bias predicts
- closed-form identity max relative error 1.07e-14 over 1120 cases
- realised effect on mean predicted ES: +0.364% (95%), +0.718% (99%) — while adversarial
  *synthetic* stress mixtures span 3.85–22.77%. README §3.5 is claimed to state that the
  synthetic range must not be quoted as this experiment's error.
- regression gate PASS: 3834 leaf values compared, 22 changed by design, 19 non-deterministic,
  0 out-of-allowlist. `refits_ssvs_leaves_differing: 0`.
- README traceability: 50 numbers in §3.1 and §3.5 re-read programmatically from rev5, 0 mismatches.

## What you must adjudicate

Judge substance, not tidiness. Specifically:

1. **Is the new ES estimator actually the right estimator?** Derive it yourself. For a posterior
   mixture of predictive densities, the coherent ES at level α is the tail expectation of the
   *mixture* beyond the *mixture* VaR — verify the code computes that, not a per-draw average
   dressed up. Check `k1731_es_mixture_check.py`'s closed form against your own derivation.
2. **Is `conclusion_flipped: false` honest?** A p-value moving 0.0145 → 0.0181 keeps the sign but
   shrinks the margin. Does the README tell the reader that part of the original 95% rejection was
   an estimator artifact, or does it quietly keep the old framing? Check §3.5 and §6 (Honest
   conclusions) directly.
3. **Is the 99% case robust?** p 0.0637 → 0.0876 is a non-rejection that got *less* marginal, but
   both sides of 0.05 matter for how it is written up. Is the README claiming absence of evidence
   as evidence of absence anywhere?
4. **Regression gate integrity.** `k1731_regression_check.py`'s allow-list now imports
   `FINALIZE_OWNED_KEYS` from the finalizer (single source of truth). Verify that this coupling
   cannot let a real drift be waved through: an allow-list that the *audited* script defines is
   a structural conflict of interest unless the allow-listed keys are provably narrative-only.
   The self-report's `blind_spot_analysis` argues exactly this — check the argument, do not accept it.
5. **The disclosed false-fail.** The first gate run reported FAIL with 57 drifts, all
   `status=removed`, attributed to a stage mismatch in the frozen baseline. Confirm that
   explanation from the bytes (`regression_baseline/`), and confirm the fix was to the *baseline
   selection*, never to the data.
6. **Provenance invariant.** Exactly one artifact must carry `is_primary=true`, and the two
   superseded files must carry `do_not_cite` with a supersession reason pointing at rev5. Verify
   in the JSONs themselves, not in the finalizer's print output.
7. **Anything the earlier rounds fixed that rev5 silently re-broke.** §10 has the review trail.
8. **Claim–evidence matching across the whole README.** Any sentence whose scope exceeds what the
   rev5 artifact supports is a FAIL, however small.

## Standing repo rules you are enforcing

- No lookahead: signals must be lagged in code, and baselines must use the same lag.
- DM tests on nested models need the appropriate correction; HAC where serial correlation is present.
- Results that look too good are ~90% a bug.
- Research honesty outranks a clean narrative. A null that is written up as a null is a PASS.

## Output

Write a Markdown report with, at the top, one line exactly:

`VERDICT: PASS` or `VERDICT: FAIL`

FAIL if any claim overstates its evidence, any estimator is wrong, or any gate is
structurally unable to catch what it purports to catch. Then, for each of the 8 points above,
a short section: what you checked, what the bytes said, and your judgement. End with a
`## Blocking issues` list (empty if PASS) where each entry is specific enough to act on
without re-deriving your reasoning — file, line/field, what is wrong, what would fix it.
