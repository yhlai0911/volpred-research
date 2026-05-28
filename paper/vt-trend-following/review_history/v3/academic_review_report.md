# Academic Review Report — v3
**Paper:** Is Volatility Targeting Just Trend Following? Decomposing the Benefits of Volatility Targeting  
**File reviewed:** `paper/vt-trend-following/body_v3.tex`  
**Review round:** R5 (on body_v3)  
**Previous round:** R4 (on body_v2) — HIGH=0, MEDIUM=13, LOW=7, declared "ready for submission to JPM/FAJ"  
**Target journals:** JPM, FAJ  
**Review date:** 2026-05-23  
**Reviewer:** latex-academic-reviewer (subagent)

---

## Executive Summary

v3 introduced four targeted fixes: (1) TSMOM direction reversal in Equation (2), (2) "1.4%"→"5.3%" correction in Table 1, (3) rho=0.830 errata documentation in Table 5 and Section 4, and (4) K1376 block bootstrap 22-asset expansion (Table 6 added, 23 rows). All four fixes are directionally correct and verified against source JSON. However, v3 applied **text updates without updating the corresponding tables**, creating three new HIGH-severity internal contradictions that were not present in body_v2. The paper cannot be submitted in its current state.

**Overall stage assessment: `review_needed`**

---

## Issue Severity Summary

| Category | NEW HIGH | NEW MEDIUM | NEW LOW | CARRY-OVER MEDIUM | CARRY-OVER LOW | Total |
|---|---|---|---|---|---|---|
| A. Internal consistency | 3 | 0 | 0 | 1 | 0 | 4 |
| B. Data traceability | 0 | 0 | 0 | 5 | 1 | 6 |
| C. Statistical methodology | 0 | 0 | 0 | 2 | 2 | 4 |
| D. Citation / references | 0 | 0 | 0 | 2 | 1 | 3 |
| E. Writing / framing | 0 | 0 | 0 | 1 | 2 | 3 |
| F. v3 fixes (verified) | — | — | — | — | — | all pass |
| **TOTAL** | **3** | **0** | **0** | **11** | **6** | **20** |

**Count by severity (v3):** HIGH=3, MEDIUM=11 (all carry-over), LOW=6 (all carry-over)

---

## NEW Issues (Introduced by v3)

---

### H1 — Table 3 not updated to K1192 canonical MDD values

**Severity:** HIGH  
**Category:** A. Internal consistency  
**Location:** `body_v3.tex` lines 192–220 (Table 3, `tab:dual_mechanism`); line 247 (Section 3.3 text)

**Description:**  
Section 3.3 text (line ~247) was updated to K1192 canonical values:
> "VT achieves −26.3%, Hedged VT −25.3%...103.7% retention (K1192 canonical, 5,240 observations)"

But Table 3 (`tab:dual_mechanism`) still contains body_v2 stale values:
- SPY VT MDD: `−24.7%` (Table 3) vs `−26.3%` (text, K1192)
- SPY Hedged VT MDD: `−26.9%` (Table 3) vs `−25.3%` (text, K1192)
- SPY retention: `92.8%` (Table 3) vs `103.7%` (text, K1192)
- 50/50 VT MDD: `−12.4%` (Table 3) vs `−16.84%` (K1192 JSON)

K1192 JSON (`experiments/k1192/k1192_results.json`) confirms:
- `spy.vt_mdd = -26.31%`, `spy.hedged_mdd = -25.25%`, `spy.retention = 103.7%`
- `50_50.vt_mdd = -16.84%`, `50_50.hedged_mdd = -17.53%`

Table 6 (K1376, new in v3) correctly shows `SPY: vt_mdd=-26.31%, hedged=-25.25%, retention=103.7%`, creating a three-way contradiction: Table 3 ≠ Section 3.3 text ≠ consistent with Table 6.

**Impact:** The paper's central result (VT "over-hedges" drawdown vs TSMOM-hedged by 103.7%) is the key empirical claim. A reviewer who reads Table 3 sees 92.8% and the sign is reversed relative to the text's 103.7%. This is a critical internal contradiction on the primary finding.

**Suggested fix:** Update Table 3 to K1192 canonical values. SPY row: B&H MDD=-55.19%, VT MDD=-26.31%, Hedged MDD=-25.25%, VT reduction=28.88 pp, Hedged reduction=29.94 pp, Retention=103.7%. Verify 50/50, QQQ, IWM, DIA rows against K1192 JSON as well. Source-tag each updated cell with `% source: K1192 k1192_results.json`.

