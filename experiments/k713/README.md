# K713 Reconstruction — SPY/GLD 加入 TLT 的靜態配置掃描

- Experiment ID: `k713`
- Status: reconstructed
- Reconstructed At: 2026-06-13
- Trigger task: `experiment_reconstruct_k713_tlt_allocation`
- Linked article: `mile_1b56cf6b`

## 問題描述

`mile_1b56cf6b` 使用了舊版 K713 的保留結果，但原始 repo 只留下摘要 JSON 與兩張圖，沒有 `k713.py`、沒有樣本期間、也沒有再平衡規則。這使得文章數字雖然能對上 retained JSON，卻無法通過目前的三件套可重現標準。

本次任務不是硬猜舊腳本，而是把 K713 重建成可重跑、可審計的 canonical experiment。

## 動機

- 補齊 `README + script + results` 三件套
- 釐清 legacy retained numbers 與可重現 rerun 之間的差異
- 確認「20% 到 25% TLT 是較平衡區間」是否在透明口徑下仍成立
- 為後續文章 errata / paper-grade 使用提供可驗證來源

## 實驗前檢查

- 已讀 `docs/error_log.md` 的 2026-06-13 K713 incident
- 已確認現況：git history 只有 `f84d76a7` summary + JSON，沒有原始腳本可回收
- 相關文獻 / 方法基準：
  - Markowitz (1952), *Portfolio Selection*
  - DeMiguel, Garlappi, Uppal (2009), *Optimal Versus Naive Diversification*
  - Asness, Frazzini, Pedersen (2012), *Leverage Aversion and Risk Parity*

## 方法

### 資料

- Source: `yfinance` adjusted close
- Assets: `SPY`, `GLD`, `TLT`
- Requested start: `2006-01-01`
- Effective sample: 由三資產共同可得資料決定；實際日期寫入 `k713_results.json`

### 組合設計

- 基準組合：`50/50 SPY + GLD`
- TLT 權重掃描：`0%, 5%, 10%, 15%, 20%, 25%, 30%`
- 每個 TLT 權重下，其餘權重平均分給 SPY / GLD
  - 例：25% TLT = `37.5% SPY / 37.5% GLD / 25% TLT`

### 再平衡口徑

- Annual rebalance：每年第一個交易日回到目標權重
- 年內允許自然 drift
- 無訊號、無預測、無 same-day timing 問題

### 指標定義

- `sharpe`: daily mean / daily std * `sqrt(252)`，`rf=0`
- `cagr`: compounded wealth CAGR
- `mdd`: compounded wealth curve 的標準 maximum drawdown
- `legacy_like_mdd`: 額外保留 cumulative-return drawdown，僅用來比對舊 artifact 可能採用的口徑

## 輸出檔案

- Script: [`experiments/k713/k713.py`](/Users/yhlai0911/Desktop/volpred-research/experiments/k713/k713.py)
- Results: [`experiments/k713/k713_results.json`](/Users/yhlai0911/Desktop/volpred-research/experiments/k713/k713_results.json)
- Figures:
  - [`experiments/k713/k713_tlt_peak.png`](/Users/yhlai0911/Desktop/volpred-research/experiments/k713/k713_tlt_peak.png)
  - [`experiments/k713/k713_return_vs_drawdown.png`](/Users/yhlai0911/Desktop/volpred-research/experiments/k713/k713_return_vs_drawdown.png)

## 主要發現

- 在可重現 annual-rebalance 口徑下，`25% TLT` 仍是 Sharpe 峰值附近
- 報酬與風險交換方向未變：
  - 加 TLT 會壓低 CAGR
  - 同時改善 drawdown
- 但 legacy retained JSON 的 MDD 與重建後標準 MDD 不一致，顯示舊 artifact 很可能混用了不同 drawdown 定義

## 局限

- 這不是 byte-perfect legacy reproduction；原始腳本不存在，無法驗證舊版是否用同一個 sample cut、同一個 drawdown 定義或其他隱含處理
- 尚未補做 cross-OOS / sensitivity / 2022 rate-risk 分段檢查，因此目前只是一個可重現的 descriptive reconstruction

## 結論

K713 現已回到「可重跑、可審計」狀態，但結論強度需要跟著收斂：可以說「在這個透明口徑下，20% 到 25% TLT 仍是較平衡區間」，不能再把舊版 retained JSON 當成無條件最終答案。若 reader-facing 文章要保留精確數字，應同步標示 reconstructed metric 與 legacy artifact 的差異。
