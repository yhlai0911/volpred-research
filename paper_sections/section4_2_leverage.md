# 4.2 Leverage Direction Across Asset Classes

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
