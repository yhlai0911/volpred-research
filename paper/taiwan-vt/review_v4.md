# Paper 2 Taiwan VT — Review v4

**Reviewer:** Claude (automated review)
**Date:** 2026-05-13
**Reviewed file:** body_v3.tex (593 lines) + main_v3.tex (151 lines)
**Target journal:** JBF

---

## Status of Previous Issues (v3 quick review, 2026-04-03)

### H1 Rolling window (500 vs 2000 days): RESOLVED

body_v3.tex has **removed the entire Section 5 high-frequency draft** (section5_hf_draft.tex). The body now contains no reference to `w = 500`. The only rolling-window specification is in Section 2.3 (line 84): "rolling window of `w = 2000` trading days… robust to `w = 504` and `w = 1000`." This is internally consistent throughout the document. No contradiction found.

**Note:** The HF Section (RealGARCH, HAR-RV, proxy ceiling narrative, RV-based evaluation) has been entirely dropped from body_v3. The GARCH ceiling discussion is now relegated to a footnote (K472 experiment note, line 250). Whether this constitutes a scientific regression relative to body_v2 + section5_hf_draft is a substantive research question outside the scope of this review, but editors at JBF may ask why high-frequency data is not exploited given TAIFEX's active futures market.

---

### H2 Abstract unsupported numbers (73.7% / 61% / R²=0.83): RESOLVED

All three numbers have been **completely removed** from both the abstract (main_v3.tex lines 34–38) and the Introduction. The new abstract makes no reference to TAIFEX night session futures regression statistics. The "night volatility share rising from 24% to 57%" claim is also absent. No unsupported numerical claims were found.

---

### H3 CF vs skewed-t conflict: RESOLVED (with caveat)

The conflict has been structurally resolved by removing the Section 5 material that showed CF as the "winner" in VaR paradox analysis. The remaining text is now **internally consistent**: Section 6.3 (Skewed Student-t for Taiwan, line 389–391) shows skewed-t wins 6/6, CF wins 5/6 across the cross-asset panel, and Section 6.4 (Cornish-Fisher Divergence, lines 393–395) explains that CF diverges with `w = 2000` for 0050.TW due to extreme kurtosis, recommending skewed-t. No contradiction remains in the current body_v3.

**Caveat:** The cross-asset panel result (Section 6.3: "CF achieves 5/6, failing for QQQ due to excessive conservatism") introduces a new mild tension — CF is recommended against for Taiwan but is near-best on the cross-asset panel. A single bridging sentence noting that 0050.TW's long-window kurtosis pathology is specific to its return distribution would preempt referee questions.

---

### M1 Section 4→5 transition: OPEN (substantially changed context)

The Section 5 (HF data) has been removed entirely; the paper now flows from Section 4 (VT Strategies) directly to Section 5 (Macroeconomic Indicators). There is no bridging paragraph at the end of Section 4. The current transition (line 324 comment: "Section 5: Macroeconomic Indicators (renumbered from Section 6)") is abrupt: Section 4 ends with the conditional leverage discussion and immediately jumps to macroeconomic indicators. A brief motivating sentence at the end of Section 4 would improve readability.

More importantly, the Section 5 opening paragraph (line 329) contains a **structural inconsistency**: it begins "While our three core contributions focus on leverage amplification, VT strategies, and **time-zone arbitrage**…" but the time-zone analysis is now in the Appendix. Calling appendix material a "core contribution" in the Macroeconomics section introduction is misleading and inconsistent with the paper's stated structure.

---

### M2 GJR+CF violation count: RESOLVED

With the removal of Section 5 (section5_hf_draft.tex), all tables involving GJR+CF violation counts across the RealGARCH analysis are gone. The only violation count now is: GJR+Student-t(5) VaR = 8 violations / 1,501 days = 0.5% (Section 6.2, line 385). This is cited consistently in the Introduction (line 16) and Conclusion. No discrepancy found.

---

## New HIGH Severity Issues

### NEW-H1: 8.63/VIX Sharpe Ratio 4-way Inconsistency Across Tables and Text

**Severity: HIGH** — multiple contradictory values for the same strategy within the same paper.

The 8.63/VIX monthly rebalancing strategy (2016–2026 full period) is reported with **four different Sharpe ratios** across the paper:

