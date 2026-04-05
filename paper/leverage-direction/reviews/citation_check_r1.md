# Citation Verification Report R1

**Manuscript**: Leverage Direction Matters (main_v2.tex + body_v2.tex)
**Date**: 2026-04-05
**Total Citations**: 54
**Verified via WebSearch**: 12 key citations
**Issues Found**: 3

---

## Summary

| Status | Count | Percentage |
|--------|-------|------------|
| Verified | 9 | 75% |
| Minor Issues | 1 | 8.3% |
| Content Mismatch | 2 | 16.7% |

*Note: Only 12 of 54 citations were web-searched (the most recent, unusual, or potentially problematic ones). Classic references (Bollerslev 1986, Engle 2002, etc.) were spot-checked but not fully web-verified.*

---

## Detailed Findings

### Verified Citations

**1. Hood and Raughtigan (2025)**
- Bibkey: `hood2025`
- Source: Journal of Portfolio Management, early access (published 2025-09-08)
- DOI: https://doi.org/10.3905/jpm.2025.1.764
- SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4773781
- Content claim: "equity VT alpha arises primarily from implicit trend-following via the leverage effect" -- **ACCURATE**. The paper explicitly finds that VT alpha loads on trend following due to the leverage effect, and that this is equity-specific (not present for commodities/bonds/currencies).
- APA format: Correct
- **Status: VERIFIED**

**2. DeMiguel, Martin-Utrera, and Uppal (2024)**
- Bibkey: `demiguel2024`
- Source: Journal of Finance, 79(6), 3859-3891
- DOI: https://doi.org/10.1111/jofi.13395
- Content claim: "achieve 13% Sharpe improvement via a hybrid implied-realized framework" -- **CONTENT MISMATCH**
  - The 13% Sharpe improvement figure is correct (verified from abstract/summary)
  - However, the method is a "conditional multifactor portfolio" NOT a "hybrid implied-realized framework"
  - The paper proposes using conditional mean-variance optimization that accounts for time-varying volatility, NOT a hybrid of implied and realized volatility
- APA format: Correct
- **Status: CONTENT MISMATCH** -- Fix "hybrid implied-realized framework" to "conditional multifactor portfolio"

**3. Xu (2024)**
- Bibkey: `xu2024`
- Source: Critical Finance Review, forthcoming
- PDF: https://cfr.ivo-welch.info/forthcoming/papers/xu2024improving.pdf
- Content claim: "validates real-time viability across 197 equity factors" -- **ACCURATE**. The paper tests on 197 risk factors and anomaly portfolios.
- APA format: Author first name is "Xia" not "Y." -- paper has "Xu, Y." which is incorrect if author is Xia Xu.
- **Status: VERIFIED** (minor: check author first initial)

**4. Bozovic (2024)**
- Bibkey: `bozovic2024`
- Source: International Review of Financial Analysis, 95, 103353
- DOI: https://doi.org/10.1016/j.irfa.2024.103353
- Content claim: "confirms VIX dominance through forward-looking information" -- **ACCURATE**. The paper demonstrates VIX-based portfolio management outperforms realized-volatility approaches due to forward-looking information in implied volatility.
- APA format: Author first name is Milos (Bozovic, M.) -- paper has correct format.
- **Status: VERIFIED**

**5. Cederburg, O'Doherty, Wang, and Yan (2020)**
- Bibkey: `cederburg2020`
- Source: Journal of Financial Economics, 138(1), 95-117
- DOI: https://doi.org/10.1016/j.jfineco.2020.04.015
- Content claim in manuscript: "show that using VIX as the scaling signal produces approximately 4.9% alpha versus realized-variance scaling" -- **POTENTIALLY MISATTRIBUTED**
  - The paper's main finding is NEGATIVE: VT does NOT systematically outperform out-of-sample
  - The 4.9% alpha figure could not be found in publicly available summaries of this paper
  - This figure may come from Bozovic (2024) or from a specific table within Cederburg et al. that the abstract does not highlight
  - The citation context gives the impression that Cederburg et al. support VIX-based VT, when their overall conclusion is skeptical
- APA format: Correct
- **Status: CONTENT MISMATCH** -- Verify the 4.9% figure. If it exists in the paper, add context that the overall finding is negative for VT. If it's from another source, correct attribution.

**6. Chevallier and Ielpo (2017)**
- Bibkey: `chevallier2017`
- Source: Research in International Business and Finance, 39, 763-778
- DOI: https://doi.org/10.1016/j.ribaf.2014.09.010
- Note: DOI registered 2014 (online first), print publication 2017
- Content claim: "find that gold, wheat, coffee, and cocoa exhibit inverted asymmetric volatility" -- **ACCURATE**
- APA format: Correct
- **Status: VERIFIED**

**7. Chang, Kung, Chen, and Tian (2021)**
- Bibkey: `chang2021`
- Source: Pacific-Basin Finance Journal, 67, 101522
- DOI: https://doi.org/10.1016/j.pacfin.2021.101522
- Content claim: "use a Markov-switching GJR-GARCH to link gold's inverted asymmetry to high-volatility regimes" -- **ACCURATE**. Paper finds inverted asymmetric volatility associated with high-volatility regime.
- APA format: Authors are Chang, M.-S., Kung, C.-C., Chen, M.-W., & Tian, Y. -- Correct.
- **Status: VERIFIED**

