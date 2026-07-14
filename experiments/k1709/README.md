# K1709 — Spot BTC/ETH ETF net flow shocks and realized volatility

**Verdict: `INCONCLUSIVE_NO_EXACT_NULL_CLAIM`**

> INCONCLUSIVE. No cell shows incremental predictive content, but only 5/10 primary cells can rule out the pre-specified 1% QLIKE gain, so the bounded null is NOT established. Failure to reject equal accuracy is not evidence of equality. The honest headline is: 'no robust incremental predictive evidence was found for spot BTC/ETH ETF flow over a HAR-RV baseline' -- a negative finding, not a proven zero. The inverted one-sided 95% upper confidence bound on the relative QLIKE gain is 4.2% simultaneously across all 10 cells (Bonferroni): gains LARGER than that are excluded by the data; anything smaller is not.

**This is a revision.** The first version of this experiment was FAILed by an independent review on 2026-07-14 (`codex_review_20260714.md`), and the project's own mechanical gate (`scripts/tests/test_nested_dm_misuse_ratchet.py`) agreed. Two headline claims did not survive. What follows is the rebuilt study.

## What v1 claimed, and what was wrong with it

| v1 claim | Status |
|---|---|
| "NULL: ETF flow has no incremental predictive content" | **Overstated.** The nested comparison was adjudicated with a raw Diebold-Mariano statistic on expanding-window losses, plus a Clark-West helper that actually scored a *different loss* (variance-level MSPE, not QLIKE). Three estimands were fused into one gate. |
| "We can rule out an RV uplift of ≥ +16.2% per 1-sd flow shock" | **Withdrawn, not replaced.** That number came from reading a single-path power curve backwards. Power cannot bound an effect. |

### The six defects, and what replaced them

| # | Defect | Fix |
|---|---|---|
| C1 | Nested comparison inferred with raw Diebold-Mariano + a mislabelled Clark-West | Giacomini-White (2006) on Patton QLIKE from a **paired fixed rolling window**; raw DM and CW demoted to `feeds_gate=false` |
| C2 | "MDE" was one injection into one noise path — no repeated sampling, no false-positive check, non-monotone, and then read backwards as an exclusion | A real power simulation (1000 simulated OOS paths per point) **plus** a pre-specified material-gain exclusion test and an inverted confidence bound — the only objects that can legitimately bound an effect |
| C3 | 16 BTC / 10 ETH US market holidays kept as genuine `Total=0.0` flow days, polluting the 20-day rolling scaler | NYSE session-calendar filter (`exchange_calendars` XNYS); holidays are MISSING, not zero |
| C4 | `pub_lag=2` robustness also lagged the HAR and return controls, handicapping its own baseline | `state_lag` and `flow_lag` are separate parameters with separately verified source dates |
| C5 | Statistic was called "HLN modified DM" but had no HLN correction; one-sided p used a normal CDF while the helper used Student-t | Renamed honestly to "HAC-DM + Harvey-Liu-Zhu |t|>3 heuristic"; one-sided p unified to the same Student-t |
| C6 | Holm ran on p-values already rounded to 4 dp; "EVERY DM test" hand-list missed 8 smearing tests | Holm on raw p; the family is derived from a single in-code test registry |
| C7 | README had a duplicated H3/H4 block with stale numbers | README is generated from the results JSON (`render_readme.py`) |

## How the claim is now established

- **Test**: Giacomini-White (2006) equal unconditional predictive ability (one-sided, flow-favouring), Holm-adjusted across the primary family
- **Loss**: Patton QLIKE on the variance level
- **Estimation scheme**: paired fixed rolling window of 250 flow days; both specs share the augmented complete-case mask, the training dates and the forward-label embargo (y_end_date < forecast origin)
- **Gate**: `qlike_improve > 0 AND GW z < -1.645 AND Holm p < 0.05`
- **Claim scope**: bounded in QLIKE-loss space only. test = Giacomini-White | loss = Patton QLIKE | scheme = paired fixed rolling window | claim = bounded in QLIKE-loss space only. These four match by construction; v1's did not.

