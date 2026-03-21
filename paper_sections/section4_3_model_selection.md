# 4.3 GARCH vs. GJR-GARCH: Forecasting Comparison

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

We validate the rule's statistical properties via Monte Carlo simulation (100 replications × 3 DGPs, N = 504). When the true DGP has standard leverage (γ = +0.20), the rule correctly selects GJR in 95% of cases. When the true DGP has no leverage (γ = 0), the rule correctly recommends GARCH in 91% of cases (9% false positive rate). For inverted leverage (γ = −0.10), the rule achieves 100% correct classification. The overall accuracy of 95% (286/300) confirms that the t-statistic threshold of 1.65 is well-calibrated for this application.

Both rules replace the conventional skewness-based heuristic, which would incorrectly prescribe GJR for gold (skewness = −0.30, but γ < 0 and insignificant).
