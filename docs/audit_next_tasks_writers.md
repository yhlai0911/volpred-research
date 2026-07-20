# Audit — `storage/next_tasks.json` 全量 writer 盤點

- **任務**：`assign_9f769a71`（refactor-master **WS-A1a**），對應 `docs/refactor_plan_ops_master_2026_07.md` §3 WS-A / §1.3 A5
- **日期**：2026-07-20
- **範圍**：全 repo（Python / shell / jq 管線 / `.claude/` prompt-rule-skill 文件）。排除 `.claude/worktrees/**`（活躍 worktree 為 canonical 的暫時副本，非獨立 writer）。
- **性質**：**只盤點、不改碼**。實作收斂是 A1b。

---

## Summary

- **writer 呼叫點總數 = 44**（分佈於 33 個檔案）。與 §1.3 A5「40+ writer」的診斷數量一致。
- **分類分佈**：**legal 25 / needs_helper 12 / delete 7**。
- **Canonical helper（實查確認，非假設）= `src/volpred/ops/next_tasks.py`**，三個入口分工明確：
  - `write_tasks_to_handle(fh, tasks)` — **最低層 mutation primitive**。serialize-first-then-truncate（2026-07-05 截斷事故的修法）、`guard_canonical_write` 護欄、priority/status/blocked_until 三道 audit。read-modify-write 的 caller 應持同一把 `LOCK_EX` handle 呼叫它。
  - `write_tasks_locked(path, tasks)` — 已握有完整 list 的 one-shot writer（自帶 flock；不可在已持鎖的 scope 內呼叫，會 self-deadlock）。
  - `append_next_task(...)` — **單一 append gateway**（2026-07-16 single-gateway refactor）。含 uuid 去重、`_request_urgent_fire` 急件直達 supervisor。`volpred ops assign` 是它的 thin wrapper。
  - 相關但非 writer：`compact_terminal_tasks()`（終態壓縮）、`scripts/task_pool_claim.py`（claim/complete 的**業務層**入口，本身經 `write_tasks_to_handle` 落地）。
- **既有機械護欄**：`src/volpred/canonical_write.py:guard_canonical_write` + ratchet 稽核 `scripts/audit_canonical_writers.py`（`LOW_LEVEL_OWNERS` 計數表）。但兩者只檢查「有沒有呼叫 guard」與「owner 數量有沒有變」，**不檢查有沒有走 helper** —— 這正是 WS-A1 gate 要補的缺口（見文末「A1b 收斂後的 gate 建議」）。
- **交叉驗證**：`grep -rn "next_tasks" --include=*.py --include=*.sh --include=*.md`（去 worktrees）= **1,454 行 / 287 檔**（py 1,050、sh 10、md 394）。本表覆蓋 44 行 / 33 檔。差異已逐項歸因，見文末「交叉驗證差異說明」，**無漏網的寫入路徑**。

---

## 分類判準

| 分類 | 判準 |
|---|---|
| **legal** | 落地時經 `write_tasks_to_handle` / `write_tasks_locked` / `append_next_task`。（僅 import `normalize_task_priorities` 之類的純函式 **不算**走 helper —— 那是欄位正規化，不是寫入路徑。） |
| **needs_helper** | 直寫（`open(...,'w')` / `json.dump` / `write_text` / `tmp+replace` / `jq`+`mv`），但語意合法、有長駐職責，應改走 helper。 |
| **delete** | 死碼、一次性 backfill/pilot、或過時指示；應刪除或移 `_legacy/`。 |

---

## 表格

### A. legal（25）— 已走 canonical helper

