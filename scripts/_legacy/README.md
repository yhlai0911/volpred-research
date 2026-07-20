# scripts/_legacy — 已退役的一次性 / 歷史腳本

這裡的檔案**確定不在 live 路徑上**：不被任何 cron / launchd / config / skill / CLI /
pipeline / test 引用。保留原檔（而非只留 git history）是為了 provenance 與可追溯 —
研究產物一件都不能漏（memory `feedback_no_research_artifact_loss`）。

- canonical 文章發佈路徑：`scripts/publish_draft.py` + feed-publisher skill
- 制度建立：2026-07-01（scripts 稽核 + 主線程遷移）
- 歸檔判準：引用反查（config/.claude/src/scripts/tests/.github/repo-root/docs
  workflow-index/launchd plist/crontab/~/.volpred/bin）零命中，且屬一次性研究 /
  backfill / 事件性產物。長駐流程不進此目錄。

## 2026-07-01 首批（文章一次性腳本 + 早期 helper，21 支）

`agent_monitor.py`、`append_k667_k668_articles.py`、`backfill_adaptive_tier.py`、
`backfill_audience.py`、`backfill_emdash.py`、`backfill_paper_trading.py`、
`gen_articles_20260328.py`、`gen_k620_v2_charts.py`、`gen_k620_v2_lazypack.py`、
`gen_k667_k668_charts.py`、`model_selector.py`、`populate_strategy_badges.py`、
`save_k848_article.py`、`send_email_attachment.py`、`tsmc_concentration_test.py`、
`write_3_articles_20260327.py`、`write_articles_20260327.py`、
`write_articles_k551_k552.py`、`write_articles_k733_k747.py`、
`write_k604_k597_k598_articles.py`、`write_nfp_articles.py`
— 一次性文章生成 / 早期 backfill；輸出已在 `storage/reports/`。

## 2026-07-20 WS-E2 批（refactor_plan_ops_master_2026_07 §WS-E）

引用反查方法：全 repo 掃描（含 repo-root conftest.py / crontab / launchd plist /
`~/.volpred/bin`）+ 死碼互引 fixpoint closure；每支逐一複核。同批 E1 已直接
`git rm` 13 支純 ops 死碼（drone_ep* 8 支、fix_cjk_charts.py、launchd_release_pool.sh、
research_helper.py、topic_cluster_audit.py、render_cost_csv_to_pdf.py），git history 留底。

### 研究一次性腳本（輸出已固化於 experiments/ / paper/ / storage/）

