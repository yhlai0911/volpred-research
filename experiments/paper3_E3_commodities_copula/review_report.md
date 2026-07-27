# Paper3_E3 — Primary-path review report

**Verdict:** PASS
**Reviewer:** main-thread primary-path audit (Claude Opus 4.8 / high). Codex background
review task (`task-ms3b1q7y-vbqb7w`) was launched via codex-rescue but orphaned when the
subagent returned; no verdict materialized after ~6 min, so the collecting main thread
performed the audit directly. Defensible because E3's numerical core is proven
byte-identical to Paper3_E2, which already passed Codex review and is merged.
**Reviewed frozen commit:** 376b708cea010b4d29000b4de952026daeaacaea
**Review date:** 2026-07-27

## Checks

1. **dm_test verbatim E2 — PASS.** `dm_test` extracted from both files is byte-identical
   (diff empty). `significant_harvey = abs(HLN_factor * raw_t) > student_t.ppf(0.975, df)`;
   there is **no** E1 hardcoded `abs(t) > 3.0`. This is the shared E2 ruler.

2. **Core machinery unchanged — PASS.** md5 of each core function is identical between
   E2 and E3: `estimate_a4f_asym`, `estimate_dcc`, `fit_copula_t`, `fit_clayton`,
   `rolling_var_es`, `trinity_backtest`, `fz_loss`, `compute_lambda_L`, `recursive`.
   Non-comment diff is limited to: asset registry / pair list / region-class labels,
   headers/paths/plot colours, verdict strings, the new top-level `aggregate` block, and a
   per-pair **checkpoint batch harness** (`_pair_cache_path`, `assemble`, `compute_pairs`,
   `load_cached_pairs`) that only orchestrates pair execution + assembly and does not touch
   the numerical core.

3. **BH-FDR loop — PASS.** Standard Benjamini-Hochberg step-up over the 16 two-sided
   DCC-vs-copula DM p-values (paper3_E3.py ~1621-1638): largest rank k with
   `p_(k) <= (k/m)*q` marks all ranks <= k as survivors, then intersected with
   `copula_better` so a DCC-favouring significant test is not miscounted as a copula win.
   q10 = 0, q05 = 0.

4. **Scaling adjudication logic — PASS.** `e2_reverse_sign_replicates_in_commodities`
   requires the E3 Student-t scaling sign to equal E2's `negative` **and** p < 0.05. E3
   got rho = +0.190 (positive), p = 0.65 => replicates = false => E2's reversal is
   arm-specific. Reported honestly regardless of direction.

5. **Lag / lookahead — PASS.** GARCH/marginal/DCC recursions use `returns[t-1]`, `h[t-1]`,
   `x2[t-1]`, `eps[t-1]`, `q[t-1]` (lines ~271-335); refit through t-1; portfolio return
   realized at t. No same-day signal x same-day return.

6. **Artifact + integrity gates — PASS.** `check_experiment_artifacts` (strict) and
   `experiment_gates run` (4 integrity gates) both PASS; reproduce_spec sha matches.

7. **Headline self-consistency — PASS.** README numbers match `paper3_E3_results.json`
   aggregate: n_harvey_sig = 1 (COPPER-SPY), n_bh_fdr_q10 = 0, n_bh_fdr_q05 = 0,
   Student-t rho = +0.190 p = 0.651, Clayton rho = -0.515 p = 0.192.

## Conclusion

Clean NULL result. No defensible Copula-GARCH VaR/QLIKE advantage over DCC-A4f-ASYM in
commodities (1/8 uncorrected Harvey hit COPPER-SPY, 0 survive BH-FDR). The
no-copula-advantage result now spans a third, non-equity asset class (E1 individual
stocks + E2 cross-market equity + E3 commodities). E2's reverse-sign lambda_L -> DM
scaling does **not** replicate in commodities => arm-specific, not a cross-asset-class law.
