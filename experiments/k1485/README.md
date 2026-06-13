# K1485: FINRA off-exchange short volume ratio 題目的 feasibility audit

## 研究問題

原 queue 題目是：

> FINRA off-exchange short volume ratio → 次日 vol  
> 用免費日頻檔檢查 off-exchange short ratio 對次日 realized vol / 極端報酬的預測力，且必須明確 lag。

這題的關鍵不是回歸公式，而是是否真的有 **FINRA off-exchange short volume 原始日資料** 可用。

## 本輪目標

先回答：

> 在目前 repo 本地資料與離線環境下，能不能誠實完成這個 FINRA off-exchange short volume ratio 研究？

## 檢查結果

### 1. 沒有找到 canonical FINRA / TRF / off-exchange short volume 原始表

本地搜尋 `storage/`、`experiments/`、`data/`、`docs/` 後，
沒有找到可直接 reuse 的 canonical 日資料表，像是：

- `date`
- `ticker`
- `short_volume`
- `total_volume`
- `off_exchange_short_ratio`

也沒有可直接指向 FINRA TRF / off-exchange short volume 的本地原始快取。

### 2. 既有 `K186` 與 `K367` 都是 proxy study，不是這題的替代品

repo 內有兩個相近方向：

- `K186`: dark-pool / volume displacement proxy
- `K367`: inverse ETF / VIX-based short-interest proxy

但兩者都在程式與說明中明確承認：

- 沒有真實 FINRA short-volume / TRF 資料
- 只能用價格與成交量 proxy

所以它們不能被包裝成「FINRA off-exchange short volume ratio 已完成」。

### 3. 沒有 canonical target panel 可直接接上

即便先不談 FINRA 原始表，
這題還需要明確定義：

- 哪些 ticker 是研究 universe
- 次日 `RV / extreme return` 如何構造
- 價格資料是否有對齊本地快取

目前 repo 沒有一張已整理好的 canonical merged panel 可以直接跑這題。

## Verdict

**BLOCKED_ON_DATA**

這題的阻塞點是資料建設，不是模型：

1. 缺真正的 FINRA off-exchange short volume 原始日資料
2. 缺 canonical ratio construction table
3. 缺和次日波動 target 對齊的乾淨 panel

## 若要解鎖這題

至少需要：

### A. FINRA off-exchange short volume 日資料表

欄位至少包含：

- `date`
- `ticker`
- `short_volume`
- `short_exempt_volume`（若來源提供）
- `total_volume`
- `source_url`

### B. 可重建 ratio 的處理層

衍生欄位至少包含：

- `off_exchange_short_ratio = short_volume / total_volume`
- `lagged_ratio`

而且必須明確遵守 `t` 訊號對 `t+1` target。

### C. 價格與波動 target panel

至少需要：

- `close`
- `log_return`
- `next_day_realized_vol_proxy`
- `next_day_extreme_return_proxy`

## 下一步

有了上述三項後，才能真正做：

1. `off_exchange_short_ratio_t -> RV_{t+1}` 預測回歸
2. 對極端報酬的 tail-risk 檢定
3. 與 volume / VIX proxy 的增量比較

## 檔案

- `k1485.py`
- `k1485_results.json`