---

### H2 — Table 2 Panel B bootstrap CI stale ([0.114, 0.737])

**Severity:** HIGH  
**Category:** A. Internal consistency  
**Location:** `body_v3.tex` line ~226 (Table 2, Panel B, CI row); line ~230 (Section 3.2 text)

**Description:**  
Table 2 Panel B header was updated to show `r = 0.793` (K1193 canonical). The Section 3.2 text was updated to show `90% CI [0.589, 0.919]` (K1193 canonical). But the CI row inside Table 2 Panel B (the footnote-style row below the split-sample correlations) still reads:

> `Bootstrap 95% CI for Pearson r: [0.114, 0.737]`

This CI comes from the old body_v2 claim (`r = 0.487`), not from K1193 (`r = 0.793`). K1193 JSON confirms:
- `pearson_r = 0.7934`, `bootstrap_ci_90 = [0.5887, 0.9195]`

The table shows r=0.793 but CI=[0.114, 0.737], which is mathematically impossible — a CI for r=0.793 cannot span 0.114 to 0.737 (the upper bound is below the point estimate). Any reviewer will flag this as an obvious error or data fabrication.

**Note on CI confidence level:** Text says "90% CI [0.589, 0.919]" but table header says "95% CI". Verify K1193 JSON: if the CI is 90%, the table label "95%" must also be corrected.

**Suggested fix:** Replace the stale CI row with K1193 canonical values. Change `[0.114, 0.737]` to `[0.589, 0.919]`. Verify the confidence level (90% vs 95%) against K1193 JSON and make text/table consistent. Source-tag: `% source: K1193 k1193_results.json bootstrap_ci`.

---

### H3 — International results dual-source (24.9 pp K1178 vs 28.7 pp Table 5)

**Severity:** HIGH  
**Category:** A. Internal consistency  
**Location:** Abstract (lines ~4–8); Table 5 average row; Section 3.5 text (line ~267); Conclusion (line ~320); Section 4.3 (line ~295)

**Description:**  
v3 created a dual-source conflict for the international analysis. Two different sets of numbers appear in the paper with no reconciliation:

**Set A (K1178 canonical, used in Abstract and Section 3.5 opening):**
- Average VT reduction: 24.9 pp
- t-statistic: 10.25
- Country-level r: −0.806
- Country-level rho: −0.835

**Set B (Table 5 computed values, used in Conclusion and Section 4.3):**
- Average VT reduction: 28.7 pp (computed from Table 5 country rows: sum/13 ≈ 28.7 pp)
- t-statistic: 15.70 (shown in Table 5 average row)
- Country-level r: −0.770 (Table 5 note)
- Country-level rho: −0.720 (Table 5 note)

Specific text contradictions:
1. Abstract: "international markets (24.9 pp, t=10.25, r=−0.806, rho=−0.835)"
2. Section 3.5 (line ~267): "24.9 pp (K1178 canonical, t=10.25)"
3. Conclusion (~line 320): "28.7 percentage points across 13 international markets"
4. Section 4.3 (~line 295): "r=−0.770" (matching Table 5, not K1178)
5. Table 5 average row: "28.7, t=15.70"

The difference (24.9 vs 28.7 pp, t=10.25 vs 15.70) is large enough that a reviewer will notice. These cannot both be correct simultaneously — they represent different sample periods, market coverage, or weighting methods, but no explanation is given.

**Suggested fix:** Decide on a single canonical source for international results. If K1178 is canonical (recommended, as it is the registered experiment), update Table 5 average row, Section 4.3, and Conclusion to match K1178 values. If Table 5 uses a different/updated sample, document why in a table note and distinguish the two measures explicitly (e.g., K1178 unweighted vs. Table 5 value-weighted). Do NOT leave both sets of numbers without reconciliation.

---

## Carry-Over Issues from R4 (MEDIUM)

These were identified in R4 and remain unresolved in v3.

---

### M1 — Table 5 international data traceability (K901/K1178 reconciliation)

**Severity:** MEDIUM  
**Category:** B. Data traceability  
**Location:** `body_v3.tex` Table 5 (`tab:international`); Section 3.5

