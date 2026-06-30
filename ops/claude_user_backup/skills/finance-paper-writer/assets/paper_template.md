# Academic Finance Paper Template

## Title Page (Separate file for review)

**Title**: Concise and Descriptive (max 15 words)
Example: "Financial Contagion Through Mutually Exciting Jump Processes: Evidence from International Markets"

**Authors**: Name, Affiliation, Email
**Date**: Month Year
**Acknowledgments**: Funding, helpful comments, etc.
**JEL Classification**: G12, G15, C58
**Keywords**: 5-7 keywords

---

## Main Manuscript Structure (40 pages maximum)

### Abstract (250 words max)

[Context: 1-2 sentences]
[Method: 1-2 sentences]
[Results: 2-3 sentences]
[Contribution: 1-2 sentences]

**Highlights** (3-5 bullets, max 85 characters each):
• [First key finding or contribution]
• [Second key finding]
• [Third key finding]
• [Fourth key finding - optional]
• [Fifth key finding - optional]

---

### 1. Introduction (4-6 pages)

#### Paragraph 1-2: Motivation (0.5-1 page)
- Start with economic phenomenon or puzzle
- Use concrete example (2008 crisis, COVID crash, etc.)
- Establish importance with data or policy relevance

[EXAMPLE TEXT:]
Financial crises rarely remain confined to their country of origin. The 2008
subprime mortgage crisis, which began in the United States, rapidly propagated
to European and Asian markets, ultimately costing the global economy an
estimated $X trillion. Understanding the mechanisms through which financial
shocks transmit across borders is crucial for...

#### Paragraph 3-4: Research Question (0.5 page)
- Clearly state what you investigate
- Explain why existing answers are inadequate
- Preview your approach

[EXAMPLE TEXT:]
This paper examines whether [specific question]. Existing studies have
documented [what's known], but [what's missing]. We address this gap by...

#### Paragraph 5-6: Methodology Preview (0.5 page)
- Briefly describe your method
- Highlight methodological contributions
- Mention data sources and sample period

[EXAMPLE TEXT:]
We employ a bivariate Hawkes jump-diffusion model estimated via GMM using
daily returns from [markets] over [period]. The Hawkes specification allows
for...

#### Paragraph 7-8: Main Findings (1 page)
- Summarize 2-3 key results
- Quantify effects when possible
- Connect to economic interpretation

[EXAMPLE TEXT:]
We obtain three main findings. First, we find significant contagion from US
to UK markets, with β₂₁=13.1 (p<0.05), implying that each US jump increases
UK jump intensity by 33-fold. Second,...

#### Paragraph 9-10: Contributions (1 page)
- List 3-4 distinct contributions
- Use numbered list for clarity
- Relate to existing literature

[EXAMPLE TEXT:]
Our paper contributes to the literature in several ways. First, methodologically,
we extend the Hawkes framework to allow for... Second, empirically, we provide
the first estimates of... Third, we show that... Fourth, our findings have
implications for...

#### Literature Review (integrate into Introduction, 1-2 pages)
- Organize by themes, not chronologically
- For each paper: what they do, what they find, how you differ
- Focus on recent top-journal papers (last 10 years)

[EXAMPLE STRUCTURE:]
**Financial Contagion Literature**:
[Author1] (Year1) examines... and finds... [Author2] (Year2) extends...
We differ by...

**Hawkes Process Literature**:
[Author3] (Year3) introduces... [Author4] (Year4) applies to... Our
contribution is...

#### Final Paragraph: Roadmap
[EXAMPLE TEXT:]
The remainder of this paper is organized as follows. Section 2 describes the
model and econometric specification. Section 3 discusses the data and
estimation procedure. Section 4 presents the results. Section 5 concludes
with policy implications and directions for future research.

---

### 2. Model and Econometric Specification (6-10 pages)

#### 2.1 Economic Motivation (1 page)
- Explain why you need this model
- Discuss stylized facts it should capture
- Preview key features

#### 2.2 Asset Price Dynamics (1-2 pages)
- Start with general setup
- Present jump-diffusion equation
- Define each component
- Specify distributional assumptions

