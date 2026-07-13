# 排程 writer Git ownership class sweep

**日期**：2026-07-13  
**觸發**：同類第 3 例（`refresh_paper_snapshots`、lazypack、`populate_upcoming_events`）後的全母體回溯  
**機械 policy**：`config/scheduled_writer_ownership.json`  
**唯一 enforcement owner**：`scripts/tests/test_scheduled_writer_commit_policy.py`

## 結論

排程 writer 的問題不是三個孤立 instance，而是沒有一份「job → tracked output → Git owner」的完整契約。
本次以 `config/runtime_schedules.json` 為母體，逐一追到實際 writer，再用 `git ls-files` 核對主 repo 與
active frontend nested repo。母體共 **79 筆**：40 個 system crontab job、3 個 cron job、1 個 daemon、
2 個 remote trigger、9 個 session cron、24 個 event job；另核對 **19 個**本機 `com.volpred.*`
LaunchAgent。

44 個直接 process 的最終分類為：10 個 `self_commit`、17 個 `phase_z_machine_state`、12 個
`no_repo_tracked_output`、3 個 delegated delivery、1 個 deprecated、1 個 tracked-content invariant。
新增任何 process、session 或 event ID 而未分類，ratchet 都會失敗。

## 稽核方法與邊界

1. 對 `system_crontab.items`、`cron_jobs`、`daemons` 做 exact-set census，不以 enabled 狀態縮小母體。
2. 對 `remote_triggers.items`、`session_crons.items`、`event_jobs.items` 分別保存 exact ID set；它們雖非
   固定 OS process，仍逐筆指定 machine-state 或 agent-delivery owner。
3. 追 wrapper 到 Python/CLI 的實際寫入點；條件性 failure path 也算，例如
   `storage/.failed_supabase_syncs.json`。
4. 以 `git ls-files` 判斷 tracked，而不是只看 `.gitignore`；另在 `frontend-v2-fix` Git root 獨立核對。
5. `self_commit` 必須同時具備：寫入前 staged/unstaged/untracked probe、髒路徑不寫、literal pathspec
   stage、`git commit --only`。PHASE-Z 只可收明確 machine-state namespace/file。

## 44 個直接 process：逐筆結果

