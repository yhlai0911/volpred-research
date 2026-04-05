# PRG Paper Literature Survey
Date: 2026-04-05

## Summary

This survey identifies **30+ papers** across 7 categories relevant to the Periodic Realized GARCH (PRG) paper. The PRG's core contribution -- a single GARCH variance recursion with session-periodic parameters where h_{n-1} carries across overnight/intraday sessions -- sits at the intersection of periodic GARCH, session decomposition, and realized volatility literatures.

---

## Category 1: Periodic GARCH Models

1. **Bollerslev & Ghysels (1996)** - "Periodic autoregressive conditional heteroscedasticity" - *Journal of Business & Economic Statistics*, 14(2), 139-151.
   - **Key finding:** Introduced the P-GARCH model allowing GARCH parameters to vary over calendar periods (day-of-week). Foundational work on periodic variance structures.
   - **Relevance:** Direct ancestor of PRG. PRG extends periodicity from calendar-based (Mon-Fri) to session-based (overnight vs. intraday). **Already cited in paper.**

2. **Franses & Paap (2000)** - "Modelling day-of-the-week seasonality in the S&P 500 index" - *Applied Financial Economics*, 10(5), 483-488.
   - **Key finding:** PAR-PIGARCH model captures day-of-week seasonality in both returns and volatility; found positive autocorrelation on Monday, negative on Tuesday.
   - **Relevance:** Shows periodic GARCH is effective for calendar seasonality. PRG applies the same idea to a more fundamental periodicity (overnight/intraday).

3. **Mixture Periodic GARCH** - Billio, Casarin & Osuntuyi (2018) - "Mixture periodic GARCH models: theory and applications" - *Empirical Economics*, 55, 1485-1517.
   - **Key finding:** M-PGARCH combines mixture distributions with periodic parameters; more parsimonious than MPARCH models.
   - **Relevance:** Shows periodic GARCH can be extended with richer distributions. PRG takes a different route (realized measures rather than richer distributions).

4. **Periodic Long-Memory GARCH** - Bordignon, Caporin & Lisi (2007) - "Periodic long-memory GARCH models" - *Econometric Reviews*.
   - **Key finding:** PLM-GARCH extends FIGARCH with periodic parameters to capture long-range persistence with seasonality.
   - **Relevance:** Another periodic extension of GARCH; PRG is simpler (no long memory) but addresses a different type of periodicity (session vs. calendar).

5. **Periodic log-GARCH** - Ambach & Forstinger (2024) - "On periodic log-GARCH model with empirical application" - *Statistics and Computing*, 34, 173.
   - **Key finding:** Introduces P-logGARCH with periodic parameters in logarithmic specification; applies to energy markets.
   - **Relevance:** Most recent periodic GARCH extension. Confirms continued interest in periodic variance structures.

---

## Category 2: Overnight / Session Volatility Decomposition

6. **Blanc, Chicheportiche & Bouchaud (2014)** - "The fine structure of volatility feedback II: Overnight and intra-day effects" - *Physica A*, 402, 58-75.
   - **Key finding:** Within an ARCH framework, overnight and intraday returns behave completely differently: past intraday returns affect both future intraday and overnight volatilities equally, but past overnight returns mainly impact future overnight volatilities. The exogenous component of overnight volatility is close to zero (feedback-dominated).
   - **Relevance:** **Highly relevant.** Provides the empirical motivation for PRG's session-specific parameters. The asymmetric cross-session feedback is exactly what PRG's h_{n-1} bridge captures.

7. **Tsiakas (2008)** - "Overnight information and stochastic volatility: A study of European and US stock exchanges" - *Journal of Banking & Finance*, 32, 251-268.
   - **Key finding:** Overnight information has substantial predictive ability for volatility; distinguishes weeknight, weekend, holiday, and long weekend effects with asymmetric news impact.
   - **Relevance:** Establishes that overnight information matters for volatility forecasting. PRG formalizes this through the session-boundary transfer mechanism.

8. **Taylor (2007)** - "A note on the importance of overnight information in risk management models" - *Journal of Banking & Finance*, 31(1), 161-180.
   - **Key finding:** Incorporating overnight return information into VaR models improves accuracy across diverse financial markets.
   - **Relevance:** PRG's VaR application (Section 5) builds on this insight; PRG provides a structural model for why overnight information matters.

