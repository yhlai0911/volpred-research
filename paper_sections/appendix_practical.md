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
