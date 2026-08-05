# per-agent / per-model token 消耗分解報告 v1

- **產出部門**：資源監控部（`resource_monitor`）
- **產出時間**：2026-08-05 14:52（台灣時間）
- **對應工作項**：`item_20260805T055820533785Z_per-agent-per-model-token-v1-to`
- **觀測窗**：2026-07-29 ～ 2026-08-04（UTC 完整 7 日；不含仍在進行中的 08-05）
- **重算工具**：`storage/org/departments/resource_monitor/tools/token_breakdown.py`
- **原始輸出**：`storage/org/departments/resource_monitor/memory/token_breakdown_2026-08-04_7d.json`

---

## 0. 一句話結論

平台 7 日 billable 共 **184.4M tokens**，其中 **76.4% 來自 Codex、且 81.6% 的 Codex 用量是
桌面互動 session（不是自動化 backbone）**；同時發現 **兩個會計層級的結構性缺陷**——每日
token 日報連續 6 天寫成 0，以及 Codex fork 造成單一對話被重複計為 76 個 session。
在修掉這兩個缺陷之前，平台對外引用的 token 數字都不可當定論。

---

## 1. 資料源盤點

| # | 資料源 | 內容 | 可用性 | 缺口 |
|---|--------|------|--------|------|
| 1 | `~/.claude/projects/**/*.jsonl` | Claude Code 每則 assistant message 的 `message.usage` | ✅ 權威 | 無 agent 欄位，需由 project 目錄推導 |
| 2 | `~/.claude/projects/**/subagents/*.jsonl` | Task-tool subagent 用量 | ✅ | 同上 |
| 3 | `~/.codex/sessions/**/rollout-*.jsonl` | Codex 累計 `token_count` → 逐步 delta | ⚠️ 有重複計算缺陷（見 §4 F2） | session 身分綁檔名而非邏輯對話 |
| 4 | `storage/reports/token_usage/daily_*.json` | 官方日報（by_model / by_provider / by_category） | ❌ 7 天中 6 天是 0（見 §4 F1） | **無 agent 維度** |
| 5 | `storage/reports/token_usage/weekly_*.json` | 官方週報（老闆 email 的數字來源） | ✅ 有數字 | 同樣無 agent 維度 |
| 6 | `storage/ops/dispatch_workspace_receipts.jsonl`、`storage/ops/agent_jobs/`、`storage/ops/executions/` | 派工／workspace／執行 receipt | ✅ | **不含 token 欄位**；無法直接做成本歸屬，只能用時間窗與 workspace 名間接對照 |

**關鍵發現（盤點層面）**：既有的 token 產出**完全沒有 agent 維度**，只有 model /
provider / category 三軸。「哪個 agent 花的」在 dispatch receipts 那邊也拿不到（receipt 不
帶 token）。本報告用的歸屬訊號是 **Claude Code 的 project 目錄**——CWD 唯一決定目錄名，
所以主 checkout ＝ 主線程、`.claude/worktrees/<slug>` ＝ 該 worktree 的實驗 agent、
dispatch scratch ＝ Operations Core worker。這是唯一不需要猜的 agent 訊號。

---

## 2. 總量（2026-07-29 ～ 08-04，UTC 7 日）

| 指標 | 值 |
|------|-----|
| billable（input + output + cache_create） | **184,380,508** |
| cache_read | 5,745,146,273 |
| output tokens | 17,230,045 |
| turns / sessions | 38,563 / 526 |
| 估算成本 | **$1,242.43，但只覆蓋 20.2% 的 billable**（見 §4 F3） |
| 產出類（mission）佔比 | 4.5%（口徑有偏，見 §5） |

## 3. 分解

### 3.1 by provider / model

| model | billable | 佔比 | 有價目表 |
|-------|----------|------|----------|
| gpt-5.6-sol | 136,038,916 | 73.8% | ❌ |
| claude-opus-5 | 36,090,122 | 19.6% | ✅ |
| claude-fable-5 | 6,251,884 | 3.4% | ❌ |
| codex-auto-review | 3,653,425 | 2.0% | ❌ |
| claude-sonnet-5 | 1,161,969 | 0.6% | ✅ |
| gpt-5.4-mini | 774,200 | 0.4% | ❌ |
| gpt-5.6-terra | 357,635 | 0.2% | ❌ |
| claude-haiku-4-5 | 52,357 | 0.0% | ✅ |

