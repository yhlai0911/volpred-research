# K1711 independent Codex review — 2026-07-16

## Scope

- Frozen candidate commit: `63520b4dae8b62d55650904ed51fab1739386f65`.
- Reviewed the complete experiment claim surface: forecasting/data/TSFM/chart/test code,
  `README.md`, `k1711_results.json`, and four reader-facing figures.
- The cached forecast and pointwise-loss artefacts were treated as evidence, not trusted
  summaries. No expensive TSFM inference was rerun.

## Verdict

**PASS.** No blocking defect remains. The supported claim is deliberately narrow:
TSFM-bearing calibrated/combination forecasts survive the pre-specified QLIKE MCS in
all three primary asset cells, and `COMB-MZ` survives the pooled MCS. Membership is
non-rejection, not a win or proof of incremental predictive content.

Nested QLIKE comparisons are correctly marked
`INCONCLUSIVE_NO_VALID_GENERAL_LOSS_NESTED_TEST`. Raw nested DM/HLN statistics are
diagnostic-only and cannot feed a verdict. Clark-West inference is restricted to MSE,
Holm-adjusted within cell, and explicitly identifies the smaller/larger-model direction.

## Independent evidence

- `25 passed` in `test_k1711.py`; Python compilation passed.
- `experiment_gates.py run` passed all four integrity gates over five Python files.
- All 24 result cells and eight pooled cells are present; 24 pointwise series keys match.
- Recomputed 264 QLIKE series means: maximum error versus results JSON was exactly zero.
- Recomputed all 240 QLIKE-vs-HAR DM/HLN records and within-cell Holm adjustments:
  maximum t, p, and adjusted-p error was exactly zero.
- Re-ran the 5,000-draw, seed-20260714 primary MCS from pointwise losses for SPY,
  0050.TW, and TX, both full and base pools; every superior set matched the frozen JSON.
- Independently rebuilt the 2,344-date pooled loss panel and re-ran both MCS pools;
  the frozen full set `{HAR-A, COMB-MZ}` and base set `{HAR-A}` matched.
- Verified all six TSFM forecast CSVs: finite 32-step forecasts, unique/ordered targets,
  recorded origin equals the immediate prior panel date, counts/dates match metadata,
  and panel SHA-256 values match both model metadata files.
- Re-applied `finalize_results` to the frozen JSON; it was idempotent.
- Compared pre/post provenance-fix results: all 3,656 numeric leaves were unchanged.
- Visually inspected all four PNG figures; labels, MCS boxing, scales, and stated
  interpretation match the frozen results.

## Review findings closed before PASS

1. Corrected the pseudo-OOS start label from 2016-01-01 to the implemented 2016-07-01.
2. Corrected the TTM revision label to official-selector `512-96-ft-r2.1`.
3. Downgraded `vintage_clean` to a later/cleaner robustness window because TTM's
   training-data cutoff is unstated.
4. Qualified squared open-to-close return as conditionally unbiased only under
   idealized assumptions and disclosed the pre-window zero floor.
5. Clarified that `clean_tw50_data()` is a close-only diagnostic, not a rewrite of
   0050.TW target OHLC; also clarified the append-only TAIFEX source versus the frozen
   experiment-time hash and committed derived panel.

## Non-blocking limitations

- The primary 2016-07+ window is retrospective pseudo-OOS because checkpoint weights
  post-date much of the sample.
- The MCS implementation is accurately identified as the `max_i t_i / e_max` variant;
  it does not separately repair nested pairwise QLIKE inference.
- The `r2` proxy exercise is approximate sensitivity, not an exact Patton theorem test.
- The current TAIFEX collector has appended later rows. On the 3,545 committed common
  dates, RV matched exactly and return differed only by CSV floating serialization
  (maximum absolute difference about `1e-16`); no frozen experimental row was revised.
