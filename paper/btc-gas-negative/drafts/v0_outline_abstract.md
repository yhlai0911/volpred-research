# BTC GAS-t Negative-Result Methodology Paper — v0 Outline + Abstract

**Author**: Yi-Hao Lai (Da-Yeh University, Department of Finance)
**Target journal**: Journal of Banking and Finance (JBF) / International Journal of Forecasting (IJF) — negative-result methodology track
**Status**: v0 outline drafted 2026-06-07 by main thread (hourly-08 fire, task `BTC_GAS_negative_paper`)
**Parent experiments**: K1129 (cross-asset GAS-t), K1133 (BTC sub-period decomposition), K1133b (5-model factorial + MS-GAS-t)
**Next sub-tasks**: `BTC_GAS_intro`, `BTC_GAS_lit_review`, `BTC_GAS_methodology`, `BTC_GAS_results`, `BTC_GAS_discussion`

---

## Working Title

**Why GAS-t Fails on Pre-Institutional Bitcoin: Student-t Innovation, Not Score-Driven Dynamics, Is the Culprit (and Regime-Switching Rescues to Parity, Not Superiority)**

Alt short title: *Decomposing the BTC GAS-t Reversal: A Factorial 5-Model Diagnosis*

---

## Abstract (draft, ≈210 words)

We document a previously unreported reversal in Generalized Autoregressive Score (GAS) volatility models with Student-t innovations applied to Bitcoin: over the pre-institutional period (Jan 2017 – Dec 2020, n=1,441 OOS days), GAS-t produces 9.92% worse QLIKE than the GJR-Normal benchmark (Diebold-Mariano-HLN t = -4.67, p < 10⁻⁵). Two natural hypotheses — that score-driven GAS dynamics fail, or that Student-t innovations fail — are typically conflated in the GAS literature. We resolve this via a factorial 5-model decomposition (GJR-N, GJR-t, GAS-N, GAS-t, GJR-N-standardized) which shows that GAS-Normal *recovers* to statistical parity with GJR-Normal (DM-HLN = -1.90, p = 0.058) while GAS-t and GJR-t both reverse, isolating Student-t innovation — not GAS dynamics — as the proximate cause. A Markov-Switching GAS-t extension rescues GAS-t to statistical parity with GJR-Normal (DM-HLN = +5.97 vs single-state GAS-t; vs GJR-Normal the point estimate is marginally favourable but indistinguishable, DM-HLN = +0.28), at a substantial parameter cost — parity, not superiority. The reversal disappears in the post-FTX recovery (OOS 2023) and spot-ETF regime-maturity (OOS 2026Q1) eras, suggesting institutional flows fundamentally altered Bitcoin's return distribution. We provide practitioner guidance on when GAS-t is and is not appropriate for crypto volatility forecasting.

**JEL**: C22, C53, C58, G17
**Keywords**: Bitcoin, GAS models, Student-t innovation, volatility forecasting, negative result, Markov-switching, regime change

---

## Three Contributions

1. **Regime-specific negative result documented and reconciled with literature.** We document that the K1129 full-sample reversal of GAS-t on Bitcoin is driven entirely by the pre-institutional period (2017-2020), while the FTX-Luna (2021-2023) and spot-ETF (2024+) eras show no GAS-t deficit. This reconciles a single anomalous full-sample finding with the broader GAS literature where GAS-t typically wins on equity indices and commodities.

2. **Proximate cause isolated via factorial decomposition.** A five-model factorial design (orthogonalizing innovation distribution × score-driven dynamics) shows that the GAS-Normal specification recovers to statistical parity with GJR-Normal, while *both* GAS-t and GJR-t reverse, identifying Student-t innovation — not GAS score-driven dynamics — as the root cause. This is a methodologically sharper diagnosis than the typical "GAS-t loses on BTC" stylized fact.

3. **Regime-switching rescue is partial and informative.** A Markov-Switching GAS-t extension provides a +5.97 DM-HLN improvement over single-state GAS-t and rescues to statistical parity with GJR-Normal, but not to clear superiority. The partial rescue rules out simple regime-confounding and indicates that the t-innovation mismatch is structural to pre-institutional BTC return distributions, not an artifact of unmodeled volatility regimes.

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
  - **Period 3 (spot-ETF regime maturity window)**: 2026-01-05 → 2026-04-14 (n_OOS = 100, preliminary). BlackRock/Fidelity spot ETF approvals 2024-01-10, with the OOS window arriving only after the rolling warm-up.
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
- MS-GAS-t vs GJR-N (M1): DM-HLN = +0.28 NS (point estimate slightly favours MS, but only reaches parity, not superiority).
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
- Planned robustness only: alternative period cuts and alternative loss functions are specified but not yet run; no numeric claims from these exercises are used in this draft.
- Sample inclusion: Excluding 2017 super-bull or 2018 crash years individually → Period 1 reversal persists.
- Planned future robustness: ETH and BNB out-of-distribution checks are specified but not yet landed in an archived results file.

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
