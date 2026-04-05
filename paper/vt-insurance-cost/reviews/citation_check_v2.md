# Citation Verification Report -- SECOND ROUND (v2)

**Paper:** The True Cost of Volatility Targeting: Decomposing the Insurance Premium into Opportunity and Transaction Components  
**Authors:** Yi-Hao Lai & VolPred Research System  
**Date of Check:** 2026-04-05  
**Verified by:** Claude Opus 4.6 (citation-verifier)  
**Prior Report:** `citation_check.md` (v1, same date)

---

## First-Round Issue Resolution Status

### MAJOR Issue: Bongaerts et al. (2020) Content Claim

| Item | v1 Text | v2 Text | Fixed? |
|------|---------|---------|--------|
| Bongaerts characterization | "conditioning on **expected returns**" | "conditioning on **volatility states**" | **YES** |

**v1 (WRONG):**
> "While Bongaerts et al. (2020) propose conditional volatility targeting by conditioning on expected returns to optimize Sharpe ratios..."

**v2 (CORRECT):**
> "While Bongaerts et al. (2020) propose conditional volatility targeting by conditioning on volatility states to optimize Sharpe ratios..."

**Verification:** Bongaerts, Kang, and van Dijk (2020) condition on extreme high- and low-volatility states, adjusting risk exposure only during volatility extremes. The revised text ("conditioning on volatility states") accurately describes their approach. **RESOLVED.**

---

### MINOR Issue #1: Huang and Shaliastovich (2015) -- Update to Published Version

| Item | v1 Entry | v2 Entry | Fixed? |
|------|----------|----------|--------|
| Huang reference | Working Paper, 2 authors, 2015 | Working Paper, 2 authors, 2015 | **NO** |

**Current entry (line 257--258):**
> Huang, D., Shaliastovich, I., 2015. Volatility-of-volatility risk. Working Paper, University of Pennsylvania.

**Should be:**
> Huang, D., Schlag, C., Shaliastovich, I., Thimme, J., 2019. Volatility-of-volatility risk. *Journal of Financial and Quantitative Analysis* 54, 2423--2452.

**Status: NOT FIXED.** The paper was published in JFQA (2019, Vol 54, Issue 6, pp. 2423--2452) with 4 authors (Huang, Schlag, Shaliastovich, Thimme). Citing a superseded working paper when the published version exists is a reviewer flag. The bibitem key `huang2015` and all `\citep{huang2015}` calls would also need updating.

---

### MINOR Issue #2: Perchet et al. Pages (21--36 vs 21--38)

| Item | v1 Entry | v2 Entry | Fixed? |
|------|----------|----------|--------|
| Page range | 21--36 | 21--36 | **NO** |

**Current entry (line 267):**
> ...2015. Predicting the success of volatility targeting strategies... *Journal of Alternative Investments* 18, 21--36.

**Correct pages:** The JAI official page (`jai.pm-research.com/content/18/3/21`) and multiple databases list pages as **21--38** (18 pages total for an article starting on page 21). The bibliography says 21--36 (16 pages).

**Status: NOT FIXED.** End page should be 38, not 36.

---

### MINOR Issue #3: Liu et al. (2019) "smooth sailing" Quotation Marks

| Item | v1 Text | v2 Text | Fixed? |
|------|---------|---------|--------|
| "smooth sailing" | Present with quotes in Sec 4 | Present with quotes in Sec 4 | **NO** |

**Current text (line 205):**
> "...consistent with \citet{liu2019}'s finding that VT destroys value in ``smooth sailing'' environments."

**Problem:** "Smooth sailing" does not appear in Liu, Tang, and Zhou (2019). Their finding is that VT "outperforms the market only during the financial crisis period." The LaTeX double-backtick/double-quote formatting (``smooth sailing'') implies a direct quotation from the cited source. Web search of the paper's abstract and available text confirms "smooth sailing" is not their terminology.

**Status: NOT FIXED.** Either remove the quotation marks to signal it is the authors' paraphrase, or replace with the original language: e.g., "...consistent with Liu et al. (2019)'s finding that VT outperforms only during crisis periods and underperforms in calm environments."

---

### MINOR Issue #4: Cederburg et al. (2020) Characterization

| Item | v1 Text | v2 Text | Fixed? |
|------|---------|---------|--------|
| Cederburg claim | "identify transaction costs as a primary concern" | "identify transaction costs as a primary concern" | **NO** |

