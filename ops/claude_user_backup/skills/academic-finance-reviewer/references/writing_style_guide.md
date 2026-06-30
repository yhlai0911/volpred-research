# Academic Writing Style Guide for Finance Research

Comprehensive guide to writing style, formatting, and presentation standards for top-tier finance journals.

---

## Golden Rules

1. **NO BULLET POINTS** in main text (prose only)
2. **Arabic numerals** for scientific data (2003, 150個, 5分鐘, 14個參數)
3. **Third person** preferred (avoid excessive "I/we")
4. **Active voice** when possible
5. **Simple, clear sentences** (academic ≠ complex)

---

## Number Formatting

### When to Use Arabic Numerals

✅ **ALWAYS use Arabic numerals**:
- Years: 2003年, 2024年
- Counts: 14個參數, 150個moment conditions, 5,644筆觀察值
- Measurements: 5分鐘, 3倍標準差, 12個月
- Decimals: 0.05, 1.96, 3.14
- Percentages: 5%, 95.3%
- Sample sizes: n = 5,644

### When Chinese/Ordinal Numbers Are OK

✓ **Acceptable for ordinals**:
- 第一階段, 第二階段 (first stage, second stage)
- 第三章 (Chapter 3)
- 第一個貢獻 (first contribution)

✓ **Small amounts in prose** (optional):
- "兩個資產" or "2個資產" (both OK)
- "三種方法" or "3種方法" (both OK)

### Examples

```markdown
❌ 我們使用五分鐘資料、十四個參數、三個時間尺度
✅ 我們使用5分鐘資料、14個參數、3個時間尺度

❌ 樣本期間為二〇〇三年至二〇二三年
✅ 樣本期間為2003年至2023年

✅ 本研究分為第一階段與第二階段 (ordinals OK)
✅ 本研究分為2個階段 (counts → Arabic)
```

---

## Bullet Points: Convert to Prose

### The Problem

Many drafts use bullet points for lists:

```markdown
❌ Our contributions are:
    • First Hawkes application to hedging
    • Use of high-frequency data
    • 23% improvement in performance
```

### The Solution

**Method 1: Numbered sentences**
```markdown
✅ Our paper makes three contributions. First, we are the first to apply
   Hawkes processes to dynamic hedging. Second, we employ high-frequency
   data to identify intraday jump contagion. Third, we demonstrate 23%
   improvement in hedge effectiveness relative to standard methods.
```

**Method 2: Integrated paragraph**
```markdown
✅ Our paper contributes to the literature in three ways. We are the first
   to incorporate Hawkes jump-diffusion models into dynamic hedge ratio
   calculation, extending prior work that relied on GARCH-based approaches
   (Kroner & Sultan, 1993; Lien & Tse, 2002). Leveraging high-frequency
   intraday data, we identify time-varying jump intensities that capture
   futures-spot contagion effects not visible in daily data. Finally, we
   demonstrate economically significant performance gains, with hedge
   effectiveness improving by 23% in crisis periods relative to OLS and
   GARCH benchmarks.
```

### Exception: Where Bullets Are OK

✓ **Online appendix**: Technical details, additional results
✓ **Presentation slides**: For readability
✓ **Response to reviewers**: Clear point-by-point format
✗ **Main manuscript**: Never

---

## Voice and Tense

### Active vs Passive Voice

**Prefer active** when subject is clear:

```markdown
❌ The model is estimated using GMM
✅ We estimate the model using GMM

❌ It was found that contagion is significant
✅ We find significant contagion
```

**Passive OK** when action is more important than actor:

```markdown
✓ The data are obtained from Taiwan Futures Exchange
✓ Standard errors are computed using Newey-West estimator
```

### Tense Guidelines

**Present tense** for:
- General truths: "Hawkes processes capture jump clustering"
- Paper content: "Section 3 describes the estimation procedure"
- Results discussion: "The results show significant contagion"

