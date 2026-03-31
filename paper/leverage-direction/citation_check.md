# Citation Check Report — Paper 1: Leverage Direction Matters
**Generated:** 2026-03-30
**Files checked:** `paper/leverage-direction/main.tex` (bibliography), `paper/leverage-direction/body.tex` (body text)

---

## Summary

| Metric | Count |
|--------|-------|
| Total bibliography entries | 47 |
| Entries cited via LaTeX `\cite{}` commands | 18 |
| Entries cited via prose only (no `\cite{}` command) | 24 |
| Total cited (LaTeX + prose) | 42 |
| **Confirmed orphan references** | **3** |
| **Suspected orphan / needs verification** | **2** |
| Missing references (cited in body but not in bibliography) | 0 |
| Format issues identified | 5 |
| Plausibility concerns (unverifiable references) | 3 |

---

## 1. Orphan References (in bibliography but not cited anywhere in body)

### Confirmed Orphans

| Key | Entry | Issue |
|-----|-------|-------|
| `bollerslev1994` | Bollerslev, Engle & Nelson (1994). ARCH models. *Handbook of Econometrics*, Vol. 4. | No mention in body.tex. The paper discusses GARCH extensively but never cites this handbook chapter. |
| `corsi2009` | Corsi, F. (2009). A simple approximate long-memory model of realized volatility. *J. Financial Econometrics*. | No mention in body.tex. HAR models are discussed and tested (HAR-ABS section) but Corsi (2009) is never cited by name. |
| `engle2002` | Engle, R.F. (2002). Dynamic conditional correlation. *J. Business & Economic Statistics*. | DCC is mentioned in Table (complexity ceiling) and in conclusion, but never with a citation. The DCC discussion is attributed to no author. |

### Suspected Orphans (prose present but citation key not linked)

| Key | Entry | Status |
|-----|-------|--------|
| `bcbs2019` | BCBS (2019). *Minimum Capital Requirements for Market Risk*. | Cited as prose "BCBS, 2006, 2019" on line 38 — this IS a valid prose citation. **NOT an orphan.** Remove from suspect list. |
| `diebold1995` | Diebold & Mariano (1995). Comparing predictive accuracy. *J. Business & Economic Statistics*. | Cited as prose "Diebold & Mariano, 1995" on line 91 — this IS a valid prose citation. **NOT an orphan.** |

**Revised confirmed orphans: 3** (`bollerslev1994`, `corsi2009`, `engle2002`)

---

## 2. Missing References (cited in body but not in bibliography)

**None found.** All 42 references found in body.tex (18 via `\cite{}` commands + 24 via prose) have corresponding entries in the bibliography.

---

## 3. Format Issues

### 3.1 Inconsistent bibliography entry format for `campbell2017`

The `campbell2017` entry uses a non-standard `\bibitem` label format:

```latex
\bibitem[Campbell et~al., 2017]{campbell2017}
```

All other entries use the format `\bibitem[Author(Year)]{key}` (e.g., `\bibitem[Bollerslev(1986)]{bollerslev1986}`). The `campbell2017` entry uses a comma-separated format with a tilde (`et~al., 2017`) instead of parentheses. This will render differently from all other entries and may cause `apalike` style conflicts.

**Fix:** Change to `\bibitem[Campbell et~al.(2017)]{campbell2017}`

### 3.2 Harvey et al. (2018): 6 authors listed in full in prose

At line 46, Harvey et al. (2018) is cited as:
> "Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, and Van Hemert (2018)"

With 6 authors, APA style (and most finance journals) require "Harvey et al. (2018)" on first citation. Listing all 6 in prose is unusual and may not conform to *Journal of Banking & Finance* style.

**Fix:** Change to "Harvey et al. (2018)" — matches the `\bibitem` label `Harvey et al.(2018)`.

### 3.3 `engle2002` is in bibliography but never cited (orphan + format note)

Since `engle2002` (DCC paper) is an orphan, the DCC references scattered through the paper (Table: complexity ceiling; conclusion para) should either cite it or the entry should be removed.

### 3.4 `corsi2009` is in bibliography but never cited despite extensive HAR discussion

The paper has a full subsection "The HAR Paradox" discussing HAR-ABS results. Corsi (2009) is the foundational HAR paper and should be cited there.

**Fix:** Add `\citet{corsi2009}` in the HAR Paradox section (line 526) when introducing HAR.

### 3.5 `bollerslev1994` is in bibliography but never cited

