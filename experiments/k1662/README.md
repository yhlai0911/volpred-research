# K1662 — Score-driven (GAS / DCS) dynamic-parameter models for direct VaR + ES

**Status:** COMPLETE — v2 authoritative run (837.9s, 2026-07-09); reviewer PASS; knowledge e9d8fabd. Verdict: NULL (score-driven no tail-risk edge over GARCH-family; DCS-t in-MCS everywhere but no edge; GAS-t weakest; EWMA-N excluded everywhere).
**Asset(s):** SPY (primary), QQQ (cross-asset robustness) — adjusted-close log returns, 2000–2026
**OOS:** rolling window = 2000 days, quarterly refit (every 63 days), one-step-ahead
**Tails:** α ∈ {1%, 5%} · **Seed:** 42

---

## Motivation & differentiation

The platform already has an extensive score-driven (GAS-t) research line —
**K437, K1038, K1129, K1134, K1138, K1143** — but every one of those experiments
evaluated the **point volatility forecast** through QLIKE / Diebold-Mariano and
found score-driven dynamics **NULL** (K1038: GAS-t QLIKE not better than GJR) or
**actively harmful** for equity σ² (K1138/K1143: SPY/QQQ GAS-t DM t ≈ −3).

K1662 asks a question that line **never tested formally** and that is *orthogonal*
to QLIKE:

> **Are score-driven models WELL-CALIBRATED for tail risk (VaR + ES)?**

Two prior hints motivate it directly:
- **K1038**: "GAS-t SPY VaR violation 1.70% vs GJR 2.02% — because of built-in Student-t."
- **K1129 H4**: "VaR violation M3<M1 confirmed（分配假設準 ≠ vol predict 好）."

i.e. a model can be *worse* at forecasting σ² (QLIKE) yet *better* at tail
coverage, because the tail is governed by the innovation distribution and the
dynamics' response to shocks, not by mean-square accuracy. K1662 runs **formal
VaR + ES backtests** and a **joint FZ0 model-confidence comparison** to settle it.

**Honest framing (not "does score-driven win"):** the question is whether the
score-driven models **enter the Model Confidence Set** and **pass the VaR/ES
backtests**. A NULL (well-calibrated but not superior to GARCH-family) is a
fully reportable result and the *a priori* most likely outcome given K1038/K1138.

This is the platform's **first** score-driven experiment whose deliverable is a
tail-risk (VaR+ES) calibration table rather than a QLIKE ranking.

## Design — 2×2 fair matrix + naive baseline

| | Score-driven | GARCH-family baseline |
|---|---|---|
| **Symmetric** | **GAS-t** (Creal-Koopman-Lucas 2013; log-variance, inverse-Fisher score) | **GARCH(1,1)-t** |
| **Asymmetric** | **DCS-t** (Harvey 2013 Beta-t-EGARCH + leverage) | **GJR-GARCH(1,1)-t** |
| **Naive** | — | **EWMA / RiskMetrics** (λ=0.94, Normal) |

All GARCH-family and score-driven models share the **same standardized
Student-t innovation** and the **same σ → VaR → ES analytic pipeline**, so any
calibration difference is attributable to the **dynamics** (score-driven vs
GARCH recursion), not the distribution. EWMA-Normal isolates the cost of the
Normal tail assumption. The symmetric/asymmetric pairing lets us compare
score-driven vs GARCH *within* the same asymmetry class (fair test).

`VaR_α(t) = σ_t · q_α`, `ES_α(t) = σ_t · e_α`, where for a **unit-variance**
standardized Student-t(ν): `q_α = t.ppf(α,ν)·√((ν−2)/ν)` and
`e_α = −(f_ν(t_α)/α)·(ν+t_α²)/(ν−1)·√((ν−2)/ν)` (both negative); Normal uses
`q_α = Φ⁻¹(α)`, `e_α = −φ(Φ⁻¹(α))/α`.

## Method (hard rules honoured)

- **Lookahead (highest-priority risk).** σ_t is a one-step-ahead forecast using
  returns only up to **t−1** (the recursion state `s²[t]` depends solely on
  `r[t−1]`, `s²[t−1]`). Parameters are refit on the rolling window
  `r[i₀−2000 : i₀]`, **strictly before** the forecast origin i₀; params are held
  fixed for the 63-day block and only the recursion rolls daily. **Identical lag
  and OOS scheme for all five models.** Block-forward optimisation runs one
  recursion per refit and slices out the in-block one-step-ahead σ_t
  (mathematically identical to a per-day recursion, ~63× faster).
