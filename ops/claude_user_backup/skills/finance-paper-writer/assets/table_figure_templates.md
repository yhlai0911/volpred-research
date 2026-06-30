# Table and Figure Templates for Finance Papers

## Table Templates

### Table 1: Summary Statistics

```
Table 1: Summary Statistics of Daily Returns

                          Asset 1 (US)              Asset 2 (UK)
                    Mean    Std.Dev  Skew  Kurt    Mean    Std.Dev  Skew  Kurt
------------------------------------------------------------------------------------
Full Sample        0.030    1.40   -0.45  8.32    0.020    1.60   -0.38  7.94
  (1990-2008)     (0.010)  (0.05)

Crisis Period      0.012    2.10   -0.62 11.45    0.008    2.35   -0.55 10.32
  (2007-2009)     (0.025)  (0.12)

Normal Period      0.032    1.25   -0.39  7.21    0.023    1.45   -0.34  6.98
  (1990-2006)     (0.011)  (0.04)
------------------------------------------------------------------------------------
Observations        4,758                          4,758
Jump events (±3σ)   142 (3.0%)                    168 (3.5%)

Notes: Daily returns expressed in percentage terms. Standard errors in parentheses (first two columns only).
Skewness and kurtosis are sample moments. Jump events defined as returns exceeding ±3 standard deviations.
Sample period: January 1990 to December 2008 (T=4,758 trading days).
```

### Table 2: Baseline GMM Estimation Results

```
Table 2: GMM Estimation Results for Bivariate Hawkes Model

Panel A: Diffusion Parameters (Stage 1)
Parameter           Estimate    Std. Error    t-stat
-------------------------------------------------------
σ₁                  0.014       0.001         14.00***
σ₂                  0.016       0.001         16.00***
ρ                   0.390       0.045          8.67***

Panel B: Jump Parameters (Stage 2)
α                   20.300      9.300          2.18**
β₁₁                 17.100      6.700          2.55**
β₂₁                 13.100      6.100          2.15**
β₂₂                  7.100      6.500          1.09
λ_∞                  0.400      0.200          2.00**
γ₁                  33.300      5.000          6.66***
γ₂                  36.400      5.500          6.62***

Panel C: Implied Quantities
Avg. jump intensity (λ₁)        2.533
Avg. jump intensity (λ₂)        3.820
Half-life (days)                0.034
Avg. jump size (Asset 1)       -3.00%
Avg. jump size (Asset 2)       -2.75%

Panel D: Diagnostic Tests
GMM J-statistic                 12.4
  (p-value)                    (0.13)
Stationarity: α > β₁₁?          Yes (20.3 > 17.1)
Stationarity: α > β₂₂?          Yes (20.3 > 7.1)
Optimization converged?         Yes
-------------------------------------------------------
Observations                    4,758
Sample period                   1990-2008
Number of moment conditions     15
Number of parameters            7

Notes: Panel A reports diffusion parameters estimated from truncated returns (±3σ threshold).
Panel B reports Hawkes parameters estimated via two-step GMM. Standard errors computed using
Newey-West HAC estimator with automatic lag selection. *** p<0.01, ** p<0.05, * p<0.10.
GMM J-statistic tests overidentifying restrictions (df=8). Half-life computed as ln(2)/α.
```

### Table 3: Hypothesis Tests for Contagion

```
Table 3: Testing for Financial Contagion (H₀: β₂₁ = 0)

                            β̂₂₁     SE(β̂₂₁)    t-stat    p-value    Conclusion
----------------------------------------------------------------------------------
Baseline (1990-2008)       13.1      6.1        2.15      0.032     Reject H₀**

Subperiods:
  Crisis (2007-2009)       18.7      8.2        2.28      0.023     Reject H₀**
  Normal (1990-2006)        9.4      7.3        1.29      0.197     Fail to reject

Alternative thresholds:
  ±2.5σ                    11.8      5.9        2.00      0.045     Reject H₀**
  ±3.5σ                    14.6      6.8        2.15      0.032     Reject H₀**

Alternative methods:
  GMM with alt. moments    12.9      6.4        2.02      0.043     Reject H₀**
  Maximum likelihood       13.5      5.8        2.33      0.020     Reject H₀**
----------------------------------------------------------------------------------

Notes: Tests null hypothesis of no contagion from Asset 1 to Asset 2. Critical value for two-sided
test at 5% level is 1.96. ** indicates rejection at 5% significance level. All specifications include
diffusion and jump parameters as in Table 2.
```

### Table 4: Robustness Across Market Pairs

