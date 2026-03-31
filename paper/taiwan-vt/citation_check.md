# Citation Verification Report: Taiwan VT Paper

**Paper:** Volatility Targeting in the Taiwan Stock Market
**Author:** Yi-Hao Lai
**Review Date:** 2026-03-30
**Reviewer:** VolPred Research System (Claude Opus 4.6)

---

## 1. Cross-Check Summary

| Metric | Count |
|--------|-------|
| Unique citation keys used in body | 30 |
| Unique bibitem keys in bibliography | 30 |
| Orphan references (in bib but not cited) | 0 |
| Missing references (cited but not in bib) | 0 |
| Perfect match | YES |

## 2. Complete Citation Key Mapping

| # | Citation Key | In Body? | In Bibliography? | Status |
|---|-------------|----------|-------------------|--------|
| 1 | `ang2002` | YES | YES | OK |
| 2 | `barber2009` | YES | YES | OK |
| 3 | `barclay2003` | YES | YES | OK |
| 4 | `barndorff2010` | YES | YES | OK |
| 5 | `black1976` | YES | YES | OK |
| 6 | `bollerslev1986` | YES | YES | OK |
| 7 | `bollerslev1992` | YES | YES | OK |
| 8 | `bozovic2024` | YES | YES | OK |
| 9 | `christie1982` | YES | YES | OK |
| 10 | `corsi2009` | YES | YES | OK |
| 11 | `diebold1995` | YES | YES | OK |
| 12 | `engle1982` | YES | YES | OK |
| 13 | `engle2013` | YES | YES | OK |
| 14 | `eun1989` | YES | YES | OK |
| 15 | `fleming2001` | YES | YES | OK |
| 16 | `gagnon2010` | YES | YES | OK |
| 17 | `glosten1993` | YES | YES | OK |
| 18 | `hamao1990` | YES | YES | OK |
| 19 | `harvey2016` | YES (via `\citet`, `\citep`, `\citealt`) | YES | OK |
| 20 | `harvey2018` | YES | YES | OK |
| 21 | `hwang2006` | YES | YES | OK |
| 22 | `jpmorgan1996` | YES | YES | OK |
| 23 | `kupiec1995` | YES | YES | OK |
| 24 | `lin1994` | YES | YES | OK |
| 25 | `moreira2017` | YES | YES | OK |
| 26 | `nelson1991` | YES | YES | OK |
| 27 | `patton2011` | YES | YES | OK |
| 28 | `rapach2013` | YES | YES | OK |
| 29 | `whaley2000` | YES | YES | OK |
| 30 | `whaley2009` | YES | YES | OK |

## 3. Orphan References

**None.** All 30 bibliography entries are cited at least once in the body.

## 4. Missing References

**None.** All 30 citation keys used in the body have corresponding bibliography entries.

## 5. Format Issues

### 5.1 Bibliography Format Inconsistencies

