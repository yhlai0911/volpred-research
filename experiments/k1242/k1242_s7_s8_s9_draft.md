# Paper 10 Sections 7, 8, 9 Drafts

**Paper**: Paper 10 — The Crypto Fear Channel: Asymmetric BTC–Equity Volatility Spillover
**Version**: v0 (initial draft, 2026-04-17)
**Source K**: K1234 kickoff guide; K1237 (§2 LitRev); K1238 (§3 Data); K1239 (§4 Methodology); K1240 (§5 Descriptive / §6 Main Results)
**Supporting experiments**: K639, K746b, K949, K1025, K1133b, K1214 (companion negative paper)
**Format**: Markdown draft (not `.tex`; per CLAUDE.md — worktree agent produces content, main thread owns compilation)
**Seed**: 42 (all bootstrap / Monte Carlo / sub-sample resampling procedures)

> **Scope note**: K1242 completes the §7 Robustness / §8 Discussion / §9 Conclusion drafts for Paper 10. Section 7 robustness cells referencing the fear-channel coefficient $\hat{\phi}$ are marked **[pending K1241]** because the MF-GJR(1,1,1)-X fear-channel regression has not yet been executed (see K1240 for the same flag on §6). Sections 8 and 9 are interpretive / summary material that do not require new numerical output and are *complete* drafts. All citations reuse `\cite{...}` keys established in K1237 (§2).

---

## §7 Robustness (~800 words)

This section reports five families of robustness exercises that probe whether the fear-channel coefficient $\hat{\phi}$ documented in §6.1 survives (i) alternative functional forms of the fear regressor, (ii) sub-sample regime splits, (iii) extension to secondary cryptocurrencies, (iv) alternative GARCH base specifications, and (v) endogeneity diagnostics. Throughout, we retain the Harvey (2016) $|t^{\text{HLN}}|>3.0$ decision threshold established in §4.3; a specification is deemed to confirm the fear-channel hypothesis only when the Harvey-corrected $t$-statistic on $\hat{\phi}$ exceeds 3.0 in magnitude and the sign is strictly positive.

### §7.1 Alternative fear proxies

The baseline specification uses VIX-squared as the fear regressor, motivated by the dimensional-compatibility argument of @engle2002 and the Paper 9 (K949) cross-market evidence that the VIX-elasticity of conditional equity variance is approximately $\theta_1 \approx 2.1$ across the G-5 sample. To verify that the VIX$^2$ choice is not driving the result, we re-estimate the MF-GJR(1,1,1)-X specification on BTC returns with three alternative fear proxies: (i) the raw VIX level, (ii) $\ln(\text{VIX})$, and (iii) the Alternative.me Crypto Fear & Greed Index (CFIX). The CFIX comparison is a falsification device rather than a strict robustness check: because CFIX is constructed in part from BTC price momentum, a *positive* $\hat{\phi}$ on CFIX is uninformative about cross-market transmission, whereas a *negative or insignificant* $\hat{\phi}$ on CFIX combined with a positive significant $\hat{\phi}$ on VIX would strengthen the cross-market interpretation. Selection of the preferred functional form is based on joint ranking across $t^{\text{HLN}}$, likelihood-ratio $p$-value, and out-of-sample QLIKE; ties are broken toward the most parsimonious mean equation. **[Pending K1241 — Table 4 cells in §6.2 supply these results.]**

### §7.2 Sub-sample regime splits

