# K1257 Codex Code Review — Primary-Path First-Time Gate (CONDITIONAL PASS)

**Review date**: 2026-04-29 (CST), task `task-moje58sy-9qtdx6`, 2m 37s
**Reviewer**: Codex CLI 0.121.0 (gpt-5.4 default), session `019dd6e7-cb2f-7671-a7d8-82ba989f54bd`
**Trigger**: K1257 closure had been pending Codex review since 2026-04-20
because the 4-day Codex CLI blocker started 2026-04-26. README explicitly
said "等候 Codex 04-24 wake 執行". This is **first-time gate-closing review**
(not re-verification). Codex CLI restored 2026-04-28T21:58.

**Scope**: K1257 Bayesian Model Averaging (BMA) volatility forecast, 6
models × 3 assets (SPY/GLD/0050.TW) × OOS 2020-2026.

**Findings**: 0 CRITICAL / 0 SEVERE / 1 MAJOR / 2 MED / 2 MINOR

---

## Verdict: **CONDITIONAL PASS**

Primary conclusion (H1 PARTIAL / H2 FAIL / H3 FAIL) accepted; lookahead /
likelihood normalization / Harvey methodology all PASS. But knowledge entry
should include caveats listed below.

## MAJOR — Invalid-model posterior contamination

`k1257_bma_volatility.py:551`: when a model's `h_pred` is invalid on day t,
the code skips that model's likelihood update but **preserves its prior
`log_weight` and re-normalizes alongside other models**. Forecast at `:542-548`
re-weights only valid models. Pre-update support and post-normalize support
are inconsistent → models that failed to produce a forecast can still
retain posterior mass.

Impact: if any candidate model has convergence failure or NaN forecast on
some days, BMA weights are silently contaminated. K1258 inherits the same
structure at `k1258_forgetting_factor_bma.py:593-598`.

**Suggested fix**: invalid-model day → set log_weight to `-inf` or very
low value before normalization, OR strictly use same valid mask for both
forecast and posterior. Apply consistently across K1257 + K1258.

## MED-1 — Refit non-convergence handling

`k1257_bma_volatility.py:425-480`: only catches Exception. If
`scipy.optimize.minimize` returns `res.success=False`, model still enters
forecast + posterior with potentially-bad parameters. `results.json` doesn't
record convergence counts.

**Suggested fix**: treat `converged=False` as unavailable; log per-model
per-asset failure counts to results.json.

## MED-2 — README ↔ implementation drift

`README.md:27-34`, `:49-50`, `:131-132` describe 7 models incl. HAR-RV,
A4f-VIX², Realized GARCH. Implementation + results actually use 6 models
incl. `HAR_ABS`, `A4f_IV2`, and GLD uses `^GVZ` not VIX. Numbers stand
but knowledge entry would mis-describe methodology.

**Suggested fix**: align README with actual implementation before knowledge
entry.

## MINOR-1 — README time-index ambiguity

`README.md:38-45` formula `w_{i,t+1}` matched with `\hat σ²_{t+1}` looks
like lookahead. Implementation is correct (pre-update posterior for day t
forecast at `:538-568`, then update with y_t), but README is confusing.

**Suggested fix**: clearer time-index notation.

## MINOR-2 — H3 "~500 days" not a computed metric

`README.md:115` claims posterior concentration "within ~500 days" — this
is from visual inspection of plots, not a computed concentration-hitting-time
metric. Empirically supported by figure but not byte-traceable.

**Suggested fix**: compute explicit concentration metric (e.g. effective
n_models drops below 1.5) before knowledge entry.

---

## Direct answers to 9 review questions

- **Lookahead audit**: PASS. `returns[s:t]` uses only data through t-1.
- **Likelihood normalization**: `logsumexp` used correctly, no overflow.
- **Posterior dynamics / H3**: figures + results.json support degeneracy
  empirically — not a normalization artifact.
- **Harvey-adjusted DM**: implementation direction correct; H1 PARTIAL /
  H2 FAIL match results.json.
- **Refit cadence fairness**: 6 models all 63-day refit; symmetric.
- **Seed handling**: `np.random.seed(42)` set; primary risk is non-
  convergence handling (MED-1), not seed.
- **NaN/Inf risk**: structural risk per MAJOR finding.
- **K1258 inheritance**: confirmed — same `invalid-model stale posterior`
  + `non-converged fit accepted` issues propagate.
- **Verdict overstatement**: H1 PARTIAL / H2 FAIL / H3 FAIL not over-
  claimed; only "~500 days" needs hardening.

---

## Cross-family pattern check (vs K1259/K1261/K1262/K1262b)

K1257 is BMA family, NOT P5-ABM family. Different code base, different
bug class:

| K family | Codex v2 verdict | Bug type |
|---|---|---|
| K1259 (meta-analysis) | FAIL | Audit subset blind spots, t_stat priority |
| K1261/K1262/K1262b (P5-ABM) | FAIL | Negative-baseline threshold + NaN/Inf agg + vt_* naming |
| **K1257/K1258 (BMA)** | **CONDITIONAL PASS** | **Stale-posterior on invalid model day** |

Pattern observation: subagent fallback consistently misses family-specific
bugs, but bug severity varies by family. K1257's MAJOR is real but
narrower in impact (only fires on convergence failure days; if results.json
has 0 such days the bug never triggered).

E078 prediction confirmed but with nuance: cross-model review IS necessary
(subagent missed this MAJOR too, since K1257 had no subagent review either —
this IS the first review and Codex caught it on first pass).

---

## Knowledge entry recommendation

Write K1257 entry with confidence **0.75** (not 0.85) reflecting:
- Primary conclusions (H1 PARTIAL / H2 FAIL / H3 FAIL) accepted
- MAJOR caveat: posterior contamination risk on invalid-model days;
  results may be biased if convergence failures occurred (currently
  unknown — convergence counts not logged)
- MED-1 unaddressed: non-converged fits silently accepted
- MED-2 README drift: methodology description in README inaccurate
- K1258 inheritance flagged for follow-up

If MAJOR + MED-1 fixed in subsequent slot + re-run produces
identical numbers → confidence can rise to 0.85+.
