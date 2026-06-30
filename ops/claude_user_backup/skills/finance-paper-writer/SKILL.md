---
name: finance-paper-writer
description: Guide for writing academic finance papers for top-tier journals like Journal of Banking and Finance. Use this skill when writing or revising empirical finance papers, particularly those involving econometric methods (GMM, maximum likelihood), financial contagion, jump-diffusion models, or systemic risk. Helps with paper structure, methodology description, results reporting, and journal-specific formatting requirements.
---

# Finance Paper Writer

## Overview

This skill provides comprehensive guidance for writing high-quality academic finance papers targeting top-tier journals such as the Journal of Banking and Finance (JBF). The skill covers the entire writing process from paper structure to journal-specific formatting, with special emphasis on empirical finance and econometric methodology.

## When to Use This Skill

Use this skill when:
- Writing a new finance paper from scratch
- Revising existing sections to meet journal standards
- Describing complex econometric methods (GMM, ML estimation, Hawkes processes, etc.)
- Reporting empirical results with proper statistical rigor
- Formatting tables, figures, and equations for journal submission
- Ensuring compliance with JBF or similar journal requirements

## Workflow Decision Tree

To determine how to use this skill, follow this decision tree:

```
┌─ Writing a new paper?
│  ├─ YES → Start with "Paper Structure Template" (assets/)
│  │        Then follow "Section-by-Section Writing Guide" below
│  └─ NO → Continue to next question
│
┌─ Revising specific section?
│  ├─ Introduction/Literature → See "Writing Introduction & Literature Review"
│  ├─ Methodology → See "Writing Methodology Section"
│  ├─ Results → See "Writing Results Section"
│  ├─ Conclusion → See "Writing Conclusion"
│  └─ Abstract/Highlights → See "Writing Abstract and Highlights"
│
┌─ Need journal-specific formatting?
│  └─ Read references/jbf_requirements.md
│
┌─ Need help with econometric terminology?
│  └─ Read references/methodology_writing.md
│
└─ Need table/figure formatting examples?
   └─ Read assets/table_figure_templates.md
```

## Section-by-Section Writing Guide

### 1. Writing Abstract and Highlights

**Abstract Requirements (JBF)**:
- Maximum 250 words
- Concise and factual
- State: purpose, principal results, major conclusions
- No references or citations
- Avoid abbreviations unless defined

**Structure**:
1. **Context** (1-2 sentences): What problem are you addressing?
2. **Method** (1-2 sentences): What approach do you use?
3. **Results** (2-3 sentences): What are your main findings?
4. **Contribution** (1-2 sentences): Why does it matter?

**Highlights Requirements**:
- 3-5 bullet points
- Maximum 85 characters each (including spaces)
- Captures key findings or contributions

**Example for a Hawkes model paper**:
```
Highlights:
• GMM estimation of bivariate Hawkes jump-diffusion for financial contagion
• Jump spillovers from US to UK markets exhibit significant asymmetry
• Contagion effects amplify during crisis periods by factor of three
• Self-excitation intensity predicts future volatility clustering
```

### 2. Writing Introduction & Literature Review

**Introduction Structure** (typically 4-6 pages):

**Paragraph 1-2: Motivation**
- Start with the economic phenomenon or puzzle
- Use concrete examples (e.g., 2008 financial crisis, COVID-19 market crash)
- Establish importance with market data or policy relevance

**Paragraph 3-4: Research Question**
- Clearly state what you investigate
- Explain why existing answers are inadequate
- Preview your approach

**Paragraph 5-6: Methodology Preview**
- Briefly describe your method (e.g., "We employ GMM estimation...")
- Highlight methodological contributions or innovations
- Mention data sources and sample period

**Paragraph 7-8: Main Findings**
- Summarize 2-3 key results
- Quantify effects when possible (e.g., "β₂₁ = 13.1, significant at 5% level")
- Connect findings to economic interpretation

