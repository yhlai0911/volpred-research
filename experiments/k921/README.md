# K921: Time-Varying Copula -- Dynamic Tail Dependence as Crisis Early Warning

## Question
K920 found SPY-GLD overall lambda=0.14, but during crises it drops to 0.007-0.068.
**Does tail dependence change *before* crises? Can it serve as an early warning signal?**

## Motivation
- K920: Student-t copula best, lambda=0.14 overall, but crisis-conditional near independence
- Patton (2006): Standard framework for time-varying copula
- If lambda drops 1-2 months before crisis -> early signal for gold "switching to protection mode"
- If lambda change is sudden -> crisis = unpredictable structural break

## Method
1. SPY + GLD daily returns (2005-2026, yfinance)
2. GJR-GARCH(1,1) Student-t marginals -> PIT -> uniform u1, u2 (same as K920)
3. Patton (2006) time-varying Student-t copula:
   - rho_t = Lambda(omega + beta * rho_{t-1} + alpha * (1/M) * sum Phi^{-1}(u1) * Phi^{-1}(u2))
   - Lambda(x) = (1-exp(-x))/(1+exp(-x)) keeps rho in (-1,1)
   - Fixed nu (df), dynamic rho only
4. Compute time-varying lambda_t from rho_t and nu
5. Early warning analysis:
   - lambda_t behavior 60 days before GFC/COVID/Rate Hike
   - Granger causality lambda -> VIX
   - Lambda regime detection with rolling bands
6. Compare time-varying vs static copula (AIC, VaR)

## Error Log Rules Applied
- Fixed seed: np.random.seed(42)
- signal.shift(1) for any strategy signals
- VaR/ES reported separately for IS and OOS
- All results from actual computation, no fabrication

## References
- Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER 47(2):527-556
- Joe (1997): Multivariate Models and Dependence Concepts
- K920: Copula-GARCH Tail Dependence (prior experiment)

## Output
- k921_time_varying_copula.py
- k921_time_varying_copula_results.json
- k921_dynamic_lambda.png
- k921_crisis_leadlag.png
