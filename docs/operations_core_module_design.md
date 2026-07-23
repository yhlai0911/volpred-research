# Operations Core Module Design

- **Status**：ACCEPTED DESIGN — 尚未切換任何 live owner
- **Date**：2026-07-23
- **Parent decisions**：ADR-0001、ADR-0002、`docs/platform_optimization_program_2026_07.md`
- **Design vocabulary**：module、interface、implementation、depth、seam、adapter、leverage、locality

## 1. 設計結論

不建立一個包住舊函式的 `OperationsCore` facade。那會保留三套生命週期與所有 caller knowledge，只多一層 shallow module。

Phase 1 建立六個各自有小 interface 的 deep modules：

1. **Work Coordinator**：durable WorkItem、claim、checkpoint、狀態機與 receipt。
2. **Change Delivery**：ChangeSet 驗證與唯一 commit 落地。
3. **Effect Delivery**：EffectRequest、transactional outbox、idempotency 與下游 read-back。
4. **Provider Execution**：能力匹配、零付費政策、執行、搶占與 checkpoint resume。
5. **Schedule Materializer**：把 canonical schedule spec 的到期項轉為 WorkItem。
6. **Primary Authority**：跨主機 lease 與 fencing token。

既有 Incident Lifecycle 是第七個已存在的 module；本期先更換 storage adapter 並接入 WorkItem，不在同一批重寫其政策。

## 2. 現況證據與重複知識

### 2.1 三套工作生命週期

| 現有 implementation | 現行角色 | Caller 必須知道的知識 | 問題 |
|---|---|---|---|
| `storage/next_tasks.json` + `next_tasks.py` + `task_pool_claim.py` | 正式 pending queue | P1–P4、pending／claimed／in_progress、dispatch lane、Codex eligibility、stale cleanup、burst fire | JSON 單機鎖；政策散在 library、CLI 與 supervisor |
| `local_control_plane.py` + `storage/ops/tasks` | TaskRecord／AgentSession／ExecutionReceipt | queued／claimed／running、approval、fallback、session identity、curation | 已標示為 audit/control-plane receipts，卻仍有可 claim queue 與另一套狀態機 |
| `jobs.py` + Supabase `ops_jobs` | Admin／手動 job queue | queued／running、scope local／remote、dedupe、20+ action dispatch | Python 與 Next.js 各自 enqueue／claim／execute；remote Admin 路徑可直接產生效果 |

這三者不是三個 adapter，因為它們各自擁有不同的狀態機與政策。新設計必須把政策移進一個 Work Coordinator implementation；舊路徑只在遷移期作 importer、projection 或 compatibility adapter。

### 2.2 已有可保留的深度

| 現有 module | 判定 | 處置 |
|---|---|---|
| `git_writer_lock.py` | 深；隱藏 Git common-dir lock、fork inheritance、process group 與 canonical checkout 規則 | 保留為 Change Delivery 內部 implementation |
| `scheduled_writer_commit.py` | 有價值但 interface 偏向「scheduled file」 | 保留 ownership／dirty-tree implementation，改由 ChangeSet validator 提供完整輸入 |
| dispatch workspace | 有真正的 worktree／shared checkout 兩種 adapter 情境 | 保留隔離、changed-path 與 merge gate implementation |
| incident lifecycle | 身分、episode、3-Strike、sustained-clean 已集中 | 保留政策；把 JSON store 換成 coordination store adapter |
| schedule parser／liveness helpers | 純計算與讀取可重用 | 移入 Schedule Materializer implementation，不暴露 parser 細節 |
| publisher／sync／notification | 各領域行為有價值 | 作 Effect Delivery 的 effect adapters，不再各自擁有 retry／dedupe lifecycle |

### 2.3 必須停止擴張的路徑

- 不再往 `task_pool_claim.py` 加新狀態或新 side effect。
- 不再往 `local_control_plane.py` 加第四種 task policy。
- 不再往 `jobs.py::_run_action` 加新 action switch。
- Admin 不再新增直接寫 `ops_jobs` 後立即執行 remote action 的路徑。
- dispatch supervisor 不再自行推理 provider 等價性、quota 恢復或 durable completion。

以上是 freeze direction，不是立即刪除；只有新 module 接管並通過 gate 後才移除舊 writer。

## 3. Dependency categories 與 seam

| 依賴 | 類型 | Seam 決策 | 測試 adapter |
|---|---|---|---|
| 狀態轉移、priority、capability match、idempotency key | In-process | 無 port；放在 deep module implementation | 直接經 module interface 測試 |
| Supabase PostgreSQL coordination state | Remote but owned | 定義 coordination-store port | transaction-safe in-memory adapter + Postgres adapter |
| 本機 filesystem／Git repo | Local-substitutable | 不放進 module external interface；以真實暫存 Git repo 測試 | temp directory + real Git |
| Claude／Codex／其他訂閱 CLI | True external | 定義 provider-executor port | scripted fake adapters；production subprocess adapters |
| Supabase REST、Mirror、SMTP、Telegram、Zeabur | True external | 每個 effect family 定義窄 port | fake effect adapter + production adapter |
| `config/runtime_schedules.json` | Local-substitutable | Schedule Materializer 內部 config-source seam | fixture file adapter + repo file adapter |
| 時鐘、ID、hash | In-process internal seam | 可注入但不暴露在 external interface | fixed clock／deterministic ID |
| `next_tasks.json`／legacy TaskRecord／`ops_jobs` | Migration only | importer／projection seam，有到期日 | fixture adapters；不得成為 steady-state writer |

Production 與測試 adapter 同時存在時，port 才成立。只有單一 implementation 的純邏輯，不為了 mock 而建立 hypothetical seam。

## 4. Work Coordinator

### 4.1 Seam

所有工作來源——使用者、Admin、scheduler、incident、email／Telegram、agent discovery——在建立 durable work 時跨越同一 seam。所有 worker 在取得 ownership、保存 checkpoint 或結束工作時也跨越這個 seam。

### 4.2 External interface

