# Paper 3 (vt-trend-following) Gemini Review — 2026-06-05

## Strengths
1. **Practical Focus for JPM Audience**: Shifting the evaluation of Volatility Targeting (VT) from pure alpha generation (Sharpe) to absolute risk mitigation (Maximum Drawdown) directly addresses how practitioners actually use and evaluate these overlays.
2. **Broad International Evidence**: The extension to 13 international equity markets with the simple 12/VIX rule provides compelling, out-of-sample evidence that US implied volatility acts as a global macro risk-off signal.
3. **Transparent Reporting of Negative Results**: Acknowledging that explicit trend-following rules (SMA, Faber, etc.) fail the Harvey threshold, and being upfront about the stringent utility requirements ($\gamma \geq 10$) adds credibility to the manuscript.

## Weaknesses (must address)
1. **The Mechanical Artifact of $>100\%$ MDD Retention (Logical Contradiction)** 
   - *Description*: The paper claims that removing TSMOM *enhances* VT's drawdown protection (retention $> 100\%$). Economically, if TSMOM provides downside protection by shorting bear markets, removing it should *worsen* the drawdown. Why does it improve? Because of Eq. 5: $r_{\text{PureVT}} = r_{\text{VT}} - \hat{\beta} \cdot \text{TSMOM}$. At the trough of a bear market (when MDD is set), markets often rebound sharply, causing "momentum crashes" (massive negative returns for TSMOM). By *subtracting* TSMOM from VT, you are mechanically injecting a massive positive return into the PureVT portfolio exactly at the market bottom. Thus, the $>100\%$ retention is not proof of "independent drawdown protection"; it is a mechanical artifact of reversing out momentum crashes. 
   - *Recommended fix*: You must address the momentum crash dynamic explicitly. Decompose the daily returns of PureVT around the MDD troughs (e.g., March 2009, March 2020). Show whether the MDD improvement in PureVT comes from actual VIX timing or simply from profiting off the short-TSMOM hedge during market rebounds.
   - *Severity*: **HIGH** (Threatens the core economic interpretation of the paper).

2. **Block Bootstrap Destroys Long-Memory Drawdown Paths**
   - *Description*: The block bootstrap uses a block size of 252 days on a 21-year sample ($N \approx 5300$). This means each synthetic path consists of only 21 independent blocks. Major drawdowns (like 2008 or 2022) have peak-to-recovery paths that last well over 252 days. Scrambling 1-year blocks severs the autocorrelation of multi-year secular bear markets, resulting in synthetic buy-and-hold MDDs that are mechanically shallower than empirical ones. Because $\text{MDD}_{\text{B\&H}}$ is the denominator in your retention fraction (Eq. 8), shrinking it artificially inflates the retention ratio, pushing the 90% CI lower bounds upward.
   - *Recommended fix*: A 252-day block is insufficient for MDD inference. Implement a stationary bootstrap with a much larger expected block size (e.g., 3-5 years) to preserve full peak-to-trough-to-recovery cycles, or report absolute MDD differences rather than a highly sensitive ratio.
   - *Severity*: **HIGH**

3. **Endogeneity vs. "Regime Shift" in the Cross-Sectional Test**
   - *Description*: The split-sample test ($r=0.793$) is used to wave away endogeneity between $\gamma$ and TSMOM loading. However, the paper admits this increase is driven by a "regime shift" where safe havens (bonds, gold) flipped to positive TSMOM loadings in 2017-2026. This implies the correlation is driven by changing macroeconomic correlations (e.g., the breakdown of the equity-bond correlation in the 2022 inflation shock) rather than the structural $\gamma$ leverage effect. If $\gamma$ is structural but the TSMOM loading flips purely due to macro regimes, the causal narrative breaks down.
   - *Recommended fix*: With $N=22$, cross-sectional regressions are notoriously fragile. Control for a "Risk Asset vs. Safe Haven" dummy. If the $\gamma$ coefficient loses significance when simply controlling for whether an asset is an equity, the leverage effect mechanism is a proxy for asset class behavior, not an independent driver.
   - *Severity*: **MEDIUM**

4. **"Insurance Premium" vs. Variance Risk Premium (VRP) Confound**
   - *Description*: The paper claims the 4% Sharpe drag is an "insurance premium" paid for MDD protection. However, VIX is not just expected volatility; it contains the Variance Risk Premium (VRP). The $12/\text{VIX}$ strategy inherently underweights equities precisely when the VRP is highest (during panics), missing out on the massive risk premiums offered during recoveries. 
   - *Recommended fix*: Clarify whether the "Sharpe drag" is actually an insurance premium, or just the mathematical consequence of failing to harvest the VRP. This distinction is critical for JPM readers who actively trade volatility.
   - *Severity*: **MEDIUM**

## Suggestions
1. **Utility Theory Gap**: You mention Cederburg et al. (2020) and state that standard utility tests "underweight" MDD protection. In Section 4.1, you briefly mention CRRA requires $\gamma \geq 10$ to prefer VT. Bring this out of the text and into a formal, concise exhibit. JPM readers need to see exactly *who* this strategy is for (i.e., highly risk-averse investors, or institutions with strict drawdown limits).
2. **Clarify Hood (2025) Differentiation**: Hood looks at 50 futures; you look at 22 ETFs. Make sure you explicitly state *why* your dual-channel decomposition was impossible or unaddressed in Hood's framework. Right now, it reads like you ran the same regression on a different dataset and then calculated MDD on the residuals.

## Missing Citations
- **Bollerslev, T., Tauchen, G., & Zhou, H. (2009/2018 literature)**: Essential for discussing the Variance Risk Premium embedded in VIX. If you trade off VIX, you are trading VRP.
- **Campbell, J. Y., & Cochrane, J. H. (1999)**. *By Force of Habit: A Consumption-Based Explanation of Aggregate Stock Market Behavior*. (Necessary to justify why investors might rationally pay a 4% Sharpe drag to avoid drawdowns—habit formation/drawdown aversion).
- **Bondarenko, O., & Bernardo, A. E. (2019/related)** on the pricing of out-of-the-money protection and volatility as an asset class.

## Overall Recommendation
**Major Revision**: The paper offers a highly relevant, practitioner-focused thesis that pushes back effectively against the "VT is just TSMOM" narrative. However, the central empirical proof—that TSMOM hedging yields $>100\%$ MDD retention—suffers from a severe logical/econometric blind spot regarding momentum crashes (subtracting a negative return mechanically boosts the portfolio). Furthermore, the block bootstrap methodology actively destroys the long-memory properties required to study maximum drawdowns. If the authors can prove the MDD retention is not just a mathematical artifact of the short-TSMOM hedge at market bottoms, and fix the bootstrap, this will be a strong fit for JPM.