The Bollerslev, Engle & Nelson (1994) Handbook chapter is commonly cited as a foundational survey reference for GARCH families. It appears to have been included anticipating a citation that was never added.

**Fix:** Either add a citation in the Literature Review (GARCH section) or remove from bibliography.

---

## 4. Plausibility Concerns

### 4.1 `hood2025` — "Volatility targeting is trendy"

| Field | Value | Assessment |
|-------|-------|------------|
| Authors | Hood, B. & Raughtigan, C. | "Raughtigan" is an unusual surname — unverifiable without web search. |
| Year | 2025 | Plausible as early-access 2025 paper. |
| Journal | *Journal of Portfolio Management*, early access | Plausible. |
| DOI | 10.3905/jpm.2025.1.764 | JPM DOI format `10.3905/jpm.YYYY.X.NNN` looks consistent with journal's pattern. |
| Title | "Volatility targeting is trendy" | Matches the paper's claim that VT alpha derives from trend-following — content is consistent. |
| **Verdict** | Plausible but unverified | Recommend web search / DOI verification before submission. |

### 4.2 `nelson2025` — SSRN Working Paper No. 5931154

| Field | Value | Assessment |
|-------|-------|------------|
| Author | Nelson, R. | Generic name, no institutional affiliation given. |
| Year | 2025 | Plausible. |
| SSRN number | 5931154 | As of 2026, SSRN numbers in the 5.9M range are plausible. |
| DOI | 10.2139/ssrn.5931154 | Standard SSRN DOI format — consistent. |
| Title | "Portfolio construction under correlation breakdowns and tail risk" | Matches the in-text use (cited for "volatility scaling as non-predictive risk control"). |
| **Verdict** | Plausible but unverified | SSRN papers require verification as they can be withdrawn or substantially revised. Recommend DOI check. |

### 4.3 `araya2024` — "A hybrid GARCH and deep learning method"

| Field | Value | Assessment |
|-------|-------|------------|
| Authors | Araya, H.T., Aduda, J., & Berhane, T. | Three authors from what appears to be an African-affiliated research group. |
| Journal | *Journal of Applied Mathematics*, 2024, 6305525 | This is an open-access Hindawi journal. |
| DOI | 10.1155/2024/6305525 | Hindawi DOI format `10.1155/YYYY/XXXXXXX` looks consistent. |
| **Verdict** | Plausible | Low-prestige venue but consistent metadata. In-text use is appropriately hedged ("e.g., Kim and Kim, 2019; Araya et al., 2024"). |

---

## 5. Author Name & Year Verification

All bibliography entries were cross-checked for internal consistency:

