# 派工決策單一 Pipeline 設計（WS-H4）

> 任務：assign_dacd4847（refactor-master H4）｜依據：docs/refactor_plan_ops_master_2026_07.md §WS-H4

本文件為 **design-first**：只描述現況證據與目標架構，不含任何 code 變更。落地由主線程後續裁決。

計畫原文（`docs/refactor_plan_ops_master_2026_07.md:136`）：

> **派工決策單一 pipeline**：派工職責現散在 5 檔（supervisor scheduler / continue_task_dispatch / pregate / slot_budget / legacy shell）→ 收斂為 supervisor 內單一 decision pipeline：`continue_task_dispatch.py` 降為純 library（候選計算，不再自帶寫入路徑，與 A1 同步）；pregate 明文 observational（D3）；priority / starvation / cluster budget / burst 的裁決邏輯集中一處、其餘為輸入
> 驗收：派工決策的單元測試集中在一個模組；`--dry-run` 輸出與實際 fire 決策一致性測試｜P1

---

## 1. 現況盤點（證據導向）

### 1.1 Owner A — supervisor scheduler

檔案：`scripts/dispatch_supervisor/scheduler.py`（855 行）

| 裁決 | 證據 | 說明 |
| --- | --- | --- |
| concurrency cap（fire 層） | `scripts/dispatch_supervisor/scheduler.py:698-704` | `len(current_jobs) >= capacity` → `action=skip, reason=slots_full` |
| capacity 來源 | `scripts/dispatch_supervisor/scheduler.py:205-242` | `load_max_slots()` 讀 `daemons[id=volpred-dispatch-supervisor].max_slots`；`DEFAULT_MAX_SLOTS = 2`（`:66`） |
| quota de-rate | `scripts/dispatch_supervisor/scheduler.py:173-203`、`:233-239` | `quota_derate_active()` 連續 quota_blocked → cap 壓回 2 |
| auth 阻擋 | `scripts/dispatch_supervisor/scheduler.py:694-695` | `snap["auth_blocked"]` → skip |
| cron due 判定 | `scripts/dispatch_supervisor/scheduler.py:560-582`、`:720` | `_due_to_fire()` |
| burst / 外部急件 | `scripts/dispatch_supervisor/scheduler.py:722-738` | `state.consume_fire_request()`；requested fire **繞過 pregate**（`:774` 只 gate `fire_reason == "cron"`） |
| pregate 呼叫點 | `scripts/dispatch_supervisor/scheduler.py:770-788` | enforce 模式會 `action=pregate_skip` 並吃掉 slot |
| dry-run 分支 | `scripts/dispatch_supervisor/scheduler.py:789-794` | `action=dry_run_fire`，位置在 pregate 區塊之後、prompt 載入之前返回 |

**dry-run 繞過 pregate（2026-07-20 覆核新增）**：`scripts/dispatch_supervisor/scheduler.py:774` 的條件是 `if fire_reason == "cron" and not dry_run:`。即 **dry-run 路徑根本不執行 pregate**。含意：H4 驗收條要求的「`--dry-run` 輸出與實際 fire 決策一致性」在現行 scheduler 上**結構性不可能成立**——只要 pregate mode 非 `off`，cron fire 會過 pregate 而 dry-run 不會，兩者天生分歧。這是除 §1.2 的 ctd `--dry-run` bug 之外的**第二個** dry-run 語意缺陷，且位於計畫指定的收斂終點（supervisor）內。§3.5 的 `decide()` 純函數化正好一併解掉：pregate 降為 `DecisionInput.demand` 輸入後，dry-run 與 fire 吃同一份輸入、走同一個 `decide()`，差別只剩是否 `reserve_fire`。

**自帶寫入路徑**：有。`:711-713`（bootstrap `last_fire_at`）、`:786-787`（pregate_skip 吃 slot）、`:792-793`（dry_run 也寫 `last_fire_at`）、`:800-806`（`state.reserve_fire`）。皆走 `state._locked_state` / `state.reserve_fire`，屬受控 writer。

### 1.2 Owner B — `scripts/continue_task_dispatch.py`（1284 行）

| 裁決 | 證據 | 說明 |
| --- | --- | --- |
| priority 排序 | `scripts/continue_task_dispatch.py:436-449` | `_agentable_sort_key = (priority, recent_type_count, id)` |
| priority 正規化 | `scripts/continue_task_dispatch.py:38-55` | `_coerce_priority`：`"P1"`→1、未知→999 |
| starvation | `scripts/continue_task_dispatch.py:78-79`、`:334-368` | `STARVATION_HOURS = {1:6.0, 2:24.0, 3:72.0}`、default 96.0；`find_starved()` 依 `(priority, 超時幅度)` 排序 |
| status / lane filter | `scripts/continue_task_dispatch.py:370-434` | `categorize()`：blocked / main_thread / agentable 三分 |
| block 判定 | `scripts/continue_task_dispatch.py:252-283` | 顯式 `blocked_reason` → `blocked_until` 到期 → 標題描述 regex 軟阻擋 |
| main-thread 保留 | `scripts/continue_task_dispatch.py:398-433` | P1 保守預設走 main_thread；`explicit_agentable` 白名單覆寫 |
| type rotation（反壟斷） | `scripts/continue_task_dispatch.py:187-221`、`:440-444` | 依最近 work_log task_type 次數壓低同型任務 |
| slot 佔用 | `scripts/continue_task_dispatch.py:142-153` | **委派** `dispatch_slot_budget.occupancy()`，自身不再持 cap 常數（`:64-69` 明文禁止再放 literal） |
| refill 觸發 | `scripts/continue_task_dispatch.py:96-100`、`:822-921` | `REFILL_FLOOR = 4`、`DRAFT_POOL_FLOOR = 6` |

**自帶寫入路徑**：**有，且多**。

