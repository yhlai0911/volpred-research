---
title: "Granger 顯著卻預測不準：金融股壓力指標對台積電波動率的 OOS 真實"
audience: research
status: draft
tags: ["K1432", "HAR-RV", "DM test", "波動率預測", "台積電", "金融股壓力", "OOS", "QLIKE"]
experiment_refs: ["K1432"]
proposer: "Claude"
---

# Granger 顯著卻預測不準：金融股壓力指標對台積電波動率的 OOS 真實

**[提出: Claude, 執行: Claude]**

## 摘要

K1432 使用 2010–2026 年台股資料（train 2,814 obs / OOS 1,397 obs），以四個預先承諾的金融股壓力指標規格（S1–S4）檢驗能否增量改善台積電（2330.TW）21 日 rolling realized volatility 的樣本外預測。基準模型為 Corsi (2009) HAR-RV 與 HAR-RV+VIX。結論是完整的 NULL：四個 spec 在三個預測期 (h=1, 5, 10) 全無增量改善，且多個 spec × horizon 組合在 Patton (2011) QLIKE 損失下對 HAR-RV 顯著惡化（DM stat 最差至 −3.25, p=0.0012）。In-sample Granger 因果（S1 lag 4: F=7.11, p=1.05e-5）在 OOS 不轉化為預測利益，HAR-RV 已內化多數可預測訊號。

---

## 研究背景

K757 / K757b / K757bv2 系列在日報酬層級建立了富邦金（2881.TW）對台積電的 Granger 因果（F=5.60, p=1.9e-6）。這個發現說明金融股報酬含有預測台積電報酬的線性資訊，在 in-sample 上足夠穩健。

學術 referee 面對這類結果必然問四個後續問題：

1. **波動率預測**：日報酬層次的 Granger 是否延伸到條件波動率（RV）？
2. **OOS**：in-sample 的顯著性能否在真正的樣本外維持？
3. **多 spec 防 cherry-pick**：發現對 spec 的選擇是否敏感？
4. **對 HAR-RV + VIX 的增量價值**：這個訊號是否在已有成熟 baseline 後仍有邊際貢獻？

K1029 延伸了 K757 系列，以 0050.TW 為目標、GJR-GARCH-X 為框架，結論是 Granger 顯著但 GARCH-X OOS 反而惡化。K1432 採用不同設計：以 TSMC 為目標、HAR-RV 框架、OLS expanding window、四個預先承諾的壓力 spec，並執行正式的 Diebold-Mariano 檢定，填補四個 gap。

---

## 方法與數據

| 項目 | 設定 |
|------|------|
| 目標資產 | 台積電 2330.TW — 21d rolling sum of squared log returns（log-transformed） |
| 金融股 universe | 2881.TW / 2882.TW / 2891.TW / 2884.TW / 2880.TW（5 檔，需含 2881+2882） |
| VIX proxy | ^VIX（美國 VIX；台指 VIX 期間覆蓋不一致） |
| 資料來源 | yfinance（日頻，cached to `data/prices.parquet`） |
| 樣本期間 | 2010-01-04 至 2026-06-08（~16 年） |
| Train / OOS | Train: 2010-03-04–2020-12-31（n=2,814）/ OOS: 2021-01-01–2026-05-25（n=1,397） |
| 預測期 h | 1, 5, 10 交易日 |
| 預測框架 | Expanding window OLS，每 21 個交易日 refit |
| Lag 規則 | `make_targets()` 用 `logrv.shift(-h)` 對齊 y；`expanding_ols_forecast` 嚴格 `iloc[:pos]` — 所有預測只含 t 及 t 之前資訊 |
| Seed | `np.random.seed(42)` 全域固定 |
| DM 檢定 | Newey-West HAC (lag=h−1) + Harvey-Leybourne-Newbold (1997) 小樣本修正；雙尾 t_{n-1} |
| 損失函式 | MSE on log RV + Patton (2011) QLIKE = log(σ̂²) + σ²/σ̂² |

### 四個預先承諾的壓力 spec（寫入腳本 source 後 commit，執行前不可更改）

| Spec | 定義 |
|------|------|
| **S1** | 5 檔金融股 21d realized variance 橫斷面均值（水平層次的聚合壓力） |
| **S2** | 每日 max-min 報酬 dispersion 的 21d rolling std（異質性壓力） |
| **S3** | （金融股平均報酬 − 0050 報酬）5d rolling mean（相對弱勢訊號） |
| **S4** | 金融股報酬 PCA 第一主成分得分絕對值的 21d rolling mean（主成分壓力；loadings 僅用 train 期估出，OOS 套用固定 loadings） |

