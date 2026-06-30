# Journal of Banking & Finance - Author Guidelines Summary

**Journal**: Journal of Banking & Finance (JBF)
**Publisher**: Elsevier
**ISSN**: 0378-4266
**ABS Ranking**: 3
**Impact Factor**: ~3.5 (varies by year)

**Official Guidelines**: https://www.elsevier.com/journals/journal-of-banking-and-finance/

---

## Submission Requirements

### Manuscript Format

**Length**:
- No strict limit, but typically 8,000-12,000 words
- Longer papers acceptable if justified by complexity
- Include word count in cover letter

**Structure**:
1. Title page (separate file)
   - Title
   - Author names and affiliations
   - Contact information
   - Acknowledgments
   - Funding disclosure

2. Main manuscript (anonymous for review)
   - Abstract (150-250 words)
   - Keywords (4-6 keywords)
   - JEL classification codes
   - Main text
   - References
   - Tables and figures (can be separate or embedded)

3. Supplementary materials (optional)
   - Online appendix
   - Replication code and data

### File Types

**Preferred**: LaTeX (.tex) or Microsoft Word (.docx)
**Figures**: EPS, PDF (vector) or high-resolution TIFF/PNG (300+ DPI)
**Tables**: Editable format (LaTeX, Word table, or Excel)

---

## Content Standards

### Abstract

**Required elements**:
- Research question/motivation
- Methodology
- Key findings
- Implications

**Style**: Self-contained, no citations

**Length**: 150-250 words

### Keywords & JEL Codes

**Keywords**: 4-6 terms for indexing

**JEL Codes**: 2-4 standard JEL classification codes
- Find codes at: https://www.aeaweb.org/econlit/jelCodes.php
- Example for Hawkes hedging paper: G13, C58, G11

### Main Text

**Mandatory sections**:
1. Introduction
2. Literature Review (can be integrated into Introduction)
3. Methodology/Theoretical Framework
4. Data and Sample
5. Empirical Results
6. Robustness Checks
7. Conclusion

**Optional sections**:
- Extended literature review
- Additional empirical tests
- Policy implications

---

## Style Guidelines

### Writing Style

**Prose only**: NO bullet points in main text
- Convert all lists to flowing sentences
- Bullet points OK in: response to reviewers, online appendix

**Person**: Third person or "we" (both acceptable)
- Avoid excessive use of "we"
- Prefer: "The results show..." vs "We show..."

**Tense**:
- Past: "We estimated the model..."
- Present: "Table 2 shows...", "The results indicate..."

**Voice**: Active voice preferred when appropriate

### Numbers and Symbols

**Use Arabic numerals for**:
- All numerical data: years (2003), counts (14 parameters), percentages (5%)
- Sample sizes, observations
- Equations and references

**Spell out**:
- Numbers at start of sentence: "Fourteen parameters are estimated..."
- Small cardinal numbers in text: "three reasons", "two approaches"

**Consistency**: Maintain uniform style throughout

### Equations

**Numbering**:
- Number all equations referenced in text
- Right-aligned: (1), (2), (3)
- Sequential numbering throughout paper

**Format**:
```latex
\begin{equation}
dX_i(t) = \mu_i dt + \sigma_i dW_i(t) + Z_i dN_i(t)
\label{eq:model}
\end{equation}
```

**Explanation**: Every equation needs surrounding text explaining:
- What it represents
- Why this specification
- Definition of all symbols

### Tables

**Format**: LaTeX booktabs style preferred

**Requirements**:
- Table number and title above table
- Column headers clearly labeled
- Footnotes below table explaining:
  - Variable definitions
  - Sample period
  - Estimation method
  - Significance levels: *** p<0.01, ** p<0.05, * p<0.1

**Example caption**:
```
Table 1: Descriptive Statistics

This table reports summary statistics for daily returns on Taiwan Index
Futures (F) and Taiwan Weighted Stock Index (S). Sample period: January 2,
2003 to October 30, 2025 (5,644 observations). Returns are in percentages.
```

### Figures

**Format**: Vector preferred (EPS, PDF)
- If raster: minimum 300 DPI
- Avoid pixelated images

**Requirements**:
- Figure number and title below figure
- All axes labeled with units
- Legend explaining all lines/markers
- Caption explaining what figure shows

**Fonts**: Readable size (minimum 10pt in final figure)

**Color**: Use color-blind friendly palettes

---

## References

### Style

**Harvard (author-date) system**:
- In-text: (Smith, 2010) or Smith (2010)
- Multiple: (Smith, 2010; Jones, 2012)
- Three+ authors: Smith et al. (2010)

### Reference List Format

