# Paper 2 §5 Revision Guide — post-K1216c FINAL

> ⚠️ **Supersedes K1222** (commit `75df1c8f`, `experiments/k1222/k1222_revision_guide.md`). K1222
> was written on top of the K1216b ρ = −0.071 "COLLAPSE" headline and framed the cross-market
> institutional-ownership ladder as WITHDRAWN. K1216c (commit `3cf6bc84`) has demonstrated that
> −0.071 was an **asymmetric-refinement artefact** — the result of mixing multistart-refined EM
> θ_rel with still-canonical (single-init, trapped-basin) DEV θ_rel. Once the identical 100-start
> protocol is applied across all 9 markets, the primary Spearman **rebounds** to ρ = +0.379
> (p = 0.201, N=13), statistically indistinguishable from canonical +0.441 under Fisher z
> (p ≈ 0.87).
>
> **Narrative state**: ladder is **MODESTLY WEAKER** (canonical +0.441 → refined +0.379) but
> **surviving**. Methodology appendix is **upgraded** from "diagnostic protocol" to an additional
> methodological contribution.
>
> All numbers are **verbatim** from source JSONs (K1211 / K1213 / K1216 / K1216b / K1216c / K1207 /
> K1163 / K1172). No new estimation in K1222b; worktree agent does not write to `.tex` per
> CLAUDE.md paper-workflow rule.

---

## 1. Narrative State Evolution

Paper 2 §5's cross-market story has moved through four evidence scopes. The K1222b FINAL scope
is the first to apply the identical 100-start protocol uniformly across the 9-market panel.

| Stage | Exp | Evidence scope | Primary ρ (N=13) | Narrative | Status |
|---|---|---|---|---|---|
| K1211 | K1165→K1171 canonical | single-start pooled MLE | **+0.385, p=0.194** / +0.441 N=12 | "STRENGTHENED ladder + 3 caveats" | superseded |
| K1215 | + K1213 AU multistart | AU above-ladder | **+0.418, p=0.156** | "STRENGTHENED + AU reclass" | superseded |
| K1222 | + K1216/K1216b 5-EM refined (DEV canonical) | **asymmetric**: 5 EM refined, 4 DEV canonical | **−0.071, p=0.817, Harvey t=−0.24** | "COLLAPSE; WITHDRAWN" | **SUPERSEDED — artefact** |
| **K1222b FINAL** | + K1216c 9-market audit | **symmetric**: 5 EM + 4 DEV + AU all refined | **+0.379, p=0.201, Harvey t=+1.36** | **"MODESTLY WEAKER + NEW methodology contribution"** | **active** |

The K1215 → K1222 swing of −0.489 (+0.418 → −0.071) was not an economic revelation — it was
an artefact of substituting refined EM θ_rel into a panel whose DEV θ_rel was still default-init
canonical. Once K1216c applies the multistart protocol to US/EU/JP/TW (all 4 FRAGILE, all 4
basin-B θ_rel much higher than canonical), DEV θ_rel rises in parallel, restoring the rank
concordance.

**Fisher-z equivalence test**: canonical +0.441 (N=12) vs refined +0.379 (N=13) → z_canon −
z_refined = 0.4735 − 0.3989 = 0.0746; SE = (1/9 + 1/10)^0.5 = 0.4595; z-stat = 0.16, two-sided
p ≈ 0.87. Canonical and K1216c refined **tell the same story**.

## 2. Core Claim Changes (K1211 → K1222b FINAL)

