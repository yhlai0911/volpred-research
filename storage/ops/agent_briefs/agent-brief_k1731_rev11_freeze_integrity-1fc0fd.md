# K1731 arm B rev10 → rev11：freeze-integrity 根因修復（先原子化重凍結，再送審）

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Pool task**: `assign_d696156d` (P1, urgent lane)
**Worktree (你唯一可寫的地方)**: `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`
**上游 verdict**: `storage/ops/codex_reviews/k1731_armB_rev10_verdict.md` → **VERDICT: FAIL**

---

## 0. 主線程已驗證的事實（不要重查，直接用）

派工前主線程已獨立複驗，以下是實測結果，不是轉述：

**A. 目前 freeze manifest 的 35 條中，恰好 3 條 byte-identity 不符**（與 Codex 回報一致，之後未再新增漂移）：

| 檔案 | manifest expected | 目前 actual | 目前 mtime |
|---|---|---|---|
| `experiments/k1731/README.md` | `2f9efd…` | `38bedc…` | 2026-07-28 15:04:50 |
| `experiments/k1731/k1731_armB_traceability_rows.json` | `bb08cf…` | `234f56…` | 2026-07-28 16:59:53 |
| `experiments/k1731/k1731_armB_verification.py` | `6ee4fa…` | `e301ed…` | 2026-07-28 15:04:36 |

**B. 時間軸證明根因是「凍結與送審之間有寫入」，不是這 3 個檔本身有問題**：
- `storage/ops/codex_reviews/k1731_armB_rev10_freeze.txt` 的 mtime = **2026-07-27 12:39**（且檔頭自述「frozen 2026-07-27 by hourly-slot-1-…」→ **人手維護的清單**）
- 上述 3 個檔被寫入的時間是 **2026-07-28 15:04 / 16:59**（凍結之後 ~27 小時）
- Codex 在 **2026-07-28 18:51** 才讀 bytes → 必然對不上

**C. 07-28 那批寫入是「合理的」而非意外**：work_log `2026-07-28T15:06:37` 記錄同一 worktree 補完 merge 側 artifact gate（`reproduce_spec.json`，commit `cd25c295a`）。`experiments/k1731/reproduce_spec.json` 現存（mtime 2026-07-28 14:57）。
→ **因此正確解法是「重新凍結目前這份完整 claim surface」，不是把 3 個檔還原回舊 bytes。** Codex 原話也給了這兩條路，選後者。

**D. 已有 canonical claim-surface 述詞可用，不要自己另發明一套**：
`scripts/experiment_claim_surface.py::is_experiment_claim_surface_file`（26 行、stdlib-only、單一 owner）。
現有 consumer：`scripts/experiment_gates.py`（merge certification gate）、`scripts/audit_nested_dm_misuse.py`、`scripts/tests/test_experiment_gates.py`、`scripts/tests/test_merge_worktree.sh`。

---

## 1. 要修的是流程，不是那 3 個檔（bounded remediation，4 項全做）

> 純粹改回 3 個檔 = 止血（contained），下一輪照樣再犯。AGENTS.md「問題結案五步 Gate」要求做到
> `root_cause_fixed_and_verified`，也就是**制度化寫回**，讓同類錯誤無法再靜默發生。
> 這與 2026-07-22 K1708 的教訓同一類：artifact 描述的不是產生它的那次執行。

### 項目 1 — freeze 清單改由程式在 run-time 產生（禁止人手維護）

在 **`scripts/experiment_gates.py`** 新增兩個 subcommand（沿用既有 argparse 風格；claim surface 一律呼叫
`experiment_claim_surface.is_experiment_claim_surface_file`，不得複製述詞）：

- `freeze --exp-dir experiments/k1731 --out <manifest path> [--extra <repo-level file> ...]`
  → 列舉 claim surface、算 sha256、**一次 snapshot 寫出** manifest；header 必須含：產生時間、產生它的 tool 版本/entrypoint sha、entry 數、以及「本檔由程式產生，人手編輯即失效」的宣告。
- `verify-freeze --manifest <path> [--json]`
  → 逐條重算並回報 `checked / matched / mismatched`；有任一不符 **exit non-zero**，且輸出 machine-readable JSON（供項目 2/3 使用）。

manifest 路徑用 **`experiments/k1731/k1731_armB_rev11_freeze.txt`**（放進 experiments/ 內，隨 worktree 一起 merge；不要再寫進 `storage/ops/codex_reviews/`，那是 rev10 出事的位置且不隨實驗一起版本化）。

### 項目 2 — 凍結之後到送審之間不得再有任何寫入；送審前先自跑一次全量驗證

- 順序必須是：**(i) 重跑該跑的 gates → (ii) 立刻 `freeze` → (iii) 立刻 `verify-freeze` 全數 PASS → (iv) 才可送審**。
- (ii) 與 (iii) 之間**不得有任何檔案寫入**（包含 README、圖、gate 產物、`__pycache__` 以外的一切）。
- 自驗結果寫成 **result artifact**（見 §3），內含：manifest 路徑、entry 總數、matched 數、每條 sha 的前 12 碼、產生時間、`verify-freeze` 的 exit code。

