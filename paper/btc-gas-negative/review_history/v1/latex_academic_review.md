# Academic Review — BTC-GAS Negative-Result Paper (R0)

**Document**: `paper/btc-gas-negative/drafts/body_v1.md`  
**Review date**: 2026-06-07  
**Reviewer**: latex-academic-reviewer (Claude, R0 pass)  
**Standard**: Top-tier finance journal (JBF / IJF target)  
**Key experiments verified**: K1129, K1133, K1133b result JSONs cross-checked against all headline claims

---

## Verdict

**MAJOR_REVISION**

The paper has a genuinely interesting and well-structured negative result, executed with methodological care (factorial design, pre-registration, multistart MLE, lookahead audit). The core headline numbers are fully reproducible from the JSON results and internally consistent. However, four issues — one severe data-description error, one quantitative factual error in the discussion, one internal threshold inconsistency, and one unresolved "Period 2 preliminary" framing problem — require correction before the paper can be submitted. None of the severe issues affect the validity of the central finding; they are presentation and framing problems that a reviewer would flag immediately.

---

## Summary Counts

| Severity | Count |
|---|---|
| SEVERE (S) | 3 |
| MAJOR (M) | 5 |
| MINOR (m) | 7 |

---

## Strengths

1. **Factorial design is methodologically exemplary.** Orthogonalizing innovation distribution × dynamics before running any comparison eliminates the standard conflation in the GAS-vs-GJR literature. The M5 placebo contrast (GJR-N-std vs M1 DM = -0.06) is an especially rigorous null calibration that most papers omit.

2. **Harvey-Liu-Zhu (2016) rigor is appropriately applied.** Using |DM| > 3 as the sub-period stability gate (not just p < 0.05) aligns with the credibility standards the target journals now demand for forecasting papers. Pre-registration of the factorial logic before running K1133b is explicitly documented and rules out data-mining critique.

3. **Multistart MLE with 100 initializations and basin stability diagnostics.** The K1213 methodology rule is visibly implemented and reported. Cross-seed log-likelihood dispersion < 0.5 in 96% of windows is a concrete, verifiable statement rather than a vague robustness claim.

4. **Regime-switching rescue test is set up as a proper falsification device.** Framing MS-GAS-t as a falsifier of "is this just regime confounding?" is the right scientific move; the result (partial rescue, parity but not exceedance vs GJR-N) is highly informative and avoids the common trap of interpreting a regime-switching improvement as exonerating the single-state failure.

5. **Writing quality is high throughout.** The logical flow — period decomposition → factorial diagnosis → rescue test → economic interpretation — is well-executed, and the discussion in Section 7 situates the finding clearly in the microstructure literature.

---

## SEVERE Issues (must fix before next round)

**S1. Period 3 OOS dates are wrong in the paper.** [Section 3.2, Abstract, Key Numbers table, Section 4, Section 9]

The paper consistently describes Period 3 as "2024-01-21 → 2024-04-30 (n_OOS = 100)" and the spot-ETF era as starting January 2024. However, the canonical result JSON (`experiments/k1133b/k1133b_results.json`, `part_A_results.Period3_spotETF_era`) shows:
- `oos_start`: **2026-01-05**
- `oos_end`: **2026-04-14**
- `sub_period_start`: 2024-01-01, `sub_period_end`: 2026-04-15

The OOS evaluation window for Period 3 runs from January 2026 to April 2026, not from January 2024 to April 2024. The paper's narrative — that Period 3 immediately follows the January 2024 spot-ETF approval — may be describing the sub-period boundary correctly, but the actual OOS data observed in the evaluation window is from 2026. This means the in-sample window for Period 3 starts in 2024 and the OOS observations begin after the rolling 750-day warm-up (approximately January 2026 for a window starting 2024-01-01). 

**Impact**: The stated "n = 100 preliminary, sample starts 2024-01-21" description is factually wrong. Either the period labeling is wrong, or the narrative about what "Period 3 OOS" means needs complete rewriting. This must be resolved before publication and affects every claim made about "2024 spot-ETF era OOS performance."

**Fix**: Clarify in Section 3.2 that Period 3 sub-period runs 2024-01-01 → 2026-04-15 and the OOS evaluation window — after the 750-day rolling warm-up — begins approximately 2026-01-05. Update all section references and the Key Numbers table to reflect the actual OOS dates. Revise the Abstract, Section 4, and Section 9 to describe Period 3 as "2026-Q1 OOS window (n = 100 days)" within the spot-ETF sub-period defined from January 2024 onward.

---

**S2. "Degrees of freedom above 30" claim for MS-GAS-t high-volatility state is factually wrong.** [Section 6, final paragraph]

