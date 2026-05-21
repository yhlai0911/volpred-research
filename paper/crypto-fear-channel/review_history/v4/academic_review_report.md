# Academic Review Report — crypto-fear-channel v4

**Date**: 2026-05-17
**Reviewer**: latex-academic-reviewer subagent (v4 round)
**Manuscript**: `paper/crypto-fear-channel/main.tex` (543 LoC)
**Source experiments**: K1025 (BTC→VIX, primary) + K1025b (BTC→VXN, multi-asset robustness)
**Target journals**: JIMF (1st) / JEF (2nd) / FRL (backup)
**Round context**: v4 = post-v3.1 hotfix. v3 review identified 0 CRIT / 0 SEV / 1 MAJOR (Table 7 K1025b errors) / 3 MED / 4 MINOR; v3.1 hotfix applied MAJOR-1 fix (K1025b BTC⁻ best F: ~15→24.31; QR amplification: ~11×→5.76×). v4 verifies the MAJOR fix and audits for new or residual issues.

---

## Overall Assessment

**Academic Score**: 4.55★ / 5.00
**Verdict**: CONDITIONAL_PASS
**Recommendation**: needs_minor_revision (one MAJOR and two MED must be addressed before submission)

---

## Summary Table

| Category | Count | Blocking? |
|----------|-------|-----------|
| CRITICAL | 0 | YES |
| SEVERE | 0 | YES |
| MAJOR | 1 | YES |
| MED | 3 | No |
| MINOR | 3 | No |

---

## Issue Details

### CRITICAL (blocking submission)

None.

---

### SEVERE (blocking submission)

None.

---

### MAJOR (blocking submission)

#### MAJOR-1 — §2.2 claims Diks (2006) and Hong (2001) as implemented robustness checks, but they are absent from §6

**Location**: §2.2 (Methodological building blocks), line 68.

**Exact text**: "Earlier nonparametric extensions of Granger causality \citep{diks2006} and asymmetric volatility-spillover tests \citep{hong2001} provide complementary diagnostic tools that **we use as robustness checks**."

**Problem**: The Robustness section (§6) contains four subsections — DY spillover stability, lag-length sensitivity, pre/post-ETF microstructure, and multi-asset BTC→VXN — none of which implements the Diks-Panchenko nonparametric Granger test or the Hong (2001) asymmetric volatility-spillover statistic. The literature review commits to these as "robustness checks we use" but the paper never delivers them.

**Why MAJOR**: This is a factual misrepresentation of the paper's scope that every referee will test. A JIMF reviewer reading §2.2 will proceed to §6 expecting to find Diks/Hong results; discovering their absence will raise questions about either the rigor of the review or the completeness of the robustness analysis. Under JIMF's detailed reviewer culture this is a reliable desk-level flag.

**Two acceptable fixes**:
1. **Weaker fix (change §2.2 language)**: Replace "we use as robustness checks" with "have been proposed as complementary robustness tools" or "could serve as robustness diagnostics for this channel." This removes the unfulfilled commitment without requiring new computation.
2. **Stronger fix (implement one of the two)**: Add a brief §6.5 running the Diks-Panchenko nonparametric Granger test for the BTC⁻→VIX channel (the key asymmetric Granger result). This would take ~1 additional page and turn the reference into a genuine robustness contribution. The Hong (2001) test would be more work and is lower priority.

**Recommendation**: Apply the weaker fix (§2.2 language change) for v4.1. The stronger fix is ideal but can be an R&R add. The important thing is that no claim commits to something the paper does not deliver.

**Estimated effort**: 5 minutes (§2.2 one-sentence edit).

---

### MED (polish before submission)

#### MED-1 — Abstract p-value inconsistency for 2020 Granger F-test

**Location**: Abstract (line 28) vs. Introduction §1 paragraph "Regime dependence" (line 47) vs. Results §5.3 (lines 238, 250).

**Problem**: Three different levels of precision for the same statistic ($F = 11.05$, 2020 subperiod):
- Abstract: "$p < 0.001$" (weakest precision)
- Intro §1: "$p < 10^{-6}$"
- Results §5.3: "$p = 7.9 \times 10^{-7}$" and Table 3 row

The actual value is $p = 7.9 \times 10^{-7}$. The abstract's "$p < 0.001$" is technically correct but two orders of magnitude weaker than what is actually observed, creating an impression mismatch for a reader who first encounters the abstract. A reviewer who moves from abstract to results will notice the escalation.