**Why Giacomini-White, and why this is not just Diebold-Mariano renamed.** The arithmetic really is nearly the same — a mean loss difference over a Bartlett HAC standard error — and on the same loss stream the two statistics agree to about three decimal places (they differ only in a small-sample HAC scaling: GW divides each lag covariance by *n*, the canonical DM helper by *n − lag*). The results file reports both, side by side, rather than hiding the coincidence.

What makes the test legal under nesting is therefore **not the formula** but the *estimation scheme*. Giacomini and White compare forecasting **methods**, with fitted-parameter noise treated as part of the object being compared rather than a nuisance to be purged — and that limiting experiment requires the estimator to have **bounded memory**, i.e. a fixed-length rolling window. Feed the same formula expanding-window forecasts, as v1 did, and the nested null is degenerate: the statistic is biased toward the smaller model and no reference distribution rescues it. Every cell therefore also reports the expanding-window value under `expanding_window_diagnostic_v1_design`, so the effect of the scheme change is auditable rather than asserted.

## Data

| | BTC | ETH |
|---|---|---|
| Flow days (NYSE sessions) | 626 | 494 |
| Sample | 2024-01-11 → 2026-07-13 | 2024-07-23 → 2026-07-13 |
| Net flow sd ($M) | 346.4 | 147.3 |
| Share of outflow days | 41.0% | 48.8% |
| **Market-holiday rows dropped (C3)** | **16** | **10** |
| …of which had a non-zero Total | 0 | 0 |
| RV calendar days | 1138 | 1138 |

Every dropped row had `Total = 0.0` with all fund columns dashed. That is the trap: `sum(skipna=True)` over an all-dash row returns `0.0`, so Farside's own Total matches the recomputed sum and the parser's cross-check cannot see the problem. These were US market holidays — days the ETFs *could not* trade — being fed to the model as genuine zero-flow days, and then into the 20-flow-day rolling standard deviation that scales every shock. Fake zeros shrink that scaler, which inflates every |z| that follows.

Data sources: Farside Investors (daily ETF creation/redemption flows, `https://farside.co.uk/bitcoin-etf-flow-all-data/`), Yahoo Finance (BTC-USD / ETH-USD OHLC + hourly bars). Realized variance is Garman-Klass on UTC calendar days; Parkinson, squared close-to-close return, and true 24-hour realized variance are carried as robustness proxies.

### Why this has to be an out-of-sample question

| | corr(flow, same-day return) | corr(\|flow\|, same-day log RV) |
|---|---|---|
| BTC | 0.388 | 0.088 |
| ETH | 0.218 | 0.064 |

Flow is contemporaneously correlated with the same day's return and volatility, so a contemporaneous regression of RV on flow is uninterpretable — it cannot tell "flow moves volatility" from "volatility attracts flow". Everything below is strictly out-of-sample and conditional on a HAR-RV baseline.

## Primary family — does ETF flow beat HAR out-of-sample?

10 pre-specified cells. `H1` adds |z| (flow shock magnitude); `H2` adds an extra loading on redemptions; `H4` tests whether BTC's flow shock predicts **ETH** volatility once ETH's own flow is controlled for.

