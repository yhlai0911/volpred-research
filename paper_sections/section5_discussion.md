# 5. Discussion

## 5.1 The Economics of Inverted Leverage

Our finding that gold exhibits inverted leverage—where positive returns increase conditional variance—has a natural economic interpretation rooted in gold's role as a safe-haven asset (Baur & McDermott, 2010). During periods of financial stress, investors flock to gold, driving prices upward. This flight-to-safety buying reflects elevated uncertainty about the broader economic outlook, which manifests as higher gold price volatility. In contrast, equity market declines increase corporate leverage ratios (Black, 1976), mechanically raising equity risk and volatility.

The taxonomy we document—risk assets (standard leverage), safe-haven assets (inverted), interest rate instruments (neutral)—suggests that the direction of the asymmetric volatility response is determined by the economic mechanism linking returns to uncertainty, not by statistical properties of the return distribution alone. This explains why return skewness is an unreliable guide to model selection: gold has negative skewness (reflecting occasional sharp selloffs) but inverted leverage (reflecting the fear-driven nature of its rallies).

## 5.2 Conditional Leverage: Regime Dependence

We investigate whether gamma varies with the volatility regime by regressing rolling gamma estimates on the annualized volatility of each estimation window. For SPY, gamma is weakly negatively correlated with volatility (slope = −0.36, p = 0.02, R² = 0.07): the leverage effect is marginally stronger in calm markets (mean γ = +0.27) than in stressed markets (mean γ = +0.20). For GLD, the inverted leverage weakens in high-volatility periods (slope = +0.49, p = 0.04). Both effects are statistically significant but economically modest, supporting the use of fixed model assignment (GJR for equities, GARCH for gold) rather than regime-conditional switching.

## 5.3 Implications for Risk Management Practice

### VaR: Simplicity Beats Complexity

Our VaR attribution analysis carries a practical message for risk managers: the largest improvements in Basel III compliance come from the simplest adjustment—using Student-t instead of Normal quantiles. This finding pushes back against the trend toward increasingly complex tail-risk models and suggests that the return on complexity is diminishing in the VaR context. The Student-t correction addresses the fundamental problem (fat tails) directly, while more sophisticated approaches attempt to capture second-order effects that are empirically negligible.

### Model Selection: Check Gamma, Not Skewness

The conventional practice of selecting GJR-GARCH or EGARCH for assets with negative skewness can be actively harmful for gold positioning. Our results suggest a simple diagnostic: estimate GJR-GARCH on the current window and inspect the gamma estimate. If gamma is consistently below 0.10 in magnitude or negative, the symmetric GARCH specification is preferred.

### Volatility Targeting: Universal Risk Management

The finding that VT effectiveness is independent of leverage direction has direct portfolio construction implications. Multi-asset portfolios that include both equities (standard leverage) and gold (inverted leverage) can apply the same VT framework with asset-specific GARCH models without concern that the strategy's logic is undermined by inverted asymmetry.

## 5.3 Limitations

Several limitations of our analysis should be acknowledged.

First, our sample covers 2017–2025, a period that includes both the COVID-19 crash and an extraordinary gold bull market. While our cross-OOS robustness tests mitigate concerns about period-specific results, extending the analysis to earlier periods (e.g., the 2008 financial crisis, the 2011–2015 gold bear market) would strengthen the generalizability of our findings.

Second, we use daily return data exclusively. The GARCH forecasting ceiling we document (Ljung-Box p > 0.76 on standardized residuals) applies specifically to daily-frequency return information. Intraday data—particularly 5-minute realized variance—may contain additional information that could improve forecasting accuracy through Realized GARCH models (Hansen et al., 2012).

Third, our VaR analysis uses a fixed Student-t degrees of freedom (df = 5) rather than estimating df jointly with the GARCH parameters in each window. While our robustness checks show that results are insensitive to df ∈ [4, 7], a time-varying df approach could potentially improve performance during periods of changing tail thickness.

Fourth, our baseline volatility targeting analysis does not deduct transaction costs. Post-hoc analysis for SPY indicates annual turnover of approximately 756%, generating annual cost drag of 8–15 basis points at typical SPY bid-ask spreads (1–2 bps one-way). This reduces the Sharpe ratio from 0.78 to approximately 0.76–0.78—a negligible impact for the most liquid ETF. At 10 bps one-way cost, Sharpe declines to 0.70, and VT remains clearly beneficial. However, for less liquid assets (e.g., BTC-USD, EEM), higher spreads could erode VT benefits more substantially, and monthly rebalancing may be more appropriate.

## 5.4 Future Research Directions

Our leverage direction taxonomy invites extension to other asset classes. Foreign exchange markets, where "carry trade" currencies may exhibit leverage patterns similar to equities while "safe-haven" currencies (CHF, JPY) may show inverted leverage, represent a natural testing ground. Similarly, commodity markets beyond gold and silver—particularly energy commodities with distinct supply-demand dynamics—could reveal additional leverage direction categories.

The interaction between leverage direction and dynamic conditional correlation (DCC-GARCH) models is unexplored. If gold's conditional correlation with equities varies with the leverage regime, this could inform dynamic hedging strategies that account for both volatility and correlation dynamics.

Finally, the accumulation of higher-frequency data (5-minute realized variance) creates the opportunity to test whether Realized GARCH models can break through the daily GARCH forecasting ceiling we document.
