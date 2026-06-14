# K1330: 美元指數作為跨資產波動條件變數（去重結案）

- **K id**: K1330
- **Status**: completed
- **Verdict**: **SUPERSEDED_BY_K1439**
- **Created**: 2026-06-14

## 問題

研究題目原文：

> 美元指數（DXY / UUP）作為跨資產 vol 的條件變數：強弱美元 regime 下 EM/商品/黃金 vol 的差異（yfinance）

## 為何這次不重跑

這個 backlog 題目已被最近完成且可重現的 [`experiments/k1439/`](../k1439/README.md) 實質覆蓋：

- **資料範圍一致**：`UUP` 作為美元 proxy，資產包含 `EEM`（EM）、`GLD`（黃金）、`DBC/DBB/USO`（商品）
- **方法更嚴格**：`K1439` 不只做 strong/weak USD bucket 比較，還額外補了
  **HAC / Newey-West** 推論來修正 21 日 RV overlap 自相關問題
- **lookahead 已處理**：regime bucket 在 `k1439.py` 內明確 `shift(1)`
- **2026-06-14 已重現驗證**：`uv run python experiments/k1439/reproduce.py` 可在目前工作樹成功重跑

因此，若再做一次 `K1330`，本質上只會產出近乎重複的實驗，不增加新知識，反而稀釋任務池品質。

## 與相關 K 的邊界

- **K1439**：回答「強弱美元 regime 下，不同跨資產 RV 是否有系統性差異」。
- **K878**：回答「DXY 是否能直接預測 SPY 波動率」，結論為 **NULL**。

也就是說：

1. `K878` 已經否定了「美元直接預測單一股市波動」這條路。
2. `K1439` 已經回答了本題真正要問的「美元作為**條件變數**時，哪些資產的 vol 更敏感」。

## 重現與結案流程

1. 先重跑 `K1439`：
   ```bash
   uv run python experiments/k1439/reproduce.py
   ```
2. 再執行本 closure audit：
   ```bash
   uv run python experiments/K1330/K1330.py
   ```

## Canonical Findings（來自 K1439 重現）

- 樣本：2010-01-04 至 2026-06-05，`N=4131` 日
- 資產：`EEM`, `GLD`, `DBC`, `USO`, `DBB`
- 主結果：若只看 naive Welch，4/5 資產在強美元 regime 下 RV 較高；但改用
  **HAC + Bonferroni** 後，只剩 **USO** 在 level 與 trend 兩種 regime 定義下都穩健顯著
- `GLD` 為 **NULL**，符合黃金 safe-haven channel 與美元 channel 互相抵銷的敘述

## 本次結論

`K1330` 應視為 **已由 K1439 回答並 supersede**，不應再以新實驗重跑相同題目。

這不是新的 empirical finding，而是對 backlog 的正式去重與治理收尾。

## 方法論與防錯

- `K1439` 的 canonical inference 已從 Welch 降級為 **HAC/Newey-West**
- 重點風險不是 lookahead，而是 **21-day rolling RV 的 overlap 自相關**，若只看 Welch 會高估顯著性
- 本結案檔不新增任何統計 claim，只引用已重現、已 commit 的 canonical artifact

## 文獻定位（本次僅做 framing，不新增實證）

以下文獻支持「美元因子 / safe-haven / 跨資產風險條件化」這個研究方向，但不改變本次去重結論：

1. Lustig, Roussanov, Verdelhan, *Common Risk Factors in Currency Markets* (NBER WP 14082, 2008)  
   <https://www.nber.org/system/files/working_papers/w14082/w14082.pdf>
2. Lustig, Roussanov, Verdelhan, *Countercyclical Currency Risk Premia* (NBER WP 16427, 2010)  
   <https://www.nber.org/system/files/working_papers/w16427/w16427.pdf>
3. Baur and McDermott, *Is gold the best hedge and a safe haven under changing stock market volatility?* (Review of Financial Economics, 2013)  
   <https://onlinelibrary.wiley.com/doi/10.1016/j.rfe.2013.03.001>

## Files

- `K1330.py` — closure audit script
- `K1330_results.json` — machine-readable dedup / supersession verdict