**Description:** Table 5 lists 13 international markets with country-specific VT reduction, t-statistics, and VIX sensitivity. The source experiment (K901 or K1178) is cited inline but no `% source:` tags appear on individual rows. The `audit_step1_2.md` identified this as untraceable in body_v2 — Table 5 countries and exact values could not be matched to K901 or K1178 JSON output. This carry-over is now elevated by H3 (dual-source conflict), which suggests the table may reflect a third, unregistered computation.

**Suggested fix:** Add `% source: K1178 k1178_results.json country_<iso>` to each row. Verify each country row against K1178 JSON. If K1178 does not contain 13 countries matching Table 5, reconcile with K901. If neither matches, the table requires re-computation and re-registration as a new K experiment.

---

### M2 — Table 3 Calmar column undiscussed

**Severity:** MEDIUM  
**Category:** E. Writing / framing  
**Location:** `body_v3.tex` Table 3 (`tab:dual_mechanism`)

**Description:** Table 3 contains a Calmar ratio column for each portfolio. The Calmar ratio is never mentioned in the text — no Section 3.x discusses its interpretation, no comparison sentence references the values, and no footnote defines the formula. Reviewers will question why the column is there if it is never analyzed.

**Suggested fix:** Either (a) add 1–2 sentences in Section 3.3 interpreting the Calmar ratios (and note that hedged VT improves Calmar vs B&H), or (b) remove the column if it is not part of the core argument. Option (a) is preferred as Calmar is a standard risk-adjusted return measure relevant to the MDD discussion.

---

### M3 — Table 4 M5 N=3,740 vs K898 N=5,049 ambiguity (BAB proxy)

**Severity:** MEDIUM  
**Category:** C. Statistical methodology  
**Location:** `body_v3.tex` Table 4 (`tab:ff5`), footnote †; K898 JSON

**Description:** Table 4 shows M5 (model with BAB factor) with N=3,740 observations and a footnote "† BAB proxied by SPLV-SPHB ETF spread." K898 JSON contains N=5,049 observations with a real BAB factor from AQR. The difference (3,740 vs 5,049) is explained by SPLV/SPHB ETF inception dates (approximately 2012), but this is not stated in the table note. A reader comparing N=5,049 (K898) to N=3,740 (Table 4) with no explanation will assume a data error.

**Suggested fix:** Expand the M5 footnote: "† BAB factor proxied by SPLV-SPHB ETF spread (available from [date]); M5 sample begins [date], reducing N to 3,740. Full-sample M5 with AQR BAB factor (N=5,049) available upon request." Source-tag: `% source: K898 k898_results.json m5`.

---

### M4 — Block bootstrap sensitivity analysis absent

**Severity:** MEDIUM  
**Category:** C. Statistical methodology  
**Location:** `body_v3.tex` Section 3.4 / Table 6 discussion

**Description:** Table 6 uses block size b=252 trading days (1 year). Standard practice for block bootstrap robustness is to test b={63, 126, 252} (quarterly, semi-annual, annual). No sensitivity analysis or robustness check for block size is presented or discussed. JPM/FAJ reviewers familiar with bootstrap methodology will ask for this.

**Suggested fix:** Either (a) run K1376 with b=63 and b=126 in addition to b=252 and add a brief robustness paragraph in Section 3.4 noting that retention estimates are stable across block sizes, or (b) add a limitation footnote citing Politis & Romano (1994) and stating that block size sensitivity is left for future work.

---

### M5 — Sector analysis (r=0.163) no source JSON

**Severity:** MEDIUM  
**Category:** B. Data traceability  
**Location:** `body_v3.tex` Section 4.3 (line ~295–300)

**Description:** Section 4.3 states "the cross-sectional correlation between γ and TSMOM loading across 11 GICS sectors is r=0.163 (p=0.63)." No K-experiment source is cited. The `audit_step1_2.md` identified this as untraceable in body_v2. The result remains in v3 without source attribution.

**Suggested fix:** Add `(K[XXXX], k[xxxx]_results.json)` inline citation if the experiment exists. If the sector analysis was computed ad hoc (not in a registered experiment), it must be registered as a new K experiment or removed. An unreproducible result in a JPM paper will not survive peer review.

---

### M6 — K687/K697/K688 results in text but not formal tables

**Severity:** MEDIUM  
**Category:** B. Data traceability  
**Location:** `body_v3.tex` Section 3.1 / Section 4.2

