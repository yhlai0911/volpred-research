---
name: memory-health
description: >
  Diagnose and repair VolPred shared-memory integrity problems. Use when the
  memory health summary reports duplication, invalid structure, missing
  experiment knowledge, provenance failure, or abnormal growth.
context: fork
agent: fresh-context-worker
user-invocable: true
---

# Memory Health

本 skill 擁有 shared-memory integrity diagnosis；一般 experiment knowledge integration
由 `agent-result-verification` 執行。

## Preflight

先讀：

- `.claude/skills/autonomous-research/references/operations-core-contract.md`
- `.claude/rules/experiments.md` 的 K1259 gate
- `src/volpred/memory/system.py` 的 canonical writer seam

每次 invocation 執行：

```bash
uv run python scripts/task_pool_control.py status
uv run volpred ops memory-health-summary
```

Task mode只影響是否能建立修復task；health diagnosis保持read-only。

## 1. Evidence

以summary輸出的machine-readable fields為準：

- per-file status、bytes、entry count與parse result
- knowledge duplicate count
- missing/unrecorded experiment evidence
- worktree/orphan signal
- recommended action

不在skill保存固定MB門檻或「正常筆數」；門檻由summary implementation與tests擁有。

對單一 finding 做 bounded inspection，保存：

- affected item ids / experiment ids
- first/last occurrence
- writer/provenance receipt
- file hash與entry count
- upstream caller與downstream index/sync影響

只讀完整population或明示sampling/blind spots；不能只抽疑似subset後宣稱clean。

## 2. Root-cause classification

| Finding | Root-cause candidates |
|---|---|
| duplicates / growth | writer idempotency、merge path、retry、identity key |
| invalid/truncated JSON | non-atomic writer、concurrent overwrite、crash |
| missing knowledge | post-experiment intake、review/K1259 gate、artifact handoff |
| provenance violation | bypass writer、缺experiment identity/reviewer |
| stale index | index-maintenance handoff或schedule receipt |
| orphan worktree | incomplete experiment delivery；交給worktree intake |

根因不明時blocked；dedup一次只算contained。

## 3. Legal repair paths

### Existing knowledge correction

先dry-run，再apply：

```bash
uv run python scripts/revise_knowledge_entry.py \
  --item-id <item-id> \
  --actor "<owner>" \
  --reason "<evidence-backed reason>" \
  --set-file content=<reviewed-content-file> \
  --dry-run
```

確認diff後以相同參數改為`--apply`。該script走shared lock、canonical write、
K1259 validation與writer log。

### New experiment knowledge

回到 `agent-result-verification`：

- 數字從canonical result程式化取得
- record帶experiment provenance、verdict與reviewer
- 經`src/volpred/memory/system.py` canonical writer寫入
- 寫後回讀item id

Agent/worktree只提供proposal，不寫shared memory。

### Duplicate or structural repair

若repository沒有對應的tested canonical repair command：

1. 先保存pre-image hash、entry count與duplicate population。
2. 修writer/root cause與regression。
3. 建立受鎖、atomic、idempotent、K1259-aware repair path。
4. Dry-run列出exact affected ids。
5. Apply後read-back，再重跑summary和provenance validator。

不能用editor、重導或臨時array rewrite直接覆蓋shared memory。

### Worktree finding

交給 `worktree-merge-verification` / canonical post-experiment intake。先保留worktree；
不在memory skill清理。

## 4. Validation

```bash
uv run volpred ops memory-health-summary
uv run python scripts/validate_knowledge_provenance.py
uv run volpred ops knowledge-index-maintain --stub-if-no-work
uv run volpred ops knowledge-index-summary
```

依finding再驗證Mirror/Supabase或article/topic consumers的read-back。Local parse成功不等於
下游收到正確entry。

若需新增repair task，每次mutation前重讀task-pool mode；queued mode走canonical producer，
direct/restore/unreadable mode不新增legacy identity。

## Completion

- [ ] Symptom有hash/count/item-level evidence
- [ ] Root cause定位到writer/merge/intake/provenance/index
- [ ] Repair走canonical lock/writer，沒有direct JSON overwrite
- [ ] K1259 validator與memory summary通過
- [ ] Index及必要remote consumer已read-back
- [ ] Regression使同類錯誤無法靜默重現

缺任一步只能回報`contained`或blocked。