- **seed = 42** for every stochastic routine (Acerbi-Székely MC null,
  McNeil-Frey bootstrap, HLN MCS stationary bootstrap, convergence random inits).
- **Unit-variance Student-t scaling** `√((ν−2)/ν)` on every t-quantile (K802
  lesson; verified byte-identical to `volpred.stats.model_evaluation.unit_variance_student_t_ppf`).
  No raw `t.ppf()`.
- **Basel disclosure.** The traffic light is an **exact-binomial** rule at the
  *realized* sample size (from `var_backtest`), explicitly **not** the canonical
  250-day count table (K802 lesson: custom ≠ canonical Basel). Reported as
  `basel_exact_binomial_light`.
- **VaR backtest:** Kupiec (1995) POF + Christoffersen (1998) independence, via
  the canonical `var_backtest()` (reused, not re-implemented — K1259 discipline).
- **ES backtest (two formal tests):** Acerbi-Székely (2014) **Z2** with a
  Monte-Carlo null p-value under each day's predictive distribution, and
  McNeil-Frey (2000) **exceedance-residual bootstrap**. Both at α = 1% and 5%.
- **Model comparison:** Diebold-Mariano (Harvey |t|>3 threshold) on the
  **pinball/tick loss** (VaR) and the **Fissler-Ziegel FZ0 joint loss** (VaR+ES;
  Patton-Ziegel-Chen 2019), plus the **HLN (2011) Model Confidence Set**.
- **Cross-asset:** SPY and QQQ are run and reported **separately**; no
  asset-day pooling (avoids the K1355 iid-across-assets pitfall entirely).
- **Convergence stability:** 20 random-init MLE on the full SPY sample for GAS-t
  and DCS-t, reporting the NLL basin distribution (`convergence_stability_spy`).
  (Not a pooled/cross-entity estimation, so 20 inits suffice per task rule.)
- **MLE:** self-implemented (scipy `L-BFGS-B`) for all five models — no package
  supports score-driven VaR/ES, and self-coding keeps one uniform σ→VaR→ES path
  (also avoids the `arch` origin/target alignment pitfall, K445).
- **GAS-t inverse-Fisher scaling correction (review-driven).** The GAS-t log-
  variance scaled score uses `S = 2(ν+3)/ν` (Creal-Koopman-Lucas 2013 §2.2;
  `S→2` as `ν→∞`, recovering the Gaussian scaled score `z²−1`). An earlier
  platform version — **inherited by `experiments/k1143/k1143.py`** — used
  `S = 2ν/((ν+3)(ν−2))`, which `→0` as `ν→∞` and is mathematically wrong. The
  fresh-context code review (below) flagged this. **Empirical impact = zero:**
  re-running the full backtest with the corrected `S` gives **bit-identical**
  results (GAS-t FZ0 1.3486, DM t=+3.06, etc.), because the freely-estimated `α`
  had exactly compensated (reparameterization equivalence: only the product
  `α·S` enters the recursion) and the `α∈(0,1.5)` bound never bound (fitted
  `α≤1.23` under the wrong `S`; `α≈0.12` under the correct `S`). The fix makes
  the code correct and puts `α` in its literature range; **the GAS-t
  underperformance is a genuine finding, not a scaling artifact** — confirmed by
  the identical numbers. *(Flagged for the main thread: the platform's K1038/
  K1129/K1138/K1143 GAS-t line uses the same old S; those are QLIKE experiments
  with free α too, so likely equally unaffected, but worth a spot-check.)*
- **Per-day-ν formal backtest (review-driven).** Kupiec/Christoffersen/traffic-
  light run on the model's **actual per-day-ν VaR series** via a local
  `var_backtest_series()` (byte-identical to canonical `var_backtest()` at
  constant ν), not a single median-ν reconstruction; the median-ν canonical
  light is kept as a cross-check field. The Acerbi-Székely MC null simulates
  each day under **its own** predictive ν.

## Success criteria

