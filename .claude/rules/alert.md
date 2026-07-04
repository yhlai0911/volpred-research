---
paths:
  - "src/volpred/ops/alerts.py"
  - "src/volpred/publisher/email_notifier.py"
  - "scripts/check_alerts.py"
  - "scripts/daily_update.py"
  - "config/runtime_schedules.json"
  - "scripts/session_startup.md"
  - "storage/ops/alert_dedup.json"
---

# Alert Rules

- Email alert 收件人固定：`yihao.lai@gmail.com`。
- SMTP secrets 只能讀既有 `.env` / `.env.local`；禁止硬編碼帳密。
- 手動寄送入口：
  ```
  uv run volpred ops send-alert --level <info|warn|critical> --title "..." --body "..."
  ```
- 條件檢查入口：`uv run volpred ops check-alerts --storage-dir storage`。
- 一鍵 script：`uv run python scripts/check_alerts.py`（log 友善輸出，適合 cron）。
- 手動測試旁路 dedup：`uv run volpred ops send-alert --level info --title "..." --body "..." --force`
- `check-alerts` 目前正式接線的 3 個條件（單一 source: `src/volpred/ops/alerts.py`）：
  1. `release_pool_gap` — `storage/logs/cron/release_pool.log` 最後 fire 時間距今 > 2 小時 → critical（>4h）/ warn
  2. `draft_pool_low` — `feed.json` 中 `draft` 文章數 < 4 → warn（=0 升級為 critical）
  3. `host_cron_fail` — **v12 後僅看** `storage/logs/cron/*.log` 最新 `=== exit N ===` 非 0 → critical。
     scheduler-tick staleness 在 v12 已降級為 advisory-only（body 內 readout 供參考，不貢獻 breach judgement）。
  4. `member_qa_stale` — `questions` 表 pending（status=`evaluating`/`pending`/未 ranked）`created_at` 距 now 超過 24h → warn / 超過 72h → critical（2026-04-26 新增；防 5 天 silent gap 再現）。
  5. `push_backlog` — `git rev-list origin/main..main` 最老未推 commit 滯留 >3h → warn / >8h → critical（2026-07-04 新增；26h push-hold incident 教訓：silent-fallback gate 正確擋 push 但無機制強迫行動——此條件直接量測傷害「未推積壓年齡」，held/分岔/認證/網路任何原因同樣浮現，且不受該 job 自身 warn email 的 24h dedup 影響）。

## Alert 觸發 → 主線程 auto-remediation（2026-04-19 用戶要求）

**硬規則**：Alert 寄出**不只是通知**，主線程**必立即採取對應 action** 解 breach。email 給用戶是 log，不是責任轉移。

| Alert | 主線程 auto-action |
|---|---|
| `draft_pool_low` | 派 agent 寫 daily_article draft 補池（依 publication-candidates skill 選題）|
| `release_pool_gap > 2h` | `VOLPRED_ACTOR=claude uv run volpred ops release-pool-by-settings` 手動釋出；同時查 cron 為何沒 fire |
| `publishing_freshness`（發文脫班 dead-man switch） | **已全自動 wired**（2026-07-03 boss email-12559）：`scripts/check_alerts.py` 每小時在寄 alert email 前呼叫 `scripts/remediate_publish_drought.py --apply` → force-release（drought circuit-breaker 挑最不重複草稿）→ 若 released 0（池空 / 全 arc-dup 重寫）則 refill fresh 主題供下班 hourly dispatch 生成。**主線程/老闆都不需手動跑指令**；alert body 用「已自動修復」框架；只有連續 2 班 hourly dispatch 仍脫班才人工檢查 generator |
| `host_cron_fail` | 查 `storage/logs/cron/<name>.log` error，修 script / 路徑 / FDA 權限 |
| `push_backlog` (>3h/>8h) | 主線程**立即**：`tail -40 storage/logs/cron/git_push_backup.log` 查原因 → HELD 就跑 `audit_silent_fallbacks --strict` 修 NEW 位置（per no-silent-fallback rule）並 commit → `bash scripts/cron_git_push_backup.sh` 解封 → 驗證 ahead=0（per memory `feedback_fix_silent_fallback_immediately`：當場修，不留下一班）|
| `Supabase sync fail` | 查 supabase_sync.py log，restart sync 或 manual reconcile |
| `Agent task fail > 3` | 查 work_log outcome=failed pattern，派新 agent with better brief 或清 stale |
| `Token 突增` | 檢 session_state + token_usage_report，降低派工頻率 or 派 compact |
| `重大 K PASS / paradigm shift` | 通知用戶 + 派 publication-candidates + 進投稿 / paper body 更新 pipeline |
| `Paper reviewer response` | 派 paper-review-cycle skill + 進 revision workflow |
| `策略 MDD > 20%` | 暫停策略上架 + 派 strategy lifecycle review agent |
| `member_qa_stale` (pending >24h / >72h) | 主線程**立即**跑 question-ranking-workflow → 4 維度評分 → question-rerank（不等下一個 6h cron tick）；ranked>0 後 dispatch claude subagent 走 research → answer → finish |
| `paper_website_drift` (網頁 over-claim) | 對每篇 over-claim 先確認 pipeline `stage` 為真實狀態，再用 `uv run volpred ops paper-upsert --paper-id <id> --status <...> [--target-journal <...>]` 對齊（**非**自動 sync；兩前端讀同一 `/api/papers` 一次即同步）。決策改了、網頁沒同步 = M3 學術權威 credibility 受損 |