| Job | Entrypoint | Git-tracked output | Owner policy |
|---|---|---|---|
| `log_rotate` | `scripts/cron_log_rotate.sh` | 無 | `no_repo_tracked_output` |
| `codex_update` | `scripts/cron_codex_update.sh` | 無 | `no_repo_tracked_output` |
| `arxiv_scan` | `scripts/scan_arxiv_topics.py` | `storage/research/arxiv_candidates.json` | `phase_z_machine_state` |
| `collect_tw_data` | `scripts/collect_tw_data.py` | `data/vixtwn/.vixtwn_daily.lock` | `tracked_content_invariant` |
| `collect_us_data` | `scripts/collect_us_data.py` | `storage/macro/fred_*.csv`（23 檔） | `self_commit` |
| `daily_update` | `scripts/daily_update.py` | paper trading、feed、strategy metrics、feed indices、failed-sync queue、closure config、nested frontend metrics | `self_commit` |
| `daily_update_intraday` | `scripts/daily_update.py` | 同 `daily_update` | `self_commit` |
| `radar_strategy_snapshot` | `scripts/radar_strategy_snapshot_daily.py` | 無（Supabase only） | `no_repo_tracked_output` |
| `release_pool` | `scripts/cron_release_pool.sh` | `storage/reports/feed.json`、條件性 failed-sync queue | `phase_z_machine_state` |
| `market_calendar_sync` | `scripts/cron_market_cal.sh` | 無（market status ignored） | `no_repo_tracked_output` |
| `shared_scheduler_tick` | `scripts/run_scheduler_tick.sh` | scheduler/event ledger、`storage/next_tasks.json` | `phase_z_machine_state` |
| `check_alerts` | `scripts/check_alerts.py` | ops/queue/publication/feed/failed queue、receipt exact outputs | `delegated_delivery_contract` |
| `memory_health_daily` | `scripts/cron_memory_health.sh` | 無 | `no_repo_tracked_output` |
| `dreaming_review` | `scripts/dreaming_review.py` | dreaming state、autonomous decisions、queue | `phase_z_machine_state` |
| `publication_candidates_refresh` | `scripts/build_publication_candidates.py` | `storage/publication_candidates.json` | `phase_z_machine_state` |
| `refresh_paper_snapshots` | `scripts/refresh_paper_snapshots.py` | `paper/*/data/*.csv`（現有 20 檔） | `self_commit` |
| `release_settings_audit` | `scripts/audit_release_settings.py` | 無 | `no_repo_tracked_output` |
| `paper_sync_all` | `src/volpred/ops/papers.py` | nested frontend 的 5 個 mapped public PDF | `self_commit` |
| `populate_events_weekly` | `scripts/populate_upcoming_events.py` | `config/runtime_schedules.json` | `self_commit` |
| `research_backlog_daily` | `scripts/generate_research_backlog.py` | queue、`storage/ops/k_id_registry.json` | `phase_z_machine_state` |
| `digest_daily_enqueue` | `scripts/enqueue_daily_digest.py` | `storage/next_tasks.json` | `phase_z_machine_state` |
| `question_research` | `scripts/cron_question_ops_maintain.sh` | queue、question ops receipts | `phase_z_machine_state` |
| `reader_facing_refill` | `scripts/refill_reader_facing_pool.py` | queue、scan/event state | `phase_z_machine_state` |
| `work_summary_6h` | `scripts/work_summary_6h.py` | 無 | `no_repo_tracked_output` |
| `audit_publish_sync` | `scripts/audit_publish_sync.py` | 無 | `no_repo_tracked_output` |
| `audit_fb_pipeline` | `scripts/audit_fb_pipeline.py` | 條件性 `storage/reports/feed.json` auto-expire | `phase_z_machine_state` |
| `fb_ttl_expire` | `scripts/mark_fb_post_status.py` | `storage/reports/feed.json` | `phase_z_machine_state` |
| `ops_dashboard` | `scripts/ops_dashboard.py` | 無（dashboard snapshot ignored） | `no_repo_tracked_output` |
| `boss_report_4h` | `scripts/boss_report.py` | 無 | `no_repo_tracked_output` |
| `gmail_poll` | `scripts/gmail_inbox_poll.py` | `storage/next_tasks.json` | `phase_z_machine_state` |
| `telegram_poll` | `scripts/telegram_poll.py` | `storage/next_tasks.json` | `phase_z_machine_state` |
| `handoff_regen` | `scripts/generate_handoff.py` | stale cleanup 可改 `storage/next_tasks.json` | `phase_z_machine_state` |
| `supabase_sync_drain` | `scripts/drain_failed_supabase_syncs.py` | `storage/.failed_supabase_syncs.json` | `self_commit` |
| `indicator_arena_daily` | `scripts/indicator_arena_daily.py` | `storage/indicator_arena/**` | `phase_z_machine_state` |
| `codex_work_log_backfill` | `scripts/cron_backfill_work_log_from_commits.sh` | `storage/work_log.json` | `self_commit` |
| `git_push_backup` | `scripts/cron_git_push_backup.sh` | 無（只 push 既有 commit） | `no_repo_tracked_output` |
| `backup_user_claude` | `scripts/backup_user_claude.sh` | `ops/claude_user_backup/**` | `phase_z_machine_state` |
| `token_report_daily` | `scripts/token_report_email.py` | 無；排程 invocation 不含手動 `--calibrate` | `no_repo_tracked_output` |
| `reader_metrics_daily` | `scripts/pull_reader_metrics.py` | `storage/analytics/**` | `phase_z_machine_state` |
| `market_closure_detect` | `scripts/detect_market_closure.py` | `config/market_closures_adhoc.json` | `self_commit` |
| `volpred-hourly-dispatch` | `scripts/cron_hourly_dispatch.sh` | retired；若重啟會是 dynamic agent output | `deprecated` |
| `volpred-compute-worker` | `scripts/compute_queue.py` | compute state + receipt literal `output_paths` | `delegated_delivery_contract` |
| `volpred-fred-backfill-guard` | `scripts/fred_backfill_guard.py` | 同一 `_collect_fred` 的 23 個 CSV | `self_commit` |
| `volpred-dispatch-supervisor` | `scripts/dispatch_supervisor/supervisor.py` | ops state + fire-owned exact paths | `delegated_delivery_contract` |

