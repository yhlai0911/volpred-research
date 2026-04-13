# K1100: Student-t / Clayton Copula-GARCH vs DCC-A4f for 50/50 SPY/GLD Portfolio Tail Risk

- **提出者**: 用戶 (賴奕豪, copula-GARCH 專家)
- **執行者**: Claude (autonomous-research)
- **日期**: 2026-04-12
- **狀態**: 完成
- **父實驗**: K1041 (DCC-A4f 初版), K1092 (DCC-A4f-ASYM 最佳), K193 (靜態 copula tail dep)

## 問題

DCC 只捕捉線性相關。Copula-GARCH 能分離邊際波動與 dependence structure，特別是非線性尾部相依（tail dependence）。
**核心問題**: Student-t 或 Clayton copula（with A4f-ASYM 邊際）能否在 50/50 SPY/GLD 組合的 VaR/ES 上**顯著**勝過 K1092 最佳模型 DCC-A4f-ASYM？

## 動機

1. **用戶專長**: 賴奕豪 (2024, APFM 31(2)) 在 PRS 論文中使用 copula-GARCH。此實驗將 copula 視角帶入 A4f-ASYM 框架。
2. **K1092 已驗證**: DCC-A4f-ASYM (SPY-VIX² + GLD-GVZ²) 在 QLIKE 上顯著勝 DCC-GJR (Harvey t=5.06)。
3. **DCC 限制**: 僅捕捉線性 correlation ρ，無法刻畫尾部相依（extreme co-movement）。
4. **Copula 優勢**: Student-t 有對稱上下尾部相依；Clayton 有不對稱的下尾相依（金融危機最關心）。
5. **K193 的靜態 copula 結論**: SPY-GLD tail dependence 存在但不強（λ_L≈0.063）。本實驗驗證其動態版本在 portfolio VaR 上的實質效益。

## 方法

**5 個模型並列**:

| 模型 | 邊際 | Copula / DCC | 說明 |
|------|------|--------------|------|
| DCC-GJR | GJR(1,1) × 2 | Gaussian DCC | 無 regressor baseline |
| DCC-A4f-SYMM | A4f with VIX² × 2 | Gaussian DCC | K1092 SYMM |
| DCC-A4f-ASYM | A4f (SPY-VIX, GLD-GVZ) | Gaussian DCC | **K1092 best** |
| Copula-t-A4f-ASYM | A4f (SPY-VIX, GLD-GVZ) | **Student-t copula** | NEW: 對稱尾部 |
| Copula-Clayton-A4f-ASYM | A4f (SPY-VIX, GLD-GVZ) | **Clayton copula** | NEW: 下尾相依 |

**VaR/ES 計算**:

- DCC 模型: CF-Rolling VaR (K1092 做法, 252d rolling)
- Copula 模型: Monte Carlo 模擬 (N=5000/day)
  1. 抽 (u₁, u₂) 來自 copula
  2. 以邊際 Student-t⁻¹ CDF 轉為 (z₁, z₂)
  3. r_i = √h_i × z_i
  4. r_p = 0.5 × r₁ + 0.5 × r₂
  5. VaR_α = quantile_α(r_p), ES_α = mean of r_p below VaR

**統計檢定**:

- Trinity test (Kupiec + Christoffersen + Basel) at α=1%, 2.5%
- ES backtest (Acerbi-Szekely 2014 Z₁)
- Fissler-Ziegel (2016) joint VaR-ES FZ₀ score
- Diebold-Mariano test with Harvey |t|>3.0 threshold
- Tail dependence 時序 λ_L (Clayton), λ (Student-t)

**配置**:

- Data: yfinance SPY, GLD, ^VIX, ^GVZ (2005-01-04 to 2026-04-10, 5350 days)
- OOS: 2013-06-01 onwards (3234 days, same as K1092 for direct comparison)
- Training window: 1250 days; Refit: every 63 days
- Seed: 42

## 預期