| Location | Period | Sharpe |
|----------|--------|--------|
| Table 3 (tab:vt_results, line 264) | 2016–2026 | **1.137** |
| Section 4.3 text (line 308) | 2016–2026 | **0.690** |
| Section 7.1 Currency Risk (line 418) | unspecified | **0.69** |
| Table 5 (tab:sharpe_reconciliation, line 483) | 2016–2026 | **0.690** (citing tab:vt_results) |

Table 3 shows Sharpe = **1.137** for 8.63/VIX in 2016–2026. The Sharpe Reconciliation table (Table 5) shows **0.690** for the same strategy over the same period, and explicitly cites Table 3 as the source (`Table~\ref{tab:vt_results}`). This is a direct self-contradiction: the reconciliation table points to Table 3 but reports a different number than what is in Table 3.

**Root cause hypothesis:** The 1.137 in Table 3 appears to reflect daily rebalancing (the table note says "all strategies use daily rebalancing"), while 0.690 is the monthly rebalancing version — but the table label explicitly says "8.63/VIX (monthly)". The note at the bottom then corrects "8.63/VIX uses monthly rebalancing" as an exception. This internal confusion in Table 3's note (contradiction between "all strategies use daily rebalancing" and "8.63/VIX uses monthly rebalancing") is likely the root cause of the conflicting numbers.

**JBF exposure:** A referee will immediately notice that Table 3 shows Sharpe 1.137 but the paper's reconciliation table shows 0.690 for the same strategy/period and cites Table 3 as the source. This will be characterized as a data integrity problem.

**Fix required:** Determine the correct Sharpe for 8.63/VIX (2016–2026, monthly rebalancing, lagged, full transaction costs). Update Table 3 (or the reconciliation table) to show the same number. The Table 3 footnote must also resolve whether "all strategies daily" applies or not to 8.63/VIX.

---

### NEW-H2: GJR VT Sharpe Increment Inconsistency (+0.114 vs +0.124) and GJR VT Sharpe (1.074 vs 1.084)

**Severity: HIGH** — multiple contradictory values for the same result.

The GJR-GARCH vs GARCH VT Sharpe increment is stated inconsistently:

| Location | GJR Sharpe | GARCH Sharpe | Increment |
|----------|-----------|-------------|-----------|
| Introduction (line 16) | — | — | **+0.114** |
| Section 4.2 text (line 245) | 1.074 | 0.950 | **+0.124** |
| Conclusion (line 503) | — | — | **+0.114** |
| Table 3 (tab:vt_results, line 263) | **1.074** | 0.950 | = 0.124 |
| Table 4 (tab:vt_common, line 286) | **1.084** | 0.950 | = 0.134 |

The arithmetic in Section 4.2 is correct (1.074 − 0.950 = 0.124), but the Introduction and Conclusion both state "+0.114." Furthermore, Table 4 (common period, also 2020–2026) shows GJR VT Sharpe = 1.084, while Table 3 and Section 4.2 text use 1.074 — these two tables cover the same 2020–2026 period but report different GJR VT Sharpe ratios.

The inconsistency is a data provenance problem: Table 3 sources GJR VT from an earlier replication (implied by context), while Table 4 sources it from K900. The footnote in Table 4 says "GJR VT sourced from K900 (n=1,512)" but Table 3 note says "GJR VT covers 2020-01-03 to 2026-03-30 (n=1,511)." The 1-day difference in n may explain 1.074 vs 1.084.

**JBF exposure:** A referee comparing Introduction to Table 3 will see +0.114 ≠ +0.124. A referee comparing Table 3 to Table 4 will see GJR VT = 1.074 vs 1.084 over the same stated period.

**Fix required:** Choose one canonical GJR VT Sharpe, verify which K-experiment produces it, and propagate consistently through Introduction text, Section 4.2 text, Tables 3 and 4, and Conclusion.

---

### NEW-H3: 8.63/VIX MDD Inconsistency (-13.7% vs -15.3%)

**Severity: HIGH**

| Location | Period | MDD |
|----------|--------|-----|
| Table 3 (tab:vt_results, line 264) | 2016–2026 | **-13.7%** |
| Section 4.3 text (line 308) | 2016–2026 | **-15.3%** |
| Table 4 (tab:vt_common, line 287) | 2020–2026 | -13.7% |

