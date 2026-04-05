# Citation Verification Report

**Manuscript**: When Volatility Targeting Crowds: Quantifying the Tipping Point via Agent-Based Simulation
**Date**: 2026-04-05
**Total Citations**: 11
**Verified**: 8 | **Minor Issues**: 2 | **Errors Found**: 1

---

## Summary

| Status | Count | Percentage |
|--------|-------|------------|
| ✓ Verified | 8 | 73% |
| ⚠ Minor Issues | 2 | 18% |
| ✗ Errors Found | 1 | 9% |

---

## Detailed Findings

### ✓ Verified Citations

**1. Moreira and Muir (2017)**
- Bib entry: `moreira2017`
- Source: *Journal of Finance*, 72(4), 1611--1644
- DOI: https://doi.org/10.1111/jofi.12513
- Bibliographic accuracy: ✓ Authors, year, title, journal, volume, issue, pages all correct
- Content claim: Manuscript states they "formalized" VT as $w_t = \sigma^*/\hat{\sigma}_t$. ✓ Accurate -- this is the canonical VT formulation from the paper
- APA format: ✓ Correct

**2. Harvey et al. (2018)**
- Bib entry: `harvey2018`
- Source: *Journal of Portfolio Management*, 45(1), 14--33
- DOI: https://doi.org/10.3905/jpm.2018.45.1.014
- Bibliographic accuracy: ✓ All six authors (Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, Van Hemert), year, title, journal, volume, issue, pages all correct
- Content claim: Manuscript says they "demonstrate that such strategies meaningfully reduce tail risk across asset classes." ✓ Accurate -- the paper shows VT reduces extreme return likelihood, particularly left-tail events, across multiple asset classes
- APA format: ✓ Correct

**3. Baltas (2019)**
- Bib entry: `baltas2019`
- Source: *Financial Analysts Journal*, 75(3), 89--104
- DOI: https://doi.org/10.1080/0015198X.2019.1600955
- Bibliographic accuracy: ✓ Author, year, title, journal, volume, issue, pages all correct
- Content claim: Manuscript states Baltas "document[s] crowding effects in alternative risk premia." ✓ Accurate -- the paper introduces a crowding framework for alternative risk premia (momentum, value, etc.)
- Note: The paper focuses on crowding in alternative risk premia (momentum, value, carry) rather than VT specifically, but the manuscript's characterization as "focused on other strategy types" (Section 1) is accurate and appropriate
- APA format: ✓ Correct

**4. Gennotte and Leland (1990)**
- Bib entry: `gennotte1990`
- Source: *American Economic Review*, 80(5), 999--1021
- Bibliographic accuracy: ✓ Authors, year, title, journal, volume, issue, pages all correct
- Content claim: Manuscript draws "parallels to the portfolio insurance strategies implicated in the 1987 crash." ✓ Accurate -- the paper develops a rational expectations model showing how hedging (portfolio insurance) strategies could cause crashes even with relatively small selling, directly relevant to the 1987 crash
- APA format: ✓ Correct

**5. Brunnermeier and Pedersen (2009)**
- Bib entry: `brunnermeier2009`
- Source: *Review of Financial Studies*, 22(6), 2201--2238
- DOI: https://doi.org/10.1093/rfs/hhn098
- Bibliographic accuracy: ✓ Authors, year, title, journal, volume, issue, pages all correct
- Content claim: Manuscript attributes "loss spiral" / "liquidity spiral" framework to this paper and encodes it in the ABM. ✓ Accurate -- the paper models mutually reinforcing liquidity spirals where market liquidity and funding liquidity feed back on each other
- APA format: ✓ Correct

**6. Harvey, Liu, and Zhu (2016)**
- Bib entry: `harvey2016`
- Source: *Review of Financial Studies*, 29(1), 5--68
- DOI: https://doi.org/10.1093/rfs/hhv059
- Bibliographic accuracy: ✓ Authors (Harvey, C.R., Liu, Y., Zhu, H.), year, title ("...and the Cross-Section of Expected Returns"), journal, volume, issue, pages all correct. Note: third author's first name is Heqing (not just "H." in the bib entry, but initials are standard)
- Content claim: Manuscript uses their $|t| > 3.0$ threshold for statistical significance. ✓ Accurate -- the paper proposes that new factors need t-ratios exceeding 3.0 given extensive data mining in the cross-section literature
- APA format: ✓ Correct