```python
class WorkCoordinator:
    def submit(self, request: WorkRequest) -> WorkItemView: ...
    def acquire(self, offer: WorkerOffer) -> WorkLease | None: ...
    def record(self, report: WorkReport) -> WorkItemView: ...
    def inspect(self, query: WorkQuery) -> WorkSnapshot: ...
```

Caller 只需知道：

- `submit` 必須帶 `idempotency_key`、source、kind、priority、capability requirements、risk／approval 與 payload reference；重播回傳同一 WorkItem。
- `acquire` 是 atomic claim；能力不符或沒有 ready work 回傳 `None`，不是例外。
- `record` 接受受控的 report variant：`ApprovalGranted`、`Started`、`Checkpointed`、`Released`、`Blocked`、`Completed`、`Failed`、`Cancelled`。
- Worker mutation 都必須帶仍有效的 WorkLease token 與 expected version；過期 ownership 回傳 `ClaimLost`。`ApprovalGranted` 是唯一非 worker mutation，必須帶 expected version、owner identity 與 approval evidence reference。
- `inspect` 是 read model，不回傳可讓 caller 旁路狀態機的 mutable row。

Implementation 隱藏：

- priority／deadline／parent readiness 排序；
- approval 與 risk gate；
- capability／provider eligibility；
- claim TTL、cooperative preemption 與 stale recovery；
- experiment identity conflict；
- checkpoint hash、artifact references 與 resume pointer；
- event、receipt 與 optimistic version；
- transaction、row lock 與 host fencing。

### 4.3 Canonical state

WorkItem 的最小 canonical 欄位：

- identity：`id`、`idempotency_key`、`source`、`kind`、`parent_id`
- intent：`title`、`payload_ref`、`priority`、`deadline`
- policy：`required_capabilities`、`required_attestations`、`risk`、`approval`
- lifecycle：`status`、`version`、`claimed_by`、`claim_token`、`claim_expires_at`
- recovery：`latest_verified_checkpoint_id`、`blocked_reason`
- audit：created／updated／terminal timestamps、requester identity

Canonical statuses：

```text
awaiting_approval -> pending -> claimed -> running -> succeeded
                              \-> pending     \-> failed
                               \-> cancelled  \-> blocked -> pending
running --checkpoint + cooperative release--> pending
```

每次 transition 與 checkpoint 都 append event／receipt。`blocked` 必須有 typed reason；provider quota 恢復只解除相符 blocker。

### 4.4 Deletion test

如果刪掉 Work Coordinator，idempotency、狀態轉移、能力比對、claim race、checkpoint、approval、parent readiness、stale recovery 與 receipts 會重新散回 task CLI、Admin route、scheduler、incident、provider worker 與 migration scripts，因此這個 module 有足夠 depth。

## 5. Change Delivery

### 5.1 Seam

Agent 完成 repo 修改後提交 ChangeSet；只有 commit worker 能要求落地。Agent 不接觸 Git index／ref，也不把整個 dirty tree 當成果。

### 5.2 External interface

```python
class ChangeDelivery:
    def propose(self, proposal: ChangeSetProposal) -> ChangeSetView: ...
    def land(self, command: LandChangeSet) -> DeliveryReceipt: ...
    def inspect(self, change_set_id: str) -> ChangeSetView: ...
```

`ChangeSetProposal` 必須包含 WorkItem、base commit、隔離 workspace、exact paths、content hashes、required checks 與作者執行證據。`land` 只接受 commit-worker identity、有效 WorkLease 與 Primary Authority fencing token。

Implementation 隱藏現有 Git writer lock、dirty ownership、worktree merge、path scope、test execution、HEAD compare-and-set、commit message、rollback point 與 receipt。成功定義為 commit object／HEAD read-back 與 exact-path diff 相符；process exit 0 不足以完成。

### 2026-07-23 ChangeSet proposal checkpoint

- 已建立 shadow `volpred.ops.delivery` 的 `propose`／`inspect` external interface；它不接
  live Git writer、不 staging、不 commit，也不改 ref。
- `propose` 從 linked worktree read-back 驗證 HEAD／base identity、index 為空、完整
  dirty-path set 與 caller 的 exact paths 相等、每個 regular file 的 SHA-256 相符，
  並拒絕 canonical checkout、symlink、path escape、rename／copy／delete。
- WorkItem id／version、作者 execution evidence、全部 required checks 與 normalized
  proposal payload 綁入 SHA-256；同一 idempotency key 的等價 replay 回傳同一
  ChangeSet，不同 payload fail closed。
- 這只完成 program commit 08 的 proposal policy／path-scope 垂直切片。Postgres
  persistence、WorkLease read-back、Primary Authority fencing、commit actuator、
  DeliveryReceipt 與 live caller 均未完成，因此不構成 Change Delivery ownership
  cutover。

### 2026-07-24 Git commit actuator checkpoint

- 已完成 program commit 09 的 private `GitCommitActuator` adapter：它只把已授權且已
  materialize 到 canonical checkout 的 exact-path request 轉交既有
  `git_writer_lock.py commit` transaction，不另外實作第二套 index／ref writer。
- 現行 writer 新增可選的 staged-blob SHA-256 fence；hash scope 必須與 exact paths
  完全相等，且在 writer lease 內、commit 前驗證 index blob。hash／HEAD 任一漂移都在
  不產生 commit 的情況下 fail closed，並把本次觸碰的 index path reset 回原狀。
- adapter 只把 process exit 0 視為候選成功；其後回讀 commit object，驗證 direct
  parent、exact-path diff 與每個 committed blob hash，再產生 immutable
  `commit-actuation.v1` receipt。既有 unrelated index／working-tree 狀態維持不變。
- program commit 09 本身仍是 shadow implementation：當時尚未接到
  `ChangeDelivery.land`、WorkLease／Primary Authority fencing、持久化 receipt 或 live
  caller，因此不取得正式 commit ownership；actuator-side fencing 的後續狀態見下一節。

### 2026-07-24 Commit authority fencing checkpoint

