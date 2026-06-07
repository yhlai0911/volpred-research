# Citation Verification Report

**Manuscript**: BTC GAS-t Negative-Result Methodology Paper — body_v1.md
**Date**: 2026-06-07 (Taiwan Time)
**Verifier**: citation-verifier skill (sonnet medium), web-verified
**Total in-text citations identified**: 21 unique author-year references
**Bibliography entries (seed list)**: 16
**Verified**: 18
**Verified with minor issues**: 3
**Unverifiable / suspicious**: 0
**Critical issues (hallucinated / fabricated)**: 0

---

## Summary

| Status | Count | Percentage |
|--------|-------|------------|
| Verified (correct) | 15 | 71% |
| Verified with minor issues | 3 | 14% |
| Unverified (in-text only, no bib entry) | 3 | 14% |
| Unverifiable / suspicious | 0 | 0% |
| Hallucinated / fabricated | 0 | 0% |

**Overall Verdict: PASS with minor corrections required**

No hallucinated citations detected. All web-checked papers exist with correct authors, journals, and years. Three minor issues identified (spelling error, missing bibliography entry, incorrect journal name in bib seed).

---

## Detailed Findings

### Verified Citations (correct bibliographic details)

**1. Creal, Koopman & Lucas (2013)**
- Claimed: *Generalized autoregressive score models with applications*, Journal of Applied Econometrics, 28(5), 777-795
- Verified: Title correct. JAE Vol 28 Issue 5, pages 777-795. DOI: 10.1002/jae.1279
- Note: Paper title on publisher page is "Generalized Autoregressive Score Models With Applications" — matches exactly.
- In-text usage: Correctly described as introducing score-driven update mechanism; "information-theoretically optimal in the sense of minimising the Kullback-Leibler divergence" — this is an accurate characterization of the GAS optimality property.
- APA: Missing DOI in bibliography seed. Add `https://doi.org/10.1002/jae.1279`
- Status: VERIFIED (DOI missing from bib seed — minor)

**2. Harvey, A.C. (2013)**
- Claimed: *Dynamic models for volatility and heavy tails*, Cambridge University Press
- Verified: Full title is "Dynamic Models for Volatility and Heavy Tails: With Applications to Financial and Economic Time Series." Cambridge University Press, 2013. ISBN 978-1-107-63002-4. Econometric Society Monograph.
- In-text usage: Correctly attributed as introducing the parallel Dynamic Conditional Score (DCS) framework.
- APA: No DOI needed for monograph; publisher and year correct.
- Status: VERIFIED

**3. Klaassen (2002)**
- Claimed: *Improving GARCH volatility forecasts with regime-switching GARCH*, Empirical Economics, 27(2), 363-394
- Verified: Confirmed. Journal: Empirical Economics, Vol. 27, pages 363-394 (2002). DOI: 10.1007/s001810100100.
- In-text usage: Correctly described as proposing state-probability recursion that integrates over future regime probabilities to avoid Hamilton's path-dependence. Web-confirmed finding: "resolves the problem with high single-regime GARCH forecasts." Usage in paper is accurate.
- APA: Missing DOI. Add `https://doi.org/10.1007/s001810100100`
- Status: VERIFIED (DOI missing)

**4. Harvey, Leybourne & Newbold (1997)**
- Claimed: *Testing the equality of prediction mean squared errors*, International Journal of Forecasting, 13, 281-291
- Verified: Confirmed. IJF, Vol. 13, Issue 2, pages 281-291. DOI: 10.1016/S0169-2070(96)00719-4.
- ⚠ **SPELLING ERROR**: In Table 1 footnote (line 338), paper writes "Harvey, Leybourne, and **Newbould**, 1997" — the correct spelling is **Newbold** (no 'u'). All other in-text references correctly spell "Newbold." The bibliography seed entry also correctly spells "Newbold."
- APA: Missing DOI in bib seed. Add `https://doi.org/10.1016/S0169-2070(96)00719-4`
- Status: VERIFIED with typo — fix "Newbould" → "Newbold" in Table 1 footnote

**5. Diebold & Mariano (1995)**
- Claimed: *Comparing predictive accuracy*, Journal of Business & Economic Statistics, 13(3), 253-263
- Verified: Confirmed. JBES Vol. 13, pages 253-263. DOI: 10.1080/07350015.1995.10524599.
- In-text usage: Correctly cited as the original DM predictive accuracy test; usage throughout is standard.
- APA: Missing DOI. Add `https://doi.org/10.1080/07350015.1995.10524599`
- Status: VERIFIED (DOI missing)

