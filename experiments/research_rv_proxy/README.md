# Direct Power-Price RV and Renewable Penetration

## Motivation

This experiment addresses `research_rv_proxy`: test power-market realized
volatility directly instead of using utility-equity proxies. The original queue
item proposed EIA Electricity Data Browser hourly RTO price and fuel-mix data;
the local environment has no EIA API key, so this run uses public CAISO OASIS
ZIP endpoints that do not require a key.

## Literature

- Rintamäki, Siddiqui & Salo (2017), "Does renewable energy generation decrease
  the volatility of electricity prices?", *Energy Economics*. VRE can decrease
  or increase daily price volatility depending on regional flexibility and
  wind/solar patterns.
- Owolabi et al. (2023), "Role of Variable Renewable Energy Penetration on
  Electricity Price and its Volatility Across Independent System Operators in
  the United States", *Data Science in Science*. U.S. ISO evidence that VRE
  penetration has nonlinear effects on price volatility.
- Brown & Yucel (2024), "What Fuels the Volatility of Electricity Prices?",
  Dallas Fed Working Paper 2408. Fuel mix and marginal-generation regimes matter
  for real-time electricity-price volatility.

## Data

- Source: CAISO OASIS public ZIP API.
- Price: `PRC_LMP`, `market_run_id=DAM`, LMP component only, nodes
  `TH_NP15_GEN-APND`, `TH_SP15_GEN-APND`, `TH_ZP26_GEN-APND`.
- Renewable forecast: `SLD_REN_FCST`, `market_run_id=DAM`, Solar + Wind.
- Load forecast: `SLD_FCST`, `market_run_id=DAM`, `CA ISO-TAC`.
- Sample: 2024-01-01 to 2025-12-31; OOS forecast starts 2025-01-01.
- EIA status: official v2 API route was tested and returned `API_KEY_MISSING`;
  no paid or manual fallback is used.

## Method

Daily power-price RV is built from hourly day-ahead hub LMP price changes:

```text
price_rv_d = sum_h (LMP_{d,h} - LMP_{d,h-1})^2
log_rv_d = log(price_rv_d)
```

Primary forecasting test per hub:

```text
log_rv_t ~ HAR(log_rv_{t-1}, weekly, monthly) + weekday dummies
log_rv_t ~ HAR(...) + renewable_share_{t-1} + weekday dummies
```

The OOS comparison is expanding-window, one-day ahead, with QLIKE on
`price_rv` and DM-HAC `h=1`. Same-day high-renewable contrasts are reported only
as descriptive diagnostics.

## Lookahead Policy

- Formal predictor is `renew_share_mean_lag1`, i.e. `renewable_share.shift(1)`.
- HAR lag/week/month features are built with `.shift(1)`.
- OOS fit uses rows strictly before the forecast date.
- Same-day renewable share is not used for the PASS gate.
- Seed is fixed at `42` for bootstrap diagnostics.

## Outputs

- `research_rv_proxy.py`
- `research_rv_proxy_results.json`
- `data/caiso_daily_panel.csv`
- `data/oos_forecasts.csv`
- `figures/caiso_renewable_rv_summary.png`

## Final Outcome

Verdict: **NULL**.

This run is a direct power-price pilot, not another utility-stock proxy. It uses
CAISO NP15 day-ahead hub LMP from 2024-01-01 to 2025-12-30, with 2025 as the OOS
period (`n_oos=364`).

Formal forecast result:

- Baseline HAR QLIKE: `0.13078`
- HAR + lagged renewable share QLIKE: `0.13110`
- QLIKE improvement: `-0.25%` (worse)
- DM t-stat for augmented-minus-baseline loss: `0.76`, p=`0.447`
- Lagged renewable-share coefficient: beta=`0.152`, HAC t=`0.706`, p=`0.480`

So lagged renewable penetration does **not** improve one-day-ahead NP15
power-price RV forecasts over a HAR baseline.

Descriptive diagnostic:

- Top-quartile same-day renewable-share days have higher log RV by `+0.402`
  (bootstrap 95% CI `[0.279, 0.528]`).
- Negative-price day rate is `47.5%` on high-renewable days versus `2.9%`
  otherwise.

This same-day pattern is economically interesting, but it is **not** the formal
forecast gate because the script does not model CAISO publication timestamps.

## Limitations

- EIA v2 was not usable in this environment because no `EIA_API_KEY` was present.
- The completed pilot is CAISO NP15 only; multi-hub CAISO downloads were
  rate-limited during the hourly tick.
- The result should not be written as a broad multi-ISO conclusion without EIA
  key access or a more robust public ISO data pipeline.

## Reviewer

- `codex_review.md`: `CONDITIONAL_PASS_AS_PILOT`.
