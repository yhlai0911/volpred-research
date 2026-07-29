# K1731 worktree ↔ main 整合：解 stale-base，讓 F1 shard 可以開跑

**Model**: opus / xhigh (per model_router)

你在 worktree `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`（branch `wt/dispatch-slot-1-bd00f90a-k1731`，HEAD `4f15f040f`，29 個未合併 commit）內工作。**你的工作到「branch 已乾淨地站在 main 之上、測試全綠、已 commit」為止；不要自己合併回 main**（合併由後續 fire 走 `scripts/merge_worktree.sh`）。

## 為什麼要做這件事（三方循環相依的最後一條邊）

K1731 F1 的 nested bootstrap 兩個 shard job 現在是 `status=failed, exit_code=2`：

- `k1731-f1-boot-c0-parametric`（c=0, B=200）
- `k1731-f1-boot-c0-block`（c=0, B=100, block_len=20）

失敗原因是 `compute_queue.py enqueue` 把 `--script` 解析到**主 repo root**，而 `experiments/k1731/run_nested_bootstrap_shard.py` 只存在於 worktree → file-not-found 秒殺。已於 2026-07-29 重新核對 `compute_queue.py enqueue --help`：**仍然沒有 `--cwd`**（只有 `enqueue-agent` 有），所以「先 merge 才能跑 shard」這個相依是真的、繞不掉。

原本的循環有三條邊，現在只剩一條：

1. ~~merge 被 `check_experiment_artifacts.py` 擋（knowledge.json 無 k1731 條目）~~ → **已解**：arm B 條目 `item_id=5a604fb2` 已於 2026-07-28T12:31 寫入 canonical knowledge.json，`check_experiment_artifacts.py check --path .../experiments/k1731` 現在回 **PASS**（knowledge entry + reproduce_spec.json，spec check: strict）。
2. ~~knowledge 條目寫不了~~ → 同上，已解（且射程只到 arm B，沒有替 F1 預寫任何結論 —— 請維持這個界線）。
3. **merge 被 stale base 擋** ← **這就是你要修的**。

## 症狀（2026-07-29 19:2x 實測）

`bash scripts/merge_worktree.sh --dry-run dispatch-slot-1-bd00f90a-k1731` 回：

```
[STALE-BASE ABORT] worktree base 落後 main 1233 commits，且雙方修改同一路徑：
    scripts/audit_dm_hac_lag.py
    scripts/audit_fevd_ordering.py
    scripts/audit_nested_dm_misuse.py
    scripts/experiment_gates.py
    scripts/tests/test_experiment_gates.py
    scripts/tests/test_nested_dm_misuse_ratchet.py
    storage/ops/codex_reviews/k1731_armB_rev9_freeze.txt
    storage/ops/nested_dm_misuse_baseline.json
[WHY] 禁止交給 -X ours 靜默裁決；86e142305 曾因此相對 worktree parent 產生 +0/-192。
```

merge-base = `a2bcd7e143c1e7dcb67b334d8a3064cf82cf0050`。

## 已幫你排除的部分（不必重查，但要驗證我沒看錯）

逐檔比對 base / main / worktree 三方 blob sha 的結果：

| 路徑 | 判定 |
|---|---|
| `scripts/audit_dm_hac_lag.py` | **main == wt**，無需處理 |
| `scripts/audit_fevd_ordering.py` | **main == wt**，無需處理 |
| `storage/ops/codex_reviews/k1731_armB_rev9_freeze.txt` | **main == wt**，無需處理 |
| `scripts/audit_nested_dm_misuse.py` | 真分歧（wt 2782 行 / main 2771 行） |
| `scripts/experiment_gates.py` | 真分歧（**wt 1069 行 / main 681 行**，wt 多 465 行） |
| `scripts/tests/test_experiment_gates.py` | 真分歧（wt 586 / main 426） |
| `scripts/tests/test_nested_dm_misuse_ratchet.py` | 真分歧（wt 1479 / main 1448） |
| `storage/ops/nested_dm_misuse_baseline.json` | 真分歧（wt 484 / main 488 行，雙向都有增刪） |

`experiments/k1731/` 在 main **完全不存在**（`git ls-tree main experiments/ | grep k1731` = 0），所以實驗檔本身不會衝突；衝突全部集中在上面 5 個共享檔。