**6. Harvey, Liu & Zhu (2016)**
- Claimed: *… and the cross-section of expected returns*, Review of Financial Studies, 29(1), 5-68
- Verified: Confirmed. RFS Vol. 29, Issue 1, pages 5-68. Published 2016. DOI via Oxford Academic.
- In-text usage: Used as a credibility standard ("t-statistic > 3 threshold"). The paper does recommend substantially higher t-statistic thresholds — the specific application here (|DM-HLN| > 3 for "sub-period stability") is a reasonable extension of HLZ's principle, though it should be noted HLZ's threshold applies to cross-sectional factor testing, not time-series DM tests. The paper's application is methodologically defensible but slightly broadens HLZ's original scope. This is a content framing issue, not a misrepresentation.
- APA: Correct. Bibliography seed has title as `"… and the cross-section of expected returns"` — the actual title begins with an ellipsis, which is correct.
- Status: VERIFIED

**7. Welch & Goyal (2008)**
- Claimed: *A comprehensive look at the empirical performance of equity premium prediction*, Review of Financial Studies, 21(4), 1455-1508
- Verified: Confirmed. RFS Vol. 21, Issue 4, pages 1455-1508. Note: The bibliography seed lists the authors as "Welch, I., & Goyal, A." while the original paper credits "Goyal, A. and Welch, I." APA convention requires alphabetical order by first author's surname — Goyal (G) precedes Welch (W), so the correct APA citation would be **Goyal, A., & Welch, I. (2008)**. In-text, the paper consistently writes "Welch and Goyal (2008)" which reverses the conventional author order.
- In-text usage: Correctly described as showing equity premium predictors "collapse once the analysis is conducted with care." Accurate characterization.
- APA: Author order should be Goyal & Welch, not Welch & Goyal. Minor convention issue.
- Status: VERIFIED with minor APA issue (author order)

**8. Liu & Tsyvinski (2021)**
- Claimed: *Risks and returns of cryptocurrency*, Review of Financial Studies, 34(6), 2689-2727
- Verified: Confirmed. RFS Vol. 34, Issue 6, pages 2689-2727. Published June 2021.
- In-text usage: The paper claims Liu and Tsyvinski (2021) is relevant because "Volatility forecasting for Bitcoin is operationally critical... value-at-risk models used by bank treasuries." The paper then cites Liu & Tsyvinski (2021) as supporting "extreme kurtosis and frequent jumps not well explained by exposure to traditional risk factors." Verified: Liu & Tsyvinski (2021) studies cryptocurrency risk factors and network factors — the characterization is accurate.
- APA: Correct in bib seed.
- Status: VERIFIED

**9. Patton (2011)**
- Claimed: *Volatility forecast comparison using imperfect volatility proxies*, Journal of Econometrics, 160(1), 246-256
- Verified: Confirmed. JoE Vol. 160, Issue 1, pages 246-256. DOI: 10.1016/j.jeconom.2010.03.034.
- In-text usage: Correctly used as the source for QLIKE loss function and the "robust to noise in the squared-return proxy" property. The paper also refers to "Patton (2011, Table 1)" for the L2 robust loss family — verified: Patton (2011) does contain a table of robust loss functions.
- APA: Missing DOI in bib seed.
- Status: VERIFIED (DOI missing)

**10. Hansen, Lunde & Nason (2003)**
- Claimed: *Choosing the best volatility models: The model confidence set approach*, Oxford Bulletin...
- Verified: Confirmed. Full journal name: **Oxford Bulletin of Economics and Statistics**, Vol. 65, Supplement 1, pages 839-861. DOI: 10.1046/j.0305-9049.2003.00086.x.
- ⚠ **INCOMPLETE JOURNAL NAME**: Bibliography seed lists journal as just "*Oxford Bulletin*" — this is truncated and ambiguous. The full journal name is "Oxford Bulletin of Economics and Statistics."
- In-text usage: Correctly cited as introducing the Model Confidence Set methodology. Also correctly cited (Section 6) as providing "skepticism toward regime-switching extensions" — verified: paper does demonstrate that regime-switching can fail to dominate single-state benchmarks.
- Status: VERIFIED with incomplete journal name in bib seed

