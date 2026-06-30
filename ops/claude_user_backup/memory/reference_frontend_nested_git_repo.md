---
name: reference_frontend_nested_git_repo
description: frontend-v2-fix 是獨立巢狀 git repo（主 repo gitignore 它）；commit 前端要 cd 進去
metadata: 
  node_type: memory
  type: reference
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

`frontend-v2-fix/` 是**獨立的巢狀 git repo**,被主 repo 的 `.gitignore`(第 40 行 `frontend-v2-fix/`)忽略。

**改完前端要 commit**:
```bash
cd frontend-v2-fix && git add <files> && git commit -m "..."
# 或 git -C frontend-v2-fix add/commit
```

在**主 repo 根目錄** `git add frontend-v2-fix/...` 會報「ignored by .gitignore / no changes added」—— 不是檔案沒存,是主 repo 不追蹤這目錄。前端有自己的 `.git`、自己的 commit 歷史,**deploy（deploy-zeabur-safe.sh）從這個 repo 出**。

**反覆踩坑**(用戶 2026-06-05「每次都要錯一次」糾正):error_log 2026-04-27 提過但沒寫進會自動載入的規則 → 每次重犯。已補進 `.claude/rules/frontend-and-deploy.md` 最上方醒目警告(碰 `frontend-v2-fix/**` 就 load)。

**Why**:規則要在「出錯的那一刻」surface(CLAUDE.md path-trigger 時序原則)。深埋 error_log 不會在工作時提醒。

相關:[[reference_zeabur_deploy_target]]、[[feedback_test_before_deploy]]。
