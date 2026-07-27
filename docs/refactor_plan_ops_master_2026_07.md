# Refactor Plan — Ops Master Consolidation（運營程式全面重構總計畫）

- **2026-07-23 關係說明**：本檔仍是交易式 operations core 接管前，Phase 1 現行 ops
  修復的 canonical implementation ledger；跨主機、provider、frontend、Admin、analytics
  與 growth 的 umbrella charter 見 `docs/platform_optimization_program_2026_07.md`。
  新 charter 吸收本檔成果，不重置 §7，也不得用尚未落地的目標架構改寫 live 狀態。
- **建立**：2026-07-20（owner 指令：「重構目前所有運營的程式碼，從底層邏輯、流程、架構分析，不符合的徹底改過；流程要有效率、不要重複功能、滿足 PDCA / loop engineering」）
- **Status**：ACTIVE — §7 狀態表為唯一進度真相（canonical）
- **性質**：**收編型 master plan**（anti-stacking）— 吸收既有 11 份 refactor plan 的全部殘留項（§4 對照表），此後所有 ops 重構工作以本檔為單一入口；舊 plan 不再各自推進。
- **診斷來源**：2026-07-20 五路平行稽核（控制面架構／scripts 全量盤點／enforcement 疊層／內容發佈管線／事故根因挖掘），全部 file:line 實證，非推測。

---

## 1. 三層診斷

### 1.1 底層邏輯層（domain model 哪裡錯了）

| # | 缺陷 | 證據 | 正確 model |
|---|---|---|---|
| L1 | **Ownership 由 cleanup layer 事後推理，不由執行隔離產生** — PHASE-Z 6+ 次復發的唯一共同根因；外部裁決原話「ownership 必須由 execution isolation 產生」 | error_log PHASE-Z 系列（2026-07-16 latch 4/5 次、07-19 40 檔 78 班）；`docs/dispatch-writer-isolation-design.md` 設計已完成未落地 | producer-scoped workspace：每個會寫檔的 dispatch 都在自己的 worktree 產出，merge 時身分自明 → WS-B |
| L2 | **任務生命週期不是單一狀態機** — status 受控詞彙 14 個，實際存在數十種自由文字終態（`completed`×11、`in_progress` 殘留、one-off 終態十餘種）；terminal 判定要同時看 status + tombstone + archived_at 三個正交維度；in_flight=7 而實際 running=0（07-20 10:49 lsof 實測 18/18 worktree 無進程） | `src/volpred/ops/next_tasks.py:160-185`（詞彙表 + baseline 27）；next_tasks.json 實測分佈；blocked_reason 欄位完全不在 vocab gate 覆蓋內 | 一個受控狀態機 + 一個 liveness reconciler；任何狀態宣告都能被磁碟/進程現實校正 → WS-A |
| L3 | **「發佈」缺最終一致性模型** — feed.json 寫入與 Supabase / Mirror 推送是三次獨立網路呼叫，失敗語意不一致（Supabase 記死信、Mirror 只 print），且**全系統沒有任何排程做全量對帳** — 收斂網不存在 | `publisher.py:2670,2407,2807-2814`；`config/runtime_schedules.json` 無 `sync_full`/`feed-sync --apply` 排程 | canonical（feed.json）→ 投影（Supabase/Mirror）採「即時推 + 週期全量對帳」的最終一致模型；一切失敗都進同一個死信與重試迴圈 → WS-C |
| L4 | **「活性」沒有單一定義** — cron_last_run 只記 piggyback 管的 job（launchd 直跑的 `daily_update` 顯示死 3 個月但其實活著）；launchd log path 失聯（size=0 但 job 在跑）；監控用哪個訊號判活全看各儀器心情 | `storage/ops/cron_last_run.json` daily_update=2026-04-25 vs `storage/logs/cron/daily_update.log` 07-20 新鮮；`run_due_jobs.py:350` | 每個 job 有唯一 liveness source（execution receipt），監控只讀該 source → WS-D |

### 1.2 流程層（process 哪裡斷了）

| # | 缺陷 | 證據 |
|---|---|---|
| P1 | **hang-kill 與 task 回收中間缺一條線**：supervisor kill worker 只釋放 dispatch_state 的 slot，不釋放 next_tasks 的 claim；補救 cleanup 又對 `claimed_at` 為空的 in_progress 直接 skip → 實測 4-5 筆殭屍（k1731_armB_rev7_*、assign_5aa9d5f5 等 20h+） | `dispatch_supervisor/health.py:88-179`、`worker.py:369`、`task_pool_claim.py:757-758` |
| P2 | **改稿流程繞 gateway**：publish_draft `--update` 直寫 feed，不推 Supabase、不推 Mirror、不記死信 → 一次改稿三方分岔，靠人記得補 | `publish_draft.py:1100,1428,1448-1450` |
| P3 | **shadow / 觀察期沒有到期決策流程**：pregate shadow 掛 18 天（token_ops_waste gate 已裁定「刻意不翻 enforce」但 shell 註解仍寫 "validating ~1 week"，spec 與裁定脫節）；hourly_dispatch Deliverable-8 退役、single_gateway claim-next 移除，全都「觀察中」無 deadline | `cron_hourly_dispatch.sh:161-165`；refactor_plan_hourly_dispatch / single_gateway 殘留項 |
| P4 | **rule 承諾的 gate 沒有落地追蹤**：`dedup-gate-audit.md:64` 承諾的 `audit_dedup_gate_decisions.py` 從未建，三條自動 alert 全無實作 — 2026-06-23 八天黑洞的防呆下半截沒蓋完 | `.claude/rules/dedup-gate-audit.md` §4 vs `ls scripts/`（不存在） |
| P5 | **事故立案不機械化**：「沒立案的 class，第二次發生等於第一次」（member_qa 重複研究事故原話）— dreaming/loop-health 的 detector 餵不到未立案訊號，閉環斷點在上游手動步驟 | error_log 2026-07-19 member_qa 條目；enforcement 稽核 §6 |
| P6 | **一次性腳本無歸檔流程**：`_legacy/` 制度在（2026-07-01 建），但此後新產物不搬 → 36 支無引用死碼 + 40+ 支未歸檔一次性腳本堆在 scripts/ 頂層 | scripts 盤點 §3/§4 |
| P7 | **prompt 層指示 agent 裸 jq 改佇列**，繞 canonical helper 與 flock | `cron_hourly_dispatch_prompt.md:63` |
| P8 | ~~急件直達線 Telegram 沒接~~ **Phase 0 查證後撤回**：急件 lane 已於 2026-07-18 後全接通 — `append_next_task` 內建 `_request_urgent_fire`（single gateway，涵蓋 telegram/user/owner/boss 全部人為 ingress）；`telegram_reply` 刻意排除是因為有更快的專屬 responder（`_spawn_responder` 即時 + 120s retry），docstring 明文「別再補接線」且有 `test_urgent_task_lane.py` 釘住。**此項非缺口** — 留此紀錄防止未來憑舊記憶再「補接線」疊層 | `src/volpred/ops/next_tasks.py:563-678`；`telegram_poll.py:127-131` |
| P9 | **對老闆的回報通道重複排程**：token 報告一天三班（`token_report_daily` 08:00 / `token_usage_daily_report` 14:43 / `token_usage_daily` 22:23）；email 報告器多支重疊（boss_report_4h ×3/日 + work_summary_6h + digest）— 降頻做過一輪（07-14）但 spec 層仍有殘餘重複 | `config/runtime_schedules.json` 實測 jq 輸出 |

### 1.3 架構層（implementation 哪裡疊了）

| # | 缺陷 | 證據 |
|---|---|---|
| A1 | **feed→Supabase 雙 sync 引擎**：`supabase_sync.sync_full`（hash+timestamp）vs `ops/feed_sync.compute_diff`（逐欄位+tags+audience），「什麼算 changed」判準不同 | `supabase_sync.py:1327,1379-1385` vs `feed_sync.py:183,222-240,428` |
| A2 | **lazypack 4 條渲染路徑且 PRIMARY 定義互相矛盾**：publishing.md 說 deterministic 唯一 PRIMARY；codex harness docstring + lazypack-infographic skill 說 codex 是 PRIMARY（引 2026-07-15 boss directive）；另有 NotebookLM 路徑與 legacy 範例檔 | `.claude/rules/publishing.md` §4 vs `gen_lazypack_codex.py:2-4` |
| A3 | **兩個 scheduler 同名一死一活**：`dispatch_supervisor/scheduler.py`（live daemon）vs `src/volpred/ops/scheduler.py`（advisory lane，last_tick 2026-04-19，無 lock 直寫 state，CLI 仍在） | `src/volpred/ops/scheduler.py:35-36`；`scheduler_state.json` |
| A4 | **雙 alert dedup store**：`ops/alerts.py`（alert_dedup.json，24h，已膨脹 769KB）vs `dispatch_supervisor/alerts.py`（dispatch_state 內 60s）— key 空間不互通 | 控制面稽核 P10 |
| A5 | **next_tasks.json 40+ writer**，含派工器自身的 truncate-before-serialize 危險寫法（同檔另兩處已用安全 helper — 同一檔三種寫法） | `continue_task_dispatch.py:509-511` vs `next_tasks.py:499-508` |
| A6 | **巨獸單檔混 concern**：phase_z.py 3137 行（隨 WS-B 縮小）、check_alerts.py 2860 行（alert 裁決 + run_due_jobs 排程混一檔）、publish_draft.py 1948 行（發佈全流程）、daily_update.py 1830 行（資料更新與發佈觸發耦合） | scripts 盤點 §5 |
| A7 | **健康/報告儀器 6 支重疊讀取**（ops_snapshot / daily_checkup / ops_dashboard / check_alerts / progress_report / boss_report + session_drill_down）— 邊界有 docstring 但 parser 重複維護 | scripts 盤點 §2 |
| A8 | **Enforcement Layer Map 過期**：漏 3 個已註冊 hook、4 項 deny、2 個 CI gate、5 個 git hook 現況 — 權威索引落後會誘發「以為沒 owner → 新開一層」 | `loop-health-and-dreaming.md:95-121` vs `settings.json` 實況 |
| A9 | **雙軌排程**（launchd 30 條 crontab 43 spec + piggyback + session_crons 殘骸）：session_crons 含 2026-04-24 一次性過期項、replay 機制 recorded 1596 次 / replayed 停在 04-27 | `runtime_schedules.json`；`pending_sessions.json` |
| A10 | **feed.json 多實體**：canonical + `storage/feed.json`（靠每小時 merge 兜）+ data-mirror 副本 + 陳舊變體檔殘留 | `merge_feed_files.py:1-4`；`daily_update.py:1499-1510` |

