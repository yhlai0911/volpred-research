# VolPred 流程審計報告 — 2026-06-10

**審計時間**：2026-06-10 17:00–17:55（台灣時間）
**性質**：read-only 流程審計（攻擊者思維找繞過路徑 / silent failure / dual source of truth）
**範圍**：任務池派工、實驗、發佈、排程、Email、FB 雙發佈、論文、Memory 共 8 條流程
**排除**：已知且已修項目（arc-dedup 三層重構、image-URL gate、Gmail BODY.PEEK、host_cron_fail audit_* exclusion、stale_inflight 48h guard）不重複報告

---

## 1. 執行摘要

**總體健康評分：C+（65/100）**。日常 happy path 運轉正常（所有 cron/LaunchAgent 均有近期 fire 證據、claim 機制有 fcntl lock、publish_milestone gate 鏈完整），但存在多個**結構性盲區**：監控系統看不到「沉默死亡」、gate 只裝在單一 code path、狀態 vocabulary 無 enforcement、文件宣稱的 code gate 有兩處不存在。其中一個 CRITICAL 已實際造成 boss 回信遺失（有 log 證據，至少 4 天份）。

**Top 5 風險**：

1. **[CRITICAL] Boss 回信系統性遺失** — gmail poll 的 subject-dedup 把「回覆同標題 alert」的後續信件永久丟棄；alert 標題是固定常數，5/27、6/1、6/2、6/7 四天對 CRITICAL alert 的回信均被 skip（log 195 次 / 8 個 unique 日×主題群）。
2. **[CRITICAL] FB 監控雙盲** — dashboard 與 audit_fb_pipeline 都只讀 `trending_repost_log.json`，但 event_article 的 FB 狀態寫在 `feed.json` 頂層 → 6 篇 awaiting（最舊 6/5、早超 72h auto-expire 門檻）對兩個監控完全 invisible。
3. **[HIGH] 排程沉默死亡無偵測** — hourly_dispatch / gmail_poll / compute_worker / handoff_regen 四個最關鍵 job 不在 dashboard staleness 監控清單；host_cron_fail 只看最後 exit code，LaunchAgent 整個停掉（log 凍結在 exit 0）不會觸發任何警報。
4. **[HIGH] release_pool 有 lost-update race** — feed 在 lock 外讀取、跨多次網路呼叫後在 lock 內全量覆寫；期間 publish 的新文章會被無聲覆蓋消失。`unpublish` 同樣無 lock 且 sync 失敗 silent。
5. **[HIGH] 兩個文件宣稱的 gate 不存在於 code** — (a) `validate_knowledge_provenance.py`「CI invariant」未接任何 cron/test；(b) paper-workflow.md 宣稱的「paper-update CLI 阻擋無 binding row」在 `update_paper_full` 中無任何實作。

---

## 2. 逐流程發現

### 2.1 任務池與派工流（next_tasks.json → dispatch → refill → sync）

**現狀**：`storage/next_tasks.json` 為 pending queue 兼永久 receipt 檔（1,245 筆 / 1.7MB），`task_pool_claim.py` 提供 fcntl-locked claim 狀態機，`continue_task_dispatch.py` 三桶分類（agentable/main_thread/blocked）+ 三段式 auto-refill，`sync_next_tasks_status.py` 反查 experiments 補標完成。機制基本健全，問題集中在狀態機邊界。

#### 發現 1-1 [HIGH] `complete` 接受任意 status 字串 — 狀態 vocabulary 失控
- **證據**：`scripts/task_pool_claim.py:151-159` — `task["status"] = args.status` 無 whitelist 驗證。實際後果：next_tasks.json 中存在 **24 種 distinct status**（jq group_by 實測），含 `partially_resolved_K1180_done_awaiting_K1179`、`in_progress_addendum_added`、`completed` vs `succeeded` vs `completed_local` vs `completed_null` 等同義異形。
- **影響**：下游所有 reader 各自 hardcode 認得的子集 — dispatcher 只認 `pending`（`continue_task_dispatch.py:102`）、dashboard in-flight 只認 `compute_queued/claimed/in_progress`（`ops_dashboard.py:110`）、stale cleanup 只認 `claimed/in_progress`。不在任何子集的 status = **三不管隱形態**：不會被派、不算 in-flight、不被 cleanup、不進 stale_inflight 警報。`partial` / `in_progress_addendum_added` 等即屬此類。這正是 2026-06-03 FB pipeline「audit terminal set 含被動態」事故的同構 anti-pattern。
- **修法**：`task_pool_claim.py` 加 `CANONICAL_STATUSES = {pending, pending_main_thread, claimed, in_progress, compute_queued, blocked, succeeded, succeeded_null_result, failed, cancelled, deprecated}`，`cmd_complete` 對不在集內的 `--status` 直接 reject；一次性 migration script 把 24 種收斂映射到 canonical 集（修流程同時修正資料產生源，符合「修流程不修資料」—— migration 是 schema 收斂不是改結果）。

#### 發現 1-2 [HIGH] 狀態轉移無前置驗證 — 可復活已完成任務、可無 claim 直標 succeeded
- **證據**：`task_pool_claim.py:124-133` `cmd_release` 對**任何** status 的 task 無條件設回 `pending`（succeeded task 也會被復活重派）；`cmd_complete`（:151-159）不檢查當前 status，未 claim 的 pending task 可直接標 succeeded。另 `cmd_claim:105` 允許從 `blocked` 直接 claim — 繞過 `blocked_reason` gate 與 `unblock_expired_blocked_tasks.py` 的 ISO 時間驗證（PRE-PHASE-0 設計的「雙層 gate」被 claim 路徑單方面打穿）。
- **影響**：「task 標 succeeded 但工作只做一半」的歷史 incident 模式無機制防禦 — 任何 agent 一行 CLI 即可偽造 terminal 態；blocked 任務（如 `paid_data_source_decision_pending`）可被誤 claim 執行。
- **修法**：`cmd_release` 限定 from-status ∈ {claimed, in_progress}；`cmd_complete` 限定 from ∈ {claimed, in_progress, compute_queued}（其他需 `--force` + 寫 release reason）；`cmd_claim` 從可 claim 集移除 `blocked`。

