# Citation Check Report — EAV Universal Magnitude
**Reviewer**: citation-verifier (main thread, Claude Sonnet 4.6)
**Date**: 2026-05-18
**Paper**: Earnings-Announcement Volatility Amplification: A Cross-Market Regularity
**References.bib status**: MISSING — all citations are inline fallback comments in body.tex

---

## Status: PENDING — references.bib does not exist

`paper/eav-universal-magnitude/references.bib` does not exist. Full formal citation verification requires the .bib file. This report audits the inline fallback citations listed at the end of body.tex (lines 921–964) and the citation keys used in the main text, cross-referenced against known publication metadata.

---

## 1. Citation Keys Used in body.tex

| Key | Usage | Inline Comment Present | Verification Status |
|-----|-------|----------------------|---------------------|
| `beaver1968` | §1, §6.1 | Yes | See §2 below |
| `patell1976` | §1, §2.2, multiple | Yes | See §2 below |
| `patell_wolfson1979` | §1, §6.1 | Yes | **JOURNAL AMBIGUITY** — see §3 |
| `ball_kothari1991` | §1 | Yes | See §2 below |
| `engel_rangel2008` | §1, §2, multiple | Yes | **TYPO IN KEY** — should be `engle_rangel2008` |
| `engle2013` | §1, §2, multiple | Yes | **JOURNAL ERROR** — see §3 |
| `garch_x_vix_paper` | §2 footnote | No entry | **PLACEHOLDER** — unresolved |
| `glosten1993` | §2 footnote | Yes | See §2 below |
| `harvey2016` | §1, §2, §5, §7, §9 | Yes | See §2 below |
| `k1213_convergence_lesson` | §2.3 footnote | No entry | **INVALID** — internal experiment ID |
| `diebold1995` | Not cited | No entry | **MISSING** — DM test not formally cited |

---

## 2. Individual Citation Verifications

### 2.1 `beaver1968`
**Inline comment**: "Beaver, W. H. (1968). The information content of annual earnings announcements. Journal of Accounting Research, 6(Supplement), 67--92."

- **Author**: William H. Beaver — CORRECT
- **Year**: 1968 — CORRECT
- **Title**: "The Information Content of Annual Earnings Announcements" — CORRECT (capitalization varies)
- **Journal**: Journal of Accounting Research — CORRECT
- **Volume/Issue**: 6(Supplement), pp. 67–92 — CORRECT
- **Status**: LOW RISK ✓ (canonical citation, well-documented)

### 2.2 `patell1976`
**Inline comment**: "Patell, J. M. (1976). Corporate forecasts of earnings per share and stock price behavior: Empirical test. Journal of Accounting Research, 14(2), 246--276."

- **Author**: James M. Patell — CORRECT
- **Year**: 1976 — CORRECT
- **Title**: "Corporate Forecasts of Earnings Per Share and Stock Price Behavior: Empirical Tests" — NOTE: inline has "Empirical test" (singular); actual title is "Empirical Tests" (plural) — minor
- **Journal**: Journal of Accounting Research — CORRECT
- **Volume**: 14(2), pp. 246–276 — CORRECT
- **Status**: LOW RISK ✓ (note minor title capitalization/plural discrepancy)

### 2.3 `ball_kothari1991`
**Inline comment**: "Ball, R., & Kothari, S. P. (1991). Security returns around earnings announcements. The Accounting Review, 66(4), 718--738."

- **Author**: Ray Ball and S.P. Kothari — CORRECT
- **Year**: 1991 — CORRECT
- **Title**: "Security Returns Around Earnings Announcements" — CORRECT
- **Journal**: The Accounting Review — CORRECT
- **Volume**: 66(4), pp. 718–738 — CORRECT
- **Status**: LOW RISK ✓

### 2.4 `engle_rangel2008` (key in body.tex: `engel_rangel2008` — TYPO)
**Inline comment**: "Engle, R. F., & Rangel, J. G. (2008). The Spline-GARCH model for low-frequency volatility and its global macroeconomic causes. Review of Financial Studies, 21(3), 1187--1222."

