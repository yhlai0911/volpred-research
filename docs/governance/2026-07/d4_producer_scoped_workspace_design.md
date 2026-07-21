# D4 — Producer-scoped workspace：現況盤點、遷移路徑與分段落地

- **任務**：`assign_c90c43c7`（D4·架構）
- **狀態**：**設計文件，未改任何既有程式碼**。本文不描述現行 runtime 行為，除了 §1 明確標「實測」的部分。
- **上游裁決**：`docs/governance/2026-07/phase_z_ownership_external_review.md` §4 D4
- **既有設計**：`docs/dispatch-writer-isolation-design.md`（2026-07-14，WS-B）。本文**不取代它**，是它的續篇：WS-B 定義了 contract 與 cutover 階段，本文補三件它沒有的東西 —— (a) 遷移成本的具體盤點，(b) 依賴/cache 與整合延遲的量化，(c) 依「已實測的 pilot 失敗狀態」重排的落地段。
- **機械 gate**：`scripts/tests/test_phase_z_ownership_class_gate.py`（D1：不得新增第 4 個 provenance guess）

> 核心約束（逐字，來自外部審查）：
> **「你一直在讓 cleanup layer 解 ownership。Ownership 必須由 execution isolation 產生，不能由 cleanup layer 事後推理。」**

---

## 0. 本文最重要的一個發現：WS-B pilot 已上線，但整合率是 0%

`config/runtime_schedules.json` 的 `daemons[volpred-dispatch-supervisor].writer_isolation.mode` **目前是 `"pilot"`**，不是 `off`。也就是說 D4 不是從零開始 —— 隔離 lane 已經在跑。但實測 receipt（`storage/ops/dispatch_workspace_receipts.jsonl`，628 筆）顯示它處於**全失敗的穩態**：

| 觀測 | 實測值 |
|---|---|
| receipt 事件種類 | 只有 `finalized`（578）與 `allocation_skipped`（50）—— **從未出現 `allocated`** |
| finalize 的 `worker_outcome` | **578/578 全部是 `orphaned`** |
| finalize 的 `disposition` | **578/578 全部是 `remediation_opened`** |
| 成功併入 main 的次數 | **0**（全檔 grep `merged` = 0） |
| `allocation_skipped` 原因 | **50/50 是 `total_cap`**（`existing=3, max_total=3`） |
| 涉及的 distinct workspace | 17 個，最早 `2026-07-20T10:19` |
| 單一 workspace 被 finalize 次數 | 最高 50 次（`dispatch-slot-1-bd00f90a-k1731`） |
| remediation 實際建立 | `{"task_id": null, "created": false, "action": "throttled"}` |

推論（三條，皆可由 receipt 直接讀出，非猜測）：

1. **finalize 不是冪等的 terminal 動作**。同一個 workspace 被重複 finalize 數十次，代表 orphan sweep 每 tick 重跑一次 finalizer，而 finalizer 沒有把 workspace 移出「待掃」集合。578 筆 receipt 其實只對應 17 個真實事件。
2. **「絕不 strand」的保證目前沒有成立**。WS-B 的 no-deadlock 承諾是「紅 gate / 失敗 merge / 中途死掉 → 開 P2 remediation 單」，但實測 `created: false / action: throttled` —— 單沒開，worktree 被保留，然後 worktree 佔住 `max_total=3`，於是後續 50 次配發全被 `total_cap` 擋掉。**這是一個自鎖迴圈**：失敗 → 保留 worktree → 佔滿額度 → 新 fire 拿不到隔離 → 全部退回 shared main → PHASE-Z 繼續猜作者。
3. **沒有任何一筆 setup latency 被記錄**。`allocated` 事件根本沒出現過，所以 WS-B §2 那句「worktree setup latency：目前未記錄；不可虛構數字」到今天仍然成立。本文 §4 的時間估計因此只能是**推導值並標明估法**，不是實測。

⇒ **D4 的第一段不是「設計新架構」，是「把已經寫好的隔離層從自鎖狀態裡拆出來並讓它真的跑完一次」**。在 0 次成功整合之前，任何關於 producer-scoped workspace 是否可行的宣稱都沒有證據支撐。

---

## 1. 現況盤點：誰假設自己跑在 canonical cwd / 直接寫 main checkout

