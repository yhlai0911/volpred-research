# Project Improvement Status

Last updated: **2026-07-26（T04 ChangeSet shadow-path root cause fixed and verified；Boss Report production owned-delivery verified；physical two-Mac authority pair verified）**

## 2026-07-23 平台運營優化總計畫（accepted charter）

跨基礎架構、程式、零付費 AI 續跑、換機／暖備、Admin、原版／v3／vNext、analytics、
自然成長與受控自我優化的總體決策，見
`docs/platform_optimization_program_2026_07.md` 與 `docs/adr/` 下四份 accepted ADR。
GitHub planning parent 為
`https://github.com/yhlai0911/volpred-research/issues/3`，33 張驗收票為 #4–#36；
GitHub 只負責規劃／驗收，`storage/next_tasks.json` 仍是唯一 runtime pending queue，
materialized runtime task 必須引用對應 planning issue。

### 2026-07-26 — T04 ChangeSet shadow commit path（Issue #10）

沿用 Issue #3 plan、`docs/refactor_plan_ops_master_2026_07.md` spec 與 T04/#10 ticket，
沒有另建計畫或 runtime queue。Matt Spec／Standards 初審發現三個結案缺口：
required checks 只相信作者自述、commit-worker 可由 command 字串冒充，以及 Supabase
ChangeSet read-back decoder 未逐欄 fail closed。

底層現已改為：正式 caller 先把 running WorkItem id／version／author／required
attestations 與 ChangeSet 綁定；首次 Git actuation 前由 trusted registry 在 linked
worktree 實跑每一項 check，前後重驗 base／scope／hash／mode，missing command、
timeout、failed test 或 workspace drift 全部在 Git writer 前拒絕。外部命令不再接受
actor，commit principal 固定由 composition root 注入
`commit-worker:operations-core`。PostgreSQL／Supabase 共用 decoder 會驗 schema、
strict integer、canonical proposal、重算 proposal SHA 與 actuation／delivery
cross-field lifecycle identity，並重新推導 owner／settlement ref 與 digest。
Lost-return recovery 會先在有效 authority 下只讀辨識 exact historical commit；
只有確定要新寫入才依賴 workspace 與重跑 checks，因此 commit 後、checkpoint 前崩潰
即使 linked worktree 已移除，也不會留下無法 settlement 的孤兒 commit；HEAD 未前進
且 checks 失敗時也不會先建立無 commit 的 durable authority grant。Stale／並行 HEAD
先用 deterministic request digest 唯讀驗 exact first-parent identity；未知 request
只做 read-only lookup且 grant count=0。隔離 PostgreSQL 並實際完成 owner rollback，
證明 fail-closed 不會轉成永久 rollback deadlock。

後續 Matt 競爭複審發現 grant 曾在 canonical writer lock 前建立，且 settlement／
abandonment 沒有共用 terminal arbitration。現已改為先取得 repo-wide canonical
writer lease，才在同一 lease 內重讀 HEAD、authorize、把 capability 傳給 writer，
並做終止判定；busy 不再建立 grant，timeout 保留 active grant等待 exact recovery，
authority-bound non-exact mutation也持續阻擋 rollback。只有同一 lease 內證明未發生
該 request mutation且repository回到完整基線才可 immutable abandon；跨 retry 的
stale HEAD完全不信任 Git trailer，即使是另一個格式正確 digest，也一律視為
ambiguous。Writer 前會保存完整 index tree 與 exact-path
kind／mode／hash，abandon 前必須全部回到基線。重試看到 target staged 或 formal
workspace 的 canonical paths 已偏離 base，會在 authorize／writer 前保留舊 grant。
DB settlement trigger與abandon共用
同一 request advisory lock，並新增雙連線競爭回歸；recovery RPC 在
`VOLPRED_NO_REMOTE_WRITE=1` 下仍可讀，abandonment decoder強制 schema version。

隔離 PostgreSQL + 暫存 Git system test 已回讀唯一 exact-path commit、
HEAD／diff、ChangeSet、authority receipt 與 succeeded WorkItem，並完成 owner rollback
rehearsal；最終精準提交鏈 `07accb1e1`、`02b160858`、`9cda15ef2` 後完整 scoped
suite **201 passed**，Matt Spec／Standards 最終複審均 PASS、無 P1/P2。本輪核心修正被另一 session 的 23:55
廣域 dispatcher transaction 一併收入 commit `d45c9a307`，未回退或改寫該 shared
commit；後續證據以 exact-path commit 補齊。Issue #10 shadow acceptance 為
**`root_cause_fixed_and_verified`**；但 production `git.commit` owner仍是
`legacy/1`、未做 live CAS，所以 Change Delivery umbrella 繼續標 **`contained`**。

### 2026-07-26 — Boss Report caller follow-up（Issue #39）

本項不是新計畫；它沿用 Issue #3 plan、master spec 與 T05/#11 owned-effect 架構，
補上原 ticket inventory 漏列的 Boss Report caller。報告內容已改為 typed read model，
只讀 master spec §7 與 current task-pool mode；歷史五月 cycle/action 檔不再進信件。
排程端由 canonical config 重建 generation／activation／cron slot／fire digest，
同一 fire 首次 render 以 no-overwrite payload 保存。

跨主機重送邊界已從本機 cache 提升至 shared evidence：
`volpred_read_owned_email_request` 讀回 immutable command 與 optional terminal receipt；
既有 Operations Core request 不可被 legacy supersede。明確 legacy rollback 同樣取得
Primary Authority，並以 deterministic Message-ID 先查 Gmail Sent。本機 PostgreSQL
migration／transaction 與 Python regressions 已通過；production migration
`20260726134809` 亦已部署並回讀 owner／ACL／transfer fence。live acceptance fire
建立 WorkItem／EffectRequest／outbox attempt 1，Gmail Sent exact read-back 為
delivered；同一 fire 重播只回相同 terminal receipt，attempt 仍為 1。新自然
schedule 已於 2026-07-27 08:10 台灣時間由 Operations Core 一次成功；canonical RPC
回讀同一 fire 的 WorkItem／Effect／attempt 1／Primary Authority epoch 211 與 Gmail
Sent evidence 完全一致，owner 維持 `operations_core/4`，未見 direct SMTP、重送或
owner drift。closure scoped regression 103 passed，五步 gate 全過，狀態為
**`root_cause_fixed_and_verified`**。
Phase 0／ADR-0001 的 module seam、interface、adapter 與第一個 TDD 切片，見
`docs/operations_core_module_design.md`。
2026-07-23 已完成 in-memory tracer（24 cases）及 private PostgreSQL 17 shadow adapter
（34 cases）；含 database-clock lease fencing、approval／risk fail-closed、parent／deadline
readiness、atomic acquire、idempotent checkpoint/resume、concurrent terminal replay、
event/receipt、
FORCE RLS、專用低權限 function definer、具名 mutation functions、worker／approver
分權、token-redacted read projection 與 transaction failure rollback，連同相鄰回歸共
71 passed。canonical row 已包含
parent／deadline、requester、created／updated 與 blocked reason。外部測試 DSN 有
localhost／hostaddr／專用 DB／opt-in 防線；CI 固定使用 PostgreSQL 17 且缺少
integration backend 時 fail closed。
Submit C legacy snapshot importer 已達
**`root_cause_fixed_and_verified`**（implementation commit `5ddb5b0d1`；47 scoped
tests；Spec／Standards 雙軸複審無 P1／P2）：
三套來源只讀映射、公開 migration façade、
內容雜湊綁定的 payload reference、structured reconciliation、duplicate ID／idempotency、
missing parent／simultaneous claim／invalid lifecycle／unknown schema／policy／public effect
fail-closed、逐值核可 provenance registry，以及強制三份 snapshot、只允許
`--dry-run`、malformed encoding／shape machine-readable、輸入逐 byte 不變的 CLI。
2026-07-23 16:14:48 CST 的 next_tasks-only smoke（snapshot SHA-256
`18281269d61832d97dc38177f8d26ec8b53b91e525e5198a99e9414a1f47c703`）為
3,337 seen／2,569 mapped／900 issues，因未分類 provenance 與歷史 schema debt 正確
回報 `ready=false`。
Submit D shadow replay 的原始 `232ffc994`／`5b9f78adf` checkpoint 只達
**`contained`**：immutable snapshot 與 append-only receipt 安全性成立，但 Matt 雙軸複審
確認 selector 是 replay 專用副本，未涵蓋真實 routing／lease semantics，故當時不得稱完成。
2026-07-23 Issue #7 reimplementation 已達
**`root_cause_fixed_and_verified`**：
legacy direct-claim gate 與 production pending-list filter／priority-id ranking 抽成
`volpred.ops.task_pool_selection`，Work Coordinator acquisition 抽成
`volpred.ops.work.selection`，production claim／in-memory acquire 與 replay 共用相同 pure
policy seam；PostgreSQL `acquire_work` 則由 34-case integration contract 回讀 parity。
legacy winner 先套用 production `list --status pending` 的 exact status／worker filter，
再對原始 immutable `next_tasks` 執行含 identity uniqueness 的 direct-claim admission；
migration importer 不可表示的 record 仍保留 reconciliation comparison。duplicate／missing
identity 以 ordinal + content hash 分開綁定並 fail closed；三來源 raw identity inventory
在 mapping 前掃描完整母體，故跨來源 duplicate 不會因一份 record 無法映射而消失，也不會
因 task-id dict 覆蓋而錯接 selector evidence；未送進 Coordinator 的 record 明示 migration `not_evaluated`，
不虛構 Coordinator reason。blocked 與 claimed records 只保留比較證據，不會被虛構成
hourly winner。需 live detector 的 registered dreaming candidate 若 snapshot 沒有
revalidation evidence，會以 `live_revalidation_required` fail closed，不查 live source，
production claim 則在同一 transaction 完成 detector check 後才重新進 admission。
replay 的 selection scope 明定為 `next_tasks`，另外兩份 snapshot 仍參與同一 hash identity
與 reconciliation evidence；若 next-task 的 parent 位於其他 snapshot，則透過 production
selector 的 non-selectable `dependency_items` 提供 readiness context，但 parent 永不進入
winner pool，因此不虛構跨三套 legacy store 的全域 winner。
逐 candidate 比較 priority、status readiness、capability、attestation、claim ownership、
lease expiry、dispatch lane、preferred agent、parent readiness、deadline 與 terminal
disposition；差異由 selector／reconciliation reason codes 經顯式 policy oracle 分類並附
evidence reference。兩支 CLI 共用同一 snapshot loader；152 個 selector／replay 核心
cases、另行重跑的 10 個 model-router topology regressions、144 個相鄰
dreaming／stale-reclaim／refill regressions 與 34 個隔離 PostgreSQL contracts 通過。
CLI 仍只讀 caller 提供的三份 snapshot，僅在指定目錄追加不可覆寫的 observation receipt。
尚未建立 canonical schedule 或累積七天 observation window，migration 也未部署，
因此仍不構成接管或上線。
2026-07-24 已完成 Issue #9 的 pre-cutover legacy read projection interface：
`project_legacy_next_tasks(WorkSnapshot)` 產生 detached、deterministic、SHA-256 綁定的
`next_tasks` compatibility rows；production legacy selector 與既有 importer 的
interface tests 覆蓋 row count、priority、claim ownership、parent、deadline、
approval 與 terminal disposition。duplicate identity、缺失／模糊 lifecycle event
及不相容 provenance 都 fail closed。此 module 沒有 canonical writer 或 apply 模式，
尚未接管 live enqueue／claim／complete，也沒有七日 receipts 或正式 rollback rehearsal；
所以 Issue #9 仍維持 `contained`，不可由 interface complete 推論 live owner 已切換。
同日新增 Issue #9 cutover preflight manifest：seam 直接從 immutable receipts 用
trusted wall clock 重跑 canonical 七日 assessment，並從同一 owner-state bytes 取得
unique-owner mode 與 CAS SHA；queue path 固定為 repo canonical，paired state 由 queue
唯一衍生並在 shared lock 內取樣。Caller 三來源 mappings 先 canonicalize 一次並重建
private snapshot，後續對帳不再重讀 mutable caller rows。Raw legacy bytes 由 seam 自行 hash、decode 與 import，
projection schema 必須精確等於 production `next-tasks-read-projection.v1`，未知
schema 不可只靠相同 payload bytes 冒充相容；row count／SHA 則從 payload 重算。
Legacy import 與 staged Coordinator projection
逐 identity 比對 row count、priority、claim ownership／started timestamp、parent、
deadline、policy、row created／updated timestamp 與 terminal disposition。通過後的
immutable manifest v3 綁定
raw legacy snapshot、assessment、import report、projection schema／SHA 與 owner state SHA-256。
它另由同一次 trusted clock 固定 `prepared_at` 與 15 分鐘 `valid_until`，讓後續 durable
gate 能拒絕過期 evidence capsule。
Assessment 另帶 receipt-set digest 與最後 snapshot identity，必須與本次完整 cutover
snapshot 一致；Coordinator 無法表示的 dispatch policy 會 fail closed。
上游 shadow replay producer 同步改為入口單次 freeze；ledger hash、兩側 selector 與
comparisons 不再分次讀 caller mappings，A→B→A mutation 無法生成自洽外觀的錯綁 ledger。
Preflight 另要求切換瞬間為零 active lease：即使 `claimed`／`running` 的 owner、
timestamp 與 expiry parity 完全相符，legacy worker 的 mutation token 也不在 read
projection 中，無法由 ownership transaction 無損移交；因此 active work 會在 manifest
前 fail closed，不以「欄位相同」冒充 lease continuity。
此能力無 apply／writer seam，live 仍是 `direct_execution`、observation count 仍為 0，
所以只是正式 transaction 前的 fail-closed evidence capsule，不構成 ownership cutover。
2026-07-26 續建 Work Coordinator durable owner fencing：local PostgreSQL schema
新增唯一 owner row、monotonic generation 與 append-only receipts，七個 mutation
共用 owner-row lock／generation fence，transfer 用 exclusive-lock CAS。Expired
claimed／running lease 會依 DB clock 在同一 transaction 回 pending、保留 work identity
並追加 release event；有效 lease 仍阻擋 transfer。Legacy runtime grants 與 owner
切換同交易撤銷／恢復；legacy wrapper 仍 assert `legacy`，已進入但排隊中的 caller
也不能越過 owner CAS。既有 notification／publisher／commit formal workflow
明確 rebind 到 runtime 不可執行的 definer-only internal seam。後續 local migration
已新增 durable `work_cutover_gates` 與 append-only gate receipts：stage 會重算 canonical
manifest bytes 的 SHA-256、驗證 v3 exact contract／row parity／15 分鐘 freshness，
並拒絕沒有 `Z`／UTC offset 的 session-dependent timestamp，再鎖定當下 legacy
generation；stage 在 owner lock 返回後、INSERT 前重驗 expiry。Owner transfer 只能在
同一 transaction consume 該 gate。Owner-row
BEFORE UPDATE trigger 與 wrapper post-CAS 會雙重驗證 DB-clock expiry，等待跨過有效窗
就整筆 rollback；rollback 只能使用 gate 記錄的 consumed generation。Stage、read、transfer
仍不授權 worker、approver 或 PUBLIC，避免任意 SHA 或 runtime caller 繞過七日 gate。
2026-07-26 production 已套用
`20260726061130 operations_core_work_ownership` 與
`20260726061244 operations_core_work_cutover_gate`。Catalog 回讀確認 owner／gate
tables 均 FORCE RLS、owner-update gate trigger 啟用，stage／gate-read／transfer／
ungated seam 對 PUBLIC、worker、approver 與 deployment role 都無 EXECUTE；既有九個
formal callers 全數綁到 definer-only internal seam。Live table statistics 只有
migration 建立的 owner row／receipt 各一筆且零 update，gate／gate receipt 均為零，
所以 owner 仍是初始 `legacy/1`，本次沒有 staged manifest 或 owner transfer。四個相鄰
suites **96 passed**；Supabase security advisor 對本 scope 零 finding，performance
advisor 只有新建 receipt timeline index 尚無 workload 的 unused-index INFO。七日
read-back／正式接管／rollback rehearsal 仍未執行；因此這是 deployed
evidence-bound transaction gate，不是 cutover，Issue #9 仍為 `contained`。
同日補上缺失的七日 evidence producer：`work_shadow_observe` 由 canonical
`runtime_schedules.json` 每小時 :15 經單一 piggy-back owner 執行，wrapper 已安裝且
live smoke exit 0、marker 回讀成功。它只讀 canonical pending queue、相關 TaskRecord
parent／active anomaly 與 queued/running `ops_jobs`，追加 gitignored receipt；
不 stage gate、不 transfer owner。最新 receipt 已把歷史無關 terminal receipts排除，
source counts 為 `1/0/0`，並正確留下 preserved control row 的 missing-parent 與
pending+started_at lifecycle blocker。Release／stale cleanup 的產生流程已統一清除
`started_at`；現存 row 未手改。Matt Spec review 後 scheduled receipt 升為
owner-bound v4，在 queue shared lock 內綁定 observation-time mode／gate／state
path／SHA；assessment 只計入與當下 owner evidence 完全相符的 v4 receipts，舊 v3
只保留 audit。Identity scoping 同步共用 production `task_identity(id | task_id)`，
不再漏掉 alias row 的 terminal 對帳。因 live mode 仍為 `direct_execution`，
cutover-eligible 七日時鐘尚未開始，且 blocking evidence 尚在，因此 Issue #9 仍是
`contained`。
相鄰回歸 **161 passed**，全專案 **5,171 passed、1 skipped、0 failed**。
Matt Standards re-review 另發現 observer 的 duplicated active-status set 漏掉合法
非終態 `blocked`；現已改為共用 `local_control_plane.NONTERMINAL_TASK_STATUSES`，
並以 queued／claimed／running／awaiting_approval／blocked 五態 regression 防止
cutover evidence 靜默漏列。
Live v4 wrapper smoke
`scheduled_20260726T071908848044Z_db0c9cd079a6` 已 exit 0；receipt 回讀
`direct_execution`／gate enabled、owner-state SHA 綁定、source counts `1/0/0`，
assessment observation count 1 且五個既有 blockers 全保留，沒有誤判 ready。
第二張 live v4
`scheduled_20260726T073001085132Z_41a7548d488c` 亦 exit 0；assessment count 2，
同一 owner-state SHA 且仍為五個 blockers。標準 full suite 功能測試
**5,183 passed、1 skipped、0 test failure**；CI-parity post-hook 因 live 未追蹤
worktrees／ops receipts 令整體 exit 1，另行透明記錄、不宣稱全綠。
第三輪 Matt review 發現 owner-mismatch receipt 若直接過濾，A→B→A 可能延續舊 A
窗口；assessor 的 gate／path／SHA optional 參數也可被 caller 省略。現改為必填 typed
`TaskPoolModeEvidence`，五欄完整 match；最後一張 mismatch 形成 epoch boundary，
七日窗口從其後重新起算。ABA／partial API RED→GREEN，assessment＋cutover
preflight **45 passed**，Matt 最終 Standards／Spec 雙軸皆 PASS。

同次 full-suite production read-back 發現三筆 06:34–06:35 UTC 建立的
`ops.alert.email` WorkItem 並非新版 runtime 健康流量，而是測試程序在
`VOLPRED_NO_REMOTE_WRITE=1` 下仍繞過 guard 呼叫 Supabase mutation RPC；三筆都只到
submitted／acquired／started、沒有 effect receipt，lease 隨後過期。根因修正把
mutation guard 放進 `SupabaseOwnedEmailStore` 的共同 RPC boundary，在任何 HTTP 前
fail closed；read-only owner query 不受影響。現存 production rows 依「修流程、不手改
資料」保留作 audit evidence，不能拿來宣稱 Work Coordinator 已開始正式接管。
修後 full suite **5,177 passed、1 skipped、0 failed**；production 以事故最後一筆
時間為 cutoff 回讀，`Claude→Codex failover 接手失敗%` 測試形狀新增數為 0。
同窗口 07:01 UTC 的另外三筆是 canonical hourly alert 真實流量，local incident
candidate 有同 timestamp／dedupe key，production WorkItem 三筆皆 `succeeded` 且各有
durable receipt。這證明 owned-email `operations_core/4` 已正式運作；它不代表
Work Coordinator queue owner 已切換，後者仍是 `legacy/1`。
Live read-back 隨後發現另一個獨立 runtime 缺口：118 次 owned-email 已成功交付，但
22 筆 attempt 因程序在 begin 後、settlement 前中斷，永久停在
`started/running/claimed` 且 lease 已過期；最近兩小時仍持續新增，證明不是歷史殘留。
根因是既有 begin 雖允許重領過期 WorkItem/outbox，卻沒有 actuator 或 schedule 會找出
並呼叫它。新 `volpred_recover_expired_owned_email_notification` 以
`FOR UPDATE SKIP LOCKED` 原子選取最舊過期 attempt、透過 canonical begin 建立下一次
fenced attempt、關閉舊 attempt，並追加 private FORCE-RLS immutable recovery receipt；
service-role 只能執行 RPC，不能直接讀私表，anon／authenticated 無權限。Python
`OwnedEmailRecovery.recover(limit)` 在一小時內先以 deterministic Message-ID 查 Sent
Mail 去重補送，超過一小時則 durable dead-letter，避免部署時補炸歷史告警。
Canonical `owned_email_recovery` schedule 每小時由 check_alerts piggy-back 單一 owner
執行，wrapper 已同步至 `~/.volpred/bin` 並以最小 cron environment smoke。
Production 首跑回收 22/22：21 筆 stale 安全 dead-letter、1 筆以 exact Sent read-back
確認 delivered；DB 回讀 `expired_started=0`、`active_started=0`、22 recovery receipts、
22 terminal WorkItems 與 22 terminal outbox，第二次執行為零 mutation no-op。
Matt review 隨後抓到 ordinary begin 可搶先重領並遺留 predecessor `started` 的
P1 race；初版結案口徑已更正。Follow-up migration 讓普通 begin 看到任何
`started` predecessor 即 fail closed，只有 recovery 能在同一 transaction 先關舊 attempt
再 begin；ordinary-first RED→GREEN 且失敗路徑零 mutation。Python delivery/recovery
也共用同一 execution context。Final Matt Standards／Spec 均 PASS；production
`20260726081120 fence_owned_email_expired_retry` 已套用，catalog/security 與
`0 started / 22 terminal receipts` 回讀一致，16:00 第一個自動排程亦
`recovered_count=0` exit 0。Post-fix 相鄰 CI-parity-on **111 passed**；全專案
功能回歸 **5,191 passed、1 skipped、0 failed**。此 expired-attempt incident 為
**`root_cause_fixed_and_verified`**；Work
Coordinator Issue #9 仍因 owner=`legacy/1`、gate=0 與七日 evidence 未滿而維持
**`contained`**。
Exact-family follow-up 另發現 1 筆 email `retry_scheduled` 已超過 outbox
`available_at`，但原排程只收 expired `started`。Recovery RPC 現一併消費 due retry，
保留原 provider settlement evidence並追加 `retry_due_without_actuator` receipt。
初版 selector 只比對 per-family owner generation；same-generation cross-family
RED fixture 證實此條件不是 authority boundary。Forward migration
`20260726083559_fence_owned_email_recovery_family` 增加 request family fence；
production 實際的 `20260726083856_fence_owned_email_recovery_family` 再增加
effect-kind fence。兩筆 ledger stored statement bytes 已分開保存並納入 PG17 replay；
production catalog 回讀已確認，且其餘 9 筆 publisher/delete rows 未變。
Production 首跑將該 email retry stale dead-letter，回讀
`email_expired_started=0`、`email_due_retry=0`、`email_nonterminal=0`、
email recovery receipts=23，隨後 wrapper no-op。
同日完成 platform program commit 10 的 actuator-side authority fencing contract：
`CommitActuation` 強制綁定 WorkItem id／version、WorkLease token、Primary Authority
fencing token 與 commit-worker identity；完整 write intent 以 canonical SHA-256 交由
注入的 authority interface 回讀，stale token、authority unavailable 與不完整／錯綁
grant 都在 Git writer 前 fail closed。成功 receipt 只保留 request hash 與兩個 authority
reference，不保存 raw token，且沿用 commit object／parent／exact paths／blob hashes
read-back。此 checkpoint 尚未提供 live Postgres authority adapter、
`ChangeDelivery.land`、durable receipt 或正式 caller，故不構成 commit ownership
cutover；主控租約 acquire／renew／demote 仍屬 program step 34。
同日完成 platform program commit 11 的 shadow EffectRequest identity contract：
`EffectDelivery.request()` 將 WorkItem id／version、effect kind、target、payload
reference + SHA-256、risk、requester 與 typed acknowledgement expectation 綁入
canonical request digest；等價 replay 回傳同一 immutable view，同 key 不同 payload
fail closed，並發 replay 只 materialize 一筆。117 個 delivery scoped tests 通過，其中
含 32 路 concurrency 與 64 組 payload-bound replay property cases。此 checkpoint
尚未建立 program commit 12 的 PostgreSQL store／transactional outbox，也沒有
effect-worker fencing、provider delivery、retry／dead letter 或 downstream read-back，
因此不會產生外部效果，現行 publisher／notification ownership 不變。
同日續做 platform program commit 12 的第一個 durable checkpoint：
private PostgreSQL migration 以單一 transaction 原子建立 EffectRequest 與唯一 outbox
row；request 先鎖 idempotency key，等價 replay 跨 adapter instance 仍只留一筆，
payload drift fail closed，注入 outbox insert failure 時兩表均為零。WorkItem FK 與
exact version 綁定阻止 unknown／stale identity。outbox claim 使用 database clock、
`FOR UPDATE SKIP LOCKED`、有限 lease 與過期重領；worker role 只能執行 named
`SECURITY DEFINER` functions／讀 token-redacted projection，不能直接 mutation。
100 個 Effect Delivery scoped tests 通過，包含真實 PostgreSQL transaction rollback、
雙 worker concurrent claim 與 crash-after-claim recovery。此 checkpoint 尚未把 request
合併進 Work Coordinator mutation transaction，也沒有 delivery acknowledgement、
retry／dead letter、Primary Authority fencing 或 provider adapter；program commit 12
與 Effect Delivery ownership cutover 均未完成。
同日完成 program commit 12 的第二個 durable checkpoint：`settle_outbox` 將
outbox sequence／effect id／attempt／worker／claim token 綁成 fenced settlement，
typed acknowledgement 必須精確匹配原 request；failure 只由 provider 分類是否
retryable，30 秒起始 exponential backoff、一小時 cap、五次上限與 dead-letter
disposition 由 PostgreSQL implementation 統一持有。每次 settlement 在同一 transaction
寫 token-digest-only immutable receipt 並更新 outbox／EffectRequest；等價並發 replay
回傳同一 receipt，late token、changed outcome、acknowledgement drift 與後半段注入失敗
均 fail closed／rollback。109 個 Effect Delivery scoped tests 通過。尚未接 provider
adapter、Primary Authority、正式 Work Coordinator caller、live migration 或真實
downstream read-back，因此仍不構成外部效果 ownership cutover。
同日完成 program commit 13 的第一個 safe email notification provider adapter：
只接受 `email.notification.send`／`safe`／單一收件人與同 target 的
`email.sent-mail.readback` typed contract；raw payload bytes 必須與 EffectRequest
SHA-256 相符。Adapter 以 effect identity 導出穩定 Message-ID，SMTP 前先查 Sent
mailbox 以避免可驗證重播重寄，provider write 後再由獨立 IMAP adapter 回讀 exact
message bytes；Message-ID、recipient、subject、plain／HTML body 全相符才產生
`AcknowledgedEffect`，查無訊息為 retryable failure，內容漂移 terminal fail closed。
既有 `EmailNotifier` 只新增可選 Message-ID threading，現行 caller ownership 不變。
133 個 Effect Delivery／EmailNotifier scoped tests 通過，全程未連網、未寄信；尚未接
durable outbox claim／settlement worker、Primary Authority、正式 Work Coordinator
caller、live migration 或真實 downstream smoke，因此仍不構成 notification ownership
cutover。
同日續做 program commit 13 的 authority-fenced worker／live shadow checkpoint：
private `EffectOutboxWorker.run_once` 收斂 claim、inspect、Primary Authority authorize、
immutable payload read、typed email provider、fenced settlement 與 receipt 回讀；
authority request hash 綁定 effect／work／outbox／worker／primary token 全部 identity，
receipt 只保存 token-redacted outbox claim ref 與 Primary Authority ref，舊 unfenced
settlement overload 已移除。Production IMAP adapter 改用 quoted mailbox argument 與
RFC 6154 `\Sent` special-use discovery，修正真實 Gmail command parse 與在地化 mailbox
問題。五個 private migrations 已套用 live Supabase；PG17 非 superuser migration
ownership／membership 路徑由真實失敗修正，performance advisor 發現的 receipt FK index
亦以 forward migration 補齊並複驗消失。Controlled shadow attempt 2 已寄送 stable
Message-ID email、由 Gmail Sent Mail 回讀 exact bytes、settlement 並從 private views
回讀為 `delivered`／`acknowledged`；143 個 scoped tests 通過。仍缺 live Primary
Authority adapter、durable payload writer、正式 Work Coordinator caller 與 ownership
transaction，故 program commit 13／notification ownership 整體仍是 `contained`。

