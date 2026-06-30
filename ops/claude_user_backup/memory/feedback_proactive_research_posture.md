---
name: Proactive research posture（喚醒 = 主動找事，不是等 queue）
description: 每次喚醒應主動生研究議題（文獻 gap / paper R1 風險 / knowledge.json 空白），不是 reactive 派 backlog brief 就交差
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
**Rule**: 每次 /loop 喚醒，主線程應**主動生研究議題**並轉化為實驗 brief 或 paper task，不是 reactive 從 next_tasks.json 撈既有 brief 派 agent 就算「有做事」。

**Why**:
- 用戶 2026-05-11 明確指出：「你的 skill 是不是有問題 一兩個月前你不是這樣的」+「我不是要你去做以前的事 而是要你知道 以前系統怎麼做事」
- 2026-03-15..2026-03-30 git log 顯示當時 working model = 主動提研究方向 + 每 2 小時可驗證產出 + ops patrol + 從 knowledge gap 自己生 brief（不是等 script 撈 unchecked items）
- Reactive 模式（dispatcher 派、agent 跑、cron refill）只是 mechanical fallback，**不是**正確的 system posture
- 「skip slot=N/4」+ research_backlog cron 是退化症狀，不是健康狀態

**How to apply**:
1. 每次 /loop 喚醒先做 30 秒 strategic scan：
   - 開放研究問題（research_program.md Open Questions）裡哪個最 ripe？
   - 最近 3 篇 paper review feedback / R1 風險哪個沒被 brief 覆蓋？
   - knowledge.json 哪個 cluster 證據最稀薄、可以一個實驗補上？
   - 最近 1 週讀過/查過的文獻有沒有 method 可挪用到 active research？
2. 從上述 scan **自己生 brief**（寫進 next_tasks.json + experiments/<id>/README.md）並派 agent，**不是**只挑 dispatcher 報的 agentable list
3. 既有 brief 派出後仍應**繼續**做 strategic scan 為下一批生 brief，而不是「我已經派了所以可以 skip」
4. Mechanical refill cron（generate_research_backlog / populate_events / build_publication_candidates）只是兜底，不是主動研究的替代品
5. 「沒事做」**不是**可接受的喚醒結論 — 若真的找不到議題，問自己「過去 1 個月哪個 paper 最久沒動」「網站哪個 audience 最久沒新內容」，從那裡反推
