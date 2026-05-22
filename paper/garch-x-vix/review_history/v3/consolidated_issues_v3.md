# Consolidated Issues — Paper 9 (garch-x-vix) v3

**Date**: 2026-05-19
**Sources integrated**: v2 Codex adversarial review + v3 LaTeX academic review + v3 citation review
**Purpose**: Single priority-sorted master list for R1 revision planning

---

## Cross-Review Issue Mapping

| # | Issue | Source | Severity | Linked to v2 Adversarial? |
|---|-------|--------|----------|--------------------------|
| C1 | COVID subperiod analysis missing | v2-Ch4 + LaTeX-HIGH2 | **CRITICAL → PASS (K1393)** | v2 SERIOUS FLAW #1 |
| C2 | Main claim overstatement: "unnecessary" vs "indistinguishable" | v2-Ch3 | **CRITICAL** | v2 SERIOUS FLAW #2 |
| C3 | Spec genealogy / multiple testing (White RC or SPA) | v2-Ch7 | **CRITICAL** | v2 SERIOUS FLAW #3 |
| C4 | HAR-RV benchmark missing | v2-Ch6 | **HIGH** | v2 SIGNIFICANT |
| C5 | Source decomposition: A4f free-ω vs Proposition 2 constrained | v2-Ch5 + LaTeX-HIGH1 | **HIGH** | v2 SIGNIFICANT + LaTeX |
| C6 | Harvey (2016) citation context mismatch (cross-section vs time-series) | Citation-MED-V3-1 | **MEDIUM** | v2-Ch7 corroborates |
| C7 | VRP tautology: mechanical component not quantified | v2-Ch1 | **MEDIUM** | v2 SIGNIFICANT |
| C8 | Cross-asset multiple testing without FDR/Bonferroni | v2-Ch8 | **MEDIUM** | v2 MODERATE-SIGNIFICANT |
| C9 | Refit frequency sensitivity (21/42/63/126 day) | v2-Ch9 + LaTeX (MEDIUM-5 related) | **MEDIUM** | v2 MODERATE |
| C10 | "Contemporaneous normalization" / simultaneity terminology | v2-Ch10 + LaTeX | **LOW-MEDIUM** | v2 MODERATE |
| C11 | A4f vs A4 best-model fragility (block-bootstrap CI) | v2-Ch2 | **LOW-MEDIUM** | v2 SIGNIFICANT |
| C12 | GLD DM t inconsistency (3.17 vs 3.39 across abstract/intro) | LaTeX-LOW7 | **LOW** | — |
| C13 | Proposition 3 lacks formal econometric status | LaTeX-MEDIUM4 | **LOW** | — |
| C14 | Table 3 does not show A4f VRP correlation | LaTeX-LOW5 | **LOW** | — |
| C15 | xeCJK/PingFang TC breaks external compilation | LaTeX-LOW1 | **LOW** | — |
| C16 | Acerbi (2014) Risk magazine → (2019) Management Science upgrade | Citation-LOW-V3-3 | **LOW** | — |
| C17 | Proposition 1 is an algebraic identity, not a proposition | LaTeX-LOW8 | **LOW** | — |

---

## TOP-5 MOST URGENT FIXES (pre-submission critical path)

### RANK 1 — COVID Subperiod Analysis (C1) — **RESOLVED 2026-05-22 (K1393)**

**Status**: ✅ PASS — K1393 leave-COVID-out DM test confirms A4f advantage is NOT COVID-driven.

**K1393 results** (K988-faithful spec, OOS 2019-01-01 to 2026-04-07):

| Subperiod | n | DM t | Harvey-sig |
|-----------|---|------|------------|
| Full OOS | 1825 | +3.60 | ✓ |
| Non-COVID (excl 2020-02-01–06-30) | 1721 | **+4.26** | **✓ C1 PASS** |
| Pre-COVID (2019) | 273 | +2.52 | ✗ |
| COVID window (2020-02–06) | 104 | +1.48 | ✗ |
| Post-COVID (2021–2026-04) | 1448 | +3.76 | ✓ |

