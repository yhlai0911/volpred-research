# K1718 / ASIA-2：日股波動基準與前一美股日 VIX 增量

## 問題與範圍

本實驗檢驗：在日本市場開盤前已知的最近一筆美國 VIX 完整收盤，是否能改善日股次一日波動預測。^N225 是價格加權 Nikkei 225；1306.T 是市值加權 TOPIX 的可交易 ETF。兩者成分與權重不同，因此各自估計、各自評分，不把指數預測冒充 ETF replication。

本 K 使用 yfinance auto_adjust=True 的 adjusted OHLC；另對 1306.T 的 2026 年官方 1:10 分割窗口做可稽核尺度正規化，並因 2015-01-05 前另有無法由發行人紀錄驗證的 10 倍 vendor unit break 而捨棄較早區段。正式 OOS 為 2020–2026，包含 COVID 與 2022 空頭。

## 預先設計的方法

- 三個 family：Gaussian GARCH(1,1)、GJR-GARCH(1,1)、HAR-style log-r²。最後一個只用落後日報酬  平方的 1/5/22 日成分，不是 5 分鐘 realized variance，因此不稱 HAR-RV。
- VIX-X 加入 (VIX/100)^2/252；VIX 以 strict backward as-of join 對齊，source date 嚴格早於  Japan target。HAR 本地特徵先 r².shift(1)。
- 每年年初用截至前一年末的 expanding sample 重估。六個 forecast 在同一嚴格正值 mask 上以  Patton QLIKE、MSE、Spearman 評分。
- X 對 base 是巢狀模型；主要推論為 Clark-West one-sided MSPE-adjusted test。六格一起做 Holm。  canonical dm_test 的 QLIKE DM 只列診斷，不餵入 verdict。
- 預註冊 robust gate：六格都必須 QLIKE_X < QLIKE_base 且 Holm-adjusted Clark-West p<0.05。  0 格為 NULL，1–5 格為 PARTIAL，6 格才是 ROBUST。

## 文獻定位

Lin、Engle、Ito (1991, NBER w3911) 對東京與紐約指出跨時區資訊傳遞，但 lagged volatility spillover 並非普遍顯著；本實驗不預設 VIX 一定有效。模型與評分另依 GJR (1993)、Corsi (2009)、Patton (2011)、Clark-West (2007)。Wang (2019) 是本次嚴格 OOS replication 的直接動機。

## 資料診斷

- 共同比較起點：2015-01-05；VIX 1990-01-02 至 2026-07-15。
- 1306.T 尺度稽核：2026-03-30/31 的 adjusted Open/Close 乘 10，轉成與相鄰日期一致的 pre-split-equivalent basis；官方分割生效日 2026-04-01，交易調整自 2026-03-30。
- Nikkei 225 index：adjusted OHLC 2015-01-05 至 2026-07-14，model n=2,794；年化波動 21.58%；VIX source age median 1.0 日。
- NEXT FUNDS TOPIX ETF：adjusted OHLC 2015-01-05 至 2026-07-15，model n=2,815；年化波動 19.80%；VIX source age median 1.0 日。

## OOS forecast 結果

| Track | Model | QLIKE | MSE | Spearman |
|---|---:|---:|---:|---:|
| Nikkei 225 index | GARCH | 1.5409 | 0.00000042 | 0.169 |
| Nikkei 225 index | GARCH-X(VIX) | 1.5616 | 0.00000041 | 0.169 |
| Nikkei 225 index | GJR | 1.5330 | 0.00000040 | 0.200 |
| Nikkei 225 index | GJR-X(VIX) | 1.5665 | 0.00000040 | 0.166 |
| Nikkei 225 index | HAR-style log-r2 | 2.0397 | 0.00000073 | 0.187 |
| Nikkei 225 index | HAR-style log-r2-X(VIX) | 2.1744 | 0.00001114 | 0.168 |
| NEXT FUNDS TOPIX ETF | GARCH | 1.3423 | 0.00000022 | 0.151 |
| NEXT FUNDS TOPIX ETF | GARCH-X(VIX) | 1.3584 | 0.00000023 | 0.177 |
| NEXT FUNDS TOPIX ETF | GJR | 1.3062 | 0.00000021 | 0.182 |
| NEXT FUNDS TOPIX ETF | GJR-X(VIX) | 1.3268 | 0.00000022 | 0.182 |
| NEXT FUNDS TOPIX ETF | HAR-style log-r2 | 5.1707 | 0.00212535 | 0.109 |
| NEXT FUNDS TOPIX ETF | HAR-style log-r2-X(VIX) | 5.3614 | 0.14069581 | 0.129 |

