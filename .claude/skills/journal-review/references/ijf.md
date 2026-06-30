# International Journal of Forecasting (IJF)

- **Abbrev**: IJF (Int. J. Forecast.); ISSN 0169-2070
- **Publisher**: Elsevier for the International Institute of Forecasters (IIF). Editorial Manager.
- **Tier**: THE premier dedicated forecasting journal (official IIF publication). JIF ~7-8, ABS 3, ABDC A. Top-tier home for forecasting/econometrics methodology + empirical forecasting (incl. financial volatility). ~12-15% acceptance.

## Scope
High-quality refereed papers on ALL aspects of forecasting; unify the field, bridge theory↔practice for decision/policy makers. Strong emphasis on empirical studies, evaluation (genuine OOS / forecast-accuracy comparison), implementation, improving forecasting PRACTICE.
- **Fits**: a paper fundamentally about forecasting — produce + rigorously evaluate forecasts (point/interval/density), or advance forecasting methodology/theory/evaluation. Vol-prediction (GARCH/HAR-RV/ML/VaR-ES/density) fits IF framed as a forecasting/evaluation contribution w/ honest OOS + formal tests.
- **Does NOT fit**: pure in-sample estimation w/ no forecasting angle; trading-strategy papers whose contribution is profit not forecast quality; descriptive empirics w/o predictive evaluation; methods on simulated data only. Welcomes replication + software/data papers.

## Format
- **Length**: no rigid cap; concise/focused expected (no published numeric limit).
- **Abstract**: unstructured, **100-150 words**; summarize findings + how obtained + why they matter to researchers AND practitioners; NO refs/jargon/math.
- **Keywords/JEL**: ≥5 keywords from the IIF recommended list (don't repeat title words); JEL NOT mandatory.
- **Structure**: unstructured; fully anonymized manuscript (double-blind) + separate title page.
- **References**: author-date (Harvard); EndNote → use APA style.
- **Figures/tables**: numbered + cited; high-res; Word equations as equation OBJECTS not images; supplementary data/code hosted alongside; color online free.
- **LaTeX**: elsarticle.cls + BibTeX encouraged; Word accepted; editable source for typesetting.

## Submission process
Editorial Manager (IIF/Elsevier portal from forecasters.org/ijf/authors). Separate title page (names/affiliations/corresponding/ORCID) + fully anonymized manuscript. Suggest **4-6 referees OUTSIDE your institution** (names/addresses/fields). Cover letter standard. Declarations: originality/no concurrent submission; disclose any published/under-review papers using similar methods/data + how this differs (anti-salami); generative-AI use; COI/funding; data+code (reproducibility) materials or a justified exemption request to the EiC.

## Review model
Double-anonymized; ≥2 reviewers. ~30% desk-rejected (often ~1 wk); reviewer turnaround historically ~42 d; first decision a few weeks (desk) to ~2-4 mo (review). ~12-15% acceptance. (EiC-report/SciRev estimates, approximate.)

## Fees & OA
No submission fee, no page charges. Hybrid: subscription free; optional gold OA APC ~US$2,800 excl. tax (verify live). Color figures free online.

## Distinctive requirements
1. **Mandatory data & code / reproducibility policy** (since Jul 2023): sharing data AND code compulsory for accepted papers unless EiC accepts a motivation. Acceptance CONDITIONAL on passing a formal reproducibility check (with CASCaD, overseen by a Reproducibility Editor). Build a self-contained replication package (scripts regenerate every table/figure from raw or clearly-instructed data, fixed seeds, README, version-pinned env) BEFORE submission. 2. Generative-AI disclosure. 3. Similar-work disclosure (anti-salami). 4. Double-anonymized manuscript + separate title page. 5. 4-6 suggested referees outside your institution. 6. Highlights 3-5 bullets (≤85 chars) supported/encouraged (confirm in portal); graphical abstract optional. 7. Forecast-evaluation rigor (genuine OOS + formal predictive-accuracy tests) substantively required.

## Pre-submission checklist (extends generic)
- Core contribution = producing + rigorously EVALUATING forecasts (not in-sample fit or trading P&L); for vol lead w/ OOS accuracy (QLIKE/MSE on variance) + density/VaR-ES, framed as forecasting.
- Genuine OOS scheme (rolling/expanding), no look-ahead; explicit lag (signal.shift(1)); forward-label target_end < forecast_origin; state forecast origin/horizon alignment.
- Formal predictive tests: DM / HLN / Giacomini-White / Model Confidence Set — not just lower average loss; horizon-matched inference; HAC/cluster-robust for multi-asset panels (no asset-day iid).
- Replication package (deal-breaker): self-contained data+code regenerating every table/figure (seeds, README, pinned env); acceptance conditional on CASCaD check; if data/code can't be shared, prepare a written exemption for the EiC.
- Anonymization: de-identify manuscript (no names/affiliations/"our previous work"/identifying acks/file metadata); details on separate title page.
- Abstract 100-150 w, no refs/jargon/math, findings + why they matter to researchers AND practitioners; ≥5 keywords from recommended list (not duplicating title).
- LaTeX elsarticle + BibTeX (or Word w/ equation objects); author-date/APA refs; numbered figures/tables w/ captions; 3-5 Highlights ≤85 chars.
- Disclosures: originality/no concurrent submission, AI-use, COI/funding, + cite & differentiate your own similar published/under-review papers.
- Provide 4-6 referees outside your institution.
- Articulate WHY the forecasting gain matters in practice (decision/policy/economic value) — IJF weights implementation relevance.
- Benchmark vs strong fairly-tuned standards (HAR-RV, GARCH-family, naive/RW) under identical lag/loss; investigate suspicious outperformance for bugs.
- Decide subscription vs OA (~$2,800) + verify current APC + portal requirements (Highlights/graphical abstract).

## Sources
- https://www.elsevier.com/journals/international-journal-of-forecasting/0169-2070/guide-for-authors
- https://forecasters.org/ijf/authors/
- https://robjhyndman.com/hyndsight/replications/
- https://www.sciencedirect.com/journal/international-journal-of-forecasting
