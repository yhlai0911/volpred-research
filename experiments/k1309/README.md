# K1309: HAR-PD (Path-Dependent HAR) — arXiv:2503.00851 replication

[提出: research_program.md L279 backlog item, autogen brief by Claude main-thread, 執行: worktree agent]

## Motivation

研究 portfolio 連續 4 個 NULL (K1300 forgetting-BMA / K1301 HAR-RS / K1303 HAR-CJ / K1306 SEC EDGAR text)。下一個 candidate 方法應有 differentiated mechanism。**HAR-PD (Path-Dependent)** 來自 arXiv:2503.00851 (2025-03 preprint)，提出 HAR 的 path-dependent extension — 不只用過去 RV 的 1d/5d/22d 平均，還用路徑特徵 (e.g. drawdown 振幅、cumulative range、time-since-peak) 作為 predictor。

差異於既有 HAR family:
- **HAR-RV**: 平均 RV at 1d/5d/22d 三層
- **HAR-RS** (K1301 NULL): asymmetric decomposition by sign
- **HAR-CJ** (K1303 NULL): jump-component decomposition
- **HAR-PD (本 K)**: path features (drawdown, range, persistence)

Hypothesis：path features 捕捉的是不同 frequency-domain 資訊（state-dependent regime 而非僅 magnitude），可能在 RV decomposition NULL trilogy 之外提供 marginal info。

## Hypothesis

- **H1 (primary)**: HAR-PD vs HAR-RV on SPY 5-min RV，DM-HLN |t| > 3 (Harvey gate)
- **H2 (secondary)**: 跨資產 generalizability — TX1 (TAIFEX), QQQ, GLD 也 |t| > 3
- **NULL outcome**: |t| < 3 on all 4 assets → 加入 NULL trilogy → 與 K1301/K1303/K868 packaged 成 "intraday RV path/decomposition NULL synthesis" paper appendix 或 member 文章

## Pre-execution literature fetch

**Required**: 在開始 implementation 前必先 fetch arXiv:2503.00851 abstract + section 3 (model spec) + section 5 (empirical results)，確認:
1. HAR-PD 的 path features 確切定義 (作者用哪些路徑統計量)
2. Lookback window for path features (通常 22d 或可調)
3. 作者 baseline assets + 用 DM-HLN 或其他 loss function
4. 作者報告的 in-sample / OOS gain magnitude (避免 too-good-to-be-true 比對)

WebSearch `arXiv:2503.00851 HAR path-dependent volatility` + WebFetch arxiv abstract URL。

## Design

| Item | Setting |
| --- | --- |
| Assets | SPY (primary), QQQ, GLD, TX1 (TAIFEX 5-min day session) |
| Sample | yfinance 5-min limit window (60d for US ETFs per K1268 cap) + TAIFEX 2017-2026 from cached parquet |
| Forecast horizon | h=1 day-ahead RV |
| Models | HAR-RV (baseline), HAR-PD (treatment, path features per arXiv) |
| Loss | MSE on RV; DM-HLN test with Harvey small-sample correction |
| OOS | 70/30 train/test split, time-ordered |
| Seed | 42 throughout |
| Path features | Per arXiv definition — minimum candidates: max-drawdown_{t-22:t}, max-range_{t-22:t}, time-since-peak_{t-22:t} |

## Lookahead discipline

- 嚴格 `RV_t.shift(1)` 為 predictor，target RV_t
- Path features 計算用 `t-22:t-1` window，不含當期 t
- 70/30 split 後 train/test 各自獨立 fit；test 用 train coefs 預測，不 refit

## Differentiation vs prior K

- K1301 HAR-RS NULL: decomp by sign — orthogonal
- K1303 HAR-CJ NULL: decomp by jump — orthogonal
- K868 day/night decomp NULL: by session — orthogonal
- K1309 HAR-PD: path-state features — **distinct mechanism**

## Success criterion

- H1 PASS: SPY DM-HLN |t| > 3 vs HAR-RV
- 任何 asset 對 HAR-RV 的 OOS R² 增益 > 5% 加成正向證據
- Multi-asset robustness: ≥2/4 assets PASS H1
- Codex review primary path required pre-knowledge-entry

## Anti-too-good safeguards

- **重要**: K1303 教訓 — US ETFs n_train=25 (60d yfinance limit) 對 7-param 模型嚴重 overfit (R²_oos < -7)。此 K 必須加 sample-size guard: `if n_train < 30 * n_params: flag UNTRUSTWORTHY`。SPY/QQQ/GLD 預期會被 demoted；**真正 gateable result 在 TX1 (2186 daily obs)**。
- 100x bootstrap CI 必跑 (seed=42)，rejecting hypothesis only if 95% CI 不含 0
- Multistart for any non-linear path feature optimization

## Mission 5 sanity

- M2 (research)：proceed novel HAR family experiment，誠實 report NULL or PASS
- M3 (paper)：if PASS — 可能 standalone paper or P4 vix-sufficiency boundary appendix
- M1 (article)：if NULL — synthesis 加入 NULL trilogy 成 1 篇深度文章 (premium tier potential)
- Mon-angle：PASS → 新策略可上架 (M4/strategy_lifecycle revenue) / NULL → premium content asset

## References (≥3 required)

- **arXiv:2503.00851** (primary source, must fetch in step 1)
- Corsi (2009 JFEC) HAR-RV canonical
- Barndorff-Nielsen & Shephard (2004 JoE) for RV asymptotic theory  
- K1301 / K1303 / K868 internal NULL refs

## Workflow

1. WebFetch arXiv:2503.00851 → 提取 path-feature 定義 + 作者 empirical setting
2. Implement HAR-PD in `experiments/k1309/k1309.py` with proper lag discipline + seed=42 + multistart
3. Run on 4 assets, write `k1309_results.json` with per-asset sample_trust_flag + DM-HLN t + p
4. If TX1 PASS: trigger H2 follow-up brief
5. If all NULL: write synthesis-ready summary in results.json with "joins NULL trilogy" note
6. Codex review primary path (post 2026-05-13 02:46 UTC quota reset); fallback per K1259 rules with clear reviewer_source labeling
7. NO knowledge.json write from worktree — main-thread + Codex PASS gates this
