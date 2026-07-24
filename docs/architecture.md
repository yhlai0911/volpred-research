# 系統架構

> **已核可的目標架構（2026-07-23）**
> 見 `docs/platform_optimization_program_2026_07.md` 與 `docs/adr/` 下四份 accepted ADR。
> 本檔以下仍描述 live/current architecture；只有某項能力完成 shadow、cutover、read-back
> 與 rollback gate 後，才能把現況段落改寫成新架構。不得從目標文件推定 live owner 已切換。

> **臨時 direct-execution cutover（2026-07-23 20:49 台灣時間）**
> 老闆指示暫停 legacy task pool；live mode receipt 在
> `storage/ops/task_pool_mode.json`。`volpred.ops.task_pool_mode` 於 canonical
> `next_tasks` 最低寫入 seam 禁止新增 task id，`task_pool_claim.py claim` 同步
> fail closed；既有 task 仍可 complete／移除。進入模式必先在同一把 queue lock
> 內產生逐位元備份並 read-back，回復只能用 receipt 綁定的
> `scripts/task_pool_control.py restore`，且 live pool 必須為空。所有 owner mutation
> 都必須先由 `status` 取得 `state_sha256`，再以 `--expected-state-sha256` 傳回；
> transition 在 queue `LOCK_EX` 內對同一份 state bytes 做 compare-and-set，過期
> operator／process 一律 fail closed；`enter-direct` 只接受 absent 或 disabled
> `queued_execution` source state，不能用最新 SHA 重入並替換 rollback receipt。
> canonical queue 缺失時也不會由 transition 自動 materialize 成合法空池。這是 legacy pool
> 的可回復 containment，不代表 Work Coordinator／Change Delivery／殘留收斂已
> 完成正式 ownership cutover；整體 Phase 1 仍依
> `docs/platform_optimization_program_2026_07.md` 的 shadow 與七天 gate 推進。
>
> Restore 採 durable two-phase transaction：先在同一把 queue lock 內把 owner state
> 寫成 `enabled=true, mode=restore_in_progress`，再把 receipt 綁定的 backup exact
> bytes 寫回並 fsync/read-back，最後才切成 disabled `queued_execution`。Active、
> prepared 與 restored receipt 都保留同一個 resolved `queue_path`；restore／reconcile
> caller 指向不同 queue 時，會在任何 queue/state mutation 前 fail closed。因此 process
> 在 queue write 前、寫到一半或 write 後 crash，admission／claim 都仍保持關閉；
> operator 由 `status` 取得新的 `state_sha256` 後，以原 backup 參數重跑 `restore`
> 即可冪等續作。State atomic replace 在 rename 後另 fsync parent directory，確保
> prepared marker 先於 queue mutation durable；即使 queue 只留下 partial JSON，
> `status` 仍回傳 state identity，並以 `queue_readable=false`／`queue_error` 明示降級。
> 自動 handoff 在同一把 queue `LOCK_SH` 內讀 owner state 與 queue bytes，避免把
> partial queue 配到較新的 final state；會把 restore 狀態標為
> `RESTORE TRANSACTION：IN PROGRESS`。即使 state 顯示 queued execution，只要 queue
> snapshot 不可讀，也改標 `TASK POOL SNAPSHOT：UNREADABLE`，不輸出 claim、refill
> 或空池 fallback。Owner state 只有「檔案不存在」可視為預設 queued；現存但
> JSON／UTF-8 損壞、root 非 object、欄位型別錯誤或 enabled mode 不受支援時，同樣
> 視為 unreadable 並 fail closed。
>
> Queue 與 owner state 也是單一 identity：state 必須等於「resolved queue parent
> `/ops/task_pool_mode.json`」。CLI 雖保留 `--queue`／`--state` 供測試與維運，但
> enter/reconcile/restore/status 都先驗證 pair；detached state、路徑 typo 或 symlink
> alias 自建的 `alias/ops` state 會在 backup、clear、queue write 前拒絕。Symlink queue
> 一律在 seam 入口 resolve 一次到真實 queue，且真實 basename 必須是
> `next_tasks.json`；state pairing、open、receipt 與 read-back 全沿用該固定 path。
> Restore 的 mutation、fsync 與 exact-byte read-back 使用同一 locked binary fd，
> alias 在 transaction 中途 retarget 也不能把驗證或寫入導向另一個 inode。

> **Work Coordinator legacy projection contract（2026-07-24，pre-cutover）**
> `volpred.ops.work_projection.project_legacy_next_tasks()` 已能把 caller 提供的完整
> `WorkSnapshot` 轉成 deterministic、hash-addressed、detached 的 legacy
> `next_tasks` read model；它保留 row count、priority、claim owner／lease、
> parent、deadline、approval 與 terminal disposition，並以既有
> `LegacySnapshotImporter` 對輸出做相容性回讀，任何 legacy consumer 無法表示的
> provenance／lifecycle／identity 都 fail closed。此 module 沒有 filesystem／database
> lookup、canonical writer 或 apply 模式；`read()` 每次回傳 detached copy，caller
> mutation 不會改變 Work Coordinator snapshot。它只是正式 cutover 前的 projection
> interface capability，尚未把 `storage/next_tasks.json` 接到新 owner，也未放行 enqueue、
> claim、complete caller 或完成 live rollback rehearsal；因此 current owner 與上方
> direct-execution containment 不變。

