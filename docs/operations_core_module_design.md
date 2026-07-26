# Operations Core Module Design

- **Status**：ACTIVE MIGRATION — `email.ops_alert` 已切換 live owner；其餘 capability
  仍須逐一通過接管 gate
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
  service；在這個 checkpoint 當時仍缺 Postgres Primary Authority adapter、durable
  DeliveryReceipt、
  `ChangeDelivery.land`、network-partition failure injection 與正式 caller 仍未完成；
  step 34 的 acquire／renew／demote workflow 前不得宣稱取得 commit ownership。

### 2026-07-24 PostgreSQL commit authority checkpoint

- 新增 private `PostgresCommitAuthority`，作為既有 `CommitAuthority` seam 的第二個
  adapter。它接收 current typed `PrimaryLease`；caller 不需要知道 SQL、grant table
  或 lock ordering。
- Adapter 在 database access 前重算 proposal、WorkItem/version、兩個 raw fencing
  token、repository/HEAD、exact paths/content hashes、message 與 commit-worker identity
  的 canonical SHA-256，不能把合法 digest 配給修改後的 intent。
- `authorize_commit_write` 在同一 transaction 要求 exact `running` version、非空
  Work holder、matching/unexpired WorkLease 與 database-clock Primary Authority。
  Durable grant 綁 proposal、Work holder、commit worker、repository/HEAD，只暴露
  token-redacted WorkLease／Primary Authority refs。
- Grant table FORCE RLS；只有 no-login definer policies 可 select/insert，
  `volpred_ops_worker` 只得到 named-function execute，PUBLIC 無 execute／table-read。
  PostgreSQL 17 non-superuser migration replay、stale-fence、forged-hash 與 equivalent
  replay contracts 通過。
- 此切片仍為 `contained`：migration 未套 live，`ChangeDelivery.land` 與 durable
  post-commit receipt 尚缺，external Git write 也尚未與 lease
  revalidation／settlement transaction 耦合。現行 Git ownership 不變。

### 2026-07-24 ChangeDelivery land／post-commit settlement checkpoint

- `ChangeDelivery.land()` 已成為 proposal 到 landing 的唯一 orchestration seam。它從
  immutable ChangeSet 建立 actuator command；Git commit 一旦取得精確
  `commit-actuation.v1` read-back，即把狀態標成 `commit_unsettled`。後續 DB 暫時失敗的
  retry 只重跑 settlement，不再啟動第二次 Git write；landing command 漂移會以
  `ChangeSetConflict` fail closed。
- 新增 private `PostgresCommitSettlement` 與 `settle_commit_write` transaction。它在
  external Git interval **之後**重新鎖定 exact running WorkItem，核對 version、holder、
  未過期 WorkLease，再用同一 authority request 重新驗證 database-clock Primary
  Authority；只有兩道 fence 仍有效時才保存 `change-delivery-receipt.v1`。
- Durable receipt 綁 change-set/proposal、authority request、token-redacted lease refs、
  repository、commit/parent、exact paths、commit worker 與 actuation timestamp。同一
  receipt 等價 replay 即使 lease 日後已到期仍可回讀；任何欄位漂移都拒絕。Receipt
  table FORCE RLS，PUBLIC 無 table/function access，worker 只有 named-function
  execute。
- Actuation timestamp 不只是 display metadata。`ChangeDelivery.land()` 在 settlement
  seam 前要求 `observed_at` 為可解析且 timezone-aware 的 timestamp；非法或 naive
  wall-clock fail closed，不能讓 PostgreSQL session timezone 隱式決定 durable identity，
  也不能把未驗證 receipt 留成 `commit_unsettled` checkpoint。
- PG17 non-superuser replay 首輪實際抓到：對 immutable authority grant 使用
  `SELECT ... FOR UPDATE` 會在 FORCE RLS 下需要不存在的 UPDATE policy，因而把現存
  grant 誤判成 unknown。Final transaction 對 immutable grant 使用 SELECT-only，
  只鎖可變 WorkItem；這同時維持 least privilege 與短 transaction。174 個
  Change／Effect Delivery 相鄰 tests 通過。
- 此 checkpoint 尚未部署 live，也沒有 formal Work Coordinator caller、candidate
  workspace→canonical checkout 的 production materializer、durable ChangeSet proposal
  store、Git ownership cutover 或 rollback rehearsal。因此 post-commit
  authorization/receipt seam 的具體缺口已修，但 Change Delivery 整體仍是
  `contained`，現行 Git owner 不變。

### 2026-07-24 durable ChangeSet lifecycle checkpoint

- external `propose／inspect／land` interface 不增加 persistence 細節；private
  `ChangeSetStore` seam 一次封裝 immutable proposal、landing-command identity、
  token-redacted `commit-actuation.v1` checkpoint 與 final `DeliveryReceipt` linkage。
  in-memory 與 PostgreSQL 兩個 adapter 讓 seam 成為真實變異點，而非只有一層 pass-through。
- `ChangeDelivery.land()` 不再以 instance dict 判斷是否已 commit。actuator read-back
  通過後，必須先由 store 原子轉成 `commit_unsettled`，才跨入 settlement；新 process
  讀到該 checkpoint 時直接重建 settlement command，不會再次呼叫 actuator。settlement
  已 durable、但 store 尚未標 landed 的 retry 也只 replay receipt linkage。
- PostgreSQL migration 以 idempotency-key advisory lock 建 proposal，並核對 exact
  WorkItem version；checkpoint transaction 鎖定 ChangeSet、驗證 proposal／command
  digest、WorkItem、parent、paths、commit actor 與 timezone-aware actuation identity；
  landed transition 必須 join 已存在且完全匹配的 immutable commit receipt。
- `change_sets` FORCE RLS，PUBLIC 無 table/function access；worker 只能讀
  token-redacted view 與呼叫三個 named functions。Raw WorkLease／Primary fencing
  token 不進 schema，只保存 canonical landing-command SHA-256。PG17 non-superuser
  migration replay、process restart、conflicting replay、RLS 與相鄰 Git/Effect suite
  共 68 tests 通過。
- production Supabase 唯讀 catalog 仍回傳 change-set／commit grant／settlement
  tables/functions 全為 `null`，證明本切片沒有越權部署。checkpoint 已 durable 後的
  restart ambiguity 已消除；Git commit 成功到 checkpoint transaction 提交之間的
  lost-return recovery 見下一節。formal caller、live migration、ownership cutover
  與 rollback rehearsal 仍未完成，所以整體仍為 `contained`。

### 2026-07-24 exact Git lost-return recovery checkpoint

- `GitCommitActuator.commit()` 每次都先重新取得完整 authority grant。HEAD 若仍等於
  expected parent 才可呼叫 canonical writer；HEAD 已前進時，actuator 只檢查該 parent
  後第一個 first-parent commit，不會在任意 history 搜尋相似內容。
- Recovery 要求 candidate 的 parent、完整 commit message、sorted exact path set 與
  每個 committed blob SHA-256 都精確符合 normalized `CommitActuation`。成功時使用
  Git committer 的 timezone-aware timestamp 重建 token-redacted receipt；任何 mismatch
  維持 stale-HEAD fail closed，writer 零呼叫。已在 candidate 上方新增後續 commit
  也不影響精確回讀。
- 「完整 commit message」不是 caller 的人類可見文字本身。Actuator 在 authorize 後
  固定附加 `Volpred-Commit-Authority-Request: <sha256>` trailer；SHA-256 綁同一次
  proposal、WorkItem/version、Git owner generation、兩個 fencing token、
  repository/parent、paths/hashes、原 message 與 commit-worker actor。Writer argv
  與 durable receipt 仍不包含 raw
  token。正常 post-write verification 與 stale-HEAD recovery 共用這個 exact bound
  message gate，因此沒有 authority trailer 的 bitwise lookalike first child 會
  fail closed。
- 跨 process regression 直接讓第一個 actuator 在 writer 已 commit 後、store
  checkpoint 前遺失 return；第二個 `ChangeDelivery` instance 由同一 proposed record
  恢復 exact commit，接著完成 checkpoint／settlement，並證明 expected parent 到 HEAD
  只有一筆 ChangeSet commit。Change Delivery／Git actuator scoped suite 37 passed。
- 此切片封閉 shadow interface 的 lost-return crash window，但沒有 materialize
  candidate workspace、部署 PostgreSQL migrations、接上 formal Work Coordinator caller
  或完成 ownership cutover／rollback rehearsal；Change Delivery 整體仍為
  `contained`。

### 2026-07-24 candidate workspace materialization checkpoint

- `ChangeDelivery.land()` 現在把 immutable proposal 的 `workspace_ref` 傳入 private
  `GitCommitActuator`；actuator 仍先取得完整 WorkLease／Primary Authority grant，只有
  真正需要寫 Git 時才把 linked worktree 交給 canonical writer。Lost-return recovery
  找到既有 commit 時不要求 ephemeral workspace 仍存在。
- `git_writer_lock.py commit --source-workspace` 將 source revalidation、exact-path
  materialization、stage、staged-blob hash fence、commit 與 commit-object read-back
  放在同一把 common-dir writer lease。Source 必須是同 repo 的 registered non-main
  worktree，HEAD、clean index、完整 dirty-path set 與每個 content hash 都須匹配
  proposal；source path 只負責搬運，write identity 仍由 proposal SHA、base、path 與
  content hash 綁定。
- Canonical target 只接受 base bytes 或前次遭 kill 留下的 exact candidate bytes；
  symlink、缺失 tracked file 或任何外來 working bytes 都在覆寫前 fail closed。一般
  commit／hook 失敗會 reset 本次 index 並原子還原 materialization 前的 exact-path
  bytes；kill 後重跑則可從 exact candidate residue 冪等續作。
- Git writer、Change Delivery 與 actuator scoped suite 共 72 tests 通過，canonical
  writer audit 為 0 unguarded／0 owner mismatch／0 routing violation。此 materializer
  seam 的 overwrite／rollback 缺口為 `root_cause_fixed_and_verified`；formal Work
  Coordinator caller、live migrations、Git ownership cutover 與 rollback rehearsal
  仍未完成，所以 Change Delivery 整體維持 `contained`。

### 2026-07-24 Git file-mode identity checkpoint

- `changeset.v1` 綁定 exact paths 與 content SHA-256，但沒有 file-mode 欄位；修正前
  同一 proposal 可在 source validation 後由 `100644` 漂成 `100755`，writer 仍會落地，
  lost-return recovery 也會把 bytes／message／paths 相同但 mode 不同的 commit 誤認為
  原 write intent。