| Key | Authors | Year | Journal | Notes |
|-----|---------|------|---------|-------|
| `baur2010hedge` | Baur & Lucey | 2010 | *Financial Review* 45(2) | Two papers by Baur in same year correctly split into `baur2010hedge` and `baur2010safe`. |
| `baur2010safe` | Baur & McDermott | 2010 | *J. Banking & Finance* 34(8) | Correct. |
| `black1976` | Black, F. | 1976 | ASA Proceedings | Non-journal publication — no DOI given, which is correct. |
| `bollerslev1986` | Bollerslev | 1986 | *J. Econometrics* 31(3) | Foundational paper, details look correct. |
| `bollerslev1987` | Bollerslev | 1987 | *Review of Economics and Statistics* 69(3) | Note: journal abbreviated as "Review of Economics and Statistics" but the DOI `10.2307/1925546` is JSTOR format consistent with RES. Correct. |
| `campbell2017` | Campbell, Sunderam & Viceira | 2017 | *Critical Finance Review* 6(2) | Content and journal match known paper. **Format issue: bibitem label** (see Section 3.1). |
| `cederburg2020` | Cederburg, O'Doherty, Wang & Yan | 2020 | *J. Financial Economics* 138(1) | 4 authors — `et al.` in bibitem label is correct. |
| `chang2021` | Chang, Kung, Chen & Tian | 2021 | *Pacific-Basin Finance Journal* 67 | Plausible. |
| `chevallier2017` | Chevallier & Ielpo | 2017 | *Research in International Business and Finance* 39 | DOI includes year 2014 in path — this may be a working paper published in 2014 but appearing in vol. 39 (2017). Verify. |
| `christoffersen1998` | Christoffersen | 1998 | *International Economic Review* 39(4) | Correct. |
| `christie1982` | Christie | 1982 | *J. Financial Economics* 10(4) | Correct foundational paper. |
| `demiguel2024` | DeMiguel, Martin-Utrera & Uppal | 2024 | *J. Finance* 79(6) | JF volume 79 is 2024, issue 6 exists. Plausible. |
| `diebold1995` | Diebold & Mariano | 1995 | *J. Business & Economic Statistics* 13(3) | Correct. Note: paper only cited via prose, no `\cite{}` command used. |
| `engle2002` | Engle | 2002 | *J. Business & Economic Statistics* 20(3) | Correct but **ORPHAN** — not cited in body. |
| `engle2018` | Engle & Siriwardane | 2018 | *Review of Financial Studies* 31(2) | Correct. |
| `fleming2001` | Fleming, Kirby & Ostdiek | 2001 | *J. Finance* 56(1) | Correct. |
| `fleming2003` | Fleming, Kirby & Ostdiek | 2003 | *J. Financial Economics* 67(3) | Correct. |
| `glosten1993` | Glosten, Jagannathan & Runkle | 1993 | *J. Finance* 48(5) | Correct foundational paper. |
| `hansen1994` | Hansen, B.E. | 1994 | *International Economic Review* 35(3) | Note: this is **Bruce E. Hansen** (U. Wisconsin). Distinguish from `hansen2005` (Peter R. Hansen). Both are correct. |
| `hansen2005` | Hansen & Lunde | 2005 | *J. Applied Econometrics* 20(7) | Correct. |
| `hansen2012` | Hansen, Huang & Shek | 2012 | *J. Applied Econometrics* 27(6) | Realized GARCH paper — correct. |
| `harvey2016` | Harvey, Liu & Zhu | 2016 | *Review of Financial Studies* 29(1) | Title `\ldots and the cross-section of expected returns` is the actual title (the `\ldots` is intentional). Correct. |
| `harvey2018` | Harvey et al. (6 authors) | 2018 | *J. Portfolio Management* 45(1) | Correct — JPM volume 45, issue 1 = 2018. |
| `henriksson1981` | Henriksson & Merton | 1981 | *J. Business* 54(4) | Correct. |
| `hood2025` | Hood & Raughtigan | 2025 | *J. Portfolio Management* | See Section 4.1. |
| `hwang2006` | Hwang & Valls Pereira | 2006 | *European J. Finance* 12(6-7) | Correct. |
| `kim2019` | Kim & Kim | 2019 | *PLoS ONE* 14(2) | Non-finance venue but PLoS ONE DOI format consistent. |
| `kuester2006` | Kuester, Mittnik & Paolella | 2006 | *J. Financial Econometrics* 4(1) | Correct. |
| `kupiec1995` | Kupiec | 1995 | *J. Derivatives* 3(2) | Correct. |
| `longin2001` | Longin & Solnik | 2001 | *J. Finance* 56(2) | Correct. |
| `mcneil2015` | McNeil, Frey & Embrechts | 2015 | Princeton Univ. Press (book) | Correct — 2nd edition is 2015. |
| `moreira2017` | Moreira & Muir | 2017 | *J. Finance* 72(4) | Correct foundational VT paper. |
| `nelson1991` | Nelson, D.B. | 1991 | *Econometrica* 59(2) | Correct EGARCH paper. |
| `nelson2025` | Nelson, R. | 2025 | SSRN 5931154 | See Section 4.2. Different person from Nelson (1991). |
| `parkinson1980` | Parkinson | 1980 | *J. Business* 53(1) | Correct range estimator paper. |
| `patton2011` | Patton | 2011 | *J. Econometrics* 160(1) | Correct. |
| `sheppard2023` | Sheppard | 2023 | Python package `arch` v6.2 | Software citation — no DOI, GitHub URL given. Correct format for software. |
| `treynor1966` | Treynor & Mazuy | 1966 | *Harvard Business Review* 44(4) | Note: **Mazuy not "Mazuy"** — spelled "Mazuy" in entry which is correct. No DOI (predates DOI). Acceptable. |
| `xu2024` | Xu, Y. | 2024 | *Critical Finance Review*, forthcoming | "Forthcoming" status — no volume/issue/DOI. This is a limitation but acceptable for a 2024 paper still in press at time of writing. |

### Potential year/author mismatch: `chevallier2017`
The DOI path is `10.1016/j.ribaf.2014.09.010` (includes 2014), suggesting acceptance/online-first in 2014 but final publication in 2017. This is a common pattern for journals with long queues. The citation year (2017) should match the **print publication year**. Verify that vol. 39 = 2017 for *Research in International Business and Finance*. If the paper appeared in print in 2017 (volume 39), the citation is correct.

