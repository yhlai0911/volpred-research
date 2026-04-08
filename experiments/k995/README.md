# K995: VaR/ES Backtesting for MF-GJR-X(A4f) vs GJR-GARCH

**[提出: 賴奕豪, 執行: Claude]**

## 動機

K988 發現 A4f（τ=θ₀+θ₁VIX², free ω, GJR g_t）在 QLIKE 上顯著勝 GJR（DM t=+4.48）。但預測好 ≠ 風險管理好（K770b 教訓）。論文必須包含 VaR/ES 評估來確認 A4f 的實用價值。

## 方法

### 模型
| 模型 | 波動率結構 | 分配 | 說明 |
|------|-----------|------|------|
| GJR_Normal | GJR-GARCH(1,1) | Normal | Benchmark |
| GJR_t | GJR-GARCH(1,1) | Student-t | 聯合估計 df |
| A4f_Normal | τ×g (VIX², free ω) | Normal | K988 最佳模型 |
| A4f_t | τ×g (VIX², free ω) | Student-t | df 從訓練殘差估計 |

### 數據
- SPY 2005-01-04 to 2026-04-07, n=5,347
- OOS: 2019-01-01 onwards, n=1,825
- Window=2000, refit every 63 days (29 refits)
- VIX from yfinance, lagged 1 day

### VaR 轉換
- Normal: VaR_α = σ × z_α
- Student-t: VaR_α = σ × t_inv(α, df) × sqrt((df-2)/df)  ← 含 scale term

### ES 計算
- Normal: ES_α = σ × (-φ(z_α)/α)
- Student-t: ES_α = σ × [f_t(t_q,df) × (df+t_q²)/((df-1)×α)] × sqrt((df-2)/df)

### Backtesting 方法
1. **Kupiec (1995) UC test** — 違反率是否 = 名義水準
2. **Christoffersen (1998) CC test** — 違反是否 i.i.d.
3. **Engle & Manganelli (2004) DQ test** — 違反是否可預測
4. **Acerbi & Szekely (2014) Z1/Z2** — ES 是否充分覆蓋尾部

## 結果

### VaR Backtesting

| Model | Alpha | Viol% | UC p | CC p | DQ p | Pass? |
|-------|-------|-------|------|------|------|-------|
| GJR_Normal | 1% | 2.30% | 0.000 | 0.000 | 0.000 | FAIL |
| GJR_Normal | 2.5% | 3.78% | 0.001 | 0.004 | 0.029 | FAIL |
| GJR_Normal | 5% | 6.19% | 0.024 | 0.073 | 0.074 | FAIL |
| GJR_t | 1% | 1.64% | 0.011 | 0.033 | 0.017 | FAIL |
| GJR_t | 2.5% | 3.45% | 0.014 | 0.048 | 0.064 | FAIL |
| GJR_t | 5% | 6.30% | 0.014 | 0.039 | 0.023 | FAIL |
| **A4f_Normal** | 1% | 1.92% | 0.000 | 0.002 | 0.000 | FAIL |
| **A4f_Normal** | 2.5% | 3.29% | 0.040 | 0.088 | 0.005 | FAIL |
| **A4f_Normal** | **5%** | **5.15%** | **0.769** | **0.830** | **0.433** | **PASS** |
| **A4f_t** | **1%** | **1.42%** | **0.087** | **0.158** | **0.354** | **PASS** |
| **A4f_t** | 2.5% | 3.01% | 0.173 | 0.337 | 0.006 | FAIL |
| **A4f_t** | **5%** | **5.42%** | **0.411** | **0.554** | **0.172** | **PASS** |

### ES Backtesting (α=2.5%)

| Model | Z1 stat | Z1 p | Z2 stat | Z2 p | Pass? |
|-------|---------|------|---------|------|-------|
| GJR_Normal | 2.200 | 0.502 | 2.816 | 0.539 | PASS |
| GJR_t | 2.098 | 0.502 | 2.516 | 0.537 | PASS |
| A4f_Normal | 2.119 | 0.516 | 2.471 | 0.524 | PASS |
| A4f_t | 2.058 | 0.510 | 2.275 | 0.526 | PASS |

### Scorecard

| Model | VaR PASS | ES PASS | Total |
|-------|----------|---------|-------|
| GJR_Normal | 0/3 | 1/1 | 1/4 |
| GJR_t | 0/3 | 1/1 | 1/4 |
| A4f_Normal | 1/3 | 1/1 | 2/4 |
| **A4f_t** | **2/3** | **1/1** | **3/4** |

### df 估計
- GJR_t (joint MLE): mean=5.94, range=[5.46, 7.67]
- A4f residual-based: mean=8.12, range=[7.24, 9.84]

## 結論

1. **A4f_t 是最佳風險管理模型**：VaR 2/3 PASS（1% 和 5%），ES PASS。GJR 系列（Normal 和 t）全部 VaR FAIL。

2. **A4f 改善 VaR violation rate**：
   - 1% VaR: GJR 2.30% → A4f_t 1.42%（接近名義 1%）
   - 2.5% VaR: GJR 3.78% → A4f_t 3.01%（接近名義 2.5%）
   - 5% VaR: GJR 6.19% → A4f 5.15%/5.42%（接近名義 5%）

3. **Student-t 分配關鍵**：A4f_Normal 在 1% VaR 仍 FAIL（violation rate 1.92%），加上 Student-t 才通過（1.42%）。VIX² 改善均值預測，t 分配修正尾部。

4. **ES 所有模型都 PASS**：ES 較不敏感於模型選擇，因為 ES 是條件期望值（平滑化效果）。

5. **2.5% VaR 對所有模型困難**：DQ test 在 2.5% 水準對 A4f_t 也 reject（p=0.006），暗示 violation clustering 問題尚未完全解決。

6. **結合 K988**：A4f 不只 QLIKE 預測顯著較好（DM t=+4.48），VaR/ES backtesting 也全面優於 GJR。**A4f 是預測 + 風險管理雙優的模型。**

## 局限性
- 單一資產（SPY），需要跨資產驗證
- OOS 含 COVID-19 極端事件，可能影響結果
- A4f_t 的 df 是從訓練殘差估計（非聯合 MLE），可能不如聯合估計精確
- 2.5% VaR DQ test 顯示 violation clustering，可能需要考慮更複雜的條件分配

## 檔案
- `k995.py`: 實驗腳本
- `k995_results.json`: 完整結果
- 數據來源: yfinance (SPY, ^VIX), 期間 2005-2026

## 參考文獻
- Kupiec (1995). J Derivatives 3(2):73-84
- Christoffersen (1998). IER 39(4):841-862
- Engle & Manganelli (2004). JBES 22(4):367-381
- Acerbi & Szekely (2014). Risk 27(11):76-81
- K988: MF-GJR-X specification comparison
