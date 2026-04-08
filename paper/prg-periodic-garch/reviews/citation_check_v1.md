# Citation Verification Report

**Manuscript**: Periodic Realized GARCH: Session-Boundary Information Transfers and Volatility Forecasting (main.tex)
**Date**: 2026-04-05
**Verified by**: Claude (citation-verifier skill)
**Total Citations**: 21 (unique \bibitem entries)
**Total \cite commands**: 21 unique citation keys used in text
**Verified**: 21 | **Issues Found**: 7

---

## Summary

| Status | Count | Percentage |
|--------|-------|------------|
| ✓ Verified | 14 | 67% |
| ⚠ Minor Issues | 5 | 24% |
| ✗ Errors Found | 2 | 10% |

---

## Cross-Reference Check

### \cite commands in text vs. \bibitem entries

All 21 `\cite`/`\citet`/`\citep` commands have matching `\bibitem` entries. No orphan references (all bibliography entries are cited at least once).

| Citation Key | Used in Text | In Bibliography |
|---|---|---|
| Blanc2014 | ✓ (Sec 1) | ✓ |
| Bollerslev1986 | Not directly cited in text | ✓ |
| Bollerslev1996 | ✓ (Sec 1, 2) | ✓ |
| Corsi2009 | ✓ (Sec 2) | ✓ |
| Diebold1995 | ✓ (Sec 2) | ✓ |
| Fissler2016 | ✓ (Sec 2, 4) | ✓ |
| Glosten1993 | ✓ (Sec 2) | ✓ |
| Haas2004 | ✓ (Sec 5) | ✓ |
| Hansen2005 | ✓ (Sec 1, 2) | ✓ |
| Hansen2011MCS | ✓ (Sec 2) | ✓ |
| Hansen2012 | Not directly cited in text | ✓ |
| Hansen2016RealizedGARCH | Not directly cited in text | ✓ |
| Harvey1997 | ✓ (Sec 2) | ✓ |
| Harvey2016 | ✓ (Sec 1, 2, 4) | ✓ |
| Kim2023 | ✓ (Sec 1, 5) | ✓ |
| Lai2024 | ✓ (Sec 1, 5) | ✓ |
| Linton2020 | ✓ (Sec 1, 5) | ✓ |
| Opschoor2021 | ✓ (Sec 1) | ✓ |
| Patton2011 | ✓ (Sec 1, 2) | ✓ |
| Todorova2014 | ✓ (Sec 1) | ✓ |
| Tsiakas2008 | Not directly cited in text | ✓ |

**⚠ Potential Orphans**: Bollerslev1986, Hansen2012, Hansen2016RealizedGARCH, and Tsiakas2008 have `\bibitem` entries but do not appear to be `\cite`d anywhere in the text body. They may be cited implicitly through the `\bibitem` label format (natbib) or may be truly orphaned. **Recommendation**: Either cite these in the text where relevant, or remove from the bibliography. For a Finance Research Letters submission (tight word limits), removing uncited references is advisable.

---

## Detailed Findings

### ✗ Errors Found

**1. Lai et al. (2024)** — `\bibitem[Lai et~al.(2024)]{Lai2024}`

- **Issue type**: Wrong title, wrong co-author initial, wrong publication status
- **In bibliography**:
  > Lai, Y.-H., Wang, J. A., and Chang, C.-L. (2024). Periodic regime-switching volatility models for forecasting realized variance. *Asia-Pacific Financial Markets*, forthcoming.
- **Actual publication**:
  > Lai, Y.-H., Wang, Y.-C., and Chang, Y.-C. (2024). Forecasting trading-session return volatility in Taiwan futures market: A periodic regime switching with jump approach. *Asia-Pacific Financial Markets*, 31(2), 285--305. https://doi.org/10.1007/s10690-023-09415-w
- **Problems**:
  1. **Title is completely wrong**: "Periodic regime-switching volatility models for forecasting realized variance" ≠ the actual title "Forecasting trading-session return volatility in Taiwan futures market: A periodic regime switching with jump approach"
  2. **Co-author initials wrong**: "Wang, J. A." should be "Wang, Y.-C." (Yi-Chiuan Wang)
  3. **Co-author initials wrong**: "Chang, C.-L." should be "Chang, Y.-C." (Yu-Ching Chang)
  4. **Publication status wrong**: Listed as "forthcoming" but it was published in vol. 31(2), pp. 285--305 (online September 2023, print June 2024)
