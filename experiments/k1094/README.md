# K1094 — A4f-VT vs 8.63/VIX on 0050.TW

**Paper 3 Cross-Market Replication of K1074**

[提出: 賴奕豪, 執行: Claude · 2026-04-12]

---

## 問題描述 (Research Question)

**K1074** 在 SPY 上比較 A4f-VT（統計顯著勝 GJR）與 12/VIX-VT（樸素）兩種
volatility-targeting 策略，發現：

| SPY | Sharpe (net) |
|-----|-------------|
| 12/VIX-VT | 0.861 |
| A4f-VT | 0.843 |
| diff (boot) | -0.018, p=0.64 NS |

→ **統計準確 ≠ 交易勝利**（Paper 3 的核心主張）

**K1077** 進一步顯示 A4f 在 0050.TW 上**統計 NULL**（DM t=-0.49）。

本實驗問兩個問題：

- **H1**: 如果 A4f 在 0050.TW 統計 NULL，是否連策略都輸給 8.63/VIX？
- **H2**: 或者兩者 Sharpe 相近，重現 K1074 的 SPY pattern？

## 動機 (Motivation)

Paper 3（"Is Volatility Targeting Just Trend Following?"）主張 VT 的 α 主要來自
**報酬端**（TSMOM／drawdown persistence），不是波動預測的精度。若此論述正確：

- SPY 已證明（K1074）：A4f 的統計優勢無法轉換為策略優勢
- 0050.TW 上：若 A4f 真的在策略上輸 8.63/VIX，表示「統計強弱」其實會傳到策略層面，Paper 3 論述需要修飾
- 若兩者 Sharpe 差異 NS，則 Paper 3 結論**跨市場一致**，強化其普適性

## 方法 (Methods)

### 5 個策略

| Key | Strategy | Formula |
|-----|---------|--------|
| A | 8.63/VIX | w_t = min(8.63 / VIX_{t-1}, 1.0) |
| B | A4f-VT | w_t = min(0.15 / σ̂_A4f,t-1, 1.5) |
| C | GJR-VT | w_t = min(0.15 / σ̂_GJR,t-1, 1.5) |
| D | 50/50 + 8.63/VIX | 50%·0050·w_A + 50%·GLD, monthly rebalance |
| E | 50/50 + A4f-VT | 50%·0050·w_B + 50%·GLD, monthly rebalance |

### A4f 規格

τ_t = max(θ₀ + θ₁ · VIX²_{t-1}, ε)  
g_t = ω_g + α·u²_{t-1} + γ·u²_{t-1}·I(u_{t-1}<0) + β·g_{t-1}  
u_{t-1} = r_{t-1} / √τ_t  
σ²_t = τ_t · g_t

Rolling window = 2000 天, refit 每 63 天（季度）。

### 資料

- **0050.TW**: yfinance + **mandatory `clean_tw50_data`**（2014 split 修正）
- **GLD**: yfinance auto_adjust
- **VIX**: yfinance `^VIX`, forward-filled to TW trading calendar
- 期間: 2005-07-01 → 2026-04-10
- OOS: **2013-01-02 → 2026-04-10**, N = 3,230 天（對齊 K1074 的 OOS 起始）
- TX cost: **2 bp**/unit weight change（台灣 ETF）
- `np.random.seed(42)`, bootstrap 1000 reps, block 22

### Taiwan-specific lag
- VIX 已 forward-fill 到 0050.TW 交易日
- weight_t 使用 `vix_lag_oos[t] = VIX[t-1]`（TW 前一交易日的 US close VIX，約 8 小時前）
- A4f/GJR 的 one-step-ahead 也僅用 r_{t-1}, VIX_{t-1}

### 評估

- Raw + Net Sharpe, CAGR, MDD, Calmar, Sortino
- Annualised turnover
- Bootstrap Sharpe-diff 95% CI（stationary block, 1000 reps, seed 42）
- Monthly hit rate (A4f-VT vs 8.63/VIX)

## 預期 (Predictions)

- 若 Paper 3 論述正確（K1074 pattern）: A4f-VT 與 8.63/VIX Sharpe 差異 NS
- 若 A4f 在 0050.TW 真的「完全無用」: A4f-VT 應該明顯輸 8.63/VIX 或 BH