### 項目 3 — 把「freeze verification 必須先於讀 claims」寫進 gate ratchet

在 `scripts/experiment_gates.py` 內把這條做成**可執行的前置閘**：只要實驗目錄下存在 freeze manifest，
certification / review-prep 路徑就必須先跑 `verify-freeze`，FAIL 直接中止且**不進入 claim 檢查**
（正是 Codex 這輪的行為 —— 把它從「外部 reviewer 的自律」變成「本地機械閘」，這樣同類失敗在本地就被擋下，
不會再燒掉一整輪 Codex review quota）。

**測試是硬要求**：在 `scripts/tests/test_experiment_gates.py` 補測試涵蓋
(a) freeze→verify happy path 全數 match；
(b) 凍結後動一個 byte → `verify-freeze` 必須 exit non-zero 且指出正確檔名；
(c) ratchet：manifest 存在且 verify FAIL 時，claim 檢查**不被執行**（用 spy/flag 斷言，不要只看 exit code）。

### 項目 4 — merge 前置：`reproduce_spec.json` 必須是 run-time 產出

- canonical main 的 `scripts/check_experiment_artifacts.py` 要求 `experiments/k1731/reproduce_spec.json`，否則 `merge_worktree.sh` 會擋。
- 該檔已存在（2026-07-28 14:57）。**你要驗證它是 run-time 由 `volpred.research.reproduce_spec.finalize_experiment()` 產出、而非事後手補**：
  比對 spec 的 `entrypoint` sha / byte size 與 disk 上該 py 檔是否一致（K1708 正是這裡對不上）。
- 若對不上 → 依 AGENTS.md 用 `finalize_experiment(...)` 在收尾時重新產出，**不得手寫**。
- 開工前後各跑一次自查：`python3 scripts/check_experiment_artifacts.py check --path experiments/k1731`

---

## 2. 硬性禁止事項

- ❌ **禁止碰共用狀態**：`storage/reports/feed.json`、`storage/memory/knowledge.json`、
  `storage/memory/thinking_journal.json`、`storage/memory/experiment_experiences.json`、
  `storage/next_tasks.json`、Supabase / Mirror sync。**knowledge.json 只能主線程寫（K1259）**。
- ❌ **禁止** `git worktree remove --force`、`--no-verify`、force push。
- ❌ **禁止**手寫 / 手改 freeze manifest 的任何一行 hash。
- ❌ **禁止**為了讓 hash 對上而回改 07-28 那批合理變更（見 §0.C）。
- ⚠️ **repo-level 寫入僅限這兩個檔**：`scripts/experiment_gates.py` 與 `scripts/tests/test_experiment_gates.py`
  （項目 1/3 本質是 repo-level ratchet，屬既有 gate 的擴充；由正式 `merge_worktree.sh` 整合）。
  其餘一律只寫 `experiments/k1731/` 內。
- ✅ 數字一律從 `*_results.json` 程式化取得，不得從 README 或摘要轉抄。
- ✅ 完成後在 worktree 內 commit（訊息要交代 what + why，不可 "wip"）。

---

## 3. 成功標準（缺一不可）

1. `scripts/experiment_gates.py` 具備 `freeze` / `verify-freeze`，且 claim surface 來自
   `experiment_claim_surface.is_experiment_claim_surface_file`（無複製述詞）。
2. `scripts/tests/test_experiment_gates.py` 三個新測試全綠；既有測試不得回歸
   （跑 `uv run pytest scripts/tests/test_experiment_gates.py -q`，貼出結果）。
3. ratchet 生效：freeze verify FAIL 時 claim 檢查不執行（有測試斷言）。
4. `experiments/k1731/k1731_armB_rev11_freeze.txt` 由程式產生，且 `verify-freeze` **全數 PASS、exit 0**。
5. `experiments/k1731/reproduce_spec.json` 的 entrypoint sha/size 與 disk 一致；
   `check_experiment_artifacts.py check --path experiments/k1731` 通過。
6. **Result artifact（runner 只驗存在，務必寫出）**：
   `experiments/k1731/k1731_armB_rev11_freeze_selfcheck.json`
   欄位至少含：`generated_at`、`manifest_path`、`entries_total`、`entries_matched`、
   `verify_exit_code`、`tool_entrypoint_sha256`、`files`（每條 `{path, sha256}`）、
   `writes_after_freeze`（必須為 `false`，並說明你如何確認）。
7. **不要自己送 Codex round 11**（quota 與 enqueue 由主線程在 followup 收件時做）。

## 4. Mission sanity check

這是 arm B 第 11 輪。前 10 輪反覆失敗的**共同模式**是「claim surface 與被審 bytes 不同步」。
你這一輪的價值**不在於讓 Codex 這次過**，而在於**讓『凍結後又動檔』這種失敗方式在本地就不可能悄悄發生**。
若你發現本 brief 的某項前提與 worktree 實況不符（例如 3 個 mismatch 已變多），**如實回報並以實況為準**，
不要為了對齊 brief 而修改事實。Null / 部分結果如實報告；研究誠實 > 一切。
