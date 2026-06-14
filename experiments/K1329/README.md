# K1329 — 原油波動率 spillover 到股市波動率

- Task: `K1329`
- Status: complete
- Seed: `42`

## 動機

研究 backlog 指定檢驗：`CL=F` / `USO` 的油價波動衝擊，是否會傳導到 `SPY` 與能源股波動率。這裡不問「油價漲跌是否預測股票報酬」，而是問「油本身的波動率 shock / vol-of-vol 是否有次日波動預測力」。

## 差異化

- `K422` 已檢查 commodity vol spillover network，且指出 `CL=F` 有 2020-04 負油價 outlier。
- `K628b` 是 Diebold-Yilmaz level connectedness，重點在跨資產 network centrality。
- `trending_2026_06_12_oil_vix_spillover` 是事件型描述診斷，沒有正式 OOS forecast gate。
- `K1329` 改成 HAR-style OOS volatility forecasting：baseline 為 own-vol HAR + VIX，extension 才加入 CL/USO 油波動 shock 與 vol-of-vol。

## 前置規則

已讀：

- `docs/error_log.md`
- `.claude/skills/autonomous-research/references/experiment-preamble.md`
- `research_program.md`
- `storage/memory/knowledge.json` 中 `spillover` / `oil` / `commodity` 相關條目

防錯規則：

- 所有 forecast feature 在程式內明確 `.shift(1)`。
- 不使用 same-day oil signal 預測 same-day equity volatility。
- `CL=F` 報酬在當日或前一日 close 非正時設為 `NaN`，避免 2020-04 負油價造成假 log return。
- 日頻 close-to-close squared return 只是低頻 volatility proxy，不宣稱為 intraday realized volatility。
- Forecast gate 使用 OOS QLIKE + Harvey-style DM threshold `|t| > 3`。

## 文獻前置

1. Diebold and Yilmaz (2009), *Measuring Financial Asset Return and Volatility Spillovers, with Application to Global Equity Markets*. NBER Working Paper `w13811`. https://www.nber.org/system/files/working_papers/w13811/w13811.pdf
2. Yu (2025), *Industry Index Volatility Spillovers and Forecasting from Crude Oil Prices Based on the MS-HAR-TVP Model*. `Mathematics`, 13(22), 3723. https://www.mdpi.com/2227-7390/13/22/3723
3. *Volatility spillovers between oil and financial markets during economic and financial crises: A dynamic approach*. `Journal of Economics and Finance`. https://link.springer.com/article/10.1007/s12197-023-09634-x

## 資料

- Source: Yahoo Finance via `yfinance`
- Window requested: `2007-01-01` to `2026-06-15` exclusive
- Oil predictors: `CL=F`, `USO`, robustness `^OVX`
- Baseline volatility control: `^VIX`
- Targets: `SPY`, `XLE`, `XOP`, `OIH`, `XOM`, `CVX`

## 方法

1. 下載 adjusted close。
2. 計算 log close-to-close returns；`CL=F` 非正價格附近 return 設為缺值。
3. 對 CL/USO 建 5-day rolling squared-return RV proxy。
4. 建油波動 shock：`z(log(rv5))`，rolling window 63 days。
5. 建油 vol-of-vol：`z(rolling_std(log(rv5), 20))`。
6. Forecast target：次日 `r_t^2` 的 log variance。
7. Baseline：own-vol `d/w/m` HAR lags + lagged VIX level z-score。
8. Extension：baseline + lagged CL/USO volatility shock + lagged CL/USO vol-of-vol。
9. Robustness：extension + lagged OVX level/change z-score。
10. 評估：chronological 70/30 split，OOS QLIKE、MAE、DM-HLN。
11. 輔助檢定：Granger causality lags 1-5，先做 lag Bonferroni，再做 family Bonferroni。

## 產物

- Script: `K1329.py`
- Results: `K1329_results.json`
- Figures:
  - `K1329_oos_qlike_improvements.png`
  - `K1329_granger_heatmap.png`
- CSV audit outputs:
  - `K1329_close_prices.csv`
  - `K1329_log_returns.csv`
  - `K1329_raw_spillover_signals.csv`
  - `K1329_granger_results.csv`
  - `K1329_correlations.csv`
  - `K1329_<target>_oos_forecasts.csv`

## 如何重跑

```bash
uv run python experiments/K1329/K1329.py
```

## 結果

Verdict: `statistical_spillover_without_oos_forecast_edge`

資料樣本：

- Latest price date: `2026-06-12`
- Forecast effective window: `2007-11-07` to `2026-06-12`
- OOS window: starts around `2020-11`, target-dependent
- OOS observations: `1395` to `1397` per target
- `CL=F` non-positive close excluded: `2020-04-20`

OOS QLIKE best improvement vs HAR+VIX baseline:

| Target | Best extension | QLIKE improvement | DM-HLN t | p-value | Harvey pass |
|---|---|---:|---:|---:|---|
| `SPY` | `plus_oil_volshock` | `+0.297%` | `-0.522` | `0.602` | no |
| `XLE` | `plus_oil_volshock` | `-0.008%` | `+0.008` | `0.993` | no |
| `XOP` | `plus_oil_volshock` | `-0.910%` | `+0.678` | `0.498` | no |
| `OIH` | `plus_oil_volshock` | `-0.973%` | `+1.025` | `0.306` | no |
| `XOM` | `plus_oil_volshock` | `+0.113%` | `-0.228` | `0.819` | no |
| `CVX` | `plus_oil_volshock` | `+0.197%` | `-0.283` | `0.778` | no |

Granger causality after lag and family Bonferroni corrections:

- `14` predictor-target pairs pass at 5%.
- Passing CL/USO vol-shock pairs include `SPY`, `XOM`, `CVX`, plus `USO_volshock -> XLE/XOP`.
- `CL_vov` and `USO_vov` do not pass for any target.
- `OVX_level_z` passes broadly, but adding OVX to the forecast model worsens OOS QLIKE for every target.

Interpretation:

Oil volatility shocks contain statistically detectable lag-1 information in daily Granger tests, especially for `SPY`, `XOM`, and `CVX`. That information does not translate into a robust OOS volatility forecast edge once own-vol HAR terms and VIX are already in the baseline. Report as a null for tradable / forecast use, not as an oil-volatility timing signal.
