# LaTeX Academic Review — v5 (body_v3.tex)
# Paper: vt-trend-following
# Date: 2026-06-10
# Reviewer: Claude Sonnet 4.6 (main-thread foreground, latex-academic-reviewer skill)

---

## Audit Dimensions (per SKILL.md)

| Dimension | Status | Key Findings |
|-----------|--------|--------------|
| A. Logic structure | PASS | Dual-channel framework logically coherent end-to-end |
| B. Research motivation | PASS | Insurance vs. repackaged-TF tension clearly framed |
| C. Literature review | PARTIAL | Key citations added; Hood(2025) differentiation prose still vague |
| D. Research gap & contribution | PASS with caveat | N=22 cross-sectional scope flagged; contributions fairly bounded |
| E. Model specification | PARTIAL | GJR-GARCH identification OK; MDD retention definition Eq.8 internally ambiguous |
| F. Equations & derivation | HIGH ISSUE | Eq.8 as referenced in body vs. Table 3 footnote description do not fully match denominator logic |
| G. Methodology | MEDIUM ISSUE | H2: stationary-bootstrap narrative vs. actual CI data inconsistency |
| H. Data & sample | PASS | Yahoo Finance, CBOE, FF5, BAB sources complete; lag structure explicit |
| I. Expected results | PASS | Claims proportionate to evidence; negative results reported |
| J. Citation format | PARTIAL | See citation_check_v1.md; minor issues |

**Overall Academic Score: 3.5★/5** (was ~3★ pre-v4 fixes; ceiling blocked by H1-mechanism and H2-numerical reporting gaps detailed below)

---

## A. Issue-by-Issue Audit (v4 Issues)

### H1 — MDD Mechanical Artifact (Gemini v4 HIGH)

**v4 requirement**: Decompose daily PureVT returns around MDD troughs (2009-03, 2020-03). Show whether MDD improvement comes from real VIX timing or from short-TSMOM hedge profiting during V-shaped rebounds.

**What body_v3 actually does**:
- Line 247 (Section 3.3): "We interpret this as non-erosion of the drawdown channel, not as proof of a separate dominant insurance technology, **because some enhancement can arise when the hedge reduces exposure during rebound windows inside momentum-crash episodes** [daniel2016]."
- Line 300 (Table 3 footnotes): "Point estimates ≥100% indicate TSMOM hedging does not degrade MDD protection; some incremental improvement can arise mechanically if the hedge trims exposure during rebound windows inside momentum-crash episodes."
- Line 490 (Section 4.1): Same language repeated, citing daniel2016.
- Line 8 (Abstract): "Point estimates above 100% should be interpreted cautiously: they indicate that hedging does not damage the drawdown channel, but part of the incremental improvement can arise mechanically when the hedge trims exposure during momentum-crash rebound windows."

**Gap Assessment**: The paper now verbally acknowledges the mechanism and cites Daniel & Moskowitz (2016) appropriately. However, **Gemini's required fix was a quantitative decomposition** — "decompose the daily returns of PureVT around the MDD troughs (e.g., March 2009, March 2020). Show whether the MDD improvement in PureVT comes from actual VIX timing or simply from profiting off the short-TSMOM hedge during market rebounds."

**No such decomposition exists in the paper.** There is no table or figure showing PureVT daily return decomposition around trough dates. The fix is **verbal acknowledgment only**, not the empirical decomposition Gemini required.

**Verdict**: **PARTIAL closure** — narrative caveat addresses the concern at the language level, but the empirical decomposition that would definitively answer whether MDD retention is real vs. mechanical is absent. For a JPM submission this is likely **still HIGH severity** because a referee can legitimately ask "you say it can arise mechanically — but does it in your data?"

**Required for v6**: Add Section 3.x with daily return decomposition around 2009-03 and 2020-03 troughs. If full decomposition is not feasible, at minimum report: (a) the number of days around each trough where TSMOM was negative (i.e., where hedging mechanically added positive returns), and (b) the cumulative PureVT return advantage from those specific windows vs. all other windows.

---

### H2 — Block Bootstrap Destroys Long-Memory (Gemini v4 HIGH)

**v4 requirement**: Use stationary bootstrap with expected block size 3-5 years OR report absolute MDD differences rather than retention ratio.

**What body_v3 actually does**:
- Line 131 (Section 2.6): "we also check the main inference with a stationary bootstrap using multi-year expected block lengths (K1417 task audit); that longer-memory resampling does not materially weaken the qualitative conclusion"
- Line 253 (Section 3.3): "The stationary-bootstrap re-check does not reverse any of the five canonical non-erosion conclusions (K1417 task audit), so the main claim does not depend on the 252-day resampling choice."
- Abstract: "A 252-day moving-block bootstrap and a stationary-bootstrap robustness check both support non-erosion of the drawdown channel...no qualitative weakening under longer-memory resampling (K1417 task audit)."

