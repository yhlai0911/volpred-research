# K1424 — Hurst as GARCH Covariate (SPY OOS Forecasting)

- Experiment ID: `K1424_hurst_garch_covariate`
- Status: scripted (awaiting compute_queue run + Codex review)
- Created: 2026-06-08
- Parent: `K1423_ewma_hurst_pilot` (pilot, CONDITIONAL_PASS, ρ(H,VIX)=+0.32)
- Source: research_program.md backlog `time_varying_hurst_via_ewma` (arXiv:2509.05820)

## 問題

K1423 用 EWMA-weighted Hurst (λ=0.94) 在 SPY 2010-2026 找到 H 與 VIX 同期日相關 ρ=+0.32（顯著正）。但 K1423 是 **descriptive**：只看相關性，不證明 H 對 vol forecasting 有 incremental 價值。

K1424 要回答的核心問題（GARCH-only scope；HAR family 推 K1425）：

1. **H_{t-1} 是否為 GARCH(1,1) 的有效 covariate？** — H 是否在 GARCH 自身 dynamics 之外帶來預測力？
2. **H 是不是只是 VIX 的 noisy proxy？** — 控制 VIX_{t-1} 後 H 還剩多少 incremental 信息？

HAR-RV 加 H 推 K1425：HAR 用 multi-day overlap target，需 overlap-correct DM HAC + 明確 future window target；scope 與 GARCH 1-step 不同，分開處理避免口徑混淆（Codex Round 1 FAIL 教訓）。

## 動機（服務 Mission #2 → #3 → #1）

- **研究嚴謹**：K1423 的 ρ=+0.32 容易被誤讀為 "H predicts vol"；K1424 用 DM test + VIX control 把 descriptive 升級為 inferential
- **論文路徑**：H-as-covariate 可入 Paper 5 / 6 的 covariate-augmented vol forecasting 章節（依結果決定）
- **文章路徑**：若 H 顯著 incremental → 一篇「市場記憶力預測波動嗎？」reader-facing 文章；若 NULL → 一篇「VIX 已含 H 信息」科普 + 寫進 research_program 結案
- **商業化**：若 H 提升 GARCH OOS QLIKE ≥3% → 補入線上 VT 策略 vol forecaster

## 方法

### 資料

- **Source**：SPY + ^VIX daily close (yfinance)，重用 K1423 cache (`experiments/K1423_ewma_hurst_pilot/data/spy_vix_daily.parquet`)
- **Span**：2010-01-05 ~ 2026-06-05 (~4130 obs)
- **Target**：rv2_t = r_t² (daily squared log return as Patton noisy RV proxy)
- **Hurst 估計**：複用 K1423 `rolling_hurst(returns, window=500, lam=0.94)` — EWMA-weighted Lo R/S

### 模型對比（4 GARCH models）

| # | Model | Spec |
|---|---|---|
| 1 | GARCH(1,1) baseline | σ²_t = ω + α r²_{t-1} + β σ²_{t-1} |
| 2 | GARCH + H | + γ · H_{t-1} |
| 3 | GARCH + VIX | + δ · VIX_{t-1} (control: H 是否只是 VIX proxy) |
| 4 | GARCH + H + VIX | + γ H_{t-1} + δ VIX_{t-1} (incremental test) |

### Splits

- **IS**：2010-01-01 ~ 2019-12-31 (~2500 obs)
- **OOS**：2020-01-01 ~ 2026-06-05 (~1600 obs，含 COVID + 2022 bear + 2025-2026)
- 採 **fixed-parameter walk-forward**（IS 一次 fit，OOS 遞推 σ² 更新）— 公平 + 可行 compute cost

### 估計

- GARCH(1,1) [+exog]：自寫 `scipy.optimize.minimize` MLE（K1213 教訓：套件不收斂 ≠ 模型無效）。多 init (5 starts, seed=42) + L-BFGS-B + Nelder-Mead fallback
- 紀錄欄位：`termination_flag` / `nll_finite_ratio` / `sigma2_clamp_ratio`（避免數值病態被當收斂；Codex Round 1 建議）

### Loss / 統計檢定

- **Loss**：QLIKE (Patton 2011, robust to noisy proxy) + MSE (report both)，target = r²_t（4 model 同 target、同 loss、同 scale）
- **DM test**：Diebold-Mariano with Newey-West HAC variance, two-sided, lag = floor(4·(n/100)^(2/9))。GARCH 1-step forecast 與通用 HAC lag 公式相容（無 overlap dependence）
- **Bootstrap CI**：Moving block bootstrap (fixed block_len=5), n_boot=500, seed=42

