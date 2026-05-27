# K1403 — HAR-RV Quantile Forecasting Cross-Asset Robustness (QQQ / GLD / TLT)

## Research question

K1402 在 SPY 上跑 HAR-RV quantile regression（pinball loss, τ ∈ {0.50, 0.75, 0.90, 0.95, 0.99}），verdict NULL：DM stat=-10.20, p=0 → quantile median QLIKE 顯著差於 OLS point forecast。

K1403 把同一 pipeline 在 **QQQ (科技)、GLD (黃金)、TLT (長債)** 三個跨資產類別重跑，回答：

1. K1402 NULL 是 **SPY-specific** 還是 **method-universal**？
2. 若所有 asset 都 NULL on DM 但 tail coverage (τ=0.95/0.99) 都 acceptable，整套方法可往 **conditional usable for tail VaR upper bound** 路線收（保留 multi-asset Risk Forecast 頁的 tail band 視覺化價值）。

## 動機與差異化

- **frontier 對接**：arXiv:2508.15922 (Probabilistic RV Quantile Forecasting) 僅 SPY；cross-asset 尚無公開 OOS evidence。
- **避開 ML novel-method NULL quartet**：用 Koenker-Bassett 1978 經典 quantile regression（non-ML），不踩 `diversity_rule_post_null_quartet`。
- **monetization angle**：3 個 asset 的 tail coverage band 餵 Risk Forecast 頁的 cross-asset upper-bound 視覺化 → Mission #4 (平台運營) + #5 (曝光) → 跨資產風險視角區隔免費內容與付費 premium tier。

## 相關 K

- K1402 — SPY 結果 NULL (DM stat=-10.20 p=0)；但 tail coverage 95/99 是否 acceptable 留待此 K cross-asset confirm
- K783c — expanding window 是 RV 預測 cross-regime 最佳折衷
- K785 — MF2-GARCH NULL，HAR-RV ceiling 仍未破
- K1038/K1129 — GAS-t VaR 邊際勝出但 QLIKE NS

## 設計

- **資料**：QQQ / GLD / TLT adj-close 2007-01-03 至 today（yfinance；cache `experiments/k1403/data/<asset>.csv`）
- **目標變數**：`daily_rv_t = |daily log return %|`（與 K1402 一致；one-step-ahead 預測）
- **特徵**（standard HAR-RV, Corsi 2009；全部 `.shift(1)`，signal at t-1, target at t）：
  - `rv_d = daily_rv[t-1]`
  - `rv_w = mean(daily_rv[t-5:t-1])`
  - `rv_m = mean(daily_rv[t-22:t-1])`
- **OOS split**：2021-01-04 起（與 K1402 / K1263 / K1312 對齊）
- **Baseline**：HAR-RV (OLS, MSE) → point forecast
- **Treatment**：HAR-RV QuantReg (pinball loss) for τ ∈ {0.50, 0.75, 0.90, 0.95, 0.99}
- **OOS 設計**：fixed-origin（pre-OOS 一次 fit；OOS 期間不 refit）— 與 K1402 對齊

## 評估

每個 asset 各自：
1. Pinball loss at each τ on OOS
2. Empirical coverage：`coverage_τ = P(daily_rv_actual ≤ q̂_τ)`，與 nominal τ 比
3. Kupiec UC test for τ=0.95/0.99 violation rate（右尾 violation rate = 1-τ）
4. DM test (HLN-adjusted) OLS QLIKE vs τ=0.5 quantile median QLIKE

## 成功標準（per-asset，套 K1402 同 criteria）

- **PASS**：(a) τ=0.95 與 τ=0.99 coverage ±2pp 內、(b) Kupiec UC p>0.05、(c) DM stat>0 p<0.10
- **CONDITIONAL_PASS**：(a) coverage ±5pp 內、(b) Kupiec UC p>0.05、(c) DM NS (p≥0.10)
- **NULL**：tail coverage gap > ±5pp OR Kupiec UC reject OR DM stat<0 p<0.10

## Cross-asset aggregate verdict

- **METHOD_RECOVERY**：≥2/3 asset PASS or CONDITIONAL_PASS → K1402 NULL 是 SPY-specific，方法 cross-asset 可用
- **UNIVERSAL_NULL**：3/3 NULL on DM 且 tail coverage 也 fail → method 整體無效
- **TAIL_CALIB_USABLE**：3/3 NULL on DM 但 ≥2/3 tail coverage acceptable → method 只能用於 tail VaR upper bound，不能取代 OLS point forecast

## Reproducibility

- Seed 42 (np.random.seed at top)
- yfinance cache 確定性；OOS_START 固定 2021-01-04
- `uv run python experiments/k1403/k1403.py`
