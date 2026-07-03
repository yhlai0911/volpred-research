# Firm-Level Labor-Shortage Exposure Public Proxy

## Purpose

This experiment tests whether a public proxy for firm-level labor-shortage
exposure predicts subsequent idiosyncratic volatility for wage-sensitive listed
firms.

The test is deliberately narrower than the RFS labor-shortage exposure paper:
it uses SEC 10-K/10-Q phrase counts plus BLS JOLTS industry tightness, not
earnings-call transcript FinBERT scores or the paper's private replication
inputs.

## Data

- Sample window for prices: 2021-01-01 through 2026-07-03.
- Regression panel after first scored filing per ticker: 2023-07-13 through
  2026-07-02.
- Firms: 24 wage-sensitive tickers:
  `AMZN`, `CAT`, `CMG`, `COST`, `DAL`, `DE`, `DG`, `DHI`, `FDX`, `HCA`, `HD`,
  `HLT`, `LEN`, `LOW`, `LUV`, `MAR`, `MCD`, `PHM`, `SBUX`, `TGT`, `THC`, `UAL`,
  `UPS`, `WMT`.
- Industry controls: `XHB`, `XRT`, `IYT`, `XLY`, `XLV`, `XLI`; `AIQ` is used
  for an automation/AI relative-volatility diagnostic.
- SEC filings scored: `288` total, with `216` 10-Q and `72` 10-K filings.
- SEC download failures: `0`.
- SEC filing dates: 2023-07-13 through 2026-06-29.
- Phrase counts in scored filings: `181` core labor-shortage hits, `442` wage
  pressure hits, `873` automation hits.
- BLS JOLTS: `77` monthly observations across `6` industries.
- Regression panel rows: `17420`.
- Random seed: `42`.

## Method

Signal construction:

- SEC text score: phrase-count proxy from 10-K/10-Q text using labor-shortage
  and wage-pressure patterns.
- BLS JOLTS tightness: industry job-openings rate minus quits rate, transformed
  into a rolling 60-month z-score.
- Primary combined signal: lagged SEC text score times lagged JOLTS tightness.
- Auxiliary signals: SEC-only and JOLTS-only diagnostics.

Lookahead controls:

- SEC score enters only after filing date and one trading-day lag.
- JOLTS is assumed observable 35 calendar days after month end, then shifted one
  trading day.
- Forward RV/downside targets start at t+1.
- Rows before each ticker has a scored filing are excluded rather than treated
  as zero exposure.

Targets:

- 5d and 22d firm idiosyncratic RV relative to industry ETF controls.
- 5d and 22d idiosyncratic downside semivariance.
- 5d and 22d firm RV relative to `AIQ`.

PASS gate:

- Combined SEC x JOLTS coefficient must be positive.
- Clustered t-stat must be at least `3.0`.
- High-minus-low signal bucket difference must be positive with Welch t-stat at
  least `3.0`.

## Results

Verdict: **NULL_PUBLIC_PROXY_DIAGNOSTIC**.

Primary combined signal:

| Target | Horizon | Beta | Clustered t | High-low diff | Welch t | Gate |
|---|---:|---:|---:|---:|---:|---|
| idio RV | 5d | `-0.01707` | `-0.6520` | `-0.00673` | `-0.3264` | fail |
| downside | 5d | `-0.05307` | `-0.6605` | `0.00277` | `0.0344` | fail |
| AIQ-relative RV | 5d | `0.01596` | `0.7317` | `0.08477` | `4.1869` | fail |
| idio RV | 22d | `-0.01497` | `-0.6502` | `0.03136` | `2.2554` | fail |
| downside | 22d | `-0.03391` | `-0.8123` | `0.06883` | `3.4554` | fail |
| AIQ-relative RV | 22d | `0.00152` | `0.0635` | `0.10299` | `7.6744` | fail |

Summary:

- Combined signal formal pass count: `0/6`.
- Combined directional positive count: `2/6`.
- Strongest combined coefficient is AIQ-relative 5d RV: beta `0.01596`,
  clustered t `0.7317`, p `0.4643`; high-low buckets are positive, but the
  coefficient gate fails.
- Strongest auxiliary result is JOLTS-only 5d idiosyncratic RV: beta `0.04166`,
  clustered t `2.9105`, p `0.00361`, high-low Welch t `4.7829`. This is a
  near miss under the t>=3 gate and is not a firm-level SEC text result.

## Interpretation

The public firm-level proxy does not support the claim that SEC labor-shortage
language combined with industry JOLTS tightness robustly predicts next-week or
next-month idiosyncratic volatility.

The only economically interesting pattern is industry-level: lagged JOLTS
tightness is directionally associated with higher idiosyncratic RV, but the
strongest clustered t-stat is `2.9105`, below the `3.0` gate. This should be
treated as a follow-up lead, not a finding.

## Outputs

- `research_firm_level_labor_shortage_exposure_wage_sensitiv.py`
- `research_firm_level_labor_shortage_exposure_wage_sensitiv_results.json`
- `data/sec_filing_index.csv`
- `data/sec_labor_filing_scores.csv`
- `data/jolts_industry_monthly.csv`
- `data/price_adjusted_close.csv`
- `data/firm_daily_regression_panel.csv`
- `figures/labor_shortage_proxy_summary.png`
- `codex_review.md`

## Limitations

- This is a phrase-count public proxy, not the RFS earnings-call FinBERT
  measure.
- The firm universe is hand-built and small.
- The SEC text sample uses recent 10-K/10-Q filings, so the regression panel
  starts only after each ticker has a scored filing.
- JOLTS industry data are broad monthly aggregates, not firm-specific local labor
  markets.
- SEC risk-factor language is sticky and legalistic; phrase counts can reflect
  disclosure style as well as true exposure.
- Daily close-to-close returns miss intraday filing/news timing.