**Current text (line 56):**
> "\citet{cederburg2020} identify transaction costs as a primary concern when evaluating volatility-managed portfolios."

**Problem:** Cederburg et al. (2020) test 103 equity strategies and find no systematic outperformance from volatility management. Their primary findings concern (1) poor out-of-sample performance, (2) structural instability of spanning regressions, and (3) look-ahead bias in earlier studies. Transaction costs are mentioned but are not the paper's primary concern or contribution.

**Status: NOT FIXED.** Recommended change: "Cederburg et al. (2020) question the out-of-sample viability of volatility-managed portfolios, noting concerns including transaction costs."

---

## Summary of First-Round Fixes

| Issue | Severity | Fixed in v2? |
|-------|----------|-------------|
| Bongaerts "expected returns" -> "volatility states" | **MAJOR** | **YES** |
| Huang 2015 WP -> 2019 JFQA (4 authors) | MINOR | NO |
| Perchet pages 21--36 -> 21--38 | MINOR | NO |
| Liu et al. "smooth sailing" quotes | MINOR | NO |
| Cederburg characterization | MINOR | NO |

**1 of 5 issues resolved. The MAJOR issue is fixed. All 4 MINOR issues remain.**

---

## Full Re-Verification of All 15 References

### 1. Barroso and Santa-Clara (2015) -- `barroso2015`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Barroso, P., Santa-Clara, P. | Pedro Barroso, Pedro Santa-Clara | OK |
| Year | 2015 | 2015 | OK |
| Title | Momentum has its moments | Momentum Has Its Moments | OK |
| Journal | *Journal of Financial Economics* | Journal of Financial Economics | OK |
| Volume | 116 | 116(1) | OK |
| Pages | 111--120 | 111--120 | OK |

**Content claim:** Listed in VT literature survey -- ACCURATE.  
**Status: PASS**

---

### 2. Bollerslev, Tauchen, and Zhou (2009) -- `bollerslev2009`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Bollerslev, T., Tauchen, G., Zhou, H. | Tim Bollerslev, George Tauchen, Hao Zhou | OK |
| Year | 2009 | 2009 | OK |
| Title | Expected stock returns and variance risk premia | Expected Stock Returns and Variance Risk Premia | OK |
| Journal | *Review of Financial Studies* | Review of Financial Studies | OK |
| Volume | 22 | 22(11) | OK |
| Pages | 4463--4492 | 4463--4492 | OK |

**Content claim:** Cited as VoV risk literature -- ACCURATE. The paper studies variance risk premia (difference between implied and realized variance), directly related to volatility-of-volatility risk.  
**Status: PASS**

---

### 3. Bongaerts, Kang, and van Dijk (2020) -- `bongaerts2020`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Bongaerts, D., Kang, X., van Dijk, M. | Dion Bongaerts, Xiaowei Kang, Mathijs A. van Dijk | OK |
| Year | 2020 | 2020 | OK |
| Title | Conditional volatility targeting | Conditional Volatility Targeting | OK |
| Journal | *Financial Analysts Journal* | Financial Analysts Journal | OK |
| Volume | 76 | 76(4) | OK |
| Pages | 54--71 | 54--71 | OK |

**Content claim (v2):** "propose conditional volatility targeting by conditioning on volatility states to optimize Sharpe ratios" -- **ACCURATE.** Bongaerts et al. adjust exposure only during extreme volatility states (high and low). The revised characterization is correct.  
**Status: PASS (MAJOR issue from v1 is now RESOLVED)**

---

### 4. CBOE (2014) -- `cboe2014`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Organization | CBOE | CBOE | OK |
| Year | 2014 | Uncertain (2012 intro, various methodology docs) | UNCERTAIN |
| Title | "CBOE VVIX Index: Measuring the volatility of volatility" | Exact title unverifiable | UNCERTAIN |
| Venue | White Paper, Chicago Board Options Exchange | White Paper | OK |

**Content claim:** "Using the CBOE VVIX index (cboe2014), we compute an expanding-window z-score..." -- ACCEPTABLE. The VVIX index is real and well-documented.  
**Status: PASS (with note: consider adding URL to VVIX methodology page for verifiability)**

---

