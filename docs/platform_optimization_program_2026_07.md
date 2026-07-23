# VolPred 平台運營優化總計畫

- **Status**：ACCEPTED PROGRAM CHARTER — 尚未完成實作
- **Accepted**：2026-07-23
- **Owner 目標**：在不犧牲研究誠實、不增加按量 AI 費用、不刪除既有 skills 與前端的前提下，重構平台的基礎架構、程式、營運、Admin、UI/UX、自然成長與自我優化能力。

## 1. 本文件的角色

本文件是跨領域的 **umbrella program**，定義最終架構、執行順序、能力接管與共同驗收，不另建一套 ops 進度帳：

- `docs/refactor_plan_ops_master_2026_07.md` 在 Phase 1 接管完成前，仍是現行 ops 修復的 canonical implementation ledger。
- `config/project_targets.json` 仍是 active frontend／service target 的唯一來源。
- `config/runtime_schedules.json` 仍是排程 spec 的唯一來源；直到 scheduler ownership 正式切換，不能由本文件反推 live schedule。
- `storage/next_tasks.json` 仍是現行 pending queue；只有 ADR-0001 的匯入與原子切換 gate 通過後，才降為唯讀投影。
- 本文件不把既有計畫、技能、前端或流程自動標為 deprecated；每個退役都要在對應能力接管時單獨證明。
- Phase 0／ADR-0001 的 deep-module seam、interface、adapter 與第一個 TDD 切片，以
  `docs/operations_core_module_design.md` 為 implementation design。

## 2. 問題與成功定義

### 2.1 現況問題

1. 任務生命週期、liveness、排程、agent failover、Git 寫入、外部效果與 incident 尚未共享一個交易模型。
2. 本機 JSON 與多層 scheduler 難以跨主機協調，故換機、warm standby 與 RPO=0 無法成立。
3. Agent 可在長任務中被 quota、timeout、commit dirty tree 或外部 API 失敗中斷，缺乏一致的 checkpoint／resume 契約。
4. Admin 目前多為 observer，部分操作仍靠共用 token 或直接後端路徑，不能作為安全 control console。
5. 原版與 v3 各有優勢，但業務邏輯與畫面重複；v3 尚有功能缺口、過重頁面與 stale first-paint。
6. 成長證據停在 pageview 線索，尚未形成 impression → click → depth → save/question → sign-in → return → qualified conversion 的完整鏈。

### 2.2 不可妥協的結果

- 任務不再因 provider 額度、程序中斷或換機而失去 durable identity；額度恢復後能從已驗證檢查點自動續跑。
- 不使用任何增量付費 AI 管線，且設定錯誤不能悄悄啟用按量計費。
- 任何 commit、發佈、通知與外部寫入都可追溯到 WorkItem、requester、驗證、lease 與下游 acknowledgement。
- 同一時間只有一台主機能產生正式效果；warm standby 可在五分鐘目標內安全接管。
- Admin 可安全觀測與操作，但不能旁路 canonical core。
- vNext 在不刪原版／v3的條件下取得功能等價與更佳體驗，且部署、預設、退役分開核准。
- 研究真相、方法、失敗與更正不受付費層影響；成長不以隱私或過度宣稱交換。

## 3. 目標架構

| 邊界 | Canonical owner | 主要責任 |
|---|---|---|
| 研究真相 | Git repo + `storage/` | 資料、實驗、文章、論文、設定與可重現產物 |
| 運營協調 | Supabase PostgreSQL + `src/volpred/ops/` | WorkItem、checkpoint、ChangeSet、EffectRequest、outbox、incident、lease、provider、migration |
| 執行隔離 | producer-scoped worktree／sandbox | Agent 純計算、修改草稿、測試證據；不得自行正式落地 |
| 版本落地 | lease-protected commit worker | exact-path validation、測試、commit receipt；push 仍依 owner policy |
| 外部效果 | lease-protected effect worker | 發佈、同步、Email／Telegram、部署等 idempotent side effects |
| 排程 | operations core scheduler | 讀 canonical schedule spec，materialize WorkItem；OS 只啟動／保活與 watchdog |
| 操作介面 | typed operations API + Admin console | 讀模型與受控命令；不直改 DB／JSON |
| 前端產品 | shared functional/data core + presentation modes | 原版的功能／資訊架構、v3 的長文閱讀、同一份資料與 analytics |

