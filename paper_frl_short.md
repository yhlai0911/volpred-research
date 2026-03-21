# Leverage Direction as a Model Selection Criterion: Cross-Asset Evidence

## Abstract

We document that the sign of the GJR-GARCH gamma parameter—rather than return skewness—provides a reliable criterion for choosing between symmetric and asymmetric GARCH specifications. Analyzing 20 assets across equities, commodities, bonds, and cryptocurrency (2005–2025), we find that the gamma direction is asset-class specific and temporally stable: equities exhibit standard leverage (gamma > 0), gold shows regime-dependent inverted leverage (gamma < 0 during bull markets, gamma > 0 during bear markets; t = −4.71, p < 0.0001), and bonds show no significant asymmetry. A significance-based selection rule (use GJR when the gamma t-statistic exceeds 1.65) correctly classifies all 12 Diebold-Mariano tests across six assets and achieves 95% accuracy in Monte Carlo simulations. For Value-at-Risk, switching from Normal to Student-t(df = 5) distribution reduces violations by 48%, converting SPY from 1/6 to 6/6 Basel III Green Zone years—a larger improvement than any model complexity adjustment.

**Keywords:** GARCH, leverage effect, gold, model selection, Value-at-Risk
**JEL:** C22, C53, G17

## 1. Introduction

Asymmetric GARCH models (GJR-GARCH, EGARCH) are routinely applied to financial data based on the assumption that negative returns increase volatility more than positive returns. While well-established for equities (Black, 1976), this assumption has not been systematically verified across asset classes. We address this gap with three contributions. First, we document that the leverage direction—measured by the GJR gamma parameter—is determined by the asset's economic role, not its return skewness. Second, we show that gamma direction provides a simple, validated model selection criterion. Third, we demonstrate that distributional choice (Normal vs. Student-t) dominates model complexity for VaR compliance.

## 2. Data and Methodology

We estimate GJR-GARCH(1,1) with rolling 504-day windows on 20 assets spanning equities (SPY, QQQ, EEM, IWM, VWO), precious metals (GLD, SLV), agricultural commodities (WEAT, JO), energy (USO, UNG), bonds (TLT, HYG, LQD), and cryptocurrency (BTC-USD, ETH-USD). Gamma stability is assessed via quarterly rolling estimates. Model comparison uses the QLIKE loss function with Diebold-Mariano tests (Newey-West HAC standard errors). VaR backtesting follows the Basel III traffic light framework with Kupiec unconditional coverage tests.

## 3. Results

### 3.1 Leverage Direction Taxonomy

Table 1 reports the gamma estimates. The taxonomy maps cleanly to economic mechanisms:

- **Equities** (SPY, QQQ, EEM): gamma > 0 (0% negative quarters), standard leverage. Falling prices increase firm leverage ratios, mechanically raising risk.
- **Gold** (GLD): gamma < 0 (93% negative quarters, HAC t = −5.79). Fear-driven buying during stress elevates both prices and uncertainty. Crucially, this is **regime-dependent**: gamma is inverted during bull markets but reverts to standard during bear markets (t = −4.71, p < 0.0001).
- **Supply-shock commodities** (coffee, natural gas, wheat): gamma < 0 (66–100% negative). Supply disruptions raise prices and uncertainty simultaneously.
- **Demand-driven commodities** (crude oil): gamma > 0. Price declines reflect weakening demand, increasing economic risk.
- **Bonds** (TLT): gamma ≈ 0 (41% negative). No significant asymmetry.

### 3.2 Model Selection Rule

We propose: estimate GJR-GARCH and use the asymmetric specification only when gamma is positive and its t-statistic exceeds 1.65. This rule:
- Correctly classifies all 12 Diebold-Mariano comparisons across 6 assets and 2 OOS periods
- Achieves 83% accuracy in true out-of-sample validation (2024–2025, improved to 100% with multi-window averaging)
- Achieves 95% accuracy in Monte Carlo simulations (100 replications × 3 DGPs)

The rule supersedes the common skewness-based heuristic: gold has skewness = −0.30 but inverted leverage, and skewness-based selection would incorrectly prescribe GJR.

### 3.3 VaR Attribution

For SPY (2020–2025), switching from Normal to Student-t(df = 5) VaR reduces 1% violations from 33 to 17 (−48%), converting 1/6 to 6/6 Basel III Green Zone years. Subsequent adjustments (adaptive thresholds, jump augmentation) contribute negligible improvement (+0%). Fixed df = 5 outperforms jointly estimated df (17 vs. 24 violations), as the latter over-adapts to quiet markets.

## 4. Conclusion

The GJR-GARCH gamma parameter sign—not return skewness—should guide the choice between symmetric and asymmetric volatility models. The leverage direction reflects the economic mechanism linking returns to uncertainty: fear-driven (inverted) versus risk-driven (standard). For VaR compliance, the Student-t distributional correction dominates model complexity improvements. These findings have direct implications for risk management practice across asset classes.

## References

Black, F. (1976). Studies of stock price volatility changes. *ASA Proceedings*.
Bollerslev, T. (1986). Generalized autoregressive conditional heteroskedasticity. *Journal of Econometrics*, 31, 307–327.
Baur, D. G., & McDermott, T. K. (2010). Is gold a safe haven? International evidence. *Journal of Banking & Finance*, 34, 1886–1898.
Chevallier, J., & Ielpo, F. (2017). Investigating the leverage effect in commodity markets. *Research in International Business and Finance*, 39, 763–778.
Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13, 253–263.
Glosten, L. R., Jagannathan, R., & Runkle, D. E. (1993). On the relation between the expected value and the volatility of the nominal excess return on stocks. *Journal of Finance*, 48, 1779–1801.
Kupiec, P. H. (1995). Techniques for verifying the accuracy of risk measurement models. *Journal of Derivatives*, 3, 73–84.
Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160, 246–256.
