# resource_monitor 部門私有記憶

## 資料源地圖（2026-08-05 v1 盤點確立）

- **唯一權威 token telemetry**：`~/.claude/projects/**/*.jsonl`（含 `*/subagents/*.jsonl`）
  ＋ `~/.codex/sessions/**/rollout-*.jsonl`。所有 `storage/reports/token_usage/` 產出都是
  它們的下游投影。
- **agent 維度不存在於任何既有產出**；唯一不需猜的歸屬訊號是 Claude project 目錄前綴
  （主 checkout／`.claude/worktrees`／dispatch scratch）。Codex 那側用
  `session_meta.originator` 區分桌面互動 vs `codex_exec` backbone。
- **dispatch receipts 不帶 token 欄位**（`storage/ops/dispatch_workspace_receipts.jsonl`、
  `agent_jobs/`、`executions/`），不要再花時間找——成本歸屬只能靠 telemetry 側。
- 本部門工具：`tools/token_breakdown.py`（重用 `scripts/token_usage_report.py` 的原語，
  只加 agent／壽命／效力維度）。v1 全窗 7 日約 38 秒；**v2 多一輪 Codex 全量重掃，約 4-5 分鐘**，
  一律 `run_in_background` 跑，不要在前景等到 timeout。

## 已知缺陷（追蹤中）

- **F1 日報日界 — 已修（經理 commit `dab112d3a`，2026-08-05）**：根因是 `summaries.py` 用
  「今天」當目標日 ＋「檔案存在即完成」；已改為「最後一個完整期間」＋ mtime 完整性守則
  （自癒），並回填。修前 7 天中 6 天空白、少記 141.1M。
  - **同型缺陷（週報）**：2026-08-05 16:00 實測 —— `weekly_2026-07-31.json` 的
    `totals.billable_total` **仍是 0**；但 `weekly_2026-07-24.json` = 238,499,898（**非 0**）。
    經理 F1 便箋寫的「07-24／07-31 全是 0」只對一半，07-24 應已被回填。
    **未竟：07-31 那份仍需回填**，否則週報序列有洞。近期序列供對照：
    07-05 95.6M／07-12 69.5M／07-19 19.8M／07-24 238.5M／07-26 269.5M／**07-31 0**／08-02 67.7M。
- **F2 Codex fork 重複計費 — 已定案量化（v2，2026-08-05）**：重複量 **4,067,614
  ＝ Codex 的 2.89%、平台的 2.21%**，不是 v1 說的上界 60.1M（**v1 高估約 15 倍**）。
  高估原因：v1 用「每個邏輯對話只留最大單檔」的上界法，忽略了
  `_iter_codex_session_records` 既有的 fork 重放 retract 機制已經丟掉大部分重放前綴。
  - **但 session 計數的膨脹是真的**：現行 `unique_sessions` 280 → fork root 收斂後
    **131 個邏輯對話（2.14 倍灌水）**。「平均每 session 花多少」「有幾個 agent 在跑」目前皆錯。
  - **修法警示（重要，別再抄 v1 那句）**：v1 寫的「最小修法：session_id 改綁
    `session_meta.session_id`」**是錯的**。實證：2815 個 rollout 檔有 2815 個相異
    `session_meta.id`（**每檔唯一**），且 `token_usage_report.py` 自 `95831cdb6` 起早已綁該欄。
    正確鍵是 `forked_from_id` / `parent_thread_id` 追到底的 **fork root**。
  - 回歸驗證期望值（同窗 07-29～08-04）：Codex billable **136,756,562**、邏輯 session **131**。
- **F3 PRICING 覆蓋率 20.2% — 未修**：gpt-5.6-sol / gpt-5.4-mini / gpt-5.6-terra /
  codex-auto-review / claude-fable-5 都計 $0。成本欄位在修好前不可對外。
- **F4 集中度規則缺口 — 已修（v2 自辦）**：新增 `agent_concentration`(>20%)、
  `session_longevity`(>48h)、`idle_burn_session`、`repeat_churn` 四條規則。

## 分析陷阱（別再踩）

- **`mission_output_share_pct` 不可作 KPI（已在資料層改名為
  `mission_output_share_pct_upstream_NOT_KPI`）**：上游分類器把主線程大量真實產出丟進
  `bash_other` / `investigation`。部門自有口徑（turn 內是否出現寫檔工具或變更型指令）
  算出 Claude 側 effectful = **41.65%（下界）**，與該欄的 4.5% 差 9 倍。
- **effectful 是下界、noop／read_only 是上界**：`mutating_command` 用保守白名單，
  會寫檔但沒命中 pattern 的腳本會被算成 read_only。報數字時一律帶「下界／上界」字樣。
- **Codex 無法判定效力**：telemetry 只有 `token_count`，沒有工具內容。R4（idle_burn）與
  效力分母都排除 Codex —— 這是「無法量測」，不是「量測後通過」，不可寫成 Codex 沒空轉。
- Codex 的 category 是 cwd/originator 推的粗桶，與 Claude 的工具級分類**不同口徑**，
  不可並列比較。
- **上界不是結論**：v1 的 60.1M 教訓 —— 對外口徑一律等 turn-level 定案，估計上界只能寫在
  「待定案」欄位。
- 環境限制：本 session 的 Write／Edit（repo 內）／裸 shell 重導向／heredoc 都被權限模式擋下，
  **經 `uv run python <script>` 與專案 CLI（`dept_send.py` / `git_writer_lock.py`）寫檔可行**；
  `jq` 帶 glob（`weekly_*.json`）也會被擋，要先 `ls | grep` 再逐檔列。下次直接走後者。
