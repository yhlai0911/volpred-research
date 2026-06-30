# Common Rejection Reasons in Financial Econometrics

A guide to frequent rejection reasons at top finance journals, with specific examples and how to avoid them.

---

## Category 1: Contribution Issues (30-40% of rejections)

### 1.1 Insufficient Novelty

**Rejection Example**:
> "The paper applies a known methodology (Hawkes processes) to a well-studied market (futures-spot hedging) without clear innovation. While technically sound, the contribution is incremental."

**How to Avoid**:
- **Be specific** about innovation in introduction
- Compare explicitly to prior work
- Highlight: New data, new market, new empirical findings
- Show economic significance (not just statistical)

**Fix Strategy**:
```markdown
❌ "We apply Hawkes processes to futures hedging"

✅ "We are the first to incorporate jump contagion into dynamic hedge ratios,
   showing that crisis-period hedging effectiveness improves by 23% when
   accounting for intensity spillovers (vs traditional OLS/GARCH approaches)"
```

### 1.2 Literature Not Adequately Covered

**Rejection Example**:
> "The authors fail to cite key papers in the futures hedging literature (Johnson 1960, Ederington 1979, Lien & Tse 2002). The positioning relative to GARCH hedging models is unclear."

**How to Avoid**:
- Cite seminal papers in EACH relevant area
- Recent papers (last 5 years) in target journal
- Acknowledge closely related work and explain differences
- Create comparison table (your approach vs prior)

**Template**:
```markdown
Our study differs from prior work in three key aspects:
1. Method: Hawkes jump-diffusion vs GARCH (Kroner & Sultan 1993)
2. Focus: Explicit contagion modeling vs variance-only (Lien & Tse 2002)
3. Data: High-frequency intraday vs daily (Yang & Allen 2005)
```

### 1.3 "So What?" Problem

**Rejection Example**:
> "The finding that β_{SF} > 0 is interesting but the economic implications are unclear. Why should practitioners or policymakers care about this parameter?"

**How to Avoid**:
- Connect to real-world decision problems
- Quantify economic impact (dollars, basis points, %)
- Policy implications section
- Robustness to transaction costs

**Fix**:
```markdown
❌ "We find significant contagion (β_{SF} = 17.8, p < 0.001)"

✅ "The estimated contagion (β_{SF} = 17.8) implies that futures market jumps
   increase spot volatility by 45% on average within 1 hour, leading to
   mispricing of ~12 basis points in hedging contracts. Our dynamic hedge ratio
   captures this effect, reducing hedging costs by NT$1.2M per billion hedged
   compared to static OLS ratios."
```

---

## Category 2: Methodology Issues (25-35% of rejections)

### 2.1 Identification Not Established

**Rejection Example**:
> "The authors claim to estimate 14 parameters but do not demonstrate identification. With daily data, separately identifying α_F, α_S, λ∞_F, λ∞_S is questionable."

**How to Avoid**:
- **Check identification** formally (Jacobian rank condition)
- Use scripts: `check_identification.py`
- Report condition number of Jacobian
- If weak: Impose and justify restrictions
- Monte Carlo: Show parameters recoverable

**Required**:
```markdown
We verify identification via:
1. Order condition: 21 moments ≥ 7 parameters ✓
2. Rank condition: rank(Jacobian) = 7 at estimates ✓
3. Condition number: 1.2×10⁴ (well-conditioned)
4. Monte Carlo: 1000 simulations show bias <5% for all parameters
```

### 2.2 Endogeneity Concerns

**Rejection Example**:
> "The contagion β_{SF} may be spurious due to common macro shocks. Have the authors considered that both assets respond to news, creating correlation without causal spillover?"

**How to Avoid**:
- **Acknowledge** potential endogeneity
- Control for common factors (market returns, VIX)
- Granger causality tests
- Instrumental variables if applicable
- High-frequency data helps (shorter window for confounds)

**Response**:
```markdown
We address endogeneity via:
1. High-frequency data (5-min) reduces confounding
2. Control for market-wide jumps (use TAIEX)
3. Lead-lag analysis confirms F→S direction (not S→F)
4. Robustness: Results hold excluding major news days
```

### 2.3 Standard Errors Incorrect

**Rejection Example**:
> "The reported standard errors appear to be from the optimizer's Hessian, not the correct GMM covariance matrix accounting for moment correlation."

**How to Avoid**:
- Use **GMM formula**: Var(θ) = (G'WG)⁻¹ G'WSW'G (G'WG)⁻¹ / n
- **Never** use optimization SE directly
- Report Newey-West HAC with lag selection
- Bootstrap as robustness check

