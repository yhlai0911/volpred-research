Hourly dispatch trigger (OS cron). 規則 (token-conserving split architecture):

PHASE A — 檢查 compute queue 有無 completed 待 followup:
1. 跑 `uv run python scripts/compute_queue.py list --completed-pending-followup --json`
2. 若有 entries → 優先處理: 對最舊一條讀 result_artifact 路徑 + agent claude_followup.brief 文字，派 Claude interpretation agent 解讀（~25K tokens, light），不再做 compute。派完跑 `uv run python scripts/compute_queue.py mark-followup-dispatched --id <id> --next-task-id <task_id>` 防重派。本小時派工結束。
3. 若無待 followup → 進 PHASE B。

PHASE B — 派新工:

1. 跑 `uv run python scripts/continue_task_dispatch.py --report` 看 dispatch state + agentable candidates。
2. 多樣性檢查: `jq '[.[-5:] | .[] | .task_type]' storage/work_log.json` — 從 10 type 池選不在 last-3 的 type（experiment / paper_decision / paper_body / paper_review / event_article / daily_article / member_qa / strategy_lifecycle / platform_ops / governance）。
3. 優先序（CLAUDE.md 關 2 diversity 為硬規）:
   a. 若 last-3 work_log 已有 ≥2 paper_review/paper_body/paper_decision → 禁挑 paper_*，必 rotate 到其他 type。違反 = 整盤 diversity 崩。
   b. 否則考量 paper R1 backlog (Paper 2 還剩 3 SEVERE) + M3 monetization weight。
   c. 每天至少 1 次 experiment 類（生新 research direction），避免長期 maintenance 化 + 30 天無新發現累積。新 experiment 必 grounded in research_program.md Open Question OR 文獻 last 7 天 + monetization angle。
   d. 從 10 type 池選不在 last-3 的 type — 嚴格 enforce，不再 audit 鎖死 paper R1。
4. Override: reactive K-experiment autogen brief（K1310-K1330 GARCH-Neural / HAR-GNN / Transformer / KAN / Conformal 等 ML novel-method NULL 4 連後 diversity decline）→ skip 改派非 ML K 或 paper_review。
5. 分流決策（token 節省）:
   - heavy compute (GARCH MLE / Bootstrap / data fetch / 全期 backtest / pooled-MLE multistart) → 改 `uv run python scripts/compute_queue.py enqueue --script <path> --title <T> --result-artifact <path> --followup-brief 'brief' --followup-task-type paper_review --timeout 3600`。Compute worker cron */15 min 接手；下次 hourly 自動派 interpretation agent（省 60-70% tokens）。注意: 腳本必須完整已寫才能 enqueue。
   - decision / writing / narrative → 派 Claude agent 正常流程（worktree for experiments；main repo for articles/paper body）。
6. Brief 含 task title/description + skill 規範 + lookahead + Codex 審核要求 + Mission sanity check。
7. 派完 end summary 格式（per memory feedback_task_end_summary_format）: 結束時間 / 總時間 / 本次 token / 完成項目 / 本週 Max 20x quota % (`uv run python scripts/weekly_quota_estimate.py`) / 下次任務時間。
8. 若 last-3 涵蓋所有 candidates 的 type → 派沒做過的 type，必要時主動生 brief / 文章 / compute job。沒事做永不可接受。
9. 嚴禁: force push, --no-verify, 寫 knowledge.json from agent (K1259), 假數字。研究誠實 > 一切。
