# Methodology Writing Guide for Finance Papers

## Overview

This guide provides examples and standard terminology for describing econometric methods commonly used in empirical finance papers. The goal is to write clear, precise methodology sections that are accessible to finance researchers while maintaining technical rigor.

## General Principles

1. **Intuition before equations**: Always explain the economic logic before presenting mathematical formulation
2. **Build gradually**: Start with simple cases, then add complexity
3. **Define everything**: Every symbol, every assumption, every restriction
4. **Justify choices**: Explain why you use this method rather than alternatives
5. **Address identification**: What variation identifies each parameter?

## Writing About GMM Estimation

### Basic GMM Framework

**Opening paragraph** (establish context):
```
To estimate the model parameters, we employ the Generalized Method of Moments
(GMM) approach of Hansen (1982). GMM is particularly well-suited for our
setting because it does not require full distributional assumptions and can
exploit the closed-form expressions for the theoretical moments of the
Hawkes process.
```

**Moment conditions** (be explicit):
```
The GMM estimator minimizes the distance between sample moments and their
theoretical counterparts implied by the model. We construct J = 15 moment
conditions based on the first two unconditional moments and the autocorrelation
structure of returns:

(1) Two mean conditions: E[ΔX_{i,t}] = μ_i Δ, i = 1, 2
(2) Two variance conditions: E[(ΔX_{i,t})²] = σ_i² Δ + E[Z_{i}²] λ_i Δ
(3) One covariance condition: E[ΔX_{1,t} ΔX_{2,t}] = ρσ_1σ_2 Δ
(4) Six autocorrelation conditions: E[ΔX_{i,t} ΔX_{i,t-k}] for i=1,2 and k=1,2,3
(5) Six cross-correlation conditions: E[ΔX_{i,t} ΔX_{j,t-k}] for i≠j and k=1,2,3

where the theoretical expressions are derived from the infinitesimal generator
of the Hawkes process (Aït-Sahalia et al., 2015).
```

**Two-step GMM** (explain the procedure):
```
We implement a two-step GMM procedure. In the first step, we use the identity
matrix as the weighting matrix W₁ = I to obtain preliminary parameter estimates
θ̂₁. In the second step, we construct the optimal weighting matrix W₂ using
the Newey-West (1987) HAC estimator with automatic lag selection, and re-estimate
to obtain the final estimates θ̂₂. The two-step procedure ensures efficiency
under heteroskedasticity and autocorrelation of unknown form.
```

**Standard errors** (describe inference):
```
Standard errors are computed using the standard GMM formula:

Var(θ̂) = (1/T) (G'WG)⁻¹ G'WSWG (G'WG)⁻¹

where G = ∂m(θ)/∂θ is the Jacobian matrix of moment conditions, W is the
optimal weighting matrix, and S is the long-run covariance matrix of moment
conditions estimated using the Newey-West procedure. We compute G numerically
using centered finite differences with step size 10⁻⁶.
```

**Identification** (explain what identifies parameters):
```
Identification of the parameters follows from the distinct implications of
different parameters for the moment structure. The diffusion volatilities
(σ₁, σ₂, ρ) are primarily identified from the variance-covariance structure
of high-frequency returns. The jump parameters (γ₁, γ₂) govern the kurtosis
and are identified from fourth moments and extreme return realizations. The
Hawkes intensity parameters (α, β₁₁, β₂₁, β₂₂, λ_∞) determine the
autocorrelation pattern and are identified from the dynamic dependencies
in returns across different lags.
```

## Writing About Hawkes Processes

### Model Motivation

**Economic intuition first**:
```
Financial markets exhibit clustering of extreme events: large negative returns
tend to be followed by additional large negative returns over short time
horizons. This clustering or "volatility feedback" cannot be fully captured
by standard diffusion models with constant or deterministic volatility. We
therefore adopt a jump-diffusion framework where the jump intensity itself
is stochastic and influenced by past jumps—a self-exciting or Hawkes process.
```