**稽核也確認的健康面**（不動）：anti-stacking 紀律整體良好（advisory+authority、single-owner+multi-trigger 模式都有明文歸屬）；dispatch_state.json 治理成熟（lock + AST gate）是模範；rule paths 無 dead path；loop-health/dreaming 程式接線完整；`__pycache__` 7.8MB 非資料誤置。**重構只動有病灶的地方，不為改而改。**

---

## 2. 設計原則（所有 WS 共用）

1. **PDCA 對映強制**：每條長駐流程必須四步齊備 — Plan（spec 在 config）、Do（單一 owner 執行）、**Check（機械驗證，不是 exit code）**、Act（失敗進 remediation task 或死信重試，教訓進 error_log/dreaming）。本次診斷的缺口幾乎全是缺 Check（無全量對帳、無 liveness reconcile）或缺 Act（Mirror 失敗只 print、rule 承諾沒人追）。
2. **Loop engineering 分層不變**：fast loop（loop_health）／slow loop（dreaming）／guardrails（hooks+gates）架構不動，本計畫是把**餵給閉環的訊號源**修好（P5 立案機械化、L4 liveness 單一化）。
3. **Anti-stacking**：一 concern 一 owner；本計畫每個 WS 都列「廢棄面」，落地時同 commit 移除被取代物，不留兩套。
4. **永遠修流程不修資料**：殭屍任務、汙染終態、分岔投影一律「先修產生它的程式 → 再讓修好的流程自然收斂資料」；一次性 migration 只在流程修復後做、且記錄原值。
5. **觀察期必有 deadline**：任何 shadow / disabled-but-alive / deprecated 狀態，建立時同步寫死到期日與到期動作（翻轉或退役），逾期未決策 = dreaming detector 可見的 breach。
6. **每 WS 落地順序**：snapshot commit → 改碼 → 測試 → Codex review → 部署/掛載 → 線上 Check → §7 狀態表更新。宣告完成必附實測證據。
7. **Gate 流暢無死局**（owner 2026-07-20 硬規）：檢查關卡不得為檢查而中斷流程；每個 block 型 gate 必附出口（自動修復路徑／時限寬限／升級裁決三選一）；audit 觸發時開單不只擋（actuator 原則）；新 gate 上線前做「死局測試」證明工作最終能流出。memory：`feedback_gates_smooth_no_deadlock`。

---

## 3. Workstreams

### WS-A 任務狀態機重構（單一狀態機 + liveness reconcile）— P1

**終態**：next_tasks.json 只有 canonical helper 一種寫路徑；status/blocked_reason 全受控；kill 與 claim 釋放閉環；佇列宣告與磁碟/進程現實每小時自動對帳。

| ID | Deliverable | 廢棄面 | 驗證 gate |
|---|---|---|---|
| A1 | 所有 writer 收斂到 `next_tasks.py` helper：修 `continue_task_dispatch.py:509-511` truncate 寫法；`cron_hourly_dispatch_prompt.md:63` 的 jq 指示改為 `task_pool_claim.py` 子命令；40+ writer 全量掃描分類（合法 caller / 需改 / 需刪） | prompt 內 jq 寫法；truncate 路徑 | 新增 audit：grep 掃「開 next_tasks.json 寫模式但非經 helper」= 0（掛進既有 pre-push audit runner，單一 owner） |
| A2 | kill→release 接線：`health.py` kill worker 時同步 re-pend 該 slot 的 claim；`task_pool_claim.py:757-758` 修 claimed_at 空白盲點（無 claimed_at 的 in_progress 以 fallback 時間戳判 stale） | — | 單元測試覆蓋「kill 後 task 回 pending」+「無 claimed_at 殭屍被回收」；現存 4-5 筆殭屍由修好的 cleanup 自然回收（不手改 JSON） |
| A3 | status/blocked_reason migration：一次性把汙染終態映射回受控詞彙（原值存 `status_original`）；vocab gate 擴覆蓋 `blocked_reason`；legacy baseline 27→0 | 自由文字終態；baseline 豁免 | `validate_next_tasks_status.py` 全綠且 baseline=0；CI gate 含 blocked_reason |
| A4 | liveness reconciler：每小時對帳 in_flight/claimed vs 磁碟 worktree vs 進程（lsof），脫鉤自動降回 pending 並記 receipt（吸收 k1709 殭屍教訓） | — | 注入假 in_flight 的 regression test；`ops_snapshot` 的 in_flight 與實際 running 長期一致 |

### WS-B Producer-scoped execution isolation — P1（收編三份文件同指的未落地架構）

**終態**：platform_ops / governance dispatch 一律 worktree 隔離產出、gate-green 才 merge；ownership 由隔離產生；PHASE-Z 猜作者邏輯降級為 fallback，穩定一個月後退役 recognizer（phase_z.py 3137 行隨之大幅縮小）。

- 依 `docs/dispatch-writer-isolation-design.md` 落地（設計已完成）；分兩段：先 platform_ops lane 試點 1 週 → 全 lane。
- 廢棄面：PHASE-Z 基線快照猜作者主路徑；error_log D1 已明令停止的新增 recognizer 路線。
- 驗證 gate：連續 2 週 PHASE-Z 零「未知作者」incident；`fire_receipt` 覆蓋率 100%。
- 收編：refactor_plan_write_boundary_quality WS6、refactor_plan_agent_output_ownership 殘留、error_log D2/D3/D4 終態。

### WS-C 發佈與同步收斂（single gateway + reconcile loop）— P1/P2

| ID | Deliverable | 廢棄面 | 驗證 gate | 優先 |
|---|---|---|---|---|
| C1 | publish_draft `--update` 改走 `publisher._rewrite_feed_entry` + sync_article + 死信記錄（消除三方分岔） | update 直寫路徑；「印提示要人工 sync」 | 改稿後自動比對 feed vs Supabase vs Mirror 三方一致的整合測試 | P1 |
| C2 | 全量對帳排程：`volpred ops feed-sync --apply` 每小時 piggyback（runtime_schedules 新 job）— 所有「寫 feed 未即時推」路徑的收斂網 | — | 排程 receipt + `audit_publish_sync` surfaces 長期歸零 | P1 |
| C3 | 合併雙 sync 引擎：`feed_sync.compute_diff` 為唯一變更偵測（較細：逐欄位+tags+audience）；`sync_full` 降為 caller（保留 memory/risk_forecast/deletes 職責） | `_article_hash` 判準 | 兩引擎對同一 feed 輸出 diff 集合一致的等價測試 → 移除舊判準後 regression | P2 |
| C4 | Mirror 失敗納入同一死信/重試迴圈（與 Supabase 同語意）；drain 同時吃兩類 | Mirror 失敗只 print | 注入 Mirror 失敗 → 死信 → drain 恢復的測試（杜絕「401 一個月」重演） | P2 |
| C5 | lazypack PRIMARY 單一真相裁決：以 2026-07-15 boss directive + memory（Codex primary path）為準 — **codex = PRIMARY、deterministic = FALLBACK、NotebookLM = 第三備援**；更新 publishing.md §4 對齊；`lazypack_render_example_spacex.py` 入 `_legacy/`（落地前先以 git log 覆核 directive 時序） | publishing.md 過期敘述；legacy 範例檔 | 治理文件與 docstring 三處口徑一致（grep 驗證） | P2 |
| C6 | FB 雙發佈收斂單一 CLI：`fb_realchrome_post` + 留言補連結 + `mark_fb_post_status` + supabase push 包成一個入口（互動 session 內一鍵） | 4 工具 8 步手工黏合；`fb_page_post.py`（已 withdrawn）實體移除 | 乾跑模式端到端測試 | P3 |
| C7 | feed.json 多實體清理：陳舊變體檔（feed_2026*.json、.bak_*）歸檔；`storage/feed.json` legacy 併軌評估（merge_feed_files 是否可退役） | 陳舊變體 | 全 repo 只剩 canonical 一份可寫實體 | P3 |

### WS-D 排程與觀測單一化 — P2

