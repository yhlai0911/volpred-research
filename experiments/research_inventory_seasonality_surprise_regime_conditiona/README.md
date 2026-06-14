# Commodity Inventory/Seasonality Regime-Conditional Forward-RV Test

## Motivation

The backlog question was whether commodity volatility becomes more predictable
when seasonal stress coincides with supply-tightness regimes. The intuition is
that low inventories can make seasonal demand or supply shocks harder to absorb,
so the next week's realized volatility should rise more after low-inventory
seasonal signals.

This experiment narrows that idea to a free-data diagnostic. Oil and natural
gas have public weekly EIA inventory proxies. Agriculture does not have a
single comparable weekly inventory proxy for DBA, so DBA is included only as a
seasonality placebo and is not treated as evidence for inventory amplification.

## Literature

- Gorton, Hayashi, and Rouwenhorst (2013), "The Fundamentals of Commodity
  Futures Returns": https://www.nber.org/papers/w13249
- "Futures basis, inventory and commodity price volatility":
  https://mpra.ub.uni-muenchen.de/39903/
- Pindyck (2004), "Volatility and Commodity Price Dynamics":
  https://web.mit.edu/rpindyck/www/Papers/Volatility_Comm_Price.pdf
- EIA weekly crude oil and natural gas storage data: https://www.eia.gov/

## Related Internal Context

Prior commodity-volatility experiments in VolPred repeatedly warn that broad
commodity effects are fragile and that proxy selection matters. This test is
therefore designed as a regime interaction test, not a general commodity timing
strategy and not a substitute for crop-specific inventory or report-surprise
data.

## Data

- Price source: yfinance adjusted close with `auto_adjust=True`.
- Price tickers: CL=F, USO, NG=F, UNG, DBA.
- Price download window: 2006-01-01 to 2026-06-15.
- OOS regression window: 2018-01-02 to 2026-06-08 for futures and 2026-06-05
  for ETFs.
- OOS observations: CL=F 2,121; USO 2,118; NG=F 2,122; UNG 2,118; DBA 2,118.
- Inventory sources:
  - EIA weekly U.S. crude oil stocks excluding SPR (`WCESTUS1`).
  - EIA weekly Lower 48 natural gas working underground storage.
- Cached data live under
  `experiments/research_inventory_seasonality_surprise_regime_conditiona/data/`.

## Method

The target is forward 5-trading-day annualized realized variance computed from
simple close-to-close returns. Simple returns are used because WTI front-month
futures briefly settled below zero in 2020, making log returns undefined for
CL=F.

Inventory features are intentionally conservative:

- weekly EIA as-of dates are delayed by 7 calendar days before daily alignment;
- inventory level z-scores and inventory-change surprise z-scores use rolling
  historical windows shifted by one weekly observation;
- daily regression features are shifted by one trading day;
- seasonal stress month dummies are also shifted by one trading day.

Seasonal stress months are:

- oil: August, September, October;
- natural gas: January, February, July, August, December;
- agriculture: April through August.

Inventory assets use:

`log(fwd5_RV) ~ lagged log trailing5_RV + seasonal + low_inventory + abs_surprise + seasonal*low_inventory + seasonal*abs_surprise`

DBA uses the seasonality-only placebo:

`log(fwd5_RV) ~ lagged log trailing5_RV + seasonal`

Standard errors are Newey-West HAC with 5 lags. Regime mean differences use a
1,000-rep moving-block bootstrap with 5-day blocks and seed 42.

The pre-specified success gate is deliberately strict:

- `PARTIAL`: both tickers in either the oil pair or gas pair must have
  `seasonal*low_inventory` HAC t-stat > 3;
- `SUPPORT`: both oil and gas pairs must pass.

## Results

Predictive regression results:

| Asset | Group | N | Seasonal t | Low-inventory t | Seasonal x low-inventory t | R2 |
|---|---|---:|---:|---:|---:|---:|
| CL=F | oil | 2,121 | 0.931 | -0.319 | -1.116 | 0.284 |
| USO | oil | 2,118 | 0.673 | -0.427 | -0.639 | 0.229 |
| NG=F | gas | 2,122 | -0.075 | -2.623 | -1.854 | 0.351 |
| UNG | gas | 2,118 | 0.057 | -2.439 | -2.238 | 0.404 |
| DBA | agriculture placebo | 2,118 | 5.321 | n/a | n/a | 0.154 |

No oil or gas asset has a positive `seasonal*low_inventory` HAC t-stat above 3.
The oil pair is weakly negative and statistically unconvincing. The gas pair is
also negative; UNG is conventionally significant at 5%, but in the opposite
direction from the amplification hypothesis and below the research gate.

The bootstrap tells the same story. Seasonal low-inventory minus seasonal
normal is negative for CL=F, USO, NG=F, and UNG. Gas low-season interaction
differences are significantly negative. DBA has strong seasonality-only
evidence, but because there is no matched inventory proxy in this experiment,
that result cannot support the low-inventory amplification claim.

## Verdict

NULL.

The inventory-low regime does not robustly amplify seasonal forward-RV
predictability across the paired commodity futures/ETF tests. The result should
not be promoted as commodity supply-tightness evidence. A stronger follow-up
would need report-calendar accurate release timing and commodity-specific crop
or product inventory surprises rather than a broad DBA placebo.

## Research Honesty Notes

- This is a forward-RV diagnostic, not a tradable futures strategy.
- DBA is explicitly not assigned a fake inventory proxy.
- EIA inventory values are delayed and shifted before prediction to reduce
  report-date lookahead risk.
- The NULL verdict is driven by the pre-specified paired gate, not by hiding a
  favorable single-series result.