## 35 個非 process schedule declarations：逐筆結果

### Remote triggers（2）

| ID | 判定 |
|---|---|
| `platform_ops_patrol` | disabled compatibility declaration；不直接執行 writer |
| `token_usage_daily_report` | disabled compatibility declaration；不直接執行 writer |

### Session crons（9）

| ID | 可能的 tracked output | Owner |
|---|---|---|
| `daily_planning` | queue | agent delivery + PHASE-Z machine state |
| `continue_task` | queue、failed-sync queue、dynamic task outputs | agent delivery / receipt owner |
| `platform_patrol` | queue、dynamic remediation | agent delivery / PHASE-Z |
| `git_sync` | 已有作者的 dynamic paths | explicit Git maintainer contract |
| `knowledge_index_check` | `storage/.knowledge_index_state.json` | exact PHASE-Z machine-state file |
| `token_usage_daily` | `storage/reports/token_usage/**` | PHASE-Z namespace |
| `ndc_indicator_refresh` | stale 時才人工更新 `storage/macro/tw_dgbas_bci_m.csv` | reviewed agent delivery |
| `codex_quota_resume_2026_04_24` | queue/work log/dynamic outputs | expired one-shot agent contract |
| `journal_topic_scan` | `research_program.md`、queue | authored agent delivery；禁止 PHASE-Z 代收 |

### Event jobs（24）

每筆先由 materializer 寫 PHASE-Z 所有的 queue/event ledger，後續文章與資產由 content agent 的
delivery contract 所有。以下 ID 均逐筆列入 policy exact set：

| ID | Owner |
|---|---|
| `nfp-2026-06-05-t7` | event delivery contract |
| `nfp-2026-06-05-t2` | event delivery contract |
| `nfp-2026-06-05-t0` | event delivery contract |
| `fomc-2026-06-17-t7` | event delivery contract |
| `fomc-2026-06-17-t2` | event delivery contract |
| `fomc-2026-06-17-t0` | event delivery contract |
| `tsmc-revenue-2026-06-10-t0` | event delivery contract |
| `cpi-us-2026-06-11-t2` | event delivery contract |
| `cpi-us-2026-06-11-t0` | event delivery contract |
| `nfp-2026-07-03-t7` | event delivery contract |
| `nfp-2026-07-03-t2` | event delivery contract |
| `nfp-2026-07-03-t0` | event delivery contract |
| `cpi-us-2026-07-14-t2` | event delivery contract |
| `cpi-us-2026-07-14-t0` | event delivery contract |
| `tsmc-revenue-2026-07-10-t0` | event delivery contract |
| `fomc-2026-07-29-t7` | event delivery contract |
| `fomc-2026-07-29-t2` | event delivery contract |
| `fomc-2026-07-29-t0` | event delivery contract |
| `nfp-2026-08-07-t7` | event delivery contract |
| `nfp-2026-08-07-t2` | event delivery contract |
| `nfp-2026-08-07-t0` | event delivery contract |
| `cpi-us-2026-08-12-t2` | event delivery contract |
| `cpi-us-2026-08-12-t0` | event delivery contract |
| `tsmc-revenue-2026-08-10-t0` | event delivery contract |

## LaunchAgent census（19）

