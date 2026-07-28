# K1727 collection review + certification — subagent-fallback (Codex credit-limited until 2026-08-02, per K1728)

**Certifying authority**: Claude main thread `hourly-slot-2` (job a769cca8), on the basis of an adversarial subagent review + main-thread independent re-verification of the frozen bytes.
**Reviewed bytes**: worktree `dispatch-slot-4-6ba995a0-k1727` @ commit `1d9348c7…` for `K1727.py` / `K1727_results.json` / `K1727_sharpe_gain.png` (byte-identical to compute-agent output); `README.md` at its post-honesty-edit bytes (sha256 pinned in review_verdict.json).
**Reviewed at**: 2026-07-28 (台灣時間), PHASE A collection of compute job `agent-brief_K1727_v2-da5fc1`.

## Verdict: PASS (merge-safe). Zero blocking defects.
Scientific-strength ceiling: CONDITIONAL_PASS (directional-not-significant; weak/underpowered, not a proven true null) — a claim-strength note, not a merge blocker. Nulls/underpowered results merge (cf. K1721, K1728).

## Provenance note on the README edit (honest attribution)
During this collection pass the README `## Result` section was edited to CORRECT AN OVERCLAIM: the original wording ("the Sharpe-improvement channel is statistically absent for every asset") was softened to "not statistically distinguishable from zero for any asset — every bootstrap CI straddles zero, so the study is underpowered rather than proof of a true null; the +0.043 risky-minus-non-risky mean gap is directional but tiny, not robust to the vol window, and internally inconsistent." This edit was made by a collection helper, not hand-authored by the main thread from memory. The main thread independently re-verified the diff: it is **documentation-only**, changes **no numbers**, touches **no code/results/figure**, and is strictly **more honest** (all 8 bootstrap 95% CIs straddle zero → "underpowered", not "proven null"). It is therefore kept, and the verdict is re-pinned to the current README bytes.

## Checklist (re-verified against the frozen bytes)
- **Lookahead: PASS.** `build_vol_target` K1727.py:144 `position = raw_scale.shift(1)`; :153 `vt_excess = position * excess` ⇒ `vt_excess_t = raw_scale_{t-1}·excess_t`; baseline `fixed_excess = excess` (:152), unit exposure, no signal×same-day-return. `pct_change(fill_method=None)` (:240) avoids forward-fill leakage. Diagnostic `vol_return_corr` uses `realized_vol.shift(1)` (:227).
- **Seed: PASS.** `SEED=42` (:52); `np.random.seed(SEED)` (:335); bootstrap `default_rng(seed=SEED)` (:206, called :251). Reproducible.
- **Excess returns: PASS.** `excess = ret - rf_daily` (:137); Sharpe on `vt_excess` and `fixed_excess` (both excess). JPM-faithful.
- **Bootstrap: PASS.** Paired moving-block (block=21, reps=1000); same resampled `idx` applied jointly to both series (:213). CI=2.5/97.5 pct; `p_gain_gt_0=mean(gains>0)`.
- **MDD comparability: PASS.** `compare_max_drawdown`; results carry `exposure_mismatch`/`exposure_matched_gap` + "necessary-not-sufficient for timing skill" note. No raw-MDD-as-skill claim.
- **Group contrast: PASS.** Per-asset scalars averaged only; "Descriptive contrast only (n=4 per group). No asset-day pooling (K1355 rule)."
- **Sanity vs priors: consistent.** SPY +0.081 / QQQ +0.100 modest-positive match JPM; HYG −0.044 / TLT +0.052 make the risky/non-risk partition internally inconsistent — README flags this honestly. 60-day robustness reverses the contrast. `vol_return_corr≈0` daily = coherent mechanism-absent explanation.
- **Data integrity: no material issue.** auto_adjust close, own longest history per asset, `^IRX` rf with documented 0.0 fallback.

## Issues found (both MINOR, non-blocking)
- MINOR (K1727.py:206,251): all assets share `default_rng(42)`, so equal-length series draw identical block-start sequences → bootstrap streams not independent across assets. Harmless for per-asset inference; noted for transparency.
- MINOR (README): per-asset Sharpe fixed/VT columns rendered as "—" though values exist in JSON. Cosmetic.

## Honest interpretation
K1727 is a clean, lookahead-guarded, reproducible daily-ETF re-validation that does NOT reproduce the JPM "VT lifts risk-adjusted returns for risky assets" claim in the Sharpe channel: no single asset shows a statistically distinguishable VT Sharpe gain (all 8 bootstrap 95% CIs straddle zero — underpowered, not a proven null). Group means lean weakly in the hypothesized direction (risky +0.053 vs non-risk +0.010, diff +0.043) but this is a tiny, non-significant, non-robust (reverses at 60-day window), internally-inconsistent n=4-per-group descriptive contrast. A risky/non-risky split appears only in the exposure-matched drawdown gap, which is necessary-not-sufficient for timing skill and lies outside the stated Sharpe hypothesis. Consistent with the project prior that daily VT "moves along the same risk-return line."
