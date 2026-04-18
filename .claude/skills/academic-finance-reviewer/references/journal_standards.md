<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

# Journal Standards for Top Finance Journals

This document outlines specific requirements and standards for top-tier finance journals commonly targeted by financial econometrics research.

---

## Journal of Banking & Finance (JBF)

**Target ABS Ranking**: 3
**Typical Acceptance Rate**: 8-12%
**Focus**: Banking, corporate finance, asset pricing, derivatives

### Formatting Requirements

- **Main Text**: NO bullet points (prose only)
- **Tables**: LaTeX format preferred, professional formatting
- **Figures**: High resolution (300+ DPI), vector format (PDF/EPS) preferred
- **References**: Harvard style (Author, Year)
- **Equations**: Numbered consecutively, right-aligned numbers
- **Supplementary Materials**: Encouraged for robustness checks

### Content Expectations

1. **Abstract**: 150-200 words, structured (Objective, Methods, Results, Conclusions)
2. **Introduction**: Clear motivation, contribution, literature positioning
3. **Literature Review**: Comprehensive but focused (20-40 key papers)
4. **Methodology**: Rigorous derivations, clear assumptions
5. **Empirical Design**: Sample justification, variable construction, robustness checks
6. **Results**: Main results + extensive robustness
7. **Conclusion**: Policy implications encouraged

### Statistical Rigor

- Report standard errors/t-statistics for ALL estimates
- Multiple robustness checks (minimum 3-4 specifications)
- J-test for overidentified models
- Bootstrap standard errors if asymptotic theory questionable
- Subperiod analysis (crisis vs normal periods)
- Alternative specifications

### Common Rejection Reasons

1. Insufficient contribution vs existing literature
2. Weak identification or endogeneity concerns
3. Limited robustness checks
4. Sample period concerns (too short, cherry-picking)
5. Poor writing quality
6. Overstated claims

---

## Journal of Financial Economics (JFE)

**Target ABS Ranking**: 4*
**Typical Acceptance Rate**: 5-8%
**Focus**: Asset pricing, corporate finance, market microstructure

### Higher Standards vs JBF

- Stronger theoretical foundation required
- Larger contribution threshold
- More extensive data requirements
- Publication lag: 2-4 years typical

### Specific Requirements

- **Theory Section**: Formal model preferred (even for empirical papers)
- **Economic Significance**: Must demonstrate in addition to statistical
- **Data Quality**: Premium data sources expected
- **Replication Package**: Mandatory (code + data or data access instructions)

---

## Journal of Econometrics (JoE)

**Target ABS Ranking**: 4
**Typical Acceptance Rate**: 6-10%
**Focus**: Econometric methodology, time series, financial econometrics

### Methodological Focus

- **Theory**: Rigorous proofs required for new methods
- **Monte Carlo**: Comprehensive simulation studies
- **Asymptotic Theory**: Formal convergence results
- **Application**: Empirical application to demonstrate usefulness

### JoE Standards for GMM/Hawkes Papers

1. **Identification**: Formal identification theorem
2. **Consistency**: Prove consistency under stated assumptions
3. **Asymptotic Normality**: Derive limiting distribution
4. **Finite Sample**: Monte Carlo evidence
5. **Empirical**: Real data application

---

## Review of Financial Studies (RFS)

**Target ABS Ranking**: 4*
**Typical Acceptance Rate**: 4-7%
**Focus**: Asset pricing, market microstructure, corporate finance

### Ultra-High Standards

- Top 5 finance journal
- Requires groundbreaking contribution
- Extensive referee process (often 3+ rounds)
- Publication typically 3-5 years

### Key Expectations

- Novel question or novel answer to important question
- Clean identification strategy
- Comprehensive empirical analysis
- Strong theoretical motivation
- Policy/practical relevance

---

## Journal of Financial Markets (JFM)

**Target ABS Ranking**: 2
**Typical Acceptance Rate**: 12-18%
**Focus**: Market microstructure, trading, liquidity, price discovery

### Ideal for High-Frequency Research

- Welcomes high-frequency data studies
- Jump detection methods
- Intraday patterns
- Market microstructure noise
- Liquidity dynamics

### Standards (Lower than JBF but Rigorous)

- Clear contribution to market microstructure literature
- Careful treatment of microstructure noise
- Multiple market comparisons encouraged
- Institutional details important

---

## Finance Research Letters (FRL)

