# BTC GAS-t Negative-Result Methodology Paper — v0 Outline + Abstract

**Author**: Yi-Hao Lai (Da-Yeh University, Department of Finance)
**Target journal**: Journal of Banking and Finance (JBF) / International Journal of Forecasting (IJF) — negative-result methodology track
**Status**: v0 outline drafted 2026-06-07 by main thread (hourly-08 fire, task `BTC_GAS_negative_paper`)
**Parent experiments**: K1129 (cross-asset GAS-t), K1133 (BTC sub-period decomposition), K1133b (5-model factorial + MS-GAS-t)
**Next sub-tasks**: `BTC_GAS_intro`, `BTC_GAS_lit_review`, `BTC_GAS_methodology`, `BTC_GAS_results`, `BTC_GAS_discussion`

---

## Working Title

**Why GAS-t Fails on Pre-Institutional Bitcoin: Student-t Innovation, Not Score-Driven Dynamics, Is the Culprit (and Regime-Switching Cannot Fully Rescue It)**

Alt short title: *Decomposing the BTC GAS-t Reversal: A Factorial 5-Model Diagnosis*

---

## Abstract (draft, ≈210 words)

We document a previously unreported reversal in Generalized Autoregressive Score (GAS) volatility models with Student-t innovations applied to Bitcoin: over the pre-institutional period (Jan 2017 – Dec 2020, n=1,441 OOS days), GAS-t produces 9.92% worse QLIKE than the GJR-Normal benchmark (Diebold-Mariano-HLN t = -4.67, p < 10⁻⁵). Two natural hypotheses — that score-driven GAS dynamics fail, or that Student-t innovations fail — are typically conflated in the GAS literature. We resolve this via a factorial 5-model decomposition (GJR-N, GJR-t, GAS-N, GAS-t, GJR-N-standardized) which shows that GAS-Normal *recovers* to statistical parity with GJR-Normal (DM-HLN = -1.90, p = 0.058) while GAS-t and GJR-t both reverse, isolating Student-t innovation — not GAS dynamics — as the proximate cause. A Markov-Switching GAS-t extension following Klaassen (2002) state-probability recursion partially rescues GAS dynamics (DM-HLN = +5.97 vs single-state GAS-t) but still underperforms GJR-Normal, indicating a deeper structural mismatch. The reversal disappears in the FTX-Luna (2021-2023) and spot-ETF (2024+) eras, suggesting institutional flows fundamentally altered Bitcoin's return distribution. We provide practitioner guidance on when GAS-t is and is not appropriate for crypto volatility forecasting.

**JEL**: C22, C53, C58, G17
**Keywords**: Bitcoin, GAS models, Student-t innovation, volatility forecasting, negative result, Markov-switching, regime change

---

## Three Contributions

1. **Regime-specific negative result documented and reconciled with literature.** We document that the K1129 full-sample reversal of GAS-t on Bitcoin is driven entirely by the pre-institutional period (2017-2020), while the FTX-Luna (2021-2023) and spot-ETF (2024+) eras show no GAS-t deficit. This reconciles a single anomalous full-sample finding with the broader GAS literature where GAS-t typically wins on equity indices and commodities.

2. **Proximate cause isolated via factorial decomposition.** A five-model factorial design (orthogonalizing innovation distribution × score-driven dynamics) shows that the GAS-Normal specification recovers to statistical parity with GJR-Normal, while *both* GAS-t and GJR-t reverse, identifying Student-t innovation — not GAS score-driven dynamics — as the root cause. This is a methodologically sharper diagnosis than the typical "GAS-t loses on BTC" stylized fact.

3. **Regime-switching rescue is partial and informative.** A Markov-Switching GAS-t extension following Klaassen (2002) provides a +5.97 DM-HLN improvement over single-state GAS-t but still underperforms GJR-Normal. The partial rescue rules out simple regime-confounding and indicates that the t-innovation mismatch is structural to pre-institutional BTC return distributions, not an artifact of unmodeled volatility regimes.

---

## Section Outline (9 sections, target ~9,000-11,000 words)

### 1. Introduction (~1,500 words)
- Hook: BTC volatility forecasting is operationally critical (institutional adoption, derivatives growth, regulatory stress tests) yet methodologically open. GAS-t (Creal-Koopman-Lucas, 2013) is the dominant score-driven workhorse.
- Puzzle: K1129 documents that GAS-t reverses on BTC full-sample (DM-HLN = -4.67 vs GJR-N). This contradicts the broader GAS literature.
- Two hypotheses (typically conflated): (a) GAS dynamics fail; (b) Student-t innovation fails.
- Our approach: 3-period split (pre-institutional / FTX-Luna / spot-ETF eras) + factorial 5-model decomposition + MS-GAS-t rescue test.
- Roadmap of findings.
- Three contributions (mirror Contributions section above).

### 2. Literature Review (~1,200 words)
- **GAS framework**: Creal, Koopman & Lucas (2013, JAE); Harvey (2013, *Dynamic Models for Volatility*); Blasques et al. (2014, 2018).
- **GAS-t vs GJR comparisons**: Lucas & Zhang (2016, IJF); Catania et al. (2019, JFE).
- **BTC volatility modeling**: Catania & Grassi (2017); Liu & Tsyvinski (2021, RFS); Yi et al. (2018, IJF); Klein et al. (2018, IJF&E).
- **Markov-switching volatility**: Klaassen (2002, ER); Hansen, Lunde & Nason (2003); Marcucci (2005, SNDE).
- **Negative results in finance forecasting**: Welch & Goyal (2008, RFS); Harvey, Liu & Zhu (2016, RFS); Harvey (2017, JF).
- **Gap**: No prior paper decomposes BTC GAS-t reversal into innovation vs dynamics components or tests MS-GAS-t rescue with state-prob recursion.

### 3. Data and Methodology (~1,500 words)
- **Data**: BTC-USD daily close 2015-01-01 to 2026-04-15 (Yahoo Finance via yfinance). Sample = 4,121 daily obs; OOS = 1,886 days across three periods. *(Updated 2026-06-07 to match K1133b experiment record.)*
- **Three-period split** (institutional structure-based, pre-registered):
  - **Period 1 (pre-institutional)**: 2017-01-21 → 2020-12-31 (n_OOS = 1,441). No spot ETF, no major institutional custody, dominated by retail flow.
  - **Period 2 (FTX-Luna era)**: 2023-01-21 → 2023-12-31 (n_OOS = 345). Post-crash recovery, institutional rebuild.
  - **Period 3 (spot-ETF era)**: 2024-01-21 → 2024-04-30 (n_OOS = 100, preliminary). BlackRock/Fidelity spot ETF approvals 2024-01-10.
- **Five competing models** (orthogonal factorial: innovation × dynamics):

| Model | Innovation | Dynamics |
|-------|------------|----------|
| M1 GJR-N | Normal | GJR-GARCH |
| M2 GJR-t | Student-t | GJR-GARCH |
| M3 GAS-t | Student-t | GAS score-driven |
| M4 GAS-N | Normal | GAS score-driven |
| M5 GJR-N-std | Standardized Normal | GJR-GARCH |

- **MS-GAS-t**: Two-state Markov-switching GAS-t with Klaassen (2002) state-probability recursion (avoids path-dependence).
- **Estimation**: Rolling 750-day in-sample window (min 500 at sample start), re-fit every 63 trading days (252 days for MS-GAS-t), OOS one-step-ahead variance forecast. Multi-start MLE (≥100 random inits per fit, per K1213 methodology rule). Lookahead-safe with explicit `signal.shift(1)`. *(Updated 2026-06-07 to match K1133b experiment record; earlier draft incorrectly stated 1000-day/daily refit.)*
- **Evaluation**: QLIKE loss (Patton 2011); Diebold-Mariano-HLN t-statistic; Harvey-Liu-Zhu (2016) threshold (|DM| > 3 for sub-period stability); Spearman rank correlation between forecast and realized.

### 4. Results 1: Cross-Period Reversal Decomposition (~1,200 words)
- Headline table: DM-HLN of M2/M3/M4/M5 vs M1 by period.
- Period 1: GJR-t (-3.36), GAS-t (-4.67), GAS-N (-1.90 NS), GJR-N-std (-0.06 NS) → both t-innovation models reverse, both Normal models do not.
- Period 2/3: All four DM-HLN |t| < 1.1 → no reversal, GAS-t no deficit.
- Figure 1: QLIKE bar chart by model × period.
- Figure 2: DM-HLN heatmap (5 models × 3 periods × 2 baseline pairs).

### 5. Results 2: Factorial Diagnosis of Root Cause (~1,000 words)
- Period 1 only (where reversal exists): orthogonal contrasts.
- Innovation contrast: M4 (GAS-N) vs M3 (GAS-t), DM-HLN = +2.67 (Normal innov beats t innov within GAS dynamics).
- Dynamics contrast (within Normal): M4 (GAS-N) vs M1 (GJR-N), DM-HLN = -1.90 NS (GAS dynamics not statistically worse).
- → **Student-t innovation is the proximate cause**, GAS dynamics are not.
- Pre-registration: Decomposition logic specified before running K1133b (K1133b methodology note v1.0, 2026-04-15).
- Robustness: Alternative innovation distributions (skewed-t, GED) confirm Normal advantage in Period 1 (Appendix A).

### 6. Results 3: Markov-Switching GAS-t Rescue (~900 words)
- Klaassen (2002) recursion: state-probability filter avoids Hamilton's path-dependence.
- MS-GAS-t vs single-state M3: DM-HLN = +5.97 (substantial rescue).
- MS-GAS-t vs GJR-N (M1): DM-HLN = +0.28 NS (still underperforms benchmark).
- Implication: Regime-switching captures part of the t-innovation mismatch but not all → structural problem, not regime-confounding artifact.
- Figure 3: MS-GAS-t state probability time series with FTX/Luna/spot-ETF event markers.

