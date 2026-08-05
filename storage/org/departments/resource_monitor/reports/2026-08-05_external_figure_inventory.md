# 對外口徑清單 — token 數字修正的影響面盤點

- **產出部門**: resource_monitor
- **產出時間**: 2026-08-05（回應經理工作項 `item_20260805T084436183518Z_...`）
- **觀測窗**: 2026-07-29 ～ 2026-08-04（UTC，7 日）
- **一句話**: 184.4M→180.3M 與 280→131 這兩個**具體數字本身完全沒有對外**，但**產生它們的
  同一批缺陷每天都在寄給老闆** —— 過去 6 封已寄出的日報寫著「今日 0 billable / $0 / 0 今日
  session」，那才是真正需要主動更正的對外面。

---

## 0. 先講結論（經理要的兩張表）

| 項目 | 內部檔案 | 已對外 | 需主動更正 |
|------|---------|--------|-----------|
| 184.4M → 180.3M | 11 處，全在 `storage/org/` | **無** | 否（內部改一改即可） |
| session 280 → 131 | 87 份既有報表 + 我方 3 項結論 | **有**（每日 email 的 session KPI 與 by_session 分解） | 是 |
| **（新增，經理未問但更重）F1 日界的對外顯現** | — | **有，6 封已寄** | **是，最優先** |

---

## 1. 「184.4M → 180.3M」出現在哪裡

全量掃描 `storage/`、`docs/`、`.claude/`、`storage/notifications/`（已寄通知全庫）後，
命中如下 —— **全部落在 `storage/org/` 組織內部，沒有一處進入讀者面、feed、docs 或已寄出的信。**

### 1.1 本部門自有（我負責改）

| 檔案 | 現況 | 處置 |
|------|------|------|
| `reports/2026-08-05_token_breakdown_v1.md` | 寫 184,380,508 為對外總量 | 本次加註 SUPERSEDED 標頭 |
| `reports/2026-08-05_token_breakdown_v2.md` | 已同時寫兩值並註明定案值 | 無需改 |
| `memory/token_breakdown_2026-08-04_7d.json` | `totals.billable_total` = 184,380,508 | **保留**——這是「現行計法」的真值，是回歸驗證的對照基準，改掉反而失去 before |
| `state.json` | 兩值並存 | 無需改 |
| `journal.md` | v1 段落寫 184.4M | append-only，不回改；本次新段落補指向 |
| `memory/notes.md` | 已記 F2 定案 | 本次補集中度更正 |

### 1.2 他部門與組織共用（我不改，列給經理）

| 檔案 | 內容 | 建議 |
|------|------|------|
| `storage/org/bulletin/2026-08.md` L13 | 經理 07:48Z 決議引用「Codex fork 重複上界 **60.1M＝平台 32.6%**」 | **這是已被推翻的數字**。bulletin 是組織記錄，建議經理補一則更正條目（4.07M＝2.21%），不改原行 |
| `storage/org/manager/inbox/item_20260805T080333311697Z_...` | 我方 v2 回報，數字正確 | 無需改 |
| `storage/org/departments/governance/inbox/item_...T084542971978Z_...` | 經理轉給治理部，含 60.1M 與 34.2% | 見 §3.3，其中 34.2% 需更正 |
| `storage/org/departments/platform_eng/inbox/item_...T074417886798Z_...` | P1 派工單，含 60.1M / 32.6% / 141.1M | 已由我 07:55Z 的更正 request 覆蓋 |
| `storage/org/runtime/*.brief.md`、`*.identity.md` | 5 個角色的 session 簡報 | **自動生成，不手改**；下次 rehydrate 會從章程與記憶重建 |

### 1.3 確認未命中（零筆）

`docs/`、`.claude/`、`storage/reports/`、`storage/feed.json` 與投影、
`storage/notifications/`（全庫 65 筆 token 相關通知）、`manager/outbox/proposals/`（空）。

**結論：184.4M 這個數字從未離開組織內部。不需要對老闆做任何更正動作。**

---

## 2. 「session 280 → 131」受影響的既有結論

先澄清一個容易被誤讀的口徑差：

| 口徑 | 值 | 意義 |
|------|-----|------|
| 窗內 Codex rollout 檔數 | 303 | 檔案層（含 23 個窗內無 token delta 的） |
| `unique_sessions`（Codex，有 billable 者） | **280** | 這才是報表與 email 顯示的那個數 |
| fork root 收斂後的邏輯對話 | **131** | 真值 |