#### 發現 1-3 [MEDIUM] blocked 池 = 永久 limbo + terminal 態混居
- **證據**：77 筆 blocked 中僅 **12 筆有 `blocked_until`**（auto-recheck 對 84% 無效）；38 筆 reason=`deprecated`（語意上是 terminal，不是「等待解除」）；2 筆完全無 reason；3 筆 free-text reason（如「K136 is completed historical experiment…」）違反 `blocked_reasons.py` controlled vocabulary。
- **影響**：blocked 審查清單被 38 筆死任務淹沒，真正待解除的 ~39 筆無人定期 re-check（control-plane.md 規定的「periodically review and unblock」無機制承載，純靠紀律）。
- **修法**：(a) `deprecated` 升格為獨立 terminal status（`mark_task_blocked.py --reason deprecated` 改寫 status=deprecated）；(b) `mark_task_blocked.py` enforce vocabulary（目前 free-text 可入庫 = vocab 形同虛設）；(c) 無 `blocked_until` 的 block 強制給 default 30d re-check，到期由 unblock sweep 翻回 pending 重新 triage。

#### 發現 1-4 [MEDIUM] queue 兼 archive — 單檔無限增長 + dup-id zombie 已發生
- **證據**：1.7MB / 1,245 筆，1,090 筆 terminal；所有 claim 操作 flock 全檔 read-parse-rewrite；`scripts/dedupe_next_tasks.py` 的存在與 docstring（「duplicate pending row after a terminal row creates a zombie task」）證明 dup-id 競態已實際發生過。gmail dedup（`_existing_task_keys`）每 15 分鐘全檔掃描。
- **影響**：lock 持有時間隨檔案線性增長 → claim 衝突率上升；`_find` 取第一筆 match，dup row 下行為未定義。
- **修法**：月度 archive 流程 — terminal 超過 30 天的 rows 搬 `storage/ops/next_tasks_archive/<YYYY-MM>.json`（receipt 不丟，符合 audit trail 要求）；gmail dedup keys 同步搬移後需改查 archive（或 dedup state 獨立成 keyed file，見 5-1 修法）。

#### 發現 1-5 [MEDIUM] stale cleanup 雙 truth：2h vs 6h，且誤傷合法多 tick 任務
- **證據**：`task_pool_claim.py:47` `DEFAULT_STALE_HOURS = 6`，但 `cron_handoff_regen.sh:22` 實際每小時跑 `cleanup --stale-hours 2`。email_reply 的設計 lifecycle 是跨多 tick 留 in_progress（task-routing.md「Tick N..M」流程）；2h cleanup 會把合法等待 linked sub-tasks 的 email_reply 強制 release 回 pending → 下一輪重新 ANALYZE/PLAN（hourly prompt 自己承認「plan email 已寄，用戶會看到 retry log」）。cleanup 判齡用 `claimed_at`，無 per-type 豁免。
- **修法**：cleanup 加 per-task_type stale 門檻（email_reply 給 24h 或以 `needs_close_reply=true` 豁免）；移除 2h/6h 雙值（cron 不帶參數，門檻收斂到 script 內單一表）。

#### 發現 1-6 [LOW] sync_next_tasks_status 把 FAIL/PRELIMINARY 一律標 terminal
- **證據**：`sync_next_tasks_status.py:69-74` — `LOW_COVERAGE_PRELIMINARY` / `PRELIMINARY` 映射到 `succeeded_null_result`（terminal）。
- **影響**：preliminary 實驗的「待補全」信號被終結，不會再被任何流程撿起；K_ID_RE 不匹配 `_v2` 後綴已在 error_log 2026-06-08 記錄（未修）。
- **修法**：PRELIMINARY 類映射到非 terminal 的 `needs_followup`（納入 1-1 的 canonical 集）或自動生 followup task。

#### 查過無問題
- claim 的 fcntl LOCK_EX 跨 session 原子性、`_maybe_refill` 三段式補池邏輯、refill 的 8 層 dedup belt（雖有 belt-accretion 風味，見 §3-E）、`unblock_expired_blocked_tasks` 的 ISO 比對設計。

### 2.2 實驗流程（三件套 → Codex review → knowledge.json）

**現狀**：三件套慣例 + K1259 process gate（`memory/system.py:_append_to_index` → `provenance.validate_provenance`）擋 PASS 無 provenance/reviewer 的寫入。gate 在 Python writer 路徑上有效。

#### 發現 2-1 [HIGH] 「CI invariant」script 未接線 — jq/Edit 繞過永遠不會被抓
- **證據**：`grep -rln validate_knowledge_provenance tests scripts .claude` 全 repo 只命中 script 自身與規則文件（worktree 副本除外）；無任何 cron wrapper、無 tests/ 引用、`cron_memory_health.sh` 無 provenance 檢查。CLAUDE.md / experiments.md 宣稱「CI invariant: scripts/validate_knowledge_provenance.py（baseline 284）」— 該 invariant 從未自動執行。
- **影響**：experiments.md 自己承認「手動 jq/Edit 不會被 Python validator 攔截 — 走 CI script 才會發現」，而 CI script 沒人跑 = K1259 gate 的第二層防線是紙上防線。violation count 超 baseline 不會有任何人知道。
- **修法**：接進 `cron_memory_health.sh`（每日 05:30 已存在）末尾跑 `validate_knowledge_provenance.py`，exit≠0 時走 send_alert warn；或加入 tests/ 由任何 pytest run 觸發。一行 wrapper 即可。

