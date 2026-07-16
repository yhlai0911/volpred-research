# K1695 Exposure-Correction Certification Review

**VERDICT: PASS** (no blocking defects)
**Reviewer:** feature-dev:code-reviewer subagent (fresh-context), main-thread dispatched
**Reviewed:** 2026-07-15 台灣時間
**Frozen commit reviewed:** bdf6b451f (`fix(k1695): retract the 13-market drawdown claim — it was an exposure artifact`)
**Scope:** the 2026-07-15 exposure-correction added to `k1695.py` (+880 lines vs a20099d99), `k1695_results.json`, `table5_rows.csv`, `common_sample_rows.csv`, `circular_shift_null_gaps.csv`, `README.md`, `test_k1695.py`.

This certifies the **retraction/correction** of K1695's original drawdown-protection claim, per 研究誠實原則第 6 條 (推翻舊結論必回溯更正).

## Checklist results

1. **Canonical drawdown tool — PASS.** Every exposure-matched gap routes through `volpred.stats.drawdown.compare_max_drawdown` (`k1695.py:1229`, `:1140`). Vectorized twin `exposure_matched_mdd_by_column` (`:683`) is fail-closed asserted against the canonical scalar helper via `assert_vectorized_matches_canonical` (`:703`, tol 1e-12, invoked `:1596` before any bootstrap/null). `circular_shift_null` re-asserts shift-0 equivalence (`:990-996`). All `raise`, not `warn`. Unit tests confirm zero-gap and equivalence (`test_k1695.py:218`, `:237`).

2. **Circular-shift null correctness — PASS** (one disclosed non-blocking nuance). Exact enumeration over all calendar-month phases (deterministic, no seed needed). `_shifted_target_matrix` (`:913`) rolls each market's own traded months with a runtime assertion no shift introduces an unheld weight (`:986-989`). p-value one-sided `n_ge/n_shifts` with shift-0 included so p can never be 0 (`:1009-1023`). Holm step-down correct (`:1106-1121`). *Non-blocking:* cross-market shift-sharing exactly preserves dependence only for the first `min(own_months)` shifts (documented); does NOT affect the common-period headline (aligned samples) or Holm/CI conclusions (0/13 survivors either way).

3. **Raw numbers preserved — PASS.** `average_delta_mdd_pp` (+12.61 common / +27.50 inception, both 13/13) retained alongside exposure-matched at every level. `test_results_json_never_reports_raw_mdd_without_its_exposure_companion` (`test_k1695.py:288`) mechanically locks this.

4. **Lookahead — PASS.** `.shift(1)` on monthly-VIX target in both `build_monthly_lagged_weights` and null-path twin (`:502`, `:845`). IRX forward-fill-then-shift unchanged (`:508-519`). No new lookahead surface.

5. **Number consistency — PASS.** Byte/decimal alignment verified across README / results.json / CSVs for every headline: common matched −0.8654 → "−0.87pp"; inception +4.9556 → "+4.96pp"; 7/13 & 12/13; null p 0.559/0.212; Holm survivors 0/0; no-timing raw 10.68/16.20 & matched +0.01/−0.06; raw 12.61/27.50. `circular_shift_null_gaps.csv` shift_months=0 matches results.json common summary to 12 decimals.

6. **No-timing reference strategy — PASS.** `constant_weight_reference` (`:1124`) with each market's mean weight, zero VIX input, reproduces 59%/85% of the raw "protection" while its matched gap is ~0 — directly demonstrating the artifact. Locked by `test_no_timing_reference_reproduces_the_raw_gap_with_zero_matched_gap`.

7. **README honesty — PASS.** Retraction banner explicit and unhedged ("這個結論是錯的"); four distinct strength lines; proactively surfaces the one number that could argue the correction away (raw stat rejects its own null at p=0.039 on long sample) with a measured mechanism explanation. No residual overclaim ("passed gate", "dependence-robust protection") survives.

## Blocking defects
none

## Non-blocking follow-ups (not gating)
- Cross-market shift-sharing nuance in circular-shift null — one-line docstring/README addendum next revision.
- Primary-path Codex re-verify recommended (subagent PASS ≠ Codex PASS per `.claude/rules/experiments.md`) — enqueued as belt-and-suspenders.
