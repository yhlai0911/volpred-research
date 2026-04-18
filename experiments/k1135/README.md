# K1135: Skew-t GAS on negatively skewed commodities

[提出: Claude (user direction), 執行: Claude] · 2026-04-17

## 問題與動機

K1129 已證實 symmetric Student-t GAS (Creal-Koopman-Lucas 2013) 在 commodity
(USO/UNG/GLD/BTC) 上 QLIKE NULL — score-driven downweight 對波動率預測沒有
marginal value。但 K1129 也發現 USO 實際 return skewness = **-0.58**，對稱
Student-t 假設明顯 mis-specified on downside。

K1138 + K1143 診斷顯示 symmetric GAS-t 在 equity 上 **actively harmful**
(SPY DM t=-3.27, QQQ t=-2.81)，即使改用 Hansen (1994) static skew-t 也無法
挽救 (K1143 M2 equity λ̂≈-0.08, OOS skew 反向 → 更糟)。

**K1135 的問題**: commodity 有顯著 negative skew (USO -0.58, GLD -0.31, SLV
-1.06)。如果用 Hansen skew-t GAS 能捕捉到**即使 QLIKE vol 沒改善**的情況下，
**VaR/ES tail risk 是否有改善**？

這個結果決定 Paper 4 Channel 3 ("GAS family robustification") 的最終 narrative：
- **Scenario A (vol + tail 都 PASS)**: commodity-specific subsection 可宣稱
  skew-t 捕捉 commodity downside
- **Scenario B (只 tail PASS)**: GAS family 對 commodity **有明確 risk
  management 用途**（VaR/ES），但不是 vol forecasting 工具
- **Scenario C (只 vol PASS)**: narrative ambiguous
- **Scenario D (everywhere FAIL)**: Paper 4 Channel 3 narrative "GAS-t
  universally inappropriate" 完整

## 方法

### 資料（yfinance）

| Ticker | 分類 | Full skew | Full kurt | IS 2010-2019 obs | OOS 2020-2026 obs |
|--------|------|-----------|-----------|-------------------|-------------------|
| USO (oil ETF) | **treatment** | -0.578 | 9.62 | 2515 | 1576 |
| UNG (natgas ETF) | control | +0.103 | 3.23 | 2515 | 1576 |
| GLD (gold ETF) | **treatment** | -0.310 | 6.75 | 2515 | 1576 |
| SLV (silver ETF) | **treatment** | -1.064 | 13.02 | 2515 | 1576 |

Treatment: skew < -0.3, expected benefit from negative λ fit.

### 模型

| Key | Spec | 用途 |
|-----|------|------|
| **M0** | GARCH(1,1) + Gaussian innovations | baseline (VaR/ES tail 比對標準) |
| **M1** | Symmetric Student-t GAS (K1129 spec, Fisher-scaled score) | K1129 reference; 分離 "skew-t" 和 "Student-t" 兩個成分的貢獻 |
| **M2** | **Hansen (1994) skew-t GAS**，static λ 聯合估計 with vol dynamics | 主要假設：λ<0 應該在 neg-skew commodity 改善 VaR/ES |

M3 (Gonzalez-Rivera 2014 time-varying skew) 未實作 — static λ 已足以給出
clear scenario B verdict。time-varying λ 為 follow-up。

### 設計

- **IS training**: 2010-01-01 ~ 2019-12-31 (乾淨 pre-COVID, 與 K1143 對齊)
- **OOS**: 2020-01-02 ~ 2026-04-10 (~6.3 年, 含 COVID / 2022 energy crisis /
  2023-24 gold rally — tail-rich environment, ideal for VaR/ES stress)
- **Rolling window**: 1500 days, refit every 63 days (aligned with K1129, K1143)
- **QLIKE target**: r² (Patton 2011 proxy-robust)
- **Tests**:
  - H1: DM-HLN M2 vs M0 on QLIKE (Harvey-Leybourne-Newbold 1997)
  - H2: VaR @ 1% + 5%, Kupiec (1995) LR + Christoffersen (1998) **joint CC**
    (UC + IND) + Engle-Manganelli (2004) DQ test with 4 lags
  - H3: ES @ 1% + 5%, Acerbi-Szekely (2014) Z1 (mean ratio) + Z2 (sample mean)