全部用 Grep/Glob 實掃 `scripts/`、`src/`、`config/`、`~/Library/LaunchAgents/`，日期 2026-07-22。`scripts/_legacy/` 與 `scripts/tests/` 已從「live 遷移成本」中排除但另計。

### 1.1 規模底數

| 項目 | 數量 |
|---|---:|
| `scripts/*.py` | 174 |
| `scripts/*.sh` | 63 |
| repo 追蹤的 `storage/` 檔 | 4,313 |
| repo 追蹤的 `config/` 檔 | 24 |

### 1.2 A 類 —— shell 入口：硬編碼 canonical root 並 `cd` 進去（**44 個 live**）

判準：檔內出現 `cd /Users/yhlai0911/volpred-research` 或 `REPO_ROOT=/…` / `PROJECT_DIR=/…` / `ROOT=/…` 字面路徑。

- **42 個 `scripts/cron_*.sh`**：
  `cron_arxiv_scan` `cron_audit_fb_pipeline` `cron_audit_publish_sync` `cron_backup_user_claude` `cron_boss_report` `cron_build_publication_candidates` `cron_check_alerts` `cron_codex_update` `cron_collect_tw` `cron_collect_us` `cron_compute_worker` `cron_continue_task_stub` `cron_daily_checkup` `cron_daily_update` `cron_daily_update_intraday` `cron_drain_failed_syncs` `cron_dreaming_review` `cron_enqueue_daily_digest` `cron_fb_ttl_expire` `cron_feed_sync` `cron_fred_backfill_guard` `cron_gmail_poll` `cron_handoff_regen` `cron_indicator_arena_daily` `cron_liveness_reconcile` `cron_market_cal` `cron_market_closure` `cron_memory_health` `cron_ops_dashboard` `cron_paper_sync_all` `cron_populate_events` `cron_question_ops_maintain` `cron_radar_strategy_snapshot` `cron_reader_facing_refill` `cron_reader_metrics` `cron_reader_preferences` `cron_reclaim_stale_worktrees` `cron_refresh_paper_snapshots` `cron_release_pool` `cron_release_settings_audit` `cron_research_backlog` `cron_telegram_poll`
- **2 個非 cron shell**：`scripts/save_session_state.sh`、`scripts/telegram_responder.sh`
- **另計（不遷移）**：`scripts/_legacy/cron_work_summary.sh`、`scripts/_legacy/independent_paper_review.sh`
- **另計（本來就該指 canonical，遷移時要保留這個語意）**：`scripts/bootstrap_new_host.sh`、`scripts/install_launchd_jobs.sh`、`scripts/backup_user_claude.sh`、`scripts/warm_tcc_authorization.sh`、`scripts/auto_start_codex_loop.sh`、`scripts/cron_git_push_backup.sh`、`scripts/cron_hourly_dispatch.sh`（launchctl-disabled）、`scripts/cron_log_rotate.sh`、`scripts/cron_token_report.sh`、`scripts/cron_backfill_work_log_from_commits.sh`

> 這 44 個是遷移成本的主體，但**不是最難的部分**：它們是 daemon 入口，設計上就該跑在 canonical root（見 §2.5「這些不遷移」）。真正的成本在 1.3 / 1.5。

### 1.3 B 類 —— Python：硬編碼 canonical 路徑字面值（7 個 live）

`scripts/_claude_project_dir.py`｜`scripts/check_alerts.py`｜`scripts/telegram_memory.py`｜`scripts/article_figures/hf_microstructure_publish_2026_04_18.py`｜`scripts/experiments/spy_gld_correlation.py`｜`scripts/experiments/xgboost_shap_vol.py`｜`src/volpred/publisher/prepublish_audit.py`

（`_legacy/` 內另有 19 個；`tests/`、`scripts/tests/` 內另有 6 個，屬 fixture，不算遷移面。）

### 1.4 C 類 —— 明確 assert「我在 canonical main checkout」（14 個呼叫點 / 8 個模組）

`require_canonical_main_checkout` 定義於 `src/volpred/ops/git_writer_lock.py:147`，呼叫點：

