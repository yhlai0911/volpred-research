# Citation/Reference Verification — leverage-direction v2

**Verdict**: FAIL_MAJOR_REVISION
**arXiv decision**: HOLD
**Date**: 2026-07-01

## Verdict rationale

Stage 1 substantially improved the main manuscript's central framing: the abstract, introduction, and conclusion now state that gold's inverted leverage is regime-dependent rather than unconditional, and the main LaTeX citation keys in `main.tex`/`body.tex` resolve against the main `thebibliography`.

The package still cannot pass citation/reference verification. The standalone supplement has unresolved citation keys; the submission package and highlights retain stale pre-reframing claims; the cover letter still includes suggested referees despite the JBF rule profile/user instruction; and several high-stakes attributed claims remain too strong relative to the cited literature. The paper should not be posted to arXiv or sent to JBF until these are fixed.

Spot-checked external sources used sparingly:
- Chang et al. (2021) explicitly links gold volatility regimes, inverted asymmetry, safe-haven behavior, contagion, and flights: https://ideas.repec.org/a/eee/pacfin/v67y2021ics0927538x21000299.html
- Baur (2012) directly studies asymmetric volatility in gold and reports inverted asymmetry: https://research-repository.uwa.edu.au/en/publications/asymmetric-volatility-in-the-gold-market
- Bekaert and Wu (2000) frames equity asymmetric volatility as involving leverage and volatility-feedback explanations: https://academic.oup.com/rfs/article-abstract/13/1/1/1584172
- Figlewski and Wang's leverage-effect paper questions whether the effect is pure financial leverage: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=256109
- Hood and Raughtigan is now listed as Journal of Portfolio Management 52(1), 100-121, DOI 10.3905/jpm.2025.1.764: https://www.pm-research.com/content/iijpormgmt/52/1/100
- Moreira and Muir (2017) supports inverse-volatility scaling and the "volatility not offset by expected returns" mechanism: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2659431
- Patton (2011) supports robust forecast comparison with conditionally unbiased imperfect volatility proxies: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=932890
- Bayer and Dimitriadis (2022) introduces ES regression backtests, but I did not verify the manuscript's specific `N < 25` power threshold from the accessible abstract: https://academic.oup.com/jfec/article/20/3/437/5912157

## Findings

### High (misattribution / claim-source mismatch / broken cite key)

- [supplementary.tex:33; supplementary_content.tex:66,72,77,83,90,96,133,150] The standalone supplement has broken citation keys. `supplementary_content.tex` cites `patton2011`, `fisslerziegel2016`, `acerbiszekely2014`, `bayerdimitriadis2022`, `henriksson1981`, `treynor1966`, and `engle2006`, but `supplementary.tex`'s bibliography contains only `araya2024`, `bali2016`, `batten2010`, `black1976`, `bollerslev1986`, `chang2021`, `chevallier2017`, `harvey2016`, and `hood2025`. Fix by sharing the main bibliography or adding all cited supplement entries to `supplementary.tex`.

- [highlights.txt:7; submission_package.md:29,42; supplementary_content.tex:31,33] The submission highlights still sell a time-zone momentum result as a main contribution, while the reframed manuscript now has one central leverage-direction contribution and two empirical manifestations. The supplement itself says the close-to-close alpha is mostly not capturable and should not be interpreted as achievable returns. Delete the time-zone highlight/package claim or move the manuscript back to a three-contribution structure with full support.

- [submission_package.md:38; main.tex:49; body.tex:11,136; tables_main.tex:24,34] `submission_package.md` still says the first highlight is "Gold exhibits regime-dependent inverted leverage (t = -5.79, 93% negative)." That is the superseded estimate. The active manuscript and Table 2 report canonical GLD mean gamma `+0.002`, HAC `t = +0.15`, 67% negative windows, with the old `t=-5.79` only as an erratum/vintage note. Update the package memo so it does not reintroduce the falsified old result.

- [cover_letter.tex:37-43; submission_package.md:31] The cover letter still suggests three potential referees. The prior JBF gate records that the local JBF profile does not request suggested reviewers, and the user specifically flagged that JBF does not accept suggested reviewers. Remove the suggested-referee paragraph and the package row advertising it.

- [body.tex:136] The sentence "Conditional on regime, the inverted-leverage channel ... has not been documented in the prior GARCH literature as a systematic phenomenon" is still too broad. Chang et al. (2021) directly studies gold volatility regimes and inverted asymmetry, and Baur (2012) directly studies inverted asymmetric volatility in gold. Fix by narrowing novelty to "not used as a cross-asset model-selection / VT-mechanism diagnostic" and add Baur (2012) if the gold prior literature remains central.