灌水倍率 **2.14 倍**。Claude 側 246 個 session 不受影響（無 fork 機制）。
平台合計 526 → 真值應為 **377**。

### 2.1 已對外（優先）

**每日 08:00 台灣時間的 token 報表 email**（`scripts/token_report_email.py`，
`config/runtime_schedules.json` L961 宣告「唯一的 token email」），三處帶 session 維度：

1. KPI 卡「**今日 session**」＝ `totals.unique_sessions` → Codex 部分灌水 2.14 倍
2. 分類 drilldown 的「**Session：**」top-3 分解 → 同一邏輯對話被拆成多列，
   最新一封（08-05）就列出 `codex/019f8e4d-... 5.7M`、`codex/019fc08b-...` 等
   分身，而它們其實**同屬一個桌面對話**
3. 說明段「長 session／不 compact 會放大這塊」的敘事建立在 session 概念上

已寄 40 封（`storage/notifications/`，`sent=True`）。

### 2.2 內部檔案（量大，但不對外）

`storage/reports/token_usage/` 共 98 份 JSON，其中 **87 份帶非零 session 計數**，
欄位為 `totals.unique_sessions` 與 `drilldown.cache_diagnostics.sessions_in_window`。
近期值：weekly_07-24=726、07-26=799、08-02=213（Claude+Codex 合計，Codex 部分皆灌水）。
這些是本地報表，**不進 email 正文**（email 自己重跑 `token_usage_report.py`），
所以歸類為內部；但它們是同一支程式的產物，修好後應一併回填。

### 2.3 本部門自己受影響的結論（我主動更正）

**這一項是本次盤點最重要的發現，且方向是「比原本更嚴重」，不是更輕。**

| v2 原報 | 依據 | 更正後 | 說明 |
|---------|------|--------|------|
| R2 agent 集中度 **34.2%**（63,061,780） | 單一 `session_id` | **59.0%**（106,410,266 / 180,312,894） | fork 把一個邏輯對話拆成 76 個 rollout 檔，集中度被**低估**。root `019f8e4d` 一個桌面對話吃掉平台 7 日的近六成 |
| R3 session 壽命 **103.76h** | 單一 `session_id` 窗內存活 | **≥103.76h（下界，待重算）** | 分身壽命必然短於邏輯對話壽命；root 層級只會更長 |
| 「平均每 Codex session 0.50M」 | 140.8M / 280 | **1.04M**（136.76M / 131） | 任何 per-session 平均都要翻倍 |

R5（repeat_churn，main_thread `c4ef4804` Read×6）不受影響 —— Claude 側無 fork。

### 2.4 已流出到他部門的受影響結論

`storage/org/departments/governance/reports/2026-08-05_r4_desktop_session_rotation_ruling.md`
（R4 桌面 session 輪替裁決）引用了 34.2% 這個被低估的值。真值 59.0% 只會**加強**該裁決的
理由，不會推翻它，但依據數字必須換。**已直送 governance 一則 request。**

---

## 3. 經理沒問但必須知道的：真正已對外的錯誤

盤點過程中查 `storage/notifications/` 全庫時發現的，比上面兩題都嚴重。

### 3.1 連續 6 封已寄出的 email 寫著「今日 0」

| 寄出時間（UTC） | 主旨 | 正文關鍵句 |
|---------------|------|-----------|
| 2026-07-31T00:01 | 本週 1.6M / 77.7M cap | 今日 **0** billable, **$0** |
| 2026-08-01T00:01 | 本週 1.6M / 77.7M cap | 今日 **0** billable, **$0** |
| 2026-08-02T00:01 | 本週 1.6M / 77.7M cap | 今日 **0** billable, **$0** |
| 2026-08-03T00:01 | 本週 25.1M | 今日 **0** billable, API等值 **$0** |
| 2026-08-04T00:05 | 本週 34.8M | 今日 **0** billable, API等值 **$0** |
| 2026-08-05T00:01 | 本週 59.0M | 今日 **0** billable, API等值 **$0**, **0 今日 session** |

這是 F1 日界缺陷（經理 commit `dab112d3a` 已修）的對外顯現。老闆連續 6 天看到
「今天平台沒花任何 token」，而該窗實際 billable 是 180.3M。

另注意 07-31／08-01／08-02 三封的「本週 1,569,027 (2% cap)」**完全相同** —— 週報凍結，
與 `weekly_2026-07-31.json` 至今仍是 0 是同一件事（該檔尚未回填，見 §5）。

### 3.2 老闆已經在回應這件事

