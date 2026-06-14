# experiment_defensive_factor_drawdown_decomposition_2026_06_14

## Question

防禦因子是否真的降低 drawdown？如果有，是降低「進入 drawdown 的頻率」，還是降低「drawdown 發生後的深度」？

本實驗比較 `USMV`、`SPLV`、`QUAL`、`VLUE` 與 `SPY`，並加上一個簡單 MA200 trend overlay，檢查 trend filter 是否提供互補保護。

## Literature

- The Best Defensive Strategies: Two Centuries of Evidence, *Financial Analysts Journal* / CFA Institute, 2026: https://rpc.cfainstitute.org/research/financial-analysts-journal/2026/best-defensive-strategies
- Frazzini and Pedersen (2014), Betting Against Beta, *Journal of Financial Economics*: https://www.aqr.com/Insights/Research/Journal-Article/Betting-Against-Beta
- Asness, Frazzini, and Pedersen (2019), Quality Minus Junk, *Review of Accounting Studies*: https://research.cbs.dk/en/publications/quality-minus-junk-2/
- Blitz and van Vliet (2007), The Volatility Effect: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=980865

## Prior Project Context

- K1446 已確認 `USMV` 在 ETF 層級有較低 realized volatility / downside deviation。
- K89 / K566 則顯示 factor ETF 放入 VT / timing 框架不會自動產生 alpha。
- 本實驗不重複 alpha 問題，而是拆解 drawdown 機制。

## Data

- Source: `yfinance`, adjusted close
- Tickers: `SPY`, `USMV`, `SPLV`, `QUAL`, `VLUE`
- Common sample: 2013-07-22 to 2026-06-12, 3,244 daily observations

## Method

- Return: adjusted daily close-to-close simple return
- Drawdown: compounded wealth path, `wealth / wealth.cummax() - 1`
- Frequency: share of days with drawdown below zero
- Depth: average absolute drawdown conditional on being underwater
- Burden: frequency times conditional depth
- Statistical test: non-overlapping 21-trading-day paired Wilcoxon tests versus SPY
- Multiple testing: Bonferroni correction across 4 factors x 2 metrics
- Trend overlay: MA200 signal with explicit `signal.shift(1)`, cash return 0, 5 bps transaction cost on signal changes

## Reproduce

```bash
uv run python experiments/experiment_defensive_factor_drawdown_decomposition_2026_06_14/experiment_defensive_factor_drawdown_decomposition_2026_06_14.py
```

## Files

- `experiment_defensive_factor_drawdown_decomposition_2026_06_14.py`
- `experiment_defensive_factor_drawdown_decomposition_2026_06_14_results.json`
- `fig_drawdown_decomposition_bars.png`
- `fig_wealth_drawdown_paths.png`
- `fig_trend_overlay_effect.png`

## Results

### Full-sample drawdown decomposition

| ETF | Ann ret % | Ann vol % | MDD % | Underwater days % | Avg underwater depth % | Burden % |
|---|---:|---:|---:|---:|---:|---:|
| SPY | 14.08 | 17.02 | -33.72 | 84.3 | 4.51 | 3.81 |
| USMV | 10.47 | 13.80 | -33.10 | 86.9 | 3.56 | 3.09 |
| SPLV | 8.96 | 14.73 | -36.26 | 89.7 | 4.30 | 3.86 |
| QUAL | 13.74 | 17.15 | -34.06 | 85.8 | 4.78 | 4.10 |
| VLUE | 13.23 | 18.71 | -39.47 | 89.7 | 6.84 | 6.13 |

### Paired block tests versus SPY

Bonferroni alpha is 0.00625 across 4 factors x 2 primary metrics.

- `USMV`: conditional depth is significantly lower than SPY (`p=0.00022`), but underwater frequency is not lower.
- `SPLV`: no Bonferroni-pass protection versus SPY.
- `QUAL`: no Bonferroni-pass protection versus SPY.
- `VLUE`: no Bonferroni-pass protection versus SPY.

## Verdict

`USMV` is the only ETF in this set with statistically supported defensive protection versus SPY, and the channel is **depth**, not frequency.

This distinction matters: USMV spent slightly more days underwater than SPY, but those drawdowns were shallower on average, reducing the drawdown burden by about 18.7%. `SPLV`, `QUAL`, and `VLUE` do not show robust drawdown protection versus SPY in this common sample.

## Trend Overlay

The MA200 overlay uses `signal.shift(1)` and 5 bps transaction cost on signal changes.

- The overlay reduces max drawdown for all five ETFs in the same-sample comparison.
- It does not uniformly reduce drawdown burden; for several ETFs it increases the frequency of shallow underwater periods.
- Interpretation: trend following is complementary for tail depth / MDD control, but it is not a free improvement on every drawdown dimension.

## Honest Limits

- ETF-level evidence only; this is not a stock-level factor-premium replication.
- The common ETF sample begins in 2013, so it misses 2000-2002 and 2008 crisis behavior.
- Drawdown metrics are path-dependent; block tests are paired diagnostics, not a structural causal model.
- The trend overlay uses zero cash return for simplicity, so it should not be treated as a production strategy backtest.
