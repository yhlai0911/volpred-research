# K1108c: Continuous guide_delta_pct as capex covariate (replace binary)

**提出**: 賴奕豪  **執行**: Claude  **日期**: 2026-04-17
**Parent**: K1108b (commit 5bcd8143, H2 DECISIVE NULL with binary flag)
**Grand-parent**: K1108 (TSMC single-firm, INCONCLUSIVE)

## 動機（Problem & Hypothesis）

K1108b pooled 5 foundry stocks (4 distinct firms) with a BINARY
`guide_updated` flag → pool Wald t=−0.0003, p=0.9997 → **H2 DECISIVE
NULL**. But a binary flag discards magnitude information: a ±1%
revision was treated the same as a ±60% MASSIVE RAISE. K1108c replaces
the binary split (θ_change vs θ_stable) with a SIGNED CONTINUOUS
regressor `guide_delta_pct` spanning the pool range [−69.6%, +136.8%]
to test whether MAGNITUDE matters.

**Hypotheses**:

| Label | Criterion | Implication |
|-------|-----------|-------------|
| **H1_MAGNITUDE_PASS** | \|t_HAC\| > 3.0 (Harvey 2016) AND bootstrap 95% CI excludes 0 | Magnitude reveals mechanism binary missed |
| **H2_MAGNITUDE_NULL** | \|t_HAC\| < 2.0 AND bootstrap CI spans 0 | K1108b null STRENGTHENED (capex has no power as binary OR continuous) |
| **H3_MAGNITUDE_MARGINAL** | 2.0 < \|t_HAC\| < 3.0 AND CI excludes 0 | Partial softening of K1108b null |

## 設計（Design）

### Two-stage regression

**Stage 1 (per-firm τ_EAV extraction)**: For each firm i, refit the
K1108b per-stock A4f-EAV model (θ₀, θ₁, θ_change, θ_stable, ω, α, γ, β
via MLE; layout from `k1108b.fit_one_stock`). For each event day d,
extract an event-day empirical long-memory shift

```
θ_EAV_empirical_{i,d} = r²_{i,d} / g_{i,d} − (θ̂_{0,i} + θ̂_{1,i}·VIX²_{d-1})
```

where g is the fitted GJR-GARCH short-run component evaluated at d.
This yields **one scalar per event** — unlike the fitted
θ̂_change/θ̂_stable scalars (which are invariant across events within a
firm-flag pair).

**Stage 2 (continuous magnitude test)**:

```
θ_EAV_empirical_{i,d} = β₀ + β₁ · guide_delta_pct_{i,d} + ε_{i,d}
```

- Newey–West HAC-robust SE, automatic bandwidth = ⌊4·(n/100)^(2/9)⌋
  (Andrews 1991) → bw = 4 for n=135
- Harvey (2016) threshold |t_HAC| > 3.0 for H1 confirmation
- Block bootstrap β₁ (N=1000, block=10, firm-stratified, seed=42)

### Robustness

1. **Winsorized [1%, 99%]** on guide_delta_pct to check tail influence
2. **Sign-asymmetry spec**: separate β_pos (on x⁺) and β_neg (on x⁻)
3. **Leave-one-firm-out** (LOO) at Stage 2
4. **Magnitude interpretation**: θ_EAV(+10%) − θ_EAV(−10%) from fit

### Data provenance

- **Per-firm frames**: reused from K1108b infrastructure (4 firms:
  2330.TW, 2303.TW, GFS, 0981.HK; TSM ADR excluded per K1108b primary
  analysis to avoid TSMC double-count)
- **guide_delta_pct magnitude table**: built by
  `k1108c_build_magnitude.py` from K1108/K1108b hand-coded dollar
  figures already recorded in `k1108b_fetch_capex_pool.py` note fields
  (e.g. "FY2022 guide ~$3.0bn sharp raise", "FY2023 CUT from $4.5bn").
  **No new external data fetches** — only numeric encoding of
  provenance already in K1108b.
- TSMC full midpoint timeline reused from
  `experiments/k1108/data/tsmc_capex_guidance.csv` (original K1108).

### Lookahead guard

- Stage 1 τ̂ uses VIX²_{d-1} and EAV_{d-1} per K1108b convention
- `guide_delta_pct_d` is event-day announcement known at market close
  (standard K1104/K1108/K1108b event-study window)
