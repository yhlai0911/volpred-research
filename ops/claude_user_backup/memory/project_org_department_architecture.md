---
name: project-org-department-architecture
description: 2026-08-05 老闆核准「運營經理＋部門制」磁碟持久化組織架構；P0+P1 已落地，遷移至 P4 前舊 dispatch 並存
metadata: 
  node_type: memory
  type: project
  originSessionId: 7cdc5dc3-2f38-4e28-b9ba-f0199042d601
  modified: 2026-08-05T06:10:23.119Z
---

老闆 2026-08-05 指出現行單一引擎病症（空轉、互擾、worktree 髒、orphan、通知亂、無分工），核准改組為「運營經理＋部門制」。計劃書：`~/.claude/plans/agents-herdr-agent-ticklish-chipmunk.md`。

**核心決策**：
- **不用 Herdr 當骨幹**（pane 綁 server 生命週期，違反「重開機/移機立刻回復」硬需求）；Herdr 只作 boss 在場時的選配觀察層。
- **磁碟持久化組織**：部門身分/記憶/inbox/journal 全在 `storage/org/`（git 管理），session ephemeral rehydrate。
- **組織即資料**：經理用 `scripts/org/org_admin.py` 即可開/裁部門，不改程式碼。
- 7 部門：research、publications、content、member_success、platform_eng、governance、resource_monitor（老闆點名要的 token 消耗監控部）。growth（行銷）留給經理日後自主提案開設。
- 通知鏈：部門禁直發 boss → manager/inbox → 經理 digest 兩班（08:30/20:30）＋P1 三類 passthrough（incident/boss 回覆/金流）。
- ownership.md 新增 D 區（storage/org/**）。

**遷移狀態**（P0→P4 每階段可回滾；58 個既有排程 job 在 parity 驗證前絕不關閉）：
- P0 完成（commit 45609a5bf + b286c4693）：工具組 scripts/org/{_core,org_admin,dept_send,manager_tick,org_status,boss_digest,org_intake,dept_wake}.py＋tests/test_org_admin.py（hermetic 8 綠）。
- P1 接電完成（commit 46b193acb）：org_manager_tick 每 30 分 shadow tick，Operations Core 直持，零成本硬事實 gate 只寫 receipt 不 spawn LLM。**7 天 shadow 對照通過才進 P2**（P2=通知收編 digest；P3=逐部門 cutover；P4=retire 舊 lane）。
- 未接電（tools 誠實回報 not wired）：boss_digest 實發、org_intake GitHub 鏡射＋request_fire 即時喚醒、dept_wake 實際提交、dept_session task_type（[[feedback-batch-tasks-per-fire]] 派工規則屆時併入 inbox priority）。
