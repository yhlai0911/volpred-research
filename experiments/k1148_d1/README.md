# K1148_d1 — K1145 Binary EAV OOS Panel DM Retest

> **TL;DR (Verdict: Scenario B — Marginal FAIL):** K1145 binary EAV spec re-evaluated with K1148's corrected OOS panel DM infrastructure (per-stock DM + stock-bootstrap SE across N=29 stocks). In-sample pooled θ_EAV is strongly identified (+4.90e-5, Hessian t = +10.62, IS 2010-2019). But OOS (2020-2025) panel DM **fails the joint PASS threshold** (t ≤ -2 AND p_one < 0.05): panel DM mean t = -1.46, bootstrap one-sided p = 0.0758. Paper 2 §5 "universal-magnitude three-market regularity" claim can no longer lean on OOS leg for either binary or continuous EAV — both fail.

[提出: Claude (Paper 2 §5 main-evidence validation), 執行: Claude]

---

## 1. 動機（Why）

K1148 剛完成並報告：continuous |surprise|-EAV 在 OOS panel DM 下 **FAIL** (t=-1.16, p=0.12)，與 IS pooled θ_EAV t=+10.43 的高顯著性相衝突。

Paper 2 §5 narrative 目前基於 K1145 binary EAV 的 **PASS** 結論（pooled θ_EAV=+6.36e-5, Hessian t=+14.14, cluster bootstrap t=+5.24, placebo 13.6σ）定位為 "universal-magnitude three-market regularity"。但 K1145 **從未做過** OOS panel DM 檢定——僅全樣本 2010-2025 MLE + bootstrap + placebo。

風險：如果 K1145 binary EAV 用 K1148 的 **正確 panel DM infrastructure**（per-stock DM + stock-bootstrap，而非天真 pool-all-stock-days）重測也 FAIL，Paper 2 §5 整段必須降級或改寫。

這個實驗是 **main-evidence recheck，不是延伸**。

### Three scenarios (pre-registered)

| Scenario | Binary OOS panel DM | Paper 2 §5 影響 |
|----------|---------------------|-----------------|
| **A** | t ≤ -2 **AND** p_one < 0.05 | universal-magnitude claim 保留 + 強化 binary-optimality 解讀 ("event is signal, magnitude is noise") |
| **B** | t ∈ (-2, 0], **or** t ≤ -2 但 p ≥ 0.05 | §5 降級為 IS-only pooled θ evidence; OOS inconclusive |
| **C** | t > 0 (反向) | universal-magnitude claim 撤回; §5 必須 pivot |

---

## 2. 方法（What）

### 2.1 Spec（嚴格對齊 K1145 + K1148）
- **Binary EAV** 從 `財報公告日.txt` (K1145 來源)，window=1（僅公告當日），**不是** K1148 的 |surprise| continuous
- **τ spec**: `τ_{i,t} = max(θ₀_i + θ_VIX · VIX²_{t-1} + θ_EAV · EAV_{i,t-1}, ε)`
- **σ² = g × τ**, g = GJR(1,1)_i per-stock, θ_VIX + θ_EAV shared across stocks (pooled)
- **Lag-1** enforced inside `_negll_numba` and `_forecast_sigma2_numba` via `vix[t-1]`, `eav[t-1]` — structural, not reliant on memory

### 2.2 Sample（對齊 K1148 子集以做 apples-to-apples 比較）
- **N=29 stocks**（K1148 survival 子集，與 K1145 31 stocks 的交集扣除 2388.TW, 2883.TW 兩檔 yfinance earnings-surprise 資料不足者）
- **IS**: 2010-01-01 ~ 2019-12-31, **OOS**: 2020-01-01 ~ 2025-12-31（完全對齊 K1148 split）
- **70,968 IS obs + 42,224 OOS obs**; 每股 57-61 公告事件