| Cell | n OOS | QLIKE Δ | GW z | Holm p | Rules out ≥1% gain? |
|---|---|---|---|---|---|
| BTC h=1 H1_absflow | 355 | -0.561% | 1.30 | 1.000 | **yes** |
| BTC h=1 H2_asym | 355 | -0.948% | 0.62 | 1.000 | no |
| BTC h=5 H1_absflow | 350 | +0.407% | -0.50 | 1.000 | no |
| BTC h=5 H2_asym | 350 | -1.527% | 1.43 | 1.000 | **yes** |
| ETH h=1 H1_absflow | 223 | -0.554% | 0.67 | 1.000 | **yes** |
| ETH h=1 H2_asym | 223 | -0.172% | 0.19 | 1.000 | no |
| ETH h=5 H1_absflow | 217 | +0.287% | -0.32 | 1.000 | no |
| ETH h=5 H2_asym | 217 | -0.370% | 0.40 | 1.000 | no |
| ETH h=1 H4_plus_btc | 223 | +0.154% | -0.34 | 1.000 | **yes** |
| ETH h=5 H4_plus_btc | 217 | -0.362% | 0.61 | 1.000 | **yes** |

`QLIKE Δ` is the flow model's improvement over the baseline — **negative means the flow model is worse**. `GW z < 0` would favour flow; the gate needs `z < -1.645` *and* Holm `p < 0.05` *and* a positive QLIKE Δ. Cells passing: **0 / 10**.

### The bound: what can actually be ruled out

Failing to reject equal accuracy is **not** evidence of equality — that is the trap v1 fell into. To claim a bound you have to reverse the burden of proof and test it directly:

> **H₀**: adding ETF flow improves expected QLIKE by at least 1% (relative). Rejecting H₀ means a gain that large is not there.

| Cell | exclusion z | p (unadjusted, IU) | excludes? | p (Holm, conservative) | 95% upper bound on the gain |
|---|---|---|---|---|---|
| BTC h=1 H1_absflow | 2.74 | 0.003 | **yes** | 0.031 | ≤ 0.19% |
| BTC h=1 H2_asym | 1.19 | 0.116 | no | 0.465 | ≤ 1.89% |
| BTC h=5 H1_absflow | 0.82 | 0.205 | no | 0.465 | ≤ 1.54% |
| BTC h=5 H2_asym | 2.22 | 0.013 | **yes** | 0.119 | ≤ 0.25% |
| ETH h=1 H1_absflow | 1.69 | 0.046 | **yes** | 0.274 | ≤ 0.95% |
| ETH h=1 H2_asym | 1.16 | 0.123 | no | 0.465 | ≤ 1.59% |
| ETH h=5 H1_absflow | 0.91 | 0.180 | no | 0.465 | ≤ 1.48% |
| ETH h=5 H2_asym | 1.64 | 0.050 | no | 0.274 | ≤ 1.00% |
| ETH h=1 H4_plus_btc | 1.97 | 0.024 | **yes** | 0.171 | ≤ 0.86% |
| ETH h=5 H4_plus_btc | 2.06 | 0.019 | **yes** | 0.156 | ≤ 0.68% |

**Why these p-values are unadjusted, while the Giacomini-White ones above are Holm-corrected.** The two claims have opposite logical structure, and the correction has to follow the claim, not the habit. *"Flow helps somewhere"* is a **union** of alternatives — ten shots at finding an effect — so the family-wise error rate must be controlled. *"Flow helps nowhere by ≥1%"* is an **intersection**: it may be asserted only if *every* cell rejects its own exclusion null, which is an intersection-union test (Berger 1982) and holds at level α with each cell tested unadjusted. Holm there would inflate type-II error and buy no type-I protection. The Holm column is reported anyway so the choice is auditable — and note it does not change the verdict either way.

**5 / 10** cells reject H₀ at the pre-specified 1% margin. That margin is the project standard carried over from K1701 — it was fixed before the results were seen, not tuned until the null looked good. Because most cells cannot reject it, **the bounded null is not established** and the verdict is `INCONCLUSIVE`, not `NULL`.

### What CAN be bounded: the inverted confidence interval

The last column above is the honest quantitative answer. It is the one-sided 95% **upper confidence bound** on the relative QLIKE gain, obtained by inverting the exclusion test: gains *larger* than the bound are excluded by the data; gains *smaller* than it are not. Unlike a power curve, this is an inference about the effect rather than a property of the design under an assumed truth — which is exactly the distinction v1 collapsed.