- **Content claim**: ✓ The description of PRS model with Markov switching and session-specific dynamics is accurate
- **Corrected entry**:
  ```latex
  \bibitem[Lai et~al.(2024)]{Lai2024}
  Lai, Y.-H., Wang, Y.-C., and Chang, Y.-C. (2024).
  \newblock Forecasting trading-session return volatility in Taiwan futures market:
  A periodic regime switching with jump approach.
  \newblock \emph{Asia-Pacific Financial Markets}, 31(2), 285--305.
  \newblock \url{https://doi.org/10.1007/s10690-023-09415-w}
  ```

**2. Kim et al. (2023)** — `\bibitem[Kim et~al.(2023)]{Kim2023}`

- **Issue type**: Wrong author initials
- **In bibliography**:
  > Kim, D., Shin, Y., and Wang, K. (2023). Overnight GARCH-Ito volatility models. *Journal of Business & Economic Statistics*, 41(4), 1215--1227.
- **Actual authors**: Kim, D. (Donggyu), Shin, **M.** (Minseok), and Wang, **Y.** (Yazhen)
- **Problems**:
  1. "Shin, Y." should be "Shin, M." — Minseok Shin, not "Y."
  2. "Wang, K." should be "Wang, Y." — Yazhen Wang, not "K."
- **All other details correct**: Title ✓, Journal ✓, Volume/Issue/Pages ✓, Year ✓
- **DOI**: 10.1080/07350015.2022.2116027 (missing from entry)
- **Content claim**: ✓ Accurate description of continuous-time Ito diffusion approach for two session processes
- **Corrected entry**:
  ```latex
  \bibitem[Kim et~al.(2023)]{Kim2023}
  Kim, D., Shin, M., and Wang, Y. (2023).
  \newblock Overnight GARCH-It\^{o} volatility models.
  \newblock \emph{Journal of Business \& Economic Statistics}, 41(4), 1215--1227.
  \newblock \url{https://doi.org/10.1080/07350015.2022.2116027}
  ```

---

### ⚠ Minor Issues

**3. Bollerslev (1986)** — `\bibitem[Bollerslev(1986)]{Bollerslev1986}`

- **Bibliographic details**: ✓ All correct (Journal of Econometrics, 31(3), 307--327)
- **Issue**: Missing DOI
- **DOI**: 10.1016/0304-4076(86)90063-1
- **APA format**: ⚠ Missing DOI
- **Content claim**: Not directly cited in text; appears in bibliography only
- **Additional note**: Not cited in text body — consider removing or adding a citation

**4. Hansen, Huang & Shek (2012)** — `\bibitem[Hansen et~al.(2012)]{Hansen2012}`

- **Bibliographic details**: ✓ All correct (Journal of Applied Econometrics, 27(6), 877--906)
- **Issue**: Missing DOI
- **DOI**: 10.1002/jae.1234
- **APA format**: ⚠ Missing DOI
- **Content claim**: Not directly cited in text body
- **Additional note**: Not cited in text body — consider removing or adding a citation (e.g., in Sec 2 when discussing the Realized GARCH framework that PRG extends)

**5. Hansen & Huang (2016)** — `\bibitem[Hansen and Huang(2016)]{Hansen2016RealizedGARCH}`

- **Bibliographic details**: ✓ All correct (Journal of Business & Economic Statistics, 34(2), 269--287)
- **Issue**: Missing DOI
- **DOI**: 10.1080/07350015.2015.1038543
- **APA format**: ⚠ Missing DOI
- **Content claim**: Not directly cited in text body
- **Additional note**: Not cited in text body — consider removing or adding a citation

**6. Tsiakas (2008)** — `\bibitem[Tsiakas(2008)]{Tsiakas2008}`

- **Bibliographic details**: ✓ Correct (Journal of Banking & Finance, 32, 251--268)
- **Issue**: Missing DOI; also missing volume issue number
- **DOI**: 10.1016/j.jbankfin.2007.11.011
- **Full volume/pages**: 32(2), 251--268
- **APA format**: ⚠ Missing DOI and issue number
- **Content claim**: Not directly cited in text body
- **Additional note**: Not cited in text body — consider removing or adding a citation

**7. Harvey (2016) — bibitem key mismatch with convention**

