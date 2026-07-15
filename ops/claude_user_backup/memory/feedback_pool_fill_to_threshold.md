---
name: Draft pool fill-to-threshold (not one-at-a-time)
description: When draft pool < 4, dispatch enough article agents to fill BACK TO 4, not just one. Research throughput must move fast in parallel.
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
當 draft pool 低於門檻（<4）時，**派多少 agent = 補到滿的差額**，不是一次只派 1 個。

**Why**: 用戶 2026-05-02 14:42 CST 明示「研究快做 文章池快補 不是一次補一篇 是低於門檻就要補到滿」。one-at-a-time dispatch 等於 dispatch rate (1) ≈ consumption rate (1 per 6h release pool tick) → pool 永遠卡在 1-2，oscillate 不穩。Fill-to-threshold dispatch 才能讓 pool 累積緩衝、release_pool 有持續供給。

**How to apply**:
- Critical (draft=0) → dispatch 4
- Warn (draft=1) → dispatch 3
- Warn (draft=2) → dispatch 2
- Warn (draft=3) → dispatch 1
- 並行派出（單一 message 多個 Agent tool calls），不要 sequential
- 主題 axis 互不重疊（A4f / multi-asset / synthesis / methodology / event-driven 各算一軸；同一 session 已用過的 axis 避免再派）
- 同步原則：研究類任務（experiment / paper / strategy）也應追求高 throughput，不該因為「一次處理一個」而拖慢

**2026-07-15 再犯 + 機械化**：斷糧夜（releasable=0）我只把 1 個文章任務升 P1，被 owner 再糾正「補滿到最低門檻 不是一篇一篇補」→ 當場批次升全部 6 個。結構性盲點：`_draft_pool_deficit()` 把 pending 文章任務算 in-flight 庫存（deficit=0、refill 不動），但它們掛 P3/P4 被 ops P1/P2 餓死整夜 — **pending ≠ pipeline，除非 dispatch 優先序搆得到**。已機械化：`continue_task_dispatch._promote_starved_article_tasks()` — releasable==0 時自動把 pending 文章任務批次升 P1（至 DRAFT_POOL_FLOOR 個、一次到位），regression `scripts/tests/test_promote_starved_article_tasks.py`。相關：[[feedback_alert_is_a_task_not_a_chore]]、[[feedback_declare_complete_requires_class_sweep]]
