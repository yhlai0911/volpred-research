# 4.1 Data Characteristics

Table 1 summarizes the distributional properties of daily returns for our seven assets over 2017–2025. Several patterns inform our subsequent modeling choices.

All return series exhibit significant excess kurtosis, ranging from 3.52 (GLD) to 14.61 (SPY), and all decisively reject the normality hypothesis (Jarque-Bera p < 0.001). The ARCH LM test confirms significant conditional heteroskedasticity in all series (p < 0.001), justifying the application of GARCH-family models.

Return skewness varies across assets: SPY (−0.315), QQQ (−0.189), GLD (−0.296), and EEM (−0.584) all show negative skewness, while TLT (+0.155) and BTC-USD (−0.028) are approximately symmetric. A naive model selection approach based on skewness would suggest asymmetric GARCH models for all negatively skewed assets. As we demonstrate in Section 4.2, this criterion is misleading for gold: despite its negative skewness, gold's conditional variance responds asymmetrically to *positive* shocks, not negative ones.

Annualized volatility spans an order of magnitude, from 14.6% (GLD) to 57.3% (BTC-USD). This range motivates our analysis of volatility targeting effectiveness as a function of base volatility level (Section 4.5).

The extreme minimum daily returns—SPY at −10.94% (March 2020 COVID crash) and BTC-USD at −37.17%—underscore the importance of fat-tailed distributions for VaR estimation, which we address in Section 4.4.