| ID | Deliverable | 廢棄面 | 驗證 gate |
|---|---|---|---|
| D1 | liveness 單一定義：`managed=False` job 的活性改讀各自 execution receipt/log；cron_last_run 明文只代表 piggyback jobs（欄位加 scope 註記或拆檔） | 「讀 cron_last_run 判一切活性」的隱含假設 | daily_checkup/dashboard 對 launchd 直跑 job 不再誤報死亡 |
| D2 | 死 lane 退役：`src/volpred/ops/scheduler.py` + `scheduler-tick` CLI + `run_scheduler_tick.sh` + scheduler_state.json 移除；session_crons 過期項清理；`pending_sessions.json` replay 機制裁決（修或廢）；runtime_schedules `cron_jobs` 與 launchctl 現實對齊（volpred-hourly-dispatch spec 標 disabled） | 整條 advisory scheduler lane；過期 session_crons | `runtime_schedules.json` 每條 spec 都能對應到一個可驗證的掛載點（audit script 掛既有 CI） |
| D3 | Legacy 退役 deadline 執行：`cron_hourly_dispatch.sh` 完成 Deliverable-8（bootout + `_legacy/` + retro）；`refactor_plan_cron_dispatch.md` 標 SUPERSEDED 歸檔；single_gateway 的 claim-next 消費 lane 移除；pregate shell 註解改為「刻意 observational」對齊 gate 裁定 | 三處 disabled-but-alive legacy | `_legacy/` README 更新；launchctl 無殘留 spec |
| D4 | alert dedup 收斂：兩 store 明文分工（daemon 60s = 防洪、ops 24h = 防轟炸）併入同一 helper 或文件化為 advisory+authority；alert_dedup.json 769KB 加 retention | 未文件化的雙 store | dedup 行為測試 + retention 後檔案 <100KB |

### WS-E scripts/ 瘦身與歸檔防再堆積 — P2/P3

| ID | Deliverable | 驗證 gate |
|---|---|---|
| E1 | 36 支無引用死碼移除（git 留歷史；`drone_ep*` 8 支、`fix_cjk_charts.py` 等）+ 空 `review_jobs/` 目錄刪除。**排除清單**：6 支僅被 test 引用的 audit_* 是 CI ratchet 受測對象，不刪 | 移除後全量 pytest + CI 綠；引用反查 0 命中 |
| E2 | 40+ 一次性研究/backfill 腳本歸檔 `_legacy/`（含 provenance 註記，比照 2026-07-01 制度） | scripts/ 頂層只剩長駐流程 |
| E3 | 防再堆積 gate：新增 pre-push audit「scripts/ 頂層新檔必須被 schedules/skills/CLI/tests 至少一處引用，否則要求放 `experiments/<id>/` 或 `_legacy/`」（掛既有 audit runner，單一 owner） | 對 E1 清單的 regression：重新引入無引用檔會被擋 |
| E4 | 巨獸拆分（僅動混 concern 者）：check_alerts 的 `run_due_jobs` piggyback 觸發抽成獨立薄入口（alert 裁決與排程分離）；daily_update 的發佈觸發與資料更新解耦；publish_draft 新發路徑收斂進 publisher（update 路徑已由 C1 處理）。phase_z 縮小由 WS-B 帶動，不獨立動 | 拆分前後行為等價測試；行數與 concern 單一化檢查 |

### WS-F PDCA / loop-engineering 閉環補強 — P2

| ID | Deliverable | 驗證 gate |
|---|---|---|
| F1 | Enforcement Layer Map 全面更新（補 fire-receipt / deny_wakeup / read_context_budget / 8 項 deny / 5 git hooks / experiment-artifacts CI / next_tasks vocab CI）+ 新增機械 audit：map 清單 vs `settings.json`+workflows 實況一致性（掛既有 CI，map 過期 = 紅燈） | audit 首跑綠；此後新增 hook 不同步更新 map 會被 CI 擋 |
| F2 | 兌現 `dedup-gate-audit.md:64`：建 `audit_dedup_gate_decisions.py`（block rate >30% / 連續無 pass 黑洞 / 同 arc block≥3 三條件）掛週期排程；或若判定過度設計則修 rule 移除承諾 — 二擇一，不留懸空 | gate 落地 + 對 2026-06-23 黑洞情境的 regression；或 rule 更新 commit |
| F3 | 事故立案機械化：alert/incident 發生時自動產 error_log 候選條目（append-only 草稿區，主線程裁決轉正），dreaming 的 recurring detector 同時讀 alert stream — 解「沒立案的 class 第二次等於第一次」 | 注入同類 alert×2 → detector 能升級的測試 |
| F4 | content_quality_patrol 裁決：盤點 plan 7 項 vs 已落地 4 check（`content_quality.py`）的差集 → 殘項排任務實作或明文縮編 plan；結束 26 天幽靈狀態 | plan 檔案狀態更新 + 殘項進 §7 |
| F5 | 觀察期 deadline 機制：所有 shadow/deprecated/observing 狀態集中登記（`storage/ops/observation_ledger.json`，dreaming detector 讀取，逾期未決策 = breach）— 原則 5 的機械化 | 現存 4 個觀察項全入帳；注入逾期項的 detector 測試 |

### WS-H 互動回報流程（email / Telegram）與派工邏輯優化 — P1/P2（owner 2026-07-20 指定納入）

**終態**：老闆的任何入站指令（Telegram / Gmail）→ 分類 → P1 直達 fire 的延遲 ≤1 分鐘且有 receipt；對老闆的出站回報「一個 cadence 一個 owner」無重複排程；派工決策收斂為 supervisor 內單一 decision pipeline。

| ID | Deliverable | 廢棄面 | 驗證 gate | 優先 |
|---|---|---|---|---|
| H1 | ~~Telegram 接 request_fire~~ **查證後改為驗證項**：急件 lane 已全接通（見 §1.2 P8 撤回紀錄）。H1 縮編為：以端到端測試確認三條 ingress（`ops assign` P1 / gmail / telegram responder 升級的 repo 級 assign）都在 ≤60s 內 fire 或 spawn，缺的情境補進 `test_urgent_task_lane.py` | — | 三條 ingress 的注入測試全綠 | P2 |
| H2 | **出站回報通道職責矩陣**：Telegram = 即時互動回覆 + 逐程序進度（`progress_report.py` 唯一 owner）；email = 週期摘要 + 決策請求 + alert（單一摘要引擎多 view）。合併三班 token 報告（`token_report_daily`/`token_usage_daily_report`/`token_usage_daily` → 一班）；boss_report_4h 與 work_summary_6h 職責重疊裁決（擇一為 owner、另一併入或退役）；矩陣寫入 Enforcement Layer Map（F1 同 commit） | 重複的 token 報告排程 ×2；重疊報告器 | `runtime_schedules.json` 中對老闆的出站 job 每個 cadence 唯一；老闆日收信量實測不升反降 | P2 |
| H3 | **互動 SOP 機械化**：responder「先 reply 再 complete」升級為機械檢查（complete 前必有 reply receipt，比照 fire_receipt 模式）；email 決策信一律附 mailto 快速回覆連結（既有 feedback 規則納入同一 owner） | prose-only 的 responder 紀律 | 注入「未 reply 就 complete」情境被擋的測試 | P2 |
| H4 | **派工決策單一 pipeline**：派工職責現散在 5 檔（supervisor scheduler / continue_task_dispatch / pregate / slot_budget / legacy shell）→ 收斂為 supervisor 內單一 decision pipeline：`continue_task_dispatch.py` 降為純 library（候選計算，不再自帶寫入路徑，與 A1 同步）；pregate 明文 observational（D3）；priority / starvation / cluster budget / burst 的裁決邏輯集中一處、其餘為輸入 | continue_task_dispatch 的獨立寫入與 advisory 分身；分散的裁決點 | 派工決策的單元測試集中在一個模組；`--dry-run` 輸出與實際 fire 決策一致性測試 | P1 |
| H5 | **急件 lane SLA 閉環**：時效性任務（event / trending / user-assigned P1）從入站（Telegram/Gmail/event_jobs）到 fire 的延遲寫入 receipt；dreaming detector 監控 SLA breach（吸收「時效過了價值歸零」原則，讓急件延誤成為可觀測 breach 而非事後發現） | — | SLA 欄位入 receipt schema；注入延誤情境 detector 可見 | P2 |

### WS-G 監控儀器邊界固化 — P3

6 支健康儀器不合併（切面確實不同），但共用 parser 抽成單一 library（`src/volpred/ops/` 下），各儀器只留呈現層；邊界宣言從 docstring 升格到 Enforcement Layer Map。驗證：parser 單元測試 + 6 儀器輸出 regression。

---

## 4. 既有 11 份計畫收編對照表

| 舊 plan | 殘留項 | 去向 |
|---|---|---|
| hourly_dispatch | Deliverable-8 legacy 退役；multi-slot 24h 驗收 | → D3；驗收留原 blocked task `assign_f59976b6` |
| cron_dispatch | 整份已被 hourly_dispatch 取代但未標註 | → D3（標 SUPERSEDED 歸檔） |
| token_ops_waste | WS1a pregate（裁定不翻）；WS5b dual stage-machine；K1709 合併 | → D3（註解對齊裁定）；WS5b → A3/A4；K1709 → A4 自然回收 |
| agent_output_ownership | legacy shell 內舊字串 | → WS-B + D3 |
| write_boundary_quality | WS6 writer 隔離 | → WS-B（主體） |
| single_gateway_task_system | claim-next 觀察中未移除 | → D3 |
| content_quality_patrol | 整份停滯 26 天 | → F4 裁決 |
| git_push_backup | failure fingerprint 細分（非阻斷） | → D4 順帶；不獨立立案 |
| kid_allocation | C in-flight marker 未接；配號入口未全改 | → 併入 A1（writer/入口收斂同一次掃描處理 `reserve_kid` 全面接管） |
| prepublish_content_gate | member_qa 覆蓋缺口（已另補發佈端 gate） | 已閉合；member_qa 三機制權威歸屬明文化 → F1 map 更新時一併寫入 |
| release_layer_deadlock | 真因 C content-supply 未修 | **不屬 ops 重構**，屬內容策略 — 保留原 spec 由 platform_ops lane 消化，本計畫不收 |

