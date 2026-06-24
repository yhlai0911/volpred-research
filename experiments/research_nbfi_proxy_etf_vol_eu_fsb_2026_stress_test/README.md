# NBFI Run-Pressure Proxy and Bank/Credit ETF Risk

## Purpose

This experiment tests whether a pure free-data proxy for non-bank financial
intermediation (NBFI) liquidity pressure leads bank and credit ETF risk. The
question is motivated by FSB/ESRB/ECB attention to NBFI liquidity mismatch,
money market funds, bank-NBFI linkages, and system-wide stress testing.

The design is deliberately separate from K1538. K1538 tested open-end bond-fund
run pressure against credit ETF volatility. This experiment broadens the proxy
to include MMF flow, bank credit, SOFR-IORB funding pressure, and BDC/private
fund public-market pressure, then tests the bank ETF channel directly.

## Pre-Experiment Context

Relevant prior internal results:

- K1332: BIZD/listed BDC stress had narrow OOS QLIKE value for BKLN/HYG, not
  KRE/IWM.
- K1499: BDC RV collapsed after SPY-vol controls; only a BIZD-HYG discount-style
  proxy survived for HYG 5d.
- K1538: bond-fund run-pressure proxy had weak directional evidence but failed
  Harvey/Bonferroni gates.

References checked before design:

- FSB Global Monitoring Report on Non-Bank Financial Intermediation 2025.
- ESRB/ECB 2026 report on bank-NBFI linkages.
- FRED WRMFNS retail money market funds series, which notes ICI weekly data.
- BIS Working Paper 972 on NBFIs and financial stability.

## Data

Public market data:

- yfinance adjusted close and volume: `HYG`, `LQD`, `BKLN`, `BIZD`, `KRE`,
  `KBE`, `XLF`, `SPY`, `^VIX`.

FRED data:

- `WRMFNS`: retail money market funds.
- `MMMFFAQ027S`: total money market funds financial assets.
- `TOTBKCR`: bank credit, all commercial banks.
- `SOFR`, `IORB`: funding/reserve pressure spread.

## Proxy Construction

The NBFI run-pressure proxy is a rolling z-score composite of:

- HYG/BKLN/BIZD ETF dollar-volume shock.
- HYG/BKLN/BIZD Amihud-style ETF illiquidity.
- HYG underperformance versus LQD.
- BIZD underperformance versus HYG as a BDC discount-style stress proxy.
- Retail MMF flow from `WRMFNS`.
- Total MMF asset flow from `MMMFFAQ027S`.
- Bank-credit contraction from `TOTBKCR`.
- SOFR minus IORB spread.

All predictive use goes through:

```python
panel["run_pressure_lag1"] = panel["run_pressure_index"].shift(1)
```

## Targets

- KRE/KBE/XLF/HYG future 5d and 22d realized variance.
- KRE/KBE/XLF/HYG future 5d and 22d downside variance.
- 22d forward average pairwise correlation among KRE/KBE/XLF/HYG as a diagnostic
  cross-sector correlation target.

## Forecast Comparison

- Baseline: own lagged target, SPY 22d RV, log VIX, HYG-LQD 22d gap.
- Augmented: baseline plus lagged NBFI run-pressure index.
- Expanding OLS, refit every 21 observations.
- Variance targets use log-target OLS and QLIKE.
- Correlation target uses raw-target OLS and MSE only.
- At forecast date `t`, training excludes any row whose forward target window
  would not have ended by `t-1`.
- Positive DM/HAC t-stat means the augmented model has lower loss.
- Harvey-style practical threshold: `|t| > 3`.

## Run

```bash
uv run python experiments/research_nbfi_proxy_etf_vol_eu_fsb_2026_stress_test/research_nbfi_proxy_etf_vol_eu_fsb_2026_stress_test.py
```

## Required Outputs

- `research_nbfi_proxy_etf_vol_eu_fsb_2026_stress_test.py`
- `research_nbfi_proxy_etf_vol_eu_fsb_2026_stress_test_results.json`
- `results.json`
- `summary_table.csv`
- `daily_panel.csv`
- `figures/nbfi_run_pressure_timeseries.png`
- `figures/oos_dm_tstats.png`
- `codex_review.md`

## Success Criteria