9. **Todorova & Soucek (2014)** - "Overnight information flow and realized volatility forecasting" - *Finance Research Letters*, 11(4), 420-428.
   - **Key finding:** Considering overnight information separately (rather than adding it to daily RV) consistently leads to better out-of-sample results despite higher parameter count.
   - **Relevance:** **Directly supports PRG's design.** PRG treats sessions separately with cross-session linkage, rather than aggregating. This paper provides empirical justification.

10. **Ahoniemi & Lanne (2013)** - "Overnight stock returns and realized volatility" - *International Journal of Forecasting*, 29(4), 592-604.
    - **Key finding:** For S&P 500 index, RV estimator incorporating overnight information is more accurate in-sample; for individual stocks, estimators without overnight are better. Method of incorporating overnight affects out-of-sample model rankings.
    - **Relevance:** Shows that *how* overnight information is incorporated matters -- simple addition may not be optimal. PRG's structural approach (variance recursion bridge) is an alternative.

11. **Kambouroudis, McMillan & Tsakou (2021)** - "Forecasting realized volatility: The role of implied volatility, leverage effect, overnight returns, and volatility of realized volatility" - *Journal of Futures Markets*, 41(10), 1618-1639.
    - **Key finding:** HAR-IV augmented with overnight returns improves forecasts in all markets except UK; leverage effect helps in 5/6 markets.
    - **Relevance:** Confirms overnight returns contain incremental forecasting power beyond IV and leverage. PRG captures this through session-specific parameters rather than adding regressors.

---

## Category 3: Realized GARCH and Variants

12. **Hansen, Huang & Shek (2012)** - "Realized GARCH: A joint model for returns and realized measures of volatility" - *Journal of Applied Econometrics*, 27(6), 877-906.
    - **Key finding:** Introduced Realized GARCH framework jointly modeling returns and realized measures via a measurement equation; leads to substantial improvements over standard GARCH; implies ARMA structure for conditional variance.
    - **Relevance:** PRG extends this framework by adding session-periodic structure. The "Realized" in PRG refers to using realized measures (RV from 5-min data) as volatility proxies. **Already cited in paper.**

13. **Hansen & Huang (2016)** - "Exponential GARCH modeling with realized measures of volatility" - *Journal of Business & Economic Statistics*, 34(2), 269-287.
    - **Key finding:** Exponential Realized GARCH (EGARCH-X) model incorporating realized measures; log-linear specification avoids non-negativity constraints.
    - **Relevance:** Shows exponential specification works well with realized measures. PRG uses linear specification for simplicity but could be extended to log-linear. **Already cited in paper.**

14. **Kim, Shin & Wang (2023)** - "Overnight GARCH-Ito volatility models" - *Journal of Business & Economic Statistics*, 41(4), 1215-1227.
    - **Key finding:** Proposes Ito diffusion-based overnight volatility model accommodating two different instantaneous volatility processes for open-to-close and close-to-open; incorporates integrated volatility as innovation.
    - **Relevance:** **Very closely related.** Both PRG and this model recognize two distinct session dynamics. The key difference: PRG uses a discrete GARCH recursion (simpler, practitioner-friendly), while Kim et al. use continuous-time Ito diffusions (theoretically elegant but harder to estimate). PRG's advantage is parsimony.

15. **Kim, Oh, Song & Wang (2023)** - "Factor Overnight GARCH-Ito Models" - *Working paper / arXiv 2204.06906*.
    - **Key finding:** Extends Overnight GARCH-Ito to factor models for large volatility matrix estimation; separate factor volatility processes for open-to-close and close-to-open.
    - **Relevance:** Multivariate extension of #14; shows the session-decomposition idea scales. PRG could similarly be extended to multivariate settings.

---

## Category 4: Coupled/Component Models for Intraday and Overnight

16. **Linton & Wu (2020)** - "A coupled component DCS-EGARCH model for intraday and overnight volatility" - *Journal of Econometrics*, 217(1), 176-201.
    - **Key finding:** Bivariate model for intraday and overnight returns respecting temporal ordering; permits different marginal properties and mutual feedback; uses dynamic conditional score (DCS) approach with t-distributions.
    - **Relevance:** **Most directly comparable to PRG.** Both models: (a) treat sessions separately, (b) allow cross-session feedback, (c) respect temporal ordering. Key difference: Linton & Wu use DCS-EGARCH (score-driven, ~12+ parameters), while PRG uses simple GARCH recursion (6-8 parameters). PRG is more parsimonious.