The paper states: "the high-volatility state estimated by MS-GAS-t exhibits degrees of freedom above 30 across the multi-start basin." The JSON `ms_fit_log` for Period 1 shows six refitting windows; the maximum ν across all windows and both states is approximately 15 (window t_abs=1758, state_1 ν=15.48). No state in any window approaches ν = 30. The next-highest is ν ≈ 15.5 and the modal values across windows are ν ∈ [4, 10]. The claim that the regime-switching model "quietly de-fattens the tail by pushing toward Normal (ν > 30) in the high-volatility state" is not supported by the actual parameter estimates.

**Impact**: This is the key mechanistic interpretation offered for the MS-GAS-t rescue result, and it is wrong. The regime-switching model helps but the explanation offered for *why* it helps (one state is essentially Normal) is not supported by the MLE output. The actual pattern — lower ν in both states relative to single-state GAS-t — requires a different or more nuanced interpretation.

**Fix**: Replace the ν > 30 claim with the actual estimated ν values from the ms_fit_log. Revise the "revealed preference for Normal alternative" interpretation accordingly. The correct observation may be that neither state pushes ν toward the Normal limit, which actually *strengthens* the overall argument: regime-switching improves on single-state GAS-t without even de-fattening the tail, but still can't beat GJR-Normal, reinforcing the structural nature of the mismatch.

---

**S3. Internal inconsistency in the Harvey-Liu-Zhu threshold applied to Table 1.** [Section 3.6, Table 1 note, Sections 4 and 5]

The methodology Section 3.6 states: "Following Harvey, Liu and Zhu (2016), we treat |t_{DM-HLN}| > 3 as the threshold for stable sub-period inference." However, Table 1's note reads: "Bold entries satisfy |t| > 2 (Harvey, Liu, and Zhu, 2016)." These two thresholds are inconsistent. In practice the paper bolds M2 (DM = -3.36) and M3 (DM = -4.67) but not M4 (DM = -1.90), which is consistent with a threshold between 1.9 and 3.36. The actual bolding is consistent with |t| > 2 but the text says |t| > 3.

**Impact**: A reviewer at JBF or IJF will spot this immediately and it undermines trust in the methodological rigor of the writeup. The choice of threshold also matters: DM = -2.67 (M4 vs M3 innovation contrast) would be bolded under a |t| > 2 rule but not under a strict |t| > 3 rule. The paper should decide on one threshold and apply it consistently everywhere.

**Fix**: Pick one threshold — either |t| > 2 (the more permissive standard from Harvey-Liu-Zhu (2016)) or |t| > 3 (the conservative sub-period stability criterion) — and apply it uniformly to the Table 1 note, all text references, and the significance language in Sections 4 and 5. We recommend |t| > 2.5 as a reasonable compromise that reflects the original HLZ paper's intended usage in cross-sectional tests (where |t| > 3 was calibrated for multiple-testing with thousands of factors), not for individual pairwise DM comparisons. Clearly state the choice and its rationale.

---

## MAJOR Issues (should fix)

**M1. Period 2 is labeled preliminary in the JSON but treated as fully inferred in the paper.** [Sections 3.2, 4, 8]

`experiments/k1133b/k1133b_results.json` sets `preliminary_flag = True` for Period 2 (FTX-Luna era, n = 345). However, the paper treats Period 2 results with full confidence throughout, and only flags Period 3 (n = 100) as preliminary. The JSON was likely set to True for bookkeeping reasons unrelated to statistical power concerns, but this discrepancy between the JSON and the paper's framing should be explicitly reconciled — either by updating the JSON flag to False for Period 2 or by adding a footnote explaining why n = 345 is sufficient for the null-finding claim in Period 2 (it is: DM-HLN under H0 ~ N(0,1) and n = 345 gives adequate HAC power for detecting |DM| > 2 type effects).

---

**M2. "70%" attribution claim for innovation factor is arithmetically inaccurate.** [Section 5]

Section 5 states: "The 9.92% QLIKE deterioration of GAS-t against GJR-Normal can be apportioned approximately as 70% attributable to the Student-t innovation factor (the M3-to-M4 step, which moves from 2.1904 to 2.0402 in QLIKE) and 30% attributable to the GAS dynamics factor (the M4-to-M1 step, which moves from 2.0402 to 1.9926)."

Verification: (2.1904 - 2.0402) / (2.1904 - 1.9926) = 0.1502 / 0.1978 = **75.9%**, not 70%. The correct figures are approximately 76% and 24%.

**Fix**: Replace "70%" with "approximately 76%" and "30%" with "approximately 24%." Small change but arithmetic accuracy is a basic credibility requirement.

---