**Paragraph 9-10: Contributions**
- List 3-4 distinct contributions
- Use numbered points for clarity
- Relate to existing literature

**Final Paragraph: Roadmap**
- "The remainder of this paper is organized as follows..."
- One sentence per subsequent section

**Literature Review Integration**:
- Weave literature into Introduction rather than separate section (JBF preference)
- Group by themes, not chronologically
- Focus on recent papers (last 10 years) in top journals
- Always include: what they do, what they find, how you differ

**Citation Format** (JBF):
- In-text: (Author, Year) or (Author1 and Author2, Year) or (Author et al., Year)
- Multiple: (Author1, Year1; Author2, Year2)

### 3. Writing Methodology Section

**Section Structure** (typically 6-10 pages):

**3.1 Model Specification**
- Start with economic intuition before equations
- Build model gradually (asset dynamics → jump intensity → parameters)
- Clearly state all assumptions

**Example opening**:
```
To capture the clustering and contagion of extreme negative returns,
we model asset prices using a bivariate jump-diffusion process where
jump intensities are mutually exciting following the Hawkes framework
(Hawkes, 1971). This specification allows jumps in one market to
trigger subsequent jumps in another market, thereby capturing financial
contagion through a self-exciting mechanism.
```

**3.2 Econometric Specification**
- State the full model with equation numbers
- Define every symbol in separate line after equation
- Use consistent notation (match standard literature)

**3.3 Estimation Strategy**
- Explain identification (what variation identifies each parameter)
- Describe estimation procedure step-by-step
- Justify choices (e.g., "We use GMM rather than ML because...")

**For GMM papers**:
- State moment conditions explicitly
- Explain economic intuition behind each moment
- Describe weighting matrix (identity vs. optimal)
- Mention standard error calculation method

**Read `references/methodology_writing.md` for detailed examples of:**
- How to describe Hawkes processes
- How to explain GMM estimation
- Standard terminology for identification, stationarity, inference

**3.4 Data and Sample Selection**
- Describe data sources with full citations
- Justify sample period selection
- Report summary statistics (mean, std, skewness, kurtosis)
- Address potential data issues (missing values, stale prices, etc.)

### 4. Writing Results Section

**Section Structure** (typically 8-12 pages):

**4.1 Baseline Results**
- Present main estimation results in Table 1
- Discuss each parameter systematically
- Report point estimates, standard errors, significance
- Provide economic interpretation

**Example paragraph**:
```
Table 1 reports the GMM estimation results for the bivariate Hawkes
model. The mean reversion parameter α is estimated at 20.3 (s.e. 9.3),
implying a half-life of 0.034 days or approximately 16 minutes. This
suggests that jump intensity shocks dissipate rapidly, consistent with
intraday patterns documented in the literature.
```

**4.2 Hypothesis Testing**
- State null hypothesis explicitly: H₀: β₂₁ = 0
- Report test statistics: t = β̂₂₁ / SE(β̂₂₁) = 2.15
- State conclusion: "We reject H₀ at the 5% significance level"
- Provide economic interpretation

**4.3 Economic Magnitudes**
- Translate parameter estimates to economically meaningful quantities
- Use implied values, elasticities, or counterfactuals
- Compare to existing literature

**Example**:
```
The contagion parameter β₂₁ = 13.1 implies that each negative jump in
the US market increases the instantaneous jump intensity in the UK
market by 13.1 units. Given the baseline intensity λ∞ = 0.4, this
represents a 33-fold amplification effect, suggesting that cross-border
spillovers are economically substantial.
```

**4.4 Robustness Checks**
- Alternative specifications (e.g., different lag lengths)
- Alternative samples (subperiods, crisis vs. normal times)
- Alternative methods (ML vs. GMM, different moment conditions)
- Present in tables with clear column headers

**4.5 Diagnostic Tests**
- Stationarity conditions: Verify α > max(β₁₁, β₂₂)
- Model fit: Compare theoretical vs. sample moments (show in figure)
- Overidentification tests: Report J-statistic if applicable
- Residual analysis: Check for remaining patterns