另收：project_improvement_status 2026-05-04 計畫的 B3.7 / B4.1-B4.4（host install，唯一需 owner 授權項）→ 併入 D2 執行時以 email 徵求授權。

---

## 5. 執行序（Phase）與任務對映

- **Phase 0 快速止血（即刻）**：A1-hotfix（truncate 寫法）、A2（kill→release + claimed_at 盲點）、H1（Telegram request_fire 接線）、D3-doc（cron_dispatch 標 superseded）— 主線程當場完成或 24h 內
- **Phase 1 狀態機與發佈收斂（本週）**：A1 全量、A3、A4、C1、C2、C4、F1、F2、H4
- **Phase 2 架構收斂（下週）**：WS-B、C3、C5、D1、D2、D4、E1、E2、F3、F4、F5、H2、H3、H5
- **Phase 3 瘦身退役（兩週內）**：C6、C7、D3 全量、E3、E4、WS-G

### 執行模式：獨立重構軌（owner 2026-07-20 糾正後修訂，取代原「入一般排程」設計）

**重構任務不進一般 hourly 派工消化。** 理由：重構對象正是派工機器本身（佇列狀態機／supervisor／派工邏輯），讓排程 agent 改自己的執行機器 = 未隔離的自我改造 — 2026-07-20 11:1x 實證：3 個 hourly agent 同時在共用 main checkout 改 `task_pool_claim.py`／supervisor／publisher，與主線程賽跑（正是 WS-B 要根治的 un-isolated writer 病灶）。

- 所有 `[refactor-master]` 任務一律 `dispatch_lane: "main_thread"`（機械隔離：hourly/Codex claim 看不見），仍留在 next_tasks 供追蹤與 §7 對帳
- 執行 = **主線程專屬 refactor session** 逐 Phase 推進；動到 supervisor / 佇列機器的 WS 在 worktree 隔離做、gate 綠才 merge（WS-B 精神先行自用）；supervisor code 改動靠 selfreload 或 reload script 生效
- 每 WS 收斂時做 Codex review + 線上 Check，才可標 ✅（過程 checkpoint commit 不算完成）
- Phase N+1 任務由 Phase N 收尾時的主線程 enqueue（同樣 main_thread lane，不預先塞爆 queue）

## 6. 驗證 gates 總表（宣告完成的硬條件）

1. 每 WS 的 per-deliverable gate（§3 表內）全綠 + Codex review 通過
2. 全量 pytest + 既有 CI（encoding / silent-fallback / provenance / pytest / tree-clean / experiment-artifacts）綠
3. 廢棄面同 commit 移除驗證：`_legacy/` 化或刪除，無兩套並行
4. 線上 Check：ops_snapshot 的 in_flight 與實際一致；audit_publish_sync surfaces 歸零；PHASE-Z 未知作者兩週零 incident
5. §7 狀態表逐項附 commit hash + 實測證據，才可標 ✅

## 7. 狀態表（canonical — 唯一進度真相）