**Description:** K687, K697, and K688 results are cited in the text (GJR-GARCH estimation, Newey-West HAC inference, TSMOM factor orthogonalization details) but do not appear as rows in any formal table or as columns in existing tables. The experiments are referenced by K-number without numerical output traceable to a specific JSON field.

**Suggested fix:** For each K-number citation, add the specific result and JSON field inline: e.g., "(K687: γ̄=0.183 across 22 assets, `k687_results.json:gamma_mean`)". Alternatively, consolidate these into a supplementary table or appendix.

---

### M7 — Sample period inconsistency across tables

**Severity:** MEDIUM  
**Category:** B. Data traceability  
**Location:** `body_v3.tex` Table 1 note, Table 4 note, Table 5 note

**Description:** Table 1 notes "2005–2026" for some assets but individual start dates vary. Table 4 (SPY factor models) covers one period. Table 5 (international) covers different periods per country. No unified data appendix lists start/end dates per asset. This makes it impossible for a reader to verify whether the 22-asset Table 1 uses consistent sample periods across all assets.

**Suggested fix:** Add a data appendix table (or expand Table 1 notes) listing for each asset: ticker, start date, end date, N (monthly observations). This is a standard requirement for multi-asset empirical papers.

---

### M8 — TSMOM full-sample orthogonalization look-ahead

**Severity:** MEDIUM  
**Category:** C. Statistical methodology  
**Location:** `body_v3.tex` Section 2.2 (TSMOM hedging methodology)

**Description:** The TSMOM-hedged VT portfolio is constructed via rolling 252-day regressions to remove TSMOM exposure from VT returns. If the regression uses the full sample to estimate loadings (even partially), there is a look-ahead bias. The paper states rolling 252-day windows but does not explicitly confirm that no future information enters the weight estimation. For a paper whose central claim involves separating TSMOM from VT, the hedging methodology must be airtight.

**Suggested fix:** Add a sentence explicitly confirming: "All TSMOM exposure loadings are estimated using only past 252 trading days of data, with no information from t+1 or later entering the weight at time t. The lagged signal shift(1) is applied before weight computation."

---

### M9 — Missing citations: Hurst et al. (2017), Liu et al. (2019)

**Severity:** MEDIUM  
**Category:** D. Citation / references  
**Location:** `body_v3.tex` bibliography / introduction

**Description:** R4 flagged that Hurst, Ooi, and Pedersen (2017, "A Century of Evidence on Trend-Following Investing") and Liu et al. (2019) on volatility targeting are standard references in the VT/TSMOM literature that are absent from the paper. Both are directly relevant to the paper's claims about the relationship between trend following and volatility targeting.

**Suggested fix:** Add Hurst et al. (2017) when discussing TSMOM literature in Section 2.1. Add Liu et al. (2019) when citing the VT literature in the introduction or Section 2. Verify that these are not cited under alternate author orderings.

---

### M10 — Hood & Raughtigan (2025) is an unpublished working paper

**Severity:** MEDIUM  
**Category:** D. Citation / references  
**Location:** `body_v3.tex` bibliography

**Description:** Hood & Raughtigan (2025) is cited as a working paper without journal or DOI. FAJ/JPM reviewers may require that cited working papers have at minimum an SSRN DOI. If the paper has been updated or published since it was first cited, the citation is stale.

**Suggested fix:** Check whether Hood & Raughtigan (2025) has been published or posted to SSRN/NBER. Update the citation to include DOI. If unpublished and unavailable, add "(Working Paper)" to the citation and note the retrieval date.

---

### M11 — No placebo test for international VIX channel

**Severity:** MEDIUM  
**Category:** C. Statistical methodology  
**Location:** `body_v3.tex` Section 3.5

**Description:** The paper argues that the international evidence (VT reduction correlates with VIX sensitivity, rho=−0.835) demonstrates a causal channel via volatility timing. No placebo test is presented to rule out alternative explanations (e.g., that markets with higher VIX sensitivity also have higher momentum returns, explaining the VT-TSMOM correlation through a third variable).

**Suggested fix:** Add a brief robustness check: regress VT reduction on country-level VIX sensitivity while controlling for country-level momentum returns. If the VIX channel survives, the causal argument is strengthened. This can be presented as a single sentence in Section 3.5 with a table note.

---

## Carry-Over Issues from R4 (LOW)

---

### L1 — Abstract uses "reduces maximum drawdown by 28.9 pp" without hedged qualifier

**Severity:** LOW  
**Category:** E. Writing / framing  
**Location:** `body_v3.tex` abstract