Table 3 and the same-period text in Section 4.3 disagree on MDD by 1.6 percentage points. Table 4 over the shorter 2020–2026 period also shows -13.7%. Since MDD is path-dependent, a longer sample (2016–2026) should generally show a larger MDD than the sub-period (2020–2026). The Table 3 figure of -13.7% for 2016–2026 being equal to the 2020–2026 MDD is arithmetically suspicious — the 2016–2019 period includes drawdown episodes that should increase the cumulative MDD. The -15.3% in Section 4.3 text is likely the correct 2016–2026 figure.

**Fix required:** Verify the correct MDD for 8.63/VIX over 2016–2026 against K-experiment data, and reconcile Table 3 with the Section 4.3 narrative.

---

## New MEDIUM Severity Issues

### NEW-M1: Section 5 Opening Paragraph Internal Inconsistency

**Location:** body_v3.tex line 329

The opening sentence of Section 5 reads: "While our three core contributions focus on leverage amplification, VT strategies, and **time-zone arbitrage**…"

The time-zone analysis has been demoted to Appendix A (not a numbered section), and the Introduction (line 19) correctly describes it as supplementary evidence presented in an appendix. Describing it as a "core contribution" in Section 5 contradicts the paper's own framing. This is a copyediting artifact that will confuse readers about what the paper's core contributions are.

**Fix:** Replace "time-zone arbitrage" with the correct third core topic (VaR/risk management, or macroeconomic indicators, depending on what the authors claim as their third contribution).

---

### NEW-M2: Table 3 Footnote Self-Contradiction on Rebalancing Frequency

**Location:** body_v3.tex lines 269–270

The Table 3 footnote simultaneously states:
1. "All strategies use daily rebalancing" 
2. "8.63/VIX uses monthly rebalancing"

These two statements directly contradict each other. The table row label also says "8.63/VIX (monthly)." Given that Sharpe = 1.137 for 8.63/VIX — a figure that is inconsistent with the 0.690 reported elsewhere for monthly rebalancing — the most likely explanation is that the 1.137 is a daily-rebalancing figure that was mistakenly not updated when the footnote was added. This is both the root cause of NEW-H1 above and independently confusing.

**Fix:** Clarify which rebalancing assumption produced Sharpe = 1.137. If it is daily, state so explicitly. If it is monthly, update to 0.690 (consistent with Section 4.3 and tab:sharpe_reconciliation).

---

### NEW-M3: TSMC γ Inconsistency Within Body (0.052 vs 0.124)

**Location:** lines 151 (Table 2) vs line 452 (footnote)

Table 2 (tab:gamma) reports TSMC γ = **0.052** (t = 3.98, full-sample MLE, K892). The TSMC Concentration Robustness footnote (Section 8.4, line 452) states: "the full-sample GJR-GARCH MLE (K892) yields TSMC γ = 0.052 (t = 3.98)." So far consistent. However, the same footnote says the sub-period concentration analysis shows "0050.TW index exhibits a GJR-GARCH leverage parameter of γ = **0.124** (t = 2.46)." This 0050.TW γ = 0.124 in the sub-period is larger than the full-sample 0.097 in Table 2. While this is noted as a sub-period analysis, the footnote does not state which sub-period is used, making the result non-reproducible. A referee may ask why the shorter window yields a different 0050.TW γ.

**Fix (LOW priority):** Add the sub-period dates to the footnote. Note this as a sensitivity result, not a new finding.

---

### NEW-M4: DM Test Statistic Sign Convention

**Location:** body_v3.tex line 243

Section 4.2 reports: "The Diebold-Mariano test yields t = −0.17 (p = 0.86), with a QLIKE improvement of only −0.20%."

The negative sign on both t and QLIKE improvement requires consistent interpretation. QLIKE is a loss function (lower = better), so a "QLIKE improvement of −0.20%" means GJR has lower (better) QLIKE than GARCH by 0.20%. However, a t-statistic of −0.17 with a two-sided p = 0.86 is consistent with the null not being rejected. The sign convention should be explicitly stated: is a negative DM t-statistic favorable or unfavorable for GJR? Without a stated convention, readers cannot determine whether −0.17 means GJR is slightly better or slightly worse.