- [main.tex:49; body.tex:15,366,370,372,437; tables_supplement.tex:101-116] The headline VT mechanism numbers in the reframed story are not supported by the supplied supplement table. The abstract/body claim equity-type `rho = 0.886, p = 0.019, N = 6`, OOS `rho = 0.821`, and heterogeneous `rho = -0.448, p = 0.14, N = 12`; the available `tab:gamma-mechanism` instead reports the older seven-asset `rho = 1.000` and Pearson `r = 0.993`. Add the updated domain-restricted/OOS correlation table to the supplement, or remove "Supplementary table and figure report" language and demote these numbers until a visible table supports them.

### Medium (weak citation / missing attribution)

- [body.tex:25,328; main.tex:49] Equity leverage is still framed as balance-sheet amplification and "mechanically" rising debt-to-equity risk. Bekaert and Wu (2000) and Figlewski and Wang (2000/2001) show that volatility feedback/down-market effects are important alternatives to pure capital-structure leverage. Add these references and revise to "consistent with leverage and volatility-feedback mechanisms."

- [main.tex:191-192,239-240] Recent VT references are stale. Hood and Raughtigan should no longer be `forthcoming`; current metadata is JPM 52(1), 100-121. Xu should be updated from `Critical Finance Review, forthcoming` with no DOI to the current publisher metadata if retained.

- [body.tex:39] The Yahoo Finance justification is weakly attributed. Bali et al. (2016) is an asset-pricing text, not a validation of Yahoo Finance as a data vendor; Moreira-Muir/Cederburg validate overlapping return moments only indirectly. Reword as a data-source choice and cite the replication/data appendix for Bloomberg/VIX spot checks.

- [body.tex:316; body.tex:433] The 2026 Iran/Hormuz event narrative is externally factual but uncited. Add an archival news/market source for the Feb. 28 strikes, Strait closure/blockade, and oil-supply share, while keeping computed market statistics separate from sourced geopolitical facts.

- [supplementary_content.tex:77,83] The specific ES-backtesting power statement "N < 25" is not verified from the accessible Bayer-Dimitriadis abstract. Either cite the exact simulation/table from the paper, or present the threshold as the manuscript's own heuristic.

- [body.tex:417; supplementary_content.tex:118-126,150] HAR, DCC, MIDAS/MS/CARR, copula, and MEM model-family claims still lack full canonical attribution. MEM has Engle and Gallo (2006), but HAR lacks Corsi (2009), DCC lacks Engle (2002), and the other families are tabled without citations. Add canonical citations or remove named model-family evidence from headline claims.

- [body.tex:232,253; main.tex:49] Extended-sample VT drawdown correlations (`rho = 0.83`, `N = 14`) are stated as reported in the online supplement, but I did not find a corresponding table in the supplied supplement files. Add the table or qualify as an unreported extension.

### Low

- [main.tex:74-242] Main bibliography contains uncited entries in the inspected LaTeX files: `araya2024`, `bucci2020`, `campbell2017`, `engle2004`, `engleGhyselsSohn2013`, `kim2019`, `longin2001`, `mcneil2015`, and `pattonSheppard2015`. Remove them unless they are needed for live claims.

- [citation_check.md:1-246] `citation_check.md` is stale relative to the Stage 1 manuscript. It still discusses old orphan keys (`corsi2009`, `engle2002`, `bollerslev1994`) that are no longer in the active main bibliography, while missing the new supplement-bibliography breakage.

- [submission_package.md:3,73-88] The package memo still marks the paper `READY_FOR_UPLOAD` and says no further edits are required. This conflicts with the current v2 verification result and should be changed after manuscript fixes.

## Convergence vs prior FAIL_MAJOR_REVISION

- Resolved: The main manuscript no longer makes an unconditional gold-inverted-leverage claim as its central evidence. The abstract, introduction, and conclusion now report GLD `gamma = +0.002`, HAC `t = +0.15`, and treat inversion as regime-dependent. The stale cover-letter "three contributions" paragraph was also removed.

- Remaining: Gold prior-literature novelty is still overclaimed at `body.tex:136`; equity leverage mechanism still lacks Bekaert-Wu/Figlewski-Wang style caveats; Hood/Xu metadata remains stale; Yahoo Finance/data-source support remains weak; Iran/Hormuz facts remain uncited; package-level JBF compliance remains unresolved.

- New: The standalone supplement now has unresolved citation keys because its bibliography was not updated with the new `supplementary_content.tex` citations. The reframed VT mechanism correlations (`rho = 0.886`, `rho = 0.821`, `rho = -0.448`) are not backed by the visible supplement table, which still reports the old seven-asset `rho = 1.000`. The highlights/submission package still reintroduce both the time-zone side contribution and the obsolete GLD `t=-5.79` result.