- **Key typo**: Body uses `\citet{engel_rangel2008}` (engel, missing 'e'). Correct key should be `engle_rangel2008`.
- **Author**: Robert F. Engle and Jose G. Rangel — CORRECT (note Engle, not Engel)
- **Year**: 2008 — CORRECT
- **Title**: "The Spline-GARCH Model for Low-Frequency Volatility and Its Global Macroeconomic Causes" — CORRECT
- **Journal**: Review of Financial Studies — CORRECT
- **Volume**: 21(3), pp. 1187–1222 — CORRECT
- **Status**: MEDIUM RISK — typo in citation key (`engel` vs `engle`) will compile as undefined key if .bib uses correct spelling

### 2.5 `engle2013` (Engle, Ghysels, Sohn 2013)
**Inline comment**: "Engle, R. F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. Review of Economics and Statistics, 95(3), 776--797."

- **JOURNAL ERROR**: The inline comment states Review of Economics and Statistics (ReStat). However, this paper is commonly confused with another Engle paper. Independent verification: Engle, R.F., Ghysels, E., & Sohn, B. (2013) "Stock Market Volatility and Macroeconomic Fundamentals" — **confirmed as Review of Economics and Statistics 95(3):776–797**. CORRECT.
- **Status**: LOW RISK ✓ (previously flagged as potential JBES confusion; ReStat is correct)
- **Note**: The key `engle2013` will create ambiguity in bibliographies that already have other Engle 2013 papers. Prefer `engle_ghysels_sohn2013` as key.

### 2.6 `glosten1993`
**Inline comment**: "Glosten, L. R., Jagannathan, R., & Runkle, D. E. (1993). On the relation between the expected value and the variance of the nominal excess return on stocks. Journal of Finance, 48(5), 1779--1801."

- **Authors**: Glosten, Jagannathan, Runkle — CORRECT
- **Year**: 1993 — CORRECT
- **Title**: CORRECT
- **Journal**: Journal of Finance, 48(5), 1779–1801 — CORRECT
- **Status**: LOW RISK ✓

### 2.7 `harvey2016`
**Inline comment**: "Harvey, C. R., Liu, Y., & Zhu, H. (2016). ...and the cross-section of expected returns. Review of Financial Studies, 29(1), 5--68."

- **Authors**: Campbell R. Harvey, Yan Liu, Heqing Zhu — CORRECT
- **Year**: 2016 — CORRECT
- **Title**: "...and the Cross-Section of Expected Returns" — CORRECT (including the unusual leading "...")
- **Journal**: Review of Financial Studies, 29(1), pp. 5–68 — CORRECT
- **Status**: LOW RISK ✓

---

## 3. High-Risk Citations

### 3.1 `patell_wolfson1979` — JOURNAL AMBIGUITY (MAJOR)

**Inline comment**: "Patell, J. M., & Wolfson, M. A. (1979). Anticipated information releases reflected in call option prices. Journal of Financial Economics, 7(2), 117--140. [NOTE: verify JFE vs JFQA -- see lit\_review.md F.]"

The inline comment itself flags this journal uncertainty. Independent search:
- Patell, J.M. and Wolfson, M.A. (1979) "Anticipated information releases reflected in call option prices" is published in **Journal of Financial Economics, 7(2), 117–140** — JFE, NOT JFQA.
- **Status**: MEDIUM RISK — journal appears correct (JFE), but the in-text `[NOTE: verify JFE vs JFQA]` must be resolved and removed before submission. Current inline annotation leaks into compiled PDF comment risk if using packages like `\todo{}`.

### 3.2 `garch_x_vix_paper` — PLACEHOLDER KEY (MAJOR)

**Inline comment**: None — no fallback entry exists.

This key appears in §2.1 footnote: "is standard in the GARCH-X literature \citep{garch_x_vix_paper}."

The GARCH-X VIX literature anchor is likely one of:
- Engle, R.F. (2002) "Dynamic Conditional Correlation" (JBES)
- Giot, P. (2005) "Relationships between implied volatility indexes and stock index returns" (JDM)
- Engle, R.F. and Rangel (2008) — already cited
- Or the project's own paper `paper/garch-x-vix/` if this is a self-citation

**Status**: MAJOR — unresolved placeholder that will cause compile failure

### 3.3 `k1213_convergence_lesson` — INVALID ACADEMIC REFERENCE (MAJOR)

This key appears as `\citet{k1213_convergence_lesson}` in §2.3 footnote: "Per \citet{k1213_convergence_lesson}, library-level convergence flags are sensitive to scale..."

