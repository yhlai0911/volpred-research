# 4.5 Volatility Targeting Across Leverage Regimes

## 4.5.1 Strategy Implementation

Following Moreira and Muir (2017), we construct volatility-managed portfolios by scaling daily exposure as w_t = σ_target / σ̂_t, where σ̂_t is the one-step-ahead GARCH conditional volatility forecast and σ_target = 10% annualized. We apply a 5-day moving average to weights (slow adjustment) and clip weights to [0, 1.5] to avoid extreme leverage.

Critically, we select the GARCH specification for each asset based on the leverage direction criterion established in Section 4.2: GJR-GARCH for assets with γ > 0.10 (SPY, EEM, BTC-USD), and standard GARCH for assets with γ ≤ 0.10 or γ < 0 (GLD, TLT).

## 4.5.2 Cross-Asset Results

Table 5 presents buy-and-hold versus volatility targeting performance for five assets over 7–16 year periods.

The most consistent finding is that **maximum drawdown improves for all five assets**, with the improvement magnitude almost perfectly correlated with base volatility (ρ = 0.983). BTC-USD, with the highest base volatility (51.7% annualized), sees MaxDD improve from −76.6% to −21.3% (55.3 percentage points). Even for lower-volatility assets like TLT (15.0%), MaxDD improves by 13.1 percentage points.

Sharpe ratio improvement is more heterogeneous: BTC-USD gains +41% (0.43 → 0.60), GLD +11%, TLT +33%, while SPY and EEM show negligible changes. The Sharpe improvement correlates strongly with base volatility level (ρ = 0.80, p = 0.10), consistent with the interpretation that VT operates primarily as a volatility scaling mechanism rather than a market-timing strategy.

## 4.5.3 Leverage Direction Does Not Affect VT Effectiveness

A central concern for applying VT to gold is its inverted leverage effect: when gold rallies (typically during market stress), volatility rises, causing VT to reduce the gold position precisely when gold serves its hedging function. We test whether this "paradox" undermines VT by comparing VT against an "anti-VT" strategy that increases gold allocation during high-volatility periods.

Over 2022–2026, standard VT achieves Sharpe 1.71 versus anti-VT's 1.51 and buy-and-hold's 1.56. The long-term backtest (2010–2026, 16 years) confirms VT's superiority: Sharpe 0.62 vs. 0.56 for buy-and-hold. The mechanism is straightforward: even when volatility is driven by positive returns, high volatility implies high risk—including the risk of sharp reversals (e.g., the January 2026 gold flash crash, −10.27%). VT's risk reduction during these periods outweighs the opportunity cost of reduced exposure to continued rallies.

## 4.5.4 VT as Volatility Scaling, Not Market Timing

Our cross-asset evidence suggests reframing VT's value proposition. The near-perfect correlation (ρ = 0.983) between base volatility and MaxDD improvement indicates that VT's primary benefit is mechanical volatility compression—bringing all assets to a common target volatility—rather than exploiting predictable variation in expected returns.

This is consistent with Moreira and Muir's (2017) theoretical framework, where VT generates alpha because changes in volatility are not offset by proportional changes in expected returns. Our contribution extends their equity-focused analysis to show that this disconnect persists across all leverage regimes—standard (equities), inverted (gold), and neutral (bonds)—and is particularly pronounced for high-volatility assets like cryptocurrency.

## 4.5.5 Hybrid VT: Using VIX During Crises

Standard GARCH-based VT can underperform during rapid regime transitions because of GARCH's inherent one-day lag. During the 2026 Iran crisis (March 1–13), GARCH VT produced the worst return (−4.3%) among all strategies, as GARCH sigma remained at 16% while VIX had already risen to 29.5. While VIX-managed portfolios have been proposed in the literature (e.g., Journal of International Financial Markets, 2024), our approach differs by dynamically switching between GARCH and VIX rather than using VIX exclusively. We propose a hybrid approach: when the VIX/GARCH ratio exceeds a threshold (1.3–1.5), switch the VT weight calculation from GARCH sigma to VIX-implied volatility. This hybrid VT achieved +0.9% during the crisis—the only strategy with positive returns—improving over standard GARCH VT by 5.2 percentage points.
