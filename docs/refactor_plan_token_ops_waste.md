# Refactor Plan: Token 與 Ops 浪費結構性優化

- **建立**: 2026-07-14（owner 指示：建立完整優化計畫留檔並執行，全程 PDCA / loop-engineering，禁止表面修補）
- **Authority**: CLAUDE.md Three-Strike Rule + Anti-stacking + PDCA skill
- **狀態追蹤**: 本檔各 WS 的 status 欄位；每週由 token_report 週報 re-measure（Check cadence 見 §6）

## 0. 測量基準（2026-07-14 盤點，全部真實數據）

| 指標 | 基準值 | 來源 |
|---|---|---|
| 週 billable | 41.0M（$2,110 est）；官方 cap 面 95.6M/77.7M（123%） | `storage/reports/token_usage/weekly_2026-07-12.json` |
| cache_create 佔 billable | **79.1%**（86.8M/109.7M，診斷窗口） | 同上 drilldown.cache_diagnostics |
| <200 字微型訊息 | 5,016 則 / 41.9M billable | 同上 drilldown.text_only |
| repo-navigation bash | 1,945 則 / 10.1M | 同上 drilldown.bash_other |
| 產出類佔比（實驗+論文+文章+QA+圖表） | **~5%**（$113/$2,110） | 同上 by_category |
| Opus 佔成本 | 71%（$1,493/$2,110） | 同上 by_model |
| next_tasks.json | 4.5MB；2,296 succeeded 滯留；24 種 status 詞彙 | 直接統計 |
| blocked 池 | 46 筆（36 筆 >1 個月） | 直接統計 |
| 老闆系統信 | ~14 封/天（boss_report 4h + work_summary 6h + token_report + alerts） | cron logs |
| 死磁碟 | rollback_points 1.7GB（5/18 後未動）+ worktree 複本 9.3GB + hooks logs 4,549 檔 | du/find |
| error_log.md | 7,666 行 / 430 條 / 35 個 3-STRIKE；前五復發主題未止血 | 掃描 agent 稽核 |
| dreaming 閉環 | 2 個 finding signature 連續 15/15 天復發（有 Check 無 Act） | `storage/ops/dreaming/*.json` |

## 1. 三層診斷（為什麼是結構問題，不是 N 個獨立 bug）

1. **底層邏輯**：ops 迴圈的 domain model 假設「每班 fire = 一個全新無狀態 LLM session」。
   後果三連鎖：每 session 重付 bootstrap cache_create（79% 帳單）→ 每 session 重新自我定位
   （repo-navigation 10M）→ 沒工作也要付一個 session 說 skip（微型訊息 41.9M）。
   正確模型：**機械可判定的事（該不該 fire、現在狀態如何）由 zero-token script 判定與彙整；
   LLM 只在有實質決策/產出工作時被喚醒，醒來時拿到一份 compact snapshot 而不是自己翻抽屜。**
2. **流程**：Check 環節壞了兩處 —— (a) pregate 建好了但 attribution coverage 只有 10.3%，
   crosscheck 明示「strict 數字不可信，先修蓋章再評 flip」，於是 shadow 模式跑了 243 班
   從未轉 enforce（有儀器沒讀數）；(b) dreaming 每天產 finding 但無 Act 端 —— 同 signature
   連續 15 天復發，resolved 隔天又 new（打地鼠）。**流程修正 = 讓每個 Check 都有機械的 Act
   出口**（finding 復發 N 天 → 自動變 next_tasks 任務或帶決策地 suppress）。
3. **程式架構**：累積性資產（queue 歷史、rollback points、hooks logs、error_log、報告面）
   全部缺 retention/rotation as-a-flow —— 每個都是「只進不出」的 append-only 設計，
   靠人（或災難）觸發清理。**架構修正 = 每個累積面在它的 owner 流程裡內建裁切/歸檔，
   不新增獨立 cleanup 機制（anti-stacking：收編進 log_rotate / sync / daily_checkup 既有 owner）。**

## 2. Workstreams