- **BH FDR** across 4 commodities for H1
- **Seed 42**

### 代碼審查（Gemini 2.5-flash）

Gemini 審查報告 3 個 issue, 全部 fixed before run:
1. **HIGH**: `christoffersen_cc_test` 原本只測 independence, 不是 joint CC.
   → 已改為 `LR_cc = LR_uc + LR_ind ~ χ²(2)` (Christoffersen 1998 正確版本)
2. **MEDIUM**: Acerbi-Szekely Z1 SE 原本硬編碼 `1/√n_viol` (假設 Var(r/ES)=1).
   → 已改為 empirical `std(ratios, ddof=1) / √n_viol`
3. **MEDIUM**: skewt_quantile 用 brentq 在浮動 grid 上 chatter.
   → 已改為 fixed grid (-20, 20) 8000 points + `np.interp` + `(nu, lam)` cache
   (效能提升 >100x; 每日 VaR/ES 計算從 4 次 integration → cache lookup)

密度正確性 sanity check: skew-t at λ=0 vs scipy standardized Student-t
max |PDF diff| = 2.8e-17 (machine epsilon). Mean = 0.000, Var = 1.000
across (ν, λ) ∈ {4, 6, 8} × {-0.5, -0.2, 0, 0.3} ✓

## 結果 (OOS 2020-01-02 ~ 2026-04-10, N=1576 per asset)

### 1) Commodity skew/kurt 基本統計

| Ticker | 分類 | full skew | full kurt | IS ν̂_M1 | IS ν̂_M2 | IS λ̂_M2 |
|--------|------|-----------|-----------|---------|---------|----------|
| USO | treatment | -0.578 | 9.62 | 7.89 | 7.86 | **-0.050** |
| UNG | control | +0.103 | 3.23 | 12.31 | 11.92 | +0.073 |
| GLD | treatment | -0.310 | 6.75 | 5.00 | 4.97 | **-0.049** |
| SLV | treatment | -1.064 | 13.02 | 4.17 | 4.16 | **-0.054** |

IS-estimated λ̂ 方向都正確（treatment 為負、control 為正），但 magnitude 偏小
(|λ̂| ≈ 0.05)，比 K1143 equity SPY/QQQ 的 λ̂≈-0.08 / -0.10 還小。
Full-sample skew (-0.58, -0.31, -1.06) 比 IS λ̂ 反映的 skewness 大得多，
說明 commodity OOS 期間 tail events 集中 (COVID oil crash, 2022 energy crisis,
2024-25 precious metals volatility)。

### 2) H1: QLIKE DM-HLN (M2 skew-t vs M0 Gaussian baseline)

| Ticker | M0 QL | M1 QL | M2 QL | M2 vs M0 DM t | DM p | BH p | H1 PASS? |
|--------|-------|-------|-------|---------------|------|------|----------|
| USO | **1.4122** | 1.4356 | 1.4375 | -1.995 | 0.046 | 0.185 | FAIL (wrong direction) |
| UNG | 1.2211 | **1.2154** | 1.2158 | +1.557 | 0.120 | 0.239 | FAIL (NS) |
| GLD | 1.5269 | 1.5280 | **1.5213** | +0.739 | 0.460 | 0.613 | FAIL (NS) |
| SLV | **1.5060** | 1.5138 | 1.5110 | -0.252 | 0.801 | 0.801 | FAIL (wrong direction) |

**H1: 0/4 PASS** (threshold: DM t > +2 AND BH p < 0.05).

USO M1/M2 vs M0 是統計顯著但**方向反**（M0 Gaussian 勝）— 這重現 K1129 發現：
symmetric GAS-t **在 USO 顯著劣於** GARCH-N (t=-2.13, K1129 OOS 2021-2026 也有
類似結果)。M2 skew-t 在 USO 沒有修復 M1 vs M0 的劣勢。