| 檔案:行號 | 寫入方式 | 分類 | 建議動作 | 備註 |
|---|---|---|---|---|
| `src/volpred/ops/next_tasks.py:481-508`（`write_tasks_to_handle`） | `fh.seek/truncate/write`（serialize-first） | legal | **不動** — 這是 canonical primitive 本體 | 唯一允許直接碰 fd 的地方；已含 guard + 3 道 audit |
| `src/volpred/ops/next_tasks.py:511-530`（`write_tasks_locked`） | flock + `write_tasks_to_handle` | legal | 不動 | one-shot writer；docstring 已警告 self-deadlock |
| `src/volpred/ops/next_tasks.py:619-679`（`append_next_task`） | flock + `write_tasks_to_handle` | legal | 不動 | single append gateway；內建 `_request_urgent_fire` |
| `scripts/task_pool_claim.py:88,100`（`_locked_load`） | `write_text("[]")` bootstrap + `write_tasks_to_handle` | legal | 不動；A2b 的 kill→re-pend 接線加在此檔 | claim/complete 業務層唯一入口 |
| `scripts/check_alerts.py:683,693`（`_append_next_task_locked`） | bootstrap + `write_tasks_to_handle` | legal | 不動 | alert→task 的 append 路徑 |
| `scripts/check_alerts.py:1257`（`_ci_close_pending_repair_tasks`） | `write_tasks_to_handle` | legal | 不動 | CI red watchdog 收尾 |
| `scripts/continue_task_dispatch.py:489,514,519`（`_materialize_pool_dry_diagnostic_task`） | bootstrap + flock + `write_tasks_to_handle` | legal | 不動（Phase 0 已修 truncate 寫法） | §7 已記錄 A1-hotfix 完成 |
| `scripts/continue_task_dispatch.py:682,713`（`_promote_starved_article_tasks`） | `open(r+)` + flock + `write_tasks_to_handle` | legal | **H4 相關**：此檔降為純 library 時，此寫入路徑移交 supervisor decision pipeline | 見 §3 WS-H H4 |
| `scripts/continue_task_dispatch.py:975`（`_sweep_cleared_dreaming_tasks`） | `write_tasks_to_handle` | legal | 同上，隨 H4 移交 | — |
| `scripts/dreaming_review.py:1438,1485`（`apply_auto_dispatch`） | bootstrap + `write_tasks_to_handle` | legal | 不動 | slow loop 自動開工單 |
| `scripts/backfill_feed_audience.py:362,414`（`reconcile_rewrite_tasks`） | bootstrap + `write_tasks_to_handle` | legal | 不動 | 已在 `audit_canonical_writers` owner 表 |
| `scripts/unblock_expired_blocked_tasks.py:201`（`main`） | `write_tasks_to_handle` | legal | 不動 | blocked 到期釋放 |
| `scripts/migrate_blocked_lane_terminal.py:144`（`_write_tasks`） | `write_tasks_to_handle` | legal | 不動；A3 的 status migration 沿用此檔模式 | 一次性但為 A3 的參考實作，**不刪** |
| `scripts/reap_orphan_deliverables.py:1060`（`_escalate_held`） | `append_next_task` | legal | 不動 | 走 single gateway，急件 fire 自動生效 |
| `src/volpred/cli.py:929`（`ops_assign`） | `append_next_task` | legal | 不動 | `volpred ops assign` = 人為 ingress 唯一入口 |
| `src/volpred/ops/alert_remediation.py:739,758,768,777,787`（`_enqueue`） | bootstrap + `write_tasks_to_handle` ×4 分支 | legal | 不動；A1b 可順手把 4 個分支的 `write_tasks_to_handle` 收成單一出口（純可讀性） | 分支多但都走 helper |
| `src/volpred/ops/alert_remediation.py:1004`（`_sweep_cleared_ordinary_tasks`） | `write_tasks_to_handle` | legal | 不動 | — |
| `src/volpred/ops/content.py:1280,1321,1357`（`_materialize_release_audit_fix_task`） | bootstrap + `write_tasks_to_handle` ×2 | legal | 不動 | release audit 自修任務 |
| `src/volpred/ops/event_jobs.py:496,519,532,542`（`_ensure_next_task`） | `write_tasks_to_handle` ×4 分支 | legal | 不動 | event_article 的 single-owner writer |
| `src/volpred/ops/event_jobs.py:729`（`_suppress_canonical_for_legacy_conflict`） | `write_tasks_to_handle` | legal | 不動 | — |
| `src/volpred/ops/event_jobs.py:889`（`_expire_next_tasks`） | `write_tasks_to_handle` | legal | 不動 | 過期 event 任務下架 |
| `src/volpred/ops/foreign_incident.py:193,220`（`upsert_incident`） | bootstrap + `write_tasks_to_handle` | legal | 不動 | PHASE-Z foreign incident 立案 |
| `src/volpred/ops/foreign_incident.py:241`（`upsert_incident`） | `append_next_task` | legal | 不動 | — |
| `src/volpred/ops/foreign_incident.py:291`（`_supersede_subsumed`） | `write_tasks_to_handle` | legal | 不動 | — |
| `src/volpred/ops/questions.py:847,896`（`ensure_member_qa_task`） | bootstrap + `write_tasks_to_handle` | legal | 不動 | member_qa single owner |