Evidence for a publishable leading indicator requires positive OOS QLIKE
improvement with Harvey-level DM support across multiple variance targets,
especially bank ETFs, after own-risk, SPY, VIX, and HYG-LQD controls. A single
credit-only or correlation-only diagnostic is not sufficient.

## Results

Final run: 2026-06-24 local session.

Aggregate OOS result:

- Valid OOS cells: 17.
- Variance-target cells: 16.
- Positive Harvey-level QLIKE cells: 0.
- Negative Harvey-level QLIKE cells: 0.
- Median QLIKE improvement from adding NBFI pressure: -0.33%.
- Mean QLIKE improvement from adding NBFI pressure: -0.62%.
- Verdict: `null_or_weak_diagnostic`.

Some short-horizon bank ETF cells had small positive QLIKE improvements, and
XLF 22d RV had the largest positive improvement, but none came close to the
Harvey-level threshold. The best in-sample HAC signal coefficient was XLF 22d RV
with t=2.81, still below the `t > 3` gate. HYG cells had positive MSE
improvements but negative QLIKE improvements, so they are not robust variance
forecast wins.

| Target | OOS N | QLIKE Improvement % | QLIKE DM t | MSE Improvement % | Signal HAC t |
|---|---:|---:|---:|---:|---:|
| KRE RV 5d | 1349 | 0.33 | 0.43 | -0.11 | -1.62 |
| KRE downside 5d | 1325 | 0.51 | 1.10 | -0.04 | -0.28 |
| KRE RV 22d | 1332 | -1.91 | -1.58 | -1.79 | 1.35 |
| KRE downside 22d | 1332 | -0.88 | -1.00 | -0.63 | 0.79 |
| KBE RV 5d | 1349 | 0.08 | 0.12 | -0.14 | -1.08 |
| KBE downside 5d | 1319 | 0.31 | 0.43 | -0.10 | 0.45 |
| KBE RV 22d | 1332 | -2.35 | -1.45 | -2.11 | 1.56 |
| KBE downside 22d | 1332 | -0.73 | -0.74 | -0.58 | 0.88 |
| XLF RV 5d | 1349 | 1.03 | 1.38 | 0.22 | 2.08 |
| XLF downside 5d | 1288 | 0.76 | 0.50 | -0.02 | 2.24 |
| XLF RV 22d | 1332 | 2.11 | 0.77 | -1.72 | 2.81 |
| XLF downside 22d | 1332 | 0.82 | 0.46 | -1.62 | 1.71 |
| HYG RV 5d | 1349 | -2.18 | -1.92 | 1.20 | 1.19 |
| HYG downside 5d | 1303 | -0.76 | -0.92 | 0.38 | 0.63 |
| HYG RV 22d | 1332 | -4.46 | -1.27 | 4.26 | 1.90 |
| HYG downside 22d | 1332 | -2.67 | -0.80 | 1.49 | 1.63 |

Correlation diagnostic:

- KRE/KBE/XLF/HYG 22d forward average pairwise correlation had MSE improvement
  -0.09%, DM t=-0.10, and signal HAC t=0.73. This does not support a
  cross-sector correlation-leading claim.

Interpretation: the free ETF/FRED NBFI pressure proxy is at most a weak
diagnostic. It does not support a robust claim that public NBFI run-pressure
signals lead bank or credit ETF volatility after standard market-risk controls.

## Data Coverage

- yfinance window: 2013-01-02 to 2026-06-23.
- FRED WRMFNS: 1980-02-04 to 2026-06-01.
- FRED MMMFFAQ027S: 1945-10-01 to 2026-01-01.
- FRED TOTBKCR: 1973-01-03 to 2026-06-10.
- FRED SOFR: 2018-04-03 to 2026-06-22.
- FRED IORB: 2021-07-29 to 2026-06-24.

## Interpretation Limits

- This is a public proxy screen, not an EU system-wide NBFI stress-test
  replication.
- Full ICI MMF flow by fund, TRACE liquidity, fund NAV discount, supervisory
  bank-NBFI exposure, and private fund redemption data are not available here.
- Total MMF assets are quarterly and forward-filled for daily alignment.
- ETF pressure can mix true NBFI liquidity stress with ordinary beta and
  risk-off price pressure.