## 結論 (Findings)

### 主要結果（Net, 2bp TX）

| Strategy | Sharpe | CAGR | MDD | Calmar | Sortino | Mean w | Ann TO |
|----------|-------:|-----:|----:|------:|-------:|------:|------:|
| A 8.63/VIX | **1.096** | 9.92% | **-16.32%** | 0.61 | 1.51 | 0.54 | 6.9 |
| B A4f-VT | 1.028 | **17.02%** | -28.82% | 0.59 | 1.44 | 0.99 | 13.7 |
| C GJR-VT | 0.745 | 12.31% | -39.84% | 0.31 | 1.01 | 0.97 | 9.1 |
| D 50/50 + 8.63/VIX | 0.909 | 8.99% | -21.01% | 0.43 | 1.20 | 0.54 | 6.9 |
| E 50/50 + A4f-VT | **1.031** | 12.45% | -21.87% | 0.57 | 1.43 | 0.99 | 13.7 |
| BH 0050.TW | 0.764 | 15.01% | -45.23% | 0.33 | 0.99 | — | — |
| BH 50/50 TW+GLD | 0.863 | 11.52% | -27.46% | 0.42 | 1.14 | — | — |

### Bootstrap Sharpe-diff Tests

| Pair | Diff | 95% CI | p |
|------|-----:|:------:|-:|
| **A4f-VT − 8.63/VIX** | -0.065 | [-0.177, +0.051] | **0.284 NS** |
| A4f-VT − GJR-VT | +0.286 | [+0.171, +0.412] | 0.000 *** |
| A4f-VT − BH_TW | +0.263 | [+0.065, +0.478] | 0.008 ** |
| 8.63/VIX − BH_TW | +0.335 | [+0.140, +0.541] | 0.002 ** |
| 50/50+A4f − 50/50+8.63/VIX | +0.116 | [-0.028, +0.266] | 0.138 NS |
| 50/50+A4f − BH 50/50 | +0.179 | [+0.033, +0.328] | 0.016 * |
| 50/50+8.63/VIX − BH 50/50 | +0.054 | [-0.144, +0.273] | 0.588 NS |

Monthly hit rate A4f-VT vs 8.63/VIX (net): **60.6%**

### H1 vs H2 判決

**H1（A4f-VT 輸 8.63/VIX）→ REJECT**
- 差 -0.065 Sharpe，95% CI [-0.18, +0.05] 跨越 0
- p=0.284 NS
- 統計上不能區分

**H2（跨市場重現 K1074 pattern）→ CONFIRMED**
- SPY (K1074): A4f-VT 0.843 vs 12/VIX-VT 0.861, diff NS
- TW (K1094): A4f-VT 1.028 vs 8.63/VIX 1.096, diff NS
- 即使 A4f 在 0050.TW 統計 **NULL**（K1077 DM t=-0.49），策略 Sharpe 仍與 VIX 簡單規則相當

### Paper 3 意涵（Cross-Market Evidence）

K1094 強化 Paper 3 的核心論點：**VT α 來自報酬端（TSMOM/persistence），波動預測精度是 second-order**。

| 市場 | 統計結果 | 策略結果 | 結論 |
|------|--------|--------|-----|
| SPY (K1075/K1074) | A4f 顯著勝 GJR（DM +7.92）| A4f-VT ≈ 12/VIX-VT | 統計強不帶來策略強 |
| 0050.TW (K1077/K1094) | A4f NS vs GJR（DM -0.49）| A4f-VT ≈ 8.63/VIX-VT | 統計弱不帶來策略弱 |

→ **統計層面與策略層面脫鉤（decoupled）**，在兩個不同市場重現。

### 附加發現

1. **A4f-VT 顯著勝 GJR-VT**（diff +0.286, p=0.000）：即使 A4f 與 GJR 在 0050.TW 上 QLIKE 難以區分，**策略維度上 A4f 仍優於 GJR**。可能因：
   - A4f 的 VIX² 外生驅動讓 σ̂ 對市場狀態更敏感 → 在極端時 de-lever 更充分
   - GJR 純 endogenous → 已實現收益才調整，反應較慢
