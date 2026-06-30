# Finance and Econometrics Terminology Guide

## Overview

This guide provides standard terminology, proper usage, and common phrases for academic finance writing. It covers both finance-specific terms and econometric methods terminology.

## Econometric Methods

### GMM (Generalized Method of Moments)

**Correct usage**:
- "We employ GMM estimation..."
- "The GMM estimator minimizes..."
- "Two-step GMM with optimal weighting matrix..."
- "Moment conditions derived from..."

**Terms**:
- **Moment condition**: Equation that should equal zero in expectation: E[g(θ)] = 0
- **Weighting matrix**: Matrix W used in GMM objective function g'Wg
- **Optimal weighting matrix**: Inverse of long-run covariance of moments
- **Overidentification**: More moment conditions than parameters (J > K)
- **J-statistic**: Test for validity of overidentifying restrictions
- **Two-step GMM**: First step with identity matrix, second with optimal weights

**Standard phrases**:
- "moment conditions implied by the model"
- "GMM objective function"
- "optimal weighting matrix estimated using Newey-West"
- "overidentifying restrictions are not rejected (J=12.4, p=0.13)"

### Maximum Likelihood

**Terms**:
- **Likelihood function**: Probability of observing data given parameters
- **Log-likelihood**: Natural log of likelihood (easier to maximize)
- **MLE**: Maximum likelihood estimator
- **Fisher information**: Expected second derivative of log-likelihood
- **Quasi-ML**: ML with misspecified density (still consistent for mean parameters)

**Standard phrases**:
- "maximize the log-likelihood function"
- "MLE is asymptotically efficient under correct specification"
- "standard errors computed from inverse Fisher information"

### Time Series Methods

**Terms**:
- **Autocorrelation**: Correlation between X_t and X_{t-k}
- **Partial autocorrelation**: Autocorrelation controlling for intermediate lags
- **Stationarity**: Distribution unchanged over time
- **Ergodicity**: Time averages converge to population moments
- **HAC (Heteroskedasticity and Autocorrelation Consistent)**: Robust standard errors
- **Newey-West**: Specific HAC estimator with automatic lag selection

**Standard phrases**:
- "exhibits significant autocorrelation at lags 1-5"
- "assume weak stationarity and ergodicity"
- "HAC standard errors using Newey-West with automatic bandwidth"

## Financial Concepts

### Financial Contagion

**Definition**: Transmission of financial shocks from one market/institution to another beyond what fundamentals justify

**Related terms**:
- **Spillover**: Similar to contagion but more neutral (can be positive or negative)
- **Systemic risk**: Risk of system-wide collapse due to interconnections
- **Flight to quality**: Investors move from risky to safe assets during crises
- **Herding**: Investors imitate others' actions

**Standard phrases**:
- "financial contagion through cross-border spillovers"
- "systemic risk arising from interconnected institutions"
- "contagion effects amplify during crisis periods"
- "spillovers beyond what fundamentals can explain"

### Jump-Diffusion Models

**Terms**:
- **Diffusion component**: Continuous Brownian motion part (σdW)
- **Jump component**: Discrete jumps at random times (ZdN)
- **Jump intensity**: Probability rate of jump occurrence (λ)
- **Jump size**: Magnitude of jump when it occurs (Z)
- **Compound Poisson process**: Poisson arrivals with random jump sizes

**Standard phrases**:
- "jump-diffusion process with stochastic volatility"
- "jumps follow a Poisson process with intensity λ"
- "jump sizes drawn from exponential distribution"
- "continuous diffusion captures normal variation"

### Hawkes Processes

**Terms**:
- **Self-exciting**: Past events increase future arrival rates
- **Mean reversion**: Intensity reverts to baseline level
- **Baseline intensity**: Long-run average intensity (λ_∞)
- **Excitation parameter**: Amount intensity increases per event (β)
- **Decay rate**: Speed of mean reversion (α)
- **Branching ratio**: β/α (determines clustering strength)

