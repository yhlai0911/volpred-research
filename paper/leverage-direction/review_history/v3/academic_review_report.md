# Academic Review — leverage-direction (main.tex / body.tex — v3 errata)

- **Date**: 2026-05-21
- **Reviewer**: Claude (latex-academic-reviewer proxy)
- **Files reviewed**: main.tex, body.tex (the file actually imported by main.tex), body_v3.tex (reference), tables.tex, table_nulls.tex
- **Paper**: "Leverage Direction Matters: Cross-Asset Evidence on GARCH Model Selection and Volatility Targeting"
- **Version**: main.tex dated "April 2026 (v3 errata)"
- **Target journal**: Journal of Banking and Finance (JBF)

---

## Critical Finding: body.tex vs body_v3.tex Mismatch

**This is the most important finding of this review cycle.** `main.tex` imports `body.tex` (line 53: `\input{body}`), NOT `body_v3.tex`. A diff between the two files reveals that v3's fixes for HIGH issues #1 and #2 are present in `body_v3.tex` but are **NOT present in `body.tex`**. Specifically:

- **body.tex line 12**: still reports `t = -4.71` (old t-stat for regime difference)
- **body.tex line 168**: footnote still references `t=-4.71`
- **body.tex line 208**: still contains the raw v2 text with the internal contradiction (+0.20 vs +0.048) and no explanatory footnote

The v3 revision was applied to `body_v3.tex` but the compiled paper (`main.tex + body.tex`) retains the v2 contradictions. As submitted to reviewers, the paper would still carry both HIGH-1 and HIGH-2 unresolved.

---

## Summary

- **Overall rating**: 3.5/5 stars (★★★½) — substantive improvements in v3 on issues 3–7, but the two CRITICAL numerical contradictions persist in the compiled paper (body.tex), and the abstract still lacks the explicit "(in-sample)" qualifier on the 9/9 claim.
- **Main strengths preserved from v2**: taxonomy clarity, robustness work, VaR orthogonality framing, honest OOS caveats.
- **v3 additions (confirmed in body.tex)**: Empirical Regularity 1 rename, ES/Fissler-Ziegel subsection, significance-based BTC allocation rule, engleGhyselsSohn2013 and pattonSheppard2015 citations, footnote explaining three distinct HM gamma specifications (in body.tex line 448).
- **Remaining blocking issues**: 2 CRITICAL (body.tex not updated with v3 fixes), 1 SEVERE (abstract 9/9 missing in-sample qualifier), plus inherited MED issues from v2.

---

## Detail: v2 HIGH Issues — Closure Assessment

### Issue #1: Regime-Gamma Contradiction (+0.20 vs +0.048)

**Location in compiled paper**: body.tex line 208

**v2 text (still present in body.tex)**:
> "During the 2013–2015 gold bear market, gamma turns sharply positive (mean γ = +0.20)... A two-sample t-test confirms: bull market γ = −0.043 versus bear market γ = +0.048 (t = −4.71, p < 0.0001)."

**Status**: OPEN — CRITICAL. The contradictory same-sentence juxtaposition of +0.20 and +0.048 is unchanged in body.tex, which is what main.tex compiles. The fix exists in body_v3.tex (adds a clarifying footnote explaining the two numbers are different statistical objects: a sub-period rolling window mean vs. a full-sample binary partition estimate, and updates t=-4.71 to t=-3.79 with p<0.001) but this fix was never ported to body.tex.

**JBF Referee Impact**: A referee will still seize on this. The v2 reviewer called this "CRITICAL-HIGH" — it remains unresolved as compiled.

**Additional inconsistency found**: body.tex line 12 reports the regime t-statistic as `t = -4.71, p < 0.0001`, and line 168's footnote also says `t=-4.71`. body_v3.tex updated both to `t=-3.79, p<0.001`. The compiled paper thus has an internal inconsistency between:
- body.tex line 12: t=-4.71
- body.tex line 208: t=-4.71
and these differ from body_v3.tex's corrected value of t=-3.79. The t-statistic itself appears to have changed between v2 and v3 (a recomputed value), but the old value persists in body.tex.

---

### Issue #2: Henriksson-Merton γ_HM Contradiction

**Location in compiled paper**: body.tex lines 388, 394, 448

**Relevant text**:
- body.tex line 388: `γ_HM = −0.035, t = −0.39, p = 0.70` (pure VT, full sample)
- body.tex line 394: `γ_HM = −0.068, t = −4.63` (pure VT, high-VIX episodes)
- body.tex line 448: `γ_HM = −0.043, t = −4.06` (Hybrid VT, full sample) + **clarifying footnote**

