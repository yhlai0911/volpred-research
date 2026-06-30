---
name: academic-finance-reviewer
description: Conduct rigorous peer review of financial econometrics research (papers, grant proposals, methodology sections) targeting top-tier journals (JBF, JFE, JoE, RFS). Evaluate methodological rigor (GMM estimation, Hawkes models, high-frequency data), literature support for innovation claims, writing style compliance, empirical design robustness, and citation accuracy. Provide structured critique with scoring rubrics and actionable improvement suggestions.
---

# Academic Finance Reviewer

This skill enables rigorous academic peer review of financial econometrics research materials, including complete manuscripts, research grant proposals, methodology sections, and revision response letters. The skill applies the standards of top-tier finance and econometrics journals (Journal of Banking & Finance, Journal of Financial Econometrics, Journal of Econometrics, Review of Financial Studies, Journal of Futures Markets, Finance Research Letters) to provide comprehensive, actionable feedback.

## When to Use This Skill

Use this skill when:
- Conducting pre-submission review of complete academic papers targeting top-tier finance/econometrics journals
- Evaluating research grant proposals (e.g., NSTC/MOST applications) for methodological soundness
- Reviewing specific manuscript sections (methodology, empirical results) for technical accuracy
- Assessing revision response letters for thoroughness and persuasiveness
- Checking compliance with journal-specific formatting and writing standards

Do NOT use this skill for:
- General proofreading or copy-editing (use standard editing tools instead)
- Reviewing non-financial/non-econometric research
- Quick grammar checks (this skill focuses on substantive academic critique)

## Core Review Process

Execute reviews in 4 progressive levels, adjusting depth based on document type and user needs:

### Level 1: Rapid Scan (5 minutes)

**Document Classification**
- Identify document type: complete paper, grant proposal, section fragment, or revision letter
- Confirm target journal(s) if specified
- Assess initial fit: Does scope, length, and format match target venue?
- Flag immediate disqualifiers (e.g., 60-page paper for 40-page limit journal)

**Output**: Brief assessment of suitability and recommended review depth

### Level 2: Structural Review (15-20 minutes)

**Section Completeness**
- For papers: Verify presence of Introduction, Literature Review, Methodology, Results, Conclusion
- For grant proposals: Check Background, Methods, Timeline, Budget Justification, Expected Outcomes
- For revision letters: Confirm point-by-point response structure

**Logical Flow**
- Assess narrative coherence across sections
- Check if empirical strategy follows from research questions
- Verify results discussion connects to hypotheses

**Presentation Quality**
- Evaluate table and figure quality (clarity, formatting, captions)
- Check citation format consistency (APA, Chicago, or journal-specific)
- Assess equation numbering and cross-referencing

**Output**: Structural issues list with section-specific recommendations

### Level 3: Deep Technical Review (30-45 minutes)

This is the core of academic peer review. Execute thorough examination across four dimensions:

#### A. Methodological Rigor

**For GMM Estimation:**
- Verify correct terminology (two-stage vs two-step vs three-stage - see `references/gmm_best_practices.md`)
- Check moment conditions specification:
  - Count total moments vs parameters (over-identification degree of freedom)
  - Verify if higher-order moments (3rd, 4th) are used when claimed
  - **Run**: `scripts/verify_moment_conditions.py` to validate setup
- Examine weight matrix sequence:
  - Identity matrix in Step 1?
  - Newey-West HAC optimal matrix in Step 2?
  - Correct lag selection formula (Newey-West 1994)?
- Validate standard error adjustments:
  - Is Newey & McFadden (1994) cited for two-stage estimation?
  - Are first-stage parameter uncertainties propagated to second-stage?
- Check identification strategy:
  - Are parameter constraints justified (economic or statistical)?
  - **Run**: `scripts/check_identification.py` to assess Jacobian rank, condition number
  - Is Monte Carlo validation provided if novel identification claimed?

**For Hawkes Jump-Diffusion Models:**
- Verify correct foundational citations:
  - Hawkes (1971, Biometrika) for basic theory
  - Daley & Vere-Jones (2003) for point process framework
  - Aït-Sahalia et al. (2015, JFE) for financial applications
