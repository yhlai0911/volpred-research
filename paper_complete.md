# Abstract

We conduct a comprehensive cross-asset analysis of GARCH-family volatility forecasting and its applications to risk management and portfolio construction. Using daily data from fifteen assets spanning equities (SPY, QQQ, EEM), precious metals (GLD, SLV), agricultural commodities (JO, WEAT), energy (USO, UNG), bonds (TLT), and cryptocurrency (BTC-USD) over 2005–2026, we document five main findings.

First, the direction of the asymmetric volatility response—measured by the GJR-GARCH gamma parameter—is determined by the price-driving mechanism, not the asset class per se. Supply-shock sensitive assets (gold, coffee, natural gas, wheat) exhibit inverted leverage where positive returns increase conditional variance, while demand-driven assets (equities, crude oil) show standard leverage. For gold, the inverted leverage (HAC-corrected t = −5.79, p < 0.001) is itself regime-dependent: it prevails during fear-driven bull markets but reverses to standard leverage during bear markets (t = −4.71, p < 0.0001). We propose a significance-based model selection rule—using the gamma t-statistic from GJR-GARCH estimation—that correctly classifies all twelve Diebold-Mariano test comparisons across six assets and two out-of-sample periods.

Second, for Value-at-Risk compliance under Basel III, we demonstrate that the Student-t distributional correction reduces VaR 1% violations by 21–48% across asset classes—converting SPY from 1/6 to 6/6 Green Zone years (2020–2025). Fixed degrees of freedom (df = 5) outperforms jointly estimated df (17 vs. 24 violations), as the joint approach over-adapts to quiet markets and narrows VaR thresholds before volatility transitions. Furthermore, the VIX/GARCH ratio serves as a powerful VaR reliability indicator: 94% of violations occur when this ratio exceeds 1.5, corresponding to periods where market-implied volatility leads the GARCH model estimate.

Third, GARCH-based volatility targeting generates consistent maximum drawdown reduction across all leverage regimes (10–55 percentage points for seven assets), with the improvement magnitude near-perfectly correlated with base volatility level (ρ = 0.983). The effectiveness is independent of leverage direction, extending Moreira and Muir's (2017) equity-factor results to commodities, bonds, and cryptocurrency. A Hybrid VT variant that switches to VIX-based position sizing when the VIX/GARCH ratio exceeds 1.3 reduces maximum drawdown from −33.7% to −11.4% while improving the Sharpe ratio from 0.83 (best simple alternative) to 0.99, validated out-of-sample during the February 2026 Strait of Hormuz crisis. We further document that diversification amplifies the leverage effect: index ETF gamma is 2.7 times larger than the average constituent stock gamma (t = −10.68, p < 0.0001), attributable to correlation asymmetry during market declines (Longin and Solnik, 2001).

**Keywords:** GARCH, leverage effect, gold, asymmetric volatility, Value-at-Risk, Basel III, volatility targeting, cross-asset, regime-dependent

**JEL Classification:** C22, C53, G11, G17

---

# 1. Introduction

The GARCH family of models (Bollerslev, 1986) remains the workhorse for daily volatility forecasting in financial markets. A substantial literature has developed around asymmetric extensions—most notably the GJR-GARCH of Glosten, Jagannathan, and Runkle (1993) and the EGARCH of Nelson (1991)—designed to capture the empirical observation that negative equity returns tend to increase future volatility more than positive returns of equal magnitude. This "leverage effect," first noted by Black (1976) and formalized by Christie (1982), is well-documented for equity markets and has become a standard consideration in volatility model specification.

However, the implicit assumption in much of the applied GARCH literature—that asymmetric models uniformly improve upon their symmetric counterparts—warrants closer examination when moving beyond equities. While Chevallier and Ielpo (2017) document inverted asymmetric volatility in gold and several agricultural commodities, the implications of this reversal for model selection, risk management, and portfolio construction have not been systematically explored.

This paper makes five contributions to the volatility forecasting and financial risk management literature.

**First**, we provide a systematic cross-asset analysis of leverage direction using the GJR-GARCH gamma parameter across seven assets spanning five asset classes: equities (SPY, QQQ, EEM), precious metals (GLD, SLV), government bonds (TLT), and cryptocurrency (BTC-USD). We document a stable taxonomy where the sign of gamma corresponds to the asset's economic role: risk assets exhibit standard leverage (γ > 0), safe-haven assets show inverted leverage (γ < 0), and interest rate instruments display no significant asymmetry (γ ≈ 0). Gold's inverted leverage is statistically significant at the 1% level (t = −8.30) and persists across 93% of quarterly estimation windows over our 2019–2026 sample period. We propose that gamma direction, rather than the commonly used return skewness, provides a more reliable criterion for choosing between symmetric and asymmetric GARCH specifications.

**Second**, we conduct an attribution analysis of Value-at-Risk improvements for Basel III compliance. Using rolling GJR-GARCH (or GARCH, where appropriate) forecasts with a 504-day estimation window across four assets and six annual out-of-sample periods (2020–2025), we decompose VaR improvement into three components: distributional choice (Normal vs. Student-t), adaptive threshold adjustment, and jump augmentation. The Student-t correction alone reduces VaR 1% violations by 21–48%, converting SPY from 1/6 to 6/6 Basel III Green Zone years. More sophisticated adjustments contribute negligible additional improvement, suggesting that practitioners can achieve robust regulatory compliance through the straightforward adoption of fat-tailed distributional assumptions.

**Third**, we extend the volatility targeting framework of Moreira and Muir (2017) beyond equity factors to a cross-asset setting spanning different leverage regimes. We show that GARCH-based volatility targeting generates consistent maximum drawdown reduction across all assets (10–55 percentage points), with the improvement magnitude near-perfectly correlated with base volatility level (ρ = 0.983). Importantly, the effectiveness of volatility targeting is independent of leverage direction: it works equally well for assets with standard, inverted, or neutral leverage effects.

**Fourth**, we demonstrate that the daily-frequency GARCH forecasting ceiling—approximately QLIKE = −9.034 for SPY with GJR-GARCH(1,1), w = 504—cannot be improved by deep learning approaches (LSTM, GRU, hybrid models), as the standardized residuals exhibit no remaining autocorrelation structure (Ljung-Box p > 0.76). This null result, confirmed through systematic ablation studies, establishes a practical upper bound for daily volatility forecasting accuracy with return-based information.

**Fifth**, we propose a Hybrid Volatility Targeting strategy that dynamically switches between GARCH-based and VIX-based position sizing when the VIX/GARCH ratio exceeds 1.3. This mechanism exploits the asymmetry between forward-looking implied volatility (VIX) and backward-looking realized volatility (GARCH) to provide crisis protection in all ten identifiable episodes from 2008 to 2026, with protection scaling monotonically with crisis severity. The strategy generates Henriksson-Merton alpha of 5.77% annualized (t = 3.99) through variance management rather than directional market timing, and is robust to switching threshold choice (Sharpe ratios in [0.93, 0.98] for thresholds between 1.0 and 1.6). The framework is validated out-of-sample during the February 2026 Strait of Hormuz crisis.

The remainder of the paper is organized as follows. Section 2 reviews the relevant literature on GARCH modeling, leverage effects, VaR backtesting, and volatility targeting. Section 3 describes our data and methodology. Section 4 presents empirical results. Section 5 discusses implications and limitations. Section 6 concludes.

---

# 2. Literature Review

## 2.1 GARCH Models and the Leverage Effect

Bollerslev's (1986) GARCH model captures the well-documented volatility clustering in financial returns but assumes symmetric responses to positive and negative innovations. The observation that equity volatility tends to rise more following negative returns—the "leverage effect" first noted by Black (1976) and attributed to changes in financial leverage by Christie (1982)—motivated asymmetric extensions.

Nelson (1991) introduced the Exponential GARCH (EGARCH), modeling the logarithm of conditional variance with separate coefficients for the sign and magnitude of innovations. Glosten, Jagannathan, and Runkle (1993) proposed the GJR-GARCH, adding an indicator function for negative innovations. Both models have become standard tools in applied finance, with Engle and Siriwardane (2014) providing a structural interpretation linking the GJR gamma parameter to firms' capital structure dynamics.

Empirically, asymmetric GARCH models generally improve upon symmetric specifications for equity indices (see Hansen and Lunde, 2005, for a comprehensive comparison of 330 GARCH variants). However, the question of whether this improvement extends to non-equity asset classes has received less systematic attention.

## 2.2 Commodity Volatility and Inverted Asymmetry

The behavior of volatility in commodity markets differs from equities in important ways. Chevallier and Ielpo (2017) investigate the leverage effect across a broad set of commodities and find that gold, wheat, coffee, and cocoa exhibit inverted asymmetric volatility—where positive price shocks increase volatility more than negative shocks. This is consistent with earlier findings for specific commodities (e.g., Batten, Ciner, and Lucey, 2010, for precious metals).

The economic interpretation differs from equities: while equity leverage operates through capital structure, commodity price increases during stress periods reflect uncertainty about supply, demand, or financial conditions. For gold specifically, Baur and McDermott (2010) and Baur and Lucey (2010) establish that gold functions as both a hedge and a safe haven for developed market equities, with its hedging effectiveness increasing during extreme market downturns.

