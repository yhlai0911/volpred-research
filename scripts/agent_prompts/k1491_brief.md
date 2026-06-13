# K1491 brief — Crypto vol-of-vol → traditional tail spillover (methodology fix of K1490)

## 動機

K1490 嘗試檢驗加密幣 vol-of-vol（rolling-20d σ 的 σ）是否預測傳統市場（SPY/GLD/USO/TLT）的尾端事件。實驗已跑完 descriptive stats（OK）但**所有 8 個 Granger causality test 全失敗**：

```
"error": "granger_failed: The x values include a column with constant values
and so the test statistic cannot be computed."
```

根因：tail event indicator 用 `|r_t| > 2σ_{t-1}` binary，在 BTC/ETH vov 高時 SPY/GLD 對應視窗的 tail event 極稀疏（多為全 0 column），statsmodels 無法計算 Granger F-stat → 整檢定 N/A。

## 任務（K1491）

把 K1490 的 spillover detection 從 **binary tail indicator** 改為 **quantile-crossing signed series**（連續、resilient to sparsity）：

1. **新 indicator**: 對每個 traditional asset (SPY/GLD/USO/TLT) 計算 `tail_signal_t = max(0, |r_t| - q_{0.95}(|r|_{t-20:t-1}))` — rolling 0.95 quantile crossing 的量，always-positive continuous。
2. **Predictor**: 沿用 K1490 的 BTC/ETH `vov_20d` (rolling σ of σ_20d)，全部 `.shift(1)` 確保 no lookahead。
3. **Tests**:
   - Granger lag 1-5 from `vov` → `tail_signal` (continuous → continuous, 不會有 constant column)
   - Quantile regression q=0.95 of traditional return |r| on lagged crypto vov（已部分跑過，補完）
   - Bonferroni adjusted across 8 (BTC/ETH) × 4 (SPY/GLD/USO/TLT) = 8 pairs
4. **Verdict**: 比 K1490 同口徑 — 多少 pair 通過 p<0.05 / p<0.10 / Bonferroni。

## Context

- 看 K1490 原始 script: `experiments/k1490/k1490.py`（複用 data loading + vov 計算邏輯）
- 看 K1490 results.json: `experiments/k1490/k1490_results.json` (descriptive 可重用)
- 防錯: lookahead — predictor 全 `.shift(1)`; seed=42 全程固定
- Pooled-MLE 不適用（純 reduced-form Granger / quantile reg，非 ML）

## 成功標準

1. `experiments/k1491/k1491.py` + `k1491_results.json` + ≥1 圖
2. Granger 8 pairs 全有 valid F-stat + p-value（沒任何「constant column」error）
3. README.md 寫差異說明 + 比較 K1490 vs K1491 結果
4. verdict_summary.interpretation 真實反映 8 pairs 的 Bonferroni 結果（NULL / PARTIAL / SIG）
5. **Codex review 必跑**（fallback: feature-dev:code-reviewer subagent）

## Scope 限制

- 只產 `experiments/k1491/` 內檔案
- 禁改 feed.json / knowledge.json / paper / supabase sync
- 不寫 knowledge.json，由主線程驗證 Codex review verdict 後寫
- 50 分鐘 hard cap（hourly fire budget）

## 文獻參考

- Diebold & Yilmaz (2012) — spillover index methodology
- Bouri et al. (2017) — crypto vol spillover to traditional assets
- Patton (2011) — quantile regression robustness

## 紀律

- 任何 random process 固定 seed=42
- 圖表 PNG 不放 placeholder
- script 內 logging 含 timestamp + git rev
