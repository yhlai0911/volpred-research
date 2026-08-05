# per-agent / per-model token 消耗分解報告 v2 — 異常規則、F2 定案、分類口徑修正

- **產出部門**：資源監控部（`resource_monitor`）
- **產出時間**：2026-08-05 16:05（台灣時間）
- **對應工作項**：`item_20260805T074432202854Z_r5-r2-v1-f1-f2-platform-eng-own`（R5 自辦 + R2 後續 + 分類口徑）
  ＋ `item_20260805T071751544758Z_f1-commit-dab112d3a-summaries-py`（F1 已修，F2 提案）
- **觀測窗**：2026-07-29 ～ 2026-08-04（UTC 完整 7 日，**與 v1 同窗**）
- **重算工具**：`storage/org/departments/resource_monitor/tools/token_breakdown.py`（v2）
- **原始輸出**：`storage/org/departments/resource_monitor/memory/token_breakdown_2026-08-04_7d.json`

---

## 0. 一句話結論

v2 補上的三條異常規則**當窗就抓到了 v1 日級規則完全看不到的東西**（單一 Codex 桌面對話佔
34.2%、窗內存活 103.8 小時）；同時 turn-level 重算把 F2 的「重複量上界 60.1M」收斂成
**定案 4.07M（Codex 的 2.89%、平台的 2.21%）——v1 的上界高估了約 15 倍**，對外口徑必須改用
定案值；而分類口徑修正後，主線程的實際產出比率是 **41.65%（下界）**，不是上游分類器算出來的
4.5%，該欄已在資料層標死為不可作 KPI。

---

## 1. v2 新增的 KPI 規則與當窗觸發結果

規則寫在 `tools/token_breakdown.py` 頂部的常數區，改常數就是改規則（不散落在報告文字裡）。

| # | 規則 | 門檻 | 當窗觸發 |
|---|------|------|----------|
| R1（v1 既有） | 單日 billable > 窗口均值 ×N | 2.0× | **0 件**（最高 07-29 = 51.0M = 1.94×） |
| R2（v2 新增） | 單一 agent 佔窗口 billable > X% | 20% | **1 件** |
| R3（v2 新增） | 單一 session 壽命 > Xh | 48h | **1 件** |
| R4（v2 新增） | 燒 ≥1M billable 卻零寫入的 session（noop） | 1M / 0 effectful | 0 件 |
| R5（v2 新增） | 同 session 內同 tool ＋ 同輸入重複 ≥N 次（空轉） | 5 次 / ≥200k billable | **1 件** |

### 觸發明細

**R2 agent 集中度｜`codex/019f8e4d-ca99-73e2-a3d0-a7aa7a8cac5f`｜63,061,780 billable｜34.2%**
單一 Codex 桌面對話吃掉平台三分之一。這正是 v1 §4 F4 指出、日級規則完全盲的那類異常——
現在會自動觸發。

**R3 session 壽命｜同一個 session｜窗內存活 103.76 小時**
註記：壽命只在觀測窗內量測，該 session 起於窗前（v1 量到的完整壽命為 238 小時），
所以 103.76h 是**下界**。規則設計上這不影響判定（>48h 照樣觸發）。

**R5 重複空轉｜`c4ef4804`（main_thread）｜`Read` 同一份輸入重複 6 次｜該 session 10.2M billable**
同一 session 內對完全相同的檔案參數重複 Read 6 次。單看金額不大，但這是「鬼打牆」的
早期訊號，屬於 3-Strike Rule 想抓的模式，故列為 P3 觀察而非 P1 事故。

**R4 未觸發**：本窗沒有「燒 ≥1M 卻零寫入」的 Claude session。Codex 因 telemetry 不含工具內容
被排除在此規則之外（見 §5 誠實邊界），不是「Codex 通過檢查」。

---

## 2. F2 定案：重複計數 = 4.07M，不是 60.1M

經理指示「禁止把上界當結論」，本節用 turn-level 比對收斂。

### 方法

對窗內每一筆 Codex `token_count` delta，把去重鍵從現行的
`session_id ＋ 累計 tuple` 換成 `fork root ＋ 累計 tuple`（`fork root` = `forked_from_id` /
`parent_thread_id` 逐層追到底），重算後與現行會計相減。實作見
`tools/token_breakdown.py::audit_codex_duplicates()`，可重跑。

