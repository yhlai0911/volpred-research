# Academic Finance Review Rubric Template

**Paper Title**: _______________________________________________________

**Authors**: __________________________________________________________

**Target Journal**: ____________________________________________________

**Review Date**: _______________________________________________________

**Reviewer**: _________________________________________________________

---

## SECTION 1: INNOVATION & CONTRIBUTION (25 points)

### 1.1 Novelty of Research Question (8 points)

| Score | Criteria |
|-------|----------|
| 7-8 | Groundbreaking question, new to literature |
| 5-6 | Important question with novel angle |
| 3-4 | Incremental advance on existing question |
| 1-2 | Minor variation of known question |
| 0 | No novelty, replicates existing work |

**Score**: _____ / 8

**Comments**:


### 1.2 Methodological Innovation (8 points)

| Score | Criteria |
|-------|----------|
| 7-8 | Novel method or major methodological advance |
| 5-6 | Creative adaptation of existing method |
| 3-4 | Standard method applied competently |
| 1-2 | Standard method with minor issues |
| 0 | Inappropriate or flawed method |

**Score**: _____ / 8

**Comments**:


### 1.3 Economic Significance (9 points)

| Score | Criteria |
|-------|----------|
| 8-9 | Major practical/policy implications, large effects |
| 6-7 | Clear economic relevance, moderate effects |
| 4-5 | Some economic significance, small effects |
| 2-3 | Marginal economic relevance |
| 0-1 | No clear economic significance |

**Score**: _____ / 9

**Comments**:


**TOTAL SECTION 1**: _____ / 25

---

## SECTION 2: METHODOLOGICAL RIGOR (30 points)

### 2.1 GMM Estimation Procedure (10 points)

**Checklist**:
- [ ] Terminology correct (two-stage vs two-step) *(2 pts)*
- [ ] Moment conditions clearly specified *(2 pts)*
- [ ] Weight matrix properly constructed *(2 pts)*
- [ ] Standard errors correctly computed *(2 pts)*
- [ ] J-test reported (if overidentified) *(2 pts)*

**Score**: _____ / 10

**Issues Found**:


### 2.2 Identification Strategy (10 points)

**Checklist**:
- [ ] Order condition verified (m ≥ p) *(2 pts)*
- [ ] Rank condition discussed *(2 pts)*
- [ ] Restrictions justified *(2 pts)*
- [ ] Identification diagnostics provided *(2 pts)*
- [ ] Monte Carlo or sensitivity analysis *(2 pts)*

**Score**: _____ / 10

**Issues Found**:


### 2.3 Numerical Implementation (10 points)

**Checklist**:
- [ ] Optimization method appropriate *(2 pts)*
- [ ] Convergence criteria stated *(2 pts)*
- [ ] Initial values described *(2 pts)*
- [ ] Bounds/constraints justified *(2 pts)*
- [ ] Numerical stability addressed *(2 pts)*

**Score**: _____ / 10

**Issues Found**:


**TOTAL SECTION 2**: _____ / 30

---

## SECTION 3: EMPIRICAL DESIGN (25 points)

### 3.1 Sample Design (10 points)

**Checklist**:
- [ ] Sample period justified (adequate length) *(3 pts)*
- [ ] Sample selection not biased *(2 pts)*
- [ ] Crisis/normal periods included *(2 pts)*
- [ ] Out-of-sample validation if applicable *(3 pts)*

**Score**: _____ / 10

**Comments**:


### 3.2 Data Quality (8 points)

**Checklist**:
- [ ] Data sources clearly identified *(2 pts)*
- [ ] Cleaning procedure described *(2 pts)*
- [ ] Outliers appropriately handled *(2 pts)*
- [ ] Descriptive statistics provided *(2 pts)*

**Score**: _____ / 8

**Comments**:


### 3.3 Robustness Checks (7 points)

**Checklist**:
- [ ] Subperiod analysis *(2 pts)*
- [ ] Alternative specifications *(2 pts)*
- [ ] Sensitivity to key assumptions *(2 pts)*
- [ ] Bootstrap or alternative inference *(1 pt)*

**Score**: _____ / 7

**Missing Checks**:


**TOTAL SECTION 3**: _____ / 25

---

## SECTION 4: WRITING QUALITY (20 points)

### 4.1 Structure & Organization (6 points)

**Checklist**:
- [ ] Clear introduction with motivation *(2 pts)*
- [ ] Logical section flow *(2 pts)*
- [ ] Comprehensive conclusion *(2 pts)*

**Score**: _____ / 6

**Issues**:


### 4.2 Academic Style Compliance (8 points)

**Checklist**:
- [ ] No bullet points in main text *(2 pts)*
- [ ] Arabic numerals for scientific data *(2 pts)*
- [ ] Appropriate tense and voice *(2 pts)*
- [ ] Grammar and clarity *(2 pts)*

**Score**: _____ / 8

**Style Violations**:


### 4.3 Presentation Quality (6 points)

**Checklist**:
- [ ] Tables properly formatted (LaTeX style) *(2 pts)*
- [ ] Figures high quality, clear labels *(2 pts)*
- [ ] Citations accurate and complete *(2 pts)*

