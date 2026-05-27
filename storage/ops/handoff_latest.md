# Handoff — 2026-05-28 02:50:04 台灣時間

**角色**：VolPred 自主運營經理（用戶 = 老闆 / report-only / full autonomy）

> 此檔由 `scripts/generate_handoff.py` 每小時 :50 自動產生。手寫補充請放本檔末段「## 候補 / 手動補充」並標時間戳。

## 1. 任務池快照（`storage/next_tasks.json`）

- **總數**：639
  - pending: 4
  - pending_main_thread: 21
  - succeeded: 538
  - failed: 11
  - blocked: 20
  - blocked_on_user: 1

**type 分佈（top 6）**：
  - daily_article: 282
  - paper_review: 142
  - experiment: 87
  - platform_ops: 53
  - paper_body: 24
  - email_reply: 18

## 2. 已 claim / in_progress 任務

- (無 — 任務池閒置)

## 3. Email 回信任務（**優先處理**）

- (無未處理回信)

_Gmail 最後 poll：2026-05-27T18:45:19.998354+00:00_

## 4. Pending 任務 top 8（依 priority asc）

- `event_article_cpi_us_2026-06-11_tminus2` P1 [event_article] [event_article] Event article: CPI_US 2026-06-11 T-2
- `event_article_cpi_us_2026-06-11_tplus0` P1 [event_article] [event_article] Event article: CPI_US 2026-06-11 T+0
- `platform_ops_refactor_hourly_dispatch_worker_daemon` P2 [platform_ops] [platform_ops] hourly-dispatch 重構 — worker daemon + queue 取代 LaunchAgent + claude CLI subprocess (3-
- `Paper2_Table4_documentation_errata` P3 [paper_review] Paper 2: Table 4 / Methodology / Data section 補說明 (K1176 發現)
- `Paper4_body_integration_9_new_experiments` P3 [paper_decision] Paper 4 body stale: 9 新實驗未整合 main_v2.tex (integration_plan_v2 未套用)
- `Paper6_DIV2_0050TW_OOS_date_errata` P3 [paper_review] Paper 6: 0050.TW OOS 起始 2019/12 vs K886 2021-01-08 (差 13 月)
- `Paper6_DIV3_SPY_VaR_violation_rate` P3 [paper_review] Paper 6: SPY VaR VR=0.93%, Kupiec p=0.77 無對應 source
- `Paper9_D5_0050TW_t144_source` P3 [paper_review] Paper 9: 0050.TW DM t=1.44 setting 不明

## 5. 進行中 agent / worktree

- **slot 占用**：0 / 4
- (slot 全空)

## 6. 最近 24h 完成（top 5）

- `paper_review_mile_8ae0e7d8` P4 [paper_review] Paper review (Codex 24h-rule): 300 個實驗之後仍未解的 24 個問題——研究前沿的誠實清單 — claimed_by=hourly-02
- `paper_review_mile_d0d66405` P4 [paper_review] Paper review (Codex 24h-rule): Range-Based 估計子作為 GARCH Proxy：哪一個最準？ — claimed_by=codex-cli
- `paper_review_followup_K562_reproduce_lag_fix` P2 [experiment] K562 reproduce: re-apply 2026-05-06 lag-fix patch + commit results (mile_91af7c48 backing) — claimed_by=codex-cli
- `paper_review_mile_91af7c48` P4 [paper_review] Paper review (Codex 24h-rule): 從 Sharpe 2.16 到輸基準：一場 lookahead 的攔截實錄 — claimed_by=hourly-22
- `platform_ops_frontend_cluster_deprioritization` P2 [platform_ops] [platform_ops] 前端 feed listing cluster-aware sort 降權（歷史 VIX 52% 解套） — claimed_by=codex-cli

## 7. Dashboard 訊號

- overall_status=warn (breaches=1, critical=0, generated=2026-05-27T18:30:05Z)
- WARN: section=health_alerts_unhandled :: 1 warn/critical alerts last 6h (read + act per .claude/rules/alert.md)

## 8. 最近 work_log（5 筆，新→舊）

- `2026-05-27T18:14` [paper_review] paper_review_mile_8ae0e7d8
- `2026-05-28T01:13` [platform_ops] hourly_dispatch supervisor refactor — Deliverable 2/8 scaffold (scripts/dispatch
- `2026-05-28T00:09` [platform_ops] hourly_dispatch_2026_05_28_0007 reader_facing_refill manual fire + crontab insta
- `2026-05-27T23:15` [paper_review] k560-lag-fix-mainthread-verify-20260527
- `2026-05-27T22:16` [paper_review] paper_review_mile_91af7c48

## 9. 接續提示詞（hourly dispatch / 互動 session 共用）

```
讀 storage/ops/handoff_latest.md 後依以下優先序選工：

優先序 (HARD)：
  1. Section 3 Email reply 任務（task_type=email_reply）— 若有 pending，立即 claim + 處理（讀 description 的「用戶回信內容」+「原始助理寄出內容」，依用戶指示回應 / 修正 / 派工 / 寄回信）
  2. Section 7 Dashboard CRITICAL — 立即 triage
  3. Section 4 Pending 任務 top 8 — 依 priority asc + work_log diversity（last-3 task_type rotate）

Claim 流程（避免雙 session 撞題）：
  uv run python scripts/task_pool_claim.py claim --id <task_id> --owner <hourly|interactive|agent-name>
  uv run python scripts/task_pool_claim.py start --id <task_id>
  ... 執行 ...
  uv run python scripts/task_pool_claim.py complete --id <task_id> --status succeeded --result '...摘要...'

完整完成原則：派 agent 後 wait 完成、驗證、寫 knowledge.json / work_log、commit。50min cap。Heavy compute 走 compute_queue。
```

---

## 候補 / 手動補充

（此區由人工 / 互動 session 編輯；hourly auto-regen 會保留此區以下內容若手動加在 `<!-- KEEP -->` 區段內。預設覆寫所有自動章節。）
