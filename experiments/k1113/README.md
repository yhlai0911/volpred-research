# K1113 — Firm-level covariate rule for Paper 2 selection (PRE-REGISTERED, CONFIRMATORY)

> **TL;DR**: All 5 pre-registered hypotheses **FAIL**. Observable, continuous
> firm characteristics (market cap, beta, earnings frequency, trading volume,
> price volatility, industry-relative momentum) **cannot predict** A4f-EAV θ₂
> within this N=31 TW panel. Leakage-free 5-fold CV R² = -0.661; no covariate
> survives BH-FDR (min adj p = 0.854); **no firm** is classified as Tier A
> under a correctly-specified prediction interval. Combined with K1109 (sector
> dummies also fail), the meta-finding is that **θ₂ heterogeneity is not
> explainable by publicly observable firm attributes** — it must either be
> idiosyncratic or require unobserved variables (insider/analyst flow, corporate
> governance, opacity, etc.).

---

## 1. Motivation (Why)

K1109 used pre-registered N=31 sampling to test sector heterogeneity in θ₂ (the
A4f-EAV coefficient on scheduled-earnings τ). Result: sector dummies **failed**
(joint F(7,20)=1.31, p=0.297; no BH-FDR survivor). But K1109's full regression
found two continuous covariates with marginal White-SE significance:

| covariate | K1109 coef | K1109 p_white |
|---|---|---|
| log_mktcap_z | −4.40e-4 | 0.027 |
| beta_rolling_z | +5.45e-4 | 0.010 |

This suggested firm-level (not sector-level) attributes might carry the signal.
Paper 2 needs a concrete, operational selection rule, not "some sectors are
better". So K1113 pre-registers a **continuous-covariates-only** regression with
6 covariates (2 from K1109 + 4 new), and a prediction-based Tier A/B/C rule.

**Problem**: sector dummies soak up variance that K1109 attributed to size/beta
because of collinearity. K1113 drops sector dummies entirely, so we get a clean
test of whether observable firm characteristics have genuine predictive power.

**Caveat (E052, E053)**: we pre-registered the full covariate list and the
hypotheses **before** running the extended regression (see `pre_registration`
section of `k1113_regression_results.json` — the SHA256 of the script is
recorded alongside the results). No cherry-picking.

---

## 2. Pre-registration (locked before extended regression)

Covariates (locked):
```
log_mktcap           (from K1109 firm_level_results.csv; yfinance marketCap)
beta_rolling_0050    (from K1109; rolling 252-day regression against 0050.TW)
earnings_freq_per_year  (from K1109; avg per year from 財報公告日期 file)
log_avg_volume       (K1113: log of past-252-day avg daily volume, yfinance)
price_volatility     (K1113: past-252-day annualized daily log-return std)
ind_momentum         (K1113: past-252-day ticker return − 0050.TW return)
```

Hypotheses (locked):
| # | Rule | Result |
|---|------|--------|
| H1 | At least 1 covariate BH-adj p_hc1 < 0.05 | **FAIL** (min = 0.854) |
| H2 | log_mktcap_z coef < 0 AND p_hc1 < 0.10 | **FAIL** (coef=−1.10e-4, p=0.682) |
| H3 | price_volatility_z coef > 0 AND p_hc1 < 0.10 | **FAIL** (coef=+3.28e-5, p=0.854) |
| H4 | 5-fold CV R² > 0 (leakage-free) | **FAIL** (CV R² = −0.661) |
| H5 | Tier A count ≥ 3 (pred CI excludes 0, pred > 0) | **FAIL** (Tier A = 0) |

Script hash in results JSON: `pre_registration.script_sha256_short`.
Seed = 42 everywhere (numpy `default_rng`). Bootstrap: 5000 reps.

---

## 3. Method (What)

1. **Input**: K1109's `firm_level_results.csv` (31 firms × θ₂ + θ₂_se already
   estimated by identical A4f-EAV MLE as K1106b/K1109).
2. **Extend covariates**: compute 3 new covariates from K1109's cached price
   parquets (no re-download; same data window as K1109).
3. **Regression**: OLS with HC1 (White) robust SE, on z-scored covariates.
4. **Multiple-testing correction**: Benjamini-Hochberg FDR on the 6 covariate
   HC1 p-values.
5. **Inference**: pairs bootstrap 5000 reps with seed=42 for each coefficient
   95% CI.
6. **Predictive validity**: 5-fold CV with **per-fold z-scoring** (leakage-free,
   see §5 for bug and fix).
7. **Tier classification**: for firm *i*, predicted θ₂ = x_i'β̂, with full
   prediction variance
   `pred_var = σ̂² + x_i' Cov_HC1 x_i`
   (includes **both** coefficient uncertainty and residual variance; see §5).
   95% prediction CI: `pred ± 1.96 · √pred_var`.
   - Tier A: CI fully > 0
   - Tier C: CI fully < 0
   - Tier B: CI overlaps 0
