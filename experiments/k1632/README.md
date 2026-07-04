# K1632 — 盤整越久、噴得越兇？低波動盤整後的大波動檢定

**Status**: completed  
**Task**: `research_myth_consolidation_then_breakout`  
**Seed**: 42  
**Verdict**: `MYTH_MOSTLY_FALSE_LOW_VOL_PERSISTS`

## 1. 動機

投資社群常見說法是：**「盤整越久，噴得越兇。」**

這句話可以拆成兩層：

1. 低波動盤整持續越久後，後續 5/20/60 日是否真的更容易大幅波動？
2. 盤整結束當天是否比較容易出現較大的單日移動？

本實驗刻意把兩者分開。第一層是可交易訊號：day `t` 收盤後已知「盤整已持續 N 天」，target 從 `t+1` 開始。第二層是描述性診斷：盤整結束當天的報酬已經發生，不能當成事前可交易預測。

## 2. 相關知識與文獻

### 相鄰 VolPred context

- 低波動不等於低風險：既有 VaR 記憶多次顯示低波動 regime 容易形成狹窄風險估計，但那是 tail-risk / VaR 問題，不等同於「盤整後必有方向性大噴」。
- `research_program.md` 已將「盤整越久噴越兇」列為台股／一般讀者迷思驗證題，本實驗填補該項。

### 文獻定位

- Engle (1982), *Econometrica*, "Autoregressive Conditional Heteroscedasticity..."：ARCH 的核心是條件變異會隨過去資訊變動，支撐「波動有狀態與聚集」這個基本前提。<https://www.econ.uiuc.edu/~econ536/Papers/engle82.pdf>
- Bollerslev (1986), *Journal of Econometrics*, "Generalized Autoregressive Conditional Heteroskedasticity"：GARCH 將過去條件變異納入當期條件變異，說明低波動可能延續，而不是機械式立刻爆開。<https://public.econ.duke.edu/~boller/Published_Papers/joe_86.pdf>
- Brock, Lakonishok, and LeBaron (1992), *Journal of Finance*, "Simple Technical Trading Rules..."：技術規則可被正式檢定，不能只靠圖形敘事。<https://finance.martinsewell.com/stylized-facts/dependence/BrockLakonishokLeBaron1992.pdf>
- Sullivan, Timmermann, and White (1999), *Journal of Finance*, "Data-Snooping, Technical Trading Rule Performance, and the Bootstrap"：技術指標有資料探勘風險，需避免事後挑規則。<https://ideas.repec.org/a/bla/jfinan/v54y1999i5p1647-1691.html>
- Bollinger Band squeeze 的交易敘事常說低波動收斂後可能迎來大波動；本實驗把這個敘事改寫成可檢定的 daily event study。<https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/bollinger-band-squeeze>

## 3. 資料

| 資產 | 來源 | 期間 | 觀測值 |
|---|---|---:|---:|
| SPY | `data/cache/price_cache.db :: price_data adj_close` | 2016-01-04 至 2026-07-02 | 2,639 |
| 0050.TW | `data/cache/price_cache.db :: price_data adj_close` + `clean_tw50_data` | 2009-01-02 至 2026-07-03 | 4,282 |

SPY 是美股大型股 proxy；0050.TW 是台股大型股 proxy，不是官方全市場指數。

## 4. 方法

### 4.1 盤整定義

day `t` 同時滿足：

1. 過去 20 日年化 realized volatility 低於自身 trailing 252 日的第 20 百分位。
2. 過去 20 日收盤價區間（20 日最高 / 最低 − 1）低於自身 trailing 252 日的第 20 百分位。

兩個 threshold 都用 `.shift(1)` 的歷史分位數，因此 day `t` 的門檻只由 `t-1` 以前資料決定。day `t` 的 20 日波動與 20 日區間在收盤後可觀察。

### 4.2 事件

主可交易事件：

- `squeeze_reaches_5d`
- `squeeze_reaches_10d`（primary）
- `squeeze_reaches_20d`

也就是低波動盤整連續第 N 天的收盤後訊號。Forward target 從 `t+1` 開始。

描述性事件：

- `episode_end_after_10d`：至少 10 天盤整後，第一個不再符合 squeeze 的交易日。
- 該日的 `breakout_day_abs_ret` 只是描述性診斷，因為同日報酬已發生，不可當作事前交易訊號。

### 4.3 Target 與檢定

Horizons：5、20、60 個交易日。

每個 event 比較：

- 後續 log return 均值。
- 後續 absolute return 均值。
- 後續 annualized realized volatility。
- Top-quintile absolute move 機率。

正式檢定：