#### 發現 2-2 [MEDIUM] verdict 無 controlled vocabulary — 後綴變體繞過 provenance gate
- **證據**：`provenance.py:97-99` 嚴格等值 `verdict == "PASS"` / `"CONDITIONAL_PASS"` 才 gate（註解明言為避開歷史後綴 label）。knowledge.json 實測 verdict 分佈含 `PASS_NULL`×2、`CONDITIONAL_PASS (SIMULATION) → FIXED → EFFECTIVE_PASS`×1、`H_K1300_CONFIRMED_FAIL`、`TAIL_CALIB_USABLE`×2 等 19 種 free-form。
- **影響**：agent 寫 `verdict: "PASS_OOS"` 或 `"EFFECTIVE_PASS"` 即合法跳過 provenance + reviewer 要求 — gate 對守規者有效、對（無意或有意的）變體寫法無效。與 1-1 同構：狀態字串無 enforcement。
- **修法**：`_append_to_index` 對 knowledge.json 新 entry 的 verdict 做 canonical 集驗證（PASS / CONDITIONAL_PASS / NULL / FAIL / MIXED / SUPPORT…），prefix 以 `PASS` 開頭但非 canonical 的直接 reject 要求改寫 — 歷史條目不動，只擋新寫入。

#### 發現 2-3 [MEDIUM] failed compute job 無自動 followup 路徑
- **證據**：`compute_queue.py:119-123` — PHASE A 用的 `--completed-pending-followup` filter 結構性排除 `status=failed`；queue 內 12 筆 failed（vs 25 completed）。`run_next` 失敗只寫 job JSON，無 alert、無 parent task release。另 :122 — completed 但缺 `claude_followup` brief 的 job 同樣永不被 followup（silent）。
- **影響**：failed compute 的 parent task 停在 `compute_queued` 直到 48h stale_inflight guard 才浮出（最多延遲 2 天）；目前 12 筆 failed 均已被手動處理（followup_dispatched=true），但靠的是人工巡檢非流程。
- **修法**：`list_jobs` 加 `--failed-pending-triage`；hourly PHASE A 第 2 步同時查 failed → 派 triage（escalation ladder 已有現成機制可掛）。`run_next` 失敗時直接 send_alert warn。

#### 查過無問題
- 三件套慣例在近期 K（k1449 等）落實正常；`_append_to_index` 確實對 knowledge.json 呼叫 validate_provenance（system.py:313-315）；NULL/FAIL 不 gated 是設計選擇（rationale 合理）。
- merge_worktree.sh `main..worktree` 誤判 bug 為**已知未修**（error_log 2026-06-09 strike-2，等 strike-3 重構）— 不重複展開，但提醒：期間每次 worktree merge 都依賴手動 bypass，建議不等 strike-3 直接改 merge-base 比對（一行 diff range 修正 + regression test）。

### 2.3 發佈流（publisher → supabase_sync → 線上）

**現狀**：`publish_milestone` gate 鏈完整且順序合理（exact-title 24h → near-dup 14d → arc-dedup 90d → cluster cooldown → content provenance Tier-1 → image-URL → Tier-2 LLM → audience gate → general audit → atomic locked append → sync → live verify）。問題在 gate 鏈**之外**的路徑。

#### 發現 3-1 [HIGH] `publish_experiment` / `publish_comparison` 繞過全部 gate
- **證據**：`publisher.py:465-528` — 兩 method 直接 `_append_to_feed`，無 dedup、無 arc、無 content/image audit、無 audience gate、status 硬編 `'published'`；`publish_experiment` 甚至**不呼叫 sync_article**（本地 published、Supabase 無 row）。`publish_experiment` 仍有 active caller：`src/volpred/cli.py:506`。
- **影響**：任何走 CLI experiment-publish 入口的內容可零檢查直上 published；是「gate 只擋一條路」anti-pattern 的教科書案例。
- **修法**：兩 method 內部改為組裝參數後委派 `publish_milestone`（保留簽名向後相容）；或若已無正當使用場景，刪除 method + 移除 cli.py 入口（需先確認 cli 該 command 的實際使用頻率）。

#### 發現 3-2 [HIGH] dup-block 回傳既有 id — 與成功發佈在 API 上不可區分
- **證據**：`publisher.py:563-564`（exact dup `return existing['id']`）、:604（near-dup `return s['id']`）、:622（arc dup `return d['id']`）— 三個 hard block 都只 print + 回傳**別篇文章的 id**，與成功路徑回傳新 pub_id 同型別同形狀。
- **影響**：呼叫端（寫作 agent / 自動化 script）拿到 id 即認定發佈成功 → task 標 succeeded、FB 雙發佈流程拿著**舊文章的 id** 去發 FB / 留言連結 / mark_fb_post_status — 整條下游污染。被 block 的事實只存在於 stdout。
- **修法**：被 block 時 raise `DuplicateArticleError(existing_id=...)`（與 cluster gate、content gate 的 ValueError 行為一致化）；或至少回傳結構 `{"id":..., "blocked": True, "dup_of":...}`。需同步盤點 caller（feed-publisher skill、publish_draft.py）的錯誤處理。