Separately, line 16 says "GJR-GARCH does not significantly improve QLIKE over standard GARCH (Diebold-Mariano p = 0.86)", consistent with the body. But also on line 243, it says SPY has "DM t = −6.27, improvement −3.8%". A DM t = −6.27 is highly significant (|t| >> 2), contradicting "does not improve" framing. If the convention is "negative t = improvement favoring GJR", then t = −6.27 means GJR strongly improves on GARCH for SPY, which is stated correctly. Clarify the sign convention once in Section 2.4.

---

### NEW-M5: ES Violation Rate vs VaR Trinity — Internal Tension Unexplained

**Location:** body_v3.tex lines 403–407

Section 6.5 (ES Backtesting) reports: "GJR VT and EWMA VT achieve VaR trinity PASS at α = 1% (violation rates 1.46% and 1.66%, respectively)." However, Section 6.2 (lines 385–387) reports: "GJR-GARCH + Student-t(5) VaR produces 8 violations (0.5%)" and "EWMA + Student-t(5) combination performs comparably, with 8 violations (0.5%)."

There is a direct contradiction: Section 6.2 shows 0.5% violation rates for both models, while Section 6.5 shows 1.46% and 1.66% violation rates. These cannot both be correct for the same strategies over comparable periods. The likely explanation is different evaluation periods or different specifications (model-level K896 vs strategy-level K900), but this is not stated. A referee will ask: "Did the VT strategies pass VaR at 0.5% (Section 6.2) or 1.46%/1.66% (Section 6.5)?"

**Fix (HIGH-adjacent):** Explicitly disambiguate: Section 6.2 likely reports model-level VaR (GJR-GARCH on raw returns, K896 period 2008–2026), while Section 6.5 reports strategy-level VaR (the portfolio after VT scaling, K900 period 2020–2026). This distinction must be stated clearly, and the two subsections should cross-reference each other.

---

## New LOW Severity Issues

### NEW-L1: Section 7 Road Map Inconsistency

The Introduction (line 19) says: "Section~\ref{sec:hf} presents high-frequency volatility evidence…" but `\label{sec:hf}` does not exist in body_v3.tex. The section-to-label mapping has changed: the old `sec:hf` from section5_hf_draft.tex was removed. If `\ref{sec:hf}` appears in main_v3.tex or body_v3.tex, it will compile as "??" — a broken reference.

**Verification needed:** Search main_v3.tex and body_v3.tex for `\ref{sec:hf}` to confirm whether any broken reference exists.

**Update:** Searching body_v3.tex, line 19 reads: "Section~\ref{sec:hf} presents high-frequency volatility evidence" — this is in the Introduction road map. Since `sec:hf` does not exist in body_v3.tex (confirmed by section label audit), this **is a broken cross-reference** that will appear as "??" in compiled PDF.

---

### NEW-L2: Introduction Road Map References Non-Existent Section

Related to NEW-L1: The Introduction road map (line 19) describes a section structure that does not match body_v3.tex:

- "Section~\ref{sec:hf} presents high-frequency volatility evidence" — **sec:hf does not exist**
- Body_v3.tex sections are: sec:intro, sec:data, sec:leverage, sec:vt, sec:macro, sec:var, sec:discussion, sec:conclusion, app:tz

The road map must be updated to reflect the actual section structure.

---

### NEW-L3: VIXTWN-to-VIX Ratio Rounding Inconsistency

**Location:** line 119 vs line 113

Line 113: "K = 12/1.39 = 8.63"
Line 119: "The VIXTWN-to-VIX ratio averages **1.393** with a coefficient of variation of 10%"

The ratio is 1.393 (line 119) but the calibration uses 1.39 (line 113). 12/1.393 = 8.615, not 8.63. This is a minor rounding issue but introduces a 0.2% inconsistency. Either use 1.39 throughout or 1.393 throughout.

---

### NEW-L4: Missing Context for "87% of total close-to-close returns" Claim

**Location:** Appendix A, line 571

"the overnight opening gap accounts for 87% of total close-to-close returns over the 2012–2025 sample"

But the main text (line 529) states "approximately 78% of the c2c strategy alpha is absorbed by the opening gap" with supporting R² statistics. These are two different measures (proportion of total returns vs proportion of strategy alpha), but the 87% and 78% figures appear in the same appendix without a clear statement of what each measures. A footnote distinguishing the two quantities would prevent confusion.

