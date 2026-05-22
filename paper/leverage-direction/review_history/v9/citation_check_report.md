# Citation Check Report — leverage-direction v9

**Date**: 2026-05-23
**Reviewer**: citation-verifier agent
**Files reviewed**: `main.tex`, `body.tex`, `tables.tex`
**Scope**: Full citation sweep + focused verification of v8 deferred MEDIUM items

---

## Executive Summary

| Severity | Count | Description |
|----------|-------|-------------|
| MAJOR | 0 | None found |
| MEDIUM | 1 | engle1982 JSTOR DOI (persists from v7/v8; not target-journal-blocking unless submission requires canonical DOI) |
| MINOR | 3 | nelson2025 SSRN unpublished; xu2024 forthcoming without final pages/DOI; chevallier2017 DOI date-prefix mismatch (2014 in DOI, cited as 2017) |
| RESOLVED | 3 | MAJOR-1 glosten1993 monthly data fix (v8→v9); M-2 sample period body.tex line 156 fix (v8 deferred); tables.tex caption updated to 2017--2025 |

**Overall verdict**: PASS — no MAJOR issues remain. The paper is citation-clean for submission pending the MEDIUM item on engle1982 DOI (target-journal dependent) and the three low-risk MINOR items.

---

## Focus Area: v8 Deferred Items Verification

### F-1: MAJOR-1 (v8) — glosten1993 monthly data ✅ RESOLVED

**v8 problem**: body.tex line 76 said "fewer than 3,000 daily observations" for GJR (1993), which used monthly CRSP data.

**v9 status**: body.tex line 76 now reads:
> `\citet{glosten1993} established the leverage effect in U.S.\ equities using approximately 735 monthly observations (CRSP 1926--1987)`

Web verification confirms: GJR (1993) used monthly NYSE/CRSP nominal excess returns. The corrected text is factually accurate. **Resolved.**

---

### F-2: MED-2 (v8) — Sample period text fix ✅ RESOLVED

**v8 deferred item (M-2)**: body.tex was noted as needing update to "in-sample period 2017--2025 (with 2026 reserved for out-of-sample validation)"; tables.tex caption needed "In-Sample Period: 2017--2025".

**v9 status**:
- `body.tex` line 156: "over the in-sample period 2017--2025 (with 2026 reserved for out-of-sample validation)" ✅
- `tables.tex` line 6: `\caption{Descriptive Statistics of Daily Returns (In-Sample Period: 2017--2025)}` ✅

Both fixes confirmed. **Resolved.**

---

### F-3: MED-1 (v8) — engle1982 JSTOR DOI ⚠ STILL OPEN (MEDIUM)

**Status**: The DOI `https://doi.org/10.2307/1912773` uses the JSTOR resolver prefix rather than a canonical publisher DOI. This carries over from v7 and v8 as an acknowledged deferred item.

**Verification**: Web search confirms:
- Econometric Society (publisher of *Econometrica*) lists the paper at econometricsociety.org; the JSTOR link `https://www.jstor.org/stable/1912773` is the stable URL.
- The `10.2307/` prefix is JSTOR's own DOI namespace. No separate Wiley/Econometric Society DOI exists for pre-digital *Econometrica* articles; the JSTOR DOI **is** the canonical persistent identifier for this paper.
- Cross-references at IDEAS, Semantic Scholar, and SCIRP all cite `doi:10.2307/1912773`.

**Assessment**: The JSTOR DOI is functionally correct — it resolves to the official JSTOR page of the paper. Most finance journals (JFE, JF, JBF, RFS) accept JSTOR DOIs for pre-1990 papers. This is only a concern if the target journal explicitly requires Crossref/publisher DOI and disallows JSTOR prefixes.

**Severity**: MEDIUM (target-journal-dependent; content accuracy unaffected).

