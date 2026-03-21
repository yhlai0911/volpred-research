# 4.4 VaR Compliance: Student-t Attribution Analysis

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

## 4.4.5 Practical Implications

Our attribution analysis reveals that the most impactful improvement to VaR compliance—switching from Normal to Student-t distribution—is also the simplest to implement. This stands in contrast to the growing literature on sophisticated VaR methodologies (conditional EVT, dynamic quantile regression, etc.), which our results suggest provide marginal improvements over the straightforward distributional correction.

The estimated degrees of freedom for our sample (df ≈ 4.78 for SPY) is consistent with the range reported in the empirical GARCH literature (Hansen, 1994; Bollerslev et al., 1994). The robustness analysis confirms that results hold for df ∈ [4, 7], covering the typical empirical range for financial returns.
