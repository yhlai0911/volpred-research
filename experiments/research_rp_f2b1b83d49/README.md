# research_rp_f2b1b83d49

## 動機

研究 backlog 題目要求檢驗：在 HAR-RV 類日頻 proxy 設定下，同時控制 `jump proxy` 與
`sign-asymmetry spillover`，是否能改善 1/5/22 日波動率預測。

這題的差異化在於：

- 不只加單一 jump proxy，而是把 `jump` 與 `bad-minus-good spillover` 放進同一個 HAR 框架。
- 使用跨市場 ETF 面板（`SPY/EWJ/EWG/EWU/EEM`），避免單一市場結論過度外推。
- 用專案既有 HAC Diebold-Mariano 實作，顯式做 lag-1 predictor guard，避免 lookahead。

## 相關知識 / 既有工作

- `K530`：HAR 多變體在日頻 proxy 下可與傳統基準競爭，但 jump 類增量先前不穩定。
- `K628b`：跨資產 vol spillover 網路確認了 transmitter / receiver 結構，但不是 HAR 預測增量檢定。
- `K1301`：semivariance 分解在另一資料場景下為 NULL，提醒「不對稱分解」不等於一定有 OOS 預測增量。
- `docs/error_log.md`：
  - HAR-CJ 類 jump 識別不可假裝成正式 BNS jump；本實驗誠實標示為 `daily jump proxy`。
  - DM-HLN 必須走 `src/volpred/stats/model_evaluation.py` 的 HAC 實作。
  - 所有 predictor 必須顯式 `shift(1)`，不能用同日訊號配同日報酬。

## 文獻前置

1. Al Rababaa, Mensi, McMillan, Kang (2025), *Forecasting the Realized Volatility of Stock Markets: The Roles of Jumps and Asymmetric Spillovers*, Journal of Forecasting. DOI: `10.1002/for.3219`
2. Barunik, Kocenda, Vacha (2017), *Asymmetric Volatility Connectedness on the Forex Market*, Journal of International Money and Finance. DOI: `10.1016/j.jimonfin.2017.06.003`
3. Patton, Sheppard (2015), *Good Volatility, Bad Volatility: Signed Jumps and the Persistence of Volatility*, Review of Economics and Statistics. DOI: `10.1162/REST_a_00503`
4. Corsi (2009), *A Simple Approximate Long-Memory Model of Realized Volatility*, Journal of Financial Econometrics. DOI: `10.1093/jjfinec/nbp001`

## 資料

- 來源：`yfinance adjusted close`
- 資產：`SPY`, `EWJ`, `EWG`, `EWU`, `EEM`
- 期間：`2010-01-04` 到 `2026-06-12`
- 價格樣本數：`4136`
- 報酬樣本數：`4135`

## 設計

### Target

- `h=1/5/22` 未來交易日平均 squared log return
- 因本題限定 `yfinance` 免費日頻資料，這裡是 **daily variance proxy**，不是 5-min realized variance

### 模型

- `HAR-RV`：lagged `rv_1`, `rv_5`, `rv_22`
- `HAR-J`：`HAR-RV + jump_proxy`
- `HAR-AS`：`HAR-RV + asym_spill`
- `HAR-J-AS`：`HAR-RV + jump_proxy + asym_spill`

### Predictor 定義

- `jump_proxy`：
  - 若 `|r_t|` 超過 trailing 252-day 的 95% 分位數，取當日 `r_t^2`
  - 否則為 `0`
  - 這是 **proxy**，不是 BNS formal jump decomposition
- `asym_spill`：
  - 先對每個資產計算 positive semivariance 與 negative semivariance
  - 在 252 日 rolling window 中，分別對正/負半變異面板做 generalized FEVD spillover
  - 取 `from_others_bad - from_others_good`
  - 再轉成 trailing z-score 並截尾到 `[-3, 3]`

### 防錯規則

- 所有 predictor 都有顯式 `shift(1)`
- OOS 採 expanding window，initial train = `756`
- DM test 使用 `volpred.stats.model_evaluation.dm_test`
- 比較時用四個模型共同可用日期交集，避免 sample-selection 偏差

## 成功標準

- 任一增量模型在至少一個 horizon 出現穩定 QLIKE 改善
- 若無改善，也要如實報告 NULL / negative result
- 不接受只靠單一資產、單一 outlier 的過度宣稱

## 主要結果

### Aggregate

| Horizon | Best model | Mean QLIKE delta vs HAR-RV | Asset wins | Harvey pass |
|---|---:|---:|---:|---:|
| 1d | HAR-J | `+0.348%` | `5/5` | `0/5` |
| 5d | HAR-J | `+0.037%` | `3/5` | `0/5` |
| 22d | HAR-J | `+0.046%` | `3/5` | `0/5` |

### 解讀

- `HAR-J` 有 **非常小的方向性改善**，但三個 horizon 都 **沒有任何 Harvey |t| > 3 的正式通過**。
- `HAR-AS` 與 `HAR-J-AS` 整體上 **普遍比 baseline 差**。
- 最明顯的反例是 `EEM, h=1`：加入 asym spillover 後 QLIKE 極端惡化，顯示這個 predictor 在單日 horizon 對部分資產會帶來不穩定 miss。
- `EWJ` 在 `h=5` 與 `h=22` 有少量正向訊號：
  - `HAR-AS` 5d `+2.90%`
  - `HAR-AS` 22d `+1.81%`
  但都沒有通過 Harvey 門檻，因此不能當成正式增量結論。

### 結論

本題在目前的 `yfinance` 日頻 proxy 設定下，**不支持**「jump × sign-asymmetry spillover 同時控制能穩定改善 HAR」。

較精確地說：

- `jump proxy` 只有 **經濟量級極小** 的正向方向性
- `sign-asymmetry spillover` 沒有帶來可重複的 OOS 增量，且對部分資產會惡化
- 因此這題目前應記為 **NULL / weak-negative**

## 產物

- Script: `research_rp_f2b1b83d49.py`
- Results: `research_rp_f2b1b83d49_results.json`
- Figure 1: `fig_qlike_delta_heatmap.png`
- Figure 2: `fig_asym_spillover_timeseries.png`

## 如何重跑

```bash
uv run python experiments/research_rp_f2b1b83d49/research_rp_f2b1b83d49.py
```

## 局限

1. 這不是 5-min RV，而是 daily squared-return proxy；與原論文設計有層級差。
2. `jump_proxy` 只是 exceedance proxy，不是 formal jump test。
3. spillover 採固定 `VAR lag = 1` 與 `step = 5`，是 tractability tradeoff。
4. `EEM h=1` 對 asym spillover 有極端脆弱性，顯示此 feature 在日頻單步預測上不穩。