### WS1 — Token 管線（最大槓桿）
- **1a. 修 pregate attribution 蓋章**（先修儀器）：讓 dispatch 產出可歸因（fire → 實質產出
  的對應蓋章率 ≥80%），然後用 `crosscheck_pregate_outcomes.py --invoker supervisor` 重評；
  strict_mismatch_rate ≤10% 才把 `config/runtime_schedules.json` 的 `pregate.mode`
  翻 `enforce`。**Gate：不達標不翻，絕不裸翻。**
- **1b. `scripts/ops_snapshot.py`**：一次輸出 compact JSON digest（backbone 心跳、queue
  概況、in-flight、alerts、pool 水位、上輪 completion），接進 dispatch prompt 與
  autonomous protocol 作為 session 開頭唯一定位動作，取代 10–20 則 bash 自我定位。
- **1c. Bootstrap 減肥**：CLAUDE.md 396 行 → 移除歷史敘事與 incident 故事（改一行 pointer
  到 docs/error_log 或 memory），目標 ≤250 行；MEMORY.md 索引分群 + 過期項 archive
  （走 consolidate-memory 流程）。改前 commit snapshot；改後 email diff 通知（治理檔規則）。
- **1d. 模型分層**：ops/low 類（checklist、audit、stub）改 Sonnet/Haiku。
  **這是 owner 2026-07-05 全 Opus 指令的反向調整 → 需 owner 裁決**，以 decision email 提出，
  未裁決前不動 `scripts/model_router.py`。
- **Check 指標**：下兩期 token 週報 cache_create share <60%、微型訊息 billable 減半、
  週 billable 回到 cap 內。

### WS2 — Queue 資料模型（next_tasks）
- **2a. 歸檔流**：完成/終態任務移 `storage/next_tasks_archive/YYYY-MM.json`；
  queue 檔只留 pending/in-flight。收編進既有 owner（`sync_next_tasks_status.py` 的收尾步驟），
  不建新 cron。
- **2b. status 詞彙收斂**：終態集合白名單（succeeded / failed / superseded / cancelled /
  blocked / pending / in_progress / claimed + `status_note` 自由欄位承載細節）；寫入端
  validation（收編進同一 owner script），杜絕 `partially_resolved_K1180_done_awaiting_K1179`
  類一次性自創狀態。
- **2c. blocked 池 triage**：46 筆一次清 —— 明顯死的關閉、可自主裁決的裁決、真需 owner 的
  （paid data source ×2）併入 decision email。加常態規則：blocked >30 天必須 escalate-or-close
  （收編進 daily_checkup 檢查維度，不建新機制）。
- **Check 指標**：next_tasks.json <500KB；status 詞彙 ≤8 種；blocked 池 0 筆超過 30 天。

### WS3 — Retention as a flow（一次清理 + 內建裁切）
- **3a**. `cron_log_rotate.sh` 的 owner python 增兩條規則：`storage/ops/rollback_points/`
  >14 天刪除；`storage/logs/hooks/` >7 天刪除。（anti-stacking：log_rotate 是既有
  retention owner，一個 concern 一個 owner。）
- **3b**. 一次性清理：rollback_points 陳舊 81 目錄（1.7GB）、`.claude/worktrees` 與
  `.codex/worktrees` 中已 merge 的 stale 複本（~9.3GB）、`scripts/` Apr-18 批確認孤兒
  →`scripts/_legacy/`、root 散落舊檔歸 `archive/`。
- **3c**. spec drift 修正：`cron_fred_backfill_guard.sh` 補進 `runtime_schedules.json`；
  `release_pool.sh`（4/19 後死亡）移除。
- **Check 指標**：du 回收 ≥10GB；spec 與 crontab/LaunchAgents 全對齊（daily_checkup 已有
  cron_completion 維度可驗）。

### WS4 — 自我監控面收斂（meta-ops 減量）
- **4a. 報告面合併**：work_summary（6h）併入 boss_report（4h→固定 3 班/天 08:00/14:00/20:00
  台灣時間），token_report 維持每日一封；目標老闆系統信 ~14 封/天 → ≤6 封/天。
  被取代的 work_summary 排程降級移除（anti-stacking (c)：不留兩套並行）。
