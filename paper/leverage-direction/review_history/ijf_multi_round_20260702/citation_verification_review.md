# Citation Verification Review — IJF Version

**Verdict**: **CONDITIONAL_PASS**  
**Scope**: body citations and bibliography in `main_v_ijf.tex` / `body_v_ijf.tex`.

## Mechanical Citation Audit

- Unique cite keys in `body_v_ijf.tex`: 39.
- `\bibitem`s in `main_v_ijf.tex`: 39.
- Missing bibliography entries: none.
- Orphan bibliography entries: none.
- `latexmk` log: no undefined citations.
- Bibliography order: alphabetic by first author surname.
- Reference style: author-date via `natbib` + `apalike`.

## Web Spot Checks

The following external spot checks were performed because the review task specifically asked for citation verification:

- Hood and Raughtigan: SSRN record exists for *Volatility Targeting Is Trendy: How Trend Following Explains Alpha in Volatility-Managed Strategies*, with authors Benjamin Hood and Cameron Raughtigan and SSRN DOI `10.2139/ssrn.4773781`. The abstract supports the manuscript's claim that the paper links volatility targeting alpha to trend-following exposure through the leverage effect. Source: <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4773781>.
- Xu: Critical Finance Review forthcoming manuscript exists for *Improving Volatility-Managed Portfolios in Real Time*. The abstract supports the manuscript's use of it as real-time volatility-management literature. Source: <https://cfr.ivo-welch.info/forthcoming/papers/xu2024improving.pdf>.
- Nelson: SSRN record exists for *Portfolio Construction Under Correlation Breakdowns and Tail Risk*, with DOI `10.2139/ssrn.5931154`. The abstract supports the paper's use as transparent/non-predictive risk-control context. Source: <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5931154>.
- IJF scope and requirements were checked against IIF/Elsevier pages. Sources: <https://forecasters.org/ijf/>, <https://forecasters.org/ijf/authors/>, <https://www.elsevier.com/researcher/author/tools-and-resources/highlights>.

## Issues To Fix Before Submission

### C1. Recent/forthcoming reference statuses need final publisher verification

`hood2025` is listed as Journal of Portfolio Management forthcoming with DOI `10.3905/jpm.2025.1.764`. I verified the SSRN version and content claim, but did not independently resolve the JPM DOI from a publisher article page in this run. Keep the SSRN DOI as fallback or verify the JPM DOI before submission.

`xu2024` is listed as Critical Finance Review forthcoming. The manuscript date is 2024; some public profile/search records describe the work as 2025 forthcoming. Verify the intended reference year/status before final submission.

### C2. Software/data references are acceptable but should be source-package consistent

`sheppard2023` cites the `arch` package as software. This is acceptable, but the replication package should pin the actual version used by the frozen run and expose it in the external replication README.

## Non-Issues

- No fabricated references were detected in the 39-key body bibliography.
- No missing DOI was detected for core journal articles where a DOI is expected.
- The body uses `\citet` / `\citep` consistently enough that natbib will handle multi-author "et al." rendering.

## Bottom Line

Citation state is conditionally acceptable. It is not the reason for the overall FAIL; the blocking issues are methodological/package readiness, not missing citations.
