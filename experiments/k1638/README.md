# K1638 — Distributional scoring audit for OOS volatility forecasts

## Research question

Can existing VolPred OOS forecast artifacts be re-evaluated with distributional scores, rather than only QLIKE / MSE / DM on point forecasts?

This is an evaluation-layer experiment. It does **not** claim to re-rank all 1400+ historical K experiments. It scans a curated set of byte-traceable OOS forecast CSVs that are already in the repo and have enough per-date rows to support scoring.

## Data coverage

- Declared panel specs: 10
- Scored panels after grouping: 18
- Primary panels (`n_eval >= 252`): 18
- Skipped as too short: 5

Skipped panels:

- `K1582_spy_harq_short`: 51 rows
- `K1582_0050_harq_short`: 38 rows
- `K1349_intraday_rv_short`: 34 rows
- `K1349_total_rv_short`: 33 rows
- `research_intraday_har_vs_seasonal`: 43 rows

Primary scored sources:

- K1637 daily close-to-close `r^2` panels by asset
- K1613 TAIFEX noise-robust RV input comparison
- K1582 TX_active HARQ / SHARK comparison
- K1601 agreed/disagreed uncertainty 21d RV forecasts
- `research_data_driven_vc_screening_shock_public_innovation` ETF panels by ticker/horizon

## Method

Most historical artifacts store point variance forecasts, not native predictive distributions. To make CRPS / pinball / coverage comparable without inventing new data, K1638 uses a transparent post-processing wrapper:

1. For each panel/model, split the available OOS rows into a calibration slice and an evaluation slice.
2. Estimate lognormal dispersion `sigma` on calibration rows only from `log(actual / forecast)`.
3. Treat the point variance forecast `mu_t` as the mean of a lognormal predictive distribution.
4. Evaluate later rows only with:
   - CRPS
   - average pinball loss at 5%, 25%, 50%, 75%, 95%
   - 90% empirical coverage
   - 90% interval score
5. Run a lightweight Hansen-Lunde-Nason-style MCS range procedure on scaled CRPS and pinball losses, with moving-block bootstrap.

Lookahead control:

- No new forecast model is fit.
- Distribution width is calibrated only on rows before the evaluation rows.
- MCS and ranking use evaluation rows only.

## Results

Verdict:

`CONDITIONAL_PASS_EVALUATION_LAYER_WORKS_COVERAGE_LIMITED`

Primary CRPS winner counts:

| Model | Panels won |
|---|---:|
| `pred_baseline` | 7 |
| `EWMA_094` | 5 |
| `pred_augmented` | 3 |
| `HAR_RV_forecast` | 1 |
| `SHARK_like_forecast` | 1 |
| `VIX_forecast` | 1 |

Primary MCS inclusion counts by scaled CRPS:

| Model | MCS inclusions |
|---|---:|
| `pred_baseline` | 10 |
| `pred_augmented` | 10 |
| `EWMA_094` | 5 |
| `MS_vol_lite` | 1 |
| `MSM_GMM` | 1 |
| `HAR_RV_forecast` | 1 |
| `HAR_MedRV_input_forecast` | 1 |
| `HAR_RK_input_forecast` | 1 |
| `HARQ_forecast` | 1 |
| `HARQ_full_forecast` | 1 |
| `SHARK_like_forecast` | 1 |
| `VIX_forecast` | 1 |
| `VIX_SPF_forecast` | 1 |

Interpretation:

- The distributional scoring layer works and produces byte-traceable panel-level rankings.
- It confirms several prior null / baseline-heavy conclusions: simple baselines survive often, and augmented models usually remain inside the same MCS rather than cleanly dominating.
- K1637's EWMA result is robust under CRPS / pinball, winning all five K1637 daily `r^2` panels.
- K1601's `VIX_forecast` remains the best distributional scorer on its 21d panel, consistent with VIX sufficiency.
- The data-driven VC screening augmented predictor wins a few panel-level CRPS cells, but baseline and augmented forecasts are both retained in MCS across all 10 ETF panels, so this does not reverse the original null conclusion.

## Files

- `k1638.py` — reproducible experiment script
- `k1638_results.json` — full panel scoring output
- `data/k1638_model_score_table.csv` — flat model/panel summary
- `data/*_distribution_scores.csv` — row-level scaled CRPS / pinball losses
- `figures/k1638_best_crps_by_panel.png`
- `figures/k1638_crps_winner_counts.png`

## Limitations

- This is not a full 1400+ K re-ranking; only artifacts with per-date OOS rows and enough observations can be scored.
- The lognormal wrapper is a scoring bridge for point forecasts, not a native probabilistic model.
- Cross-panel winner counts are descriptive because assets, horizons, and targets differ.
- The MCS implementation is intentionally lightweight; it is suitable for an audit layer, not a replacement for a full paper-grade MCS package.