**Correct Reporting**:
```python
# WRONG
se = np.sqrt(np.diag(result.hess_inv))

# CORRECT
G = numerical_jacobian(theta, moments)
S = newey_west_covariance(moments, lags=5)
W = np.linalg.inv(S)
V_gmm = np.linalg.inv(G.T @ W @ G)
se = np.sqrt(np.diag(V_gmm) / n)
```

### 2.4 Robustness Checks Missing

**Rejection Example**:
> "The paper reports a single specification. No robustness checks for alternative thresholds, subperiods, or frequency choices."

**How to Avoid**:
- **Minimum 4-5 robustness checks**:
  1. Alternative jump thresholds
  2. Subperiod analysis (crisis vs normal)
  3. Frequency robustness (if high-freq data)
  4. Alternative model specifications
  5. Bootstrap inference

**Table Template**:
```markdown
Table X: Robustness Checks

Panel A: Alternative Jump Thresholds
Threshold    β_{SF}   SE      t-stat
-1.5%        18.2     2.8     6.5***
-2.0% (base) 17.8     2.5     7.1***
-2.5%        16.9     2.6     6.5***

Panel B: Subperiod Analysis
Period       β_{SF}   SE      t-stat
Pre-crisis   15.2     3.1     4.9***
Crisis       23.4     4.2     5.6***
Post-crisis  16.8     2.9     5.8***
```

---

## Category 3: Empirical Design Issues (15-25% of rejections)

### 3.1 Sample Selection Bias

**Rejection Example**:
> "The sample period (2020-2023) coincides with COVID pandemic, raising concerns about generalizability. Results may be driven by abnormal market conditions."

**How to Avoid**:
- **Long sample**: Minimum 10 years for daily, 1 year for high-freq
- Include multiple market regimes
- Justify sample period explicitly
- Subperiod analysis showing consistency

**Fix**:
```markdown
❌ Sample: 2020-2023 (3 years)

✅ Sample: 2010-2023 (13 years)
   - Includes normal, crisis, recovery periods
   - Subperiod analysis confirms results hold across regimes
   - Out-of-sample: 2023-2024 for validation
```

### 3.2 Cherry-Picking Assets/Markets

**Rejection Example**:
> "Why only Taiwan futures market? Are results specific to this market or generalizable? Authors should test on multiple markets."

**How to Avoid**:
- Justify market choice (data availability, institutional features)
- If single market: Acknowledge limitation, suggest extensions
- If feasible: Test on 2-3 markets
- Compare to prior studies on same market

**Response**:
```markdown
Taiwan market is ideal for our research question because:
1. Liquid futures market with after-hours trading
2. High-frequency data available (not accessible for many markets)
3. Prior hedging studies (Yang 2005) provide benchmark

Limitation: Results specific to Taiwan. Future research should test on
US, European markets to assess generalizability.
```

### 3.3 Data Quality Concerns

**Rejection Example**:
> "The data cleaning procedure is not adequately described. How were outliers handled? What about non-trading hours for futures?"

**How to Avoid**:
- **Detailed data section**: Source, cleaning, filters
- Descriptive statistics table
- Show raw vs cleaned data comparison
- Justify all filter choices

**Required Description**:
```markdown
Data Cleaning Protocol:
1. Source: Taiwan Futures Exchange (TAIFEX), tick data
2. Regular hours: 09:00-13:30 (270 minutes)
3. Aggregation: 5-minute OHLC bars → 54 obs/day
4. Outlier filter: Remove |r| > 5σ (daily vol) → 23 obs removed (0.08%)
5. Missing data: Forward fill gaps <15 min, drop longer gaps
6. Final sample: 247,832 observations (4,589 trading days)
```

---

## Category 4: Writing & Presentation (10-15% of rejections)

### 4.1 Poor Writing Quality

**Rejection Example**:
> "The manuscript suffers from numerous grammatical errors and unclear exposition. The methodology section is particularly difficult to follow."

**How to Avoid**:
- Professional editing service
- Have colleagues read draft
- Clear, simple sentences (avoid complex nested clauses)
- Define all notation before use
- Proofread multiple times

**Common Errors**:
```markdown
❌ "The estimation we employ is two-step GMM which is efficient"
✅ "We employ two-step GMM estimation for efficiency"

❌ "By using high frequency data, the identification can be improved"
✅ "High-frequency data improves parameter identification"
```

### 4.2 Bullet Points in Main Text

**Rejection Example**:
> "The paper uses bullet points extensively in the main text, violating journal style guidelines. All content must be in prose form."

**How to Avoid**:
- **No bullet points** in main text (prose only)
- Bullet points OK in: Online appendix, slides, response letters
- Convert lists to flowing sentences

