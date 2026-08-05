# 部門權責與寫入權不對齊 — 治理立案與裁定

- **產出部門**：治理部（`governance`）
- **產出時間**：2026-08-05 17:40（台灣時間）
- **立案由來**：內容部在 `item_20260805T093855018606Z` 主動提議立案並提供證據；
  治理部本日自身踩到三次；`publications` / `resource_monitor` journal 亦有紀錄
- **對應工作項**：`item_20260805T093855018606Z_mile-63e0e1ff-config-series-reg`

---

## 0. 一句話裁定

**這個 class 成立，但它的機械 owner 今天已經誕生了（`a17aa310c`，17:32），所以裁定是
「不新建任何權限層」。** 殘餘缺口不在機制，在**宣告**：4 個部門的 `owned_paths` 是空的或
過窄，而權限產生器忠實地按宣告發權——**宣告什麼就得到什麼，宣告空的就什麼都得不到**。
要動的是 `registry.json`（經理職權），不是再寫一道 gate。

---

## 1. 症狀盤點（跨 5 個部門，同一天）

| 部門 | 事件 | 出處 |
|---|---|---|
| governance | 三次：`docs/governance/**` 寫不進（週次 audit 報告只能暫存部門子樹）、`enforcement_layer_map.md` 一行修不了（`audit_enforcement_map.py` 紅燈至今）、`.claude/rules/paper-workflow.md:62` 一行修不了 | 本部門 journal 2026-08-05T09:00Z／09:32Z |
| content | 三次：`storage/drafts/` 目錄級鎖、缺 `mv` 權限（收尾契約機械上做不到）、`config/` 無權 | `content/journal.md:6`、`:30`；本案 request |
| publications | 寫不進 `paper/` 與 `experiments/`，review round 歸檔卡住；寫不進 `.claude/rules/` | `publications/journal.md:134`、`:245` |
| resource_monitor | 兩次上報 `weekly_2026-07-31.json` 需回填但不在 `owned_paths` | `resource_monitor/journal.md:38`、`:65` |
| member_success | 無法寫入轄區，被 policy.md 記為「判斷對了卻沒走管道」的示範案例 | `storage/org/policy.md` §卡住了要走組織管道 |

**≥3 strike 早就滿足**，且是同一根因、跨部門、同日重複——依 CLAUDE.md「一旦看見結構性
root cause 就立刻重構，不等次數累積」，本案不該再等。

## 2. 根因（已定位到機械層，不是推測）

兩套系統各自為政：

| 層 | 誰宣告轄區 | 今日狀態 |
|---|---|---|
| **組織層** | `storage/org/registry.json` 的 `owned_paths` | 7 個部門中 **4 個是空陣列**（governance / member_success / publications / resource_monitor） |
| **執行層** | Claude Code permission allow-list | 專案 allow-list **116 條規則、Edit/Write 為 0**（`.claude/settings.json` 5 條＋`.claude/settings.local.json` 111 條，逐條統計） |

沒有 Edit/Write 規則 ＋ don't-ask 模式 = 每一次寫入都要有人坐在那裡按同意。這就是
五個部門同時「有正確判斷、沒有對應轄區」的機械解釋。

## 3. 機械 owner 已存在——不得再疊一層（anti-stacking §）

平台工程部今天 17:32 落地 `a17aa310c`，`scripts/org/org_attach.py:156 generate_dept_settings()`
**就是這個 concern 的 enforcement owner**：

- 從 `registry.json` 讀 `owned_paths`，產生 `Edit(...)` / `Write(...)` allow 規則，
  範圍是 `storage/org/departments/<dept>/**` ＋ 該部門 `owned_paths`，**不多給一寸**
- 補了收尾契約需要的 `mv` 與 `mkdir`（內容部回報的那一項）
- 同 commit 把 claim 身分從 session 改成部門，修掉「部門擋自己下一班」

**裁定：任何人不得為此 concern 新增第二套權限機制**（不得手寫
`departments/<dept>/settings.json`、不得放寬全域 allow-list、不得用
`VOLPRED_ALLOW_CONCURRENT_WRITE` 當日常出路）。要更多權限，**只能改 registry 的宣告**，
讓既有產生器去發——這樣「誰能寫什麼」永遠只有一份真相。

**操作面警告**：`generate_dept_settings` 在 **attach 時**產生設定。`a17aa310c` 之前啟動的
部門 session（含本 session）**不會**拿到新權限。經理要讓修法生效，必須讓部門重新 attach，
否則會看到「修了卻沒用」而誤判機制失效。

## 4. 殘餘缺口＝宣告，不是機制：建議的 `owned_paths`（經理裁決）

治理部不改 registry。以下是逐部門建議與理由，**每一列都對得上該部門今天實際被擋的事**：

| 部門 | 現況 | 建議 | 理由／邊界 |
|---|---|---|---|
| `governance` | `[]` | `docs/governance/`、`.claude/rules/` | 兩者都是本部門章程明列的產出面（skill/rules 治理、enforcement owner 稽核）。**`.claude/skills/` 刻意不列入**——改 skill 有「必寄信通知老闆」的義務且是跨部門共用面，維持走 request |
| `publications` | `[]` | `paper/` | 章程 owned_task_types = paper_review／paper_body／paper_decision，產出物就在 `paper/`。**`experiments/` 不給**（是研究部的），維持走 request |
| `content` | `storage/drafts/` | 維持 | 目錄級鎖與 `mv` 兩項已由 `a17aa310c` 修掉；`config/article_series.json` **不建議給**——它是跨部門 registry，正確路徑是 request（本案已如此走） |
| `resource_monitor` | `[]` | 維持空 | 它今天要動的是別人產生的資料檔（`weekly_*.json` 回填），**資料錯誤要修產生它的程式**，給它寫入權會鼓勵改資料而不是修流程。上報是對的 |
| `member_success` | `[]` | **待該部門提出證據後再議** | 本部門今天沒有它實際被擋在哪個 path 的一手證據，不憑印象發權 |
| `research` | `experiments/` | 維持 | 今日無相關症狀 |
| `platform_eng` | `frontend-v2-fix/` | **待議** | 它今天代寫了大量他部門轄區（rules／config／scripts），實際上是「代工窗口」。這是否該制度化，牽涉 Zone A 與 Codex 分工，需另案 |

## 5. 附帶必修：`policy.md` 沒有 Zone 的定義

7 份 charter 的 §邊界都寫「自己 `owned_paths` 與 **Zone C 共用區**」，但 `policy.md` 全文
沒有 Zone 的定義，真正的定義在 `docs/agents/ownership.md:60`（一張 7 列具名表，
**不含 `docs/governance/**` 也不含 `config/**`**）。部門在自己的身分簡報裡查不到自己的
邊界——這是本日多起「判斷對了卻不知道能不能動手」的共同前置原因。

建議在 `policy.md` 補一節：Zone A/B/C 對部門的意義 ＋ 指向 `ownership.md` 的 pointer。
**不複製表格內容**（複製＝第二份會漂移的副本，違反 policy.md 自己的開場白）。

---

## 6. 制度化寫回

> **「宣告」與「權限」是同一件事的兩半，中間不該有人工翻譯。** 本案在
> `generate_dept_settings()` 出現之前，registry 的 `owned_paths` 只是一句話；
> 之後它才真的是權限。判準：**看到「某某沒有權限」的回報時，先問這個 concern 有沒有
> 產生器，有就去改它的輸入（宣告），沒有才談建機制。** 直接改 allow-list 是繞過產生器，
> 會製造第二份真相。（已寫入 `memory/notes.md`）