**7. Kyle (1985)**
- Bib entry: `kyle1985`
- Source: *Econometrica*, 53(6), 1315--1335
- Bibliographic accuracy: ✓ Author, year, title, journal, volume, issue, pages all correct (some sources cite the final page as 1336 rather than 1335; both appear in standard references; the difference is negligible)
- Content claim: Manuscript uses a "simplified Kyle (1985) model" for price formation with lambda (price impact). ✓ Accurate -- Kyle's model introduces the concept of market maker pricing with informed trader impact (Kyle's lambda)
- APA format: ✓ Correct

**8. Bookstaber, Paddrik, and Tivnan (2014)**
- Bib entry: `bookstaber2014`
- Source: OFR Working Paper 14-05, Office of Financial Research
- Bibliographic accuracy: ✓ Authors, year, title, and working paper designation all correct. Note: later published as journal article in *Journal of Economic Interaction and Coordination*, 13, 433--466 (2018)
- Content claim: Manuscript states they "use agent-based modeling to study financial system fragility but do not specifically examine VT crowding." ✓ Accurate -- the paper models fire sales and financial vulnerability via ABM but does not address volatility targeting
- APA format: ✓ Correct

---

### ⚠ Minor Issues

**9. European Central Bank (2020)**
- Bib entry: `ecb2020`
- Source: *Financial Stability Review*, May 2020
- Bibliographic accuracy: ⚠ The bib entry title is "Procyclicality of volatility targeting strategies." However, the actual title of the ECB box/chapter is **"Volatility-targeting strategies and the market sell-off"** (ECB FSR May 2020, Box 2). The title used in the bibliography does not match the actual publication title.
- Content claim: Manuscript says ECB "explicitly flagged VT procyclicality as a source of market fragility." ✓ Accurate -- the ECB box discusses how VT strategies create procyclical selling pressure and may have amplified the March 2020 sell-off
- APA format: ⚠ Title should be corrected to match the actual publication
- **Recommendation**: Change the bibliography title from "Procyclicality of volatility targeting strategies" to "Volatility-targeting strategies and the market sell-off"
- Verified source: https://www.ecb.europa.eu/press/financial-stability-publications/fsr/focus/2020/html/ecb.fsrbox202005_02~f6616db9be.en.html

**10. Perchet et al. (2015) / cited as `perchet2016`**
- Bib entry: `perchet2016` (cite key says 2016, bib entry says 2015)
- Source listed in bib: *Journal of Alternative Investments*, 18(3), 48--64
- Bibliographic accuracy: ⚠ **Multiple discrepancies found**:
  1. **Title mismatch**: The bib entry title is "Inter- and intra-asset diversification in risk-based portfolios with the 1/VIX rule." However, the actual published paper by these four authors in JAI 18(3) is titled **"Predicting the Success of Volatility Targeting Strategies: Application to Equities and Other Asset Classes"** (JAI, 18(3), 21--38, Winter 2015). The title in the bibliography does not appear to correspond to any published work by these authors that could be found via web search.
  2. **Page numbers**: JAI 18(3) lists this paper at pages **21--38**, not 48--64 as stated in the bibliography.
  3. **Cite key inconsistency**: The cite key is `perchet2016` but the year in the bib entry is 2015. The paper was published in Winter 2015 (the "2016" in the DOI `10.3905/jai.2016.18.3.021` reflects the DOI assignment convention, not the publication year).
- Content claim: Manuscript cites this as a "widely-used practitioner heuristic" for the 12/VIX rule. ⚠ **Needs verification** -- the published paper ("Predicting the Success of Volatility Targeting Strategies") does discuss volatility targeting and the 1/vol concept, and may discuss 1/VIX as a special case, but the cited title "Inter- and intra-asset diversification...with the 1/VIX rule" could not be independently verified as a standalone publication. It is possible this title refers to a different version (working paper or presentation) that differs from the published JAI version.
- **Recommendation**: 
  - Correct the title to: "Predicting the success of volatility targeting strategies: Application to equities and other asset classes"
  - Correct the pages to: 18(3), 21--38
  - Decide on year: use 2015 (actual publication) and update cite key to `perchet2015`
  - Alternatively, if the "Inter- and intra-asset diversification" title refers to a specific working paper version, add the working paper source (e.g., SSRN) and distinguish it from the published version