- `event_window_definition`: event dated at the NEXT trading close
  after the announcement (e.g. after-hours earnings → next trading
  day's open-to-close window); this is K1108b's searchsorted
  positioning, reused verbatim
- `np.random.seed(42)` fixed; numba-JIT deterministic

## 結果（Results）

### Sample

| Quantity | Value |
|----------|-------|
| Firms | 4 (2330.TW, 2303.TW, GFS, 0981.HK) |
| Total events extracted (Stage 1) | 136 |
| Events matched to magnitude table | 135 (7-day tolerance) |
| guide_delta_pct range (pool) | [−69.57%, +136.84%] |
| non-zero Δpct events | 77 |
| Newey–West bandwidth | 4 |

### Primary OLS/HAC (MAIN TEST)

| Parameter | Point est | HAC SE | HAC t | HAC p (two-sided) | 95% CI |
|-----------|-----------|--------|-------|-------------------|--------|
| β₀ (intercept) | +1.252e-03 | 4.39e-04 | +2.85 | 0.0043 | [+3.9e-04, +2.1e-03] |
| **β₁ (guide_delta_pct)** | **−1.286e-05** | **9.60e-06** | **−1.339** | **0.1804** | **[−3.17e-05, +5.96e-06]** |
| R² | 0.003 | — | — | — | — |

**β₁ is negative (wrong sign for H1 — a capex raise of +10% is
associated with a SMALL DECREASE of θ_EAV by 1.3e-04), small in
magnitude, and statistically indistinguishable from 0.**

### Block bootstrap β₁ (N=1000, block=10, firm-stratified)

| Statistic | Value |
|-----------|-------|
| Mean | −2.33e-06 |
| SD | 8.70e-06 |
| 95% CI | [−1.79e-05, +1.63e-05] |
| Two-sided bootstrap p | **0.7280** |

Bootstrap 95% CI **crosses zero** → no evidence of a non-zero β₁.

### Winsorized [1%, 99%]

| Parameter | Point est | HAC t | HAC p |
|-----------|-----------|-------|-------|
| β₁_wins | −1.594e-05 | −1.351 | 0.1768 |

Winsorization does not materially change the result.

### Sign-asymmetry spec

θ_EAV = β₀ + β_pos · max(x, 0) + β_neg · min(x, 0) + ε

| Parameter | Point est | HAC t | HAC p |
|-----------|-----------|-------|-------|
| β_pos | −2.319e-05 | −2.329 | 0.0198 |
| β_neg | +1.728e-05 | +0.646 | 0.518 |

**β_pos marginally significant (p=0.02) with counter-intuitive
negative sign** (larger capex RAISE → LOWER event-day long-memory
component). Fails Harvey threshold (|t|<3.0). β_neg insignificant.

Interpretation: if anything, large positive capex revisions are
associated with slightly CALMER post-event τ₂ — the opposite of what
the foundry-edge mechanism hypothesis would predict. This is
consistent with "positive guidance = certainty-reducing news" rather
than "positive guidance = volatility-inducing mechanism", but given
p=0.02 across 135 events it is not Harvey-robust and could reflect
mild specification search artefact.

### LOO by firm

| Dropped | n | β₁ | t_HAC | Change from primary |
|---------|---|----|----|---------------------|
| 2330.TW | 88 | −1.19e-05 | −1.011 | Stable negative |
| 2303.TW | 87 | −1.58e-05 | −1.009 | Stable negative |
| 0981.HK | 112 | −6.61e-06 | −1.064 | Stable negative |
| GFS | 118 | −2.07e-05 | −1.502 | Slightly stronger (still not significant) |

No single firm drives the result; all LOO |t_HAC| < 1.6.

### Magnitude interpretation

- θ_EAV(+10% guide) − baseline = **−1.29e-04**
- θ_EAV(−10% guide) − baseline = **+1.29e-04**
- Implied effect of a full-range swing (+60% vs −32% ≈ 92pt range):
  ≈ −1.18e-03 shift in θ_EAV — smaller than the cross-firm dispersion
  of θ̂_change in K1108b (~5e-03 range across 4 firms).

## 判定（Verdict）

### **H2_MAGNITUDE_NULL (DECISIVE)**

| Criterion | Threshold | Actual | Result |
|-----------|-----------|--------|--------|
| \|t_HAC\| > 3.0 | Harvey (2016) | 1.34 | **Fail** |
| \|t_HAC\| > 2.0 | Weaker | 1.34 | **Fail** |
| Bootstrap CI excludes 0 | direction | [−1.79e-05, +1.63e-05] | **Fail (spans 0)** |
| LOO \|t\| > 2 any exclusion | robustness | max 1.50 | **Fail** |
| R² | > 1% | 0.003 | **Fail** |

**K1108b binary NULL is STRENGTHENED by K1108c**. Whether we encode
the capex guidance as a binary flag (K1108b, t=−0.0003) or as a signed
continuous percentage change (K1108c, t=−1.34), the capex mechanism
produces **no significant explanatory power for foundry θ₂>0**.

## Implication for foundry mechanism paper (Paper 2)

The K1108 series (K1108 → K1108b → K1108c) is now an end-to-end
DECISIVE NULL on the capex-guidance hypothesis:

1. **K1108** (TSMC N=48): directionally supportive (+8e-5) but
   underpowered (t=0.94) → INCONCLUSIVE
2. **K1108b** (4-firm pool, N=136 binary): pool t=−0.0003, diff ≈ 0 →
   DECISIVE NULL
3. **K1108c** (4-firm pool, N=135 continuous ±69.6% range): HAC
   t=−1.34, bootstrap CI crosses 0 → DECISIVE NULL

**Capex guidance is NOT a codifiable foundry-specific signal driving
K1104's θ₂>0 pattern, in any measurable sense (direction, magnitude,
or sign asymmetry).** The Paper 2 foundry rule requires a mechanism
other than capex — candidates (per K1108b D2/D3/D4 backlog, to be
tested as K1120+):