**Hawkes framework**:
```
The Hawkes process, introduced by Hawkes (1971) in the context of seismology
and adapted to finance by Aït-Sahalia et al. (2015), models jump arrivals
through a conditional intensity process λ_t that increases instantaneously
when a jump occurs and then decays exponentially back to a baseline level.
This parsimonious specification captures both the clustering of jumps within
a single asset (self-excitation) and the spillover of jumps across assets
(cross-excitation or contagion).
```

### Bivariate Specification

**Asset dynamics**:
```
Consider two financial assets with log-price processes X₁,t and X₂,t. Each
asset's return follows a jump-diffusion process:

dX_{i,t} = μ_i dt + σ_i dW_{i,t} + Z_{i,t} dN_{i,t},  i = 1, 2

where μ_i is the drift, σ_i is the diffusion volatility, W_{i,t} is a standard
Brownian motion, N_{i,t} is a counting process for jumps, and Z_{i,t} represents
the jump size. The Brownian motions are correlated with Corr(dW₁, dW₂) = ρ.
```

**Jump intensity dynamics**:
```
The innovation of the Hawkes specification lies in the dynamics of jump
intensities λ_{i,t}. Rather than being constant or dependent solely on
exogenous state variables, λ_{i,t} responds endogenously to past jump events:

dλ_{1,t} = α(λ_∞ - λ_{1,t})dt + β_{11} dN_{1,t}

dλ_{2,t} = α(λ_∞ - λ_{2,t})dt + β_{21} dN_{1,t} + β_{22} dN_{2,t}

The first equation states that the intensity for Asset 1 mean-reverts to a
long-run level λ_∞ at speed α and jumps up by β_{11} whenever Asset 1
experiences a jump (self-excitation). The second equation allows Asset 2's
intensity to be affected by both its own jumps (β_{22}, self-excitation) and
Asset 1's jumps (β_{21}, cross-excitation or contagion).
```

**Triangular structure**:
```
We impose a triangular structure β_{12} = 0, meaning that jumps in Asset 2
do not directly trigger jumps in Asset 1. This restriction simplifies estimation
and is motivated by the empirical context: Asset 1 represents the US market,
which is typically considered the originator of global financial shocks, while
Asset 2 represents recipient markets (UK, Japan, etc.). This assumption can be
tested by examining residual cross-correlations.
```

**Parameter interpretation**:
```
The parameter α governs the speed of mean reversion: larger α implies faster
decay of jump intensity back to λ_∞. The half-life of an intensity shock is
ln(2)/α days. The self-excitation parameters (β_{11}, β_{22}) measure how
much each market's intensity increases following its own jump, capturing
within-market clustering. The contagion parameter β_{21} measures spillover:
each jump in Asset 1 increases Asset 2's intensity by β_{21} units. For
stationarity, we require α > max(β_{11}, β_{22}).
```

### Jump Size Distribution

**Specification**:
```
Jump sizes are assumed to follow independent exponential distributions:

Z_i ~ -Exp(γ_i) with probability 1  (negative jumps only)

This implies E[Z_i] = -1/γ_i and Var[Z_i] = 1/γ_i². The restriction to
negative jumps reflects our focus on downside risk and financial contagion,
which primarily concerns negative co-movements during crisis periods. The
exponential distribution provides analytical tractability while capturing
heavy tails.
```

## Writing About Two-Stage Estimation

### Stage 1: Diffusion Parameters

**Rationale for two-stage approach**:
```
We adopt a two-stage estimation strategy following the principle of
parsimony and computational efficiency. In the first stage, we estimate
the diffusion parameters (σ₁, σ₂, ρ) using truncated data that excludes
extreme observations likely to be contaminated by jumps. In the second
stage, conditional on the first-stage estimates, we estimate the jump and
intensity parameters using GMM. This approach exploits the near-separation
between diffusion and jump dynamics at high frequencies.
```

