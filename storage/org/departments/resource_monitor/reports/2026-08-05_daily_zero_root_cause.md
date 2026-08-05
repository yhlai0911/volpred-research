# 今日 daily 報表為 0 的根因（2026-08-05 22:0x 台灣時間）

工作項 `item_20260805T135712462998Z`（P1, manager）｜資源監控部

## 結論先講

**根因已定位、且已經修好了——修法是今天 15:17 上線的，而那個 0 是 15:17 之前 7 小時 17 分產生的。**
不需要補資料，也不需要新修法。明早 08:00 那班會自動重產。**但這件事仍然是我的失職**，
理由在第 4 節。

## 1. 症狀與證據（全部可回讀）

| 事實 | 證據 |
|---|---|
| `daily_2026-08-05.json` 的 `billable_total` = 0 | 實讀 payload |
| 該檔寫於 **2026-08-05T00:00:50Z**（= 台灣 08:00:50） | `stat` mtime |
| 檔案大小 1,232 bytes（正常日報 25–31 KB） | `ls -l` |
| 今日真實用量 ≥ 4,734,619 billable | 本部門 D43 獨立重算（`tools/today_burn.py`） |

## 2. 根因鏈

今早 08:00 的 `cron_token_report.sh` → `volpred ops token-usage-maintain`。
當時跑的是**修法前的程式碼**，log 原文（`storage/logs/cron/token_report.log`）：

```
"target_date": "2026-08-05", ... "action": "generate_daily_report"
runs: [{"command": "uv run python scripts/token_usage_report.py --date 2026-08-05", "returncode": 0,
        "stdout_tail": [... "Billable: 0" ... "Saved: daily_2026-08-05.json"]}]
"after": {"action": "skip", "daily_report_exists": true, "latest_daily": {"billable_total": 0}}
```

**它在 UTC 日開始後 50 秒統計「今天」，必然近 0；寫檔之後 `daily_report_exists=true`，
於是同一班的後續判定變成 `skip`，這個 0 就被鎖在磁碟上。**
這正是 F1 的定義症狀，不是新缺陷。

**修法 `dab112d3a` 的落地時間是 2026-08-05T15:17:15+08:00**（`git log`），
比今早那班晚 **7 小時 17 分**。所以今天這個 0 是 **F1 的最後一個受害者**，
在修法存在之前就已經寫下了。

## 3. 現行程式碼會不會自癒——不預測，直接問 planner

```
_report_covers_its_period(daily_2026-08-05.json, period_end=08-06) = False
build_token_usage_maintenance(target_date=2026-08-05):
    action = generate_daily_report     skip = False     daily_report_exists = False
    execution_commands = ['uv run python scripts/token_usage_report.py --date 2026-08-05']
```

**明早 08:00（= 08-06T00:00Z）那班會重產它**，因為該檔的 mtime（08-05T00:00:50Z）
早於它自己期間的結束（08-06T00:00Z），完整性守則判它不算數。
對照組：今天這班 `target=08-04` 回 `action=skip`（08-04 已於 15:15 回填、mtime 在期間之後），
也就是自癒**只針對真的不完整的那些**，不會亂重產。

**所以 (1) 的正確處置是「不動它」**：人工補一次會把 mtime 蓋成期間之後，
反而讓自癒機制以後認為它是完整的——**補資料在這裡不只是多餘，是有害的。**

## 4. 但這仍然是我的失職，而且失職點不在修法

我今天做了 D43 全日 token 盤點，自己算出 **4,734,619**。
canonical 日報寫著 **0**。**兩個數字都在我手上，我沒有把它們放在一起看。**

我的獨立重算是為了回答經理的問題（停擺窗燒了多少、部門制倍數多少），
算完就交件了；**我沒有問「那落檔的那份說多少」**。
如果問了，今天下午就會發現這個 0，而不是等老闆問「資源監控部在放假嗎」。

這正是「量測本身沒產出」這一類——它不會出現在任何人的收件匣裡，因為它的症狀就是**沒有東西出現**。
已寫進 charter（見第 6 節）。

## 5. 順著同一條線抓到的第二個儀表缺陷（P1，已交 platform_eng）

`ops_snapshot.alerts.sent_last_24h` **結構性恆為 0**：
- 讀端 `scripts/ops_snapshot.py:181` 讀 `sent_at` / `ts`
- 寫端 `src/volpred/ops/alerts.py:889` 寫的是 `last_sent_at` / `first_sent_at`
- 全量佐證：`storage/ops/alert_dedup.json` 678 筆中，有 `sent_at` 的 **0 筆**、
  有 `ts` 的 **0 筆**、有 `last_sent_at` 的 636 筆（最近 08-05T12:01:01Z）

而 `scripts/org/_core.py:297` 把它渲染成「alerts 已送 N 則」進**每一份經理 brief**。
今天下午平台停擺 2h45m，經理的 brief 全程顯示 0 則告警——
**「平台正常」與「平台停擺」在這個儀表上長得一模一樣。**

## 6. 兩個儀表不可互相回答（已寫進 charter）

| 問題 | 唯一可信來源 | 不可用來回答 |
|---|---|---|
| 額度還剩多少 | Claude Code `/usage` 的 All models 週百分比 | billable、本地 cap、任何估算 |
| 誰花的／花在什麼／成本歸屬 | billable telemetry | `/usage` 百分比 |

**今天的實測落差**：08:00 那封 email 報「59.0M / 77.7M cap」= **76%**，
而 `/usage` 是 **89%**——低報 13 個百分點。
`config/token_quota_calibration.json` 的錨點停在 **2026-07-01**（35 天前）；
`scripts/weekly_quota_estimate.py` 內另有一個反推 cap ≈ 213.3M，
與 email 的 77.7M **差 2.75 倍**——同一個帳號的同一個週上限，repo 內有兩個互相矛盾的值。
該檔自己的註解記著上一個錨點漂 7 週、估出 122.4% 而實際 54%（低估 2.26 倍）。

**結論：billable 回答「還剩多少」不是近似，是會給出相反結論的錯答案。**

## 7. 誠實邊界

- 我**沒有 owned_paths**，`scripts/`、`config/`、`src/volpred/` 都不是我能改的。
  第 5、6 節兩個缺陷已以 request 送 platform_eng（`item_20260805T140214140944Z`），
  附行號與全量佐證，他們可直接動手。**我這一班沒有修任何程式碼，也不宣稱修了。**
- 89% 這個數字來自老闆的 `/usage` 讀數，我在 headless session 讀不到 `/usage`，
  **沒有獨立驗證**，只驗證了 email 側的 76% 與兩個 cap 常數的矛盾。
- 「明早會自癒」是對現行程式碼的判定（planner 直接回答），不是對明早那班會不會準時 fire 的保證。
