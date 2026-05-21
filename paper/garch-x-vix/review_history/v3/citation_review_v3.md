# Citation Verification Report — Paper 9 (garch-x-vix) v3

**Manuscript**: `paper/garch-x-vix/main.tex`
**Date**: 2026-05-19
**Reviewer**: Claude (citation-verifier skill)
**Scope**: Full re-audit of all bib entries + content-fidelity check, incorporating v1 fixes and new claims added during revision

---

## Summary

| Metric | Count |
|--------|-------|
| Unique references in `thebibliography` | 27 |
| Unique `\cite*` keys used in body | 27 |
| Orphan bib entries (not cited) | 0 |
| Orphan in-text cites (no bib) | 0 |
| **MAJOR issues (new, v3)** | **0** |
| **MEDIUM issues (residual from v1 + new)** | **2** |
| **LOW/MINOR issues** | **3** |
| OK references (fully verified, v1 fixes applied) | 25 / 27 |

**Verdict**: v1 MAJOR-1 (`conrad2015` wrong journal) was fixed in a prior commit (2026-04-18). All 10 v1 checklist items are closed per `review_history/v1/citation_check_report.md`. No new MAJOR errors introduced. Two MEDIUM issues remain: (1) `diebold2002` cites the 2002 JBES reprint but the original 1995 paper is more commonly cited — acceptable as-is but flag for journal style guide compliance; (2) `harvey2016` is applied in a non-standard context (time-series forecasting, not cross-sectional factor research).

---

## Status of v1 Issues

All v1 issues confirmed resolved in current `main.tex`:

| v1 Issue | Status | Verification |
|----------|--------|-------------|
| MAJOR-1: `conrad2015` JAE 30(7) + DOI | **FIXED** | Line 936-939: JAE, 30(7):1090-1114, DOI 10.1002/jae.2404 |
| MED-1: `bollerslev1986` DOI | **FIXED** | Line 892: DOI 10.1016/0304-4076(86)90063-1 |
| MED-2: `engle1982` DOI | **FIXED** | Line 902-903: DOI 10.2307/1912773 |
| MED-3: `glosten1993` DOI | **FIXED** | Line 973: DOI 10.1111/j.1540-6261.1993.tb05128.x |
| MED-4: `han2014` DOI | **FIXED** | Line 979: DOI 10.1080/07350015.2014.897954 |
| MED-5: `francq2019` DOI | **FIXED** | Line 947: DOI 10.1017/S0266466617000512 |
| MINOR-1: `conrad2020` DOI | **FIXED** | Line 934: DOI 10.1002/jae.2742 |
| MINOR-2: JBES ampersand | **FIXED** | Lines 897, 957, 979: `\&` used |
| MINOR-3: `acerbi2014` URL | **FIXED** | Line 880: URL added |
| MINOR-4: `kupiec1995` DOI | **FIXED** | Line 1005: DOI 10.3905/jod.1995.407942 |

---

## New v3 MEDIUM Issues

### MEDIUM-V3-1. `harvey2016` citation context mismatch

**Location**: Lines 79, 297, 420, 748, 766 (multiple uses throughout)

**Issue**: Harvey, Liu, & Zhu (2016) "... and the Cross-Section of Expected Returns" (RFS 29(1):5-68) is a paper about multiple-testing in the **cross-sectional asset pricing factor literature**. The paper proposes a t-statistic threshold of |t| > 3.0 for claiming discovery of new cross-sectional return factors.