- 為避免在 shadow schema 尚未 cutover 前擴張 durable identity，本 slice 採明確的
  bounded policy：tracked regular file 必須保留 base tree 的 `100644`／`100755`；
  new file 只允許 `100644`。Executable-bit transition 與 executable new file 都 fail
  closed，未來若要支援必須先把 mode 正式加入 proposal、authority request 與 receipts。
- `propose()` 先核對 workspace stat 與 base tree；canonical writer 在 common-dir
  lease 內再次核對 source 與 target mode，避免 materialize 覆蓋 foreign chmod；
  commit-object read-back與 stale-HEAD recovery 再比較 expected／observed tree mode。
  四個 RED cases 已轉 GREEN，完整 Change Delivery／Git actuator／Git writer scoped
  suite 76 passed。此 mode identity 根因為 `root_cause_fixed_and_verified`；formal
  caller、live migrations、ownership cutover 與 rollback rehearsal仍缺，整體維持
  `contained`。

### 2026-07-24 authority-bound Git object checkpoint

- Lost-return recovery 原先把 caller message、parent、paths、blob hashes 與 bounded
  file modes 當成完整 commit identity；另一個 writer 若先建立位元完全相同的 first
  child，actuator 會誤建自己的 authority receipt。該 commit 實際上沒有證明由本次
  WorkLease／Primary Authority grant 產生。
- `GitCommitActuator` 現在只把原 message 留在 authority request identity，authorize
  成功後才交給 canonical writer 一份附加 authority-request SHA-256 trailer 的 bound
  message。正常 writer read-back 與 historical recovery 都重建並 exact-match 同一
  trailer；不同 grant、沒有 trailer或只有相同內容的 lookalike 均 fail closed。
- Regression 先證明 unbound bitwise lookalike 會被舊實作接受，再驗證修正後拒絕，
  同時正常 commit object 的 trailer 與 receipt digest 精確一致、真 lost-return
  recovery 仍可完成；舊 owner generation 產生的合法 trailer 也不可被新 generation
  recovery 接受。這個 commit-provenance identity 缺口為
  `root_cause_fixed_and_verified`；formal caller、live migrations、Git ownership
  cutover 與 rollback rehearsal仍缺，Change Delivery 整體維持 `contained`。

### 2026-07-24 owner-fenced formal caller checkpoint

- `OwnedChangeDelivery` 將 formal Work Coordinator caller 收斂為一個 deep operation：
  讀 current `git.commit` owner、建立 immutable proposal、owner-fenced land，再回讀
  terminal WorkItem。它要求 owner 為 `operations_core`，並將同一 generation 綁入
  landing command、authority request／grant、actuation、settlement 與 delivery
  receipt；PostgreSQL authorize／settle 會在 transaction 內再次鎖定 owner，caller
  的前置 read 不會成為授權依據。
- Private `commit_owners`／`commit_owner_receipts` 提供 approver-only CAS transfer。
  舊的無 owner 參數 authorize／settle overload 已對 worker 失權；rollback 必須指出
  current generation，且任何未 settlement grant 或 `commit_unsettled` ChangeSet
  都會阻擋 ownership transfer。新 settlement 在 immutable receipt 落表後，同一
  transaction 以穩定 report id 完成 WorkItem；formal caller 回讀 status、version、
  settlement ref、summary、finished time 與 cleared claim。
- PostgreSQL 17 已用 non-superuser migration executor 從乾淨 schema replay；
  RLS／function owner／fixed search path／least-privilege read-back 全部通過。臨時
  canonical repo + registered linked worktree 的 non-live E2E 實際建立 owner
  generation 2 commit、回讀 ChangeSet／grant／receipt／WorkItem，再演練 legacy
  generation 3 rollback、冪等 replay、stale CAS refusal 與 generation 4 re-cutover。
- Formal caller、durable store、commit authority、settlement 與 rollback mechanism
  的 shadow 根因達 `root_cause_fixed_and_verified`。

### 2026-07-24 live schema deployment checkpoint

- 五筆 Change Delivery private migrations 已依序套到 production Supabase：
  commit authority、post-commit settlement、Git owner generation、durable
  ChangeSet store，以及 advisor 回讀後追加的 delivery-receipt FK covering index。
- Live catalog 回讀所有 named functions 都由 no-login `volpred_ops_definer` 持有、
  `SECURITY DEFINER` 且固定 `search_path`；五張新表全部 FORCE RLS，PUBLIC 無
  SELECT／EXECUTE，worker 可用 owner-fenced overload、不可用舊 overload。Security
  advisor 對 `volpred_ops` 為 0 findings；新 FK 的 unindexed finding 在 forward
  migration 後消失。
- Owner row 刻意保持 `git.commit=legacy/1`，grant／delivery receipt／ChangeSet
  count 均為 0。這只完成 schema deployment 與 live read-back，不是 Git ownership
  cutover；正式 CAS、production smoke 與 live rollback rehearsal 尚未執行，因此
  Change Delivery 整體仍為 `contained`。

### 2026-07-24 service-role owner RPC checkpoint

- Live 管理面實測無法執行 private `read_commit_owner()`；這是正確的 privilege
  拒絕，但也證明 production 沒有可供 operator／PostgREST 使用的正式 read／CAS
  adapter，不能靠臨時 SQL 或 RLS bypass 收尾。
- 新 public RPC 只委派 private owner functions，保留原本的 CAS、unsettled grant／
  ChangeSet rollback fence 與 immutable receipt。兩個 functions 都由
  `volpred_ops_definer` 持有、`SECURITY DEFINER`、空 `search_path`，只授權
  service role；anon／authenticated／PUBLIC 均拒，service role 無 table SELECT。
  Python `SupabaseCommitOwnerStore` 對 RPC payload 與錯誤做 typed fail-closed。
- PG17 non-superuser clean replay、service-role cutover→rollback、ACL 與 HTTP adapter
  regressions通過；production receipt
  `20260724074117 operations_core_commit_ownership_rpc` 已回讀，security／performance
  advisors 對兩個新 RPC 均為 0 findings。Live RPC 回讀 owner 仍是 `legacy/1`，沒有
  執行 transfer。這個 operator seam 根因為 `root_cause_fixed_and_verified`，但完整
  production delivery adapters、live commit smoke 與 rollback rehearsal仍缺，
  Change Delivery umbrella 維持 `contained`。

### 2026-07-24 service-role ChangeSet store checkpoint

- `SupabaseChangeSetStore` 實作既有 private `ChangeSetStore` protocol，不另造 lifecycle
  state machine；immutable create、兩種 identity read、actuation checkpoint 與 landed
  linkage 分別委派 private transaction functions。PostgREST payload 會轉回同一
  `ChangeSetRecord`，timestamp 必須含 offset，conflict／validation error 保留 typed
  fail-closed semantics。
- 五個 public wrappers 全是 `volpred_ops_definer` owner、`SECURITY DEFINER`、
  `search_path=''`，只給 service role EXECUTE；anon／authenticated／PUBLIC 拒絕，
  service role 仍不能 SELECT private table 或 token-redacted view。Owner store 與
  ChangeSet store 共用窄 service-role transport，且 environment builder 只讀
  `SUPABASE_SERVICE_ROLE_KEY`。
- Unit transport contracts、PG17 non-superuser clean migration replay／二次 replay、
  ACL 及 service-role create/by-id/by-idempotency read 已通過。Production receipt
  `20260724081714 operations_core_change_set_rpc` 已回讀；live catalog hardening／ACL
  全 true，HTTP missing lookup 為 null、owner=`legacy/1`、ChangeSet count=0。這封閉
  ChangeSet production HTTP persistence seam，但 Work read model 仍只有 direct
  PostgreSQL adapter；故 bounded seam 為
  `root_cause_fixed_and_verified`，Change Delivery umbrella 仍是 `contained`。

### 2026-07-24 service-role commit authority checkpoint

- `SupabaseCommitAuthority` 是既有 private `CommitAuthority.authorize()` seam 的第二個
  production adapter。它先重算完整 write-intent SHA-256，再把 current PrimaryLease
  identity、兩個 raw fencing token 與 owner generation 交給 narrow PostgREST RPC；
  caller 不需要知道 SQL、grant table 或 lock ordering。
- Public wrapper 只委派既有 owner-fenced `authorize_commit_write` transaction，沒有
  第二套 grant policy；輸出只有 token-redacted durable grant。Function 由
  `volpred_ops_definer` 持有、`SECURITY DEFINER`、`search_path=''`，只給 service role
  EXECUTE，service role 對 private grant table／view 仍無 SELECT。
- PG17 non-superuser clean migration、migration replay、actual service-role
  authorize/replay、transport／typed-error regressions與相鄰 135 tests 通過。
  Production receipt `20260724085535 operations_core_commit_authority_rpc` 已回讀；
  live catalog 八項 hardening／ACL predicates 全 true，advisor 沒有指向新 RPC 的
  finding。正式 HTTP adapter 在 `git.commit=legacy/1` 下精確 fail closed 為 typed
  `CommitActuatorBlocked`，再次回讀 grant／receipt／ChangeSet 全為 0。
- 這個 remote authority adapter seam 為 `root_cause_fixed_and_verified`；Work read
  model HTTP adapter、live ownership CAS、commit smoke 與 rollback
  rehearsal仍缺，因此 Change Delivery umbrella 維持 `contained`。

### 2026-07-24 service-role commit settlement checkpoint

- `SupabaseCommitSettlement` 是既有 private `CommitSettlementStore.settle()` seam 的
  第二個 production adapter。它在送網路前由 exact actuation 重算 settlement
  SHA-256；caller 不需要知道 RPC payload、receipt table、lock ordering 或 Work
  completion transaction。
- Public wrapper 只委派 owner-fenced `settle_commit_write`，不複製 settlement state
  machine。Raw WorkLease／Primary Authority tokens 只作 database-clock revalidation，
  回傳仍是 token-redacted `change-delivery-receipt.v1`。Adapter 逐欄核對 proposal、
  WorkItem/version、owner generation/ref、authority refs、repo、commit/parent、paths、
  actor、timestamp、status、settlement ref 與 digest，untrusted JSON 一律 fail closed。
- Function 由 `volpred_ops_definer` 持有、`SECURITY DEFINER`、`search_path=''`，只給
  service role EXECUTE；anon／authenticated／PUBLIC 拒絕，service role 無 private
  receipt table／view SELECT。PG17 non-superuser clean／idempotent migration、
  actual service-role settlement、ACL 與相鄰 140 tests 通過。
  Production receipt `20260724092237 operations_core_commit_settlement_rpc` 已回讀；
  live catalog hardening／ACL predicates 全 true，兩類 advisor 沒有指向新 RPC 的
  finding。正式 HTTP adapter 在 `git.commit=legacy/1` 下 typed fail closed，前後
  grant／receipt／ChangeSet 全為 0。
