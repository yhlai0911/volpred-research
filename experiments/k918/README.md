# K918: BEKK-GARCH Volatility Spillover — SPY <-> GLD Direct Transmission

## Research Question
Can BEKK-GARCH quantify direct cross-asset volatility spillover between SPY and GLD?
Does spillover intensity vary with VIX regime?

## Context
- K907: TCI network (9 assets) — SPY is transmitter (NET=+34.8), GLD is isolator (NET=-5.5)
- K915: DCC-GARCH — dynamic correlation, SPY-GLD mean rho=0.069, std=0.199
- BEKK fills the gap: models H_t dynamics with cross-asset vol transmission via A matrix off-diagonals

## Method
- Full BEKK(1,1): H_t = C'C + A' eps_{t-1} eps'_{t-1} A + B' H_{t-1} B (11 params)
- Diagonal BEKK(1,1): A, B are diagonal (7 params, no cross terms)
- LR test: Full vs Diagonal
- VIX regime subsample analysis
- BEKK-based time-varying hedge ratio and minimum variance portfolio
- Numba JIT for fast log-likelihood computation

## Data
- SPY + GLD daily log returns (%), 2004-11-19 to 2026-04-02, N=5375
- VIX for regime classification
- Source: yfinance

## Key Findings

1. **No significant cross-spillover**: LR test (7.50, p=0.112) fails to reject Diagonal BEKK. AIC/BIC both prefer Diagonal.

2. **Spillover coefficients are tiny**:
   - a12 (SPY shock -> GLD vol) = -0.0090, only 2.6% of SPY's own ARCH effect
   - a21 (GLD shock -> SPY vol) = 0.0010, only 0.5% of GLD's own ARCH effect
   - This confirms K907's finding: GLD is an isolator

3. **BEKK correlation matches DCC (K915)**:
   - Full BEKK: mean=0.071, std=0.240
   - DCC (K915): mean=0.069, std=0.199
   - BEKK has wider swings (higher std) but same mean

4. **Correlation increases with VIX regime**:
   - Low VIX (<15): rho=0.034
   - Medium (15-25): rho=0.091
   - High (25-35): rho=0.120
   - Extreme (>35): rho=0.037 (drops back — flight-to-quality dissipates)

5. **Portfolio: BEKK MinVar marginally beats 50/50 on Sharpe but worse MDD**:
   - BEKK MinVar: Sharpe=0.782, MDD=-37.5%, avg weights SPY=56%/GLD=44%
   - 50/50 Static: Sharpe=0.759, MDD=-36.1%
   - Marginal improvement not worth the complexity (turnover=7.4x/yr)

6. **Hedge ratio very small**: mean=0.060 — confirms SPY-GLD have very weak linkage

## Conclusion
BEKK confirms and quantifies what K907 and K915 showed qualitatively: **SPY and GLD volatilities are nearly independent**. Cross-spillover is statistically insignificant (p=0.112). The two assets' volatilities are driven by their own dynamics, not each other's shocks. This independence is precisely WHY 50/50 diversification works — it's a feature, not a limitation.

## Limitations
- Standard BEKK does not capture asymmetric spillover (positive vs negative shocks)
- 2-asset only — does not capture indirect spillover through other assets
- Full-sample estimation; subsample parameters may differ

## References
- Engle & Kroner (1995): Multivariate Simultaneous Generalized ARCH, Econometric Theory
- Baba, Engle, Kraft & Kroner (1990): BEKK original formulation