> **Work Coordinator cutover preflight contract（2026-07-24，pre-cutover）**
> `volpred.ops.work_cutover.prepare_work_ownership_cutover()` 直接從 immutable replay
> receipts 用 trusted wall clock 重跑七日 assessment，並從同一次 owner-state byte
> snapshot 取得 mode 與 CAS SHA。Queue path 固定為 repo canonical
> `storage/next_tasks.json`，paired state 由 queue path 唯一衍生；兩者在 shared queue
> lock 內取樣。Caller 的三來源 mappings 在 seam 入口先 canonicalize 一次並解碼成
> private snapshot，後續 queue equality／import／identity 只讀該 frozen generation。
> Raw legacy bytes 由 seam 自行 decode、計算 SHA
> 並重建 importer report。只有 import 無 reconciliation issue，且 staged projection 的 row
> identity／priority／claim ownership／parent／deadline／terminal disposition 與
> import 完全一致時才產生 immutable、hash-addressed cutover manifest。Projection
> schema 必須精確等於 production `next-tasks-read-projection.v1`；未知 schema
> 即使 payload bytes 相同也 fail closed。Row count／SHA 由 decoded payload 重算，
> 不信任 caller metadata。Manifest v2
> 同時綁定 raw legacy snapshot SHA、assessment SHA、import report SHA、projection
> schema／SHA 與兩側 row count；assessment 的 receipt-set digest 與最後 snapshot identity
> 必須等於本次完整三來源 cutover snapshot。即使兩側 active claim 欄位完全一致，
> `claimed`／`running` legacy row 仍不能產生 manifest：legacy worker 持有的 lease
> token 不在 compatibility projection 中，ownership transaction 無法無損移交該寫入權，
> 所以正式切換必須在零 active lease 的 quiescent queue 執行。任何 drift 或未排空 lease
> 都在 mutation 前 fail closed。此 seam
> 沒有 apply／writer 能力，live 仍為 `direct_execution` 且 observation count 為 0；
> 它不等於 cutover 核可，也無法用手造 assessment／hash 繞過七日真實證據。

