# Abstract

We conduct a comprehensive cross-asset analysis of GARCH-family volatility forecasting and its applications to risk management and portfolio construction. Using daily data from fifteen assets spanning equities (SPY, QQQ, EEM), precious metals (GLD, SLV), agricultural commodities (JO, WEAT), energy (USO, UNG), bonds (TLT), and cryptocurrency (BTC-USD) over 2005–2025, we document four main findings.

First, the direction of the asymmetric volatility response—measured by the GJR-GARCH gamma parameter—is determined by the price-driving mechanism, not the asset class per se. Supply-shock sensitive assets (gold, coffee, natural gas, wheat) exhibit inverted leverage where positive returns increase conditional variance, while demand-driven assets (equities, crude oil) show standard leverage. For gold, the inverted leverage (HAC-corrected t = −5.79, p < 0.001) is itself regime-dependent: it prevails during fear-driven bull markets but reverses to standard leverage during bear markets (t = −4.71, p < 0.0001). We propose a significance-based model selection rule—using the gamma t-statistic from GJR-GARCH estimation—that correctly classifies all twelve Diebold-Mariano test comparisons across six assets and two out-of-sample periods.

Second, for Value-at-Risk compliance under Basel III, we demonstrate that the Student-t distributional correction reduces VaR 1% violations by 21–48% across asset classes—converting SPY from 1/6 to 6/6 Green Zone years (2020–2025). Fixed degrees of freedom (df = 5) outperforms jointly estimated df (17 vs. 24 violations), as the joint approach over-adapts to quiet markets and narrows VaR thresholds before volatility transitions. Furthermore, the VIX/GARCH ratio serves as a powerful VaR reliability indicator: 94% of violations occur when this ratio exceeds 1.5, corresponding to periods where market-implied volatility leads the GARCH model estimate.

Third, GARCH-based volatility targeting generates consistent maximum drawdown reduction across all leverage regimes (10–55 percentage points for seven assets), with the improvement magnitude near-perfectly correlated with base volatility level (ρ = 0.983). The effectiveness is independent of leverage direction, extending Moreira and Muir's (2017) equity-factor results to commodities, bonds, and cryptocurrency.

**Keywords:** GARCH, leverage effect, gold, asymmetric volatility, Value-at-Risk, Basel III, volatility targeting, cross-asset, regime-dependent

**JEL Classification:** C22, C53, G11, G17
