# K1666: Path-Dependent Volatility Free-Data Diagnostic

## Motivation

This experiment tests a conservative version of the Guyon-Lekeufack path-dependent volatility claim: how much of daily equity-index volatility can be explained by the past return path, and do those path features add out-of-sample value beyond a plain HAR baseline?

The task asks for SPY/QQQ via yfinance. Because this uses daily OHLC only, the result is a free-data proxy diagnostic, not a replication of the original 5-minute realized-volatility design.

## Evidence Package

- Script: `K1666.py`
- Results: `K1666_results.json`
- Data snapshot: `data/prices_yfinance_auto_adjust.csv`
- Figures: `K1666_fig1_pdv_r2.png`, `K1666_fig2_har_incremental.png`
- Review note: `codex_review.md`

## Data

- Source: Yahoo Finance through `yfinance.download(auto_adjust=True)`
- Assets: SPY, QQQ
- Period: 2000-01-03 to 2026-07-09
- Raw rows: 6,668 per asset
- Usable rows after 252-day path lag and HAR lags: 6,415 per asset
- OOS one-step HAR evaluation: 2004-12-29 to 2026-07-09, 5,415 dates per asset

Targets:

- `gk`: Garman-Klass daily range variance, annualized. This is the primary daily OHLC proxy for intraday realized variance.
- `c2c`: close-to-close squared log return variance, annualized. This is a robustness proxy and is noisier for daily RV.

## Method

PDV features are computed from daily close-to-close returns over a 252-trading-day lookback:

- `R1`: power-law weighted sum of past returns, alpha = 1.0, annualized. This is the leverage/trend channel.
- `R2`: square root of a power-law weighted sum of past squared returns, alpha = 0.5, annualized. This is the path-volatility channel.

Anti-lookahead policy:

- Raw path and HAR features are indexed by the last date used in the input path.
- The code explicitly applies `signal = raw_signal.shift(1)`.
- Forecast row `t` uses only signals known at the end of `t-1`.
- Expanding OOS models fit only rows strictly before the forecast row.

Forecast comparison:

- Baseline: log-variance HAR with daily / weekly / monthly lagged components.
- Augmented: `HAR+R1` and `HAR+R1+R2`.
- Loss: canonical QLIKE via `volpred.stats.model_evaluation.qlike_pointwise(actual, predicted)`.
- Inference: Diebold-Mariano HAC with one-step horizon; Harvey gate uses `t < -3` for augmented-better.
- Cross-asset aggregate: date-clustered mean loss across SPY/QQQ, no asset-day iid pooling.

## Main Results

PDV-only explanatory R2:

| Asset | Target | Full-sample R2 | Chronological holdout OOS R2 |
|---|---:|---:|---:|
| SPY | GK range proxy | 0.501 | 0.420 |
| QQQ | GK range proxy | 0.551 | 0.345 |
| SPY | C2C proxy | 0.244 | 0.206 |
| QQQ | C2C proxy | 0.232 | 0.135 |

Date-clustered OOS QLIKE vs HAR:

| Target | Challenger | QLIKE improvement | DM t | Harvey pass? |
|---|---:|---:|---:|---|
| GK | HAR+R1 | +7.49% | -3.90 | yes |
| GK | HAR+R1+R2 | +8.79% | -4.53 | yes |
| C2C | HAR+R1 | +3.75% | -11.65 | yes |
| C2C | HAR+R1+R2 | +5.84% | -10.98 | yes |

Subperiod check for the primary GK target:

- 2005-2009: HAR+R1+R2 improves QLIKE by +6.85%, DM t = -4.73.
- 2010-2019: direction remains positive at +9.31%, but DM t = -2.61, below the Harvey threshold.
- 2020-2026: HAR+R1+R2 improves QLIKE by +9.15%, DM t = -4.96.

Interpretation: the PDV signal is strongest in stress and post-shock regimes. The calm 2010s still point in the same direction but do not clear the stricter 3-sigma gate.

## Verdict

`CONDITIONAL_PASS_RANGE_PROXY_PDV_EXPLAINS_AND_HAR_QLIKE_EDGE`

The daily range-based GK proxy supports the PDV path-dependence channel: PDV-only R2 is around 50%+ for SPY/QQQ, and HAR+PDV improves OOS QLIKE beyond HAR. This should not be stated as a full replication of Guyon-Lekeufack daily high-frequency RV results.

## Caveats

- No 5-minute realized variance is used.
- Kernel parameters are fixed, not literature-calibrated or tuned by MCS.
- The C2C target is very noisy: QLIKE improves, but MSE diagnostics show severe overprediction for SPY C2C and weaker robustness. C2C is a robustness check, not the headline target.
- SPY GK QLIKE improves, but MSE worsens; QQQ GK improves under both QLIKE and MSE. The practical forecast claim should therefore be QLIKE-specific.
- This tests SPY/QQQ only. A Taiwan extension should wait for a longer 5-minute 0050/TX realized-vol panel or be explicitly labelled as daily proxy only.

## References

- Guyon and Lekeufack (2023), *Volatility Is (Mostly) Path-Dependent*.
- Liu, Fu and Hong (2025), *Forecasting realized volatility in the stock market: a path-dependent perspective*, arXiv:2503.00851.
- Corsi (2009), *A Simple Approximate Long-Memory Model of Realized Volatility*.
- Bayer, Horst and Ulbricht (2024), *Pricing and calibration in the 4-factor path-dependent volatility model*.