Provider：codex 140,824,176（76.4%）／claude 43,556,332（23.6%）。

### 3.2 by agent class（本報告新增的維度）

| agent class | billable | 佔比 | sessions | mission 佔比 |
|-------------|----------|------|----------|--------------|
| codex_worker | 140,824,176 | 76.4% | 280 | 4.1% |
| main_thread | 22,859,887 | 12.4% | 9 | 0.5% |
| dispatch_worker | 9,349,116 | 5.1% | 92 | 3.0% |
| worktree_agent | 6,478,246 | 3.5% | 110 | **32.7%** |
| dispatch_worker_subagent | 3,594,217 | 1.9% | 27 | 0.3% |
| main_thread_subagent | 1,014,978 | 0.6% | 6 | 0.0% |
| worktree_agent_subagent | 259,888 | 0.1% | 2 | 0.0% |

**worktree agent 是投入產出比最高的一類**：只花 3.5% 的 token，卻有 32.7% 落在
產出類（experiment / paper / article / knowledge）。實驗 agent 的錢花得最準。

### 3.3 Codex 用量的真實來源（`session_meta.originator`，全窗無截斷）

| originator | billable | 佔 Codex | sessions |
|------------|----------|----------|----------|
| codex_work_desktop | 110,477,880 | 78.5% | 76 |
| codex_exec（codex_loop / 派工 backbone） | 26,027,445 | 18.5% | 199 |
| Codex Desktop | 4,318,851 | 3.1% | 5 |

**桌面互動合計 114.8M ＝ Codex 的 81.6%、整個平台 7 日用量的 62.3%。**
自動化 backbone（`codex_exec`）只佔平台 14.1%。平台的 token 帳單主體是互動式桌面
使用，不是 24/7 自動運營。

### 3.4 agent class × model（前 5）

| 組合 | 佔比 |
|------|------|
| codex_worker × gpt-5.6-sol | 73.8% |
| main_thread × claude-opus-5 | 8.9% |
| dispatch_worker × claude-opus-5 | 5.1% |
| worktree_agent × claude-opus-5 | 3.5% |
| main_thread × claude-fable-5 | 3.4% |

---

## 4. 異常與結構性缺陷

### F1 — 每日 token 日報連續 6 天寫成 0（P1，資料源等於沒有）

| 日期 | 落檔日報 billable | 重算真值 | 少記 |
|------|------------------|----------|------|
| 2026-07-29 | 0 | 51,024,977 | 51.0M |
| 2026-07-30 | 0 | 30,600,777 | 30.6M |
| 2026-07-31 | 0 | 543,826 | 0.5M |
| 2026-08-01 | 43,240,765 | 43,240,765 | 0（08-02 15:40 補跑的） |
| 2026-08-02 | 0 | 25,093,007 | 25.1M |
| 2026-08-03 | 0 | 9,698,197 | 9.7M |
| 2026-08-04 | 0 | 24,178,959 | 24.2M |

**7 天中 6 天完全空白，累計少記 141.1M ＝ 該窗 76.5%。**

- **根因（流程契約層）**：`token_report_daily` cron 在 **08:00 台灣＝00:00 UTC** 觸發，
  且傳的是 **當天** 日期（cron log：`--date 2026-08-05` 於 `2026-08-05T00:00:50Z` 執行），
  而 `token_usage_report.py` 的日界是 **UTC**（`generate_daily_report` 用
  `[target_date, target_date+1)` 過濾 `ts.date()`）。等於每天都在統計「剛開始 50 秒的
  那一天」→ 必然接近 0。所有非 0 的日報都是事後手動補跑（mtime 可證）。
- **影響**：老闆每日 token email 裡的「當日／使用類型／模型／reasoning 佔比／cache_read」
  全部是空的，只有週報有數字。本部門 KPI（每日消耗分解）目前無可用自動資料源。
- **修法（二選一，不可各改一半）**：(a) cron 改產「昨天（UTC）」的報表；
  (b) aggregation 改台灣日界、並移到台灣日結後跑。
- **歸屬**：`scripts/token_usage_report.py` ＋ `/Users/yhlai0911/.volpred/bin/cron_token_report.sh`
  都不在本部門 owned_paths，**未自行修改**，回報經理指派。

### F2 — Codex fork 造成同一對話被重複計為多個 session（P1，會計正確性）

- 邏輯對話 `019f8e4d-ca99-73e2-a3d0-a7aa7a8cac5f` 被寫成 **76 個 rollout 檔**，
  逐檔各算一次 session，加總 **110.5M**，而其最大單檔為 **63.1M**。
