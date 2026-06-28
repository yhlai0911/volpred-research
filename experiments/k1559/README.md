# K1559: Missing / Stale Market Data as Liquidity-Volatility Prior

## Research Question

Do missing, stale, or zero-volume daily OHLCV observations in thin ETF histories
act as a liquidity-volatility prior, or are they only data-cleaning noise?

This experiment tests that question on a 28-ETF panel of liquid controls,
small/micro-cap ETFs, country ETFs, frontier ETFs, and niche commodity ETFs.

## Motivation and Differentiation

Nearby prior work already tested conventional low-frequency liquidity proxies:

- `K1472`: HAR plus Amihud / Corwin-Schultz proxies. Broad result was null,
  with one QQQ Amihud exception.
- `K753`: volume and market volatility relation, focused on SPY/VIX.
- `K265`: daily OHLCV liquidity-proxy extension, including Amihud and
  high-low spread measures.

K1559 is narrower: it treats explicit data-quality events themselves as the
signal. The point is not to claim that bad vendor data is alpha. The point is to
test whether zero-volume or stale-price days in thin ETFs behave like observable
liquidity-stress flags for subsequent volatility risk.

## Literature Preamble

- Lesmond, Ogden, and Trzcinka (1999), Review of Financial Studies:
  zero returns can proxy transaction costs and non-trading.
- Amihud (2002), Journal of Financial Markets:
  absolute return over dollar volume is a daily low-frequency illiquidity
  measure.
- Getmansky, Lo, and Makarov (2004), Journal of Financial Economics:
  stale or smoothed prices can understate economic risk in illiquid assets.
- Bekaert, Harvey, and Lundblad (2007), Review of Financial Studies:
  zero-return liquidity measures matter in thin markets and should be compared
  with turnover / price controls.
- Scholes and Williams (1977), Journal of Financial Economics:
  nonsynchronous trading creates measurement bias in thin assets.

## Data

- Source: yfinance daily OHLCV, `auto_adjust=False`.
- Returns: adjusted close log returns.
- Reference calendar: SPY trading dates.
- Sample request: `2014-01-01` to `2026-06-29`.
- Effective last dates: most ETFs to `2026-06-26`; AFK ends at `2025-01-08`.
- Assets used: 28.
- Estimation rows: 86,148.
- Random seed: 42.

Universe:

`SPY, QQQ, IWM, IWC, IJR, VIOO, XBI, XES, XME, REMX, URA, COPX, GREK, TUR,
EPOL, EIRL, ECH, EPU, EIDO, THD, EPHE, VNM, GXG, KSA, QAT, UAE, FM, AFK`.

## Event Definitions

- `missing_row`: ticker absent on a SPY reference trading day between its first
  and last observed dates.
- `recovery_after_missing`: first valid ticker row after a missing reference day.
- `zero_volume`: valid ticker row with `Volume <= 0`.
- `stale_price`: zero adjusted return plus zero volume or zero high-low range.
- `corporate_action_gap`: large raw close move mostly removed by adjusted close.
- `zero_return_day`: LOT-style zero adjusted-return proxy, reported separately.
- `any_data_quality_event`: missing row, recovery day, zero volume, stale price,
  or corporate-action gap.

## Lookahead Control

Signals are measured at the end of reference day `t`. Targets start strictly at
`t+1`:

- `fwd_rv5`: annualized sum of squared returns over `t+1 ... t+5`.
- `fwd_rv22`: annualized sum of squared returns over `t+1 ... t+22`.
- `gap5_5pct` / `gap22_5pct`: any forward absolute return above 5%.
- `dd22_10pct`: forward 22-day cumulative drawdown below -10%.

The script implements this in `forward_window_stats()`, which slices
`returns[i + 1 : i + 1 + h]`.

## Formal Test

For each event-target pair, the script runs an asset fixed-effect panel
regression with HAC standard errors:

`target = event + log_lag_rv22 + log_dollar_volume + log_price + abs(SPY_return) + asset_FE`

Binary risk targets use the same specification as a linear probability model.
P-values are Holm-Bonferroni adjusted across event-target tests.

## Main Result

Verdict: `CONDITIONAL_PASS`.

Controlled panel tests are positive after Holm correction, but the evidence is
concentrated in a few thin ETFs and true missing-row observations are too rare
for a broad "missing data predicts volatility" claim.

Key counts:

| Item | Count |
|---|---:|
| Any data-quality event | 335 |
| Missing row | 1 |
| Recovery after missing | 1 |
| Zero volume | 306 |
| Stale price | 322 |
| Corporate-action gap | 1 |
| Zero-return day | 1,328 |

Primary controlled tests:

| Event | Target | Coef | HAC t | Holm p | Event N |
|---|---|---:|---:|---:|---:|
| any_data_quality_event | log_fwd_rv5 | 0.860 | 5.99 | 5.39e-08 | 335 |
| any_data_quality_event | log_fwd_rv22 | 0.884 | 17.33 | 9.47e-66 | 335 |

Event-specific strongest tests:

| Event | Target | Coef | HAC t | Holm p | Event N |
|---|---|---:|---:|---:|---:|
| zero_volume | log_fwd_rv22 | 0.962 | 18.13 | 6.59e-72 | 306 |
| zero_volume | gap22_5pct | 0.468 | 17.04 | 1.43e-63 | 306 |
| stale_price | log_fwd_rv22 | 0.862 | 16.90 | 1.54e-62 | 322 |

Concentration audit:

| Asset | Any DQ N | 5d RV ratio | 22d RV ratio | 22d gap event | 22d gap non-event |
|---|---:|---:|---:|---:|---:|
| QAT | 172 | 1.68 | 1.47 | 19.8% | 6.1% |
| KSA | 87 | 1.30 | 1.35 | 26.4% | 7.4% |
| UAE | 72 | 0.77 | 0.74 | 2.8% | 11.0% |

This is why the result is conditional. The pooled controlled model sees a
strong signal, and QAT/KSA show clear within-asset risk elevation, but the broad
event set is not diversified across many ETFs and missing rows themselves are
not empirically identified.

## Interpretation

The supported claim is:

> Zero-volume and stale-price days in some thin country ETFs can act as a
> conditional liquidity-risk prior for next-month volatility and gap risk.

The unsupported claims are:

- Missing rows alone predict volatility. There is only one missing-row event.
- This is a cross-ETF universal rule. Only three assets have at least 10
  `any_data_quality_event` observations.
- This is a tradable alpha signal. It is a risk-prior / monitoring result.

## Caveats

- yfinance is a vendor snapshot, not exchange-certified audit data.
- SPY-calendar missing rows can mix vendor omissions, exchange halts, and
  ETF-specific trading issues.
- Corporate-action gaps are adjustment flags, not volatility events.
- The strongest result is geographically concentrated in Gulf country ETFs.
- Linear probability models are used for binary risk outcomes; coefficients
  should be read as controlled association, not structural probability laws.

## Files

- `k1559.py`: experiment script.
- `k1559_results.json`: full results artifact.
- `k1559_event_counts.png`: event counts by ETF.
- `k1559_future_rv_ratios.png`: unconditional future RV ratios.