- 這個 remote settlement adapter seam 為 `root_cause_fixed_and_verified`；Work read
  model 與 formal caller 的後續狀態見下方 checkpoint；live ownership CAS、commit
  smoke 與 rollback rehearsal仍缺，因此 Change Delivery umbrella 維持 `contained`。

### 2026-07-24 service-role Work read model 與 remote caller checkpoint

- `SupabaseWorkReadModel` 實作既有 `_WorkReadModel.inspect(WorkQuery)` seam，但 production
  adapter 只接受 exact WorkItem id，不提供未界定的全表 scan。單一 RPC 回傳 WorkItem、
  events、verified checkpoints 與 terminal receipts；Python 端驗證 schema、
  lifecycle、versions、timestamps、checkpoint hash 與所有 nested WorkItem identity。
- `volpred_read_work_snapshot` 只讀 private FORCE-RLS sources；function 是
  `volpred_ops_definer` owner、`SECURITY DEFINER`、`search_path=''`，只有 service role
  EXECUTE。anon／authenticated／PUBLIC 無權，service role 對
  `work_item_reads`／`work_events`／`work_checkpoints`／`work_receipts` 仍無 SELECT。
  `build_supabase_owned_change_delivery()` 現在將 owner store、ChangeSet store、
  commit authority、Git actuator、settlement 與 Work read model 組成 formal caller，
  並保留 owner check 在 proposal／Git write 之前。
- PG17 non-superuser clean migration、二次 replay、實際 service-role bounded read、
  ACL、HTTP transport 與相鄰 114 tests 通過。Production receipt
  `20260724101005 operations_core_work_read_model_rpc` 已回讀；live adapter 對一筆
  succeeded WorkItem 回傳 items=1／events=4／receipts=1，missing id 回傳空 snapshot。
  Probe 前後 WorkItem=19、ChangeSet=0、commit grant=0、commit receipt=0，
  owner=`legacy/1`；兩類 advisor 無新 RPC finding。
- 這個 read model 與 remote composition seam 為
  `root_cause_fixed_and_verified`。尚未執行 production ownership CAS、真實 commit、
  exact Git read-back 或 rollback rehearsal，所以 Change Delivery umbrella 仍為
  `contained`。

### 2026-07-24 service-role Primary Authority lifecycle checkpoint

- `SupabaseAuthorityStore` 是既有 `PrimaryAuthority` external interface 的 production
  HTTP adapter；acquire／renew／authorize／release 仍由原本的 private PostgreSQL
  database-clock transactions擁有，caller 不需要知道 lease table、token digest、
  lock ordering 或 PostgREST payload。
- 四個 public wrappers 只接受 lifecycle 所需的 raw fencing token，回傳 lease／grant／
  receipt 均不含 token。Python adapter 會核對 authority key、holder、epoch、
  resource、timezone-aware timestamps 與 lease window；任何 JSON drift 都 fail
  closed。Functions 是 `volpred_ops_definer` owner、`SECURITY DEFINER`、
  `search_path=''`，只給 service role EXECUTE；anon／authenticated／PUBLIC 無權，
  service role 也不能直接 SELECT private authority tables。
- PG17 non-superuser clean／idempotent migration、service-role
  acquire→authorize→renew→release、ACL 與 HTTP transport contracts 通過。Production
  receipt `20260724101355 operations_core_primary_authority_rpc` 已回讀；live HTTP
  smoke 只使用 `smoke:no-external-effect` resource，release 後下游 read-back 證實
  holder 與 token digest 都已清空，並各留下 1 筆 immutable grant／receipt；兩類
  advisor 都沒有指向新 RPC 的 finding。
- 這個 remote Primary Authority seam 為 `root_cause_fixed_and_verified`；它沒有執行
  Git owner CAS、commit、effect 或 host failover。Change Delivery umbrella 與
  program commit 34 的 acquire／renew／demote workflow 仍為 `contained`。

### 2026-07-24 host authority session checkpoint

- `HostAuthoritySession` 把 host-side acquire／renew／demote 收進一個 typed workflow，
  不讓 scheduler、commit worker 與 effect worker各自保存一份「本機是否 primary」
  判斷。`activate()` 成功後的等價重入回傳同一份 lease，不再次產生 fencing token；
  token-redacted `status()` 只暴露 holder、epoch、expiry 與最後 release reference。
- `renew()` 在同一把 process lock 內重驗 lease identity 與 timezone-aware window；
  control plane unavailable、stale lease、malformed read-back 或已過期 lease都會先清除
  本機 raw lease 並轉為 `demoted`，再以 typed `AuthorityInactive` 失敗。`demote()`
  同樣先停用本機 authority 才呼叫 remote release；release response 遺失時，本機仍
  不可繼續產生正式 write，remote lease 至多留到 database-clock expiry。
- 共享 store 的雙 host failure injection 證明同時只有一個 session 可 active；
  primary release 後 standby 取得下一個 epoch，舊 session 無法再取出 token。Renew
  failure、release failure 與 local expiry cases 亦都維持 fail closed。Primary
  Authority session、Supabase adapter 與 PG17 RPC scoped suite 共 12 passed。
- 這完成 host workflow 的 in-process state／demotion contract，但尚未把週期性 renew
  接到 canonical keepalive。這個缺口的後續狀態見下方 checkpoint；所有 effect
  classes 的 enable gate與兩台真實 Mac network-partition／五分鐘 failover rehearsal
  仍未完成。因此本切片的局部根因為 `root_cause_fixed_and_verified`，program
  commit 34 整體仍是 `contained`。

### 2026-07-24 canonical Primary Authority keepalive checkpoint

- `HostAuthorityKeepalive` 是一個 host process 內唯一的週期性 renew owner。它先透過
  `HostAuthoritySession.activate()` 取得 lease，之後 caller 只能經 keepalive 的
  `current_lease()` 取用；wrapped session 不再是 effect／commit caller 的 enable
  interface。Renew interval 必須短於 lease，production composition 預設
  300 秒 lease／60 秒 renew。
- Worker renew failure、非 `Exception` 的 thread termination、dead worker、session
  read-back drift、release failure與 join timeout都先把 keepalive state 設為
  `demoted` 並關閉 current-lease gate。Stop 也先進 `stopping` 再等待 remote release；
  即使 RPC 卡住，正式 caller 已無法取得 lease。Status 不含 raw fencing token，只暴露
  authority identity、renewal count、last renewed expiry、worker liveness與 exception
  type。
- Start 的 remote acquire、renew worker publication 與 `running` gate 現在位於同一個
  process-lock transition。並行 starter 只能取得同一 lease／同一 worker；並行 stop
  必須等這個 transition 落定後再關 gate，不能在 acquire 尚未返回時先報完成，隨後又被
  starter 重開。
- 新 unit／concurrency cases覆蓋 renew、clean stop、renew failure、`BaseException`、
  release response lost、blocked-renew stop timeout、invalid renewal margin、
  concurrent start／stop、environment composition與 token redaction；連同
  session／Supabase adapter共 24 passed。Production no-effect rehearsal讓 A host
  renew 一次並 release，B host
  以同一 key 接管；epoch 精確 `1 → 2`，兩個 release refs 都由 DB transaction回傳，
  final state 都是 `stopped`。
- 這個週期性 keepalive owner 缺口為
  `root_cause_fixed_and_verified`。尚未完成的是全 effect-family enable gate、真實
  雙 Mac network partition、Supabase outage與五分鐘 RTO rehearsal，因此 program
  commit 34 整體仍是 `contained`。

### 2026-07-25 live Supabase outage／RTO rehearsal checkpoint

- `scripts/rehearse_primary_authority_outage.py` 將 production outage演練收進
  fail-closed operator seam。CLI只接受自動產生的
  `operations-core-outage-smoke-*` authority key，先驗 publisher owner為預期的
  `operations_core/8`，且整個模組不組裝 authorize、outbox、provider或settlement
  interface。Authority store在一次 healthy renew後切到實際不可達的
  `127.0.0.1:1` PostgREST transport；standby在transport恢復後仍須等待DB-clock
  lease到期，不能靠local state繞過remote fence。
- 正式live run採production composition的300秒lease／60秒renew。Primary健康renew
  後的 expiry為`2026-07-24T17:27:27.770913+00:00`；renew transport中斷後
  `HostAuthorityKeepalive`在60.526秒內demote且`current_lease()` fail closed。
  Standby在239.962秒內取得exact next epoch `1 → 2`，其後release receipt使final
  state=`stopped`。Receipt回讀successful claims=2、duplicate claims=0、
  effect requests=0、provider calls=0。
- Durable evidence由CLI原子寫入
  `storage/ops/primary_authority_outage_rehearsal_latest.json`並exact JSON
  read-back；publisher fence在演練前後都是同一
  `publisher.article.supabase.sync=operations_core/8`。相鄰authority suite共
  28 passed，compileall與diff check通過。
- 這個live Supabase renewal-outage／五分鐘RTO operator seam為
  `root_cause_fixed_and_verified`。兩個session仍在同一台Mac process內；真正跨兩台
  實體Mac的network partition與其餘effect-family cutover尚未完成，因此program
  commit 34與operations-core umbrella保持`contained`。
- 後續將同一 seam 深化為明確的`primary`／`standby` process roles與
  `verify-pair`：shared rehearsal ID決定性導出隔離key，receipt記錄hash過的machine
  fingerprint與implementation SHA-256，配對時綁定兩份receipt SHA-256並驗distinct
  machine、相同code、exact next epoch、DB-clock expiry後300秒內handoff、固定
  publisher fence及零effect/provider。
  failure-injection regression也把原先「state先demoted、worker稍後退出」的觀測競態
  改成兩個條件同時成立才接受。6個interface cases、compileall與diff check通過；
  真正雙Mac receipt pair仍待operator執行，umbrella狀態不變。

### 2026-07-24 generic effect-worker keepalive gate checkpoint

- 原本的 `EffectWorkerCommand` 讓 caller 直接提供 authority key、holder、epoch 與 raw
  fencing token；即使 host keepalive 已 demote，caller 仍可用記憶體中的舊欄位先 claim
  outbox，再走到 database authority check。這使 `HostAuthorityKeepalive` 只是可選
  helper，不是 Effect Delivery 的實際 enable gate。
