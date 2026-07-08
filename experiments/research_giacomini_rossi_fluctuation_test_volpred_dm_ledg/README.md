# Giacomini-Rossi fluctuation-test feasibility audit for the VolPred DM ledger

## Motivation

The research backlog asked whether VolPred's existing K1259 DM ledger can be
upgraded from static pairwise Diebold-Mariano summaries to a Giacomini-Rossi
fluctuation-test view of time-varying relative forecast performance,
especially for A4f / CF-Rolling versus HAR-style benchmarks.

This is a method-diagnosis experiment. It does not try to rescue a positive
result if the required data are absent.

## Data and scope

- Source: `experiments/k1259/dm_ledger.json`.
- Ledger scope: K1259 Phase 1.5 DM summary ledger, 2,718 rows from historical
  experiment result files.
- Evaluation target: rows whose model pair contains A4f and HAR, plus any
  CF/HAR or A4f/CF rows if present.
- Methodology type: empirical metadata audit plus descriptive diagnostics.
- Lookahead policy: no trading signal, return target, or forecast is formed in
  this experiment. The script only reads ex-post ledger summaries and checks
  whether date-indexed loss differentials exist.

## Literature anchor

- Giacomini and Rossi (2010), "Forecast comparisons in unstable environments",
  Journal of Applied Econometrics: fluctuation tests require a chronological
  out-of-sample loss-differential path.
- Diebold and Mariano (1995), "Comparing predictive accuracy", Journal of
  Business & Economic Statistics: equal-predictive-accuracy test on loss
  differentials.
- Harvey, Leybourne, and Newbold (1997), International Journal of Forecasting:
  small-sample DM modification.
- Hansen, Lunde, and Nason (2011), Econometrica: Model Confidence Set context
  for K1259 and why raw loss vectors matter.

## Method

The script applies a precondition gate before attempting any formal
Giacomini-Rossi calculation:

1. Load K1259's 2,718-row DM ledger.
2. Filter rows for A4f/HAR, CF/HAR, and A4f/CF model-pair text.
3. For every candidate row, open the cited source JSON and navigate to
   `source_field_path`.
4. Search the pair node, full source JSON, and sidecar forecast/loss files for
   date-indexed loss or forecast series with at least 252 observations.
5. If no pair-level chronological loss differential exists, stop and report a
   method-diagnosis null. A descriptive ledger-level diagnostic is reported
   separately and explicitly not treated as a formal fluctuation test.

## Results

Run:

```bash
uv run python experiments/research_giacomini_rossi_fluctuation_test_volpred_dm_ledg/research_giacomini_rossi_fluctuation_test_volpred_dm_ledg.py
```

Headline output:

- A4f/HAR rows in K1259 ledger: 20.
- Candidate source K experiments: K1002, K1014, K1054, K1057, K1063, K1072.
- CF / CF-Rolling related rows: 0.
- Candidate rows exposing pair-level date-indexed loss differentials: 0.
- Formal Giacomini-Rossi fluctuation test: not run, because preconditions fail.

The descriptive-only ledger diagnostic finds many large absolute DM statistics,
but the signs and pair definitions are source-experiment specific and not
normalized into a common loss-differential path. It is evidence of coverage
heterogeneity, not evidence of time-varying predictive superiority.

## Conclusion

Verdict: `METHOD_DIAGNOSIS_NULL`.

The current VolPred DM ledger cannot support a formal Giacomini-Rossi
fluctuation test for A4f/CF-Rolling versus HAR. It supports only a
summary-stat coverage audit. The next valid step is to extend future
DM-producing experiments to persist `date`, `model_a_loss`, `model_b_loss`,
and `loss_diff` sidecars, or to add a `loss_series_uri` field to a future
ledger schema.

## Files

- Script: `research_giacomini_rossi_fluctuation_test_volpred_dm_ledg.py`
- Results: `research_giacomini_rossi_fluctuation_test_volpred_dm_ledg_results.json`
- Figure: `ledger_fluctuation_precondition_audit.png`
