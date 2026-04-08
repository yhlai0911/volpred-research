---
name: PRG session-by-session is NOT lookahead
description: Using realized overnight return to predict intraday variance is legitimate — overnight session ends before intraday starts
type: feedback
---

PRG model uses r²_overnight[d] to predict h_intraday[d]. This is NOT lookahead because the overnight session (close→open) completes BEFORE the intraday session (open→close) starts.

**Why:** The user (who designed the PRS/PRG model) explicitly stated: "可以用前一段交易時段的波動來預測接下來一段交易時段的波動，交替進行，並不會有 look-ahead bias。" Session by session — 夜盤收盤後早盤才開始。

**How to apply:** 
- Never flag session-boundary information as "lookahead" for periodic models
- Codex flagged this incorrectly (K880v2 "bug 1") — do NOT blindly accept Codex judgments about periodic/session models
- K880 (original) is correct; K880v2 bug 1 "fix" was wrong and degraded PRG unnecessarily
- GJR/HAR not having this info is by design — they don't decompose sessions. That's WHY PRG beats them.
- This applies to all session-based models: PRS, PRG, HAR with session regressors, BRG, etc.
- When Codex or any reviewer claims "lookahead" on a periodic model, verify the temporal ordering of sessions before accepting