- `scripts/continue_task_dispatch.py:486-538` — `_materialize_pool_dry_diagnostic_task()` 直接 `flock` + `truncate` 寫 `storage/next_tasks.json`（`:489`、`:507`、`:524-526`）。這正是 WS-A1（`docs/refactor_plan_ops_master_2026_07.md:73`）點名的 `continue_task_dispatch.py:509-511` truncate 寫法。
- `scripts/continue_task_dispatch.py:673-733` — `_promote_starved_article_tasks()`。
- `scripts/continue_task_dispatch.py:734-820`、`:822-921`、`:922-948` — refill / retire 路徑。
- `scripts/continue_task_dispatch.py:949-994` — `_sweep_cleared_dreaming_tasks()`。
- `scripts/continue_task_dispatch.py:1271-1273` — 寫 `storage/ops/dispatch_report_latest.json`。

**關鍵缺陷（直接命中 H4 驗收條）**：`--dry-run` 在 `scripts/continue_task_dispatch.py:1260` 被宣告，但 `main()`（`:1258-1280`）**從未讀取 `args.dry_run`**。`:1267` 無條件呼叫 `build_report(auto_refill=not args.no_refill)`，而 `build_report`（`:995-1015`）在產生候選之前就會 retire / sweep / refill 並寫入 `next_tasks.json`。全檔其餘 `dry_run` 字樣（`:546`、`:561`、`:571`、`:772`、`:842`、`:868`、`:891`）都是內部 refill helper 參數，且呼叫端一律傳 `dry_run=False`。

→ 結論：**`--dry-run` 目前是名不副實的旗標，會產生真實的 state mutation。** H4 的一致性測試不能建立在現行語意上，必須先修正語意。

**生產呼叫者**：程式碼層 grep 全庫（排除 worktrees），除 `tests/` 外**無任何 `.py` / `.sh` / plist 呼叫 `continue_task_dispatch`**。唯一實際消費者是 LLM prompt：`scripts/cron_hourly_dispatch_prompt.md:118`、`:141`（`--report`）。即它已經事實上是「advisory 分身」——輸出被模型自由裁量，這正是 `scripts/continue_task_dispatch.py:70-77` 註解記載的 17 小時 member_qa 餓死事故根因。

### 1.3 Owner C — pregate

> **Pre-retirement inventory snapshot（2026-07-20）**：本節描述 H4-4
> 切換前狀態；終態以 §3.3 與 Q3 的 2026-07-30 決議為準。

當時檔案：`scripts/hourly_dispatch_pregate.py`（現已移至
`scripts/_legacy/hourly_dispatch_pregate.py`）

| 裁決 | 證據 |
| --- | --- |
| 需求訊號彙整 + proceed/skip | `scripts/hourly_dispatch_pregate.py:280-321` `decide()` |
| email backlog | `:101-109` |
| CRITICAL 告警 | `:110-145` |
| P1/P2 高優先待辦 | `:146-170`（`:158` `int(t.get("priority", 9))` — 與 Owner B 的 `_coerce_priority` **不同實作**） |
| compute followup | `:231-251` |
| publish drought | `:252-265` |
| cadence starvation | `:171-230`、`:301-318`（未知 → 視為 due，`:303`） |

**自帶寫入路徑**：有，但僅 append-only 觀測 log — `scripts/hourly_dispatch_pregate.py:266-278` 寫 `storage/logs/hourly_pregate.jsonl`。不碰 `next_tasks.json`。

**當時確實會裁決**：`scripts/dispatch_supervisor/scheduler.py:781-788` 在 enforce 模式下依 pregate 退出碼直接 `pregate_skip` 並消耗 slot。此 pre-cutover 缺陷已由 §3.3 的 H4-4 終態消除。

### 1.4 Owner D — `scripts/dispatch_slot_budget.py`（289 行）

| 裁決 | 證據 |
| --- | --- |
| cluster budget（subagent slot cap） | `scripts/dispatch_slot_budget.py:240-279` `budget()` |
| baseline / surge / derate | `:81`（`P1_SURGE_AT = 3`）、`:246-260`（auth_blocked → DERATE_CAP；PHASE-Z incident 未關 → DERATE_CAP；P1 ≥ 3 → SURGE_CAP；否則 BASE_CAP） |
| P1 專屬 slot | `:266` `p1_only_slots = max(0, cap - BASE_CAP)` |
| 佔用計算 | `:149-175`（worktree）、`:176-206`（agent record）、`:207-225` `occupancy()` |
| priority 讀取 | `:93-104`（`int(t.get("priority", 4))` — **第三種** priority 解析，且 default 為 4） |

**自帶寫入路徑**：無（純讀 + stdout JSON，`:280-289`）。這是五個 owner 中唯一乾淨的純函數模組。

**消費者**：`scripts/continue_task_dispatch.py:83`（import）與 `scripts/cron_hourly_dispatch_prompt.md:124`（prompt 內叫 LLM 自己跑）。**沒有任何機械 enforcement**——prompt `:126` 自稱「唯一的 slot cap enforcement owner」，但實際 enforcement 是模型自律。

### 1.5 Owner E — legacy shell

檔案：`scripts/cron_hourly_dispatch.sh`（822 行）；LaunchAgent spec `~/Library/LaunchAgents/com.volpred.hourly-dispatch.plist`

| 裁決 | 證據 |
| --- | --- |
| pregate 呼叫 + 依退出碼 skip | `scripts/cron_hourly_dispatch.sh:158-176`（`exit 0` on pregate skip） |
| shadow 預設 | `:165`（`PREGATE_SHADOW=1` 時加 `--shadow`） |
| timeout 視為 fail-open PROCEED | `:166-175` |
| 執行時間上限 | `:201` `HOURLY_CAP_SEC=3000` |
| 模型退避 / failover | `:205-215`、`:379-383`、`:465` |

**狀態**：plist 檔案存在於磁碟，但 `launchctl list | grep hourly` **無輸出**（未載入）。`scripts/dispatch_supervisor/scheduler.py:742-744` 註解亦記載「its only caller was the now-unloaded cron_hourly_dispatch.sh」。→ **disabled-but-alive**，與 D3（`docs/refactor_plan_ops_master_2026_07.md:105`）描述一致。

### 1.6 額外發現的裁決點（計畫的「5 檔」不完整）

