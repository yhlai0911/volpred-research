# Citation Check Report — Paper 4: Volatility Absorption
**Generated:** 2026-03-30
**File checked:** `paper/volatility-absorption/main.tex`

---

## Summary

| Metric | Count |
|--------|-------|
| Total bibliography entries | 20 |
| Entries cited in body text (via `\citet{}` / `\citep{}` / `\citealt{}`) | 20 |
| **Confirmed orphan references** | **0** |
| Missing references (cited in body but not in bibliography) | 0 |
| Format issues identified | 4 |
| Factual/plausibility concerns | 6 |
| Recommended additions (missing from literature) | 12 |

---

## 1. Orphan References (in bibliography but not cited in body)

**None found.** All 20 bibliography entries are cited at least once.

---

## 2. Missing References (cited in body but not in bibliography)

**None found.** All `\citet{}`, `\citep{}`, and `\citealt{}` commands have matching `\bibitem` entries.

---

## 3. Citation-by-Citation Verification

### 3.1 Verified Correct

| Key | Entry | Status |
|-----|-------|--------|
| `mandelbrot1963` | Mandelbrot, B. (1963). The variation of certain speculative prices. *Journal of Business*, 36(4), 394--419. | **CORRECT.** Classic reference. |
| `engle1982` | Engle, R.F. (1982). Autoregressive conditional heteroscedasticity... *Econometrica*, 50(4), 987--1007. | **CORRECT.** |
| `bollerslev1986` | Bollerslev, T. (1986). Generalized autoregressive conditional heteroskedasticity. *Journal of Econometrics*, 31(3), 307--327. | **CORRECT.** |
| `hamilton1989` | Hamilton, J.D. (1989). A new approach to the economic analysis of nonstationary time series... *Econometrica*, 57(2), 357--384. | **CORRECT.** |
| `kahneman1979` | Kahneman, D. & Tversky, A. (1979). Prospect theory... *Econometrica*, 47(2), 263--291. | **CORRECT.** |
| `nelson1991` | Nelson, D.B. (1991). Conditional heteroskedasticity in asset returns... *Econometrica*, 59(2), 347--370. | **CORRECT.** |
| `glosten1993` | Glosten, L.R., Jagannathan, R. & Runkle, D.E. (1993). On the relation between the expected value... *Journal of Finance*, 48(5), 1779--1801. | **CORRECT.** |
| `christie1982` | Christie, A.A. (1982). The stochastic behavior of common stock variances... *Journal of Financial Economics*, 10(4), 407--432. | **CORRECT.** |
| `romer2004` | Romer, C.D. & Romer, D.H. (2004). A new measure of monetary shocks... *American Economic Review*, 94(4), 1055--1084. | **CORRECT.** |

### 3.2 Concerns Identified

| # | Key | Entry | Issue | Severity |
|---|-----|-------|-------|----------|
| F1 | `black1976` | Black, F. (1976). Studies of stock price volatility changes. *Proceedings of the 1976 Meetings of the ASA*, 177--181. | **CORRECT** but incomplete citation. The full venue is "Proceedings of the 1976 Meetings of the American Statistical Association, Business and Economics Statistics Section." The paper has it correct in the body text (line 651) but the bibitem is acceptable as-is. Minor. | LOW |
| F2 | `bollerslev2009` | Bollerslev, T., Tauchen, G. & Zhou, H. (2009). Expected stock returns and variance risk premia. *Review of Financial Studies*, 22(11), 4463--4492. | **CORRECT.** Volume 22, Issue 11. | OK |
| F3 | `carr2009` | Carr, P. & Wu, L. (2009). Variance risk premiums. *Review of Financial Studies*, 22(3), 1311--1341. | **CORRECT.** | OK |
| F4 | `bekaert2000` | Bekaert, G. & Wu, G. (2000). Asymmetric volatility and risk in equity markets. *Review of Financial Studies*, 13(1), 1--42. | **CORRECT.** | OK |
| F5 | `bekaert2014` | Bekaert, G. & Hoerova, M. (2014). The VIX, the variance premium and stock market volatility. *Journal of Econometrics*, 183(2), 181--192. | **CORRECT.** | OK |
| F6 | `barberis2001` | Barberis, N., Huang, M. & Santos, T. (2001). Prospect theory and asset prices. *Quarterly Journal of Economics*, 116(1), 1--53. | **CORRECT.** | OK |
| F7 | `andrei2015` | Andrei, D. & Hasler, M. (2015). Investor attention and stock market volatility. *Review of Financial Studies*, 28(1), 33--72. | **CORRECT.** | OK |
| F8 | `fleming2001` | Fleming, J., Kirby, C. & Ostdiek, B. (2001). The economic value of volatility timing. *Journal of Finance*, 56(1), 329--352. | **CORRECT.** | OK |
| F9 | `moreira2017` | Moreira, A. & Muir, T. (2017). Volatility-managed portfolios. *Journal of Finance*, 72(4), 1611--1644. | **CORRECT.** | OK |