**M3. The "companion experiment K1129" reference in Section 5 may confuse readers.** [Section 5, first paragraph]

Section 5 refers to "the GAS-t reversal documented in our companion experiment K1129 on the full Bitcoin sample." This is internal experiment nomenclature that will not survive the LaTeX conversion. More importantly, K1129 is described as documenting the full-sample reversal while K1133b documents the sub-period decomposition — but the DM-HLN of -4.67 (Period 1) is from K1133b, not from K1129's full-sample test. The paper should be explicit about which numbers come from which experiment in the final version, without relying on K-id references.

---

**M4. Missing formal identification of the GAS-N score equation.** [Section 3.3, equations]

The paper writes the GAS-t score as $s_t = \frac{(\nu+1) r_t^2}{(\nu-2) h_t + r_t^2} - 1$ and then states that "the Normal-innovation GAS analog (M4) replaces $s_t$ with the Gaussian score $s_t^N = r_t^2 / h_t - 1$, which is the limit of $s_t$ as $\nu \to \infty$." However, this limit is only correct when the information-matrix scaling factor (the Fisher information normalization) is also taken to its Normal limit. The paper should explicitly derive or cite that $\lim_{\nu \to \infty} s_t^{Student} = s_t^{Normal}$ under the same scaling convention (i.e., showing that the Fisher information matrix element for ν → ∞ converges to 2, restoring the GAS-N score). Without this, a reader familiar with Creal-Koopman-Lucas (2013) may question whether M4 is correctly specified. This is a one-line algebraic note but important for precision.

---

**M5. Appendix A and B are referenced but do not exist in the draft.** [Sections 5, 8]

Section 5 references "Appendix A" for robustness with skewed-t and GED innovations; Section 8 references "Appendix B" for cross-asset ETH and BNB replication. Neither appendix is present in the current draft. This is presumably intentional at the v1 stage, but the references to "detailed results in Appendix A/B" should either be provisionally drafted or marked explicitly as [Appendix — to be added post-R0].

---

## MINOR Issues (nice to fix)

**m1. The QLIKE formula in Section 3.6 appears off by one.** [Section 3.6]

The formula as written is $\mathrm{QLIKE}_t = \frac{r_t^2}{\hat h_t} - \ln\frac{r_t^2}{\hat h_t} - 1$. This is not the standard Patton (2011) QLIKE loss. The conventional form is $\mathrm{QLIKE}_t = \frac{\sigma_t^2}{\hat h_t} - \ln \frac{\sigma_t^2}{\hat h_t} - 1$ where $\sigma_t^2$ is the realized volatility proxy (here $r_t^2$). The formula as written is numerically equivalent when $\sigma_t^2 = r_t^2$, but Patton (2011) distinguishes the formula from its substitute proxy; writing it as $r_t^2$ conflates the proxy substitution with the loss definition and deviates from the standard notation. Use the two-argument form $\text{QLIKE}(\sigma^2, \hat h) = \sigma^2/\hat h - \ln(\sigma^2/\hat h) - 1$ with $\sigma^2 = r_t^2$ stated separately.

**m2. "Harvey-Leybourne-Newbould (1997)" typo.** [Section 4, Table 1 note]

Table 1 note reads "Harvey, Leybourne, and Newbould." The correct spelling is Harvey, Leybourne, and **Newbold** (no 'u'). This appears correctly spelled as "Newbold" in Section 3.6. Fix for consistency.

**m3. Period 1 OOS start date inconsistency.** [Section 3.2]

Period 1 OOS start is stated as "2017-01-21" but the sub_period_start in the JSON is "2015-01-01". The OOS start of 2017-01-21 makes sense as the date after the 750-day warm-up window from 2015-01-01, but the paper never explains this explicitly. A sentence in Section 3.2 or a footnote clarifying "Period 1 OOS begins 2017-01-21 following the initial 750-day in-sample window" would prevent reader confusion.

**m4. QLIKE relative improvement framing flips sign conventions between tables and text.** [Sections 4 and 5]

The JSON uses `QLIKE_rel_improvement_pct` from the perspective of the challenger model, so M3 GAS-t vs M1 GJR-N is listed as "-9.92%" (M3 is 9.92% *worse*). The paper correctly translates this as "9.92% deterioration." But when Table 1 is described in the text, the convention is occasionally unclear (e.g., "a QLIKE point estimate of 2.1904 against the benchmark 1.9926, a 9.92% deterioration" — this is correct). Ensure all percentage mentions use a consistent frame: either always "X% worse" or always "X% higher QLIKE."

**m5. Section 5 innovation contrast p-value rounds ambiguously.** [Section 5]

