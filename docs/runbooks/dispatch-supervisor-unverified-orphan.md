# Runbook — dispatch-supervisor `*_unverified` outcomes（需人工檢查）

**觸發來源**：`storage/ops/dispatch_state.json` 的 `completions[]` 出現 outcome
`orphan_unverified_not_killed` 或 `timeout_unverified`，同時收到
`supervisor orphan_restart` / `supervisor hang_killed` alert email 帶
「未驗證」字樣。

**為什麼會發生**：supervisor 對每個 worker 在 spawn 時用 `ps -o lstart=` 記錄
process 啟動時間戳當身分指紋（防 PID 被 OS 回收後誤殺無辜 process）。若指紋
從未記錄成功（`ps` 呼叫剛好失敗、或 supervisor 在 attach 中途 crash），之後的
kill 決策點就**拒絕對無法驗證身分的 pid 發 signal**——這是刻意的安全 tradeoff
（Codex review 2026-07-04 round-2 認可）：寧可留下一個可能還活著的 process 交給
人工，也不誤殺別人的 process。代價就是這份 runbook 的存在。

**兩個 outcome 的差異**：

| outcome | 發生在 | 意義 |
|---|---|---|
| `timeout_unverified` | health monitor 的 50min max-age 檢查 | worker 超時了，但指紋缺失無法確認那個 pid 還是不是我們的 worker → 沒 kill，slot 已清（排程不卡），process 可能還活著 |
| `orphan_unverified_not_killed` | supervisor 重啟時的孤兒清理 | 前一個 supervisor crash 留下的 job，pid 還活著但指紋缺失 → 沒 kill，slot 已清 |

**人工處理步驟**（收到 alert 後盡快，worker cap 是 50 分鐘，放著不管最多浪費一個
process 的 CPU/token，不會重複派工——slot 已清、新 fire 正常進行）：

1. 從 alert body 或 state file 取得 pid / pgid / started_at：
   ```bash
   jq '.completions[-5:]' storage/ops/dispatch_state.json
   ```
2. 檢查該 pid 現在是誰（**不要**直接 kill）：
   ```bash
   ps -p <pid> -o pid,pgid,lstart,etime,command
   ```
3. 判斷：
   - **command 是 `claude`**（或 node 跑 claude CLI）**且 lstart 與 job 的
     `started_at`（UTC，換算台灣時間 +8）一致（±2 分鐘）** → 這就是我們的
     orphan worker：`kill -TERM -- -<pgid>`，10 秒後還活著再
     `kill -KILL -- -<pgid>`。
   - **command 不是 claude、或 lstart 對不上** → pid 已被回收給別的 process，
     什麼都不用做。
   - **pid 已不存在** → process 自己結束了，什麼都不用做。
4. 無論哪種結果，在 `docs/error_log.md` 記一行（日期 + pid + 判定 + 動作），讓
   頻率可追蹤——若一個月內出現 ≥3 次 `*_unverified`，代表 `ps` 指紋抓取本身
   不穩，回頭看 `scripts/dispatch_supervisor/procutil.py:get_process_start_wall`
   的失敗原因（是否 timeout 5s 太緊、launchd 環境 `ps` 權限問題等），照
   Three-Strike Rule 處理。

**相關程式**：
- 指紋機制：`scripts/dispatch_supervisor/procutil.py`（`check_identity` 四態）
- kill 決策點：`scripts/dispatch_supervisor/health.py:check_once`、
  `scripts/dispatch_supervisor/supervisor.py:_handle_restart_orphan`
- 背景：`docs/refactor_plan_hourly_dispatch.md` §6 Codex review round-2 findings

*Created 2026-07-04 — Codex review round-2 medium finding #2 的 cutover 前置條件。*
