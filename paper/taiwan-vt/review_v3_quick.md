# Paper 2 Taiwan VT v3 -- Quick Review

**Reviewer:** Claude (automated academic review)
**Date:** 2026-04-03
**Scope:** New Section 5 (section5_hf_draft.tex) integration with existing body_v2.tex and main_v2.tex
**Target:** FRL -> JBF upgrade

---

## HIGH Severity Issues

### H1. Rolling window inconsistency: 500 vs. 2000 days

**Location:** section5_hf_draft.tex line 73 vs. body_v2.tex line 86

Section 2 (Data and Methodology) states:

> "All GARCH and GJR-GARCH models are estimated using a rolling window of w = 2000 trading days"

Section 5 states:

> "GJR-GARCH and EWMA forecasts are computed using the same specifications as in Section 4, with rolling 500-day estimation windows"

These directly contradict each other. Section 5 claims to use "the same specifications as in Section 4" but then specifies w=500, which is 4x smaller than the w=2000 used everywhere else. This is not a minor discrepancy -- the paper explicitly cites Hwang & Valls Pereira (2006) to justify w=2000 and warns that "windows below 500 induce substantial persistence bias." Using exactly w=500 in the HF section therefore contradicts the paper's own methodological argument.

**Fix:** Either (a) re-run Section 5 GARCH with w=2000 for consistency, or (b) explicitly justify the shorter window (e.g., "Due to the shorter TAIFEX sample [2,163 days], we use w=500 to preserve a sufficient OOS evaluation period") and acknowledge the persistence bias implication.

### H2. Abstract/Introduction claims unsupported by Section 5

**Location:** main_v2.tex line 35, body_v2.tex lines 18 and 501

The abstract states:

> "73.7% of daily returns and 61% of overnight gap variance are captured by TAIFEX night session futures (R^2 = 0.83), with night volatility share rising from 24% (2017) to 57% (2026)"

The "night volatility share rising from 24% to 57%" IS supported by Table 6 (tab:night_share) in Section 5. However, the specific claims about **"73.7% of daily returns"** and **"61% of overnight gap variance (R^2 = 0.83)"** do NOT appear anywhere in section5_hf_draft.tex. These numbers are asserted in the abstract, introduction (line 18), and conclusion (line 501) but have no corresponding table, regression, or discussion in the body.

This is a critical gap for a JBF submission -- every number in the abstract must be traceable to a specific analysis in the paper. A referee will immediately flag this.

**Fix:** Add a subsection to Section 5 (e.g., 5.5 "Night Session Return Capture") that presents the regression of 0050.TW close-to-close returns on TAIFEX night session returns, reports the 73.7% / 61% / R^2=0.83 statistics, and includes the relevant table. Alternatively, if these numbers come from a different experiment not yet integrated, add them now or remove the claims from the abstract.

### H3. Section 7 VaR recommends skewed Student-t; Section 5 VaR uses Cornish-Fisher

**Location:** body_v2.tex lines 396-402 vs. section5_hf_draft.tex lines 184-216

Section 7 (VaR and Risk Management) explicitly concludes:

> "For practical purposes, we recommend the skewed Student-t approach for Taiwan VaR, which is both theoretically principled and computationally stable."

Section 7 also documents that Cornish-Fisher diverges with w=2000 for 0050.TW due to extreme kurtosis values.

Yet Section 5's VaR paradox analysis (Table 5) uses GJR+Cornish-Fisher as the best-performing method (2 violations, Trinity PASS), and Section 5.6 reports RealGARCH-Log+CF as the model that resolves the paradox. The paper never reconciles why CF works well in Section 5 but diverges in Section 7.

The likely explanation is the shorter window (w=500 in Section 5 vs. w=2000 in Section 7) and the different sample period (2023-2024 vs. 2020-2026), but this must be stated explicitly. Otherwise a referee will ask: "You recommend against CF in Section 7 but crown it the winner in Section 5 -- which is it?"

**Fix:** Add a paragraph in Section 5.5 or 5.6 noting that CF performs well here because (a) the shorter evaluation period avoids the extreme kurtosis episodes, and/or (b) the 500-day GARCH window produces more stable kurtosis estimates. Cross-reference Section 7's recommendation.

---

## MEDIUM Severity Issues

### M1. Section 4 "GARCH ceiling" narrative vs. Section 5 resolution needs a transition paragraph

**Location:** body_v2.tex line 252 (Section 4 footnote about K472) -> section5_hf_draft.tex line 8

Section 4 establishes the "GARCH ceiling": all enhancements (HAR-RV, semivariance, kurtosis signals) fail to beat GJR-GARCH for 0050.TW when evaluated against r^2. Section 5 then explains this as a "proxy ceiling" rather than a model ceiling. The narrative arc is actually well-constructed, but the transition is abrupt.

Currently, Section 4 ends with conditional leverage (Section 4.4), then Section 5 immediately opens with "The preceding sections evaluate volatility models using daily squared returns..." There is no bridging paragraph at the end of Section 4 that motivates why HF data is needed.

**Fix:** Add 2-3 sentences at the end of Section 4 (before `\input{section5_hf_draft}`): "The preceding analysis raises a natural question: is GJR-GARCH's apparent sufficiency a genuine property of Taiwan's volatility dynamics, or an artifact of the noisy daily r^2 proxy? We address this in the next section by exploiting high-frequency TAIFEX futures data."

### M2. GJR+CF violation count discrepancy across tables

**Location:** section5_hf_draft.tex Table 5 (tab:var_paradox) vs. Table 7 (tab:realgarch)

- Table 5 (Prediction-VaR Paradox): GJR+CF = **2**/481 violations (0.42%), Trinity PASS
- Table 7 (Realized GARCH): GJR-GARCH+CF = **3**/481 violations (0.62%), Trinity PASS