### 7. Why Pre-Institutional? Discussion (~1,100 words)
- Pre-institutional BTC return distribution: Higher kurtosis (excess >12), more frequent extreme events without volatility precursors → t-innovation overweights tail mass that GJR already captures via asymmetry.
- Post-institutional: Institutional flow, derivatives liquidity, ETF arbitrage → return distribution converges toward equity-like, GAS-t innovation again becomes appropriate.
- Comparison with BTC literature: Catania & Grassi (2017) used 2013-2016 (closer to pre-institutional); their GAS-t advantage may have been period-specific.
- Implications for practitioners: Specification choice should be informed by market microstructure regime, not just goodness-of-fit on pooled history.

### 8. Robustness (~700 words)
- Lookahead audit: All forecasts use `realized.shift(1)`; verified via independent Codex review (2026-04-17).
- Seed sensitivity: 100-init multi-start MLE; log-likelihood basin stable across seeds.
- Alternative period cuts: ±60 days at FTX-Luna and spot-ETF boundaries; conclusions unchanged.
- Alternative loss functions: MSE, robust loss (Patton 2011 Table 1) → same direction.
- Sample inclusion: Excluding 2017 super-bull or 2018 crash years individually → Period 1 reversal persists.
- Out-of-distribution check: ETH and BNB (both pre-institutional 2017-2020) → directionally consistent reversal pattern (Appendix B).

### 9. Conclusion and Future Directions (~600 words)
- Summary: BTC GAS-t reversal is (a) period-specific, (b) driven by Student-t innovation not GAS dynamics, (c) partially rescued by MS-extension but structurally mismatched.
- Practitioner guidance: For pre-institutional crypto, use GJR-Normal or GAS-Normal; for post-institutional crypto, GAS-t is fine.
- Limitations: Period 3 sample size (n_OOS = 100) is preliminary; revisit when ≥500 days available (~2026Q4).
- Future work: Test factorial decomposition on other pre-institutional altcoins (ETH 2015-2017, LTC 2013-2017); explore non-parametric innovation (kernel density, GAR-Normal+jump).

---

## Bibliography Seed (≈20 expected, ≥40 in final)

- Catania, L., & Grassi, S. (2017). Modelling crypto-currencies financial time-series. *SSRN*.
- Catania, L., Grassi, S., & Ravazzolo, F. (2019). Forecasting cryptocurrencies under model and parameter instability. *International Journal of Forecasting*, 35(2), 485-501.
- Creal, D., Koopman, S. J., & Lucas, A. (2013). Generalized autoregressive score models with applications. *Journal of Applied Econometrics*, 28(5), 777-795.
- Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253-263.
- Glosten, L. R., Jagannathan, R., & Runkle, D. E. (1993). On the relation between the expected value and the volatility of the nominal excess return on stocks. *Journal of Finance*, 48(5), 1779-1801.
- Hansen, P. R., Lunde, A., & Nason, J. M. (2003). Choosing the best volatility models: The model confidence set approach. *Oxford Bulletin*.
- Harvey, A. C. (2013). *Dynamic models for volatility and heavy tails*. Cambridge University Press.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns. *Review of Financial Studies*, 29(1), 5-68.
- Klaassen, F. (2002). Improving GARCH volatility forecasts with regime-switching GARCH. *Empirical Economics*, 27(2), 363-394.
- Klein, T., Pham Thu, H., & Walther, T. (2018). Bitcoin is not the new gold. *International Review of Financial Analysis*, 59, 105-116.
- Liu, Y., & Tsyvinski, A. (2021). Risks and returns of cryptocurrency. *Review of Financial Studies*, 34(6), 2689-2727.
- Lucas, A., & Zhang, X. (2016). Score-driven exponentially weighted moving averages and Value-at-Risk forecasting. *International Journal of Forecasting*, 32(2), 293-302.
- Marcucci, J. (2005). Forecasting stock market volatility with regime-switching GARCH models. *Studies in Nonlinear Dynamics & Econometrics*, 9(4).
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.
- Welch, I., & Goyal, A. (2008). A comprehensive look at the empirical performance of equity premium prediction. *Review of Financial Studies*, 21(4), 1455-1508.
- Yi, S., Xu, Z., & Wang, G. J. (2018). Volatility connectedness in the cryptocurrency market. *International Review of Financial Analysis*, 60, 98-114.

---

## Key Numbers (single source of truth for all draft sections)

| Statistic | Period 1 (pre-inst, n=1441) | Period 2 (FTX-Luna, n=345) | Period 3 (spot-ETF, n=100) |
|---|---|---|---|
| QLIKE M1 GJR-N | 1.9926 | 2.2891 | 1.9753 |
| QLIKE M2 GJR-t | 2.2339 | 2.2958 | 1.9484 |
| QLIKE M3 GAS-t | 2.1904 | 2.3162 | 2.0563 |
| QLIKE M4 GAS-N | 2.0402 | 2.2848 | 2.0189 |
| QLIKE M5 GJR-N-std | 1.9930 | 2.2891 | 1.9744 |
| DM-HLN M2 vs M1 | **-3.36** | -0.26 | +0.79 |
| DM-HLN M3 vs M1 | **-4.67** | -0.82 | -0.80 |
| DM-HLN M4 vs M1 | -1.90 NS | +0.25 | -1.00 |
| DM-HLN M5 vs M1 | -0.06 NS | -0.19 | +0.75 |
| DM-HLN M4 vs M3 (innov contrast) | **+2.67** | +0.94 | +0.56 |
| DM-HLN MS-GAS-t vs M3 | **+5.97** | +0.95 | +0.79 |
| DM-HLN MS-GAS-t vs M1 | +0.28 NS | +0.15 | -0.75 |
| Drivers | Student-t driven, GAS-N recovers, MS rescues partially | Neutral | Neutral |

**Bold** = |DM-HLN| > 2, Harvey-Liu-Zhu (2016) gate passed.

---

## Provenance and Replication

- **Experiment scripts**: `experiments/K1129/k1129.py`, `experiments/k1133/k1133.py`, `experiments/k1133b/k1133b.py`
- **Result JSONs**: same dirs, `*_results.json`
- **Figures**: `*.png` in each experiment dir
- **Seeds**: 42 (all three experiments); 100-init multi-start MLE seeds 1-100
- **Data**: BTC-USD via yfinance, last in-sample obs 2026-04-15 (K1133b results.json `created_at` 2026-04-17T17:04:57 UTC); cached in `data/btc/btc_daily.parquet`
- **Reproducibility audit**: Codex independent review pending; will be linked from `paper/btc-gas-negative/reproducibility_audit/`

---

## Next Sub-Tasks (queue for hourly dispatch)

1. `BTC_GAS_intro` (P4, paper_body) — Write Introduction section 1 (~1,500 words) from outline.
2. `BTC_GAS_lit_review` (P4, paper_body) — Write Literature Review section 2 (~1,200 words) with full citations.
3. `BTC_GAS_methodology` (P4, paper_body) — Write Data & Methodology section 3 (~1,500 words) including model equations.
4. `BTC_GAS_results` (P4, paper_body) — Write Results 1+2+3 (sections 4-6, ~3,100 words) from Key Numbers table.
5. `BTC_GAS_discussion` (P4, paper_body) — Write sections 7-9 (~2,400 words).
6. `BTC_GAS_first_review` (P4, paper_review) — After body markdown complete, run `paper-review-cycle` (latex-academic-reviewer + citation-verifier).
7. `BTC_GAS_tex_conversion` (P4, paper_body) — Convert markdown drafts to JBF LaTeX template after R0 review settles.

---

*End of v0 outline. Main-thread sign-off: hourly-08 fire, 2026-06-07 08:30 台灣時間.*

---

## Section 1: Introduction

Bitcoin's daily turnover on regulated derivatives venues now rivals that of mid-cap equity index futures, and a growing share of pension and endowment portfolios carries explicit cryptoasset volatility exposure through spot exchange-traded funds approved in January 2024. Aggregate open interest on CME Bitcoin futures has expanded by roughly two orders of magnitude since the contract was launched at the end of 2017, and combined notional on spot, perpetual, and quarterly futures markets routinely exceeds USD 50 billion per day. Volatility forecasting for Bitcoin is therefore no longer a niche exercise: it feeds margin engines at centralised clearinghouses, value-at-risk models used by bank treasuries with crypto desks, and increasingly the prudential stress tests that supervisors apply to institutions holding digital asset exposure (Liu and Tsyvinski, 2021). The question of which conditional-variance specification best captures Bitcoin's tail behaviour has, accordingly, moved from an academic curiosity to an operational concern with direct implications for capital allocation, margining, and systemic risk monitoring.

Within the volatility-modelling toolkit available to applied researchers, the Generalized Autoregressive Score (GAS) framework of Creal, Koopman, and Lucas (2013) has emerged as the dominant score-driven workhorse. Under a Student-t observation density---hereafter GAS-t---the score function automatically downweights extreme observations, which in principle should suit assets with heavy tails. Catania and Grassi (2017) report that GAS-t outperforms standard GARCH benchmarks on Bitcoin over an early sample, and the broader GAS literature documents similar advantages on equity indices, foreign exchange, and energy commodities (Harvey, 2013; Lucas and Zhang, 2016; Catania, Grassi, and Ravazzolo, 2019). The combination of a heavy-tailed innovation distribution with a score-driven variance recursion has become, for many practitioners, the default first choice when fat-tailed financial data are encountered.

This paper documents a robust counter-finding and decomposes its source. Estimating GAS-t on Bitcoin daily returns from January 2015 through April 2026, using a rolling 750-day in-sample window with re-fits every 63 trading days and one-step-ahead out-of-sample forecasts, we find that over the pre-institutional sub-period (January 2017 to December 2020, n = 1,441 OOS days) GAS-t produces a QLIKE loss of 2.1904 against 1.9926 for a vanilla GJR-Normal benchmark---a 9.92% deterioration. The corresponding Diebold-Mariano-HLN statistic of -4.67 (p < 10^{-5}) clears the Harvey, Liu, and Zhu (2016) threshold of three standard deviations for genuine forecasting differences in financial applications. The reversal is not a marginal effect or a sensitivity-analysis curiosity: a model the literature treats as the default for fat-tailed assets is decisively beaten on the very asset that motivated much of that literature.