- **Critical**: Flag if Hamilton (1989) is cited for Hawkes filtering (this is WRONG - Hamilton is Markov-switching, not self-exciting point processes)
- Check stationarity conditions: α > max(β₁₁, β₂₂) must hold
- Evaluate parameter identification:
  - Daily data: typically requires α₁=α₂, λ₁∞=λ₂∞ constraints (Aït-Sahalia et al. 2010, Line 861)
  - High-frequency data: may identify α_F≠α_S IF supported by Monte Carlo (see `references/hawkes_methodology.md`)
- Assess interval vs instantaneous moments:
  - For Δ > 1 hour: must use interval moments (Appendix B formulas)
  - For 5-min data: can use instantaneous if Δ·α << 1

**For High-Frequency Data:**
- Check microstructure noise handling:
  - Realized Kernel estimator (Barndorff-Nielsen et al. 2008)?
  - Refresh time sampling (Harris et al. 1995)?
  - Bid-ask bounce mitigation?
- Evaluate jump identification method:
  - Fixed threshold (-2%, -3.5%): justify against sampling frequency
  - Dynamic percentile (5%, 10%): provide economic rationale
  - Lee-Mykland test: correct critical value formula?
- Verify intraday pattern handling (U-shape volatility, if applicable)

**Numerical Implementation:**
- Check optimization algorithm choice and convergence criteria
- Verify global vs local optimization (differential evolution preferred for GMM)
- Assess computational complexity claims (do NOT trust unverified time estimates)

#### B. Literature Support & Innovation Claims

**Innovation Verification:**
- For "first study to..." claims:
  - Demand evidence of literature search (keywords used, databases searched, results)
  - Check if truly novel or incremental extension
  - **Run**: `scripts/validate_citation_format.py` to identify missing key citations
- For methodology innovations:
  - Verify if adequate Monte Carlo validation is provided (not just claimed)
  - Check if assumptions are weaker or stronger than existing methods
  - Assess if complexity is justified by performance gain

**Citation Accuracy:**
- Verify all methodological claims have proper attribution
- Check for common misattributions:
  - Hamilton (1989) ≠ Hawkes filtering ❌
  - Newey-West (1987) ≠ GMM two-step (should be Hansen 1982) ❌
  - OLS hedge ratio ≠ Johnson (1960) style, should specify if Ederington (1979) or others
- Identify missing essential citations (see `references/common_rejections.md`)

**Literature Review Quality:**
- Assess coverage of recent work (last 5 years in target journal)
- Check for selective citation bias (only supporting prior work)
- Verify international scope (not just one region unless regionally focused study)

#### C. Empirical Design & Robustness

**Sample Design:**
- **Run**: `scripts/assess_sample_split.py` to evaluate:
  - In-sample vs out-of-sample ratio (typical: 70-80% training)
  - Split point pre-determination (avoid look-ahead bias)
  - Out-of-sample period adequacy (minimum 2-3 years for financial data)
  - Crisis period inclusion (should span multiple regimes)

**Robustness Checks - Mandatory Suite:**
- **Over-identification Test:**
  - Hansen (1982) J-statistic reported?
  - Degrees of freedom = moments - parameters correct?
  - If p-value < 0.05, are misspecified moments diagnosed?
- **Sub-period Stability:**
  - At least 3 sub-periods tested (early/middle/recent)?
  - Chow test for structural breaks?
  - Parameter consistency across periods?
- **Frequency Robustness (for high-freq data):**
  - Test 3-4 sampling frequencies (e.g., 5min, 15min, 30min, 1hour)?
  - Verify parameters stable across frequencies (α should not change)?
- **Bootstrap Inference:**
  - Block bootstrap with appropriate block size (1 day for 5-min data)?
  - 95% CI comparison: bootstrap vs asymptotic?
  - At least 500 replications (1000 preferred)?

**Alternative Specifications:**
- Different parameter constraints tested (e.g., symmetric vs asymmetric)?
- Alternative jump thresholds (if applicable)?
- Competing model comparisons (e.g., OLS vs GARCH vs Hawkes)?

**Sensitivity Analysis:**
- Initial value robustness (multiple starting points)?
- Outlier treatment sensitivity (winsorization levels)?
- Truncation/threshold sensitivity?

#### D. Results Interpretation

**Statistical Significance:**
- Check if t-statistics/p-values are correctly reported
- Verify significance levels (1%, 5%, 10%) are appropriate for claims
- Assess multiple testing corrections (if applicable)