| 項 | 狀態 | 證據 |
|---|---|---|
| Plan 建立 + 五路稽核 | ✅ 2026-07-20 | 本檔 |
| Phase 0：A1-hotfix（truncate→serialize-first/helper） | ✅ 2026-07-20 | `continue_task_dispatch.py` 修復；pytest 綠 |
| Phase 0：A2a（cleanup claimed_at 盲點 + fallback 判齡） | ✅ 2026-07-20 | `task_pool_claim.py` 修復；2 新測試綠；live 跑 cleanup 自然回收 5 筆殭屍（k1731_armB_rev7_*、assign_5aa9d5f5 等） |
| Phase 0：P8 急件 lane 查證（撤回誤診斷） | ✅ 2026-07-20 | `_request_urgent_fire` 已全接通；enqueue 實測 12/12 `fire_requested: true` |
| Phase 0：D3-doc（cron_dispatch 標 SUPERSEDED） | ✅ 2026-07-20 | `refactor_plan_cron_dispatch.md` 檔頭 |
| Phase 1 任務 enqueue（12 筆 refactor-master 系列） | ✅ 2026-07-20 | A2b/A1a/A1b/A4/C1/C2/H4 = P1；A3/C4/F1/F2/H2 = P2；經 `ops assign` single gateway |
| Phase 1：**A1a next_tasks writer 全量盤點分類** | ✅ 2026-07-20 · commit `pending-phase-z` | `docs/audit_next_tasks_writers.md`：掃到 **44 個 writer 呼叫點 / 33 檔**（印證 §1.3 A5「40+」），分類 **legal 25 / needs_helper 12 / delete 7**。Canonical helper 確認為 `src/volpred/ops/next_tasks.py` 三入口（`write_tasks_to_handle` primitive / `write_tasks_locked` one-shot / `append_next_task` single append gateway）。交叉驗證 `grep -rn next_tasks --include=*.{py,sh,md}` = 1,454 行 / 287 檔，差額 1,410 行逐類歸因（測試 fixture / 敘述性提及 / 唯讀查詢 / 路徑常數 / config 宣告 / 註解），無漏網寫入路徑。已附 A1b 可直接執行的建議動作與 gate 規格 |
| Phase 0：A2b kill→re-pend 接線 | ✅ 2026-07-20 | commit `pending-phase-z`。`health.py` force-kill 成功後呼叫 `task_pool_claim.release_owner_claims()`（canonical helper，owner token 由 `identity.task_claim_owners_for_job()` 依 slot+job 產出，涵蓋 hourly / codex-failover 兩角色）；re-pend 的 task ids 進 hang alert receipt (`repended_tasks`) 與 LOG。task pool 讀寫失敗只記 WARNING，kill 流程照常完成（stale sweep 仍為 backstop）。3 新測試綠：`test_health_kill_repends_the_claim_the_dead_fire_was_holding`、`test_health_kill_repends_codex_failover_claim_for_the_same_slot`、`test_health_kill_completes_even_when_the_task_pool_is_unreadable` → `3 passed`；`tests/test_dispatch_supervisor.py` 全檔 `92 passed`，相鄰 8 檔 `117 passed` |
| Phase 1：**A4 liveness reconciler（宣告 vs 磁碟 vs 進程對帳）** | ✅ 2026-07-20 · commit `pending-phase-z` | `scripts/liveness_reconcile.py`（467 行）+ `scripts/cron_liveness_reconcile.sh` + `config/runtime_schedules.json#liveness_reconcile`（`45 * * * *`，`host_crontab_managed=false` + `piggy_back_enabled=true`，經 `run_due_jobs.py` 分派；wrapper TCC 副本 `~/.volpred/bin/` 已裝且與 repo 版 `diff` 相同）。**判定為兩項死亡證明的 AND**：進程（`dispatch_supervisor.procutil` pid-reuse-safe 指紋）+ 磁碟（worktree 不存在），任一存活即否決，另加 20min 寬限期；re-pend 一律走 canonical `task_pool_claim.release_owner_claims()`，不新增 next_tasks writer（守 A1）。**回歸測試**：`tests/test_liveness_reconcile.py` 注入假 in_flight → `11 passed in 0.30s`。**線上實測（11:35）**：dry-run 判 `in_flight=8 owners=7 detached=2`，`--apply` 釋放 3 筆真殭屍（`K1495_article_general` / `K1718_article_general` owner=`hourly-slot-1-51a8c53b…` 已 completions 且無 worktree、claim age 25.2min；`ci-red-29711772660` owner=`hourly-slot-1-8ac4cbc8…` age 57.8min），receipt 落 `storage/ops/liveness_receipts/liveness_reconcile_20260720T033500+0000.json`；pool 複查兩筆皆 `status=pending owner=-`；**重跑冪等** `in_flight=5 detached=0`，未誤動任何持有 worktree 或寬限期內的 claim（含本班自身 claim）。**已知殘留（設計內，非 bug）**：剩 5 筆 in_flight 的 fire 已死但 worktree 仍在 → 被磁碟否決保留（`feedback_no_research_artifact_loss`），最舊 idle ~25h；這條由 worktree merge/裁決線負責，已另開 followup `assign_3684bd32`（worktree-veto 殘留 in_flight 裁決出口）追蹤，不在 A4 scope 內 |
| Phase 0：**A2c worker 自身 timeout→re-pend 接線（補完 A2b 的另一半）** | ✅ 2026-07-20 · commit `pending PHASE-Z` | **缺口**：A2b 只關了 `health.py` 那半。實務上先觸發的是 `worker._run_one_attempt` 自己的 `Popen.wait(timeout=)`（health 約晚 1s，worker.py docstring 自陳 health 只是 belt-and-suspenders），該路徑贏 CAS 時 A2b 的分支根本不執行 → claim 仍成殭屍。**做法**：helper 抽到新模組 `scripts/dispatch_supervisor/claim_release.py::repend_killed_job_claims()`（**不放 `identity.py`**：該模組刻意零相依、純 token 字串，塞進 task pool writer + 檔鎖會污染所有只要命名慣例的 consumer）；`health.py` 改 import 呼叫（`_repend_killed_job_claims` 保留為 thin wrapper，`_task_pool_claim` re-export 以維持單一 cached module 實例），`worker.py` category=="hang" 分支呼叫**同一個** helper，不新增第二條 next_tasks 寫入路徑（守 A1）。**無條件釋放（不看 CAS 勝負）**，三點理由寫在 worker.py 註解：(1) 走到 category=="hang" 蘊含 `_kill_pgid()` 已回 True（存活會被歸為 `hang_survived`），kill 已確認完成；(2) `release_owner_claims()`（`scripts/task_pool_claim.py:579-582`）只動 status 仍為 `claimed`/`in_progress` **且** `claimed_by` 命中 owner token 的列 → 二次釋放為 no-op，且 owner token 內嵌 job_id（每次 fire 唯一）故不可能搶到後手 fire 的 claim；(3) 若只在贏 CAS 時釋放會留真洞——health 以 `silent_death` / `timeout_unverified` 關掉的 job 並不釋放，此時 `entry is None` 就等於沒人交回。**best-effort**：helper 內部吞掉自身例外（僅 WARNING），解析也移進 try（worker 呼叫點沒有 `check_once` 那層 sibling isolation），`killed_timeout` 落地與 hang alert 一律不受阻；receipt 欄位 `repended_tasks` 也加進 worker 的 hang alert。**新測試 5 支綠**：`test_worker_own_timeout_repends_the_claim_the_dead_fire_was_holding`、`test_worker_own_timeout_repends_codex_failover_claim_for_the_same_slot`、`test_worker_hang_result_and_alert_survive_a_broken_task_pool`、`test_worker_repends_even_when_health_won_the_close`、`test_release_owner_claims_is_idempotent_for_an_already_pending_task` → `5 passed, 92 deselected in 0.38s`。**全檔**：`tests/test_dispatch_supervisor.py` + `tests/test_liveness_reconcile.py` → `108 passed in 17.64s`；加上 `scripts/tests/test_hang_alert_ownership.py` + `tests/test_task_pool_claim.py` → `143 passed in 17.48s`。**順手修**：`test_hang_alert_ownership.py` 自 A2b 起就會打到真 `storage/next_tasks.json` 並被 `CanonicalWriteBlocked`（刻意繼承 BaseException，best-effort handler 吞不掉）擋下（5 紅），補 autouse fixture 把 `NEXT_TASKS` 導到 `tmp_path` |
| **A2b flag#1 裁決：silent_death / identity MISMATCH·DEAD 路徑歸屬** | ✅ 2026-07-20 · 判給 **WS-A4**（`health.py` 明確**不**釋放） | **裁決：`health.py:265-293` 的 silent_death／failure 路徑不得釋放 claim，該類殭屍由 A4 liveness reconciler 回收。** 理由：這條路徑上進程**未經我方擊殺確認**，health 只探 leader pid，無法證明 pgid 內的子孫已死，也**完全沒有磁碟證據**；無條件釋放 = 活著的 worker 的 task 被別人搶走（雙跑）或未合併的 worktree 成果被重做（`feedback_no_research_artifact_loss`）。**A4 確實撿得到，非互推**：`liveness_reconcile.process_verdict()` 對 `IDENTITY_DEAD` / `IDENTITY_MISMATCH` 直接判 `DEAD`（`scripts/liveness_reconcile.py:188-191`，與 health 判 silent_death 用的是同一組 procutil verdict）；health 一旦 `record_completion` 關檔，該 job_id 進 completions ring → `:194-203` 判 DEAD，若連 ring 都輪掉則 `:205-208` fallback 仍判 DEAD——三條分支都落在 DEAD，不存在漏接。真正的釋放條件是 `:333-338` 的 AND：`process==DEAD` **且** worktree 不在磁碟上 **且** claim age ≥ 20min 寬限（`:330`），這正是 health 給不出的兩項證據，也是把裁決放在 A4 而非 health 的理由。排程已上線：`config/runtime_schedules.json#liveness_reconcile`（`45 * * * *`）+ `scripts/cron_liveness_reconcile.sh --apply`。**分工結論**：kill 已確認（worker 自身 timeout / health force-kill 成功）→ 由 A2b+A2c 當場釋放；死亡未確認（silent_death / MISMATCH / DEAD / `timeout_unverified` / `kill_failed_orphan`）→ 一律留給 A4 對帳，health 與 worker 皆不動 |
| Phase 1：**C1 publish_draft `--update` 改走 publisher gateway** | ✅ 2026-07-20 · commit `3ebb40542`（本班驗收，§7 落章 `pending-phase-z`） | `Publisher.rewrite_and_sync_article()`（`publisher.py:2740`）成為 in-place rewrite 的**單一出口**：locked feed 重寫 + Mirror PUT + Supabase sync，任一投影失敗寫死信（`.failed_mirror_syncs.json` / `.failed_supabase_syncs.json`）。`publish_draft.apply_update()`（`publish_draft.py:1420-1450`）改為委派，**舊的直寫 feed 路徑同 commit 移除**（複驗：`grep write_text\|json.dump\|_atomic_write scripts/publish_draft.py` 僅剩 1 個無關的 `json.dumps` 參數序列化，無殘留 feed 寫入 → 無兩套並行）。`--sync-supabase` 語意不變（額外的全量對帳），per-article 投影改為無條件。**整合測試**：`tests/test_publish_draft_update_gateway.py` **6 passed in 0.99s**，涵蓋三方一致（`test_update_fans_out_to_feed_supabase_and_mirror`）+ Supabase 失敗/例外入死信 + Mirror 失敗入死信 + dry-run 不碰投影 + remote-write kill switch 不誤記死信。**Gate 複驗**：`scripts/audit_canonical_writers.py` → `PASS: 0 unguarded, 0 owner-count mismatch, 0 parse error`。**殘留（不在 C1 scope，已建單）**：(1) Mirror 死信只**記錄**未進重試迴圈 —— `runtime_schedules#supabase_sync_drain` 只 drain Supabase 佇列，Mirror 端由 **C4** 負責（lane 內既有任務 `assign_ac3c3aa6`）；(2) `src/volpred/publisher/article_correction.py:apply_article_correction` 是**第三條 in-place 重寫路徑**（自行 atomic 寫 feed + 直呼 `sync_article`，不推 Mirror、不記死信、改以 raise 收場），全 repo `grep` **零 production caller**，但仍登記在 canonical-writers 白名單 → 違反 §2「一 concern 一 owner」，已開 follow-up `assign_bc2ab360` 決定收編進 gateway 或退役 |
| Phase 1：**C1 correction writer 殘留收斂** | ✅ 2026-07-22 · `assign_bc2ab360` | 採收編方案：`article_correction.apply_article_correction()` 只保留 exact-once replacement、errata 與 fail-loud validation，canonical mutation / Mirror / Supabase / dead-letter 全委派 `Publisher.rewrite_and_sync_article()`；從 canonical-writer 白名單移除 correction。gateway 加 `expected_item` compare-and-swap，讀後若有並行改稿便拒絕覆寫；atomic replace 失敗會清除 temp。回歸涵蓋三投影 fan-out、Supabase 失敗死信、並行衝突、atomic cleanup；correction + C1 gateway tests 共 **24 passed**，writer audit 通過 |
| Phase 1：**C2 feed→Supabase 全量對帳排程** | ✅ 2026-07-20 | `runtime_schedules#feed_sync`（`5 * * * *` piggyback）+ `scripts/cron_feed_sync.sh`；**線上實跑**：12:05 exit 0（duration 16s，`storage/logs/cron/feed_sync.log`），cron_last_run 已記 |
| **T05 EffectRequest Notification Tracer（GitHub #11）** | ✅ 2026-07-26 | `fdb2ecc6a`／`e987a6103`／`ebb7214f3` 建立 payload-bound idempotency、transactional outbox 與 fenced settlement；`48356067e`／`9afc3d3d3`／`46e0ddddf` 完成 Gmail Sent exact-byte read-back、worker authority 與 `email.ops_alert` formal caller cutover。2026-07-26 closure audit 的 scoped suite **252 passed**；production 回讀為唯一 owner `operations_core/4`，ownership history `legacy/1 → operations_core/2 → legacy/3 rollback → operations_core/4`，每個 effect 的最新 attempt 為 123 delivered／23 dead-lettered、0 expired started、0 due retry，最新 delivery 為 `work_status=succeeded`／`effect_status=delivered` 且帶 evidence SHA-256 與 Primary Authority ref。Issue #11 五項 acceptance criteria 均有 code、transaction regression 與 live read-back 證據，狀態為 **`root_cause_fixed_and_verified`**。 |
| **T06 Publisher／Sync Effect Delivery（GitHub #14）** | ✅ root_cause_fixed_and_verified 2026-07-27 | 既有 single-article／safe reconcile 已具 payload-bound WorkItem、EffectRequest/outbox、bounded retry、durable dead-letter、owner CAS 與 rollback rehearsal；closure audit 再抓到 Supabase 已收斂時會繞過 Mirror/cache acknowledgement 的 false-delivered 缺口。Formal single／recovery／batch caller現共同要求Supabase row／tag exact read-back、public article exact read-back、hidden 404健康feed佐證及typed cache POST ack；versioned public projection contract（policy SHA `6d125ff3…806888`）由hourly audit與rollback rehearsal強制驗證，失敗／partial batch receipt保留typed refs。Immutable batch recovery只重播原Effect durable payload，production migration `20260726182802`已回讀FORCE RLS與service-role-only RPC，due candidate／runner皆為0。Production owner=`operations_core/8`的live write-boundary effect `effect_owned_publisher_db02df8f575ce1bbe317bafd7bd7e577` attempt 1 delivered且replay不增attempt。最終scoped測試208 passed（另1 skipped／1既有deselect），固定base Matt spec／standards雙審皆PASS。 |
| **T13 Primary Lease／Fencing（GitHub #18）** | 🟡 contained 2026-07-27 | 五步 closure audit推翻先前 umbrella 誤結案：two-Mac receipt只驗 isolated key 且 effect/provider=0；production capability-scoped keys可形成系統級雙主，renew/expiry/reject亦無 append-only receipt。底層 contract現收斂所有 formal builders/adapters至唯一`operations-core-primary`，DB grant trigger拒絕非canonical key；migration`20260727080000`新增acquire/renew/expiry/demote/reject token-redacted ledger、typed rejection與service-role read RPC。Contract／PG17 tests綠，但 migration尚未production read-back，Git／email mutation-boundary canary與legacy writer retirement分屬#24/#46且未完成；因此#18保持OPEN，不得標`root_cause_fixed_and_verified`。 |
| **T05 follow-up：Boss Report owned delivery／canonical read model（GitHub #39）** | 🟡 contained 2026-07-26 | 20:10 production fire 證實 Operations Core scheduler 仍呼叫 legacy direct-SMTP Boss Report，且內容讀 2026-05-19 pseudo-living files。實作已以 canonical generation／activation／cron slot／fire digest 綁 immutable payload 與 owned-email idempotency、共用 durable owner router／terminal replay、wrapper pre-effect owner gate、typed §7＋current task-pool mode read model與小寫 `z` 正規化。跨主機先以 service-role-only RPC 讀 immutable command／terminal receipt；core request 不可被 legacy supersede，明確 legacy rollback 亦由 Primary Authority＋deterministic Message-ID Gmail Sent read-back 防重送；DB owner transfer 與 PA acquire 共用 advisory lock、有效 lease 時 transfer fail closed，legacy 取得 fence 後再核對 request／generation，關閉 transition TOCTOU。Scoped 回歸 **154 案綠**，包含實際本機 PostgreSQL migration／shared-read／terminal-replay／雙 connection advisory-race transaction；production migration `20260726134809` 已部署並回讀 owner／ACL／fence。live acceptance fire 建立 WorkItem／EffectRequest／outbox attempt 1，Gmail Sent exact read-back 為 delivered；同一 fire 重播只回相同 terminal receipt，attempt 仍為 1。報告內容已確認舊 cycle／舊 action／假 warning 消失。只待下一個自然 schedule receipt 與 sustained-clean 回讀，才可升為 `root_cause_fixed_and_verified`。 |
| Program commit 15：**immutable safe reconcile production ownership** | ✅ root_cause_fixed_and_verified 2026-07-26 | Hourly `feed_sync`依`publisher.article.supabase.reconcile` generation在legacy逐篇caller與Operations Core immutable batch之間路由；private payload、WorkItem、EffectRequest/outbox、primary lease與typed settlement由單一adapter擁有。Live rehearsal完成`legacy/1 → operations_core/2 → legacy/3 rollback → operations_core/4`，回讀work/effect/outbox/attempt全acknowledged、local/Supabase 14/14、drift 0。Destructive delete另有獨立owner CAS、durable approval、六表／七edge recovery、atomic compare-delete、exact restore executor與service-role-only atomic restore RPC；`live-20260726-0503`已完成synthetic delete→exact restore→cleanup delete及standing convergence零mismatch。最後的physical two-Mac authority gate亦已由Mac Studio epoch `1`→MacBook Pro exact-next epoch `2`正式通過，DB-clock handoff=`0.162352s`、duplicate/effect/provider全為0、publisher fence全程`operations_core/8`；canonical evidence=`storage/ops/primary_authority_outage_cross_host_latest.json`。 |
| Phase 1：**F1 Enforcement Layer Map 更新 + 一致性 audit 掛 CI** | ✅ 2026-07-20 | map 更新（loop-health-and-dreaming.md +64，commit f23d870c4）+ `scripts/audit_enforcement_map.py`（實跑 OK：10 hooks / 8 deny / 5 CI / 5 git hooks 全對齊）+ CI trigger `tests/test_enforcement_map_audit.py`（騎 pytest.yml，map 過期 = 紅 build）。H2 通道矩陣寫入待 H2 執行時補 |
| Phase 1：**A1b writer 收斂執行 + NEXT-TASKS-ROUTING gate** | ✅ 2026-07-20 | worktree commit `da04993c6` → merge `552edeb5d`；12 needs_helper 全收斂、7 delete 裁決（2 筆 A1a 誤判改保留並記錄）、新 `append_task_record` 單一 append gateway、`annotate` CLI 取代 prompt jq、gate 對舊樹咬 57 violations → 修後 0；main 複驗測試綠 + auditor PASS；skill 修改通知已寄 |
| Phase 1：**H4 設計裁決** | ✅ 2026-07-20 13:1x 主線程核准 decide() 純函數收斂方向；設計覆核發現兩個 dry-run 語意缺陷（ctd `--dry-run` 旗標從未被讀、scheduler dry-run 繞過 pregate）— 已納入實作 Step 1 止血 | `docs/dispatch-decision-pipeline-design.md`；實作 agent 執行中 |
| Phase 1：**H4 派工決策單一 pipeline** | ✅ 2026-07-20 | worktree `5ebbf9837`+`d20ac68ec` → merged；Step1 dry-run 語意修真（ctd `--dry-run` byte-identical 實證、scheduler dry-run 過同一 pregate）；Step2 `dispatch_supervisor/decision.py` 純函數 `decide()`（頻率/純度由 source-audit 測試機械鎖）、dry 與 fire 同輸入同裁決 dataclass-equal；main 複驗 144 tests 綠；4 點偏離皆記錄（含 pregate-enforce 保留待 Q3 裁決） |
| **操作手冊 `docs/ops-manual.md`**（owner 2026-07-20 指定交付物：平台運作＋派工＋email/Telegram 新設計，白話＋範例） | ✅ 初版 2026-07-20；每 Phase 收尾同步更新（驗收清單含本檔） | `docs/ops-manual.md` |
| Phase 1：C4 Mirror 死信重試 | ✅ 2026-07-20 | worktree commit `8dc5ab04b` → merge `661f50ed7`；main 複驗 29 tests 綠；dry-run 注入實證 |
| Phase 1：F2 dedup-gate-audit 兌現 | ✅ 2026-07-20 | worktree commit `bbbaefc89` → merge `262e20934`；main 複驗 71 tests 綠；歷史資料實跑抓到真 warn（10 arc ×4 block） |
| **D6 compute-worker work-conserving 連續運轉 + 有界平行** | ✅ 2026-07-20 | worktree commit `d161229e4` → merged；run-loop + fcntl flock 互斥（crash 即釋放）+ 原子 claim + max_parallel=min(3,cpu//3)（config 可覆寫）；wrapper 經 sync_cron_wrappers 原子安裝、lockstep 綠；**live 實證**：首次 drain 即撿起真 compute job 連續執行。**已知缺口 → D6b**（`assign_5f17c382`，main_thread lane）：SIGTERM 殺 drain loop 會留孤兒 running receipt（本日實測），需 pid-liveness reaper + requeue 兩筆 k741 codex job（等額度） |
| **A3 status/blocked_reason vocab migration** | ✅ 2026-07-20 | worktree `4cbcd54f1` → merged；canonical queue migration + 六鏡像 baseline 27→0/3→0 **同一 commit**（13:30）；validator 0/3077×2 綠；81 tests 綠；原值全保留 |
| **D6b compute stale-running reaper** | ✅ 2026-07-20 | worktree `c817c95fe` → merge `86e142305`；flock-invariant + pid-reuse-safe 指紋五種裁決、孤兒子行程 skip 防護；requeue 收 worker_killed；36+43+107 tests 綠；:15 班 launchd drain 已自然接手 |
| **H2 出站回報收斂** | ✅ 2026-07-20 | worktree `04e03a477` → merged；token 三班→一班（owner=token_report_daily 含落檔收編）、work_summary 併入 boss_report 20:10 日結班並退役（wrapper/_legacy、LaunchAgent bootout、host crontab 殘班修正已執行）；**定期信 ≤7→4 班/日**；通道矩陣入 Layer Map（skill 通知已寄）；merge 後 manifest/policy 26 tests 綠 |
| **CI 紅燈裁定（2026-07-20 12:00/13:00 兩班）** | ✅ 非迴歸 | 6 個紅全屬「重構中間態被 hourly auto-push」（manifest 缺項/writer policy 未註冊/map 時序）；現 HEAD 本地複驗 27 passed 全綠；14:00 班 in-progress 預期綠 |
| Phase 2：**E1E2 scripts 瘦身** | ✅ 2026-07-20 | worktree `a15fba0d7` → merge `0a3e41be2`；removed 13 / archived 43（含 K55/K79 論文源碼依不遺失原則改歸 _legacy 保檔）/ 反查救回 7 支活工具；3789 tests 綠；其列 4 pre-existing 紅在 main 已被先前修復覆蓋（26 passed 複驗）；頂層 285→231 |
| **C3 雙 sync 引擎合併** | ✅ 2026-07-20 | worktree `ecfdfa389` → merge `8b2cffb25`；compute_diff 唯一判準（補 category/details/phase 盲點）；**順手抓到 pre-existing 資料流失 bug**：`details.view_display` seed 被每次 re-sync 清掉 → SERVER_RESIDENT_DETAILS_KEYS 保護落地；線上 dry-run 1576→3 flagged；35 tests 綠。**殘留決策已結案（2026-07-20 17:2x 儀器實測）**：seeder 即時讀 DB = 1575 seeded / 0 needs seeding（73 unseeded 皆凍結後新文屬正常）— C3 估的 257 為候選數非實際流失，無需補種；防 clobber 保護已上線即足 |
| **C3b full-sync acknowledgement cursor** | ✅ 2026-07-25 | Program commit 15 前置 failure injection抓到 `sync_full()` 對 article／memory／risk provider失敗仍推進 mtime／count並回綠，下一輪 unchanged gate會永久跳過未落地 projection。Article現保存 explicit retry slug且失敗不推進 mtime；purge retry綁定 prerequisite write；memory cursor只涵蓋下游 ack的連續 prefix；risk/reconcile失敗統一使 CLI非零。4 RED轉 GREEN，clean tracked snapshot相鄰套件 **31 passed, 1 skipped**。局部根因 `root_cause_fixed_and_verified`；formal EffectRequest/outbox、convergence receipt與rollback仍屬 program commit 15後續。 |
| **C3c hourly feed-sync acknowledgement** | ✅ 2026-07-25 | Failure injection證實 scheduled `feed-sync --apply` 已回 `failed=1`仍 exit 0，cron receipt因此 false-green。External interface新增 aggregate `acknowledged`；apply未明確全數確認即在輸出 JSON evidence後 exit 1，quiet clean維持0。Canonical schedule登記0／1語意，wrapper regression固定 exit propagation；與相鄰套件 **69 passed**，production read-only feed/db=1877/1877、drift=0。局部根因 `root_cause_fixed_and_verified`；formal full-sync outbox ownership與rollback仍屬 program commit 15後續。 |
| **GitGuardian 事件（04e03a477/a0dfd2d）** | ✅ 誤報結案 2026-07-20 | 高熵字串 = wrapper manifest 的 SHA-256 checksum；私有 repo、無機密形狀、.env 從未入 git；`.gitguardian.yaml` 防再誤報；**待老闆**：GG dashboard 點 resolve as FP |
| **F3+F5 閉環訊號源補強** | ✅ 2026-07-20 | worktree `a078af56a` → merge `63060b573`；F3 = alert 三出口記 incident_candidates.jsonl + dreaming `detect_unfiled_incident_class`（立案辨識契約機械可閉合）；F5 = `observation_ledger.py` + `volpred ops observation` CLI + 逾期 breach detector，4 現存觀察項入帳（pregate=permanent、Deliverable-8 07-27、claim-next 07-30、multi-slot 07-21）；main 複驗 92 tests + map audit 全對齊；skill 通知已寄；手冊已同步 |
| **WS-I 工作產物落地保證**（owner 2026-07-20 新指令：杜絕無效工作 — 知識庫/文章/論文必記錄、寫了必發得出、worktree 產物必可溯源） | ✅ 2026-07-20 · commit `pending worktree merge`（worktree agent-a6322efc68ce63e0c）| **機制地圖結論**：三類 loss 的偵測面全數已存在（merge certify gate + reproduce_check/daily_checkup 顧 class 1；release_settings_audit starved 檢查顧 class 2；reclaim dry-run + liveness worktree-veto + daily_checkup worktree_reconcile 顧 class 3），共同缺口 = **偵測有了沒 actuator**。**補的兩個 actuator（皆冪等開單，不疊新儀器）**：(1) `reclaim_stale_worktrees.py --open-tasks` — 每個 held（dirty/unmerged）stale worktree 開一張 `worktree_salvage_<name>` P3 main_thread 裁決單（merge/salvage/discard 三出口明寫在單上）；掛 `runtime_schedules#reclaim_stale_worktrees`（`25 */6 * * *` piggy-back，**絕不帶 --apply**，破壞性動作仍歸主線程）+ `cron_reclaim_stale_worktrees.sh`（sync_cron_wrappers 已 --apply，manifest gate 綠）。(2) `audit_release_settings.py --fix` 對 starved drafts 逐篇開 `starved_draft_<article_id>` P3 修復單（修 gate/手動釋出/retire 三出口），exit 1 從「沒人消費的裁決」變成有出口的 block。**盤點實測**：stale worktrees=16（held 16；unmerged commits 最多 8、最久 idle 138h）；k1380 有效 results 困在 agent-a6325a478bff05509 未提交、main 只有 INVALID 版 = class 3 直接餵 class 1 的活案例；code-without-results 169 中 144 為 2026-04 舊帳、19 為 2026-07-02 搬 repo touch、真近期僅 3（K1694/k259/k1380，其中 k1380 即 worktree 擱淺）→ class 1 增量已被 forward ratchet 擋住，存量歸 kb_backfill 線，不另開 169 張單；mile_47c4bc3e 已於 07-20 06:02 released（skips=20 后自然解），當下 starved=0。**E2E 實測**：以真實 16-worktree population 對 scratch queue 跑 actuator → 開 16 單、重跑 0 新單（冪等）；`tests/test_worktree_salvage_actuator.py` 6 passed（含 append 失敗必 loud + 單一失敗不擋全掃）；相鄰回歸 `test_audit_release_settings`+`test_audit_release_cadence`+`test_liveness_reconcile`+`test_stale_reclaim` 23 passed；schedule/wrapper gates（runtime_schedules/cron_wrapper_manifest/cutover_orphans/run_due_jobs/install_host_crontab）47+11 passed；silent-fallback strict new=0。**死局風險 gate 清單（對照 owner 新規「block 型 gate 必須有出口」）**：(a) merge certify 拒併 + reclaim 拒刪 + 無人開審 = 原三方死鎖 → 本次 salvage 單即出口；(b) starved exit 1 無消費者 → starved_draft 單即出口；(c) reclaim「保留待人工裁決」無裁決佇列 → 同 (a)；(d) 殘留：kb_backfill 降級的 UNVERIFIED（PRIORITY_UNVERIFIED 226）無 re-review 排程出口，屬 class 1 存量問題，留給 kb_backfill/review 線裁決，未在本 WS 疊機制。**與 assign_3684bd32 的關係**：該單是 batch 級裁決（A4 殘留 5 筆）；本 actuator 是同 class 的常態化 per-worktree 出口，主線程收割時可引用 salvage 單收掉 batch 單 |
| **D2+D4 死 lane 退役 + alert dedup 收斂** | ✅ 2026-07-20 | worktree 3 commits → merge `36ddd6a7b`；advisory scheduler lane 全退役（5 檔 + 全 reader 修 + 第二隻孤兒 agent_cli_health）；過期 session_cron 清、hourly-dispatch spec 標 retired；dedup 雙層明文分工 + 30 天 retention（**實證** prune 773KB→414KB）；433 targeted tests 綠；退役 state 檔已清；skill 通知已寄 |
| **C5+D1 lazypack 裁決 + 活性單一定義** | ✅ 2026-07-20 | 2 commits → merged；C5 依 git 時序證據（boss directive `38ad605f8`）裁定 codex=PRIMARY 三層鏈，6 處矛盾口徑全統一 + legacy 範例歸檔；D1 = `job_liveness()` 單一判活入口，5 個 reader（含老闆 dashboard 誤判出處）全改 helper，**線上實測** daily_update 誤判死 3 個月已修復；34+130 tests 綠；skill/rule 通知已寄 |
| **WS-B producer-scoped isolation（Issue #43 / T35）** | ✅ `root_cause_fixed_and_verified` 2026-07-27 | 原 07-20 試點已升級為 production enforce：mutating lane 只能 isolated-or-requeued，shared-main fallback 已移除；task/session/declared paths 在 admission 綁定，producer OS sandbox 不可改 common Git metadata、canonical state 或讀取外部權限，machine finalizer 單獨持有 exact-path commit、candidate-SHA gate、main-base CAS 與 durable settlement。失敗注入涵蓋雙 slot、同路徑衝突、pre-dirty、CAS lost、stale gate、worker crash、restart orphan及 admission/settlement crash。Live canary job `80f1563b…` 只落地 `docs/ops/issue43_live_canary.md`，commit `296aabac0`；receipts `751cdf01… → dd8e3614… → 38b6fe70… → 0b19918a… → c256addc…`，queue 回讀 succeeded。Canary 另抓出 sandbox log FD、dispatch env 與 synthetic-HOME auth 三個部署缺陷，已由 `6893fb285`、`5b1b8b979` 底層修正並以 326 tests + live replay 驗證。舊 PHASE-Z recognizer 退役仍由後續 legacy-retirement ticket 負責，不以本 slice 冒充全計畫結案。 |
| **D5 DB 入庫驗證常設化**（owner「抓完數據要確認資料庫正確存入」） | ✅ 2026-07-20 | worktree `eecf3489f` → merge `732cf232f`；兩 stripped 欄位裁決 local-only（四點證據）非流失；線上比對 market_daily/paper_trades **零缺口**；daily_checkup 新 db_landing sub-check（落後=finding+自動 P1 修復單+正式重推 CLI）；12 tests 綠。插曲：合併兩度被 main WIP 擋 — 根因是 weekend 查證 agent 的 commit 被 silent-fallback gate 拒但回報宣稱已修，主線程補註記收掉（「宣稱已修但 commit 被 gate 擋」回報縫隙列觀察） |
| **G2 高頻查詢儀器化**（owner「現在做」） | ✅ 2026-07-20 | worktree `3b8ff854b` → merge `1a8ca3e1b`；ops_snapshot 六子查詢（--task/--article/--job/--worktrees/--receipts/--queue，皆 <2KB 有 size gate 測試）取代 ad-hoc jq/grep（該類今日實測 237K tokens，預估壓 60-90%）；消費端 prompt/context-hygiene rule/手冊速查表全改指儀器；13+18 tests 綠；rule 通知已寄 |
| **H2b token 報表 bash 指令大類拆分** | ✅ 2026-07-20 | merge `4300049a5`；日報+email 新增 Bash 子表（大類×次數×tokens×佔比 + uv python 按腳本細分）；當日實測 top：jq/grep 36.6% > python heredoc 21.3% > 檔案系統 13.5% > git 11.9%；8 tests 綠 |
| **PHASE-Z 死結重設計 + lazypack 發佈自癒鏈**（owner 07-20 晚間「立刻重新設計」＋「換免費路徑」） | ✅ 2026-07-20 | 三張結構單：(1) trusted-gate **拆批**（agent `37b72a5f4` + 主線程 review-lane 首戰 `c7caed63c`）— gate 檔單獨保留待審、其餘照常提交，candidate_gate_self_modification 一檔連坐 24 檔的死局形狀消失；(2) **hot machine-state 不 pin** 進 failed-closeout receipt + 舊 receipt 靜默 drain（`47c0ee002`，2 regression tests）—「放棄認領」孤兒警報類根絕（根因：pin 了每小時被十幾個 daemon 改寫的檔案，fingerprint 100% 必 drift）；(3) **lazypack 三層鏈重建**（worktree 4 commits → merge `d115cd6e4`）：deterministic 機械自我修復 ≤3 輪（fa098fc8 真實事故 plan round-2 全綠、llm_calls=0）+ agy 免費中間層（codex quota fast-skip，`[FAILURE_CLASS]` marker）+ compute-kind quota backoff 收編既有 `_requeue_quota_blocked` + 鏈終敗自動開 P1 修復單。**SELF_REMEDIATING 真實性 gate（幻覺 class 關閉）**：4 條稽核 2 條為假 — lazypack retry 做成真的（check_alerts→`requeue-stranded` 冪等、attempt≤3）、series_registry 降級為建任務；結構升級 `{claim, owner}` + `tests/test_self_remediating_owners.py` 機械驗證 owner 存在且在 email 前執行。main 複驗 45+189 targeted tests 綠。**實戰驗證**：requeue-stranded 首跑救回 fa098fc8（-r2）；兩篇 plan-less 草稿（mile_d26308ba↔K1495 / mile_fa57f77d↔K1718）agent 補 evidence-bound plans → deterministic 4+4 panels 全綠已裝上 synced，release 死結解除。附帶：3 筆 silent-fallback 修本體非塞 baseline、pregate main-level 測試 hermetic 化（`519a26d65`）、foreign incident assign_a8ae4225 收單降載解除 |
| **Worker DOA 偵測重設計（3-strike）**（owner 07-21 凌晨「徹底重構不要修補」） | ✅ 2026-07-21 | `5e36d1720`；真根因 = CLI 把 fatal 留在行程內、死時才 flush（六個 incident log mtime==kill 時間），主 log 活體期間 0 bytes = 通道無資訊，11:48 的 marker probe 是 patch-on-wrong-model（00:07 第六殺實證盲）。重設計：debug sidecar 每 attempt 必開、以 sidecar 成長為正向活性訊號 — 啟動窗內凍結（180s 零 bytes 或 120s 窗內凍結 + 240s 無成長）= DOA 秒級回收 + claim 當場回池 + transient retry；啟動窗後才安靜（長 tool call）永不誤殺。hang 警報改報 started_at 起算的實際時長（原「50min cap」文案對每次事故都是假的 — 同 truth-gate 原則）。16+16+18 targeted tests 綠（五形狀 fake-clock pins + argv sidecar invariant） |
| **派工優先序三刀 + 外部訊號誤報**（owner 07-21「telegram/email 任務阻塞要重構」＋「你自己看看問題有多大」） | ✅ 2026-07-21 | 病根實測：33 P1 僅 8 張 boss 來源、選擇端未接 task_urgency lane（急件 fire 醒來仍做餓最久的系統 P1）。三刀（worktree 4 commits → merge `20ba96778`）：R1 選擇端 lane 排序（urgent FIFO → time-critical type-only → 其餘原邏輯；餓死 reserve 只在剩餘 slots 運作，機械不可逐出 lane head；無 lane 任務時與舊排序 byte-identical）；R2 admission 夾制（機器來源 P1 → P2 + `priority_capped_from`，判定唯一 owner=task_urgency，只 clamp 不 block 遵守 pool_pressure 邊界）；R3 存量遷移實跑 **25 夾 / 8 保**；R4 snapshot 加 `urgent_pending`/`main_thread_inbox`。加收 8 張「工作早完成、單未收」的 refactor-master 殭屍 P1（§7 逐條證據）→ **P1 pending 歸零**（38→0），boss 新急件=全池唯一 P1。同日：外部 SIGTERM 誤報 hang CRITICAL 根治（`23b8063de`，raw signal exit 依 sentinel 單源原則必為外部 → external_signal 類：claim 退回 + 誠實 WARN 6h 去重 + 歸因 receipt）；CI 紅燈確認綠（75a597735 → run 29805658287 群全 success）；13:0x 擱淺的 pool_pressure writer 接線裁決落地（`f69fc96f4`）。106+134+259 targeted tests 綠。已知漏網（agent 盤點，屬增量、R3 重跑會夾平）：check_alerts CI-red P1、drought emergency 直寫、starved promote — 收編 gateway 屬下一刀 |
| **Incident-lifecycle P1-P5 + worktree 零殘留 + batch-drain**（owner 07-21「徹底重構完整」＋「worktree 不要殘留」＋「一班跑多個任務」） | ✅ 2026-07-21 | (1) incident 一等公民（merge `883903a96`，4 commits）：獨立 store、計數永不歸零、同根因多實例一張、G1-G7 七條機械 gate 全過、24h 全域開單上限（**上線 2 小時即實戰咬住第一張超額單** — G6 有效實證）、machine_self 不進自動修復迴圈、舊 episode 機械 -550 行；main 複驗 128+399 tests。(2) **17 張 stale worktree 全清運**：2 收割合併、13 checkpoint 進 branch 後移除（experiment certify gate 擋 = 設計行為）、2 走 plumbing quarantine ref（hook 免疫、同 PHASE-Z 模式）— 零 --force、零資料損失（bytes 全存 branch/ref），殘餘收割收斂為 1 個 `worktree_unmerged` incident（15 instances）+ 1 張 aggregate 裁決單。(3) P5 收斂：19 salvage + 17 wsb + 1 internal 單全收，pool 190→138、P1=0、main_thread_inbox 27→0。(4) **batch-drain**（`11fc93e9b`）：每班連續消化任務到預算用盡（≥12 分鐘就接下一張），CLAUDE.md dispatch 段同步。教訓補記：P5 driver 曾用 capture_output 吞掉 annotate 拒絕留下 18 張 stale claim — annotate 的 lifecycle-field guard 正確擋了我，己身也要守 no-silent-fallback |
| Program commit 15：**destructive delete production owner／approval／projection** | ✅ 2026-07-26 | 獨立family `publisher.article.supabase.delete`；generation-CAS owner、private WorkItem/EffectRequest/outbox、durable scope approval、attempt-bound provider及transaction-fenced compare-delete已部署。Live ACL/RLS回讀、approval record→read→revoke、六表candidate read-back及`legacy/1 → operations_core/2 → legacy/3 rollback`皆通過；`live-20260726-0503`再完成兩個獨立delete effects、中間exact restore與standing convergence零mismatch。此slice為`root_cause_fixed_and_verified`；physical two-Mac receipt pair亦已於2026-07-26完成。 |
| Program commit 15：**destructive exact restore execution contract** | 🟡 contained 2026-07-25（contract slice ✅） | Recovery consumer驗exact SHA/canonical JSONL/六表identity，全批preflight只接受absent或exact；mutation authority緊貼atomic `restore_batch`，完成後逐candidate exact typed read-back，收斂replay零write。相鄰157 tests綠、零remote mutation。此contract slice `root_cause_fixed_and_verified`；production service-role restore projection與manual live delete→restore→convergence仍缺，umbrella維持`contained`。 |
| Program commit 15：**destructive production atomic restore projection** | ✅ 2026-07-26 | `SupabasePublisherArticleDeleteRestoreProjection`＋service-role-only batch RPC已部署；七edge catalog／row shape／全批absent-exact preflight後依parent→六child恢復，relation雙edge去重，exact post-readback，例外全批rollback，replay零write。隔離PG17 6案（含scope drift、nullable child binding與mid-batch failure）通過；production migrations `20260725020432`＋forward-only NULL-safe wrapper `20260725020935`與owner／ACL／14 RLS policies已回讀，舊v1不對service role開放。`live-20260726-0503`已實際exact restore `1/1`並以cleanup與standing convergence回讀；此slice為`root_cause_fixed_and_verified`，physical two-Mac receipt pair亦已於2026-07-26完成。 |
| **T08 Scheduler Shadow Engine** | ✅ implementation accepted 2026-07-26 | Immutable fire key、activation boundary、catch-up、fenced lease、retry／timeout／terminal receipt、shadow comparator 與 machine-readable parity report 已落地；自然 fire、duplicate suppression、rollback rehearsal 與 no-early-fire regression 均有 live evidence。 |
| **T09 Scheduler Ownership Cutover** | 🟡 live / contained 2026-07-26 | 使用者明確授權正式上線後，`mode=active` 將 49/49 executable jobs 轉給單一 Operations Core daemon；host VolPred cron=0、legacy per-job LaunchAgents=0、owner audit 0 conflict。active 後第一個自然 fire attempt 1 exit 0。正式 ownership 已切換，但 sustained-clean 長窗尚未完成，故 ticket 不宣稱五步結案。 |
| **Session Cron retirement** | ✅ 2026-07-26 | `session_crons.items=[]`、歷史 spec 保存在 `retired_items`；`run_due_jobs` 不再新增 pending session intents。knowledge index 補成 executable core job，其餘舊 prompt 有 explicit replacement mapping。 |
| 其餘 | ⏳ 依 §5，Phase N 收尾時登記 GitHub Issue（direct execution 期間禁止新增 legacy next_tasks identity） | — |
