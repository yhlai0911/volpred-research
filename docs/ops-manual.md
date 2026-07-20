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
| **compute-worker** | **連續運轉**（2026-07-20 D6） | 重算力工作（回測/GARCH/bootstrap）不耗 token — 佇列有工就連續消化到空、最多 3 個平行；15 分 tick 只是「掛了自動重啟」的保險 |
| **check-alerts** | 每小時整點 | 唯一可靠的鬧鐘：先跑到期排程（piggyback），再檢查告警條件 |
| **dreaming + loop-health** | 每日 05:25 / 每小時 | 慢迴圈找反覆出事的模式、快迴圈量測「系統有沒有在變好」。2026-07-20 F3F5 補上兩個盲點：**每個 alert 自動留立案候選**（同類事故第二次出現時系統「記得」它是老問題，不再靠人記）；**觀察期帳本**（任何 shadow／待退役狀態逾期未決策自動升 breach，不再無限掛著） |

**重構後新增的三張自癒安全網**（本次重構的核心成果）：

1. **任務殭屍三層回收**：agent 被 kill 或 timeout → 當場把任務還回佇列（A2b/A2c）；漏網的 → 每小時 cleanup 用任何可用時間戳判齡回收（A2a）；連時間戳都沒有的 → 每小時 liveness reconciler 用「進程死亡 + 磁碟無 worktree」雙證據回收（A4）。**效果：任務不再卡死 20 小時沒人管**（上線當天就自然回收 8 筆歷史殭屍）。
2. **發佈同步收斂網**：文章改稿一律走 publisher 單一出口，同時推 Supabase + Mirror，失敗進死信（C1）；每小時全量對帳把任何漏推的補齊（C2）；死信每 30 分自動重試、含 Mirror（C4）；變更偵測只剩一套判準（C3，順帶抓到並根治「瀏覽數 seed 被同步清掉」的潛伏 bug — 你指示的瀏覽數顯示從此受 server-resident 保護）。**效果：「網站顯示舊內容一個月沒人發現」這類事故結構性絕跡**。
3. **治理防漂移**：enforcement 總表與實況不一致 = CI 紅燈（F1）；dedup 內容黑洞有三條件自動告警（F2）；front-end feed 順序有機械 regression 鎖住「新的永遠在上面」。
4. **佇列寫入與詞彙全面機械管制**（2026-07-20 A1b+A3）：佇列的每一條寫入路徑只能走 canonical helper（44 個寫入點全數收斂，新的非法寫法會被 `NEXT-TASKS-ROUTING` audit 攔下）；任務狀態與 blocked 原因只准受控詞彙，歷史汙染已全部清洗歸零（原值保留可稽核）— 任何新汙染 = CI 紅燈。
5. **工作產物落地保證**（2026-07-20 WS-I，你的「杜絕無效工作」指令）：擱淺的 worktree 產物每 6 小時自動開裁決單（合併／搶救／棄置三出口明寫單上，不再永久卡住）；發不出去的草稿自動開修復單（不再只有紅燈沒人管）；實驗沒進知識庫的增量已被 CI ratchet 封死。**每一份做出來的工作都有去處或明確裁決，不再白做。**

---

## 2. 任務怎麼派（新設計）

### 2.1 任務的一生（單一狀態機）

```
建立(ops assign 唯一入口) → pending → claimed → in_progress → succeeded/failed/blocked
                                ↑__________釋放/回收(三層安全網)__________|
```

- **唯一入口**：`uv run volpred ops assign --title ... --description ... --priority N`。所有人為任務（你、我、Telegram、email）都走這裡 — 不再有第二個佇列。
- **唯一佇列**：`storage/next_tasks.json`。所有寫入走 canonical helper（防檔案寫壞），claim/complete 走 `scripts/task_pool_claim.py`（跨 session 檔案鎖）。
- **優先序**：P1 急件 ≈ 時效性 > P2 排程 > P3 日常。任務年齡會解鎖飢餓保護（P1 超過 6 小時沒人接會被強制推頭）。

### 2.2 急件直達（你最常用的）

**P1 任務入池的瞬間**，系統自動叫醒 supervisor（`request_fire`），**不等下一班整點** — 從你下指令到 agent 開工 ≤60 秒。三條 ingress 全接通：`ops assign`、Gmail、事件驅動（CI 紅燈等）。

### 2.3 執行車道（dispatch_lane）— 本次新增的隔離機制

| lane | 誰執行 | 用途 |
|---|---|---|
| `agent`（預設） | hourly dispatch 自動消化 | 一般任務：文章、實驗、資料、平台修補 |
| `main_thread` | 只有互動 session 的我 | **改運營機器本身的任務**（重構、派工邏輯、佇列機制）— hourly agent 連 claim 都會被機械拒絕 |
| `blocked` | 沒人 | 卡外部條件，到期自動回 pending |

**為什麼**：2026-07-20 實證 — 讓排程 agent 改派工系統自己 = 未隔離的自我改造（3 個 agent 同時在共用工作區改佇列程式）。現在 claim 入口直接 enforce，這類任務只能由主線程在專屬 session + worktree 隔離下執行。

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
| **Telegram** | 即時互動回覆 + 逐程序進度回報（結論/驗證/產物/下一步，宣稱完成必附實測） | `scripts/progress_report.py`（唯一） |
| **Email** | 週期摘要、需要你決策的事（🔴 標題 + mailto 快速回覆）、告警、skill 修改通知 | `volpred ops send-alert` + 排程報告 |

**分工原則**：Telegram = 「現在正在發生什麼」；Email = 「定期總結 + 需要你出手的」。
**收信量收斂（2026-07-20 H2 已落地）**：定期信從最多 7 班/日收斂為 **4 班/日** — boss_report 08:10／14:10／20:10 三班（晚班含完整日結，原 work_summary 已併入退役）+ token 報告 08:00 一班（原三班合一）。通道職責矩陣已入 enforcement 總表。

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
| 看任務佇列 | `uv run python scripts/task_pool_claim.py list --status pending --limit 10` |
| 監控 dashboard | http://127.0.0.1:8787 |

---

## 5. 活文件維護

**更新節奏（owner 2026-07-20 指定）：任何新優化或新功能落地時即時更新本檔**（不是等 Phase 收尾）；計畫 §7 每列驗收含「本檔已同步」。
架構細節 → `docs/architecture.md`；排程真相 → `config/runtime_schedules.json`；
控制面規則 → `.claude/rules/control-plane.md`；重構進度 → `docs/refactor_plan_ops_master_2026_07.md` §7。