**Key finding**: Non-COVID DM t=+4.26 is Harvey-significant (|t|>3.0). COVID window t=+1.48 not sig — advantage comes from **normal market conditions**, not crisis volatility spikes.

**Paper action required**:
1. Add robustness table (Table A1 or Table 5 expansion) showing subperiod DM results
2. Narrative: "The VIX-augmented model advantage is not an artifact of the COVID-19 crisis episode. Excluding the 2020-02 to 2020-06 window (n=104), the non-COVID DM t-statistic is +4.26, remaining Harvey-significant at |t|>3.0."
3. ~~Compute K_NEW_A~~ → completed as K1393

**Why top priority**: The entire 2019-2026 OOS period is heavily influenced by the COVID-19 shock (VIX peak = 82.69). Without leave-COVID-out analysis, any VIX-driven model trivially wins on crisis episodes. The paper acknowledges the 7-period 2-year window analysis in prose (lines 714-716) but provides no table. This is the most likely reason a referee at JEF/JoF will reject in R1.

**Connection to v2**: v2 SERIOUS FLAW #1; also corroborated by LaTeX-HIGH2 (missing table for the existing 7-period claim)

---

### RANK 2 — Reframe Main Claim (C2)

**Why second**: The abstract and conclusion use language like "GARCH-MIDAS complexity is unnecessary" despite the MCS showing A4f is statistically indistinguishable from B1 (best MIDAS, K=22). This is the type of overstatement that triggers automatic reject-with-major-revision at top journals.

**Required actions**:
1. Change "GARCH-MIDAS is unnecessary" → "A4f is a parsimonious alternative statistically indistinguishable from best MIDAS"
2. Move MCS result to the main findings list (currently buried in Section 5.3)
3. Rewrite abstract's second-to-last sentence of findings

**Scope of edit**: Abstract (line 51), introduction Finding 4 (line 433-434), conclusion (line 852-853). No new experiments needed — reframe existing evidence.

---

### RANK 3 — Spec Genealogy / White RC or SPA (C3)

**Why third**: 17 specs post-hoc ranked by QLIKE, then the winner's DM test is reported. Without documenting which specs were pre-specified by theory vs. post-hoc, and without a formal multiple-testing correction beyond Bonferroni, the identification credibility of A4f's win is undermined. Harvey (2016) threshold helps but is not designed for this setting.

**Required actions**:
1. Add Appendix B documenting spec genealogy: which specs are ex-ante theory-driven (A4 = dimensional consistency; A2 = GARCH-MIDAS convention; B0 = benchmark) vs. ex-post ranked (A4f vs A4 only by free intercept)
2. Run White's Reality Check or Hansen SPA on the 17-spec horse race (K_NEW_D in v2 suggestions)
3. Add `white2000` citation alongside `harvey2016` throughout (Citation MEDIUM-V3-1)

---

### RANK 4 — HAR-RV Benchmark (C4)

**Why fourth**: In the volatility forecasting literature, a horse race without HAR-RV is incomplete. Referees at JFEC, JEF, or Journal of Forecasting will immediately flag this as a selective benchmark set.

**Required actions**:
1. Run K_NEW_C: HAR-RV and HAR-RV-VIX vs A4f DM test (same OOS protocol: 2019-2026, W=2000, 63-day refit)
2. Add HAR-RV (B-1) and HAR-RV-VIX (B-2) rows to Table 2, ranked appropriately
3. If A4f significantly outperforms HAR-RV: adds substantially to contribution. If A4f does not (likely): report as honest limitation and note it in conclusion.

---

### RANK 5 — Source Decomposition Coherence (C5)

**Why fifth**: Propositions 1-3 derive structural interpretation for the constrained model (E[g_t]=1), but the recommended model is A4f (free ω_g, E[g_t]=0.48). This creates a 1.5-page theoretical section that formally proves properties of a model the paper ultimately does not recommend. A referee will point this out as an internal contradiction.