This is an internal experiment working note, not a published or citable academic reference. Using it as `\citet{}` in the main body text violates academic citation standards. Options:
1. Remove the `\citet{}` and simply state the explanation inline without citation
2. Add a footnote: "This observation is consistent with known limitations of L-BFGS-B gradient tolerance in low-magnitude parameter spaces; see also [proper citation if available]."

**Status**: MAJOR — academic citation violation

---

## 4. Missing Citations (Not in body.tex but methodologically required)

| Missing Citation | Why Needed | Priority |
|-----------------|-----------|----------|
| Diebold & Mariano (1995) | OOS DM test used in K1148_d2, K1149 — not cited anywhere in body | **HIGH** |
| Harvey, Leybourne & Newbold (1997) | HLN correction for DM finite-sample — K1148_d2 uses `panel_dm_hln` field | **HIGH** |
| Bollerslev (1986) | GARCH foundation — GJR-GARCH(1,1) in §2 references Glosten1993 but not original GARCH | **MEDIUM** |
| Benjamini & Hochberg (1995) | BH-FDR procedure used in §4, §5, §6 — uncited | **MEDIUM** |
| Relevant cross-market EAV paper | Third contribution strand in §1.3 explicitly needs this [CITATION NEEDED] | **CRITICAL** |

### 4.1 Diebold & Mariano (1995)
"Comparing Predictive Accuracy." Journal of Business & Economic Statistics, 13(3), 253–263.
- The OOS DM test is a core inferential tool for K1148_d2 and K1149
- NOT cited anywhere in body.tex
- **Status**: MAJOR omission

### 4.2 Harvey, Leybourne & Newbold (1997)
"Testing the Equality of Prediction Mean Squared Errors." International Journal of Forecasting, 13(2), 281–291.
- K1148_d2 explicitly labels results `oos_dm_hln` (Harvey-Leybourne-Newbold corrected)
- Body does not cite HLN
- **Status**: MAJOR omission (method used but uncited)

### 4.3 Benjamini & Hochberg (1995)
"Controlling the False Discovery Rate: A Practical and Powerful Approach to Multiple Testing." Journal of the Royal Statistical Society B, 57(1), 289–300.
- BH-FDR procedure explicitly mentioned in §4, §5, §6, §7
- Currently uncited in body.tex
- **Status**: MEDIUM omission

---

## 5. Engle-Rangel 2008 Model Description Accuracy

**Body §1**: "our multiplicative GARCH framework adapted from \citet{engel_rangel2008} and \citet{engle2013}"

Engle-Rangel (2008) is the Spline-GARCH paper — it uses a spline for the long-run variance component, not event-date binary indicators. The body correctly notes in §2.1 that "we adapt this framework by replacing the macroeconomic long-run driver with an event-date covariate." This adaptation is legitimate but should be explicit that the EAV specification is the authors' innovation, not directly from either paper. The current text does this adequately.

However, Engle-Ghysels-Sohn (2013) is the GARCH-MIDAS paper (Mixed Data Sampling), which uses mixed-frequency data. The present paper does not use MIDAS. The citation to `engle2013` as a specification ancestor is methodologically imprecise — the multiplicative decomposition $\sigma^2 = g \cdot \tau$ is closer to Engle-Rangel (2008) than to GARCH-MIDAS. Consider narrowing the citation or adding a footnote distinguishing the specification lineage.

---

## 6. Summary of Citation Issues

| Severity | Count | Issues |
|----------|-------|--------|
| CRITICAL | 1 | `[CITATION NEEDED]` cross-market EAV anchor in §1.3 |
| MAJOR | 4 | `garch_x_vix_paper` unresolved; `k1213_convergence_lesson` invalid; Diebold-Mariano uncited; HLN uncited |
| MEDIUM | 3 | `engel_rangel2008` key typo; BH-FDR uncited; GARCH-MIDAS citation imprecision |
| MINOR | 3 | Patell 1976 title plural; `patell_wolfson1979` journal note must be removed; `engle2013` key ambiguity |

**Total distinct citation issues**: 11

**references.bib**: Does not exist. Must be created before compilation or submission.

---

## 7. Inline Comment Cleanup Required

Lines 921–964 contain inline `\bibitem`-style comments that are commented out. These are useful working notes but must be replaced by a proper `references.bib`. The inline comments do not compile and are not a substitute for the .bib file.
