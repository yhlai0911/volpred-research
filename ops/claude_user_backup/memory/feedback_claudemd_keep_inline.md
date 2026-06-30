---
name: CLAUDE.md 不要移出內容
description: CLAUDE.md 參考資料不可移到外部文件按需讀取，因為 Claude 常忘記讀外部文件導致犯錯
type: feedback
---

CLAUDE.md 的參考資料（架構、指令、Registry 表等）必須保持 inline，不要移到外部文件。

**Why:** 實際經驗證明，移出去的內容 Claude 在需要時經常忘記去讀外部文件，導致犯錯。16,800 tokens 固定成本在 1M context window 中佔比 <2%，是值得付的代價。

**How to apply:** 不要建議或執行「把 CLAUDE.md 內容移到 docs/ 按需讀取」的瘦身方案。要省 token 應找其他途徑（如對話歷史壓縮、減少不必要的 Read），而不是拆 CLAUDE.md。
