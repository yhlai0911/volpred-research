<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

# Hawkes Process Methodology for Financial Applications

Comprehensive guide to Hawkes self-exciting point processes in financial econometrics, with emphasis on proper citations, identification strategies, and common pitfalls.

---

## Historical Background & Proper Citations

### Original Development

**Alan Hawkes (1971)** - "Spectra of some self-exciting and mutually exciting point processes"
- **DOI**: 10.1093/biomet/58.1.83
- **First paper** introducing self-exciting point processes
- **Must cite** for any Hawkes process application

**Hawkes & Oakes (1974)** - "A cluster process representation of a self-exciting process"
- Cluster representation (immigrants + offspring)
- Branching process interpretation

### Mathematical Foundation

**Daley & Vere-Jones (2003)** - "An Introduction to the Theory of Point Processes" (2nd ed.)
- **Chapter 13**: Self-exciting processes
- Standard reference for theoretical properties
- **Cite for**: Filtering, conditional intensity, stationarity conditions

### Financial Applications

**Bowsher (2007)** - "Modelling security market events in continuous time"
- **Journal of Econometrics**, 141(2), 876-912
- First major financial application
- Mid-quote changes in FX market

**Errais, Giesecke, & Goldberg (2010)** - "Affine point processes and portfolio credit risk"
- **SIAM Journal on Financial Mathematics**, 1, 642-665
- Credit risk application

**Aït-Sahalia, Cacho-Diaz, & Laeven (2015)** - "Modeling financial contagion using mutually exciting jump processes"
- **Journal of Financial Economics**, 117, 585-606
- **THE key paper** for bivariate Hawkes in finance
- Eurozone sovereign CDS contagion

**Aït-Sahalia, Laeven, & Pelizzon (2014)** - "Mutual excitation in Eurozone sovereign CDS"
- Working paper version with more technical details

### DO NOT Confuse

❌ **Hamilton (1989)** - "A new approach to the economic analysis of nonstationary time series"
- This is about **Markov regime-switching models**
- **NOT related to Hawkes processes**
- **Common mistake**: Citing Hamilton for Hawkes filtering

✅ **Correct**: "We use the standard Hawkes filter (Hawkes, 1971; Daley & Vere-Jones, 2003)"

❌ **Wrong**: "We use the Hamilton (1989) filter to compute jump intensities"

---

## Univariate Hawkes Process

### Model Specification

**Jump process**:
```
dN(t): counting process (jumps)
```

**Conditional intensity** (time-varying jump rate):
```
λ(t) = λ(t-) + dN(t)

dλ(t) = α(λ∞ - λ(t))dt + β dN(t)
```

**Components**:
- **λ∞**: Baseline intensity (long-run average)
- **α**: Mean reversion speed (decay rate)
- **β**: Self-excitation (jump size in intensity)

### Key Properties

**Stationarity condition**:
```
α > β  (REQUIRED)
```

**Stationary mean intensity**:
```
E[λ] = α λ∞ / (α - β)
```

**Branching ratio** (expected offspring per jump):
```
n = β / α < 1  (for stationarity)
```

**Half-life** (time for intensity to decay by 50%):
```
t_{1/2} = ln(2) / α
```

### Filtering (Recursive Intensity Computation)

**Exact filter** (continuous time):
```
λ(t) = λ∞ + (λ(tᵢ) + β - λ∞) e^{-α(t - tᵢ)}

where tᵢ is time of last jump before t
```

**Discrete-time approximation**:
```
λₜ₊₁ = λ∞ + (λₜ + β·Nₜ - λ∞)(1 - α·Δt)

where Δt is time step
```

**NOT Hamilton filter**: The above is from Hawkes (1971), not Hamilton (1989) regime-switching.

---

## Bivariate Hawkes Process

### Full Model (Mutual Excitation)

**Two assets**: F (futures), S (spot)

**Intensity dynamics**:
```
dλ_F(t) = α_F(λ∞_F - λ_F(t))dt + β_{FF} dN_F(t) + β_{FS} dN_S(t)
dλ_S(t) = α_S(λ∞_S - λ_S(t))dt + β_{SF} dN_F(t) + β_{SS} dN_S(t)
```

**10 parameters** (full model):
- Decay rates: α_F, α_S
- Baseline intensities: λ∞_F, λ∞_S
- Self-excitation: β_{FF}, β_{SS}
- Cross-excitation: β_{FS}, β_{SF}
- Jump sizes (if modeling returns): γ_F, γ_S

