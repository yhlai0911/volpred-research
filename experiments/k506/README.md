# k506

- Experiment ID: `k506`
- Status: retry_in_progress
- Last updated: 2026-06-07

## 問題描述

驗證 `EWT / 0050.TW` 21 日 realized volatility ratio，是否能作為台股 VT (`8.63 / VIX`) 的額外 overlay，在 5 段不重疊兩年期 cross-OOS 中穩定改善淨 Sharpe。

## 本輪修正目標（K506_retry_lookahead_fix）

1. 修正 lookahead bias：所有調倉訊號都必須用 `t-1` 資訊決定 `t` 報酬。
2. 統一台股 ETF 往返成本為 `0.001855`（18.55bp，K625 更正後口徑）。
3. 對 5 段 + pooled 共 6 次 DM 檢定加上 Bonferroni 與 BH 校正。
4. 禁止混用 K505 的數字；K506 的對外數字只能來自本實驗 `results.json`。

## 目前狀態

- `k506_ewt_volspread_cross_oos.py` 已改為：
  - `vix_signal = vix.shift(1)`
  - `vol_ratio_signal = vol_ratio.shift(1)`
  - 輸出 Bonferroni / Benjamini-Hochberg 校正後的 p-value
  - 優先讀本地 cache（`data/cache/price_cache.db`）
- **尚未重跑成功**：目前 workspace 有 `0050.TW` 與 `^VIX` 本地 cache，但缺少 2010-2021 的 `EWT` 原始價格；外網也被 sandbox 擋住，無法從 yfinance 補抓。
- 現有 `k506_ewt_volspread_cross_oos_results.json` 為 **舊版失效輸出**，不可再引用於文章或知識庫。

## 資料來源需求

- `0050.TW`: 本地 SQLite cache `data/cache/price_cache.db`
- `^VIX`: 本地 SQLite cache `data/cache/price_cache.db`
- `EWT`: 需要 2010-01-01 至 2021-12-31 的日資料；目前 repo 只找到 `experiments/k1090/data/EWT.csv`（2018-01-02 至 2024-12-30），不足以支撐五段 OOS。

## 下一步

1. 補齊 `EWT` 2010-2021 本地快取。
2. 重跑 `python experiments/k506/k506_ewt_volspread_cross_oos.py`。
3. 由 Codex 再做一次 source-code-level review，確認 results/README/文章口徑一致後，才允許重新發布更正版文章。
