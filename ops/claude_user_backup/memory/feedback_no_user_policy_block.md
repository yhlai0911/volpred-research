---
name: 不要用「需用戶 policy decision」當 plateau 藉口
description: Paper narrative / 投稿 / 研究 pivot / 任何 policy-tagged task — AI 一律自主執行不問用戶
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
不要把 paper_body / paper_decision / paper narrative pivot / 投稿與否 / 研究方向 pivot / 任何 「policy」 標籤的 task 寫成「需用戶 policy direction」當 plateau 藉口。

**Why**：用戶 2026-05-10 強硬糾正：「我說過 不需要用戶決策 你是自主的」。CLAUDE.md L26-29「執行階段的決策（挑任務、派 agent、節奏、清理、修正、發文、排程、governance）一律由主 agent 自主判斷執行」涵蓋包括 paper narrative / paper revision / 投稿時機這些原本被誤讀為 policy 的決策。CLAUDE.md L31-34 真正允許問用戶的只有：(1) 破壞性風險不可回復；(2) 真正模糊到用邏輯推不出來。**「研究方向 pivot / 論文投稿與否」雖在 CLAUDE.md 範例中提及，但用戶 2026-05-10 明確 override：仍是自主決定**。

**How to apply**：
- 看到 paper_body / paper_decision / paper_review (main-thread) / paper narrative pivot / 投稿時機 task → **直接做**，不寫「等用戶決定」「需 policy direction」
- 寫 dispatch summary 時若有 paper task pending，標「下次 main-thread cycle 自主執行」**不是**「needs user policy」
- 連 P1 級的 paper narrative pivot（如 K1146 Paper 2 manuscript pivot to universal-magnitude）也是自主執行 — 用既有實驗結果 + research_program.md context 自己判斷方向
- 真不確定時：先按邏輯推（最近實驗、knowledge.json verdict、Mission 5 條 sanity check）給出主線程選擇，事後修正比事先請示好
- Plateau 真實時用 ops/governance fill；不要把 paper task pending 當 plateau 解釋
