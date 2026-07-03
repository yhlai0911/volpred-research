# California Wildfire / Drought ETF Dose-Response Diagnostic

## Purpose

This experiment tests whether West-coast physical climate risk proxies produce
a dose-response in public-market volatility:

- Wildfire dose: CAL FIRE final perimeter acres by alarm date.
- Drought dose: U.S. Drought Monitor California DSCI-style severity and 4-week
  DSCI increase.
- Market response: utility idiosyncratic RV/downside and agriculture ETF
  RV/downside.

This is a public-data proxy diagnostic. It does not estimate utility service
territory exposure, actual wildfire liability, crop yields, insurance losses, or
county-level agricultural production.

## Data

- Price source: yfinance adjusted close, `auto_adjust=True`.
- Price sample: 2011-01-03 through 2026-07-02.
- Utility liability proxy: `PCG`, `EIX`, `SRE` returns relative to `XLU`.
- Agriculture proxy: equal-weight `DBA`, `CORN`, `WEAT` returns relative to
  `SPY`.
- Wildfire source: CAL FIRE California Fire Perimeters (all).
- CAL FIRE sample rows used: `5774` fire rows, `2446` daily event rows.
- Wildfire event rows with acres >= 5,000: `237`.
- Drought source: U.S. Drought Monitor state statistics for California.
- USDM weekly rows: `810`, 2010-12-28 through 2026-06-30.
- Random seed: `42`.

## Method

Wildfire event study:

- Event date is CAL FIRE `Alarm Date`.
- Market targets start on the first trading day strictly after the alarm date.
- Final acres are used only as an ex-post physical dose, not as a real-time
  trading signal.
- Targets are 5d and 22d utility RV/downside log ratios versus a lagged
  63-trading-day pre-event baseline.
- PASS requires positive log-acre coefficient with `t >= 3`, monotone low/mid/high
  acreage terciles, and high-minus-low bootstrap CI above zero.

Drought regression:

- USDM `validStart` is treated as observable after `+2` calendar days, then all
  signals are shifted one trading day.
- DSCI-style score is `D0 + D1 + D2 + D3 + D4` because USDM traditional
  categories are cumulative percentages.
- HAC regressions test both drought level (`dsci_lag1`) and 4-week increase
  (`dsci_delta4w_lag1`) against 5d/22d RV and downside targets.
- PASS requires a positive dose coefficient with `t >= 3`.

## Results

Verdict: **PARTIAL_PUBLIC_PROXY_DOSE_RESPONSE**.

There is one formal pass: a 4-week increase in California drought severity
predicts higher 5d agriculture ETF RV.

| Channel | Target | Horizon | Dose | t-stat | Gate |
|---|---|---:|---|---:|---|
| Drought | ag RV | 5d | 4w DSCI increase | `3.54` | pass |
| Drought | ag RV | 5d | DSCI level | `1.78` | fail |
| Wildfire | utility RV | 5d | log acres | `1.47` | fail |
| Wildfire | utility downside | 5d | log acres | `1.37` | fail |
| Wildfire | utility RV | 22d | log acres | `1.28` | fail |
| Wildfire | utility downside | 22d | log acres | `0.96` | fail |

Detailed pass cell:

- Group: `ag`
- Target: `rv`
- Horizon: `5d`
- `beta_delta4w_lag1 = 0.00325`
- `t_delta4w_lag1 = 3.5355`
- `p_delta4w_lag1 = 0.000407`
- High-minus-low 5d RV target: `0.000286`
- Welch `t = 6.59`

Wildfire results are directionally positive but not formal passes. The 5d utility
RV acreage terciles are monotone and high-minus-low bootstrap CI is positive
(`[0.0456, 0.7391]` in log-ratio units), but the continuous log-acre coefficient
has only `t=1.47`, below the `t>=3` gate.

Utility drought level results are mostly negative. This does not support a broad
"drought raises utility RV" claim in the ETF/large-utility public proxy.

## Interpretation

The honest claim is narrow:

> In this public-data specification, rapid increases in California drought
> severity are associated with higher near-term agriculture ETF RV, but wildfire
> final-acre dose does not pass a formal utility-volatility gate.

This is not enough to claim a broad tradable climate-risk factor. It is enough to
justify a follow-up with crop-region exposure, county-level drought data,
utility service-territory fire overlap, and intraday announcement timing.

## Outputs

- `research_etf_dose_response.py`
- `research_etf_dose_response_results.json`
- `data/price_adjusted_close.csv`
- `data/calfire_fire_perimeters_raw.csv`
- `data/calfire_fire_daily.csv`
- `data/usdm_california_weekly.csv`
- `data/wildfire_event_panel.csv`
- `data/drought_regression_panel.csv`
- `figures/physical_risk_dose_response_summary.png`
- `codex_review.md`

## Limitations

- CAL FIRE final acres are not known on the alarm date; wildfire dose results
  are ex-post diagnostics only.
- State-level California USDM is coarse for agriculture ETF exposure.
- Utility returns relative to `XLU` are not a true liability or service-territory
  risk model.
- Agriculture ETFs include global commodity and roll-yield effects, not only
  California drought.
- Daily close-to-close data can miss intraday event pricing and public-safety
  power-shutoff timing.