### 5. Booth and Fama (1992) -- `booth1992`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Booth, D.G., Fama, E.F. | David G. Booth, Eugene F. Fama | OK |
| Year | 1992 | 1992 (May/June) | OK |
| Title | Diversification returns and asset contributions | Diversification Returns and Asset Contributions | OK |
| Journal | *Financial Analysts Journal* | Financial Analysts Journal | OK |
| Volume | 48 | 48(3) | OK |
| Pages | 26--32 | 26--32 | OK |

**Content claim:** "consistent with the theoretical prediction of Booth and Fama (1992)" regarding rebalancing premium -- ACCURATE.  
**Status: PASS**

---

### 6. Cederburg, O'Doherty, Wang, and Yan (2020) -- `cederburg2020`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Cederburg, S., O'Doherty, M.S., Wang, F., Yan, X.S. | Scott Cederburg, Michael S. O'Doherty, Feifei Wang, Xuemin (Sterling) Yan | OK |
| Year | 2020 | 2020 | OK |
| Title | On the performance of volatility-managed portfolios | On the Performance of Volatility-Managed Portfolios | OK |
| Journal | *Journal of Financial Economics* | Journal of Financial Economics | OK |
| Volume | 138 | 138(1) | OK |
| Pages | 95--117 | 95--117 | OK |

**Content claim:** "identify transaction costs as a primary concern when evaluating volatility-managed portfolios" -- **STILL OVERSTATED.** Their primary finding is that volatility-managed portfolios do not systematically outperform unmanaged portfolios across 103 strategies, primarily due to poor OOS performance and structural instability, not primarily due to transaction costs.  
**Status: MINOR (unchanged from v1)**

---

### 7. Fleming, Kirby, and Ostdiek (2001) -- `fleming2001`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Fleming, J., Kirby, C., Ostdiek, B. | Jeff Fleming, Chris Kirby, Barbara Ostdiek | OK |
| Year | 2001 | 2001 | OK |
| Title | The economic value of volatility timing | The Economic Value of Volatility Timing | OK |
| Journal | *Journal of Finance* | The Journal of Finance | OK |
| Volume | 56 | 56(1) | OK |
| Pages | 329--352 | 329--352 | OK |

**Content claim:** Cited for VT's tail-risk compression -- ACCURATE.  
**Status: PASS**

---

### 8. Harvey, Liu, and Zhu (2016) -- `harvey2016`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Harvey, C.R., Liu, Y., Zhu, H. | Campbell R. Harvey, Yan Liu, Heqing Zhu | OK |
| Year | 2016 | 2016 | OK |
| Title | \ldots and the cross-section of expected returns | ... and the Cross-Section of Expected Returns | OK |
| Journal | *Review of Financial Studies* | Review of Financial Studies | OK |
| Volume | 29 | 29(1) | OK |
| Pages | 5--68 | 5--68 | OK |

**Content claim:** "|t| > 3.0" threshold for multiple testing -- ACCURATE.  
**Status: PASS**

---

### 9. Harvey et al. (2018) -- `harvey2018`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Harvey, C.R., Hoyle, E., Korgaonkar, R., Rattray, S., Sargaison, M., Van Hemert, O. | All 6 authors confirmed | OK |
| Year | 2018 | 2018 (October) | OK |
| Title | The impact of volatility targeting | The Impact of Volatility Targeting | OK |
| Journal | *Journal of Portfolio Management* | Journal of Portfolio Management | OK |
| Volume | 45 | 45(1) | OK |
| Pages | 14--33 | 14--33 | OK |

**Content claim:** "demonstrate that such strategies meaningfully reduce tail risk" and "prominently report turnover metrics" -- ACCURATE.  
**Status: PASS**

---

### 10. Hasbrouck (2009) -- `hasbrouck2009`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Hasbrouck, J. | Joel Hasbrouck | OK |
| Year | 2009 | 2009 | OK |
| Title | Trading costs and returns for U.S. equities: Estimating effective costs from daily data | Trading Costs and Returns for U.S. Equities: Estimating Effective Costs from Daily Data | OK |
| Journal | *Journal of Finance* | The Journal of Finance | OK |
| Volume | 64 | 64(3) | OK |
| Pages | 1445--1477 | 1445--1477 | OK |

**Content claim:** SPY's bid-ask spread of 1--2 bps -- ACCURATE (consistent with Hasbrouck's methodology for large-cap ETFs).  
**Status: PASS**

---