| Owner | 證據 | 裁決內容 |
| --- | --- | --- |
| F. `src/volpred/ops/task_urgency.py` | `:70`（URGENT_SOURCE_TOKENS）、`:73`（TIME_CRITICAL_TASK_TYPES）、`:104-121`、`:123-142` `dispatch_lane()` sort | **第四套** priority 解析（`_priority()` `:96`）＋急件插隊排序，是 PHASE A0 的唯一 owner |
| G. `scripts/cron_hourly_dispatch_prompt.md` | `:86-99`（PHASE A0 lane 規則、停止條件）、`:118`（deficit ≥ 2 觸發）、`:120-127`（slot cap 使用規則） | **prompt 即裁決器**：實際「哪個 slot 做哪張 task」的最終決定在 LLM，腳本只提供建議 |
| H. `scripts/task_pool_claim.py` | `:618-650` `_burst_actions()`、`:660-678` `_request_burst_fire()`（`:673` `sup_state.request_fire(f"burst:{task_id}")`） | burst 窗口內完成一張 → 立刻要求下一次 fire |
| I. `src/volpred/ops/dispatch_burst.py` | `:64-78` `read_window()`、`:106-110` `active()`、`:111-126` `_quota_suspended()` | burst 窗口狀態機；quota 判定又向 scheduler 借（`:30` 註解） |
| J. `src/volpred/ops/scheduler.py` | `:30-40`（無鎖直寫 `scheduler_state.json`） | A3 記載的死 advisory lane（`docs/refactor_plan_ops_master_2026_07.md:41`） |

→ 實際裁決點是 **10 個，不是 5 個**。設計必須以 10 為基準，否則收斂後仍有殘留 owner。

---

## 2. concern × owner 矩陣

`●` = 實質裁決（會改變結果）；`○` = 僅讀取/回報，不裁決；空白 = 無涉。

| concern | A scheduler | B ctd | C pregate | D slot_budget | E legacy sh | F task_urgency | G prompt.md | H task_pool_claim | I dispatch_burst | **裁決 owner 數** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| priority 解析（字串→int） | | ● `:38` | ● `:158` | ● `:102` | | ● `:96` | | | | **4** |
| priority 排序 | | ● `:436` | | | | ● `:140` | ● `:86-99` | | | **3** |
| starvation | | ● `:334-368` | ● `:171-230` | | | | | | | **2** |
| cluster / slot budget | ● `:205-242` `:698` | ○ `:142`（委派） | | ● `:240-279` | | | ● `:120-127` | | | **3** |
| burst / 急件插隊 | ● `:722-738` | | | | | ● `:123-142` | ● `:86-99` | ● `:660-678` | ● `:106` | **5** |
| status / block filter | | ● `:252-283` `:370-434` | ○ `:147-170` | ○ `:102`（只數 pending） | | ○ `:123` | | | | **1** |
| concurrency cap | ● `:698-704` | | | ● `:240-279` | | | ● `:126` | | | **3** |
| pregate skip 否決權 | ● `:774-788` | | ● `:280-321` | | ● `:158-176` | | | | | **3** |
| quota / auth derate | ● `:173-203` | | | ● `:246-249` | | | ● `:125` | | ○ `:111-126` | **3** |
| 需求訊號（是否值得 fire） | | | ● `:280-321` | | ● `:158-176` | | | | | **2** |
| `next_tasks.json` 寫入 | | ● `:486-538` 等 | | | | | ● `:63`(jq，A1 點名) | ● | | **3** |
| dry-run 語意 | ● `:789-794` | ✗ `:1260`（宣告未實作） | | | | | | | | **1（+1 破損）** |

**被 2 個以上 owner 重複裁決的 concern（anti-stacking 違規）**：

1. **priority 解析** — 4 個獨立實作，default 值三種（999 / 9 / 4）。同一張缺 priority 的任務在三處會得到三種等級。
2. **burst / 急件插隊** — 5 個 owner。
3. **priority 排序** — 3 個。
4. **cluster / slot budget** — 3 個。
5. **concurrency cap** — 3 個（scheduler 的 fire cap=2 與 slot_budget 的 subagent cap=4/6/2 是不同軸，但兩者都無交叉檢查，可同時各自放行）。
6. **pregate skip 否決權** — 3 個。
7. **quota / auth derate** — 3 個。
8. **`next_tasks.json` 寫入** — 3 個（與 WS-A1 重疊）。
9. **starvation** — 2 個（ctd 的 per-task 年齡 vs pregate 的全域 cadence，判準不同、互不知情）。
10. **需求訊號** — 2 個。

---

## 3. 目標架構

### 3.1 單一 decision pipeline 放哪

**放 supervisor 內**，建議新模組 `scripts/dispatch_supervisor/decision.py`，由 `scheduler._tick()`（`scripts/dispatch_supervisor/scheduler.py:634` 起）唯一呼叫。

理由（三條，皆有現況證據支撐）：

1. **只有 supervisor 是活的**。`com.volpred.dispatch-supervisor` 已載入（`launchctl list` 有 PID），`com.volpred.hourly-dispatch` 未載入。把 pipeline 放在唯一活著的執行體內，避免再造一個「advisory 分身」——那正是 `continue_task_dispatch.py` 現在的處境（無任何生產 caller，只有 prompt 讀）。
2. **只有 supervisor 握有受控 state writer**。`state.reserve_fire` / `state._locked_state`（`scheduler.py:711`、`:800`）是唯一有 lease 語意的寫入面。裁決與 lease 分家會產生 TOCTOU：現況 `slot_budget` 算出 cap 後，到 LLM 真正派工之間沒有任何鎖。
3. **只有 supervisor 已有 dry-run 骨架**。`scheduler.py:789-794` 已存在完整的 `dry_run_fire` 分支語意；H4 的一致性驗收只需在此之上加約束，不必新造。

### 3.2 `continue_task_dispatch.py` 降為純 library

目標終態：模組只保留**純函數候選計算**，無 `main()` 副作用、無檔案寫入。

**保留（成為 pipeline 的輸入供給者）**：
- `_coerce_priority`（`:38`）→ 但應改為 re-export `volpred.ops.next_tasks` 的單一實作（見 §3.4）
- `detect_block_reason`（`:252`）、`is_main_thread_only`（`:223`）、`dispatch_lane`（`:240`）、`is_paper_task`（`:287`）
- `task_age_hours`（`:319`）、`starvation_threshold_hours`（`:334`）、`find_starved`（`:338`）
- `categorize`（`:370`）、`load_recent_task_type_counts`（`:187`）