| 檔案 | Provenance |
|---|---|
| `article_k1718_charts.py` | K1718 文章圖表；數字綁 `experiments/k1718/k1718_results.json` |
| `article_k514_charts.py` | K514 FOMC VIX-surprise 文章圖表；見 `experiments/k514/` |
| `draft_k1681_figures.py` | K1681 讀者版圖表；數字綁 `experiments/k1681/k1681_results.json` |
| `backtest_3yr_us.py` | SPY 系策略 3 年回測（2023-2026）；`backtest_3yr_final.py` 為留任版（add-strategy-guide 引用） |
| `btc_allocation_deep_dive.py` | K64 後續：small BTC allocation deep dive |
| `compare_data.py` | paper/taiwan-vt pinned CSV vs yfinance 一次性資料核對 |
| `complexity_ceiling_score.py` | CCS（Complexity Ceiling Score）三維模型改善量化分析 |
| `cross_asset_multistep_gjr.py` | GJR-GARCH 多步預測跨資產驗證 |
| `experiment_evt_var.py` | EVT-VaR（POT）尾部風險實驗 |
| `experiment_fhs_var_targeting.py` | FHS-VaR targeting 實驗 |
| `experiment_garch_midas.py` | GARCH-MIDAS 宏觀變數日頻波動預測實驗 |
| `experiment_interest_rate_vt.py` | 利率 regime 下 VT 表現實驗 |
| `experiment_portfolio_var.py` | Portfolio VaR aggregation 實驗 v2 |
| `experiment_rebalancing_boundary.py` | 12/VIX 策略再平衡邊界實驗 |
| `experiment_regime_switching_vt.py` | Markov regime-switching VT 實驗 |
| `experiment_risk_budgeting.py` | GJR-GARCH 動態 risk budgeting 對比實驗 |
| `experiment_sector_vt_map.py` | Sector-level VT 有效性地圖 |
| `experiment_tail_dep_var.py` | 尾部相依對多資產 VT 組合 VaR 影響 |
| `experiment_tail_dep_var_full.py` | 同上補充：全樣本 VaR 對比 + 壓力測試 |
| `experiment_vix_seasonality.py` | VIX 季節性 / 週期型態分析 |
| `experiment_vol_spillover.py` | 跨資產波動外溢實驗 |
| `garch_lstm_hybrid.py` | GARCH-LSTM hybrid 波動預測實驗 |
| `k1511_bootstrap.py` | K1511 block bootstrap（1000 iter）；`experiments/k1511/README.md` 引用原路徑 `scripts/k1511_bootstrap.py` |
| `kurtosis_corr_asymmetry.py` | Kurtosis collapse vs correlation asymmetry 分析 |
| `master_var_panel.py` | Master VaR panel — 全 VaR 方法統一比較框架 |
| `paper3_fixes.py` | K79：VIX threshold sensitivity + dual mechanism（paper vt-trend-following 引用其輸出 `paper/vt-trend-following/experiments/paper3_fixes.json`，JSON 已固化於 paper 資料夾） |
| `phase_u1_panel_garch.py` | Phase U1：panel vs single-asset GARCH |
| `qa_taiwan_5yr_outlook.py` | 會員問答：台灣五年展望分析 |
| `taiwan_comprehensive_analysis.py` | 台股金融 + 情緒指標綜合分析 |
| `var_backtest_trinity.py` | VaR 回測三件套：Kupiec + Christoffersen + DQ |
| `var_report.py` | Basel III VaR compliance 報告產生器 |
| `vol_return_prediction.py` | 波動 → 報酬預測研究 |
| `vt_trend_decomposition.py` | VT alpha trend-following 分解 |
| `vt_tsmom_final_n22.py` | K55：VT-TSMOM N=22 跨資產面板 — paper vt-trend-following Tables 1&2 原始碼；輸出 JSON 固化於 `paper/vt-trend-following/experiments/vt_tsmom_final_n22.json` 與 `storage/experiments/` |
| `vvix_skew_analysis.py` | VVIX / SKEW / VIX term structure 分析 |

### 一次性 backfill / 資料事件修復（canonical 資料已修復完畢）

| 檔案 | Provenance |
|---|---|
| `backfill_lazypack_sections.py` | 既有文章補懶人包 PNG 一次性 backfill |
| `backfill_new_strategies.py` | vix_cond_leverage / taiwan_hybrid_leverage 3 年 paper trading 補歷史 |
| `backfill_strategy_gate_receipts.py` | active 策略 grandfathered activation receipts 補建 |
| `detect_price_split_breaks.py` | 0050 分割斷點事件：price_cache split-break 偵測（`repoint_snapshot_from_db.py` import 它，兩支同批歸檔，於本目錄內互相可 import） |
| `fix_0050_split_break.py` | 0050.TW 2014-01-02 分割斷點修復（governance: `docs/governance/2026-07/foreign_incident_path_adjudication.md`） |
| `repoint_snapshot_from_db.py` | pinned snapshot CSV 重新指向修復後 price_cache |

### 已被取代的流程工具（superseded）

| 檔案 | Provenance |
|---|---|
| `gen_brand_assets.py` | VolPred 品牌視覺資產生成器（可復現）；資產已產出進 frontend |
| `independent_paper_review.sh` | 2026-05-21 跨模型論文獨立審查（Codex+agy）；已被 paper-review-cycle / journal-review skill 流程取代 |