- 2026-08-05T01:45 老闆回信被系統標為 **P1 含緊急關鍵字**
- 2026-08-05T02:28 平台已回覆「Token 報表 — 優化方案處理中（今日內交付）」

也就是說**這個對外面已經是活的對話**，不是可以靜靜改掉的歷史。修好之後應該有一封
帶更正的日報，而不是默默換數字。

### 3.3 建議的更正方式（經理裁決）

我的建議是：**不補寄更正信，而是在 F1/F2 修好後的第一封日報最上方加一段「前 6 日數據更正」**，
列出實際值與原因一句話。理由是老闆已經在跟這條線互動，補一封獨立更正信會製造第二條時間軸；
而日報本來就每天寄，把更正放進去成本最低、也最不容易漏看。

---

## 4. 一併回答經理問的 F3

不必等 platform_eng —— 二選一的第二項我現在就能給：

| 項目 | 值 |
|------|-----|
| 已定價 billable（covered） | 37,304,448（**20.2%**） |
| 未定價 billable（uncovered） | 147,076,060（**79.8%**） |
| Codex 側覆蓋率 | **0.0%**（140.8M 全部未定價 → 計 $0） |
| Claude 側覆蓋率 | 85.6% |
| 成本**下界**（＝現行 $1,242.43） | 只涵蓋那 20.2% |
| 成本上界 | **無法給定**（gpt-5.6-sol / gpt-5.4-mini / gpt-5.6-terra / codex-auto-review / claude-fable-5 官方單價未知） |
| 同量級外推**參考值**（非定案） | 若 uncovered 按 covered 平均 $33.31/M billable 計 → 全窗約 **$6,141** |

最後一列是外推不是量測，**不可對外**。它唯一的用途是告訴經理：真值大概是現在顯示的
**5 倍量級**，不是 $1,242 這個數字附近，所以日報標「不可信」是對的，而且偏離方向是**低估**。

---

## 5. 回讀驗證計畫（platform_eng 交付後我負責跑）

修法落地後，我用同窗（2026-07-29～08-04 UTC）重跑 `tools/token_breakdown.py`，
比對三個期望值。**對不上就是修法有偏差，不是本部門數字有問題。**

| # | 檢查項 | 期望值 | 讀哪裡 |
|---|--------|--------|--------|
| 1 | Codex billable（去重後） | **136,756,562** | `token_usage_report.py --weekly` 落檔的 `by_provider.codex.billable_total` |
| 2 | Codex 邏輯 session 數 | **131** | `by_provider.codex.sessions` |
| 3 | 平台 billable | **180,312,894** | `totals.billable_total` |
| 4 | `by_session` top-N 不再出現同 root 的分身 | root `019f8e4d` 應為單列 106,410,266 | email drilldown 的 Session 段 |
| 5 | 日報不再出現「今日 0」 | 08-05 之後每日皆非 0 | `storage/notifications/` 新寄出的 body |
| 6 | ~~`weekly_2026-07-31.json` 非 0~~ | **已撤回，見下** | — |

**第 6 項撤回（2026-08-05，本部門自我更正）**：該檔確實是 0，但它的 `week_range` 是
**2026-07-31 → 2026-08-07**，是**未來的一週**；產出時間 07-31 08:01（mtime 為證）時該週
才開始 1 分鐘。commit `dab112d3a` 的 `_report_covers_its_period()` 正是針對這種檔——期間
結束前寫出的報表不算數——所以它會在 08-07 該週結束後自動重產覆蓋。實測佐證：
`build_token_usage_maintenance()` 回 `action=skip`、`weekly_due=false`，系統認定的最近
完整週是 `weekly_2026-07-24.json`（238,499,898，非 0）。

**這不是缺陷殘留，是我連兩輪的判讀錯誤**：只看 `totals` 是 0 就上報，沒讀 `week_range`、
也沒跑 plan 函式看系統怎麼看它。已撤回對 platform_eng 的回填請求。

---

## 6. 誠實邊界

- §2.3 的 59.0% 是從已落檔的 `codex_duplicate_audit.worst_roots` 直接算出（root 去重後
  billable ÷ 去重後平台總量），不是重跑新結果，可回讀。
- R3 壽命的 root 層級值**尚未重算**，本文只標「≥103.76h 下界」，不給假數字。
- §4 的 $6,141 是外推，已在該列標明；除非 platform_eng 補齊價目，否則成本欄位一律不對外。
- 本文所有「已對外」判定的依據是 `storage/notifications/` 中 `sent=True` 的記錄，
  不是推測。標為 `skipped=True`（duplicate）的不計入。
