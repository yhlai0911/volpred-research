# PM2.5 / AQI 外生 regressor pilot

- **Experiment ID**: `research_pm2_5_regressor_nber_w22753_heyes_neidell_saberi`
- **Task**: PM2.5 情緒型外生 regressor：以交易所城市污染資料作為 HAR-RV add-on，檢查高污染日與 risk-off / 波動反應。
- **執行時間**: 2026-07-02
- **Verdict**: `NULL`

## 結論

在 2020-2024 的 New York County daily AQI + SPY daily OHLC/VIX panel 中，`AQI[t-1]` 沒有改善 SPY 日頻 Garman-Klass variance proxy 的 OOS 預測。

主要數字：

- 樣本：2020-02-04 至 2024-12-31，`n=1236` 個交易日。
- AQI 資料：EPA AirData county daily AQI，2020-2024 每日皆有值；calendar `n=1827`。
- PM2.5 為 defining pollutant 的 calendar share：`59.2%`。
- `AQI >= 150` calendar days：`6` 天；對應可用交易預測事件只有 `4` 筆，事件檢定 power 不足。
- OOS：2023-01-03 至 2024-12-31，`n=502`。
- Base HAR-style daily proxy + VIX QLIKE：`0.40344`。
- AQI add-on QLIKE：`0.40567`，比 base 差 `0.55%`。
- DM-HAC：`t=0.627, p=0.531`；沒有可用的 OOS 改善證據。
- VIX-controlled residual 中 `AQI[t-1]/10` coefficient `0.0108`，HAC `p=0.518`。

因此本輪只支持一個保守結論：在這個可重現、lag-clean 的日頻 proxy 設計下，New York County AQI 不是 SPY 日頻波動 proxy 的有效 add-on。這不推翻原文獻的 same-day / intraday / monitor-level PM2.5 設計，因為本實驗不是完整 replication。

## 方法

Primary model:

```text
log(GK_RV_t) =
  HAR daily lag + HAR weekly lag + HAR monthly lag + log(VIX variance_{t-1}) + |r_{t-1}|
```

AQI add-on:

```text
AQI_{t-1}/10 + I(PM2.5 defines AQI_{t-1}) + AQI_{t-1}/10 * I(PM2.5 defines AQI_{t-1})
```

Lookahead guard：

- AQI feature 在程式內明確以 `signal.shift(1)` 建立。
- Market HAR / VIX features 也全部 lag 一個交易日。
- OOS forecast day `t` 使用 expanding window，訓練資料只到 `t-1`。

Inference：

- In-sample：OLS + HAC covariance (`maxlags=5`)。
- OOS：Patton-style QLIKE on variance proxy，DM-HAC `h=1`。
- Event diagnostics：Welch t-test + fixed-seed bootstrap (`seed=42`)。

## 資料來源

- Pollution：US EPA AirData `daily_aqi_by_county_<YEAR>.zip`
  - URL template: `https://aqs.epa.gov/aqsweb/airdata/daily_aqi_by_county_<YEAR>.zip`
  - Geography: New York State, New York County (`State Code=36`, `County Code=61`)
  - Period: 2020-2024
- Market：`yfinance` daily `SPY` and `^VIX`
  - Period: 2020-2024
  - SPY target proxy: daily Garman-Klass variance from OHLC

## 文獻

本實驗前先查三篇相關研究：

- Heyes, Neidell, and Saberian (2016), NBER w22753, "The Effect of Air Pollution on Investor Behavior: Evidence from the S&P 500".
- Kiihamaki, Korhonen, and Jaakkola (2021), Scientific Reports, "Ambient particulate air pollution and daily stock market returns and volatility in 47 cities worldwide".
- Meyer and Pagel (2017), NBER w24048 / Review of Finance 2024, "Fresh Air Eases Work - The Effect of Air Quality on Individual Investor Activity".

## Diagnostic Notes

High-AQI diagnostics are not the primary finding:

- `AQI >= 150` event rows are only `4` in the trading-day model frame, so no formal conclusion.
- AQI top-decile days (`AQI >= 64`) show lower next-day daily variance proxy in this sample, not higher. This is counter to the "pollution raises volatility" hypothesis and likely sensitive to seasonality/sample composition; no weather or seasonal controls are included.
- PM2.5-defining days by themselves have no volatility or return difference (`rv_garman_klass` Welch `p=0.960`).

## Files

- `research_pm2_5_regressor_nber_w22753_heyes_neidell_saberi.py`：完整可重跑腳本。
- `research_pm2_5_regressor_nber_w22753_heyes_neidell_saberi_results.json`：正式結果。
- `data/`：EPA zip cache、filtered AQI CSV、market CSV、model panel、OOS forecasts。
- `figures/`：AQI/vol time series、OOS cumulative QLIKE advantage、pollution coefficient chart。

## Reproduce

```bash
uv run python experiments/research_pm2_5_regressor_nber_w22753_heyes_neidell_saberi/research_pm2_5_regressor_nber_w22753_heyes_neidell_saberi.py
```

若要重新下載資料：

```bash
uv run python experiments/research_pm2_5_regressor_nber_w22753_heyes_neidell_saberi/research_pm2_5_regressor_nber_w22753_heyes_neidell_saberi.py --refresh
```

## Limitations

- 使用 county daily AQI，不是逐站 PM2.5 concentration；AQI 可由 ozone 或其他污染物定義。
- 使用 daily Garman-Klass / range variance proxy，不是 5-minute RV 或 bid-ask spread。
- 沒有 weather、traffic、macro-news、wildfire-specific controls。
- 2020-2024 樣本含 COVID regime 與 2023 wildfire episode，不可直接推廣。
- 高污染事件少，`AQI>=150` test underpowered。
