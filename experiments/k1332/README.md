# K1332: Private-Credit Public-Market Shadow Stress Proxy

## Question

Can liquid public-market proxies for private-credit stress, especially BDC and loan-market instruments, lead realized volatility in high-yield credit, loan ETFs, regional banks, and small caps?

## Motivation

Private credit is increasingly important, but direct loan tape, non-traded fund NAV marks, borrower defaults, and fund flows are not fully observable in public daily data. The practical question is whether listed BDCs and loan/credit ETFs provide an early warning signal before broader public credit and small-cap volatility rises.

This experiment is intentionally a public-proxy pilot. It does not claim to observe private-credit loan performance directly.

## Literature Checked

- Financial Stability Board, `Report on Vulnerabilities in Private Credit` (2026). The FSB estimates private credit at roughly USD 1.5-2.0 trillion, highlights bank/nonbank interlinkages, borrower credit quality, valuation opacity, leverage, liquidity mismatch, and data gaps: <https://www.fsb.org/2026/05/report-on-vulnerabilities-in-private-credit/>
- Federal Reserve FEDS Notes, `Bank Lending to Private Credit: Size, Characteristics, and Financial Stability Implications` (2025). The note defines private credit as nonbank lending to mid-market borrowers, including BDCs, and documents bank credit lines to private-credit vehicles: <https://www.federalreserve.gov/econres/notes/feds-notes/bank-lending-to-private-credit-size-characteristics-and-financial-stability-implications-20250523.html>
- IMF Global Financial Stability Report chapter, `The Rise and Risks of Private Credit` (2024). This motivates monitoring private credit because of borrower fragility, opacity, and valuation concerns: <https://www.elibrary.imf.org/display/book/9798400257704/CH002.xml>
- VanEck BIZD product materials. BIZD is used here because it is a liquid ETF designed to track publicly traded BDCs, which lend to small and midsize private companies: <https://www.vaneck.com/us/en/investments/bdc-income-etf-bizd/>

## Related Knowledge Search

Searches in `storage/memory/knowledge.json`, `research_program.md`, `experiments/`, and `docs/error_log.md` for `private credit`, `BDC`, `BIZD`, `BKLN`, `HYG`, `LQD`, `KRE`, and `credit stress` found several related credit-proxy findings but no completed private-credit / BDC shadow-stress experiment.

Relevant prior constraints:

- HYG/LQD and broader bond-stress features often become redundant once VIX or own-HAR volatility is included.
- Public credit signals can show descriptive stress association while failing rolling OOS QLIKE tests.
- Same-day credit stress cannot be paired with same-day target return or volatility.

## Data

- Source: yfinance adjusted close.
- Requested sample: `2013-02-11` to `2026-06-14`.
- Private-credit public proxy: equal-weight return of available listed BDC proxies:
  - `BIZD`, `ARCC`, `MAIN`, `GBDC`, `PSEC`, `HTGC`
- Credit / public-market targets:
  - `BKLN`: senior loan ETF
  - `HYG`: high-yield bond ETF
  - `KRE`: regional bank ETF
  - `IWM`: small-cap equity ETF
- Controls:
  - `SPY`, `^VIX`, `LQD`

## Method

1. Build close-to-close log returns and squared daily returns.
2. Build private-credit proxy features:
   - lagged private-credit log RV;
   - 5-day lagged private-credit log RV;
   - lagged private-credit downside return;
   - lagged 63-day drawdown;
   - lagged 20-day BDC underperformance versus LQD.
3. Define a private-credit stress event when private-credit proxy log RV is above its lagged rolling 252-day 90th percentile or lagged drawdown is in its rolling 10th percentile tail.
4. Apply explicit timing discipline: `pc_stress_signal_lag1 = raw_stress.shift(1)`.
5. Run event diagnostics comparing next-day and forward-5-day target RV after lagged private-credit stress versus non-stress days, with 5-day moving block bootstrap and `seed=42`.
6. Fit HAC regressions of target log RV on own-HAR lags plus market and private-credit features.
7. Run expanding-window OOS forecasts from `2021-01-04`:
   - `har`: target own-HAR lags;
   - `har_market`: own-HAR plus lagged SPY/VIX volatility;
   - `har_pc`: own-HAR plus lagged private-credit features;
   - `har_market_pc`: own-HAR plus market plus private-credit features.
8. Evaluate by QLIKE and DM-HLN. Strict success requires lower QLIKE and Harvey-style `|t| > 3`.

## Lookahead Controls

- All predictive private-credit and market features are shifted by one trading day.
- The private-credit stress event flag is `raw_stress.shift(1)`.
- OOS forecasts at day `t` fit only on rows strictly before `t`.

## Reproduction

```bash
uv run python experiments/k1332/k1332.py
```

Expected artifacts:

- `k1332_results.json`
- `k1332_private_credit_event.png`
- `k1332_oos_qlike_delta.png`

## Success Criteria

- Complete three-piece experiment package.
- Honest disclosure that the proxy is public BDC / ETF market data, not private-credit loan tape.
- Formal QLIKE and DM tests, not chart-only interpretation.
- Null result reported as such if private-credit features do not improve rolling OOS forecasts.

## Results

Status: `PASS_NARROW_CREDIT_ONLY`.

The lagged private-credit proxy stress event is followed by higher next-day RV for all four targets, but the ratios are largest for the direct credit / loan targets:

| Target | Next-day stress / non-stress RV | Bootstrap p | Stress days |
|---|---:|---:|---:|
| BKLN | 12.517 | 0.009 | 640 |
| HYG | 4.630 | 0.001 | 640 |
| KRE | 2.289 | 0.005 | 640 |
| IWM | 2.811 | 0.001 | 640 |

Rolling OOS results are more selective. Private-credit features improve `BKLN` and `HYG` forecasts at Harvey strength, both against own-HAR and against HAR+market controls:

| Target | HAR QLIKE | HAR+PC QLIKE | HAR+market QLIKE | HAR+market+PC QLIKE | Strong PC win? |
|---|---:|---:|---:|---:|---|
| BKLN | 13.620 | 12.137 | 13.515 | 12.294 | Yes |
| HYG | 3.576 | 3.320 | 3.604 | 3.365 | Yes |
| KRE | 3.966 | 4.028 | 3.975 | 4.038 | No |
| IWM | 3.188 | 3.236 | 3.187 | 3.238 | No |

DM-HLN tests:

| Pair | DM t | p | QLIKE improvement |
|---|---:|---:|---:|
| BKLN HAR vs HAR+PC | 3.639 | 0.00028 | 10.89% |
| BKLN HAR+market vs HAR+market+PC | 3.343 | 0.00085 | 9.03% |
| HYG HAR vs HAR+PC | 3.452 | 0.00057 | 7.14% |
| HYG HAR+market vs HAR+market+PC | 3.230 | 0.00127 | 6.63% |
| KRE HAR vs HAR+PC | -0.876 | 0.381 | -1.57% |
| IWM HAR vs HAR+PC | -0.945 | 0.345 | -1.51% |

## Conclusion

K1332 supports a narrow conclusion: listed BDC / private-credit proxies contain useful lagged information for public loan and high-yield credit volatility (`BKLN`, `HYG`) beyond own-HAR and SPY/VIX volatility controls. The evidence does not support a broader claim that the same proxy improves regional-bank (`KRE`) or small-cap (`IWM`) RV forecasts.

The result should be framed as a public-market shadow-stress finding, not as evidence from private-credit loan tape or non-traded NAV marks.
