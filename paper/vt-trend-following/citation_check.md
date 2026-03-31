# Citation Verification Report
**Paper:** "Is Volatility Targeting Just Trend Following? Decomposing the Benefits of Volatility Targeting"
**Author:** Yi-Hao Lai (2026)
**Date:** 2026-03-30
**Reviewer:** VolPred Research System (Claude Opus 4.6)

---

## Summary

| Metric | Count |
|--------|-------|
| Bibliography entries | 18 |
| In-text citation keys used | 15 |
| Orphan entries (in bib, never cited) | 3 |
| Missing entries (cited, no bib) | 0 |
| Format issues | 4 |
| Entries needing DOI/URL verification | 3 |

---

## 1. Cross-Reference: In-Text Citations vs. Bibliography

### In-text citation keys (15 unique):
| # | Key | Citation Type | Lines Used | In Bibliography? |
|---|-----|--------------|------------|-----------------|
| 1 | `baltas2013` | `\citep` | 73, 437 | YES |
| 2 | `black1976` | `\citep` | 63 | YES |
| 3 | `bozovic2024` | `\citet`, `\citep` | 93, 455 | YES |
| 4 | `cederburg2020` | `\citet` | 61, 65, 439 | YES |
| 5 | `christie1982` | `\citep` | 63 | YES |
| 6 | `glosten1993` | `\citep` | 143 | YES |
| 7 | `harvey2016` | `\citet` | 43, 442, 467, 481 | YES |
| 8 | `harvey2018` | `\citep` | 61 | YES |
| 9 | `hood2025` | `\citet`, `\citep` | 63, 114, 435, 471 | YES |
| 10 | `lai2026a` | `\citet`, `\citep` | 61, 98, 158, 462, 73 | YES |
| 11 | `miranda2020` | `\citet`, `\citep` | 71, 365, 462 | YES |
| 12 | `moreira2017` | `\citep` | 61 | YES |
| 13 | `moskowitz2012` | `\citet`, `\citep` | 61, 102, 437, 452 | YES |
| 14 | `newey1987` | `\citep` | 124 | YES |
| 15 | `rapach2013` | `\citet` | 365 | YES |

### Bibliography entries NOT cited in text (ORPHANS --- 3):
| # | Key | Entry | Severity | Recommendation |
|---|-----|-------|----------|---------------|
| 1 | `barroso2015` | Barroso, P., & Santa-Clara, P. (2015). Momentum has its moments. *JFE*, 116(1), 111-120. | **HIGH** | **Must cite or remove.** Directly relevant: momentum crash avoidance via vol-scaling. Suggested location: Introduction (para 1, alongside Moreira & Muir 2017) or Section 4.1 (VT vs. trend following). |
| 2 | `daniel2016` | Daniel, K., & Moskowitz, T.J. (2016). Momentum crashes. *JFE*, 122(2), 221-247. | **HIGH** | **Must cite or remove.** Relevant to leverage effect driving momentum crashes. Suggested location: Section 3.2 (leverage effect discussion) or Section 4.1. |
| 3 | `fleming2001` | Fleming, J., Kirby, C., & Ostdiek, B. (2001). The economic value of volatility timing. *JF*, 56(1), 329-352. | **HIGH** | **Must cite or remove.** Foundational VT paper. Suggested location: Introduction (para 1, before Moreira & Muir 2017 as an earlier reference). |

---

## 2. Bibliography Entry Verification

### Entry-by-Entry Check

