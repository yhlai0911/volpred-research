# Codex Contribution Gate Review for JBF First Round

Manuscript reviewed:

- `paper/leverage-direction/main.tex`
- `paper/leverage-direction/body.tex`
- `paper/leverage-direction/tables_main.tex`
- `paper/leverage-direction/cover_letter.tex`

## Verdict

**CONTRIBUTION BORDERLINE - needs reframing.**

I would not recommend a JBF revise-and-resubmit in the manuscript's current form. The paper contains a potentially publishable finance insight: the sign of the asymmetric volatility response may be an economically interpretable state variable that helps explain when asymmetry matters for forecasting and what volatility targeting is doing economically. But the current package is overextended, internally inconsistent, and still reads too much like a broad empirical GARCH exercise over ETFs with many auxiliary findings. A JBF editor is likely to desk-reject it unless the paper is narrowed to one finance question and the core contribution is made much cleaner.

## 1. Contribution Gate

### The central claim

The one central claim should be:

> Leverage direction, measured by the GJR-GARCH `gamma` parameter, is not merely a nuisance asymmetry parameter; it identifies the economic mechanism linking returns to volatility and therefore tells us when asymmetric volatility modeling and volatility-managed allocation have economic value.

This is the coherent claim. The manuscript gestures toward it in several places. The abstract states that "the direction of the asymmetric volatility response... varies systematically across asset classes" and has "direct implications for model selection, risk management, and portfolio construction" (`main.tex:39`). The introduction similarly says the paper proposes "a leverage direction taxonomy based on the GJR-GARCH `gamma` parameter" and that "the sign of `gamma` corresponds to the asset's price-driving mechanism" (`body.tex:11`). The literature review says the contribution is to "connect these strands through a single empirical object, the sign and magnitude of `gamma`" (`body.tex:25`).

That is a better paper than the current one. It would be a finance paper about when asymmetry has economic content. The submitted version, however, repeatedly slides into a method-selection paper: "GJR-GARCH significantly outperforms symmetric GARCH only for assets with statistically significant asymmetry" (`body.tex:11`), "the prescribed model is never significantly beaten" (`body.tex:200`), and "check gamma, not skewness" (`body.tex:371-373`). That is useful, but by itself it is not a JBF-level contribution. JBF will not be excited by a rule saying "estimate GJR, use GJR if its asymmetry coefficient is significant."

### Novelty relative to the cited literature

The paper is strongest where it links existing literatures rather than where it claims to discover cross-asset asymmetry. Black (1976) and Christie (1982) already anchor standard equity leverage. The manuscript itself acknowledges that "negative equity returns tend to increase future volatility more than positive returns" and that this is "well-documented for equity markets" (`body.tex:5`). It also acknowledges that prior non-equity work exists: "Chevallier (2017) document inverted asymmetric volatility in gold and several agricultural commodities" (`body.tex:7`) and "a smaller literature shows that non-equity assets can reverse the sign of the asymmetry" (`body.tex:23`). The references include Chang et al. (2021), whose title directly covers "Volatility regime, inverted asymmetry, contagion, and flights in the gold market" (`main.tex:103-104`).

Therefore, the taxonomy is not novel if stated as "equities positive, gold inverted, bonds near zero." The possible novelty is conditional: use leverage direction to explain model choice and the mechanism of volatility targeting, especially relative to Moreira and Muir (2017), Cederburg et al. (2020), and Hood and Raughtigan (2025). The manuscript makes that claim in Section `gamma-mechanism`: "Within equity-type assets," `gamma` is associated with whether VT is trend-following, contrarian, or pure variance management (`body.tex:391-399`). That is potentially new and economically meaningful, but the paper's own evidence sharply limits the claim: the mapping "does not extend to a broader cross-section including commodities, bonds, and digital assets" (`body.tex:399`) and is significant only in a six-asset equity-type domain (`body.tex:399`, `body.tex:405`, `body.tex:515`).