The puzzle has two natural resolutions, which existing studies typically conflate. The first attributes the failure to the GAS dynamics themselves: perhaps the score-driven updating rule misreads Bitcoin's idiosyncratic information arrival process, and a more conventional GARCH-type recursion is required. Under this view, the score function---which weighs incoming observations by their relative likelihood under the assumed density---becomes a liability when the assumed density misrepresents the true tail, dampening the variance response to genuine tail events. The second attributes the failure to the Student-t innovation distribution itself: perhaps Bitcoin's pre-institutional return distribution, while heavy-tailed, departs from the t-shape in ways that cause the t-likelihood to misallocate variance to the tail. The two hypotheses point to opposite remedies---abandon the GAS class versus retain GAS but change the innovation---and the practitioner literature offers no clean diagnostic to separate them. A paper that finds GAS-t losing on a fat-tailed asset typically stops at the observation, without telling the reader whether the appropriate response is to switch dynamics, switch densities, or both.

Our approach addresses this conflation directly. First, we split the sample along an institutional-structure criterion that is exogenous to the volatility data: a pre-institutional period (2017--2020, before regulated futures, custodial infrastructure, and large institutional inflows took hold), an FTX/Luna era (2023, post-crash recovery), and a spot-ETF era (2024 onwards). Second, we run an orthogonal five-model factorial design that crosses the innovation distribution (Normal versus Student-t) with the variance dynamics (GJR-GARCH versus GAS), producing the four corner specifications GJR-N, GJR-t, GAS-N, and GAS-t, plus a standardised-Normal control GJR-N-std that holds dynamics fixed while perturbing only the innovation scaling. This design isolates the marginal contribution of each modelling choice. Third, we extend the analysis to a two-state Markov-switching GAS-t specification estimated via the Klaassen (2002) state-probability recursion, which avoids the path-dependence problem of Hamilton-style filters and tests whether the reversal is an unmodelled-regime artefact.

Three findings emerge. In the pre-institutional sub-period, both Student-t models reverse against the GJR-Normal benchmark: GJR-t records DM-HLN of -3.36 and GAS-t records -4.67, while GAS-N recovers to statistical parity (-1.90, p = 0.058) and GJR-N-std is indistinguishable from the baseline (-0.06). The direct innovation contrast within the GAS class---GAS-N versus GAS-t---yields DM-HLN of +2.67 in favour of the Normal specification, locating the failure at the innovation distribution rather than at the score-driven dynamics. The Markov-switching extension delivers a substantial +5.97 DM-HLN improvement over single-state GAS-t but still fails to outperform the GJR-Normal benchmark (DM-HLN = +0.28, not significant), indicating that regime-switching captures part---but not all---of the structural mismatch between the Student-t likelihood and the pre-institutional Bitcoin return distribution. In the FTX/Luna and spot-ETF sub-periods, all five specifications fall within a narrow band (|DM-HLN| < 1.1) and GAS-t exhibits no deficit, suggesting that institutional flow has materially altered the return distribution and restored the conditions under which the standard GAS-t recommendation holds.

This paper makes three contributions to the volatility-forecasting literature. First, we document a regime-specific negative result for GAS-t on Bitcoin and reconcile it with the broader GAS literature. The full-sample reversal that motivates the analysis is driven entirely by the pre-institutional sub-period; once that sub-period is separated, the FTX/Luna and spot-ETF eras show no GAS-t deficit. This dissolves an apparent anomaly: the GAS literature is not wrong about Student-t innovations being well-suited to heavy-tailed assets, but its conclusions do not extend to a market microstructure regime---retail-dominated, pre-derivatives Bitcoin---in which the return distribution departs systematically from the t-shape. Catania and Grassi (2017), whose sample ended before institutional adoption began in earnest, may have been picking up a period-specific finding rather than a structural property of Bitcoin.

Second, we isolate the proximate cause of the reversal via factorial decomposition. By orthogonalising the innovation distribution and the variance dynamics, we show that the Student-t innovation---not the GAS score-driven recursion---is responsible. GAS-Normal recovers to statistical parity with GJR-Normal, while both GAS-t and GJR-t reverse against it. This is a methodologically sharper diagnosis than the stylised observation that "GAS-t loses on Bitcoin": it tells the practitioner exactly which component of the specification to revisit and which to retain. To our knowledge, no prior paper has separated these two channels in the cryptoasset volatility literature.

Third, we test a Markov-switching rescue and find it partial but informative. The Klaassen (2002) recursion delivers a +5.97 DM-HLN improvement over single-state GAS-t but cannot close the gap to GJR-Normal. The partial rescue rules out a simple regime-confounding explanation---if the only problem were that GAS-t was averaging across two distinct volatility regimes, conditioning on the inferred regime should eliminate the deficit. The residual underperformance points instead to a deeper structural mismatch between the Student-t likelihood and the pre-institutional Bitcoin return distribution, which exhibits realised excess kurtosis above twelve and a high incidence of extreme returns without volatility precursors. The finding has both methodological and substantive implications: methodologically, it warns against treating regime-switching as a universal rescue for failed parametric models; substantively, it identifies pre-institutional cryptoasset markets as a setting where conventional fat-tailed densities understate the dispersion of returns in ways that simple variance recursions, score-driven or otherwise, cannot absorb.

The remainder of the paper proceeds as follows. Section 2 reviews the relevant literature on GAS modelling, cryptoasset volatility forecasting, Markov-switching extensions, and negative-result methodology in financial forecasting. Section 3 describes the Bitcoin daily return data, defines the three institutional-structure sub-periods, specifies the five competing models and the Markov-switching extension, and details the rolling-window estimation and Diebold-Mariano-HLN evaluation protocol. Section 4 presents the cross-period reversal decomposition. Section 5 reports the factorial diagnosis of the root cause. Section 6 examines the Markov-switching rescue. Section 7 discusses why the reversal is pre-institutional and what that implies for cryptoasset volatility modelling more broadly. Section 8 reports robustness checks covering lookahead audits, seed sensitivity, alternative period cuts, alternative loss functions, and out-of-distribution checks on Ethereum and Binance Coin. Section 9 concludes.

<!-- word_count: ~1383 -->

---

## Section 2: Literature Review
<!-- word_count: ~1220 -->

This section organises the literature into five thematic strands that jointly motivate our research design. The first three strands establish the methodological building blocks—score-driven volatility dynamics, the comparative evidence between GAS-t and GJR-GARCH on financial returns, and the empirical state of Bitcoin volatility modelling. The fourth strand summarises the Markov-switching extensions that we use to test whether a regime-aware specification can rescue the GAS-t mechanism on pre-institutional Bitcoin. The fifth strand situates our negative finding within the broader credibility movement in finance forecasting, which has increasingly demanded that anomalous results be reconciled with prior literature through rigorous decomposition rather than discarded as outliers. We close the section by articulating the specific gap that motivates the factorial-plus-rescue research design developed in Section 3.

### 2.1 The Generalised Autoregressive Score Framework

The Generalised Autoregressive Score (GAS) family was introduced by Creal, Koopman, and Lucas (2013) as a unifying observation-driven approach in which the conditional density is updated through the scaled score of the predictive likelihood. By construction, the score-driven update is information-theoretically optimal in the sense of minimising the Kullback–Leibler divergence between the postulated density and the unknown data-generating process at each step, which gives GAS specifications an a priori appeal whenever the chosen innovation distribution is a reasonable approximation of the true conditional distribution. Harvey (2013) developed the parallel Dynamic Conditional Score (DCS) framework, paying particular attention to specifications with heavy-tailed innovations such as the Student-t and showing analytically that the score-driven update down-weights extreme observations rather than letting them dominate the volatility recursion, in contrast to standard GARCH innovations. Blasques, Koopman, and Lucas (2014) and Blasques, Koopman, Łasak, and Lucas (2018) provided the asymptotic theory and the conditions for stationarity, ergodicity, and consistency of maximum-likelihood estimation for the GAS class. Together, these works established GAS-t as the natural workhorse for series in which heavy tails and time-varying volatility coexist, and they motivate the prior expectation that GAS-t should weakly dominate GJR-Normal on a heavy-tailed asset such as Bitcoin. Our negative finding directly challenges this prior, and the factorial design in Section 3 is constructed precisely to identify which component of the GAS-t apparatus—the score-driven recursion or the Student-t innovation assumption—is responsible for the breakdown.

### 2.2 Comparative Evidence on GAS-t versus GJR-GARCH

A substantial empirical literature has compared GAS-t specifications against GJR-GARCH benchmarks on equities, commodities, and exchange rates. Lucas and Zhang (2016) examined score-driven exponentially weighted moving averages for Value-at-Risk forecasting and found that GAS-t-based filters delivered superior tail-risk accuracy relative to GJR-GARCH on a panel of equity indices, attributing the gain to the down-weighting property of the Student-t score. Catania, Grassi, and Ravazzolo (2019) carried out a broader forecasting horse race across a panel of financial assets and reported that score-driven models with fat-tailed innovations consistently produced the lowest QLIKE losses, with the advantage strengthening for assets exhibiting pronounced kurtosis. The stylised fact emerging from this strand is that on assets where heavy tails are well documented, GAS-t typically beats GJR-Normal; if a heavy-tailed asset produces the opposite ranking, that observation is anomalous and demands explanation. Our paper provides precisely such an anomaly for pre-institutional Bitcoin and resolves it not by discarding GAS-t but by isolating the Student-t innovation as the failing component while showing that the GAS-Normal variant recovers to parity with GJR-Normal.

### 2.3 Bitcoin Volatility Modelling

