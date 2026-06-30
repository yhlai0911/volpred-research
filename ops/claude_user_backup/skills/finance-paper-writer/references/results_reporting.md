# Results Reporting Guide for Finance Papers

## Overview

This guide provides best practices for reporting empirical results in finance papers, including parameter estimates, hypothesis tests, robustness checks, and economic interpretations.

## General Principles

1. **Show, don't just tell**: Present estimates, standard errors, and test statistics
2. **Interpret economically**: Translate statistical significance to economic magnitude
3. **Be precise**: Avoid vague language like "significant" without specifics
4. **Systematic presentation**: Discuss each parameter in order, table-by-table
5. **Compare to literature**: Relate your findings to existing studies

## Reporting Parameter Estimates

### Basic Format

**Template**:
```
The [parameter name] is estimated at [point estimate] (s.e. [standard error]),
which is [statistically significant/insignificant] at the [X]% level. This
implies [economic interpretation].
```

**Example**:
```
The mean reversion parameter α is estimated at 20.3 (s.e. 9.3), which is
statistically significant at the 5% level (t=2.18). This implies a half-life
of ln(2)/20.3 = 0.034 days, or approximately 16 minutes, suggesting that
jump intensity shocks dissipate rapidly.
```

### Reporting Multiple Parameters

**Panel-by-panel approach**:
```
Table 1 reports the GMM estimation results. Panel A presents the diffusion
parameters. The volatility estimates are σ̂₁=0.014 and σ̂₂=0.016, consistent
with typical daily volatility levels of 1.4% and 1.6% respectively. The
correlation coefficient ρ̂=0.39 indicates moderate positive co-movement
between the two markets during normal times.

Panel B reports the jump parameters. The self-excitation parameter for
Asset 1 is β̂₁₁=17.1 (s.e. 6.7, p<0.05), indicating that each jump increases
the subsequent jump intensity by 17.1 units. The contagion parameter β̂₂₁=13.1
(s.e. 6.1, p<0.05) is statistically significant and economically substantial,
as we discuss below. The long-run intensity λ̂_∞=0.40 suggests an average of
0.4 jumps per day, or approximately one jump every 2.5 days, in the absence
of self-excitation.
```

### Standard Phrases

**Significance**:
- "statistically significant at the 1% [5%, 10%] level"
- "highly significant (p<0.01)"
- "marginally significant (p<0.10)"
- "not statistically distinguishable from zero (t=0.54)"
- "precisely estimated (s.e.=0.002)"

**Magnitude**:
- "economically substantial"
- "economically negligible despite statistical significance"
- "first-order importance"
- "modest in magnitude"
- "an order of magnitude larger than"

**Comparison**:
- "consistent with prior findings in Smith (2020)"
- "larger than the estimate of 15.3 reported by Jones (2019)"
- "within the range of existing estimates [12-18]"
- "considerably smaller than suggested by earlier studies"

## Hypothesis Testing

### Null Hypothesis Tests

**Template**:
```
We test the null hypothesis H₀: [parameter] = [value]. The test statistic
is [formula] = [value], which [exceeds/does not exceed] the critical value
of [threshold] at the [X]% significance level. We therefore [reject/fail to
reject] H₀, providing [strong/weak/no] evidence for [alternative hypothesis].
```

**Example**:
```
We test the null hypothesis of no contagion, H₀: β₂₁=0. The Wald test
statistic is t = β̂₂₁/SE(β̂₂₁) = 13.1/6.1 = 2.15, which exceeds the critical
value of 1.96 at the 5% significance level. We therefore reject H₀, providing
strong evidence that jumps in the US market trigger jumps in the UK market
through a self-exciting contagion mechanism.
```

### Joint Hypothesis Tests

**Example**:
```
To test whether both self-excitation parameters are jointly zero (H₀: β₁₁=β₂₂=0),
we construct a Wald chi-square statistic with 2 degrees of freedom. The test
statistic is χ²(2)=15.7, with p-value <0.001, strongly rejecting the null.
This confirms that both markets exhibit significant within-market jump clustering.
```

### Comparing Parameter Magnitudes

**Example**:
```
To test whether contagion from US to UK (β₂₁) differs from UK self-excitation
(β₂₂), we compute t = (β̂₂₁-β̂₂₂)/SE(β̂₂₁-β̂₂₂) = (13.1-7.1)/8.5 = 0.71, which
is not significant (p=0.48). We cannot reject the null that cross-market and
within-market excitation are of similar magnitude, suggesting that contagion
effects are as important as domestic clustering.
```

## Economic Interpretation

### Translating Parameters to Quantities