**Past tense** for:
- What you did: "We estimated the model using GMM"
- Data description: "The sample included 5,644 daily observations"
- Prior literature: "Johnson (1960) proposed the minimum variance hedge ratio"

**Example paragraph**:
```markdown
We estimate the model using two-stage GMM (past - what we did). The first
stage uses truncated returns to identify diffusion parameters (present -
describing method). Table 2 reports the results (present - paper content).
We find that the contagion parameter β_{SF} equals 17.8 with t-statistic
7.1 (past - what we found). This estimate is statistically significant
and economically meaningful (present - interpretation).
```

---

## Person (First vs Third)

### Modern Finance Journals

**Acceptable**: "We estimate...", "Our results show..."

**Traditional**: "This paper estimates...", "The results show..."

**Avoid**: "I", "my" (unless single-author)

### Balance

Don't overuse "we":

```markdown
❌ We use GMM. We find that we can improve hedging. We show that we...
✅ The paper employs GMM estimation. Results indicate improved hedging
   performance. Specifically, we demonstrate...
```

**Vary**:
- "We estimate..."
- "The analysis reveals..."
- "Our results indicate..."
- "The data show..."
- "Table 2 reports..."

---

## Sentence Structure

### Keep It Simple

**Bad** (too complex):
```markdown
❌ The utilization of a two-stage GMM estimation procedure, whereby the first
   stage involves the estimation of diffusion parameters through the employment
   of truncated returns, which are returns that have been subjected to a
   filtering process that removes observations exceeding three standard
   deviations, enables us to subsequently, in the second stage, proceed with
   the estimation of the jump parameters.
```

**Good** (clear, direct):
```markdown
✅ We employ a two-stage GMM procedure. The first stage estimates diffusion
   parameters using truncated returns (removing observations exceeding 3σ).
   The second stage then estimates jump parameters conditional on the
   diffusion estimates.
```

### One Idea Per Sentence

**Bad**:
```markdown
❌ We find that contagion is significant and economically large and robust
   to alternative specifications and consistent across subperiods and our
   approach improves hedging by 23%.
```

**Good**:
```markdown
✅ We find significant and economically large contagion effects. The results
   are robust to alternative specifications and consistent across subperiods.
   Relative to OLS benchmarks, our approach improves hedging effectiveness
   by 23%.
```

### Avoid Nominalizations

**Nominalization** = turning verbs into nouns

```markdown
❌ The estimation of parameters (nominalization of "estimate")
✅ We estimate parameters

❌ The computation of moments (nominalization of "compute")
✅ We compute moments

❌ The identification of jumps (nominalization of "identify")
✅ We identify jumps
```

---

## Transitions and Flow

### Between Paragraphs

**Use transition sentences**:

```markdown
Having established the theoretical framework, we now turn to estimation.

While the previous section focused on methodology, we next describe the data.

These findings raise the question: how robust are the results to alternative
specifications? We address this concern in Section 6.
```

### Within Sections

**Signpost**:
```markdown
The estimation proceeds in three steps. First, we...
Second, we... Finally, we...

We address this issue in two ways. On the one hand, we...
On the other hand, we...

The results support three conclusions. The first...
The second... The third...
```

---

## Common Weak Phrases to Avoid

### Replace with Stronger Alternatives

| ❌ Weak | ✅ Strong |
|---------|-----------|
| In order to | To |
| Due to the fact that | Because |
| A large number of | Many |
| It is important to note that | Importantly, / Note that |
| It can be seen that | We observe / The data show |
| There is evidence that | Evidence suggests / We find |
| It is our belief that | We believe / We argue |
| In this paper we | We |
| Based on the results | The results suggest |

### Examples

```markdown
❌ In order to estimate the parameters, we use GMM
✅ To estimate the parameters, we use GMM

❌ Due to the fact that the data exhibit clustering, we use Hawkes processes
✅ Because the data exhibit clustering, we use Hawkes processes

❌ It is important to note that our findings are robust
✅ Importantly, our findings are robust
```

---