[EXAMPLE EQUATIONS:]
```
dX_{i,t} = μ_i dt + σ_i dW_{i,t} + Z_{i,t} dN_{i,t},  i = 1, 2

where:
- X_{i,t}: log-price of asset i
- μ_i: drift parameter
- σ_i: diffusion volatility
- W_{i,t}: standard Brownian motion with Corr(dW₁,dW₂) = ρ
- N_{i,t}: counting process for jumps
- Z_{i,t}: jump size ~ -Exp(γ_i)
```

#### 2.3 Jump Intensity Dynamics (2-3 pages)
- Present Hawkes intensity specification
- Explain self-excitation and cross-excitation
- Derive stationarity conditions
- Discuss parameter interpretation

[EXAMPLE EQUATIONS:]
```
dλ_{1,t} = α(λ_∞ - λ_{1,t})dt + β_{11} dN_{1,t}
dλ_{2,t} = α(λ_∞ - λ_{2,t})dt + β_{21} dN_{1,t} + β_{22} dN_{2,t}

Stationarity: α > max(β₁₁, β₂₂)
Half-life: t_{1/2} = ln(2)/α
```

#### 2.4 Moment Conditions (2-3 pages)
- Derive theoretical moments from model
- Present moment conditions explicitly
- Explain economic intuition for each moment
- Discuss identification

[EXAMPLE:]
```
We construct J=15 moment conditions:

E[ΔX_{i,t}] = μ_i Δ                                    (Mean)
E[(ΔX_{i,t})²] = σ_i² Δ + (1/γ_i²) λ_i Δ            (Variance)
E[ΔX_{1,t}ΔX_{2,t}] = ρσ_1σ_2 Δ                      (Covariance)
E[ΔX_{i,t}ΔX_{i,t-k}] = f(α,β,λ,k)                  (Autocorrelation)
E[ΔX_{i,t}ΔX_{j,t-k}] = g(α,β,λ,k), i≠j            (Cross-correlation)

where f(·) and g(·) are derived from the infinitesimal generator.
```

#### 2.5 GMM Estimation (1-2 pages)
- Present GMM objective function
- Explain two-step procedure
- Describe weighting matrix
- Discuss standard errors

[EXAMPLE:]
```
The GMM estimator minimizes:

Q(θ) = m_T(θ)' W m_T(θ)

where m_T(θ) = (1/T)Σ_t g_t(θ) are sample moment conditions and W is the
weighting matrix.
```

---

### 3. Data and Sample Selection (2-3 pages)

#### 3.1 Data Sources
- Describe each data source with citation
- Report frequency and coverage
- Mention any data cleaning procedures

[EXAMPLE:]
Data on daily stock market returns are obtained from [source]. The sample
covers [period], yielding T=[number] observations. We exclude weekends,
holidays, and days with missing data, resulting in...

#### 3.2 Variable Construction
- Explain how you compute key variables
- Define jump identification method
- Discuss any transformations

#### 3.3 Summary Statistics (1 page + Table 1)
- Present Table 1: Summary Statistics
- Discuss mean, volatility, skewness, kurtosis
- Highlight patterns relevant to model (e.g., negative skewness, excess kurtosis)

[EXAMPLE TABLE:]
Table 1: Summary Statistics

Variable    Mean     Std.Dev.  Skewness  Kurtosis   Min      Max
Asset 1   0.0003    0.014     -0.45     8.32      -0.089   0.067
Asset 2   0.0002    0.016     -0.38     7.94      -0.095   0.071

#### 3.4 Preliminary Analysis
- Show time series plots (Figure 1)
- Display autocorrelation functions (Figure 2)
- Identify jump events visually

---

### 4. Results (8-12 pages)

#### 4.1 Baseline Estimation Results (2-3 pages + Table 2)

**Table 2: Baseline GMM Estimation Results**

- Present all parameter estimates with standard errors
- Report t-statistics and significance stars
- Include diagnostic statistics (J-statistic, convergence)

**Discussion**:
- Discuss each parameter systematically
- Report statistical significance
- Provide economic interpretation
- Compare half-lives, jump frequencies, etc.

[EXAMPLE TEXT:]
Table 2 reports the GMM estimation results. The mean reversion parameter
α is estimated at 20.3 (s.e. 9.3), statistically significant at the 5% level
(t=2.18). This implies a half-life of 0.034 days or approximately 16 minutes...