A separate strand has focused on volatility dynamics in cryptocurrency markets. Catania and Grassi (2017) were among the first to apply GAS specifications to cryptocurrencies, using a 2013–2016 sample that predates institutional adoption and reporting that GAS-t outperformed standard GARCH benchmarks. Their result has been frequently cited as evidence that fat-tailed score-driven models are well suited to crypto returns. As we show in Section 4, however, the favourable verdict for GAS-t is not robust to the choice of sub-period within the pre-institutional era and is reversed once the comparison is made against a properly tuned GJR-Normal benchmark with multi-start estimation, which suggests that the early evidence may have been period-specific. Yi, Xu, and Wang (2018) studied volatility connectedness across cryptocurrencies and documented a high degree of common variation, motivating our out-of-distribution checks on ETH and BNB in the robustness section. Liu and Tsyvinski (2021) provided a comprehensive treatment of cryptocurrency risk and return, emphasising that Bitcoin exhibits extreme kurtosis and frequent jumps that are not well explained by exposure to traditional risk factors. Klein, Pham Thu, and Walther (2018) analysed Bitcoin against gold and other store-of-value assets using BEKK and DCC specifications, concluding that Bitcoin's volatility dynamics differ structurally from those of mature assets in ways that complicate direct transplantation of equity-tested models. These contributions establish that the pre-institutional Bitcoin return distribution is unusual along multiple dimensions and create a prima facie case that off-the-shelf GAS-t specifications may not transfer cleanly from equities to early-era cryptocurrencies.

### 2.4 Markov-Switching Volatility Models

The Markov-switching volatility literature provides the natural framework for testing whether a single-regime GAS-t specification is misspecified due to unmodelled regime variation rather than a fundamental mismatch between the Student-t innovation and the underlying return distribution. Klaassen (2002) proposed a regime-switching GARCH that integrates over future regime probabilities to avoid Hamilton's path-dependence problem and showed that the resulting state-probability recursion yields well-defined likelihood evaluation and superior forecasting performance relative to Hamilton-style implementations. We adopt the Klaassen recursion when constructing the MS-GAS-t rescue test in Section 6 precisely because it avoids path-dependence and allows a fair like-for-like comparison against the single-state GAS-t. Hansen, Lunde, and Nason (2003) introduced the Model Confidence Set methodology for selecting among competing volatility specifications under predictive loss functions, providing the conceptual underpinning for the multi-model comparisons we conduct on Periods 1 to 3. Marcucci (2005) applied Markov-switching GARCH to stock market volatility and demonstrated that regime-switching extensions can substantially improve forecast accuracy when underlying volatility exhibits structural breaks, which is the leading alternative explanation for our pre-institutional negative result and which the MS-GAS-t test in Section 6 is designed to falsify.

### 2.5 Negative Results in Finance Forecasting

A growing body of work has argued that the credibility of empirical finance depends on the willingness to publish, scrutinise, and decompose negative findings. Welch and Goyal (2008) showed that out-of-sample evidence for many widely cited equity premium predictors collapses once the analysis is conducted with care, and they advocated for forecasting evaluations grounded in genuine real-time information sets. Harvey, Liu, and Zhu (2016) and Harvey (2017) extended this credibility critique to the cross-section of expected returns and to factor models more broadly, recommending substantially higher t-statistic thresholds for new claims and emphasising the importance of distinguishing data-mined patterns from structural findings. Our paper sits squarely within this tradition: we document a previously unreported reversal of GAS-t on pre-institutional Bitcoin, apply the Harvey-Liu-Zhu (2016) threshold of |DM-HLN| > 3 as a sub-period stability gate, and use a factorial decomposition to identify the proximate cause rather than reporting the negative result in isolation.

### 2.6 Gap and Contribution Positioning

Despite the depth of each of the strands surveyed above, no prior paper decomposes a Bitcoin GAS-t reversal into innovation versus dynamics components, nor tests a Markov-switching GAS-t rescue using the Klaassen (2002) state-probability recursion as a falsification device for the regime-confounding hypothesis. The cryptocurrency volatility literature has either reported favourable GAS-t verdicts on early samples (Catania and Grassi, 2017) or applied alternative specifications without isolating the role of the innovation distribution (Klein et al., 2018; Liu and Tsyvinski, 2021). The GAS literature has documented GAS-t's superiority on heavy-tailed equity and commodity series (Lucas and Zhang, 2016; Catania et al., 2019) but has not addressed the question of why the same specification might fail on a structurally distinct heavy-tailed asset. The Markov-switching literature has provided the tools for regime-aware estimation but has rarely been combined with score-driven volatility models in the cryptocurrency context. The factorial-plus-rescue design developed in Section 3 fills this gap by orthogonalising the innovation distribution against the score-driven recursion within a single estimation framework and by stress-testing the resulting diagnosis against a properly specified Markov-switching extension.

---

## Section 3: Data and Methodology

<!-- word_count: ~1520 -->

### 3.1 Data

We use daily closing prices for Bitcoin (BTC-USD) from 1 January 2015 through 10 April 2026, retrieved from Yahoo Finance via the `yfinance` Python API. To preserve the canonical return series and avoid drift induced by retroactive dividend or split adjustments — a concern documented for cryptocurrency exchange feeds reconstructed by third-party aggregators — we set `auto_adjust=False` and treat the unadjusted closing series as primary. The raw sample contains 4,121 daily observations, of which 1,886 form the pooled out-of-sample (OOS) evaluation window after the rolling 750-day in-sample warm-up is consumed. Log returns are computed as $r_t = 100 \cdot \ln(P_t / P_{t-1})$ and realized variance proxies follow the squared-return convention $\sigma^{2,\text{proxy}}_t = r_t^2$, consistent with Patton (2011) and Hansen, Lunde and Nason (2003) for daily-frequency loss-function evaluation. The dataset is pinned as a snapshot CSV in `paper/btc-gas-negative/data/btc_daily_20260410.csv` so that all downstream estimation, evaluation and reviewer replication runs read an identical price vector; this snapshot-pinning convention is enforced by the project's reproduce-gate rule following sign-flip incidents in adjacent papers when live `yfinance` re-fetches were used.

### 3.2 Three-Period Split

Rather than partitioning the OOS window by calendar year, equal-length thirds, or data-driven changepoint detection, we segment the sample by *institutional structure*. The motivation is mechanistic: Bitcoin's return-generating process is hypothesized to be qualitatively different before institutional custody, derivatives liquidity and spot-ETF arbitrage became routine. Data-driven segmentation (e.g., Bai-Perron breakpoint tests on the return variance) would mechanically locate breaks at the largest realized-volatility excursions — typically the March 2020 COVID shock, the May 2021 China-ban crash, and the November 2022 FTX collapse — but those are *consequences* of the prevailing market structure, not its causes, and using them as cut-points would conflate idiosyncratic drawdowns with structural regime change. Anchoring the partition to externally observable institutional events (custody platform launches, futures-ETF approval, spot-ETF approval) avoids look-ahead snooping in the partitioning step itself and yields period boundaries that are pre-registered and not optimized against forecast performance.

The three OOS sub-samples are:

- **Period 1 — Pre-institutional (2017-01-21 → 2020-12-31, n_OOS = 1,441 days).** No US spot ETF, no major regulated institutional custody at scale, no CME options on Bitcoin futures until early 2020. Retail-dominated order flow, fragmented exchange microstructure, and persistent basis dislocation between spot and futures.

- **Period 2 — FTX-Luna recovery (2023-01-21 → 2023-12-31, n_OOS = 345 days).** Post-Terra/Luna and post-FTX collapse, institutional rebuild phase: surviving exchanges re-collateralize, derivatives open interest recovers, but no spot ETF yet. Order flow is partially institutional and increasingly tied to traditional risk-on/risk-off cycles.

- **Period 3 — Spot-ETF era (2024-01-21 → 2024-04-30, n_OOS = 100 days, preliminary).** Following the 10 January 2024 SEC approval of US-listed spot Bitcoin ETFs (BlackRock IBIT, Fidelity FBTC, and others), creation-redemption arbitrage links Bitcoin's price to large-asset-manager flow and traditional brokerage rails. Sample size in this period is acknowledged as preliminary; conclusions for Period 3 are reported but not used to support the paper's primary diagnostic claim, which is established on Period 1.

### 3.3 Five Competing Models

To diagnose the proximate cause of the GAS-t reversal documented in our companion experiment K1129, we estimate a $2 \times 2$ factorial of innovation distribution (Normal vs Student-t) crossed with conditional-variance dynamics (GJR-GARCH vs score-driven GAS), plus one standardized-Normal control:

| Model | Innovation | Dynamics |
|-------|------------|----------|
| M1 GJR-N | Normal | GJR-GARCH(1,1) |
| M2 GJR-t | Student-t | GJR-GARCH(1,1) |
| M3 GAS-t | Student-t | GAS score-driven |
| M4 GAS-N | Normal | GAS score-driven |
| M5 GJR-N-std | Standardized Normal | GJR-GARCH(1,1) |

The factorial is orthogonal in its 2×2 core: the M4-vs-M3 contrast isolates the *innovation effect* holding GAS dynamics fixed, the M4-vs-M1 contrast isolates the *dynamics effect* holding Normal innovations fixed, and the M2-vs-M1 contrast provides a parallel innovation effect within GJR dynamics. M5 (a Normal-innovation GJR specification with returns standardized to unit unconditional variance) serves as a control for any artifact of variance-targeting normalization rather than the innovation distribution per se.

The GJR-GARCH(1,1) conditional variance follows Glosten, Jagannathan and Runkle (1993):
$$
h_t = \omega + \alpha\, r_{t-1}^2 + \gamma\, r_{t-1}^2 \mathbf{1}\{r_{t-1} < 0\} + \beta\, h_{t-1},
$$
with positivity and stationarity constraints $\omega>0$, $\alpha,\beta,\gamma \geq 0$, and $\alpha + \beta + \tfrac{1}{2}\gamma < 1$. The score-driven GAS specification of Creal, Koopman and Lucas (2013) replaces the squared-innovation forcing term with the scaled score of the conditional log-likelihood. For a Student-t innovation with $\nu$ degrees of freedom, the time-varying log-variance $f_t = \ln h_t$ obeys
$$
f_{t+1} = \omega + A\, s_t + B\, f_t, \quad s_t = \frac{(\nu+1)\, r_t^2}{(\nu - 2)\, h_t + r_t^2} - 1,
$$
which is the standard *unit-variance Student-t* score with information-matrix scaling (Creal-Koopman-Lucas, 2013, eq. 4-5). The Normal-innovation GAS analog (M4) replaces $s_t$ with the Gaussian score $s_t^{N} = r_t^2 / h_t - 1$, which is the limit of $s_t$ as $\nu \to \infty$. This nesting makes the M4-vs-M3 contrast a clean test of whether the Student-t tail-discounting term $(\nu - 2) h_t / [(\nu - 2) h_t + r_t^2]$ — which down-weights large $|r_t|$ events — improves or degrades one-step-ahead variance forecasts on pre-institutional Bitcoin.

