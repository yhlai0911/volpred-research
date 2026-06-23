# K1538 - Bond-fund run-pressure proxy and credit ETF volatility

## Motivation

This experiment tests whether a public proxy for open-end fixed-income fund
run pressure leads credit ETF realized volatility.

The task is motivated by the open-end fund liquidity-transformation literature:
bond mutual funds issue daily redeemable claims against less liquid fixed-income
assets, so redemptions can look run-like during stress. This experiment is a
free-data diagnostic, not a replication using ICI fund-level flows or fund NAV
microdata.

## Differentiation

Prior internal results already cover related but different channels:

- K1332: private-credit / BDC public proxy, narrow credit-only pass.
- K1499: BIZD-minus-HYG NAV-discount proxy, narrow HYG 5-day result after
  controls.
- K1538: broad bond ETF volume, price pressure, illiquidity, and public cash
  migration proxies for open-end bond-fund run pressure.

K1538 uses K1538 because K1536 is reserved in `research_program.md` and K1537 is
already occupied by the biodiversity proxy line.

## Literature Precheck

- Ma, Xiao, and Zeng, "Bank Debt, Mutual Fund Equity, and Swing Pricing in
  Liquidity Provision", Review of Financial Studies.
- Jin, Kacperczyk, Kahraman, and Suntheim, "Swing Pricing and Fragility in
  Open-End Mutual Funds", Review of Financial Studies.
- IMF, "Fund Investor Types and Bond Market Volatility", Global Financial
  Stability Note 2025.
- Xiao / Zeng, "Mutual Fund Liquidity Transformation and Reverse Flight to
  Liquidity".

## Data

- yfinance daily adjusted close and volume, requested 2010-01-01 to 2026-06-24.
- Effective daily sample: 2010-01-04 to 2026-06-23, 4,143 rows.
- ETFs: `AGG`, `BND`, `LQD`, `HYG`, `BKLN`, `TLT`, `SPY`, `^VIX`.
- FRED series:
  - `DPSACBW027SBOG`: deposits, all commercial banks, weekly.
  - `MMMFFAQ027S`: money market funds total financial assets, quarterly.

FRED series are explicitly low frequency and forward-filled to daily dates; they
are context proxies, not daily fund-flow measurements.

## Method

The run-pressure proxy is the rolling z-score average of:

- bond ETF dollar-volume shocks (`AGG`, `BND`, `LQD`, `HYG`),
- negative 5-day broad bond ETF return pressure,
- HYG underperformance versus LQD,
- Amihud-style ETF illiquidity for `HYG`, `LQD`, `BKLN`,
- FRED cash migration: money-market asset growth minus bank-deposit growth.

Lookahead guard: the predictive variable is always
`signal_lag = run_pressure_index.shift(1)`. Targets begin at date `t`, so the
signal uses only information through `t-1`.

Formal tests:

- OLS predictive regressions with Newey-West HAC standard errors.
- Controls: own lagged RV21, SPY lagged RV21, lagged log VIX, lagged HYG-LQD
  credit underperformance.
- Targets: `HYG`, `LQD`, `BKLN`, `TLT` forward RV5/RV21 and HYG-SPY forward
  21-day downside correlation.
- Harvey-style gate: expected positive coefficient with `t >= 3`.
- Bonferroni and BH q-values across 9 HAC tests.
- Expanding-window OOS MSE comparison, with HAC DM test on augmented-minus-
  baseline squared-error loss.

## Results

Verdict: **WEAK_DIRECTIONAL_PROXY**.

No formal gate passes. The strongest HAC result is HYG 5-day forward realized
volatility:

| Target | Horizon | beta | HAC t | raw p | BH q | Bonferroni p | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| HYG | RV5 | +0.00284 | +2.04 | 0.041 | 0.191 | 0.372 | FAIL |
| HYG | RV21 | +0.00204 | +1.68 | 0.092 | 0.191 | 0.832 | FAIL |
| BKLN | RV5 | +0.00301 | +1.65 | 0.098 | 0.191 | 0.883 | FAIL |
| LQD | RV5 | +0.00363 | +1.51 | 0.132 | 0.191 | 1.000 | FAIL |
| HYG-SPY | downside corr21 | +0.01223 | +1.45 | 0.148 | 0.191 | 1.000 | FAIL |

OOS forecasts are directionally better but also fail formal gates:

| Target | Horizon | MSE improvement | DM t | p | Gate |
|---|---:|---:|---:|---:|---|
| HYG | 5d | +4.06% | -1.47 | 0.142 | FAIL |
| LQD | 5d | +4.35% | -1.56 | 0.119 | FAIL |
| BKLN | 5d | +4.20% | -1.88 | 0.061 | FAIL |
| TLT | 5d | +2.01% | -1.36 | 0.173 | FAIL |

Interpretation: the proxy points in the economically expected direction for
credit-sensitive ETF volatility, especially short-horizon HYG/BKLN/LQD, but the
signal is too weak for a reader-facing positive claim.

## Outputs

- `k1538_bond_fund_run_proxy_credit_etf_vol.py`
- `k1538_bond_fund_run_proxy_credit_etf_vol_results.json`
- `k1538_bond_fund_run_proxy_credit_etf_vol_daily_panel.csv`
- `figures/k1538_run_pressure_timeseries.png`
- `figures/k1538_hac_tstats.png`
- `codex_review.md`

## Limitations

- No ICI fund-level flow or NAV microdata are used.
- ETF trading volume can reflect hedging or institutional ETF use, not only
  open-end mutual fund redemptions.
- FRED cash-migration variables are low frequency and cannot identify daily
  fund runs.
- ETF volatility is not the same as TRACE corporate bond volatility.
- Results are associations, not causal evidence of fund-run fire sales.