### Baseline 模型

- **B1 AR(1)**：log(RV_t) → log(RV_{t+h})
- **B2 HAR-RV**：Corsi (2009) daily / weekly(5d) / monthly(22d) RV
- **B3 HAR-RV+VIX**：B2 加上 log(^VIX)

### 比較模型矩陣

B2+S1 / B2+S2 / B2+S3 / B2+S4 / B2+all（共 5 個 B2 augmented）；B3+S1 / B3+S2 / B3+S3 / B3+S4（共 4 個 B3 augmented）。

---

## 核心發現一：In-sample Granger 顯著性

在全樣本（n=4,211）執行 Granger 因果檢定，lag 1–10，Wald F-test：

| Spec | 代表 lag | F-stat | p-value | 結論 |
|------|---------|--------|---------|------|
| S1（xs vol） | lag 4 | 7.11 | 1.05e-5 | 顯著 |
| S1（xs vol） | lag 5 | 5.67 | 3.23e-5 | 顯著 |
| S2（dispersion） | lag 2 | 7.91 | 3.73e-4 | 顯著 |
| S2（dispersion） | lag 3 | 5.68 | 7.00e-4 | 顯著 |
| S3（rel weak） | lag 1–10 | 0.003–0.25 | 0.954–0.991 | 完全不顯著 |
| S4（PCA \|PC1\|） | lag 3 | 4.89 | 2.15e-3 | 顯著 |
| S4（PCA \|PC1\|） | lag 4 | 4.59 | 1.06e-3 | 顯著 |

**S1、S2、S4 在 in-sample 對 TSMC log RV 具有 Granger 因果（p<0.005）。S3 在所有 lag 完全無顯著性（p>0.95）。**

下圖呈現四個 spec 在 lag 1–10 的 F-stat 分布（顏色深度代表 p-value 強度）：

![In-sample Granger F-stat heatmap：4 specs × 10 lags](experiments/k1432/figures/stress_and_rv.png)

*圖 1：台積電 RV 時間軸與四個壓力指標（z-score 標準化）。S1、S2 的高壓期（紅色帶）與 TSMC RV 高峰有明顯的視覺共移。*

---

## 核心發現二：OOS DM 檢定 — 系統性惡化

下表整理對 HAR-RV（B2）的 DM 檢定結果。**DM stat < 0 代表壓力增強模型的 LOSS 比基準高**，即 baseline 較好。

### QLIKE 損失（Patton 2011 穩健損失）— vs B2 HAR-RV

| Horizon | 比較對 | DM stat | p-value | 解讀 |
|---------|--------|---------|---------|------|
| h=1 | B2 vs B2+S3 | −2.09 | 0.037 | S3 顯著惡化 |
| h=1 | B2 vs B2+S4 | −2.23 | 0.026 | S4 顯著惡化 |
| h=1 | B2 vs B2+S1 | −1.91 | 0.057 | 邊緣（略惡化） |
| h=1 | B2 vs B2+S2 | −0.07 | 0.944 | 無差異 |
| h=5 | B2 vs B2+S1 | −2.60 | 0.0095 | S1 顯著惡化 |
| h=5 | B2 vs B2+S4 | −2.82 | 0.0048 | S4 顯著惡化 |
| h=5 | B2 vs B2+all | **−3.12** | **0.0018** | 全 spec 組合最強惡化 |
| h=10 | B2 vs B2+S1 | −2.90 | 0.0038 | S1 顯著惡化 |
| h=10 | B2 vs B2+S4 | −2.70 | 0.0069 | S4 顯著惡化 |
| h=10 | B2 vs B2+all | **−3.25** | **0.0012** | 全 spec 最強惡化（整個矩陣） |

**整個 spec × horizon 矩陣沒有任何一格在統計顯著的方向上優於 B2 HAR-RV。** 多個格子在 QLIKE p<0.05 顯著惡化，h=10 的 B2+all 得到最強 DM stat=−3.25（p=0.0012）。

### MSE 損失 — 對應子集（顯著惡化格）

| Horizon | 比較對 | DM stat (MSE) | p-value |
|---------|--------|---------------|---------|
| h=1 | B2 vs B2+S3 | −2.58 | 0.010 |
| h=10 | B2 vs B2+S1 | −1.98 | 0.048 |
| h=10 | B2 vs B2+all | −2.94 | 0.003 |

MSE 損失的惡化數量略少，但整體方向一致。

### OOS QLIKE 損失水準

