# LaTeX Academic Review v2 — eav-universal-magnitude

**Reviewer**: Codex, using `.claude/skills/latex-academic-reviewer/` + `finance-paper-quality`
**Date**: 2026-07-06
**Scope**: `paper/eav-universal-magnitude/body.tex` (1433 lines), `references.bib`, `reproduce.py`, selected evidence packages K1163/K1172/K1207/K1216c/K1470
**Trigger**: `paper_review_eav_universal_magnitude_v2` — body.tex revised after v1 review

## Executive Verdict

**NEEDS MAJOR REVISION / NOT SUBMISSION READY**

v2 is a real improvement over v1: `references.bib` exists, citation keys all resolve, Table 2 dropout minimums were corrected, and the paper compiles with BibTeX. The reproduce gate remains GREEN (20/20).

However, v2 introduces a larger narrative-synthesis problem. The manuscript now mixes the original three-market evidence with K1172/K1207/K1216c/K1470 follow-up experiments, but it does not keep market counts, sample sizes, multistart status, and contribution hierarchy consistently separated. The PDF still prints two explicit placeholders. These are submission blockers.

## Verification Performed

| Check | Result |
|---|---|
| `xelatex -> bibtex -> xelatex -> xelatex body.tex` | PASS; `body.pdf` generated, 30 pages |
| BibTeX citation-key coverage | PASS; 10 cite keys, 10 bib keys, no missing/orphan keys |
| `uv run python reproduce.py` | PASS; 20/20 GREEN |
| `uv run python scripts/check_paper_compliance.py` | CLEAN for eav-universal-magnitude |
| `pdftotext body.pdf` placeholder scan | FAIL; placeholders and title-page disclaimer appear in PDF |

## Severity Summary

| Severity | Count | Main Issues |
|---|---:|---|
| SEVERE | 4 | PDF placeholders; K1470/table-footnote contradiction; market-count/sample-size mouth-mixing; internal workflow language in final prose |
| HIGH | 4 | contribution overload; reproduce gate undercovers new panel; multistart nomenclature conflict; model notation/fixed-effect ambiguity persists |
| MEDIUM | 5 | DOI/citation improvements deferred to citation report; overfull tables; CJK dependency; bootstrap B=150 sensitivity; JP/US timing/data quality caveats |
| LOW | 3 | abstract precision, typography, table layout |

## SEVERE Findings

### S1. Two placeholders are printed in the PDF

**Location**: `body.tex:479-503`, `body.tex:1368-1377`

`pdftotext body.pdf` shows:
- `[PLACEHOLDER: Summary statistics table to be generated from reproduce.py output ...]`
- `[PLACEHOLDER: To be written after P1 follow-up (analytic-gradient MLE re-fit ...]`

This is a hard blocker. The Appendix A placeholder is especially damaging because the main text uses it to justify the convergence caveat (`body.tex:372-380`) and the multistart discussion later refers back to Appendix A (`body.tex:932-934`).

**Required fix**: either write Appendix A and populate the summary-statistics table, or remove both references and explicitly state that those checks are not yet complete.

### S2. Abstract/conclusion say K1470 resolved multistart, but Table 1 footnote says it is still open

**Locations**: `body.tex:86-91`, `body.tex:646-658`, `body.tex:1337-1344`

The abstract and conclusion state that a pooled-MLE multistart audit establishes the US > JP > TW ordering is preserved. Table 1 footnote simultaneously says whether the main three-market estimates and ordering survive matched 100-multistart re-estimation is "an open verification item."

This is internally inconsistent. K1470 exists and reports `ordering_check.ordering_preserved=true`, with refined order US > JP > TW. The table footnote is now stale, or the abstract/conclusion are overclaiming. Both cannot remain.

**Required fix**: rewrite Table 1 footnote around K1470. It should distinguish canonical single-init estimates from K1470 refined estimates, and state exactly which numbers remain canonical in the table.

### S3. The new panel uses conflicting market counts and sample sizes

**Locations**: `body.tex:76-79`, `body.tex:228-231`, `body.tex:861-869`, `body.tex:899-900`, `body.tex:1030`, `body.tex:1322-1325`

The manuscript alternates among:
- "13-market institutional panel, N=172" while listing only 12 markets and omitting AU.
- "12-market panel" in §6.6 while later using K1216c final Spearman `N=13`.
- K1172 evidence: 12 markets, 172 stocks.
- K1207 evidence: 12 markets, 182 stocks, includes AU sector table.
- K1216c final Spearman: 13 markets including AU, but CA/HK/KR remain canonical.

This is a serious synthesis error, not a typo. The paper currently combines different experiment universes as if they were one panel.

**Required fix**: introduce a short "panel provenance" table before §6.6:

| Evidence block | Markets | Stock N | Purpose |
|---|---:|---:|---|
| K1172 | 12 | 172 | baseline institutional ladder |
| K1207 | 12 | 182 | sector-FE decomposition |
| K1216c | 13 | market-level | multistart-corrected Spearman |
| K1470 | 3 | 91 | headline TW/US/JP multistart check |

Then use those labels consistently instead of "the 13-market panel" everywhere.

### S4. Internal workflow language remains in reader-facing prose

**Locations**: `body.tex:1027`, `body.tex:1076-1083`, figure captions at `body.tex:1163-1165`

Examples printed into the PDF include "FINAL", "Paper 2 commits to...", and "all future extensions ... must follow..." These read like internal project-control notes, not journal prose.