> **Change Delivery commit-authority contract（2026-07-24，shadow）**
> private `GitCommitActuator` 在呼叫 canonical Git writer 前，必須以完整 write-intent
> SHA-256 同時取得有效 WorkLease 與 Primary Authority grant；stale token、authority
> unavailable、grant 與 intent 不符皆 fail closed。Git argv 與 receipt 都不保存 raw
> token，receipt 只保留 request hash 與兩個 authority reference，之後仍回讀 commit
> parent、exact paths 與 blob hashes。這只是 program commit 10 的 actuator-side
> interface；後續 PostgreSQL authority 與 settlement 狀態見下方，正式 caller 與
> Git ownership 仍未切換。
>
> **Change Delivery durable commit-grant follow-up（2026-07-24，shadow）**
> private `PostgresCommitAuthority` 會在跨入 database seam 前重算完整 write-intent
> identity。單一 PostgreSQL transaction 鎖定並核對 exact running WorkItem version、
> 未過期 WorkLease token 與 database-clock Primary Authority lease，再保存一筆只含
> token-redacted WorkLease／Primary Authority refs 的 immutable grant。等價 replay
> 回同一 grant；stale work／primary fence 或 forged request digest 都在 Git mutation
> 前 fail closed。Grant table FORCE RLS，worker 只能呼叫 named function，PUBLIC 無
> table read 或 function execute 權限。
>
> 此 migration 目前只有 clean-replay evidence，未套用 live。
>
> **Change Delivery post-commit settlement follow-up（2026-07-24，shadow）**
> `ChangeDelivery.land()` 現在把 immutable ChangeSet、authority-fenced
> `GitCommitActuator` 與 durable `PostgresCommitSettlement` 收進同一 deep-module
> workflow。Git commit read-back 後，`settle_commit_write` 再次核對 exact running
> WorkItem／WorkLease 與 database-clock Primary Authority，才保存 token-redacted
> `change-delivery-receipt.v1`；DB 暫時失敗的 retry 只續做 settlement，不會重複
> commit。Receipt FORCE RLS，PUBLIC 無存取，worker 只有 named-function execute。
> `commit-actuation.v1.observed_at` 也是 settlement identity：`land()` 會在進入
> durable adapter 前要求它可解析且帶 UTC offset；非法或 naive wall-clock 不得交由
> PostgreSQL session timezone 猜測，也不得先把 ChangeSet 標成 `commit_unsettled`。
>
> **Change Delivery durable lifecycle follow-up（2026-07-24，shadow）**
> `ChangeDelivery` 的 external interface 不變，proposal、token-redacted actuation
> checkpoint 與 final receipt 改由 private `ChangeSetStore` seam 保存。
> `PostgresChangeSetStore` 以三個 named transaction 實作 immutable create、
> `commit_unsettled` checkpoint 與 landed receipt linkage；另一個 in-memory adapter
> 保留 interface tests。程序若在 checkpoint 已提交後、settlement 前中斷，新 instance
> 會讀回 actuation，只續做冪等 settlement，不再呼叫 Git writer。Raw WorkLease／
> Primary Authority token 不落表，只保存 payload-bound landing-command SHA-256。
>
> **Change Delivery lost-return recovery follow-up（2026-07-24，shadow）**
> `GitCommitActuator` 在每次 retry 仍先重新取得 WorkLease／Primary Authority grant；
> 若 canonical HEAD 已離開 expected parent，actuator 不再立刻把所有情況都視為未知
> stale write。它只檢查 expected parent 後的第一個 first-parent commit，並要求
> parent、完整 message、exact path set 與每個 committed blob SHA-256 全部等於原
> authority-bound command，才由 Git committer 的 timezone-aware timestamp 重建
> `commit-actuation.v1`。任何差異仍 fail closed，且不呼叫 writer。這讓程序在 Git
> commit 成功、receipt return／ChangeSet checkpoint 前中斷後，可於 restart 續進
> checkpoint 與 settlement，不會再建立第二個 commit；之後已有其他 mainline commit
> 也可從歷史第一個 child 精確回讀。
> 實際 Git commit message 另由 actuator 加上
> `Volpred-Commit-Authority-Request: <sha256>` trailer；digest 是同一次
> WorkLease／Primary Authority authorize request 的完整 identity，並包含原 message、
> actor、owner generation、parent、paths 與 content hashes。Post-write read-back
> 與 lost-return recovery 都要求這個 trailer 精確匹配；只有
> bytes／paths／mode／人類可見 message 相同、但未經本次 authority request 的
> first-child commit 不再能冒充 actuator 成果。Raw fencing token 不寫入 Git object。
>
> 以上 migrations 均未部署 live；2026-07-24 唯讀 catalog 回讀 proposal／grant／
> settlement tables/functions 皆不存在。Lost-return crash window 已由 exact Git
> read-back recovery 在 shadow interface 封閉。
>
> **Candidate workspace materialization follow-up（2026-07-24，shadow）**
> `ChangeDelivery.land()` 將 proposal 的 linked `workspace_ref` 傳給 canonical Git
> writer；writer 在同一把 common-dir lease 內重驗 source HEAD／clean index／完整
> dirty set／content hashes，再 materialize、stage、commit 與回讀 commit object。
> Canonical exact paths 若不是 base bytes 或可驗證的 candidate residue便拒絕；一般
> 失敗會還原原 bytes，kill 後 exact residue可冪等續作。這封閉 production
> materializer 的 overwrite／rollback seam，但 formal caller、live migration、
> ownership cutover 與正式 rollback rehearsal仍未完成，因此不改變目前 Git ownership。
> ChangeSet v1 的 immutable identity 只包含 path 與 blob SHA-256，不包含 Git tree
> mode；因此此 bounded slice 明確禁止 mode transition：tracked regular file 必須保留
> base 的 `100644`／`100755`，new file 固定為 `100644`。Proposal validation、
> lease 內 materialization 與 post-commit／lost-return read-back 都套用同一規則，
> 不讓相同 proposal digest 落成不同 tree。
>
> **Formal Work Coordinator caller 與 Git owner generation（2026-07-24，live schema／legacy owner）**
> `OwnedChangeDelivery.deliver()` 是 formal caller 的窄入口：先讀 private PostgreSQL
> `git.commit` owner row，只有 `operations_core` 的 current generation 才可 propose；
> 同一 generation 會進入 landing-command digest、authority request／grant、
> actuation checkpoint、settlement digest 與 final receipt。授權及 settlement
> transactions 都再次鎖定並核對 owner generation，消除 caller read 與 Git write
> 之間的 TOCTOU。舊的無 owner 參數 RPC 已對 worker 失權。
>
> Settlement 寫入 immutable delivery receipt 後，會在同一 PostgreSQL transaction
> 呼叫 `complete_work()`；formal caller 最後回讀唯一 `succeeded` WorkItem，並核對
> version、settlement ref、summary、finished time 與 claim clearing。Owner transfer
> 是 approver-only CAS；有未 settlement grant 或 `commit_unsettled` ChangeSet 時不得
> rollback。PG17 clean migration replay 與臨時 canonical repo／linked worktree 的
> end-to-end shadow 已完成 operations_core generation 2 commit → durable receipt／
> Work completion → legacy generation 3 rollback → operations_core generation 4
> re-cutover。2026-07-24 已把 commit authority、settlement、owner generation、
> ChangeSet store 與 receipt-FK covering index 五筆 private migrations 套到 production；
> live read-back 為 `git.commit=legacy/1`、grant／receipt／ChangeSet 全為 0，worker
> 對舊無 owner overload 已失權，全部新表 FORCE RLS 且 PUBLIC 無 read／execute。
> Schema deployment 不等於 ownership cutover；production Git writer 仍由 legacy
> path 持有，只有另一次 approver CAS 才能切換。
>
> **Change Delivery service-role operator seam（2026-07-24，live read／legacy owner）**
> Production 不能靠 Management SQL 的 session role 暗中繞過 private RLS。新增
> `volpred_read_commit_owner`／`volpred_transfer_commit_owner` 兩個 public
> PostgREST RPC；它們只委派既有 private read／CAS transaction，owner 是
> `volpred_ops_definer`、`SECURITY DEFINER` 且 `search_path=''`，只有
> `service_role` 可執行，anon／authenticated／PUBLIC 全拒，service role 仍不能直接
> SELECT owner tables。`SupabaseCommitOwnerStore` 是 production HTTP adapter，會嚴格
> 驗證 schema、capability、owner generation 與 timezone-aware timestamp，CAS 衝突
> 轉成 typed `CommitOwnershipLost`。Live migration receipt 是
> `20260724074117 operations_core_commit_ownership_rpc`；RPC 回讀仍為
> `git.commit=legacy/1`，本 checkpoint 沒有執行 ownership transfer。完整 production
> Change Delivery caller 尚未完整接上 service-role adapters，故不得只因 owner RPC
> 可用便切換 Git ownership。
>
> **ChangeSet service-role lifecycle seam（2026-07-24，live read／legacy owner）**
> `SupabaseChangeSetStore` 將 immutable create、by-id／by-idempotency read、
> actuation checkpoint 與 landed linkage 對應到五個 narrow public RPC。RPC 只委派
> private `volpred_ops` transaction／token-redacted read view；functions 由
> `volpred_ops_definer` 持有、空 `search_path` 且只授權 service role，caller 仍無
> ChangeSet table／view SELECT。Owner 與 ChangeSet adapter 共用一個 service-role
> transport，禁止 publishable-key fallback。PG17 clean replay、migration idempotence、
> ACL 與 service-role create/read 已通過；production receipt 是
> `20260724081714 operations_core_change_set_rpc`。Live catalog 的五項 ACL／hardening
> predicates 全 true，HTTP missing lookup 精確回傳 null，owner 仍為 `legacy/1` 且
> ChangeSet count 為 0。Settlement／Work read model 的 HTTP adapters 仍缺，因此
> 不能執行 live commit smoke。
>
> **Commit authority service-role seam（2026-07-24，live fail-closed／legacy owner）**
> `SupabaseCommitAuthority` 實作既有 `CommitAuthority.authorize()` interface，先在
> process 內重算完整 request digest，再由單一 service-role RPC 委派 private
> `authorize_commit_write` transaction；WorkLease／Primary Authority／owner generation
> 仍以 database clock 與 durable state 驗證，HTTP adapter 不重寫 lifecycle。RPC 只
> 回傳 token-redacted grant，function 由 `volpred_ops_definer` 持有、
> `SECURITY DEFINER`、`search_path=''`，且只有 service role 可執行；service role
> 無 private grant table／view SELECT。PG17 clean／idempotent replay、actual
> service-role grant/replay 與 135 個相鄰 tests 通過；production receipt 是
> `20260724085535 operations_core_commit_authority_rpc`。正式 HTTP adapter 在 live
> `legacy/1` owner 下回傳 typed `CommitActuatorBlocked`，其後 grant／receipt／
> ChangeSet count 仍全為 0。這是 production authority adapter 的 fail-closed smoke，
> 不是 live commit smoke或 ownership cutover。

