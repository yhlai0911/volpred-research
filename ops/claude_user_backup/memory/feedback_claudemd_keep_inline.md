---
name: claude-md
description: CLAUDE.md 參考資料不可移到外部文件按需讀取，因為 Claude 常忘記讀外部文件導致犯錯
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 84ae09c8-9673-48d4-b7bc-6113766e22dc
---

CLAUDE.md 的參考資料（架構、指令、Registry 表等）必須保持 inline，不要移到外部文件。

**Why:** 實際經驗證明，移出去的內容 Claude 在需要時經常忘記去讀外部文件，導致犯錯。16,800 tokens 固定成本在 1M context window 中佔比 <2%，是值得付的代價。

**How to apply:** 不要建議或執行「把 CLAUDE.md 內容移到 docs/ 按需讀取」的瘦身方案。要省 token 應找其他途徑（如對話歷史壓縮、減少不必要的 Read），而不是拆 CLAUDE.md。

---

**2026-07-01 memory-hygiene 更正（dreaming consolidation_review finding）**：此則與同日稍晚（7 小時後）寫的
[[feedback_progressive_disclosure]] 在字面上矛盾（「不要移出」vs「用 skill 漸進揭露就是要移出」）。
比對現行 `CLAUDE.md`「Bootstrap 原則」段（「這份 CLAUDE.md 只保留每次 session 都必須先知道的核心規則...
較長的細節拆到 `.claude/skills/`」）與實際運作方式，**確認 `feedback_progressive_disclosure` 是後續生效
的實作方向，此則「絕對不要移出」的原始建議已被取代**。保留此檔不刪（研究誠實 + memory 保留完整歷史），
但**新任務請以 `feedback_progressive_disclosure` + `feedback_keep_concise_mnemonics` 為準**：
- 可以移出去 skill / docs（漸進揭露），前提是 skill 有明確 trigger description 讓 Claude 知道何時載入
- 純「見 docs/xxx.md」without skill trigger 才是本則原本要禁止的反面模式（那種確實容易被忘記讀）
- CLAUDE.md 內「一句話 mnemonic 摘要」段落例外，永遠保留 inline（見 `feedback_keep_concise_mnemonics`）
