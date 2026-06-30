---
name: 「開始執行」指的是實作計劃，不是跑既有任務
description: 當 plan mode 通過計劃後用戶說「開始執行」，是指實作計劃中的優化工作（程式碼改動、新 CLI、schema 遷移），不是切換身份去跑系統中已存在的任務
type: feedback
originSessionId: 7d4e5d63-920e-4d06-b12c-a763cf9fdb9e
---
當用戶在 plan mode 通過優化計劃後說「開始執行」、「使用 auto mode」，意思是**實作計劃本身描述的優化工作**（程式碼改動、新 CLI、資料模型擴充），不是切換身份去跑系統內既有任務。

**Why:** 2026-04-18 多 agent 3-terminal 計劃 v4 通過後，我 exit plan mode 就開始以 T1 supervisor 身份跑 Phase 0 預演，想 materialize 既有 next_tasks。用戶回：「你不是在做優化嗎 怎麼開始執行任務？」。我把「開始執行」誤讀為「開始運營系統」，正確意思是「開始實作計劃 Phase B/C 的優化工作」。

**How to apply:**
- Plan 通過後「開始執行」= 實作計劃描述的優化（寫 code、改 schema、加 CLI、migration、tests）
- 不是切身份跑既有 task；既有 task 會在優化完成後由用戶/workers 自行啟動消化
- 若計劃是純 workflow / prompt / 文件改動（零工程量），那「執行」才等於「按新 workflow 跑」
- 計劃有明確的 Phase A/B/C 時，自主判斷從哪個 Phase 開始，不問用戶