同日 follow-up 已加入 live-shaped `PostgresEffectPayloadStore`、
`PostgresAuthorityStore` 與 `PostgresEffectAuthority`。Payload bytes 由 private
named functions immutable 保存並由資料庫綁 SHA-256，worker 在 provider 前再次驗證；
Primary Authority 以 database clock、epoch 與 hashed fencing token 管 lease，effect
grant 則原子核對 exact outbox claim／EffectRequest／WorkItem／payload／ack identity。
Settlement trigger 只接受資料庫已簽發的 matching grant。五張新表全數 FORCE RLS，
definer functions 固定 `search_path`、revoke PUBLIC 並以 no-login owner 與最小 worker
grants 隔離。Supabase migration receipt
`20260723230547 operations_core_effect_payload_primary_authority` 已用同名 local receipt
stub 對齊；較晚 canonical migration 可在乾淨 PostgreSQL 17 環境重播兩次。Live
read-back 證實五表、privileges、function ownership／search path 與兩個 index 正確，
`volpred_ops` security advisor 0 lint，performance advisor 只有 10 個 INFO。既有八筆
舊 migration-history drift 未被 repair。Payload／authority seam 的具體缺口已完成
五步 gate；但正式 Work Coordinator caller、production ownership transaction、
unique-owner acknowledgement 與 rollback rehearsal 尚缺，program commit 13 整體仍是
`contained`。

同日 production ownership follow-up 已把 `send_alert` email branch 接到正式
Work Coordinator／Effect Delivery transaction。PostgreSQL 以單一
`email.ops_alert` owner row + monotonic generation CAS 控制 legacy 與
operations_core 唯一路由；DB unavailable、stale generation、active attempt transfer
或 request drift 都 fail closed。Service-role-only RPC 內原子完成 WorkItem、immutable
payload、EffectRequest／outbox、Primary Authority、provider settlement 與 receipts，
private tables FORCE RLS，public RPC 固定空 search path 並撤銷 PUBLIC／anon／
authenticated。

PG17 transaction regressions 與 267 個相關 tests 通過。Live
`legacy/1 → operations_core/2` 後，第一封暴露 SMTP CRLF 對 LF 的 read-back 假
mismatch；修成 canonical newline comparison 並用 SMTP policy 回歸後，第二封真 alert
的 Work／effect／outbox／attempt、payload hash、Primary Authority release 與 Gmail
Sent exact-byte evidence 全部一致。接著完成
`operations_core/2 → legacy/3 → operations_core/4` rollback rehearsal，stale
generation request 零落地，final live read-back 為唯一 owner `operations_core/4`、
零 active attempts。Remote migration receipts `20260723234435`／`20260723235106`
均有同名 local stub，ownership FK advisor gap 已補；本 scope security lint 為零。
因此 program commit 13 的 `email.ops_alert` production ownership 為
`root_cause_fixed_and_verified`；其他 effect family 不在本次完成宣告內。

2026-07-24 08:07 CST 的 Codex failover read-only 複驗再次從 production owner
interface 回讀 `notification-owner.v1`：effect family=`email.ops_alert`、
owner=`operations_core`、generation=`4`、changed_at=
`2026-07-23T23:48:57.414826+00:00`；caller／owned delivery／Sent read-back scoped
suite 同班為 `85 passed`。本次未寄信、未轉移 owner，也不把單一 effect family 的
接管擴張為整個 Effect Delivery 已完成。

同日開始 program commit 14 的 publisher 單篇 sync 切片：
`PublisherArticleSyncEffectAdapter` 只接受 payload-bound、safe、單一 Supabase article
target 與 typed read-back expectation。provider 先讀後寫，projection 已收斂的等價
replay 不再 upsert；需要寫入時，文章完整 row 與 tags 必須全部回讀一致，否則回傳
typed retryable failure，由既有 PostgreSQL outbox 統一 backoff／dead-letter。
production `SupabaseArticleProjectionAdapter` 與 fake adapter 共用同一 seam；原本散在
`sync_article()` 的 row shape 已抽為 `projected_article_row()`，供 direct writer 與
effect read-back 共用；explicit empty tags 會刪除 stale join rows，不再無限 mismatch。
9 個新 cases 與 193 個 scoped 相鄰 regressions 通過，另有 1 個既有 skip。
09:13 CST 再以 production adapter 對最新 published article `mile_f00be77f` 做
read-only live smoke，完整 row／tags 回讀 `matches=true`（evidence SHA-256
`faf3920540be40ad90ab7d8e2392be39d52cd9e38eda5f896dca31a2699ee3de`）；未產生外部寫入。
正式 publisher caller、durable payload transaction、effect-family Primary Authority、
唯一 owner cutover 與 live rollback rehearsal 尚未完成，現行兩條 single-article
write path 也未移除，因此此 checkpoint 僅為 **`contained`**。

同日下一個 checkpoint 將 formal caller 收斂成
`OwnedPublisherArticleSync.sync(command) -> receipt` 的單一 external interface。
caller 不再組裝 WorkItem、immutable payload、EffectRequest／outbox、owner
generation、兩種 claim token、Primary Authority 或 settlement。private store seam
同時有 fake 與 service-role-only Supabase adapter；publishable key 不會被當成權限
fallback，owner transfer 必須用 generation CAS，rollback identity 也在 interface
固定。request／begin／provider 三道 lease read-back 與 begin identity drift cases
皆證明 projection write 為零，相鄰 suite 為 `171 passed`。四個 production RPC、
owner row／migration、現行 writer routing、live cutover 與 rollback rehearsal 尚未
落地，故這是 formal caller contract checkpoint，program commit 14 仍為
**`contained`**。

同日 publisher ownership transaction 的 local PostgreSQL migration 已補齊 owner
read／generation-CAS transfer、durable request、begin 與 settlement 五個
service-role-only RPC，並完成 cutover → acknowledged delivery → rollback → stale
generation rejection → recutover transaction rehearsal。獨立複驗抓到 settlement
一度誤從 token-redacted authority read model 讀取 fencing-token hash；修正後
SECURITY DEFINER 直接鎖 private lease table，security-shape regression 也明確鎖住
begin/read-model 與 settle/private-table 的不同契約。PostgreSQL suite 為 `45 passed`，
owned publisher／email 相鄰 suite 為 `10 passed`。production migration、live owner
transfer、writer routing 與 live acknowledgement／rollback 尚未執行，所以此
checkpoint 仍為 **`contained`**。

同日兩個 forward-only production migrations 已落地：
`20260724151111 operations_core_publisher_article_ownership` 與
`20260724152359 operations_core_publisher_article_terminal_replay`。第二個 migration
修正「settlement 已成功但 HTTP response 遺失」的終端重播：相同 idempotency request
會從 durable terminal attempt 組回 receipt，formal caller 在 begin／provider 前直接
返回；PG17 regression 實際確認 attempt count維持 1。Production catalog回讀 function
owner、SECURITY DEFINER、空 search path、service-role-only EXECUTE、四張 private
table FORCE RLS／service-role SELECT denial與 definer public CREATE denial全數通過；
publisher owner仍為 `legacy/1`，request／active attempt／lease皆為 0，沒有文章寫入。
Security advisor無本 scope finding；performance advisor僅列出三個早於本 migration
存在、尚未累積使用統計的 shared ownership indexes。

現有 Python single-article writer已改成 database-owner router，active frontend repo
也在 commit `ae14890` 加入 full-feed 409與single-report delegated fence；完整
PostgreSQL suite `45 passed`、caller／adapter `22 passed`、frontend typecheck通過。
但 frontend repo仍比 `origin/main` ahead 9 commits，依治理規則本輪未 push，因此 fence
尚未部署到 live route。Production owner不得在此時切換；program commit 14維持
**`contained`**。下一步是由有 push／deploy authority 的流程發布 active frontend，
回讀 live version與 owner-fence行為後，才執行 CAS article smoke、exact Supabase
read-back、rollback與 stale-generation refusal。

同日 formal caller補上 settlement／terminal replay response 的 fail-closed契約。
先前 provider雖完成 exact read-back，caller卻直接返回 service-role receipt；若 response
的 generation、Work／Effect／attempt、Primary Authority ref、evidence或 lifecycle
tuple漂移，上游仍可能把不屬於本 transaction的 terminal response當成結果。現在
`OwnedPublisherArticleSync`逐欄核對 durable attempt與 provider outcome，並固定三組
合法 lifecycle tuple。兩個 public-interface RED injections修正前均為
`DID NOT RAISE`，修正後與 publisher／PostgreSQL相鄰套件共 `69 passed`，compileall與
diff check通過；沒有 remote write或 owner mutation。這個 response-boundary根因為
**`root_cause_fixed_and_verified`**，但 frontend deploy、live owner cutover與rollback
仍缺，program commit 14整體狀態不變。

2026-07-25 完成 program commit 14 production closure。Active frontend commit
`ae14890` 由 clean detached worktree 經 canonical Zeabur upload部署為
`6a6393ea4727f1da77de7137`（`RUNNING`），live feed／strategy API通過。Generation 6
下 full-feed route回 409、single-report route回 delegated；published article
`crisis_protection_20260316_002220` 的 formal caller receipt為 attempt 1、
`succeeded/delivered`，evidence SHA-256
`9ecceb0468f16bec17b2e0a418db4a4ae4c512850c1e39723122996ef33bcbe1`。Exact rollback
回讀 `legacy/7`，final recutover回讀 `operations_core/8`，舊 generation 7 CAS被拒，
generation 8兩條 frontend fence再次通過。Canonical
`scripts/rehearse_publisher_cutover.py` 把 mutation前 single-report preflight、live
fence、typed receipt與任何失敗的 automatic rollback制度化；四個 regression cases
覆蓋成功與 failure paths。因此 program commit 14為
**`root_cause_fixed_and_verified`**。整體 operations-core與 program commit 34仍因
真實 network partition／Supabase outage／五分鐘 RTO等未完成而維持
**`contained`**。

同日開始 program commit 15 的 full-sync convergence checkpoint。Failure injection
證實 `sync_full()` 在 article／memory／risk provider回 `False`後仍推進
`feed_mtime`／count cursor並由 CLI回綠，讓未落地 projection被 unchanged gate永久
跳過。底層現以 `article_retry_slugs`保存明確重試輸入，article失敗不推進 mtime，
purge retry不會在 prerequisite write失敗時被清掉；memory cursor只覆蓋下游已確認的
連續前綴，risk與delete reconcile也進統一 failure contract，CLI遇任何 failure均
非零。四個 RED injections轉 GREEN，相鄰 sync/reconcile suite
在 clean tracked snapshot為 **31 passed, 1 skipped**。此 silent cursor advancement根因為
**`root_cause_fixed_and_verified`**；program commit 15仍缺 formal outbox ownership、
週期 convergence receipt與 rollback rehearsal，所以維持 **`contained`**。

同日補完 program commit 15 的週期 convergence receipt。舊 audit只查 local feed
已知 slug，因而永遠無法觀測 Supabase-only orphan；local視窗為空時還會跳過 remote
query並假綠。Receipt v2改以相同72小時 published window分頁讀完整 remote projection，
雙向計算 missing／orphan，且 local為空仍必須查 remote；unavailable failure contract
維持 fail closed。兩個 orphan regressions、pagination／URL contract與既有
audit/schedule suite共 **11 passed**；production read-only smoke為 local=14、
Supabase=14、missing=0、
orphan=0、live 404=0。此 false-convergence根因為
**`root_cause_fixed_and_verified`**；formal outbox ownership與 rollback rehearsal
仍缺，因此 program commit 15維持 **`contained`**。

同日關閉 hourly feed-sync 的 scheduler false-green。舊 CLI即使
`apply_diff()`已回 `failed=1`仍 exit 0，導致每小時 wrapper留下成功 receipt。現在
feed-sync external interface提供 aggregate `acknowledged`，apply未明確全數確認即在
輸出 JSON evidence後 exit 1；quiet clean維持靜默成功。Canonical schedule已登記
0／1語意，wrapper propagation regression也鎖住 `cron_emit_exit`及最終 exit。
Failure injection由0轉1；相關與相鄰套件 **69 passed**，production read-only dry-run
為 feed/db 1877/1877、drift 0，wrapper三份 lockstep。此局部根因為
**`root_cause_fixed_and_verified`**；formal full-sync outbox ownership與rollback
rehearsal仍缺，program commit 15維持 **`contained`**。

同日建立 program commit 15 的 immutable reconcile EffectRequest shadow contract。
`prepare_publisher_article_reconcile()`把 Work identity、canonical feed SHA與本次完整
article objects收進單一safe interface，effect constants與payload hash不再散給caller；
payload內嵌且canonical排序，retry不會從已漂移feed重建intent。Batch provider先讀、
只寫mismatch、再逐篇exact read-back；等價 replay零寫入，非法contract由durable
worker dead-letter。八個新cases與相鄰套件 **36 passed**；production read-only
`mile_30b22ca5`完全相符。Hourly production caller／payload store／outbox owner、
destructive delete family與rollback rehearsal尚未接通，所以本checkpoint及program
commit 15仍為 **`contained`**。

同日safe reconcile ownership已從shadow接到production。`feed_sync`依
`publisher.article.supabase.reconcile` owner generation在legacy逐篇caller與
Operations Core immutable batch之間路由；batch由private payload store、WorkItem、
EffectRequest/outbox、primary lease及typed read-back receipt完整擁有。Live rehearsal
走完`legacy/1 → operations_core/2 → legacy/3 rollback → operations_core/4`，
回讀work succeeded、effect/outbox delivered、local/Supabase 14/14、drift 0，且
schedule-equivalent hourly command exit 0；最終tracked-snapshot selected suite
91案通過（含完整47-case PostgreSQL contract檔）。這個safe ownership切片為
**`root_cause_fixed_and_verified`**。破壞性delete
仍保留既有floor/cap/dump guard，尚未收進獨立formal effect／owner／rollback，因此
program commit 15與operations-core umbrella仍為 **`contained`**。

同一production slice隨後補上single-article與batch true-external mutation boundary的
authority fence。兩條failure injections都讓provider第一次Supabase read-back後換成
新epoch／fencing token；修正前舊attempt仍會upsert，修正後formal callers把原始lease
identity傳入provider，每筆真正write前重新核對key／holder／epoch／token／acquired-at，
漂移即以ownership loss中止且不settle。回讀projection write=0、settlement=0；相鄰
套件 **82 passed**。
此根因為 **`root_cause_fixed_and_verified`**，但destructive delete family仍未formal
cutover，故program commit 15與umbrella狀態不變。

Destructive delete後續先完成零I/O的獨立intent checkpoint。兩段式deep module以exact
canonical feed bytes建立scope並在任何EffectRequest前執行floor／cap、candidate
不在feed、identity唯一性與六張cascade table／七條FK edge完整性；module自行產生包含
article及impressions／reactions／雙向relations／tags／comments／question links的
deterministic recovery JSONL。只有approval artifact的scope SHA精確相符才會materialize
risk=`destructive`的EffectRequest；approval drift也不能沿用idempotency key。
Effect Delivery與相鄰 **156 passed**，且本module沒有provider或hourly接線，所以零
remote mutation。
Owner CAS、durable approval verifier、delete/read-back adapter、restore executor與live
rollback/convergence仍缺；此checkpoint誠實維持 **`contained`**，program commit 15與
umbrella狀態不變。

同一班隨後用production catalog推翻intent初版的五表假設：`article_relations`另有
`source_id`與`target_id`兩條cascade edge。Delete contract改為單一六表／七edge來源；
legacy apply新增service-role-only live catalog equality gate，並把完整article row、
所有child rows、feed SHA與fsync/read-back後dump SHA一起保存。任何schema drift、
child read失敗或capture期間feed換代都零刪除。Production ACL與七edge RPC回讀通過；
read-only reconcile為1877/1877、ghost=0、deleted=0，相鄰
**200 passed, 1 skipped**。此recovery完整性根因為
**`root_cause_fixed_and_verified`**，但owner/provider/restore/live rollback缺口不變。

同班再補上destructive worker execution adapter。原scope-bound EffectRequest現在只有
在durable approval仍active、全部candidate的article與六表cascade bytes都exact-match
時才可進mutation；每筆delete前會重新read-back、重驗approval，並讓owned caller緊貼
mutation重驗原Primary Authority epoch。第二筆scope drift時維持全批零刪除，
authority換代直接向外拋ownership loss；effect只有在每筆typed absence read-back都帶
合法evidence ref/hash時才acknowledge。Failure injections與相鄰套件
**127 passed**。此execution-contract根因為
**`root_cause_fixed_and_verified`**；production Supabase projection、delete owner CAS、
exact restore executor與live delete→rollback→convergence尚未完成，所以program
commit 15與operations-core umbrella仍為 **`contained`**。

同班另修正current Test Suite連續紅燈：cron alert metadata原本只能把整支log標為
`findings`，無法表達`audit_publish_sync`的exit 1=findings、exit 2=unavailable。
Schedule新增typed `findings_exit_codes=[1]`；host health只豁免code 1，code 2仍會進
infra failure。精確重現與相鄰publisher／audit suites共 **121 passed**，此CI契約根因
為 **`root_cause_fixed_and_verified`**。

同日 Change Delivery follow-up 把 program commit 10 的 fake-only authority 推進為
private PostgreSQL adapter。`PostgresCommitAuthority` 先重算完整 commit intent
SHA-256，再由單一 `authorize_commit_write` transaction 鎖定並核對 running WorkItem
version、未過期 WorkLease token 與 database-clock Primary Authority lease；成功只落
token-redacted WorkLease／Primary Authority refs，等價 replay 回同一 immutable grant。
Grant table FORCE RLS，worker 只有 named function execute，PUBLIC 無 execute／table
read；PG17 non-superuser migration replay 與相關 Change／Effect Delivery suite 共
138 tests 通過。此 migration 未套 live；`ChangeDelivery.land`、durable post-commit
receipt、external Git interval 的 lease revalidation、正式 caller 與 rollback
rehearsal 仍缺，因此 Change Delivery ownership 保持 `contained`。

同日下一個 bounded slice 補上 `ChangeDelivery.land()` 與 durable post-commit
settlement。Landing 在 actuator 已回讀 commit 後保存 `commit_unsettled` checkpoint；
DB 暫時失敗的 replay 只續 settlement，不會再寫一次 Git。PostgreSQL
`settle_commit_write` 在 external write 後重新驗證 exact running WorkItem、
WorkLease 與 Primary Authority，才保存 immutable、token-redacted
`change-delivery-receipt.v1`；等價 receipt 在 lease 日後過期仍可回讀，漂移 replay
fail closed。PG17/FORCE RLS 測試另抓到 immutable grant 不可用 `FOR UPDATE`，final
contract 只 SELECT grant、只鎖可變 WorkItem；174 個 scoped 相鄰 tests 通過。Live
catalog 回讀新 tables/functions 皆不存在，確認 migration 仍未套 live；formal
caller、durable proposal store、workspace materializer、Git ownership cutover 與
rollback rehearsal 仍缺，所以 Change Delivery 整體維持 `contained`。

同日 Change Delivery interface regression 證實 `commit-actuation.v1.observed_at`
原本只驗非空，非法字串與 naive wall-clock 都能穿過 `land()` 進入 settlement；
PostgreSQL 可能依 session timezone 解讀後者，或在 Git 已落地後才拒絕前者。既有
actuation receipt gate 現在先 parse 並要求 timezone-aware，失敗時保持 ChangeSet
`proposed` 且不呼叫 settlement。公開 `land()` seam 的兩個 RED cases 已轉 GREEN，
Change Delivery unit suite 22 passed；這個 timestamp identity 缺口為
`root_cause_fixed_and_verified`，但未改變整體 ownership 的 `contained` 狀態。

同日下一個 Change Delivery slice 把原本只存在 Python instance dict 的 proposal、
landing-command digest、`commit_unsettled` actuation 與 final receipt linkage 收進
private `ChangeSetStore` seam。in-memory／PostgreSQL 兩個 adapter 共用同一 contract；
新 process 在 checkpoint 已提交後能讀回 actuation，只 replay settlement，Git actuator
零次重呼。PostgreSQL transaction 另核對 WorkItem version、proposal／command hash、
parent／paths／actor／timezone-aware timestamp 與 immutable settlement receipt；
FORCE RLS、PUBLIC revoke、named-function-only worker access、raw-token absence 及
non-superuser migration replay 均通過。Change／Effect／Git 相鄰 suite 共 68 tests
通過。Production catalog 唯讀回讀所有新舊 Change Delivery tables/functions 仍為
`null`，確認沒有部署；checkpoint 已提交後的 restart ambiguity 已消除。

同日 lost-return follow-up 封閉 Git commit 已成功、但 receipt return／ChangeSet
checkpoint 尚未完成的窄 crash window。`GitCommitActuator` retry 仍先重驗 WorkLease
與 Primary Authority；HEAD 已前進時，只接受 expected parent 後第一個 first-parent
commit，且 parent、完整 message、exact paths、全部 blob SHA-256 必須精確符合原
authority-bound command，才以 Git committer 的 timezone-aware timestamp 重建 receipt。
任何 lookalike／stale commit 均 fail closed 且不再呼叫 writer。跨 process regression
證明 commit 後立即遺失 return 時，restart 能 recovery → checkpoint → settlement，
且不產生第二筆 Git commit；scoped suite 37 passed。

同日下一個 bounded slice 完成 candidate workspace→canonical checkout 的 production
materializer seam。`ChangeDelivery.land()` 直接沿用 proposal 的 linked worktree；
canonical writer 在單一 common-dir lease 內重驗 source HEAD、clean index、完整 dirty
path set 與 content hashes，才 materialize、stage、commit 並回讀 object。Canonical
target 有 foreign bytes／symlink／unowned deletion 時在覆寫前拒絕；hook／commit failure
會還原原 exact-path bytes，process kill 留下的 exact candidate residue則可冪等續作。
Git writer／Change Delivery／actuator scoped suite 72 passed，canonical writer audit
0 violations。Materializer overwrite／rollback seam 為
`root_cause_fixed_and_verified`；formal caller、live migrations、Git ownership
cutover 與正式 rollback rehearsal仍缺，所以 Change Delivery 整體維持 `contained`。

同日 materializer follow-up 發現 `changeset.v1` 只綁 path／blob SHA-256，沒有綁定
Git tree mode；相同 proposal 可落成 `100644` 或 `100755`，lost-return recovery 也會
接受 mode 不同的 lookalike。現階段不擴張尚未 cutover 的 durable schema，而是把
bounded policy 機械化：tracked regular file 保留 base mode，new file 固定
`100644`。Proposal、lease 內 source／canonical target materialization，以及
commit-object／recovery read-back 三層都核對 mode。四個 RED cases 轉 GREEN，完整
scoped suite 76 passed；具體 identity 根因為 `root_cause_fixed_and_verified`，
Change Delivery 整體仍因 formal caller、live migrations、ownership cutover 與
rollback rehearsal未完成而維持 `contained`。

同日 lost-return provenance follow-up 證實，原 recovery 即使核對
parent／message／paths／blob／mode，仍會接受另一個 writer 先落下的 bitwise
lookalike first child，並錯誤產生本次 authority receipt。Actuator 現在於 authorize
後把完整 authority-request SHA-256 寫成
`Volpred-Commit-Authority-Request` commit trailer；正常 post-write read-back 與
historical recovery 都要求 trailer 精確匹配，raw fencing token 不進 Git object。
Unbound lookalike regression 已先 RED 後 GREEN，正常 commit trailer 與 receipt
digest 亦精確對帳；owner-generation follow-up 另釘住舊 generation 的合法 trailer
不可被新 generation recovery 接受。此 provenance identity 缺口為
`root_cause_fixed_and_verified`。Formal caller、live migrations、Git ownership
cutover 與 rollback rehearsal仍未完成，因此 Change Delivery 整體維持
`contained`。

同日 formal caller follow-up 已新增 `OwnedChangeDelivery` 與 durable
`git.commit` owner generation。Operations Core 只有在 owner row 為
`operations_core` 時可 propose／land；generation 由 landing digest 一路綁到
authority、actuation、settlement 與 final receipt，DB transaction 會再次核對 owner，
舊的無 owner RPC 對 worker 已失權。Settlement 與 `complete_work()` 原子化，caller
並回讀 terminal WorkItem。PG17 non-superuser clean migration replay、RLS／權限回讀、
unsettled rollback refusal，以及臨時 canonical repo + linked worktree 的完整
generation 2 commit → generation 3 rollback → generation 4 re-cutover 均已通過。
此 formal caller／ownership seam 在 shadow 為 `root_cause_fixed_and_verified`；
其後五筆 private migrations 已套到 production，live read-back 證實 owner 仍是
`legacy/1`、grant／receipt／ChangeSet 皆為 0、五張新表 FORCE RLS、PUBLIC deny、
worker 只可用 owner-fenced overload。首次 advisor 回讀抓到 ChangeSet delivery-receipt
FK 缺 covering index；forward migration 與 PG17 contract 補齊後該 finding 消失，
`volpred_ops` security advisor 為 0 findings。Production Git owner 尚未切換，正式
CAS／live smoke／rollback rehearsal未執行，因此 umbrella 狀態仍是 `contained`。
同日 live Management SQL 對 private owner function 的 permission denial 證實缺少
production operator seam。新增兩個 service-role-only public RPC 與
`SupabaseCommitOwnerStore`，只委派原 private read／CAS transaction；definer owner、
空 search path、anon／authenticated／PUBLIC deny、service role 無 table SELECT 均由
PG17 與 live catalog 回讀。Production migration receipt
`20260724074117 operations_core_commit_ownership_rpc` 已存在，HTTP adapter 回讀仍為
`legacy/1`，兩類 advisor 對新 RPC 零 findings。Owner 沒有 transfer；完整 production
delivery adapters 與 live smoke／rollback rehearsal仍缺，umbrella 仍為 `contained`。
同日 ChangeSet lifecycle 再新增五個 service-role-only RPC 與
`SupabaseChangeSetStore`，共用 narrow HTTP transport，禁止 publishable key fallback；
PG17 clean／idempotent migration、ACL 與實際 service-role create/read 回歸通過。
Production receipt `20260724081714 operations_core_change_set_rpc` 已回讀；live HTTP
missing lookup 為 null、owner=`legacy/1`、ChangeSet count=0，沒有 transfer 或寫入。
同日 `SupabaseCommitAuthority` 與一個 service-role-only RPC 補上 production
authority adapter；它保留既有 `CommitAuthority.authorize()` interface，process 先
重算 request digest，RPC 只委派 private owner／WorkLease／Primary Authority
transaction。PG17 clean／idempotent replay、actual service-role grant/replay、ACL
及 135 個相鄰 tests 通過。Production receipt
`20260724085535 operations_core_commit_authority_rpc` 已回讀；live HTTP adapter 在
`legacy/1` 下 typed fail closed，grant／receipt／ChangeSet 再次回讀皆為 0。
同日 `SupabaseCommitSettlement` 與 service-role-only RPC 補上 production settlement
adapter；process 重算 settlement digest，RPC 只委派 private owner／WorkLease／
Primary Authority／receipt／Work completion transaction，回傳後逐欄核對
token-redacted evidence。PG17 clean／idempotent replay、actual service-role settlement、
ACL 與相鄰 140 tests 通過。Production receipt
`20260724092237 operations_core_commit_settlement_rpc` 已回讀；live HTTP adapter 在
`legacy/1` 下 typed fail closed，前後 grant／receipt／ChangeSet 均為 0。Work read
model 後續新增 service-role-only bounded snapshot RPC 與 `SupabaseWorkReadModel`，
並由 `build_supabase_owned_change_delivery()` 將全部 production adapters 接成 formal
caller。PG17 clean／idempotent replay、ACL、實際 service-role read 與相鄰 114 tests
通過；production receipt `20260724101005 operations_core_work_read_model_rpc` 已回讀。
Live 成功 WorkItem snapshot 為 items=1／events=4／receipts=1，probe 前後
WorkItem=19、ChangeSet／grant／commit receipt=0、owner=`legacy/1`，新 RPC 無 advisor
finding。這只核可 remote read/composition seam；尚未執行 CAS、真實 commit、exact
Git read-back或 rollback rehearsal，umbrella 狀態不變。
同日 `SupabaseAuthorityStore` 與四個 service-role-only RPC 補上 production
Primary Authority lifecycle adapter；既有 private PostgreSQL transactions仍唯一擁有
database-clock acquire／renew／authorize／release policy，HTTP seam 不回傳 raw
fencing token。PG17 clean／idempotent replay、實際 service-role lifecycle、ACL 與
transport contracts 通過；production receipt
`20260724101355 operations_core_primary_authority_rpc` 已回讀。Live
`smoke:no-external-effect` acquire→authorize→renew→release 後，canonical holder／
token digest 均已清空，grant／receipt 各 1，兩類 advisor 無新 RPC finding。這只核可
remote authority seam；未執行 Git owner CAS、commit、effect 或 host failover，
program commit 34 與 Change Delivery umbrella 仍為 `contained`。
同日再以 `HostAuthoritySession` 收斂 host-side acquire／renew／demote state：active
重入不重發 token；status 只回 token-redacted identity；renew、release 或 local expiry
失敗都先清除本機 lease並轉為 demoted。共享 store 的雙 host injection、renew
unavailable、release response lost 與 expiry regressions，加上既有 Supabase／PG17
authority contracts，共 12 passed。這使 session lifecycle 的局部缺口達
`root_cause_fixed_and_verified`。

