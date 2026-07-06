# Codex 24h Review - mile_4518e9d8 (K1590)

- Review date: 2026-07-06
- Reviewer: Codex CLI
- Task id: `paper_review_mile_4518e9d8`
- Article id: `mile_4518e9d8`
- Article status: `published`
- Linked experiment: `experiments/k1590`
- Evidence file: `experiments/k1590/k1590_diagnostic_results.json`

## Verdict

`PASS_WITH_CAVEATS`

The article's published quantitative claims are supported by K1590's stored diagnostic results. I found no evidence that the article presents a forecast, trading strategy, DM/Harvey test, or investment recommendation. The main caveat is interpretive: K1590 studies daily MNA ETF behavior as a portfolio proxy, not individual deal spreads or deal-break events.

## Number Checks

| Article claim | Evidence field | Stored value | Review |
|---|---:|---:|---|
| 1,629 trading days, 2020-2026 | `meta.period.n_trading_days`; `meta.period.start/end` | 1629; 2020-01-01 to 2026-07-01 | OK |
| Low-VIX MNA daily shock about 0.21% | `vol_regime_test.low_vix_lt20.mean_abs_ret` | 0.0021013888 | OK |
| High-VIX MNA daily shock about 0.64% | `vol_regime_test.high_vix_gt30.mean_abs_ret` | 0.0064089649 | OK |
| High/low volatility ratio about 3x | `vol_regime_test.magnitude_ratio_high_over_low` | 3.0498710 | OK |
| Difference statistically significant, p < 0.001 | `vol_regime_test.p_value` | 8.7889e-07 | OK |
| MNA/SPY correlation about 0.52 | `correlations.pearson.MNA.SPY` | 0.5170432 | OK |
| MNA skew -2.89 | `full_sample_stats.MNA.skew` | -2.8883908 | OK |
| MNA excess kurtosis 66.4 | `full_sample_stats.MNA.kurt_excess` | 66.4031087 | OK |
| SPY skew about -0.6 | `full_sample_stats.SPY.skew` | -0.5538163 | OK |
| SPY excess kurtosis about 13.6 | `full_sample_stats.SPY.kurt_excess` | 13.5681977 | OK |

## Lookahead and Framing Audit

K1590's primary regime comparison classifies same-day MNA absolute log returns by same-day VIX level. This is not forward-looking evidence, but the article correctly frames it as a descriptive diagnostic and explicitly says it is not a prediction test. The experiment also stores a lagged robustness check under `vol_regime_test.robustness_lag1_vix_classification`, with `p_value = 4.3265e-06`, which reduces concern that the descriptive pattern depends only on same-day classification.

The article does not claim strategy alpha, portfolio performance, or stability versus a 50/50 benchmark. It also does not invoke DM, Harvey correction, or out-of-sample forecast superiority. The statistical language is therefore acceptable for a general-audience diagnostic article, as long as the current caveats remain visible.

## Caveats to Preserve

- The phrase-level interpretation that MNA is reflecting "deal-break concern" is an economic reading of a merger-arbitrage ETF proxy, not a directly tested per-deal mechanism.
- K1590 uses daily ETF data and absolute daily log returns; it does not use individual deal spreads, intraday prices, or event-level merger announcement windows.
- The VIX threshold comparison is descriptive. It should not be reused as a trading rule without a separate lagged, cost-aware, out-of-sample strategy test.

## Conclusion

No article correction is required from this review. Keep the article bounded as descriptive evidence from K1590, with no upgrade to forecast, causal, or investment-advice language.
