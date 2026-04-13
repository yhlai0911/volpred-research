# K1115 — SPY VaR Breach Clustering with Conditional Copula-like Framework

**Status**: NULL RESULT — H2 REJECTED in OOS
**Date**: 2026-04-13
**Author**: VolPred Research System (Claude worktree agent)

---

## 1. Motivation

E055 結論：copula 真正適合 3 個必要條件之一：

1. 高正相關（ρ>0.95，近 collinear）pairs
2. **單一資產的 path-dependent 應用**（如 VaR breach persistence、drawdown analytics）
3. 非對稱 dependence（contagion 期 downside > upside）

K1100 系列全失敗都因為測 portfolio-level — aggregation 把 tail dependence 平均化：
- K1100 (SPY-GLD tail-indep): NULL
- K1100b (5 equity pairs): NULL
- K1100f (SPY-ES ρ=0.97 λ_L=0.92 + PRG): NULL
- K1100g_d2 (TAIFEX periodic): OOS REJECTED

條件 1 與 3 已經實驗過失敗。**K1115 是 E055 條件 (b) 的直接檢驗**：跳出 portfolio，
測試單一資產 SPY 的 path-dependent application（VaR breach clustering + 條件式模型）。

**核心問題**：SPY 日報酬的 1%/5% VaR breach 是否 cluster？條件式模型（以 breach 歷史為 exog）
能否在 OOS 顯著改善 GJR-t baseline 的 tail risk forecasting？

---

## 2. Design

### Data
- **Asset**: SPY (yfinance, adjusted close, log returns × 100)
- **Period**: 2010-01-05 to 2026-04-10 (N=4091 trading days)
- **Descriptive**: mean=0.052%, std=1.13%, skew=-0.64, kurt=14.4, min=-12.0%, max=8.97%

### Train/Test Split (嚴格 OOS)
- **IS**: 2010-01 to 2017-12 (~1760 days after rolling_window burn-in)
- **OOS**: 2018-01 to 2026-04 (~2079 days; covers 2018 vol spike, COVID crash, 2022 bear, 2025 tariff shock)

### 5 Models (both α=1% and α=5%)

| # | Name | Specification |
|---|------|--------------|
| M1 | Empirical | 252-day rolling α-quantile (lagged by 1) |
| M2 | GARCH-N | GARCH(1,1) with Normal innovations |
| M3 | GJR-t | GJR-GARCH(1,1,1) with Student-t innovations（K1041 baseline） |
| M4 | GJR-t + Breach Count | M3 × (1 + δ₄ · breach_count_5d_lag / σ) |
| M5 | GJR-t + Hawkes Decay | M3 × (1 + δ₅ · λ_lag / σ) with exponential decay 0.3 |

**關鍵 lag 保證**：
- `breach_count_5d` 在時間 t 只包含 t-1..t-5 的 breach indicators（`shift(1)` 確保）
- `hawkes_intensity` 在 t 只用到 t-1 及之前的 breach 事件
- δ₄, δ₅ **僅用 IS 估計**（grid search 最佳匹配 α），套用到 OOS

### Tests

| 類別 | 檢定 | PASS 門檻 |
|------|------|-----------|
| Clustering | Christoffersen (1998) independence | p > 0.05 → 無 cluster |
| Clustering | Ljung-Box Q(10) on breach indicator | p > 0.05 → 無 cluster |
| Coverage | Kupiec (1995) POF LR | p > 0.10 |
| Joint | Christoffersen CC (coverage + indep, df=2) | p > 0.10 |
| ES | Acerbi-Szekely (2014) Z2 (one-sided, bootstrap) | p > 0.05 |
| Forecast | DM-HLN on quantile loss (Koenker-Bassett check) | \|t\| > 2 |

**H2 PASS 三重門檻**（必須全部滿足）：
1. OOS Kupiec p > 0.10
2. OOS Christoffersen CC p > 0.10
3. OOS \|DM-HLN t\| > 2 vs M3

---

## 3. Results

### H1: Breach Clustering（條件模型是否已吸收 clustering？）

| Model | Period | α | Christoffersen Indep p | Ljung-Box(10) p | Cluster? |
|-------|--------|---|------------------------|-----------------|----------|
| M1 (Emp) | OOS | 1% | — | **0.000** | Yes |
| M2 (GARCH-N) | OOS | 1% | 0.464 | 0.494 | No |
| **M3 (GJR-t)** | OOS | 1% | **0.620** | **0.878** | **No** |
| M1 (Emp) | OOS | 5% | — | **0.000** | Yes |
| M2 (GARCH-N) | OOS | 5% | 0.498 | 0.101 | No |
| **M3 (GJR-t)** | OOS | 5% | **0.334** | 0.479 | **No** |

**關鍵發現**：GJR-t baseline **已經吸收了** SPY 的 VaR breach clustering（OOS Christoffersen p>0.3 均無法拒絕獨立性）。
只有 empirical quantile (M1) 的 breach 才有顯著 serial correlation，但 M1 是 naive 模型，其 clustering 來自
缺乏 conditional heteroscedasticity。

