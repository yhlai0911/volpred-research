---
name: reference-advisor-fable-bug
description: advisor 設 fable 後 unavailable 的根因（CC bug
metadata: 
  node_type: memory
  type: reference
  originSessionId: 2c02c0a5-d84a-4ddd-a4c1-5f243d01e172
---

**現象**：`~/.claude/settings.json` 設 `model: fable` + `advisorModel: fable` 後，session 內呼叫 advisor 一律回「The advisor tool is unavailable. Do not try to use it again.」

**根因（2026-07-15 上網查證 + 本機實測，CC 2.1.206）**：
- GitHub Issue **anthropics/claude-code#76199**（open，2.1.205/206 未修）：`advisorModel: fable` + transcript 內**有任何 tool_use**（Bash/Read/任何工具）→ 後端 deterministic 回 generic "unavailable"，且單次失敗就把工具鎖死整個 session。executor 是誰無關；`advisorModel: opus` immune。相關：#67609（fable + >100K tokens）、#73923（被 76199 supersede）、#66784（generic error 無診斷）。
- 本機實測 b：`claude --model fable --advisor fable -p "先呼叫 advisor"`（無前置 tool_use）→ **成功** ✅（證實 pairing 合法、fable 可用，bug 只在 tool_use 後觸發）
- 本機實測 a：`claude --model fable --advisor opus` + 先跑 Bash → advisor 工具**根本沒掛載**（docs pairing 規則：advisor 弱於 main 就不 attach；opus < fable）

**結論**：main=fable 時 advisor 實際無解 — fable advisor 撞 #76199（實務 session 必有 tool_use），更弱的 advisor 不掛載。Anthropic 推薦的組合是 main=opus/sonnet + advisor=fable（advisor-executor pattern），但同樣被 #76199 擋，需等修復。

**替代**：平台既有 Codex（`codex exec`）/ agy 三模 review 已覆蓋 stronger-reviewer 需求。

**重測條件**：Claude Code 升級（>2.1.206）後重跑實測 a/b 兩條命令；#76199 關閉即可恢復 `advisorModel: fable`。
