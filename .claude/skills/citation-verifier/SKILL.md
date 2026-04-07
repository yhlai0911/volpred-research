---
name: citation-verifier
description: Conduct rigorous verification of academic citations in financial econometrics research (papers, grant proposals, methodology sections). This skill verifies citation accuracy including APA format compliance, DOI correctness, author names, publication details, and whether quoted content accurately reflects original sources. Uses web search to verify all information against real sources. This skill should be used proactively after completing manuscript draft sections, or manually when reviewing citations in academic finance writing (futures hedging, jump-diffusion models, GMM estimation, financial contagion, systemic risk).
---

# Citation Verifier

## Overview

This skill provides systematic verification of academic citations in financial econometrics manuscripts. It ensures all references are accurate, properly formatted (APA 7th edition with DOI), and that cited claims faithfully represent the original source material.

**Target Domains**: Financial econometrics, futures/spot hedging, jump-diffusion models, Hawkes processes, GMM estimation, high-frequency finance, financial contagion, systemic risk.

**Languages**: Matches the manuscript language (English or Chinese). Verification reports are provided in the same language as the reviewed text.

## When to Use This Skill

This skill should be triggered:
1. **Automatically**: After saving a new draft version of a manuscript section
2. **Manually**: When explicitly requested to verify citations
3. **Proactively**: When reviewing literature review sections, methodology citations, or any text with academic references

## Verification Workflow

### Step 1: Extract All Citations

Scan the manuscript text to identify all citations. Common patterns include:
- Parenthetical: `(Author, Year)`, `(Author et al., Year)`
- Narrative: `Author (Year)`, `Author et al. (Year)`
- Multiple authors: `(Author1 & Author2, Year)`, `(Author1, Author2, & Author3, Year)`
- Multiple citations: `(Author1, Year1; Author2, Year2)`
- Page-specific: `(Author, Year, p. XX)` or `(Author, Year, pp. XX-YY)`

Create a numbered list of all unique citations found.

### Step 2: Verify Each Citation

For each citation, verify the following using web search:

#### 2.1 Bibliographic Accuracy
- [ ] **Author names**: Correct spelling, proper order, all authors included
- [ ] **Publication year**: Matches the actual publication date
- [ ] **Title**: Exact title of the paper/book
- [ ] **Journal/Publisher**: Correct journal name, volume, issue, pages
- [ ] **DOI**: Valid and resolves to the correct paper (format: `https://doi.org/10.xxxx/xxxxx`)

#### 2.2 APA 7th Edition Format Compliance
Check reference list entry follows APA 7th format:

**Journal Article**:
```
Author, A. A., Author, B. B., & Author, C. C. (Year). Title of article.
    Journal Name, Volume(Issue), Page–Page. https://doi.org/xxxxx
```

**Book**:
```
Author, A. A. (Year). Title of work: Capital letter also for subtitle.
    Publisher. https://doi.org/xxxxx
```

**Book Chapter**:
```
Author, A. A. (Year). Title of chapter. In E. E. Editor (Ed.), Title of book
    (pp. xx–xx). Publisher. https://doi.org/xxxxx
```

#### 2.3 Content Accuracy (Critical)

This is the most important verification step. Check whether the manuscript's claims about the cited work are accurate:

| Claim Type | Verification Method |
|------------|---------------------|
| "Author found X" | Search for original abstract/conclusions |
| "According to Author, X" | Verify this is actually the author's position |
| "Author's model shows X" | Check model specifications match |
| "Author (Year) introduced X" | Verify priority/originality claim |
| Methodology attribution | Confirm method originated from cited source |

