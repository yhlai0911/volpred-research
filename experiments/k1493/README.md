# K1493 — VRP Decline and Short-Vol Edge

- Experiment ID: `K1493`
- Status: complete
- Seed: `42`
- Task: `research_variance_risk_premium_edge`

This experiment tests whether the variance risk premium decline thesis maps into weaker short-vol economics using only free daily data.

## Motivation

The task asks whether short-vol strategies lost their economic edge as the variance risk premium (VRP) declined. The experiment separates two related but different questions:

1. Did a public-data VRP proxy decline after 2018?
2. Did short-vol ETF proxies lose economic edge after 2018?

This separation matters because tradable short-vol products include futures roll, leverage changes, daily rebalancing, path dependence, and tail survival. Those are not the same object as an option-chain variance premium.

## Literature Check

1. **Dew-Becker and Giglio (2025), Chicago Fed WP 2025-17, _The Decline of the Variance Risk Premium_**
   - Link: <https://www.chicagofed.org/publications/working-papers/2025/2025-17>
   - Main motivation: traded and synthetic option alphas have become indistinguishable from zero over the past 15 years.
2. **Bollerslev, Tauchen, and Zhou (2009), RFS, _Expected Stock Returns and Variance Risk Premia_**
   - Link: <https://academic.oup.com/rfs/article-abstract/22/11/4463/1565787>
   - Establishes VRP as a return-predictability and priced variance-risk object.
3. **Carr and Wu (2009), RFS, _Variance Risk Premia_**
   - Link: <https://academic.oup.com/rfs/article-abstract/22/3/1311/1581057>
   - Formalizes measuring variance risk premia through option-implied variance versus realized variance.
4. **ProShares SVXY product page**
   - Link: <https://www.proshares.com/our-etfs/strategic/svxy>
   - Used only to define the product proxy as short exposure to VIX futures, not as a pure variance swap.

## Data

- Source: yfinance adjusted close
- Symbols: `SPY`, `^VIX`, `SVXY`, `VIXY`, `VXX`, `BIL`
- Requested sample: `2006-01-01` to `2026-06-14`
- Snapshot: `experiments/k1493/close_prices.csv`

Availability differs by instrument:

| Series | First obs | Role |
|---|---:|---|
| SPY / VIX | 2006-01-03 | VRP proxy |
| BIL | 2007-05-30 | cash benchmark |
| VIXY | 2011-01-04 | naive short-VIX-futures proxy |
| SVXY | 2011-10-04 | actual inverse VIX-futures ETF proxy |
| VXX | 2018-01-25 | post-2018 naive short long-vol proxy only |

## Method

### VRP proxy

For each trading day:

```text
VRP_t = (VIX_t / 100)^2 - forward_RV21_t
forward_RV21_t = sum(r_{t+1:t+21}^2) * (252 / 21)
```

This is an ex-post diagnostic, not a tradable signal. It uses future realized variance because the object being measured is the realized premium embedded in today's implied variance.

Segments:

- pre: `2006-01-01` to `2017-12-31`
- post: `2018-01-01` to latest date with a full forward 21-trading-day RV window

Tests:

- Newey-West mean t-stat for each segment
- Welch difference test for post minus pre mean VRP

### Short-Vol Economics

Proxy strategies:

1. `SVXY_actual`: actual SVXY adjusted-close log returns
2. `short_VIXY_naive`: `-VIXY` daily log return
3. `short_VXX_naive`: `-VXX` daily log return, post-2018 only

Benchmarks:

- `SPY`
- `BIL`

Metrics:

- annualized return
- annualized volatility
- Sharpe
- max drawdown
- worst day
- worst 5-day return
- skewness
- `strategy_dm_test(..., loss_fn="negative_return")` against SPY/BIL

Post-period robustness cuts:

- full post: `2018-01-01` onward
- after Volmageddon: `2018-03-01` onward
- after COVID shock: `2020-05-01` onward
- recent: `2023-01-01` onward

## Main Results

Verdict: `MIXED_EDGE_EROSION`

The public VIX-minus-forward-RV proxy does **not** provide clean evidence that the VRP mean vanished. Actual short-vol product economics did deteriorate sharply.

### VRP proxy

| Segment | n | Mean | Median | Positive share | NW t vs 0 |
|---|---:|---:|---:|---:|---:|
| 2006-2017 | 3,020 | 0.00873 | 0.01059 | 85.0% | 1.97 |
| 2018-2026 | 2,088 | 0.00711 | 0.01334 | 81.7% | 1.18 |