同日 `HostAuthorityKeepalive` 再成為週期性 renew 的單一 process owner：正式 caller
只能從 keepalive 取 lease，stop／renew failure／dead worker／join timeout 都先封鎖
本機 enable gate，status 不洩漏 raw token。後續 startup race 回歸抓到 remote acquire
原先不在 keepalive lock 內：並行 start 可建立兩個 renew owner，並行 stop 可先返回再被
starter 重開 gate。Acquire、worker publication與 running gate 現已原子化；
concurrency／composition與相鄰 authority suite 共 24 passed；production service-role
no-effect rehearsal 完成 A renew/release、B 同 key acquire/release，epoch `1 → 2` 且
final state 都是 `stopped`。這個 canonical
keepalive 缺口達 `root_cause_fixed_and_verified`；但全 effect-family enable gate與
真實雙 Mac network-partition／Supabase outage／五分鐘 RTO rehearsal尚未完成，所以
program commit 34 整體仍是 `contained`。
同日下一個production slice新增
`scripts/rehearse_primary_authority_outage.py`，只用隔離generated authority key，
先後回讀publisher=`operations_core/8`，並在一次healthy renew後把authority adapter
切到真實不可達PostgREST transport。正式300秒lease／60秒renew live run讓local gate
於60.526秒內demote，transport恢復後standby仍等DB-clock expiry，於239.962秒內取得
exact next epoch `1 → 2`，最後release為`stopped`。Durable receipt
`storage/ops/primary_authority_outage_rehearsal_latest.json`回讀successful claims=2、
duplicate claims=0、effect requests/provider calls=0，publisher fence前後完全一致；
authority相鄰suite共28 passed。這使live Supabase outage與五分鐘RTO的單host operator
seam達`root_cause_fixed_and_verified`；真正跨兩台實體Mac的network partition與其餘
effect-family cutover仍缺，因此program commit 34 umbrella保持`contained`。
同日 operator seam又新增`primary`／`standby`／`verify-pair`三個process角色：
shared rehearsal ID決定性導出隔離key，兩端receipt含machine fingerprint與code hash，
配對receipt綁定兩個payload SHA-256並機械驗distinct hosts、相同implementation、
exact next epoch、DB-clock expiry後300秒內handoff、publisher fence不變與零
duplicate/effect/provider。local interface
suite 6 passed；兩台實體Mac尚未產出production paired receipts，所以umbrella仍為
`contained`。
同日 generic durable outbox worker 也移除 caller 自填 raw authority identity／token
的介面，改從 keepalive lease gate 取得，並在 claim、authorize、provider 三個階段前
重驗同一 lease identity。Email notification 與 publisher article sync 都走這個深模組
seam；closed gate、錯誤 authority family與 epoch／token replacement 的 failure
injection 均在 provider 前拒絕，正常 renew 的 expiry 延長仍可通過。Authority／Effect
Delivery／PG17 相鄰套件共 88 passed，這個 generic worker 局部根因為
`root_cause_fixed_and_verified`。但 production `email.ops_alert` ownership RPC 仍會
自行 acquire family-specific lease，尚未 revalidate host keepalive lease；因此全
effect-family enable gate與 program commit 34 umbrella 繼續是 `contained`。
同日下一個 production slice 把 `OwnedEmailNotification` 接到 canonical host
keepalive。Caller不再製造 Primary Authority token，而是在 request、begin 與 provider
前重驗 `notification:email.ops_alert` 的同一 holder／epoch／token；錯誤 family、
closed gate、lease replacement或 RPC 回傳不同 authority identity都在 SMTP 前
fail closed。Forward migration把 begin RPC從「自行 acquire」改為只接受既有且未過期
的 host lease，settlement也不再 release，release lifecycle唯一歸 keepalive stop。
PG17 clean／idempotent／non-superuser migration與 transaction contract通過：無預持
lease時 begin全 transaction rollback，settlement後 lease仍由 host持有，最後 explicit
release成功。Production migration
`20260724131707 operations_core_owned_email_keepalive_gate` 已套用；live回讀確認
兩個 RPC仍為 `volpred_ops_definer`／fixed empty search path／service-role-only，
begin self-acquire=false、settle release=false、owner=`operations_core/4`、current
lease holder=null、live attempt=0。此 family gate局部根因為
`root_cause_fixed_and_verified`；其他 effect family與真實雙 Mac network partition
仍未完成。單host live Supabase outage／五分鐘RTO已由上方receipt證實，但不取代跨
實體host演練，因此program commit 34 umbrella保持`contained`。
同日多 family盤點抓到 generic outbox claim沒有 provider capability filter：任一 narrow
provider worker都會拿全域最舊 row，publisher上線後可能先拿 email effect並把合法 intent
錯判為 unsupported後 dead-letter。底層改為 provider宣告 immutable `effect_kinds`，
claim transaction join EffectRequest後只鎖相符 family，worker對回傳 row再做 provider前
family fence；舊三參數 unfiltered RPC直接移除，無相容 escape hatch。PG17 clean／
idempotent migration與「email先入列、publisher後入列」交錯案例證明各 worker只拿自己
family；unit／PG17相鄰套件共 67 passed。Production migration
`20260724134742 operations_core_effect_family_routing`已套用，live catalog回讀
filtered signature、`volpred_ops_definer` owner、fixed search path、worker-only ACL、
filter definition與 index全對；當下 active claim=0，本次沒有 claim或 provider call。
此 cross-family routing根因為 `root_cause_fixed_and_verified`。Publisher durable
formal caller／HTTP adapters／owner cutover已由後續publisher checkpoint處理；
program commit 34仍缺跨兩台實體Mac的partition演練，umbrella維持`contained`。
同日再以 payload-store blocking injection 驗證 generic worker 的 provider boundary：
既有第三次 keepalive 回讀發生在 durable payload read 之前，reader 若在回傳 bytes
前讓 host demote，舊 worker仍會呼叫 provider。現在 payload SHA-256 通過後會立即
重驗同一 lease identity；RED case轉 GREEN，provider／settlement皆為 0，email、
publisher與PostgreSQL相鄰套件共 68 passed。這個 provider-boundary race為
`root_cause_fixed_and_verified`；沒有 live effect或 owner mutation，program commit 34
umbrella仍因其餘 family cutover與跨兩台實體Mac的partition演練未完成而保持
`contained`。

這是 umbrella program，不另建 ops 進度帳；下方
`docs/refactor_plan_ops_master_2026_07.md` 在交易式 operations core 接管完成前，仍是
Phase 1 現行修復的 canonical implementation ledger。原版、v3 與全部既有 skills 在
各自 gate 與 owner 獨立核可前不得刪除。

## 2026-07-20 Ops Master Consolidation（active — 最高優先）

Owner 指令「重構所有運營程式碼：底層邏輯/流程/架構三層徹底改、去重複、滿足 PDCA/loop
engineering、含 email/Telegram 互動與派工邏輯」。五路平行稽核（控制面/scripts/enforcement/
發佈管線/事故根因）後產出**收編型 master plan** = `docs/refactor_plan_ops_master_2026_07.md`
（§7 狀態表為 canonical，吸收既有 11 份 refactor plan 全部殘留項，此後 ops 重構單一入口）。
當日 Phase 0 完成：truncate-before-serialize corruption 路徑修復（continue_task_dispatch）、
cleanup claimed_at 盲點修復 + 5 筆殭屍任務自然回收（task_pool_claim）、cron_dispatch plan
標 SUPERSEDED、12 筆 Phase 1 任務入池（refactor-master 系列，P1/P2）。

## 2026-07-14 Token/Ops 浪費重構（active）

Owner 指示對「浪費且無意義的流程」全面盤點後的結構性優化。計畫 + 三層診斷 + 執行狀態
= `docs/refactor_plan_token_ops_waste.md`（§4 狀態表為 canonical，本檔不重複）。
當日完成：定位儀器 ops_snapshot、queue tombstone 壓縮（-64%）、retention as flow
（回收 ~6.3GB）、報告面降頻（老闆信 ~14→~5-6 封/天）、CLAUDE.md 396→333、blocked
triage 46→29、circular import / FRED guard 空轉 / spec drift 根治。剩餘 WS（pregate
attribution、error_log 壓縮、治理疊層收斂、K1709 合併）已進 next_tasks P2 由排程消化。

## 2026-05-04 系統性 audit + 4-phase 優化計劃

## 2026-05-04 系統性 audit + 4-phase 優化計劃

### 觸發背景

用戶 2026-05-04 觀察「slot 池無工作但 backlog 有 37 個 pending」→ 質問為何沒 auto-fill → 主線程深度 audit 揭露**完整 dispatch 機制存在但 0 次落地執行**。

### Audit 範圍

兩階段並行：
- **Schedule 7-layer 盤點**（主線程）：launchd / crontab / runtime_schedules.json / session_crons / event_jobs / Anthropic CronCreate / piggy-back
- **Codebase 深度審視**（Explore subagent）：storage source-of-truth / publisher / paper workflow / frontend / test coverage / skills / error_log

### Findings — 18 個系統性問題

#### CRITICAL（Mission impact，立即修）

1. **`session_crons` 9 spec / 0 實際 fire** — piggy-back 累積 1313 條 missed (continue_task=219, daily_planning=161, …)，**replayed_count=null × 8**。`session_startup.md §2.0` SOP 從未真實執行。
2. **`continue_task` dispatch 邏輯缺工具** — 只有 `stub.py` 設旗標，**無腳本判 slot < 4 + 派下個 task**。已修：`scripts/continue_task_dispatch.py` 補上（dry-run 列出 4 個 agentable candidates）。
3. **`.claude/skills/admin-ops/SKILL.md` + 11 skills 引用不存在的 `references/*.md`** — Agent dispatch 時 skill 加載不全 → context 壞 → 影響 admin-ops / autonomous-research / feed-publisher / paper-review-cycle。
4. **`scripts/supabase_sync.py:74-82` `_MARKET_DAILY_COLUMNS` 白名單未 upstream enforce** — 各 caller 仍可發送未列欄位 → PostgREST 400 silent fail（2026-04-17 incident pattern）。
5. **`scheduler_state.json` vs `cron_last_run.json` 雙寫 race** — `control-plane.md` 規則文字說「不雙寫」但 code 路徑兩個都寫，無 atomic merge / lock。
6. **`continue_task_dispatch.py` 已寫但無 cron 排程** — 只在當前 session in-process CronCreate (id 3e643940 hourly :17) 補上；session 結束就死。需 host 層 install。
7. **`shared_scheduler_tick */10` spec 寫但 launchd / crontab 都沒掛** — log size=0 自 2026-04-19，已 14 天死亡。功能被 piggy-back 接管但 spec 沒同步刪。

#### HIGH（Debt accumulating）

8. **`publisher.py:629-650` 寫 feed.json 無 read-back 驗證** — write 失敗（disk full / permission）仍回 success（2026-04-30 K1021 incident pattern）。
9. **`content.py::release_pool_articles:318` `sync_article()` 回傳被忽略** — Supabase sync 失敗無人知道，不寫 alert / pending_syncs。
10. **`tests/` coverage 缺口**：`volpred.publisher.email_notifier` (518 行) **無任何 test**；`volpred.ops.alerts` / `volpred.ops.event_jobs` test 不足。
11. **`storage/.release_settings.json` 與 Supabase out-of-sync 風險** — 2026-04-20 PATCH 400 incident 起點，無定期 audit。
12. **`frontend-v2-fix/scripts/deploy-zeabur-safe.sh` hardcode env** — 改 `config/project_targets.json` 不會 reflect 到 deploy。
13. **`next_tasks.json` 完成的 task 沒同步 status** — K1125 已 FAIL 2026-04-13 仍 pending（會被 dispatch 誤再派）。
14. **`event_jobs` 4 個過期未 GC**（FOMC 4-29 / NFP 5-1 已過 deadline）— ledger 累積。

#### MEDIUM（Cleanup nice-to-have）

15. **8 個 error_log entries 同 pattern「sync 失敗被吞」** — 缺架構性 retry + read-back + alert 三層防護。
16. **缺 skill audit script** — 2026-04-27 `member-questions/SKILL.md` 遺失 incident 顯示需 weekly audit。
17. **`control_plane.lock` 不統一** — multi writer 寫 shared state 沒共用 lock 機制。
18. **piggy-back timing drift assertion 缺** — 2026-04-19 1.5s drift 致 3h 週期 regression incident，未加 defensive assertion。

### 4-Phase 優化計劃

對應 Mission 5 條目標 priority：(1)文章 + (4)網頁 ← sync robustness；(2)實驗 ← skill references；(3)論文 ← paper workflow 整潔；(5)流量 ← 由 1+4 derived。

#### Phase 1（commit-safe，已完成）

- [x] B1.1: `scripts/continue_task_dispatch.py` slot-aware report + candidate list — commit `00bbce4e`
- [x] B1.2: `scripts/cron_continue_task_stub.sh` 補 call dispatch.py — commit `00bbce4e`
- [x] B1.3: in-process CronCreate replace stale `/loop` heartbeat（id 3e643940 hourly :17）— session-only
- [x] B1.4: `docs/error_log.md` 「2026-05-04 工作池 auto-fill 全鏈路斷裂」entry — commit `00bbce4e`
- [x] B1.5: commit Phase 1 — `00bbce4e`

#### Phase 2（中度修整，commit batch）

- [x] B2.1: `scripts/sync_next_tasks_status.py` — 從 experiments/<id>/README.md 反查，把 next_tasks 已完成 K 標 succeeded（解 #13）— commit `51c8f4a2`，K1125 已標 succeeded_null_result
- [x] B2.2: `scripts/check_skills_complete.sh` — audit skill SKILL.md + reference paths（解 #16）— commit `9f6e5045`，4 dead refs 修（paper-review-cycle .agents→.claude × 3, external-data-sources 移除 missing taiwan-macro-data 提及）
- [x] B2.3: `publisher.py::_append_to_feed` 加 post-write read-back（解 #8）— commit `bb0e3705`
- [x] B2.4: `content.py::release_pool_articles` sync_article 失敗寫 `.failed_supabase_syncs.json` 觸 alert（解 #9）— commit `bb0e3705`
- [x] B2.5: `gc_event_ledger` verified no-op — 機制 work，gc_after=deadline+7d 是設計（4 個 expired event_jobs 5-7/5-9 才該清，今 5-4 不該動，is finding #14 over-warning）
- [x] B2.6: `tests/test_email_notifier.py` 7 cases + `tests/test_event_jobs.py` 擴 3 cases（gc preserve unexpired / past_deadline skip / payload_patch overlay）（解 #10）

#### Phase 3（架構級，需 review，分批 commit）

- [x] B3.1: 已於 B2.2 commit 修完所有可解 ref；2026-05-04 重跑 `check_skills_complete.sh` 報 `all references/*.md mentions in SKILL.md exist`；原 audit「11 個」是 over-counting includes legacy `.agents/` paths and same-skill self-refs（解 #3）
- [x] B3.2: 確認 `scheduler_state.json` vs `cron_last_run.json` 為不同 domain（K cluster 訓練 state vs piggy-back run state），#5 為 audit over-warning，無需拆
- [x] B3.3: `supabase_sync.py::sync_market_daily` 加 stripped-keys warning（解 #4）— commit `9f6e5045`
- [x] B3.4: `content.py` L362+L693 兩個 unlocked feed.json write 統一加 `shared_state_lock("publisher_feed")`（解 #17）— commit `450d26a7`
- [x] B3.5: `scripts/audit_release_settings.py` + 6h piggy-back schedule + `auto`→`scheduled` 線上 mapping 修 silent PATCH 400 history（解 #11）— commit `db2f6ece`
- [x] B3.6: `frontend-v2-fix/scripts/deploy-zeabur-safe.sh` 從 `config/project_targets.json` 讀 PROJECT_ID/SERVICE_ID（解 #12）— frontend-v2-fix commit `4740e34`
- [x] B3.7: piggy-back drift assertion 加進 `check_alerts.py`（解 #18）—
  原 assertion 已由 `2e42993ed` 落地；2026-07-24 收尾修正兩個 live false-positive：
  `gmail_poll`／`handoff_regen` 改讀 wrapper execution receipt，並讓 canonical
  liveness parser 正確解析既有 host-local CST timestamp。48 個相鄰測試通過，
  live drift read-back=`0`。
- [x] B3.8: CLAUDE.md L107 + control-plane.md 統一 task source-of-truth（已於 B2 commit 寫入；session_startup.md 已是 read-only doc，無需動）

#### Phase 4（host install，需用戶授權）

- [ ] B4.1: 寫 launchd plist `~/Library/LaunchAgents/com.volpred.continue-task.plist` cron `*/30 * * * *`
- [ ] B4.2: 跑 `bash scripts/install_host_crontab.sh` rebuild canonical crontab + 補 continue_task entry（解 #1, #6）
- [x] B4.3: 移除 `runtime_schedules.json system_crontab.shared_scheduler_tick`（已死，piggy-back 接管）（解 #7）— 2026-07-20 ops-master D2 完成：整條 advisory scheduler lane（scheduler.py / scheduler-tick·preview·smoke CLI / run_scheduler_tick.sh / schedule spec / writer-ownership entry）退役，readers（summaries/health/alerts/control-plane snapshot/docs）同 commit 拔除
- [ ] B4.4: `session_startup.md §2.0` replay 改為 enforced script `scripts/replay_pending_sessions.py`（解 #1, #2）

### Effort × Risk × Mission Impact

| Phase | Effort | Risk | Mission Impact |
|---|---|---|---|
| 1 | 0.5 day | Low | 立即恢復 dispatch + 留 audit trail |
| 2 | 1-2 days | Low-Med | 修 8 個 sync 漏洞、補 status sync、補 test |
| 3 | 3-5 days | Med | 解所有 architectural debt（skills + control plane） |
| 4 | 0.5 day + user auth | Med-High | host 級 install — 需用戶 review crontab/launchd diff |

### 執行原則

- 不誤殺 active agent / 不 break feed
- 每個 commit 標明對應 finding 編號
- Phase 3 之前先確認 Phase 1+2 commit 通過 + tests pass
- Phase 4 之前產出 diff preview 給用戶 review

---

## 2026-04-23 Token Optimization Planning