```
Table 4: Contagion Parameter β₂₁ Across Different Market Pairs

Source → Recipient     β̂₂₁     Std. Error    t-stat    Significant?
-----------------------------------------------------------------------
US → UK                13.1      6.1          2.15      Yes**
US → Japan             15.3      7.2          2.13      Yes**
US → Germany           12.8      6.8          1.88      Yes*
US → France            11.9      7.1          1.68      Yes*

UK → US                 3.2      4.5          0.71      No
Japan → US              2.8      5.1          0.55      No
Germany → US            4.1      5.3          0.77      No
-----------------------------------------------------------------------
Observations (each)    4,758
Sample period          1990-2008

Notes: Each row represents a separate bivariate Hawkes model estimation. "Source" market corresponds
to Asset 1, "Recipient" to Asset 2. Triangular structure imposed (β₁₂=0). Standard errors computed
using Newey-West HAC estimator. ** p<0.05, * p<0.10. Results show significant contagion from US to
other markets but not vice versa, consistent with US as originator of global financial shocks.
```

### Table 5: Economic Magnitudes of Contagion

```
Table 5: Economic Interpretation of Contagion Effects

                                        Baseline    No Contagion    Difference
                                        (β₂₁=13.1)  (β₂₁=0)
--------------------------------------------------------------------------------
Avg. jump intensity (Asset 2)           3.82        0.90           2.92 (324%)
Jump probability (after US jump)        0.38        0.04           0.34
Expected jumps per month               25.2         5.9           19.3
Avg. monthly return                    -1.2%       -0.3%          -0.9%
99% VaR (monthly)                      -8.7%       -5.2%          -3.5%

Counterfactual scenarios:
  β₂₁ = 0 (no contagion)               0.90
  β₂₁ = 6.5 (half baseline)            2.12
  β₂₁ = 13.1 (baseline)                3.82
  β₂₁ = 19.7 (1.5× baseline)           5.96
--------------------------------------------------------------------------------

Notes: All quantities computed by simulation with 100,000 paths over 252 trading days. "Baseline"
uses estimated parameters from Table 2. "No Contagion" sets β₂₁=0 while keeping other parameters
fixed. "Difference" shows absolute (and percentage) change. VaR = Value at Risk. Results show that
contagion accounts for approximately 75% of jump clustering in Asset 2.
```

## Figure Templates

### Figure 1: Time Series of Daily Returns

```
[Description for figure creation]

Panel A (top): Asset 1 (US) daily returns over time
- X-axis: Date (1990-2008)
- Y-axis: Return (%)
- Shade crisis periods (e.g., 2007-2009) in gray
- Mark jump events (±3σ) with red dots

Panel B (bottom): Asset 2 (UK) daily returns
- Same format as Panel A
- Use blue dots for jumps
- Align x-axes for visual comparison

Caption:
Figure 1: Daily Returns and Identified Jump Events

This figure plots daily returns for Asset 1 (US, Panel A) and Asset 2 (UK, Panel B) over the
sample period 1990-2008. Shaded regions indicate crisis periods (2007-2009). Red (blue) dots
mark identified jump events defined as returns exceeding ±3 standard deviations. The clustering
of jumps during crisis periods motivates the use of self-exciting intensity models.
```

### Figure 2: Sample and Theoretical Autocorrelation Functions

```
[4-panel figure]

Panel A (top-left): Asset 1 Autocorrelation
- X-axis: Lag (1-10)
- Y-axis: Autocorrelation
- Solid line: Sample ACF
- Dashed line: Theoretical ACF from estimated model
- Shaded area: 95% confidence band
- Include zero line

Panel B (top-right): Asset 2 Autocorrelation
- Same format as Panel A

Panel C (bottom-left): Cross-correlation Asset 1 → Asset 2
- X-axis: Lag (1-10)
- Y-axis: Cross-correlation
- Solid: Sample
- Dashed: Theoretical

Panel D (bottom-right): Cross-correlation Asset 2 → Asset 1
- Same format as Panel C
- Should show near-zero correlation (triangular structure)

Caption:
Figure 2: Model Fit - Sample versus Theoretical Autocorrelations

This figure compares sample autocorrelation functions (solid lines) with theoretical autocorrelations
implied by the estimated Hawkes model (dashed lines). Panel A shows Asset 1 autocorrelations, Panel B
shows Asset 2 autocorrelations. Panels C and D show cross-correlations in each direction. Shaded regions
represent 95% confidence intervals. The close fit between sample and theoretical moments indicates that
the Hawkes specification adequately captures the dynamic dependence structure. The near-zero cross-correlation
in Panel D confirms the validity of the triangular structure (β₁₂=0).
```

### Figure 3: Jump Intensity Impulse Responses