### VIX 增量 gate

| Track | Family | QLIKE improvement | CW t | raw p | Holm p | pass |
|---|---:|---:|---:|---:|---:|---:|
| Nikkei 225 index | garch | -1.34% | 1.974 | 0.0242 | 0.1422 | FAIL |
| Nikkei 225 index | gjr | -2.18% | 1.633 | 0.0512 | 0.2047 | FAIL |
| Nikkei 225 index | har_r2 | -6.60% | -1.579 | 0.9428 | 1.0000 | FAIL |
| NEXT FUNDS TOPIX ETF | garch | -1.20% | 1.983 | 0.0237 | 0.1422 | FAIL |
| NEXT FUNDS TOPIX ETF | gjr | -1.58% | 1.254 | 0.1049 | 0.3147 | FAIL |
| NEXT FUNDS TOPIX ETF | har_r2 | -3.69% | -1.586 | 0.9436 | 1.0000 | FAIL |

**結論：NULL。** Lagged US VIX passes none of six pre-registered nested-model cells; evidence does not support a robust Japan VIX overlay.

## Exploratory 1306.T VT scorecard

權重在 1306.T 開盤時計算為 min(1, 12% / annualized forecast vol)，持有 adjusted Open[t]→Open[t+1]，主口徑每單位 turnover 10 bps。forecast target 是 close-to-close r²，策略 holding 是 open-to-next-open；下表只作描述性診斷，不支撐上架。

| Model | Ann. return | Ann. vol | Sharpe | Ann. turnover | Mean weight |
|---|---:|---:|---:|---:|---:|
| Buy & hold | 18.97% | 20.08% | 0.944 | 0.16 | 1.000 |
| GARCH | 10.31% | 12.57% | 0.821 | 11.86 | 0.713 |
| GARCH-X(VIX) | 9.78% | 11.79% | 0.829 | 10.83 | 0.666 |
| GJR | 9.67% | 12.95% | 0.747 | 12.80 | 0.752 |
| GJR-X(VIX) | 9.07% | 12.28% | 0.739 | 11.72 | 0.708 |
| HAR-style log-r2 | 1.12% | 1.23% | 0.911 | 0.99 | 0.065 |
| HAR-style log-r2-X(VIX) | 1.03% | 1.22% | 0.846 | 0.95 | 0.064 |

## 限制

- 日報酬平方是 noisy proxy；HAR-style log-r² 不是 intraday HAR-RV。
- 1306.T 與 ^N225 是不同籃子；一致性只能視為跨指標 robustness。
- yfinance 是 2026-07-16 vendor snapshot；1306.T 的尺度修復只保證報酬連續，不宣稱輸出價格水準是可交易報價；本結果未使用不可得的 ^NKVI。
- Clark-West 對 nested MSPE 有正確方向，但主要 ranking loss 是 QLIKE；兩者不互相冒充。
- VT target/holding-period 不完全一致，且只測簡化 turnover cost。

## 產物

- k1718.py、k1718_results.json、k1718_data.csv、k1718_oos_forecasts.csv
- k1718_oos_qlike.png、k1718_annual_stability.png、k1718_vt_paths.png

完整 fit diagnostics、canonical DM HAC/ACF/sensitivity、六格 Holm receipt、資料 SHA 與 0/10/25 bps sensitivity 均在 results JSON。