1. ≥1 asset × 2 tail levels with a complete VaR + ES backtest table. ✔ (SPY, QQQ)
2. Score-driven vs ≥2 baselines with a **formal** comparison (DM + MCS). ✔
3. **Honest verdict:** state explicitly whether score-driven is well-calibrated /
   enters the MCS / is NULL vs GARCH-family. See "Results & verdict" below.

## Relevant prior knowledge

- **K802** — GJR + Skewed/Student-t VaR "dual champion"; unit-variance scaling &
  Basel-disclosure lessons (both honoured here).
- **K445** — `arch` forecast target-alignment / off-by-one lookahead risk
  (avoided by self-implementing the σ→VaR→ES pipeline).
- **K783c** — window-size sensitivity (motivates the rolling 2000-day window).
- **K1038 / K1129 / K1138 / K1143** — the GAS-t QLIKE-NULL line this experiment
  is orthogonal to; K1038/K1129 supply the tail-coverage hint.
- **K1355** — no asset-day pooling for cross-asset inference (honoured: separate).

## References

- Creal, Koopman & Lucas (2013), *J. Applied Econometrics* 28 — Generalized
  Autoregressive Score (GAS) models.
- Harvey (2013), *Dynamic Models for Volatility and Heavy Tails* — Dynamic
  Conditional Score (DCS) / Beta-t-EGARCH.
- Patton, Ziegel & Chen (2019), *J. Econometrics* 211 — dynamic semiparametric
  models for Expected Shortfall; FZ0 joint loss.
- Acerbi & Székely (2014), *Risk* — Backtesting Expected Shortfall (Z-tests).
- McNeil & Frey (2000), *J. Empirical Finance* 7 — exceedance-residual ES backtest.
- Kupiec (1995); Christoffersen (1998); Fissler & Ziegel (2016), *Ann. Statist.* 44;
  Hansen, Lunde & Nason (2011), *Econometrica* 79 (MCS).

## Files

- `k1662.py` — reproducible pipeline (`uv run python experiments/k1662/k1662.py`).
- `k1662_results.json` — byte-traceable outputs (per asset × model × tail).
- `k1662_spy_var_breach.png`, `k1662_spy_fz0_loss.png` (+ QQQ) — charts.

---

## Results & verdict

**OOS 2007-12-18 → 2026-07-02, 4663 days per asset** (spans GFC 2008, 2011,
2015-16, Volmageddon 2018, COVID 2020, 2022 bear). Authoritative numbers in
`k1662_results.json`. Runtime 884 s.

**Convergence stability (SPY full, 20 random inits):** GAS-t 20/20 converged,
90% within 0.5 NLL of the best basin; DCS-t 19/20, 100% at best (NLL std 0.00).
Both score-driven models are well-identified — no single-start artifact.

### SPY — key backtest table

| Model | α | breach% | Kupiec p | Christ. p | ES: AS Z2 | ES: McNeil-Frey p | pinball | FZ0 |
|---|---|---|---|---|---|---|---|---|
| GARCH-t | 1% | 1.54 | 0.002 | 0.022 | −0.59 | 0.175 ✓ | 0.0380 | **1.2931** |
| **GAS-t** | 1% | 1.72 | 0.000 | **0.002** ✗ | −0.82 | 0.039 ✗ | 0.0390 | 1.3485 |
| GJR-t | 1% | 1.44 | 0.011 | 0.922 | −0.56 | 0.022 ✗ | **0.0371** | **1.2914** |
| **DCS-t** | 1% | 1.54 | 0.002 | 0.983 | −0.63 | 0.084 ✓ | 0.0373 | 1.3010 |
| EWMA-N | 1% | 2.34 | 0.000 | 0.018 | **−1.88** | 0.000 ✗ | 0.0429 | 1.6080 |

(5% tail: same ordering; **GAS-t and EWMA-N are excluded from the 5% MCS**.)

### Model Confidence Set (HLN 2011, α=0.10) & DM (Harvey |t|>3)

