# Codex Review: K1525

- Task: `research_idiosyncratic_vol_icapm_covariance_risk_proxy_ex`
- Date: 2026-06-17
- Verdict: `PASS_MIXED_RESULT`

## Checks

- **Lookahead**: PASS. Daily CAPM residual volatility and aggregate proxies are formed with data available by month-end `t`. `stock_excess_next` and `target_next` use `.shift(-1)` only to align the next-month target in the evaluation table. Recursive OOS fitting uses rows before the forecast row.
- **OOS design**: PASS. The monthly forecast comparison uses expanding OLS and an expanding historical-mean baseline. The OOS window starts `2012-01-31`, with 173 monthly forecasts for the full-coverage models.
- **DM / Harvey**: PASS. Forecast tests use `volpred.stats.model_evaluation.dm_test` on squared forecast errors with `h=1`. No idiosyncratic-volatility timing model passes the `DM t < -3` Harvey threshold.
- **Fama-MacBeth claim**: CONDITIONAL PASS. The current-name large-cap proxy gives `gamma_idio=0.00514`, HAC `t=4.063`, but this is not a CRSP/survivorship-free test and should be described only as proxy evidence.
- **Claim strength**: PASS. The experiment verdict is mixed: cross-sectional pricing signal survives, but market excess-return timing is null. This avoids overclaiming the ICAPM proxy as a tradable timing signal.

## Key Numbers

- Fama-MacBeth idio-vol gamma: `t=4.063`.
- Annualized Q5-minus-Q1 next-month spread: `+16.18%`.
- Best idio timing model: `LWIV`, OOS R² `-0.122%`, DM `t=0.769`.
- Best overall model: `market_vol_control`, OOS R² `+0.234%`, DM `t=-0.486`, not significant.
- Idio timing Harvey pass count: `0/7`.

## Risks

- The universe is current-name and large-cap, so survivorship bias likely inflates cross-sectional spreads.
- Dollar-volume weighting is not market-cap weighting.
- `CBIV_spread` and `hedge_cov_36m` are proxies, not the exact Han-Li CBIV object.
- `SHY` is a cash proxy, not a matched one-month T-bill excess-return construction.

## Conclusion

K1525 is safe as a mixed/null timing result: it supports further investigation of idio-vol cross-sectional pricing, but it does not support a publication-grade claim that cross-sectional idio-vol predicts next-month market excess returns.