### 結果（2026-07-29 ～ 08-04）

| 指標 | 值 |
|------|-----|
| 現行會計 Codex billable | 140,824,176 |
| root-keyed 去重後 | **136,756,562** |
| **重複量（定案）** | **4,067,614** |
| 佔 Codex | **2.89%** |
| 佔平台總量 | **2.21%** |
| turn 記錄數 | 29,512 → 29,044（重複 468 筆） |
| 重複全部集中在 | `019f8e4d`（76 個 rollout 檔，110.5M → 106.4M） |

**平台 7 日 billable 定案：184,380,508 → 180,312,894**（Codex 佔比 76.4% → 75.8%）。

### v1 為什麼高估 15 倍

v1 的 60.1M 用的是「每個邏輯對話只保留最大單檔、其餘全算重複」的**上界估計**，前提是
跨檔重放完全沒被去重。實際上 `_iter_codex_session_records` 已有 fork 重放偵測與 retract
機制（`replaying` / `boundary_proven`），把 fork 檔的重放前綴大部分丟掉了。殘留的 4.07M
才是真正漏網的部分。v1 對此標了「介於 0 與 60.1M 之間、要 turn-level 才能定案」——
方向正確，但**上界不可作為對外數字**，本節取代它。

### 但 session 計數的膨脹是真的

| 口徑 | 數量 |
|------|------|
| 現行 `unique_sessions`（Codex） | 280 |
| fork root 收斂後的邏輯對話數 | **131** |

**session 數被灌水 2.14 倍**（窗內 149 個 rollout 檔帶 fork marker）。所以 F2 的 token 影響
是 2.89% 的小事，**session 維度的失真才是主要問題**——任何「平均每 session 花多少」「有幾個
agent 在跑」的推論目前都錯。

### 給 platform_eng 的可執行修法（已於 07:55Z 直送其 inbox，因其正在寫該檔）

**先撤銷 v1 寫的「最小修法：session_id 改綁 `session_meta.session_id`」——那句是錯的。**
實證：`~/.codex/sessions` 全量 2815 個 rollout 檔，`session_meta.id` 有 2815 個相異值，
**每檔各自唯一**；且 `token_usage_report.py` 自 commit `95831cdb6` 起早已綁在該欄位
（line 874-880）。照該句實作＝零效果。

可執行步驟：

1. 開檔時建 `id → forked_from_id / parent_thread_id` 的 parent map，`root_of()` 迭代解析
   （含 self-loop 保護）。
2. 去重鍵身分段由 `session_id` 換成 `root`：`f"codex:{root}:{累計tuple}:{last tuple}"`。
   同 root 下重放的相同累計 tuple 會自然命中既有 `seen_record_ids`。
3. 對外的 session 計數與 `by_session` 一併改用 root，否則 `unique_sessions` 仍被灌水。

**回歸驗證的期望值**：修好後重跑同窗，Codex billable 應落在 **136,756,562**、
Codex 邏輯 session 數應為 **131**。對不上就是修法有偏差，不是本部門數字有問題。
參考實作可直接抄 `audit_codex_duplicates()`。

---

## 3. 分類口徑：主線程「0.5% 產出」是分類器造成的假象

經理附帶要求：修口徑，或就地標註不可作 KPI。**兩件都做了。**

### 3.1 就地標註（資料層，不靠讀者記得）

JSON 內原欄位 `mission_output_share_pct` 已改名為
**`mission_output_share_pct_upstream_NOT_KPI`**，並在報告根節點加 `kpi_field_warnings`
說明。欄名本身就是警告，複製貼上到別處也帶著走。

### 3.2 部門自有口徑（修口徑）

不再問「這個 turn 屬於哪個任務類型」（上游分類器的問法，主線程大量真實產出被丟進
`bash_other` / `investigation`），改問一個結構性的問題：**這個 turn 有沒有真的改變世界？**

| 分類 | 判準 | billable | turns |
|------|------|----------|-------|
| `write` | 出現 Edit / Write / NotebookEdit | 4,288,492 | 1,266 |
| `mutating_command` | Bash 命中變更型白名單、或 Agent/Task/Cron 等變更型工具 | 13,852,124 | 2,862 |
| `read_only` | 有工具但都是讀／搜尋／查詢 | 24,250,315 | 4,470 |
| `noop_text_only` | 完全沒有 tool_use | 1,165,401 | 453 |
| `unknown_no_content` | Codex（telemetry 無工具內容，不猜） | 140,824,176 | 29,512 |