| Element | K1211 | K1215 | K1222 (SUPERSEDED) | **K1222b FINAL** |
|---------|-------|-------|--------------------|--------------------|
| Primary ρ (N=13) | +0.385 p=0.194 | +0.418 p=0.156 | **−0.071 p=0.817** *artefact* | **+0.379 p=0.201** *modestly weaker* |
| Primary ρ (N=12) | +0.441 p=0.152 | +0.441 p=0.152 | **−0.077 p=0.812** | +0.441 canonical reference; +0.379 N=13 is FINAL headline |
| Harvey t (panel) | +1.55 | +1.52 | **−0.24** (artefact) | **+1.36** |
| Ladder | STRENGTHENED | STRENGTHENED + AU reclass | **WITHDRAWN** (artefact) | **MODESTLY WEAKER but SURVIVING**; Fisher z ≈ canonical |
| Sector-FE (K1207) | secondary | secondary | PRIMARY (adj-R² 32× inst) | **PRIMARY** (unchanged) |
| Panel Harvey t | 3.236→3.808 | same | same | **3.236→3.808 UNCHANGED** |
| Within-market analyst | robust | robust | robust | **ROBUST UNCHANGED** |
| # caveats | 3 | 3 | 1 + appendix | **2 (EU + CA/HK/KR disclosure) + 1 NEW contribution** |
| Methodology | n/a | n/a | appendix only | **ADDITIONAL Paper 2 contribution (§5.4)** |
| # cross-market drivers | 1 (ladder) | 1 (ladder) | 2 (analyst + sector) | **3 (analyst + sector + modestly-weaker ladder)** |

K1222's "COLLAPSE" / "WITHDRAWN" framing is retired; K1222b restores the ladder while being
honest about (a) modest downward revision (+0.441 → +0.379), (b) non-significance at 5% for
both, and (c) the panel-wide multistart fragility requiring 10 × 100 = 1000 fits to resolve.

## 3. Full Revised §5 Structure (K1222b FINAL)

### §5.1 Within-market analyst-attention mechanism (primary result)

The cross-market panel (K1166 → K1171 pooled 13 markets, N=172 stocks × mean 2955 trading days)
supports a within-market analyst-attention channel. Joint panel OLS with market FE, `log_analyst`,
`log_mcap`, `institutions_pct`, cluster-robust SE yields Panel Harvey |t|(`log_analyst`) sequence
**3.236 → 3.556 → 3.627 → 3.789 → 3.808** across K1165 → K1166 → K1168 → K1172 → K1171. All
five above Harvey (2016) |t|>3; monotonically increasing; `institutions_pct` insignificant at
|t|<1 within every iteration, β ≈ −1.27e−3 stable.

This panel Harvey t does not consume pooled-MLE θ_EAV — it uses stock-level GJR volatility +
analyst coverage + institutional ownership + market FE, independent of the shared-MIDAS pooled-fit
basin. Therefore K1213 / K1216 / K1216b / K1216c pooled-MLE fragility **does not affect §5.1**.
This is the strongest and most robust Paper 2 §5 finding, invariant to the multistart controversy.

**Figure**: K1204 Figure B (Panel Harvey t trajectory), unchanged across all 4 versions.

### §5.2 Sector-FE dominant cross-market decomposition (K1207)

K1207's GICS sector FE augmentation of K1171 (N=172 × 12-market pool, 10 GICS sectors) establishes:

- Sector-FE incremental adjusted R² (M3 − M1) = **0.148**; inst-FE incremental adjusted R²
  (M2 − M1) = **0.0046**. Sector explains **≈ 32×** more θ_rel variation than inst ownership.
- Sector-FE joint **F = 689.5, p = 7.9 × 10⁻¹⁴** under market-clustered SE.
- `inst_pct` coefficient stable M2 → M4: β = −1.27e−3 → −1.22e−3 (|Δβ|/|β| = 4.4%), |t|<1.
- Cross-sector Spearman(sector-median θ_EAV, sector-median `inst_pct`) = **−0.006, p = 0.987**
  (n = 10). Sector and institutional ownership are empirically **independent at sector level**.
- Sector-adjusted residuals absorb above-ladder EM residuals by: IN 95.4%, MX 78.2%, BR 38.6%.

