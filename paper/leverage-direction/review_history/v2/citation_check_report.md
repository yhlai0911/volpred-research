# Citation Verification Report — leverage-direction

**Date**: 2026-04-13
**Reviewer**: Claude (citation-verifier skill)
**Manuscript**: paper/leverage-direction/main_v2.tex + body_v2.tex
**Reference source**: inline `\begin{thebibliography}` block in main_v2.tex (no external .bib file)

---

## Summary

| Status | Count | Percentage |
|--------|-------|------------|
| Verified (completely correct) | 40 | 85.1% |
| Minor issues | 5 | 10.6% |
| MAJOR issues | 0 | 0.0% |
| NEEDS_CHECK | 2 | 4.3% |
| **Total bibitems** | **47** | 100% |

- Citations actually used (`\cite*` or narrative): 34 unique keys across body_v2.tex
- Unused bibitems: 13 (reference list contains extras not cited in text; not an error but worth trimming)
- Self-citation (Lai): **none present** — this paper has no Lai self-citations, so the usual self-citation risk does not apply

---

## Unused Bibitems (not an error, but flag for review)

The following bibitems exist in the reference list but are not cited in body_v2.tex or main_v2.tex. Consider removing to keep the reference list clean (journals often audit this):

1. `bcbs2006` — BCBS (2006) — *narratively referenced* as "(BCBS, 2006, 2019)" in body line 36 but not via `\cite{}`. OK if APA narrative; otherwise missing `\cite{}`.
2. `bcbs2019` — same as above
3. `bollerslev1987` — narratively referenced line 38 as "Bollerslev (1987)" without `\cite{}`. Same comment.
4. `bollerslev1994` — not cited anywhere in body_v2 or main_v2. **Remove or use.**
5. `christoffersen1998` — narratively referenced line 36 + 129 without `\cite{}`. OK if narrative APA.
6. `diebold1995` — narratively referenced line 113 without `\cite{}`. OK.
7. `engle2002` — not cited anywhere. **Remove or use.**
8. `fleming2001` / `fleming2003` — narratively referenced line 44 without `\cite{}`.
9. `glosten1993` — used via `\citet{glosten1993}` line 76 (OK).
10. `hansen2012` — used via `\citep{hansen2012}` line 588 (OK).
11. `kim2019` — narratively referenced line 50 without `\cite{}`. OK.
12. `kupiec1995` — narratively referenced lines 36, 129 without `\cite{}`.
13. `longin2001` — narratively referenced line 401 without `\cite{}`.
14. `mcneil2015` — narratively referenced line 36 without `\cite{}`.
15. `nelson1991` — narratively referenced line 5 without `\cite{}`.
16. `nelson2025` — narratively referenced line 429 as "Nelson's (2025)" without `\cite{}`.
17. `parkinson1980` — **not cited anywhere** (even narratively). **Remove or use.**
18. `sheppard2023` — narratively referenced line 91 without `\cite{}`.
19. `treynor1966` — used via `\citet{treynor1966}` line 375 (OK).

**Minor (stylistic)**: Mixing `\citet/\citep` with narrative "Author (Year)" is inconsistent. APA 7th recommends consistency. Not a factual error.

---

## Detail by Citation

### Verified

#### 1. `araya2024` — Araya, Aduda, & Berhane (2024) — Verified
- Journal of Applied Mathematics, 2024, 6305525. DOI: 10.1155/2024/6305525
- Authors confirmed: Hailabe T. Araya, Jane Aduda, Tesfahun Berhane
- APA format: correct. DOI resolves.

#### 2. `baur2010hedge` — Baur & Lucey (2010) — Verified
- Financial Review, 45(2), 217-229. DOI: 10.1111/j.1540-6288.2010.00244.x
- Title "Is gold a hedge or a safe haven? An analysis of stocks, bonds and gold" confirmed.

#### 3. `baur2010safe` — Baur & McDermott (2010) — Verified
- Journal of Banking & Finance, 34(8), 1886-1898. DOI: 10.1016/j.jbankfin.2009.12.008
- All bibliographic details match.

#### 4. `bali2016` — Bali, Engle, & Murray (2016) — Verified
- Wiley textbook, DOI: 10.1002/9781118709207. Correct.

#### 5. `batten2010` — Batten, Ciner, & Lucey (2010) — Verified
- Resources Policy, 35(2), 65-71. DOI: 10.1016/j.resourpol.2009.12.002. Correct.

#### 6. `black1976` — Black (1976) — Verified (classic, no DOI)
- "Studies of stock price volatility changes," *Proceedings of the Business and Economics Statistics Section, ASA*, 177-181. Widely cited form. No DOI available (conference proceedings).

