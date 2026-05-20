---
title: VIX 期限結構真的能預測波動率嗎？K489 用 6 個 horizon 給出誠實答案
audience: general
status: draft
tags:
  - VIX
  - 期限結構
  - VIX9D
  - VIX3M
  - implied-volatility
  - mixed-result
  - 研究誠實
experiment_refs:
  - K489
---

# VIX 期限結構真的能預測波動率嗎？K489 用 6 個 horizon 給出誠實答案

> **K489 一句話**：matched-tenor IV 在「短期 5 天」horizon 顯著贏過慣性基準，21 天和 63 天**沒贏**；期限結構斜率對「波動率方向」有預測力，但**對 magnitude 的增量貢獻很小**（+0.013 到 +0.026 R²）。所謂「VIX 是波動率預測王道」這句話，要看你預測的是哪個 horizon。

## 為什麼這個問題重要

打開任何選擇權交易平台，期限結構（term structure）是交易員每天看的訊號。VIX9D（9 天）、VIX（30 天）、VIX3M（90 天）三條曲線排起來：

- **正向（contango）**：長天期 IV > 短天期 IV — 平靜時期，市場預期遠期不確定性較高
- **逆向（backwardation）**：短天期 IV > 長天期 IV — 危機警報，市場預期短期內會非常動盪

學術上 Carr & Wu (2006)、Mixon (2007, JFE) 早就用期限結構建立過 implied volatility 與 realized volatility 的橋梁。但**真的拿來預測 realized vol，跨多個 horizon、做嚴格 out-of-sample 比較，結果到底有多好？**

K489 用 SPY + ^VIX9D + ^VIX + ^VIX3M 從 2011-01-03 到 2026-03-25 共 3,829 天，IS 期間 2011–2022（n=3,020），OOS 期間 2023-01-03 ~ 2026-03-25（n=809），測 6 種 IV-tenor × RV-horizon 組合 + term structure 斜率方向預測 + variance risk premium。

## K489 是怎麼設計的

**Realized Volatility 定義**：對未來 h 天的對數報酬，
$$RV_h(t) = \sqrt{\frac{252}{h} \sum_{k=1}^{h} r_{t+k}^2}$$
所以 t 時點觀察 IV[t]，預測的是**接下來 h 天**累積的 RV — 沒有 lookahead，baseline lag persistence 用 `RV_h(t-h)`（同 horizon 的非重疊歷史值），保證公平。

**Part A — Matched tenor**（最直觀）：把 IV 期限對到 RV horizon
- VIX9D (9d) → RV(5d)
- VIX (30d) → RV(21d)
- VIX3M (90d) → RV(63d)

**Part B — Cross tenor**：3 × 3 全配對，看哪個 IV 對哪個 RV 預測最好

**Part C — Direction prediction**：用斜率（90d−9d）+ ratio（90d/9d）+ IV level 預測 `RV(t+h) > RV(t)` 二分類

**Part D — Conditional RV**：把交易日依斜率分 5 組（strong contango 到 strong backwardation），看條件均值

**Part F — Variance Risk Premium**：VRP = IV − RV 的時序統計與作為預測變數的能力

## 真實結果：好但局部，不全面

### 結果一：matched tenor 只有 5 天 horizon 顯著贏 lag persistence

![圖 1：三 horizon 的 OOS R² 比較](/experiments/k489/fig1_matched_tenor_r2.png)

| Horizon | Lag persistence R² | IV only R² | IV+Lag+TS R² | DM 檢定 (IV vs lag) |
|---|---:|---:|---:|---|
| VIX9D → RV(5天) | 0.156 | **0.413** | **0.422** | t=−2.47, p=0.014 ✓ |
| VIX → RV(21天) | 0.056 | 0.207 | 0.234 | t=−1.36, p=0.175 |
| VIX3M → RV(63天) | −0.165 | −0.021 | 0.025 | t=−1.15, p=0.249 |

**讀法**：5 天 horizon 上 IV 對 lag persistence 的兩模型比較檢定統計強度 −2.47（達顯著水準（顯著性 0.014）），**統計顯著贏過慣性**。21 天 / 63 天的 R² 雖然 IV 數值較高，但比較檢定沒能拒絕「兩者預測精度相同」的虛無假設 — 也就是**樣本上 IV 沒有顯著贏 lag persistence**。

對 63 天 horizon 來說，連慣性基準本身的 OOS R² 都已經是負的（−0.165），意味著「用上一個 63 天的 RV 預測下一個 63 天的 RV」在這個 OOS 期間連 unconditional 平均值都沒贏。模型架構在這個 horizon 是真的難。

### 結果二：cross-tenor 確認「短天期 IV 預測短天期 RV」最強

![圖 2：所有 IV-tenor × RV-horizon 組合的 R² heatmap](/experiments/k489/fig2_cross_tenor_heatmap.png)

3 × 3 heatmap 對角線（matched tenor）並非總是最高 R²；而是**最短的 VIX9D 在所有 horizon 都最強或接近最強**：

- VIX9D → RV(5d)：R² = **0.413**（全表最高）
- VIX9D → RV(21d)：R² = 0.227（贏 VIX→RV(21d) 的 0.207）
- VIX9D → RV(63d)：R² = 0.004（贏 VIX3M→RV(63d) 的 −0.021）

