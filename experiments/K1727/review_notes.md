# K1727 collection review — subagent-fallback certification

**Reviewer**: subagent (general-purpose, opus, xhigh-equiv adversarial review), dispatched by main thread `hourly-slot-2`.
**Why not Codex**: Codex primary review path credit-limited until 2026-08-02 (see knowledge K1728, 2026-07-28). Subagent-fallback code review is the sanctioned interim path.
**Reviewed bytes**: worktree `dispatch-slot-4-6ba995a0-k1727` @ commit `1d9348c7e914fa93faf5846515dd828cdd14a18b` (frozen; files unmodified since compute-agent finish 2026-07-27T19:44Z).
**Reviewed at**: 2026-07-28 (台灣時間, PHASE A collection).

## Verdict: PASS (merge-safe) — scientific strength: CONDITIONAL_PASS (null / does not reproduce at daily ETF frequency)

The binary merge gate asks "is this code correct, lookahead-guarded, reproducible, and honestly reported?" — yes on all counts, zero blocking defects. The "CONDITIONAL_PASS" ceiling is about the *strength of the scientific claim* (per-asset bootstrap CIs all straddle zero → directional-not-significant), not a code defect; that caveat is recorded in the knowledge.json entry, not as a merge blocker.

## Checklist
- **Lookahead: PASS.** `build_vol_target` (K1727.py:140-144): `position = raw_scale.shift(1)`; `vt_excess = position * excess` (line 153) so `vt_excess_t = raw_scale_{t-1}·excess_t`. Baseline `fixed_excess = excess` (line 152), unit exposure, no signal×same-day-return anywhere. `excess = ret - rf_daily` (line 137); `pct_change(fill_method=None)` (line 240) avoids forward-fill leakage. Diagnostic `vol_return_corr` uses `realized_vol.shift(1)` (line 227).
- **Seed: PASS.** `SEED=42` (line 52); `np.random.seed(42)` (line 335); bootstrap `default_rng(seed=SEED)` (lines 206, 251). Reproducible.
- **Bootstrap: PASS.** Paired moving-block (block=21, reps=1000), same resampled `idx` applied jointly to both series (line 213). CI = 2.5/97.5 pct; `p_gain_gt_0 = mean(gains>0)`.
- **MDD comparability: PASS.** Delegated to `compare_max_drawdown`; results carry `exposure_mismatch` / `exposure_matched_gap` and the "necessary-not-sufficient for timing skill" note. No raw-MDD-as-skill claim.
- **Group contrast: PASS.** Per-asset scalars averaged only; "Descriptive contrast only (n=4 per group). No asset-day pooling (K1355 rule)."
- **Sanity vs priors: consistent.** SPY +0.081, QQQ +0.100 modest-positive matches JPM; HYG −0.044 / TLT +0.052 make the risky/non-risky partition internally inconsistent — README flags this honestly. 60-day robustness reverses the contrast. `vol_return_corr≈0` = coherent mechanism-absent explanation.
- **Data integrity: no material issue.** auto_adjust close, own longest history per asset, `^IRX` rf with documented 0.0 fallback.

## Issues found (both MINOR, non-blocking)
- MINOR (lines 206, 251): all assets share `default_rng(42)`, so equal-length series draw identical block-start sequences → bootstrap streams not independent across assets. Harmless for per-asset inference; noted for transparency.
- MINOR (README lines 107-114): per-asset Sharpe fixed/VT columns rendered as "—" though values exist in JSON. Cosmetic.

## Honest interpretation
K1727 is a clean, lookahead-guarded, reproducible daily-ETF re-validation that does NOT reproduce the JPM "VT lifts risk-adjusted returns for risky assets" claim in the Sharpe channel: no single asset shows a statistically distinguishable VT Sharpe gain (all 8 bootstrap 95% CIs straddle zero). Group means lean weakly in the hypothesized direction (risky +0.053 vs non-risky +0.010, diff +0.043) but this is a tiny, non-significant, non-robust (reverses at 60-day window), internally-inconsistent n=4-per-group descriptive contrast. A risky/non-risky split appears only in the exposure-matched drawdown gap, which is necessary-not-sufficient for timing skill and lies outside the stated Sharpe hypothesis. Consistent with the project prior that daily VT "moves along the same risk-return line."

## Re-certification 2026-07-28 (README honesty edit)

**Reviewer**: subagent/general-purpose opus (independent re-cert; Codex credit-limited until 2026-08-02 per K1728).
**Trigger**: after the prior PASS certification, the main thread made ONE documentation-only edit to the README `## Result` headline — softening an overclaim ("statistically absent for every asset") into the correctly-hedged "not statistically distinguishable from zero / every bootstrap CI straddles zero, so the study is underpowered rather than proof of a true null; the +0.043 risky-minus-non-risky gap is directional but tiny, not robust, internally inconsistent."

**What changed**: README `## Result` verdict paragraph only. `K1727.py`, `K1727_results.json`, and `K1727_sharpe_gain.png` are byte-identical to the prior certification (sha256-pinned in review_verdict.json; unchanged).

**Gate results (re-verified independently against the frozen bytes):**
- **Lookahead: PASS.** `build_vol_target` K1727.py:144 `position = raw_scale.shift(1)`; :153 `vt_excess = position * excess` → `vt_excess_t = raw_scale_{t-1}·excess_t`; baseline `fixed_excess = excess` (:152). `pct_change(fill_method=None)` (:240). Diagnostic `vol_return_corr` uses `realized_vol.shift(1)` (:227). No same-day signal×return contamination.
- **Seed: PASS.** `SEED=42` (:52); `np.random.seed(SEED)` (:335); bootstrap `default_rng(seed=SEED)` (:206) called with `SEED` (:251). Reproducible.
- **Excess returns: PASS.** `excess = ret - rf_daily` (:137); Sharpe (:162-168) computed on `vt_excess` and `fixed_excess`, i.e. excess for BOTH legs. JPM-faithful.
- **README honesty: PASS.** The edited `## Result` headline now correctly frames the outcome as directional/underpowered (all 8 CIs straddle zero → not a proven null), and does NOT underclaim: it still credits the weak +0.043 hypothesis-direction gap while flagging it as tiny/non-robust/internally-inconsistent. README numbers cross-check against the JSON (e.g. SPY gain +0.081, CI [−0.137,+0.300]). No overclaim, no underclaim.
- **No new correctness red flags.** Edit is documentation-only; compute artifacts unchanged.

**Verdict: PASS (merge-safe). Zero blocking defects.** Scientific ceiling remains CONDITIONAL_PASS (directional-not-significant null), which is a claim-strength note, not a merge blocker.
