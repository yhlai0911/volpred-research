# K1497 — Realized Volatility Roughness Stability and OOS Predictive Gain Re-Check

## 問題

`research_realized_volatility_roughness_hurst_0_5` 要求重新檢查兩件事：

1. realized-volatility 的 roughness（`H < 0.5`）是否跨資產、跨期穩定；
2. 把 roughness 訊息加進 HAR 類模型後，是否真的帶來可重現的 OOS 預測增益。

## 動機

- `K529` 在 SPY 上確認 roughness，但用單一資產、單一 proxy，且 HAR-Rough 只明顯勝過 GJR，未勝 EWMA。
- `K764`、`K1386` 已指出 roughness / multivariate roughness 的 OOS 優勢很脆弱，常在 HAR baseline 前消失。
- `research_program.md` 明確把這題定位為對 K1423/K1424 的正交延伸：不是問「time-varying H 是否能當額外 predictor」，而是問「RV path 自身的 roughness 是否穩定，且是否值得放進 forecasting model」。
- repo 內沒有可覆蓋多年、多資產的本地 `5-min` archive；`K953` 已誠實記錄 free-tier yfinance 只有 ~60 天，不足做正式檢定。因此本次先用 **本地多年 OHLC + Parkinson RV proxy** 做可驗證再檢查，不假裝完成高頻版。

## 文獻脈絡

1. Gatheral, Jaisson, Rosenbaum (2018), *Volatility is Rough*：log-volatility 的 Hurst 指數約 0.1。
2. Corsi (2009), *A Simple Approximate Long-Memory Model of Realized Volatility*：HAR-RV 是 realized-vol 預測基準。
3. Patton (2011), *Volatility forecast comparison using imperfect volatility proxies*：用 proxy 比較時 QLIKE 是主要公平 loss。
4. Cont and Das (2024), *Rough volatility: fact or artefact?*：realized volatility 本身可能因估計誤差而呈現「假 roughness」。

## 資料

- 來源：`paper/garch-x-vix/data/`
- 資產：`SPY`, `QQQ`, `EEM`, `FEZ`, `GLD`, `USO`
- 樣本：各資產自可用起始日至 `2026-05-19`
- target proxy：Parkinson variance
  - `RV_t = (log(High_t / Low_t))^2 / (4 log 2)`

## 方法

### 1. Roughness 估計

- 在 `log(RV)` 上用 structure-function regression：
  - `E[(log RV_{t+h} - log RV_t)^2] ~ C h^{2H}`
- 對 `log h` 與 `log mean(square increment)` 做 OLS，`slope / 2 = H`
- 報告：
  - full-sample `H`
  - 3 個等長子樣本 `H`
  - rolling 504-day `H` 的平均、標準差、區間、`H<0.5` 比例

### 2. OOS 預測比較

- Baseline：HAR-RV
  - `RV_t ~ RV_{t-1} + mean(RV_{t-1:t-5}) + mean(RV_{t-1:t-22})`
- Candidate：HAR-Rough
  - 先用與 baseline 同樣的 OLS 估係數
  - 再用 trailing 504-day `H_{t-1}` 對 daily / monthly 分量做保守重加權：
    - `w_d = 1 + (0.5 - H)`
    - `w_m = 1 - (0.5 - H)`
    - `w_w = 1`
- OOS 起點：`2022-01-03`
- 訓練：expanding window，嚴格使用 `t-1` 以前資訊
- 評估：
  - QLIKE
  - log-RV MSE
  - DM test（pointwise QLIKE；Harvey threshold `|t| > 3`）

## Lookahead 防呆

- `RV_t` 的預測只用 `RV_{t-1}`、`RV_{t-1:t-5}`、`RV_{t-1:t-22}`
- `H_t` 只用到 `t-1` 截止的 trailing window
- 沒有 same-day signal 乘 same-day target

## 成功標準

1. 多資產 roughness 是否普遍且穩定有明確數字。
2. HAR-Rough 是否至少在部分資產上穩定勝 HAR，且需通過 DM/Harvey 門檻。
3. 若沒有增益，要如實報告 NULL，不把 `H<0.5` 本身誤當 forecasting contribution。

## 預期可能結果

- roughness 本身大概率仍成立；
- 但 forecasting gain 可能延續 `K764/K1386` 的 pattern，在 HAR baseline 前消失。
