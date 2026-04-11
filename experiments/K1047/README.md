# K1047: Agent-Based Model — VT Adoption Rate Impact on Market Dynamics (Formal)

## Motivation

If many investors adopt the 12/VIX volatility targeting strategy, does it destabilize markets? Prior work (K742) concluded "safe to publish, feedback loops always converge" — but K742 used a simplified, stylized price model. This experiment builds a formal ABM with heterogeneous agents to properly test the crowding hypothesis.

## Core Questions

1. Does VT adoption increase or decrease market volatility?
2. Is there a tipping point beyond which markets destabilize?
3. How does VT agent alpha decay with adoption?
4. Does K742's "always converge" conclusion hold in a formal ABM?

## Method

**Type**: Simulation / Theoretical (NOT empirical)

### Agent Types (N = 1,000 total)
- **Fundamentalist (60% of non-VT)**: Mean-reversion to fair value. d_i = phi * (p_fund - p_t)/p_t + noise
- **Chartist (40% of non-VT)**: Momentum following. d_i = chi * sum(r_{t-k}) + noise  
- **VT Agent (variable %)**: 12/VIX position sizing. demand = change in min(12/VIX, 1.5) + noise

### Market Clearing
Fully endogenous returns: r_t = (1/lambda) * mean(all_demands)

### Parameters
- lambda_depth = 3.0 (market depth)
- phi = 4.0 (fundamentalist strength)
- chi = 2.0 (chartist strength)
- sigma_agent_noise = 1.0
- T = 5,000 days (~20 years), MC = 50 repetitions
- VT fractions: 0%, 5%, 10%, 25%, 50%, 75%, 90%

## Results

| VT% | Ann. Vol | MDD | Kurtosis | AC(\|r\|) | Skew | VT Sharpe | F Sharpe | C Sharpe |
|-----|----------|-----|----------|-----------|------|-----------|----------|----------|
| 0% | 0.2022 | -0.093 | 0.02 | 0.047 | 0.008 | - | 0.819 | 0.287 |
| 5% | 0.2004 | -0.093 | -0.02 | 0.044 | -0.000 | 0.455 | 0.823 | 0.300 |
| 10% | 0.1995 | -0.095 | 0.02 | 0.041 | 0.003 | 0.464 | 0.829 | 0.303 |
| 25% | 0.1987 | -0.105 | 0.01 | 0.048 | -0.016 | 0.537 | 0.819 | 0.310 |
| 50% | 0.2106 | -0.155 | 1.07 | 0.149 | -0.159 | 0.653 | 0.825 | 0.304 |
| 75% | 0.2465 | -0.254 | 6.09 | 0.333 | -0.567 | 0.783 | 0.838 | 0.268 |
| 90% | 0.3045 | -0.328 | 14.57 | 0.449 | -0.750 | 0.949 | 0.902 | 0.193 |

## Key Conclusions

### Q1: Volatility increases with VT adoption (+50.6% at 90%)
Baseline volatility = 20.2%, at 90% VT adoption = 30.5%. The increase is nonlinear — moderate up to 25%, then accelerates.

### Q2: Tipping point at ~50-75%
Up to 25% VT adoption, volatility actually decreases slightly (stabilizing). Beyond 50%, it starts to increase, crossing the +10% threshold around 75%.

### Q3: VT alpha does NOT decay — it increases slightly
Contrary to simple crowding theory, VT agents' Sharpe increases from 0.45 (at 5%) to 0.95 (at 90%). This is because VT agents profit from the volatility dynamics they create. However, the alpha comes at the cost of higher market volatility — a negative externality.

### Q4: K742's "always converge" needs qualification
At 90% VT adoption: kurtosis = 14.57 (vs 0.02 baseline), vol clustering AC(|r|) = 0.449 (vs 0.047). While prices don't diverge to infinity (convergence in K742's sense), the market develops pathological properties: extreme fat tails, strong vol clustering, and negative skewness. K742's conclusion is technically correct but misleading — "converges" does not mean "healthy."

### Q5: VT dramatically increases volatility clustering
AC(|r|) rises from 0.047 to 0.449 — a 10x increase. VT creates a feedback loop: high vol -> high VIX -> VT sells -> further selling pressure -> price drop -> higher vol. This self-reinforcing cycle doesn't diverge but creates persistent vol regimes.

## Phase Diagram

- **0-25% VT (Safe Zone)**: Vol slightly decreases. VT acts as stabilizer. No tail risk increase.
- **25-50% VT (Transition)**: Vol starts increasing. Fat tails emerge (kurtosis > 1). Vol clustering doubles.
- **50-90% VT (Danger Zone)**: Vol increases 50%+. Extreme fat tails (kurtosis > 14). Strong negative skewness. Severe vol clustering.

## Practical Implications

With current VT AUM estimated at <5% of total market, we are firmly in the "safe zone." The 12/VIX strategy is safe to recommend. However, if VT became a universal strategy (>50% adoption), it would create the very instability it claims to protect against — a classic tragedy of the commons.

## Comparison with Prior Work

| Experiment | Model | Key Finding |
|-----------|-------|-------------|
| K742 | Stylized | "Always converge, safe to publish" |
| K827 | Kyle MM | Kurtosis explodes at 100% VT |
| K864 | Heterogeneous | Strategy diversity amplifies crowding |
| **K1047** | Formal ABM | Tipping at 50-75%, K742 needs qualification |

## Limitations

1. Simplified market microstructure (single depth parameter)
2. No transaction costs (would amplify crowding cost)
3. Agents homogeneous within class
4. No adaptive learning or strategy switching
5. Constant fundamental value
6. VIX = realized vol, not option-implied
7. Model-dependent results
8. N=1000 agents is small vs real markets

## References

- LeBaron (2006): Agent-based computational finance
- Hommes (2006): Heterogeneous agent models in economics and finance
- Brock & Hommes (1998): Heterogeneous beliefs and routes to chaos
- Lux & Marchesi (1999): Scaling and criticality in a stochastic multi-agent model
- Farmer & Foley (2009): The economy needs agent-based modelling (Nature)
- K742, K827, K864: Prior VT crowding simulations

## Files

- `k1047.py` — Simulation script
- `k1047_results.json` — Full results with all metrics
- `k1047_market_dynamics.png` — Volatility, MDD, kurtosis, vol clustering vs VT fraction
- `k1047_alpha_decay.png` — Agent-type Sharpe ratios and alpha decay curve
