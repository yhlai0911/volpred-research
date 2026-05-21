---
title: "路徑依賴特徵在 5 分鐘 RV 上仍敗給標準 HAR"
audience: general
status: draft
tags: [波動率預測, HAR, 路徑依賴, 高頻數據, 過度配適, 樣本外, 概念驗證]
experiment_refs: [K966]
---

# 路徑依賴特徵在 5 分鐘 RV 上仍敗給標準 HAR：一個 pilot 的誠實報告

## 為什麼會做這個實驗

在波動率預測的世界裡，有一個非常乾淨、結構簡單卻極為強悍的基準模型：HAR-RV（Heterogeneous Autoregressive Realized Volatility，Corsi 2009）。它把昨天、過去一週、過去一個月的已實現波動率（realized variance, RV）線性疊加，僅僅三個解釋變數，卻能在絕大多數市場、多數樣本期間擊敗結構複雜許多的 GARCH 家族。HAR-RV 之所以難以被超越，不是因為它「對」，而是因為它「夠簡單到不會 over-fit」，加上它捕捉了波動率最重要的長記憶結構。

近年 Guyon 與 Lekeufack（2023, arXiv:2503.00851）提出了 path-dependent volatility（PDV）框架，主張波動率「主要由路徑決定」——也就是說，光看歷史 RV 並不夠，過去報酬「怎麼走過來」（路徑）會留下記憶。具體而言他們提出兩個新特徵：

- **R1（趨勢記憶）**：對過去報酬做指數加權（衰減率 λ₁），捕捉趨勢方向的遺留效應
- **R2（波動記憶）**：對過去 |報酬| 做指數加權（衰減率 λ₂），捕捉「最近震盪程度」的延續

這個概念非常吸引人——它呼應了我們對市場的直覺：剛跳過水的人，下一刻心跳還在加速。但問題是：這個機制究竟在實證上能不能擊敗 HAR-RV？

我們在前身實驗 K624 已經測試過：在每日平方報酬（squared return）作為 RV 代理變數的設定下，HAR-PD 比標準 HAR-RV **差 88%**——一個非常響亮的 NULL。當時的合理懷疑是：**日頻 RV 代理太雜訊**，掩蓋了路徑依賴特徵的真實訊號。如果改用高頻 5 分鐘資料計算的 realized variance，訊號清晰許多，是不是能讓 HAR-PD 翻盤？

K966 就是這個假說的 pilot 測試。

## 資料來源

- **標的**：SPY（S&P 500 ETF）
- **頻率**：5 分鐘 intraday，由 yfinance 抓取
- **期間**：2026-01-15 至 2026-04-06，共 55 個有效交易日
- **切分**：In-sample（IS）37 日，Out-of-sample（OOS）17 日
- **實驗編號**：K966
- **相關前身與家族實驗**：K624（HAR-PD 日頻 NULL）、K1024 / K1066 / K1072（microstructure / 高頻特徵家族）

需要先把話說清楚：**N_OOS=17 屬於 pilot 規模，遠遠不足以下定論**。本文所有數字必須在這個 caveat 之下解讀。即便如此，方向性的證據仍然值得記錄，因為它與 K624 的 NULL 完全一致。

## 模型設定與時序合法性

**HAR-RV 基準模型**：

RV_{t+1} = β₀ + β_d · RV_t + β_w · RV_t^(週) + β_m · RV_t^(月)

**HAR-PD 擴展模型**：在 HAR-RV 基礎上額外加入 R1 與 R2 兩個 path-dependent 特徵，λ₁、λ₂ 由 in-sample 的 grid search 決定（候選 grid：0.01, 0.05, 0.1, 0.2, 0.5, 0.8, 0.9, 0.95，共 64 組）。

**Lookahead audit**：所有特徵都是用「t 時刻及之前」的資訊預測「t+1 時刻」的 RV。HAR 的 daily / weekly / monthly aggregates、R1、R2 都嚴格只看歷史；λ 的選取也只在 IS 期間做，不偷看 OOS。沒有未來資訊洩漏。

**隨機程序 seed**：bootstrap 1000 次重複固定 seed=42。

## 結果一：In-sample 看起來 HAR-PD 大勝

先看訓練集的擬合效果：

| 模型 | IS R² | IS Adj R² |
|------|-------|-----------|
| HAR-RV | 0.575 | 0.448 |
| HAR-PD（R1 + R2，λ₁=0.01, λ₂=0.20） | **0.841** | **0.742** |