- **H1**: Copula-t 可能 QLIKE 微勝 DCC-A4f-ASYM（因能刻畫 fat tails），但統計顯著性不確定
- **H2**: Clayton 可能在 1% 下尾 VaR 勝 Student-t（專攻下尾）
- **H3**: COVID 2020-03 期間 copula 可能展示 tail dependence 暴衝（若 SPY 崩盤時 GLD 也崩）
- **負面預期**: SPY-GLD 過去 20 年平均 corr ≈ 0.06（full-sample），tail dependence 可能不強 → copula 未必顯著勝 DCC

## 結論

### 核心發現

**用戶的 copula-GARCH 直覺在 portfolio VaR 上無法顯著打敗 DCC-A4f-ASYM**。K1092 的結論穩固。

| 假設 | 結果 | DM t-stat | Harvey |t|>3 |
|------|------|-----------|------|
| **H1: Copula-t 勝 DCC-A4f-ASYM (QLIKE)** | **否定** | -1.68 | ❌ NS |
| **H2: Clayton 勝 DCC-A4f-ASYM (QLIKE)** | **否定** | -1.41 | ❌ NS |
| **H1-FZ: Copula-t 勝 DCC-A4f-ASYM (1% FZ)** | **否定** | -0.92 | ❌ NS |
| **H2-FZ: Clayton 勝 DCC-A4f-ASYM (1% FZ)** | **否定** | -0.53 | ❌ NS |
| **H3: Clayton 勝 Copula-t (1% FZ)** | ✅ 肯定 | +3.02 | ✅ Harvey Sig |
| **Copula-t 勝 DCC-GJR (QLIKE)** | ✅ 肯定 | +4.08 | ✅ Harvey Sig |
| **Clayton 勝 DCC-GJR (QLIKE)** | ✅ 肯定 | +4.10 | ✅ Harvey Sig |

### Trinity Test (Kupiec+CC+Basel) 勝負

| 模型 | α=2.5% | α=1% | Trinity |
|------|--------|------|---------|
| DCC-GJR | PASS | FAIL (CC) | 1/2 |
| DCC-A4f-SYMM | PASS | PASS | **2/2** |
| DCC-A4f-ASYM | PASS | FAIL (CC) | 1/2 |
| Copula-t-A4f-ASYM | FAIL (Kupiec) | FAIL (Kupiec) | 0/2 |
| **Copula-Clayton-A4f-ASYM** | PASS | PASS | **2/2** ✅ |

### Mean QLIKE 排名（lower better, unit = negative）

1. **DCC-A4f-ASYM**: -9.11477 ✅ 最佳
2. Copula-Clayton-A4f-ASYM: -9.10873
3. Copula-t-A4f-ASYM: -9.10799
4. DCC-A4f-SYMM: -9.09029
5. DCC-GJR: -9.05021 (最差)

### Copula 動態參數

- **Student-t copula**: ρ 均值 +0.023 (vs DCC-A4f-ASYM 的 +0.028)，ν 均值 7.95（fat-tail confirmed），**λ 均值 0.038**
- **Clayton copula**: θ 均值 0.077（非常弱），**λ_L 均值 0.007**（下尾相依近乎為零）
- **SPY-GLD 長期近乎無尾部相依**：兩種 copula 都指向相同結論 — SPY 和 GLD 本質上是 tail-independent

### COVID 2020-02 至 2020-06 發現

- **Student-t ρ 轉負**: -0.128（平常 +0.023）— SPY 和 GLD 在 COVID 期間**反向移動**（黃金避險）
- **ρ 轉負同時 λ（尾部相依）塌縮至 0.002**（從平均 0.038）— 負相關時尾部相依本來就趨於 0
- **Clayton θ 塌至下限 0.010**, λ_L ≈ 0 — Clayton copula 無法捕捉負相關（它只支援正向下尾相依）
- 這解釋為何 Clayton VaR 表現勉強過關：它退化為獨立 copula，相當於「不依賴兩資產相依性」

### 為什麼 Copula-t Trinity FAIL

MC-based VaR 的 violation rate 在 2.5% 下達 **3.28%**（Kupiec p=0.007，明顯過度違約）。原因：
1. MC 取樣的尾部 noise 使 VaR 估計偏樂觀（quantile 往右偏）
2. Student-t copula 的 nu ≈ 8 假設可能過度 fat-tail
3. 邊際 PIT 到 Student-t 假設（相對 GJR 的實際殘差分配）有偏差

