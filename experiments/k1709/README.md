# K1709 — Spot BTC/ETH ETF net flow shocks and realized volatility

**Verdict: `INCONCLUSIVE_NO_EXACT_NULL_CLAIM`**

> INCONCLUSIVE. No primary cell clears the pre-specified Holm-adjusted UNCONDITIONAL detection gate, but only 5/10 primary cells can rule out the pre-specified 1% UNCONDITIONAL average relative QLIKE-loss gain, so the bounded null is NOT established. Failure to reject equal accuracy is not evidence of equality. The honest headline is: 'no robust incremental UNCONDITIONAL predictive evidence was found for spot BTC/ETH ETF flow over a HAR-RV baseline' -- a negative finding, not a proven zero. For the UNCONDITIONAL average-loss estimand, holding **simultaneously across all 10 cells** (Bonferroni), the relative QLIKE-loss gain from adding ETF flow is **≤ 4.2%**. Anything larger on that estimand is ruled out; anything smaller is not. Gains that vary by regime or state are outside this result.

**This is a revision.** The first version of this experiment was FAILed by an independent review on 2026-07-14 (`codex_review_20260714.md`), and the project's own mechanical gate (`scripts/tests/test_nested_dm_misuse_ratchet.py`) agreed. Two headline claims did not survive. What follows is the rebuilt study.

## What v1 claimed, and what was wrong with it

| v1 claim | Status |
|---|---|
| "NULL: ETF flow has no incremental predictive content" | **Overstated.** The nested comparison was adjudicated with a raw Diebold-Mariano statistic on expanding-window losses, plus a Clark-West helper that actually scored a *different loss* (variance-level MSPE, not QLIKE). Three estimands were fused into one gate. |
| "We can rule out an RV uplift of ≥ +16.2% per 1-sd flow shock" | **Withdrawn, not replaced.** That number came from reading a single-path power curve backwards. Power cannot bound an effect. |

### The six defects, and what replaced them

| # | Defect | Fix |
|---|---|---|
| C1 | Nested comparison inferred with raw Diebold-Mariano + a mislabelled Clark-West | Giacomini-White (2006) **Sec 3.4 unconditional special case** (h_t = 1, equals a HAC Diebold-Mariano) on Patton QLIKE from a **paired fixed rolling window**; raw DM and CW demoted to `feeds_gate=false` |
| C2 | "MDE" was one injection into one noise path — no repeated sampling, no false-positive check, non-monotone, and then read backwards as an exclusion | A repeated-sampling power simulation plus a pre-specified exclusion test and inverted confidence bound for the UNCONDITIONAL average QLIKE-loss estimand. Only the latter two can bound that estimand; none of them bounds conditional or regime-specific gains. |
| C3 | 16 BTC / 10 ETH US market holidays kept as genuine `Total=0.0` flow days, polluting the 20-day rolling scaler | NYSE session-calendar filter (`exchange_calendars` XNYS); holidays are MISSING, not zero |
| C4 | `pub_lag=2` robustness also lagged the HAR and return controls, handicapping its own baseline | `state_lag` and `flow_lag` are separate parameters with separately verified source dates |
| C5 | Statistic was called "HLN modified DM" but had no HLN correction; one-sided p used a normal CDF while the helper used Student-t | Renamed honestly to "HAC-DM + Harvey-Liu-Zhu |t|>3 heuristic"; one-sided p unified to the same Student-t |
| C6 | Holm ran on p-values already rounded to 4 dp; "EVERY DM test" hand-list missed 8 smearing tests | Holm on raw p; the family is derived from a single in-code test registry |
| C7 | README had a duplicated H3/H4 block with stale numbers | README is generated from the results JSON (`render_readme.py`) |

## How the claim is now established

