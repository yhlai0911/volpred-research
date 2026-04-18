# High-Frequency Data Methodology for Financial Econometrics

Comprehensive guide to handling intraday/high-frequency financial data, with emphasis on microstructure noise, jump detection, and estimation challenges.

---

## Data Characteristics

### Time Scales

**Ultra-High Frequency** (Tick-by-tick):
- Every trade or quote update
- Irregular spacing (milliseconds to seconds)
- **Issues**: Bid-ask bounce, discreteness, asynchronous trading

**High Frequency** (1-min to 15-min):
- Regularly spaced intervals
- 1-min, 5-min, 10-min, 15-min bars
- **Sweet spot** for many applications

**Medium Frequency** (30-min to hourly):
- Less microstructure noise
- Sufficient observations per day
- Good for jump detection

### Trading Hours

**Taiwan Market** (TWSE + TAIFEX):
- **Regular Session**: 09:00 - 13:30 (4.5 hours)
- **After-hours** (Futures only): 15:00 - 05:00 next day
- **Total**: ~270 minutes regular trading

**Observations per day**:
- 1-min bars: 270
- 5-min bars: 54
- 15-min bars: 18
- 30-min bars: 9

### Data Quality Issues

1. **Missing data**: Holidays, system outages
2. **Bid-ask bounce**: Trades alternate between bid/ask
3. **Price discreteness**: Minimum tick size
4. **Asynchronicity**: Futures vs spot don't trade at exact same time
5. **Flash crashes**: Extreme outliers
6. **Stale prices**: No trading for extended periods

---

## Microstructure Noise

### The Problem

**Observed price** = **Efficient price** + **Noise**

```
Pᵒᵇˢ(t) = P*(t) + ε(t)
```

where:
- P*(t): True efficient price (random walk + jumps)
- ε(t): Microstructure noise (bid-ask bounce, discreteness, etc.)

**Consequence**: Naive estimators are biased

### Realized Variance Bias

**Naive realized variance**:
```
RV_naive = Σᵢ rᵢ²

where rᵢ = log(Pᵢ/Pᵢ₋₁)
```

**Under noise**:
```
E[RV_naive] = IV + 2nσ²_ε

where:
  IV = true integrated variance
  n = number of observations
  σ²_ε = noise variance
```

**Result**: As n↑, bias↑ (paradoxically, more data → worse estimates!)

### Solutions

#### 1. Sparse Sampling

**Idea**: Use lower frequency to reduce noise impact

**Example**: Use 5-min returns instead of 1-min

**Tradeoff**: Lose information, fewer observations

#### 2. Realized Kernel (Barndorff-Nielsen et al., 2008)

**Weighted sum**:
```
RK = Σᵢ rᵢ² + Σⱼ₌₁ᴴ k(j/H) Σᵢ rᵢ rᵢ₊ⱼ

where k(·) is kernel function (Parzen, Tukey-Hanning, etc.)
```

**Property**: Consistent for IV even with noise

#### 3. Pre-Averaging (Jacod et al., 2009)

**Smooth then sample**:
```
r̄ᵢ = Σⱼ₌₁ᵏⁿ g(j/kₙ) rᵢ₊ⱼ

where kₙ ~ n^(1/2)
```

**Then**:
```
PA-RV = Σᵢ r̄ᵢ²
```

#### 4. Two-Scales Realized Variance (Zhang et al., 2005)

**Use two frequencies**:
```
TSRV = RV_slow - (n_fast/n_slow) × bias_correction
```

**Intuition**: Slow frequency has little noise, fast frequency estimates noise

### Recommendation for Hawkes Estimation

**Don't use tick-by-tick data** for GMM moment conditions

**Use 5-min or 15-min returns**:
- Microstructure noise negligible
- Sufficient observations (54 or 18 per day)
- Clean jump identification

---

## Jump Detection Methods

### Fixed Threshold (Simplest)

**Method**:
```
Jump if |rₜ| > c × σ̂

where c = 3, 4, or 5
```

**Pros**: Simple, fast, intuitive

**Cons**: Threshold choice arbitrary, doesn't account for intraday patterns

### Percentile-Based Threshold