---

### NEW-L5: Citation for GARCH-MIDAS Framework

**Location:** body_v3.tex line 329

Section 5 introduces the "GARCH-MIDAS framework \citep{engle2013}" but does not cite the original MIDAS (Mixed Data Sampling) papers: Ghysels, Santa-Clara, and Valkanov (2004, 2005, 2006). This is a standard citation in the volatility forecasting literature. For JBF, reviewers familiar with GARCH-MIDAS will expect the foundational MIDAS references alongside Engle et al. (2013).

---

## Overall Verdict

**MAJOR REVISION NEEDED — DO NOT SUBMIT IN CURRENT FORM**

The three previous HIGH severity issues from v3_quick have been resolved through the architectural change of removing the HF section. However, this review has identified **three new HIGH severity issues** (NEW-H1 through NEW-H3) involving numerical inconsistencies within the paper itself:

1. **8.63/VIX Sharpe = 1.137 (Table 3) vs 0.690 (Table 5, citing Table 3)** — a referee will immediately identify this as a data integrity problem.
2. **GJR VT Sharpe increment = +0.124 (body) vs +0.114 (intro/conclusion)** — internal inconsistency across three locations.
3. **8.63/VIX MDD = -13.7% (Table 3) vs -15.3% (Section 4.3 text)** — contradictory values for same strategy/period.

Additionally, the paper has a **broken cross-reference** (NEW-L1/L2): `\ref{sec:hf}` in the Introduction road map points to a section that no longer exists, producing "??" in the compiled PDF. This must be fixed before submission.

The root causes appear to be (a) a rebalancing-frequency confusion in Table 3 footnote (daily vs monthly), and (b) stale numbers in the Introduction and Conclusion that were not updated when Table 4 was revised to K900 canonical values.

---

## Next Recommended Actions (Priority Order)

1. **[BLOCKER] Fix broken \ref{sec:hf} in Introduction road map** (NEW-L1/L2). Rewrite the road map paragraph to match actual section structure (sec:leverage, sec:vt, sec:macro, sec:var, sec:discussion).

2. **[BLOCKER] Resolve 8.63/VIX Sharpe inconsistency** (NEW-H1): Identify the canonical source experiment and Sharpe (0.690 monthly vs 1.137 daily). Update Table 3 to show the correct monthly-rebalancing Sharpe. Remove the self-contradictory "all strategies daily / 8.63/VIX monthly" statement from Table 3 footnote.

3. **[BLOCKER] Resolve GJR VT Sharpe increment inconsistency** (NEW-H2): Decide on canonical GJR VT Sharpe (1.074 from Table 3 or 1.084 from Table 4). Update Introduction and Conclusion to say +0.124 (if 1.074 is canonical) or +0.134 (if 1.084 is canonical). Ensure Tables 3 and 4 are sourced from the same K-experiment or the discrepancy is explicitly footnoted.

4. **[HIGH] Resolve 8.63/VIX MDD inconsistency** (NEW-H3): Verify against K-experiment data whether 2016–2026 MDD is -13.7% or -15.3%. Correct Table 3 or Section 4.3 text accordingly.

5. **[HIGH] Clarify VaR violation rate inconsistency** (NEW-M5): Add explicit language disambiguating model-level VaR (0.5%, K896, Section 6.2) vs strategy-level VaR (1.46%/1.66%, K900, Section 6.5). Cross-reference the two subsections.

6. **[MEDIUM] Fix Section 5 opening paragraph** (NEW-M1): Remove "time-zone arbitrage" from the list of core contributions, since it is appendix material.

7. **[MEDIUM] Fix Section 4→Macro transition** (M1, still open): Add 1–2 bridging sentences at the end of Section 4 motivating why macroeconomic indicators are examined next.

8. **[MEDIUM] Clarify DM test sign convention** (NEW-M4): Add one sentence in Section 2.4 stating the sign convention for the DM t-statistic.

9. **[LOW] Fix VIXTWN ratio rounding** (NEW-L3): Use 1.393 consistently, or 1.39 consistently.

10. **[LOW] Add GARCH-MIDAS citations** (NEW-L5): Add Ghysels et al. foundational MIDAS references in Section 5.

11. **[LOW] After all fixes, recompile and verify no "??" cross-references remain** in the PDF.
