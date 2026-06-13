---
title: "K482：MCS p-value 加權平均輸給等權重，不是 5 段全敗"
audience: research
experiment_refs:
  - K482
  - K481
  - K475
description: "Codex 24h review correction: K482 supports an average QLIKE advantage for equal weight, not a five-period clean sweep; period-level count is Equal 3 vs MCS 2, with only Volmageddon significant."
---

# K482：MCS p-value 加權平均輸給等權重，不是 5 段全敗

**[提出: User, 執行: Claude；2026-06-12 Codex review 更正]**

## 更正摘要

原文把 K482 的主要結果寫成「等權重在 5 個市況全勝」與「MCS p-value 加權在 5 個市況全輸」。這個說法過強。`experiments/k482/k482_mcs_weighted_ensemble_results.json` 支持的正確結論是：

- 等權重在 5 個 OOS 期間的**平均 QLIKE** 低於 MCS p-value 加權：`0.721023` vs `0.735633`，MCS 平均損失高 2.03%。
- 逐期間比較不是 clean sweep：Equal 在 2015-2016、2017-2018、2019-2020 較好；MCS_PValue 在 2021-2022 與 2023-2025 數值上略好。
- 只有 2017-2018 Volmageddon 期間的 Equal vs MCS 差異達 5% 顯著：`DM=-2.6034`、`p=0.0092`。
- 五期間 Wilcoxon test 未達顯著：`W=3.0`、`p=0.3125`。
- `Inv_QLIKE_Prev` 是無 lookahead 的 period-level 自適應變體，但它的平均 QLIKE 是 `0.755654`，整體比等權重差，不應描述為接近等權重。

因此，本文結論改為：K482 支持 Timmermann forecast combination puzzle 的「平均 loss」版本，也就是 naive equal weight 在這個 SPY / 4-model / 5-period 設定下平均勝過 MCS p-value weighting；但它不支持「每個市況都勝」的強宣稱。

---

## 研究背景

波動率預測文獻有一個反覆出現的現象：把模型的統計資訊用來決定如何分配權重，理論上應該比平均分配更好，但實證上往往沒有。Timmermann（2006）將這類現象整理為 forecast combination puzzle。

K481 用 MCS 方法（Hansen, Lunde, Nason 2011）找出 4 個可納入 ensemble 的成份模型：GJR-GARCH、EGARCH、HAR log-range、HAR-Semivariance。K482 的問題是：既然 MCS 已提供 p-value 訊號，把 p-value 正規化成權重，是否能打敗 1/4 等權重？

---

## 方法與數據

| 項目 | 設定 |
|------|------|
| 資產 | SPY（yfinance，2005-02-02 至 2026-03-25）|
| 樣本數 | 5,319 個觀測值 |
| IS 窗口 | 2,000 個交易日 |
| 重估頻率 | 每季（63 個交易日）|
| 成份模型 | GJR-GARCH(1,1) Student-t / EGARCH(1,1) / HAR log-range / HAR-Semivariance |
| OOS 期間 | 2015-2016 / 2017-2018 / 2019-2020 / 2021-2022 / 2023-2025 |
| 損失函數 | QLIKE（Patton 2011），使用 r2 proxy 作為真實波動率替代 |
| 顯著性檢定 | Diebold-Mariano test + 五期間 Wilcoxon signed-rank test |

**六種比較方案**

| 方案 | 定義 | 是否可實際執行 |
|------|------|----------------|
| Equal_Weight | 各模型 1/4 等權 | 是 |
| MCS_PValue | 依 K481 MCS p-value 比例加權 | 是（靜態）|
| MCS_Subperiod | 依 K481 子期間 MCS p-value 比例加權 | 是（但需先有子期間估計）|
| Inv_QLIKE | 依當期 QLIKE 倒數加權 | 否，oracle |
| Inv_QLIKE_Prev | 依前一期 QLIKE 倒數加權 | 是，period-level 無 lookahead |
| Best_Single | 每期事後最佳單一模型 | 否，ex-post benchmark |

---

## 核心結果

![K482：五個 OOS 期間各加權方案的 QLIKE 比較](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k482_qlike_comparison.png)

*圖1：5 個 OOS 期間下各加權方案的 QLIKE。數值越低代表損失越小。*

| 期間 | n | Equal_Weight | MCS_PValue | MCS_Subperiod | Inv_QLIKE_Prev | Best_Single | Equal vs MCS |
|------|---:|---:|---:|---:|---:|---:|---|
| 2015-2016（低波動） | 504 | 0.5753 | 0.5876 | 0.5760 | - | 0.5892 | Equal 較好 |
| 2017-2018（Volmageddon） | 502 | 0.1093 | 0.1507 | 0.1072 | 0.0902 | 0.1098 | Equal 較好，且顯著 |
| 2019-2020（COVID） | 505 | 1.0876 | 1.1085 | 1.0911 | 1.0967 | 1.1329 | Equal 較好 |
| 2021-2022（升息） | 503 | 1.2198 | 1.2182 | 1.2606 | 1.2225 | 1.2205 | MCS 略好，未顯著 |
| 2023-2025（後疫情） | 752 | 0.6131 | 0.6131 | 0.6129 | 0.6132 | 0.6251 | MCS 極小幅略好，未顯著 |
| **平均** | | **0.7210** | 0.7356 | 0.7296 | 0.7557 | 0.7355 | Equal 平均較好 |

