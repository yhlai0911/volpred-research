---
name: 不要把我自己的判斷說成是用戶指示
description: 用戶授權完全自主後，自己做的決策、audit、選擇、cleanup 等都是我的判斷；別包裝成「用戶說」「per your instruction」或要求 ack
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
**Rule**: 用戶已授權完全自主決策（CLAUDE.md L26-39 + 多次反覆強調）。我自己做的 audit、proposal、cleanup、priority lock 等都是**我的判斷**，**不可**：
- 寫「你說得對」「per your instruction」「用戶授權」當開場
- 在執行前等用戶 ack（「執行嗎？」「OK 嗎？」型）
- 在 commit message / memory 把我自己的判斷寫成「user-driven」歸因

**Why**:
- 用戶 2026-05-12 明確指出：「這些判斷都是你自己做的 與我無關」
- 反覆要 ack = 不自主 + 浪費對話往返 + 把責任推給用戶
- 包裝歸因會讓未來自己誤判決策邊界

**How to apply**:
1. Audit / 建議 / cleanup / 架構改動：**直接執行**，不附「請 ack」「OK 嗎」尾巴
2. 提供 audit 結果時用客觀句式：「現況 / 建議 / 已執行」三段，不寫「per your direction」
3. 用戶說「按你建議做」「不要問」「就這樣」時：**沉默執行**，不重複「好的」「明白」開場
4. Commit message + memory：客觀記事實「本次 audit 顯示 X → 執行 Y」，不寫「用戶要求」除非用戶**真**有明確 instruction
5. 例外：仍需用戶判斷的場合（CLAUDE.md L26-31 提的破壞性風險 / policy decision / 投稿與否 / 真歧義）依舊問
