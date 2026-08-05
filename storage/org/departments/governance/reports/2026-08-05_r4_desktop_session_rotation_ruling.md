# R4 長壽 Codex Desktop session 輪替政策 — 治理裁定

- **產出部門**：治理部（`governance`）
- **產出時間**：2026-08-05 16:40（台灣時間）
- **數字口徑更正（v2）**：2026-08-05 17:10（台灣時間），依資源監控部 request
  `item_20260805T090917645325Z_...`
- **對應工作項**：`item_20260805T074441696044Z_r4-codex-desktop-session-codex`
- **來源證據**：`storage/org/departments/resource_monitor/reports/2026-08-05_token_breakdown_v1.md`
  ＋ **更正來源** `storage/org/departments/resource_monitor/reports/2026-08-05_external_figure_inventory.md` §2.3／§2.4

> **v2 修訂摘要**：原文引用的集中度 **34.2%** 是 session_id 層級的**低估值**；fork root
> 收斂後的真值是 **59.0%**。方向與原裁定的假設相反——原裁定擔心數字可能腰斬，實際上它
> 接近翻倍。因此 §2「先修會計再談政策」的**阻塞理由已消失**，§0 與 §3 的 A 項隨之改寫；
> §1 的 anti-stacking 判定不受影響（它從來不依賴這個數字）。舊值保留在 §2.1 以備追溯，
> 不刪改。

---

## 0. 一句話裁定（v2，已更新）

**仍然不新建機制；但「不現在提政策」的理由已經不成立，C3 是否上呈老闆改由經理裁決。**
R4 的可機械化殘餘（rollout 磁碟占用）**已有 enforcement owner**，應收編而非另起爐灶（§1，
未變）。而 R4 的前提數字經 fork root 重算後不再是待定值：單一桌面對話吃掉平台 7 日
**59.0%** 的 billable token，比原本引用的 34.2% 嚴重得多，五步 Gate 的第 1 步「證據化症狀」
**已完成**。治理部原先把 R4 標為 blocked-on-R2，前提是「數字可能反轉結論」——這個前提
已被證偽，**故解除該 blocked 標記**。

---

## 1. Owner-first 判定（anti-stacking §）— 未因數字更正而改變

把 R4 拆成三個 concern，逐一查 `docs/governance/enforcement_layer_map.md` 與
`config/runtime_schedules.json`：

| # | concern | 既有 enforcement owner | 裁定 |
|---|---------|------------------------|------|
| C1 | **自動化 backbone 的 Codex session 壽命** | `scripts/codex_loop.sh` 每 tick 起新的 `codex exec`（`rg rollout\|sessions/` 對該檔零命中）；壽命上界另由 `pretooluse-bash-optimizer.sh` 的「禁止裸跑 codex exec」deny 規則（強制 timeout）把守 | **已有 owner，且本來就沒有長壽問題**。報告本身也印證：codex_exec 僅佔平台 14.1% |
| C2 | **rollout 檔磁碟占用（628.6 MB）** | `log_rotate`（`config/runtime_schedules.json` id=`log_rotate`，每日 04:40，>5MB 截斷）——語意最接近的既有 retention owner | **有 owner，應收編**：把 `~/.codex/sessions/**/rollout-*.jsonl` 的 retention 加進 `cron_log_rotate.sh` 的掃描面，不另建 cleanup job |
| C3 | **老闆桌面互動對話的壽命／輪替門檻** | **無 owner**，且**平台無執行面**——rollout 檔是 Codex.app 的產物，平台沒有任何 hook / cron / deny 能終止或輪替它 | 只能是**對老闆的行為建議**，不可能有機械 owner。屬 boss 核准範圍 |

**anti-stacking 結論（不變）**：C1、C2 都有 owner，不得新增 gate。C3 沒有 owner，但也沒有
任何可寫的 enforcement 檔——為它新建「機制」必然只能是 prose 提醒（strike 1 層級），依
CLAUDE.md 的升級路徑，prose 提醒不算機制，不進 layer map。**數字從 34.2% 變成 59.0%
不會改變這一節的任何一列**：嚴重度提高不會憑空長出一個平台能執行的介面。

---

## 2. 前提數字：從「待定」到「已定」（本節為 v2 主要改寫處）

### 2.1 v1 當時的判斷（保留供追溯）

v1 引用來源報告 §4 F2（行 135–147）：

> Codex fork 造成同一對話被重複計為多個 session…去重鍵 `record_id` 內嵌該 session_id，
> fork 重放同一段歷史時檔名不同 → record_id 不同…**真實重複量介於 0 與 60.1M 之間**。

v1 據此裁定：34.2% 建立在 140.8M 的 Codex 總量上，若重複量落在上界，桌面互動佔比會腰斬；
兩個方向會導向相反的政策，故 R4 標為 **blocked-on-R2**。

### 2.2 v2 的更正：重複量已被量測，且方向相反

資源監控部用 **fork root 收斂**重算（turn-level 去重：去重鍵從 `session_id + 累計 tuple`
換成 `fork root + 累計 tuple`），結果已落檔在
`storage/org/departments/resource_monitor/memory/token_breakdown_2026-08-04_7d.json`
的 `codex_duplicate_audit`，可回讀：

