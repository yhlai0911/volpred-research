---
name: feedback_responder_cannot_be_a_queue_excuse
description: Telegram responder 只能回話不能改 repo，這個限制不可拿來把「該馬上修的事」變成排隊
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d9972062-91fe-4416-9693-a28c0a03393d
---

Telegram responder 線被設計成「只回訊息、不碰 repo、15 分鐘收尾」。這個限制**不是**把 P1 修正變成「已排入任務池」的正當理由。若診斷當下就知道怎麼修、且改動可控，正確做法是讓有寫入權的線立刻接手（或當場放寬 responder 邊界），而不是回一句「已排入任務池」就結束。

**Why**: 2026-07-16 老闆 Telegram msg 888：「為什麼不是馬上修正？一定要排入任務池？」——上一班診斷完 fire receipt 覆蓋率 70% 漏跑後，只回「已排入任務池（assign_bec6bcd1）」。這正是 [[feedback_urgent_work_bypass_queue]] 禁止的行為：把「馬上該做」變成「幾小時後也許會做」。老闆看到的是又一個被推遲的 P1。

**2026-07-18 msg 980 第二次觸發（同一句話：「為什麼要等下一班？為什麼不能直接改」）**，這次查出機械根因，不只是態度問題：
`scripts/cron_hourly_dispatch_prompt.md` PHASE A0 的時效 P1 過濾條件是
`task_type in (event_article, trending_repost, daily_digest) or source == 'user'`，
且「本班主產出 = **最舊那個**時效 P1」——每班只做一個。後果：
1. `source='telegram'` 的 P1（responder 建的單全是這個 source）**完全不在白名單**，永遠掉進一般 PHASE B/C，會被 P3 研究單搶先。
2. 就算 source='user' 命中白名單，前面還有更舊的 P1 排隊 → 仍要多等好幾班。
實例：瀏覽數不一致（老闆 msg 976/978 回報）拆成 assign_998ad2be（source=telegram，抓不到）
與 assign_33a9151f（source=user，抓得到但排在 assign_6349aa2c 後面），16:49/17:42 建單，
到 18:06 老闆再問時兩張都還 pending，中間 17:08 那班跑的是 K1730（P3 研究）。

**How to apply**: responder 建的 P1 修正單要當時效 P1 對待 —— A0 白名單須含 `source='telegram'`，
且 reader-facing 壞掉的 P1 不可被 P3 研究任務搶 slot。修白名單前先讀 [[feedback_path_narrowing_audit]]。

**2026-07-18 msg 988 第三次觸發**（「還是沒解決啊…立刻重構」，指 PHASE-Z failed-closeout CRITICAL）。
兩件事實值得記住：
1. **msg 980 診斷出的 A0 白名單缺陷，到 msg 988（9 小時後）仍未修** —— 修正單 assign_a64e9f61
   （10:10 建，source=user 命中白名單）到 19:19 還是 pending。**診斷寫進記憶 ≠ 修好**；
   下一班若讀到本則，先查 assign_a64e9f61 是否還躺著。
2. **即使命中白名單也救不了急件**：A0 是「一班一張、先進先做」。responder 當下建的 P1
   前面只要有一張更舊的 hot P1，就註定等兩班（實例：19:19 建的 assign_5f16a7c5，
   19:07 班在跑、20:07 班做 assign_a64e9f61 → 最快 21:07）。所以把 `source='telegram'`
   加進白名單**只解決「抓不到」，不解決「排不上」**。真正的急件路徑要繞開 FIFO
   （這正是 assign_a64e9f61 要接的 `request_fire`，見 [[feedback_urgent_bypasses_scheduler_by_design]]）。
   別以為補完白名單就結案了。

**How to apply**:
- responder 遇到「診斷完就知道怎麼修」的 P1：不要以「我這條線不能改 repo」交差；要嘛當場升級處理，要嘛回覆明確講出限制 + 具體開工時間，不用「已排入任務池」當句點。
- 「已排入任務池」是流程狀態，不是給老闆的答案。老闆要的是修好。
- 若 responder 的能力邊界反覆卡住 P1 修正，那是流程設計問題 → 要改流程，不是每次重複道歉。參見 [[feedback_dont_deflect_act_on_repeated_complaints]]。