> **Effect Delivery durable outbox contract（2026-07-24，shadow）**
> `volpred.ops.delivery.EffectDelivery` 已提供 immutable `request`／`inspect` seam。
> 每個 intent 必須綁定 WorkItem id／version、effect kind、target、payload reference
> 與 SHA-256、risk、requester，以及 typed downstream acknowledgement expectation；
> normalized payload 另綁成 canonical SHA-256。同一 idempotency key 的等價／並發
> replay 只 materialize 一個 EffectRequest，任何欄位漂移皆 fail closed。
> private PostgreSQL adapter 會在同一 transaction 建立 EffectRequest 與唯一 outbox；
> claim 使用 database clock、`SKIP LOCKED`、有限 lease 與 token fencing。attempt
> settlement 只接受 typed acknowledgement 或具 evidence hash 的 failure，並原子寫入
> immutable receipt、bounded exponential retry 或 dead-letter 終態；等價 settlement
> replay 回傳同一 receipt，late／mismatched token、錯誤 acknowledgement 或 changed
> outcome 全部 fail closed。worker 只能呼叫 named functions 與讀 token-redacted views。
> program commit 13 已加入一個窄的 safe email notification adapter：raw JSON payload
> 必須與 EffectRequest SHA-256 相符，effect／recipient／acknowledgement 必須是同一個
> typed contract；穩定 Message-ID 在 SMTP 前先查 Sent mailbox，重播若已存在且收件人、
> subject、plain／HTML body 全相符就不重寄。SMTP 返回後仍須經獨立 IMAP read-back
> 取得 exact message bytes 才能回傳 `AcknowledgedEffect`；查無訊息為 retryable
> failure，內容漂移則 terminal fail closed。
>
> program commit 13 follow-up 已把 durable claim、authority request、immutable payload
> read、provider write、fenced settlement 與 receipt read-back 收進單一 private
> `EffectOutboxWorker.run_once` deep module。每次 settlement 現在必須保存
> token-redacted authority request hash、outbox claim ref 與 Primary Authority ref；
> 舊的 unfenced SQL overload 已移除。PostgreSQL 17 非 superuser migration executor、
> private schema privileges、receipt FK covering index、SMTP／IMAP contract 都有回歸。
> production IMAP adapter 會 quote mailbox argument，未明示 mailbox 時依 RFC 6154
> `\Sent` special-use 自動發現在地化 Sent folder。
>
> 2026-07-24 controlled live shadow 已把五個 private migrations 套用到 Supabase，
> 以 attempt 2 寄送一封 stable-Message-ID email，從 Gmail Sent Mail 回讀 exact bytes，
> 再把 EffectRequest／outbox／attempt receipt 回讀為 `delivered`／`acknowledged`；
> security advisor 沒有新增 `volpred_ops` lint，performance advisor 新發現的 receipt
> foreign-key index 缺口也已 migration 修正並複驗消失。這是 live shadow evidence，
> 不是 ownership cutover：live Primary Authority adapter、durable payload writer、
> Work Coordinator 正式 caller 與既有 notification／publisher owner 移交仍未完成。
>
> program commit 13 的下一個 follow-up 已把前兩個缺口落成 private PostgreSQL
> adapters。`PostgresEffectPayloadStore` 透過 named function 寫入 immutable bytes，
> 由資料庫重算並綁定 SHA-256；worker 在 provider 呼叫前會獨立重算 hash，payload
> 漂移即 terminal fail closed。`PostgresAuthorityStore` 以 database clock 管理
> Primary Authority lease／epoch／token hash，`PostgresEffectAuthority` 則在同一個
> database function 內核對 exact outbox claim、EffectRequest、WorkItem、payload、
> acknowledgement 與 Primary Authority lease，發出只含 token-redacted references
> 的 durable grant。Settlement trigger 只接受資料庫已簽發且 identity 完全相符的
> grant，不能再靠任意非空字串偽造 authority evidence。
>
> 新 private tables 全部 FORCE RLS；SECURITY DEFINER functions 固定 `search_path`、
> revoke PUBLIC 並採 no-login definer ownership／最小 worker grants。對應 migration
> 已由 Supabase migration API 套用，remote receipt
> `20260723230547 operations_core_effect_payload_primary_authority` 以同名 local
> receipt stub 對齊；乾淨環境由較晚、可重播且冪等的 canonical migration 建立 schema。
> Live PostgreSQL 17 回讀確認五表 FORCE RLS、匿名／authenticated 無 payload 或
> authorize 權限、worker 僅有必要 named-function 權限、兩個預期 index 存在；
> `volpred_ops` security advisor 為 0 lint，performance advisor 只有 10 個
> shadow-table unused-index INFO。既有八筆舊 migration-history drift 未做 repair，
> 不屬於本切片。仍未完成正式 Work Coordinator caller、production ownership
> transaction、unique-owner read-back 與 rollback rehearsal，所以整體仍是
> `contained`。
>
> 後續 production ownership checkpoint 已完成上述四個缺口。正式
> `volpred ops send-alert` caller 每次先從 PostgreSQL 讀取
> `email.ops_alert` 的唯一 owner／generation；owner 是 `legacy` 才可走原路徑，
> owner 是 `operations_core` 則由 `OwnedEmailNotification.deliver()` 收斂：
> 原子建立 WorkItem、immutable payload、EffectRequest／outbox 與 ownership
> receipt，原子取得 Work lease／outbox claim／Primary Authority grant，完成 provider
> write 後再以 IMAP exact-byte evidence settlement。Owner RPC 只授權
> `service_role`，五個 public entrypoints 都是 no-login definer owner、固定空
> `search_path`；private ownership tables FORCE RLS，service role 不可直接讀表。
>
> Live migration receipts
> `20260723234435 operations_core_notification_ownership` 與
> `20260723235106 operations_core_notification_ownership_index` 已各以同名 local
> stub 對齊，較晚 canonical migrations 供 clean replay。Production 實測先做
> `legacy/1 → operations_core/2` CAS cutover；成功 alert
> `effect_owned_email_1408c5e8812e08612817e355601b1561` 回讀 Work
> `succeeded`、effect／outbox／attempt `delivered`，durable payload SHA-256
> `82c8a16c…01aa0155` 與 DB 重算相同，Gmail Sent 原始 bytes SHA-256
> `da61bcdd…dc7a0846` 與 settlement evidence 相同。其後 rehearsal
> `operations_core/2 → legacy/3`，舊 generation request 被拒且零 row，再
> `legacy/3 → operations_core/4`；final live state 只有一個 owner row、零 active
> attempts。故 `email.ops_alert` production ownership 四個缺口現為
> `root_cause_fixed_and_verified`；這不表示其他 effect family 已自動切換。