**Conversion**:
```markdown
❌ Our contributions are:
    • First application of Hawkes to hedging
    • High-frequency data analysis
    • 23% improvement in hedge effectiveness

✅ Our paper makes three contributions. First, we are the first to apply
   Hawkes processes to dynamic hedging. Second, we use high-frequency data
   to identify intraday contagion patterns. Third, we demonstrate that our
   approach improves hedge effectiveness by 23% relative to standard methods.
```

### 4.3 Equations Not Explained

**Rejection Example**:
> "Equation (7) appears without explanation. What is each term? Why is this specification appropriate?"

**How to Avoid**:
- **Every equation** gets 2-3 sentences
- Explain: What it represents, why it's specified this way, what's novel
- Define all symbols in text OR in table

**Template**:
```markdown
The conditional intensity follows the Hawkes specification:

  dλ_F(t) = α(λ∞ - λ_F(t))dt + β_{FF}dN_F(t) + β_{FS}dN_S(t)    (7)

Equation (7) captures three effects. The first term represents mean reversion
to the long-run intensity λ∞ at rate α. The second term (β_{FF}) captures
self-excitation: when futures jump, future jump probability increases. The
third term (β_{FS}) captures cross-excitation from spot to futures, which is
the key contagion channel of interest.
```

### 4.4 Tables Not Publication-Ready

**Rejection Example**:
> "Tables are poorly formatted with inconsistent decimal places and missing significance indicators."

**How to Avoid**:
- Use **LaTeX table** format (booktabs package)
- Consistent decimal places (2-3 for params, 1 for t-stats)
- Significance stars: *** p<0.01, ** p<0.05, * p<0.1
- Clear column headers
- Comprehensive notes

---

## Category 5: Reproducibility Issues (5-10% of rejections)

### 5.1 Code Not Provided

**Rejection Example**:
> "Authors must provide replication code and data (or data access instructions) per journal policy."

**How to Avoid**:
- Prepare replication package:
  - All estimation code
  - Data processing scripts
  - README with instructions
- Clean, documented code
- Test on fresh environment

### 5.2 Results Not Reproducible

**Rejection Example**:
> "We attempted to replicate Table 2 using the provided code but obtained different results (β_{SF} = 15.3 vs reported 17.8)."

**How to Avoid**:
- **Set random seeds** everywhere
- Document software versions (Python 3.10, NumPy 1.24, etc.)
- Test code on different machine
- Include sample output in README

```python
# Set all random seeds
np.random.seed(42)
random.seed(42)

# Document versions
"""
Requirements:
- Python 3.10+
- NumPy 1.24.0
- SciPy 1.10.0
- Pandas 2.0.0

Tested on:
- macOS 13.2
- Ubuntu 22.04
"""
```

---

## Category 6: Statistical Issues (10-15% of rejections)

### 6.1 Overfitting

**Rejection Example**:
> "With 150 moment conditions for 14 parameters, the model may be overfitting. The out-of-sample performance should be tested."

**How to Avoid**:
- Check degrees of freedom (m - p should be reasonable)
- J-test for overidentifying restrictions
- Out-of-sample validation
- Cross-validation if applicable

**Response**:
```markdown
We address overfitting concerns via:
1. J-test: p-value = 0.18 (fail to reject correct specification)
2. Out-of-sample: Estimate 2010-2020, test 2021-2023
3. Rolling window: Re-estimate every quarter, forecast next quarter
4. Shrinkage: Also report Ridge-GMM estimates (similar results)
```

### 6.2 Multiple Testing Not Addressed

**Rejection Example**:
> "The authors test 47 hypotheses (one for each contagion link) without correcting for multiple testing. Many 'significant' results may be false positives."

**How to Avoid**:
- Acknowledge multiple testing
- Apply Bonferroni or FDR correction
- Focus on economically largest effects
- Don't over-interpret marginal significance

**Fix**:
```markdown
We test contagion for 47 stock pairs. To address multiple testing, we:
1. Apply Bonferroni correction: α = 0.05/47 = 0.001
2. Report FDR q-values (Benjamini-Hochberg)
3. Focus on 12 pairs with largest economic magnitude (>15% effect)

Result: 38/47 pairs remain significant at Bonferroni-corrected level.
```

### 6.3 No Power Analysis

**Rejection Example**:
> "With N=500 daily observations, can the authors even detect the hypothesized effect sizes? A power analysis would strengthen confidence."

**How to Avoid**:
- Monte Carlo power study
- Report minimum detectable effect
- If underpowered: Acknowledge limitation

**Power Study**:
```python
def power_analysis(n, beta_true, alpha=0.05, n_sim=1000):
    """
    Compute power to detect beta != 0.

    Returns: Proportion of simulations where H0 rejected.
    """
    rejections = 0
    for _ in range(n_sim):
        # Simulate data under alternative
        data = simulate_hawkes(n, beta=beta_true)

        # Estimate
        beta_hat, se = gmm_estimate(data)

        # Test
        t_stat = beta_hat / se
        if abs(t_stat) > 1.96:
            rejections += 1

    return rejections / n_sim

# Report: Power = 0.92 to detect β = 15 with n=5000
```