### 11. Hocquard, Ng, and Papageorgiou (2013) -- `hocquard2013`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Hocquard, A., Ng, S., Papageorgiou, N. | Alexandre Hocquard, Sunny Ng, Nicolas Papageorgiou | OK |
| Year | 2013 | 2013 (January) | OK |
| Title | A constant-volatility framework for managing tail risk | A Constant-Volatility Framework for Managing Tail Risk | OK |
| Journal | *Journal of Portfolio Management* | Journal of Portfolio Management | OK |
| Volume | 39 | 39(2) | OK |
| Pages | 28--40 | 28--40 | OK |

**Content claim:** Cited for VT's tail-risk compression -- ACCURATE.  
**Status: PASS**

---

### 12. Huang and Shaliastovich (2015) -- `huang2015`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Huang, D., Shaliastovich, I. | Darien Huang, Christian Schlag, Ivan Shaliastovich, Julian Thimme (4 authors) | **MISMATCH** |
| Year | 2015 | 2019 (published JFQA) | **MISMATCH** |
| Title | Volatility-of-volatility risk | Volatility-of-Volatility Risk | OK |
| Venue | Working Paper, University of Pennsylvania | JFQA 54(6), 2423--2452 | **MISMATCH** |

**Content claim:** Cited for VoV risk literature -- ACCURATE.  
**Status: MINOR (should cite published 2019 JFQA version with all 4 authors)**

---

### 13. Liu, Tang, and Zhou (2019) -- `liu2019`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Liu, F., Tang, X., Zhou, G. | Fang Liu, Xiaoxiao Tang, Guofu Zhou | OK |
| Year | 2019 | 2019 | OK |
| Title | Volatility-managed portfolio: Does it really work? | Volatility-Managed Portfolio: Does It Really Work? | OK |
| Journal | *Journal of Portfolio Management* | Journal of Portfolio Management | OK |
| Volume | 46 | 46(1) | OK |
| Pages | 38--51 | 38--51 | OK |

**Content claim:** "VT destroys value in ``smooth sailing'' environments" -- **SUBSTANTIVELY CORRECT but misleading quotation.** Liu et al. find VT "outperforms the market only during the financial crisis period," which implies underperformance in calm periods. The phrase "smooth sailing" is not from their paper. The LaTeX quotation marks (``...'') imply direct quotation.  
**Status: MINOR (quotation marks misleading; unchanged from v1)**

---

### 14. Moreira and Muir (2017) -- `moreira2017`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Moreira, A., Muir, T. | Alan Moreira, Tyler Muir | OK |
| Year | 2017 | 2017 | OK |
| Title | Volatility-managed portfolios | Volatility-Managed Portfolios | OK |
| Journal | *Journal of Finance* | The Journal of Finance | OK |
| Volume | 72 | 72(4) | OK |
| Pages | 1611--1644 | 1611--1644 | OK |

**Content claim:** "formalized by Moreira and Muir (2017), prescribes scaling equity exposure inversely to conditional volatility" -- ACCURATE.  
**Status: PASS**

---

### 15. Perchet, de Carvalho, Heckel, and Moulin (2015) -- `perchet2016`

| Field | Bibliography | Verified | Match? |
|-------|-------------|----------|--------|
| Authors | Perchet, R., de Carvalho, R.L., Heckel, T., Moulin, P. | Romain Perchet, Raul Leote de Carvalho, Thomas Heckel, Pierre Moulin | OK |
| Year | 2015 (in entry text) | Winter 2015/2016 (Vol 18 No 3) | OK |
| Title | Predicting the success of volatility targeting strategies... | Predicting the Success of Volatility Targeting Strategies: Application to Equities and Other Asset Classes | OK |
| Journal | *Journal of Alternative Investments* | Journal of Alternative Investments | OK |
| Volume | 18 | 18(3) | OK |
| Pages | 21--36 | **21--38** | **MISMATCH** |

**Note on bibkey:** The key `perchet2016` vs displayed year 2015 is cosmetically inconsistent but functionally harmless because the `\bibitem` label `[Perchet et al.(2015)]` controls what appears in text.

**Content claim:** "We use the 12/VIX rule (perchet2016)" -- ACCURATE.  
**Status: MINOR (pages should be 21--38, not 21--36; unchanged from v1)**

---

## New Issues Introduced in v2