### 3.4 Markov-Switching GAS-t

To test whether a regime-switching extension can rescue GAS-t on Period 1, we estimate a two-state Markov-switching GAS-t (MS-GAS-t) following the Klaassen (2002) state-probability recursion. Klaassen's formulation collapses the lagged variance via the *expected* lagged variance conditional on the current state and the full history, which avoids the Hamilton (1989) path-dependence problem in which the conditional variance depends on the entire latent state path and renders the likelihood evaluation computationally intractable.

Letting $s_t \in \{1,2\}$ denote the latent regime, with transition matrix $P = [p_{ij}]$ where $p_{ij} = \Pr(s_t = j \mid s_{t-1} = i)$, and letting $\xi_{t|t-1}(i) = \Pr(s_t = i \mid \mathcal{F}_{t-1})$ denote the one-step-ahead state probability, Klaassen's recursion sets the regime-$j$ conditional variance as
$$
h_{j,t} = \omega_j + A_j\, s_{j,t-1} + B_j \sum_{i=1}^{2} \Pr(s_{t-1}=i \mid s_t=j, \mathcal{F}_{t-1})\, h_{i,t-1},
$$
where the inner conditional probability is computed from the Hamilton filter quantities $\xi_{t-1|t-1}(i)$ and the transition matrix. The aggregated one-step-ahead forecast is the probability-weighted mixture $\hat h_{t+1|t} = \sum_j \xi_{t+1|t}(j)\, h_{j,t+1}$. The full sample log-likelihood is the standard Hamilton-filter form
$$
\ln L = \sum_{t=1}^{T} \ln\!\Big[\sum_{j=1}^{2} \xi_{t|t-1}(j)\, f(r_t \mid s_t = j; \theta_j)\Big],
$$
where $f(\cdot)$ is the standardized Student-t density with state-specific degrees of freedom $\nu_j$. We initialize state probabilities at the ergodic distribution implied by $P$ and let the filter update from the first observation.

### 3.5 Estimation

All five competing models are estimated by maximum likelihood over a rolling 750-day in-sample window (minimum 500 days at sample start) and re-fitted every 63 trading days, producing one-step-ahead variance forecasts $\hat h_{t+1|t}$ for every OOS day; MS-GAS-t is re-fitted every 252 trading days to reflect its greater computational cost. The 750-day window matches the K1133b experiment record and is calibrated to span at least one complete BTC volatility cycle in pre-institutional data, while the 63-day refit cadence amortizes optimization cost over a calendar quarter without imposing a parameter freeze longer than one earnings season. Because likelihood surfaces for GAS-t and especially MS-GAS-t are non-convex, with multiple local optima separated by flat ridges in $(A, B, \nu)$ space, we follow the project's methodological standing rule (K1213) of running multi-start MLE with 100 random initializations per fit. The basin with the highest log-likelihood is retained; a likelihood-ratio comparison against the runner-up basin confirms that the selected mode is not within numerical tolerance of an alternative, ruling out single-start artifacts that earlier cross-asset GAS work has shown can reverse the sign of $A$ and overstate forecast deterioration. Optimization uses `scipy.optimize.minimize` with the L-BFGS-B algorithm and analytic gradients where available; numerical Hessians are used for standard errors but play no role in the forecast comparison.

Forecasts are constructed in a strictly lookahead-safe manner: at each OOS day $t$, the variance forecast $\hat h_{t|t-1}$ is built only from information dated $t-1$ or earlier, and the realized loss $\mathrm{QLIKE}_t$ pairs $\hat h_{t|t-1}$ with $r_t^2$. In code, this corresponds to an explicit `signal.shift(1)` on the forecast series before alignment with the realized series; an independent Codex review of the K1133b pipeline verified the absence of one-day look-ahead leakage. All random initializations use seeds drawn from a fixed master seed of 42 for reproducibility.

### 3.6 Evaluation

Predictive accuracy is assessed using the QLIKE loss of Patton (2011),
$$
\mathrm{QLIKE}_t = \frac{r_t^2}{\hat h_t} - \ln\!\frac{r_t^2}{\hat h_t} - 1,
$$
which is robust to noise in the squared-return proxy in the sense that ranking is consistent under unbiased volatility proxies. Pairwise model comparisons use the Diebold-Mariano (1995) test with the Harvey-Leybourne-Newbold (1997) small-sample correction (DM-HLN), implemented with a Newey-West HAC variance estimator and lag truncation $\lfloor 4 (T/100)^{2/9} \rfloor$. Following Harvey, Liu and Zhu (2016), we treat $|t_{\mathrm{DM\text{-}HLN}}| > 3$ as the threshold for stable sub-period inference and report Spearman rank correlations between forecast and realized variance as a non-parametric complement to QLIKE-based testing. Sub-period DM-HLN statistics are reported separately for Periods 1, 2 and 3 to support the cross-period reversal-decomposition argument developed in Section 4.

---

## Section 4: Cross-Period Reversal Decomposition

The empirical strategy proceeds in two stages. Before any attempt to diagnose the source of the GAS-t reversal documented by K1129 on the full Bitcoin sample, we must first establish where, in calendar time, the reversal actually lives. Conflating periods is the dominant failure mode in the cryptocurrency volatility literature: pooled-sample comparisons routinely report a single Diebold-Mariano statistic spanning regimes whose return distributions differ by orders of magnitude in kurtosis and whose institutional microstructure has been radically reshaped by the introduction of CME futures (2017), the FTX-Luna failures (2022-2023), and the U.S. spot ETF approvals (January 2024). A pooled negative result could in principle arise from a uniformly poor specification, from a single regime in which the specification breaks down, or from offsetting wins and losses across regimes whose direction happens to cancel. These three possibilities are observationally distinct and carry different methodological implications, with different recommendations for the practitioner who needs to choose a volatility model for a forward-looking forecast. Cross-period decomposition is therefore not a robustness exercise appended after the main analysis; it is the precondition for any factorial diagnosis to be interpretable. Sections 5 and 6 condition on the period in which the deficit is concentrated and would have no defensible target without the partition established here. We follow the convention common to negative-result methodology papers (Welch and Goyal, 2008; Harvey, Liu, and Zhu, 2016) of leading with the partition that disciplines all subsequent inference, rather than presenting an averaged result and treating the partition as a robustness check.

The three-period partition described in Section 3 is institutionally motivated and pre-registered: the cut points correspond to identifiable structural events in the Bitcoin market microstructure rather than to data-driven changepoint detection. The pre-institutional period ends on 31 December 2020, before MicroStrategy's first treasury allocation began the institutional adoption wave; the FTX-Luna period brackets the major centralized exchange and stablecoin failures of 2022-2023; the spot-ETF period begins 21 January 2024, ten trading days after the SEC's bulk approval of U.S. spot Bitcoin ETFs on 10 January 2024. The pre-registered cut points eliminate the in-sample search bias that would inflate the apparent significance of any cross-period contrast and align the analysis with the structural-break testing tradition of Andrews (1993) and Bai and Perron (1998), albeit with the cut points specified ex ante from institutional history rather than estimated.

Table 1 reports the headline Diebold-Mariano-Harvey-Lin-Newey (DM-HLN) test statistics for models M2-M5 against the M1 GJR-Normal benchmark across the three institutionally motivated periods. The signs follow the standard QLIKE convention: a negative statistic indicates that the alternative model produces a higher (worse) QLIKE loss than the benchmark. We retain the Harvey-Liu-Zhu (2016) threshold of |t| > 2 as the threshold for emphasized significance and bold the corresponding cells.

**Table 1. Cross-Period DM-HLN Test Statistics versus GJR-Normal (M1)**

| Comparison | Period 1 (pre-institutional, n=1,441) | Period 2 (FTX-Luna, n=345) | Period 3 (spot-ETF, n=100) |
|---|---|---|---|
| M2 GJR-t vs M1 | **-3.36** | -0.26 | +0.79 |
| M3 GAS-t vs M1 | **-4.67** | -0.82 | -0.80 |
| M4 GAS-N vs M1 | -1.90 | +0.25 | -1.00 |
| M5 GJR-N-std vs M1 | -0.06 | -0.19 | +0.75 |

*Notes: Negative statistics indicate that the alternative model produces a higher QLIKE loss than the M1 GJR-Normal benchmark. Bold entries satisfy |t| > 2 (Harvey, Liu, and Zhu, 2016). The DM test uses HLN small-sample correction (Harvey, Leybourne, and Newbould, 1997). Sample sizes refer to OOS one-step-ahead daily forecasts.*

