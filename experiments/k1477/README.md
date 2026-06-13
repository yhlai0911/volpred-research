# K1477: 0DTE 時代的日內 vs 隔夜波動結構轉變

## 研究問題

0DTE 普及後，SPY 的波動結構有沒有從隔夜轉向日內？

更精確地說，本實驗檢驗三件事：

1. `2022-05-02` 前後，SPY 的**隔夜平方報酬**與**日內平方報酬**是否出現結構性位移
2. 用 OHLC 可得的 **Parkinson intraday range variance** 衡量時，日內波動占比是否上升
3. 這個變化是否特別集中在原本沒有固定 SPX 到期的 **星期二 / 星期四**

## 動機

`research_program.md` 的 queue 題目指向一個很具體的 microstructure 假說：

> 0DTE 時代，日內 hedging / gamma 交易增加，SPY 的波動結構可能從「隔夜主導」轉向「日內主導」。

本實驗不直接觀測 options order flow，而是先做 **honest reduced-form test**：

- 用免費可重現的 `yfinance` 日 OHLC
- 把 close-to-close 波動拆成
  - 隔夜：`log(Open_t / Close_{t-1})^2`
  - 日內：`log(Close_t / Open_t)^2`
  - 日內 range proxy：Parkinson variance
- 檢驗 `2022-Q2` 前後是否有可驗證的 shift

## 文獻與背景 anchor

本題先做 literature scan，再設計 reduced-form experiment。這裡只列對本題直接有用的 4 個背景 anchor：

1. Cboe / 市場資料背景：`0DTE` 在 2025 年已超過 SPX option volume 的 60%，並且熱潮起點來自 2022 年完成的 weekday expiries 擴張。  
   - MarketWatch 引述 Cboe 數據（2025-06-02）  
   - https://www.marketwatch.com/story/popular-zero-day-options-saw-record-share-of-trading-volume-in-may-as-retail-traders-piled-in-8ecf7a5c
2. 同一脈絡的量能背景：2025 年 SPX 0DTE 日均量超過 210 萬口，約佔總量 61%。  
   - MarketWatch（2025-07-22）  
   - https://www.marketwatch.com/story/retail-traders-just-cant-quit-risky-zero-day-options-as-trading-volume-booms-68115414
3. 0DTE 研究已進入 ultra-short maturity regime 的專門建模。  
   - Sakuma (2026), *Differential Machine Learning for 0DTE Options with Stochastic Volatility and Jumps*  
   - https://arxiv.org/abs/2603.07600
4. 高頻 SPY 本身存在 intraday structural pattern，但不能自動推論為 0DTE 因果。  
   - Vlasiuk & Smirnov (2025), *Push-response anomalies in high-frequency S&P 500 price series*  
   - https://arxiv.org/abs/2511.06177

另外，知識庫已有兩條直接相關 prior：

- `K38`：0DTE 沒有明顯改變 `VIX-SPY` correlation，但 VIX mean reversion 變快
- `K1452`：隔夜 / 日內 VRP proxy 沒有支持「隔夜風險溢酬為負」的假說

因此 K1477 的定位不是重講 0DTE 熱潮，而是把問題縮到：

> 在最容易重現的 SPY 日資料上，波動的「時間分配」有沒有改變？

## 資料

- **來源**：`yfinance`
- **標的**：`SPY`
- **期間**：`2018-01-02` 至 `2026-06-10`
- **有效樣本**：2,120 個交易日
- **Breakpoint**：`2022-05-02`
- **Seed**：42

## 變數定義

### 核心報酬

- 隔夜報酬：`r_ov,t = log(Open_t / Close_{t-1})`
- 日內報酬：`r_id,t = log(Close_t / Open_t)`

### 波動 proxy

- 隔夜 variance proxy：`r_ov,t^2`
- 日內 variance proxy：`r_id,t^2`
- Parkinson intraday variance：`log(High_t / Low_t)^2 / (4 log 2)`

### 結構比例

