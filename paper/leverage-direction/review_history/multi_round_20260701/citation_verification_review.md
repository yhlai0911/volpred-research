# Citation Verification Review — 2026-07-01
Verdict: FAIL_MAJOR_REVISION
High findings: 3
Medium findings: 6

Scope: directly inspected `paper/leverage-direction/main.tex`, `paper/leverage-direction/body.tex`, `paper/leverage-direction/tables_main.tex`, and `paper/leverage-direction/review_history/codex_contribution_gate_20260701.md`. I also inspected `cover_letter.tex` only to confirm stale cover-letter issues flagged by the gate review. This was a targeted citation/reference review, not a full DOI audit.

## High Findings

### H1. Gold/inverted-leverage novelty is still overclaimed relative to prior literature

Evidence:
- `body.tex:7` says Chevallier and Ielpo (2017) document inverted asymmetric volatility in gold and commodities, then claims the implications have not been systematically explored.
- `body.tex:23` cites Chevallier (2017), Batten (2010), and Chang (2021) for non-equity sign reversal.
- `body.tex:134` says that, conditional on regime, the inverted-leverage channel "has not been documented in the prior GARCH literature as a systematic phenomenon."
- `body.tex:359` states "Our finding that gold exhibits inverted leverage" even though `body.tex:134` and `tables_main.tex:34` say GLD's unconditional mean gamma is insignificant (`+0.002`, HAC `t=+0.15`).
- `main.tex:103-107` already includes Chang et al. (2021) and Chevallier and Ielpo (2017), both directly adjacent to inverted/regime commodity asymmetry.

Why this matters for JBF:
The manuscript cannot imply that regime-dependent inverted gold asymmetry itself is undocumented when Chang et al. (2021) explicitly concerns gold volatility regimes and inverted asymmetry, and Baur (2012) is a direct missing gold-asymmetric-volatility reference. The credible novelty is the use of leverage direction for model selection and VT mechanism interpretation, not discovery of inverted gold leverage.

Correction instructions:
- Replace "has not been documented in the prior GARCH literature as a systematic phenomenon" with a narrower claim such as: "has not, to our knowledge, been used as a cross-asset model-selection and allocation diagnostic."
- Change `body.tex:359` and similar wording to "Gold's leverage direction is regime-dependent" rather than "gold exhibits inverted leverage" without qualification.
- Add and cite Baur (2012), "Asymmetric Volatility in the Gold Market," Journal of Alternative Investments, 14(4), 26-38, DOI `10.3905/jai.2012.14.4.026`, near `body.tex:7`, `body.tex:23`, and `body.tex:359`.
- Use Chevallier (2017), Chang (2021), and Baur (2012) as prior-literature anchors; reserve the paper's novelty claim for taxonomy/model-selection/VT implications.

### H2. Equity leverage mechanism is cited too narrowly and overstates the capital-structure explanation

Evidence:
- `body.tex:5` says the leverage effect was first noted by Black (1976), formalized by Christie (1982), and is well documented.
- `body.tex:23` says equity leverage is "economically tied to balance-sheet amplification" and cites Black (1976), Christie (1982), and Engle and Siriwardane (2018).
- `body.tex:138` and `body.tex:359` repeat that equity declines increase debt-to-equity ratios and mechanically raise firm risk.
- Prior project reviews already flagged missing Bekaert and Wu (2000) and Figlewski and Wang (2000) (`reviews/review_r1.tex:88-91`, `reviews/citation_check_r1.md:167-170`, `reviews/review_r2.tex:147`, `reviews/review_r3.tex:194`), but the current `main.tex` bibliography still does not include either reference.

Why this matters for JBF:
JBF referees will expect the manuscript to acknowledge that the equity "leverage effect" literature includes volatility-feedback and non-pure-leverage interpretations. Citing only Black/Christie makes the mechanism sound settled and one-dimensional.

Correction instructions:
- Add Bekaert and Wu (2000), "Asymmetric Volatility and Risk in Equity Markets," Review of Financial Studies, 13(1), 1-42, DOI `10.1093/rfs/13.1.1`.
- Add Figlewski and Wang (2000/2001), "Is the 'Leverage Effect' a Leverage Effect?", SSRN/NYU working paper, DOI `10.2139/ssrn.256109`.
- Revise mechanism language to: "consistent with leverage and volatility-feedback mechanisms" rather than "mechanically" caused by debt-to-equity changes.
- Cite the two references around `body.tex:23`, `body.tex:138`, and `body.tex:359`.

