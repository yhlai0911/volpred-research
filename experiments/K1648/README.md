# K1648 — QML/Kalman SV 類 vs GARCH 類日頻波動率預測

## 動機

VolPred 既有實驗大量覆蓋 GARCH / GJR / HAR / MIDAS，但「隨機波動率（SV）」這一整類較少被公平地放進同一個 OOS loss framework。K1648 測試一個可在本機快速重跑的版本：用 QML / Kalman filter 估 latent log variance，再和 GARCH 類做一日 ahead variance 與 VaR/quantile 比較。

文獻 anchor：

- Threshold stochastic volatility: properties and forecasting — https://www.sciencedirect.com/science/article/abs/pii/S0169207017300717
- Realized Stochastic Volatility Model with Skew-t Distributions for Improved Volatility and Quantile Forecasting — https://arxiv.org/abs/2401.13179
- Patton (2011), volatility forecast comparison using imperfect volatility proxies — https://public.econ.duke.edu/~ap172/Patton_vol_proxies_JoE_2011.pdf

## 設計

資料：

- yfinance daily adjusted OHLC, `auto_adjust=True`
- Assets: `SPY`, `TLT`, `HYG`
- Download window: 2010-01-01 至 2026-07-07
- OOS: 2018-01-02 起
- Cache: `K1648_ohlc_cache.parquet`

模型：

- `EWMA_094`
- `GARCH_N`: GARCH(1,1), Normal innovations
- `GJR_T`: GJR-GARCH(1,1), Student-t innovations
- `SV_KF`: log-squared-return QML SV, Kalman filter
- `TSV_KF`: `SV_KF` 加 `1[r_{t-1}<0]` threshold / leverage state term
- `RSV_KF`: `SV_KF` 加 OHLC Parkinson range log-variance measurement

評估：

- Primary: Patton QLIKE on close-to-close `r_t^2`
- VaR / quantile: expanding empirical standardized residual quantile at 5% and 1%，用 pinball loss、Kupiec、Christoffersen conditional coverage 檢查
- DM: `volpred.stats.model_evaluation.dm_test`，h=1；Harvey-style threshold 以 `|t| > 3` 判定強 evidence
- SV variance forecast: Kalman log-normal conditional mean `exp(h_pred + 0.5 * p_pred)`，不是只用 plug-in `exp(h_pred)`
- SV convergence audit: annual refit 的 optimizer success、log-likelihood、參數與 boundary hit 寫入 `K1648_results.json`；clean verdict 需 chosen success rate >= 95%

## Lookahead 防護

每日 `t` 的 forecast 先用到 `t-1` 為止的 state 與前一日 return sign。GARCH/SV state 在 day `t` 的 forecast 記錄後，才用 day `t` return / range observation update。這等價於一日 ahead `signal.shift(1)`。

程式入口：`K1648.py`

結果檔原子寫入：先寫 `.tmp`、`json.loads` 驗證、再 `os.replace` 到 `K1648_results.json`。

## 結果

Verdict: `WEAK_SV_AVERAGE_QLIKE_EDGE_NO_HARVEY_WIN`

本次是 Codex review 後的 v2 rerun：修正 SV forecast 從 `exp(h_pred)` 改成 log-normal mean `exp(h_pred + 0.5 * p_pred)`，並加入收斂稽核。SV optimizer chosen success rate = 81/81 = 100%，fallback = 0；但 `SV_KF`/`TSV_KF` 有 12 個 boundary-hit fits，解讀時仍應偏保守。

平均 QLIKE 排名：

| model | mean QLIKE | mean rel vs GARCH_N | Harvey wins vs GARCH_N | Harvey losses vs GARCH_N |
|---|---:|---:|---:|---:|
| `RSV_KF` | 1.3442 | +1.59% | 0 | 0 |
| `GJR_T` | 1.3445 | +1.51% | 1 | 0 |
| `GARCH_N` | 1.3658 | 0.00% | 0 | 0 |
| `EWMA_094` | 1.4058 | -2.74% | 0 | 0 |
| `TSV_KF` | 2.0925 | -53.69% | 0 | 2 |
| `SV_KF` | 2.1165 | -55.16% | 0 | 2 |

逐資產 QLIKE winner：

- `HYG`: `GJR_T`, QLIKE 1.2991；對 `GARCH_N` DM t=-4.07，Harvey-significant win
- `SPY`: `RSV_KF`, QLIKE 1.4889；對 `GARCH_N` DM t=-1.65，raw p=0.100，未過 `|t|>3`
- `TLT`: `RSV_KF`, QLIKE 1.1935；對 `GARCH_N` DM t=-2.16，raw p=0.031，但未過 `|t|>3`

VaR calibration：

- 5% VaR 的 Kupiec p 值大多不拒絕；`SPY` 的 `SV_KF` 5% p=0.033，`TSV_KF` 1% p=0.007，顯示部分 SV 近似在尾部 calibration 上仍不穩。
- `RSV_KF` 在 SPY/TLT 取得弱 QLIKE edge，三資產平均比 `GARCH_N` 好 1.59%，但沒有任何 RSV 單資產 DM 過 `|t|>3`。

## 解讀

這個可重跑的 QML/Kalman pilot 不再支持原本的乾淨 NULL：log-normal mean 修正後，`RSV_KF` 在平均 QLIKE 上略高於 `GJR_T` / `GARCH_N`，且在 SPY/TLT 是逐資產 winner。可是這個 edge 沒有通過 VolPred 的 Harvey-style `|t|>3` 強 evidence bar；唯一 Harvey-significant win 仍是 `GJR_T` 在 HYG 對 `GARCH_N` 的改善。

這不等於完整 Bayesian realized-SV skew-t 文獻已被驗證，也不能宣稱 SV 類一般性勝出。K1648 的 RSV 是日頻 OHLC range measurement 的 QML 近似，不是 MCMC realized-SV skew-t，也沒有用 intraday realized variance。結論應限縮為：在免費日頻 yfinance OHLC、年度 refit、QML/Kalman log-normal mean 近似下，RSV 有弱平均 QLIKE edge，但尚未達正式 publication-strength evidence。

## 檔案

- `K1648.py`
- `K1648_results.json`
- `K1648_ohlc_cache.parquet`
- `K1648_forecasts.parquet`
- `fig_k1648_mean_qlike.png`
- `fig_k1648_rel_vs_garch.png`