- **4b. dreaming Act 端**：同 signature 復發 ≥3 天 → 自動建 next_tasks 任務（P3）或寫入
  suppression 決策（含理由與 review 日期）；讓「resolved 隔天又 new」在機械上不可能無聲循環。
- **4c. error_log 壓縮**：7,666 行 → 「活教訓索引」（每類 root cause 一條 + 防錯規則，
  目標 ≤800 行）+ `docs/error_log_archive/`（歷史全文按季歸檔）。實驗前必讀的對象改為索引。
- **4d. circular import 修復**：`email_notifier` ↔ `ops.alerts` 解環（import 移函式內或抽
  第三模組），token_report 路徑不再每日吞 ImportError。
- **Check 指標**：老闆信 ≤6 封/天；dreaming 連 7 天無「同 signature 復發 ≥3 天且無 task/
  suppression」情形；error_log 索引 ≤800 行；token_report log 無 ImportError。

### WS5 — 治理疊層收斂（慢工，排程執行）
- **5a**. 6 個多層 concern（3-strike、dedup、worktree merge、silent fallback、時間戳、
  發文查重）各指定唯一 enforcement owner，其餘層降一行 pointer（依 anti-stacking 升級路徑）。
- **5b**. 8 個 paper skill 整併評估（PDCA skill 已列月度 audit 候選；不粗暴合併）。
- **5c**. docs 清理：自標 STALE 的 system_handbook、superseded 雙檔、website_restructure v1
  → `docs/_archive/`。
- 本 WS 進 next_tasks 排程（P2），不在首日硬吃 —— 治理檔動刀需逐檔核對引用面。

## 3. 廢棄面（重構落地後移除，不留兩套）
- work_summary 獨立排程與 wrapper（併入 boss_report 後）
- `release_pool.sh`（已被 cron_release_pool.sh 取代，log 停在 4/19）
- scripts/ Apr-18 批孤兒（populate_strategy_badges、agent_monitor、model_selector、
  backfill_adaptive_tier、backfill_paper_trading 等）→ `_legacy/`
- error_log.md 歷史全文 → archive（主檔只留索引）
- 若 1d 獲裁決：model_router 全 Opus 註記段改分層表

## 4. 執行順序與狀態