**Suggested fix (if required by target journal)**:
```latex
Engle, R.~F. (1982). Autoregressive conditional heteroscedasticity with estimates
of the variance of United Kingdom inflation. \textit{Econometrica}, 50(4),
987--1007. [No canonical Crossref DOI available; JSTOR stable: 
https://www.jstor.org/stable/1912773]
```
Or simply retain `https://doi.org/10.2307/1912773` as is; it is widely used in the literature.

---

### F-4: hood2025 JPM 52(1) citation ✅ VERIFIED

**v8 concern**: "early access" label potentially stale.

**v9 status**: `main.tex` line 184:
```latex
Hood, B., \& Raughtigan, C. (2025). Volatility targeting is trendy: How trend
following explains alpha in volatility-managed strategies. \textit{Journal of
Portfolio Management}, 52(1). https://doi.org/10.3905/jpm.2025.1.764
```

**Verification**: Web search confirms:
- Author names correct: Benjamin Hood and Cameron Raughtigan.
- The paper appears in JPM Vol. 52(1) (November 2025).
- DOI `10.3905/jpm.2025.1.764` resolves to the correct article on pm-research.com.
- No page numbers are listed in the current bibitem. JPM articles are often available without traditional page numbers in online-first format.

**Note**: The pm-research.com URL still shows the "early" path (`early/2025/09/08/jpm20251764`), which is the publisher's persistent URL for this article even after formal publication. This is consistent with JPM's URL scheme.

**Status**: VERIFIED. No action required. The citation as written is correct for a formally published JPM article.

---

## General Citation Sweep

### ✅ Verified Citations (no issues)