### 2.3 Estimation
- Block Coordinate Descent + Numba-JIT (verbatim from K1145/K1148)
- IS-only 估計 shared (θ_VIX, θ_EAV) + per-stock (θ₀, ω, α, γ, β)
- 最多 8 outer iter, `ftol=1e-10`
- **無 OOS refit**（pure forward-only forecast）

### 2.4 OOS Panel DM Test（關鍵，Codex-corrected K1148 spec）
1. **Per-stock DM-HLN**: 對每一檔股票 i，用 IS-fitted 參數對 OOS 計算 binary EAV model σ²_i,t 和 pure-GJR baseline σ²_i,t，QLIKE loss，DM-HLN t-stat（Student-t small-sample correction at h=1）
2. **Stock-bootstrap**: 從 29 per-stock DM t-stats 有放回抽樣 **10,000 次**（vs K1148 只用 2,000），計算 panel DM 平均 + bootstrap SE + 95% percentile CI + one-sided p (binary better than baseline)
3. **PASS 判定（joint threshold）**: `panel_dm_t ≤ -2.0 AND panel_dm_p_one < 0.05`
   - ⚠️ Codex pre-execution review 抓到：初稿只檢查 t，會給出 false PASS。已修正為聯合條件（對齊 docstring spec 和 K1148 H3 邏輯）

### 2.5 Random seed
`GLOBAL_SEED = 42`（numpy + default_rng）; bootstrap seed = 123

---

## 3. 資料

| 項目 | 值 |
|------|-----|
| 數據來源 | yfinance daily close (cache from K1148) + `財報公告日.txt` (Big5) |
| 期間 | 2010-01-01 ~ 2025-12-31 |
| IS / OOS 分點 | 2020-01-01 |
| N_stocks | 29 (K1148 子集) |
| IS obs | 70,968 |
| OOS obs | 42,224 |
| IS events total | 1,721 |
| OOS events total | — (次要資訊) |
| Seed | 42 |

---

## 4. 結果（Findings）

### 4.1 IS pooled MLE (binary EAV)

| 量 | 值 |
|-----|----|
| θ_VIX | +9.45e-08 |
| **θ_EAV (pooled IS)** | **+4.90e-05** |
| Hessian SE (1D conditional) | 4.61e-06 |
| **Hessian t** | **+10.62** |
| IS pooled log-lik | 198,238.81 |
| BCD outer iter | 8 (未嚴格收斂，但 θ_EAV 在 iter 4 後穩定於 ±0.002e-5 範圍) |

**對照 K1145 全樣本 (2010-2025, N=31)**: θ_EAV=+6.36e-5, Hessian t=+14.14。
K1148_d1 IS-only (2010-2019, N=29) θ_EAV 略小、t 略低——符合預期（更短的樣本、更少的股票）。

### 4.2 OOS panel DM test（主檢驗）

| 量 | 值 |
|-----|----|
| Per-stock DM 有效樣本 | 29/29 |
| Panel DM mean | **-0.5365** |
| Panel DM median | -0.8593 |
| Panel DM bootstrap SE (N=10,000) | 0.3671 |
| **Panel DM t** | **-1.4615** |
| Panel DM 95% bootstrap CI | [-1.229, +0.217] — **跨越 0** |
| **Panel DM one-sided p** | **0.0758** |
| 個別股票 DM ≤ -2 | 9/29 (31.0%) |
| Pooled mean QLIKE (binary) | -7.0927 |
| Pooled mean QLIKE (GJR) | -7.0846 |

**判決**: 
- Panel DM t = -1.46 **未達** Harvey (2016) t ≤ -2 門檻
- Bootstrap one-sided p = 0.076 **未達** α=0.05
- **95% bootstrap CI 跨越 0** — 無法拒絕 "binary = baseline" null
- 但方向一致（mean & median 皆 < 0），31% 個股 DM ≤ -2 顯示訊號並非完全缺席

### 4.3 直接比較 K1148 continuous

