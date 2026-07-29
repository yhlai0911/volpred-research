# VolPred 平台操作流程說明（2026-07-20 重構後新設計）

> 給老闆看的白話版操作手冊：平台怎麼自己運轉、任務怎麼派、你跟系統怎麼互動。
> 對應重構計畫：`docs/refactor_plan_ops_master_2026_07.md`（§7 為進度真相）。
> 標 🔜 的段落 = Phase 2 還會再收斂，其餘皆為已上線並驗證的現行設計。

---

## 1. 平台怎麼 24/7 自己運轉

四個常駐機制，session 關掉照跑：

| 機制 | 節奏 | 做什麼 |
|---|---|---|
| **dispatch-supervisor**（daemon） | 每 ≤60 秒評估 | 唯一派工引擎：挑任務、開 agent、看管執行、收屍。派工裁決集中在單一純函數（2026-07-20 H4），dry-run 預覽與真實派工**保證同一套判斷** |
| **compute-worker** | **Operations Core 每 15 分喚醒，單次連續排空** | 重算力工作（回測/GARCH/bootstrap）不耗 token — 佇列有工就連續消化到空、最多 3 個平行；queue flock 防止重疊 drain。`cron_compute_worker.sh` 只是 executor wrapper，不是時鐘；舊 `com.volpred.compute-worker` LaunchAgent 已退役 |
| **check-alerts** | 每小時整點 | 唯一可靠的鬧鐘：先跑到期排程（piggyback），再檢查告警條件 |
| **dreaming + loop-health** | 每日 05:25 / 每小時 | 慢迴圈找反覆出事的模式、快迴圈量測「系統有沒有在變好」。2026-07-20 F3F5 補上兩個盲點：**每個 alert 自動留立案候選**（同類事故第二次出現時系統「記得」它是老問題，不再靠人記）；**觀察期帳本**（任何 shadow／待退役狀態逾期未決策自動升 breach，不再無限掛著） |

**重構後新增的三張自癒安全網**（本次重構的核心成果）：

1. **任務殭屍三層回收**：agent 被 kill 或 timeout → 當場把任務還回佇列（A2b/A2c）；漏網的 → 每小時 cleanup 用任何可用時間戳判齡回收（A2a）；連時間戳都沒有的 → 每小時 liveness reconciler 用「進程死亡 + 磁碟無 worktree」雙證據回收（A4）。**效果：任務不再卡死 20 小時沒人管**（上線當天就自然回收 8 筆歷史殭屍）。
2. **發佈同步收斂網**：文章改稿一律走 publisher 單一出口，同時推 Supabase + Mirror，失敗進死信（C1）；每小時全量對帳把任何漏推的補齊（C2）；死信每 30 分自動重試、含 Mirror（C4）；變更偵測只剩一套判準（C3，順帶抓到並根治「瀏覽數 seed 被同步清掉」的潛伏 bug — 你指示的瀏覽數顯示從此受 server-resident 保護）。**效果：「網站顯示舊內容一個月沒人發現」這類事故結構性絕跡**。
3. **治理防漂移**：enforcement 總表與實況不一致 = CI 紅燈（F1）；dedup 內容黑洞有三條件自動告警（F2）；front-end feed 順序有機械 regression 鎖住「新的永遠在上面」。
4. **佇列寫入與詞彙全面機械管制**（2026-07-20 A1b+A3）：佇列的每一條寫入路徑只能走 canonical helper（44 個寫入點全數收斂，新的非法寫法會被 `NEXT-TASKS-ROUTING` audit 攔下）；任務狀態與 blocked 原因只准受控詞彙，歷史汙染已全部清洗歸零（原值保留可稽核）— 任何新汙染 = CI 紅燈。
5. **工作產物落地保證**（2026-07-20 WS-I，你的「杜絕無效工作」指令）：擱淺的 worktree 產物每 6 小時自動開裁決單（合併／搶救／棄置三出口明寫單上，不再永久卡住）；發不出去的草稿自動開修復單（不再只有紅燈沒人管）；實驗沒進知識庫的增量已被 CI ratchet 封死。**每一份做出來的工作都有去處或明確裁決，不再白做。**
6. **發文圖組自癒鏈**（2026-07-20 晚間，你的「立刻重新設計」+「換免費路徑」指令）：懶人包圖改三層鏈 — codex（額度死秒跳過）→ **agy 免費層** → deterministic **機械自我修復**（縮字級/換行/加高卡片重畫 ≤3 輪，零 LLM 額度）。失敗分類接上：額度牆走 backoff 自動重排、三層全敗自動開 P1 修復單；每小時巡檢真的會重排擱淺的 render（`requeue-stranded`，冪等、每篇 ≤3 次）。**「圖生不出來 → 文章永遠卡草稿」的死結結構性消失。** 另附幻覺防線：警報宣稱「系統會自動做 X」的每一條都掛機械驗證的 owner + 測試，文案再也不能宣稱不存在的自動化。
7. **PHASE-Z 收班死結拆除**（2026-07-20 晚間）：gate 檔改動不再連坐整批（單獨保留待審、其餘照常提交）；每小時被 daemon 改寫的共享狀態檔不再被 pin 進補交 receipt（「放棄認領」孤兒警報從此根絕）。
8. **派工 worker 猝死秒級回收**（2026-07-21）：claude CLI「落地即死但不退出」的班（log 只有 Execution error 那種），改由 debug sidecar 活性訊號在 3-4 分鐘內判死回收 — 原本要白吃 10-50 分鐘 hang 上限；任務當場退回佇列重派、不發 CRITICAL；警報一律報實際卡住時長，文案不得超出事實。

