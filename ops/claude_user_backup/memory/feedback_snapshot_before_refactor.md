---
name: 結構性重構前必先 commit snapshot
description: 動 CLAUDE.md / rules / skills / memory 等治理檔前先 commit snapshot，保留回滾點
type: feedback
originSessionId: 4742deae-8cbd-477f-a560-11e57f03099f
---
結構性重構（CLAUDE.md、.claude/rules/、.claude/skills/、memory/ 等治理檔同批改動）動手前，**先 commit 當前狀態做 snapshot**，commit message 加 `snapshot:` prefix 供日後 `git log --grep="snapshot:"` 找回滾點。

**Why:** 用戶 2026-04-20 指示：「要 commit 一份起來 未來有必要才能回滾」。治理檔動到好幾支、影響 session auto-load 行為，回滾粒度要夠細才能隔離問題；沒 snapshot 就動 → 若發現觸發規則失效或誤觸發，要一支支 revert 非常痛苦。

**How to apply:**
- 批次改多個治理檔前：`git add CLAUDE.md .claude/rules/ .claude/skills/ <memory_dir>/ && git commit -m "snapshot: pre <topic> baseline"`
- 不帶 `storage/` / 日誌類無關檔（避免 snapshot 噪音）
- 改動分組 commit，每組一個主題（例如 `rules: slim X` / `claude.md: remove duplicated Y`），讓 revert 粒度可控
- 適用情境：token optimization refactor、path 收窄 audit、rule 搬家到 skill references、CLAUDE.md 精簡等
- 不適用情境：單檔小修、明確 scoped 的 bugfix、feed.json / storage json 類資料檔（後者有 supabase_sync 還原）
