# Citation Verification Report

**Manuscript**: "Is Volatility Targeting Just Trend Following? Decomposing the Benefits of Volatility Targeting"
**Version**: body_v3.tex (incorporating v3 revisions: TSMOM direction correction, 1.4%→5.3% errata, K1192 bootstrap update)
**Date**: 2026-05-23
**Reviewer**: VolPred Research System (Claude Sonnet 4.6)
**Total Bibliography Entries**: 18
**Total Unique Cite Keys in Body**: 18
**Baseline Comparison**: citation_check.md (v1, 2026-03-30) + citation_check_r1.md (v2, 2026-04-05)

---

## Issue Count Summary

| Severity | Count |
|----------|-------|
| MAJOR    | 4     |
| MEDIUM   | 3     |
| MINOR    | 3     |
| INFO     | 2     |

**Overall Verdict: CONDITIONAL_PASS**

All 18 citation keys are present in both the body and the bibliography — no orphan or missing references. The bibliographic entries themselves are accurate. However, four MAJOR internal-consistency issues were found between text, tables, and figures that reviewers will flag as data-integrity problems. These must be resolved before submission.

---

## Section 1: Cross-Reference Audit

### 1.1 In-Text Citations vs. Bibliography

| # | Key | Body Citations | In Bibliography? | Status |
|---|-----|---------------|-----------------|--------|
| 1 | `baltas2013` | Lines 38, 79 (via moskowitz2012 group) | YES | OK |
| 2 | `barroso2015` | Line 28 | YES | OK — orphan fixed from v1 |
| 3 | `black1976` | Line 28 | YES | OK |
| 4 | `bozovic2024` | Lines 58, 508 | YES | OK |
| 5 | `cederburg2020` | Lines 26, 30, 492 | YES | OK |
| 6 | `christie1982` | Line 28 | YES | OK |
| 7 | `daniel2016` | Line 38 | YES | OK — orphan fixed from v1 |
| 8 | `fleming2001` | Line 38 | YES | OK — orphan fixed from v1 |
| 9 | `glosten1993` | Line 108 | YES | OK |
| 10 | `harvey2016` | Lines 27, 397, 495, 538 | YES | OK |
| 11 | `harvey2018` | Line 26 | YES | OK |
| 12 | `hood2025` | Lines 28, 38, 79, 488, 524, 526 | YES | OK |
| 13 | `lai2026a` | Lines 26, 38, 63, 141, 513, 520 | YES | OK |
| 14 | `miranda2020` | Lines 36, 410, 515 | YES | OK |
| 15 | `moreira2017` | Line 26 | YES | OK |
| 16 | `moskowitz2012` | Lines 26, 38, 67, 490, 505 | YES | OK |
| 17 | `newey1987` | Line 89 | YES | MEDIUM — see Issue M1 |
| 18 | `rapach2013` | Line 410 | YES | OK |

**Orphan Count**: 0 (all three v1 orphans — barroso2015, daniel2016, fleming2001 — are now cited in the body)
**Missing Count**: 0

---

## Section 2: Issue Registry

### MAJOR Issues

**[MAJOR-1] SPY MDD values inconsistent between Section 3.3 narrative and Table 3**

- **Location**: Section 3.3 (line 247) vs. Table 3 (`tab:dual_mechanism`, lines 320–321)
- **Description**: The body text (line 247) states VT achieves -26.3% MDD and TSMOM-hedged VT achieves -25.3%, implying VT protects 28.9 pp and hedged VT retains 29.9 pp (103.7%). However, Table 3 shows VT = -24.7% and TSMOM-Hedged VT = -26.9%, with the decomposition rows reporting MDD protection (VT) = 30.5 pp and MDD protection retained = 28.3 pp (93%).
- **Extent**: Three-way inconsistency: Section 3.3 text ≠ Table 3 raw values ≠ Table 3 decomposition footer. The retention percentage claimed in the text (103.7%) matches Table 2 / K1192, but the raw MDD numbers differ between the prose and Table 3. Additionally, the figure 1 caption states TSMOM explains "only 3--10% of MDD protection" which aligns with 103.7% retention, but Table 3's decomposition footer shows 93% retained (= 7% not retained), creating an additional discrepancy.
- **Severity**: MAJOR — a referee will compute the numbers from the table and find they do not match the text.
- **Fix**: Reconcile Table 3 MDD values against K1192 canonical JSON. Either update the table rows (-24.7% and -26.9%) to match the text values (-26.3% and -25.3%), or update the text to match the table. The K1192 canonical source should be treated as ground truth.

