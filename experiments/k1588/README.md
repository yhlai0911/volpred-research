# K1588: Social Connectedness → 財報 vol 反應

- Experiment ID: `K1588`
- Verdict: `NULL`
- Script: `experiments/k1588/k1588.py`
- Results: `experiments/k1588/k1588_results.json`

## 動機

這個題目對應研究程式中的社交連結假說：如果公司總部所在 county 與外部社會網路更緊密，財報公布附近的價格反應與波動是否更強，且波動是否更快衰減。

原始構想是用 Meta / Facebook 的 Social Connectedness Index（SCI）去量化 county centrality，再看 earnings announcement 附近的 realized volatility jump 與 HAR-style decay。這次實驗有做成可重現版本，但必須誠實說明：我拿到的是公開 SCI county pair snapshot 與公開 HQ location proxy，並不是歷史逐日 SCI。

## 與既有工作的差異

- 這不是一般財報事件研究，而是把 county-level social connectedness 當作 cross-sectional 解釋變數。
- 這裡不使用私有平台資料，也不捏造 SCI；完全依靠公開資料與可重跑腳本。
- 估計標的是 daily close-to-close 的 volatility proxy，不是 5-minute intraday RV。

## 資料來源

1. `HDX Social Connectedness Index` 的 `us_counties.csv`，用 county pair 的 `scaled_sci` 聚合成 county centrality。
2. `datasets/s-and-p-500-companies` 的 current constituents snapshot，用來取 US-headquartered tickers 與 headquarters location。
3. `OpenStreetMap Nominatim`，把 headquarters location 轉成 county。
4. `yfinance`，抓 daily OHLCV、`^VIX` 與 earnings dates。

## 樣本與範圍

- 期間：`2018-01-01` 到 `2026-06-30`
- 選到的 tickers：`112`
- 可用 earnings events：`2,663`
- event profile rows：`15,978`
- train / OOS split：`2024-01-01` 前後切分

## 方法

### 1) county centrality

- 先把 SCI county pair 檔中的 US-US pair 過濾出來。
- 對每個 `user_region` county 取 `scaled_sci` 加總，得到 county centrality。
- 再做 `log1p` 與 z-score 標準化。

### 2) earnings event 對齊

- earnings timestamp 只當作公告日，不拿來看同日市場反應。
- 反應日定義為「公告日之後的第一個 trading day」，避免 lookahead。
- pre-baseline 用 event day 前的 20 個交易日，但排除 `t-1` 與 event day 本身。
- post window 用 event day 後 5 個交易日。

### 3) outcome

主 outcome 用兩個 daily proxy：

- `jump_log_abs = log(event_abs / pre_mean_abs)`
- `decay_speed_log_abs = log(event_abs / post_1_5_mean_abs)`

也同時估 `jump_log_rv` 與 `decay_speed_log_rv`。

### 4) model

- cluster-robust OLS by ticker
- 控制變數：
  - county SCI z-score
  - earnings surprise z-score
  - pre-event log absolute return baseline
  - sector fixed effects
  - sample-year fixed effects
  - VIX regime 與 `SCI × VIX`
- 補充檢定：
  - high SCI tercile vs low SCI tercile 的 Welch t-test
  - cluster bootstrap
  - horizon profile regressions for `h = 0..5`

## Lookahead 防錯

- `signal` 不直接對同日報酬。
- 反應日明確對齊為公告日後第一個交易日。
- pre-window 只用公告前的資料，且排除 `t-1` 與 event day。
- 所有隨機程序用 `seed=42`。

## 結果

### 主要回歸

- `jump_log_abs` 上的 `county_sci_z` coefficient = `+0.0213`, `p = 0.7430`
- `decay_speed_log_abs` 上的 `county_sci_z` coefficient = `+0.0228`, `p = 0.7117`
- OOS `jump_log_abs` coefficient = `+0.0666`
- OOS `decay_speed_log_abs` coefficient = `+0.0613`

### tercile 檢定

- high SCI 對 low SCI 的 `jump_log_abs` Welch t = `-2.69`, `p = 0.0071`
- high SCI 對 low SCI 的 `decay_speed_log_abs` Welch t = `-3.06`, `p = 0.0023`

方向上，高 SCI county 的平均 jump 與 decay speed 都沒有比較高，反而略低。

### verdict

`NULL`

這次的公開 proxy 版本，沒有得到支持「county social connectedness 解釋財報事件附近 vol jump / decay」的穩健證據。點估計有正號，但無論 full sample、OOS，還是 tercile split，都不足以支持正向敘事。

## 限制

1. `SCI` 不是歷史 time series，而是公開 county pair snapshot，所以這是 associational proxy study，不是 causal identification。
2. headquarters location 是目前公開 location，未追蹤歷史搬遷。
3. earnings timestamp 來自 `yfinance`，公告精確到交易時段的資訊不足，所以反應日只能保守地對齊到下一個交易日。
4. 只有 daily close-to-close proxy，沒有 intraday realized volatility。
5. regression cluster bootstrap 為了這輪時間 cap，採 `300` reps；tercile bootstrap 用 `1000` reps。

## 檔案

- [`k1588.py`](./k1588.py)
- [`k1588_results.json`](./k1588_results.json)
- [`figures/k1588_event_profile_by_sci_tercile.png`](./figures/k1588_event_profile_by_sci_tercile.png)
- [`figures/k1588_sci_horizon_coefficients.png`](./figures/k1588_sci_horizon_coefficients.png)
- `data/` 下有快取資料與 event panel

## 可重跑驗證

```bash
python experiments/k1588/k1588.py
python - <<'PY'
import json, pathlib
json.loads(pathlib.Path("experiments/k1588/k1588_results.json").read_text())
print("ok")
PY
```

## 文獻

- Bailey, Kuchler, Stroebel, and Wong (2018), *Social Connectedness: Measurement, Determinants, and Effects*, Journal of Economic Perspectives. https://www.aeaweb.org/articles?id=10.1257/jep.32.3.259
- Hirshleifer, Peng, and Wang (2025), *Social Networks and Market Reactions to Earnings News*, Review of Financial Studies. https://academic.oup.com/rfs
- Sui and Wang (2025), *Social transmission bias: evidence from an online investor platform*, Review of Finance. https://academic.oup.com/rof
