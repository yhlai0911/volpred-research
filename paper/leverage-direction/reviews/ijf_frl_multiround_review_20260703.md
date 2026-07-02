# IJF/FRL Multiround Review Gate

Date: 2026-07-03  
Task: `paper_review_leverage_direction_honest_null_reframe_multiround_20260703`  
Inputs reviewed:

- `paper/leverage-direction/main_v_ijf.tex`
- `paper/leverage-direction/body_v_ijf.tex`
- `paper/leverage-direction/highlights_v_ijf.tex`
- `paper/leverage-direction/tables_main.tex`
- `paper/leverage-direction/title_page_v_ijf.tex`
- Local bibliography embedded in `main_v_ijf.tex`

Review passes run:

- LaTeX academic-method review
- Citation-verification review
- IJF/FRL journal gate review
- Mechanical checks: LaTeX compile, cite-key/bibitem consistency, abstract/highlight limits, DOI status spot checks

## Overall Verdict

**FAIL_DO_NOT_ADVANCE.**

The honest-null reframing is directionally much improved, but the package is not yet submission-ready for IJF and is not suitable as the current manuscript for FRL. The central research narrative can still be made publishable as an IJF method-diagnosis/null-result paper, but the current draft leaves major auditability, citation, and journal-compliance gaps.

The highest-risk issue for this round is residual confirmatory language around the allocation/crisis-period evidence. The forecast-level null is mostly stated honestly, but several phrases still let a skeptical reviewer read the asymmetric term as delivering a positive conditional allocation edge.

## Pass Checks

- `latexmk -xelatex -interaction=nonstopmode -halt-on-error main_v_ijf.tex` completed successfully and produced a 36-page PDF.
- Abstract length is within the IJF 100--150 word target by independent word-count checks.
- Highlights have five bullets and each bullet is under the 85-character Elsevier limit.
- Citation-key mechanics passed: 39 in-text cite keys and 39 `\bibitem`s, with no missing cite keys and no orphan bibitems in the reviewed files.
- The blinded main manuscript is mostly anonymized; author details are isolated on the title-page file.

These are mechanical passes only. They do not clear the manuscript for submission.

## Must-Fix Findings

### 1. Residual Positive Allocation-Edge Language

Location: `body_v_ijf.tex:305`

> "The asymmetry term therefore does earn its keep"

Why this fails: this reads as a positive payoff claim for the asymmetric term. The honest result is that no asset shows statistically significant OOS forecast superiority after multiple-testing correction, and the allocation evidence is not cleanly pre-specified or multiplicity-adjusted.

Minimal rewrite:

> "In this crisis subperiod, the asymmetric specification is suggestive of a lower tail-loss allocation pattern, but this evidence is not a statistically corrected general allocation edge."

Location: `body_v_ijf.tex:342`

> "a genuine crisis-period risk-management feature"

Why this fails: "genuine" is confirmatory. Given one COVID-period subperiod and unclear multiplicity discipline, the sentence overstates the allocation result.

Minimal rewrite:

> "a suggestive crisis-period risk-management pattern that should be treated as diagnostic rather than as a general allocation edge."

Location: `body_v_ijf.tex:314`

> "the sign of gamma also predicts whether VT re-weighting behaves as trend-following or contrarian"

Why this fails: "predicts" overstates an N=6 diagnostic association and risks reviving the prior unsupported gamma-sign classification story.

Minimal rewrite:

> "the sign of gamma is associated with whether VT re-weighting behaves as trend-following or contrarian in this small cross-asset diagnostic sample."

### 2. Sample and Window Coherence Is Not Yet Auditable

Locations:

- `body_v_ijf.tex:214`
- `tables_main.tex:24`
- `body_v_ijf.tex:312`
- `tables_main.tex:128`

Representative conflict:

> "To keep every table and figure on a common footing..."

versus table/section language using 2010--2026 gamma evidence, a full 2005--2026 regime sample, and native allocation windows such as SPY 2014--2026.

Why this fails: the manuscript promises a single canonical partition, but key forecast, gamma, regime, and allocation evidence use different windows. That can be fine if labelled, but not if the paper claims common footing.

