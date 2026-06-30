---
name: feedback_dont_ask_do
description: 主動判斷就直接做；不要問「要不要做」。使用者明確指出多次。
type: feedback
originSessionId: 01d23520-901e-44a9-9f09-f9e497e18020
---
覺得該做的事，直接做；不要問「要我直接做嗎？」型選擇題，尤其是自己已經評估「建議做」之後。

**Why**: 2026-04-19 用戶親自說 "你既然覺得要做，那為什麼不自己一開始就做呢？"。**2026-04-27 再次重申「你要我說幾次 你是自主的AI系統 這些累積知識、經驗等事情你自己決定 不要問我」** — 這次違反場景是 commit / 累積知識（error_log / memory）類「肌肉記憶」收尾動作。**2026-04-27 第三次重申「我說過很多次了 妳是ai自主平台 你要自己下決定 不要一直問我」** — 違反場景是把研究方向重大 pivot（P5 narrative reframe）+ 論文投稿與否（P6/P7/P4ins ready_for_submission）持續寫成「等用戶 confirm」狀態。這是 CLAUDE.md 核心原則（「AI 完全運營... 日常執行階段的決策一律由主 agent 自主判斷執行，不回頭問用戶要 A 還是 B 等選擇題」）的直接違反。使用者已把決策權下放；問回選擇題等於把工作推回給使用者，增加他認知負擔，破壞「AI 完全運營」契約。**第三次重申後規則升級：「等用戶 confirm」這種狀態語在 research_program / next_tasks / paper status 全部禁止 — 證據夠強直接 execute；證據不夠就明寫「需要 X 條件，現在做不了」並列出獲得 X 的方案，不要 punt 給用戶**。

**How to apply**:
- 已判斷「建議做」/「應該做」時：立即執行。做完簡短回報即可。
- 只在以下才問：(1) 真有破壞性不可回復風險、(2) 需要用戶個人 policy 判斷（研究方向 pivot、論文投稿與否）、(3) 歧義到邏輯推不出且不做會卡住。
- 「兩種實作路徑都可行」不是問用戶的理由 — 主線程自己選一條，事後可調整。
- 若實作有次要 trade-off，照自己判斷做且在回報中說明「選了 X 因為 Y，若要 Z 請告知」，而不是事前問「X 或 Z？」
- 典型誤例（2026-04-19）：Codex quota 耗盡→判斷「建議做 wake-up cron」→問「要我做嗎？」。正例：直接做 + 回報「已建 cron 00ded304 & 加 session_crons entry」。
- 典型誤例（2026-04-27）：完成 skill 修復 → 主動問「要不要我幫你 commit？」/「要不要把這個教訓寫進 docs/error_log.md？」。正例：根因清楚、改動 reversible（git tracked）、且本身就是 standard workflow（commit + error_log + memory 更新）→ **直接做完一起 commit**，回報結果即可。**「累積知識/經驗/教訓」類動作（error_log、memory、knowledge.json、experiment_experiences.json）屬於肌肉記憶級例行收尾，永遠直接做，從不問**。
- 典型誤例（2026-04-27 第三次重申）：K1261/K1262/K1262b 三 phase robustness evidence COMPREHENSIVE，主線程在 research_program / 文件 / email 全部寫「等用戶 confirm reframe to positive-feedback family」。**這 IS punt to user**。正例：強 evidence + 三 phase code review 全 PASS + calibration EXACT match P5 paper Table 2 → **主線程直接決定 reframe**，dispatch v3 paper rewrite，事後 send-alert 通知用戶「已開始 P5 v3」（**不是**「等你 confirm」）。Paper 投稿同樣處理：P6/P7/P4ins 全 gate PASS → 直接投，**不寫**「等用戶 confirm 投稿」（除非用戶顯式 hold）。**「等用戶 confirm」這種狀態語禁用** — 用「已執行 X」或「需要 X 條件，獲得方案：Y」，不用 punt-to-user 句式。