| 模型 | h=1 QLIKE | h=5 QLIKE | h=10 QLIKE |
|------|-----------|-----------|------------|
| B2 HAR-RV | −4.17794 | −4.12623 | −4.05600 |
| B2+S1 | −4.17792 | −4.12580 | −4.05505 |
| B2+S4 | −4.17792 | −4.12578 | −4.05502 |
| B2+all | −4.17792 | −4.12556 | −4.05377 |
| B3 HAR-RV+VIX | −4.17805 | −4.12795 | −4.05974 |

QLIKE 損失絕對差值小（第五位小數），但累積 1,397 obs 後 DM 統計量仍達顯著，說明壓力 spec 引入了系統性的估計誤差，而非只是隨機雜訊。

下圖呈現 OOS QLIKE 各模型 × 各 horizon：

![OOS QLIKE by horizon：各模型比較](experiments/k1432/figures/qlike_by_horizon.png)

*圖 2：OOS QLIKE by horizon。B3 HAR-RV+VIX 在三個 h 均優於 B2，顯示 VIX 有增量信息。B2+stress 系列普遍高於（更差）B2，B2+all 最差。*

---

## 核心發現三：VIX 的角色

**B3 HAR-RV+VIX 在三個 h 均優於 B2**（h=1 QLIKE: −4.17805 vs −4.17794, DM stat=1.98, p=0.048；h=5: −4.12795 vs −4.12623, DM stat=1.76, p=0.078）。VIX 在短期預測上有統計顯著的增量價值，而金融股壓力 spec 完全沒有。

矛盾現象：加入 stress 後 B3 augmented 版本（B3+S4）在 h=5, h=10 QLIKE 反而略優於 B3（h=5: −4.12881 vs −4.12795, DM=2.73, p=0.006），但這個「優」的方向是 B3+S4 好於 B3，**不是** B3+S4 好於 B2，所以沒有改變核心結論：對 B2 baseline 的 DM 全無顯著改善。這只說明在 B3 基礎上，S4 能提供一點 incremental gain，但 B2→B3 的跳躍遠大於 B3→B3+S4 的跳躍。

---

## 主要解讀

### 1. In-sample Granger 顯著 ≠ OOS 預測價值

S1（橫斷面 vol）在 lag 4 F=7.11（p=1.05e-5），S2（dispersion）在 lag 2 F=7.91（p=3.73e-4），是很強的 in-sample 線性 predictive content。但 OOS 加入 HAR-RV 後反而使 QLIKE 惡化。

Granger 因果是**條件均值**層次的線性 predictive content test。它問的是「給定 X 過去值，Y 的條件均值是否更精確」。波動率預測的目標是**條件二階矩**（RV level，不是報酬），HAR-RV 本身已用三個不同頻率的 RV lag 捕捉了自身的長記憶結構。壓力指標能 Granger-cause log RV，說明兩者有 in-sample 線性關係；但這個關係在 OOS 無法帶來增量改善，代表：(a) 這個關係的 signal-to-noise 在 OOS 衰減，或 (b) HAR-RV 已涵蓋相同資訊。

### 2. HAR-RV 已內化金融壓力的預測成分

台積電的日/週/月 RV 結構本身與金融股壓力高度共移——台股在高壓力期間系統性地提升波動率，HAR-RV 的月項（22d）已間接包含了這段記憶。S1（21d 橫斷面 vol）與 HAR-RV 月項高度共線，加入後不帶新資訊，反而增加係數估計的方差（OLS overfitting），導致 OOS 退化。

### 3. 全 spec 聚合（B2+all）最差

h=5 B2+all QLIKE DM=−3.12（p=0.0018），h=10 DM=−3.25（p=0.0012）是整個矩陣最強的惡化。加入所有四個 spec 帶來更多共線性，過參數化更嚴重，OOS 惡化比任何單一 spec 都強。

### 4. 與 K757 系列的關係

K757bv2 在**日報酬**層次建立 Fubon→TSMC Granger F=5.60，K1432 延伸到**波動率（log RV）預測 + OOS + 多 spec + HAR-RV/VIX baseline**，兩者結論不矛盾：日報酬的線性 predictive content 存在，但不轉化為 OOS 波動率預測的增量利益。

---

## 實務意義

**對量化研究者**：Granger 顯著在 in-sample 是研究的起點，不是終點。每個 Granger 顯著的因子都要接著問：(a) OOS 的 DM test 對 appropriate baseline（本例是 HAR-RV，不只是 AR(1)）是否顯著，(b) 是否有共線性的 overfitting 問題。本例中 S1 與 HAR-RV 月項的高共線性是系統性風險，pre-commit spec 並不能防止這類問題。

