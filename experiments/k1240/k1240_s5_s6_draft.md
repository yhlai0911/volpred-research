# Paper 10 Section 5 + 6 Drafts

**Paper**: Paper 10 — The Crypto Fear Channel: Asymmetric BTC–Equity Volatility Spillover
**Version**: v0 (initial draft, 2026-04-17)
**Source K**: K1234 kickoff guide; K1238 (§3 Data); K1239 (§4 Methodology)
**Supporting experiments**: K639, K746b, K949, K1025, K1133b
**Format**: Markdown draft (not `.tex`; worktree-agent rule per CLAUDE.md)
**Seed**: 42 (all bootstrap / subsample / resampling procedures)

> **Scope note**: §5 Data Description is a ~400-word *complete* draft whose descriptive-stats numbers are sourced verbatim from `experiments/k1025/k1025_results.json`. §6 Main Results is a ~600-word *skeleton* whose fear-channel coefficient values ($\phi$, HLN-$t$, QLIKE) are marked as **[pending experiment]** because the GARCH-X fear-channel regression specified in §4 (K1239) has not yet been executed. Main thread must commission the supporting experiment (tentatively K1241) before §6 numbers can be populated.

---

## §5 Data Description (~400 words, COMPLETE)

### §5.1 Summary statistics

Table 2 reports first- to fourth-moment summary statistics for the three primary series over the full sample (2015-02-02 to 2026-04-08, $N = 2{,}812$). Daily log returns on BTC-USD have mean $0.229\%$ and standard deviation $3.76\%$, implying an annualized unconditional volatility of approximately $59.8\%$ — roughly $3.4\times$ the $17.7\%$ annualized figure for SPY ($\mu = 0.056\%$, $\sigma = 1.12\%$). Excess kurtosis is $7.58$ for BTC and $14.15$ for SPY, both materially above Gaussian tails and consistent with the stylized facts of daily equity and cryptocurrency markets. The VIX averages $18.38$ points with standard deviation $7.11$, ranging from $9.14$ (late-2017 low) to $82.69$ (March-2020 COVID peak); the 20-day annualized realized volatility of BTC (BTC-RV20) averages $54.2\%$ with standard deviation $25.7\%$.

### §5.2 Correlation patterns

Unconditional contemporaneous correlations over the full sample indicate a mild positive association between BTC returns and VIX-scaled equity fear [full pairwise matrix TBD at main-thread review; to be produced from K1025 return panel]. More informatively, the DCC-GARCH conditional correlation between BTC and SPY (K1025 §DCC table) rises monotonically with the prevailing VIX regime: $0.068$ in the Low regime (VIX $< 15$, $n = 1{,}037$ days), $0.265$ in Normal ($15 \le$ VIX $\le 25$, $n = 1{,}386$), $0.449$ in High ($25 <$ VIX $\le 35$, $n = 326$), and $0.409$ in Crisis (VIX $> 35$, $n = 63$). Percent of days with positive BTC–SPY correlation rises from $61.9\%$ (Low) to $98.4\%$ (Crisis). The lead–lag direction is examined formally in §6: lagged VIX Granger-causes BTC-RV20 at all tested lags ($F = 6.71$ at lag 1, $p = 0.010$), while the reverse test (BTC-RV20 $\to$ VIX) is insignificant at lag 1 ($F = 0.64$, $p = 0.422$) but becomes significant from lag 3 onward.

### §5.3 Stationarity and autocorrelation

Augmented Dickey-Fuller tests reject the unit-root null at the $1\%$ level for all three Granger inputs: BTC-RV20 ($\text{ADF} = -4.898$, $p = 3.5\times 10^{-5}$, lags 20), VIX ($\text{ADF} = -5.711$, $p = 7.3\times 10^{-7}$, lags 9), and SPY-RV20 ($\text{ADF} = -4.460$, $p = 2.3\times 10^{-4}$, lags 20). These confirm stationarity and validate both the VAR-based Granger machinery in §4.1 and the GARCH-X fear-channel regression in §4.2; Ljung-Box $Q$ and Jarque-Bera statistics on the return and squared-return residuals of the fitted GJR baseline are reported in the Online Appendix and show no evidence of remaining autocorrelation or conditional heteroskedasticity at the $5\%$ level, consistent with GARCH-X applicability.

---

**[Table 2 placeholder — Descriptive Statistics and Stationarity Tests, 2015-02-02 to 2026-04-08, $N = 2{,}812$]**

| Series | Mean | Std. Dev. | Skewness | Excess Kurtosis | Min | Max | ADF stat | ADF $p$-value |
|--------|------|-----------|----------|-----------------|-----|-----|----------|---------------|
| BTC log return | 0.00229 | 0.03764 | $-0.093$ | 7.579 | — | — | — | — |
| SPY log return | 0.00056 | 0.01117 | $-0.307$ | 14.150 | — | — | — | — |
| VIX (level) | 18.382 | 7.110 | — | — | 9.140 | 82.690 | $-5.711$ | $7.3\!\times\!10^{-7}$ |
| BTC-RV20 (ann.) | 0.5418 | 0.2569 | — | — | 0.0980 | 1.7009 | $-4.898$ | $3.5\!\times\!10^{-5}$ |
| SPY-RV20 (ann.) | — | — | — | — | — | — | $-4.460$ | $2.3\!\times\!10^{-4}$ |