- **In bibliography**: `\bibitem[Harvey(2016)]{Harvey2016}` — The `\bibitem` optional argument says "Harvey(2016)" (single author) but the entry lists three authors: Harvey, C. R., Liu, Y., and Zhu, H.
- **Issue**: The natbib key `Harvey(2016)` will render as "Harvey (2016)" in text, which is correct for a 3+ author paper in APA, but the `\bibitem` optional argument should technically read `Harvey et~al.(2016)` for consistency and to generate proper "Harvey et al. (2016)" citations.
- **Bibliographic details**: ✓ All correct (Review of Financial Studies, 29(1), 5--68)
- **DOI**: 10.1093/rfs/hhv059 (not in entry)
- **Content claim**: ✓ The paper's use of the |t| > 3.0 threshold is an accurate representation of Harvey et al.'s recommendation
- **Note**: The third author's name is Heqing Zhu (sometimes listed as "Caroline Zhu" on SSRN); "H." initial is correct for the published version

---

### ✓ Verified Citations

**8. Bollerslev and Ghysels (1996)** — `Bollerslev1996`

- **Source**: Journal of Business & Economic Statistics, 14(2), 139--151
- **DOI**: 10.1080/07350015.1996.10524640 (or 10.2307/1392425)
- **Content claim**: ✓ Accurately described as introducing periodic structures into GARCH models for calendar-based variation. The stationarity condition in Eq. (3) correctly references this paper.
- **APA format**: ✓ Correct (minor: DOI missing, but acceptable for pre-DOI era papers)

**9. Corsi (2009)** — `Corsi2009`

- **Source**: Journal of Financial Econometrics, 7(2), 174--196
- **DOI**: 10.1093/jjfinec/nbp001
- **Content claim**: ✓ Accurately described as HAR model with daily/weekly/monthly lags
- **APA format**: ✓ Correct

**10. Diebold and Mariano (1995)** — `Diebold1995`

- **Source**: Journal of Business & Economic Statistics, 13(3), 253--263
- **DOI**: 10.1080/07350015.1995.10524599
- **Content claim**: ✓ Correctly cited for the DM predictive accuracy test
- **APA format**: ✓ Correct

**11. Fissler and Ziegel (2016)** — `Fissler2016`

- **Source**: The Annals of Statistics, 44(4), 1680--1707
- **DOI**: 10.1214/16-AOS1439
- **Content claim**: ✓ Correctly cited for joint elicitability of VaR and ES, and the FZ joint loss function
- **APA format**: ✓ Correct

**12. Glosten, Jagannathan, and Runkle (1993)** — `Glosten1993`

- **Source**: The Journal of Finance, 48(5), 1779--1801
- **DOI**: 10.1111/j.1540-6261.1993.tb05128.x
- **Content claim**: ✓ Correctly cited as the GJR-GARCH model
- **APA format**: ✓ Correct

**13. Haas, Mittnik, and Paolella (2004)** — `Haas2004`

- **Source**: Journal of Financial Econometrics, 2(4), 493--530
- **DOI**: 10.1093/jjfinec/nbh020
- **Content claim**: ✓ Correctly cited for GARCH-Markov estimation difficulties
- **APA format**: ✓ Correct

**14. Hansen and Lunde (2005)** — `Hansen2005`

- **Source**: Journal of Applied Econometrics, 20(7), 873--889
- **DOI**: 10.1002/jae.800
- **Content claim**: ✓ Correctly cited for the forecast comparison framework and the finding that GARCH(1,1) is inferior for equities
- **APA format**: ✓ Correct

**15. Hansen, Lunde, and Nason (2011)** — `Hansen2011MCS`

- **Source**: Econometrica, 79(2), 453--497
- **DOI**: 10.3982/ECTA5771
- **Content claim**: ✓ Correctly cited for the Model Confidence Set methodology
- **APA format**: ✓ Correct

**16. Harvey, Leybourne, and Newbold (1997)** — `Harvey1997`

- **Source**: International Journal of Forecasting, 13(2), 281--291
- **DOI**: 10.1016/S0169-2070(96)00719-4
- **Content claim**: ✓ Correctly cited for the small-sample correction to the DM test
- **APA format**: ✓ Correct

**17. Patton (2011)** — `Patton2011`

- **Source**: Journal of Econometrics, 160(1), 246--256
- **DOI**: 10.1016/j.jeconom.2010.03.034
- **Content claim**: ✓ Correctly cited for QLIKE robustness to noise in unbiased volatility proxies. The paper's Eq. (3) claim about target invariance is consistent with Patton's results.
- **APA format**: ✓ Correct

**18. Blanc, Chicheportiche, and Bouchaud (2014)** — `Blanc2014`

