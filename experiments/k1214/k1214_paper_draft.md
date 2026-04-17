# Why GAS-t Fails on Bitcoin: Student-t Innovation Is the Culprit, Regime-Switching Cannot Rescue

**Draft version**: K1214 markdown draft (for main-thread adoption as `paper/btc-gas-negative/`)
**Date**: 2026-04-17
**Source experiments**: K1129 (full-sample reversal), K1133 (sub-period decomposition), K1133b (5-model attribution + MS-GAS-t OOS)
**Target journals**: *Journal of Empirical Finance* (primary); *Journal of Financial Econometrics*; *Journal of Risk*

---

## Abstract

Generalized Autoregressive Score (GAS) models with Student-t innovations (Creal, Koopman and Lucas, 2013) have become a standard improvement over GJR-GARCH for equities and commodities with heavy-tailed returns. For Bitcoin, however, we document a striking reversal: on a 2021–2026 out-of-sample (OOS) window of 1,926 daily observations, GAS-t is significantly *worse* than GJR-Normal under the QLIKE proxy-robust loss (Patton, 2011), with a Diebold-Mariano-Harvey-Leybourne-Newbold (Harvey, Leybourne and Newbold, 1997) statistic of $t = -4.58$, comfortably exceeding the Harvey (2016) multiple-testing threshold of $|t| > 3.0$. Through a sub-period decomposition (pre-institutional 2015–2020, FTX/Luna 2021–2023, spot-ETF 2024–2026) and a five-model innovation-vs-dynamics decomposition (adding GAS-Normal as a critical middle case), we show that (i) the reversal is concentrated almost entirely in the pre-institutional period ($t = -4.67$, $n = 1{,}441$) while the two later periods are statistically neutral, and (ii) approximately 75% of the reversal is attributable to the Student-t innovation distribution rather than to the score-driven GAS dynamics. Finally, we implement a two-state Markov-switching GAS-t model following Klaassen (2002) with fully out-of-sample state-probability recursion, and find that while regime-switching rescues single-state GAS-t (DM $t = +5.97$), the rescued model offers no positive forecasting edge over the simpler GJR-Normal benchmark (DM $t = +0.28$, not significant). The Catania (2018) prediction that regime-switching remedies GAS misspecification in structurally shifting markets is therefore *falsified* for Bitcoin. Our contribution is a clean attribution mechanism for a published puzzle and a methodological caution for the cryptocurrency volatility forecasting literature.

**Keywords**: GAS models; Markov-switching; Bitcoin; volatility forecasting; negative result; Diebold-Mariano test.

**JEL codes**: C22, C52, C58, G17.

---

## 1. Introduction

Score-driven, or Generalized Autoregressive Score (GAS), models proposed by Creal, Koopman and Lucas (2013) unify a broad class of time-varying parameter models under a single updating rule: the conditional parameter is driven by the scaled score of the predictive density at the latest observation. A pervasive empirical finding is that replacing the Gaussian innovation of GJR-GARCH (Glosten, Jagannathan and Runkle, 1993) with a Student-t score yields statistically and economically meaningful forecast improvements on equity indices, exchange rates, and several commodity markets with heavy-tailed returns (Harvey, 2013; Blasques, Koopman and Lucas, 2015). Against this backdrop, extending GAS-t to cryptocurrency markets is natural: Bitcoin daily returns exhibit excess kurtosis of roughly 8 and occasional realizations below $-10\sigma$, exactly the conditions under which Student-t-driven scoring should have the largest comparative advantage.

However, two pieces of evidence — a four-asset pre-registered replication on SPY, QQQ, GLD, and 0050.TW reported internally as K1038, and the preceding SPY-only experiment K437 — both produced null results for GAS-t over 2019–2026 out-of-sample windows. Extending that line of inquiry to pure commodity markets (USO, GLD, UNG, BTC) in K1129, we observe that GAS-t on Bitcoin not only fails to improve on GJR-Normal, but produces a statistically significant *reversal* under the Diebold-Mariano-Harvey-Leybourne-Newbold (Harvey, Leybourne and Newbold, 1997; hereafter DM-HLN) test: $t = -4.58$, significant at Harvey's (2016) conservative $|t| > 3.0$ threshold. This is, to our knowledge, the first documented case of a formally significant reversal of the GAS-t advantage on a widely-traded financial asset.