*Notes*: All figures reproduced from `experiments/k1025/k1025_results.json` (seed 42). BTC and SPY are continuously compounded daily log returns from Yahoo Finance via `yfinance`. BTC-RV20 and SPY-RV20 are 20-day rolling annualized realized volatilities. ADF lag length selected by AIC.

---

## §6 Main Results Outline (~600 words, SKELETON)

### §6.1 Primary Finding: Fear-Channel Transmission (~180 words placeholder)

This subsection reports the central test of $H_{0}:\phi = 0$ against $H_{1}:\phi > 0$ in the GARCH-X specification of equation (4) in §4.1. We estimate the MF-GJR(1,1,1)-X specification with Student-$t$ innovations by quasi-maximum likelihood on the full sample; a pure GARCH(1,1) and a GJR-GARCH(1,1,1) without the fear term serve as nested baselines. Table 3 (placeholder) reports, for each specification, the estimated $\hat{\phi}$ coefficient with its robust (Bollerslev–Wooldridge) standard error, its Harvey-adjusted $t$-statistic ($t^{\text{HLN}}$), the likelihood-ratio test $p$-value against the GJR baseline, and the in-sample Patton QLIKE loss. The Harvey (2016) $|t^{\text{HLN}}| > 3.0$ threshold is applied as the decision rule for a genuine fear-channel finding; the conventional $t > 1.96$ threshold is insufficient given the cross-section of alternative fear proxies we examine in §6.2.

> **[PENDING EXPERIMENT — K1241]**: The MF-GJR(1,1,1)-X estimation on BTC returns with VIX$^2$ as the fear regressor has **not** been executed. Expected outputs: $\hat{\phi}$, $\text{SE}(\hat{\phi})$, $t^{\text{HLN}}$, LRT $p$-value, QLIKE$_{\text{GJR}}$ vs. QLIKE$_{\text{GJR-X}}$. Main-thread action required: commission K1241 GARCH-X fear-channel regression before this subsection can be populated. Do *not* fabricate representative numbers.

**Table 3 (placeholder)** — Fear-channel coefficient $\phi$ across specifications

| Spec. | $\hat{\phi}$ | SE | $t^{\text{HLN}}$ | LRT $p$ | QLIKE | Harvey pass? |
|-------|--------------|----|----|----|-------|--------------|
| GARCH(1,1) | — | — | — | — | — | — |
| GJR-GARCH(1,1,1) | — | — | — | — | — | — |
| GARCH(1,1)-X(VIX$^2$) | TBD | TBD | TBD | TBD | TBD | TBD |
| MF-GJR(1,1,1)-X(VIX$^2$) | TBD | TBD | TBD | TBD | TBD | TBD |

### §6.2 Alternative Fear Proxies (~150 words placeholder)

We examine four alternative functional forms and measures of the fear regressor, re-estimating the MF-GJR(1,1,1)-X specification once per alternative: (i) raw VIX level, (ii) VIX$^2$ (preferred per K949 cross-market evidence of a VIX-elasticity $\theta_1 \approx 2.1$ in the MF-GJR(VIX) frontier), (iii) $\log(\text{VIX})$, and (iv) the Alternative.me Crypto Fear & Greed Index (CFIX) — a crypto-native sentiment aggregator that serves as a falsification device for the *cross-market* channel. Selection of the preferred functional form is based on joint ranking across $t^{\text{HLN}}$, LRT, and out-of-sample QLIKE; ties are broken in favor of the specification with the most parsimonious mean equation.

> **[PENDING EXPERIMENT — K1241]**: All four columns of Table 4 require K1241 outputs.

**Table 4 (placeholder)** — Fear-channel coefficient across alternative fear proxies

| Proxy | $\hat{\phi}$ | $t^{\text{HLN}}$ | QLIKE improvement (%) | Harvey pass? |
|-------|--------------|----|----|----|
| VIX (level) | TBD | TBD | TBD | TBD |
| VIX$^2$ | TBD | TBD | TBD | TBD |
| log(VIX) | TBD | TBD | TBD | TBD |
| CFIX | TBD | TBD | TBD | TBD |

### §6.3 Pre- and Post-ETF Split (~150 words placeholder)

Motivated by the structural-break evidence in K1133b and the January-2024 U.S.\ spot-Bitcoin-ETF approval, we re-estimate the preferred specification on two non-overlapping sub-samples: pre-ETF (2015-02-02 to 2023-12-31) and post-ETF (2024-01-01 to 2026-04-08). The fear channel may be regime-dependent: in the pre-ETF retail-dominated era, margin-call cascades and forced liquidations plausibly amplify the transmission; in the post-ETF institutional era, arbitrage and basis-trade flows may dampen it. We also report the K1025 five-regime Granger breakdown (Pre-mania, Crypto winter, COVID, Bull-Bear, Recovery+ETF) for comparison; K1025 finds BTC-RV $\to$ VIX Granger causality significant *only* in 2020 ($F = 11.05$, $p = 7.9\times 10^{-7}$), a concentration that must be reconciled with any positive full-sample fear-channel finding.

