---
name: feedback-gemini-v042-skip-trust
description: Gemini CLI v0.42+ headless 必加 --skip-trust，否則 -y/YOLO 被強制降回 default mode、prompt silent fail（stdout 空）
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0ca8f10c-d34e-4570-af41-a25c2fff4e5c
---

Gemini CLI **v0.42+** headless 模式必繞過 trusted-folder gate，否則 `-y` / `--approval-mode yolo` 會被覆寫成 `default`，prompt 不會執行而 stdout 完全空。

**首選方法（2026-05-14 二次驗證）**：用 env var `GEMINI_CLI_TRUST_WORKSPACE=true gemini -y -p "..."`
- **`--skip-trust` flag 在 v0.42.0 實測會 hang**（2026-05-14 smoke test：`gemini -y --skip-trust -p "echo OK"` 跑 6 分鐘無輸出無錯誤，必須手動 kill）— 不知道是 bug 還是 flag 已重命名，避用
- env var 路徑 PASS：3 秒內回 `OK`（同 prompt 同目錄）

**Why**：v0.42 新增 trusted directories 安全機制，自動拒絕未授信目錄的 YOLO。stderr 訊息：`Approval mode overridden to "default" because the current folder is not trusted.`

**How to apply**：
- 所有 `gemini -p` headless call 預設用 `GEMINI_CLI_TRUST_WORKSPACE=true gemini -y -p "..."`
- 若必須走 flag 路徑（例如 prompt 太長），先 smoke test 確認該機器 `--skip-trust` 不 hang
- Debug「為什麼 gemini 沒輸出」時**先看 stderr**（去掉 `2>/dev/null`），trust 錯誤只在 stderr
- 相關記錄：[[feedback-3model-review-discipline]] / [[feedback-gemini-cli-share-load]]
- Skill：[gemini-cli](/Users/yhlai0911/.claude/skills/gemini-cli/SKILL.md) 已更新

---

**2026-07-01 memory-hygiene 更正（dreaming consolidation_review finding）**：`gemini-cli` 本身已於
2026-06-18 因 Google 停服而**棄用**（見 CLAUDE.md「已放棄：gemini-cli」+ skill 檔已標 DEPRECATED）。
此則記錄的 `--skip-trust` hang bug / env var workaround 已無實際操作意義（工具不再使用）。**繼任工具是
`agy`（Antigravity CLI，OAuth）headless / `scripts/gemini_ask.py`（直打 API，需 email 通知 + log 使用）**
— 見 user memory `reference_antigravity_cli` + `reference_dual_cli_availability`。保留此檔作歷史記錄
（研究誠實：不刪除已發生的診斷過程），但**新任務不要再依此則操作 gemini-cli**。
