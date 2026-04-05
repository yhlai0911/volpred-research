# Citation Verification Report

**Paper:** The True Cost of Volatility Targeting: Decomposing the Insurance Premium into Opportunity and Transaction Components  
**Authors:** Yi-Hao Lai & VolPred Research System  
**Date of Check:** 2026-04-05  
**Verified by:** Claude Opus 4.6 (citation-verifier)

---

## Summary

| Category | Count | Status |
|----------|-------|--------|
| Total bibliography entries | 15 | -- |
| Citations in text | 14 unique keys | -- |
| PASS (correct) | 9 | OK |
| MINOR issues (formatting/year) | 4 | Needs fix |
| MAJOR issues (content accuracy) | 1 | Needs fix |
| Orphan references | 0 | OK |
| Missing references | 0 | OK |

**Overall assessment:** 4 minor issues + 1 major content accuracy issue. No orphan or missing references. The bibliography is well-constructed but requires corrections before submission.

---

## Citation-by-Citation Verification

### 1. Barroso and Santa-Clara (2015) -- `barroso2015`

**In bibliography:**
> Barroso, P., Santa-Clara, P., 2015. Momentum has its moments. *Journal of Financial Economics* 116, 111--120.

**Verified details:**
- Authors: Pedro Barroso, Pedro Santa-Clara -- **CORRECT**
- Year: 2015 -- **CORRECT**
- Title: "Momentum has its moments" -- **CORRECT**
- Journal: *Journal of Financial Economics* -- **CORRECT**
- Volume: 116, Issue 1 -- **CORRECT** (issue not listed, acceptable)
- Pages: 111--120 -- **CORRECT**
- DOI: 10.1016/j.jfineco.2014.11.010

**Content claim in paper:** Cited as part of the VT literature: "Despite a substantial literature on VT mechanics (moreira2017, barroso2015, cederburg2020, bongaerts2020, liu2019)..."  
**Accuracy:** **CORRECT.** Barroso & Santa-Clara (2015) apply volatility scaling to momentum strategies, directly relevant to VT mechanics.

**Status: PASS**

---

### 2. Bollerslev, Tauchen, and Zhou (2009) -- `bollerslev2009`

**In bibliography:**
> Bollerslev, T., Tauchen, G., Zhou, H., 2009. Expected stock returns and variance risk premia. *Review of Financial Studies* 22, 4463--4492.

**Verified details:**
- Authors: Tim Bollerslev, George Tauchen, Hao Zhou -- **CORRECT**
- Year: 2009 -- **CORRECT**
- Title: "Expected Stock Returns and Variance Risk Premia" -- **CORRECT**
- Journal: *Review of Financial Studies* -- **CORRECT**
- Volume: 22, Issue 11 -- **CORRECT** (issue not listed, acceptable)
- Pages: 4463--4492 -- **CORRECT**
- DOI: available from Oxford Academic

**Content claim in paper:** Cited as part of the "volatility-of-volatility risk" literature: "This connects to the broader 'volatility-of-volatility risk' literature (bollerslev2009, huang2015)..."  
**Accuracy:** **CORRECT.** Bollerslev et al. (2009) study variance risk premia -- the difference between implied and realized variance -- which is directly related to VoV risk. The paper shows variance risk premia predict stock returns.

**Status: PASS**

---

### 3. Bongaerts, Kang, and van Dijk (2020) -- `bongaerts2020`

**In bibliography:**
> Bongaerts, D., Kang, X., van Dijk, M., 2020. Conditional volatility targeting. *Financial Analysts Journal* 76, 54--71.

**Verified details:**
- Authors: Dion Bongaerts, Xiaowei Kang, Mathijs A. van Dijk -- **CORRECT**
- Year: 2020 -- **CORRECT**
- Title: "Conditional Volatility Targeting" -- **CORRECT**
- Journal: *Financial Analysts Journal* -- **CORRECT**
- Volume: 76, Issue 4 -- **CORRECT** (issue not listed, acceptable)
- Pages: 54--71 -- **CORRECT**
- DOI: 10.1080/0015198X.2020.1790853