**Journal articles**:
```
Aït-Sahalia, Y., Cacho-Diaz, J., Laeven, R.J.A., 2015. Modeling financial
    contagion using mutually exciting jump processes. Journal of Financial
    Economics 117, 585–606. https://doi.org/10.1016/j.jfineco.2014.11.003
```

**Books**:
```
Campbell, J.Y., Lo, A.W., MacKinlay, A.C., 1997. The Econometrics of
    Financial Markets. Princeton University Press, Princeton, NJ.
```

**Working papers**:
```
Aït-Sahalia, Y., Cacho-Diaz, J., Laeven, R.J.A., 2010. Modeling Financial
    Contagion Using Mutually Exciting Jump Processes. NBER Working Paper
    No. 15850.
```

**DOI**: Include when available

**Alphabetical order**: By first author surname

---

## Reproducibility & Data

### Replication Package (Mandatory from 2024)

**Must include**:
1. All estimation code
   - Scripts to produce tables
   - Scripts to produce figures
   - Scripts for robustness checks

2. Data or data access instructions
   - If proprietary: Detailed instructions for obtaining
   - If public: Direct download links
   - Sample data if full data restricted

3. README file
   - Software requirements (versions)
   - Execution instructions
   - Expected runtime
   - Description of output

### Code Requirements

**Documentation**:
- Comments explaining key steps
- Header with author, date, purpose
- Modular structure (not one giant script)

**Software**:
- R, Python, Stata, MATLAB acceptable
- Julia, C++, Fortran acceptable (provide compilation instructions)
- Proprietary software OK but open-source preferred

**Portability**:
- Relative paths (not absolute: "/Users/john/...")
- Set random seeds
- Document OS tested on

---

## Submission Process

### Initial Submission

1. **Create account** at Editorial Manager: https://www.editorialmanager.com/jbf/

2. **Prepare files**:
   - Title page (with author info)
   - Main manuscript (anonymous)
   - Tables and figures
   - Supplementary materials

3. **Cover letter** addressing:
   - Why suitable for JBF
   - Confirmation of original work
   - Disclosure of prior versions (SSRN, conferences)
   - Suggested reviewers (optional)

4. **Submit through Editorial Manager**

### Editorial Process

**Desk review** (2-4 weeks):
- Editor screens for fit and quality
- 30-40% desk reject

**Peer review** (2-4 months):
- Sent to 2 reviewers
- Reviewers assess and make recommendation

**Decision**:
- Accept (rare at first submission)
- Minor Revision
- Major Revision
- Revise & Resubmit
- Reject

### Revision Submission

**Response letter** (mandatory):
- Point-by-point response to every comment
- Explain changes made
- Justify if not following suggestion

**Format**:
```
Reviewer 1, Comment 1: "Sample period is too short"

Response: We have extended the sample period from 2015-2020 to 2010-2023,
increasing observations from 1,250 to 3,250. The main results remain
qualitatively similar (see revised Table 2) but standard errors are now
15% smaller, strengthening our inferences.

Changes: Table 2, Section 4.2 (pages 18-22), Figure 4.
```

**Highlight changes** in manuscript:
- Use revision marks in Word
- Color changed text in LaTeX (use \textcolor)

**Resubmit within deadline** (typically 3-6 months)

---

## Ethical Guidelines

### Authorship

**All authors must**:
- Have made substantial contribution
- Approve final version
- Agree to be accountable for work

**Corresponding author** responsible for:
- Communication with journal
- Ensuring all co-authors approve submission
- Coordinating revisions

### Conflicts of Interest

**Disclose**:
- Financial interests in subject companies
- Consulting relationships
- Funding sources

### Data Ethics

**Required**:
- IRB approval if human subjects data
- Permission if using proprietary data
- Acknowledgment of data providers

### Prior Dissemination

**Allowed**:
- Conference presentations
- Working paper series (SSRN, NBER)
- Personal/institutional websites

**Must disclose** in cover letter

**Not allowed**:
- Simultaneous submission to other journals
- Publication of identical content elsewhere

---

## Common Rejection Reasons

### Desk Reject (30-40%)

1. **Out of scope**: Not related to banking/finance
2. **Insufficient novelty**: Incremental advance
3. **Poor quality**: Major methodological flaws
4. **Wrong venue**: Better suited to other journal

### After Review (60-70% of reviewed papers)

1. **Weak contribution**: "So what?" problem
2. **Methodology issues**: Identification, standard errors
3. **Insufficient robustness**: Limited checks
4. **Sample concerns**: Too short, biased selection
5. **Poor execution**: Writing, presentation

---

## Tips for Success

### Before Submitting