## 4. 既有能力去向

「退役」均指能力接管後的舊執行路徑；不是刪除歷史、skills 或前端資產。

| 現有能力 | 去向 | 接管條件 |
|---|---|---|
| `src/volpred/ops/` CLI 與 domain helpers | **保留並深化** | 新模組沿用 CLI-first、read-back、receipt 與 fail-loud 原則 |
| dispatch supervisor 的 slot、health、workspace、failure classification | **保留／轉型** | 執行器改為消費 WorkItem，scheduler decision 逐步移入 core |
| `local_control_plane` 的 TaskRecord／AgentSession／ExecutionReceipt | **轉換** | schema 對映後由 Supabase canonical；本機檔變 audit cache |
| `storage/next_tasks.json` | **接管後唯讀投影** | 一次匯入、row-count/hash/狀態對帳、原子 owner 切換、回滾演練 |
| `storage/ops/` receipts／ledger | **保留為本地稽核鏡像** | 不再被誤認成第二套 pending queue |
| `config/runtime_schedules.json` | **保留為 spec** | core scheduler 成為唯一 materializer；禁止另建 schedule source |
| LaunchAgent／host cron／piggy-back scheduler | **縮為 bootstrap、keepalive、watchdog** | core scheduler 連續穩定且舊 business fire 路徑可證明為零 |
| `git_writer_lock`／`scheduled_writer_commit`／merge gates | **保留並收斂為 commit actuator** | 所有正式 commit 都需 ChangeSet、lease fencing 與 receipt |
| publisher、feed sync、Mirror／Supabase dead letter | **保留業務行為，納入 EffectRequest／outbox** | idempotency、retry、reconcile 與下游 read-back 全通過 |
| incident lifecycle、3-Strike、sustained-clean resolution | **保留並升為 core incident owner** | detector 只開／更新 incident，不各自建重複修復 loop |
| Claude→Codex failover | **由 capability-aware provider router 接管** | 零付費 guard、能力契約、probe backoff、checkpoint resume 全通過 |
| 現行換機 bootstrap | **轉為 parity manifest 驅動的 guided migration** | 無硬編 user/path、無 plaintext secret、shadow／lease／rollback 演練 |
| 原版網站與 `/v3/*` | **並行保留** | vNext 三階段 gate；退役仍須 owner 另行明確批准 |
| Admin observer surfaces | **保留讀取面，命令改走 typed core API** | RBAC、reauth、audit、idempotency、read-back 與 break-glass policy |
| 現行 analytics | **補齊 evidence chain** | first-paint、v3 beacon、CTR、深讀、回訪、合格轉化與隱私 lifecycle |
| `.claude/skills/` 全部既有 skills | **全部保留** | 只改進缺漏；不得刪除或改名，新增需通過 §10 建立門檻 |

## 5. 分期執行

### Phase 0 — 基線與契約固定

目的不是寫新平台，而是讓之後每次接管都有可比較的 pre-image。

- 盤點所有正式 writer、external effects、scheduler fire、provider entry、Admin mutation、frontend routes 與 secrets locations。
- 建立 capability matrix、side-effect catalog、schedule ownership map、frontend parity matrix、migration asset manifest。
- 為現況記錄 task throughput、stale claims、commit failure、duplicate effect、incident MTTR、first-paint correctness、核心 Web 指標與 analytics coverage。
- 把每個接管項定義成 snapshot → implementation → tests → shadow replay → cutover → downstream read-back → rollback rehearsal。