**移出（自帶寫入路徑，全部搬離）**：

| 現況 | 去向 |
| --- | --- |
| `_materialize_pool_dry_diagnostic_task` `:458-538` | 改為回傳「建議建立的任務 dict」，實際寫入由 pipeline 呼叫 `volpred.ops.next_tasks` helper（**與 WS-A1 同步**：A1 明列要修 `:509-511` truncate 寫法） |
| `_promote_starved_article_tasks` `:673-733` | 同上，改為回傳 promote 建議清單 |
| `_maybe_refill_draft_pool` `:734` / `_maybe_refill` `:822` / `_maybe_retire_covered_article_tasks` `:922` / `_sweep_cleared_dreaming_tasks` `:949` | 移到獨立的 pool-maintenance 模組，由 supervisor 在裁決**之前**當作獨立階段執行；裁決本身不得觸發 refill |
| `REPORT_PATH.write_text` `:1273` | 改由 pipeline 統一輸出 decision receipt |
| `main()` `:1258-1280` + `--dry-run` / `--execute` / `--report` | `--execute`（`:1262` 自陳 reserved 未實作）直接刪；CLI 若保留只作 read-only 診斷，且 `--dry-run` 必須真的 no-write |

**與 A1 的相容設計**：所有寫入一律經 `volpred.ops.next_tasks` helper（`write_tasks_to_handle` 已在 `:528-530` 被部分使用）。降 library 後 `continue_task_dispatch.py` 對 `next_tasks.json` 的開寫模式次數應為 **0**，直接讓 A1 的 grep audit（`docs/refactor_plan_ops_master_2026_07.md:73`）綠燈。

### 3.3 pregate 明文 observational（呼應 D3）

> **2026-07-30 H4-4 最終裁定（取代本節原 observational-transfer 草案）**：
> production crosscheck 的 10 個 skip candidates 有 9 個仍產生實質工作，
> 因此 demand heuristic 本身不具安全裁決價值。保留它作 `DecisionInput`
> 不是 ownership transfer，而是把錯誤判準搬入新 owner。

- `scripts/dispatch_supervisor/scheduler.py` 移除 pregate subprocess 與所有 skip
  分支；`DecisionInput` 不再有 `pregate_mode` / `demand` 欄位。
- `config/runtime_schedules.json` 移除 pregate config，防止單一熱重載字串恢復否決權。
- evaluator 移至 `scripts/_legacy/hourly_dispatch_pregate.py`；CLI 只回報
  `retired/no-decision`，不讀寫 production state/log。
- `storage/logs/hourly_pregate.jsonl` 與
  `scripts/crosscheck_pregate_outcomes.py` 依 S9 保留為歷史 audit baseline；
  共享 substantive taxonomy 由 `volpred.ops.dispatch_outcomes` 擁有。

### 3.4 四項裁決集中，其餘退化為輸入

| 裁決 | 集中後的唯一 owner | 其餘 owner 的新角色 |
| --- | --- | --- |
| **priority** | `decision.py` 內單一 `rank()`；priority 正規化統一到 `volpred.ops.next_tasks.normalize_task_priority`（已存在，`continue_task_dispatch.py:85` 已 import） | ctd `:38` / pregate `:158` / slot_budget `:102` / task_urgency `:96` 全部改為呼叫同一函式 |
| **starvation** | `decision.py`；吃 ctd `find_starved()` 的輸出當**輸入**，pregate 的 cadence 當**另一個輸入欄位** | ctd `:338` 純計算、pregate `:171-230` 純觀測 |
| **cluster budget** | `decision.py`；`dispatch_slot_budget.budget()` 保持純函數，其 `cap` / `p1_only_slots` 成為輸入 | slot_budget 已是純函數，**不需改**（唯一乾淨的 owner）；prompt.md 的 cap 段落刪除 |
| **burst** | `decision.py`；`dispatch_burst.active()` / `read_window()` 成為輸入 | `task_pool_claim._request_burst_fire`（`:660-678`）保留（那是 ingress 喚醒，不是裁決）；`task_urgency.dispatch_lane()` 降為候選排序輸入 |

其餘一律為 **inputs**：`auth_blocked`、`quota_derate`、`occupancy`、`recent_type_counts`、`open_incident`。`demand_signals` 已由 2026-07-30 H4-4 最終裁定退役。

### 3.5 介面草案（signature 級）

```python
# scripts/dispatch_supervisor/decision.py  （新增，設計稿）

@dataclass(frozen=True)
class DecisionInput:
    now: datetime
    candidates: list[dict]          # continue_task_dispatch.categorize()["agentable"]
    main_thread: list[dict]
    blocked: list[dict]
    starved: list[dict]             # continue_task_dispatch.find_starved()
    urgency_lane: list[dict]        # volpred.ops.task_urgency.dispatch_lane()
    budget: dict                    # dispatch_slot_budget.budget()  -> cap / p1_only_slots / occupied
    fire_capacity: int              # scheduler.load_max_slots()
    active_jobs: list[dict]         # state snapshot current_jobs
    burst: dict | None              # volpred.ops.dispatch_burst.status()
    recent_type_counts: Counter
    fire_reason: str                # "cron" | "requested:<r>" | "cron+requested:<r>"

@dataclass(frozen=True)
class Assignment:
    slot_index: int
    task_id: str
    priority: int
    lane: str                       # "urgent" | "starved" | "normal" | "p1_only_slot"
    reason: str                     # 人類可讀理由字串，進 receipt

@dataclass(frozen=True)
class Decision:
    action: str                     # "fire" | "skip" | "no_candidates"
    reason: str
    assignments: list[Assignment]
    skipped: list[tuple[str, str]]  # (task_id, why_not_chosen)
    inputs_digest: str              # DecisionInput 的穩定 hash，供一致性測試比對

def decide(inp: DecisionInput) -> Decision: ...
    """純函數。無 I/O、無時鐘（now 由 inp 給）、無隨機。"""
```