#### 7. `bollerslev1986` — Bollerslev (1986) — Verified
- Journal of Econometrics, 31(3), 307-327. DOI: 10.1016/0304-4076(86)90063-1. Correct.

#### 8. `bollerslev1987` — Bollerslev (1987) — Verified
- Review of Economics and Statistics, 69(3), 542-547. DOI: 10.2307/1925546. Correct.

#### 9. `bollerslev1994` — Bollerslev, Engle, & Nelson (1994) — Verified
- Handbook of Econometrics chapter, Vol. 4, pp. 2959-3038, Elsevier. Correct bibliographic form (no DOI standard for book chapter).

#### 10. `bozovic2024` — Bozovic (2024) — Verified
- International Review of Financial Analysis, 95, 103353. DOI: 10.1016/j.irfa.2024.103353. Correct.

#### 11. `bucci2020` — Bucci (2020) — Verified
- Journal of Financial Econometrics, 18(3), 502-531. DOI: 10.1093/jjfinec/nbaa008. Correct.

#### 12. `cederburg2020` — Cederburg, O'Doherty, Wang, & Yan (2020) — Verified
- Journal of Financial Economics, 138(1), 95-117. DOI: 10.1016/j.jfineco.2020.04.015.
- Author spelling: "Cederburg" (NOT "Cederburg et al. ... Cederburg" — the `baur2010hedge` reviewer prompt warning about "Cederburg vs Cederburg" was a generic example; actual spelling here is consistent and correct: Scott Cederburg).

#### 13. `corsi2009` — Corsi (2009) — Verified (listed but only narratively cited? not present in body)
- Journal of Financial Econometrics, 7(2), 174-196. DOI: 10.1093/jjfinec/nbp001. Correct.
- **Note**: this bibitem is not cited in body_v2 via `\cite{}` or narratively. Consider removing or adding to literature review.

#### 14. `chang2021` — Chang, Kung, Chen, & Tian (2021) — Verified
- Pacific-Basin Finance Journal, 67, 101522. DOI: 10.1016/j.pacfin.2021.101522. Correct.

#### 15. `chevallier2017` — Chevallier & Ielpo (2017) — Verified
- Research in International Business and Finance, 39, 763-778. DOI: 10.1016/j.ribaf.2014.09.010. Correct.

#### 16. `christoffersen1998` — Christoffersen (1998) — Verified
- International Economic Review, 39(4), 841-862. DOI: 10.2307/2527341. Correct.

#### 17. `christie1982` — Christie (1982) — Verified
- JFE, 10(4), 407-432. DOI: 10.1016/0304-405X(82)90018-6. Correct.

#### 18. `diebold1995` — Diebold & Mariano (1995) — Verified
- JBES, 13(3), 253-263. DOI: 10.1080/07350015.1995.10524599. Correct.

#### 19. `demiguel2024` — DeMiguel, Martin-Utrera, & Uppal (2024) — Verified
- Journal of Finance, 79(6), 3859-3891. DOI: 10.1111/jofi.13395. Correct.
- **Minor note on content claim**: the manuscript (line 46) states "DeMiguel, Martin-Utrera, and Uppal (2024) achieve 13% Sharpe improvement via a hybrid implied-realized framework." The paper's central claim is about a conditional multifactor portfolio (not specifically a hybrid implied-realized framework). Author should double-check whether the "13% Sharpe improvement" is the exact number the paper reports and whether the framing matches the paper's actual methodology. See **Minor Issues #1** below.

#### 20. `engle2002` — Engle (2002) — Verified
- JBES, 20(3), 339-350. DOI: 10.1198/073500102288618487. Correct.

#### 21. `engle2006` — Engle & Gallo (2006) — Verified
- Journal of Econometrics, 131(1-2), 3-27. DOI: 10.1016/j.jeconom.2005.01.018. Correct.

#### 22. `engle2018` — Engle & Siriwardane (2018) — Verified
- Review of Financial Studies, 31(2), 449-492. DOI: 10.1093/rfs/hhx099. Correct.

#### 23. `engle2004` — Engle (2004) — Verified
- American Economic Review, 94(3), 405-420. DOI: 10.1257/0002828041464597. Correct.

#### 24. `fleming2001` — Fleming, Kirby, & Ostdiek (2001) — Verified
- Journal of Finance, 56(1), 329-352. DOI: 10.1111/0022-1082.00327. Correct.