**Content claim in paper:** "While Bongaerts et al. (2020) propose conditional volatility targeting by **conditioning on expected returns** to optimize Sharpe ratios, our approach conditions on volatility-of-volatility..."  
**Accuracy:** **MAJOR ERROR.** Bongaerts et al. (2020) do NOT condition on expected returns. They condition on **volatility states** -- adjusting risk exposure only during periods of extreme high and low volatility. Their conditioning variable is realized volatility itself, not expected returns. The paper's characterization of Bongaerts et al. is inaccurate and must be corrected.

**Recommended fix:** Change to something like: "While Bongaerts et al. (2020) propose conditional volatility targeting by adjusting exposure only in extreme volatility states to optimize Sharpe ratios, our approach conditions on volatility-of-volatility..."

**Status: FAIL -- MAJOR (content accuracy error)**

---

### 4. Booth and Fama (1992) -- `booth1992`

**In bibliography:**
> Booth, D.G., Fama, E.F., 1992. Diversification returns and asset contributions. *Financial Analysts Journal* 48, 26--32.

**Verified details:**
- Authors: David G. Booth, Eugene F. Fama -- **CORRECT**
- Year: 1992 -- **CORRECT**
- Title: "Diversification Returns and Asset Contributions" -- **CORRECT**
- Journal: *Financial Analysts Journal* -- **CORRECT**
- Volume: 48, Issue 3 (May/June) -- **CORRECT** (issue not listed, acceptable)
- Pages: 26--32 -- **CORRECT**
- DOI: 10.2469/faj.v48.n3.26

**Content claim in paper:** "...consistent with the theoretical prediction of Booth and Fama (1992) and confirmed by our weight-sweep analysis..."  
**Accuracy:** **CORRECT.** Booth & Fama (1992) establish the theoretical basis for diversification returns (rebalancing premium). The paper's claim that the 54 bps rebalancing premium is "consistent with the theoretical prediction" is appropriate.

**Status: PASS**

---

### 5. CBOE (2014) -- `cboe2014`

**In bibliography:**
> CBOE, 2014. CBOE VVIX Index: Measuring the volatility of volatility. White Paper, Chicago Board Options Exchange.

**Verified details:**
- Organization: CBOE -- **CORRECT**
- Year: 2014 -- **UNCERTAIN.** The VVIX index was introduced in March 2012 via a press release. CBOE publishes methodology documents for the VIX family, but the specific "CBOE VVIX Index: Measuring the volatility of volatility" white paper dated 2014 could not be independently confirmed via web search. CBOE white papers have been updated multiple times (2012, 2014, 2019). A 2012 document "Double the Fun with CBOE's VVIX Index" exists on cdn.cboe.com.
- Title: "CBOE VVIX Index: Measuring the volatility of volatility" -- **UNCERTAIN.** The exact title may differ; a related document is titled "Double the Fun with CBOE's VVIX Index."

**Content claim in paper:** "Using the CBOE VVIX index (cboe2014), we compute an expanding-window z-score..."  
**Accuracy:** **ACCEPTABLE.** The VVIX index is real and well-documented. The citation to a CBOE white paper is standard practice.

**Recommended fix:** Verify the exact title and year of the CBOE white paper. Consider citing the 2012 introduction or the current methodology document. At minimum, add a URL: `\url{https://www.cboe.com/us/indices/dashboard/vvix/}`.

**Status: MINOR (year and title unverifiable; recommend adding URL)**

---

### 6. Cederburg, O'Doherty, Wang, and Yan (2020) -- `cederburg2020`

**In bibliography:**
> Cederburg, S., O'Doherty, M.S., Wang, F., Yan, X.S., 2020. On the performance of volatility-managed portfolios. *Journal of Financial Economics* 138, 95--117.

**Verified details:**
- Authors: Scott Cederburg, Michael S. O'Doherty, Feifei Wang, Xuemin (Sterling) Yan -- **CORRECT**
- Year: 2020 -- **CORRECT**
- Title: "On the performance of volatility-managed portfolios" -- **CORRECT**
- Journal: *Journal of Financial Economics* -- **CORRECT**
- Volume: 138, Issue 1 -- **CORRECT** (issue not listed, acceptable)
- Pages: 95--117 -- **CORRECT**
- DOI: 10.1016/j.jfineco.2020.04.015