#### 發現 3-3 [HIGH] `unpublish` 無 lock 寫 feed + sync 失敗 silent — 下架不保證傳播
- **證據**：`publisher.py:1033-1055` — (a) 直接 `open(self._feed_file,'w')` 寫全檔，**未走** `shared_state_lock("publisher_feed")`（`_append_to_feed`:1154 與 `_rewrite_feed_entry`:1200 都有 lock，唯獨 unpublish 沒有）；(b) Supabase sync 包在 `except Exception: pass`，失敗**不進** `.failed_supabase_syncs.json`（publish 路徑有此機制，unpublish 沒有）。
- **影響**：(a) 與並發 publisher 寫入互相覆蓋（lost update）；(b) 撤稿/下架（含 arc-dup retract，正是 6/10 當天用過的操作）若 sync 失敗，文章在 Supabase 繼續 published，本地與線上分歧且無警報 — 對「推翻舊結論必回溯更正」的研究誠實條款是直接威脅。
- **修法**：unpublish 改走 `_rewrite_feed_entry`（已有 lock + read-back）；sync 失敗加入 `.failed_supabase_syncs.json`（drain cron 已存在，免費獲得 retry）。

#### 發現 3-4 [HIGH] release_pool lost-update race — lock 外讀、跨網路呼叫後 lock 內全量覆寫
- **證據**：`src/volpred/ops/content.py:219` `feed = load_feed(storage_dir)`（無 lock）→ 釋出迴圈內每篇做 sync_article（HTTP）+ notify + live_verify（HTTP）→ :374-375 才取 lock `dump_json(_feed_path, feed)` 全量覆寫；:408-409 live-verify 後再覆寫一次。視窗長達數秒～數十秒。
- **影響**：視窗內任何 `publish_milestone._append_to_feed`（有 lock 但 release 的 stale 全量 dump 會蓋掉它）寫入的新文章**無聲消失**。2026-05-04 finding #17 只把「寫」放進 lock，沒把「讀-改-寫」做成臨界區 — 修了一半。release cron 每 3h fire 一次 × 平台每日 6+ 篇發文節奏，碰撞機率不可忽略。
- **修法**：release 改成 per-entry 更新 — 選出 candidate ids 後，在 lock 內 re-load feed、逐 id 更新 status、寫回（網路呼叫全部移出臨界區，sync/verify 用更新後的 entry copy）；或全迴圈改用 `_rewrite_feed_entry` 逐篇提交。

#### 發現 3-5 [MEDIUM] release 不 re-run arc gate；arc gate import 失敗 silent skip
- **證據**：(a) release 時僅 re-run `_audit_general_content`（content.py:299），arc-dedup 在 2026-06-10 之前建立的存量 draft 沒被掃過（當日重構只清了 task pool pending，未掃 feed.json 內 status=draft 的存量文章）；(b) `publisher.py:623-624` `except ImportError: pass` — arc_dedup 模組壞掉時 gate 無聲消失（content gate 同型失效會 send_alert，arc gate 不會）。
- **修法**：(a) 一次性 `scripts/check_arc_dedup.py` 掃 feed 內全部 draft，dup 標 deprecated；(b) ImportError 分支加 print + send_alert（比照 prepublish_audit degrade 處理）。

