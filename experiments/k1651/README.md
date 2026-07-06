# K1651 — CAViaR 直接動態分位數 VaR vs GARCH-VaR

## 研究問題

Engle-Manganelli CAViaR 是否能在不先估計波動率模型的情況下，直接預測一日左尾 VaR，並在 out-of-sample 風險回測與 pinball loss 上勝過傳統 GJR-GARCH skew-t VaR？

本實驗不是「首次發現 CAViaR」：knowledge 內已有 O15 / K905 / K941 / K967 / K1571 等 CAViaR 或 quantile-VaR 結果。K1651 的差異是把四個經典 CAViaR 規格（SAV / AS / IG / Adaptive）放進正式 K 實驗三件套，對 SPY 與 HYG 同時跑 5% / 1% VaR，並用 OOS Dynamic Quantile gate 對照 GJR-GARCH skew-t。

## 文獻先行

- Engle and Manganelli (2004), *CAViaR: Conditional Autoregressive Value at Risk by Regression Quantiles*：CAViaR 把 VaR 視為 conditional quantile，直接指定 quantile 的 autoregressive dynamics，而不是先估條件變異再套分布假設。參考：<https://pages.stern.nyu.edu/~rengle/CAVIAR.pdf>
- Dumitrescu, Hurlin, and Pham (2012), *Backtesting Value-at-Risk: From Dynamic Quantile to Dynamic Binary Tests*：整理並延伸 DQ/backtesting 口徑，支撐本實驗把 DQ 作為 conditional specification gate。參考：<https://shs.hal.science/halshs-00671658v1/document>
- Cai et al. (2026), *CAViaR Model Selection via Adaptive Lasso*：近期文獻仍把 CAViaR 當作可擴展的動態分位數框架，但也凸顯 model selection / latent quantile lag 的估計難度。參考：<https://zongwucai.github.io/papers/paper143.pdf>
- Long-memory CAViaR-FZ / CAViaR-ES 文獻顯示 vanilla CAViaR 的自然延伸是 joint VaR-ES，而非把 VaR-only 模型硬說成 ES 模型。參考：<https://ideas.repec.org/a/wly/jforec/v44y2025i2p391-423.html>

## 方法

- **資料**：Yahoo Finance adjusted close；SPY / HYG；2007-04-12 至 2026-07-02，共 4,837 個 daily log-return rows。
- **OOS**：2015-01-01 起；每個 asset-alpha cell 2,891 OOS observations。
- **VaR 水準**：5% 與 1% left-tail VaR。
- **模型**：
  - HS250：`y.shift(1).rolling(250).quantile(alpha)`
  - CAViaR-SAV：`q[t] = b0 + b1 q[t-1] + b2 |r[t-1]|`
  - CAViaR-AS：`q[t] = b0 + b1 q[t-1] + b2 r_pos[t-1] + b3 r_neg[t-1]`
  - CAViaR-IG：`q[t] = -sqrt(b0 + b1 q[t-1]^2 + b2 r[t-1]^2)`，明確輸出負的左尾 VaR，避免把正 scale 誤當 VaR。
  - CAViaR-AD：Engle-Manganelli adaptive recursion。
  - GJR-GARCH-SkewT：`arch` GJR-GARCH(1,1,1)，skew-t standardized residual quantile。
- **Refit**：annual expanding-window refit；refit row 嚴格使用 `index < t`；refit 後每日用 `r[t-1]` 遞迴預測 `t`。
- **推論 / 評估**：Kupiec POF、Christoffersen independence、exact-binomial Basel-style zone、Engle-Manganelli DQ（4 hit lags + VaR）、pinball loss、DM-HAC；Harvey-style gate 使用 `|t| > 3`。
- **ES 範圍**：本實驗只評估 VaR。Vanilla CAViaR 沒有原生 ES 預報，因此不做 ES superiority claim；若要 joint VaR-ES，應另開 CAViaR-FZ / RES-CAViaR 題。

