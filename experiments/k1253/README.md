# K1253：還原後環境 smoke test（SPY GARCH(1,1) rolling QLIKE）

## 動機
2026-04-18 系統剛從 4/14 備份還原。跑一個最小規範實驗驗證端到端流程（資料下載 → 模型估計 → 評估指標 → 結果 JSON → knowledge 記錄 → 發草稿）是否通暢。**目的是驗證環境，不是研究新發現。**

## 問題描述
SPY 2020–2026 的日報酬，用 GARCH(1,1) 做 rolling 1-step-ahead 條件變異數預測，OOS 區間 2025-01-01 起，QLIKE 均值在常識範圍（約 -6 ~ -4）？

## 方法
- **資料**：yfinance `SPY` Adj Close，2020-01-01 ~ today（2026-04-18 左右），對數報酬 × 100
- **模型**：`arch.arch_model(..., vol="GARCH", p=1, q=1, rescale=False)`
- **評估**：QLIKE = log(σ²_t) + r²_t / σ²_t（以日報酬平方為 realized proxy）
- **防 lookahead**：t 日的預測用 `returns[:t]`，realized 用 `returns[t]`（實質 t-1 資訊預測 t）
- **固定 seed**：`np.random.seed(42)`
- **OOS rolling**：每個 OOS 日重新 fit 一次 full-sample-to-t GARCH

## 預期
- QLIKE 均值約 -5 左右（過去類似實驗的 reference）
- OOS 長度 ~300+ 交易日
- 執行時間 < 10 分鐘
- 產出 `k1253_results.json`

## 非目標（smoke test 不做）
- 不做跨模型比較（GJR / EGARCH / HAR-RV）
- 不做 DM test / MCS
- 不做參數穩定性檢定
- 不發 published 文章（只發草稿）

## 結論
- **QLIKE mean = 0.8815**（std = 2.4041），OOS 323 天
- 資料載入 OK（1580 天，2020-01-03 → 2026-04-17）
- GARCH(1,1) 估計在每個 rolling step 都收斂（無 exception）
- 結果 JSON 正確產出
- **環境完全通暢** — 還原後的程式碼 + yfinance + arch + numpy/pandas 相容
- 本實驗目的是環境驗證，不作為研究結論引用

## 參考
- `.claude/skills/autonomous-research/references/folder_layout.md` §1.2（標準研究型資料夾結構）
- Patton (2011) QLIKE 定義