### B. needs_helper（12）— 直寫但語意合法，A1b 應改走 helper

| 檔案:行號 | 寫入方式 | 分類 | 建議動作 | 備註 |
|---|---|---|---|---|
| `scripts/gmail_inbox_poll.py:394,405-406`（`_append_task`） | `write_text("[]")` + `fh.truncate()` + `json.dump(fh)` | needs_helper | **改用 `append_next_task(source="gmail", ...)`**，刪掉本地 bootstrap/truncate/dump 三行；`_trigger_immediate_dispatch`（:757）可一併移除，`append_next_task` 內建 `_request_urgent_fire` 已涵蓋 | **高風險 #2**：truncate-then-dump，序列化失敗會留下半截 JSON（正是 2026-07-05 事故模式）；且自帶第二條急件觸發線（marker 檔），與 single gateway 重複 |
| `scripts/telegram_poll.py:126-127`（`_append_task`） | `tmp.write_text(indent=1)` + `tmp.replace(NEXT_TASKS)` | needs_helper | **改用 `append_next_task(source="telegram", task_family=...)`**；保留 `telegram_reply` 不觸發 urgent fire 的既有語意（`task_urgency.is_urgent` 已對 `DEDICATED_OWNER_TASK_TYPES` 回 False，無需額外處理） | **高風險 #1**：`tmp+replace` **不持 `LOCK_EX`** → 與 claim/dispatch 併發時整檔覆蓋，會吃掉他人剛寫入的 task；且 `indent=1` 與 canonical 的 `indent=2` 不一致，每次寫入製造全檔 diff（污染 PHASE-Z 作者判定與 git 歷史） |
| `scripts/mark_task_blocked.py:122-124`（`_save`） | `tmp.write_text` + `tmp.replace(NEXT_TASKS)` | needs_helper | **改用 `write_tasks_locked(NEXT_TASKS, out)`**（本函式已握有完整 list，正是該 API 的設計用途） | `tmp+replace` 無 flock；且是 host UI daemon 的唯一 repo mutation（見 `config/scheduled_writer_ownership.json:436`），併發面大 |
| `scripts/enqueue_daily_digest.py:159-160`（`_reconcile_stale_digest_task`） | `tmp.write_text` + `tmp.replace` | needs_helper | 改用 `write_tasks_locked` | 無 flock；每日排程 job |
| `scripts/enqueue_daily_digest.py:221-222`（`main`） | `tmp.write_text` + `tmp.replace` | needs_helper | 新增路徑改用 `append_next_task`；若需保留冪等 upsert 語意則用 `write_tasks_locked` | 同上；同檔兩處重複寫法 |
| `scripts/refill_reader_facing_pool.py:93,105-106`（`_append_task`） | bootstrap + `truncate` + `json.dump` | needs_helper | 改用 `append_next_task`；`normalize_task_priorities` import 可移除（helper 內建） | truncate-then-dump；已排程 job（`cron_reader_facing_refill.sh`） |
| `scripts/refill_task_pool.py:95`（`_save_tasks`） | `NEXT_TASKS.write_text(json.dumps(out))` **全檔覆蓋** | needs_helper | 改用 `write_tasks_locked(NEXT_TASKS, out)` | **高風險 #3**：載入時只取 `LOCK_SH`（:71），寫入時**完全無鎖**的全檔覆蓋 → 典型 lost-update；被 `research-topic-discovery` skill 與 `control-plane.md` 明文引用，呼叫頻率高 |
| `scripts/generate_research_backlog.py:108,113-114`（`_save_tasks`） | bootstrap + `truncate` + `json.dump` | needs_helper | 改用 `append_next_task` 逐筆 append（本函式即是 append 語意） | 已排程（`cron_research_backlog.sh` + `runtime_schedules.json`） |
| `scripts/sync_next_tasks_status.py:345-358`（`main`） | 手抄 serialize-first：`json.dumps` → `encode` → `seek/truncate/write` | needs_helper | 改用 `write_tasks_to_handle(fh, tasks)`（已持同一把 `LOCK_EX` handle，直接替換即可） | 這是 canonical 邏輯的**手抄複本**——最容易在 helper 演進時漂移；另注意它支援 `dict` root（`original["tasks"]`）的 legacy 形狀，替換前需確認該分支是否仍有實資料 |
| `scripts/dedupe_next_tasks.py:167-168`（`main`） | `truncate` + `json.dump` | needs_helper | 改用 `write_tasks_to_handle(fh, deduped)` | 已持 `LOCK_EX`，一行替換 |
| `scripts/cron_hourly_dispatch_prompt.md:63-67` | **jq 管線**：`jq ... storage/next_tasks.json > /tmp/nt && mv /tmp/nt storage/next_tasks.json` | needs_helper | **刪除該 jq 範例**，改寫為 `task_pool_claim.py` 子命令（記 plan 到 `task.result`）。若該子命令尚不存在，A1b 需一併新增（例：`task_pool_claim.py set-result --id <id> --plan <text> --subtasks <json>`） | **§3 WS-A1 明文指名項**。`mv` 覆蓋完全繞過 flock 與 status vocab gate，且教的是 **agent**（放大 N 倍）。同檔 :44/:47/:55/:142 的 jq 皆為**唯讀查詢**，不在此列 |
| `.claude/skills/autonomous-research/SKILL.md:464` | 文字指示：終態任務「移到 `storage/next_tasks_archive.jsonl`」，並提及「每次 Edit 都重寫整檔」 | needs_helper | 改寫為指向既有壓縮 helper `next_tasks.compact_terminal_tasks()`（測試：`scripts/tests/test_queue_maintenance_compact.py`），明文禁止 Edit 工具直改佇列 | 現行文字暗示用 Edit 直改 canonical 佇列；歸檔目錄現況為 `storage/next_tasks_archive/`（見 `phase_z.py:218`），與文中 `.jsonl` 檔名不符，一併更正 |

