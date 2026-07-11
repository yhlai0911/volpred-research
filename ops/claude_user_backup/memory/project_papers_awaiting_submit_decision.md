---
name: project_papers_awaiting_submit_decision
description: 更正（7/4）：兩篇原 submission-ready 論文都已被誠實 re-review 撤回 ready — M3 瓶頸現為 revision 收斂（prg=K1544 narrative、leverage=method-null body rewrite），不是投稿決策；revision 完成後才回到投稿決策點
metadata:
  node_type: memory
  type: project
  originSessionId: 9b03f82f-4b5a-4fd1-8247-88240cdbc856
---

**2026-07-04 深度審計更正**（取代 6/21 快照的「卡投稿決策」framing）：

- `garch-x-vix` → 已 submitted（under review）✓ 不變
- `prg-periodic-garch` → ready 狀態已於 5/21 與 6/24 **兩次被誠實 re-review 撤銷**；現卡 K1544 timing-convention narrative 收斂 + body 重寫。replication package 不自足且過期 68 天（FRL hard requirement 不符）——等 body 重寫後重建（凍結 CSV、TAIFEX proprietary 標示、reproduce.py 重跑）。
- `leverage-direction` → 7/01-7/03 **三連 review FAIL**；卡 method-null body rewrite（`paper_body_leverage_direction_method_null_reframe_20260702`）。package 核心健全但文件層 stale、reproduce.py 未 gate 改版後 claims（IJF review blocking findings）——body rewrite 時一併修。

**How to apply**：
- **停用**「每隔幾 tick 向 boss 重提 ready-but-unsubmitted」指示——當前無任何一篇真 ready，重提會誤導。
- M3 真瓶頸 = revision 收斂工作（主線程逐篇推進，禁 background agent 寫 .tex）。revision 完成 + re-review PASS + package 重建後，**自主推進投稿**——老闆 msg 309（2026-07-09 Telegram）已把投稿決策下放主線程、目標優化 acceptance，取代舊的「投稿仍是 user-policy」framing。見 [[feedback_paper_autonomy_optimize_acceptance]]。
- `paper_stale` alert 兜底不變；stage tracker `stage_entered_at` 7/1 被 bulk baseline 重設過（days_in_stage 曾全體低估），讀數時注意 baseline 語意。

關聯 [[feedback_dont_deflect_act_on_repeated_complaints]] [[project_paper_portfolio_decisions_2026_04_27]] [[feedback_no_user_policy_block]]。