**No new citation issues were introduced in the revision.** The only substantive text change (Bongaerts "expected returns" -> "volatility states") was correctly executed without introducing new errors.

---

## Orphan Reference Check (v2)

All 15 bibliography entries are cited at least once in the text:

| bibkey | Cited? | Location(s) |
|--------|--------|-------------|
| `barroso2015` | Yes | Sec 1 |
| `bollerslev2009` | Yes | Sec 4 |
| `bongaerts2020` | Yes | Sec 1 (x2) |
| `cboe2014` | Yes | Sec 2.2 |
| `booth1992` | Yes | Sec 3.3 |
| `cederburg2020` | Yes | Sec 1 (x2) |
| `fleming2001` | Yes | Sec 1 |
| `harvey2016` | Yes | Sec 3.5 |
| `hasbrouck2009` | Yes | Sec 2.3 |
| `harvey2018` | Yes | Sec 1 (x2) |
| `hocquard2013` | Yes | Sec 1 |
| `huang2015` | Yes | Sec 4 |
| `liu2019` | Yes | Sec 1, Sec 4 |
| `moreira2017` | Yes | Sec 1 (x2) |
| `perchet2016` | Yes | Sec 2.1 |

**No orphan references. No missing references.**

---

## Overall v2 Assessment

| Category | Count | Status |
|----------|-------|--------|
| Total bibliography entries | 15 | -- |
| PASS (fully correct) | 11 | OK |
| MINOR issues remaining | 4 | Needs fix |
| MAJOR issues remaining | 0 | All resolved |
| New issues introduced | 0 | OK |

**The critical MAJOR error (Bongaerts characterization) has been correctly fixed.** The 4 MINOR issues from v1 remain unaddressed. None are fatal for submission, but all are the type of detail that careful reviewers or editors may flag.

---

## Remaining Correction Checklist (Priority Order)

### SHOULD FIX (before submission)

- [ ] **Huang et al.:** Update from 2015 working paper to 2019 JFQA published version (4 authors: Huang, Schlag, Shaliastovich, Thimme). Update bibkey `huang2015` -> `huang2019` and all `\citep{huang2015}` calls in text.
  - New entry: `Huang, D., Schlag, C., Shaliastovich, I., Thimme, J., 2019. Volatility-of-volatility risk. \textit{Journal of Financial and Quantitative Analysis} 54, 2423--2452.`

- [ ] **Perchet et al. pages:** Change `21--36` to `21--38` (confirmed via JAI official page and multiple databases).

- [ ] **Liu et al. "smooth sailing":** Remove LaTeX quotation marks (``...'') or rephrase. Current formatting implies direct quotation from Liu et al., but the phrase is not theirs. Suggested fix: change `in ``smooth sailing'' environments` to `in calm market environments`.

- [ ] **Cederburg et al. characterization:** Soften "identify transaction costs as a primary concern" to "question the out-of-sample viability of volatility-managed portfolios, noting concerns including transaction costs." Their primary contribution is about OOS failure and structural instability across 103 strategies, not specifically about transaction costs.

### OPTIONAL IMPROVEMENTS (unchanged from v1)

- [ ] **CBOE (2014):** Add URL `\url{https://www.cboe.com/us/indices/dashboard/vvix/}` for verifiability.
- [ ] **DOIs:** Consider adding DOIs to all entries.

---

## Specific LaTeX Fixes

```latex
% 1. Huang: replace lines 257-258
\bibitem[Huang et al.(2019)]{huang2019}
Huang, D., Schlag, C., Shaliastovich, I., Thimme, J., 2019. Volatility-of-volatility risk. \textit{Journal of Financial and Quantitative Analysis} 54, 2423--2452.

% 2. Perchet pages: line 267, change 21--36 to 21--38
% Before: ...18, 21--36.
% After:  ...18, 21--38.

% 3. Liu "smooth sailing": line 205
% Before: ...VT destroys value in ``smooth sailing'' environments.
% After:  ...VT destroys value in calm market environments.

% 4. Cederburg: line 56
% Before: \citet{cederburg2020} identify transaction costs as a primary concern when evaluating volatility-managed portfolios.
% After:  \citet{cederburg2020} question the out-of-sample viability of volatility-managed portfolios, noting concerns including transaction costs.

% 5. Update all \citep{huang2015} to \citep{huang2019} (appears once, line 205)
```

---

*End of second-round citation verification report.*
