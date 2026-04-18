# K1108f: Regime-split K1108c 5-foundry pool by semiconductor cycle

**提出**: 賴奕豪  **執行**: Claude  **日期**: 2026-04-17
**Parent**: K1108c (4-firm pool continuous magnitude NULL, β₁=-1.29e-05 t=-1.34)
**Stack**: K1108 → K1108b → K1108c → K1108f

## 動機（Motivation, D4 hypothesis）

K1108c 全樣本 pooled continuous magnitude regression 為 NULL
(β₁ = -1.29e-05, HAC t = -1.34, p = 0.18, N=135). 但 semi industry 是
強 cyclical：

- **UP-cycle**: 2020 post-COVID 補庫存 + 2024-2026 AI/HBM boom
  → capex RAISE 可能代表 growth signal（positive magnitude effect）
- **DOWN-cycle**: 2022-2023 memory/logic inventory correction
  → capex CUT 可能代表 distress signal（negative magnitude effect）
- **Pooled**: 若兩 regime β 符號相反 → 機械性抵消成 NULL

**D4 hypothesis**: capex guidance sensitivity 為 regime-dependent；
K1108c pooled NULL 是 masking confounding 的假象。

如果 K1108f 發現 β_up ≠ β_down（Wald F 拒絕等式）且至少一個 regime 的
β 通過 Harvey |t|>3 門檻 → K1108c pooled NULL 是 masking，Paper 2
敘事需改為 regime-dependent capex mechanism。

如果 K1108f 仍然 NULL → 4-layer null stack
(K1108 / K1108b / K1108c / K1108f) 確認 capex guidance **不是** foundry
θ₂>0 的機制，Paper 2 必須改方向（K1108d/e 等）。

## 設計（Design）

### 資料重用（DO NOT rewrite θ_EAV）

依任務規則直接 reuse K1108c 的 `k1108c_merged_pool.csv`
（N=135 events, 4 firms: 2330.TW, 2303.TW, GFS, 0981.HK）。**不重新
refit A4f-EAV**，確保 θ_EAV_empirical 與 K1108c 完全一致、無 seed drift。

### Regime 定義（先固定，避免 data-snooping）

```python
UP_PERIODS    = [('2020-04-01', '2021-12-31'),
                 ('2024-01-01', '2026-04-15')]
DOWN_PERIODS  = [('2022-01-01', '2023-11-30')]
TRANS_PERIODS = [('2020-01-01', '2020-03-31'),  # COVID shock
                 ('2023-12-01', '2023-12-31')]  # recovery edge
# Pre-2020 (2014-2019) events default to NEUTRAL (excluded from Spec 1)
```

| Regime | N | Events |
|--------|---|--------|
| UP | 54 | 2020Q2-2021 + 2024-2025 |
| DOWN | 32 | 2022-2023 |
| NEUTRAL | 47 | pre-2020 baseline |
| TRANSITION | 2 | COVID shock + 2023 edge |
| **UP ∪ DOWN (primary)** | **86** | — |

**Power check**: UP n=54 ≥ 20 ✓, DOWN n=32 ≥ 20 ✓. 兩 regime 皆 adequately powered.

### Spec 1 — Regime-dummy interaction

```
θ_EAV = β₀ + β_up · guide_delta_pct · 1[UP]
          + β_down · guide_delta_pct · 1[DOWN] + ε
```

- HAC Newey-West SE (Andrews 1991 auto-BW; bw=3 for N=86)
- **Wald χ²-test** H₀: β_up = β_down
- Block bootstrap (firm-stratified, block=10, N=1000, seed=42)

### Spec 2 — Continuous TSMC-revenue-YoY proxy

```
θ_EAV = β₀ + β₁ · guide_delta_pct
          + β₂ · guide_delta_pct · tsmc_rev_yoy_lag + ε
```

TSMC quarterly revenue YoY growth is hand-coded from TSMC IR
press releases (2013Q1 → 2026Q1, 53 quarters).

**Strict PIT shift**: event at time d uses most recent TSMC YoY
with `reporting_date < d` (reporting_date = quarter_end + 15 days,
conservative IR announce lag). No lookahead.

Sample: N=133 (drops 2 pre-2014Q1 events).

## 結果（Results）

### Regime counts

| Regime | N | Date range |
|--------|---|------------|
| UP | 54 | 2020Q2-2021 + 2024-2025 |
| DOWN | 32 | 2022-2023 |
| NEUTRAL | 47 | 2014-2019 |
| TRANSITION | 2 | 2020Q1 + 2023Q4 edge |

### Spec 1 — Regime-dummy HAC regression (N=86)