Holding **simultaneously across all 10 cells** (Bonferroni): the relative QLIKE gain from adding ETF flow is **≤ 4.2%**. Anything larger is ruled out; anything smaller is not.

**Read the bound literally.** It lives in QLIKE-loss space: it is about *forecast accuracy*. It is **not** a statement that the RV uplift per flow shock is smaller than any particular percentage, and it is **not** a proof of exact zero.

## Power — what this design could have seen

1000 simulated OOS paths per point. The DGP is the fitted calendar-day HAR law of motion with block-bootstrapped innovations, the real flow shocks and the real returns retained, and the effect injected **into the law of motion** so it propagates through the HAR lags — exactly as a genuine effect would, and exactly as the baseline would partially absorb it.

| | BTC | ETH |
|---|---|---|
| Rejection rate when the true effect is 0 | 0.007 | 0.019 |
| 80% power first reached at | +82.21% RV uplift (power 0.91; previous grid point 0.73) | never — not even at +82.21% RV uplift |
| 90% power first reached at | +82.21% RV uplift (power 0.91; previous grid point 0.73) | never — not even at +82.21% RV uplift |

These are the first points on a **coarse grid** at which power is met, not solved thresholds — the true crossing sits somewhere between the previous grid point and this one. Reporting them as exact would be a small cousin of the error that got v1 failed.

The β=0 row is **not** "size" in the textbook sense, and it should sit *below* 5% rather than at it. Under Giacomini-White's method-level null with a fixed window, an irrelevant extra regressor makes the augmented method genuinely worse — it pays an estimation cost and buys nothing — so E[L_flow − L_base] > 0 strictly. A one-sided flow-favouring gate is therefore conservative at β=0 by construction. What the row establishes is the thing that matters: **this gate does not manufacture flow signals out of noise**. A rate materially *above* 5% would have been the alarm.

Per-β detail (BTC / ETH rejection rate at the 5% gate):

| True RV uplift per 1-sd shock | BTC power | ETH power |
|---|---|---|
| +0.0% | 0.01 | 0.02 |
| +5.1% | 0.01 | 0.03 |
| +10.5% | 0.03 | 0.07 |
| +16.2% | 0.10 | 0.11 |
| +22.1% | 0.19 | 0.18 |
| +35.0% | 0.40 | 0.32 |
| +56.8% | 0.73 | 0.57 |
| +82.2% | 0.91 | 0.70 |

**Power is not an exclusion.** This table says how often the gate fires against an effect of a given size. It does *not* say the true effect is smaller than the 80%-power point — that inversion is precisely the error v1 made. It is also per-cell power at the nominal gate; the primary family additionally applies a Holm correction, so the family-wise design has *less* power than the table shows.

Note how much blunter this honest reading is than v1's. v1 advertised a minimum detectable effect of +16.2% and then used it as an exclusion. In reality the design needs an uplift of about +82.21% (BTC) before it reaches 80% power, and for ETH 80% power is never reached across the whole grid. The instrument is far cruder than v1 claimed — which is one more reason the RV-space "exclusion" had to go, and why the verdict is INCONCLUSIVE rather than a bounded NULL.

## Robustness

Every run below is registered in the same in-code test registry as the primary family, so the full-family Holm correction sees all of them. v1's hand-written "EVERY DM test" list silently omitted 8.

| Family | Cells | Best (most flow-favouring) GW z | Any cell passing the gate? |
|---|---|---|---|
| RV proxy (Parkinson / r² / true hourly RV) | 6 | 0.55 | no |
| Conservative flow lag (flow usable only at end of t+1; state lag stays 1) | 4 | -0.28 | no |
| No lognormal smearing | 4 | -1.07 | no |
| Baseline's smearing forced onto both models | 4 | -0.51 | no |
| Flow transform: signed / squared / gross churn / AR(5)-unexpected | 8 | -0.62 | no |
| Shock threshold dummies (|z| ≥ 1.0 … 2.5) | 16 | -0.82 | no |
| Shorter ETH burn-in (200) | 2 | 0.07 | no |

