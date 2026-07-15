---
name: feedback_declare_complete_requires_class_sweep
description: 宣告完成前必須對 bug class 做 full-population sweep + 留機械 gate；「我改的通過測試」是 strike-1 門檻
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b3170187-15da-4edf-8e6c-17a80a5c34bd
---

老闆連問四次「所以一切都正常了？」，每次都挖出新缺陷（2026-07-10 dispatch_supervisor observability）。四次都不是他發現 bug，是**我的完成門檻太鬆**：我每輪都在「改的東西通過測試」就宣告完成，然後下一輪才發現同 class 還有漏網的。

**Why**：子集 audit 把 false negative 留在盲區裡。四輪的實例——
1. 補了 `supervisor_pid`，沒 sweep 其他「有 writer 卻未宣告在 `_empty_state()`」的欄位 → 漏掉 `fire_requested_at` / `fire_request_reason`。
2. 宣告「state 檔現在能誠實回答 daemon 死活」，沒查有沒有 reader 在問 → `get_supervisor_age_seconds()` 零 production consumer，docstring 說有是假的。
3. 修完告警，沒 grep 還有誰在讀 cutover 遺骸 → `dispatch_binary_health` 在 grep 已退役的 shell wrapper。
4. 處置只留 docstring 散文，沒升級成機械 gate → 同 bug class 第三次復發。

本專案自己的 `.claude/rules/experiments.md` §Audit methodology hard rule 早已明文「必須 re-walk full population，不可只 sample suspect subset」，但該規則 paths 不含 `storage/ops/**`，審 ops state 時不會 auto-load —— 規則存在卻 silent skip（同 2026-04-20 publish-checklist path-trigger incident）。

**How to apply**：
- **先跑 canonical 儀器，再談你手上那條線**。被問「一切正常了嗎」/ 要宣稱平台健康時，第一個動作是 `uv run python scripts/daily_checkup.py`，不是自己 grep。2026-07-10 前四輪全靠手刻 grep（找到四個 bug，但全在同一個子系統）；第五輪跑大體檢，4 秒撈出當下正在阻塞的 `git_push_backup exit=120`（silent-fallback gate 擋 push、2 個 commit 沒備份）—— 那條線 grep 永遠碰不到。**儀器的價值在於它掃你沒在看的地方。**
- 修完一個欄位 / reader / 監控**之前**問「同類還有幾個？」，grep 出全 population 再收工。
- 宣告完成的門檻 = **「這個 bug class 在整個 population 上都不存在」+「有機械 gate 擋住復發」**，不是「我改的通過測試」。
- 同一 bug class 第二次出現起，交付物必須是機械 gate（AST / invariant test / CI script），不是 docstring 或 rule 裡的散文提醒。散文擋不住第四次。gate 一律收編進既有 owner，不加第二層 watchdog（[[feedback_snapshot_before_refactor]] 之外的 anti-stacking 原則）。
- 「宣告完成前先自問一次『我引用的每句 docstring / 註解，我查證過嗎？』」—— 上述 (2)(3) 都是我照抄了 docstring 的說法而沒 grep 驗證。

規則正文已在 `.claude/rules/control-plane.md` §控制面 audit 的完成門檻立指標；paths 補上 `scripts/dispatch_supervisor/**` / `cron_review.py` / `check_alerts.py` 讓它在審 daemon 程式碼時就 surface。

**2026-07-14 變體（用戶糾正「你不是只補做決策 你發現流程問題就要去解決流程問題」）**：發現「漏掉的決策 / stale state」時，補做那個決策 = 修資料；交付物必須是**讓這類遺漏不可能再發生的機械 gate**。實例：K1686 gating task 完成 43h 無人裁決 + handoff 抄到已撤回裁定 —— 我先只補了裁決並回報，被糾正後才交付 `paper_adjudication_gap` alert（check_alerts owner、remediation 自動建 task）+ handoff pointer 規則 + regression tests。而且 gate 一寫出來就在現行 population 掃出 2 個同類引用需要收窄契約（provenance vs 活依賴）—— 再次證明 class sweep 不是形式。教訓入 error_log 2026-07-14 15:30。

相關：[[feedback_path_narrowing_audit]]（改 paths 前填 workflow stage × paths 矩陣）、[[feedback_verify_before_restructure]]、[[feedback_dont_deflect_act_on_repeated_complaints]]