**Why MED (not MAJOR)**: "$p < 0.001$" is not false, just imprecise. The mismatch is cosmetic rather than substantive. However, in a paper whose central argument rests on precise regime identification, sloppy precision in the abstract undermines the "rigorous reporting" branding.

**Suggested fix**: Update abstract to "$p < 10^{-6}$" to match the Introduction paragraph's level. The full precise value can remain in Table 3.

**Estimated effort**: 2 minutes.

---

#### MED-2 — §4 methodology intro section-numbering inconsistency: "three (§4.1–§4.4)" is self-contradictory

**Location**: §4 (Methodology) opening paragraph, line 122.

**Exact text**: "We employ four methodological building blocks. The first three (\S\ref{sec:methodology}.1--\ref{sec:methodology}.4) characterize *in-sample* cross-asset structure along three dimensions: directional asymmetry, tail dependence, and regime stability. The fourth (\S\ref{sec:methodology}.5) tests *out-of-sample* predictive content."

**Problem**: The text says "the first three" but cites "§4.1–§4.4," which spans four subsections, not three. The subsection structure of §4 is:
- §4.1 Symmetric Granger causality (baseline) — this is a *baseline/preamble*, not one of the "four building blocks"
- §4.2 Asymmetric Granger (Building Block 1: directional asymmetry)
- §4.3 Quantile regression (Building Block 2: tail dependence)
- §4.4 Diebold-Yilmaz (Building Block 3: regime stability)
- §4.5 Out-of-sample forecasting (Building Block 4: OOS predictive content)

So "the first three" in-sample building blocks are in §4.2–§4.4, not §4.1–§4.4. The intro paragraph subsumes §4.1 (the symmetric Granger baseline) into the in-sample group, making the count "three dimensions = four subsections" contradiction visible to a careful reader. Additionally, the data section reference uses the same pattern: "\S\ref{sec:methodology}.5" correctly points to §4.5, but "\S\ref{sec:methodology}.2" (used in §3.2) uses decimal-dot notation that LaTeX renders ambiguously (it will print as "§4.2" but is not a real cross-reference with hyperlinks if not using \nameref).

**Why MED**: A referee who reads §4's opening carefully will notice "three" and ".1–.4" don't match. This is a copy-edit error that is easy to fix but signals careless proofreading.

**Two acceptable fixes**:
1. Change "the first three (§4.1–§4.4)" to "§4.2–§4.4" (the three in-sample building blocks, excluding the symmetric-Granger baseline in §4.1); OR
2. Change "the first three" to "the first four" if the intent is that §4.1 symmetric Granger counts as the first in-sample component — but then the "three dimensions" claim at the end of the same sentence also needs updating to "four."

The cleanest fix is option 1: "Subsections §4.2–§4.4 characterize in-sample cross-asset structure along three dimensions: directional asymmetry, tail dependence, and regime stability. Subsection §4.1 provides the symmetric-Granger baseline against which these building blocks are compared. Subsection §4.5 tests out-of-sample predictive content."

**Estimated effort**: 5–10 minutes.

---

#### MED-3 — §6 robustness section intro says "three robustness checks" but §6 now has four

**Location**: §6 (Robustness), line 287.

**Exact text**: "This section reports **three** robustness checks on the headline findings of §5: the time-series stability of the Diebold-Yilmaz spillover index, the lag-length sensitivity of the subperiod Granger structure, and a pre-ETF vs. post-ETF microstructure comparison."

**Problem**: The K1025b multi-asset robustness check (§6.4) was added in v3, making §6 a four-subsection section. The intro sentence enumerates only the original three (matching §6.1, §6.2, §6.3) and never mentions §6.4. A referee reading §6's intro will expect three subsections and then encounter a fourth.

**Why MED**: The omission is cosmetic but will be noticed by any editor or referee who counts. More importantly, §6.4 is actually the strongest robustness check (multi-asset OOS generalization), and failing to mention it in §6's intro undersells the paper's robustness case.

**Suggested fix**: Update §6 intro to: "This section reports four robustness checks on the headline findings of §5: the time-series stability of the Diebold-Yilmaz spillover index (§6.1), the lag-length sensitivity of the subperiod Granger structure (§6.2), a pre-ETF vs. post-ETF microstructure comparison (§6.3), and a multi-asset generalization to the BTC→VXN (NASDAQ-100 fear gauge) channel (§6.4)."

**Estimated effort**: 5 minutes.

