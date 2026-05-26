# Handoff — 2026-05-26 14:11:02 台灣時間

**角色**：VolPred 自主運營經理（用戶 = 老闆 / report-only / full autonomy）

> 此檔由 `scripts/generate_handoff.py` 每小時 :50 自動產生。手寫補充請放本檔末段「## 候補 / 手動補充」並標時間戳。

## 1. 任務池快照（`storage/next_tasks.json`）

- **總數**：582
  - pending: 21
  - pending_main_thread: 28
  - succeeded: 481
  - failed: 3
  - blocked: 4
  - blocked_on_user: 1

**type 分佈（top 6）**：
  - daily_article: 280
  - paper_review: 132
  - experiment: 86
  - platform_ops: 32
  - paper_body: 24
  - paper_decision: 14

## 2. 已 claim / in_progress 任務

- (無 — 任務池閒置)

## 3. Email 回信任務（**優先處理**）

- (無未處理回信)

_Gmail 最後 poll：2026-05-26T06:00:28.788809+00:00_

## 4. Pending 任務 top 8（依 priority asc）

- `K1268b_gdelt_with_paid_intraday` P3 [experiment] K1268b: GDELT 5-min vs SPY 5-min RV — re-run with backtest-grade intraday data
- `K1310` P3 [experiment] K1310: I4: VIX futures roll yield 策略 — contango 環境下的 roll yield 收割 vs 尾部風險保護 ⚠️ **BLOCKED: 需要 VIX fu
- `K1383` P3 [experiment] K1383: PatchTST-lite vs HAR-RV — MDPI 2025
- `K1385` P3 [experiment] K1385: Sentiment-Augmented GARCH-LSTM — Computational Economics 2025
- `K1388` P3 [experiment] K1388: HAR-GNN（Graph Neural Network）— ScienceDirect 2024
- `K1389` P3 [experiment] K1389: KAN for VIX Forecasting — Expert Systems with Applications 2025
- `Paper2_G20_T4_IS_Sharpe_errata` P3 [paper_review] Paper 2 G20 T4: IS Sharpe 0.732 vs K1180 0.413 (44% gap) — main-thread errata
- `Paper2_Table4_documentation_errata` P3 [paper_review] Paper 2: Table 4 / Methodology / Data section 補說明 (K1176 發現)

## 5. 進行中 agent / worktree

- **slot 占用**：1 / 4
- worktrees:
  - `agent-af9b396e7976b970b`

## 6. 最近 24h 完成（top 5）

- `gen_article_k551` P4 [daily_article] K551: write general-audience article (auto-discovered, verdict={'checks': {'harvey_dm_t3': True, 'ha — claimed_by=codex-cli
- `gen_article_k510` P4 [daily_article] K510: write general-audience article (auto-discovered, verdict=NEGATIVE — Volume-GARCH significantly — claimed_by=hourly-13
- `gen_article_k524` P4 [daily_article] K524: write general-audience article (auto-discovered, verdict={'SPY': 'beats_baseline', 'SPY_GLD':  — claimed_by=codex-cli
- `gen_article_k487` P4 [daily_article] K487: write general-audience article (auto-discovered, verdict=EQUITY-SPECIFIC) — claimed_by=hourly-12
- `K1322` P3 [experiment] K1322: 台灣 5-min 數據 HAR-RV（0050.TW 47 天，ETA 2026 Q2）

## 7. Dashboard 訊號

- overall_status=ok (breaches=0, critical=0, generated=2026-05-26T06:00:44Z)

## 8. 最近 work_log（5 筆，新→舊）

- `2026-05-26T13:14` [daily_article] gen_article_k510
- `2026-05-26T11:47` [experiment] K1322
- `2026-05-26T10:15` [paper_review] Paper2_D3D4D5_gamma_VaR_days
- `2026-05-26T08:07` [governance] hourly_08_cleanup_stale_k1401_todo
- `2026-05-26T06:20` [daily_article] gen_article_k786

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