- `EffectOutboxWorker` 現在依賴一個內部 lease-gate seam，public command 只剩 worker
  identity 與 outbox lease duration。Worker 會在 claim 前、authority grant 前與
  provider 前呼叫 `current_lease()`；錯誤 authority family、closed gate、epoch／token
  replacement都在外部 provider 前 fail closed。Renew 造成的 expiry 延長仍視為同一
  identity，不會阻擋正常長駐 worker。
- Email notification 與 publisher article sync 兩個 provider adapters 都經相同 worker
  interface 驗證；failure injection 證明 gate 在三個 checkpoint 任一處關閉時 provider
  呼叫為 0，command／receipt 不含 raw token。Authority、Effect Delivery 與 PG17
  相鄰套件共 88 passed。
- 這個 generic outbox worker interface 根因為
  `root_cause_fixed_and_verified`。Production `email.ops_alert` 的深層 ownership RPC
  仍自行 acquire `notification:email.ops_alert` lease，尚未 revalidate host keepalive
  lease；其他 effect family 也未逐一接管。因此「全 effect-family enable gate」與
  program commit 34 umbrella 仍為 `contained`。
- 後續 public-interface regression 證實上述「provider 前」回讀仍早了一個真正的
  external boundary：durable payload reader 可在回傳 bytes 前阻塞，期間 keepalive
  demote，但 worker 原先不會再回讀就呼叫 provider。現在 valid payload 通過
  EffectRequest SHA-256 後會立即重驗同一 lease identity；payload-read demotion 轉為
  typed `EffectWorkerBlocked`，provider 與 settlement 均不執行。Email、publisher 與
  PostgreSQL 相鄰套件 68 passed；此 race 為
  `root_cause_fixed_and_verified`，program commit 34 umbrella 仍因真實 outage／RTO
  rehearsal 與其餘 family cutover 未完成而保持 `contained`。

### 2026-07-24 owned email production keepalive gate checkpoint

- `OwnedEmailNotification` 現在依賴 live lease gate，不再由 token factory產生
  Primary Authority token。它在 durable request前、begin前與 provider前回讀同一
  `notification:email.ops_alert` holder／epoch／token identity；gate關閉、family
  不符、lease replacement或 begin RPC回傳另一個 authority identity，都在 SMTP
  provider前 fail closed。
- Production caller啟動 `HostAuthorityKeepalive` 後才進 owned transaction，並以
  `finally` stop。Migration
  `20260724131707_operations_core_owned_email_keepalive_gate.sql` 保留 public RPC
  signature，但 begin只讀既有未過期 lease，再由 `authorize_effect_write` 驗 raw
  token；settlement不再 release，避免在 keepalive背後清掉 remote lease。
- PG17 contract覆蓋無 host lease的 transaction rollback、預持 lease後完整 delivery、
  settlement後 lease仍存續及 host explicit release；unit failure injection另覆蓋
  closed gate與 epoch／token replacement，provider call均為 0。Production migration
  receipt為 `20260724131707 operations_core_owned_email_keepalive_gate`；live
  function-definition／owner／ACL／search-path、notification owner與 live lease均已回讀，
  未寄信、未做 owner transfer。
- 此 `email.ops_alert` family enable-gate缺口為
  `root_cause_fixed_and_verified`。兩筆歷史 `started` attempt均早已 lease-expired，
  live attempt=0；其 reconciliation不在本 slice內。其他 effect family、真實雙 Mac
  network partition、Supabase outage與五分鐘 RTO rehearsal仍缺，因此 program
  commit 34 umbrella保持 `contained`。

### 2026-07-24 effect-family transactional routing checkpoint

- Generic outbox 原本只有 `(worker_id, lease_seconds, token)` 三參數 claim；它按時間
  認領全域最舊 effect，完全不知道注入 worker 的 narrow provider 支援哪些
  `effect_kind`。第二個 provider family 上線後，publisher worker可能先拿到 email
  effect，再由 provider把合法他族 intent當 unsupported contract dead-letter。這是
  routing transaction 的能力資訊缺失，不是 provider validation 問題。
- `EffectProvider` 現在必須宣告 non-empty normalized `effect_kinds`；worker只把該
  capability set傳入 durable claim，並在 store回傳 EffectRequest後再做一次
  defense-in-depth family check。錯 family在 payload read／authority grant／external
  provider之前 fail closed，不能被錯誤結案。
- Forward migration
  `20260724134742_operations_core_effect_family_routing.sql` 移除舊三參數 RPC，
  新 claim在同一 `SKIP LOCKED` transaction join EffectRequest並以
  `effect_kind = ANY(...)` 篩選。PG17 clean／idempotent replay實際用「email先入列、
  publisher後入列」證明兩個 worker各自拿到正確 row；owner、fixed search path、
  worker-only execute、PUBLIC deny與 routing index也由 contract鎖住。
- Production migration receipt為
  `20260724134742 operations_core_effect_family_routing`。Live catalog回讀確認舊
  unfiltered signature不存在、新 function由 `volpred_ops_definer`持有且 family filter
  在 definition內；當下 email outbox有 2 pending、2 expired claimed、0 active claim，
  本次只讀、沒有 claim或 provider call。三個相鄰套件共 67 passed，Supabase advisor
  沒有此 function的新 scope finding。
- 這個 cross-family誤認領根因為 `root_cause_fixed_and_verified`。Publisher仍缺
  durable payload／WorkItem／EffectRequest正式 caller、production HTTP adapters與
  owner cutover；真實雙 Mac network partition、Supabase outage及五分鐘 RTO rehearsal
  也未完成，所以 program commit 14／34 umbrella皆維持 `contained`。

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

### 2026-07-24 durable payload／Primary Authority checkpoint

- `PostgresEffectPayloadStore` 透過 private named functions 寫入 immutable payload
  bytes；資料庫重算 SHA-256，既有 ref 只能等價 replay。worker 在 provider 前再次
  重算 hash，任何 storage drift 都以 terminal
  `effect_payload_integrity_mismatch` settlement，provider 不會被呼叫。
- `PostgresAuthorityStore` 以 database clock 取得／續租／釋放 Primary Authority
  lease，epoch 單調遞增，raw fencing token 只以 SHA-256 保存。
  `PostgresEffectAuthority.authorize` 在單一 database function 內同時鎖定並核對
  Primary Authority lease 與 exact outbox claim，綁定 EffectRequest、WorkItem、
  payload、provider contract 與 acknowledgement identity。
- Database-issued effect grant 是 settlement 的必要前置證據；trigger 會拒絕不存在、
  已漂移或屬於另一個 attempt 的 authority refs。這取代先前「任意非空 reference」
  就能 settlement 的假 authority seam。
- 新 private tables 全部 FORCE RLS；SECURITY DEFINER functions 固定 `search_path`、
  revoke PUBLIC、由 no-login definer 擁有，worker 只取得所需 named functions。
  Immutable payload trigger 不再使用 `FOR KEY SHARE`：在 FORCE RLS 下那會額外要求
  UPDATE policy，使 SELECT-only definer 產生假 `unknown payload`；payload 不可更新，
  因此移除 row lock 才是正確 contract。
- Canonical migration 在本機 PostgreSQL 17 non-superuser fixture 重播兩次；
  Supabase migration API 的 remote receipt
  `20260723230547 operations_core_effect_payload_primary_authority` 由同名 no-op local
  receipt stub 對齊，較晚的 canonical migration 保持完整且冪等供乾淨環境使用。
  Live read-back 確認五表 FORCE RLS、最小 grants、definer owner／fixed search path
  與兩個 index；`volpred_ops` security advisor 0 lint，performance advisor 只有
  10 個 unused-index INFO。既有八筆舊 migration-history drift 未做 repair。
- Payload／authority 具體 seam 已完成底層修復、PG17 回歸、live read-back 與制度化；
  但尚無正式 Work Coordinator caller、production ownership transaction、
  unique-owner acknowledgement read-back 或 rollback rehearsal，所以 program commit
  13／notification ownership 仍是 `contained`。

### 2026-07-24 production ops-alert ownership checkpoint

- 正式 caller 是 `volpred.ops.alerts.send_alert` 的 email branch。它先透過
  `SupabaseOwnedEmailStore.read_owner()` 讀取 PostgreSQL 的唯一 owner generation；
  DB 不可用或 effect family 漂移即 fail closed，不會為了「先寄出去」偷偷 fallback。
  `legacy` generation 才可呼叫既有 notifier；`operations_core` generation 只能進
  `OwnedEmailNotification.deliver()`。
- `OwnedEmailNotification` 是單一 deep interface：caller 只給 idempotency key、
  severity、subject/body、recipient 與 actor。其 store 的 request RPC 在一個
  transaction 建立 WorkItem、immutable payload、EffectRequest／outbox 與 owned
  request receipt；begin RPC 同時取得 Work lease、outbox claim、Primary Authority
  與 effect grant；settle RPC 原子寫 effect／Work receipts、釋放 authority 並完成
  owned attempt。Caller 不持有 table mutation 能力，也不組裝半套 transaction。
- Ownership transfer 使用 owner + monotonic generation 的 CAS。轉移前必須零 active
  attempts；等價 retry 回傳原 receipt，競爭或漂移欄位 fail closed。Rollback 到
  `legacy` 必須精確帶當前 generation 作 `rollback_of_generation`，因此 rollback
  本身也是 durable、可稽核的 ownership event。
- 四張 ownership tables 位於 private `volpred_ops` 且 FORCE RLS。五個 PostgREST
  RPC 只授權 `service_role`，PUBLIC／anon／authenticated 全撤銷；function owner 是
  no-login definer、`search_path=''`，definer 的 public CREATE 在 migration 結束前
  撤銷。PG17 non-superuser fixture 覆蓋 migration replay、privilege shape 與完整
  cutover→delivery→rollback→recutover transaction。
- 第一次 live caller 已正確 fail closed 為
  `email_sent_mail_readback_mismatch`。Durable payload hash 沒有漂移；獨立比對 Gmail
  raw MIME 證明唯一差異是 SMTP 把 LF 正規化成 CRLF，而 read-back verifier 只移除尾端
  newline。底層修成比較前將 CRLF／CR canonicalize 為 LF，測試 mailbox 改用 SMTP
  policy，避免測試環境再次遮住 wire-format 差異。
- 第二個唯一 idempotency key 的 live alert 完整 delivered，DB payload hash、Work／
  effect／outbox／attempt receipt、Primary Authority release receipt 與 Gmail Sent
  exact-byte SHA-256 全部回讀一致。接著完成
  `operations_core/2 → legacy/3 → operations_core/4` rehearsal；舊 generation
  request 被拒且未落 row，final state 為唯一 owner `operations_core/4`、零 active
  attempts。Security advisor 沒有本 scope lint；performance advisor 的 ownership
  FK 缺 index 已補，剩餘只有新 index 尚未累積使用統計的 INFO。
