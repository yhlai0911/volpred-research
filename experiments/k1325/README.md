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

## Revisit Gate

至少滿足以下其中兩項再考慮升級成正式可發表證據：

- `n_total_days >= 200`
- `n_test >= 50`

在那之前，這條線適合作為 methodology checkpoint，不適合作為強結論文章依據。

## 產物

- `k1325.py`
- `k1325_results.json`
- `k1325_rv_forecasts.png`
- `data/0050_tw_daily_rv_rebuilt.csv`