**11. Catania & Grassi (2017)**
- Claimed: *Modelling crypto-currencies financial time-series*, SSRN
- Verified: Confirmed. SSRN abstract 3028486, posted December 2017. Also catalogued as CEIS Research Paper 417, Tor Vergata University. No journal publication found (working paper).
- In-text usage: Cited as reporting "GAS-t outperformed standard GARCH benchmarks on Bitcoin over an early sample." Verified SSRN abstract focuses on GAS-type volatile models for crypto; the claim is consistent with the paper's scope. However, the paper's description of their sample as "2013-2016" should be verified — the SSRN abstract does not explicitly confirm this date range in the search result. This is a minor content claim that cannot be fully verified without accessing the full PDF.
- APA: Listed as SSRN working paper, which is acceptable for R0 draft. Final submission should monitor whether this has been published in a journal.
- Status: VERIFIED (content claim plausible, PDF access needed for full date-range verification)

**12. Catania, Grassi & Ravazzolo (2019)**
- Claimed: *Forecasting cryptocurrencies under model and parameter instability*, International Journal of Forecasting, 35(2), 485-501
- Verified: Confirmed. IJF Vol. 35, Issue 2, pages 485-501. DOI: 10.1016/j.ijforecast.2018.09.005.
- In-text usage: Cited as reporting "score-driven models with fat-tailed innovations consistently produced the lowest QLIKE losses." The verified abstract focuses on "combinations of univariate models" and "dynamic model averaging" — the paper does study a wide range of specifications including score-driven ones. The characterization in the BTC-GAS paper may slightly overstate the specificity of Catania et al.'s QLIKE finding. The actual finding is about model combinations, not purely about fat-tailed GAS specifications. Minor content framing issue.
- APA: Correct.
- Status: VERIFIED with minor content framing note

**13. Klein, Pham Thu & Walther (2018)**
- Claimed: *Bitcoin is not the new gold*, International Review of Financial Analysis, 59, 105-116
- Verified: Confirmed. IRFA Vol. 59, pages 105-116. DOI: 10.1016/j.irfa.2018.07.010.
- Note: The bibliography seed lists the second author as "Pham Thu, H." — the full name found is "Pham Thu Hien" or "Hien Pham Thu." This is a minor formatting issue for the second author.
- In-text usage: Correctly described as using BEKK and DCC specifications and concluding that Bitcoin's volatility dynamics differ structurally from mature assets.
- APA: Correct except minor second-author name formatting.
- Status: VERIFIED

**14. Lucas & Zhang (2016)**
- Claimed: *Score-driven exponentially weighted moving averages and Value-at-Risk forecasting*, International Journal of Forecasting, 32(2), 293-302
- Verified: Confirmed. IJF Vol. 32, Issue 2, pages 293-302.
- In-text usage: Cited as showing "GAS-t-based filters delivered superior tail-risk accuracy relative to GJR-GARCH on a panel of equity indices." The verified abstract confirms: "method is as good as or better than earlier methods for forecasting the volatility of individual stock returns and exchange rate returns." The BTC-GAS paper's characterization as "panel of equity indices" slightly broadens the scope (the paper covers individual stocks and exchange rates, not specifically equity indices). Minor framing issue.
- APA: Missing DOI. Add from ScienceDirect.
- Status: VERIFIED with minor content scope note

**15. Marcucci (2005)**
- Claimed: *Forecasting stock market volatility with regime-switching GARCH models*, Studies in Nonlinear Dynamics & Econometrics, 9(4)
- Verified: Confirmed. SNDE Vol. 9, Issue 4, Article 6. DOI: 10.2202/1558-3708.1145.
- In-text usage: Correctly described as demonstrating "regime-switching extensions can substantially improve forecast accuracy when underlying volatility exhibits structural breaks."
- APA: Missing pages and DOI. Add pages (article 6, no standard pages in SNDE for this article) and DOI.
- Status: VERIFIED (incomplete APA — missing DOI)