| 檔案 | 行 |
|---|---|
| `scripts/reap_orphan_deliverables.py` | 81, 216 |
| `scripts/dispatch_supervisor/phase_z.py` | 79, 3274 |
| `scripts/git_writer_lock.py`（shim） | 42, 124 |
| `src/volpred/ops/rollback.py` | 17, 268 |
| `src/volpred/ops/scheduled_writer_commit.py` | 35, 234 |
| `src/volpred/ops/foreign_disposition.py` | 50, 221 |
| `scripts/tests/test_git_writer_lock.py` | 549（gate，非 runtime） |

**這 6 個 runtime 模組是 fail-closed 邊界，不是 bug** —— 它們刻意拒絕在 worktree 內執行。遷移時它們必須**留在 canonical**，由 integrator 呼叫，不能跟著 producer 進 worktree。

### 1.5 D 類 —— 共享狀態的多寫者面（真正的難點）

| 面 | 實測規模 |
|---|---:|
| 引用 `storage/next_tasks.json` 或 `append_task_record` 的 live 模組 | **73** |
| 使用 `volpred.ops.common.project_path()`（= 一律解析回 canonical root）的模組 | **28**（26 個在 `src/volpred/ops/`） |
| 引用 `git_writer_lock` 的檔案 | **28** |
| 走 `scheduled_writer_commit` 自 commit 的腳本 | **7**（`daily_update` `collect_us_data` `populate_upcoming_events` `detect_market_closure` `refresh_paper_snapshots` `drain_failed_supabase_syncs` + `src/volpred/ops/papers.py`） |
| `config/scheduled_writer_ownership.json` 宣告的 job | **47** |
| 已安裝的 launchd plist | **20**（`~/Library/LaunchAgents/com.volpred.*`） |

`project_path()` 是最關鍵的單點：**28 個模組透過它把所有讀寫綁回 canonical root**。這既是遷移的槓桿（改一個函式的解析規則，28 個模組同時跟著走），也是最大的風險（改錯 = 28 個模組同時寫錯地方）。

### 1.6 E 類 —— 現存 worktree 基礎設施（會與 D4 衝突或需整併）

| 檔案 | 行數 | 角色 |
|---|---:|---|
| `scripts/merge_worktree.sh` | 1,036 | 唯一 landing door（K1032/K1143/K1262/K1618 防線） |
| `scripts/dispatch_supervisor/workspace.py` | 709 | WS-B allocator + finalizer（**已上線，即 §0 的自鎖來源**） |
| `scripts/worktree_gc.py` | 489 | 列舉 `.claude/worktrees` 下所有 linked worktree |
| `scripts/reclaim_stale_worktrees.py` | 414 | 回收陳舊 worktree |
| `src/volpred/ops/git_writer_lock.py` | 522 | 全域 git 序列化鎖 + canonical 判定 |
| `src/volpred/ops/foreign_incident.py` | 593 | D3 incident / quarantine ref |
| `src/volpred/ops/foreign_disposition.py` | 336 | D2 quarantine checkpoint |
| `scripts/dispatch_supervisor/phase_z.py` | 3,427 | 現行 shared-main ownership 推理（要被降級的那個） |

另有 5 處以 regex 解析 `.claude/worktrees/<name>` 反推狀態：`liveness_reconcile.py:88`、`reap_orphan_deliverables.py:285`、`daily_checkup.py:817`、`dispatch_slot_budget.py:32`、`src/volpred/ops/alerts.py:1741`。這些**都是從路徑字串猜語意**，D4 完成後應改讀 workspace receipt，但**不在本輪範圍**（見 §6）。

### 1.7 磁碟實測

| 項目 | 實測 |
|---|---:|
| repo 總計 | 20 GB |
| `.git` | 2.9 GB |
| canonical `.venv` | 1.4 GB |
| `experiments/` | 1.6 GB |
| `frontend-v2-fix/`（獨立 nested repo，含 `node_modules`） | 979 MB |
| `data/` | 968 MB |
| `storage/` | 802 MB |
| `paper/` | 70 MB |
| 現存 4 棵 worktree | 3.0 / 3.1 / 1.7 / 3.0 GB，**合計 11 GB** |
| uv 全域 cache（`~/.cache/uv`） | 8.5 GB |
| 檔案系統 | 926 GiB 總量、**88 GiB 可用**、91% used |

---

## 2. Worktree lifecycle 設計

### 2.1 誰建

**Supervisor 在 worker spawn 之前建，agent 永遠不自己建。** 這一點 WS-B 已經定案且已實作（`workspace.py`）；本文不改它，只補強兩個實測缺口：

