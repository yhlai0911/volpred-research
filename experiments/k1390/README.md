# K1390: Regime-Weighted Conformal VaR

## 動機

本實驗檢驗一個最小可解釋的 regime-structured conformal VaR 校準：若市場處於高波動狀態，單一固定的 unconditional tail quantile 可能會低估尾部風險；若以 `VIX_{t-1} > 20` 將校準樣本拆成高波動與低波動兩個 bucket，再做 regime-specific conformal quantile，是否能改善 VaR 覆蓋率。

## 方法摘要

- 標的：SPY 日對數報酬 `r_t = log(SPY_t / SPY_{t-1})`
- Regime 定義：`high_vol = VIX_{t-1} > 20`，嚴格使用 `t-1` lag，避免 lookahead
- IS：2004-01-01 至 2014-12-31
- OOS：2015-01-01 至 2026-12-31
- VaR 方法：
  - `HS-252`：前 252 日 rolling historical simulation quantile
  - `CU`：以 IS 全樣本尾部分位數固定校準的 conformal-unconditional VaR
  - `CR`：以 IS 高/低波動 bucket 分開校準的 conformal-regime VaR
- 評估：
  - 95% VaR (`alpha=0.05`)
  - 99% VaR (`alpha=0.01`)
  - exceedance 定義：`r_t < -VaR_t`
  - Kupiec LR unconditional coverage test

## 資料來源與期間

- 資料檔：`paper/leverage-direction/data/spy_vix_2004-2026.csv`
- 欄位：`spy_adj_close`、`vix_close`
- OOS regime 次數：高波動 859 日，低波動 2012 日

## 結果

| Method | Alpha | Actual rate | Nominal alpha | Kupiec p-value |
|---|---:|---:|---:|---:|
| HS-252 | 0.05 | 0.0526 | 0.0500 | 0.5268 |
| CU | 0.05 | 0.0421 | 0.0500 | 0.0474 |
| CR | 0.05 | 0.0498 | 0.0500 | 0.9624 |
| HS-252 | 0.01 | 0.0167 | 0.0100 | 0.0010 |
| CU | 0.01 | 0.0063 | 0.0100 | 0.0310 |
| CR | 0.01 | 0.0111 | 0.0100 | 0.5445 |

## 結論

`CR` 在兩個 alpha 都比 `CU` 更接近 nominal exceedance rate，且 Kupiec p-value 顯著更高：95% VaR 下 `CR` 幾乎完全貼近目標覆蓋率，99% VaR 下也明顯優於 unconditional conformal。相較之下，`CU` 在 95% 與 99% 皆呈現 under-exceedance，代表固定全樣本 quantile 對不同波動 regime 的 tail risk 校準不足。

本實驗 verdict 為 `REGIME_EFFECT`，因為 `CR` 的 Kupiec p-value 至少在一個 alpha 上優於 `CU`；實際上在 95% 與 99% 兩個水準都更好。