- 全窗 **280 個 rollout 檔只對應 131 個邏輯對話**（依 `session_meta.session_id`）。
- 以「每個邏輯對話取最大單檔」為下界估計：**重複量上界 60.1M
  ＝ Codex billable 的 42.7%、平台總量的 32.6%。**
- **根因**：`_iter_codex_session_records` 用 **rollout 檔名 uuid** 當 session_id，而
  去重鍵 `record_id` 內嵌該 session_id。fork 重放同一段歷史時檔名不同 → record_id 不同
  → 跨檔去重失效。
- **最小修法**：session_id 改用 `session_meta.session_id`（邏輯對話 id）。fork 重放的
  相同累計 tuple 會自然命中既有 `seen_record_ids` 去重。
- **誠實邊界**：fork 檔可能含真正的新 turn，所以真實重複量介於 0 與 60.1M 之間。
  證據（同一 `session_meta.session_id`、時間跨度與檔案大小近乎相同、前綴重放）指向
  大部分是重複，但**要 turn-level 比對才能定案**——本報告不宣稱已定案。

### F3 — 成本估算只覆蓋 20.2% 的 billable（P2）

`PRICING` 缺 `gpt-5.6-sol`、`gpt-5.4-mini`、`gpt-5.6-terra`、`codex-auto-review`、
`claude-fable-5`，這些一律計 $0。所以「$1,242」不是本週成本，只是 Claude 那 20% 的帳。

### F4 — 單日尖峰未觸發，但單一 agent 集中度是本窗真異常（P2）

- KPI 規則「單日 > 2× 均值」**本窗未觸發**：最高 2026-07-29 ＝ 51.0M ＝ 均值 26.3M 的 1.94×。
- 但單一 Codex 桌面對話吃掉 **34.2%** 的平台用量，且該 session 連續存活
  **238 小時（07-23 09:28Z → 08-02 07:45Z）、rollout 檔 628.6 MB**。日級規則看不到這種異常。
- **v2 建議新增規則**：單一 agent 佔窗口 > 20%；單一 session 壽命 > 48h。

---

## 5. 方法與限制（誠實邊界）

1. **口徑**：billable ＝ input + output + cache_create（與官方日報同定義，不含 cache_read）；
   turn 依 `message.id` 去重（與官方同口徑），未重寫 token 會計，直接重用
   `scripts/token_usage_report.py` 的讀取與計價原語。
2. **日界為 UTC**，與官方報表一致；未與台灣日界混用。
3. **agent 歸屬是結構性推導而非埋點**：來自 Claude project 目錄前綴。若 runtime 佈局改變，
   會落入 `unclassified` 而非靜默歸零（本窗無 unclassified）。
4. **mission 產出佔比會低估主線程**：分類器把主線程大量 turn 歸到 `bash_other`(15.6%) 與
   `investigation`(3.8%)，這些不在 `MISSION_OUTPUT_CATEGORIES`。**不要直接把 0.5% 當成
   「主線程沒在做產出」**——這是分類口徑問題，需先修分類才能用作 KPI。
5. **Codex 分類粗**：`codex_desktop` / `codex_exec` / `codex_review` 是由 cwd/originator 推的
   粗桶，不是真任務類型，所以 Codex 的 mission 佔比不具可比性。
6. §3.3 的 originator 統計是全窗無截斷；§4 F2 的重複量是**上界**，非定值。

---

## 6. 建議行動（皆需經理指派，均在本部門 owned_paths 之外）

| # | 事項 | 優先 | 建議 owner |
|---|------|------|-----------|
| R1 | 修 `token_report_daily` 日界／目標日期不匹配（F1） | P1 | Operations Core / platform_eng |
| R2 | Codex session 身分改綁 `session_meta.session_id`（F2） | P1 | Codex 熱區（`scripts/token_usage_report.py`） |
| R3 | 補齊 `PRICING` 缺漏模型（F3） | P2 | platform_eng |
| R4 | 長壽 Codex Desktop session 輪替政策（238h／628MB 單一 session） | P2 | governance |
| R5 | v2：新增集中度／壽命異常規則 ＋ noop／空轉偵測（本部門 KPI 尚未覆蓋） | P2 | resource_monitor（自辦） |

R1／R2 未修完之前，平台對外引用的 token 數字（含老闆每日 email）都應標註為
**未定案**。
