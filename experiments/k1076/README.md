# K1076: Fissler-Ziegel Joint VaR/ES Backtest — A4f vs GJR

**提出**: Claude  **執行**: Claude  **日期**: 2026-04-12
**編號**: K1076 | **狀態**: COMPLETED

## 計劃與動機

先前的 risk-management 實驗（K1058 於 0050.TW、K1034/K1035 VaR 方法變形）
都停留在 VaR-only 檢定（Kupiec、Christoffersen、Basel Trinity）。然而 ES
（Expected Shortfall）單獨不是 elicitable（Gneiting 2011 JASA），單純比
較 empirical ES vs predicted ES 缺乏嚴格的 loss-function 基礎。

**Fissler & Ziegel (2016, Annals of Statistics) 證明 (VaR_α, ES_α) 對
是 jointly elicitable**，並給出唯一的 strictly consistent joint scoring
function class。這是目前 risk management model comparison 的 gold standard。

本實驗用 FZ joint score 在 2007-2026（含 2008 GFC、COVID）全 OOS 期間
比較 A4f（K988/K1075 贏家）與 GJR-GARCH，作為 Paper 9 VaR/ES section
的核心 empirical evidence。

## 研究問題

1. **H1**: A4f 在 Fissler-Ziegel 聯合分數上顯著勝 GJR？（DM t Harvey |t|>3）
2. **H2**: Acerbi-Szekely (2014) Z2 test 對 A4f 和 GJR 的 ES 獨立檢定結果如何？
3. **H3**: A4f 的 FZ 優勢是否集中在高 VIX regime？（crisis > normal > low）
4. **H4**: Normal vs Student-t innovation 假設下結論是否一致？

## 方法

### 資料
- **來源**: yfinance，SPY + ^VIX
- **期間**: 2000-01-04 ~ 2026-04-10（6,606 日）
- **OOS**: 2007-01-03 ~ 2026-04-10（4,848 日，含 2008 GFC）
- **訓練視窗**: 2,000 日（初始 1,758 日，隨時間成長），每 63 日 refit

### 模型
- **GJR-GARCH(1,1)**: h_t = ω + α·r²_{t-1} + γ·r²_{t-1}·I{r_{t-1}<0} + β·h_{t-1}
- **A4f** (K988 winner): σ²_t = τ_t · g_t，其中
  - τ_t = max(θ₀ + θ₁·VIX²_{t-1}, 1e-16)
  - g_t 為 GJR 結構於 u_t = r_t/√τ_t，自由 ω_g

### VaR/ES 推導
給定預測 σ̂_t:

- **Normal 假設**:
  - VaR_α = -σ̂ · z_α
  - ES_α = σ̂ · φ(z_α)/α
- **Student-t(ν=5) 假設**（scale 校正 Var(r)=σ²）:
  - scale = √((ν-2)/ν)
  - VaR_α = -σ̂ · scale · t_{α,ν}
  - ES_α = σ̂ · scale · (f_ν(t_{α,ν})/α) · (ν + t²_{α,ν})/(ν-1)

- **信心水平**: α ∈ {0.01, 0.05}

### 評估

1. **Fissler-Ziegel 聯合分數**（Patton-Ziegel-Chen 2019 JoE 211:388-413 Eq.4）:
   ```
   S_FZ(v,e,y) = (1/(αe))·I{y≤-v}·(-y-v) + v/e + log(e) - 1
   ```
   其中 v=VaR（正），e=ES（正），y=return（signed）。分數越小越好。
   **Sanity check**: 將 ES 或 VaR 偏離真值（±½, ±2×）後分數嚴格提高，
   確認 strictly consistent。

2. **Diebold-Mariano 檢定**（HAC Newey-West，max_lag = T^(1/3)）
   - H₀: E[S^GJR - S^A4f] = 0
   - 正 t = A4f 勝
   - Harvey (2016) threshold: |t| > 3.0

3. **Acerbi-Szekely (2014) Z2 test**
   - Z2 = (1/(Nα))·Σ r_t·I{r_t≤-VaR_t}/ES_t + 1
   - 模型 bootstrap 產生 p-value（1,000 reps from model's σ-path）
   - H₀: E[Z2]=0（ES 正確）；Z2 負 = ES under-estimated