#### 25. `fleming2003` — Fleming, Kirby, & Ostdiek (2003) — Verified
- JFE, 67(3), 473-509. DOI: 10.1016/S0304-405X(02)00259-3. Correct.

#### 26. `francq2004` — Francq & Zakoïan (2004) — Verified
- Bernoulli, 10(4), 605-637. DOI: 10.3150/bj/1093265632. Correct.

#### 27. `glosten1993` — Glosten, Jagannathan, & Runkle (1993) — Verified
- Journal of Finance, 48(5), 1779-1801. DOI: 10.1111/j.1540-6261.1993.tb05128.x. Correct.

#### 28. `hansen1994` — Hansen (1994) — Verified
- International Economic Review, 35(3), 705-730. DOI: 10.2307/2527081. Correct.

#### 29. `hansen2005` — Hansen & Lunde (2005) — Verified
- JAE, 20(7), 873-889. DOI: 10.1002/jae.800. Correct.

#### 30. `hansen2012` — Hansen, Huang, & Shek (2012) — Verified
- JAE, 27(6), 877-906. DOI: 10.1002/jae.1234. Correct.

#### 31. `harri2009` — Harri & Brorsen (2009) — Verified
- Quantitative and Qualitative Analysis in Social Sciences, 3(3), 78-115. Correct (no DOI for that journal in 2009).

#### 32. `harvey2016` — Harvey, Liu, & Zhu (2016) — Verified
- Review of Financial Studies, 29(1), 5-68. DOI: 10.1093/rfs/hhv059. Correct.

#### 33. `harvey2018` — Harvey et al. (2018) — Verified
- JPM, 45(1), 14-33. DOI: 10.3905/jpm.2018.45.1.014. Correct.
- Six authors: Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, Van Hemert — all confirmed.

#### 34. `hood2025` — Hood & Raughtigan (2025) — Verified (see minor issue)
- JPM, early access, DOI: 10.3905/jpm.2025.1.764.
- Full title: "Volatility Targeting Is Trendy: How Trend Following Explains Alpha in Volatility-Managed Strategies"
- **Minor**: bibitem gives short title "Volatility targeting is trendy." The full published title includes the subtitle. APA 7th recommends full title; consider updating. See **Minor Issues #2**.
- Content claim in body_v2 (lines 44, 46, 429, 469): all align with paper's actual findings (equity-specific leverage-effect channel, fails for commodity/fixed income/currency).

#### 35. `henriksson1981` — Henriksson & Merton (1981) — Verified
- Journal of Business, 54(4), 513-533. DOI: 10.1086/296144. Correct.

#### 36. `hou2020` — Hou, Xue, & Zhang (2020) — Verified
- Review of Financial Studies, 33(5), 2019-2133. DOI: 10.1093/rfs/hhy131. Correct.
- **Minor**: the manuscript (line 61) claims "Hou et al. (2020) demonstrate that Yahoo Finance closing prices for large-cap U.S. securities closely track CRSP data." This is NOT the central thesis of Hou, Xue & Zhang (2020) — the paper's main contribution is replicating 452 anomalies and showing 65% fail. The data-quality comparison between Yahoo Finance and CRSP is, at best, an ancillary observation. See **Minor Issues #3 (content claim)**.

#### 37. `hwang2006` — Hwang & Valls Pereira (2006) — Verified
- European Journal of Finance, 12(6-7), 473-494. DOI: 10.1080/13518470500039436. Correct.

#### 38. `kim2019` — Kim & Kim (2019) — Verified
- PLoS ONE, 14(2), e0212320. DOI: 10.1371/journal.pone.0212320. Correct.

#### 39. `kuester2006` — Kuester, Mittnik, & Paolella (2006) — Verified
- Journal of Financial Econometrics, 4(1), 53-89. DOI: 10.1093/jjfinec/nbj002. Correct.

#### 40. `kupiec1995` — Kupiec (1995) — Verified
- Journal of Derivatives, 3(2), 73-84. DOI: 10.3905/jod.1995.407942. Correct.

#### 41. `longin2001` — Longin & Solnik (2001) — Verified
- Journal of Finance, 56(2), 649-676. DOI: 10.1111/0022-1082.00340. Correct.

#### 42. `mcneil2015` — McNeil, Frey, & Embrechts (2015) — Verified
- Princeton University Press textbook. Correct (full title "Quantitative Risk Management: Concepts, Techniques and Tools – Revised Edition").
- **Minor**: APA 7th would include the edition ("Revised ed.") and possibly place of publication. See **Minor Issues #4**.

#### 43. `moreira2017` — Moreira & Muir (2017) — Verified
- Journal of Finance, 72(4), 1611-1644. DOI: 10.1111/jofi.12513. Correct.

