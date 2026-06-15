# Codex Review — K1501 FINRA off-exchange proxy -> idiosyncratic volatility

VERDICT: CONDITIONAL_PASS

Condition: results are valid only as a **FINRA public off-exchange / short-volume proxy** experiment. They must not be described as direct evidence on true retail order flow, broker-level retail flow, or PFOF routing quality.

## Scope Reviewed

- `experiments/k1501_proxy_idio_vol/k1501.py`
- `experiments/k1501_proxy_idio_vol/k1501_results.json`
- `experiments/k1501_proxy_idio_vol/README.md`

## Checks

1. **Lag / lookahead**
   - PASS.
   - Forecasting features use explicit `.shift(1)`:
     - `log_idio_r2_lag1`, `log_idio_r2_lag5`, `log_idio_r2_lag22`
     - `spy_r2_lag1`
     - `short_ratio_z_lag1`
     - `log_offex_volume_z_lag1`
     - `finra_present_lag1`
   - The target is date-t residual squared return, and all predictors are known by t-1.
   - Horizon is h=1, so the K1337 forward-label OOS leakage issue does not apply. Any h>1 extension must embargo the last h-1 training labels.

2. **Random seed**
   - PASS.
   - `SEED = 42` and `np.random.seed(SEED)` are set. The current experiment has no stochastic bootstrap / Monte Carlo operation.

3. **Baseline fairness**
   - PASS.
   - Baseline and full model use the same rolling 252-day fit window, same 21-day refit cadence, same target, and same OOS dates.
   - Full model only adds lagged FINRA proxy variables.

4. **OOS integrity**
   - PASS.
   - Per ticker OOS is 477 observations from 2024-07-19 to 2026-06-12.
   - Refits use rows `[i-window:i]` and predict row `i`; h=1 target avoids forward-label overlap.
   - OOS length exceeds the project minimum of 252 trading days.

5. **DM / evaluation**
   - PASS.
   - Uses `volpred.stats.model_evaluation.qlike`, `qlike_pointwise`, and `dm_test`.
   - Harvey gate is correctly applied as `|DM t| > 3.0`.

6. **Conclusion strength**
   - PASS with caveat.
   - NULL conclusion is supported: 0 / 22 tickers pass Harvey, sign test p=0.416, pooled DM p=0.493.
   - README correctly states that FINRA short-volume data are not true retail order flow.

## Issues

- No blocking code issue found.
- Method caveat: CAPM residual variance is daily close-to-close idiosyncratic variance, not intraday realized idio RV.
- Data caveat: the retail-tilted basket is manually selected and survivorship-biased.

## Must Fix Before Publication

- Do not publish as "retail order flow predicts idiosyncratic volatility."
- Safe phrasing: "A public FINRA off-exchange proxy does not provide robust next-day idiosyncratic-volatility forecasting power in a retail-tilted basket."

## Review Result

The experiment can be recorded as a NULL result for the public-data proxy. It should not be promoted to a production signal or used as direct evidence about true retail order-flow behavior.