**Read `references/results_reporting.md` for:**
- Standard phrases for reporting estimates
- How to discuss statistical vs. economic significance
- Table formatting guidelines

### 5. Writing Conclusion

**Conclusion Structure** (typically 2-3 pages):

**Paragraph 1: Summary**
- Restate research question in fresh words
- Summarize methodology in one sentence
- List key findings (2-3 bullet points acceptable)

**Paragraph 2-3: Economic Implications**
- Connect findings to broader economic questions
- Discuss policy implications if applicable
- Relate to current market conditions or recent events

**Paragraph 4: Limitations and Future Research**
- Acknowledge model limitations honestly
- Suggest specific extensions (not vague "future research should...")
- Connect limitations to feasible next steps

**Avoid**:
- Introducing new results or citations
- Repeating abstract verbatim
- Overstating contributions
- Generic statements ("more research is needed")

## Tables and Figures

### Table Guidelines

**Table Structure**:
- Title above table: "Table 1: Baseline GMM Estimation Results"
- Column headers: Parameter, Estimate, Std. Error, t-stat
- Footnotes below table: Sample period, number of observations, notes on significance levels

**Formatting**:
- Right-align numbers, left-align text
- Use consistent decimal places (typically 3 for parameters, 2 for standard errors)
- Mark significance: * p<0.10, ** p<0.05, *** p<0.01
- Include panel headers for multi-panel tables

**Example structure** (see `assets/table_figure_templates.md` for full examples):
```
Table 1: GMM Estimation Results for Bivariate Hawkes Model

Panel A: Diffusion Parameters
Parameter    Estimate    Std. Error
σ₁           0.014      0.001
σ₂           0.016      0.001
ρ            0.390      0.045

Panel B: Jump Parameters
α            20.300***  9.300
β₁₁          17.100**   6.700
β₂₁          13.100**   6.100
β₂₂           7.100     6.500
λ_∞           0.400**   0.200

Notes: Sample period 1990-2008 (N=4,758 daily observations).
Standard errors computed using Newey-West HAC estimator.
*** p<0.01, ** p<0.05, * p<0.10.
```

### Figure Guidelines

**Figure Captions**:
- Number consecutively: Figure 1, Figure 2, ...
- Descriptive title below figure
- Explain all elements (axes, lines, shading)
- Note data sources and sample period

**Types of Figures**:
1. **Time series plots**: Show asset returns, jump intensity
2. **Diagnostic plots**: Sample vs. theoretical moments
3. **Impulse responses**: Effect of jump on future intensity
4. **Heatmaps**: Parameter stability over time

**Example caption**:
```
Figure 1: Sample and Theoretical Autocorrelation Functions

This figure compares the sample autocorrelation of daily returns
(solid lines) with theoretical autocorrelations implied by the
estimated Hawkes model (dashed lines) for lags 1-10. Panel A shows
Asset 1 (US), Panel B shows Asset 2 (UK). Sample period: 1990-2008.
```

## Journal-Specific Requirements (JBF)

**Key Requirements**:
- **Page limit**: ~40 pages (including tables, figures, references)
- **Abstract**: 250 words maximum
- **Highlights**: 3-5 bullet points, 85 characters each
- **Double-blind review**: Remove author-identifying information
- **File format**: .docx or .tex (editable source files)
- **Citation style**: Author-year format (see references/jbf_requirements.md)
- **Submission fee**: USD $300 for new manuscripts

**Formatting**:
- Single-column for Word, double-column allowed for LaTeX
- 12-point font, double-spaced
- Line numbers for review
- Separate title page (removed for blind review)

**For full details**, read `references/jbf_requirements.md`.

## Common Writing Pitfalls to Avoid

1. **Vague motivation**: Don't say "financial contagion is important." Say "The 2008 crisis saw US-originated shocks spread to 47 countries within 48 hours (Ref), costing $X trillion."