8. **Secondary** regression: add `analyst_count` (yfinance `numberOfAnalystOpinions`,
   29/31 firms have data, median-imputed for the 2 missing).
9. **Leave-one-out sensitivity**: drop `log_mktcap` or `beta_rolling_0050` and
   refit.

**Baseline reference**: K1109 sector-dummies full model R² = 0.340 (in-sample,
p_ANOVA = 0.297 → the R² is over-fit noise, not signal).

---

## 4. Results

### 4.1 Primary regression (N=31)

| Covariate (z-scored) | β | t_HC1 | p_HC1 | BH-adj p |
|---|---|---|---|---|
| log_mktcap | −1.10e-4 | −0.41 | 0.682 | 0.854 |
| beta_rolling_0050 | −8.96e-5 | −0.33 | 0.746 | 0.854 |
| earnings_freq_per_year | +5.72e-5 | +0.50 | 0.623 | 0.854 |
| log_avg_volume | +1.98e-4 | +1.21 | 0.239 | 0.854 |
| price_volatility | +3.28e-5 | +0.19 | 0.854 | 0.854 |
| ind_momentum | −5.81e-5 | −0.53 | 0.598 | 0.854 |

In-sample R² = 0.116, R²_adj = −0.105, **leakage-free 5-fold CV R² = −0.661**.

**Every bootstrap 95% CI (5000 reps) crosses zero.** No covariate separates
from noise.

### 4.2 Cross-check with K1109 sector model