**Truncation procedure**:
```
To isolate the continuous diffusion component, we truncate returns exceeding
±3 standard deviations, where the standard deviation is computed using the
median absolute deviation (MAD) to ensure robustness to outliers. Specifically,
we exclude observation t if |ΔX_{i,t}| > 3 × 1.4826 × MAD(ΔX_i). This
threshold corresponds approximately to the 99.7th percentile under normality
but is determined by the robust MAD rather than the sample standard deviation
itself.
```

**Bias correction**:
```
Truncation induces a downward bias in the estimated volatilities because we
systematically remove large returns. To correct this bias, we multiply the
truncated sample volatilities by an adjustment factor derived from the
expected value of a truncated normal distribution. The bias correction
factor is approximately 1.05 for the ±3σ threshold, ensuring that the
corrected estimates are consistent for the true diffusion volatilities.
```

### Stage 2: Hawkes Parameters

**Conditional estimation**:
```
In the second stage, we treat the diffusion parameter estimates (σ̂₁, σ̂₂, ρ̂)
from Stage 1 as known and estimate the remaining parameters θ₂ = (α, β₁₁,
β₂₁, β₂₂, λ_∞, γ₁, γ₂) via GMM. The moment conditions used in Stage 2
depend on both the data and the fixed Stage 1 estimates, but asymptotic
theory for two-stage M-estimators (Newey and McFadden, 1994) ensures that
accounting for first-stage estimation error is asymptotically negligible
when sample size is large.
```

## Writing About Hypothesis Testing

### Testing for Contagion

**Null hypothesis**:
```
Our central hypothesis test concerns the contagion parameter β₂₁. Under the
null hypothesis of no cross-market contagion, we have H₀: β₂₁ = 0. This
restriction implies that jumps in Asset 1 do not directly affect the jump
intensity of Asset 2, ruling out self-exciting spillovers.
```

**Test statistic**:
```
We construct a Wald test statistic:

t = β̂₂₁ / SE(β̂₂₁)

where SE(β̂₂₁) is the standard error computed from the GMM variance-covariance
matrix. Under H₀ and standard regularity conditions, t follows a standard
normal distribution asymptotically. We reject H₀ at the 5% significance level
if |t| > 1.96.
```

**Economic interpretation**:
```
Rejection of H₀ provides evidence that Asset 1 jumps propagate to Asset 2
through an intensity feedback channel, consistent with financial contagion.
The economic magnitude of contagion is assessed by comparing β₂₁ to the
baseline intensity λ_∞: a ratio β₂₁/λ_∞ >> 1 indicates that contagion
effects dominate baseline jump probabilities during shock transmission.
```

### Testing Stationarity

**Stationarity conditions**:
```
For the Hawkes intensity process to be stationary, we require that mean
reversion dominates self-excitation:

α > β_{11}  and  α > β_{22}

If these conditions are violated, jump intensities explode (λ_{i,t} → ∞),
which is economically implausible and statistically inconsistent with
observed data. We verify that our parameter estimates satisfy these
inequalities and report confidence intervals to assess how far the estimates
are from the stationarity boundary.
```

## Standard Terminology and Phrases

### Describing Estimation Methods

**Strong phrases** (use these):
- "We employ GMM estimation to avoid strong distributional assumptions"
- "The model parameters are identified from the autocorrelation structure"
- "We implement a two-step procedure to improve efficiency"
- "Standard errors account for heteroskedasticity and autocorrelation"
- "The optimal weighting matrix ensures asymptotic efficiency"

**Weak phrases** (avoid these):
- "We use GMM" (too terse, no justification)
- "Parameters are estimated" (passive voice, no detail)
- "Standard errors are robust" (vague, what kind of robustness?)

### Describing Model Features

**Strong phrases**:
- "The self-exciting specification captures clustering of extreme returns"
- "Jump intensity mean-reverts to a long-run baseline at exponential rate α"
- "Cross-excitation parameter β₂₁ measures contagion from Asset 1 to Asset 2"
- "Triangular structure imposes that Asset 2 does not trigger Asset 1 jumps"
- "Stationarity requires mean reversion to dominate self-excitation: α > β"