- allocator 必須寫 `allocated` receipt（含 `wall_start/wall_end`、`du` bytes、base SHA）。目前 0 筆，導致 §4 的時間估計無法用實測校準。
- worker 的 process `cwd` 必須**機械上**指向 worktree，且要有測試斷言（WS-B §2 已指出 `worker.py::_spawn` 未指定 cwd 是 prose 約定）。

### 2.2 命名規則

沿用現行且已被 5 處 regex 依賴的格式，**不改**：

```
.claude/worktrees/dispatch-slot-<N>-<job8>[-<slug>]
branch: wt/dispatch-slot-<N>-<job8>[-<slug>]
```

`_JOB8_RE = ^dispatch-slot-\d+-([0-9a-f]{8})$`（`workspace.py:93`）目前**不接受 `-<slug>` 尾綴**，但實測 17 個 workspace **全部有 slug**（`-k1731`、`-snapdup`…）。這是一個待驗的實作缺口：若 `_JOB8_RE` 是 orphan 判定的入口，slug 會讓每個 workspace 都匹配失敗 → 被判 orphan → 這正好解釋 §0 的「578/578 全部 `orphaned`」。**落地段 S0 的第一件事就是驗證這條假設**（本文不改碼，只指出方向）。

> 注意：這是「修一個正則」，不是「新增一個 recognizer」。差別在於它不是用來**猜作者**，而是用來認回 allocator 自己剛剛寫下的名字 —— provenance 來自 allocator 的 receipt，正則只是索引。

### 2.3 誰銷 / 孤兒回收

三個 terminal 狀態，**全部由 receipt 驅動，不由目錄掃描驅動**：

| 狀態 | 條件 | 動作 |
|---|---|---|
| `integrated` | main 已含 branch 的每個 declared blob | `git worktree remove`（**永不 `--force`**） |
| `quarantined` | gate 紅 / merge conflict / worker 死亡，且 branch 有 unique commit | 保留 branch，移除 worktree 目錄，開 P2 remediation 單 |
| `empty` | branch 無 unique commit 且工作區乾淨 | 直接 remove branch + worktree |

**關鍵修正（相對現行實作）**：現行是「失敗 → 保留 worktree」，因此失敗品佔住 `max_total`。正確的不變式是 **branch 是 durable 載體，worktree 目錄不是**。commit 到 branch 之後 worktree 目錄可以刪 —— bytes 在 ref 裡，不會遺失。這樣 `max_total` 只受 **live** worktree 數限制，不受歷史失敗數限制，§0 的自鎖迴圈就消失了。

### 2.4 與現有工具的關係

| 工具 | 關係 | 理由 |
|---|---|---|
| `scripts/merge_worktree.sh` | **共存，且是唯一 landing door** | 1,036 行的防線是四次事故換來的。不重寫、不繞過。D4 只把「誰呼叫它、在什麼鎖下呼叫」收斂成單一 integrator。 |
| `src/volpred/ops/git_writer_lock.py` | **共存，範圍縮小** | 目前每個 repo mutation 都排隊。D4 之後 producer 在自己的 worktree 寫，不需要全域鎖；鎖只保護 **integrator 的 merge 臨界區**（§4 顯示這是延遲能否成立的關鍵）。 |
| `scripts/reclaim_stale_worktrees.py` | **降級為 backstop** | 它是 cleanup-layer 推理（掃目錄、看 mtime）。D4 之後正常路徑由 receipt 驅動，reclaim 只處理「receipt 都不存在」的殘骸，並且**只報告不刪除**。 |
| `scripts/worktree_gc.py` | **保留為列舉工具** | 它只列舉不判斷，是 receipt 的對帳來源（列舉 ≠ 歸因）。 |
| `scripts/dispatch_supervisor/phase_z.py` | **保留為 fallback，直到覆蓋率達標** | WS-B §9 Phase 4 的條件不變：所有 automated repo-byte writer 連續觀測期零 direct-main write 之後，才准把 baseline 猜測降級。**pilot 階段不得提前宣稱根治。** |

---

## 3. 依賴與 cache 成本

### 3.1 `.venv`：不要每棵一份，但實測數字會騙人

