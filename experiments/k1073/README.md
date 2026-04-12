# K1073: A4f Exogenous Variable Sensitivity — VIX9D vs VIX vs VIX3M vs VVIX

**[提出: Claude, 執行: Claude]**
**Date: 2026-04-12**
**Status: Complete**

## Motivation

K988, K1056, K1066 all used **VIX² (30-day)** as the A4f-GARCH exogenous
regressor and reported strong OOS improvement vs GJR baseline. But CBOE
publishes multiple implied volatility horizons, and no prior experiment
systematically tested which is best as the A4f long-run driver:

- **VIX9D** — 9-day implied vol (most reactive)
- **VIX** — 30-day (standard)
- **VIX3M** — 3-month (smoother)
- **VVIX** — vol-of-VIX (second-order)

## Research questions

| # | Hypothesis | Verdict |
|---|-----------|---------|
| H1 | VIX² is the best A4f exog for SPY | **FAIL (close)** / **PASS (oc)** — VIX9D is marginally best on both targets; only Harvey-sig on r²_oc |
| H2 | Adding VIX3M−VIX slope as second regressor adds marginal contribution | **FAIL** — SLOPE does not beat A4f-VIX on either target |
| H3 | Optimal VIX choice differs by target (close vs oc) | **FAIL** — VIX9D wins on both targets (same choice) |
| H4 | θ₁ CV differs meaningfully across variants | **Descriptive finding** — VVIX most stable (CV 0.60), VIX/VIX9D oc targets least stable (CV 4.6–5.5) |

## Data

- **SPY**: daily Adj Close + Close + Open, yfinance
- **VIX family**: ^VIX, ^VIX9D, ^VIX3M, ^VVIX, yfinance
- **Period**: 2011-01-04 to 2026-04-10 (VIX9D binding: starts 2011-01-03)
- **n**: 3831 total, 3330 OOS observations
- **OOS**: 2013-01-02 onwards (~13 years)
- **Random seed**: 42

Descriptive statistics (full sample):

| | mean | std | min | max | AC(1) |
|---|---|---|---|---|---|
| VIX | 18.17 | 6.85 | 9.14 | 82.69 | 0.963 |
| VIX9D | 17.54 | 8.24 | 7.10 | 106.66 | 0.935 |
| VIX3M | 20.05 | 6.07 | 11.85 | 72.98 | 0.979 |
| VVIX | 96.37 | 16.13 | 61.76 | 207.59 | 0.939 |

Correlation: VIX ~ VIX9D = 0.972, VIX ~ VIX3M = 0.972, VIX ~ VVIX = 0.692.

## Methods

### Specifications (14 models)

Common multiplicative form (Engle et al. 2013): σ²_t = τ_t · g_t with
g_t = ω_g + α·u²_{t−1} + γ·u²_{t−1}·I{u<0} + β·g_{t−1} and
u_{t−1} = r_{t−1}/√τ_t.

| Model | τ_t formula |
|-------|-------------|
| GJR_close / GJR_oc | Standard GJR(1,1), baseline |
| A4f-VIX | θ₀ + θ₁·VIX²_{t−1} |
| A4f-VIX9D | θ₀ + θ₁·VIX9D²_{t−1} |
| A4f-VIX3M | θ₀ + θ₁·VIX3M²_{t−1} |
| A4f-VVIX | θ₀ + θ₁·VVIX²_{t−1} |
| A4f-SLOPE | θ₀ + θ₁·VIX²_{t−1} + θ₂·(VIX3M−VIX)_{t−1} |
| A4f-COMBO | θ₀ + θ₁·VIX9D²_{t−1} + θ₂·VIX²_{t−1} + θ₃·VIX3M²_{t−1} |

Each A4f spec fit for both r_close and r_oc targets → 12 A4f models.

### Fit & evaluation