> ⚠️ **當前真實架構修正（2026-05-29，本檔下方 v12 描述部分已 superseded）**
> 願景見 `VISION.md`；重新擘劃藍圖見 `docs/master_plan.md`（含完整現況/目標/7-phase 路線圖）。
> **實際控制面 = 5 層並存**（非單純 v12 單線程）：
> 1. **LaunchAgent**（macOS 原生，最可靠）— hourly-dispatch / compute-worker / check-alerts / daily-update / gmail-poll / collect / release / work-summary / handoff-regen 等 12 個
> 2. **piggy-back universal scheduler** — `check_alerts (0 * * * *)` → `scripts/run_due_jobs.py` 讀 `runtime_schedules.json` 評估 due 並執行（macOS host cron 只可靠 fire `0` 分 pattern，故非 0 分 job 走此路）。`piggy_back_skip:true` / `host_crontab_managed:false` 的 job 由 LaunchAgent 專責、piggy-back 跳過（防雙 fire）
> 3. **codex_loop.sh daemon**（VSCode terminal，常駐）— Codex 每小時 tick，讀 `AGENTS.md`（Codex 版指令檔，**勿歸檔**）claim task
> 4. **task pool** — `next_tasks.json`（pending queue，目前實際多靠 hourly-dispatch 自生）+ `storage/ops/tasks/`（audit receipts）
> 5. **dispatch_supervisor 重構（進行中，D4/8）** — 目標 long-lived asyncio supervisor 收斂上述為「1 樞紐 + 3 消費端」（見 `docs/refactor_plan_hourly_dispatch.md`）
> crontab 多數條目是 no-op fallback（不刪、勿手動改，只透過 `install_host_crontab.sh`）。
> 下方 v12「單一主線程 / 不再有常駐 supervisor」描述為歷史，dispatch_supervisor 完成後本檔將整體重寫。