My assessment: the manuscript has a borderline contribution if reframed as a disciplined paper on the economic content of asymmetric volatility for allocation. As submitted, the novelty is diluted by too many side claims and by overclaiming the robustness of the taxonomy.

### Leverage direction taxonomy and gold

The gold finding is the paper's most interesting economic hook, but also the most fragile part of the contribution.

The manuscript is commendably honest in the body: it says GLD's canonical rolling-window mean is "statistically indistinguishable from zero (mean `gamma = +0.002`, HAC `t = +0.15`)" and that "the unconditional mean therefore does not establish inverted leverage for gold" (`body.tex:134`). Table 2 confirms this: GLD has mean `gamma = +0.002`, 67% negative windows, HAC `t = +0.15`, and the model choice is GARCH (`tables_main.tex:34`). This is not an unconditional inverted-leverage result.

The regime result is more promising. The body reports that bull and bear regimes give "bull `gamma = -0.043` versus bear `gamma = +0.048` (`t = -3.79`, `p < 0.001`)" (`body.tex:173`), and interprets this as "inverted during fear-driven rallies" but "standard leverage during liquidation-driven declines" (`body.tex:168`, `body.tex:173`). That is a real economic story if the regimes are defined independently of the outcome and validated out of sample.

At present, I would treat it as suggestive rather than JBF-grade. First, the manuscript acknowledges that an earlier draft reported a much stronger GLD result, "mean `gamma = -0.067` (HAC `t = -5.79`, 93% negative windows)," but that the canonical re-estimation "reverses the sign of the mean to `+0.002` and renders it insignificant" (`body.tex:134`). Yet the cover letter still tells the editor that "Gold exhibits a statistically significant inverted leverage effect (`t = -5.79`)" (`cover_letter.tex:29`). This is not a small presentation issue. It is an internal inconsistency on the central contribution.

Second, the regime-dependent interpretation is close to what the cited safe-haven and gold asymmetry literature would lead one to expect. The paper says inverted gold leverage is "consistent with gold's role as a safe-haven asset" (`body.tex:138`) and that regime-dependence "connects the leverage effect literature to the safe-haven literature" (`body.tex:175`). That is a plausible synthesis, but to clear JBF's contribution gate, the paper must show that it is not merely relabeling known safe-haven behavior with a GJR coefficient.

The gold contribution can become real if the paper makes the regime classification ex ante, economically motivated, and validated on holdout data or independent instruments. As written, "gold has no unconditional inverted leverage, but the sign changes across regimes" is interesting but not yet enough to carry a JBF paper.

### Complexity ceiling

The "complexity ceiling" claim is intellectually appealing but not convincingly identified as a contribution.

The manuscript states that "increasing model sophistication improves statistical measurement but not investable allocation decisions" (`main.tex:39`) and summarizes "ten independent tests" in Table `complexity_ceiling` (`body.tex:442-478`). It also offers a sharper version in the HAR section: HAR-ABS "outperforms GJR-GARCH in all seven markets tested" on QLIKE but produces "the lowest VT Sharpe" (`body.tex:491-493`). This prediction-versus-allocation distinction could interest JBF readers if it were the main paper.

The problem is that the ceiling is currently assembled from many heterogeneous exercises, many in the online supplement, after a very large search. The limitations section says results were selected from "110+ experiments across 14 model families" and that "all thresholds remain in-sample estimates pending replication" (`body.tex:497`). That admission weakens the claim that the ceiling is identified rather than discovered by extensive experimentation. Table `complexity_ceiling` mixes forecast loss, VaR, DCC allocation, copulas, VIX timing, CDaR, VVIX, HAR-ABS, and MEM (`body.tex:455-465`). This is too broad for a clean contribution unless the design is pre-specified around one question: when does better volatility measurement translate into better allocation?

