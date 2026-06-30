---
name: feedback_proactively_complete_red_alerts
description: 看到紅色/critical 警告要主動完成或主動安排完成並告訴老闆會完成，不要只被動回報
metadata: 
  node_type: memory
  type: feedback
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

用戶 2026-06-07 硬性糾正：「你看到紅色的警告應該主動完成，或者主動安排要完成、告訴我你會完成。」

**Why**：autonomous loop fire 一直回報「warn / critical」卻沒採取行動 = 把紅色當 noise 被動 log。紅色是要 close 的責任，不是通知。

**How to apply**：
1. 每個 fire / boss report 看到 **critical 或 warn**（dashboard 非-ok section、host_cron_fail、stale backlog 等）→ **立刻 triage 根因**。
2. 能當下完成的 → **主動完成**（修 root cause / 派工 / 清 backlog），不等下一輪。
3. 不能當下完成的 → **主動排程 + 在回報裡明說「我會在 X 完成」**（具體 action + 時點），不是只列出問題。
4. 完成後 dashboard 要回到 ok / alert 標 resolved（`scripts/mark_alert_resolved.py`）。
5. 這延伸 `.claude/rules/alert.md` 的「Alert 寄出 → 主線程 auto-remediation」：email 是 log 不是責任轉移。

**首次套用範例**（2026-06-07）：host_cron_fail critical 整天紅 → 查到根因是 `audit_fb_pipeline.py` exit 1（找到 stale FB 的 findings 信號，非 infra 失敗）被 host_cron_fail 誤當 infra-critical。主動修 `alerts.py _parse_host_cron_state` 排除 audit_* signal log + mark_alert_resolved 清歷史 → dashboard warn→ok。並非只在 fire 回報「critical」。

相關：[[feedback_audit_no_passive_terminal]]、[[feedback_dispatch_over_diversity]]、[[feedback_autonomous_loop_email_summary]]。