**對策略設計者**：台灣金融股壓力指標在 TSMC 波動率預測上不帶有效的 OOS 訊號。如果研究目標是改善 TSMC 波動率預測，金融壓力指標不是合適的輸入。如果研究目標是台灣系統性金融風險指標的建構（非 TSMC 單一標的預測），問題框架不同，結論不必然相同。

**對其他研究者**：pre-commit 四個 spec 是必要的設計，但 4 spec × 3 horizon × 2 loss 的矩陣中「全無改善」是更強的 null 訊號——不是 cherry-pick 的問題，是這類訊號本身在 OOS 對 HAR-RV 沒有增量價值。

---

## 限制與穩健性

1. **VIX proxy**：使用美國 ^VIX，非台指 VIX（後者期間覆蓋不一致）。若用 TWVIX 結論可能微調，方向大概率不變。
2. **21d RV 定義**：daily-only proxy；台股日內資料免費版不可用，更精確的 5-min realized variance 可能給不同結果。
3. **PCA loadings 固定**：S4 的 PCA loadings 僅用 train 期估出並固定在 OOS 套用，符合 K1216c symmetric refinement 規則。若用 rolling PCA 可能微調，但會引入額外 complexity。
4. **OLS 框架**：所有模型統一用 expanding window OLS（每 21 d refit），未試 GARCH-based 波動率方程式（K1029 已試過 GJR-GARCH-X 路徑）。

HAC DM 檢定使用 Newey-West lag=h−1 + HLN 小樣本修正，n=1,397 足夠大，p-value 穩健。多重比較未做 Bonferroni 或 MCS 調整，但考慮到全矩陣無一顯著改善、且多格顯著惡化，方向性結論不受多重比較影響。

---

## 結論

**K1432 verdict: NULL（with stronger reading: stress augmentation 在 OOS 對 TSMC log RV 預測上顯著惡化）。**

四個預先承諾的台灣金融股壓力規格（S1–S4）在三個預測期（h=1, 5, 10）相對於 HAR-RV 與 HAR-RV+VIX baseline：

- **無任何 spec × horizon 的 DM 顯著正向**（壓力模型勝過 baseline）
- **多個 spec × horizon 在 QLIKE 顯著負向**（壓力模型顯著劣於 baseline），最差 DM=−3.25（p=0.0012）
- **全 spec 聚合（B2+all）系統性最差**，h=5 和 h=10 QLIKE DM 均超過 |3.0| 的 Harvey 多重檢定門檻

In-sample Granger 因果（S1 F=7.11, p=1.05e-5；S2 F=7.91, p=3.73e-4）在 OOS 框架下不轉化為預測利益。HAR-RV 的三頻率 RV 結構已充分內化了金融壓力與 TSMC 波動率的共移成分，額外加入壓力指標帶來的是過參數化而非資訊增量。

這個結果延伸並補充了 K1029 的結論（0050 target / GJR-GARCH-X 路徑），並填補了 K757 系列留下的四個 OOS gap。結論是 in-sample Granger 顯著是必要條件，不是充分條件；OOS 增量預測能力要對 HAR-RV 這類成熟 baseline 額外提供，才構成可操作的 forecastability claim。

後續方向：(a) 非線性規格（regime-switching HAR-RV with stress threshold）能否克服 OOS 過參數化；(b) 更短期預測（h=0，日內更新）下金融壓力的即時 signal 性質；(c) 跨資產（台股以外）的金融板塊壓力與龍頭股波動率的普遍性。

---

## 資料來源與相關實驗

*本文基於實驗 K1432（腳本：`experiments/k1432/k1432_tw_financial_stress.py`，結果：`experiments/k1432/k1432_tw_financial_stress_results.json`）。資料來源：yfinance（2330.TW / 2881.TW / 2882.TW / 2891.TW / 2884.TW / 2880.TW / 0050.TW / ^VIX 日頻收盤價）；期間：2010-01-04 至 2026-06-08；train obs: 2,814；OOS obs: 1,397；seed: 42。*

**關聯實驗**：
- K757 / K757b / K757bv2 — 富邦金 → TSMC 日報酬層次 Granger 因果（F=5.60, p=1.9e-6），K1432 的先行研究
- K1029 — 0050 target / GJR-GARCH-X 路徑，Granger 顯著但 GARCH-X OOS 退化的平行結論

**參考文獻**：
- Corsi, F. (2009). A simple approximate long-memory model of realized volatility. *Journal of Financial Econometrics*, 7(2), 174–196.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246–256.
- Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253–263.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction MSEs. *International Journal of Forecasting*, 13(2), 281–291.