---

### ✗ Errors Found

**11. Bouchaud et al. (2018) -- Content Attribution Error**
- Bib entry: `bouchaud2018`
- Source: *Trades, Quotes and Prices: Financial Markets Under the Microscope*, Cambridge University Press
- Bibliographic accuracy: ✓ Authors (Bouchaud, Bonart, Donier, Gould), year (2018), title, publisher all correct
- ISBN: 978-1-107-15605-0
- Content claim: ✗ **Misattribution of the USD 2 trillion figure**. The manuscript states: "Industry estimates suggest that short-volatility and volatility-sensitive strategies collectively manage over USD 2 trillion in assets (Bouchaud et al., 2018)." However:
  - **The USD 2 trillion estimate originates from Christopher Cole / Artemis Capital Management** (2017 paper "Volatility and the Alchemy of Risk"), not from Bouchaud et al.
  - **Bouchaud et al. (2018)** is a textbook on market microstructure (limit order books, price impact, market dynamics) and does not focus on volatility strategy AUM estimates.
  - The ECB Financial Stability Review (May 2020) also cites USD 2 trillion for volatility-sensitive strategies but attributes it to industry estimates, not to Bouchaud.
  - Extensive web search found no connection between the Bouchaud et al. book and the USD 2 trillion figure.
- **Recommendation**: Either:
  - (a) Re-attribute to the correct source: Cole, C. (2017). Volatility and the Alchemy of Risk. Artemis Capital Management. Or cite the ECB (2020) FSR which also mentions this figure.
  - (b) If the figure genuinely appears in Bouchaud et al. (2018), provide the specific page number to allow verification.
  - (c) Remove the specific dollar figure and use a more general characterization of widespread VT adoption.
- Verified sources: 
  - Artemis Capital: https://caia.org/sites/default/files/03_volatility_4-2-18.pdf
  - ECB FSR May 2020: https://www.ecb.europa.eu/press/financial-stability-publications/fsr/focus/2020/html/ecb.fsrbox202005_02~f6616db9be.en.html

---

## Correction Checklist

- [ ] **Fix #11 (ERROR)**: The USD 2 trillion AUM claim attributed to `\citep{bouchaud2018}` appears to originate from Artemis Capital (Cole, 2017) or ECB (2020), not from the Bouchaud market microstructure textbook. Re-attribute or remove.
- [ ] **Fix #9**: Change ECB (2020) bibliography title from "Procyclicality of volatility targeting strategies" to "Volatility-targeting strategies and the market sell-off" to match the actual ECB FSR May 2020 box title.
- [ ] **Fix #10**: Perchet et al. bibliography entry has wrong title ("Inter- and intra-asset diversification...") and wrong pages (48--64). The published paper in JAI 18(3) is titled "Predicting the Success of Volatility Targeting Strategies: Application to Equities and Other Asset Classes" with pages 21--38. Also resolve the 2015 vs. 2016 year discrepancy and update the cite key.

---

## Verified Reference List (with corrections applied)

