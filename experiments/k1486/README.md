# K1486: 現貨 BTC ETF 上市對加密 vol「時段結構」題目的 feasibility audit

## 研究問題

原 queue 題目是：

> 現貨 BTC ETF 上市對加密 vol「時段結構」的改變  
> 用 `BTC-USD` 小時資料拆成美股時段 / 非時段 / 週末 RV，檢查 `2024-01` 現貨 ETF 上市前後是否出現結構斷點。

這題的核心不是單純跑一個 break test，而是先確認：

1. 是否有 **24/7 小時級 BTC 資料**
2. 是否能穩定標記 **美股交易時段 / 非時段 / 週末**
3. 是否有足夠的 ETF 上市事件與對照資訊

## 本輪目標

先回答：

> 在目前 repo 本地資料與離線環境下，能不能誠實完成這個 BTC ETF 後時段結構變化研究？

## 檢查結果

### 1. 本地有 BTC 日線，但沒有可直接重用的 BTC 小時級 canonical panel

repo 內可以找到多份 BTC 日線快取，例如：

- `experiments/k1206/data/BTC_USD.csv`
- `experiments/k1186/data/BTC_USD.csv`
- `experiments/k1090/data/BTC-USD.csv`
- `experiments/k1090b/data/BTC-USD.csv`

但這些都是 **daily OHLCV**，不能拆出：

- 美股時段
- 非美股時段
- 週末

也就不能構造題目要求的「時段結構」vol 分解。

### 2. 沒有本地現貨 BTC ETF 價格快取

沒有找到可直接 reuse 的 canonical 本地資料，例如：

- `IBIT`
- `FBTC`
- `ARKB`
- `BITB`

雖然這題的主體是 BTC 本身，不一定非得把 ETF 價格放進主回歸，
但至少要有明確的 ETF 事件與制度背景資料層，才能避免只是在 `2024-01` 生硬切樣本。

### 3. 既有 BTC 實驗碰過 ETF / 結構議題，但不是這題的替代品

例如 `K916` 已經研究過 BTC 與 VIX 的 daily 結構，並且看過 ETF 前後 subsample；
但它的資料是：

- 日線
- 只保留 VIX 可用的 business days

這和本題要問的「24/7 時段分配是否更貼近美股交易時鐘」不是同一件事。

## Verdict

**BLOCKED_ON_DATA**

這題的阻塞點是資料頻率與結構，不是模型：

1. 缺 BTC 24/7 小時級或更細本地 canonical 資料
2. 缺可重建美股時段 / 非時段 / 週末標記的 panel
3. 缺本地 ETF universe / event metadata

## 若要解鎖這題

至少需要：

### A. BTC 小時級價格資料

欄位至少包含：

- `timestamp_utc`
- `open`
- `high`
- `low`
- `close`
- `volume`

### B. 時段分類表或可重建規則

至少要能標記：

- `is_us_cash_session`
- `is_us_non_cash_session`
- `is_weekend`

而且時區規則要固定，避免 DST 漂移。

### C. ETF 事件 / 對照資訊

至少需要：

- `event_date`
- `event_name`
- `event_type`
- `source_url`

若要擴充成更完整的制度性分析，最好再有：

- `IBIT/FBTC/ARKB/BITB` 本地價格或資金流資料

## 下一步

有了上述三項後，才能真正做：

1. 分時段 RV share 分解
2. `2024-01` 前後斷點檢定
3. 平日美股時段 vs 非時段 vs 週末的結構重配分析

## 檔案

- `k1486.py`
- `k1486_results.json`
