# Passive ETF-Flow Proxy and Mega-Cap Idiosyncratic Volatility

## Motivation

Jiang, Vayanos, and Zheng (2025) argue that passive flows can disproportionately affect the largest firms. This experiment tests a narrow free-data proxy version of that idea: do SPY/IVV/VOO trading-volume shocks predict larger CAPM residual volatility increases for current mega-cap stocks than for other large caps?

This is not a replication of the RFS paper. yfinance does not provide historical ETF AUM or creation/redemption flow, so the experiment uses ETF dollar volume as a liquidity/attention proxy.

## Literature

- Jiang, Vayanos, and Zheng (2025), "Passive Investing and the Rise of Mega-Firms", *Review of Financial Studies*. https://academic.oup.com/rfs/article/38/12/3461/8280528
- Ben-David, Franzoni, and Moussawi, "Do ETFs Increase Volatility?", NBER / later Journal of Finance lineage. https://www.nber.org/papers/w20071
- Sushko and Turner (2018), "The implications of passive investing for securities markets", BIS Quarterly Review. https://www.bis.org/publ/qtrpdf/r_qt1803j.htm

## Data

- Source: yfinance daily adjusted close and volume.
- Requested period: 2010-09-01 to 2026-06-18.
- Actual monthly panel: 2010-09-30 to 2026-05-31.
- Panel: 7,539 stock-month rows, 189 months, 40 current-name large-cap stocks.
- ETF proxy: SPY, IVV, VOO aggregate dollar volume.
- Top10 current-name mega-cap proxy: AAPL, MSFT, NVDA, AMZN, META, GOOGL, BRK-B, AVGO, TSLA, JPM.

## Method

Monthly stock-level target:

```text
idio_rv = annualized monthly CAPM residual variance
log_idio_rv = log(idio_rv)
```

Passive-flow proxy:

```text
flow_shock = rolling 36-month z-score of monthly change in aggregate SPY+IVV+VOO dollar volume
```

Primary regression:

```text
log_idio_rv_t ~ Top10_i x flow_shock_{t-1}
                + lag_log_idio_rv_{i,t-1}
                + stock fixed effects
                + month fixed effects
```

Standard errors are clustered by month. The primary coefficient is `Top10_i x flow_shock_{t-1}`; expected sign is positive. Harvey-style threshold is `|t| > 3.0` with the expected sign.

Lookahead guard: the primary test uses `flow_shock_l1`; target month `t` does not use ETF volume from month `t`. The contemporaneous specification is reported only as a diagnostic.

## Results

Verdict: `NULL_PROXY`.

| Test | Coef | t-stat | p-value | n obs | Months | Harvey pass |
|---|---:|---:|---:|---:|---:|---|
| Primary lagged month-FE | +0.007416 | +0.287 | 0.7742 | 6,560 | 164 | no |
| Lagged pooled controls | +0.007987 | +0.000 | 1.0000 | 6,560 | 164 | no |
| Contemporaneous month-FE diagnostic | -0.005301 | -0.207 | 0.8358 | 6,600 | 165 | no |

Event diagnostic:

- High-shock threshold: lagged flow shock >= 1.251.
- High-shock months: 17.
- Top10-minus-control log idio-RV spread, high minus normal months: -0.0237.
- Seeded bootstrap 95% CI: [-0.2414, +0.1972].
- `p_gt_0 = 0.5814`.

## Interpretation

This free-data proxy does not support the hypothesis that SPY/IVV/VOO trading-volume shocks disproportionately amplify current mega-cap CAPM residual volatility. The primary lagged interaction is economically tiny and statistically null; the event diagnostic points slightly negative with a wide CI.

Conclusion strength is limited: ETF dollar volume is not ETF AUM flow, not creation/redemption flow, and not an instrument for passive reallocation. The honest result is narrower: in this yfinance proxy design, passive-flow amplification does not show up robustly.

## Caveats

- Current-name stock universe creates survivorship bias.
- Current top-10 membership is used for the whole history; no historical S&P 500 constituent weights.
- Dollar volume mixes investor demand, market-maker inventory, volatility-driven trading, and attention.
- Month fixed effects remove common market shocks but do not identify causal ETF flow.
- A true replication needs historical passive fund flow/AUM, index weights, and preferably stock-level ETF ownership.

## Artifacts

- `research_mega_cap_idiosyncratic_vol_spy_ivv_voo.py`
- `research_mega_cap_idiosyncratic_vol_spy_ivv_voo_results.json`
- `fig_flow_shock_idio_spread.png`
- `fig_interaction_tstats.png`
