# Handoff — 2026-05-26 05:50:04 台灣時間

**角色**：VolPred 自主運營經理（用戶 = 老闆 / report-only / full autonomy）

> 此檔由 `scripts/generate_handoff.py` 每小時 :50 自動產生。手寫補充請放本檔末段「## 候補 / 手動補充」並標時間戳。

## 1. 任務池快照（`storage/next_tasks.json`）

- **總數**：580
  - pending: 30
  - pending_main_thread: 31
  - succeeded: 468
  - failed: 2
  - blocked: 4
  - blocked_on_user: 1

**type 分佈（top 6）**：
  - daily_article: 280
  - paper_review: 132
  - experiment: 84
  - platform_ops: 32
  - paper_body: 24
  - paper_decision: 14

## 2. 已 claim / in_progress 任務

- (無 — 任務池閒置)

## 3. Email 回信任務（**優先處理**）

- (無未處理回信)

_Gmail 最後 poll：2026-05-25T21:45:16.238156+00:00_

## 4. Pending 任務 top 8（依 priority asc）

- `K1268b_gdelt_with_paid_intraday` P3 [experiment] K1268b: GDELT 5-min vs SPY 5-min RV — re-run with backtest-grade intraday data
- `K1310` P3 [experiment] K1310: I4: VIX futures roll yield 策略 — contango 環境下的 roll yield 收割 vs 尾部風險保護 ⚠️ **BLOCKED: 需要 VIX fu
- `K1383` P3 [experiment] K1383: PatchTST-lite vs HAR-RV — MDPI 2025
- `K1385` P3 [experiment] K1385: Sentiment-Augmented GARCH-LSTM — Computational Economics 2025
- `K1388` P3 [experiment] K1388: HAR-GNN（Graph Neural Network）— ScienceDirect 2024
- `K1389` P3 [experiment] K1389: KAN for VIX Forecasting — Expert Systems with Applications 2025
- `Paper1_D3_kupiec_rounding_precision` P3 [paper_body] Paper 1 MEDIUM: Kupiec p 1-decimal rounding — 建議 paper 改 2-decimal
- `Paper1_KB_only_tables_10_11_12_C3_footnote` P3 [paper_review] Paper 1: Tables 10/11/12/C3 6 KB-only 數字加 'pre-K era, KB source' footnote

## 5. 進行中 agent / worktree

- **slot 占用**：0 / 4
- (slot 全空)

## 6. 最近 24h 完成（top 5）

- `K_NEW_B_paper9_har_benchmark` P3 [experiment] K_NEW_B: Paper 9 加入 HAR-RV / HAR-RV-VIX 基準至 Table 2 horse race — claimed_by=hourly-05
- `K_NEW_A_paper9_covid_subperiod` P3 [experiment] K_NEW_A: Paper 9 leave-COVID-out DM test — 驗證主要結果非 COVID 驅動 — claimed_by=hourly-05
- `gen_article_k182` P4 [daily_article] K182: write general-audience article (auto-discovered, verdict={'fomc_vol_effect': True, 'vix_uncert — claimed_by=codex-cli
- `paper_vt_trend_following_self_contained` P2 [paper_review] (no title) — claimed_by=hourly-04
- `gen_article_k181` P4 [daily_article] K181: write general-audience article (auto-discovered, verdict=Mixed results — partial corr sig in 4 — claimed_by=codex-cli

## 7. Dashboard 訊號

- (dashboard_latest.json present but no critical/warn keys recognized)

## 8. 最近 work_log（5 筆，新→舊）

- `2026-05-25T21:16` [experiment] K_NEW_A_paper9_covid_subperiod+K_NEW_B_paper9_har_benchmark
- `2026-05-26T04:10` [paper_review] paper_vt_trend_following_self_contained
- `2026-05-26T03:22` [paper_review] paper_taiwan_vt_self_contained
- `2026-05-26T02:13` [platform_ops] hourly_02_sync_k1391_k1392_state
- `2026-05-26T01:22` [daily_article] gen_article_k769

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
