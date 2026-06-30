# K1585 - Agreed vs Disagreed Uncertainty Regime Pilot

## Motivation

K1585 tests whether a two-dimensional uncertainty regime can add information beyond VIX alone. The task is motivated by the agreed/disagreed uncertainty distinction in Gambetti, Korobilis, Tsoukalas, and Zanetti (2023), where high uncertainty paired with low disagreement is economically more damaging than high uncertainty paired with high disagreement.

This is a deliberately narrower market-volatility pilot. It asks:

1. Does the high-VIX / low-SPF-disagreement cell have higher forward SPY realized volatility or tail risk than the high-VIX / high-SPF-disagreement cell?
2. Does SPF disagreement improve forward-RV forecasting beyond a VIX-only baseline?

Relevant references:

- Gambetti, Korobilis, Tsoukalas, and Zanetti (2023), "Agreed and Disagreed Uncertainty", arXiv `2302.01621`.
- Philadelphia Fed Survey of Professional Forecasters, "Cross-Sectional Forecast Dispersion", D2 workbook.
- Jurado, Ludvigson, and Ng (2015), "Measuring Uncertainty", *American Economic Review*.
- Baker, Bloom, and Davis (2016), "Measuring Economic Policy Uncertainty", *Quarterly Journal of Economics*.
- Patton (2011), "Volatility forecast comparison using imperfect volatility proxies", *Journal of Econometrics*.

## Data

- SPY/VIX daily panel: `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv`.
- Daily sample after required columns: 6,670 rows from 2000-01-03 to 2026-06-26.
- SPF dispersion workbook: `experiments/k1585/data/Dispersion_2.xlsx`, downloaded from Philadelphia Fed historical SPF dispersion files.
- SPF quarterly rows used: 226 from 1968Q4 to 2026Q2.
- Disagreement proxy: mean of `log1p(RGDP_D2(T+4))` and `log1p(PGDP_D2(T+4))`, where D2 is the SPF interquartile range for quarter-over-quarter annualized growth forecasts.

The workbook does not include exact release timestamps. To avoid lookahead, the script assumes each survey quarter becomes available only at quarter end + 45 calendar days, daily forward-fills the latest available value, and then applies a one-trading-day signal lag.

## Method

Targets:

- Forward 5-day and 21-day SPY realized variance from close-to-close log returns.
- Forward 21-day max drawdown from the previous close.
- Tail event: forward 21-day drawdown <= -5%.

Signals:

```python
df["vix_signal"] = df["vix_close"].shift(1)
df["spf_disagreement_signal"] = df["spf_disagreement_raw"].shift(1)
```

Both signals are converted to expanding z-scores with a 252-observation warm-up. A regime is high if the relevant expanding z-score is above zero.

Formal forecast test:

- Baseline: VIX z-score, lagged 21-day RV, lagged 21-day return, lagged 5-day absolute return.
- Augmented: baseline plus SPF disagreement z-score and VIX x disagreement interaction.
- In-sample diagnostic: HAC OLS with max lag equal to the forecast horizon.
- OOS diagnostic: expanding OLS in log-RV space, retransformed with residual-variance correction, evaluated by Patton QLIKE.
- OOS guard: for horizon `h`, forecast row `i` trains only on rows `j <= i-h`, so overlapping forward-RV targets are fully observed before the forecast origin.
- Strong support gate: augmented model must improve OOS QLIKE with DM `t < -3` and have a HAC SPF/disagreement term with `|t| > 3`.

Seed: 42.

## Results

Verdict: **WEAK_RAW_ONLY**.

The raw regime diagnostic is directionally consistent with the agreed-uncertainty story for 21-day realized variance, but the formal incremental forecast test fails. This should not be cited as evidence that SPF disagreement improves VIX-based volatility forecasting.

### Regime means

| Regime | n | Mean fwd RV21 | Annualized vol from RV21 | Tail event rate |
|---|---:|---:|---:|---:|
| High VIX / Low SPF disagreement | 976 | 0.007739 | 30.47% | 33.09% |
| High VIX / High SPF disagreement | 1,009 | 0.004946 | 24.36% | 27.55% |
| Low VIX / Low SPF disagreement | 2,969 | 0.001490 | 13.37% | 11.05% |
| Low VIX / High SPF disagreement | 1,444 | 0.001701 | 14.29% | 15.03% |

High VIX / low SPF disagreement has higher mean forward 21-day RV than high VIX / high SPF disagreement:

- RV21 difference: `0.002793`.
- Moving-block bootstrap 95% interval: `[-0.000375, 0.006391]`.
- One-sided bootstrap p-value for agreed > disagreed: `0.044`.

The result is weak because the two-sided interval crosses zero, the 5-day RV contrast is weaker (`p=0.0875`), and the tail event contrast is not significant (`p=0.1875`).

### Incremental forecast test

| Horizon | Baseline QLIKE | VIX+SPF QLIKE | QLIKE improvement | DM t | DM p |
|---|---:|---:|---:|---:|---:|
| 5d | 0.403495 | 0.406376 | -0.714% | 0.874 | 0.382 |
| 21d | 0.335947 | 0.346609 | -3.174% | 1.809 | 0.071 |

Negative improvement means the VIX+SPF augmented model is worse by primary QLIKE loss. The 21-day DM statistic is positive, which means augmented losses exceed baseline losses.

In-sample HAC regressions show SPF disagreement can have positive coefficients:

| Horizon | SPF disagreement coeff | HAC t | Interaction coeff | HAC t | Adj. R2 delta |
|---|---:|---:|---:|---:|---:|
| 5d | 0.0788 | 4.403 | -0.0094 | -0.510 | +0.00533 |
| 21d | 0.0695 | 2.564 | -0.0156 | -0.657 | +0.00664 |

This in-sample signal does not survive the OOS QLIKE gate.

## Conclusion

K1585 does **not** overturn the current VIX-sufficient prior from K43/K730-style results. There is a weak descriptive regime pattern: high VIX paired with low SPF disagreement has higher subsequent SPY realized variance than high VIX paired with high SPF disagreement. However, SPF disagreement does not improve OOS volatility forecasts beyond the VIX baseline, and tail evidence is not statistically strong.

The result is useful as a diagnostic and as a design note for a future macro-release-date-clean replication using exact SPF release dates and a JLN uncertainty level measure. It is not ready as a positive paper claim.

## Files

- `k1585.py`: reproducible experiment script.
- `k1585_results.json`: machine-readable results.
- `figures/k1585_regime_diagnostics.png`: signal, regime, and QLIKE diagnostics.
- `data/Dispersion_2.xlsx`: pinned Philly Fed SPF D2 workbook used by the script.
- `codex_review.md`: adversarial review of the artifact and claim strength.

## Reproducibility

Run from the repository root:

```bash
uv run python experiments/k1585/k1585.py
```
