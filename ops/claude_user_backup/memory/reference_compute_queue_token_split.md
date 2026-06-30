---
name: Compute queue token-conserving split architecture
description: 將 heavy CPU work (MLE/bootstrap/data fetch) 與 Claude decision/writing 分流，~75% K-experiment token 節省
type: reference
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
**Architecture**: 兩階段 split — heavy compute 走本地 worker（0 Claude tokens），decision/interpretation 走 Claude agent（light tokens）。

**Why**:
- 用戶 2026-05-12 觀察：每小時實際用 Claude tokens 的決策時間很短，但 agent runtime 大部分花在 Python compute
- Token economics: K-experiment 派 1 agent ~100K tokens；分流後 0 + 25K = ~75% 節省
- 每天 24 派工 × 平均 60K 節省 ≈ 1.4M tokens/day（接近 Max 20x 1.5% quota）

**元件**:

1. **Queue**: `storage/ops/compute_queue/<id>.json`
   - Schema: id / title / script_path / interpreter / status / queued_at / started_at / completed_at / exit_code / result_artifact / claude_followup{brief, task_type, priority} / followup_dispatched / timeout_seconds
   - States: queued → running → completed / failed

2. **CLI** (`scripts/compute_queue.py`):
   ```bash
   uv run python scripts/compute_queue.py enqueue \
     --script experiments/k1320/k1320.py \
     --title "K1320 HAR-GNN multistart MLE" \
     --result-artifact experiments/k1320/k1320_results.json \
     --followup-brief "解讀 byte-match verdict + 決定下一步派 K-x follow-up" \
     --followup-task-type paper_review \
     --timeout 3600
   uv run python scripts/compute_queue.py list --completed-pending-followup --json
   uv run python scripts/compute_queue.py mark-followup-dispatched --id <id> --next-task-id <task_id>
   ```

3. **Worker**: `scripts/cron_compute_worker.sh` + `~/.volpred/bin/` copy + crontab `*/15 * * * *`
   - Lock file prevents concurrent runs
   - Stale lock > 6h auto-released
   - 1 job per fire (oldest queued)

4. **Hourly dispatch 整合** (`cron_hourly_dispatch.sh`):
   - **Phase A**: 先 check `--completed-pending-followup` — 若有 → 派 Claude interpretation agent，**本小時結束**
   - **Phase B**: 否則查 work_log diversity → pick type
     - Heavy-compute task → **enqueue compute job** (0 Claude tokens)
     - Decision/writing task → **派 Claude agent**

**When to use which**:

| 任務類型 | 例 | 派發方式 |
|---|---|---|
| Compute only (script 已寫好) | 跑 GARCH/Bootstrap/Backtest 全期 | enqueue compute_queue + followup brief |
| 寫 script + 跑 + 解讀 | 新 K-experiment (script 未存在) | Claude agent 一次完成 |
| Pure writing | Article / paper body / brief 設計 | Claude agent |
| Pure decision | Codex 結果後改 closure / queue follow-up | Claude agent (light) |
| Mixed | K-experiment 重跑（script 在）+ result 解讀 | 分兩步：先 enqueue compute，下小時 followup |

**Migration target patterns**:
- K-experiment full backtest sweep on existing scripts → enqueue
- Reproduce.py gate check after data update → enqueue
- Codex re-verify when quota resets → enqueue `codex exec` as script
- MC simulation runs → enqueue
- Embedding rebuild / LanceDB index → enqueue
- Paper-update CLI sync → could enqueue if no Claude decision needed

**Reliability**:
- Worker runs */15 min — if queue empty, exits in 1s
- Lock 防 concurrent runs
- Timeout per job (default 3600s = 1h)
- Stdout/stderr 進 storage/logs/compute/
- Failed jobs not auto-retried (manual debug)

**Commit**: 2026-05-12 14:24 CST, "feat(scheduling): compute queue + hourly dispatch split".

**相關規則**:
- `reference_hourly_dispatch_via_os_cron.md` — hourly trigger via crontab
- `feedback_one_dispatch_per_hour.md` — 1 agent per hour rule（compute job 不算 agent dispatch）
- `feedback_task_end_summary_format.md` — 結束摘要 6 項
