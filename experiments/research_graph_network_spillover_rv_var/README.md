# research_graph_network_spillover_rv_var

## 動機

任務池題目要求檢定：

> Graph/network spillover 學習 RV 是否贏線性 VAR。

這和既有 connectedness 實驗不同。`K357` 與 `research_quantile_connectedness_var_yfinance_etf_rv_quant` 主要回答「誰和誰連結、誰是傳染源」，本題回答的是「把 network 結構拿去預測，OOS QLIKE 是否真的變好」。

## 前置規則

已讀：

- `docs/error_log.md`
- `.claude/skills/autonomous-research/references/experiment-preamble.md`
- `storage/memory/knowledge.json` 中 graph / network / spillover / QLIKE 相關條目

防錯重點：

- yfinance 日頻資料不能產生真正 5-min realized volatility。本實驗只使用 close-to-close squared log return 作 daily variance proxy。
- 全部模型預測同一個 target：未來 `1/5/22` 日平均 daily variance proxy。
- forecast date `t` 的 feature 只用 close `t` 以前資訊，target 是 `t+1..t+h`。
- refit 時，training set 只包含在 block start 前已完整觀測到 target 的樣本，避免 horizon overlap lookahead。
- 結論只可說 daily proxy 下的 forecast evidence，不可宣稱 intraday RV 或結構因果。

## 文獻

至少 3 篇：

1. Zhang, Pu, Cucuringu, Dong (2025), *Forecasting realized volatility with spillover effects*, International Journal of Forecasting.  
   https://ideas.repec.org/a/eee/intfor/v41y2025i1p377-397.html
2. Diebold and Yilmaz (2012), *Predictive directional measurement of volatility spillovers*, International Journal of Forecasting.  
   https://econpapers.repec.org/RePEc%3Aeee%3Aintfor%3Av%3A28%3Ay%3Ai%3A1%3Ap%3A57-66
3. Wade (2026), *Do Better Volatility Forecasts Lead to Better Portfolios? Evidence from Graph Neural Networks*.  
   https://arxiv.org/abs/2605.19278
4. Mallory (2026), *Volatility Spillovers in High-Dimensional Financial Systems: A Machine Learning Approach*.  
   https://arxiv.org/abs/2601.03146

## 資料

- 來源：`yfinance` auto-adjusted close
- 標的：`SPY`, `QQQ`, `TLT`, `GLD`, `HYG`, `EEM`, `CL=F`
- 樣本：2007-04-12 至 2026-06-12 左右，依共同交易日與 HYG 可得資料決定
- proxy：`r_t^2`，其中 `r_t = log(P_t / P_{t-1})`
- `CL=F` 在 2020-04 有負結算價；程式會先移除任何非正 close 的共同日期，再計算 log return，避免負價直接進 log。

## 方法

### Target

對 horizon `h`，date `t` 的 target 是：

`mean(r^2_{t+1}, ..., r^2_{t+h})`

### Models

1. `own_har`
   - own log RV lag1
   - own 5-day rolling mean
   - own 22-day rolling mean
2. `spillover_var`
   - all assets log RV lag1
   - own 5-day / 22-day rolling mean
   - 這是線性 spillover-VAR baseline
3. `graph_har`
   - own-HAR features
   - `graph_neighbor_lag1`
   - adjacency 由 rolling training window 的 lagged correlation 建立：row asset 接收 column asset 的 lagged volatility signal
   - row-normalized，只保留正相關；若該 row 無正相關則等權分配到其他 assets

### OOS

- OOS start：2018-01-02
- rolling train window：1260 trading days
- refit frequency：21 trading days
- horizons：`1`, `5`, `22`
- estimation：ridge regression on log target variance

### 檢定

- QLIKE：Patton-style `a/f - log(a/f) - 1`
- DM test：date-level average QLIKE loss，HAC bandwidth 由 canonical `volpred.stats.model_evaluation.dm_test` 控制
- significance：Harvey-style `|t| > 3`

## 主要結果

完整數字以 `research_graph_network_spillover_rv_var_results.json` 為準。

### OOS mean QLIKE

| Horizon | own-HAR | spillover-VAR | graph-HAR |
|---:|---:|---:|---:|
| 1d | 4.0173 | 3.9433 | 3.8920 |
| 5d | 0.7013 | 0.6682 | 0.6626 |
| 22d | 0.5922 | 0.5782 | 0.5725 |

### Graph-HAR vs spillover-VAR

| Horizon | QLIKE improvement | DM t | Harvey `|t| > 3` |
|---:|---:|---:|---:|
| 1d | +1.30% | -4.34 | PASS |
| 5d | +0.84% | -2.39 | FAIL |
| 22d | +0.98% | -1.62 | FAIL |

### Verdict

`short_horizon_graph_vs_var_only_not_robust`

Graph propagation 在 1 日 horizon 對線性 spillover-VAR 有顯著 QLIKE 改善，但 5 日與 22 日沒有通過 Harvey `|t| > 3` 門檻。更重要的是，`graph_har` 相對 `own_har` 在三個 horizon 都不顯著，表示此 daily proxy 設定下的 network feature 不是穩健的新預測來源。

可說的結論：graph aggregation 可能有短 horizon 壓縮參數的價值。

不可說的結論：GNN / graph spillover 已全面優於傳統 VAR 或 own-HAR。

## 產物

- `research_graph_network_spillover_rv_var.py`
- `research_graph_network_spillover_rv_var_results.json`
- `fig_qlike_by_horizon.png`
- `fig_average_graph_adjacency.png`
- `data/prices.csv`

## 重跑

```bash
cd /Users/yhlai0911/Desktop/volpred-research
uv run python experiments/research_graph_network_spillover_rv_var/research_graph_network_spillover_rv_var.py
```
