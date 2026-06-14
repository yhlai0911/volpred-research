# research_quantile_connectedness_var_yfinance_etf_rv_quant

## 動機

研究 backlog 題目要求檢驗：跨資產波動率連結度在尾部 quantile 是否高於中位數，並找出誰是尾部波動的淨傳染源。

本實驗和既有工作不同：

- `K628b` 是 mean-VAR / Diebold-Yilmaz level connectedness。
- `K1491` 是 crypto vol-of-vol tail spillover 修正版，重點在 Granger / predictor 顯著性。
- 本題改用 QVAR-style quantile connectedness，比較 `tau=0.95` 與 `tau=0.50` 的 generalized FEVD network。

## 前置規則

已讀：

- `docs/error_log.md`
- `.claude/skills/autonomous-research/references/experiment-preamble.md`
- `research_program.md`
- `storage/memory/knowledge.json` 中 connectedness / CoVaR / spillover 相關條目

防錯重點：

- `BTC-USD` 有週末交易，ETF 沒有。本實驗只保留 ETF 共同交易日，BTC 用該日期可得價格對齊，避免把 ETF 價格 forward-fill 到週末造成 0 報酬。
- yfinance 日頻資料無法產生真正 5-min realized volatility，本文只使用 5 日 rolling squared-return 的低頻 RV proxy。
- Diebold-Yilmaz / FEVD 類 directional connectedness 是 network centrality diagnostic，不是結構因果。

## 文獻前置

1. Ando, Greenwood-Nimmo, Shin (2022), *Quantile Connectedness: Modeling Tail Behavior in the Topology of Financial Networks*, Management Science. DOI: `10.1287/mnsc.2021.3984`
2. Diebold and Yilmaz (2009), *Measuring Financial Asset Return and Volatility Spillovers, with Application to Global Equity Markets*, NBER Working Paper `w13811`
3. Barunik and Krehlik (2018), *Measuring the Frequency Dynamics of Financial Connectedness and Systemic Risk*, Journal of Financial Econometrics. DOI: `10.1093/jjfinec/nby001`
4. Federal Reserve Bank of Boston (2024), *Scenario-based Quantile Connectedness of the U.S. Interbank System*

## 資料

- 來源：`yfinance adjusted close`
- 期間：`2015-01-02` 到 `2026-06-12`
- 價格樣本：`2878` 個 ETF 共同交易日
- log RV proxy 樣本：`2873`
- 資產：
  - `SPY`：美股
  - `TLT`：美債
  - `GLD`：黃金
  - `USO`：原油
  - `BTC`：`BTC-USD`，長樣本 crypto proxy，不是 ETF

## 方法

1. 下載 adjusted close。
2. 只保留 `SPY/TLT/GLD/USO` 共同交易日，BTC 對齊到同一交易日面板。
3. 計算 log return。
4. 以 `5` 交易日 rolling sum of squared log returns 作 RV proxy，再取 log。
5. 對 log RV panel 標準化。
6. 對 `tau=0.05/0.50/0.95` 分別估計 equation-by-equation Quantile VAR(1)。
7. 用 QVAR coefficient matrix 與 residual covariance 做 generalized FEVD。
8. 產生 total connectedness、to/from/net connectedness、pairwise FEVD table。
9. rolling window：
  - window = `756` trading days
  - step = `42` trading days
  - FEVD horizon = `10`
10. 正式檢定：
  - `TCI(tau=0.95) - TCI(tau=0.50)` 的 HAC mean test
  - moving-block bootstrap，seed=`42`，reps=`1000`，block=`6`
  - 高 SPY RV windows vs 非高 SPY RV windows 的 Welch test

## 主要結果

### Full Sample Total Connectedness

| Quantile | TCI |
|---:|---:|
| `0.05` | `17.59%` |
| `0.50` | `6.87%` |
| `0.95` | `14.67%` |

### Rolling Test

- `tau=0.95 - tau=0.50` 平均差：`+8.30 pp`
- HAC t-stat：`8.95`
- p-value：`5.86e-12`
- Moving-block bootstrap 95% CI：`[6.46, 10.46] pp`
- bootstrap `P(mean > 0)`：`1.00`

### Crisis Specificity

用 rolling window 的 SPY log RV 平均值 top quartile 定義高波動 windows。

- 高 SPY 波動 windows：`13`
- 非高 SPY 波動 windows：`38`
- 高波動 mean gap：`7.70 pp`
- 非高波動 mean gap：`8.50 pp`
- Welch t-stat：`-0.87`
- p-value：`0.390`

結論：upper-tail connectedness 明顯高於 median connectedness，但這個 gap 不是高 SPY 波動期才特別放大的現象。

### Upper-Tail Net Roles

| Asset | Net connectedness at tau=0.95 |
|---|---:|
| `SPY` | `+12.32` |
| `GLD` | `+8.42` |
| `BTC` | `+0.55` |
| `USO` | `-7.32` |
| `TLT` | `-13.97` |

SPY 是 upper-tail 最大淨傳染源，TLT 是最大淨接收者。GLD 在此 daily proxy 設定下也是淨傳染源，這點需要後續用不同 RV proxy 檢查。

## Verdict

`tail_connectedness_positive_not_crisis_specific`

本實驗支持「尾部 quantile connectedness 高於 median connectedness」，但不支持「高 SPY 波動期會進一步放大 tail-minus-median gap」。

結論強度限制：

- 可作為 daily proxy 下的 network evidence。
- 不可宣稱為 intraday realized volatility 結論。
- 不可宣稱為結構因果傳染。
- 不可直接轉成交易策略或風險配置規則。

## 產物

- Script: `research_quantile_connectedness_var_yfinance_etf_rv_quant.py`
- Results: `research_quantile_connectedness_var_yfinance_etf_rv_quant_results.json`
- Figure 1: `fig_tail_vs_median_connectedness.png`
- Figure 2: `fig_net_transmitters_by_quantile.png`
- Figure 3: `fig_pairwise_tail_minus_median.png`

## 如何重跑

```bash
uv run python experiments/research_quantile_connectedness_var_yfinance_etf_rv_quant/research_quantile_connectedness_var_yfinance_etf_rv_quant.py
```

## 局限與後續

1. `BTC-USD` 不是 crypto ETF。若要嚴格 ETF 口徑，只能改用 `IBIT` 等短樣本並放棄長 rolling QVAR。
2. 日頻 squared-return proxy 噪音大，應等 intraday RV 或更可靠 realized measure 後重測。
3. QVAR 是 equation-by-equation QuantReg，沒有 Bayesian shrinkage，pairwise source 解讀要保守。
4. 下尾 `tau=0.05` 的 TCI 也高於 median，甚至 full-sample 與 rolling mean gap 更大，值得另做「低波動/壓抑波動 regime connectedness」檢查。
