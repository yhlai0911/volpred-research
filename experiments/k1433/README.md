# K1433 — BTC 週末 / 週間波動率季節性

- Experiment ID: `K1433`
- Status: `completed`
- Author: `Codex`
- Date: `2026-06-09`

## 問題描述

Bitcoin 是 24/7 交易資產，沒有股市那種「週末休市 → 週一開盤」結構，但市場參與者組成與流動性仍可能有週末差異。K1433 測試：

1. BTC 的日波動 proxy 在週末是否系統性高於或低於平日？
2. 在 HAR-style range-vol 模型中，加入 `weekend` 或 `weekday` calendar dummies，是否能在 OOS 改善對隔日波動的預測？

## 動機

- repo 內已有 K873 的較粗 weekend anomaly 掃描，但不是這次要的「HAR baseline vs HAR + calendar covariates」增量設計。
- 對 crypto 而言，calendar effects 若存在，理論上應能作為低成本 covariate 幫助次日 vol 預測。

## 資料

- Source: 本地快取 `experiments/k1119/data/btc_ohlcv.csv`
- Asset: `BTC-USD`
- Period: `2020-01-01` to `2026-04-12`
- Frequency: daily OHLCV
- Sample size: 約 2,295 日

## 方法

### Volatility target

使用日資料 `High/Low` 建立 Parkinson variance proxy：

`RV_t = [ln(H_t/L_t)]² / (4 ln 2)`

再取 `log(RV_t)` 做 HAR-style 線性模型，最後把 forecast exponentiate 回 level 後，用 level-RV 評估。

### Models

1. `HAR` baseline  
   `log RV_t ~ logRV_{t-1} + avg7_{t-1} + avg30_{t-1}`
2. `HAR + weekend`  
   baseline + `1{t is Sat/Sun}`
3. `HAR + weekday`  
   baseline + Tue..Sun dummies（Mon 為 base）

### OOS 設計

- IS: `2020-01-31` to `2023-12-31`
- OOS: `2024-01-01` to `2026-04-12`
- Expanding-window one-step forecast
- Metrics: `QLIKE`, `MSE`
- Formal test: Diebold-Mariano (`h=1`)

### Lookahead policy

- HAR regressors 一律使用 `t-1` 以前資訊：
  - `log_rv_l1 = log_rv.shift(1)`
  - `log_rv_7 = log_rv.shift(1).rolling(7).mean()`
  - `log_rv_30 = log_rv.shift(1).rolling(30).mean()`
- Calendar dummy 對 forecast day 是 ex ante 已知資訊，不構成 lookahead。

## 參考文獻

1. Parkinson (1980), *The Extreme Value Method for Estimating the Variance of the Rate of Return*
2. Corsi (2009), *A Simple Approximate Long-Memory Model of Realized Volatility*
3. French and Roll (1986), *Stock Return Variances: The Arrival of Information and the Reaction of Traders*

## 成功標準

1. 若 `weekend` 或 `weekday` dummy 在 HAC t-test 顯著，表示存在條件平均上的 calendar effect。
2. 若 calendar-augmented HAR 在 OOS `QLIKE` / `MSE` 改善且 DM 顯著，表示該 effect 對預測有增量價值。

## 局限

1. 這不是高頻「真 HAR-RV」，而是日資料 Parkinson variance proxy。
2. 僅用單一資產 BTC；calendar effect 可能是 regime-specific。
3. 未納入 funding / options / order-flow 類 covariates，因此若 calendar effect 很弱，可能代表資訊早被更強變數吸收。
