# Citation Verification Report -- Round 3

**Manuscript**: When Volatility Targeting Crowds: Quantifying the Tipping Point via Agent-Based Simulation
**File**: `paper/vt-crowding-abm/main.tex` (v1.5)
**Date**: 2026-04-05
**Round**: 3 (final follow-up verifying Round 2 fixes)
**Focus**: (1) Bouchaud orphan removed? (2) ECB title fixed? (3) LeBaron + Danielsson correct? (4) Cole correct? (5) Any orphans or phantoms?
**Total Citations**: 13 (in-text) / 13 (bibliography)
**Verified**: 11 | **Minor Issues**: 2 | **Errors Found**: 0

---

## Summary

| Status | Count | Percentage |
|--------|-------|------------|
| ✓ Verified | 11 | 85% |
| ⚠ Minor Issues | 2 | 15% |
| ✗ Errors Found | 0 | 0% |

**Round 2 to Round 3 comparison**: All three HIGH/MEDIUM priority items from Round 2 have been resolved: (1) the Bouchaud orphan entry has been removed entirely, (2) the ECB title has been corrected to the verified title "Volatility-targeting strategies and the market sell-off," and (3) Cole (2017) is correctly attributed. Two LOW-priority minor issues remain (Perchet cite key cosmetic mismatch; Danielsson thematic fit nuance). The bibliography is now clean -- 13 in-text citation keys map one-to-one to 13 bibliography entries with zero orphans and zero phantoms.

---

## Round 2 Fix Verification

### FIX 1: Bouchaud orphan entry -- RESOLVED ✓

**Round 2 issue**: After re-attributing the USD 2T figure from Bouchaud to Cole, the `bouchaud2018` bib entry remained with no in-text citation (orphan).

**Current state**: No occurrence of "bouchaud" anywhere in `main.tex`. The entry has been completely removed. Confirmed via case-insensitive search: zero matches.

**Status**: ✓ Fully resolved. The bibliography is orphan-free.

### FIX 2: ECB title -- RESOLVED ✓

**Round 2 issue**: Line 302 still read "Procyclicality of volatility targeting strategies" -- wrong title.

**Current state** (line 297):
```latex
\newblock Volatility-targeting strategies and the market sell-off.
```