**[MAJOR-2] International MDD statistics inconsistent across abstract, body text, and Table 5**

- **Location**: Abstract (line 8), Section 3.1 intro (line 36), Section 3.4 text (line 404/408) vs. Table 5 (`tab:international`, lines 442–447) vs. Figure 2 caption (line 463)
- **Description**: Two distinct sets of statistics appear for the cross-sectional VIX-sensitivity vs. ΔMDDs relationship:
  - **Set A (K1178 canonical, cited in abstract and Section 3.4)**: average ΔMDDs = 24.9 pp, t = 10.25; VIX sensitivity Pearson r = -0.806, Spearman ρ = -0.835
  - **Set B (Table 5 and Figure 2 caption)**: average ΔMDDs = 28.7 pp, t = 15.70; VIX sensitivity r = -0.770, ρ = -0.720 (Table 5 shows r = -0.770, ρ = -0.720; figure caption says r = -0.770)
- **Conclusion (Section 5, line 538)** uses 28.7 pp (matching Table 5), while the abstract uses 24.9 pp (matching K1178 canonical). The abstract and Table 5 directly contradict each other.
- **Severity**: MAJOR — abstract vs. table disagreement on key headline statistics. A reviewer reading the abstract and then Table 5 will flag this immediately.
- **Fix**: Determine which is the canonical figure (K1178 JSON or Table 5 replication) and update all occurrences to be consistent. The Section 3.4 table note also has r = -0.770 for "VIX Sensitivity vs. ΔMDDs" which may reflect a corrected computation; if so, abstract and body text must be updated to match.

**[MAJOR-3] Split-sample bootstrap CI: confidence level and values inconsistent between body text and Table 2**

- **Location**: Section 3.2 narrative (line 206) vs. Table 2 Panel B (line 226)
- **Description**: The body text states the split-sample Pearson r = 0.793 has a "bootstrap **90%** CI [0.589, 0.919]" (5,000 replications). Table 2, Panel B, row labeled "Bootstrap 95% CI for Pearson r: [0.114, 0.737]" — both the confidence level (90% vs. 95%) and the interval values differ substantially. Additionally, Table 2's note (line 239) says "Bootstrap 95% CI for full-sample Pearson r: [0.263, 0.772]" which appears to be describing the full-sample CI, not the split-sample CI, but the Panel B row is about the split-sample.
- **Severity**: MAJOR — mismatched confidence levels cannot be attributed to rounding. A referee testing the bootstrap will find the inconsistency.
- **Fix**: (a) Determine whether the bootstrap for the split-sample used 90% or 95% CI. (b) Correct the table row label to match the actual confidence level. (c) If [0.114, 0.737] is a 95% CI for the split-sample r, it is consistent with r = 0.793 being the point estimate but outside a plausible 95% CI range — this warrants investigation. The K1193 canonical JSON should be the source of truth.

**[MAJOR-4] Broken cross-reference: `\ref{tab:intl_vix}` does not exist**

- **Location**: Section 4 (Limitations), line 528
- **Description**: The text references `Table~\ref{tab:intl_vix}` for "13 markets in Table \ref{tab:intl_vix}". The actual table label for the international results is `tab:international` (line 417). This is an undefined label — LaTeX will render "Table ??" and log an "undefined reference" warning. Since the `\ref{tab:intl_vix}` does not exist anywhere in the document, this is not a label collision but a stale reference from a prior draft version.
- **Severity**: MAJOR — compiles to "Table ??" in the PDF, which no journal will accept.
- **Fix**: Change `\ref{tab:intl_vix}` to `\ref{tab:international}` on line 528.