**The K1417 experiment results** (from `experiments/k1417/k1417_results.json`):
- SPY: fixed-252 CI lo=86, stationary-756 CI lo=97.1, stationary-1260 CI lo=97.7 → **lo shift = +11.7pp**
- 50/50: fixed-252 CI lo=90, stationary-756 CI lo=84.7, stationary-1260 CI lo=89.8 → **lo shift = -0.2pp (slightly lower!)**
- DIA: fixed-252 CI lo=83, stationary-1260 CI lo=93.4 → **+10.4pp**
- QQQ: fixed-252 CI lo=82, stationary-1260 CI lo=97.5 → **+15.5pp**
- IWM: fixed-252 CI lo=91, stationary-1260 CI lo=100.0 → **+9.0pp**
- K1417 verdict: "H2 NOT SUPPORTED — CI shift below 3pp on majority of assets; retention robust to bootstrap block length"

**Critical inconsistency**: The paper's Abstract (line 8) says the moving-block bootstrap CI lower bounds are "76–93%" for the five-asset canonical table. Looking at Table 3 (K1376 data), the five-asset canonical lower bounds are: SPY=93.0%, 50/50=76.0%, DIA=82.7%, QQQ=89.0%, IWM=86.7%. So the "76–93%" refers to K1376 moving-block results.

Meanwhile K1417 stationary-bootstrap lower bounds (3-year/5-year blocks) are: SPY=97.7%, 50/50=89.8%, DIA=93.4%, QQQ=97.5%, IWM=100.0% — meaning the stationary bootstrap actually **tightens the lower bounds upward** (not downward as Gemini predicted). This is the favorable result that "H2 is not supported."

**The paper never reports K1417's actual CI numbers in-text.** The body simply states "no qualitative weakening" with a parenthetical "(K1417 task audit)" reference but gives no numerical comparison. For a referee evaluating whether H2 is adequately addressed, the complete CI comparison table (fixed-252 vs. stationary-756 vs. stationary-1260) should appear in a table, not be buried in an experiment reference.

**Verdict**: **PARTIAL closure** — K1417 exists and was run correctly. The result actually favors the paper (stationary bootstrap narrows bounds upward). But the paper only cites it narratively without presenting the comparative CI table. Referees cannot evaluate this claim without the table.

**Required for v6**: Add K1417 comparative table (either as Table 4 or Online Appendix Table A1). Report all five assets × three block sizes with CI lo/hi. This would strongly strengthen the paper because the result is favorable.

---

### M1 — Regime Shift / Safe-Haven Dummy (Gemini v4 MEDIUM)

**v4 requirement**: Add a "Risk Asset vs. Safe Haven" dummy control in the cross-sectional regression. If γ coefficient loses significance after this control, the leverage effect is a proxy for asset class.

**What body_v3 actually does**:
- Lines 32–33 (Introduction, Contribution 1): "we interpret the increase conservatively because it partly reflects a 2017–2026 regime shift in which international and safe-haven loadings flipped from near-zero to positive."
- Line 206–208 (Section 3.2): Full paragraph discussing regime shift limitation; notes the "split-sample approach reduces but does not fully eliminate the mechanical channel."
- Limitations (line 528): "A formal instrumental variable approach—instrumenting γ with a variable that affects the leverage effect but not VT's TSMOM loading through other channels—would provide stronger identification, but suitable instruments are not readily available."

**Gap Assessment**: The paper extensively discusses the regime-shift concern and conservatively interprets the split-sample result. However, **Gemini's required fix was to add the "Risk Asset vs. Safe Haven" dummy as a control variable in the cross-sectional regression and report whether γ retains significance**. No such regression with a dummy control appears in the paper. Adding this is a one-line addition to Table 2 (the cross-sectional table): report γ coefficient and t-stat after controlling for an "equity vs. non-equity" dummy (or a more refined safe-haven dummy including GLD, TLT, VNQ).

**Verdict**: **PARTIAL closure** — The concern is acknowledged and discussed at length, but the specific quantitative control variable test was not run. Given N=22, this test is trivial to implement and would either (a) show γ retains significance → strengthen the paper, or (b) show γ loses significance → require reframing contribution 1.

**Required for v6**: Add Panel C to Table 2 with cross-sectional regression controlling for equity-vs-non-equity dummy. Report γ coefficient, t-stat, R², and dummy coefficient. If γ remains significant, this conclusively addresses M1. Two-line addition.

---

### M2 — Insurance Premium vs. VRP Confound (Gemini v4 MEDIUM)

**v4 requirement**: Clarify distinction — is Sharpe drag (a) insurance cost for drawdown protection, or (b) opportunity cost of not harvesting VRP? Different welfare implications.

