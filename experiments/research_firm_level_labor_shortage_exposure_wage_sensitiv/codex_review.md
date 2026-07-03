# Codex Review

Reviewer: Codex
Date: 2026-07-03
Experiment: `research_firm_level_labor_shortage_exposure_wage_sensitiv`

## Verdict

**CONDITIONAL_PASS_SOURCE_REVIEW / research verdict NULL_PUBLIC_PROXY_DIAGNOSTIC**

The code is reproducible and the final empirical claim is appropriately narrow.
The public SEC phrase-count plus BLS JOLTS proxy does not pass the pre-specified
firm-level combined-signal gate. The result should be recorded as a null public
proxy diagnostic.

## Checks

- Experiment triplet present:
  - `README.md`
  - `research_firm_level_labor_shortage_exposure_wage_sensitiv.py`
  - `research_firm_level_labor_shortage_exposure_wage_sensitiv_results.json`
- Data sources are explicit:
  - SEC company ticker index and submissions API for 10-K/10-Q filing metadata.
  - SEC filing HTML documents for phrase-count exposure.
  - BLS JOLTS official time-series files for job-openings and quits rates.
  - yfinance adjusted closes for firm and control ETF returns.
- Lookahead controls:
  - SEC filing score is merged by filing date and shifted one trading day.
  - JOLTS month data are assumed observable after 35 calendar days and then
    shifted one trading day.
  - Forward RV/downside targets begin at t+1.
  - Rows before a ticker has an observed scored filing are excluded instead of
    zero-filled.
- Gate logic:
  - PASS requires combined SEC text x JOLTS signal coefficient > 0, clustered
    t-stat >= 3, and positive high-minus-low Welch t-stat >= 3.
  - SEC-only and JOLTS-only tests are auxiliary diagnostics and do not determine
    the firm-level verdict.
- Corrections made during review:
  - Fixed pandas `merge_asof` datetime dtype mismatch by normalizing merge dates.
  - Removed duplicated regression controls for SEC-only/JOLTS-only auxiliary
    specifications to avoid collinearity artifacts.
  - Rebuilt high/low buckets with percentile ranks so tied signal values cannot
    make high and low groups overlap.
  - Removed pre-first-filing rows from the panel to avoid treating unavailable
    SEC text exposure as true zero exposure.

## Result Snapshot

- Overall verdict: `NULL_PUBLIC_PROXY_DIAGNOSTIC`.
- Combined signal formal pass count: `0/6`.
- Combined signal positive-direction count: `2/6`.
- SEC filings scored: `288` (`216` 10-Q, `72` 10-K), with `0` download failures.
- Regression panel: `17420` rows, 2023-07-13 through 2026-07-02.
- Strongest combined result: AIQ-relative 5d RV beta `0.01596`, clustered
  t=`0.7317`, p=`0.4643`; high-low Welch t=`4.1869`, but coefficient gate fails.
- Strongest auxiliary result: JOLTS-only 5d idiosyncratic RV beta `0.04166`,
  clustered t=`2.9105`, p=`0.00361`, high-low Welch t=`4.7829`; near miss but
  below t>=3 and not a firm-level SEC text result.

## Limitations

- The public phrase-count proxy is not a replication of the RFS earnings-call
  FinBERT exposure measure.
- The 24-firm hand-built universe is too small for a broad cross-sectional asset
  pricing claim.
- JOLTS data are monthly industry aggregates and can capture sector-wide labor
  tightness rather than firm-level shortage exposure.
- Filing language can reflect legal disclosure style and risk-factor stickiness.
- Daily close-to-close returns are too coarse for intraday filing and labor-news
  timing.

No blocking source-level defects remain if downstream knowledge/article language
preserves the null verdict and treats the JOLTS-only near miss as exploratory.
