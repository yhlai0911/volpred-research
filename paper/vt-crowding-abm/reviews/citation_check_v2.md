# Citation Verification Report -- Round 2

**Manuscript**: When Volatility Targeting Crowds: Quantifying the Tipping Point via Agent-Based Simulation
**Date**: 2026-04-05
**Round**: 2 (follow-up to Round 1 on same date)
**Focus**: Verify Round 1 fixes (Bouchaud->Cole, Perchet title+pages, ECB title) + check new citations added in revision
**Total Citations**: 13 (was 11 in Round 1; +2 new: Cole 2017, Danielsson et al. 2012, LeBaron 2006; Bouchaud 2018 now orphan)
**Verified**: 10 | **Minor Issues**: 3 | **Errors Found**: 0

---

## Summary

| Status | Count | Percentage |
|--------|-------|------------|
| ✓ Verified | 10 | 77% |
| ⚠ Minor Issues | 3 | 23% |
| ✗ Errors Found | 0 | 0% |

**Round 1 vs Round 2 comparison**: The critical ERROR (Bouchaud misattribution of USD 2T) has been resolved by adding Cole (2017) and re-attributing the claim. However, two Round 1 minor issues (ECB title, Perchet cite key) remain unfixed, and one new issue has been introduced (orphan Bouchaud entry). Two new citations (Danielsson et al., LeBaron) have been added, one with a minor issue.

---

## Round 1 Fix Verification

### FIX 1: Bouchaud -> Cole re-attribution -- RESOLVED

**Round 1 error**: USD 2 trillion AUM figure was attributed to `\citep{bouchaud2018}` (a market microstructure textbook that does not discuss VT AUM). The figure originates from Christopher Cole / Artemis Capital Management.

**Revision**: Line 54 now reads `\citep{cole2017}`, and a new bibliography entry has been added (lines 335--338). The body text no longer cites Bouchaud for this claim.

**Verification of Cole (2017)**:
- **Author**: Christopher Cole, CFA, founder of Artemis Capital Management. ✓
- **Title**: "Volatility and the Alchemy of Risk" -- subtitled "Reflexivity in the Shadows of Black Monday 1987". The bib entry uses the short title without subtitle. ✓ Acceptable
- **Year**: October 2017. ✓
- **Publisher**: Artemis Capital Management. The bib entry says "Artemis Capital Management, Research Report." ✓ Accurate -- this is an industry research report, not a peer-reviewed journal article
- **USD 2 trillion claim**: Cole (2017) estimates "the global short volatility trade represents an estimated $2+ trillion in financial engineering strategies." ✓ The manuscript's statement "short-volatility and volatility-sensitive strategies collectively manage over USD 2 trillion in assets" accurately reflects this figure
- **Format**: ⚠ See Minor Issue #1 below (full subtitle and URL recommended)

**Status**: ✓ Core error resolved. The re-attribution is correct.

### FIX 2: Perchet title and pages -- PARTIALLY RESOLVED

**Round 1 issue**: Title was "Inter- and intra-asset diversification in risk-based portfolios with the 1/VIX rule" (not a published title), pages were 48--64 (wrong), year was inconsistent (cite key 2016, entry 2015).

**Revision**: Lines 330--333 now show:
- Title corrected to: "Predicting the success of volatility targeting strategies: Application to equities and other asset classes" ✓
- Pages corrected to: 18(3), 21--38 ✓
- Year changed to 2015 in the bibliography entry ✓

**Remaining issue**: The cite key is still `perchet2016` while the bibliography displays `[Perchet et~al.(2015)]`. This creates a mismatch: `\citep{perchet2016}` in the text (line 75) will render as "(Perchet et al., 2015)" which is correct for the reader, but the cite key is misleading for anyone reading the .tex source. See Minor Issue #2.

### FIX 3: ECB title -- NOT FIXED

**Round 1 issue**: Bibliography title is "Procyclicality of volatility targeting strategies" but the actual ECB FSR May 2020 Box 2 is titled "Volatility-targeting strategies and the market sell-off."

**Current state** (line 302): Still reads `Procyclicality of volatility targeting strategies.` -- **unchanged from Round 1**.

**Status**: ⚠ Still incorrect. See Minor Issue #3.

---

## New Citations Added in Revision

### ✓ Verified: LeBaron (2006)

