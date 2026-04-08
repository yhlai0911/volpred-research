# K988: Multiplicative GARCH-X vs GARCH-MIDAS(VIX) Specification Comparison

## 動機

K889 引入了 MF-GJR(VIX) 模型：$\sigma^2_t = \tau_t \times g_t$，聲稱基於 GARCH-MIDAS。賴教授指出兩個關鍵問題：

1. **不是 GARCH-MIDAS**：τ 是日頻的且只用單一 lag VIX，沒有 MIDAS Beta 加權結構
2. **g 方程分母不一致**：估計用 τ_t（同期），OOS 用 τ_{t-1}（前期）
3. **E(g) ≠ 1 問題**：因 VIX² 系統性高估 realized variance（VRP > 0），強制 ω = 1-α-γ/2-β（即 E(g)=1）不合理

本實驗系統性地比較不同設定的 multiplicative model，釐清最佳規格。

## 模型設定

### 概念框架

- **τ_t**（外生波動率水準因子）：由 VIX 決定市場的波動率環境（不是「長期成分」）
- **g_t**（內生動態因子）：捕捉在給定外生環境下的 GARCH 動態（不是「短期成分」）
- **乘法含義**：σ² = τ × g → VIX 設定波動率的 scale，GARCH 在這個 scale 內做動態
- **VRP 連結**：當 τ ≈ VIX²_{t-1} 時，g = r²/τ ≈ realized/implied variance ratio，g 的動態就是 VRP 的時序動態

### Part A: Multiplicative GARCH-X（日頻 τ，無 MIDAS）

| # | 名稱 | τ_t 定義 | g_t 分母 | ω 約束 |
|---|------|---------|---------|--------|
| A1 | K889-original | exp(θ₀+θ₁ log VIX_{t-1}) | estimation: τ_t, OOS: τ_{t-1} | ω = 1-α-γ/2-β |
| A2 | consistent_tau_t | 同上 | τ_t（兩邊一致） | ω = 1-α-γ/2-β |
| A3 | consistent_tau_t1 | 同上 | τ_{t-1}（兩邊一致） | ω = 1-α-γ/2-β |
| A4 | vix_squared | θ₀ + θ₁ VIX²_{t-1} | τ_t | ω = 1-α-γ/2-β |
| A5 | vix_level | exp(θ₀ + θ₁ VIX_{t-1}) | τ_t | ω = 1-α-γ/2-β |
| A2f | free_omega | exp(θ₀+θ₁ log VIX_{t-1}) | τ_t | **ω 自由估計** |
| A4f | vix2_free_omega | θ₀ + θ₁ VIX²_{t-1} | τ_t | **ω 自由估計** |

### Part B: Proper GARCH-MIDAS(VIX)（Beta 加權 MIDAS）

| # | 名稱 | τ 定義 | K (lags) |
|---|------|-------|----------|
| B1 | MIDAS_K22 | m + θ Σ φ_k(ω₁,ω₂) log(VIX_{i-k}) | 22 (月) |
| B2 | MIDAS_K65 | 同上 | 65 (季) |
| B3 | MIDAS_K125 | 同上 | 125 (半年) |

### Benchmark
- B0: GJR-GARCH(1,1)

## 方法

- **資產**: SPY (2005-2026, yfinance)
- **VIX**: ^VIX (yfinance), lagged 1 day
- **Window**: 2000 trading days
- **OOS**: 2019-01-01 to 2026-04-07 (1825 obs)
- **Refit**: 每 63 天
- **評估**: QLIKE on r² (Patton 2011), DM test (Harvey |t| > 3.0), Spearman rank ρ

## 結果

### 完整排名（K988 + K988b 合併，17 個規格）