**Gate P0**：清單能機械重跑；每個正式 side effect、schedule 與 route 恰有一個現行 owner；未知 owner 一律是 blocker。

### Phase 1 — 可靠性與交易式運營核心

本期吸收而不取代 ops master 的未完成工作。

- 建立 WorkItem、Checkpoint、ChangeSet、EffectRequest、Event、Outbox、Lease 的 migration 與 domain service。
- 將現行 task vocab 對映為受控狀態機，所有狀態變更具 optimistic concurrency／transaction。
- 先讓 next_tasks importer 與 projection 在 shadow 比對，再做單次 ownership cutover；禁止雙寫。
- 把現有 worktree isolation、Git writer lock 與 merge verification 接到 ChangeSet validator／commit worker。
- 把 publisher、sync、notification 等正式寫入包成 EffectRequest，成功定義為下游 read-back，不是 process exit 0。
- 讓 incident lifecycle 成為所有 detector 的唯一 durable identity，保留 sustained-clean resolution 與 3-Strike。
- scheduler 先 shadow materialize，對帳現行 fires；穩定後逐類接管，OS 最終只保活 core。

**Gate P1**：

- 重複 WorkItem／EffectRequest replay 不會產生第二次效果。
- crash 可在任一 transaction 邊界重啟，不遺失 claim、不留下不可判定 commit。
- 連續七天無 silent fallback、無雙 materialization、無孤兒正式寫入。
- `next_tasks` 新舊計數、priority、ownership、terminal disposition 全數對帳。
- 問題只能在五步 gate 全過後標 `root_cause_fixed_and_verified`，否則為 `contained` 或 `blocked`。

### Phase 2 — 零付費 provider continuity、暖備與一鍵遷移

- Provider registry 明確區分 Claude Desktop／Claude Code、Codex／ChatGPT、其他既有訂閱 OAuth surface 的能力與 gate 資格。
- 設定 schema 白名單只允許 subscription/OAuth provider；掃描並拒絕 AI API key、credit、auto-reload 與付費 overflow。
- probe 採 bounded backoff，不以昂貴完整任務測試可用性；恢復後解除 blocker 並從 checkpoint resume。
- 遷移 bundle 只包含 manifest、版本、加密 service-secret envelope／references 與必要本地 artifacts，不包含 AI session token。
- standby 定期做唯讀 parity check；切換採 prepare → shadow → acquire lease → enable effects → read-back → demote old primary。
- 定期演練 warm failover 與 cold restore；失去 lease、網路分割與 Supabase 中斷都做 failure injection。

**Gate P2**：

- 測試與設定稽核證明不存在可被自動選用的付費 AI 路徑。
- 所有可續跑任務從最後 checkpoint 接續；不能等價續跑者保持 blocked，不偽裝成功。
- verified state RPO=0；warm failover 目標 ≤5 分鐘；雙主 injection 下只有一方能正式 commit／effect。
- 新 Mac 不複製 AI OAuth／Keychain session，仍能經引導在同一流程完成授權、TCC、parity 與切換。

### Phase 3 — 使用者價值與 analytics 證據

- 修正 v3 首屏 stale/mock 資料與 analytics beacon 缺口，再比較兩版。
- 建立 first-party event dictionary 與 evidence chain；匿名 ID、登入 identity merge、retention、opt-out／delete 都有契約。
- 首批產品假設依既有資料排序：即時風險答案、不可改寫戰績、資料破迷思、會員提問閉環、收藏／追蹤／提醒。
- 每個實驗預註冊 primary metric、guardrail、sample／window 與停止條件；pageview 只作探索性訊號。

**Gate P3**：核心頁事件遺失率、重複率與 identity merge 經測試；能量到 impression→qualified conversion；隱私刪除能在所有 projection 回讀確認。

### Phase 4 — 混合式 vNext 與安全 Admin

