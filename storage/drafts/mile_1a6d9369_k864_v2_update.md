---
description: "K864-v2 重跑後，分散 VT 策略在 primary quadratic herding 模型下仍會放大市場風險；但 linear demand sensitivity 顯示此結論高度依賴群聚放大假設，不能直接外推為一般市場定律。"
---

# 分散策略不一定救得了市場：波動率目標的模型陷阱

*2026-06-14 修訂：本文已依 Codex source-code review 重跑 K864-v2。新版本修正 rolling crash 口徑、price clamp、noise trader demand、common-random-number paired tests，並新增 linear-demand sensitivity 與 per-type performance。本文所有數字改用 `experiments/k864/k864_results.json` 新版結果。*

---

一個直覺聽起來很合理：如果市場上的投資人使用不同版本的波動率目標策略，彼此調倉時間不同，群聚風險應該下降。

K864-v2 給出的答案比較精確：**在 K827v3 沿用的 quadratic herding 模型裡，分散策略沒有降低市場風險，反而放大了風險；但在線性 demand sensitivity 裡，這個效果幾乎消失。**

所以這不是「分散策略永遠沒用」的實證結論，而是一個模型警訊：如果市場衝擊會隨採用人數非線性放大，策略多樣化未必能抵銷群聚風險。

---

## 實驗設計

K864-v2 是代理人模擬，不是真實市場回測。設定如下：

| 項目 | 設定 |
|---|---|
| 代理人數 | 1000 |
| 噪音交易者 | 固定 200 |
| 模擬長度 | 2520 交易日，約 10 年 |
| Monte Carlo | 每組 200 次 |
| VT 採用率 | 0%, 10%, 20%, 30%, 50%, 70%, 100% |
| Primary demand | quadratic，沿用 K827v3 herding amplification |
| Sensitivity | linear demand，同樣 seed 重跑 |
| Crash 定義 | rolling t-1 22 日波動率，`r_t < -3 * sigma_{t-1}` |

異質型 VT 代理人平均分成四類：

| 類型 | 規則 |
|---|---|
| A | 12/VIX 標準版 |
| B | 12/VIX 加 30% floor 與 90% cap |
| C | 風險平價，目標 10% 波動率 |
| D | EWMA(22) 目標波動率 |

---

## Primary 結果：quadratic herding 下更脆弱

在 primary quadratic demand 模型下，異質型市場的風險明顯高於同質型。

**表1：50% 採用率，quadratic demand**

| 指標 | 同質型 | 異質型 | 變化 |
|---|---:|---:|---:|
| rolling crash 頻率 | 0.756 次/年 | 5.563 次/年 | +636% |
| 固定 -5% crash 頻率 | 0.044 次/年 | 4.015 次/年 | +9126% |
| 年化市場波動率 | 19.0% | 29.0% | +52.2% |
| 最大回撤 | -41.1% | -53.6% | 惡化 12.5 個百分點 |
| VT aggregate Sharpe | 0.313 | 0.419 | +33.7% |

![K864-v2 rolling crash frequency](storage/reports/assets/k864_v2/k864_v2_flash_crash.png)

70% 採用率時，差距更大：rolling crash 頻率從 0.797 次/年升到 9.020 次/年，市場年化波動率從 23.6% 升到 51.8%，最大回撤從 -64.7% 惡化到 -84.4%。

這裡的悖論仍然存在：市場更脆弱，但 VT aggregate Sharpe 變高。50% 採用率下，aggregate Sharpe 從 0.313 升到 0.419；70% 採用率下，從 0.083 升到 0.375。

但舊版文章把這點解讀成個體層級全面改善是不精確的。K864-v2 補上 per-type performance 後，50% 採用率下各類型差異很大：

| 類型 | Sharpe |
|---|---:|
| A 12/VIX | -0.245 |
| B Floor/Cap | -0.170 |
| C Risk Parity | 0.773 |
| D EWMA | 1.173 |

也就是說，aggregate 改善主要來自 C/D 類型的組合效果，不代表每一類 agent 都變好。

---

## Sensitivity：linear demand 下結果消失

最重要的修訂是 linear demand sensitivity。若把每個 agent 的 demand impact 改成線性加總，而不是 K827v3 的 quadratic herding amplification，異質型與同質型幾乎沒有市場層級差異。

**表2：50% 採用率，linear demand sensitivity**

| 指標 | 同質型 | 異質型 | 變化 |
|---|---:|---:|---:|
| rolling crash 頻率 | 0.987 次/年 | 0.987 次/年 | -0.05% |
| 年化市場波動率 | 16.008% | 16.008% | 約 0 |
| 最大回撤 | -33.25% | -33.25% | 約 0 |
| VT aggregate Sharpe | 0.474 | 0.472 | -0.3% |

![K864-v2 demand sensitivity](storage/reports/assets/k864_v2/k864_v2_demand_sensitivity.png)

這表示本文的正確解讀不是「策略分散一定有害」，而是：

> 當市場衝擊隨採用人數非線性放大時，策略多樣化無法保證降低系統風險；若衝擊只是線性加總，K864-v2 找不到同樣的惡化效果。

---

## 機制修訂：不是已證明的 A→C→D 連鎖

舊版文章用明確的 A/C/D lead-lag cascade 解釋結果。K864-v2 加入 per-type flow diagnostics 後，這個敘事不能保留為結論。

50% 採用率下，A 類 sell flow 對 C/D 類未來 1-5 日 sell flow 的平均 lag correlation 是小幅負值；C 與 D 則主要是同日相關，lag 0 correlation 約 0.80。這不支持「A 明確領先，C/D 延後接力」的簡單 cascade 版本。

較保守的解釋是：primary 模型裡的 quadratic demand amplification 讓不同策略權重變化的總市場衝擊被非線性放大；同時 C/D 類策略在個體組合上表現較好，讓 aggregate VT Sharpe 看起來改善。這兩件事可以同時成立。

---

## 對投資人的意涵

K864-v2 不是用來預測真實市場會在某個採用率崩盤。它的用途是提醒我們：評估群聚風險時，不能只問「大家是不是用同一套策略」，還要問「市場衝擊函數是不是非線性的」。

如果流動性足夠深、需求衝擊接近線性，策略多樣化未必造成系統性惡化。若市場處於壓力期、做市能力下降、同方向調倉的價格衝擊開始隨資金規模非線性上升，分散成多個 VT 版本也不一定能救場。

因此本文更新後的結論是：

1. K864-v2 primary quadratic model 仍顯示異質 VT 會放大 crash、波動率與回撤。
2. 這個結果通過 common-random-number paired HLN 檢定與 3-sigma gate，但它是模型內結論。
3. Linear demand sensitivity 幾乎完全否定「異質性本身必然有害」。
4. 舊版 A→C→D cascade 敘事未被新增 flow diagnostics 支持，已撤回。

---

*資料與程式：`experiments/k864/k864_heterogeneous_abm.py`、`experiments/k864/k864_results.json`。本研究為 Monte Carlo ABM simulation，非實證市場資料。*
