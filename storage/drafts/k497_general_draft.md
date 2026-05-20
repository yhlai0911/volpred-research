---
title: "換一把尺，模型排名會變嗎？K497 用 5 條 Patton loss 對 SPY 波動率模型重排"
audience: general
status: draft
tags:
  - 波動率預測
  - 模型評比
  - 損失函數
  - 穩健性
  - 方法論
experiment_refs:
  - K497
---

# 換一把尺，模型排名會變嗎？K497 用 5 條 Patton loss 對 SPY 波動率模型重排

## 一句話結論

我們把 8 個常見的 SPY 日波動率模型（GARCH 家族 + HAR + Semivar + EWMA + 簡單滾動 + 等權集成）拿出來，**用 5 條不同的 Patton loss function 各排一次名**。結果是：排名不會「亂掉」，但也**不會完全一致**。平均兩兩 Spearman ρ = **0.7071**，屬於 **MODERATELY STABLE（中等穩定）**。沒有任何一個模型在 5 條 loss 下都進 MCS（model confidence set），也沒有任何模型被全部判出局。換句話說：**「QLIKE 上贏的模型」不等於「不管怎麼算都贏的模型」** —— 學術上只看 QLIKE 的習慣，需要至少 1 條額外 loss 做穩健性檢核。

## 為什麼要做這個實驗

學術界比波動率模型，有一個近乎默認的選擇：**QLIKE**（Patton 2011 推薦）。理由很硬：在 r²、parkinson 等不完美 proxy 下，QLIKE 對 proxy 偏誤具備 robustness（degree-0 homogeneous），錯誤的 proxy 不會把模型排名翻過來。

但問題是：**世界上的損失函數不只有 QLIKE**。實務交易者可能更在乎絕對誤差（MAE）、避險工程師可能更在乎相對誤差（HMSE / HMAE）、教科書最常用的還是 MSE。如果**換把尺量同一批模型，名次大洗牌**，那「QLIKE 第一名」就是脆弱的。

K495 是這個系列的另一個實驗，它整理了一份「unified vol forecasting guide」，結論幾乎全部建立在 QLIKE 上。K497 的任務就是回答一個簡單的問題：**這份 guide 的結論禁得起換 loss 嗎？**

## 怎麼做的

- **資產**：SPY（2004-01-05 到 2026-03-25，5,591 筆日報酬，OOS 2023-01-01 之後共 752 天）
- **8 個模型**：GJR-GARCH、GARCH、EGARCH、HAR_logrange、Semivar_RS-（負半變異）、EWMA、EW_Ensemble（等權集成）、Rolling_21d（21 日滾動 baseline）
- **5 條 loss function（Patton family）**：
  - QLIKE：rv/σ² − log(rv/σ²) − 1（degree-0 homogeneous，proxy-robust）
  - MSE：(σ² − rv)²（標準二次損失）
  - MAE：|σ² − rv|（穩健於極端值）
  - HMSE：(rv/σ² − 1)²（標準化版 MSE，scale-free）
  - HMAE：|rv/σ² − 1|（標準化版 MAE）
- **MCS** 採 Hansen-Lunde-Nason，α=0.1、bootstrap 5,000 次、block size 10
- **滾動視窗** 2,000 天，每 63 個交易日重估參數一次

## 結果一：5 條 loss 給出 5 種「冠軍」

下面這張排名熱力圖把答案畫得最清楚。每一格是「模型 × loss」下的名次，1 = 第一名（綠），8 = 末名（紅）。

![K497 Ranking Heatmap](experiments/k497/k497_ranking_heatmap.png)

幾個重點：

- **Semivar_RS-** 在 QLIKE / HMSE / HMAE 三條都拿第一，但在 MSE 第 2、MAE 掉到第 3
- **HAR_logrange** 在 MSE 拿第一，在 MAE 卻掉到第 6
- **EGARCH** 在 MAE 拿第一，但在 MSE 排到第 5
- **Rolling_21d** 是唯一**5 條 loss 都最後一名**的模型 —— 這個是真正穩定的「輸家」

換言之：「最好」是 loss-dependent，「最差」反而是穩定的。

## 結果二：Spearman ρ 矩陣 —— 中等而非完美

如果排名完全不受 loss 影響，5 條 loss 兩兩 Spearman 相關都應接近 1。實際上：

![K497 Spearman Matrix](experiments/k497/k497_spearman_matrix.png)

- **平均兩兩 ρ = 0.7071**（系統判定 MODERATELY STABLE）
- HMSE 和 HMAE 之間 **ρ = 1.00**（兩條本質都在比 rv/σ² 偏離 1，名次完全一樣）
- QLIKE vs HMSE / HMAE：**ρ = 0.9048**（高度一致，因為這 3 條都屬 Patton degree-0 homogeneous family）
- **MAE vs HMSE / HMAE：ρ = 0.3571**（明顯分歧）
- **MAE vs MSE：ρ = 0.4286**（同樣是 absolute vs squared，但因為 SPY 報酬厚尾，MSE 被尾巴拖著走）