---

### MEDIUM Issues

**[MEDIUM-1] Newey–West (1987) citation for automatic lag formula is technically incorrect**

- **Location**: Line 89, and carried through all table notes referencing NW automatic lag
- **Description**: The paper attributes the automatic lag selection formula $\ell = \lfloor 4(T/100)^{2/9} \rfloor$ to `\citep{newey1987}`. This formula is from Newey & West (1994), "Automatic lag selection in covariance matrix estimation," *Review of Economic Studies*, 61(4), 631–653. The 1987 paper introduces the HAC estimator but does not contain automatic lag selection. This was flagged in citation_check_r1.md (2026-04-05) as MINOR and remains unresolved in v3.
- **Severity**: MEDIUM — a referee expert in HAC will flag this. It is a factual misattribution of a formula.
- **Fix options**: (a) Add the NW (1994) bibitem and cite it for the lag formula while keeping NW (1987) for the HAC estimator itself; or (b) drop the automatic lag claim and specify a fixed integer lag, citing only NW (1987).

**[MEDIUM-2] Hood & Raughtigan (2025) working paper: no institution, SSRN, or URL**

- **Location**: Bibliography entry, lines 582–583
- **Description**: The bibitem reads: `Hood, M., & Raughtigan, J. (2025). Volatility targeting alpha is trend following alpha. Working Paper.` — no institutional affiliation, no SSRN accession number, no conference venue, no URL. This paper is the manuscript's primary interlocutor (cited six times, including the opening empirical claim that "91% of equity VT alpha is absorbed by a TSMOM factor"). Reviewers and readers cannot verify the cited claim without being able to locate the paper. This was flagged as ERROR in citation_check_r1.md and remains unresolved.
- **Severity**: MEDIUM — journal editors may return the manuscript requesting identification before sending to referees.
- **Fix**: Add SSRN link (if available), institutional affiliation, or AFA/WFA conference year. If the paper is unpublished and accessible only to the authors, note the availability (e.g., "Available from the authors upon request").

**[MEDIUM-3] Baltas & Kosowski (2013) remains as working paper despite published version existing**

- **Location**: Bibliography entry, lines 549–550
- **Description**: The bibitem cites a 2013 working paper from Imperial College London. A published version appeared in *European Financial Management* (2019, 25(3), 441–484). The working paper is now 13 years old and has been superseded. This was flagged as MEDIUM in citation_check.md (v1) and citation_check_r1.md (v2) and remains unresolved through v3.
- **Severity**: MEDIUM — using a published version is standard practice and strengthens the reference's traceability.
- **Fix**: Update to: Baltas, A. N., & Kosowski, R. (2019). Momentum strategies in futures markets and trend-following funds. *European Financial Management*, 25(3), 441–484. https://doi.org/10.1111/eufm.12138

---

### MINOR Issues

**[MINOR-1] Grammar error in Barroso (2015) citation context**

- **Location**: Line 28
- **Description**: "volatility-scaling momentum strategies **eliminates** momentum crashes" should be "eliminate" (plural subject "strategies" requires plural verb). This was identified in citation_check_r1.md and remains unresolved.
- **Severity**: MINOR — grammatical error, not a citation error.
- **Fix**: Change "eliminates" to "eliminate".

**[MINOR-2] Lai (2026a) suffix: no companion (2026b) identified in bibliography**

- **Location**: Bibliography entry (line 585) and all in-text citations
- **Description**: The "a" suffix in "Lai (2026a)" implies a Lai (2026b) exists. This paper itself would logically be Lai (2026b). If the intention is for this manuscript and the leverage-direction paper to appear as (2026a)/(2026b) in a submission package, the suffix is correct but should be documented. If no companion paper is intended, the suffix creates unnecessary ambiguity. This was noted in both prior citation checks.
- **Severity**: MINOR — not an error per se, but reviewers will expect to see Lai (2026b) if Lai (2026a) is cited.
- **Fix**: Either (a) add a self-citation `lai2026b` for this paper at appropriate locations, or (b) remove the "a" suffix if no companion paper will be submitted alongside.

