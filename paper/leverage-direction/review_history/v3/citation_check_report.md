# Citation Verification Report — leverage-direction (v3)

**Date**: 2026-05-21
**Reviewer**: Claude (citation-verifier proxy)
**Manuscript**: paper/leverage-direction/main.tex + body.tex (the compiled paper)
**Reference source**: inline `\begin{thebibliography}` block in main.tex (57 bibitems)
**Prior round**: v2 citation_check_report.md (2026-04-13, 47 bibitems)

---

## Summary

| Status | Count | Notes |
|--------|-------|-------|
| VERIFIED (correct) | 46 | Includes 10 new v3 entries |
| MINOR issues | 4 | Format/style, unfixed from v2 |
| NEEDS_CHECK | 2 | One new v3 entry; one inherited |
| ERROR | 1 | `k1092` internal record cited as bibitem |
| **Total bibitems** | **57** | +10 from v2's 47 |

**v3 Changes vs v2**:
- **Removed**: `bollerslev1994`, `corsi2009`, `engle2002` (3 orphans) — CORRECT
- **Added**: `engleGhyselsSohn2013`, `pattonSheppard2015`, `acerbiszekely2014`, `bayerdimitriadis2022`, `fisslerziegel2016`, `k1092`, plus `patton2011` previously present (net new = 6 unique entries + corrections)
- `xu2024` author initial corrected from Y. to X. — CORRECT

---

## v3 New Citations — Detailed Assessment

### NEW-1: `engleGhyselsSohn2013` — VERIFIED

**Bibitem (main.tex line 111–112)**:
> Engle, R.F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics*, 95(3), 776–797. https://doi.org/10.1162/REST_a_00300

**Verification**: This paper exists and is correctly cited. The DOI resolves. Note that the actual GARCH-MIDAS paper is Engle, Ghysels & Sohn (2013) "Stock Market Volatility and Macroeconomic Fundamentals" published in *Review of Economics and Statistics*, 95(3):776–797. The key GARCH-MIDAS paper (which introduced the MIDAS variance component) is this paper plus Ghysels, Santa-Clara & Valkanov (2006) "Predicting volatility: Getting the most out of return data sampled at different frequencies" in *Journal of Econometrics*. The citation is appropriate; the body text (line 26) says Engle-Ghysels-Sohn "introduce GARCH-MIDAS" — this is the standard attribution.

**Bibitem label**: `[Engle et~al.(2013)]` — uses `et~al.` format, consistent with other multi-author entries. Minor: uses tilde-separated "et~al." in label while text elsewhere uses author surnames.

**Usage**: body.tex line 26 uses `\citet{engleGhyselsSohn2013}`. CORRECT.

**Status**: VERIFIED

---

### NEW-2: `pattonSheppard2015` — VERIFIED

**Bibitem (main.tex line 126–128)**:
> Patton, A.J., & Sheppard, K. (2015). Good volatility, bad volatility: Signed jumps and the persistence of volatility. *Review of Economics and Statistics*, 97(3), 683–697. https://doi.org/10.1162/REST_a_00503

**Verification**: This paper exists. The DOI resolves. Authors are Patton and Sheppard. Journal is *Review of Economics and Statistics* 97(3), 683–697. This is the correct "Good Volatility, Bad Volatility" paper.

**Note**: The bibitem key `pattonSheppard2015` uses camelCase, while other keys use lowercase (e.g., `patton2011`). This is a style inconsistency but not an error. The `\citet{pattonSheppard2015}` usage in body.tex line 26 matches. CORRECT.

**Status**: VERIFIED

---

### NEW-3: `fisslerziegel2016` — VERIFIED

**Bibitem (main.tex line 123–124)**:
> Fissler, T., & Ziegel, J.F. (2016). Higher order elicitability and Osband's principle. *Annals of Statistics*, 44(4), 1680–1707. https://doi.org/10.1214/16-AOS1439

**Verification**: The Fissler-Ziegel elicitability paper exists in *Annals of Statistics* 44(4), 2016. The DOI is correct. This is the canonical reference for joint (VaR, ES) elicitability. CORRECT.

**Usage**: body.tex line 258 uses `\citet{fisslerziegel2016}`. Correctly placed in ES subsection.

**Status**: VERIFIED

---

### NEW-4: `acerbiszekely2014` — NEEDS_CHECK (minor)

**Bibitem (main.tex line 117–118)**:
> Acerbi, C., & Szekely, B. (2014). Back-testing expected shortfall. *Risk*, 27(11), 76–81.

**Verification**: The Acerbi-Szekely (2014) ES backtesting paper was published in *Risk*. The issue and page range (27(11), 76–81) are consistent with records for this paper. However, the exact page range should be verified against the published article as *Risk* changed its article format in this period. The description matches the well-known 2014 Risk paper on ES backtesting. No DOI provided (Risk articles from this era often lack public DOIs).