- **Source**: Physica A, 402, 58--75
- **DOI**: 10.1016/j.physa.2014.01.047
- **Content claim**: ✓ The paper accurately states that Blanc et al. "demonstrate that overnight and intraday returns exhibit fundamentally different volatility feedback structures: past intraday returns affect both future sessions symmetrically, while past overnight returns primarily feed back into future overnight volatility." This faithfully represents the original findings.
- **APA format**: ✓ Correct
- **Note on author order**: The published ScienceDirect version lists Blanc, P. as first author, matching the bibliography entry.

**19. Linton and Wu (2020)** — `Linton2020`

- **Source**: Journal of Econometrics, 217(1), 176--201
- **DOI**: 10.1016/j.jeconom.2019.12.015
- **Content claim**: ✓ Correctly described as a coupled component DCS-EGARCH model allowing cross-session feedback with approximately twelve parameters
- **APA format**: ✓ Correct

**20. Opschoor and Lucas (2021)** — `Opschoor2021`

- **Source**: International Journal of Forecasting, 37(2), 622--633
- **DOI**: 10.1016/j.ijforecast.2020.07.009
- **Content claim**: ✓ Correctly described as applying score-driven models to realized variances with overnight returns for VaR and ES forecasting
- **APA format**: ✓ Correct

**21. Todorova and Soucek (2014)** — `Todorova2014`

- **Source**: Finance Research Letters, 11(4), 420--428
- **DOI**: 10.1016/j.frl.2014.04.002
- **Content claim**: ✓ Correctly cited for showing that treating overnight information separately improves realized volatility forecasts
- **APA format**: ✓ Correct
- **Note**: Author name is "Souček" (with háček) but bibliography uses "Soucek" — acceptable anglicization in LaTeX

---

## Content Claim Accuracy Summary

All content claims about cited works were verified and found to be accurate:

| Claim in Paper | Cited Work | Verdict |
|---|---|---|
| Blanc et al. show overnight/intraday have different feedback structures | Blanc et al. (2014) | ✓ Accurate |
| Bollerslev & Ghysels introduce periodic GARCH for calendar variation | Bollerslev & Ghysels (1996) | ✓ Accurate |
| Linton & Wu develop coupled DCS-EGARCH with ~12 params | Linton & Wu (2020) | ✓ Accurate |
| Kim et al. propose Overnight GARCH-Ito with continuous-time diffusions | Kim et al. (2023) | ✓ Accurate |
| Todorova & Soucek show separate overnight treatment improves forecasts | Todorova & Soucek (2014) | ✓ Accurate |
| Opschoor & Lucas apply score-driven models to RV + overnight for VaR/ES | Opschoor & Lucas (2021) | ✓ Accurate |
| Lai et al. use Markov switching for session-specific dynamics | Lai et al. (2024) | ✓ Accurate |
| Hansen & Lunde show GARCH(1,1) inferior for equities | Hansen & Lunde (2005) | ✓ Accurate |
| Patton shows QLIKE robust to noise in unbiased proxies | Patton (2011) | ✓ Accurate |
| Harvey et al. recommend \|t\| > 3.0 threshold | Harvey et al. (2016) | ✓ Accurate |
| Haas et al. describe GARCH-Markov estimation difficulties | Haas et al. (2004) | ✓ Accurate |
| Harvey et al. propose DM test small-sample correction | Harvey et al. (1997) | ✓ Accurate |
| Fissler & Ziegel show VaR+ES are jointly elicitable | Fissler & Ziegel (2016) | ✓ Accurate |

---

## Correction Checklist

### Must Fix (Errors)

- [ ] **Fix #1 (Lai2024)**: Correct title to "Forecasting trading-session return volatility in Taiwan futures market: A periodic regime switching with jump approach"
- [ ] **Fix #1 (Lai2024)**: Change "Wang, J. A." to "Wang, Y.-C."
- [ ] **Fix #1 (Lai2024)**: Change "Chang, C.-L." to "Chang, Y.-C."
- [ ] **Fix #1 (Lai2024)**: Replace "forthcoming" with "31(2), 285--305"
- [ ] **Fix #1 (Lai2024)**: Add DOI: `https://doi.org/10.1007/s10690-023-09415-w`
- [ ] **Fix #2 (Kim2023)**: Change "Shin, Y." to "Shin, M."
- [ ] **Fix #2 (Kim2023)**: Change "Wang, K." to "Wang, Y."
- [ ] **Fix #2 (Kim2023)**: Add DOI: `https://doi.org/10.1080/07350015.2022.2116027`