**Status**: PARTIAL — The disambiguating footnote is present in body.tex at line 448, which reads: "The three γ_HM estimates reported in this paper share the same symbol but correspond to distinct Henriksson-Merton regressions on different samples: γ_HM = −0.035 (t = −0.39) for the pure-VT strategy over the full 2014–2026 sample (Section 4.7); γ_HM = −0.068 (t = −4.63) for the pure-VT strategy conditional on high-VIX episodes (VIX > 25); and γ_HM = −0.043 (t = −4.06) for the Hybrid VT strategy over the full sample (this section). The consistent negative sign across all three specifications supports the variance-management interpretation."

**Assessment**: This footnote is an effective partial resolution. A careful reader can now disambiguate the three values. However, a JBF referee reading Section 4.8 without reaching the footnote at line 448 will still see γ_HM = -0.035 n.s. followed later by γ_HM = -0.043 t=-4.06 ***, which is still potentially confusing. The fix would be stronger if Section 4.8 itself cross-referenced the forthcoming clarification ("see footnote in Section 5.4.4 for disambiguation of three HM regression specifications"). As currently written, the footnote appears only in §5.4.4 and a reader may not backtrack.

**Severity downgrade**: from CRITICAL-HIGH to MEDIUM. The disambiguation exists but relies on a reader reaching the footnote.

---

### Issue #3: Proposition 1 → Empirical Regularity 1

**Location**: body.tex line 458

**v3 text**: `\textbf{Empirical Regularity 1 (Gamma-Mechanism Mapping, equity-type assets).}`

**Status**: CLOSED. The rebranding is clean and consistently applied throughout (lines 458, 619). The conclusion also uses "Empirical Regularity 1" correctly.

**Assessment**: The rename eliminates the "theorem-like promise that N=6 cannot deliver" problem. CLOSED.

---

### Issue #4: Table 3 "9/9 perfect" — Abstract In-Sample Qualifier

**Location**: main.tex abstract (lines 39–39)

**Abstract text**: "...correctly classifying all nine Diebold-Mariano comparisons in the primary sample, with 6/6 correct out-of-sample predictions."

**Body text (line 237)**: Explicit caveat present — "the 9/9 'perfect classification' is therefore partly in-sample and should not be interpreted as a measure of predictive accuracy."

**Status**: PARTIAL — SEVERE. The body text has an explicit in-sample caveat. However, the abstract says "in the primary sample" without adding "(in-sample)" or "in-sample threshold calibration" qualifier. Body-level fix from v2 action plan (add "(in-sample threshold calibration)" qualifier to the 9/9 clause) was applied in body.tex but the abstract still does not carry the qualifier. A reader reading only the abstract would still not immediately grasp that "primary sample" here means "in-sample."

**JBF Impact**: Referees read abstracts first. This remains a framing issue.

---

### Issue #5: Missing ES Backtest

**Location**: body.tex lines 256–269

**v3 addition**: New subsection 4.4.1 "Expected Shortfall: Fissler-Ziegel Evaluation" present in body.tex.

**Content**:
- Invokes Fissler-Ziegel (2016) elicitability theorem
- Reports multi-asset DCC asymmetric vs. symmetric comparison from K1092: ΔL_FZ = −0.074, t=2.95, p=0.003 at α=1%
- Explicitly flags limitation: standalone FRTB ES backtest on all 7 primary assets not yet at power threshold; deferred to replication package supplement

**Status**: PARTIAL. The ES section exists and correctly invokes the FZ framework. However:
1. The FZ evidence cited (K1092) is from the multi-asset DCC-GARCH framework, not the primary seven-asset univariate panel that is the paper's core result. A referee will note this is evidence from a different model class.
2. The limitation footnote explicitly admits: "does not claim a stand-alone FRTB ES backtest pass at the single-asset level." While honest, this partially undercuts the response to the v2 criticism.
3. The `k1092` bibitem (line 129–131 of main.tex) is an internal experiment record, not a peer-reviewed citation. JBF will question citing internal research records.

**Assessment**: Good-faith addition, but a referee will still call this insufficient for FRTB compliance evidence. PARTIAL — downgraded from HIGH to MEDIUM.

---

### Issue #6: BTC Allocation Logic

**Location**: body.tex lines 230–235, 289

**v3 text (line 230)**: "If γ is statistically significant at 10% (t > 1.65) and positive: Use GJR-GARCH"