補充總覽文件：`docs/system_handbook.md`。若你要一次看完整系統架構、功能、資料流、排程、control plane、前後台與維運邏輯，先讀這份再回來查本檔細節。`2026-04-19` v12 架構已收斂為**單一主線程 Claude Code session 作為唯一 orchestrator**；不再有常駐 supervisor / worker terminal pool。舊的 3-terminal / supervisor-worker 構想（`docs/multi-agent-terminal-workflow-codex.md`）已 deprecated，僅保留歷史。

## 網站架構（v4 Supabase + Admin CMS + Mirror API）
- **前端 target 設定**：`config/project_targets.json`（唯一來源；目前 `active_frontend=frontend-v2-fix`、`active_service=volpred-v3`）
- **排程 target 設定**：`config/runtime_schedules.json`（唯一來源；host crontab + session cron + `event_jobs` spec。v12 下 session cron 是正式的 queue 推進時鐘，host crontab 處理資料收集與外部世界 trigger）
- **前端（目前線上版）**：`frontend-v2-fix/`（Next.js 15 + React 19 + Supabase，部署於 volpred-v3 服務）
- **Legacy 前端快照**：舊版已自 root retire；如需參考請看 `archive/root-clutter/local/舊前端/`
- **Mirror API**：`mirror-api.zeabur.app`（研究記憶檔案鏡像，減少 Supabase egress）
- **資料庫**：Supabase（PostgreSQL + Auth + REST API + RPC）
- **Zeabur Project / Service IDs**：見 `config/project_targets.json`
- **線上網址**：https://volpred.zeabur.app
- **舊版**：https://volpred-old.zeabur.app（過渡期保留）

### 前端 v4 架構（frontend-v2-fix/）
- **SSR + CSR 混合**：首頁用 Server Component 初始載入 → `FeedBrowser` 用 `useSWRInfinite` 無限滾動
- **Admin CMS**（12 個面板）：analytics / content / health / ops / paper-trading / papers / program / questions / schedules / strategies / thinking / users
  - `/admin/schedules` 讀 canonical schedule spec + live `crontab -l`，不再從 rendered guide 逆向解析
- （原 legacy `program` 已重新啟用為主面板之一；`thinking` 為 Claude 思考日誌檢視器）
- **用戶專區** `/me`：書籤、提問歷史、活動摘要
- **API 路由 45+**：含 `/api/admin/*`（12 端點）、`/api/me/*`（3 端點）、`/api/strategy-overview`、`/api/portfolio-overview`
- **認證**：`admin-auth.ts` 支持 secret-based + session-based 雙模式，角色：admin/user/guest
- **Feed RPC**：`feed_page()` + `feed_tag_counts()` 伺服器端分頁+標籤計數，取代 client-side filter
- **互動追蹤**：`ArticleEngagement` 組件（瀏覽、按讚、收藏、分享）
- **策略視覺化**：`PaperTradingChartIsland` + sparkline 走勢圖（Recharts）
- **論文管理**：`/admin/papers` + `/api/admin/papers` + `/api/admin/papers/upload`，論文頁 metadata 與 PDF 交付都可走平台層

### 資料流
- `storage/` → 本地唯一源頭（JSON）
- **文章採 Contentlayer 模式（2026-04-18 起）**：
  - `storage/reports/feed.json` 是**唯一 canonical 文章源**，git-tracked，保留完整 audit trail
  - Supabase `articles` 表是**唯讀 projection**，寫入只允許 `service_role`（migration 022 RLS 物理阻擋前端/admin CMS 反向寫）
  - **寫入只走三條 path**：`publisher.publish_milestone` / `ops release-pool` / `ops feed-sync`
  - 三者內部都先改 feed.json，再呼叫 `sync_article(...)` / `_delete_where(...)` 把變動推 Supabase
  - 歷史的 `storage/reports/mile_*.json` 個別檔案已廢除，全部移到 `storage/reports/_archive_mile_files/`，不再被任何 code 讀寫
  - 漂移偵測：`uv run volpred ops feed-sync --dry-run` 或 session Monitor 每小時檢查 `feed.json ↔ Supabase`
- `scripts/supabase_sync.py` → Supabase 同步工具（由 daily_update.py 呼叫，不需獨立 cron）
  - **文章同步**：只讀取 `storage/reports/feed.json`（唯一源頭，`storage/feed.json` + `mile_*.json` 全部已廢除）
  - **Paper trades 同步**：自動剝離市場數據（spy_close/gld_close 等），只存策略 weights + returns
  - **Draft 同步**：用 `published_at OR created_at` 過濾（支持 draft sync）