Minimal rewrite/action:

- Add a sample-map table listing each evidence object, asset set, start/end dates, OOS split, validation period, and whether the result is primary or robustness.
- Replace "every table and figure" with "the primary forecast-comparison tables" or another narrower phrase.
- Label native-window allocation evidence as such, or make common-window allocation the primary allocation result.

### 3. Primary QLIKE Table Does Not Match the Claimed Asset/Window Scope

Locations:

- `body_v_ijf.tex:290`
- `tables_main.tex:50-62`

Representative text:

> "evaluated on the main OOS window (2023--2024) and the validation window (2025)"

Why this fails: Table 3 has no SLV rows and no BTC 2025 row, despite the seven-primary-asset and validation-window framing.

Minimal rewrite/action:

- Add the missing SLV and BTC validation rows if they exist.
- Otherwise explicitly state the exclusions in the caption and body, and avoid "seven primary assets" language for that table.

### 4. Multiple-Testing Correction Is Not Reproducible From the Draft

Locations:

- `body_v_ijf.tex:293`
- `tables_main.tex:44`

Representative text:

> "disciplined with a Harvey-style multiple-testing correction"

and

> "Stars denote unadjusted 5% DM tests"

Why this fails: the decisive result is that no model has adjusted OOS superiority, but the draft does not make the correction auditable from the table. "Harvey-style" is underspecified.

Minimal rewrite/action:

- State the exact correction, family size, test statistic, benchmark family, and adjusted critical values or adjusted p-values.
- Add a column or companion table for Harvey-adjusted p-values.
- Preserve the honest wording that unadjusted stars do not imply adjusted superiority.

### 5. Robustness Evidence Is Treated Too Much Like a Co-Equal Pillar

Locations:

- `body_v_ijf.tex:303`
- `body_v_ijf.tex:335`
- `body_v_ijf.tex:349`

Representative text:

> "12/VIX ... across seven OOS periods (2009--2025)"

and

> "were not all pre-registered"

Why this fails: robustness results that were not fully pre-registered should not be used as co-equal support for the main empirical conclusion. They can corroborate the null, but should be labelled as extensions or robustness diagnostics.

Minimal rewrite/action:

- Mark 12/VIX, EWMA, and HAR results as corroborating or exploratory unless a pre-analysis protocol is documented.
- Keep the main null anchored in the frozen model-selection/OOS forecast protocol.

### 6. Citation Readiness Fails

Location: `body_v_ijf.tex:269`

> "Following \citet{moreira2017}, the volatility-managed weight is ... w_t = sigma_target / sigma_hat_t"

Why this fails: Moreira--Muir's canonical volatility-managed portfolio is inverse conditional variance scaling, not the inverse-volatility target-vol rule used here.

Minimal rewrite:

> "Adapting the volatility-targeting literature, we implement an inverse-volatility target-volatility weight..."

Location: `body_v_ijf.tex:303` and `main_v_ijf.tex:139`

> "equivalent to the VIX-managed portfolio of \citealt{bozovic2024}"

Why this fails: exact-title/DOI checks did not return an authoritative source for the cited Bozovic reference. Because this claim anchors the 12/VIX comparison, it must be verified or removed.

Minimal rewrite/action:

- Provide the source PDF/DOI and confirm metadata.
- If unavailable, remove the equivalence claim and cite established, verifiable volatility-targeting/VIX literature.

Location: `body_v_ijf.tex:342` and bibliography entries for `hood2025`, `nelson2025`, and `xu2024`

Why this fails: these references were not verifiable in this audit; `xu2024` also conflicts with archived metadata on author initial/name.

Minimal rewrite/action:

- Confirm these references with source files/DOIs, or replace them with established references.
- Do not rely on unverifiable forthcoming/working-paper citations for a key interpretive claim.

Other citation fixes:

- `body_v_ijf.tex:307`: add Treynor and Mazuy (1966) and the intended Merton-ratio source, or remove the named methods.
- `body_v_ijf.tex:320`: add Engle and Manganelli (2004) for dynamic-quantile tests, or avoid naming DQ.
- `body_v_ijf.tex:337`: add Corsi (2009) for HAR, or move the claim to a properly cited supplement.
- `body_v_ijf.tex:225`: soften the Francq-QMLE/mean-misspecification claim unless a direct supporting citation is supplied.
- `body_v_ijf.tex:230`: soften the Hwang sample-size threshold unless the cited source explicitly makes a 500-observation recommendation.

