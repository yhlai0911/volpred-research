# Active v3 Final Gate Review — 2026-07-01

Manuscript reviewed:

- `paper/leverage-direction/main_v3.tex`
- `paper/leverage-direction/body_v3.tex`
- `paper/leverage-direction/tables.tex`
- `paper/leverage-direction/table_nulls.tex`
- `paper/leverage-direction/cover_letter.tex`
- `paper/leverage-direction/highlights.txt`
- `paper/leverage-direction/submission_package.md`
- `paper/leverage-direction/review_history/multi_round_20260701/`

No manuscript source files were edited in this pass. This report records the post-scrub active-v3 gate after three independent read-only Codex review runs and a local compile/package sanity check.

## Verdict

**NEEDS_MAJOR_REVISION — arXiv HOLD.**

The active v3 draft is cleaner than the prior review target, but the paper is not yet ready for arXiv permanence or JBF submission. The central blocker is not copyediting: the contribution is still overloaded, the OOS/sample map is internally inconsistent, and the submission package still exposes provenance, anonymity, and journal-compliance problems.

## Review Inputs

| Pass | Output | Verdict | arXiv decision |
|---|---|---:|---:|
| Academic/LaTeX consistency | `/tmp/leverage_active_v3_latex_review.md` | `NEEDS_MAJOR_REVISION` | `HOLD` |
| Citation and claim verification | `/tmp/leverage_active_v3_citation_review.md` | `NEEDS_MAJOR_REVISION` | `HOLD` |
| JBF final submission gate | `/tmp/leverage_active_v3_jbf_final_gate.md` | `NEEDS_REVISION` | `HOLD` |

Local mechanical checks:

- `xelatex -interaction=nonstopmode -halt-on-error -output-directory=/tmp/leverage_direction_build main_v3.tex` completed and produced `/tmp/leverage_direction_build/main_v3.pdf`.
- The build still reports an unresolved reference from `tables.tex:149` to `sec:var_compliance`.
- The abstract environment spans `main_v3.tex:36`-`48`; the main abstract paragraph is about 238 words and the full environment is about 266 words, above the local JBF profile limit.
- All five highlight bullets in `highlights.txt:3`-`7` exceed the local 85-character limit.

## 1. Contribution Gate

### Central claim

The best version of this paper would tell JBF readers that the sign of return-volatility asymmetry can be used as an economically interpretable state variable for choosing volatility models and deciding when volatility targeting helps or hurts.

Active v3 is moving toward that claim, but it still presents a broader bundle. The abstract says the paper identifies "two systematic patterns" and then expands into model selection, tail-risk scoring, allocation, and a complexity ceiling (`main_v3.tex:39`). The body formalizes two contributions plus supplementary time-zone evidence (`body_v3.tex:10`-`16`). The cover letter still describes three contributions and keeps time-zone arbitrage as a selling point (`cover_letter.tex:29`, `cover_letter.tex:33`). That is not a single clean JBF contribution yet.

### Novelty and framing

The paper has a plausible novelty path: it can connect leverage-effect sign to model-family choice and realized allocation value in a way that is more decision-oriented than a standard asymmetric-volatility comparison. That is a contribution JBF might understand.

The current draft weakens that path by trying to carry too many adjacent claims. It includes taxonomy, GARCH-family model choice, VaR/ES scoring, volatility-targeting allocation, a geopolitical stress episode, VIX/HAR/crowding discussion, complexity-ceiling claims, and a time-zone appendix (`body_v3.tex:245`, `body_v3.tex:379`, `body_v3.tex:396`, `body_v3.tex:545`, `body_v3.tex:591`, `body_v3.tex:643`). Several of these may be useful robustness checks, but the manuscript treats them as part of the main selling package rather than evidence supporting one contribution.

Gold is the most important example. The active source correctly discloses that GLD's unconditional mean asymmetry estimate is near zero and insignificant (`body_v3.tex:168`, `tables.tex:35`). Yet later language still says gold exhibits inverted leverage (`body_v3.tex:410`) and the conclusion repeats a safe-haven negative-asymmetry taxonomy (`body_v3.tex:618`). A defensible claim is regime-dependent gold asymmetry and its consequences for model selection, not unconditional discovery of inverted gold leverage.

### Practical takeaway

There is a practical rule in the draft, but it is not yet clean enough to anchor the paper. The rule says negative leverage direction favors GJR-style asymmetry, while inverted or near-zero leverage favors Student-t or symmetric alternatives (`body_v3.tex:227`). That is usable for portfolio managers if presented as a forecast-origin rule with clear sample timing, an auditable cutoff, and decision magnitudes.

