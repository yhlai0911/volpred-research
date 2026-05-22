# Academic Review Report — leverage-direction v9

**Reviewer**: Claude Sonnet 4.6 (automated academic review)
**Review date**: 2026-05-23
**Files reviewed**: `main.tex`, `body.tex`, `tables.tex`, `table_nulls.tex`
**Previous version**: v8 (review_history/v8/)
**Output target**: `review_history/v9/academic_review_report.md`

---

## Overall Assessment

**Academic Score: 3.5 / 5★**

The paper presents a well-structured and methodologically rigorous empirical study of GJR-GARCH leverage direction and its implications for volatility-targeting strategies. The v9 revision resolved most v8 MEDIUM deferred items. One critical issue remains: the abstract still states "2017--2026" while body and tables correctly state "2017--2025 (with 2026 reserved for OOS)." This inconsistency directly affects reproducibility and must be fixed before submission. Eight orphan labels (defined but never referenced) also require attention.

---

## Part I — V9 Focus Area Verification

### V9-1. M-2 Sample Period Reconciliation

**Status: PARTIALLY RESOLVED — REMAINING BUG IN ABSTRACT**

| Location | Text | Status |
|---|---|---|
| `main.tex` line 39 (abstract) | "over 2017--**2026**" | ❌ FAIL — still incorrect |
| `body.tex` line 156 | "in-sample period 2017--**2025** (with 2026 reserved for out-of-sample validation)" | ✅ PASS |
| `tables.tex` line 6 caption | "(In-Sample Period: 2017--**2025**)" | ✅ PASS |

**Severity**: SEVERE

**Finding**: The v9 fix was applied to body.tex and tables.tex but the abstract in main.tex was not updated. The abstract currently reads:

> "Using daily data over 2017--2026 for nine assets..."

This contradicts the body's explicit statement that 2026 is reserved for OOS validation. A referee or reader will immediately flag this as a data-handling inconsistency.

**Suggested Fix**: Change `main.tex` line 39 from:
```
Using daily data over 2017--2026 for nine assets
```
to:
```
Using daily data over 2017--2025 (with 2026 reserved for out-of-sample validation) for nine assets
```
or the more concise:
```
Using daily in-sample data over 2017--2025 for nine assets, with 2026 reserved for out-of-sample validation,
```

---

### V9-2. Dagger Footnote Style (tables.tex lines 125, 204)

**Status: FULLY RESOLVED ✅**

- Line 125: `$^{\dagger}$Three pass rates...` — dagger symbol confirmed; no "Errata:" prefix.
- Line 204: `$^{\dagger}$Constituent $\bar{\hat{\gamma}}$...` — dagger symbol confirmed; no "Errata:" prefix.

The dagger footnote format is standard in economics/finance journals (JF, JFE, RFS) for table-level clarifications. Format is appropriate and academically standard. No further action required on this item.

---

### V9-3. γ_HM Abbreviation Expansion

**Status: FULLY RESOLVED ✅**

`body.tex` line 382 reads:
> "The \citet{henriksson1981} Henriksson--Merton (HM) regression..."

The explicit "(HM)" expansion is present at first use. Subsequent uses of γ_{HM} (lines 384, 447–448) are unambiguous. The disambiguation footnote at lines 447–448 comprehensively distinguishes the three γ estimates (γ_{HM}, γ_{TM}, and the GJR-GARCH γ). No forward reference friction remains.

---

### V9-4. Dagger Footnote Content — Academic Appropriateness

**Status: CONFIRMED APPROPRIATE ✅**

The two dagger footnote contents are:

1. **Line 125 (tab:var)**: Reports that three pass rates were updated after "correcting for an off-by-one lag error in the backtest" (57.1%→76.2%, 57.1%→71.4%, 61.9%→66.7%). The use of a dagger footnote to disclose a correction within a table note is nonstandard but not uncommon in working paper versions. For a journal submission, this should ideally be moved to an errata or version note, or the table should simply be presented with the corrected values and the correction disclosed in a "Revision History" footnote on the first page rather than embedded in the table.