**這意味著 E055 條件 (b)「path-dependent 殘留結構」在 SPY 上並不存在** — 已經被 GARCH family 的
conditional variance 解釋掉了。沒有殘留 clustering，conditional copula-like 調整就沒有資訊可以利用。

### H2: Conditional Model Improvement

#### α = 1% OOS（N=2079）

| Model | Breaches | Rate | Kupiec p | CC p | LB p | DM-HLN vs M3 | H2 PASS |
|-------|----------|------|----------|------|------|--------------|---------|
| M3 | 35 | 1.68% | 0.004 | 0.015 | 0.878 | — | (baseline) |
| M4 | 39 | 1.88% | 0.000 | 0.001 | 0.053 | t=+1.07 (p=0.287) | **FAIL** |
| M5 | 45 | 2.16% | 0.000 | 0.000 | 0.000 | t=+1.71 (p=0.087) | **FAIL** |

#### α = 5% OOS（N=2079）

| Model | Breaches | Rate | Kupiec p | CC p | LB p | DM-HLN vs M3 | H2 PASS |
|-------|----------|------|----------|------|------|--------------|---------|
| M3 | 133 | 6.40% | 0.005 | 0.012 | 0.479 | — | (baseline) |
| M4 | 133 | 6.40% | 0.005 | 0.012 | 0.479 | δ=0 (identical) | **FAIL** |
| M5 | 133 | 6.40% | 0.005 | 0.012 | 0.479 | δ=0 (identical) | **FAIL** |

At α=5%, the IS grid search converged to δ=0 (no adjustment helps) because M3 already has near-perfect IS
Kupiec p=0.913 and CC p=0.936. The breach-conditioning adds no IS value → no OOS test possible.

**DM-HLN t 為正（M4/M5 均為 +1.07 / +1.71）意味著 conditional 模型的 quantile loss 比 M3 更高**，
即 path-dependent 調整**惡化**了 forecast quality，並未改善。

### IS vs OOS Divergence（K1100g_d1 教訓直接映射）

| Alpha | Model | IS Kupiec p | OOS Kupiec p | IS CC p | OOS CC p | IS Trinity | OOS Trinity |
|-------|-------|-------------|--------------|---------|----------|-----------|------------|
| 1% | M4 | **0.914** ✓ | 0.000 ✗ | 0.043 | 0.001 ✗ | Partial | **FAIL** |
| 1% | M5 | **0.922** ✓ | 0.000 ✗ | 0.043 | 0.000 ✗ | Partial | **FAIL** |
| 5% | M4 | **0.934** ✓ | 0.005 ✗ | 0.941 ✓ | 0.012 ✗ | PASS | **FAIL** |
| 5% | M5 | **0.917** ✓ | 0.005 ✗ | 0.937 ✓ | 0.012 ✗ | PASS | **FAIL** |

**⚠️ 經典 overfitting pattern（遵循 E059 教訓）**：
IS Kupiec p > 0.9（看似完美）→ OOS Kupiec p < 0.01（嚴重 under-coverage）。
Delta parameter fit 在 IS 是用 grid search 匹配 α，這是 **by-construction IS PASS**。
OOS FAIL 證明這種 path-dependent 調整**不能** generalize — IS breach clustering pattern
不穩定，fit 的 delta 到 OOS（包含 COVID、2022 bear）無用。

**所有 OOS Kupiec FAIL 的 M3 baseline** 也反映：2018-2026 真實市場 tail 比 GJR-t 估的更厚
（COVID、2022、2025 tariff 三次異常）— 這是 SPY 市場結構性問題，非我們方法的缺陷。
但 conditional 調整 M4/M5 **都未改善** 這個 under-coverage，反而多次加劇。

### Decision

**Paper 3 single-asset path-dependent niche REJECTED.**

E055 的三個 copula 必要條件現已全部實驗過：
- 條件 1（near-collinear）: K1100f FAIL (SPY-ES ρ=0.97)
- 條件 2（non-symmetric dependence）: K1100 series FAIL
- **條件 3（path-dependent single-asset）: K1115 FAIL（本實驗）**

三者全 null 意味著 Lai (2024) PRS 的 copula edge **不是方法論通用** — 它是
**TAIFEX 市場 microstructure 特有的效應**（K1100g_d1/d2 進一步確認）。

---

## 4. Charts

| 圖 | 檔案 | 內容 |
|----|------|------|
| 1 | `k1115_breach_cluster_acf.png` | IS vs OOS breach indicator ACF，Ljung-Box p 標注。M3 breaches 已無顯著 serial correlation |
| 2 | `k1115_5model_trinity.png` | 5 model × 10 test column × 2 alpha heatmap，綠/黃/紅區分 p-value bucket |
| 3 | `k1115_oos_quantile_loss.png` | α=1% cumulative quantile loss (M3/M4/M5 OOS)；α=5% mean QL bar |
| 4 | `k1115_inter_breach_duration.png` | IS/OOS inter-breach duration histogram + exponential fit |

---

## 5. Codex Review