---

### MINOR (nice-to-have)

#### MINOR-1 — Table 6 (multiasset) caption still says "OOS robustness" but table contains both in-sample and OOS metrics

**Location**: line 316, `\caption{Multi-asset OOS robustness: K1025 (BTC$\to$VIX, SPY) versus K1025b (BTC$\to$VXN, QQQ).}`

**Problem**: Table 6 (tab:multiasset) contains mixed in-sample metrics (Granger F-statistics, QR β coefficients, DY net spillover) and OOS metrics (DM t-statistic). The caption "Multi-asset OOS robustness" implies the table is OOS-focused, misrepresenting its content scope.

**Suggested fix**: Rename caption to "Multi-asset robustness: K1025 (BTC$\to$VIX, SPY) versus K1025b (BTC$\to$VXN, QQQ) across in-sample and OOS specifications."

**Estimated effort**: 2 minutes.

---

#### MINOR-2 — §8.2 claims asymmetric Granger has "$p < 10^{-7}$" but Table 1 lag-1 row shows $p = 1.4 \times 10^{-5}$

**Location**: §8.2 (Granger causality ≠ forecastability), line 385.

**Exact text**: "The juxtaposition of the highly significant in-sample asymmetric Granger result ($F$ up to 18.96, $p < 10^{-7}$) with the failed out-of-sample DM test..."

**Problem**: $F = 18.96$ corresponds to lag 1 (Table 1 BTC⁻ row), which has $p = 1.4 \times 10^{-5}$, not $p < 10^{-7}$. The lower p-values ($4.1 \times 10^{-7}$, $1.2 \times 10^{-6}$, $7.1 \times 10^{-6}$, $3.7 \times 10^{-6}$) are for lags 2–5, which have lower F-statistics. The claim pairs the maximum F-statistic with a p-value that does not correspond to it. While the statement is not strictly false (some lags do have $p < 10^{-7}$), the pairing "$F$ up to 18.96, $p < 10^{-7}$" implies the highest-F observation also has the smallest p-value, which is incorrect for this table structure.

**Suggested fix**: Change to either "$F$ up to 18.96 (lag 1, $p = 1.4 \times 10^{-5}$)" — precise pairing — or "$F$-statistics up to 18.96 and $p$-values as small as $4.1 \times 10^{-7}$" — correct but unpaired framing.

**Estimated effort**: 2 minutes.

---

#### MINOR-3 — `\texttt{statsmodels.tsa.stattools.grangercausalitytests}` overfull hbox at line 132 (carried from v3 MED-2, downgraded to MINOR)

**Location**: line 132, §4.1 (Symmetric Granger causality).

**Problem**: The `\texttt{statsmodels.tsa.stattools.grangercausalitytests}` string in the middle of a long compound clause causes an overfull \hbox (80.78pt in v3 compile log). The v2.3 sentence split reduced the sentence structure but did not resolve the overflow because the long `\texttt{}` string is the underlying source of the overflow.

**Why MINOR (downgraded from MED)**: The overfull box will produce a visually stretched line in PDF but does not affect content. At 80pt the issue is visible but not egregious. JIMF submissions in pre-review stage are typically read in PDF, where a single stretched line does not cause desk-rejection. The issue is best-effort for v4.1.

**Suggested fix**: Wrap the long `\texttt{}` reference into a footnote: "...the default specification of the routine that generates our $F$-statistics.\footnote{We use \texttt{statsmodels.tsa.stattools.grangercausalitytests} from statsmodels 0.14.}"

**Estimated effort**: 5 minutes.

---

## v3 Residual Issues Status

The v3 review identified **0 CRIT / 0 SEV / 1 MAJOR / 3 MED / 4 MINOR** at the time of the v3.1 hotfix expectation. This section verifies what was fixed and what carries over.