| Key | Bibliographic details | Verdict |
|-----|----------------------|---------|
| araya2024 | Araya, Aduda, Berhane (2024). J. Applied Mathematics 2024, 6305525. DOI: 10.1155/2024/6305525 | OK |
| baur2010hedge | Baur & Lucey (2010). Financial Review 45(2), 217–229. DOI: 10.1111/j.1540-6288.2010.00244.x | OK |
| baur2010safe | Baur & McDermott (2010). J. Banking & Finance 34(8), 1886–1898. DOI: 10.1016/j.jbankfin.2009.12.008 | OK |
| bali2016 | Bali, Engle, Murray (2016). *Empirical Asset Pricing*. Wiley. DOI: 10.1002/9781118709207 | OK |
| batten2010 | Batten, Ciner, Lucey (2010). Resources Policy 35(2), 65–71. DOI: 10.1016/j.resourpol.2009.12.002 | OK |
| bcbs2006 | BCBS (2006). Basel II framework. BIS. | OK (no DOI standard for institutional reports) |
| bcbs2019 | BCBS (2019). FRTB minimum capital requirements. BIS. | OK |
| black1976 | Black (1976). ASA Proceedings 177–181. | OK (MINOR-3 from v8 retained; pre-digital) |
| bollerslev1986 | Bollerslev (1986). J. Econometrics 31(3), 307–327. DOI: 10.1016/0304-4076(86)90063-1 | OK |
| bollerslev1987 | Bollerslev (1987). Rev. Econ. Statistics 69(3), 542–547. DOI: 10.2307/1925546 | OK |
| bozovic2024 | Bozovic (2024). IRFA 95, 103353. DOI: 10.1016/j.irfa.2024.103353 | OK |
| bucci2020 | Bucci (2020). J. Fin. Econometrics 18(3), 502–531. DOI: 10.1093/jjfinec/nbaa008 | OK |
| cederburg2020 | Cederburg, O'Doherty, Wang, Yan (2020). JFE 138(1), 95–117. DOI: 10.1016/j.jfineco.2020.04.015 | OK |
| chang2021 | Chang, Kung, Chen, Tian (2021). Pac.-Basin Finance J. 67, 101522. DOI: 10.1016/j.pacfin.2021.101522 | OK |
| christoffersen1998 | Christoffersen (1998). IER 39(4), 841–862. DOI: 10.2307/2527341 | OK |
| christie1982 | Christie (1982). JFE 10(4), 407–432. DOI: 10.1016/0304-405X(82)90018-6 | OK |
| diebold1995 | Diebold & Mariano (1995). JBES 13(3), 253–263. DOI: 10.1080/07350015.1995.10524599 | OK |
| demiguel2024 | DeMiguel, Martin-Utrera, Uppal (2024). J. Finance 79(6), 3859–3891. DOI: 10.1111/jofi.13395 | OK |
| engle2018 | Engle & Siriwardane (2018). RFS 31(2), 449–492. DOI: 10.1093/rfs/hhx099 | OK |
| engle2004 | Engle (2004). AER 94(3), 405–420. DOI: 10.1257/0002828041464597 | OK |
| engleGhyselsSohn2013 | Engle, Ghysels, Sohn (2013). Rev. Econ. Statistics 95(3), 776–797. DOI: 10.1162/REST\_a\_00300 | OK |
| engle2006 | Engle & Gallo (2006). J. Econometrics 131(1–2), 3–27. DOI: 10.1016/j.jeconom.2005.01.018 | OK |
| acerbiszekely2014 | Acerbi & Szekely (2014). Risk 27(11), 76–81. | OK (no DOI; pre-2015 Risk article) |
| bayerdimitriadis2022 | Bayer & Dimitriadis (2022). J. Fin. Econometrics 20(3), 437–471. DOI: 10.1093/jjfinec/nbaa013 | OK |
| fisslerziegel2016 | Fissler & Ziegel (2016). Annals of Statistics 44(4), 1680–1707. DOI: 10.1214/16-AOS1439 | OK |
| pattonSheppard2015 | Patton & Sheppard (2015). Rev. Econ. Statistics 97(3), 683–697. DOI: 10.1162/REST\_a\_00503 | OK ✓ issue 3 confirmed |
| flemming2001 | Fleming, Kirby, Ostdiek (2001). J. Finance 56(1), 329–352. DOI: 10.1111/0022-1082.00327 | OK |
| flemming2003 | Fleming, Kirby, Ostdiek (2003). JFE 67(3), 473–509. DOI: 10.1016/S0304-405X(02)00259-3 | OK |
| francq2004 | Francq & Zakoïan (2004). Bernoulli 10(4), 605–637. DOI: 10.3150/bj/1093265632 | OK |
| glosten1993 | Glosten, Jagannathan, Runkle (1993). J. Finance 48(5), 1779–1801. DOI: 10.1111/j.1540-6261.1993.tb05128.x | OK (MAJOR-1 resolved in v9) |
| hansen1994 | Hansen (1994). IER 35(3), 705–730. DOI: 10.2307/2527081 | OK |
| hansen2005 | Hansen & Lunde (2005). J. Applied Econometrics 20(7), 873–889. DOI: 10.1002/jae.800 | OK |
| hansen2011 | Hansen, Lunde, Nason (2011). Econometrica 79(2), 453–497. DOI: 10.3982/ECTA5771 | OK |
| hansen2012 | Hansen, Huang, Shek (2012). J. Applied Econometrics 27(6), 877–906. DOI: 10.1002/jae.1234 | OK |
| harri2009 | Harri & Brorsen (2009). QQASS 3(3), 78–115. | OK (no DOI for this journal) |
| harvey2016 | Harvey, Liu, Zhu (2016). RFS 29(1), 5–68. DOI: 10.1093/rfs/hhv059 | OK |
| harvey2018 | Harvey et al. (2018). JPM 45(1), 14–33. DOI: 10.3905/jpm.2018.45.1.014 | OK |
| hood2025 | Hood & Raughtigan (2025). JPM 52(1). DOI: 10.3905/jpm.2025.1.764 | OK (verified) |
| henriksson1981 | Henriksson & Merton (1981). J. Business 54(4), 513–533. DOI: 10.1086/296144 | OK |
| hwang2006 | Hwang & Valls Pereira (2006). Eur. J. Finance 12(6–7), 473–494. DOI: 10.1080/13518470500039436 | OK |
| kim2019 | Kim & Kim (2019). PLoS ONE 14(2), e0212320. DOI: 10.1371/journal.pone.0212320 | OK |
| kuester2006 | Kuester, Mittnik, Paolella (2006). J. Fin. Econometrics 4(1), 53–89. DOI: 10.1093/jjfinec/nbj002 | OK |
| kupiec1995 | Kupiec (1995). J. Derivatives 3(2), 73–84. DOI: 10.3905/jod.1995.407942 | OK |
| longin2001 | Longin & Solnik (2001). J. Finance 56(2), 649–676. DOI: 10.1111/0022-1082.00340 | OK |
| mcneil2015 | McNeil, Frey, Embrechts (2015). *Quantitative Risk Management*. Princeton UP. | OK |
| moreira2017 | Moreira & Muir (2017). J. Finance 72(4), 1611–1644. DOI: 10.1111/jofi.12513 | OK |
| nelson1991 | Nelson (1991). Econometrica 59(2), 347–370. DOI: 10.2307/2938260 | OK |
| newey1987 | Newey & West (1987). Econometrica 55(3), 703–708. DOI: 10.2307/1913610 | OK |
| parkinson1980 | Parkinson (1980). J. Business 53(1), 61–65. DOI: 10.1086/296071 | OK |
| patton2011 | Patton (2011). J. Econometrics 160(1), 246–256. DOI: 10.1016/j.jeconom.2010.03.034 | OK |
| sheppard2023 | Sheppard (2023). arch Python package v6.2. GitHub. | OK |
| treynor1966 | Treynor & Mazuy (1966). Harvard Business Review 44(4), 131–136. | OK (pre-DOI era) |
| campbell2017 | Campbell, Sunderam, Viceira (2017). Critical Finance Review 6(2), 263–301. DOI: 10.1561/104.00000043 | OK (v7 correction confirmed) |

