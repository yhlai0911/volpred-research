# K1543 brief — Listed infrastructure inflation-hedge: 真效應還是 energy + duration beta artifact?

## 動機與差異化

主流敘事：listed infrastructure ETF（IFRA / NFRA / IGF / GRID / PAVE / UTF / XLU）在通膨期間提供 hedge — 收費自動 CPI 連動、實體資產、穩定現金流。

**Falsifiable claim**：「inflation-shock days 上, listed infra RV、downside semivariance、equity correlation **顯著低於** 廣泛股市（SPY），且此效應 **獨立於 energy beta（XLE）與 duration beta（TLT/IEF）**」。若控制 energy/duration 後 alpha → 0，則 hedge 是 composite-beta artifact，不是 infra-specific 性質。

**與 K1508 (AI power demand → NULL) 差異**：
- K1508 測 AI 敘事 → 監管/裝置容量 → ETF RV 是否進入高 vol regime
- K1543 測 **inflation-hedge 機制** + **是否在 energy/duration beta 控制後仍 survive**
- Outcome 不同（K1508: log(fwd_rv21 ratio)；K1543: inflation-shock 條件下 RV/semivariance/correlation）
- 不重複跑 AI narrative；focus 在 CPI/PPI surprise event + breakeven inflation regime

## 任務（K1543）

### Data (yfinance + FRED)
1. **Infra ETFs**: IFRA, NFRA, IGF, PAVE, GRID, UTF, XLU（測 7 個取最長 overlap）
2. **Controls**: SPY (broad market), XLE (energy beta), TLT (long duration), IEF (intermediate duration)
3. **Inflation signals**:
   - CPI surprise = (CPI release - Bloomberg/consensus expected) 改用 FRED CPIAUCSL MoM Δ (deviation from 12m trailing mean) 當 proxy
   - PPI surprise: PPIACO MoM Δ deviation
   - Breakeven inflation: T5YIE / T10YIE (FRED)
4. Period: 2014-01 to 2026-06（covers high-inflation 2021-2023 regime + low-inflation 2014-2019 + normalisation 2024-25）

### Method
1. 計算 daily log returns + 20d rolling RV + downside semivariance (RV restricted to r<0) + 60d rolling corr(ETF, SPY)
2. **Inflation-shock days definition**: 月度 CPI release 前後 ±5 trading days OR breakeven_5y 單日 ΔBP > 5（top 5% tail）。所有 lag 用 .shift(1)
3. **Hypothesis tests** (4 tier):
   - **H1 (raw)**: 在 inflation-shock days, ETF RV 是否 < SPY RV？ paired t-test + Wilcoxon
   - **H2 (downside)**: ETF semivariance 是否 < SPY semivariance？
   - **H3 (correlation)**: ETF-SPY 60d corr 在 inflation-shock regime 是否 < baseline regime？ Fisher z-transform 比較
   - **H4 (controlled, KEY)**: regression  
     `log(rv_etf / rv_spy)_t = α + β1 * inflation_shock_dummy_{t-1} + β2 * |return_xle|_{t-1} + β3 * |return_tlt|_{t-1} + β4 * vix_{t-1} + ε`  
     If β1 (after controlling energy + duration beta) 仍顯著負 → hedge 真實。If β1 → 0 → composite-beta artifact (核心 falsifiable claim)
4. Bonferroni adjust across 7 ETFs × 4 tests = 28 cells；mark cells passing α=0.05 raw, α=0.05/28=0.0018 Bonferroni
5. Robustness: 分 2014-2019 (low inflation) vs 2020-2026 (high inflation) sub-period — hedge effect 是否 regime-dependent

### Lookahead 防錯硬規則
- All predictors `.shift(1)`
- CPI surprise 用 release date（FRED ALFRED real-time vintage 或 conservative lag = release_date + 1 trading day）
- Rolling windows 不向前看
- seed=42 全程

### Output
- `experiments/k1543/k1543.py`
- `experiments/k1543/k1543_results.json` — full hypothesis table (28 cells + controlled regression results)
- `experiments/k1543/README.md` — 動機 + 差異化 vs K1508 + 方法 + verdict
- ≥2 圖：
  - fig1: inflation-shock vs baseline regime 下 7 ETF RV vs SPY RV 比較 (boxplot)
  - fig2: controlled regression β1 coefficient + 95% CI 跨 7 ETFs (forest plot)
- verdict_summary.interpretation: 真實反映 controlled regression 後幾個 ETFs 仍 survive

## 成功標準
1. 7 ETFs × 4 tests = 28 cells 全有 p-value 並 Bonferroni adjusted
2. H4 controlled regression β1 顯著性可清楚 falsify 或 confirm hedge claim
3. README 寫清楚 result 跟 K1508 差異 + 引用 inflation-hedge 文獻 ≥3 篇
4. **Codex review 必跑**（codex exec --skip-git-repo-check — fallback: feature-dev:code-reviewer subagent；CONDITIONAL_PASS 以上才可寫 knowledge）

## Scope 硬限制
- 只產 `experiments/k1543/` 內檔案
- 禁改 feed.json / knowledge.json / paper / supabase sync — 主線程驗證後寫
- 50 分鐘 hard cap
- Codex CLI 故障 → fallback `feature-dev:code-reviewer` subagent

## 文獻參考（agent 自行 web search 補齊 ≥3 篇）
- Rödel (2014) — inflation hedging properties of REITs/infra
- Bekaert & Wang (2010) — inflation risk and the inflation risk premium
- Bhardwaj, Gorton, Rouwenhorst (2015) — commodities & inflation

## 防錯規則必讀
- `docs/error_log.md` 最近 entries
- `.claude/rules/experiments.md` lookahead + arch forecast alignment + QLIKE + cross-asset pooled inference
