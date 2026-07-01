# Stage 1 Rerun Review - main/body/tables package

Date: 2026-07-01 11:50 Asia/Taipei

Scope:

- `paper/leverage-direction/main.tex`
- `paper/leverage-direction/body.tex`
- `paper/leverage-direction/tables_main.tex`
- `paper/leverage-direction/README.md`

No manuscript source files were edited in this pass.

## Pass 1 - LaTeX Academic Reviewer

verdict: FAIL

Top blockers:

- `tables_main.tex:30,50` and `README.md:4,43,47-57` expose internal experiment identifiers, source paths, status symbols, and review-history metadata. These must not be present in a submitted source/package.
- `body.tex:36,44,122` and `tables_main.tex:5` use inconsistent sample-period definitions: 2017-March 2026, 2017-December 2025, and 2017-2025.
- `body.tex:13,145,185` overstates Table 3 as all asset-period combinations, while `tables_main.tex:42-64` has 11 rows and omits SLV and BTC 2025.
- `body.tex:108-114,228,403` makes VIX timing explicit but leaves GARCH VT trading timing ambiguous; add an explicit no-lookahead equation such as `R^{VT}_t = w_{t-1} r_t`.
- `tables_main.tex:22-24` uses an audit/vintage narrative in a table caption; move provenance to replication documentation.
- `tables_main.tex:67-85` defines `tab:var` but the table is not cited in the inspected main manuscript.
- `body.tex:79-83,421` uses DM testing without HLN discussion while acknowledging 110+ experiments and in-sample thresholds.

Required revisions:

1. Clean all internal identifiers, source comments, status symbols, and review-history text from the submission package.
2. Canonicalize sample periods, asset counts, and table scope.
3. Add explicit no-lookahead VT timing notation.
4. Fix Table 3 scope or add missing rows.
5. Cite or remove uncited tables.
6. Replace audit-style captions with publication-style captions.
7. Strengthen multiple-testing and forecast-comparison inference.

## Pass 2 - Citation Verifier

verdict: CONDITIONAL_PASS

missing_refs: none

bib_but_unused:

- `acerbiszekely2014`
- `araya2024`
- `bayerdimitriadis2022`
- `bucci2020`
- `campbell2017`
- `engle2004`
- `engleGhyselsSohn2013`
- `fisslerziegel2016`
- `kim2019`
- `longin2001`
- `mcneil2015`
- `pattonSheppard2015`
- `treynor1966`

Suspect or stale citation items:

- `xu2024`: main bibliography lists Critical Finance Review forthcoming with no DOI; Crossref currently returns SSRN DOI `10.2139/ssrn.4778937`.
- `hood2025`: no longer forthcoming; Crossref reports Journal of Portfolio Management 52(1), 100-121, DOI `10.3905/jpm.2025.1.764`.
- HAR/HAR-ABS discussion lacks Corsi (2009), DOI `10.1093/jjfinec/nbp001`.
- DM testing lacks Harvey-Leybourne-Newbold (1997) citation or justification for not applying the correction, DOI `10.1016/S0169-2070(96)00719-4`.
- Realized-volatility and 5-minute proxy discussion lacks Andersen et al. (2003), DOI `10.1111/1468-0262.00418`.
- `nelson2025` exists as SSRN posted content, DOI `10.2139/ssrn.5931154`; align title casing and metadata.

## Pass 3 - JBF Submission Gate

verdict: NEEDS_REVISION

identification_soundness: FRAGILE

Contributions that could survive a revision:

- GJR gamma sign as an economically interpretable classification signal across equity, gold, and bond mechanisms.
- Gamma-based asymmetric model selection only when current positive asymmetry is statistically meaningful.
- VT's directional channel is gamma-dependent within equity-type assets, while drawdown protection is mainly variance management.

Main gate blockers:

- Submission hygiene fails through internal identifiers, experiment paths, status symbols, and audit metadata in source/context files.
- The core OOS classification evidence is only `N=6` and partly calibrated on the same empirical family.
- Gold is central, but unconditional gamma is statistically zero; the regime decomposition needs a main table with pre-specified regime definitions.
- VT Table 6 uses asset-specific windows and notes only 6/20 uniform-window cells match, which is not submission-grade.
- The paper still risks reading as a GARCH/VT horse race rather than a JBF finance contribution.
- Novelty versus Moreira-Muir, Harvey-Rattray-Van Hemert, Hood-Raughtigan, and Wachter is underdeveloped.
- The QLIKE scale is equivalent but nonstandard; reporting centered Patton QLIKE would reduce direction-error risk.
- The 2026 Iran/Hormuz event narrative needs formal sourcing or relocation to the supplement.

JBF format gaps:

- Abstract is about 288 words; target is <=200.
- Keywords count is 9; reduce to 3-6.
- Submitted source/package is not clean of internal identifiers.
- Supplement-dependent references require bundled supplement and resolved aux/PDF.
- Tables should not contain audit or replication-history narrative.

## Final Synthesis

overall_verdict: MAJOR_REVISION_REQUIRED

arxiv_gate_recommendation: DO_NOT_POST_YET

Top actions:

1. Clean the submission package completely.
2. Rebuild the empirical core around uniform samples/windows, full asset-period coverage, and explicit no-lookahead VT timing.
3. Move the main identification evidence into the paper: gold regime decomposition, 14/26-asset validation, and corrected inference.

One-line synthesis: strong idea, but submission hygiene and identification fragility remain below JBF and arXiv-ready standards.
