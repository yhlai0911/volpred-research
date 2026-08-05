# Path ownership：Claude／Codex 互動工作與 Operations Core 的分工契約

**建立 2026-07-26**，起因：owner 詢問「Codex 在優化平台，Claude 會不會改到他的程式碼」。實測近 7 天
commit 足跡，**兩邊都寫過的檔案 40+ 個**，包含 `scripts/dispatch_supervisor/scheduler.py`、
`src/volpred/ops/feed_sync.py`、`storage/reports/feed.json`、`.claude/rules/publishing.md`。
既有的 `git_writer_lock` 只擋「同時寫壞」，**不擋「各自 lock、各自 commit、設計往兩個方向走」**。
這份契約補的是後者。

## 誰是誰

| Runtime | 進入點 | 指令檔 | 節奏 |
|---|---|---|---|
| Operations Core | `com.volpred.operations-core-scheduler` | `config/runtime_schedules.json` | 唯一 business clock；30 秒 reconcile |
| dispatch executor | `com.volpred.dispatch-supervisor` + local socket | `scripts/dispatch_supervisor/` | 無自有時鐘；只接 Operations Core tick |
| Claude 主線程 | Claude Code interactive session | `CLAUDE.md` + `.claude/rules/` + `.claude/skills/` | 互動 turn；不是 schedule owner |
| Codex interactive | Codex app／CLI | `AGENTS.md` | 互動 turn；不是 schedule owner |
| legacy Codex loop | `scripts/codex_loop.sh` | rollback only | SessionStart 預設 no-op，不自動啟動 |

模型派發仍以 stable owner token／fire receipt 防重；純程式 schedule receipt 與
模型 completion receipt 分開。`storage/next_tasks.json` 的 admission 是否開放仍由
`storage/ops/task_pool_mode.json` 決定，不能因互動 app 啟停而改變。

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

### D. 組織區 — `storage/org/**`（磁碟持久化組織，2026-08-05 立）

部門制多 agent 架構的組織態（registry、charter、記憶、inbox、journal）全在此區，
全部進 git（`receipts/` 除外，gitignored）。寫入權限依角色劃分：

| 角色 | 可寫 | 禁寫 |
|---|---|---|
| 運營經理 | `registry.json`（僅經 `scripts/org/org_admin.py`）、`bulletin/`、任何部門 `inbox/`、`manager/**` | 部門的 `journal.md` / `state.json` / `memory/`（那是部門收尾契約義務） |
| 部門 session | 自己的 `departments/<自己>/**`；工作報告經 `scripts/org/dept_send.py --to-manager` | registry、其他部門子樹、`manager/**` 直寫 |
| boss I/O adapter（telegram/gmail 路由） | `manager/inbox/`（僅經 `scripts/org/org_intake.py`） | 其他一切 |

規矩：`bulletin/` 是 append-only（同 C 區慣例）；registry 變更一律走 `org_admin.py`
（它會同步寫 bulletin），禁裸編輯 JSON；部門 owned_paths 由 `org_admin.py create`
在建立時做衝突檢查，不得與 A/B 區或其他部門重疊。

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

### 2026-07-26 接線實作更新（Issue #37）

上述方向已由 runtime bridge 落地，但 ownership 邊界不變：

- `issue_ref` 是 planning foreign key，不是第二套 pending queue；
- canonical ingress 將 GitHub URL／issue number正規化為 `#N`；
- local claim 是執行 ownership source of truth，GitHub assignee同步失敗只留下可觀察
  receipt，不可回滾或阻塞本地 claim；
- task成功只寫`issue_close_pending`，精確Git writer／PHASE-Z取得真實commit SHA後才
  close issue並回寫`issue_closed_commit`；
- GitHub已由同一task/commit marker關閉時可安全replay；無marker的外部關閉不得冒認；
- direct-execution mode只允許既有identity的lifecycle／metadata settlement，這條橋
  不會為了同步GitHub而恢復legacy admission。

實作與回歸 owner：`src/volpred/ops/issue_tracker_sync.py`、
`src/volpred/ops/next_tasks.py`、`scripts/task_pool_claim.py`、
`scripts/git_writer_lock.py`及PHASE-Z post-commit seam。操作細節以
`docs/agents/issue-tracker.md`為單一SOP來源。

## 有效期

Operations-core 重構完成（program commit 15 的 physical two-Mac authority receipt pair 落地）後
重新評估 A 區範圍。屆時 `src/volpred/ops/**` 應交回共用區。