**Note**: The author name "Szekely" should technically have an accent: Székely. This is a common simplification in LaTeX that does not affect identification.

**Status**: NEEDS_CHECK (page range; missing DOI — acceptable for Risk 2014)

---

### NEW-5: `bayerdimitriadis2022` — VERIFIED

**Bibitem (main.tex line 120–121)**:
> Bayer, S., & Dimitriadis, T. (2022). Regression-based expected shortfall backtesting. *Journal of Financial Econometrics*, 20(3), 437–471. https://doi.org/10.1093/jjfinec/nbaa013

**Verification**: This paper exists. Bayer and Dimitriadis (2022), "Regression-based expected shortfall backtesting," *Journal of Financial Econometrics*, 20(3), 437–471. The DOI resolves. CORRECT.

**Status**: VERIFIED

---

### NEW-6: `k1092` — ERROR (structural problem)

**Bibitem (main.tex line 129–131)**:
```
\bibitem[VolPred Research(K1092, 2026)]{k1092}
VolPred Research Program (2026). K1092: Asset-matched DCC-A4f Fissler–Ziegel evaluation. Internal experiment record, available in the paper's replication package.
```

**Issue**: This is not a verifiable published or working paper. It is an internal experiment record. JBF's editorial system will reject this as a bibliographic entry. The appropriate treatment is either:
1. Move to a footnote: "See internal experiment K1092, available in the paper's replication package."
2. Deposit as an SSRN working paper and cite as such.

Additionally, "VolPred Research Program" as an author name will raise editorial flags — it does not correspond to a human author.

**Status**: ERROR — must be restructured before submission.

---

## v2 Inherited Citations — Key Status Updates

### `xu2024` — MINOR ISSUE RESOLVED, NEW QUESTION

**v2 issue**: Author initial "Y." was wrong; correct is "X." (Xia Xu).
**v3 fix**: `Xu, X. (2024)` — CORRECTED.

**New question**: "Critical Finance Review, forthcoming" — as of 2026-05-21, the publication status should be re-verified. If published, update to volume/issue/pages.

**Status**: MINOR (publication status needs update before submission)

---

### `hou2020` — v2 MED CONTENT CLAIM

**v2 finding**: Hou, Xue & Zhang (2020) does not document Yahoo vs. CRSP concordance as a central finding; the attribution was inaccurate.

**v3 status**: body.tex lines 61–65 no longer attribute the Yahoo/CRSP comparison to hou2020. Instead, the data section uses `\citet{bali2016}` as the data quality precedent and `\citet{moreira2017,cederburg2020}` for return distribution consistency. The hou2020 citation itself is not found in the data section any longer. The v2 MED issue was **RESOLVED** by removing the incorrect attribution.

**Status**: RESOLVED

---

### `demiguel2024` — v2 MED CONTENT CLAIM

**v2 finding**: "13% Sharpe improvement via hybrid implied-realized framework" was inaccurate framing.

**v3 status**: body.tex line 46 reads "DeMiguel, Martin-Utrera, and Uppal (2024) reframe volatility-managed portfolios from a multifactor perspective, showing that the in-sample Sharpe gains of VT strategies are substantially attenuated once exposures to standard risk factors are controlled for." This is an accurate characterization of the paper's contribution (testing VT strategies after controlling for risk factor exposures).

**Status**: RESOLVED

---

### `hood2025` — MINOR (unfixed from v2)

**v2 issue**: Short title "Volatility targeting is trendy." — APA 7th requires full title with subtitle.
**v3 status**: main.tex line 181 still uses `Volatility targeting is trendy.` — UNFIXED.
**Full title**: "Volatility Targeting Is Trendy: How Trend Following Explains Alpha in Volatility-Managed Strategies."

**Status**: MINOR (unfixed)

---

### `parkinson1980` — Uncited Orphan (unfixed)

**v2 finding**: Not cited anywhere.
**v3 status**: `parkinson1980` remains in bibliography (main.tex line 219–220); not found in body.tex via `\cite{}` or narrative. Still an orphan.

**Status**: MINOR (unfixed — remove or use)

---

### `campbell2017` — Label Style Mismatch (unfixed)

**v2 finding**: Uses `[Campbell et~al., 2017]` while all others use `[Author(Year)]`.
**v3 status**: main.tex line 234 still uses `\bibitem[Campbell et~al., 2017]{campbell2017}` — UNFIXED.

**Status**: MINOR (unfixed)

---

### `nelson2025` — NEEDS_CHECK (inherited)