---

## Category 7: Interpretation Issues (5-10% of rejections)

### 7.1 Correlation vs Causation

**Rejection Example**:
> "The authors interpret β_{SF} as causal contagion, but the evidence only supports correlation. Futures and spot may both respond to a common shock."

**How to Avoid**:
- Careful language: "association" vs "causal effect"
- Granger causality tests
- Lead-lag analysis
- Acknowledge limitations

**Fix**:
```markdown
❌ "Futures jumps CAUSE spot jumps"

✅ "Futures jumps are associated with increased spot jump intensity,
   consistent with causal spillover. However, we cannot fully rule out
   common shocks. Lead-lag analysis (futures leads by 2 minutes) and
   robustness to macro controls support causal interpretation."
```

### 7.2 Economic vs Statistical Significance

**Rejection Example**:
> "While β_{SF} is highly statistically significant (p<0.001), the economic impact is negligible (0.02% improvement in hedge ratio). Is this result practically meaningful?"

**How to Avoid**:
- **Always report** economic magnitude
- Translate parameters to interpretable quantities
- Compare to transaction costs
- Honest discussion of practical relevance

---

## Prevention Checklist

Before submitting to a top journal, verify:

### Contribution
- [ ] Clear statement of innovation in introduction
- [ ] Explicit comparison to 3-5 closest papers
- [ ] Economic significance quantified
- [ ] Policy/practical implications discussed

### Methodology
- [ ] Identification formally verified
- [ ] GMM standard errors correctly computed
- [ ] Minimum 4-5 robustness checks
- [ ] All assumptions stated and justified

### Empirical Design
- [ ] Sample period justified (≥10 years daily, ≥1 year high-freq)
- [ ] Data cleaning protocol described
- [ ] Descriptive statistics table
- [ ] Out-of-sample validation if forecasting

### Writing
- [ ] No bullet points in main text
- [ ] All equations explained
- [ ] Professional editing completed
- [ ] Tables in LaTeX format
- [ ] Figures high-resolution, clearly labeled

### Reproducibility
- [ ] Code provided (cleaned, documented)
- [ ] README with software versions
- [ ] Random seeds set
- [ ] Sample output included

### Statistics
- [ ] Multiple testing addressed if applicable
- [ ] Power analysis for key tests
- [ ] Overfitting checks (J-test, out-of-sample)
- [ ] Correct inference (no p-hacking)

---

## Recovery from Rejection

### Revise & Resubmit (R&R)

**R&R is good news!** (~30-50% acceptance rate)

**How to respond**:
1. Thank editor and reviewers
2. Address **every comment** (even minor ones)
3. Point-by-point response letter
4. Highlight changes in revised manuscript
5. Don't argue, provide additional analysis

**Response Letter Template**:
```markdown
We thank the editor and reviewers for constructive feedback that has
significantly improved the paper. Below we address each comment in detail.

Reviewer 1, Comment 1: "Identification is not established"

Response: We have added Section 4.3 "Parameter Identification" with:
- Formal rank condition verification (new Table 4)
- Condition number analysis
- Monte Carlo power study (new Figure 3)
These analyses confirm that all 14 parameters are well-identified.
Changes: Section 4.3 (pages 18-21), Table 4, Figure 3.
```

### Desk Reject → Resubmit Elsewhere

**Move down tier**:
- JFE → JBF
- JBF → JFM
- JoE → JBES

**Or change focus**:
- General journal → field journal
- International → regional journal

**What to change**:
- Address substantive criticisms
- Don't just resubmit identical paper
- Tailor to new journal's focus

---

## Common Mistakes by Career Stage

### PhD Students
- Overselling contribution
- Insufficient literature review
- Poor writing quality
- Missing robustness checks

### Junior Faculty
- Not enough economic intuition
- Overly complex models
- Neglecting policy relevance
- Insufficient replication materials

### Senior Faculty
- Not citing recent papers
- Unfamiliar with latest methods
- Dismissing reviewers' concerns
- Overconfidence in initial submission

---

## Final Wisdom

**Most common avoidable rejections**:
1. Weak contribution positioning (fix in intro)
2. Missing robustness checks (add 5-10 pages of checks)
3. No out-of-sample validation (split sample)
4. Poor writing (hire editor)
5. Incomplete replication package (test on clean machine)

**Remember**: Rejection is normal (even for great papers). Top journals reject 90-95% of submissions. Learn from reviews, improve, and persist.