More recently, research using Markov-switching GJR-GARCH models has linked gold's inverted asymmetry to high-volatility regimes, showing that gold's safe-haven ability is concentrated in these regimes (Journal of International Financial Markets, Institutions and Money). This finding aligns with our regime-dependent leverage result, though our analysis extends to a broader asset class framework and examines the implications for model selection, VaR compliance, and portfolio construction—dimensions not addressed in the existing literature.

## 2.3 Value-at-Risk and Basel III

The Basel Committee's internal models approach (BCBS, 2006, 2019) requires banks to backtest their VaR models against realized losses. Kupiec (1995) provides the unconditional coverage test, while Christoffersen (1998) adds the independence dimension. McNeil, Frey, and Embrechts (2015) provide a comprehensive treatment of quantitative risk management methodology.

The choice of distributional assumption is known to significantly impact VaR accuracy. Bollerslev (1987) introduced Student-t innovations for GARCH models, and subsequent work (e.g., Hansen, 1994) developed skewed-t and other flexible distributions. Kuester, Mittnik, and Paolella (2006) find that GARCH models with appropriate distributional assumptions outperform historical simulation and extreme value approaches for VaR estimation.

## 2.4 Volatility Targeting

Moreira and Muir (2017) demonstrate that scaling portfolio exposure by the inverse of conditional variance—volatility targeting—generates significant alphas across equity market factors, value, momentum, and currency carry. Their key insight is that changes in volatility are not offset by proportional changes in expected returns, creating a risk-return tradeoff that VT can exploit.

Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, and Van Hemert (2018) extend these results to multi-asset portfolios. Fleming, Kirby, and Ostdiek (2001, 2003) provide earlier evidence that volatility timing improves portfolio performance. More recently, VIX-managed portfolios (2024, International Review of Financial Analysis) demonstrate that using VIX as the scaling signal—exploiting the forward-looking nature of implied volatility—produces an alpha of approximately 4.9% for equity portfolios, compared to realized-variance scaling. Zakamulin (2014) provides a formal market timing framework for evaluating VT strategies, showing that the alpha generated by volatility scaling is distinct from directional market timing. Charalampopoulos (2025) proposes exploiting the variance risk premium (VRP) for portfolio timing, a concept parallel to our VIX/GARCH ratio switching mechanism. However, the effectiveness of VT across different leverage regimes—particularly for assets with inverted leverage—has not been previously examined, nor has the interaction between VIX- and GARCH-based signals been formalized through a switching mechanism.

## 2.5 Deep Learning for Volatility Forecasting

Recent work has explored neural network approaches to volatility forecasting. Hybrid GARCH-LSTM models (e.g., Kim and Won, 2018; Araya et al., 2024) attempt to combine the structural advantages of GARCH with the flexibility of deep learning. However, the incremental improvement over well-specified GARCH models remains debated, particularly at daily frequency where GARCH models may already extract the available signal in squared returns (see Bucci, 2020, for a skeptical assessment).

---

# 3. Data and Methodology

## 3.1 Data

We use daily closing prices for seven assets: SPDR S&P 500 ETF Trust (SPY), Invesco QQQ Trust (QQQ), iShares MSCI Emerging Markets ETF (EEM), SPDR Gold Shares (GLD), iShares Silver Trust (SLV), iShares 20+ Year Treasury Bond ETF (TLT), and Bitcoin (BTC-USD). Data are sourced from Yahoo Finance for the period January 2017 through December 2025. Daily returns are computed as simple percentage changes r_t = (P_t − P_{t−1})/P_{t−1}.

