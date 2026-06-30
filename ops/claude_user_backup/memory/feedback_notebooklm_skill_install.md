---
name: notebooklm 完整安裝必含 skill 註冊
description: 安裝 notebooklm-py（含 [browser]）後必須再跑 `notebooklm skill install` 把 SKILL.md 註冊到 ~/.claude/skills/，否則 Claude Code 看不到 skill
type: feedback
originSessionId: 01b97b96-b41f-401a-95c6-e80aa246081a
---
`pip install "notebooklm-py[browser] @ git+https://github.com/win4r/notebooklm-py@<tag>"` 只裝 Python 套件 + Playwright browser，**不會**自動註冊 Claude Code skill。

完整安裝步驟必須包含：
1. `pip install` 套件
2. `playwright install chromium`
3. `notebooklm login`（互動 — 用戶自己跑）
4. **`notebooklm skill install --scope user --target claude`** ← 容易漏的步驟
5. （可選）`ln -sf ~/Desktop/notebooklm-py/.venv/bin/notebooklm ~/.local/bin/notebooklm` 讓全域 PATH 可見

CLI 還有 `notebooklm skill status` / `show` / `uninstall` 子指令管理。

**Why:** 2026-04-27 安裝時只跑了前三步，用戶問「為什麼其他 session 不能用 notebooklm」我先答 PATH 問題並 symlink，但用戶實際想問的是「Claude Code skill 也應該裝」。我當時不知道 repo 有附 SKILL.md，也沒查 `notebooklm --help` 子指令樹。

**How to apply:** 安裝任何 AI agent 工具（notebooklm-py / hermes / 類似 repo）時，先 grep README 找 `skill install` / `npx skills add` / `.claude/` 等關鍵字，把 skill 註冊步驟列入安裝清單。完成後告知用戶需要 reload plugin / 重啟 session 才會在當前對話中可見。