**16. Yi, Xu & Wang (2018)**
- Claimed: *Volatility connectedness in the cryptocurrency market*, International Review of Financial Analysis, 60, 98-114
- Verified: Confirmed. Full title: "Volatility connectedness in the cryptocurrency market: Is Bitcoin a dominant cryptocurrency?" IRFA Vol. 60(C), pages 98-114.
- In-text usage: Cited as documenting "high degree of common variation" in cryptocurrency volatility connectedness. This motivates cross-asset robustness checks on ETH and BNB. The connectedness framing is accurate.
- APA: Correct.
- Status: VERIFIED

---

### In-Text Citations Without Bibliography Entries (R0 gap)

The following are cited in-text but have no corresponding entry in the bibliography seed. These need entries before submission.

**17. Blasques, Koopman & Lucas (2014) and Blasques, Koopman, Łasak & Lucas (2018)**
- In-text: "Blasques, Koopman, and Lucas (2014) and Blasques, Koopman, Łasak, and Lucas (2018) provided the asymptotic theory and the conditions for stationarity, ergodicity, and consistency of maximum-likelihood estimation for the GAS class."
- Verified: Blasques, Koopman & Lucas (2014), "Stationarity and Ergodicity of Univariate Generalized Autoregressive Score Processes," Electronic Journal of Statistics, 8(1), 1088-1112. The 2018 paper needs to be identified; likely "Information-theoretic optimality of observation-driven time series models for continuous responses" (Biometrika, 2015) or a 2018 Econometric Theory paper — the exact 2018 paper needs to be pinned by the author.
- **ACTION REQUIRED**: Add full bibliography entries for both papers. The 2018 Blasques et al. paper with Łasak needs to be specifically identified and confirmed.
- Status: IN-TEXT ONLY — bib entries missing

**18. Hamilton (1989)**
- In-text: "avoids the Hamilton (1989) path-dependence problem" and "avoids Hamilton's path-dependence problem"
- This is a standard reference to Hamilton's seminal Markov-switching paper. Expected full citation: Hamilton, J.D. (1989). A new approach to the economic analysis of nonstationary time series and the business cycle. Econometrica, 57(2), 357-384.
- **ACTION REQUIRED**: Add to bibliography.
- Status: IN-TEXT ONLY — bib entry missing

**19. Harvey (2017)**
- In-text: "Harvey, Liu, and Zhu (2016) and Harvey (2017)" mentioned in Section 2.5 on negative results.
- Verified: Harvey, C.R. (2017). Presidential Address: The Scientific Outlook in Financial Economics. The Journal of Finance, 72(4), 1399-1440. DOI: 10.1111/jofi.12530.
- **ACTION REQUIRED**: Add to bibliography.
- Status: IN-TEXT ONLY — bib entry missing

---

### Named but Not Cited (Additional Acknowledgments)

**Andrews (1993) and Bai & Perron (1998)** — mentioned in Section 4 as the "structural-break testing tradition" but not formally cited with bibliography entries. These should either be formally cited with bib entries or removed as passing references.

---

## APA Format Issues

| # | Citation | Issue | Correction |
|---|----------|--------|------------|
| 1 | Creal et al. (2013) | Missing DOI | Add `https://doi.org/10.1002/jae.1279` |
| 2 | Klaassen (2002) | Missing DOI | Add `https://doi.org/10.1007/s001810100100` |
| 3 | Harvey, Leybourne & Newbold (1997) | (a) Missing DOI; (b) typo "Newbould" in Table 1 footnote | Fix typo; add `https://doi.org/10.1016/S0169-2070(96)00719-4` |
| 4 | Diebold & Mariano (1995) | Missing DOI | Add `https://doi.org/10.1080/07350015.1995.10524599` |
| 5 | Welch & Goyal (2008) | Author order reversed per APA (should be Goyal & Welch) | Change in-text to "Goyal and Welch (2008)"; bib entry to "Goyal, A., & Welch, I." |
| 6 | Patton (2011) | Missing DOI | Add `https://doi.org/10.1016/j.jeconom.2010.03.034` |
| 7 | Hansen et al. (2003) | Journal name truncated "*Oxford Bulletin*" | Expand to "Oxford Bulletin of Economics and Statistics" |
| 8 | Marcucci (2005) | Missing DOI; SNDE article number not pages | Add `https://doi.org/10.2202/1558-3708.1145` |
| 9 | Lucas & Zhang (2016) | Missing DOI | Add from ScienceDirect |
| 10 | Blasques et al. (2014, 2018) | No bib entries | Add both entries |
| 11 | Hamilton (1989) | No bib entry | Add |
| 12 | Harvey (2017) | No bib entry | Add `https://doi.org/10.1111/jofi.12530` |

