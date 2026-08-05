---
name: project_test_spawn_leak_sandbox_escape
description: 測試可 spawn 真實 opus session（org wake 路徑）；tree-clean class gate 對 out-of-process 副作用結構性失明
metadata: 
  node_type: memory
  type: project
  originSessionId: 8fcc3160-7565-412d-a321-b6309d420511
  modified: 2026-08-05T11:21:59.887Z
---

2026-08-05：`tests/test_org_admin.py::test_boss_intake_triggers_gate` 以 subprocess 跑
`scripts/org/org_intake.py --boss-message`，該路徑呼叫 `manager_tick.wake_manager`，
`subprocess.Popen(manager_run.py, cwd=REPO_ROOT, start_new_session=True)` **生出真的
`claude -p --model opus --effort high`**，持 live repo 寫入權。當天觸發 8+ 次、間隔從 11 分鐘
縮到 ~30 秒（有東西在反覆跑 test suite），一度四個並存；其中一個依測試夾具字串「急件」
對老闆送出真 Telegram。經理 session 的 brief 因此整段為假（org root 指向 pytest tmp）。

**根因（可複用的設計教訓，不只這個 bug）**：`wake_manager` 的兩道鎖
（`_too_soon_for_manager(root)`、`read_lease(root)`）都以**呼叫端傳入的 root** 為鍵，
而副作用（detached session on live repo）是**全域**的。測試每次給新 tmp root ⇒ 永遠拿到
處女 lease ⇒ 鎖**結構上不可能咬**。程式沒寫錯，是防護的作用域選錯層級：
它保護「那個 org」，傷害發生在「這台機器」。
**判準：防護的鍵所屬的作用域，必須 ≥ 副作用的作用域。**

**Why**：[[project_canonical_write_test_leak_gate]] 的 class gate 判準是「跑完 checkout 有沒有變」
（porcelain + mtime sentinel）。該判準對此類**結構性失明**——spawn 的副作用在別的行程、
且在測試結束後才落地，套件結束當下 tree 是乾淨的。所以那道 class gate 綠燈 ≠ 測試無外洩副作用。

**How to apply**：測試觸及會 spawn / 發訊 / 打外部 API 的路徑時，別只問「有沒有寫檔」，
要問「有沒有製造行程或對外訊息」。防呆下在**單一收斂點**（此例 `wake_manager`，非
`org_intake._wake`），且綁 canonical 常數（`DEFAULT_ORG_ROOT`）而非信任呼叫端參數。
`monkeypatch` 對照組**對 subprocess 無效**，不可拿來當「已擋住」的證明
（`tests/test_org_admin.py:748` 即為此誤導性先例）。相關
[[feedback_declare_complete_requires_class_sweep]]、[[feedback_verify_org_brief_against_canonical]]。
