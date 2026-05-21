# K1258 Codex Code Review v2 — Primary-Path Re-Verification (CONDITIONAL PASS)

**Review date**: 2026-04-29 (CST), task `task-mojhf3d0-1gfgyn`, 2m 21s
**Reviewer**: Codex CLI 0.121.0 (gpt-5.4 default), session `019dd73b-a1e0-7e52-9cae-83de2a59e2a4`
**Trigger**: K1258 closure (knowledge entry `727e23ee`, confidence 0.88, 2026-04-25
PASS-with-caveats) went through main-thread fallback because Codex CLI was
blocked. Last of 5 fallback-gate closures from 2026-04-26 to 04-28 blocker
window. Per E078 systematic plan.

**Scope**: K1258 forgetting-factor BMA, 3 assets × 5 λ × OOS 2020-2026.

---

## Verdict: **CONDITIONAL PASS** (subagent v1 said PASS-with-caveats / 0.88)

**Findings**: 0 CRITICAL / 0 SEVERE / 2 MAJOR / 2 MED / 1 MINOR

**Comparison vs subagent v1 `727e23ee`**:
- Agree: H1 FAIL, H2 switching restoration, H4 default λ=1.0
- Additional findings: K1257 MAJOR inheritance + unconverged-fit acceptance + H3 over-interpretation
- Contradicts: not full PASS-with-caveats — should be CONDITIONAL PASS with confidence < 0.88

---

## MAJOR-1 — K1257 invalid-model posterior contamination REPLICATED (not fixed)

`k1258_forgetting_factor_bma.py:593` when `ll_row` invalid for a model on
day t, code only adds likelihood for `valid` models but invalid models
**retain their decayed prior**, then all normalize together at `:598`.

Same structural bug from K1257 (Codex K1257 review MAJOR), now embedded in
forgetting-factor recursion. Forgetting factor only **decays** the stale
weight slowly; doesn't fix the bug.

**Suggested fix**: invalid-model day → set log_w to `-inf` before
normalization (or use strict valid mask both for forecast and posterior).
Apply consistently across K1257 + K1258 in single coordinated fix.

## MAJOR-2 — Unconverged fits accepted; results.json has NO convergence logs

Multiple fit functions store `res.success` as `converged` field (e.g.,
`fit_garch_n:249`, `fit_gjr_t:303`, `fit_a4f:388`) but **no downstream
exclusion**. `build_forecasts:489` only checks `state is not None`.

`k1258_results.json:1` has NO convergence count, NaN count, or dropped-
model-day count. Cannot verify from artifact whether MAJOR-1 actually
fired.

**Suggested fix**: treat `converged=False` as unavailable (skip in
forecast); log per-asset per-model convergence/invalid-day counts to
results.json. Without this, the run cannot be audited for MAJOR-1
contamination.

## MED-1 — H3 "optimal λ asset-specific" identified by ex-post argmin

`verdict_h3` at `:872` uses `min(lams, key=lambda k: lams[k]["qlike"])` —
ex-post OOS argmin, not CV / AIC / posterior criterion. H3 is descriptive
observation, not "selected via independent model selection procedure".

**Suggested fix**: refine H3 wording or add CV/AIC validation.

## MED-2 — "BMA family structurally insufficient" overstated

`README.md:112` claim is too strong. Evidence base is 3 assets × 5 fixed
λ × same base models × single OOS window. Accurate claim: "在本 K1257/K1258
設定下，forgetting factor 沒有帶來 Harvey-gated predictive gain" — cannot
extrapolate to whole BMA family.

**Suggested fix**: README + knowledge entry wording adjusted to in-scope
finding, not family-level structural claim.

## MINOR-1 — λ=1.0 reduce-to-K1257 not code-asserted

`README.md:108` claims byte-identical to K1257 when λ=1.0. No automated
smoke test / assert in code. Doesn't overturn results but lowers regression
protection.

**Suggested fix**: add `assert_array_equal` smoke test for λ=1.0 vs K1257.

---

## Direct answers to 9 review questions

