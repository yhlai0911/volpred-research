# Thematic Concentration Public ETF Proxy

## Purpose

This experiment tests whether a public proxy for thematic fund concentration and
attention predicts underlying-stock crowding volatility.

This is **not** a mutual-fund TCI replication. The RFS paper constructs a
thematic concentration index from fund holdings and firm-level thematic
exposures. This run uses current yfinance thematic ETF top holdings as an
ex-post proxy, then combines static holdings concentration with lagged ETF
dollar-volume attention.

## Data

- Price sample: 2021-01-01 through 2026-07-03.
- Regression panel: 2021-06-01 through 2026-07-02.
- Thematic ETF candidates: `ARKK`, `ARKW`, `ARKG`, `ARKF`, `AIQ`, `BOTZ`,
  `ROBO`, `CIBR`, `HACK`, `FINX`, `CLOU`, `DRIV`, `ICLN`, `TAN`, `LIT`, `SKYY`.
- ETFs with usable U.S. top holdings: `16`.
- Top-holding rows used: `122`.
- Unique underlying symbols: `76`.
- Underlying stock panel rows: `97128`.
- ETF panel rows: `20448`.
- Maximum ETF top-10 HHI: `0.04931`.
- Maximum ETF top-5 share: `0.46487`.
- Random seed: `42`.

## Method

Static proxy:

- Pull current ETF top holdings from yfinance `funds_data.top_holdings`.
- Keep U.S.-style tickers with usable daily price history.
- Compute ETF top-10 HHI, top-5 share, and holding weights.

Time-varying signal:

- ETF attention is log dollar volume transformed into a rolling 63-day z-score.
- Signal is shifted one trading day.
- Each underlying stock receives the sum of `ETF attention × ETF HHI × holding
  weight` across theme ETFs that hold it in the current top-holdings snapshot.

Targets:

- Underlying-stock residual RV and downside semivariance relative to `QQQ`.
- Theme ETF residual RV and downside semivariance relative to `QQQ`.
- Horizons: 5d and 22d.
- Targets are log ratios versus lagged 63-day baselines.

Controls and gate:

- Regressions include entity fixed effects and lagged recent 5d RV control.
- Standard errors are clustered by stock or ETF.
- Primary PASS gate is stock-level only: coefficient > 0, clustered t-stat >=
  `3.0`, and high-minus-low pressure bucket Welch t-stat >= `3.0`.
- ETF-level tests are auxiliary.

## Results

Verdict: **PASS_ETF_PROXY**.

Primary stock-level cells:

| Target | Horizon | Beta | Clustered t | High-low diff | Welch t | Gate |
|---|---:|---:|---:|---:|---:|---|
| stock RV | 5d | `0.03862` | `5.2349` | `0.10410` | `10.8744` | pass |
| stock downside | 5d | `0.10875` | `7.0006` | `0.22177` | `7.0973` | pass |
| stock RV | 22d | `0.03200` | `3.9769` | `0.05101` | `7.3280` | pass |
| stock downside | 22d | `0.05025` | `5.4840` | `0.08718` | `9.9492` | pass |

Auxiliary ETF-level cells also pass:

- ETF RV 5d: beta `0.05042`, clustered t `4.0809`.
- ETF downside 5d: beta `0.14273`, clustered t `4.3132`.
- ETF RV 22d: beta `0.03843`, clustered t `3.4293`.
- ETF downside 22d: beta `0.07381`, clustered t `4.7372`.

## Interpretation

The honest claim is:

> In a public ETF proxy using current top holdings, lagged concentration-weighted
> ETF attention is associated with higher next-week and next-month residual
> volatility in the underlying stocks.

This does **not** prove the mutual-fund TCI mechanism. Current holdings introduce
ex-post basket definition, top-holdings data are incomplete, and ETF dollar
volume can capture theme news or volatility clustering even after a lagged RV
control. A full claim requires historical N-PORT holdings or the authors' TCI
data.

## Outputs

- `research_mutual_fund_thematic_concentration_underlying_th.py`
- `research_mutual_fund_thematic_concentration_underlying_th_results.json`
- `data/theme_etf_top_holdings_snapshot.csv`
- `data/price_adjusted_close_volume.csv`
- `data/underlying_stock_pressure_panel.csv`
- `data/theme_etf_pressure_panel.csv`
- `figures/thematic_concentration_proxy_summary.png`
- `codex_review.md`

## Limitations

- ETF top holdings are current snapshots and define an ex-post proxy universe.
- yfinance top-holdings data usually include only top holdings, not full
  portfolios.
- ETF dollar volume is a noisy attention/flow proxy.
- Entity fixed effects and lagged RV controls reduce but do not eliminate
  volatility-clustering explanations.
- The result is an ETF proxy finding, not a mutual-fund TCI or N-PORT finding.
