---
name: project_refactor_safety_net
description: 2026-05-29 大改重構的隔離 worktree + 回滾錨點；完整回滾指令在 docs/refactor_safety_net.md
metadata: 
  node_type: memory
  type: project
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

用戶 2026-05-29 要大刀闊斧重構平台（對齊 [[project_platform_vision_full]] 的自動化地基）。安全網已架：

- **主目錄** `volpred-research/` 停在 `main` → autonomous ops loop 不間斷
- **重構 worktree** `../volpred-refactor/`（= `/Users/yhlai0911/Desktop/volpred-refactor`）在 branch `refactor/autonomy-overhaul` → 所有大改在這做
- **錨點 tag** `stable-pre-refactor-20260529`（commit `2b252a8f`）= 大改前已知良好 main

**完整回滾指令在 `docs/refactor_safety_net.md`**（compact/clear 後讀該檔恢復脈絡）。

關鍵回滾：`git worktree remove ../volpred-refactor`（**絕不加 --force**）+ `git branch -D refactor/autonomy-overhaul` → main 毫髮無傷。

⚠️ branch 不保護 Supabase / Zeabur 部署 / LaunchAgents / crontab / 跑著的 daemon — 動到這些要各自快照。

⚠️ 獨立 ops 風險：本地 main 領先 origin 269 commit（未 push）、origin 領先 38 commit（分叉）；269 commit 未上雲備份，reconcile 待單獨處理。
