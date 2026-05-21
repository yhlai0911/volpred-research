# K901 Codex Primary-Path Review

**Date**: 2026-05-16  
**Reviewer**: Codex CLI (gpt-5.4, session 019e2d57)  
**Verdict**: **FAIL**  
**Tokens used**: 51,380

---

## Summary

Lookahead bias 主幹邏輯乾淨：`run_vt()` 的 `signal = raw_signal.shift(1)` (L182) 方向正確，DM/Spearman 主幹無明顯寫反。**FAIL 原因**：GJR 估計失敗被靜默吞掉 + Bootstrap 無固定 seed，不可重現。

---

## Issues

### Major — GJR-GARCH 失敗被靜默吞掉
**Lines**: L48, L224, L243-245, L249-265, L421-424

全域 `warnings.filterwarnings("ignore")`、`fit(..., show_warning=False)`、bare `except: pass` 把所有 convergence 問題藏起來；`res.convergence_flag != 0` 的結果仍被 append，rolling mean / `pct_significant` 照算。`gjr_gamma_full` 與 `gjr_gamma_rolling` 在失敗或半失敗估計下看起來像正常結果。

**修正**：移除全域 ignore；只捕捉並記錄 `arch` 相關 warning/exception；summary 只納入 `converged == True` 且 `gamma/tstat/pval` 有限值的視窗；把 `n_attempted / n_failed / n_converged` 寫進結果 JSON。

### Major — Bootstrap Sharpe CI 無固定 seed
**Lines**: L270-289

使用全域 `np.random.choice`，不可重現，直接違反專案「隨機程序固定 seed」規則。

**修正**：加入 `BOOTSTRAP_SEED = 42`，改用 `rng = np.random.default_rng(BOOTSTRAP_SEED)`，並把 seed 寫入 results。

### Minor — 第一個回測日 fillna(1.0) 補值
**Lines**: L182-185, L324-328

先切 `valid_idx` 再 `shift(1)` 導致第一筆 signal 為 NaN，被 `fillna(1.0)` 覆蓋成滿倉。不是未來函數，但與「VIX_{t-1} determines weight」語義不完全一致。

**修正**：先在完整 `merged[col_vix]` 上建 signal 再對齊回報，或 lag 後 drop 第一筆投組回報。

### Minor — 結果合理性檢查只有 print
**Lines**: L340-342, L355-359, L514-517

`Sharpe > 2x baseline` 只是 warning print，不會阻止輸出；MDD improvement 無 sanity band。

**修正**：把 `Sharpe>2x baseline`、異常 MDD 改善、`DM |t|>3` 做成結構化 `review_flags` 欄位。

### Minor — Spearman 被全域 suppress warnings 覆蓋
**Lines**: L490-500, L48

global suppress 會把 constant-input / NaN 警告吞掉，最後可能靜默 `nan`。

**修正**：顯式檢查輸入是否常數、樣本數是否足夠。

---

## Lookahead 結論

**CLEAN**：`signal = raw_signal.shift(1)` (L182) 正確；DM test/Spearman 方向無明顯違規。

---

## Action Required

- 修正 2 Major issues → 重新執行實驗 → re-submit Codex review
- 修正前**不得**寫 `knowledge.json` entry