**Method**:
```
Jump if rₜ < percentile(r, 5%)  (negative jumps)
      or rₜ > percentile(r, 95%) (positive jumps)
```

**Pros**: Adaptive to data distribution

**Cons**: Circular (jumps define percentile, percentile defines jumps)

### Lee-Mykland (2008) Test

**Test statistic**:
```
L(t) = rₜ / √(BV(t))

where BV(t) = bipower variation (local volatility estimate)
```

**Jump if**:
```
|L(t)| > Φ⁻¹(1 - α/(2n)) + ... (size-correction)
```

**Pros**: Statistical test, controls false positive rate

**Cons**: Requires tuning window, sensitive to volatility estimation

### Barndorff-Nielsen & Shephard (2006) Test

**Compare**:
```
RV(t) vs BV(t)

where:
  RV = Σᵢ rᵢ²  (realized variance)
  BV = Σᵢ |rᵢ||rᵢ₋₁| (bipower variation)
```

**Test statistic**:
```
z = (RV - BV) / √(var_asymptotic)
```

**Jump if**: z > critical value

**Pros**: Formal asymptotic theory

**Cons**: Daily test (not intraday), low power

### Andersen, Dobrev, & Schaumburg (2012) Jump Test

**Generalization** of BNS using multiple power variations

**More robust** to market microstructure

### Recommendation for Hawkes Models

**For daily data**: Fixed threshold (-2%, -3σ) sufficient

**For high-frequency data**: Lee-Mykland (2008) preferred
- Accounts for time-varying volatility
- Individual jump detection (not just daily)
- Well-established in literature

---

## Intraday Volatility Patterns

### U-Shaped Pattern

**Empirical finding**: Volatility high at open/close, low mid-day

```
σ(t) = σ₀ × [a + b × U(t)]

where U(t) = function high at endpoints
```

**Implications**:
- Jump detection must account for this
- Standardize returns by intraday volatility

### Seasonal Adjustment

**Flexible Fourier Form**:
```
σ²(t) = exp(Σₖ aₖ sin(2πkt/T) + bₖ cos(2πkt/T))
```

**Polynomial**:
```
σ²(t) = a + bt + ct²
```

**Recommendation**: Estimate σ(t) from moving window, then standardize

---

## Synchronization Issues (Futures vs Spot)

### Problem

**Futures** and **Spot** don't trade at exactly same time:
- Futures trade 09:00:00.152
- Spot trades 09:00:00.387

**Naive matching** → mismatch error

### Solutions

#### 1. Previous Tick Synchronization

**Match** each futures trade to most recent spot trade

```python
def sync_previous_tick(futures_df, spot_df):
    merged = pd.merge_asof(
        futures_df,
        spot_df,
        left_on='timestamp',
        right_on='timestamp',
        direction='backward'
    )
    return merged
```

#### 2. Refresh Time Sampling (Harris et al., 1995)

**Sample only when BOTH assets have traded**

**Pros**: Perfect synchronization

**Cons**: Irregular spacing, fewer observations

#### 3. Linear Interpolation

**Interpolate** to common grid (e.g., every second)

**Cons**: Creates spurious autocorrelation

#### 4. Lead-Lag Adjustment

**Model** lead-lag relationship explicitly:
```
Sₜ = α + β Fₜ₋ₖ + εₜ
```

**Estimate** k (lag) first, then align

### Recommendation

For **5-min bars**: Synchronization less critical
- Use interval end points (09:05:00, 09:10:00, ...)
- Both assets have traded by interval end

For **tick data**: Use refresh time or previous tick

---

## Aggregation Methods

### OHLC Bars

**Open-High-Low-Close** for each interval

**Pros**: Rich information, captures intraday variation

**Cons**: Complex to use in GMM (need multi-dimensional moments)

### Last Price

**Use only close price** of each interval

**Pros**: Simple, standard

**Cons**: Ignores intraday info

### Volume-Weighted Average Price (VWAP)

```
VWAP = Σᵢ Pᵢ × Vᵢ / Σᵢ Vᵢ

where sum over all trades in interval
```

**Pros**: More robust to outliers

**Cons**: Requires volume data

### Recommendation for Hawkes GMM

**Use close prices** (last price of interval)
- Simplifies moment calculation
- Standard in literature
- Sufficient for identifying Hawkes parameters