- program commit 10 的 actuator-side interface contract 已完成：每個
  `CommitActuation` 都必須帶 WorkItem id／version、目前 WorkLease token、Primary
  Authority fencing token 與 `commit-worker:` 身分；缺少任一欄位都在 Git writer 前
  fail closed。
- private actuator 會把 proposal、WorkItem、兩個 token、repository、HEAD、exact
  paths／content hashes、message 與 actor 做 canonical JSON SHA-256，交由注入的
  `CommitAuthority.authorize()` 同時回讀兩個 canonical fence。grant 必須精確回應同一
  request hash；stale token、authority unavailable、malformed／mismatched grant 均不會
  啟動 writer transaction。
- raw tokens 不會傳入 Git writer argv 或寫入成功 receipt；receipt 只保存
  authority-request hash、WorkLease reference 與 Primary Authority reference，並仍須
  通過 commit object／parent／exact paths／blob hashes read-back 才成立。
- 這完成的是 program commit 10 的 stale-token rejection seam，不是 live authority
  service。Postgres Primary Authority adapter、durable DeliveryReceipt、
  `ChangeDelivery.land`、network-partition failure injection 與正式 caller 仍未完成；
  step 34 的 acquire／renew／demote workflow 前不得宣稱取得 commit ownership。

## 6. Effect Delivery

### 6.1 Seam

任何 Email、Telegram、文章同步、Mirror、Supabase projection、部署或其他外部寫入，都先跨越 Effect Delivery seam；domain caller 不自行 retry 或判定成功。

### 6.2 External interface

```python
class EffectDelivery:
    def request(self, request: EffectRequest) -> EffectView: ...
    def deliver(self, command: DeliverEffect) -> DeliveryReceipt: ...
    def inspect(self, effect_id: str) -> EffectView: ...
```

`request` 與 WorkItem 在同一 transaction 寫入 outbox，並要求 idempotency key、effect kind、target reference、payload reference、risk class 與期望 acknowledgement。`deliver` 只允許 effect-worker identity + fencing token。

Implementation 隱藏 retry、backoff、dead letter、provider-specific request、下游 read-back 與 reconcile。每個 true external system有 production adapter 與 fake adapter；不存在一個無型別的 `execute(action, payload)`。

### 2026-07-24 EffectRequest idempotency checkpoint

- program commit 11 已建立 shadow `EffectDelivery.request()`／`inspect()` external
  interface。`EffectRequest` 強制追溯 WorkItem id／version，並明確保存 effect kind、
  target reference、payload reference + SHA-256、`safe | sensitive | destructive`
  risk、requester 與 typed acknowledgement kind／read-back target。
- normalized request 的每個語意欄位都進入 canonical JSON SHA-256。同一 idempotency
  key 的等價 replay 回傳原始 immutable `EffectView`；不同 payload 拒絕。in-process
  lock 讓 32 路 concurrent replay 仍只呼叫一次 id factory；64 組不同 intent 的
  payload-bound replay property cases 另行覆蓋 identity。
- 此 checkpoint 不包含 program commit 12 的 durable store／transactional outbox。
  `request` 尚未與 WorkItem 在同一 PostgreSQL transaction 寫入，也沒有 `deliver`、
  effect-worker fencing、provider adapter、retry／dead letter 或 acknowledgement
  read-back；因此它不產生外部效果，也不構成 Effect Delivery ownership cutover。

### 2026-07-24 durable request／outbox checkpoint

- program commit 12 的第一個 durable slice 將 `EffectRequest` 與唯一 outbox row
  放進同一個 private PostgreSQL transaction。request 以 advisory transaction lock
  綁定 idempotency key；等價 replay 回傳原始 row，不同 canonical request SHA-256
  fail closed，outbox insert 失敗會連同 request 一起 rollback。
- request 必須引用已存在且 version 完全相符的 WorkItem。outbox worker 只能透過
  named `SECURITY DEFINER` function 取得單筆 claim；selection 使用 database clock、
  `FOR UPDATE SKIP LOCKED` 與有限 lease，crash 後由過期 claim 重領。read projection
  不暴露 claim token，runtime role 不能直接新增、修改或刪除底層 row。
- 此 checkpoint 尚未把 EffectRequest 建立嵌入 Work Coordinator 的 mutation
  transaction，也沒有 delivered／retry／dead-letter transition、effect-worker 的
  Primary Authority fencing、provider adapter 或 acknowledgement read-back。因此這是
  transactional outbox identity／claim 基礎，不是完整的 program commit 12，更不是
  notification／publisher ownership cutover。

### 2026-07-24 fenced settlement／retry checkpoint

- program commit 12 的第二個 durable slice 新增 typed
  `AcknowledgedEffect | FailedEffect` outcome 與單一 `settle_outbox` interface。
  acknowledgement 必須精確匹配原 EffectRequest 的 kind／target，所有 outcome 都要有
  evidence reference + SHA-256；provider 只分類 failure 是否 retryable，backoff、
  attempt limit 與 dead-letter disposition 留在 Effect Delivery implementation。
- PostgreSQL settlement 以 outbox sequence、effect id、attempt number、worker 與 raw
  claim token 做 fencing；過期、已被重領或錯綁 claim 在 mutation 前拒絕。transaction
  會一起寫入 token-digest-only immutable attempt receipt，並更新 outbox／EffectRequest
  終態；任何後半段 failure 會 rollback receipt 與狀態。等價 client retry 以
  transaction advisory lock 序列化並回傳原 receipt，不同 outcome fail closed。
- retry 採 database clock、30 秒起始的 bounded exponential backoff、一小時 cap、
  五次 attempt limit；第五次 retryable failure 或任何 terminal failure 進
  dead letter。worker role 只能執行 named function 並讀 token-redacted receipt view，
  不能 mutation table 或讀 claim token digest。
