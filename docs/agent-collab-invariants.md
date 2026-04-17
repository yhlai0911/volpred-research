# Agent Collaboration Invariants

這份文件是 Claude Code 與 Codex (VS Code OAuth extension) 在本機 VS Code 共同操作這個 repo 時的**硬性 invariants**。任何寫入共享狀態的腳本 / skill / subagent 都必須遵守。

> 規則出處：`docs/project_improvement_status.md` Phase B（2026-04-17）。違反會造成 lost-update、knowledge 損毀或失蹤，過往紀錄見 `docs/error_log.md` 2026-04-11 / 2026-04-17。

## 1. Shared-state lock 命名規則

所有共享 JSON 寫入路徑都必須 wrap 在 `volpred.ops.shared_lock.shared_state_lock(name)` 之中。命名 convention：

| 目標檔 | lock name |
|--------|-----------|
| `storage/memory/<file>.json` | `memory_<stem>`（例：`memory_knowledge`、`memory_experiments`） |
| `storage/reports/feed.json` | `publisher_feed` |
| `storage/reports/<report>.json`（若未來有並發風險） | `publisher_report_<id>`（保留） |
| `storage/ops/tasks/*.json` + agents/executions/approvals | `control_plane`（由 `_plane_lock` 代表） |
| `experiments/` rewrite of text references | per-file `fcntl.flock` in-place（不走 shared_state_lock） |

鎖落在 `storage/ops/locks/<name>.lock`。互斥範圍：同主機所有 Python process。

## 2. Writer provenance log

每次共享 JSON 寫入都需呼叫 `volpred.ops.writer_log.append_writer_log(...)`，寫 JSONL 到 `storage/ops/writer_log.jsonl`。

欄位：
- `ts`（ISO 8601 UTC）
- `actor`（`VOLPRED_ACTOR` env var；否則 `unknown`）
- `subsystem`（`memory` / `publisher` / `experiments` / `control_plane`）
- `target`（相對路徑，如 `memory/knowledge.json`）
- `record_id`（可空）
- `result`（`ok` / `error: ...` / `reclaimed_from_*`）

失敗寫 log **不可** raise（best-effort）。

## 3. Actor identity

Claude Code 與 Codex 在啟動時各自設 env：

```bash
# Claude Code（啟動腳本或 shell profile）
export VOLPRED_ACTOR=claude

# Codex (VS Code extension) — 在 VS Code integrated terminal 內設
export VOLPRED_ACTOR=codex
```

沒設 = `unknown`，provenance 仍有效但作者欄無意義。

## 4. Stale reclaim（agent heartbeat 逾期）

`AGENT_STALE_SECONDS = 300`（`src/volpred/ops/local_control_plane.py:36`）。

觸發條件：agent 的 `heartbeat_at` 距 now > 5 分鐘。

效果（在 `claim_next_task` 入口執行一次）：
- 掃所有 `claimed` / `running` tasks
- 若 claimed_by 對應 session 已 stale → 將 task 回復為 `queued`，清 `claimed_by` / `claimed_at`
- Agent session 的 `claimed_task_id` 也 reset
- writer_log 記錄 `reclaimed_from_<status>_<agent>`

因此：agent 當機 / VS Code 關閉 > 5 分鐘，其 task 會自動被另一 agent 接手，不會死鎖。

## 5. Admin override claim

網站 `/admin/ops` 介面可觸發：

- `claim`：強制把 queued task 指派給 claude / codex（透過 `admin_override_claim(task_id, agent_name, actor)`）
- `complete` / `fail`：由 admin 強制關閉 claimed / running task（走 `complete_task` / `fail_task`）
- `rollback_restore`：還原指定 rollback point（走 `restore_rollback_point`，先 dry_run 再 force）

所有 admin-override 都會在 `writer_log.jsonl` 留下 `admin_override_claim_by_<agent>` 等記錄，`actor` 寫 admin 帳號。

## 6. 禁止事項

- 不可繞過 `shared_state_lock` 直接寫 `storage/memory/*.json` 或 `storage/reports/feed.json`
- 不可手改 `storage/ops/tasks/*.json`（只能走 `local_control_plane` 函式）
- 不可關閉 `writer_log.jsonl`（忘了加不違規，但寫入不可 silently 失敗）
- 不可在 agent 並發執行時同跑同一 experiment id（查 `experiments/` 與 `.claude/worktrees/`）

## 7. 驗證

- `uv run pytest tests/test_shared_lock.py tests/test_memory_system.py tests/test_publisher_provenance.py tests/test_stale_reclaim.py` 全綠
- `cat storage/ops/writer_log.jsonl | tail -10` 應該看到最近寫入紀錄
- `ls storage/ops/locks/` 顯示活躍 lock 名稱（lock 檔是 sentinel，內容空）
