# K1502 — FINRA off-exchange proxy and next-day idiosyncratic volatility

## Research Question

散戶交易強度的公開 proxy 是否能領先美股 retail-tilted 籃子的次日 idiosyncratic volatility？

本實驗是 reduced-form public-data pilot。它沒有直接觀測券商層級 retail order flow；使用的是 FINRA CNMS off-exchange short-sale volume ratio 與 off-exchange total volume，作為「公開可得的 off-exchange / internalization activity proxy」。

## Motivation and Literature

文獻動機是真實存在的：散戶交易與個股波動、idiosyncratic volatility、PFOF/internalization market structure 有關。但可得資料很有限，因此本實驗只檢查 public proxy 是否足以形成可用 forecasting signal。

References checked before implementation:

- Foucault, Sraer, and Thesmar (2011), *Journal of Finance*, "Individual Investors and Volatility": retail trading can causally raise stock-return volatility.
- Wu and Ren (2025), *Pacific-Basin Finance Journal*, "Retail investors and the behavioral component of idiosyncratic volatility": retail activity correlates with idiosyncratic volatility in China.
- FINRA Short Sale Volume documentation and Information Notice 5/10/19: FINRA short-sale files are off-exchange/publicly disseminated short-sale volume, not short interest and not consolidated exchange-wide volume.
- Ernst and Spatt, "Payment for Order Flow and the Retail Trading Experience"; Hoffmann and Jank (2024), "What is the Value of Retail Order Flow?": PFOF/internalization motivates why off-exchange trading may proxy retail-related market structure.

Useful links:

- FINRA Short Sale Volume Data: <https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data>
- FINRA daily file endpoint pattern: <https://cdn.finra.org/equity/regsho/daily/CNMSshvolYYYYMMDD.txt>
- FINRA Information Notice 5/10/19: <https://www.finra.org/rules-guidance/notices/information-notice-051019>
- Foucault et al. PDF: <https://faculty.haas.berkeley.edu/dsraer/SRD.pdf>
- Wu and Ren entry: <https://ideas.repec.org/a/eee/pacfin/v90y2025ics0927538x2400369x.html>

## Data

- FINRA CNMS daily short-sale volume files, filtered to 22 requested symbols.
- yfinance daily OHLC for the same symbols plus SPY.
- Sample span: 2023-01-03 to 2026-06-12.
- Filtered FINRA rows: 19,008.
- OOS forecast window: 2024-07-19 to 2026-06-12.
- OOS observations: 477 per ticker, 10,494 stacked ticker-days.

Retail-tilted basket:

`IWM, GME, AMC, BB, KOSS, OPEN, KSS, PLTR, SOFI, HOOD, RIVN, LCID, F, CHWY, DKNG, AFRM, UPST, MARA, RIOT, COIN, CVNA, TLRY`

The basket is intentionally survivorship-biased and liquid/current-name biased. It is acceptable for a pilot diagnostic, but not enough for a production cross-section claim.

## Timing and Lookahead Guard

Target row is date `t`: CAPM-residual squared return on date `t`.

All forecast features are known by `t-1`:

- `log_idio_r2_lag1`
- `log_idio_r2_lag5`
- `log_idio_r2_lag22`
- `spy_r2_lag1`
- `short_ratio_z_lag1`
- `log_offex_volume_z_lag1`
- `finra_present_lag1`

The code uses explicit `.shift(1)` for every forecasting feature. Horizon is one day, so the K1337 forward-label leakage failure mode does not apply. If this experiment is extended to h=5 or h=21, the rolling fit must embargo the last h-1 training rows.

## Method

For each ticker:

1. Estimate a rolling 126-day CAPM residual versus SPY.
2. Define realized idiosyncratic variance as residual squared return, clipped at `1e-10`.
3. Baseline model: rolling 252-day HAR-log idiosyncratic variance plus lagged SPY variance.
4. Full model: baseline plus lagged FINRA short-ratio z-score, lagged log off-exchange volume z-score, and FINRA-present indicator.
5. Refit every 21 trading days.
6. Evaluate OOS using Patton QLIKE on residual variance and canonical `volpred.stats.model_evaluation.dm_test`.
7. Apply Harvey threshold `|DM t| > 3.0`.

## Results

Headline result: **NULL**.

| Metric | Value |
|---|---:|
| Tickers with valid OOS | 22 |
| OOS observations per ticker | 477 |
| Tickers passing Harvey `|t| > 3` | 0 |
| Median QLIKE improvement, full vs baseline | +1.91% |
| Mean QLIKE improvement, full vs baseline | +0.75% |
| Positive-improvement tickers | 12 / 22 |
| Sign-test p-value | 0.416 |
| Pooled DM full vs baseline | t = -0.69, p = 0.493 |
| Median ticker-level DM t | -0.37 |
| Best QLIKE improvement | CVNA, +17.92% |
| Worst QLIKE improvement | TLRY, -40.09% |

Selected ticker-level results:

| Ticker | QLIKE improvement | DM t | p-value | Harvey pass |
|---|---:|---:|---:|---|
| CVNA | +17.92% | -2.13 | 0.034 | No |
| DKNG | +15.80% | -2.25 | 0.025 | No |
| GME | +9.93% | -0.72 | 0.473 | No |
| IWM | -4.21% | +1.76 | 0.079 | No |
| KOSS | -12.42% | +2.32 | 0.021 | No |
| RIOT | -15.97% | +1.89 | 0.060 | No |
| TLRY | -40.09% | +1.46 | 0.144 | No |

In-sample HAC regressions show a frequent positive coefficient for lagged off-exchange volume (`median t = 2.93`), but that does not translate into robust OOS QLIKE improvement. Lagged short-ratio itself is weak (`median t = 0.09`).

## Verdict

**NULL for forecasting use.**

The public FINRA off-exchange proxy has some descriptive association with idiosyncratic volatility regimes, especially through off-exchange volume, but it does not pass the project gate for a next-day idiosyncratic-volatility forecasting signal:

- 0 / 22 tickers pass Harvey `|t| > 3`.
- Cross-sectional sign test is not significant.
- Pooled DM test is insignificant.
- Gains are heterogeneous and fragile across names.

Operational implication: do not add this proxy to the Indicator Arena as a standalone signal. A stronger follow-up would need true retail order-flow, odd-lot trade data, broker/client classification, or option-retail flow proxies.

## Limitations

- FINRA short-sale volume is not retail order flow.
- FINRA files are not consolidated with exchange short-sale volume.
- The basket is manually selected and survivorship-biased.
- Idiosyncratic variance is daily CAPM residual squared return, not intraday realized idio RV.
- Sample is only 2023-2026 because the experiment intentionally keeps data fetch size bounded for hourly execution.

## Files

- `k1502.py` — full reproducible pipeline.
- `k1502_results.json` — machine-readable results.
- `data/finra_cnms_filtered.csv` — filtered FINRA rows for the selected symbols.
- `data/prices.parquet` — yfinance OHLC cache.
- `data/panel.parquet` — model panel.
- `data/oos_predictions.parquet` — OOS forecasts and pointwise losses.
- `figures/k1502_qlike_improvement_by_ticker.png` — ticker-level OOS QLIKE improvement.
- `figures/k1502_short_ratio_bucket_nextday_idio_var.png` — descriptive next-day idio variance by lagged short-ratio bucket.
- `codex_review.md` — source-level review.

## Reproduce

```bash
uv run python experiments/k1502_proxy_idio_vol/k1502.py
```

Cold run downloads FINRA daily files and yfinance prices. Cached reruns are much faster.