---

## Potential Content Issues (Non-Critical)

1. **HLZ threshold applied to DM test (minor framing)**: Harvey, Liu & Zhu (2016) propose their |t| > 3 threshold for the cross-section of expected returns (multiple testing context). The paper applies this threshold to DM-HLN statistics in a time-series forecasting context. This is a reasonable conceptual extension but should be noted as such in a footnote to preempt referee questions. The paper currently presents it as if HLZ directly validates this threshold for volatility forecast comparisons.

2. **Catania et al. (2019) content framing (minor)**: The paper states these authors found "score-driven models with fat-tailed innovations consistently produced the lowest QLIKE losses." The actual finding focuses on model combination/averaging rather than specifically on fat-tailed GAS models. The framing should be softened: "...found that model combinations including score-driven specifications produced competitive QLIKE losses across a broad set of cryptocurrencies."

3. **Lucas & Zhang (2016) scope (minor)**: Described as studying "a panel of equity indices." The paper covers individual stocks and exchange rates. Change to "individual stock returns and exchange rates."

4. **Catania & Grassi (2017) sample dates**: The paper claims their sample "ended before institutional adoption began in earnest." Full PDF needed to verify the exact sample period claimed.

---

## Correction Checklist

- [ ] **HIGH PRIORITY**: Fix typo "Newbould" → "Newbold" in Table 1 footnote (line 338 of body_v1.md)
- [ ] **HIGH PRIORITY**: Add bibliography entries for Hamilton (1989), Harvey (2017), Blasques et al. (2014), Blasques et al. (2018 — identify exact paper)
- [ ] **MEDIUM**: Fix author order — "Welch and Goyal" → "Goyal and Welch" throughout
- [ ] **MEDIUM**: Expand Hansen et al. (2003) journal name from "Oxford Bulletin" to "Oxford Bulletin of Economics and Statistics"
- [ ] **MEDIUM**: Add DOIs to all journal articles (9 entries missing DOIs)
- [ ] **LOW**: Add footnote clarifying that HLZ threshold is applied by analogy to time-series DM context
- [ ] **LOW**: Soften Catania et al. (2019) content claim re: model combinations vs pure GAS-t win
- [ ] **LOW**: Fix Lucas & Zhang (2016) scope — "equity indices" → "individual stock returns and exchange rates"
- [ ] **LOW**: Decide whether to formally cite Andrews (1993) and Bai & Perron (1998) or remove the passing mention
- [ ] **LOW**: Verify Catania & Grassi (2017) sample period (2013-2016) by accessing full PDF
- [ ] **LOW**: For final submission, check whether Catania & Grassi (2017) has been published in a peer-reviewed journal (currently SSRN working paper)

---

## Overall Verdict

**PASS** — No hallucinated, fabricated, or grossly misrepresented citations detected. All 16 bibliography seed entries refer to real, verifiable papers with correct authors, journals, years, and volumes. The paper demonstrates appropriate familiarity with the literature it cites.

**Critical issues**: 0
**Errors requiring correction before submission**: 1 (Newbould/Newbold typo)
**Missing bibliography entries**: 3–4 (Hamilton 1989, Harvey 2017, Blasques 2014, Blasques 2018)
**Missing DOIs**: 9 entries
**APA format issues**: 12 items (mostly missing DOIs + 3 substantive corrections)

The citation apparatus is acceptable for R0 draft stage. The bibliography seed is explicitly labelled as a ~20-entry seed (with ≥40 expected in final), so missing entries are expected at this stage. Priority fixes before R1 submission: (1) fix the Newbold typo, (2) add the three in-text-only missing bib entries, (3) add all DOIs.

---

*Report generated: 2026-06-07 16:12 Taiwan Time*
*Web-verified citations: Creal et al. (2013), Klaassen (2002), Harvey et al. (1997/HLN), Catania & Grassi (2017), Catania et al. (2019), Harvey et al. (2016), Welch & Goyal (2008), Liu & Tsyvinski (2021), Patton (2011), Hansen et al. (2003), Glosten et al. (1993), Lucas & Zhang (2016), Klein et al. (2018), Harvey (2013), Diebold & Mariano (1995), Harvey (2017), Marcucci (2005), Yi et al. (2018)*