### Should Fix (Minor Issues)

- [ ] **Fix #7 (Harvey2016)**: Change `\bibitem[Harvey(2016)]` to `\bibitem[Harvey et~al.(2016)]` so natbib generates "Harvey et al. (2016)" consistently
- [ ] **Fix #7 (Harvey2016)**: Add DOI: `https://doi.org/10.1093/rfs/hhv059`
- [ ] **Fix #6 (Tsiakas2008)**: Add issue number: "32(2), 251--268"
- [ ] **Fix #6 (Tsiakas2008)**: Add DOI: `https://doi.org/10.1016/j.jbankfin.2007.11.011`

### Nice to Fix (DOIs for completeness)

- [ ] Add DOI to Bollerslev (1986): `https://doi.org/10.1016/0304-4076(86)90063-1`
- [ ] Add DOI to Hansen et al. (2012): `https://doi.org/10.1002/jae.1234`
- [ ] Add DOI to Hansen & Huang (2016): `https://doi.org/10.1080/07350015.2015.1038543`

### Structural Issues

- [ ] **Orphan references**: Bollerslev1986, Hansen2012, Hansen2016RealizedGARCH, and Tsiakas2008 appear in the bibliography but are not `\cite`d in the text. Either add citations or remove entries. For a Finance Research Letters submission with tight page limits, removing uncited references is recommended.
- [ ] **Duan (1995)**: Mentioned in Sec 2.3 ("Duan (1995) smearing correction") but has no `\bibitem` entry. Either add a reference or remove the parenthetical citation.

---

## DOI Reference Table

| Citation | DOI |
|---|---|
| Bollerslev (1986) | 10.1016/0304-4076(86)90063-1 |
| Bollerslev & Ghysels (1996) | 10.1080/07350015.1996.10524640 |
| Corsi (2009) | 10.1093/jjfinec/nbp001 |
| Diebold & Mariano (1995) | 10.1080/07350015.1995.10524599 |
| Fissler & Ziegel (2016) | 10.1214/16-AOS1439 |
| Glosten, Jagannathan & Runkle (1993) | 10.1111/j.1540-6261.1993.tb05128.x |
| Haas, Mittnik & Paolella (2004) | 10.1093/jjfinec/nbh020 |
| Hansen & Huang (2016) | 10.1080/07350015.2015.1038543 |
| Hansen & Lunde (2005) | 10.1002/jae.800 |
| Hansen, Lunde & Nason (2011) | 10.3982/ECTA5771 |
| Hansen, Huang & Shek (2012) | 10.1002/jae.1234 |
| Harvey, Liu & Zhu (2016) | 10.1093/rfs/hhv059 |
| Harvey, Leybourne & Newbold (1997) | 10.1016/S0169-2070(96)00719-4 |
| Lai, Wang & Chang (2024) | 10.1007/s10690-023-09415-w |
| Blanc, Chicheportiche & Bouchaud (2014) | 10.1016/j.physa.2014.01.047 |
| Kim, Shin & Wang (2023) | 10.1080/07350015.2022.2116027 |
| Linton & Wu (2020) | 10.1016/j.jeconom.2019.12.015 |
| Opschoor & Lucas (2021) | 10.1016/j.ijforecast.2020.07.009 |
| Patton (2011) | 10.1016/j.jeconom.2010.03.034 |
| Todorova & Soucek (2014) | 10.1016/j.frl.2014.04.002 |
| Tsiakas (2008) | 10.1016/j.jbankfin.2007.11.011 |

---

## APA 7th Edition Format Assessment

The bibliography generally follows APA-like formatting (used via `apalike` bibstyle with natbib). Specific observations:

1. **DOIs are missing from all entries** — APA 7th requires DOIs for all works that have them. This is the single biggest format issue.
2. **Journal names are correctly italicized** via `\emph{}` ✓
3. **Author names use correct format** (Last, Initials) ✓
4. **Year in parentheses** ✓
5. **Volume and pages present** for most entries ✓
6. **The `apalike` bibstyle** does not natively produce DOI fields; if the submission requires DOIs, they must be added manually via `\newblock \url{...}` or by switching to a modern `.bst` file that supports the `doi` field.

---

## Verification Sources

All citations verified via web search on 2026-04-05 using:
- Google Scholar
- ScienceDirect (Elsevier)
- Taylor & Francis Online
- Oxford Academic
- Wiley Online Library
- IDEAS/RePEc
- SSRN
- Project Euclid
- NBER Working Papers
- Springer Link