**Economic Significance:**
- Are effect sizes economically meaningful beyond statistical significance?
- Is practical impact quantified (e.g., "hedge effectiveness improves 5 percentage points")?
- Are magnitudes compared to existing benchmarks?

**Causality vs Correlation:**
- Are causal claims supported by identification strategy?
- Is language appropriately cautious if only correlation shown?

### Level 4: Writing Style & Compliance (10-15 minutes)

**Academic Tone:**
- Flag excessive emphasis ("extremely important", "groundbreaking", "revolutionary")
- Check for unsupported absolute claims ("this is the first...", "we prove that...")
- Verify objective, third-person style (minimize "we believe", "in our opinion")
- Assess balance between active and passive voice (field-dependent, but avoid all-passive)

**Format Compliance:**
- **Critical for top journals**: NO bullet points in main text (convert to prose)
- Verify Arabic numerals for scientific data (2003年, 150個, 14個參數)
  - Exception: ordinal words (第一階段, 第二章)
- Check LaTeX table formatting (booktabs package, no vertical lines)
- Assess figure resolution (vector format PDF/EPS preferred)

**Terminology Consistency:**
- Same term for same concept throughout (e.g., "hedge ratio" not "hedging ratio")
- Acronyms defined at first use
- Mathematical notation consistent across sections

**Length Appropriateness:**
- JBF/RFS: 40-50 pages main text acceptable
- JFE/JoE: 30-40 pages preferred (more technical density)
- Grant proposals: typically 15-30 pages depending on funding agency

## Scoring System (100 points)

Apply the following rubric to generate an overall score and decision recommendation:

### Innovation & Contribution (25 points)

- **Theoretical Contribution** (10 points):
  - 9-10: Novel theory with clear advancement
  - 7-8: Meaningful extension of existing theory
  - 5-6: Incremental theoretical contribution
  - 3-4: Minimal theoretical novelty
  - 0-2: No theoretical contribution

- **Methodological Innovation** (10 points):
  - 9-10: New method with rigorous validation
  - 7-8: Novel application of existing method
  - 5-6: Competent use of standard methods
  - 3-4: Flawed or outdated methodology
  - 0-2: Serious methodological errors

- **Empirical Evidence** (5 points):
  - 5: Compelling new evidence from superior data
  - 4: Good evidence from appropriate data
  - 3: Adequate evidence but data limitations
  - 2: Weak evidence or questionable data
  - 0-1: Insufficient or flawed evidence

### Methodological Rigor (30 points)

- **Estimation Procedure** (10 points):
  - 9-10: Flawless technical execution
  - 7-8: Sound with minor technical issues
  - 5-6: Acceptable but some concerns
  - 3-4: Significant technical problems
  - 0-2: Fundamentally flawed

- **Identification Strategy** (10 points):
  - 9-10: Convincingly identified with validation
  - 7-8: Well-identified but could be stronger
  - 5-6: Adequate identification
  - 3-4: Weak or questionable identification
  - 0-2: Not identified

- **Numerical Implementation** (10 points):
  - 9-10: Excellent detail, replicable
  - 7-8: Good detail, likely replicable
  - 5-6: Adequate but some missing details
  - 3-4: Important details missing
  - 0-2: Cannot be replicated

### Empirical Design (25 points)

- **Data Quality** (8 points):
  - 7-8: Excellent data, no concerns
  - 5-6: Good data with minor issues
  - 3-4: Data concerns affect results
  - 0-2: Serious data problems

- **Sample Design** (7 points):
  - 6-7: Excellent design, appropriate split
  - 4-5: Good design with minor issues
  - 2-3: Questionable design choices
  - 0-1: Flawed sample design

- **Robustness Checks** (10 points):
  - 9-10: Comprehensive robustness suite (J-test, subperiod, frequency, bootstrap)
  - 7-8: Good robustness (missing 1 component)
  - 5-6: Basic robustness (missing 2+ components)
  - 3-4: Minimal robustness
  - 0-2: No robustness checks

### Writing Quality (20 points)

- **Logical Clarity** (10 points):
  - 9-10: Crystal clear, excellent flow
  - 7-8: Clear with minor organizational issues
  - 5-6: Generally clear but some confusion
  - 3-4: Confusing in places
  - 0-2: Poorly organized, hard to follow

