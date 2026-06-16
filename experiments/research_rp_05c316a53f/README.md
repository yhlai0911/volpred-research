# research_rp_05c316a53f

- Experiment ID: `research_rp_05c316a53f`
- Status: completed
- Created At: 2026-06-17
- Task: 動能因子時序動量的「隔夜 vs 日內」拆解

## Motivation

文獻指出 momentum / anomaly return 可能不是均勻出現在 close-to-close 報酬裡，而是集中在隔夜或日內其中一段。這個實驗用免費 daily OHLC 做可重跑 pilot：同一組 12-1 月 momentum 權重，分別只吃 `close -> open` 與 `open -> close` 報酬，檢查哪一段承擔主要績效。

## Differentiation

本題與既有 overnight/intraday VRP 題不同：這裡不估 variance risk premium，也不預測 RV；只檢查 momentum 策略報酬本身在隔夜與日內的分解。

## Data

- Source: yfinance daily OHLC, `auto_adjust=False`
- Adjusted close: `Adj Close`
- Adjusted open: `Open * Adj Close / Close`
- Universe: `SPY`, `QQQ` + 30 檔大型股長歷史樣本
- Requested period: 2010-01-01 to 2026-06-17

## Method

1. 建立日報酬分解：
   - `overnight_t = log(adj_open_t / adj_close_{t-1})`
   - `intraday_t = log(adj_close_t / adj_open_t)`
2. 月末計算 12-1 月 momentum：
   - `signal_t = log(adj_close.shift(21) / adj_close.shift(252))`
3. 建兩種策略：
   - `TSMOM`: 每檔依自身 signal 正負做多/做空，gross normalized to 1
   - `CSMOM`: cross-section top/bottom 30%，dollar-neutral gross 1
4. 權重 `ffill().shift(1)` 後才乘 day t 的 overnight / intraday return，避免 same-day lookahead。
5. 評估年化平均、波動、Sharpe、偏態、最大回撤、hit rate、strategy DM test、stationary block bootstrap CI。

## Success Criteria

H1「momentum payoff 主要集中於 overnight」要成立，至少要在 stocks-only universe 的 `TSMOM` 與 `CSMOM` 兩個策略上同時看到：

- annualized mean `overnight - intraday > 0`
- strategy DM test Harvey `|t| > 3`
- early/late subperiod 方向一致

否則只報 point estimate 或 NULL。

## Result

Run `uv run python experiments/research_rp_05c316a53f/research_rp_05c316a53f.py` to regenerate:

- `research_rp_05c316a53f_results.json`
- `fig_overnight_intraday_momentum.png`

Main stocks-only results, 2011-02-01 to 2026-06-16 after signal warmup:

| Strategy | Component | Ann. mean | Ann. vol | Sharpe | Max DD |
|---|---:|---:|---:|---:|---:|
| TSMOM 12-1 | overnight | 5.43% | 6.97% | 0.779 | -24.41% |
| TSMOM 12-1 | intraday | 1.03% | 8.25% | 0.125 | -16.17% |
| CSMOM top/bottom 30% | overnight | 5.81% | 5.91% | 0.982 | -10.66% |
| CSMOM top/bottom 30% | intraday | -2.84% | 8.14% | -0.349 | -47.27% |

Primary comparison:

- TSMOM: overnight - intraday annualized mean = +4.39%; DM t=-1.52, p=0.128; bootstrap CI [-1.74%, +9.82%]. Directionally overnight, not Harvey-significant.
- CSMOM: overnight - intraday annualized mean = +8.64%; DM t=-3.32, p=0.0009; bootstrap CI [+3.32%, +14.01%]. Harvey-significant overnight dominance.
- Early and late halves both show overnight > intraday for both strategies.

## Verdict

`CONDITIONAL_PASS`.

The yfinance daily-OHLC pilot supports the literature's overnight-concentration pattern for cross-sectional 12-1M momentum, and directionally for time-series momentum. It is not a full PASS because TSMOM fails the Harvey |t|>3 gate and the universe is current-large-cap / survivorship-biased. No retail-flow mechanism is claimed from this data.
