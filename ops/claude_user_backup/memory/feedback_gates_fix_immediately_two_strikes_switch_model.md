---
name: feedback-gates-fix-immediately-two-strikes-switch-model
description: 老闆 2026-07-13 Telegram 指示：每個關卡（gate/alert）壞了立刻徹底修好；同一關卡修兩次仍修不好就換 Fable 模型處理
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 8351b309-4243-4145-a883-a71729b88f77
---

老闆 2026-07-13 00:22（台灣時間）經 Telegram 下達 standing directive：「拜託徹底把每個關卡都立刻修好 兩次修不好就換fable模型」。

**Why:** 老闆連日收到重複的 gate/alert 失敗信（git_push_backup 12 天 33 次 exit1 等），對「同一關卡反覆壞」失去耐性。這是 [[feedback-fix-silent-fallback-immediately]] 與 Three-Strike Rule 的更嚴版本：門檻從 3 次降到 2 次。

**How to apply:**
- 任何 gate/alert/cron 關卡失敗 → 當下立刻根因修復（不是 suppress、不是排下班）。
- 同一關卡第 2 次修復後仍復發 → 升級處理：改用 Fable 模型（claude-fable-5）跑修復（`claude --model claude-fable-5` 或 dispatch 時指定），並照 Three-Strike 三層重構思維翻底層。
- 註：2026-07-13 起互動 session 已預設跑 Fable 5；此指示對 dispatch/subagent 的 model 選擇仍適用。