實測 `du` 顯示每棵 worktree 的 `.venv` 約 1.4 GB。**但 `du` 在這裡高估邊際成本**：`uv` 預設把套件從全域 cache（`~/.cache/uv`，實測 8.5 GB）**hardlink** 進 venv，多次獨立 `du` 會把同一份 inode 重複計算。真實邊際 bytes 遠低於 1.4 GB，但**無法從現有資料推出確切值**（需要 `du -sh --count-links` 或 `find -links +1` 對照才知道）。

**設計決定：per-worktree `.venv` 一律不建。** worker env 以 `VIRTUAL_ENV` / `PATH` 指向 canonical `.venv`，唯讀使用。理由不是省磁碟（省不了多少），而是：

- WS-B §4.5 已把「dependency manifest 變更」列為獨立高風險 class，pilot 明確不得自行 sync 共享 env。既然 pilot 不改依賴，就沒有理由給它一份自己的 env。
- 一份 env = 一個版本事實。多份 env 會讓「gate 在哪個 env 下綠的」變成新的不可歸因問題 —— 那是同一個 class bug 換一個維度復發。
- 例外：任務宣告 `dependency_change=true` 時才建隔離 env，並且該任務**不得**與其他任務並行整合。

### 3.2 `__pycache__`

必須設 `PYTHONPYCACHEPREFIX` 指向 worktree 外的 per-workspace 暫存目錄。否則兩個問題：worktree 內產生 untracked `.pyc`（污染 finalizer 的 declared-path 檢查），以及共用 canonical `.venv` 時 site-packages 的 pyc 寫入權競爭。`.gitignore:2` 已忽略 `__pycache__/`，所以這是執行面問題不是版本面問題。

### 3.3 `node_modules`

**不在範圍。** 唯一的 `node_modules` 在 `frontend-v2-fix/`（979 MB），而它是**獨立 nested repo** —— parent-repo 的 `git worktree add` 根本不會 checkout 它的內容，parent worktree 也隔離不了它。WS-B §3 已明確把它排除在首波之外，本文維持。

### 3.4 磁碟量級估計

估法：每棵 worktree = tracked 內容（`experiments` 1.6G + `data` 968M + `storage` 802M + `paper` 70M + 程式碼 ≈ **3.4 GB**）+ 執行期暫存，扣掉不建 `.venv` 的 1.4 GB。實測現存 4 棵為 1.7–3.1 GB（含 `.venv`），與此一致。

| 情境 | worktree 數 | 磁碟 |
|---|---:|---:|
| 現行 pilot（cap 3） | 3 | ~10 GB |
| `max_slots=4` 全隔離 + 1 個 integrator checkout | 5 | **~17 GB** |
| 上述 + 8 個 quarantine 保留 | 13 | ~44 GB |
| 採 §2.3「quarantine 只留 branch 不留目錄」 | 5 | **~17 GB（與並行度無關）** |

可用空間 88 GiB、`disk_floor_gib=20` ⇒ 可用預算 68 GiB。**§2.3 的修正把磁碟從「隨失敗數線性成長」變成「隨並行度有界」**，這是這一節唯一真正重要的結論。

### 3.5 時間量級估計（**推導值，非實測**）

現有 receipt 沒有任何 `allocated` 事件，所以下列是純推導，估法逐項列出，落地後必須用真實 receipt 取代：

| 步驟 | 估計 | 估法 |
|---|---:|---|
| `git worktree add`（3.4 GB tracked） | **30–120 s** | 3.4 GB ÷ APFS 實務寫入 30–100 MB/s（git 是小檔隨機寫，非序列吞吐）+ index 建立 |
| env 準備 | **~0 s** | §3.1 決定不建 venv |
| gate（pytest 子集） | **60–600 s** | `_TEST_GATE_TIMEOUT_S = 600` 是硬上限；實際取決於 `_resolve_test_targets` 選中的檔數 |
| merge（`merge_worktree.sh`） | **10–60 s** | `_MERGE_TIMEOUT_S = 900` 是上限；正常三方合併是秒級 |

參照：`_GIT_TIMEOUT_S = 300`（`workspace.py:79`，註解寫「worktree add checks out the full tree (multi-GB)」），與 30–120 s 的估計相容。

---

## 4. 整合延遲：序列化 integrator 會不會成為瓶頸

### 4.1 負載實測