### Triangular Model (Simplified)

**Restriction**: β_{FS} = 0 (F does not affect S, or vice versa)

**Motivation**:
- Identification: Daily data may not separately identify all 4 β parameters
- Economic: Spot leads futures (or reverse)
- Computational: Fewer parameters, easier optimization

**7 parameters** (triangular):
- α (assume α_F = α_S for parsimony)
- λ∞ (assume λ∞_F = λ∞_S)
- β_{FF}, β_{SS}, β_{SF} (or β_{FS})
- γ_F, γ_S

### Stationarity Conditions

**Univariate**: α > β

**Bivariate** (sufficient):
```
α_F > β_{FF}
α_S > β_{SS}

Or more generally: spectral radius(B/A) < 1

where B = [β_{FF}  β_{FS}]    A = [α_F   0  ]
          [β_{SF}  β_{SS}]        [0    α_S ]
```

**Check**: Eigenvalues of B/A all < 1

---

## Combined Jump-Diffusion Model

### Aït-Sahalia et al. (2015) Specification

**Returns**:
```
dX_F(t) = μ_F dt + σ_F dW_F(t) + Z_F dN_F(t)
dX_S(t) = μ_S dt + σ_S dW_S(t) + Z_S dN_S(t)
```

**Jumps**:
- Z_i ~ Exponential(γ_i) with negative sign
- E[Z_i] = -1/γ_i
- Var[Z_i] = 1/γ_i²

**Intensities**:
```
dλ_F(t) = α(λ∞ - λ_F(t))dt + β_{FF} dN_F(t) + β_{FS} dN_S(t)
dλ_S(t) = α(λ∞ - λ_S(t))dt + β_{SF} dN_F(t) + β_{SS} dN_S(t)
```

**Total parameters**:
- Diffusion: σ_F, σ_S, ρ (3)
- Drift: μ_F, μ_S (2, often fixed from sample mean)
- Hawkes: α, λ∞, β_{FF}, β_{FS}, β_{SF}, β_{SS} (6)
- Jump size: γ_F, γ_S (2)
- **Total**: 13 parameters (11 if μ fixed, 9 if triangular model)

---

## Identification Strategies

### Problem: Too Many Parameters

With **daily data**, identifying all parameters is challenging:
- α_F vs α_S: Similar decay rates, hard to distinguish
- λ∞_F vs λ∞_S: Similar baseline intensities
- All 4 β parameters: Requires strong cross-correlation patterns

### Solution 1: Symmetry Restrictions

**Assume**:
```
α_F = α_S = α
λ∞_F = λ∞_S = λ∞
```

**Reduces**: 10 → 7 parameters

**Justification**: Often reasonable if assets are from same market

### Solution 2: Triangular Structure

**Assume**: β_{FS} = 0 (or β_{SF} = 0)

**Reduces**: 4 β parameters → 3

**Justification**: Economic theory (e.g., spot leads futures in price discovery)

### Solution 3: High-Frequency Data

**With intraday data**:
- More jumps observed → better β identification
- Finer time resolution → can separate α_F and α_S
- **All 10 parameters may be identifiable**

**Tradeoff**: Need to handle microstructure noise

### Solution 4: Multi-Frequency Moments

**Use moments at different frequencies**:
- 5-min aggregates
- 30-min aggregates
- 2-hour aggregates

**Intuition**: Different frequencies have different sensitivities to α, β

**Literature**: Todorov & Tauchen (2011), Aït-Sahalia & Jacod (2014)

---

## Two-Stage GMM Estimation

### Stage 1: Diffusion Parameters

**Motivation**: Separate diffusion from jumps

**Method**: Use truncated returns
```
Truncate: Remove |r_t| > 3σ

Estimate: σ̂_F, σ̂_S, ρ̂ from truncated sample
```

**Correction**: Apply bias correction for truncation
```
σ̂ = σ̂_truncated × correction_factor
```

**Typical correction**: 1.05-1.10 depending on threshold

### Stage 2: Jump Parameters via GMM

**Given**: Fixed σ_F, σ_S, ρ from Stage 1

**Estimate**: θ = (α, λ∞, β_{FF}, β_{SS}, β_{SF}, γ_F, γ_S)