#### 發現 3-6 [LOW] sync_full 在 partial failure 時 `feed_mtime` 照常前進
- **證據**：`supabase_sync.py:861` — 即使 `to_sync` 中部分 sync_article 失敗，`state["feed_mtime"] = feed_mtime` 仍寫入；失敗 entry 的 hash 不記錄（會 retry），但 retry 要等下次 `feed_mtime > last_feed_sync` 才會重開 change-detection block。實務上 reports/*.json mtime 常變 + drain cron 兜底，影響低。

#### 查過無問題
- `_append_to_feed` 的 lock + tmp-file + read-back verification 鏈完整；K1021 修正（sync 回傳值捕捉 + failed queue）在 publish 與 release 兩路徑都落實；markdown sanitizer / emdash normalizer 雙層；live_verify 失敗有 alert。

### 2.4 排程與 cron

**現狀**：實際執行健康 — 34 個 log 全部有合理近期 mtime（gmail_poll 17:45、handoff 17:50、check_alerts 17:02 等），piggy-back + LaunchAgent + crontab 三軌並行可用。問題在 spec 漂移與監控覆蓋。

#### 發現 4-1 [HIGH] 最關鍵的 4 個 job 無 staleness 監控；LaunchAgent 沉默死亡不可見
- **證據**：`ops_dashboard.py:278-282` `monitored` dict 只含 8 個 job（collect_us/tw、release_pool、check_alerts、paper_sync_all、memory_health_daily、market_calendar_sync、refresh_paper_snapshots）— **hourly_dispatch、gmail_poll、compute_worker、handoff_regen 全不在內**。host_cron_fail（alerts.py:448-534）只 parse 各 log「最後一行 exit banner」— 若 LaunchAgent plist 被 unload / keychain 失效 / 機器重開後未載入，log 凍結在最後一次 exit 0，**永遠不 breach**。歷史上 hourly-dispatch 已有「8/12 失敗未警報」（alerts.py:35 註解）與 keychain 全 attempt 失敗（email_reply 任務 11820 標題可證）前科。
- **影響**：整個自主運營引擎（hourly dispatch）或 boss 通訊通道（gmail poll）死掉時，唯一發現機制是 boss 自己覺得「怎麼沒信了」。
- **修法**：dashboard `monitored` 補 4 個 job（cron string 已在 runtime_schedules.json，croniter 機制現成）：`hourly_dispatch`（grace 30min）、`gmail_poll`（grace 30min）、`compute_worker`（grace 60min）、`handoff_regen`（grace 90min）— 用 log mtime 當 fire 證據（`job_log_map` 機制已存在，只缺 entries）。

#### 發現 4-2 [MEDIUM] runtime_schedules.json 與實際執行面漂移 — `host_crontab_managed: true` 名不符實
- **證據**：spec `system_crontab.items` 26 項全部未標 `host_crontab_managed: false`（按 control-plane.md 規則應視為 crontab 管理），實際 `crontab -l` 僅 15 條 volpred entries — gmail_poll、handoff_regen、check_alerts、daily_update、work_summary_6h、reader_facing_refill、question_research、supabase_sync_drain、log_rotate、codex_update、arxiv_scan 共 12 項不在 crontab（實際由 LaunchAgent / piggy-back run_due_jobs 執行，log 證明有 fire）。另 control-plane.md 仍宣稱「macOS host cron 只可靠執行 `0 * * * *` pattern」，但現行 crontab 15 條中 13 條非該 pattern 且照常 fire（`15 * * * *` audit_publish_sync 17:15 有 log）— 文件敘述已過期。
- **影響**：「排程唯一來源 = runtime_schedules.json」的 single source of truth 只剩 spec 層；**執行載體**（crontab vs LaunchAgent vs piggy-back）無 canonical 記錄 — 搬機器 / 災難復原時無法從 config 重建完整排程面；`install_host_crontab.sh` 重跑會把 12 個非 crontab 項裝回 crontab 造成雙 fire。
- **修法**：spec 每項加 `runner: crontab|launchd|piggyback` 欄位並校正至現實；`install_host_crontab.sh` 只裝 runner=crontab 項；control-plane.md 0-pattern 段落更新或刪除。

#### 發現 4-3 [MEDIUM] dashboard_latest.json stale 問題已記教訓未結構修正
- **證據**：error_log 2026-06-07/08 兩度記錄「ops_dashboard.py 只 print，檔案靠 cron 重導，tick 間 stale」，處置是行為約定（tick 改 live recompute）。約定型修正在 compact / 新 session 後易丟失 — 同類 prompt-discipline 失效已有多前科。
- **修法**：ops_dashboard.py main() 直接寫 `storage/ops/dashboard_latest.json`（atomic tmp+rename）並在 payload 加 `generated_by` / `age_seconds` 欄位；讀方檢查 age 超門檻就 live recompute。strike 2 已到，建議直接修。

#### 發現 4-4 [LOW] dashboard Supabase parity 查詢失敗誤報為 sync missing
- **證據**：`ops_dashboard.py:210-211` `except Exception as e: pass` — 網路 / key 失敗時 `supa_synced` 留空 → 全部 recent_ids 被列 missing → distribution_supabase 誤判 critical，建議行動（跑 full sync）治標不治本。
- **修法**：exception 時該 section 改報 `status=warn, tldr="parity check unavailable: <err>"`，不冒充 sync 失敗。

### 2.5 Email / Gmail 流

**現狀**：gmail_poll 每 15 分鐘 PEEK 掃 2 天窗、三條件 filter（owner + Re: + [VolPred）、三層 dedup（Message-ID → normalized subject → state file）、fast-path 即答、ack 即時寄、新單即時觸發 dispatch。架構合理，但 dedup 第二層有系統性誤殺。

#### 發現 5-1 [CRITICAL] subject-dedup 永久丟棄同標題的後續 boss 回信 — 已實際遺失多封 CRITICAL 回信
- **證據鏈**：
  1. `gmail_inbox_poll.py:553-557` — normalized subject 命中**任何 status** 的既有 email_reply task 即 skip。dedup keys 來自 next_tasks.json 全量（`_existing_task_keys`，任何 status、永不過期）。
  2. Message-ID dedup 在 subject dedup **之前**（:549）— 因此凡 log 出 `already_queued_by_subject` 的信，其 Message-ID 必不在任何已 queue task 中 = **是一封從未被 queue 的不同信件**。
  3. alert 標題是固定常數（`alerts.py:525` `title="Host cron failure detected"`；boss report 標題亦同模板）→ boss 每次回覆同類 alert，subject 正規化後完全相同。
  4. log 實測：`already_queued_by_subject` 共 **195 次**，去重後 **8 個 unique 日×主題群**，其中 `Re: [VolPred Alert][CRITICAL] Host cron failure de...` 出現在 **05-27、06-01、06-02、06-07 四天**（SINCE 窗僅 2 天，跨 11 天的四群必為不同信件）。next_tasks 中該主題僅一筆 task（2026-05-25 建、已 succeeded）。
- **影響**：boss 對**重複發生的 CRITICAL alert** 的回信（最需要被讀的信）被系統性丟棄，無 ack、無 task、無任何痕跡（只在 cron log）。直接違反「mandate 直接讀 Gmail 最新信」的 boss 指令與 AI 全自動運營承諾。
- **修法**（任選其一，建議 a）：
  - (a) subject-dedup 只對 **非 terminal** 的既有 task 生效（`_existing_task_keys` 過濾 `status in {pending, claimed, in_progress}`）— 已結案的 thread 來新信就是新任務；Message-ID dedup（第一層）+ state file（第三層）已足以防同信重掃。
  - (b) dedup key 改 `(normalized_subject, Date-header 當日)` 複合。
  - 並補一次性 backfill：對 8 個 dropped 群以 IMAP 重撈原文、人工 triage 是否仍 actionable。
- **註**：`UNVERIFIED` 殘餘風險 — 無法在本審計中讀取信件原文確認 4 封 CRITICAL 回信的內容是否含未執行指令；驗證方法 = IMAP search `SUBJECT "Host cron failure" SINCE 26-May-2026` 比對 Message-ID 與 next_tasks。

#### 發現 5-2 [MEDIUM] `M.search` 用 sequence number 非 IMAP UID — `email_uid` 跨日不穩定
- **證據**：`gmail_inbox_poll.py:507/526` 用 `M.search` + `M.fetch`（非 `M.uid('search')` / `M.uid('fetch')`）— 回傳的是 mailbox **sequence number**，隨信箱增刪變動。實證：log 中 2026-06-07 的 `uid=11725` subject 是 "Host cron failure"，而 next_tasks 中 `email_uid=11725` 的 task（05-25 建）subject 是 "Boss Report 05-25" — 同編號不同信。
- **影響**：task 的 `email_uid` 欄位與 `state.last_uid` 無法用於回溯定位原信（audit / backfill 時誤導）；dedup 正確性不受影響（靠 Message-ID）。
- **修法**：改用 `M.uid('search', ...)` / `M.uid('fetch', ...)`，state 記真 UID（UIDVALIDITY 一併記錄）。

#### 查過無問題
- ack `--force` 旁路 dedup 設計正確（ack 必須每次寄）；fast-path task 直標 succeeded 含 result 痕跡完整；`_trigger_immediate_dispatch` 的 pgrep + min-gap 雙 guard；PEEK 不動已讀態；ack 失敗不丟 task。

### 2.6 FB 雙發佈流

**現狀**：trending_repost 走 `trending_repost_log.json`，event_article 走 feed.json 頂層 `fb_post_status`（2026-06-01 single-source migration 後的 canonical）+ `fb_post_failures.jsonl` append log。audit_fb_pipeline cron 每 6h 掃 stale + auto-expire >72h。

#### 發現 6-1 [CRITICAL→HIGH] 監控只讀 trending log — event_article FB backlog 對 dashboard 與 audit 雙盲
- **證據**：
  - `ops_dashboard.py:236` `fb_log = jl(.../trending_repost_log.json)`；`audit_fb_pipeline.py:17` `LOG = .../trending_repost_log.json` — 兩個監控同讀單一來源。
  - feed.json 實測：6 筆 `fb_post_status=awaiting_interactive_session`（mile_7c8a04f4 06-05、mile_072c3972 06-08、mile_166eda01/mile_0fa9c7f5 06-09、mile_0e1eb5aa/mile_64f2e656 06-10）；**0/6 存在於 trending_repost_log.json**（jq 交叉比對）。
  - trending log 內 28 筆全 terminal → dashboard FB section 顯示「0 pending / 0 awaiting」= 全綠，audit 的「>72h auto-expire」對 mile_7c8a04f4（已 5 天）永不觸發。
- **影響**：publishing.md 宣稱 feed.json 頂層是「dashboard/audit 唯一讀的位置」——**寫**收斂了，**讀**沒跟上；event_article 的 FB 強制雙發佈承諾（2026-05-25 用戶硬性要求）整條 backlog невidimý，與 2026-06-03「FB pipeline 4 天 100% 失敗」事故同構（換了一個檔案重演 wrong-source 盲區）。
- **修法**：`classify_fb_pipeline` 與 `audit_fb_pipeline.py` 的資料源改為 **feed.json 頂層 fb_post_status**（per publishing.md canonical），trending_repost_log 降級為 trending 專屬 metadata；audit 的 auto-expire 同步搬。加 regression test：feed 含 awaiting entry 而 trending log 不含時，audit 必須列出該 entry。

#### 發現 6-2 [MEDIUM] `fb_post_failures.jsonl` 無 reader — failed entry 15 天 retry_count=0
- **證據**：檔案僅 2 筆；2026-05-26 `mile_ebb5d6f5` `fb_post_status=failed, retry_count=0` 至今無人收（該文 feed 端後來標 success，顯示實際有人工補發但 failure log 從未被消化/更新 — 寫入端有、消費端無）。grep 全 repo 無任何 script 讀此檔。
- **影響**：SKILL 規定的「失敗必留 retry log」有寫無讀 = 儀式性合規；retry 責任實際落在 interactive session 的人工記憶。
- **修法**：併入 6-1 — failure 狀態統一寫 feed.json 頂層（mark_fb_post_status.py 已支援），jsonl 廢棄或降級為純 append 歷史；若保留，audit_fb_pipeline 必須消化它。

### 2.7 論文流

**現狀**：11 個 paper dir，10 個有 reproduce.py + reproduce_report.json；review_history/v(n) 慣例落實良好（garch-x-vix 到 v7、leverage-direction 到 v10）；paper-sync-all cron 每 6h 兜底同步。

#### 發現 7-1 [HIGH] 文件宣稱的 reproduce / table-binding code gate 不存在
- **證據**：`paper-workflow.md` 硬規則 #3 宣稱「reproduce.py 輸出 table_row_mapping 驗證；**paper-update CLI gate 阻擋無 binding 的 row**」、#2 宣稱 reproduce gate 是 review 先決條件。實測：`grep -rln "reproduce_report\|table_row_mapping" src/volpred/ scripts/*.py` → **零命中**；`cli.py:2494-2504` `ops_paper_update` = `update_paper_full`（數頁數/引用數、傳 PDF、sync metadata）無任何 gate。
- **影響**：投稿品質 gate 全靠主線程讀規則自律；文件宣稱 code gate 存在會給未來 session 虛假安全感（「CLI 會擋」→ 不手動驗）— 與 2-1 同構的「紙上 gate」。
- **修法**：最小實作 — `update_paper_full` 開頭檢查 `paper/<id>/reproduce_report.json` 存在且 `match_rate ≥ 95%` / `alert_level == green`，否則 require `--skip-reproduce-gate --reason`；table_row_mapping 驗證可後續迭代。或退而求其次：修正 paper-workflow.md 措辭為「規範要求」而非「CLI gate 阻擋」。

#### 發現 7-2 [LOW] btc-gas-negative 無 reproduce.py 但已跑 review v1
- **證據**：`paper/btc-gas-negative/` 無 reproduce.py / reproduce_report.json，`review_history/v1` 存在；README status=draft「v1 body sections complete (2026-06-07), pending R0 review cycle」。硬規則 #2「未 pass 不得跑 review」與 kickoff 豁免條款邊界模糊（body 已 complete = 應已過 kickoff 階段）。
- **修法**：在 7-1 的 gate 實作中順帶覆蓋（paper-review-cycle 啟動前同一檢查）；btc-gas-negative 補 reproduce.py 後再進 R1。
- **註**：review→fix→re-review 鏈的逐 round 內容比對（task 標 succeeded 但 fix 只做一半）未逐篇展開 — 見附錄盲區。

### 2.8 Memory / 知識流

**現狀**：唯一合法寫入路徑 `MemorySystem._append_to_index`（含 provenance gate）；worktree agent 禁改 shared JSON 由 merge_worktree.sh 把關（該 script 有已知 bug，見 2-4 註）。

- 發現 8-1 = 2-1（CI script 未接線）與 2-2（verdict vocabulary）— 不重複計。
- 發現 8-2 [LOW]：`work_log.json` 596KB append-only 無 rotation；hourly prompt 高頻 `jq .[-5:]` 全檔 parse。與 1-4 同 pattern，月度 archive 一併處理。
- 查過無問題：`record_and_publish.py` 走 MemorySystem 正路；knowledge 寫入點未發現其他繞 Python writer 的 active script。

---

## 3. 跨流程結構性問題（重複出現的 anti-pattern）

| # | Anti-pattern | 實例 |
|---|---|---|
| A | **狀態字串無 enforcement**（free-form 入庫，下游各自 hardcode 子集） | task status 24 種（1-1）、knowledge verdict 19 種（2-2）、blocked_reason free-text 混入（1-3） |
| B | **Gate 只裝在一條 code path** | publisher gates 只在 publish_milestone（3-1）、provenance 只在 Python writer 且 CI 未接（2-1）、claim 可從 blocked 直取（1-2） |
| C | **監控看 active signal 不看 absence** | host_cron_fail 看 exit code 不看 log 凍結（4-1）、FB audit 讀錯源看不到 awaiting（6-1）、dashboard monitored 子集（4-1） |
| D | **文件宣稱 ≠ code 實作** | paper CLI gate 不存在（7-1）、provenance CI invariant 沒人跑（2-1）、host_crontab_managed 名不符實（4-2）、control-plane 0-pattern 敘述過期（4-2） |
| E | **Belt accretion**（每 incident 加一條 belt 而非重建 domain model） | refill 8 層 dedup belt、publisher 多層 patch 史 — 2026-06-10 arc_dedup 重構是正確方向，建議同法處理 A（status domain model）與 C（liveness domain model） |
| F | **失敗分支 silent**（except: pass / 只 print） | unpublish sync（3-3）、dashboard parity（4-4）、arc ImportError（3-5）、compute failed 無 followup（2-3） |

根本共因：**沒有「跨 reader 的 contract」概念** — 狀態集、資料源位置、gate 覆蓋面都是各 script 私有約定，新增 writer/reader 時無 schema 層擋住 drift。

---

## 4. 優化建議優先序表

| 優先 | 發現 | Severity | Effort | 可立即做? | 動作摘要 |
|---|---|---|---|---|---|
| 1 | 5-1 boss 信丟失 | CRITICAL | S（~20 行） | ✅ | `_existing_task_keys` subject keys 過濾 terminal status + backfill 8 個 dropped 群 |
| 2 | 6-1 FB 監控雙盲 | CRITICAL→HIGH | S | ✅ | dashboard + audit_fb_pipeline 資料源改 feed.json 頂層；補 regression test |
| 3 | 4-1 排程沉默死亡 | HIGH | S | ✅ | dashboard `monitored` 補 4 jobs（機制現成，只加 entries） |
| 4 | 3-3 unpublish 不傳播 | HIGH | S | ✅ | 改走 `_rewrite_feed_entry` + 失敗入 failed_syncs queue |
| 5 | 2-1 provenance CI 未接線 | HIGH | XS（1 行 wrapper） | ✅ | 接進 cron_memory_health.sh + 失敗 send_alert |
| 6 | 3-2 dup-block 偽裝成功 | HIGH | M（需盤 caller） | 設計後做 | block 改 raise / 結構化回傳 |
| 7 | 3-4 release_pool race | HIGH | M | 設計後做 | 讀-改-寫收進臨界區、網路呼叫移出 |
| 8 | 1-1 + 1-2 status 狀態機 | HIGH | M | 設計後做 | canonical status 集 + 轉移驗證 + migration（cross-cutting A 的根治起點） |
| 9 | 7-1 paper gate 落地 | HIGH | S | ✅（最小版） | update_paper_full 加 reproduce_report 檢查 |
| 10 | 3-1 ungated publish 路徑 | HIGH | S | ✅ | publish_experiment/comparison 委派 publish_milestone |
| 11 | 2-2 verdict vocabulary | MEDIUM | S | ✅ | _append_to_index 驗 canonical verdict 集（只擋新寫入） |
| 12 | 4-2 schedules spec 漂移 | MEDIUM | M | 設計後做 | spec 加 runner 欄位 + install script 對齊 + 文件更新 |
| 13 | 1-5 stale cleanup 雙 truth | MEDIUM | S | ✅ | per-type 門檻 + 收斂單一值 |
| 14 | 2-3 failed compute 無 followup | MEDIUM | S | ✅ | `--failed-pending-triage` + PHASE A 接 |
| 15 | 1-3 blocked limbo | MEDIUM | S | ✅ | deprecated 升 terminal + vocab enforce + default blocked_until |
| 16 | 4-3 dashboard 檔案 stale | MEDIUM | XS | ✅ | main() 直接寫檔 + age 欄位 |
| 17 | 6-2 failures.jsonl 無 reader | MEDIUM | XS | ✅ | 併入 6-1 |
| 18 | 5-2 IMAP UID | MEDIUM | S | ✅ | 改 M.uid() |
| 19 | 3-5 draft 存量 arc 掃描 | MEDIUM | XS | ✅ | 一次性 check_arc_dedup 掃 feed drafts |
| 20 | 1-4 / 8-2 queue archive | MEDIUM | M | 設計後做 | 月度 terminal archive（需與 5-1 dedup 方案協調） |
| 21 | 1-6 / 3-6 / 4-4 / 7-2 | LOW | XS-S | ✅ | 各一小修 |

**建議批次**：第 1-5 + 9-10 + 16 項可在 1-2 個 hourly fire 內完成（全是小 diff + 現成機制）；6-8、12、20 需先寫 mini design（涉及 caller 盤點 / migration / lock 語意），建議各立 platform_ops task 走正常派工。

---

## 5. 附錄

### 5.1 掃描範圍

**全文閱讀**：`scripts/continue_task_dispatch.py`、`scripts/sync_next_tasks_status.py`、`scripts/cron_hourly_dispatch_prompt.md`、`scripts/task_pool_claim.py`（核心段）、`src/volpred/ops/alerts.py`、`scripts/ops_dashboard.py`、`src/volpred/memory/provenance.py`、`scripts/gmail_inbox_poll.py`（370-700 + 結構 grep）、`src/volpred/publisher/publisher.py`（gate 鏈 + append + unpublish 全段）、`src/volpred/ops/content.py`（release 全段）、`scripts/compute_queue.py`（run_next/list/mark）、`.claude/rules/`（task-routing / control-plane / alert / publishing / experiments / paper-workflow / frontend）、`docs/error_log.md` 近 10 條、`storage/ops/agents/*.json`。

**結構 grep / jq 抽樣**：`storage/next_tasks.json`（status/blocked/email_reply 分佈）、`storage/memory/knowledge.json`（verdict 分佈）、`storage/reports/feed.json`（fb_post_status 分佈、awaiting 清單）、`storage/reports/trending_repost_log.json`、`storage/logs/fb_post_failures.jsonl`、`storage/logs/cron/gmail_poll.log`（dedup skip 全量）、`storage/logs/cron/` mtime 全量、`crontab -l`、`config/runtime_schedules.json`、`scripts/refill_task_pool.py`（belt 結構）、`scripts/supabase_sync.py`（sync_full/sync_article）、`scripts/dedupe_next_tasks.py`、`scripts/audit_fb_pipeline.py`、`paper/*/`（reproduce 檔存在性）、`src/volpred/cli.py`（paper-update / publish-experiment 入口）、`src/volpred/memory/system.py`（gate call site）、`git worktree list`。

### 5.2 盲區聲明（未查 / 查不到）

1. **LaunchAgent plist 內容**（`~/Library/LaunchAgents/`）— sandbox 限制未能列出；4-2 的 runner 歸屬靠 log mtime 反推，plist 層的 KeepAlive / 錯誤處理未驗。
2. **Supabase 線上實際 rows** — 未做 live parity 查詢；3-3/3-6 的線上分歧風險是 code-path 推論，當前是否存在實際 divergence 未驗（驗法：`scripts/audit_publish_sync.py` 已有 27 mismatch 前科可追）。
3. **Boss 被丟信件的內文** — 5-1 標 UNVERIFIED 段已給 IMAP 驗法。
4. **paper review→fix→re-review 逐 round 內容比對** — 僅驗慣例結構與 gate 存在性，未逐 paper diff review report vs 後續 commit（工作量大，建議抽 1-2 篇由 paper_review task 抽查）。
5. **anti_ai_gate.py / lazypack 流程** — 未展開（非本次 8 流程範圍核心）。
6. **`.env*` 未讀**（per 審計約束）；SMTP/IMAP credential 健康僅由 log 成功 fire 反推。
7. **frontend-v2-fix 巢狀 repo 的部署流** — 未展開（read-only 審計不觸 deploy）。

### 5.3 與既有 error_log 的銜接

- 本報告 4-3（dashboard stale）與 2-4 註（merge_worktree bug）是 error_log 已記錄但**未結構修正**項的 strike 升級提醒，非新發現。
- 6-1 是 2026-06-03 FB audit 事故（`feedback_audit_no_passive_terminal`）的**同構復發**（換資料源重演），建議在 error_log 記為該事故的 strike-2。
- 1-1/2-2 的 vocabulary 失控與 2026-05-27 blocked_reasons vocab drift 教訓同根 — 當時收斂了 blocked_reason 的 set 定義，但未 enforce 寫入端，本次發現 free-text 已再滲入。