| # | Key | Authors | Year | Title | Journal/Venue | Volume/Pages | DOI/URL | Issues |
|---|-----|---------|------|-------|---------------|-------------|---------|--------|
| 1 | `baltas2013` | Baltas, A.N. & Kosowski, R. | 2013 | Momentum strategies in futures markets and trend-following funds | Working Paper, Imperial College London | -- | None | **MEDIUM:** Working paper from 2013 --- check if published since. May now be published in a journal. |
| 2 | `barroso2015` | Barroso, P. & Santa-Clara, P. | 2015 | Momentum has its moments | JFE | 116(1), 111-120 | 10.1016/j.jfineco.2014.11.010 | OK (but orphan) |
| 3 | `black1976` | Black, F. | 1976 | Studies of stock price volatility changes | ASA Proceedings | 177-181 | None | OK. Conference proceedings, no DOI expected. |
| 4 | `bozovic2024` | Bozovic, M. | 2024 | VIX-managed portfolios | IRFA | 95, 103353 | 10.1016/j.irfa.2024.103353 | OK |
| 5 | `cederburg2020` | Cederburg, S., O'Doherty, M.S., Wang, F., & Yan, X.S. | 2020 | On the performance of volatility-managed portfolios | JFE | 138(1), 95-117 | 10.1016/j.jfineco.2020.04.015 | OK |
| 6 | `christie1982` | Christie, A.A. | 1982 | The stochastic behavior of common stock variances | JFE | 10(4), 407-432 | 10.1016/0304-405X(82)90018-6 | OK |
| 7 | `daniel2016` | Daniel, K. & Moskowitz, T.J. | 2016 | Momentum crashes | JFE | 122(2), 221-247 | 10.1016/j.jfineco.2015.12.002 | OK (but orphan) |
| 8 | `fleming2001` | Fleming, J., Kirby, C., & Ostdiek, B. | 2001 | The economic value of volatility timing | JF | 56(1), 329-352 | 10.1111/0022-1082.00327 | OK (but orphan) |
| 9 | `glosten1993` | Glosten, L.R., Jagannathan, R., & Runkle, D.E. | 1993 | On the relation between the expected value and the volatility of the nominal excess return on stocks | JF | 48(5), 1779-1801 | 10.1111/j.1540-6261.1993.tb05128.x | OK |
| 10 | `harvey2016` | Harvey, C.R., Liu, Y., & Zhu, H. | 2016 | ...and the cross-section of expected returns | RFS | 29(1), 5-68 | 10.1093/rfs/hhv059 | **LOW:** Title uses `\ldots{}` which renders as "..." --- the actual title starts with "..." which is correct but unconventional in a bib entry. Consider writing the full title. |
| 11 | `harvey2018` | Harvey, C.R., Hoyle, E., Korgaonkar, R., Rattray, S., Sargaison, M., & Van Hemert, O. | 2018 | The impact of volatility targeting | JPM | 45(1), 14-33 | 10.3905/jpm.2018.45.1.014 | OK |
| 12 | `hood2025` | Hood, M. & Raughtigan, J. | 2025 | Volatility targeting alpha is trend following alpha | Working Paper | -- | None | **MEDIUM:** No institution, no SSRN number, no URL. As the paper's primary foil, this needs better identification. Verify author name "Raughtigan" spelling. |
| 13 | `lai2026a` | Lai, Y.-H. | 2026a | Leverage direction matters: Cross-asset evidence on GARCH model selection and volatility targeting | Working Paper, Da-Yeh University | -- | None | **LOW:** The "a" suffix implies a "b" exists. If this paper will be "b", add self-citation; if not, drop the "a". |
| 14 | `moreira2017` | Moreira, A. & Muir, T. | 2017 | Volatility-managed portfolios | JF | 72(4), 1611-1644 | 10.1111/jofi.12513 | OK |
| 15 | `miranda2020` | Miranda-Agrippino, S. & Rey, H. | 2020 | U.S. monetary policy and the global financial cycle | ReStud | 87(6), 2754-2776 | 10.1093/restud/rdaa019 | OK |
| 16 | `moskowitz2012` | Moskowitz, T.J., Ooi, Y.H., & Pedersen, L.H. | 2012 | Time series momentum | JFE | 104(2), 228-250 | 10.1016/j.jfineco.2011.11.003 | OK |
| 17 | `newey1987` | Newey, W.K. & West, K.D. | 1987 | A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix | Econometrica | 55(3), 703-708 | 10.2307/1913610 | OK |
| 18 | `rapach2013` | Rapach, D.E., Strauss, J.K., & Zhou, G. | 2013 | International stock return predictability: What is the role of the United States? | JF | 68(4), 1633-1662 | 10.1111/jofi.12041 | OK |

---

## 3. Missing Literature (Should Consider Adding)

These papers are relevant to the paper's topic but are neither cited nor in the bibliography:

| # | Paper | Relevance | Priority |
|---|-------|-----------|----------|
| 1 | Frazzini & Pedersen (2014). Betting against beta. *JFE*. | BAB factor used in Table 4. Currently proxied by SPLV-SPHB instead of citing the original factor. | HIGH |
| 2 | Hurst, Ooi & Pedersen (2017). A century of evidence on trend following. *AQR Working Paper*. | Longest trend-following backtest. Relevant to Section 4.1. | MEDIUM |
| 3 | Liu et al. (2019). Volatility-managed portfolios revisited. *Working Paper*. | Direct response to Moreira & Muir. Relevant to Introduction. | MEDIUM |
| 4 | Jegadeesh & Titman (1993). Returns to buying winners and selling losers. *JF*. | Cross-sectional momentum distinction (MOM factor discussed in Table 4). | MEDIUM |
| 5 | Rey (2015). Dilemma not trilemma. *Jackson Hole*. | Global financial cycle, relevant to Section 3.5 international. | LOW |
| 6 | Kahneman & Tversky (1979). Prospect theory. *Econometrica*. | Loss aversion utility framework for MDD weighting (Section 4.1 rebuttal of Cederburg). | LOW |
| 7 | Roy (1952). Safety first and the holding of assets. *Econometrica*. | Safety-first criterion relevant to MDD focus. | LOW |

---

## 4. Format Issues

| # | Issue | Location | Severity |
|---|-------|----------|----------|
| 1 | Harvey et al. (2016) title uses `\ldots{}` ellipsis at the start | Line 520 | LOW --- renders correctly but looks unusual in a reference list |
| 2 | Hood & Raughtigan (2025) missing institution/SSRN | Line 525-526 | MEDIUM --- essential for identification of working paper |
| 3 | Baltas & Kosowski (2013) is 13 years old as a working paper | Line 492-493 | MEDIUM --- check if published; if still WP, note it may have been superseded |
| 4 | `\citet` vs `\citep` usage is consistent throughout | Throughout | OK --- no issues found |

---

## 5. Action Items

### Must Fix (before submission)
1. **Cite or remove 3 orphan entries:** `barroso2015`, `daniel2016`, `fleming2001`
2. **Add Hood & Raughtigan (2025) identification:** institution, SSRN number, or URL
3. **Add Frazzini & Pedersen (2014):** if using BAB factor in the analysis

### Should Fix
4. Check if Baltas & Kosowski (2013) has been published since 2013
5. Decide on Lai (2026a) vs Lai (2026) suffix
6. Consider adding Hurst et al. (2017) and Jegadeesh & Titman (1993)

### Nice to Fix
7. Write out Harvey (2016) full title instead of using ellipsis
8. Add DOIs/URLs for all working papers where available
9. Consider adding Rey (2015) and behavioral finance references for the MDD/utility discussion