| 量 | 實測 |
|---|---:|
| 近 3 日 fire 數（`dispatch_state.completions`） | 07-19: 17、07-20: 54、07-21: 29 |
| fire duration（n=100） | median **676 s**、p90 **1,554 s**、max **2,327 s** |
| `max_slots` | 4 |
| 隔離 `active_cap` / `max_total` | 1 / 3 |

取尖峰日 λ = 54/day = **2.25 fire/hr**（保守：假設每個 fire 都產出 repo bytes 且都要整合）。

### 4.2 M/M/1 佇列估算

以 `Wq = ρS/(1−ρ)`、`ρ = λS`：

| 序列化臨界區包含什麼 | 服務時間 S | ρ | 平均等待 Wq |
|---|---:|---:|---:|
| **只有 merge**（gate 在鎖外） | 60 s | **3.8%** | **≈ 2 s** |
| gate + merge，gate 快 | 300 s | 19% | ≈ 70 s |
| gate + merge，gate 中等 | 400 s | 25% | ≈ 133 s |
| gate + merge，gate 打到上限 | 1,500 s | **94%** | **發散（不穩定）** |

### 4.3 結論（本節的設計約束）

**序列化 integrator 本身不是瓶頸 —— 只要 gate 不在鎖裡。** 這不是調參偏好，是穩定性條件：把 600 s 的 gate 上限放進臨界區，尖峰日 ρ 逼近 1，佇列理論上不收斂。

因此 landing protocol 必須切成兩段：

1. **鎖外**：在 workspace 自己的 checkout 跑 gate，產出綁 `head_sha` 的 gate receipt。可完全並行。
2. **鎖內（`git_writer_lock`）**：重讀 main HEAD → 驗 receipt 未過期（`head_sha` 相符、main 未前進超過允許範圍）→ 三方 candidate → CAS 採納。目標 < 60 s。

代價：main 在 gate 期間前進 ⇒ receipt 失效 ⇒ 需要 re-gate。以 ρ_merge ≈ 3.8% 計，衝突機率低；但**必須真的 re-gate，不得沿用舊 PASS**（WS-B §6.4 已定此規則）。

### 4.4 突發流量

尖峰不是均勻的：`max_slots=4` 且 median duration 676 s，最壞情況是 4 個 fire 在 ~10 分鐘內同時完成。若鎖內 S=60 s，第 4 個等待 180 s —— 可接受。若鎖內 S=400 s，等待 1,200 s（20 分鐘），超過 median fire 本身的時長。**再次指向同一個結論：gate 必須在鎖外。**

---

## 5. 分段落地計畫

原則：每段小到能獨立入池當一張任務；每段有明確回退點（優先是 config flag，不是 revert）；每段結束時系統處於一個**可陳述的**可用狀態。

### S0 — 讓現行 pilot 跑完一次（**先決條件，不做這段後面全部無意義**）

- **做**：診斷 §0 的 `orphaned` 全失敗（優先驗證 §2.2 的 `_JOB8_RE` slug 假設）；讓 finalize 冪等（terminal 之後不再重掃）；補 `allocated` receipt 的真實計時與 disk delta。
- **不做**：不改 landing、不改 lane、不動 PHASE-Z。
- **回退點**：`writer_isolation.mode = "off"`（config 每 tick 熱重載，無需重啟）。
- **完成後狀態**：至少 1 個 fire 走完 allocate → gate → merge → main，且 receipt 可從 task id 追到 commit SHA。§3.5 的推導值被實測取代。**在此之前，「producer-scoped workspace 可行」沒有任何證據。**

### S1 — 解除自鎖：quarantine 只留 branch，不留目錄

- **做**：實作 §2.3 的三個 terminal 狀態；失敗品 commit 到 branch 後移除 worktree 目錄；`max_total` 只計 live workspace。修 remediation 的 `throttled / created:false`（單必須真的開，否則 no-deadlock 保證是空話）。
- **回退點**：`max_total` 調回 3 並停止移除（純加法，舊行為仍在）。
- **完成後狀態**：磁碟從「隨失敗數線性成長」變成「隨並行度有界」（§3.4）；`allocation_skipped: total_cap` 歸零。

### S2 — 把 gate 移出鎖，landing 收斂成單一 integrator

