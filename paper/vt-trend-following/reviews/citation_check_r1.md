# Citation Verification Report (R1)

**Manuscript**: "Is Volatility Targeting Just Trend Following? Decomposing the Benefits of Volatility Targeting"
**Version**: body_v2.tex (~33 pages, 18 citations)
**Date**: April 5, 2026
**Total Citations**: 18
**Verified**: 15 | **Minor Issues**: 2 | **Errors Found**: 1

---

## Summary

| Status | Count | Percentage |
|--------|-------|------------|
| Verified | 15 | 83% |
| Minor Issues | 2 | 11% |
| Errors Found | 1 | 6% |

---

## Detailed Findings

### Verified Citations

1. **Baltas and Kosowski (2013)**
   - Source: Working Paper, Imperial College London
   - Content claim: Momentum strategies in futures markets and trend-following funds
   - APA format: Correct (working paper format)
   - DOI: N/A (working paper)
   - Note: Published version appeared in 2015 in *European Financial Management* — consider updating to published version

2. **Barroso and Santa-Clara (2015)**
   - Source: Journal of Financial Economics, 116(1), 111-120
   - DOI: https://doi.org/10.1016/j.jfineco.2014.11.010
   - Content claim: "volatility-scaling momentum strategies eliminates momentum crashes" — Accurate representation of the paper's main finding
   - APA format: Correct
   - Note: Grammar error in paper text ("eliminates" should be "eliminate")

3. **Black (1976)**
   - Source: Proceedings of the 1976 Meetings of the American Statistical Association, Business and Economic Statistics Section, 177-181
   - DOI: N/A (conference proceedings)
   - Content claim: Leverage effect / asymmetric volatility — Accurate. This is the seminal paper on the leverage effect
   - APA format: Correct

4. **Bozovic (2024)**
   - Source: International Review of Financial Analysis, 95, 103353
   - DOI: https://doi.org/10.1016/j.irfa.2024.103353
   - Content claim: VIX-managed portfolios, cited for the 12/VIX construction — Accurate
   - APA format: Correct

5. **Cederburg et al. (2020)**
   - Source: Journal of Financial Economics, 138(1), 95-117
   - DOI: https://doi.org/10.1016/j.jfineco.2020.04.015
   - Content claim: "challenge VT on utility grounds, arguing that the strategy does not improve investor welfare after accounting for higher moments" — Accurate representation
   - APA format: Correct
   - Note: The paper text says "138(1)" which matches the published version

6. **Christie (1982)**
   - Source: Journal of Financial Economics, 10(4), 407-432
   - DOI: https://doi.org/10.1016/0304-405X(82)90018-6
   - Content claim: Leverage effect — Accurate (Christie documents the leverage effect empirically)
   - APA format: Correct

7. **Daniel and Moskowitz (2016)**
   - Source: Journal of Financial Economics, 122(2), 221-247
   - DOI: https://doi.org/10.1016/j.jfineco.2015.12.002
   - Content claim: "momentum crashes are driven by precisely this leverage-effect-induced volatility clustering" — Accurate. The paper shows momentum crashes occur because losers are low-beta, high-leverage stocks whose volatility spikes
   - APA format: Correct

8. **Fleming et al. (2001)**
   - Source: Journal of Finance, 56(1), 329-352
   - DOI: https://doi.org/10.1111/0022-1082.00327
   - Content claim: "established the economic value of volatility timing in a portfolio context" — Accurate
   - APA format: Correct

9. **Glosten et al. (1993)**
   - Source: Journal of Finance, 48(5), 1779-1801
   - DOI: https://doi.org/10.1111/j.1540-6261.1993.tb05128.x
   - Content claim: GJR-GARCH model — Accurate (this is the original GJR model paper)
   - APA format: Correct

10. **Harvey et al. (2016)**
    - Source: Review of Financial Studies, 29(1), 5-68
    - DOI: https://doi.org/10.1093/rfs/hhv059
    - Content claim: $t > 3.0$ threshold for multiple testing — Accurate. The paper recommends a threshold of approximately 3.0 for a single test and higher for multiple tests
    - APA format: Correct
    - Note: The paper applies this as an absolute threshold for individual strategies. The original Harvey et al. paper provides a framework for adjusting thresholds based on the number of factors tested. Using $t > 3.0$ as a fixed threshold is a conservative simplification that is widely adopted in the literature.

11. **Harvey et al. (2018)**
    - Source: Journal of Portfolio Management, 45(1), 14-33
    - DOI: https://doi.org/10.3905/jpm.2018.45.1.014
    - Content claim: "VT strategies improve risk-adjusted returns across multiple asset classes" — Accurate
    - APA format: Correct

12. **Moreira and Muir (2017)**
    - Source: Journal of Finance, 72(4), 1611-1644
    - DOI: https://doi.org/10.1111/jofi.12513
    - Content claim: "VT strategies improve risk-adjusted returns across equity factors" — Accurate. This is the seminal paper on volatility-managed portfolios
    - APA format: Correct

13. **Miranda-Agrippino and Rey (2020)**
    - Source: Review of Economic Studies, 87(6), 2754-2776
    - DOI: https://doi.org/10.1093/restud/rdaa019
    - Content claim: "global financial cycle" and "US monetary conditions propagate internationally through capital flows" — Accurate
    - APA format: Correct

14. **Moskowitz et al. (2012)**
    - Source: Journal of Financial Economics, 104(2), 228-250
    - DOI: https://doi.org/10.1016/j.jfineco.2011.11.003
    - Content claim: "generate significant abnormal returns across 58 futures markets" — Accurate
    - APA format: Correct