- Window 2000, refit every 63 days, 53 total refits
- L-BFGS-B with 3 multi-starts; A4f negative log-likelihood numba-compiled
- Targets: r²_close and r²_oc
- Metrics: Patton (2011) QLIKE, MSE, MAE, Spearman ρ
- Pairwise DM tests: Newey-West HAC (lag T^(1/3))
- Harvey (2016) |t| > 3.0 threshold for significance

### Lookahead audit (passed)

- `vix_lag[t] = vix[t-1]` implemented in `build_vix2_lag`
- OOS forecast at day `abs_idx` uses `X²_{abs_idx-1}` (pre-determined)
- g-state carried forward between refits; no future returns leak in

## Results

### QLIKE ranking (lower is better, Patton 2011 proxy-robust)

**On r²_close** (close-to-close target):

| Rank | Model | QLIKE | Spearman ρ |
|---|---|---|---|
| 1 | A4f-VIX9D_close | -8.6675 | 0.4490 |
| 2 | A4f-VIX_close | -8.6499 | 0.4347 |
| 3 | A4f-SLOPE_close | -8.6221 | 0.4373 |
| 4 | A4f-VIX3M_close | -8.6116 | 0.4111 |
| 5 | A4f-VVIX_close | -8.5880 | 0.4000 |
| 6 | GJR_close | -8.5607 | 0.3727 |
| 7 | A4f-COMBO_close | -8.4803 | 0.4345 |

**On r²_oc** (open-to-close target):

| Rank | Model | QLIKE | Spearman ρ |
|---|---|---|---|
| 1 | A4f-VIX9D_oc | -9.0959 | 0.4373 |
| 2 | A4f-VIX_oc | -9.0768 | 0.4250 |
| 3 | A4f-COMBO_oc | -9.0481 | 0.4557 |
| 4 | A4f-VIX3M_oc | -9.0436 | 0.4078 |
| 5 | A4f-VVIX_oc | -9.0146 | 0.3969 |
| 6 | GJR_oc | -8.9789 | 0.3680 |
| 7 | A4f-SLOPE_oc | -8.9807 | 0.4248 |

### Key DM tests (Newey-West, |t|>3 = Harvey-significant)

**vs GJR baseline (r²_close target, same-target A4f variants):**
- A4f-VIX9D vs GJR: **t = +7.51 ★★★**
- A4f-VIX vs GJR: **t = +7.17 ★★★**
- A4f-VIX3M vs GJR: **t = +4.64 ★★★**
- A4f-VVIX vs GJR: t = +2.84
- A4f-SLOPE vs GJR: t = +2.21
- A4f-COMBO vs GJR: t = −0.63 (GJR wins — COMBO degenerates)

**vs GJR baseline (r²_oc target):**
- A4f-VIX9D vs GJR: **t = +6.22 ★★★**
- A4f-VIX vs GJR: **t = +6.08 ★★★**
- A4f-SLOPE vs GJR: **t = +5.60 ★★★**
- A4f-COMBO vs GJR: **t = +5.53 ★★★**
- A4f-VIX3M vs GJR: **t = +4.75 ★★★**
- A4f-VVIX vs GJR: **t = +3.17 ★★★**

**VIX9D vs VIX (head-to-head):**
- On r²_close: t = **+2.70** (below Harvey 3.0, not sig) → H1 FAIL on close
- On r²_oc: t = **+3.53 ★★★** → H1 PASS on oc (VIX9D Harvey-significantly better)

**SLOPE vs VIX:**
- On r²_close: t = −1.10 (VIX wins, not sig) → H2 FAIL
- On r²_oc: t = −0.28 (VIX wins, not sig) → H2 FAIL

### θ₁ stability (CV = std/|mean| across 53 refits)

