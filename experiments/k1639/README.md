# K1639 - Hierarchical portfolio construction OOS horse race

## Research Question

Do hierarchical allocation methods improve out-of-sample portfolio outcomes versus simple baselines?

The tested hierarchy family is HRP, HERC-ERC, NCO minimum-variance, and a transparent Schur/block minimum-variance approximation. The baselines are equal weight, inverse volatility, equal-risk-contribution risk parity, and long-only minimum variance.

## Data

- Source: yfinance adjusted close, cached in `data/adjusted_close_yfinance.csv`
- Universe: SPY, QQQ, IWM, EFA, EEM, TLT, IEF, LQD, HYG, GLD, DBC
- Common price period: 2007-04-11 to 2026-07-02
- Return rows: 4,837
- OOS evaluation after 252-day lookback: 2008-04-11 to 2026-07-02
- OOS days: 4,585

## Method

Each strategy is rebalanced monthly. On return day `t`, the covariance matrix is estimated from returns `t-252` through `t-1` only. The code makes this explicit with:

```python
hist = returns.iloc[i - LOOKBACK : i]
```

The script also includes an audit-visible `signal.shift(1)` helper, but the live simulation uses the stricter rolling-window convention above rather than multiplying same-day signals by same-day returns.

Transaction cost is 5 bps per dollar traded. All strategies are long-only, fully invested, unlevered, and evaluated on the same close-to-close return series.

## Main Result

Verdict: `CONDITIONAL_PASS_NULL_HIERARCHICAL_DOES_NOT_BEAT_SIMPLE_BASELINES`

Net Sharpe ranking:

1. `erc_risk_parity`: 0.743
2. `inverse_vol`: 0.703
3. `herc_erc`: 0.685
4. `equal_weight`: 0.645
5. `hrp`: 0.643
6. `min_variance`: 0.537
7. `schur_block_mv`: 0.522
8. `nco_minvar`: 0.448

Best drawdown:

- `min_variance`: MDD -17.8%
- `schur_block_mv`: MDD -18.8%
- `hrp`: MDD -20.1%
- `herc_erc`: MDD -20.2%
- `erc_risk_parity`: MDD -20.4%

The hierarchy methods do not deliver a robust Sharpe improvement over the simple ERC risk-parity baseline. HERC-ERC beats long-only minimum variance on Sharpe, but still trails ERC risk parity.

## Formal Checks

Paired moving-block bootstrap on net Sharpe differences, 1,000 reps, 21-day blocks, seed fixed.

Versus `erc_risk_parity`:

- `hrp`: Sharpe diff -0.100, 95% CI [-0.241, +0.049]
- `herc_erc`: Sharpe diff -0.058, 95% CI [-0.209, +0.091]
- `nco_minvar`: Sharpe diff -0.295, 95% CI [-0.501, -0.081]
- `schur_block_mv`: Sharpe diff -0.221, 95% CI [-0.404, -0.029]

Versus `min_variance`:

- `herc_erc`: Sharpe diff +0.148, 95% CI [+0.012, +0.286]
- `hrp`: Sharpe diff +0.106, 95% CI [-0.026, +0.238]
- `nco_minvar`: Sharpe diff -0.089, 95% CI [-0.202, +0.020]
- `schur_block_mv`: Sharpe diff -0.015, 95% CI [-0.115, +0.093]

## Interpretation

The null is economically informative. In this ETF panel, most of the useful diversification is already captured by inverse-vol / ERC risk parity. The hierarchical tree does not add a stable extra edge once all strategies share the same data, lag, rebalance schedule, and costs.

Schur/block and minimum-variance variants reduce drawdown but concentrate into low-volatility bond/credit sleeves and give up too much return. HRP/HERC diversify more than pure minimum variance, but their turnover is materially higher than ERC without producing a higher Sharpe.

## Limitations

- ETF adjusted close is a public proxy, not institutional total-return index data.
- Expected returns are deliberately ignored; this is covariance-only portfolio construction.
- `schur_block_mv` is a transparent recursive block-MV approximation, not a full reproduction of every Schur Complementary Allocation variant.
- Monthly execution and 5 bps transaction cost are simplified assumptions applied equally to all dynamic strategies.

## Outputs

- `k1639.py`: reproducible experiment script
- `k1639_results.json`: full metrics, tests, metadata, and limitations
- `data/k1639_performance_table.csv`: performance summary
- `data/k1639_net_returns.csv`: daily net return panel
- `data/k1639_average_weights.csv`: average weights by strategy
- `figures/k1639_net_sharpe_mdd_turnover.png`
- `figures/k1639_average_weights_heatmap.png`
- `figures/k1639_final_quasi_diag_corr.png`

## Literature Checked

- Lopez de Prado (2016), Building Diversified Portfolios that Outperform Out of Sample
- Lopez de Prado (2019), A Robust Estimator of the Efficient Frontier
- Raffinot (2018), The Hierarchical Equal Risk Contribution Portfolio
- Cotton (2024), Schur Complementary Allocation