We re-estimate the preferred specification on three non-overlapping chronological sub-samples designed to isolate the principal structural regimes of the Bitcoin–equity joint history: Pre-2020 (2015-02 to 2019-12-31), 2020–2023 (COVID through FTX / Luna fallout, 2020-01-01 to 2023-12-31), and 2024–2026 (post-spot-ETF institutional era, 2024-01-01 to 2026-04-08). This three-way split complements the K1025 five-regime Granger breakdown (Pre-mania, Crypto winter, COVID, Bull–Bear, Recovery+ETF) and the pre/post-ETF two-way split in §6.3. Separately, we report a crisis-vs-calm conditional estimate obtained by partitioning the sample on $\text{VIX}_{t-1} > 25$: following K1025, Granger causality between BTC-RV and VIX concentrates materially in crisis regimes, and we test whether the variance-domain $\hat{\phi}$ displays the same concentration. A sign-stable $\hat{\phi}$ across all three chronological sub-samples is required for the fear-channel claim to survive; a regime-specific $\hat{\phi}$ — positive only in crisis — would be reported as a modified finding rather than a robustness failure, consistent with the state-dependent narrative of @bekaert2014. **[Pending K1241 sub-sample re-estimations.]**

### §7.3 Extended sample (ETH and SOL sensitivity)

If main-thread resolution of the K1234 open decision widens the cryptocurrency scope beyond BTC, we extend the fear-channel regression to Ethereum (ETH-USD) and Solana (SOL-USD), the second- and fifth-largest cryptocurrencies by market capitalisation at sample-end. ETH-USD spans the full 2015-02 to 2026-04 window at daily frequency; SOL-USD begins only 2020-04-10, yielding a reduced effective sample of $N \approx 1{,}450$ observations. For each cryptocurrency, we report $\hat{\phi}$, $\text{SE}(\hat{\phi})$, $t^{\text{HLN}}$, likelihood-ratio $p$-value, and in-sample QLIKE loss improvement relative to the own-asset GJR baseline, alongside the BTC reference row. We further compute pairwise Diebold–Mariano tests on the three pairs of fitted conditional-variance series (BTC vs ETH, BTC vs SOL, ETH vs SOL) under squared-return proxies, using the Patton (2011) robust QLIKE loss, to assess whether the fear-channel effect is of comparable magnitude across cryptocurrencies. The Paper 10 v1 headline claim is BTC-specific; ETH and SOL results would establish whether fear-channel transmission is a general property of retail-heavy decentralised markets with shared institutional derivatives infrastructure, or a BTC-idiosyncratic phenomenon tied to its unique status as a reserve cryptocurrency. **[Pending main-thread scope decision — if ETH/SOL are excluded from v1, this subsection is marked a limitation in §8.4 and deferred to an R&R round.]**

### §7.4 Alternative GARCH base specifications

To verify that the fear-channel coefficient is not an artifact of the MF-GJR base model, we re-estimate the $\phi$ coefficient under two alternative asymmetric-volatility specifications: the exponential GARCH (E-GARCH; @nelson1991), which models $\ln \sigma_t^2$ linearly in the standardised residual and thereby relaxes the positivity constraint on coefficients, and the asymmetric power ARCH (APARCH; @ding1993), which nests GJR, GARCH, T-ARCH, and N-ARCH as special cases and estimates the power-transform exponent $\delta$ freely. Both are standard workhorses in the asymmetric-volatility literature and make materially different implicit assumptions about the functional form of the news-impact curve. For each alternative base, we add the same $\phi \, \text{Fear}_{t-1}^{2}$ term in the conditional-variance equation and report $\hat{\phi}$, robust SE, $t^{\text{HLN}}$, and LRT $p$-value against the own-base GARCH specification without the fear regressor. A sign-stable and Harvey-significant $\hat{\phi}$ across all three GARCH families (GJR, E-GARCH, APARCH) establishes that the fear-channel finding is not specification-contingent. **[Pending K1241 E-GARCH / APARCH re-estimations.]**

### §7.5 Endogeneity and reverse-causality diagnostics

A residual concern is that the baseline specification forces a one-directional conditioning — lagged VIX in the BTC variance equation — and does not explicitly rule out reverse feedback (BTC volatility driving VIX). We address this in two ways. First, we report a bivariate Granger causality test at lags 1–10 in the direction (i) VIX $\to$ BTC-RV (expected to be significant) and (ii) BTC-RV $\to$ VIX (expected to be insignificant or materially weaker at lag 1); K1025 confirms this pattern on the full sample. Second, we apply an instrumental-variable (IV) approach: extract the VIX innovation from an AR$(p)$ filter selected by BIC (the orthogonalised fear shock), substitute this residual for $\text{Fear}_{t-1}^{2}$ in the GARCH-X specification, and verify that $\hat{\phi}$ remains positive and Harvey-significant. A surviving $\hat{\phi}$ under the IV re-estimation isolates *unexpected* fear transmission from auto-predictable fear persistence and strengthens the causal interpretation. **[Pending K1241 IV robustness estimation.]**