| # | Issue | Severity | Details |
|---|-------|----------|---------|
| 1 | Inconsistent `et al.` in bibitem labels | LOW | `fleming2001` uses `[Fleming et al.(2001)]` but `barndorff2010` uses `[Barndorff-Nielsen et~al.(2010)]`. The tilde spacing (`et~al.`) should be consistent. |
| 2 | Inconsistent ampersand usage | LOW | Some entries use `\&` (e.g., `Ang, A. \& Chen, J.`), others use `, \&` or `, and`. Standardize per journal style. |
| 3 | Harvey (2016) title uses `\ldots` | LOW | The title reads `\ldots and the cross-section of expected returns`. While accurate (the paper's actual title begins with an ellipsis), some journals require the full title. Verify with PBFJ style guide. |
| 4 | JPMorgan (1996) capitalization | LOW | The bibitem uses `JPMorgan` as author. Some citation styles require corporate authors in a specific format. |
| 5 | Missing DOIs | MEDIUM | No bibliography entries include DOIs. Most journals now require or strongly encourage DOIs for all entries. Add DOIs for all 30 references. |
| 6 | Page number format varies | LOW | Some entries use `pp. 117--136` (Barndorff-Nielsen), others use just `443--494` (Ang \& Chen). Standardize. |

### 5.2 Citation Command Issues

| # | Issue | Severity | Details |
|---|-------|----------|---------|
| 1 | Mixed `\citet` and `\citep` usage is correct | OK | The paper properly uses `\citet` for textual citations and `\citep` for parenthetical citations. |
| 2 | `\citealt` used once | OK | `\citealt{harvey2016}` is used correctly in a parenthetical context where additional parentheses would be redundant (inside `\citealt` within a `\citep`-style parenthetical). |
| 3 | Multi-cite ordering | LOW | In `\citep{engle1982,bollerslev1986}`, the citations are in publication-year order (1982, 1986). Verify that the target journal prefers chronological vs. alphabetical ordering within multi-cites. |

### 5.3 Internal Reference Issues

| # | Issue | Severity | Details |
|---|-------|----------|---------|
| 1 | Internal experiment IDs in footnotes | MEDIUM | The body contains references to "Experiment K472" and "K461" (internal VolPred experiment identifiers). These must be removed or replaced with "supplementary analysis" before journal submission. |
| 2 | Codex review comments in LaTeX source | MEDIUM | Multiple `% Codex-R6-fix:` comments appear in the source. While these are comments (not rendered), they should be cleaned up before submission to avoid accidental inclusion in review materials. |

## 6. Missing References (Recommended Additions)

The following references are relevant to the paper's topics but are not cited:

| # | Reference | Relevance | Priority |
|---|-----------|-----------|----------|
| 1 | Moskowitz, Ooi & Pedersen (2012), "Time series momentum," *JFE* | TZ momentum strategy is a variant of time-series momentum | HIGH |
| 2 | Ledoit & Wolf (2008), "Robust performance hypothesis testing with the Sharpe ratio," *JEmpFin* | Formal Sharpe ratio comparison test (currently missing) | HIGH |
| 3 | Baele (2005), "Volatility spillover effects in European equity markets," *JFQA* | Volatility spillover methodology | MEDIUM |
| 4 | Caporin & McAleer (2012), DCC-GARCH for Asian markets | Asian GARCH applications | MEDIUM |
| 5 | Jegadeesh & Titman (1993), "Returns to buying winners and selling losers," *JoF* | Foundational momentum reference | MEDIUM |
| 6 | Liu et al. (2019), VIX as global fear gauge for emerging markets | VIX proxy for Taiwan | MEDIUM |
| 7 | Jobson & Korkie (1981), "Performance hypothesis testing with the Sharpe and Treynor measures," *JoF* | Alternative Sharpe comparison test | LOW |

## 7. Citation Frequency Analysis

| Citation Key | Times Cited | Sections Used |
|-------------|-------------|---------------|
| `harvey2016` | 10+ | Intro, TZ, Robustness, Discussion, Conclusion |
| `moreira2017` | 6 | Intro, VT, VIX-Proxy, Discussion, Conclusion |
| `ang2002` | 5 | Intro, Leverage, Amplification, Discussion |
| `glosten1993` | 4 | Intro, Methodology, Leverage |
| `bollerslev1986` | 3 | Methodology |
| `black1976` | 3 | Intro, Leverage, TSMC |
| `hamao1990` | 3 | Intro, Spillover |
| `barber2009` | 2 | Intro, Leverage |
| `kupiec1995` | 2 | VaR |
| `diebold1995` | 2 | Methodology, VT |
| All others | 1 each | Various |

## 8. Verification Notes

### Spot-checked bibliographic details:

1. **Moreira & Muir (2017)**: Correct. *Journal of Finance*, 72(4), 1611--1644. Verified.
2. **Harvey et al. (2016)**: Correct. Title does begin with "...and the cross-section". *RFS*, 29(1), 5--68. Verified.
3. **Bollerslev (1986)**: Correct. *Journal of Econometrics*, 31(3), 307--327. Verified.
4. **Glosten et al. (1993)**: Correct. *Journal of Finance*, 48(5), 1779--1801. Verified.
5. **Bozovic (2024)**: Correct. *International Review of Financial Analysis*, 95, 103353. Verified.
6. **Harvey et al. (2018)**: Volume listed as 45(1), 14--33. The article appeared in JPM Fall 2018 issue. The volume/issue should be verified against the publisher. This may be the correct volume for 2018 publication.

---

## Summary

The citation infrastructure is **clean**: zero orphan references, zero missing references, and a perfect 30/30 match between in-text citations and bibliography entries. The main action items are:

1. **Add DOIs** to all bibliography entries (MEDIUM priority)
2. **Remove internal experiment IDs** (K472, K461) from footnotes (MEDIUM priority)
3. **Clean up Codex-R6-fix comments** from LaTeX source (MEDIUM priority)
4. **Add missing foundational references**: Moskowitz et al. (2012), Ledoit & Wolf (2008) (HIGH priority)
5. **Standardize bibliography formatting** (ampersands, et al. spacing, page numbers) (LOW priority)