### 7. Title Page and Submission Declarations Are Not Ready

Locations:

- `main_v_ijf.tex:65`
- `title_page_v_ijf.tex:18-19`
- `title_page_v_ijf.tex:40`

Issues:

- The main manuscript title and title-page title disagree.
- The title page still contains a draft disclosure placeholder requiring author sign-off.
- The disclosure text names tools/vendors and is not ready for journal submission as-is.

Minimal rewrite/action:

- Make the title-page title exactly match the main IJF manuscript title.
- Replace the placeholder with an author-approved final declaration in the required declarations location, or remove it if the journal portal handles it separately.
- Confirm that the submission package has author name "Yi-Hao Lai" only and no non-required branding/tool names.

### 8. IJF Data/Code Availability Package Is Not Yet Submission-Ready

Locations:

- `title_page_v_ijf.tex:32`
- `tables_main.tex:128`

Representative text:

> "replication package ... accompanies"

and

> "see REPLICATION.md"

Why this fails: the reviewed package does not yet provide a formal data/code availability statement with anonymous repository/DOI, environment, seeds, exact scripts, and a table/figure regeneration map.

Minimal rewrite/action:

- Add a Data and Code Availability section.
- Confirm the replication package is self-contained and anonymized.
- Map each table/figure to the exact script and output file that generates it.

### 9. FRL Gate Fails for the Current Manuscript

Locations:

- `main_v_ijf.tex:99`
- `body_v_ijf.tex:191`
- `body_v_ijf.tex:303`
- `body_v_ijf.tex:319`
- `body_v_ijf.tex:337`

Why this fails:

- `texcount -merge` gives approximately 5,696 text words and 6,262 total words, far above FRL's short-letter format.
- The manuscript draws on four literatures and adds VIX, VaR, HAR, and allocation layers. That is a full IJF paper, not a single-result finance letter.

Minimal rewrite/action:

- Treat IJF as the primary target for this manuscript.
- If FRL is desired, create a separate <=2500-word letter around one result only, likely the absence of robust OOS GJR superiority after correction.

### 10. Minor Formatting and Reference Issues

Locations:

- `tables_main.tex:92`
- `tables_main.tex:128`

Issues:

- The table preamble uses a vertical rule: `lccccccc|r`.
- The VT table note points to `sec:var_compliance` when it appears to discuss allocation.
- The note says "four of five" Sharpe comparisons despite the displayed table showing five positive deltas; either the count or the exclusion rule must be clarified.

Minimal rewrite/action:

- Remove the vertical rule and use booktabs spacing only.
- Point the VT note to the allocation section.
- Reconcile the "four of five" statement with the table.

## Contribution Gate

Conditional IJF contribution: **possible, but not cleared.**

The paper can plausibly contribute to IJF if framed as a pre-specified, cross-asset diagnosis of when asymmetric GARCH complexity fails to deliver corrected OOS forecast gains. That is a forecasting-method evaluation contribution, especially if the paper transparently links forecast scores to allocation and risk diagnostics while reporting the null.

The current version does not clear the gate because:

- The main null is not fully auditable without adjusted p-values/family details.
- The evidence objects use multiple windows without a clear sample map.
- Residual allocation/crisis wording still implies an affirmative edge.
- Several citations and submission-package elements are not ready.

FRL contribution: **not this manuscript.** A separate, much shorter paper would be needed.

## Required Next Actions Before Any Submission

1. Do not run the paper-publication/update workflow for this draft yet.
2. Remove or demote the residual positive allocation-edge language.
3. Add an auditable multiple-testing table or adjusted-p-value column.
4. Add a sample/window map for every major evidence object.
5. Resolve missing rows/exclusions in the primary QLIKE table.
6. Verify or replace the questionable citations.
7. Synchronize the title page and finalize declarations.
8. Add a formal data/code availability statement and replication map.