---

## Sample Size Considerations

### Required Observations for GMM

**Daily data** (Δt = 1 day):
- Minimum: ~2500 obs (10 years)
- Recommended: 3000-5000 obs (12-20 years)

**High-frequency** (Δt = 5 min):
- Observations/day: 54
- Days needed: 2500/54 ≈ 46 days
- Recommended: 100-200 trading days for robust estimation

### Statistical Power

**More observations** → Better identification

**BUT** microstructure noise increases

**Optimal frequency** (Hansen & Lunde, 2006):
```
Δt* ~ n^(-0.5)  (for RV estimation)
```

**For Hawkes**: 5-15 min empirically works well

---

## Overnight Returns

### The Problem

**Futures** trade after hours, **Spot** doesn't

**Overnight jump**:
```
r_overnight = log(P_9:00 / P_close_previous)
```

**Contains**:
- Information accumulation overnight
- Market open effects
- Potential for large jumps

### Solutions

#### 1. Exclude Overnight Returns

**Simplest**: Only use intraday returns

**Loss**: Miss important jumps (earnings announcements, etc.)

#### 2. Model Separately

**Overnight jump intensity**:
```
λ_overnight = f(overnight hours, news, ...)
```

**Separate parameters** from intraday

#### 3. Scaling Adjustment

```
r_overnight_scaled = r_overnight × √(Δt_intraday / Δt_overnight)
```

**Questionable** theoretical justification

### Recommendation

**For futures-spot hedging research**:
- Model overnight separately
- Add overnight contagion parameters:
  - β^{open}_{FF}: Overnight futures jump → next day futures intensity
  - β^{open}_{SF}: Overnight futures jump → next day spot intensity

**Justification**: Different trading mechanisms, different dynamics

---

## Interval Moments (Critical for High-Frequency)

### Instantaneous vs Interval

**Instantaneous moments** (Δt → 0):
```
E[ΔX] = μ Δt + O(Δt²)
Var[ΔX] = σ² Δt + O(Δt²)
```

**Interval moments** (finite Δt):
```
E[ΔX] = ∫ₜᵗ⁺ᐩᵗ μ(s) ds
Var[ΔX] = ∫ₜᵗ⁺ᐩᵗ σ²(s) ds + jump component
```

### Why It Matters

For **daily data**: Δt = 1, instantaneous ≈ interval (small error)

For **5-min data**: Δt = 1/78, need interval formulas

**Aït-Sahalia et al. (2010) Appendix B**:
- Derives interval moment formulas
- More complex than instantaneous
- Required for correct high-frequency estimation

### Implementation

**Interval autocorrelation** (Appendix B):
```
Cov[ΔX_{t,t+Δ}, ΔX_{t+Δ,t+2Δ}] =
    (β/α²) [2 - e^{-αΔ} - e^{-2αΔ}] × (E[Z])² × λ̄
```

vs **Instantaneous**:
```
Cov[ΔX_t, ΔX_{t+Δ}] ≈ (β/α) e^{-αΔ} × (E[Z])² × λ̄ × Δ²
```

**Recommendation**: Implement Appendix B formulas for Δt < 1 hour

---

## Data Cleaning Protocol

### Step-by-Step

1. **Remove non-trading hours**
   - Keep only 09:00-13:30 for regular session
   - Handle after-hours separately

2. **Filter outliers**
   - Remove |r| > 5 × daily σ (flash crashes)
   - Manual inspection of largest 10 returns

3. **Handle missing data**
   - Linear interpolation for short gaps (<5 min)
   - Exclude long gaps (>1 hour)

4. **Aggregate to regular grid**
   - 5-min intervals: 09:00, 09:05, 09:10, ..., 13:30
   - Use last price in interval

5. **Synchronize futures-spot**
   - Align to same time grid
   - Check correlation (should be >0.9)

6. **Compute returns**
   - Log returns: rₜ = log(Pₜ/Pₜ₋₁)

7. **Detect jumps**
   - Apply Lee-Mykland test
   - Or fixed threshold after volatility adjustment

8. **Verify**
   - Plot time series, ACF, jump times
   - Check for data errors

### Python Example