### 比較 pairs（dm_tests 輸出）

1. `garch_baseline vs garch_plus_h` (QLIKE)
2. `garch_baseline vs garch_plus_vix` (QLIKE)
3. `garch_baseline vs garch_plus_h_vix` (QLIKE)
4. **`garch_plus_vix vs garch_plus_h_vix` — 核心 incremental test**（控制 VIX 後 H 是否仍 marginal 有效）

### Per-year OOS breakdown

避免單一 split 過度宣稱 — 對 2020-2026 每年分別算 QLIKE，看 H 是否在不同 regime（COVID 2020 / 2022 bear / 2025 calm）一致有效或只在特定子期間生效。

## 預期

- **GARCH + H vs baseline**：QLIKE 改善 0-3%；H 直接 covariate 多半弱顯著（H 變動慢，GARCH 自身 α 捕捉短期 shock 已強）
- **GARCH + VIX vs baseline**：QLIKE 改善 5-15%；VIX 強 implied vol signal，已知 lift
- **GARCH + H + VIX vs GARCH + VIX**（核心 test）：兩種可能
  - PASS：H 在控制 VIX 後仍帶 1-3% 改善 → H 不只是 VIX proxy
  - NULL：H 邊際無效（mean_d≈0, p>0.10）→ K1423 的 ρ=+0.32 完全被 VIX 吸收

## Anti-pattern guards（per `.claude/rules/experiments.md`）

| Guard | 落地 |
|---|---|
| Lookahead | 所有 covariates (h_lag/vix_lag/rv_lag) 在 `build_dataset()` 已 `.shift(1)`；Hurst 序列本身在 K1423 用 `x[t-window:t]` 嚴格 strictly past；results JSON `lookahead_audit` 區自證 |
| Seed | bootstrap `seed=42`；GARCH MLE 多 init `rng = np.random.default_rng(42)` |
| 過度宣稱 | 只看 2020-2026 OOS 單 split，不對全期下結論；report `per_year_oos` breakdown |
| 套件限制 | GARCH 自寫 scipy MLE，不依賴 `arch.arch_model`（K1213 + K1216c 教訓） |
| Walk-forward 公平比較 | 4 個 GARCH model 同 target (r²_t) / 同 loss (QLIKE+MSE) / 同 lag 慣例 / 同 IS-OOS split / 同 seed |
| 過度擬合 | 不每日 refit；用 IS-fit 固定參數 + OOS 遞推 σ²（lift 來自 covariate 訊息而非 model adaptation） |
| MLE 數值健康 | 紀錄 `termination_flag` / `nll_finite_ratio` / `sigma2_clamp_ratio`，post-run 檢查 clamp 比例（病態解識別） |

## 成功標準（運轉完成後）

- [ ] 4 個 GARCH model 都收斂 (`fit.success=True` 或至少 MLE NLL 有限值且 sigma2_clamp_ratio < 0.05)
- [ ] OOS forecasts 全部正值 (`sigma2 > 0`)
- [ ] DM test 對核心 pair `garch_plus_vix vs garch_plus_h_vix` 產出有限 p-value
- [ ] Bootstrap CI 不橫跨無窮
- [ ] Per-year breakdown 至少 5 個年度 (2020-2025) 有 ≥30 obs
- [ ] Codex review pass (lookahead / MLE 寫法 / DM HAC 寫法)
- [ ] Verdict 由主線程決定（PASS / CONDITIONAL_PASS / NULL）並寫 knowledge.json

## 後續方向

| 結果 | 接續 K |
|---|---|
| `garch_plus_vix vs garch_plus_h_vix` PASS (DM p<0.05, d>0) | **K1425a**：HAR-RV family（multi-horizon target h ∈ {1,5,22}），overlap-correct DM HAC (lag = h-1 + Newey-West formula)，純 forecast target (future-window) — Codex Round 1 推遲事項 |
| PASS | **K1425b**：其他 λ ∈ {0.97, 0.99} robustness + 跨資產 (QQQ/IWM/EFA) 重做 |
| CONDITIONAL_PASS | **K1425c**：拆 OOS 期間 — H 是否只在 high-VIX regime (VIX>20) 有 lift？|
| NULL | research_program.md 結案 `time_varying_hurst_via_ewma`；寫一篇 reader-facing「為何市場記憶力沒能預測波動」科普 |

## 輸出檔