**Score**: _____ / 6

**Issues**:


**TOTAL SECTION 4**: _____ / 20

---

## CRITICAL ISSUES DETECTED

### 🔴 CRITICAL ERRORS (Must Fix)

**Citation Errors**:
- [ ] Hamilton (1989) misattributed to Hawkes processes
- [ ] Missing required citations (Hawkes 1971, Hansen 1982, etc.)
- [ ] Other: _____________________________________________

**Methodological Errors**:
- [ ] Parameters not identified
- [ ] Standard errors incorrect (using optimizer SE, not GMM)
- [ ] Terminology confusion (two-stage vs two-step)
- [ ] Other: _____________________________________________

**Empirical Issues**:
- [ ] Sample too short / biased selection
- [ ] Data quality problems not addressed
- [ ] No robustness checks
- [ ] Other: _____________________________________________

### ⚠️ IMPORTANT WARNINGS

- [ ] Economic significance unclear or marginal
- [ ] Contribution not clearly positioned vs literature
- [ ] Identification weak but possible
- [ ] Writing quality needs improvement
- [ ] Reproducibility concerns
- [ ] Other: _____________________________________________

---

## OVERALL ASSESSMENT

### Total Score

| Section | Score | Maximum |
|---------|-------|---------|
| 1. Innovation & Contribution | _____ | 25 |
| 2. Methodological Rigor | _____ | 30 |
| 3. Empirical Design | _____ | 25 |
| 4. Writing Quality | _____ | 20 |
| **TOTAL** | **_____** | **100** |

### Decision Framework

| Score Range | Decision | Typical Outcome |
|-------------|----------|-----------------|
| 90-100 | **ACCEPT** | Publish with minor edits |
| 80-89 | **MINOR REVISION** | Accept pending small changes |
| 70-79 | **MAJOR REVISION** | Significant work needed |
| 60-69 | **REVISE & RESUBMIT** | Borderline, major overhaul |
| <60 | **REJECT** | Not suitable for this journal |

### **Recommended Decision**: _______________________________

### Journal-Specific Thresholds

**For reference** (approximate, based on review experience):

- **RFS/JFE**: Typically need 90+ for acceptance
- **JBF/JoE**: Typically need 85+ for R&R
- **JFM**: Typically need 80+ for R&R
- **FRL**: Typically need 75+ for acceptance

---

## DETAILED COMMENTS

### Strengths

1.

2.

3.

### Critical Issues (Must Address)

1.

2.

3.

### Important Suggestions (Strongly Recommended)

1.

2.

3.

### Minor Comments (Optional)

1.

2.

3.

---

## PRIORITIZED ACTION ITEMS

### Priority 1: Critical (Must Fix Before Resubmission)

- [ ]
- [ ]
- [ ]

### Priority 2: Important (Strongly Recommended)

- [ ]
- [ ]
- [ ]

### Priority 3: Enhancements (If Time Permits)

- [ ]
- [ ]
- [ ]

---

## ADDITIONAL NOTES

### Literature Gaps

Papers that should be cited:


### Methodological Suggestions

Alternative approaches to consider:


### Extension Ideas

Potential future research directions:


---

## FINAL RECOMMENDATION

### Summary (200 words)

[Provide concise summary of review: main strengths, critical weaknesses,
overall assessment, and recommendation]




### Estimated Revision Time

**If Minor Revision**: _____ weeks

**If Major Revision**: _____ months

**If R&R**: _____ months (significant work required)

---

**Review Completed**: _____________________ (Date)

**Reviewer Signature**: _____________________

---

## APPENDIX: SCORING CALIBRATION GUIDE

### How to Score

**90-100 (Excellent)**:
- Top 5-10% of papers
- Publishable in top-tier journals with minor changes
- Novel contribution, rigorous methods, excellent writing

**80-89 (Good)**:
- Top 20-30% of papers
- Solid contribution with good execution
- Suitable for good journals (JBF, JFM) with revisions

**70-79 (Acceptable)**:
- Median paper
- Incremental contribution, competent methods
- Needs major revision to meet publication standards

**60-69 (Marginal)**:
- Below median
- Some merit but significant issues
- R&R possible if authors address all concerns

**<60 (Weak)**:
- Below publication threshold
- Fundamental flaws or minimal contribution
- Rejection recommended

### Calibration Examples

**Example 1: Score 85**
- Novel application (7/8)
- Standard GMM but well-executed (5/8)
- Clear economic relevance (7/9)
- All identification checks passed (10/10)
- Minor standard error issue (-2 from Section 2)
- Good robustness checks (6/7)
- Writing needs polish (14/20)
- **Decision**: Minor Revision for JBF

**Example 2: Score 65**
- Incremental question (4/8)
- Method OK but identification weak (4/10)
- Marginal economic significance (4/9)
- Sample too short (4/10)
- No robustness checks (0/7)
- Writing acceptable (16/20)
- **Decision**: Major Revision or Reject, recommend lower-tier journal

---

*This rubric is based on standards for Journal of Banking & Finance and similar top finance journals. Adjust thresholds for other journals as appropriate.*