- 抽出共用 data access、route contract、auth、SEO、analytics、design tokens 與功能元件。
- 以 route／scenario parity matrix 逐頁組裝 vNext，不先複製整套 v3。
- 首頁簡潔回答當前風險；深度文章採 editorial reading；會員頁以回訪與追蹤為核心；Admin 維持高密度但命令走 typed operations API。
- 原版、v3、vNext 同時可測與可回滾。依 ADR-0003 分別裁決 deploy、default、retire。

**Gate P4**：100% 有效功能／路由 parity、authoritative first paint、桌面／行動核心流程、auth／Admin、SEO、效能、a11y、analytics、七天小流量觀察與回滾演練全過。未取得 owner 的獨立退役批准，不得刪除原版或 v3。

### Phase 5 — 自然成長、商業化與受控自我優化

- 免費層固定研究真相與公開戰績；premium 驗證提醒、匯出、深度工具與 dashboard；institutional 驗證 API、資料與研究包。
- 建立 SEO、Email、社群與站內回訪的 attribution，先做自然流量，不做付費投放。
- 自我優化只能產生候選版本，經 isolated tests、shadow replay、canary、rollback 才能取得 ownership；核心不能原地改寫自己或自行放行自己的 gate。

**Gate P5**：成長以合格轉化、留存與收入證據判斷，研究誠實／隱私 guardrail 零違反；任何自動調整皆有版本、批准、效果與回滾 receipt。

## 6. 建議的小步提交序列

每一列是一個可獨立測試、可回滾的意圖；不得把跨列工作壓成大提交。

| # | 提交意圖 | 最低證據 |
|---:|---|---|
| 01 | 加入 ADR、program charter 與既有文件指標 | links／scope audit |
| 02 | 建立可重跑的 writer／effect／schedule inventory | deterministic snapshot |
| 03 | 建立 provider capability 與 zero-paid policy schema | schema validation |
| 04 | 建立 WorkItem migration 與 repository | transaction tests |
| 05 | 加入受控狀態 transition 與 optimistic concurrency | invalid-transition tests |
| 06 | 建立 Checkpoint schema 與 artifact hash 驗證 | corrupt／partial checkpoint tests |
| 07 | 建立 append-only operational event 與 receipt | order／immutability tests |
| 08 | 建立 ChangeSet schema，禁止 agent commit | policy and path-scope tests |
| 09 | 將現行 Git writer 包為 commit actuator adapter | existing regression suite |
| 10 | 加入 lease fencing 到 commit actuator | stale-token rejection |
| 11 | 建立 EffectRequest 與 idempotency contract | replay property tests |
| 12 | 建立 transactional outbox／claim loop | crash-between-write-and-send tests |
| 13 | 先接一個低風險 notification effect | downstream read-back |
| 14 | 接管 publisher 的單篇 sync effect | duplicate／dead-letter tests |
| 15 | 接管 reconcile／full sync effect | projection convergence |
| 16 | 把 incident identity 與 WorkItem disposition 接通 | recurrence／sustained-clean tests |
| 17 | 建立 next_tasks one-time importer dry-run | counts／hash／mapping report |
| 18 | 建立 next_tasks read-only projection | compatibility consumer tests |
| 19 | shadow 比較新舊 task selection | seven-day diff ledger |
| 20 | 原子切換 pending queue ownership | rollback rehearsal |
| 21 | 建立 scheduler materialization service | due／DST／duplicate tests |
| 22 | shadow 比較現行 scheduler fires | fire receipt parity |
| 23 | 接管第一類 business schedule | zero duplicate fires |
| 24 | 逐類接管其餘 schedules | per-class cutover receipts |
| 25 | 將 OS 排程縮為 core keepalive／watchdog | killed-core recovery test |
| 26 | 加入 provider health／quota blocker 狀態 | transition／backoff tests |
| 27 | 將 Claude→Codex failover 改為 capability routing | equivalence／non-equivalence tests |
| 28 | 加入零付費三層 deny guard | config／startup／dispatch tests |
| 29 | 加入 cooperative preemption 與 resume | checkpoint handoff test |
| 30 | 建立 migration parity manifest | clean-host deterministic scan |
| 31 | 去除 bootstrap 的 user／path 硬編 | alternate-user test |
| 32 | 將 secrets 遷移改為 Keychain references／guided input | plaintext leak scan |
| 33 | 建立 standby read-only parity checker | drift detection |
| 34 | 建立 lease acquire／renew／demote workflow | split-brain failure injection |
| 35 | 完成 warm failover／cold restore rehearsal | RPO／RTO receipts |
| 36 | 定義 analytics event dictionary 與 privacy lifecycle | contract tests |
| 37 | 修正原版／v3 first-paint 與 beacon parity | browser E2E |
| 38 | 建立 frontend route／scenario parity checker | CI report |
| 39 | 抽出 shared data／auth／SEO／analytics core | both-mode regression |
| 40 | 組裝 vNext public／article／member surfaces | desktop/mobile E2E |
| 41 | 將 Admin commands 接到 typed ops API | RBAC／reauth／audit tests |
| 42 | 部署 vNext 小流量但不改預設 | seven-day observation |
| 43 | owner 核可後切 default，保留原版／v3 rollback | rollback drill |
| 44 | 建立自然成長實驗 registry | preregistration audit |
| 45 | 驗證 premium／institutional 最小方案 | qualified-conversion evidence |
| 46 | 建立 self-optimization shadow／canary gate | self-approval denial test |