```bibtex
@article{baltas2019,
  author  = {Baltas, Nick},
  title   = {The Impact of Crowding in Alternative Risk Premia Investing},
  journal = {Financial Analysts Journal},
  year    = {2019},
  volume  = {75},
  number  = {3},
  pages   = {89--104},
  doi     = {10.1080/0015198X.2019.1600955}
}

@techreport{bookstaber2014,
  author      = {Bookstaber, Rick and Paddrik, Mark and Tivnan, Brian},
  title       = {An Agent-Based Model for Financial Vulnerability},
  institution = {Office of Financial Research},
  year        = {2014},
  type        = {Working Paper},
  number      = {14-05}
}

@book{bouchaud2018,
  author    = {Bouchaud, Jean-Philippe and Bonart, Julius and Donier, Jonathan and Gould, Martin},
  title     = {Trades, Quotes and Prices: Financial Markets Under the Microscope},
  publisher = {Cambridge University Press},
  year      = {2018},
  isbn      = {978-1-107-15605-0}
}
% NOTE: The USD 2 trillion claim needs re-attribution -- see correction checklist.

@article{brunnermeier2009,
  author  = {Brunnermeier, Markus K. and Pedersen, Lasse Heje},
  title   = {Market Liquidity and Funding Liquidity},
  journal = {Review of Financial Studies},
  year    = {2009},
  volume  = {22},
  number  = {6},
  pages   = {2201--2238},
  doi     = {10.1093/rfs/hhn098}
}

@article{ecb2020,
  author  = {{European Central Bank}},
  title   = {Volatility-Targeting Strategies and the Market Sell-Off},
  journal = {Financial Stability Review},
  year    = {2020},
  month   = {May},
  note    = {Box 2}
}
% CORRECTED: Title changed from "Procyclicality of volatility targeting strategies"

@article{gennotte1990,
  author  = {Gennotte, Gerard and Leland, Hayne E.},
  title   = {Market Liquidity, Hedging, and Crashes},
  journal = {American Economic Review},
  year    = {1990},
  volume  = {80},
  number  = {5},
  pages   = {999--1021}
}

@article{harvey2016,
  author  = {Harvey, Campbell R. and Liu, Yan and Zhu, Heqing},
  title   = {{\ldots} and the Cross-Section of Expected Returns},
  journal = {Review of Financial Studies},
  year    = {2016},
  volume  = {29},
  number  = {1},
  pages   = {5--68},
  doi     = {10.1093/rfs/hhv059}
}

@article{harvey2018,
  author  = {Harvey, Campbell R. and Hoyle, Edward and Korgaonkar, Russell and Rattray, Sandy and Sargaison, Matthew and Van Hemert, Otto},
  title   = {The Impact of Volatility Targeting},
  journal = {Journal of Portfolio Management},
  year    = {2018},
  volume  = {45},
  number  = {1},
  pages   = {14--33},
  doi     = {10.3905/jpm.2018.45.1.014}
}

@article{kyle1985,
  author  = {Kyle, Albert S.},
  title   = {Continuous Auctions and Insider Trading},
  journal = {Econometrica},
  year    = {1985},
  volume  = {53},
  number  = {6},
  pages   = {1315--1335}
}

@article{moreira2017,
  author  = {Moreira, Alan and Muir, Tyler},
  title   = {Volatility-Managed Portfolios},
  journal = {Journal of Finance},
  year    = {2017},
  volume  = {72},
  number  = {4},
  pages   = {1611--1644},
  doi     = {10.1111/jofi.12513}
}

@article{perchet2015,
  author  = {Perchet, Romain and de Carvalho, Raul Leote and Heckel, Thomas and Moulin, Pierre},
  title   = {Predicting the Success of Volatility Targeting Strategies: Application to Equities and Other Asset Classes},
  journal = {Journal of Alternative Investments},
  year    = {2015},
  volume  = {18},
  number  = {3},
  pages   = {21--38},
  doi     = {10.3905/jai.2016.18.3.021}
}
% CORRECTED: Title, pages, year, and cite key all updated.
% If "Inter- and intra-asset diversification in risk-based portfolios with the 1/VIX rule"
% is a separate working paper, add it as a distinct entry with the working paper source.
```

---

## Notes on Content Accuracy Beyond Bibliography

1. **Kyle lambda usage**: The manuscript uses a simplified version of Kyle (1985) with constant lambda. The paper correctly acknowledges in the Limitations section that Kyle derives lambda endogenously. No content accuracy issue.

2. **Brunnermeier-Pedersen feedback**: The manuscript is careful to say the feedback mechanism is "encoded in the model" (a design choice), not "discovered" from simulation -- this is intellectually honest and accurately represents the relationship to the original theory.

3. **Harvey et al. (2016) threshold**: The $|t| > 3.0$ threshold is correctly attributed and correctly applied (Welch's t-test on simulation Sharpe ratios).

4. **ECB (2020) procyclicality claim**: While the bibliography title is wrong, the substantive claim about ECB flagging VT procyclicality is accurate -- the May 2020 FSR box extensively discusses this issue.

5. **Perchet et al. as "practitioner heuristic"**: The 12/VIX (or 1/VIX) rule is indeed a widely-used practitioner heuristic. Whether the Perchet et al. paper is the best citation for this claim could be debated -- the rule predates their paper -- but the attribution is reasonable as they formalize and test it.