- 因而 `email.ops_alert` 的正式 caller、production ownership transaction、
  unique-owner live acknowledgement 與 rollback rehearsal 四項 gate 均為
  `root_cause_fixed_and_verified`。其他 notification family 不在這次 cutover scope。
- 2026-07-24 08:07 CST 的 Codex failover read-only 複驗再次從 production owner
  interface 回讀 `notification-owner.v1`：effect family=`email.ops_alert`、
  owner=`operations_core`、generation=`4`、changed_at=
  `2026-07-23T23:48:57.414826+00:00`；同班 caller／owned delivery／Sent read-back
  scoped suite 為 `85 passed`。複驗沒有寄信或改 owner，且不擴張上述完成範圍。

### 2026-07-24 publisher 單篇 Supabase sync shadow checkpoint

- program commit 14 的第一個垂直切片建立
  `PublisherArticleSyncEffectAdapter` external interface，只接受
  `publisher.article.supabase.sync`／`safe`／單一 slug 與完全相同的
  `publisher.article.supabase.readback` target。payload 以 canonical JSON 綁定完整
  feed article；hash、schema、slug 或 acknowledgement 漂移都在 projection write 前
  terminal fail closed。
- provider 在 upsert 前先做完整 projection read-back。已收斂的等價 replay 直接回傳
  acknowledgement，不再重複寫；需要寫入時，只有文章 row（含 content／details／
  audience／category／phase 等）與 tags 都回讀一致才算成功。時區等價的
  `published_at` 先正規化，`view_display` 等 server-resident details key 不被誤判成
  canonical drift。
- `SupabaseArticleProjectionAdapter` 是 production adapter；測試使用 in-memory
  fake adapter，兩者跨越同一 internal seam。既有 `sync_article()` 的 row 組裝抽成
  `projected_article_row()`，direct writer、hourly differ 與 effect read-back 不再各自
  推理 projection shape。
- duplicate replay、provider failure、invalid intent、post-write mismatch、worker
  terminal dead-letter、production-shaped row／tag read-back與 explicit empty-tag
  convergence 共 9 個新 cases 通過；publisher／Supabase sync／feed-sync／
  Effect Delivery worker 的 scoped 相鄰回歸為 `193 passed, 1 skipped`。
- 2026-07-24 09:13 CST 的 read-only live smoke 從 canonical feed 只取最新 published
  article `mile_f00be77f`，再由 production Supabase adapter 回讀完整 row／tags；
  `matches=true`，evidence SHA-256 =
  `faf3920540be40ad90ab7d8e2392be39d52cd9e38eda5f896dca31a2699ee3de`。
  本 smoke 沒有 upsert、cache purge、owner transfer 或其他外部寫入。
- 本切片尚未建立 publisher WorkItem／EffectRequest 的正式 caller、payload durable
  writer、Primary Authority family、single-owner transaction 或 live cutover receipt；
  現行 `/api/sync/reports/<slug>.json` 與 direct `sync_article()` caller 都未移除。

### 2026-07-24 publisher formal caller contract checkpoint

- `OwnedPublisherArticleSync.sync()` 現在是 program commit 14 的單一 external
  interface。caller 只提供 immutable article、idempotency key 與 actor；owner
  generation 回讀、durable request、Work／outbox claim token、family Primary
  Authority keepalive、provider read-back 與 settlement 全藏在 implementation。
- private store seam 有 fake 與 `SupabaseOwnedPublisherArticleStore` 兩個 adapters；
  production adapter 只接受 `SUPABASE_SERVICE_ROLE_KEY`，不會 fallback 到 publishable
  key。owner transfer interface 是 generation CAS，rollback 必須攜帶
  `rollback_of_generation`；對應 RPC 名稱與 payload shape 已鎖成 caller contract。
- formal caller 在 request 前、begin 前與 provider 前重驗同一
  `publisher:article.supabase.sync` lease；begin 若漂移 Work／Effect identity、owner
  generation 或 authority identity，外部 projection write 為零。new caller／provider／
  generic Effect Delivery／owned email 相鄰 suite 共 `171 passed`。
- 本 checkpoint 尚未提供四個 service-role RPC 的 PostgreSQL implementation，也沒有
  將任何現有 publisher write path 路由到新 interface；production owner row、CAS
  cutover、live acknowledgement 與 rollback rehearsal 都未執行。因此 live 行為不變，
  program commit 14 仍為 **`contained`**，不是 publisher sync ownership 完成。

### 2026-07-24 publisher ownership transaction checkpoint

- PostgreSQL migration 現在提供 service-role-only owner read／generation-CAS transfer、
  durable request、begin 與 settlement 五個 RPC，並預置唯一
  `publisher.article.supabase.sync=legacy/1` owner row。local PostgreSQL 17 fixture
  會重播完整 migration chain，驗證 cutover、delivery acknowledgement、active-attempt
  transfer rejection、rollback、stale-generation rejection 與 recutover。
- 獨立複驗曾抓到 settlement 從 token-redacted
  `primary_authority_lease_reads` 讀取不存在的 `fencing_token_sha256`；migration 已改為
  由 SECURITY DEFINER 直接鎖 private `primary_authority_leases`，保留 raw fencing token
  hash 驗證。security-shape regression 現在同時要求 begin 只能讀 redacted view、settle
  必須讀 private table 且核對 `fencing_token_sha256`，防止兩種 authority surface 再次
  靜默互換。PostgreSQL suite 為 `45 passed`，owned publisher／email 相鄰 suite 為
  `10 passed`。
- 本 checkpoint 仍未套用 production migration、轉移 live owner、路由現有 writer 或
  執行 live acknowledgement／rollback rehearsal；因此只標 **`contained`**。

### 2026-07-24 publisher production schema、owner routing 與 terminal replay checkpoint

- Production 已套用
  `20260724151111 operations_core_publisher_article_ownership` 與
  `20260724152359 operations_core_publisher_article_terminal_replay`。五個 public RPC
  由 no-login definer 持有、固定空 search path，只有 service role可執行；四張
  ownership／request／attempt private tables均 FORCE RLS，service role沒有 direct
  SELECT，definer也沒有殘留 public schema CREATE。
- Request RPC現在隱藏 terminal-replay recovery：若相同 idempotency key對應的 attempt
  已是 `delivered` 或 `dead_lettered`，同一 transaction組回
  `owned-publisher-article-receipt.v1`。`OwnedPublisherArticleSync.sync()`驗證 receipt
  的 owner generation／Work／Effect identity後直接返回，不重新 begin，也不呼叫
  provider。PG17完整 cutover案例實際 settlement後重播，receipt完全相同且 attempt
  count仍為 1；caller unit case確認 projection calls為 0。
- `scripts/supabase_sync.sync_article()`是現行 writer的 database-owner router：
  `legacy`只進既有 `sync_article_projection()`，`operations_core`才啟動
  `publisher:article.supabase.sync` keepalive並呼叫 formal interface；錯誤 family或
  未知 owner fail closed。Production provider adapter只呼叫 projection implementation，
  不會遞迴回 owner router。
- Active frontend repo commit `ae14890`也讀同一 owner RPC。部署後 full `feed.json`
  route在 operations-core generation回 409，single-report route只回 delegated；
  兩條路徑都不再 upsert article。該 repo目前仍比 `origin/main` ahead 9 commits，
  本輪未被授權 push，所以此 fence尚未部署。
- Production owner回讀保持 `legacy/1`，publisher request／active attempt／Primary
  Authority lease均為 0，沒有文章 write或 owner mutation。PG17 `45 passed`、
  caller／adapter `22 passed`、frontend typecheck通過；security advisor對本 scope為
  0 finding。正式 CAS、unique-owner article acknowledgement與rollback rehearsal
  必須等 frontend部署與live version回讀，故 program commit 14仍是
  **`contained`**。
- Formal caller不把 service-role response視為 acknowledgement：
  settlement後逐欄核對 receipt schema、owner generation、Work／Effect／attempt、
  Primary Authority ref與 provider evidence，並要求
  `delivered → succeeded/delivered`、
  `retry_scheduled → pending/requested`、
  `dead_lettered → failed/dead_lettered`。Terminal replay同樣驗證 terminal lifecycle
  tuple；任何漂移都回 `PublisherArticleSyncOwnershipLost`，不能被上游誤認成成功。
  RED injections原先兩次均未 raise，修正後連同 publisher／PostgreSQL相鄰套件共
  **69 passed**，且未執行 remote write或 owner mutation。

### 2026-07-25 publisher production ownership closure

- Active frontend `ae14890` 從 clean detached worktree 經
  `frontend-v2-fix/scripts/deploy-zeabur-safe.sh` 上傳到 canonical `volpred-v3`；
  Zeabur deployment `6a6393ea4727f1da77de7137` 為 `RUNNING`，部署腳本對
  production feed／strategy API 的下游回讀都通過。Active checkout 內既有的
  package／PDF／test 變更沒有進 deployment。
- Generation 6 的 live fence read-back 得到 full-feed
  `409 operations_core_owns_publisher_article_sync` 與 single-report
  `delegated/operations_core/6`。Canonical published single-report
  `crisis_protection_20260316_002220` 經 database-owner router與 formal caller
  產生 `work_owned_publisher_110068f9062bfe12d5a501935f1a631c`／
  `effect_owned_publisher_110068f9062bfe12d5a501935f1a631c`；durable terminal
  receipt為 attempt 1、`succeeded/delivered`，provider evidence ref
  `supabase:articles/crisis_protection_20260316_002220`，SHA-256
  `9ecceb0468f16bec17b2e0a418db4a4ae4c512850c1e39723122996ef33bcbe1`。
- Exact generation-CAS rollback回到 `legacy/7`，再正式 recutover到
  `operations_core/8`。Generation 7 stale transfer 被 production RPC拒絕；final
  owner與 generation 8 的兩條 live route fence均已回讀。前兩次 operator-script
  preflight／receipt呈現錯誤也都在 exception path自動回到 legacy，沒有留下雙 owner；
  第一案在 article input前、第二案在 terminal receipt後，後者的 projection write為
  同一 canonical article的冪等 upsert。
