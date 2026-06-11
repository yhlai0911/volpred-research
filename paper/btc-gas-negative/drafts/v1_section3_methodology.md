## Section 3: Data and Methodology

<!-- word_count: ~1520 -->

### 3.1 Data

We use daily closing prices for Bitcoin (BTC-USD) from 1 January 2015 through 15 April 2026, retrieved from Yahoo Finance via the `yfinance` Python API. To preserve the canonical return series and avoid drift induced by retroactive dividend or split adjustments — a concern documented for cryptocurrency exchange feeds reconstructed by third-party aggregators — we set `auto_adjust=False` and treat the unadjusted closing series as primary. The raw sample contains 4,121 daily observations, of which 1,886 form the pooled out-of-sample (OOS) evaluation window after the rolling 750-day in-sample warm-up is consumed. Log returns are computed as $r_t = 100 \cdot \ln(P_t / P_{t-1})$ and realized variance proxies follow the squared-return convention $\sigma^{2,\text{proxy}}_t = r_t^2$, consistent with Patton (2011) and Hansen, Lunde and Nason (2003) for daily-frequency loss-function evaluation. A paper-local snapshot CSV matching this `2026-04-15` canonical sample end is still a pending reproducibility requirement; until it lands, the draft should not describe the snapshot layer as fully completed.

### 3.2 Three-Period Split

Rather than partitioning the OOS window by calendar year, equal-length thirds, or data-driven changepoint detection, we segment the sample by *institutional structure*. The motivation is mechanistic: Bitcoin's return-generating process is hypothesized to be qualitatively different before institutional custody, derivatives liquidity and spot-ETF arbitrage became routine. Data-driven segmentation (e.g., Bai-Perron breakpoint tests on the return variance) would mechanically locate breaks at the largest realized-volatility excursions — typically the March 2020 COVID shock, the May 2021 China-ban crash, and the November 2022 FTX collapse — but those are *consequences* of the prevailing market structure, not its causes, and using them as cut-points would conflate idiosyncratic drawdowns with structural regime change. Anchoring the partition to externally observable institutional events (custody platform launches, futures-ETF approval, spot-ETF approval) avoids look-ahead snooping in the partitioning step itself and yields period boundaries that are pre-registered and not optimized against forecast performance.

The three OOS sub-samples are:

- **Period 1 — Pre-institutional (2017-01-21 → 2020-12-31, n_OOS = 1,441 days).** No US spot ETF, no major regulated institutional custody at scale, no CME options on Bitcoin futures until early 2020. Retail-dominated order flow, fragmented exchange microstructure, and persistent basis dislocation between spot and futures.

- **Period 2 — FTX-Luna recovery (2023-01-21 → 2023-12-31, n_OOS = 345 days).** Post-Terra/Luna and post-FTX collapse, institutional rebuild phase: surviving exchanges re-collateralize, derivatives open interest recovers, but no spot ETF yet. Order flow is partially institutional and increasingly tied to traditional risk-on/risk-off cycles.

- **Period 3 — Spot-ETF regime maturity window (2026-01-05 → 2026-04-14, n_OOS = 100 days, preliminary).** Following the 10 January 2024 SEC approval of US-listed spot Bitcoin ETFs (BlackRock IBIT, Fidelity FBTC, and others), creation-redemption arbitrage links Bitcoin's price to large-asset-manager flow and traditional brokerage rails; because the rolling 750-day warm-up is consumed first, the actual OOS evaluation window arrives in 2026Q1. Sample size in this period is acknowledged as preliminary; conclusions for Period 3 are reported but not used to support the paper's primary diagnostic claim, which is established on Period 1.

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