**無 auto-action 情境**：alert 條件不明 / 需用戶 policy decision → 明標 "L11 policy pending" 於 signal_payload，**主線程立記 pending** 並每輪 check 是否用戶已回覆。

**Anti-pattern**：
- 看到 alert sent 就 stub skip（算力閒置 + alert 變 noise）
- 只寄 email 不 action → 下次 alert 再寄 → 用戶 inbox 被 spam
- dedup 24h 內不 re-send 不等於不處理；dedup 是防 email spam，action 仍要做

### Alert body 框架：「已自動執行」不是「建議老闆行動」（2026-07-03 boss email-12559 硬性糾正）

boss 原話：「你應該不是建議行動 而是你應該要直接行動吧？」凡是**有明確 auto-remediation
路徑**的 alert（上表左欄），body 的行動段落**必須**寫成「## 系統已自動修復 / 已自動執行 +
結果」，**不可**寫成對老闆下 imperative 指令的「## 建議行動」（`1. 跑 X 指令 2. 派 Y`）。
老闆看到 alert = 知道系統做了什麼、是否需人工介入，而不是收到一張待辦清單。
只有**真正需要老闆 policy 判斷**（投稿與否 / paid data 採購 / 研究 pivot）的 alert 才保留
boss-facing 決策段，且須明標「## 需老闆決策」而非「建議行動」。此為 boss-facing 措辭原則，
與 `feedback_plain_language_boss_facing`（白話化）並列。

## Body 三段結構（用戶 2026-04-19 要求）

每個 alert body 必須是 **三段結構**，不要只 dump 事實數字：

```
## 觸發條件
<事實 + 數字 + 相關檔案路徑>

## 影響
<1-2 句：為什麼這個 breach 重要，對 Mission 哪條目標（第 1 條內容 / 第 5 條流量 / 資料完整）影響>

## 建議行動
<具體 CLI command / 主線程下一步 / 相關 skill / error log 線索>
```

- 保持 plaintext markdown-like（`##` 當 section header）；email 客戶端都支援 plain text 顯示。
- 每 alert body **<800 字**（太長用戶 email 讀不完）。
- `send_alert()` signature 不變；body 組裝發生在各 `_parse_*_state()` 函式裡。
- 新增 alert 條件時務必產生符合三段格式的 body，不只事實 dump。
- 去重規則：同一 alert 以 `sha256(level + "\\0" + title)` 當 key；24 小時內不可重寄。
- 去重狀態檔：`storage/ops/alert_dedup.json`。不要手動改這個檔案來「消警報」。
- Hook 點：
  - `scripts/daily_update.py` 結尾自動呼叫 `_run_alert_checks()`（每日 08:03 cron）
  - 建議 host crontab 每小時跑：
    ```
    0 * * * * cd /path/to/volpred-research && uv run python scripts/check_alerts.py >> storage/logs/cron/check_alerts.log 2>&1
    ```
- Session/local/cloud prompt 若要做平台巡檢或續跑，應先跑 `check-alerts`，讓系統自行 dedup + dispatch。
- 新增 alert 條件時，優先擴充 `src/volpred/ops/alerts.py`（在 `build_alert_condition_report` 加新 `_parse_*_state`），不要把判斷散落在多個 prompt 或 shell script。