Post minus pre mean:

- Difference: `-0.00162`
- Welch t: `-0.83`
- p-value: `0.407`

Interpretation: the mean is lower after 2018, but this daily public proxy cannot reject equality of pre/post means.

### SVXY actual product proxy

| Segment | Ann return | Sharpe | MDD | Worst day | Worst 5d |
|---|---:|---:|---:|---:|---:|
| 2011-2017 | 66.9% | 0.81 | -67.9% | -26.4% | -45.4% |
| 2018-2026 | -16.9% | -0.25 | -95.2% | -82.9% | -92.1% |
| 2018-03 onward | 10.1% | 0.25 | -62.2% | -21.4% | -33.8% |
| 2020-05 onward | 21.5% | 0.53 | -46.4% | -21.4% | -33.8% |

`SVXY` loses its full-period post-2018 edge. Even after excluding February 2018, it recovers only weakly compared with the pre-2018 period.

DM tests for SVXY:

| Segment | vs SPY t/p | vs BIL t/p |
|---|---:|---:|
| 2011-2017 | -1.76 / 0.078 | -2.19 / 0.028 |
| 2018-2026 | +1.14 / 0.256 | +0.69 / 0.489 |

Sign convention: negative t means SVXY has lower negative-return loss than benchmark. Pre-2018 is economically strong but below Harvey `|t| > 3`; post-2018 is not better than SPY or BIL.

### Naive short-VIXY proxy

| Segment | Ann return | Sharpe | MDD | Worst day | Worst 5d |
|---|---:|---:|---:|---:|---:|
| 2011-2017 | 173.3% | 1.64 | -49.3% | -19.4% | -39.8% |
| 2018-2026 | 67.5% | 0.71 | -80.6% | -30.1% | -48.4% |
| 2018-03 onward | 78.9% | 0.81 | -80.6% | -30.1% | -48.4% |
| 2020-05 onward | 115.1% | 1.10 | -54.6% | -30.1% | -48.4% |

Naive short VIXY still has a positive average return post-2018, but the drawdown and capital-survival profile worsens materially. This proxy is not directly tradable without borrow/margin/cap constraints.

## Conclusion

The task's hypothesis is only partly supported:

1. **VRP mean decline:** weak in this proxy. The public-data VIX-minus-forward-RV measure declines from `0.00873` to `0.00711`, but the difference is not statistically significant (`p=0.407`).
2. **Short-vol ETF edge:** clearly worse for actual `SVXY`. Pre-2018 Sharpe `0.81` becomes post-2018 `-0.25`, with MDD deteriorating from `-67.9%` to `-95.2%`.
3. **Mechanism:** the edge erosion in tradable proxies is not cleanly attributable to a lower VRP mean alone. It also reflects tail losses, product leverage design, VIX futures roll exposure, and path dependence.

Reader-facing phrasing should be conservative:

> 「短波產品的交易 edge 確實變差，但免費日頻資料不能證明底層 VRP 本身已經消失。更準確的說法是：VRP carry 仍可見，產品化後的尾部風險與結構成本吃掉了很多可交易收益。」

## Limitations

1. No option chain, variance swap, or delta-hedged option PnL data are used.
2. `VIX^2 - forward RV21` is a rough public proxy, not the Chicago Fed paper's traded-option alpha.
3. SVXY changed exposure after 2018 Volmageddon, so actual product returns mix premium, tail loss, and product design.
4. Naive short VIXY/VXX ignores borrow cost, margin calls, recalls, path-dependent rebalancing constraints, and capital survival.
5. BIL Sharpe is mechanically high in the post-2018 rate regime because its volatility is tiny; use it as a cash hurdle, not as a comparable risky strategy.

## Artifacts

- [`experiments/k1493/k1493.py`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1493/k1493.py)
- [`experiments/k1493/k1493_results.json`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1493/k1493_results.json)
- [`experiments/k1493/close_prices.csv`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1493/close_prices.csv)
- ![VRP periods](/Users/yhlai0911/Desktop/volpred-research/experiments/k1493/fig_vrp_periods.png)
- ![Short vol NAV](/Users/yhlai0911/Desktop/volpred-research/experiments/k1493/fig_short_vol_nav.png)
- ![Strategy metrics](/Users/yhlai0911/Desktop/volpred-research/experiments/k1493/fig_strategy_metrics.png)