**Required fix**: translate governance/status language into academic prose. Example: replace "Paper 2 commits to..." with "The evidence supports three mechanisms..." and move operational mandates to review notes, not the article.

## HIGH Findings

### H1. Contribution count is now too broad for one paper

**Locations**: `body.tex:201-252`, `body.tex:1076-1083`

The introduction now lists five contribution strands plus a later "three structural drivers + methodological contribution" declaration. This violates the project finance-paper-quality rule that a JBF-style paper should carry 2-3 core contributions.

**Impact**: reviewers may conclude the paper is a bundle of post-hoc experiments rather than one focused contribution.

**Suggested fix**: collapse to three claims:
1. Three-market EAV sign and magnitude ordering.
2. Cross-market mechanisms with clearly delimited panel provenance.
3. Multistart diagnostic as a methodological caution, not a coequal empirical contribution unless the paper is reframed around estimation pathology.

### H2. Reproduce gate is GREEN but undercovers the revised manuscript

**Location**: `reproduce.py`, `reproduce_report.json`

`reproduce.py` checks 20 cells: Table 1 headline, placebo, and K1149 factor absorption. It does not bind:
- summary statistics table,
- K1172/K1207/K1216c/K1470 panel claims,
- figures 5A-5E,
- the multistart LR table.

**Suggested fix**: extend `reproduce.py` or create `reproduce_panel.py` for the new §6.6 / figures. Until then, do not call the full manuscript reproduce-verified.

### H3. Multistart terminology mixes different estimators

**Locations**: `body.tex:86-91`, `body.tex:932-938`, `body.tex:1116-1146`, `body.tex:1337-1344`

K1470's headline three-market multistart and K1216c's joint pooled-MLE multistart are not the same evidence object. K1470 reports TW as `STABLE/FLAT_RIDGE` with LR=1.43, while the §6.6 table reports TW as `FRAGILE` with LR=587.78 under the K1216c joint pooled spec.

**Required fix**: name the estimator/specification whenever reporting a multistart result:
- "headline three-market BCD-style spec (K1470)"
- "K1216c joint shared-MIDAS + stock-FE-GJR small-S spec"

Without that distinction, the TW stable vs fragile findings look contradictory.

### H4. Model notation ambiguity from v1 persists

**Locations**: `body.tex:280-321`, `body.tex:357-367`

Equation (3) defines `\tau_t` but includes `EAV_{i,t-1}`. A factor depending on firm `i` should be written `\tau_{i,t}` or the notation must explicitly explain it is a common coefficient applied to firm-time covariates. Also, `m_i` stock fixed effects are mentioned in text but absent from equations and the parameter vector.

**Suggested fix**: revise equations and parameter vector before the next review.

## MEDIUM Findings

### M1. Summary-statistics table is outside reproduce scope and still blank

**Location**: `body.tex:479-503`

The blank cells are already captured as S1, but the method issue is separate: summary statistics need a stable generator and source binding. Do not manually fill this table.

### M2. Cross-platform LaTeX dependency remains fragile

**Location**: `body.tex:13-15`

The paper uses `xeCJK` and `PingFang TC`. It compiles on this macOS host but may fail on Linux/journal systems. Since the manuscript is English and now compliance-clean, remove CJK packages or use a portable fallback only in local builds.

### M3. Overfull tables and captions need layout cleanup

The final LaTeX run reports overfull boxes, including:
- lines 944-953: 57.8pt,
- lines 1226-1264: 63.0pt,
- lines 490-505: 26.0pt.

These are not methodological blockers, but they are visible typesetting risks.

### M4. Bootstrap B=150 remains underpowered for percentile CIs

**Location**: `body.tex:384-396`

For 2.5/97.5 percentile confidence intervals, B=150 is light. If compute cost prevents B=999, state this as a limitation and show sensitivity for the headline estimates.

### M5. OOS DM test citation and naming should reflect DM-HLN implementation

**Locations**: `body.tex:796`, `experiments/k1148_d2/README.md`, `experiments/k1149/README.md`

The manuscript cites Diebold-Mariano only, while the experiment README describes "per-stock DM-HLN". Citation report covers this; academically, the text should either call it DM-HLN and cite Harvey-Leybourne-Newbold (1997), or remove the HLN wording from the evidence chain.

## What Improved Since v1

- `references.bib` now exists.
- `engle_rangel2008` key typo is fixed.
- `garch_x_vix_paper` placeholder is removed.
- `k1213_convergence_lesson` is no longer a citation key.
- Table 2 dropout minimums match the v1-flagged values: US `1.82e-4`, `20.27`; JP `18.22`.
- `body.tex` compiles with BibTeX on this host.
- Paper compliance scan finds no AI/LLM/VolPred/K-id violations in TeX source.

## Action Plan for v3

1. Remove printed placeholders by populating summary stats and Appendix A, or explicitly mark them as unavailable limitations outside the final PDF.
2. Reconcile K1470 multistart status with Table 1 footnote.
3. Add a panel-provenance table and standardize market/N language.
4. Remove internal workflow/status language from prose and figure captions.
5. Extend reproduce coverage to §6.6 / K1172 / K1207 / K1216c / K1470.
6. Fix notation: `\tau_t` vs `\tau_{i,t}` and stock fixed effects.
7. Apply citation fixes from `citation_check.md`.

**Predicted status after fixes**: if S1-S4 and H1-H4 are fixed, the paper can move from major revision to a focused submission-readiness review. It is not ready for arXiv or journal submission in v2.