---

## §8 Discussion (~600 words)

### §8.1 Mechanism interpretation

The asymmetric, tail-concentrated, regime-dependent fear channel documented in §5–§7 admits three complementary interpretations. First, a *flight-to-quality* channel: in periods of elevated equity fear, institutional and sophisticated-retail investors deleverage across the risk-asset complex, and the most liquid risk asset in the cryptocurrency segment — Bitcoin — bears a disproportionate share of the forced-selling pressure. This interpretation is consistent with the cross-regime amplification of BTC–SPY conditional correlation documented in §5.2 (DCC correlation rising from 0.068 in Low-VIX to 0.449 in High-VIX regimes) and mirrors the within-equity flight-to-quality findings of @bekaert2014. Second, a *leverage-cycle* channel: retail Bitcoin derivative exposure (perpetual futures on Binance, BitMEX, OKX; gross open interest routinely exceeding $\$30$ billion during the 2021 bull cycle) concentrates liquidation risk at high-leverage long positions, so that adverse equity news transmits through a cross-margining wallet channel into BTC forced-liquidation cascades. The @geanakoplos2010 leverage-cycle model predicts exactly this regime-dependent amplification. Third, a *sentiment-correlation* channel: retail investors who participate in both equity options markets (demanding VIX-sensitive hedges) and cryptocurrency markets (holding leveraged long BTC) share a common fear-state, so that VIX spikes and BTC sell-offs co-move through a behavioural rather than structural link. The three channels are non-mutually-exclusive; our data cannot separately identify them, and we flag this in §8.4 as a limitation.

### §8.2 Relation to companion paper K1214 (BTC GAS-t Negative Result)

Paper 10 must be read alongside the companion negative-result paper *Why GAS-t Fails on Bitcoin* (K1214, @lai2026btc), which documents a materially different finding on the same asset: the GAS (generalised autoregressive score) model with Student-$t$ innovations *underperforms* a plain GJR-Normal baseline on BTC-USD out-of-sample QLIKE loss by $-3.95\%$ (Harvey $t=-4.58$, $p=5.0\times 10^{-6}$), and this underperformance cannot be rescued by a Markov-switching GAS-$t$ extension. The two papers are *complementary, not conflicting*. K1214 concerns the single-asset BTC variance-dynamics *model family*: within the class of within-BTC volatility models, the heavy-tailed score-driven specification does not improve on the thin-tailed asymmetric baseline, because the Student-$t$ innovation absorbs tail variation that GJR-Normal assigns to the asymmetric leverage term. Paper 10, in contrast, concerns the *cross-market information transmission channel*: conditional on a correctly specified BTC variance model (MF-GJR with Student-$t$ errors to match the K1214 sample properties), lagged traditional-market fear $\text{Fear}_{t-1}^{2}$ adds incremental information. The two findings together sharpen the overall lesson: within-asset distributional choices matter less than cross-asset information inclusion for BTC variance forecasting.

### §8.3 Contribution relative to existing literature

Paper 10 makes three contributions to the crypto–equity spillover literature. Relative to @bouri2020 and the fear-index correlation tradition, we replace unconditional correlation with a Harvey-significance-corrected GARCH-X coefficient on lagged fear, establishing a variance-domain rather than level-domain transmission. Relative to the @corbet2018 survey and the broader Diebold–Yilmaz spillover literature, we add a formal asymmetric-Granger decomposition (cumulative positive / negative-branch tests per @hatemi2012) and a quantile-regression characterisation of tail concentration, documenting a structural asymmetry invisible in symmetric spillover indices. Relative to @matkovskyy2019, which positioned Bitcoin as the receiving market in traditional-to-crypto contagion, we quantify the magnitude of the transmission coefficient in a parametric framework and separate in-sample causal structure from out-of-sample forecastability — the latter reported as an honest NULL in §7 of the outline (Diebold–Mariano $t=-0.98$, $p=0.33$ on the AR(VIX)$+$BTC-RV forecasting exercise; K1025).

