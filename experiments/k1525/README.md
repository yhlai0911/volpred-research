# K1525: Idiosyncratic-Volatility ICAPM Covariance-Risk Proxy

## Question

Can cross-sectional idiosyncratic volatility act as a proxy for ICAPM covariance risk and forecast next-month U.S. equity market excess returns?

The backlog item references Han and Li's CBIV logic. K1525 is a conservative yfinance proxy, not a CRSP long-sample replication.

## Literature Setup

- Han and Li, *Idiosyncratic Volatility and the ICAPM Covariance Risk*, motivates using the cross-section of CAPM residual volatilities to proxy covariance risk with an unobserved hedge portfolio.
- Goyal and Santa-Clara (2003), *Idiosyncratic Risk Matters!*, reports a positive relation between average stock variance and future market returns.
- Guo and Savickas (2006), *Idiosyncratic Volatility, Stock Market Volatility, and Expected Stock Returns*, argues the sign and robustness depend on value weighting and market-volatility controls.

## Data

- Source: yfinance.
- Universe: current-name liquid U.S. large-cap stocks listed in `k1525.py`.
- Market: `SPY`.
- Cash/excess-return proxy: `SHY`.
- Daily sample starts in 2004 where data are available.
- OOS forecast evaluation starts `2012-01-31`.

This current-name universe has survivorship bias and is not a substitute for CRSP.

## Method

1. Compute daily stock returns and rolling 126-day CAPM residuals against `SPY`.
2. Annualize trailing idiosyncratic volatility and sample it at month end.
3. Build aggregate proxies:
   - `EWIV`: equal-weight average idiosyncratic volatility.
   - `LWIV`: dollar-volume-weighted idiosyncratic volatility.
   - `CBIV_spread`: `EWIV - LWIV`.
   - `beta_weighted_IV`.
   - `hedge_cov_36m`: trailing covariance between the known high-minus-low idio-vol hedge return and market excess return.
4. Fama-MacBeth: regress next-month stock excess returns on lagged idio-vol and beta each month; test the average gamma with HAC t-stat.
5. Time-series OOS: recursively forecast next-month `SPY - SHY` returns with expanding OLS and compare against an expanding historical-mean baseline.

Formal test: OOS R² plus `volpred.stats.model_evaluation.dm_test` on squared forecast errors. Harvey pass requires `DM t < -3` and positive OOS R².

## Outputs

Run:

```bash
uv run python experiments/k1525/k1525.py
```

Artifacts:

- `k1525.py`
- `k1525_results.json`
- `k1525_oos_r2.png`
- `codex_review.md`

## Result

Verdict: `MIXED_CROSS_SECTION_ONLY`.

Key numbers:

| Layer | Result |
|---|---|
| Fama-MacBeth idio-vol gamma | `+0.00514`, HAC `t=4.063`, Harvey pass |
| Fama-MacBeth beta gamma | `+0.00142`, HAC `t=1.103`, fail |
| Annualized Q5-minus-Q1 next-month spread | `+16.18%` in the current-name large-cap proxy |
| Best idio timing model | `LWIV`, OOS R² `-0.122%`, DM `t=0.769` |
| Best overall timing model | `market_vol_control`, OOS R² `+0.234%`, DM `t=-0.486`, fail |
| Harvey-pass idio timing models | `0/7` |

Interpretation:

Lagged idiosyncratic volatility is priced in the current-name large-cap cross-section, but the same information does not translate into a useful next-month SPY excess-return timing signal. The ICAPM covariance-risk mechanism is therefore not supported as a market-timing predictor in this yfinance proxy.

The conclusion must retain the proxy limitations above. In particular, this is not evidence for or against the full Han-Li long-sample CBIV result.