```python
import pandas as pd
import numpy as np

def clean_high_freq_data(df, freq='5min'):
    """Clean high-frequency data for GMM estimation."""

    # 1. Filter trading hours
    df = df.between_time('09:00', '13:30')

    # 2. Aggregate to regular grid
    df_agg = df.resample(freq).last()

    # 3. Forward fill short gaps (max 2 intervals)
    df_agg = df_agg.fillna(method='ffill', limit=2)

    # 4. Drop remaining NaN
    df_agg = df_agg.dropna()

    # 5. Compute returns
    df_agg['return'] = np.log(df_agg['price'] / df_agg['price'].shift(1))

    # 6. Remove extreme outliers
    sigma_daily = df_agg['return'].std() * np.sqrt(252/54)  # Daily vol
    outliers = np.abs(df_agg['return']) > 5 * sigma_daily
    print(f"Removing {outliers.sum()} outliers")
    df_agg.loc[outliers, 'return'] = np.nan
    df_agg = df_agg.dropna()

    return df_agg
```

---

## Estimation Challenges

### Challenge 1: Explosion of Moment Conditions

**With 3 frequencies** × 50 moments each = 150 moments

**Issue**: Large covariance matrix Ŝ (150×150)
- Numerical instability
- Long computation time

**Solution**: Block diagonal approximation or PCA

### Challenge 2: Computational Cost

**5-min data**: ~200K observations over 10 years

**GMM iteration**: Compute 150 moments × 1000 optimizer iterations

**Solution**: Parallelize, use compiled code (Cython), GPU

### Challenge 3: Convergence

**More parameters + more moments** = harder optimization

**Solution**: Multi-stage initialization
1. Estimate subset of params with subset of moments
2. Fix some params, estimate others
3. Joint optimization with good starting point

---

## Robustness Checks for High-Frequency

### 1. Frequency Robustness

Estimate at **multiple frequencies**:
- 1-min, 5-min, 15-min, 30-min

**Expect**: Consistent parameter estimates across frequencies

**If not**: Specification issue or microstructure contamination

### 2. Subperiod Stability

Split sample into **quarters**:
- 2020 Q1, Q2, Q3, Q4

**Expect**: Stable parameters in normal periods, different in crisis

### 3. Microstructure Robustness

**Compare**:
- Raw prices vs VWAP
- Last vs mid-quote
- Different cleaning rules

**Expect**: Hawkes parameters robust, diffusion params may differ

### 4. Jump Detection Sensitivity

**Vary threshold**: 3σ, 4σ, 5σ or 5%, 10%, 15% percentile

**Expect**: β estimates somewhat sensitive, but qualitatively similar

---

## Key References

**Microstructure Noise**:
- Zhang et al. (2005): "Two-scales RV"
- Barndorff-Nielsen et al. (2008): "Realized kernel"
- Jacod et al. (2009): "Pre-averaging"

**Jump Detection**:
- Lee & Mykland (2008): "Jump test"
- Barndorff-Nielsen & Shephard (2006): "BNS test"
- Andersen et al. (2012): "ADS test"

**High-Frequency Econometrics**:
- Aït-Sahalia & Jacod (2014): "High-Frequency Financial Econometrics" (textbook)
- Hansen & Lunde (2006): "Realized variance and market microstructure noise"

**Interval Moments**:
- Aït-Sahalia et al. (2010): NBER w15850, Appendix B

---

## Checklist for Reviewing High-Frequency Papers

✅ **Data Description**
- [ ] Trading hours clearly stated?
- [ ] Frequency and sample size reported?
- [ ] Missing data handling explained?
- [ ] Outlier treatment described?

✅ **Microstructure**
- [ ] Acknowledged and addressed?
- [ ] Appropriate frequency chosen (not too high)?
- [ ] Synchronization method for multiple assets?

✅ **Jump Detection**
- [ ] Method clearly described?
- [ ] Threshold or test statistic justified?
- [ ] Intraday volatility pattern accounted for?

✅ **Estimation**
- [ ] Interval moments used (not instantaneous)?
- [ ] Computational details provided?
- [ ] Convergence verified?

✅ **Robustness**
- [ ] Frequency robustness check?
- [ ] Sensitivity to jump detection threshold?
- [ ] Subperiod stability analysis?