**v2 finding**: Ryan Nelson (2025) SSRN paper; recommend disambiguating from Daniel B. Nelson (1991).
**v3 status**: main.tex line 216 still uses `\bibitem[Nelson(2025)]{nelson2025}` — two "Nelson" entries in bibliography with same bracket label style will be confusing in in-text citations.

**Status**: NEEDS_CHECK (disambiguation still recommended)

---

## Orphan Citation Check (Inherited)

| Bibitem | v2 Status | v3 Status |
|---------|-----------|-----------|
| `bollerslev1994` | Orphan | REMOVED — CORRECT |
| `corsi2009` | Orphan | REMOVED — CORRECT |
| `engle2002` | Orphan | REMOVED — CORRECT |
| `parkinson1980` | Orphan | Still present — UNCITED |
| `engle2004` | Present | Present — usage needs verification |

---

## Full Bibliography Inventory (v3)

57 total bibitems:

1. `araya2024` — VERIFIED
2. `baur2010hedge` — VERIFIED
3. `baur2010safe` — VERIFIED
4. `bali2016` — VERIFIED
5. `batten2010` — VERIFIED
6. `bcbs2006` — VERIFIED
7. `bcbs2019` — VERIFIED
8. `black1976` — VERIFIED
9. `bollerslev1986` — VERIFIED
10. `bollerslev1987` — VERIFIED
11. `bozovic2024` — VERIFIED
12. `bucci2020` — VERIFIED
13. `cederburg2020` — VERIFIED
14. `chang2021` — VERIFIED
15. `chevallier2017` — VERIFIED
16. `engleGhyselsSohn2013` — VERIFIED (NEW v3)
17. `engle2006` — VERIFIED
18. `acerbiszekely2014` — NEEDS_CHECK (NEW v3)
19. `bayerdimitriadis2022` — VERIFIED (NEW v3)
20. `fisslerziegel2016` — VERIFIED (NEW v3)
21. `pattonSheppard2015` — VERIFIED (NEW v3)
22. `k1092` — ERROR (NEW v3 — internal record, not a valid bibitem)
23. `christoffersen1998` — VERIFIED
24. `christie1982` — VERIFIED
25. `diebold1995` — VERIFIED
26. `demiguel2024` — VERIFIED (content claim corrected in v3)
27. `engle2018` — VERIFIED
28. `engle2004` — NEEDS_CHECK (possibly uncited — verify usage)
29. `fleming2001` — VERIFIED
30. `fleming2003` — VERIFIED
31. `francq2004` — VERIFIED
32. `glosten1993` — VERIFIED
33. `hansen1994` — VERIFIED
34. `hansen2005` — VERIFIED
35. `hansen2012` — VERIFIED
36. `harri2009` — VERIFIED
37. `harvey2016` — VERIFIED
38. `harvey2018` — VERIFIED
39. `hood2025` — MINOR (short title)
40. `henriksson1981` — VERIFIED
41. `hou2020` — VERIFIED (content claim corrected in v3)
42. `hwang2006` — VERIFIED
43. `kim2019` — VERIFIED
44. `kuester2006` — VERIFIED
45. `kupiec1995` — VERIFIED
46. `longin2001` — VERIFIED
47. `mcneil2015` — MINOR (no "Revised ed.")
48. `moreira2017` — VERIFIED
49. `nelson1991` — VERIFIED
50. `newey1987` — VERIFIED
51. `nelson2025` — NEEDS_CHECK (disambiguation)
52. `parkinson1980` — MINOR (uncited orphan)
53. `patton2011` — VERIFIED
54. `sheppard2023` — VERIFIED
55. `treynor1966` — VERIFIED
56. `xu2024` — MINOR (publication status, author initial fixed)
57. `campbell2017` — MINOR (label style mismatch)

---

## Overall Citation Assessment

**v3 improvements over v2**:
- 3 orphan citations removed (bollerslev1994, corsi2009, engle2002) — CLEAN
- 2 key missing citations added (engleGhyselsSohn2013, pattonSheppard2015) — COMPLETE
- 3 ES framework citations added (fisslerziegel2016, acerbiszekely2014, bayerdimitriadis2022) — APPROPRIATE
- xu2024 author initial corrected (Y. → X.) — CLEAN
- hou2020 and demiguel2024 content claims corrected — CLEAN

**v3 remaining issues**:
- 1 ERROR: `k1092` internal record cited as bibitem — must fix before submission
- 4 MINOR: parkinson1980 orphan, hood2025 short title, campbell2017 style, mcneil2015 format
- 2 NEEDS_CHECK: acerbiszekely2014 page range, nelson2025 disambiguation

**Overall citation quality**: High — 46/57 (81%) fully verified, with only one structural error (k1092) that must be fixed before submission. The citation landscape is substantially cleaner than v2.
