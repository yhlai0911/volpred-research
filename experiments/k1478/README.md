# K1478: 槓桿 ETF 機械再平衡與尾盤波動放大

## 研究問題

當 `TQQQ / SQQQ / SSO` 這類槓桿 ETF 在大漲大跌日接近收盤時，被迫做 daily reset，
它們的機械再平衡需求，是否會放大 `QQQ` 的**最後一小時波動**，或帶來**隔夜延續**？

原 queue 題目想測的是：

> `rebalance demand ∝ (k^2-k) × return × AUM`

這在理論上成立，但免費資料的限制是：

1. `yfinance` 沒有歷史 daily AUM
2. 1h intraday 歷史只有約 730 天

因此本實驗採 **honest proxy**：

- underlying：`QQQ`
- LETF basket：`TQQQ`, `SQQQ`, `SSO`
- frequency：`1h`
- sample：`2023-07-17` 到 `2026-06-11`
- size proxy：同日 LETF **交易美元量**，不是歷史 AUM

## 文獻與背景

先做最小文獻掃描，再決定 reduced-form 設計：

1. Hsieh, Chang, Chen (2025), *Compounding Effects in Leveraged ETFs: Beyond the Volatility Drag Paradigm*  
   - arXiv: https://arxiv.org/abs/2504.20116  
   - 重點：LETF 的表現與 daily rebalancing、serial correlation、vol dynamics 緊密相關，不只是「vol drag」
2. Yagi, Maruyama, Mizuta (2020), *Trading Strategies of a Leveraged ETF in a Continuous Double Auction Market Using an Agent-Based Simulation*  
   - arXiv: https://arxiv.org/abs/2010.13036  
   - 重點：LETF rebalancing 可以影響 underlying 的價格形成與波動
3. Thurner, Farmer, Geanakoplos (2009), *Leverage Causes Fat Tails and Clustered Volatility*  
   - arXiv: https://arxiv.org/abs/0908.1555  
   - 重點：槓桿與 forced deleveraging 本身就能放大 tail 與 vol clustering

這三篇給的共同背景是：

- 槓桿與 rebalancing 理論上可能放大市場尾部動態
- 但要在真實市場做識別，得把「市場本來就大漲跌」和「LETF 額外放大」分開

## 資料

- **來源**：`yfinance`
- **標的**：`QQQ`, `TQQQ`, `SQQQ`, `SSO`
- **頻率**：`1h`
- **期間**：`2023-07-17` 至 `2026-06-09`
- **有效交易日**：719 天
- **Seed**：42

## Honest proxy 設計

### Step 1. 每日 `QQQ` 結構變數

由 `1h` bar 聚合成每天：

- `daily_ret`：當日第一根 open 到最後一根 close 的 log return
- `last_hour_ret`：最後一小時 log return
- `last_hour_range_var`：最後一小時 Parkinson variance
- `same_sign_last_hour = sign(daily_ret) * last_hour_ret`
  - 正值代表最後一小時順著當天方向繼續推進
- `overnight_cont = sign(daily_ret) * log(next_open / close_t)`
  - 正值代表收盤後到隔日開盤延續同方向

### Step 2. LETF 機械壓力 proxy

理論上的 rebalancing demand 與 `(k^2-k) * |r| * size` 成正比。  
因歷史 AUM 不可得，本實驗改用同日 LETF 交易美元量：

`pressure_proxy_t = Σ_i |k_i^2-k_i| * |r_QQQ,t| * dollar_volume_i,t`

其中：

- `TQQQ`: `k=+3`
- `SQQQ`: `k=-3`
- `SSO`: `k=+2`

注意：

1. 這是 **交易活躍度 × 市場大波動** 的 reduced-form proxy，不是 fund book 的真實 rebalancing ticket
2. 所以本實驗只能回答「是否有可觀測的尾盤/隔夜關聯」，不能直接做因果宣稱

## 方法

### A. 描述性高壓力 vs 低壓力比較

把 `pressure_proxy` 前 25% 定義為高壓力日，比較：

- `same_sign_last_hour`
- `last_hour_range_var`
- `overnight_cont`

用 Welch t-test。

### B. 控制當日波動後的增量效果

真正的識別關鍵不是「高壓力日是不是比較動」，因為高壓力本身就來自大波動日。  
所以主迴歸是：

`y_t = α + β1 log(pressure_proxy_t) + β2 |daily_ret_t| + ε_t`

`HAC(5)` robust SE。

若 `β1` 仍顯著，才算對「LETF 額外放大」有 reduced-form 支持。

## 主要結果

### 1. 高壓力日的最後一小時確實更躁動

高壓力日（top quartile）相對其餘 75%：

- `same_sign_last_hour`：`0.095%` vs `0.018%`, Welch `p=0.0043`
- `last_hour_range_var`：`1.13e-05` vs `4.77e-06`, Welch `p=3.1e-05`
- `overnight_cont`：沒有顯著差異，Welch `p=0.711`

這表示在描述層次上，大壓力日的尾盤確實更容易順勢推進、最後一小時波動更大。

### 2. 但控制當日絕對報酬後，尾盤放大的主效果消失

主迴歸：

- `same_sign_last_hour ~ log_pressure + |daily_ret|`
  - `β_pressure t = -0.19`, `p = 0.852`
- `last_hour_range_var ~ log_pressure + |daily_ret|`
  - `β_pressure t = -0.25`, `p = 0.801`

也就是說：

> 高壓力日的尾盤更躁動，主要是因為那天本來就是大漲大跌日；  
> 在這個樣本下，沒看到 LETF proxy 對最後一小時有獨立增量放大。

### 3. 隔夜延續反而有一個較弱但顯著的 proxy 關聯

- `overnight_cont ~ log_pressure + |daily_ret|`
  - `β_pressure t = 2.48`, `p = 0.0133`
  - `β_|daily_ret| t = -2.60`, `p = 0.0094`

解讀要非常保守：

- 這只表示高 LETF 活躍 / 高壓力 proxy 的日子，收盤到隔日開盤的**同方向延續**略高
- 不足以證明是 LETF rebalancing 本身造成
- 也可能只是高 attention / 高 news-intensity / 高 overnight information flow 的共同因子

## Verdict

**NULL on the primary tail-vol amplification claim; PRELIMINARY signal on overnight continuation**

更白話地說：

1. **主假說不成立**：在控制 `|daily move|` 後，沒看到 LETF 壓力 proxy 對 `QQQ` 最後一小時波動有獨立放大
2. **次要發現**：隔夜 continuation 有一個弱但顯著的 proxy 關聯，值得後續驗證
3. 因此不能把這題寫成「LETF rebalancing 已證明放大尾盤 vol」

## 限制

1. 歷史 AUM 不可得，只能用 **美元量 proxy**
2. `1h` 歷史只有約 719 天，沒有 10 年長樣本
3. 只看 `QQQ` 一條路徑，沒擴到 `SPY/UPRO/SPXL/SOXL`
4. reduced-form proxy 無法分辨 dealer hedging、macro news、AI 熱點、ETF flow 等共因

## 下一步

若要把這題升級，下一步應該是：

1. 拿到更長的 5-min 或 1-min intraday 歷史
2. 拿真實 historical AUM / shares outstanding / fund flow
3. 對照更多 LETF：`UPRO/SPXL/SOXL/TECL/LABU`
4. 做 event-study 或 IV-style 設計，而不是只靠 contemporaneous proxy

## 檔案

- `k1478.py`
- `k1478_results.json`
- `k1478_pressure_bins.png`
- `k1478_scatter.png`