**v3 text (line 289)**: "GJR-GARCH for assets where γ is statistically significant at 10% and positive (t > 1.65) — namely SPY and EEM — and symmetric GARCH otherwise (GLD, TLT, BTC-USD; BTC's mean γ = 0.117 is insignificant given std = 0.136, consistent with Table 3 showing GARCH marginally outperforms GJR for BTC)."

**Status**: CLOSED. The significance-based rule (t>1.65) replaces the raw γ>0.10 threshold. BTC is correctly excluded from GJR because its γ is unstable (std=0.136, t<1.65). The text explicitly explains why BTC is correctly treated as symmetric despite γ=0.117 > 0.10. The logic is self-consistent.

---

### Issue #7: Citation Orphans and Missing References

**Status**: CLOSED (mostly).

**Confirmed removed orphans**: `bollerslev1994`, `corsi2009`, `engle2002` — none found in main.tex bibliography.

**New citations added**:
- `engleGhyselsSohn2013` — present in bibliography (line 111) and cited in body.tex line 26
- `pattonSheppard2015` — present in bibliography (line 126) and cited in body.tex line 26
- `fisslerziegel2016` — added for ES section
- `acerbiszekely2014` — added for ES section
- `bayerdimitriadis2022` — added for ES section
- `k1092` — internal experiment record citation (see concerns in Issue #5 above)

**Remaining**: `parkinson1980` still in bibliography but not cited anywhere in body.tex or narrative (unchanged from v2). `hood2025` title still uses short form "Volatility targeting is trendy." without subtitle.

---

## New Issues Found in v3

### NEW-1: body.tex Not Updated with v3 Fixes [CRITICAL]

As documented above, `main.tex` imports `body.tex` not `body_v3.tex`. The corrected t-statistics (t=-3.79) and the clarifying footnote for Issue #1 are in `body_v3.tex` only. The compiled paper still presents the v2 contradiction. This is a structural defect in the v3 revision process — the fixes were written to the wrong file.

**Fix required**: Either update `body.tex` with the changes from `body_v3.tex`, or change `main.tex` to `\input{body_v3}`.

### NEW-2: Internal t-Statistic Inconsistency in body.tex [SEVERE]

body.tex has three occurrences of the regime t-statistic for gold:
- Line 12: `t = -4.71, p < 0.0001`
- Line 168: (footnote) `t=-4.71`
- Line 208: `t = -4.71, p < 0.0001`

body_v3.tex updated all three to `t=-3.79, p<0.001`. If the t-statistic changed between v2 and v3 due to recomputation, this is a substantive revision. The fact that body.tex has the old value while body_v3.tex has the new value suggests a recomputed result was applied only to body_v3.tex. A reviewer will ask which value is correct.

### NEW-3: Abstract Still Missing "(in-sample)" Qualifier on 9/9 [SEVERE]

main.tex abstract (line 39): "correctly classifying all nine Diebold-Mariano comparisons in the primary sample" — the phrase "in the primary sample" does not explicitly say "in-sample." The v2 action plan called for adding "(in-sample threshold calibration)" to this clause. This was NOT done in the abstract.

### NEW-4: k1092 Internal Citation in Bibliography [MEDIUM]

The bibliography (main.tex line 129–131) contains:
```
\bibitem[VolPred Research(K1092, 2026)]{k1092}
VolPred Research Program (2026). K1092: Asset-matched DCC-A4f Fissler–Ziegel evaluation. Internal experiment record, available in the paper's replication package.
```
JBF does not accept internal experiment records as citable bibliography entries. This entry should either be moved to a footnote or replaced with a working paper deposited on SSRN. As a bibitem it will be flagged by the editorial system.

### NEW-5: Abstract Lists Only Five Asset Classes for Seven Assets [MED]

main.tex abstract (line 39): "daily data for seven primary assets (equities, gold, bonds, emerging markets, cryptocurrency)" — five classes listed for seven assets, still missing silver (SLV). This was flagged in v2 as [MED] and remains unresolved.

### NEW-6: engle2004 Placement [LOW]

`engle2004` (Engle 2004, Nobel lecture AER) remains in the bibliography but is not visibly cited in body.tex via `\cite{}`. Only narrative references appear possible. This may be an orphan — verify.

---

## Sections Review: Selected Notes

### Abstract
- 9/9 qualifier: PARTIAL (see NEW-3)
- "seven primary assets (equities, gold, bonds, emerging markets, cryptocurrency)" — SLV missing (inherited v2 [MED])
- "extended to 26 assets in validation analyses" — body says "up to 26 assets"; abstract should match — still [LOW] unfixed

### Introduction (body.tex lines 1–20)
- Line 12: t=-4.71 still present (see NEW-2)
- Christie (1982) attribution issue from v2 still present (HIGH in v2 review): "first noted by Black (1976) and formalized by Christie (1982)" — Christie formalized financial-leverage mechanism, not the term itself. This [HIGH] issue from v2 academic review was listed in the original issues but not in the v2 README's "7 HIGH" count; it should be addressed.

### Literature Review (body.tex lines 22–52)
- engleGhyselsSohn2013 and pattonSheppard2015 now correctly cited. CLOSED.
- demiguel2024 framing: body.tex line 46 now reads "in-sample Sharpe gains of VT strategies are substantially attenuated once exposures to standard risk factors are controlled for" — this is accurate and the v2 MED citation-framing issue is CLOSED.

### Methodology (body.tex lines 54–147)
- VaR Student-t formula clarity: not explicitly re-examined in v3 body.tex. Body line 132 references VaR formula but the σ_t standardization concern from v2 is not visibly addressed.

### Results
- Section 4.3 (body.tex line 237): In-sample caveat in body is explicit and strong. CLOSED at body level.
- Section 4.4.1: ES/FZ section present but with caveats (NEW-4).
- Section 4.8 HM test: three estimates present; disambiguating footnote at §5.4.4. PARTIAL.

### References
- parkinson1980 remains uncited but in bibliography
- hood2025 short title (minor, unfixed)
- campbell2017 bibitem label style mismatch (minor, unfixed)

---

## Submission Readiness Assessment

| Criterion | v2 Score | v3 Score | Change |
|-----------|----------|----------|--------|
| Internal consistency | ★★☆☆☆ | ★★☆☆☆ | No change (body.tex not updated) |
| Citation completeness | ★★☆☆☆ | ★★★★☆ | +2 (orphans removed, key citations added) |
| Statistical rigor | ★★★☆☆ | ★★★½☆ | +0.5 (ES section, BTC rule fixed) |
| Argument quality | ★★★☆☆ | ★★★½☆ | +0.5 (Empirical Regularity rename) |
| Reproducibility | ★★★★☆ | ★★★★☆ | Unchanged |
| Abstract quality | ★★★☆☆ | ★★★☆☆ | Unchanged (in-sample qualifier missing) |
| **Overall JBF fit** | ★★★☆☆ | ★★★☆☆ | No net improvement (compilation error) |

**Overall rating**: ★★★☆☆ (3/5) — effectively unchanged from v2 because the two CRITICAL issues persist in the compiled paper.

---

## Recommendations

### Must fix before JBF submission (blocking)

1. **[CRITICAL]** Port `body_v3.tex` changes to `body.tex` (or update `main.tex` to `\input{body_v3}`). This is the single most important fix — it resolves HIGH-1 and partially resolves HIGH-2.
2. **[CRITICAL]** After porting, verify the t-statistic for regime difference: is the correct value -4.71 (v2) or -3.79 (v3)? The change implies recomputation; both cannot be correct. The `body_v3.tex` version and footnote text that references `K1198 reconciliation` suggests -3.79 is the recomputed value — confirm and document.
3. **[SEVERE]** Add "(in-sample)" qualifier to abstract's 9/9 claim: "...correctly classifying all nine Diebold-Mariano comparisons in the primary sample (in-sample threshold calibration), with 6/6 correct out-of-sample predictions."
4. **[MEDIUM]** Convert `k1092` bibliography entry to a footnote rather than a `\bibitem{}` — JBF does not accept internal experiment records as formal references.
5. **[MEDIUM]** Strengthen §4.8 cross-reference: add "(see footnote, Section 5.4.4, for disambiguation of three HM regression specifications)" at first mention to prevent referee confusion before reaching the footnote.

### Should fix (framing)

6. **[LOW]** Update `hood2025` to full title with subtitle.
7. **[LOW]** Remove or cite `parkinson1980` (still uncited).
8. **[MED]** Fix abstract asset-class enumeration: list SLV or collapse correctly.

---

## Bottom Line

The v3 revision achieved significant progress on issues 3–7 (ES section added, BTC rule fixed, Empirical Regularity rename, orphan citations removed, new key citations added). However, the revision was applied to `body_v3.tex` rather than `body.tex`, meaning the compiled paper (`main.tex`) still carries the v2 text for the two most critical internal contradictions (Issue #1 regime-gamma contradiction, Issue #2 HM gamma). The abstract also still lacks the in-sample qualifier. These are trivial to fix but currently block submission. Once these mechanical issues are corrected, the paper would be ready for JBF submission with a realistic R&R outcome, estimated at 1–2 rounds.