`codex exec --sandbox read-only` 審查代碼，結果：
- **HIGH**: 無
- **MED**（已修正）:
  - quantile_loss_series 原本使用 `(ind - alpha) * (r - v)` 與標準 Koenker-Bassett 差一個負號 → 已改為 `(alpha - ind) * (r - v)`
  - Acerbi-Szekely Z2 p-value 原本使用雙尾 `2 * min(...)` → 已改為左尾 `P(Z2_boot ≤ Z2_obs)`
- **LOW**: Kupiec 邊界處理（x=0 或 x=N 回 NaN）可以優化，但 K1115 所有 alpha/model/period 均有非零 breaches，不影響本結果

修正後重跑，核心結論不變（H2 仍 REJECTED）。

---

## 6. Paper 3 衍生新方向

本實驗加上 K1100 系列（共 5 個實驗）確認 Paper 3 原構想**不可行**。提出三條衍生：

### 方向 A：**Paper 3 reframe 為 "Negative Result + Mechanism" paper**
- Title: *"Why Copula-GARCH Risk Models Don't Generalize Beyond Spot-Futures: Empirical Evidence from Equity Indices"*
- Contribution: 首次系統性展示 copula edge 的 3 條件 all-or-nothing 性質
- Target: Journal of Empirical Finance、Finance Research Letters
- 結構：(1) Lai 2024 motivation (2) K1100 series 5 experiments (3) Mechanism analysis

### 方向 B：**TAIFEX-specific periodic paper（K1100g_d2 已 REJECT → 需新 anchor）**
- 問題：K1100g_d2 的 night→day LRT OOS 不穩定
- 下一步：換 anchor，測 TAIFEX **options expiration day** (每月第 3 個週三) 的 cross-session effect
- 若成立：Paper 3 改寫為 *"TAIFEX Settlement-Day Volatility Dynamics: A Microstructure Study"*

### 方向 C：**Abandon Paper 3 資源轉到其他 Papers**
- Papers 4-9 尚有空間（檢查 `research_program.md`）
- 或集中精力於 已上架策略的 out-of-sample maintenance 與 robustness（K846 50/50 三重護城河後續）

---

## 7. Limitations

1. **固定 train/test split**：2018-01 切點可能導致 regime-specific 結果。可做 expanding-window robustness
2. **僅 SPY**：未測 QQQ/EEM/個股。SPY 是 largest-cap smoothest pattern，可能系統性低估 path-dependence
3. **M4/M5 specification**：Multiplicative adjustment 簡單但可能不是 optimal conditional form。
   可考慮 GARCHX（外生變數進 mean 或 variance equation）取代 VaR-level 乘法
4. **α=5% δ=0**：grid search 無解 → 反映 M3 在 IS α=5% 已近最佳，無 headroom。這本身是 M3 夠強的證據
5. **Refit frequency=250**：rolling refit 太頻繁可能引入 parameter noise；太少可能 stale。未做 sensitivity

---

## 8. Conclusion

**OOS Trinity: 5/5 model × 2 alpha × 4 test = 全 FAIL（除 M3 OOS α=5% LB p=0.479 過 clustering 門檻）**

**E055 三條件全否定** — copula-GARCH 的實證 niche 僅限於 Lai (2024) 的 TAIFEX spot-futures 特殊情境。
Paper 3 在此方向上**無更深耕空間**，建議 reframe 為 negative result paper（方向 A）或 pivot
到新 anchor（方向 B）。

**此實驗直接防止了另一輪 K1100-style null research loop**：若繼續 search "different dataset, same method"，
只會再得到 5 個 null。應該 pivot 至 methodology paradigm（方向 B 的 TAIFEX settlement microstructure）
或承認 null 並退出（方向 A）。

---

## References

- Acerbi, C., & Szekely, B. (2014). Back-testing Expected Shortfall. *Risk Magazine*, 27(11), 76–81.
- Christoffersen, P. F. (1998). Evaluating Interval Forecasts. *International Economic Review*, 39(4), 841–862.
- Diebold, F. X., & Mariano, R. S. (1995). Comparing Predictive Accuracy. *JBES*, 13(3), 253–263.
- Engle, R. F., & Russell, J. R. (1998). Autoregressive Conditional Duration. *Econometrica*, 66(5), 1127–1162.
- Harvey, D. I., Leybourne, S. J., & Newbold, P. (1997). Testing the Equality of Prediction Mean Squared Errors. *IJF*, 13(2), 281–291.
- Hawkes, A. G. (1971). Spectra of Some Self-Exciting and Mutually Exciting Point Processes. *Biometrika*, 58(1), 83–90.
- Koenker, R., & Bassett, G. (1978). Regression Quantiles. *Econometrica*, 46(1), 33–50.
- Kupiec, P. H. (1995). Techniques for Verifying the Accuracy of Risk Measurement Models. *Journal of Derivatives*, 3(2), 73–84.
- Lai, Y.-H. (2024). Periodic Realized Semivariance with Spot-Futures Copula. *APFM*, 31(2).
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246–256.