表中保留了兩個重點。第一，Equal_Weight 的平均 QLIKE 最低，這是本文的主要實證訊號。第二，這不是每期都贏；2021-2022 與 2023-2025 的 MCS_PValue 數值略低，但差距非常小，DM test 不支持把這兩段解讀為有統計意義的 MCS 優勢。

---

## MCS p-value 權重為何沒有改善平均 QLIKE

![MCS p-value 權重與平均 QLIKE 排名](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k482_mcs_weights_and_ranking.png)

*圖2：MCS p-value 正規化後的靜態權重，以及各方案跨期間平均表現。*

K482 使用的 MCS p-values 為 GJR=0.186、EGARCH=0.461、HAR=0.141、Semi=0.785。正規化後，HAR-Semivariance 佔 49.9%，EGARCH 佔 29.3%，GJR 與 HAR 合計只剩約 20.7%。

這不是 MCS 方法本身錯，而是「把特定估計期間的 p-value 固化為跨市況永久權重」引入了穩定性假設。若市場結構切換，過高的 Semi 權重會讓 ensemble 變得不夠分散。等權重沒有估計誤差優勢；它只是避免讓任何單一模型主導。

---

## 正式檢定

Equal_Weight vs MCS_PValue 的 DM test 如下：

| 期間 | DM stat | p-value | Equal 較好 | 5% 顯著 |
|------|---:|---:|---|---|
| 2015-2016 | -1.0153 | 0.3100 | 是 | 否 |
| 2017-2018 | -2.6034 | 0.0092 | 是 | 是 |
| 2019-2020 | -1.8781 | 0.0604 | 是 | 否 |
| 2021-2022 | 0.1936 | 0.8465 | 否 | 否 |
| 2023-2025 | 0.0002 | 0.9998 | 否 | 否 |

整體五期間 Wilcoxon signed-rank test 為 `W=3.0`、`p=0.3125`，沒有達到顯著。這代表本文不能宣稱「MCS p-value weighting 在每個市場狀態都失敗」；能宣稱的是，在這個設計下，Equal_Weight 的平均 QLIKE 較低，而最強的 period-level 統計證據集中在 Volmageddon。

---

## Lookahead 與可執行性

K482 的核心 forecast loop 對 Equal_Weight、MCS_PValue、MCS_Subperiod 都是 ex-ante：第 t 日預測使用 `feat.iloc[is_start:pos]` 的資料估計模型，再和第 t 日 realized variance 比較。

`Inv_QLIKE` 使用當期 QLIKE 來決定權重，是 oracle 上界，不可實際執行。`Inv_QLIKE_Prev` 使用上一個 OOS period 的 component QLIKE，沒有同期間 lookahead，但它在跨市況切換時不穩定，平均 QLIKE `0.755654` 比等權重差。

---

## 實務意義

1. **MCS 比較適合作為篩選工具，而不是直接權重工具。** K481 的 p-values 可以幫助決定哪些模型進入候選集合；K482 顯示，把 p-value 直接正規化成固定權重不一定改善平均 OOS loss。

2. **等權重仍是非常強的 baseline。** 若一個 adaptive weighting 方法沒有清楚通過 Harvey/DM 或 bootstrap 類正式檢定，不能只因方法更複雜就宣稱它更好。

3. **下一步應測試真正 time-varying 的權重。** K482 測的是靜態 MCS p-value 與 period-level inverse-QLIKE。rolling MCS、forgetting factor、或月度 loss-based weights 都是可檢定的後續方向。

---

## 限制

- 單一資產：目前只測 SPY，不能直接推論到台股、商品或債券。
- r2 proxy 有噪音：QLIKE 的絕對水準受 realized variance proxy 影響，本文重點應放在相對 ranking。
- MCS p-values 不是 rolling 估計：靜態權重可能放大某段歷史狀態的模型偏好。
- Period 數只有 5：五期間檢定力有限，Wilcoxon 未達顯著。

---

## 結論

K482 的修正後結論是：在 SPY 2005-2026、四個 volatility model、五個跨 OOS period 的設計下，Equal_Weight 的平均 QLIKE 低於 MCS_PValue，支持 forecast combination puzzle 的平均-loss 版本。但 period-level 結果是 Equal 3 段勝、MCS 2 段數值勝，且只有 Volmageddon 的 Equal 優勢達 5% 顯著。這是「等權重平均更穩健」的證據，不是「每個市況都全勝」的證據。

*本文基於實驗 K482（腳本：`experiments/k482/k482_mcs_weighted_ensemble.py`，結果：`experiments/k482/k482_mcs_weighted_ensemble_results.json`）。數據來源：yfinance SPY，期間 2005-02-02 至 2026-03-25，樣本 5,319 個觀測值。相關實驗：K475、K481。*

*引用文獻：Hansen, Lunde, Nason (2011) "The Model Confidence Set" Econometrica 79(2):453-497；Timmermann (2006) "Forecast Combinations" Handbook of Economic Forecasting；Patton (2011) Journal of Econometrics, QLIKE loss。*