## 主要結果

整體 verdict：`CONDITIONAL_CAVIAR_COMPETITIVE_NO_HARVEY_EDGE`。

| Cell | Pinball 最佳 | 完整 VaR+DQ gate 通過模型 | 重點 |
|---|---:|---|---|
| SPY VaR 5% | GJR-GARCH-SkewT | GJR-GARCH-SkewT | GARCH pinball 0.001162；CAViaR-AS 接近但 Kupiec / DQ fail。 |
| SPY VaR 1% | CAViaR-AS | CAViaR-AS, GJR-GARCH-SkewT | AS pinball 0.000357 vs GARCH 0.000369，但 DM-HAC t=-1.78，未達 Harvey `|t|>3`。 |
| HYG VaR 5% | GJR-GARCH-SkewT | GJR-GARCH-SkewT | CAViaR-SAV/AS/IG pinball 接近，但 5% coverage 偏保守且 DQ/Kupiec fail。 |
| HYG VaR 1% | GJR-GARCH-SkewT | 無 | GARCH pinball 最佳但 Kupiec p=0.048，嚴格 gate 仍 fail；CAViaR-SAV/AS 過度保守。 |

總結：

- GJR-GARCH-SkewT 是 3/4 cells 的 mean pinball winner，也是 3/4 cells 的完整 VaR+DQ gate winner。
- CAViaR-AS 在 SPY 1% cell 表現最好且通過 gate，但相對 GARCH 的 pinball 改善沒有達到 Harvey `|t|>3`。
- CAViaR-SAV / AS / IG 在多數 cell 與 GARCH 接近，說明 direct quantile paradigm 可作為 VaR 替代模型；但本次樣本不支持「CAViaR 系統性勝過 GARCH-VaR」。
- Adaptive CAViaR 在本設定明顯不穩，違約率大幅偏高，不能作為實務候選。

## 研究誠實結論

K1651 支持一個有限結論：**CAViaR 是可用的 direct-quantile VaR 框架，尤其 AS 規格在 SPY 1% tail 具競爭力；但它沒有在 SPY/HYG 兩市場、1%/5% 兩分位數上穩健打敗 GJR-GARCH skew-t。** 因此不能把 CAViaR 宣稱為新的 VaR 王者。實務上，GJR-GARCH skew-t 仍是更穩定的 baseline；CAViaR-AS 可列入 tail-risk model set 或 regime-specific challenger。

## 檔案

- `k1651.py`：完整可復現腳本，seed=42，atomic JSON write。
- `k1651_results.json`：所有統計量、gate、DM-HAC、metadata。
- `k1651_forecasts.parquet`：逐日 forecast / actual / loss / violation。
- `k1651_prices.parquet`：yfinance adjusted-close cache。
- `fig_k1651_pinball.png`：mean pinball loss 圖。
- `fig_k1651_violations.png`：violation rate vs target 圖。

## 限制

- annual refit 是為了讓四規格 CAViaR + GARCH 在 hourly task 內可完整重跑；monthly refit 可能改變短期適應速度，應另開 sensitivity。
- CAViaR 估計使用 bounded L-BFGS-B + 2 starts；非全域最佳保證。結果因此定位為 practical OOS comparison，不是 CAViaR numerical optimization paper。
- 只測 SPY/HYG；不外推到台股、商品或 crypto。
- Vanilla CAViaR 無 ES；本文不做 ES backtest 與 FZ joint loss 結論。

## Reviewer

Independent fresh-context Codex review：**CONDITIONAL_PASS**。Reviewer 未發現 no-lookahead、CAViaR IG 符號、GJR-GARCH skew-t 遞迴/quantile、Kupiec/Christoffersen/Basel/DQ、DM-HAC/Harvey gate 的 correctness bug。唯一 Medium finding 是 `main()` 不自動生成 README；本輪已手動新增 `README.md`，三件套（README / script / results JSON）齊全，故不阻塞結果使用。