| Rank | Model | QLIKE | DM t vs GJR | 類型 |
|------|-------|-------|-------------|------|
| 1 | **A4f_vix2_free_omega** | **-8.3608** | **+4.48** | GARCH-X, VIX², free ω |
| 2 | A4_vix_squared | -8.3577 | +4.17 | GARCH-X, VIX², ω 約束 |
| 3 | A2_consistent_tau_t | -8.3564 | +3.46 | GARCH-X, log-exp, τ_t |
| 4 | A4n_vix2_samplenorm | -8.3549 | +3.55 | GARCH-X, VIX², 方案B |
| 5 | A2n_logexp_samplenorm | -8.3541 | +3.26 | GARCH-X, log-exp, 方案B |
| 6 | B1_MIDAS_RW_K22 | -8.3538 | +3.37 | MIDAS rolling, K=22 |
| 7 | A2f_free_omega | -8.3531 | +3.30 | GARCH-X, log-exp, free ω |
| 8 | A3_consistent_tau_t1 | -8.3522 | +3.25 | GARCH-X, τ_{t-1} 分母 |
| 9 | A1_K889_original | -8.3501 | +3.17 | K889 bug 重現 |
| 10 | A3f_tau_t1_free_omega | -8.3495 | +3.09 | GARCH-X, τ_{t-1}, free ω |
| 11 | B2_MIDAS_RW_K65 | -8.3417 | +3.15 | MIDAS rolling, K=65 |
| 12 | B3_MIDAS_RW_K125 | -8.3373 | +3.26 | MIDAS rolling, K=125 |
| 13 | A5_vix_level | -8.3317 | +1.84 | GARCH-X, VIX level |
| 14 | C1_MIDAS_FS_K6 | -8.3092 | +3.55 | MIDAS fixed-span, K=6m |
| 15 | C3_MIDAS_FS_K24 | -8.3074 | +2.85 | MIDAS fixed-span, K=24m |
| 16 | C2_MIDAS_FS_K12 | -8.3019 | +2.33 | MIDAS fixed-span, K=12m |
| 17 | B0_GJR | -8.2772 | ref | Benchmark |

### VRP 驗證

| 指標 | Spearman ρ | p-value |
|------|-----------|---------|
| g_proxy (A3f) vs VRP | **0.630** | 0.000 |
| g_proxy (A2n) vs VRP | **0.618** | 0.000 |
| g_proxy (A4n) vs VRP | **0.545** | 0.000 |
| Raw r²/VIX² vs VRP | 0.173 | 0.000 |

## 結論

### 規格比較
1. **VIX² 是最佳 τ 函數型式**：維度直接對應 variance（VIX~σ → VIX²~σ²），DM t = +4.48 最顯著
2. **τ_t 分母 > τ_{t-1} 分母**：A2 > A3（修正 off-by-one 後翻轉），原論文 Engle et al. (2013) Eq.4 的邏輯在日頻設定下仍成立
3. **Free omega 改善 VIX² 模型**（A4f > A4），但對 log-exp 模型無效（A2f < A2）
4. **方案 B（sample mean 標準化）表現佳**：保持 ω=1-α-γ/2-β 簡潔性，QLIKE 接近 free omega
5. **K889 的估計/OOS 不一致確實損失績效**：A1 < A2

### GARCH-X vs GARCH-MIDAS
6. **日頻 GARCH-X 全面勝過 GARCH-MIDAS**：
   - Rolling window MIDAS (B1-B3) < GARCH-X (A2/A4)
   - Fixed-span MIDAS (C1-C3) 更差（QLIKE -8.30 vs -8.36）
   - 原因：VIX 資訊集中在近期，MIDAS 加權稀釋信號；月頻 τ 丟失日頻資訊

### VRP 連結（新發現）
7. **g 成分高度追蹤 VRP 動態**：ρ = 0.55-0.63，遠高於原始 r²/VIX² 比值（ρ = 0.17）
8. **GARCH 動態大幅提升 VRP 捕捉**：從 0.17 → 0.63，乘法結構 + 自回歸 = VRP 的 AR 建模
9. **自洽框架**：E(g)=1 約束下，τ 的估計自動校正 VRP → g 反映 VRP 偏離其長期均值的動態

## 局限性

- 僅測 SPY，需跨資產驗證（QQQ/EEM/0050.TW/GLD）
- 未做 VaR/ES 評估
- Refit 每 63 天，非每日
- 未做 VaR/ES 評估

## 檔案

- `k988.py` — 主實驗腳本（A1-A5, A2f, A4f, B0-B3）
- `k988b_supplement.py` — 補充實驗（A3f, A2n, A4n, C1-C3, VRP 驗證）
- `k988_results.json` — 主實驗結果
- `k988b_results.json` — 補充實驗結果
- `k988_specification_comparison.png` — 比較圖表

## 數據來源

yfinance: SPY (2005-2026), ^VIX (2005-2026). n=5347, n_oos=1825.

## 參考文獻

- Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.
- Engle & Rangel (2008). Spline-GARCH. RFS 21(3):1187-1222.
- Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility. JBES 33(3):338-358.
- Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
- Harvey et al. (2016). t > 3.0 threshold.
- Bollerslev, Tauchen & Zhou (2009). Expected Stock Returns and Variance Risk Premia. RFS 22(11):4463-4492.