| v3 Issue | Severity | Status in v4 | Notes |
|----------|----------|-------------|-------|
| MAJOR-1: Table 7 K1025b BTC⁻ best F (~15→24.31) | MAJOR | **FIXED** | Line 322 now shows 24.31 (lag 1) |
| MAJOR-1: Table 7 K1025b amplification (~11×→5.76×) | MAJOR | **FIXED** | Line 327 now shows 5.76×; §6.4 narrative corrected |
| MAJOR-1: §6.4 narrative directional reversal | MAJOR | **FIXED** | Now correctly states "VIX exhibiting the stronger sign-reversing tail amplification of the two" |
| MED-1: Table 7 caption "OOS robustness" scope mismatch | MED | **NOT FIXED** → MINOR-1 (v4) | Caption still says "Multi-asset OOS robustness" |
| MED-2: §4.1 overfull hbox 80pt | MED | **NOT FIXED** → MINOR-3 (v4) | Still present; downgraded to MINOR given proximity to submission |
| MED-3: §6 structural balance (4 subsections, intro says 3 checks) | MED | **NOT FIXED** → MED-3 (v4) | §6 intro still says "three robustness checks" |
| MIN-1: Table 7 BTC⁻ entry needs lag-explicit note | MINOR | **IMPLICITLY FIXED** | Line 322 now reads "24.31 (lag 1)" with explicit lag specifier |

**New issues found in v4** (not present in v3 review):
- MAJOR-1 (v4): §2.2 Diks/Hong unfulfilled robustness commitment — this was present in the paper throughout v1-v3 but was not caught in prior reviews. First detected in v4 full-text read.
- MED-1 (v4): Abstract p-value imprecision ($p < 0.001$ vs. $p = 7.9 \times 10^{-7}$) — present throughout but not previously flagged.
- MED-2 (v4): §4 methodology intro self-contradictory count ("three (§4.1–§4.4)") — present throughout but not previously caught.
- MINOR-2 (v4): §8.2 F-statistic/p-value pairing error.

---

## Strengths

1. **Sign-reversal finding is genuinely novel and well-documented.** The quantile regression showing negative slope at τ=0.05, τ=0.25 and positive slope at τ=0.5, τ=0.75, τ=0.95 is a structurally interesting result with strong t-statistics at every quantile. This will attract referee attention in a positive way.

2. **Honest OOS null is a genuine contribution.** The explicit pairing of strong in-sample asymmetric Granger ($F$ up to 18.96) with a failed OOS DM test ($t = -0.98$) is methodologically honest and rare in the crypto-equity spillover literature. §8.2's reconciliation of this juxtaposition (sparse signal + regime concentration) is logically airtight.

3. **COVID-2020 watershed is cleanly identified.** The five-subperiod decomposition with 4/5 non-significant and 1/5 (2020) strongly significant Granger results is a clean regime story that translates directly to practical risk management advice.

4. **Multi-asset K1025b extension strengthens robustness.** With the v3.1 fixes correcting the K1025b numerical errors, §6.4 and Table 6 now credibly establish that the five stylized facts survive the BTC→VXN channel substitution, closing the most common single-asset referee objection.

5. **Policy implications are specific and quantitatively anchored.** §8.3's three policy prescriptions (no-decoupling supervision, upper-tail-calibrated margin systems, retail-investor protection externalities) are grounded in specific empirical findings and are directly actionable. The quantitative anchor (8.5× amplification ratio for stress-test calibration) is unusual in spillover papers and will be valued by JIMF's policy-oriented readership.

6. **Data and replication infrastructure are strong.** Yahoo Finance snapshot CSV with `auto_adjust=False`, reproduce.py 29/29 byte-match for K1025, inline `% source:` annotations on every table, and the qualitative γ-footnote for unverified rolling-window claims all meet the JIMF replication expectation.

---

## Potential Reviewer Objections

**Objection 1 (MOST LIKELY — methodology)**: "The Hatemi-J framework decomposes series into cumulative positive and negative innovations of the series itself (i.e., partial sums of the levels process). The authors adapt this by applying the decomposition to BTC *returns* first, then constructing directional RV — a departure from the Hatemi-J canonical specification. Why is this adaptation justified? Could it introduce spurious asymmetry by mapping level shocks to return-sign-conditional volatility in a non-standard way?"

*Severity for authors*: Medium-high. The paper acknowledges the adaptation in §3.2 and defends it as "preserving the key identification...while allowing the volatility-channel interpretation." But a methodologically sophisticated reviewer could push for either: (a) showing the original cumulative-innovation Hatemi-J specification gives the same qualitative result, or (b) formally deriving why the return-sign decomposition is asymptotically equivalent to the cumulative-partial-sum decomposition for the BTC RV process. This is an R&R-class request, not a desk-reject blocker, but should be anticipated.

**Objection 2 (LIKELY — data)**: "Using VIX as the dependent variable conflates implied and realized volatility. VIX is an options-market-implied measure. The paper claims to document crypto-to-equity 'volatility spillover' but the transmission is actually from Bitcoin realized variance to equity implied volatility — a cross-domain (realized-to-implied, crypto-to-equity) specification with different properties than a same-domain (realized-to-realized) comparison. Why not use SPX realized variance as the dependent variable?"

