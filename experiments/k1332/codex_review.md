# K1332 Codex Code Review

**Date**: 2026-06-14 16:52 台灣時間
**Reviewer**: Codex desktop / GPT-5
**Verdict**: **PASS_NARROW_CREDIT_ONLY**

## Verdict

K1332 passes as a narrow public-market proxy finding. The code uses adjusted-close yfinance data, constructs private-credit proxy features from `BIZD` plus listed BDCs, applies explicit one-day lags to predictive features, and evaluates rolling expanding OOS forecasts from `2021-01-04`. The conclusion is now appropriately scoped: the private-credit proxy improves `BKLN` and `HYG` RV forecasts at Harvey strength, but not `KRE` or `IWM`.

This should not be promoted as direct evidence from private-credit loan tape, non-traded NAV marks, or borrower-level defaults. It is a liquid listed-BDC / ETF shadow-stress result.

## Checks

1. **Lookahead safety**
   - Target RV is same-day squared close-to-close log return.
   - Predictive target HAR features use `.shift(1)`.
   - Private-credit features use `.shift(1)`.
   - Stress flag uses `raw_stress.shift(1)`.
   - OOS forecasts fit only on rows before the forecast row.

2. **Seed discipline**
   - `SEED = 42`.
   - Moving block bootstrap uses `np.random.default_rng(SEED)`.

3. **Fair comparison**
   - `har` vs `har_pc` and `har_market` vs `har_market_pc` use the same target rows and expanding-window OLS machinery.
   - DM tests compare pointwise QLIKE losses over the same OOS dates.

4. **Conclusion strength**
   - `BKLN` and `HYG` show Harvey-strength incremental QLIKE improvements.
   - `KRE` and `IWM` worsen with private-credit features.
   - Results JSON and README use `PASS_NARROW_CREDIT_ONLY`, avoiding an overbroad all-market pass.

5. **Disclosure**
   - README and JSON both state that true private-credit loan tape, NAV marks, non-traded BDC flows, and borrower-level defaults are blocked.

## Residual Risks

- BIZD and listed BDC equities can load on equity discount-rate shocks, not only private-credit credit quality.
- `BKLN` has very low daily RV outside stress windows, so event ratios can look large. The stronger evidence is the rolling OOS QLIKE + DM result, not the event ratio alone.
- The experiment uses daily squared returns as an RV proxy; it is not an intraday realized variance study.