## Equations and Mathematical Notation

### Integration with Text

**Every equation needs context**:

```markdown
❌ [Equation appears]
   dλ_F(t) = α(λ∞ - λ_F(t))dt + β_{FF}dN_F(t)

❌ [No explanation]

✅ The intensity follows the Hawkes specification:

   dλ_F(t) = α(λ∞ - λ_F(t))dt + β_{FF}dN_F(t)    (7)

   where α is the mean reversion rate, λ∞ is the baseline intensity, and
   β_{FF} captures self-excitation. This specification nests the constant
   intensity model (β_{FF} = 0) as a special case.
```

### Define All Symbols

**Bad**:
```markdown
❌ We estimate θ = (α, β, λ∞, γ)
   [No definition of what these are]
```

**Good**:
```markdown
✅ We estimate the parameter vector θ = (α, β, λ∞, γ), where α denotes
   the mean reversion speed, β the self-excitation parameter, λ∞ the
   long-run intensity, and γ the jump size parameter.
```

### Equation Numbering

- Number all equations referenced in text
- Right-align equation numbers: (1), (2), (3)
- Reference as: "Equation (7) shows...", "From (7), we see..."

---

## Tables

### Format Standards

**Use LaTeX booktabs** style:

```latex
\begin{table}[htbp]
\centering
\caption{GMM Estimation Results}
\label{tab:results}
\begin{tabular}{lrrrr}
\toprule
Parameter & Estimate & Std. Error & t-stat & p-value \\
\midrule
α         & 125.3    & 8.2        & 15.28  & <0.001*** \\
β_{FF}    & 18.7     & 2.1        & 8.90   & <0.001*** \\
β_{SF}    & 17.8     & 2.5        & 7.12   & <0.001*** \\
\midrule
\multicolumn{5}{l}{Model Diagnostics} \\
J-statistic        & \multicolumn{2}{c}{18.42} & \multicolumn{2}{c}{p = 0.187} \\
Sample size        & \multicolumn{4}{c}{5,644} \\
\bottomrule
\end{tabular}
\begin{tablenotes}
\small
\item \textit{Notes}: Standard errors computed using Newey-West HAC estimator
      with 5 lags. Sample period: 2003-01-02 to 2025-10-30.
      *** p<0.01, ** p<0.05, * p<0.1
\end{tablenotes}
\end{table}
```

### Table Captions

**Self-contained** - reader should understand table without reading text:

```markdown
❌ Table 2: Results

✅ Table 2: Two-Stage GMM Estimation Results for Bivariate Hawkes Model

   This table reports parameter estimates from the two-stage GMM procedure
   described in Section 4. Panel A shows diffusion parameters from Stage 1.
   Panel B shows Hawkes jump parameters from Stage 2. Standard errors are
   computed using the Newey-West HAC estimator with 5 lags. Sample:
   5,644 daily observations from January 2, 2003 to October 30, 2025.
```

### Decimal Places

**Consistent rounding**:
- Parameters: 1-2 decimals (17.8, not 17.832584)
- Standard errors: Match parameter decimals
- t-statistics: 1-2 decimals
- p-values: 3 decimals or "<0.001"

---

## Figures

### Requirements

1. **Vector format**: PDF or EPS (not PNG/JPEG for submission)
2. **High resolution**: 300+ DPI if raster
3. **Readable fonts**: Minimum 10pt in final size
4. **Color-blind safe**: Use colorblind-friendly palettes
5. **Self-contained caption**: Explain all elements

### Caption Example

```markdown
Figure 3: Time Series of Filtered Jump Intensities

This figure plots the filtered jump intensities λ_F(t) (solid line) and
λ_S(t) (dashed line) for the sample period January 2020 to December 2023.
Intensities are computed recursively using equation (7) with parameter
estimates from Table 2. Gray shaded regions indicate crisis periods
(COVID: March-April 2020; Market correction: January-March 2022). Jump
intensities spike dramatically during crisis periods, reaching 10x baseline,
consistent with the clustering predicted by the Hawkes model.
```