*Severity for authors*: Medium. VIX is the standard fear gauge and the paper's title ("Crypto Fear Channel") justifies using it. But a reviewer could argue that the sign-reversal result in quantile regression reflects VIX's mean-reversion property (VIX has a lower bound near 9) rather than a genuine crypto-to-equity spillover mechanism. The §3.2 DCC correlation table using SPY (not SPX RV) somewhat insulates the paper from this critique, but does not fully address it.

**Objection 3 (LIKELY — omitted robustness)**: "The paper commits to Diks-Panchenko and Hong (2001) as robustness diagnostics (§2.2) but never reports them. Where are these results?"

*Severity for authors*: High if MAJOR-1 is not fixed (see above). Low if the §2.2 language is changed before submission. This is the most easily triggerable referee objection because it requires only reading §2.2 and then searching §6 for Diks/Hong.

**Objection 4 (POSSIBLE — single episode concern)**: "The entire asymmetric Granger and quantile-regression story is driven by a single 253-day episode (COVID-2020). The post-COVID sample (2021–2026, roughly 3× longer than the COVID window) shows no Granger causality. Is the paper's contribution stable or is it a COVID-specific artifact that will not replicate in future samples?"

*Severity for authors*: Medium-low. The paper addresses this directly in §8.4 (limitations) and frames the COVID concentration as a substantive finding rather than a deficiency. However, a reviewer could push for a longer-horizon assessment or a structural-break test on the full Granger model.

**Objection 5 (POSSIBLE — DY specification)**: "The Diebold-Yilmaz total spillover of 90.1% with standard deviation 0.21pp is suspiciously stable. Most 3-variable VAR systems with a highly volatile asset (BTC) show more variation in variance decompositions. Is the total spillover reflecting VAR order selection overfitting or the FEVD horizon choice (H=10 days)?"

*Severity for authors*: Medium. The paper acknowledges the stability is "remarkable" in §6.1 and uses it to argue the DY and Granger measures capture different objects. A reviewer could request sensitivity to FEVD horizon (H=5, H=20) and VAR order (p=2, p=6). These are straightforward to add as robustness notes.

---

## Action Plan for v4.1

### Must-fix before submission

| Priority | Issue | Action | Effort |
|----------|-------|--------|--------|
| P1 (MAJOR) | MAJOR-1: §2.2 Diks/Hong unfulfilled commitment | Change "we use as robustness checks" to "have been proposed as complementary robustness diagnostics" | 5 min |
| P2 (MED) | MED-1: Abstract p-value for 2020 F-test | Change "$p < 0.001$" to "$p < 10^{-6}$" | 2 min |
| P3 (MED) | MED-2: §4 methodology intro "three (§4.1–§4.4)" contradiction | Rewrite §4 intro paragraph to correctly map subsection numbers to the three in-sample dimensions vs. the OOS fourth | 10 min |
| P4 (MED) | MED-3: §6 intro says "three robustness checks" (has four) | Update §6 intro to enumerate all four checks including §6.4 multi-asset | 5 min |

### Recommended but deferrable to R&R

| Priority | Issue | Action | Effort |
|----------|-------|--------|--------|
| P5 (MINOR) | MINOR-1: Table 6 caption "OOS robustness" scope | Rename to "in-sample and OOS specifications" | 2 min |
| P6 (MINOR) | MINOR-2: §8.2 F/p pairing error | Fix p-value pairing for F=18.96 lag 1 | 2 min |
| P7 (MINOR) | MINOR-3: Overfull hbox at line 132 | Wrap statsmodels texttt into footnote | 5 min |

### Anticipated R&R requests (prepare responses, no immediate action)

- Hatemi-J adaptation justification (return-sign vs. cumulative-partial-sum decomposition)
- VIX as implied-vs.-realized cross-domain specification concern
- Diks-Panchenko/Hong robustness implementation (if reviewer insists after §2.2 language fix)
- DY sensitivity to H (FEVD horizon) and VAR order p

---

## 10-Dimension Scoring (v4)

