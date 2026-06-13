# K1484: 颱風登陸與台股波動題目的 feasibility audit

## 研究問題

原 queue 題目是：

> 颱風登陸與台股波動：颱風假的 vol 機制  
> 用 CWB 警報 / 登陸資料 + 台股 / 台指期，檢查停市後復市日的 gap / vol，並和一般連假區分。

這題的關鍵不是回歸公式，而是資料表：

1. 颱風事件表
2. 市場停市 / 復市表
3. 台股與台指期價格序列

## 本輪目標

先回答：

> 在目前 repo 本地資料與離線環境下，能不能誠實完成這個台灣颱風假波動研究？

## 檢查結果

### 1. 本地只有 `0050.TW`，沒有完整市場層級序列

本地可直接確認：

- `storage/macro/yf_0050.TW.csv`

但沒有找到可直接 reuse 的 canonical：

- `TAIEX`
- `TXF / 台指期`

所以如果硬做，會退化成「只有 0050 ETF」的局部版本，這和原題設計不同。

### 2. 沒有 canonical 颱風假事件表

repo 內沒有正式資料表記錄：

- 哪一天颱風登陸
- 哪一天發布警報
- 哪一天台股停市
- 哪一天復市

沒有這張表，就不能區分：

- 颱風本身
- 停市機制
- 復市 gap

### 3. 也沒有一般連假對照表

原題要求把颱風假和一般長假分開看，
但本地沒有結構化 holiday classification table，
因此 control group 也還沒定義。

## Verdict

**BLOCKED_ON_DATA**

這題的阻塞點是資料建設，不是方法：

1. 缺 canonical typhoon-holiday event table
2. 缺 TAIEX / TXF 本地價格序列
3. 缺一般長假對照表

## 若要解鎖這題

至少需要：

### A. 颱風假事件表

欄位至少包含：

- `event_date`
- `event_name`
- `landfall_date`
- `market_closed`
- `reopen_date`
- `source_url`

### B. 市場價格快取

- `storage/macro/yf_0050.TW.csv`
- `storage/macro/yf_TAIEX.csv` 或等價現貨指數資料
- `storage/macro/yf_TXF.csv` 或等價台指期資料

### C. holiday control table

- `date`
- `holiday_type`
- `is_typhoon_related`

## 下一步

有了上述三項後，才能真正做：

1. 復市日 gap / RV 檢定
2. 颱風假 vs 一般連假比較
3. ETF / 現貨 / 期貨三層機制拆解

## 檔案

- `k1484.py`
- `k1484_results.json`