---

## MEDIUM Issues

### MED-1: engle1982 — JSTOR DOI (persists from v7/v8)

**Location**: `main.tex`, line 115
**Entry**: `https://doi.org/10.2307/1912773`

**Detail**: The `10.2307/` prefix is JSTOR's own DOI namespace. For pre-digital *Econometrica* articles published before Wiley began cross-registering DOIs, the JSTOR DOI **is** the standard persistent identifier. This is verified by the fact that the Econometric Society's own publication page (econometricsociety.org) links to the JSTOR record. No separate publisher Crossref DOI exists for this 1982 paper.

**Recommendation**: Retain as-is for most target journals. If the target journal's style guide or submission system explicitly requires Crossref DOIs only, replace DOI with the JSTOR stable URL in a URL field:
```
https://www.jstor.org/stable/1912773
```

**Severity**: MEDIUM (unblocking; functionally correct).

---

## MINOR Issues

### MINOR-1: nelson2025 — SSRN working paper, unpublished

**Location**: `main.tex`, lines 216–217
**Entry**:
```latex
Nelson, R. (2025). Portfolio construction under correlation breakdowns and tail risk.
SSRN Working Paper No.~5931154. https://doi.org/10.2139/ssrn.5931154
```

**Verification**: SSRN confirms the paper exists (by Ryan Nelson, posted December 2025). The author's institutional affiliation is missing from the bibitem.

**Suggested fix**:
```latex
Nelson, R. (2025). Portfolio construction under correlation breakdowns and tail risk.
\textit{SSRN Working Paper} No.~5931154. https://doi.org/10.2139/ssrn.5931154
```
Additionally, check if published since December 2025; if still unpublished, add "(unpublished manuscript)" per target journal style. The author name "R. Nelson" matches "Ryan Nelson" confirmed on SSRN.

**Severity**: MINOR.

---

### MINOR-2: xu2024 — forthcoming, no final pages/DOI

**Location**: `main.tex`, lines 231–232
**Entry**:
```latex
Xu, X. (2024). Improving volatility-managed portfolios in real time.
\textit{Critical Finance Review}, forthcoming.
```

**Verification**: The paper appears on the CFR forthcoming page (cfr.ivo-welch.info/forthcoming). As of the verification date (2026-05-23), it is listed as "forthcoming" without an assigned volume/issue. SSRN DOI 10.2139/ssrn.4778937 confirmed.