- Effect Delivery scoped suite 109 passed，包含雙 worker claim、crash-after-claim
  recovery、expired-token rejection、並發 settlement replay、retry exhaustion、
  acknowledgement mismatch 與 transaction rollback。此 checkpoint 沒有 provider
  adapter、Primary Authority grant、正式 Work Coordinator caller 或 live migration，
  也尚未實際執行 typed downstream read-back；因此不是 notification／publisher
  ownership cutover。

### 2026-07-24 safe email notification adapter checkpoint

- program commit 13 的第一個 provider adapter 只接受
  `email.notification.send` + `safe` risk + 單一 `email:<recipient>` target，並要求
  完全相同 target 的 `email.sent-mail.readback` acknowledgement；其他 effect／risk／
  target 組合在 provider 前 terminal fail closed。
- caller 提供的 raw `email-notification.v1` JSON bytes 必須 exact-match EffectRequest
  的 payload SHA-256。Adapter 以 effect／request／payload identity 導出穩定
  Message-ID；SMTP 前先查 Sent mailbox，已存在且 Message-ID、收件人、subject、
  plain／HTML body 全相符時直接回傳相同 acknowledgement，不重寄。
- 現行 `EmailNotifier` 只新增可選的 provider Message-ID threading，既有 caller
  interface 與 bookkeeping 不變。SMTP process exit／server acceptance 不算成功；
  provider write 後必須透過獨立 `ImapSentMailReader` 回讀 exact message bytes，
  acknowledgement evidence hash 直接取該 bytes。缺 Sent copy 為 retryable failure，
  已存在但內容漂移則 terminal fail closed。
- fake Sent adapter 與 production IMAP adapter 共用同一個窄 read port；133 個 Effect
  Delivery／EmailNotifier scoped regressions 通過，且測試未連網、未寄信。此 checkpoint
  尚未接 durable outbox worker／settlement、Primary Authority、正式 Work Coordinator
  caller 或 live migration，也未執行真實 downstream smoke；因此 program commit 13
  只達 shadow provider capability，不構成 notification ownership cutover。

### 2026-07-24 authority-fenced worker／live shadow checkpoint

- private `EffectOutboxWorker.run_once` 現在擁有 claim → inspect → Primary Authority
  authorize → immutable payload read → typed provider → fenced settlement → receipt
  read-back 的完整嘗試生命週期。caller 只提供 worker identity、primary fencing token
  與 lease duration；raw outbox／primary token 不進回傳 receipt。
- authority request canonical hash 綁定 EffectRequest digest、WorkItem id／version、
  outbox sequence／attempt／claim／expiry、worker、primary fencing token、effect kind、
  target、payload 及 acknowledgement。SQL settlement 強制保存該 hash、token-redacted
  outbox claim ref 與 Primary Authority ref；11-argument unfenced overload 已移除。
- `FileEffectPayloadReader` 只接受設定 root 內 normalized `file:` relative path，拒絕
  absolute path、traversal、symlink escape 與 non-file。payload read／provider exception
  會變成 typed retry evidence，仍經同一 durable settlement path。
- production IMAP read-back 不再硬編英文 `[Gmail]/Sent Mail`：explicit mailbox 會轉成
  IMAP quoted-string，未設定時以 `LIST` 的 RFC 6154 `\Sent` special-use 找出在地化
  mailbox。這兩個修正都來自真實 Gmail `EXAMINE`／mailbox discovery failure。
- 五個 Operations Core migrations 已套用 live Supabase。PG17 非 superuser
  `CREATEROLE` migration path 的 membership／schema ownership privilege 順序已由
  真實失敗修正，並以本機 PG17 fixture 重播；Supabase performance advisor 指出的
  attempt-receipt outbox FK 缺 index 另由 forward migration 修正，複驗後不再出現。
- controlled live shadow attempt 2 已取得 stable Message-ID 的 Gmail Sent exact bytes，
  以 evidence SHA-256 settlement，並從 token-redacted views 回讀 EffectRequest／outbox
  為 `delivered`、receipt 為 `acknowledged`。143 個 Effect Delivery／EmailNotifier
  scoped regressions 通過。
- 這個 checkpoint 仍沒有 live Primary Authority adapter、durable payload writer、
  Work Coordinator 正式 caller 或 production ownership transaction；shadow 使用顯式
  authority grant 驗證 worker-side contract，不得宣稱 notification ownership 已切換。

## 7. Provider Execution

### 7.1 Seam

Worker 拿到 WorkLease 後，把 capability requirements 與最近 checkpoint 交給 Provider Execution；caller 不指定「Claude 失敗就 Codex」，也不自行解析 quota 字串。

### 7.2 External interface

```python
class ProviderExecution:
    def execute(self, request: ExecutionRequest) -> ExecutionOutcome: ...
    def observe(self, observation: ProviderObservation) -> ProviderStateView: ...
```

Implementation 隱藏 capability matching、attestation requirements、subscription/OAuth allowlist、bounded probe、quota/auth state、retry、preemption 與 resume。`ExecutionOutcome` 只能是 verified checkpoint、blocked reason、candidate ChangeSet／EffectRequest，或 terminal failure；provider adapter 不具正式 commit／effect 權限。

`observe` 不接受「下次重置日期」作真相，只接受實際 probe／execution evidence。零付費 deny policy 在 config validation、startup 與每次 selection 都執行。

## 8. Schedule Materializer 與 Primary Authority

### Schedule Materializer

```python
class ScheduleMaterializer:
    def materialize(self, tick: ScheduleTick) -> MaterializationReceipt: ...
```

它讀 canonical schedule spec，以 schedule id + due instant 作 idempotency key，將所有到期工作提交給 Work Coordinator。cron parsing、timezone、DST、missed-fire policy 與 event deadline 都藏在 implementation；OS 不直接執行 business action。

### Primary Authority

```python
class PrimaryAuthority:
    def acquire(self, request: AuthorityRequest) -> PrimaryLease: ...
    def renew(self, lease: PrimaryLease) -> PrimaryLease: ...
    def authorize(self, intent: WriteIntent) -> FencingToken: ...
    def release(self, lease: PrimaryLease) -> AuthorityReceipt: ...
```