---

## 2. 任務怎麼派（新設計）

### 2.1 任務的一生（單一狀態機）

```
建立(ops assign 唯一入口) → pending → claimed → in_progress → succeeded/failed/blocked
                                ↑__________釋放/回收(三層安全網)__________|
```

- **唯一入口**：`uv run volpred ops assign --title ... --description ... --priority N`。所有人為任務（你、我、Telegram、email）都走這裡 — 不再有第二個佇列。
- **唯一佇列**：`storage/next_tasks.json`。所有寫入走 canonical helper（防檔案寫壞），claim/complete 走 `scripts/task_pool_claim.py`（跨 session 檔案鎖）。
- **優先序（2026-07-21 重構，根治「你的任務排不上」）**：選擇順序 = **你的急件（boss 來源 P1）永遠第一** → 時效性任務（event_article 等，看類型不看數字）→ 其餘按 P2/P3 + 飢餓保護 + 多樣性輪替。**系統自動產生的任務禁止自封 P1**（入池時機械夾到 P2）— P1 從此只屬於你和真急件，「大家都是 P1 = 沒有優先序」的通膨結構性消失。生成端另有水位閘（池太深自動停產，你的任務不受閘）。

### 2.2 急件直達（你最常用的）

**P1 任務入池的瞬間**，系統自動叫醒 supervisor（`request_fire`），**不等下一班整點** — 從你下指令到 agent 開工 ≤60 秒。三條 ingress 全接通：`ops assign`、Gmail、事件驅動（CI 紅燈等）。

### 2.3 執行車道（dispatch_lane）— 本次新增的隔離機制

| lane | 誰執行 | 用途 |
|---|---|---|
| `agent`（預設） | hourly dispatch 自動消化 | 一般任務：文章、實驗、資料、平台修補 |
| `main_thread` | 只有互動 session 的我 | **改運營機器本身的任務**（重構、派工邏輯、佇列機制）— hourly agent 連 claim 都會被機械拒絕 |
| `blocked` | 沒人 | 卡外部條件，到期自動回 pending |

**為什麼**：2026-07-20 實證 — 讓排程 agent 改派工系統自己 = 未隔離的自我改造（3 個 agent 同時在共用工作區改佇列程式）。現在 claim 入口直接 enforce，這類任務只能由主線程在專屬 session + worktree 隔離下執行。