**Half-life calculations**:
```
The estimated mean reversion speed α̂=20.3 implies a half-life of ln(2)/α =
0.034 days, or approximately 16 trading minutes. This rapid decay suggests
that elevated jump probabilities following a shock return to baseline levels
within a single trading session.
```

**Implied jump frequencies**:
```
The long-run intensity parameter λ̂_∞=0.40 implies an average of 0.4 jumps per
day in the absence of self-excitation. However, when self-excitation is active,
the average intensity becomes λ̂₁ = αλ_∞/(α-β₁₁) = 20.3×0.4/(20.3-17.1) = 2.53
jumps per day, a six-fold amplification.
```

**Average jump sizes**:
```
The exponential jump size parameter γ̂₁=33.3 implies an average jump size of
E[Z₁] = -1/γ₁ = -0.030, or -3.0%. This is consistent with the typical magnitude
of daily drawdowns during crisis episodes.
```

### Elasticities and Sensitivities

**Example**:
```
To assess the sensitivity of Asset 2's intensity to Asset 1 jumps, we compute
the elasticity ∂λ₂/∂N₁ = β₂₁. Our estimate β̂₂₁=13.1 implies that each jump in
Asset 1 increases Asset 2's instantaneous jump probability by 13.1 events per
unit time. Relative to the baseline intensity of λ_∞=0.40, this represents a
33-fold (13.1/0.4) amplification, highlighting the economically substantial
nature of cross-border contagion.
```

### Counterfactuals

**Example**:
```
To quantify the importance of contagion, we simulate the model under two
scenarios: (i) the estimated model with β̂₂₁=13.1, and (ii) a counterfactual
with β₂₁=0 (no contagion). Under the baseline model, Asset 2 experiences an
average of 3.8 jumps per day during periods following Asset 1 jumps. Under
the no-contagion counterfactual, this drops to 0.9 jumps per day, a 76%
reduction. This confirms that contagion is the primary driver of jump
clustering in Asset 2.
```

## Robustness Checks

### Organizing Robustness Results

**Standard structure**:
```
Section 4.X: Robustness Checks

We assess the robustness of our baseline results along several dimensions:
(1) alternative sample periods, (2) alternative jump detection thresholds,
(3) alternative moment conditions, and (4) alternative econometric methods.
Table X summarizes these robustness checks, reporting the contagion parameter
β₂₁ (our key parameter of interest) across specifications.
```

### Reporting Robustness Results

**Table format**:
```
Table 5: Robustness Checks for Contagion Parameter β₂₁

Specification                          β̂₂₁      Std. Error    t-stat
------------------------------------------------------------------
(1) Baseline (1990-2008)              13.1      6.1          2.15**
(2) Crisis period (2007-2009)         18.7      8.2          2.28**
(3) Normal period (1990-2006)          9.4      7.3          1.29
(4) 2.5σ jump threshold               11.8      5.9          2.00**
(5) 3.5σ jump threshold               14.6      6.8          2.15**
(6) Alternative moment set             12.9      6.4          2.02**
(7) Maximum likelihood                 13.5      5.8          2.33**
------------------------------------------------------------------
Notes: ** p<0.05, * p<0.10. All specifications include diffusion and jump parameters.
```

**Discussion**:
```
Table 5 demonstrates that our finding of significant US-to-UK contagion is
robust across specifications. The point estimate ranges from 9.4 to 18.7,
but remains economically meaningful and statistically significant in all cases
except the normal period subsample (row 3), where contagion appears weaker.
Notably, the crisis period estimate (row 2) is 50% larger than the full-sample
estimate, consistent with amplified spillovers during market stress. Alternative
thresholds for jump detection (rows 4-5) and alternative econometric methods
(rows 6-7) produce very similar estimates, confirming that our results are not
sensitive to these methodological choices.
```

### Sensitivity Analysis

**Example**:
```
To assess sensitivity to the choice of lag length in the autocorrelation
moments, we re-estimate the model using lags 1-5 (instead of 1-3 in the
baseline). Figure 3 plots the estimated contagion parameter β̂₂₁ as a function
of maximum lag K. The estimate is stable around 13-14 for K ≥ 3, suggesting
that our baseline choice K=3 captures the relevant autocorrelation structure
without overfitting.
```

## Diagnostic Tests

### Model Fit

**Comparing sample vs. theoretical moments**:
```
Figure 2 compares the sample autocorrelation functions (solid lines) with the
theoretical autocorrelations implied by the estimated model (dashed lines).
Panel A shows Asset 1, Panel B shows Asset 2. The theoretical moments closely
track the sample moments for lags 1-10, with an average absolute deviation of
0.012 for Asset 1 and 0.015 for Asset 2. This close fit suggests that the
Hawkes specification adequately captures the dynamic dependencies in the data.
```