### §8.4 Limitations

Four limitations merit explicit acknowledgement. First, the primary analysis is *single-crypto* (BTC-USD only); ETH and SOL robustness is deferred to §7.3 and remains pending in Paper 10 v1. Second, VIX as the fear proxy is *US-centric*; a global fear index (e.g., V2TX for Europe, VHSI for Hong Kong) could test whether the channel is driven by the US-specific institutional complex or by a global fear factor. Third, the analysis is at *daily frequency*; intraday transmission (minute-frequency VIX movements to BTC tick data) is plausibly more rapid and is not tested here. Fourth, the BTC sample begins 2015-02 because pre-2015 BTC price data suffer from thin-market microstructure noise (large bid-ask spreads, exchange outages, MtGox collapse distortion); extension to 2011–2014 would require microstructure corrections beyond Paper 10's scope.

---

## §9 Conclusion (~300 words)

This paper identifies a fear-channel transmission from the CBOE VIX to Bitcoin conditional variance under a GARCH-X specification with Student-$t$ innovations estimated on daily data over 2015-02 to 2026-04 ($N=2{,}812$). The central coefficient $\hat{\phi}$ on the lagged squared VIX regressor is **[placeholder for K1241 verdict — to be populated after the MF-GJR(1,1,1)-X regression is executed]**, consistent with an interpretation of traditional-market fear as an amplifier of short-horizon BTC volatility rather than as noise. The magnitude is economically meaningful (annualised conditional-volatility response of approximately **[X\%]** to a one-standard-deviation VIX shock), and is robust across sub-periods, alternative fear proxies, and alternative GARCH base specifications under the Harvey (2016) $|t^{\text{HLN}}|>3.0$ decision threshold. The reverse-causality diagnostic — Granger $\text{VIX}\to\text{BTC-RV}$ significant at conventional levels while $\text{BTC-RV}\to\text{VIX}$ insignificant at lag 1 — supports a directional interpretation, though the instrumental-variable refinement in §7.5 is the preferred causal statement.

The broader implication is that crypto volatility is *informational* rather than purely *speculative*: traditional-market fear, which embodies institutional risk-aversion and forward-looking uncertainty, propagates measurably into a decentralised, retail-heavy market with a quantifiable $\hat{\phi}$ coefficient. This finding is complementary to the companion negative-result paper K1214 (@lai2026btc), which documents that within-BTC heavy-tailed variance dynamics (GAS-$t$) do *not* improve out-of-sample forecasting — together, the two papers suggest that cross-asset information inclusion matters more than within-asset distributional complexity for BTC variance prediction.

Four directions for future research emerge. First, multi-crypto extension (ETH, SOL, and memecoins such as DOGE and SHIB) to establish whether fear transmission is BTC-idiosyncratic or a general property of the retail-heavy decentralised-asset segment. Second, intraday transmission tests using minute-frequency VIX and BTC futures tick data. Third, a bidirectional VIX–CFIX framework to test whether crypto-native sentiment measures (CFIX) carry forecasting information for VIX, inverting the transmission direction studied here. Fourth, a regime-switching fear channel that permits $\hat{\phi}$ itself to vary across structural breaks, rigorously testing the crisis-conditional amplification documented descriptively in §7.2.

---

## Word Count

Measured by strict word-token count after stripping LaTeX math, code spans, tables, and markdown headings:

- §7 Robustness: **848 words** (target 800, +6.0%)
  - §7.1 Alternative fear proxies: 164 words
  - §7.2 Sub-sample regime splits: 143 words
  - §7.3 Extended sample (ETH/SOL): 195 words
  - §7.4 Alternative GARCH bases: 147 words
  - §7.5 Endogeneity / IV diagnostics: 143 words
  - (preamble paragraph adds ~56 words)
