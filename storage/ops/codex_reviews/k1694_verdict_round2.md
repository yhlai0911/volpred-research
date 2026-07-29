## Standards

The main estimator repairs are sound:

- `_within_ols()` is algebraically equivalent to `PanelOLS(..., entity_effects=True)` with no constant or time effects.
- The identity assertion runs on the actual 3,278-row spec1 sample before bootstrap draws. The recorded difference is \(4.88\times10^{-19}\).
- Both bootstraps use the reported `SPEC1_RHS`, including `t`, and the exact spec1 row set.
- `_month_blocks_stationary()` correctly implements geometric restarts with mean length six and circular continuation.
- Provenance matches: the on-disk script, `results.code_trace`, and spec entrypoint all have SHA `c4dbb956…`; the canonical result hash also matches its bytes.

However, three process guards remain incomplete:

1. `np.log(oi).diff()` at `K1694.py:514` has no `oi > 0`/finite guard. Current cached OI is strictly positive, so this did not alter this run, but the requested missing/invalid-value repair is incomplete: infinities would survive `dropna()`.

2. The completeness rule is not a general proof of full coverage. `nweeks >= 4` plus a recent final report can accept a five-report month with an interior report missing. Likewise, `rv_ndays >= 15` does not prove that an independently truncated RV download reached month-end. The current cache does drop only 2006-06 and 2026-07 as reported, but the guard can silently accept future partial inputs.

3. The results call the 149 months “independent FCM variation.” They are not independent: cached HHI has ACF(1) 0.964 and ACF(6) 0.817. This should say 149 calendar observations with effective temporal degrees of freedom below 149.

## Spec

Seven of the eight round-1 repair areas are substantially repaired, but the promised predictive specification is still overstated.

`spec4` correctly:

- uses the month-start FCM as-of merge;
- computes expanding labels using information through label month \(t\), then uses the label at \(t+1\), which is legitimate;
- loses exactly \(24\times22=528\) rows through the declared FCM PIT warm-up, not outcome-dependent coefficient selection.

But it is not true that “every regressor is known before the outcome month begins”:

- `nonrep_lag`, `d_nonrep_lag`, and `dlog_oi_lag` use the complete prior-month DCOT aggregate; its last Tuesday observation may be published on Friday after the next calendar month begins. The limitations admit this while the README and JSON continue to claim strict pre-outcome availability.
- `build_spec_frame()` preconditions spec4 on contemporaneous `rv_z`, even though spec4 does not use that regressor. Thus its evaluation sample is not defined solely using its predictive design.
- Most importantly, the FCM availability dates remain synthetic. That disclosure is adequate for spec1–3’s ex-post association, but it cannot certify the README’s claim that spec4 establishes “沒有可預測性”.

The README also says the negative binary effect “不成立” at line 13. The estimators establish only “未獲支持”; line 25 uses the appropriately limited formulation.

## Primary-path judgment

The reported NULL does not appear manufactured:

- Reduced-control within estimates remain positive: \(2.71\times10^{-4}\) without the dynamic/OI controls, \(2.14\times10^{-4}\) with only contemporaneous `dlog_oi`, and \(3.16\times10^{-4}\) in spec1.
- With \(T=149\), Nickell bias from the lagged dependent terms should be small, and it does not explain the positive interaction sign. The contemporaneous OI control remains potentially endogenous/mechanical, but removing it does not reverse the conclusion.
- Independent stationary-bootstrap diagnostics at mean lengths 3, 6, 12, 18, 24, and 36 months all retained zero in the 95% interval. Although six months is not an optimally selected block length, the interaction score’s ACF is small and the NULL is not sensitive to plausible longer blocks.
- Missing RV propagates correctly in the current run: 45 missing `rv` rows correspond to 45 missing `highvol` rows, with no silent zero labels. The adjacency guard also covers all constructed differences and lags.

Therefore, the negative binary association result itself looks credible, but I cannot certify the experiment artifact for knowledge ingestion while it still makes an invalid predictive claim and leaves the completeness/non-positive-OI guards incomplete.

Required before PASS:

- either build a genuinely ex-ante spec4 using verified availability/cutoff rules and a spec4-specific sample, or remove all predictive/no-predictability claims;
- replace “不成立” with “未獲支持” everywhere and describe the temporal effective sample accurately;
- guard non-positive/non-finite OI explicitly;
- strengthen completeness checks so they detect interior weekly gaps and independently truncated RV months, then rerun the artifacts.

VERDICT: FAIL