**硬性約束**：`decide()` 不得 import `pathlib` 以外的 I/O、不得呼叫 `datetime.now()`、不得寫任何檔案。所有 I/O 由 `scheduler` 側的 `collect_inputs()` 完成，`fire()` 側消費 `Decision`。這是 §4 一致性測試能成立的前提。

---

## 4. 驗收準則

### 4.1 派工決策的單元測試集中在一個模組

**新檔**：`tests/test_dispatch_decision.py`（單一模組，涵蓋 `decision.decide()` 全部分支）。

必測項目：

| # | 測什麼 | 通過判準 |
| --- | --- | --- |
| 1 | priority 排序 | 混入 `1` / `"P1"` / `"p1"` / 缺欄位，`Decision.assignments` 順序與 int 版完全一致；缺欄位一律落在隊尾 |
| 2 | priority 單一解析 | 對同一組 fixture，`decision`、`task_urgency`、`slot_budget`、`pregate` 四路解析結果 **逐筆相等**（防 §2 的 999/9/4 三種 default 復辟） |
| 3 | starvation 解鎖 | P1 age 6.1h、P2 24.1h、P3 72.1h 必被選中，且排在同 priority 未餓死者之前 |
| 4 | starvation 不越級 | 47h 超時的 P3 不得排在剛跨 6h 線的 P1 之前（`continue_task_dispatch.py:341-345` 記載的既有語意） |
| 5 | cluster budget | `cap=4` / `cap=6, p1_only_slots=2` / `cap=2 (derate)` 三情境下 `len(assignments) <= cap - occupied` |
| 6 | P1-only slot | cap=6 時 slot 5-6 只能被 priority ≤ 2 佔用；無 P1/P2 候選時該 slot 空著而非降級 |
| 7 | burst | `burst.active=True` 時急件 lane 先清空；`_quota_suspended` 為真時 burst 不得放大 cap |
| 8 | 急件繞道 | `fire_reason` 以 `requested:` 開頭時，`demand.proceed=False` 不得產生 skip |
| 9 | pregate observational | 對任意 `demand` 值，`Decision.action` 只能因 `demand` 改變 `reason` 字串，不得單獨把 `fire` 變成 `skip`（除非同時無候選） |
| 10 | 純函數性 | 同一 `DecisionInput` 連呼叫 100 次，`Decision` 完全相等；且測試期間 `next_tasks.json` mtime 不變 |

**同時退役 / 改導向**：`tests/test_dispatch_type_rotation.py`、`tests/test_continue_task_dispatch_pool_dry.py` 中屬於「決策」的斷言搬進本模組；留在原檔的只保留 library 層的候選計算斷言。`tests/test_dispatch_slot_budget.py` 保留（它測的是輸入產生器，不是裁決）。

### 4.2 `--dry-run` 與實際 fire 的一致性測試

**前提修正**：先修好 `scripts/continue_task_dispatch.py:1260-1267` 的 `--dry-run` 語意（現況為 no-op，見 §1.2）。收斂後 dry-run 的定義為：**同一份 `DecisionInput` 產生同一個 `Decision`，差別只在是否呼叫 `state.reserve_fire` 與 spawn worker。**

測試設計（`tests/test_dispatch_decision.py::test_dry_run_matches_fire`）：

1. 建構固定 fixture（凍結 `now`、凍結 `next_tasks.json` 副本、凍結 budget/occupancy）。
2. 跑 `_tick(dry_run=True)`，攔截 `Decision`，記為 `d_dry`。
3. 對**同一份未被修改的 fixture**跑 `_tick(dry_run=False)`，於 `state.reserve_fire` 與 worker spawn 處打 mock（只記錄不執行），攔截 `Decision`，記為 `d_fire`。
4. 比對。

**通過判準（三條全滿足才算過）**：

- `d_dry.action == d_fire.action`、`d_dry.reason == d_fire.reason`
- `[(a.slot_index, a.task_id, a.lane) for a in d_dry.assignments] == 同上 for d_fire`（**理由字串 `a.reason` 也要相等**；只允許 receipt 的時間戳欄位不同）
- `d_dry.inputs_digest == d_fire.inputs_digest`

**副作用判準（H4 的真正價值所在）**：dry-run 路徑跑完後，斷言

- `storage/next_tasks.json` 的 mtime 與 sha256 **完全不變**
- `storage/ops/dispatch_state.json` 中除 `last_fire_at` 外的欄位不變（`last_fire_at` 是既有的刻意行為，`scheduler.py:791-793`，需在測試中明文豁免並註明理由）
- `state.reserve_fire` 的 mock **零次呼叫**

**回歸鎖**：加一條 audit 測試，grep `decision.py` 內若出現 `open(`, `write_text`, `datetime.now` → fail。

---

## 5. 遷移路徑（分階段，每階段可獨立驗證）

依賴順序：**A3 → A1 →（H4-1..H4-3）→ D3 → H4-4 → H4-5**。

| 階段 | 內容 | 前置依賴 | 獨立驗收 |
| --- | --- | --- | --- |
| **H4-0** | 修 `--dry-run` 語意 bug：`scripts/continue_task_dispatch.py:1267` 讓 `args.dry_run` 真正抑制 `auto_refill` 與所有寫入 | 無 | 跑 `--dry-run` 前後 `next_tasks.json` sha256 不變 |
| **H4-1** | priority 解析收斂：四處改呼叫 `volpred.ops.next_tasks.normalize_task_priority` | 無（可與 A3 併行） | §4.1 測項 2 綠；四路解析對同 fixture 逐筆相等 |
| **H4-2** | 新增 `decision.py`（純函數）＋ `tests/test_dispatch_decision.py`，**shadow 模式**：`scheduler` 呼叫它但只記 log，實際仍走舊路徑，比對兩者差異 | H4-1 | shadow log 連續 72h（約 72 fires）差異率 = 0 |
| **H4-3** | `continue_task_dispatch.py` 降 library：搬離所有寫入路徑到 pool-maintenance 模組 | **A1**（writer 收斂；A1 已點名 `:509-511`） | 對該檔跑 A1 的 writer grep audit = 0 命中；`--execute` 移除 |
| **H4-4** | 切換 `scheduler` 為 `decision.py` 唯一裁決；移除 `scheduler.py:774-788` 的 pregate 否決分支；pregate 降 observational | **D3**（legacy 退役）＋ H4-2 shadow 通過 | §4.2 一致性測試綠；pregate enforce 分支不存在 |
| **H4-5** | prompt 瘦身：`cron_hourly_dispatch_prompt.md:86-99`（A0 lane）、`:118-127`（cap）改為「讀 pipeline 的 `Decision`，不自行裁決」 | H4-4 | prompt 內不再出現 cap 數字與 lane 條件；prompt diff review |
| **H4-6** | 殘留清除：`src/volpred/ops/scheduler.py` advisory lane 退役（A3 尾款）、`cron_hourly_dispatch.sh` 移 `_legacy/` | A3、D3 | `launchctl` 無殘留 spec；`_legacy/README` 更新 |