```
[2-panel figure]

Panel A: Response of λ₁ to own jump
- X-axis: Time after jump (hours or days)
- Y-axis: Intensity λ₁
- Baseline intensity λ_∞ as horizontal dashed line
- Jump at t=0 increases intensity by β₁₁
- Exponential decay back to baseline at rate α
- Show half-life point

Panel B: Response of λ₂ to Asset 1 jump
- X-axis: Time after jump
- Y-axis: Intensity λ₂
- Jump at t=0 increases λ₂ by β₂₁ (contagion)
- Exponential decay at rate α
- Compare to response from own jump (β₂₂, different color)

Caption:
Figure 3: Impulse Responses of Jump Intensities

This figure shows the impulse response of jump intensities to jump events. Panel A displays the response
of Asset 1's intensity (λ₁) to its own jump: intensity increases by β̂₁₁=17.1 and decays exponentially
at rate α̂=20.3 (half-life of 16 minutes, marked with vertical line). Panel B shows Asset 2's intensity
response to an Asset 1 jump (solid line, increase of β̂₂₁=13.1) compared to its response to an own jump
(dashed line, β̂₂₂=7.1). The similar magnitudes highlight the economically substantial nature of cross-border
contagion.
```

### Figure 4: Parameter Stability Over Time

```
[Rolling window estimation plot]

- X-axis: End date of 5-year rolling window
- Y-axis: Estimated β₂₁ (contagion parameter)
- Point estimates as solid line
- 95% confidence bands as shaded area
- Mark crisis periods with vertical lines

Caption:
Figure 4: Time Variation in Contagion Parameter

This figure plots the estimated contagion parameter β₂₁ from 5-year rolling window estimations.
Each point represents the GMM estimate using data from a 5-year window ending at the date shown.
Shaded region shows 95% confidence intervals. Vertical lines mark major crisis episodes: Asian
Financial Crisis (1997-98), Dotcom Crash (2000-02), and Global Financial Crisis (2007-09). The
contagion parameter exhibits significant time variation, increasing sharply during crisis periods,
consistent with amplified spillovers during market stress.
```

## Formatting Guidelines

### Table Formatting Rules

1. **Title**: Above table, starts with "Table X:"
2. **Column alignment**: Numbers right-aligned, text left-aligned
3. **Lines**: Use only horizontal lines (top, bottom, between panels)
4. **Decimal places**: Consistent within columns (typically 3 for estimates, 2 for SEs)
5. **Significance stars**: *** p<0.01, ** p<0.05, * p<0.10
6. **Standard errors**: In parentheses directly below estimates, OR in separate column
7. **Notes**: Below table, explain sample, method, significance levels, any special coding

### Figure Formatting Rules

1. **Caption**: Below figure, starts with "Figure X:"
2. **Caption length**: 3-5 sentences explaining what is shown and key takeaways
3. **Axes**: Always label with units
4. **Legend**: Include if multiple lines/series
5. **Font size**: Large enough to read when printed (minimum 10pt)
6. **Line styles**: Solid, dashed, dotted for different series
7. **Colors**: Should work in grayscale (use line styles, not just colors)
8. **Resolution**: 300 dpi minimum for submission

### Panel Layouts

**2-panel (side by side)**:
```
+----------------------+----------------------+
|      Panel A         |       Panel B        |
|   (e.g., Asset 1)   |   (e.g., Asset 2)    |
+----------------------+----------------------+
```

**4-panel (2×2 grid)**:
```
+----------------------+----------------------+
|      Panel A         |       Panel B        |
+----------------------+----------------------+
|      Panel C         |       Panel D        |
+----------------------+----------------------+
```

**3-panel (stacked)**:
```
+------------------------------------------+
|               Panel A                    |
+------------------------------------------+
|               Panel B                    |
+------------------------------------------+
|               Panel C                    |
+------------------------------------------+
```

## Common Mistakes to Avoid

### Tables

❌ **Too many decimal places**: 13.145672
✓ **Appropriate rounding**: 13.1

❌ **Missing standard errors**
✓ **Always include SEs**: 13.1 (6.1)

❌ **Inconsistent significance notation**
✓ **Use standard stars**: *, **, ***

❌ **No sample size or period**
✓ **Include in notes**: N=4,758; 1990-2008

❌ **Unexplained variables**
✓ **Define in notes or caption**

### Figures

❌ **Unlabeled axes**
✓ **Always label with units**

❌ **Too small font**
✓ **Readable when printed**

❌ **Color-dependent (invisible in grayscale)**
✓ **Use line styles + colors**

❌ **No caption**
✓ **Descriptive caption below**

❌ **Cluttered** (too many lines/series)
✓ **Focus on key comparisons**

## Checklist Before Submission

Tables:
- [ ] All tables numbered consecutively
- [ ] Titles above tables
- [ ] Column headers clear
- [ ] Numbers properly aligned and rounded
- [ ] Standard errors reported
- [ ] Significance levels indicated
- [ ] Notes explain sample, method, symbols
- [ ] Referenced in text before appearing

Figures:
- [ ] All figures numbered consecutively
- [ ] Captions below figures
- [ ] Axes labeled with units
- [ ] Legend included (if multiple series)
- [ ] Readable in grayscale
- [ ] High resolution (300 dpi)
- [ ] Referenced in text before appearing
- [ ] Files in acceptable format (.eps, .pdf, .png)