**Standard phrases**:
- "self-exciting jump intensity"
- "mutually exciting processes capture contagion"
- "intensity mean-reverts exponentially at rate α"
- "stationarity requires α > β"
- "half-life of intensity shock is ln(2)/α"

### Market Microstructure

**Terms**:
- **Bid-ask spread**: Difference between bid and ask prices
- **Tick size**: Minimum price increment
- **High-frequency data**: Intraday data (second, minute level)
- **Market impact**: Price movement caused by trade
- **Price discovery**: Process by which prices reflect information

### Volatility

**Terms**:
- **Realized volatility**: Volatility computed from high-frequency returns
- **Implied volatility**: Volatility implied by option prices
- **GARCH**: Generalized autoregressive conditional heteroskedasticity
- **Stochastic volatility**: Volatility follows its own stochastic process
- **Volatility clustering**: Periods of high/low volatility persist

**Standard phrases**:
- "volatility exhibits strong persistence"
- "GARCH(1,1) specification captures clustering"
- "stochastic volatility with mean reversion"
- "implied volatility exceeds realized volatility during crises"

### Risk Measures

**Terms**:
- **VaR (Value at Risk)**: Maximum loss at given confidence level
- **CVaR (Conditional VaR)**: Expected loss given VaR is exceeded
- **Expected shortfall**: Same as CVaR
- **Tail risk**: Risk of extreme losses
- **Downside risk**: Risk of negative returns only

**Standard phrases**:
- "VaR at 99% confidence level"
- "expected shortfall captures tail risk"
- "model focuses on downside risk and left-tail events"

## Statistical Concepts

### Hypothesis Testing

**Terms**:
- **Null hypothesis (H₀)**: Hypothesis to be tested
- **Alternative hypothesis (H₁)**: What you believe if H₀ is rejected
- **Test statistic**: Quantity used to decide whether to reject H₀
- **p-value**: Probability of observing test statistic under H₀
- **Significance level**: Threshold for rejecting H₀ (typically 0.05)
- **Type I error**: Falsely rejecting true H₀
- **Type II error**: Failing to reject false H₀
- **Power**: Probability of correctly rejecting false H₀

**Standard phrases**:
- "test the null hypothesis H₀: β=0"
- "reject H₀ at the 5% significance level"
- "fail to reject H₀ (p=0.23)"
- "highly significant (p<0.01)"
- "marginally significant (p<0.10)"

### Estimation

**Terms**:
- **Estimator**: Rule/formula for computing estimate from data
- **Estimate**: Actual number produced by estimator
- **Bias**: Expected difference between estimator and true value
- **Consistency**: Estimator converges to true value as n→∞
- **Efficiency**: Estimator has smallest variance among consistent estimators
- **Asymptotic distribution**: Limiting distribution as n→∞

**Standard phrases**:
- "unbiased and consistent estimator"
- "asymptotically efficient under standard conditions"
- "point estimate is β̂=13.1"
- "estimated with precision (s.e.=0.5)"

### Standard Errors

**Terms**:
- **Standard error**: Standard deviation of estimator
- **Robust standard errors**: Valid under heteroskedasticity
- **Clustered standard errors**: Valid when data clustered (e.g., by firm)
- **Bootstrap standard errors**: Computed via resampling

**Standard phrases**:
- "standard errors in parentheses"
- "robust standard errors accounting for heteroskedasticity"
- "clustered by firm to account for within-firm correlation"
- "bootstrap standard errors with 1,000 replications"

## Writing Conventions

### Numbers

**Rounding**:
- Parameters: 3 decimal places (β=13.145 → 13.1)
- Standard errors: 2-3 decimal places
- p-values: 2-3 decimal places, or <0.001 for very small
- Percentages: 1-2 decimal places

**Large numbers**:
- Use commas: 1,500 not 1500
- Scientific notation for very large: 3×10⁶
- Spell out small numbers in prose: "three markets" not "3 markets"

### Symbols