### 2.4 排程 agent 也全面隔離（2026-07-20 WS-B 試點上線）

platform_ops 類的排程 agent 現在**每班配一個機械指派的隔離工作區**（agent 無法自選身分）：產出在自己的 worktree 完成 → 通過測試 gate 才併進 main；gate 沒過 = 自動開修復單（產出保留、不會爛掉也不會死鎖）。「誰改了什麼」由隔離本身直接證明，不再靠事後推理猜作者 — 這是根治「PHASE-Z 認錯作者」六次復發的終極方案。觀察窗至 08-03：兩週零事故就擴大到 governance 類並退役舊的猜作者邏輯。

### 範例：你要系統做一件急事

```
你（Telegram）:「XX 數據好像斷了，查一下」
  → telegram_poll 秒建 P1 telegram_reply 任務 → 專屬 responder 立即 spawn
  → responder 能當場答的直接回你
  → 需要改 repo 的：responder 建 P1 assign 任務 → request_fire → ≤60s agent 開工
  → 完成後 Telegram 回你結果（先回覆才能 complete，機械強制）
```

---

## 3. email / Telegram 互動（新設計）

### 3.1 入站（你 → 系統）

| 通道 | 處理方式 | 延遲 |
|---|---|---|
| **Telegram** | 專屬 responder **即時** spawn 處理（不排隊）；失敗 120 秒內重派；repo 級工作升級為 P1 assign 並直達派工 | 秒級 |
| **Email**（回信含 `[VolPred` 標題） | gmail-poll 每 15 分收件 → 先寄 ACK → 建 P1 email_reply + request_fire → 完工寄 CLOSE 信 | ≤15 分 + ≤60s |

**防呆**：同一則訊息的回覆權綁 claim — 兩個 session 不可能對你同一句話矛盾雙回（guard 機械拒發）。

### 3.2 出站（系統 → 你）

| 通道 | 內容 | Owner |
|---|---|---|
| **Telegram** | 即時互動回覆 + 逐程序進度回報（結論/驗證/產物/下一步，宣稱完成必附實測）+ 具 delivery receipt 的指定事件通知 | responder／`telegram-send`；`scripts/progress_report.py`（逐程序進度唯一 owner）；typed notification pipeline |
| **Email** | 週期摘要、需要你決策的事（🔴 標題 + mailto 快速回覆）、告警、skill 修改通知 | `volpred ops send-alert` + 排程報告 |

**分工原則**：Telegram = 「現在正在發生什麼」；Email = 「定期總結 + 需要你出手的」。
`volpred ops send-alert` **不得直接鏡像 Telegram**：逐程序進度的唯一 owner
是 `scripts/progress_report.py`；互動回覆由 responder／`telegram-send` 負責，另有
delivery receipt 綁定的 GitHub comment typed pipeline。這些用途彼此分工，避免同一
事件被 alert 層與進度層各送一次。Alert 依 remediation disposition 路由：

- `owner_decision`：立即寄 email（標題含 `[新架構派發]`；需要回覆時另有
  `🔴【需老闆回信】`）。
- `recovery`：只寄一封驗證完成 email，不發 Telegram。
- 平台已建修復 task／正在 self-heal：只記入 dedup + incident lifecycle，不立即外送；
  連續修復失敗達 escalation gate 才寄 email。
- 一般 record／週期摘要：email；24 小時相同 level+title 去重。

