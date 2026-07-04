# Predictor Zoo Multiple-Testing Audit

Experiment id: `research_predictor_zoo_30_predictor_romano_wolf_fdr_oos`

## Question

The backlog asked for a platform-wide cleanup of the external-predictor volatility
zoo: AI power demand, PM2.5/AQI, GPR, EPU/disagreement, credit/liquidity stress,
stablecoin / crypto funding, sentiment / attention, macro cross-asset signals,
Taiwan external-flow proxies, and related public-data event signals. The core
question is:

> After multiple-testing correction, how many of the previously tried external
> predictors still look like robust OOS volatility predictors?

## Data Sources

This audit does not create new forecasts. It reuses already-computed platform
artifacts and records every source path:

- `storage/memory/knowledge.json` entries, parsed as a text index.
- `experiments/**/README.md` text summaries.
- `experiments/**/*_results.json` and `experiments/**/results.json`, parsed
  recursively for reported t-statistics and p-values.

The script deliberately avoids hand-editing source JSON or backfilling missing
statistics. If a p-value is missing but a t-statistic is present, it records a
two-sided normal-approximation p-value with `p_source="estimated_from_t_normal"`.

## Method

1. Detect candidate sources with strict external-predictor regexes plus a
   volatility / OOS / forecast context filter.
2. Extract structured statistical nodes from result JSON and text windows from
   README / knowledge summaries.
3. Collapse to one deliberately favorable source-level hypothesis per
   `(source_group, external_predictor_family)` by taking the smallest available
   p-value. This is a best-case audit for the predictor zoo, not a pessimistic
   counting exercise.
4. Apply:
   - Harvey-style raw screen: `abs(t_or_z) >= 3`.
   - Holm FWER at alpha 5%.
   - Benjamini-Hochberg FDR at q=10%.
   - A clearly labelled independent maxT stepdown approximation.

Formal Romano-Wolf stepdown requires a joint loss-differential or test-statistic
matrix so the dependence structure can be resampled. Most historical K results
only store summary t/p values, so this experiment does **not** claim a formal
Romano-Wolf result. It reports `formal_romano_wolf_feasible=false` and uses the
independent maxT stepdown only as a conservative, reproducible reference.

## Literature Checked

- Romano and Wolf (2005), "Stepwise Multiple Testing as Formalized Data
  Snooping", Econometrica / SSRN.
- White (2000), "A Reality Check for Data Snooping", Econometrica.
- Hansen (2005), "A Test for Superior Predictive Ability", JBES.
- Goyal and Welch (2008), "A Comprehensive Look at the Empirical Performance of
  Equity Premium Prediction", RFS.
- Goyal, Welch, and Zafirov (2024), "A Comprehensive 2022 Look at the Empirical
  Performance of Equity Premium Prediction", RFS.

The important design implication is that a predictor-zoo conclusion must control
the full family of tries; raw winners are not enough.

## Reproduction

```bash
uv run python experiments/research_predictor_zoo_30_predictor_romano_wolf_fdr_oos/research_predictor_zoo_30_predictor_romano_wolf_fdr_oos.py
```

Outputs:

- `research_predictor_zoo_30_predictor_romano_wolf_fdr_oos_results.json`
- `predictor_zoo_audit_table.csv`
- `fig_predictor_zoo_corrections.png`

## Run Summary

Latest run (`uv run python ...`, seed 42) extracted 811 candidate statistical
rows and retained 67 primary source-family hypotheses after excluding
knowledge-only text, diagnostics, intercept/const rows, correlations, Granger /
lead-lag screens, and IS/full-sample/descriptive rows.

Best-case summary-stat correction:

- Raw p < 0.05: 48 / 67.
- Harvey-style `abs(t_or_z) >= 3`: 35 / 67.
- BH FDR q <= 0.10: 53 / 67.
- Holm FWER p <= 0.05: 34 / 67.
- Independent maxT-style stepdown p <= 0.05: 34 / 67.

Interpretation: the platform has many statistically sharp *reported cells*,
especially VIX / IV / VRP / macro-cross-asset variants. This is not the same as
"34 robust useful external predictors": direction, baseline-worse cases, and
economic value are not adjudicated in this summary-stat pass. The durable
methodological result is the infrastructure gap: formal Romano-Wolf needs old
experiments to persist aligned pointwise loss differentials, not just summary
t/p values.

## Honesty Notes

- This is a meta-audit over existing platform outputs, not a fresh per-predictor
  expanding-window HAR/GARCH rerun.
- It is intentionally favorable to discoveries because it takes the best
  source-level p-value per family before correction.
- A survivor is a statistical cell, not automatically a positive edge; several
  cells can be significant because the candidate is worse than baseline or
  because the effect is descriptive rather than economically useful.
- Because raw daily loss differentials are not stored consistently across the
  old experiments, a formal Romano-Wolf resampling pass is an infrastructure
  follow-up, not a defensible claim in this run.