**8. Harri and Brorsen (2009)**
- Bibkey: `harri2009`
- Source: Quantitative and Qualitative Analysis in Social Sciences, 3(3), 78-115
- SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=76460
- Content claim: "overlapping observations inflate the effective sample size" -- **ACCURATE**. Paper discusses MA error from overlap and bias in naive t-statistics.
- APA format: Correct
- **Status: VERIFIED**

**9. Nelson (2025)**
- Bibkey: `nelson2025`
- Source: SSRN Working Paper No. 5931154
- URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5931154
- Author: Ryan Nelson (posted December 15, 2025)
- Content claim: "characterization of volatility scaling as non-predictive risk control" -- Plausible from the abstract (AAM framework for downside risk mitigation), though the specific phrase "non-predictive risk control" should be verified in the full text.
- APA format: Correct
- **Status: VERIFIED** (with caveat: verify specific claim in full text)

**10. Moreira and Muir (2017)**
- Bibkey: `moreira2017`
- Source: Journal of Finance, 72(4), 1611-1644
- DOI: https://doi.org/10.1111/jofi.12513
- Content claims: Multiple claims throughout, all standard characterizations of the VT framework.
- **Status: VERIFIED**

**11. Patton (2011)**
- Bibkey: `patton2011`
- Source: Journal of Econometrics, 160(1), 246-256
- DOI: https://doi.org/10.1016/j.jeconom.2010.03.034
- Content claims: QLIKE proxy-robustness. Standard and accurate.
- **Status: VERIFIED**

**12. Harvey, Liu, and Zhu (2016)**
- Bibkey: `harvey2016`
- Source: Review of Financial Studies, 29(1), 5-68
- DOI: https://doi.org/10.1093/rfs/hhv059
- Content claim: t > 3.0 threshold for multiple testing. Standard and accurate.
- **Status: VERIFIED**

---

## Correction Checklist

- [ ] **C1**: Fix DeMiguel et al. (2024) characterization: "hybrid implied-realized framework" should be "conditional multifactor portfolio" (body_v2.tex, line 46, Section 2.4)
- [ ] **C2**: Verify Cederburg et al. (2020) "4.9% alpha" figure attribution. If from this paper, add context that overall finding is negative for VT. If from Bozovic (2024) or another source, correct attribution. (body_v2.tex, line 46, Section 2.4)
- [ ] **C3**: Check Xu (2024) author first initial: "Y." vs "Xia" (main_v2.tex bibliography)
- [ ] **C4**: Standardize Campbell et al. (2017) bibitem format to match other entries (main_v2.tex, line 225-227)
- [ ] **C5**: Verify Nelson (2025) "non-predictive risk control" claim against full text

---

## References Not Web-Searched (Spot-Checked Only)

The following classic references were not web-searched but are well-known and unlikely to have issues:

- Bollerslev (1986), (1987) -- Standard GARCH references
- Nelson (1991) -- EGARCH
- Glosten, Jagannathan, Runkle (1993) -- GJR-GARCH
- Black (1976), Christie (1982) -- Original leverage effect
- Diebold and Mariano (1995) -- DM test
- Kupiec (1995), Christoffersen (1998) -- VaR backtesting
- Hansen and Lunde (2005) -- GARCH comparison
- Newey and West (1987) -- HAC
- Engle (2002), (2004) -- DCC, Nobel lecture
- Henriksson and Merton (1981) -- Market timing
- Treynor and Mazuy (1966) -- Quadratic timing
- Baur and Lucey (2010), Baur and McDermott (2010) -- Gold safe haven
- McNeil, Frey, and Embrechts (2015) -- QRM textbook
- Fleming, Kirby, and Ostdiek (2001, 2003) -- Volatility timing
- Corsi (2009) -- HAR model
- Longin and Solnik (2001) -- Extreme correlations

---

## Missing References (Recommended Additions)

1. **Bekaert, G., & Wu, G. (2000)**. Asymmetric volatility and risk in equity markets. *Review of Financial Studies*, 13(1), 1-42. https://doi.org/10.1093/rfs/13.1.1
   - Essential for Section 5.1 economic interpretation of leverage effect vs. volatility feedback

2. **Figlewski, S., & Wang, X. (2000)**. Is the "Leverage Effect" a Leverage Effect? Working paper, NYU Stern.
   - Challenges the capital-structure interpretation of leverage that the paper adopts from Christie (1982)

3. **Bollerslev, T., Litvinova, J., & Tauchen, G. (2006)**. Leverage and volatility feedback effects in high-frequency data. *Journal of Financial Econometrics*, 4(3), 353-384.
   - High-frequency evidence on the leverage mechanism, relevant to discussion

4. **Acerbi, C., & Szekely, B. (2014)**. Back-testing expected shortfall. *Risk*, 27(11), 76-81.
   - Needed if ES backtesting is added per review recommendation

---

*Report generated by Claude Opus 4.6 (1M context), 2026-04-05.*
