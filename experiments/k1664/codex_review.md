# K1664 Codex Review

## Verdict

CONDITIONAL_PASS

The experiment is methodologically acceptable as a short-sample pilot and the empirical verdict is appropriately limited to `PILOT_DIRECTIONAL_HAR_EDGE_NO_HARVEY_PASS`.  It must not be promoted as a formal Taiwan HAR-RV win until the 5-minute archive is materially longer.

## Checks

- Lookahead: PASS.  `add_forecast_features()` constructs `raw_signal` from same-day RV and then applies `.shift(1)`, so every feature for target day `t` is known through `t-1`.  Expanding OOS trains on `common.iloc[:i]` and predicts `common.iloc[i]`.
- Data provenance: PASS.  Inputs are local `data/intraday/0050_TW_5min_*.csv`; the result records file count, valid days, period, rows-per-day diagnostics, and generated snapshots.
- RV definition honesty: PASS.  Results explicitly state intraday 5-minute RV excludes overnight return, so it is not full close-to-close variance.
- Statistical framing: PASS.  QLIKE comes from `volpred.stats.model_evaluation.qlike_pointwise`; DM comes from `dm_test(h=1)`; the formal gate is DM t < -3.0.
- Small-sample handling: PASS with caveat.  OOS n=26 is too small for strong inference.  The README and JSON verdict say directional/pilot only.
- Atomic output: PASS.  `atomic_write_json()` writes a temp file, parses it, then `os.replace()`s the final results JSON.
- Seed: PASS.  Bootstrap uses seed 42.

## Caveats

- The 108-day archive is useful, but the 22-day HAR lag plus 60-row expanding minimum leaves only 26 OOS forecasts.
- HAR_DW_log improves QLIKE by +31.0% versus persistence, but DM t=-1.64 does not pass the Harvey threshold.
- HAR_DWM_log is weaker than HAR_DW_log in this sample, likely because the monthly component is estimated from too little history.
- Overnight variance is excluded; Taiwan ETF risk can be strongly affected by overnight US-market information.

## Required Interpretation

This closes K1664 as a data-ready pilot: 0050.TW 5-minute RV can now be computed reproducibly, and HAR(d,w) has a directional OOS QLIKE edge.  It does not close the broader research question of whether Taiwan HAR-RV robustly beats simple benchmarks.
