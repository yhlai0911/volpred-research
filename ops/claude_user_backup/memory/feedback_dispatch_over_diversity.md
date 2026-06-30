---
name: feedback_dispatch_over_diversity
description: Type 多樣性規則不能凌駕「必須派工」原則。沒 actionable 時優先派一份工，不要用 hold 空轉
type: feedback
originSessionId: 01d23520-901e-44a9-9f09-f9e497e18020
---
當 cron 觸發 "繼續任務" 時，**至少要派發一份工作出去**，否則永遠沒新工作開始。

「連續 2 輪同一 task_type 換 type」的多樣性規則**是輔助，不是目的**。若因為 diversity 條件而反覆 "hold" 空轉，就本末倒置了。

**Why**：2026-04-20 session 00:05-00:45 UTC 連跑 8-10 輪 minimal hold 「pool 5 stable / next piggy-back XX:XX UTC」無實質產出。用戶指正：hold 不是 valid 產出。即使該輪沒新 actionable work，也要做**某件事**（派真正的 agent、實做具體修復、補文章 draft、跑 paper review、寫新 K 實驗）。

**How to apply**:
- 每輪優先順序：(1) queue user-assigned (2) actual dispatch (agent 寫文章/研究) (3) concrete infra/code fix (4) low-cost ops (INDEX rebuild / sync verify)
- **Hold / observation / stub skip 不算產出**；只有新 agent ID / finish-task / code commit / article draft / real decision 算
- 若真沒事做，優先做 novelty experiment 或 paper deep-review；不優先 diversify type 而 hold
- 多樣性規則在「有多件 actionable 可選」時才生效（避免過度集中單一 type）；沒事可做時不 invoke diversity excuse
- 每小時 check_alerts 自動 fire universal piggy-back scheduler 觸發 due jobs — 主線程仍要同步有 output
- 具體 test: 當想寫 "hold" 或 "observation-only" 時停下來問：「有沒有 memo pipeline 可派？有沒有 paper 可 review？有沒有 research_program backlog 可開始？」若全 no 才進 minimal ops

**Edge cases**:
- Queue codex-blocked + slot free → 優先用 Claude agent 派 discovery/article/research 任務，不等 Codex 回來
- Pool healthy + no memo → 從 missing_general_audience top5 + research_program backlog 隨機挑一個派
- 深夜時段 user 不在線 → 仍派，早上醒來看到成果比看到 hold 有價值
