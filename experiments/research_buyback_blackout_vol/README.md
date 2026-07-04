# Buyback Blackout Coverage vs SPY Volatility

**Verdict: NULL_OR_PROXY_LIMITED**

## Question

Do periods when a large share of major S&P 500 constituents are plausibly in
issuer-repurchase blackout windows have systematically higher SPY realized
volatility?

The economic story is intuitive: if issuer buybacks are a meaningful source of
liquidity or price support, then the synchronized disappearance of that bid
around earnings could raise market-level volatility. The test below asks whether
that calendar proxy survives basic controls and an OOS forecast gate.

## Data

| Item | Specification |
|---|---|
| Price target | SPY adjusted close from yfinance, 2020-01-02 to 2026-07-02 |
| Volatility proxy | SPY close-to-close squared log return, plus 5-day forward mean variance |
| Universe | Current top-50 large-cap S&P proxy reused from K1510 |
| Weights | Current yfinance `fast_info.market_cap`, normalized within the top-50 proxy |
| Earnings calendar | `yfinance.Ticker.get_earnings_dates(limit=50)` |
| Blackout window | Earnings date minus 35 calendar days through plus 2 calendar days |
| Final daily sample | 1,633 SPY trading days |

Coverage is high for the proxy sample: all 50 tickers had valid market caps and
earnings rows in the model range. The inferred blackout coverage is mechanically
seasonal and often large: mean 42.35%, median 27.69%, 90th percentile 83.06%,
max 93.20% of the top-50 proxy weight.

## Method

1. Build a daily `blackout_coverage` series by flagging each top-50 ticker as in
   blackout during `[earnings_date - 35 calendar days, earnings_date + 2 calendar days]`.
2. Run HAC OLS for same-day descriptive log variance, next-day predictive log
   variance using `blackout_coverage.shift(1)`, and forward 5-day log variance.
3. Control for lagged 5-day RV, lagged 21-day RV, lagged VIX, OPEX window,
   day-of-week FE, and month FE.
4. Compare high-vs-low coverage days with a 1,000-rep 10-day block bootstrap.
5. Run expanding OOS QLIKE from 2022-02-02 to 2026-07-02:
   baseline = HAR-style daily proxy + VIX + OPEX; augmented = baseline +
   `blackout_coverage.shift(1)`.

The publishability gate is deliberately strict: lagged 1-day and 5-day
coefficients must be positive with Harvey `|t| > 3`, and the augmented OOS
model must beat the baseline with DM `t < -3`.

## Results

| Test | Estimate | t / CI | Interpretation |
|---|---:|---:|---|
| Same-day log variance vs coverage | -0.018 log-var per +10pp | t = -0.58 | No descriptive positive relation |
| Next-day log variance vs lagged coverage | +0.0047 log-var per +10pp | t = +0.14 | No predictive effect |
| Forward 5-day log variance vs coverage | -0.0387 log-var per +10pp | t = -1.64 | Wrong sign, not significant |
| High minus low coverage annualized abs return | -2.18 vol points | 95% CI [-7.33, +2.40] | No robust high-coverage premium |
| OOS QLIKE augmented vs baseline | +0.105% improvement | DM t = -0.17 | Economically tiny, statistically null |

## Conclusion

The free-data blackout-coverage proxy does **not** support the claim that
buyback blackout periods are a robust SPY volatility calendar factor. Once
lagged RV, VIX, OPEX, weekday, and month effects are controlled, the next-day
coefficient is essentially zero and the 5-day coefficient has the wrong sign.
The OOS QLIKE improvement is too small to interpret and fails the DM/Harvey
gate.

This is a useful null rather than a definitive refutation. The test only uses a
current top-50 proxy and inferred blackout windows. It cannot observe actual
issuer repurchase activity, 10b5-1 plans, historical constituent weights, or
real-time as-of earnings-calendar revisions.

## References

- Dittmann, Li, Obernberger, and Zheng, "Equity-based compensation and the
  timing of share repurchases: the role of the corporate calendar," Journal of
  Accounting and Economics / SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4084794
- Cook, Krigman, and Leach (2004), "On the Timing and Execution of Open Market
  Repurchases," Review of Financial Studies:
  https://academic.oup.com/rfs/article-abstract/17/2/463/1576952
- SEC Rule 10b-18 FAQ:
  https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/division-trading-markets-answers-frequently-asked-questions-concerning-rule-10b-18-safe-harbor
- SEC Share Repurchase Disclosure Modernization final rule:
  https://www.sec.gov/files/rules/final/2023/34-97424.pdf

## Files

- `research_buyback_blackout_vol.py` - single reproducible script.
- `research_buyback_blackout_vol_results.json` - metrics, metadata, and verdict.
- `blackout_coverage_vs_spy_rv.png` - coverage and SPY RV diagnostic figure.
- `data/market_caps_top50_snapshot.csv` - current market-cap snapshot.
- `data/earnings_dates_yfinance.csv` - raw yfinance earnings calendar rows.
- `data/blackout_coverage_daily.csv` - daily blackout coverage series.
- `data/model_frame.csv` - modeling panel.

## Reproduce

```bash
uv run python experiments/research_buyback_blackout_vol/research_buyback_blackout_vol.py
```