- 新增 `scripts/rehearse_publisher_cutover.py` 作唯一 operator rehearsal seam：
  article存在性、path-safe slug、published status都在 CAS前驗證；空 full-feed 先證明
  409，才以完整 canonical article驗 single-report delegated；delivery receipt直接
  由 typed dataclass序列化。任何 cutover後例外都在 `finally` 以目前 generation做
  exact rollback。四個 regression cases覆蓋 mutation前 preflight、成功 rollback、
  live-probe failure與 receipt generation drift。
- 以上完成 program commit 14 的 production deployment、唯一 owner fence、
  acknowledged single-article effect、exact rollback、stale-generation refusal與
  final recutover，狀態為 **`root_cause_fixed_and_verified`**。Program commit 34
  的真實 network-partition／Supabase outage／五分鐘 RTO，以及其他 operations-core
  umbrella slices不由此結案。

### 2026-07-25 full-sync acknowledgement cursor checkpoint

- Program commit 15 前置盤點發現 legacy `sync_full()` 把 provider 回傳的 `False`
  當成已完成：article write失敗仍推進 `feed_mtime`，memory write失敗仍把 count cursor
  推到檔尾，risk write失敗仍回報 1；CLI 只針對 cache purge失敗回非零。因此單次
  transport/provider失敗會被本地 cursor覆蓋，下一輪 unchanged run不再碰到那筆
  未落地 projection。
- Article path現在保存 `article_retry_slugs`，失敗時不推進 feed gate；即使本輪是由
  另一個 purge retry打開 gate，provider失敗的 slug仍是下一輪顯式輸入。既有
  `purge_retry_slugs`只有在 prerequisite projection write成功後才能清除。Memory count
  定義改為「下游已確認的連續前綴」，遇到第一個洞便停止；risk與delete reconcile也
  進入同一 typed failure list。`_report_counts()`只要有任何 projection failure就
  非零退出，不再印假 `Done.`。
- 四個 failure injections在修正前得到 4 failed；修正後 article retry、purge
  dependency、memory contiguous cursor、risk exit contract與相鄰 reconcile/cache
  套件在 clean tracked snapshot共 **31 passed, 1 skipped**。這個 silent cursor advancement根因為
  **`root_cause_fixed_and_verified`**。Program commit 15 的 formal EffectRequest／
  outbox ownership、週期 projection-convergence receipt與 rollback rehearsal尚未
  完成，因此 commit 15與 operations-core umbrella仍為 **`contained`**。

### 2026-07-25 projection convergence orphan checkpoint

- Hourly `audit_publish_sync.py` 雖宣稱比較 local、Supabase與live route，Supabase query
  卻只要求 local feed已知的 slug；因此 remote-only published row不可能進入結果，
  「orphan」surface實際永遠是假陰性。Local視窗為空時更直接跳過 remote query，
  receipt仍可標 converged。
- Convergence receipt v2改以相同72小時 `published_at`視窗讀取完整 published
  projection；PostgREST read以exact count與Range分頁到完整視窗，再雙向計算
  `missing_supabase`與`orphan_supabase`。即使 local set為空也必須觀測 remote。
  任何 credential、transport或response-shape failure維持 unavailable，不能被空集合
  冒充。Mismatch total與alert亦納入 orphan。
- 兩個新 failure injections覆蓋 remote-only row與空 local視窗，URL contract另驗
  published status／window filter且不再出現 local slug `in`限制；audit與schedule
  scoped suite共 **11 passed**。Production read-only smoke用臨時 receipt回讀
  v2 `converged`，local=14、Supabase=14、missing=0、orphan=0、live 404=0、
  observation error=0。此 false-convergence根因為
  **`root_cause_fixed_and_verified`**；program commit 15的週期 convergence receipt
  gate已完成，formal outbox ownership與 rollback rehearsal仍缺，故整體維持
  **`contained`**。

### 2026-07-25 hourly feed-sync acknowledgement checkpoint

- Scheduled `feed-sync --apply` 原本雖從 per-article Operations Core caller收到
  `failed=1`，CLI仍一律 exit 0；wrapper正確傳遞這個錯誤的 code，造成 cron
  receipt false-green。這是最外層 acknowledgement seam缺失，不是 provider或
  outbox沒有回報。
- `sync_feed_to_supabase()`現在以單一 top-level `acknowledged`隱藏 nested counters：
  apply只有全部 effect確認時為true，dry-run為 `None`。CLI在輸出 evidence後要求
  apply acknowledgement明確為true，否則 exit 1；quiet clean仍安靜 exit 0。
  Canonical schedule登記同一 0／1語意，wrapper regression固定 exit code不被吞掉。
- Failure injection由 exit 0轉1；本切片與 feed diff、full-sync cursor、publisher
  ownership／effect相鄰套件共 **69 passed**。Production read-only dry-run回讀
  feed/db均1877、三種 drift均0，host wrapper lockstep。此 scheduler false-green根因
  為 **`root_cause_fixed_and_verified`**；full-sync formal outbox ownership與rollback
  rehearsal仍缺，故 program commit 15保持 **`contained`**。

### 2026-07-25 immutable reconcile EffectRequest checkpoint

- Safe full-feed reconcile現在有一個小型 external interface：
  `prepare_publisher_article_reconcile(...) -> PreparedPublisherArticleReconcile`。
  Interface隱藏 effect kind、target、risk、acknowledgement與payload hash；implementation
  將 canonical feed SHA-256及本次需upsert的完整 article objects綁入immutable payload，
  slug必須唯一且canonical排序。Worker retry不再有機會從後來已變動的`feed.json`
  重建另一個 batch intent。
- `PublisherArticleReconcileEffectAdapter`沿用已有 production／fake article
  projection adapters這個真 seam：先逐篇read-back、只upsert mismatch、再逐篇exact
  read-back。等價 replay為零寫入；payload hash、schema、target或safe-risk漂移為
  non-retryable，經generic durable worker落dead letter；provider與read-back錯誤為
  retryable。Destructive delete不混入此effect family，保留獨立權限與rollback設計。
- 八個新 public-interface cases連同single-article provider及effect worker相鄰套件為
  **36 passed**。Production adapter只讀回
  `supabase:articles/mile_30b22ca5`，projection完全相符，evidence SHA-256為
  `b8b20a3bddd6c5035f821ac0572f38b1c6785b83e2b51d6658f6837289e6dff6`；未執行
  remote write、owner transfer或live effect。
- 這完成 formal EffectRequest／provider contract的shadow切片，不等於production
  ownership cutover。Hourly producer尚未寫入production payload store／outbox，
  family owner CAS、destructive delete effect與exact rollback rehearsal仍缺；因此
  program commit 15與operations-core umbrella維持 **`contained`**。

### 2026-07-25 publisher safe reconcile production ownership closure

- External interface維持單一
  `OwnedPublisherArticleReconcile.reconcile(command)`；caller只提供idempotency、
  Work identity、canonical feed SHA與完整article objects。Supabase adapter隱藏private
  payload store、WorkItem、EffectRequest/outbox、owner fence、primary-authority lease、
  attempt與receipt transaction，避免hourly caller自行拼湊effect contract。
- `feed_sync.apply_diff()`只在有safe upsert時讀family owner。Legacy generation走既有
  per-article formal caller；Operations Core generation把整批immutable intent只提交
  一次；article objects與canonical feed SHA取自同一份byte snapshot，並行改稿不能
  拼出舊objects／新hash。Begin要求owner generation與active primary lease完全相符；settle要求同一
  owner、work、outbox與authority receipt，terminal replay只接受exact identity。
  Destructive delete刻意維持獨立guarded seam，不借用safe權限。
- Production migration將五個RPC設為service-role-only、`SECURITY DEFINER`且空
  `search_path`；private tables不開direct service-role access。Live operator rehearsal
  完成`legacy/1 → operations_core/2 → legacy/3 rollback → operations_core/4`，
  回讀WorkItem succeeded、Effect/outbox delivered、attempt acknowledged，
  local/Supabase均14且drift=0；schedule-equivalent hourly command再以exit 0收尾。
  最終tracked-snapshot selected suite **91 passed**，其中包含完整47-case
  PostgreSQL contract檔。
- 因此safe reconcile production ownership切片是
  **`root_cause_fixed_and_verified`**。Program commit 15仍缺獨立destructive delete
  EffectRequest／owner／rollback；program commit 34的physical two-Mac receipt也不在
  本切片，故兩個較大範圍仍標 **`contained`**。

### 2026-07-25 publisher mutation-boundary authority checkpoint

- Post-cutover failure injection發現single-article與batch formal callers雖在
  `begin`後、進provider前回讀同一
  Primary Authority epoch，provider卻先做一次true-external Supabase read-back再
  upsert。若read-back阻塞期間keepalive被demote或另一host接管，舊attempt原本仍會在
  已失效的epoch下執行upsert，直到settlement才可能被database fence拒絕；這時外部
  mutation已經發生。
- 兩個owned callers現在都把原始lease identity綁成mutation authorizer；single與batch
  adapters在每一筆真正需要upsert的article、且緊貼provider write前重讀authority。
  Authority key、holder、epoch、fencing token或acquired-at任一漂移都直接拋出
  ownership loss；不轉成provider retry、不settle舊attempt。已完全收斂的零寫入
  replay不要求額外write authority。
- 兩條failure injections都在第一次read-back後替換epoch與token，回讀projection
  write=0、settlement=0；owned callers、effect adapters、兩套operator rehearsals、
  feed sync與CLI相鄰套件共 **82 passed**，compileall與`git diff --check`通過。此external-boundary
  fencing根因為 **`root_cause_fixed_and_verified`**。Destructive delete仍缺獨立
  EffectRequest／owner／rollback，因此program commit 15與operations-core umbrella
  仍為 **`contained`**。

### 2026-07-25 publisher destructive delete intent checkpoint

- Delete維持與safe reconcile不同的interface與權限。新的兩段式deep module先以
  `plan_publisher_article_delete(...)`凍結exact canonical feed bytes、floor／cap、
  完整remote article rows與所有cascade-affected rows，再由
  `prepare_publisher_article_delete(...)`要求scope-bound explicit approval，才產生
  risk=`destructive`的EffectRequest。Caller不再自行拼effect kind、target、
  acknowledgement或recovery digest。
- Plan要求每個candidate不在canonical feed，slug／article id皆唯一，且
  article_impressions、article_reactions、article_relations、article_tags、comments、
  question_articles六個table／七條FK edge必須完整出現；一般dependent row的
  `article_id`、relations的`source_id`或`target_id`須綁回candidate。Module自行產生
  deterministic JSONL recovery artifact，scope同時綁定
  canonical feed SHA、guard values、candidate bytes及recovery ref／SHA。