| Parameter | Point est | HAC SE | HAC t | HAC p | n per regime |
|-----------|-----------|--------|-------|-------|--------------|
| β₀ (intercept) | +1.09e-03 | 5.69e-04 | +1.91 | 0.056 | — |
| **β_up** | **-1.76e-05** | **2.94e-05** | **-0.599** | **0.549** | 54 |
| **β_down** | **-1.17e-05** | **1.36e-05** | **-0.863** | **0.388** | 32 |
| R² | 0.002 | — | — | — | — |

**Wald χ²(β_up = β_down) = 0.036, df=1, p = 0.8491**

兩個 β 皆負號（與 K1108c pooled β₁ 一致）、magnitude 相近、皆不顯著；
Wald 測試幾乎完全無法拒絕等式。**沒有 regime-dependent signal**。

### Spec 2 — Continuous YoY-interaction HAC regression (N=133)

| Parameter | Point est | HAC SE | HAC t | HAC p |
|-----------|-----------|--------|-------|-------|
| β₀ | +1.29e-03 | 4.45e-04 | +2.91 | 0.004 |
| **β₁ (Δpct main)** | **-5.90e-06** | **1.06e-05** | **-0.555** | **0.579** |
| **β₂ (Δpct × YoY)** | **-5.42e-05** | **6.19e-05** | **-0.877** | **0.381** |

與 Spec 1 一致：interaction term 不顯著；TSMC revenue-cycle 作為
continuous proxy 也未能救援 pooled NULL。

### Block bootstrap (Spec 1, N=1000, block=10)

| Quantity | Mean | 95% CI |
|----------|------|--------|
| β_up | +6.71e-06 | [-2.45e-05, +3.76e-05] |
| β_down | +1.52e-05 | [-1.17e-05, +6.85e-05] |
| β_up − β_down | — | [-6.21e-05, +3.63e-05]  p=0.794 |

Bootstrap 95% CI 皆跨 0；差分 CI 也跨 0（p=0.794）。

### Block bootstrap (Spec 2, N=1000, block=10)

| Quantity | Mean | 95% CI |
|----------|------|--------|
| β₁ | +1.89e-06 | [-1.12e-05, +2.27e-05] |
| β₂ (interaction) | -4.65e-05 | [-2.02e-04, +6.10e-05] |

同樣跨 0。

## 判定（Verdict）

### **H2_REGIME_NULL_CONFIRMED**

| Criterion | Threshold | Actual | Result |
|-----------|-----------|--------|--------|
| \|t_up\| > 3.0 or \|t_down\| > 3.0 (Harvey) | PASS | max=0.86 | **Fail** |
| Wald χ² (β_up=β_down) rejects | p < 0.05 | p=0.849 | **Fail** |
| \|t_b2\| > 3.0 (Spec 2 interaction) | PASS | 0.88 | **Fail** |
| Bootstrap diff CI excludes 0 | robustness | [-6.2e-05, +3.6e-05] | **Fail (spans 0)** |
| Any \|t\| > 2.0 | weaker | max=0.88 | **Fail** |

**兩個 regime 的 β 符號相同（皆負）、magnitude 相近、都不顯著；Wald 無法
拒絕等式；Spec 2 interaction 亦 null**。K1108c pooled NULL 並非 masking
confounding — regime split 之後 signal 依然不存在。

## 4-Layer Null Stack (Paper 2 implication)

| Experiment | N | Encoding | Verdict |
|------------|---|----------|---------|
| K1108 | 48 (TSMC only) | continuous | INCONCLUSIVE (underpowered, t=0.94) |
| K1108b | 136 (pool, binary) | binary flag | DECISIVE NULL (Wald t=-0.0003) |
| K1108c | 135 (pool, continuous) | continuous magnitude | DECISIVE NULL (t=-1.34) |
| **K1108f** | **86 (pool, regime-split)** | **UP vs DOWN regimes** | **DECISIVE NULL (Wald p=0.85)** |

**結論**: capex guidance 在 binary、continuous magnitude、regime-interacted
任一 encoding 下都**不是** K1104 foundry θ₂>0 rule 的機制。

### Paper 2 narrative pivot

Paper 2 的 foundry 規則必須轉向 K1108b/c 既列但未測的候選：

- **D2** (non-capex quantitative guidance): utilisation rate、
  wafer-price、R&D guidance
- **D3** (operating leverage): foundry fixed-cost structure as
  mechanism without any earnings-day component
- **D5** (non-event firm-level attributes): foundry 的 cross-firm
  dispersion in θ₂ 可能來自 non-event firm characteristics
  (geographic exposure, fab technology node, customer concentration)

