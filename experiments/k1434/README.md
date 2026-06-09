# K1434 — 台股 Q1 財報集中公告日波動率 cluster vs HAR-RV

- Experiment ID: `K1434`
- Status: `completed`
- Author: `Codex`
- Date: `2026-06-09`

## 問題描述

台股 Q1 財報通常集中在 5 月公告，而且多數公司在收盤後揭露。K1434 檢驗：

1. 當「前一交易日」有較多 TWSE 50 公司集中公告 Q1 財報時，次日 TWII 波動 proxy 是否偏高？
2. 將這種 `Q1 earnings cluster` 當成 HAR-style 波動率模型的額外 covariate，是否能在 OOS 改善預測？

## 動機

- K1061 已證實台股財報波動效應重點落在 `T+1`，因台灣公告慣例多在收盤後。
- 但 K1061 是 individual-stock / portfolio-level EAV，不是市場指數層級的「集中公告密度」效應。
- 若 cluster density 對大盤次日波動有增量資訊，表示財報季不只影響個股，還可能改變市場 aggregate uncertainty。

## 資料

- TWII OHLC：`storage/macro/yf_TWII.csv`
- 財報公告日：專案根目錄 `財報公告日.txt`（Big5）
- 公司池：沿用 K1061 的 TWSE 50 名單
- Sample: `2014-01-01` to `2026-05-31`

## 方法

### Cluster 變數

- 只保留 `ym` 以 `03` 結尾的公告，即 Q1 季報。
- 每個交易日統計 TWSE 50 有幾家公司公告 Q1 財報，得到 `q1_cluster_count_t`。
- 另建 `q1_cluster_day_t = 1{count_t >= 3}`，把密集公告日與一般零星公告日分開。

### Volatility target

使用 TWII 日 OHLC 建立 Parkinson variance proxy：

`RV_t = [ln(H_t/L_t)]² / (4 ln 2)`

模型在 `log(RV_t)` 上估計，forecast 再 exponentiate 回 level，並用 level-RV 評估。

### Models

1. `HAR` baseline  
   `log RV_t ~ logRV_{t-1} + avg7_{t-1} + avg30_{t-1}`
2. `HAR + cluster_count`  
   baseline + `q1_cluster_count_{t-1}`
3. `HAR + cluster_day`  
   baseline + `q1_cluster_day_{t-1}`

### OOS 設計

- IS: `2014-01-31` to `2020-12-31`
- OOS: `2021-01-01` to `2026-05-31`
- Expanding-window one-step forecast
- Metrics: `QLIKE`, `MSE`
- Formal test: Diebold-Mariano (`h=1`)

## Lookahead policy

- HAR regressors 均使用 `shift(1)`。
- `q1_cluster_count_t` 代表當日收盤後已知的公告密度，只能用來預測 `t+1`。
- 因此模型使用 `q1_cluster_count.shift(1)` / `q1_cluster_day.shift(1)`，不允許同日混用。

## 成功標準

1. `cluster` covariate 在 HAC t-test 顯著。
2. cluster-augmented HAR 在 OOS `QLIKE` / `MSE` 優於 baseline，且 DM 顯著。

## 局限

1. 只測 Q1 財報季，不代表 Q2/Q3/Q4 同樣成立。
2. TWII 是價格指數，不是 total-return index。
3. 這是日資料 Parkinson proxy，不是高頻 realized volatility。
