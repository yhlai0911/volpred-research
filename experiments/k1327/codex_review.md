# K1327 Codex Code Review

**Date**: 2026-06-14 14:02 台灣時間
**Reviewer**: Codex CLI 0.137.0
**Verdict**: **FAIL**
**Triggered by**: `K1327_codex_review_followup`

## Verdict

Lookahead safety、固定 seed、results 可重跑都合格；但核心模型比較**沒有 matched training window / refit cadence**，因此目前 `CONDITIONAL_PASS` 不能當成可寫入 knowledge 的結論。

## What Passed

1. **Lookahead safety is explicit**
   - `experiments/k1327/k1327.py:116` 對每個因子都先 `shift(1)` 再做 rolling mean，符合 `signal from t-1, return at t`。

2. **Seed is fixed and rerun is reproducible**
   - `experiments/k1327/k1327.py:24` 定義 `SEED = 42`
   - `experiments/k1327/k1327.py:298` 執行 `np.random.seed(SEED)`
   - 2026-06-14 互動重跑 `uv run python experiments/k1327/k1327.py`，`k1327_results.json` 維持 `best_model=MF_ElasticNet_static`, `verdict=CONDITIONAL_PASS`

## Issues

1. **Baseline vs challenger comparison is not matched** (`experiments/k1327/k1327.py:207-210`, `306-326`)
   - `HAR3` 用 `rolling=True, window=1000, refit_every=21`
   - 最佳 challenger `MF_ElasticNet_static` 用 `rolling=False`，也就是 expanding sample
   - 另兩個 rolling challengers 又改成 `refit_every=63`
   - 所以目前觀察到的 QLIKE 差異，混合了 model class、sample window、refit cadence 三種變化，不是乾淨的 apples-to-apples model test

2. **Current summary overstates what was learned** (`experiments/k1327/k1327.py:340-352`)
   - `best_model` 來自未 matched 的 `MF_ElasticNet_static`
   - `summary` 寫成「比 HAR3 低 QLIKE，但未達 Harvey > 3」容易讓 reader 以為差異主要來自 multifactor 結構
   - 其實更精確的說法應是：在這個不對稱設計下，expanding ElasticNet 得到較低 QLIKE；不能直接推論 adaptive multi-factor 本身優於 HAR

## Required Follow-Up

- 做 `K1327-v2`：
  - HAR 與 multifactor challengers 使用同一 train window
  - rolling 版本使用同一 refit cadence
  - 若要比較 static vs rolling，應明確拆成另一個 sensitivity block，而不是混在主 verdict
- 在 v2 完成前：
  - `k1327_results.json` 可保留作 audit artifact
  - **不可**把目前結論寫進 `knowledge.json`

## Bottom Line

K1327 目前是**可重現但比較設計未對齊**的中間結果。數字本身不是假的，但 method comparison 還不夠公平，故本次 Codex review 判定 **FAIL**。