**Minor residual concern** (see also Section II, Issue 4): The visible correction history embedded in a table note ("57.1% → 76.2%") may invite referee skepticism about the integrity of the computation pipeline. A cleaner presentation would simply state the current values and note in the acknowledgment or a paper-level footnote that an error was corrected in revision.

2. **Line 204 (tab:gamma)**: Provides a methodological note on the VIX average used in the hybrid strategy. This is standard practice and appropriate.

Overall: Format and purpose of both dagger notes are appropriate for academic publication, with the minor concern noted above for line 125.

---

### V9-5. γ_RA Disambiguation

**Status: SUBSTANTIALLY RESOLVED — MINOR RESIDUAL ✓ (with caveat)**

`body.tex` line 495 and accompanying footnote:
> "CRRA risk aversion parameter γ_RA"
> Footnote: "We use γ_RA to denote the CRRA risk-aversion coefficient to distinguish it from the GJR-GARCH leverage parameter γ used throughout."

The disambiguation from GJR-GARCH γ is present and explicit. ✅

**Minor residual**: The acronym "CRRA" is used without expansion at its first occurrence (line 495). The full term "Constant Relative Risk Aversion (CRRA)" should appear before or at this point. In a finance journal, CRRA is widely known, but per standard abbreviation rules (first use must be expanded), this should be corrected.

**Suggested Fix**: Change `body.tex` line ~495 from:
```
CRRA risk aversion parameter γ_RA
```
to:
```
Constant Relative Risk Aversion (CRRA) risk aversion parameter γ_RA
```

---

## Part II — General Academic Review

### Issue 1: Abstract Sample Period Inconsistency

*(Covered in V9-1 above — repeated here for severity ranking)*

**Severity**: SEVERE (must fix before submission)
**Score impact**: −0.5★

As documented above, the abstract states "2017--2026" while the body and tables state "2017--2025." This is a data description error that will be caught by any careful referee.

---

### Issue 2: Orphan Labels (Defined but Never \ref{}'d)

**Severity**: MEDIUM
**Score impact**: −0.3★

The following labels are defined in body.tex or tables.tex but are never referenced via `\ref{}` or `\eqref{}` anywhere in the paper:

| Label | Defined in | Type | Comment |
|---|---|---|---|
| `eq:fz` | body.tex | Equation | Fissler-Ziegel joint (VaR,ES) scoring function |
| `eq:mdd_utility` | body.tex | Equation | MDD utility equivalence equation |
| `fig:cumulative_returns` | body.tex | Figure | Cumulative returns figure |
| `fig:mdd_comparison` | body.tex | Figure | MDD comparison figure |
| `fig:rolling_gamma` | body.tex | Figure | Rolling gamma estimates figure |
| `fig:vix_garch_ratio` | body.tex | Figure | VIX/GARCH ratio figure |
| `tab:amplify` | tables.tex | Table | Amplification/attenuation taxonomy |
| `tab:hybrid` | tables.tex | Table | Hybrid VT strategy |
| `tab:tail` | tables.tex | Table | Tail risk analysis |

**Why this matters**: Orphan labels suggest either (a) figures/tables/equations exist in the paper but are never explicitly introduced in the text, or (b) there are "Figure N" type implicit references in the body that do not use `\ref{}`. Both create navigation confusion for referees using PDF viewers, and the former (unintroduced float elements) is a structural argument problem.

**Suggested Fix**: For each orphaned label, either:
1. Add a `\ref{<label>}` at the appropriate discussion point in the body text (e.g., "as shown in Figure~\ref{fig:cumulative_returns}"); or
2. Remove the `\label{}` if the figure/table/equation does not need cross-referencing.

Priority order: `fig:cumulative_returns`, `fig:mdd_comparison`, `fig:rolling_gamma` (main result figures should always be cross-referenced explicitly).

---

### Issue 3: CRRA Acronym Unexpanded at First Use

*(Covered in V9-5 above — also appears in general review)*

**Severity**: MINOR-MEDIUM
**Score impact**: −0.1★