- Authorization保存opaque approval ref、approver、timezone-aware timestamp與scope
  SHA；任何scope漂移都在EffectRequest前fail closed，approval內容漂移也不能重用原
  idempotency key。Module沒有provider adapter或hourly caller，故此checkpoint沒有
  remote mutation，也不把destructive authority交給無人值守safe job。
- Contract、Effect Delivery、safe reconcile、legacy delete與feed-sync相鄰套件共
  **156 passed**；
  compileall及`git diff --check`通過。本切片仍為 **`contained`**：獨立owner CAS、
  durable approval verifier、provider delete/read-back、mutation-boundary authority、
  exact restore executor與live rollback/convergence rehearsal尚未完成，program commit
  15及operations-core umbrella狀態不變。

### 2026-07-25 publisher destructive recovery graph checkpoint

- Production catalog證實`articles`目前有六張child table、七條
  `ON DELETE CASCADE` edge；intent初版漏掉
  `article_relations.source_id/target_id`，legacy recovery則只保存部分article欄位與
  impressions。兩者原本都不能支持「完整rollback」宣稱。
- Cascade column contract現在由delete intent module單一持有，shadow plan與legacy
  runtime共用。Legacy apply在任何DELETE前以service-role-only RPC比對live catalog，
  完整讀回article與六張child table，並把exact feed SHA、recovery v2 bytes及dump
  SHA綁在同一capture。RPC／child read／fsync read-back失敗或feed generation漂移一律
  零刪除；新增FK若未先擴充recovery，也會被catalog drift gate擋住。
- Migration已套production；function owner、SECURITY DEFINER、空search path及
  service-role-only ACL逐欄回讀。RPC得到七條edge，與code exact match；read-only
  reconcile回讀local=1877、remote=1877、ghost=0、deleted=0；相鄰套件
  **200 passed, 1 skipped**。此不完整recovery根因為
  **`root_cause_fixed_and_verified`**；owner CAS、provider delete/read-back、restore
  executor與live rollback rehearsal仍缺，program commit 15與umbrella維持
  **`contained`**。

### 2026-07-25 publisher destructive execution adapter checkpoint

- Immutable delete intent先前只證明scope與approval bytes已綁定，worker仍沒有可安全
  執行destructive EffectRequest的interface。新增
  `PublisherArticleDeleteEffectAdapter`，把durable approval read-back、完整candidate
  與六表cascade read-back、delete compare-and-mutate及typed absence acknowledgement
  收在同一個effect family adapter；payload hash、risk、target與acknowledgement任一
  漂移均在provider I/O前terminal fail closed。
- Adapter先重驗scope-bound approval，再把**全部**candidate做exact preflight，確保
  第二筆scope drift時第一筆也不會先刪。每筆真正mutation前再讀一次完整candidate，
  重驗durable approval，並由owned caller緊貼delete重驗原Primary Authority epoch。
  Projection interface的delete語意是atomic compare完整article/cascade bytes後刪除；
  authority replacement直接向外拋ownership loss，不會被包成provider retry或settle
  stale attempt。
- Replay只有在每筆都回傳typed absence且evidence ref/hash合法時才acknowledge；delete
  回true但read-back仍存在會成為retryable absence mismatch。Failure injections覆蓋
  全scope preflight、approval撤回、authority換代零mutation、已刪除replay與缺absence
  acknowledgement；delete contract及Effect/reconcile/Supabase相鄰套件
  **127 passed**。這個worker execution-contract根因為
  **`root_cause_fixed_and_verified`**；production Supabase projection、owner CAS、
  exact restore executor及live delete→rollback→convergence rehearsal仍缺，故program
  commit 15與umbrella維持 **`contained`**。

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
  Projection schema 必須精確等於 production compatibility contract
  `next-tasks-read-projection.v1`；未知 schema 即使產生相同 payload 也拒絕。
  Row count／SHA 由 payload 重算。Manifest v2 以 canonical JSON 綁定 raw
  legacy snapshot、canonical assessment、derived import report、validated projection
  schema 與 owner-state 五個 SHA-256 identity；assessment 額外綁定 canonical receipt-set
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

## 15. Publisher destructive delete production ownership（2026-07-25）

`publisher.article.supabase.delete` 現在是獨立於 hourly safe reconcile 的 destructive
family。`OwnedPublisherArticleDelete.delete()` 是正式 caller：先回讀 generation-CAS
owner，再以 private payload 建立 WorkItem、EffectRequest/outbox 與 attempt，provider
則由 attempt-bound factory 建立，不能把另一個 attempt 的 authority identity 帶進
projection。

Production Supabase seam 由 service-role-only RPC 組成：

- durable approval table 開啟並強制 RLS；approval 可 idempotent record、read-back、
  revoke，scope SHA-256 與完整 authorization identity 不可漂移；
- candidate read-back 固定回傳完整 article 與六張 dependent tables；live FK catalog
  必須仍精確等於七條 cascade edges；
- compare-delete 在同一 PostgreSQL transaction 內鎖住 family owner、started attempt、
  active approval、Primary Authority epoch/token、article 與 child rows，並把 caller
  candidate 與 durable effect payload scope、database projection逐 byte 比對後才 DELETE；
- public／anon／authenticated 無 EXECUTE，十個 public wrapper 皆由 no-login
  `volpred_ops_definer` 持有、空 search path，只有 service role 可呼叫。

Live verification 完成`legacy/1 → operations_core/2 → legacy/3 rollback`的owner CAS，
最終仍未授權任何 unattended delete。Approval smoke 已完成 record → read-back →
revoke；candidate read-back回傳六張 dependent tables；故意呼叫 compare-delete 時由
owner fence 拒絕，前後 candidate 與 evidence hash完全相同。相鄰 Effect/outbox、
safe reconcile、publisher sync 與 Supabase suites 共222 passed。此 production
owner／approval／projection slice 為
`root_cause_fixed_and_verified`；exact restore executor、manual-only
delete→rollback→convergence rehearsal及physical two-Mac authority receipts仍缺，
所以 program commit 15 與 operations-core umbrella 維持 `contained`。

## 16. Publisher destructive delete exact restore contract（2026-07-25）

`PublisherArticleDeleteRestoreExecutor.restore()`是recovery artifact的唯一consumer
interface。Request必須攜帶exact recovery bytes、SHA-256、artifact ref與requester；
executor在任何provider call前重算hash、解析canonical JSONL並重新套用六張cascade
table／七條edge identity contract。

Projection seam刻意只有兩個能力：

- `readback(expected_candidate)`回傳完整article與六表candidate或typed absence；
- `restore_batch(expected_candidates)`必須在單一transaction內compare所有row目前為
  absent或exact match，再恢復整批；不得暴露逐table CRUD給caller。

Executor先完成全批preflight；任一既存row漂移都零mutation。確有缺row時mutation
authorizer是required，並緊貼唯一`restore_batch`external boundary。Provider回true後
仍須逐candidate exact read-back，receipt綁定recovery SHA、artifact、requester、完整
evidence refs/hashes與實際restore count。已完全恢復的replay為read-only，不要求新的
mutation authority。

Contract與相鄰publisher suites共157 passed；本切片沒有production RPC或remote write。
下一個切片是service-role-only atomic restore projection及其ACL／transaction failure
injections，之後才可執行manual-only live delete→restore→convergence rehearsal。
因此exact restore execution contract為`root_cause_fixed_and_verified`，program commit
15與operations-core umbrella仍為`contained`。

## 17. Publisher destructive delete production restore projection（2026-07-25）

`SupabasePublisherArticleDeleteRestoreProjection`是restore executor唯一production
adapter：read-back沿用完整candidate RPC；mutation只呼叫一次
`volpred_restore_publisher_article_delete_batch(jsonb)`，並fail-close驗證schema、
candidate count、restore count與boolean acknowledgement。Runtime只從
`SUPABASE_SERVICE_ROLE_KEY`建立client，不存在publishable-key fallback。

Database RPC在同一transaction內依序完成：

1. 回讀live FK catalog，必須精確等於六張cascade tables／七條edges；
2. 驗每個article與child JSON可完整round-trip至目前table row type，且child仍綁定
   candidate article；
3. 鎖住全批既存parent／child rows，再對每個candidate只接受absent或exact；
4. 先插入全部missing articles，再插入六張child tables；跨兩個candidate重複出現的
   relation以`(source_id,target_id)`去重；
5. 逐candidate重新呼叫private complete read model，任何不等即raise並回滾全批。

Public wrapper由no-login definer持有、`SECURITY DEFINER`、空search path，只有
service role能EXECUTE；definer只有SELECT／INSERT／row-lock所需UPDATE privileges及
對應RLS policies，migration結束後沒有public schema CREATE。隔離PG17以真constraint
與trigger注入驗證scope drift零write、中途失敗全批rollback、nullable child binding、
dual-edge relation與read-only replay，共6案通過。首版migration
`20260725020432`後以forward-only `20260725020935`補上SQL NULL-safe wrapper；舊v1
僅no-login owner可執行。Production owner、ACL、14個RLS policies與七edge catalog已
回讀。此slice為
`root_cause_fixed_and_verified`；umbrella仍為`contained`，下一步是manual-only live
synthetic delete→restore→feed convergence rehearsal。

## 18. Publisher destructive delete manual rehearsal seam（2026-07-26）

`scripts/rehearse_publisher_delete_restore.py`是destructive family唯一operator
rehearsal入口，刻意不進任何runtime schedule。CLI必須明示
`--confirm DELETE-RESTORE-SYNTHETIC`，且scope只准包含一筆slug以
`ops-core-delete-restore-smoke-`開頭、已預先seed且live完整candidate與本地artifact
exact-match的remote-only row。

Interface把整個人工流程收斂成一個failure-closed transaction choreography：

1. 先從exact feed bytes與candidate產生scope/recovery，fsync並read-back recovery
   artifact，再記錄scope-bound durable approval；
2. destructive owner只准從`legacy`以generation CAS切到`operations_core`；
3. 第一個獨立EffectRequest完成delete與typed absence receipt；
4. atomic restore executor恢復article與六表完整bytes，且receipt的candidate／restore
   count必須精確等於scope；
5. 第二個不同idempotency/work identity的EffectRequest做cleanup delete；
6. standing publisher convergence receipt必須為v2、`converged`、零mismatch且零
   observation error，才可正常結束；
7. 最後以generation CAS回`legacy`並撤銷approval。任何delete RPC可能已mutation但
   response遺失時，一律先重跑exact restore；即使restore失敗，owner rollback與
   approval revoke仍各自繼續嘗試，最後合併回報cleanup failure。

