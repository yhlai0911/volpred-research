# GMM Best Practices for Financial Econometrics

A comprehensive guide to proper GMM (Generalized Method of Moments) estimation, terminology, and reporting standards.

---

## Critical Terminology Distinctions

### Two-Stage vs Two-Step GMM

**These are DIFFERENT concepts** - confusion is a major red flag in review.

#### Two-Stage GMM
- **Meaning**: Estimate DIFFERENT parameter sets in each stage
- **Stage 1**: Estimate subset of parameters (θ₁)
- **Stage 2**: Given θ̂₁, estimate remaining parameters (θ₂)
- **Example**: Hawkes jump-diffusion models
  - Stage 1: Diffusion parameters (σ_F, σ_S, ρ) from truncated data
  - Stage 2: Jump parameters (α, β, λ∞, γ) via GMM given diffusion params

#### Two-Step GMM
- **Meaning**: Estimate SAME parameters twice with different weight matrices
- **Step 1**: Use identity weight matrix (W = I) → get θ̂₁
- **Step 2**: Use optimal weight matrix (W = Ŝ⁻¹) based on θ̂₁ → get θ̂₂
- **Example**: Standard GMM optimization
  - Step 1: Quick rough estimate with W = I
  - Step 2: Efficient estimate with W = Newey-West HAC

#### Three-Stage GMM (Two-Stage + Two-Step)
- **Stage 1**: Diffusion parameters
- **Stage 2**: Jump parameters (Step 1: W = I)
- **Stage 3**: Jump parameters (Step 2: W = Ŝ⁻¹)
- **Used in**: Advanced Hawkes estimation (Aït-Sahalia et al., 2015)

### Correct Usage

✅ **CORRECT**:
- "We employ a two-stage GMM procedure. The first stage estimates diffusion parameters..."
- "Within the second stage, we use a two-step GMM approach: first with identity weight..."

❌ **WRONG**:
- "We use two-step GMM to separately estimate diffusion and jump parameters"
- Mixing "two-stage" and "two-step" interchangeably

---

## GMM Fundamentals

### Basic Setup

**Population moment conditions**:
```
E[g(data; θ₀)] = 0
```

**Sample moment conditions**:
```
ḡₙ(θ) = (1/n) Σᵢ g(dataᵢ; θ)
```

**GMM objective**:
```
Q(θ; W) = ḡₙ(θ)' W ḡₙ(θ)
```

**GMM estimator**:
```
θ̂ = argmin Q(θ; W)
```

### Identification Conditions

1. **Order Condition** (Necessary):
   - Number of moments (m) ≥ Number of parameters (p)

