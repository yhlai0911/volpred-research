# K1479: 單股槓桿 ETF 上市對標的尾盤波動的因果效應

## 研究問題

單股槓桿 ETF 上市後，標的股票本身的「收盤尾端」波動或順勢收尾行為，是否會相對同業變得更強？

queue 題目原本想做：

> `TSLL / NVDL / CONL` 上市日 DiD，測 underlying 的尾盤波動是否被單股槓桿 ETF 放大。

## 誠實 feasibility 結論

這題若嚴格照「上市日前後的最後一小時」來做，**免費資料做不到**。

原因：

1. `TSLL / NVDL / CONL` 的最早交易日分別是：
   - `TSLL`: 2022-08-09
   - `CONL`: 2022-08-10
   - `NVDL`: 2022-12-13
2. 但 `yfinance` 的 `1h` intraday 歷史大約只能回溯約 730 天
3. 因此現在拿到的 `1h` 資料起點大約是 `2023-07-17`
4. 也就是：**上市前 intraday 視窗不存在**

所以如果硬做「launch-day last-hour DiD」，會是偽研究。

## Honest proxy 設計

本實驗改成 **daily event-study DiD**，明確回答較窄的問題：

> 單股槓桿 ETF 上市後，標的股票的日頻尾端 proxy 是否相對同業有可檢出的位移？

### ETF / treated / controls

1. `TSLL` → treated=`TSLA`，controls=`F`, `GM`
2. `NVDL` → treated=`NVDA`，controls=`AMD`, `AVGO`
3. `CONL` → treated=`COIN`，controls=`HOOD`, `MSTR`

控制組不是完美對照，但都屬於最接近的同主題股票群。

## 資料

- **來源**：`yfinance`
- **頻率**：日 OHLC
- **期間**：`2021-01-01` 至 `2026-06-11`
- **事件日**：用 ETF 自身在 `yfinance` 的**首個交易日**定義
- **事件窗**：每個事件前後各 126 個日曆日
- **Seed**：42

## 尾端 proxy 定義

因沒有上市前 1h bar，本實驗使用兩個 daily proxy：

1. `park_var = log(High/Low)^2 / (4 log 2)`  
   - 當日 range-based variance
2. `signed_clv`  
   - `CLV = 2 * (Close-Low)/(High-Low) - 1`
   - 再乘上 `sign(log(Close/Open))`
   - 若股價上漲且收在接近當日高點，或下跌且收在接近低點，`signed_clv` 會較高
   - 這是「順勢收尾」的 daily proxy，不是最後一小時真實波動

另外也報：

3. `abs_ret = |log(Close/Open)|`

## 方法

對每個事件 individually 做：

`y_it = α + β1 treated_i + β2 post_t + β3 treated_i * post_t + ε_it`

其中：

- `treated_i = 1` 代表標的股票
- `post_t = 1` 代表上市後
- `β3` 是 DiD 主係數

`HAC(5)` robust SE。

## 主要結果

### 1. 三個 treated ticker 都沒有顯著的 post-launch differential effect

#### TSLL / TSLA

- `abs_ret`：DiD `p = 0.991`
- `park_var`：DiD `p = 0.234`
- `signed_clv`：DiD `p = 0.529`

#### NVDL / NVDA

- `abs_ret`：DiD `p = 0.963`
- `park_var`：DiD `p = 0.717`
- `signed_clv`：DiD `p = 0.772`

#### CONL / COIN

- `abs_ret`：DiD `p = 0.193`
- `park_var`：DiD `p = 0.490`
- `signed_clv`：DiD `p = 0.894`

### 2. treated 本身常常比 controls 更 volatile，但那不是上市造成的新增跳變

例如：

- `TSLA` 本來就比 `F/GM` 更 volatile
- `NVDA` 本來就比 `AMD/AVGO` 更會走趨勢
- `COIN` 本來就比 `HOOD/MSTR` 更高波動

DiD 的問題不是誰比較 volatile，而是：

> 上市後，treated 相對 control 的差距有沒有額外放大？

答案在這組資料下是：**沒有。**

## Verdict

**NULL**

在可重現的免費資料條件下：

1. 無法誠實做「上市前後 last-hour intraday DiD」
2. 改用 daily honest-proxy event-study 後
3. `TSLA / NVDA / COIN` 都沒有顯著的 post-launch differential tail-vol effect

因此目前不能支持：

> 「單股槓桿 ETF 上市會明顯放大標的股票的尾盤波動」

## 限制

1. 最關鍵限制：**缺上市前 intraday data**
2. `signed_clv` 只是 daily close-end proxy，不是真正 last-hour variance
3. 控制組是近似同業，不是完美 synthetic control
4. 沒有真實 ETF AUM / flow / dealer hedge inventory

## 下一步

如果要把這題升級成真正的 causal microstructure paper，需要：

1. 更長的 5-min / 1-min intraday 歷史
2. 真實 ETF AUM / shares outstanding / primary flow
3. 更細的上市事件時間戳與 placebo launch dates
4. 更正式的 synthetic control 或 staggered DiD

## 檔案

- `k1479.py`
- `k1479_results.json`
- `k1479_did_coefficients.png`