The present manuscript applies this threshold to **time-series volatility forecast comparison** (Diebold-Mariano tests). This is a conceptually non-standard application — Harvey et al. (2016) does not specifically discuss time-series forecast horse races. The DM framework has its own literature on multiple-testing adjustments (e.g., White's (2000) Reality Check, Romano & Wolf (2005) StepM, Hansen (2005) SPA).

The current paper (line 297) notes: "consistent with the multiple-testing concerns raised by Harvey et al. (2016)" and computes Bonferroni-adjusted critical values. This is a defensible use, but referees at JEF/JoF may question whether Harvey et al. (2016) is the appropriate citation for this practice in a time-series forecasting context.

**Fix**: Add a citation to a directly applicable time-series multiple-testing reference (e.g., White (2000) "A Reality Check for Data Snooping," *Econometrica*, 68(5):1097-1126) alongside Harvey et al. (2016). The sentence at line 297 could read: "We adopt the conservative threshold |t| > 3.0, consistent with Bonferroni adjustment and the broader multiple-testing concerns raised in the cross-sectional literature [Harvey et al. 2016] and time-series forecast comparison literature [White 2000]."

**Additional reference needed**:
```latex
\bibitem[White, 2000]{white2000}
White, H. (2000).
\newblock A reality check for data snooping.
\newblock {\em Econometrica}, 68(5):1097--1126.
\newblock \url{https://doi.org/10.1111/1468-0262.00152}
```

---

### MEDIUM-V3-2. `diebold2002` — 1995 original vs 2002 reprint citation

**Location**: Line 897-898

**Issue**: The paper cites Diebold & Mariano (2002) using the JBES 20th-anniversary reprint. The original paper was published in 1995:

> Diebold, F.X. and Mariano, R.S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3):253-263.

The 2002 version (JBES 20(1):134-144) is a republication with a discussant response. Some journals and style guides require citing the original 1995 paper; others accept the 2002 reprint. The v1 report correctly noted this is acceptable, but the key difference is:

- Vol. 13(3), pp. 253-263 = 1995 original
- Vol. 20(1), pp. 134-144 = 2002 reprint

**Recommendation**: Check the target journal's style guide. If citing the methodology, 1995 is more standard. If the 2002 version is used, confirm the JBES volume/pages are correct (20(1):134-144 corresponds to the 2002 reprint, which the current bib entry shows). The current bib entry is self-consistent; this is low-severity. Flag for author's preference.

---

## Low Issues

### LOW-V3-1. `bollerslev2009` — author ordering note

**Location**: Line 905-909

**Issue**: The bib entry reads `Bollerslev, T., Tauchen, G., and Zhou, H. (2009)`. In-text at line 113: "since Bollerslev (2009) showed that VRP predicts aggregate stock returns." The `\citet{bollerslev2009}` command with natbib will render as "Bollerslev et al. (2009)" — which is correct. However, at line 505: "consistent with the low daily VRP autocorrelation (ρ ≈ 0.20) and the well-known difficulty of predicting variance risk premia at short horizons (Bollerslev et al. 2009)" — this is also correct. No error, but note the implied precision: the actual paper's key prediction-horizon finding is at monthly horizons (not daily), so invoking it as justification for "difficulty of predicting VRP at short horizons" slightly overstates the source's scope.

**Fix**: Minor content note — add "at monthly and longer horizons" to the in-text claim, or replace with a reference more specifically about daily VRP unpredictability (e.g., Carr & Wu 2009 is already cited and discusses VRP dynamics).

---

### LOW-V3-2. `giacomini2006` — Giacomini & White attribution

**Location**: Lines 949-951, 762

**Issue**: The bib entry reads "Giacomini, R. and White, H. (2006)" and the in-text cite "The Giacomini and White (2006) conditional predictive ability test" is correct. However, the paper reports χ² = 16.28, p < 0.001 and χ² = 3.77, p = 0.152 without specifying the test window length (the GW test requires a forecast window W, which determines degrees of freedom). The result is plausible but not fully described for replication.

**Fix**: Technical note for the results section (Section 5.5) — add the estimation window W = 2,000 as the relevant parameter for the GW test statistic interpretation.

---

### LOW-V3-3. `acerbi2014` — Risk magazine, Z1/Z2 test identification

**Location**: Lines 876-880

**Issue**: The Acerbi & Szekely (2014) tests are sometimes referenced by their 2014 Risk paper and sometimes by a longer working paper / subsequent peer-reviewed publication. A follow-up publication appeared as:

> Acerbi, C. and Szekely, B. (2019). "Backtesting Expected Shortfall: Accounting for tail risk." *Management Science*, 65(12):5542-5567.

