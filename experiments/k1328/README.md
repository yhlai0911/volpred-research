# K1328: HAR Ceiling Validation — Los Flamingos 2025

## 動機

`research_program.md` 把「HAR ceiling」列為待驗證方向。repo 內雖然已有 `K530`、`K764`、`K1377` 等 HAR 家族結果，但它們回答的是：

- HAR vs GARCH / rough-vol / HAR 組合
- 並不是 Los Flamingos 2025 所強調的那個更窄命題：
  - **如果 rolling window / re-fit scheme 調對，簡單 HAR 會不會形成一個很難被 ML 打破的 baseline ceiling？**

因此這個實驗不是重跑 `K530`，而是做一個 matched-feature、同資料、同 target 的再驗證。

## 文獻前置

本實驗設計前先查三條主文獻線：

1. Corsi (2009), *A Simple Approximate Long-Memory Model of Realized Volatility*
   - HAR-RV 的原始三尺度結構（d / w / m）。
2. Audrino & Chassot (2024/2025 SSRN), *Hard to Beat: The Overlooked Impact of Rolling Windows in the Era of Machine Learning*
   - claim：HAR 的 fit scheme 很重要；若 window / re-estimation 做對，ML 不一定能贏。
3. Kilic (2025 FEDS), *Linear and nonlinear econometric models against machine learning models: realized volatility prediction*
   - 提醒最新文獻不是單向「ML 一定贏」，而是 evidence mixed，且 regime-aware / interpretable models 仍常有優勢。

## 研究問題

在本地可重跑資料上，兩個問題分開檢定：

1. **HAR fit scheme 是否真的重要？**
   - 不同 rolling / expanding 規格下，HAR 的 OOS QLIKE 差距有多大？
2. **最佳 HAR 是否會形成 practical ceiling？**
   - 在同一組 HAR 特徵下，最佳 HAR 是否能穩定打平或擊敗常見 ML baseline？

## 資料

- 來源：本地 snapshot `experiments/k1206/data/*.csv`
- 資產：`SPY`, `QQQ`, `GLD`, `TLT`
- 期間：
  - SPY / QQQ: 2000-01-03 至 2026-04-16
  - GLD: 2004-11-18 至 2026-04-16
  - TLT: 2002-07-30 至 2026-04-16
- target proxy：日頻 squared log return
  - `rv_t = (log Close_t - log Close_{t-1})^2`

### 誠實限制

- 這不是 paper-grade 5-min realized variance。
- 這是 **honest local proxy test**，目的是驗證「fit scheme 與 baseline ceiling」而不是冒充高頻 RV 論文複現。
- 所有模型都吃同一個 proxy，所以 model-vs-model 比較仍公平。

## 特徵與 timing discipline

HAR 三尺度特徵：

- `log_rv_1 = log(rv_{t-1})`
- `log_rv_5 = log(mean(rv_{t-5:t-1}))`
- `log_rv_22 = log(mean(rv_{t-22:t-1}))`

target：

- `log(rv_t)`

重要 timing 規則：

- 特徵只用 `t-1` 以前資料
- 預測的是 `t` 的 RV
- 沒有 same-day signal × same-day return

## 模型

### Stage A: HAR fit-scheme audit

v2 為了讓 Stage B 能做真正 matched comparison，Stage A 只在**共同 21 交易日 re-fit cadence**下比較 window：

- `expanding_refit_21d`
- `rolling_252_refit_21d`
- `rolling_1000_refit_21d`

**v2 methodology fix**：

- Stage A **只**用獨立 selection / holdout window `2017-01-03` 至 `2020-12-31` 選 best HAR scheme
- `2021-01-04+` 的 final OOS 完全不參與 scheme selection

### Stage B: Best HAR vs matched-feature ML

先用 Stage A 選出 cross-asset 平均 QLIKE 最佳的 HAR scheme。Stage B 的比較規則是：

- `HAR_OLS`：直接用 Stage A 選出的最佳 scheme
- ML challengers：**完全沿用同一個 training window 與同一個 21 交易日 re-fit cadence**
  - 這次不再允許 HAR 與 ML 有不同 re-fit 頻率，避免把比較結果混進 schedule advantage

- `HAR_OLS`
- `ElasticNet`
- `RandomForest`
- `XGBoost`

## 評估

- selection window：`2017-01-03` 至 `2020-12-31`
- final OOS 起點：`2021-01-04`
- primary metric：Patton-style `QLIKE` on `rv_t`
- pairwise test：DM-HLN (`src/volpred/stats/model_evaluation.py`)
- threshold：Harvey `|t| > 3`

## 成功標準

- 產出完整三件套：`README.md`, `k1328.py`, `k1328_results.json`
- 有明確 lookahead-safe 實作
- 清楚分開：
  - HAR 內部 tuning 是否重要
  - 最佳 HAR 是否對 ML 形成 ceiling
- 如果結果為 NULL，也要如實報告

## 預註冊預期

基於 repo 既有脈絡（`K530`, `K764`, `K1377`, `K1314`）與文獻混合證據，我預期：

- HAR 的 fit scheme 會明顯影響 OOS 表現
- 最佳 HAR 會是強 baseline
- 但未必在每個資產都顯著贏 ML；比較可能是 **「多數打平或小勝，少數資產被局部 ML 規格超過，但未達 Harvey 強門檻」**

## 相關既有實驗

- `K530`: HAR family vs GARCH family baseline
- `K764`: rough-vol extension 沒有穩定打破 HAR ceiling
- `K1377`: HAR family 內 adaptive combination
- `K1314`: 複雜 graph augmentation 在簡化設定下多半沒能穩定勝過 HAR