K497 進一步把 5 條 loss 拆成兩類：

- **Homogeneous（QLIKE / HMSE / HMAE）內部**：平均 ρ = **0.9365**（很穩）
- **Non-homogeneous（MSE / MAE）內部**：平均 ρ = **0.4286**（不穩）
- **跨 class 平均**：ρ = **0.6389**

這是一個很乾淨的訊號：**Patton 推薦 QLIKE 並非偶然 —— degree-0 homogeneous 這個性質的確讓排名更穩定**。但也意味著：**只要你切到 non-homogeneous loss，名次就會洗**。

## 結果三：MCS 沒有「universal 冠軍」

更嚴格的問法是 MCS（model confidence set）：在每條 loss 下，誰能進「無法被剔除的模型集合」？K497 的逐 loss MCS（α=0.1）結果：

- **QLIKE**：5 個進（EGARCH、EW_Ensemble、GJR-GARCH、HAR_logrange、Semivar_RS-）
- **MSE**：8 個全進（沒有任何模型被剔除）
- **MAE**：7 個進（只剔除 Semivar_RS-）
- **HMSE**：4 個進（EW_Ensemble、HAR_logrange、Rolling_21d、Semivar_RS-）
- **HMAE**：**只有 1 個** —— Semivar_RS-，其他全被踢出

把 5 條交集起來：

![K497 MCS Inclusion](experiments/k497/k497_mcs_intersection.png)

關鍵觀察：

- **universal_superior_models = []** —— 沒有任何模型在 5 條 loss 下都進 MCS
- **never_superior = []** —— 也沒有任何模型在 5 條 loss 下全被剔除
- 進 MCS 比例最高的是 **Semivar_RS- / HAR_logrange / EW_Ensemble**（4/5 = 80%）
- 雖然每條 loss 下 best vs second 的 Diebold-Mariano 檢定都未達顯著（pval 介於 0.0771 ~ 0.9408 之間），但這正是 MCS 的價值 —— 排名前段的差距通常統計上區分不開

## 該怎麼讀這份結果？

這是 K497 想送出的訊息，分**三層**講清楚：

1. **K495 的結論可以採信**，因為 QLIKE 是公認的 proxy-robust loss，且 K497 確認 **qlike_robustness = true**（QLIKE 的排名不被替換 loss 顯著推翻）。但這個 robustness 是 **conditional on QLIKE-based framework**，不是「排名怎麼換 loss 都一樣」。
2. **學術寫作不能只報 QLIKE**。K497 的 ρ=0.7071 不是接近 1，而是「中等」 —— 換成 MAE 會看到 EGARCH 反而拿冠軍。論文 robustness check 至少需要 1 條額外的 loss（MSE 或 MAE）佐證。
3. **「universal superior model」是個迷思**。讀者下次看到「我家模型贏 QLIKE，所以最好」這種敘事，應該追問一句：**「換 MSE / MAE / HMSE 還贏嗎？」** —— K497 的 8 個模型沒有一個能通過這個檢定。

## 誠實的限制

- 這只是 **SPY 一個資產**。Patton (2011) 的 robustness 性質是針對 proxy 偏誤而非跨資產，所以理論上 ρ 可能在 BTC / 台股 / 個股上有不同模式（K498 之後的 cross-asset 延伸是合理下一步）
- 5 條 loss 都是 **Patton family**，沒有納入 VaR / ES / utility-based loss（避險工程師最在乎的那一塊）
- MCS 用 r² 當 proxy（Patton 的標準做法）；用 RV5 / Parkinson 當 proxy 排名可能再變

## 下一步

K497 給了 K495 的結論一張「中等可信」的合格證，也指出後續工作方向：**將同樣的 5-loss 排名穩定性檢定推到 cross-asset（QQQ / IWM / 加密 / 台股）與 regime-conditional（高低波分段）**，看 ρ 在不同制度下會不會掉到 0.5 以下。如果掉了，那就是 K495 結論真正需要被重訪的地方。

---

**資料來源**：實驗 K497（`experiments/k497/k497_loss_sensitivity_results.json`）；OOS 樣本 2023-01-01 ~ 2025-12-31，752 天；MCS 採 Hansen-Lunde-Nason（α=0.1，5,000 bootstrap，block 10）。所有圖表由 K497 results JSON 直接渲染，數字 byte-for-byte 對齊實驗檔。延伸閱讀：K495（unified vol forecasting guide）、K481（QLIKE-only MCS baseline）。