### Overidentification Tests

**J-statistic**:
```
The GMM J-statistic for testing overidentifying restrictions is J=12.4, with
8 degrees of freedom (15 moments minus 7 parameters). The associated p-value
is 0.13, indicating that we do not reject the null that the overidentifying
restrictions are valid. This provides support for the model specification.
```

### Stationarity Verification

**Example**:
```
The stationarity conditions α > β₁₁ and α > β₂₂ are satisfied by our estimates:
α̂=20.3 > β̂₁₁=17.1 and α̂=20.3 > β̂₂₂=7.1. To assess how far we are from the
stationarity boundary, we compute 95% confidence intervals: α ∈ [2.1, 38.5],
β₁₁ ∈ [4.0, 30.2], β₂₂ ∈ [-5.6, 19.8]. While the confidence intervals overlap
slightly, the point estimates comfortably satisfy stationarity, and the
probability that α < β₁₁ is less than 5% based on bootstrap simulations.
```

## Comparing to Literature

### Benchmarking Your Results

**Template**:
```
Our estimate of [parameter] = [value] can be compared to existing studies.
[Author1 (Year1)] report [value1] for [similar sample/period]. [Author2 (Year2)]
find [value2] using [alternative method]. Our estimate is [consistent with/
larger than/smaller than] these prior findings, which may reflect [differences
in sample period/methodology/market conditions].
```

**Example**:
```
Our estimate of the contagion parameter β₂₁=13.1 can be compared to related
studies. Aït-Sahalia et al. (2015) report β=9.8 for US-to-European markets
during 1996-2010, while Chen and Li (2019) find β=16.3 for US-to-Asian
markets during the financial crisis. Our estimate falls between these values,
consistent with the intermediate level of financial integration between US
and UK markets. The larger crisis-period estimate of Chencorresponds to
heightened contagion during extreme market stress.
```

## Standard Phrases and Templates

### Opening a Results Section

```
Table [X] presents the [baseline/main] estimation results. Column [1] reports
[specification 1], while columns [2-4] show [alternative specifications]. Our
discussion focuses on column [1], which is our preferred specification because
[reason]. Results from alternative specifications are qualitatively similar and
discussed in Section [X].
```

### Discussing Individual Parameters

```
The [parameter name] is estimated at [value] (s.e. [se]), [significant/
insignificant] at the [X]% level. This [confirms/contradicts] our prior
expectation that [expectation], and is [consistent/inconsistent] with
[economic theory/prior studies]. Economically, this estimate implies [interpretation].
```

### Summarizing Robustness

```
Our key findings are robust to [list of variations]. Across [N] alternative
specifications reported in Table [X], the [parameter of interest] ranges from
[min] to [max] but remains [statistically significant/economically meaningful]
in all cases [except when...]. This robustness reinforces our confidence in
the [main conclusion].
```

### Concluding a Results Section

```
In summary, the results provide [strong/moderate/weak] evidence for [main
finding]. The [key parameter] is [statistically significant and economically
substantial], [robust to alternative specifications], and [consistent with
theoretical predictions]. These findings have important implications for
[application/policy], as we discuss in Section [X].
```

## Common Mistakes to Avoid

1. **Vague significance claims**: Don't say "β is significant." Say "β=13.1 (t=2.15, p<0.05)"

2. **Ignoring economic magnitude**: Don't stop at statistical significance; interpret what the number means

3. **Cherry-picking**: Report all specifications, not just those that "work"

4. **Missing standard errors**: Always report standard errors alongside point estimates

5. **No comparison**: Relate your estimates to existing literature

6. **Passive voice**: Use active voice: "We find β=13.1" not "β is found to be 13.1"

7. **Overinterpreting**: Be honest about limitations and alternative explanations

8. **Table without discussion**: Never present a table without discussing its contents in text

## Checklist for Results Section

Before submitting, verify that your results section:

- [ ] Presents all tables referenced in text
- [ ] Discusses each parameter systematically
- [ ] Reports point estimates, standard errors, and significance levels
- [ ] Provides economic interpretation for key parameters
- [ ] Includes hypothesis tests with clear H₀ and conclusion
- [ ] Shows robustness checks for main findings
- [ ] Compares results to existing literature
- [ ] Includes diagnostic tests (stationarity, model fit, overidentification)
- [ ] Uses consistent notation between text and tables
- [ ] Defines all new variables before using them
- [ ] Addresses both statistical and economic significance
- [ ] Acknowledges limitations or alternative interpretations