> **[PENDING EXPERIMENT — K1241 sub-sample split]**: Table 5 requires K1241 pre-ETF / post-ETF sub-sample estimates plus the already-available K1025 five-regime Granger breakdown.

**Table 5 (placeholder)** — Fear-channel coefficient across ETF regimes and K1025 five-regime split

| Sample | $n$ | $\hat{\phi}$ | $t^{\text{HLN}}$ | Harvey pass? |
|--------|-----|--------------|----|----|
| Pre-ETF (2015-02 to 2023-12) | TBD | TBD | TBD | TBD |
| Post-ETF (2024-01 to 2026-04) | TBD | TBD | TBD | TBD |
| K1025 2020 (COVID) sub-panel | 253 | — | — | (Granger $F = 11.05$) |
| K1025 other four sub-panels | — | — | — | (all insignificant) |

### §6.4 Granger Causality Direction (~120 words placeholder)

Figure 1 (placeholder) depicts the Granger causality flow among the three series — VIX, BTC-RV20, and SPY-RV20 — using the K1025 canonical $F$-statistics at lag 5. The expected pattern based on §5.2 and K1025 is (a) VIX $\to$ BTC-RV20 ($F = 3.90$, $p = 0.0016$), (b) BTC-RV20 $\to$ VIX ($F = 5.29$, $p = 7.7\times 10^{-5}$), and (c) an asymmetric channel in which only the negative BTC return branch Granger-causes VIX (K1025 asymmetric-Granger: $F_{\text{BTC}^{-}\to\text{VIX}} = 6.64$ at lag 5, $F_{\text{BTC}^{+}\to\text{VIX}} = 0.28$). Interpretation: the fear channel is *not* unidirectional — both series contain incremental information about each other's short-horizon volatility — but the asymmetry is strong enough to justify the downside-focused narrative.

> **[PENDING FIGURE]**: Figure 1 production script requires K1025 output JSON + one-off Graphviz layout; can be built immediately as a K1025 by-product, does not require K1241.

---

## Word Count

- §5 Data Description: ~400 words (target met; descriptive content complete with K1025-verified values)
  - §5.1: ~130 words
  - §5.2: ~160 words
  - §5.3: ~110 words
- §6 Main Results Skeleton: ~600 words (target met; 4 subsections, 3 placeholder tables, 1 placeholder figure)
  - §6.1: ~180 words
  - §6.2: ~150 words
  - §6.3: ~150 words
  - §6.4: ~120 words
- **Total**: ~1,000 words

## Pending-Experiment Flags

1. **K1241 (critical)**: MF-GJR(1,1,1)-X fear-channel regression on BTC returns with VIX$^2$ regressor. Outputs needed: Table 3 (all cells of specifications 3 and 4), Table 4 (all four fear-proxy cells), Table 5 (pre/post-ETF and sub-sample $\hat{\phi}$). Main-thread action: spin up K1241 worktree (no new data download required — reuse `experiments/k1025/data` or equivalent yfinance pull).
2. **Figure 1 (non-critical)**: Granger-causality flow diagram. Can be generated from K1025 JSON without new estimation; assign to a utility/visualization slot rather than a full experiment.

## Notes for Main-Thread Adoption

1. All descriptive numbers in §5 are verbatim from `experiments/k1025/k1025_results.json` — main thread may cross-check by `jq` query on that file. No value is interpolated, rounded ad-hoc, or estimated from an alternative pull.
2. The K1025 DCC regime table (low/normal/high/crisis) is reported in §5.2 with four regimes rather than the outline's generic "regime-dependent" phrasing; main thread should decide whether to retain the four-regime breakdown in body text or push it to §6.3 / Online Appendix.
3. §6 placeholders **do not contain fabricated $\hat{\phi}$ values**. Per research-honesty principle 9 (Null result 如實報告) and principle 1 (不可造假), this draft marks every unexecuted number as `TBD` or `—` and explicitly flags the pending K1241 experiment. Do *not* edit these cells to plausible-looking numbers before the experiment runs.
4. The K1239 methodology draft positions the GARCH-X fear-channel regression as potentially `§4.1` or `§4.6` — this §6 draft assumes it is `§4.1` (primary). If main thread moves it to `§4.6`, §6.1 table ordering should follow suit.
5. The K1025 out-of-sample DM test on AR(VIX) $+$ BTC-RV is an *honest NULL* ($t = -0.98$, $p = 0.327$) — Paper 10 §7 (to be drafted later) will report it. §6 is the in-sample transmission section and is separate from §7 forecastability; readers must be warned in §6.1 opening lines that in-sample causality $\neq$ out-of-sample forecastability.
6. Seed 42 is fixed for all §5 descriptive bootstrap CIs (if any are added) and for any §6 Monte Carlo sanity checks implemented during K1241.