- **Test**: TWO pre-specified objects, with OPPOSITE multiplicity treatments, and the verdict is a function of both. (1) DETECTION -- Giacomini-White (2006) Sec 3.4 UNCONDITIONAL special case (instrument h_t = 1, which coincides with a HAC Diebold-Mariano t; NOT the conditional GW test -- no instrument vector, no Wald statistic, no chi-square_q), one-sided and flow-favouring, HOLM-ADJUSTED across the 10-cell family (a union of alternatives: ten shots at finding an effect). (2) EXCLUSION -- the pre-specified one-sided material-gain test, run as an INTERSECTION-UNION test with each cell UNADJUSTED (Berger 1982): the bounded null may be asserted only if EVERY cell rejects its own exclusion null, which needs no correction. Holm-adjusted exclusion p-values are also reported as a conservative sensitivity, but they are NOT the test. The verdict is determined by those two objects. The verdict is INCONCLUSIVE because the detection family finds no Holm-adjusted evidence and the exclusion conjunction does not hold in every cell.
- **Loss**: Patton QLIKE on the variance level
- **Estimation scheme**: paired fixed rolling window of 250 flow days; both specs share the augmented complete-case mask, the training dates and the forward-label embargo (y_end_date < forecast origin). Every one of the 10 primary cells is therefore a BOUNDED-MEMORY forecasting method, which is the condition GW's limiting experiment needs. Every non-primary robustness row is `feeds_gate=false` and cannot broaden that claim. The two asset-specific `flow_transform/unexpected_z` rows are additionally `bounded_memory=false` because their regressor comes from an expanding-window AR(5); they are invalid-for-nested-inference diagnostics.
- **Gate**: `qlike_improve > 0 AND unconditional GW/DM z < -1.645 AND Holm p < 0.05`
- **Claim scope**: test = GW(2006) Sec 3.4 unconditional special case (= HAC DM) | loss = Patton QLIKE | scheme = paired fixed rolling window | claim = no robust evidence of UNCONDITIONAL incremental predictive ability, with any bound stated in QLIKE-loss space only. These four match by construction; v1's did not, and rev2's claim was broader than its test.

> ### What this study did NOT test
>
> The conditional GW test (h_t a non-trivial instrument, q x q moment covariance, Wald chi-square_q) is NOT run anywhere in this study. Every claim below is therefore UNCONDITIONAL: it is about the AVERAGE loss differential over the OOS sample. A flow effect that helps in one regime and hurts in another, netting to zero on average, would be invisible to this design and is NOT excluded by it.

**Why the word Giacomini-White appears when the statistic has HAC-DM form.** With h_t=1, GW (2006) Sec. 3.4 reduces to a mean loss differential over a Bartlett HAC standard error and targets only UNCONDITIONAL expected loss. This file builds no non-trivial instrument vector, q x q moment covariance, Wald statistic, or chi-square_q reference distribution, so it performs no conditional GW test and licenses no conditional or state-dependent claim.

Validity under nesting comes from the estimation scheme, not the DM-form arithmetic. GW compares forecasting methods with fitted-parameter noise included, and this limiting experiment requires bounded estimator memory. The paired fixed rolling window satisfies that condition; an expanding window does not and produces a degenerate nested null. Expanding-window values are retained only as diagnostic, feeds_gate=false records.

## Data

| | BTC | ETH |
|---|---|---|
| Flow days (NYSE sessions) | 626 | 494 |
| Sample | 2024-01-11 → 2026-07-13 | 2024-07-23 → 2026-07-13 |
| Net flow sd ($M) | 346.4 | 147.3 |
| Share of outflow days | 41.0% | 48.8% |
| **Market-holiday rows dropped (C3)** | **16** | **10** |
| …of which had a non-zero Total | 0 | 0 |
| RV calendar days | 1139 | 1139 |

Every dropped row had `Total = 0.0` with all fund columns dashed. That is the trap: `sum(skipna=True)` over an all-dash row returns `0.0`, so Farside's own Total matches the recomputed sum and the parser's cross-check cannot see the problem. These were US market holidays — days the ETFs *could not* trade — being fed to the model as genuine zero-flow days, and then into the 20-flow-day rolling standard deviation that scales every shock. Fake zeros shrink that scaler, which inflates every |z| that follows.

Data sources: Farside Investors (daily ETF creation/redemption flows, `https://farside.co.uk/bitcoin-etf-flow-all-data/`), Yahoo Finance (BTC-USD / ETH-USD OHLC + hourly bars). Realized variance is Garman-Klass on UTC calendar days; Parkinson, squared close-to-close return, and true 24-hour realized variance are carried as robustness proxies.

### Why this has to be an out-of-sample question

| | corr(flow, same-day return) | corr(\|flow\|, same-day log RV) |
|---|---|---|
| BTC | 0.389 | 0.088 |
| ETH | 0.219 | 0.064 |

Flow is contemporaneously correlated with the same day's return and volatility, so a contemporaneous regression of RV on flow is uninterpretable. Every inferential predictive claim below concerns the UNCONDITIONAL average loss differential of paired out-of-sample forecasting methods relative to a HAR-RV baseline; no conditional or state-dependent predictive-ability claim is made.

