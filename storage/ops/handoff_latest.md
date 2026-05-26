# Handoff — 2026-05-26 19:50:06 台灣時間

**角色**：VolPred 自主運營經理（用戶 = 老闆 / report-only / full autonomy）

> 此檔由 `scripts/generate_handoff.py` 每小時 :50 自動產生。手寫補充請放本檔末段「## 候補 / 手動補充」並標時間戳。

## 1. 任務池快照（`storage/next_tasks.json`）

- **總數**：597
  - pending: 24
  - pending_main_thread: 26
  - succeeded: 495
  - failed: 3
  - blocked: 4
  - blocked_on_user: 1

**type 分佈（top 6）**：
  - daily_article: 280
  - paper_review: 132
  - experiment: 86
  - platform_ops: 38
  - paper_body: 24
  - paper_decision: 14

## 2. 已 claim / in_progress 任務

- (無 — 任務池閒置)

## 3. Email 回信任務（**優先處理**）

- (無未處理回信)

_Gmail 最後 poll：2026-05-26T11:45:24.659429+00:00_

## 4. Pending 任務 top 8（依 priority asc）

- `event_article_us_cpi_2026_06_13_preview` P1 [event_article] [event_article] US CPI 2026-06-13 預覽（T-7 / T-2 / T+0 三篇之 T-7）— VolPred vol regime + VIX term structu
- `trending_repost_2026_05_26_etf_dividend_vol` P1 [trending_repost] [trending_repost] 5 月台股 ETF 配息潮 30 檔 — VolPred VT/risk-parity 角度看配息日 IV skew 與配置策略
- `trending_repost_2026_05_26_silicon_valley_layoffs_capex` P1 [trending_repost] [trending_repost] 8000 人換 GPU：矽谷大裁員 × $725B AI CapEx 經濟學悖論 — VolPred labor-displacement vol 角度
- `platform_ops_audience_misclassification_audit` P2 [platform_ops] [platform_ops] 既有 feed 41+ 篇 audience=general mis-classification audit + batch reclassify
- `platform_ops_question_research_host_cron_migration` P2 [platform_ops] [platform_ops] question_research 從 session_cron 搬到 host_crontab（解 member_qa 36 天 silent gap）
- `platform_ops_reader_facing_refill_cron` P2 [platform_ops] [platform_ops] 寫 cron_reader_facing_refill.sh + 加 host crontab，收斂 PHASE 0.5 prompt-level reader-faci
- `K1268b_gdelt_with_paid_intraday` P3 [experiment] K1268b: GDELT 5-min vs SPY 5-min RV — re-run with backtest-grade intraday data
- `K1310` P3 [experiment] K1310: I4: VIX futures roll yield 策略 — contango 環境下的 roll yield 收割 vs 尾部風險保護 ⚠️ **BLOCKED: 需要 VIX fu

## 5. 進行中 agent / worktree

- **slot 占用**：1 / 4
- worktrees:
  - `agent-af9b396e7976b970b`

## 6. 最近 24h 完成（top 5）

- `platform_ops_feed_publisher_audience_gate` P2 [platform_ops] [platform_ops] feed-publisher 加 audience classification gate（防新文章再 mis-tag general） — claimed_by=hourly-19
- `email-11750-53fa5c` P3 [email_reply] [email_reply] Re: [VolPred Alert][INFO] [VolPred Alert][INFO] [VolPred Alert][INFO] [VolPred A — claimed_by=hourly-19
- `platform_ops_dispatcher_type_rotation` P2 [platform_ops] [platform_ops] continue_task_dispatch.py 加 type-rotation sort weight（防 same-priority experiment 搶光 s — claimed_by=codex-cli
- `member_qa_44b3cfcd_import_cars` P2 [member_qa] [member_qa] 會員 yaoxk1431 提問：台灣進口車比例與經濟變遷 + 個股推薦 2000 字 + 圖表
- `email-11748-7b1f24` P3 [email_reply] [email_reply] Re: [VolPred Alert][INFO] [VolPred Alert][INFO] [VolPred Alert][WARN] Member Q&A — claimed_by=hourly-18

## 7. Dashboard 訊號

- overall_status=warn (breaches=1, critical=0, generated=2026-05-26T11:30:10Z)
- WARN: section=health_alerts_unhandled :: 2 warn/critical alerts last 6h (read + act per .claude/rules/alert.md)

## 8. 最近 work_log（5 筆，新→舊）

- `2026-05-26T19:20` [platform_ops] platform_ops_feed_publisher_audience_gate
- `2026-05-26T19:09` [email_reply] email-11750-53fa5c
- `2026-05-26T10:11` [email_reply] email-11748-7b1f24
- `2026-05-26T17:13` [member_qa] ?
- `2026-05-26T16:13` [paper_review] Paper2_G20_T4_IS_Sharpe_errata

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