只有 Change Delivery 與 Effect Delivery 需要 `authorize`。一般 WorkItem 純計算、讀取與 checkpoint 不要求 primary lease，因此 standby 或 provider failover 仍可做安全工作。

## 9. Package 與 visibility

建議在 `src/volpred/ops/` 下形成以下 public imports；每個 package 的 `__init__.py` 只 export external interface 與資料型別：

```text
volpred.ops.work         WorkCoordinator
volpred.ops.delivery     ChangeDelivery, EffectDelivery
volpred.ops.execution    ProviderExecution
volpred.ops.scheduling   ScheduleMaterializer
volpred.ops.authority    PrimaryAuthority
volpred.ops.incidents    IncidentLifecycle（由現有 incident implementation 漸進遷入）
```

Postgres repository、SQL、filesystem、subprocess、provider parsers、effect adapters、legacy importers 與 projections 都是 implementation，不從 package root export。Admin、CLI、scheduler 與 tests 只能跨 external seam，不能 import internal repository function。

## 10. Legacy 接管順序

### 10.1 Work lifecycle

1. 建立 Work Coordinator 與兩個 coordination-store adapters。
2. 以 fixture 重播 `next_tasks`、TaskRecord 與 `ops_jobs`，產生 mapping／collision／unrepresentable report。
3. shadow 讀 live sources，但不寫回、不 claim、不觸發 supervisor。
4. 匯入 `next_tasks` pending lifecycle；對帳 count、priority、claim ownership、parent、deadline 與 terminal history。
5. 原子切換 enqueue／claim／complete caller。
6. `next_tasks` 改為唯讀 projection；TaskRecord／ops_jobs 只保留歷史相容讀取。
7. 觀察期證明舊 writer 為零後，才移除舊 execution path。

### 10.2 Admin jobs

- 現有 Admin GET 先改讀 Work Coordinator read model。
- POST／PATCH 改提交 typed WorkRequest／WorkReport，不再直接 insert／update `ops_jobs`。
- `maybeExecuteRemoteJob` 必須在 Effect Delivery 接管後退役；不得讓網站程序持有正式外部效果 ownership。

### 10.3 Dispatch

- Supervisor 先保留 slot、process health 與 workspace allocation。
- Task selection、provider selection、quota blocker 與 completion 逐一改由新 modules 回傳決策。
- 等 Schedule Materializer 接管後，supervisor 只執行已取得的 WorkLease，不再擁有 business clock。

## 11. 第一個 TDD 垂直切片

第一個切片是 **Shadow Work Coordinator：submit → acquire → checkpoint → release/resume → complete**。它必須同時經過 external interface、transaction store port 與 event／receipt，不只建立 dataclass 或 CRUD repository。

### 2026-07-23 tracer checkpoint

- 已建立 `volpred.ops.work` external interface 與 transaction-safe in-memory adapter。
- 二十四個 in-memory interface test cases 已涵蓋 idempotent submit／inspect、approval／risk gate、
  unknown-policy 與 request self-approval fail-closed、可稽核的 owner approval transition、
  two-worker atomic acquire、capability-aware acquire、claimed→running、可冪等重播且
  衝突 payload fail-closed 的 verified checkpoint、
  cooperative release／resume、完整 lifecycle event audit、idempotent terminal receipt，
  parent／deadline readiness，以及 invalid transition／version／token、lease expiry／
  re-acquire／stale lease rejection。
- 已建立 private `volpred_ops` PostgreSQL 17 schema 與 production-shaped adapter；34 個
  Postgres cases 覆蓋相同 external seam、atomic claim、database-clock lease fencing、
  concurrent completion replay、由專用低權限 definer 擁有的具名
  `SECURITY DEFINER` mutation functions、worker／approver 分權、token-redacted read
  projection、RLS、NULL token/TTL fail-closed 與 transaction failure rollback；
  canonical row 已包含 parent／deadline、requester、created／updated、blocked reason。
- in-memory、Postgres 與相鄰 control-plane regression 共 71 tests 通過，Python compile
  與 whitespace check 通過。
- 這仍是 shadow implementation：沒有 CLI／Admin／supervisor caller，沒有讀寫
  `next_tasks`、live Supabase、schedule 或 live state；legacy importer 與 shadow replay
  尚未實作，migration 也尚未部署。
- Shadow `ApprovalGranted` 已保存 owner identity 與 evidence reference；正式 caller 的
  身分驗證、授權簽章與 replay protection 仍是 live cutover 前的必要 gate。
- 因尚未完成 Submit A–D 與七天 shadow，本 checkpoint 不構成 capability cutover，
  也不得將現行 queue owner 改為 Work Coordinator。

### 提交 A — Interface behaviour tests

- 以 transaction-safe in-memory adapter 測 external interface。
- 覆蓋 idempotent submit、atomic acquire、capability mismatch、invalid transition、stale lease、checkpoint hash、cooperative release、resume pointer、terminal replay。
- 測試只斷言 interface observable outcomes，不讀 internal dict／table。

### 提交 B — Postgres schema 與 adapter

- 建立 WorkItem、work event、checkpoint 與 claim transaction／RPC migration。
- Postgres adapter 通過與 in-memory adapter 相同的 external seam／behaviour matrix；
  目前兩套案例仍分檔鏡像，抽成單一 parameterized backend contract 是 live caller 前的
  維護性工作，不影響本輪 shadow transaction/security gate。
- 不部署、不讀 live queue；migration 可在隔離資料庫完整 rollback。
- **2026-07-23 shadow implementation complete**：migration 由 Supabase CLI 2.109.1
  產生，使用 private schema、FORCE RLS、無直接 DML 的 `volpred_ops_worker`、
  獨立 `volpred_ops_approver`、無登入／無繼承／無 membership 且僅具必要 DML 的
  `volpred_ops_definer`、PUBLIC privilege revoke、具名 mutation functions、
  `FOR UPDATE SKIP LOCKED` 與 transaction-scoped event／checkpoint／receipt。
  外部測試 DSN 必須同時為 localhost、無 remote `hostaddr`、專用
  `volpred_ops_test` database 且有明確 destructive-test opt-in；CI 固定啟動
  `postgres:17-alpine`，缺少 Postgres 時 fail
  而非整批 skip。已在短命
  PostgreSQL 17.10 cluster
  套用並驗證 rollback；未執行 linked migration 或 live query。CLI `db lint` 因純
  PostgreSQL image 缺少 Supabase `plpgsql_check` extension 無法執行，schema catalog
  security tests 與 31 個真實 adapter cases 作為本輪替代證據。