The current implementation is not there. The text admits the threshold rule was calibrated on the evaluation sample (`body_v3.tex:237`) and the cross-sectional OOS validation has only six cases, including one miss (`body_v3.tex:237`-`240`). The multiple-testing paragraph says the broader program includes more than 110 experiment families and that several thresholds remain in-sample pending replication (`body_v3.tex:600`-`601`). For a practitioner journal, those disclosures are honest, but they move the rule from "deployable" to "interesting but not yet validated."

### Coherence

The contribution is coherent in embryo and padded in execution. A tighter paper should lead with one rule and one economically meaningful consequence: leverage direction helps choose volatility-model asymmetry, which changes volatility-targeted allocation outcomes. Time-zone momentum, broad complexity ceilings, VIX/HAR discussion, and the crisis vignette should either become supporting appendices or be removed until they can be tied directly to that rule.

## 2. Identification and Rigor

### In-sample vs OOS honesty

The manuscript is commendably explicit that the rule is not fully pre-specified, but that same honesty currently blocks submission. Active v3 uses January 2017 through March 2026 data in the data section (`body_v3.tex:58`), describes 2023-2024 as the primary OOS period and 2025-March 2026 as validation (`body_v3.tex:74`), shows Table 1 as an in-sample period of 2017-2025 (`tables.tex:6`), and later describes 2017-2025 as the limitation window with 2026 OOS language (`body_v3.tex:603`). These cannot all be the clean sample map.

The OOS claim should be rebuilt from one chronological protocol:

- estimation/training window,
- validation window for selecting thresholds,
- true holdout window,
- exact asset inclusion rules,
- exact forecast origin and trade execution lag.

The draft discusses lagging and no-lookahead principles (`body_v3.tex:97`, `body_v3.tex:532`, `body_v3.tex:579`), but the volatility-targeted return notation remains effectively contemporaneous in places (`body_v3.tex:147`, `body_v3.tex:289`). Add one explicit traded-return equation that uses information available at the prior close.

### Multiple testing

The current multiple-testing disclosure is a blocker rather than a cure. The manuscript says the active results are the product of a broad experiment family and that thresholds remain in-sample pending replication (`body_v3.tex:600`-`601`). That should be converted into a controlled design:

- identify one primary endpoint,
- freeze the leverage-direction rule before evaluating the final holdout,
- report all tried model families in a compact appendix,
- separate discovery evidence from confirmatory evidence.

Absent that rewrite, the reader cannot tell whether the practical rule is an ex-ante discipline or an ex-post summary of explored specifications.

### Magnitudes vs noise

The paper reports economically relevant objects: DM tests, Sharpe differences, drawdown effects, VaR/ES scoring, turnover/cost adjustments, and certainty-equivalent break-even values. That is directionally appropriate for JBF.

The problem is that several key magnitudes are either too sample-dependent or too weakly sourced for the claims attached to them. GLD's mean asymmetry is insignificant (`body_v3.tex:168`, `tables.tex:35`) but later supports a strong taxonomy. The OOS cross-asset rule rests on `N = 6` (`body_v3.tex:237`). The ES section invokes Fissler-Ziegel-style support while admitting direct SPY ES computation is infeasible and a fuller regression test is deferred (`body_v3.tex:258`-`269`, `tables.tex:219`, `tables.tex:231`). The CRRA break-even discussion uses a range that needs a better portfolio-choice source or removal (`body_v3.tex:498`).

### Internal consistency

Internal consistency is not submission-grade.

- Contribution count differs across manuscript and cover letter: two contributions plus supplementary evidence in the body (`body_v3.tex:10`-`16`) versus three in the cover letter (`cover_letter.tex:29`, `cover_letter.tex:33`).
- Sample windows differ across abstract, data section, tables, and limitations (`main_v3.tex:39`, `body_v3.tex:58`, `body_v3.tex:74`, `tables.tex:6`, `body_v3.tex:603`).
- Rolling-window text and the Figure 1 caption conflict: the method/table context uses 504-day windows stepped by 63 days (`body_v3.tex:133`, `tables.tex:26`), while the caption says "Rolling 252-day" (`body_v3.tex:274`).
- Submission-package state contradicts review history: `submission_package.md:3` says ready for upload, while this review round and `review_history/multi_round_20260701/README.md:15`-`17` say not converged.
- The highlights claim broader coverage than active v3 supports and promote the time-zone appendix (`highlights.txt:4`, `highlights.txt:7`).

## 3. JBF Fit

### Venue fit

The topic is plausible for JBF. The best version is practitioner-facing, model-selection-oriented, and tied to portfolio allocation. The paper does not need pure econometric novelty to be publishable if it delivers a clear, stable decision rule with transparent out-of-sample evidence.

The current version has high desk-reject risk because it still reads like a broad empirical research program compressed into one paper. JBF readers should not have to decide whether the paper is about asymmetric volatility, volatility targeting, VaR/ES validation, safe-haven gold, model complexity, VIX/HAR limits, geopolitical stress, or time-zone spillovers. Pick the one portfolio decision and make everything else serve it.