Owned-email durable command 的 idempotency key 同時綁定 payload hash；同 title 從
record 升級成 owner decision 時可安全成為新 command。若 command conflict，警報
runner 只記成 `owned_email_command_conflict` transport incident（含 effect evidence），
不得再誤分類為 `host_cron_fail`。
**收信量收斂（2026-07-20 H2 已落地）**：定期信從最多 7 班/日收斂為 **4 班/日** — boss_report 08:10／14:10／20:10 三班（晚班含完整日結，原 work_summary 已併入退役）+ token 報告 08:00 一班（原三班合一）。通道職責矩陣已入 enforcement 總表。
Boss Report 的內容以 master spec §7 與當前 task-pool mode 為準，不再引用 5 月的 cycle 暫存檔；寄信則先讀 `email.ops_alert` durable owner。正常 `operations_core` 路徑會留下 WorkItem／EffectRequest／outbox／Gmail Sent 回讀證據，只有資料庫明確切回 `legacy` 才可使用 direct SMTP rollback；owner 讀取失敗一律不寄。
同一個排程 fire 會先驗證 canonical generation／cron slot／digest，再跨主機讀回既有
command 或 terminal receipt。Rollback 路徑也受 Primary Authority 保護，並以固定
Message-ID 先查 Gmail Sent；所以重啟 Codex／Claude、切換 Mac 或重跑同一班次，
都不會因本機 cache 不同而再寄一次。
2026-07-26 production acceptance 已實測：首次 fire 只有一筆 delivered attempt，
同 fire 重跑只回相同 terminal receipt，沒有第二次 provider send。2026-07-27 08:10
台灣時間的下一筆自然 scheduler receipt 亦由 Operations Core attempt 1 成功，RPC
回讀同一 WorkItem／Effect／Gmail Sent evidence，owner 維持 `operations_core/4`；
此 caller 的 sustained-clean gate 已完成。

### 範例：一篇文章從產出到你看到

```
選題(查重三層) → agent 寫作(worktree) → 發佈 gate(anti-AI/圖表/dedup)
  → publisher 單一出口寫 feed + 推 Supabase + Mirror（任一失敗進死信）
  → 每小時全量對帳網補漏 + 每 30 分死信重試
  → 前端嚴格按發佈時間新到舊顯示（機械 regression 鎖住）
  → 你在 Telegram 收到進度回報；重大發佈另有 email
```

### 範例：系統自己出事自己修

```
某 agent hang 死 → supervisor 60s 內偵測 → kill 整個 process group
  → 同一口氣把它佔的任務還回佇列（A2b/A2c，不再等人發現）
  → 下一班 fire 重新派工 → dreaming 記錄模式，同類三次 = 自動升級 3-strike
  → 你只在「需要決策」時收到信，其餘全自動
```

---

## 4. 你需要知道的指令（速查）

| 要做什麼 | 指令 |
|---|---|
| 看平台現況（30 秒） | `uv run python scripts/ops_snapshot.py` |
| 大體檢（result-level） | `uv run python scripts/daily_checkup.py` |
| 指派任務 | `uv run volpred ops assign --title "..." --description "..." --priority 1` |
| 看任務佇列（計數＋列表） | `uv run python scripts/ops_snapshot.py --queue --status pending --limit 10` |
| 查單一任務狀態 | `uv run python scripts/ops_snapshot.py --task <id 或標題關鍵字>` |
| 查某篇文章狀態（不拉 content） | `uv run python scripts/ops_snapshot.py --article <mile_id 或 slug>` |
| 查排程 job 有沒有活著 | `uv run python scripts/ops_snapshot.py --job <schedule_id>` |
| 盤點 worktrees（未合併/dirty） | `uv run python scripts/ops_snapshot.py --worktrees` |
| 看最近幾班派工結果 | `uv run python scripts/ops_snapshot.py --receipts 5` |
| 監控 dashboard | http://127.0.0.1:8787 |

（G2 子命令一律回極簡 JSON <2KB，取代手寫 jq/grep 翻 `next_tasks.json` / `feed.json` / cron log。）

---

## 5. 活文件維護

**更新節奏（owner 2026-07-20 指定）：任何新優化或新功能落地時即時更新本檔**（不是等 Phase 收尾）；計畫 §7 每列驗收含「本檔已同步」。
架構細節 → `docs/architecture.md`；排程真相 → `config/runtime_schedules.json`；
控制面規則 → `.claude/rules/control-plane.md`；重構進度 → `docs/refactor_plan_ops_master_2026_07.md` §7。
