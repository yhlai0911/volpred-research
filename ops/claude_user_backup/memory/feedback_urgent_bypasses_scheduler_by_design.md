---
name: feedback_urgent_bypasses_scheduler_by_design
description: 老闆架構硬指令 — 急件不進排班、直接派工；一般排程才進排班。兩條路徑必須分開
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 28629bfa-bec3-4273-af34-1b7befbe90f3
---

老闆架構硬指令（2026-07-18 Telegram msg 981）：
**「急件和一般排程應該要分開。急件就不進入排班直接派工，一般排程才進入排班。」**

這是架構要求，不是態度要求 —— 不可用「已排入任務池，下一班會做」回應急件。

**現況（2026-07-18 實查）**：底層機制**已經存在且正確**，缺的只是接線：
- `scripts/dispatch_supervisor/state.py:684 request_fire(reason)` = out-of-band 立即派工；
  `scheduler.py:723` 明確保證 **requested fire 繞過所有 gate**（「Gates ONLY plain cron fires」）。
- 已接上的來源：`scripts/gmail_inbox_poll.py:754`（`email_reply:*`）、
  `scripts/check_alerts.py:1168`（`ci_red:*`）。
- **未接上：Telegram**。Telegram P1 只是 append 進 `storage/next_tasks.json` 等 hourly cron，
  這就是「email 急件立刻做、Telegram 急件要等下一班」的全部原因。

**第二層缺陷**：`request_fire` 只是 generic wake-up，不是 targeted claim
（`scripts/continue_task_dispatch.py:970` 註解自陳）。fire 之後仍由
`scripts/cron_hourly_dispatch_prompt.md` PHASE A0 白名單挑任務，而該白名單漏掉
`source='telegram'` 且每班只做最舊一張 —— 詳見 [[feedback_responder_cannot_be_a_queue_excuse]]。
所以「急件直達」要兩處都修：**ingest 端接 request_fire + 派工端 targeted 認得急件**。

**已修復並驗證（2026-07-19 10:20 台北，msg 1007 第四次觸發時逐項查證）**：
1. **ingest 端已接線** — `src/volpred/ops/next_tasks.py:604` 對急件呼叫
   `request_fire(f"{source}:{id}")`，失敗時走 `warn("urgent_fire_request")` + hourly 兜底。
   不再是 telegram 專屬 hack，是以 record 為準的通用路徑。
2. **派工端已改判定 owner** — `cron_hourly_dispatch_prompt.md` PHASE A0 不再列舉 task_type，
   改呼叫 `uv run python -m volpred.ops.task_urgency`（`src/volpred/ops/task_urgency.py`），
   以 **source + priority** 判 urgent lane，time_critical 排其後。
3. **一班一張已解除** — A0 現在規定「本班主產出 = 這條 lane，且要連續清完」，
   停止條件只有 lane 清空或 50min cap。
驗證數據：`task_urgency` 回 `{count:0, urgent:0, time_critical:0}`（lane 乾淨）；
`storage/ops/dispatch_state.json` `last_fire_at=2026-07-19T02:19:20Z`（= 老闆訊息前一分鐘的 fire）。
**下一班別再把這條當「已知未修」**；若老闆再提，先跑 task_urgency 看 lane 有沒有堆積，
而不是重讀上面的舊診斷。

**How to apply**:
- 任何新的急件來源（Telegram、webhook、監控）上線時，ingest 端必須呼叫 `request_fire`，
  不可只 append task pool。這是 checklist 項，不是 nice-to-have。
- 判斷「這是不是急件」的白名單要以 **source + priority** 為準，不要逐一列舉 task_type
  （列舉法就是這次漏掉 telegram 的原因）。
- 回應老闆時不要說「這很難架構」—— 八成已經在了。參見
  [[feedback_check_existing_mechanism_before_building]]。