- ✅ 重寫 [Token 優化計劃（2026-04-23 修正版）](/Users/yhlai0911/volpred-research/docs/token_optimization_plan_2026-04-23.md)：依 Claude Code 官方語義重新區分 `subagent` 與 `agent team`，補上 `skills/model/effort/context: fork` 的可用能力與限制。
- ✅ 補上既有 skills 配置矩陣：`admin-ops`、`autonomous-research`、`feed-publisher`、`paper-*`、`memory-health` 等已在計劃中對應預設 `model / effort / context: fork`，可作為下一輪實作 frontmatter 的直接依據。
- ✅ 確認現況：全域 [~/.claude/settings.json](</Users/yhlai0911/.claude/settings.json:94>) 已有 `statusLine`，且 [~/.claude/statusline-command.sh](</Users/yhlai0911/.claude/statusline-command.sh:1>) 已顯示 `context_window.used_percentage`；缺的不是顯示，而是明確行為規則。
- ✅ 專案層 `.claude/settings.json` / `.claude/settings.local.json` 已改為 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=62`，並移除預設開啟 `agent team` 的 env。
- ✅ chatty hooks 已瘦身：保留 `Stop` / `PreCompact` state save 與針對實驗 Bash 的 `PreToolUse` guard，移除會反覆把 meta 指令塞回 context 的 `SessionStart`、`SubagentStop`、`TaskCompleted`、`Notification`、`PostCompact` hooks。
- ✅ 依官方 hooks lifecycle/cost 文檔補上 `PreToolUse` Bash optimizer：對 `pytest` / `npm test` / `go test` 等高噪音測試命令改走 compact wrapper，完整輸出寫到 `storage/logs/hooks/`，Claude 只看通過摘要或失敗片段；這是目前唯一直接作用在 agentic loop、能穩定減少 token 的 hook 週期。
- ✅ 再把 `PreToolUse` Bash optimizer 擴到高頻人工巡檢輸出：`git status`（保留 `--porcelain` / `-z` 這類機器可讀模式）與大型 log `tail` 現在也會改走 compact wrapper，完整輸出仍落到 `storage/logs/hooks/`，Claude 只看 branch / dirty counts / path preview 或最後 40 行摘要，進一步降低 dirty worktree 與 log 巡檢的固定 context 稅。
- ✅ 新增 [docs/workflow-index.md](/Users/yhlai0911/volpred-research/docs/workflow-index.md)：把 workflow、執行模式、預設 `model / effort`、compact 邊界與 detail path 集中成輕量索引。
- ✅ `CLAUDE.md`、`docs/hardware.md`、`.claude/rules/agent-delegation.md`、`autonomous-research` delegation playbook 已同步改成「單一主 session / forked subagent 為預設，agent team 為特例」。
- ✅ 高頻 top-level skills 已補上 `model / effort`，並對 `citation-verifier`、`member-questions`、`memory-health`、`publication-candidates`、`latex-academic-reviewer` 補進 `context: fork` 路由。
- ✅ 將完成任務後的 `bash say ...` 從 `AGENTS.md` / `CLAUDE.md` 這類 always-loaded guide 移出，改成 on-demand 的 [`.claude/commands/task-done.md`](/Users/yhlai0911/volpred-research/.claude/commands/task-done.md)：收尾時才做摘要、讀 status line context %、給 `/compact` / `/clear` 建議，最後才播報，避免每個 session 都為這條規則付固定 token 稅。
- ✅ 2026-07-16 依使用者新選擇恢復 user-level「每次完成自動語音」：`~/.claude/CLAUDE.md` 只負責在真正完成時產一個 hidden `task-done` receipt；global Stop hook 以 `enforce_final_text.py --speech-only` 驗 receipt、Desktop/VSCode entrypoint 與 assistant UUID，再 detached argv 直呼 `/usr/bin/say`。SDK/headless/API error/無 receipt 回覆靜音；`/task-done` 移除手動 `say` 避免雙播。user settings/CLAUDE 已同步 `ops/claude_user_backup/`。
- ✅ 補上 Phase 4.1 的固定低噪音 summary CLI：`uv run volpred ops queue-summary`、`scheduler-summary`、`token-summary`、`log-summary`。它們都用現有 control-plane / schedule / token report / logs 做 compact readout，取代日常巡檢時手動拼多個較吵命令，降低 context 汙染。
- ✅ 補上 Phase 4.2 的 ID-based execution prompt：`execution_brief` 現在會帶 `workflow_id`，並把 executor / coordinator prompt 從整包 `TASK_JSON + BRIEF_JSON` 收斂成 compact task envelope / execution packet，只保留 `workflow_id`、`required_files`、`success_criteria` 等最小必要欄位，避免把 `updated_at`、`template_hash`、`source_type` 之類 metadata 一起塞進模型。
- ✅ 補上 Phase 4.3 的開工前 boundary gate：新增 [`.claude/commands/task-start.md`](/Users/yhlai0911/volpred-research/.claude/commands/task-start.md)，讓跨 workflow 或高成本任務在載入長 skill 前先看 status line context %、決定 `直接開始 / 先 compact / 先 clear`；`/research`、`/publish`、`/deploy` 也同步加上這層 gate，避免在高 context session 直接把長 SOP 再塞進主線。
- ✅ 進一步瘦身 recurring prompt 範例：把 `autonomous-research`、`admin-ops` scheduling 參考與 `scripts/session_startup.md` 內的長 `CronCreate(prompt=\"...\")` 改成短 prompt，改用 `queue-summary`、`scheduler-summary`、`log-summary`、`token-summary` 等固定 CLI 當入口，保留行為意圖但移除冗長步驟描述，降低 session cron / skill 載入時的固定 token 稅。
- ✅ 將 publication topic selection 也收斂到固定低噪音入口：新增 `uv run volpred ops publication-candidates-summary`，把 `publication-candidates`、`feed-publisher` 與 publishing rule 從 `cat/jq storage/publication_candidates.json` 改成 compact snapshot；每週 publication 巡檢 cron 也同步改成短 prompt，降低寫作前 workflow 的固定 token 與 shell glue 噪音。
- ✅ 將平台巡檢也收斂到固定低噪音入口：新增 `uv run volpred ops platform-patrol-summary`，把原本常要交錯讀的 `platform-cycle-summary`、alert 條件、scheduler / health 關鍵欄位壓成單一 compact snapshot；session cron / admin-ops 參考改成先看 patrol summary，只有 breach / release_due / pending_questions 時才下鑽 detail CLI，確保巡檢效果不減損但日常 context 更乾淨。
- ✅ 將會員問題重排入口也改成兩層式：新增 `uv run volpred ops question-ops-summary`，先只看 pending / ranked / candidate pool / top previews；只有 `pending_questions > 0` 時才打開完整 `question-ranking-workflow` 讀 `evaluation_template`。stable insertion rerank、atomic claim 與後續研究/發文流程都不變，但 6 小時巡檢不再每次都把完整 workflow 包塞進 context。
- ✅ 將 `memory-health` 也補成 summary-first workflow：新增 `uv run volpred ops memory-health-summary`，先回報記憶檔大小 / JSON 可讀性 / knowledge duplicates / orphan worktrees；只有 `warn / danger / duplicates / orphan_count > 0` 時才展開完整維護步驟。這樣每週記憶健檢不必每次都執行長 shell/python 區塊，且原本檢查項目沒有減少。
- ✅ 將知識索引檢查也收斂成 summary-first：新增 `uv run volpred ops knowledge-index-summary`，直接回報 `fresh / stale / missing / broken`、state drift、tracked files、index entries、`recommended_action` / `recommended_command` 與 top sources；`knowledge_index_check` 的 canonical prompt、`session_startup` 與 active skills 現在都先看這個 compact gate，依建議決定 `skip / auto / build`，不再把判斷邏輯散落在文件裡。
- ✅ 再把知識索引維護下沉成單一 wrapper CLI：新增 `uv run volpred ops knowledge-index-maintain --stub-if-no-work`，由程式先看 before summary、再自動執行 `skip / auto / build`、最後做 after-check 與 state sync；session cron / active skills 不再需要在 prompt 裡描述 decision tree，no-work 路徑也能只吐極小 stub。
- ✅ 將 `platform_patrol` / `question_research` 也下沉成 wrapper gate：新增 `uv run volpred ops platform-patrol-maintain --stub-if-no-work`、`uv run volpred ops question-ops-maintain --stub-if-no-work`；當沒有 `breach / release_due / pending_questions` 或沒有待評分題目時，cron 可以直接吐 tiny stub，不必每次都把 summary 與 decision 規則載進模型。
- ✅ 將 `continue_task` 也下沉成 slot-aware wrapper gate：新增 `uv run volpred ops continue-task-maintain --stub-if-no-work`，直接根據 `scheduler_preview`、queue snapshot、busy agent count 與 `idle_policy.max_concurrent_agents` 判斷 `no_work / slot_full / blocked_queue / dispatch_candidate`；沒有 runnable work 時 cron 可直接 tiny stub，不再每次都把 queue 規則與 slot-aware 判讀寫在 prompt 裡。
- ✅ 將 `daily_planning` 也下沉成固定 planning gate：新增 `uv run volpred ops daily-planning-maintain --stub-if-no-work`，先把 queue、scheduler 與 platform gate 壓成單一 compact packet；若沒有 `queued_tasks / pending_user_tasks / scheduler_gap / platform_signal` 就直接 tiny stub，避免每日規劃 prompt 每次都重述 queue/scheduler/草稿池檢查規則。
- ✅ 收掉剩餘兩條 recurring prompt 的 decision tax：新增 `uv run volpred ops token-usage-maintain --stub-if-no-work` 與 `uv run volpred ops git-sync-maintain --stub-if-no-work`。前者會自動判斷今日日報與週五週報是否缺失，必要時直接生成後再回報 after summary；後者則把 `git status/branch ahead-behind/dirty tree` 先壓成 compact preflight，只有真的有變更或同步需求時才展開 commit/pull/push。這樣 `token_usage_daily` / `git_sync` 也和其他 recurring workflows 一樣走 wrapper-first，不再靠 prompt 內自然語言 decision tree。
- ✅ 對齊 `release_pool` fallback 的觀測面：`check_alerts.py` 內的 hourly piggy-back release 若成功，現在會同步補寫 `storage/logs/cron/release_pool.log` 與 `storage/ops/cron_last_run.json["release_pool"]`。這不改釋出邏輯，只修正「文章有發出去，但 cron/log/health 看起來像沒跑」的 observability 分叉，避免之後誤判 host cron 是否失效。
- ✅ 將 `ndc_indicator_refresh` 也改成 wrapper-first：新增 `uv run volpred ops ndc-indicator-maintain --stub-if-no-work`，先檢查 `storage/macro/tw_dgbas_bci_m.csv` 是否已達 NDC 2 個月 lag 的預期月份；平常沒缺口時直接 tiny stub，只有 canonical CSV 落後或缺檔時，才展開 `collect_ndc_bci.py` 的人工更新流程。這樣月度台灣景氣指標維護不再每次都把整段更新 SOP 載入主線。
- ✅ 收掉 token 優化計劃剩餘兩個治理尾巴：將 `.claude/skills/member-questions/SKILL.md`、`.claude/skills/taiwan-macro-data/SKILL.md` 正式標準化，並同步更新 workflow index / error log / token plan 引用；避免 provider-visible skill 命名不一致，讓後續 agent-spec render / drift 檢查與自動化治理更單純。
- ✅ 將 `config/runtime_schedules.json` 的 canonical recurring prompts 收斂到 summary-first 短版：`daily_planning`、`continue_task`、`question_research`、`platform_patrol`、`token_usage_daily`、`ndc_indicator_refresh`、`git_sync` 等現在都和 `scripts/session_startup.md` / admin-ops 參考一致，直接指向 `queue-summary`、`question-ops-summary`、`platform-patrol-summary`、`token-summary` 等 compact 入口；效果不變，但日常 recurring prompt 載荷明顯下降。
- ✅ 新增 `config/token_policy.json` 作為 token / context 邊界的 canonical source，集中管理 `auto_compact=62`、`normal/compact/clear` 邊界與 status line 顏色門檻；`task-start`、`task-done`、`research`、`publish`、`deploy`、`workflow-index`、`hardware` 改成引用這份 config，而不再各自 hardcode 一套數字。
- ✅ `scripts/check_session_health.py` 的 `cost / lifetime / cache / messages / active window` threshold 也改成讀 `config/token_policy.json > session_health`，讓 token/context 相關巡檢門檻不再散落在 repo 內腳本。
- ✅ 全域 `~/.claude/statusline-command.sh` 也改成在 repo 內優先讀 `config/token_policy.json > statusline_colors`；畫面上的 context bar 顏色門檻現在和 repo 內 workflow/commands 使用的是同一套 canonical policy。
- 🎯 修正版優先序已調整為：`先把 agent team 從預設降為特例` → `設定 auto-compact 62%` → `建立 workflow index + skills routing` → `用 skill/subagent frontmatter 正式管理 model/effort`。
- 📌 新結論：本專案最該優化的是 **workflow routing 與 context boundary**，不是單純「少用 agent」。`subagent` 應保留並精準使用；`agent team` 只留給真正需要多 session 協作的任務。

## 2026-04-20 v12 continuation session outcomes（16 commits）

### Research
- ✅ **K1259 MCS/SPA meta-analysis 3-phase 完整落地**：Phase 1 ledger 2741 DM rows/236 K/16 assets (commit def4695b) → Phase 1.5 main-thread asset backfill 38%→78% (efd370f4) → Phase 2 HLN-2011 Variant A 18/20 per-asset MCS runs (5314dbd3) + CF-Rolling absence 分析 appendix (5bbeb48e)。**Key finding**: SPY QLIKE α=0.10 88/100 survive, A4f family dominant; GLD MSE 窄 set; α=0.10=0.20 identical; CF-Rolling 真正 absent（Trinity-only evaluation，never DM-compared pairwise）。
- ✅ **K1258 forgetting-factor BMA completed** (commit b6c6225f, agent a09ba983 5.83 min)：H1 FAIL (no Harvey pass), H2 PASS (regime switching restored 10-80x), H3 PASS (optimal λ asset-specific), H4 λ=1.0 default。Structural insight: forgetting 修好 K1257 H3 concentration 但 switching 不 translate 為 predictive gain → BMA family 對 vol forecasting 結構性不足，regime gains 需 switching-model / mixture-of-experts。
- ✅ **K1258 knowledge.json done** (entry 727e23ee, 2026-04-24 main-thread fallback `codex_review.md` PASS-with-caveats)。
- ✅ **K1259 knowledge.json done** (entry c4db347a, 2026-04-28 subagent fallback `codex_review.md` PASS-with-caveats; agent a9496102fadd8a804, commit 7c0013b6)。
- ✅ **K1259 review-cycle TRULY closed 2026-04-29**（Codex primary-path 二次驗證後）：(1) `d4c2faf1` MAJOR-3 docstring；(2) `53c1d559` MAJOR-1 v1 Phase 1.5 backfill scripted；(3) `aff7b4a5` MAJOR-2 v1 NON_DM_PATH_TOKENS 5 tokens；(4) `b1f85845` knowledge entry refresh；(5) `9b9951fd` research_program；(6) `90b650e7` project_improvement_status；(7) `218f350c` retraction of premature closure after Codex v2 FAIL；(8) **此 commit** v2 fix — extended NON_DM_PATH_TOKENS 至 9 tokens (加 `welch`/`stat_test`/`statistical_test`/`vs_zero`)，ledger 2730 → 2718 (12 false-positives 移除)；MCS 18/20 cells superior_sets 100% identical pre-v2 vs post-v2 (n_pairs=418 不變；12 removed rows 因 MIN_PAIRS_PER_MODEL=2 filter 早就 0 MCS signal)。**Codex review v2 doc**：`experiments/k1259/codex_review_v2.md`（FAIL → fix → close 完整 trail）。Option B (positive DM gate `dm`/`harvey`/`hln`) 拒絕 — 會誤刪 K1085/K1088 等 191 legit DM rows。Knowledge `c4db347a` confidence 0.88→0.75 retracted→0.90 (true closure)。**MED finding** (phase15_asset_map K1128/K1130/K1131 TAIFEX target-asset semantic) 留 separate slot — orthogonal to extraction correctness。**Lesson 系統化**: subagent fallback ≠ primary-path Codex；Codex 可用時應 primary，subagent 是 secondary opinion。
- ⏸️ **K1258/K1259 feed publication** 推延至 Phase 3 article 階段（meta-analysis 完整 narrative 需 Phase 1+2 結果整合，非單獨 K-finding 文章）。Phase 3 K1259 article 已 dedup-clean (3-layer 2026-04-28T19:40 CST)，可隨時排入後續 slot。

### Platform / Infrastructure
- ✅ **event_jobs full pipeline wired**（round 6 發現 empty → round 13 populate FOMC T-2/T+0 commit aebaeab4 → round 14 root-fix run_due_jobs piggy-back expand_due_event_jobs commit cac18c1a → round 15 standard pattern doc commit 4d7d787c）。完整鏈：host cron `0 * * * *` → check_alerts → run_due_jobs → expand_due_event_jobs → materialize task → 下輪 claim-next。scheduler_tick.log 自 2026-04-19 size=0 的 dead scheduler 被 piggy-back 接管。
- ✅ **Supabase `content_release_settings` PATCH 400 root fix** (commit 8ef0d67b)：`_update_content_release_settings` 拆 local_payload (8 fields 保 shape) vs remote_payload (delta fields only)；schema-mismatch 面積 8→2 fields。3/3 test_content_release_pool PASS。
- ✅ **P8 volatility-absorption reproduce re-verified** (commit 82f9c449)：46 MATCH / 12 MISMATCH / 17 UNTRACE / 75 total = 61.3% consistent since 2026-04-19 errata；no drift。Still awaiting user Path A/B/C decision.
- ✅ **活文件更新**: `.claude/rules/control-plane.md` universal piggy-back §step 6 + event_jobs populate 規範 + standard event pattern (CPI/NFP/FOMC/Earnings T-series); `docs/error_log.md` scheduler_tick dead incident + Supabase PATCH delta-payload root-fix entries。
- ✅ **`storage/next_tasks.json` legacy list GC** (commit e3732d3e)：106→82 entries, -298 行，24 completed/done 清除，canonical queue 不動。
- ✅ **feed INDEX refresh** (commit ce9a6a78)：944→949 articles, draft 5→8。

### Content
- ✅ **K1257 BMA draft mile_5173955c queued** (audience=research, 11415 chars, 2107 CJK)。
- ✅ **FOMC T-2 dispatch memo** (commit 15b6c27c)：`storage/next_draft_candidate_fomc_t2.md` 含 scenario-conditional number grid 主題軸 + 3-layer dedup checklist；wired to event_jobs entry fomc-2026-04-29-t2 (2026-04-26 00:00 CST not_before)。
- ✅ **FOMC T+0 event_job entry**（fomc-2026-04-29-t0, 2026-04-29 21:00 CST post-announce, requires_websearch）。

### Meta / Governance
- ✅ **Standard event pattern** 寫入 .claude/rules/control-plane.md — 6 種 event-type (FOMC/CPI/NFP/Earnings/央行/Geo) 檢查清單 + T-series slot 表 + 配額 cap + 6-step populate workflow + ROI 排序。未來任何新事件 populate 只查此段 + copy template。
- ✅ **Rule path-trigger timing principle** (pre-session commit a5573c81) — 寫規則時必檢查 paths 是否 cover planning/selection phase 而不只 execution。

---

## v12 Transition Status (2026-04-19 update)

> **v11 → v12**: 原 v11 3-terminal 架構（Claude supervisor + worker + Codex worker）已 retired (session cron decommissioned as execution clock)，**v12 模式**為 single main-thread Claude + ephemeral subagent dispatch（claude general-purpose / codex-rescue）。canonical source of truth = `storage/ops/` control plane + `config/runtime_schedules.json` + `event_jobs`。

### 2026-04-19 v12 session outcomes
- ✅ **5 Codex ops victories**（task_4e75 snapshot infra / task_fdf8 release-pool fix / task_361a P6 audit / task_9b07 session-bootstrap v11 cleanup / task_6e7c claim-next parent guard）
- ✅ **4 papers GREEN**（P4 vix-sufficiency 98% / P4ins vt-insurance-cost 100% / P5 vt-crowding-abm 100% / P6 prg-periodic-garch 100%）— 首次四篇 submission-ready
- ✅ **6 papers 0 MISMATCH**（+P1 / P2 / P3 cross-source NOTE reclass clean）
- ✅ **Host cron selectivity bug workaround**: `scripts/check_alerts.py` `_auto_trigger_release_pool_if_due()` piggy-back（解 `3 */2` cron silent skip issue）
- ✅ **Session cleanup**（0 stale claims / 0 orphan worktrees / 0 orphan worktree-* branches）
- ⏸️ **Codex quota 耗盡** until 2026-04-24 10:27 UTC；wake-up cron + canonical schedule entry 已建（one-shot durable）
- 📝 **3 reusable next-draft memos** (K957 / K1091 / K1092) for future pool-breach remediation
- 📝 **2 errata_pending.md** (P8 CRITICAL / P9 shelf-ready)
- 📝 **Release cadence** unified to 120 min interval + 2h cron

### 2026-04-19 18:00+ UTC post-compact saturation-round work (Codex-blocked observation mode)

- ✅ **K1174 memo written + DOWNGRADED**（score 10 但 `mile_45060685` 已以 footer 吸收 — pivot-angle 用）
- ✅ **publication_candidates.json rebuild** (stale 3h → fresh 18:35)；uncovered 225→215；真正 uncovered K1100-K1224 僅 K1106 + K1115（大部分已被 content/title-matching 覆蓋）
- ✅ **alerts.py `release_pool_gap` false-positive fix**：`_parse_release_pool_state` 補 `.release_settings.json.last_released_at` 作 alternative truth source — 前 24h dedup-壓著的每小時 false-positive 鏈結束（驗證 `check-alerts` → `breached=false gap=0.78h`）
- ✅ **experiments/INDEX.md rebuild**（5h30m stale → fresh；1011→1012 K，uncovered 736→735）
- ✅ **docs/strategy-registry.md drift fix**（header 14/10 active → 實 14/11 active，附 verified timestamp + code line ref）
- ✅ **Question archive**: 2026-03-20 keyboard-mash garbage question `54ba8732` (testtewtrwqetwqtewqtqwet) archived — 清 member_qa ranking 污染
- ✅ **K957 knowledge.json metadata fix**（title 37→40 Experiments / 第一句 4 缺 K→K555 唯一缺 / 研究效率觀察 37→40 + 5.4→5.0%）
- 📝 **error_log 3 新 section**: P1/P2/P3 reproduce_report stale / alerts piggy-back 失明 / K957 KB-article drift map
- 📝 **Piggy-back production-validated** (18:00 UTC 純自動 trigger mile_1beaaa3f released — 第一次 auto-release 不靠主線程 intervention)

### Historical v11 context 保留於下方（不刪除，作為 architecture evolution reference）

---

## VolPred 雙 Agent 最終優化方案 v11

### Summary

- 本方案只在**目前 `volpred-research` 專案基礎上增量調整**，不重做網站、不替換 `storage/` / `ops` / `frontend-v2-fix/` / Supabase / Mirror / Admin 主架構。
- 優先序正式鎖定為：**正確性 > 穩定性 > token 效率 > 吞吐量**。
- 運作模式鎖定為：**Claude Code = 協調者 / 規則主導者 / brief builder；Claude 與 Codex = 執行者；control plane = 唯一狀態來源。** repo 目前仍保留 `shared scheduler` 這條 `cron-driven` 過渡路徑，但校正後的目標 runtime 是 VS Code supervisor / worker sessions。
- `2026-04-18` 依 user story 校正後，**正式操作故事應是 VS Code 三終端機模式**：1 個 Claude supervisor 管理排程 / brief / 狀態，1 個 Claude worker + 1 個 Codex worker 在已登入 OAuth 的互動 session 內認領並完成任務。
- shared scheduler 跑在 **macOS `crontab`**；Claude 既有 session cron **退役為非執行時鐘**，只保留提醒與 monitor；`idle_policy` 僅作為 slot-aware continuation / selection policy，不是另一個主時鐘。
- shared scheduler 對 live manual agent session 採保守策略：若偵測到非 scheduler 擁有的 Claude/Codex session 仍在線，則不會搶同一個 agent。
- 目前 repo 仍殘留 `scheduler -> subprocess.run(["claude", "-p", ...]) / subprocess.run(["codex", "exec", ...])` 的 headless 路徑；這是**偏離 user story 的過渡期實作**，不應視為最終 runtime contract。
- Claude 與 Codex **都可以提出 cron / schedule 需求**，但只有 **Claude coordinator** 可以把需求落成正式 canonical schedule、調整排程策略、安裝或移除 cron。
- 每輪任務都必須符合 **codebase grounding contract**：在 repo root 啟動、先讀必要背景、用結構化 brief 控制上下文；拿不到足夠背景就 fail closed。
- 一次性任務與事件前後任務正式納入 canonical schedule，新增 `event_jobs`；不再只靠 prompt 或自由文字文件記憶。
- **Brief 生成策略固定為 `C`：模板優先，Claude 協調輪只處理例外。**
- brief 模板固定放在 **`config/brief_templates/<task_family>.yaml`**。
- Claude coordinator 的 JSON brief 固定採 **pydantic 驗證 + fenced JSON 抽取 + 最多 2 次重試**；第 3 次失敗即標記 `brief_status=needs_manual_review`。
- brief 過期規則固定為：**`task.updated_at > brief_payload.generated_at` 或 template hash 改變**。
- scheduler cron 安裝與移除腳本化處理：**`scripts/install_scheduler_cron.sh`**、**`scripts/uninstall_scheduler_cron.sh`**。
- v1 **不做 task dependency graph**；事件鏈先靠 `not_before/deadline` + preconditions + fail-closed preflight 控制。
- **存檔目標**鎖定為 `docs/project_improvement_status.md`；本檔即為最終規格版本。

### Implementation Status

- 已完成：
  - Phase 6 provider skills render 修正
  - Phase 3 最小 schema 擴充
  - Phase 1 session lifecycle wrappers
  - Phase 2 auto routing
  - Phase 4 `experiment_id` 並發防撞
  - Phase 5 `agent-spec sync` alias
  - Phase 5b `event_jobs` / event ledger / preview / GC
  - Phase 7a shared scheduler tick、self-lock、scheduler state、cron wrapper scripts
  - Phase 7b execution brief、template-first policy、prior findings、fail-closed preflight
  - Phase 7c 基礎 observability：CLI、health snapshot、control-plane summary、admin ops/health 指標
  - scheduler 與 live manual Claude/Codex session 共存護欄：目標 agent 已被真人 session 佔用時，tick 會跳過並回報 `no_runnable_work`
  - `preconditions` 已落地為實際派工護欄：scheduler 會跳過未滿足前置條件的 task，executor preflight 也會把手動 claim 的 task 重新排回 queue
  - schedule governance contract 已落地：`payload.governance_area=schedule` / `payload.schedule_proposal` 會被系統辨識，並強制收斂到 Claude 作為治理 owner
  - schedule proposal 任務已有專用 brief template，`/admin/ops` 也能直接看到 `governance schedule` badge
  - `uv run volpred ops propose-schedule ...` 已提供正式 CLI 提案入口，Claude/Codex 都可用同一個 contract 建立 schedule proposal task
  - `/admin/ops` 建立本機 task 表單已補齊 `member` / `strategy` family、`public_effect` 欄位與「Schedule Proposal 範本」快捷按鈕
  - `storage/next_tasks.json` 的定位已正式收斂為 **legacy planning / working list**；canonical orchestration 仍以 `storage/ops/` control plane、`config/runtime_schedules.json`、`event_jobs` / `event_ledger` 為準
  - session worker flow 已補強：`next-task --emit-brief` 現在只會返回可執行 task，會跳過尚未被 supervisor brief 化或 preconditions 未滿足的 queued task
  - supervisor 已可用 `uv run volpred ops brief-show` / `brief-set` 正式查看與寫入 manual brief，不必手改 `storage/ops/tasks/*.json`
  - canonical `system_crontab` spec 已補上 `shared_scheduler_tick`，並把既有 `market_calendar sync` 納回 canonical，避免 install script、live crontab 與 `/admin/schedules` 的 source of truth 分裂
  - shared scheduler 已實際安裝進本機 `crontab`，目前 canonical system tasks 與 live crontab 對齊（`schedule-report` = `6/6` matched）
  - `/admin/schedules` 的心智模型已更新：shared scheduler / system crontab 為正式時鐘，session cron 僅保留為 legacy session convenience
  - coordinator / executor subprocess 已補 timeout fail-closed 護欄，避免 `claude -p` / `codex exec` 卡住時長時間占住 scheduler self-lock
  - 已新增 `uv run volpred ops scheduler-smoke` 隔離 smoke helper：自備最小 prompt / brief template，mock 掉真實 `claude -p` / `codex exec`，可在不碰 live queue 的前提下驗證 coordinator 與 executor 鏈路
  - 已新增 `uv run volpred ops scheduler-live-smoke`：用隔離 storage 真正呼叫本機 Claude/Codex CLI 做最終 smoke；Claude 走 no-persistence + no-tools，Codex 走 read-only sandbox + ephemeral，避免碰 live queue 與 repo 內容
  - 已補 execution brief CLI 相容性修正：Claude `-p --output-format json` result envelope / 純文字錯誤可正確解包；Codex output schema 已符合新版 `additionalProperties=false` 與 full required set 規則
  - 已新增 agent CLI readiness snapshot：`scheduler-live-smoke` 會把 Claude/Codex live path 分類成 `ready / auth_required / free_text_response / schema_mismatch / timeout` 等狀態，寫入 `storage/ops/agent_cli_health.json`，`ops health` / `/admin/health` 可直接觀察
- 已驗證：
  - `uv run pytest tests/test_shared_lock.py tests/test_execution_brief.py tests/test_scheduler.py tests/test_agent_spec.py tests/test_local_control_plane.py tests/test_stale_reclaim.py tests/test_session_ops.py tests/test_event_jobs.py tests/test_runtime_schedules.py`
  - `uv run python -m volpred.cli ops scheduler-preview`
  - `uv run python -m volpred.cli ops event-preview`
  - `uv run python -m volpred.cli ops scheduler-tick`
  - `uv run python -m volpred.cli ops control-plane-summary`
  - `uv run python -m volpred.cli ops health`
  - `uv run python -m volpred.cli ops schedule-report`
  - `bash scripts/install_scheduler_cron.sh`
  - `bash scripts/run_scheduler_tick.sh`
  - `cd frontend-v2-fix && npm run typecheck`
  - `uv run pytest tests/test_execution_brief.py tests/test_scheduler.py`
  - `uv run python -m volpred.cli ops agent-spec check --target all`
  - `uv run python -m volpred.cli ops propose-schedule --title ... --description ... --proposal-json ... --storage-dir /tmp/...`
  - `uv run python -m volpred.cli ops task-show <task_id> --storage-dir /tmp/...`
  - `uv run python -m volpred.cli ops scheduler-smoke --mode both --cleanup`
  - `uv run python -m volpred.cli ops scheduler-live-smoke --mode all --cleanup`
  - `2026-04-18` live smoke 實測：Codex executor path 已通過（read-only sandbox、`files_touched=[]`）；Claude coordinator / executor 目前仍會輸出自由文字而非 schema-valid JSON，因此 helper 已能穩定暴露這個剩餘 gap
  - `cd frontend-v2-fix && npm run typecheck`
- 尚未執行：
  - 將正式執行路徑從 headless scheduler subprocess 收斂回 VS Code supervisor / worker session 模式，並退役或降級 `claude -p` / `codex exec` 直跑 task 的舊路徑
  - Claude live structured-output compatibility remediation（`scheduler-live-smoke` 已確認 gap，可作為後續修正入口）
  - 最終 commit / deploy

### User Stories

- 作為專案 owner，我希望打開 VS Code 後能建立 3 個終端機：1 個 Claude supervisor、1 個 Claude worker、1 個 Codex worker；全部都用 OAuth 訂閱登入的互動 session，而不是背景另外開 headless process。
- 作為專案 owner，我希望平台能在**不犧牲正確性與穩定性**的前提下持續推進任務，而不是為了並行而增加錯誤與重工。
- 作為專案 owner，我希望 **Claude 負責協調與規則判斷**，而 Claude 或 Codex 都可以根據任務類型成為執行者。
- 作為專案 owner，我希望每輪任務都能讀到**剛好夠用的 codebase 背景**，而不是每次都重掃整個 repo 浪費 token。
- 作為專案 owner，我希望 recurring 任務、一次性任務、事件前後任務都能由同一套 canonical schedule 管理，不再分散在 session cron、prompt 與活文件裡。
- 作為專案 owner，我希望 Codex 持續參與系統，但主要聚焦在 **code/review/ops/bug rescue**，而不是一開始就和 Claude 完全對等搶任務。
- 作為專案 owner，我希望所有 mutating 任務都能追溯到 session、rollback point、brief、execution receipt，失敗時可以完整恢復。
- 作為專案 owner，我希望導入新 orchestration 後，網站上的文章、策略績效、會員問答、工具頁仍照常運作。
- 作為專案 owner，我希望從 `/admin/ops`、`/admin/health`、CLI 看到 scheduler、event materialization、agent session、approval、rollback、brief 狀態的實際情況。
- 作為 Claude 協調者，我希望能用最少 token 先把任務變成低歧義、可執行、可驗證的 brief，再決定交給 Claude 或 Codex。
- 作為 Claude supervisor，我希望能在互動 session 中查看 task、補 manual brief、調整 queue，然後由 worker terminals 去 claim 與完成任務。
- 作為 Codex 執行者，我希望接到的是已經定義好目標、必讀檔案、成功標準、禁止整檔讀取清單的任務，而不是模糊探索題。
- 作為平台維運者，我希望 scheduler 空轉時幾乎不耗 token，只有真的有可做任務時才喚起 LLM。
- 作為事件任務管理者，我希望 CPI / NFP / FOMC / TSMC 財報前後任務能被正式展開、去重、觀測，而不是靠記憶與臨場判斷。

### Key Scenarios

#### 1. 每日自動運作

- `crontab` 定時執行 `scripts/run_scheduler_tick.sh`。
- wrapper 腳本負責切到 repo root、載入 `.env.local`、補 PATH、執行 `uv run volpred ops scheduler-tick`。
- `scheduler-tick` 一開始先取 **`shared_state_lock("scheduler_tick")` 非阻塞鎖**；拿不到就直接退出 0，代表上一輪還在跑。
- 若目標 agent 已被 live manual session 佔用，該輪視為 `no_runnable_work`，不強行覆蓋 agent session。
- 若 task 的 `preconditions` 尚未成立，該輪也視為不可執行，不會進入 coordinator/executor。
- scheduler 再做 queue、stale reclaim、event expander、approval backlog、slot 檢查。
- 沒有可做任務就直接退出；有任務才喚起 Claude 或 Codex。

#### 2. recurring 任務

- 例子：平台巡檢、會員問題、知識索引檢查、token 日報。
- scheduler 依 recurring 規則找到 task family，直接載入 `config/brief_templates/<task_family>.yaml`。
- 模板足夠時不跑 Claude 協調輪。
- 模板 preflight 不成立時直接 fail-closed，不用 LLM 補猜。

#### 3. 一次性任務

- `event_jobs.trigger_mode=one_shot` 定義只跑一次的任務。
- scheduler 到時間後 materialize 成正式 task。
- `dedupe_key` 保證同一任務只建立一次。
- materialize 同時寫入 event ledger，避免下一輪 tick 重建。

#### 4. 事件前後任務

- 例子：CPI / NFP / FOMC / TSMC 財報前後的資料抓取、分析、文章、會員問答。
- `event_jobs.trigger_mode=relative_to_event` 用 `not_before` / `deadline` 控制窗口。
- `event_key` 固定為 `{type}_{yyyymmdd}_{variant?}`。
- `dedupe_key` 固定為 `{event_key}:{task_family}`。
- v1 不做 `depends_on_task_ids`；改用時間窗錯開與 preconditions 檢查產物是否存在。

#### 5. 模糊或跨領域任務

- 模板不足、brief 缺失、brief 過期、事件複雜、跨模組、研究 discovery、高風險任務，先喚起 Claude 協調輪。
- 協調輪輸出 schema-valid JSON brief。
- 若重試 2 次仍不合法，task 轉 `brief_status=needs_manual_review` 與 `status=blocked`。

#### 6. Code Review / Bug Rescue

- 若任務明確屬於 code/review/ops，且 brief 已就緒，直接派給 Codex。
- 若背景不清楚、跨多模組、或 risk 高，先由 Claude 補 brief，再交 Codex。
- Codex 不需要重掃整個 repo，只讀 `required_files` 與少量 `recommended_files`。

#### 7. 任務中斷與恢復

- 某個 agent session 中斷或超過 stale threshold。
- 後續 tick 執行 stale reclaim，把 task 釋回 queue。
- scheduler 下一輪重新分派，不讓任務永久卡死。

#### 8. 高風險公開行為

- 正式發文、會員可見回答、策略 runtime 變更等高影響任務進入 approval gate。
- 先建立 rollback、生成 brief、跑 preflight、等 approval。
- 通過後才對外落地。

### Final Architecture

#### Scheduler

- 唯一 clock，透過 `crontab` 執行 `scripts/run_scheduler_tick.sh`。
- 僅負責機械節奏、event expander、cheap preflight、派工判斷。
- `scheduler-tick` 使用專用 self-lock，避免雙 tick 併發。
- scheduler 是 **中立執行層**，不是 Claude/Codex 任一方私有的時鐘；但排程治理權歸 Claude coordinator。

#### Coordinator

- 預設由 Claude fresh-context 執行。
- 僅在模板不足、brief 缺失/過期、事件複雜、任務模糊或高風險時啟動。
- 輸出必須是**可驗證的 JSON brief**。
- Claude 也是 **schedule governance owner**：
  - 接收 Claude/Codex 提出的 cron 需求
  - 決定是否納入 `config/runtime_schedules.json`
  - 決定 `event_jobs` / recurring 規則 / cadence 調整
  - 決定是否執行 `install_scheduler_cron.sh` / `uninstall_scheduler_cron.sh`

#### Executors

- Claude：研究、內容、會員、模糊或高判斷任務。
- Codex：code、review、ops、bug rescue、明確結構化任務。
- Codex 不做開放式 discovery，只接已 brief 化任務。
- 因此「排程由 Claude 治理」**不等於**「所有 cron-triggered 任務都只能由 Claude 實作」；若任務 brief 清楚，仍可由 Codex 作為 executor。

#### Control Plane

- 任務、session、approval、rollback、execution receipt 的唯一協調層。
- scheduler、Claude、Codex 都只能透過 ops layer 改共享狀態。

#### Grounding

- brief 是 worker 的正式執行入口。
- executor 必須先讀 `required_files`。
- `forbidden_large_files` 是 prompt 級禁止整檔讀取清單。
- 必要背景不足時不得硬做。

### Public Interfaces / Data Contracts

#### New CLI

- `uv run volpred ops session-bootstrap --agent claude|codex`
- `uv run volpred ops next-task --agent claude|codex [--emit-brief]`
- `uv run volpred ops finish-task --agent claude|codex --task-id ...`
- `uv run volpred ops session-shutdown --agent claude|codex`
- `uv run volpred ops brief-show <task_id>`
- `uv run volpred ops brief-set <task_id> --brief-json ... --actor ...`
- `uv run volpred ops requeue-task --task-id ... --actor ... --reason ...`
- `uv run volpred ops agent-spec sync --from claude|codex`
- `uv run volpred ops scheduler-tick`
- `uv run volpred ops scheduler-preview`
- `uv run volpred ops scheduler-smoke [--mode coordinator|executor|both] [--cleanup]`
- `uv run volpred ops scheduler-live-smoke [--mode coordinator|claude-executor|codex-executor|all] [--cleanup]`
- `uv run volpred ops event-preview`

#### New Scripts

- `scripts/run_scheduler_tick.sh`
- `scripts/install_scheduler_cron.sh`
- `scripts/uninstall_scheduler_cron.sh`

#### New Config / Template Paths

- `config/runtime_schedules.json`
  - 新增 optional section：`event_jobs`
- `config/brief_templates/<task_family>.yaml`
- `config/agent_prompts/claude_coordinator.txt`
- `config/agent_prompts/claude_executor.txt`
- `config/agent_prompts/codex_executor.txt`

#### TaskRecord 新欄位

- `session_id: Optional[str]`
- `rollback_point_id: Optional[str]`
- `public_effect: Optional[str]`
- `brief_status: Optional[str]`
- `brief_payload: Optional[dict]`

#### AgentSession 新欄位

- `session_rollback_point_id: Optional[str]`

#### ExecutionReceipt 新欄位

- `session_id: Optional[str]`
- `rollback_point_id: Optional[str]`

#### `brief_status` 列舉

- `pending`
- `ready`
- `stale`
- `needs_manual_review`

#### `brief_payload` 固定欄位

- `generated_at`
- `source_type`: `template | coordinator`
- `template_id`
- `template_hash`
- `coordinator_run_id`
- `task_summary`
- `goal`
- `success_criteria`
- `repo_root`
- `required_files`
- `recommended_files`
- `forbidden_large_files`
- `relevant_commands`
- `prior_findings`
- `rollback_point_id`
- `why_this_agent`

#### `event_jobs` 固定欄位

- `id`
- `event_key`
- `trigger_mode`: `one_shot | relative_to_event`
- `not_before`
- `deadline`
- `dedupe_key`
- `preferred_agent`
- `public_effect`
- `task_template`

#### `task_template` 固定欄位

- `title`
- `description`
- `task_family`
- `priority`
- `preferred_agent`
- `approval_mode`
- `risk_level`
- `payload_patch`
- `brief_template`
- `preconditions`

#### Event Ledger

- materialize 後必寫到 `storage/ops/event_ledger/`
- 為避免 path 字元問題，檔名用 `sha256(dedupe_key).json`
- ledger 內容至少包含：
  - `dedupe_key`
  - `event_key`
  - `task_family`
  - `task_id`
  - `materialized_at`
  - `deadline`
  - `gc_after`
- `gc_after` 固定為 `deadline + 7 days`
- expander 以 ledger 作為是否已 materialize 的唯一判斷來源
- scheduler 每次 tick 只做便宜 GC；刪除已過 `gc_after` 的 ledger

#### Compatibility Rules

- 所有新欄位都必須向後相容：`Optional[...] = None`
- 所有舊 JSON 讀取時一律 `.get(...)`
- 不做 migration
- `payload` 本 phase 只認 `payload["experiment_id"]` 單數字串

### Brief Generation Policy

- 策略固定為：**模板優先，Claude 協調輪只處理例外**
- recurring、明確、低歧義 task family：使用 `config/brief_templates/<task_family>.yaml`
- schedule governance 任務：優先使用 `config/brief_templates/schedule-governance.yaml`，且 scheduler 先走 Claude 協調輪
- 事件任務：先試事件模板；模板不足才跑 Claude 協調輪
- 研究 discovery、跨模組、模糊或高風險任務：跑 Claude 協調輪
- JSON 保證機制：
  - 抽取 fenced JSON 或第一個合法 JSON object
  - 用 pydantic schema 驗證
  - 最多重試 2 次
  - 第 3 次失敗：`brief_status=needs_manual_review`
- brief 過期規則：
  - `task.updated_at > brief_payload.generated_at`
  - 或 `brief_payload.template_hash != current_template_hash`
  - 任一成立即把 `brief_status` 轉為 `stale`
- `prior_findings` 自動填入規則：
  - `--emit-brief` 時自動讀取該 `task_id` 最近 3 筆 `ExecutionReceipt`
  - 收集非空 `summary` 與關鍵 `error`
  - 組成 `prior_findings` list
  - coordinator 如有更精確內容，可覆蓋或追加
- executor prompt 預設採**self-contained 模式**
  - 即使 `claude -p` 會載入 skills，也不把 auto-loaded skills 當正確性前提
  - Phase 0 會 smoke test `claude -p` 的 skills 可用性，但 Phase 7b 的執行面仍以 self-contained brief 為準
  - skill 名稱可作為提示，不作必要依賴

### Cron Governance Policy

- Claude 與 Codex 都可以提出：
  - 新 recurring 任務需求
  - 新 `event_jobs` 需求
  - cadence / interval 調整建議
  - 停用、延後、加嚴 preconditions 的建議
- 但正式落地只走 Claude coordinator：
  - 修改 `config/runtime_schedules.json`
  - 修改 `scripts/run_scheduler_tick.sh`
  - 執行 `scripts/install_scheduler_cron.sh`
  - 執行 `scripts/uninstall_scheduler_cron.sh`
  - 調整 shared scheduler 的 routing / policy
- Codex 不直接擁有 cron 安裝權，也不直接成為 canonical schedule 的最終作者。
- 若 Codex 發現需要排程變更，應產出：
  - task / brief / code review finding / schedule proposal
  - 再由 Claude coordinator 審核後納入 canonical
- schedule proposal 的 payload contract：
  - `governance_area: "schedule"`
  - `schedule_proposal: {...}`
- 一旦符合上述 contract，即使建立 task 的人是 Codex，control plane 也會把正式治理任務收斂到 Claude
- v1 的保守預設：
  - schedule discovery 可以來自兩邊
  - schedule governance 只由 Claude
  - schedule-triggered 任務若模板足夠，可直接派給 Codex executor
  - 但任何 schedule 規則變動仍需 Claude 寫回 canonical

### Fail-Closed Policy

#### Global Tick Failure

- `scheduler-tick` 在 claim 前若發現 repo root 錯誤、runtime config 無法讀取、scheduler self-lock 未取得：
  - 直接退出
  - 不變更任何 task 狀態
  - 寫 scheduler log

#### Task-Scoped Preflight Failure

- repo root mismatch / agent-spec drift / skills render 壞：
  - task 轉 `blocked`
  - `last_error` 記錄原因
  - 清掉 claim
  - 寫 execution receipt，`result_status=blocked_preflight`
- brief missing / stale：
  - `brief_status=stale`
  - 若 task 已被 claim，釋放 claim 並回 `queued`
  - 下輪 scheduler 重新生成 brief
- `required_files` 不存在：
  - task 轉 `failed`
  - `last_error` 記錄缺檔
  - 清掉 claim
- coordinator 3 次 retry 全失敗：
  - `brief_status=needs_manual_review`
  - task 轉 `blocked`
  - 清掉 claim
- `blocked` 不是 terminal，但 scheduler 不會自動重跑 blocked task
- blocked task 修復後，需透過 `ops requeue-task` 明確回到 `queued`

### Event Layer Policy

- `event_key` 固定格式：`{type}_{yyyymmdd}_{variant?}`
- `dedupe_key` 固定格式：`{event_key}:{task_family}`
- v1 不做 `depends_on_task_ids`
- 替代方案：
  - 事件任務用 `not_before/deadline` 錯開
  - `task_template.preconditions` 檢查必要檔案 / 產物 / 狀態
  - preconditions 不成立時不派工或 fail-closed
- 若未來實務上真的出現 race，再升級到 dependency graph

### Implementation Plan

#### Phase 0: Baseline 與回滾起點

- 建立 named rollback baseline
- 記錄：
  - `uv run volpred ops agent-spec check --target all`
  - `uv run volpred ops control-plane-summary`
  - `uv run volpred ops health`
  - Claude/Codex CLI skills warnings
  - `claude -p "list skills you have access to in this repo"` smoke 結果
- 每 phase 結束固定執行：
  - `pytest`
  - `uv run volpred ops agent-spec check --target all`
  - `uv run volpred ops health`
  - git commit

#### Phase 6: Provider Skills Render 修正

- 修 `src/volpred/ops/agent_spec.py` 的 header 注入點
- 所有 provider-rendered `SKILL.md` 第一行都必須是 `---`
- `.claude/skills/**` 與 `.agents/skills/**` 一起修
- provider-visible `skill.md` 一律 render 成 `SKILL.md`
- 驗證時本機同時檢查 `.claude/skills/**` 與 `.agents/skills/**` 第一行
- 注意 `.agents/skills/**` 為本機 render 產物，PR 主要只會看到 `.claude/` diff

#### Phase 3: 最小 Schema 擴充

- `TaskRecord` 增加 `session_id`, `rollback_point_id`, `public_effect`, `brief_status`, `brief_payload`
- `AgentSession` 增加 `session_rollback_point_id`
- `ExecutionReceipt` 增加 `session_id`, `rollback_point_id`
- `public_effect` 固定枚舉：
  - `none`
  - `draft_only`
  - `published`
  - `member_visible`
  - `prod_runtime`

#### Phase 1: Session Lifecycle Wrappers

- `session-bootstrap`
  - 驗證 `VOLPRED_ACTOR == args.agent`
  - 建立 session rollback point
  - 執行 `agent-spec check`
  - 寫入 heartbeat / session metadata
- `next-task`
  - heartbeat
  - claim-next
  - 繼承 `session_id` / `session_rollback_point_id`
  - 需要時輸出 execution brief
- `finish-task`
  - 成功與失敗都寫 execution receipt
- `session-shutdown`
  - 標 offline，必要時釋放 claim
- `requeue-task`
  - 僅允許 `blocked` task 回到 `queued`
  - 記錄 actor 與 reason

#### Phase 2: Auto Routing

- 保留現有 `task_family`
- `preferred_agent=auto` 時映射：
  - `research/content/member -> claude`
  - `code/review/ops/strategy -> codex`
- scheduler 先看 `brief_status`
  - 未 brief / stale / 模糊 / 事件任務：先交 Claude 協調
  - 已 brief 且 `preferred_agent=codex`：可直接交 Codex

#### Phase 4: `experiment_id` 並發防撞

- claim 流程新增 guard：
  - 若 queued task 的 `payload.experiment_id` 已被另一個非 terminal task 佔用，則本輪跳過

#### Phase 5: `agent-spec sync` Alias 正式化

- 新增 `ops agent-spec sync --from claude|codex`
- 內部等價於：
  - `import --from <provider>`
  - `render --target all`
  - `check --target all`

#### Phase 5b: Event Layer

- 在 `config/runtime_schedules.json` 增加 `event_jobs`
- 新增 event expander
  - 讀 `event_jobs`
  - 判斷 `not_before` / `deadline`
  - 用 `dedupe_key` 與 ledger 防重複 materialize
  - 依 `task_template` 建立 control-plane tasks
- 新增 `storage/ops/event_ledger/`
- scheduler 每 tick 執行 event ledger 輕量 GC
- `research_program.md` 保留事件敘事，但不再作為 scheduler 唯一事件來源

#### Phase 7a: Shared Scheduler Tick

- 新增 `src/volpred/ops/scheduler.py`
- `scheduler-tick`
  - 非阻塞取得 `shared_state_lock("scheduler_tick")`
  - 讀 `runtime_schedules.json`
  - stale reclaim
  - event expander
  - cheap preflight：queue / approvals / discovery / slots
  - 無可做任務時直接退出
  - 有任務時決定本輪走 coordinator 或 executor
- `scheduler-preview`
  - 回報本輪會做什麼，不執行
- scheduler 部署層固定為 **macOS `crontab`**
- system crontab 既有永久任務保留，只新增 orchestration tick
- scheduler 自身 logging 改用 `RotatingFileHandler(10MB, backupCount=5)`

#### Phase 7b: Execution Brief 與 Grounding Contract

- 新增 `src/volpred/ops/execution_brief.py`
- recurring task family 先查 `config/brief_templates/`
- 例外 task 再跑 Claude coordinator
- `forbidden_large_files` 在 executor prompt 中轉成 `DO NOT read these files in full`
- `required_files` 必須足以完成任務；若不足則回 `needs_manual_review`
- 大檔沿用既有 token discipline，禁止整檔讀

#### Phase 7c: Observability 與 Cron 退役整理

- `/admin/ops` 與 `/admin/health` 增加：
  - active agents
  - approval backlog
  - latest rollback point
  - recent execution receipts
  - agent-spec drift
  - scheduler heartbeat / last tick
  - event materialization 狀態
  - brief_status 分布
- Claude session cron 退役為非執行時鐘
- `scripts/setup_session_crons.sh` 與 `scripts/session_startup.md` 改寫為：
  - shared scheduler 是正式時鐘
  - session cron 只剩 monitor / 提醒
- 新增：
  - `scripts/install_scheduler_cron.sh`
  - `scripts/uninstall_scheduler_cron.sh`
- cron 安裝必須 idempotent，可重跑、不重複插入
- install script 用固定 tag comment，例如 `# volpred-scheduler-tick`
- uninstall script 依 tag comment 清除

### Runtime Behavior After Completion

- `crontab` 定時執行 `scripts/run_scheduler_tick.sh`
- `run_scheduler_tick.sh` 固定內容：
  - `cd /Users/yhlai0911/volpred-research`
  - `set -a; source .env.local 2>/dev/null || true; set +a`
  - `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"`
  - `exec uv run volpred ops scheduler-tick`
- 正式派工由 `crontab -> shared scheduler tick` 驅動；`idle_policy` 只決定 slot 空出時如何挑 user / scheduled / discovery 任務，不是獨立自動觸發器
- 建議 cron line：
  - `*/10 * * * * /Users/yhlai0911/volpred-research/scripts/run_scheduler_tick.sh # volpred-scheduler-tick`
- scheduler 先做便宜檢查與 event 展開
- recurring/固定模式任務先查模板；模板足夠就直接派工
- 模糊、事件複雜、研究 discovery 任務才喚起 Claude 協調輪生成 brief
- Claude 是協調者，不是每輪都必經的人肉轉接站
- Codex 主要處理被明確 brief 化的任務
- 系統在**機器開著且 `crontab` 生效**時可穩定持續推進；睡眠期間 tick 會跳過，醒來後從下一輪恢復

### Delivery Plan

#### Work Session 1（約 4 小時）

- Phase 0 / 6 / 3 / 1 / 2
- 目標：skills render 修正、schema optional fields、session wrappers、auto routing 都可用
- 結束標準：turn-based 雙 session 流程已穩，無 scheduler 也能手動跑完一輪

#### Work Session 2（約 4 小時）

- Phase 4 / 5 / 5b
- 目標：experiment guard、agent-spec sync alias、event layer 上線
- 結束標準：once-only / event-relative 任務可 materialize 成 control-plane tasks

#### Work Session 3（約 10 小時）

- Phase 7a / 7b / 7c
- 目標：shared scheduler、brief system、grounding enforcement、observability、session cron 退役整理
- 結束標準：shared scheduler 可持續推進 Claude/Codex 工作，且不依賴舊 session cron

### Test Plan

- 結構測試
  - `.claude/skills/**/SKILL.md` 與 `.agents/skills/**/SKILL.md` 第一行都是 `---`
  - render outputs 不再出現小寫 `skill.md`
- Schema 相容測試
  - 舊 task / agent / execution JSON 沒有新欄位時仍能讀取
- Session 測試
  - `VOLPRED_ACTOR` 不符時 `session-bootstrap` fail fast
  - 同一 session 多個 mutating task 預設繼承同一 rollback point
- Routing 測試
  - `preferred_agent=auto` 依 `task_family` 正確分派
  - `brief_status` 未完成時不直接把模糊任務丟給 Codex
- Event 測試
  - one-shot 任務只 materialize 一次
  - relative-to-event 任務在 `not_before` 前不展開、超過 `deadline` 不再展開
  - `dedupe_key` 可防雙重建立
  - event ledger 會正確寫入與 GC
- Scheduler 測試
  - queue 空時不呼叫 LLM
  - `scheduler-preview` 能準確顯示本輪決策
  - cron wrapper 能正確載入 repo root、env、PATH
  - self-lock 能避免雙 tick 併發
- Brief 測試
  - 模板任務不需要跑 Claude 協調輪
  - 例外任務會得到 schema-valid 的 Claude JSON brief
  - `forbidden_large_files` 真的進入 executor prompt
  - `task.updated_at > brief_payload.generated_at` 時 brief 轉 stale
  - 模板 hash 改變時 brief 轉 stale
  - coordinator 最多重試 2 次，第 3 次轉 `needs_manual_review`
  - `prior_findings` 會自動帶入最近 3 筆 receipt 摘要
- Fail-Closed 測試
  - preflight fail 會轉 `blocked`
  - brief stale 會釋放 claim 並回 `queued`
  - 缺檔會轉 `failed`
  - blocked task 可由 `requeue-task` 回復
- Grounding 測試
  - repo root 錯誤、brief 缺失、必要檔缺失、agent-spec drift 時必須拒絕執行
  - brief 的 `required_files` 足以完成任務，且不要求 broad scan
- 回歸測試
  - `pytest`
  - `uv run volpred ops agent-spec check --target all`
  - `uv run volpred ops health`
  - `daily_update`
  - `recalc_metrics`
  - `release-pool-by-settings`
  - `question-ranking-workflow`
  - 前端 regression verifier

### Assumptions / Defaults

- 優先目標是**正確、穩定、token 效率**，不是最大吞吐量
- v1 架構採 **Claude 協調、Claude/Codex 執行**，不採雙主並行自治
- shared scheduler 層固定選 **macOS `crontab`**
- 目前系統是 **`cron-driven shared scheduler + slot-aware idle policy`**，不是純 idle-driven runtime
- Claude session cron 正式退役為非執行時鐘
- Brief 生成策略固定為 **模板優先，Claude 協調輪只處理例外**
- brief 模板固定放在 **`config/brief_templates/*.yaml`**
- Claude coordinator JSON 驗證固定採 **pydantic + fenced JSON 抽取 + 最多 2 次重試**
- brief 過期規則固定為 **`task.updated_at > brief_payload.generated_at` 或 template hash 改變**
- 所有新欄位 optional，讀取用 `.get(...)`，不做 migration
- `rollback_point_id` 預設由 session rollback 繼承，只有高價值或 destructive task 才另建
- `config/runtime_schedules.json` 繼續是唯一排程母本，並新增 `event_jobs`
- v1 **不做 task dependency graph**；事件鏈依賴先靠時間窗與 preconditions
- `claude -p` 是否自動載入 skills 會在 Phase 0 smoke 測試，但執行面不依賴它作為正確性前提
- 正式落檔目標是 `docs/project_improvement_status.md`
- 技術前提仍對齊最新官方能力：Claude 有 hooks / IDE integration；Codex CLI/IDE 目前無官方明確等價的 session cron，因此持續運作依賴 shared scheduler  
  https://code.claude.com/docs/en/vs-code  
  https://code.claude.com/docs/en/settings  
  https://code.claude.com/docs/en/sub-agents  
  https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan/  
  https://github.com/openai/codex


---

## 2026-04-18 Supervisor TODO — Paper 4 (vix-sufficiency) main_v2.tex patches

**Source**: Paper 4 reproducibility audit (task_a2ad5cff36e9, codex-worker) → `paper/vix-sufficiency/reproduce_report_2026-04-18.md`. Audit confidence: strong + codex_reviewed.

**規則**: 論文 .tex 寫作只能 supervisor 親自做 (CLAUDE.md §論文 .tex 寫作). 以下三條屬 supervisor 不可派工 backlog, 必須等 supervisor 有 narrative patch window 時執行 (非自動 tick 派工). 相關 knowledge: `PAPER4_AUDIT` item_id=2baed83f. Relevant experiences: E076, E077.

### TODO-P4-PATCH-1: K745 `41.8% QLIKE improvement` 方向反轉 (推薦 (a) 直接改 tex)
- **Location**: `paper/vix-sufficiency/main_v2.tex:98, 703, 813`
- **事實**: K745 `key_comparison.improvement_pct = -41.8` 意味 **daily HAR-ABS 勝 5-min HAR-RV 41.8%**, 不是反過來.
- **修法**: 改三處敘述為 "5-min HAR-RV underperforms best daily model by 41.8%" 或等義表達; 確保 L98 claim、L703、L813 一致.
- **相關檔**: `paper/vix-sufficiency/experiments/k745_pilot_har_rv_results.json` (n_oos=37)

### TODO-P4-PATCH-2: Table 6 era-cells 數量級錯誤 + "Harvey Pass? 0/5" 錯判 (推薦 (a))
- **Location**: `paper/vix-sufficiency/main_v2.tex:583-590`
- **Canonical source**: `paper/vix-sufficiency/experiments/k752_vix_sufficiency_eras_results.json -> part_d_competing_signals_by_era`
- **Divergent cells**: Overnight VIX Era3 (0.0004→0.0039), Era5 (0.0003→0.0032); VRP proxy Era3 (0.0008→0.0160); Vol mom 20/60 Era3 (0.0006→0.0216), Era5 (0.0002→0.0372).
- **Harvey Pass 正解**: **4 pass** (Era3: Overnight VIX t=-3.15, VRP t=-6.51, Vol mom t=+7.60; Era5: Vol mom t=+9.30), 不是 0/5.
- **修法**: 重寫 Table 6 + header claim + narrative 討論 era 5 VRP failure mechanism (現有文字仍保留但把 "0/5" 改 "4/10 pass Harvey t>3.0 threshold").

### TODO-P4-PATCH-3: Table 3 mixed-sample-window Sharpe ranking 方法論不公 (推薦 (b) 重寫)
- **Location**: `paper/vix-sufficiency/main_v2.tex:470-471, 493`
- **問題**: BH 50/50 Sharpe 0.947 來自 K507 (2005-01-03 – 2026-03-26, n=5339); 12/VIX Sharpe 0.870 來自 K731 不同 sample 窗. L493 ranking claim 混期間.
- **修法**: 選 canonical — 要嘛把 BH 50/50 改用 K731 同窗, 要嘛在 K507 同窗加跑 12/VIX (需新 code task), 要嘛 Table 3 加註 sample-window caveat 並撤回 ranking claim. 決策前不要改 tex.
- **實驗側配合**: 若走 K507 窗統一跑, 可能需派 code task 在 K731 script 加 K507 matching period.

### TODO-P4-PATCH-4: Table 10 SPY/GLD label 與 K738 cross-asset 輸出不符 (推薦 (c) 產 canonical 或 relabel)
- **Location**: `paper/vix-sufficiency/main_v2.tex:772-775`
- **問題**: Table 10 row label 寫 "SPY/GLD", 但 `3.49%/yr` / `2.12%/yr` 取自 K738 `cross_asset_summary.avg_return_drag_{12vix,ewma}` (跨所有 asset 平均); 而 K738 per-asset output 的 mdd_reduction_pp SPY=20.28, GLD=9.42 不是 paper 寫的 -8.2pp.
- **修法選項**: (i) 在 experiments/k738/ 開 subtask 算 SPY/GLD two-asset 專屬 insurance cost output + 存 JSON, 然後 supervisor 改 tex 用該 output; 或 (ii) supervisor 直接 relabel Table 10 為 "Cross-asset summary (6-asset)" 去掉 SPY/GLD 特稱.
- **建議先等 supervisor 決定走 (i) 或 (ii) 再派 code task**.

### 不派 worker 的理由
- P4-PATCH-1/2: 純論文文字修訂 → supervisor 專屬.
- P4-PATCH-3: 需 narrative 決策 (選哪個 canonical window) → supervisor 判斷.
- P4-PATCH-4: 需先走 narrative 決策 (relabel vs rerun) → supervisor 判斷後才能 spawn code task.
- **已派 worker 的部分**: `task_a683510edfc3` (codex-worker, code) — expose Table 2 behavioral sentiment (K732) + calendar anomaly OOS (K736) intermediate outputs, 讓 Table 2 也能 reproduce.

_Created 2026-04-18 06:09 UTC by claude-supervisor from audit task_a2ad5cff36e9._

## 2026-07-25 — Program commit 15 destructive production seam checkpoint

`publisher.article.supabase.delete` 已有獨立 production owner CAS、durable approval、
private WorkItem/EffectRequest/outbox transaction、attempt-bound provider factory，以及
transaction-fenced Supabase compare-delete。Production ACL回讀確認十個 wrapper均為
`volpred_ops_definer` SECURITY DEFINER、空 search path，PUBLIC／anon／authenticated
不可執行，service role only；approval table為RLS + FORCE RLS。

Live smoke 真實走過 approval record／read-back／revoke，並對既有article回讀完整六表
candidate。Owner CAS完成`legacy/1 → operations_core/2 → legacy/3 rollback`；未建立任何
delete attempt、未刪除article。帶假attempt呼叫compare-delete被owner fence拒絕，前後
candidate與evidence hash不變。相鄰回歸
222 passed。此切片為 `root_cause_fixed_and_verified`；整體仍為 `contained`，下一步是
exact restore executor與manual-only delete→rollback→convergence rehearsal，另須完成
program commit 34的physical two-Mac authority receipt pair。

## 2026-07-25 — Program commit 15 exact restore contract checkpoint

Recovery JSONL現在有單一`PublisherArticleDeleteRestoreExecutor`consumer：先驗exact
SHA-256、canonical ordering與完整六表identity，再對全批candidate做absent／exact
preflight；scope drift一律零write。真正restore必須取得mutation authorizer，provider
contract要求單transaction compare-and-restore整批，之後逐candidate exact read-back並
產生hash-bound receipt；已收斂replay維持read-only。

Failure injections與相鄰publisher suites共157 passed；本輪沒有remote mutation。此
execution-contract切片為`root_cause_fixed_and_verified`。整體仍是`contained`：
production service-role atomic restore projection、manual-only live
delete→restore→convergence rehearsal及physical two-Mac receipt pair仍待完成。

## 2026-07-25 — Program commit 15 production atomic restore projection checkpoint

Exact restore已接上production service-role adapter與單一PostgreSQL batch RPC。
RPC先驗七條live cascade edges與完整table row shape，再鎖全批parent／child scope；
只接受absent或exact，依articles→六張child tables順序恢復，雙向relation去重，最後
逐candidate exact read-back。任一中途例外由同一transaction全批rollback；exact
replay回`restored_count=0`且零write。

隔離PG17 migration重套與failure injections **6 passed**，包含nullable child
binding與mid-batch rollback。Production migrations `20260725020432`及forward-only
NULL-safe wrapper `20260725020935`已套用；live回讀確認no-login definer、空search
path、service-role-only wrapper EXECUTE、internal v1不對service role開放、14個RLS
policies及七edge catalog一致，advisors無新增本function告警。本輪未執行production
article delete／restore。此projection slice為
`root_cause_fixed_and_verified`；整體仍是`contained`，下一步是manual-only live
synthetic delete→restore→feed convergence rehearsal，另須physical two-Mac receipt
pair。

## 2026-07-26 — Program commit 15 manual destructive rehearsal seam

新增唯一manual-only operator入口
`scripts/rehearse_publisher_delete_restore.py`。它只接受單筆固定synthetic slug prefix、
已pre-seed且live exact的remote-only candidate，並要求explicit confirmation。流程依序
freeze recovery artifact、record approval、CAS cutover、owned delete、atomic exact
restore、第二個獨立cleanup delete、standing convergence read-back、CAS rollback與
approval revoke。

不確定delete response會先走exact restore；restore本身失敗也不會跳過owner rollback
或approval revoke。Failure injections涵蓋正常完成、第一個delete response遺失、
cleanup response遺失、approval response遺失、restore unavailable及非synthetic scope
拒絕；與相鄰destructive suites共 **56 passed**。本輪沒有remote mutation，所以
operator seam為`root_cause_fixed_and_verified`，program commit 15仍等待實際live
synthetic rehearsal receipt；operations-core umbrella另仍等待physical two-Mac pair。

## 2026-07-26 — Program commit 15 live destructive rehearsal verified

Production rehearsal `live-20260726-0503`已完整完成primary delete、atomic exact restore
與獨立cleanup delete。過程先修正scope approval未提升為generic WorkItem approval，
再以同一live lease的typed preflight與exception context定位
`owned_notification_requests FOR SHARE`被RLS UPDATE default-deny過濾的根因；forward
migration在owner generation已鎖定後改用plain immutable read，沒有替append-only table
開UPDATE policy。

Canonical receipt回讀：兩個WorkItem=`succeeded`、兩個Effect／attempt=`delivered`、
restore=`1/1`、Primary Authority epoch 8／9皆已release、final owner=`legacy/19`、
approval inactive、synthetic row absent，standing convergence=`converged`且
`mismatch_total=0`。此live rehearsal incident為`root_cause_fixed_and_verified`；
operations-core umbrella仍為`contained`，下一步只剩physical two-Mac authority
receipt pair。

## 2026-07-26 — Program commit 34 cross-host receipt identity checkpoint

Cross-host Primary Authority receipt的implementation identity已從單一operator檔提升為
canonical source manifest：operator加上`src/volpred/ops/**/*.py`全部Python source
逐檔SHA-256，再對repo-relative manifest做aggregate SHA-256。Pair verifier同時要求
authority key精確等於shared rehearsal ID導出的隔離key，不能把正式effect-family key
包成rehearsal evidence。

相鄰authority suites **31 passed**，本輪沒有remote acquire、effect或provider call。
Receipt false-positive缺口為`root_cause_fixed_and_verified`；實際physical two-Mac
process roles與paired receipt仍未執行，所以program commit 34及operations-core
umbrella維持`contained`。

## 2026-07-26 — Program commit 34 run-time code stability checkpoint

Cross-host role不再於結束時才決定implementation identity。Primary／standby均在第一個
remote read或mutation前快照canonical Operations Core aggregate，完成remote cleanup後、
建立receipt前重驗；shared checkout若在role執行途中變更，該次run會fail closed且不能
留下receipt，避免舊loaded code被新disk hash冒名。

Primary與standby source-drift failure injection及相鄰authority suites通過，standby
失敗路徑亦確認lease已release。此evidence identity切片為
`root_cause_fixed_and_verified`；本機沒有可操作的第二台Mac remote session，本輪未做
production mutation，physical receipt pair與operations-core umbrella仍為`contained`。

## 2026-07-26 — Program commit 34 cross-host readiness checkpoint

Physical rehearsal現在必須先由兩端各跑只讀`prepare-host`，再以
`verify-readiness`綁定distinct machine fingerprints、shared rehearsal-derived key、
canonical Operations Core aggregate與publisher fence。Primary／standby正式CLI都要求
同一份paired readiness，並在任何authority RPC前重驗本機role、fingerprint與source，
不再先改live lease、最後才發現第二台不相容。

Failure injections與相鄰authority suites **36 passed**；本機production只讀preflight
回讀`operations_core/8`與安全隔離key，沒有authority acquire、effect或provider call。
此pre-mutation sequencing切片為`root_cause_fixed_and_verified`。第二台實體Mac仍沒有
可操作remote session，故physical paired receipt與operations-core umbrella維持
`contained`。

## 2026-07-26 — Program commit 34 readiness evidence-chain checkpoint

Cross-host role不再只由CLI外部檢查readiness。Primary／standby function直接要求同一
typed paired readiness，在第一個remote read／mutation前重驗role、machine、safe key
與source，兩份process receipt v2各自保存readiness SHA-256。Final `verify-pair`也強制
接收該artifact，重驗distinct hosts與完整identity／publisher fence binding，並把相同
SHA寫入final v2 receipt；任意兩份相容role receipt不能再脫離原preflight重組成假綠
evidence。

Failure injections與相鄰authority suites **37 passed**；production只讀preflight
`readiness-binding-20260726-0710`已原子落檔並exact read-back
`operations_core/8`、安全隔離key與新implementation aggregate，沒有authority acquire
或provider call。此evidence-chain切片為`root_cause_fixed_and_verified`；實體第二台
Mac仍無可操作session，故physical paired receipt與operations-core umbrella維持
`contained`。

## 2026-07-26 — Program commit 34 standby primary-evidence checkpoint

Standby不再接受operator手抄的primary epoch或caller自填holder。正式function／CLI要求
同一份primary v2 receipt，並在任何remote read／mutation前驗readiness hash、主機與
source identity、lease window、完整fail-closed evidence、零effect counters及publisher
fence；expected epoch從receipt直接導出。兩端holder ref由shared rehearsal、role與host
fingerprint內部導出，final verifier亦重驗。

Primary receipt drift與holder drift failure injections、相鄰authority suites
**38 passed**。Production只讀preflight `standby-preflight-20260726-0830`原子落檔並
exact read-back `operations_core/8`、安全隔離key與implementation
`a273e8bc7ae65fb0f0205dbc9caadf8485f88422bda6bdceccc0a0796d6fab52`，沒有authority
acquire、effect或provider call。此standby pre-mutation切片為
`root_cause_fixed_and_verified`；實體第二台Mac仍無可操作session，physical paired
receipt與operations-core umbrella維持`contained`。

## 2026-07-26 — Program commit 34 primary artifact binding checkpoint

Standby雖已在任何remote mutation前驗完整primary receipt，舊standby receipt只保存
primary epoch，沒有保存當時驗過的exact artifact identity。Final verifier因此可接受
同epoch但其他內容事後被改寫的primary receipt。Standby receipt現升v3並保存canonical
`primary_receipt_sha256`；final verifier與final receipt同步升v3，必須以當前primary
artifact重算值exact match後才可產生cross-host evidence。

修改primary `completed_at`的failure injection在修前重現假綠、修後fail closed；相鄰
authority suites **41 passed**。Production只讀preflight
`primary-artifact-preflight-20260726-0940`已exact read-back
publisher=`operations_core/8`、stable host fingerprint=`6652d01267d664d621c957b8`與
implementation=`bfa6af660456fb3292b00fbda334c4c21a1dceb79e6e694942077fc24ed34168`。
本機Tailscale恢復Running後，候選第二台Mac仍為offline且ping timeout，故未執行remote
authority mutation。此artifact-binding切片為`root_cause_fixed_and_verified`；
physical paired receipt與operations-core umbrella維持`contained`。

## 2026-07-26 — Program commit 34 raw host-readiness binding checkpoint

舊paired readiness只保存兩份host receipt的digest，roles與final verifier卻沒有raw
artifacts可重算，因而不能證明pair內的第二台host identity確實來自mutation前preflight。
Readiness pair現升v2、內嵌兩端typed raw receipts；所有正式consumer都會重算兩份
canonical hashes並逐欄核對denormalized pair identity。

偽造pair standby identity的failure injection在零新增remote read、零authority acquire
下fail closed；相鄰authority suites **42 passed**。Production只讀preflight
`raw-host-binding-preflight-20260726-1010`已exact read-back
publisher=`operations_core/8`、stable host fingerprint=`6652d01267d664d621c957b8`與
implementation=`66030247729b74be53645bd0d9da87fbe3940f2ba4443034083340691b973c38`，
沒有authority mutation。此raw-artifact binding切片為
`root_cause_fixed_and_verified`；physical paired receipt與operations-core umbrella
仍因第二台實體Mac離線而維持`contained`。

## 2026-07-26 — Program commit 34 readiness freshness checkpoint

Raw host artifacts雖已exact binding，pair v2沒有有效期限；修正前16分鐘舊host
observation仍可配對，20分鐘舊pair甚至會讓primary進入remote read與authority acquire。
Readiness pair現升v3，由兩端較早`observed_at`導出15分鐘`valid_until`，容忍60秒跨機
clock skew；兩個role在任何remote read前共用同一active-window validator，final
verifier則保留歷史稽核語義。

Stale／future／expired failure injections修後在零新增remote read、零authority
acquire下fail closed；相鄰authority suites **44 passed**。Production只讀preflight
`freshness-window-preflight-20260726-103436`已exact read-back
publisher=`operations_core/8`、stable host fingerprint=`6652d01267d664d621c957b8`與
implementation=`4feea2fb05dc0db72eedc92afe13f665586e4e5148a64c120d12454cd707e809`，
沒有authority mutation。此freshness-window切片為
`root_cause_fixed_and_verified`；physical paired receipt與operations-core umbrella
仍因第二台實體Mac離線而維持`contained`。

## 2026-07-26 — Program commit 34 standby retry-freshness checkpoint

Paired readiness的active window不再只守住standby role入口。Takeover等待primary
DB-clock lease到期的每一次acquire attempt，都會在remote authority boundary前重驗
同一`valid_until`；pair在RTO loop中途過期就立即停止，不再繼續碰control plane。

第一次「already held」後推進clock至過期的failure injection確認第二次attempt為零；
相鄰authority suites **45 passed**，`py_compile`與diff gate通過。Production只讀
preflight `retry-freshness-preflight-20260726-1111`已exact read-back
publisher=`operations_core/8`、stable host fingerprint=`6652d01267d664d621c957b8`與
implementation=`44b9c4059dd4ad35da8a0c5574e2ebadb38c04d81942c1e8c41369127273cbdc`，
沒有authority mutation。此retry-freshness切片為
`root_cause_fixed_and_verified`；physical paired receipt與operations-core umbrella
仍因第二台實體Mac離線而維持`contained`。

## 2026-07-26 — Program commit 34 Supabase backend binding checkpoint

Cross-host readiness不再把相同publisher fence誤當成相同database。Service Role RPC
adapter提供只含SHA-256的backend identity；host readiness v2與pair v4要求兩端exact
match，primary／standby role在第一個remote boundary前再驗本機adapter，process與final
receipts亦保存並核對同一digest。

「兩個backend、相同`operations_core/8` fence」與「配對後role換backend」failure
injections均在零authority acquire下fail closed，後者也維持零publisher read；outage與
publisher adapter相鄰 suites共 **48 passed**。Production只讀preflight
`backend-binding-clean-20260726-1158`已由合併後乾淨commit worktree exact read-back
backend=`c6a1e836…a1404`、publisher=`operations_core/8`、stable host
fingerprint=`6652d01267d664d621c957b8`與implementation=`aacc1959…dd8c`，沒有
authority mutation。此backend-identity切片為`root_cause_fixed_and_verified`；
physical paired receipt與operations-core umbrella仍因第二台實體Mac離線而維持
`contained`。

## 2026-07-26 — Program commit 34 receipt directory durability checkpoint

Cross-host receipt writer現在把filesystem transaction完整藏在同一persistence seam：
temporary file fsync後atomic replace，再fsync父目錄，最後才exact read-back並回報
成功。修前failure injection只看到regular-file fsync；修後以真實filesystem驗證
順序為`[regular-file, directory]`，directory open／fsync失敗會fail closed。

Outage與Primary Authority相鄰 suites **49 passed**，`py_compile`與diff gate通過。
此durability切片為`root_cause_fixed_and_verified`；physical paired receipt與
operations-core umbrella仍因第二台實體Mac離線而維持`contained`。

## 2026-07-26 — Owned publisher sync recovery checkpoint

Publisher sync 的 3 筆 due retry 已完成獨立 actuator：production ledger
`20260726093801 operations_core_owned_publisher_article_recovery` 提供
exact-family／kind／generation fenced RPC、ordinary-begin predecessor gate 與
private immutable receipt；canonical hourly piggy-back wrapper 已安裝並通過最小
環境 no-op smoke。

首輪 2/3 delivered，剩餘一筆揭露「payload 缺 tags 時 writer 保留、readback 卻要求
空集合」的 contract 漂移；RED→GREEN 後 attempt 3 delivered。Production 最終回讀
publisher sync 未回收 `due_retry=0`、`started=0`、recovery receipts=4。
Matt 雙軸 review 後再封住兩個邊界：`tags:null` 現在不能冒充 explicit `[]` 清空，
shared service-role RPC 也會在 remote-write guard／pytest runtime 於 HTTP 前
fail closed；mocked transport tests 只能經先隔離真網路的 opt-in fixture 執行。
此 publisher-sync slice 為 `root_cause_fixed_and_verified`；6 筆 publisher-delete
old-generation retry 不屬現 owner authority，仍待獨立 reconcile，Issue #9 umbrella
保持 `contained`。

## 2026-07-26 — Operations Core scheduler writer-policy checkpoint

Full-suite 唯一紅燈揭露新 scheduler LaunchAgent 與
`event_jobs_materialize` 沒有進 canonical writer inventory。現已在
`schedule_materialization` 補正式 `job_id=operations_core_scheduler`，policy 把
daemon 分類為只寫 ignored audit/runtime state 的 delegating clock，並把 event
materializer 的 queue／ledger outputs 歸入 PHASE-Z machine state。Policy suite
17 passed、相鄰 scheduler suite 71 passed，live daemon 為 running，validator
`ok=true`（47 jobs、5 canary owners）。

此 writer-policy 缺漏為 `root_cause_fixed_and_verified`。唯讀 reconcile 仍看到
`audit_publish_sync` 與 `feed_sync` 的 legacy host-crontab simultaneous-owner
conflict；未經 canary cutover transaction 不手動移除，Issue #9 仍是 `contained`。

## 2026-07-26 — Publisher-delete stale retry reconciliation checkpoint

使用者已授權新架構正式上線。Production 的 publisher-delete owner 已回到
`legacy/19`，但六次 destructive restore rehearsal 各留下一筆 generation
6/8/10/12/14/16 的 `retry_scheduled`；六個 scope-bound approval 均已撤銷，
work/effect/outbox 卻仍為 pending/requested/pending。這些列不可能再合法執行，
也不能交給 current-generation provider retry。

`20260726103201_reconcile_stale_owned_publisher_delete` 新增唯一 service-role RPC。
它只選取 exact family/kind、old generation、revoked approval、original immutable
retry receipt 與三層 nonterminal state 全部一致的列，以 `FOR UPDATE SKIP LOCKED`
原子領取；不接受 provider／Primary Authority／delete projection。原 attempt 與
attempt receipt 保持 `retry_scheduled` 作歷史證據，另寫 private FORCE-RLS
reconciliation receipt，並把 WorkItem、EffectRequest、outbox 終止。

Production 首輪精確收斂 6/6，回讀 `receipt_count=6`、`fully_converged=6`、
`approvals_still_revoked=6`、`work_receipts=6`；同一 RPC 重跑
`reconciled_count=0`。既有 hourly `owned_publisher_article_recovery` 入口已升為
v2，先走零-provider delete reconciliation，再走原 publisher-sync recovery；
production wrapper smoke 兩邊均為零筆 no-op。此切片完成五步 gate，狀態為
`root_cause_fixed_and_verified`。

Matt 雙軸初審其後抓到 selector 尚未證明跨表 parent identity、decoder 未驗證
generation 順序／固定 reason，以及 schedule metadata 仍描述成 sync-only。
`20260726104730_fence_publisher_delete_reconciliation_identity` 已以 forward migration
補 request→work→effect→outbox→attempt receipt 全鏈 identity fences；cross-linked
request 的 PostgreSQL 負向案例先 RED 後 GREEN。Python decoder 現拒絕
`current_generation <= stale_generation` 與未知 reason；runtime schedule／writer
inventory 也已明列零-provider delete reconciliation。Production function definition
回讀三組 identity fence 均存在，重跑仍為 0。

## 2026-07-26 — Operations Core scheduler 全量上線

- ✅ `schedule_materialization.mode=active`；49/49 executable system jobs 已轉給
  `com.volpred.operations-core-scheduler`。
- ✅ Host crontab 的 VolPred entries=0；舊 per-job LaunchAgents=0；wrapper effect 前
  另有 fail-closed owner gate。唯讀 reconcile 為
  `owner_surfaces_verified`，0 conflict、0 dormant legacy surface。
- ✅ active boundary 後自然 `event_jobs_materialize` fire attempt 1 exit 0；immutable
  fire identity／duplicate suppression／no-early-fire 均有 live receipt。
- ✅ 七條 session-local CronCreate 全數制度化退役，`session_crons.items=[]`；
  knowledge index 改由新的 Operations Core 六小時 wrapper 執行，其餘功能有 explicit
  replacement mapping，`run_due_jobs` 不再寫新的 pending-session marker。
- ✅ NDC hand-off 遵守 direct execution：legacy queue 關閉時明確失敗並留 receipt，
  本次 stale work 已登記 GitHub Issue #38；沒有手改 next_tasks 或 canonical CSV。
- 🟡 Scheduler 已正式提供服務，但 Issue #28 的 sustained-clean 觀察窗仍為
  `contained`。Issue #9 是獨立的 Work Coordinator queue cutover，七日 evidence 未滿，
  不隨 scheduler ownership 自動結案。

## 2026-07-26 — Active daemon owner audit 與新架構通知標示

- 線上查核發現 `com.volpred.dispatch-supervisor` 未載入、heartbeat 停止，但 scheduler
  owner audit 仍回報 0 conflict。服務已由 canonical plist 恢復，heartbeat 與實際
  hourly worker 均重新運作。
- 根因不是 scheduler job ownership，而是 reconciler 只稽核 business clock 與 legacy
  surfaces，漏掉 `runtime_schedules.json.daemons`。owner plan／audit／apply 現正式管理
  active KeepAlive daemons：缺失轉紅，apply 自動安裝並 bootstrap，已載入者不重啟。
- Production `--apply` 已冪等回讀：host crontab unchanged、49/49 Operations Core jobs、
  required dispatch daemon present、0 conflict；heartbeat checker `breached=false`。
- dispatch-supervisor 寄出的所有管理通知標題統一加 `[新架構派發]`。19:06 收到的
  `supervisor restart` 是本次恢復新派發層產生，不是舊逐工作 LaunchAgent。
- 19:13 的 Operations Core worker Telegram 班報同樣確認來自新架構，但它繞過 daemon
  alert sink，標題未帶來源，且把已恢復的真 outage 說成「誤報」。worker prompt contract
  已補兩個 gate：所有外部報告 title／第一行必帶 `[新架構派發]`；歷史 incident 必以
  告警當下 evidence 裁決，current healthy 只能稱 recovered，不得倒推 false positive。
  同一 contract 已由一般 Claude worker、Codex failover 與 failover inline fallback 共用。
- 此 active-daemon 漏查 incident 為 `root_cause_fixed_and_verified`；T09 整體仍須
  sustained-clean 長窗，維持 `contained`。

## 2026-07-26 — NDC ingestion 改為 quota-independent 自動流程

- ✅ 移除 `collect_ndc_bci.py` 的人工 Chrome 指示與錯誤 endpoint 註解；正式流程由
  Playwright + 本機 Chrome 取得官方 Angular app 的 JSON 回應。
- ✅ 以官方固定代碼 `SR0051`／`SR0005`、schema、期間、有限數值與 SHA-256
  fail closed；保存含 capture time、source latest date、官方 revision notice 的
  source snapshot。
- ✅ canonical CSV 採 atomic upsert、逐列 readback、freshness postcondition；
  unattended writer 只 self-commit CSV 與 snapshot，既有工作樹其他修改不會被帶入。
- ✅ `ndc_indicator_refresh` Operations Core wrapper 直接執行 collector；fresh 時
  tiny skip，stale 時自動同步，不再寫 legacy queue 或等待 Claude／Codex 額度。
- ✅ 首次 live 同步後兩條必要序列均到 `2026M05`：領先指標 `103.81`、信號 `39`；
  補齊 17 個缺月並保存官方 current-vintage 全歷史修正。Issue #38 可依此證據結案。
- ⚠️ NDC 官方每月回溯修正完整歷史；`tw_dgbas_bci_m.csv` 是 current-vintage
  canonical，不是歷史 point-in-time database。Git 自本次起保存 snapshot 版本，
  任何舊期回測若需要 real-time vintage，必須另設 availability/vintage gate。

## 2026-07-26 — 模型派發收斂到 Operations Core 單時鐘

- ✅ 新增 `agent_dispatch_tick`：Operations Core 每分鐘經權限 0600 的本機 Unix socket
  觸發 dispatch executor；executor 的 internal scheduler loop 已從 production
  `_run_async` 拔除。
- ✅ executor 仍保留 4 slots、健康監控、Claude→Codex failover、quota derating、
  worktree isolation 與 PHASE-Z；因此單一時鐘不以犧牲並行能力換取。
- ✅ trigger receipt 與 model completion receipt 分離：額度用盡不會讓 scheduler
  停止或假裝模型成功；下一個合法 hourly/requested tick 會在額度恢復後自然重試。
- ✅ 舊 `codex_loop.sh` 已停止；SessionStart 呼叫的
  `auto_start_codex_loop.sh` 預設改為 retired no-op，重新開 Claude／Codex 不會復活
  第二個派工時鐘。
- ✅ live socket round-trip 回傳 `not_due`、owner audit 為 50/50 Operations Core、
  0 legacy／0 conflict；Mac launchd 的 Operations Core 與 dispatch executor 均為
  RunAtLoad／KeepAlive。

## 2026-07-26 — Direct-mode 正式退出契約

- ✅ 修正 active receipt 永遠保留 control row、restore 卻要求 live queue完全為空的
  自相矛盾；restore現在只接受 receipt-bound control rows，receipt外 identity、
  anonymous或duplicate row全數 fail closed。
- ✅ 覆寫前把現行 control rows原始bytes durable archive，prepared／final receipt
  綁定path、SHA-256、bytes與row count；crash retry會重新驗證，不能靜默遺失
  direct-mode期間的新checkpoint。
- ✅ backup內的`claimed`／`in_progress` task必須由operator以
  `--expected-active-task-id`精確列出整個集合；漏列、多列或prepared receipt與backup
  漂移都在queue mutation前拒絕。
- ✅ public function／CLI／crash-tamper回歸共37案通過。底層restore可退出性根因已
  `root_cause_fixed_and_verified`。
- ✅ Production已於12:14 UTC走正式CLI退出：3338筆備份復原，direct期間唯一control
  row原始bytes另存archive並由SHA-256回讀；mode為`queued_execution`／`enabled=false`。
- ✅ Restore後發現5筆歷史`pending` row帶active claim trace；cleanup原先只掃
  `claimed`／`in_progress`。正式cleanup現可留下pending→pending audit再清除 residue，
  仍有live compute job則fail closed；3個TDD回歸與live readback確認
  `pending_claim_residue=0`。此cleanup缺口為`root_cause_fixed_and_verified`。
- ⏳ Operations Core tick已在restore後持續；內容產出是否恢復仍需第一筆publisher
  acknowledgement，未取得前只宣稱queue/control plane恢復，不把content recovery
  說成完成。

## 2026-07-26 — Physical two-Mac Primary Authority 正式結案

- ✅ Mac Studio與MacBook Pro透過專用SSH key及Tailscale建立可操作的兩個實體failure
  domains；硬體fingerprint分別為`6652d012…57b8`與`d9fca0a4…fbde`。
- ✅ MacBook部署最小Operations Core checkout，不啟動scheduler／dispatcher；兩端
  Python `3.12.10`、OpenSSL `3.0.16`、implementation
  `b83f7bbc…e5003`與Supabase backend `c6a1e836…a1404` exact match。
- ✅ readiness v4在15分鐘窗內配對；Studio完成健康renew→partition→59.220721秒demote，
  local gate關閉且partition probe被拒。
- ✅ MacBook在primary DB expiry後取得exact-next epoch `2`，handoff
  `0.162352s`，隨即release；successful claims=2、duplicate/effect/provider=0，
  publisher fence全程`operations_core/8`。
- ✅ final `verify-pair`為`cross_host_verified=true`；canonical evidence：
  `storage/ops/primary_authority_outage_cross_host_latest.json`。Program commit 15及
  Operations Core umbrella的最後外部硬體gate為
  `root_cause_fixed_and_verified`。

## 2026-07-26 — Matt workflow living-doc 漂移修正

- ✅ Live 回讀確認 Matt Pocock suite 位於 Codex / Agent Skills 全域 surface
  `$HOME/.agents/skills/`；先前只查 `~/.claude` 就宣稱 `ask-matt` 不存在，是
  runtime surface 身分混淆。
- ✅ `AGENTS.md` 已移除互相矛盾的舊聲明，記錄正確安裝位置、驗證命令與三種 skill
  surface 的邊界；current docs 關鍵字稽核無其他同類錯誤聲明。
- ✅ 新增九項必要 manifest 的可執行稽核與 4 個 regression；缺檔、frontmatter 錯名、
  不完整 CLI 都 fail closed，文件也不能再宣稱 router 不存在。
- ✅ 既有計畫不重建：GitHub Issue #3 → master spec → Issues #5~#36 仍是 canonical；
  接續優化按 `ask-matt` 的 `implement` → `tdd` → `code-review` 逐 ticket 執行。
- ✅ 此 living-doc drift 已 `root_cause_fixed_and_verified`；它沒有修改另一 session
  的 task-pool/runtime state 或任何現行排程。

## 2026-07-26 — Boss Report owned delivery 與 canonical read model（Issue #39）

- 🔎 20:10 production receipt 證明 trigger 已由 Operations Core 擁有，但 caller
  仍以 direct SMTP 寄信；cycle intent／next actions 又取自 2026-05-19 的
  pseudo-living files。這是 #11 owned-email 架構未涵蓋 Boss Report caller 的
  acceptance gap，不是舊 cron 重複觸發。
- ✅ 寄信入口已收斂為 `dispatch_email_by_current_owner()`；Boss Report 用 exact
  schedule fire key 作 idempotency key，`operations_core` 必走
  WorkItem／EffectRequest／outbox／Primary Authority／Gmail Sent read-back，
  durable owner 明確為 `legacy` 時才保留 direct rollback，owner read failure
  在 provider 建立前 fail closed。
- ✅ 新 typed read model 只讀 master spec §7 與 current task-pool mode；完成列省略，
  contained／pending 保留 exact status 與 source SHA。它同時認得 direct mode 與
  12:14 UTC 已合法完成的 queued-mode restore，不修改另一 session 的 control state。
- ✅ 小寫 UTC `z` 於 reader 邊界正規化，未手改 `storage/work_log.json`；dry render
  回讀確認 5 月 cycle／舊 action／該 historical warning 均消失。
- ✅ production wrapper、repo source 與 manifest 已 lockstep，SHA-256 均為
  `f28fab932a917498db7f25472507fbb228538a515c5b1f6d4097ee09ca7eaee6`。
  Cross-host shared request／terminal read、exact schema、canonical fire validator
  與 legacy Primary Authority／deterministic Gmail Sent replay 已進回歸；owner
  transfer 在該 PA lease 有效時會 fail closed，不能於 legacy SMTP 中途切 owner。
- ✅ production migration `20260726134809` 已部署；函式 owner／ACL、shared-read
  schema、terminal replay 與 owner-transfer advisory fence 均由 production 回讀確認。
- ✅ live acceptance fire 建立 WorkItem／EffectRequest／outbox attempt 1，settlement
  為 delivered，帶 Gmail Sent evidence 與 Primary Authority ref；同 fire 再跑只回
  相同 terminal receipt，effect 不變且 attempt_count 仍為 1。
- ✅ 2026-07-27 08:10 台灣時間自然 fire
  `operations-core-v1:boss_report_4h:35208392b85064c22499c492` 由
  `operations-core-scheduler` attempt 1 成功；RPC 回讀 owner=`operations_core/4`、
  WorkItem=`succeeded`、Effect=`delivered`、attempt_count=`1`、Primary Authority
  epoch `211`，Gmail Sent evidence 與 scheduler receipt 完全一致。未見 direct
  SMTP、重送或 owner drift；closure scoped regression 103 passed，狀態為
  **`root_cause_fixed_and_verified`**。

## 2026-07-27 — Publisher／Sync Effect Delivery 完成 Mirror acknowledgement（Issue #14）

- 🔎 T06 acceptance audit確認 formal publisher receipt過去只證明Supabase row／tags；
  frontend cache purge回傳值被忽略，而且Supabase已相符時會直接settle。網站可能仍讀到
  舊內容，effect卻顯示delivered。
- ✅ 正式single-article、hourly recovery與hourly batch reconcile都啟用composite
  acknowledgement：Supabase exact read-back、public article API reader-visible
  exact read-back及typed cache revalidation acknowledgement缺一不可。只有明確
  legacy rollback保留舊capability，不新增第二套retry或pending queue。
- ✅ 失敗仍由既有WorkItem／EffectRequest／outbox的bounded retry與durable
  dead-letter處理；receipt evidence ref保存Supabase、public article／feed health與
  cache POST target／HTTP status，aggregate SHA-256綁定三段觀察。
- ✅ Reader-visible/internal detail分界已收斂到versioned
  `config/public_article_projection_contract.json`，policy SHA-256
  `6d125ff3…806888`；hourly audit與兩個rollback rehearsal必須持有exact
  contract evidence。缺檔、壞JSON、digest／frontend drift都fail closed並寫
  `unavailable`，public payload在過濾前即拒絕internal key洩漏。
- ✅ Single失敗receipt保存typed cache target/status/ref/hash；batch reconcile逐篇
  write後立即readback，partial batch receipt保留先前成功與失敗項目的全部refs，
  不再把evidence丟成generic failure。
- ✅ Immutable batch due recovery已接進同一canonical hourly runner，只可重播原
  Effect與durable payload。Production migration
  `20260726182802 owned_publisher_reconcile_recovery`已部署；回讀為private table
  FORCE RLS、外部roles無直讀、RPC僅service role execute。部署後due candidates與
  canonical runner皆為0。
- ✅ TDD紅測先證明舊介面無法要求Mirror ack；修後formal effect與publisher相鄰
  scoped回歸通過，另有production read-only public body exact match。
- ✅ Live acceptance在owner `operations_core/8`建立
  `effect_owned_publisher_e35fe214c6acef66f14d87da4aec7f2e`：attempt 1、
  Work succeeded、Effect delivered，evidence為
  `supabase:articles/mile_beee535c|https://volpred.zeabur.app/api/publications/feed/mile_beee535c#status=200`；
  同key重播回同一terminal receipt且attempt仍為1。
- ✅ Production read-only另確認 omitted-tags/comma-packed案例
  `mile_cc6ea154` composite match；隱藏文章`mile_f9c70bd0`的initial HTTP 404即使
  reader feed健康，在無same-attempt cache ack時仍為`matches=false`。
- ✅ Live write-boundary驗收以同一canonical hidden article建立
  `effect_owned_publisher_db02df8f575ce1bbe317bafd7bd7e577`，attempt 1 delivered；
  receipt含Supabase、article 404、健康feed 200、cache POST 200及aggregate digest
  `74a7720…22bdd2`。同key重播仍是同一effect／digest且attempt維持1。
- ✅ Issue #14五項acceptance的底層流程、回歸、production read-back與活文件已齊；
  固定base的Matt spec／standards雙軸複審皆PASS。最終scoped行為測試為
  152 passed、1 skipped、1個既有基線案例deselect，PostgreSQL交易測試另56 passed；
  狀態為 **`root_cause_fixed_and_verified`**。

## 2026-07-27 — Mutating execution isolation production enforcement（Issue #43）

- ✅ 依既有 Matt Issue #3 → master spec → T35 ticket 執行，未重做 plan/spec/tickets。
  Mutating work 的 public interface 現只允許 isolated workspace 或 requeue；無法配發、
  preflight 不完整、receipt 寫入失敗都不會 firing unisolated。
- ✅ Admission 原子綁定 task id、claim session、workspace identity、base SHA 與 exact
  declared paths；producer 的 macOS sandbox 拒絕 canonical state、common Git metadata、
  credential files及外部 transport，machine finalizer 才能做 exact-path commit、gate、
  main-base CAS、merge及 durable settlement。
- ✅ 失敗注入及 E2E 覆蓋雙 slot 不同路徑、同路徑 conflict、pre-dirty target、
  CAS lost、stale gate、worker crash、restart orphan、admission outbox與 settlement
  recovery；最終相鄰組合測試 **326 passed**，spec／standards獨立複審均 PASS。
- ✅ Production canary `issue43_live_canary_v2_20260727` 的 job
  `80f1563b6a1f4dd89d5e100e2e0f4005` 在 enforce mode 完成；worker 唯一變更
  `docs/ops/issue43_live_canary.md`，machine landing commit `296aabac0` 無 foreign
  path。Gate、terminal intent、finalized、settlement receipts 分別為
  `dd8e3614…`、`38b6fe70…`、`0b19918a…`、`c256addc…`，queue 回讀 succeeded。
- ✅ Live canary 沒有掩蓋部署錯誤：前兩輪依序抓出 log FD 被 sandbox 拒絕、
  dispatch identity env 被剝除及 synthetic HOME 無模型認證。根因修於
  `6893fb285`／`5b1b8b979`；模型 token 僅由 supervisor 從 owner-only regular file
  讀入單一 allowlisted env，worker 仍不能讀 secret tree或取得 SSH/Git/cloud/Telegram
  authority。重載後 live replay 通過，狀態為 **`root_cause_fixed_and_verified`**。
- ⏭️ 這只結案 T35；PHASE-Z legacy recognizer、舊 wrapper及其他 compatibility path
  仍須按後續 ticket 各自完成五步 Gate 後才能宣稱「新架構完全取代舊架構」。

## 2026-07-27 — Global Primary Authority production deployment（Issue #18）

- ✅ Formal commit/effect authority 已收斂為單一
  `operations-core-primary`；Python adapters、database formal-grant trigger及live
  owned-effect SQL mutation boundaries均拒絕capability-scoped formal authority。
- ✅ Append-only lifecycle ledger保存acquire／renew／natural expiry／demote／reject；
  release未確認或回讀drift時以token-redacted、backend-bound、fsync journal在恢復後
  reconcile，多worker peer cleanup具冪等競態回歸。
- ✅ Production migration `20260727080000` 已精確部署並回讀owner／FORCE RLS／ACL，
  migration ledger本地與remote exact match，legacy SQL authority boundary計數為0。
- ✅ Global-key live canary證明epoch 1 acquire→renew→release、第二holder fail closed、
  synthetic authorize grant及durable事件回讀；最終相關套件 **467 passed**，
  Matt Spec／Standards雙軸review皆PASS，supervisor planned reload後heartbeat正常。
- 🟡 Issue #18仍為 **`contained`**：synthetic authorize不等於真實Git／email mutation
  partition canary；direct legacy caller cutover與全域retirement仍由#24／#46完成，
  五步Gate未齊前不關Issue、不宣稱新架構已完全取代舊架構。

## 2026-07-27 — Task success／Issue closure lifecycle 分離（Issue #47）

- ✅ Linked runtime task成功預設`issue_disposition=contained`，不再自動關閉parent
  GitHub issue；只有整張issue五步Gate全過才可明確指定`close`。
- ✅ Close receipt在producer、candidate與ack三段都綁task id、canonical issue ref、
  completion timestamp、commit SHA及exact pending receipt；legacy／ambiguous／drift
  一律在GitHub IO前fail closed。
- ✅ Missing HEAD／invalid issue會保留task in-progress，annotate不能改closure lifecycle。
- ✅ 相關測試 **315 passed**，Matt Spec／Standards雙軸PASS。
- ✅ Live default-contained task commit `6036b7c6a`後#47保持OPEN且marker=0；
  explicit-close task commit `9677d28bb`才產生exact marker並CLOSED。Issue #47為
  **`root_cause_fixed_and_verified`**。

## 2026-07-27 — Frontend Route／Scenario Parity Checker（Issue #6）

- ✅ 沿用既有 Matt Issue #3 → master spec → T19 ticket，未重做 plan/spec/tickets。
  Active frontend只從`config/project_targets.json`讀取；contract逐mode／surface記
  authoritative owner、capability、advantage、access與explicit known gap。
- ✅ App Router pages、route handlers、metadata與redirect組成唯一inventory；
  handler逐實際source與HTTP method展開，contract→source與source→contract雙向exact，
  不會把兩個surface的GET／POST union成假完整。
- ✅ Navigation fail-closed涵蓋href、dynamic segment、typed/destructured/direct router、
  alias／optional／bracket reference、`next/navigation` named／namespace import及各種
  re-export；無法局部證明的binding直接block。註解／字串不會製造假route或假link。
- ✅ 每個source先resolve在active frontend／repo boundary內，後續只讀resolved path；
  nested Git HEAD、dirty digest與source tree SHA在audit前後CAS，漂移receipt無效。
- ✅ 最終adversarial suite **27 passed**，Matt Spec／Standards雙軸均PASS。live
  read-back為133 route-method rows、25 rules、7 required scenarios、4 known gaps、
  32 blockers，`source_revision.stable=true`；同一source連跑兩次SHA-256皆
  `0e3b70851ad0e9350df7a92f4a4395837cee6bd61d111c9da10fd22c806e989a`。
- ✅ Issue #6 checker本身為 **`root_cause_fixed_and_verified`**。Live report的3個
  dead links、2個scenario evidence gaps、27個unresolved navigation targets以及
  4個single-mode gaps是#8/T20的精確輸入；frontend parity仍未完成，不得混淆口徑。

## 2026-07-27 — Queue Ownership 七日 clean-suffix gate（Issue #9）

- ✅ 依既有 Matt Issue #3 → master spec → T03 ticket 接續，未重跑規劃。Live queue
  已回復 `queued_execution`；read-back 為 3,386 rows／84 pending／0 active claim，
  owner-state SHA-256 `3653409c0c3e22dcdb3e5c12c3a5d86014789db6718e19af5b48033f002fb1f2`。
- ✅ 23:37 UTC 後五筆 hourly v4 receipt 均為 0 reconciliation issue；winner 差異是
  已由 policy oracle 與 snapshot evidence 綁定的 `coordinator_capability_contract`。
- ✅ `9eb9845f1` 已讓新 claim 持久化兩小時 expiry，並把 main-thread lane 映射成
  Coordinator exclusive capability；claim／migration／replay 141 tests 綠。
- ✅ 04:31 UTC receipt 的 blocking dimension mismatch 由 10 降為 3；僅剩修復前
  已在執行的 `assign_8262c921` 缺 readiness／claim ownership／durable lease expiry。
  該 claim 當時仍在執行，未人工釋放；自然結束後，04:56:14 UTC 正式
  receipt `scheduled_20260727T045614581709Z_def2f814b885` 已回讀 3,389／3,389
  comparisons、0 reconciliation、0 blocking dimensions，252 個差異全為 evidence-bound
  registered policy change，七日 continuous-clean suffix 已由該時刻啟動。
- ✅ Closure audit 證明原 assessor 只在 owner SHA 改變時重啟窗口；同 owner 下即使
  legacy provenance／row evidence 已修好，舊 blocking receipt 仍會永久留在七日集合，
  使 ticket 在數學上永遠無法完成。
- ✅ 公開 assessment seam 現取最新一段內容乾淨、時間連續且 replay clock live 的
  segment；只有該 segment 真正滿七日才取代舊集合，歷史 receipt 仍 append-only 保留。
  Owner epoch 與 segment 皆以 `max(recorded_at, observed_at)` 的有效順序處理，最新
  receipt 無法靠大幅 backdate 移到舊窗口前方，也無法藏掉 owner mismatch。
  Legacy corruption、incomplete row-count、歷史 gap 與歷史 clock violation均先紅後綠；
  近期 gap／clock violation與兩種 backdate attack仍會推翻較舊完整窗口。Assessment
  **37 passed**，相鄰 cutover／replay／observer suites 合計 **104 passed**。
- ✅ 修正 schedule-receipt test isolation 後，全專案回歸為 **5,721 passed、
  1 skipped**；Matt Spec／Standards 雙軸 review 皆 PASS，沒有 P1／P2。
- ✅ Closure read-back 另發現 `blocked_until` 仍保留舊窗口日期；generic expiry
  sweeper 原本只看日期，可能在新 clean suffix 滿七日前把 #9 提早轉 pending。
  現在日期只作 not-before：`mark_task_blocked.py --unblock-gate
  work_shadow_cutover_ready_v1` 寫入 allowlisted lifecycle contract，expiry sweep
  必須再從 owner-bound append-only receipts 跑 canonical assessment，唯有
  `ready_for_cutover=true` 才能 re-pend；未知 gate、讀取失敗或窗口不足皆 fail closed。
  正式 parent task 已回讀 `blocked_until=2026-08-03T04:56:16.743114Z` 且 gate 綁定；
  把其日期在記憶體中改成已過期後重播，結果仍為 `swept=[]`／status=`blocked`。
  Reviewer 另抓到 manual unblock／release bypass與whole-writer schema缺口；現已禁止
  gated row 經 manual unblock、release、claim、start、handoff或supervisor preassign
  進入dispatchable狀態，且canonical `next_tasks` writer機械拒絕非法
  gate/status/reason/until組合。Production adapter以真owner evidence與receipt fixtures
  覆蓋ready、短窗口、owner mismatch及evidence不可讀。Reviewer第二輪發現re-block
  可移除gate及mark CLI分離讀寫鎖；現改為既有gate在非terminal re-block不可移除，
  且同一queue descriptor持`LOCK_EX`完成read→mutate→write，並行writer交錯測試證明
  兩邊transition皆保留；含 pool-pressure fail-visible 與 canonical-writer
  guard 回歸的相鄰套件 **217 passed**。
- 🟡 clean suffix 已開始但尚未滿七日；Work Coordinator owner 仍為 `legacy/1`，且
  未執行 stage／owner transfer／downstream acknowledgement／rollback rehearsal；
  Issue #9 維持 **`contained`**，不得提前標完成。

## 2026-07-27 — Git formal commit mutation-boundary fencing（Issue #18）

- ✅ 依既有 Matt Issue #3 → master spec → T13 ticket 接續，未重跑
  plan/spec/tickets；Issue #9 的七日 clean suffix 尚未滿，因此改接 blockers 已完成且
  不碰 frontend／PHASE-Z session 的 #18 tracer slice。
- 🔎 `GitCommitActuator` 原本只在準備階段取得一次 durable authority grant；grant
  返回後若 WorkLease、commit owner generation 或全域 Primary Authority 在真正 Git
  writer 啟動前失效，現行流程仍可能落 commit。原公開 seam RED case 確實在第二次
  authority 應拒絕時產生新 HEAD。
- ✅ actuator 現在於持有 canonical Git writer lock、argv 與 exact content hashes
  固定後，緊貼 subprocess 前重跑同一 durable authority transaction；第二次 grant
  必須與第一次完全一致。partition、stale lease、owner generation 或 grant identity
  漂移皆在 Git mutation 前 fail closed，原 grant 保留供精確事故復原。
- ✅ `tests/test_git_commit_actuator.py` **26 passed**；Change Delivery、Supabase／
  Primary Authority、session／keepalive／outage相鄰套件 **107 passed**；
  PostgreSQL commit-authority transaction **8 passed**，其中三個end-to-end案例在
  durable grant後分別使WorkLease、owner generation、Primary Authority失效，均回讀
  HEAD／index不變；全專案回歸 **5,738 passed、1 skipped**，`git diff --check`通過。
- ✅ 此 Git mutation-boundary fencing根因為
  **`root_cause_fixed_and_verified`**。Issue #18整體仍為 **`contained`**：
  Email真實partition canary與 #24/#46 direct legacy writer cutover／retirement尚未完成。

## 2026-07-27 — Email SMTP mutation-boundary fencing（Issue #18）

- ✅ 依既有 Matt Issue #3 → master spec → T13 ticket 接續，未重跑
  plan/spec/tickets；修改範圍只含 Email delivery deep module及其測試，未碰另一個
  session正在修改的supervisor、termination、Git hook或experiment檔案。
- 🔎 `OwnedEmailNotification` 雖會在進入provider前驗證Primary Authority，
  `EmailNotificationEffectAdapter`卻會先查Sent mailbox才呼叫SMTP。公開介面RED案例
  在第一次Sent read-back期間換掉lease；修正前仍會呼叫notifier且不會拋出
  `NotificationOwnershipLost`，證明授權檢查與真正SMTP mutation間存在競態窗口。
- ✅ adapter現接受窄的`authorize_mutation` callback，在確認沒有既有Sent copy之後、
  緊貼SMTP notifier之前執行。授權錯誤不會被provider failure mapping吞掉，也不會
  settle成retry/dead-letter；normal delivery、expired-attempt recovery與legacy rollback
  三條路徑都使用同一個Primary Lease identity重新驗證。已存在Sent copy的冪等replay
  仍直接回讀，不需再次取得mutation authority。
- ✅ 原案例RED→GREEN；Email notification／owned delivery／alerts／worker／boss report／
  PostgreSQL settlement完整相關範圍 **206 passed**，Matt Spec／Standards雙軸review
  均PASS、0 P1／P2，commit `6ca2d9adf`通過`git show --check`。
- ✅ 全庫回歸為 **5,746 passed、1 skipped、3 failed**；三個失敗分別來自另一個
  session未提交的termination API、Git hook packaging及新實驗K1730 nested-DM gate，
  與本slice四個commit檔案無交集；真實外部驗收因此改由commit `069350634`的乾淨
  archive執行，不載入共享髒檔。owner-only正式寄送由`operations_core/4`完成，
  WorkItem／Effect均delivered、Gmail Sent evidence回讀成功；同key立即重播仍為
  `attempt_count=1`且所有identity／evidence完全相同。第二案在真實IMAP read後demote
  Primary Authority epoch 35，SMTP notification log=0，獨立Message-ID回讀亦不存在。
  去敏receipt為`storage/ops/email_mutation_boundary_canary_latest.json`。Email SMTP
  mutation-boundary五步Gate已全過，狀態升級為
  **`root_cause_fixed_and_verified`**；Issue #18 acceptance scope完成，可關閉。
  #24/#46 direct legacy writer retirement仍由各自ticket追蹤，不再混入本Issue狀態。

## 2026-07-27 — Warm Standby closure audit 與雙機重演（Issue #21）

- ✅ 沿用既有Matt plan/spec/ticket，不重跑規劃；closure audit確認#21的GitHub
  blocking edges仍包含#16/#17，而兩者等待#12→#9七日ownership gate，因此本輪不得
  關閉#21或宣稱持續warm standby完成。
- ✅ MacBook上的誤疊full-repo部署已移到
  `~/.Trash/volpred-research-unsafe-20260727T1608`保留可復原副本；正式目錄重建為
  最小tracked Operations Core runtime，不含Git history、storage、experiments、
  frontend或Studio secret。MacBook只沿用本機既有mode-600 authority環境與已驗證
  Python `3.12.10`／OpenSSL `3.0.16` venv，且沒有VolPred LaunchAgent／cron。
- ✅ 雙機readiness v4在任何lease mutation前確認不同硬體fingerprint、相同backend、
  相同publisher owner `operations_core/8`及相同implementation
  `9db5479f…e401`。新演練`issue21-warm-standby-20260727-1615`中，Studio於
  transport partition後`9.635672s`關閉local gate；MacBook只在舊lease的DB-clock
  expiry後取得exact-next epoch `2`，standby等待`29.034066s`、DB-clock handoff
  `0.528014s`，claims=2、duplicate/effect/provider=0。
- 🟡 Canonical aggregate receipt已更新為
  `storage/ops/primary_authority_outage_cross_host_latest.json`；五份raw receipt另以
  mode 600保存於`~/.volpred/handoffs/issue21-20260727T0811Z/`。本輪只完成
  isolated no-effect takeover slice；formal effect RPO=0、guided parity／TCC、
  可重複cold restore與持續standby仍待#16/#17/#24，因此#21維持
  **`contained`／OPEN**。
## 2026-07-27 — T20 Original／v3 First-paint 與 Beacon（Issue #8）

- ✅ 原版與v3首頁以同一server snapshot首屏；raw HTML、desktop/mobile立即DOM與
  hydration後DOM均回讀實驗數115，沒有mock、`—`或knowledge count 3,198覆寫。
- ✅ 同一typed analytics contract涵蓋impression、click、read depth、
  qualified action與return visit；browser E2E實際產生前四類，production DB回讀
  15列／15 distinct idempotency keys、retention drift 0，exact replay為duplicate。
- ✅ PostgreSQL private schema／FORCE RLS／RPC ACL已精確部署並回讀；production
  receipts為`20260727100227`與`20260727100422`。
- ✅ Zeabur deployment `6a6736c7225290ec74322de0`為RUNNING。部署secret由Keychain
  供應，只進variable API的外部temp file；source upload與container均沒有
  `.env.production`，runtime仍回讀必要analytics vars。
- ✅ 原版／v3在desktop與mobile皆完成首屏及navigation實際操作；兩者均保持原路徑。
  Nested frontend commits為`01913b6..c8832bf`，Next production build 88 routes成功。
- ✅ Issue #8 acceptance與五步Gate全過，狀態
  **`root_cause_fixed_and_verified`**。文章view-count舊資料面之後由既有
  legacy-retirement tickets收斂，不混入本ticket結案口徑。

## 2026-07-27 — T40 CI remediation execution-contract slice（Issue #46）

- ✅ 郵件所述 main CI red 屬本專案真實 run `30258321227`；committed-version
  minimal probe穩定重現`shared_state_lock` ImportError，不是單純陳舊告警。
- ✅ 直接修復已由唯一互動session接管，exact-path commit `c0a62a612`；
  committed probe與`tests/test_covered_article_dedup.py` 8案全綠，canonical task
  `ci-root-30256296797`已正式claim/start/complete並帶真repair SHA。
- ✅ 結構死鎖根因不是fire未啟動，而是watcher建出的mutating task缺producer
  isolation contract。現在完整failed log會產生bounded literal repo paths與
  repo-patch contract；真run回放精確取3路徑，absolute/traversal/storage/glob
  fail closed；paths與failure run key持久化避免restart失憶，CI
  watcher／preassignment 74案綠。
- ✅ GitHub Test Suite run `30260596460`已在包含`c0a62a612`與結構修正的
  `dec3708bb`全綠，直接ImportError與CI修復派工contract兩個slice均為
  `root_cause_fixed_and_verified`。
- 🟡 整體Issue #46仍缺其餘legacy physical retirement及14日sustained-clean，
  umbrella維持`contained`。

## 2026-07-27 — T40 duplicate-effect retirement evidence producer（Issue #46）

- ✅ 在formal PostgreSQL Effect Delivery receipt的不可避settlement邊界增加獨立
  duplicate-delivery tripwire；同一EffectRequest出現第二筆`delivered`時，原交易必須
  同步寫入private retirement ledger，寫不成即整筆settlement rollback。
- ✅ Matt review抓出兩個初版阻斷缺陷：PostgreSQL `IDENTITY`在rollback後會留下永久
  sequence gap；並行delivery若沒有per-effect serialization可能互相看不到。現以
  transactionally updated durable head密集配號、advisory xact lock序列化同effect；
  rollback、並行與attempt編號逆序皆有PG17回歸。
- ✅ event/head表均為FORCE RLS且owner=`volpred_ops_definer`；RPC固定空
  `search_path`並只授權`service_role`。RPC回傳exact cursor→high-watermark範圍，
  materializer拒絕gap、schema/cursor drift、越界時間與不連續sequence。
- ✅ Production migration receipt=`20260727112014`；catalog回讀trigger enabled、
  anon/authenticated execute=false、service_role execute=true、event/head
  `0/0`。直接production materializer生成mode-600
  `duplicate_effect.json`，`count=0/high_watermark=0`。
- ✅ 既有Operations Core `*/5` wrapper已改為依序刷新legacy-business-fire與
  duplicate-effect，任一來源失敗整個job非零。19:25自然fire
  `operations-core-v1:legacy_retirement_signal_materialize:a08baf4868d03695348302f5`
  attempt 1／exit 0，兩個typed signal均由正式owner刷新；duplicate signal為mode 600、
  `count=0/high_watermark=0`。observation recorder仍未排程，不提前啟動14日窗。

## 2026-07-27 — T40 四類 retirement evidence producer live（Issue #46）

- ✅ orphan-work commit `b30b3bd8a`與silent-loss commit `f99249718`補齊後，
  legacy business fire、duplicate effect、orphan work、silent loss四個typed signal
  均由同一Operations Core `*/5` fail-fast wrapper刷新；recorder仍未排程。
- ✅ silent-loss以version-exact lifecycle與bidirectional terminal receipt
  cardinality／outcome reconciliation辨識遺失；durable event delta與active violations
  聯集，避免短暫違規漏記與persistent violation在cursor前進後假乾淨。
- ✅ Production catalog回讀確認兩張新table為private FORCE RLS、`service_role`
  無直接讀權；VOLATILE `SECURITY DEFINER` reconcile RPC固定空`search_path`且只授權
  `service_role`。ledger回讀event=0／high=0／head_rows=1，advisor 0 matching finding。
- ✅ 19:50自然fire
  `operations-core-v1:legacy_retirement_signal_materialize:a18842f93993dcde184ae363`
  attempt 1／exit 0並落出四個signal；silent-loss為`count=0/high_watermark=0`。
  Post-commit相鄰回歸110 passed，Matt Spec／Standards雙審PASS、0 P1/P2。
- 🟡 四個producer完成不等於Issue #46結案。其目前仍OPEN的direct blocking edges為
  #9、#13、#21、#24、#28、#44、#45；全部通過前不啟動14日gap-free recorder。
  physical legacy retirement亦未完成，umbrella維持`contained`。

## 2026-07-27 — T40 orphan-work durable evidence hardening（Issue #46）

- ✅ orphan裁決在finalize前先寫hash-chain event；寫入失敗即fail closed，重啟依同一
  workspace identity冪等，不會「workspace已移除但證據未落地」。
- ✅ event append改成durable pending intent → fsynced temp inode → no-clobber
  hard-link → durable head；event或head中途crash均可恢復，legacy-business-fire與
  orphan-work兩個本機ledger都有partial-temp／event-head gap回歸。
- ✅ branch讀取失敗先記`unresolved`再中止；下一輪只允許單調解析成一個actual
  branch。loader會獨立驗證每個workspace最多兩筆、第一筆必為unresolved、第二筆
  必為actual且job相同；重新計算hash與head的偽造chain仍被拒絕。resolution只推進
  watermark，不重複計為事故。
- ✅ on-disk schema與key set維持`orphan-work-retirement-event.v1`，舊版reader
  回滾仍能讀完整證據；不採用會造成既有ledger永久拒讀的一次性v2切換。
- ✅ commits `d72311c86`,`3959bdfe6`,`b586aa48c`；event tests **24 passed**、
  workspace相鄰tests **11 passed**、ruff／compileall／diff-check全綠，Matt Spec與
  Standards最終雙PASS。
- ✅ 20:10 Operations Core自然fire
  `operations-core-v1:legacy_retirement_signal_materialize:1302e10729ea1f2566623753`
  attempt 1／exit 0；orphan signal mode 600、`count=0/high_watermark=0`，pending
  intent不存在，installed wrapper SHA與manifest均為`c9a9c6d9…9037ac`。
  planned reload工具曾因launchd minimum-runtime throttle在30秒內拿不到PID而exit 1；
  live read-back確認服務於20:06:56重生，現為running且health loop／trigger socket已啟動。
- 🟡 此producer slice為`root_cause_fixed_and_verified`；Issue #46 umbrella仍須等
  direct blocking edges、14日sustained-clean與physical retirement，維持`contained`。

## 2026-07-27 — T40 formal Primary Authority owner attestation（Issue #46）

- ✅ Formal census不再把`host_authority/operations-core-primary`永久寫死為
  `unresolved`。Inventory綁定`volpred_read_primary_authority_owner`，Supabase
  adapter只接受schema v1、canonical capability/key、`operations_core`、
  generation 1、exact contract ref與exact key set；inventory pin production
  backend SHA-256，census沿用DB `attested_at`，以owner read完成後的clock驗
  stale/future evidence，不拿audit起始時間誤判較晚產生的合法DB timestamp。
  RPC失敗或任一identity／時間欄漂移都不產生claim。
- ✅ PostgreSQL用一筆immutable owner singleton作live source；table為FORCE RLS且
  owner=`volpred_ops_definer`，service role沒有SELECT或mutation權，只能執行
  `SECURITY DEFINER` read RPC；anon/authenticated無execute。migration與non-superuser
  role cleanup均有真PG17回歸。
- ✅ commits `db804d760`,`5deb97fa7`,`df1e9c2c5`,`01a9a8512`；Primary Authority／
  formal-census範圍 **62 passed**。Production migration已部署，回讀owner=`operations_core`、
  authority key=`operations-core-primary`、generation=`1`、row count=`1`，
  RLS／ACL／function owner全符。
- ✅ Fresh production census的host-authority row為`unique_owner`、probe errors=0，
  blockers由6降為5；這個slice通過五步Gate，狀態為
  **`root_cause_fixed_and_verified`**。
- 🟡 Issue #46仍保留work、commit、publisher delete、incident與provider五個
  blocker；#9等gate未成熟前不轉owner、不啟動14日recorder、不做physical
  retirement，umbrella維持`contained`。

## 2026-07-27 — T40 formal Work Coordinator owner attestation（Issue #46）

- ✅ Formal census的`work.coordinate`不再永久寫死`unresolved`。Inventory綁定
  production backend SHA與service-role-only `volpred_read_work_owner`；adapter以
  exact key set驗owner singleton、同generation immutable receipt，以及對應
  consumed／rolled-back cutover gate與完整時間順序。不存在、額外欄位、空白漂移、
  receipt/gate不一致或未來時間全部fail closed，不會偽造owner claim。
- ✅ Supabase migration history保持append-only：原始
  `20260727123500_work_owner_attestation.sql` bytes原樣保留，hardening另以
  `20260727124801_work_owner_attestation.sql`前進。Production receipts為
  `20260727125501 work_owner_attestation`與
  `20260727125509 harden_work_owner_attestation`。
- ✅ Production catalog回讀：function owner=`volpred_ops_definer`、
  `SECURITY DEFINER`、STABLE、空`search_path`；ACL只有definer與service role，
  anon/authenticated不可執行；`work_owners`為FORCE RLS且service role無SELECT。
  Security advisor沒有此RPC的新finding。
- ✅ commits `64e10c933`,`0bcdcc8dd`,`e27ae2cd4`；相鄰範圍
  **126 passed**、ruff／compileall／diff-check全綠，Matt Spec／Standards最終雙PASS。
  Fresh production census回讀`legacy`／generation 1／receipt 1，
  `work.coordinate=wrong_owner`且`probe_errors=[]`。可觀測性slice通過五步Gate，
  狀態為 **`root_cause_fixed_and_verified`**。
- 🟡 此slice不轉移ownership。Issue #9七日clean gate成熟前，`legacy`是誠實現況；
  因此Issue #46與operations-core umbrella仍為`contained`。

## 2026-07-27 — T03 clean-soak evidence 與自動 re-arm（Issue #9）

- ✅ `work-shadow-assessment.v1`以additive fields公開最後一次breach後的clean
  receipt數、observed／recorded起訖、連續秒數與`next_eligible_at`。Live回讀
  clean起點=`2026-07-27T12:40:16.244030Z`、count=1、window=0秒、next eligible=
  `2026-08-03T12:40:16.244030Z`。
- ✅ Allowlisted `work_shadow_cutover_ready_v1`在舊not-before到期但七日仍不足時，
  只可於canonical queue `LOCK_EX`交易內把`blocked_until`單調向後re-arm並寫
  `blocked→blocked` history；未知gate、不可讀assessment與owner mismatch保持blocked，
  observer不取得mutation authority。
- ✅ Final hardening拒絕對stale suffix、future receipt或錯誤owner mode提供假
  `next_eligible_at`。Commits=`de75c25c5`,`0a0dc7b64`；相鄰範圍
  **225 passed**、Matt Spec／Standards雙PASS。
- 🟡 `ready_for_cutover=false`；真正七日尚未經過，未stage、未transfer owner。
  本人工校時根因為 **`root_cause_fixed_and_verified`**，Issue #9維持`contained`。

## 2026-07-27 — T40 formal Incident Lifecycle owner attestation（Issue #46）

- ✅ `incident.lifecycle`不再由formal census硬編碼為`unresolved`。Production
  backend-pinned `volpred_read_incident_owner`回讀私有owner singleton及逐欄相同的
  immutable receipt；adapter拒絕schema、identity、contract、chronology、stale／future
  或extra-field drift，probe失敗時保持`unknown_owner`。
- ✅ Canonical chain
  `20260727130815→20260727132000→20260727132229`可乾淨重播。
  Matt雙審發現並行`131500`可能補造receipt後，convergence commit `714bb25f6`
  將它自canonical鏈移除、remote標reverted；`132229`安裝前要求exact一筆owner與
  matching receipt，RPC亦拒絕任何額外receipt。Production ledger另含並行重複套用
  `131925`與`132700`；最後兩個finalizer receipt把曾被弱版`132000`覆蓋的RPC重新
  收斂。Live function definition含`NOT EXISTS`，owner／receipt各一筆。Catalog回讀
  `SECURITY DEFINER`／STABLE／空`search_path`、owner=`volpred_ops_definer`；
  service role只能execute RPC，anon/authenticated不可執行，兩張私表皆FORCE RLS。
  四個normalized-nonempty CHECK與capability FK亦5/5存在且已validate。
- ✅ Adapter／census與相鄰owner範圍 **122 passed**；真PG另證明owner漂移後
  重播canonical bootstrap必raise、receipt count不增加。ruff／compileall綠。Fresh production
  census為`legacy/generation 1/wrong_owner`且
  `probe_errors=[]`。此可觀測性slice為
  **`root_cause_fixed_and_verified`**。
- ✅ Commits=`0d95e67b8`,`e9f411582`,`714bb25f6`,`49fb8a7ae`；Matt
  Spec／Standards最終雙PASS。
- 🟡 本slice刻意沒有transfer或incident mutation RPC；#9七日gate與#13整體
  acceptance未完成前不切owner。#13與#46 umbrella維持`contained`。

## 2026-07-27 — T40 formal Provider Execution owner attestation（Issue #46）

- ✅ `provider.execution`不再由formal census硬編碼為`unresolved`。Production
  backend-pinned `volpred_read_provider_owner`回讀私有owner singleton及逐欄相同的
  immutable receipt；adapter拒絕schema、identity、contract、chronology、
  stale／future與extra-field drift，probe失敗時仍保持`unknown_owner`。
- ✅ Canonical migration `20260727133500`可重播，且只在owner不存在時同交易建立
  `legacy/generation 1`與bootstrap receipt。Owner漂移、缺receipt或額外receipt都
  會使migration／RPC fail closed，不會從既存漂移狀態補造「合法」receipt。
- ✅ Production ledger已回讀local=remote。RPC為STABLE、SECURITY DEFINER、空
  `search_path`、owner=`volpred_ops_definer`；只有service role可execute，
  anon/authenticated不可執行。`provider_owners`與`provider_owner_receipts`皆
  FORCE RLS，service role無table SELECT；live owner／receipt各恰一筆。
- ✅ Commits=`52157406e`,`23a5ea5bf`；incident/provider共用typed attestation
  parser，backend-bound resolver metadata收斂到單一registry，並修正replay測試
  autocommit污染共享fixture。相鄰範圍 **117 passed**，
  完整PostgreSQL effect contract **62 passed**，ruff／diff-check全綠，Matt
  Spec／Standards最終雙PASS。Fresh
  production census為`legacy/generation 1/wrong_owner`且`probe_errors=[]`。
  此可觀測性slice為 **`root_cause_fixed_and_verified`**。
- 🟡 本slice沒有owner transfer、provider execution、#9 bypass、14日recorder或
  physical retirement。#9七日gate與#12 acceptance完成前不切owner；#12與#46
  umbrella維持`contained`。

## 2026-07-27 — T10 canonical zero-paid registry 接上三條 live launcher（Issue #12）

- ✅ `config/provider_registry.json`成為versioned exact-schema registry；provider
  identity、實際model、subscription auth surface、billing、semantic classes、
  capabilities、attestations、formal eligibility、enabled、health與bounded probe policy
  均有明確schema。未知欄位、metered、credits、paid overflow、API key與auto-reload
  直接拒絕。
- ✅ Supervisor Claude、compute-agent Claude、Codex failover改由三個canonical launch
  contract派生不可降級需求；startup與每次subprocess前都重讀policy。Receipt綁
  executable realpath+SHA、pinned settings SHA、registry SHA與final child env；
  Claude排除user/local/project drift及`apiKeyHelper`，Codex固定
  `gpt-5.6-sol --ignore-user-config`。
- ✅ Commits=`7e46f10e8`,`dc902d4be`；targeted **119 passed**、
  compileall／ruff／diff-check綠，live no-spawn三份receipt同SHA且alternate-auth
  injection全部fail closed；Matt Spec／Standards最終雙PASS。
- ✅ 本三條production launcher接管slice通過五步Gate，狀態為
  **`root_cause_fixed_and_verified`**。
- 🟡 其他utility／legacy AI CLI seam由follow-up `assign_5938ee83`納管；本slice未
  transfer owner、未繞過#9、未close #12。Issue #12與operations-core umbrella仍為
  **`contained`**。

## 2026-07-27 — T10 全 production AI CLI source-census 與旁路封閉（Issue #12）

- ✅ Production Python source已成為AST ratchet：已知清單與自動發現必須完全相等；
  新增Claude／Codex／agy business spawn若未在Popen前呼叫canonical provider policy，
  CI立即失敗。`codex help/--version`只有在argv可證明純metadata時列diagnostic，不能
  替`codex exec`取得豁免。
- ✅ `execution_brief`、member-QA warn-band、trending scan、Codex／agy lazypack及
  prepublish audit均綁定不可由caller降級的semantic/capability/formal=false contract、
  實際model、executable/hash、registry SHA與receipt environment；agy只允許owner既有
  Google OAuth的`gemini-3.6-flash-high`，API key／credits／paid overflow仍fail closed。
- ✅ Shell census另抓到`codex_exec_bounded.sh`與`telegram_responder.sh`兩條live seam。
  前者改用repo `.venv`（live測得舊system Python在policy前即因型別語法crash），固定
  registry-pinned nvm Codex及model；後者用`authorized_provider_exec.py`在同PID
  `execve`前授權Claude，Codex fallback傳專屬contract。Legacy
  `cron_hourly_dispatch.sh`只接受canonical schedule的`status=retired`且
  `host_crontab_managed=false`作非live證據。
- ✅ 相鄰範圍 **167 passed**，另有3組alternate-auth live no-spawn denial、shell
  syntax、compileall／diff-check／critical ruff checks全綠。此launcher旁路根因為
  **`root_cause_fixed_and_verified`**。
- 🟡 本slice沒有transfer `provider.execution` owner、沒有繞過#9；Issue #12／#46
  umbrella仍為 **`contained`**。

## 2026-07-27 — Async agent task ownership 終態 reconciler

- ✅ `task_pool_claim.py cleanup` 不再只處理 `claimed/in_progress` lease；它會回讀
  `awaiting_agent_job` 綁定的 durable compute receipt。`queued/running/claimed/pending`
  保持 external ownership，`completed` 轉成
  `external_compute_receipt_pending_collection`，`failed/cancelled/gone` 才清除 binding
  並 re-pend；已在 receipt collection 的 task 永不因 job file 消失而誤重派。若
  receipt 的 `source_task_id` 不匹配則 fail closed，只回報
  `invalid_compute_bindings`，不猜測 ownership。
- ✅ TDD 先建立 5 個紅燈案例，再完成最小狀態轉移；task-pool／compute-queue／starvation
  相鄰範圍 **171 passed**。
- ✅ Live cleanup 回讀 10 個 external tasks：K1728 的 running owner 保留，3 個
  receipt-pending 保留，6 個 failed owner（K1720/K1721/K1722/K1727 與兩個
  snapdupfix）以正式 CLI re-pend，且每筆留下 `compute_release_reason` 與
  `status_history`。同類「dead compute job 永久冒充 in-flight」根因狀態為
  **`root_cause_fixed_and_verified`**。

## 2026-07-27 — T11 durable bounded capability probe（Issue #16）

- ✅ `provider-registry.v1#probe_policy` 現在由單一 `ProbePolicy` 契約執行：
  minimum interval、exponential backoff、全域 rolling cost budget 與 reservation
  TTL 在 in-memory reference store／durable ledger 使用相同 admission 順序；TTL
  只釋放 ownership，不會縮短 minimum interval。
- ✅ Durable ledger 以 lock + fsync + atomic replace 保存 reservation、typed
  admission/outcome、identity-bound receipt、policy-denial hash chain 與完整檔案
  integrity。Crash reservation 納入 budget；舊 `provider-probe-ledger.v1`
  reservation shape 可直接回讀；逾 TTL 才完成的 provider I/O 仍以 `late+` receipt
  留下不可靜默遺失的證據。
- ✅ 公開 mutation seam 只有 `run()`；callback 前重新授權 registry SHA、
  executable realpath/SHA、model、auth surface 與 cost。Policy denial 在 provider
  I/O 前 fail closed 並 dedup，admission throttle 不冒充 provider failure。
- ✅ Matt Spec／Standards 最終雙 PASS；本 slice 沒有 provider reroute、task resume、
  business effect、owner transfer 或 #9/#12 bypass。Durable probe 底層 slice 為
  **`root_cause_fixed_and_verified`**；Issue #16 umbrella 仍為 **`contained`** 且
  保持 OPEN，等 #9→#12 owner cutover 才進下一階段。

## 2026-07-27 — PHASE-Z orphan-half 高併發 owner 分群

- ✅ Orphan-half 的 8-path safety cap 從全域計數改為 declared ownership cohort：
  `stale:<fire-id>`、排序後的 `contested:<fire-ids>` 與 `unowned` 各自計算。超額
  cohort 只回報在 `skipped_groups`，不再讓其他 owner 的小型、可證明候選一起被放棄。
- ✅ Clone revision pin、HEAD-red→candidate-green 證明、禁止採用 test bytes 與整體
  wall-clock budget 均維持不變；這不是放寬 adoption，只移除跨 owner 的連坐拒絕。
- ✅ TDD 證明 9-path noisy owner 不會壓掉另一 owner 的 missing half；PHASE-Z 相鄰
  **105 passed**。同類高併發 `candidates exceeds cap 8` 造成 recovery 全關閉的根因為
  **`root_cause_fixed_and_verified`**。
- ✅ Production 採 deferred self-reload：先讓既有 worker／舊 PHASE-Z cohort 自然 drain，
  再於 2026-07-28 00:01 台北時間明確回報載入 `phase_z.py`，daemon 從 PID 39318
  換為 PID 85797；新進程 heartbeat 正常、`auth_blocked=false`，全程沒有用 signal
  終止 worker 或回滾 claim。

## 2026-07-29 — T12 Guided Migration live gate hardening（Issue #17）

- ✅ Commits `15fcd6c85`,`0586e114c`建立machine-readable parity manifest、四角色
  獨立Ed25519信任、one-time challenge、source/target immutable Git、exact executable
  SHA、signed permission、secret-reference與formal RPO/RTO contract；所有輸出皆為
  dry-run，且永不授權Primary Lease。
- ✅ Live capture證明`uv run`實際Python位於使用者家目錄；manifest現允許此origin，
  但仍強制合法owner、不可group/world-write、execute bit、single-fd SHA與兩端exact
  parity。安全矩陣涵蓋0775、other owner與SHA mismatch拒絕。
- ✅ Telegram state原writer以預設0644重建檔案，令手動chmod每次都失效。Canonical
  writer已改為0600同目錄temp→file fsync→atomic replace→parent directory fsync；
  live同內容寫回前後SHA一致、mode=0600，四組secret reference preflight全綠。
- ✅ Migration forbidden aliases已包含Anthropic、OpenAI與Google/Gemini各API-key
  名稱；舊bootstrap文件移除所有secret env/session複製指示，target只能由密碼管理器、
  服務後台或subscription OAuth重新授權。
- ✅ 相鄰範圍104 tests、post-commit CI-parity 51 tests、ruff、py_compile與diff-check
  全綠；Matt Spec／Standards最終雙PASS，P1/P2皆0。
- ✅ 已產生只含manifest-declared artifacts、runtime continuity receipt與獨立frontend
  checkout的clean target bundle：21,693,118 bytes，SHA-256
  `89b044640c61c71b8834be872ea77a31d9ccc23e1965a55c9404343c492779b2`；
  declared Git paths與frontend均clean，掃描0個`.env*`／Ed25519私鑰。
- 🟡 Studio live snapshot正確回報仍有`GOOGLE_CLOUD_API_KEY`與`OPENAI_API_KEY`，
  且共享checkout有別項WIP；MacBook Tailscale目前offline，不能取得fresh target
  signature。API-key正式退役須由#12 subscription replacement接管，#12又等待#9
  七日ownership gate；formal-effect RPO=0 pair亦尚未產生。因此#17維持
  **`contained`／OPEN**，不得宣稱完成或promotion eligible。

## 2026-07-29 — T23 Member Continuity／Privacy（Issue #23）

- ✅ 原版／v3共用browser anonymous identity、登入後receipt-backed merge，以及
  收藏／追蹤／提醒／提問／read／delete seam；未送出的提問草稿只留browser，介面明示
  研究內容不是個人化投資建議。
- ✅ Private member／analytics tables全部FORCE RLS；五個public RPC由
  no-login/non-bypass worker持有、`SECURITY DEFINER`、空`search_path`且只給
  service role。PG17 managed owner transfer與重跑契約已機械化。
- ✅ Parent commits=`ff46f9fbe`,`dc43c4b1e`,`c2bbcbf61`；nested frontend=
  `a15bc14`,`b264eb5`。PostgreSQL integration **8 passed**，member gate
  **19 passed**且已納入canonical `npm run check`；frontend full check／89-page
  production build與Matt Spec／Standards雙PASS。
- ✅ Production migration receipts=`20260728190500`,`20260728191149`；
  service-role transaction live E2E完成save/follow/reminder/question/read、
  exact replay、identity merge及雙delete後rollback。
- ✅ Zeabur deployment `6a6913edeac99cc636f25a5d`為RUNNING；原版／v3首頁、
  文章、questions、member頁皆200，continuity GET／POST／DELETE匿名皆401。部署只含
  candidate commit，未收active checkout的package／PDF／question-test WIP。

Issue #23五步Gate全過，狀態為 **`root_cause_fixed_and_verified`**。

## 2026-07-29 — T40 compute-worker clock 漏網修復（Issue #46）

- 🔄 Owner audit 發現 `volpred-compute-worker` 仍只存在舊 `cron_jobs` registry，並由
  `com.volpred.compute-worker` LaunchAgent 每 15 分直接喚醒；因此先前
  `system_crontab` 54/54、legacy owner 0 的結論沒有涵蓋這條正式 executor clock。
- ✅ Reconciler 現對任何非 `retired` 的 `cron_jobs` row fail closed，避免第二個
  schedule registry 再逃出唯一 owner audit。
- ✅ Compute worker cadence／`max_parallel` 已移入 canonical
  `system_crontab[id=volpred-compute-worker]`；runtime resolver不再從 retired row
  讀 active policy。
- ✅ 07:45 natural fire
  `operations-core-v1:volpred-compute-worker:133ccb319bd393968dde017b`
  attempt 1／exit 0；priority-0 smoke同秒完成，receipt內的owner／job／fire key與
  scheduler exact match，validator回讀55/55 Core、legacy 0。
- ✅ Receipt-gated reconcile隨後bootout exact
  `com.volpred.compute-worker`；`launchctl print`回113/not found，targeted owner audit
  `conflicts=[]`、`dormant_legacy_surfaces=[]`。Detached Core executor與其K781
  lazypack child在bootout後仍持續運行，證明退役的是clock而非工作。
- ✅ 交接期間另抓到nested receipt-lock自鎖；底層改為same-thread reentrant且保留
  cross-thread/process排他，144 tests與Matt雙review PASS。此compute clock漏網與
  nested-lock slice為 **`root_cause_fixed_and_verified`**；Issue #46 umbrella仍需
  其他capability與14-day clean，不在本slice冒稱關閉。

## 2026-07-30 — T38 Supervisor Fire Lifecycle 最終結案（Issue #42）

- ✅ 將同一個 committed regression overlay 到精確 pre-fix parent `dad84187e`：
  `test_defers_while_durable_closeout_is_pending` 實際 RED，舊碼在仍有 durable
  `phase_z_pending` generation 時錯回 `reload`；目前 HEAD 同一 test GREEN。
- ✅ restart／generation／closeout／self-reload 聚焦範圍 **92 passed**；覆蓋
  pre-fire、worker running、worker complete、closeout failure、terminal commit後
  recovery，以及無 matching generation 時拒絕 closeout。
- ✅ Production generation receipt
  `371e54f705a729ea9b8421960acfb7e2d88e5bbf7a0a870e3dfdf5e33ed20239`
  對應 commit `5e63b6b57f9c5f2e1ad3dbc426509d8a089999fe`；`phase_z_pending=[]`，
  downstream commit可回讀。
- ✅ `inc_537a3ff3304f`由 detector 依 `clean_streak_k3_24h` 自動 resolved，
  非人工改狀態；planned reload後沒有新 baseline-missing episode。
- ✅ Matt Standards review PASS；Matt Spec review原本只缺歷史 RED receipt，
  補上可重播 pre-fix RED→HEAD GREEN 後六項 acceptance 均有證據。
- ℹ️ 00:14 immutable release 因 monitored notification source 尚未 commit 而拒絕，
  是正確 fail-closed：沒有載入 mutable bytes、沒有中止 worker、fresh generation
  仍成功建立；兩檔已於 `96018b340`／`13061f9dc`正式落地。
- 🔁 原結案後的 production regression 重新開啟本 issue：request `749b49b3…`
  durable 後，舊 scheduler 仍於 01:17 與 01:49 各 admission 一班，證明
  health-loop-only drain 沒有封住 scheduler TOCTOU。`983a8eaf5`新增共用 reload-root
  admission lock、active-intent fail-closed 與 fire-demand CAS；相鄰最終
  **336 passed、1 skipped**，Matt Spec／Standards雙 PASS。
- ✅ 兩班舊 worker 都自然 `exit=0`，沒有 signal kill；token-owned quiesce 阻止第三班。
  immutable release `451f9bf61cc0…` 於 02:04:40 fresh boot，包含
  `983a8eaf5` 與通知路由 `9a15cede8`，planned-restart 通知正確抑制。
- ✅ 控制性 request `9b5db49d2642…` 存在時，真實 Operations Core socket tick回傳
  `skip/deferred_reload_pending`，`current_jobs=0`、`last_fire_at`不變；其後
  completion receipt回讀相同 release SHA／新 generation，最終
  `auth_blocked=false`、quiesce已解除。這項 regression 的五步 Gate 已重新通過。

Issue #42狀態為 **`root_cause_fixed_and_verified`**。這只結案 T38；不代表
Operations Core 全域替換完成，#9七日 queue gate、五個 formal legacy owner與#46
十四日 sustained-clean 仍各自 fail closed。

## 2026-07-30 — T36 runtime audit Git ownership bounded closure（Issue #41）

- ✅ 定位 PHASE-Z 多筆 stuck-files incident 的共同殘留：
  `storage/logs/trending_primary_source_verification.jsonl` 是 daemon append-only audit，
  卻仍被 Git 追蹤。
- ✅ 以 canonical `git_writer_lock untrack-preserve` exact-HEAD transaction 移出
  Git index，加入 committed ignore policy；live 檔 SHA-256／1443 bytes／mode 0644
  前後完全一致，沒有刪資料或手改 runtime content。
- ✅ 新 repository gate 同時驗證 ignore policy 與非 tracked ownership；相關
  **79 tests passed**。
- ✅ Production `foreign_incident --reconcile` 自動關閉本單與另 13 筆同源 incident；
  dispatcher cap 從 2 回復 baseline 4，P1=0、free slots=4。
- ✅ Matt Standards／Spec review 均 PASS。
- 🟡 此 bounded slice 為 **`root_cause_fixed_and_verified`**；Issue #41 umbrella 仍
  被 #9 與完整 writer inventory／single interface／crash injection／recognizer
  retirement 阻塞，維持 OPEN／`contained`。

## 2026-07-30 — Compute queue UTF-8 argv boundary

- ✅ `assign_8b0b2c61` 已完成；commit `f3c504abd`。
- ✅ 正式 `compute_queue main → enqueue-agent → durable receipt` seam 由 RED
  `UnicodeEncodeError` 轉 GREEN，空 locale process 回讀中文 title `中文派工`。
- ✅ 修正在完整 argparse namespace 的單一 process boundary，不要求 caller 改 ASCII，
  並涵蓋序列 argv。
- ✅ Affected suites **104 passed**；Ruff F/E9、py_compile、diff check、Matt
  Standards／Spec 均 PASS。
- ⚠️ 完整 suite **6568 passed、3 skipped、20 failed**；紅燈全部在未修改的
  dispatch-supervisor／agent-auth 範圍，分別由 live producer coalition 與本機
  `OPENAI_API_KEY` 污染觸發，未以本 slice 掩蓋。

此 Unicode root class 為 **`root_cause_fixed_and_verified`**；相鄰環境隔離紅燈仍未結案。

## 2026-07-30 — T37 PHASE-Z 首班 derate contract bounded closure（Issue #44）

- ✅ production 同一張 `assign_cf82928c` 曾同時出現 assessor
  `derates=false`／blocker 0 與 actuator cap 2；queue 證據為首次 row 缺
  `payload.derates`，不是 grace 或 WIP ownership 判錯。
- ✅ deterministic RED 在正式 `first PHASE-Z fire → durable queue → slot budget`
  seam 命中 `KeyError: derates`；修正後首班即持久化 `false`。
- ✅ upsert 後立即走 canonical reconciler；budget 仍唯讀、缺判定仍 fail-safe，
  沒有複製 24h grace 邏輯、沒有關閉 incident、沒有收走任何 session WIP。
- ✅ 兩組 cap tests 已隔離 developer-only occupancy，CI-parity 不再讀
  `.claude/worktrees`／live agent receipt。
- ✅ affected suites **101 passed**；Ruff、py_compile、diff check 與 Matt
  Standards／Spec review均 PASS。
- ✅ production reconcile 回讀五張 open incident 全部 derate lifted；
  `assign_cf82928c` 保持 pending、31/31 deferred，slot cap 2 → baseline 4、
  free slots 2。

此 bounded slice 為 **`root_cause_fixed_and_verified`**；Issue #44 umbrella 的完整
Producer Isolation／PHASE-Z recognizer retirement仍未全部驗收，維持 OPEN／`contained`。

## 2026-07-30 — T13 GitHub 留言通知 batching bounded slice（Issue #13）

- ✅ production audit 定位逐 comment 雙通道 burst：同一 Issue 85 分鐘內
  4 Email＋4 Telegram；ingress 每五分鐘本身不是問題，缺少聚合與 channel ownership
  才是根因。
- ✅ schema v3 先 durable stage 完整 comment、再推進 per-source cursor；每個 Issue／PR
  使用固定 15 分鐘窗，新留言不延長既有窗，逾期留言進下一窗。
- ✅ incremental 改為 Email-only 摘要；Telegram 保留給互動／progress owner。Email
  外送保持 in-flight／unknown 防重送與 failed retry。
- ✅ v2 delivered、pending、failed、in-flight、delivery_unknown 均有 migration；
  exact comment identity、receipt 與 cursor 不遺失。
- ✅ canonical `runtime_schedules.json` 已同步 channel／cadence contract；affected
  suites **25 passed**，Ruff、py_compile、schedule parse、diff check均通過。
- ✅ production schema v3 已由自然 Core fire 接管；Issue #13 固定窗到期後只留下
  一筆 Email durable receipt，沒有 Telegram receipt，cursor／batch terminal
  read-back一致。
- ⏳ GitHub dual-channel burst bounded root class 為
  **`root_cause_fixed_and_verified`**；仍待 24 小時頻率／資訊性 sustained audit，
  因此 Issue #13 umbrella 保持 OPEN，尚未宣稱整體通知政策完成。

## 2026-07-30 — T37 handoff slot observer ownership bounded closure（Issue #44）

- ✅ 定位 `13/4` 為 observer 誤報：handoff 自行數所有 worktree directories，
  繞過 canonical progress TTL 與 dynamic cap。
- ✅ handoff 現直接投影 `dispatch_slot_budget` 的 cap 2／4／6、live occupancy、
  agent metadata snapshot 與 stale count；stale artifact 可見但不占 slot。
- ✅ agent receipt invalid JSON schema／status type／UTF-8 只會 warning＋skip；
  metadata 不再二次讀檔，移除 TOCTOU。
- ✅ affected suites **85 passed**；Ruff E9/F/I、py_compile、diff check與 Matt
  Standards／Spec review PASS。
- ✅ live build 由 `13/4` 修正為 `3/4`，另列 11 個 stale artifacts 不占 slot。

此 observer root class 為 **`root_cause_fixed_and_verified`**；Issue #44 umbrella
仍須 Producer Isolation／PHASE-Z recognizer retirement acceptance，維持 OPEN。

## 2026-07-30 — Operations Core RPC test-egress containment

- ✅ CI run `30473391569` 的表面 monkeypatch 問題已由既有 `3c14e0a57` 修正；本輪續追
  到 owned-email 與共用 Operations Core PostgREST transport 都繞過
  `VOLPRED_NO_REMOTE_READ` 的第二層根因。
- ✅ 兩條 transport 現在於 read-only RPC 的任何 network I/O 前 fail loud；共用 client
  同時用已知 inventory 與 `volpred_read_*`／`read_volpred_*` 命名 ratchet，補上
  primary-authority events 漏列並防止同類新增讀取再靜默旁路。mutation 仍由獨立
  write guard 控制，不把 read/write 兩種權限混成一個開關。
- ✅ 共用 client 的 fake RPC 測試必須顯式 opt in
  `mocked_operations_core_rpc_transport`；owned-email 專用測試則在安裝 fake 後顯式
  移除 read guard。缺 stub 不再能靠本機 `.env.local` 或 production 資料變綠。
- ✅ deterministic RED→GREEN、相鄰 **308 passed**；四 guard live probe 回讀兩條
  transport 均在 transport 前被拒絕。
- ⏳ 狀態 **`contained`**：待新 commit 由正式 push/CI 路徑落地，並以新的 GitHub
  Test Suite 全綠 receipt 回讀後才升級為
  **`root_cause_fixed_and_verified`**。

## 2026-07-30 — K-COVERAGE legacy metadata-gap containment

- ✅ K1716 live 重播由錯誤 `clean` 修正為 `warn_coverage_metadata_gap`，並將真正同題
  舊文 `mile_74d12ac6` 排為第一個 review evidence。
- ✅ 沒有手改 1,907 篇 feed 或把 fuzzy evidence 變 hard block；fallback 只看同
  audience、live、且完全無可抽取 K-id 的舊文，維持 fail-open。
- ✅ warning verdict、candidate list 與 dedup audit 已制度化；缺 metadata 不再與
  「已完整檢查、確定沒有覆蓋」共用 `clean`。
- ✅ deterministic RED→GREEN；K-coverage 13 tests、dedup／generator 相鄰範圍合計
  **182 passed**。
- ⏳ 狀態 **`contained`**：待正式 commit／push 與 GitHub CI read-back 後升級。

## 2026-07-30 — dispatch retry 終態 observer containment

- ✅ live evidence 證明 `9189c746…` 是同一 job 的 attempt 1 failure、attempt 2
  success；supervisor heartbeat 與後續工作均健康。
- ✅ loop-health 不再把 attempt receipts 當成多個最終 job：相同 `job_id` 先依
  append order 收斂，仍在 `current_jobs`／`current_job` 的 retry 不提前視為終態。
- ✅ retry 最終成功不列 failure；retry 最終仍失敗只計一次；無 `job_id` 的舊 receipt
  維持相容。
- ✅ deterministic RED→GREEN；loop-health **27 passed**，live read-back 已移除
  `dispatch_supervisor:failure:exit1`，且未吞掉其他獨立 recurrence。
- ✅ Matt Standards／Spec 雙軸複審 PASS。
- ⏳ 狀態 **`contained`**：待正式 commit／push 與 GitHub CI read-back 後升級。

## 2026-07-30 — GitHub CI system dependency timeout containment

- ✅ run `30490697153` 的取消點已精確定位：Azure mirror 下載 61.2MB
  `fonts-noto-cjk` 卡 17m29s，pytest 尚未開始；不是 code/test failure。
- ✅ workflow 不再 raw apt 無界等待；index 30s、install 120s、各兩次，apt
  connect/read/lock 20s，整個 process group 到期 TERM→KILL；不信任已退出的
  `sudo` leader，SIGKILL 後也沒有無界 wait；group 未消失便立即 fail closed，
  不再啟動重疊 apt。
- ✅ bounded supervisor 由 workflow 以 root 啟動，apt/dpkg 不另包 sudo；kill
  authority 與 descendants 同權限，非 root 誤用 fail loud。
- ✅ 保留真實 ripgrep／Noto CJK 與 apt partial cache；不以 skip 或假 font 取巧。
- ✅ TERM/KILL grace 全納入後 worst-case dependency budget 346s，job budget
  30m；contract 與相鄰 workflow suites **22 passed**，Ruff／py_compile／diff
  check 全綠。
- ✅ Matt Standards／Spec 最終雙軸複審 PASS。
- ⏳ 狀態 **`contained`**：待正式 push 與 fresh GitHub Test Suite 完整跑到 pytest
  後升級。