| # | Dimension | v3 | v4 | Δ | Comment |
|---|-----------|----|----|---|---------|
| 1 | Logic flow (abstract→conclusion) | 4.5 | 4.5 | 0 | Chain is intact; OOS null reconciliation in §8.2 is the strongest part |
| 2 | Argument quality / honest reporting | 4.7 | 4.7 | 0 | γ footnote template remains exemplary; K1025b corrected |
| 3 | Methodology self-containedness | 4.5 | 4.3 | -0.2 | Diks/Hong committed but not delivered (MAJOR-1) pulls this down |
| 4 | Equation correctness & clarity | 4.0 | 4.0 | 0 | Equations are internally correct; §4.1 Granger baseline eq is clear |
| 5 | Symbol consistency (§1–§9) | 3.5 | 3.5 | 0 | RV^{(20)} vs. RV^{btc} notation still mixed; §4 intro count inconsistency (MED-2) |
| 6 | Citation grounding | 4.5 | 4.5 | 0 | 22 bibitems; all cited works have DOIs; Diks/Hong cited correctly |
| 7 | Structure / sequencing | 4.0 | 4.0 | 0 | §6 four subsections but intro says "three"; otherwise clean |
| 8 | Honest reporting | 4.7 | 4.7 | 0 | No change from v3; γ footnote + K1025b corrected |
| 9 | Tables (T1–T6 self-containedness) | 3.7 | 4.2 | +0.5 | K1025b numerical errors fixed; amplification ratio now correct |
| 10 | First-time-paper fundamentals | 4.0 | 4.0 | 0 | 17-page length, multi-asset robustness; within JIMF norms |

**Weighted overall**: 4.55★ / 5.00 (up from v3's 4.30 post-hotfix projection of 4.55 — confirmed).

---

## Stage Gate Criteria Check

| Gate | Threshold | v3 pre-hotfix | v4 (current) | Pass? |
|------|-----------|--------------|-------------|-------|
| LaTeX score | ≥ 4★ | 4.30 | **4.55** | ✓ |
| CRITICAL count | 0 | 0 | 0 | ✓ |
| SEVERE count | 0 | 0 | 0 | ✓ |
| MAJOR count | 0 | 1 | **1** (NEW: §2.2 Diks/Hong) | **FAIL** |
| MED count | ≤ 3 | 3 | 3 | ✓ |
| Reproduce gate | green + ≥95% match | green (K1025 only) | green (K1025 only) | ✓ (caveat: K1025b coverage gap) |
| Compile clean | 0 errors | borderline | borderline (same) | ✓ borderline |

**Verdict**: 6/7 gates pass. One gate fails (MAJOR count = 1). MAJOR-1 (§2.2 Diks/Hong) can be fixed in 5 minutes with a language change. Recommend v4.1 single-commit fix batch to clear the MAJOR and three MED, then advance to `ready_for_submission`.

---

## Predicted Journal Outcomes

| Journal | Tier | v4 prediction (pre-fix) | v4.1 prediction (post-fix) |
|---------|------|------------------------|---------------------------|
| **JIMF** (1st target) | A- | R&R medium (Diks/Hong referee flag likely) | **R&R very high probability**; multi-asset robustness and honest OOS null are strong JIMF fits |
| **JEF** (2nd) | A | R&R medium (same flag) | **R&R high probability**; JEF's forecasting orientation is served by the Harvey-threshold OOS discipline |
| **FRL** (backup) | B+ | Accept medium | **Accept very high** |

**Strategic recommendation**: Do **NOT** submit v4 as-is. Apply the four must-fix items above in a v4.1 single-commit batch (estimated 20–25 minutes total). Once MAJOR-1 (§2.2 language) and MED-1 through MED-3 are resolved, the paper is ready for JIMF submission.

---

**Reviewer signature**: latex-academic-reviewer subagent (v4 round)
**Round**: v4, fourth-pass post-v3.1-hotfix verification + new full-text audit
**Next round trigger**: after v4.1 commit closes MAJOR-1 + MED-1 through MED-3. v4.1 should recompile clean and re-verify Table 6 numbers remain correct.

**Verdict**: 0 CRITICAL / 0 SEVERE / 1 MAJOR / 3 MED / 3 MINOR; score 4.55★ / 5.00; stage rec: STAY at `review` until v4.1 fixes MAJOR-1 (§2.2 language) + MED-1 (abstract p-value) + MED-2 (§4 intro count) + MED-3 (§6 intro count).

**Post-fix projected verdict (v4.1)**: 0 CRITICAL / 0 SEVERE / 0 MAJOR / 0 MED / 3 MINOR; score ~4.70★ / 5.00; stage rec: advance to `ready_for_submission`.