| 量 | 值 | 出處欄位 |
|---|---|---|
| root `019f8e4d-ca99-73e2-a3d0-a7aa7a8cac5f` 的 rollout 檔數 | **76** | `worst_roots[0].rollout_files` |
| 該 root 去重後 billable | **106,410,266** | `worst_roots[0].deduplicated_billable` |
| Codex 全體重複量（實測，非上界） | **4,067,614** | `codex_duplicate_audit.duplicate_billable` |
| 平台 billable（去重前） | **184,380,508** | `totals.billable_total` |
| 平台 billable（去重後） | **180,312,894** | 184,380,508 − 4,067,614 |
| **單一桌面對話集中度** | **59.0%** | 106,410,266 ÷ 180,312,894 = 59.01% |

治理部已獨立回讀原始 JSON 複算，數字對得上（不從摘要轉抄）。

**關鍵反轉**：v1 假設的「重複量可能高達 60.1M」是上界估計；實測只有 **4.07M**，
不到該上界的 7%。而 34.2% 之所以偏低，不是因為重複被高估，而是因為 **fork 把一個邏輯
對話拆成 76 個 rollout 檔，使 session_id 層級的集中度成為下界**。真值是 59.0% ——
近六成，不是三分之一。

**因此 v1 的阻塞理由消滅**：第 1 步「證據化症狀」已完成，證據不再自帶足以翻轉結論的
誤差上界。R4 可以進入後續步驟。

### 2.3 仍未定的量：session 壽命

R3 的 **103.76 小時**同樣是分身值（單一 `session_id` 在窗內的存活時間）。邏輯對話的真實
壽命必然**不短於**分身壽命，root 層級尚未重算，故本文一律寫

> **≥ 103.76 小時（下界，root 層級待重算）**

v1 §4 給老闆的段落中的「連續開了 238 小時」同屬未經 root 收斂的口徑，v2 一併改為下界
寫法。**不給假定值。**

---

## 3. 治理部給經理的建議處置（v2 已更新）

| 項 | 動作 | 執行者 | 優先序 |
|---|------|--------|--------|
| A | ~~R4 標為 blocked-on-R2~~ → **解除 blocked**。前提數字已定值（59.0%），R4 不再受 R2 阻擋。**C3 是否上呈老闆，屬經理裁決**；治理部的意見是值得上呈——近六成集中在單一對話，且平台完全沒有執行面，只能靠老闆自己改習慣 | 經理裁決 | 提升至 P2 |
| B | C2 收編：`cron_log_rotate.sh` 加掃 `~/.codex/sessions/**/rollout-*.jsonl`（同樣的 >5MB 原子截斷語意；rollout 是 append-only JSONL，截尾不影響 Codex 續談，但**需先驗證**這點再上） | platform_eng | P3（不變） |
| C | R3 壽命的 root 層級重算；以及 R2 落地後用修正後口徑複驗 59.0%（回讀計畫見來源報告 §5 檢查項 4：root `019f8e4d` 應為單列 106,410,266） | resource_monitor | 跟隨 R2 |

**治理部不執行 B**（`scripts/` 不在本部門 owned_paths），也不執行 C。本裁定僅釘住
「不新建機制」（§1）與「前提數字已定值、blocked 解除」（§2）。

---

## 4. 給老闆的一段話（v2 已重寫；僅供經理走 proposals 流程時使用，治理部不直接發送）

> 我們在盤 token 帳單時，看到您桌面上有一則 Codex 對話連續開了**至少 104 小時**（真實時間
> 只會更長，我們還在算），而且它一個對話就吃掉了平台**一週用量的 59%** ——接近六成。
>
> 這個數字我們一開始算成三分之一，複核後發現是**低估**：Codex 的「另開分支繼續談」會把
> 同一段對話拆成好幾十個紀錄檔（這則拆成了 76 個），照檔案數去算就會把集中度算小。改用
> 對話為單位重算之後才是 59%。重複計算的部分我們也量了，只有 4M，影響很小。
>
> 平台這邊沒有任何辦法自動處理這件事——桌面 App 的對話不歸平台管，我們不能也不該去
> 中斷它。所以這是一個**只能由您決定**的使用習慣問題：談完一個主題就開一則新對話，
> 累積的上下文不會被反覆重讀，帳單會明顯下降。
>
> 另外我們會順手清理舊對話紀錄檔佔的 628 MB 磁碟，不影響您正在進行的對話。

---

## 5. 制度化寫回

本裁定確立的治理判準（v1 寫入，v2 補充）：

> **帶已知會計缺陷的成本證據，不得直接驅動行為政策。** 先修口徑（第 1 步的證據化尚未
> 完成），再談門檻。否則政策的正確性完全繫於一個標了誤差上界的數字。

v2 補上這條判準的**另一半**，兩者缺一不可：

> **口徑修好之後要回頭解除自己下的 blocked，不要讓它變成永久擱置。** 本案的 blocked 只
> 存活了約半小時就被上游的重算解除——如果治理部不主動回收，一個為了嚴謹而下的 blocked
> 會變成拖延的藉口。**下 blocked 時就要寫明「什麼證據出現時自動解除」**，本案是
> 「重複量被實測」。
>
> 附帶教訓：**誤差上界不等於誤差**。v1 因為一個 0–60.1M 的上界而停手，實測值是 4.07M，
> 不到上界的 7%；而真正讓數字失真的是完全另一個機制（fork 拆檔造成的**低估**），
> 不在當時列出的誤差方向裡。**列了誤差上界不代表窮舉了偏誤方向。**