- `intraday_share_oc = intraday_sq / (intraday_sq + overnight_sq)`
- `range_share = parkinson_var / (parkinson_var + overnight_sq)`
- `log_ratio_io = log((intraday_sq + eps) / (overnight_sq + eps))`

注意：

1. 這是 **realized proxy**，不是 latent variance
2. `intraday_sq + overnight_sq` 只是兩段 proxy 的和，**不是** close-to-close return square 的恆等分解
3. 本題研究的是「時間分配結構」，不是期權因果識別

## 方法

### Step 1. pre/post summary

對每個變數報告：

- pre / post mean
- pre / post median
- post / pre mean ratio
- Welch t-test
- Mann-Whitney U

### Step 2. exogenous breakpoint regression

對下列變數做 `HAC(5)` robust OLS：

- `overnight_sq`
- `intraday_sq`
- `parkinson_var`
- `intraday_share_oc`
- `range_share`
- `log_ratio_io`

模型：

`y_t = alpha + beta * post_t + error_t`

其中 `post_t = 1[t >= 2022-05-02]`

### Step 3. weekday interaction

因為「新增 weekday expiry」若有額外效果，理應先反映在原本沒有固定同日到期的 `Tue/Thu`，
所以做一個簡化 DiD：

`y_t = alpha + beta1*post_t + beta2*tue_thu_t + beta3*(post_t*tue_thu_t) + error_t`

主要看 `beta3` 是否顯著。

## 主要結果

### 1. 整體方向：不是日內爆量上升，而是隔夜波動明顯壓縮

- 隔夜平方報酬均值：`7.95e-05 -> 4.31e-05`，約 **-45.8%**
- 日內平方報酬均值：`8.67e-05 -> 7.95e-05`，約 **-8.3%**
- Parkinson range variance 均值：`9.84e-05 -> 7.23e-05`，約 **-26.5%**

換句話說，後 0DTE 時代不是「日內波動全面放大」，而是 **兩端都下降，但隔夜降得更快**。

### 2. 因為隔夜壓縮更大，日內占比有中度上升

- `intraday_share_oc`：`0.553 -> 0.584`，Welch `p=0.041`
- `range_share`：`0.695 -> 0.716`，Welch `p=0.067`，Mann-Whitney `p=0.049`
- `log_ratio_io` 均值上升 `+0.355`，Welch `p=0.012`

所以「日內相對更重要」有 evidence，但它主要來自 **相對份額重配**，不是日內 variance level 本身明顯抬升。

### 3. 沒有看到乾淨的 Tue/Thu 額外 uplift

用 `Tue/Thu × post` interaction 測：

- `intraday_share_oc` interaction t = `0.55`, p = `0.584`
- `range_share` interaction t = `-0.13`, p = `0.895`

這不支持「新增 weekday expiries 後，Tue/Thu 特別被日內 gamma / hedging 放大」的簡單版本。

## Verdict

**CONDITIONAL PASS**

本實驗支持一個比較窄、也比較誠實的結論：

1. `2022-Q2` 前後，SPY 的波動結構**確實出現 shift**
2. shift 的主體是 **隔夜波動壓縮快於日內波動**
3. 因此日內占比提高，但不是「日內 variance level 明顯上升」
4. `Tue/Thu` 沒有額外顯著 interaction，所以**不能**把這個 reduced-form shift 直接歸因於 weekday 0DTE expiries

## 限制

1. 只有 `SPY` 單一標的，沒有 `SPX / ES / QQQ` cross-check
2. 只有日 OHLC，沒有期權 order flow、dealer gamma、1-min / 5-min realized vol
3. `2022-05-02` 是外生 policy-style breakpoint，不是 endogenously estimated break
4. reduced-form shift 不等於因果識別

## 下一步

若要把題目往論文級推，下一步應該是：

1. 加入 `SPX / ES / QQQ`
2. 用更高頻資料重做 `open / lunch / close` 分段 RV
3. 直接接 0DTE volume / gamma proxy
4. 用多個候選 breakpoints 做 placebo / sup-Wald robustness

## 檔案

- `k1477.py`
- `k1477_results.json`
- `k1477_rolling_structure.png`
- `k1477_weekday_bars.png`