2. **Rank Condition** (Necessary & Sufficient):
   - rank(E[∂g/∂θ']) = p

**Check**: Use `scripts/check_identification.py`

---

## Weight Matrix Selection

### Identity Weight (W = I)

**When to use**:
- First step of two-step GMM
- When all moments have similar scale
- Preliminary estimation

**Pros**:
- Fast computation
- No matrix inversion
- Robust to misspecification

**Cons**:
- Inefficient (large standard errors)
- Equal weight to all moments

### Optimal Weight (W = Ŝ⁻¹)

**Newey-West HAC Estimator**:
```
Ŝ = Γ̂₀ + Σᵥ₌₁ᵍ [1 - v/(q+1)] (Γ̂ᵥ + Γ̂ᵥ')

where Γ̂ᵥ = (1/n) Σₜ₌ᵥ₊₁ⁿ gₜ gₜ₋ᵥ'
```

**Lag selection (q)**:
- Newey-West (1994): q = floor(4(n/100)^(2/9))
- Daily data (n≈5000): q ≈ 5-7
- High-frequency (n≈200K): q ≈ 30-40

**When to use**:
- Final estimates
- Standard error calculation
- Hypothesis testing

**Pros**:
- Asymptotically efficient
- Correct standard errors under HAC

**Cons**:
- Requires preliminary estimate
- Sensitive to lag choice
- Can be poorly conditioned

### Diagonal Weight

**W = diag(σ₁², σ₂², ..., σₘ²)⁻¹**

**When to use**:
- Moments have very different scales
- Full optimal weight is poorly conditioned
- Robustness check

---

## Moment Condition Design

### General Principles

1. **Relevance**: Each moment should identify specific parameter(s)
2. **Power**: Use moments with strong sensitivity to parameters
3. **Independence**: Avoid redundant moments
4. **Higher-Order**: Include for jump/heavy-tail models

### For Hawkes Jump-Diffusion Models

**Basic Moments (15 total)**:
1. Mean (2): E[ΔXF], E[ΔXS]
2. Variance (2): Var[ΔXF], Var[ΔXS]
3. Covariance (1): Cov[ΔXF, ΔXS]
4. Autocorrelation (6): ACF(k) for k=1,2,3; both assets
5. Cross-correlation (4): CCF(k) for k=1,2,3 (one direction if triangular)

**Enhanced Moments (+6)**:
- 3rd moments (2): Skewness of each asset
- 4th moments (2): Kurtosis of each asset
- Cross 3rd/4th (2): Cross-skewness, cross-kurtosis

**Total**: 21 moments for robust jump parameter identification

### Multi-Frequency Moments

**Advanced technique** for high-frequency data:

Use moments at multiple aggregation levels:
- 5-min returns: 50 moments
- 30-min returns: 50 moments
- 2-hour returns: 50 moments
- **Total**: 150 moments

**Literature support required**: Aït-Sahalia & Jacod (2014), Todorov & Tauchen (2011)

**Verification**: Use `scripts/verify_moment_conditions.py`

---

## Standard Error Computation

### Asymptotic Standard Errors

**GMM Covariance Matrix**:
```
Var(θ̂) = (1/n) (G' W G)⁻¹ G' W S W G (G' W G)⁻¹

where:
  G = E[∂g/∂θ']  (Jacobian)
  S = var(g)      (Long-run variance)
  W = weight matrix
```

**With optimal weight (W = S⁻¹)**:
```
Var(θ̂) = (1/n) (G' S⁻¹ G)⁻¹
```

### Numerical Jacobian

**Finite difference**:
```python
def jacobian(theta, moment_func, eps=1e-7):
    m = len(moment_func(theta))
    p = len(theta)
    J = np.zeros((m, p))

    for j in range(p):
        theta_plus = theta.copy()
        theta_plus[j] += eps
        J[:, j] = (moment_func(theta_plus) - moment_func(theta)) / eps

    return J
```

### Bootstrap Standard Errors

**When to use**:
- Asymptotic theory questionable
- Small sample size
- Suspected misspecification

**Block bootstrap** for time series:
```python
def block_bootstrap(data, block_size, n_boot=1000):
    n = len(data)
    n_blocks = n // block_size

    boot_estimates = []
    for b in range(n_boot):
        # Randomly select blocks
        blocks = np.random.choice(n_blocks, n_blocks, replace=True)
        boot_data = np.concatenate([data[i*block_size:(i+1)*block_size]
                                    for i in blocks])
        # Estimate on bootstrap sample
        boot_theta = gmm_estimate(boot_data)
        boot_estimates.append(boot_theta)

    return np.std(boot_estimates, axis=0)  # Bootstrap SE
```

**Block size**:
- Daily data: 20-30 days
- High-frequency: 1-3 days worth of observations

---

## Hypothesis Testing

### Wald Test (Parameter Restrictions)

**H₀: R θ = r**

**Test statistic**:
```
W = (R θ̂ - r)' [R Var(θ̂) R']⁻¹ (R θ̂ - r) ~ χ²(q)
```

**Example**: Test β₂₁ = 0 (no contagion)
```
R = [0 0 0 1 0 0 0]  (picks β₂₁ from parameter vector)
r = 0
q = 1 (one restriction)
```

### J-Test (Overidentification)

**Only valid when m > p** (overidentified)

**Test statistic**:
```
J = n · ḡₙ(θ̂)' Ŝ⁻¹ ḡₙ(θ̂) ~ χ²(m - p)
```

**Interpretation**:
- H₀: Model is correctly specified
- Large J → Reject H₀ (model misspecified)
- **Warning**: Low power in finite samples

**Reporting**:
```
J-statistic: 18.42
Degrees of freedom: 14  (21 moments - 7 parameters)
p-value: 0.187
Conclusion: Fail to reject correct specification
```

### t-Test (Individual Parameters)

**H₀: θⱼ = 0**

**Test statistic**:
```
t = θ̂ⱼ / SE(θ̂ⱼ) ~ N(0, 1) asymptotically
```

**Critical values**:
- 10% level: |t| > 1.645
- 5% level: |t| > 1.96
- 1% level: |t| > 2.576

---

## Robustness Checks (Mandatory)

### 1. Alternative Specifications

- Triangular vs full bivariate model
- Different lag specifications (max_lag = 2, 3, 5)
- With/without higher-order moments

### 2. Subperiod Analysis

- Pre-crisis vs crisis vs post-crisis
- First half vs second half
- Rolling window estimation

**Tools**: `scripts/assess_sample_split.py`

### 3. Alternative Thresholds

- Jump detection: -1.5%, -2%, -2.5%
- Truncation: 2.5σ, 3σ, 3.5σ
- Percentile-based: 5%, 10%, 15%

### 4. Frequency Robustness

For high-frequency data:
- 1-min, 5-min, 15-min, 30-min, hourly
- Should see consistency across frequencies

### 5. Bootstrap Inference

- Confirm asymptotic standard errors
- Check if significance holds

---

## Common Mistakes and How to Avoid Them

### ❌ Mistake 1: Confusing two-stage and two-step

**Problem**: "We use two-step GMM to estimate diffusion and jump parameters separately"

**Fix**: "We use a two-stage procedure: Stage 1 estimates diffusion, Stage 2 estimates jump parameters via two-step GMM"

### ❌ Mistake 2: Forgetting J-test

**Problem**: Reporting estimates without J-test for overidentified model

**Fix**: Always report J-statistic when m > p

### ❌ Mistake 3: Wrong standard errors

**Problem**: Using SE from last optimization step (not GMM SE)

**Fix**: Compute proper GMM covariance matrix:
```python
# WRONG
se_wrong = result.hess_inv.diagonal() ** 0.5

# CORRECT
G = jacobian(theta_hat, moment_func)
S = newey_west(moments, lags=5)
W = np.linalg.inv(S)
V = np.linalg.inv(G.T @ W @ G)
se_correct = np.sqrt(np.diag(V) / n)
```

### ❌ Mistake 4: Ignoring identification

**Problem**: Estimating without checking rank condition

**Fix**: Run `scripts/check_identification.py` BEFORE estimation

### ❌ Mistake 5: No robustness checks

**Problem**: Single specification only

**Fix**: Report at least 4-5 alternative specifications

---

## Reporting Template

### Main Results Table

```
Table 1: Two-Stage GMM Estimation Results

Panel A: Stage 1 - Diffusion Parameters
Parameter     Estimate    Std. Error    t-stat    p-value
σ_F           0.0156      0.0008        19.5      <0.001***
σ_S           0.0142      0.0007        20.3      <0.001***
ρ             0.783       0.018         43.5      <0.001***

Panel B: Stage 2 - Hawkes Jump Parameters (Two-Step GMM)
Parameter     Estimate    Std. Error    t-stat    p-value
α             125.3       8.2           15.3      <0.001***
λ∞            0.312       0.028         11.1      <0.001***
β_FF          18.7        2.1           8.9       <0.001***
β_SS          19.2        2.3           8.3       <0.001***
β_SF          17.8        2.5           7.1       <0.001***
γ_F           31.4        3.8           8.3       <0.001***
γ_S           28.9        3.5           8.3       <0.001***

Panel C: Model Diagnostics
Number of moments:                  21
Number of parameters:               7  (Stage 2 only)
Degrees of freedom:                 14
J-statistic:                        18.42
J-test p-value:                     0.187
Sample size:                        5,644 observations

Notes: Stage 1 uses truncated returns (|r| < 3σ) to estimate diffusion
parameters. Stage 2 uses two-step GMM: Step 1 with identity weight, Step 2
with Newey-West HAC optimal weight (5 lags). Standard errors computed from
GMM covariance matrix. Sample period: 2003-01-02 to 2025-10-30.
*** p<0.01, ** p<0.05, * p<0.1
```

---

## Software Implementation

### Python Example

```python
import numpy as np
from scipy.optimize import minimize, differential_evolution

class TwoStageGMM:
    def __init__(self, data):
        self.data = data

    def stage1_diffusion(self):
        """Estimate diffusion parameters from truncated data."""
        # Truncate outliers
        truncated = self.data[np.abs(self.data) < 3*np.std(self.data)]

        # Sample moments
        sigma = np.std(truncated)
        # Apply correction for truncation bias
        sigma *= 1.05

        return {'sigma': sigma}

    def stage2_jumps(self, diffusion_params):
        """Two-step GMM for jump parameters."""

        # Step 1: Identity weight
        result1 = differential_evolution(
            self.gmm_objective,
            bounds=self.bounds,
            args=(diffusion_params, np.eye(self.m))
        )
        theta1 = result1.x

        # Step 2: Optimal weight
        S = self.newey_west(theta1)
        W = np.linalg.inv(S)

        result2 = minimize(
            self.gmm_objective,
            theta1,
            args=(diffusion_params, W),
            method='BFGS'
        )

        return result2.x, W, S

    def gmm_objective(self, theta, diffusion_params, W):
        g = self.moment_conditions(theta, diffusion_params)
        return g.T @ W @ g
```

---

## Further Reading

**Essential References**:
- Hansen (1982): "Large sample properties of GMM estimators"
- Newey & West (1987): "HAC covariance matrix estimation"
- Hall (2005): "Generalized Method of Moments" (textbook)
- Andrews (1991): "Heteroskedasticity and autocorrelation consistent covariance matrix estimation"

**For Hawkes Models**:
- Aït-Sahalia et al. (2015): "Mutual excitation in Eurozone sovereign CDS"
- Aït-Sahalia, Laeven, & Pelizzon (2014): "Mutual excitation in credit default swaps"

**For High-Frequency**:
- Aït-Sahalia & Jacod (2014): "High-Frequency Financial Econometrics"
