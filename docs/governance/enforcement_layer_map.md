# Enforcement Layer Map

本檔是 L1 enforcement inventory 的 canonical owner。它不是 workflow skill，也不應被 skill
精簡或遷移流程刪除。`scripts/audit_enforcement_map.py` 會從磁碟重建下列四張表並逐項比對；
新增或移除 hook、deny 規則、CI job、git hook 時，必須在同一個 commit 更新本檔。

一個 concern 只設一個 enforcement owner；新增約束前先查本表，優先收編進既有 owner。

## Claude Code hooks

<!-- AUDIT:HOOKS -->
| 事件 | matcher | owner script（repo 相對路徑） | 擋什麼 / 做什麼 |
|---|---|---|---|
| `SessionStart` | `*` | `scripts/auto_start_codex_loop.sh` | 冪等啟動 detached `codex_loop.sh` |
| `SessionStart` | `*` | `scripts/warm_tcc_authorization.sh` | macOS TCC 授權預熱 |
| `UserPromptSubmit` | `*` | `.claude/hooks/email_pool_reminder.sh` | pending `email_reply` 提醒 |
| `Stop` | `*` | `scripts/save_session_state.sh` | 保存 session state |
| `Stop` | `*` | `scripts/hooks/enforce_final_text.py` | 禁止無最終文字結束 turn |
| `Stop` | `*` | `scripts/hooks/enforce_fire_receipt.py` | 有產出的 fire 必須留下 receipt |
| `PreCompact` | `*` | `scripts/save_session_state.sh` | compact 前保存 session state |
| `PreToolUse` | `Bash` | `.claude/hooks/pretooluse-bash-optimizer.sh` | Bash deny 與指令防呆 |
| `PreToolUse` | `ScheduleWakeup` | `scripts/hooks/deny_wakeup_interactive.py` | 互動 turn 禁用 ScheduleWakeup |
| `PreToolUse` | `Read` | `scripts/hooks/read_context_budget.py` | 限制無界整檔讀取 |
| `PreToolUse` | `Edit&#124;Write&#124;MultiEdit&#124;NotebookEdit` | `scripts/hooks/gate_edit_guard.py` | 編輯前保全 gate 原始 bytes |
| `PostToolUse` | `Edit&#124;Write&#124;MultiEdit&#124;NotebookEdit` | `scripts/hooks/record_fire_manifest.py` | 記錄 fire producer manifest |

## PreToolUse deny 規則

key 是 deny 訊息開頭到第一個 `（` 或 `。` 為止。

<!-- AUDIT:DENY -->
| deny key | owner | 擋什麼 | 為什麼 |
|---|---|---|---|
| `禁止在 dispatch fire 內 spawn headless agent` | `pretooluse-bash-optimizer.sh` | fire 內 `claude -p` / `agy -p` | 避免超過 fire hard cap |
| `禁止 git worktree remove --force` | `pretooluse-bash-optimizer.sh` | 強制刪除 worktree | 避免未合併產物遺失 |
| `禁止直呼 zeabur deploy` | `pretooluse-bash-optimizer.sh` | 直接部署 | 強制使用鎖定 service 的安全入口 |
| `禁止整檔讀取 feed.json / knowledge.json` | `pretooluse-bash-optimizer.sh` | 無界讀 canonical 大檔 | context/token 紀律 |
| `禁止裸跑 codex exec` | `pretooluse-bash-optimizer.sh` | 無 timeout 的 Codex job | 避免撞 hard cap |
| `共用 main checkout 禁止裸 Git mutation` | `pretooluse-bash-optimizer.sh` | main 的 stage/merge/ref mutation | 強制 Git writer lease |
| `禁止用 git commit -m 內嵌非 ASCII` | `pretooluse-bash-optimizer.sh` | 非 ASCII inline message | 避免不可回復的編碼錯誤 |
| `hook:scripts/hooks/deny_wakeup_interactive.py` | 該 hook | 互動 turn 的 `ScheduleWakeup` | 防止使用者回合被吞掉 |

## CI

<!-- AUDIT:CI -->
| workflow 檔 | job id | 擋什麼 |
|---|---|---|
| `experiment-artifacts.yml` | `artifacts` | 實驗 artifact 完整性 |
| `knowledge-provenance.yml` | `audit` | canonical state provenance 與 vocabulary |
| `pytest.yml` | `pytest` | 測試與 tree-clean gate |
| `silent-fallbacks.yml` | `audit` | 新增 silent fallback |
| `source-encoding.yml` | `audit` | mojibake / 非 UTF-8 原始碼 |

## Git hooks

canonical source 是 `scripts/git_hooks/`；`.git/hooks/` 是安裝副本。

<!-- AUDIT:GITHOOKS -->
| 檔名 | 擋什麼 | 觸發時機 |
|---|---|---|
| `pre-commit` | source encoding、silent fallback、candidate test closure | `git commit` |
| `pre-push` | 對被推 commit 的 encoding、fallback、test-import gate | `git push` |
| `prepare-commit-msg` | 非 ASCII / 非 UTF-8 commit message | 產生 commit message |
| `reference-transaction` | main/ref mutation 必須持有 Git writer lease | ref transaction |
| `git-writer-lease-verify.py` | reference-transaction 的 lease 驗證實作 | 由 hook 呼叫 |