**[MINOR-3] Harvey et al. (2016) title uses `\ldots{}` ellipsis**

- **Location**: Bibliography entry, line 577
- **Description**: The actual title is "\ldots and the cross-section of expected returns" which renders as "... and the cross-section of expected returns". The `\ldots{}` rendering is technically correct (the title does begin with an ellipsis), but is unconventional in a reference list and may confuse automated citation parsers.
- **Severity**: MINOR — format only.
- **Fix**: Consider spelling out the full title if the journal style guide requires it, or verify the official citation format on the RFS website.

---

### Informational Notes

**[INFO-1] Missing Frazzini & Pedersen (2014) citation for BAB factor**

- **Description**: The paper uses a BAB factor in Table 4 (M5) and discusses its economic interpretation (line 356: "consistent with VT's dynamic leverage being partially correlated with the low-beta anomaly"). The data source "AQR" is acknowledged (line 54), but the original Frazzini & Pedersen (2014) "Betting Against Beta" (*Journal of Financial Economics*, 111(1), 1–45, DOI: 10.1016/j.jfineco.2013.10.005) is not cited. This was flagged as HIGH priority in both prior citation checks.
- **Priority**: HIGH for submission — finance referees will expect this citation when any BAB factor appears in regressions.
- **Fix**: Add bibitem for Frazzini & Pedersen (2014) and cite it when BAB is first introduced in Section 2.4 or when first used in Table 4.

**[INFO-2] Intro inconsistency: Section 3.4 body claims MDD % "90–97%" but section 3.3 body and Table 2 show K1192 retention of 95.6–109%**

- **Description**: Introduction (line 30) states "90–97% across five US equity assets" as the MDD retention. This appears to be a v2-era figure that was not updated when K1192 revised estimates to 95.6–109.0%. The body of Section 3.3 and Conclusion correctly use K1192 canonical figures. The introduction paragraph retains the outdated range.
- **Priority**: Should be updated for internal consistency.
- **Fix**: Update the introduction's "90–97%" to "95.6–109.0% (K1192 canonical)" to match Section 3.3 and Conclusion.

---

## Section 3: Bibliography Entry Verification

| # | Key | Authors | Year | Journal/Venue | DOI | Status |
|---|-----|---------|------|--------------|-----|--------|
| 1 | baltas2013 | Baltas & Kosowski | 2013 | Working Paper, Imperial College | None | MEDIUM-3: published 2019 |
| 2 | barroso2015 | Barroso & Santa-Clara | 2015 | JFE 116(1), 111–120 | 10.1016/j.jfineco.2014.11.010 | OK |
| 3 | black1976 | Black | 1976 | ASA Proceedings, 177–181 | None (conference) | OK |
| 4 | bozovic2024 | Bozovic | 2024 | IRFA 95, 103353 | 10.1016/j.irfa.2024.103353 | OK |
| 5 | cederburg2020 | Cederburg et al. | 2020 | JFE 138(1), 95–117 | 10.1016/j.jfineco.2020.04.015 | OK |
| 6 | christie1982 | Christie | 1982 | JFE 10(4), 407–432 | 10.1016/0304-405X(82)90018-6 | OK |
| 7 | daniel2016 | Daniel & Moskowitz | 2016 | JFE 122(2), 221–247 | 10.1016/j.jfineco.2015.12.002 | OK |
| 8 | fleming2001 | Fleming et al. | 2001 | JF 56(1), 329–352 | 10.1111/0022-1082.00327 | OK |
| 9 | glosten1993 | Glosten et al. | 1993 | JF 48(5), 1779–1801 | 10.1111/j.1540-6261.1993.tb05128.x | OK |
| 10 | harvey2016 | Harvey et al. | 2016 | RFS 29(1), 5–68 | 10.1093/rfs/hhv059 | MINOR-3 (title format) |
| 11 | harvey2018 | Harvey et al. | 2018 | JPM 45(1), 14–33 | 10.3905/jpm.2018.45.1.014 | OK |
| 12 | hood2025 | Hood & Raughtigan | 2025 | Working Paper | None | MEDIUM-2: no identification |
| 13 | lai2026a | Lai | 2026a | Working Paper, Da-Yeh | None | MINOR-2 (suffix) |
| 14 | miranda2020 | Miranda-Agrippino & Rey | 2020 | ReStud 87(6), 2754–2776 | 10.1093/restud/rdaa019 | OK |
| 15 | moreira2017 | Moreira & Muir | 2017 | JF 72(4), 1611–1644 | 10.1111/jofi.12513 | OK |
| 16 | moskowitz2012 | Moskowitz et al. | 2012 | JFE 104(2), 228–250 | 10.1016/j.jfineco.2011.11.003 | OK |
| 17 | newey1987 | Newey & West | 1987 | Econometrica 55(3), 703–708 | 10.2307/1913610 | MEDIUM-1: wrong paper for lag formula |
| 18 | rapach2013 | Rapach et al. | 2013 | JF 68(4), 1633–1662 | 10.1111/jofi.12041 | OK |