Would JBF readers cite this? Possibly, but only if the paper is reframed around the measurement-versus-allocation wedge and uses a disciplined, pre-specified model set. In the present form, the ceiling reads like an ex post synthesis of many negative robustness checks.

### Is the time-zone contribution coherent?

No. It is bolted on and should be removed from the submission package.

The abstract and introduction now say the paper makes two contributions (`main.tex:39`, `body.tex:9-13`). The conclusion also says "Two contributions emerge" (`body.tex:511`). The only substantive time-zone-arbitrage claim appears in the cover letter: "Third, I document a persistent time-zone arbitrage channel..." (`cover_letter.tex:33`). In the manuscript body, the closest text is a vague sentence that "supplementary evidence on cross-market transmission" is reported online (`body.tex:15`, `body.tex:515`). A search of the provided manuscript source shows no developed time-zone section.

This hurts the package. It signals that the paper has not settled on its contribution. It also distracts from the only plausible JBF paper here. A time-zone spillover paper could be a separate paper; it does not belong in this one unless it is central to the leverage-direction mechanism, which it currently is not.

## 2. Identification and Rigor Concerns That Could Sink the Paper

### In-sample versus OOS honesty is still confused

The paper is unusually explicit about the in-sample concern, which is good. Section `model_selection` says the magnitude band and significance rule "are calibrated on the same sample used for evaluation" and that "the in-sample classification consistency is therefore partly mechanical" (`body.tex:202`). This is exactly the issue.

The current model-selection evidence relies heavily on weak formulations. The claim that the rule-prescribed model is "never significantly beaten" (`body.tex:200`) is not the same as showing it selects the best model. Many cells are statistically indistinguishable. Table `qlike` has 11 comparisons, with significant results mainly for SPY and GLD (`tables_main.tex:51-61`). Non-rejection of equal predictive accuracy should not be marketed as correct classification.

The "6/6 correct" OOS result is supportive but far too small. The paper itself notes that with `N = 6`, "random classification would achieve 100% accuracy with probability `2^{-6} approx 1.6%`" and that independent validation is needed (`body.tex:202`). That is an appropriate caveat, but it also means the OOS result cannot carry a JBF contribution.

There is also a sample-split inconsistency. The data section says the period is "January 2017 through March 2026" (`body.tex:34`). The sample-period paragraph says "2023--2024 as the main out-of-sample period and 2025--March 2026 as validation" (`body.tex:41-42`). But the data-characteristics section calls 2017--2025 "the in-sample period" with 2026 reserved (`body.tex:120`), and Table 1 is captioned "In-Sample Period: 2017--2025" (`tables_main.tex:5`) while Table 3 treats 2025 as an OOS period (`tables_main.tex:52`, `tables_main.tex:54`, `tables_main.tex:56`, `tables_main.tex:58`, `tables_main.tex:60`). A finance referee will not accept OOS claims until the sample split is unambiguous and consistently implemented.

Finally, the cover letter says the taxonomy "correctly classifies all twelve Diebold--Mariano comparisons across two out-of-sample periods" (`cover_letter.tex:29`), while the abstract and body refer to eleven comparisons (`main.tex:39`, `body.tex:200`) and the table explicitly lacks a BTC 2025 row: "BTC 2025 has no canonical source row and is not added" (`tables_main.tex:62`). This discrepancy is likely to damage credibility at the editor stage.

### Multiple-testing discipline is acknowledged but not solved

The limitations section admits "110+ experiments across 14 model families" and "data mining concern" (`body.tex:497`). It lists mitigants, including a `t > 3.0` threshold, Benjamini-Hochberg FDR, and a null-to-positive ratio (`body.tex:497`). But the paper's main claims do not yet read as pre-specified hypotheses tested under a unified family of tests. Instead, the manuscript accumulates claims: taxonomy, GARCH selection, VaR orthogonality, ES, VT, EWMA, VIX, crisis validation, complexity ceiling, HAR paradox, crowding risk, behavioral costs, and future semantic volatility risk premium.