**Content claim in paper:** "Cederburg et al. (2020) identify transaction costs as a primary concern when evaluating volatility-managed portfolios."  
**Accuracy:** **PARTIALLY ACCURATE but overstated.** Cederburg et al. (2020) find that volatility-managed portfolios do not systematically outperform unmanaged portfolios, primarily due to structural instability in spanning regressions and poor out-of-sample performance -- not primarily due to transaction costs. While they discuss transaction costs as one factor, it is not the paper's primary finding. The attribution is somewhat misleading.

**Recommended fix:** Soften the claim, e.g., "Cederburg et al. (2020) raise concerns about the out-of-sample performance of volatility-managed portfolios, including the role of transaction costs."

**Status: MINOR (content slightly overstated; not the paper's primary finding)**

---

### 7. Fleming, Kirby, and Ostdiek (2001) -- `fleming2001`

**In bibliography:**
> Fleming, J., Kirby, C., Ostdiek, B., 2001. The economic value of volatility timing. *Journal of Finance* 56, 329--352.

**Verified details:**
- Authors: Jeff Fleming, Chris Kirby, Barbara Ostdiek -- **CORRECT**
- Year: 2001 -- **CORRECT**
- Title: "The Economic Value of Volatility Timing" -- **CORRECT**
- Journal: *Journal of Finance* -- **CORRECT**
- Volume: 56, Issue 1 -- **CORRECT** (issue not listed, acceptable)
- Pages: 329--352 -- **CORRECT**

**Content claim in paper:** Cited as confirming "VT's ability to compress the return distribution, particularly in the left tail."  
**Accuracy:** **CORRECT.** Fleming et al. (2001) demonstrate the economic value of volatility timing for mean-variance investors.

**Status: PASS**

---

### 8. Harvey, Liu, and Zhu (2016) -- `harvey2016`

**In bibliography:**
> Harvey, C.R., Liu, Y., Zhu, H., 2016. \ldots and the cross-section of expected returns. *Review of Financial Studies* 29, 5--68.

**Verified details:**
- Authors: Campbell R. Harvey, Yan Liu, Heqing Zhu -- **CORRECT** (note: some sources list "Caroline Zhu" but "Heqing Zhu" is also used; "H." initial is correct)
- Year: 2016 -- **CORRECT**
- Title: "... and the Cross-Section of Expected Returns" -- **CORRECT** (the ellipsis is part of the actual title)
- Journal: *Review of Financial Studies* -- **CORRECT**
- Volume: 29, Issue 1 -- **CORRECT** (issue not listed, acceptable)
- Pages: 5--68 -- **CORRECT**

**Content claim in paper:** "Diebold-Mariano tests confirm that no strategy difference achieves the Harvey (2016) threshold of |t| > 3.0"  
**Accuracy:** **CORRECT.** Harvey et al. (2016) propose that newly discovered factors need t-ratios exceeding 3.0 to be considered significant, given the multiple testing problem in finance.

**Status: PASS**

---

### 9. Harvey et al. (2018) -- `harvey2018`

**In bibliography:**
> Harvey, C.R., Hoyle, E., Korgaonkar, R., Rattray, S., Sargaison, M., Van Hemert, O., 2018. The impact of volatility targeting. *Journal of Portfolio Management* 45, 14--33.

**Verified details:**
- Authors: Campbell R. Harvey, Edward Hoyle, Russell Korgaonkar, Sandy Rattray, Matthew Sargaison, Otto Van Hemert -- **CORRECT**
- Year: 2018 -- **CORRECT** (published October 2018)
- Title: "The Impact of Volatility Targeting" -- **CORRECT**
- Journal: *Journal of Portfolio Management* -- **CORRECT**
- Volume: 45, Issue 1 -- **CORRECT** (issue not listed, acceptable)
- Pages: 14--33 -- **CORRECT**
- DOI: 10.3905/jpm.2018.45.1.014

**Content claim in paper:** "Harvey et al. (2018) demonstrate that such strategies meaningfully reduce tail risk" and "Harvey et al. (2018) prominently report turnover metrics as a key performance drag."  
**Accuracy:** **CORRECT.** Harvey et al. (2018) show VT reduces tail risk across asset classes. The paper does discuss turnover implications, though the phrasing "prominently report turnover metrics as a key performance drag" is a reasonable characterization.

**Status: PASS**

---

### 10. Hasbrouck (2009) -- `hasbrouck2009`

**In bibliography:**
> Hasbrouck, J., 2009. Trading costs and returns for U.S. equities: Estimating effective costs from daily data. *Journal of Finance* 64, 1445--1477.

**Verified details:**
- Authors: Joel Hasbrouck -- **CORRECT**
- Year: 2009 -- **CORRECT**
- Title: "Trading Costs and Returns for U.S. Equities: Estimating Effective Costs from Daily Data" -- **CORRECT**
- Journal: *Journal of Finance* -- **CORRECT**
- Volume: 64, Issue 3 -- **CORRECT** (issue not listed, acceptable)
- Pages: 1445--1477 -- **CORRECT**
- DOI: 10.1111/j.1540-6261.2009.01469.x

**Content claim in paper:** "...which exceeds SPY's typical bid-ask spread of 1--2 bps (hasbrouck2009)..."  
**Accuracy:** **CORRECT.** Hasbrouck (2009) estimates effective trading costs from daily data. SPY's effective spread being 1-2 bps is consistent with the literature and with Hasbrouck's methodology.

**Status: PASS**

---

### 11. Hocquard, Ng, and Papageorgiou (2013) -- `hocquard2013`

**In bibliography:**
> Hocquard, A., Ng, S., Papageorgiou, N., 2013. A constant-volatility framework for managing tail risk. *Journal of Portfolio Management* 39, 28--40.

**Verified details:**
- Authors: Alexandre Hocquard, Sunny Ng, Nicolas Papageorgiou -- **CORRECT**
- Year: 2013 -- **CORRECT**
- Title: "A Constant-Volatility Framework for Managing Tail Risk" -- **CORRECT**
- Journal: *Journal of Portfolio Management* -- **CORRECT**
- Volume: 39, Issue 2 -- **CORRECT** (issue not listed, acceptable)
- Pages: 28--40 -- **CORRECT**
- DOI: 10.3905/jpm.2013.39.2.028

**Content claim in paper:** Cited as confirming "VT's ability to compress the return distribution, particularly in the left tail."  
**Accuracy:** **CORRECT.** Hocquard et al. (2013) propose a constant-volatility framework that reduces tail risk exposure.

**Status: PASS**

---

### 12. Huang and Shaliastovich (2015) -- `huang2015`

**In bibliography:**
> Huang, D., Shaliastovich, I., 2015. Volatility-of-volatility risk. Working Paper, University of Pennsylvania.

**Verified details:**
- Authors: Listed as Huang, D. and Shaliastovich, I. (2 authors) -- **PARTIALLY CORRECT.** The original working paper circa 2014 was by Huang (Darien) and Shaliastovich (Ivan). However, the paper was later expanded to include Christian Schlag and Julian Thimme as co-authors, and was published in the *Journal of Financial and Quantitative Analysis* 54(6), 2423-2452, in 2019.
- Year: 2015 -- **UNCERTAIN.** The SSRN version (abstract 2497759) shows a 2014 posting date, later revised in 2018. A 2015 working paper date is plausible for a circulating draft but cannot be independently confirmed to a specific dated version.
- Title: "Volatility-of-Volatility Risk" -- **CORRECT**
- Venue: Working Paper, University of Pennsylvania -- **PARTIALLY CORRECT.** Shaliastovich was at UPenn (Wharton). Huang (Darien) had Cornell affiliation in some versions.

**Content claim in paper:** Cited as part of the VoV risk literature: "This connects to the broader 'volatility-of-volatility risk' literature (bollerslev2009, huang2015)."  
**Accuracy:** **CORRECT.** The paper studies VoV risk and its role in asset pricing.

**Recommended fix:** Since the paper has been published, update to the published version:
> Huang, D., Schlag, C., Shaliastovich, I., Thimme, J., 2019. Volatility-of-volatility risk. *Journal of Financial and Quantitative Analysis* 54, 2423--2452.

If retaining the working paper citation, at minimum correct the author count and year.

**Status: MINOR (should cite the published 2019 JFQA version with 4 authors)**

---

### 13. Liu, Tang, and Zhou (2019) -- `liu2019`

**In bibliography:**
> Liu, F., Tang, X., Zhou, G., 2019. Volatility-managed portfolio: Does it really work? *Journal of Portfolio Management* 46, 38--51.

**Verified details:**
- Authors: Fang Liu, Xiaoxiao Tang, Guofu Zhou -- **CORRECT**
- Year: 2019 -- **CORRECT** (published online September 2019)
- Title: "Volatility-Managed Portfolio: Does It Really Work?" -- **CORRECT**
- Journal: *Journal of Portfolio Management* -- **CORRECT**
- Volume: 46, Issue 1 -- **CORRECT** (issue not listed, acceptable)
- Pages: 38--51 -- **CORRECT**

**Content claim in paper:** "consistent with Liu et al. (2019)'s finding that VT destroys value in 'smooth sailing' environments."  
**Accuracy:** **PARTIALLY ACCURATE.** Liu et al. (2019) find that VT "outperforms the market only during the financial crisis period" -- which implies underperformance in non-crisis (calm) periods. The phrase "smooth sailing" does not appear to be a direct quote from Liu et al. The characterization is substantively correct but the quotation marks around "smooth sailing" are misleading if this is not their terminology.

**Recommended fix:** Remove quotation marks from "smooth sailing" or rephrase: "...consistent with Liu et al. (2019)'s finding that VT outperforms only during crisis periods and underperforms in calm environments."

**Status: MINOR (misleading quotation marks around a phrase not from the cited paper)**

---

### 14. Moreira and Muir (2017) -- `moreira2017`

**In bibliography:**
> Moreira, A., Muir, T., 2017. Volatility-managed portfolios. *Journal of Finance* 72, 1611--1644.

**Verified details:**
- Authors: Alan Moreira, Tyler Muir -- **CORRECT**
- Year: 2017 -- **CORRECT**
- Title: "Volatility-Managed Portfolios" -- **CORRECT**
- Journal: *Journal of Finance* -- **CORRECT**
- Volume: 72, Issue 4 -- **CORRECT** (issue not listed, acceptable)
- Pages: 1611--1644 -- **CORRECT**
- DOI: 10.1111/jofi.12513

**Content claim in paper:** "The framework, formalized by Moreira and Muir (2017), prescribes scaling equity exposure inversely to conditional volatility---increasing allocation when markets are calm and reducing it when turbulence rises."  
**Accuracy:** **CORRECT.** This accurately describes the core mechanism of Moreira & Muir (2017).

**Status: PASS**

---

### 15. Perchet, de Carvalho, Heckel, and Moulin (2015) -- `perchet2016`

**In bibliography:**
> Perchet, R., de Carvalho, R.L., Heckel, T., Moulin, P., 2015. Predicting the success of volatility targeting strategies: Application to equities and other asset classes. *Journal of Alternative Investments* 18, 21--36.

**Verified details:**
- Authors: Romain Perchet, Raul Leote de Carvalho, Thomas Heckel, Pierre Moulin -- **CORRECT**
- Year: Listed as 2015 in bibliography text -- **AMBIGUOUS.** The journal issue is Vol 18, No 3 (Winter 2016). The DOI (10.3905/jai.2016.18.3.021) contains "2016." Many databases list this as a 2015 publication (December 2015 print date), while the DOI suggests 2016. Both are defensible.
- Title: "Predicting the Success of Volatility Targeting Strategies: Application to Equities and Other Asset Classes" -- **CORRECT**
- Journal: *Journal of Alternative Investments* -- **CORRECT**
- Volume: 18, Issue 3 -- **CORRECT** (issue not listed, acceptable)
- Pages: 21--36 -- **NEEDS CHECK.** Some sources list pages 21--38. The bibliography says 21--36.

**Note on bibitem key:** The key is `perchet2016` but the year in the entry is 2015. This causes a **key-year mismatch**. In `natbib`, the key label `perchet2016` would render as "Perchet et al. (2016)" in the text, but the bibliography entry says 2015. However, the `\bibitem` label is `[Perchet et al.(2015)]` which should override to show 2015 in text. This is internally consistent but the key name is confusing for maintenance.

**Content claim in paper:** "We use the 12/VIX rule (perchet2016): w_t = min(12/VIX_{t-1}, 1)."  
**Accuracy:** **CORRECT.** Perchet et al. discuss volatility targeting strategies including the use of VIX-based allocation rules.

**Recommended fix:** (1) Verify end page: is it 36 or 38? Multiple databases show pages 21-38 for an 18-page article. (2) Decide on year: 2015 or 2016; ensure consistency between bibitem key and displayed year.

**Status: MINOR (pages possibly wrong: 21--36 vs. 21--38; year ambiguity)**

---

## Orphan Reference Check

All 15 bibliography entries are cited in the text:

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

**No orphan references found.**

---

## Missing Reference Check

All citation keys used in text have corresponding bibliography entries:

| Citation key in text | In bibliography? |
|---------------------|-----------------|
| `moreira2017` | Yes |
| `harvey2018` | Yes |
| `fleming2001` | Yes |
| `hocquard2013` | Yes |
| `cederburg2020` | Yes |
| `barroso2015` | Yes |
| `bongaerts2020` | Yes |
| `liu2019` | Yes |
| `perchet2016` | Yes |
| `cboe2014` | Yes |
| `hasbrouck2009` | Yes |
| `booth1992` | Yes |
| `harvey2016` | Yes |
| `bollerslev2009` | Yes |
| `huang2015` | Yes |

**No missing references found.**

---

## APA 7th Format Assessment

The bibliography uses `apalike` style (natbib), which is a common variant in finance/economics journals. It does not strictly follow APA 7th edition but follows the author-year convention used by most finance journals (JFE, JoF, RFS style). This is appropriate for the target venue.

**Minor format notes:**
- All entries use surname-first format with initials: **CORRECT**
- Journal names are italicized: **CORRECT**
- Year follows authors: **CORRECT**
- Volume numbers included without issue numbers: **ACCEPTABLE** for this style
- Page ranges use en-dashes: **CORRECT** (LaTeX `--`)
- DOIs are not included: **ACCEPTABLE** for the apalike style, though adding DOIs would strengthen verifiability

---

## Required Actions (Priority Order)

### MUST FIX (before submission)

1. **[MAJOR] Bongaerts et al. (2020) content claim -- Section 1, paragraph 3:**
   - **Current:** "While Bongaerts et al. (2020) propose conditional volatility targeting by conditioning on expected returns to optimize Sharpe ratios..."
   - **Problem:** Bongaerts et al. condition on **volatility states** (extreme high/low volatility), NOT on expected returns.
   - **Fix:** "While Bongaerts et al. (2020) propose conditional volatility targeting by adjusting exposure only in extreme volatility states to optimize Sharpe ratios..."

### SHOULD FIX (recommended)

2. **[MINOR] Huang and Shaliastovich (2015) -- update to published version:**
   - **Current:** "Huang, D., Shaliastovich, I., 2015. Volatility-of-volatility risk. Working Paper, University of Pennsylvania."
   - **Problem:** Paper was published in 2019 in JFQA with 4 authors.
   - **Fix:** "Huang, D., Schlag, C., Shaliastovich, I., Thimme, J., 2019. Volatility-of-volatility risk. *Journal of Financial and Quantitative Analysis* 54, 2423--2452."
   - **Note:** Also update bibitem key from `huang2015` to `huang2019` and update all `\citep{huang2015}` references.

3. **[MINOR] Perchet et al. pages -- verify 21--36 vs 21--38:**
   - Multiple databases (JAI official, ResearchGate, ProQuest) list pages as 21--38 (not 21--36).
   - **Fix:** Change `21--36` to `21--38` if confirmed.

4. **[MINOR] Liu et al. (2019) "smooth sailing" quotation marks:**
   - **Current:** "...VT destroys value in 'smooth sailing' environments."
   - **Problem:** "Smooth sailing" does not appear to be a direct quote from Liu et al. (2019).
   - **Fix:** Remove quotation marks or rephrase: "...VT underperforms in calm market environments."

5. **[MINOR] Cederburg et al. (2020) content characterization:**
   - **Current:** "Cederburg et al. (2020) identify transaction costs as a primary concern..."
   - **Problem:** Their primary finding is about poor OOS performance and structural instability of spanning regressions, not specifically about transaction costs.
   - **Fix:** "Cederburg et al. (2020) question the out-of-sample viability of volatility-managed portfolios, noting concerns including transaction costs..."

### OPTIONAL IMPROVEMENTS

6. **CBOE (2014):** Add URL to the VVIX methodology page or verify the exact white paper title and year.

7. **DOIs:** Consider adding DOIs to all entries for improved verifiability (standard practice for post-2020 submissions).

8. **Perchet et al. year:** Decide definitively between 2015 and 2016; ensure bibitem key matches.

---

*End of citation verification report.*