| Model | R² (in-sample) | CV R² | Note |
|---|---|---|---|
| K1109 sector+cov (full, 10 regressors) | 0.340 | — (K1109 didn't report CV) | p_ANOVA=0.297; in-sample R² is over-fit |
| K1109 cov-only (reduced, 3 regressors) | 0.038 | — | all coefs p>0.5 |
| **K1113 firm cov (6 regressors)** | **0.116** | **−0.661** | leakage-free CV |
| K1113 drop log_mktcap (5 regressors) | 0.107 | −0.372 | |
| K1113 drop beta_rolling (5 regressors) | 0.109 | −0.412 | |

All CV R² are **strongly negative** → the model predicts worse than simply
predicting the sample mean for every firm.

### 4.3 Tier classification

With correctly-specified prediction SE (including residual variance):

| Tier | Definition | n_firms | |
|---|---|---|---|
| **A** (recommended for EAV) | pred CI entirely > 0 | **0** | — |
| **B** (neutral / use baseline A4f) | pred CI overlaps 0 | **31** | all |
| **C** (avoid EAV) | pred CI entirely < 0 | **0** | — |

**Meaning**: at N=31, no firm has a prediction precise enough — based on
observable characteristics — to recommend different model selection. This is
the honest answer to "which firms should use A4f-EAV instead of A4f baseline?".

### 4.4 Secondary regression (6 + analyst_count, n=31 with 2 median-imputed)

All 7 covariates still fail BH-FDR (min adj p = 0.740). analyst_count alone:
coef=+2.05e-4, p_hc1=0.281. In-sample R²=0.204, CV R² (leakage-free) still
large-negative.

### 4.5 Top-5 / Bottom-5 observed θ₂ (for reference only, not a rule)

| Top 5 (most positive θ₂) | Sector | θ₂ |
|---|---|---|
| 3035 FarEastone Info | fabless | +1.20e-3 |
| 2382 Quanta | ems | +7.44e-4 |
| 2317 Hon Hai | ems | +7.25e-4 |
| 3034 Novatek | fabless | +7.02e-4 |
| 2347 Synnex | consumer | +6.66e-4 |

| Bottom 5 (most negative θ₂) | Sector | θ₂ |
|---|---|---|
| 2379 Realtek | fabless | −2.39e-3 |
| 2454 MediaTek | fabless | −1.61e-3 |
| 6239 Powertech | foundry | −1.60e-4 |
| 2388 VIA Tech | fabless | −1.05e-4 |
| 3443 GlobalWafer | fabless | −9.63e-5 |

Both tails are dominated by fabless — but this is the same pattern K1109 showed
would not survive BH-FDR after correction. The "fabless is special" narrative
from K1106b was cherry-picked and is not real.

---

## 5. Codex code review and fixes

Codex (GPT-5) flagged **2 HIGH-severity bugs** in the original code after the
first run:

| Bug | Problem | Fix |
|-----|---------|-----|
| **CV leakage** | z-score mean/sd computed on the full sample, then same design matrix fed into `_kfold_cv`. Test folds "saw" their own observations in the standardization step. | Added `_kfold_cv_leakage_free`: for each fold, compute mean/sd only on training fold, then transform test fold with those statistics. CV R² was and remains −0.661 (the leakage effect was negligible because all 6 covariates z-score nearly the same whether or not 6 test points are included; but the fix makes the test logically correct). |
| **Wrong prediction SE** | `tier_classification` used only `sqrt(x'Cov_HC1 x)` (coefficient uncertainty) as the prediction SE. This is the SE of the fitted mean, not the prediction interval SE — it omits residual variance, making the CI artificially narrow. | Changed to `pred_var = σ̂² + x'Cov_HC1 x` where σ̂² = ss_res/dof. After fix, Tier A count fell from 1 (2002 China Steel, an obvious in-sample fluke) to 0. This confirms the earlier Tier assignment was driven by the bug, not real signal. |

Both fixes pushed results in the direction of **stronger null** (i.e., the
original code was mildly optimistic). This is reassuring: the methodology
failure is even more decisive after the fix.

Codex's review of HC1 OLS, BH-FDR, pairs bootstrap, and the "z-score AFTER
NA-filter" order flagged no HIGH issues.

---

## 6. Paper 2 implication

**K1113 closes this path**. The selection-rule design for Paper 2 we had in
mind — "regress θ₂ on firm characteristics → predict → Tier firms" — is
**not viable** within the N=31 TW panel. The rule would classify every firm
as Tier B ("neutral, keep baseline A4f"), which is the same as having no rule.

**What to do in Paper 2** (updated after K1113):

1. **Report θ₂ heterogeneity as an unexplained empirical finding**, not a
   predictable one. List per-firm θ₂ in an appendix. Acknowledge that neither
   sector (K1109) nor firm characteristics (K1113) explain the cross-section.
2. **Pooled A4f-EAV remains the default**. Weight by firm in pooled estimation
   to pin down a "typical" θ₂ effect (if it exists in pooling).
3. **Propose follow-ups** for what *might* explain heterogeneity — e.g.:
   - Retail-order-flow fraction (see K992 family of studies)
   - Firm-level opacity / corporate-governance indices (TEJ has some, IFRS
     segment reporting could proxy)
   - Event-specific volume-anomaly pre-announcement (leaky news)
   - Optionable vs non-optionable firms (disagreement / short-interest
     asymmetry)
4. **Explicitly label this null result in the discussion** — it's a service to
   the literature. Too many empirical-finance papers stop at "there is
   heterogeneity"; we quantify that the heterogeneity is **unpredictable from
   public data** within a meaningful sample.

### Decision-flow diagram for Paper 2 (revised, honest version)

```
Input firm → Use baseline A4f (do NOT attempt firm-level EAV-selection rule).
           → Report pooled θ₂ with clustered-by-firm SE.
           → Mention the K1113 null result as motivation for future research.
```

We are **not** publishing a Tier A/B/C rule in Paper 2, because the rule would
be built on unsafe ground.

---

## 7. Limitations

- N=31 is small. A larger panel (all TW listings, N~300-500) could potentially
  find weak predictors. K1113's null does not rule out that possibility.
- The 6 covariates are all derived from *market* data; **firm-specific**
  qualitative attributes (corporate-governance quality, retail flow, opacity
  indices) might be the missing variables. But these require non-yfinance data
  sources.
- `analyst_count` was median-imputed for 2 missing firms. With 29/31 non-missing
  it's not unreasonable, but future work should use a complete dataset.
- `price_volatility` and `log_avg_volume` are both backward-looking 252-day
  windows ending at the sample end date — they may be collinear with each other
  in TW's market structure.
- θ₂ itself has considerable per-firm MLE uncertainty (some firms have
  θ₂_se > |θ₂|; K1109 noted this). OLS on noisy θ₂ is a model of attenuation
  bias; errors-in-variables would mechanically shrink coefficients toward zero.
  But the practical consequence is the same: we cannot separate signal from
  estimation noise.

---

## 8. Files

| File | Content |
|------|---------|
| `k1113.py` | Main pipeline (pre-registered design, CV fix, prediction-SE fix) |
| `k1113_regression_results.json` | All regression output + hypothesis verdicts + tier panel |
| `firm_covariates_extended.csv` | N=31 × 7 covariates (including analyst_count) |
| `tier_classification.json` | Paper 2 appendix-ready Tier A/B/C firm lists |
| `k1113_coefficient_forest.png` | Bootstrap 95% CI forest plot |
| `k1113_tier_scatter.png` | Predicted vs observed θ₂ by tier |
| `k1113_vs_k1109_sector_comparison.png` | R² bar comparison of K1109 sector model vs K1113 firm-level model (in-sample and CV) |
| `README.md` | This file |

---

## 9. Ancestry & references

- **K1104**: cross-sectional heterogeneity, N=24 stratified
- **K1106b**: cherry-picked N=14 (fabless "significant" at p=0.004) — now
  disproven (E052).
- **K1109**: pre-registered N=31 sector test, rejected sector dummies (E053
  documents the pre-registration value).
- **K1113** (this experiment): pre-registered continuous-covariate test,
  rejects firm-level observable rule.
- Benjamini & Hochberg (1995), BH-FDR.
- White (1980), HC0/HC1.

**Executed by**: Claude (worktree agent `agent-k1113`), Codex review by
GPT-5. Seed 42 everywhere, bootstrap n=5000, CV folds=5.