**Target ABS Ranking**: 2
**Typical Acceptance Rate**: 15-20%
**Focus**: Short, novel empirical findings

### Format Requirements

- **Length**: Maximum 3000 words (strict)
- **Tables**: Maximum 3-4 tables
- **Focus**: Single clear finding
- **Turnaround**: Fast review process (3-6 months)

### Good for:

- Initial findings (before full JBF paper)
- Replication studies with new data
- Extension of existing methods to new market
- Quick publication needed

### Not Good for:

- Complex methodological contributions
- Papers requiring extensive exposition
- Multiple research questions

---

## General Standards Across All Journals

### Writing Style

1. **No Bullet Points**: Main text must be prose
2. **Active vs Passive**: Prefer active voice
3. **Person**: Third person (avoid "I/we" excessively)
4. **Tense**: Past for methodology, present for results discussion
5. **Clarity**: Simple sentences preferred over complex

### Number Formatting

- **Scientific Data**: Arabic numerals (2003, 150個, 5分鐘, 14個參數)
- **Ordinals in Text**: Can use Chinese/English ordinals (第一階段, first stage)
- **Consistency**: Maintain within paper

### Citation Accuracy

- **Hawkes**: MUST cite Hawkes (1971), NOT Hamilton (1989)
- **GMM**: Hansen (1982) required
- **Newey-West**: Newey and West (1987)
- **Self-citations**: Limit to relevant papers only

### Tables

```latex
\begin{table}[htbp]
\centering
\caption{Estimation Results for Bivariate Hawkes Model}
\label{tab:main_results}
\begin{tabular}{lcccc}
\toprule
Parameter & Estimate & Std. Error & t-stat & p-value \\
\midrule
$\alpha$ & 125.3 & 8.2 & 15.28 & <0.001*** \\
$\beta_{11}$ & 18.7 & 2.1 & 8.90 & <0.001*** \\
\bottomrule
\end{tabular}
\begin{tablenotes}
\small
\item Notes: Standard errors computed using Newey-West HAC estimator with 5 lags.
\item *** p<0.01, ** p<0.05, * p<0.1
\end{tablenotes}
\end{table}
```

### Figures

- Vector format (PDF, EPS) required for publication
- Clear axis labels with units
- Legible font sizes (minimum 10pt in final figure)
- Color-blind friendly palettes
- Caption should be self-contained

---

## Decision Criteria by Journal

| Journal | Min Score | Typical Outcome |
|---------|-----------|-----------------|
| RFS | 95+ | Desk reject <95, R&R >95 |
| JFE | 90+ | Desk reject <85, R&R >90 |
| JoE | 88+ | Desk reject <80, R&R >88 |
| JBF | 85+ | Desk reject <75, R&R >85 |
| JFM | 80+ | Review >75, R&R >80 |
| FRL | 75+ | Review >70, Accept >80 |

*Note: These are approximate thresholds based on review experience.*

---

## Recommended Journal Selection Strategy

### For Hawkes Jump-Diffusion GMM Papers:

1. **First Submission**:
   - If major methodological innovation: JoE or JFE
   - If strong empirical contribution: JBF or RFS
   - If focused on market microstructure: JFM

2. **After Rejection**:
   - JFE → JBF or JoE
   - JBF → JFM or sector-specific journal
   - JoE → JBF or Journal of Business & Economic Statistics

3. **Quick Publication Path**:
   - Submit to FRL for initial finding
   - Develop full paper for JBF/JFM later

---

## Key Differences in Review Process

### JFE/RFS (Top Tier)
- Editor screens heavily (50-70% desk reject)
- 2-3 referees if sent to review
- Multiple rounds common (3-4 rounds normal)
- Co-editor shepherds through process
- 2-4 year publication lag

### JBF/JoE (Second Tier)
- Lower desk reject rate (30-40%)
- 2 referees typical
- 1-2 revision rounds
- 1-2 year publication lag

### JFM/FRL (Third Tier)
- Most papers reviewed (20-30% desk reject)
- 1-2 referees
- Single revision typical
- 6-12 month publication lag

---

## Updated for 2024-2025

- **Replication Requirements**: All journals now require code + data
- **Preregistration**: Encouraged (some journals offer badges)
- **Open Access**: Options available (often required by funders)
- **Reproducibility**: R/Python preferred over Stata/MATLAB
- **Data Availability**: Must describe data access clearly
