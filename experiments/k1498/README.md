# K1498 - Option-Liquidity Crash-Risk Proxy Without Option Microstructure

## 問題

`research_crash_risk` 來自 `research_program.md` 的 open backlog：

> 期權市場流動性作股價 crash-risk 的免期權代理 - yfinance 用 SPY 量/價差代理（Amihud、range-volume）與 `^VIX` skew proxy 建 option-illiquidity proxy，檢定流動性惡化日是否領先次日/次週極端負報酬與 RV 跳升，明確 lag。

這題不能直接宣稱測到真實 option liquidity，因為 repo 沒有 OptionMetrics / TAQ / OPRA 類微觀資料。本實驗做的是可驗證的低頻 proxy 版本。

## 動機與差異化

- `K1472` 已測過低頻 illiquidity 對一般 HAR vol forecast 的增量，結論偏弱。
- 本題改問 crash-risk 左尾：`SPY` 的 liquidity stress 是否領先極端負報酬或 realized variance jump。
- 文獻上 option liquidity / market illiquidity 與 crash risk 的關係強，但正式研究多用 option 或高頻 spread；本實驗刻意測「免費低頻代理」能否保留足夠訊號。

## 文獻脈絡

1. Deng, Nguyen, Gebka (2026), *Option market liquidity and stock price crash risk*, European Journal of Finance: equity option liquidity increases future stock price crash risk.
2. Christoffersen, Feunou, Jeon, Ornthanalai (2021), *Time-Varying Crash Risk Embedded in Index Options: The Role of Stock Market Liquidity*, Review of Finance: market illiquidity helps explain option-implied crash risk beyond spot variance.
3. Chang, Chen, Zolotoy (2017/2016 SSRN), *Stock Liquidity and Stock Price Crash Risk*, JFQA: stock liquidity can increase future crash risk through bad-news-hoarding / transient-investor channels.
4. Amihud (2002) and Corwin-Schultz (2012): low-frequency liquidity and bid-ask spread proxies used when microstructure data is unavailable.

## 資料

- `SPY` OHLCV and `^VIX`: `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv`
- `^SKEW` and `^VVIX`: yfinance download cached under `experiments/k1498/data/`
- Effective sample after joins and rolling feature construction: 2013 onward.
- Seed: `42`

## Proxy construction

All raw signals are computed at close of day `t`, then explicitly shifted:

```python
signal = raw_signal.shift(1)
```

Predictors:

- `amihud_z`: rolling 252-day z-score of `|r| / dollar_volume`
- `cs_spread_z`: rolling 252-day z-score of Corwin-Schultz spread
- `range_volume_z`: rolling 252-day z-score of intraday range adjusted by volume
- `vix_z`, `skew_z`, `vvix_z`: rolling 252-day z-scores
- `stock_liquidity_stress`: average of `amihud_z`, `cs_spread_z`, `range_volume_z`
- `option_tail_stress`: average of `skew_z`, `vvix_z`
- `option_liquidity_proxy`: average of `stock_liquidity_stress`, `option_tail_stress`

## Targets

Targets are indexed at day `t`; predictors are lagged to `t-1`.

- `crash_1d`: `SPY` return on `t` is below the rolling 5% quantile estimated through `t-1`
- `crash_5d`: cumulative return over `t..t+4` is below the prior rolling 5% quantile of 5-day returns
- `rv_jump_1d`: `r_t^2` exceeds the prior rolling 95% quantile
- `rv_jump_5d`: 5-day realized variance exceeds the prior rolling 95% quantile

## Evaluation

OOS starts at `2021-01-04`.

For each target:

1. Fit baseline logistic model with `vix_z`, `rv22_z`, `momentum22`.
2. Fit augmented models adding:
   - `stock_liquidity_stress`
   - `option_tail_stress`
   - `option_liquidity_proxy`
3. Compare OOS AUC, Brier score, and log-likelihood.
4. Run LR test versus baseline and Bonferroni-adjust across 4 targets x 3 augmentations.
5. Report top-decile signal event-rate lift with moving-block bootstrap (`B=1000`, block=21).

## Success criteria

The proxy only supports the backlog claim if it:

- improves OOS AUC and Brier versus baseline;
- passes LR test after Bonferroni correction;
- shows economically meaningful top-decile event-rate lift;
- survives for crash targets, not only generic RV jump targets.

## Main result

Verdict: **NULL**.

The baseline model already classifies the left-tail / RV-jump targets well using only lagged VIX, realized variance, and momentum controls:

| Target | Baseline AUC | Combined proxy AUC | Direction |
|--------|--------------|--------------------|-----------|
| `crash_1d` | 0.754 | 0.735 | worse |
| `crash_5d` | 0.759 | 0.685 | worse |
| `rv_jump_1d` | 0.791 | 0.781 | worse |
| `rv_jump_5d` | 0.873 | 0.866 | worse |

`stock_liquidity_stress` alone gives tiny AUC gains for `crash_1d`, `rv_jump_1d`, and `rv_jump_5d` (roughly +0.002 to +0.003), but all train-sample nested LR tests fail the 12-test Bonferroni bar. The combined low-frequency option-liquidity proxy therefore does **not** provide robust OOS crash-risk improvement over the simpler VIX/vol/momentum baseline.

## Limitations

- This is not direct option-market liquidity.
- `^SKEW` and `^VVIX` are index-level implied-risk proxies, not spread/depth measures.
- Daily OHLCV proxies can miss intraday liquidity collapses.
- Crash events are rare, so effect sizes and confidence intervals matter more than one p-value.