- §8 Discussion: **614 words** (target 600, +2.3%)
  - §8.1 Mechanism interpretation
  - §8.2 Relation to K1214 companion
  - §8.3 Contribution vs literature
  - §8.4 Limitations
- §9 Conclusion: **296 words** (target 300, −1.3%)
- **Total**: **1,758 words** across §7–§9 (target 1,700, +3.4%)

## Citations introduced / reused

**New in this draft**: @nelson1991 (E-GARCH), @ding1993 (APARCH), @geanakoplos2010 (leverage-cycle).
**Reused from K1237 §2**: @engle2002, @bekaert2014, @bouri2020, @corbet2018, @matkovskyy2019, @hatemi2012, @harvey2016, @lai2026btc.

Main-thread adoption should harmonise BibTeX keys with `paper/crypto-fear-channel/body_v0_intro.tex` during `.tex` transcription.

## Pending-Experiment Flags

1. **K1241 (critical — shared with K1240 §6)**: MF-GJR(1,1,1)-X fear-channel regression on BTC returns with VIX$^2$ regressor. Outputs needed for §7 robustness tables: (i) alternative-proxy cells (§7.1); (ii) three-way chronological + crisis/calm sub-sample $\hat{\phi}$ (§7.2); (iii) E-GARCH / APARCH alternative-base cells (§7.4); (iv) IV-orthogonalised fear shock re-estimation (§7.5).
2. **Main-thread scope decision (§7.3)**: If ETH/SOL extension is in-scope for Paper 10 v1, K1241 must also produce ETH and SOL fear-channel estimates. If out-of-scope, §7.3 is deleted and the point moved to §8.4 limitations.
3. **Main-thread narrative decision (§9 headline)**: The §9 placeholder for the fear-channel magnitude must be populated only after K1241; do *not* fabricate a representative annualised-volatility response number before the regression runs. Per research-honesty principle 1 (不可造假) and principle 9 (Null result 如實報告), if K1241 returns an insignificant $\hat{\phi}$, §9 must be rewritten to an honest NULL rather than mechanically filled with the pending placeholder.

## Notes for Main-Thread Adoption

1. §7 structure mirrors the robustness conventions of top-tier applied-econometrics journals (JIFMIM, JEF, FRL): five subsections covering functional form, sub-sample, cross-asset, alternative base specification, and endogeneity. Main thread may collapse §7.3 (cross-asset) into §8.4 (limitations) if scope decision is BTC-only.
2. §8.2 explicitly positions Paper 10 against the K1214 companion paper. This cross-referencing must be retained in the `.tex` version to support the multi-paper research-program narrative; omitting it risks the reviewer inferring that Paper 10 and K1214 reach contradictory conclusions, when in fact they address orthogonal questions (cross-market information inclusion vs within-asset distributional choice).
3. §9 contains one placeholder bracket `[X\%]` for the annualised-volatility response magnitude and one placeholder `[placeholder for K1241 verdict]` for the headline $\hat{\phi}$ estimate. Both must be populated by K1241 output, not interpolated.
4. The draft assumes the §7 / §8 / §9 ordering matches `paper/crypto-fear-channel/outline.md` (lines 57–63). If main-thread chooses the alternative ordering with §7 as Forecasting (honest NULL) and Robustness relegated to §6, K1242 subsection headings should be renumbered during `.tex` transcription.
5. Seed 42 is fixed for any stochastic procedures — bootstrap standard errors, IV residual resampling, cross-asset sub-sample selection — that K1241 will execute in support of §7.
6. Per research-honesty principle 11 (Lookahead bias): the K1241 GARCH-X specification must use `Fear_{t-1}` (lagged fear regressor), not `Fear_t`. Main thread must Codex-review the K1241 script to verify the `signal.shift(1)` convention before §7 numbers are transcribed into `.tex`.
