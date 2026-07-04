# research_garch_midas_horizon_garch_har

## Verdict

`NULL_NO_HARVEY_MIDAS_EDGE`

On daily yfinance close-to-close variance proxies, an RV-driven MIDAS long-run
component does **not** improve 22- or 66-trading-day variance forecasts relative
to HAR or single-component GARCH baselines. The strongest pooled model at both
horizons is plain HAR, but even HAR's edge over GARCH does not clear the strict
Harvey-style `|t| > 3` reporting bar.

This is a daily-data component-MIDAS proxy test. It is not a full
Engle-Ghysels-Sohn GARCH-MIDAS MLE replication, so the conclusion is limited to
the tested daily proxy design.

## Motivation

The research backlog asked whether GARCH-MIDAS-style two-component
decomposition helps at longer horizons, where the slow-moving long-run component
should, in theory, matter more than it does for one-day volatility.

This extends but does not duplicate K526. K526 tested one-step SPY
GARCH-MIDAS and found no robust OOS win over GJR-GARCH. This experiment changes
the target to genuine forward multi-day average variance at `H=22` and `H=66`.

Related prior context:

- K526: GARCH-MIDAS-RV/VIX did not beat GJR-GARCH OOS; long-run tau explained
  limited variance.
- K785: MF2-GARCH did not produce a clean Harvey-pass win.
- K1001: VIX GARCH-X beat macro/MIDAS-style alternatives in the paper-period
  setup.
- K782v2 / K1473: longer daily-proxy horizons do not automatically make HAR or
  long-memory methods dominate.
- K1624: apparent long memory in daily volatility proxies is largely
  level-shift driven, so a long-run component needs an OOS test, not just an
  intuitive persistence story.

## Data

- Source: yfinance daily adjusted OHLCV.
- Assets: SPY, QQQ, GLD.
- Download window: 2005-01-01 to 2026-07-04.
- Effective daily return sample: 2005-01-04 to 2026-07-02.
- Daily returns per asset: 5,407.
- OOS forecast origins begin 2015-01-01.
- GARCH fitting failures: 0 for all three assets.

## Method

Target:

`mean(r^2_{t+1}, ..., r^2_{t+H})`, with `H in {22, 66}`.

Models:

- `GARCH_raw`: rolling GARCH(1,1) normal baseline, 1,500-day window, refit
  every 63 trading days, then converted to an H-step average variance forecast.
- `GARCH_log`: log-OLS calibration of the GARCH forecast.
- `HAR`: horizon-specific log-HAR using `r2_t`, 5-day average variance, and
  22-day average variance.
- `Component_MIDAS`: daily GARCH-MIDAS proxy using log GARCH short-run forecast
  plus a fixed-beta 12-block MIDAS long-run RV component.
- `HAR_MIDAS`: HAR plus the same fixed-beta MIDAS long-run component.

Lookahead guard:

- Forecast features use information through origin day `t`.
- The target starts at `t+1`.
- OOS training rows require `j + H < i`, so each training target is fully
  completed before forecast origin `i`.
- Multi-asset pooled DM tests average loss differentials by date before
  inference, following the K1355 guard against asset-day iid inflation.

Inference:

- Primary loss: canonical Patton QLIKE via
  `volpred.stats.model_evaluation.qlike_pointwise`.
- Pairwise tests: canonical HAC DM helper with `h` set to the forecast horizon.
- Reporting gate: `|t| > 3`.

## Results

| Horizon | Best pooled model | HAR QLIKE | GARCH QLIKE | Component MIDAS vs HAR | HAR+MIDAS vs HAR |
| --- | --- | ---: | ---: | ---: | ---: |
| 22d | HAR | 0.3326 | 0.3536 | -13.78%, t=+1.50 | -5.25%, t=+0.88 |
| 66d | HAR | 0.3681 | 0.3939 | -12.85%, t=+1.75 | -2.04%, t=+0.61 |

Negative improvement means the MIDAS-augmented model has higher QLIKE loss than
HAR. Positive t-stat in the two MIDAS-vs-HAR rows also means the MIDAS model has
higher loss. Neither horizon is close to the strict `|t| > 3` gate.

HAR vs GARCH:

- H=22: HAR improves pooled QLIKE by 5.95%, DM t=-1.57.
- H=66: HAR improves pooled QLIKE by 6.56%, DM t=-1.94.

So the data weakly favors HAR over rolling GARCH at long horizons, but the
formal evidence is not strong enough to call HAR a Harvey-pass winner.

## Interpretation

The long horizon alone does not rescue the MIDAS long-run component. In this
daily proxy design, adding fixed-beta RV-MIDAS information to either GARCH or
HAR makes average QLIKE worse, not better. The result is therefore another null
against the claim that a slow volatility component is a free OOS improvement.

The conservative takeaway is:

> For SPY/QQQ/GLD daily close-to-close variance forecasts at 22- and 66-day
> horizons, a simple HAR baseline is hard to beat; the tested RV-MIDAS long-run
> component adds no robust OOS value.

## Limitations

- Daily close-to-close `r^2` is a noisy variance proxy; this is not a 5-minute
  realized-variance replication.
- `Component_MIDAS` is a daily component-MIDAS proxy with fixed weights, not a
  full joint GARCH-MIDAS MLE.
- The MIDAS driver uses rolling 22-trading-day blocks rather than calendar
  macro releases. This is intentional because the experiment asks about
  RV-driven long-run variance, not macro fundamentals.
- Only three liquid ETFs are tested.
- A full follow-up could re-estimate true GARCH-MIDAS MLE at each OOS refit,
  but that is a heavier compute task and must still respect the same
  target-end embargo.

## References

- Engle, Ghysels, and Sohn (2013), "Stock Market Volatility and Macroeconomic
  Fundamentals," *Review of Economics and Statistics*.
- Corsi (2009), "A Simple Approximate Long-Memory Model of Realized
  Volatility," *Journal of Financial Econometrics*.
- Hansen and Lunde (2005), "A Forecast Comparison of Volatility Models,"
  *Journal of Applied Econometrics*.
- Patton (2011), "Volatility Forecast Comparison Using Imperfect Volatility
  Proxies," *Journal of Econometrics*.
- Diebold and Mariano (1995), "Comparing Predictive Accuracy," *Journal of
  Business & Economic Statistics*.
- Conrad and Loch (2015), "Anticipating Long-Term Stock Market Volatility,"
  *Journal of Applied Econometrics*.

## Artifacts

- `research_garch_midas_horizon_garch_har.py`: reproducible script.
- `research_garch_midas_horizon_garch_har_results.json`: structured results.
- `midas_horizon_qlike_improvement.png`: pooled QLIKE improvement figure.
- `codex_review.md`: source-level review and conclusion-bound check.

Reproduce:

```bash
uv run python experiments/research_garch_midas_horizon_garch_har/research_garch_midas_horizon_garch_har.py
```
