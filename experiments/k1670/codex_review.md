# K1670 Codex Review

Verdict: `PASS_NULL_RESULT`

Reviewed files:

- `experiments/k1670/K1670.py`
- `experiments/k1670/K1670_results.json`
- `experiments/k1670/README.md`

## Checks

- Lookahead: PASS. Raw interval features are shifted with `signal = raw_signal.shift(1)`. Target day `t` uses only features through `t-1`.
- OOS training discipline: PASS. Forecast row `i` is fit on `work.iloc[:i]`. The refit state is updated only from rows strictly before the forecast row.
- Randomness: PASS. `SEED = 42` is fixed; the OLS forecasts are deterministic.
- Model-target match: PASS. The experiment evaluates interval forecasts against interval targets. It does not claim scalar RV QLIKE superiority.
- Baseline fairness: PASS. The scalar point-HAR baseline and interval-valued challengers are all calibrated on the expanding training sample to the same 80% containment target.
- Cross-asset inference: PASS. Aggregate DM tests use date-clustered daily average losses across assets rather than asset-day iid pooling.
- Results JSON integrity: PASS. The writer uses tmp JSON, parses it, then `os.replace`.
- Null-result honesty: PASS. The README records that the best aggregate improvement is only +0.034% and not statistically meaningful.

## Main Audit Numbers

- Center-radius interval vs point HAR: interval MSE improvement +0.034%, DM t=-0.318, p=0.751, aggregate coverage 78.34%.
- Direct bounds interval vs point HAR: interval MSE improvement -1.347%, DM t=+0.902, p=0.367, aggregate coverage 77.80%.
- Point-HAR baseline aggregate coverage: 78.41%.
- QQQ center-radius per-asset result is positive (DM t=-4.08), but this is offset by other assets and does not survive date-clustered aggregate inference.

## Caveats

- The direct-bounds model is intentionally transparent OLS, not a full fuzzy interval time-series system.
- Daily adjusted OHLC is a public proxy and can contain ETF and corporate-action artifacts.
- The conclusion is limited to next-day interval forecasting accuracy under interval MSE and interval score.

No blocking issue found. The correct conclusion is `NULL_NO_INTERVAL_EDGE`.
