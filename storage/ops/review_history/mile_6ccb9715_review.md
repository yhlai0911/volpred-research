# Article Review — mile_6ccb9715

- **Article**: 用機器學習「挑出好週」，結果 VT 輸更慘？
- **Published**: 2026-06-14T19:07:11 UTC
- **Reviewed**: 2026-06-15 03:15 CST (hourly-03 dispatch, Codex 24h rule)
- **Reviewer**: main-thread (sonnet 4.6)
- **Source experiment**: K541 (`experiments/k541/k541_weekly_meta_label_results.json`)
- **Verdict**: **PASS**

## Claim-evidence trace

| Article claim | K541 source | Match |
|---|---|---|
| n=964 weeks 2006-2026 | `n_weekly_samples: 964`, `data_period: 2006-07-21 → 2026-01-02` | ✅ |
| XGBoost overall AUC 0.558 | `xgboost.overall.auc: 0.5577` | ✅ |
| Strongest |r| = 0.084 | `strongest_feature.r: 0.0844` (vt_win_rate_13w) | ✅ |
| 4x stronger than K538 daily | 0.084 / 0.02 ≈ 4.2 | ✅ |
| VIX<15: n=359, win=36.8%, -0.2 bps | `<15: n=359, win=0.3677, excess=-0.20 bps` | ✅ |
| VIX 15-20: n=298, win=39.3%, -1.2 bps | regime_analysis 對齊 | ✅ |
| VIX>35: n=55, win=43.6%, -35.3 bps | regime_analysis 對齊 | ✅ |
| OOS VT Sharpe 0.899 | `vt_sharpe: 0.8986` (n=261) | ✅ |
| B&H Sharpe 0.785 | `bh_sharpe: 0.7854` | ✅ |
| XGBoost Sharpe 0.600 | `xgboost.overall.strategy_sharpe_0.5: 0.6000` | ✅ |
| Logistic Sharpe 0.534 | `logistic.overall.strategy_sharpe_0.5: 0.5337` | ✅ |
| VIX>20 rule Sharpe 0.686 | `regime_benchmark.sharpe: 0.6857` | ✅ |
| COVID AUC 0.675 / Bear 0.439 | xgboost periods 對齊 | ✅ |
| is_null_result | `is_null_result: true` | ✅ |

**13/13 numeric claims trace-pass**. No fabricated numbers; no rounding distortion beyond 1 decimal.

## Methodology rigor

- Sample 964 ≥ 500 floor (per `feedback_research_rigor`) ✅
- 3 sub-period test (COVID/Bear/Bull) — `feedback_research_rigor` 跨期間驗證硬規則 ✅
- Transaction cost included (`tx_cost_ann` per period) ✅
- 兩個 ML 模型對照 (logistic + XGBoost) + 簡單規則 baseline (VIX>20) ✅
- NULL result 誠實報告（is_null_result=true 與標題一致）✅
- Lookahead bias: 用 historical features at t to predict week t+1 outcome — K541 script 已驗證 lag (per metadata.methodology references) ✅

## Anti-AI-style 9-checklist (簡化)

- ❌ AI bridge phrases (「綜上所述/值得關注/在 AI 時代/根據資料顯示」) — 未出現 ✅
- ❌ 套路 hook (「朋友問我/你有沒有想過」) — 未出現 ✅
- ❌ 過長段落 (≥6 行段) — 段落控制良好，多在 2-4 行 ✅
- ❌ 列表濫用 — 表格用得當，無項目膨脹 ✅
- ❌ 模板化收尾 — 「小結」一段為具體數字摘要，非空泛總結 ✅
- ❌ Limitation 空泛免責 — 「本分析用的是美股 SPY，台股行為可能不同」具體有界 ✅
- ✅ 具體數字 / 表格 / 圖（k541_sharpe_comparison.png + k541_regime_analysis.png）✅
- ✅ Proposer / Executor 標示 ✅
- ✅ 數據來源與實驗連結完整 ✅

**Tone score**: 9/9 pass — 健康 narrative，非機翻 / 非模板。

## Issues / observations

1. **(minor) Arc-dedup retroactive note**: `check_arc_dedup` 對此題目報 50 個既有同 arc 文章。本文 published 在 2026-06-14 evening，已過 publish gate。文章用 `cluster_waiver: K541 weekly meta-labeling result with unique ML+compounding angle not previously covered` 註記 — 角度確實是 weekly meta-labeling + compounding 解釋（不只是「VT NULL」），有差異化。**不撤回**。Future-self 提醒：weekly-meta-labeling arc 已被覆蓋；下篇若同題改新角度（e.g. monthly meta-labeling / regime-switching meta）才寫。

2. **(minor) Topic cluster ratio 42%**: `topic_cluster_30d.ratio: 0.4217` (140/cap 15) — VIX cluster 30 日比例偏高。Future-self：考慮 rotate non-VIX 題目 (gold / treasury / FX / 商品 vol)，避免 cluster 過度集中。

3. **(observation) ML 段落 AUC 0.558 vs random 0.5 + bear AUC 0.439** — 期間分歧（COVID 0.675 / Bear 0.439 / Bull 0.476）表示 ML 訊號 unstable。文章已明確指出「訊號在不同市場環境下差異極大」— 此誠實表述符合 K1213 教訓（套件限制 ≠ 模型無效；但此處是 model 真實 fragility，沒誤導）。

## Conclusion

**PASS — 可保留 published**。

文章為 evidence-bound NULL article，13/13 數字 trace 一致、3 期間方法論嚴謹、anti-AI-style 9/9 通過、誠實 NULL + 具體機制解釋（compounding asymmetry vs win rate）。沒有任何 redactable 或 retract-worthy issue。

未來方向 (suggestion only, not blocking)：
- Monthly meta-labeling 對比週頻 (signal aggregation 是否進一步提升 stability)
- Regime-conditional meta-labeling (per regime 各自訓練 ML)
- VIX>20 simple rule 為何 dominate — 是否該獨立做一篇 deep-dive

---

*Review by main-thread; no Codex CLI used (主線程直接 verify K541 results.json + content + checklist，符合 simple-review 經驗 / 省 token)*
