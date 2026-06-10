# K1452: 隔夜 vs 日內 Variance Risk Premium 反號之謎

## 問題

`research_program.md` 的 backlog 指向一個明確問題：如果把 SPY 的 close-to-close 變異數拆成隔夜與日內兩段，variance risk premium（VRP）是否會出現「隔夜負、日內正」的反號結構，且預測力集中在短期 1-3 個月而非長期 6-12 個月？

## 設計

- 資料：`yfinance` 的 `SPY` 與 `^VIX`
- 樣本：`2005-01-01` 到執行當日可得區間
- 隔夜報酬：`log(Open_t / Close_{t-1})`
- 日內報酬：`log(Close_t / Open_t)`
- 22 日 trailing realized variance：
  - `rv_overnight_22 = 252 * mean(overnight_ret^2)`
  - `rv_intraday_22 = 252 * mean(intraday_ret^2)`
- 30 日 implied variance proxy：`(VIX / 100)^2`
- Segment implied variance proxy：
  - 先用 trailing 252 日 realized variance share 拆出隔夜占比與日內占比
  - 再把 `VIX` 總 implied variance 乘上 share，得到 `iv_overnight_proxy`、`iv_intraday_proxy`
- Segment VRP：
  - `vrp_overnight = iv_overnight_proxy - rv_overnight_22`
  - `vrp_intraday = iv_intraday_proxy - rv_intraday_22`
- 預測目標：`t+1` 起算的 forward annualized variance，分別看 22 日與 126 日 horizon

## Primary Tests

固定 6 個 primary tests，並對 6 個 p-value 同時做 Bonferroni 與 BH：

1. `E[vrp_overnight] < 0`（one-sided HAC mean test）
2. `E[vrp_intraday] > 0`（one-sided HAC mean test）
3. `vrp_overnight_t -> fwd overnight RV(22d)`（HAC OLS）
4. `vrp_intraday_t -> fwd intraday RV(22d)`（HAC OLS）
5. `vrp_overnight_t -> fwd overnight RV(126d)`（HAC OLS）
6. `vrp_intraday_t -> fwd intraday RV(126d)`（HAC OLS）

另提供 moving block bootstrap mean CI（`seed=42`）。

## 防錯規則

- 沒有 same-day signal × same-day target：
  - signal 在 `t` 收盤形成
  - forward RV 一律從 `t+1` 開始累積
- rolling variance 都是 trailing window
- bootstrap 固定 `seed=42`
- `yfinance` 下載失敗時重試 3 次後才中止

## 產物

- 主程式：[k1452.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1452/k1452.py)
- 結果 JSON：`k1452_results.json`
- 圖：
  - `figures/segment_vrp_timeseries.png`
  - `figures/segment_vrp_means.png`

## 預期解讀邊界

這個實驗只能回答「在一個 past-only、日頻、VIX-share-based proxy 下，是否看得到 segment VRP sign split 與 horizon split」；它不能直接證明期權市場真的分別對隔夜與日內做獨立定價。若 sign split 存在，也只能說是 reduced-form evidence。