- **Q1 K1257 inheritance**: REPLICATED (not fixed) at `:593-598`.
- **Q2 forgetting factor implementation**: correct order — decay `log_w`
  first, then add log-likelihood. λ grid {1.0, 0.99, 0.975, 0.95, 0.9}.
  `logsumexp` + `log_floor=-700` provides adequate numerical stability.
- **Q3 H1 FAIL**: computed correctly. `passing_cells=[]`. Max |t| only 2.659
  (GLD λ=0.975); 0050.TW best λ=0.9 only 1.59.
- **Q4 H2 PASS / "10-80x switching"**: derivable from results but metric
  is `weight_switch_freq` (descriptive ratio), not effective n_models.
  Verified: SPY 0.0108→0.1987 ~18.5x; GLD 0.0247→0.2405 ~9.7x; 0050.TW
  0.00263→0.2154 ~82x.
- **Q5 H3 PASS**: identified by ex-post OOS argmin QLIKE (MED-1).
- **Q6 λ=1.0 default / K1257 reduction**: numerically claimed in README,
  no code-level smoke test (MINOR-1).
- **Q7 NaN/Inf risk**: present, not loggable from artifact (MAJOR-2).
  Different from P5-ABM aggregation bug class but same "results file
  insufficient to prove clean run" issue.
- **Q8 verdict overstatement**: yes, "BMA family structurally insufficient"
  overreaches (MED-2).
- **Q9 results reveal actual failures**: NO — `results.json` lacks
  convergence/invalid-day counts.

---

## Knowledge entry retraction

Knowledge `727e23ee` confidence **0.88 → 0.70 RETRACTED 2026-04-29**:
- Primary conclusions (H1 FAIL, H2 switching restored, H3 asset-specific
  optimum, H4 λ=1.0 default) accepted **as descriptive findings**
- MAJOR-1 caveat: invalid-model posterior contamination risk (replicated
  from K1257); requires coordinated fix across K1257 + K1258
- MAJOR-2 caveat: convergence logging missing; cannot verify MAJOR-1 fired
- MED-2 caveat: "BMA family structurally insufficient" wording downgraded
  to in-scope finding
- All caveats baked into knowledge entry content

If MAJOR-1 + MAJOR-2 fixed (single coordinated K1257 + K1258 family fix
slot) + re-run produces near-identical numbers → confidence can rise to
0.85+.

---

## Cross-family pattern: E078 plan complete (5/5 fallback closures reviewed)

| K | Family | Subagent v1 | Codex v2 verdict |
|---|---|---|---|
| K1259 | meta-analysis | PASS-with-caveats | FAIL / 2 NEW MAJOR |
| K1261 | P5-ABM | CONDITIONAL PASS | FAIL / 3 NEW MAJOR |
| K1262 | P5-ABM | CONDITIONAL PASS | FAIL / 4 MAJOR |
| K1262b | P5-ABM | CONDITIONAL PASS | FAIL / 4 MAJOR + 1 MED |
| K1257 | BMA (first review) | (none) | CONDITIONAL PASS / 1 MAJOR |
| **K1258** | **BMA** | **PASS-with-caveats** | **CONDITIONAL PASS / 2 MAJOR + 2 MED** |

**5/5 = 100% subagent-fallback / main-thread-fallback closures had primary-
path Codex find unsignaled issues.**

**Severity bimodal by family**:
- P5-ABM family (K1261/K1262/K1262b): all FAIL with structural bugs
  (negative-baseline threshold + NaN/Inf aggregation + vt_* naming)
- BMA family (K1257/K1258): both CONDITIONAL PASS with shared narrower
  bug (invalid-model posterior contamination)
- Meta-analysis (K1259): FAIL with audit-method blind spot

**E078 prediction fully validated**: cross-model review (Anthropic claude-
sonnet vs OpenAI gpt-5.4) is NOT optional — it consistently catches
family-specific bugs that same-family LLM reviewers share blind spots on.
Hit rate uniform across 3 distinct code bases.