- **Bib entry** (lines 345--348): `lebaron2006`
- **Bibliographic accuracy**:
  - Author: Blake LeBaron ✓
  - Title: "Agent-based computational finance" ✓
  - Source: In L. Tesfatsion and K. L. Judd (Eds.), *Handbook of Computational Economics*, Vol. 2, pp. 1187--1233. Elsevier ✓
  - This is Chapter 24 of the Handbook. All details match the published record exactly.
- **Content claim**: The manuscript cites this (line 56) as evidence that "ABMs have proven effective for studying feedback-driven market dynamics." ✓ Accurate -- LeBaron (2006) is the canonical survey of agent-based computational finance, covering heterogeneous agent models, artificial stock markets, and feedback dynamics
- **APA format**: ✓ Correct for a book chapter

### ⚠ Minor Issue: Danielsson, Shin, and Zigrand (2012)

- **Bib entry** (lines 340--343): `danielsson2012`
- **Listed as**: "Working Paper, London School of Economics"
- **Bibliographic accuracy**: ⚠ The paper "Procyclical Leverage and Endogenous Risk" by Danielsson, Shin, and Zigrand has a complex publication history:
  - **SSRN working paper**: First posted 2009, revised October 2012 (SSRN 1360866)
  - **NBER book chapter**: A closely related version titled "Endogenous and Systemic Risk" was published in *Quantifying Systemic Risk* (J. Haubrich and A. Lo, eds.), University of Chicago Press, 2013, pp. 73--94 (NBER chapter c12054)
  - The "Procyclical Leverage" title version does NOT appear to have been published in a peer-reviewed journal -- it circulated as a working paper
  - The bib entry description "Working Paper, London School of Economics" is approximately correct but could be more precise
- **Content claim**: Cited alongside LeBaron (2006) as evidence that ABMs are effective for studying "feedback-driven market dynamics." ⚠ The Danielsson et al. paper is about procyclical leverage and VaR-induced feedback, not specifically about agent-based models. It uses an equilibrium model, not an ABM. However, it does model feedback-driven dynamics (VaR constraints creating endogenous risk), so the citation is thematically appropriate even if not a pure ABM paper.
- **Recommendation**: Either (a) rephrase the citation context to "feedback-driven dynamics" rather than "ABMs" specifically, since Danielsson et al. is not an ABM paper; or (b) replace with a more ABM-specific reference; or (c) keep as-is since the thematic relevance to feedback dynamics is clear. Also consider upgrading the bib entry to cite the NBER chapter version if the content matches.

---

## Previously Verified Citations (unchanged, spot-checked)

The following 8 citations from Round 1 were re-checked for any accidental modifications. All remain correct:

1. **Moreira and Muir (2017)** -- ✓ Unchanged, verified
2. **Harvey et al. (2018)** -- ✓ Unchanged, verified
3. **Baltas (2019)** -- ✓ Unchanged, verified
4. **Gennotte and Leland (1990)** -- ✓ Unchanged, verified
5. **Brunnermeier and Pedersen (2009)** -- ✓ Unchanged, verified
6. **Harvey, Liu, and Zhu (2016)** -- ✓ Unchanged, verified
7. **Kyle (1985)** -- ✓ Unchanged, verified
8. **Bookstaber, Paddrik, and Tivnan (2014)** -- ✓ Unchanged, verified

---

## Minor Issues (3 total)

### ⚠ Minor Issue #1: Cole (2017) -- Format Enhancement

**Lines 335--338**:
```latex
\bibitem[Cole(2017)]{cole2017}
Cole, C. (2017).
\newblock Volatility and the alchemy of risk.
\newblock Artemis Capital Management, Research Report.
```

**Issues**:
1. The full title includes a subtitle: "Volatility and the Alchemy of Risk: Reflexivity in the Shadows of Black Monday 1987." Adding the subtitle would improve discoverability.
2. No URL provided. Since this is an industry report (not in a journal database), a URL is important for reader access.

**Recommended correction**:
```latex
\bibitem[Cole(2017)]{cole2017}
Cole, C. (2017).
\newblock Volatility and the alchemy of risk: Reflexivity in the shadows of {Black Monday} 1987.
\newblock Artemis Capital Management, Research Report. Available at
  \url{https://www.artemiscm.com/research}.
```