- **Academic Standards** (10 points):
  - 9-10: Perfect compliance (no bullets, correct numerals, proper citations)
  - 7-8: Minor formatting issues
  - 5-6: Several formatting violations
  - 3-4: Many violations
  - 0-2: Does not meet journal standards

### Overall Decision Framework

- **90-100**: Accept (rare - only exceptional work)
- **80-89**: Minor Revision (strong work, needs minor fixes)
- **70-79**: Major Revision (good work, significant improvements needed)
- **60-69**: Reject & Resubmit (fundamental issues but salvageable)
- **<60**: Reject (does not meet publication standards)

## Output Format

Structure every review report as follows:

### 1. Executive Summary (200 words max)

Provide a concise overview:
- Document type and target journal
- Overall assessment in 2-3 sentences
- Top 3 strengths
- Top 3 weaknesses
- Recommended next actions

### 2. Overall Score & Decision

```
Total Score: [X/100]
Decision: [Accept / Minor Revision / Major Revision / Reject & Resubmit / Reject]

Score Breakdown:
- Innovation & Contribution: [X/25]
- Methodological Rigor: [X/30]
- Empirical Design: [X/25]
- Writing Quality: [X/20]
```

### 3. Critical Issues (🔴 Must Fix Before Submission/Resubmission)

List all major problems that would lead to immediate rejection:
- Methodological errors
- Missing essential robustness checks
- Incorrect citations for key methods
- Unsupported innovation claims

**Example**:
```
🔴 Critical Issue #1: GMM Identification Not Proven
The paper claims to identify α_F ≠ α_S using 150 moment conditions, but provides
no Monte Carlo validation. Without proof that condition number κ(D'WD) < 1000
and rejection rate > 80%, this claim cannot be accepted.

Action Required: Run scripts/check_identification.py and report results in Appendix.
Estimated effort: 2-3 days.
```

### 4. Important Issues (⚠️ Should Fix for Strong Publication)

List issues that weaken the paper but are not fatal:
- Missing robustness checks
- Suboptimal writing style
- Literature gaps
- Formatting violations

### 5. Minor Suggestions (💡 Nice to Have)

List improvements that would enhance the paper:
- Additional analyses
- Clearer exposition
- Better figures/tables
- Extended discussion

### 6. Detailed Comments by Section

Provide section-by-section feedback:

**Introduction:**
- Clarity of research question
- Motivation strength
- Contribution positioning

**Literature Review:**
- Coverage completeness
- Critical analysis depth
- Gap identification clarity

**Methodology:**
- Technical correctness (primary focus)
- Clarity of exposition
- Sufficient detail for replication

**Results:**
- Interpretation accuracy
- Statistical vs economic significance
- Robustness demonstration

**Conclusion:**
- Summary accuracy
- Limitations acknowledgment
- Future research directions

### 7. Recommended Actions (Prioritized Checklist)

Create a prioritized action list:

```markdown
## High Priority (Address Before Resubmission)
- [ ] Run Monte Carlo to validate identification claim (Section 3.3)
- [ ] Add J-test over-identification check (Section 4.5)
- [ ] Fix Hamilton (1989) misattribution → cite Hawkes (1971) instead

## Medium Priority (Improves Acceptance Chances)
- [ ] Add bootstrap standard errors (Appendix E)
- [ ] Test frequency robustness (5min, 15min, 30min, 1hour)
- [ ] Convert all bullet points to prose (entire manuscript)

## Low Priority (Polish for Final Version)
- [ ] Improve Figure 3 resolution (use vector format)
- [ ] Expand discussion of practical implications (Section 6)
- [ ] Add comparison with international markets (if data available)
```

## Utilizing Bundled Resources

### Running Diagnostic Scripts

When reviewing methodology sections, execute the diagnostic scripts to provide objective assessments:

**Check Parameter Identification:**
```bash
# Extract parameter count and moment count from manuscript
python scripts/check_identification.py --params 14 --moments 150 --alpha-F 150 --alpha-S 100

# Script outputs:
# - Jacobian matrix analysis
# - Condition number κ(D'WD)
# - Rank verification
# - Identification strength assessment
```

**Verify Moment Conditions:**
```bash
# Provide moment specification details
python scripts/verify_moment_conditions.py --config moment_setup.yaml

# Script validates:
# - Over-identification DOF = moments - params
# - Moment type distribution (mean, variance, autocorr, cross-corr)
# - Higher-order moments usage
# - Identification adequacy
```