For JBF, the multiple-testing problem is not just a p-value adjustment issue. It is a contribution-design issue. The paper needs to say what the one null is, what the primary outcome is, which tests are confirmatory, and which are exploratory. At present, the manuscript acknowledges the problem but still asks the reader to trust a large set of selected findings.

### The gold result does not support the current cover-letter claim

This is the most serious internal inconsistency.

The body says the gold unconditional mean is insignificant and reversed from the old draft (`body.tex:134`). Table 2 reports GLD `gamma = +0.002`, HAC `t = +0.15` (`tables_main.tex:34`). But the cover letter still reports "Gold exhibits a statistically significant inverted leverage effect (`t = -5.79`)" (`cover_letter.tex:29`). The body footnote states that exact number belongs to an earlier draft and "the canonical re-estimation... reverses the sign" (`body.tex:134`).

If an editor notices this, the paper may be desk-rejected for credibility reasons before the contribution is evaluated. The author must remove every stale `t = -5.79` claim and state the gold claim as regime-dependent only.

### The model-selection OOS classification is not yet genuinely out of sample

The rule is not cleanly pre-specified. Section `model_selection` first proposes "If `gamma` is statistically significant at 10% (`t > 1.65`) and positive: Use GJR-GARCH; otherwise use symmetric GARCH" (`body.tex:194-199`). It then clarifies that two statistics are being used: a single-window estimation `t` available in real time and the quarterly-mean HAC `t` in Table 2 (`body.tex:200`). It further says the rule applied to the quarterly-mean statistic is never significantly beaten (`body.tex:200`) but that the real-time single-point rule misses SPY while a four-quarter average succeeds (`body.tex:204`).

That is not yet a transparent out-of-sample decision rule. A JBF referee will ask: before seeing the OOS QLIKE table, which statistic exactly is used, over which window, with what threshold, for which assets, and what counts as success? The paper should provide a decision log: forecast-origin date, estimated `gamma`, its standard error, chosen model, realized OOS loss differential, and DM result. It should also separate "correctly selected the significantly superior model" from "selected a model that was not significantly beaten."

### The VT evidence is economically interesting but not cleanly identified

The VT mechanism proposition is one of the better ideas in the paper, but the identification is fragile. The manuscript states that the mapping is "partly mechanical, as both `beta^trend` and `gamma` derive from the GJR specification" (`body.tex:405`). The main significant claim is in a small and restricted sample: "Spearman `rho = 0.886`, `p = 0.019`, `N = 6`" for equity-type assets (`body.tex:399`, `body.tex:515`). The broader cross-asset result is insignificant and has the opposite sign (`body.tex:399`, `body.tex:515`).

This can still be useful if framed as a mechanism diagnostic rather than a broad cross-asset law. But the paper currently alternates between broad claims and domain restrictions. The abstract says leverage direction is linked to the economic channel of VT alpha but immediately notes the relationship does not extend to diverse asset classes (`main.tex:39`). The conclusion says the same (`body.tex:515`). That is honest, but it also means the finance contribution must be narrower.

### Replication and data-vintage issues are too visible

Several table notes are unusually damaging for a first-round submission. Table `vt` says a reproducibility check "matched 6/20 cells using a uniform 2015--2026 OOS window" and that "exact reconstruction of GLD metrics also requires the paper-original data vintage" (`tables_main.tex:146-147`). Table `var` says yfinance backfill revisions may shift violation counts by up to `+/- 3` (`tables_main.tex:84`). Table `gamma` says earlier estimates came from "a vintage whose source experiment could not be re-located" (`tables_main.tex:24`).

These are good internal audit notes, but they should not appear in a JBF submission in this form. They make the paper look unstable. The correct response is not to hide them; it is to freeze a replication dataset, define the sample once, and make all main tables reproducible from that frozen source.

### ES and risk-management claims overreach relative to evidence