17. **Dhaene & Wu (2020)** - "Incorporating overnight and intraday returns into multivariate GARCH volatility models" - *Journal of Econometrics*, 217(2), 471-495.
    - **Key finding:** Mixed-frequency multivariate GARCH (BEKK type) modeling low-frequency volatility as weighted sum of intraday and overnight components using 5-minute returns; systematically dominates models using only lower-frequency data.
    - **Relevance:** Another approach to session decomposition in GARCH. Uses mixed-frequency (5-min + overnight) while PRG uses session-level returns. PRG is simpler (univariate, 6-8 params) but shares the core insight.

18. **Opschoor & Lucas (2021)** - "Observation-driven models for realized variances and overnight returns applied to Value-at-Risk and Expected Shortfall forecasting" - *International Journal of Forecasting*, 37(2), 622-633.
    - **Key finding:** Decomposes daily volatility into filtered open-to-close volatility and time-varying scaling factor; uses score-driven dynamics with fat-tailed distributions; outperforms HEAVY model and separate-process models for VaR and ES.
    - **Relevance:** **Closely related to PRG's VaR/ES evaluation.** Both papers evaluate session-decomposition models on VaR/ES. PRG's simpler structure (GARCH recursion) vs. Opschoor & Lucas's score-driven approach.

19. **Engle & Sokalska (2012)** - "Forecasting intraday volatility in the US equity market. Multiplicative component GARCH" - *Journal of Financial Econometrics*, 10(1), 54-83.
    - **Key finding:** Decomposes intraday variance into daily, diurnal, and stochastic components (multiplicative); pooled cross-section outperforms company-by-company estimation.
    - **Relevance:** Influential component decomposition approach. PRG's decomposition (overnight + intraday) is at a coarser level but addresses a different question (session boundary transfer vs. within-day periodicity).

---

## Category 5: Option Pricing with Session Decomposition

20. **Liang, Du & Huang (2023)** - "Option pricing with overnight and intraday volatility" - *Journal of Futures Markets*, 43(11), 1576-1614.
    - **Key finding:** Bisected Realized GARCH (BRG) separating close-to-open and open-to-close components; derives option pricing formulas via multivariate Edgeworth expansion.
    - **Relevance:** The BRG model is structurally similar to PRG but applied to option pricing. Both bisect the day into overnight/intraday. Key difference: BRG uses separate equations without the cross-session h_{n-1} bridge that defines PRG. This is essentially PRG's "Separate GARCH" ablation benchmark.

21. **Wang, Cheng, Yin & Yu (2022)** - "Overnight volatility, realized volatility, and option pricing" - *Journal of Futures Markets*, 42(7), 1264-1283.
    - **Key finding:** Integrates intraday, overnight returns, and realized volatility in an augmented Autoregressive Volatility model; derives analytical option pricing formula; distinguishing overnight reduces pricing errors.
    - **Relevance:** Confirms that session decomposition improves derivative pricing. PRG's contribution is in the forecasting domain, but could be extended to option pricing.

---

## Category 6: Foundational Volatility Forecasting & Evaluation

22. **Hansen & Lunde (2005)** - "A forecast comparison of volatility models: Does anything beat a GARCH(1,1)?" - *Journal of Applied Econometrics*, 20(7), 873-889.
    - **Key finding:** Compared 330 GARCH-type models; GARCH(1,1) not beaten for exchange rates but clearly inferior for equities (leverage effect matters). Established the SPA test for model comparison.
    - **Relevance:** PRG paper's GJR benchmark is motivated by this finding that leverage matters for equities. The cross-session bridge in PRG provides improvement beyond leverage. **Already cited in paper.**

23. **Patton (2011)** - "Volatility forecast comparison using imperfect volatility proxies" - *Journal of Econometrics*, 160(1), 246-256.
    - **Key finding:** QLIKE loss function is robust to noise in unbiased volatility proxies; model rankings under QLIKE are preserved regardless of proxy quality.
    - **Relevance:** **Core evaluation methodology in PRG paper.** Using r^2 as proxy for sigma^2 is justified by this result. **Already cited in paper.**

24. **Corsi (2009)** - "A simple approximate long-memory model of realized volatility" - *Journal of Financial Econometrics*, 7(2), 174-196.
    - **Key finding:** HAR model captures long memory in RV with simple OLS-estimable structure using daily/weekly/monthly components.
    - **Relevance:** HAR is a key benchmark in PRG paper. PRG shows HAR advantage over GJR disappears on common target (target-mismatch artifact). **Already cited in paper.**

25. **Andersen, Bollerslev, Diebold & Labys (2003)** - "Modeling and forecasting realized volatility" - *Econometrica*, 71(2), 579-625.
    - **Key finding:** Foundational work on realized volatility; simple long-memory Gaussian VAR for log(RV) produces excellent forecasts; established the RV framework.
    - **Relevance:** Theoretical foundation for using 5-minute RV as volatility proxy in PRG's TAIFEX analysis.

