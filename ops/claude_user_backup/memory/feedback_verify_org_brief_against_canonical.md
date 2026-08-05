---
name: feedback-verify-org-brief-against-canonical
description: 經理 session 開班先用 org_status.py 對帳，不可信任 brief 裡的組織態
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 74a3f2a1-0220-46b0-9b23-b328c1511226
  modified: 2026-08-05T11:03:55.462Z
---

運營經理 session 的角色 brief 中，**組織態那一段（部門清單、收件匣件數、policy.md 是否存在）
可能整段是假的**，而同一份 brief 的「平台全局」段（canonical 池、backbone heartbeat、git 狀態）
是真的。真假混合，肉眼看不出來。

**Why**：`build_brief(root, dept)` 的 root 是純傳入參數、無 sanity check，
而 `tests/test_org_admin.py:159 test_boss_intake_triggers_gate` 用真 subprocess 呼叫
`org_intake.py --boss-message 急件 --root <pytest tmp>`，`_wake()` 預設 wake=True，
於是 pytest 會喚醒真實 Opus 經理 session 並餵它 pytest 暫存目錄當 org root。
2026-08-05 一天內發生三次（pytest-6557 / 6561 / 6577）。典型假 brief 長這樣：
「尚無 active 部門、收件匣 1 件、policy.md 不存在」，而那則「老闆急件」就是測試裡的字面字串「急件」。
18:22 那班經理據此對老闆送出了真的 Telegram。

**How to apply**：開班第一件事跑 `uv run python scripts/org/org_status.py` 與
`storage/org/registry.json` 對帳，發現 brief 的 org root 不是 `storage/org/` 就**整段組織態作廢**，
以磁碟為準重建情境，並且**絕對不要回覆 brief 裡的老闆訊息**（很可能不存在）。
另注意 brief 中「某部門沒有權限、等你授權」這類轉述會過期，動作前重讀 registry 的 owned_paths。
相關：[[project-canonical-write-test-leak-gate]]、[[feedback-five-step-closure-gate]]