These pool-level statistics do not depend on individual-market pooled θ_EAV basin choice; they
survive the K1216c multistart audit. **K1207 verdict `SECTOR_ORTHOGONAL_CONFIRMED`** retained
as §5.2 primary. The K1222b modestly-weaker ladder coexists with K1207 as two orthogonal
cross-market channels (cross-sector ρ=−0.006 p=0.987; no multicollinearity).

**Figure**: K1207 adj-R² decomposition (promoted to §5.2 headline figure in K1222).

### §5.3 Cross-market institutional-ownership ordering — MODESTLY WEAKER but SURVIVING

The K1165 → K1171 canonical trajectory reported ρ = +0.75 → +0.61 → +0.44 → +0.39 → +0.42 (after
K1213 AU). K1222 retracted this to ρ = −0.07 as local-min artefact. K1222b reverses the
retraction on K1216c grounds: with identical 100-multistart applied to **all 9 fragile pools**
(4 DEV + 5 EM + AU = K1213), primary Spearman **rebounds** to ρ = +0.379, p = 0.201, N=13.

**(i) K1216c 9-market audit (commit `3cf6bc84`)**. Pathology is not EM-specific:

| Market | Canon θ_rel | Refined θ_rel (NM) | Canon LL | Refined LL | LR stat | HAC t | Verdict |
|---|---|---|---|---|---|---|---|
| US | 0.415 | **8.614** | 79291.63 | 80709.97 | **2836.68** | 5.21 | FRAGILE |
| EU | 0.196 | **1.434** | 83936.06 | 84355.05 | **837.97** | 2.96 | FRAGILE |
| JP | 1.668 | **4.706** | 75325.33 | 75443.12 | **235.57** | 3.41 | FRAGILE |
| TW | 0.314 | **1.364** | 95629.74 | 95923.63 | **587.78** | 1.94 | FRAGILE |

All 4 LR statistics exceed χ²(1) = 3.84 by 2–3 orders of magnitude. K1216c verdict:
`ROOT_CAUSE_METHODOLOGY` (9 / 9 FRAGILE).

**(ii) 9-market consistent Spearman rebuild**. Substituting all 9 markets' refined θ_rel (+ K1213
AU + K1172 canonical CA/HK/KR for 3 unaudited markets):

| Scenario | N | ρ | p | Harvey t | Status |
|---|---|---|---|---|---|
| K1172 baseline (all canonical) | 12 | +0.441 | 0.152 | +1.55 | **reference baseline** |
| K1216b 5-EM refined + AU (DEV canonical) | 13 | **−0.071** | **0.817** | **−0.24** | **artefact — asymmetric refinement** (footnote only) |
| **K1216c full 9-market refined + AU** | **13** | **+0.379** | **0.201** | **+1.36** | **FINAL** |

Canonical (+0.441 N=12) and refined (+0.379 N=13) are indistinguishable under Fisher z (p ≈ 0.87);
both moderately positive, both non-significant at 5%. K1216b −0.071 was the result of mixing
refined EM (BR 1.89→2.69, IN 1.17→3.08, MX 1.20→1.85, CH 0.30→1.47, ID 0.24→1.92) with canonical
DEV (US 0.42, EU 0.20, JP 1.67, TW 0.31). Moving DEV to refined basin (US 8.61, EU 1.43, JP 4.71,
TW 1.36) restores the rank concordance.

**(iii) Economic interpretation**. The institutional-ownership ladder's cross-market prediction
is **weak positive** at the global optimum. Canonical +0.441 slightly overstated the concordance;
−0.071 grossly understated it; honest estimate is ρ = +0.379, p = 0.20. **The ladder survives
in weakened form** at ≈86% of canonical magnitude.

**(iv) Pre-registration disclosure**. CA, HK, KR still carry K1172 canonical θ_rel in K1216c
Spearman. Given 9 / 9 audited markets FRAGILE, a future K1216d audit on CA/HK/KR is likely to
shift these upward; final ρ expected between +0.30 and +0.50.