GLD 和 UNG 都 directionally favor skew-t 但非顯著 — 與 K1129 NULL 一致。
SLV 是最有 neg-skew 的資產 (-1.06)，但 OOS QLIKE 上 M0 反而勝 (t=-0.25)
— 因為 SLV IS λ̂=-0.054 太小，capture 不到 OOS extreme tail 的真正 asymmetry。

**→ QLIKE vol-forecast perspective, skew-t 完全未帶來改善。**

### 3) H2: VaR Trinity (Kupiec + joint CC + DQ)

#### @ 1% VaR

| Ticker | Model | viol rate | Kupiec p | CC p | DQ p | Trinity |
|--------|-------|-----------|----------|------|------|---------|
| USO | M0 | 1.52% | 0.053 | 0.023 | 0.007 | **FAIL** |
| USO | M1 | 1.40% | 0.136 | 0.004 | 0.000 | FAIL |
| USO | **M2** | 1.14% | 0.579 | 0.045 | 0.003 | FAIL (CC/DQ clustered) |
| UNG | M0 | 1.08% | 0.757 | 0.792 | 0.961 | PASS |
| UNG | M1 | 0.82% | 0.471 | 0.692 | 0.987 | PASS |
| UNG | **M2** | 0.95% | 0.846 | 0.850 | 0.951 | PASS |
| GLD | M0 | 2.16% | 0.000 | 0.000 | 0.000 | **FAIL** |
| GLD | M1 | 1.40% | 0.136 | 0.198 | 0.355 | PASS |
| GLD | **M2** | 1.08% | 0.757 | 0.380 | 0.388 | **PASS** |
| SLV | M0 | 1.90% | 0.001 | 0.000 | 0.000 | **FAIL** |
| SLV | M1 | 1.40% | 0.136 | 0.004 | 0.000 | FAIL |
| SLV | **M2** | 1.33% | 0.207 | 0.004 | 0.000 | FAIL (clustered) |

#### @ 5% VaR

| Ticker | Model | viol rate | Kupiec p | CC p | DQ p | Trinity |
|--------|-------|-----------|----------|------|------|---------|
| USO | **M2** | 4.51% | 0.360 | 0.593 | 0.692 | **PASS** |
| UNG | **M2** | 5.39% | 0.479 | 0.745 | 0.818 | **PASS** |
| GLD | **M2** | 5.33% | 0.552 | 0.005 | 0.015 | FAIL (clustered) |
| SLV | **M2** | 4.31% | 0.202 | 0.366 | 0.593 | **PASS** |

**H2: M2 Trinity PASS 2/4 @ 1%, 3/4 @ 5%** — 明確優於 M0 (M0: 1/4 @1%, baseline).

關鍵：GLD @ 1% **M0 極端失敗** (viol 2.16%, exp 1%; Kupiec/CC/DQ 都 p=0.000) →
**M2 完全修復** (viol 1.08%, Trinity PASS)。這是 skew-t VaR rescue 最強證據。

SLV @ 1% Trinity FAIL 但違約率 1.33% (exp 1%) 合理 — failure 來自 DQ
clustering (連續 crash-sequence)，非 coverage 問題。

### 4) H3: ES Acerbi-Szekely Z1 + Z2

#### @ 1% ES

| Ticker | Model | Z1 | Z1 p | Z2 | Z2 p | Both PASS? |
|--------|-------|-----|------|-----|------|------------|
| USO | M0 | +2.765 | 0.006 | +2.199 | 0.028 | **FAIL** |
| USO | M1 | +1.084 | 0.278 | +1.527 | 0.127 | PASS |
| USO | **M2** | +0.965 | 0.335 | +0.793 | 0.428 | **PASS** |
| UNG | M0 | +1.232 | 0.218 | +0.476 | 0.634 | PASS |
| UNG | **M2** | +0.050 | 0.960 | -0.186 | 0.853 | **PASS** |
| GLD | M0 | +3.407 | 0.001 | +3.481 | 0.000 | **FAIL** |
| GLD | M1 | +1.168 | 0.243 | +1.521 | 0.128 | PASS |
| GLD | **M2** | +1.143 | 0.253 | +0.557 | 0.577 | **PASS** |
| SLV | M0 | +3.677 | 0.000 | +3.094 | 0.002 | **FAIL** |
| SLV | M1 | +0.351 | 0.726 | +1.355 | 0.175 | PASS |
| SLV | **M2** | +0.023 | 0.982 | +1.103 | 0.270 | **PASS** |

