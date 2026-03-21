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

Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, and Van Hemert (2018) extend these results to multi-asset portfolios. Fleming, Kirby, and Ostdiek (2001, 2003) provide earlier evidence that volatility timing improves portfolio performance. However, the effectiveness of VT across different leverage regimes—particularly for assets with inverted leverage—has not been previously examined.

## 2.5 Deep Learning for Volatility Forecasting

Recent work has explored neural network approaches to volatility forecasting. Hybrid GARCH-LSTM models (e.g., Kim and Won, 2018; Araya et al., 2024) attempt to combine the structural advantages of GARCH with the flexibility of deep learning. However, the incremental improvement over well-specified GARCH models remains debated, particularly at daily frequency where GARCH models may already extract the available signal in squared returns (see Bucci, 2020, for a skeptical assessment).