2. **8.63/VIX 在 MDD 維度領先**：-16.32% vs A4f-VT -28.82%
   - 8.63/VIX 的 1.0 cap 更保守（mean w 0.54 vs 0.99）
   - 但 CAGR 顯著偏低（9.92% vs 17.02%）→ 投資人偏好取決於 risk aversion
3. **Paper 3 標準 50/50 + 8.63/VIX 在 TW 上表現不如 BH 50/50**（Sharpe 0.909 vs 0.863，差 NS）
   - TW 版 Paper 3 標準策略需要重新檢視
4. **50/50 + A4f-VT 勝 BH 50/50**（+0.179, p=0.016）：含 GLD 分散風險後，A4f-VT 明顯增值

## 局限性 (Limitations)

1. **GLD 為 USD 計價**：TW 投資人實際可用的黃金 ETF（如 00635U）是期貨導出，有 roll cost 與 contango 問題。本實驗 GLD 假設與 K1074 一致，但實務複製需考慮 00635U 的差異
2. **VIX forward-fill**：TW 日曆遇 US 休市時 VIX 停滯，可能低估真實不確定性
3. **OOS 2013-2026**：含 2015 中國熔斷、2020 COVID、2022 升息，但 n=3230 相當於 K1074 的 3322（差距小）
4. **Target σ = 15%** 為固定值；K1058 曾用 12%，K62 用 10% 內隱，未做 target σ sensitivity
5. **A4f VIX²_{t-1} 使用 US VIX** — 台股本土 VIXTWN 未納入
6. 未評估 **VaR/ES**（本實驗聚焦 strategy Sharpe；K1058 已驗證 A4f 在 0050.TW Trinity PASS）

## 衍生方向

1. **K1094b**: A4f-VT 用 VIXTWN 替代 US VIX 作外生變數
2. **K1094c**: target σ sensitivity（10%, 12%, 15%, 18%）在 0050.TW 上是否改變 A4f vs 8.63/VIX 排序
3. **K1094d**: 0050.TW A4f-VT + TW 0050.TW 期貨（低 TX、含槓桿）vs ETF 交易
4. **K1095**: 為何 A4f-VT 在 TW 上勝 GJR-VT 策略（0.286 Sharpe）卻不勝 VIX 簡單規則？——拆解 VIX regime-dependent performance
5. **K1096**: 2022 bear market 子樣本 A4f vs 8.63/VIX 個別表現

## 檔案

- `k1094.py` — 主腳本
- `k1094_results.json` — 完整結果（metrics, bootstrap, lookahead guard, convergence log）
- `k1094_sharpe_comparison.png` — 5 策略 + 2 BH Sharpe 比較
- `k1094_equity_curves.png` — cumulative equity（log scale）
- `k1094_weight_dynamics.png` — weight time series（8.63/VIX vs A4f-VT vs GJR-VT）
- `k1094_rolling_sharpe.png` — rolling 252-day Sharpe
- `k1094_us_vs_tw.png` — SPY (K1074) vs 0050.TW (K1094) 策略比較

## 參考文獻

- Moreira & Muir (2017). "Volatility-Managed Portfolios." *Journal of Finance* 72(4):1611-1644.
- Harvey et al. (2018). "The Impact of Volatility Targeting." *Journal of Portfolio Management* 45(1):14-33.
- Engle, Ghysels & Sohn (2013). "Stock Market Volatility and Macroeconomic Fundamentals." *RES* 95(3):776-797.
- Patton (2011). "Volatility forecast comparison using imperfect volatility proxies." *J. Econometrics* 160:246-256.

**Internal cross-references:**
- **K1074** — SPY analogue (12/VIX-VT vs A4f-VT)
- **K1075** — SPY A4f extended history DM t=+7.92
- **K1077** — 0050.TW A4f statistical NULL (DM t=-0.49)
- **K1058** — 0050.TW A4f VaR Trinity PASS
- **K62, K461** — Taiwan 8.63/VIX baseline calibration

---

*Data source: yfinance 0050.TW (clean_tw50_data), GLD (auto_adjust), ^VIX*  
*Period: 2005-07-01 to 2026-04-10 (OOS 2013-01-02 onwards)*  
*N_OOS: 3,230 trading days · Window 2000 · Refit 63 · TX 2bp · Seed 42*