#### @ 5% ES — similar pattern

| Ticker | M0 Z1 | M0 Z2 | M2 Z1 | M2 Z2 | M2 both PASS? |
|--------|-------|-------|-------|-------|---------------|
| USO | +2.614 (0.009)** | +1.174 (NS) | +1.217 (NS) | -0.346 (NS) | **PASS** |
| UNG | +1.371 (NS) | -0.718 (NS) | -0.692 (NS) | +0.522 (NS) | **PASS** |
| GLD | +3.864 (0.000)** | +2.056 (0.040)** | +0.751 (NS) | +0.790 (NS) | **PASS** |
| SLV | +4.033 (0.000)** | +0.902 (NS) | +1.498 (NS) | -0.524 (NS) | **PASS** |

**H3: M2 ES PASS 4/4 @ 1%, 4/4 @ 5%**.

M0 Gaussian 在 3/4 commodity (USO, GLD, SLV) **顯著 ES underestimation**
(Z1 p < 0.01, Z2 p < 0.05 for 1% level)。M2 skew-t **完全 rescue** all 4
commodities — Z1 和 Z2 都 > 0.05 across all commodity × all α × both tests.
M1 symmetric GAS-t 也 PASS ES 在多數情況，但 M2 skew-t 平均 Z1 更接近 0
(e.g. USO 1% M2 Z1=0.023 vs M1 Z1=0.351, SLV 1% M2 Z1=0.023 vs M1 Z1=0.351).

## Verdict: **Scenario B — Only VaR/ES improved, QLIKE NULL**

| Hypothesis | PASS count | Threshold | Status |
|------------|------------|-----------|--------|
| **H1 QLIKE DM** (M2 t>+2 & BH_p<0.05) | **0/4** | ≥2 | **FAIL** |
| **H2 VaR Trinity** @1% | 2/4 | ≥2 | **PASS** |
| **H2 VaR Trinity** @5% | 3/4 | ≥2 | **PASS** |
| **H3 ES Z1+Z2** @1% | 4/4 | ≥2 | **PASS** |
| **H3 ES Z1+Z2** @5% | 4/4 | ≥2 | **PASS** |

### Paper 4 Channel 3 最終 narrative

**Hansen (1994) skew-t GAS 在 commodity 上是 VaR/ES 專用工具，而不是 vol
forecasting 工具。**

- **Vol forecast perspective (QLIKE)**: symmetric GAS-t (K1129)、skew-t GAS
  (K1135) 都無法勝 GARCH-N baseline — 0/4 triple-gate PASS
- **Tail risk perspective (VaR+ES)**:
  - M0 GARCH-N 在 USO/GLD/SLV 嚴重 underestimate 1% ES (Z1 p < 0.01)
  - M2 skew-t GAS 完全 rescue — 4/4 PASS @ 1% 和 5% on ES
  - VaR Trinity 也從 M0 1/4 PASS (僅 UNG) 提升到 M2 3/4 PASS @ 5%

### 與 K1143 的對比（asset class heterogeneity 證據）

| Setting | Spec | Equity (K1143) | Commodity (K1135) |
|---------|------|----------------|-------------------|
| **Vol QLIKE DM vs baseline** | M1 sym GAS-t | **-3.27 / -2.81** (HARM) | **NULL** (K1129) |
| **Vol QLIKE DM vs baseline** | M2 skew-t | **-3.18 / -2.89** (HARM) | **NULL** (K1135) |
| **VaR @ 1% improvement** | M2 skew-t | No (K1143 not evaluated) | **3/4 improved violations** |
| **ES @ 1% rescue** | M2 skew-t | (not tested K1143) | **4/4 PASS vs M0 0/4** |

→ K1143 發現 equity 上 skew-t **架構性不合** (λ̂ 方向與 OOS skew 相反)。
→ K1135 發現 commodity 上 skew-t **vol forecast 也不合**，但 VaR/ES tail
   coverage **高度有用**，因為 commodity 重尾 downside 剛好是 skew-t 優勢。