### H3. Cover letter still contains an unsupported third contribution not present in the manuscript

Evidence:
- `cover_letter.tex:29` says the paper makes three contributions.
- `cover_letter.tex:33` claims a "persistent time-zone arbitrage channel" with Harvey-threshold `t`-statistics in six Asia-Pacific markets.
- Current manuscript framing says two contributions in `main.tex:39`, `body.tex:9-13`, and `body.tex:511-515`.
- The gate review already flags this as stale and unsupported (`review_history/codex_contribution_gate_20260701.md:60-66`, `:122`, `:126`, `:132`).

Why this matters for JBF:
The submission package would promise a contribution that is not developed, cited, or referenced in the body. This is a credibility and desk-reject risk even though it is outside the main `.tex` manuscript.

Correction instructions:
- Delete the third contribution paragraph from `cover_letter.tex:33`.
- Change `cover_letter.tex:29` from "three contributions" to "two contributions."
- If time-zone spillovers remain anywhere in the package, move them to a separate paper or cite a developed appendix with proper references and data.

## Medium Findings

### M1. Recent VT references are stale or incomplete

Evidence:
- `main.tex:181-182` lists Hood and Raughtigan (2025) as `Journal of Portfolio Management, forthcoming`.
- `main.tex:229-230` lists Xu (2024) as `Critical Finance Review, forthcoming` with no DOI.
- `body.tex:13`, `body.tex:377`, `body.tex:409`, and `body.tex:515` rely on Hood and Raughtigan as the anchor for the VT trend-following mechanism.
- `body.tex:25` cites Xu (2024) in the VT literature list.

Correction instructions:
- Update Hood and Raughtigan metadata to the published version: Journal of Portfolio Management, 52(1), 100-121, November 2025. Keep or verify DOI `10.3905/jpm.2025.1.764`.
- Update Xu metadata from "forthcoming" to the current publisher metadata: Critical Finance Review, 15(2), 179-207, DOI `10.1108/CFR-03-2023-2491`.
- Keep the in-text Hood claims, but avoid saying the present paper "generalizes" Hood beyond the manuscript's own domain restriction unless the sentence immediately says the mapping only holds within equity-type assets.

### M2. Bibliography has uncited entries, including references that should either be cited or removed

Evidence:
- Key audit found no undefined citation keys, but these `\bibitem` keys are not cited anywhere in `main.tex`, `body.tex`, or `tables_main.tex`: `araya2024`, `bucci2020`, `campbell2017`, `engle2004`, `engleGhyselsSohn2013`, `kim2019`, `longin2001`, `mcneil2015`, `pattonSheppard2015`.
- Visible source examples: `main.tex:64-65` Araya, `main.tex:97-98` Bucci, `main.tex:109-110` Engle/Ghysels/Sohn, `main.tex:127-128` Patton/Sheppard, `main.tex:232-233` Campbell et al.

Correction instructions:
- Remove uncited entries unless they are needed for a live claim.
- If retained, cite them where relevant: `engleGhyselsSohn2013` for GARCH-MIDAS, `pattonSheppard2015` for good/bad volatility or signed jumps, `mcneil2015` for VaR/ES risk-management foundations, and `campbell2017` only if the bond-risk discussion is actually in the text.

### M3. Several named model-family claims lack canonical citations

Evidence:
- `main.tex:39` and `body.tex:515` mention DCC-GARCH, copula, GARCH-MIDAS, and Markov-switching as part of the "complexity ceiling."
- `body.tex:442-465` presents a table covering MIDAS/MS/CARR, DCC, copula, HAR-ABS, and MEM/AMEM.
- `body.tex:491` discusses HAR-ABS but there is no Corsi HAR citation in the bibliography.
- `main.tex:109-110` includes Engle, Ghysels, and Sohn (2013) but it is not cited.

Correction instructions:
- Either add canonical citations near the first model-family mention or remove named model families from the abstract/conclusion.
- At minimum: cite Engle, Ghysels, and Sohn (2013) for GARCH-MIDAS; add Engle (2002) for DCC if DCC remains; add Corsi (2009) for HAR; add appropriate CARR and Markov-switching GARCH references if those rows remain in the main table.
- Do not leave model families as uncited headline evidence in the abstract.

### M4. Current-event Iran/Hormuz episode needs external event citations