意思是：**最即時的 implied volatility 訊號（VIX9D）反而是跨 horizon 最有用的單一變數**，這跟「matched tenor 才最好」的直覺不太一樣。文獻 Carr & Wu (2006) 提到的 IV horizon 嵌套結構在這裡有部分支持。

### 結果三：term structure 的增量貢獻 modest（+0.013 ~ +0.026 R²）

把 IV+Lag 模型加上斜率（slope）和比值（ratio）這兩個 term structure 形狀變數後：

| Horizon | R² without TS | R² with TS | 增量 |
|---|---:|---:|---:|
| VIX9D → RV(5天) | 0.408 | 0.422 | **+0.0135** |
| VIX → RV(21天) | 0.208 | 0.234 | **+0.0259** |
| VIX3M → RV(63天) | 0.003 | 0.025 | **+0.0223** |

斜率與比值有貢獻，但**幅度不大**。一句話總結：term structure 是 nice-to-have，不是 game-changer。

### 結果四：方向預測顯著 ≠ magnitude 預測精準

Part C 的方向預測（`RV(t+h) > RV(t)` 二分類）OLS 模型 OOS 準確率：

- 5 天：55.3%（base rate 49.9%，提升 +5.4 pp）
- 21 天：61.3%（base rate 48.0%，提升 +13.3 pp）
- 63 天：48.6%（沒贏 base rate）

**21 天 horizon 的方向預測非常顯著**（z-test 拒絕 50%）。但這不能直接讀成「IV 對 21 天 magnitude 預測也好」— 從結果一可以看到，21 天的 magnitude 比較檢定顯著性 0.175，**不顯著**。

這是個非常重要的區分：**「能不能預測接下來會變高還是變低」是一個問題；「能不能預測會高多少」是另一個問題**。term structure 對前者較有貢獻；對後者要看 horizon。

### 結果五：斜率分組 — backwardation 真的對應劇烈未來波動

![圖 3：斜率分組 vs 未來 realized vol](/experiments/k489/fig3_slope_regime_rv.png)

把 OOS 樣本按斜率分 5 組，未來 5 天 RV 條件平均：

- Strong Contango（slope > 0.02，n=425）：RV(5d) = **10.4%**
- Mild Contango（0 < slope ≤ 0.02，n=339）：13.7%
- Flat（|slope| ≤ 0.005，n=47）：20.2%
- Mild Backwardation（−0.02 ≤ slope < 0，n=34）：23.9%
- Strong Backwardation（slope < −0.02，n=10）：**46.2%**

contango vs backwardation 的 t-test：t=−15.24，p ≈ 3.2 × 10⁻⁴⁶（5 天）／t=−12.31，p ≈ 5.9 × 10⁻³² （21 天）— **超強顯著**。但要注意 backwardation 樣本只有 42 天（5d horizon），效應「真實但稀有」，不能拿來當高頻訊號。

## 誠實討論：哪些話不能說

K489 結果是經典的 **mixed result** — 為了維持研究誠實原則，下面幾句話**不能說**：

1. ❌「VIX 是波動率預測的王道」— 只在 5 天 horizon 顯著贏 baseline，21/63 天沒贏
2. ❌「期限結構提供強大的增量預測力」— 增量 R² 0.013–0.026，是 modest 不是 strong
3. ❌「斜率能用來方向擇時」— 21 天方向準確率提升 13 pp 是亮點，但 5/63 天沒到那麼好；且要區分方向 vs magnitude
4. ❌「VIX3M 是長 horizon 預測首選」— heatmap 顯示反而是 VIX9D 在所有 horizon 都最強

可以說：

1. ✅ **短期 vol（5 天）預測**：IV 顯著贏 lag persistence（比較檢定顯著性 0.014），實務上有用
2. ✅ **斜率對波動率方向有預測力**（21 天 horizon 最強，提升 13 pp）
3. ✅ **VIX9D 是跨 horizon 最有用的單一 IV 訊號**（cross-tenor heatmap 對角線不是最高的）
4. ✅ **Term structure 形狀有條件均值差異**（contango vs backwardation 的 t=15.24 高度顯著）

## 下一步

K489 留下兩個自然延伸：

- **Regime-conditional**：把斜率與 IV level 結合，建構 regime-switching 預測模型，看是不是 backwardation 期間 IV 預測力會被放大
- **Cross-asset**：VIX 期限結構對股票 RV 之外的資產（金、原油、利率）的 spillover 效應

學術 framing 上，K489 跟 K429（VIX 斜率對下一日 vol 的 null result）形成互補：K429 說「斜率預測下一日 vol 沒用」，K489 說「斜率預測下一個月方向有用，但 magnitude 增量有限」。兩個結果都對 — 因為它們問的是不同的問題。

**這就是為什麼我們需要跨 6 個 horizon 全面測試 — 不然單看一個 horizon 很容易過度宣稱或誤判。**

---

*資料來源：yfinance（^VIX9D / ^VIX / ^VIX3M / SPY），2011-01-03 ~ 2026-03-25，n=3,829 個交易日。*
*實驗代碼：`experiments/k489/k489_vix_term_structure.py`*
*原始結果：`experiments/k489/k489_vix_term_structure_results.json`*
*參考：Carr & Wu (2006) — A Tale of Two Indices；Mixon (2007) — Implied Volatility Term Structure, JFE；Johnson (2017) — VIX Term Structure as Predictor, SSRN；K429（先前 VIX slope null result）。*
