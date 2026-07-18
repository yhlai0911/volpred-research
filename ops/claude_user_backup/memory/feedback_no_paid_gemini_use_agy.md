---
name: feedback-no-paid-gemini-use-agy
description: 老闆硬指令 — 禁止用付費 Gemini API（scripts/gemini_ask.py），headless Gemini 一律走免費的 agy
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 1cdc09c3-2043-4275-af96-5f639ec818c5
---

老闆 2026-07-18（Telegram msg 936）硬性指令：**「我不要用 API 我不要付錢 要用 agy」**。
起因是收到 gemini_ask.py 觸發 PAID Gemini API 的警報。

**Why**：`scripts/gemini_ask.py` 每次成功呼叫都直打 Gemini API → 產生真實費用。老闆不接受
為 headless Gemini 付費；`agy`（Antigravity CLI，Google OAuth，免費）已可用且 headless
`agy -p` 實測正常。

**How to apply**：
- headless Gemini 一律走 `agy -p "<prompt>"`（用法/陷阱見 [[reference-antigravity-cli]]：
  `-p` 吃參數不吃 stdin、多行用 heredoc、換模型用 `ANTIGRAVITY_MODEL`）。
- **不要**把 `gemini_ask.py` 當自動 fallback。它應為需明確 opt-in 的最後手段或直接加 hard
  guard，任何自動流程（review / lazypack / 圖）都不得再打付費 API。
- 稽核工具：`storage/logs/gemini_ask_usage.jsonl` — 若自動流程仍出現在此 log 即為違規。
- 修 repo 的後續任務見任務池 `assign_f8da7545`（2026-07-18 建）。
- 相關：[[reference-dual-cli-availability]] / [[feedback-gemini-v042-skip-trust]]
