# K1592 - Genuine OOS Gamma-Rule Horse Race

## Motivation

The leverage-direction paper's JBF review gate flagged the current model-selection story as too close to an in-sample or weak-OOS claim. The specific concern was that phrases such as "never significantly beaten" and "genuine OOS gains" blurred three distinct outcomes:

1. significant superiority,
2. non-rejection of equal predictive accuracy,
3. a small mean-loss edge that is not publication-grade after multiple-testing control.

K1592 rebuilds the model-selection evidence as a frozen, pre-specified, future OOS horse race.

## Difference From Prior Paper Tables

- Uses the paper-local frozen CSV only: `paper/leverage-direction/data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv`.
- Freezes the rule before the test window: use GJR only when the current-window GJR gamma is positive and `gamma_t > 1.65`; otherwise use symmetric GARCH.
- Splits the asset universe into development assets (`SPY`, `QQQ`, `EEM`, `GLD`, `TLT`) and disjoint holdout assets (`IWM`, `SLV`, `BTC-USD`).
- Tests the future OOS period `2023-01-03` through `2026-06-26`.
- Uses target-aligned one-step forecasts and canonical Patton QLIKE: `actual / predicted - log(actual / predicted) - 1`.
- Performs panel inference by averaging losses by date before DM tests, following the K1355 lesson.

## Related Internal Lessons

- K445: `arch` origin-aligned forecasts must not be compared to same-index realized variance.
- K783c: inverse QLIKE can silently reverse model rankings; use canonical Patton QLIKE.
- K1355: pooled asset-day DM is not valid primary inference; use date-clustered loss differentials.
- K478: forecast evaluation must align inference horizon and loss construction.
- K1583: MCS often retains multiple GARCH-family variants; do not force a single winner when data are uninformative.

## Literature Checked

- Patton (2011), volatility forecast comparison with imperfect proxies: QLIKE orientation and proxy-robust loss.
- Hansen, Lunde, and Nason (2011), Model Confidence Set: avoid declaring one best model when the data retain several.
- Harvey, Leybourne, and Newbold (1997), forecast-comparison small-sample correction context.
- Glosten, Jagannathan, and Runkle (1993), asymmetric volatility term being tested as a model-selection signal.

## Data

Source: paper-local pinned yfinance CSV, not refreshed during the experiment.

Return unit: `100 * log(adjusted_close).diff()`. Squared returns and variance forecasts are therefore in percent-squared units.

OOS sample sizes:

| Asset | Split | OOS dates |
|---|---:|---:|
| SPY | development | 873 |
| QQQ | development | 873 |
| EEM | development | 873 |
| GLD | development | 873 |
| TLT | development | 873 |
| IWM | holdout | 873 |
| SLV | holdout | 825 |
| BTC-USD | holdout | 1202 |

## Method

At each forecast origin, the script fits two models on the prior 504 returns:

- zero-mean GARCH(1,1), Normal quasi-likelihood;
- zero-mean GJR-GARCH(1,1), Normal quasi-likelihood.

Forecast origins are spaced every 21 trading days. Within each block, daily one-step forecasts are generated recursively. The variance forecast for day `t` is formed before seeing `r_t`, then the recursion updates with `r_t` for the next forecast.

The frozen rule is:

```text
Use GJR iff current-window gamma > 0 and gamma_t > 1.65.
Otherwise use GARCH.
```

Inference:

- asset-level DM-HAC, `h=1`;
- Holm adjustment across asset-level pairwise tests;
- strict superiority requires both `|t| > 3` and Holm `p < 0.05`;
- panel tests average model losses by date before DM;
- MCS uses the local HLN 2011 stationary-bootstrap implementation with `B=1000`, `alpha=0.10`.

## Results

### Main Verdict

`NULL_OR_WEAK`: the pre-specified positive-gamma rule is not a JBF-grade OOS superiority result. It is best described as a risk-controlled diagnostic, not as a general forecasting edge.

The rule has the lowest mean loss for 3 of 8 assets (`EEM`, `TLT`, `IWM`), but it has 0 asset-level strict-superiority wins after Harvey-style and Holm gates.

### Asset-Level Summary

| Asset | Best mean-loss model | GammaRule GJR share | Rule vs GARCH DM t | Rule vs GJR DM t | Strict Rule win |
|---|---:|---:|---:|---:|---:|
| SPY | GJR | 80.8% | -2.85 | +0.99 | no |
| QQQ | GJR | 59.1% | -1.10 | +2.08 | no |
| EEM | GammaRule | 60.1% | -1.11 | -0.49 | no |
| GLD | GARCH | 0.0% | 0.00 | -0.13 | no |
| TLT | GammaRule | 36.1% | -0.26 | -1.02 | no |
| IWM | GammaRule | 54.3% | -0.65 | -0.79 | no |
| SLV | GJR | 2.5% | +0.88 | +1.39 | no |
| BTC-USD | GJR | 10.9% | -0.75 | +0.00 | no |

### Panel Tests

| Panel | Best mean-loss model | Rule vs GARCH DM t | Rule vs GJR DM t | MCS survivors |
|---|---:|---:|---:|---|
| Development assets, future OOS | GJR | -2.90 | +0.73 | GJR, GammaRule |
| Disjoint holdout assets, future OOS | GJR | -0.79 | +1.08 | GARCH, GJR, GammaRule |
| All assets, future OOS | GJR | -2.75 | +1.20 | GJR, GammaRule |

Interpretation:

- The rule is directionally helpful versus GARCH in the development panel, but does not clear the strict `|t| > 3` gate.
- The disjoint holdout panel is the key JBF test, and it is unambiguously weak: MCS retains all three models.
- GJR remains the best mean-loss model in the combined and holdout panels, while GammaRule is statistically indistinguishable from it.

## Paper Implication

Delete or demote any headline that says the gamma rule delivers genuine OOS forecasting gains or is never significantly beaten.

Safer paper language:

> In a pre-specified 2023-2026 OOS horse race, the gamma rule is statistically indistinguishable from the best fixed GJR benchmark and avoids using GJR for GLD, but it does not deliver strict out-of-sample superiority. The evidence supports gamma as a model-selection diagnostic, not as a standalone forecasting alpha rule.

## Limitations

- The frozen paper CSV only provides 8 usable assets, so this does not satisfy the stronger 14/26-asset validation requested by the review gate.
- Monthly refit is used for tractability and forecast-origin logging; a daily-refit rerun may change small mean-loss differences but should not be expected to rescue the strict-inference conclusion.
- Only Normal quasi-likelihood GARCH/GJR is tested. Distributional VaR/ES results are outside this experiment.
- MCS uses `B=1000` for runtime; a final paper table should use a larger bootstrap count.

## Reproduction

```bash
uv run python experiments/k1592/k1592.py
```

## Artifacts

- `k1592.py`
- `k1592_results.json`
- `k1592_oos_losses.csv`
- `k1592_forecast_origin_decision_log.csv`
- `fig1_oos_mean_qlike_by_asset.png`
- `fig2_gammarule_gjr_share.png`
- `fig3_origin_gamma_t.png`