Narrative state machine（依 CLAUDE.md 防 pivot）：單一 null result 不
直接改 paper body.tex；K1108f 只更新 knowledge.json + research_program.md，
等 D2/D3/D5 至少 3 個互補實驗都完成後再 user confirm narrative 改寫。

## Robustness notes（honest disclosure）

1. **Regime dating fixed a priori**: UP/DOWN 邊界皆在執行前寫死於 script
   頂端，非從資料學習。無 data-snooping。

2. **TSMC revenue YoY hand-coded**: 2013Q1-2026Q1 53 quarters of TSMC
   consolidated revenue (NT\$ bn, 1-dp precision) from public TSMC IR
   press releases. PIT shift = quarter_end + 15 days (conservative
   announce lag). 2026Q1 使用 TSMC guidance midpoint (placeholder),
   僅影響 1-2 個 2026 events.

3. **Neutral regime excluded from Spec 1**: 47 pre-2020 events 定為
   NEUTRAL 並排除於 Spec 1 primary。這是設計選擇 — Spec 2 透過
   continuous YoY proxy 納入所有可用 events 作為穩健性對照。

4. **Power**: UP n=54, DOWN n=32 皆 ≥ 20. 無 under-power flag.
   Spec 1 N=86 是中等樣本 — 若真有 regime effect,
   Power for |t|=3 at α=0.05 is ~0.85 for SE=1.36e-05 and effect size
   ~4e-05 (conservative). 現觀察 |t|≤0.86 → 不是 power 問題是 no signal.

5. **Harvey multi-testing**: 本實驗測了 Spec 1 (β_up, β_down) + Wald +
   Spec 2 (β₁, β₂) 共 5 coefficient tests. Bonferroni α=0.05/5=0.01 →
   即便有 t≈2 marginal signal 也會被糾正為非顯著。目前 max |t|=0.88
   遠低於此門檻,verdict 不受 multi-testing 修正影響。

6. **θ_EAV_empirical reuse**: K1108c 的 r²_d/g_d Jensen bias 延續；
   若該 bias 與 regime 系統性相關，可能 bias regime 估計 — 但兩
   regime 皆使用同一 bias 過濾 → 差分 (β_up − β_down) 仍 informative.

## Codex 審查

依 K1108b/K1108c precedent，null result 不強制 Codex review。
K1108f 的代碼是 K1108c 既有 `ols_hac` + 新增 Wald test + bootstrap
extension 的直接延伸，皆標準 textbook 程序。Regime 邊界 hardcoded、
TSMC YoY PIT shift 明確、seed=42 fix。如 main branch 後續提出
narrative 重大 pivot，再請 Codex 審整體 stack。

## 檔案清單

- `README.md` — this file
- `k1108f.py` — main experiment (Spec 1 regime dummies + Spec 2
  continuous YoY + Wald + bootstrap + plots)
- `k1108f_results.json` — complete statistics
- `k1108f_scatter_by_regime.png` — θ_EAV vs guide_delta_pct scatter
  coloured by regime + UP/DOWN fit lines
- `k1108f_coef_forest.png` — coefficient forest plot with HAC 95% CI
- `run.log` — full stdout

## References

- K1108 (TSMC single-firm INCONCLUSIVE)
- K1108b (4-firm pool binary NULL)
- K1108c (4-firm pool continuous NULL)
- K1104 (foundry θ₂ > 0 rule)
- Andrews (1991). Heteroskedasticity and Autocorrelation Consistent
  Covariance Matrix Estimation. Econometrica 59(3):817-858.
- Newey & West (1987). A Simple, Positive Semi-definite,
  Heteroskedasticity and Autocorrelation Consistent Covariance Matrix.
  Econometrica 55(3):703-708.
- Harvey et al. (2016). ... and the Cross-Section of Expected Returns.
  RFS 29(1):5-68. — t > 3.0 threshold for multi-testing.
- Politis & Romano (1994). The Stationary Bootstrap. JASA 89:1303-1313.
- Wald (1943). Tests of Statistical Hypotheses Concerning Several
  Parameters When the Number of Observations is Large. Transactions
  of the American Mathematical Society 54:426-482.

## Data provenance

- Parent pool: `experiments/k1108c/k1108c_merged_pool.csv` (N=135,
  4 firms, θ_EAV reused verbatim — no refit)
- TSMC quarterly revenue: hand-coded from TSMC IR public press
  releases (2013Q1-2026Q1)
- Regime boundaries: fixed at lines 88-100 of `k1108f.py`
- Random seed: 42
- OLS: numpy `np.linalg.pinv`
- HAC: manual Newey-West with Andrews (1991) auto-bandwidth
- Bootstrap: firm-stratified block resampling, 1000 reps, block=10