15. **Rapach et al. (2013)**
    - Source: Journal of Finance, 68(4), 1633-1662
    - DOI: https://doi.org/10.1111/jofi.12041
    - Content claim: "US market leads international returns" — Accurate
    - APA format: Correct

---

### Minor Issues

16. **Newey and West (1987)**
    - Source: Econometrica, 55(3), 703-708
    - DOI: https://doi.org/10.2307/1913610
    - Content claim: HAC standard errors — Accurate
    - APA format: Correct
    - **Minor issue**: The DOI `10.2307/1913610` is a JSTOR stable URL. The actual Econometrica DOI may differ. The JSTOR DOI resolves correctly, so this is a minor format inconsistency.
    - Also: The paper cites the automatic lag selection formula as from Newey and West (1987), but the $\ell = \lfloor 4(T/100)^{2/9} \rfloor$ formula is actually from **Newey and West (1994)**, "Automatic lag selection in covariance matrix estimation," *Review of Economic Studies*, 61(4), 631-653. The 1987 paper introduces the HAC estimator but does not provide automatic lag selection.
    - **Recommendation**: Either cite Newey and West (1994) for the lag formula, or change the text to say "Newey-West HAC with lag = [specific integer]" and attribute only the estimator to NW (1987).

17. **Lai (2026a)**
    - Source: Working Paper, Da-Yeh University
    - DOI: N/A (working paper)
    - Content claim: Various — cited for 12/VIX threshold robustness, insurance premium interpretation, DCC analysis, volatility-as-insurance perspective
    - APA format: Correct (working paper format)
    - **Minor issue**: The "(2026a)" suffix implies a companion paper "(2026b)" exists. If this paper will be (2026b), a self-citation should be added. If not, the suffix should be removed to avoid confusion.

---

### Errors Found

18. **Hood and Raughtigan (2025)**
    - Source: "Working Paper" — **No further identification provided**
    - DOI: N/A
    - Content claim: "approximately 91% of equity VT alpha is absorbed by a TSMOM factor when applied to 50 futures contracts" — **Cannot be independently verified** because the paper is not publicly accessible from the reference entry alone
    - APA format: **Incomplete** — Working papers should include either an SSRN link, institutional affiliation, or conference presentation venue
    - **Error**: This is the paper's primary interlocutor — the entire manuscript is structured as a response to Hood & Raughtigan's claim. A reviewer must be able to access this paper. The current reference provides no way to locate it.
    - **Recommendation**: Add SSRN link, institutional affiliation (e.g., "Working Paper, University of [X]"), or note if it was presented at a specific conference (e.g., "Presented at AFA 2025")

---

## Missing References (Recommended Additions)

The following references are absent but would strengthen the paper:

| Reference | Reason Needed | Priority |
|-----------|---------------|----------|
| **Frazzini & Pedersen (2014)** "Betting Against Beta," *JFE* | BAB factor used in Table 4 M5; creators must be cited | HIGH |
| **Hurst, Ooi & Pedersen (2017)** "A Century of Evidence on Trend-Following Investing" | Longest trend-following backtest; directly relevant to Section 4.1 claim that trend following fails | MEDIUM |
| **Liu et al. (2019)** "Volatility-managed portfolios revisited" | Direct response to Moreira & Muir; challenges VT benefits | MEDIUM |
| **Jegadeesh & Titman (1993)** "Returns to Buying Winners and Selling Losers," *JoF* | Cross-sectional momentum; relevant when discussing MOM factor in Table 4 | LOW |
| **Newey & West (1994)** "Automatic lag selection in covariance matrix estimation," *RES* | Automatic lag formula attributed to NW (1987) but actually from NW (1994) | LOW |
| **Lahiri (2003)** *Resampling Methods for Dependent Data* | Block bootstrap block size justification ($b \approx T^{1/3}$) | LOW |

---

## Correction Checklist

- [ ] **Fix citation #18 (Hood & Raughtigan)**: Add SSRN link or institutional affiliation
- [ ] **Fix citation #16 (Newey & West)**: Either add NW (1994) for lag formula or remove automatic lag attribution
- [ ] **Fix citation #17 (Lai 2026a)**: Remove "a" suffix or add self-citation for (2026b)
- [ ] **Add Frazzini & Pedersen (2014)**: Essential if using BAB factor
- [ ] **Consider adding**: Hurst et al. (2017), Liu et al. (2019)
- [ ] **Consider updating**: Baltas & Kosowski (2013) to published 2015 version

---

## Orphan Reference Check

All 18 bibliography entries are cited in the text. No orphan references found. (v2 fixed the 3 orphans from v1: barroso2015, daniel2016, fleming2001.)

## In-Text Citation Format Check

- All citations use `\citet{}` or `\citep{}` style appropriately
- Multi-author citations correctly use "et al." after first mention
- Year-only citations (e.g., in parenthetical lists) are formatted correctly
- No duplicate citations detected

---

## Summary Assessment

The citation quality is generally good. The 14 published journal article citations are all verified with correct bibliographic details and accurate content representation. The main concern is the incomplete reference for Hood & Raughtigan (2025), which is the paper's primary interlocutor and must be locatable by reviewers. The missing Frazzini & Pedersen (2014) citation for BAB is a notable omission that a finance referee will immediately flag. The Newey & West lag formula attribution is a minor technical inaccuracy (1994 not 1987) that a careful econometrics referee might notice.