## Primary family — does flow improve UNCONDITIONAL average OOS QLIKE?

10 pre-specified cells. `H1` adds |z| (flow-shock magnitude); `H2` adds an extra loading on redemptions; `H4` asks whether BTC flow improves ETH's UNCONDITIONAL average out-of-sample QLIKE after controlling for ETH's own flow. None tests conditional or state-dependent predictive ability.

| Cell | n OOS | QLIKE Δ | uncond. GW/DM z | Holm p | Rules out ≥1% UNCONDITIONAL average QLIKE gain? |
|---|---|---|---|---|---|
| BTC h=1 H1_absflow | 355 | -0.561% | 1.30 | 1.000 | **yes** |
| BTC h=1 H2_asym | 355 | -0.948% | 0.62 | 1.000 | no |
| BTC h=5 H1_absflow | 351 | +0.404% | -0.50 | 1.000 | no |
| BTC h=5 H2_asym | 351 | -1.526% | 1.44 | 1.000 | **yes** |
| ETH h=1 H1_absflow | 223 | -0.554% | 0.67 | 1.000 | **yes** |
| ETH h=1 H2_asym | 223 | -0.172% | 0.19 | 1.000 | no |
| ETH h=5 H1_absflow | 218 | +0.297% | -0.33 | 1.000 | no |
| ETH h=5 H2_asym | 218 | -0.363% | 0.39 | 1.000 | no |
| ETH h=1 H4_plus_btc | 223 | +0.154% | -0.34 | 1.000 | **yes** |
| ETH h=5 H4_plus_btc | 218 | -0.389% | 0.66 | 1.000 | **yes** |

`QLIKE Δ` is the sample-average QLIKE-loss improvement of the flow method over the baseline; a negative value means worse average QLIKE. Negative unconditional GW/DM z favours flow. The gate requires `z < -1.645`, Holm `p < 0.05`, and positive QLIKE Δ.
For the UNCONDITIONAL average-loss primary family, **0 / 10** cells pass the pre-specified Holm-adjusted flow-detection gate.

### The UNCONDITIONAL average QLIKE-loss bound: what can be ruled out

Failing to reject equal UNCONDITIONAL expected loss is not evidence of equality. A bound on the average QLIKE-loss estimand requires reversing the burden of proof and testing the material-gain null directly; this does not bound conditional or regime-specific gains.

> **H₀**: the flow method's UNCONDITIONAL expected QLIKE loss is at least 1% lower than the baseline's. Rejecting H0 rules out a gain that large only for the UNCONDITIONAL average-loss estimand.

| Cell | exclusion z | p (unadjusted, IU) | excludes? | p (Holm, conservative) | 95% upper bound on the UNCONDITIONAL average QLIKE gain |
|---|---|---|---|---|---|
| BTC h=1 H1_absflow | 2.74 | 0.003 | **yes** | 0.031 | ≤ 0.19% |
| BTC h=1 H2_asym | 1.19 | 0.116 | no | 0.465 | ≤ 1.89% |
| BTC h=5 H1_absflow | 0.83 | 0.203 | no | 0.465 | ≤ 1.54% |
| BTC h=5 H2_asym | 2.22 | 0.013 | **yes** | 0.118 | ≤ 0.25% |
| ETH h=1 H1_absflow | 1.69 | 0.046 | **yes** | 0.274 | ≤ 0.95% |
| ETH h=1 H2_asym | 1.16 | 0.123 | no | 0.465 | ≤ 1.59% |
| ETH h=5 H1_absflow | 0.90 | 0.183 | no | 0.465 | ≤ 1.49% |
| ETH h=5 H2_asym | 1.64 | 0.050 | no | 0.274 | ≤ 1.00% |
| ETH h=1 H4_plus_btc | 1.97 | 0.024 | **yes** | 0.171 | ≤ 0.86% |
| ETH h=5 H4_plus_btc | 2.12 | 0.017 | **yes** | 0.136 | ≤ 0.64% |