### 提交 C — Legacy snapshot importer

- read-only 解析三套來源，輸出 canonical candidate 與 reconciliation report。
- 對未知狀態、重複 ID、丟失 parent、同時 claim、無法映射的 public effect 一律 fail closed。
- `--dry-run` 是唯一模式；不修改 Supabase、JSON 或 task status。
- **2026-07-23 Submit C = `root_cause_fixed_and_verified`**（implementation commit
  `5ddb5b0d1`；47 scoped tests；Spec／Standards 雙軸複審無 P1／P2）：
  `LegacySnapshotImporter` 只接收 caller
  明確提供的 `next_tasks`、TaskRecord 與 exported `ops_jobs` snapshots，不自行連線
  Supabase 或讀 live source；輸出含 canonical candidate、原狀態、claim／terminal trace、
  source counts 與 structured issues 的 deterministic JSON report。公開 caller 只透過
  `volpred.ops.work_migration.preview_legacy_snapshots`，adapter class 保持 implementation
  detail。跨來源 duplicate ID、canonical idempotency collision、missing parent、
  simultaneous active claim、invalid lifecycle、unknown status／kind／policy／source、
  無時區 timestamp 與尚未有 Effect Delivery 契約的 public effect 都使 `ready=false`；
  payload reference 以 record SHA-256 綁定 supplied snapshot 內容。`next_tasks.source`
  採逐值核可的 exact provenance registry；原始值與分類依據都出現在 report，未登錄值
  fail closed，不使用 prefix 或 fallback 猜測 canonical source。
- CLI `uv run volpred ops work-import-legacy --dry-run` 強制同時提供三份 JSON array snapshot；
  沒有 apply／write 模式，對帳不通過以 exit code 2 結束。測試逐 byte 驗證三份輸入未變，
  且命令沒有產生旁路輸出檔。
- 對 2026-07-23 16:14:48 CST 的 `storage/next_tasks.json` 唯讀 smoke（snapshot
  SHA-256 `18281269d61832d97dc38177f8d26ec8b53b91e525e5198a99e9414a1f47c703`）：
  3,337 筆中 2,569 筆形成 candidate；structured issues 為 320 `invalid_record`、6
  `unknown_kind`、442 `unknown_source`、9 `missing_parent`、123
  `invalid_lifecycle`，因此正確 `ready=false`。此數字只描述該 hash 的
  `next_tasks` snapshot；TaskRecord／exported `ops_jobs` 由固定 fixtures 驗證，不與
  live queue 數字混加。未登錄 provenance 與其他差異是 Submit D 前要分類的 legacy
  debt，不以 importer 猜測修補。
- 本提交仍沒有 submit candidate、更新舊 JSON、查詢／修改 live `ops_jobs`、部署 migration
  或改變 canonical queue owner；它只建立 cutover 前的可稽核 migration boundary。

### 提交 D — Shadow replay

- 對相同 snapshot 執行舊 selection 與 Work Coordinator selection，記錄差異。
- 差異分類為預期政策變更、legacy corruption 或新 implementation bug。
- 沒有七天穩定 shadow 證據前，不進 live cutover。
- **2026-07-23 原始 checkpoint = `contained`（GitHub #7）**：
  `232ffc994`／`5b9f78adf` 已證明 immutable snapshot、no-live-lookup 與 append-only receipt，
  但 Matt 雙軸複審發現 replay 自行重寫 legacy／Coordinator readiness 與 ranking；54 個測試
  只能證明影子模型內部自洽，不能證明 production selector parity。該 checkpoint 不得再標
  implementation complete。
- **2026-07-23 reimplementation = `root_cause_fixed_and_verified`（GitHub #7）**：
  legacy `cmd_claim` gate 與 `cmd_list --status pending` candidate filter／priority-id rank 共用
  `volpred.ops.task_pool_selection`；in-memory Work Coordinator `acquire` 與 replay 共用
  `volpred.ops.work.selection`。PostgreSQL adapter 的 SQL acquire contract 另以 34 個隔離
  integration cases 回讀 capability／attestation、parent／deadline、atomic claim 與
  expired-lease reclaim parity。公開 `replay_legacy_selection` 仍先把 caller 提供的三份
  snapshot canonicalize 成單一 SHA-256 identity，再從該 bytes 建立私有 immutable copy；
  legacy selector 直接接收該 copy 的原始 `next_tasks`，不先經 migration importer 篩選；
  selection 只對真正由 production `list --status pending` 暴露、且包含 identity uniqueness
  在內的 direct-claim gate 接受者決定 winner。三份 supplied snapshot 的 raw identity
  inventory 會先於 mapping 掃描完整母體，因此跨來源 duplicate 不會因其中一筆無法映射而
  消失。Importer 無法表示的 record 仍留在 ledger，
  由 reconciliation evidence 分類；duplicate／missing identity 以 record ordinal + content
  hash 分開綁定並 fail closed，不會以 task id dict 覆蓋另一筆證據。blocked／claimed
  records 仍保留逐維度 evidence，但不參與 hourly winner。registered dreaming task 若需要 live detector，
  supplied snapshot 無法證明 revalidation 結果時以 `live_revalidation_required` fail
  closed；production claim 在同一 transaction 跑完 detector 後才重新進 admission，
  replay 本身不查 knowledge／feed／paper／live queue。另兩套
  snapshot 只參與相同 identity、reconciliation evidence，以及 next-task parent 的
  non-selectable dependency context；共用 selector 的 `dependency_items` 只提供 parent
  status、永遠不會成為 winner，因此不虛構跨 store selector。
  ledger 的 single dimension registry 比較 priority、status readiness、capability、
  attestation、claim ownership、lease expiry、dispatch lane、preferred agent、parent
  readiness、deadline 與 terminal disposition。每個不一致與 winner 差異都由實際 selector
  reason code 或 reconciliation issue 經顯式 policy oracle 分為 `policy_change`、
  `legacy_corruption` 或 `implementation_bug`，並附 candidate field、selector decision、
  policy contract、reconciliation issue 與 snapshot hash evidence reference；未送進
  Coordinator 的 record 明示 migration `not_evaluated`，不冒稱 selector reason。