26. **Shephard & Sheppard (2010)** - "Realising the future: forecasting with high-frequency-based volatility (HEAVY) models" - *Journal of Applied Econometrics*, 25, 197-231.
    - **Key finding:** HEAVY models directly model daily volatility using realized measures; adjust quickly to structural breaks; outperform GARCH during credit crunch.
    - **Relevance:** HEAVY is a precursor to Realized GARCH; PRG extends this line by adding session-periodic structure.

27. **Hansen, Lunde & Nason (2011)** - "The model confidence set" - *Econometrica*, 79(2), 453-497.
    - **Key finding:** MCS provides a formal statistical procedure for determining which models belong to the set of "best" models at a given confidence level.
    - **Relevance:** Used in PRG paper for joint model comparison. PRG Extended survives MCS while GJR and HAR are eliminated. **Already cited in paper.**

28. **Fissler & Ziegel (2016)** - "Higher order elicitability and Osband's principle" - *The Annals of Statistics*, 44(4), 1680-1707.
    - **Key finding:** VaR and ES are jointly elicitable; provides consistent loss functions for joint backtesting.
    - **Relevance:** Used in PRG paper for joint VaR-ES evaluation (FZ loss). **Already cited in paper.**

---

## Category 7: Recent Work on Overnight Volatility (2023-2026)

29. **Hao (2025/2026)** - "Overnight trading matters! Volatility forecast in the crude oil futures market" - *Journal of Forecasting*.
    - **Key finding:** Integrating overnight information into HAR models notably improves crude oil futures volatility forecasts; short-term overnight information has more predictive power than long-term.
    - **Relevance:** Very recent confirmation that overnight trading session matters for forecasting. PRG goes beyond augmenting HAR with overnight regressors -- it provides a structural model for the cross-session link.