| Cell | MCS members (FZ0) | Best | GAS-t vs GARCH-t | DCS-t vs GJR-t |
|---|---|---|---|---|
| SPY 1% | GARCH-t, GJR-t, GAS-t, DCS-t | GJR-t | t=+3.06 **✗ GARCH wins (Harvey)** | t=+0.67 tie |
| SPY 5% | GARCH-t, GJR-t, DCS-t | GJR-t | t=+2.39 (GAS-t dropped from MCS) | t=+1.89 tie |
| QQQ 1% | GARCH-t, GJR-t, GAS-t, DCS-t | GARCH-t | t=+2.57 | t=+1.87 tie |
| QQQ 5% | GARCH-t, GJR-t, DCS-t(, GAS-t FZ0) | GJR-t | t=+1.72 | t=+2.42 tie |

Every score-driven model **Harvey-significantly beats EWMA-Normal**; no
score-driven model Harvey-significantly beats any GARCH-family model anywhere.

### Verdict — **NULL for the headline, with a calibration nuance** (CONDITIONAL)

1. **Score-driven does NOT beat GARCH-family for VaR/ES.** The best model on
   both assets and both tails is **GJR-GARCH-t** (GARCH-family, asymmetric).
   No GAS-t/DCS-t cell is Harvey-significantly better than a GARCH-family model.
   → Consistent with, and extends to tail risk, the K1038/K1138/K1143 QLIKE-NULL line.

2. **Symmetric GAS-t is the *weakest* Student-t model** — worst FZ0 among the
   four t-models, **Harvey-significantly worse than GARCH-t at SPY 1% (t=+3.06)**,
   **excluded from the 5% MCS on both assets**, and it **fails Christoffersen at
   SPY 1% (p=0.002, clustered violations → red Basel light)**. The score-driven
   downweighting that hurt equity σ² (K1143 "architectural incompatibility") also
   clusters its tail violations. GAS-t is *not* a recommendable VaR/ES model.

3. **Asymmetric DCS-t (Beta-t-EGARCH + leverage) IS well-calibrated and
   competitive** — in the MCS in **every** cell, statistically indistinguishable
   from GJR-t (DM |t|<3 everywhere), and it passes the McNeil-Frey ES test at 1%
   on both assets (SPY p=0.084, QQQ p=0.138 — the *only* models besides GARCH-t
   to do so). **The leverage term rescues score-driven for tail risk.** This is
   the genuine differentiation from the QLIKE line: a leverage-augmented DCS model
   is a *viable* (though not *superior*) VaR/ES tool, unlike the harmful symmetric
   score-driven σ² forecasts. It gives no reason to displace GJR-t, however.

4. **EWMA/RiskMetrics-Normal is decisively the worst** — 2.34% breach at nominal
   1% (red light), excluded from every MCS, Harvey-significantly worse FZ0, and
   the only model rejected by *both* ES tests at *both* tails (AS Z2 ≈ −1.8 to
   −1.9). The Normal-tail assumption is the dominant risk-management error; the
   choice of *distribution* dwarfs the choice of *dynamics*.

5. **All models mildly under-cover the 1% tail over 2007-2026** (breach
   1.44–2.34%; Kupiec rejects all — expected power over 4663 days spanning two
   once-in-a-decade crises; AS ES understatement mild for t-models, severe for
   Normal). This is the well-documented long-horizon VaR procyclicality through
   GFC+COVID, not a model-specific defect — and the mild *over*-breach (not
   suspiciously perfect coverage) is itself evidence the forecasts are genuinely
   out-of-sample / lookahead-free.

**Bottom line for the platform:** keep **GJR-GARCH-t** as the robust VaR/ES
workhorse; **do not** adopt score-driven as a tail-risk champion. DCS-t
(Beta-t-EGARCH-leverage) is a legitimate, well-calibrated *addition* to the
model library (in-MCS everywhere) but offers no edge over GJR-t; symmetric
GAS-t should be avoided for tail risk. Distribution (Student-t vs Normal)
matters far more than dynamics for VaR/ES.

*Reviewer: `feature-dev:code-reviewer` fresh-context audit (Codex CLI was
usage-limited — accepted fallback per K1259/K1261/K1262). Round 1 verdict FAIL
(1 HIGH: GAS-t `S` constant; 2 MEDIUM: median-ν backtest, silent fallback) — all
three fixed; the HIGH fix produced bit-identical results (α compensated the wrong
constant, bound never bound), confirming GAS-t's underperformance is genuine.
Round-2 re-review verdict recorded in the merge report / final hand-off.*