**明確不做**：不做大爆炸重寫。H4-2 的 shadow 期是整條路徑的安全閥——舊裁決仍是唯一生效者，直到差異率歸零。

---

## 6. 風險與緩解

### R1 — 收斂期間新舊路徑並存造成雙重派工（高）

`scheduler` 的 fire cap（`scheduler.py:698`，預設 2）與 `slot_budget` 的 subagent cap（`dispatch_slot_budget.py:240-279`，4/6/2）是**兩條互不知情的軸**。H4-2 到 H4-4 之間若 `decision.py` 開始影響行為而舊 prompt 規則（`cron_hourly_dispatch_prompt.md:120-127`）仍生效，同一批候選可能被兩邊各派一次。

**緩解**：
- H4-2 嚴格 shadow：`decision.py` 的回傳值在該階段**不得**被任何分支消費，只寫 log。以 §4.1 測項 10 的純函數性測試 + code review 保證。
- H4-4 切換必須是單一 commit，同時移除舊分支與啟用新 pipeline；不允許「先啟用新的、下週再拆舊的」。
- 依賴 `state.reserve_fire` 的 lease 作最後防線：任何路徑派工都必須先拿 lease，重複派工會在 lease 層失敗而非靜默成功。切換前先加一條測試驗證 lease 對重複 `task_id` 的行為。

### R2 — priority default 值變更改變既有任務排序（中）

現況三種 default（`continue_task_dispatch.py:38` → 999、`hourly_dispatch_pregate.py:158` → 9、`dispatch_slot_budget.py:102` → 4）。統一後，一批缺 `priority` 欄位的既有任務會在 `slot_budget` 側從「等同 P4」變成「隊尾 999」，可能讓 `pending P1 >= 3` 的 surge 判定結果改變，cap 由 6 掉回 4。

**緩解**：
- H4-1 前先跑一次盤點：對 `storage/next_tasks.json` 全量統計缺 `priority` / 字串 priority 的筆數，若非 0 則先做一次性 normalize（可掛在 A3 的 status migration 同一批次，A3 已有 `status_original` 保留原值的先例）。
- H4-1 的測項 2 除了「四路相等」外，另加一條 golden test：對當前真實 pool 快照，統一前後的 `budget()["cap"]` 必須相同，否則需人工裁決。

### R3 — pregate 從 enforce 降為 observational 造成 token 成本回升（中）

**2026-07-30 最終裁定：本風險的原假設被 production evidence 推翻。**
pregate 想省下 cold-load，但最終 crosscheck 的 10 個 skip candidates 有 9 個
仍產生實質工作；把同一 heuristic 搬進 `decision.py` 會保留 90% false-skip
風險，並非安全的等價功能。

**緩解**：
- 不把已證偽的 `demand` 搬入 `DecisionInput`；若未來要省 token，須以新的
  可歸因 signals 另立設計與 shadow gate，不得復活 legacy evaluator。
- H4-4 上線後 7 日監控仍保留，canonical item =
  `observation_ledger.hourly_pregate_retirement_monitor`，deadline
  `2026-08-06T19:30:00+08:00`。比較 fire frequency 與可得 provider-usage
  proxy；回退門檻仍為 >20%。
- 回退只能切回 H4-4 前 immutable release 以調查 regression；不得恢復 legacy
  executable owner 或 pregate 否決權。歷史 log 與 crosscheck 依 S9 保留。

### R4 — `continue_task_dispatch.py` 目前無生產 caller，改動缺乏實戰回歸信號（中）

該檔唯一消費者是 LLM prompt（`cron_hourly_dispatch_prompt.md:118`、`:141`）。降 library 過程若破壞某個輸出欄位，CI 可能全綠但每小時的實際派工靜默劣化——這正是 `continue_task_dispatch.py:70-77` 記載的 17h member_qa 餓死事故的同型風險。

**緩解**：
- H4-3 前先為 `build_report()` 的輸出加 schema snapshot 測試（凍結欄位名與型別），任何欄位增刪必須顯式改 snapshot。
- H4-3 完成後，prompt 側的兩處引用（`:118`、`:141`）必須在同一 PR 內同步更新，不允許跨 PR 漂移。

### R5 — burst 有 5 個 owner，收斂時最容易漏（中）

`scheduler.py:722-738`、`task_urgency.dispatch_lane`、`prompt.md:86-99`、`task_pool_claim.py:660-678`、`dispatch_burst.py:106` 分散在四個目錄。

**緩解**：
- 收斂前先建 burst 專屬 trace test：開一個 burst 窗口，跑一次完整 tick，斷言恰好一條路徑產生 fire request（目前預期會失敗，失敗本身即是基準）。
- 明確區分 **ingress 喚醒**（`task_pool_claim` 的 `request_fire`，保留）與 **裁決**（誰先做，收進 `decision.py`）——設計上這兩件事同名不同義，是漏改的主因。

---

## 7. 與計畫假設不符之處（需主線程確認）

