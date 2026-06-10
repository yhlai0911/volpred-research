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

## Code Review 記錄（2026-06-10）

**Reviewer**: Codex CLI (`codex exec`, gpt-5.4) — primary path。

**v1 verdict: FAIL**（NULL 結論本身保守且成立，但兩個方法論缺陷）：
1. `share_overnight_252` 的 `rolling(252)` 沒有 `.shift(1)` — share 在 t 日含當日平方報酬，與 README 宣稱的 past-only 矛盾（同日污染，非未來 lookahead）。
2. Baseline VRP 用 trailing 22d RV（×252 年化）對 `(VIX/100)^2`（~30 曆日 forward 風險中性）— 方向/horizon mismatch 未處理、結論未承認 proxy-dependence。

**v2 修正**（主線程，commit 同日）：
1. share split 加 `.shift(1)`（嚴格 ex-ante）。
2. 新增 `sensitivity_horizon_matched`：BTZ 式 ex-post premium `IV_t − RV_{t+1..t+22}`（horizon-matched；只用於 mean sign test，絕不作 signal）。
3. methodology 加 `horizon_mismatch_note`；conclusion 加 proxy-dependence caveat。

**v2 重跑結果**：verdict 維持 **NULL** 且更穩健 — baseline 與 horizon-matched 兩個版本的 overnight VRP 平均都是**正**（baseline mean=0.0025, HAC t=+2.85；HM mean=0.0025, t=+1.49），「隔夜負」前提在此 proxy 下不成立；intraday 為正且顯著（兩版本一致）。反號故事 NULL 與 proxy 選擇無關。