**Figure**: `K1216c_9market_trajectory.png` — canonical +0.441 / asymmetric −0.071 /
symmetric +0.379. Key §5.3 / Table 5 visual.

### §5.4 NEW — Multistart methodology as additional Paper 2 contribution

K1213 + K1216 + K1216b + K1216c together establish that shared-MIDAS + stock-FE-GJR pooled-MLE
(K1168 / K1172 spec) has a **panel-wide two-basin likelihood surface**: 9 / 9 audited markets,
across both DEV and EM, hold default-init L-BFGS-B in the inferior basin-A. This is a
methodological contribution to cross-market systemic-volatility studies on small-S pools
(S ≤ 10 per market). §5.4 documents the protocol as standard.

**Protocol specification** (K1213 / K1216 / K1216b / K1216c identical):

1. 100 random L-BFGS-B multistarts per market; log-uniform on θ_EAV, θ_0 ∈ [1e-6, 5e-4].
2. Penalty-trap guard rejecting `res.fun > 1e11` or `−res.fun < 1000`.
3. K-means (K=2) basin identification on converged (θ_EAV, LL) pairs.
4. Best-LL across valid starts = L-BFGS-B global estimate.
5. Sensitivity polish: Nelder-Mead warm-start + differential_evolution check.
6. Refined best-LL = max over valid optimizers (NM consistently beats L-BFGS-B best).
7. LR test vs canonical: LR = 2·(LL_refined − LL_canonical) vs χ²(1) = 3.84.
8. Standard errors: Hessian on θ_EAV + HAC-robust sandwich (stock-level scores).
9. Cross-market rebuild: refit every market's θ_rel = θ_EAV_pooled / σ²_sample_mean.
10. Seed discipline: base=42; 100 start seeds 43..142; DE seed 49; K-means seed 42.

**9-market LR record** (verbatim):

| Market | Exp | Canon θ_rel | Refined θ_rel | LR stat | χ²(1)=3.84 × | Verdict |
|---|---|---|---|---|---|---|
| AU | K1213 | 0.150 | 1.476 (NM 1.070) | 198.9 (511.9 NM) | 51.8× (133×) | ABOVE_LADDER_OVERTURNED |
| BR | K1216 | 1.887 | 2.691 | 145.66 | 37.9× | FRAGILE |
| IN | K1216 | 1.170 | 3.077 | 410.76 | 107× | FRAGILE |
| MX | K1216 | 1.202 | 1.845 | 347.27 | 90× | FRAGILE |
| CH | K1216b | 0.304 | 1.469 | 597.94 | 156× | FRAGILE |
| ID | K1216b | 0.238 | 1.917 | 365.36 | 95× | FRAGILE |
| US | K1216c | 0.415 | 8.614 | 2836.68 | 739× | FRAGILE |
| EU | K1216c | 0.196 | 1.434 | 837.97 | 218× | FRAGILE |
| JP | K1216c | 1.668 | 4.706 | 235.57 | 61.3× | FRAGILE |
| TW | K1216c | 0.314 | 1.364 | 587.78 | 153× | FRAGILE |

All 10 markets reject the canonical estimate at p < 10⁻³⁰ under nested-LR. The 9 / 9 FRAGILE
pattern is a feature of the K1168 / K1172 joint pooled-MLE spec on small-S panels, not a market-
specific anomaly. The two-basin pathology is **invisible under default single-init L-BFGS-B**
(used by K1145 / K1147 / K1150 / K1153 / K1168 / K1172); the multistart diagnostic revealed it
only after 10 × 100 = 1000 fits.

**Figure**: 10-market basin-bimodality panel overlaying K1213 AU + K1216 BR/IN/MX + K1216b
CH/ID + K1216c US/EU/JP/TW histograms.

### §5.5 Narrative commitment — FINAL (K1222b)