---

## Section 4: Content Claim Accuracy

| Citation | Claim in Text | Accuracy | Notes |
|----------|--------------|---------|-------|
| barroso2015 | "eliminates momentum crashes" via vol-scaling | Accurate | Barroso & Santa-Clara (2015) is exactly this; grammar error noted (MINOR-1) |
| black1976 | leverage effect seminal reference | Accurate | Standard attribution |
| bozovic2024 | 12/VIX construction; VIX mean-reversion | Accurate | Paper proposes VIX-managed portfolios |
| cederburg2020 | VT does not improve welfare via higher moments | Accurate | Matches abstract/conclusion of the paper |
| christie1982 | leverage effect empirical documentation | Accurate | Standard attribution |
| daniel2016 | momentum crashes driven by leverage-effect volatility clustering | Accurate | Core finding of Daniel & Moskowitz (2016) |
| fleming2001 | "economic value of volatility timing in portfolio context" | Accurate | Title and content match |
| glosten1993 | GJR-GARCH model origination | Accurate | Standard attribution |
| harvey2016 | t > 3.0 threshold for multiple-testing | Accurate | Paper recommends ~3.0 for a new factor |
| harvey2018 | VT improves risk-adjusted returns across asset classes | Accurate | Core finding of the paper |
| hood2025 | "~91% of equity VT alpha absorbed by TSMOM, 50 futures" | Cannot independently verify | No public URL; claim plausible but unverifiable — MEDIUM-2 |
| lai2026a | 12/VIX threshold robustness [6,20]; insurance premium; DCC analysis | Accurate per context | Self-authored, consistent with leverage-direction paper |
| miranda2020 | US monetary policy propagates via global financial cycle | Accurate | Core finding of Miranda-Agrippino & Rey (2020) |
| moreira2017 | VT improves Sharpe across equity factors | Accurate | Seminal volatility-managed portfolios paper |
| moskowitz2012 | TSMOM significant across 58 futures markets | Accurate | Exact number from paper |
| newey1987 | HAC estimator + automatic lag formula | HAC accurate; lag formula INCORRECT | Lag formula is NW (1994) — MEDIUM-1 |
| rapach2013 | US market leads international returns | Accurate | Core finding of Rapach et al. (2013) |

---

## Section 5: Changes from v1/v2 Baselines