**Self-review**:
- Read your paper as if you were a skeptical reviewer
- Have colleagues review
- Check all citations are accurate
- Verify all numbers in tables match text

**Quality check**:
- All equations numbered and explained
- All tables have notes explaining content
- All figures have clear captions
- References complete with DOIs

**Comparison**:
- Read recent JBF papers in your area
- Match their level of rigor
- Ensure your contribution is clear vs those papers

### Cover Letter

**Template**:
```
Dear Editor,

We submit our manuscript "Title" for consideration at the Journal of Banking
& Finance. The paper contributes to the literature on [topic] by [contribution].

[2-3 sentences on why this is important and suitable for JBF]

This manuscript represents original work and is not under consideration
elsewhere. We have no conflicts of interest to disclose. A preliminary
version was presented at [conference] and is available as [working paper].

Thank you for considering our work.

Sincerely,
[Authors]
```

### Suggested Reviewers

**Optional but helpful**:
- 3-5 names
- Experts in your area
- No conflicts of interest
- Mix of junior and senior scholars

**Format**:
```
1. Professor Jane Smith, University of X (jane.smith@university.edu)
   Expertise: GMM estimation, jump-diffusion models
   Reason: Published seminal work on Hawkes processes in finance

2. Dr. John Doe, Bank of Y (john.doe@bank.edu)
   Expertise: Futures hedging, financial econometrics
   Reason: Leading researcher on dynamic hedging strategies
```

---

## Post-Acceptance

### Proofs

**Timing**: 2-4 weeks after acceptance

**Tasks**:
- Review typeset version
- Check for formatting errors
- NO major content changes allowed
- Return within 48 hours

### Open Access

**Options**:
- Subscription (default, no author fee)
- Open access ($3,000-$3,500 fee)

**Funder requirements**: Check if funder requires open access

### Copyright

**Transfer to Elsevier** (standard agreement)
- Retain right to post preprint
- Can share final version on personal website

---

## Useful Resources

**Journal homepage**: https://www.elsevier.com/journals/journal-of-banking-and-finance/

**Editorial Manager**: https://www.editorialmanager.com/jbf/

**LaTeX template**: Available on journal website

**JEL codes**: https://www.aeaweb.org/econlit/jelCodes.php

**Elsevier author hub**: https://www.elsevier.com/authors

---

## Contact Information

**Managing Editor**: Journal of Banking & Finance

**Email**: jbf@elsevier.com

**Publisher**: Elsevier B.V.
The Boulevard, Langford Lane
Kidlington, Oxford OX5 1GB, UK

---

## Typical Timeline

| Stage | Duration |
|-------|----------|
| Desk review | 2-4 weeks |
| Peer review (if not desk reject) | 2-4 months |
| Revision period (if R&R) | 3-6 months |
| Re-review | 1-2 months |
| Final decision to publication | 2-4 months |
| **Total (if accepted first R&R)** | **8-16 months** |

**Note**: Multiple revision rounds can extend timeline to 2-3 years

---

*This summary is based on JBF author guidelines as of 2024. Always check the official journal website for most current requirements.*

---

## Checklist Before Submission

**Manuscript Preparation**:
- [ ] Title page with all author info
- [ ] Anonymous main manuscript
- [ ] Abstract (150-250 words)
- [ ] Keywords (4-6) and JEL codes (2-4)
- [ ] All sections present (intro, methods, results, conclusion)
- [ ] References formatted correctly
- [ ] Tables and figures properly formatted

**Content Quality**:
- [ ] Clear contribution statement
- [ ] Literature review comprehensive
- [ ] Methodology rigorous
- [ ] Robustness checks included (minimum 3-4)
- [ ] Results clearly presented
- [ ] Limitations discussed

**Style Compliance**:
- [ ] NO bullet points in main text
- [ ] Arabic numerals for data
- [ ] All equations explained
- [ ] All tables have notes
- [ ] All figures have captions

**Reproducibility**:
- [ ] Replication code prepared
- [ ] Data or data instructions included
- [ ] README file created
- [ ] Code tested on clean environment

**Ethics & Disclosures**:
- [ ] All authors approve submission
- [ ] Conflicts of interest disclosed
- [ ] Funding acknowledged
- [ ] Data permissions obtained

**Submission Materials**:
- [ ] Cover letter written
- [ ] Suggested reviewers (optional)
- [ ] All files uploaded to Editorial Manager

**Final Check**:
- [ ] Proofread entire manuscript
- [ ] All citations accurate (especially Hawkes vs Hamilton!)
- [ ] Numbers in text match tables
- [ ] Figures referenced correctly
- [ ] Contact info current