| Model | θ₁ mean | θ₁ std | CV |
|-------|---------|--------|-----|
| A4f-VVIX_close | 6.76e-09 | 4.05e-09 | **0.599** (most stable) |
| A4f-VVIX_oc | 3.65e-09 | 2.71e-09 | 0.744 |
| A4f-VIX9D_close | 1.33e-04 | 1.99e-04 | 1.501 |
| A4f-VIX3M_oc | 5.28e-07 | 9.44e-07 | 1.787 |
| A4f-VIX3M_close | 1.53e-06 | 2.75e-06 | 1.795 |
| A4f-VIX_close | 1.53e-05 | 4.60e-05 | 3.000 |
| A4f-VIX9D_oc | 2.56e-06 | 1.17e-05 | 4.567 |
| A4f-VIX_oc | 4.00e-07 | 2.22e-06 | **5.545** (least stable) |

**Observation**: θ₁ stability is *inversely* correlated with predictive power —
VVIX has the most stable θ₁ but is the weakest predictor. This is a known
GARCH-MIDAS identification issue (see limitations).

### τ contribution and identification caveat

The τ-component of A4f absorbs a non-trivial fraction of total variance —
but the τ/σ² ratio is **not directly interpretable** in our specification
because we use a free-ω_g parametrization without the E[g]=1 normalization of
the original GARCH-MIDAS. The product τ · g is well-identified (the forecast
itself is valid), but the τ vs g decomposition is not. See limitations.

The post-hoc τ statistics (using per-refit params) show A4f-VIX9D_close has
51% of OOS days with τ exceeding 10× the unconditional r²_close mean, which
reflects the bimodal fit landscape (L-BFGS-B alternates between two local
optima across refits) rather than an invalid forecast. QLIKE remains the
relevant comparison metric.

### MSE blowup in SLOPE_close and COMBO_close

`SLOPE_close` MSE = 1.22e+07 and `COMBO_close` MSE = 1.79e+08 indicate some
refit windows produce τ+θ₂·slope < 0 corrections that compound into extremely
large σ² forecasts in rare periods. QLIKE is less sensitive (log-scale) but
still shows their inferiority. **Finding**: over-parametrized specs (7-8
params with collinear VIX family) are numerically unstable.

## Verdicts

- **H1 — VIX² is the best A4f exog**: **FAIL on r²_close, PASS on r²_oc**
  - VIX9D is marginally better on both targets
  - Harvey-significant only on r²_oc (t=+3.53)
  - On r²_close the margin is t=+2.70 (meaningful but not Harvey-sig)
- **H2 — SLOPE adds marginal contribution**: **FAIL**
  - SLOPE ties with or slightly worse than A4f-VIX on both targets
  - Term structure information is redundant with VIX level (which it drives)
- **H3 — Best choice differs by target**: **FAIL**
  - VIX9D wins on both close and oc targets (same winner)
- **H4 — θ₁ stability**: VVIX most stable, VIX/VIX9D_oc least stable
  - Inverse relationship with predictive power (normalization artifact)

## Paper 9 implication

**RECOMMENDATION: Keep A4f-VIX as main specification, add A4f-VIX9D as a
robustness check in the appendix.**

Rationale:

1. **Marginal gain is modest**: VIX9D improvement over VIX is 0.18% QLIKE on
   r²_close and 0.21% QLIKE on r²_oc. DM t-stat +2.70 / +3.53 is real but
   only one target crosses Harvey 3.0 threshold.
2. **Data availability narrower**: VIX9D starts 2011-01 vs VIX 1990, cutting
   ~20 years of potential OOS.
3. **VIX literature precedent**: VIX² is the industry-standard regressor;
   deviating requires stronger evidence than marginal improvement in one
   target.
4. **Robustness value**: Adding VIX9D appendix strengthens Paper 9 by
   demonstrating A4f is not sensitive to the specific horizon chosen —
   any VIX-family variable works, supporting the "VIX content, not horizon
   specifics" claim.

**DO NOT switch to VIX9D as main spec** given:
- Harvey 3.0 threshold crossed only on r²_oc (one of two targets)
- Shorter historical coverage
- Magnitude of improvement small in absolute terms (<1% QLIKE)

## Figures

