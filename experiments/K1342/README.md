# K1342: MOC Imbalance Proxy and Late-Close Drift

**Status:** completed proxy study
**Run date:** 2026-06-15

## Motivation

NYSE and Nasdaq publish closing-auction imbalance information shortly before the
close. The economic question is whether imbalance direction contains enough
short-horizon information to predict the last minutes of trading or the next
session after realistic costs.

This experiment is deliberately conservative: free Yahoo minute bars do **not**
include the true exchange MOC imbalance feed. K1342 therefore tests a public-data
proxy: signed-volume pressure before the 15:50 ET imbalance publication window.
Any positive result would be only a screening signal for buying proper imbalance
data; any null result does not disprove true-feed alpha.

## Literature / Source Motivation

- NYSE, "The NYSE Significant Imbalance" (2024): the 15:50 ET significant
  imbalance flag is explicitly designed to identify large, symbol-specific
  closing-auction imbalances.
- NYSE, "Closing Auction: Immediate market impact, price drift and transaction
  cost of trading" (2023): auction imbalance changes are linked to reference
  price impact and drift in the final minutes.
- Federal Register / Nasdaq rule filing (2018): the Nasdaq Closing Cross
  disseminates an Order Imbalance Indicator once on-close orders are locked in.
- Goyal, Jegadeesh, and Wu, JFQA forthcoming/2026: closing auctions are a large
  liquidity venue and trading costs in auctions can be lower than continuous
  trading for non-microcap anomaly portfolios.

## Data

- Source: yfinance 1-minute OHLCV.
- Period requested: last 30 calendar days available from Yahoo, fetched in
  7-day chunks because Yahoo currently rejects 1-minute requests longer than
  about 8 days and older than about 30 days.
- Universe: SPY, QQQ, IWM, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA.
- Time zone: timestamps converted from UTC to America/New_York.
- Regular session only: 09:30-15:59 ET.

## Method

For each ticker-day:

1. Compute 1-minute log returns and signed volume:
   `signed_volume = sign(return_1m) * volume`.
2. Define pre-publication pressure using only 15:30-15:49 ET:
   `pressure = sum(signed_volume) / sum(volume)`.
3. Direction = `sign(pressure)`.
4. Targets:
   - `late_close`: direction times log return from 15:51 close to last
     available 15:55-15:59 close.
   - `overnight_open`: direction times close-to-next-open return.
   - `next_close`: direction times close-to-next-close return.
5. High-pressure days are selected causally:
   `abs(pressure)` must exceed the ticker's prior 20-trading-day rolling 70th
   percentile, with `shift(1)` and `min_periods=10`.
6. Results are equal-weighted by date across available tickers.
7. Report gross and net returns. Net subtracts a conservative 3.4 bps round-trip
   cost (1.7 bps per side, from the task assumption).
8. Statistical test: one-sided centred block bootstrap of daily equal-weight
   returns, block length 5 trading days, 5,000 draws, seed 42. Newey-West t-stats
   with lag 5 are also reported.

## Lookahead Policy

- The signal excludes 15:50 and all later bars.
- Late-close target starts at 15:51, so the target does not overlap the signal.
- Overnight and next-close targets use the next observed trading day, not
  calendar-day offsets.
- High-pressure threshold uses `shift(1)` before the rolling quantile; no
  full-sample quantile is used for the tradable subset.
- Bootstrap uses `np.random.default_rng(seed=42)`.

## Outputs

- `K1342.py`
- `K1342_results.json`
- `K1342_daily_signals.csv`
- `figures/k1342_mean_drift_bps.png`
- `figures/k1342_late_close_net_cumulative.png`

## Interpretation Guardrail

This is not a test of proprietary exchange imbalance messages. It is a
public-data proxy study for whether late-day signed-volume pressure is enough to
recover a tradable MOC-like drift. Conclusions must be stated at that proxy
level only.