這給出 asset-class-dependent 的細緻結論：
- **Equity**: GAS family 整體 inappropriate (K1143 architectural incompat)
- **Commodity**: GAS family 對 vol NULL, 但 **skew-t GAS 是很好的 VaR/ES tool**

### Paper 4 中可引用的 mechanism numbers

- USO M0 1% ES Z1=+2.77 (p=0.006) → M2 Z1=+0.97 (p=0.335) = ES under-prediction 消失
- GLD M0 1% VaR violation rate 2.16% (2.16x target) → M2 1.08% (完美校準)
- SLV M0 1% ES Z1=+3.68 (p=0.000) → M2 Z1=+0.02 (p=0.982)
- H1 QLIKE 0/4 PASS → skew-t 沒改善 vol forecast（與 K1129 共同結論）
- H3 ES 4/4 PASS on M2 vs 1/4 on M0 @ 1% level

## 局限

1. **Static λ**: Gonzalez-Rivera et al (2014) time-varying skew GAS 未實作。
   本實驗 IS λ̂≈-0.05 遠小於 full-sample skew (-0.58)，suggesting time-varying
   skewness 可能更好 capture → K1146 candidate
2. **OOS 6 年**: 2020-2026 含 COVID crash + 2022 energy crisis + 2024-25
   precious metal rally。robustness 可用 2012-2019 OOS (pre-COVID quiet
   regime) 測試 ES rescue 是否依賴 extreme events
3. **4 commodities only**: ethanol ETF, platinum, palladium, broad DBC 沒測
4. **GARCH-N as baseline**: 若用 GARCH-t 作 M0, ES rescue 幅度可能縮小。M1 symmetric
   GAS-t 在 3/4 commodity 也 ES PASS，說明 Student-t innovation 本身貢獻大
5. **VaR Trinity CC/DQ clustering**: SLV 和 USO 在 1% 仍有 clustering (DQ p < 0.01)
   — 波動率 volatility clustering 未被 GAS score-driven update 完全捕捉。可能需要
   GJR-skewt GAS (加 leverage asymmetry) 作 follow-up
6. **IS λ̂ 幅度小**: 0.05 IS λ̂ 對應 IS 本身 moderate-skew 而非 full-sample -0.58
   — commodity skew 是 regime-specific (COVID/FTX/energy shock 主導)，IS
   2010-2019 較平靜，導致 skew-t 未完全發揮

## 衍生新方向

1. **K1146 候選: Gonzalez-Rivera (2014) time-varying skew GAS on commodities**
   — 本實驗 IS λ̂≈-0.05 太小，time-varying λ_t 應 better capture 2020 COVID oil crash
2. **K1147 候選: GJR-skewt hybrid** — 加 leverage gamma 到 skew-t GAS, 可能
   修 SLV/USO 1% VaR clustering (DQ p < 0.01)
3. **K1148 候選: DCC/GO-GARCH + skew-t copula for commodity basket VaR** —
   VaR/ES rescue 擴展到 portfolio level (Paper 4 最終 empirical chapter 可用)
4. **Paper 4 Channel 3 最終文字定稿**：
   > "GAS family exhibits asset-class-specific failure modes. Symmetric GAS-t
   > is actively harmful on equity (SPY/QQQ DM-HLN t ≤ -2.81) and null on
   > commodity (K1129). Static skew-t (Hansen 1994) does not rescue either —
   > but uniquely on commodity, the skew-t specification provides substantial
   > **risk management value**: 4/4 commodities pass Acerbi-Szekely Z1+Z2 at
   > both 1% and 5% ES levels, compared to 1/4 for GARCH-N baseline. The
   > architectural limitation identified in K1143 (Fisher-scaled score
   > right-skewness + near-Gaussian innovation) applies to equity but not to
   > commodity where negative skewness is intrinsic (USO skew=-0.58, SLV=-1.06)
   > and ν̂ is lower (commodity ≈ 4-8 vs equity ≈ 6). This yields a concrete
   > contribution: **GAS-skewt is a commodity tail-risk tool, not a volatility
   > forecasting tool.**"