| Label | 對應 job | 狀態 |
|---|---|---|
| `com.volpred.check-alerts` | `check_alerts` | active |
| `com.volpred.collect-tw-data` | `collect_tw_data` | active |
| `com.volpred.collect-us-data` | `collect_us_data` | active |
| `com.volpred.compute-worker` | `volpred-compute-worker` | active |
| `com.volpred.daily-update` | `daily_update` | active |
| `com.volpred.daily-update-intraday` | `daily_update_intraday` | active |
| `com.volpred.dispatch-supervisor` | `volpred-dispatch-supervisor` | active |
| `com.volpred.gmail-poll` | `gmail_poll` | active |
| `com.volpred.handoff-regen` | `handoff_regen` | active |
| `com.volpred.hourly-dispatch` | `volpred-hourly-dispatch` | retired/unloaded |
| `com.volpred.market-calendar-sync` | `market_calendar_sync` | active |
| `com.volpred.market-closure-detect` | `market_closure_detect` | active |
| `com.volpred.memory-health-daily` | `memory_health_daily` | active |
| `com.volpred.reader-facing-refill` | `reader_facing_refill` | active |
| `com.volpred.reader-metrics-daily` | `reader_metrics_daily` | active |
| `com.volpred.release-pool` | `release_pool` | active |
| `com.volpred.telegram-poll` | `telegram_poll` | active |
| `com.volpred.work-summary` | `work_summary_6h` | active |
| `com.volpred.work-dashboard` | host-only interactive dashboard | explicit host-only exception |

## 實際補強

- 新增共用 helper：每個 exact output 先用 `git status --porcelain=v1 --untracked-files=all -- <path>`
  捕捉 staged、unstaged、untracked、deletion；Git probe 失敗也 fail closed。
- 髒路徑在 writer 動手前即被排除；單一 config/queue writer 則整次中止。寫完只 `git add -A -- <paths>`，
  再以 `git commit --only -- <paths>` 提交，不碰 foreign staged work。
- 補齊 FRED、daily update、market closure、failed-sync drain、paper snapshot、event populate、work-log
  與 nested frontend PDF/metrics 的 ownership。daily update 直接呼叫 closure function 的繞路也納入。
- `.failed_supabase_syncs.json` 因 Publisher/release/check-alerts 等多 writer，另列為 exact PHASE-Z machine
  state；`storage/.knowledge_index_state.json` 同理。
- `audit_fb_pipeline` 的 conditional auto-expire 被正確分類為 feed writer；ignored dashboard/handoff/inbox
  state不再誤標成 tracked output。

## 明示盲區與後續風險

1. **雙觸發**：本機 crontab 與 loaded LaunchAgent 同時註冊 collect TW、collect US、release pool、market
   calendar、memory health 五個 job；其中 release pool 時刻還相同。pre-write snapshot 無法消除兩個同 job
   同時看見 clean 的 TOCTOU，應另做 trigger 去重或共用 `flock`，不冒充已由本 sweep 解決。
2. **nested repo 現況**：`frontend-v2-fix` 在本次開工前已有 metrics 與兩個 PDF dirty；本次不認領、不
   偷 commit。新 guard 會跳過這些 exact targets，其他 clean targets仍可更新。
3. **動態 agent output**：session/event 的實際文章路徑在 schedule time 不可知，機械邊界是 receipt
   `output_paths` 與 supervisor pre-fire baseline；policy 只可 ratchet ID 與 owner 類型，不能假裝靜態列完檔名。
4. **wrapper drift**：canonical/live wrapper 一致性仍由既有 `test_cron_wrapper_manifest.py` 單獨所有，
   本 gate 不複製同一 concern。host-only dashboard 也不冒充 runtime config job。
5. `data/vixtwn/.vixtwn_daily.lock` 是 tracked-but-ignored 空 sentinel；目前 byte-empty invariant 可驗，
   但長期更乾淨的處置是解除追蹤。手動 `token_report_email.py --calibrate` 不在排程 invocation 範圍。
6. lazypack/compute producer 不自行 commit；唯一 owner 維持 central reaper，僅依 receipt literal
   `output_paths` collision-check 後 `--only` 提交，避免重新引入雙 owner。

## Gate 證明的事

`scripts/tests/test_scheduled_writer_commit_policy.py` 是唯一讀取 policy 的 enforcement owner。它驗證：

- 44 個 executable、2 個 remote、9 個 session、24 個 event 的 exact-set equality 與新增 negative control；
- 所有 concrete declared output 在正確 Git root 確實 tracked；empty lock 的 byte invariant；
- PHASE-Z exemption 的 probe 真正在 authorship boundary；
- self-commit owner 同時使用 pre-write guard 與 path-scoped commit；
- installed/canonical LaunchAgent label 均有 disposition；
- 暫存 Git repo 中 pre-staged target 不會被覆寫，foreign staged/unstaged work 不會被 sweep。