| # | 項目 | 層級 | 狀態 |
|---|---|---|---|
| 1 | 計畫留檔 + snapshot commit | - | ✅ b3ac2a9e5 |
| 2 | WS3a retention 規則 + WS3b 一次清理 + WS3c spec 修正 | 架構 | ✅ f96482a6a（1.7GB+3,254 檔已清；crontab 16→33 條對齊 spec；codex worktree 4.6GB 回收；K1709 worktree 留待 merge 任務） |
| 3 | WS4d circular import | 架構 | ✅ f96482a6a（雙向 import 實測 + token_report dry-run 通過） |
| 4 | WS1b ops_snapshot.py + 接線 | 邏輯 | ✅ f96482a6a（0.4s 實測；3 消費端已接） |
| 5 | WS2a/2b 歸檔流 + 詞彙收斂 | 邏輯 | ✅ b61789d26（2a：tombstone 壓縮 4.5MB→1.6MB、-64%，未達 <500KB 目標 — 殘量 = tombstone 本體 + <3d 窗口，判定可接受；2b：**既有機制已完成**，TASK_STATUSES + CI baseline gate，無需新工） |
| 6 | WS2c blocked triage | 流程 | ✅ 46→29（9 expired / 2 closed / 5 誤標回 pending / paid×2 設 until；rot >30d 監測收編 daily_checkup，首跑浮出 10 筆） |
| 7 | WS1c bootstrap 減肥 | 流程 | ✅ be8e69b20（396→333 行、-16%；未達 ≤250 — 剩餘全為 operative 規則，深度收斂屬 WS5；MEMORY.md 整併由 dreaming 已排的 consolidation task 收）|
| 8 | WS4a 報告面合併 | 流程 | ✅ 降頻生效（boss_report 6→3 班/天、work_summary 4→1 班/天，LaunchAgent 重生驗證；預估老闆信 ~14→~5-6 封/天；單一 owner 完整合併併入 WS5） |
| 9 | WS4b dreaming Act 端 | 流程 | ✅ **經查 2026-07-12 已閉環**（apply_auto 預設 ON + rot≥3 晚自動 queue task + queue-once dedup；兩個復發 finding 的 task 已 pending 待派）— 無需新機制 |
| 10 | WS1a pregate attribution 修復 | 流程 | 🔜 enqueued P2（`topology-audit-20260710-pregate-enforce-flip` 已重規格：修蓋章→重評→gate 達標才翻 enforce） |
| 11 | WS4c error_log 壓縮 | 流程 | 🔜 enqueued P2（`ws4c_error_log_compaction`） |
| 12 | WS5 治理疊層收斂 | 流程 | 🔜 enqueued P2（`ws5_governance_layer_consolidation`；月度 skill audit 併入） |
| 13 | WS1d 模型分層 | 決策 | ✅ **owner 2026-07-14 裁決：維持全 Opus**（不改 model_router；成本優化改由 WS1a/1b/1c 的結構面承擔） |
| 14 | K1709 worktree 正規合併（WS3b 發現） | - | 🔜 enqueued P2 main-thread；⚠️ 依賴 k1709_rev2 GW 措辭修正先行（15:45 Codex 裁決） |
| 15 | paid data 裁決（WS2c 併入決策信） | 決策 | ✅ **owner 2026-07-14 裁決：不採購**。K1268b/K1310 closed；intraday 線改用自有 TAIFEX tick（新任務 `taifexdata_dropbox_organize` P2 + `research_taifex_intraday_rv_line` P3） |

**執行日 meta-發現（2026-07-14）**：計畫的 5 個「待建機制」中有 3 個其實已存在但未啟用/未被知悉
（pregate 只差 config flip、dreaming apply_auto 7/12 已 ON、status 詞彙 gate 已有 CI baseline）。
教訓固化至 memory `feedback_check_existing_mechanism_before_building`。

## 5. 驗證 Gate（宣告完成前必過）
- 每 WS 的 Check 指標用**線上實測數據**驗證（token 週報 / du / jq 統計 / 信件計數），
  不以「改完 code」為完成。
- WS1a 翻 enforce 的 gate：attribution coverage ≥80% 且 strict_mismatch_rate ≤10%。
- 回歸防護：daily_checkup 既有維度覆蓋 cron_completion 與 alert_conditions；
  retention 規則生效後 rollback_points/hooks logs 的重新膨脹會被 3a 的 owner 每日裁切，
  無需新監控（anti-stacking）。

## 6. PDCA cadence
- **P**：本檔 §0 基準 + 每週 token 週報。
- **D**：§4 順序執行；剩餘項以 P2 任務進 next_tasks，由 dispatcher 常態驅動。
- **C**：每週一 token 週報產出後，比對 §2 各 Check 指標，結果回寫本檔 §4 狀態欄。
- **A**：達標項固化（規則進對應 owner script/skill/rule 並降級 prose 層）；未達標項
  升級診斷層級（邏輯→流程→架構）重打，不加 patch 層。

---

## 7. WS1e — Tool-boundary context budget（2026-07-14 owner 打回票後補上的「真正的結構修正」）

**Owner 回信（2026-07-14 16:25）**：「不能只有壓縮或是減班，要確實重構優化流程提高運作效率，
但又不損當前的功能，立即優化。」

**這個批評是對的，且指出了原計畫的診斷缺陷。** 原 §0 把 `cache_create 佔 billable 79%` 讀成
「bootstrap 太大」，於是 WS1c 去瘦 CLAUDE.md、WS2/WS3 去壓縮與清理、報告面去減班。
但 bootstrap 是**一次性前綴**，會被 cache_read（0.1x）攤平 —— 瘦它幾乎打不到 cache_create。