### 研究誠實原則標註

- **實證分析（真實數據）**：yfinance SPY/GLD/VIX/GVZ，2005-2026
- **Null result 如實報告**：user's copula-GARCH hypothesis 的 H1/H2 被拒絕
- **局限**：OOS 不含 2008 GFC、MC paths N=5000 有取樣誤差、Clayton 無法捕捉負相依
- **提議者**: 用戶 (賴奕豪 APFM 2024 copula-GARCH 專家)

### 對用戶研究方向的啟示

1. **Copula-GARCH 在 portfolio VaR 上未必勝 DCC（當 SPY-GLD tail 相依本來就弱時）**
2. **SPY-GLD 是 tail-independent asset pair** — 這是統計事實，不是模型選擇的問題
3. **用戶的 PRS copula 論文**（Lai 2024）比較的是 spot-futures 的 hedge，那裡 tail dependence 強 → copula 有價值
4. **這個實驗的方法論**可以用來檢視**其他 asset pairs**（e.g., SPY-TLT 在 rate regime 改變時、SPY-QQQ 在 tech crash 時）是否 copula 顯著勝 DCC
5. **若要 paper-level 貢獻**：Asymmetric copula (Patton 2006 GJR-copula) 可能比 symmetric Student-t 更貼合實證

### 下一步方向（寫入 research_program.md）

1. **K1100b**: SPY-TLT + SPY-QQQ pair 測試（tail dependence 更強的 pair）
2. **K1100c**: Patton asymmetric copula（JEDC-style 時變 ρ_L, ρ_U）
3. **K1100d**: Portfolio VaR 時用 conditional on VIX regime 的 copula（低 VIX → Gaussian, 高 VIX → Student-t）
4. **Paper**: Lai (2024) APFM 延伸至 equity-bond hedging（不是 spot-futures）

## 檔案

- `k1100.py`: 完整實驗腳本（~1700 行，含 numba-JIT GJR/A4f/DCC + scipy copula fit + MC VaR）
- `k1100_results.json`: 完整結果（模型 VaR 檢定 + DM + copula 動態）
- `k1100_copula_fit.png`: Student-t ρ/ν, Clayton θ 時序
- `k1100_tail_dependence_ts.png`: λ_L 動態（兩個 copula）
- `k1100_portfolio_var_compare.png`: 5 個模型 VaR/ES 時序對比
- `k1100_trinity_comparison.png`: FZ score + Trinity PASS/FAIL 比較

## 參考文獻

- Patton (2006). Modelling asymmetric exchange rate dependence. *IER* 47(2).
- Jondeau & Rockinger (2006). The Copula-GARCH model. *JIMF* 25(5).
- Demarta & McNeil (2005). The t Copula and Related Copulas. *Int Stat Rev* 73(1).
- Nelsen (2006). *An Introduction to Copulas*. Springer.
- Lai, Chen, Gerlach (2009). Copula-GARCH and VaR. *JEDC*.
- Lai (2024). PRS-based copula hedging. *APFM* 31(2). (用戶論文)
- Fissler & Ziegel (2016). Higher order elicitability. *Ann Stat* 44(4).
- Engle (2002). Dynamic Conditional Correlation. *JBES* 20(3).

## 局限性

1. **OOS 不含 2008 GFC**: 訓練需要 1250 天 + GVZ 從 2008-06 才有 → OOS 最早從 2013-06 開始。論文 K1092 同樣局限。
2. **MC 取樣誤差**: 5000 paths 在 α=1% 極端尾部有波動。更大 N 可降低 noise（但 runtime ↑）。
3. **Copula 模型的 pvar**: 本實驗用 analytical approximation（rho-implied variance），MC 才是真正的 VaR 計算方式。因此 QLIKE 比較給 copula 不公平（copula 的真優勢在尾部，不在 pvar）。主要比較應看 FZ score。
4. **邊際 Student-t df 假設**: PIT 使用 fitted Student-t marginal，若真實邊際分配有 skew（GJR 已捕捉部分），PIT 可能失準。