## 7. 測試與驗證策略

### 7.1 必測外部行為

- 同一請求重播不重複建立 WorkItem、commit、文章、通知或部署。
- worker 在 claim 後、checkpoint 前後、outbox send 前後、commit 前後 crash 的恢復結果。
- quota exhausted、auth expired、binary missing、provider recovered、capability mismatch 的派工結果。
- lease expired、stale fencing token、network partition、standby 誤啟動的 fail-closed 行為。
- queue importer／projection 的 row count、priority、ownership、terminal status 與 rollback。
- Admin 的 role、reauth、confirmation、break-glass expiry 與 audit read-back。
- 原版／v3／vNext 的資料、功能、route、SEO、analytics 與桌面／行動流程 parity。
- analytics opt-out、delete、retention 與 aggregation 後不可回推出不必要個資。

### 7.2 測試層次

- **Unit／property**：狀態機、idempotency、capability match、backoff、lease fencing、privacy retention。
- **Contract**：Supabase schema、provider adapter、effect adapter、Admin API、frontend data contract。
- **Integration**：transaction + outbox、commit actuator、publisher/read-back、queue migration。
- **Failure injection**：程序 kill、timeout、DB 不可達、網路分割、重複 webhook、磁碟滿、stale host。
- **Replay／shadow**：歷史 task、schedule、incident 與 frontend traffic 的差異報告。
- **E2E**：從使用者／排程建立 WorkItem，到 agent、ChangeSet／EffectRequest、commit／effect、Admin receipt 的完整鏈。

所有完成宣告都遵守 AGENTS.md 五步 gate：症狀證據、根因層級、底層重構、回歸與下游回讀、制度化寫回。

## 8. 安全、權限與 secrets

- 人員、agent、scheduler、commit worker、effect worker、migration worker 使用分離身分與最小權限。
- 高風險或不可逆操作需 owner 重新驗證與逐次確認；break-glass 限時、可撤銷、完整稽核。
- secrets 只在 Keychain／secret store；DB、repo、logs、WorkItem、checkpoint、migration bundle 只存 reference 或遮蔽值。
- 所有 log、receipt、error payload 在落地前做 secret redaction；CI 掃描 plaintext credentials。
- Admin 不保存共用全域 token；瀏覽器 session 只取得其角色所需的短期權限。

## 9. 明確不做

