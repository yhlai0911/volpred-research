# Maritime Chokepoint Stress as Commodity / Retail / Shipping Vol Signal

## Question

Can maritime chokepoint and supply-chain stress proxies forecast realized
volatility for commodity, retail, transportation, and shipping ETFs?

This experiment tests the backlog idea:

> Maritime chokepoint stress index as a signal for commodity / retail /
> shipping vol: GSCPI, shipping proxies, Panama/Suez/Red Sea/Hormuz events,
> USO/DBA/XRT/IYT/BDRY.

## Data

- Prices: yfinance auto-adjusted closes for `USO`, `DBA`, `XRT`, `IYT`,
  `BDRY`, and `^VIX`.
- Price sample: 2018-01-02 to 2026-06-29, 2,134 trading days.
- Monthly supply-chain pressure: New York Fed GSCPI, 1998-01 to 2026-05.
- Chokepoint event calendar: manual diagnostic calendar for Suez/Ever Given,
  Black Sea shipping shock, Panama Canal drought restrictions, Red Sea/Suez
  rerouting, and Hormuz oil-shipping stress.
- Freightos/Harpex/FRED shipping-rate data were not used because this run did
  not find a stable public endpoint. `BDRY` is used only as a public dry-bulk
  shipping ETF/futures proxy.

## Literature / Source Preamble

- New York Fed Global Supply Chain Pressure Index:
  `https://www.newyorkfed.org/research/policy/gscpi`
- NY Fed GSCPI data workbook:
  `https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx`
- UNCTAD / IMF / global-trade reporting on Red Sea, Panama Canal, and shipping
  disruption channels motivated the chokepoint event calendar, but this is not
  a replication of proprietary vessel or freight-rate datasets.

## Method

Signals:

- `gscpi_z`: GSCPI rolling z-score.
- `bdry_rv_z`: trailing BDRY realized-vol rolling z-score.
- `event_z`: manual chokepoint-event intensity rolling z-score.
- `maritime_composite_z`: mean of GSCPI, BDRY RV, BDRY 21d momentum, and event
  components, then re-standardized.

Lookahead controls:

- GSCPI monthly observations are assumed available only after month-end plus
  10 business days, then daily forward-filled.
- All signals are shifted one trading day before entering forecasts.
- Future RV target is strictly from `t+1` to `t+H`.
- Sparse event z-scores are winsorized to +/-5 so a single dummy event does not
  mechanically dominate regressions.

Forecast setup:

- Baseline: expanding OOS OLS
  `log(future RV) ~ log RV_5 + log RV_22 + log RV_63 + log VIX variance`.
- Extended: baseline plus one maritime stress signal.
- Targets: annualized future realized variance for `H=5` and `H=22`.
- Loss: QLIKE on future realized variance.
- Inference: `volpred.stats.model_evaluation.dm_test` on pointwise QLIKE
  losses; Harvey-style pass if extended model has `DM t < -3`.
- Multiple testing: Holm p-values across all 40 ETF/horizon/signal cells.
- Secondary test: future 22-day average pairwise correlation among
  `USO/DBA/XRT/IYT`, baseline MSE vs baseline + composite.

## Results

Verdict:

**PARTIAL_GSCPI_RETAIL_5D_SUPPORT_NOT_BROAD_CHOKEPOINT_SIGNAL**

Formal RV forecast tests:

- 40 ETF/horizon/signal cells.
- Harvey pass count: 1.
- Holm-positive pass count: 1.
- Composite maritime signal Holm pass count: 0.
- Composite signal point estimates are positive in 5/10 cells, but none are
  statistically significant after the forecast-loss test.

Only formal hit:

| Target | Horizon | Signal | QLIKE Improvement | DM t | raw p | Holm p |
|---|---:|---|---:|---:|---:|---:|
| XRT | 5d | GSCPI | +2.94% | -4.00 | 0.000065 | 0.0026 |

Correlation-spike test:

- Target: future 22-day average pairwise correlation among
  `USO/DBA/XRT/IYT`.
- Baseline MSE: 1.2585.
- Extended MSE: 1.2706.
- Relative improvement: -0.96%.
- DM t = +1.94, p = 0.052; this goes the wrong direction and does not pass
  Harvey.

## Interpretation

There is a credible but narrow signal: lagged GSCPI improves 5-day XRT
realized-vol forecasts beyond HAR+VIX. That fits a retail-margin-risk story:
aggregate supply-chain pressure may show up fastest in retail ETF volatility.

The broader claim fails. The composite maritime chokepoint proxy does not
robustly improve commodity (`USO`, `DBA`), transport (`IYT`), shipping (`BDRY`),
or cross-asset correlation forecasts. This should not be published as
"chokepoints forecast commodity/shipping volatility." A fair article angle
would be "supply-chain pressure has a narrow short-horizon retail-vol hint, but
the broad maritime chokepoint signal is mostly null."

## Files

- `research_maritime_chokepoint_stress_commodity_retail_ship.py`
- `research_maritime_chokepoint_stress_commodity_retail_ship_results.json`
- `fig_signal_components.png`
- `fig_oos_qlike_improvement.png`
- `fig_corr_spike_proxy.png`
- `data/gscpi_monthly.csv`
- `data/yfinance_prices.csv`
- `data/composite_oos_predictions.csv`
- `codex_review.md`

## Limitations

- `BDRY` is not Freightos or Harpex. It is a tradable dry-bulk proxy, so the
  container-rate and port-congestion channels are only partially represented.
- The event calendar is manually constructed and diagnostic. It mixes clean
  chokepoint shocks with broader geopolitical shocks.
- GSCPI is monthly. The conservative release lag protects against lookahead but
  can miss fast-moving daily disruptions.
- `BDRY` as a target is partly self-referential when BDRY-derived features are
  used as predictors; cross-asset results are more informative.
- This is an empirical proxy test, not a structural causal model of maritime
  logistics.