"The two-sided p-value is approximately 0.008." The JSON shows 0.007775, which rounds to 0.008. However, "approximately 0.008" suggests ≈ 0.01 precision; consider "p = 0.0078" for precision, or "p < 0.01" as a threshold statement.

**m6. The title is informative but very long for a journal.** [Title page]

"Why GAS-t Fails on Pre-Institutional Bitcoin: Student-t Innovation, Not Score-Driven Dynamics, Is the Culprit (and Regime-Switching Cannot Fully Rescue It)" is 22 words including the subtitle and parenthetical. JBF typically runs title lengths of 10-15 words. Consider trimming to e.g. "Student-t Innovation, Not Score-Driven Dynamics, Drives Bitcoin Volatility Forecast Failure: A Factorial Decomposition" or similar.

**m7. Abstract still uses K-experiment cross-reference notation.** [Abstract line: "documents the K1129 full-sample reversal"]

The K-id notation ("K1129 full-sample reversal") in the abstract is internal workflow notation. This does not appear in the v1 draft abstract for publication, only in the outline — but when the abstract is finalized, ensure no K-ID references survive into the reader-facing text.

---

## Structural / Coverage Gaps

1. **No formal test for the "Period 3 absence of reversal" claim.** The paper reports |DM-HLN| < 1.1 across all Period 3 comparisons and concludes "no deficit." But this is a null finding with n = 100 OOS days. The power of the DM-HLN test under standard alternative hypotheses (e.g., a 5% QLIKE difference similar to what Period 1 shows) should be computed or at least discussed. Otherwise a reviewer could argue the null finding in Period 3 is simply due to inadequate power.

2. **Literature review does not cite Blasques et al. (2018) scoring function paper.** Section 2.1 mentions "Blasques, Koopman, Łasak, and Lucas (2018)" in passing but does not include it in the bibliography seed. This paper is a key reference for GAS asymptotic theory. Ensure it is in the final bibliography.

3. **The "pre-registration" claim needs to be more formally stated.** The paper says "pre-registration of the factorial logic in K1133b methodology note v1.0, 2026-04-15." For a journal like JBF, pre-registration means a public registration (OSF, AEA RCT Registry). The internal methodology note is good practice but is not technically "pre-registration" in the sense reviewers expect. Consider replacing "pre-registration" with "specification ante-dating" or "pre-specified factorial design" to avoid overstating what was done.

---

## Recommendation for R1

The paper should be revised to address S1, S2, and S3 as hard requirements. S1 (Period 3 date error) and S2 (ν > 30 claim) are both factual errors that would cause a JBF reviewer to question the credibility of all other numbers; they must be fixed before re-submission. S3 (threshold inconsistency) is a presentation error that undermines methodological credibility. 

The MAJOR issues (M1–M5) are each addressable in a revision without structural change to the paper. M2 (70% → 76% correction) takes five minutes but must be caught. M4 (GAS-N score derivation note) adds one sentence. M5 (appendix stubs) is a placeholder issue.

After addressing S1–S3 and M1–M5, the paper's core argument is sound and well-supported. The factorial design, multistart MLE discipline, pre-specified period partition, and partial-rescue test constitute a methodologically defensible negative-result paper suitable for the target journals. The writing quality is strong and the structure is compelling. A clean R1 submission addressing these issues should be competitive for IJF and has a reasonable shot at JBF's negative-result / methodology track.

---

## Traceability of Key Numbers

All headline statistics verified against `experiments/k1133b/k1133b_results.json`:

| Statistic | Paper value | JSON value | Match |
|---|---|---|---|
| QLIKE M1 GJR-N (P1) | 1.9926 | 1.9926 | YES |
| QLIKE M3 GAS-t (P1) | 2.1904 | 2.1904 | YES |
| QLIKE M4 GAS-N (P1) | 2.0402 | 2.0402 | YES |
| DM-HLN M3 vs M1 (P1) | -4.67 | -4.669 | YES |
| DM-HLN M2 vs M1 (P1) | -3.36 | -3.355 | YES |
| DM-HLN M4 vs M1 (P1) | -1.90 | -1.898 | YES |
| DM-HLN M4 vs M3 (innov) | +2.67 | +2.665 | YES |
| DM-HLN MS vs M3 | +5.97 | +5.971 | YES |
| DM-HLN MS vs M1 | +0.28 | +0.275 | YES |
| GAS-t QLIKE deterioration % | 9.92% | 9.92% | YES |
| Period 3 OOS start | 2024-01-21 | 2026-01-05 | **NO (S1)** |
| 70% innovation attribution | 70% | 76.0% | **NO (M2)** |
| MS high-state ν > 30 | > 30 | max ≈ 15.5 | **NO (S2)** |
