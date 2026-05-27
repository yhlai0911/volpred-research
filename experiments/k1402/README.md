# K1402 — HAR-RV Quantile Forecasting (Pinball Loss)

## Research question

HAR-RV 是現役 RV point forecast 的標竿之一。若改用 pinball loss 訓練 conditional quantile forecast (τ ∈ {0.50, 0.75, 0.90, 0.95, 0.99})，能否：

1. 比單一 point forecast 更精準刻劃 RV 條件分佈（特別是右尾）？
2. 在 τ=0.95/0.99 提供經得起 Kupiec UC 檢定的 VaR-equivalent 信賴上界（直接服務 risk management 端）？

## 動機與差異化

- **frontier 對接**：arXiv:2508.15922（Probabilistic RV Quantile Forecasting）提出將 HAR/GARCH 點預測擴展為條件分位數，目前 SPY 無公開 OOS 結果。
- **避開 ML novel-method NULL quartet**（K1263 KAN / K1312 GARCH-Neural / K816v2 GINN / K784 GARCH-GRU 已連 4 NULL，CLAUDE.md 觸發 diversity rule `diversity_rule_post_null_quartet`）。本實驗用 1970s 經典 quantile regression（Koenker & Bassett 1978），**non-ML，不踩 rule**。
- **monetization angle**：tail-aware vol upper bound 直接餵 Risk Forecast 頁的 VaR/ES 視覺化（Mission #4 平台運營 + #5 曝光）。

## 相關 K

- K783c — expanding window 是 RV 預測 cross-regime 最佳折衷
- K785 — MF2-GARCH NULL，HAR-RV ceiling 仍未破
- K1263/K1312 — ML novel-method 連續 NULL → 改 econometrics extension
- K1038/K1129 — GAS-t 在 VaR 邊際勝出但 QLIKE NS（裝有 Student-t innovation）

## 設計

- **資料**：SPY adj-close 2007-01-03 至 today（yfinance；cache 自 K1312/data/SPY.csv 共用）
- **目標變數**：`daily_rv_t = |daily log return %|`（單日 realized vol proxy；one-step-ahead 預測）
- **特徵**（standard HAR-RV, Corsi 2009）：
  - `rv_d = daily_rv[t-1]`（lag-1 daily RV）
  - `rv_w = mean(daily_rv[t-5:t-1])`（過去 5 日平均）
  - `rv_m = mean(daily_rv[t-22:t-1])`（過去 22 日平均）
  - 全部 `.shift(1)`，signal at t-1，target at t（lag explicit）
- **OOS split**：2021-01-04 起（與 K1312 / K1263 同對齊）
- **Baseline**：HAR-RV (OLS, MSE 訓練) → point forecast
- **Treatment**：HAR-RV 5 個獨立 quantile regression (statsmodels QuantReg, pinball loss) for τ ∈ {0.50, 0.75, 0.90, 0.95, 0.99}
- **OOS 設計**：fixed-origin OOS（pre-OOS 一次 fit；OOS 期間不 refit）。**不是** expanding window — MVP 簡化，rolling refit 留 K1402b 比較 refit 成本

## 評估

1. **Pinball loss** at each τ on OOS
2. **Empirical coverage** at each τ：`coverage_τ = P(daily_rv_actual ≤ q̂_τ)`；nominal 對應 0.5/0.75/0.9/0.95/0.99
3. **Kupiec UC test** for τ=0.95/0.99 violation rate（右尾 violation rate = 1-τ）
4. **DM test (Diebold-Mariano, HLN-adjusted)** baseline OLS QLIKE vs τ=0.5 quantile median forecast on QLIKE 損失（檢驗 median quantile 是否 outperform mean）

## 成功標準（PASS / CONDITIONAL_PASS / NULL）

- **PASS**：(a) τ=0.95 與 τ=0.99 empirical coverage 落在 nominal ±2pp 範圍內、(b) Kupiec UC p>0.05、(c) DM qmed vs OLS p<0.10 且 stat>0（quantile median 顯著 outperform mean）
- **CONDITIONAL_PASS**：(a) coverage 落在 nominal ±5pp 範圍內、(b) Kupiec UC p>0.05、(c) DM **NS** (p≥0.10)；tail calibration 實用但 median 不顯著超越 OLS
- **NULL**：以下任一條件成立 — (i) tail coverage gap > ±5pp、(ii) Kupiec UC 任一尾 p≤0.05、(iii) **DM stat<0 且 p<0.10**（quantile median QLIKE 顯著差於 OLS）

## Reproducibility

- `SEED = 42`
- `statsmodels >= 0.14`, `scipy >= 1.10`, `numpy`, `pandas`, `yfinance`
- `uv run python experiments/k1402/k1402.py` 寫 `k1402_results.json`（無圖；coverage 視覺化留 K1402b walk-forward 版一併補）

## Lookahead 防線

- target `daily_rv_t = |ret_pct_t|` 無 forward smoothing
- 特徵 `rv_d/rv_w/rv_m` 全部 `.shift(1)` 明確 lag（rv_w/rv_m 先 rolling 後 shift，rolling window 全在 t-1 之前）
- OOS train fit 限定 `idx < OOS_START`；fixed-origin 設計 OOS 期間不再用未來資料

## Limitation

- **QuantReg on levels**：RV>0，理論上 `log(rv)` QR 再 exp back 較穩健（避免負分位數預測）。本 MVP 直接在 levels 做 QR，若 τ=0.5 predict 出現負值會被 QLIKE log(σ²) clamp 到 1e-12 → loss 異常高。實測 SPY OOS 期 QR 預測值未觸發此 edge case；log-QR 版本留 K1402c 比較
- **無 OOS refit**：parameter shift 期間 (e.g. 2022 bear) 可能 stale；K1402b 將跑 rolling refit 比較

## 計算 budget

- single-shot fixed-origin OLS + 5 QuantReg fits → ~5s 完成（測得）
- 計算量小，hourly fire 直接執行，未走 compute_queue worker

## 結果摘要 (v2 final)

- verdict: **NULL** (但 narrative = "median-under-QLIKE null"，per Codex v2 framing)
- τ=0.95 emp coverage 96.07% (gap +1.07pp), Kupiec UC p=0.062 邊際 PASS
- τ=0.99 emp coverage 99.26% (gap +0.26pp), Kupiec UC p=0.318 PASS
- DM qmed vs OLS QLIKE: stat<<0 p≈0.000 顯著 NEGATIVE
- 解讀：使用 QLIKE（對 conditional mean 一致的 loss）評估 q50 conditional median，目標函數不對稱 → q50 系統性 underforecast → DM 顯著為負 = 預期且具資訊量的 null result
- **不是** 「quantile HAR 全失敗」：tail (q95/q99) coverage 與 Kupiec 表現 OK，可獨立服務 risk-management 上界
- 後續：K1402b rolling refit / K1402c log-QR / K1402d quantile-implied mean vs OLS 公平比較
