# K981 Codex Primary-Path Review

**Date**: 2026-05-16  
**Reviewer**: Codex CLI (gpt-5.4, session 019e2d59)  
**Verdict**: **CONDITIONAL_PASS**  
**Tokens used**: 68,992  
**Prior review**: Gemini CONDITIONAL_PASS (k981_post_publish_codex_review.md)

---

## Summary

無直接 lookahead bias。HAR 路徑乾淨。Wavelet 路徑有「過度保守的一日額外 lag」（t-2 而非 t-1），屬於對齊錯誤，不是 lookahead，但會不公平削弱 wavelet 模型，足以影響「wavelet 無效」的主結論。IS t-stats 計算方法不正確（intercept 與 X'X 不一致）。Gemini 發現的 5 個 issues 全部未修正。

---

## Issues

### Major — Wavelet feature 額外多一日 lag（Codex 新發現）
**Lines**: L95, L184

`compute_wavelet_features()` 在 index `t` 用 `values[t-window:t]`（看到 t-1），之後統一 `.shift(1)` 使模型在日期 `t` 實際只用到 `t-2` 的 wavelet 資訊。不是 lookahead，但偏移與 HAR 不對稱，「wavelet 無效」的結論需在修正後重新驗證。

**修正**：wavelet feature 定義改成 `values[t-window+1:t+1]` 再保留 `.shift(1)`；或維持現有 window 定義但不對 wavelet 特徵額外 `.shift(1)`。

### Major — max(pred, 0.0001) 造成 QLIKE artifact（Gemini 已知，未修正）
**Lines**: L171, L222

`WHAR_HAR_db4 QLIKE=474.48` 高機率是 hard floor artifact（`a/p - log(a/p) - 1` 被少數點爆掉），不是可直接比較的 loss 水準。

**修正**：把 floor 改成 train target 的 0.5%/1% quantile；或同時回報 unclipped diagnostics 與極端 loss 次數。

### Major — IS t-stats 算法不正確（Codex 新發現）
**Lines**: L460, L474

模型有 intercept，但標準誤用 `X'X` 而非含常數項的設計矩陣，`k = p + 1` 與 `XtX_inv = inv(X'X)` 彼此不一致，D2/D3/D4/D5/A5 顯著性可能失真。

**修正**：用含常數項的 OLS 設計矩陣重算，或改用 `statsmodels.OLS(...).fit()` 取 t-stats。

### Minor — n_oos 1824 vs 1823 traceability（Gemini 已知）
**Lines**: L67, L191, L246

`target = r2.shift(-1)` 邏輯正確，n_oos=1823 與最後一天無 target 一致。但 JSON 未明確區分。

**修正**：JSON 加 `n_oos_rows` 和 `n_oos_evaluated`；README 明寫「最後一天無 target」。

### Minor — HAR-vs-WHAR DM t=5.98 不在 JSON（Gemini 已知，未修正）
**Lines**: L427, L609

只 print 出、未寫入 `dm_tests`。

**修正**：`HAR_vs_WHAR_db4` 一併寫進 `results_json['dm_tests']`。

### Minor — IS R²=0.126 不在 JSON（Gemini 已知，未修正）
**Lines**: L485, L595

只 print 出，README 的數字無法直接由結果檔驗證。

**修正**：把 `wavelet_is_r2` 存進 JSON。

### Minor — 多個 DM 檢定無 multiple-testing correction（Gemini 已知，未修正）
**Lines**: L397, L421

7 個 DM 檢定無 Bonferroni/Holm correction。

**修正**：加 adjusted p-values，或明示未調整且主結論對調整穩健。

---

## Gemini Issues Status

| Issue | Status |
|-------|--------|
| WHAR_HAR_db4 QLIKE=474.48 artifact | 未修正 |
| 1824 vs 1823 traceability | code 邏輯正確，traceability 未修 |
| IS R²=0.126 不在 JSON | 未修正 |
| DM 無 multiple-testing correction | 未修正 |
| HAR-vs-WHAR t=5.98 不在 JSON | 未修正 |

---

## Lookahead 結論

**CLEAN**（但 wavelet 有不對稱 lag）：`target = r2.shift(-1)` 只預測 next-day r²，feature 未被污染。Wavelet 路徑是「過度保守」的額外 lag，不是 lookahead bias，但影響結論方向。

---

## Closure Condition

CONDITIONAL_PASS — knowledge.json 可寫入，但需明記：
1. 3 個 Major issues 尚未修正
2. Wavelet extra-lag 修正後需重跑，結論可能改變（NULL result 需再驗）
3. IS t-stats 修正後需重驗 wavelet component 顯著性