**Weak phrases**:
- "The model has jumps" (uninformative)
- "Parameters affect the process" (vague)
- "We use Hawkes processes" (no intuition)

### Describing Identification

**Strong phrases**:
- "Diffusion volatilities are identified from high-frequency return variations"
- "Jump sizes are identified from the kurtosis and tails of the return distribution"
- "Self-excitation is identified from within-asset autocorrelation patterns"
- "Contagion is identified from lead-lag cross-correlations between assets"
- "Mean reversion speed α is identified from the decay of autocorrelations"

### Describing Inference

**Strong phrases**:
- "We reject the null of no contagion at the 5% significance level (t=2.15)"
- "The point estimate β₂₁=13.1 implies economically substantial spillovers"
- "Confidence intervals comfortably exclude zero, providing strong evidence"
- "Standard errors account for heteroskedasticity using Newey-West correction"

**Weak phrases**:
- "β₂₁ is significant" (provide t-stat and magnitude)
- "Results are robust" (robust to what? show evidence)
- "Standard errors are corrected" (corrected how?)

## Common Mistakes to Avoid

1. **Equations without context**: Never drop a 10-line equation without preamble or follow-up explanation

2. **Undefined notation**: Define every symbol when first introduced, even "standard" ones like E[·]

3. **Skipping identification**: Readers need to know what variation identifies each parameter

4. **Vague language**: "We estimate the model" → "We estimate the seven model parameters using GMM"

5. **Missing assumptions**: State all assumptions explicitly (e.g., independence, stationarity, distributional)

6. **No intuition**: Connect every equation back to economic logic

7. **Ignoring alternatives**: Justify why your method vs. alternatives (GMM vs. ML, two-stage vs. one-stage)

## Templates for Common Sections

### Introducing a New Model Component

```
[Economic motivation - why we need this feature]
Standard jump-diffusion models assume constant jump intensity, which cannot
explain the empirical clustering of extreme returns.

[Proposed solution]
We therefore allow jump intensity to be stochastic and self-exciting.

[Mathematical formulation]
Specifically, the intensity λ_t follows:
dλ_t = α(λ_∞ - λ_t)dt + β dN_t

[Interpretation]
This specification implies that each jump increases the conditional probability
of future jumps by amount β, and this elevated intensity decays exponentially
at rate α back to the baseline λ_∞.

[Parameter restrictions]
For stationarity, we require α > β to ensure mean reversion dominates
self-excitation.
```

### Describing an Estimation Procedure

```
[Method choice and justification]
We estimate the model parameters using [METHOD] because [REASON].

[Step-by-step procedure]
The estimation proceeds as follows:
(1) [First step and its purpose]
(2) [Second step and its purpose]
(3) [Final step]

[Inference]
Standard errors are computed using [FORMULA], which accounts for [ISSUES].

[Implementation details]
We implement the estimator using [SOFTWARE] with [OPTIMIZER] and check
convergence using [CRITERION].
```

### Reporting Identification

```
[General principle]
The model parameters are identified from distinct features of the data:

[Parameter-by-parameter]
- σ₁, σ₂, ρ: Identified from the variance-covariance structure of returns
- γ₁, γ₂: Identified from the kurtosis and tail thickness
- λ_∞: Identified from the unconditional mean jump frequency
- α: Identified from the decay rate of autocorrelations
- β₁₁, β₂₂: Identified from the strength of within-asset autocorrelation
- β₂₁: Identified from cross-asset lead-lag correlations

[Informal identification check]
As an informal check, we verify that these moments exhibit meaningful
variation in the data and are not nearly collinear.
```

## Additional Resources

For more examples of methodology writing:
- Journal of Financial Economics (JFE) papers on GMM
- Review of Financial Studies (RFS) papers on Hawkes processes
- Journal of Econometrics for technical exposition
