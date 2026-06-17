# K1529 — Credit-spread FOMC volatility precursor ETF-proxy pilot

## Motivation

This experiment tests the backlog idea:

> 價格剛性行業 credit spread 對 FOMC 衝擊敏感度差異，是否能作為 SPY realized volatility 的前哨？

The original backlog suggested Cleveland/FRED surprise data plus industry-level
credit-spread responses. In this first reproducible hourly-run version, I use a
public SF Fed monetary-policy-surprise CSV and free daily ETF proxies. This is
therefore an ETF-proxy pilot, not a firm-level or TRACE bond-level credit-spread
study.

## Literature And Prior-K Context

External references checked before running:

- Augustin, Cong, Corhay, and Weber, "Price Rigidities and Credit Risk", JFQA:
  sticky-price firms experience larger credit-spread responses to monetary
  policy shocks.
  https://jfqa.org/2025/12/04/price-rigidities-and-credit-risk/
- SF Fed Monetary Policy Surprises data: public FOMC surprise series based on
  money-market futures around FOMC announcements.
  https://www.frbsf.org/research-and-insights/data-and-indicators/monetary-policy-surprises/
- Bernanke and Kuttner (2005): canonical monetary-policy surprise event-study
  framing for asset-price reactions.
  https://www.newyorkfed.org/research/staff_reports/sr174.html
- Gilchrist and Zakrajsek (2012): credit spreads contain macro-financial stress
  information, but this experiment only tests a narrow ETF proxy.
  https://www.aeaweb.org/articles?id=10.1257%2Faer.102.4.1692

Related VolPred priors:

- K513: FOMC event-day volatility is elevated, but FOMC-aware exposure reduction
  did not improve strategy Sharpe.
- K651 / T14 / G5 / K730: credit-spread and cross-asset stress signals are
  usually absorbed by VIX or too small for daily SPY vol timing.
- K1515: HYG illiquidity feature-importance claims need AR-only feature-set
  testing.
- K1522: corporate-bond ETF factor proxies do not rescue factor-zoo premia after
  conservative lag discipline.

## Data

- Price data: yfinance daily OHLC with `auto_adjust=False`
- Surprise data: SF Fed chart CSV
- Sample after alignment: 102 FOMC events, 2012-01-25 to 2023-12-13
- OOS split: 2019-01-01
- Credit ETF proxies: HYG, LQD, VCIT, VCSH
- Market controls: SPY, ^VIX
- Sticky sector proxy: XLP, XLU, XLV
- Flexible sector proxy: XLE, XLB, XLK

The SF Fed chart CSV used here stops at 2023-12-13 even though price data are
available through 2026-06-17. Extending to 2026 requires switching to USMPD or a
separately constructed surprise proxy; this run does not mix methodologies.

## Method

Headline credit-stress proxy:

```text
credit_stress = -(log_return(HYG) - log_return(LQD))
```

Positive values mean HYG underperformed LQD, interpreted as high-yield spread
stress relative to investment-grade credit.

Tests:

1. FOMC event window t0 to t+5 versus same-month non-event baseline, excluding
   all FOMC +/-5 trading days.
2. HAC OLS: credit stress t0 to t+5 on absolute orthogonalized surprise, lagged
   VIX variance, and pre-FOMC credit stress.
3. HAC OLS: sticky-minus-flexible sector RV on surprise, lagged VIX variance,
   and credit response.
4. OOS log-RV model: pre-FOMC credit stress predicts SPY RV t0 to t+5 beyond
   lagged SPY RV and VIX.
5. OOS log-RV model: credit response t0 to t+5 predicts SPY RV t+6 to t+26
   beyond lagged SPY RV, VIX, and surprise.

Multiple-testing discipline: 5 headline tests, Bonferroni alpha = 0.01. OOS
model comparison uses Patton QLIKE and DM HAC with h=5; Harvey pass requires
DM t < -3.

## Results

Verdict: `NULL_ETF_PROXY`.

Key numbers from `k1529_credit_spread_fomc_vol_results.json`:

- FOMC HYG-LQD stress event mean: 0.000115
- Same-month baseline mean: -0.000342
- Paired difference mean: 0.000457
- Paired t-test p-value: 0.737580
- Wilcoxon one-sided p-value: 0.340171
- Block-bootstrap one-sided p-value: 0.376623
- Surprise-to-credit HAC coefficient t-stat: 1.9229, not Bonferroni-significant
- Sticky/flexible diagnostic credit coefficient t-stat: -2.0745, exploratory only
- Pre-FOMC credit OOS model worsens SPY RV t0 to t+5 QLIKE by -13.85%
- Post-response credit model improves SPY RV t+6 to t+26 QLIKE by 5.92%, but
  DM t = -1.294, far below Harvey strength

Conclusion: in this free-data ETF-proxy specification, corporate-bond ETF credit
stress does not provide Harvey-strength incremental information for SPY realized
variance around FOMC meetings. The strongest-looking effect is the post-response
model's small OOS QLIKE improvement, but it is not statistically strong enough
to support a research or article claim beyond an exploratory null.

## Lookahead Checks

- Pre-FOMC model predictors use only t-1 or earlier data; target is t0 to t+5.
- Post-response model uses credit response from t0 to t+5, but the target starts
  at t+6, so predictor and target windows do not overlap.
- No same-day signal is multiplied by same-day returns for a strategy.
- Event dates are public FOMC dates; surprise magnitude is only used after the
  announcement window or for descriptive event-response regressions.

## Limitations

- ETF proxies are not bond-level credit spreads and blend duration, liquidity,
  fund structure, and credit quality.
- Sector baskets are crude price-rigidity proxies, not NFIB, markup, or
  firm-level price-duration measures.
- Daily data cannot isolate the 2pm ET FOMC announcement window.
- The surprise CSV ends in 2023, so this does not cover the full 2024-2026
  high-rate regime.

## Reproduction

```bash
uv run python experiments/k1529_credit_spread_fomc_vol/k1529_credit_spread_fomc_vol.py
```

Artifacts:

- `experiments/k1529_credit_spread_fomc_vol/k1529_credit_spread_fomc_vol.py`
- `experiments/k1529_credit_spread_fomc_vol/k1529_credit_spread_fomc_vol_results.json`
- `experiments/k1529_credit_spread_fomc_vol/k1529_credit_spread_fomc_vol.png`