### ⚠ Minor Issue #2: Perchet cite key mismatch (carryover from Round 1)

**Line 75**: `\citep{perchet2016}` -- cite key says 2016
**Line 330**: `\bibitem[Perchet et~al.(2015)]{perchet2016}` -- bib entry year says 2015

The rendered output will show "(Perchet et al., 2015)" which is correct for the reader. However, the internal cite key `perchet2016` is misleading. The DOI (10.3905/jai.2016.18.3.021) uses 2016 in the DOI string (a publisher convention), but the actual publication year is Winter 2015.

**Recommended correction**: Change cite key from `perchet2016` to `perchet2015` throughout (lines 75 and 330).

### ⚠ Minor Issue #3: ECB (2020) title still incorrect (carryover from Round 1)

**Line 302**: `Procyclicality of volatility targeting strategies.`

The actual title of ECB FSR May 2020 Box 2 is **"Volatility-targeting strategies and the market sell-off"** (verified: https://www.ecb.europa.eu/press/financial-stability-publications/fsr/focus/2020/html/ecb.fsrbox202005_02~f6616db9be.en.html).

**Recommended correction**:
```latex
\newblock Volatility-targeting strategies and the market sell-off.
```

---

## New Issue: Orphan Bibliography Entry

### ⚠ Bouchaud et al. (2018) -- Orphan entry (no in-text citation)

**Lines 290--293**: The `bouchaud2018` bibliography entry remains in the reference list, but after the re-attribution to Cole (2017), there is **no `\cite{bouchaud2018}` anywhere in the body text**. This creates an orphan reference that will appear in the bibliography without being cited.

**Options**:
1. **Remove** the entry entirely (cleanest solution, since the book is no longer relevant to any claim in the paper)
2. **Add a citation** somewhere in the text if the Bouchaud et al. textbook is relevant to the market microstructure discussion (e.g., in the Kyle lambda / price impact discussion in Section 2.2 or the Limitations in Section 4.2)
3. If keeping, note that the Bouchaud et al. book covers order flow, price impact, and Kyle-type models, so a natural placement would be: "Price formation follows a simplified Kyle (1985) model; see also Bouchaud et al. (2018) for a comprehensive treatment of price impact and order flow dynamics."

**Recommendation**: Option 1 (remove) unless you want to cite it for its market microstructure content.

---

## Correction Checklist (Round 2)

### From Round 1 (still open)
- [ ] **Fix ECB title** (line 302): Change from "Procyclicality of volatility targeting strategies" to "Volatility-targeting strategies and the market sell-off"
- [ ] **Fix Perchet cite key** (lines 75, 330): Change `perchet2016` to `perchet2015`

### New in Round 2
- [ ] **Resolve Bouchaud orphan**: Either remove `bouchaud2018` bib entry (lines 290--293) or add an in-text citation
- [ ] **Cole (2017) enhancement** (optional): Add subtitle and URL to bib entry
- [ ] **Danielsson et al. (2012)** (optional): Consider upgrading from "Working Paper, LSE" to the NBER chapter citation, or adjust the text to not imply it is an ABM paper

---

## Overall Assessment

The most critical Round 1 error -- the Bouchaud misattribution of the USD 2 trillion figure -- has been correctly resolved by adding Cole (2017). The Cole citation accurately represents the source of this widely-cited industry estimate. The Perchet title and pages have been corrected. The two new citations (LeBaron 2006, Danielsson et al. 2012) are thematically appropriate, though Danielsson et al. is not strictly an ABM paper.

Three minor issues remain: the ECB title (unchanged from Round 1), the Perchet cite key mismatch (cosmetic), and the orphan Bouchaud entry (created by the fix). None of these affect the substantive accuracy of the paper's claims. The Bouchaud orphan is the most visible issue -- a bibliography entry with no corresponding in-text citation will be flagged by reviewers.

**Priority for Round 3 (if needed)**:
1. Remove or re-cite Bouchaud (HIGH -- orphan entries are a reviewer red flag)
2. Fix ECB title (MEDIUM -- wrong title, verifiable)
3. Fix Perchet cite key (LOW -- cosmetic, reader sees correct year)
4. Enhance Cole entry (LOW -- optional quality improvement)
5. Clarify Danielsson citation context (LOW -- thematic fit is adequate)