"CRRA" at body.tex line ~495 is used without writing "Constant Relative Risk Aversion (CRRA)" first. Standard abbreviation rule: expand at first use.

**Suggested Fix**: As stated in V9-5 above.

---

### Issue 4: tab:var_panel Self-Correction Language

**Severity**: MINOR
**Score impact**: −0.1★

The dagger footnote in `tab:var` (line 125) discloses a correction via visible before/after numbers:
> "Three pass rates were corrected after identifying an off-by-one lag error: 57.1% → 76.2%, 57.1% → 71.4%, and 61.9% → 66.7%."

**Problem**: This format makes the revision history visible in the published table. While honest and commendable, referees may question why the initial incorrect values are mentioned at all in a final submission. The arrows imply earlier incorrect work was submitted, which can raise concerns about the robustness of other computed values.

**Suggested Fix for journal submission**: Remove the "before → after" format. Present only the correct values. Add a paper-level note in Acknowledgments or a cover letter explaining the correction was identified and fixed during revision. If a version note is needed in the table, use neutral language: "Values reflect corrected backtest implementation (see Appendix~X for backtest code)."

---

### Issue 5: BTC Sample Size Discrepancy Not Explicitly Stated

**Severity**: MINOR
**Score impact**: −0.05★

Table tab:desc shows BTC has N=3,285 observations while all other assets have N=2,260. The body implies BTC starts earlier but does not state the BTC start date in a single, clearly visible sentence in the Data section.

**Suggested Fix**: Add one explicit sentence in the data section (Section~\ref{sec:data}):
> "Bitcoin (BTC) data are available from [start date], yielding N=3,285 observations; all other assets begin in [start date], yielding N=2,260 observations. All OOS evaluation windows are aligned to a common end date."

---

### Issue 6: Abstract Uses |γ| > 0.10 While Body Proposes t > 1.65 as Primary Criterion

**Severity**: MINOR
**Score impact**: −0.05★

The abstract states:
> "assets with |γ| > 0.10..."

Section 4.2.2 of the body proposes the leverage direction taxonomy based on t > 1.65 (one-sided significance at 10%) as the primary criterion, with |γ| > 0.10 as a secondary/equivalent approximation.

**Problem**: A referee reading only the abstract will understand the classification as magnitude-based, whereas the body makes it significance-based. This is a framing inconsistency, not a numerical inconsistency.

**Suggested Fix**: Align abstract language to the primary criterion:
> "assets with statistically significant leverage effects (t > 1.65, |γ| > 0.10)..."

or simply use the body's primary framing:
> "assets where the GJR-GARCH leverage parameter is statistically significant..."

---

### Issue 7: tab:vt Heterogeneous Evaluation Windows

**Severity**: MEDIUM
**Score impact**: −0.2★

Table tab:vt reports Sharpe ratios for the VT strategy across assets with different evaluation periods:
- GLD: 2022–2026 (post-COVID window only)
- SPY: 2014–2026 (full history)
- TLT/EEM: ~2015–2026
- BTC: post-2019

The table acknowledges this heterogeneity in a footnote, but Sharpe ratios calculated over different time horizons (especially when one window captures a bull market run-up and another captures a crisis period) are not directly comparable.

**Why this matters**: A referee in a methods paper will note that cross-asset Sharpe comparisons are invalid when the evaluation windows differ by 7+ years. The "BTC Sharpe = 1.8" vs "GLD Sharpe = 0.4" comparison may be driven entirely by the window rather than the strategy quality differential.

**Suggested Fix**: Add a robustness check using a common evaluation window for the subset of assets where data overlap permits (e.g., 2019–2025 for all nine assets). Report both the full-history and the common-window results. This turns a methodological limitation into a robustness result.

---

### Issue 8: Section Labels Never Pointed To

**Severity**: MINOR
**Score impact**: −0.05★

Several section labels are defined but never cross-referenced:

| Label | Section name |
|---|---|
| `sec:calendar` | Calendar / time-zone appendix |
| `sec:cross_asset_vt` | Cross-asset VT section |
| `sec:ewma_vt` | EWMA-based VT robustness |
| `sec:model_spec_robustness` | Model specification robustness |

