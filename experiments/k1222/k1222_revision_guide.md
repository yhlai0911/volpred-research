# Paper 2 §5 Revision Guide (post-K1216b)

> **Status**: Markdown revision guide for main-thread cherry-pick into
> `paper/<paper2>/body_v(n+1).tex`. Per CLAUDE.md paper-workflow rule,
> this worktree agent does **not** write to paper `.tex`; body rewrite
> stays in the main thread. All numbers **verbatim** from source
> experiment JSONs (K1163 / K1165 / K1168 / K1172 / K1171 / K1173 /
> K1204 / K1207 / K1213 / K1216 / K1216b).
>
> **Supersession log**:
> - K1211 `k1211_draft.md` (commit `9efffe4b`): 7-iteration trajectory
>   STRENGTHENED narrative — **SUPERSEDED**.
> - K1215 `k1215_revised_draft.md` (commit `45f621ee`): K1213 AU
>   `ABOVE_LADDER_OVERTURNED` integration, STRENGTHENED + 3 caveats —
>   **SUPERSEDED**.
> - K1216 (commit `cbc852ae`) + K1216b (commit `ee923da1`):
>   `WIDESPREAD_FRAGILITY` → `ALL_5_EM_FRAGILE`. All 5 EM pooled MLE
>   trapped in secondary local minima; primary Spearman collapses to
>   `ρ = −0.071, p = 0.817, Harvey t = −0.24` at N=13.
> - **K1222 (this guide)**: consolidated revision — within-market channel
>   and K1207 sector-FE retained as primary; cross-market institutional
>   ladder **WITHDRAWN** and demoted to methodology-appendix artefact.

---

## 1. Narrative State Transition

The cross-market institutional-ownership ladder story went through three
evolutions within a 48-hour window; each subsequent evidence layer
strictly dominated (higher-LL basin, larger multistart budget, wider
EM coverage) the previous one:

| Stage | Exp | Evidence scope | Primary ρ (N=13) | Narrative |
|---|---|---|---|---|
| v4-K1211 | K1165→K1171 canonical | 7 iter, single-start pooled MLE | **+0.385, p=0.194** (primary) / +0.441 at N=12 | "STRENGTHENED cross-market ladder + 3 caveats" |
| v4-K1215 | + K1213 AU multistart | K1213 overturns AU below-ladder | **+0.418, p=0.156** (primary) | "STRENGTHENED + AU reclassified above-ladder" |
| **v4-K1222 (this)** | + K1216/K1216b 5-EM audit | ALL 5 EM pooled canonical fits trapped | **−0.071, p=0.817, Harvey t=−0.24** | "Within-market + sector-FE dominant; ladder WITHDRAWN as local-min artefact" |

The K1211 → K1215 → K1222 ρ trajectory is **+0.385 → +0.418 → −0.071**
at N=13. The decisive swing happened at K1216b: refining the 5 EM
pooled fits (BR, IN, MX, CH, ID) to their global-LL optima with a
100-random-start protocol dragged the primary Spearman **1.16 σ to the
wrong side of zero** (Δρ = −0.489 vs K1215 baseline). The effect that
K1211 / K1215 reported as "above-ladder EM cluster differentiating the
institutional-ownership slope" was an artefact of single-start L-BFGS-B
getting stuck in low-θ basins for all 5 EM pools, not a real rank
ordering.

## 2. Core Claim Changes Table