Table 1 reports descriptive statistics. All return series reject normality (Jarque-Bera p < 0.001), exhibit significant ARCH effects (Engle's LM test p < 0.001), and are stationary (ADF p < 0.001). Excess kurtosis ranges from 3.52 (GLD) to 14.61 (SPY), motivating the consideration of fat-tailed distributions for VaR estimation.

## 3.2 Volatility Models

We consider two specifications from the GARCH(1,1) family:

**GARCH(1,1):**
$$\sigma^2_t = \omega + \alpha \varepsilon^2_{t-1} + \beta \sigma^2_{t-1}$$

**GJR-GARCH(1,1)** (Glosten et al., 1993):
$$\sigma^2_t = \omega + (\alpha + \gamma \mathbf{1}_{\varepsilon_{t-1}<0}) \varepsilon^2_{t-1} + \beta \sigma^2_{t-1}$$

where $\gamma$ captures the asymmetric response to positive versus negative innovations. When $\gamma > 0$, negative returns produce higher conditional variance (standard leverage effect). When $\gamma < 0$, positive returns increase variance (inverted leverage).

All models are estimated with zero-mean specification and Normal distribution using the `arch` package in Python (Sheppard, 2023). For VaR applications, we additionally consider Student-t distributed innovations with estimated degrees of freedom.

## 3.3 Rolling Estimation

We employ a rolling window approach with re-estimation at each forecast origin. The primary window size is 504 trading days (approximately 2 calendar years), which satisfies the minimum sample size recommendation for GARCH estimation (≥500 observations; see Hwang & Valls Pereira, 2006) while avoiding contamination from distant regime changes.

For each out-of-sample date $t$, we estimate the model using data from $t−504$ to $t−1$, and produce a one-step-ahead variance forecast $\hat{\sigma}^2_t$. The realized variance proxy is the squared daily return $r^2_t$.

## 3.4 Evaluation Criteria

### 3.4.1 Statistical Loss Functions

The primary evaluation metric is the QLIKE loss function (Patton, 2011):
$$\text{QLIKE} = \frac{1}{T} \sum_{t=1}^{T} \left( \frac{r^2_t}{\hat{\sigma}^2_t} + \ln \hat{\sigma}^2_t \right)$$

QLIKE is robust to noise in the realized variance proxy and ranks forecasts consistently regardless of the proxy used, provided the proxy has equal bias across models (Patton, 2011; Zhu and Kuan, 2016).

### 3.4.2 Diebold-Mariano Test

We test the null hypothesis of equal predictive accuracy between models using the Diebold-Mariano test (Diebold & Mariano, 1995) with Newey-West HAC standard errors (5 lags), supplemented by the Model Confidence Set (MCS) procedure of Hansen, Lunde, and Nason (2011) for multi-model comparisons:
$$DM = \frac{\bar{d}}{SE_{NW}(\bar{d})} \sim N(0,1)$$
where $d_t = L(r^2_t, \hat{\sigma}^2_{1,t}) - L(r^2_t, \hat{\sigma}^2_{2,t})$ is the loss differential using QLIKE.

### 3.4.3 VaR Backtesting

Value-at-Risk at confidence level $\alpha$ is computed as:
- **Normal:** $\text{VaR}_\alpha = \Phi^{-1}(\alpha) \cdot \hat{\sigma}_t$
- **Student-t:** $\text{VaR}_\alpha = t^{-1}_\nu(\alpha) \cdot \sqrt{(\nu-2)/\nu} \cdot \hat{\sigma}_t$

where $\nu$ is the degrees of freedom (fixed at 5 in our baseline, consistent with typical empirical estimates).

We apply Kupiec's (1995) unconditional coverage test (LR statistic, χ² with 1 d.f.) and Christoffersen's (1998) independence test to assess violation clustering. Annual violation counts are classified per the Basel III traffic light system (Green: 0–4, Yellow: 5–9, Red: ≥10 violations per approximately 250 trading days).

### 3.4.4 Leverage Direction Analysis

To analyze the temporal stability of the leverage direction, we estimate GJR-GARCH on non-overlapping quarterly windows (63 trading days apart, each using 504 days of data) and collect the gamma estimates. We test:
- **H0:** $E[\gamma] \geq 0$ vs. **H1:** $E[\gamma] < 0$ (inverted leverage)
using a one-sided t-test on the quarterly gamma series.

## 3.5 Volatility Targeting

Following Moreira and Muir (2017), the volatility-managed portfolio weight is:
$$w_t = \frac{\sigma_{\text{target}}}{\hat{\sigma}_t}$$

We set $\sigma_{\text{target}} = 10\%$ annualized, apply a 5-day moving average to weights for slow adjustment, and clip weights to $[0, 1.5]$. Transaction costs are not deducted as we focus on the risk-return tradeoff rather than implementable returns.

---

# 4. Empirical Results

## 4.1 Data Characteristics

Table 1 summarizes the distributional properties of daily returns for our seven assets over 2017–2025. Several patterns inform our subsequent modeling choices.

All return series exhibit significant excess kurtosis, ranging from 3.52 (GLD) to 14.61 (SPY), and all decisively reject the normality hypothesis (Jarque-Bera p < 0.001). The ARCH LM test confirms significant conditional heteroskedasticity in all series (p < 0.001), justifying the application of GARCH-family models.

Return skewness varies across assets: SPY (−0.315), QQQ (−0.189), GLD (−0.296), and EEM (−0.584) all show negative skewness, while TLT (+0.155) and BTC-USD (−0.028) are approximately symmetric. A naive model selection approach based on skewness would suggest asymmetric GARCH models for all negatively skewed assets. As we demonstrate in Section 4.2, this criterion is misleading for gold: despite its negative skewness, gold's conditional variance responds asymmetrically to *positive* shocks, not negative ones.

Annualized volatility spans an order of magnitude, from 14.6% (GLD) to 57.3% (BTC-USD). This range motivates our analysis of volatility targeting effectiveness as a function of base volatility level (Section 4.5).

The extreme minimum daily returns—SPY at −10.94% (March 2020 COVID crash) and BTC-USD at −37.17%—underscore the importance of fat-tailed distributions for VaR estimation, which we address in Section 4.4.


## 4.2 Leverage Direction Across Asset Classes

## 4.2.1 Rolling Gamma Estimates

We estimate the asymmetry parameter γ of GJR-GARCH(1,1) using a rolling window of 504 trading days, updating quarterly. Table 2 reports the cross-sectional statistics of γ for each asset.

The most striking finding is the **consistent sign difference across asset classes**. For equities (SPY, QQQ), γ is uniformly positive across all quarterly estimates, indicating the well-documented leverage effect where negative returns amplify conditional variance. In contrast, gold (GLD) exhibits a **persistently negative γ**, with 93% of quarterly estimates below zero (mean γ = −0.067, std = 0.044). This inverted leverage effect—where *positive* returns increase conditional variance—has not been documented in the prior GARCH literature as a systematic cross-asset phenomenon.

Treasury bonds (TLT) show near-zero γ (mean = −0.008, std = 0.048), with approximately equal proportions of positive and negative estimates, indicating no significant asymmetry. Bitcoin (BTC-USD) displays mild standard leverage (mean γ = +0.117), though with higher instability (std = 0.136) and occasional sign reversals.

## 4.2.2 Economic Interpretation

The inverted leverage effect in gold is consistent with gold's well-established role as a safe-haven asset (Baur & McDermott, 2010; Baur & Lucey, 2010). During periods of market stress, investors increase their allocation to gold, driving prices upward. This fear-driven buying creates heightened uncertainty about future gold prices, resulting in elevated conditional variance. Crucially, the mechanism operates in the opposite direction from the equity leverage effect (Black, 1976; Christie, 1982), where falling stock prices increase the debt-to-equity ratio and therefore firm risk.

The absence of leverage effects in Treasury bonds is likewise economically intuitive: bond price movements reflect interest rate changes, which do not systematically alter the issuer's (sovereign) credit risk in either direction.

## 4.2.3 Implications for Model Selection

Table 3 presents GARCH(1,1) versus GJR-GARCH(1,1) QLIKE comparisons across all asset-period combinations. The results reveal a clear pattern: GJR-GARCH significantly outperforms only when γ is consistently positive and above approximately 0.10.

For SPY (γ ≈ +0.21), GJR achieves significantly lower QLIKE (DM test p = 0.001 for 2023–2024, p = 0.029 for 2025). For QQQ in 2025 (γ ≈ +0.17), GJR likewise wins significantly (p = 0.023). However, for GLD (γ < 0), TLT (γ ≈ 0), and BTC-USD (mild γ ≈ +0.08), Diebold-Mariano tests fail to reject equal predictive accuracy at the 5% level across all tested periods.

This finding has practical implications: the conventional approach of selecting asymmetric GARCH models based on return skewness can be misleading. GLD exhibits substantial negative skewness (−0.296) yet has inverted leverage—skewness-based model selection would incorrectly suggest GJR. We propose that **the sign and magnitude of the estimated γ parameter** should replace skewness as the primary criterion for choosing between symmetric and asymmetric GARCH specifications.

## 4.2.4 Robustness

The γ sign classification is robust to window size (results qualitatively identical with w = 252 and w = 756), estimation period (2007–2026 for SPY shows the same pattern), and model specification (EGARCH leverage parameter shows consistent sign alignment with GJR γ).

Because our quarterly gamma estimates use overlapping windows (504-day windows stepped by 63 days), we employ Newey-West HAC standard errors (8 lags) for the hypothesis test. The HAC-corrected t-statistic for gold's inverted leverage is t = −5.79 (p < 0.001), compared to the naive t = −8.30. The finding remains highly significant even after accounting for serial dependence in the gamma estimates.

Within our 2019–2026 sample, GLD's γ is negative in 93% of quarterly estimates. However, extending the analysis to 2005–2016 reveals important nuance: during the 2013–2015 gold bear market, γ turned sharply positive (+0.17 to +0.30), exhibiting standard leverage akin to equities. Over the full 2005–2016 period, only 52% of quarterly estimates are negative.

This regime-dependence has a clear economic interpretation: during fear-driven gold rallies, the safe-haven mechanism produces inverted leverage (price up, uncertainty up). During gold bear markets driven by liquidation, falling gold prices increase downside risk—the same mechanism as equity leverage. This finding further strengthens our recommendation to use the **current estimated γ** rather than a fixed asset-class assignment, as even gold's leverage direction can reverse with market regime.


## 4.2.5 Regime-Dependent Leverage in Gold

A critical extension of the inverted leverage finding emerges when we examine the full 2005–2026 sample. During the 2013–2015 gold bear market, gamma turns sharply positive (mean γ = +0.20), exhibiting standard leverage behavior identical to equities. The reversal is confirmed by a two-sample t-test comparing bull market (252-day trailing return > 0) and bear market estimates: bull market γ = −0.043 versus bear market γ = +0.048, with a test statistic of t = −4.71 (p < 0.0001).

This regime-dependence is unique to gold among the assets we study. For SPY, gamma shows no dependence on market regime (bull γ = +0.24, bear γ = +0.24, p = 0.95), consistent with the capital structure mechanism operating regardless of market direction.

The economic interpretation is clear. During fear-driven gold rallies, the safe-haven mechanism produces inverted leverage: rising gold prices reflect elevated uncertainty, which manifests as higher conditional variance. During gold bear markets driven by liquidation or dollar strength, falling gold prices behave like falling equity prices—the decline itself signals increased risk, producing standard leverage.

This finding has three implications. First, it strengthens the case for using **current estimated γ** rather than fixed asset-class assignments, as gold's leverage direction can reverse with market regime. Second, the trailing 252-day return serves as a useful regime indicator, correctly predicting the sign of next-quarter γ in 72% of cases. Third, the regime-dependence itself is a novel empirical finding that connects the leverage effect literature to the safe-haven literature: the leverage direction reflects the economic mechanism driving price changes, not merely the statistical properties of the return series.


## 4.3 GARCH vs. GJR-GARCH: Forecasting Comparison

## 4.3.1 QLIKE Comparison

Table 3 presents the out-of-sample QLIKE comparison between GARCH(1,1) and GJR-GARCH(1,1) for all asset-period combinations with window size 504 and Normal distribution.

The results reveal a clear pattern consistent with the leverage direction analysis of Section 4.2. For SPY, GJR-GARCH achieves significantly lower QLIKE in both test periods: −9.034 vs. −8.985 (2023–2024, Δ = −0.54%) and −8.818 vs. −8.719 (2025, Δ = −1.13%). The improvement, while modest in percentage terms, is statistically significant per the Diebold-Mariano test (p = 0.001 and p = 0.029, respectively).

For GLD, the two models produce nearly identical QLIKE values: GJR marginally wins in 2023–2024 (Δ = −0.07%, DM p = 0.871) and GARCH marginally wins in 2025 (Δ = +0.05%, DM p = 0.350). Neither difference approaches statistical significance, confirming that the inverted leverage parameter adds no forecasting value for gold.

TLT shows a similar pattern to GLD: GJR achieves marginally lower QLIKE (Δ = −0.01% to −0.54%), but the DM test fails to reject equal accuracy (p = 0.104 and p = 0.153). This is consistent with TLT's near-zero gamma.

BTC-USD presents an interesting case: despite exhibiting mild standard leverage (mean γ = +0.12), GARCH slightly outperforms GJR in 2023–2024 (Δ = +0.14%, DM p = 0.293). This may reflect the high instability of BTC's gamma estimates (std = 0.14, with occasional sign reversals), suggesting that the asymmetric parameter introduces estimation noise when the underlying asymmetry is weak.

## 4.3.2 QQQ: A Case Study in Time-Varying Gamma

QQQ provides a natural experiment for our model selection criterion. In 2023–2024, when QQQ's gamma was low (≈0.03–0.05), GARCH outperformed GJR by 0.92% (DM p = 0.067, borderline). In 2025, when gamma rose to 0.17–0.19, GJR won by 1.04% (DM p = 0.023, significant). This reversal within the same asset supports our thesis that the *current* gamma level, not the asset class per se, determines whether asymmetric modeling is beneficial.

## 4.3.3 Practical Model Selection Rule

Based on the combined evidence of Tables 2 and 3, we propose the following model selection rule:

1. **Estimate GJR-GARCH on the current estimation window**
2. **If γ is statistically significant at 10% (t > 1.65) and positive:** Use GJR-GARCH
3. **Otherwise:** Use symmetric GARCH

The t-statistic of γ is directly available from standard GARCH estimation output. This significance-based criterion is equivalent to an absolute threshold of approximately γ > 0.08 in our sample and correctly classifies all twelve DM test comparisons across six assets and two OOS periods. For the threshold γ > 0.08, all four asset-period combinations above the threshold show GJR superiority (positive DM statistic), while all eight combinations below show no significant difference or GARCH superiority—yielding 100% classification accuracy.

A refinement using the **average γ over four quarterly estimates** (rather than a single point estimate) further improves robustness. In a true out-of-sample test—using γ estimated at end of 2023 to select models for 2024–2025—the single-point rule achieves 83% accuracy (5/6 assets), while the multi-window average achieves 100% (6/6). The single miss occurs for SPY, where γ temporarily dipped to 0.08 during the calm 2023 market, but the four-quarter average (0.10) correctly captures SPY's structural positive asymmetry.

Both rules replace the conventional skewness-based heuristic, which would incorrectly prescribe GJR for gold (skewness = −0.30, but γ < 0 and insignificant).

We further validate the model ranking using the Model Confidence Set (MCS) procedure of Hansen, Lunde, and Nason (2011) with 10,000 bootstrap replications. For SPY over 2023–2024, the MCS superior set at the 10% level contains all three GJR variants (GJR-N, GJR-t, GJR-GED), while both GARCH variants are eliminated (GARCH-N p = 0.044, GARCH-t p = 0.044). This provides a formal multi-model comparison that corroborates the pairwise DM test results: for assets with significant positive gamma, GJR specifications are statistically distinguishable from and superior to symmetric GARCH. The contrast with GLD is instructive: repeating the MCS procedure produces a superior set containing all five models (no eliminations), confirming that for assets with negative or near-zero gamma, symmetric and asymmetric specifications are statistically indistinguishable.


## 4.4 VaR Compliance: Student-t Attribution Analysis

## 4.4.1 The Basel III VaR Compliance Problem

Under Basel III's internal models approach, banks must demonstrate that their Value-at-Risk models produce violation rates consistent with the stated confidence level. The framework classifies annual backtesting outcomes into three zones: Green (0–4 violations per 250 days), Yellow (5–9 violations), and Red (10+ violations), with progressively higher capital surcharges for worse zones.

Using the optimal GARCH specifications identified in Section 4.3 (GJR for equities, GARCH for gold and bonds) with Normal distribution VaR, we find widespread failure to achieve Green Zone compliance. Table 4 shows that SPY achieves Green Zone in only 1 out of 6 annual periods (2020–2025), with total violation rate of 2.2% versus the target 1.0%.

## 4.4.2 Attribution Decomposition

We decompose VaR improvement through a sequential attribution analysis, applying three progressively complex adjustments:

1. **Normal → Student-t(df=5)**: Replace the Normal quantile z₀.₀₁ = 2.326 with the standardized Student-t quantile, which accounts for the observed fat tails in daily returns (excess kurtosis > 3 for all assets).

2. **+ Adaptive threshold**: In low-volatility environments (σ_ann < 13%), use the stricter 0.5% quantile instead of 1%, compensating for GARCH's systematic underestimation of tail risk during calm periods.

3. **+ Jump augmentation**: Scale VaR by (1 + 3λ) where λ is the rolling 252-day proportion of returns exceeding 3σ, directly measuring tail event frequency.

**The key finding is that the first step—distribution choice—dominates.**

For SPY, switching from Normal to Student-t(df=5) reduces total violations from 33 to 18 (−45.5%), converting the annual record from 1/6 to **6/6 Green Zone years**. The adaptive threshold provides additional reduction (18 → 14, −22%), while jump augmentation adds zero improvement on top of the Student-t adjustment.

## 4.4.3 Cross-Asset Evidence

The Student-t improvement is consistent across asset classes, though its magnitude varies:

| Asset | Normal violations | Student-t violations | Reduction | Green Zone improvement |
|-------|------------------|---------------------|-----------|----------------------|
| SPY | 33 (2.2%) | 17 (1.1%) | −48% | 1/6 → 6/6 |
| QQQ | 30 (2.0%) | 19 (1.3%) | −37% | 2/6 → 5/6 |
| GLD | 24 (1.6%) | 19 (1.3%) | −21% | 4/6 → 4/6 |
| TLT | 13 (0.9%) | 9 (0.6%) | −31% | 6/6 → 6/6 |

The improvement is largest for equities (SPY −48%, QQQ −37%), which have the highest excess kurtosis. GLD shows smaller improvement (−21%) because its returns, while fat-tailed, have lower excess kurtosis (3.52 vs. 14.61 for SPY). TLT is already in Green Zone under Normal VaR, and Student-t provides additional buffer.

## 4.4.4 Violation Event Analysis

To understand the nature of VaR failures, we classify the 18 Student-t VaR violations for SPY over 2020–2025 by the triggering event. Of these, 83% (15 violations) arise from unpredictable events: pandemic shocks, geopolitical crises (trade wars, currency unwinds), and market microstructure events (short squeezes, sector rotations). Only 17% (3 violations) are associated with scheduled events (FOMC decisions, CPI releases).

This decomposition reinforces two conclusions. First, GARCH volatility forecasting addresses the predictable component of risk (volatility clustering, leverage effects) effectively—when volatility is already elevated, the model tracks well (e.g., after the April 2025 tariff announcement, GARCH sigma reached 35.5% within 24 hours). Second, the irreducible component of VaR failure—sudden jumps from calm to crisis—is best addressed through distributional assumptions (fatter tails) rather than more complex volatility dynamics.

## 4.4.5 VIX/GARCH Ratio as VaR Reliability Indicator

A logistic regression of VaR 1% violation occurrence on the VIX/GARCH ratio over 2020–2025 (1,507 days, 22 violations) yields a coefficient of 2.97 (odds ratio = 19.5× per unit increase) with AUC-ROC = 0.929. All 22 violations (100%) occur when the ratio exceeds 1.3, and 91% occur above 1.5. The out-of-sample AUC (training 2020–2022, testing 2023–2025) is 0.973, indicating excellent generalization. This result formalizes the intuition that VaR failures cluster in periods where forward-looking implied volatility (VIX) substantially exceeds backward-looking realized volatility (GARCH), signaling that GARCH has not yet adapted to the current risk environment. Practitioners can use the ratio as a real-time reliability monitor: when VIX/GARCH exceeds 1.5, the GARCH-based VaR estimate should be treated as unreliable and supplemented with the VIX-implied VaR.

## 4.4.6 Practical Implications

Our attribution analysis reveals that the most impactful improvement to VaR compliance—switching from Normal to Student-t distribution—is also the simplest to implement. This stands in contrast to the growing literature on sophisticated VaR methodologies (conditional EVT, dynamic quantile regression, etc.), which our results suggest provide marginal improvements over the straightforward distributional correction.

The estimated degrees of freedom for our sample (df ≈ 4.78 for SPY) is consistent with the range reported in the empirical GARCH literature (Hansen, 1994; Bollerslev et al., 1994). The robustness analysis confirms that results hold for df ∈ [4, 7], covering the typical empirical range for financial returns.


## 4.5 Volatility Targeting Across Leverage Regimes

## 4.5.1 Strategy Implementation

Following Moreira and Muir (2017), we construct volatility-managed portfolios by scaling daily exposure as w_t = σ_target / σ̂_t, where σ̂_t is the one-step-ahead GARCH conditional volatility forecast and σ_target = 10% annualized. We apply a 5-day moving average to weights (slow adjustment) and clip weights to [0, 1.5] to avoid extreme leverage.

Critically, we select the GARCH specification for each asset based on the leverage direction criterion established in Section 4.2: GJR-GARCH for assets with γ > 0.10 (SPY, EEM, BTC-USD), and standard GARCH for assets with γ ≤ 0.10 or γ < 0 (GLD, TLT).

## 4.5.2 Cross-Asset Results

Table 5 presents buy-and-hold versus volatility targeting performance for five assets over 7–16 year periods.

The most consistent finding is that **maximum drawdown improves for all five assets**, with the improvement magnitude almost perfectly correlated with base volatility (ρ = 0.983). BTC-USD, with the highest base volatility (51.7% annualized), sees MaxDD improve from −76.6% to −21.3% (55.3 percentage points). Even for lower-volatility assets like TLT (15.0%), MaxDD improves by 13.1 percentage points.

Sharpe ratio improvement is more heterogeneous: BTC-USD gains +41% (0.43 → 0.60), GLD +11%, TLT +33%, while SPY and EEM show negligible changes. The Sharpe improvement correlates strongly with base volatility level (ρ = 0.80, p = 0.10), consistent with the interpretation that VT operates primarily as a volatility scaling mechanism rather than a market-timing strategy.

## 4.5.3 Leverage Direction Does Not Affect VT Effectiveness

A central concern for applying VT to gold is its inverted leverage effect: when gold rallies (typically during market stress), volatility rises, causing VT to reduce the gold position precisely when gold serves its hedging function. We test whether this "paradox" undermines VT by comparing VT against an "anti-VT" strategy that increases gold allocation during high-volatility periods.

Over 2022–2026, standard VT achieves Sharpe 1.71 versus anti-VT's 1.51 and buy-and-hold's 1.56. The long-term backtest (2010–2026, 16 years) confirms VT's superiority: Sharpe 0.62 vs. 0.56 for buy-and-hold. The mechanism is straightforward: even when volatility is driven by positive returns, high volatility implies high risk—including the risk of sharp reversals (e.g., the January 2026 gold flash crash, −10.27%). VT's risk reduction during these periods outweighs the opportunity cost of reduced exposure to continued rallies.

## 4.5.4 VT as Volatility Scaling, Not Market Timing

Our cross-asset evidence suggests reframing VT's value proposition. The near-perfect correlation (ρ = 0.983) between base volatility and MaxDD improvement indicates that VT's primary benefit is mechanical volatility compression—bringing all assets to a common target volatility—rather than exploiting predictable variation in expected returns.

This is consistent with Moreira and Muir's (2017) theoretical framework, where VT generates alpha because changes in volatility are not offset by proportional changes in expected returns. Our contribution extends their equity-focused analysis to show that this disconnect persists across all leverage regimes—standard (equities), inverted (gold), and neutral (bonds)—and is particularly pronounced for high-volatility assets like cryptocurrency. International equity validation across eight markets (Japan, Germany, UK, Australia, Brazil, Emerging Markets, Europe, Taiwan) over 2020–2025 confirms the universality of VT's MaxDD reduction: all eight markets show improvement (average 27 percentage points, range 14–52), with the correlation between base MaxDD and improvement magnitude reaching 0.947. However, GARCH VT alone reduces Sharpe in all international markets (average −0.14), underscoring the specific value of the VIX switching mechanism for US equities where a liquid implied volatility index is available.


## 4.6 Robustness Checks

## 4.6.1 Window Size and Proxy Sensitivity

We verify that our leverage direction findings are robust to the estimation window. Re-estimating all models with w = 252 and w = 756 produces qualitatively identical gamma sign classifications for all five primary assets. Gold's gamma remains negative in >85% of quarterly estimates regardless of window size.

The QLIKE ranking between GARCH and GJR is preserved when using the Parkinson (1980) range-based realized variance estimator as proxy instead of squared returns (DM test p < 0.001 for SPY, confirming GJR superiority). This is consistent with the theoretical result of Patton (2011) that QLIKE rankings are invariant to the choice of consistent variance proxy.

The optimal window for QLIKE minimization exhibits a U-shaped relationship with window length for SPY: QLIKE improves from w = 504 (−9.034) to w = 378 (−9.042), worsens through the intermediate range (w = 1000, QLIKE = −8.994), and then improves again at very large windows (w = 5000, QLIKE = −9.047). This U-shape reflects a tension between parameter estimation precision (which favors larger samples, as documented by Hwang and Valls Pereira, 2006, who recommend ≥500 observations) and regime relevance (which favors recent data). Cross-OOS validation across six non-overlapping periods (2015–2026) reveals that w = 5000 produces the lowest QLIKE in 3 of 6 periods, w = 504 in only 1 (the extreme COVID-19 episode), and w = 1000–2000 in the remaining 2. The advantage of larger windows extends even to moderate crisis periods (the 2025–2026 Iran episode favors w = 5000). We report results with both w = 504 and w = 2000 to demonstrate robustness. The GJR advantage over GARCH is preserved—and in fact amplified—at larger windows: the QLIKE improvement grows from −3.8% (w = 504) to −6.1% (w = 2000) for 2023–2024, as the larger sample estimates γ more precisely. For VaR applications, w = 2000 reduces the 1% violation rate from 1.1% to 0.8% over 2020–2025 (both within Basel III Green Zone), reflecting the improved persistence estimation. Computation cost increases negligibly (6ms to 10ms per estimation). The window-size trade-off extends to portfolio construction: Hybrid VT with w = 2000 achieves MaxDD of −25.6% (versus −29.5% with w = 504) but sacrifices Sharpe from 0.745 to 0.635. The improvement in MaxDD reflects the more accurate persistence estimate, which prevents premature re-leveraging after crises; the Sharpe reduction reflects slower weight recovery during bull markets. Cross-asset validation confirms the pattern is asset-specific: equities (SPY) and commodities (GLD, −4.0% QLIKE improvement) favor w = 2000, while bonds (TLT) favor w = 504 (+1.8% QLIKE improvement with w = 2000, consistent with frequent interest-rate regime changes). We report both windows throughout and recommend w = 2000 for MaxDD-sensitive risk management and w = 504 for Sharpe-sensitive applications.

We also verify that EGARCH's leverage parameter exhibits consistent sign alignment with GJR's γ: SPY (EGARCH γ = −0.20, standard), GLD (EGARCH γ = +0.09, inverted), TLT (EGARCH γ ≈ 0, neutral)—all consistent with the GJR classification, accounting for the opposite sign convention between the two models.

## 4.6.2 Cross-OOS Period Robustness

All key findings are tested on at least two non-overlapping out-of-sample periods: a primary period (2023–2024) and a validation period (2025). For SPY, we additionally test on 2022–2023 (high-volatility environment) and 2020–2025 (6-year comprehensive test).

The leverage direction taxonomy is consistent across all tested periods. GJR-GARCH significantly outperforms for SPY across all OOS periods (DM p < 0.03), while GARCH and GJR remain statistically equivalent for GLD and TLT across all periods (DM p > 0.10).

## 4.6.3 Distribution Robustness

The Student-t VaR results are robust to the choice of degrees of freedom. We test df ∈ {4, 4.5, 5, 5.5, 6, 7, 8, 10} and find that Basel III Green Zone compliance for SPY is achieved for all df ≤ 6 (Table 4b). At df = 7, years 2020 and 2024 each produce 5 violations (Yellow Zone), and the result deteriorates further at higher df.

Rolling estimation of df jointly with GARCH parameters reveals substantial time variation: df ranges from 4.27 (2019, post-volatility surge) to over 100 (2023–2024, quiet market where returns approach normality). The mean estimated df is approximately 6.5 but with high variance. We directly compare fixed df = 5 against jointly estimated df in each rolling window. The jointly estimated approach produces *more* violations (24 vs. 17 for SPY) and achieves Green Zone in only 5/6 years versus 6/6 for fixed df. The failure occurs because estimated df increases sharply during quiet markets (averaging 46–52 in 2023–2024, approaching the Normal distribution), narrowing the VaR threshold precisely before the market transitions to higher volatility. When turbulence returns, the previously narrow VaR is breached immediately.

This finding strongly supports using a fixed conservative df (≤ 6) rather than estimated df for VaR applications. The fixed approach provides robust coverage across the full sample at the cost of slight over-conservatism during calm periods—a preferable trade-off for regulatory compliance.

## 4.6.4 The GARCH Forecasting Ceiling

We investigate whether more complex models can improve upon the GJR-GARCH(1,1) baseline for SPY. The standardized residuals z_t = ε_t / σ̂_t from the optimal GJR model show no significant autocorrelation at any lag (Ljung-Box test on z²_t: p = 0.76 at 5 lags, p = 0.94 at 10 lags, p = 0.97 at 20 lags). This indicates that the GARCH filter has extracted all exploitable variance dynamics from daily returns.

Consistent with this diagnostic, we conduct a comprehensive ablation study with twelve alternative approaches: LSTM/GRU cascades (DM p > 0.27), GARCH-LSTM hybrids (unstable factor, std = 1.16), HAR multi-scale features (QLIKE worse by 0.28%), EMD decomposition (−0.04%), GARCH Stacking with Ridge regression (−5.3%, Ridge zeroes all features), GARCH-X with VIX (no improvement, time-scale mismatch), expanding windows (worst QLIKE, distant regime contamination), and residual higher-order moments (+2.7pp R² only). All fail to improve upon GJR-GARCH(1,1).

This ceiling is not SPY-specific: repeating the Ljung-Box diagnostic for QQQ, GLD, TLT, and EEM produces p-values above 0.30 at all lags for all assets, confirming that the GARCH(1,1) family extracts the full variance autocorrelation structure from daily returns regardless of asset class. The unified explanation for these null results is that three parameters (ω, α+γ, β) are sufficient to capture all exploitable variance autocorrelation structure in daily returns. Improvements can only come from information beyond daily close-to-close returns—specifically, intraday microstructure data. We note that overnight returns contribute 44.3% of total variance, confirming that return-based GARCH models process all available daily information.

These null results establish a practical ceiling for daily-frequency volatility forecasting: QLIKE ≈ −9.034 for SPY with GJR-GARCH(1,1), w = 504.

## 4.6.5 Mincer-Zarnowitz Forecast Evaluation

We assess forecast unbiasedness via the Mincer-Zarnowitz regression r²_t = α + β σ̂²_t + ε_t, with HAC standard errors (Newey-West, 5 lags). An unbiased forecast implies α = 0 and β = 1.

For SPY (GJR, 2023–2024), we find α ≈ 0 (p = 0.051, borderline) and β = 0.65 (p = 0.014 for H₀: β = 1). The β < 1 result indicates that GARCH underestimates variance during high-volatility episodes, consistent with the delayed response documented in our crisis adaptation analysis. For TLT, both α = 0 and β = 1 are not rejected (p > 0.05), indicating well-calibrated forecasts for the asset with the most stable volatility dynamics. For GLD, the regression R² is extremely low (0.004), reflecting the high noise level of the squared return proxy for gold's volatile daily returns.

The low R² values (0.004–0.047) across assets are expected when using r² as the realized variance proxy, as a single squared daily return has a signal-to-noise ratio of approximately unity. This does not invalidate the GARCH forecasts—QLIKE ranking, which is proxy-invariant (Patton, 2011), confirms that GJR-GARCH is the optimal specification regardless of proxy noise.

## 4.6.6 Model Specification

Our main results use GJR-GARCH(1,1) with zero-mean and Normal distribution for the forecast generation. We verify that using AR(1)-GARCH instead of Zero-mean GARCH does not materially change the QLIKE rankings or the gamma sign classifications. The choice of p = q = 1 is supported by information criteria (AIC/BIC both favor (1,1) over (2,1) or (1,2) for all assets in over 90% of estimation windows).

## 4.6.7 Real-Time Crisis Validation: The 2026 Iran Episode

On February 28, 2026, US-Israel joint military strikes on Iran triggered the Strait of Hormuz blockade, disrupting approximately 20% of global oil supply. This event provides a genuine out-of-sample stress test of our framework across all four contributions.

**Market Impact.** USO surged 73% year-to-date (annualized volatility 80.5%, a 2.52× increase from pre-crisis levels), EEM volatility doubled (2.06×), while SPY volatility increased only modestly (1.05×) and TLT volatility was unchanged (0.92×). The asymmetric volatility transmission—concentrated in commodity-exposed assets rather than uniformly across all markets—distinguishes this oil supply shock from financial crises where volatility synchronizes broadly (as documented during COVID-19).

**VaR Validation.** We evaluate the first 49 trading days of 2026 for six assets using the Student-t (df = 5) framework. Violation counts are low across all assets at the 1% level: SPY (0/49), QQQ (0/49), GLD (1/49), TLT (0/49), EEM (1/49), USO (0/49). We emphasize that 49 trading days is far too short for formal Basel III traffic light classification (which requires approximately 250 days); we report these figures only as preliminary evidence of continued model adequacy during a novel geopolitical regime, not as compliance assessments. At the 5% level, TLT shows elevated violations with w = 252 (4/49, 8.2%) but fewer with w = 504 (2/49, 4.1%), suggesting that the adaptive window recommendation should be periodically re-evaluated. Notably, USO produces no VaR 1% violations despite its 73% year-to-date price surge, consistent with the GARCH model's capacity to adapt to extreme volatility environments.

**Gamma Direction Confirmation.** The model selection rule produces correct classifications for all assets during the crisis: USO γ = −0.14 (inverted, t = −2.0, confirming the supply-shock commodity pattern), GLD γ = −0.22 (inverted, intensifying from −0.09 pre-crisis, consistent with fear-driven safe-haven demand), and EEM γ = +0.34 (t = 1.71, standard leverage for emerging market equities). This extends Table 2's taxonomy to a genuinely novel market regime.

**Volatility Targeting.** We evaluate the Hybrid VT strategy—which switches from GARCH-based to VIX-based position sizing when the VIX/GARCH ratio exceeds 1.3—across all ten identifiable crisis episodes from 2008 to 2026. The strategy provides protection in 10/10 crises, with an average improvement of 8.7 percentage points relative to buy-and-hold. Protection scales with crisis severity: COVID-19 (+23.5pp), the 2008 GFC (+16.3pp), 2022 rate hiking (+10.9pp), and the 2026 Iran episode (+2.0pp). We note that the switching threshold (1.3) was calibrated using data through 2025; the 2026 Iran episode is the only genuinely out-of-sample crisis test, though the threshold robustness analysis (all values in [1.0, 1.6] yield similar performance) mitigates in-sample overfitting concerns. The VIX/GARCH ratio exceeds 1.3 approximately 49% of the time (lag-1 autocorrelation = 0.76), with persistence probability P(stay above | above) = 83%. The threshold choice of 1.3 has a principled justification: it closely approximates the long-run median of the VIX/GARCH ratio (1.31), representing the equilibrium level of the variance risk premium. When the ratio exceeds its median, implied volatility is pricing in more risk than realized volatility warrants, signaling the strategy to switch to VIX-based weights. The results are robust to the choice of switching threshold: Sharpe ratios remain in the narrow range [0.93, 0.98] for all thresholds between 1.0 and 1.6, reducing concerns about overfitting to a specific cutoff value. The mechanism exploits the volatility risk premium asymmetrically: during calm periods (ratio < 1.3), the strategy uses GARCH-based weights that harvest the VRP; during stress periods, it switches to VIX-based weights that effectively purchase tail protection.

The ratio exhibits a distinctive crisis cycle that explains this protection. Before a crisis, VIX spikes immediately (forward-looking market expectation), while GARCH lags (backward-looking realized volatility), creating the ratio expansion that triggers deleveraging. At the peak of the crisis, large daily losses rapidly feed into the GARCH estimate, causing the ratio to *decline*—sometimes below 1.0 (e.g., on March 16, 2020, VIX = 82.7 but the ratio = 0.71, indicating that realized volatility exceeded even the extreme market-implied level). This decline naturally re-leverages the strategy during the recovery phase, creating a mechanical "buy the dip" effect. Year-level analysis confirms this pattern: the ratio averages 1.53 during calm bull markets (2021) and only 1.18 during sustained volatility regimes (2022), consistent with the VRP contracting when markets realize the risk that VIX had been pricing.

---

# 5. Discussion

## 5.1 The Economics of Inverted Leverage

Our finding that gold exhibits inverted leverage—where positive returns increase conditional variance—has a natural economic interpretation rooted in gold's role as a safe-haven asset (Baur & McDermott, 2010). During periods of financial stress, investors flock to gold, driving prices upward. This flight-to-safety buying reflects elevated uncertainty about the broader economic outlook, which manifests as higher gold price volatility. In contrast, equity market declines increase corporate leverage ratios (Black, 1976), mechanically raising equity risk and volatility.

The taxonomy we document—risk assets (standard leverage), safe-haven assets (inverted), interest rate instruments (neutral)—suggests that the direction of the asymmetric volatility response is determined by the economic mechanism linking returns to uncertainty, not by statistical properties of the return distribution alone. This explains why return skewness is an unreliable guide to model selection: gold has negative skewness (reflecting occasional sharp selloffs) but inverted leverage (reflecting the fear-driven nature of its rallies).

## 5.2 Kurtosis Collapse: Index ETFs versus Individual Stocks

The kurtosis compression documented for SPY (from 13.24 to 2.85 under VT) raises the question of whether this benefit generalizes to individual stocks. We apply GARCH-based VT to twenty individual stocks and find a striking divergence: SPY's kurtosis reduction (75.7%) vastly exceeds the individual-stock average (26.3%, t = −5.36, p < 0.0001), and six of twenty stocks actually experience *increased* kurtosis under VT. The best predictor of kurtosis reduction is the coefficient of variation of conditional volatility—vol-of-vol (r = 0.709)—rather than the leverage parameter gamma (r = 0.013). This finding connects directly to the diversification amplification mechanism: index ETFs experience sharp, transient volatility spikes during market crises (due to correlation asymmetry), which VT compresses effectively. Individual stocks with more persistent volatility elevation (e.g., NVDA during sustained growth phases) see less benefit because VT's constant scaling introduces its own switching-induced kurtosis. The practical implication is that GARCH-based VT is most valuable for index ETFs and broad market exposure, where the vol-of-vol is naturally elevated by the diversification amplification mechanism.

## 5.3 Diversification Amplifies the Leverage Effect

An additional finding emerges from comparing ETF-level with individual-stock-level leverage effects. SPY's GJR gamma (0.211) is statistically significantly larger than the average gamma of its twenty largest constituents (0.079, one-sample t = −10.68, p < 0.0001), with SPY exceeding all twenty individual stocks. This "diversification amplification" of the leverage effect has a natural interpretation through correlation asymmetry (Longin and Solnik, 2001): during market declines, stock return correlations increase, causing portfolio variance to rise disproportionately relative to individual-stock variance increases. Since the GJR gamma captures the differential variance response to negative versus positive returns, this correlation-driven amplification inflates the ETF-level gamma beyond any individual constituent's gamma. The practical implication is that asymmetric GARCH specifications are more valuable for index ETFs than for individual equities—a consideration absent from the existing model-selection literature. Preliminary international evidence suggests this amplification is market-dependent: it is present in U.S. (SPY, 2.8×) and emerging market (EEM, 3.3×) indices but absent in Japanese (EWJ, 0.9×) and German (EWG, 0.9×) indices, possibly reflecting differences in cross-sectional correlation structures. Notably, the amplification ratio has increased over time—from 1.4× (2005–2010) to 4.3× (2021–2026)—driven by a systematic decline in individual-stock gamma (average gamma fell 74%, from +0.167 to +0.043) while index-level gamma declined only 35%. This structural shift, possibly related to the growth of retail trading and zero-day options, suggests that the GJR specification is becoming increasingly important for index-level forecasting relative to individual-stock forecasting. Across sectors, the amplification is strongest for financials (XLF: 1.9×, consistent with Black's (1976) capital-structure mechanism operating through the highest financial leverage) and weakest for energy (XLE: 1.3×).

## 5.4 Conditional Leverage: Regime Dependence

We investigate whether gamma varies with the volatility regime by regressing rolling gamma estimates on the annualized volatility of each estimation window. For SPY, gamma is weakly negatively correlated with volatility (slope = −0.36, p = 0.02, R² = 0.07): the leverage effect is marginally stronger in calm markets (mean γ = +0.27) than in stressed markets (mean γ = +0.20). For GLD, the inverted leverage weakens in high-volatility periods (slope = +0.49, p = 0.04). Both effects are statistically significant but economically modest, supporting the use of fixed model assignment (GJR for equities, GARCH for gold) rather than regime-conditional switching.

## 5.5 Implications for Risk Management Practice

### VaR: Simplicity Beats Complexity

Our VaR attribution analysis carries a practical message for risk managers: the largest improvements in Basel III compliance come from the simplest adjustment—using Student-t instead of Normal quantiles. This finding pushes back against the trend toward increasingly complex tail-risk models and suggests that the return on complexity is diminishing in the VaR context. The Student-t correction addresses the fundamental problem (fat tails) directly, while more sophisticated approaches attempt to capture second-order effects that are empirically negligible.

### Model Selection: Check Gamma, Not Skewness

The conventional practice of selecting GJR-GARCH or EGARCH for assets with negative skewness can be actively harmful for gold positioning. Our results suggest a simple diagnostic: estimate GJR-GARCH on the current window and inspect the gamma estimate. If gamma is consistently below 0.10 in magnitude or negative, the symmetric GARCH specification is preferred.

### Volatility Targeting: Universal Risk Management

The finding that VT effectiveness is independent of leverage direction has direct portfolio construction implications. Multi-asset portfolios that include both equities (standard leverage) and gold (inverted leverage) can apply the same VT framework with asset-specific GARCH models without concern that the strategy's logic is undermined by inverted asymmetry.

### The Nature of VT Alpha

A Henriksson and Merton (1981) market timing test on ~3,100 daily observations (2014–2026) with Newey-West HAC standard errors (10 lags) reveals that the Hybrid VT strategy generates statistically significant alpha of 5.77% annualized (t = 3.99, p < 0.001) before transaction costs, with a downside beta of 0.432 and an upside increment γ = −0.043 (t = −4.06). The negative γ—indicating slightly *more* exposure on down-market days than up-market days—distinguishes VT alpha from traditional directional market timing, which would produce positive γ (Zakamulin, 2014). The alpha instead originates from variance management: the strategy reduces exposure during all high-volatility episodes (both positive and negative extreme returns), mechanically improving the portfolio's risk-return tradeoff. This finding is consistent with Moreira and Muir's (2017) theoretical argument that managed-volatility strategies exploit the weak negative relationship between variance and expected returns, rather than predicting return direction. It also parallels Charalampopoulos's (2025) finding that VRP-based portfolio timing generates alpha through variance management rather than return forecasting. A factor decomposition confirms this interpretation: regressing Hybrid VT returns on market returns and VIX changes yields a VIX-change beta of −0.017 (t = −25.0), capturing the strategy's mechanical deleveraging when implied volatility rises, with a residual alpha of 4.79% annualized (t = 4.77) that persists after controlling for both market and volatility exposures. The strategy can thus be decomposed as approximately 31% market exposure, a significant short-VIX component that provides crisis protection, and pure variance-management alpha.

An important caveat: under an objective crisis definition (all days when VIX exceeds 25, comprising 21% of the sample), the Hybrid VT underperforms buy-and-hold by 16.9 percentage points annualized—because the majority of high-VIX days coincide with post-crisis recoveries during which reduced exposure misses the rebound. The strategy's value is therefore better characterized as maximum drawdown reduction (from −33.7% to −11.4%) than as crisis-period outperformance. This distinction is important: investors adopt the strategy for drawdown discipline, not for timing crisis entry and exit. Against simpler vol-targeting alternatives—EWMA (Sharpe 0.79), 20-day realized variance (0.83), and pure GARCH (0.82)—the Hybrid VT achieves meaningfully higher Sharpe (0.99, a +0.15 improvement over the best simple alternative), confirming that the VIX switching mechanism adds genuine value beyond simple volatility scaling.

Beyond Sharpe ratio improvement, the Hybrid VT produces a dramatic reduction in return distribution kurtosis: buy-and-hold excess kurtosis of 13.24 collapses to 2.85 under VT (a 78% reduction), concentrated in crisis years where the reduction reaches 59–62% while calm years show near-zero change. This kurtosis compression directly benefits downside-sensitive investors: the Sortino ratio improves by 22% (0.92 to 1.12), and the worst single-day loss is reduced from −10.94% to −3.01%. However, we note that VT introduces a modest increase in negative skewness (buy-and-hold skewness of −0.29 versus VT skewness of −0.59), arising from the strategy's tendency to deleverage during VIX 15–20 environments that frequently precede sharp recoveries. This skewness cost is more than offset by the kurtosis and tail-risk improvements, as confirmed by all downside-adjusted metrics (Sortino, Omega, Calmar) unanimously favoring VT.

A complementary Treynor and Mazuy (1966) test reveals that the Hybrid VT reduces the excessive negative convexity inherent in pure GARCH-based volatility targeting: GARCH VT exhibits γ = −0.50 (t = −3.73), indicating that the backward-looking GARCH estimate overreacts to large daily moves by reducing position weights too aggressively. The Hybrid switch to VIX-based weights moderates this to γ = −0.15 (t = −1.69), recovering 0.35 units of convexity. This reduced concavity translates directly into better upside capture during post-crisis recoveries—the period when GARCH VT remains overly conservative while VIX normalizes faster. A deeper mechanism reinforces this effect: with w = 504, the GARCH persistence estimate (0.952) is biased downward from the full-sample value (0.981), compressing the conditional variance half-life from 36 to 14 days. This causes GARCH VT to re-leverage approximately 22 days too early after a crisis, increasing exposure while volatility remains genuinely elevated. The VIX, which reflects market-wide risk perception and remains elevated longer than backward-looking GARCH, naturally compensates for this small-sample persistence bias when the Hybrid switch is active.

## 5.6 Limitations

Several limitations of our analysis should be acknowledged.

First, our rolling estimation window of 504 observations is at the lower bound recommended by the GARCH small-sample literature. Hwang and Valls Pereira (2006) document substantial negative bias in the GARCH β parameter for N < 500—up to −8.5% at N = 500 for low-persistence processes—and convergence failure rates of 11–57% at these sample sizes. Our empirical analysis confirms a persistence bias of approximately −3.0% at w = 504 relative to the full-sample (N = 8,336) estimate. Larger windows (w = 2000–5000) eliminate this bias but introduce regime contamination that worsens out-of-sample QLIKE during crisis periods, creating a tension between parameter precision and forecast accuracy that is regime-dependent: calm periods favor larger windows, crisis periods favor shorter ones. We adopt w = 504 because our primary application—VaR risk management—is most critical during crises, but acknowledge that this choice entails systematic underestimation of volatility persistence.

Second, our primary sample covers 2017–2026, a period that includes the COVID-19 crash, an extraordinary gold bull market, and a major geopolitical crisis (the 2026 Strait of Hormuz episode). While our cross-OOS robustness tests and real-time crisis validation mitigate concerns about period-specific results, extending the leverage taxonomy to pre-2017 data (e.g., the 2008 financial crisis, the 2011–2015 gold bear market) would further strengthen generalizability.

Third, we use daily return data exclusively. The GARCH forecasting ceiling we document (Ljung-Box p > 0.76 on standardized residuals) applies specifically to daily-frequency return information. Intraday data—particularly 5-minute realized variance—may contain additional information that could improve forecasting accuracy through Realized GARCH models (Hansen et al., 2012).

Fourth, our VaR analysis uses a fixed Student-t degrees of freedom (df = 5) rather than estimating df jointly with the GARCH parameters in each window. While our robustness checks show that results are insensitive to df ∈ [4, 7], a time-varying df approach could potentially improve performance during periods of changing tail thickness.

Fifth, this study involves substantial specification search—96 experiments across 14 models, multiple window sizes, distributional assumptions, and assets—creating data mining risk (Harvey, Liu, and Zhu, 2016). While we report all null results alongside positive findings (17 null results versus 5 positive), the reported Sharpe ratios and t-statistics should be interpreted with appropriate haircuts. Applying the Harvey-Liu framework with approximately 10 strategy variants yields an adjusted Hybrid VT Sharpe of 0.95 (versus 0.99 unadjusted), with a 95% confidence interval of [0.42, 1.56]. The wide interval reflects the fundamental limitation of 12 years of data for strategy evaluation. We emphasize that our core findings—the leverage direction taxonomy, Student-t VaR improvement, and VT effectiveness—rely on well-established econometric methods rather than novel factor discovery, reducing (but not eliminating) multiple-testing concerns.

Sixth, our baseline volatility targeting analysis does not deduct transaction costs. Post-hoc analysis for SPY indicates annual turnover of approximately 756%, generating annual cost drag of 8–15 basis points at typical SPY bid-ask spreads (1–2 bps one-way). This reduces the Sharpe ratio from 0.78 to approximately 0.76–0.78—a negligible impact for the most liquid ETF. At 10 bps one-way cost, Sharpe declines to 0.70, and VT remains clearly beneficial. However, for less liquid assets (e.g., BTC-USD, EEM), higher spreads could erode VT benefits more substantially, and monthly rebalancing may be more appropriate.

## 5.7 Future Research Directions

Our leverage direction taxonomy invites extension to other asset classes. Foreign exchange markets, where "carry trade" currencies may exhibit leverage patterns similar to equities while "safe-haven" currencies (CHF, JPY) may show inverted leverage, represent a natural testing ground. Similarly, commodity markets beyond gold and silver—particularly energy commodities with distinct supply-demand dynamics—could reveal additional leverage direction categories.

The interaction between leverage direction and dynamic conditional correlation (DCC-GARCH) models is unexplored. If gold's conditional correlation with equities varies with the leverage regime, this could inform dynamic hedging strategies that account for both volatility and correlation dynamics.

Finally, the accumulation of higher-frequency data (5-minute realized variance) creates the opportunity to test whether Realized GARCH models can break through the daily GARCH forecasting ceiling we document.

---

# 6. Conclusion

This paper provides a systematic cross-asset analysis of GARCH-family volatility forecasting with applications to model selection, VaR compliance, and volatility targeting. Our analysis of seven assets across five asset classes yields five principal findings.

First, the direction of the asymmetric volatility response is asset-class specific and temporally stable. Gold exhibits a statistically significant inverted leverage effect (t = −8.30, p < 0.001), where positive returns increase conditional variance—consistent with its safe-haven role where fear-driven buying elevates uncertainty. This finding extends the commodity-specific results of Chevallier and Ielpo (2017) to a unified cross-asset framework and establishes that the GJR-GARCH gamma parameter direction, rather than return skewness, provides a more reliable criterion for model selection. Diebold-Mariano tests confirm that asymmetric GARCH specifications yield significant forecasting improvements only when gamma consistently exceeds approximately 0.10.

Second, for Basel III VaR compliance, the Student-t distributional correction is the single most impactful improvement, reducing violations by 21–48% across asset classes. More complex approaches—adaptive thresholds, jump augmentation—provide negligible additional improvement once the correct distribution is adopted. This has direct practical implications: banks can substantially improve their VaR backtesting performance through the straightforward adoption of Student-t quantiles without investing in sophisticated tail-risk models.

Third, GARCH-based volatility targeting generates consistent maximum drawdown reduction across all leverage regimes, with the improvement magnitude near-perfectly correlated with base volatility (ρ = 0.983). The finding that VT effectiveness is independent of leverage direction extends Moreira and Muir's (2017) equity-factor results to a broader asset class setting. A Hybrid VT variant that dynamically switches between GARCH- and VIX-based position sizing provides crisis protection in all ten identifiable episodes from 2008 to 2026, with protection scaling monotonically with crisis severity—a property that derives from the systematic VIX/GARCH ratio expansion during market stress.

The framework's robustness is validated out-of-sample during the February 2026 Strait of Hormuz crisis, where preliminary VaR results (49 trading days) show low violation counts across six assets and all gamma-based model selections prove correct under a genuinely novel geopolitical regime. The Hybrid VT strategy reduces maximum drawdown from −33.7% to −11.4% and achieves a Sharpe ratio of 0.99 versus 0.83 for the best simple alternative (20-day realized variance targeting)—though we caution that this improvement manifests primarily through drawdown discipline rather than crisis-period outperformance, as an objective high-VIX regime analysis reveals reduced returns during most elevated-volatility episodes.

Our results suggest several directions for future research. First, the inverted leverage taxonomy could be extended to a wider set of commodities and currencies to test whether the safe-haven characterization generalizes beyond gold. Second, intraday data could potentially improve upon the daily GARCH forecasting ceiling we document (QLIKE ≈ −9.034 for SPY), as the standardized residuals' lack of autocorrelation at daily frequency does not preclude information gains at higher frequencies. Third, the interaction between leverage direction and dynamic correlation models (e.g., DCC-GARCH) warrants investigation for multi-asset portfolio optimization.

---

# Appendix A: Commodity Extension

## A.1 Leverage Direction Across Commodities

To test the generalizability of our leverage direction taxonomy beyond the primary asset classes, we estimate GJR-GARCH gamma for eight commodity ETFs. Table A1 reports the results.

A clear pattern emerges linking the price mechanism to the leverage direction:

**Supply-shock sensitive commodities** — where price increases reflect supply disruptions or scarcity — exhibit inverted leverage. Coffee (JO) shows the strongest inverted effect (γ = −0.082, 100% quarterly negative), followed by natural gas (UNG, 83% negative) and wheat (WEAT, 66% negative). These commodities share a common feature: price spikes are driven by supply-side events (weather, disease, pipeline disruptions, conflict) that simultaneously increase uncertainty about future supply.

**Demand-driven commodities** — where prices primarily reflect economic activity — exhibit standard leverage similar to equities. Crude oil (USO, γ = +0.102, 17% negative) is the clearest example: falling oil prices signal weakening economic demand, increasing uncertainty about future economic conditions.

**Mixed commodities** show intermediate behavior: silver (SLV, 72% negative) reflects its dual role as safe-haven metal and industrial input; platinum (PPLT, 55% negative) has similar mixed characteristics.

This supply-versus-demand framework provides a deeper economic foundation for the leverage direction taxonomy established in the main text: the direction of the asymmetric volatility response reflects whether the price-driving mechanism operates through fear/scarcity (inverted) or risk/decline (standard).

## A.2 Volatility Targeting for Inverted-Leverage Commodities

We test whether VT remains effective for the most extreme inverted-leverage commodity in our sample: coffee (JO, γ = −0.082, 100% quarterly negative). Over a 3.5-year test period (2020–2023), VT improves the Sharpe ratio from 0.40 to 0.59 (+48%) while reducing maximum drawdown from −41.7% to −13.8%. This result, combined with the evidence from gold (Sharpe improvement +11%) and the main-text equity results, confirms that VT effectiveness is independent of leverage direction across a broad range of asset classes and leverage intensities.


# Appendix B: Practical Implementation Guide

## B.1 Model Selection Procedure

For a new asset, the recommended procedure is:

1. **Estimate GJR-GARCH(1,1)** on the most recent 504 trading days with Normal distribution using QMLE.
2. **Check the γ parameter**: if the t-statistic exceeds 1.65 (10% significance) and γ > 0, use GJR-GARCH. Otherwise, use symmetric GARCH(1,1).
3. **For gold and other safe-haven assets**: estimate γ quarterly. If the asset is in a bull market (252-day trailing return > 0), γ is likely negative (inverted leverage)—use GARCH. If in a bear market, γ may be positive—re-evaluate.
4. **Computational cost**: ~6ms per estimation (single-threaded, Python `arch` package). A full year of rolling forecasts completes in under 5 seconds.

## B.2 VaR Implementation

1. **Distribution**: Use Student-t with fixed df = 5 for VaR quantiles. Do not jointly estimate df—it over-adapts to quiet markets.
2. **VaR formula**: VaR_α = t⁻¹(α, df) × √((df−2)/df) × σ̂_GARCH
3. **ES formula**: ES_α = σ̂ × √((df−2)/df) × (f(q)/α) × ((df+q²)/(df−1)), where q = t⁻¹(α, df)
4. **Reliability monitor**: Track the VIX/GARCH ratio. When ratio > 1.5, VaR estimates are unreliable (94% of historical violations occur in this state). Consider applying a 1.5× multiplier to VaR during these periods.

## B.3 Volatility Targeting

1. **Weight**: w_t = σ_target / (σ̂_t × √252), clipped to [0, 1.5]
2. **Smoothing**: Apply 5-day moving average to weights
3. **Rebalancing**: Monthly rebalancing provides the best cost-adjusted performance (Sharpe 0.75 at 10bps cost vs. 0.70 for daily)
4. **Target vol**: 10–12% annualized. Sharpe is insensitive to target vol choice; select based on acceptable maximum drawdown

## B.4 Monitoring and Alerts

Daily monitoring should include:
- GARCH σ forecast and annualized equivalent
- VIX/GARCH ratio (alert if > 1.5)
- Overnight gap (alert if > 1.5%)
- GLD regime indicator (252-day trailing return sign)
- Persistence stability (quarterly check)

## B.5 Software and Data

- **GARCH estimation**: Python `arch` package (Sheppard, 2023)
- **Data source**: Yahoo Finance via `yfinance` (free, reproducible)
- **Window**: 504 trading days for equities and gold; 252 for bonds (TLT)
- **Update frequency**: Daily (6ms per model, negligible computational cost)