- **做**：實作 §4.3 的兩段式；gate 在 workspace 內並行跑，鎖內只做「驗 receipt + 三方 candidate + CAS」；`merge_worktree.sh` 維持唯一 landing door。
- **回退點**：整合改回手動（WS-B Phase 1 的 manual landing），worktree 與 branch 全保留。
- **完成後狀態**：整合延遲有實測 p50/p95；ρ 可驗證是否落在 §4.2 的預期區間。若實測 ρ > 50%，**停在這裡**，回到 §4 重估，不要往下走。

### S3 — cwd 綁定的機械證明

- **做**：`worker.py::_spawn` 明確指定 `cwd=workspace`；加測試斷言「isolated lane 的 worker process cwd 不是 canonical root」。
- **回退點**：拿掉 cwd 參數（回到繼承 supervisor cwd）。
- **完成後狀態**：「fire 在 worktree 裡寫」從 prompt 約定升級為 execution boundary。**這是 D4 的語意核心**：在此之前所有隔離都只是禮貌性的。

### S4 — canonical root 的單一解析點

- **做**：讓 `project_path()`（§1.5，28 個模組的槓桿）成為唯一的 root 解析入口，且在 worktree 內執行時對 canonical-only 路徑 fail closed（沿用 §1.4 那 6 個模組已有的 `require_canonical_main_checkout` 語意，不新增判斷邏輯）。§1.3 的 7 個硬編碼 py 改走它。
- **回退點**：`project_path()` 恢復無條件回傳 canonical root（單函式 revert）。
- **完成後狀態**：worktree 內誤寫 canonical state 從「靜默成功」變成「明確拋錯」。
- **風險**：28 個模組同時受影響，是全計畫最高風險的一段。**必須單獨成一張任務，不與任何其他段合併。**

### S5 — daemon 狀態離開版本化檔

- **做**：`storage/next_tasks.json`（73 個引用點，§1.5）與 `storage/ops/**` 的多寫者改走單一 writer API。這是外部審查「daemon 狀態改走單一 writer API/DB」那一句。
- **回退點**：API 之下仍是同一個 JSON 檔 + 現行 fcntl 鎖，因此可隨時把呼叫改回直接讀寫。
- **完成後狀態**：daemon churn 不再出現在 main 的 dirty set，PHASE-Z 的 `_MACHINE_STATE_PREFIXES` 分支不再被觸發。
- **註**：這一段**可以跟 S1–S4 並行**（它處理的是 machine state，不是 repo patch），但**不能省** —— §1.5 那 73 個引用點是共享 checkout 上並行寫入的最大單一來源。

### S6 — 擴大覆蓋：governance lane、Codex session、interactive session

- **做**：`writer_isolation.lanes` 加 `governance`（config 改一欄）；Codex hourly peer 走同 contract。
- **回退點**：`lanes` 改回 `["platform_ops"]`。
- **完成後狀態**：WS-B Phase 3/4 的入口。
- **interactive session 需老闆決定**：把互動 session 也趕進 worktree 會改變老闆自己的工作目錄語意。**本文不替他決定**，只指出：只要互動 session 還直接寫 main，D4 就只能宣稱「automated writer 的 ownership 由隔離產生」，不能宣稱共享 checkout 的問題結構上消失了。

### S7 — PHASE-Z 降級（**最後，且需通過 acceptance gate**）

沿用 WS-B §10 的 gate（≥20 個 pilot task、0 foreign-path commit、0 lost unique commit、0 force removal、0 stash、連續 7 天無 authorship alert）。**在此之前 `owned = dirty_now - baseline` 全程保留** —— 拆掉安全網比留著錯誤的安全網更糟。

---

## 6. 明確的非目標

