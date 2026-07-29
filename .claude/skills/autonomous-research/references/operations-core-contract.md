# Research Domain Operations Core Contract

本文件是 research、data、experiment intake 與 memory skills 共用的控制面契約。
各 skill 只保留自己的研究流程，不另抄 task mode、排程、路徑、Git 或 writer 規則。

## 1. 每次動作都重讀 task-pool mode

每次準備 claim、start、complete、annotate、handoff、refill 或新增 task 前，都重新執行：

```bash
uv run python scripts/task_pool_control.py status
```

這個命令讀取 `storage/ops/task_pool_mode.json` 與配對的 canonical queue；同一 session
稍早的結果、handoff 快照與記憶都不能取代本次 read-back。

依回傳狀態處理：

| 狀態 | 可做的事 |
|---|---|
| `enabled=false`, `mode=queued_execution`, queue readable | 既有 task 的 claim/start/complete 走 `scripts/task_pool_claim.py`；新增工作只走 canonical producer/writer。 |
| `enabled=true`, `mode=direct_execution` | 不新增 task identity、不 refill legacy queue；只完成使用者當前直接交付或 receipt 明列的 preserved task。 |
| `mode=restore_in_progress` | 停止 queue mutation，交由 owner 完成 restore。 |
| state/queue unreadable、path mismatch、未知 mode | Fail closed；保存錯誤輸出並回報，不能猜測 mode。 |

Task pool mode 只控制 work admission，不控制研究真實性 gate，也不是 business clock。

## 2. Operations Core 是唯一排程 owner

- `config/runtime_schedules.json` 是 schedule spec。
- `.schedule_materialization` 指定目前 owner、generation、receipt path 與 active mode。
- 排程是否真的執行，以該 spec 指向的 terminal receipt 及下游資料 read-back 為證。
- Wrapper、互動 session、手動 recovery 都不是第二個排程 owner。
- Skill 不保存 cron 表、服務 ID、主機安裝路徑或「目前幾點執行」的副本。
- 變更排程時先改 canonical config，再走 Operations Core owner reconciliation 與自然 fire
  驗證；不能另加一個時鐘來止血。

查單一 job 時，動態讀：

```bash
jq --arg id "<job-id>" \
  '.schedule_materialization,
   (.system_crontab.items[] | select(.id == $id))' \
  config/runtime_schedules.json
```

## 3. 路徑與 target 不硬編

- 本地 canonical state 以 `storage/` 為源頭。
- Runtime/frontend/deploy target 從 `config/project_targets.json` 或
  `src/volpred/config/runtime.py` 取得。
- 外部資料根目錄由 collector、manifest、config 或明確環境設定解析；skill 不保存使用者
  home、Dropbox、worktree 或服務 ID 的絕對路徑。
- 正式實驗把每個 resolved input 的來源、期間、hash/identity 寫入
  `reproduce_spec.json`；不能靠 skill 內的歷史路徑復現。

## 4. 實驗 identity 與 artifact gate

新 K 編號一律由 registry 保留：

```bash
uv run python scripts/kid_reserve.py reserve \
  --owner "<owner>" --topic "<topic>"
```

實驗腳本必須在同一次 runtime 收尾呼叫：

```python
from volpred.research.reproduce_spec import finalize_experiment

finalize_experiment(
    results=payload,
    entrypoint=__file__,
    canonical_result="<experiment_id>_results.json",
    inputs=inputs,
    seeds=seeds,
    started_at=started_at,
)
```

它同時建立 canonical results 與 `reproduce_spec.json`，並讓 code trace 指向真正產生
結果的 bytes。

若 runtime-pinned entrypoint 要改，先保存原始 bytes：

```bash
uv run python scripts/preserve_gate_blob.py preserve \
  --path experiments/<experiment_id>/<entrypoint>.py \
  --reason "<why the gate is changing>"
```

收尾 gate：

```bash
uv run python scripts/experiment_gates.py run \
  --path experiments/<experiment_id>
uv run python scripts/check_experiment_artifacts.py check \
  --path experiments/<experiment_id>
```

`review_verdict.json` 必須由 `experiment_gates.py verdict-template` 產生並 pin 當下 claim
surface。審查後若 code、README 或 result 改動，就重審；不能手改 verdict 或 checksum。

## 5. Knowledge writer / K1259

- Worktree/background agent 只能產出 evidence 與 knowledge proposal，不能寫 shared memory。
- Main thread 從 canonical results 程式化擷取數字，再走
  `volpred.memory.provenance.validate_provenance` 與
  `MemorySystem._append_to_index("knowledge.json", record)` 的 canonical writer seam。
- `PASS` 必須帶 experiment provenance 與 reviewer；`CONDITIONAL_PASS` 必須帶
  experiment provenance。詳細欄位見 `.claude/rules/experiments.md` 的 K1259 gate。
- 修訂既有 entry 走 `scripts/revise_knowledge_entry.py`，先 `--dry-run`，再 `--apply`。
- 寫後回讀 item identity，並執行 `scripts/validate_knowledge_provenance.py`。
- 不以 editor、重導、臨時 JSON rewrite 或 array overwrite 修改 shared memory。

## 6. Git 與 worktree delivery

- Shared checkout 的 commit 交易只走 `scripts/git_writer_lock.py commit`，傳 actor、
  task id 與 exact paths。
- Experiment worktree 的成果只包含 `experiments/<experiment_id>/`，完成前同樣用受鎖的
  exact-path commit 交易保存。
- 主線程整合只走：

```bash
bash scripts/merge_worktree.sh <worktree-name>
```

- Merge 失敗時保留 worktree、完整輸出與 artifact identity；交給 merge workflow
  根因處理，不自行移除 worktree、改 branch 或拼接 commit。
- 「指令沒有報錯」不是完成；必須回讀 main 上的 artifact hash、gate 結果及下游
  acknowledgement。

## 7. 結案口徑

- `contained`：只重跑、補資料、保留 artifact、暫時恢復可用。
- `root_cause_fixed_and_verified`：症狀證據、根因層級、底層修正、回歸及下游回讀、
  制度化 guard 五步都完成。

同類問題尚可靜默復發時，不得使用後者。