- **D2 (non-capex quantitative guidance)**: utilisation rate,
  wafer-price, R&D guidance
- **D3 (operating leverage)**: foundry fixed-cost structure as driver
  without any earnings-day component
- **D4 (regional regime-aware spec)**: different foundry regimes
  (Taiwan vs US vs China) under export-control era

## 統計限制與誠實標註

- **guide_midpoint values** for UMC/GFS/SMIC are hand-coded from
  K1108b's note-field dollar figures. While these figures are traceable
  to public IR filings, they carry the same ±10% classification
  uncertainty flagged in K1108b §"Statistical limitations".
- **TSMC + TSM ADR** intentionally excluded from primary pool (to
  avoid same-firm double counting); an extended 5-firm spec would
  require the TSM-specific trading-day adjustment from K1108b — left
  as future work if any H1/H3 signal emerges.
- **β_pos p=0.02 is NOT Harvey-robust**. With k=2 additional
  regressors (pos/neg split) plus implicit family-wise choice across
  3 specs (primary / winsorized / sign-split), naïve α=0.05 is
  inappropriate. Under Bonferroni-corrected α=0.05/3=0.0167 even the
  nominal p=0.02 fails to reach significance.
- **θ_EAV_empirical construction** uses r²_d/g_d as the event-day
  τ estimate. This is a noisy per-event estimator (standard event
  study variance-shock extraction); it is unbiased under correctly
  specified GJR-GARCH but carries the usual Jensen inequality bias
  for τ under Gaussian innovations. Bootstrap CI absorbs this noise
  into the observed SE.
- **R²=0.003 is tiny** — guide_delta_pct explains 0.3% of event-day
  θ_EAV variance. Even if β₁ were Harvey-significant, the economic
  magnitude of the capex channel would be minor.
- **Null result reported in good faith per 誠實原則 §8/§9/§10**.

## Codex 審查

Per K1108b precedent, not requested for this null result. The
estimation pipeline is a direct extension of the K1108b codebase
(`k108b.build_pool`, `k108b.fit_one_stock`); the only new code is
the Stage 2 OLS/HAC and block bootstrap. Both are standard textbook
procedures with correctly-typed inputs. Lookahead convention unchanged
from K1108b.

## 檔案清單

- `README.md` — this file
- `k1108c.py` — main experiment (Stage 1 refit + Stage 2 OLS/HAC +
  bootstrap + sign asymmetry + LOO)
- `k1108c_build_magnitude.py` — helper: encodes K1108/K1108b note-field
  dollar figures into numeric guide_midpoint → guide_delta_pct CSVs
- `k1108c_results.json` — complete statistics
- `k1108c_merged_pool.csv` — merged (event, θ_EAV_empirical,
  guide_delta_pct, flag) table used in Stage 2
- `k1108c_scatter_theta_vs_deltapct.png` — scatter with fit line
- `k1108c_bootstrap_beta1.png` — bootstrap β₁ distribution histogram
- `run.log` — full stdout
- `data/2330_TW_capex_guidance_mag.csv` — TSMC with delta_pct
- `data/2303_TW_capex_guidance_mag.csv` — UMC with delta_pct
- `data/TSM_capex_guidance_mag.csv` — TSM ADR (=TSMC)
- `data/GFS_capex_guidance_mag.csv` — GFS with delta_pct
- `data/0981_HK_capex_guidance_mag.csv` — SMIC with delta_pct
- `data/pooled_capex_guidance_mag.csv` — concatenated pool (N=184)

## References

- K1108 (TSMC single-firm capex-guidance test — INCONCLUSIVE)
- K1108b (4-firm pooled binary — H2 DECISIVE NULL)
- K1104 (cross-sectional θ₂ foundry rule)
- K1166 (pooled stock-FE framework)
- K1067 (A4f-EAV baseline)
- Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).
- Andrews (1991). Heteroskedasticity and Autocorrelation Consistent
  Covariance Matrix Estimation. Econometrica 59(3):817-858. —
  automatic bandwidth for Newey-West
- Newey & West (1987). A Simple, Positive Semi-definite,
  Heteroskedasticity and Autocorrelation Consistent Covariance Matrix.
  Econometrica 55(3):703-708.
- Politis & Romano (1994). The Stationary Bootstrap. JASA 89:1303-1313.
- Patton (2011). Volatility forecast comparison. JoE 160:246-256.
- Harvey et al. (2016). ... and the Cross-Section of Expected Returns.
  RFS 29(1):5-68. — t > 3.0 threshold for multi-testing

## Data provenance

- Data period: 2014-01-03 → 2025-12-30
- Stage 1 firm-trading-day obs: 9,844 across 4 firms
- Stage 2 N: 135 firm-event rows (1 event unmatched to 7-day window)
- Capex midpoints: 100% traceable to K1108/K1108b note-field
  dollar figures (public IR archives)
- Random seed: 42
- OLS: numpy `np.linalg.pinv` (well-conditioned 2×2 / 3×3 designs)
- HAC: manual Newey-West with Andrews (1991) auto-bandwidth
- Bootstrap: firm-stratified block resampling, 1000 reps