**What body_v3 actually does**:
- Line 36 (Introduction): "We interpret this pricing channel cautiously: VIX likely bundles expected volatility, variance risk premium, and downside-protection demand rather than isolating a single structural primitive [bollerslev2009, bondarenko2019]."
- Line 519 (Section 4.3): "We do not, however, interpret this as evidence that VT is loading on a pure expected-volatility state variable. VIX embeds the variance risk premium [bollerslev2009] and investor demand for downside protection [bondarenko2019], so the observed premium is better read as a reduced-form price of protection than as a single-factor structural estimate."

**Gap Assessment**: The paper adds the two citations (bollerslev2009, bondarenko2019) and explicitly states that the 4%/year drag is "a reduced-form price of protection" rather than a pure structural estimate. However, the paper does not:
1. Explicitly label the two competing interpretations (insurance premium vs. VRP opportunity cost)
2. Discuss the welfare implications of each interpretation
3. Suggest an empirical test to separate them

The current language is appropriately cautious but does not fully "clarify the distinction" as Gemini required. A JPM referee focused on VRP would still note this gap.

**Verdict**: **PARTIAL closure** — Citations added, cautionary language added. But the explicit two-paragraph discussion distinguishing "insurance premium vs. VRP opportunity cost" as competing hypotheses with different welfare implications is absent.

**Required for v6**: Add a two-paragraph subsection in Section 4.3 explicitly contrasting the two interpretations: (1) Under the insurance interpretation, investors rationally sacrifice VRP to buy drawdown protection per Campbell-Cochrane habit utility; (2) Under the VRP-cost interpretation, the strategy mechanically underweights equities when VRP is highest, and the "premium" is just foregone VRP compensation. Note that these interpretations yield different target clients (highly risk-averse institutional vs. retail seeking risk-adjusted efficiency) and different implications for optimal VT timing (insurance → always hedge; VRP-cost → hedge only when VRP exceeds threshold).

---

### Missing Citations — Status

| Citation | Added? | Location | Correctness |
|----------|--------|----------|-------------|
| Bollerslev, Tauchen & Zhou (2009) | YES | Lines 36, 519 (bibliography line 560–561) | See citation_check_v1.md |
| Campbell & Cochrane (1999) | YES | Line 30 (bibliography line 569–570) | See citation_check_v1.md |
| Bondarenko & Bernardo (2019) | YES | Lines 36, 519 (bibliography line 563–564) | See citation_check_v1.md |
| Politis & Romano (1994) | YES | Bibliography line 617–618; Section 2.6 (stationary bootstrap) | See citation_check_v1.md |

All four missing citations are now present. Bibliographic accuracy checked in citation_check_v1.md.

---

## B. New Residual Issues (v5 Findings)

### NEW-H1 (v5, HIGH) — Abstract CI Range "76–93%" Inconsistent with Text Claims

**Location**: Abstract (line 8)

**Issue**: Abstract states "90% CI lower bounds of 76–93% in the five-asset canonical table." This refers to K1376 moving-block bootstrap (Table 3 confirms: SPY=93%, 50/50=76%, DIA=82.7%, QQQ=89%, IWM=86.7%). But the abstract also says "no qualitative weakening under longer-memory resampling (K1417 task audit)" — implying the K1417 stationary bootstrap gives similar or worse bounds. In fact, K1417 stationary-bootstrap lower bounds are **higher** (SPY=97.7%, 50/50=89.8%, DIA=93.4%, QQQ=97.5%, IWM=100.0%). The narrative "no qualitative weakening" is correct but understates: K1417 actually shows **tightening** (improvement). A reader seeing "76–93%" in the abstract and "no weakening" from stationary bootstrap will infer the stationary bootstrap gives similar numbers, not substantially higher ones.

**Severity**: HIGH — the abstract is the paper's most-read paragraph; the CI description misleads readers about the robustness of the main finding.

**Fix**: Update abstract to correctly describe K1417 result: e.g., "A stationary-bootstrap robustness check with 3- and 5-year expected block lengths yields lower bounds of 90–100%, confirming that the non-erosion conclusion is robust to or strengthened by longer-memory resampling."

---

### NEW-M1 (v5, MEDIUM) — Calmar Ratio for TSMOM-Hedged 50/50 Anomaly

**Location**: Table 2 (tab:dual_mechanism), line 321

**Issue**: TSMOM-Hedged VT for 50/50 reports Calmar=0.501, while VT has Calmar=0.624 — a 20% drop. For SPY, the Calmar drops only negligibly (0.283 → 0.281). The large Calmar drop for the 50/50 blend is inconsistent with the "95.6% MDD retention" claim: if hedged MDD is -17.5% vs. VT MDD of -16.8%, the absolute MDD difference is small (0.7pp), which should produce minimal Calmar deterioration. The Calmar drop from 0.624 to 0.501 is much larger than 0.7pp MDD difference would suggest — either the annualized return of TSMOM-Hedged VT is substantially lower, or there is a computational inconsistency.