光看這張表，你會以為 HAR-PD 是個重大突破——R² 從 0.575 跳到 0.841，提升幅度高達 46%。新增的 R1、R2 兩個係數在 in-sample 也都達顯著水準（顯著性方面，β_R1 與 β_R2 的 p-value 分別為 0.022 與 0.0197）。

如果故事在這裡結束，HAR-PD 已經可以發論文了。但 in-sample 顯著本身**不是證據**——它只是個前提條件。決勝點在樣本外。

## 結果二：Out-of-sample HAR-PD 反而變差

切到 OOS 17 日後，故事整個翻轉：

| 模型 | OOS QLIKE ↓ | OOS R² |
|------|-------------|--------|
| HAR-RV | **0.331** | -7.354 |
| HAR-PD（R1 + R2） | 0.377 | -10.835 |
| HAR-PD（R1 only） | 0.346 | -8.617 |
| HAR-PD（R2 only） | 0.335 | -8.266 |

QLIKE 是波動率預測界 Patton（2011）建議的 robust loss function，越小越好。完整版 HAR-PD 比 HAR-RV **差 13.8%**（0.377 vs 0.331）。即便是只加 R2 的最簡單變體，也只能勉強和 HAR-RV 平手（差 1.3%）。

兩個模型的 OOS R² 都呈大幅負值，意味著 IS 與 OOS 期間的 RV 動態相差很大——這 17 日的 OOS 期可能剛好是個比較特殊的 regime（4 月初）。但**比較 HAR vs HAR-PD 在同一個 OOS 上的相對表現**仍是合理的，因為兩者面對的是同樣的測試資料。

## 結果三：兩模型比較顯著嗎？

我們做了兩個正式檢定：

**比較檢定（DM-style）**：統計強度 t = -1.37，未達顯著水準。換句話說，雖然方向上 HAR-PD 比較差，但在 N=17 的小樣本下統計強度不足以宣稱 HAR-PD 顯著遜於 HAR-RV。負號意味著 HAR-PD 較差，但檢定本身不能 reject「兩者一樣」的虛無假說。

**Bootstrap（1000 次重抽，seed=42）**：HAR-PD 的 QLIKE 平均比 HAR-RV 差 0.043，95% 信賴區間為 [-0.098, +0.030]，包含 0；在 1000 次重抽中，HAR-PD 表現較佳的比例僅 **10.6%**。

也就是說，bootstrap 的方向訊號很清楚（HAR-PD 在 1000 次重抽中只有 106 次贏），但統計上不能 reject「兩者效果相同」。**這是一個典型的「方向強但統計弱」的 pilot 結果**——指向 NULL，但不能 100% 釘死。

## 為什麼會這樣？典型的過度配適

把 IS 與 OOS 並排看，就會看到非常經典的 over-fitting pattern：

- IS：R² 從 0.575 拉到 0.841（+46%）
- OOS：QLIKE 從 0.331 惡化到 0.377（-14%）

**訓練集越會解釋，測試集反而越爛**——這幾乎是過度配適的教科書定義。

R1、R2 在 IS 期間「擬合」進去的東西，多半是 37 日 IS 樣本中的雜訊與特定波動結構，而不是可外推的訊號。模型新增了 2 個自由度（β_R1、β_R2），加上 grid search 在 64 組 λ 組合中挑最好的——等於做了第三層 selection bias——這在 N_total=55 的小樣本下幾乎注定 overfit。

值得一提的是，HAR-PD 的某些係數在 OOS 上甚至「方向錯了」：HAR-RV 的 β_d = -0.624，HAR-PD 的 β_d 進一步推到 -1.033。負的 daily coefficient 在 IS 上被 R1、R2 補回平衡，但 OOS 上 R1、R2 的補償效果消失，留下不穩定的負 daily 載荷。

## 與 K624 的一致性

把 K624（日頻 r²，PD 比 HAR 差 88%）與 K966（5 分鐘 RV，PD 比 HAR 差 13.8%）並列：

- 兩個資料頻率
- 兩個 RV 代理變數（日頻 squared return vs 5 分鐘 realized variance）
- 兩個樣本期
- **兩次都是 NULL，方向一致**

