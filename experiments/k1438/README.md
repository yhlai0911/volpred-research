# K1438: VIX1D 作為 SPY 日內 RV covariate — Feasibility Audit

## 動機

任務原始假說是：`VIX1D` 這種 1-day implied volatility 指標，理論上比 30-day `VIX` 更貼近日內 / 次日 realized variance，可能在 `HAR-RV` 框架裡提供額外訊號。

但本專案的研究誠實原則要求：

1. `HAR-RV` 必須用 **5-min realized variance** 當 target，不能偷換成日頻 `r²`
2. `VIX1D` 必須有 **本地可重現** 的 time series，不能靠一次性的外網抓取
3. 在資料缺口沒補齊前，不可宣稱正式 forecasting 結論

因此 K1438 本輪先做 **feasibility audit**，確認本地是否具備正式實驗的最小條件。

## 研究問題

1. 本地是否已有足夠長度的 SPY 5-min 資料可做 HAR-RV 類比較？
2. repo 內是否已有 canonical 的 `VIX1D` 歷史資料源？
3. 若沒有，現在能否誠實完成 `HAR-RV + VIX1D` horse race？

## 相關既有發現

- `research_findings.md` 已記錄一條先前策略層 null result：`VIX1D` 比 30-day `VIX` 更 noisy，對 VT sizing 較差
- `research_program.md` 與 `knowledge.json` 多次記錄：5-min RV 是突破日頻 proxy ceiling 的正確方向，但樣本長度不足時容易 underpowered
- `docs/research_notes/literature_review_2024_2026.md` 也提到 2025 文獻把 `VIX1D` 視為值得追蹤的新指標

## 方法

`k1438.py` 不做正式預測估計，而是做三件事：

1. 掃描 `data/intraday/SPY_5min_*.csv`，量化本地 5-min SPY 覆蓋長度
2. 掃描 repo 內檔案與 `paper/garch-x-vix/data/*.csv`，確認是否存在本地 `VIX1D` canonical series
3. 整理已知內部證據與方法論限制，輸出是否能合法啟動正式實驗

## 結果摘要

- 本地 SPY 5-min 檔案存在，覆蓋 2026-01-14 到 2026-06-08，共 100 個 trading days
- 這個長度對 `HAR-RV` pilot 尚可，但 **仍低於 formal OOS 常用的 252 天**
- repo 內雖有多處 `VIX1D` 文字提及，但 **沒有本地 canonical 歷史 time series**
- `paper/garch-x-vix/data/` 的 snapshot CSV 也 **沒有 `VIX1D` 欄位**

## 結論

**K1438 本輪結論是 `BLOCKED_DATA_UNAVAILABLE`。**

這不是失敗，而是符合研究誠實原則的正確收尾：在 `VIX1D` 本地資料未 materialize 前，不能假裝完成 `HAR-RV+VIX1D` 的 source-verifiable experiment。

## 下一步

1. 先建立 canonical 本地 `VIX1D` 歷史資料檔或 snapshot 欄位
2. 補齊後再跑同 target 的 `HAR-RV` / `HAR-RV+VIX` / `HAR-RV+VIX1D`
3. OOS 足夠長後才報 DM / Harvey 顯著性

## 檔案

- `k1438.py` — feasibility audit 腳本
- `k1438_results.json` — audit 輸出