> *The within-market analyst-attention mechanism is robust: Panel Harvey |t|(`log_analyst`) grows
> monotonically **3.236 → 3.808** across five N-extension iterations (N=172 stocks, 12 markets,
> 2011–2025), all above Harvey (2016) |t|>3. `institutions_pct` insignificant within market
> (|t|<1, β ≈ −1.25e−3 stable). GICS sector FE add incremental adjusted R² of **0.148 (≈ 32×**
> the inst-FE 0.0046), F = 689.5, p = 7.9 × 10⁻¹⁴ (K1207). Sector and inst ownership are
> independent at sector level (cross-sector ρ = −0.006, p = 0.987). EU panel full-coverage
> robustness (K1163) keeps EU low-cluster under N=30 (bootstrap t = 4.81, 95% CI θ_rel ∈
> [0.127, 0.277]).*
>
> *The cross-market institutional-ownership ladder is **modestly weaker but surviving** under
> panel-wide 100-multistart audit. Canonical trajectory ρ = +0.75 → +0.44 → +0.39 updates to
> **9-market consistent refined `ρ(institutions_pct_mean, θ_rel) = +0.379, p = 0.201, Harvey
> t = +1.36`** at N=13 (K1216c). Canonical +0.441 (K1172 N=12) and refined +0.379 are
> statistically indistinguishable under Fisher z (p ≈ 0.87); both moderately positive, both
> non-significant at 5%. The intermediate K1216b ρ = −0.071 was an **asymmetric-refinement
> artefact**: refining 5 EM pools to basin-B while leaving 4 DEV pools at default-init basin-A
> broke the rank concordance canonical +0.441 had. K1216c shows all 4 DEV pools are also FRAGILE
> (US LR=2837, EU 838, JP 236, TW 588); moving DEV to basin-B in parallel rebuilds concordance.*
>
> *As an additional methodological contribution, this paper establishes that cross-market
> pooled MLE on the shared-MIDAS + stock-FE-GJR specification requires **≥100 random
> initializations** to avoid secondary local minima. Default-init single-shot L-BFGS-B lands
> in inferior basin-A for every audited market (9 / 9 FRAGILE across AU + 5 EM + 4 DEV); NM
> polish further improves L-BFGS-B best in every case. §5.4 reports the protocol as a
> standalone methodological finding.*
>
> *Paper 2 §5 commits to **three** cross-market structural drivers — within-market analyst
> attention (primary, Harvey t > 3 × 5 iter), within-market GICS sector composition (primary,
> F = 689.5), and cross-market institutional ownership (modestly weaker but surviving,
> refined ρ = +0.379, p = 0.20, N=13) — plus **one** additional methodological contribution
> (multistart pooled-MLE diagnostic; §5.4). All future extensions on this spec must follow
> §5.4 protocol.*

## 4. Cherry-pick Instructions for Main Thread

1. **Treat K1222 as SUPERSEDED**. Revert any K1222 "WITHDRAWN" / "COLLAPSED" / "numerical
   artefact" language in `body_v(n).tex` if partially merged.
2. **§5.1**: retain K1215 Panel Harvey t 3.236→3.808 verbatim. Unchanged.
3. **§5.2**: retain K1207 promotion to §5.2 headline (same as K1222 plan).
4. **§5.3 MODESTLY WEAKER BUT SURVIVING**: replace K1222's RETRACTED language with §3 §5.3
   verbatim. Include 3-column Spearman Table 5 (canonical +0.441 / asymmetric −0.071 footnote /
   9-market refined +0.379 FINAL). Add Fisher-z indistinguishability note.
5. **§5.4 NEW methodology contribution**: promote from K1222 appendix to §5.4 additional Paper
   2 contribution. Use §3 §5.4 verbatim with 10-market LR record + 10-step protocol.
6. **§5.5 FINAL narrative**: replace K1222's two-drivers commitment with K1222b three-drivers +
   methodology commitment (§3 §5.5 verbatim).
