# K475: Simple Ensemble Of Validated Volatility Methods

## Summary

K475 tests whether simple equal-weight forecast combinations can reduce the tradeoff between volatility forecast accuracy and VaR reliability for SPY. The experiment combines previously validated model families:

- `GJR`: GJR-GARCH(1,1) with Student-t innovations.
- `HAR`: HAR log-range forecast, converted from Parkinson variance scale to squared-return scale for r2-proxy evaluation.
- `Semi`: HAR-style semivariance model using positive and negative realized semivariance components.
- Ensemble variants: `Ens_3way`, `Ens_GJR_HAR`, `Ens_GJR_Semi`, and `Ens_HAR_Semi`.

## Data And Method

- Data source: yfinance SPY OHLC data.
- Effective sample: 2005-02-02 to 2026-03-25, 5319 daily observations after feature construction.
- Forecast design: rolling 2000-day estimation window, evaluated across five OOS periods: 2015-2016, 2017-2018, 2019-2020, 2021-2022, and 2023-2025.
- Forecast metrics: QLIKE against squared-return proxy and Parkinson range-based proxy.
- Significance check: Diebold-Mariano comparison with HAC variance, ensemble versus best single model per period.
- VaR backtest: 2021-01-04 to 2024-12-31, 1005 observations, Normal VaR at 1% and 5%, checked with Kupiec, Christoffersen, and DQ tests.

All OOS forecasts use an estimation window ending before the target date. No same-day signal is used to forecast the same-day return.

## Key Results

- `Ens_GJR_HAR` has the lowest five-period average QLIKE under the r2 proxy: 0.694465 versus HAR 0.736682 and GJR 0.742422.
- Its r2-proxy ranks across the five OOS periods are `2, 1, 1, 1, 4`, for an average rank of 1.8 out of 7 models.
- `Ens_GJR_HAR` has the lowest five-period average Parkinson-proxy QLIKE: 0.252176.
- At 1% VaR over 2021-2024, `Ens_GJR_HAR` passes all three tests with 16 violations out of 1005 observations, violation rate 1.59%, and Kupiec p=0.0824.
- GJR fails the 1% Kupiec test in the same VaR window with 22 violations, violation rate 2.19%, and Kupiec p=0.0011.
- None of the five r2-proxy DM comparisons for `Ens_GJR_HAR` versus the best single model reaches 5% significance. The result is a stable ranking pattern, not a strong statistical dominance claim.

## Article Review Note

Codex 24h review on 2026-06-12 found one production-article overstatement: the article said `Ens_GJR_HAR` ranked first in three periods and top-three in the other two. The source results show ranks `2, 1, 1, 1, 4`; the published article was corrected through `scripts/publish_draft.py --update`.

## Artifacts

- Script: `experiments/k475/k475_validated_ensemble.py`
- Results: `experiments/k475/k475_validated_ensemble_results.json`
- Figures: `experiments/k475/k475_cross_oos_qlike_rank.png`, `experiments/k475/k475_var_1pct_backtest.png`
- Review record: `experiments/k475/reviews/paper_review_mile_c5881a5b_codex_20260612.md`