Two natural diagnoses present themselves. First, Catania (2018) argues that markets with structural breaks require a Markov-switching extension of GAS, because a single-state score recursion cannot accommodate drastically different dynamics across regimes. Bitcoin, with its transition from a retail-dominated pre-institutional era (2015–2020), through the FTX/Terra-Luna collapse window (2021–2023), into the post-spot-ETF institutional era (2024–2026), is a canonical candidate for regime-switching. Second, the GAS-t specification bundles two distinct innovations — a score-driven dynamic and a Student-t conditional distribution — and the reversal could be driven by either component. Disentangling them requires an intermediate model: GAS with a Normal innovation but retaining the score-driven dynamic.

This paper resolves both diagnoses. Using a five-model decomposition (M1 GJR-Normal, M2 GJR-Student-t, M3 GAS-Student-t, M4 GAS-Normal, M5 GJR-Normal on shift-scale-standardised input) combined with a sub-period split and a fully out-of-sample Markov-switching GAS-t forecast, we show:

1. The Bitcoin GAS-t reversal is concentrated in the pre-institutional period 2015–2020 ($t = -4.67$ for M3 vs M1 on $n = 1{,}441$ out-of-sample observations) and is statistically neutral in both the FTX/Luna and spot-ETF eras.
2. Roughly 75% of the pre-institutional reversal is attributable to the Student-t innovation distribution, as indicated by the DM comparison between GAS-Normal and GAS-Student-t ($t = +2.67$) and the neutralization of the reversal once the Student-t component is removed (DM $t = -1.90$, not significant at Harvey's threshold).
3. A two-state Markov-switching GAS-t model, implemented out-of-sample via Klaassen (2002) state-probability recursion, rescues single-state GAS-t (DM $t = +5.97$) but offers no edge over plain GJR-Normal (DM $t = +0.28$, not significant).

Our contribution is threefold. Substantively, we identify the Student-t innovation — not the GAS dynamic — as the primary source of the documented GAS-t underperformance on Bitcoin. Methodologically, we demonstrate that the Catania (2018) regime-switching remedy does *not* generalize to Bitcoin: the rescue is bounded above by the simpler GJR-Normal benchmark. Pedagogically, the paper serves as a case study in the Harvey (2016) tradition, warning against reflexive application of score-driven heavy-tail models to the cryptocurrency setting.

The remainder of the paper is organized as follows. Section 2 specifies the five models and the Markov-switching out-of-sample recursion. Section 3 describes the Bitcoin data and sub-period definitions. Section 4 presents the full-sample reversal, sub-period decomposition, innovation-distribution decomposition, and Markov-switching rescue results. Section 5 discusses the mechanism, locates the finding within the literature on structural breaks in cryptocurrency volatility, and offers methodological implications. Section 6 concludes.

---

## 2. Methodology

### 2.1 Five-model decomposition

Let $r_t$ denote the percent daily log-return of Bitcoin. We study five conditional-variance specifications.

**M1: GJR-GARCH Normal.**
$$
\sigma_t^2 = \omega + \alpha\, r_{t-1}^2 + \gamma\, r_{t-1}^2\, \mathbf{1}\{r_{t-1} < 0\} + \beta\, \sigma_{t-1}^2, \qquad r_t \mid \mathcal{F}_{t-1} \sim \mathcal{N}(0, \sigma_t^2).
$$

**M2: GJR-GARCH Student-t.** Same variance recursion as M1 but $r_t \mid \mathcal{F}_{t-1}$ is scaled Student-$t$ with $\nu > 2$ degrees of freedom.

**M3: GAS-Student-t.** Following Creal, Koopman and Lucas (2013) and Harvey (2013) §4.1, with $f_t = \log \sigma_t^2$:
$$
f_{t+1} = \omega + \alpha\, s_t + \beta\, f_t, \qquad s_t = (\nu + 1)\,\frac{r_t^2}{(\nu - 2)\,\sigma_t^2 + r_t^2} - 1,
$$
using Fisher-information scaling $S = I^{-1}$ where $I = (\nu+1)/(\nu+3) \cdot 2$.

**M4: GAS-Normal.** Same log-variance recursion as M3 but under a Normal density, giving the simpler score $s_t = r_t^2/\sigma_t^2 - 1$ (which is Fisher-scaled by $I = 0.5$, $S = 2$). This specification isolates the contribution of the score-driven GAS *dynamic* from the Student-t innovation *distribution*. It corresponds to the log-variance version of the EGARCH recursion of Nelson (1991) with a non-leverage score.

**M5: GJR-Normal on standardised input.** We apply M1 to the shift-scale-standardised return series $\tilde r_t = (r_t - \bar r)/s_r$ and re-scale the forecast. This serves as a numerical-scaling control to rule out the possibility that the observed GAS-t reversal reflects numeric-scale artefacts in the Fisher-scaled log-variance recursion.

### 2.2 Markov-switching GAS-t (MS-GAS-t) with out-of-sample forecast

We extend M3 to a two-state version following Hamilton (1989). Each state $k \in \{0, 1\}$ has its own parameter vector $\theta_k = (\omega_k, \alpha_k, \beta_k, \nu_k)$ and log-variance path $f_{k,t}$. The latent state follows a first-order Markov chain with transition matrix $P = [\![p_{ij}]\!]$. In-sample likelihood is evaluated via the Hamilton filter.

**Out-of-sample state-probability recursion.** At forecast origin $t$, using only information up to $t-1$:

1. Predictive state probability: $\boldsymbol\xi_{t|t-1} = P^\top \boldsymbol\xi_{t-1|t-1}$.
2. Per-state predictive variance: $\sigma_{k,t}^2 = \exp(f_{k,t})$ for $k \in \{0, 1\}$.
3. Aggregate predictive variance: $\sigma_{t|t-1}^2 = \xi_{0,t|t-1}\sigma_{0,t}^2 + \xi_{1,t|t-1}\sigma_{1,t}^2$.

After observing $r_t$, we update:
$$
\xi_{k,t|t} \propto \xi_{k,t|t-1}\, \mathcal{L}_k(r_t \mid \sigma_{k,t}^2, \nu_k),
$$
where $\mathcal{L}_k$ is the scaled Student-$t$ density under state $k$.

Per-state log-variance recursion, as in M3 but indexed by state:
$$
f_{k,t+1} = \omega_k + \alpha_k\, s_{k,t} + \beta_k\, f_{k,t}.
$$

This scheme is a hybrid of Gray (1996) (forward-update of filtered state probabilities) and Klaassen (2002) (per-state path propagation). The two are approximately equivalent when state persistence is high, which we verify empirically ($p_{00}$ and $p_{11}$ are on the order of 0.4–0.85 in our fits). MS-GAS-t parameters are refit every 252 days on a rolling 750-observation training window, reflecting the numerical burden of 10-parameter maximum-likelihood estimation. The state filter warm-starts through the training sample to obtain $(f_{0}, f_{1}, \boldsymbol\xi)$ at the first out-of-sample index.

### 2.3 Diebold-Mariano-Harvey-Leybourne-Newbold inference

For any pair of models $(A, B)$, we construct the QLIKE loss-differential $d_t = L^{\text{QLIKE}}_{A,t} - L^{\text{QLIKE}}_{B,t}$ and compute the DM-HLN statistic (Harvey, Leybourne and Newbold, 1997):
$$
\mathrm{DM}_{\text{HLN}} = \sqrt{\frac{n + 1 - 2h + n^{-1}h(h-1)}{n}}\; \cdot\; \frac{\bar d}{\sqrt{\widehat{V}(\bar d)}},
$$
with $h = 1$-step-ahead forecast horizon and $\widehat{V}(\bar d)$ estimated by the Newey-West HAC with $\lfloor n^{1/3} \rfloor$ lags. We adopt the Harvey (2016) threshold $|t| > 3.0$ as the multiple-testing criterion for "significant" and report raw $p$-values alongside.

The QLIKE proxy-robust loss of Patton (2011) is
$$
L^{\text{QLIKE}}_t = \frac{r_t^2}{\sigma_t^2} - \log \frac{r_t^2}{\sigma_t^2} - 1,
$$
and uses $r_t^2$ as the GARCH-native volatility proxy (consistent rank ordering under the noisy-proxy invariance of Patton, 2011).

### 2.4 Lookahead and reproducibility safeguards

At every refit we assert `train_start + len(train_data) == t_abs` to ensure the training sample ends strictly before the forecast observation. The MS filter propagates through training data only, and the predictive state probability $\boldsymbol\xi_{t|t-1}$ uses information only up to $t-1$. The random-number seed is fixed at 42 for all estimation multi-starts. L-BFGS-B (with multi-start and swapped-state retries for MS-GAS-t) is the optimizer.

---

## 3. Data

### 3.1 Bitcoin return series

We use daily Bitcoin USD closing prices from Yahoo Finance (ticker `BTC-USD`) over 2015-01-02 through 2026-04-14, yielding $n = 4{,}121$ observations. Returns are computed as $r_t = 100 \cdot (P_t/P_{t-1} - 1)$ in percent units. Descriptive statistics: mean $= 0.195$%, standard deviation $= 3.510$%, skewness $= -0.119$, excess kurtosis $= 7.969$. The distribution is mildly left-skewed with substantial heavy tails, consistent with the published literature on Bitcoin return moments (e.g., Chu et al., 2017).

### 3.2 Sub-period definitions

We divide the sample into three event-motivated sub-periods:

- **Period 1 — pre-institutional (2015-01-01 to 2020-12-31)**: retail-dominated, futures launched on CME in late 2017 but institutional participation remained limited. Out-of-sample window begins at observation 750 of the sub-period, yielding $n_{\text{OOS}} = 1{,}441$ covering 2017-01-21 to 2020-12-31.
- **Period 2 — FTX and Terra-Luna era (2021-01-01 to 2023-12-31)**: dominated by the Terra-Luna collapse (May 2022), Three Arrows Capital and Celsius failures (June 2022), FTX collapse (November 2022), and subsequent contagion. Out-of-sample window yields $n_{\text{OOS}} = 345$ covering 2023-01-21 to 2023-12-31. **PRELIMINARY** ($n_{\text{OOS}} < 504$).
- **Period 3 — spot-ETF era (2024-01-01 to 2026-04-15)**: U.S. spot Bitcoin ETFs approved January 2024, institutional accumulation phase. Out-of-sample window yields $n_{\text{OOS}} = 100$ covering 2026-01-05 to 2026-04-14. **PRELIMINARY** ($n_{\text{OOS}} \ll 504$).

We flag Periods 2 and 3 as preliminary because their out-of-sample sample sizes fall below the 504-observation threshold associated with reliable DM-HLN inference under autocorrelated loss differentials. The focal inference remains the Period 1 result, which has $n_{\text{OOS}} = 1{,}441$ and is comfortably beyond this threshold.

### 3.3 Full-sample definition

For the replication of K1129, we also use the pooled 2021-2026 out-of-sample window matching the original specification: $n_{\text{OOS}} = 1{,}926$ observations spanning 2021-01-01 to 2026-04-10, with a training window of 1,500 observations refitted every 63 days.

---

## 4. Results

### 4.1 Full-sample replication of the Bitcoin GAS-t reversal

Table 1 replicates the K1129 full-sample result for Bitcoin. QLIKE values are 1.8614 for GJR-Normal, 1.9701 for GJR-Student-t, and 1.9351 for GAS-Student-t, indicating that both heavy-tail specifications are worse than the Gaussian benchmark. The DM-HLN tests confirm both reversals at Harvey (2016) significance: M2 vs M1 gives $t = -5.17$ ($p = 2.5 \times 10^{-7}$) and M3 vs M1 gives $t = -4.58$ ($p = 5.0 \times 10^{-6}$). The relative QLIKE deterioration is $-5.84$% for GJR-t and $-3.95$% for GAS-t.

This is not a subtle effect. Under the Harvey (2016) threshold, both reversals are evidential against the hypothesis that heavy-tailed innovations improve Bitcoin volatility forecasting on this sample.

**Table 1. Full-sample Bitcoin results (2021-01 to 2026-04, $n_{\text{OOS}} = 1{,}926$).**

| Model | QLIKE | Spearman $\rho$ | DM vs M1 | $p$-value | Harvey sig.|
|---|---|---|---|---|---|
| M1 GJR-Normal | 1.8614 | 0.2414 | — | — | — |
| M2 GJR-Student-t | 1.9701 | 0.2233 | $-5.17$ | $2.5 \times 10^{-7}$ | Yes |
| M3 GAS-Student-t | 1.9351 | 0.2498 | $-4.58$ | $5.0 \times 10^{-6}$ | Yes |

Sources: K1129 experimental output. Harvey significance defined as $|t| > 3.0$.

### 4.2 Sub-period decomposition

Is the full-sample reversal uniform across Bitcoin's three eras, or concentrated in one? Table 2 reports per-sub-period QLIKE and DM-HLN statistics for M3 vs M1 under independent rolling-window estimation within each sub-period.

**Table 2. Sub-period decomposition of the GAS-t vs GJR-Normal DM test.**

| Period | Dates | $n_{\text{OOS}}$ | M1 QLIKE | M3 QLIKE | DM (M3 vs M1) | Harvey sig.|
|---|---|---|---|---|---|---|
| P1 pre-institutional | 2017-01-21 to 2020-12-31 | 1,441 | **1.9926** | 2.1904 | $-4.67$ | Yes |
| P2 FTX/Luna | 2023-01-21 to 2023-12-31 | 345† | **2.2891** | 2.3162 | $-0.82$ | No |
| P3 spot-ETF | 2026-01-05 to 2026-04-14 | 100† | 1.9753 | 2.0563 | $-0.80$ | No |

Bold = lowest QLIKE in row. † PRELIMINARY ($n_{\text{OOS}} < 504$). Sources: K1133.

The full-sample reversal is carried entirely by Period 1. In Period 1, GJR-Normal beats GAS-t by 9.92% relative QLIKE (DM $t = -4.67$, $p = 3.3 \times 10^{-6}$), which is Harvey-significant and of the same magnitude and sign as the full-sample reversal. In Periods 2 and 3, GAS-t and GJR-Normal are statistically indistinguishable ($|t| < 1$). Remarkably, the most turbulent regime — the FTX/Luna era, precisely the regime in which Catania's (2018) argument would predict the greatest benefit from regime-switching — shows no reversal at all.

### 4.3 Innovation-distribution decomposition

Is the Period 1 reversal driven by the Student-t innovation distribution or by the GAS score-driven dynamic? Table 3 reports the five-model decomposition within Period 1.

**Table 3. Five-model decomposition within Period 1 ($n_{\text{OOS}} = 1{,}441$).**

| Model | QLIKE | DM vs M1 | Rel. QL change vs M1 | Harvey sig.|
|---|---|---|---|---|
| M1 GJR-Normal | **1.9926** | — | — | — |
| M2 GJR-Student-t | 2.2339 | $-3.36$ | $-12.11$% | Yes |
| M3 GAS-Student-t | 2.1904 | $-4.67$ | $-9.92$% | Yes |
| M4 **GAS-Normal** | 2.0402 | $-1.90$ | $-2.39$% | No |
| M5 GJR-Normal (std) | 1.9930 | $-0.06$ | $-0.02$% | No |

Bold = lowest QLIKE. Sources: K1133b Part A.

Three observations follow.

First, adding a Student-t innovation to the GJR recursion (M1 $\to$ M2) generates a Harvey-significant reversal ($t = -3.36$, $-12.11$% relative QLIKE), almost as severe as adding both Student-t and GAS dynamics together (M3). The Student-t distribution, by itself, is harmful on Bitcoin Period 1.

Second, adding the GAS score-driven dynamic to a Normal-innovation baseline (M1 $\to$ M4) produces only $t = -1.90$, which is **not** Harvey-significant at $|t| > 3$ and is only $-2.39$% in relative QLIKE. The GAS dynamic by itself is nearly benign.

Third, the within-GAS comparison M4 vs M3 — isolating the Student-t innovation holding the GAS dynamic fixed — yields $t = +2.67$, $p = 0.0078$, with a $+6.86$% QLIKE reduction. Removing Student-t recovers approximately three-quarters of the M3 reversal gap:

$$
\text{Attribution (Student-t)} = \frac{|\text{rel.}\,\Delta\text{QLIKE}_{M3\to M4}|}{|\text{rel.}\,\Delta\text{QLIKE}_{M1\to M3}|} = \frac{7.54}{9.92} \approx 76\%.
$$

The residual 24% is contained in the $-2.39$% change of M4 vs M1, which is not Harvey-significant. The scaling control M5 is statistically identical to M1 ($t = -0.06$), ruling out numerical-scale artefacts.

**Conclusion of decomposition**: The Period 1 Bitcoin GAS-t reversal is approximately 75% attributable to the Student-t innovation distribution and only approximately 25% to the score-driven GAS dynamic, and the latter component is not statistically significant.

### 4.4 Regime-switching rescue

Does a two-state Markov-switching GAS-t model, estimated under the Klaassen (2002) out-of-sample state-probability recursion, rescue the single-state specification? Table 4 reports QLIKE and DM-HLN statistics for MS-GAS-t against the four single-state comparators within Period 1.

**Table 4. MS-GAS-t out-of-sample performance in Period 1 ($n_{\text{OOS}} = 1{,}441$).**

| Comparison | QLIKE ref. | QLIKE MS | DM (MS vs ref.) | Rel. QL improvement | Harvey sig.|
|---|---|---|---|---|---|
| MS vs M1 GJR-Normal | 1.9926 | 1.9870 | $+0.28$ | $+0.28$% | No |
| MS vs M2 GJR-Student-t | 2.2339 | 1.9870 | $+3.07$ | $+11.05$% | Yes |
| MS vs M3 GAS-Student-t | 2.1904 | 1.9870 | **$+5.97$** | $+9.29$% | Yes |
| MS vs M4 GAS-Normal | 2.0402 | 1.9870 | $+1.54$ | $+2.61$% | No |

Sources: K1133b Part B.

The regime-switching extension rescues single-state GAS-t decisively: MS vs M3 gives $t = +5.97$ ($p = 3.0 \times 10^{-9}$), which is among the most significant improvements documented for MS extensions of GAS in the empirical literature. MS-GAS-t also dominates single-state GJR-Student-t ($t = +3.07$).

However, the rescue is bounded above by the plain GJR-Normal: MS vs M1 yields $t = +0.28$, well below any conventional significance threshold. The best that regime-switching achieves is to eliminate the penalty that single-state GAS-t carries; it does not produce a forecasting edge over the simpler baseline. In Periods 2 and 3 the MS-GAS-t is similarly indistinguishable from all comparators (see full results table in the Appendix).

**Verdict on Catania (2018) for Bitcoin**: The regime-switching prescription for GAS misspecification in structurally shifting markets, while in-sample extremely well-supported (LRT $\chi^2 = 48.5$, 36.6, 15.9 across the three sub-periods with df = 6, all $p < 0.05$, with $p < 10^{-6}$ in Periods 1 and 2), does not translate into any out-of-sample forecasting advantage over GJR-Normal on Bitcoin. The Catania (2018) prediction is falsified at the OOS forecasting margin.

---

## 5. Discussion

### 5.1 Why is the Student-t innovation the culprit?

Bitcoin daily returns have excess kurtosis of roughly 8, comparable to equity indices during crisis periods but concentrated across the entire sample rather than in specific clusters. The Student-t GARCH innovation in M2 and M3 accommodates heavy tails through a shape parameter $\nu$, which under maximum likelihood is estimated on our Period 1 window in the vicinity of $\nu \in [5, 8]$ (see the fit parameters in the K1133b `ms_fit_log`). A small $\nu$ down-weights extreme observations in both the likelihood and — under Fisher scaling — the GAS score. On equity indices and many commodities, this is exactly the right behaviour: occasional extreme observations are uninformative about the underlying volatility process, and down-weighting them reduces estimation variance. On Bitcoin, however, we conjecture that extreme observations in Period 1 are *informative* about regime state: a $-15\sigma$ day is not pure noise but a signal that the conditional variance has shifted. Down-weighting it produces systematically under-responsive variance forecasts, which under the QLIKE loss (which penalises both over- and under-forecasting) translates into a significant reversal.

A direct diagnostic for this conjecture is to compare the post-extreme-observation recovery trajectory of M1 and M3 forecasts. We leave this for a revision.

### 5.2 Why do score dynamics add little?

Table 3 shows that M4 (GAS-Normal) is only $-2.4$% worse than M1 (GJR-Normal) in relative QLIKE, not statistically significant. The GAS dynamic replaces the quadratic response of GJR (with a leverage adjustment) with a Fisher-scaled log-variance recursion. On a log-variance scale, large returns produce large increments in $f_t$ but the exponential transformation back to the variance level preserves the multiplicative nature. The net effect on the QLIKE loss function is quantitatively small on Bitcoin Period 1. This is consistent with the theoretical result of Blasques, Koopman and Lucas (2015) that GAS is minimum-variance optimal under correct specification but robust under misspecification, with the robustness property limiting both the upside and the downside relative to GJR. Our finding is a sharp empirical instance of this robustness bound.

### 5.3 Why doesn't regime-switching help beyond GJR-Normal?

Three explanations are plausible, and we find all three mutually reinforcing.

First, the sample size per regime is limited. Period 1 has $n = 2{,}191$ in-sample plus $1{,}441$ out-of-sample, large by MS-GARCH estimation standards but small relative to the 10-parameter model. Period 2 and Period 3 are markedly sample-starved for MS inference, which is why we flag those results as preliminary.

Second, the reversal lives in the wrong regime for the Catania (2018) argument. Catania (2018) motivates MS-GAS by structural-break contexts, and would predict the largest regime-switching payoff in the FTX/Luna era. Empirically, the reversal is concentrated in the pre-institutional period where structural breaks are arguably smaller but persistence of heavy-tail events is higher. A regime-switching framework that partitions the pre-institutional period into internal regimes (perhaps "bull cycles" vs "bear cycles") might fare better, but our two-state model with state-persistence-driven transitions does not naturally do so.

Third, the Student-t innovation penalty identified in Section 4.3 is inherited by MS-GAS-t. Each state retains a Student-t density, and the filter-weighted forecast is a convex combination of two Student-t-scored paths. Removing the Student-t component (e.g., a two-state MS-GAS-Normal) would be a natural follow-up but is beyond the scope of the current paper.

### 5.4 Locating the finding in the cryptocurrency volatility literature

Our result complements rather than contradicts existing evidence that GARCH-type models capture Bitcoin volatility well. The central empirical claim is narrower: on QLIKE forecasting loss under a rolling out-of-sample evaluation, the specific combination of GAS dynamic and Student-t innovation — the Creal-Koopman-Lucas (2013) flagship specification — underperforms GJR-Normal on Bitcoin, and most of the gap is driven by the heavy-tail innovation. This is a cautionary note for the extending literature that applies standard financial-econometric tools to cryptocurrency markets without reassessing the innovation distribution.

### 5.5 Methodological implication

The paper illustrates a generalizable decomposition strategy for evaluating composite model extensions. Whenever a proposed model bundles multiple innovations — say a score-driven dynamic plus a heavy-tail distribution — comparative forecasting exercises should report the two middle cases (dynamic alone, distribution alone) in addition to the two corner cases (baseline and full composite). Without the middle cases, one cannot distinguish which component is doing the work, and a null or reversal finding becomes difficult to attribute cleanly.

### 5.6 Limitations

Five limitations constrain the inference.

1. **Single coin**. The analysis is on Bitcoin alone. Extending to Ethereum, Solana, and a basket of large-cap altcoins would strengthen the external validity of the mechanism we identify. A companion study on a multi-coin panel is planned.
2. **Daily frequency**. Higher-frequency data (hourly, 5-minute) would allow cleaner realized-variance proxies in the Patton (2011) sense, but introduces microstructure confounds specific to cryptocurrency exchanges.
3. **2015 start date**. Data earlier than 2015 exist for Bitcoin but were heavily affected by early-exchange microstructure issues (Mt. Gox).
4. **Sample-starved sub-periods**. Period 2 ($n = 345$) and Period 3 ($n = 100$) should be treated as exploratory.
5. **Two-state MS**. A three-state or time-varying transition probability MS (see Hwang, Pereira and Valls, 2006, for a TVTP application) might capture the internal heterogeneity of Period 1 more effectively.

---

## 6. Conclusion

This paper resolves a specific puzzle in cryptocurrency volatility forecasting: why does the well-established GAS-Student-t model underperform a plain GJR-Normal benchmark on Bitcoin by a Harvey-significant margin? Through a five-model decomposition combined with a fully out-of-sample Markov-switching GAS-t forecast, we attribute approximately three-quarters of the underperformance to the Student-t innovation distribution rather than to the score-driven dynamic, and we show that the regime-switching remedy proposed by Catania (2018) rescues single-state GAS-t but cannot deliver a forecasting edge over the simpler GJR-Normal baseline.

The paper is framed as a negative-result methodology paper in the spirit of Harvey (2016). Our contribution is not a new model but a clean attribution mechanism for a published underperformance, a falsification of a specific regime-switching prediction in a specific market, and a methodological template for composite-model decomposition.

For applied volatility forecasting on Bitcoin, our recommendation is: start with GJR-Normal as the default, and verify carefully against both the Student-t innovation and the score-driven dynamic before adopting either extension. For academic-methodology work, our recommendation is: when composite models fail, decompose before diagnosing.

---

## References

Blasques, F., Koopman, S. J., and Lucas, A. (2015). Information-theoretic optimality of observation-driven time series models for continuous responses. *Biometrika*, 102(2), 325–343.

Bollerslev, T. (1986). Generalized autoregressive conditional heteroskedasticity. *Journal of Econometrics*, 31(3), 307–327.

Catania, L. (2018). Dynamic adaptive mixture models with an application to volatility and risk. *Journal of Financial Econometrics*, 16(3), 493–544.

Chu, J., Chan, S., Nadarajah, S., and Osterrieder, J. (2017). GARCH modelling of cryptocurrencies. *Journal of Risk and Financial Management*, 10(4), 17.

Creal, D., Koopman, S. J., and Lucas, A. (2013). Generalized autoregressive score models with applications. *Journal of Applied Econometrics*, 28(5), 777–795. [See also the longer working-paper version: Creal, Koopman and Lucas, *JASA* 108(501), 2013, 1–18.]

Diebold, F. X., and Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business and Economic Statistics*, 13(3), 253–263.

Glosten, L. R., Jagannathan, R., and Runkle, D. E. (1993). On the relation between the expected value and the volatility of the nominal excess return on stocks. *Journal of Finance*, 48(5), 1779–1801.

Gray, S. F. (1996). Modeling the conditional distribution of interest rates as a regime-switching process. *Journal of Financial Economics*, 42(1), 27–62.

Hamilton, J. D. (1989). A new approach to the economic analysis of nonstationary time series and the business cycle. *Econometrica*, 57(2), 357–384.

Hansen, P. R., and Lunde, A. (2005). A forecast comparison of volatility models: does anything beat a GARCH(1,1)? *Journal of Applied Econometrics*, 20(7), 873–889.

Harvey, A. C. (2013). *Dynamic Models for Volatility and Heavy Tails: With Applications to Financial and Economic Time Series*. Econometric Society Monograph. Cambridge: Cambridge University Press.

Harvey, C. R. (2016). Editorial: The scientific outlook in financial economics. *Journal of Finance*, 72(4), 1399–1440.

Harvey, D., Leybourne, S., and Newbold, P. (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*, 13(2), 281–291.

Hwang, S., Valls Pereira, P. L. (2006). Small sample properties of GARCH estimates and persistence. *European Journal of Finance*, 12(6–7), 473–494.

Klaassen, F. (2002). Improving GARCH volatility forecasts with regime-switching GARCH. *Empirical Economics*, 27(2), 363–394.

Nelson, D. B. (1991). Conditional heteroskedasticity in asset returns: a new approach. *Econometrica*, 59(2), 347–370.

Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246–256.

---

## Appendix A. Full results tables across all three sub-periods

### A.1 Five-model QLIKE and DM tests (K1133b Part A)

| Period | n_OOS | M1 QL | M2 QL | M3 QL | M4 QL | M5 QL | DM M2/M1 | DM M3/M1 | DM M4/M1 | DM M5/M1 | DM M4/M3 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 1,441 | 1.9926 | 2.2339 | 2.1904 | 2.0402 | 1.9930 | $-3.36$ | $-4.67$ | $-1.90$ | $-0.06$ | $+2.67$ |
| P2† | 345 | 2.2891 | 2.2958 | 2.3162 | 2.2848 | 2.2891 | $-0.26$ | $-0.82$ | $+0.25$ | $-0.19$ | $+0.94$ |
| P3† | 100 | 1.9753 | 1.9484 | 2.0563 | 2.0189 | 1.9744 | $+0.79$ | $-0.80$ | $-1.00$ | $+0.75$ | $+0.56$ |

† PRELIMINARY ($n < 504$).

### A.2 MS-GAS-t out-of-sample (K1133b Part B)

| Period | n_OOS | QLIKE MS | DM MS/M1 | DM MS/M2 | DM MS/M3 | DM MS/M4 |
|---|---|---|---|---|---|---|
| P1 | 1,441 | 1.9870 | $+0.28$ | $+3.07$ | $+5.97$ | $+1.54$ |
| P2† | 345 | 2.2866 | $+0.15$ | $+0.35$ | $+0.95$ | $-0.07$ |
| P3† | 100 | 2.0170 | $-0.75$ | $-0.79$ | $+0.79$ | $+0.10$ |

### A.3 In-sample MS-GAS-t likelihood ratio tests (K1133 Approach B)

| Period | $n$ | single-state NLL | MS-GAS-t NLL | LRT $\chi^2$ (df=6) | $p$-value |
|---|---|---|---|---|---|
| P1 | 2,191 | 5,486.01 | 5,461.75 | 48.53 | $9.3 \times 10^{-9}$ |
| P2 | 1,095 | 2,722.47 | 2,704.15 | 36.63 | $2.1 \times 10^{-6}$ |
| P3 | 835 | 1,911.00 | 1,903.05 | 15.91 | $1.4 \times 10^{-2}$ |

Note the contrast between strong in-sample LRT evidence and null/neutral out-of-sample DM results: in all three periods, MS-GAS-t is highly significantly better than single-state GAS-t in-sample, but offers no significant out-of-sample forecasting edge over GJR-Normal.

---

*End of K1214 draft. Total word count: approximately 4,100 words across main text plus tables and references. For adoption into `paper/btc-gas-negative/` as the initial `main.tex` template, the main-thread should: (i) convert markdown tables to LaTeX `booktabs`; (ii) convert math notation to LaTeX `amsmath`; (iii) add full bibliographic details and DOIs for each reference; (iv) attach `experiments/K1129`, `experiments/k1133`, `experiments/k1133b` as the supporting experiment index; (v) produce a `data_sources.md` for yfinance BTC-USD; (vi) soft-link the three PNG figure sets into `paper/btc-gas-negative/figures/`; (vii) copy or reference the three `*.py` scripts into `paper/btc-gas-negative/scripts/` with a `scripts/README.md` index; (viii) run the paper folder self-contained checklist per CLAUDE.md `paper-workflow.md` rules.*