---

## 4. Factual/Plausibility Concerns

| # | Location | Claim | Concern | Severity |
|---|----------|-------|---------|----------|
| P1 | `haas2004` | Haas, M., Mittnik, S. & Paolella, M.S. (2004). A new approach to Markov-switching GARCH models. *Journal of Financial Econometrics*, 2(4), 493--530. | **VERIFY VOLUME/ISSUE.** JFE Volume 2 was published in 2004. Issue 4, pages 493--530 is plausible. However, alternative sources list this as pages 493--530 in Volume 2, Issue 4 — consistent. **Likely correct.** | LOW |
| P2 | `harvey2018` | Harvey, C.R. et al. (2018). The impact of volatility targeting. *Journal of Portfolio Management*, 45(1), 14--33. | **DATE DISCREPANCY.** The bibitem year says 2018, but JPM 45(1) was published in Fall 2018 (dated 2018). Some databases list this as 2019 because the issue date is October 2018 but formally Volume 45, Number 1, Fall 2018. The `\bibitem` label says `Harvey et al.(2018)` which is acceptable. Minor formatting concern: some style guides would use 2018 while others 2019 depending on the "official" publication date. | MEDIUM |
| P3 | `lin2020` | Lin, C.-C., Chen, C.-S. & Hwang, D.-Y. (2020). Does VIX or volume improve... *Pacific-Basin Finance Journal*, 61, 101316. | **VERIFY AUTHORS AND ARTICLE NUMBER.** PBFJ Volume 61 was published in June 2020. Article 101316 is plausible for Elsevier sequential numbering. The exact author list and title should be verified against the actual publication. The paper uses this citation only once (line 353) to support a US-Taiwan lead-lag claim, which is a reasonable use. | MEDIUM |
| P4 | Line 75 | "the variance risk premium literature (Bollerslev et al., 2009; Carr and Wu, 2009)" | The paper cites these as establishing the VRP literature, which is correct. However, the claim "We find that the VRP narrows at high VIX (+2.8% annualized versus +3.5% at low VIX) but remains strictly positive---there is no VRP sign flip, contrary to some prior claims" does **not cite which prior claims** it is refuting. This is a strong refutation without a target. | MEDIUM |
| P5 | Line 75 | "the behavioral finance literature on 'panic fatigue' or 'crisis habituation' (Kahneman and Tversky, 1979; Barberis et al., 2001)" | **MISATTRIBUTION.** Neither Kahneman & Tversky (1979) nor Barberis et al. (2001) use the terms "panic fatigue" or "crisis habituation." KT1979 is about prospect theory (gains/losses framing), not about habituation to repeated shocks. Barberis et al. (2001) model investor sentiment affecting risk premiums via prior outcomes, which is related but is not about habituation to fear. The paper puts these terms in quotes as if citing them, but these are the authors' own labels. | HIGH |
| P6 | Line 104 | "investor attention as a scarce resource that becomes saturated during crises, reducing the informativeness of prices" (attributed to Andrei & Hasler 2015) | **VERIFY CLAIM.** Andrei & Hasler (2015) model attention as endogenous and show that higher attention increases price informativeness and volatility. The paper's characterization of attention becoming "saturated during crises, reducing informativeness" is a loose interpretation. A&H show that attention is high during volatile periods, which increases informativeness — somewhat the opposite of what the paper claims. | MEDIUM |

---

## 5. Format Issues

| # | Issue | Location | Severity |
|---|-------|----------|----------|
| FMT1 | `\citealt{romer2004}` used without parentheses/year format on line 624. `\citealt` produces "Romer and Romer 2004" without parentheses — this is correct usage in the context "as in \citealt{romer2004}" but the sentence reads awkwardly because it says "narrative identification as in Romer and Romer 2004" without year parentheses. Consider `\citep{romer2004}` or `\citet{romer2004}`. | Line 624 | LOW |
| FMT2 | All `\bibitem` entries use manual formatting rather than BibTeX. The `\bibliographystyle{apalike}` declaration on line 635 is ignored because the bibliography is manual (`\begin{thebibliography}{99}`). This creates an inconsistency: the style declaration has no effect. Remove `\bibliographystyle{apalike}` or switch to `.bib` file. | Lines 635--701 | LOW |
| FMT3 | Author format inconsistency: some entries use `\&` (e.g., `Andrei, D., \& Hasler, M.`) while APA style requires `&` without backslash in the bibliography. However, since these are in a LaTeX `\thebibliography` environment, the `\&` is needed to produce the `&` character. This is technically correct LaTeX but visually different from standard APA. | Throughout | LOW |
| FMT4 | The `\bibitem` labels use `Author(Year)` format consistently (e.g., `[Bollerslev(1986)]`), which is correct for `apalike` natbib compatibility. No issues found. | Throughout | OK |

