---
name: feedback-answer-first-then-act
description: 老闆問問題時必須先在對話串直接回答，不可先跑一串 shell 指令才回話（2026-07-02 連續三則訊息糾正，最後動怒）
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 84ae09c8-9673-48d4-b7bc-6113766e22dc
---

老闆在對話裡問問題（「你建議是？」「會改善嗎？」等）時，我連續用 shell 指令回應而不是先講結論，老闆連發三則訊息糾正（「不是應該直接在對話串回應我嗎」→ 動怒）。

**Why:** 對話中的問題，deliverable 是答案本身。先跑指令再答會讓老闆像在對一台沒有回應的機器說話；查證只在答案需要事實依據且缺該事實時才做，且應最小化。執行型指令（「回復狀態」）才是先做後報。

**How to apply:**
1. 收到疑問句 → 第一動作是文字回答（用已知資訊給結論與建議），不開工具。
2. 答案真的缺關鍵事實才查，且一次查完、簡短回報。
3. 執行型指令照舊先做，但做完用一兩句話回報，不把對話串塞滿指令輸出。
4. 問題與執行混在一起時：先答問題，再做事。

相關：[[feedback-dont-ask-do]]、[[feedback-own-judgment-dont-credit-user]]