The 2019 Management Science version is the peer-reviewed publication; the 2014 Risk piece is an industry magazine article. For top-tier academic journals, the 2019 MS publication is more citable.

**Fix**: Consider replacing or supplementing the `acerbi2014` entry with the 2019 Management Science publication:
```latex
\bibitem[Acerbi and Szekely, 2019]{acerbi2019}
Acerbi, C. and Szekely, B. (2019).
\newblock Backtesting expected shortfall: Accounting for tail risk.
\newblock {\em Management Science}, 65(12):5542--5567.
\newblock \url{https://doi.org/10.1287/mnsc.2018.3159}
```

---

## Content-Fidelity Spot Checks (v3 additions)

The following new content-fidelity checks cover material added or emphasized after v1:

| In-text claim | Cite | v3 Assessment |
|---|---|---|
| "Harvey threshold |t| > 3.0 … for multiple-testing concerns" | `harvey2016` | Acceptable but context mismatch (cross-section vs time-series). See MEDIUM-V3-1. |
| "OOS R² … following Campbell & Thompson (2008)" | `campbell2008` | ✓ Campbell & Thompson (2008) defines out-of-sample R² exactly as used in this paper. Correct citation. |
| "Giacomini & White (2006) conditional predictive ability test" | `giacomini2006` | ✓ Correct attribution. Missing window W parameter (LOW-V3-2). |
| "Bekaert & Hoerova (2014) decomposed VIX² into expected variance and VRP" | `bekaert2014` | ✓ Central result of that paper. |
| "VRP proxy following Bollerslev et al. (2009): VRP_t = VIX²_{t-1}/252 - r_t²" | `bollerslev2009` | ✓ This proxy definition is consistent with that paper's framework, though Bollerslev et al. use realized variance (not r_t²) for VRP. The substitution of r_t² for realized variance is standard in daily data and acknowledged by the existing footnote. |
| "Engle & Rangel (2008) introduced Spline-GARCH" | `engle2008` | ✓ RFS 21(3):1187-1222. Correct. |
| "Conrad & Kleen (2020) combining RV and macro variables outperforms single-variable" | `conrad2020` | ✓ JAE 35(1):19-45. Correct. |
| "Francq & Thieu (2019) extended GARCH-X to possibly nonstationary covariates" | `francq2019` | ✓ Econometric Theory 35(1):37-72. Correct attribution. |
| "Lai (2026) split-adjustment procedure for 0050.TW" | `lai2026vt` | Self-citation, working paper. Acceptable; verify the cited split procedure is actually documented in that working paper before submission. |

No fabricated references, no reversed conclusions, no misattributed findings detected in v3 review.

---

## Action Checklist (v3)

- [ ] **MEDIUM-V3-1**: Add `white2000` to bibliography; update line 297 citation to include White (2000) alongside Harvey et al. (2016)
- [ ] **MEDIUM-V3-2**: Decide 1995 vs 2002 Diebold-Mariano citation based on target journal style guide
- [ ] **LOW-V3-1**: Refine "daily VRP unpredictability" claim to "monthly-and-longer" or cite more specific daily-horizon source
- [ ] **LOW-V3-2**: Add "estimation window W = 2,000" to GW test report in Section 5.5
- [ ] **LOW-V3-3**: Consider replacing `acerbi2014` (trade magazine) with `acerbi2019` (Management Science peer-reviewed)

---

## Overall Citation Status

- **0 MAJOR** issues (v1 MAJOR fixed)
- **2 MEDIUM** issues (context mismatch for Harvey 2016; DM 1995 vs 2002 preference)
- **3 LOW** issues (Bollerslev scope, GW window, Acerbi peer-reviewed upgrade)
- **Content claims**: All spot-checked attributions accurately represent original sources. No fabrication or misattribution detected.

**Verdict**: Citations are in acceptable condition for submission. The MEDIUM-V3-1 (Harvey 2016 context) should be addressed before top-tier submission as it exposes the paper to methodological criticism on its multiple-testing framework.
