# K1325: 台灣 5-min 數據 HAR-RV（0050.TW 82-day continuation）

**Date:** 2026-06-03  
**Status:** COMPLETE  
**Verdict:** `UNTRUSTWORTHY_SMALL_SAMPLE`

## 動機

`research_program.md` 裡的原始待辦仍寫成：

> 台灣 5-min 數據 HAR-RV（0050.TW 47 天，ETA 2026 Q2）

但這條線其實已經歷經 `K1307 -> K1318 -> K1322 -> K1324` 多次續跑。  
`K1325` 的角色不是另換模型，而是把同一條 0050.TW 5-min HAR-RV pipeline 用最新資料再重跑一次，確認：

1. `K1324` 之後多兩個有效交易日，結論有沒有改變？
2. 樣本是否已脫離明顯 under-powered 的區間？
3. 方向性優勢是否仍只停留在 raw score，尚未進入可強宣稱的統計區？

## 方法

完全沿用 `K1324` 已通過審查的主規格：

- 來源：`data/intraday/0050_TW_5min_*.csv`
- 先從 raw 5-min bars 重建 daily realized variance
- 丟掉 `volume == 0` 的非成交 bar
- HAR-RV 特徵：
  - `log(RV_{t-1})`
  - `log(mean(RV_{t-5..t-1}))`
  - `log(mean(RV_{t-22..t-1}))`
- target：`log(RV_t)`
- split：70/30 chronological
- baseline：Random Walk = `log(RV_{t-1})`
- loss：QLIKE on RV level
- test：Newey-West HAC DM + HLN small-sample correction

## Lookahead 防呆

- `rv_d = rv.shift(1)`
- `rv_w`、`rv_m` 都建立在 shifted series 上
- target 是 `log(RV_t)`，沒有 contemporaneous RV 洩漏到 predictors
- chronological split，不做 shuffle
- random seed 固定為 `42`

## 結果摘要

- raw 5-min files：`82` 天
- effective HAR rows after 22d warm-up：`60`
- train / test = `42 / 18`
- HAR QLIKE = `0.265`
- RW QLIKE = `0.375`
- DM-HLN t = `0.88`
- p = `0.390`

和 `K1324` 相比：

- total days: `+2`
- effective HAR rows: `+2`
- OOS test days: `0`（70/30 split 下仍維持 18 天）
- DM-HLN t: `0.99 -> 0.88`

方向上 HAR-RV 仍優於 Random Walk，但證據強度幾乎沒有變，依然遠低於 Harvey `|t| > 3`。

## 結論

1. 0050.TW 5-min HAR-RV pipeline 仍然可重跑、可延續、無 lookahead。
2. 新增兩個有效交易日後，方向性優勢還在，但統計證據沒有實質升級。
3. 這條線目前最誠實的結論仍是：

> **UNTRUSTWORTHY_SMALL_SAMPLE**

## Revisit Gate（2026-08-02 重新校準）

原本的條件是 `n_total_days >= 200` 或 `n_test >= 50`。這兩個數字沒有推導來源，
而且 K1325 自己的結果就證明它們訂得太鬆：DM-HLN `t = 0.883 @ n_test = 18`，
t 大致隨 `sqrt(n_test)` 成長，`n_test = 50` 只推到 `|t| ≈ 1.47`，距離專案的
Harvey `|t| > 3` 及格線還很遠。舊 gate 一旦觸發，只會再產出一份一模一樣的
「不足以下結論」判決。公開文章 `mile_3445217e` 已對讀者承認這件事並承諾修正。

**新條件不是另一個寫死的數字，而是由觀察到的效果量推導出來的**：

| 項目 | 值 |
|---|---|
| 需要的測試天數 | **208**（`n_test × (3 / 0.883)²`） |
| 換算原始交易日 | **716**（`ceil(208 / 0.3) + 22` 天 HAR 暖身） |
| 目前（k1325 當時） | 82 天原始 / 18 測試日 → 還差 634 個交易日 ≈ 2.5 年 |
| 判決 | **`DESIGN_CHANGE_REQUIRED`** |

因為缺口超過 2 年的等待上限（`max_wait_trading_days = 504`），正確的行動不是排一個
「以後回來再跑」的檢查點，而是**改設計**：跨資產 pooling、買更長的歷史資料，或換到
效果量更大的頻率。單純等資料不再是計畫。

需要留意的誠實但難看的一點：`t = 0.883` 本身是從 18 個測試日估出來的，t 統計量的
標準誤約為 1，所以「需要 208 天」這個數字自己的不確定性就有一個數量級
（樂觀端 21 天，悲觀端無上界）。gate 的決策採點估計，但 `required_test_days_ci`
會把這個帶寬明寫出來，避免有人把 208 當成承諾。

**Owner / 產生方式**（不要手改）：

- 政策：`config/revisit_gates.json`（pipeline `tw50_5min_har_rv`）
- 算術：`src/volpred/research/revisit_gate.py`
- 現行判決：`experiments/k1325/revisit_gate.json`，由
  `uv run python scripts/eval_revisit_gate.py --pipeline tw50_5min_har_rv --write` 產生
- 同一條 pipeline 的 `k1307` / `K1322` / `k1324` / `k1325` 腳本都已改成向上面取值，
  不再各自寫死門檻（K1307 原本另外寫死 `POWERED_OOS_TARGET = 252`，同樣過鬆）

`k1325_results.json` 裡的 `revisit_gate` 區塊仍記著舊的 200/50 —— 它是 2026-06 那次
執行留下的產物，不做事後改寫（改資料不改流程正是要避免的事）。現行判決以
`revisit_gate.json` 為準。

## 產物

- `k1325.py`
- `k1325_results.json`
- `revisit_gate.json`（generated；現行 revisit 判決）
- `k1325_rv_forecasts.png`
- `data/0050_tw_daily_rv_rebuilt.csv`