- `uv run volpred ops work-shadow-replay` 只接受三份顯式 snapshot 路徑，沒有 live queue、
  Supabase 或 `ops_jobs` lookup，也不呼叫 Work Coordinator `submit`。它只在 caller
  指定目錄以 create-if-absent hard link 追加 observation receipt；相同 observation id
  會 fail closed，不覆寫舊證據。import 與 replay CLI 共用
  `load_legacy_snapshots`，避免 loader schema 漂移。152 個 selector／replay 核心 cases、
  另行重跑的 10 個 model-router topology regressions、144 個相鄰
  dreaming／stale-reclaim／refill regressions 與 34 個 PostgreSQL integration contracts
  通過，含輸入逐 byte 不變與測試期 remote/canonical I/O deny。
- 這只完成 replay 與 receipt 機械能力；尚未把 replay 加入 canonical schedule，也尚未
  累積七天 observation window，因此不構成 queue ownership cutover。
- **2026-07-23 Issue #9 assessment gate = `contained`**：新增
  `uv run volpred ops work-shadow-assess --observation-dir <dir>`，production CLI 固定七日
  window／26 小時最大 observation gap，clock 不可由 caller 覆寫；queue ownership
  直接回讀 canonical `storage/ops/task_pool_mode.json`；mode／enabled 與 SHA-256 由
  同一份 byte snapshot 解析，避免 atomic replace 期間出現 mode B 配 SHA A。
  append-only receipt 升為 `work-shadow-replay.v3`，由 append seam 寫入不可由 replay
  caller 回填的 `recorded_at`；七日 window／gap／freshness 一律用 `recorded_at`，
  `observed_at` 只作 selector clock 且與 append wall-clock 最多差五分鐘。每份 receipt
  逐日核對 `next_tasks` row count、candidate identity 與
  priority／claim ownership／parent／deadline／terminal disposition，未來時間、
  snapshot identity drift、重複 observation、未註冊 policy oracle reason、
  reconciliation issue 或 blocking selector difference 全部 fail closed。
  selection difference 與兩個 selector views 採 iff／exact-ref 契約，所有 selected /
  eligible refs 必須存在於該 receipt comparisons；兩側 eligible set 必須分別精確等於
  `legacy_eligible=true`／`coordinator_eligible=true` 的 candidates，禁止 duplicate，
  且 winner 存在 iff eligible set 非空。非 ranking policy reason 只能由實際
  legacy／Coordinator winner 的已驗證 mismatch dimension 提供。
  初版 `d53a705a6` 經 Matt 雙軸 review 發現 caller-declared mode、future receipt、
  cross-day dimension union 與 policy-change 字串豁免四個 gate 漏洞；第二輪又發現
  mode/SHA 雙讀競態、`observed_at` 可回填七日，以及只驗 oracle reason 名稱而未驗
  兩側 selector prerequisites／evidence binding。以上 remediation 均以
  public-interface regression 重現後修復。
- live canonical mode 已由 owner-directed P1 切成 `direct_execution`，舊 queue 3,338
  rows 已有 exact-byte backup 後清空；因此原 Issue #9 的 legacy-queue 七日 soak
  **不能沿用或補算**，assessment 正確回報 mode conflict。尚無七日 receipt、canonical
  replay schedule、CAS cutover、legacy read-only projection 或 rollback rehearsal，
  Issue #9 保持 open，狀態不得高於 `contained`。
- assessment slice commits：`d53a705a6`、`fcb8d8d21`、`da4e43277`、
  `54a9d6a28`、`28b6d193b`。最終 Matt Standards／Spec 雙軸 review 均 PASS
  （0 findings）；assessment／replay／direct-mode／claim／handoff targeted suite
  135 passed，live read-back 仍為 `ready_for_cutover=false`（mode=`direct_execution`、
  observation_count=0）。這只核可 gate implementation，不核可 Issue #9 cutover。

### Issue #9 — Pre-cutover legacy read projection

- **2026-07-24 projection interface implemented and isolated**：
  `volpred.ops.work_projection.project_legacy_next_tasks(WorkSnapshot)` 是唯一 public
  projection seam；輸入由 caller 注入，implementation 不讀 filesystem、Supabase、
  `ops_jobs` 或 live queue，也沒有 publish／apply／writer interface。
- projection 把 Work Coordinator 的 pending、awaiting approval、claimed、running、
  blocked、succeeded、failed 與 cancelled lifecycle 映回 legacy status，保留
  row count、priority、capability、
  attestation、claim owner／expiry、由 event ledger 回推的 claim/start timestamp、
  parent、deadline、approval evidence state 與 terminal result。輸出先依
  priority／work id deterministic 排序，再以 canonical JSON bytes 產生 SHA-256；
  `read()` 每次 decode 新 copy，因此 compatibility caller 無法改到 canonical snapshot。
- duplicate WorkItem id、active lifecycle 缺 claim event／owner／expiry、同一版本有模糊
  event、unsupported Coordinator status，或 existing `LegacySnapshotImporter` 無法
  round-trip 的 source／kind／policy／parent／lifecycle 一律在產生 projection 前
  fail closed。相容測試直接把輸出交給 production legacy read selector 與 importer，
  不建立 projection 專用 policy copy。
