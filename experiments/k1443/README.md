# K1443 — BTC / ETH vs SPY 波動 spillover（SPY 交易日 panel）

- Experiment ID: `K1443`
- Status: complete
- Created: 2026-06-10
- Task source: `research_spillover_btc_usd_eth_usd_realized_vol_spy_vol_s`

## 問題

在 `BTC-USD / ETH-USD / SPY` 之間，crypto 波動到底有沒有穩健地**領先**
美股波動？還是只是危機期一起震、但沒有可辨識的 lead-lag？

這題用本地快取日資料，在 **SPY 交易日 panel** 上做雙向 spillover 檢定：

1. `BTC → SPY` 是否存在波動 Granger 因果？
2. `ETH → SPY` 是否存在波動 Granger 因果？
3. 反方向 `SPY → crypto` 是否更強？
4. 若把 BTC / ETH 一起放進條件 VAR，crypto 對 SPY 還有沒有增量資訊？
5. 動態相關（DCC）是高但穩，還是會大幅 regime-shift？

## 文獻前置

本題先對齊 3 條文獻脈絡：

1. **Engle (2002)**：Dynamic Conditional Correlation (DCC) 提供可 tractable 的動態相關框架，適合做 crypto–equity conditional correlation 描述。
2. **Diebold and Yilmaz (2012)**：volatility spillover 的方向性測量提醒我們，**共動** 和 **誰領先誰** 是不同問題，不能只看相關係數。
3. **Ampountolas (2023, DCC-EGARCH crypto/stock volatility study)**：危機期 crypto 與股市的相關與 spillover 會升高，但是否形成穩健的日頻 lead-lag，仍需逐市場驗證。

本研究的可反駁假說是：
若 crypto 真的是 equity vol 的領先市場，那至少在日頻主規格下，應看到
`BTC/ETH → SPY` 的 Granger 顯著，且方向不弱於 `SPY → crypto`。

## 與既有 K 的差異

- **K1437**：USD/TWD vs TWII，FX vol → TWII vol 的 spillover
- **K1441**：EM ETF 內部的共同 vol factor
- **K1443**：改成 **crypto vs US equity**，聚焦「誰領先誰」而不是只看共同因子

## 資料

- 本地快取，**不重抓 yfinance**
- `BTC-USD`: `experiments/k1206/data/BTC_USD.csv`
- `ETH-USD`: `experiments/k1090b/data/ETH-USD.csv`
- `SPY`: `experiments/k1406/data/SPY.csv`

### 樣本

- Panel 定義：**SPY trading days**
- 樣本期：**2018-01-02 → 2026-04-16**
- Price observations: **2,083**

### 對齊方式

BTC / ETH 是 7 天交易，SPY 只有美股交易日。

本實驗不把 SPY 強行補成週末 0 return，也不把 crypto 日資料直接 inner join 成「只有平日」後再當同步日報酬；
而是採用：

- **在 SPY 日期上抽取 BTC / ETH 價格**
- 因此 crypto 報酬是 **adjacent-SPY-day return**

這代表週末 crypto move 會自然併進週一 interval。這不是 lookahead，
但 interpretation 必須寫清楚：它測的是 **「相鄰 SPY 交易日之間」的 crypto 波動**。

## 方法

## 主規格：daily volatility shock proxy

因為只有日頻 close 資料，主檢定不用 intraday realized vol，而用：

- `log(r_t^2 + 1e-10)`

理由：

1. 它是 close-to-close volatility shock proxy
2. 避免 21d rolling RV 的重疊視窗自相關污染 headline inference
3. 適合做日頻 VAR / Granger lead-lag 問題

## 描述性 / robustness

- `21d realized vol = sqrt(sum_{i=t-20}^t r_i^2 * 252/21)`

這只是 descriptive 與 robustness，不拿來當主 headline。

## 模型

1. **Pairwise VAR / Granger**
   - `BTC logrv1 ↔ SPY logrv1`
   - `ETH logrv1 ↔ SPY logrv1`
   - lag max = 5，BIC 選 lag
2. **Conditional VAR**
   - 三變數 `BTC / ETH / SPY logrv1`
   - 檢查 `BTC`、`ETH` 對 `SPY` 的 conditional causality
3. **Pairwise DCC-GARCH**
   - `BTC-SPY`
   - `ETH-SPY`
   - 為控制計算量，DCC 僅用最近 **1,000** 個 SPY trading days
   - 3 個起始點 multistart，seed=42