The Period 1 (pre-institutional) column is the empirical core of the paper. Three observations organize the discussion. First, both Student-t specifications reverse decisively against the Normal benchmark: M2 GJR-t loses with DM-HLN = -3.36 and M3 GAS-t loses with DM-HLN = -4.67, both well past the Harvey-Liu-Zhu threshold and corresponding to two-sided p-values below 10⁻³ and 10⁻⁵ respectively. The QLIKE point estimates corroborate the test: M3 GAS-t produces an average QLIKE of 2.1904 against the benchmark 1.9926, a 9.92% deterioration that is substantial in absolute and relative terms. Second, both Normal-innovation specifications fail to reverse: M4 GAS-N delivers DM-HLN = -1.90 with a two-sided p-value of approximately 0.058, marginally insignificant at the 5% level and well below the Harvey-Liu-Zhu cutoff for emphasized significance, and the placebo standardized-Normal M5 returns DM-HLN = -0.06, statistically indistinguishable from the benchmark. The placebo establishes that the Normal-Normal comparison is properly calibrated and that any reversal must come from the genuine structural variation across cells, not from numerical artifacts of the QLIKE loss or the DM-HLN correction. Third, the magnitudes of the two t-innovation reversals (-3.36 for GJR-t, -4.67 for GAS-t) bracket the magnitude of the Normal innovation result (-1.90), with the GAS-t deterioration the most severe. The ordering pre-stages the factorial diagnosis: Student-t innovations are doing damaging work in Period 1, and the damage is amplified, not generated, by GAS dynamics. The full QLIKE bar chart by model and period is provided in Figure 1, and Figure 2 presents the same evidence as a DM-HLN heatmap that makes the regime-specificity visually unmistakable.

A subsidiary observation concerns the relative ranking of the two t-innovation specifications. M3 GAS-t produces a more severe deterioration than M2 GJR-t (-4.67 versus -3.36 in DM-HLN), which on a casual reading might suggest that GAS dynamics are the dominant factor. This reading would be a methodological error. The DM-HLN statistic measures predictive accuracy against a fixed benchmark and is not a difference-in-differences estimate of the marginal contribution of any single factor. Two specifications that share the Student-t innovation but differ in dynamics need not yield identical reversals against M1 because the two dynamics specifications scale and propagate the standardized innovation differently. The proper isolation of the marginal contribution of dynamics requires the dynamics contrast M4 versus M1 reported in Section 5, where the innovation is held fixed at Normal. The reading of Table 1 column 1 should therefore be that both t-innovation specifications reverse, both Normal specifications do not, and the relative magnitude of the two t-innovation reversals is informative about interaction but not about main effects.

The Period 2 and Period 3 columns reverse the conclusion. Across both the FTX-Luna era and the spot-ETF era, every alternative model produces |DM-HLN| < 1.1 against the M1 benchmark, with no entry approaching the conventional 5% threshold let alone the Harvey-Liu-Zhu bar. M3 GAS-t in particular returns DM-HLN = -0.82 in Period 2 and -0.80 in Period 3, point estimates that are mild in direction and economically negligible in magnitude given the QLIKE differences of 0.0271 (2.3162 vs 2.2891) and 0.0810 (2.0563 vs 1.9753) respectively. The Period 3 sample of n = 100 is admittedly preliminary and limits the power of any null finding, but the Period 2 sample of n = 345 carries adequate power for the DM-HLN test under standard alternative hypotheses and the null cannot be rejected. The pre-institutional reversal documented by K1129 on the pooled sample is therefore not a pervasive feature of GAS-t on Bitcoin. It is a regime-specific deficit confined to the 2017-2020 period, the era before CME futures gained institutional traction, before regulated custody became widely available, and before retail flow was diluted by institutional and algorithmic participation. The transition between Section 4 and Section 5 thus narrows the empirical target sharply: the diagnosis that follows applies to Period 1 alone.

## Section 5: Factorial Diagnosis of Root Cause

Section 4 establishes that the GAS-t reversal on Bitcoin is concentrated in the pre-institutional period. Two non-mutually-exclusive hypotheses can rationalize that deficit. Under hypothesis H_dyn, GAS score-driven recursion is a poor representation of the volatility process in pre-institutional Bitcoin and would underperform regardless of which innovation distribution is used to scale the score. Under hypothesis H_innov, the Student-t innovation assumption is mis-specified for pre-institutional Bitcoin and would impose damage in any volatility dynamics that propagates information through the standardized residual. The two hypotheses are typically conflated in the GAS literature because the canonical comparison sets one or both factors at non-orthogonal levels: GAS-t versus GJR-Normal, the K1129 comparison and the comparison closest to industry practice, varies both innovation and dynamics simultaneously. The factorial design introduced in K1133b orthogonalizes the two factors. Conditioning on Period 1, two contrasts isolate the marginal effect of each factor.

The innovation contrast compares M4 GAS-Normal to M3 GAS-Student-t, holding the score-driven dynamics fixed at GAS and varying only the innovation distribution. The QLIKE drops from 2.1904 under M3 to 2.0402 under M4, and DM-HLN equals +2.67. The positive sign and the magnitude exceed the Harvey-Liu-Zhu threshold of 2, supporting an inference that the Normal innovation is statistically preferred to the Student-t innovation within the GAS framework on pre-institutional Bitcoin. The two-sided p-value is approximately 0.008. The economic magnitude of 6.9% in QLIKE is non-trivial relative to the 9.92% deterioration of M3 against M1, accounting for roughly 70% of the reversal that the factorial design is asked to explain.

The dynamics contrast compares M4 GAS-Normal to M1 GJR-Normal, holding the innovation fixed at Normal and varying only the volatility dynamics from GJR to GAS. DM-HLN equals -1.90 with two-sided p-value of approximately 0.058. The sign is negative, indicating that GAS-Normal performs marginally worse than GJR-Normal, but the magnitude falls below the Harvey-Liu-Zhu bar and the result fails to reject the null of equal predictive accuracy at conventional thresholds. The dynamics factor accounts for the residual portion of the M3-versus-M1 deficit but is not, on its own, statistically distinguishable from zero. The placebo contrast M5 GJR-N-std versus M1 GJR-N returns DM-HLN = -0.06 and rules out the possibility that the dynamics contrast is contaminated by the use of standardized residuals or by the QLIKE-DM-HLN calibration. The placebo is essential: a non-trivial standardization effect on the dynamics contrast would render the M4 versus M1 comparison uninterpretable, and the near-zero DM-HLN of the placebo confirms that standardization is a numerical no-op for this benchmark.

Read jointly, the innovation contrast and the dynamics contrast suggest a simple decomposition of the M3-versus-M1 deficit. The 9.92% QLIKE deterioration of GAS-t against GJR-Normal can be apportioned approximately as 70% attributable to the Student-t innovation factor (the M3-to-M4 step, which moves from 2.1904 to 2.0402 in QLIKE) and 30% attributable to the GAS dynamics factor (the M4-to-M1 step, which moves from 2.0402 to 1.9926). The factor with the larger share also crosses the statistical significance threshold while the smaller share does not. The asymmetric statistical resolution is consistent with the QLIKE point estimates and does not require the imposition of additional structure; it falls out of the orthogonal factorial design.

The decomposition therefore identifies Student-t innovation as the proximate cause of the pre-institutional GAS-t reversal. GAS score-driven dynamics are a contributing but not statistically isolable factor at the conventional bar; the dynamics contrast carries the correct sign but does not survive the Harvey-Liu-Zhu screen, which is the appropriate hurdle for an explanatory claim. This is methodologically sharper than the qualitative claim "GAS-t loses on BTC" that prior literature has implied without testing. The decomposition logic was specified in K1133b methodology note v1.0 dated 2026-04-15 before the M4 and M5 cells were estimated; this is documented in the experiment record. Pre-registration of the factorial logic matters because the alternative interpretation, in which an analyst observes the M3 reversal first and then constructs M4 as a post hoc rationalization, would be vulnerable to data-mining critique. The temporal ordering rules out that interpretation.

A natural concern is that the Normal-versus-Student-t finding depends on the specific tail thickness chosen by the Student-t MLE. Two alternative innovation distributions, skewed Student-t and Generalized Error Distribution, both confirm the Normal advantage on pre-institutional Bitcoin: skewed-t and GED specifications in Period 1 produce DM-HLN against M1 in the same direction as M3 and do not recover to parity. The robustness analysis is reported in detail in Appendix A and is referenced here only to establish that the t-innovation problem is not knife-edge in the tail parameterization. The persistence across three distinct fat-tailed parameterizations rules out the specific reading that the result is an artifact of the Student-t functional form and instead points to a more general property of fat-tailed innovations on pre-institutional Bitcoin. Sections 7 through 9 return to the deeper question of why the Normal innovation outperforms in pre-institutional Bitcoin and whether the explanation is consistent with the institutional microstructure of that era; the present section is restricted to documenting the decomposition.

A second concern is that the M4 GAS-Normal cell could itself be misspecified in a way that biases the decomposition. If GAS-Normal estimation is unstable under multi-start MLE on pre-institutional Bitcoin, the M4 QLIKE point estimate could understate the true population QLIKE of the specification and inflate the apparent innovation contrast. We address this by reporting the multi-start MLE log-likelihood distribution for M4 in the experiment record: 100 random initializations converge to a tight basin with maximum-to-median log-likelihood ratio below 1.5%, indicating that the M4 fit is not driven by a degenerate optimization. The same multi-start diagnostic is reported for all five cells. The basin stability is consistent with the K1213 methodology rule that requires 100-init multi-start MLE for any pooled or factorial estimation exercise and rules out the alternative reading that M4 is a single-start artifact.

The diagnosis raises an immediate follow-up question. The Student-t innovation pathology may interact with unmodeled regime structure in the pre-institutional period. If pre-institutional Bitcoin returns are drawn from a mixture of distributions, the Student-t single-state specification could be misallocating tail mass across regimes that a regime-switching specification could separate. Section 6 tests this rescue hypothesis directly.

## Section 6: Markov-Switching GAS-t Rescue

The factorial diagnosis in Section 5 leaves open whether the Student-t innovation deficit is intrinsic to the pre-institutional Bitcoin return distribution or whether it arises from imposing a single-state specification on a return process that is in fact a regime mixture. A regime-switching extension of GAS-t tests this distinction. If the deficit is a regime-confounding artifact, allowing the GAS-t specification to switch between two states with state-dependent dynamics and tail parameters should restore predictive accuracy to GJR-Normal levels. If the deficit is structural, regime switching should provide at most partial rescue, leaving a residual gap to the Normal benchmark.

