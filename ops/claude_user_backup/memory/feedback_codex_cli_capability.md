---
name: Codex CLI 與 Claude Code 能力對等
description: 終端機中的 Codex CLI 是完整互動式 agent，能力與 Claude Code 對等；不要把它誤描述為 one-shot 或無法長任務執行
type: feedback
originSessionId: 7d4e5d63-920e-4d06-b12c-a763cf9fdb9e
---
終端機執行的 Codex CLI（與 `codex:codex-rescue` 子 agent）是**完整的互動式 agent**：能讀 codebase、跑 bash、工具呼叫、長任務執行，與 Claude Code 在 workflow 層面對等。

**Why:** 2026-04-18 session 在規劃 3-terminal 監督者/工人模式時，我把 Codex 錯寫成「不會自動 loop / one-shot / 容易失焦」，用戶立刻指出 Codex CLI 也在專案中、也能讀 codebase、也能長任務執行。這是把「子 agent 分類」與「互動式 agent 能力」混為一談的錯誤。

**How to apply:** 
- 描述 Codex vs Claude Code 差異時，只講**真正不同**的事：model 後端（GPT-5/Codex vs Opus）、OAuth 配額獨立、子工具生態
- 不要暗示 Codex 比 Claude Code「弱一級」、「只能 one-shot」、「無法 long-running」
- **特別注意：兩者都是完整 agent，一次 prompt 後會自主循環多步驟任務**（自主呼叫 Bash/Read/Edit 工具，執行 next-task→execute→complete→loop 直到 budget 用完）— 不需要 /loop skill、bash wrapper、也不需要每輪戳「繼續」
- 先前錯誤框架：「互動式 CLI 需要用戶戳繼續才進下一輪」— 這是把 1-round chatbot 誤推廣到 agent
- 2026-04-18 用戶二次糾正：「我要講幾次 claude code/codex都是agent 他自己有tool 可以判斷並持續執行該任務」— 這是重點
- 多 agent workflow 中兩者可用同一套 claim/execute/complete 循環模板