---

## 6. Recommended Missing References

The following references are strongly recommended based on the review report:

| # | Reference | Why Needed |
|---|-----------|-----------|
| 1 | Zakoian, J.-M. (1994). Threshold heteroskedastic models. *J. Time Series Analysis*, 15(3), 253--266. | Threshold GARCH directly models state-dependent shock impacts — the core phenomenon this paper studies. |
| 2 | Engle, R.F. & Ng, V.K. (1993). Measuring and testing the impact of news on volatility. *Journal of Finance*, 48(5), 1749--1778. | News impact curves parameterize how shock impact varies — natural comparison framework. |
| 3 | Da, Z., Engelberg, J. & Gao, P. (2015). The sum of all FEARS: Investor sentiment and asset prices. *Review of Financial Studies*, 28(1), 1--32. | FEARS index — direct measure of investor fear/attention, directly relevant to absorption. |
| 4 | Vlastakis, N. & Markellos, R.N. (2012). Information demand and stock market volatility. *Journal of Banking & Finance*, 36(6), 1808--1821. | Information demand framework for volatility — directly relevant and in the target journal. |
| 5 | Whaley, R.E. (2000). The investor fear gauge. *Journal of Portfolio Management*, 26(3), 12--17. | The original "fear gauge" paper; essential for a paper about "market fear." |
| 6 | Andersen, T.G., Bollerslev, T., Diebold, F.X. & Vega, C. (2003). Micro effects of macro announcements. *American Economic Review*, 93(1), 38--62. | NFP event-study methodology standard; needed for Section 5.3. |
| 7 | Balduzzi, P., Elton, E.J. & Green, T.C. (2001). Economic news and bond prices. *Journal of Financial and Quantitative Analysis*, 36(4), 523--543. | Bond-market event study methodology. |
| 8 | Todorov, V. (2010). Variance risk-premium dynamics. *Review of Financial Studies*, 23(1), 345--383. | VRP and jumps — relevant to VRP section. |
| 9 | Drechsler, I. & Yaron, A. (2011). What's vol got to do with it. *Review of Financial Studies*, 24(1), 1--45. | Uncertainty premia framework. |
| 10 | Danielsson, J., Valenzuela, M. & Zer, I. (2018). Learning from history: Volatility and financial crises. *Review of Financial Studies*, 31(7), 2774--2805. | Endogenous risk in financial systems — directly relevant to the endo/exo decomposition. |
| 11 | Patton, A.J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246--256. | Alternative methodology for NSI comparison. |
| 12 | Muler, N. & Yohai, V.J. (2008). Robust estimates for GARCH models. *Journal of Statistical Planning and Inference*, 138(10), 2918--2940. | Relevant to outlier treatment in crisis bin. |

---

## 7. Cross-Reference Consistency

| Check | Result |
|-------|--------|
| All `\bibitem` keys match `\cite` commands | **PASS** |
| All `\cite` commands have `\bibitem` entries | **PASS** |
| No duplicate `\bibitem` keys | **PASS** |
| All `\ref` and `\label` pairs match | **PASS** (10 labels, all referenced) |
| Equation numbering sequential | **PASS** (Eq. 1--10) |
| Table numbering sequential | **PASS** (Tables 1--9, A1, A2) |

---

## 8. Summary of Action Items

### Must Fix (HIGH)
1. **P5:** Remove misattribution of "panic fatigue" / "crisis habituation" to Kahneman & Tversky (1979) and Barberis et al. (2001). These papers do not discuss habituation. Either find proper references for crisis habituation or present the concept as the authors' own framework.

### Should Fix (MEDIUM)
2. **P2:** Verify Harvey et al. (2018) vs. (2019) publication year for JPM.
3. **P3:** Verify Lin et al. (2020) article number and author list against PBFJ database.
4. **P4:** Cite the specific "prior claims" about VRP sign flips being refuted.
5. **P6:** Verify characterization of Andrei & Hasler (2015) — their model may not support the "saturation" interpretation.
6. **FMT2:** Remove `\bibliographystyle{apalike}` since bibliography is manual.

### Should Add
7. Add at least 10--12 references from the recommended list above to bring the bibliography to 30+ entries (standard for JBF).