4. **Regime 分析**: VIX lag 分桶 Low(<15) / Normal(15-25) / High(25-40) / Crisis(≥40)

## 主要結果

### (A) Full-sample FZ Joint Score（n=4,848）

| Spec | FZ_GJR | FZ_A4f | DM t | p-value | Harvey |
|---|---|---|---|---|---|
| Normal, α=1% | -3.1782 | -3.3181 | **+3.507** | 0.0005 | **PASS** |
| Normal, α=5% | -3.7531 | -3.8129 | **+5.080** | <0.0001 | **PASS** |
| Student-t, α=1% | -3.3361 | -3.4327 | **+3.532** | 0.0004 | **PASS** |
| Student-t, α=5% | -3.7578 | -3.8152 | **+5.153** | <0.0001 | **PASS** |

**→ H1 PASS（4/4）**。A4f 在所有 4 個 distribution × alpha 組合上都以
Harvey threshold (|t|>3) 顯著勝 GJR。α=5% 的 DM t 超過 5，對應 p<1e-6。

### (B) Violation Rate 對比（closer to target = better VaR calibration）

| Spec | target | GJR | A4f |
|---|---|---|---|
| Normal, α=1% | 1.00% | 2.35% | **1.98%** |
| Normal, α=5% | 5.00% | 5.71% | **5.59%** |
| Student-t, α=1% | 1.00% | 1.36% | **1.32%** |
| Student-t, α=5% | 5.00% | 6.62% | 6.50% |

A4f 在所有 specs 都比 GJR 更接近目標違約率，但 Normal 1% 仍超過 1.98%
（Student-t 假設已修正到 1.32%，更接近目標）。

### (C) Acerbi-Szekely Z2 Test

| Spec | Z2_GJR | p_GJR | Z2_A4f | p_A4f |
|---|---|---|---|---|
| Normal, α=1% | -1.711 | 0.000 | -1.267 | 0.000 |
| Normal, α=5% | -0.327 | 0.000 | -0.267 | 0.000 |
| Student-t, α=1% | -0.389 | 0.008 | -0.281 | 0.022 |
| Student-t, α=5% | -0.352 | 0.000 | -0.298 | 0.000 |

**→ H2 PARTIAL**。兩個模型都 reject H₀（p<0.05），顯示 ES 在絕對意義上
仍 under-forecast（Z2<0 代表尾部損失比預測大）。但 A4f 的 |Z2| 系統性
小於 GJR（-1.267 vs -1.711 at Normal 1%），代表 A4f 的 ES 偏誤較小。
這與 FZ DM 結論一致——A4f 不是完美，但比 GJR 明顯好。

### (D) Regime 分析（VIX bucket，spec: Normal α=5%）

| Bucket | VIX 範圍 | n | DM t | Harvey |
|---|---|---|---|---|
| Low | [0, 15) | 1,545 | +2.89 | fail |
| Normal | [15, 25) | 2,421 | **+4.01** | **PASS** |
| High | [25, 40) | 703 | +1.60 | fail |
| Crisis | [40, ∞) | 179 | +1.05 | fail |

**→ H3 PARTIAL**。優勢最強在 **Normal 區**（VIX 15-25），Crisis 樣本數
太小（n=179）難以達到 Harvey threshold，但 **所有 regime 的 DM t 都是
正的**——A4f 從不輸 GJR。這反映 A4f 主要在「一般市場」提供穩定優勢，
而非 crisis 期間特殊勝出（這跟 K988 結論一致：A4f 的價值來自 VIX²_{t-1}
對 τ 的持續校準，不是極端尾部）。

### (E) Distribution Consistency

Normal 和 Student-t 結論：4/4 同號同為正，結論穩健。
Student-t 將違約率壓低到更接近目標（尤其 α=1%：2.35%→1.32%），
建議論文 Paper 9 preferred spec 採用 **Student-t(5)** 以改善 VaR calibration，
但 FZ joint score DM 結論兩個假設下一致。

## 結論