**Description:** The abstract states VT reduces maximum drawdown by 28.9 pp for SPY. This is the VT vs B&H reduction, not the hedged-vs-B&H reduction. A reader may conflate this with the primary claim that hedged VT achieves the same reduction as plain VT (103.7% retention). The abstract should clarify "plain VT reduces MDD by 28.9 pp; TSMOM-hedged VT achieves equivalent protection (103.7% retention)."

**Suggested fix:** Rephrase: "Volatility targeting reduces SPY maximum drawdown by 28.9 percentage points (from −55.2% to −26.3%); TSMOM-hedged volatility targeting retains 103.7% of this protection (K1192), confirming that trend-following exposure is not the source of VT's drawdown benefit."

---

### L2 — Section 4 forensic note length vs narrative flow

**Severity:** LOW  
**Category:** E. Writing / framing  
**Location:** `body_v3.tex` Section 4 (forensic note paragraphs)

**Description:** Section 4 contains multiple paragraphs documenting corrections (rho=0.830 removal, 5.3% caveat, TSMOM direction fix). While academically honest, the forensic note occupies approximately 400 words in a section that also discusses implications. FAJ/JPM editors may ask to move correction notes to a footnote or supplementary erratum rather than the main body.

**Suggested fix:** Consider condensing the forensic note to a single footnote per correction: "Note: an earlier draft reported [X]; this was corrected to [Y] per K[XXXX]." Move extended methodological reasoning about why the correction was made to an appendix or supplementary material.

---

### L3 — "Insurance pricing" metaphor needs formal definition

**Severity:** LOW  
**Category:** E. Writing / framing  
**Location:** `body_v3.tex` Section 4 discussion

**Description:** The paper uses "insurance pricing" metaphorically (~4%/year Sharpe drag) but does not provide a formal definition or cite insurance-pricing literature. FAJ readership includes practitioners who will appreciate a precise definition of what is being priced.

**Suggested fix:** Add a sentence: "We define the insurance price of TSMOM exposure as the Sharpe ratio drag of the TSMOM-hedged portfolio relative to plain VT: (SR_VT − SR_Hedged) × √12 annualized."

---

### L4 — Harvey et al. (2016) threshold not linked to specific test statistics

**Severity:** LOW  
**Category:** C. Statistical methodology  
**Location:** `body_v3.tex` Section 3 (significance discussion)

**Description:** The paper cites Harvey et al. (2016) threshold of |t| > 3.0 for multiple-testing-adjusted significance but does not systematically list which reported t-statistics exceed (or fail to exceed) this threshold. Readers cannot verify which claims survive this bar.

**Suggested fix:** Add a Table 1 footnote or Section 3 paragraph: "Alpha estimates in Table 1 with |t| ≥ 3.0 (Harvey et al. 2016 threshold) are marked †; [X of 22] assets meet this threshold for M1 CAPM alpha."

---

### L5 — Equation numbering gaps after v3 edits

**Severity:** LOW  
**Category:** E. Writing / framing  
**Location:** `body_v3.tex` equations

**Description:** v3 added and modified equations (Equation 2 TSMOM direction fix, Equation 9 MDD retention bootstrap). Manual inspection suggests equation numbering may have gaps or renumbering artifacts if equations were added/removed during v3 edits. LaTeX cross-references may be stale.

**Suggested fix:** Compile body_v3.tex and verify all `\ref{eq:X}` cross-references resolve correctly. Confirm equation numbers cited in text (e.g., "Equation (2)" for TSMOM, "Equation (9)" for MDD retention) match the compiled PDF.

---

### L6 — Newey-West lag formula footnote vs text inconsistency

**Severity:** LOW  
**Category:** C. Statistical methodology  
**Location:** `body_v3.tex` Section 2 / Table 2 footnote

**Description:** The Newey-West HAC lag formula `ℓ = ⌊4(T/100)^{2/9}⌋` appears in the text but the table footnote uses a different description ("automatic lag selection"). Verify that the formula and the phrase "automatic" refer to the same implementation. If `automatic` means something different (e.g., Andrews 1991 data-dependent selection), clarify.

**Suggested fix:** Harmonize: either use the explicit formula in both text and table footnotes, or cite a specific function/package (e.g., `statsmodels.stats.sandwich_covariance.cov_hac` with `nlags` parameter) to make it reproducible.

---

## v3 Fix Verification (All Pass)