2. **Equation dumping**: Don't present 10 equations then discuss. Introduce each equation with intuition, present it, then interpret.

3. **Results without interpretation**: Don't just say β=0.5, p<0.05. Say what this means economically.

4. **Ignoring magnitudes**: Don't focus only on statistical significance. Discuss economic magnitude (elasticity, percentage change, dollar impact).

5. **Inconsistent notation**: Choose symbols once and stick with them. Make a notation table if many symbols.

6. **Unclear identification**: Explain what variation in the data identifies each parameter.

7. **Missing robustness**: Always check sensitivity to key assumptions (sample period, specification, method).

## Terminology and Phrases

For domain-specific terminology and standard academic phrases, consult:
- `references/methodology_writing.md` - How to describe econometric methods
- `references/results_reporting.md` - Standard phrases for reporting results
- `references/finance_terminology.md` - Finance-specific terms and conventions

## Resources

### references/

**jbf_requirements.md**
Complete Journal of Banking and Finance submission guidelines including abstract requirements, formatting rules, citation style, and review process details.

**methodology_writing.md**
Examples of how to describe common econometric methods in finance papers: GMM estimation, maximum likelihood, Hawkes processes, GARCH models, panel data methods. Includes standard terminology and phrasing.

**results_reporting.md**
Guidelines and examples for reporting empirical results: parameter estimates, hypothesis tests, economic magnitudes, robustness checks. Shows how to write clear, precise descriptions of statistical findings.

**finance_terminology.md**
Glossary of finance and econometrics terms with proper usage: contagion, systemic risk, jump-diffusion, self-exciting processes, market microstructure, etc. Includes American vs. British English conventions.

### assets/

**paper_template.md**
Complete paper structure template with section headings, subsection organization, and suggested page lengths. Provides scaffolding for a full empirical finance paper.

**section_examples.md**
Real examples of well-written sections from published JBF papers. Shows introduction paragraphs, methodology descriptions, and results discussions that follow best practices.

**table_figure_templates.md**
Formatted examples of tables and figures meeting JBF standards. Includes estimation results tables, summary statistics, diagnostic plots, and proper captions.

## Usage Examples

**Example 1: Writing methodology for GMM estimation**
```
User: "Help me write the methodology section describing GMM estimation
       of the Hawkes model."

Assistant reads references/methodology_writing.md for GMM terminology,
then drafts:

"We estimate the model parameters θ = (α, β₁₁, β₂₁, β₂₂, λ_∞, γ₁, γ₂)
using the Generalized Method of Moments (GMM). The GMM estimator exploits
the closed-form expressions for the theoretical moments of the process,
derived from the infinitesimal generator (Aït-Sahalia et al., 2010).
We construct 15 moment conditions consisting of..."
```

**Example 2: Formatting a results table**
```
User: "Format my estimation results as Table 1 for JBF submission."

Assistant reads assets/table_figure_templates.md, then creates properly
formatted table with title, column headers, significance stars, and
footnotes following JBF conventions.
```

**Example 3: Writing abstract and highlights**
```
User: "Draft an abstract for my paper on financial contagion."

Assistant follows the 4-part structure (Context-Method-Results-Contribution),
ensures ≤250 words, and creates 4 highlights of ≤85 characters each.
```

## Checklist Before Submission

Before submitting to JBF, verify:

- [ ] Abstract ≤ 250 words
- [ ] 3-5 highlights, each ≤ 85 characters
- [ ] Paper length ≤ 40 pages
- [ ] All equations numbered and symbols defined
- [ ] All tables have titles and notes
- [ ] All figures have descriptive captions
- [ ] References formatted as (Author, Year)
- [ ] Double-blind review ready (no author names)
- [ ] All acronyms defined at first use
- [ ] Consistent notation throughout
- [ ] Robustness checks included
- [ ] Economic interpretation provided for all results
- [ ] Limitations acknowledged in conclusion
- [ ] Source files in .docx or .tex format