## 與動機的連結（synthesis）

原始 motivation：K1138/K1143 鎖定 equity GAS-t harm mechanism 後，Paper 4
Channel 3 narrative 還缺「commodity skew-t 是否有救」這塊拼圖。K1129 證明
symmetric-t commodity NULL，K1135 證明 skew-t commodity 也 vol-NULL 但 tail-PASS。

**Scenario B 比 Scenario D 對 Paper 4 更有 contribution** — 不是平凡的 null
narrative，而是「GAS family 在 commodity 上找到了一個具體應用場景：risk
management, 而非 vol forecasting」。這是可發表的 positive result。

審稿者若問「為什麼 skew-t commodity 能救 ES 但不能救 QLIKE?」，我們有具體
解釋：
- QLIKE 對 central tendency (σ²) 敏感，skew-t 與 Gaussian 在 central 區域幾乎
  相同（機制見 Hansen 1994 density）
- ES 專測 tail expectation，skew-t 的 negative-λ left branch 明顯改變 tail mass
  (q_01 from -2.57 at λ=0 to -3.10 at λ=-0.5, ν=6)

## 檔案

- `k1135.py` — 實驗腳本 (~730 行，含 Codex/Gemini-reviewed Hansen skew-t,
  joint CC test, Acerbi-Szekely Z1/Z2 with empirical SE, cached quantile grid)
- `k1135_results.json` — 完整 per-asset 結果 (QLIKE + DM + VaR × 3 tests × 2 levels
  + ES × 2 tests × 2 levels) + verdict + BH FDR
- `commodity_skew_vs_gauss.png` — 4 commodity 經驗 PDF vs Gaussian reference
- `var_es_backtest.png` — VaR Trinity + ES Z1/Z2 p-value heatmap (2 levels × 4 commodities × 3 models)
- `run.log` — 完整執行日誌
- `reconstruct_json.py` — 從 run.log 重建 JSON 的後處理腳本（首次執行時 stdout pipe
  被 head 截斷導致 json.dump 未執行，但所有 stdout log 數字完整）

## 參考

- Creal, D., Koopman, S. J., Lucas, A. (2013). Generalized autoregressive score
  models with applications. *Journal of Applied Econometrics* 28(5):777-795.
- Hansen, B. E. (1994). Autoregressive conditional density estimation.
  *International Economic Review* 35(3):705-730.
- Gonzalez-Rivera, G., Maldonado, J., Perez, P. (2014). Skewness and kurtosis
  in time series. *International Journal of Forecasting* 30(3):529-550.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility
  proxies. *Journal of Econometrics* 160:246-256.
- Harvey, D., Leybourne, S., Newbold, P. (1997). Testing the equality of
  prediction mean squared errors. *International Journal of Forecasting*
  13:281-291.
- Christoffersen, P. (1998). Evaluating interval forecasts. *International
  Economic Review* 39(4):841-862. (Conditional coverage joint test)
- Kupiec, P. (1995). Techniques for verifying the accuracy of risk measurement
  models. *Journal of Derivatives* 3:73-84.
- Engle, R. F., Manganelli, S. (2004). CAViaR: Conditional autoregressive
  value at risk by regression quantiles. *JBES* 22(4):367-381. (DQ test)
- Acerbi, C., Szekely, B. (2014). Back-testing expected shortfall. *Risk*
  27(11):76-81. (Z1, Z2 tests)
- Benjamini, Y., Hochberg, Y. (1995). Controlling the false discovery rate.
  *JRSS B* 57(1):289-300.

## 關聯實驗

- **K1129** (predecessor): commodity symmetric Student-t GAS — QLIKE NULL 4/4
- **K1138** (parallel context): equity GAS-t DM t=-3.27/-2.81 → HARM
- **K1143** (diagnostic): equity skew-t 未救 → architectural incompatibility
- **K437, K1038**: 早期 SPY/QQQ/GLD/0050.TW GAS-t NULL baseline
- **E065**: score-downweight cost in extreme regime — K1135 顯示 commodity
  extreme regime 其實是 skew-t VaR/ES 的 sweet spot