| Item | v1 Status | v2 Status | v3 Status |
|------|-----------|-----------|-----------|
| barroso2015 orphan | HIGH (orphan) | Fixed (cited in intro) | OK |
| daniel2016 orphan | HIGH (orphan) | Fixed (cited in intro) | OK |
| fleming2001 orphan | HIGH (orphan) | Fixed (cited in intro) | OK |
| hood2025 no institution | HIGH error | Medium (persists) | MEDIUM-2 (persists) |
| Newey-West lag formula | MINOR | MEDIUM (persists) | MEDIUM-1 (persists) |
| Baltas2013 working paper | MEDIUM | MEDIUM (persists) | MEDIUM-3 (persists) |
| Frazzini & Pedersen missing | HIGH | HIGH (persists) | INFO-1 (persists) |
| lai2026a suffix | LOW | MINOR (persists) | MINOR-2 (persists) |
| Harvey2016 title format | LOW | MINOR (persists) | MINOR-3 (persists) |
| Grammar: "eliminates" | NEW | MINOR (persists) | MINOR-1 (persists) |
| SPY MDD text/table mismatch | n/a | NEW in v3 | MAJOR-1 |
| International t-stat mismatch | n/a | NEW in v3 | MAJOR-2 |
| Split-sample CI mismatch | n/a | NEW in v3 | MAJOR-3 |
| Broken \ref{tab:intl_vix} | n/a | NEW in v3 | MAJOR-4 |

---

## Section 6: Correction Priority Checklist

### Must Fix Before Any Further Review

- [ ] **MAJOR-4**: Replace `\ref{tab:intl_vix}` with `\ref{tab:international}` (line 528) — 1-line fix
- [ ] **MAJOR-1**: Reconcile SPY MDD values (-26.3%/-25.3% in text vs. -24.7%/-26.9% in Table 3); verify against K1192 JSON and make text + table consistent
- [ ] **MAJOR-2**: Reconcile international statistics (24.9 pp, t=10.25, r=-0.806, ρ=-0.835 in abstract/body vs. 28.7 pp, t=15.70, r=-0.770, ρ=-0.720 in Table 5/Figure 2); identify which is K1178 canonical and update all occurrences consistently
- [ ] **MAJOR-3**: Resolve split-sample bootstrap CI discrepancy — body text says "90% CI [0.589, 0.919]" but Table 2 says "95% CI [0.114, 0.737]"; verify against K1193 JSON

### Must Fix Before Submission

- [ ] **MEDIUM-1**: Either add Newey & West (1994) bibitem for the automatic lag formula, or specify a fixed integer lag
- [ ] **MEDIUM-2**: Add SSRN link / institutional affiliation for Hood & Raughtigan (2025)
- [ ] **MEDIUM-3**: Update Baltas & Kosowski citation to published 2019 European Financial Management version
- [ ] **INFO-1**: Add Frazzini & Pedersen (2014) bibitem and cite when BAB factor is introduced
- [ ] **INFO-2**: Update introduction "90–97%" to "95.6–109.0% (K1192 canonical)" for internal consistency

### Should Fix

- [ ] **MINOR-1**: Change "eliminates" to "eliminate" (line 28)
- [ ] **MINOR-2**: Either add `lai2026b` self-citation or remove the "a" suffix
- [ ] **MINOR-3**: Review Harvey (2016) title format with target journal style guide

---

## Overall Verdict

**CONDITIONAL_PASS**

The citation architecture is structurally sound: all 18 keys are present in both the body and the bibliography, three v1 orphans were correctly fixed in v2 and carry through to v3, and the bibliographic details for the 15 peer-reviewed journal articles are accurate. Content claims are accurately represented for all verifiable citations.

However, v3 introduced four MAJOR internal-consistency issues (MAJOR-1 through MAJOR-4) that create direct contradictions between the abstract, body text, tables, and figures. A referee will compute the numbers from the tables and find they do not match the text. These must be resolved by tracing each figure back to its canonical experiment JSON (K1178, K1192, K1193) before any further peer-review submission. Three persistently unresolved MEDIUM issues from v1/v2 (Hood working paper identification, NW lag attribution, Baltas published version) should also be addressed at submission.

---

*Report generated 2026-05-23 by VolPred citation-verifier. Baseline: citation_check.md (v1), citation_check_r1.md (v2). Source files: paper/vt-trend-following/body_v3.tex, paper/vt-trend-following/main_v3.tex.*
