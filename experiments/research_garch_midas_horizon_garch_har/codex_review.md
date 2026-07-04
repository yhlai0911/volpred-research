# Codex Review — research_garch_midas_horizon_garch_har

Date: 2026-07-04

## Verdict

`PASS_WITH_LIMITATIONS`

The experiment is sound for the stated daily component-MIDAS proxy scope. The
results support the reported null: the tested RV-MIDAS long-run component does
not provide a Harvey-pass OOS improvement over HAR or rolling GARCH baselines at
22- or 66-trading-day horizons.

## Checks

- Experiment three-piece package exists: `README.md`,
  `research_garch_midas_horizon_garch_har.py`, and
  `research_garch_midas_horizon_garch_har_results.json`.
- Lookahead guard is explicit: target is `mean(r2[t+1:t+H])`; OOS training rows
  require `j + H < i`, so no training target overlaps the forecast origin.
- Forecast features use information available through origin day `t`; the
  target begins at `t+1`.
- QLIKE uses the canonical project helper
  `volpred.stats.model_evaluation.qlike_pointwise(actual, predicted)`.
- Multi-asset pooled inference averages loss differentials by date before DM,
  avoiding asset-day iid inflation.
- Rolling GARCH fit failures are counted and reported; this run had zero fit
  failures and zero fallback uses for SPY, QQQ, and GLD.
- Re-run completed successfully and reproduced the same verdict.

## Limitations

- `Component_MIDAS` is a daily component-MIDAS proxy, not a full
  Engle-Ghysels-Sohn GARCH-MIDAS MLE.
- The MIDAS component uses fixed beta weights and rolling 22-trading-day RV
  blocks, not estimated MIDAS weights or calendar macro-release timing.
- The variance proxy is daily close-to-close squared returns, not intraday
  5-minute realized variance.
- The GARCH baseline is symmetric GARCH(1,1), not GJR-GARCH. This is acceptable
  for the backlog wording "GARCH/HAR", but a heavier follow-up could add GJR.

## Conclusion Bound

Do not cite this as a universal rejection of GARCH-MIDAS. Cite it as:

> In a daily close-to-close proxy test on SPY/QQQ/GLD, at H=22 and H=66,
> fixed-weight RV-MIDAS long-run components did not improve OOS QLIKE over HAR
> or rolling GARCH baselines.