30. **He et al. (2025)** - "What the night tells the day: Forecasting realized volatility in Chinese commodity markets" - *Journal of Futures Markets*.
    - **Key finding:** Night-session realized volatility significantly predicts daytime volatility across 10 Chinese commodity futures; separating jump and continuous components of night-session RV improves long-horizon forecasts.
    - **Relevance:** Confirms the night-to-day information flow in commodity futures (similar to PRG's TAIFEX finding). The Chinese night session is analogous to TAIFEX's night session covering US market hours.

31. **Chen & Huang (2025)** - "Forecasting Chinese stock market volatility with intraday and overnight volatility components of INE oil futures" - *Journal of Futures Markets*, 45(10), 1665-1682.
    - **Key finding:** Overnight volatility of INE oil futures significantly improves Chinese stock volatility forecasting, while 5-minute intraday RV does not.
    - **Relevance:** Shows overnight information has *incremental* value beyond intraday high-frequency data. Supports PRG's emphasis on the overnight session.

32. **Zhang, Zhou & Liu (2025)** - "The information content of overnight information for volatility forecasting: Evidence from China's stock market" - *Journal of Forecasting*, 44(8), 2331-2345.
    - **Key finding:** Overnight volatility proxy within HAR models significantly improves realized range-based volatility forecasts; improvement strongest at short horizons; performs extremely well during market turbulence.
    - **Relevance:** Confirms overnight info is most valuable at short horizons (1-day), which is PRG's primary forecasting target.

33. **Zhao et al. (2025)** - "Intraday and overnight causality in time and frequency domains: Evidence from stock returns and volatility" - *International Journal of Finance & Economics*.
    - **Key finding:** Bidirectional and nonlinear Granger causality between overnight and intraday returns/volatility; trading volume is an important transmission channel; causality driven by specific time-frequency components.
    - **Relevance:** Provides frequency-domain evidence for the cross-session information flow that PRG models through the h_{n-1} bridge.

---

## Category 8: TAIFEX / Taiwan-Specific Studies

34. **Lai, Wang & Chang (2024)** - "Forecasting trading-session return volatility in Taiwan futures market: A periodic regime switching with jump approach" - *Asia-Pacific Financial Markets*, 31(2), 285-305.
    - **Key finding:** PRS model with Markov regime switching and jumps for TAIFEX session-level volatility forecasting; significant improvements over standard GARCH in both in-sample and out-of-sample.
    - **Relevance:** **PRG paper's direct predecessor.** PRG simplifies PRS by replacing Markov switching with deterministic session index, eliminating Hamilton filter. **Already cited in paper.**

35. **So & Yu (2006)** - "Empirical analysis of GARCH models in Value at Risk estimation" - *Journal of International Financial Markets, Institutions and Money*, 16(2), 180-197.
    - **Key finding:** For TAIFEX and SGX-DT Taiwan stock index futures, Normal APARCH is preferred at lower confidence levels; fat tails and volatility clustering are prominent.
    - **Relevance:** Provides context for TAIFEX volatility properties that motivate PRG's application to this market.

36. **Time-varying predictability of TAIEX volatility** - Guo et al. (2025) - *Review of Derivatives Research*.
    - **Key finding:** Novel periodic regime-switching models improve forecasting of TAIEX volatility.
    - **Relevance:** Confirms that periodic/regime-switching approaches are effective for Taiwan markets.

---

## Papers Already Cited in PRG Paper (for reference)

| # | Citation Key | Authors | Year | Already in bibliography |
|---|-------------|---------|------|------------------------|
| 1 | Bollerslev1986 | Bollerslev | 1986 | Yes |
| 2 | Bollerslev1996 | Bollerslev & Ghysels | 1996 | Yes |
| 3 | Corsi2009 | Corsi | 2009 | Yes |
| 4 | Diebold1995 | Diebold & Mariano | 1995 | Yes |
| 5 | Fissler2016 | Fissler & Ziegel | 2016 | Yes |
| 6 | Glosten1993 | Glosten, Jagannathan & Runkle | 1993 | Yes |
| 7 | Haas2004 | Haas, Mittnik & Paolella | 2004 | Yes |
| 8 | Hansen2016RealizedGARCH | Hansen & Huang | 2016 | Yes |
| 9 | Hansen2005 | Hansen & Lunde | 2005 | Yes |
| 10 | Hansen2011MCS | Hansen, Lunde & Nason | 2011 | Yes |
| 11 | Hansen2012 | Hansen, Huang & Shek | 2012 | Yes |
| 12 | Harvey2016 | Harvey, Liu & Zhu | 2016 | Yes |
| 13 | Harvey1997 | Harvey, Leybourne & Newbold | 1997 | Yes |
| 14 | Lai2024 | Lai, Wang & Chang | 2024 | Yes |
| 15 | Patton2011 | Patton | 2011 | Yes |

---

## Priority Additions to PRG Bibliography

Based on this survey, the following papers are **most important to add** to the PRG paper's bibliography (ranked by relevance):

### Must-Add (directly address PRG's core mechanism)

1. **Linton & Wu (2020)** - Coupled component DCS-EGARCH for intraday/overnight - *J. Econometrics*
   - Most directly comparable model; PRG should position itself as a simpler alternative.

2. **Kim, Shin & Wang (2023)** - Overnight GARCH-Ito - *JBES*
   - Continuous-time analog of PRG's session decomposition; PRG should distinguish itself as discrete-time/practitioner-friendly.

3. **Blanc, Chicheportiche & Bouchaud (2014)** - Fine structure of volatility feedback II - *Physica A*
   - Empirical evidence for asymmetric overnight/intraday feedback; provides micro-foundation for PRG.

4. **Todorova & Soucek (2014)** - Overnight information flow and RV forecasting - *Finance Research Letters*
   - Directly supports PRG's separate-session approach over aggregation.

5. **Opschoor & Lucas (2021)** - Observation-driven models for RV + overnight returns - *IJF*
   - Comparable VaR/ES evaluation framework; PRG should compare.

### Should-Add (context and support)

6. **Dhaene & Wu (2020)** - Mixed-frequency multivariate GARCH with overnight - *J. Econometrics*
7. **Ahoniemi & Lanne (2013)** - Overnight stock returns and RV - *IJF*
8. **Tsiakas (2008)** - Overnight information and stochastic volatility - *JBF*
9. **Andersen, Bollerslev, Diebold & Labys (2003)** - Modeling and forecasting realized volatility - *Econometrica*
10. **Shephard & Sheppard (2010)** - HEAVY models - *JAE*

### Nice-to-Have (recent supporting evidence)

11. **Liang, Du & Huang (2023)** - BRG option pricing - *JFM*
12. **Hao (2025/2026)** - Overnight trading matters, crude oil - *J. Forecasting*
13. **He et al. (2025)** - Night tells the day, Chinese commodities - *JFM*
14. **Zhang, Zhou & Liu (2025)** - Overnight info content, China - *J. Forecasting*
15. **Engle & Sokalska (2012)** - Multiplicative component GARCH - *JFEC*