**Greek letters** (common usage):
- α: Mean reversion speed, significance level
- β: Regression coefficient, excitation parameter
- γ: Discount factor, jump size parameter
- δ: Depreciation rate, Dirac delta
- λ: Jump intensity, eigenvalue
- μ: Mean, drift
- ρ: Correlation
- σ: Standard deviation, volatility
- τ: Time to maturity, time constant
- θ: Parameter vector

**Operators**:
- E[·]: Expectation
- Var[·]: Variance
- Cov[·,·]: Covariance
- Pr[·]: Probability
- argmax: Argument that maximizes
- →: Converges to
- ∼: Distributed as

### Abbreviations

**Common abbreviations**:
- GMM: Generalized Method of Moments
- ML/MLE: Maximum Likelihood (Estimator)
- OLS: Ordinary Least Squares
- IV: Instrumental Variables
- VAR: Vector Autoregression (or Value at Risk - context dependent)
- GARCH: Generalized Autoregressive Conditional Heteroskedasticity
- HAC: Heteroskedasticity and Autocorrelation Consistent
- i.i.d.: independent and identically distributed
- w.r.t.: with respect to
- s.t.: such that / subject to (context dependent)

**Define at first use**: "Generalized Method of Moments (GMM)"

## American vs. British English

**Spelling differences**:
- American: analyze, behavior, color, modeling, center
- British: analyse, behaviour, colour, modelling, centre

**Choose one and be consistent throughout**

**Finance journals typically accept either but prefer American English**

## Common Phrases by Section

### Introduction

- "financial contagion has attracted considerable attention"
- "understanding the transmission of shocks is crucial for"
- "we contribute to the literature in several ways"
- "our findings have important implications for"
- "the remainder of this paper is organized as follows"

### Literature Review

- "builds on the seminal work of..."
- "extends the analysis by..."
- "differs from prior studies in that..."
- "consistent with the findings of..."
- "we complement these studies by..."

### Methodology

- "to address the endogeneity concern, we..."
- "identification relies on the assumption that..."
- "the model parameters are estimated using..."
- "we construct the following moment conditions..."
- "stationarity requires that..."

### Results

- "Table X reports the estimation results"
- "the coefficient is statistically significant at the X% level"
- "this finding is robust to alternative specifications"
- "economically, this estimate implies..."
- "consistent with our hypothesis,..."
- "contrary to expectations,..."

### Conclusion

- "in this paper, we examine..."
- "our findings suggest that..."
- "these results have implications for..."
- "important avenues for future research include..."
- "subject to the caveat that..."

## Phrases to Avoid

**Avoid vague language**:
- ❌ "significant" → ✓ "significant at the 5% level (t=2.15)"
- ❌ "large effect" → ✓ "33-fold amplification effect"
- ❌ "interesting result" → ✓ "this finding suggests..."

**Avoid casual language**:
- ❌ "shows up in the data"
- ❌ "pretty robust"
- ❌ "sort of surprising"
- ❌ "it turns out that"

**Avoid hedge words (unless necessary)**:
- ❌ "seems to suggest"
- ❌ "appears to indicate"
- ❌ "might possibly be"

**Use precise language**:
- ✓ "suggests"
- ✓ "indicates"
- ✓ "provides evidence that"

## LaTeX and Mathematical Notation

**Common commands**:
```latex
\beta_{21}          % subscript
\hat{\beta}         % estimate
\bar{X}             % sample mean
\mathbb{E}[X]       % expectation
X \sim N(\mu,\sigma^2)  % distributed as
X \to \infty        % converges to
```

**Equations**:
- Number equations you reference: \begin{equation} ... \label{eq:model} \end{equation}
- Align multi-line equations: \begin{align} ... \end{align}
- Matrices: \begin{pmatrix} ... \end{pmatrix}

## Checklist for Terminology

Before submitting, verify:

- [ ] All acronyms defined at first use
- [ ] Consistent terminology throughout (don't switch between "contagion" and "spillover")
- [ ] Proper statistical terminology (hypothesis test, standard error, significance level)
- [ ] Greek symbols used consistently
- [ ] American OR British English (not mixed)
- [ ] No casual or colloquial language
- [ ] Precise language (avoid "seems", "appears" unless hedging is needed)