wt 側那 465 行 `experiment_gates.py` 增量是 rev11/rev12 的 freeze-integrity gate 與 ratchet 工作（commit `223f85081` "make freeze integrity a local gate, not reviewer discipline"、`4f15f040f` "repair the crashed gate at its root, certify rev11"）。**main 沒有這些**，所以不能無腦取 main。

## 你要做的

1. **先讀**：`docs/error_log.md`（2026-07-04 K1618 條、86e142305 那次 `-X ours` 事故）、worktree 內 `experiments/k1731/README.md` §11.x、`k1731_armB_rev12_gatefix_report.json`、`k1731_armB_rev11_freeze_selfcheck.json`。
2. **整合 main 進 branch**。`git rebase main` 與 `git merge main` 都可以，自己判斷哪個對這 29 個 commit 比較不會反覆解同一個衝突；**選了要在報告裡寫理由**。
3. **逐檔解 5 個真衝突**，每一檔都要在報告裡回答：main 這 1233 commit 對這個檔做了什麼、wt 這邊的意圖是什麼、你保留誰、為什麼合起來仍然正確。
   - `experiment_gates.py` / 兩個測試檔：wt 的 freeze-integrity gate 與 ratchet **必須存活**（那是 rev11/rev12 的成果），同時 main 後來對這個檔的修改也不能被吃掉。
   - `nested_dm_misuse_baseline.json` 是 ratchet baseline：**不是靠手改數字對齊**，要理解 baseline 語意後產生正確內容（若有 regenerate 腳本就用腳本）。
4. **重跑驗證**（全部要綠，貼實際輸出到報告）：
   - `uv run pytest scripts/tests/test_experiment_gates.py -q`
   - `uv run pytest scripts/tests/test_nested_dm_misuse_ratchet.py -q`
   - `uv run python scripts/check_experiment_artifacts.py check --path experiments/k1731`
   - `uv run python scripts/audit_nested_dm_misuse.py`（若它是可獨立跑的 audit）
5. **commit** 在 branch 上（訊息說明整合了什麼、解了哪些衝突）。
6. **產出報告** `experiments/k1731/k1731_main_integration_report.json`（就是本 job 的 result artifact），至少含：
   ```json
   {"integration_method": "rebase|merge", "method_rationale": "...",
    "merge_base_before": "a2bcd7e1...", "head_after": "<sha>",
    "conflicts": [{"path": "...", "main_side_intent": "...", "wt_side_intent": "...",
                   "resolution": "...", "why_correct": "..."}],
    "tests": [{"cmd": "...", "exit_code": 0, "output_tail": "..."}],
    "artifact_gate": "PASS|FAIL",
    "ready_for_merge_worktree_sh": true,
    "residual_risks": ["..."]}
   ```

## 成功標準

`bash scripts/merge_worktree.sh --dry-run dispatch-slot-1-bd00f90a-k1731` 不再 STALE-BASE ABORT，且上述測試全綠、artifact gate PASS、報告已寫。**你自己可以跑這個 --dry-run 驗收**（dry-run 不動 main）。

## 禁止

- ❌ `-X ours` / `-X theirs` 靜默裁決任何一個真衝突（就是 86e142305 那次事故的成因）
- ❌ 自己跑 `bash scripts/merge_worktree.sh`（**不加 --dry-run**）或任何把 branch 推進 main 的動作
- ❌ `git worktree remove --force`（機械攔截，且會毀掉 29 個 commit）
- ❌ 動 `storage/memory/knowledge.json`、`storage/reports/feed.json`、`thinking_journal.json`、`experiment_experiences.json`（worktree agent 禁改共享狀態；K1259）
- ❌ 為了讓測試變綠而弱化 gate / 刪測試 / 調寬 baseline 容忍度 —— 那是把 ratchet 拆掉，不是整合
- ❌ 替 F1 預寫任何 bootstrap 還沒跑出來的結論（F1 的 result artifact 依設計此刻本來就不該存在）
- ❌ 用 `config/experiment_artifact_exclusions.json` 繞 gate

## 交接

parent task = `k1731_f1_bootstrap_merge_deadlock`（Exit A，已在 work_log 記錄選擇理由）。
你完成後，後續 fire 會在 PHASE A 收件：跑正式 `merge_worktree.sh` 合併，然後
`uv run python scripts/compute_queue.py requeue --id k1731-f1-boot-c0-parametric` 與 `--id k1731-f1-boot-c0-block`
把兩個 shard 放回去跑（README §11.6 指明 requeue 是預定回收路徑）。
