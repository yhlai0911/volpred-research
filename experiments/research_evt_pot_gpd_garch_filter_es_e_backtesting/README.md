# EVT-GPD x GARCH-Filtered ES E-Backtesting

## Motivation

This experiment tests whether a semiparametric POT/GPD tail model on GJR-GARCH standardized residuals improves one-day VaR/ES forecasts. The research-program backlog explicitly targets Basel/FRTB-style ES monitoring: compare GARCH-EVT against filtered historical simulation (FHS) and parametric Normal/Student-t baselines using both joint VaR/ES scoring and sequential ES e-backtesting.

This is not a repeat of K1035. K1035 mainly asked whether EVT-GPD fixes VaR/Trinity calibration for GJR and A4f residuals. This experiment adds a direct ES focus: Fissler-Ziegel joint VaR/ES loss, Wang-Wang-Ziegel style e-process diagnostics, and an SPY/HYG equity-versus-credit contrast.

## Literature

- McNeil and Frey (2000), "Estimation of tail-related risk measures for heteroscedastic financial time series", Journal of Empirical Finance. <https://doi.org/10.1016/S0927-5398(00)00012-8>
- Wang, Wang, and Ziegel (2026), "E-backtesting". <https://doi.org/10.48550/arXiv.2209.00991>
- Zhao (2026), "E-Backtesting Expected Shortfall: What Defines a Good Forecasting Method for Chinese Regulators?", Risks. <https://doi.org/10.3390/risks14050110>
- Fissler and Ziegel (2016), "Higher order elicitability and Osband's principle", Annals of Statistics. <https://doi.org/10.1214/16-AOS1439>
- Basel Committee (2019), "Minimum capital requirements for market risk". <https://www.bis.org/bcbs/publ/d457.htm>

## Data

- Assets: SPY and HYG.
- Source: local adjusted-close cache copied from `experiments/k1651/k1651_prices.parquet`.
- Local frozen input: `prices_spy_hyg_2007_2026.parquet`.
- Price sample: 2007-04-11 to 2026-07-02.
- Return sample: 2007-04-12 to 2026-07-02.
- OOS start: 2015-01-01.
- Daily log returns: `log(price).diff()`.

The script checks monotone dates, duplicate dates, NaNs, and non-positive prices before estimating.

## Method

All models use one-day forecasts for return at date `t` with information strictly before `t`.

- Volatility filter: GJR-GARCH(1,1), constant mean, annual expanding refit, daily variance recursion.
- Baselines:
  - `GJR-Normal`
  - `GJR-StudentT`
  - `GJR-FHS`
  - `GJR-EVT-GPD`
- Tail levels: 5% and 1% left tail.
- GPD threshold: top 10% of standardized residual losses.
- VaR tests: Kupiec, Christoffersen independence, Basel-style exact-binomial zone.
- ES diagnostics:
  - Fissler-Ziegel joint VaR/ES loss, lower is better.
  - Sequential ES e-backtesting with GREM = 0.5 * GREE + 0.5 * GREL, 250-day betting window, alert thresholds 2/5/10.

Lookahead guard: each refit uses `y.iloc[:pos]`, excluding `r_t`; daily recursion advances variance with `r[t-1]` and previous conditional variance only.

## Results

Verdict: `EVT_GPD_COMPETITIVE_NOT_DOMINANT`.

Best FZ joint VaR/ES score:

| Cell | Winner | EVT-GPD status |
|---|---:|---:|
| SPY 5% | GJR-EVT-GPD | Winner |
| SPY 1% | GJR-EVT-GPD | Winner |
| HYG 5% | GJR-StudentT | Not winner |
| HYG 1% | GJR-StudentT | Not winner |

Sequential ES e-backtest size-2 detections:

| Model | Cells with detection |
|---|---:|
| GJR-Normal | 4 / 4 |
| GJR-StudentT | 3 / 4 |
| GJR-FHS | 1 / 4 |
| GJR-EVT-GPD | 1 / 4 |

Main interpretation: EVT-GPD helps SPY residual tails and reduces sequential regulatory underestimation pressure relative to parametric Normal/Student-t. It is not a universal upgrade: HYG credit ETF tails are better scored by Student-t in this sample, while EVT/FHS are more conservative and lose FZ score there.

## Artifacts

- `research_evt_pot_gpd_garch_filter_es_e_backtesting.py`
- `research_evt_pot_gpd_garch_filter_es_e_backtesting_results.json`
- `prices_spy_hyg_2007_2026.parquet`
- `fig_fz_loss_race.png`
- `fig_var_violation_rates.png`
- `fig_e_backtest_grem.png`

## Limitations

- Scope is daily adjusted-close SPY/HYG only; no intraday realized measure, no portfolio-level FRTB desk mapping.
- GARCH refit is annual expanding; 250-day rolling Basel-style estimation could change e-process timing.
- GPD threshold is fixed at 10%; threshold sensitivity is not explored here.
- E-backtesting follows the public R reference implementation; it is a regulatory-style sequential diagnostic, not a replacement for model-specific economic validation.
