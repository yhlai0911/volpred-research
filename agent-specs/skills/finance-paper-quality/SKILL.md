---
name: finance-paper-quality
description: >
  This skill should be used when writing or revising academic finance papers targeting
  top-tier journals (JBF, JFE, RFS, JoE). It enforces quality standards: claim-evidence
  matching, mechanical vs empirical distinction, threshold justification, contribution
  count, academic tone, Harvey (2016) rigor, and submission checklist.
  Trigger phrases: 'write paper section', '寫論文', 'revise paper', '修改論文',
  'check paper quality', 'submission checklist', or '/finance-paper-quality'.
  Trigger situations: drafting new LaTeX sections, revising after peer review, adding
  empirical results, or verifying that claims match evidence scope.
  This skill should NOT be used for: LaTeX formatting/structure review (use
  latex-academic-reviewer), citation verification (use citation-verifier), or feed publishing.
---

# Finance Paper Quality Standards

Enforce academic quality standards when writing or revising finance papers targeting top-tier journals (JBF, JFE, RFS, JoE, FRL).

## Scope Boundary

Use this skill for：

- claim-evidence matching
- contribution count and framing
- mechanical vs empirical distinction
- threshold justification
- submission-quality writing standards

Do **not** use this skill for：

- citation-only verification → `citation-verifier`
- LaTeX 結構與符號審查 → `latex-academic-reviewer`
- paper 平台同步 → `paper-update`

## When to Use

- Writing new paper sections
- Revising paper after peer review
- Checking if a claim is appropriately stated
- Adding new empirical results to the paper

## Related Bundle

Read `academic-finance-reviewer/` as a reference bundle when you need journal standards,
rejection patterns, writing style guidance, or reviewer response templates.

## Core Principles (from Codex Review Lessons)

### 1. Claims Must Match Evidence Scope

**Rule**: Never claim "cross-asset" results from < 10 assets. Never claim "universal" from a single market.

| Evidence Base | Permissible Claim |
|---|---|
| 1-5 assets | "preliminary evidence suggests..." |
| 6-15 assets | "cross-sectional evidence indicates..." |
| 16-30 assets | "broad cross-asset evidence supports..." |
| 30+ assets + international | "robust cross-asset finding" |

**Anti-pattern**: "Our cross-asset analysis of seven assets demonstrates..." (7 is NOT cross-asset)

### 2. Distinguish Mechanical vs Empirical Results

**Rule**: If a result follows mathematically from the model specification, it is mechanical (not a contribution). The contribution is the EMPIRICAL validation + economic interpretation.

Example:
- Mechanical: "gamma > 0 implies VT de-levers after negative returns" (this follows from the GJR equation)
- Empirical: "the magnitude of the cross-sectional correlation (rho=0.874, N=17) exceeds what simple mechanics would predict" (this is testable)
- Contribution: "we show that GARCH-based gamma captures structural information beyond realized volatility asymmetry (rho=0.857 vs 0.643)" (anti-tautology test)

### 3. Threshold Justification

**Rule**: Every calibrated threshold must have either:
(a) Theoretical derivation, or
(b) Sensitivity analysis showing robustness, or
(c) Out-of-sample validation

Format: "We set [threshold] = [value] because [reason]. The results are robust to values in [[lower], [upper]]."

### 4. Contributions Count

**Rule**: A JBF paper should have 2-3 core contributions, not 5+.

- 2 contributions: Focused and strong (ideal for FRL, short papers)
- 3 contributions: Standard for JBF/JFE
- 4+ contributions: Too many → referee suspects none is deep enough

Each contribution must pass the "so what" test: Would a busy portfolio manager or risk officer change behavior based on this finding?

### 5. Academic vs Practitioner Language

**DO NOT write**:
- "Monthly rebalancing is sufficient"
- "Investors should use..."
- "The recommended strategy is..."
- "A practical guide for..."

**DO write**:
- "The strategy's performance is robust to rebalancing frequency reduction"
- "The economic magnitude suggests relevance for portfolio construction"
- "Our findings have implications for volatility-managed portfolio design"

### 6. Statistical Rigor

**Harvey (2016) Framework (always apply)**:
- Report both point estimate AND confidence interval
- For Sharpe ratios: SE ≈ 1/√N_years, need ~1500 years for t>3
- For multiple comparisons: mention Bonferroni/FDR correction
- Distinguish: statistically significant vs economically meaningful

**Required tests for any claimed difference**:
- Diebold-Mariano for QLIKE comparisons
- Bootstrap for MDD comparisons
- Permutation test for cross-sectional correlations with N<20
- Leave-one-out for small-sample robustness

### 7. Paper Structure (JBF Standard)

```
1. Introduction (2-3 pages)
   - Motivation (why should we care?)
   - Gap in literature (what's missing?)
   - Contributions (2-3, with preview of key numbers)
   - Roadmap (1 paragraph)

2. Literature Review (2-3 pages)
   - Organized by theme, not chronologically
   - Each paragraph ends with "however, [gap]"

3. Data and Methodology (3-4 pages)
   - Data description (sources, periods, summary statistics)
   - Model specification (equations, estimation method)
   - Evaluation metrics (QLIKE, VaR, DM test)

4. Empirical Results (8-12 pages)
   - Organized by contribution
   - Each subsection: hypothesis → test → result → interpretation
   - Tables before discussion

5. Discussion (3-5 pages)
   - Economic interpretation
   - Connection to theory
   - Robustness and caveats

6. Conclusion (1-2 pages)
   - Summary of findings
   - Limitations
   - Future research
```

### 8. Table and Figure Quality

- Tables: booktabs style, no vertical lines
- Figures: vector PDF, clear axis labels, referenced in text
- Every table/figure MUST be discussed in the text
- Caption should be self-contained (reader understands without text)

### 9. Citation Standards

- Method → cite original paper (GARCH → Bollerslev 1986, GJR → Glosten et al. 1993)
- Claim → cite supporting evidence
- Number → cite data source
- "It is well known that..." → cite or remove

### 10. Author Presentation

- Human authors only (no AI systems as co-authors)
- Acknowledge AI assistance in footnote if used
- Affiliation must be real academic institution
- Corresponding author email from institutional domain

## Paper Location

Papers are stored in `paper/[paper-name]/` subdirectories:
- `paper/leverage-direction/` — First paper (Leverage Direction Matters)
- Future papers: `paper/taiwan-vt/`, `paper/12-vix-strategy/`, etc.

Compile: `cd paper/[name] && /Library/TeX/texbin/xelatex -interaction=nonstopmode main.tex`

## Checklist Before Submission

- [ ] Claims match evidence scope (Section 1 rule)
- [ ] Mechanical vs empirical clearly distinguished (Section 2)
- [ ] All thresholds justified (Section 3)
- [ ] 2-3 core contributions only (Section 4)
- [ ] No practitioner language (Section 5)
- [ ] Harvey framework applied to key claims (Section 6)
- [ ] All tables/figures discussed in text (Section 8)
- [ ] All methods properly cited (Section 9)
- [ ] Human authors only (Section 10)