1. `k1073_dm_matrix.png` — 8×8 DM t-stat heatmap on r²_close + r²_oc
2. `k1073_theta1_stability.png` — θ₁ time series for 4 single-X variants
3. `k1073_qlike_ranking.png` — QLIKE ranking of all models on both targets
4. `k1073_tau_contribution.png` — mean τ/σ² ratio (not directly interpretable, see caveat)
5. `k1073_comparison_table.png` — QLIKE/Spearman/DM heatmap summary

## Limitations

1. **Normalization not imposed**: Our A4f uses free ω_g instead of E[g]=1
   normalization (Engle, Ghysels, Sohn 2013). This means τ vs g are not
   separately identified; τ/σ² ratios are descriptive only.
2. **Bimodal optimization**: L-BFGS-B finds two local optima across refits
   (a "tau-dominated" regime and a "g-dominated" regime). The forecast
   σ² = τ·g is the same in both regimes at equilibrium, so forecasts are OK,
   but parameter trajectories are bimodal.
3. **Sample**: OOS starts 2013 (post-crisis). Cannot extrapolate to 2008-09
   regime. VIX9D availability is the binding constraint.
4. **VIX family collinearity**: VIX, VIX9D, VIX3M pairwise ρ > 0.9. COMBO
   spec suffers from collinearity and is numerically unstable.
5. **Single asset (SPY)**: Cross-asset validation (QQQ, GLD, 0050.TW)
   deferred to future experiments.
6. **Single-exog scope**: Did not test VIX + macro variables, VIX + realized
   variance, or nonlinear transformations (log VIX, square-root VIX).

## References

- **Engle, Ghysels & Sohn (2013)**. Stock market volatility and macroeconomic
  fundamentals. *Review of Economics and Statistics* 95(3):776-797.
  [GARCH-MIDAS multiplicative framework]
- **Patton (2011)**. Volatility forecast comparison using imperfect
  volatility proxies. *Journal of Econometrics* 160:246-256.
  [QLIKE proxy-robust loss]
- **Harvey, Liu & Zhu (2016)**. …and the cross-section of expected returns.
  *Review of Financial Studies* 29:5-68.
  [Harvey t > 3.0 threshold under multiple testing]
- **Hansen & Lunde (2005)**. A forecast comparison of volatility models.
  *Journal of Applied Econometrics* 20:873-889.
  [Proxy-robust loss functions]
- **CBOE**. VIX, VIX9D (9-day), VIX3M (3-month), VVIX (vol-of-VIX)
  methodology white papers.
- **K988**: A4f with VIX² DM t=4.48 vs GJR (Paper 9 baseline).
- **K1056**: A4f-VIX 5/5 sub-period stability.
- **K1066**: A4f_oc vs GJR_oc on r²_oc DM t=+7.05.

## Reproduction

```bash
cd /Users/yhlai0911/Desktop/volpred-research
uv run python experiments/k1073/k1073.py
uv run python experiments/k1073/k1073_postprocess.py  # per-refit tau stats
```

Runtime: ~30 seconds (numba-compiled likelihoods).
Output: `k1073_results.json` + 5 PNGs.

## Follow-up ideas

1. **Normalization fix**: Re-estimate with E[g]=1 constraint (Engle et al.
   2013) to make τ/σ² interpretable and stabilize θ₁.
2. **Log-VIX transform**: Test τ = θ₀ + θ₁·log(VIX) as in MIDAS literature.
3. **Cross-asset VIX sensitivity**: Run K1073 on QQQ, GLD, 0050.TW; for
   0050.TW use VIXTWN as main and test VIX as cross-market proxy.
4. **Time-varying VIX choice**: Test if VIX9D wins in high-vol regimes and
   VIX3M wins in low-vol regimes (regime-switching A4f).
5. **Pre-2008 extension**: Re-estimate VIX and VIX3M (both available) from
   2000+ to include crisis period, accepting VIX9D exclusion.
