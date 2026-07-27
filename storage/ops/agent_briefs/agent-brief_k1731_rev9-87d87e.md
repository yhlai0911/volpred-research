# K1731 arm B rev9 — bounded canonical claim-surface remediation

**Model**: opus / xhigh (per model_router)
**Task id**: assign_k1731_rev9
**Work in-place**: `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731` (branch `wt/dispatch-slot-1-bd00f90a-k1731`, HEAD f5338d54d).
**絕對禁止**：`git worktree remove`、建新 worktree、回退/覆蓋 f5338d54d 之後任何 F1/F3 commit、寫 `storage/memory/knowledge.json`、merge worktree、重跑估計 (re-estimation)。修正**套在現行 branch 上**，commit 後留在 branch（主線程後續 fire 收）。

## 背景

Codex round 8 對 frozen target `bb57bda98` 裁決 **FAIL**（完整裁決見 canonical repo `storage/ops/codex_reviews/k1731_armB_rev8_verdict.md`）。唯一 blocking finding：canonical finalizer 仍在 `ARM_A_ENGINE_ISSUES[0].why_it_matters` 把 low PIP 稱作 "evidence of no effect"，並宣稱 "the arm B null rests most solidly on CPI, UNRATE, VIX and TERM"。這段文字由 finalizer 重生到全部三份 results JSON（含唯一可引用的 primary artifact），與 README / headline_verdict 的 claim downgrade 矛盾。107-check gate 的 artifact prose scan 只掃 nested rows / headline_verdict / cross_arm_comparison、concept scan 只掃 README，因此漏掉這個 surface → silent false pass。另有一個 non-blocking gate hole：`k1731_rev8_drift_check.py` 不會因 numeric additions/removals 而 FAIL。

## 待辦（逐條，全部 bounded、不重跑估計）

1. **修文字**：`experiments/k1731/k1731_finalize_report.py` 的 `ARM_A_ENGINE_ISSUES[0].why_it_matters`（約 line 277-287）。
   - 移除任何把 low PIP 稱為 "evidence of no effect" 的措辭。
   - 移除 "the arm B null rests most solidly on CPI, UNRATE, VIX and TERM" 這類宣稱建立 OOS null 的措辭。
   - 改寫成：只支持 **under-this-prior 的 weak in-sample selection**，並**明說此結果不建立 OOS null**（in-sample PIP 在此 prior 下偏低，僅代表這個 selection 弱、不能外推成 OOS 無效果）。與 README / headline_verdict 的 downgrade 口徑一致。
2. **由 canonical finalizer 重生三份 results JSON**（`k1731_gevreg_midas_ssvs_returns_results.json` / `_corrected.json` / `_corrected_rev5.json`）——**禁止手改 JSON**。重生後做獨立 leaf diff（排除 `finalized_utc`）：**numeric change/add/remove 必須 = 0，renamed numeric leaves 值 exact 不變**（只有那段 why_it_matters 文字 leaf 改變）。
3. **擴 `k1731_armB_verification.py`**：artifact claim scan 必須涵蓋 `armA_engine_issues`（全部三份 artifact，不只 nested rows / headline_verdict / cross_arm_comparison）。加 **negative control**：塞回舊的 null-phrase（"evidence of no effect" / "arm B null rests"）時 gate 必須 exit 1。
4. **補 `k1731_rev8_drift_check.py`**：numeric additions/removals 也必須讓 gate FAIL（目前只擋 changed leaves + interval mismatch）。加 regression test / negative control 證明新增或移除一個 numeric leaf 會 FAIL。
5. HEAD 已含 bb57bda98 後的 F1/F3 commits — 不得回退或覆蓋。修正套在現行 branch，commit 後**重新建立完整 current claim-surface freeze**（更新 freeze txt + SHA-256）。
6. **跑全部 gate**：108-test nested-DM ratchet、arm-B verification、3834-leaf regression/drift gates。逐一貼出實際 PASS/FAIL 輸出（不要只說「通過」）。全部 PASS 才算完成本輪。

## 成功標準 / 產出

- 三份 results JSON 已由 finalizer 重生，leaf diff numeric change/add/remove=0（貼出 diff 摘要）。
- 兩個 gate 擴充完成，各附 negative control 證明舊 null-phrase / numeric add-remove 會 exit 1（貼出實際 exit code）。
- 108-test ratchet + arm-B verification + 3834-leaf regression/drift **全部 PASS**（貼出實際輸出尾段）。
- freeze txt + SHA-256 已更新。
- 全部改動 commit 在 `wt/dispatch-slot-1-bd00f90a-k1731` branch（**不 merge**）。
- 寫一份 `experiments/k1731/K1731_ARMB_REV9_COLLECTION.md`：列出本輪每項改動、gate 輸出、freeze hash、以及「送 Codex round 9」所需的 baseline/frozen target commit SHA。
- **result-artifact = `experiments/k1731/K1731_ARMB_REV9_COLLECTION.md`**（runner 只驗存在）。

## 誠信約束（AGENTS.md）

不可造假數字、gate 輸出要真實可驗證、null 如實報告、承認局限不過度宣稱、隨機程序固定 seed。任何 gate FAIL 就如實回報 FAIL 並停下（不要繞過、不要 `--force`、不要 `--no-verify`）。