### Common Mistakes

❌ Tiny axis labels
❌ Overlapping legends
❌ Too many colors (hard to distinguish)
❌ No units on axes
❌ Caption just says "Results"

---

## Citations and References

### In-Text Citations

**Harvard style** (Author, Year):

```markdown
Following Aït-Sahalia et al. (2015), we specify...

Prior studies find mixed results (Johnson, 1960; Ederington, 1979;
Lien & Tse, 2002).

As shown by Hawkes (1971) and Daley and Vere-Jones (2003), the intensity...
```

### Reference List

**Alphabetical by first author surname**:

```markdown
Aït-Sahalia, Y., Cacho-Diaz, J., Laeven, R.J.A., 2015. Modeling financial
    contagion using mutually exciting jump processes. Journal of Financial
    Economics 117, 585–606.

Hawkes, A.G., 1971. Spectra of some self-exciting and mutually exciting
    point processes. Biometrika 58, 83–90.

Lien, D., Tse, Y.K., 2002. Some recent developments in futures hedging.
    Journal of Economic Surveys 16, 357–396.
```

### DOI

**Include DOI** when available (journal requirement):

```markdown
Aït-Sahalia, Y., Jacod, J., 2014. High-Frequency Financial Econometrics.
    Princeton University Press, Princeton, NJ.
    https://doi.org/10.1515/9781400850327
```

---

## Abstract

### Structure

**150-200 words**, covering:
1. **Motivation** (1-2 sentences): What's the problem?
2. **Method** (2-3 sentences): What do you do?
3. **Results** (2-3 sentences): What do you find?
4. **Conclusion** (1 sentence): So what?

### Example

```markdown
Abstract

Traditional hedging strategies fail to account for jump contagion between
futures and spot markets, leading to suboptimal performance during crises.
We develop a dynamic hedge ratio based on bivariate Hawkes jump-diffusion
processes, explicitly modeling time-varying jump intensities and spillover
effects. Using high-frequency data from Taiwan futures markets (2010-2024),
we estimate the model via three-stage GMM. We find significant contagion:
futures jumps increase spot jump intensity by 45% within one hour. Our
dynamic Hawkes-based hedge ratios improve effectiveness by 23% relative to
OLS and 15% relative to GARCH methods, with gains concentrated in crisis
periods when hedging is most valuable. The results demonstrate the importance
of modeling jump clustering and contagion for risk management applications.

Keywords: Hawkes processes; Jump-diffusion; Futures hedging; GMM estimation;
          Financial contagion
JEL Classification: G13, C58, G11
```

---

## Introduction Template

### Paragraph 1: Motivation

```markdown
Opening hook (broad problem)
↓
Narrow to specific issue
↓
Why it matters (economic significance)
```

**Example**:
```markdown
Effective hedging of financial risk requires understanding how extreme events
propagate across markets. Traditional hedging models assume constant volatility
or independent jumps, failing to capture the clustering and contagion effects
observed during crises. These failures can lead to substantial hedging errors
precisely when protection is most needed, with costs reaching billions of
dollars during market turmoil.
```

### Paragraph 2: Gap in Literature

```markdown
What we know (prior literature)
↓
What we don't know (gap)
↓
Why this gap matters
```

### Paragraph 3: What You Do

```markdown
We address this gap by...
↓
Our approach (method in 2-3 sentences)
↓
Key innovation
```

### Paragraph 4: What You Find

```markdown
Main finding 1
↓
Main finding 2
↓
Main finding 3
```

### Paragraph 5: Contribution & Roadmap

```markdown
Three contributions:
1. Method
2. Empirical
3. Practical

Roadmap: "The rest of the paper..."
```

---

## Conclusion

### Structure

**DO**:
- Summarize 3-4 main findings (1 paragraph)
- Limitations and caveats (1 paragraph)
- Future research directions (1 paragraph)
- Practical implications if applicable