| 不做 | 為什麼 |
|---|---|
| **不新增任何 recognizer / namespace / 收編條件** | D1。這個 class 已經失敗 6+ 次，`test_phase_z_ownership_class_gate.py` 會擋。本文從頭到尾沒有一句「判斷這個檔屬不屬於本班」—— ownership 一律是 `task_id + workspace ref + parent SHA`，由 allocator 在執行前寫下，不由任何人事後推理。 |
| **不重寫 `merge_worktree.sh`** | 1,036 行是 K1032/K1143/K1262/K1618 四次事故換來的。重寫等於把防線清零換一個更乾淨的 API。 |
| **不拆 `phase_z.py`（3,427 行）** | 它現在是 fallback。在 S0–S2 證明隔離 lane 真的能整合之前動它，等於同時拆掉舊網和沒鋪好新網。 |
| **不做 sparse checkout / partial clone** | §3.4 顯示採 §2.3 後磁碟只需 ~17 GB，可用 68 GiB。省磁碟的複雜度現在買不到東西，而 sparse config 會污染整個 repo（WS-B §8 已記此風險）。 |
| **不隔離 `frontend-v2-fix/`** | 獨立 nested repo，parent worktree 在機制上隔離不了它。要做是另一個 repo 的獨立任務。 |
| **不接管 scheduled writer / experiment lane** | 47 個 scheduled job 有自己的 ownership registry（`config/scheduled_writer_ownership.json`），experiment lane 有自己的 certification。兩者都已有明確 owner，不是本 class 的成員。 |
| **不改 §1.7 那 5 處 `.claude/worktrees/<name>` regex 解析** | 它們該改讀 receipt，但那是 S0–S2 有 receipt 之後的事。現在改 = 在沒有替代資料源時拆掉現有的（雖然粗糙的）觀測。 |
| **不裁決 K1380 那 8 個檔** | D5 明確要求由知道 K1380 現況的人/任務裁決，不由 cleanup layer 猜。 |
| **不在本輪碰互動 session 的 cwd 語意** | 見 S6，需老闆決定。 |

---

## 7. 自檢：本設計有沒有偷渡第 7 次同 class 修復？

逐項對照外部審查 §4 點名的四種失敗形態：

| 失敗形態 | 本文是否觸犯 |
|---|---|
| 用目錄 / suffix / mtime / receipt / 測試變綠反推 producer identity | **否**。ownership 來自 allocator 在 spawn **之前**寫下的 `task_id + workspace ref + base SHA`，是宣告不是推論。§2.2 的正則只用來認回 allocator 自己寫的名字。 |
| 把新 orphan 類別加進 recognizer / registry / bucket | **否**。`orphan_namespaces.json` 一個字都不動；§2.3 的三個 terminal 狀態由 receipt 決定，不由檔案特徵決定。 |
| 把 liveness 委託給 best-effort consumer | **否**。§2.3 把 durable 載體從「worktree 目錄」改成「git branch」—— ref 的存在不依賴任何 consumer 有沒有跑。 |
| 測試只證明已知樣本有出口 | **部分風險仍在**。§5 每段有回退點，但「任何 writer crash / 同 path 並行 / pre-dirty 再修改 / 未知檔案類型，都在有限班數內必達 terminal state」**尚未被證明**。WS-B §9 Phase 2 的 E2E 清單（兩 slot 同時改不同路徑、同路徑 conflict、main dirty target、CAS lost、gate receipt stale、worker crash、restart orphan）是該證明的最低集合，**必須在 S2 完成前補上**。 |

---

## 8. 最大的未解風險

**不是磁碟、不是延遲、不是 44 個 cron wrapper。是「隔離 lane 從未成功整合過一次」。**

§0 的實測是：17 個 workspace、578 次 finalize、**0 次 merge**、100% 判為 orphan、remediation 單一張都沒開。這個設計（以及 WS-B 那份）的每一個成本估計、每一條 landing protocol、每一個 acceptance gate，都預設 happy path 至少走通過一次 —— **而現有證據顯示它沒有**。

在 S0 產出第一筆真實的 allocate → gate → merge receipt 之前，本文 §3.5 的時間、§4 的佇列、§5 的排序，**全部是紙上推導**。這一點必須誠實寫進任何引用本文的驗收裡，理由和外部審查 §4 點名的第四種失敗完全相同：**綠色的測試與完整的設計文件都不是「它會在生產環境達到 terminal state」的證據。**

次高風險是 S4：`project_path()` 一個函式牽動 28 個模組，改錯的失敗模式是「28 個模組同時把資料寫到錯的 root」，而且很可能靜默。它必須單獨一張任務、單獨一次回退點。

---

**相關**：`docs/dispatch-writer-isolation-design.md`（WS-B contract / cutover 母文件）｜`docs/governance/2026-07/phase_z_ownership_external_review.md`（D1–D5 裁決）｜`docs/governance/2026-07/git_single_writer_transaction.md`｜`docs/error_log.md` §B｜`scripts/tests/test_phase_z_ownership_class_gate.py`（D1 機械 gate）