- 這只完成 step 18 的 **read interface contract**，沒有 materialize
  `storage/next_tasks.json`、沒有讓 legacy claim path 寫 projection、沒有 transaction
  cutover 或 rollback rehearsal。Issue #9 仍為 `contained`；七日 receipts、正式
  Coordinator ownership transaction 與 live unique-owner read-back 仍是 blocker。

### Issue #9 — Cutover manifest preflight

- `prepare_work_ownership_cutover()` 是 step 20 transaction 前的唯一 evidence-binding
  seam。它直接讀 immutable receipt directory，以不可由 API caller 覆寫的 wall clock
  呼叫 canonical assessor。Canonical queue path 由 repo root 固定推導，不接受 caller
  path；paired owner state 由 queue path 唯一衍生，queue bytes／owner state 在同一
  shared lock 內取樣並取得 mode 與 CAS SHA；
  caller 不再能傳入或重建 `ready_for_cutover=True` summary 來放行。
- Caller 三來源 snapshot 的 row mappings 雖可能 mutable，進 seam 第一個動作會先
  canonicalize 成單一 byte generation，再 decode 成 private copy；queue equality、
  importer 與 latest-snapshot identity 不再跨三次讀 caller object，避免 mutable-input
  TOCTOU 交叉綁定。
- 同一規則也由 canonical `replay_legacy_selection()` producer 持有：ledger snapshot
  hash、import、legacy selector、Coordinator selector 與 comparisons 全部只從入口
  private copy導出；不再以 A→B→A 三次 caller read 讓 ledger hash 與比較內容脫鉤。
- Raw legacy bytes 由 seam 自行 decode、計算 SHA 並產生 importer report；staged
  Work Coordinator projection 會再走既有
  importer，逐 work identity 比對 row count、status、priority、source／policy、
  capability／attestation、claim owner／timestamps／expiry、parent、deadline、
  blocked reason 與 terminal disposition（含 row `created_at`／`updated_at` 及 current
  claim 的 `started_at`）。
  Projection row count／SHA 由 payload 重算。Manifest 以 canonical JSON 綁定 raw
  legacy snapshot、canonical assessment、derived import report、validated projection
  與 owner-state 五個 SHA-256 identity；assessment 額外綁定 canonical receipt-set
  digest 與最後 snapshot identity，最後一筆必須 exact-match 本次三來源 cutover
  snapshot。Importer 已保存但 Coordinator projection 無法表示的 dispatch lane、
  preferred／target agent、fallback policy、dreaming 或 timestamp 會造成 parity fail，
  不會靜默降級。
- Parity 相符不代表 active lease 可移交。Legacy `claimed`／`running` worker 手上的
  mutation token 不存在於唯讀 projection，硬切 owner 會讓舊 worker 失去續寫能力，
  或迫使新 owner 接受無法驗證的 claim。Preflight 因此要求 next_tasks 為
  quiescent（零 active lease）；active work id 會在 manifest 產生前明確 fail closed。
- 這是 **read-only preflight capability**，沒有 filesystem／database mutation、
  materialize 或 apply interface。Live `direct_execution` mode 與零 observation
  evidence 均未變；正式 CAS transaction、唯一 owner 下游回讀及 live rollback
  rehearsal 仍未完成，因此 Issue #9 保持 `contained`。

這四個提交就是下一輪 `tdd` skill 的範圍；完成並取得七天 shadow 證據後，才規劃第一個
正式接管切片。ChangeSet、EffectRequest、provider 與 scheduler 不與 Work Coordinator
第一批同時實作。

## 12. Interface-level 測試矩陣

| 行為 | In-memory | Postgres | Failure injection |
|---|---:|---:|---:|
| idempotent submit | ✓ | ✓ | transaction rollback |
| two-worker atomic acquire | ✓ | ✓ | `SKIP LOCKED` race |
| expected-version transition | ✓ | ✓ | stale writer |
| capability／attestation match | ✓ | ✓ | provider state changes after claim |
| checkpoint verify／resume | ✓ | ✓ | corrupt hash／event failure rollback |
| cooperative preemption | ✓ | ✓ | kill before／after checkpoint |
| parent／deadline readiness | ✓ | ✓ | database clock／expired lease |
| terminal receipt replay | ✓ | ✓ | concurrent duplicate completion |
| host fencing on delivery link | — | — | Submit D shadow replay 前實作 |

舊 shallow module tests 先保留作 regression。只有 caller 已切到新 seam、且相同行為已在 external interface contract suite 覆蓋後，才刪除被取代的舊 unit tests；不能提前用新測試掩蓋舊路徑。

## 13. Rejected designs

- **單一 `OperationsCore` God module**：interface 會包含 task、provider、Git、effect、schedule、incident 與 Admin 所有知識，沒有 locality。
- **Generic CRUD repository 作 external interface**：把狀態機、交易順序與權限推回 caller，是 shallow module。
- **Generic `execute(action, payload)`**：延續 `jobs.py::_run_action` 的無型別 switch，無法局部推理 effect 契約。
- **每張 table 一個 module**：資料儲存形狀不是業務 seam，會產生大量 pass-through。
- **永久 dual write**：新舊狀態不同步時沒有唯一裁決者。
- **只用 mocks 測 Git／filesystem**：本機依賴有可替代環境，應用真實 temporary Git repo。
- **一次重寫 task、provider、scheduler、delivery**：無法判定回歸屬於哪個 interface，違反逐能力接管。

## 14. Phase 0 尚需機械盤點

在 TDD 實作前，先由可重跑 inventory 固定：

- 所有 `next_tasks` writers／readers 與 task state mutation；
- `local_control_plane` callers 與仍會 claim 的路徑；
- Python／Next.js `ops_jobs` writers、remote executors 與 Admin routes；
- Git index／ref writers與外部 effects；
- schedule materializers、provider spawners、quota/auth parsers；
- secrets／identity／host-specific paths；
- frontend 與 Admin 對舊 task shapes 的讀取依賴。

Inventory 只讀並輸出 versioned report。任何未知 writer、無法重播的 migration 或無 owner side effect，都會阻擋接管，不以猜測補齊。