**Why these p-values are unadjusted, while the detection ones above are Holm-corrected.** The two UNCONDITIONAL average-loss claims have opposite logical structure. *"Flow improves average loss somewhere"* is a **union** of alternatives — ten shots at finding an effect — so the family-wise error rate must be controlled. *"Flow improves average loss nowhere by ≥1%"* is an **intersection**: it may be asserted only if every cell rejects its own exclusion null. That intersection-union test holds at level alpha with each cell tested unadjusted (Berger 1982). Holm there would inflate type-II error and buy no type-I protection; its values are reported only as a conservative sensitivity. Neither claim addresses conditional or regime-specific gains.

**5 / 10** cells reject H0 at the pre-specified 1% UNCONDITIONAL average relative QLIKE-loss margin. That margin was carried from K1701 and fixed before these results. Because the intersection-union conjunction fails, **the bounded null is not established** and the verdict is `INCONCLUSIVE`, not `NULL`.

### What CAN be bounded: the UNCONDITIONAL average-loss confidence interval

The last column is the one-sided 95% **upper confidence bound** on the UNCONDITIONAL average relative QLIKE-loss gain, obtained by inverting the exclusion test. Gains larger than the bound on that estimand are excluded; gains smaller than it are not. Unlike a power curve, this is an inference about the average-loss estimand rather than a property of the design under an assumed truth. It says nothing about conditional or regime-specific gains.

For the UNCONDITIONAL average-loss estimand, holding **simultaneously across all 10 cells** (Bonferroni), the relative QLIKE-loss gain from adding ETF flow is **≤ 4.2%**. Anything larger on that estimand is ruled out; anything smaller is not. Gains that vary by regime or state are outside this result.

**Read the bound literally.** It lives in QLIKE-loss space and bounds only UNCONDITIONAL average forecast accuracy. It does not bound a conditional or regime-specific gain, an RV uplift per flow shock, or the true effect at exactly zero.

**Frozen-bound limitation.** The frozen UNCONDITIONAL average-loss QLIKE upper bounds were produced by a binary inversion that assumed the rejection set was an upper tail. The primary streams were later found mildly non-monotone; a dense independent audit found one crossing per stream, so the published crossings did not move, but the frozen JSON does not archive the loss paths needed to reproduce that audit. Future runs verify the full rejection topology before reporting a bound.

## Power — one h=1 cell, one injected alternative, nominal gate

1000 simulated OOS paths per point. The DGP is the fitted calendar-day HAR law of motion with block-bootstrapped innovations; real flow shocks and returns are retained, and the effect is injected into the law of motion so it propagates through HAR lags.

The beta grid is coarse, so 80%- and 90%-power crossings are intervals, not thresholds. No point estimate of a crossing is reported.

POWER IS NOT AN EXCLUSION. This says how often the gate fires against an effect of a given size; it does not bound the truth at the 80%-power point. The only upper bound this study defends is produced by the material-gain exclusion test, lives in QLIKE-loss space, and applies only to the UNCONDITIONAL average-loss estimand — not to conditional or regime-specific gains. The simulation is per-cell power at the nominal 5% gate, h=1, against one injected alternative. The actual verdict applies Holm across 10 cells, includes h=5, and includes alternatives not simulated here, so family-wise power is lower.

The beta=0 row is not textbook size. Under the fixed-window method-level null, an irrelevant extra regressor raises the augmented method's UNCONDITIONAL expected loss through estimation cost, so the one-sided flow-favouring gate is conservative. A rejection rate materially above 5% would be alarming; a lower rate does not establish conditional or state-dependent validity.

Per-beta rejection rates for the h=1, one-cell nominal gate:

| Assumed RV uplift per 1-sd shock | BTC one-cell power | ETH one-cell power |
|---|---|---|
| +0.0% | 0.00 | 0.02 |
| +5.1% | 0.01 | 0.02 |
| +10.5% | 0.04 | 0.07 |
| +16.2% | 0.09 | 0.13 |
| +22.1% | 0.19 | 0.22 |
| +35.0% | 0.42 | 0.30 |
| +56.8% | 0.71 | 0.57 |
| +82.2% | 0.91 | 0.72 |

**Power is not an exclusion.** This table says how often a one-cell gate fires against an assumed effect. It does not bound the true effect at the 80%-power point. The separate material-gain test bounds only the UNCONDITIONAL average relative QLIKE-loss gain; conditional or regime-specific gains are not bounded. The primary family also applies Holm across 10 cells, so family-wise power is lower than the table shows.

## Robustness

Every robustness row is registered with the primary family, but only pre-specified, bounded-memory primary rows can feed the claim gate. Non-primary rows remain diagnostic regardless of their p-values.