The manuscript discusses FRTB expected shortfall, but then says direct SPY ES computation is "infeasible with only six `alpha = 1%` exceedances" (`body.tex:227`) and that a full ES regression test is "deferred to the paper's replication package supplement" (`body.tex:233`). That is a responsible limitation, but it means ES should not be a main JBF contribution. Similarly, Table `var_ortho` contains a useful point about variance-equation choice versus distributional choice (`tables_main.tex:89-100`), but this is not central enough to carry the paper unless the manuscript becomes a risk-management paper rather than a leverage-direction paper.

## 3. JBF Fit and Likely Desk-Reject Reason

The topic is within JBF's scope. JBF has a natural audience for cross-asset risk management, gold safe-haven behavior, volatility forecasting, VaR/ES backtesting, and implementable allocation rules. The manuscript explicitly positions itself around "GARCH model selection, VaR backtesting under Basel III, and volatility targeting" (`cover_letter.tex:35`), all of which fit the journal.

The most likely desk-reject reason is not lack of topical fit. It is that the editor will see an incremental econometric exercise with unstable claims rather than a clean finance contribution. The title and abstract promise a broad contribution across "model selection, risk management, and portfolio construction" (`main.tex:25`, `main.tex:39`). The body then contains too many loosely connected modules. The cover letter worsens the problem by adding a third time-zone contribution not developed in the manuscript (`cover_letter.tex:33`) and by repeating an obsolete gold statistic (`cover_letter.tex:29`). The single biggest editorial concern is: this paper has not decided what it is.

## 4. Highest-Leverage Changes

1. **Make the paper about one contribution: the economic content of leverage direction.** Drop the time-zone contribution entirely. Move most VaR/ES, VIX, HAR, crowding, and behavioral material to an online appendix unless it directly tests the leverage-direction mechanism. The main paper should answer one question: when does asymmetric volatility have economic value for forecasting and allocation?

2. **Rebuild the gold result around pre-specified regimes.** Stop claiming unconditional inverted leverage for gold. State the current fact: GLD's unconditional mean `gamma` is insignificant. Then test an ex ante regime model using independently defined safe-haven and liquidation regimes, gold futures or institutional data, and a holdout period. Compare directly to Chevallier (2017), Chang et al. (2021), and Baur and Lucey/McDermott. The contribution must be "regime-dependent economic mechanism," not "gold has negative gamma."

3. **Turn model selection into a real OOS horse race.** Pre-specify the `gamma` rule using an initial training period or one asset universe, then test it on a non-overlapping asset universe and future period. Report all forecast-origin decisions. Use DM/MCS with multiple-testing correction and clearly distinguish significant superiority from non-rejection. Remove "never significantly beaten" as the headline claim.

4. **Clean all internal inconsistencies before submission.** Fix the cover letter's `t = -5.79` and "twelve DM comparisons" claims. Make the sample split consistent across data, descriptive statistics, OOS tables, and validation language. Freeze the data vintage and remove table notes implying that main-table numbers cannot be exactly reconstructed.

5. **Identify the VT channel independently of the GJR construction.** The `gamma`-to-trend-beta mapping is promising but small-sample and partly mechanical. Show that pre-sample `gamma` predicts future VT behavior under alternative volatility signals, or show that exogenous leverage-direction proxies predict the trend/contrarian channel. Report economic magnitudes, turnover, costs, and investor utility, not only correlations.

## Final Referee Assessment

I would tell the editor that the paper is not a method-exercise pure and simple; there is a potentially interesting finance idea here. But the current submission does not yet clear JBF's contribution gate. It overclaims a fragile gold result, relies on small and partly in-sample model-selection evidence, bundles too many auxiliary exercises, and contains internal inconsistencies that undermine confidence. A sharply reframed version centered on leverage direction as an economic mechanism, with a clean regime design for gold and genuinely out-of-sample model-selection tests, could become JBF-adjacent. The current version is more likely to be desk-rejected than sent to referees.
