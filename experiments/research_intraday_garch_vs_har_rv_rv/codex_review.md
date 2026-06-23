# Codex Review — research_intraday_garch_vs_har_rv_rv

Date: 2026-06-23

## Verdict

PASS_WITH_PILOT_NULL_RESULT.

The script is reproducible from local 5-minute SPY snapshots, writes the required
results JSON, and uses project QLIKE/DM helpers. The scientific conclusion is
only pilot-level: the augmented intraday-shape proxy does not beat HAR in this
short OOS window, and the sample is far below the 252-OOS-day paper-grade bar.

## Checks

- Data source is transparent: local `data/intraday/SPY_5min_YYYY-MM-DD.csv`
  snapshots, 2026-01-14 to 2026-06-22 after dropping two short-bar days.
- Target matching is coherent: both models forecast next-day 5-minute realized
  variance, so HAR-RV is evaluated on its native RV target.
- Lookahead guard is explicit: `target_rv_next = rv.shift(-1)` and all predictors
  are day-t HAR / intraday-shape features observed after day-t close.
- OOS estimation is expanding-window OLS; each test row is excluded from its
  training window.
- Statistical comparison uses Patton QLIKE and `volpred.stats.model_evaluation.dm_test(h=1)`.
- Result is correctly downgraded to `PILOT_ONLY_INSUFFICIENT_OOS` because
  `n_oos_forecasts = 43 < 252`.

## Caveats

- This is not a full Engle-Sokalska multiplicative component GARCH MLE; it is a
  low-dimensional proxy using intraday-shape features.
- The local yfinance cache is short and single-asset only.
- Forecast target excludes overnight variance, so do not compare this result to
  close-to-close GARCH without Hansen-Lunde style target alignment.