- `scripts/daily_update.py` → 每日 08:03 台灣時間（crontab `3 8 * * 2-6`，美股收盤後）計算策略權重 + 同步 Supabase + 重算績效指標 + Supabase heartbeat
- `scripts/recalc_metrics.py` → 從 paper_trading.json 重算 Sharpe/MDD 等（daily_update 自動呼叫）
- `config/project_targets.json` + `src/volpred/config/runtime.py` → 控制 active frontend、Zeabur deploy service、paper public dir、strategy metrics local sync target、預設 remote/mirror URL
- `config/runtime_schedules.json` + `src/volpred/config/schedules.py` → 控制 canonical session cron / host crontab / `event_jobs` spec（v12 單主線程架構）
- **Paper Trading 資料結構**：
  - `paper_trading.json` 是唯一源頭，不可手動修改歷史數據
  - `daily_update.py` 正確使用 next-day return（K692 驗證），forward tracking 自動修正
  - `recalc_metrics.py` 每次執行自動 sync 到 Supabase `strategy_metrics_cache`
  - `recalc_metrics.py` 也會同步到 active frontend 的 configured metrics target（目前 `frontend-v2-fix/data/strategy_metrics.json`）
  - **不修改歷史數據**：歷史 entries 反映當時追蹤的結果，隨新的正確條目累積 metrics 自然收斂
  - 市場數據統一存在 `_market_daily`（key=日期），不在每個 entry 重複
- **新策略評估**：
  - 必須用 `scripts/evaluate_new_strategy.py` 在 COMMON_START（2023-01-04）~ 今天的同期間比較
  - 與已上架策略的 paper_trading actual returns 做公平比較（同期間、同 lag、同 TX cost）
  - 通過同期間比較 + cross-OOS 才能進入上架流程
- `src/volpred/ops/` + `uv run volpred ops ...` → agent-first 操作層（真人與本機 agent 共用）
- `uv run volpred ops experiments ...` → `experiments/` 結構治理工具；v2 採「新規先行 + touched-file migration」，不一次性批量搬歷史散檔
- 前端從 Supabase 讀取策略 metadata，不需靜態檔案同步
- **Mirror 資料流**：`MemorySystem._sync_to_remote()` 直接呼叫 Mirror API（預設 URL 由 `config/project_targets.json` 提供，可被 `VOLPRED_MIRROR_URL` 覆蓋）
  - 平時：增量 append（POST，只送新 entry）
  - 初始/復原：整檔覆蓋（PUT，`reconcile_remote()`）
  - Mirror 存：thinking_journal / knowledge / experiments / research_log（4 個大型記憶檔案）
  - Supabase 存：articles / questions / papers / paper_trades / strategy_signals（產品面向資料）
  - 本地 frontend data mirror 預設不啟用；只有 `project_targets.json` 明確配置 `local_data_sync_dirs` 才會寫入
  - Rollout 文件：`docs/research-mirror-rollout.md`

### 策略管理（DB 驅動，無需重新部署）
- 策略 metadata 唯一來源：`daily_update.py` 頂部的 `STRATEGY_REGISTRY`（display_name, is_active, order）
- Registry 驅動三件事：Feed 文章（只列 active）、Supabase 同步、Paper trading
- **新增策略**：(1) 加入 STRATEGY_REGISTRY (2) 加計算邏輯到 strat_list (3) `add_strategy.py` 寫 DB
- **下架策略**：改 STRATEGY_REGISTRY 的 `is_active=False`（面板隱藏、文章不列、paper trading 繼續記錄）
- **績效指標**：每日由 `daily_update.py` 自動重算 → `storage/strategy_metrics.json` → active frontend configured target
- 詳細流程見 `.claude/skills/autonomous-research/references/add-strategy-guide.md`

### 發佈流程
1. 研究系統優先寫入 `storage/`，再依需求選擇：
   - `立即發布`
   - `放入文章池草稿（draft）`
   - `排程發布（scheduled）`
2. 平台層釋出優先走：
   - `uv run volpred ops publish-milestone`
   - `uv run volpred ops release-pool-by-settings`
   - `/admin/content`
3. 文章真正進入 `published` 後，平台層會準備管理通知：
   - 單篇新文章通知
   - 每日發文摘要
   - 若未配置 SMTP，會先寫入 `storage/notifications/`，不算真正寄出
4. Feed 發文用 `feed-publisher` skill；若涉及文章池、排程、節奏釋出、下架、釋出規則、管理通知，轉交 `admin-ops`
5. 改前端代碼時：Zeabur CLI 部署 `frontend-v2-fix/`（見下方 Zeabur CLI 指令）
6. 新增策略用 `add_strategy.py`（只寫 DB，不需部署）
7. 測試貼文清理優先走 `uv run volpred ops cleanup-post <pub_id>`，不要手改 feed/DB

### Agent-first Ops Layer（v12 單主線程架構，2026-04-19）

**核心模型**：整個本地 control plane 只有**一個持久的執行者** — 主線程 Claude Code single session。v11 的 3-terminal worker pool（supervisor + claude-worker + codex-worker）已於 git commit `e64a1907` 拆除；不再有常駐 T2/T3 worker terminal、也不再依賴 headless `claude -p` / `codex exec` subprocess。舊架構詳見 `docs/multi-agent-terminal-workflow-codex.md`（已 DEPRECATED）。

**角色分工**：

- **dispatch-supervisor orchestrator pool**：`config/runtime_schedules.json` 的 `volpred-dispatch-supervisor.max_slots` 控制並行 logical fires（2026-07-13 起預設 2）。每槽以 stable `job_id` / `slot_id` 隔離 state、log 與 worktree prefix；task-pool claim 仍由 canonical fcntl control plane 仲裁。
- **Codex（ephemeral subagent）**：透過 `codex:codex-rescue` / `codex:review` 等 subagent 以 **ad-hoc** 方式被主線程派遣。共用 runtime、一次一個、任務結束即退出；**不是常駐 session，也不會主動 poll queue**。
- **Worktree agents（ephemeral）**：僅產出 `experiments/kXXX/`，完成後由主線程 `scripts/merge_worktree.sh` 合併；不可寫共享狀態。
- **Cloud triggers（遠端/host 層）**：Session cron 與 host crontab 只負責**把事件放進 queue**，不直接完成 task。

