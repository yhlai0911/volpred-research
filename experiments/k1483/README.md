# K1483: 極端高溫/颶風對保險與公用 ETF 的 vol event study feasibility audit

## 研究問題

原 queue 題目是：

> 極端高溫/颶風對保險與公用 ETF 的 vol event study  
> 用 NOAA 事件日期 + `KIE/KBWP/XLU` 的 RV 做 event study，並看 damage / severity 的 dose-response。

這題和既有 `K148` 有血緣，但不是同一題：

- `K148`：`SPY/XLE/DBA/KIE/USO` + 手工命名災害清單
- 本題：`KIE/KBWP/XLU` + NOAA canonical event table + 更明確的 physical-climate sector design

## 本輪目標

先回答：

> 在目前 repo 本地資料與離線環境下，能不能誠實完成這個 ETF event study？

## 檢查結果

### 1. 本地沒有 `KIE/KBWP/XLU` 價格快取

本輪檢查了：

- `storage/`
- `experiments/`
- `data/`
- `docs/`

沒有找到可直接 reuse 的本地價格快取：

- `KIE`
- `KBWP`
- `XLU`

因此連最基本的 sector RV panel 都組不起來。

### 2. repo 內也沒有 canonical NOAA event table

雖然 `K148` 的 code 內有一份手工整理的 named-disaster 清單，
但它不是獨立的 canonical input，也沒有被整理成正式資料表。

本題若要誠實重做，至少需要：

- `event_date`
- `event_name`
- `event_category`
- `damage_usd_billion`
- `source_url`

否則只是在沿用舊研究的手工清單，無法算真正可重複的資料建設。

### 3. 直接重跑 `K148` 不能算完成本題

原因有三個：

1. 目標 ETF 不同
2. event table 不同
3. `K148` 是舊的 hand-curated 設計，不是這題要求的 canonical NOAA design

所以不能把 `K148` rerun 當成這題已完成。

## Verdict

**BLOCKED_ON_DATA**

阻塞點很明確：

1. 缺 `KIE/KBWP/XLU` 本地價格序列
2. 缺 canonical NOAA event table
3. 既有 `K148` 只能當方法前例，不能直接替代

## 若要解鎖這題

至少需要：

### A. 本地 ETF 價格快取

- `storage/macro/yf_KIE.csv`
- `storage/macro/yf_KBWP.csv`
- `storage/macro/yf_XLU.csv`

### B. NOAA-style event table

欄位至少包含：

- `event_date`
- `event_name`
- `event_category`
- `damage_usd_billion`
- `source_url`

## 下一步

有了這兩項之後，才能真正做：

1. `KIE/KBWP/XLU` 的 RV event study
2. heat / hurricane / flood 分類比較
3. damage/severity dose-response

## 檔案

- `k1483.py`
- `k1483_results.json`