**DON'T**:
- Introduce new results
- Repeat introduction verbatim
- End abruptly without takeaways

### Template

```markdown
Paragraph 1: Summary
This paper develops and estimates a bivariate Hawkes jump-diffusion model
for futures-spot markets. Three findings emerge...

Paragraph 2: Limitations
Several limitations should be noted. First, our analysis focuses on a single
market (Taiwan)... Second, we assume exponentially distributed jump sizes...

Paragraph 3: Extensions
Future research could extend our framework in several directions...

Paragraph 4: Implications (if applicable)
For practitioners, our results suggest that...
```

---

## Common Grammar Mistakes

### 1. Data is/are

**"Data" is plural**:
```markdown
❌ The data is obtained from...
✅ The data are obtained from...

✅ The dataset is obtained from... (dataset = singular)
```

### 2. Which vs That

**"That" = restrictive** (essential):
```markdown
✅ We use the model that Hawkes (1971) proposed
```

**"Which" = non-restrictive** (additional info):
```markdown
✅ We use GMM, which is a semi-parametric method
```

### 3. Fewer vs Less

**"Fewer" for countable**:
```markdown
✅ Fewer observations
✅ Fewer parameters
```

**"Less" for uncountable**:
```markdown
✅ Less noise
✅ Less autocorrelation
```

### 4. Effect vs Affect

**"Effect" = noun**:
```markdown
✅ The contagion effect is significant
```

**"Affect" = verb**:
```markdown
✅ Jumps affect future intensity
```

---

## Revision Checklist

Before submitting, check:

### Content
- [ ] Clear contribution statement (introduction paragraph 5)
- [ ] All citations accurate (especially Hawkes vs Hamilton!)
- [ ] Every equation explained
- [ ] All symbols defined

### Style
- [ ] No bullet points in main text
- [ ] Arabic numerals for data (2003, 14, 5分鐘)
- [ ] Consistent tense within sections
- [ ] Active voice where appropriate
- [ ] No nominalizations

### Presentation
- [ ] Tables in LaTeX format
- [ ] Figures vector format (PDF/EPS)
- [ ] Captions self-contained
- [ ] Decimal places consistent

### Technical
- [ ] All standard errors correct (GMM, not optimizer)
- [ ] Robustness checks included
- [ ] Replication code ready
- [ ] References complete with DOIs

---

## Tools and Resources

### Writing Tools

**Grammar**:
- Grammarly (catches basic errors)
- LanguageTool (open-source alternative)

**LaTeX**:
- Overleaf (online collaborative editing)
- TeXstudio (desktop editor)

**Tables**:
- `stargazer` (R package)
- `estout` (Stata)
- Manual LaTeX (most flexible)

**Figures**:
- Matplotlib/Seaborn (Python)
- ggplot2 (R)
- Save as PDF: `fig.savefig('figure.pdf', format='pdf', bbox_inches='tight')`

### Style Guides

**Academic Writing**:
- Strunk & White, "The Elements of Style"
- Williams & Bizup, "Style: Lessons in Clarity and Grace"

**Finance Specific**:
- Cochrane, "Writing Tips for PhD Students"
- Kwan & Craig, "A Guide to Writing a Successful Research Paper"

**LaTeX**:
- AEA Template: https://www.aeaweb.org/journals/templates
- Journal-specific templates from journal websites

---

## Final Polish

### Read Aloud

**Why**: Catches awkward phrasing you miss when reading silently

**How**: Read entire paper aloud, preferably to someone else

### Reverse Outline

**What**: After writing, create outline from existing paragraphs

**Why**: Checks logical flow, identifies gaps

**How**: One sentence per paragraph summarizing its point

### Fresh Eyes

**What**: Set paper aside for 1 week, then re-read

**Why**: You'll see issues you were blind to before

**How**: Print out, read on paper (easier to catch errors than on screen)

---

**Remember**: Good writing = clear thinking. If you can't explain it simply, you don't understand it well enough.