#### 4.2 Contagion Testing (1-2 pages)
- State null hypothesis: H₀: β₂₁=0
- Report test statistic and p-value
- Interpret result economically
- Compute economic magnitudes (amplification factor, etc.)

#### 4.3 Robustness Checks (2-3 pages + Table 3-4)

**Table 3: Robustness to Alternative Specifications**

Test:
- Alternative sample periods (crisis vs. normal)
- Alternative jump thresholds
- Alternative moment sets
- Alternative methods (ML vs. GMM)

**Table 4: Robustness to Alternative Markets**

- Replicate analysis for different market pairs
- Check if findings generalize

**Discussion**:
- Summarize patterns across robustness checks
- Note any cases where results differ
- Explain potential reasons for differences

#### 4.4 Model Diagnostics (1-2 pages + Figure 3)

**Figure 3: Sample vs. Theoretical Moments**

- Plot autocorrelations (sample vs. fitted)
- Show cross-correlations
- Display residual analysis

**Tests**:
- Stationarity: Verify α > β
- Model fit: Average absolute deviation
- Overidentification: J-statistic

#### 4.5 Economic Implications (1-2 pages)
- Translate findings to policy-relevant quantities
- Compute counterfactuals
- Discuss implications for regulation, portfolio allocation, etc.

---

### 5. Conclusion (2-3 pages)

#### Paragraph 1: Summary
- Restate research question (in fresh words)
- Summarize methodology (1 sentence)
- List key findings (bullet points OK)

[EXAMPLE:]
This paper examines financial contagion through mutually exciting jump
processes. Using GMM estimation of a bivariate Hawkes model on US and UK
markets from 1990-2008, we find: (i) significant contagion from US to UK,
(ii) amplification during crises, and (iii) rapid mean reversion of intensity.

#### Paragraph 2-3: Economic and Policy Implications
- Connect to broader questions
- Discuss policy relevance
- Relate to current events if applicable

[EXAMPLE:]
These findings have important implications for regulatory policy. The
significant contagion parameter suggests that shocks originating in the US
rapidly transmit to UK markets, implying that...

#### Paragraph 4: Limitations and Extensions
- Acknowledge model assumptions
- Discuss potential extensions
- Suggest specific future research directions

[EXAMPLE:]
Our analysis is subject to several limitations. First, the triangular structure
assumes unidirectional contagion, which may not hold during simultaneous
crises. Second, we focus on negative jumps only, abstracting from positive
jumps. Third,... Future research could extend the model to allow for...

**Avoid**:
- New results
- New citations
- Verbatim repetition of abstract
- Overstating contributions
- Vague "more research is needed"

---

### References (3-5 pages)

Format: Author-year (see JBF style guide)

Example:
```
Aït-Sahalia, Y., Cacho-Diaz, J., Laeven, R.J.A., 2015. Modeling financial
contagion using mutually exciting jump processes. Journal of Financial
Economics 117 (3), 585–606.

Hansen, L.P., 1982. Large sample properties of generalized method of moments
estimators. Econometrica 50 (4), 1029–1054.
```

---

### Online Appendix (Optional, no page limit)

**Appendix A: Proofs**
- Derive theoretical moments
- Prove identification
- Derive asymptotic distribution

**Appendix B: Additional Robustness**
- Extended robustness tables
- Additional subsamples
- Alternative specifications

**Appendix C: Replication**
- Data sources and construction
- Code availability
- Step-by-step instructions

---

## Page Count Guidelines

| Section | Typical Pages |
|---------|--------------|
| Abstract | 1 |
| Introduction | 4-6 |
| Model & Econometrics | 6-10 |
| Data | 2-3 |
| Results | 8-12 |
| Conclusion | 2-3 |
| References | 3-5 |
| Tables (5-8 tables) | 5-8 |
| Figures (4-6 figures) | 2-3 |
| **Total** | **~40** |

## Formatting Checklist

- [ ] Double-spaced, 12pt font
- [ ] 1-inch margins
- [ ] Line numbers (for review)
- [ ] Page numbers
- [ ] All equations numbered
- [ ] All tables and figures numbered
- [ ] All acronyms defined
- [ ] Consistent notation
- [ ] Author info removed (for blind review)
