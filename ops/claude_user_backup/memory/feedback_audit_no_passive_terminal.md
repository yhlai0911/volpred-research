---
name: feedback_audit_no_passive_terminal
description: Audit script 的 terminal status set 不可含「無限期被動等」狀態（awaiting_*/pending_*），否則 silent failure。
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 06d2f049-020f-4a60-8657-d0feb83cd23e
---

任何 audit / health check / staleness scanner 的 `TERMINAL_STATUSES` 集合**只能含主動決策的終態**（success / wont_fix / fb_silent_reject / expired_skip / cancelled / completed），**不能含「無限期被動等」狀態**（awaiting_interactive_session、pending_user / pending_external / blocked_on_*）。

**Why**：2026-06-03 FB pipeline 4 天 100% 失敗 root cause — `scripts/audit_fb_pipeline.py::TERMINAL_OR_HANDOFF_STATUSES` 把 `awaiting_interactive_session` 算 terminal → audit 永遠 0 alert → dashboard 看不到 4 篇連續 4 天累積。用戶 email-11939 嚴重質問「FB 到底要錯幾次？你到底有沒有檢討底層」。`awaiting_*` 是「等不到的中間狀態」不是「已收尾」。

**How to apply**：
- 寫新 audit 時 `TERMINAL_STATUSES` 必審：每個 status 問「這是主動決策完成的終態，還是被動等某事發生的暫態？」後者不放
- `awaiting_*` / `pending_user` / `pending_external` 應另設 `HANDOFF_STATUSES` 集合，配 `max_age`：超過 → 觸發 escalate / alert / auto-downgrade 成真 terminal
- 既有 audit 改 terminal set 時必 backfill 邏輯：若某 status 從 terminal 拿掉，先掃所有目前該 status 的 entry 看會不會炸 alert（本次 4 篇 awaiting →72h cutoff 全 auto-expired 才安全）
- 反例（K1313 / fb_pipeline）：terminal set 包含「無限期等」→ silent skip → 累積到用戶抓到才被動 reactive 修
- 相關：[[feedback_dont_ask_do]]（不問選擇題；3-strike 重構觸發）