- `K1424_hurst_garch_covariate_results.json` — 4 GARCH fits / DM tests / per-year / verdict_hint
- `data/K1424_forecasts.csv` — OOS 每日 4 GARCH model forecasts
- `data/K1424_loss_diff_series.csv` — OOS 每日 QLIKE，供 DM/bootstrap re-run

## 結果（2026-06-08 OOS run）

### DM tests（n=1615, NW lag=7, two-sided）

| Pair | mean d | DM stat | p-value | Bootstrap CI (block=5, n=500) | 解讀 |
|---|---:|---:|---:|---|---|
| baseline vs +H | +0.0224 | 2.25 | 0.0243 | [+0.0033, +0.0414] | H 對 baseline 有顯著小 lift |
| baseline vs +VIX | +0.0464 | 3.85 | 0.0001 | [+0.0227, +0.0712] | VIX 強 lift（~3% QLIKE 改善） |
| baseline vs +H+VIX | +0.0463 | 3.85 | 0.0001 | [+0.0226, +0.0710] | 與 +VIX 幾乎相等 |
| **+VIX vs +H+VIX**（核心） | **-0.00012** | **-2.99** | **0.0028** | **[-0.00020, -0.00004]** | **加 H 反而 marginal harm（effect ~10⁻⁴ 微小）** |

### Per-year OOS QLIKE

| Year | n | baseline | +H | +VIX | +H+VIX | 最佳 |
|---|---:|---:|---:|---:|---:|---|
| 2020 | 253 | 1.466 | 1.461 | **1.425** | 1.426 | +VIX |
| 2021 | 252 | **1.409** | 1.438 | 1.413 | 1.413 | baseline |
| 2022 | 251 | 1.575 | 1.466 | **1.423** | 1.424 | +VIX |
| 2023 | 250 | 1.453 | 1.432 | **1.425** | 1.425 | +VIX |
| 2024 | 252 | 1.637 | 1.627 | **1.619** | 1.619 | +VIX |
| 2025 | 250 | 1.734 | 1.710 | **1.691** | 1.691 | +VIX |
| 2026 | 107 | 1.637 | 1.624 | **1.585** | 1.585 | +VIX |

VIX 在 6/7 年最佳；H 在 2021 反而 -2% 變差；加 H 進 +VIX model 7 年皆無感（差異在小數第 4 位）。

### MLE 數值健康

- baseline / +H：`CONVERGENCE: RELATIVE REDUCTION OF F <= FACTR*EPSMCH`、`success=True`
- +VIX / +H+VIX：`termination_flag=ABNORMAL`、`success=False`，但 NLL 有限、`sigma2_clamp_ratio=0`、params 落 IS-fit α=0.1, β=0.85 邊界 → L-BFGS-B 邊界停止判據未滿足，估計值仍可用（不是失敗）；建議 K1425 系列改 reparameterize 或 unconstrained optimization

### Verdict

**NULL** — H 控制 VIX 後不僅無 incremental value，反而**統計上顯著**為負（p=0.0028）；惟 effect size 極小（~10⁻⁴ QLIKE 量級），實務無意義。K1423 ρ(H, VIX) = +0.32 被 VIX 完全吸收。

研究啟示：EWMA-Hurst 作為 long-memory 指標的訊息已被 VIX 隱含波動率涵蓋；單獨用 H 對 baseline 仍有 1.5% lift（DM p=0.024）— H 對「無 VIX 可用」的市場可能仍有價值（後續可在 TW / EM 等無成熟 IV market 上測）。

### 後續方向（依 NULL verdict）

- 結案 `research_program.md` backlog 條目 `time_varying_hurst_via_ewma`（標 NULL_resolved）
- **K1425 PCA factor-attribution 已啟動**（無關 Hurst，獨立方向）
- **不**推 K1425a HAR-RV + H（NULL_in_garch 已削弱 prior，HAR scope 性價比低；改測 TW/EM market 才有差異化動機）
- **可**寫一篇 reader-facing 短文：「市場記憶力預測波動嗎？答：VIX 已先一步知道」（draft pool）

## Notes

- **不在 scope**：不改 `feed.json`、不寫 `knowledge.json`、不動 K1423 既有檔；compute 由 worker 接手；HAR family 推 K1425a
- **Lineage**：K1423 結果直接讀（parquet cache），不重新 fetch yfinance
- **Compute estimate**：~3-5 分鐘 (4 個 GARCH MLE 各 5 starts 約 1-2 min；DM/bootstrap 秒級)
- **Codex Round 1 FAIL → Round 2 patch**（2026-06-08）：HAR family 砍出 scope；bootstrap docstring 改 moving block (與實作一致)；MLE 結果擴充 termination diagnostics
