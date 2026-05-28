---
title: "VT 的 alpha 只是 Sell in May 嗎？K736 的答案是否定的"
audience: general
status: draft
tags:
  - VIX
  - 波動率策略
  - 資產配置
  - 季節性
  - Sell in May
  - 風險管理
experiment_refs:
  - K736
---

# VT 的 alpha 只是 Sell in May 嗎？K736 的答案是否定的

很多人看到波動率切換策略表現不錯，第一個懷疑常常不是模型多厲害，而是：

「這會不會只是剛好吃到 Sell in May 之類的季節性？」

`K736` 就是在處理這個質疑。它不是只比報酬，而是直接拆開看：

- 夏天和冬天的 VIX 真的差很多嗎
- VT 的權重變化是不是其實被月份主導
- 把 calendar effect 拿掉後，VT 的表現還在不在

結果很乾脆：

**VT alpha 不是 calendar anomaly，權重變化幾乎都還是 VIX level 在解釋。**

## 先看季節性本身

![K736 季節性與策略 Sharpe](experiments/k736/k736_general_seasonality_vs_sharpe.png)

先看最容易讓人誤會的地方。K736 的月度 VIX 季節圖顯示：

- 夏季平均 VIX `19.18`
- 冬季平均 VIX `19.77`
- 差距只有 `-0.58`

這個差異在統計上雖然過了 5% 門檻，但經濟意義其實很小。更重要的是，回到投資報酬時，事情就沒那麼像「Sell in May 神話」了。

完整樣本裡：

- `12/VIX` Sharpe `0.806`
- `VT ex-Calendar` Sharpe `0.825`
- `Calendar-Only` Sharpe `0.658`
- `50/50 BH` Sharpe `0.862`

如果 VT alpha 真的只是日曆季節性，你會期待 `Calendar-Only` 很強、拿掉 calendar 後 VT 會明顯變差。但 K736 看到的剛好相反：**純 calendar 版本比較弱，拿掉 calendar 的 VT 反而沒有垮。**

## 真正決定 VT 權重的，幾乎不是月份

![K736 樣本外與權重解釋比例](experiments/k736/k736_general_oos_explainer.png)

K736 最有力的一個數字，不是在 Sharpe 表，而是在權重解釋比例：

- `pct_seasonal = 1.2%`
- `pct_vix_level = 98.8%`

這幾乎把問題講完了。

也就是說，VT 權重的變化裡，真正重要的是 `VIX` 水位，不是「現在是不是 5 月到 10 月」。月份 dummy 幾乎解釋不了什麼。

這和實驗的 partial correlation 也一致。控制月份之後，VT 權重和 VIX 的關係還是非常強，代表訊號核心沒有被季節性吃掉。

## 樣本外也不支持「只是日曆效應」這種說法

K736 還把樣本切成 5 段 cross-OOS：

- `12/VIX` 有 `3/5` 段 Sharpe 勝過 `50/50 BH`
- `Calendar-Only` 只有 `1/5`
- 最近一段 `2022-2025`，`Calendar-Only` Sharpe 只有 `0.704`，明顯落後 `BH` 的 `1.353`

如果這個 alpha 真的主要來自日曆季節性，那純 calendar 規則不該這麼弱。

更直接的是 DM 檢定也沒有給 calendar 版本任何實質優勢：

- `Calendar vs BH` 的差異不顯著
- `12/VIX vs Calendar` 的差異也不顯著
- `VT-exCal vs 12/VIX` 同樣不顯著

這表示日曆因素不是完全不存在，而是它不足以解釋 VT 策略的主要表現來源。

## 這份結果真正重要的地方

K736 最值得留下來的，不是它證明了季節性「完全沒影響」，而是它把影響大小講清楚了：

**有些季節訊號存在，但它們只佔非常小的一部分，遠遠稱不上 VT alpha 的核心來源。**

這比很多表面結論更有價值。因為在投資裡，常見的錯不是把完全沒有的東西看成有，而是把很小的東西誤認成主因。

K736 等於是在說：

**VT 不是因為剛好夏天少做、冬天多做才看起來有效；它主要還是在跟著 VIX 水位調整。**

## 最後一句

K736 最重要的結論不是「Sell in May 完全沒用」，而是：

**VT 的 alpha 不是穿著季節性外套的假訊號，真正驅動它的仍然是波動率本身。**

## 資料來源

本文基於實驗 `K736`（`experiments/k736/`）。資料來源為 `yfinance` 的 `SPY`、`GLD`、`^VIX`，期間 `2006-01-01` 至 `2026-03-29`，共 `5,089` 筆觀測。所有動態策略均採 `signal.shift(1)` 的 `t-1` lag，交易成本 `5 bps`。