**Red Flags to Check**:
- Misattributed findings (Author A's result attributed to Author B)
- Overgeneralized claims (paper says "may" but cited as definitive)
- Reversed conclusions (citing opposite of what paper actually found)
- Outdated information (citing superseded findings)
- Cherry-picked results (ignoring caveats or limitations)

### Step 3: Generate Verification Report

Produce a structured report in the manuscript's language.

#### Report Format (English)

```markdown
# Citation Verification Report

**Manuscript**: [Section/Chapter name]
**Date**: [Verification date]
**Total Citations**: [N]
**Verified**: [N] | **Issues Found**: [N]

---

## Summary

| Status | Count | Percentage |
|--------|-------|------------|
| ✓ Verified | X | XX% |
| ⚠ Minor Issues | X | XX% |
| ✗ Errors Found | X | XX% |

---

## Detailed Findings

### ✓ Verified Citations

1. **Aït-Sahalia et al. (2015)**
   - Source: Journal of Financial Economics, 115(1), 1-27
   - DOI: https://doi.org/10.1016/j.jfineco.2014.08.005
   - Content claim: ✓ Accurately represents Hawkes process application
   - APA format: ✓ Correct

### ⚠ Minor Issues

2. **Bollerslev (1986)**
   - Issue: Missing DOI in reference list
   - Correction: Add `https://doi.org/10.1016/0304-4076(86)90063-1`
   - Content claim: ✓ Accurate

### ✗ Errors Found

3. **[Author] ([Year])**
   - Issue type: [Content mismatch / Wrong author / Wrong year / Fabricated]
   - Claimed in manuscript: "[quoted claim]"
   - Actual source states: "[what source actually says]"
   - Recommendation: [specific correction]
   - Verified source: [URL or search query used]

---

## Correction Checklist

- [ ] Fix citation #3: [specific instruction]
- [ ] Add DOI to citation #2
- [ ] [Other corrections]

---

## References Verified

[Complete APA-formatted reference list with corrections applied]
```

#### Report Format (Chinese/中文)

```markdown
# 引用驗證報告

**稿件**: [章節名稱]
**日期**: [驗證日期]
**引用總數**: [N]
**已驗證**: [N] | **發現問題**: [N]

---

## 摘要

| 狀態 | 數量 | 百分比 |
|------|------|--------|
| ✓ 已驗證 | X | XX% |
| ⚠ 輕微問題 | X | XX% |
| ✗ 發現錯誤 | X | XX% |

---

## 詳細結果

### ✓ 已驗證引用

1. **Aït-Sahalia et al. (2015)**
   - 來源: Journal of Financial Economics, 115(1), 1-27
   - DOI: https://doi.org/10.1016/j.jfineco.2014.08.005
   - 內容聲明: ✓ 準確呈現 Hawkes 過程應用
   - APA 格式: ✓ 正確

### ⚠ 輕微問題

2. **Bollerslev (1986)**
   - 問題: 參考文獻缺少 DOI
   - 修正: 添加 `https://doi.org/10.1016/0304-4076(86)90063-1`
   - 內容聲明: ✓ 準確

### ✗ 發現錯誤

3. **[作者] ([年份])**
   - 問題類型: [內容不符 / 作者錯誤 / 年份錯誤 / 虛構引用]
   - 稿件中聲稱: 「[引用的內容]」
   - 原文實際表述: 「[原文實際內容]」
   - 建議修正: [具體修正建議]
   - 驗證來源: [使用的 URL 或搜索查詢]

---

## 修正清單

- [ ] 修正引用 #3: [具體說明]
- [ ] 為引用 #2 添加 DOI
- [ ] [其他修正]

---

## 已驗證參考文獻

[修正後的完整 APA 格式參考文獻列表]
```

## Verification Search Strategies

### Finding Original Papers

1. **Google Scholar**: Search `"exact paper title" author:lastname`
2. **DOI lookup**: Use `https://doi.org/` prefix to resolve DOIs
3. **Publisher sites**: SSRN, NBER, ScienceDirect, Wiley, Taylor & Francis
4. **Semantic Scholar**: For citation context and related papers

### Verifying Content Claims

1. Search for paper abstract + specific terms mentioned in manuscript
2. Look for author interviews, presentations, or summaries
3. Check citing papers that summarize the original findings
4. For methodology claims, search for the specific equation/method name

### Common Finance/Econometrics Sources

| Source Type | Where to Search |
|-------------|-----------------|
| Working papers | SSRN, NBER, CEPR, Fed Reserve |
| Journal articles | JSTOR, ScienceDirect, Wiley |
| Econometrics methods | Journal of Econometrics, Econometrica |
| Finance empirics | JFE, JoF, RFS, JBF |
| High-frequency | Journal of Financial Markets |

## Domain-Specific Verification Notes

### Hawkes Process / Jump-Diffusion Models

Key papers to cross-reference:
- Aït-Sahalia, Y., Cacho-Diaz, J., & Laeven, R. J. (2015). Modeling financial contagion using mutually exciting jump processes. *Journal of Financial Economics*, 115(1), 1-27.
- Hawkes, A. G. (1971). Spectra of some self-exciting and mutually exciting point processes. *Biometrika*, 58(1), 83-90.

Verify: Model specifications, parameter interpretations, stationarity conditions.

### GMM Estimation

Key papers:
- Hansen, L. P. (1982). Large sample properties of generalized method of moments estimators. *Econometrica*, 50(4), 1029-1054.
- Newey, W. K., & West, K. D. (1987). A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix. *Econometrica*, 55(3), 703-708.

Verify: Moment conditions, weight matrix specifications, standard error calculations.

### Futures Hedging

Key papers:
- Ederington, L. H. (1979). The hedging performance of the new futures markets. *Journal of Finance*, 34(1), 157-170.
- Kroner, K. F., & Sultan, J. (1993). Time-varying distributions and dynamic hedging with foreign currency futures. *Journal of Financial and Quantitative Analysis*, 28(4), 535-551.

Verify: Hedge ratio formulas, effectiveness measures, comparison benchmarks.

## Quality Standards

### Acceptable Citation
- All bibliographic details verified against original source
- DOI present and resolves correctly (or confirmed unavailable)
- Content claims accurately reflect source (±reasonable paraphrasing)
- APA 7th edition format followed

### Flagged for Review
- Minor formatting issues (spacing, italics, punctuation)
- DOI missing but obtainable
- Slight paraphrasing that may oversimplify

### Requires Correction
- Factual errors in bibliographic information
- Content misrepresentation (claims source says something it doesn't)
- Wrong author attribution
- Fabricated or non-existent sources
- Significant APA format violations

## Important Notes

1. **Always verify via web search** - Never assume a citation is correct based on memory
2. **Check primary sources** - Don't rely on secondary citations
3. **Note uncertainty** - If unable to verify, clearly state this in the report
4. **Preserve original intent** - Corrections should maintain the author's scholarly argument
5. **Be thorough but efficient** - Focus verification effort on claims central to the manuscript's argument