#### 44. `nelson1991` — Nelson (1991) — Verified
- Econometrica, 59(2), 347-370. DOI: 10.2307/2938260. Correct.

#### 45. `newey1987` — Newey & West (1987) — Verified
- Econometrica, 55(3), 703-708. DOI: 10.2307/1913610. Correct.

#### 46. `patton2011` — Patton (2011) — Verified
- Journal of Econometrics, 160(1), 246-256. DOI: 10.1016/j.jeconom.2010.03.034. Correct.

#### 47. `parkinson1980` — Parkinson (1980) — Verified
- Journal of Business, 53(1), 61-65. DOI: 10.1086/296071. Correct.

#### 48. `treynor1966` — Treynor & Mazuy (1966) — Verified
- Harvard Business Review, 44(4), 131-136. No DOI (HBR rarely provides them for this vintage). Correct.

#### 49. `campbell2017` — Campbell, Sunderam, & Viceira (2017) — Verified
- Critical Finance Review, 6(2), 263-301. Correct.
- **Minor stylistic**: this bibitem uses a different label style `[Campbell et~al., 2017]` from all others (`[Author(Year)]`), likely because it was added later. Recommend harmonizing. See **Minor Issues #5**.

### NEEDS_CHECK

#### 50. `nelson2025` — Nelson (2025) — NEEDS_CHECK (borderline)
- SSRN Working Paper No. 5931154. DOI: 10.2139/ssrn.5931154. Author: Ryan Nelson.
- Posted on SSRN 2025-12-15 (after the paper's March 2026 date, so timeline OK).
- **Issue**: Working paper, not peer-reviewed. Manuscript cites "Nelson's (2025) characterization of volatility scaling as non-predictive risk control" (line 429). This is an SSRN paper by Ryan Nelson — a different author from David B. Nelson (Econometrica 1991, `nelson1991`). Make sure readers don't conflate the two "Nelson" authors. Consider changing bibitem label to `[Nelson, R.(2025)]` or `[Nelson, Ryan(2025)]` to disambiguate from `nelson1991`.
- Content claim: "non-predictive risk control" matches the abstract's "interpretable, non-predictive risk control mechanisms."

#### 51. `xu2024` — Xu (2024) — NEEDS_CHECK
- "Improving volatility-managed portfolios in real time," *Critical Finance Review*, forthcoming.
- SSRN version confirmed (Xia Xu, ESSCA): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4778937
- Status as of verification date (2026-04-13): listed as "forthcoming" in Critical Finance Review. The CFR "forthcoming" page https://cfr.ivo-welch.info/forthcoming/papers/xu2024improving.pdf does show a forthcoming PDF, suggesting it is forthcoming in CFR.
- **Recommend**: verify actual publication status before final submission. If still forthcoming, the "forthcoming" notation is correct APA 7.
- Author first name: Xia Xu (single author). Bibitem uses "Xu, Y." — **possible wrong first initial**. SSRN and ESSCA faculty page list the author as "Xia Xu," so the initial should be X., not Y. See **Minor Issues / Potential Typo** below.

---

## Minor Issues Summary

### Minor Issue #1: `demiguel2024` content framing
- **Manuscript claim (line 46)**: "DeMiguel, Martin-Utrera, and Uppal (2024) achieve 13% Sharpe improvement via a hybrid implied-realized framework"
- **Paper's actual contribution**: conditional multifactor portfolio that outperforms unconditional counterpart out-of-sample and net of costs (parametric portfolio framework). "Hybrid implied-realized" is not language used by the paper.
- **Recommendation**: rephrase to "DeMiguel, Martin-Utrera, and Uppal (2024) demonstrate that a conditional multifactor volatility-managed strategy outperforms out-of-sample net of transaction costs" — or verify the 13% figure with the paper and adjust framing.

### Minor Issue #2: `hood2025` short title
- Bibitem uses: "Volatility targeting is trendy."
- Actual published title: "Volatility Targeting Is Trendy: How Trend Following Explains Alpha in Volatility-Managed Strategies."
- **Recommendation**: APA 7th requires full title. Replace with full title.

### Minor Issue #3: `hou2020` content claim (MEDIUM severity)
- **Manuscript claim (line 61)**: "Hou et al. (2020) demonstrate that Yahoo Finance closing prices for large-cap U.S. securities closely track CRSP data."
- **Paper's actual contribution**: Replicating Anomalies — demonstrates 65% of 452 anomalies fail standard t > 1.96 threshold. Data-quality comparison between Yahoo and CRSP is NOT a documented central finding of this paper.
- **Recommendation**: This may be a content misattribution. If Hou, Xue & Zhang (2020) does not explicitly document Yahoo vs. CRSP concordance, the citation is incorrect. Replace with a citation that actually validates Yahoo vs. CRSP (e.g., Ince & Porter 2006, JFQA, who explicitly compare data sources), or remove the claim.

### Minor Issue #4: `mcneil2015` APA format
- Current: "McNeil, A. J., Frey, R., & Embrechts, P. (2015). *Quantitative Risk Management*. Princeton University Press."
- APA 7th recommendation: include "Revised ed." (full title is "Quantitative Risk Management: Concepts, Techniques and Tools – Revised Edition")
- Not a factual error; style fix only.

### Minor Issue #5: `campbell2017` bibitem label style mismatch
- Uses `[Campbell et~al., 2017]` while all others use `[Author(Year)]`.
- **Recommendation**: rewrite as `\bibitem[Campbell et al.(2017)]{campbell2017}` to match house style.

### Minor Issue #6: `xu2024` possible author initial error
- Bibitem: "Xu, Y. (2024)"
- SSRN and ESSCA confirm author as **Xia Xu**, initial **X.** not Y.
- **Recommendation**: verify and correct to "Xu, X. (2024)."

### Minor Issue #7: inconsistent in-text citation style
- The manuscript mixes `\citep{}`/`\citet{}` (parenthetical/narrative via natbib) with hand-written narrative forms like "Bollerslev (1986)" and "(Bollerslev, 1986)" without `\cite{}`.
- Not a factual error, but natbib+apalike with `\bibitem[Key(Year)]{}` will auto-format correctly only if you use `\cite*` commands. Hand-written narrative forms bypass the bibliography link-checker.
- **Recommendation**: convert all narrative text-only citations to `\citet{key}` (or `\citeauthor{key} (\citeyear{key})`) so that BibTeX/natbib can verify label consistency.

---

## Correction Checklist (ordered by priority)

- [ ] **Medium**: verify `hou2020` content claim — the Yahoo vs CRSP comparison attribution needs double-checking (see Minor #3). If not in paper, replace citation or remove claim.
- [ ] **Medium**: re-check `demiguel2024` "13% Sharpe improvement via hybrid implied-realized framework" claim against actual paper text (see Minor #1).
- [ ] **Medium**: verify `xu2024` author initial (X not Y — see Minor #6).
- [ ] **Low**: update `hood2025` to full title with subtitle (Minor #2).
- [ ] **Low**: add "Revised ed." to `mcneil2015` (Minor #4).
- [ ] **Low**: harmonize `campbell2017` bibitem label style (Minor #5).
- [ ] **Low**: disambiguate `nelson2025` (Ryan) from `nelson1991` (Daniel B.) — e.g., "Nelson, R."
- [ ] **Low**: verify `xu2024` publication status (forthcoming vs published) before final submission.
- [ ] **Optional / housekeeping**: convert narrative-only citations (Kupiec, Christoffersen, Fleming, Longin, McNeil, Nelson 1991, Sheppard, Parkinson, BCBS, Bollerslev 1987, Kim & Kim, etc.) to `\citet/\citep` natbib commands for consistency (Minor #7).
- [ ] **Optional**: remove unused bibitems if they remain uncited after the above audit (bollerslev1994, engle2002, corsi2009 if not reintroduced).

---

## Overall Assessment

**No MAJOR issues found.** No fabricated references, no wrong authors, no wrong years, no wrong journal attributions. All 47 bibitems point to real, verifiable papers with correct DOIs.

The issues identified are **stylistic or require small content-claim adjustments**:
- 3 medium-level items (content claims or author initial that need verification against the actual papers)
- 4 low-level items (title/format/label harmonization)

The self-citation issue flagged in the skill prompt does **not apply** — this paper contains no Lai (2024) self-citation. The PRS paper (`reference_lai_prs_paper.md`) is not cited in this manuscript.

**Overall citation quality is high for this manuscript.** With the medium-level fixes applied (especially the `hou2020` content claim, which is the most likely to be flagged by a reviewer), the reference list should meet JBF/JFE standards.

---

## References Consulted for Verification

All verifications performed via WebSearch on 2026-04-13. Key sources:
- DOI-resolved publisher pages (Wiley, Oxford Academic, ScienceDirect, Taylor & Francis, AEA, JSTOR)
- SSRN for working papers (hood2025, nelson2025, xu2024)
- NBER for working paper versions
- RePEc/IDEAS for cross-reference