**Assess Sample Split:**
```bash
python scripts/assess_sample_split.py --train-start 2003 --train-end 2019 --test-start 2020 --test-end 2024

# Script checks:
# - In-sample ratio (should be 70-80%)
# - Pre-determination (split before crisis?)
# - Out-of-sample period length
# - Crisis period coverage
```

**Validate Citations:**
```bash
python scripts/validate_citation_format.py manuscript.md

# Script identifies:
# - Format inconsistencies
# - Common misattributions (Hamilton for Hawkes)
# - Missing essential citations
# - Suspicious citation patterns
```

### Consulting Reference Documentation

When uncertain about standards, consult the references:

- **Journal Requirements**: `references/journal_standards.md` - detailed requirements for JBF, JFE, JoE, RFS, JFM, FRL
- **GMM Standards**: `references/gmm_best_practices.md` - correct terminology, standard errors, weight matrices
- **Hawkes Methods**: `references/hawkes_methodology.md` - required citations, identification constraints, common errors
- **High-Freq Data**: `references/high_frequency_data.md` - microstructure noise, jump detection, intraday patterns
- **Common Rejections**: `references/common_rejections.md` - frequently seen rejection reasons and how to avoid them
- **Writing Guide**: `references/writing_style_guide.md` - academic tone, formatting rules, journal-specific styles

**Search Patterns for Large References:**
If references exceed context window, use grep patterns:
```bash
# Find specific topic in references
grep -n "Hamilton.*Hawkes" references/*.md
grep -n "identification.*daily.*frequency" references/*.md
grep -n "bullet.*point" references/*.md
```

### Using Assets

- **Review Rubric**: Open `assets/review_rubric_template.xlsx` in Excel to fill detailed checklist and auto-calculate score
- **Journal Guidelines**: Refer to `assets/jbf_author_guidelines.pdf` for JBF-specific formatting requirements
- **Revision Template**: Use `assets/revision_response_template.md` as structure when reviewing revision response letters

## Special Considerations by Document Type

### Complete Manuscripts

- Execute full Level 1-4 review
- Emphasize replicability (can another researcher reproduce results?)
- Check if online appendix materials are referenced (code, data documentation)
- Verify word count fits target journal

### Research Grant Proposals

- Adjust scoring: weight feasibility and innovation equally (unlike papers where rigor dominates)
- Be stricter on innovation claims (funders want clear novelty)
- Check if timeline and budget are realistic
- Assess team qualifications
- Verify pilot results if claimed
- Flag any overly ambitious goals as red flags

### Methodology Sections Only

- Focus exclusively on Level 3 (Deep Technical Review)
- Run all diagnostic scripts
- Provide detailed equations verification
- Check consistency with Introduction's research question
- Assess if sufficient detail for replication

### Revision Response Letters

- Verify every reviewer comment is addressed
- Check for point-by-point structure
- Assess if "we agree but..." responses have valid justification
- Look for specific manuscript changes cited (page numbers, line numbers)
- Flag any evasive or dismissive responses
- Verify tone is respectful and professional

## Integration with Existing Workflows

This skill is designed to work alongside the existing `academic-finance-reviewer` agent. Differences:

- **Agent**: Interactive, conversational review with back-and-forth clarifications
- **Skill**: Structured, comprehensive report generation in single pass

Use the skill when:
- A complete, formal review report is needed
- Systematic scoring across multiple dimensions is required
- Diagnostic scripts should be run
- Comparison against journal standards is critical

Use the agent when:
- Iterative refinement through dialogue is preferred
- Quick targeted feedback on specific sections
- Collaborative revision process

## Limitations and Disclaimers

This skill provides academic peer review simulation based on published journal standards and common practices. However:

- Final publication decisions involve editor discretion and reviewer subjectivity
- Field-specific norms may vary (this skill optimizes for financial econometrics)
- Scores are indicative, not absolute predictors of acceptance
- Novel methodologies may require additional expert consultation
- The skill cannot access paywalled journal guidelines or proprietary reviewer databases

When in doubt, consult:
- Recent publications in target journal for current standards
- Senior colleagues with editorial experience
- Journal editors for clarification on specific requirements