**Moment conditions**:
1. Mean (2)
2. Variance (2) - diffusion component subtracted using Stage 1
3. Covariance (1)
4. Autocorrelations (6) - driven by Hawkes clustering
5. Cross-correlations (3-4) - driven by contagion β_{SF}, β_{FS}
6. Higher-order moments (4+) - identify γ_F, γ_S

**Total**: 15-21 moments

---

## Moment Formulas (Key Results)

### Mean (includes drift + jumps)

```
E[ΔX_i] = μ_i Δt + E[λ_i] E[Z_i] Δt

where E[λ_i] = α λ∞ / (α - β_{ii})  (stationary)
```

### Variance (diffusion + jump)

```
Var[ΔX_i] = σ_i² Δt + E[λ_i] E[Z_i²] Δt

where E[Z_i²] = 2/γ_i²  (exponential jumps)
```

### Autocorrelation (Hawkes clustering)

```
Cov[ΔX_{i,t}, ΔX_{i,t+k}] ∝ β_{ii} e^{-α k Δt}  (k > 0)
```

**Key**: Exponential decay with rate α

### Cross-correlation (Contagion)

```
Cov[ΔX_{F,t}, ΔX_{S,t+k}] ∝ β_{SF} e^{-α k Δt}  (k > 0)
```

**Key**: β_{SF} captures F → S contagion

### Higher-Order Moments

**Skewness** (3rd moment):
```
E[(ΔX_i)³] ∝ E[λ_i] E[Z_i³]
```

**Kurtosis** (4th moment):
```
E[(ΔX_i)⁴] ∝ E[λ_i] E[Z_i⁴] + 3σ_i⁴ Δt²
```

**Critical for**: Identifying jump size parameters γ_i

---

## Common Estimation Issues

### Issue 1: α Too Large

**Symptom**: α̂ > 500 or even > 1000

**Cause**: With daily data, α → ∞ as Δt → 0

**Solution**:
- This is actually OK! Just means jumps decay within one day
- Report half-life: t_{1/2} = ln(2)/α ≈ 0.001 days (minutes)
- **Don't force α to be small**

### Issue 2: β Near α

**Symptom**: β̂ ≈ 0.95 × α̂ (near non-stationarity)

**Cause**: Data shows strong persistence

**Solution**:
- Check if α - β > 0.01 α (at least 1% margin)
- If borderline, report sensitivity analysis
- Consider non-stationary alternative (explosive Hawkes)

### Issue 3: Negative Jump Intensities

**Symptom**: λ̂(t) < 0 in filtering

**Cause**: Parameter estimates violate stationarity

**Solution**:
- Impose constraints: α > β + ε in optimization
- Check λ∞ > 0
- Verify all β > 0

### Issue 4: Weak Identification

**Symptom**:
- Very large standard errors
- Condition number > 10⁶
- Estimates change drastically with small data changes

**Diagnosis**: Run `scripts/check_identification.py`

**Solutions**:
- Add more moments (higher-order, more lags)
- Impose symmetry restrictions
- Use high-frequency data
- Fix some parameters based on prior studies

---

## Interpretation of Parameters

### Economic Meaning

**α (Mean Reversion)**:
- **Large α** (>100): Jumps decay quickly (within hours)
- **Small α** (<10): Jumps decay slowly (over days)
- **Typical**: α = 50-150 for daily data

**β (Self-Excitation)**:
- **Large β** (>20): Strong clustering, jumps beget jumps
- **Small β** (<5): Weak clustering
- **Typical**: β = 10-25 for financial assets

**β_{SF} (Contagion F→S)**:
- **β_{SF} > 0**: Futures jumps cause spot jumps
- **β_{SF} = 0**: No contagion
- **Test**: H₀: β_{SF} = 0 using t-statistic

**λ∞ (Baseline)**:
- **Units**: Jumps per day (for daily Δt)
- **Typical**: 0.1 - 0.5 jumps/day
- **Interpretation**: Background jump rate without excitation

**γ (Jump Size)**:
- **E[|Z|] = 1/γ**: Average jump size
- **Typical**: γ = 30-50 → E[|Z|] = 2%-3%
- **Larger γ**: Smaller jumps

### Derived Quantities

**Average intensity**:
```
E[λ] = α λ∞ / (α - β)
```

**Jump clustering ratio**:
```
clustering = β / α < 1
```

**Expected jumps per day**:
```
jumps/day ≈ E[λ] × Δt × (trading days/year) / year
```

---

## Hypothesis Tests for Contagion

### Test 1: Is there contagion F→S?

**H₀**: β_{SF} = 0