- 不以 big-bang rewrite 取代逐能力接管。
- 不建立第二個 pending queue、schedule source 或 Admin-owned control plane。
- 不使用任何按量付費 AI 備援，也不把較弱模型的輸出冒充特定 provider gate。
- 不讓 agent 自行 commit、push、發佈、部署或批准自己的核心變更。
- 不在 vNext gate 前刪除、改名或破壞原版、v3、`frontend-v3-design` 與任何既有 skill。
- 不直接改歷史 JSON／DB 來結案；修產生錯誤的流程。
- 不因 pageview 上升就宣稱產品成功，也不建立跨站或金融側寫。

## 10. Project skill 治理

### 10.1 建立門檻

只有同時符合以下條件才新增 project skill：

1. 同一流程會重複執行，且靠臨場提示容易漏掉 gate。
2. 流程已有 canonical code／config／doc 可引用，不需要在 skill 複製第二份規格。
3. 涉及固定工具順序、危險操作、遷移、驗收或專門領域判斷。
4. 能以 validator、fixture 或 smoke scenario 證明 skill 完整。
5. 先確認現有 skill 不能用小幅擴充解決。

既有 skill 一律保留，不刪除、不改名。Skill 不能替代 schema、lock、transaction、權限或程式修復；若流程缺陷可由 code 機械防止，先修 code，再讓 skill 成為入口。

### 10.2 建議盤點與處置

| 工作流 | 優先處置 | 理由 |
|---|---|---|
| 日常 ops 診斷、事故、PDCA | 先擴充 `platform-ops-manager`／`pdca-operations`／`admin-ops` | 已有相近入口，避免再建同義 skill |
| WorkItem／ChangeSet／EffectRequest 操作 | Phase 1 穩定後新增 `operate-work-items` | 新的跨工作負載正式操作契約，適合薄入口 + CLI references |
| 零付費 provider 恢復與 checkpoint resume | 優先納入 `platform-ops-manager`；流程成熟後再決定是否拆 skill | 初期 schema／router 仍會變，過早固化會漂移 |
| Guided migration／warm failover 演練 | Phase 2 新增 `migrate-volpred-host` | 高風險、低頻、步驟嚴格，需 deterministic scripts 與 parity checklist |
| 原版／v3／vNext parity 與切換 gate | 擴充 `web-ui-ux-review`；必要時新增 `verify-frontend-cutover` | 評估可沿用，正式 deploy/default/retire gate 才需要專用入口 |
| Growth experiment | 先建立 code registry 與 analytics contract，再評估新增 `run-growth-experiment` | 不能用 prompt 代替實驗預註冊與隱私 enforcement |
| Commit／worktree 驗證 | 擴充 `worktree-merge-verification` | 現有 skill 已接近 ChangeSet 驗證職責 |

### 10.3 Skill 驗收

- `SKILL.md` 保持精簡，詳細規則放 references，脆弱步驟放 deterministic scripts。
- references 只指向 canonical config／ADR／plan，不複製會漂移的狀態表。
- 使用 `skill-creator` 的 validator 與至少一個成功／失敗 smoke scenario。
- 新 skill 必須登記 owner、trigger、inputs、side-effect boundary、failure mode 與 superseded-by；但不得以此授權刪除舊 skill。

## 11. Program-level 完成條件

本計畫只有在以下全部成立時才能從 `ACCEPTED PROGRAM CHARTER` 改為完成：

1. Phase 1–5 各自的 gate 與下游 read-back 有可查 receipt。
2. 連續運行證據顯示任務、commit、外部效果與主機切換沒有 silent loss／duplicate。
3. 零付費 policy 經靜態、啟動、runtime 與演練四層證明。
4. vNext 的 deploy／default 已各自核可；是否 retire 原版／v3仍是獨立 owner 決策。
5. 既有 skills、研究真相與歷史產物無未批准刪除。
6. `docs/architecture.md`、運營狀態、遷移手冊、Admin 操作手冊與 skill references 已反映 live reality。