For appendix sections this is acceptable (appendix sections are often self-contained). For `sec:cross_asset_vt` and `sec:model_spec_robustness` in the main body, at least one forward reference should exist in the introduction or earlier body sections (e.g., "robustness checks are reported in Section~\ref{sec:model_spec_robustness}").

---

### Issue 9: Missing \eqref{eq:fz} Cross-Reference

**Severity**: MINOR
**Score impact**: −0.05★

The Fissler-Ziegel joint (VaR, ES) scoring function is introduced as eq:fz with a full equation display, but is never explicitly cited in the text via `\eqref{eq:fz}`. The body discusses FZ scoring properties but does not point the reader back to the equation number.

**Suggested Fix**: At the point where FZ scores are discussed/reported, add "using the scoring function in Equation~\eqref{eq:fz}."

---

### Issue 10: Harvey et al. (2016) t > 3.0 Threshold Application Scope

**Severity**: MINOR (flagging for referee awareness)
**Score impact**: −0.05★

The paper correctly applies Harvey et al.'s (2016) t > 3.0 threshold for multiple testing in the strategy context. However, the paper contains 9 assets × multiple model specs × multiple tests, and the t > 3.0 threshold was designed for factor discovery across a large cross-section of proposed factors, not for model comparison within a single research design.

This is not a fatal flaw, but a referee from the empirical asset pricing tradition may challenge whether t > 3.0 is the right benchmark here, or whether a Bonferroni/Holm correction applied to the specific set of tests in this paper would be more appropriate.

**Suggested Fix**: Add a sentence clarifying the scope of application: "Following Harvey et al. (2016), we apply a threshold of t > 3.0 as a conservative benchmark to guard against data-snooping across the nine assets in our cross-section."

---

## Part III — Scorecard Summary

