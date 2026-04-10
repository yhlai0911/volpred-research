# K1031: Bayesian SSVS for ARX-GARCH (Joint Variable Selection)

## Motivation

Previous SSVS experiments performed variable selection **separately** for the mean equation (K433) and variance equation (K484, K821, K1013). This leaves open the question: could there be cross-equation interactions that sequential selection misses? For example, a variable might be unimportant in the mean equation alone but become important when a related variable is included in the variance equation.

So, Chen, and Liu (2006) proposed a **joint MCMC** approach that simultaneously samples binary inclusion indicators for both equations, allowing the posterior to capture such synergies.

## Method

**Model**: ARX(1)-GJR(1,1) with SSVS
- Mean: r_t = mu + sum(delta^m_i * beta_i * X_{i,t-1}) + eps_t
- Variance: sigma^2_t = omega + alpha*eps^2_{t-1} + gamma*eps^2_{t-1}*I(eps<0) + beta*sigma^2_{t-1} + sum(delta^v_j * theta_j * Z_{j,t-1})
- delta^m_i, delta^v_j in {0, 1} are binary inclusion indicators
- Prior: P(delta_i = 1) = 0.5 (uninformative)
- Spike-and-slab: tau^2 = 0.01 (spike), c^2 = 100 (slab)

**Candidate Variables** (8 total):
- Mean equation (4): VIX_change, VIX_level, TLT_return, CREDIT_spread (HYG)
- Variance equation (4): VIX^2, VIX9D^2, RV_22d, VIX_change^2

**MCMC**: 10,000 iterations, burn-in 2,000, thinning every 5th sample (1,600 kept). Gibbs for mean coefficients, Metropolis-Hastings for variance coefficients and GARCH parameters. Numba JIT for inner loops.

**Data**: SPY, yfinance
- In-sample: 2011-01-03 to 2018-12-31 (2,012 obs)
- OOS: 2019-01-02 to 2026-04-09 (1,827 obs)

## Results

### Posterior Inclusion Probabilities

| Variable | Equation | PIP | Selected? |
|----------|----------|-----|-----------|
| VIX_change | Mean | 0.0063 | No |
| VIX_level | Mean | 0.0138 | No |
| TLT_return | Mean | 0.0100 | No |
| CREDIT_spread | Mean | 0.0131 | No |
| VIX^2 | Variance | 0.0037 | No |
| **VIX9D^2** | **Variance** | **1.0000** | **Yes** |
| RV_22d | Variance | 0.0031 | No |
| VIX_change^2 | Variance | 0.0013 | No |

### Best Model (Posterior Probability = 0.9494)
- Mean equation: **NONE** (all 4 variables excluded)
- Variance equation: **VIX9D^2 only** (included with PIP = 1.000)

The best model has 94.9% posterior probability — overwhelmingly dominant. The next best model (adding VIX_level to mean) has only 1.3%.

### OOS QLIKE Comparison

| Model | QLIKE | vs GJR-t |
|-------|-------|----------|
| GJR-t baseline | 1.5491 | -- |
| SSVS null (no exog) | 1.6532 | -6.72% (worse) |
| SSVS best (VIX9D^2 in var) | 1.4428 | +6.86% (better) |

### DM Test
- SSVS best vs GJR-t: t = 2.494, p = 0.013
- Harvey (2016) threshold |t| > 3.0: **NOT significant**
- The improvement is suggestive but does not pass the stringent multiple-testing threshold.

### MCMC Diagnostics
- MH acceptance rate (theta_v): 51.4% (good)
- MH acceptance rate (GARCH): 42.2% (good)
- ESS: loglik=214, alpha=484, omega=28, beta=24
- Low ESS for omega and beta suggests some mixing issues, but PIP estimates are stable (PIP evolution plot shows convergence within first 200 post-burn-in samples)

## Conclusion

Joint SSVS confirms two key findings:

1. **Mean equation: all external variables NULL** (all PIP < 0.02). Consistent with K433. No cross-equation interactions rescue any mean-equation variable.

2. **Variance equation: VIX9D^2 selected with PIP = 1.000**. This is consistent with K1004 (VIX9D best short-term vol predictor) but **differs from K821** which found 0/8 external variance predictors with PIP > 0.5. The difference may be due to the joint framework allowing the variance equation to be estimated more cleanly when the mean equation is simultaneously optimized.

3. **OOS improvement**: +6.86% QLIKE improvement over GJR-t, but DM test t=2.49 falls short of Harvey (2016) t>3.0 threshold. Marginal improvement at best.

4. **No cross-equation synergies detected**: The joint framework did not reveal any variable that becomes important in one equation conditional on another equation's specification. The null model in both equations (except VIX9D^2 in variance) remains dominant.

## References

- So, M.K.P., Chen, C.W.S., Liu, F.C. (2006). "Best Subset Selection of Autoregressive Models with Exogenous Variables and Generalized Autoregressive Conditional Heteroscedasticity Errors." JRSS-C, 55(2), 201-224.
- George, E.I. & McCulloch, R.E. (1993). "Variable selection via Gibbs sampling." JASA, 88(423), 881-889.
- Patton, A.J. (2011). "Volatility forecast comparison using imperfect volatility proxies." JFE, 98(1), 1-18.
- Harvey, C.R. (2016). "Presidential Address: The Scientific Outlook in Financial Economics." JF, 72(4), 1399-1440.

## Files

- `k1031.py` — Experiment script
- `k1031_results.json` — Full results
- `k1031_pip_chart.png` — PIP bar chart (mean + variance)
- `k1031_mcmc_trace.png` — MCMC diagnostics (trace plots + PIP evolution)
- `k1031_qlike_comparison.png` — OOS QLIKE comparison
