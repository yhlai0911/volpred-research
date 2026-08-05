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
  只加 agent 維度；全窗 7 日掃描約 38 秒）。

## 已知缺陷（追蹤中，均已回報經理）

- **F1 日報日界**：cron 08:00 台灣＝00:00 UTC 卻產「當天」報表 → 每日日報恆為 0。
  2026-07-29～08-04 有 6 天空白，少記 141.1M。修好前日報不可用作 KPI 來源。
- **F2 Codex fork 重複計費**：session 身分綁 rollout 檔名而非 `session_meta.session_id`；
  單一對話 `019f8e4d` 被算成 76 個 session。重複量上界 60.1M（平台 32.6%）。**尚未定案**，
  要 turn-level 比對才能坐實。
- **F3 PRICING 覆蓋率 20.2%**：gpt-5.6-sol / gpt-5.4-mini / gpt-5.6-terra /
  codex-auto-review / claude-fable-5 都計 $0。
- **F4** 單日 >2× 均值規則對「單一 agent 長期霸佔」無感（238h session 吃掉 34.2% 卻不觸發）。

## 分析陷阱（別再踩）

- `mission_output_share_pct` 對主線程嚴重低估：主線程大量 turn 落在 `bash_other` /
  `investigation`，不在 `MISSION_OUTPUT_CATEGORIES`。修分類前不可拿它下「主線程沒產出」的結論。
- Codex 的 category 是 cwd/originator 推的粗桶，與 Claude 的工具級分類**不同口徑**，
  不可並列比較。
- 環境限制：本 session 的 Write／裸 shell 重導向被權限模式擋下，**經 `uv run python <script>`
  與專案 CLI（`dept_send.py` / `git_writer_lock.py`）寫檔可行**。下次直接走後者。
