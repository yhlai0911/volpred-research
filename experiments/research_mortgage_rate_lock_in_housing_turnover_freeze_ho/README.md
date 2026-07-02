# Mortgage-Rate Lock-In and Housing Turnover Freeze

## Question

Does a mortgage-rate lock-in wedge, combined with housing turnover freeze proxies, forecast realized variance for homebuilders, brokerage/housing platforms, and regional banks?

Backlog item:

> Mortgage-rate lock-in / housing turnover freeze 是否領先 homebuilder、brokerage、regional-bank RV.

## Data

- Mortgage rate: FRED `MORTGAGE30US`, weekly 30-year fixed mortgage rate.
- Housing turnover and supply proxies: FRED `ACTLISCOUUS`, `NEWLISCOUUS`, `MSACSR`, `HOUST`, `PERMIT`, and `HSN1F`.
- Equity prices: yfinance daily adjusted close, downloaded with `auto_adjust=False` and then using the explicit `Adj Close` column.
- Target assets:
  - Homebuilders: `XHB`, `ITB`, `DHI`, `LEN`, `PHM`, `TOL`
  - Regional banks: `KRE`, `KBE`
  - Housing platforms and mortgage names: `Z`, `OPEN`, `RKT`, `UWMC`
- Main monthly panel starts after the Realtor.com listing series and causal normalization have enough history.

FRED existing-home-sales tickers checked during preflight (`EXHOSLUSM495N`, `EXHOSLUSM495S`) only exposed 13 months through the public CSV endpoint, so they are excluded from the formal sample.

## Method

1. Convert weekly mortgage rates and monthly FRED housing series to a monthly panel.
2. Build an embedded-rate proxy as a 36-month EWMA of mortgage rates shifted by 6 months.
3. Define the lock-in wedge as current mortgage rate minus the embedded-rate proxy.
4. Build turnover-freeze components from causally normalized new listings YoY, months supply, housing starts YoY, permits YoY, and new-home sales YoY.
5. Apply `raw_features.shift(1)` before merging with same-month target RV, so the signal from month `t-1` forecasts realized variance in month `t`.
6. Aggregate daily squared log returns to monthly realized variance.
7. Compare a pooled OOS log-RV multiplier model against a trailing 12-month RV baseline using QLIKE.
8. Report clustered OLS by month, month-bootstrap OOS loss differences, and high-lock-in regime contrasts.

## Files

- `research_mortgage_rate_lock_in_housing_turnover_freeze_ho.py`: reproducible script.
- `research_mortgage_rate_lock_in_housing_turnover_freeze_ho_results.json`: machine-readable results.
- `data/raw/fred_*.csv`: raw FRED CSV caches.
- `data/raw/yfinance_adj_close_*.csv`: yfinance adjusted-close caches.
- `data/monthly_signals.csv`: lagged signal panel.
- `data/monthly_rv_panel.csv`: asset-month target panel.
- `data/oos_predictions.csv`: OOS forecast and QLIKE rows.
- `figures/`: diagnostics.

## References

- FHFA Working Paper 24-03, "The Lock-In Effect of Rising Mortgage Rates".
- Federal Reserve FEDS, "Locked In: Mobility, Market Tightness, and House Prices".
- Fonseca, Liu, Lu, and Liu, "Mortgage Lock-In, Mobility, and Labor Reallocation".
- "Household Mobility and Mortgage Rate Lock", Journal of Financial Economics / NBER working paper.

## Current Result

Completed run:

```bash
uv run python experiments/research_mortgage_rate_lock_in_housing_turnover_freeze_ho/research_mortgage_rate_lock_in_housing_turnover_freeze_ho.py
```

Verdict: `null_or_inconclusive`.

Key diagnostics:

- Sample: 2019-08 to 2026-06, 938 asset-month rows, 83 months, 12 assets.
- Groups: 6 homebuilder names/ETFs, 4 housing-platform or mortgage names, 2 regional-bank ETFs.
- Latest lagged lock-in wedge: 0.176 percentage points; latest lagged turnover-freeze z-score: 0.611.
- Clustered OLS by month: lock-in wedge z coefficient = 0.059, p = 0.309; turnover-freeze z coefficient = 0.083, p = 0.358.
- OOS QLIKE model-vs-baseline loss difference = +0.376, month-bootstrap 95% CI [+0.255, +0.515]. Positive means the lock-in model is worse than the trailing-12-month RV baseline.
- By group, OOS QLIKE loss differences are also positive: homebuilders +0.382, housing platforms +0.364, regional banks +0.384.
- High-lock-in regime contrast is negative rather than positive: mean scaled RV difference = -1.582, 95% CI [-5.334, +0.430], p = 0.631.

Interpretation: this public-data pilot does not provide robust evidence that a mortgage-rate lock-in wedge plus turnover-freeze proxies reliably forecast realized variance for the selected homebuilder, housing-platform, mortgage, or regional-bank targets. The result should not be generalized to loan-level mortgage lock-in research: the embedded-rate proxy is derived from market mortgage-rate history rather than borrower-level coupon data.