### Journal mechanics

The active package is not JBF-ready.

- The main manuscript identifies the author and affiliation (`main_v3.tex:25`, `main_v3.tex:27`), while the local JBF profile requires double anonymization.
- The package states non-blinded handling (`submission_package.md:51`-`53`), conflicting with the local JBF requirement.
- Required title-page/declaration materials are not cleanly separated in the upload checklist (`submission_package.md:14`-`24`).
- The abstract is too long under the local profile and includes keywords/JEL inside the abstract environment (`main_v3.tex:36`-`48`).
- The highlights exceed the local character limit and include a side claim (`highlights.txt:3`-`7`).
- Data/code availability is not strong enough for current submission norms: the manuscript still says details are available upon request (`main_v3.tex:25`, `body_v3.tex:78`) while the tables disclose data-vintage and exact-reconstruction limitations (`tables.tex:83`, `tables.tex:127`, `tables.tex:150`).

### Figures and tables

The figures and tables should support a take-home rule. At present, the main tables often expose research provenance rather than submission-ready evidence. Table notes mention an unrelocated source, data-vintage shifts, original values not reproducible under variations, paper-original vintage dependence, and internal memo provenance (`tables.tex:26`, `tables.tex:83`, `tables.tex:127`, `tables.tex:150`, `tables.tex:207`, `tables.tex:232`, `tables.tex:259`). Those notes are valuable for an internal audit trail but not acceptable as final manuscript captions.

Fixing this does not mean hiding problems. It means rebuilding tables from frozen, reproducible scripts and then describing the data vintage and replication protocol once in a formal data appendix.

## 4. Required Reframing Agenda

The next revision should be a major reframing, not another compliance scrub.

- **Choose one contribution anchor in `main_v3.tex:39` and `body_v3.tex:10`-`16`:** state that leverage direction is a decision variable for volatility-model choice and allocation. Remove the third-contribution framing from `cover_letter.tex:29` and `cover_letter.tex:33`. This reduces desk-reject risk from overclaiming.

- **Rebuild the sample map in `body_v3.tex:58`, `body_v3.tex:74`, `tables.tex:6`, and `body_v3.tex:603`:** define one training/validation/holdout chronology and use it everywhere. The current mixed OOS language undercuts identification.

- **Freeze and document the rule at `body_v3.tex:227`-`240`:** separate discovery calibration from final holdout evaluation, and stop presenting an in-sample threshold as deployable. The rule is the practical contribution, so its timing must be defensible.

- **Rewrite gold language at `body_v3.tex:12`, `body_v3.tex:168`, `body_v3.tex:410`, and `body_v3.tex:618`:** frame gold as regime-dependent and model-selection-relevant, not unconditionally inverted. The table estimate does not support the stronger wording.

- **Move side claims out of the main selling path in `body_v3.tex:396`, `body_v3.tex:545`, `body_v3.tex:591`, and `body_v3.tex:643`:** crisis validation, complexity ceilings, VIX/HAR/crowding, and time-zone material should only remain if they directly support the rule.

- **Replace provenance-heavy tables in `tables.tex:26`, `tables.tex:127`, `tables.tex:150`, `tables.tex:207`, `tables.tex:232`, and `tables.tex:259`:** regenerate final tables from frozen scripts and move audit history to a private replication log or formal appendix. The current notes invite rejection.

- **Repair journal package mechanics in `main_v3.tex:25`, `main_v3.tex:27`, `highlights.txt:3`-`7`, and `submission_package.md:14`-`24`:** create a double-blind manuscript, separate title page, short abstract, compliant highlights, declaration files, and editable source bundle.

- **Fix citation and event support at `body_v3.tex:58`-`65`, `body_v3.tex:258`-`269`, `body_v3.tex:396`-`402`, and `body_v3.tex:498`:** source the data-quality claims, soften ES claims until fully tested, cite event facts separately from computed returns, and add a proper CRRA/risk-aversion reference or remove the range.

- **Resolve mechanical LaTeX issues at `tables.tex:149` and `body_v3.tex:274`:** add or remove the missing `sec:var_compliance` reference and align the rolling-window figure caption with the actual methodology.

## 5. Recommended Next Step

**Major revision — DO NOT arXiv yet.**

The paper should not be posted or submitted in active v3 form. The next productive action is a focused contribution rewrite around a single PM decision rule, followed by a rebuilt sample/OOS protocol and a fresh submission package check. Once those are complete, rerun the three-gate sequence:

1. academic/LaTeX consistency review,
2. citation and claim verification,
3. JBF submission gate.

Only if all three converge to minor or no issues should the paper move to arXiv and journal submission.