| Diagnostic family | Rows | Best flow-favouring UNCONDITIONAL z |
|---|---|---|
| RV proxy (Parkinson / r² / true hourly RV) | 6 | 0.37 |
| Conservative flow lag (flow usable only at end of t+1; state lag stays 1) | 4 | -0.31 |
| No lognormal smearing | 4 | -1.07 |
| Baseline's smearing forced onto both models | 4 | -0.50 |
| Flow transform: signed / squared / gross churn / AR(5)-unexpected | 8 | -0.62 |
| Shock threshold dummies (|z| ≥ 1.0 … 2.5) | 16 | -0.82 |
| Shorter ETH burn-in (200) | 2 | 0.03 |

Across all **10** gate-eligible tests of the UNCONDITIONAL average QLIKE-loss differential, **0** survive Holm in the flow-favouring direction. Another 152 registered tests are diagnostic-only and barred from every claim gate. This result does not address gains that vary by regime or state.

### 2 registered diagnostic rows fail the bounded-memory gate

GW's limiting experiment assumes the forecasting METHOD has bounded estimator memory. Every final regression here uses a fixed 250-day rolling window, but the condition is on the whole method. `flow_transform|BTC_h1|T_unexpected_z|rv_gk|fl1`, `flow_transform|ETH_h1|T_unexpected_z|rv_gk|fl1` build their regressors from an AR(5) refitted on an EXPANDING window of flow history. There is no lookahead, but those rows are not bounded-memory forecasting methods. It would therefore be false to call all 162 registered tests bounded-memory. The affected rows are diagnostic-only and cannot enter a verdict.

### Could smearing bias the UNCONDITIONAL average QLIKE comparison?

The augmented method has more parameters, which can lower its training residual variance and lognormal smearing multiplier. Because QLIKE is asymmetric, that channel could bias the UNCONDITIONAL average QLIKE comparison against flow. The residual variance is dof-corrected; two diagnostic panels also remove smearing or force the baseline multiplier onto both methods. Those non-gate diagnostics do not change the INCONCLUSIVE primary verdict, and they say nothing about conditional or regime-specific gains.

### H3 — Friday flow → weekend volatility (in-sample, descriptive)

Crypto trades through the weekend but the ETFs do not, so Friday flow is the last ETF-flow observation before a two-day gap. This in-sample descriptive coefficient asks where an association might be most visible; it does not test out-of-sample, conditional, or state-dependent predictive ability.

| | n Fridays | β(\|z\|) | HAC t | two-sided p |
|---|---|---|---|---|
| BTC | 121 | -0.0349 | -0.46 | 0.648 |
| ETH | 94 | 0.0426 | 0.43 | 0.667 |

In-sample only. The study's verdict concerns the UNCONDITIONAL average loss differential of paired out-of-sample forecasting methods, so this weekend coefficient is descriptive and enters no verdict. It does not test conditional or state-dependent predictive ability.

## What a second, independent re-review still found — and what changed

Six methodology/wording residuals found by an independent re-review of the frozen commit 34c291a4. NOT ONE OF THEM CHANGED AN ESTIMATE -- they are all about what a reader is entitled to conclude from the estimates, which is the failure mode that got v1 FAILed. Be precise about the one thing that did move between the two runs: it was the DATA, not the fixes. Yahoo back-filled a calendar day it had previously dropped (2026-07-12 -> 2026-07-13), which adds one out-of-sample observation to the h=5 cells and shifts their GW z in the third decimal. The h=1 statistics, the verdict, every gate count and the family-wide bound are bit-identical across the two runs.

