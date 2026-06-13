# K1481: 台灣 country-GPR 與台股波動題目的 feasibility audit

## 研究問題

原 queue 題目是：

> 台灣 country-GPR 與台股波動：台海風險的可測價  
> GPR(Taiwan) 月頻 + 0050/台幣波動，檢查領先性與事件窗。

這個題目有研究價值，但先決條件比一般 yfinance 題更嚴格：

1. 要有 **Taiwan country-GPR 原始序列**
2. 要知道 **這個序列何時發布**
3. 才能判定可不可以拿來解釋或預測同月 / 次月波動

沒有第 2 點，最容易犯的就是把事後整理好的月資料拿去解釋同月市場波動，直接踩到 lookahead。

## 本輪目標

這輪不是硬做回歸，而是先誠實回答：

> 在目前 repo 本地資料與離線環境下，能不能真實完成 Taiwan country-GPR 研究？

## 檢查結果

### 1. 本地市場資料夠做 dependent variables

本地可直接讀到：

- `storage/macro/yf_0050.TW.csv`
- `storage/macro/yf_TWDX.csv`

所以：

- `0050.TW` realized volatility
- `USD/TWD` 波動
- 2022-08 / 2024-01 事件窗

這些 dependent variables 都是可做的。

### 2. 缺的是核心自變數：Taiwan country-GPR

repo 內找得到的 GPR 相關檔案，主要是：

- 既有實驗結果
- 非台灣 country-specific 的 GPR 研究 artifact

找不到：

- `Taiwan country-GPR` 月頻原始資料
- 帶 `publication_date` 的 canonical csv/json

所以目前不能誠實做：

- monthly predictive regression
- lead/lag claim
- 「台海風險可提前反映在股市波動」這類敘事

### 3. timing 是這題最大的研究風險

即使明天拿到一份月頻 `Taiwan GPR`，
如果不知道它是：

- 月底發布
- 次月初發布
- 事後回補 / 修訂

就不能把 `month t` 的 GPR 直接拿去解釋 `month t` 的波動。

正確做法應該至少有一個明確規則：

- `signal from publication date, return/vol after publication`
- 或保守用 `t-1` / `next-month` 設計

## 與既有研究的關係

既有本地經驗不是空白：

- `K100`：generic geopolitical proxies 對 vol 增量很弱
- `K446`：broad GPR 指數在一般 US vol 測試裡也偏弱，甚至出現 reversed-causality 訊號

所以 Taiwan 題若要成立，不能只是把舊 proxy 換個標題重跑；必須有真正 Taiwan-specific 的 risk measure。

## Verdict

**BLOCKED_ON_DATA**

這不是說題目錯，而是說：

1. 因變數已就緒
2. 核心自變數缺失
3. 而且缺的不是小細節，是會直接影響 lookahead 合法性的發布時點資訊

因此本輪最誠實的完成方式，就是把資料缺口與 timing gate 寫清楚。

## 若要解鎖這題

至少需要一個 canonical 檔案，例如：

- `taiwan_country_gpr_monthly.csv`

欄位至少包含：

- `period`
- `country`
- `gpr_value`
- `source_url`
- `publication_date`

有了這個檔，下一步才是：

1. `GPR_{t-1}` / publication-lag-respected monthly regression
2. `0050.TW` / `USD-TWD` 波動反應
3. 2022-08 / 2024-01 事件窗補充分析

## 檔案

- `k1481.py`
- `k1481_results.json`
