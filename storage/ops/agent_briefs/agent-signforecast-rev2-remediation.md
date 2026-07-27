# Remediation — direction_predictability_signforecast (Codex round 2 = FAIL)

**Model**: opus / max (per model_router, experiment, at_ceiling)
**Worktree (cwd)**: `.claude/worktrees/dispatch-slot-2-7087efc0-signfc`
**Experiment dir**: `experiments/direction_predictability_signforecast/`
**只准改此實驗目錄**，勿碰 worktree 內其他實驗。

## 背景

這是一個「方向（漲跌）可預測性的誠實 OOS 檢定」實驗（NULL 假設：方向不可預測、波動可預測）。
Codex round 2 審查判 **FAIL**，完整審查在 `storage/ops/codex_reviews/signforecast_rev1_verdict.md`（先讀完）。
凍結 sha256 見 `review_verdict.json`。禁止捏造數字，研究誠實 > 一切。

## 必修的 3 個 blocking defects

### Defect 1 — GARCH 靜默 fallback（違反 no-silent-fallback 宣稱）
- `direction_predictability_signforecast.py` py 45 全域 `warnings.filterwarnings` 關閉、不檢查 `arch` 的 convergence flag；只有 exception 才 log。
- 若參數非有限，`used_garch=False` 後直接進 EWMA 無 log（py 169、179–182）；有限性檢查漏 `mu` 與 `resid_prev`。NaN 可能被 `dropna()`（py 239–240）靜默刪。
- **修**：加入逐資產·逐塊的 GARCH 診斷（convergence status、是否 fallback、finiteness 檢查含 mu/resid_prev、被 dropna 刪除的列數），寫進 results.json（新欄位 e.g. `garch_diagnostics`）。README §方法 明確揭露 fallback 次數/比例。真正做到 no-silent-fallback。

### Defect 2 — DM 單尾 p 值誤讀
- README 把 DM 單尾 p 值解讀為 8/8 模型「顯著較差」；實際僅 **6/8** 在反方向 5% 檢定顯著。
- **修**：README 逐一列出 8 個 model×asset 的 DM 統計量與正確的單尾 p 值判定，明確標示哪 6/8 顯著、哪 2/8 不顯著。措辭改為精確計數。

### Defect 3 — 結論過度外推（failure-to-reject ≠ 證實 NULL）
- README 146/194 把 multiple-correction 後不顯著寫成「證實 NULL／證明假陽性」——**不可**。failure-to-reject 只能說「這組模型與特徵未找到穩健 edge」。
- 「波動率明顯可預測」僅有 OOS R²/QLIKE 點估，無正式顯著性檢定。
- 圖 `direction_vs_vol_predictability.png` 標題「variance is predictable OOS; sign is not」超出證據。
- **修**：
  1. 方向 NULL：加正式 **equivalence test（TOST）** 或明列最小經濟效果界線（MDE）+ **檢定力分析**，才可談「無法拒絕不可預測」；措辭嚴格改為 failure-to-reject，刪除「證實/證明」。
  2. 波動可預測：對 loss differential（HAR vs expanding-mean benchmark）做正式 **HAC DM 檢定**（可加 **stationary bootstrap** p 值），逐資產報告。只有通過才可說「顯著可預測」；0050.TW 負 R² 需在跨資產推論框架內誠實處理。
  3. 重繪 `direction_vs_vol_predictability.png` 標題，與實際檢定結論一致。

## 交付與驗收
1. 改 `direction_predictability_signforecast.py`（新診斷 + TOST/power + HAC DM/bootstrap），**確認所有特徵仍 `.shift()` causal、baseline 同 lag**，重跑產生新 `direction_predictability_signforecast_results.json` + 更新圖。
2. 更新 README（defect 2/3 措辭、defect 1 揭露），數字逐格對齊 results.json。
3. **重新凍結**：更新 `review_verdict.json` 的 `reviewed_sha256`（新檔雜湊），`verdict` 留白待 Codex 複審（不要自評 PASS）。
4. **不要 merge worktree、不要 force-merge、不要寫 knowledge.json**（主線程負責）。
5. `result-artifact` = `experiments/direction_predictability_signforecast/direction_predictability_signforecast_results.json`（收件時驗存在 + 含 garch_diagnostics + DM/TOST 欄位）。

收件後 followup：主線程送 Codex round 3 複審 3 個 defect 是否全數解除；PASS 才合併 + 記 knowledge。