| # | Residual | What changed |
|---|---|---|
| R1 | Power curve read as the study's power | The power curve is now explicitly scoped: single cell, h = 1, one injected alternative, nominal gate. It was being read as the study's power. See power_simulation.scope. |
| R2 | 80%/90%-power effect quoted as a point | The 80%/90%-power effect sizes are now BRACKETS only. The point fields (`rv_uplift_at_80pct_power_pct` and friends) are DELETED, not merely annotated -- a coarse grid cannot produce a point estimate, and leaving one in the JSON invites exactly the quotation it warns against. |
| R3 | β=0 row described as a size calibration | The beta = 0 row is a false-positive diagnostic, not a size calibration. The 'size-calibrated' wording is gone from the module docstring and the figure legend. |
| R4 | Fixed-window raw DM tagged "biased toward the smaller model" | The fixed-window raw Diebold-Mariano statistic was tagged 'biased toward the smaller model', which contradicts the very reason the scheme was changed. The role text is now scheme-specific: the expanding one is invalid, the fixed one is valid-but-not-the-gate. |
| R5 | `verdict_basis` named only the detection test | verdict_basis.test named only the Holm-adjusted detection family, although the verdict is co-determined by the unadjusted intersection-union exclusion test. Both are now named, with their opposite multiplicity treatments. |
| R6 | Two robustness rows are not bounded-memory methods | Two asset-specific `flow_transform/unexpected_z` rows use an expanding-window AR(5) to build their regressor, so their forecasting methods are not bounded-memory. They remain visible but are flagged `bounded_memory=false`, `feeds_gate=false` and diagnostic-only before their p-values are read. |

## Reproducing

```bash
uv run python experiments/k1709/k1709.py --relabel  # frozen-safe wording only
uv run python experiments/k1709/k1709.py --render-frozen-figures
uv run python experiments/k1709/render_readme.py    # JSON-only README render
uv run --extra dev python -m pytest experiments/k1709/test_k1709.py -q
uv run --extra dev python -m pytest scripts/tests/test_nested_dm_misuse_ratchet.py -q
```

Seed `1709` throughout (OLS is deterministic; the block bootstrap and the power simulation are seeded explicitly). The results JSON is written atomically: temp file → parse → `os.replace`.

**Point-in-time limitation.** Neither the Farside flow response nor the Yahoo price response was archived point-in-time. The source URLs and sample endpoint identify what was queried, but cannot reconstruct the exact vendor bytes. Any live rerun may therefore change any statistic, gate count, bound or verdict; only --relabel and JSON-only rendering preserve this frozen numerical artefact.

The committed result endpoint is **2026-07-13** (last fully closed UTC day in that run). This records the sample endpoint, not the unarchived vendor response bytes. Running `k1709.py` without a frozen-only flag is a new live-data estimate, not a reproduction of this artefact.

| File | What it is |
|---|---|
| `k1709.py` | The experiment |
| `k1709_results.json` | Every number in this README |
| `test_k1709.py` | Regression gates |
| `render_readme.py` | Generates this file from the results JSON |
| `codex_review_20260714.md` | The independent review that FAILed v1 |
| `fig1_flow_vs_rv.png` | Flow vs realized volatility |
| `fig2_event_window.png` | Frozen descriptive event plot; see label limitation below |
| `fig3_oos_qlike.png` | OOS QLIKE + unconditional GW/DM z, primary cells |
| `fig4_threshold_sensitivity.png` | Unconditional GW/DM z by shock threshold |
| `fig5_simulated_power.png` | Simulated power (replaces v1's "MDE" curve) |

**Figure 2 limitation.** The frozen fig2 is descriptive and has a one-day label shift: its x=0 is the first RV target day after the lagged flow observation, so the actual flow day is x=-1. It feeds no estimate, test or verdict. Future renders centre x=0 on the recorded flow source date explicitly.

## What this study does and does not say

**Does say:**

- **No robust incremental UNCONDITIONAL predictive evidence was found** for spot BTC/ETH ETF net flow over a HAR-RV baseline. Not one of the 10 primary cells clears the pre-specified Holm-adjusted detection gate; the point estimates mostly run the wrong way.
- For the UNCONDITIONAL average-loss estimand, gains larger than **4.2%** in relative QLIKE are excluded simultaneously across all 10 cells.
- For the UNCONDITIONAL average-loss estimand, only 5/10 cells can rule out the pre-specified 1% gain, so this is a **negative finding, not a proven zero**. Calling it a null result would overstate the evidence.
- The flow-transform, RV-proxy, smearing, publication-lag and threshold panels are reported as diagnostics only; none broadens the 10-cell primary UNCONDITIONAL average-loss claim.

**Does not say:**

- That the true effect is exactly zero. No test here establishes that.
- That an RV uplift of any particular size is excluded. The only reported bound is on the UNCONDITIONAL average relative QLIKE-loss gain.
- That flow lacks conditional or state-dependent predictive ability. The conditional GW test is not run; regime-specific effects that help in one state and hurt in another, netting to zero on average, are invisible to this design and are NOT excluded.
- Anything about the level effect of ETF-ization on crypto volatility. The treatment here is flow, not the trading clock or session structure.