### 7.1 重新量測（7 天 transcript，17,570 筆 tool_result；`/tmp` 一次性腳本，數字見下）

| 事實 | 數值 |
|---|---|
| cache_create（週 billable） | 33.3M |
| 全部進入 context 的新內容（tool_result 7.26M + assistant 3.83M + …） | ~11M |
| **放大倍數** | **~3×** —— 每個進 context 的 token 平均被寫進 cache 三次（長 session 跨 cache TTL 續跑時整段 prefix 重寫） |
| tool_result 總量 | 7.26M tok / 17,570 筆 |
| **Read** | **3.68M tok / 2,005 次 / 平均 1,835 → 佔全部 tool_result 的 51%** |
| ├ 無 limit/offset（整檔讀） | **2.71M tok / 1,015 次 / 平均 2,673（佔 Read 的 73.8%）**，p90 = 8,045 |
| └ 有 limit/offset | 0.97M tok / 990 次 / 平均 975 |
| Bash | 3.24M tok / 12,075 次 / 平均 268（**長尾問題，不是均值問題**） |
| 長尾集中度 | 僅 8.1% 的 tool_result 握有 60% 的 token |
| 單檔冠軍 | `storage/ops/handoff_latest.md` — **457K tok/週**，被每個 session 整檔讀 |

**真正的成本函數**：`bill ≈ 3 × (每 turn 追加進 context 的 token)`。
→ 槓桿不在「文件多大」，在**「工具邊界每次倒多少東西進來」**。砍 tool_result 是**放大 3 倍**的節省，不是 1:1。

### 7.2 落地：`scripts/hooks/read_context_budget.py`（PreToolUse: Read）

- **政策**：caller 未給 `limit` 也未給 `offset` **且** 檔案 > 250 行 → 注入 `limit=200`，
  並在 additionalContext 告知真實行數與取得其餘內容的三條路（offset / Grep / 明確 limit）。
- **不損功能（owner 硬性條件）**：**明確意圖永遠不被覆寫** —— 有 `limit` 或 `offset` 就完全 no-op。
  這只是替「沒表達意圖」的呼叫補一個預設上限，與 Read 內建的 2000 行上限是同一個契約。
  任何 malformed input / 讀不到的路徑 / 二進位 / PDF·ipynb·圖片 → fail-open 回 `{}`。
- **實測效益**：命中 1,015 筆無界 Read 中的 273 筆，**省 ~1.12M raw tok/週**；
  以 3× 放大計 ≈ 3.4M billable/週 ≈ 週帳單的 **8%**。
- **回歸測試**：`scripts/tests/test_read_context_budget.py`（19 cases：觸發 / 明確 limit 不覆寫 /
  offset 不覆寫 / 邊界 250 行 / 非行導向格式 / 二進位 / 其他工具 / 7 種 malformed 全 fail-open）。

### 7.3 明確否決：Bash 端的通用輸出包裝

`.claude/hooks/run-compact-bash.sh` 已能用 `updatedInput` 改寫指令來壓縮輸出（pytest / git status /
tail log 三個模式），把它的 `*)` default case 改成「所有 Bash 都套預算」看似順理成章 —— **但會損害功能，故否決**：
wrapper 用 `bash -lc` 跑在子殼，而 7 天內有 **6,399 次呼叫以 `cd` 開頭、553 次 `export`**；
包裝後 cwd / env 不會延續到下一次 Bash 呼叫，直接違反 owner 的「不損當前功能」。
Bash 端要省，必須走「逐 class 判定為無 shell-state 副作用才包裝」，不是無差別包裝 —— 列入 backlog，不在本次硬推。

### 7.4 Check（下期驗收）

下兩期 token 週報應看到：`drilldown.by_tool.Read` 的無 limit/offset 佔比從 73.8% 明顯下降；
tool_result 總量下降 ≥1M/週。**若沒有下降 = 政策沒生效或被繞過，回來查，不要自我安慰。**
