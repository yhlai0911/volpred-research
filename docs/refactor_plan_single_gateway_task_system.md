# Refactor Plan: 任務系統單一關口（single gateway）收斂

**日期**: 2026-07-16 深夜
**指令來源**: 老闆（互動 session）：「重新設計精密的功能彙整 不要疊床架屋、一堆重複相互牽制」「該單一關口的 就單一關口」
**觸發 incident**: 同晚兩個並行互動 session 對老闆同一則 Telegram 訊息（msg 877）做出**矛盾雙回覆**（msg 879 vs msg 880），並把同一研究議題排進**兩套不同的任務系統**（一套是 canonical queue，一套是無人消費的黑洞）。

## 三層診斷

### 1. 底層邏輯（domain model 錯誤）

任務域存在**兩個寫入口、一個執行者**：

| 入口 | 寫到哪 | 誰執行 | 現況 |
|------|--------|--------|------|
| `next_tasks.json` append（refill / event_jobs / alert router / 手動） | `storage/next_tasks.json` | `dispatch-supervisor` + 互動 session claim | ✅ canonical（control-plane.md 定調） |
| `volpred ops assign`（cli.py:874 → `local_control_plane.create_task`） | `storage/ops/tasks/*.json` | **沒有任何排程消費**（唯一 reader = 手動 `volpred ops claim-next`，無人在跑） | ❌ write-only 黑洞 |

證據：`storage/ops/tasks/` 累積 **16 個 status=queued**（2026-07-11 ~ 07-16），全部從未被派工。其中包括已被其他路徑做掉的（CI push 收尾）、**結論已被推翻絕不能執行的**（K1695「回撤保護存活」文章——該結論 7/15 已撤回）、與 canonical queue 重複的（Telegram 結構化回報格式）。

Control-plane.md 早在 2026-05-04 就裁定 `storage/ops/tasks/` = execution receipts（非 pending queue），但**只改了規則沒關入口**：散文管不住活代碼，`ops assign` 四天內又被並行 session 當正式入口用了 7+ 次。

### 2. 流程（協作缺口）

- 兩台機器／兩個並行 session 操作同一份 storage，claim 防撞只覆蓋 `next_tasks.json` 這套；用 `ops assign` 的那條路完全繞過防撞。
- **外部回覆（Telegram）無冪等關口**：FB 有 `fb_post_status` guard，git 有 writer lock，memory 有 shared_state_lock——Telegram 回覆是僅剩的無 gate 對外通道。本 session 也違反 claim-first（先做研究、先回覆、最後才 claim → claim 時發現對方已完成，訊息已送出收不回）。

### 3. 架構

single-writer / single-gateway 原則在其他域都有機械 owner，任務域缺位。修法不是加第三層 watchdog（anti-stacking），而是**關掉多餘入口**。

## 設計（單一關口）

### 關口 A：任務唯一入口 = `storage/next_tasks.json`

1. `volpred ops assign` **保留 CLI 介面、重定向實作**：改寫為 `next_tasks.json` 的 thin wrapper（沿用 flock append 慣例），欄位對映：
   - `task_family` → `task_type`（ops→platform_ops、research→experiment、article→daily_article、paper→paper_review、其他→platform_ops）
   - `priority`（local plane 大數字）→ P1-P4（≤10→1、≤50→2、≤100→3、>100→4）
   - id：`assign_<hex8>`；`source` 保留原值
   - 不再寫 `storage/ops/tasks/`
2. `volpred ops claim-next` / local control plane 的 queued 消費路徑：標 deprecated（stderr 警告 + 指向 `task_pool_claim.py`），存量遷移完成後移除。
3. `storage/ops/tasks/` 回歸 receipts-only。

### 關口 B：老闆訊息唯一回覆權

- 回覆老闆訊息（telegram_reply task）前**必須先 claim 成功**；claim 被拒（already_claimed / already_completed）→ **禁止送出回覆**。
- 機械 owner：`telegram-send` CLI 新增 `--reply-to-task <task_id>` 參數：送出前檢查該 task 狀態，`succeeded`/`claimed by others` → 拒發（exit 非 0），杜絕雙回覆。responder SOP / dispatch prompt 同步改為必帶此參數。

### 關口 C：存量 16 個 queued 的 triage 處置

| 處置 | 任務 |
|------|------|
| **superseded（已被做掉）** | cb8439b588c3（7/15 CI push 收尾）、10db9a3e1102（K1695 Table 5 rebind——v4 reproduce +33 checks 已覆蓋） |
| **deprecated（結論已推翻，執行有害）** | 0b511962b10c（K1695「回撤保護存活」文章——結論 7/15 已撤回，正確版文章 mile_badbc47b 已發） |
| **duplicate（canonical queue 已有）** | c15a8faa3da5（Telegram 結構化回報 ≒ next_tasks `governance_telegram_structured_progress_report_format`） |
| **merge-improve（與今晚拆解合併）** | 31d75ca61913（credit/CDS→AI 股 vol）——brief 補 K872/T14/K1621 aggregate-NULL 教訓 + firm-level 差異化 + 控制 VIX 主檢定後，以單一任務遷入 canonical queue |
| **migrate（仍有效，原樣遷入）** | 其餘 11 個（CPI/NFP 日期污染 ×3、K1684 E2、daily_update dirty-guard、PHASE-Z orphan 警報、feed audience mismatch、paper snapshot 並行 append、CI 卡死 5 測試、CI 通知白話根因、運營回報排版） |

### 驗證 gate（機械 owner，唯一）

`scripts/tests/test_ops_tasks_receipts_only.py`：斷言 `storage/ops/tasks/*.json` 中非終態（queued/claimed/running/awaiting_approval）數量 = 0。CI 跑。這是 receipts-only invariant 的唯一 enforcement owner；不再新增第二層 watchdog。

## 廢棄面

- `local_control_plane.create_task` 的 assign 呼叫路徑（重定向後不再產生新檔案）
- `claim-next` 消費 lane（deprecation → 觀察一輪 → 移除）
- 不動：`storage/ops/tasks/` 歷史 receipts（audit trail 保留）

## 為什麼不是「再加一個同步器」

把兩套 queue 用同步器對齊 = 疊第三層床架屋（dual-source 的 canonical 解法是消滅一個 source，不是調和兩個）。同理，Telegram 雙回覆的解法是回覆權綁 claim，不是「回覆後互相檢查」。