**Required actions**:
1. Add clarifying sentence to Proposition 2: "The following VRP identification applies to the constrained model (A4). For the free-omega model A4f, VRP correction is distributed across two channels (θ_1 and E[g_t])."
2. Add A4f's VRP Spearman correlation to Table 3 (currently missing)
3. Consider restructuring Section 6 to explicitly discuss constrained vs. free model interpretability trade-off

---

## Medium-Priority Fixes (should address before R1 response)

### C6 — Harvey (2016) citation context

Add `white2000` to bibliography; update line 297 to cite both. 1-line bib addition + 1-sentence revision.

### C7 — VRP tautology quantification

Add simulation-based quantification of the mechanical component of the ρ=0.80 correlation. Fixes v2-Ch1. Requires K_NEW_E (new computation).

### C8 — Cross-asset multiple testing

Add Bonferroni footnote to Table 4: "With 6 additional assets, Bonferroni-adjusted threshold is |t| > 3.22; SPY, QQQ, STOXX50E, FEZ remain significant."

### C9 — Refit sensitivity

Already partially addressed in Table 5 (rows 1-4: 21/63/126/252 days) but the COVID-period interaction with refit frequency (v2-Ch9) is not reported. Add footnote or Appendix table.

### C10 — Contemporaneous normalization terminology

Change "contemporaneous normalization avoids a simultaneity issue" → "contemporaneous normalization reflects an information-timing choice" (2-sentence edit in Section 3.1.2).

---

## Low-Priority Fixes (address in final polish before submission)

| ID | Fix | Effort |
|----|-----|--------|
| C11 | Block-bootstrap CI for A4f vs A4 QLIKE difference | Small computation + footnote |
| C12 | GLD DM t: align abstract (3.17) with intro (3.39) — verify which is correct | 1-line edit |
| C13 | Rename Proposition 3 → Remark 3 | 2-word edit |
| C14 | Add A4f VRP correlation to Table 3 | 1-row table addition |
| C15 | Remove xeCJK/PingFang TC from submission draft | 2-line deletion |
| C16 | Upgrade Acerbi (2014) → (2019) Management Science | 1 bib entry |
| C17 | Reframe Proposition 1 as empirical result | 2-sentence rewrite |

---

## New Experiments Required (compute queue)

| ID | Description | Urgency | Estimated K |
|----|-------------|---------|-------------|
| K_NEW_A | Leave-COVID-out DM test (2019+2021-2026) | ~~CRITICAL~~ **DONE** | K1393 (2026-05-22) |
| K_NEW_B | HAR-RV + HAR-RV-VIX horse race | HIGH | K_next+1 |
| K_NEW_C | White's Reality Check / SPA on 17-spec horse race | HIGH | K_next+2 |
| K_NEW_D | COVID-period refit sensitivity interaction (refit freq × crisis dates) | MEDIUM | K_next+3 |
| K_NEW_E | VRP mechanical component simulation (fix τ_t, draw g_t i.i.d.) | MEDIUM | K_next+4 |

---

## Version Progression Summary

| Version | Type | Verdict | Key Outcome |
|---------|------|---------|-------------|
| v1 (2026-04-13) | LaTeX + Citation review | Needs revision | 1 MAJOR bib error (fixed), 5 MEDIUM DOIs (fixed) |
| v2 (2026-05-19) | Codex adversarial review | 3 SERIOUS FLAWS | COVID dominance, MCS overstatement, spec genealogy |
| v3 (2026-05-19) | LaTeX academic + Citation | 3 HIGH, 10 MEDIUM, 8 LOW (new) | Structural contradiction in Propositions, Harvey citation context, missing COVID table |

**Current paper status**: Under significant revision required. The 3 SERIOUS FLAWs from v2 + 2 HIGH from v3 are independent issues, all of which require substantive changes before top-tier submission. Estimated revision scope: 3-5 new experiments + 2-4 weeks of writing/revision.

**Stage recommendation**: Move from `review` → `revision_required`. Do not submit until at minimum C1 (COVID analysis) and C2 (claim reframing) are resolved.