| Spec | θ_EAV IS | IS t(Hessian) | OOS DM_t | OOS p_one | Joint PASS? |
|------|---------|---------------|----------|-----------|-------------|
| **K1148_d1 (binary, 29 stocks)** | +4.90e-5 | +10.62 | **-1.46** | 0.0758 | ❌ FAIL |
| K1148 (continuous \|surprise\|, 29 stocks) | +2.70e-4 | +10.43 | -1.16 | 0.1225 | ❌ FAIL |

**兩個 spec 在 IS 都高度顯著，在 OOS 都 FAIL。Binary 的 OOS DM 比 continuous 略好（更負、p 更小），但仍未越過門檻。**

- 「event 訊號比 magnitude 強」這條 narrative 有弱支持（binary DM 更負）
- 但「event 訊號強到可以推翻 baseline」在 OOS 不成立

### 4.4 Codex pre-execution 審查摘要
**1 HIGH bug 抓到並修正，無其他 HIGH severity issue。**
- HIGH bug: Scenario A 判定只用 `panel_dm_t ≤ -2`，違反 docstring spec 和 K1148 H3 聯合條件。已修正為 `t ≤ -2 AND p_one < 0.05`
- 其他 4 檢查點通過: (a) binary EAV 來源正確 (`財報公告日.txt`), (b) lag-1 in numba, (c) IS/OOS split 無 overlap + 無 OOS refit, (d) QLIKE burn-in 兩模型一致從 t=1 開始

---

## 5. 結論

### Verdict: Scenario B — Marginal FAIL

Binary EAV OOS panel DM t = **-1.46**, bootstrap one-sided p = **0.076**

- **Scenario A (PASS)**: ❌ 未達成 (需要 t ≤ -2 AND p < 0.05)
- **Scenario B (marginal FAIL)**: ✅ **本實驗判決** — DM 為負（方向對）但不夠強；IS pooled θ_EAV 高度顯著但無法在 OOS 被外推式拒絕 baseline
- **Scenario C (反向 FAIL)**: ❌ 未達成（DM 為負不是正）

### Paper 2 §5 implication

**Paper 2 §5 "universal-magnitude three-market regularity" narrative 必須降級。**

原先建立在 K1145 binary EAV PASS 上的 §5 主張在 OOS 維度無法獲得 K1148 corrected panel DM infrastructure 支持。**具體建議：**

1. **保留的結論**（仍有證據支撐）：
   - IS pooled θ_EAV 在 binary spec 下顯著為正（+4.90e-5, Hessian t=+10.62, IS 2010-2019）
   - K1145 placebo 檢定（13.6σ distance）與 cluster bootstrap (t=+5.24) 仍有效
   - 31% 個股 (9/29) 在 OOS 有個別顯著的 binary-EAV forecast 改善 (DM ≤ -2)

2. **必須降級的主張**：
   - "Universal-magnitude" 不可再使用。應改為 **"IS-identified panel effect with OOS heterogeneity — some stocks benefit, panel-mean improvement insufficient to reject baseline"**
   - 不可宣稱「跨市場普適」——OOS 在同一市場（台股）都未過關，跨市場擴展需要新的方法論

3. **§5 pivot 建議方向**:
   - **Option 1（保守）**: 完全刪掉 §5 OOS 段，只報告 IS identification。論文降級為「panel-level IS evidence paper」
   - **Option 2（中庸）**: 保留 §5 但改框架為「announcement-driven vol is IS-identifiable but OOS subgroup-dependent」，報告 9/29 個股 individual PASS rate，把"universal-magnitude"改為"subgroup-specific effect"
   - **Option 3（擴張）**: 加一個新 subsection 探討哪類股票 OOS 有 DM≤-2 (金融/塑化/電子？) — 這才是 Paper 2 真正的 empirical contribution

### 局限（honest limitations）