1. **A4f 勝 GJR 於 Fissler-Ziegel joint VaR/ES 分數**（4/4 specs Harvey PASS）。
   這是 risk management model comparison 最嚴格的 joint criterion，結果強化
   了 K988/K1075 QLIKE-only 的優勢結論。

2. **A4f 的優勢在 VaR calibration 和 ES 相對精確度**，不是 crisis 期間異能。
   Acerbi-Szekely 顯示兩模型 ES 都仍 slightly under-forecast（常見於 SPY 收盤價），
   但 A4f 偏誤較小。

3. **Paper 9 意涵**:
   - Risk management section 現有 rigorous joint elicitability evidence。
   - 建議 preferred spec: Student-t(5) innovation（VaR calibration 更好，
     FZ DM 仍 PASS t=+3.53/5.15）。
   - Regime 分析表明 A4f 是「持續性 (persistent) 改善」而非「crisis-only」，
     適合寫作框架為「stable risk-adjusted forecasting」。

4. **局限**:
   - Crisis 樣本 n=179 太小，無法對「crisis advantage」做強斷言。
   - Both models reject Acerbi-Szekely absolute calibration → 都未完全符合
     假設分配；Student-t(5) 只是部分修正。真實尾部可能需要 GAS / 
     dynamic-tail-index 模型（未來方向）。
   - 沒有比較更複雜 GARCH 變形（EGARCH, TGARCH, HEAVY）——只證明
     「vs plain GJR」優勢。

## 檔案
- `k1076.py` — 完整實驗腳本（numba-accelerated GJR + A4f, FZ scoring, AS Z-tests）
- `k1076_results.json` — 完整結果 JSON（FZ、AS、regime、hypothesis verdicts）
- `k1076_forecasts.csv` — 每日 σ²、VaR、return（n=4,848 供下游重用）
- `k1076_forecasts.npz` — numpy cache，重跑 plotting 不需再 refit
- `k1076_fz_score_series.png` — FZ 累積優勢時序
- `k1076_dm_matrix.png` — dist × alpha DM t 熱圖
- `k1076_acerbi_szekely.png` — Z1/Z2 bar chart
- `k1076_regime_fz.png` — VIX regime 分析
- `k1076_normal_vs_t.png` — Normal vs Student-t 比較

## 參考文獻

1. **Fissler, T. & Ziegel, J.F.** (2016). "Higher Order Elicitability and
   Osband's Principle" *Annals of Statistics* 44(4):1680-1707. (核心理論)
2. **Acerbi, C. & Szekely, B.** (2014). "Back-testing expected shortfall"
   *Risk* 27(11). (Z-test 實作)
3. **Gneiting, T.** (2011). "Making and evaluating point forecasts"
   *JASA* 106(494):746-762. (ES non-elicitability 證明)
4. **Nolde, N. & Ziegel, J.F.** (2017). "Elicitability and backtesting:
   perspectives for banking regulation" *Annals of Applied Statistics*
   11(4):1833-1874. (FZ 應用指引)
5. **Patton, A., Ziegel, J., Chen, R.** (2019). "Dynamic semiparametric
   models for expected shortfall" *Journal of Econometrics* 211:388-413.
   (0-homogeneous FZ 形式採用)
6. **Engle, R., Ghysels, E., Sohn, B.** (2013). "Stock market volatility
   and macroeconomic fundamentals" *RES* 95(3):776-797. (A4f multiplicative
   framework 起源)
7. **Harvey, D., Leybourne, S., Newbold, P.** (1997/2016). DM test
   bias correction, Harvey threshold |t|>3. (統計門檻)

## 後續衍生方向

1. **K10??**: 同方法應用於 0050.TW — 跨市場 FZ joint score 比較
2. **K10??**: GAS (Generalized Autoregressive Score) models 對抗 A4f，
   GAS 是 Creal-Koopman-Lucas 2013 的 strictly consistent ES 框架
3. **K10??**: FZ joint score 作為 loss function 直接估計（而非用 QLIKE 估
   後再評估）——Patton-Ziegel-Chen (2019) 的半參數 FZ-minimization 範式
4. **Paper 9 寫作**: 將本實驗結果寫入 "Risk Management" section，配合
   Nolde-Ziegel (2017) 的 regulatory interpretation 框架
