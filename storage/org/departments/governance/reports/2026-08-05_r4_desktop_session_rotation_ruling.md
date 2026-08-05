# R4 長壽 Codex Desktop session 輪替政策 — 治理裁定

- **產出部門**：治理部（`governance`）
- **產出時間**：2026-08-05 16:40（台灣時間）
- **對應工作項**：`item_20260805T074441696044Z_r4-codex-desktop-session-codex`
- **來源證據**：`storage/org/departments/resource_monitor/reports/2026-08-05_token_breakdown_v1.md`

---

## 0. 一句話裁定

**不新建機制、也不現在提政策。** R4 的前提數字（單一對話 238 小時、佔平台 7 日用量
34.2%）由同一份報告的 F2 標記為**會計缺陷未修時的上界估計**，而 F2 的修法（R2）尚未落地；
在拿未定口徑的數字去改老闆的桌面工作方式之前，先修會計。R4 的可機械化殘餘（rollout
磁碟占用）**已有 enforcement owner**，應收編而非另起爐灶。

---

## 1. Owner-first 判定（anti-stacking §）

把 R4 拆成三個 concern，逐一查 `docs/governance/enforcement_layer_map.md` 與
`config/runtime_schedules.json`：

| # | concern | 既有 enforcement owner | 裁定 |
|---|---------|------------------------|------|
| C1 | **自動化 backbone 的 Codex session 壽命** | `scripts/codex_loop.sh` 每 tick 起新的 `codex exec`（`rg rollout\|sessions/` 對該檔零命中）；壽命上界另由 `pretooluse-bash-optimizer.sh` 的「禁止裸跑 codex exec」deny 規則（強制 timeout）把守 | **已有 owner，且本來就沒有長壽問題**。報告本身也印證：codex_exec 僅佔平台 14.1% |
| C2 | **rollout 檔磁碟占用（628.6 MB）** | `log_rotate`（`config/runtime_schedules.json` id=`log_rotate`，每日 04:40，>5MB 截斷）——語意最接近的既有 retention owner | **有 owner，應收編**：把 `~/.codex/sessions/**/rollout-*.jsonl` 的 retention 加進 `cron_log_rotate.sh` 的掃描面，不另建 cleanup job |
| C3 | **老闆桌面互動對話的壽命／輪替門檻** | **無 owner**，且**平台無執行面**——rollout 檔是 Codex.app 的產物，平台沒有任何 hook / cron / deny 能終止或輪替它 | 只能是**對老闆的行為建議**，不可能有機械 owner。屬 boss 核准範圍 |

**anti-stacking 結論**：C1、C2 都有 owner，不得新增 gate。C3 沒有 owner，但也沒有任何
可寫的 enforcement 檔——為它新建「機制」必然只能是 prose 提醒（strike 1 層級），依 CLAUDE.md
的升級路徑，prose 提醒不算機制，不進 layer map。

---

## 2. 為什麼現在不提政策：前提數字不可當定論

引用來源報告 §4 F2（行 135–147）：

> Codex fork 造成同一對話被重複計為多個 session…去重鍵 `record_id` 內嵌該 session_id，
> fork 重放同一段歷史時檔名不同 → record_id 不同…**真實重複量介於 0 與 60.1M 之間**。

R4 主張的 34.2% 建立在 140.8M 的 Codex 總量上。若重複量落在上界，桌面互動的真實佔比會
從 34.2% 掉到接近一半以下；若落在下界則 R4 成立。**這兩個結論會導向完全相反的政策**
（要不要請老闆改變工作方式），所以現階段任何門檻數字都是猜的。

報告自己列的 R2（session 身分改綁 `session_meta.session_id`，P1，owner=Codex 熱區
`scripts/token_usage_report.py`）尚未落地。**R4 的前置條件是 R2。**

這也符合結案五步 Gate：R4 目前只到第 1 步「證據化症狀」，且證據本身帶已知偏誤，
根因層級未定 → 不得進第 3 步「重構底層邏輯」。

---

## 3. 治理部給經理的建議處置

| 項 | 動作 | 執行者 | 優先序 |
|---|------|--------|--------|
| A | **R4 標為 blocked-on-R2**，重排在 R2 之後；不現在做政策 | 經理排序 | — |
| B | C2 收編：`cron_log_rotate.sh` 加掃 `~/.codex/sessions/**/rollout-*.jsonl`（同樣的 >5MB 原子截斷語意；rollout 是 append-only JSONL，截尾不影響 Codex 續談，但**需先驗證**這點再上） | platform_eng | P3 |
| C | R2 落地後，由資源監控部用修正後口徑重算桌面佔比，再判斷 C3 是否值得驚動老闆 | resource_monitor | 跟隨 R2 |

**治理部不執行 B**（`scripts/` 不在本部門 owned_paths），也不執行 C。本裁定僅釘住
「不新建機制」與「R4 排在 R2 之後」。

---

## 4. 給老闆的一段話（僅供經理走 proposals 流程時使用，治理部不直接發送）

> 我們在盤 token 帳單時，看到您桌面上的 Codex 對話有一則連續開了 238 小時，粗估佔了平台
> 一週用量的三分之一。但我們自己複核後發現，這個數字的算法有一個已知缺陷：Codex 的
> 「另開分支繼續談」會讓同一段對話被重複計算，最多可能虛增到六成。所以我們**先不建議您
> 改變任何使用習慣**——我們會先把算法修對，用可靠的數字再回報一次。若修正後桌面用量
> 仍然偏高，我們才會提出具體建議（例如談完一個主題就開新對話）。這期間會順手清理舊
> 對話紀錄檔佔的 628 MB 磁碟，不影響您正在進行的對話。

---

## 5. 制度化寫回

本裁定確立一條可複用的治理判準，已寫入 `memory/notes.md`：

> **帶已知會計缺陷的成本證據，不得直接驅動行為政策。** 先修口徑（第 1 步的證據化尚未
> 完成），再談門檻。否則政策的正確性完全繫於一個標了誤差上界的數字。
