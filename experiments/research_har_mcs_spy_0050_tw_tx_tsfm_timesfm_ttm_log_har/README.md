# research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har

## Question

Can open time-series foundation models, specifically TimesFM and Tiny Time Mixers
(TTM), improve on a log-HAR volatility baseline through forecast combinations,
and do those combinations survive Hansen-Lunde-Nason MCS on SPY, Taiwan 0050,
and TAIFEX TX?

## Status

`BLOCKED_FOR_PRIMARY_TSFMS_BUT_BASELINE_HARNESS_EXECUTED`.

The primary TSFM portion was not completed because the shared project
environment did not have usable model weights:

- TimesFM package import works after installing `timesfm==2.0.2`, but
  `google/timesfm-2.5-200m-pytorch/model.safetensors` did not finish downloading
  during a >150 second smoke test.
- Granite TTM dry-run install would downgrade the project-required
  `scikit-learn` from 1.8.0 to 1.7.2, so it was not installed into the shared
  venv.

No TimesFM or TTM empirical forecast is included. The experiment therefore
should not be cited as evidence for or against TSFM forecast skill.

## Executed Harness

The script still builds the intended evaluation scaffold:

- assets: `SPY`, `0050.TW`, `TAIFEX_TX`
- targets:
  - SPY / 0050.TW: next trading day close-to-close squared log return
  - TAIFEX_TX: next trading session 5-minute realized variance from prior TAIFEX
    cache
- models:
  - `HAR_log`
  - `EWMA_094`
  - `CONST_rollmean`
  - `COMBO_equal_HAR_EWMA`
  - `COMBO_biascorr_HAR_EWMA`
- inference:
  - per-asset QLIKE, DM-HLN vs `HAR_log`, and MCS
  - pooled inference averages losses by target date before DM/MCS

## Lookahead Policy

At forecast origin `t`, every feature uses observed volatility through `t`; the
target is `y[t+1]`. The bias-corrected combination uses only previous OOS
forecast rows, with the first 60 rows falling back to equal-weight HAR/EWMA.

For 0050.TW, `volpred.utils.clean_tw50_data` is applied to avoid the known Yahoo
Finance split artifact.

## Literature Checked

- Das et al. (2024), TimesFM / decoder-only foundation model for time-series
  forecasting, arXiv:2310.10688.
- Ekambaram et al. (2024), Tiny Time Mixers, arXiv:2401.03955.
- Hansen, Lunde and Nason (2011), Model Confidence Set, Econometrica.
- Diebold and Mariano (1995) with Harvey-Leybourne-Newbold small-sample
  adjustment for forecast comparison.

## Files

- `research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har.py` — reproducible
  script.
- `research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har_results.json` —
  atomic-written results and TSFM environment audit.
- `research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har_oos_forecasts.csv`
  — OOS forecast sidecar.

## Interpretation Rule

Use this run as a blocked diagnostic and ready-to-extend evaluation harness, not
as a completed TSFM-vs-HAR study.