Evidence:
- `body.tex:345-351` states that on February 28, 2026 US-Israel strikes on Iran triggered the Strait of Hormuz blockade, describes oil-supply exposure, and reports cross-asset effects.
- `body.tex:511` says the paper is "confirmed out-of-sample through the 2026 Iran/Hormuz crisis."

Correction instructions:
- Add a cited source for the event date, blockade description, and oil-supply share if this remains in the main manuscript.
- Separate market statistics computed by the paper from externally sourced geopolitical facts. For example: "Following the February 2026 Iran/Hormuz shock [source], we compute..."
- If no archival source is intended for the event narrative, move this episode to the supplement and leave the main text as "2026 validation episode" with data-source details.

### M5. Yahoo Finance/data-source justification is not well supported by the cited reference

Evidence:
- `body.tex:37` says Yahoo Finance is standard and defensible for large liquid ETFs and Bitcoin, citing `bali2016`.
- The same sentence also claims validation against Bloomberg, Yahoo VIX/official series, and benchmark return moments, but no source or replication artifact is cited in the manuscript.

Correction instructions:
- Do not use Bali, Engle, and Murray (2016) as though it validates Yahoo Finance as a data vendor.
- Reword to say Yahoo Finance is the chosen data source, then cite the replication validation artifact or supplement for Bloomberg/VIX spot checks.
- If JBF submission is intended, state that the replication package freezes the Yahoo download vintage and provide a data appendix; otherwise the table notes about yfinance backfill (`tables_main.tex:84`, `tables_main.tex:125`, `tables_main.tex:147`) will undercut citation credibility.

### M6. Some source claims overextend what the cited method papers establish

Evidence:
- `body.tex:67-73`, `body.tex:164`, `body.tex:314`, `body.tex:326`, and `body.tex:427` repeatedly invoke Patton (2011) for QLIKE/proxy robustness and broader evaluation framing.
- `body.tex:227` cites Bayer and Dimitriadis (2022) for a power threshold of `N < 25` ES exceedances; this is a very specific operational threshold.
- `body.tex:423` cites Cederburg et al. (2020) for CRRA `gamma_RA in [2,10]`, but the citation is not obviously a generic source for that empirical CRRA range.

Correction instructions:
- Keep Patton (2011) for robust volatility forecast comparison with imperfect proxies, but do not use it as a blanket citation for all multi-target VT evaluation claims unless the sentence is narrowed.
- Verify the `N < 25` ES exceedance threshold against Bayer and Dimitriadis (2022) or cite it as the paper's own power heuristic.
- Add a standard asset-pricing/portfolio-choice source for the CRRA range, or remove the bracketed `[2,10]` citation claim.

## Visible DOI / Reference Formatting Notes

- DOI format is mostly consistent as `https://doi.org/...`.
- `main.tex:118-119` Acerbi and Szekely (2014) has no DOI; this may be acceptable for a Risk magazine article, but confirm publisher metadata.
- `main.tex:223-224` Sheppard (2023) is software with GitHub URL only; acceptable if the package version is correct, but consider citing the package documentation URL and the exact version used by replication.
- `main.tex:214-215` Nelson (2025) SSRN entry appears plausible with DOI `10.2139/ssrn.5931154`; retain as working-paper citation unless a newer version exists.

## Spot-Checked External Sources

- Baur (2012), "Asymmetric Volatility in the Gold Market," Journal of Alternative Investments, 14(4), 26-38, DOI `10.3905/jai.2012.14.4.026`: https://research-repository.uwa.edu.au/en/publications/asymmetric-volatility-in-the-gold-market.
- Hood and Raughtigan (2025), "Volatility Targeting Is Trendy," Journal of Portfolio Management, 52(1), 100-121: https://www.pm-research.com/content/iijpormgmt/52/1/100.
- Xu, "Improving volatility-managed portfolios in real time," Critical Finance Review, DOI `10.1108/CFR-03-2023-2491`: https://www.emerald.com/cfr/article/doi/10.1108/CFR-03-2023-2491/1370042/Improving-volatility-managed-portfolios-in-real.
- Bekaert and Wu (2000), Review of Financial Studies, 13(1), 1-42, DOI `10.1093/rfs/13.1.1`: https://academic.oup.com/rfs/article-abstract/13/1/1/1584172.
- Figlewski and Wang (2000), "Is the 'Leverage Effect' a Leverage Effect?", SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=256109.
