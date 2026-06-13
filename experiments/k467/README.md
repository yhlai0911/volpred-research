# K467 — HAR Log-Range Based VaR Estimation

- **Status**: completed
- **Script**: `k467_har_range_var.py`
- **Results**: `k467_har_range_var_results.json`
- **Data source**: yfinance OHLC daily data
- **Assets**: SPY, QQQ, EEM
- **OOS period**: 2023-01-03 to 2024-12-31
- **OOS sample**: 502 trading days per asset
- **Rolling window**: 504 trading days

## Question

K465 found HAR log-range to be a strong volatility forecaster across 10 asset-period tests. K467 asks whether that forecast accuracy transfers to VaR estimation: if a model predicts total volatility well, does it also produce well-calibrated downside tail risk forecasts?

K469 later corrected the K465 proxy concern by rechecking HAR log-range under an r^2 proxy rather than only Parkinson range. The HAR forecasting premise remains supported, but published K467 narratives should cite K469 when using K465 as the "best volatility forecaster" premise.

## Methods

K467 runs rolling one-step-ahead VaR backtests for six methods:

- `GJR-Normal`
- `GJR-SkewT`
- `RS_neg-Normal`
- `HAR-Range-Normal`
- `HAR+Semi-Combined`
- `Hybrid-GARCH+HAR`

Each method is tested at 1% and 5% VaR for SPY, QQQ, and EEM. A cell passes only if all three Trinity tests pass:

- Kupiec unconditional coverage
- Christoffersen independence
- Engle-Manganelli dynamic quantile

The HAR VaR forecast is built from feature rows strictly before the target date (`feat.index < date_t`), so the K467 VaR loop does not use same-day high/low range to forecast same-day returns.

## Results

| Method | Trinity passes |
|---|---:|
| GJR-Normal | 6/6 |
| GJR-SkewT | 6/6 |
| RS_neg-Normal | 3/6 |
| Hybrid-GARCH+HAR | 2/6 |
| HAR-Range-Normal | 0/6 |
| HAR+Semi-Combined | 0/6 |

Key source checks:

- SPY HAR-Range 1% VaR has 21 violations versus roughly 5 expected.
- EEM HAR-Range 1% VaR has 50 violations versus roughly 5 expected.
- Hybrid GARCH+HAR passes only the SPY and QQQ 5% cells.

## Interpretation

K467 supports a task-specific conclusion: volatility forecast accuracy does not imply VaR adequacy. HAR log-range can forecast total range well, while GJR-GARCH's leverage/asymmetry structure is more suitable for downside tail calibration in this VaR setup.

## Limitations

- The OOS period is only 2023-2024, a relatively stable equity regime.
- HAR VaR uses a Normal distribution overlay; Student-t, EVT, or conformal overlays remain follow-up work.
- The result covers three equity ETFs only.
- K465's original Parkinson-proxy framing needs the K469 r^2-proxy correction when cited as broad evidence of HAR forecast strength.