7. **K1173 EM scale-factor**: defer to §6 robustness pending panel-wide K1216/K1216b/K1216c
   refined-input recomputation.
8. **K1163 EU**: retain as EU robustness footnote in §5.3.
9. **Table 5**: 3-column format (canonical / asymmetric footnote / 9-market FINAL).
10. **Figure 5A**: annotate K1216c N=13 ρ=+0.379 as FINAL; relegate K1216b −0.071 to methodology
    footnote.
11. **Figure 5G**: expand from 6 markets (K1222) to 10 markets (AU + 5 EM + 4 DEV).
12. **Reference**: cite K1216c commit `3cf6bc84` in §5.3 / §5.4.

### Machine-readable canonical inputs

- Primary Spearman FINAL: `experiments/k1216c/k1216c_results.json` field
  `spearman_variants.K1216c_FULL_9market_refined_plus_AU_N13`
  (ρ = 0.37912087912087916, p = 0.20140608996104342, Harvey t = 1.3588432170088491).
- Canonical baseline: `experiments/k1172/k1172_results.json` (ρ = +0.441 N=12).
- Panel-wide LR: K1213 + K1216_per_market_summary + K1216b_per_market_summary +
  K1216c_per_market_summary.
- K1207: `experiments/k1207/k1207_results.json`.
- K1163 EU: `experiments/k1163/`.

## 5. Provenance and rigour

All numbers verbatim from source JSONs — no re-estimation in K1222b. The 10 markets whose
multistart results are cited (AU / BR / IN / MX / CH / ID / US / EU / JP / TW) share identical
100-start protocol with seeds base=42, starts 43..142, DE seed 49, K-means seed 42 across
K1213 / K1216 / K1216b / K1216c. Shared-MIDAS + stock-FE-GJR spec and bounds identical to
K1168 / K1172 — no spec widening. Lookahead guard inherited from `_pooled_negll` (VIX²_{t−1},
EAV_{i,t−1}).

CA, HK, KR carry K1172 canonical θ_rel in K1216c; §5.3 discloses this. A future K1216d is
expected (given 9 / 9 FRAGILE) to shift these upward and move final ρ between +0.30 and +0.50.

Within-market Panel Harvey t is **invariant** to pooled-MLE basin across K1211 / K1215 / K1222 /
K1222b — the strongest Paper 2 §5 finding, independent of multistart controversy.

## 6. Supersession summary

- **K1211** (commit `9efffe4b`): §5 superseded; K1211 §5.6 sector survives as §5.2 primary.
- **K1215** (commit `45f621ee`): §5 superseded; AU reclass subsumed in §5.4 methodology.
- **K1222** (commit `75df1c8f`): **SUPERSEDED** by K1222b. K1222 "WITHDRAWN" framing based on
  K1216b asymmetric-refinement artefact; K1216c demonstrates framing was wrong; ladder is
  MODESTLY WEAKER BUT SURVIVING at ρ = +0.379.
- **K1222b (this document)**: active FINAL revision guide. Main-thread cherry-pick target.

### Table: K1222b Superseding Narrative Summary (4 versions)

| Version | §5 Headline | Primary ρ (N=13) | Ladder status | Methodology role | # drivers |
|---|---|---|---|---|---|
| K1211 | Ladder STRENGTHENED | +0.385 | active | n/a | 1 |
| K1215 | STRENGTHENED + AU | +0.418 | active | n/a | 1 |
| K1222 | Within + sector; WITHDRAWN | −0.071 | retracted (artefact) | appendix | 2 |
| **K1222b FINAL** | **Within + sector + modestly-weaker ladder + NEW methodology** | **+0.379** | **MODESTLY WEAKER but SURVIVING** | **ADDITIONAL contribution** | **3** |

---

Machine-readable canonical diff: `experiments/k1222b/k1222b_vs_k1222_diff.json`.