- Forward abs-return / volatility：OLS dummy regression with Newey-West HAC SE，`maxlags = horizon`。
- Breakout-day abs-return：Welch test。
- Top-quintile absolute move：Fisher exact test。
- Primary 20 日 future-vol 差異：moving-block bootstrap，block=20、n_boot=2000、seed=42。

## 5. 結果

### 5.1 Primary：盤整達 10 天後，後續 20 日波動沒有升高

| 資產 | 事件數 | 事件後 20 日年化波動 | 其他日 | 差異 | HAC t | p | Block bootstrap 95% CI |
|---|---:|---:|---:|---:|---:|---:|---:|
| SPY | 14 | 11.48% | 14.85% | -3.37pp | -2.90 | 0.00377 | [-5.77pp, -1.04pp] |
| 0050.TW | 17 | 14.79% | 17.81% | -3.03pp | -2.93 | 0.00339 | [-4.81pp, -0.80pp] |

**解讀**：若把「盤整已持續 10 天」當作收盤後可用的訊號，後續 20 日不但沒有更震，兩個市場都偏向更安靜。

### 5.2 20 日絕對報酬也沒有支持「噴更大」

| 資產 | 事件後 20 日平均絕對報酬 | 其他日 | 差異 | HAC t | p | Top 20% 大波動機率 |
|---|---:|---:|---:|---:|---:|---:|
| SPY | 1.94% | 3.44% | -1.49pp | -3.82 | 0.000133 | 0.0% vs 20.1% |
| 0050.TW | 4.24% | 4.25% | -0.01pp | -0.01 | 0.989 | 23.5% vs 20.0% |

SPY 的結果明顯反向；0050.TW 則幾乎沒有差異。

### 5.3 盤整結束當天確實比較容易動，但那不是事前訊號

至少 10 天盤整後的 episode end：

| 資產 | 事件數 | 結束當天平均單日絕對報酬 | 其他日 | 差異 | Welch p |
|---|---:|---:|---:|---:|---:|
| SPY | 14 | 1.11% | 0.73% | +0.38pp | 0.0271 |
| 0050.TW | 17 | 1.74% | 0.86% | +0.88pp | 0.000754 |

這是一半成立的地方：**盤整結束那一天本身比較容易有較大單日移動**。但這個數字不能拿來當「明天會噴」的訊號，因為你只有在當天收盤後才知道它已經結束。

### 5.4 盤整結束後的 20 日仍未變更震

| 資產 | 事件後 20 日年化波動 | 其他日 | 差異 | HAC t | p |
|---|---:|---:|---:|---:|---:|
| SPY | 11.31% | 14.85% | -3.54pp | -3.03 | 0.00243 |
| 0050.TW | 14.05% | 17.82% | -3.77pp | -3.70 | 0.000212 |

盤整結束後，後續 20 日也沒有進入「更大波動」狀態。

## 6. 結論

**「盤整越久、噴得越兇」作為可交易預測訊號不成立。**

更精確地說：

1. 低波動盤整達 10 天後，SPY 與 0050.TW 的後續 20 日波動都低於一般日子。
2. 盤整結束當天確實比較容易有較大的單日絕對報酬，但這是描述性結果，不是事前可交易訊號。
3. 因此，較誠實的白話版是：**盤整結束那天可能會動一下，但盤整越久不代表後面 20 天會一路大噴。低波動常常只是低波動 regime 的延續。**

## 7. 限制

1. **日頻資料限制**：盤整與 breakout 在日內可能更清楚；日頻 close-to-close 可能漏掉 intraday 先噴後收斂。
2. **事件數偏小**：10 日 squeeze 事件 SPY 14 次、0050.TW 17 次；20 日 squeeze 更少，不宜過度解讀。
3. **盤整定義單一**：本實驗使用 20 日 realized volatility + 20 日收盤區間雙低分位。不同技術派可能用 Bollinger BandWidth、Keltner Channel 或成交量收縮。
4. **非交易策略回測**：本實驗只檢定迷思，不含交易成本、停損、突破方向濾網或部位管理。
5. **資產範圍有限**：只測 SPY 與 0050.TW；個股、題材股、加密貨幣可能有不同微結構。

## 8. 檔案

| 檔案 | 內容 |
|---|---|
| `k1632.py` | 完整可復現腳本 |
| `k1632_results.json` | 所有統計量與 provenance |
| `k1632_panel.csv` | joined panel 與事件欄位 |
| `fig_squeeze_future_vol.png` | 盤整達標後的後續波動比較 |
| `fig_episode_end_breakout.png` | 盤整結束當天 vs 結束後 |
| `codex_review.md` | Codex 審查 |

復現：

```bash
uv run python experiments/k1632/k1632.py
```