### C. delete（7）— 死碼 / 一次性腳本 / 過時指示

| 檔案:行號 | 寫入方式 | 分類 | 建議動作 | 備註 |
|---|---|---|---|---|
| `experiments/K1387/write_knowledge.py:143,147` | `open(next_tasks_path,"w")` + `json.dump`，**無鎖、無 guard** | delete | **直接刪除整檔**（一次性 K1387 收尾腳本，git 留歷史）。若要保留紀錄則移 `experiments/K1387/_legacy/` | 最裸的寫法：讀完關檔再開 `"w"` 覆蓋，全程無 flock、無 `guard_canonical_write`；`experiments/` 不在 `audit_canonical_writers.py` 掃描範圍（`SKIP_PARTS`）→ **現有護欄完全看不到它** |
| `scripts/decompose_drone_series.py:129-133`（`main`） | flock + 手抄 serialize-first + `truncate/write` | delete | 移 `scripts/_legacy/`（含 provenance 註記） | **零引用**（config / skills / rules / tests 全無）；drone series 一次性拆解腳本，對應 §1.2 P6 與 WS-E E1 的 `drone_ep*` 死碼群 |
| `scripts/graphify_codeonly_pilot.py:212,225-226`（`_ensure_followup_task`） | bootstrap + `truncate` + `json.dump` | delete | 移 `scripts/_legacy/` | **零引用**；名稱與 docstring 皆自述為 pilot（一次性實驗），卻保有一條無 helper 的佇列寫入路徑 |
| `scripts/backfill_null_task_ids.py:110-118`（`main`） | flock + 手抄 serialize-first + `truncate/write` | delete | 移 `scripts/_legacy/`；同 commit 更新 `tests/test_canonical_write_guard.py` 的路徑清單與 `audit_canonical_writers.py:LOW_LEVEL_OWNERS` 計數 | 一次性 backfill（id=null 修補，已完成）；唯一引用是 CI ratchet 測試，非功能依賴 |
| `scripts/backfill_task_types.py:139-140`（`main`） | flock + `truncate` + `json.dump` | delete | 同上（`_legacy/` + 更新 ratchet 兩處） | 一次性 backfill；唯一引用是 `test_canonical_write_guard.py` |
| `scripts/generate_diverse_tasks.py:98`（`_save_tasks`） | `NEXT_TASKS.write_text(json.dumps(out))` **全檔覆蓋、無鎖** | delete | 移 `scripts/_legacy/`；`tests/test_dispatch_type_rotation.py` 與 `tests/test_generate_diverse_tasks.py` 同 commit 處理 | 無排程、無 skill/rule 引用，職責已被 `task_generator_v2` + `refill_task_pool` 覆蓋；留著就是一條無鎖全檔覆蓋的活路徑 |
| `scripts/task_generator_v2.py:849-850`（`main`） | `open(NEXT_TASKS,"w")` + `json.dump`，**無 flock** | delete | 移 `scripts/_legacy/`（**A1b 執行前先向主線程確認**：H4 的 decision pipeline 是否要收編其 5 來源候選計算邏輯；若要，則先把候選計算抽成 library 再刪寫入路徑） | 無排程、無 skill/rule 引用，只有測試引用；寫入方式是全表最危險的一種（`"w"` 直開 + 無鎖 + 全檔 `combined` 覆蓋）。因與 H4 有潛在交集，是本表**唯一需要人工裁決**的 delete 項 |