| # | 計畫假設 | code 現況 | 建議 |
| --- | --- | --- | --- |
| 1 | 派工職責散在 **5 檔** | 實測 **10 個裁決點**（見 §1.6）：多出 `task_urgency.py`、`cron_hourly_dispatch_prompt.md`、`task_pool_claim.py`、`dispatch_burst.py`、`ops/scheduler.py` | H4 範圍應擴為 10；否則收斂後 `task_urgency` 與 prompt 仍會各自裁決 |
| 2 | `continue_task_dispatch.py` 有「advisory 分身」問題 | 比預期更嚴重：**零生產 caller**，唯一消費者是 LLM prompt。它已不是「分身」，而是「建議書」 | 降 library 的工作量比預期小（無 caller 要改），但回歸風險比預期大（無 CI 覆蓋實際行為） |
| 3 | 驗收要求「`--dry-run` 輸出與實際 fire 決策一致性測試」 | `--dry-run` 在 `continue_task_dispatch.py:1260` 宣告後**從未被讀取**；`main():1267` 無條件執行含寫入的 `build_report`。現況不存在可比對的 dry-run 語意 | 必須先加 H4-0（修 bug），才有東西可測。這是計畫未預期的前置工項 |
| 4 | pregate「明文 observational（D3）」暗示它已接近 observational | **已查證（2026-07-20）**：生產 `config/runtime_schedules.json:1450-1454` 為 `"pregate": {"mode": "shadow", "window_hours": 3.0}`。故 pregate 目前**行為上確實 observational**（`scheduler.py:781` 的 `if pregate_skip` 註解明寫 "only reachable in enforce mode"），但 enforce 分支仍在程式內、可經 config 熱重載（`scheduler.py:457-497`）單改一個字串就取得否決權。同 config note 寫「觀察 2-3 班判斷正確後改 enforce」——與 `refactor_plan_token_ops_waste` 的「刻意不翻 enforce」裁定**相矛盾**（正是 §1.2 P3 記載的 spec/裁定脫節） | D3 應把 mode 收斂為單一值並移除 enforce 分支，而非留著靠 config 自律。此為 open question Q3 |
| 5 | 「priority / starvation / cluster budget / burst 四項」為主要衝突 | 實測最嚴重的是**第五項：priority 解析本身**（4 種實作、3 種 default）。它是前四項的共同上游——不先修它，其餘三項的收斂結果仍會因輸入不一致而分歧 | 建議把 priority 正規化提為 H4-1（最先做），列為第五項裁決 |
| 6 | `dispatch_slot_budget.py` 是需要收斂的 owner 之一 | 它是唯一**無寫入路徑、純函數、已有測試**的模組（`tests/test_dispatch_slot_budget.py`）。它不是問題，缺的是 **enforcement**——`prompt.md:126` 自稱「唯一 enforcement owner」，實際 enforcement 是 LLM 自律 | 建議 `slot_budget` **不改**，直接當 `DecisionInput` 的輸入產生器；要修的是消費端 |
| 7 | legacy shell 需退役 | plist 存在磁碟但 `launchctl list` 僅見 `com.volpred.dispatch-supervisor`（PID 20346）與 `com.volpred.telegram-poll`，無 hourly-dispatch。`cron_hourly_dispatch.sh` 內的裁決（`:158-176`、`:201`）目前不生效 | D3 的工作是**檔案歸檔**而非行為變更，風險低，可提前做以縮小 H4 的 owner 數 |
| 8 | （計畫未提）rule 層對 ctd 的定位 | `.claude/rules/control-plane.md:28` 明文「dispatcher `scripts/continue_task_dispatch.py` 從這挑工」、`:124`/`:142`/`:150` 也把 categorize / vocab / refill 的 owner 指到該檔。降 library 後這四處全部過期 | H4-3 必須同 PR 改 `control-plane.md`，否則 rule 層會繼續把 ctd 當 authority（A8「權威索引落後誘發新開一層」的同型風險） |

---

## 8. 不做什麼（scope boundary）

明文列出**本 WS 不碰**的東西，避免下一輪 agent 讀到本文件後 over-reach：

| # | 不做 | 理由 |
| --- | --- | --- |
| S1 | **不改 `dispatch_slot_budget.py` 的計算邏輯** | 它是五個 owner 中唯一純函數、無寫入、已有測試（`tests/test_dispatch_slot_budget.py`）。要修的是消費端沒有機械 enforcement，不是它本身。cap 數值（BASE/SURGE/DERATE）**不在本 WS 調整** |
| S2 | **不改 `state.reserve_fire` / lease / dispatch_state.json 的治理** | §1.3 已認定「dispatch_state.json 治理成熟（lock + AST gate）是模範」。H4 只新增消費者，不動 writer 契約 |
| S3 | **不動 worker spawn / worktree 隔離** | 那是 WS-B（producer-scoped isolation）的範圍。H4 止於「決定派哪張」，不管「怎麼跑」 |
| S4 | **不做 next_tasks.json 的 writer 全面收斂** | 那是 WS-A1。H4-3 只負責把 **ctd 這一個檔** 的寫入路徑搬走，其餘 40+ writer 不碰 |
| S5 | **不做狀態機/status 詞彙收斂** | WS-A 的範圍。H4 把 status 當**輸入**讀，不重新定義終態語意 |
| S6 | **不新增第二層 gate** | 反 anti-stacking。H4 是**淨減少** enforcement 點（10 → 1 裁決 owner）。任何「再加一個檢查器來確認 pipeline 沒錯」的提案一律拒絕；正確做法是把約束寫成 `tests/test_dispatch_decision.py` 的斷言或 §4.2 的 audit grep |
| S7 | **不改 hourly prompt 的研究內容段落** | H4-5 只刪 prompt 內**裁決性**條文（cap 數字、lane 條件），把散文縮成指向 `Decision` 的 pointer。PHASE A/B 的研究任務描述不動 |
| S8 | **不做 token 成本優化** | pregate 的省 token 效果是 R3 的**約束**（不得劣化 >20%），不是本 WS 的目標 |
| S9 | **不刪 `storage/logs/hourly_pregate.jsonl` 與 `crosscheck_pregate_outcomes.py`** | 它們是 H4-4 前後的對照基準線，必須跨越切換點存活 |

---

## 9. 待裁決事項（open questions — 給主線程／老闆）

每項附選項與推薦。**本文件不自行決定任何一項。**

### Q1 — H4 的 owner 範圍要不要從 5 擴到 10？

計畫寫「5 檔」，實測 10 個裁決點（§1.6）。