**Test statistic**:
```
t = β̂_{SF} / SE(β̂_{SF})
```

**Decision**: |t| > 1.96 → Contagion at 5% level

### Test 2: Is contagion symmetric?

**H₀**: β_{SF} = β_{FS}

**Test statistic**:
```
W = (β̂_{SF} - β̂_{FS})² / [Var(β̂_{SF}) + Var(β̂_{FS}) - 2Cov(β̂_{SF}, β̂_{FS})]

W ~ χ²(1) under H₀
```

### Test 3: Joint significance

**H₀**: β_{SF} = β_{FS} = 0 (no contagion at all)

**Wald test**: 2 degrees of freedom

---

## Hawkes vs Other Models

### Hawkes vs Regime-Switching

**Hawkes**:
- Continuous intensity evolution
- Self-exciting (endogenous jumps)
- Exponential decay after jumps

**Hamilton Regime-Switching**:
- Discrete states (high/low volatility)
- Exogenous state transitions
- Markov chain dynamics

**Different models!** Don't confuse citations.

### Hawkes vs GARCH

**Similarities**:
- Both model volatility clustering
- Autocorrelation in squared returns

**Differences**:
- GARCH: Continuous volatility process
- Hawkes: Discrete jump clustering
- Hawkes explicitly models jump times

### Hawkes vs Jump-Diffusion (Merton)

**Merton (1976)**:
- Constant jump intensity λ
- No clustering, no contagion

**Hawkes**:
- Time-varying intensity λ(t)
- Self-exciting: recent jumps ↑ future jump probability
- Captures volatility clustering

---

## Software Implementation Notes

### Numerical Considerations

**Filtering**:
```python
def filter_intensity(jump_times, alpha, beta, lambda_inf, T):
    """Compute λ(t) at all jump times."""
    n = len(jump_times)
    intensity = np.zeros(n)
    intensity[0] = lambda_inf  # Initial condition

    for i in range(1, n):
        dt = jump_times[i] - jump_times[i-1]
        # Decay + jump
        intensity[i] = lambda_inf + (intensity[i-1] + beta - lambda_inf) * np.exp(-alpha * dt)

    return intensity
```

**Overflow prevention**:
```python
# If alpha very large, exp(-alpha * dt) → 0
if alpha * dt > 20:
    decay = 0
else:
    decay = np.exp(-alpha * dt)
```

### Parameter Bounds

**Recommended bounds** for optimization:
```python
bounds = [
    (1, 500),        # α
    (0.01, 2),       # λ∞
    (0.1, 50),       # β_{FF}
    (0.1, 50),       # β_{SS}
    (0, 50),         # β_{SF} (allow 0)
    (10, 100),       # γ_F
    (10, 100),       # γ_S
]
```

---

## Key References

**Must Cite**:
1. Hawkes (1971) - Original paper
2. Daley & Vere-Jones (2003) - Theoretical foundation
3. Aït-Sahalia et al. (2015) - Financial contagion application

**Good to Cite**:
4. Bowsher (2007) - First financial application
5. Errais et al. (2010) - Credit risk
6. Bacry et al. (2015) - Review of Hawkes processes

**For High-Frequency**:
7. Aït-Sahalia & Jacod (2014) - High-frequency methods
8. Todorov & Tauchen (2011) - Jump detection

**DO NOT Cite** (for Hawkes filtering):
- Hamilton (1989) - This is regime-switching, NOT Hawkes!

---

## Checklist for Reviewers

When reviewing a Hawkes process paper:

✅ **Proper citations**
- [ ] Hawkes (1971) cited?
- [ ] No Hamilton (1989) confusion?

✅ **Model specification**
- [ ] Stationarity conditions stated and checked?
- [ ] All parameters clearly defined?
- [ ] Jump distribution specified?

✅ **Identification**
- [ ] Symmetry restrictions justified?
- [ ] Triangular model justified if used?
- [ ] Identification check performed?

✅ **Estimation**
- [ ] Two-stage vs two-step terminology correct?
- [ ] Moment conditions clearly listed?
- [ ] Weight matrix properly constructed?

✅ **Results**
- [ ] Parameter estimates economically reasonable?
- [ ] Standard errors reported?
- [ ] Hypothesis tests for contagion?
- [ ] J-test for overidentification?

✅ **Robustness**
- [ ] Subperiod analysis?
- [ ] Alternative specifications?
- [ ] Sensitivity to threshold choice?