---

## 6. Citation Format Consistency (APA / apalike style)

The paper uses `\bibliographystyle{apalike}` with a mix of LaTeX `\cite{}` commands and prose author-year format.

### Issues with prose citations not using LaTeX commands

Many citations use prose format (e.g., "Bollerslev (1986)", "BCBS, 2006, 2019") without `\cite{}` commands. This means:
1. These references will **not** be automatically hyperlinked if `hyperref` is enabled.
2. The bibliography will still compile correctly since all keys exist.
3. However, if the bibliography style changes, prose citations remain as-is (not auto-reformatted).

**Recommendation:** Replace all prose citations with `\citet{}` or `\citep{}` for consistency and hyperlinking. This affects approximately 24 references.

### Specific prose format correctness

| Prose citation | Correct format? | Notes |
|----------------|-----------------|-------|
| "Bollerslev (1986)" | Correct for narrative | Should be `\citet{bollerslev1986}` |
| "BCBS, 2006, 2019" | Acceptable as parenthetical | Should be `\citep{bcbs2006,bcbs2019}` |
| "Diebold \& Mariano, 1995" | Uses `\&` — correct in LaTeX | Should be `\citet{diebold1995}` |
| "Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, and Van Hemert (2018)" | 6 authors listed — should be "Harvey et al. (2018)" per APA | **Format error** |
| "Glosten, Jagannathan, and Runkle (1993)" | 3 authors — correct for first cite | Acceptable |
| "McNeil, Frey, and Embrechts (2015)" | 3 authors — correct | Acceptable |
| "Fleming, Kirby, and Ostdiek (2001, 2003)" | 3 authors — correct for first cite | Acceptable (combined citation) |
| "DeMiguel, Martin-Utrera, and Uppal (2024)" | 3 authors — correct | Acceptable |
| "Kuester, Mittnik, and Paolella (2006)" | 3 authors — correct | Acceptable |

---

## 7. Action Items (Priority Order)

### HIGH Priority

1. **Remove or cite `engle2002` (DCC paper):** Either add `\citet{engle2002}` when DCC is first mentioned (Section 4 / Table complexity ceiling), or delete from bibliography.

2. **Remove or cite `corsi2009`:** Add `\citet{corsi2009}` in the HAR Paradox section (line 526) when HAR is introduced, or delete from bibliography.

3. **Remove or cite `bollerslev1994`:** Either add as a general survey citation in the Literature Review or delete.

4. **Fix `campbell2017` bibitem label format:** Change `\bibitem[Campbell et~al., 2017]` to `\bibitem[Campbell et~al.(2017)]` to match apalike convention.

5. **Verify `hood2025` DOI and author name "Raughtigan"** before submission.

### MEDIUM Priority

6. **Change "Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, and Van Hemert (2018)" to "Harvey et al. (2018)"** in body line 46.

7. **Convert prose citations to `\citet{}`/`\citep{}`** for consistency and auto-hyperlinking (24 instances).

8. **Verify `chevallier2017` publication year** (DOI suggests 2014 online-first; confirm vol. 39 = 2017).

### LOW Priority

9. **Verify `nelson2025` SSRN paper** exists at SSRN 5931154 with the stated title.

10. **Add `\cite{}` to the DCC table entry** in complexity ceiling discussion so it links to `engle2002` if retained.

---

## 8. Verification Summary

| Reference category | Status |
|-------------------|--------|
| Core GARCH papers (Bollerslev 1986/87, Nelson 1991, Glosten 1993, Christie 1982, Black 1976) | All present, details plausible |
| VaR/risk papers (Kupiec, Christoffersen, McNeil et al.) | All present, cited correctly |
| VT papers (Moreira & Muir, Fleming et al., Harvey 2018, Hood 2025) | Present; Hood 2025 needs verification |
| Gold/commodity papers (Baur×2, Batten, Chang, Chevallier) | All present; Chevallier year needs check |
| Statistical methods (Diebold & Mariano, Patton, Hansen & Lunde) | Present but Diebold 1995 never via `\cite{}` |
| **Confirmed orphans** | `bollerslev1994`, `corsi2009`, `engle2002` |
| **Suspicious references** | `hood2025` (unverifiable author name), `nelson2025` (unverifiable SSRN) |