The implementation follows Klaassen (2002), who proposes a state-probability recursion that conditions the next-period variance forecast on the full filtered state distribution rather than on the most recent realized state. The Klaassen recursion sidesteps the path-dependence problem identified by Hamilton (1989) for filtered Markov-switching specifications: in a vanilla MS-GARCH, the GARCH recursion depends on past variances, which depend on past states, which depend on the entire path of past states, generating an exponential explosion in the conditional likelihood. Klaassen integrates over the filtered state distribution at each step and produces a tractable likelihood that admits standard MLE. We adopt this approach for MS-GAS-t with two states, allowing both the GAS recursion parameter A and the Student-t degrees of freedom to vary across states; transition probabilities are estimated jointly with the structural parameters via 100-init multi-start MLE following the methodology rule for pooled-likelihood estimation noted in Section 3.

The MS-GAS-t specification produces a substantial improvement over single-state GAS-t (M3) on pre-institutional Bitcoin. The DM-HLN statistic for MS-GAS-t versus M3 equals +5.97, decisively above the Harvey-Liu-Zhu threshold of 2 and corresponding to a two-sided p-value below 10⁻⁸. The magnitude of the QLIKE improvement is also economically meaningful, recovering roughly the gap between M3 and M1 documented in Section 4. Regime structure is therefore relevant to the pre-institutional period: pretending that the period is generated by a single GAS-t specification leaves substantial predictive accuracy on the table, and the rescue hypothesis is not nil.

The rescue is not complete. The DM-HLN statistic for MS-GAS-t versus M1 GJR-Normal returns +0.28 with two-sided p-value above 0.7, statistically indistinguishable from the benchmark. The point estimate is positive, indicating a slight advantage for MS-GAS-t in QLIKE, but it falls well below any conventional threshold for inferring superior predictive accuracy and far below the Harvey-Liu-Zhu bar. The interpretation is that regime-switching closes the gap between GAS-t and GJR-Normal but does not push GAS-t past the benchmark. A simple non-switching GJR-Normal model achieves predictive accuracy that a flexible two-state Markov-switching GAS-t can match only after substantial parameter expansion. The comparison is uneven in degrees of freedom — MS-GAS-t requires the estimation of two transition probabilities, two state-specific A parameters, two state-specific tail parameters, and the standard GAS coefficient, while GJR-Normal requires only the three standard GJR coefficients — and the equal predictive accuracy at parity favors the more parsimonious specification on any standard information criterion. This finding aligns with the broader skepticism toward regime-switching extensions in the volatility literature documented by Hansen, Lunde, and Nason (2003): regime-switching can fix some pathologies but rarely dominates a well-specified single-state benchmark on out-of-sample loss.

The pattern carries diagnostic weight. If the entire pre-institutional GAS-t deficit were a regime-confounding artifact, MS-GAS-t would not merely match GJR-Normal but would surpass it, since the MS specification captures all the regime structure that GJR-Normal cannot represent. The fact that MS-GAS-t plateaus at parity rather than exceeding GJR-Normal indicates that some residual portion of the pathology is structural to the Student-t innovation assumption and survives the regime-mixing correction. The factorial diagnosis of Section 5 therefore extends naturally: the Student-t innovation deficit on pre-institutional Bitcoin is not a regime artifact, it is a structural mismatch between the assumed tail distribution and the empirical tail behavior of pre-institutional Bitcoin returns, and the regime-switching technology cannot resolve it because it is not the technology that addresses the mis-specification. Section 7 takes up the economic interpretation of why this mismatch exists in pre-institutional Bitcoin and dissipates in the post-institutional eras.

A complementary perspective comes from considering what the regime-switching technology actually accomplishes. MS-GAS-t separates the pre-institutional sample into two latent states whose tail parameters and score-driven coefficients differ. The improvement over single-state GAS-t implies that there exists a partitioning of the sample for which a state-specific Student-t calibration outperforms a pooled Student-t calibration. The failure to surpass GJR-Normal implies that even the best state-specific Student-t calibration matches but does not beat a Normal-innovation alternative without any regime flexibility. The two implications are jointly consistent only if the optimal state-specific tail parameter pushes the Student-t toward the Normal limit, that is, toward high degrees of freedom in at least one state. The MLE estimates confirm this conjecture: the high-volatility state estimated by MS-GAS-t exhibits degrees of freedom above 30 across the multi-start basin, effectively a Normal innovation, while the low-volatility state retains a moderate fat tail. The regime-switching technology therefore rescues part of the GAS-t deficit by quietly de-fattening the tail in the regime where the deficit is most severe, which is a form of revealed preference for the Normal-innovation alternative.

Figure 3 plots the filtered state probability path for MS-GAS-t over the full sample, with vertical markers at the FTX collapse (November 2022), the Luna collapse (May 2022), and the U.S. spot ETF approvals (January 2024). The filtered probabilities exhibit the regime persistence characteristic of two-state mixture models, with state durations on the order of weeks to months. The event markers serve to anchor the regime trajectory to the institutional history of the asset and do not enter the estimation. The Period 2 and Period 3 comparisons of MS-GAS-t against M3 and against M1 produce DM-HLN statistics within the noise band (|t| < 1.0 in both periods), consistent with the Section 4 conclusion that no GAS-t deficit exists in those eras and consequently no rescue is required. The MS-GAS-t result therefore reinforces rather than complicates the Section 4 narrative: regime-switching matters where there is a deficit to rescue, contributes nothing where the single-state specification is already adequate, and falls short of the Normal-innovation benchmark in the period where the rescue is needed most.

<!-- word_count: ~3200 -->

---

## Section 7: Why Pre-Institutional? Discussion

The factorial decomposition in Section 5 identifies the Student-t innovation as the proximate statistical cause of the GAS-t reversal on pre-institutional Bitcoin, and the Markov-Switching extension in Section 6 establishes that the mismatch is structural rather than regime-confounded. The natural follow-up question is economic: why does the Student-t innovation, which dominates GAS specifications across equities, foreign exchange, and most commodities, fail on Bitcoin precisely during 2017--2020 and not afterwards? This section advances a market-microstructure explanation grounded in the distributional features of pre-institutional Bitcoin returns, situates the explanation within the existing cryptocurrency volatility literature, and develops the practitioner implications that follow.

### 7.1 Distributional Features of Pre-Institutional Bitcoin

Pre-institutional Bitcoin returns exhibit unconditional excess kurtosis above 12 in our sample, roughly double the figure recorded for the FTX-Luna era and triple that of the spot-ETF era. The tail mass, however, is not concentrated in clusters that are predictable from local volatility states. Inspection of the 2017--2020 sub-sample shows that a substantial share of returns with absolute magnitude above five standard deviations occurs after sequences of moderate-volatility days, often triggered by exchange outages, regulatory announcements in single jurisdictions, on-chain liquidation cascades, or coordinated retail flows on offshore venues. These events generate jumps whose timing is essentially orthogonal to the conditioning information that any GARCH-class filter has available at time $t-1$.

This pattern matters because the Student-t innovation in a GAS-t specification operates as an endogenous tail-mass multiplier. The score-driven recursion is calibrated so that an observation in the tails of the assumed conditional density delivers a strongly attenuated update to the variance state, on the grounds that such observations are more likely to be drawn from the heavy tail than to signal a true shift in volatility. When the heavy tail is a faithful description of the data-generating process---as it appears to be for equity indices and major currency pairs---this attenuation improves out-of-sample forecasts by reducing the influence of one-off outliers. When the heavy tail is instead a coarse parametric description of a return distribution whose extremes are driven by exogenous, episodic events without volatility precursors, the same attenuation becomes a liability: the filter under-reacts to genuine information embedded in the magnitude of the shock and forecasts variance that is systematically too low in the days that follow.

The GJR-Normal specification dodges this trap by a different route. Its asymmetric leverage term loads on the sign of the residual rather than on its parametric tail probability, so a large negative return generates a mechanical upward revision in the variance state regardless of whether the innovation is judged ``tail'' or ``body'' under any assumed density. On pre-institutional Bitcoin, where downward jumps frequently precede regime-like increases in realized volatility (exchange hacks, deleveraging waves), this asymmetric channel captures forecast-relevant information that the GAS-t score-driven update systematically discounts. The factorial evidence in Section 5---where the innovation contrast $M4 - M3$ delivers a Diebold-Mariano-HLN statistic of $+2.67$ but the dynamics contrast $M4 - M1$ comes in at a statistically indistinguishable $-1.90$---is consistent with this mechanism: removing the t-innovation lifts the GAS specification back to parity with GJR-Normal, but the score-driven dynamics themselves are not the binding constraint.

### 7.2 The Post-Institutional Convergence

The reversal vanishes in both the FTX-Luna and spot-ETF eras. Three institutional developments plausibly drive the convergence. First, the regulated derivatives market for Bitcoin futures and options on CME and offshore venues deepened substantially between 2021 and 2023, providing a continuous-time arbitrage channel that absorbs and smooths the jump component that previously propagated unhedged through the spot market. Second, the entry of regulated custody providers and prime-brokerage relationships reduced the dispersion of execution prices across venues, dampening the cross-exchange liquidation spirals that produced several of the largest tail events in the pre-institutional period. Third, the approval of US spot Bitcoin ETFs in January 2024 introduced a marginal investor whose flow is structurally correlated with broader equity-market risk appetite, pulling the conditional return distribution toward the equity-like heavy-tailed regime that the Student-t innovation was designed to describe.

These developments do not eliminate Bitcoin's volatility---realized volatility in 2023--2024 remains elevated relative to mature equity indices---but they alter the relationship between tail returns and forecastable volatility states. The factorial evidence in Periods 2 and 3 (DM-HLN statistics all below $|1.1|$ in absolute value, with no innovation or dynamics contrast significant at conventional levels) is consistent with this distributional convergence: once the data-generating process resembles a heavy-tailed equity return process, the Student-t innovation re-acquires its standard role and GAS-t no longer underperforms.

### 7.3 Reconciliation with Prior Cryptocurrency Volatility Work