| # | Issue | Severity | Score Impact | Fix Effort |
|---|---|---|---|---|
| V9-1 / II-1 | Abstract "2017--2026" vs body/tables "2017--2025" | **SEVERE** | −0.5★ | 1 line change |
| II-2 | 9 orphan labels (fig/eq/tab never \ref{}'d) | MEDIUM | −0.3★ | Add \ref calls or remove labels |
| II-7 | tab:vt heterogeneous evaluation windows | MEDIUM | −0.2★ | Add common-window robustness |
| V9-5 / II-3 | CRRA unexpanded at first use | MINOR-MEDIUM | −0.1★ | Expand acronym once |
| II-4 | tab:var_panel self-correction "→" language | MINOR | −0.1★ | Reframe footnote for submission |
| II-5 | BTC N=3285 vs N=2260 not stated explicitly | MINOR | −0.05★ | Add one sentence in data section |
| II-6 | Abstract |γ|>0.10 vs body t>1.65 framing | MINOR | −0.05★ | Align abstract to body framing |
| II-8 | Section labels never cross-referenced | MINOR | −0.05★ | Add forward refs in intro |
| II-9 | eq:fz never \eqref{}'d | MINOR | −0.05★ | Add \eqref at discussion point |
| II-10 | Harvey t>3.0 scope not qualified | MINOR | −0.05★ | Add scope qualifier sentence |

**Resolved in v9** (no further action):
- ✅ Dagger footnote style (V9-2)
- ✅ γ_HM expansion (V9-3)
- ✅ Dagger content appropriate (V9-4)
- ✅ γ_RA disambiguation footnote present (V9-5 core)
- ✅ body.tex sample period "2017--2025" (V9-1 partial)
- ✅ tables.tex caption "(In-Sample Period: 2017--2025)" (V9-1 partial)

---

## Part IV — Pre-Submission Priority Order

### Must Fix Before Submission

1. **[5 minutes]** `main.tex` abstract: Change "2017--2026" → "2017--2025 (with 2026 reserved for OOS validation)"
2. **[20 minutes]** Expand "CRRA" to "Constant Relative Risk Aversion (CRRA)" at first use in body.tex
3. **[30 minutes]** Add `\ref{}` or `\eqref{}` for the 9 orphan labels, or explicitly remove labels from floats/equations that are referenced only implicitly
4. **[15 minutes]** Align abstract leverage classification language to body's primary criterion (t > 1.65 significance)

### Strongly Recommended

5. **[2 hours]** Add common-window robustness panel to tab:vt (common period 2019–2025 across all 9 assets)
6. **[10 minutes]** Reframe tab:var dagger footnote to remove "before → after" correction history; present clean values only

### Optional / Minor Polish

7. Explicitly state BTC start date and N discrepancy in data section (1 sentence)
8. Add scope qualifier for Harvey t > 3.0 application
9. Add forward references to `sec:model_spec_robustness` and `sec:cross_asset_vt` from introduction or results overview

---

## Part V — Citation and Bibliography Check

*(Quick spot-check — full citation verification requires citation-verifier skill)*

**Observed**: Bibliography contains ~36 entries. Key methodological citations spot-checked:

| Citation | Expected | Found | Status |
|---|---|---|---|
| Patton (2011) | JBES proxy-robustness | `patton2011` | ✅ |
| Diebold & Mariano (1995) | DM test | `dieboldmariano1995` | ✅ |
| Hansen et al. (2011) | MCS | `hansen2011` | ✅ |
| Moreira & Muir (2017) | VT strategy | `moreira2017` | ✅ |
| Harvey et al. (2016) | Multiple testing | `harvey2016` | ✅ |
| Fissler & Ziegel (2016) | Joint VaR+ES scoring | `fissler2016` | ✅ |
| Henriksson & Merton (1981) | HM timing test | `henriksson1981` | ✅ |
| Glosten, Jagannathan & Runkle (1993) | GJR-GARCH | `glosten1993` | ✅ |

No missing core citations identified in spot-check. Full citation audit (author lists, years, journal names, DOIs) should be run via `citation-verifier` skill before submission.

---

## Appendix — Cross-Reference Audit Detail

### Labels defined in body.tex (complete list from grep)

```
eq:fz, eq:mdd_utility, eq:qlike,
fig:cumulative_returns, fig:gamma_mechanism, fig:mdd_comparison,
fig:rolling_gamma, fig:vix_garch_ratio, fig:vix_weight,
sec:calendar, sec:conclusion, sec:cross_asset_vt, sec:data_methodology,
sec:data, sec:empirical_results, sec:ewma_vt, sec:gamma-mechanism,
sec:garch_comparison, sec:har_paradox, sec:implications, sec:ivt,
sec:leverage_direction, sec:literature, sec:model_spec_robustness,
sec:qlike_ceiling, sec:robustness_checks, sec:timing_tests,
sec:tz_arbitrage, sec:var_compliance, sec:vt_alpha_nature,
sec:vt_insurance, sec:vt_methodology, sec:vt_results,
tab:complexity_ceiling, tab:tz_arbitrage
```

### Labels defined in tables.tex (complete list)

```
tab:desc, tab:gamma, tab:qlike, tab:var, tab:var_ortho,
tab:var_panel, tab:vt, tab:window, tab:hybrid, tab:amplify, tab:tail,
tab:gamma-mechanism
```

### Labels defined in table_nulls.tex

```
tab:nulls
```

### Orphan labels (confirmed never \ref{}'d in body.tex via grep)

`eq:fz`, `eq:mdd_utility`, `fig:cumulative_returns`, `fig:mdd_comparison`, `fig:rolling_gamma`, `fig:vix_garch_ratio`, `tab:amplify`, `tab:hybrid`, `tab:tail`

Note: `tab:var_ortho`, `tab:var_panel`, `tab:nulls`, `tab:window`, `tab:gamma-mechanism`, `fig:gamma_mechanism`, `fig:vix_weight` were also checked; their reference status should be verified manually as grep may miss aliases.

---

*Report generated: 2026-05-23 | Review version: v9 | Next recommended action: fix abstract line, then recompile and run citation-verifier*