## Lookahead guard

- 所有 Granger / VAR 都只用 lagged values
- 沒有 same-day forward info
- 沒有用 future window 生成訊號
- DCC recursion 只用 `t-1` 標準化殘差

## 主要結果

## 1. 主規格下，看不到穩健的 crypto 領先 SPY

### BTC vs SPY（`log(r²)`）

- `BTC → SPY`: **p = 0.282**
- `SPY → BTC`: **p = 0.160**

### ETH vs SPY（`log(r²)`）

- `ETH → SPY`: **p = 0.225**
- `SPY → ETH`: **p = 0.094**

方向上，只有 `SPY → ETH` 稍微接近 10% 邊界，但仍未過 5%。

## 2. 把 BTC 與 ETH 一起放進條件 VAR，crypto 對 SPY 的增量資訊仍然不顯著

三變數 conditional VAR（BIC lag = 3）：

- `BTC → SPY | ETH`: **p = 0.440**
- `ETH → SPY | BTC`: **p = 0.621**
- `BTC+ETH joint → SPY`: **p = 0.511**

這表示：

- 就日頻 volatility shock proxy 而言，
- **BTC / ETH 沒有對 SPY 提供穩健的增量 spillover 訊號**

## 3. DCC 顯示的是「持續共動」，不是「清楚領先」

最近 1,000 個 SPY trading days 的 pairwise DCC：

### BTC / SPY

- mean ρ = **0.361**
- p10 / p90 = **0.179 / 0.514**
- max = **0.581**

### ETH / SPY

- mean ρ = **0.376**
- p10 / p90 = **0.210 / 0.502**
- max = **0.576**

這說明 crypto 與 SPY 的條件相關並不低，而且 ETH 略高於 BTC，
但 **高動態相關 ≠ 有方向性的日頻 spillover**。

## 4. 21 日 rolling RV robustness 會跑出「雙向都顯著」，但不適合做 headline

若改看 `21d RV`：

- `BTC → SPY`: **p = 2.46e-08**
- `SPY → BTC`: **p = 1.86e-07**
- `ETH → SPY`: **p = 1.52e-07**
- `SPY → ETH`: **p = 3.57e-06**

表面上看起來是「雙向強 spillover」。

但這裡必須保守：

- 21d RV 是高度 **overlapping rolling window**
- 會機械性放大 persistence 與共動
- 很容易把「一起慢慢升、一起慢慢降」誤讀成 lead-lag

所以本題的主裁決仍以 `log(r²)` 規格為準。

## Verdict

**CONDITIONAL_PASS**

理由：

1. **實作層面通過**：時間對齊清楚、無 lookahead、seed 固定、結果可重跑。
2. **研究誠實通過**：沒有把 21d RV 的表面雙向顯著拿來硬說成「crypto 領先股市」。
3. **主結論是 honest null / mixed**：
   - 日頻主規格看不到穩健 `crypto → SPY`
   - `SPY → ETH` 僅接近 10% 邊界
   - 條件 VAR 也不支持 crypto 對 SPY 有增量 spillover

最誠實的結論是：

- **crypto 與 SPY 存在中度且持續的條件相關**
- 但在本樣本與本日頻規格下，**沒有足夠證據說 BTC / ETH 穩健領先 SPY 波動**
- 若有 lead-lag，方向更像是 **弱的 SPY → ETH**，而不是 crypto → equity

## 研究意涵

1. **共動與領先要分開**：看到 DCC 高，不代表可以做日頻 spillover alpha claim。
2. **overlapping RV 很危險**：rolling RV 很容易把同步 persistence 包裝成雙向因果。
3. **crypto 作為風險情緒溫度計是合理的；作為 SPY vol 的日頻領先器，證據不足。**

## 限制

1. 主資料是日頻 close，不是 intraday realized vol；因此 headline 只能說 daily vol shock proxy。
2. SPY trading-day panel 會把週末 crypto move 併到週一 interval，這是合理對齊，但 interpretation 不是 calendar-day synchronous spillover。
3. DCC 為計算可行性只用最近 1,000 個 SPY trading days，定位為 descriptive correlation，不是 full-sample structural estimate。
4. 沒有做 structural-break / subperiod split；若只看 COVID、post-ETF、2022 緊縮期，結果可能不同。

## 圖表

- `figures/rv21_timeseries.png`
- `figures/dcc_correlations.png`

## 三件套

- `k1443.py`
- `k1443_results.json`
- `README.md`