雖然 K966 的「差 13.8%」幅度遠小於 K624 的「差 88%」（這暗示 5 分鐘 RV 確實減少了一些雜訊噪音），但**從未有任何一次顯示 HAR-PD 真的勝出**。在 SPY 這個資產上，Guyon-Lekeufack 路徑依賴特徵的這個特定形式（R1、R2 with exponential decay），看起來就是 add noise rather than signal。

## 為什麼概念吸引、實證不勝？

這裡有幾個值得思考的可能解釋：

1. **HAR 已經「間接」捕捉了路徑資訊**：daily / weekly / monthly aggregates 本身就是一種「過去多長時間怎麼走」的摘要，R1、R2 多半在重複表達同一件事，但用了更多參數。
2. **5 分鐘 RV 的訊號雜訊比仍不夠高**：雖然比日頻好，但要榨出 R1、R2 的邊際資訊，可能需要 1 分鐘甚至 tick 級資料。
3. **路徑依賴效應在指數型市場上偏弱**：Guyon-Lekeufack 在 ES futures 等資產上的優勢，可能來自個別市場的特定 microstructure，未必能 generalize 到 SPY。
4. **參數化形式可能不對**：exponential decay 不見得是路徑記憶的最佳函數形式，hyperbolic / power-law decay 或許表現不同。

## Pilot 不是定論：誠實標示限制

最後也是最重要的一條：**N_OOS = 17 是 pilot 樣本，不是定論**。

我們不會用這 17 個 OOS 日就宣告 HAR-PD 在 5 分鐘 RV 上「死亡」。一個負責任的後續實驗應該至少蒐集 200+ 日的 5 分鐘資料（可能要動用更深的歷史 tick 庫、或改用 IB / Polygon 等資料源），重新跑一次乾淨的 IS / OOS / hold-out 三段切分，加上 cross-OOS robustness。在那之前，K966 只是一個 directional 訊號，不是 final verdict。

但結合 K624 的日頻 NULL，**我們認為「HAR-PD 在 SPY 上沒有展現出能 beat HAR 的證據」這個觀察夠強，足以把它從研究 backlog 上移到較低優先序**。下一步若要繼續探索路徑依賴方向，會優先測試：

- 不同的 path 函數形式（power-law vs exponential）
- 不同資產（單一股票、外匯、加密貨幣）
- 不同預測 horizon（intraday、weekly aggregate）
- 把 R1、R2 加入 GJR / EGARCH 而非 HAR 框架

## 結論

HAR-PD 在 5 分鐘 RV 上沒有打敗 HAR-RV，QLIKE 落後 13.8%。這個結果與 K624 在日頻的 NULL 方向一致，雖然兩模型比較顯著性未達嚴格統計門檻、且 N_OOS=17 屬於 pilot 規模需後續驗證，但 in-sample 大幅勝出 + out-of-sample 反而變差的 pattern 是非常典型的 over-fitting 警訊。

研究誠實的真義是：**不替吸引人的概念過度宣稱，也不替不漂亮的結果遮掩**。HAR-PD 是一個概念上漂亮的 idea；K966 沒有把它推翻，但也沒有給它任何 empirical 上的勝利。我們把這個 NULL 如實記錄下來，供後續以更大樣本、更多資產去進一步檢驗。

## 延伸閱讀

- Guyon, J. & Lekeufack, J. (2023). "Volatility is (Mostly) Path-Dependent." arXiv:2503.00851
- Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized Volatility." *Journal of Financial Econometrics* 7(2), 174–196
- Patton, A. (2011). "Volatility Forecast Comparison Using Imperfect Volatility Proxies." *Journal of Econometrics* 160(1), 246–256
- HLZ (2016) — 多假設檢定下的嚴格統計門檻參考

## 圖表

![HAR vs HAR-PD OOS 預測比較](k966_forecast_comparison.png)

*圖 1：HAR-RV 與 HAR-PD 在 OOS 17 日的逐日預測對比。HAR-PD 在多數日期偏離 actual RV 的幅度反而比 HAR-RV 大，視覺上印證了 QLIKE 數字。*

![Lambda Grid Search 熱圖](k966_lambda_grid.png)

*圖 2：λ₁ × λ₂ grid search 的 IS QLIKE 熱圖。最佳組合落在 λ₁=0.01, λ₂=0.20（IS QLIKE = 0.041）。但這個 in-sample 最佳組合並未轉化為 out-of-sample 的優勢，反而是 over-fitting 的證據之一——grid search 在小樣本下挑出的就是最會 fit IS 雜訊的點。*