- **(a) 維持 5 檔**：範圍可控，但 `task_urgency` / prompt / `task_pool_claim` / `dispatch_burst` 仍各自裁決，收斂後 burst 與 priority 仍有多 owner ⇒ H4 的驗收條「裁決集中在一個模組」實質不成立。
- **(b) 擴為 10，一次做完**：範圍近乎翻倍，跨 `scripts/` 與 `src/volpred/ops/` 兩樹，單一 PR 風險高。
- **(c) 擴為 10 但分兩批**：H4-1..H4-4 先收 A–E 五檔＋priority 正規化（含 F 的 `_priority`）；F–J 的 burst 收斂另立 H4-7。

**推薦 (c)**。理由：priority 正規化（4 種實作）必須一次做完否則無意義，但 burst（5 owner、跨 ingress 與裁決兩種語意，R5）值得獨立一輪並先有 trace test 當基準。

### Q2 — `continue_task_dispatch.py` 的 CLI 要保留還是刪除？

該檔零生產 caller，唯一消費者是 prompt（`cron_hourly_dispatch_prompt.md:118`、`:141`）。

- **(a) 全刪 CLI，純 library**：最乾淨，但 prompt 的兩處 `--report` 呼叫要同步改為讀 pipeline receipt，且失去人工診斷入口。
- **(b) 保留 read-only 診斷 CLI**：`--dry-run` 修成真 no-write、刪 `--execute`；prompt 改讀 `Decision` receipt，CLI 只給人用。
- **(c) 現狀不動**，只搬寫入路徑。

**推薦 (b)**。理由：診斷入口有實際價值（17h member_qa 餓死事故就是靠人跑這支發現的，`continue_task_dispatch.py:70-77`），但必須先修 §1.2 的 `--dry-run` 假旗標，否則「診斷」動作本身會改 state。

### Q3 — pregate 的 enforce 分支：移除還是保留？

**2026-07-30 決議：採 (a)，並進一步完整 retire。** Production shadow
在 capacity + novelty rewire 後最終累積 10 個 skip candidates，其中 9 班有實質
產出（90% false skips，門檻 ≤10%）。`runtime_schedules.json` 已移除 pregate config，
`decision.py` / `scheduler.py` 已移除 collect/enforce 分支；保留的 evaluator
CLI 只回報 `retired/no-decision`，不再寫入 gate evidence。歷史 log 與 crosscheck 儀器依 S9
保留，僅供退役前後對照，不是 runtime authority。

生產 mode 已是 `shadow`（§7 item 4），但 enforce 分支仍在 `scheduler.py:781-788`，改一個 config 字串即生效；而 token_ops_waste gate 已裁定「刻意不翻 enforce」。

- **(a) 移除 enforce 分支**：程式碼即宣告，config 的 `mode` 退化為「是否寫 log」。符合 D3「明文 observational」。
- **(b) 保留分支、config 註記 deadline**：留一條快速回退路徑，但違反「觀察期必有 deadline」原則的精神（此觀察期已掛 18 天，§1.2 P3）。
- **(c) 先翻 enforce 觀察，再決定**：與既有裁定衝突。

**推薦 (a)**，且與 H4-4 同 commit。理由：現況是「裁定說不翻、shell 註解說 validating ~1 week、config note 說觀察 2-3 班後改 enforce」三方脫節，任何保留都在延續脫節。真要回退，git revert 單一 commit 比留一個熱重載開關安全。

### Q4 — dry-run 一致性的驗收標的是哪一個 dry-run？

現有兩個都壞：ctd 的 `--dry-run` 從未被讀（§1.2），scheduler 的 dry-run 繞過 pregate（§1.1）。

- **(a) 以 scheduler 的 `_tick(dry_run=True)` 為準**：貼近 H4「收斂到 supervisor」的終態，但需先修 pregate 繞過問題（即需 H4-4 先落地）。
- **(b) 以 ctd 的 `--dry-run` 為準**：可在 H4-0 立即修好、立即測，但測的是即將降為 library 的東西，H4-4 後要重寫測試。
- **(c) 兩個都修，驗收綁 scheduler**。

**推薦 (c)**。理由：ctd 的 dry-run bug 是**現在就會造成真實 state mutation** 的安全問題（任何人以為在 dry-run 卻觸發 refill/retire/sweep），不應等 H4-4；但 H4 的正式驗收條應綁在終態（scheduler）上。

### Q5 — priority default 統一為哪個值？

現況 999（ctd 隊尾）／9（pregate）／4（slot_budget）／`None`（task_urgency）。

- **(a) 統一為隊尾（999）**：語意最安全（缺欄位不會意外插隊），但會改變 `slot_budget` 的 surge 判定（R2）——一批缺 priority 的任務從「等同 P4」變隊尾，`pending P1>=3` 的計數不受影響但 cap 相關統計會動。
- **(b) 統一為 4**：對 `slot_budget` 零行為變更，但 ctd 側缺欄位任務會從隊尾躍升至 P4，可能排到真 P4 之前。
- **(c) 先一次性 normalize 資料（補齊所有缺欄位），再統一為 999**。

**推薦 (c)**，normalize 掛在 A3 的 status migration 同批次（A3 已有 `status_original` 保留原值的先例）。理由：符合「永遠修流程不修資料」的下半句——流程修好後才做一次性 migration，且此處 default 之爭的根因是資料髒，補乾淨後 default 選哪個都不再有行為差異。

### Q6 — H4-2 的 shadow 期要多久？

本文件 §5 暫定 72h（約 72 fires）差異率 0。

- **(a) 72h**：符合原則 5「觀察期必有 deadline」，但樣本量小（72 次 fire 中真正有候選的更少）。
- **(b) 7 天**：樣本足，但與「pregate shadow 掛 18 天」的前車之鑑同型 —— 長觀察期本身就是拖延的偽裝。
- **(c) 以事件數為準**：累積 30 次「有候選且實際 fire」的 tick 差異率為 0 即通過，設 7 天硬上限，逾期未達標即視為設計有問題並回報。

**推薦 (c)**。理由：時間窗會被低活動期稀釋；事件數才是真正的統計量，加硬上限則避免無限觀察。