**Severity**: MEDIUM — does not invalidate the main claim but is internally inconsistent and would trigger a referee query.

**Fix**: Verify K1192 computation for 50/50 Calmar ratio. If annualized return is substantially reduced (≥2% drag), explain this in the table footnote. If computational error, correct.

---

### NEW-MINOR-1 (v5, MINOR) — Hood & Raughtigan (2025) Citation Incomplete

**Location**: Bibliography line 596–597

**Issue**: "Hood, M., \& Raughtigan, J. (2025). Volatility targeting alpha is trend following alpha. *Working Paper*. Retrieved May 2025." This citation lacks any URL, SSRN ID, or institutional affiliation. For a working paper that is central to the paper's contribution differentiation, referees will want to locate it. If it's on SSRN, add the SSRN link.

**Fix**: Check SSRN/Google Scholar for "Hood Raughtigan 2025 volatility targeting trend following" and add URL/SSRN number to bibliography.

---

### NEW-MINOR-2 (v5, MINOR) — K898 Forensic Caveat Still Unresolved

**Location**: Lines 34, 251, 484 (multiple mentions)

**Issue**: The paper repeatedly mentions "K898 back-calculated estimate is approximately 5.3% of total strategy Sharpe, subject to ongoing forensic reconciliation against the originally reported 1.4% figure." This "ongoing reconciliation" caveat has appeared in at least v2 and v3 of the paper and is still unresolved. By v6/submission, either (a) resolve the discrepancy and report the canonical figure, or (b) remove the original 1.4% figure and only report 5.3% with source, or (c) explicitly close the forensic note with "original 1.4% figure cannot be reproduced; 5.3% is the canonical value forward."

**Fix**: Close the forensic note before submission. It signals to reviewers that the authors are unsure of their own numbers.

---

### NEW-MINOR-3 (v5, MINOR) — Equity Sector Sample Start Date

**Location**: Line 52 (data section) and line 399

**Issue**: The sector sample is stated as "December 1998 to March 2026" in the data section (line 52) but Section 3.4 discusses sector results without stating this earlier start date explicitly. The primary sample starts 2005 but sector starts 1998 — this creates a longer sector sample that could produce stronger sector results. The paper mentions the boundary condition finding ($r = 0.163$, NS) without noting that the sector sample period is different from the 22-asset primary sample period. Add a note clarifying that the sector-sample period difference (1998 vs. 2005) does not bias the gamma-TSMOM cross-sectional comparison because gamma and TSMOM loadings are estimated over the full respective periods.

---

## C. Previously Unaddressed Suggestions from v4

| v4 Suggestion | Addressed? |
|---------------|------------|
| "Utility exhibit" for who benefits (γ≥10 CRRA) | YES — K688 CRRA crossover discussed in Section 4.1 |
| Hood(2025) differentiation clarity | PARTIAL — scope clarification paragraph added but relies on "per-asset TSMOM vs. diversified CTA" which referee could query further |

---

## D. Paper Structural Assessment

**Strengths (v3 improvements)**:
1. Abstract now correctly frames the dual-channel separation upfront (lines 8–17)
2. >100% retention footnotes now consistent across abstract, text, and table (no longer claiming these values as proof of superiority)
3. Forensic notes on v3 revisions (Section 4 discussion) demonstrate intellectual honesty
4. Limitations section is comprehensive and specific

**Structural gaps remaining**:
1. No comparative CI table for K1417 (stationary) vs. K1376 (fixed-252) — this is the most straightforward fix and yields favorable results
2. No quantitative decomposition for H1 mechanism
3. No regression-with-dummy for M1 control
4. Section 3.6 "Sub-Period Stability" defers all detailed results to "Online Appendix" — for JPM submission this is acceptable but main paper should at minimum include a 2×2 table summary

---

**Academic Rating Summary**:
- Logic structure: ★★★★☆ (4/5 — solid, minor gaps in M1 causal chain)
- Literature: ★★★★☆ (4/5 — new citations land well)
- Methodology: ★★★☆☆ (3/5 — H2 numerical gap, H1 empirical decomposition absent)
- Results reporting: ★★★★☆ (4/5 — tables complete, forensic honesty good)
- Discussion: ★★★★☆ (4/5 — M2 still under-developed)
- **Overall: 3.5★/5**

For JPM submission: currently **Major Revision** (two residual HIGH-severity items + 3 MEDIUM). Fixing NEW-H1 (abstract CI correction) and H2 (add K1417 table) is low effort and would push to Minor Revision. H1 empirical decomposition and M1 dummy regression are medium effort.