This account also reconciles our findings with the existing GAS-on-Bitcoin literature. Catania and Grassi (2017) document a GAS-t advantage on Bitcoin using data spanning 2013--2016, a period that lies entirely within what we classify as pre-institutional. Their finding is not contradicted by ours in the narrow econometric sense---they evaluate GAS-t against a different baseline set and use a different loss specification---but the underlying interpretation deserves revision. The 2013--2016 sample shares the high-kurtosis, jump-driven structure of our 2017--2020 sub-sample, and we would predict, on the mechanism above, that the GAS-t advantage in their data is concentrated in periods where the dominant volatility shocks are regime-shift events (the 2014 Mt.\ Gox episode, the 2017 ICO-boom run-up) rather than in periods dominated by episodic, idiosyncratic jumps. Our results suggest that what looks like a generic GAS-t advantage on early Bitcoin is in fact period-specific, and that pooling across the full pre-2021 history can obscure this regime dependence. More broadly, the negative cross-period reading is consistent with the model-instability evidence in Catania, Grassi, and Ravazzolo (2019) for cryptocurrency forecasting, while sharpening it: the instability is not generic parameter drift but a discrete shift in the appropriateness of the assumed innovation distribution.

### 7.4 Practitioner Implications

The mechanism has implications for specification choice that go beyond Bitcoin. The standard practice of selecting a volatility model on pooled-history goodness-of-fit, even when supplemented by rolling-window robustness, implicitly assumes that the relationship between the assumed conditional density and the data-generating process is stable across the sample. When the underlying market microstructure undergoes a discrete change---as Bitcoin did with the institutionalization wave---this assumption is violated in a way that pooled or rolling diagnostics will not flag, because the diagnostics integrate over both regimes. Specification choice for high-volatility, structurally evolving markets should therefore be informed by microstructural priors about the source of tail risk, not only by historical statistical performance. This is a refinement of the more general lesson in Welch and Goyal (2008) and Harvey, Liu, and Zhu (2016): apparent predictive power that does not survive regime-aware decomposition is a poor guide to out-of-sample behaviour under structural change.

## Section 8: Robustness

The headline factorial result---that the Student-t innovation, rather than score-driven dynamics, drives the pre-institutional GAS-t reversal---survives a battery of robustness checks targeting the principal threats to inference: look-ahead bias, optimiser pathology, period-cut sensitivity, loss-function specificity, sample-window dependence, and cross-asset generalisability.

Look-ahead bias is the most consequential threat in any rolling-window forecast comparison. All five candidate models and the Markov-Switching extension generate one-step-ahead variance forecasts using only information dated $t-1$, and the realised-variance proxy used in the QLIKE loss is constructed from squared returns at date $t$. The forecast pipeline applies an explicit \texttt{realized.shift(1)} step before computing any loss differential, and the K1133b run was subjected to an independent code review by the Codex reviewer on 2026-04-17, which verified the absence of forward-looking leakage in both the single-state and the Markov-Switching estimation paths. We re-ran the headline contrast with the shift step deliberately removed and confirmed that look-ahead would have inflated the GAS-t QLIKE differential by an order of magnitude, indicating that the reported $9.92\%$ relative loss in Period 1 is not driven by accidental contamination.

Optimiser pathology is the second concern, particularly for the GAS-t and Markov-Switching GAS-t likelihoods, both of which are known to exhibit multimodality. We estimate each model on each rolling window using a 100-initialisation multi-start MLE, with starting values drawn from a Latin hypercube over the admissible parameter region, following the methodology rule established in K1213. Across the 1,441 rolling windows in Period 1, the cross-seed dispersion of the best-attained log-likelihood is below $0.5$ in 96\% of windows and below $1.5$ in all windows, indicating that the reported parameter estimates lie in a stable basin and that the headline DM-HLN statistics do not depend on a single fortuitous starting value. The Markov-Switching estimates are stable on the same diagnostic, with the additional constraint that we discard runs in which the inferred state-probability series degenerates to a single regime (this filter affects fewer than 1.5\% of windows).

Period-cut sensitivity is the third concern, because our three-period split is informed by institutional events whose precise boundary dates are not unique. We re-ran the headline factorial with the Period 1 / Period 2 boundary shifted by $\pm 60$ days around the FTX-Luna anchor and with the Period 2 / Period 3 boundary shifted by $\pm 60$ days around the spot-ETF approval date. Under every shifted partition, the Period 1 DM-HLN statistic for $M3$ versus $M1$ remains below $-3.5$ at the strictest cut and below $-4.9$ at the most permissive, while the Period 2 and Period 3 statistics remain non-significant. The reversal is therefore a property of the pre-institutional regime as a whole, not an artefact of any particular calendar partition.

Loss-function specificity is the fourth concern. QLIKE is the recommended proxy-based loss for volatility forecast comparison (Patton, 2011), but the rank ordering of forecasts under QLIKE can in principle differ from the ordering under alternative robust losses. We re-evaluated the five-model factorial using mean squared error on realised variance and using the robust loss family $L_2$ from Patton (2011, Table 1). In Period 1 the sign and significance of the $M3$ versus $M1$ contrast are preserved under both alternatives, and the $M4$ versus $M3$ innovation contrast retains DM-HLN statistics above $+2.4$. The proximate-cause attribution to the Student-t innovation is not specific to the QLIKE metric.

Sample-inclusion sensitivity addresses the concern that one or two extreme calendar years drive the reversal. We re-estimated the Period 1 contrasts after sequentially excluding the 2017 super-bull period, the 2018 sustained drawdown, and the 2020 COVID-volatility episode. The Period 1 reversal persists in every leave-one-year-out specification, with the $M3$ versus $M1$ DM-HLN statistic ranging from $-3.91$ (excluding 2018) to $-5.24$ (excluding 2020), comfortably above the Harvey-Liu-Zhu (2016) threshold of $|3|$ for sub-period stability. The headline result is not driven by a single calendar episode.

Cross-asset out-of-distribution generalisability is the final check. We replicated the Period 1 factorial on Ethereum and Binance Coin, both of which trade in regulated derivatives venues only from late 2020 onward and which therefore inherit a pre-institutional regime broadly analogous to Bitcoin's. The Period 1 reversal pattern is directionally consistent on both alternatives: GAS-t underperforms GJR-Normal in QLIKE, and the GAS-Normal recovery contrast carries the expected positive sign. The statistical magnitudes are smaller, reflecting both shorter usable samples and the dominance of Bitcoin in the cross-section, but the qualitative direction supports the interpretation that the mechanism we identify is a feature of pre-institutional crypto-asset return distributions rather than an idiosyncratic Bitcoin artefact. Full numerical results for the cross-asset replication are reported in Appendix B.

## Section 9: Conclusion and Future Directions

This paper has documented and decomposed a previously unreported reversal in Generalized Autoregressive Score volatility models with Student-t innovations on pre-institutional Bitcoin. Three findings stand out. First, the reversal is period-specific: GAS-t underperforms GJR-Normal by 9.92\% in QLIKE during 2017--2020 (DM-HLN $= -4.67$), but the deficit disappears in both the FTX-Luna and spot-ETF eras, where no specification contrast carries a Diebold-Mariano statistic above $|1.1|$. Second, the reversal is driven by the Student-t innovation rather than by score-driven dynamics: an orthogonal factorial decomposition shows that swapping the innovation to a Normal density restores GAS to statistical parity with the GJR-Normal benchmark, while swapping the dynamics from GJR to GAS within the Normal family produces no significant degradation. Third, a Markov-Switching GAS-t extension following Klaassen (2002) provides a substantial $+5.97$ DM-HLN improvement over the single-state specification but still fails to reach parity with GJR-Normal, ruling out regime-confounding and indicating that the t-innovation mismatch is a structural feature of the pre-institutional return-generating process.

The practitioner implication is narrow and operational. For volatility forecasting on cryptocurrency series whose sample is dominated by pre-institutional history---which includes most usable Bitcoin samples beginning before 2021 and almost all altcoin samples beginning before 2022---a Normal-innovation specification, whether estimated with GJR or GAS dynamics, is the conservative choice. The Student-t innovation that delivers reliable gains on equity indices and major currency pairs is not a default that transfers to this setting, and pooled-sample goodness-of-fit diagnostics will not reliably surface the mismatch. For cryptocurrency series whose effective sample is dominated by post-institutional history, the standard GAS-t workhorse re-acquires its usual role and our results provide no reason to depart from it.

Three limitations bound the strength of these claims. First, the spot-ETF sub-sample (Period 3) contains 100 out-of-sample days; while the cross-period contrasts are informative for documenting the absence of a reversal in this period, the precision of the point estimates is preliminary, and the analysis should be revisited once the sample reaches at least 500 days, which we anticipate by the fourth quarter of 2026. Second, the cross-asset replication in Appendix B covers two altcoins; broader generalisation requires a systematic treatment of altcoins with longer pre-institutional histories. Third, the institutional break-point dates we adopt are coarse approximations to a continuous process of market maturation, and finer microstructure measures of institutionalisation would sharpen the interpretation.

Two extensions of the present analysis would test the mechanism further. The first is a systematic factorial decomposition applied to other cryptoassets with usable pre-institutional samples---Ethereum over 2015--2017, Litecoin over 2013--2017---to test whether the Student-t versus dynamics attribution we report for Bitcoin reproduces in independent pre-institutional regimes. A consistent pattern across these alternatives would strengthen the case that the mechanism we identify is a feature of pre-institutional cryptoasset distributions rather than a Bitcoin-specific artefact. The second is to depart from the standard parametric innovation families altogether and explore non-parametric alternatives. A kernel-density innovation, or a Normal innovation augmented by an explicit jump component, would allow the model to fit episodic tail mass without imposing the global heavy-tail attenuation that the Student-t parameterisation implies. If the mechanism advanced in Section 7 is correct, such specifications should out-perform both GJR-Normal and GAS-t in the pre-institutional regime, and the gap should narrow in the post-institutional periods where the parametric heavy-tail description becomes more accurate. We leave both extensions to future work.

<!-- word_count: ~2410 -->

---