Both tables claim N=481 and period 2023-2024, but the violation counts differ (2 vs. 3). If these are the same model on the same data, the numbers must match. If the specifications differ (e.g., different refitting schedule or window), this must be noted.

**Fix:** Verify the underlying data. If both are identical GJR+CF on the same sample, one table has an error. If they differ in specification, add a footnote explaining the difference.

### M3. Cross-OOS wins column potentially misleading

**Location:** section5_hf_draft.tex Table 3 (tab:har_comparison)

HAR-RV shows 2/5 wins on Track A and 3/5 on Track B, while the text says "HAR-RV (or HAR-RV-J) wins every fold on both tracks." The parenthetical "(or HAR-RV-J)" is doing heavy lifting -- HAR-RV-J gets 3/5 on Track A, so the combined "HAR family" wins 5/5, but HAR-RV alone does not win every fold.

**Fix:** Rephrase to: "The HAR family (HAR-RV or HAR-RV-J) wins every fold on both tracks" or report the combined wins more clearly.

### M4. Section numbering comment in body_v2.tex

**Location:** body_v2.tex line 331

The comment says `% --- Section 6: Macroeconomic Indicators (renumbered)` but the actual LaTeX `\section` command will auto-number. This is fine for compilation, but the old comment suggests this was previously Section 5. Verify that all cross-references (e.g., "Section 6" in the introduction's road map) are using `\ref{}` rather than hard-coded numbers.

The introduction (line 22) correctly uses:

> "Section~\ref{sec:hf} presents high-frequency volatility evidence..."
> "Section~\ref{sec:macro} explores macroeconomic indicators..."

This is properly done with labels, so auto-renumbering will work. No action needed beyond cleaning up the comment.

### M5. HAR-RV Track A note: QLIKE improvement percentage seems inverted

**Location:** section5_hf_draft.tex line 105

The text states:

> "the HAR-RV advantage is *larger* on Track B (46% QLIKE improvement) than on Track A (66% improvement...)"

But 66% > 46%, so the advantage is numerically *larger* on Track A, not Track B. The parenthetical acknowledges this ("but Track B's lower baseline QLIKE reflects the more complete RV target"), but the topic sentence is confusing. A referee may read "larger on Track B" and immediately object.

**Fix:** Rephrase: "While the absolute QLIKE improvement is larger on Track A (66% vs. 46%), Track B's lower baseline QLIKE reflects the more informative RV target. In relative terms, HAR-RV's advantage is even more pronounced when night-session information is included."

---

## LOW Severity Issues

### L1. Bibliography entries are complete

All four new citations required by Section 5 are present in main_v2.tex:
- `\bibitem[Hansen and Lunde(2005)]{hansen2005}` -- line 143
- `\bibitem[Hansen et~al.(2012)]{hansen2012}` -- line 152
- `\bibitem[Barndorff-Nielsen and Shephard(2004)]{barndorff2004}` -- line 146
- `\bibitem[Andersen et~al.(2007)]{andersen2007}` -- line 149

No issues found.

### L2. No label conflicts

All 18 labels in section5_hf_draft.tex (sec:hf, sec:hf_rv, eq:rv, eq:bpv, tab:rv_stats, sec:hf_har, eq:har, tab:har_comparison, sec:hf_proxy, tab:proxy_ratio, sec:hf_night, tab:night_share, sec:hf_paradox, tab:var_paradox, sec:hf_realgarch, eq:realgarch_simple, eq:realgarch_log, tab:realgarch) are unique and do not conflict with any labels in body_v2.tex.

### L3. Minor: "Limitations" paragraph title inconsistency

Section 5.6 uses `\paragraph{Limitations and practical considerations.}` while other sections use `\paragraph{...}` without trailing periods. Minor style inconsistency.

### L4. Table numbering will shift

With Section 5 inserted, all tables in Sections 6-9 and the Appendix will be renumbered. Any hardcoded table references (rather than `\ref{}`) would break. A quick grep confirms all cross-references use `\ref{}`, so this is handled correctly. Just flagging for awareness during proof review.

### L5. Corsi (2009) cited in both Section 4 footnote and Section 5

Section 4 footnote (line 252) references "HAR-RV (Corsi, 2009)" as having been tested and failed for 0050.TW. Section 5 then shows HAR-RV crushes GJR-GARCH. The difference is the evaluation target (r^2 vs. RV), which is exactly the paper's "proxy ceiling" argument. This is actually well-handled narratively, but a very careful referee might flag the apparent contradiction. Consider adding a forward reference in the Section 4 footnote: "...fail to improve out-of-sample QLIKE for 0050.TW when evaluated against daily r^2 (see Section 5 for the resolution via high-frequency data)."

---

## Summary

| Severity | Count | Key Issue |
|----------|-------|-----------|
| HIGH | 3 | Window mismatch (500 vs 2000), unsupported abstract claims (73.7%/61%/R^2=0.83), CF recommendation contradiction |
| MEDIUM | 5 | Missing transition paragraph, violation count discrepancy, cross-OOS phrasing, comment cleanup, QLIKE improvement phrasing |
| LOW | 5 | Bib OK, labels OK, minor style, table renumbering, forward reference suggestion |

**Overall assessment:** The new Section 5 is a substantial and well-structured contribution (proxy ceiling + prediction-VaR paradox + Realized GARCH resolution). The narrative arc from Section 4's "GARCH ceiling" to Section 5's "proxy ceiling" explanation is the paper's strongest upgrade for JBF. However, the three HIGH issues must be resolved before submission: the w=500/2000 contradiction will be caught by any econometrics referee, the unsupported abstract numbers are a red flag for data integrity, and the CF recommendation inconsistency between sections creates confusion about practical guidance.