---

## A1b 收斂後的 gate 建議（對應 §3 WS-A A1 驗證欄）

A1b 完成後，新增 audit 掛進既有 pre-push audit runner（單一 owner，不新開一層）：

1. **靜態 AST 規則**：在 `src/volpred/`、`src/api/`、`scripts/`（排除 `_legacy/`、`tests/`）中，任何解析到 `storage/next_tasks.json` 的路徑物件，其 `open(mode含 w/a/+)` / `write_text` / `json.dump` / `os.replace` / `Path.replace` 呼叫必須落在 `src/volpred/ops/next_tasks.py` 內，否則 FAIL。
2. **文字規則**：`.claude/**` 與 `scripts/*.md` 中，若同一行同時出現 `next_tasks.json` 與（`jq` 且 `>` / `mv` / `tee` / `sponge`）則 FAIL。
3. **擴掃 `experiments/`**：`audit_canonical_writers.py` 的 `SKIP_PARTS` 目前含 `experiments`，導致 K1387 這類 writer 隱形。至少對 `storage/next_tasks.json` 這一個目標取消該豁免。

---

## 交叉驗證差異說明

原始 `grep -rn "next_tasks" --include=*.py --include=*.sh --include=*.md`（去 `.claude/worktrees/**`）= **1,454 行 / 287 檔**；本表覆蓋 **44 行 / 33 檔**。差額 1,410 行逐類歸因如下，**均非寫入路徑**：

| 類別 | 約略行數 | 說明 |
|---|---|---|
| 測試 fixture 寫入（`tests/**`、`scripts/tests/**`） | ~430 | 寫的是 `tmp_path` 下的臨時佇列，非 canonical。`VOLPRED_NO_CANONICAL_WRITE` + `guard_canonical_write` 已機械保證，刻意不列入收斂清單 |
| 文件/計畫/skill/rule 的**敘述性提及** | ~390 | `docs/**`、`.claude/rules/**`、`.claude/skills/**`、`AGENTS.md`、`research_program.md`、`paper/**`、`experiments/**/README.md`。已逐一過濾「教人直接改檔」的指示，僅 2 處命中（B 表 N11/N12） |
| **唯讀** 讀取與查詢 | ~340 | `json.load` / `LOCK_SH` 載入 / `jq` 查詢（如 `.claude/hooks/email_pool_reminder.sh:14,25`、`scripts/telegram_responder.sh:100`、`cron_hourly_dispatch_prompt.md:44,47,55`）。`telegram_responder.sh:91-92` 的 prompt 已明文「禁止直接 append JSON、一律走 `task_pool_claim.py`」，屬**正面範例** |
| 路徑常數 / import / 型別宣告 | ~130 | `NEXT_TASKS = ROOT / "storage" / "next_tasks.json"`、`from volpred.ops.next_tasks import ...`、CLI `--next-tasks` 參數 |
| config 宣告（`scheduled_writer_ownership.json` / `runtime_schedules.json` 的 `tracked_outputs`、`phase_z_probe_paths`） | ~60 | 治理宣告，非執行寫入。**但可作 A1b 的反查校驗**：宣告 `tracked_outputs` 含 `next_tasks.json` 的 job 都應對應到本表某個 writer |
| 註解 / docstring / error_log 事故敘述 | ~60 | 如 `phase_z.py:166-246`、`cli.py` docstring |

