# k501

- Experiment ID: `k501`
- Status: retry_completed_locally
- Last updated: 2026-06-07

## 問題描述

重做「美股昨晚的資訊，能不能預測並交易今天台股」這個問題，修正前版 K501 的四個結構問題：

1. `target` 與文章敘事差一天。
2. `0050.TW` 未清洗，出現 `-138.9%` 極端值。
3. 把不可交易的 close-to-close gap alpha 直接當成策略 Sharpe。
4. 錯把不存在於本地 canonical artifact 的 `I8 3.09 → 0.87` 當成 provenance。

## Retry 設計

- 資料來源：本地 `data/cache/price_cache.db`
- 可用 ticker：`SPY`, `QQQ`, `0050.TW`, `^VIX`, `TLT`
- 期間：`2016-01-04` 至 `2026-06-05`
- OOS 起點：`2020-01-02`
- 台股成本：往返 `0.001855`（18.55bp）

### 兩條分析線

1. **Non-tradable info channel**
   - 問題：`SPY` 前一晚收盤資訊是否能解釋 `0050.TW` **同日 close-to-close** 報酬？
   - 用途：驗證資訊傳遞是否存在
   - 限制：包含 overnight gap，不能直接當作可交易策略

2. **Tradable open-to-close channel**
   - 問題：`SPY` 前一晚收盤資訊是否能在台股 **開盤買入後** 產生可交易的同日 open-to-close alpha？
   - 用途：回答真正能不能下單賺錢
   - 規則：long/cash，於台股開盤調倉，扣 18.55bp 成本

## Provenance 更正

- 舊文章引用的 `I8 3.09 → 0.87` 在目前 repo **找不到對應 canonical local artifact**。
- Retry 改用 `experiments/k521/k521_2day_momentum_check_results.json` 補 timing-bias provenance：
  - `gap_sharpe = 5.644`
  - `intraday_sharpe = 0.453`
  - `c2c_sharpe = 4.225`
  - `conclusion = "100% of alpha is in overnight gap; intraday has near-zero signal"`

## 產物

- `k501_return_prediction.py`：離線可重現 retry 主程式
- `k501_return_prediction_results.json`：retry 結果

## Retry 結果摘要

- 非交易資訊線（TW same-day close-to-close）最佳模型 `ridge`
  - OOS R² = `8.10%`
  - hit rate = `58.25%`
- 可交易盤中線（TW same-day open-to-close）最佳模型 `ssvs_ols`
  - OOS R² = `2.51%`
  - net Sharpe = `-0.933`
  - 年化報酬 = `-9.84%`
- 結論：美股前一晚資訊對台股 **收盤到收盤** 有可觀察的資訊傳遞，但把它限制到 **台股開盤後才能執行** 的盤中交易後，alpha 轉為負值，不能再用舊版 `5.66` Sharpe 當 headline。

## 注意

- Retry 樣本比原版短，因為本地 `SPY/QQQ/TLT` cache 自 `2016-01-04` 才開始。
- 這不是原版結果的輕微修補，而是口徑修正後的重算。