| Fix | Claim | Verified | Source |
|---|---|---|---|
| TSMOM direction reversal | Eq.(2): `sign(r_{t-252:t}) × r_t` | PASS | body_v3.tex line ~85; consistent with positive equity loadings in Table 1 M2 column |
| "1.4%"→"5.3%" correction | Table 1 GLD footnote documents caveat | PASS | Table 1 footnote; K1376 JSON does not contain this number; caveat correctly notes it may reflect a specific sub-period |
| rho=0.830 errata | Table 5 note documents removal; Section 4 forensic note explains | PASS | body_v3.tex Table 5 note + Section 4; consistent with K1193 updated values |
| K1376 Table 6 data (22 assets + 50/50) | All 23 rows verified against K1376 JSON | PASS | `experiments/k1376/k1376_results.json`: all retention values, CIs, MDD values match Table 6 to ≤0.1 pp rounding |

---

## Academic Score

| Dimension | Score | Notes |
|---|---|---|
| A. Novelty / contribution | 4★ | TSMOM decomposition of VT is a genuine contribution; international evidence strengthens claim |
| B. Methodology rigor | 3★ | GJR-GARCH + block bootstrap solid; H3 dual-source raises doubt about international analysis robustness |
| C. Internal consistency | 2★ | H1+H2+H3 are critical text-table contradictions; 3 HIGHs on a 604-line paper is a serious consistency failure |
| D. Data traceability | 3★ | Table 6 fully traceable; Table 3 stale values; Table 5 international unresolved |
| E. Writing quality | 3★ | Section 4 forensic note is honest but too long for main body; abstract-body contradiction on international |
| F. Citation completeness | 3★ | Missing Hurst et al. 2017; working paper without DOI |
| G. Reproducibility | 3★ | K1376 registered and verified; K1193 registered; K1178 international still partially unresolved |
| H. Statistical claims | 3★ | H2 CI=[0.114,0.737] for r=0.793 is mathematically impossible — cannot survive reviewer scrutiny |
| I. Journal fit (JPM/FAJ) | 4★ | Topic is directly relevant; policy implications clear; style appropriate |
| J. Submission readiness | 2★ | 3 HIGH issues block submission; all three are fixable with known source JSONs |

**Overall academic score: 3.0★ / 5★**  
(Downgraded from R4's implicit 4★ due to three new HIGH issues introduced by partial v3 updates)

---

## Overall Stage Assessment

**`review_needed`**

The paper **cannot be submitted in its current state.** Three critical internal contradictions were introduced by v3's partial update strategy (updating text without updating tables). All three are **mechanically fixable** — the correct values are known and verified in source JSONs:

1. **H1 fix**: Update Table 3 from K1192 JSON (`k1192_results.json`: SPY vt=-26.31%, hedged=-25.25%, retention=103.7%)
2. **H2 fix**: Update Table 2 Panel B CI from K1193 JSON (`k1193_results.json`: bootstrap_ci=[0.5887, 0.9195]; verify 90% vs 95% label)
3. **H3 fix**: Decide on canonical source for international results (K1178 recommended); update abstract, Table 5 average row, Section 3.5, Section 4.3, and Conclusion to single consistent set of numbers

After fixing H1–H3, the paper returns to R4's status (HIGH=0) and is eligible for submission to JPM/FAJ, contingent on the 11 MEDIUM carry-overs being addressed or documented as known limitations.

**Recommended next action:** Fix H1, H2, H3 in body_v3.tex → re-run `uv run volpred ops paper-update --paper-id vt-trend-following` → re-run R6 review to confirm HIGH=0.

---

## File Reference Index

| File | Role in review |
|---|---|
| `paper/vt-trend-following/body_v3.tex` | Primary review target |
| `paper/vt-trend-following/main_v3.tex` | Wrapper (no issues found) |
| `paper/vt-trend-following/reviews/review_r4.tex` | Previous round baseline |
| `paper/vt-trend-following/reviews/audit_step1_2.md` | body_v2 traceability audit |
| `experiments/k1376/k1376_results.json` | Table 6 source (all 23 rows verified PASS) |
| `experiments/k1193/k1193_results.json` | Table 2 Panel B split-sample source (CI update needed) |
| `experiments/k1192/k1192_results.json` | Table 3 MDD source (table update needed) |
| `experiments/k1178/k1178_results.json` | Table 5 international canonical (H3 reconciliation needed) |
