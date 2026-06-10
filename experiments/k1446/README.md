# K1446 — Factor ETF Volatility and Downside-Risk Diagnostics

- **K id**: K1446
- **Status**: completed
- **Created**: 2026-06-10
- **Task source**: `research_factor_etf_mtum_qual_usmv_min_vol_vlue_realized`

## Question

用 `yfinance` 可直接取得的 4 檔美股 factor ETF：

- `MTUM`（momentum）
- `QUAL`（quality）
- `USMV`（minimum volatility）
- `VLUE`（value）

再加 `SPY` 當 broad-market benchmark，比較它們在**共同樣本**中的：

1. 全樣本 realized volatility
2. downside risk
3. 不重疊 21 日 block 下的風險差異

核心問題是：**USMV 這檔 min-vol ETF，風險真的比其他 factor ETF 和 SPY 更低嗎？**

## Motivation

既有專案結論多集中在「factor ETF 放進 VT / timing overlay 後是否帶來 alpha」，例如：

- **K89**：MTUM / VLUE / QUAL / USMV 替換 SPY 後，VT 框架下沒有顯著改善
- **K566**：factor timing + VT 也屬 NULL，且 factor ETFs 與 SPY 高度相關
- **K876**：MTUM crash risk 與 VIX 關聯有限，動能 ETF 本身風險特徵值得獨立看

但上面這些 K 的焦點不是「單純風險輪廓診斷」。K1446 改問更基礎的描述性問題：

- min-vol ETF 的「低波動」名號，在共同樣本裡是否真的成立？
- 如果成立，是只反映在年化 vol，還是連 downside deviation / VaR / ES / MDD 都一致較低？

## Related Literature

這次只做簡短文獻 preamble，不做完整回顧。設計動機主要對齊 3 條文獻線：

1. **Blitz & van Vliet (2007), The Volatility Effect**  
   低波動 / 低風險資產未必帶來較低報酬，是 low-vol anomaly 的經典起點。

2. **Frazzini & Pedersen (2014), Betting Against Beta**  
   提供低 beta / 低風險資產可能有超額表現的結構性解釋：槓桿約束與需求失衡。

3. **Baker, Bradley & Wurgler (2011), Benchmarks as Limits to Arbitrage**  
   說明 benchmark pressure 與受限套利，如何支撐 low-vol anomaly 持續存在。

K1446 不是在驗證 anomaly 是否帶來 alpha，而是先做**可交易 ETF 層級的風險輪廓診斷**。

## Data

- Source: `yfinance`
- Tickers: `MTUM`, `QUAL`, `USMV`, `VLUE`, `SPY`
- Fetch period: 2010-01-01 → 2026-06-09
- 各自可得起點：
  - `MTUM`: 2013-04-19
  - `QUAL`: 2013-07-19
  - `USMV`: 2011-10-21
  - `VLUE`: 2013-04-19
  - `SPY`: 2010-01-05
- **共同樣本**（公平比較用）：2013-07-19 → 2026-06-09，`n=3242`

## Method

### Return definition

- 使用 adjusted close 計算 daily log return
- 無預測 setup，純 descriptive comparison

### Full-sample risk metrics

共同樣本上對每個資產計算：

- 年化報酬
- 年化波動率
- downside deviation
- 歷史 5% VaR
- 歷史 5% Expected Shortfall
- max drawdown
- 負報酬日占比
- worst day

### Fair-comparison design

這次**不用 rolling window 直接做顯著性檢定**，避免 overlap-induced pseudo-significance。

改用：

- **non-overlapping 21-trading-day blocks**
- 每個 block 計算：
  - annualized realized vol
  - annualized downside deviation

然後對 `USMV` vs 其餘 4 個對手做配對比較。

### Statistical tests

對每個 peer、每種 risk metric 做：

1. **paired Wilcoxon signed-rank**
   - alternative = `peer risk > USMV risk`

2. **bootstrap mean-difference CI**
   - reps = 5000
   - seed = 42

3. **Bonferroni correction**
   - 4 peers × 2 metrics = 8 tests
   - `alpha = 0.05 / 8 = 0.00625`

## Main Results

### Full-sample risk level

| Asset | Ann vol % | Downside dev % | MDD % |
|---|---:|---:|---:|
| MTUM | 19.90 | 14.35 | -34.08 |
| QUAL | 17.17 | 12.26 | -34.06 |
| **USMV** | **13.84** | **10.02** | **-33.10** |
| VLUE | 18.75 | 13.51 | -39.47 |
| SPY | 17.05 | 12.29 | -33.72 |

**USMV 是 5 檔中全樣本年化 vol 最低、downside deviation 最低、MDD 也最低。**

### Block-level paired tests

對 `USMV` 的 4 個對手，兩類 block risk test **全部通過** Bonferroni：

- `rv_pass = 4 / 4`
- `downside_dev_pass = 4 / 4`

代表在不重疊 21 日 block 這個較公平的設計下：

- `MTUM` 的 block realized vol 與 downside risk 顯著高於 `USMV`
- `QUAL` 顯著高於 `USMV`
- `VLUE` 顯著高於 `USMV`
- `SPY` 也顯著高於 `USMV`

### Magnitude

一些有代表性的平均差距（peer − USMV）：

- `MTUM` minus `USMV` block RV mean diff = **+0.0581**
- `QUAL` minus `USMV` block RV mean diff = **+0.0320**
- `VLUE` minus `USMV` block RV mean diff = **+0.0459**
- `SPY` minus `USMV` block RV mean diff = **+0.0301**

downside deviation 的差距也全部為正，bootstrap `P(peer > USMV) = 1.0`。

## Verdict

**PASS**

理由不是「USMV 報酬最好」，而是這個實驗要回答的問題比較窄：

> USMV 的低風險定位，在共同樣本與公平 block 設計下，是否真的成立？

對這個問題，答案是 **yes**：

- 全樣本年化 vol 最低
- 全樣本 downside deviation 最低
- 全樣本 MDD 最低
- 對 4 個對手的 block-level realized vol / downside risk 檢定全部通過 Bonferroni

因此這次的 `PASS` 是**描述性風險輪廓確認**，不是 alpha / timing / allocation 的 PASS。

## Interpretation

K1446 和 K89 / K566 並不衝突。

- **K89 / K566** 說的是：把 factor ETF 放進 VT / timing 架構，**不會自動帶來 alpha**
- **K1446** 說的是：如果只看風險輪廓，`USMV` 的確比 `MTUM / QUAL / VLUE / SPY` 更 defensive

也就是：

- `USMV` 可以是 **lower-risk equity vehicle**
- 但 **lower-risk 不等於 higher-alpha strategy**

這是兩個不同命題。

## Honest Limits

- 這是 **ETF 層級 descriptive comparison**，不是 underlying stock-level factor premium test
- 共同樣本從 `2013-07-19` 開始，早於此的 SPY / USMV 歷史沒有納入公平比較
- block size 固定 21 日；若改成 63 日或月曆月，顯著性大小可能不同
- 沒有做交易成本、容量、holding-period utility，也沒有做 alpha regression
- `yfinance` 僅作可重現公開資料源，非 CRSP / official index return

## Files

- `k1446.py`
- `k1446_results.json`
- `fig1_rolling_vol_63d.png`
- `fig2_full_sample_risk_bars.png`
- `fig3_block_rv_usmv_vs_peers.png`

## Reproduce

```bash
uv run python experiments/k1446/k1446.py
```