1. 樣本為 N=29 台股（K1148 子集），Cross-stock bootstrap SE 受限於 N=29 的離散度
2. OOS 期 2020-2025 涵蓋 COVID 衝擊 (Feb-Mar 2020) + 2022 升息循環 + 2024 geopolitics — 可能 OOS regime 變化太大以至於 IS-fitted 參數不具預測力（regime instability ≠ model invalidity）
3. Binary EAV window=1 是極簡定義；K1145 robustness 顯示 window=3/5 也顯著——但本實驗只測 window=1（對齊 K1145 primary spec）
4. OOS panel DM 的 9/29 個股 PASS 顯示訊號確實存在但分散，可能需要 heterogeneity-aware 的 secondary test（e.g. meta-analysis, subgroup stratification）

### 衍生 next_tasks

| K ID | 主題 | 優先度 |
|------|------|--------|
| K1148_d2 | 9/29 OOS-DM-PASS 股票的 firm characteristic regression：是否某些特質 (market cap, sector, liquidity) 可預測 OOS EAV 效應？ | 高（為 §5 pivot 提供 empirical backbone）|
| K1148_d3 | OOS split 改為 rolling 2-year 視窗：binary EAV OOS DM 是否在某些年份 PASS 某些 FAIL？(regime stability test) | 中 |
| K1149 | Paper 2 §5 manuscript pivot：刪除 "universal-magnitude" 宣稱；按 Option 2 or 3 改寫 | **最優先**，直接由本 K 觸發 |

---

## 6. 檔案

- `k1148_d1.py` — 主實驗腳本（IS BCD + per-stock DM + stock-bootstrap panel DM）
- `k1148_d1_results.json` — 完整結果 JSON（含 per-stock DM 表、bootstrap CI、直接對比 K1148）
- `binary_vs_continuous_oos.png` — 三面板比較 (a) IS θ_EAV t-stat (b) OOS per-stock DM mean (c) OOS bootstrap panel DM t
- `run.log` — stdout 執行 log
- `README.md` — 本文件

---

## 7. 參考文獻

- Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253-263.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*, 13, 281-291.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns. *Review of Financial Studies*, 29(1), 5-68. *(t > 3 threshold; t > 2 as conventional OOS threshold)*
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256. *(QLIKE robust ranking under r² proxy)*
- Engle, R. F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics*, 95(3), 776-797. *(GARCH-MIDAS long-run τ)*
- Cameron, A. C., Gelbach, J. B., & Miller, D. L. (2008). Bootstrap-based improvements for inference with clustered errors. *Review of Economics and Statistics*, 90(3), 414-427. *(cluster bootstrap for panel)*

## 8. 相關 K 編號

- **K1109 / K1113 / K1140** — Cross-sectional/firm-covariate/temporal NULL (pre-context)
- **K1145** — Binary EAV pooled panel IS PASS (但未做 OOS panel DM)
- **K1148** — Continuous |surprise| EAV, OOS panel DM FAIL (H1 PASS, H3 FAIL) — 本實驗直接承接

---

## 9. 誠實性自檢（Preamble Rule #5）

1. **Mechanical vs empirical**: OOS DM FAIL 是 empirical finding — 不是模型定義的必然結果（IS 有識別 + OOS 有機會 PASS）
2. **vs research_program.md 既有標準**: 符合 Harvey (2016) threshold + Codex-corrected panel DM spec
3. **不同 target/proxy 會改變結論嗎？**: 本實驗用 r² proxy + QLIKE loss (Patton 2011 robust)。如果改用 RV proxy 結論可能不同，但 binary EAV 的 OOS DM 已經用最 proxy-robust 的 Patton QLIKE 測過
4. **Sharpe > 2x baseline?** 不適用（volatility forecast 評估，非策略 backtest）
5. **結論強度 vs 證據**: 判決為 "Scenario B — Marginal FAIL"，沒有宣稱 "clean PASS" 也沒有宣稱 "definitive REJECT"。個股 31% PASS 如實報告。方向一致但 panel 不過門檻如實報告。
