# Path ownership：Claude 主線程 × Codex loop 的分工契約

**建立 2026-07-26**，起因：owner 詢問「Codex 在優化平台，Claude 會不會改到他的程式碼」。實測近 7 天
commit 足跡，**兩邊都寫過的檔案 40+ 個**，包含 `scripts/dispatch_supervisor/scheduler.py`、
`src/volpred/ops/feed_sync.py`、`storage/reports/feed.json`、`.claude/rules/publishing.md`。
既有的 `git_writer_lock` 只擋「同時寫壞」，**不擋「各自 lock、各自 commit、設計往兩個方向走」**。
這份契約補的是後者。

## 誰是誰

| Runtime | 進入點 | 指令檔 | 節奏 |
|---|---|---|---|
| Claude 主線程 | Claude Code session + `dispatch-supervisor` daemon | `CLAUDE.md` + `.claude/rules/` + `.claude/skills/` | 每小時 `:07` dispatch；互動 turn 隨時 |
| Codex loop | `scripts/codex_loop.sh`（VSCode 終端常駐，單一 instance lock） | `AGENTS.md` | 每小時 tick，`codex exec resume --last` |

兩邊從**同一個** `storage/next_tasks.json` claim 任務，claim 帶 owner token
（`codex-vscode` / `codex-cli` / `hourly-slot-N-<hash>`）。

## 三區分工

### A. Codex 專屬 — 動手前必須先協調

operations-core 重構（`docs/refactor_plan_ops_master_2026_07.md` program commit 15）期間，
以下 path 由 Codex 擁有。近 7 天只有 Codex 寫過，Claude 一次都沒碰：

- `src/volpred/ops/**`（delivery、work_shadow_*、work_cutover、task_pool_mode…）
- `supabase/migrations/**`
- `docs/operations_core_module_design.md`
- `tests/test_postgres_*.py`、`tests/test_work_*.py`、`tests/test_change_delivery.py`
- `scripts/rehearse_primary_authority_outage.py`、`scripts/git_writer_lock.py`

**Claude 要動這些 → 先開 GitHub Issue 或 `gh issue comment` 對應 ticket，不要直接改。**
例外：production 掛掉的止血，改完當回合在 `docs/error_log.md` 記錄並標記給 Codex。

> **⚠️ 不要用 `volpred ops assign` 建單。** `storage/ops/task_pool_mode.json` 自 2026-07-23T12:49Z
> 起 `enabled=true, mode=direct_execution`（`activated_by: codex-vscode`，理由「Telegram 1329
> owner-directed direct execution; suspend legacy task-pool admission during operations-core
> cutover」）。**legacy next_tasks admission 已關閉**，任何新 task id 會被
> `task_pool_mode.enforce_task_pool_write()` 擋下並拋 `TaskPoolAdmissionClosed`（生命週期更新與
> 刪除仍放行）。operations-core cutover 期間，**新工作的唯一登記處是 GitHub Issues**。

### B. Claude 主線程專屬 — Codex 不應主動改

- `paper/**`（CLAUDE.md 明文禁止 background agent 寫 `.tex`）
- `experiments/k*/`（K 編號由主線程分配，`storage/ops/k_id_registry.json` 是 registry）
- `.claude/skills/**`、`.claude/rules/**`、`CLAUDE.md`
- `research_program.md`
- `frontend-v2-fix/**`
- `storage/reports/feed.json` 的**內容決策**（發佈走 `feed-publisher`；Codex 可修事實錯誤，但要走
  `scripts/publish_draft.py --update`，不直寫）

**近 7 天違規實例**：Codex 改過 `.claude/rules/publishing.md` 與
`.claude/skills/feed-publisher/SKILL.md`。依 `feedback_skill_autonomy`，改既有 skill 必須寄信通知
owner —— 這條規則寫在 `CLAUDE.md`，**`AGENTS.md` 沒有**，所以 Codex 不知道。已在 AGENTS.md 補上。

### C. 共用區 — append-only，衝突機率低但要守規矩

| Path | 保護機制 | 規矩 |
|---|---|---|
| `docs/error_log.md` | 無（append-only 慣例） | 一律 append 到檔尾，不重排既有段落 |
| `docs/project_improvement_status.md` | 無 | 同上 |
| `docs/architecture.md` | 無 | 改前先 `git log -3 --oneline -- <file>` 看對方剛動過什麼 |
| `storage/next_tasks.json` | `storage/ops/locks/next_tasks.lock` + claim token | 只走 `src/volpred/ops/next_tasks.py` 三入口，禁裸寫 |
| `storage/work_log.json` | codex_loop 的 backfill hook | Codex tick 後自動 backfill，Claude 不手動補 |
| `AGENTS.md` | 無 | **兩邊都改過**。Claude 改此檔 = 對 Codex 下指令，改完要在回覆說明 |
| 所有 git commit | `scripts/git_writer_lock.py` | 一律走 lock，禁裸 `git commit` |

## 動手前的 30 秒檢查

改任何 `src/volpred/ops/**`、`scripts/dispatch_supervisor/**`、`tests/**` 之前：

```bash
git log -5 --oneline -- <path> && git status --porcelain -- <path>
```

- 最近 5 筆有 `[codex]` → 屬 A 區或熱區，先協調
- `git status` 非空 → **Codex 這個 tick 正在寫**，等他 commit 完再動（`ps -ax | grep 'codex exec'`
  看 tick 是否在跑）

## Plan / spec / ticket 三層現況

| 層 | 位置 | 狀態 |
|---|---|---|
| Plan（策略） | GitHub Issue #3「VolPred 平台全域優化」 | 存在 |
| Spec（設計） | `docs/refactor_plan_ops_master_2026_07.md`（WS-A~H + 狀態表）、`docs/operations_core_module_design.md` | 存在，Codex 正在執行 |
| Ticket（工單） | GitHub Issues #5~#36，25 張 `[Plan T01~T33]`，含 What to build / Acceptance criteria / Blocked by | **存在但斷線** |

**cutover 期間 GitHub Issues 是唯一開著的工單入口**（`next_tasks` admission 已關，見上方 A 區警示）。

**斷線點**：25 張 ticket 全部 `ready-for-agent`、零 assignee，且 `storage/next_tasks.json`
沒有任何一筆引用 issue 編號（實測 grep = 0）。`docs/agents/issue-tracker.md` 明寫
「materialize 到 next_tasks.json 必須引用本 issue，且不得建立第二套 pending queue」——
這條契約目前無人遵守，於是 ticket 層與執行層各走各的。

**接線方向**（未實作，追蹤中）：next_tasks 任務加 `issue_ref` 欄位，dispatcher 派工時
`gh issue edit <n> --add-assignee`，完成時 `gh issue close`。這樣三層收斂成一份真相。

## 有效期

Operations-core 重構完成（program commit 15 的 physical two-Mac authority receipt pair 落地）後
重新評估 A 區範圍。屆時 `src/volpred/ops/**` 應交回共用區。