Failure-injection完成後，production rehearsal `live-20260726-0503`也實際走完兩個
獨立owned delete effects與中間atomic restore。首輪live evidence另外揭露兩個contract
gap：destructive WorkItem必須由`required/awaiting_approval`經`approve_work`提升；
append-only owned request不可使用同時要求UPDATE RLS visibility的`FOR SHARE`。目前
projection以service-role-only preflight與typed exception context保留失敗位置，並在已
鎖定owner generation後plain-read immutable request。

Live receipt與DB readback一致：primary／cleanup effect皆`delivered`，restore為`1/1`，
epoch 8／9 authority均release，synthetic row absent，final owner=`legacy/19`且approval
inactive；standing convergence為零mismatch。Manual rehearsal evidence gate已
`root_cause_fixed_and_verified`，umbrella升級前只剩physical two-Mac authority pair。

## 19. Physical cross-host receipt implementation identity（2026-07-26）

Primary／standby process receipt的implementation identity必須涵蓋實際載入的
Operations Core，不可只雜湊operator入口。Canonical manifest以repo-relative path排序，
包含`scripts/rehearse_primary_authority_outage.py`與
`src/volpred/ops/**/*.py`全部Python source、`pyproject.toml`、`uv.lock`，另加入實際
Python implementation／version與OpenSSL version的canonical runtime identity；各項先做
SHA-256，再對canonical manifest做aggregate SHA-256。Verifier仍要求兩端aggregate
exact-match，並新增
`authority_key == derive(rehearsal_id)`，避免edited receipt把正式effect-family key包成
隔離演練。

Physical machine identity在macOS必須來自`IOPlatformUUID`後的one-way SHA-256，
receipt不可保存raw hardware UUID。`uuid.getnode()`不是硬體identity contract：多網卡
與介面列舉差異會讓同一台Mac跨process選到不同node，造成distinct-host假綠；穩定anchor
不可讀時必須在任何publisher／authority remote read前fail closed。

相鄰authority suites共31 passed；本切片沒有remote acquire、effect或provider call。
Receipt identity false-positive根因為`root_cause_fixed_and_verified`，但兩台實體Mac
尚未執行process roles並形成paired receipt，因此program commit 34與operations-core
umbrella仍為`contained`。

## 20. Cross-host receipt run-time identity stability（2026-07-26）

只在role結束時雜湊disk source仍不足：shared checkout可能在primary已import舊code後
更新，使receipt記錄從未執行過的新bytes，再與之後啟動的standby錯誤配對。Primary與
standby現在都在第一個remote read／mutation前快照canonical implementation aggregate，
並在remote cleanup後、receipt construction前重驗相同aggregate；任何中途source drift
都fail closed且不留下可配對receipt。

兩個role的failure injection與相鄰authority suites通過；standby drift路徑另回讀lease
已release。本false-positive根因為`root_cause_fixed_and_verified`。因第二台實體Mac
目前沒有可操作的remote session，本輪沒有執行production role，physical pair與umbrella
仍維持`contained`。

## 21. Cross-host pre-mutation readiness gate（2026-07-26）

原本的physical流程在primary已acquire／renew／demote live authority lease之後，才把
primary與standby receipt交給`verify-pair`檢查distinct machines、相同code與publisher
fence。若第二台host沒有正確credential、checkout不是同一版，或其實是同一台machine，
失敗會在live控制面已mutation後才被看見。這是operator sequencing缺口，不是lease CAS
本身的錯誤。

新增兩段式readiness handshake。`prepare-host`只做machine identity、canonical source
aggregate與publisher owner read-back，不acquire authority；`verify-readiness`把兩端
receipt SHA-256、shared rehearsal-derived key、distinct host、exact code與exact
publisher fence綁成paired receipt。正式`primary`／`standby`CLI現在都強制接受同一份
paired readiness，並在任何authority RPC前重驗本機role／fingerprint與source aggregate。

Failure injections涵蓋code mismatch、same-machine、wrong-role host、preflight後
source drift與CLI validation後的窄race；相鄰authority suites **36 passed**，compile
與diff gate通過。Production只讀preflight `readiness-20260726-0635`回讀
publisher=`operations_core/8`、安全隔離key與implementation
`d02ed42e3aa8e380ba07d862ca6c270054a67c1d6907b349ea502c14128e387d`，沒有authority
acquire或provider call。本sequencing根因為`root_cause_fixed_and_verified`；第二台
實體Mac仍無可操作remote session，所以physical pair與umbrella維持`contained`。

## 22. Readiness-to-process receipt evidence binding（2026-07-26）

Readiness gate先前只存在CLI啟動路徑：role function接受可選的implementation hash，
process receipt本身不記paired readiness，final `verify-pair`也不接收readiness
artifact。即使CLI確實先驗過兩端，事後只有兩份role receipt時仍無法證明它們使用的是
mutation前通過的那組host／source／publisher fence；另一組相容receipt可以被重新配對而
假綠。

Primary與standby role現在直接要求typed `CrossHostReadinessReceipt`，在function內而非
CLI外重驗role、machine、derived authority key與source，再把paired readiness的
SHA-256寫入各自v2 receipt。Final verifier強制接收同一readiness，重驗其distinct-host、
digest與derived-key invariants，並要求兩端readiness hash、host identity、
implementation及publisher fence都exact match；v2 final receipt也保存同一hash。

Failure injection涵蓋role啟動前source race、edited same-machine readiness、不同
readiness的process receipt與identity drift；相鄰authority suites **37 passed**，
`py_compile`與diff gate通過。本機production只讀receipt
`storage/ops/primary_authority_outage_host_readiness_latest.json`回讀
publisher=`operations_core/8`、安全隔離key與implementation
`cc02ab8d5a073f2bd85aa08045abcd285b2a3151059192c7b99dea40563043cc`，沒有組裝
authority store或provider。此evidence-chain根因為
`root_cause_fixed_and_verified`；第二台實體Mac仍未執行role，所以physical pair與
operations-core umbrella仍為`contained`。

## 23. Standby primary-receipt pre-mutation gate（2026-07-26）

Standby先前只接收operator由primary JSON手抄的`expected_primary_epoch`。它會先嘗試取得
live authority lease，直到final `verify-pair`才檢查該epoch是否真的來自同一份primary
receipt；錯檔、舊檔或不完整的primary evidence因此會先改控制面、事後才失敗。兩個role
function也接受caller自填`holder_ref`，authority mutation identity可與readiness宣稱的
physical host脫鉤。

Standby function與CLI現在強制接受完整primary v2 receipt，在任何publisher read或
authority RPC前重驗shared rehearsal-derived key、readiness SHA、primary host／source、
lease window、healthy renewal、local gate closure、partition probe、terminal demotion、
零effect/provider counters與exact publisher fence，再由receipt直接導出expected epoch。
Primary／standby holder則由rehearsal ID、role與host fingerprint在module內唯一導出；
final verifier同樣重驗兩端holder binding。

Failure injection把primary receipt改成`local_gate_closed=false`，standby在零新增remote
read、零新增authority claim下拒絕；holder drift也不能形成final pair。相鄰authority
suites **38 passed**，`py_compile`與diff gate通過。Production只讀preflight
`standby-preflight-20260726-0830`已原子落檔並exact read-back
publisher=`operations_core/8`、安全隔離key與implementation
`a273e8bc7ae65fb0f0205dbc9caadf8485f88422bda6bdceccc0a0796d6fab52`；沒有authority
acquire或provider call。此pre-mutation identity根因為
`root_cause_fixed_and_verified`；第二台實體Mac仍未執行roles，physical pair與
operations-core umbrella維持`contained`。

## 24. Standby-to-primary exact artifact binding（2026-07-26）

Standby雖已在mutation前讀取並驗證完整primary v2 receipt，舊standby v2 receipt卻只
保存`expected_primary_epoch`。Final verifier因此無法證明standby實際驗過的是現在拿來
配對的那份primary artifact；只要保留同一epoch與其餘可驗欄位，事後改寫primary
receipt中未參與epoch比較的內容，仍可形成`cross_host_verified=true`假綠。

Standby現在於所有publisher read／authority RPC前，對已通過完整驗證的typed primary
receipt計算canonical SHA-256，並寫入standby v3 receipt。Final verifier重新計算當前
primary artifact digest，要求與standby保存值exact match後才檢查handoff；final receipt
同步升v3，並以同一digest作為`primary_receipt_sha256`。Failure injection在standby完成後
只改primary `completed_at`，舊流程先紅燈證實仍會接受，新流程在final verification
fail closed；相鄰authority suites **41 passed**，未執行production remote mutation。

本artifact-binding根因為`root_cause_fixed_and_verified`。Production只讀preflight
`primary-artifact-preflight-20260726-0940`已原子落檔並exact read-back
publisher=`operations_core/8`、stable host fingerprint=`6652d01267d664d621c957b8`與
implementation=`bfa6af660456fb3292b00fbda334c4c21a1dceb79e6e694942077fc24ed34168`。
本機Tailscale backend恢復Running後，候選第二台Mac仍為offline且peer ping timeout；
因此真實physical pair尚不可執行，program commit 34與operations-core umbrella維持
`contained`。

## 25. Paired readiness raw-artifact binding（2026-07-26）

Readiness pair v1雖保存primary／standby host receipt SHA-256，正式process與final
verifier只收到pair artifact，沒有原始host receipts可供重算。Pair內的standby host
identity因此可以在沒有exact standby preflight artifact的情況下被自行填寫；primary端
仍可能在第二台尚未完成preflight時進入control-plane mutation。

`primary-authority-outage-readiness-pair.v2`現在內嵌兩份typed host readiness receipts，
保留各自canonical digest，並在primary、standby及final verifier的function boundary
逐欄重驗pair identity、publisher fence、source aggregate與raw artifact hashes。Failure
injection只修改pair的standby host identity、保留原始host receipt不變；流程在零新增
publisher read、零authority acquire下fail closed。相鄰authority suites **42 passed**，
`py_compile`與diff gate通過；Ruff未安裝，未把缺工具宣稱為lint通過。

Production只讀preflight `raw-host-binding-preflight-20260726-1010`已原子落檔並exact
read-back publisher=`operations_core/8`、stable host
fingerprint=`6652d01267d664d621c957b8`與implementation
`66030247729b74be53645bd0d9da87fbe3940f2ba4443034083340691b973c38`；沒有authority
acquire、effect或provider call。此pre-mutation evidence-chain根因為
`root_cause_fixed_and_verified`；第二台實體Mac仍離線，physical pair與
operations-core umbrella維持`contained`。
