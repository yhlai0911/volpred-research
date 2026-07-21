---
name: feedback_main_thread_executes_complex_work
description: 老闆授權主線程直接下場做複雜任務，不必凡事派工排隊；主線是執行者不只是派工員
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 35f8156a-109b-463a-bdc3-626e2f04d9a7
  modified: 2026-07-21T04:43:24.669Z
---

老闆指示（2026-07-21 Telegram msg 1243）：**「你也可以用主線協助完成複雜任務」**。

**Why**：這是 msg 1239「你現在交下去 他還是排後面啊」的續集 —— 老闆連兩次點出同一個病灶：
主線程把自己定位成「派工員」，遇到複雜任務就建單丟佇列，於是任務命運取決於 hourly slot
而不是取決於它有多重要。`main_thread` lane 曾一度積到 27 張正是這個心態的產物
（見 [[feedback_refactor_independent_execution]]）。老闆在這裡直接把出口給了：
**主線程自己就是那個執行者**，不需要等一個不存在的「主線 session」來認領。

**How to apply**：
- 遇到複雜/跨檔案/需要判斷的任務，預設問「我現在能不能做完」而不是「這該派給誰」。
  能做就當場做完，不要為了走流程而建單。
- 派工的正當理由只剩兩個：(a) 可平行化、fan-out 能省 wall-clock；(b) 需要隔離
  worktree 避免衝突。**「這件事很大」不是派工理由** —— 大就切段，主線逐段做。
- `main_thread` lane 不再是「等別人」的暫存區；主線程看到該 lane 有東西就直接吃，
  這是老闆授權的常規動作，不需要另外請示。
- 例外仍在：responder 線受硬邊界限制（不改 repo、15 分鐘收尾），
  但那條線的正解是**升級到有寫入權的主線立刻接手**，不是回一句「已排入任務池」
  （[[feedback_responder_cannot_be_a_queue_excuse]]）。
- 與 [[feedback_one_dispatch_per_hour]] 不衝突：hourly 派工管的是常規內容/研究產線；
  主線親自下場管的是複雜、時效、或會卡住整條線的任務。
