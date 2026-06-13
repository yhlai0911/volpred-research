# K1482: Green-minus-brown transition-risk 題目的 feasibility audit

## 研究問題

原 queue 題目是：

> Green-minus-brown 波動價差作 transition-risk 情緒指標  
> 用 `ICLN/TAN` 對 `XLE/XOP` 的 RV spread，看氣候政策事件是否帶來 jump，並檢查訊號力。

題目本身合理，但至少要先有兩類 canonical inputs：

1. `ICLN/TAN/XLE/XOP` 的本地價格序列
2. climate / transition policy 事件表

少任一項，都不能誠實做完整研究。

## 本輪目標

這輪先回答：

> 在目前 repo 本地資料與離線環境下，能不能真實完成 green-minus-brown transition-risk study？

## 檢查結果

### 1. 四檔核心 ETF 價格序列本地不存在

本輪檢查了：

- `storage/`
- `experiments/`
- `data/`
- `docs/`

沒有找到可直接 reuse 的本地快取：

- `ICLN`
- `TAN`
- `XLE`
- `XOP`

因此連最基本的 spread：

`mean(RV_green) - mean(RV_brown)`

都無法在離線條件下組起來。

### 2. transition-policy event table 也不存在

repo 內沒有 canonical 事件表，例如：

- `event_date`
- `event_name`
- `event_type`
- `jurisdiction`
- `source_url`

沒有這張表，就不能做可重複的 jump / event-window 檢定，只能手挑幾個新聞日期，這不符合研究誠實。

### 3. 舊 climate / ESG proxy 不能拿來冒充這題

本地雖然有既有相關研究：

- `K148`：named climate events / physical climate shocks
- `K335`：ESG leaders vs laggards 的 broader proxy framing

但它們都**不是**這題要驗證的 `green-minus-brown transition-risk vol spread`。

若直接拿舊 proxy 代替，只是把研究問題換掉，不是把研究做完。

## Verdict

**BLOCKED_ON_DATA**

阻塞點不是計算方法，而是輸入缺口：

1. 缺四檔核心 ETF 價格序列
2. 缺 transition-policy 事件表
3. 既有 climate/ESG artifact 與本題不等價

因此最誠實的完成方式是 feasibility audit，而不是硬湊回歸。

## 若要解鎖這題

至少需要：

### A. 本地價格快取

- `storage/macro/yf_ICLN.csv`
- `storage/macro/yf_TAN.csv`
- `storage/macro/yf_XLE.csv`
- `storage/macro/yf_XOP.csv`

### B. canonical event table

欄位至少包含：

- `event_date`
- `event_name`
- `event_type`
- `jurisdiction`
- `source_url`

## 下一步設計

有了上面兩項之後，才能真正跑：

1. `green-minus-brown` RV spread
2. policy-event jump test
3. lag-respected predictive regression

## 檔案

- `k1482.py`
- `k1482_results.json`
