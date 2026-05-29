# K1324: 台灣 5-min 數據 HAR-RV（0050.TW 80-day continuation）

**Date:** 2026-05-29  
**Status:** COMPLETE  
**Verdict:** `UNTRUSTWORTHY_SMALL_SAMPLE`

## 問題

`research_program.md` 的原始待辦寫法是：

> 台灣 5-min 數據 HAR-RV（0050.TW 47 天，ETA 2026 Q2）

到 `K1322` 為止，這條線已經不是 47 天，而是：

- 0050.TW 5-min 日 RV 樣本 `76` 天
- HAR warm-up 後 `54` 列
- 70/30 chronological OOS 只有 `17` 天

`K1324` 的角色是接續 `K1322`，用最新累積到 `2026-05-28` 的資料重跑相同規格，回答：

1. 樣本是否已脫離極端 under-powered 區間？
2. `K1322` 的方向性結果是否穩定？

## 方法

完全沿用 `K1322` 已經通過 Codex review 的主規格：

- 來源：`data/intraday/0050_TW_5min_*.csv`
- 先從 raw 5-min bars **重建 daily RV**
- 丟掉 `volume == 0` 的 pre-open / non-traded bars
- HAR-RV 特徵：
  - `log(RV_{t-1})`
  - `log(mean(RV_{t-5..t-1}))`
  - `log(mean(RV_{t-22..t-1}))`
- target：`log(RV_t)`
- split：70/30 chronological
- baseline：Random Walk = `log(RV_{t-1})`
- loss：QLIKE on RV level
- test：DM with Newey-West HAC + HLN correction

Lookahead 規範不變：

- 所有 HAR 特徵都建立在 `rv.shift(1)` 上
- rolling windows 也作用在 lagged series 上
- 沒有同日 RV 洩漏到 predictor

## 主要結果

### 樣本進度

- raw 5-min files：`80` 天
- effective HAR rows after 22d warm-up：`58`
- train / test = `40 / 18`

和 `K1322` 相比，只多了：

- total days: `+4`
- OOS test days: `+1`

### HAR-RV vs Random Walk

- HAR QLIKE = `0.353`
- RW QLIKE = `0.536`
- HAR OOS R² = `-0.140`
- RW OOS R² = `-0.763`
- DM-HLN t = `0.99`
- p = `0.329`

方向上 HAR-RV 仍優於 Random Walk，但統計證據依然很弱，完全沒到 Harvey `|t| > 3`。

## 為什麼 K1324 有價值

最值得記錄的不是「HAR-RV 很好」或「HAR-RV 不行」，而是：

> **只增加 4 個新交易日，DM-HLN t-stat 就從 K1322 的約 1.82 掉到 0.99。**

這代表目前樣本仍處於非常高噪音區：

- model ranking 在 raw QLIKE 上看起來有差
- 但 test statistic 對新增幾天極度敏感
- 任何強宣稱都不可靠

這反而強化了 `K1307` 的 readiness logic：

- 這條線可以持續跑
- 但還沒有到能寫正式研究結論的點

## 結論

1. `0050.TW` 5-min HAR-RV pipeline 現在是**可重跑、可續積累**的
2. 80 天樣本下，HAR-RV 對 Random Walk 仍是**方向正確但統計無力**
3. `K1322 -> K1324` 的 t-stat 大幅擺動，證明目前仍在 small-sample fragility regime
4. 因此最誠實 verdict 仍是：

> **UNTRUSTWORTHY_SMALL_SAMPLE**

## Revisit Gate

建議至少滿足其中兩個條件再升級成正式實驗：

- `n_total_days >= 200`
- `n_test >= 50`

在那之前，這條線適合作為 methodology checkpoint，不適合作為 publishable claim。

## 產物

- `k1324.py`
- `k1324_results.json`
- `k1324_rv_forecasts.png`
- `data/0050_tw_daily_rv_rebuilt.csv`