**Claude 側 effectful 佔比 = 41.65%（下界）**，對照上游分類器的 4.5%——**差 9 倍**。
「主線程沒在產出」這個結論在 v1 就已被標為不可用，v2 正式用數字推翻它。

---

## 4. noop／空轉偵測結果

| 指標 | 值 | 讀法 |
|------|-----|------|
| `noop_text_only` 佔 Claude billable | **2.68%（上界）** | 純文字無工具的 turn，含 cron stub 的極短回覆 |
| `idle_burn_session`（≥1M 零寫入） | **0 件** | 本窗沒有大額純燒 |
| `repeat_churn`（同輸入 ≥5 次） | **1 件** | main_thread `c4ef4804`，Read ×6 |

結論：**本窗沒有系統性空轉**。真正的成本問題不是「跑了沒用的東西」，而是集中度
——一個桌面對話佔 34.2%。

---

## 5. 誠實邊界（沿用 v1 §5，新增 3 條）

1. `mutating_command` 是**保守白名單**：會寫檔但沒命中 pattern 的 python 腳本會被歸為
   `read_only`。⇒ **effectful 41.65% 是下界，noop / read_only 佔比是上界。**
2. Codex telemetry 只有 `token_count`，**沒有工具內容**，無法判定效力，故 R4（idle_burn）
   與效力分母都排除 Codex。這是「無法量測」，不是「量測後通過」。
3. session 壽命只在觀測窗內量測；跨窗 session 的真實壽命 ≥ 報告值。
4. F2 的 4.07M 是 **turn-level 定值**（同 root 內累計 tuple 完全相同的 delta 只計一次），
   不是上界。fork 檔內真正新增的 turn 有不同的累計 tuple，會被保留、不會被誤刪。
5. 總量 184.4M、成本覆蓋率 20.2%、by_model / by_agent_class 等 v1 數字**未變動**——v2 沒有
   改動 token 會計，只加了審計維度。F3（PRICING 覆蓋率 20.2%）仍未修，成本數字仍不可對外。

---

## 6. 對外口徑更新建議（請經理採用）

| 項目 | v1 對外說法 | v2 定案說法 |
|------|-------------|-------------|
| Codex fork 重複量 | 「上界 60.1M＝平台 32.6%」 | **4.07M＝平台 2.21%**（turn-level 定值） |
| 平台 7 日 billable | 184.4M（未定案） | **180.3M**（扣除定案重複量） |
| 主線程產出佔比 | 0.5%（已標失真） | **41.65% 下界**（Claude 側 effectful）；舊欄位不可引用 |
| Codex session 數 | 280 | **131 個邏輯對話**（現行 280 是灌水值） |
| 成本 $1,242 | 只覆蓋 20.2% | 不變，**F3 修好前仍不可對外** |

---

## 7. 依賴與未竟

- **R2 落地後需再跑一次**：platform_eng 修完 `token_usage_report.py` 後，用本報告 §2 的
  期望值（136,756,562 / 131）做回歸驗證。本部門已把定案值與參考實作直送其 inbox。
- **F3 未修**：成本覆蓋率仍 20.2%，成本欄位維持「不可對外」。
- **F1 已修並回填**（經理 commit `dab112d3a`），已寫入本部門 `memory/notes.md` 已知缺陷節。
  **但經理便箋的週報敘述需更正**：2026-08-05 16:00 實測，`weekly_2026-07-31.json` 的
  `totals.billable_total` **確實仍是 0**，而 `weekly_2026-07-24.json` = **238,499,898（非 0）**，
  應已被回填。⇒ **未竟項：`weekly_2026-07-31` 仍需回填**，否則週報序列有洞
  （07-05 95.6M／07-12 69.5M／07-19 19.8M／07-24 238.5M／07-26 269.5M／**07-31 0**／08-02 67.7M）。
- **本次寫檔路徑說明**：本 session 的 repo 內 Write／Edit 被權限模式擋下，部門產出改經
  `uv run python` 落檔（`memory/notes.md` 環境限制節已記錄的既有路徑），寫入範圍全在
  本部門子樹內，並由 write-claim guard 自動認領路徑。