**Verification**: The ECB FSR May 2020 Box 2 is indeed titled "Volatility-targeting strategies and the market sell-off" (confirmed: [ECB website](https://www.ecb.europa.eu/press/financial-stability-publications/fsr/focus/2020/html/ecb.fsrbox202005_02~f6616db9be.en.html)). The bibliography entry now matches exactly.

**Status**: ✓ Fully resolved.

### FIX 3: Cole (2017) -- Verified correct ✓

**Round 1 origin**: USD 2T AUM was misattributed to Bouchaud (2018). Corrected in v1.3 to Cole (2017).

**Current state** (line 54): `\citep{cole2017}` -- correctly attributes the claim "short-volatility and volatility-sensitive strategies collectively manage over USD 2 trillion in assets" to Cole.

**Verification**:
- **Author**: Christopher Cole, CFA, founder of Artemis Capital Management. ✓
- **Title**: "Volatility and the Alchemy of Risk" (full subtitle: "Reflexivity in the Shadows of Black Monday 1987"). The bib entry uses the short title. ✓ Acceptable.
- **Year**: October 2017. ✓
- **Publisher**: Artemis Capital Management. Bib entry says "Artemis Capital Management, Research Report." ✓
- **USD 2T claim**: Cole (2017) estimates "the global short volatility trade represents an estimated $2+ trillion in financial engineering strategies." The manuscript's paraphrase is accurate. ✓
- **Note**: The ECB FSR May 2020 Box 2 independently cites a similar figure ("funds with assets under management worth up to USD 2 trillion invested in some form of volatility strategies"), suggesting convergent sourcing. Cole (2017) is the primary origin.

**Status**: ✓ Verified. The re-attribution is correct and the content claim is accurate.

### Perchet cite key -- Still minor, unchanged ⚠

**Round 1/2 issue**: Cite key `perchet2016` vs. bib display year 2015.

**Current state**: Line 75 uses `\citep{perchet2016}`; line 325 shows `\bibitem[Perchet et~al.(2015)]{perchet2016}`. The rendered output correctly shows "(Perchet et al., 2015)" to the reader.

**Verification**: The paper was published in The Journal of Alternative Investments, Volume 18, Issue 3, Winter 2015, pages 21--38 ([JAI link](https://jai.pm-research.com/content/18/3/21)). The DOI (10.3905/jai.2016.18.3.021) contains "2016" as a publisher convention, but the actual publication date is December 2015. The bibliography entry year (2015) is correct.

**Status**: ⚠ LOW priority. The reader sees the correct year. The cite key `perchet2016` is only a source-level cosmetic issue. See Minor Issue #1 below.

---

## New & Revised Citations -- Full Verification

### ✓ Cole (2017) -- Verified

- **Bib entry** (lines 330--333): `cole2017`
- **Author**: Christopher Cole, CFA. ✓
- **Title**: "Volatility and the alchemy of risk." ✓ (short title; full subtitle omitted -- acceptable for a bib entry)
- **Publisher**: Artemis Capital Management, Research Report. ✓
- **Year**: 2017. ✓
- **Content claim** (line 54): "short-volatility and volatility-sensitive strategies collectively manage over USD 2 trillion in assets." ✓ Accurately represents Cole's estimate.
- **APA format**: Acceptable for an industry research report (not a journal article). No DOI exists; a URL to artemiscm.com/research would be a quality enhancement but is not required.

### ✓ LeBaron (2006) -- Verified

- **Bib entry** (lines 340--343): `lebaron2006`
- **Author**: Blake LeBaron. ✓
- **Title**: "Agent-based computational finance." ✓
- **Source**: In L. Tesfatsion and K. L. Judd (Eds.), *Handbook of Computational Economics*, Vol. 2, pp. 1187--1233. Elsevier. ✓ (Chapter 24 of the Handbook; all details match [IDEAS/RePEc](https://ideas.repec.org/h/eee/hecchp/2-24.html) and [Elsevier](https://shop.elsevier.com/books/handbook-of-computational-economics/tesfatsion/978-0-444-51253-6))
- **Content claim** (line 56): "ABMs have proven effective for studying feedback-driven market dynamics \citep{lebaron2006, danielsson2012}." ✓ LeBaron (2006) is the canonical survey of agent-based computational finance, covering heterogeneous agent models, artificial stock markets, and feedback dynamics. The claim is accurate.
- **APA format**: ✓ Correct for a book chapter.

### ⚠ Danielsson, Shin, and Zigrand (2012) -- Verified with nuance

- **Bib entry** (lines 335--338): `danielsson2012`
- **Authors**: Jon Danielsson, Hyun Song Shin, Jean-Pierre Zigrand. ✓
- **Title**: "Procyclical leverage and endogenous risk." ✓
- **Source**: "Working Paper, London School of Economics." -- Approximately correct. The paper circulated as an SSRN working paper (SSRN 1360866, first posted 2009, revised October 2012). It was never published in a peer-reviewed journal under this exact title. A related version titled "Endogenous and Systemic Risk" appeared as an NBER book chapter (in Haubrich & Lo (Eds.), *Quantifying Systemic Risk*, U. Chicago Press, 2013, pp. 73--94).
- **Year**: 2012. ✓ Matches the SSRN revision date (October 4, 2012).
- **Content claim** (line 56): Cited alongside LeBaron as evidence that "ABMs have proven effective for studying feedback-driven market dynamics." ⚠ The Danielsson et al. paper uses an equilibrium model (not an ABM) to show that VaR-based risk management creates procyclical leverage and endogenous risk through feedback dynamics. The paper is thematically appropriate (feedback-driven dynamics, procyclical behavior, endogenous risk) but is not strictly an "ABM" paper.
- **Assessment**: The citation is defensible because the sentence says "feedback-driven market dynamics" (which Danielsson et al. clearly studies), and the ABM qualifier modifies the broader claim. However, a reader familiar with the Danielsson paper might note the mismatch. See Minor Issue #2.

---

## Previously Verified Citations (spot-checked, all unchanged)

| # | Citation | Key | Lines | Status |
|---|----------|-----|-------|--------|
| 1 | Moreira and Muir (2017) | `moreira2017` | 320--323 | ✓ Unchanged, verified |
| 2 | Harvey, Hoyle, et al. (2018) | `harvey2018` | 310--313 | ✓ Unchanged, verified |
| 3 | Baltas (2019) | `baltas2019` | 280--283 | ✓ Unchanged, verified |
| 4 | Gennotte and Leland (1990) | `gennotte1990` | 300--303 | ✓ Unchanged, verified |
| 5 | Brunnermeier and Pedersen (2009) | `brunnermeier2009` | 290--293 | ✓ Unchanged, verified |
| 6 | Harvey, Liu, and Zhu (2016) | `harvey2016` | 305--308 | ✓ Unchanged, verified |
| 7 | Kyle (1985) | `kyle1985` | 315--318 | ✓ Unchanged, verified |
| 8 | Bookstaber, Paddrik, and Tivnan (2014) | `bookstaber2014` | 285--288 | ✓ Unchanged, verified* |

*Note on Bookstaber et al.: The bib entry cites the 2014 OFR Working Paper version. This paper was subsequently published as Bookstaber, R., Paddrik, M., & Tivnan, B. (2018), "An agent-based model for financial vulnerability," *Journal of Economic Interaction and Coordination*, 13, 433--466. Citing the working paper version is acceptable (it is the version most commonly referenced), but upgrading to the journal version would strengthen the reference. This is purely optional and not flagged as an issue.

---

## Orphan & Phantom Cross-Check

### Method
Extracted all `\cite`/`\citet`/`\citep` keys from the body text and all `\bibitem` keys from the bibliography using regex, then compared the two sets.

### In-text citation keys (13):
`baltas2019`, `bookstaber2014`, `brunnermeier2009`, `cole2017`, `danielsson2012`, `ecb2020`, `gennotte1990`, `harvey2016`, `harvey2018`, `kyle1985`, `lebaron2006`, `moreira2017`, `perchet2016`

### Bibliography entry keys (13):
`baltas2019`, `bookstaber2014`, `brunnermeier2009`, `cole2017`, `danielsson2012`, `ecb2020`, `gennotte1990`, `harvey2016`, `harvey2018`, `kyle1985`, `lebaron2006`, `moreira2017`, `perchet2016`

### Result:
- **Orphans** (in bibliography but not cited): **0** ✓
- **Phantoms** (cited but no bibliography entry): **0** ✓
- **One-to-one match**: All 13 keys match exactly. ✓

---

## Minor Issues (2 remaining, both LOW priority)

### ⚠ Minor Issue #1: Perchet cite key cosmetic mismatch (carryover from Round 1)

**Lines 75, 325**: Cite key `perchet2016` vs. displayed year 2015.

The rendered LaTeX output shows "(Perchet et al., 2015)" which is correct. The internal cite key `perchet2016` is only visible in the `.tex` source. The DOI contains "2016" as a publisher convention, which likely caused the original mismatch.

**Recommended fix** (optional):
```latex
% Line 75: change
\citep{perchet2016}
% to
\citep{perchet2015}

% Line 325: change
\bibitem[Perchet et~al.(2015)]{perchet2016}
% to
\bibitem[Perchet et~al.(2015)]{perchet2015}
```

**Priority**: LOW. Does not affect reader experience or bibliographic accuracy.

### ⚠ Minor Issue #2: Danielsson et al. (2012) -- not strictly an ABM paper

**Line 56**: "ABMs have proven effective for studying feedback-driven market dynamics \citep{lebaron2006, danielsson2012}"

The sentence groups Danielsson et al. with LeBaron under the umbrella of ABM effectiveness. While Danielsson et al. studies feedback-driven dynamics (procyclical leverage, VaR-induced selling spirals), it uses an analytical equilibrium model, not an agent-based model.

**Options** (all acceptable):
1. **Keep as-is**: The sentence is about "feedback-driven market dynamics" broadly, and the ABM qualifier applies primarily to LeBaron. A careful reader would understand the distinction. This is the lowest-effort option.
2. **Rephrase slightly**: Split the citation context:
   ```latex
   ABMs have proven effective for studying feedback-driven market dynamics
   \citep{lebaron2006}, and analytical models have demonstrated how
   risk-management constraints amplify endogenous risk \citep{danielsson2012},
   though applications to volatility-targeting strategies remain absent
   from the literature.
   ```
3. **Replace Danielsson with a pure ABM reference**: E.g., Thurner, Farmer, & Geanakoplos (2012), "Leverage causes fat tails and clustered volatility," *Quantitative Finance*, 12(5), 695--707 -- which uses an ABM with leveraged agents and produces feedback-driven dynamics.

**Priority**: LOW. The current text is defensible; a reviewer is unlikely to flag this. Option 2 would be the cleanest if any revision is done.

---

## Correction Checklist (Round 3)

### Resolved since Round 2
- [x] ~~Remove Bouchaud orphan entry~~ -- DONE (entry completely removed)
- [x] ~~Fix ECB title~~ -- DONE (now reads "Volatility-targeting strategies and the market sell-off")
- [x] ~~Cole (2017) re-attribution~~ -- Confirmed correct (resolved in Round 1->2, stable)

### Still open (LOW priority, optional)
- [ ] **Perchet cite key** (cosmetic): Change `perchet2016` to `perchet2015` in lines 75 and 325
- [ ] **Danielsson citation context** (optional): Consider rephrasing line 56 to distinguish ABM (LeBaron) from analytical model (Danielsson), or keep as-is
- [ ] **Cole subtitle** (optional): Add full subtitle "Reflexivity in the shadows of Black Monday 1987" and URL to bib entry
- [ ] **Bookstaber journal upgrade** (optional): Update from OFR WP 14-05 (2014) to JEIC 13, 433--466 (2018)

---

## Overall Assessment

**The bibliography is now clean.** All three actionable items from Round 2 have been resolved:

1. **Bouchaud orphan**: Removed entirely. Zero occurrences of "bouchaud" in the file.
2. **ECB title**: Corrected to the verified title "Volatility-targeting strategies and the market sell-off."
3. **Cole attribution**: Stable and correct since Round 2. The USD 2T figure is properly sourced.

The 13 citations form a perfect one-to-one mapping between in-text keys and bibliography entries. No orphans, no phantoms. All bibliographic details (authors, titles, years, journals, pages) have been verified against primary sources via web search.

The two remaining minor issues (Perchet cite key, Danielsson thematic fit) are cosmetic/stylistic and do not affect the accuracy, completeness, or reader experience of the reference list. **No further rounds of citation verification are needed** unless new citations are added in a future revision.

### Verification Trail

| Citation | Verified Against |
|----------|-----------------|
| Cole (2017) | [Artemis Capital](https://www.artemiscm.com/chris-cole); [CAIA hosted PDF](https://caia.org/sites/default/files/03_volatility_4-2-18.pdf) |
| ECB (2020) | [ECB FSR Box 2](https://www.ecb.europa.eu/press/financial-stability-publications/fsr/focus/2020/html/ecb.fsrbox202005_02~f6616db9be.en.html) |
| LeBaron (2006) | [IDEAS/RePEc](https://ideas.repec.org/h/eee/hecchp/2-24.html); [Brandeis PDF](https://people.brandeis.edu/~blebaron/wps/hbook.pdf) |
| Danielsson et al. (2012) | [SSRN 1360866](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1360866); [riskresearch.org](https://www.riskresearch.org/papers/DanielssonShinZigrand2012/) |
| Perchet et al. (2015) | [JAI 18(3)](https://jai.pm-research.com/content/18/3/21) |
| Bookstaber et al. (2014) | [OFR](https://www.financialresearch.gov/working-papers/2014/07/29/an-agent-based-model-for-financial-vulnerability/); [Springer JEIC 2018](https://link.springer.com/article/10.1007/s11403-017-0188-1) |
| Moreira & Muir (2017) | Previously verified Round 1 |
| Harvey et al. (2018) | Previously verified Round 1 |
| Baltas (2019) | Previously verified Round 1 |
| Gennotte & Leland (1990) | Previously verified Round 1 |
| Brunnermeier & Pedersen (2009) | Previously verified Round 1 |
| Harvey, Liu, & Zhu (2016) | Previously verified Round 1 |
| Kyle (1985) | Previously verified Round 1 |