Across **all 54** gate-eligible Giacomini-White tests in the study, **0** survive the full-family Holm correction in the flow-favouring direction. (108 further tests are registered as diagnostic-only and are barred from any gate by construction.)

### Is the null an artifact of the log → variance mapping?

A live threat, and worth spelling out. The flow model has more parameters → a lower training residual variance → a smaller `exp(s²/2)` smearing multiplier → systematically lower variance forecasts. QLIKE is asymmetric, so in principle this channel could *manufacture* the null we are reporting. Three defences: the residual variance is dof-corrected (`N − k`), which makes its expectation spec-invariant under the null; the study re-scores with no smearing at all; and it re-scores again with the *baseline's* multiplier forced onto both models. The verdict does not move.

### H3 — Friday flow → weekend volatility (in-sample, descriptive)

Crypto trades through the weekend but the ETFs do not, so a Friday flow shock is the last piece of ETF information before a two-day gap. If flow carried volatility news anywhere, this is where it should be loudest.

| | n Fridays | β(\|z\|) | HAC t | two-sided p |
|---|---|---|---|---|
| BTC | 121 | -0.0349 | -0.46 | 0.648 |
| ETH | 94 | 0.0426 | 0.43 | 0.667 |

**In-sample only**, and it does not feed any verdict — the study's claim is about out-of-sample predictive content.

## Reproducing

```bash
uv run python experiments/k1709/k1709.py            # rebuilds the results JSON
uv run python experiments/k1709/render_readme.py    # rebuilds this README
uv run --extra dev python -m pytest experiments/k1709/test_k1709.py -q
uv run --extra dev python -m pytest scripts/tests/test_nested_dm_misuse_ratchet.py -q
```

Seed `1709` throughout (OLS is deterministic; the block bootstrap and the power simulation are seeded explicitly). The results JSON is written atomically: temp file → parse → `os.replace`.

| File | What it is |
|---|---|
| `k1709.py` | The experiment |
| `k1709_results.json` | Every number in this README |
| `test_k1709.py` | Regression gates |
| `render_readme.py` | Generates this file from the results JSON |
| `codex_review_20260714.md` | The independent review that FAILed v1 |
| `fig1_flow_vs_rv.png` | Flow vs realized volatility |
| `fig2_event_window.png` | log-RV path around large flow shocks |
| `fig3_oos_qlike.png` | OOS QLIKE + Giacomini-White z, primary cells |
| `fig4_threshold_sensitivity.png` | GW z by shock threshold |
| `fig5_simulated_power.png` | Simulated power (replaces v1's "MDE" curve) |

## What this study does and does not say

**Does say:**

- **No robust incremental predictive evidence was found** for spot BTC/ETH ETF net flow over a HAR-RV baseline. Not one of the 10 primary cells clears the gate, and the point estimates mostly run the *wrong* way (the flow model is slightly worse).
- Gains larger than **4.2%** in relative QLIKE are excluded, simultaneously across all 10 cells.
- But only 5/10 cells can rule out the pre-specified 1% gain, so this is a **negative finding, not a proven zero**. Calling it "NULL" would be the same overreach v1 was FAILed for.
- The result survives four flow transforms, four RV proxies, three smearing conventions, a conservative publication lag, and four shock thresholds.

**Does not say:**

- That the true effect is exactly zero. No test here can establish that.
- That an RV uplift of any particular size is excluded. v1 claimed it could 'rule out an RV uplift of >= +16.2% per 1-sd flow shock'. That number came from reading a single-path power curve backwards. Power is not an exclusion. The claim is WITHDRAWN and is not replaced by an RV-space bound of any size.
- Anything about the *level* effect of ETF-ization on crypto volatility. The treatment here is the flow, not the trading clock or the session structure.