**結論**：無漏網寫入路徑。唯一「grep 掃不到」的殘餘風險是 agent 在 dispatch 期間即興用 Edit/Bash 直改佇列 —— 該面向由 PHASE-Z（WS-B execution isolation）與上列 gate 規則 2 覆蓋，不屬本表範圍。

---

## A1b 執行後記（2026-07-20，worktree agent-aae0802fcba9f05f7）

收斂已落地；本表以下判定在實作時被**證據推翻或細化**（均已在 code comment 標注）：

| 原判定 | 實作裁決 | 證據 |
|---|---|---|
| N1 gmail：`_trigger_immediate_dispatch` 可移除，`append_next_task` 內建 `_request_urgent_fire` 已涵蓋 | **保留** `_trigger_immediate_dispatch`，只換寫入原語 | `email_reply` ∈ `DEDICATED_OWNER_TASK_TYPES`，`task_urgency.is_urgent()` 一律回 False（`classify()` 對 dedicated-owner 直接歸 scheduled）— 移除即斷 email 即時派工；task_urgency docstring 明文「各自的 ingest 已經有自己的即時路徑」 |
| D4 `backfill_null_task_ids.py` delete（「唯一引用是 CI ratchet 測試」） | **改列 needs_helper**：換 `write_tasks_to_handle`，檔案保留 | `scripts/daily_checkup.py:408` 以它為 null-id finding 的 recovery 命令（live 功能引用） |
| D6 `generate_diverse_tasks.py` delete（「無排程、無 skill/rule 引用」） | **改列 needs_helper**：`_save_tasks` 換 `write_tasks_locked`，檔案保留 | `continue_task_dispatch.py:841` `_maybe_refill` 每輪 refill live 呼叫 `generate(dry_run=False)` → `_save_tasks` |
| D7 `task_generator_v2.py` 移 `_legacy/`（待人工裁決 H4 交集） | **保留檔案、只移除寫入路徑**（`--commit` 分支整段刪除，計算邏輯與 dry-run/JSON 報表留給 H4） | 貼合 A1b brief「移除該寫入路徑（保留讀取邏輯）」，H4 收編候選計算不受影響 |
| D1 K1387 `write_knowledge.py` 刪除整檔 | **檔案不動**，凍結為 gate baseline（`NEXT_TASKS_EXPERIMENT_BASELINE`，only-shrink ratchet） | 比照 `scripts/tests/test_work_log_writer_gate.py::BASELINE` 先例：「experiment artifacts are evidence, not live code」（research-honesty）+ memory `feedback_no_research_artifact_loss`；gate 已取消 experiments/ 豁免，該檔不再隱形 |
| legal 表 `continue_task_dispatch:_materialize_pool_dry_diagnostic_task`「不動」 | legacy-dict 分支的手抄 serialize-first 複本改為 **loud reject**（list 分支本就走 helper） | 兩份 live queue 實測 list-root；dict 手抄複本正是 §N9 指出的 drift 形狀 |

Gate 落地（收編進 `scripts/audit_canonical_writers.py`，單一 owner）：`NEXT-TASKS-ROUTING` 檢查
= 文末三條建議全數實作（AST helper-routing + 文字規則 + experiments 掃描）。
Break-then-verify：pre-A1b tree **57 violations**、收斂後 **0**；模擬新增
`experiments/K9999/write_knowledge.py` 被咬、K1387 baseline 正確凍結。
新增 canonical helper：`next_tasks.append_task_record()`（record-preserving append gateway；
`append_next_task` 收斂為其 caller）；新增 `task_pool_claim.py annotate` 子命令取代
cron prompt 的 jq+mv 指示。