**Recommended update** (if journal has published final version by submission date):
```latex
Xu, X. (2024). Improving volatility-managed portfolios in real time.
\textit{Critical Finance Review}. https://doi.org/10.2139/ssrn.4778937
```
Check the CFR website directly at submission time to confirm whether final citation details are available.

**Severity**: MINOR (acceptable for forthcoming papers; update at proof stage).

---

### MINOR-3: chevallier2017 — DOI year prefix anomaly

**Location**: `main.tex`, lines 108–109
**Entry**:
```latex
Chevallier, J., \& Ielpo, F. (2017). Investigating the leverage effect in commodity
markets with a recursive estimation approach. \textit{Research in International
Business and Finance}, 39, 763--778. https://doi.org/10.1016/j.ribaf.2014.09.010
```

**Issue**: The DOI `10.1016/j.ribaf.2014.09.010` contains "2014" in the identifier path — this is the date the manuscript was registered with the publisher (Elsevier received/accepted the paper in 2014), while the final volume publication was 2017 in RIBAF vol. 39. This is normal for long-review-cycle papers at Elsevier; the DOI resolves correctly to the final 2017 published article.

**Verification**: IDEAS/RePec confirms: "Research in International Business and Finance, vol. 39(PB), pages 763-778" with this exact DOI. ScienceDirect confirms the paper is published in Vol. 39, Part B. The DOI is correct and resolves to the published article.

**Severity**: MINOR (informational; no correction needed — the DOI is correct as published).

---

### MINOR-4 (informational): black1976 — No DOI available

**Location**: `main.tex`, line 88
Pre-digital conference proceedings. No DOI available. Standard citation is "pp. 177–181". No action required.

---

## In-Text Content Accuracy Spot-Checks

The following key factual claims were spot-checked against sources:

| Claim in paper | Cited paper | Verdict |
|----------------|-------------|---------|
| "Moreira & Muir (2017) demonstrate that scaling portfolio exposure by the inverse of conditional variance… generates significant alphas across equity factors" | moreira2017 | ✓ Accurate |
| "Harvey et al. (2018) extend these results to multi-asset portfolios" | harvey2018 | ✓ Accurate |
| "Hood (2025) demonstrate that equity VT alpha arises primarily from implicit trend-following via the leverage effect" | hood2025 | ✓ Accurate per published abstract |
| "Cederburg et al. (2020)… whose headline finding is that VT does not systematically improve Sharpe ratios over unmanaged portfolios" | cederburg2020 | ✓ Accurate (paper's main finding is negative on VT broadly) |
| "DeMiguel et al. (2024) reframe volatility-managed portfolios from a multifactor perspective, showing that the in-sample Sharpe gains of VT strategies are substantially attenuated" | demiguel2024 | ✓ Confirmed: JF 79(6), 3859–3891 |
| "Baur & McDermott (2010)… gold functions as both a hedge and a safe haven for developed market equities" | baur2010safe | ✓ Accurate |
| "Chang et al. (2021) use a Markov-switching GJR-GARCH to link gold's inverted asymmetry to high-volatility regimes" | chang2021 | ✓ Accurate |
| "Patton & Sheppard (2015) show that the asymmetric response of volatility can be traced specifically to realized negative semivariance" | pattonSheppard2015 | ✓ Accurate (paper's central finding) |
| "Chevallier & Ielpo (2017) investigate the leverage effect across a broad set of commodities and find that gold, wheat, coffee, and cocoa exhibit inverted asymmetric volatility" | chevallier2017 | ✓ Accurate per abstract |
| Glosten et al. (1993) "approximately 735 monthly observations (CRSP 1926–1987)" | glosten1993 | ✓ Accurate (monthly data confirmed) |
| Harvey et al. (2016) t > 3.0 threshold | harvey2016 | ✓ Accurate (paper introduces this threshold) |
| Patton & Sheppard (2015) vol. 97(3) pp. 683–697 | pattonSheppard2015 | ✓ Issue 3 confirmed (MIT Press direct.mit.edu/rest/article/97/3/683) |

---

## Correction Checklist

- [x] MAJOR: glosten1993 monthly data error — **RESOLVED in v9**
- [x] M-2: Sample period text/table — **RESOLVED in v9**
- [x] M-2: hood2025 early-access label — **RESOLVED; citation is correct as 52(1)**
- [ ] MED-1: engle1982 JSTOR DOI — **retain as-is** unless target journal requires Crossref DOI exclusively
- [ ] MINOR-1: nelson2025 — add institutional affiliation; confirm still unpublished; add "(unpublished manuscript)" if required by target journal
- [ ] MINOR-2: xu2024 — check CFR final publication at submission time; update pages/DOI if assigned
- [ ] MINOR-3: chevallier2017 — no correction needed (DOI is correct); informational only

---

## Complete Reference List Status

57 bibitems in `main.tex`. All verified. Zero orphan in-text citations. Zero unused bibitems.

| Key | Status |
|-----|--------|
| araya2024 | ✅ OK |
| baur2010hedge | ✅ OK |
| baur2010safe | ✅ OK |
| bali2016 | ✅ OK |
| batten2010 | ✅ OK |
| bcbs2006 | ✅ OK |
| bcbs2019 | ✅ OK |
| black1976 | ✅ OK (MINOR-4, pre-digital) |
| bollerslev1986 | ✅ OK |
| bollerslev1987 | ✅ OK |
| bozovic2024 | ✅ OK |
| bucci2020 | ✅ OK |
| cederburg2020 | ✅ OK |
| chang2021 | ✅ OK |
| chevallier2017 | ✅ OK (MINOR-3, DOI year prefix) |
| engleGhyselsSohn2013 | ✅ OK |
| engle1982 | ⚠ MED-1 (JSTOR DOI; functionally correct) |
| engle2006 | ✅ OK |
| acerbiszekely2014 | ✅ OK |
| bayerdimitriadis2022 | ✅ OK |
| fisslerziegel2016 | ✅ OK |
| pattonSheppard2015 | ✅ OK (issue 3 confirmed) |
| christoffersen1998 | ✅ OK |
| christie1982 | ✅ OK |
| diebold1995 | ✅ OK |
| demiguel2024 | ✅ OK |
| engle2018 | ✅ OK |
| engle2004 | ✅ OK |
| fleming2001 | ✅ OK |
| fleming2003 | ✅ OK |
| francq2004 | ✅ OK |
| glosten1993 | ✅ OK (MAJOR-1 resolved in v9) |
| hansen1994 | ✅ OK |
| hansen2005 | ✅ OK |
| hansen2011 | ✅ OK |
| hansen2012 | ✅ OK |
| harri2009 | ✅ OK |
| harvey2016 | ✅ OK |
| harvey2018 | ✅ OK |
| hood2025 | ✅ OK (JPM 52(1) verified) |
| henriksson1981 | ✅ OK |
| hwang2006 | ✅ OK |
| kim2019 | ✅ OK |
| kuester2006 | ✅ OK |
| kupiec1995 | ✅ OK |
| longin2001 | ✅ OK |
| mcneil2015 | ✅ OK |
| moreira2017 | ✅ OK |
| nelson1991 | ✅ OK |
| newey1987 | ✅ OK |
| nelson2025 | ⚠ MINOR-1 (SSRN; missing affiliation) |
| parkinson1980 | ✅ OK |
| patton2011 | ✅ OK |
| sheppard2023 | ✅ OK |
| treynor1966 | ✅ OK |
| xu2024 | ⚠ MINOR-2 (forthcoming; update at submission) |
| campbell2017 | ✅ OK (v7 correction retained) |

---

*Generated by citation-verifier skill. Web verification sources: pm-research.com, ideas.repec.org, direct.mit.edu, onlinelibrary.wiley.com, econometricsociety.org, ssrn.com, sciencedirect.com.*