**Queue 語意**：control-plane queue (`storage/ops/`, `event_jobs`, `storage/next_tasks.json`) 在 v12 下是 **proposal / backlog**，不是 worker poll target。主線程在每輪 cron 或 idle pass 時**主動消化** queue。沒有 worker daemon loop 去認領 task。

**排程 / 時鐘層級**（全部 source of truth 在 `config/runtime_schedules.json`）：

- **Session cron（Claude Code `CronCreate` durable）**：`*/4` 分鐘觸發「繼續任務」prompt，驅動主線程自動推進 queue。這是 v12 的正式執行時鐘。
- **Host crontab（5 entries + 1 hourly）**：
  - 資料收集：`collect_tw` / `collect_us`
  - 每日更新：`daily_update`（08:03 TPE）
  - Pool 釋出：`release_pool`
  - 日曆同步：`market_cal`
  - 每小時：`check_alerts`（email alert subsystem）
- **Event jobs**：由 cron / signal 觸發的 one-shot 事件（例如 FOMC、CPI release），materialize 成 control-plane task 由主線程消化。

**Alert subsystem**（`src/volpred/ops/alerts.py` + `.claude/rules/alert.md`）：

- 3 條件：`release_pool_gap` / `draft_pool_low` / `host_cron_fail`
- 三段 body：觸發條件 / 影響 / 建議行動
- Dedup 避免重複轟炸；CLI 支援 `--force` 強制發信
- 由 host crontab hourly `check_alerts` 入口驅動

**CLI 首選入口**：`uv run volpred ops ...`（agent + 真人共用同一套操作）

已統一的操作：
- `ops publish-milestone`
- `ops release-pool-by-settings`
- `ops send-article-notification`
- `ops send-daily-digest`
- `ops unpublish`
- `ops cleanup-post`
- `ops sync-all`
- `ops daily-update`
- `ops recalc-metrics`
- `ops strategy-upsert`
- `ops strategy-set-active`
- `ops question-ranking-summary`
- `ops question-rerank`
- `ops question-answer`
- `ops health`

**Job Queue**（`src/volpred/ops/jobs.py`）：
- Supabase-backed 任務佇列（`ops_jobs` 表）
- lifecycle: `queued` → `running` → `succeeded|failed`
- 支援 dedupe key、dry-run、priority
- CLI: `ops jobs` / `ops job-show` / `ops enqueue` / `ops worker`
- **`ops worker` 定位（v12 更新）**：手動觸發用的本地執行 helper，不是常駐 daemon；主線程才是正式 orchestrator

**Web Admin**（`frontend-v2-fix/src/app/admin/ops/`）：**Observer only**。OpsConsole 做瀏覽器端 job 監看；canonical control plane 是 `storage/ops/` + 主線程 session state，UI 不是 source of truth。

**Claude 可直接讀的 summary surfaces**：
- `/api/admin/analytics/summary`
- `/api/admin/questions/summary`
- `/api/admin/content`

**核心原則重申**：同一套 `ops` CLI，真人與主線程 agent 共用；v12 下真人 UI 是監看層，主線程才是正式執行者，不再有第二個平行 Claude / Codex session 持續消化 queue。

## 程式碼架構
- **Python CLI (volpred)**：研究引擎（實驗、評估、記憶、發佈）
- **config/project_targets.json**：前端 / 部署 / Mirror target 的版本控制設定
- **src/volpred/config/runtime.py**：程式側讀取 runtime target 的 helper
- **storage/**：唯一資料源頭（JSON），跨 session 保存
- **frontend-v2-fix/**：Next.js 15 前端（線上版，volpred-v3 服務）
- **archive/root-clutter/local/舊前端/**：legacy snapshot 存放處；不參與 active code path / deploy
- **scripts/supabase_sync.py**：資料同步到 Supabase
- **src/volpred/ops/jobs.py**：Supabase-backed job queue（agent + human 共用）
- **research_program.md**：研究策略文件（北極星）
- **paper/**：學術論文（按子目錄組織）

### Supabase 資料庫表
| 表名 | 用途 |
|------|------|
| `articles` + `article_tags` | 文章（feed）+ 標籤 |
| `strategy_signals` | 策略即時信號（權重、VIX、sigma） |
| `paper_trades` | Paper trading 每日記錄 |
| `strategy_metrics_cache` | 預計算的績效指標 + sparkline |
| `questions` + `question_articles` | 會員問答系統 |
| `memory_entries` | 研究記憶（thinking/knowledge/experiments） |
| `profiles` + `quota_usage` | 用戶角色（admin/premium/free）+ 配額 |
| `article_impressions` + `article_reactions` | 互動追蹤（瀏覽/按讚/收藏） |
| `ops_jobs` + `ops_job_logs` + `ops_audit_logs` | Job queue + 審計紀錄 |
| `papers` | 論文 metadata（論文頁 DB 驅動） |
| RPC: `feed_page()`, `feed_tag_counts()` | 伺服器端分頁查詢 |

### Supabase Migrations
- `004_deep_efficiency.sql` — 索引 + feed RPC + strategy_metrics_cache
- `005_ops_control_plane.sql` — ops_jobs + audit logs
- `006_reload_postgrest_schema.sql` — schema refresh