| Element | K1211 Original | K1215 Revised | **K1222 (post-K1216b)** |
|---------|----------------|----------------|---------------------------|
| Primary ρ (N=13) | +0.385 p=0.194 *STRENGTHENED trajectory* | +0.418 p=0.156 *STRENGTHENED + AU above-ladder* | **−0.071 p=0.817** *COLLAPSE after 5-EM multistart* |
| Primary ρ (N=12) | +0.441 p=0.152 | +0.441 p=0.152 | **−0.077 p=0.812** |
| Harvey t (ρ proxy) | +1.55 (N=12 cluster-bootstrap) | +1.55 → +1.52 | **−0.24 (PRIMARY), p>>0.5** |
| Institutional ladder | cross-market anchor, "STRENGTHENED" | cross-market anchor with AU reclass | **NUMERICAL ARTEFACT — WITHDRAWN** |
| Sector-FE role | secondary channel to inst-FE | secondary channel to inst-FE | **PRIMARY cross-market driver** (adj-R² 0.148 = 32× inst-FE's 0.0046) |
| Panel Harvey t | 3.236 → 3.808 monotonic (within-market) | unchanged (AU revision only affects cross-market) | **UNCHANGED** — within-market panel invariant to pooled-MLE basin choice |
| Within-market analyst channel | robust (Harvey t>3 at all 5 iter) | robust | **ROBUST — UNCHANGED** |
| K1213 AU `θ_rel` status | not yet available | canonical θ_rel = 1.476 "above-ladder" | still basin-B best, but K1216b context shows AU is **one of 5 EM markets** all with this pathology, so the "AU-specific above-ladder" framing of K1215 is itself subsumed |
| K1173 EM scale-factor | EM cost-of-capital residual | EM cost-of-capital residual | **QUALIFIED** — K1173 ρ rebuild used canonical (trapped) EM `θ_rel`; refit is required before any EM-scale claim survives |
| Number of residual caveats in §5.7 | 3 (EM / AU / EU) | 3 (EM / AU reclassified / EU) | **2 surviving** (EU low-cluster robust; within-market inst_pct/analyst two-level), plus **1 methodology appendix** disclosing multistart fragility |

## 3. Full Revised §5 Structure

The revised §5 replaces K1211's / K1215's "cross-market ladder as headline
result + residual caveats" with a **within-market + sector-FE dominant
headline + cross-market ladder demoted to methodology appendix artefact**
structure. Subsections renumber accordingly.

### §5.1 Within-market analyst-attention mechanism (primary result)

The cross-market panel (K1166 → K1171 pooled TW / EU / JP / US / KR / HK /
CA / BR / IN / CH / MX / ID / AU, total N=172 stocks × mean 2955 trading
days) supports a **within-market** analyst-attention channel. The joint
panel OLS with market fixed effects, `log_analyst`, `log_mcap`,
`institutions_pct`, cluster-robust SE (by market), yields Panel Harvey
|t|(`log_analyst`) sequence **3.236 → 3.556 → 3.627 → 3.789 → 3.808**
across the K1165 → K1166 → K1168 → K1172 → K1171 N-extension iterations.
All five iterations are above Harvey (2016) |t|>3, the sequence is
**monotonically increasing**, and `institutions_pct` remains
statistically insignificant in every iteration (|t|<1, coefficient
β ≈ −1.27e-3 → −1.22e-3 stable across the same extension).

Crucially, this panel Harvey t **does not consume any pooled-MLE
`θ_EAV` input** — the within-market regression uses stock-level GJR
volatility + analyst coverage + institutional ownership + market fixed
effects, computed independently of the shared-MIDAS pooled-fit basin.
Therefore the K1213 / K1216 / K1216b pooled-MLE fragility described in
§5.4 below **does not affect §5.1**; the within-market result is
invariant to the entire pooled-MLE controversy.

The structural-stability of this channel across the trajectory is the
primary Paper 2 §5 cross-market finding.

### §5.2 Sector-FE dominant cross-market decomposition (K1207)

K1207's GICS sector fixed-effect augmentation of the K1171 panel
(N=172 × 12-market pool, 10 GICS sectors present, Utilities absent)
reveals that **sector composition** — **not** cross-market
institutional ownership — is the dominant within-market driver:

- **Sector-FE incremental adjusted R² (M3 − M1) = 0.148**; inst-FE
  incremental adjusted R² (M2 − M1) = **0.0046**. Sector explains
  **approximately 32×** more within-market θ_rel variation than
  institutional ownership.
- **Sector-FE joint F = 689.5, p = 7.9 × 10⁻¹⁴** under
  market-clustered SE.
- **`inst_pct` coefficient stable** across M2 → M4: β = −1.27e-3 →
  −1.22e-3 (|Δβ|/|β| = 4.4%), |t|<1 in both specifications. Adding
  sector FE does not kill the already-weak within-market `inst_pct`
  channel — it leaves sign, magnitude, and significance essentially
  unchanged.
- **Cross-sector Spearman**(sector median θ_EAV, sector median
  `inst_pct`) = **−0.006, p = 0.987, n = 10**. The two variables are
  empirically **independent** at the sector level.
- **Sector-adjusted residuals** absorb the above-ladder EM residual
  magnitudes by: **IN 95.4%, MX 78.2%, BR 38.6%**. At pool level,
  sector composition is the dominant channel behind the EM
  above-ladder residual magnitudes.

These sector-FE pool statistics are pool-level quantities — they do
not depend on any individual market's pooled `θ_EAV` basin choice. They
therefore survive the K1213 / K1216 / K1216b pooled-MLE fragility
described in §5.4.

**K1207 verdict (retained, re-headlined as §5.2 primary)**:
`SECTOR_ORTHOGONAL_CONFIRMED`. Sector and institutional ownership are
statistically independent within-market channels. Sector composition is
the **primary cross-market driver** of the θ_rel heterogeneity that
K1168 / K1172 originally attributed to the institutional-ownership
ladder.

### §5.3 European full-coverage robustness (K1163) — RETAINED

K1163 full N=30 (10 DAX + 10 CAC + 10 FTSE, 100% coverage) refit yields:

- θ_EAV = **5.22e-5** (K1153 4.07e-5; Δ = +1.15e-5),
- cluster-bootstrap t = **4.807** (K1153 4.19; Δ = +0.62),
- placebo z = **22.27σ** (K1153 14.77σ; Δ = +7.50),
- θ_rel = **0.194** (K1153 0.137; Δ = +0.057),
- bootstrap 95% CI for θ_rel = **[0.127, 0.277]**.

All three strength-of-evidence statistics **strengthen** under full
coverage. θ_rel point-estimate moves up but 95% CI upper bound 0.277
stays below the high-cluster lower bound of 0.30 — EU remains squarely
in the **low cluster (≤ 0.25)**. The four developed-market classification
(TW + EU low vs JP + US high) **survives full coverage**. K1152
quarterly-density hypothesis (rejected in K1153) remains rejected.
**Verdict: ROBUST.** This result is a within-market bootstrap result on
the EU panel alone and is independent of the cross-market pooled-MLE
basin controversy.

This caveat is retained as a stand-alone EU-specific robustness bullet
in the final §5.7 narrative commitment below.

### §5.4 Cross-market institutional-ownership ordering — RETRACTED (K1216 / K1216b / K1213 multistart audit)

K1211 §5.1 / K1215 §5.1 framed the cross-market trajectory
K1165 ρ = +0.750 → K1168 +0.612 → K1172 +0.441 → K1171 +0.385 (primary)
/ +0.418 (K1215 K1213 AU correction) as "STRENGTHENED". K1216 / K1216b
demonstrate this trajectory is a **pooled-MLE numerical artefact**. The
retraction is decisive at the following quantitative level:

**(i) AU K1213 precedent.** K1213 ran 100 L-BFGS-B random multi-starts
on the K1171 pooled MLE (seeds 43..142). The K1171 canonical LL =
89047.22 was not a local maximum of the pooled likelihood — it sat
between two basins. Basin-B best LL = 89146.69 gives
**LR = 2·ΔLL = 198.9 >> χ²(1) = 3.84**; basin-B NM polish pushes
LR further to **511.9** at θ_rel = 1.070. Basin-B canonical
**θ_rel ∈ [1.07, 1.48]** replaces K1171 θ_rel = 0.150.

**(ii) K1216 BR / IN / MX audit (commit `cbc852ae`).** Same 100-start
protocol applied verbatim to the other 3 canonical off-ladder EM
markets:

| Market | Canon `θ_rel` | Refined `θ_rel` (NM polish) | Canon LL | Refined LL | **LR stat** | HAC t | Verdict |
|---|---|---|---|---|---|---|---|
| BR | 1.887 | **2.691** | 72213.52 | 72286.35 | **145.66** | 3.24 | **FRAGILE** |
| IN | 1.170 | **3.077** | 81844.51 | 82049.89 | **410.76** | 6.58 | **FRAGILE** |
| MX | 1.202 | **1.845** | 75932.06 | 76105.69 | **347.27** | 3.74 | **FRAGILE** |

All 3 LR statistics blow past χ²(1) = 3.84 by two orders of magnitude.
Refined `θ_rel` shifts by 43 – 163 % from canonical. NM refinement
consistently beats L-BFGS-B best for all 3 markets, by +73, +103, +154
LL units — the L-BFGS-B 100-multistart search alone would have
under-reported the true best-LL basin for BR / MX. K1216 cross-market
verdict: `WIDESPREAD_FRAGILITY`.

**(iii) K1216b CH / ID closing audit (commit `ee923da1`).** The same
protocol applied to the canonical low-`θ_rel` EM pools:

| Market | Canon `θ_rel` | Refined `θ_rel` (NM polish) | Canon LL | Refined LL | **LR stat** | HAC t | Verdict |
|---|---|---|---|---|---|---|---|
| CH | 0.304 | **1.469** | 77922.50 | 78221.47 | **597.94** | 3.00 | **FRAGILE** |
| ID | 0.238 | **1.917** | 76494.23 | 76676.91 | **365.36** | 2.54 | **FRAGILE** |

Low `θ_rel` did NOT protect the pool from the pathology — it made the
fragility **worse** in relative terms (3.8× CH, 7.1× ID shifts vs
1.4 – 2.6× for BR / IN / MX). Under shared-MIDAS + stock-FE-GJR, every
EM pool has a high-θ basin with strictly higher LL than the "natural"
default-init basin, and only aggressive multistart search finds it.
K1216b cross-market verdict: `ALL_5_EM_FRAGILE`.

**(iv) 5-EM refined Spearman at the global optimum.**

| Scenario | N | **ρ** | **p** | Harvey t | Status |
|---|---|---|---|---|---|
| K1172 baseline (canonical) | 12 | +0.441 | 0.152 | +1.55 | retracted input |
| K1213 AU only (canonical EM + refined AU) | 13 | +0.418 | 0.156 | +1.52 | retracted input |
| K1216 EM refined (BR/IN/MX; CH/ID canon) | 12 | +0.364 | 0.245 | +1.23 | interim |
| K1216 EM + K1213 AU | 13 | +0.341 | 0.255 | +1.20 | interim |
| **K1216b 5-EM refined (BR/IN/MX/CH/ID)** | **12** | **−0.077** | **0.812** | **−0.24** | **global optimum** |
| **K1216b 5-EM + K1213 AU N=13 (PRIMARY)** | **13** | **−0.071** | **0.817** | **−0.24** | **global optimum** |

At the global optimum the primary Spearman is `ρ = −0.071, p = 0.817,
Harvey t = −0.24` at N=13. The 1.16-σ swing happens almost entirely
when the CH + ID refined `θ_rel` (1.47, 1.92) replace canonical
(0.30, 0.24): CH and ID have LOW `institutions_pct_mean` (0.157, 0.154)
yet at the global optimum carry HIGH `θ_rel`, **breaking the rank
concordance** that drove +0.44 at the K1172 baseline.

**(v) Conclusion.** The K1165 → K1171 cross-market Spearman trajectory
was driven by the single-point default initialization consistently
landing in low-θ_EAV basins for all 5 EM pools. Correcting to the global
optimum erases the institutional-ownership ladder. The cross-market
institutional-ownership rank ordering is **formally withdrawn from
Paper 2 §5 as a finding**; it is relocated to §5.5 (methodology
appendix) as a documented optimizer-fragility case study.

**Per-market effect sign and significance at the refined optimum
survive** (HAC t ≥ 2.54 for every market). What is withdrawn is the
**cross-market rank concordance** claim — i.e., the claim that
`institutions_pct_mean` predicts `θ_rel` ordering across markets.

### §5.5 Methodology appendix: multistart pooled-MLE diagnostic protocol

Post-K1213 / K1216 / K1216b, Paper 2 adopts the following pooled-MLE
protocol for all cross-market shared-MIDAS + stock-FE-GJR fits on
small-S panels (S ≤ 10, which is every market in the current Paper 2
panel):

1. **≥ 50 L-BFGS-B random multi-starts** (K1213 / K1216 / K1216b used
   100). Starts are log-uniform on `θ_EAV, θ_0 ∈ [1e-6, 5e-4]` with
   random α / γ / β within the shared-MIDAS + stock-FE-GJR persistent
   bounds.
2. **Penalty-trap guard** rejecting `res.fun > 1e11` or `−res.fun < 1000`.
3. **K-means (K=2) basin identification** on converged `(θ_EAV, LL)`
   pairs, reporting basin-A / basin-B fraction, mean θ, max LL per
   basin.
4. **Best-LL across all converged starts** = L-BFGS-B global
   estimate.
5. **Sensitivity polish**: Nelder-Mead warm-start from L-BFGS-B best +
   differential-evolution. DE consistently penalty-walled in the
   K1213 / K1216 / K1216b runs and is excluded from the sensitivity
   delta metric (reported for transparency).
6. **Refined best-LL** = max over valid optimizers.
7. **LR test** against canonical: `LR = 2·(LL_refined − LL_canonical)`
   vs χ²(1) = 3.84 (5% cutoff) and half-threshold 1.92 (profile-LR
   ROBUST cutoff).
8. **Standard errors at the refined point**: numerical Hessian on
   `θ_EAV` (primary) + HAC-robust sandwich based on stock-level score
   contributions (stocks independent, so no lag kernel).
9. **Cross-market rebuild**: refit every market's `θ_rel = θ_EAV_pooled
   / σ²_sample_mean`, then re-compute Spearman
   ρ(institutions_pct_mean, θ_rel) at the global optima.
10. **Seed discipline**: base 42; 100 start seeds 43..142; DE seed
    base+7; K-means seed 42. Identical across markets for reproducibility.

**K1213 / K1216 / K1216b record** (verbatim):
- AU (K1213): canonical θ_rel = 0.150 → basin-B best 1.476 (NM 1.070);
  LR = 198.9 (511.9 NM-polished).
- BR (K1216): 1.887 → 2.691; LR = 145.66.
- IN (K1216): 1.170 → 3.077; LR = 410.76.
- MX (K1216): 1.202 → 1.845; LR = 347.27.
- CH (K1216b): 0.304 → 1.469; LR = 597.94.
- ID (K1216b): 0.238 → 1.917; LR = 365.36.

All 6 markets (5 EM + AU) reject the canonical single-start estimate
at p < 10⁻³⁰ under the standard nested-LR inference. The diagnostic
protocol is recorded in this appendix; any future cross-market addition
to Paper 2 must document multistart basin structure per this
specification.

### §5.6 Narrative commitment — FINAL (K1222)

> *The within-market analyst-attention mechanism is robust: Panel Harvey
> |t|(`log_analyst`) grows monotonically 3.236 → 3.808 across five
> N-extension iterations (K1165 → K1166 → K1168 → K1172 → K1171; N=172
> stocks, 12 markets, 2011 – 2025), all above the Harvey (2016) |t|>3
> threshold. In every iteration `institutions_pct` is insignificant
> within market (|t|<1, β ≈ −1.25e-3 stable). GICS sector fixed effects
> add an incremental adjusted R² of 0.148 (**≈ 32×** the incremental
> adjusted R² of institutional ownership, 0.0046), with joint
> F = 689.5, p = 7.9 × 10⁻¹⁴ (market-clustered SE; K1207). Sector
> composition and institutional ownership are statistically independent
> at the sector level (cross-sector Spearman `ρ = −0.006, p = 0.987`).
> European panel full-coverage robustness (K1163) keeps EU in the
> low-cluster under N=30 with bootstrap t = 4.81 and 95% CI
> θ_rel ∈ [0.127, 0.277], excluding the high-cluster lower bound 0.30.*
>
> *The cross-market institutional-ownership ordering claim of K1168 /
> K1172 / K1211 / K1215 is formally **withdrawn**. A 100-multistart
> re-estimation (K1213 AU; K1216 BR / IN / MX; K1216b CH / ID) finds
> that all 5 EM pooled-MLE canonical fits sit in secondary local
> minima of the shared-MIDAS + stock-FE-GJR likelihood. At the
> global optimum the primary cross-market Spearman
> `ρ(institutions_pct_mean, θ_rel) = −0.071, p = 0.817, Harvey
> t = −0.24` (N=13; K1216b). The K1165 N=7 ρ = +0.750 through K1171 /
> K1213 N=13 ρ = +0.418 trajectory reported in K1211 / K1215 was
> driven by single-start L-BFGS-B consistently landing in low-θ_EAV
> basins for all 5 EM pools; correcting to the global optimum erases
> the institutional-ownership ladder. Per-market effect sign and
> significance survive at the refined optimum (HAC t ≥ 2.54 every
> market), but the cross-market rank concordance does not.*
>
> *Paper 2 §5 therefore commits to **two** cross-market structural
> drivers of θ_rel — within-market analyst attention (primary) and
> within-market GICS sector composition (primary; K1207). Institutional
> ownership operates at the within-market level with weak / insignificant
> coefficients and at the cross-market level does not rank-order θ_rel
> at the global pooled-MLE optimum. All future pooled MLE on the
> shared-MIDAS + stock-FE-GJR spec must follow the §5.5 multistart
> diagnostic protocol.*

## 4. Cherry-pick Instructions for Main Thread

Main-thread body rewrite (delegated to main thread per CLAUDE.md
paper-workflow rule) should apply the following swaps to the most
recent K1215-integrated `body_v(n).tex`:

1. **§5.1 opening paragraphs** — keep K1215's Panel Harvey t
   monotonic 3.236 → 3.808 passage verbatim. Remove the second paragraph
   that discusses between-market Spearman as a headline; defer the
   between-market Spearman to the new §5.4 / §5.5 placement as a
   retracted artefact.
2. **§5.2 two-level variance decomposition** — retain the 7.86× – 8.79×
   ratio table (between inst_pct R² ≈ 0.42; within log_analyst R² ≈
   0.053) but append a sentence that the between-market R² is now
   interpreted as a reduced-form pool description, not as evidence of
   a ranked institutional-ownership ladder.
3. **K1211 §5.6 / K1215 §5.6 (sector orthogonality, K1207)** →
   **promote to new §5.2** as a primary cross-market finding. This is
   the most substantive relocation: what was a caveat becomes the
   headline cross-market result. K1207 verdict
   `SECTOR_ORTHOGONAL_CONFIRMED` is the surviving cross-market headline.
4. **K1211 §5.3 / K1215 §5.3 (EM scale-factor + K1173)** — remove the
   "developed-ladder slope vs EM absolute scale as two separate
   parameters" framing. The K1173 ρ rebuild used canonical (trapped)
   EM `θ_rel` values (+0.385 primary, Δρ −0.056 band). Under K1216 /
   K1216b refined `θ_rel` the K1173 rebuild should be re-run; the
   yfinance-artefact falsification (K1173 verdict NULL) is invariant
   to the basin choice because it depends on per-stock proxy swaps, not
   pooled `θ_EAV` magnitudes, but the aggregate-ρ number needs a
   verbatim recomputation under K1216 / K1216b refined inputs in the
   main-thread body rewrite. Consider deferring K1173 to §6 / robustness
   section rather than §5.
5. **K1211 §5.4 / K1215 §5.4 (EU K1163)** — retain **unchanged** as the
   new §5.3. This is a within-market bootstrap finding independent of
   the cross-market pooled-MLE controversy.
6. **K1211 §5.5 / K1215 §5.5 (AU trajectory)** — absorb into the new
   §5.4 RETRACTED section. Do **not** retain as a stand-alone subsection.
   K1215's "AU reclassified above-ladder" framing is subsumed by the
   K1216b ALL_5_EM_FRAGILE finding: AU is not a special case; it is
   one of 5 EM pools with the same pathology. The narrative pivot point
   is now "all 5 EM pooled canonical fits are numerical artefacts",
   not "AU specifically is reclassified".
7. **Insert new §5.4** (RETRACTED cross-market trajectory) verbatim
   from §3 above of this guide. Include the 6-row LR-stat table and
   the 6-row Spearman rebuild table verbatim.
8. **Insert new §5.5** (multistart methodology appendix) verbatim from
   §3 above. This is net-new content; no prior K1211 / K1215 subsection
   covered it.
9. **Replace K1211 §5.7 / K1215 §5.7** (Narrative commitment FINAL)
   with the new §5.6 FINAL block above. Delete the three-caveat
   structure; replace with the two-cross-market-drivers commitment.

### Figure mapping updates

- **Figure 5A** (ρ trajectory) — main thread must annotate K1216b N=13
  point at **ρ = −0.071**. The updated figure now shows the decisive
  1.16-σ swing from K1215 +0.418 to K1216b −0.071 at N=13 due to EM
  multistart correction.
- **Figure 5B** (Panel Harvey t monotonic) — UNCHANGED; within-market
  panel is invariant.
- **Figure 5C** (two-level R²) — UNCHANGED; between-R² interpretation
  footnote added.
- **Figure 5D** (EM residual taxonomy) — REPLACE with a basin-structure
  visual per market (K1216/K1216b basin histograms overlaid). The old
  K1204 Figure D is retired because its above-ladder color-coding
  assumed the canonical (trapped) `θ_rel` as ground truth.
- **Figure 5E** (K1163 EU robustness) — UNCHANGED.
- **Figure 5F** (K1207 sector-FE incremental adj-R²) — PROMOTED to
  Figure 5B-equivalent prominence (new §5.2 headline figure).
- **Figure 5G** (K1213 basin bimodality) — EXPAND into a 6-market
  basin-bimodality panel figure using K1216 BR / IN / MX histograms +
  K1216b CH / ID histograms + K1213 AU histogram. This is the key
  methodology-appendix visual (new §5.5).
- Trajectory table (Table 5) — replace with the 6-row LR-stat + 6-row
  Spearman rebuild tables from §3 above.

### Machine-readable canonical inputs

- Trajectory table: `experiments/k1216b/k1216b_results.json` (6-row
  `paper2_s5_full_trajectory_table`) supersedes both
  `experiments/k1211/k1211_panorama.csv` and
  `experiments/k1215/k1215_revision_stats.json`.
- Per-market LR stats: `experiments/k1216/k1216_per_market_summary.csv`
  + `experiments/k1216b/k1216b_per_market_summary.csv` + K1213's AU
  result in `experiments/k1213/k1213_results.json`.
- Primary Spearman: `k1216b_5em_refined_au_n13_primary`
  (`ρ = −0.07142857142857142, p = 0.8166280406760862, N=13`).

## 5. Provenance and rigour

All numbers in this guide are **verbatim** from source experiment
JSONs — no re-estimation. The six markets whose pooled-MLE estimates
are retracted (AU, BR, IN, MX, CH, ID) are the six markets audited
under the K1213 / K1216 / K1216b 100-start L-BFGS-B + NM + DE protocol
with identical seeds (base 42; starts 43..142; DE seed 49; K-means seed
42). The shared-MIDAS + stock-FE-GJR spec and bounds are identical to
K1168 / K1172 — no spec widening. Lookahead guard inherited from
`_pooled_negll` (VIX²_{t-1}, EAV_{i,t-1}).

The remaining 7 developed markets in the N=13 panel (TW, EU, JP, US,
KR, HK, CA) have not yet been multistart-audited. K1222 §5.5
methodology appendix recommends a K1216c extension to run the same
100-start protocol on all 7 developed pools to confirm the ladder
base is stable under the global optimum. Main thread may elect to
(a) defer the K1216c audit to a supplementary appendix, or (b) commission
K1216c before final body rewrite. Either decision is consistent with
the §5.6 commitment, because the within-market Panel Harvey t channel
is invariant to pooled-MLE basin choice — the K1216c outcome only
affects the cross-market institutional-ownership retraction's
completeness, which is already decisively committed.

## 6. Supersession summary

- **K1211** (commit `9efffe4b`, `experiments/k1211/k1211_draft.md`):
  entire 7-iteration §5 superseded. §5.6 sector discussion survives as
  new §5.2 primary headline.
- **K1215** (commit `45f621ee`,
  `experiments/k1215/k1215_revised_draft.md`): entire §5 superseded.
  §5.3 / §5.4 (K1173 EU robustness / K1163 EU) absorbed into new §5.3;
  §5.5 / §5.6 (AU reclassification / K1207 sector) absorbed into new
  §5.2 and §5.4 respectively. §5.7 FINAL narrative commitment replaced
  by §5.6 above.
- **K1222 (this document)**: active revision guide. Main-thread cherry-
  pick target.

---

## Table: K1222 Superseding Narrative Summary

| Version | §5 Headline | Primary ρ (N=13) | Sector-FE status | Caveats | Ladder status |
|---|---|---|---|---|---|
| K1211 | Cross-market ladder STRENGTHENED | +0.385 (p=0.194) | secondary | 3 (EM/AU/EU) | active |
| K1215 | Cross-market ladder STRENGTHENED + AU reclassified | +0.418 (p=0.156) | secondary | 3 (EM/AU-reclass/EU) | active |
| **K1222** | **Within-market + sector-FE dominant; cross-market ladder WITHDRAWN** | **−0.071 (p=0.817)** | **PRIMARY** | **1 (EU retained) + 1 methodology appendix** | **retracted as local-min artefact** |

---

Machine-readable canonical diff: `experiments/k1222/k1222_revision_diff.json`.
